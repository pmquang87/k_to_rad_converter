"""Tests for the CARDSTACK PIPELINE batch (k2rad), group K3 - the property
cards:

  K-30  a *SECTION_SOLID whose elements are ALL 4- / 10-node tets (ELFORM
        10 / 13, every element a /TETRA4 or /TETRA10, not ALE, not cohesive)
        writes /PROP/SOLID Isolid 1 instead of Isolid 14 (``tet_isolid1``,
        default ON, ``--no-tet-isolid1``). The hourglass-split emitter,
        ``writer/mesh._effective_solid_isolid`` and the LAW115 gate follow the
        emitted value; the /PRELOAD formulation check does not judge a tet
        by its property cell (the hex-measured stable set), with or without
        the opt-out: the starter runs every tet group at Isolid 1. A
        section with a /BRICK (hex, wedge, pyramid) keeps 14; a tet section
        written 17 (ELFORM 2 / 16) keeps 17
  K-31  a *SECTION_SHELL whose parts are all LAW1, NIP != 1, with no
        *INITIAL_STRESS_SHELL / *INITIAL_STRAIN_SHELL record, on a deck that
        writes no /THERM_STRESS, writes /PROP/SHELL N = 0 instead of
        max(2, NIP) (``law1_shell_global_n``, default ON,
        ``--no-law1-shell-global-n``). NIP 1 keeps N 2, which the starter
        still switches to N = 0 with WARNING 1084
  K-32  the ELFORM 16 log text, the *PART_CONTACT OPTT advice and the SHRF
        note (text only, the .rad bytes do not move)
  K-33  the default solid hourglass sentence (text only)

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_7.py (and one deck,
b2_ax15, from tests/test_r14_triage_9.py) as MODULES, so no earlier TestCase
is bound in this namespace and none runs twice. The default arms of the
historical-bytes pins in tests/test_r14_triage_8 / _9 that K-30 / K-31 move
are checked there (test_r14_triage_8._k3_default_moves).
"""

import dataclasses
import hashlib
import os
import shutil
import tempfile
import unittest

import test_r14_triage_7 as _t7
import test_r14_triage_9 as _t9

from k2rad.writer import mesh as _mesh
from k2rad.writer.common import (ISHELL_QBAT, ISHELL_QEPH, _elform_to_ishell,
                                 _elform_to_isolid)

_row = _t7._row
_convert = _t7._convert
_dispatch = _t7._dispatch
_has = _t7._has


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── readers ──────────────────────────────────────────────────────────────────

def _prop_rows(starter: str, head: str):
    """The data rows of the card block whose header line IS *head* (the title
    line skipped, comments dropped), up to the next ``/`` card or ``#---``."""
    lines = starter.splitlines()
    i = lines.index(head)
    rows = []
    for ln in lines[i + 2:]:
        if ln.startswith("/") or ln.startswith("#---"):
            break
        if not ln.startswith("#"):
            rows.append(ln)
    return rows


def _isolid(starter: str, prop: int = 1) -> int:
    return int(_prop_rows(starter, f"/PROP/SOLID/{prop}")[0][0:10])


def _itetra10(starter: str, prop: int = 1) -> int:
    return int(_prop_rows(starter, f"/PROP/SOLID/{prop}")[0][40:50])


def _shell_n(starter: str, prop: int = 1) -> int:
    """/PROP/SHELL card 3 field 1 (N, cols 1-10)."""
    return int(_prop_rows(starter, f"/PROP/SHELL/{prop}")[2][0:10])


def _diff_lines(a: str, b: str):
    """The (line_a, line_b) pairs that differ, for two equally long files."""
    la, lb = a.splitlines(), b.splitlines()
    assert len(la) == len(lb), (len(la), len(lb))
    return [(x, y) for x, y in zip(la, lb) if x != y]


# ── decks ────────────────────────────────────────────────────────────────────

_EXPLICIT = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n"
_IMPLICIT = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
             "*CONTROL_TERMINATION\n" + _row(1.0) + "\n")
_ELASTIC = "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
_PLASTIC = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
            + _row(1, 2.7e-9, 72000.0, 0.3, 200.0) + "\n")

#: nodes 1-4 a corner tet, 5-12 a 10 mm cube beside it
_TET_PTS = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0),
            (0.0, 0.0, 10.0))
_CUBE_PTS = ((20.0, 0.0, 0.0), (30.0, 0.0, 0.0), (30.0, 10.0, 0.0),
             (20.0, 10.0, 0.0), (20.0, 0.0, 10.0), (30.0, 0.0, 10.0),
             (30.0, 10.0, 10.0), (20.0, 10.0, 10.0))


def _node_rows(pts, start: int = 1) -> str:
    return "".join(f"{i:>8}{x:>16}{y:>16}{z:>16}\n"
                   for i, (x, y, z) in enumerate(pts, start))


def _elem(eid: int, pid: int, *nodes: int) -> str:
    return "".join(f"{v:>8}" for v in (eid, pid) + nodes) + "\n"


#: the tet as LS-DYNA's collapsed 8-slot hex, n4 repeated
_TET_ROW = _elem(1, 1, 1, 2, 3, 4, 4, 4, 4, 4)
#: the same tet as 4 ids and trailing zeros
_TET_ZEROS_ROW = _elem(1, 1, 1, 2, 3, 4, 0, 0, 0, 0)
#: the cube as element 2 (beside the tet) and as element 1 (alone)
_HEX_ROW = _elem(2, 1, 5, 6, 7, 8, 9, 10, 11, 12)
_HEX1_ROW = _elem(1, 1, 5, 6, 7, 8, 9, 10, 11, 12)
#: a wedge (6 distinct nodes, LS-DYNA's n1 n2 n3 n4 n5 n5 n6 n6 collapse) and
#: a pyramid (5 distinct nodes, n5 repeated) on the cube's nodes, as element
#: 2 (beside the tet) and as element 1 (alone) - both written as a /BRICK
_WEDGE_ROW = _elem(2, 1, 5, 6, 7, 8, 9, 9, 12, 12)
_WEDGE1_ROW = _elem(1, 1, 5, 6, 7, 8, 9, 9, 12, 12)
_PYRAMID_ROW = _elem(2, 1, 5, 6, 7, 8, 9, 9, 9, 9)
_PYRAMID1_ROW = _elem(1, 1, 5, 6, 7, 8, 9, 9, 9, 9)


def _solid_deck(elems: str = _TET_ROW, elform: int = 10,
                mat: str = _ELASTIC, control: str = _EXPLICIT,
                extra: str = "") -> str:
    """Part 1 on *SECTION_SOLID 1 (ELFORM *elform*) and material 1."""
    return ("*KEYWORD\n" + control
            + "*NODE\n" + _node_rows(_TET_PTS + _CUBE_PTS)
            + "*ELEMENT_SOLID\n" + elems
            + "*PART\nsolid\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, elform) + "\n"
            + mat + extra + "*END\n")


_T10_PTS = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0),
            (0.0, 0.0, 10.0), (5.0, 0.0, 0.0), (5.0, 5.0, 0.0),
            (0.0, 5.0, 0.0), (0.0, 0.0, 5.0), (5.0, 0.0, 5.0),
            (0.0, 5.0, 5.0))


def _tet10_deck(elform: int = 10) -> str:
    """ONE 10-node tet (the TEN-NODE *ELEMENT_SOLID format: card 1 EID PID,
    card 2 n1..n10) on *SECTION_SOLID 1."""
    return ("*KEYWORD\n" + _EXPLICIT
            + "*NODE\n" + _node_rows(_T10_PTS)
            + "*ELEMENT_SOLID\n" + f"{1:>8}{1:>8}\n"
            + "".join(f"{i:>8}" for i in range(1, 11)) + "\n"
            + "*PART\ntet10\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, elform) + "\n"
            + _ELASTIC + "*END\n")


_QUAD_PTS = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0),
             (0.0, 10.0, 0.0), (20.0, 0.0, 0.0), (20.0, 10.0, 0.0))


def _shell_deck(nip="5", elform: int = 2, mat: str = _ELASTIC,
                second: str = "", control: str = _EXPLICIT,
                extra: str = "", shrf="", part: str = "") -> str:
    """Quad 1 (part 1, *SECTION_SHELL 1, NIP *nip*, T 1.0) on material 1;
    *second* adds parts / elements of its own."""
    return ("*KEYWORD\n" + control
            + "*NODE\n" + _node_rows(_QUAD_PTS)
            + "*ELEMENT_SHELL\n" + _elem(1, 1, 1, 2, 3, 4)
            + (part or "*PART\nplate\n" + _row(1, 1, 1) + "\n")
            + "*SECTION_SHELL\n" + _row(1, elform, shrf, nip) + "\n"
            + _row(1.0) + "\n"
            + mat + second + extra + "*END\n")


#: part 2 = quad 2 on the SAME section 1, material 2 (*MAT_PLASTIC_KINEMATIC)
_SECOND_LAW44 = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                 + "*PART\nplastic plate\n" + _row(2, 1, 2) + "\n"
                 + "*MAT_PLASTIC_KINEMATIC\n"
                 + _row(2, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
                 + _row(0.0, 0.0, 0.0) + "\n")
#: part 2 = quad 2 on the SAME section 1, material 2 (*MAT_ELASTIC)
_SECOND_LAW1 = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                + "*PART\nsecond elastic plate\n" + _row(2, 1, 2) + "\n"
                + "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 70000.0, 0.33) + "\n")


def _johnson_cook(mid: int) -> str:
    """*MAT_JOHNSON_COOK without an *EOS_* - written /MAT/LAW2 (PLAS_JOHNS),
    writer/mesh._target_mat_law."""
    return ("*MAT_JOHNSON_COOK\n" + _row(mid, 7.85e-9, 80000.0, 210000.0, 0.3)
            + "\n" + _row(300.0, 500.0, 0.26, 0.01, 1.0) + "\n"
            + _row(1800.0, 0.0, 0.0, 1.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0) + "\n")


#: part 2 = quad 2 on the SAME section 1, material 2 (*MAT_JOHNSON_COOK, LAW2)
_SECOND_LAW2 = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                + "*PART\nJohnson-Cook plate\n" + _row(2, 1, 2) + "\n"
                + _johnson_cook(2))


# ═════════════════════════════════════════════════════════════════════════════
# K-30 - all-tet sections write Isolid 1
# ═════════════════════════════════════════════════════════════════════════════

class TetSectionWritesIsolid1(unittest.TestCase):
    """The starter runs every 4- / 10-node tet group at Isolid 1
    (sgrtails.F:694 turns a 2 into 0, :984-999 reset any other value to 1);
    Isolid 14 draws WARNING 791 on the way for a LAW1 group
    (sgrtails.F:695-704). So an all-tet ELFORM 10 / 13 section writes the 1
    the starter runs."""

    def test_an_elform_10_tet_section_writes_isolid_1(self):
        _r, starter, _e = _convert(_solid_deck())
        self.assertIn("/TETRA4/1", starter)
        self.assertEqual(_isolid(starter), 1)
        self.assertEqual(_itetra10(starter), 0)

    def test_the_opt_out_writes_isolid_14(self):
        _r, starter, _e = _convert(_solid_deck(), tet_isolid1=False)
        self.assertEqual(_isolid(starter), 14)

    def test_an_elform_13_tet_section_writes_isolid_1(self):
        _r, starter, _e = _convert(_solid_deck(elform=13))
        self.assertEqual(_isolid(starter), 1)
        _r, s14, _e = _convert(_solid_deck(elform=13), tet_isolid1=False)
        self.assertEqual(_isolid(s14), 14)

    def test_a_tet_spelled_with_trailing_zeros_counts(self):
        _r, starter, _e = _convert(_solid_deck(elems=_TET_ZEROS_ROW))
        self.assertIn("/TETRA4/1", starter)
        self.assertEqual(_isolid(starter), 1)

    def test_a_tet10_section_writes_isolid_1_and_keeps_itetra10(self):
        _r, starter, _e = _convert(_tet10_deck())
        self.assertIn("/TETRA10/1", starter)
        self.assertEqual(_isolid(starter), 1)
        self.assertEqual(_itetra10(starter), 1000)
        _r, s14, _e = _convert(_tet10_deck(), tet_isolid1=False)
        self.assertEqual((_isolid(s14), _itetra10(s14)), (14, 1000))

    def test_every_material_not_only_law1(self):
        """The scope decision: every all-tet section, whatever its law (the
        reset at sgrtails.F:984-988 does not look at the law)."""
        _r, starter, _e = _convert(_solid_deck(mat=_PLASTIC))
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertEqual(_isolid(starter), 1)

    def test_an_implicit_tet_section_writes_isolid_1(self):
        _r, starter, _e = _convert(_solid_deck(control=_IMPLICIT))
        self.assertEqual(_isolid(starter), 1)

    def test_a_section_with_one_hex_keeps_isolid_14(self):
        """A /BRICK on the section: the property serves a hex group too, so
        it keeps the ELFORM value."""
        _r, starter, _e = _convert(_solid_deck(elems=_TET_ROW + _HEX_ROW))
        self.assertIn("/TETRA4/1", starter)
        self.assertIn("/BRICK/1", starter)
        self.assertEqual(_isolid(starter), 14)

    def test_a_wedge_or_a_pyramid_on_the_section_keeps_isolid_14(self):
        """A wedge (6 distinct nodes) and a pyramid (5) are written as a
        degenerate /BRICK, so the property serves a hex group: the section is
        not all-tet and keeps the ELFORM's 14, beside a tet or alone, on both
        arms. (Counting them as tets would run that /BRICK at Isolid 1, the
        one-point viscous hex, instead of the fully integrated Isolid 14.)"""
        for name, elems in (("tet + wedge", _TET_ROW + _WEDGE_ROW),
                            ("tet + pyramid", _TET_ROW + _PYRAMID_ROW),
                            ("wedge alone", _WEDGE1_ROW),
                            ("pyramid alone", _PYRAMID1_ROW)):
            with self.subTest(section=name):
                _r, starter, _e = _convert(_solid_deck(elems=elems))
                self.assertIn("/BRICK/1", starter)
                self.assertEqual(_isolid(starter), 14)
                _r, s_off, _e = _convert(_solid_deck(elems=elems),
                                         tet_isolid1=False)
                self.assertEqual(starter, s_off)

    def test_a_tet_section_written_17_keeps_17(self):
        """Only a 14 is replaced (writer/mesh._tet_section_isolid). ELFORM 16
        (the 10-node tet) and ELFORM 2 map to Isolid 17 (_elform_to_isolid);
        the starter runs those tet groups at Isolid 1 as well
        (sgrtails.F:984-999), but a 17 draws no WARNING 791 (that one is for
        a LAW1 group at Isolid 14 / 15, :695-704) and K-30's scope is the
        ELFORM 10 / 13 sections, so these bytes do not move."""
        for name, deck in (("ELFORM 16 /TETRA10", _tet10_deck(elform=16)),
                           ("ELFORM 2 /TETRA4", _solid_deck(elform=2))):
            with self.subTest(section=name):
                _r, starter, _e = _convert(deck)
                self.assertEqual(_isolid(starter), 17)
                _r, s_off, _e = _convert(deck, tet_isolid1=False)
                self.assertEqual(starter, s_off)

    def test_a_hex_section_is_untouched(self):
        """ELFORM 1 hexes keep the default-hourglass Isolid 1 / h 0.1 and
        ELFORM 2 keeps 17 - the rule only replaces a 14."""
        hex1 = _solid_deck(elems=_HEX1_ROW, elform=1)
        _r, s1, _e = _convert(hex1)
        _r, s1off, _e = _convert(hex1, tet_isolid1=False)
        self.assertEqual(s1, s1off)
        self.assertEqual(_isolid(s1), 1)
        _r, s2, _e = _convert(_solid_deck(elems=_HEX1_ROW, elform=2))
        self.assertEqual(_isolid(s2), 17)
        _r, s10, _e = _convert(_solid_deck(elems=_HEX1_ROW, elform=10))
        self.assertEqual(_isolid(s10), 14)      # a hex on a tet ELFORM

    def test_only_the_isolid_cell_moves(self):
        """Default against the opt-out: one starter line differs, the
        /PROP/SOLID card 1, and only in its Isolid cell; the engine file is
        the same."""
        _r, s1, e1 = _convert(_solid_deck())
        _r, s14, e14 = _convert(_solid_deck(), tet_isolid1=False)
        diff = _diff_lines(s1, s14)
        self.assertEqual(len(diff), 1, diff)
        a, b = diff[0]
        self.assertEqual((a[0:10], b[0:10]), (_row(1)[0:10], _row(14)[0:10]))
        self.assertEqual(a[10:], b[10:])
        self.assertEqual(e1, e14)

    def test_an_ale_section_keeps_isolid_0(self):
        """ELFORM 11 / 12 are ALE: the property is written Isolid 0 (the ALE
        brick) and the tet rule never sees a 14 there."""
        st = _dispatch(_solid_deck(elform=12))
        self.assertTrue(st.sec_solids[1].iale)
        self.assertNotIn(1, _mesh._tet_only_solid_secids(st))


class TetIsolidConsumers(unittest.TestCase):
    """The places that read the /PROP/SOLID Isolid follow the emitted one."""

    def test_effective_solid_isolid_reports_the_emitted_value(self):
        st = _dispatch(_solid_deck())
        sec = st.sec_solids[1]
        self.assertEqual(_elform_to_isolid(sec.elform), 14)   # base kept
        self.assertEqual(_mesh._effective_solid_isolid(st, 1, sec), 1)
        st.options = dataclasses.replace(st.options, tet_isolid1=False)
        self.assertEqual(_mesh._effective_solid_isolid(st, 1, sec), 14)

    def test_a_mixed_section_reports_14(self):
        st = _dispatch(_solid_deck(elems=_TET_ROW + _HEX_ROW))
        self.assertEqual(
            _mesh._effective_solid_isolid(st, 1, st.sec_solids[1]), 14)

    def test_the_hourglass_split_emitter_follows(self):
        """The second /PROP/SOLID emission site. An ELFORM 10 / 13 part never
        reaches it through _assign_hourglass_props (its hourglass values are
        gated to (None, None)), so the split is planted by hand here."""
        st = _dispatch(_solid_deck())
        st.hourglass_prop_ids[1] = 900
        st.hourglass_prop_vals[1] = (None, None)
        lines = _mesh._emit_hourglass_props(st, 0)
        text = "\n".join(lines)
        self.assertEqual(_isolid(text, 900), 1)
        self.assertEqual(_mesh._effective_solid_isolid(st, 1, st.sec_solids[1]),
                         1)
        st.options = dataclasses.replace(st.options, tet_isolid1=False)
        text = "\n".join(_mesh._emit_hourglass_props(st, 0))
        self.assertEqual(_isolid(text, 900), 14)

    def test_the_tet_only_set_is_computed_per_state(self):
        """The set is memoised (the /PRELOAD and /INIBRI writers ask once per
        element) - and must never answer for another deck or a changed
        element list."""
        st_tet = _dispatch(_solid_deck())
        st_hex = _dispatch(_solid_deck(elems=_HEX_ROW, elform=10))
        self.assertEqual(_mesh._tet_only_solid_secids(st_tet), {1})
        self.assertEqual(_mesh._tet_only_solid_secids(st_hex), set())
        self.assertEqual(_mesh._tet_only_solid_secids(st_tet), {1})
        st_mixed = _dispatch(_solid_deck(elems=_TET_ROW + _HEX_ROW))
        self.assertEqual(_mesh._tet_only_solid_secids(st_mixed), set())
        st_mixed.solid_elems[:] = [e for e in st_mixed.solid_elems
                                   if e.eid == 1]
        self.assertEqual(_mesh._tet_only_solid_secids(st_mixed), {1})

    def test_a_section_without_elements_is_not_all_tet(self):
        st = _dispatch(_solid_deck())
        st.solid_elems[:] = []
        self.assertEqual(_mesh._tet_only_solid_secids(st), set())


# ── /PRELOAD on a tet bolt ───────────────────────────────────────────────────

def _tet_bolt_deck(elform: int = 10, extra: str = "") -> str:
    """A 1 x 1 x 4 bar of four hex cells, each split into the six Kuhn tets
    along its 0-6 diagonal (the split is face-conforming between cells), cut
    through its second cell by one plane, pre-tensioned 200 MPa by an
    *INITIAL_STRESS_SECTION - the tet twin of test_preload_inistate's
    _bar_deck."""
    lines = ["*KEYWORD", "*NODE"]
    nid = 1
    layers = []
    for k in range(5):
        row = []
        for (u, v) in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
            lines.append(f"{nid:>8}{u:16.8E}{v:16.8E}{float(k):16.8E}")
            row.append(nid)
            nid += 1
        layers.append(row)
    lines += ["*PART", "bolt", _row(1, 1, 1),
              "*SECTION_SOLID", _row(1, elform),
              "*MAT_ELASTIC", _row(1, 7.85e-9, 210000.0, 0.3),
              "*ELEMENT_SOLID"]
    eid = 1
    kuhn = ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6),
            (0, 4, 5, 6), (0, 5, 1, 6))
    for c in range(4):
        n = layers[c] + layers[c + 1]
        for t in kuhn:
            a, b, cc, d = (n[i] for i in t)
            lines.append("".join(f"{x:>8}" for x in
                                 (eid, 1, a, b, cc, d, d, d, d, d)))
            eid += 1
    lines += ["*SET_PART_LIST", _row(5), _row(1),
              "*DATABASE_CROSS_SECTION_PLANE_ID", f"{1:>10}bolt cut",
              _row(5, 0.5, 0.5, 1.5, 0.5, 0.5, 2.5, 3.0),
              "*DEFINE_CURVE", _row(1, 0, 1.0, 200.0, 0.0),
              f"{0.0:>20.10G}{0.0:>20.10G}", f"{2.0e-4:>20.10G}{1.0:>20.10G}",
              "*INITIAL_STRESS_SECTION_TITLE", "bolt one",
              # ISSID CSID LCID PSID VID IZSHEAR ISTIFF
              _row(7, 1, 1, 0, 0, 0, 0)]
    if extra:
        lines.append(extra.rstrip("\n"))
    lines += ["*CONTROL_TERMINATION", "    4.0E-4", "*END"]
    return "\n".join(lines) + "\n"


class PreloadOnATetBolt(unittest.TestCase):
    """writer/preload._PRELOAD_STABLE_ISOLID {5, 14, 17} was measured on a HEX
    bar. A tet group written Isolid 14, 1 or 24 runs Isolid 1 alike (the
    starter reset, sgrtails.F:984-999), so a preloaded tet is not judged by
    that set, with or without --no-tet-isolid1: MEASURED (starter + engine,
    nt 4, 20 us) this deck written Isolid 14 (master), 1 (K-30) and 24
    (ELFORM 1 + IHQ 6) gives decoded-equal T01 (GLOBAL + the bolt /SECT, 50
    states from t = 0 to 1.96e-5 s) and byte-equal anim files, so a verdict
    keyed on the cell would split one run in two. (That deck is a FREE bar,
    which collapses at every Isolid: its T01 time step falls from 1.0e-7 s
    to 2.8e-9 s by t = 1.88e-5 s on all three arms. CLAMPED, the tet twin
    holds 192.2 .. 208.2 MPa after Tstop and runs NORMAL to 4e-4 s - round
    10, B9. No warning names a preloaded tet any more.)"""

    def _formulation_warnings(self, res):
        return [w for w in res.warnings if "emit /PROP/SOLID Isolid=" in w]

    def test_the_tet_bolt_preloads_and_is_not_warned(self):
        res, starter, _e = _convert(_tet_bolt_deck())
        self.assertIn("/PRELOAD/", starter)
        self.assertIn("/TETRA4/1", starter)
        self.assertEqual(_isolid(starter), 1)
        self.assertEqual(self._formulation_warnings(res), [])

    def test_the_opt_out_is_silent_too(self):
        res, starter, _e = _convert(_tet_bolt_deck(), tet_isolid1=False)
        self.assertEqual(_isolid(starter), 14)
        self.assertEqual(self._formulation_warnings(res), [])

    def test_tets_on_an_ihq6_section_are_not_judged_by_the_hex_set(self):
        """ELFORM 1 tets under *CONTROL_HOURGLASS IHQ 6 sit on an Isolid 24
        property, which the hex bar measured as diverging - but the tet
        groups run Isolid 1 after the starter's reset."""
        res, starter, _e = _convert(_tet_bolt_deck(
            elform=1, extra="*CONTROL_HOURGLASS\n" + _row(6)))
        self.assertEqual(_isolid(starter), 24)
        self.assertEqual(self._formulation_warnings(res), [])


# ═════════════════════════════════════════════════════════════════════════════
# K-31 - LAW1 shells write N = 0
# ═════════════════════════════════════════════════════════════════════════════

class Law1ShellGlobalN(unittest.TestCase):
    """cgrtails.F:780-791 switches a LAW1 shell group with N > 1 to N = 0
    (global integration) and prints WARNING 1084; N = 0 written directly is
    the same group without the warning."""

    def test_a_law1_section_with_nip_5_writes_n_0(self):
        _r, starter, _e = _convert(_shell_deck())
        self.assertIn("/MAT/ELAST/1", starter)
        self.assertEqual(_shell_n(starter), 0)

    def test_the_opt_out_writes_max_2_nip(self):
        _r, starter, _e = _convert(_shell_deck(), law1_shell_global_n=False)
        self.assertEqual(_shell_n(starter), 5)

    def test_a_blank_nip_writes_n_0(self):
        """NIP blank = LS-DYNA's 2 points (Vol I R17 p.41-66), written 2 by
        max(2, NIP) and switched to 0 by the starter."""
        _r, starter, _e = _convert(_shell_deck(nip=""))
        self.assertEqual(_shell_n(starter), 0)
        _r, s_off, _e = _convert(_shell_deck(nip=""),
                                 law1_shell_global_n=False)
        self.assertEqual(_shell_n(s_off), 2)

    def test_nip_1_keeps_n_2(self):
        """NIP 1 keeps the N 2 k2rad has always written (max(2, NIP); the
        plan keeps NIP 1 as it was), on both arms. That N 2 is NOT LS-DYNA's
        one-point, no-bending NIP 1 (Vol I R17 p.41-66): the starter still
        switches the LAW1 group to N = 0 (global integration,
        cgrtails.F:780-791) and prints WARNING 1084 - MEASURED (starter +
        engine, nt 1, 2026-10-31) on a NIP-1 *MAT_ELASTIC strip: N 2 and 1 x
        WARNING 1084 on both arms, anim files byte-equal. A triangle-only
        NIP-1 section takes N 1 since R14 round 10 (A2,
        tests/test_r14_round10.py); this strip is a QUAD, which keeps N 2."""
        _r, starter, _e = _convert(_shell_deck(nip="1"))
        self.assertEqual(_shell_n(starter), 2)
        _r, s_off, _e = _convert(_shell_deck(nip="1"),
                                 law1_shell_global_n=False)
        self.assertEqual(starter, s_off)

    def test_two_law1_parts_on_one_section_write_n_0(self):
        _r, starter, _e = _convert(_shell_deck(second=_SECOND_LAW1))
        self.assertEqual(_shell_n(starter), 0)

    def test_a_mixed_law1_law44_section_keeps_max_2_nip(self):
        """N = 0 on a non-LAW1 group is WARNING 1912 and N = 3
        (cgrtails.F:796-804) - a physics change, so a mixed section keeps
        max(2, NIP)."""
        _r, starter, _e = _convert(_shell_deck(second=_SECOND_LAW44))
        self.assertEqual(_shell_n(starter), 5)

    def test_a_law2_section_keeps_max_2_nip(self):
        """*MAT_JOHNSON_COOK without an *EOS_* is /MAT/LAW2, a non-LAW1
        group: N = 0 there would be WARNING 1912 and N = 3
        (cgrtails.F:796-805). Alone on the section, and beside a LAW1 part
        on the same section, it keeps max(2, NIP) on both arms."""
        for name, deck in (("LAW2 alone", _shell_deck(mat=_johnson_cook(1))),
                           ("LAW1 + LAW2", _shell_deck(second=_SECOND_LAW2))):
            with self.subTest(section=name):
                _r, starter, _e = _convert(deck)
                self.assertIn("/MAT/LAW2/", starter)
                self.assertEqual(_shell_n(starter), 5)
                _r, s_off, _e = _convert(deck, law1_shell_global_n=False)
                self.assertEqual(starter, s_off)
        _r, starter, _e = _convert(_shell_deck(second=_SECOND_LAW2))
        self.assertIn("/MAT/ELAST/1", starter)
        self.assertIn("/MAT/LAW2/2", starter)

    def test_a_plastic_section_keeps_max_2_nip(self):
        plastic = ("*MAT_PLASTIC_KINEMATIC\n"
                   + _row(1, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
                   + _row(0.0, 0.0, 0.0) + "\n")
        _r, starter, _e = _convert(_shell_deck(mat=plastic))
        self.assertEqual(_shell_n(starter), 5)

    def test_a_rigid_shell_section_writes_n_0(self):
        """*MAT_RIGID is written as /MAT/ELAST (LAW1) for the /RBODY, and
        cgrtails.F:780 tests only the law."""
        rigid = "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
        _r, starter, _e = _convert(_shell_deck(mat=rigid))
        self.assertEqual(_shell_n(starter), 0)

    def test_an_initial_stress_shell_section_keeps_max_2_nip(self):
        """/INISHE carries one station per through-thickness point and the
        starter cross-checks the count against N (the writer drops a record
        whose NTHICK is not max(2, NIP), so the record states 2 on NIP 2)."""
        ini = ("*INITIAL_STRESS_SHELL\n" + _row(1, 1, 2, 0, 0, 0) + "\n"
               + _row(-0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        _r, starter, _e = _convert(_shell_deck(nip="2", extra=ini))
        self.assertIn("/INISHE/STRS_F/GLOB", starter)
        self.assertEqual(_shell_n(starter), 2)
        _r, plain, _e = _convert(_shell_deck(nip="2"))
        self.assertEqual(_shell_n(plain), 0)

    def test_an_initial_strain_shell_section_keeps_max_2_nip(self):
        ini = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 2) + "\n"
               + _row(0.0, 0, 0, 0, 0, 0, -1.0) + "\n"
               + _row(0.02, 0, 0, 0, 0, 0, 1.0) + "\n")
        _r, starter, _e = _convert(_shell_deck(extra=ini))
        self.assertIn("/INISHE/STRA_F", starter)
        self.assertEqual(_shell_n(starter), 5)

    def test_a_set_based_initial_strain_keeps_max_2_nip(self):
        """*INITIAL_STRAIN_SHELL_SET names its elements through a
        *SET_SHELL: the exclusion follows the set."""
        ini = ("*SET_SHELL_LIST\n" + _row(77) + "\n" + _row(1) + "\n"
               + "*INITIAL_STRAIN_SHELL_SET\n" + _row(77) + "\n"
               + _row(0.0, 0, 0, 0, 0, 0, -1.0) + "\n"
               + _row(0.02, 0, 0, 0, 0, 0, 1.0) + "\n")
        _r, starter, _e = _convert(_shell_deck(extra=ini))
        self.assertIn("/INISHE/STRA_F", starter)
        self.assertEqual(_shell_n(starter), 5)

    def test_the_initial_state_exclusion_is_per_section(self):
        """Only the section whose element carries the record keeps max(2,
        NIP); a second all-LAW1 section of the same deck is written N = 0.
        STARTER + ENGINE (nt 4, 2026-10-31): 0 ERROR(S) on both arms; the
        record's section still draws 1 x WARNING 1084 (the starter switches
        it to N = 0 as well), --no-law1-shell-global-n draws it for both
        couples. Every energy, the mass and the time step agree in all
        digits; the written N of the two LAW1 groups now differs (2 / 0
        against 2 / 2), and the starter sorts its shell groups by the
        written N before its switch, so it orders the elements differently:
        all 40 anim files differ (62 to 198 of 3488 bytes) and the X / Y
        momentum (the round-off of zero, |value| <= 6.9e-19) by up to
        1.3e-20. Any two LAW1 groups whose written N differs on one arm do
        that (different NIP, NIP 1 kept at 2 beside a 0) - the side effect
        _law1_global_n_secids records."""
        second = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                  + "*PART\nsecond plate\n" + _row(2, 2, 1) + "\n"
                  + "*SECTION_SHELL\n" + _row(2, 2, "", 2) + "\n"
                  + _row(1.0) + "\n")
        ini = ("*INITIAL_STRESS_SHELL\n" + _row(1, 1, 2, 0, 0, 0) + "\n"
               + _row(-0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        _r, starter, _e = _convert(_shell_deck(nip="2", second=second,
                                               extra=ini))
        self.assertIn("/INISHE/STRS_F/GLOB", starter)
        self.assertEqual((_shell_n(starter, 1), _shell_n(starter, 2)),
                         (2, 0))

    def test_a_therm_stress_deck_keeps_max_2_nip(self):
        """A deck that writes /THERM_STRESS keeps max(2, NIP) on every shell
        section (the thermal texts and their measurements are about that
        output). The expansion card here sits on a SOLID part, so the LAW1
        shell itself is not restated."""
        solid = ("*NODE\n" + _node_rows(_CUBE_PTS, start=11)
                 + "*ELEMENT_SOLID\n"
                 + _elem(5, 3, 11, 12, 13, 14, 15, 16, 17, 18)
                 + "*PART\nblock\n" + _row(3, 3, 3) + "\n"
                 + "*SECTION_SOLID\n" + _row(3, 1) + "\n"
                 + "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n")
        expand = ("*MAT_ADD_THERMAL_EXPANSION\n"
                  + _row(3, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0) + "\n"
                  + "*LOAD_THERMAL_LOAD_CURVE\n" + _row(7, 0) + "\n"
                  + "*DEFINE_CURVE\n" + _row(7) + "\n"
                  + f"{0.0:>16}{20.0:>16}\n{1.0:>16}{120.0:>16}\n")
        _r, cold, _e = _convert(_shell_deck(second=solid))
        self.assertEqual(_shell_n(cold), 0)
        _r, hot, _e = _convert(_shell_deck(second=solid, extra=expand))
        self.assertIn("/THERM_STRESS/MAT/3", hot)
        self.assertIn("/MAT/ELAST/1", hot)
        self.assertEqual(_shell_n(hot), 5)

    def test_an_implicit_law1_section_writes_n_0(self):
        _r, starter, _e = _convert(_shell_deck(control=_IMPLICIT))
        self.assertEqual(_shell_n(starter), 0)

    def test_the_hourglass_split_shell_prop_follows(self):
        """A per-part *HOURGLASS splits the part onto its own /PROP/SHELL
        (writer/mesh._emit_hourglass_props) - written with the same N."""
        part = "*PART\nplate\n" + _row(1, 1, 1, 0, 9) + "\n"
        hg = "*HOURGLASS\n" + _row(9, 4, 0.05) + "\n"
        res, starter, _e = _convert(_shell_deck(part=part, extra=hg))
        split = [ln for ln in starter.splitlines()
                 if ln.startswith("/PROP/SHELL/") and ln != "/PROP/SHELL/1"]
        self.assertEqual(len(split), 1, split)
        self.assertEqual(_shell_n(starter, int(split[0].split("/")[-1])), 0)
        res, s_off, _e = _convert(_shell_deck(part=part, extra=hg),
                                  law1_shell_global_n=False)
        split = [ln for ln in s_off.splitlines()
                 if ln.startswith("/PROP/SHELL/") and ln != "/PROP/SHELL/1"]
        self.assertEqual(_shell_n(s_off, int(split[0].split("/")[-1])), 5)

    def test_only_the_n_cell_moves(self):
        _r, s0, e0 = _convert(_shell_deck())
        _r, s5, e5 = _convert(_shell_deck(), law1_shell_global_n=False)
        diff = _diff_lines(s0, s5)
        self.assertEqual(len(diff), 1, diff)
        a, b = diff[0]
        self.assertEqual((a[0:10], b[0:10]), (_row(0)[0:10], _row(5)[0:10]))
        self.assertEqual(a[10:], b[10:])
        self.assertEqual(e0, e5)

    def test_the_law1_set_helper(self):
        st = _dispatch(_shell_deck(second=_SECOND_LAW1))
        self.assertEqual(_mesh._law1_global_n_secids(st), {1})
        st.options = dataclasses.replace(st.options,
                                         law1_shell_global_n=False)
        self.assertEqual(_mesh._law1_global_n_secids(st), set())


class Law1TextsAfterTheSwitch(unittest.TestCase):
    """The texts that cited WARNING 1084 as what a k2rad deck prints."""

    def test_the_dropped_integration_rule_text_names_the_global_n(self):
        """*INTEGRATION_SHELL on a LAW1 part: the rule is dropped and the
        part keeps its plain /PROP/SHELL - which is now written N = 0."""
        rule = ("*INTEGRATION_SHELL\n" + _row(3, 3, 0) + "\n"
                + _row(-0.5, 0.25) + "\n" + _row(0.0, 0.5) + "\n"
                + _row(0.5, 0.25) + "\n")
        deck = _shell_deck().replace(
            "*SECTION_SHELL\n" + _row(1, 2, "", "5"),
            "*SECTION_SHELL\n" + _row(1, 2, "", "5", 1.0, -3))
        res, starter, _e = _convert(deck.replace("*END\n", rule + "*END\n"))
        msg = [w for w in res.warnings if "the rule is DROPPED" in w
               and "LAW1" in w]
        self.assertEqual(len(msg), 1, [w for w in res.warnings
                                       if "INTEGRATION_SHELL" in w])
        self.assertNotIn("integration point(s) but a UNIFORM thickness",
                         msg[0])
        self.assertIn("N = 0", msg[0])
        self.assertIn("--no-law1-shell-global-n", msg[0])
        self.assertEqual(_shell_n(starter), 0)
        # the opt-out arm names the N it writes and the starter's own switch
        res, s_off, _e = _convert(deck.replace("*END\n", rule + "*END\n"),
                                  law1_shell_global_n=False)
        msg = [w for w in res.warnings if "the rule is DROPPED" in w
               and "LAW1" in w]
        self.assertEqual(len(msg), 1)
        self.assertIn("UNIFORM thickness and N = 3", msg[0])
        self.assertIn("WARNING 1084 (cgrtails.F:780-791)", msg[0])
        self.assertNotIn("written N = 0", msg[0])
        self.assertEqual(_shell_n(s_off), 3)

    def test_a_one_point_rule_names_the_n_2_written(self):
        """A one-point *INTEGRATION_SHELL makes the section NIP 1 (the
        rule's count wins, writer/composites), which K-31 leaves at the N 2
        k2rad has always written: the text names that N = max(2, NIP) = 2,
        not the rule's 1, and the starter's own switch of the LAW1 group to
        N = 0 with WARNING 1084."""
        rule = ("*INTEGRATION_SHELL\n" + _row(3, 1, 0) + "\n"
                + _row(0.0, 1.0) + "\n")
        deck = _shell_deck().replace(
            "*SECTION_SHELL\n" + _row(1, 2, "", "5"),
            "*SECTION_SHELL\n" + _row(1, 2, "", "5", 1.0, -3))
        for kw in ({}, dict(law1_shell_global_n=False)):
            with self.subTest(arm="opt-out" if kw else "default"):
                res, starter, _e = _convert(
                    deck.replace("*END\n", rule + "*END\n"), **kw)
                msg = [w for w in res.warnings if "the rule is DROPPED" in w
                       and "LAW1" in w]
                self.assertEqual(len(msg), 1, res.warnings)
                self.assertIn("UNIFORM thickness and N = 2, which the starter "
                              "switches to N = 0", msg[0])
                self.assertIn("WARNING 1084 (cgrtails.F:780-791)", msg[0])
                self.assertEqual(_shell_n(starter), 2)

    def test_the_thermal_restatement_text_does_not_say_k2rad_prints_1084(self):
        """thermal.py's LAW36 restatement warning: the 1084 is the starter's
        answer to a written N > 1, not a property of the converted deck."""
        expand = ("*MAT_ADD_THERMAL_EXPANSION\n"
                  + _row(1, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0) + "\n"
                  + "*LOAD_THERMAL_LOAD_CURVE\n" + _row(7, 0) + "\n"
                  + "*DEFINE_CURVE\n" + _row(7) + "\n"
                  + f"{0.0:>16}{20.0:>16}\n{1.0:>16}{120.0:>16}\n")
        res, starter, _e = _convert(_shell_deck(extra=expand))
        msg = [w for w in res.warnings if "is RESTATED as /MAT/LAW36" in w]
        self.assertEqual(len(msg), 1)
        self.assertNotIn("(it answers N > 1 with WARNING 1084", msg[0])
        self.assertIn("cgrtails.F:780", msg[0])


# ═════════════════════════════════════════════════════════════════════════════
# The golden fixtures K-30 / K-31 move (tests/fixtures/expected)
# ═════════════════════════════════════════════════════════════════════════════

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fixtures")

#: STARTER SHA-256 (text mode, LF) of each golden fixture as master d7652da
#: converts it - equal to the checked-in golden at d7652da and to this tree
#: with both K3 levers off (the K3 scratch golden_master_sha.py, run against
#: the `git archive d7652da` export and against the tree, 2026-10-31).
_GOLDEN_MASTER_SHA = {
    "shell_explicit":
        "df578a09392c0994f21cdba32b320c405d26c10f764014007a8b646bfc14ad22",
    "solid_plastic":
        "1706cc99c654b92dcd77aef50981520b98ba8a709f6181e9cf1a67f3c66dba2e",
    "rigid_contact":
        "ab9076abbc92c570c2347d1e248363221a9861eb2bd0b81d7be1b447999398a9",
    "tied_weld":
        "94de955cc31055a060242486082947fd18e62974a5ed78840488ea8c1b889786",
    "implicit_qstat":
        "22fda7b0c103341752c3b0445eb901892e99d92184fd59689498c8313c0e426e",
}

#: (card family, master cell, new cell, how many lines) per golden
_GOLDEN_MOVES = {
    "solid_plastic": ("/PROP/SOLID/", 14, 1, 1),
    "shell_explicit": ("/PROP/SHELL/", 3, 0, 1),
    "rigid_contact": ("/PROP/SHELL/", 3, 0, 1),
    "tied_weld": ("/PROP/SHELL/", 3, 0, 2),
    "implicit_qstat": ("/PROP/SHELL/", 3, 0, 1),
}


def _fixture_starter(stem: str, **kw) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, stem + ".k")
        shutil.copy(os.path.join(_FIXTURES, stem + ".k"), dst)
        res = _t7.convert(dst, write_log=False, **kw)
        with open(res.starter_path) as fh:
            return fh.read()


class GoldenFixtureMoves(unittest.TestCase):
    """K-30 and K-31 are default-ON byte changes, so five checked-in golden
    starters were re-baselined (tests/fixtures/expected/*_0000.rad; every
    engine golden and the two wedge goldens are untouched). This pins that
    re-baseline to exactly the planned cells: with both levers off each
    fixture still converts to master d7652da's bytes, and the default moves
    only the /PROP/SOLID card-1 Isolid cell (14 -> 1, solid_plastic's ELFORM
    10 tets) or the /PROP/SHELL card-3 N cell (3 -> 0, the four *MAT_ELASTIC
    shell goldens - rigid_contact's *MAT_RIGID part shares the section).

    MEASURED (OpenRadioss starter + engine, nt 4, 2026-10-31, three arms per
    fixture: master d7652da, this tree, this tree with both levers off; the
    explicit fixtures run to 2 ms, implicit_qstat to its ENDTIM 1.0):
    shell_explicit, tied_weld and implicit_qstat print 2 x WARNING 1084 at
    master and with the levers off and 0 WARNING(S) at the default; their
    T01 decodes equal (tools/th_to_csv.py) and every anim file is
    byte-equal across the three arms. rigid_contact goes 2 x 1084 -> 0 as
    well, but its starter stops on all three arms at the fixture's own ERROR
    120 (its *LOAD_RIGID_BODY names curve 1, which the deck does not
    define), so it has no engine run. solid_plastic (LAW36 tets, no 791 to
    lose) prints 0 WARNING(S) on every arm, T01 decoded equal, anim
    byte-equal."""

    def test_the_levers_off_keep_the_master_bytes(self):
        for stem, sha in _GOLDEN_MASTER_SHA.items():
            with self.subTest(stem=stem):
                self.assertEqual(
                    _sha(_fixture_starter(stem, tet_isolid1=False,
                                          law1_shell_global_n=False,
                                          shrf_ashear=False)), sha)

    def test_the_default_moves_only_the_planned_cells(self):
        for stem, (fam, old, new, count) in _GOLDEN_MOVES.items():
            with self.subTest(stem=stem):
                off = _fixture_starter(stem, tet_isolid1=False,
                                       law1_shell_global_n=False)
                on = _fixture_starter(stem)
                moved = []
                head = ""
                for a, b in zip(off.splitlines(), on.splitlines()):
                    if a.startswith("/"):
                        head = a
                    if a != b:
                        moved.append((head, a, b))
                self.assertEqual(len(off.splitlines()),
                                 len(on.splitlines()))
                self.assertEqual(len(moved), count, moved)
                for h, a, b in moved:
                    self.assertTrue(h.startswith(fam), h)
                    self.assertEqual((int(a[:10]), int(b[:10])), (old, new))
                    self.assertEqual(a[10:], b[10:])

    def test_the_checked_in_goldens_are_the_default(self):
        for stem in _GOLDEN_MOVES:
            with self.subTest(stem=stem):
                with open(os.path.join(_FIXTURES, "expected",
                                       stem + "_0000.rad")) as fh:
                    gold = fh.read().replace("\r\n", "\n")
                self.assertEqual(_fixture_starter(stem), gold)

    def test_round10_a1_moves_only_the_ashear_cells(self):
        """R14 round 10, A1: the four shell goldens' /PROP/SHELL card-3
        Ashear cell (columns 41-60) goes 0 -> 1 (every section leaves SHRF
        blank, LS-DYNA's 1.0) - tied_weld has two sections, solid_plastic
        none; --no-shrf-ashear keeps the K3 default bytes."""
        want = {"shell_explicit": 1, "rigid_contact": 1, "tied_weld": 2,
                "implicit_qstat": 1, "solid_plastic": 0}
        for stem, count in want.items():
            with self.subTest(stem=stem):
                off = _fixture_starter(stem, shrf_ashear=False)
                on = _fixture_starter(stem)
                lo, ln = off.splitlines(), on.splitlines()
                self.assertEqual(len(lo), len(ln))
                head, moved = "", []
                for a, b in zip(lo, ln):
                    if a.startswith("/"):
                        head = a
                    if a != b:
                        moved.append((head, a, b))
                self.assertEqual(len(moved), count, moved)
                for h, a, b in moved:
                    self.assertTrue(h.startswith("/PROP/SHELL/"), h)
                    self.assertEqual((a[:40], a[60:]), (b[:40], b[60:]))
                    self.assertEqual((a[40:60].strip(), b[40:60].strip()),
                                     ("0", "1"))


# ═════════════════════════════════════════════════════════════════════════════
# K-32 - ELFORM 16 text, OPTT advice, SHRF note (the bytes do not move)
# ═════════════════════════════════════════════════════════════════════════════

#: the K-32 decks carry a LAW44 plate, so K-31 does not move their N and
#: their starter must keep the master bytes (_MASTER_PINS at the end)
_K32_LAW44 =("*MAT_PLASTIC_KINEMATIC\n"
              + _row(1, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
              + _row(0.0, 0.0, 0.0) + "\n")


class ElformSixteenLogText(unittest.TestCase):
    """LS-DYNA ELFORM 16 is the FULLY integrated shell (Vol I R17 p.41-64,
    'Fully integrated shell element'), so the default Ishell 12 (QBAT) is the same
    integration class, and 'qeph' (Ishell 24) is the dyna2rad parity choice,
    not a closer match."""

    def _w(self, deck, **kw):
        res, _s, _e = _convert(deck, **kw)
        return [w for w in res.warnings if w.startswith("*SECTION_SHELL ELFORM")]

    def test_the_mapping_pins(self):
        self.assertEqual(_elform_to_ishell(16, False), ISHELL_QBAT)
        self.assertEqual(_elform_to_ishell(16, False, ISHELL_QEPH),
                         ISHELL_QEPH)
        self.assertEqual(_elform_to_ishell(16, True), ISHELL_QEPH)
        self.assertEqual(_elform_to_ishell(2, False), ISHELL_QBAT)

    def test_the_default_log_says_same_class_not_closer_match(self):
        w = self._w(_shell_deck(elform=16, mat=_K32_LAW44))
        self.assertEqual(len(w), 1, w)
        self.assertIn("ELFORM 16", w[0])
        self.assertIn("Ishell=12", w[0])
        self.assertIn("SAME integration class", w[0])
        self.assertIn("dyna2rad", w[0])
        self.assertIn("+0.46 %", w[0])
        self.assertNotIn("closer match", w[0])
        self.assertNotIn("UNDER-integrated", w[0])

    def test_the_qeph_log_says_it_lowers_the_class(self):
        w = self._w(_shell_deck(elform=16, mat=_K32_LAW44),
                    shell_formulation="qeph")
        self.assertEqual(len(w), 1, w)
        self.assertIn("Ishell=24", w[0])
        self.assertIn("results WILL differ", w[0])
        self.assertIn("FULLY integrated", w[0])
        self.assertIn("dyna2rad", w[0])
        self.assertNotIn("closer match", w[0])

    def test_elform_2_keeps_its_text(self):
        w = self._w(_shell_deck(elform=2, mat=_K32_LAW44))
        self.assertEqual(len(w), 1, w)
        self.assertTrue(w[0].startswith(
            "*SECTION_SHELL ELFORM [2] -> /PROP/SHELL Ishell=12 (QBAT, FULLY "
            "integrated, 4 in-plane points) — the default."), w[0])
        self.assertIn("the closer match", w[0])

    def test_a_deck_with_2_and_16_gets_both_texts(self):
        second = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                  + "*PART\nsixteen\n" + _row(2, 2, 1) + "\n"
                  + "*SECTION_SHELL\n" + _row(2, 16, "", 5) + "\n"
                  + _row(1.0) + "\n")
        w = self._w(_shell_deck(elform=2, mat=_K32_LAW44, second=second))
        self.assertEqual(len(w), 2, w)
        self.assertTrue(w[0].startswith("*SECTION_SHELL ELFORM [2] -> "), w)
        self.assertIn("ELFORM 16", w[1])
        self.assertIn("SAME integration class", w[1])

    def test_the_bytes_do_not_move(self):
        _r, starter, _e = _convert(_shell_deck(elform=16, mat=_K32_LAW44),
                                   shrf_ashear=False)
        self.assertEqual(_sha(starter), _MASTER_PINS["k32_elform16"])
        _r, starter, _e = _convert(_shell_deck(elform=16, mat=_K32_LAW44),
                                   shell_formulation="qeph", shrf_ashear=False)
        self.assertEqual(_sha(starter), _MASTER_PINS["k32_elform16_qeph"])


def _optt_deck() -> str:
    """The LAW44 plate as a *PART_CONTACT with OPTT 0.5 (card 3 field 5)."""
    part = ("*PART_CONTACT\nplate\n" + _row(1, 1, 1) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0) + "\n")
    return _shell_deck(mat=_K32_LAW44, part=part)


class OpttAdvice(unittest.TestCase):
    """The *PART_CONTACT OPTT warning pointed every route at Card 3 SST/MST;
    /INTER/TYPE25 has no Gapmin column and reads neither, and OPTT IS its
    per-part gap lever (i25sti3.F:217-218)."""

    def _optt(self, **kw):
        res, starter, _e = _convert(_optt_deck(), **kw)
        msg = [w for w in res.warnings if "OPTT on part(s)" in w]
        self.assertEqual(len(msg), 1, msg)
        return msg[0], starter

    def test_the_type25_route_is_pointed_at_optt(self):
        msg, _s = self._optt()
        self.assertIn("i7sti3.F:222", msg)               # the Igap gate kept
        self.assertIn("INERT", msg)
        self.assertNotIn("set /INTER Gapmin directly (or *CONTACT Card 3 "
                         "SST/MST)", msg)
        self.assertIn("Igap=0 TYPE7", msg)
        self.assertIn("--inter-gapmin", msg)
        self.assertIn("no Gapmin column", msg)
        self.assertIn("i25sti3.F:217-218", msg)
        self.assertIn("Gap_scale x OPTT / 2", msg)

    def test_the_bytes_do_not_move(self):
        _msg, starter = self._optt(shrf_ashear=False)
        self.assertEqual(_sha(starter), _MASTER_PINS["k32_optt"])


class ShrfNote(unittest.TestCase):
    """*SECTION_SHELL SHRF (K-0P read it; R14 round 10, A1 writes it): the
    /PROP/SHELL Ashear cell carries the stated factor, a blank as LS-DYNA's
    1.0, a value within 0.005 of 5/6 as the starter's own 5/6 (the cell 0,
    hm_read_prop01.F:244). The K-32 'NOT converted' note survives as the
    --no-shrf-ashear sentence, which names every section whose cell the
    default writes (stated AND blank); the default path names only what it
    did not write as stated (the exclusion, the window, the range, the
    Kirchhoff elements - tests/test_r14_round10.py)."""

    def _notes(self, deck, **kw):
        res, starter, _e = _convert(deck, **kw)
        return [w for w in res.warnings if "SHRF" in w
                and "Ashear" in w], starter

    def test_a_stated_shrf_1_is_named_only_under_the_opt_out(self):
        notes, _s = self._notes(_shell_deck(mat=_K32_LAW44, shrf="1.0"))
        self.assertEqual(notes, [])
        notes, _s = self._notes(_shell_deck(mat=_K32_LAW44, shrf="1.0"),
                                shrf_ashear=False)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 1 (SHRF 1): SHRF, the transverse shear "
            "correction factor, is NOT carried to the /PROP/SHELL Ashear cell "
            "(--no-shrf-ashear)"), notes[0])
        for needle in ("5/6", "hm_read_prop01.F:244", "p.41-63",
                       "-0.041 % (L/t 3) / -0.018 % (L/t 5)",
                       "all 2642 R14 shell parts",
                       "The default writes the factor (a value within 0.005 "
                       "of 5/6 keeps the starter's own 5/6)."):
            with self.subTest(needle=needle):
                self.assertIn(needle, notes[0])
        self.assertNotIn("ROADMAP", notes[0])

    def test_one_note_groups_the_sections_by_value(self):
        """Three sections, two values: ONE warning, grouped by SHRF."""
        second = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                  + "*PART\nsecond\n" + _row(2, 2, 1) + "\n"
                  + "*SECTION_SHELL\n" + _row(2, 2, "0.9", 5) + "\n"
                  + _row(1.0) + "\n"
                  + "*SECTION_SHELL\n" + _row(3, 2, "1.0", 5) + "\n"
                  + _row(1.0) + "\n")
        notes, _s = self._notes(_shell_deck(mat=_K32_LAW44, shrf="1.0",
                                            second=second),
                                shrf_ashear=False)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 2 (SHRF 0.9); 1, 3 (SHRF 1): "), notes[0])

    def test_an_implicit_deck_is_named_too(self):
        """The ELFORM sentence skips implicit decks; the SHRF note does not
        (the Ashear cell is the same on both)."""
        notes, _s = self._notes(_shell_deck(mat=_K32_LAW44, shrf="1.0",
                                            control=_IMPLICIT),
                                shrf_ashear=False)
        self.assertEqual(len(notes), 1, notes)

    def test_blank_and_five_sixths_are_silent(self):
        for shrf in ("", "0.833", "0.8333333"):
            with self.subTest(shrf=shrf):
                notes, _s = self._notes(_shell_deck(mat=_K32_LAW44,
                                                    shrf=shrf))
                self.assertEqual(notes, [])
        # the opt-out names the blank too: its cell is the one the default
        # writes (1.0), the K3 review's minor
        notes, _s = self._notes(_shell_deck(mat=_K32_LAW44),
                                shrf_ashear=False)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 1 (SHRF blank / 0): "), notes[0])

    def test_the_ids_of_one_value_are_capped_at_10(self):
        """Eleven sections stating SHRF 1.0: ten ids, then the count."""
        deck = ("*KEYWORD\n" + _EXPLICIT + "*NODE\n" + _node_rows(_QUAD_PTS)
                + "*ELEMENT_SHELL\n"
                + "".join(_elem(i, i, 1, 2, 3, 4) for i in range(1, 12))
                + "".join(f"*PART\nplate {i}\n" + _row(i, i, 1) + "\n"
                          + "*SECTION_SHELL\n" + _row(i, 2, "1.0", 5) + "\n"
                          + _row(1.0) + "\n" for i in range(1, 12))
                + _K32_LAW44 + "*END\n")
        notes, _s = self._notes(deck, shrf_ashear=False)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, ... (11 sections) "
            "(SHRF 1): "), notes[0])

    def test_an_axisymmetric_route_is_not_named(self):
        """A deck routed to the 2-D axisymmetric deck (writer/axisym2d)
        rewrites its ELFORM 14 / 15 /PROP/SHELL as a /PROP/SOLID, which has
        no Ashear cell: no note. tests/test_r14_triage_9.b2_ax15 states SHRF
        1.0 on its ELFORM 15 section; with --no-axisymmetric-2d the section
        is a /PROP/SHELL again and A1's exclusion names it (a 2-D ELFORM:
        the cell stays 0)."""
        notes, starter = self._notes(_t9.b2_ax15())
        self.assertIn("/PROP/SOLID/1", starter)
        self.assertNotIn("/PROP/SHELL/", starter)
        self.assertEqual(notes, [])
        notes, starter = self._notes(_t9.b2_ax15(), axisymmetric_2d=False)
        self.assertIn("/PROP/SHELL/1", starter)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 1 (ELFORM 15): SHRF is NOT written to the "
            "/PROP/SHELL Ashear cell (it stays 0: the starter's 5/6, or 0 "
            "on an N-1 property)"),
            notes[0])

    def test_a_stated_1_and_a_blank_write_the_same_bytes(self):
        _n, s1 = self._notes(_shell_deck(mat=_K32_LAW44, shrf="1.0"))
        _n, s0 = self._notes(_shell_deck(mat=_K32_LAW44))
        self.assertEqual(s1, s0)


# ═════════════════════════════════════════════════════════════════════════════
# K-33 - the default solid hourglass sentence (the bytes do not move)
# ═════════════════════════════════════════════════════════════════════════════

class SolidHourglassSentence(unittest.TestCase):
    """The default (IHQ 2 -> Isolid 1, h 0.1) is LS-DYNA's own and faithful;
    the sentence names what it costs in coarse bending and the .k routes
    that avoid it."""

    def _hg(self, deck, **kw):
        res, starter, _e = _convert(deck, **kw)
        return [w for w in res.warnings if "DEFAULTED" in w], starter

    def test_the_explicit_sentence(self):
        msg, starter = self._hg(_solid_deck(elems=_HEX1_ROW, elform=1))
        self.assertEqual(len(msg), 1, msg)
        m = msg[0]
        self.assertEqual(_isolid(starter), 1)
        for needle in ("faithful", "1 - 1/n^2", "VISCOSITY", "IHQ 6",
                       "QH", "1.0", "Isolid 24", "ELFORM 2", "cube-like",
                       "shvis3.F", "WARNING 311", "0.0812 mm", "0.0613 mm",
                       "p.12-272 Remark 4", "p.41-100 Remark 5"):
            with self.subTest(needle=needle):
                self.assertIn(needle, m)
        # the pins the existing suite holds (tests/test_hourglass.py)
        self.assertIn("p.12-271", m)
        self.assertIn("Isolid 1", m)

    def test_the_implicit_dn_sentence(self):
        msg, starter = self._hg(_solid_deck(elems=_HEX1_ROW, elform=1,
                                            control=_IMPLICIT))
        self.assertEqual(len(msg), 1, msg)
        m = msg[0]
        self.assertEqual(_isolid(starter), 24)
        self.assertNotIn("the same number h states", m)
        self.assertIn("szhour3.F", m)
        self.assertIn("not a stiffness scale", m)

    def test_the_bytes_do_not_move(self):
        _m, starter = self._hg(_solid_deck(elems=_HEX1_ROW, elform=1))
        self.assertEqual(_sha(starter), _MASTER_PINS["k33_hex_explicit"])
        _m, starter = self._hg(_solid_deck(elems=_HEX1_ROW, elform=1,
                                           control=_IMPLICIT))
        self.assertEqual(_sha(starter), _MASTER_PINS["k33_hex_implicit"])


#: The STARTER SHA-256 of each deck above, converted at master d7652da with
#: the default options (`git archive d7652da k2rad k2rad.py` exported to the
#: K3 scratch folder and run with the repo venv, 2026-10-25; the script is
#: the group's master_pins.py). K-32 / K-33 are text only, so these decks
#: must keep the master bytes.
_MASTER_PINS = {
    "k32_elform16":
        "9ee936a9335b4eaa9f5cae881ef6607ee1e70823db55e9751a24e741e8a6368a",
    "k32_elform16_qeph":
        "9bf21b6313fc151d93c4cfacaa5f6a252b0a56e22e926f97c284978ef651a277",
    "k32_optt":
        "c66dfb27acf3cb314669106acd3850c0f3386be9a215ffa9794dc43ac6ebc9e3",
    "k33_hex_explicit":
        "a5e1147213c5ce6470200698e788ec808a52ae8dcd1b3c25aa4fea173098189f",
    "k33_hex_implicit":
        "a4ded6515e6de4ed94044babe0fa7921cb9c72b85e3453ae35c5f82cfd38e8f7",
}


if __name__ == "__main__":
    unittest.main()
