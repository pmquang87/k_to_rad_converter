"""Tests for the R14 CAMPAIGN TRIAGE batch, round 3 — PART A (contacts + ties):

  A1  the ONE ``*CONTACT`` registration table (``handlers._CONTACT_SPELLINGS``)
      that feeds ``HANDLERS``, ``assembly._OFFSET_SPECS`` and the README rows —
      16 spellings plus their ``_MPP`` forms, each with its named losses
  A2  the new routes: ``_SINGLE_EDGE`` -> /INTER/TYPE11 self edge-impact,
      ``_INTERFERENCE`` -> the surf2surf route with ``Inacti`` forced to 0, the
      five ``_THERMAL`` spellings -> a real ``Ithe = 1`` card, and
      ``_AUTOMATIC_GENERAL_MPP`` through the existing MPP card shift
  A3  the three by-name refusals: ``_DRAWBEAD``, ``_ENTITY``, ``_SLIDING_ONLY``
  D1  the tied family keyed on the KEYWORD and the SOLVER, and the derived
      ``/INTER/TYPE10`` ``STFAC``

...and PART B (elements, rigid velocities, ALE, the implicit residue):

  B   LS-DYNA's own DEFAULT hourglass control on a 1-point ``*SECTION_SOLID``
      the deck leaves defaulted (IHQ 2 explicit / 6 implicit, QH 0.1), through
      the existing IHQ -> Isolid remap, with the fluid / preload / LAW115 /
      ELFORM screens and the ``--no-default-hourglass`` opt-out
  C   ``*INITIAL_VELOCITY_GENERATION`` re-pointed onto the ``/RBODY`` main
      node, MIXED groups SPLIT in place, a PARTLY covered body refused
  E   ``*SECTION_SOLID`` ELFORM 5/6/7 stay LAGRANGIAN, named
  F   ``/IMPL/DT/FIXPOINT`` off by default

Kept in its own module, the repo's one-module-per-batch convention. Round 3's
item-D tests that REPLACE an invalidated test do NOT live here and must not be
moved here — ``TiedFamilyRoutingTests`` (tests/test_roadmap_keywords.py) and
``TiedContactAllRigidSecondaryTakesThePenaltyTie``
(tests/test_contact_silent_drop.py) are the named successors of
``TiedNegativeGapRoutingTests`` and ``TiedContactDropIsAccounted``, and the
"a moved or removed test carries its named successor IN PLACE" rule puts them
where the reader of the old test will look.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import (CONTACT_OFFSET_KEYWORDS, CONTACT_REGISTERED_KEYWORDS,
                            HANDLERS, _CONTACT_SPELLINGS, dispatch)
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the helpers of tests/test_r14_triage_2.py) ──────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
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


# ── One mesh every spelling can be hung on ───────────────────────────────────
#
# Two 8-node bricks (parts 1 and 2) that touch on the x = 1 plane, plus the
# three set flavours the contact card 1 can name: a *SET_SEGMENT of FACES
# (styp 0), a *SET_SEGMENT of two-node EDGES (the *CONTACT_SINGLE_EDGE
# spelling, see SegmentSet.edges) and a *SET_NODE_LIST (styp 4).

_MESH_TEMPLATE = (
    "*KEYWORD\n"
    "*NODE\n"
    + "".join(
        f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
        for i, (x, y, z) in enumerate(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
             (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
             (2, 0, 0), (2, 1, 0), (2, 0, 1), (2, 1, 1)], start=1))
    + "*ELEMENT_SOLID\n"
      "       1       1       1       2       3       4       5       6       7       8\n"
      "       2       2       2       9      10       3       6      11      12       7\n"
      "*PART\n"
      "left\n"
    + _row(1, 1, 1, 0, 0, 0, 0, "%TMID%") + "\n"
    + "*PART\n"
      "right\n"
    + _row(2, 1, 1, 0, 0, 0, 0, "%TMID%") + "\n"
    + "*SECTION_SOLID\n"
    + _row(1, 1) + "\n"
    + "*MAT_ELASTIC\n"
    + _row(1, "7.85e-9", 210000.0, 0.3) + "\n"
    + "*SET_SEGMENT\n"
    + _row(100) + "\n"
    + _row(2, 3, 7, 6) + "\n"
    + "*SET_SEGMENT\n"
    + _row(101) + "\n"
    + _row(2, 3) + "\n"
    + _row(3, 7) + "\n"
    + _row(7, 6) + "\n"
    + _row(6, 2) + "\n"
    + "*SET_NODE_LIST\n"
    + _row(110) + "\n"
    + _row(9, 10, 11, 12) + "\n"
)
#: The plain mesh (no *PART TMID, so no /HEAT/MAT) and the thermal one.
_MESH = _MESH_TEMPLATE.replace("%TMID%", "0")
#: A *PART TMID naming a *MAT_THERMAL_ISOTROPIC is what makes k2rad emit the
#: /HEAT/MAT that arms GLOB_THERM%ITHERM_FE -- the gate the interface thermal
#: card needs (ale_euler_init.F:193-200 via hm_read_part.F:366-368).
_MESH_THERMAL = (
    _MESH_TEMPLATE.replace("%TMID%", "9")
    + "*MAT_THERMAL_ISOTROPIC\n"          # Card1 TMID TRO ... / Card2 HC TC
    + _row(9, "7.85e-9") + "\n"
    + _row(4.6e8, 45.0) + "\n"
)
_TERM = "*CONTROL_TERMINATION\n" + _row(1.0) + "\n*END\n"
_IMPLICIT = "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.1) + "\n"
#: LS-DYNA THRM 1: ``K FRAD H0 LMIN LMAX FTOSA BC_FLAG ALGO``
#: (Keyword971/CONTACT/contact_surface_to_surface.cfg:1102-1103).
_THRM1 = _row(0.026, 0.5, 50.0, 0.5, 2.0, 0.5, 1, 0)
#: LS-DYNA Card 4 of *CONTACT_SURFACE_TO_SURFACE_INTERFERENCE: ``LCID1 LCID2``.
_CARD4_INTERFERENCE = _row(0, 0)
#: Optional Cards A / B / C. Card A states SOFT = 2 and Card C IGNORE = 1, with
#: DIFFERENT numbers on Card B, so a one-line card-stack slip is visible.
_CARD_A = _row(2, 0.1, 0, 1.025, 2, 2, 0, 1)
_CARD_B = _row(0.0, 7, 0, 0, 0, 0, 0.0, 0.0)
_CARD_C = _row(2, 1, 0.0, 0.0, 0.0, 0.0, 0.0, 0)


def _contact_block(kw: str) -> str:
    """One ``*CONTACT_<kw>`` block for the registration sweep.

    The card stack is built from the SAME table the dispatcher reads, so a row
    whose ``extra`` is wrong produces a deck this test reads back wrong — which
    is the point: ``_read_contact_soft`` and ``_read_contact_ignore`` both
    index off it.
    """
    base = kw
    if kw not in _CONTACT_SPELLINGS and kw.endswith("_MPP"):
        base = kw[:-4]
    row = _CONTACT_SPELLINGS[base]
    extra = int(row.kwargs.get("extra", 0))
    if base == "CONTACT_ENTITY":
        # Card 1 PID GEOTYP SURFA SURFATYP SF DF CF INTORD, then BT/DT/SO...,
        # the two orientation cards and card 5 INOUT G1..G7 (Vol I pp.11-155…).
        cards = [_row(2, 2, 110, 4, 1.0, 0.0, 0.0, 0),
                 _row(0.0, "1.0E20", 0, 0, 0, 0),
                 _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                 _row(0.0, 1.0, 0.0),
                 _row(0, 1.5, 0.5, 0.5, 0.25, 0.0, 0.0, 0.0)]
        if kw.endswith("_MPP"):
            cards.insert(0, _row(0, 0, 0, 0, 0, 1.0005, 0, 0))
        return f"*CONTACT_{kw[8:]}\n" + "".join(c + "\n" for c in cards)
    if "TIED" in base:
        card1 = _row(110, 100, 4, 0)
    elif base == "CONTACT_SINGLE_EDGE":
        card1 = _row(101, 0, 0, 0)
    elif base == "CONTACT_SINGLE_SURFACE":
        card1 = _row(0, 0, 0, 0)
    else:
        card1 = _row(1, 2, 3, 3)
    cards = [card1,
             _row(0.1, 0.1, 0.0, 0.0, 0.0, 0, 0.0, "1.0E20"),
             _row(0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)]
    # The card the spelling inserts between Card 3 and optional Card A. It is
    # keyed on the row's SEMANTICS, not on ``extra``: ``extra`` exists for the
    # handlers that read PAST the card (surf2surf's SOFT on Card A and IGNORE
    # on Card C), while the tied handler reads only Cards 1-3 plus THRM 1 — so
    # a tied _THERMAL row states no ``extra`` and still carries the card.
    if row.kwargs.get("thermal"):
        cards.append(_THRM1)
    elif row.kwargs.get("interference"):
        cards.append(_CARD4_INTERFERENCE)
    elif extra:
        cards.append(_row(0))
    if base == "CONTACT_DRAWBEAD":
        # Card 4.1 LCIDRF LCIDNF DBDTH DFSCL NUMINT DBPID ELOFF NBEAD.
        cards.append(_row(0, 0, 4.4, 2.0, 0, 0, 0, 0))
    cards += [_CARD_A, _CARD_B, _CARD_C]
    head = f"*CONTACT_{kw[8:]}"
    if kw.endswith("_MPP"):
        # The _MPP card sits BEFORE Card 1 (IGNORE BCKT LCBCKT NS2TRK INITITR
        # PARMAX <blank> CPARM8) — _contact_mpp_card_offset must step past it.
        cards.insert(0, _row(0, 0, 0, 0, 0, 1.0005, 0, 0))
    return head + "\n" + "".join(c + "\n" for c in cards)


#: The three spellings that are RECOGNIZED and deliberately emit nothing.
_REFUSED = ("CONTACT_DRAWBEAD", "CONTACT_ENTITY", "CONTACT_SLIDING_ONLY")


# ─────────────────────────────────────────────────────────────────────────────
# A1 — the one source table and its three consumers
# ─────────────────────────────────────────────────────────────────────────────

class OneSourceRegistrationTable(unittest.TestCase):
    """``HANDLERS``, ``assembly._OFFSET_SPECS`` and the README read ONE list.

    Hand-listing any of the three is what leaves a
    ``*CONTACT_SURFACE_TO_SURFACE_MPP`` unroutable while its base spelling
    converts — the #116 combinatorics rule, in the family where a miss costs a
    LOAD PATH rather than an output card.
    """

    def test_every_spelling_is_in_handlers(self):
        missing = [kw for kw in CONTACT_REGISTERED_KEYWORDS if kw not in HANDLERS]
        self.assertEqual(missing, [])

    def test_the_table_generates_the_mpp_siblings(self):
        # 16 rows: 15 with an _MPP sibling + CONTACT_AUTOMATIC_GENERAL_MPP,
        # which IS the _MPP spelling of an already-registered base.
        self.assertEqual(len(_CONTACT_SPELLINGS), 16)
        self.assertEqual(len(CONTACT_REGISTERED_KEYWORDS), 31)
        for base, row in _CONTACT_SPELLINGS.items():
            with self.subTest(base=base):
                self.assertEqual(base + "_MPP" in CONTACT_REGISTERED_KEYWORDS,
                                 row.mpp_sibling)

    def test_offset_specs_cover_exactly_the_offset_subset(self):
        for kw in CONTACT_OFFSET_KEYWORDS:
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_no_mpp_spelling_gets_an_offset_spec(self):
        """The MPP card pushes Card 1 down a line and ``_off_contact`` rewrites
        ``b.raw[start]`` blind — offsetting it would renumber the MPP bucket
        parameters as if they were SSID/MSID."""
        for kw in CONTACT_REGISTERED_KEYWORDS:
            if kw.endswith("_MPP"):
                with self.subTest(kw=kw):
                    self.assertNotIn(kw, _OFFSET_SPECS)

    def test_every_row_with_an_inserted_card_states_its_extra(self):
        """``extra`` is the number of MANDATORY cards between Card 3 and
        optional Card A. Every row routed to the surf2surf handler that
        inserts one (a ``_THERMAL`` THRM 1 or an ``_INTERFERENCE`` Card 4) must
        state ``extra = 1``, or ``_read_contact_soft`` reads the inserted
        card's first cell as SOFT and ``_read_contact_ignore`` reads Card B's
        THKOPT as IGNORE. The tied handler reads neither, which is why its
        ``_THERMAL`` rows state none."""
        from k2rad.handlers import handle_contact_automatic_surface_to_surface
        for base, row in _CONTACT_SPELLINGS.items():
            inserts = bool(row.kwargs.get("thermal")
                           or row.kwargs.get("interference"))
            reads_past = row.handler is handle_contact_automatic_surface_to_surface
            with self.subTest(base=base):
                self.assertEqual(int(row.kwargs.get("extra", 0)),
                                 1 if (inserts and reads_past) else 0)

    def test_no_refusal_gets_an_offset_spec(self):
        """An unmodelled card stack must not have its cells rewritten by
        position (the *AIRBAG warn-drop rule) — and *CONTACT_ENTITY's card 1 is
        PID/GEOTYP, not SSID/MSID, so offsetting it would renumber a PART id in
        the SET namespace."""
        for kw in _REFUSED:
            with self.subTest(kw=kw):
                self.assertNotIn(kw, _OFFSET_SPECS)


class EverySpellingDispatches(unittest.TestCase):
    """Table-driven, one subtest per spelling: nothing lands in
    ``skipped_keywords``, and every non-refused spelling emits an ``/INTER``."""

    def test_every_spelling(self):
        for kw in CONTACT_REGISTERED_KEYWORDS:
            base = kw
            if kw not in _CONTACT_SPELLINGS and kw.endswith("_MPP"):
                base = kw[:-4]
            with self.subTest(kw=kw):
                deck = _MESH_THERMAL + _contact_block(kw) + _TERM
                res, starter = _convert(deck)
                self.assertNotIn(kw, res.skipped_keywords)
                self.assertNotIn(base, res.skipped_keywords)
                if base in _REFUSED:
                    # keyed on the SPELLING, so an _MPP sibling is named as
                    # itself rather than folded into its base.
                    self.assertIn(kw, dict(res.recognized_not_emitted))
                else:
                    self.assertIn("/INTER/", starter)

    def test_an_unregistered_contact_is_skipped_but_never_silent(self):
        """The floor the whole item rests on: a *CONTACT with no handler still
        reaches skipped_keywords (the accounting is unchanged) and now says
        what a skipped contact costs."""
        deck = (_MESH
                + "*CONTACT_NO_SUCH_SPELLING\n" + _row(1, 2, 3, 3) + "\n"
                + _TERM)
        res, _ = _convert(deck)
        self.assertIn("CONTACT_NO_SUCH_SPELLING", res.skipped_keywords)
        hits = [w for w in res.warnings if "MISSING LOAD PATH" in w]
        self.assertEqual(len(hits), 1, repr(res.warnings))
        self.assertIn("18 of the 30 decks", hits[0])


class IncludeTransformOffsetRoundTrip(unittest.TestCase):
    """A new spelling's Card-1 set ids survive an ``*INCLUDE_TRANSFORM``.

    One spelling per side bucket: a PART-side pair (SURFATYP/SURFBTYP 3) and a
    SET-side pair (a *SET_NODE secondary + a *SET_SEGMENT main), because
    ``_off_contact`` maps the two cells through DIFFERENT offset namespaces.
    """

    def _round_trip(self, kw, card1, idpoff, idsoff, expect):
        with tempfile.TemporaryDirectory() as tmp:
            child = os.path.join(tmp, "child.k")
            with open(child, "w") as fh:
                fh.write(_MESH
                         + f"*CONTACT_{kw[8:]}\n" + card1 + "\n"
                         + _row(0.1, 0.1, 0.0, 0.0, 0.0, 0, 0.0, "1.0E20") + "\n"
                         + _row(0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0) + "\n"
                         + "*END\n")
            root = os.path.join(tmp, "root.k")
            with open(root, "w") as fh:
                fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                         # card 2: IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF
                         # IDDOFF (Vol I R17 p.31-19) — IDSOFF is field FIVE.
                         + _row(0, 0, idpoff, 0, idsoff, 0, 0) + "\n"
                         + _row(0, 0, 0, 0, 0.0, 0.0) + "\n"
                         + _TERM)
            state = ConversionState()
            for block in parse_k_file(root):
                dispatch(block, state)
        rec = (state.contacts_surf2surf + state.contacts_tied)[0]
        self.assertEqual((rec.ssid, rec.msid), expect)

    def test_part_side_ids_are_offset(self):
        # SURFATYP/SURFBTYP 3 -> both cells are PART ids (IDPOFF 1000).
        self._round_trip("CONTACT_SURFACE_TO_SURFACE", _row(1, 2, 3, 3),
                         1000, 0, (1001, 1002))

    def test_set_side_ids_are_offset(self):
        # SURFATYP 4 -> a *SET_NODE id, SURFBTYP 0 -> a *SET_SEGMENT id; both
        # live in the SET namespace (IDSOFF 500).
        self._round_trip("CONTACT_TIED_SURFACE_TO_SURFACE_THERMAL",
                         _row(110, 100, 4, 0), 0, 500, (610, 600))


# ─────────────────────────────────────────────────────────────────────────────
# A1/A2 — the card stack: `extra` keeps SOFT and IGNORE on their own cards
# ─────────────────────────────────────────────────────────────────────────────

class ThermalCardStackOffsets(unittest.TestCase):
    """THRM 1 sits BETWEEN Card 3 and optional Card A (Vol I R17 p.11-6/11-7).

    Without ``extra = 1`` ``_read_contact_soft`` reads THRM 1's ``K`` as SOFT
    and ``_read_contact_ignore`` reads Card B's second cell as IGNORE — here 7,
    which maps to nothing and would print an IGNORE the deck never states.
    """

    def _state(self, kw):
        return _dispatch(_MESH_THERMAL + _contact_block(kw) + _TERM)

    def test_ignore_comes_from_card_c_not_card_b(self):
        st = self._state("CONTACT_SURFACE_TO_SURFACE_THERMAL")
        self.assertEqual(st.contacts_surf2surf[0].ignore, 1)

    def test_the_thrm1_cells_are_read_in_the_manual_s_order(self):
        st = self._state("CONTACT_SURFACE_TO_SURFACE_THERMAL")
        th = st.contacts_surf2surf[0].thermal
        self.assertIsNotNone(th)
        # K FRAD H0 LMIN LMAX FTOSA BC_FLAG ALGO — H0 is column 3, not column 1.
        self.assertEqual((th.k, th.frad, th.h0), (0.026, 0.5, 50.0))
        self.assertEqual((th.lmin, th.lmax, th.ftosa), (0.5, 2.0, 0.5))
        self.assertEqual((th.bc_flg, th.algo), (1, 0))

    def test_the_mpp_sibling_reads_the_same_cells(self):
        st = self._state("CONTACT_SURFACE_TO_SURFACE_THERMAL_MPP")
        rec = st.contacts_surf2surf[0]
        self.assertEqual((rec.ssid, rec.msid, rec.ignore), (1, 2, 1))
        self.assertEqual(rec.thermal.h0, 50.0)


# ─────────────────────────────────────────────────────────────────────────────
# A2 — the thermal contact card
# ─────────────────────────────────────────────────────────────────────────────

class ThermalContactCard(unittest.TestCase):
    """``_THERMAL`` -> a real ``Ithe = 1`` card, or a NAMED drop."""

    def test_ithe_card_is_emitted_with_a_heat_mat(self):
        res, s = _convert(_MESH_THERMAL
                          + _contact_block("CONTACT_SURFACE_TO_SURFACE_THERMAL")
                          + _TERM)
        self.assertIn("/HEAT/MAT/", s)
        self.assertIn("Ithe_form", s)
        body = s[s.index("/INTER/TYPE7/"):]
        card = body[body.index("Ithe_form"):].splitlines()[1]
        cells = card.split()
        # Kthe = H0, fct_IDK 0, Tint 0, Ithe_form 1, AscaleK 0 (= one unit,
        # hm_read_inter_type07.F:693-697).
        self.assertEqual(cells, ["50", "0", "0", "1", "0"])
        frad = body[body.index("Frad"):].splitlines()[1].split()
        # Frad = FRAD, Drad = LMAX, Fheats/Fheatm = FTOSA / 1-FTOSA.
        self.assertEqual(frad, ["0.5", "2", "0.5", "0.5"])
        # ...and Ithe = 1 on card 1.
        c1 = body.splitlines()[3].split()
        self.assertEqual(c1[3], "1")

    def test_the_named_facts_are_in_the_warning(self):
        res, _ = _convert(_MESH_THERMAL
                          + _contact_block("CONTACT_SURFACE_TO_SURFACE_THERMAL")
                          + _TERM)
        w = next(w for w in res.warnings if "THERMAL card -> /INTER" in w)
        self.assertIn("Kthe=50", w)
        self.assertIn("K=0.026", w)          # the named drop
        self.assertIn("LMIN=0.5", w)
        self.assertIn("BC_FLAG=1", w)

    def test_no_heat_mat_drops_ithe_and_says_so(self):
        """Emitting the card on a deck with no /HEAT/MAT would ship something
        the starter disables with WARNING 702
        (hm_read_inter_type07.F:700-707)."""
        res, s = _convert(_MESH
                          + _contact_block("CONTACT_SURFACE_TO_SURFACE_THERMAL")
                          + _TERM)
        self.assertNotIn("/HEAT/MAT/", s)
        self.assertNotIn("Ithe_form", s)
        w = next(w for w in res.warnings if "THERMAL card is NOT converted" in w)
        self.assertIn("WARNING 702", w)
        self.assertIn("the seam transfers no heat", w)

    def test_algo_1_is_refused_by_name_rather_than_given_an_invented_tint(self):
        deck = _MESH_THERMAL + _contact_block(
            "CONTACT_SURFACE_TO_SURFACE_THERMAL").replace(_THRM1, _row(
                0.026, 0.5, 50.0, 0.5, 2.0, 0.5, 1, 1)) + _TERM
        res, s = _convert(deck)
        self.assertNotIn("Ithe_form", s)
        w = next(w for w in res.warnings if "THERMAL card is NOT converted" in w)
        self.assertIn("ALGO=1", w)
        self.assertIn("No Tint is invented", w)

    def test_a_tied_thermal_takes_the_type2_kthe_card_on_an_explicit_deck(self):
        res, s = _convert(_MESH_THERMAL
                          + _contact_block("CONTACT_TIED_SURFACE_TO_SURFACE_THERMAL")
                          + _TERM)
        self.assertIn("/INTER/TYPE2/", s)
        body = s[s.index("/INTER/TYPE2/"):]
        card = body[body.index("#     Ithe                Kthe"):].splitlines()[1]
        self.assertEqual(card.split()[:2], ["1", "50"])
        w = next(w for w in res.warnings if "THERMAL card -> /INTER/TYPE2" in w)
        # TYPE2 has no radiation branch and no friction split — both NAMED.
        self.assertIn("no radiation branch at all", w)

    def test_a_tied_thermal_on_an_implicit_deck_names_the_whole_card_as_lost(self):
        """It routes to /INTER/TYPE10 there, which has no thermal field at
        all — hm_read_inter_type10.F reads no I_TH/Kthe."""
        res, s = _convert(_MESH_THERMAL + _IMPLICIT
                          + _contact_block("CONTACT_TIED_SURFACE_TO_SURFACE_THERMAL")
                          + _TERM)
        self.assertIn("/INTER/TYPE10/", s)
        w = next(w for w in res.warnings if "THERMAL card is NOT converted" in w)
        self.assertIn("NO thermal fields at all", w)


# ─────────────────────────────────────────────────────────────────────────────
# A2 — *CONTACT_SURFACE_TO_SURFACE_INTERFERENCE
# ─────────────────────────────────────────────────────────────────────────────

class InterferenceForcesInactiZero(unittest.TestCase):
    """The keyword exists to RESOLVE an initial overlap into prestress
    (Vol I R17 p.11-66). ``i7pwr3.F:244-258`` makes Inacti 5/6 ACCEPT the
    overlap as the zero-force state, which would leave the fit unstressed."""

    def _inacti(self, starter):
        body = starter[starter.index("/INTER/TYPE7/"):]
        card = body[body.index("#      IBC"):].splitlines()[1]
        return int(card.split()[1])

    def test_inacti_is_zero_even_though_the_deck_states_ignore_1(self):
        st = _dispatch(_MESH
                       + _contact_block("CONTACT_SURFACE_TO_SURFACE_INTERFERENCE")
                       + _TERM)
        self.assertEqual(st.contacts_surf2surf[0].ignore, 1)   # the deck's cell
        _, s = _convert(_MESH
                        + _contact_block("CONTACT_SURFACE_TO_SURFACE_INTERFERENCE")
                        + _TERM)
        self.assertEqual(self._inacti(s), 0)

    def test_the_ordinary_spelling_still_maps_ignore_1_to_inacti_5(self):
        """The control: the override is keyed on the KEYWORD, so its sibling
        must be untouched. A mutation that drops the `interference` branch has
        to fail the test above, not this one."""
        _, s = _convert(_MESH + _contact_block("CONTACT_SURFACE_TO_SURFACE")
                        + _TERM)
        self.assertEqual(self._inacti(s), 5)

    def test_the_lcid_ramp_is_named_as_lost(self):
        res, _ = _convert(_MESH
                          + _contact_block("CONTACT_SURFACE_TO_SURFACE_INTERFERENCE")
                          + _TERM)
        w = next(w for w in res.warnings if "INTERFERENCE contact must RESOLVE" in w)
        self.assertIn("i7pwr3.F:244-258", w)
        self.assertIn("LCID1/LCID2 stiffness ramp", w)


# ─────────────────────────────────────────────────────────────────────────────
# A2 — *CONTACT_SINGLE_EDGE
# ─────────────────────────────────────────────────────────────────────────────

class SingleEdgeTakesTheType11SelfRoute(unittest.TestCase):
    """Vol I R17 p.11-124 Remark 3: edge-to-edge only, SURFA only. The exact
    OpenRadioss analogue is /INTER/TYPE11 self edge-impact, ``line_IDm = 0``."""

    def setUp(self):
        self.res, self.starter = _convert(
            _MESH + _contact_block("CONTACT_SINGLE_EDGE") + _TERM)

    def test_a_type11_over_a_synthesized_line(self):
        self.assertIn("/INTER/TYPE11/", self.starter)
        self.assertIn("/LINE/SEG/", self.starter)

    def test_line_idm_is_zero_self_edge_impact(self):
        body = self.starter[self.starter.index("/INTER/TYPE11/"):]
        card1 = body[body.index("# line_IDs"):].splitlines()[1].split()
        self.assertNotEqual(card1[0], "0")
        self.assertEqual(card1[1], "0")

    def test_no_node_to_surface_interface_is_added(self):
        """SINGLE_EDGE has none, so neither does the conversion."""
        self.assertNotIn("/INTER/TYPE7/", self.starter)
        self.assertNotIn("/INTER/TYPE25/", self.starter)

    def test_the_permissiveness_is_named(self):
        w = next(w for w in self.res.warnings if "SINGLE_EDGE" in w
                 and "p.11-124" in w)
        self.assertIn("more permissive", w)

    def test_the_two_node_segment_rows_are_kept_as_edges_and_named(self):
        """A *SET_SEGMENT can hold the EDGES directly, as two-node rows — the
        way the R14 carrier contact.edge.k spells this contact's SURFA. Before
        round 3 ``collapse_segment_corners`` dropped them with no diagnostic."""
        st = _dispatch(_MESH + _contact_block("CONTACT_SINGLE_EDGE") + _TERM)
        self.assertEqual(st.segment_sets[101].segments, [])
        self.assertEqual(st.segment_sets[101].edges,
                         [(2, 3), (3, 7), (7, 6), (6, 2)])
        self.assertEqual(len(st.segment_sets[100].edges), 0)
        self.assertTrue(any("state only TWO" in w for w in st.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# A3 — the three by-name refusals
# ─────────────────────────────────────────────────────────────────────────────

class RefusedByName(unittest.TestCase):
    """RECOGNIZED, deliberately not converted. Each text names the LS-DYNA
    fact, the OpenRadioss card that cannot carry it (with its source line), the
    PHYSICAL CONSEQUENCE and a REMEDY — the deck has to say what it lost."""

    def _run(self, kw):
        res, starter = _convert(_MESH + _contact_block(kw) + _TERM)
        hits = [w for w in res.warnings if "RECOGNIZED but NOT converted" in w]
        self.assertEqual(len(hits), 1, repr(res.warnings))
        return res, starter, hits[0]

    def test_all_three_are_accounted_and_never_skipped(self):
        for kw in _REFUSED:
            with self.subTest(kw=kw):
                res, starter, w = self._run(kw)
                self.assertNotIn(kw, res.skipped_keywords)
                self.assertIn(kw, dict(res.recognized_not_emitted))
                self.assertIn("PHYSICAL CONSEQUENCE", w)
                self.assertIn("REMEDY", w)

    def test_drawbead_names_the_curve_and_the_constant_it_would_have_to_invent(self):
        _, _, w = self._run("CONTACT_DRAWBEAD")
        self.assertIn("hm_read_inter_type08.F:131-137", w)
        self.assertIn("p.11-54", w)
        self.assertIn("DBDTH=4.4", w)
        self.assertIn("invent a restraining force", w)

    def test_drawbead_quotes_the_curve_range_when_the_deck_defines_one(self):
        """The refusal is built in the WRITER, not the handler, exactly so it
        can quote a *DEFINE_CURVE the corpus carrier states 150 lines AFTER the
        contact."""
        curve = ("*DEFINE_CURVE\n" + _row(7) + "\n"
                 + f"{0.0:>20}{0.0:>20}\n" + f"{3.0:>20}{22.7:>20}\n"
                 + f"{4.5:>20}{87.5:>20}\n")
        deck = (_MESH
                + _contact_block("CONTACT_DRAWBEAD").replace(
                    _row(0, 0, 4.4, 2.0, 0, 0, 0, 0),
                    _row(7, 0, 4.4, 2.0, 0, 0, 0, 0))
                + curve + _TERM)
        res, _ = _convert(deck)
        w = next(w for w in res.warnings if "RECOGNIZED but NOT converted" in w)
        self.assertIn("rising from 0 to 87.5 over delta 0..4.5", w)

    def test_entity_names_the_geotype_and_the_rwall_it_would_need(self):
        _, _, w = self._run("CONTACT_ENTITY")
        self.assertIn("GEOTYP=2", w)
        self.assertIn("hm_read_rwall_spher.F:290", w)
        self.assertIn("KINEMATICALLY constrained", w)

    def test_sliding_only_names_the_measured_regression_it_avoids(self):
        _, _, w = self._run("CONTACT_SLIDING_ONLY")
        self.assertIn("SLIDING AND VOIDS", w)
        self.assertIn("hm_read_inter_type03.F:262", w)
        self.assertIn("8.3e-17", w)          # the measured dt collapse
        self.assertIn("266379 cycles", w)


# ─────────────────────────────────────────────────────────────────────────────
# A1 — the named losses of the aliased spellings
# ─────────────────────────────────────────────────────────────────────────────

class NamedLossesPerSpelling(unittest.TestCase):
    """Every alias states what LS-DYNA fact it could not carry."""

    def _warnings(self, kw):
        res, _ = _convert(_MESH + _contact_block(kw) + _TERM)
        return [w for w in res.warnings if w.startswith(f"*{kw} ")]

    def test_non_automatic_orientation_is_named(self):
        w = " ".join(self._warnings("CONTACT_SURFACE_TO_SURFACE"))
        self.assertIn("p.11-10 item 4", w)
        self.assertIn("MORE permissive", w)

    def test_two_way_scoping_is_named_with_its_measured_deck(self):
        w = " ".join(self._warnings("CONTACT_SURFACE_TO_SURFACE"))
        self.assertIn("p.11-8 item 1b", w)
        self.assertIn("twobar", w)
        self.assertIn("+1151 %", w)

    def test_one_way_spelling_does_not_carry_the_two_way_note(self):
        """The control for the note table: ONE_WAY is a 1:1 semantic fit for
        /INTER/TYPE7, so claiming a scoping loss there would be a false fact."""
        w = " ".join(self._warnings("CONTACT_ONE_WAY_SURFACE_TO_SURFACE"))
        self.assertIn("p.11-10 item 4", w)
        self.assertNotIn("p.11-8 item 1b", w)

    def test_forming_names_the_tooling_thickness_and_offset(self):
        w = " ".join(self._warnings("CONTACT_FORMING_ONE_WAY_SURFACE_TO_SURFACE"))
        self.assertIn("General Remark 9", w)
        self.assertIn("--inter-gapmin", w)

    def test_mortar_names_the_missing_segment_to_segment_assembly(self):
        w = " ".join(self._warnings("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR"))
        self.assertIn("General Remark 14", w)
        self.assertIn("no mortar interface", w)

    def test_the_mpp_sibling_names_its_dropped_decomposition_cards(self):
        w = " ".join(self._warnings("CONTACT_AUTOMATIC_GENERAL_MPP"))
        self.assertIn("bucket sort", w)

    def test_single_surface_reaches_the_self_contact_route(self):
        _, s = _convert(_MESH + _contact_block("CONTACT_SINGLE_SURFACE") + _TERM)
        self.assertIn("/INTER/TYPE25/", s)          # explicit self-contact


# ─────────────────────────────────────────────────────────────────────────────
# D1 — the tied family, per spelling
# ─────────────────────────────────────────────────────────────────────────────

class TiedFamilyPerSpelling(unittest.TestCase):
    """The route per tied spelling, on both solvers.

    The class-level measurement lives in ``_tied_interface_type``; these pin
    the ROUTE. (``TiedFamilyRoutingTests`` in tests/test_roadmap_keywords.py is
    the named successor of the deleted sign-rule class and pins the rest.)
    """

    _TIED = ("CONTACT_TIED_SURFACE_TO_SURFACE",
             "CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET",
             "CONTACT_TIED_SURFACE_TO_SURFACE_THERMAL",
             "CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET_THERMAL")

    def _deck(self, kw, implicit):
        block = _contact_block(kw) if kw in _CONTACT_SPELLINGS else (
            f"*CONTACT_{kw[8:]}\n" + _row(110, 100, 4, 0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, "1.0E20") + "\n"
            + _row(0.0, 1.0, -0.1, -0.1, 1.0, 1.0, 1.0, 1.0) + "\n")
        return _MESH_THERMAL + (_IMPLICIT if implicit else "") + block + _TERM

    def test_surface_to_surface_family_is_solver_keyed(self):
        for kw in self._TIED:
            for implicit in (False, True):
                with self.subTest(kw=kw, implicit=implicit):
                    _, s = _convert(self._deck(kw, implicit))
                    if implicit:
                        self.assertIn("/INTER/TYPE10/", s)
                        self.assertNotIn("/INTER/TYPE2/", s)
                    else:
                        self.assertIn("/INTER/TYPE2/", s)
                        self.assertNotIn("/INTER/TYPE10/", s)

    def test_the_offset_thermal_spelling_is_read_as_an_OFFSET_flavour(self):
        """``kw.endswith("OFFSET")`` reported the R14 spelling
        *CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET_THERMAL as the plain
        constraint-based family, because the option sits in the MIDDLE of the
        keyword."""
        st = _dispatch(self._deck("CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET_THERMAL",
                                  False))
        self.assertTrue(st.contacts_tied[0].offset)

    def test_nodes_and_shell_edge_variants_never_take_the_penalty_tie(self):
        for kw in ("CONTACT_TIED_NODES_TO_SURFACE",
                   "CONTACT_TIED_SHELL_EDGE_TO_SURFACE"):
            for implicit in (False, True):
                with self.subTest(kw=kw, implicit=implicit):
                    _, s = _convert(self._deck(kw, implicit))
                    self.assertIn("/INTER/TYPE2/", s)
                    self.assertNotIn("/INTER/TYPE10/", s)


class TiedStfacLever(unittest.TestCase):
    """``--tie-stfac`` and the derived value.

    ``i7sti3.F:148/:444`` make the tie spring ``STFAC * A^2 * K / V`` per tied
    secondary node, i.e. ``STFAC / (3(1-2nu))`` times the stiffness of the
    element it welds. MEASURED on a determinate two-hex coupon (closed form
    IE 210.0, merged bar 209.2): STFAC 0.2 -> -67.6 %, 1 -> -24.3 %,
    10 -> -2.63 %, 30 -> -0.76 %, 100 -> -0.10 %, 120 -> +0.05 %.
    """

    _DECK = (_MESH + _IMPLICIT
             + "*CONTACT_TIED_SURFACE_TO_SURFACE\n"
             + _row(110, 100, 4, 0) + "\n"
             + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, "1.0E20") + "\n"
             + _row(0.0, 1.0, -0.1, -0.1, 1.0, 1.0, 1.0, 1.0) + "\n"
             + _TERM)

    def _stfac(self, **kw):
        _, s = _convert(self._DECK, **kw)
        body = s[s.index("/INTER/TYPE10/"):]
        card = body[body.index("#              STFAC"):].splitlines()[1]
        return float(card.split()[0])

    def test_default_is_the_shipped_zero(self):
        self.assertEqual(self._stfac(), 0.0)

    def test_auto_is_100x3x1_minus_2nu(self):
        # nu = 0.3 on the main side -> 100 * 3 * 0.4 = 120.
        self.assertAlmostEqual(self._stfac(tie_stfac="auto"), 120.0)

    def test_a_number_is_used_verbatim(self):
        self.assertAlmostEqual(self._stfac(tie_stfac=30.0), 30.0)

    def test_auto_falls_back_to_thirty_without_one_poisson_ratio(self):
        """``_TIE_STFAC_NO_NU``. The main side here spans two materials with
        different ratios, so ``K/E`` has no single value and the derived
        formula has nothing to evaluate. MEASURED on the same coupon:
        -0.76 % against the merged bar at a fifth of the nu = 0.3 arm's
        time-step cost. Pinned because the round-3 mutation round changed the
        constant to 3.0 and the whole suite stayed green."""
        head, tail = self._DECK.split("*PART\nright\n", 1)
        row, rest = tail.split("\n", 1)
        deck = (head + "*PART\nright\n"        # part 2 -> its own material
                + row[:20] + f"{2:>10}" + row[30:] + "\n" + rest)
        self.assertNotEqual(deck, self._DECK)
        deck = deck.replace(
            "*SET_SEGMENT",
            "*MAT_ELASTIC\n" + _row(2, "7.85e-9", 210000.0, 0.45) + "\n"
            + "*SET_SEGMENT", 1)
        _, s = _convert(deck, tie_stfac="auto")
        body = s[s.index("/INTER/TYPE10/"):]
        card = body[body.index("#              STFAC"):].splitlines()[1]
        self.assertAlmostEqual(float(card.split()[0]), 30.0)

    def test_the_default_arm_names_the_measured_softness(self):
        res, _ = _convert(self._DECK)
        w = next(w for w in res.warnings if "/INTER/TYPE10/" in w)
        self.assertIn("-67.6 %", w)
        self.assertIn("i7sti3.F:444", w)
        self.assertIn("--tie-stfac", w)


# ═════════════════════════════════════════════════════════════════════════════
# PART B — item B: LS-DYNA's DEFAULT solid hourglass control
# ═════════════════════════════════════════════════════════════════════════════

def _solid_prop(starter: str, prop_id):
    """(Isolid, h) of a /PROP/SOLID block. h is card 2 field 3 (cols 41-60)."""
    lines = starter.splitlines()
    i = lines.index(f"/PROP/SOLID/{prop_id}")
    data = [ln for ln in lines[i + 1:i + 9] if not ln.startswith("#")]
    return int(data[1][0:10]), float(data[2][40:60])


def _hg_deck(elform=1, mat=None, control="", hourglass="", hgid=0,
             implicit=False, extra=""):
    """One brick on *SECTION_SOLID <elform>, with whatever hourglass source."""
    mat = mat or ("*MAT_ELASTIC\n" + _row(1, "7.85e-9", 210000.0, 0.3) + "\n")
    return (
        "*KEYWORD\n*NODE\n"
        + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                  for i, (x, y, z) in enumerate(
                      [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                       (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], start=1))
        + "*ELEMENT_SOLID\n"
          "       1       1       1       2       3       4       5       6       7       8\n"
        + "*PART\nbrick\n" + _row(1, 1, 1, 0, hgid) + "\n"
        + "*SECTION_SOLID\n" + _row(1, elform) + "\n"
        + mat + control + hourglass + extra
        + ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.1) + "\n" if implicit else "")
        + "*CONTROL_TERMINATION\n" + _row(1.0) + "\n*END\n")


_MAT_NULL = ("*MAT_NULL\n" + _row(1, "1.0e-9", 0.0, 0.0, 0.0, 0.0, 1.0e-3)
             + "\n")


class DefaultSolidHourglassRuleTable(unittest.TestCase):
    """The rule, cell by cell: absent card / IHQ 0 / QH 0 / explicit vs
    implicit / fluid -> (Isolid, h).

    Vol I R17 p.12-271 ``*CONTROL_HOURGLASS`` Remark 1: "If omitted or if
    IHQ = 0, the default hourglass control types are as follows: ... b) For
    solids: type 2 for explicit; type 6 for implicit." QH's Default row is
    0.1, and p.25-5 Remark 7 makes a blank-or-zero QM/QH that same 0.1 unless
    a nonzero QH supersedes it.
    """

    def test_absent_card_explicit(self):
        _, s = _convert(_hg_deck())
        self.assertEqual(_solid_prop(s, 1), (1, 0.1))

    def test_absent_card_implicit(self):
        _, s = _convert(_hg_deck(implicit=True))
        self.assertEqual(_solid_prop(s, 1), (24, 0.1))

    def test_stated_ihq_zero_is_the_same_default(self):
        # component2.k's shape: IHQ 0 with a stated QH, which LS-DYNA's own
        # d3hsp echoes as "hourglass model = 2" / "coefficient = 5.00000E-02".
        _, s = _convert(_hg_deck(
            control="*CONTROL_HOURGLASS\n" + _row(0, 0.05) + "\n"))
        self.assertEqual(_solid_prop(s, 1), (1, 0.05))

    def test_stated_qh_zero_takes_the_default_coefficient(self):
        # birdball.k's shape: IHQ 2 / QH 0.0, whose d3hsp echoes
        # "hourglass coefficient = 1.00000E-01".
        _, s = _convert(_hg_deck(
            control="*CONTROL_HOURGLASS\n" + _row(2, 0.0) + "\n"))
        self.assertEqual(_solid_prop(s, 1), (1, 0.1))

    def test_a_stated_nonzero_coefficient_is_kept(self):
        # sloshing_B.k's shape (IHQ 1 / QH 0.005) — the three-line twin of
        # sloshing_A that must NOT move.
        _, s = _convert(_hg_deck(
            control="*CONTROL_HOURGLASS\n" + _row(1, 0.005) + "\n"))
        self.assertEqual(_solid_prop(s, 1), (1, 0.005))

    def test_a_fluid_keeps_the_viscous_form_even_implicitly(self):
        # *HOURGLASS Remark 4 (p.25-3): "For fluids modeled with null
        # material, type 6 hourglass control is viscous". MEASURED on
        # sloshing_A: Isolid 24 "terminates normally" at IE 1.75e16 / 99.9 %
        # energy error, Isolid 1 runs to t = 2.0 at IE -0.25 %.
        _, s = _convert(_hg_deck(mat=_MAT_NULL, implicit=True))
        self.assertEqual(_solid_prop(s, 1), (1, 0.1))
        _, s2 = _convert(_hg_deck(mat=_MAT_NULL))
        self.assertEqual(_solid_prop(s2, 1), (1, 0.1))

    def test_an_implicit_deck_retypes_a_stated_ihq_one_to_five(self):
        # Vol I R17 p.12-272: "For implicit analysis ... if IHQ = 1-5, then
        # solid elements will be switched to type 6."
        _, s = _convert(_hg_deck(
            implicit=True,
            control="*CONTROL_HOURGLASS\n" + _row(4, 0.1) + "\n"))
        self.assertEqual(_solid_prop(s, 1)[0], 24)
        # ... and an EXPLICIT deck keeps the stated stiffness form (IHQ 4 -> 5)
        _, s2 = _convert(_hg_deck(
            control="*CONTROL_HOURGLASS\n" + _row(4, 0.1) + "\n"))
        self.assertEqual(_solid_prop(s2, 1)[0], 5)

    def test_a_per_part_hourglass_with_ihq_zero_follows_the_same_rule(self):
        _, s = _convert(_hg_deck(
            hgid=7, hourglass="*HOURGLASS\n" + _row(7, 0, 0.0) + "\n"))
        ref = int([ln for ln in s.splitlines()
                   if ln.startswith("/PROP/SOLID/")][0].rsplit("/", 1)[1])
        self.assertEqual(_solid_prop(s, ref), (1, 0.1))

    def test_a_blank_qm_inherits_a_nonzero_global_qh(self):
        # Remark 7 (p.25-5): "The default value for QM is 0.1 unless
        # superseded by a nonzero value of QH in *CONTROL_HOURGLASS."
        _, s = _convert(_hg_deck(
            hgid=7,
            control="*CONTROL_HOURGLASS\n" + _row(1, 0.03) + "\n",
            hourglass="*HOURGLASS\n" + _row(7, 2) + "\n"))
        ref = int([ln for ln in s.splitlines()
                   if ln.startswith("/PROP/SOLID/")][0].rsplit("/", 1)[1])
        self.assertAlmostEqual(_solid_prop(s, ref)[1], 0.03)


    def test_a_stated_zero_qm_inherits_the_global_qh_too(self):
        """The OTHER half of Remark 7, and the half the blank-QM test above
        does not reach: "unless superseded by a NONZERO value of QH" makes a
        stated ``QM = 0.0`` exactly as un-stated as a blank cell. Pinned
        because the round-3 mutation round dropped the ``or not hg.qm`` term
        and the whole suite stayed green while this deck moved 0.03 -> 0.1."""
        _, s = _convert(_hg_deck(
            hgid=7,
            control="*CONTROL_HOURGLASS\n" + _row(1, 0.03) + "\n",
            hourglass="*HOURGLASS\n" + _row(7, 2, 0.0) + "\n"))
        ref = int([ln for ln in s.splitlines()
                   if ln.startswith("/PROP/SOLID/")][0].rsplit("/", 1)[1])
        self.assertAlmostEqual(_solid_prop(s, ref)[1], 0.03)

    def test_a_stated_nonzero_qm_supersedes_the_global_qh(self):
        """The control for the two above: "A nonzero value of QM supersedes
        QH" (p.25-5 Remark 7)."""
        _, s = _convert(_hg_deck(
            hgid=7,
            control="*CONTROL_HOURGLASS\n" + _row(1, 0.03) + "\n",
            hourglass="*HOURGLASS\n" + _row(7, 2, 0.02) + "\n"))
        ref = int([ln for ln in s.splitlines()
                   if ln.startswith("/PROP/SOLID/")][0].rsplit("/", 1)[1])
        self.assertAlmostEqual(_solid_prop(s, ref)[1], 0.02)


class DefaultSolidHourglassScreens(unittest.TestCase):
    """The ELFORMs and decks the default deliberately does NOT reach."""

    def test_elform_minus_one_keeps_the_full_integration_isolid(self):
        # Vol I R17 p.41-97 Remark 13: an ELFORM -1 assumed-strain hex has "no
        # hourglass energy, and the behavior is not affected by hourglass
        # parameters", so a default hourglass control has nothing to act on.
        _, s = _convert(_hg_deck(elform=-1))
        self.assertEqual(_solid_prop(s, 1), (17, 0.0))

    def test_elform_two_is_a_no_op(self):
        # Fully-integrated S/R hex: no hourglass modes, already gated out.
        _, s = _convert(_hg_deck(elform=2))
        self.assertEqual(_solid_prop(s, 1), (17, 0.0))

    def test_elform_sixteen_is_a_tet10_and_is_excluded(self):
        # _elform_to_isolid(16) is 17, which the {14,18} gate does not catch —
        # so ELFORM 16 is excluded by the 1-point ELFORM set instead.
        _, s = _convert(_hg_deck(elform=16))
        self.assertEqual(_solid_prop(s, 1), (17, 0.0))

    def test_elform_five_six_seven_DO_take_it(self):
        # They are 1-point solids in LS-DYNA and its own d3hsp echoes
        # "hourglass type = 2" / "coefficient = 1.00000E-01" for them
        # (taylor_B, sloshing_C, channel_A, advection_B).
        for ef in (5, 6, 7):
            with self.subTest(elform=ef):
                _, s = _convert(_hg_deck(elform=ef))
                self.assertEqual(_solid_prop(s, 1), (1, 0.1))

    def test_a_preloaded_deck_keeps_the_full_integration_isolid(self):
        # writer/preload._PRELOAD_STABLE_ISOLID: measured on a 1x1x4 hex bar at
        # /PRELOAD Itype=2 / 200 MPa, Isolid 1 and 2 hit ZERO OR NEGATIVE
        # VOLUME at cycle 0. The screen is deck-wide because the preloaded
        # parts are only known after the cross-section cut is resolved.
        deck = _hg_deck(extra=(
            "*DATABASE_CROSS_SECTION_PLANE\n"
            + _row(0, 0.5, 0.5, 0.5, 1.0, 0.5, 0.5) + "\n"
            + _row(0.5, 1.5, 0.5) + "\n"
            + "*DEFINE_CURVE\n" + _row(77) + "\n"
              "                 0.0                 0.0\n"
              "                 1.0               200.0\n"
            + "*INITIAL_STRESS_SECTION\n" + _row(1, 1, 77) + "\n"))
        _, s = _convert(deck)
        self.assertEqual(_solid_prop(s, 1), (17, 0.0))


class DefaultSolidHourglassOptOut(unittest.TestCase):
    def test_the_opt_out_is_byte_identical_to_the_old_behaviour(self):
        _, on = _convert(_hg_deck())
        _, off = _convert(_hg_deck(), default_hourglass=False)
        self.assertNotEqual(on, off)
        self.assertEqual(_solid_prop(off, 1), (17, 0.0))

    def test_the_opt_out_leaves_a_stated_card_alone(self):
        """A deck that STATES its hourglass control is unaffected by the flag —
        the flag is about the DEFAULT, not about the remap."""
        deck = _hg_deck(control="*CONTROL_HOURGLASS\n" + _row(1, 0.005) + "\n")
        _, on = _convert(deck)
        _, off = _convert(deck, default_hourglass=False)
        self.assertEqual(on, off)


class DefaultSolidHourglassInibriCoupling(unittest.TestCase):
    """/INIBRI Nb_integr must follow the DEFAULT-resolved Isolid, or the
    starter refuses the deck with MSGID 695."""

    _ISS = ("*INITIAL_STRESS_SOLID\n" + _row(1, 1) + "\n"
            "     100.0     200.0     300.0      10.0      20.0      30.0       0.0\n")

    def _inibri(self, starter):
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/INIBRI/STRS_FGLO"))
        card = next(ln for ln in lines[i + 1:] if not ln.startswith("#"))
        return int(card[10:20]), int(card[30:40])       # Nb_integr, Isolid

    def test_nb_integr_follows_the_default(self):
        _, s = _convert(_hg_deck(extra=self._ISS))
        self.assertEqual(_solid_prop(s, 1)[0], 1)
        self.assertEqual(self._inibri(s), (1, 1))

    def test_nb_integr_follows_the_opt_out_too(self):
        _, s = _convert(_hg_deck(extra=self._ISS), default_hourglass=False)
        self.assertEqual(_solid_prop(s, 1)[0], 17)
        self.assertEqual(self._inibri(s), (8, 17))


# ═════════════════════════════════════════════════════════════════════════════
# PART B — item C: the second half of the rigid-velocity re-point
# ═════════════════════════════════════════════════════════════════════════════

_IVG_NODES = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
              (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10),
              (20, 0, 0), (30, 0, 0), (30, 10, 0), (20, 10, 0),
              (20, 0, 10), (30, 0, 10), (30, 10, 10), (20, 10, 10)]

_MAT_RIGID = ("*MAT_RIGID\n" + _row(2, "7.85e-9", 210000.0, 0.3) + "\n"
              + _row(0, 0, 0) + "\n" + _row(0.0, 0.0, 0.0) + "\n")


def _ivg_deck(styp=2, sid=2, omega=0.0, v=(0.0, 0.0, 0.0),
              axis=(0.0, 0.0, 1.0), origin=(50.0, 0.0, 0.0),
              both_rigid=False, set_nodes=None):
    """Two bricks: part 1 deformable, part 2 *MAT_RIGID (or both rigid), with
    one *INITIAL_VELOCITY_GENERATION over whatever scope."""
    mat1 = (_MAT_RIGID.replace(_row(2, "7.85e-9", 210000.0, 0.3),
                               _row(1, "7.85e-9", 210000.0, 0.3))
            if both_rigid
            else "*MAT_ELASTIC\n" + _row(1, "7.85e-9", 210000.0, 0.3) + "\n")
    sets = ""
    if styp == 2:
        sets = "*SET_PART_LIST\n" + _row(sid) + "\n" + _row(2) + "\n"
    elif styp == 3:
        sets = ("*SET_NODE_LIST\n" + _row(sid) + "\n"
                + _row(*(set_nodes or [])) + "\n")
    return (
        "*KEYWORD\n*NODE\n"
        + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                  for i, (x, y, z) in enumerate(_IVG_NODES, start=1))
        + "*ELEMENT_SOLID\n"
          "       1       1       1       2       3       4       5       6       7       8\n"
          "       2       2       9      10      11      12      13      14      15      16\n"
        + "*PART\nleft\n" + _row(1, 1, 1) + "\n"
        + "*PART\nright\n" + _row(2, 1, 2) + "\n"
        + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
        + mat1 + _MAT_RIGID + sets
        + "*INITIAL_VELOCITY_GENERATION\n"
        + _row(sid, styp, omega, v[0], v[1], v[2], 0, 0) + "\n"
        + _row(origin[0], origin[1], origin[2],
               axis[0], axis[1], axis[2], 0, 0) + "\n"
        + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")


def _inivel_group(starter: str):
    """The member list of the /GRNOD the (single) /INIVEL/AXIS points at."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("/INIVEL/AXIS/"))
    data = [ln for ln in lines[i + 1:i + 8] if not ln.startswith("#")]
    grnod = int(data[1][20:30])
    h = lines.index(f"/GRNOD/NODE/{grnod}")
    out = []
    for row in lines[h + 2:]:
        if row.startswith(("/", "#")):
            break
        out.extend(int(t) for t in row.split())
    return out


class InivelGenerationRigidRepoint(unittest.TestCase):
    """``*INITIAL_VELOCITY_GENERATION`` on rigid members — round 2 left this
    half warned-only on a docstring rationale that was never solver-measured.

    ``hm_read_inivel.F:580-617`` writes BOTH ``VR = omega*n`` and
    ``V + omega x (x - O)`` on every node of an ``/INIVEL/AXIS`` group when
    ``IRODDL > 0``, and ``contrl.F:1053`` puts ``NRBODY`` in the ``IRODDL``
    minimum — so the main node carries the body's SPIN as well as its
    translation, and ``inirby.F:1032-1048`` rebuilds the secondaries from it.
    """

    def test_an_all_rigid_ivg_is_repointed_onto_the_main_node(self):
        res, s = _convert(_ivg_deck(v=(1000.0, 0.0, 0.0)))
        members = _inivel_group(s)
        self.assertEqual(len(members), 1, members)
        self.assertEqual(set(members) & set(range(9, 17)), set(), members)
        self.assertIn(f"/RBODY/{members[0]}", s)
        w = [x for x in res.warnings
             if "*INITIAL_VELOCITY_GENERATION" in x and "RE-POINTED" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("hm_read_inivel.F:580-617", w[0])
        self.assertIn("inirby.F:1032-1048", w[0])

    def test_the_spin_carrier_is_repointed_too(self):
        """brake.k's shape: OMEGA on a rigid part about an off-centre axis.

        Hand values from the coupon the round measured: a 10 mm *MAT_RIGID
        cube at OMEGA 100 about global Z through (50,0,0) gives
        1/2 m v_c^2 = 98.125 and 1/2 I omega^2 = 1.9625, and the re-pointed
        arm reads KE-T 98.13 (+0.005 %) / KE-R 1.963 (+0.026 %) where the
        control reads 0.000 / 0.000.
        """
        res, s = _convert(_ivg_deck(omega=100.0))
        self.assertEqual(len(_inivel_group(s)), 1)
        # the angular velocity really is on the card (VR, card 2 field 4)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/INIVEL/AXIS/"))
        data = [ln for ln in lines[i + 1:i + 8] if not ln.startswith("#")]
        self.assertAlmostEqual(float(data[2][60:80]), 100.0)

    def test_a_mixed_ivg_is_split_in_place(self):
        """pipe.k's shape: the group spans a deformable and a rigid part."""
        res, s = _convert(_ivg_deck(styp=3, sid=5, v=(1000.0, 0.0, 0.0),
                                    set_nodes=list(range(1, 9))
                                    + list(range(9, 17))))
        members = set(_inivel_group(s))
        self.assertTrue(set(range(1, 9)) <= members, sorted(members))
        self.assertEqual(members & set(range(9, 17)), set(), sorted(members))
        self.assertEqual(len(members), 9, sorted(members))
        w = [x for x in res.warnings
             if "*INITIAL_VELOCITY_GENERATION" in x and "RE-POINTED" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("the deformable nodes unchanged", w[0])

    def test_a_partly_covered_body_is_refused_and_named(self):
        """Vol I R17 p.28-129 Remark 3 makes LS-DYNA's answer a MASS-weighted
        momentum average over the WHOLE body — k2rad has no nodal masses at
        conversion time and will not invent one."""
        res, s = _convert(_ivg_deck(styp=3, sid=5, v=(1000.0, 0.0, 0.0),
                                    set_nodes=[9, 10, 11, 12]))
        members = set(_inivel_group(s))
        self.assertEqual(members, {9, 10, 11, 12}, sorted(members))
        w = [x for x in res.warnings if "NOT every element node" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("p.28-129 Remark 3", w[0])
        self.assertIn("*INITIAL_VELOCITY_RIGID_BODY", w[0])

    def test_a_wholly_deformable_ivg_says_nothing(self):
        res, s = _convert(_ivg_deck(styp=3, sid=5, v=(1000.0, 0.0, 0.0),
                                    set_nodes=list(range(1, 9))))
        self.assertEqual(sorted(_inivel_group(s)), list(range(1, 9)))
        self.assertEqual([x for x in res.warnings
                          if "*INITIAL_VELOCITY_GENERATION" in x
                          and ("rigid body" in x or "RE-POINTED" in x)], [])

    def test_the_round_two_nsid_repoint_is_unchanged(self):
        """The ``*INITIAL_VELOCITY`` NSID form keeps behaving as round 2 left
        it: an all-rigid group collapses onto the one main node."""
        deck = _ivg_deck(v=(1000.0, 0.0, 0.0)).replace(
            "*INITIAL_VELOCITY_GENERATION\n"
            + _row(2, 2, 0.0, 1000.0, 0.0, 0.0, 0, 0) + "\n"
            + _row(50.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0) + "\n",
            "*SET_NODE_LIST\n" + _row(88) + "\n"
            + _row(*range(9, 17)) + "\n"
            + "*INITIAL_VELOCITY\n" + _row(88) + "\n"
            + _row(1000.0, 0.0, 0.0) + "\n")
        res, s = _convert(deck)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/INIVEL/TRA/"))
        data = [ln for ln in lines[i + 1:i + 8] if not ln.startswith("#")]
        grnod = int(data[1][60:70])
        h = lines.index(f"/GRNOD/NODE/{grnod}")
        members = [int(t) for t in lines[h + 2].split()]
        self.assertEqual(len(members), 1, members)
        self.assertIn(f"/RBODY/{members[0]}", s)


# ═════════════════════════════════════════════════════════════════════════════
# PART B — item E: ELFORM 5/6/7 stay LAGRANGIAN, named
# ═════════════════════════════════════════════════════════════════════════════

class OnePointAleElformIsNamedNotMapped(unittest.TestCase):
    """The measured NO-GO. Three carriers, four arms, all worse or fatal:
    ``hm_read_prop14.F:264-267`` refuses ``Iale /= 0`` on any Isolid but 1 or 2
    (ERROR 131 + 608 — 9 starter errors on taylor_B, 4 on advection_B), and
    with Isolid 1 the remap took taylor_B from IE +5.1 %% / KE +4.9 %% against
    its LS-DYNA reference to a 99.9 %% energy error at 198 220 cycles.
    """

    def test_iale_stays_zero(self):
        for ef in (5, 6, 7):
            with self.subTest(elform=ef):
                _, s = _convert(_hg_deck(elform=ef))
                lines = s.splitlines()
                i = lines.index("/PROP/SOLID/1")
                card = [ln for ln in lines[i + 1:i + 9]
                        if not ln.startswith("#")][1]
                self.assertEqual(int(card[20:30]), 0)     # Iale

    def test_the_warning_names_the_measurement_and_the_source(self):
        res, _ = _convert(_hg_deck(elform=5))
        w = [x for x in res.warnings if "ELFORM=5" in x and "LAGRANGIAN" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("hm_read_prop14.F:264-267", w[0])
        self.assertIn("ERROR 131", w[0])
        self.assertIn("solid formulation = 11", w[0])
        self.assertIn("/ALE/GRID", w[0])
        self.assertIn("HOURGLASS control IS carried", w[0])

    def test_elform_seven_names_its_dropped_ambient_type(self):
        res, _ = _convert(_hg_deck(elform=7))
        w = [x for x in res.warnings if "ELFORM=7" in x][0]
        self.assertIn("AET", w)

    def test_elform_eleven_still_maps_to_iale_one(self):
        """The negative control: the ALE ELFORMs k2rad DOES map are untouched."""
        _, s = _convert(_hg_deck(elform=11))
        lines = s.splitlines()
        i = lines.index("/PROP/SOLID/1")
        card = [ln for ln in lines[i + 1:i + 9] if not ln.startswith("#")][1]
        self.assertEqual(int(card[20:30]), 1)             # Iale


# ═════════════════════════════════════════════════════════════════════════════
# PART B — item F: /IMPL/DT/FIXPOINT off by default
# ═════════════════════════════════════════════════════════════════════════════

class ImplicitFixpointGridIsOptIn(unittest.TestCase):
    """The milestone grid is a k2rad convenience LS-DYNA never asks for, and it
    makes the adaptive implicit step oscillate against ``/IMPL/DT/2``.
    MEASURED: ten R14 reference decks that died ``** ERROR: SOLVER IMPLICIT
    STOPPED DUE TO TIMESTEP LIMIT **`` reach NORMAL TERMINATION without it.
    """

    def _engine(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "impl.k")
        with open(path, "w") as fh:
            fh.write(_hg_deck(implicit=True))
        res = convert(path, write_log=False, **kw)
        with open(res.engine_path) as fh:
            return fh.read()

    def test_no_fixpoint_card_by_default(self):
        self.assertNotIn("/IMPL/DT/FIXPOINT", self._engine())

    def test_the_rest_of_the_implicit_block_is_unchanged(self):
        eng = self._engine()
        self.assertIn("/IMPL/DT/2", eng)
        self.assertNotIn("/IMPL/DT/3", eng)

    def test_an_explicit_deck_never_had_the_card(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "x.k")
        with open(path, "w") as fh:
            fh.write(_hg_deck())
        res = convert(path, write_log=False)
        with open(res.engine_path) as fh:
            self.assertNotIn("/IMPL", fh.read())

    def test_asking_for_it_still_works(self):
        eng = self._engine(fixpoint_count=10)
        self.assertIn("/IMPL/DT/FIXPOINT", eng)
        i = eng.splitlines().index("/IMPL/DT/FIXPOINT")
        vals = []
        for ln in eng.splitlines()[i + 1:]:
            if not ln.strip() or ln.startswith(("/", "#")):
                break
            vals.extend(float(t) for t in ln.split())
        self.assertEqual(len(vals), 10)


if __name__ == "__main__":
    unittest.main()
