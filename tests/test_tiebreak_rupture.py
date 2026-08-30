"""``*CONTACT_..._TIEBREAK`` -> ``/INTER/TYPE2`` (+ rupture, + companion).

The defining decision of this batch, and the silent loss it removes:

    LS-DYNA Vol I R17 p.11-9 --- "TIEBREAK is a special case of a tied contact
    allowing failure in which the contact usually becomes a regular one-way,
    two-way, or single surface version after failure."

So the PRE-failure state of every spelling in the family is a TIE. The
pre-#131 converter routed four of the thirteen spellings to a plain
``/INTER/TYPE7`` --- a sliding penalty contact with no bond at all --- and left
the other nine in ``skipped_keywords``. Both losses are load-path losses, not
output-card losses: the tied joint simply was not in the converted model, from
t = 0, and on ``plates.tied.k`` (``*CONTACT_TIEBREAK_NODES_ONLY``, the only
joint between the two plates) it vanished with no warning whatsoever.

What can and cannot be reproduced, measured rather than assumed:

* OpenRadioss releases a ``/INTER/TYPE2`` tie on DISPLACEMENT and nothing else
  (``ruptint2.F:138``, ``Rupt = 2``: ``IRUPT = 1`` when ``|d_n| > Max_N_Dist``
  or ``d_t > Max_T_Dist``). The stress functions only CAP the transmitted
  traction (``:130-136``). So only an OPTION that states a RELEASE DISTANCE can
  be converted with its failure intact --- OPTION 6 and 8, whose
  ``PARAM = CCRIT`` is exactly that ("when the distance equals PARAM, damage is
  fully developed, and interface failure occurs", p.11-37).
* Everything else becomes a permanent auto-penalty tie with a NAMED warn-drop.
* The rupture Spotflags 20/21/22 are KINEMATIC (``hm_read_inter_type02.F:343``
  gates the rupture cards on them, ``:301`` gates the penalty card on
  25/26/27/28 --- disjoint sets), so a conformally meshed pair would be
  ERROR 556. That is guarded at conversion time.

Solver evidence quoted in the CHANGELOG entry; the two scaling twins are the
load-bearing ones (NFLS 50 -> 100 moved START RUPTURE from 6.60566149E-04 s to
1.32113230E-03 s, ratio exactly 2.000000).
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import (
    HANDLERS, TIEBREAK_CONTACT_KEYWORDS, _TIEBREAK_BASES,
    _TIEBREAK_OPTION_CLASS, _TIEBREAK_SUFFIXES, _tiebreak_card4_extra,
    _tiebreak_spelling, dispatch,
)
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState
from k2rad.writer.contacts import (
    _TIEBREAK_RUPTURE_CLASSES, _TIEBREAK_TIE_SPOTFLAG, _emit_inter_type2,
    _tiebreak_bond_class,
)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers (same shape as tests/test_eroding_contacts.py)
# ═════════════════════════════════════════════════════════════════════════════

def _convert(deck: str, **opts):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **opts)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _convert_both(deck: str, **opts):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "deck.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, write_log=False, **opts)
        return (result,
                Path(result.starter_path).read_text(),
                Path(result.engine_path).read_text())


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
    """The lines of one /KEYWORD/id block, header line first."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            out = [ln]
            for nxt in lines[i + 1:]:
                if nxt.startswith("#---"):
                    break
                out.append(nxt)
            return out
    return []


def _cards(block):
    """Data lines of a block (no header, no title, no # comments)."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


#: Two separate 10-mm bricks: part 1 on nodes 1-8, part 2 on nodes 11-18. The
#: two parts share NO node, so the ERROR 556 conformal guard does not fire.
_MESH = """*NODE
         1               0.0               0.0               0.0
         2              10.0               0.0               0.0
         3              10.0              10.0               0.0
         4               0.0              10.0               0.0
         5               0.0               0.0              10.0
         6              10.0               0.0              10.0
         7              10.0              10.0              10.0
         8               0.0              10.0              10.0
        11               0.0               0.0              10.0
        12              10.0               0.0              10.0
        13              10.0              10.0              10.0
        14               0.0              10.0              10.0
        15               0.0               0.0              20.0
        16              10.0               0.0              20.0
        17              10.0              10.0              20.0
        18               0.0              10.0              20.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
       2       2      11      12      13      14      15      16      17      18
*PART
lower
         1         1         1
*PART
upper
         2         1         1
*SECTION_SOLID
         1         1
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
"""

#: The same two parts CONFORMALLY meshed: element 2 reuses nodes 5-8.
_MESH_CONFORMAL = """*NODE
         1               0.0               0.0               0.0
         2              10.0               0.0               0.0
         3              10.0              10.0               0.0
         4               0.0              10.0               0.0
         5               0.0               0.0              10.0
         6              10.0               0.0              10.0
         7              10.0              10.0              10.0
         8               0.0              10.0              10.0
         9               0.0               0.0              20.0
        10              10.0               0.0              20.0
        11              10.0              10.0              20.0
        12               0.0              10.0              20.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
       2       2       5       6       7       8       9      10      11      12
*PART
lower
         1         1         1
*PART
upper
         2         1         1
*SECTION_SOLID
         1         1
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
"""

_TAIL = "*CONTROL_TERMINATION\n     0.001\n*END\n"


def _auto_tiebreak(option, nfls, sfls, param, cid=20, extra_cards="",
                   keyword="CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK",
                   eraten=0.0, erates=0.0, ct2cn=0.0, cn=0.0):
    """An AUTOMATIC-family tiebreak card with a DISTINCT number per Card-4 slot
    so a column swap cannot pass."""
    return (
        f"*{keyword}_ID\n"
        f"{cid:>10}glue joint\n"
        "         1         2         3         3         0         0         0         0\n"
        "       0.3       0.2       0.0       0.0       0.0         0       0.0       0.0\n"
        "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
        f"{option:>10}{nfls:>10}{sfls:>10}{param:>10}"
        f"{eraten:>10}{erates:>10}{ct2cn:>10}{cn:>10}\n" + extra_cards)


# ═════════════════════════════════════════════════════════════════════════════
# 1. Spelling coverage from ONE source (#116)
# ═════════════════════════════════════════════════════════════════════════════

class TiebreakSpellingCoverage(unittest.TestCase):
    """The dispatch table and assembly._OFFSET_SPECS must cover exactly the set
    ``TIEBREAK_CONTACT_KEYWORDS`` generates. A hand-kept second list is how a
    legal spelling silently vanishes into ``skipped_keywords`` --- and a
    skipped *CONTACT is a missing LOAD PATH, not a missing output card."""

    def test_generator_covers_the_whole_family(self):
        # Vol I R17 p.11-14 lists eleven tiebreak spellings, p.11-14/15 two
        # Mortar ones. k2rad reaches all thirteen; _MPP doubles the count.
        bases = set()
        for kw in TIEBREAK_CONTACT_KEYWORDS:
            base, *_ = _tiebreak_spelling(kw)
            bases.add(base)
        self.assertEqual(bases, set(_TIEBREAK_BASES))
        self.assertEqual(len(TIEBREAK_CONTACT_KEYWORDS), 26)
        for named in (
                "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK",
                "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_USER",
                "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_MORTAR",
                "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_USER_MORTAR",
                "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK",
                "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK_DAMPING",
                "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK_USER",
                "CONTACT_AUTOMATIC_SINGLE_SURFACE_TIEBREAK",
                "CONTACT_AUTOMATIC_GENERAL_TIEBREAK",
                "CONTACT_TIEBREAK_NODES_TO_SURFACE",
                "CONTACT_TIEBREAK_NODES_ONLY",
                "CONTACT_TIEBREAK_SURFACE_TO_SURFACE",
                "CONTACT_TIEBREAK_SURFACE_TO_SURFACE_ONLY"):
            with self.subTest(kw=named):
                self.assertIn(named, TIEBREAK_CONTACT_KEYWORDS)
                self.assertIn(f"{named}_MPP", TIEBREAK_CONTACT_KEYWORDS)

    def test_every_spelling_is_dispatched(self):
        for kw in TIEBREAK_CONTACT_KEYWORDS:
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_offset_specs_cover_the_same_set_minus_mpp(self):
        """_off_contact rewrites b.raw[start] blind, so the _MPP spellings ---
        whose MPP card pushes Card 1 down a line --- are deliberately left out
        and fall to the unmapped warn, exactly as the spotweld and eroding
        grammars do."""
        want = {kw for kw in TIEBREAK_CONTACT_KEYWORDS if "_MPP" not in kw}
        have = {kw for kw in TIEBREAK_CONTACT_KEYWORDS if kw in _OFFSET_SPECS}
        self.assertEqual(have, want)
        for kw in TIEBREAK_CONTACT_KEYWORDS:
            if "_MPP" in kw:
                with self.subTest(kw=kw):
                    self.assertNotIn(kw, _OFFSET_SPECS)

    def test_longest_base_wins(self):
        """_ONLY must not be swallowed by its own prefix."""
        for kw, want in (
                ("CONTACT_TIEBREAK_SURFACE_TO_SURFACE_ONLY",
                 "CONTACT_TIEBREAK_SURFACE_TO_SURFACE_ONLY"),
                ("CONTACT_TIEBREAK_SURFACE_TO_SURFACE",
                 "CONTACT_TIEBREAK_SURFACE_TO_SURFACE"),
                ("CONTACT_TIEBREAK_NODES_ONLY_MPP",
                 "CONTACT_TIEBREAK_NODES_ONLY"),
                ("CONTACT_TIEBREAK_NODES_TO_SURFACE",
                 "CONTACT_TIEBREAK_NODES_TO_SURFACE")):
            with self.subTest(kw=kw):
                self.assertEqual(_tiebreak_spelling(kw)[0], want)

    def test_suffix_flags(self):
        base, mortar, user, damping, mpp = _tiebreak_spelling(
            "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_USER_MORTAR_MPP")
        self.assertEqual(base, "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK")
        self.assertTrue(mortar and user and mpp)
        self.assertFalse(damping)
        # The DAMPING option cannot be combined with MORTAR (p.11-35), so no
        # generated spelling carries both.
        for kw in TIEBREAK_CONTACT_KEYWORDS:
            _, mo, _, da, _ = _tiebreak_spelling(kw)
            with self.subTest(kw=kw):
                self.assertFalse(mo and da)

    def test_suffix_table_keys_are_real_bases(self):
        self.assertEqual(set(_TIEBREAK_SUFFIXES) - set(_TIEBREAK_BASES), set())


# ═════════════════════════════════════════════════════════════════════════════
# 2. The mandatory Card 4 shifts the optional-card stack (the fixed defect)
# ═════════════════════════════════════════════════════════════════════════════

class Card4ShiftsTheOptionalStack(unittest.TestCase):
    """Vol I R17 p.11-6 lists Card 4 as MANDATORY for the tiebreak family and
    p.11-7 adds "the format of Card 4 (which can include multiple cards) is
    different for each option listed"; optional Cards A-G follow AFTER it.

    Reading them unshifted lands IGNORE (optional Card C field 1) on optional
    Card B field 1 = THKOPT. Proven with a with/without twin: two decks
    identical except for the presence of Card 4."""

    #: Card A / Card B (THKOPT = 3) / Card C (IGNORE = 2).
    OPTIONAL = (
        "         1       1.0         0       0.0         1         1         1         1\n"
        "       0.0         3         0         0         0         0       0.0       0.0\n"
        "         0         2       0.0       0.0                           0.0         0\n")

    PLAIN = (
        "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n"
        "        60twin plain\n"
        "         1         2         3         3         0         0         0         0\n"
        "       0.3       0.2       0.0       0.0       0.0         0       0.0       0.0\n"
        "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
        + OPTIONAL)

    def _ignore_line(self, deck):
        result, _ = _convert("*KEYWORD\n" + _MESH + deck + _TAIL)
        hits = [w for w in result.warnings if "ignore=" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        return hits[0]

    def test_tiebreak_reads_the_same_ignore_as_the_plain_twin(self):
        # OPTION 4 keeps the penalty-contact route, which is the one that reads
        # IGNORE at all --- so this is the branch where the shift is visible.
        tb = _auto_tiebreak(4, "1000.0", "1000.0", "0.0", cid=60,
                            extra_cards=self.OPTIONAL)
        self.assertIn("ignore=2", self._ignore_line(tb))
        self.assertIn("ignore=2", self._ignore_line(self.PLAIN))

    def test_thkopt_is_not_read_as_ignore(self):
        """The other direction: Card B THKOPT = 1 must NOT surface as
        ignore=1 when Card C says IGNORE = 0."""
        optional = (
            "         1       1.0         0       0.0         1         1         1         1\n"
            "       0.0         1         0         0         0         0       0.0       0.0\n"
            "         0         0       0.0       0.0                           0.0         0\n")
        tb = _auto_tiebreak(4, "1000.0", "1000.0", "0.0", cid=60,
                            extra_cards=optional)
        self.assertIn("ignore=0", self._ignore_line(tb))

    def test_extra_counts_the_further_mandatory_cards(self):
        """Card 4.1a (OPTION 9/11 + _DAMPING) and Cards 4.1b + 4.2b
        (OPTION 13/14) sit between Card 4 and optional Card A too."""
        self.assertEqual(_tiebreak_card4_extra("AUTOMATIC", 6, False), 1)
        self.assertEqual(_tiebreak_card4_extra("SURFACE", 2, False), 1)
        self.assertEqual(_tiebreak_card4_extra("NODES", 0, False), 1)
        # DAMPING alone is not enough: p.11-35 scopes card 4.1a to OPTION 9/11.
        self.assertEqual(_tiebreak_card4_extra("AUTOMATIC", 6, True), 1)
        self.assertEqual(_tiebreak_card4_extra("AUTOMATIC", 9, True), 2)
        self.assertEqual(_tiebreak_card4_extra("AUTOMATIC", 11, True), 2)
        self.assertEqual(_tiebreak_card4_extra("AUTOMATIC", 13, False), 3)
        self.assertEqual(_tiebreak_card4_extra("AUTOMATIC", 14, False), 3)


# ═════════════════════════════════════════════════════════════════════════════
# 3. The *CONTACT_*_ID header is FIXED format (the second fixed defect)
# ═════════════════════════════════════════════════════════════════════════════

class ContactIdHeaderIsFixedFormat(unittest.TestCase):
    """``CARD("%10d%-70s", _ID_, TITLE)`` --- LS-PrePost butts the title
    against the id, and a free split of "        10Kurbel self tiebreak
    contact" yields the token ``10Kurbel``, which reads back as id 0."""

    def test_butted_title_keeps_the_deck_id(self):
        deck = ("*KEYWORD\n" + _MESH
                + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_ID\n"
                  "        10Kurbel self tiebreak contact\n"
                  "         1         2         3         3         0         0         0         0\n"
                  "       0.3       0.2       0.0       0.0       0.0         0       0.0       0.0\n"
                  "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                  "         1    1000.0    1000.0       0.0       1.0       0.0       0.0       0.0\n"
                + _TAIL)
        _, starter = _convert(deck)
        block = _block(starter, "/INTER/TYPE2/10")
        self.assertTrue(block, starter)
        self.assertEqual(block[1], "Kurbel self tiebreak contact")

    def test_space_separated_header_still_free_parses(self):
        deck = ("*KEYWORD\n" + _MESH
                + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_ID\n"
                  "77, free format title\n"
                  "         1         2         3         3         0         0         0         0\n"
                  "       0.3       0.2       0.0       0.0       0.0         0       0.0       0.0\n"
                  "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                  "         1    1000.0    1000.0       0.0       1.0       0.0       0.0       0.0\n"
                + _TAIL)
        _, starter = _convert(deck)
        self.assertTrue(_block(starter, "/INTER/TYPE2/77"), starter)


# ═════════════════════════════════════════════════════════════════════════════
# 4. OPTION classification and routing
# ═════════════════════════════════════════════════════════════════════════════

class OptionClassification(unittest.TestCase):
    def test_every_documented_option_has_a_class(self):
        """Vol I R17 p.11-36..11-38 enumerates -11, -9, -3..-1, 1..11, 13, 14
        (12 is absent from the manual's own list)."""
        want = {-11, -9, -3, -2, -1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14}
        self.assertEqual(set(_TIEBREAK_OPTION_CLASS), want)

    def test_only_ccrit_is_rupture_expressible(self):
        """Radioss releases on DISPLACEMENT only, so the class must state one.
        6 and 8 are the OPTIONs whose PARAM IS that distance."""
        self.assertEqual(_TIEBREAK_RUPTURE_CLASSES, ("CCRIT",))
        ccrit = {o for o, (cls, _) in _TIEBREAK_OPTION_CLASS.items()
                 if cls == "CCRIT"}
        self.assertEqual(ccrit, {6, 8})

    def test_tie_spotflags_are_auto_penalty(self):
        """chktyp2.F:82 tags secondary nodes of every TYPE2 outside
        {25,26,27,28} and any MAIN node so tagged is ERROR 556."""
        for family, sf in _TIEBREAK_TIE_SPOTFLAG.items():
            with self.subTest(family=family):
                self.assertIn(sf, (25, 26, 27, 28))

    def test_option_4_keeps_the_penalty_contact(self):
        """"tangential motion with frictional sliding is permitted" --- the
        LS-DYNA pre-failure state is not a tie, and /INTER/TYPE2 always
        inhibits tangential motion, so a tie would OVER-constrain it."""
        state = _dispatch("*KEYWORD\n" + _MESH
                          + _auto_tiebreak(4, "1000.0", "1000.0", "0.0")
                          + _TAIL)
        self.assertEqual(len(state.contacts_tiebreak), 0)
        self.assertEqual(len(state.contacts_surf2surf), 1)
        self.assertTrue(any("OPTION 4" in w and "OVER-constrain" in w
                            for w in state.warnings), state.warnings)

    def test_self_tiebreak_keeps_the_self_contact(self):
        """i2trivox.F90:233-234 skips a secondary node that is a corner of the
        candidate main segment, so a surface tied to itself is an EMPTY tie."""
        deck = ("*KEYWORD\n" + _MESH
                + "*CONTACT_AUTOMATIC_SINGLE_SURFACE_TIEBREAK\n"
                  "         0         0         5         0         0         0         0         0\n"
                  "       0.3       0.2       0.0       0.0       0.0         0       0.0       0.0\n"
                  "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                  "         2    1000.0    1000.0       0.0       0.0       0.0       0.0       0.0\n"
                + _TAIL)
        state = _dispatch(deck)
        self.assertEqual(len(state.contacts_tiebreak), 0)
        self.assertEqual(len(state.contacts_single), 1)
        self.assertTrue(any("SELF-tiebreak" in w and "EMPTY tie" in w
                            for w in state.warnings), state.warnings)

    def test_tie_classes_land_in_contacts_tiebreak(self):
        for option in (1, -1, 2, -2, 3, -3, 5, 6, 7, 8, 9, 10, 11, 13, 14):
            with self.subTest(option=option):
                state = _dispatch(
                    "*KEYWORD\n" + _MESH
                    + _auto_tiebreak(option, "50.0", "20.0", "0.005") + _TAIL)
                self.assertEqual(len(state.contacts_tiebreak), 1)
                self.assertEqual(state.contacts_tiebreak[0].option, option)

    def test_surface_family_is_rewritten_onto_the_option_enumeration(self):
        """p.11-72 THKOFF: "It works by substituting with
        *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK (OPTION = 2 if TBLCID is
        not specified; OPTION = 5 if TBLCID is specified)." """
        base = ("*CONTACT_TIEBREAK_SURFACE_TO_SURFACE\n"
                "         1         2         3         3         0         0         0         0\n"
                "       0.0       0.0       0.0       0.0       0.0         0       0.0       0.0\n"
                "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                "     100.0     200.0%s         0\n")
        for tblcid, want in (("         0", 2), ("         7", 5)):
            with self.subTest(tblcid=tblcid.strip()):
                state = _dispatch("*KEYWORD\n" + _MESH + base % tblcid + _TAIL)
                self.assertEqual(state.contacts_tiebreak[0].option, want)

    def test_nodes_family_reads_forces_not_stresses(self):
        deck = ("*KEYWORD\n" + _MESH
                + "*CONTACT_TIEBREAK_NODES_ONLY\n"
                  "         1         2         3         3         0         0         0         0\n"
                  "       0.0       0.0       0.0       0.0       0.0         0       0.0       0.0\n"
                  "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                  "   10000.0   50000.0       1.0       3.0\n"
                + _TAIL)
        c = _dispatch(deck).contacts_tiebreak[0]
        self.assertEqual(c.family, "NODES")
        self.assertTrue(c.only)
        # Distinct number per slot: a swap would show.
        self.assertEqual((c.nflf, c.sflf, c.nen, c.mes),
                         (10000.0, 50000.0, 1.0, 3.0))
        self.assertEqual((c.nfls, c.sfls), (0.0, 0.0))
        self.assertEqual(_tiebreak_bond_class(c), "FORCE")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Column-exact rupture cards
# ═════════════════════════════════════════════════════════════════════════════

class RuptureCardColumns(unittest.TestCase):
    """``inter_type2.cfg`` FORMAT(radioss2017), gated
    ``if (WFLAG==20 || WFLAG==21 || WFLAG==22)``::

        %10d%10d%10d%10d%10d%10d%20lg%20lg
        Rupt Ifiltr fct_IDsr fct_IDsn fct_IDst Isym Max_N_Dist Max_T_Dist
        %20lg%20lg%20lg%20lg%20lg
        Fscalestress Fscalestr_rate Fscaledist Alpha Area

    Every value below is DISTINCT so a slot swap cannot pass, and the starter
    echo on the same deck reads back SCAL_F 50.0 / DN_MAX 5.0E-03 / IFUNN 90003
    / IFUNT 90004 / IMOD 2 / ISYM 1 / IFILTR 0."""

    def test_emitter_columns(self):
        lines = _emit_inter_type2(
            41, "bond", 101, 202, 22, 0.75,
            rupture=(9001, 9002, 12.5, 0.004, 0.006))
        self.assertEqual(lines[0], "/INTER/TYPE2/41")
        cards = _cards(lines)
        # Card 1: grnd surf Ignore Spotflag Level Isearch Idel2 <10 blank> dsearch
        self.assertEqual(
            cards[0],
            "       101       202         2        22         0         2"
            "         0                          0.75")
        # Card 2 (rupture): Rupt=2, Ifiltr=0, fct_IDsr=0, sn, st, Isym=1
        self.assertEqual(
            cards[1],
            "         2         0         0      9001      9002         1"
            "               0.004               0.006")
        # Card 3: Fscalestress, Fscalestr_rate=0, Fscaledist=1, Alpha=0, Area=0
        self.assertEqual(
            cards[2],
            "                12.5                   0                   1"
            "                   0                   0")
        # And no penalty card: 20/21/22 and 25/26/27/28 are disjoint.
        self.assertEqual(len(cards), 3)

    def test_penalty_spotflag_takes_the_other_card(self):
        cards = _cards(_emit_inter_type2(41, "tie", 101, 202, 27, 0.0))
        self.assertEqual(len(cards), 2)
        self.assertEqual(
            cards[1],
            "                   1                0.05                    "
            "         2")

    def test_rupture_payload_ignored_on_a_penalty_spotflag(self):
        """The two card sets are mutually exclusive in the reader
        (hm_read_inter_type02.F:343 vs :301), so the emitter must not write a
        rupture card under Spotflag 27 even if a caller passes one."""
        cards = _cards(_emit_inter_type2(41, "tie", 101, 202, 27, 0.0,
                                         rupture=(1, 2, 3.0, 4.0, 5.0)))
        self.assertEqual(len(cards), 2)


class RuptureEmission(unittest.TestCase):
    DECK = ("*KEYWORD\n" + _MESH
            + _auto_tiebreak(6, "50.0", "20.0", "0.005") + _TAIL)

    def setUp(self):
        self.result, self.starter = _convert(self.DECK)

    def test_type2_carries_the_rupture_cards(self):
        cards = _cards(_block(self.starter, "/INTER/TYPE2/20"))
        self.assertEqual(len(cards), 3)
        # Spotflag 22 = brick faces only (the secondary side is solid).
        self.assertEqual(cards[0][30:40], "        22")
        # Rupt=2 (Rupt=1 is dimensionally broken), Isym=1 (tension only).
        self.assertEqual(cards[1][0:10], "         2")
        self.assertEqual(cards[1][50:60], "         1")
        # PARAM (CCRIT) 1:1 into BOTH release distances.
        self.assertEqual(cards[1][60:80].strip(), "0.005")
        self.assertEqual(cards[1][80:100].strip(), "0.005")
        # NFLS 1:1 into Fscalestress; Fscaledist = 1 (abscissae in length units).
        self.assertEqual(cards[2][0:20].strip(), "50")
        self.assertEqual(cards[2][40:60].strip(), "1")

    def test_the_two_functions_are_the_damage_ramp(self):
        """ruptint2.F:130-131 --- SIGNMAX = SCAL_F * f_sn(|d_n| / SCAL_D). With
        SCAL_F = NFLS the normal ramp is 1 -> 0 over [0, CCRIT] and the shear
        one starts at SFLS/NFLS = 20/50 = 0.4, a ratio of two card cells and
        not a conversion factor."""
        cards = _cards(_block(self.starter, "/INTER/TYPE2/20"))
        fct_sn = int(cards[1][30:40])
        fct_st = int(cards[1][40:50])
        self.assertNotEqual(fct_sn, fct_st)
        sn = _cards(_block(self.starter, f"/FUNCT/{fct_sn}"))
        st = _cards(_block(self.starter, f"/FUNCT/{fct_st}"))
        self.assertEqual([ln.split() for ln in sn],
                         [["0", "1"], ["0.005", "0"], ["0.01", "0"]])
        self.assertEqual([ln.split() for ln in st],
                         [["0", "0.4"], ["0.005", "0"], ["0.01", "0"]])

    def test_function_ids_dodge_the_funct_table_namespace(self):
        """/FUNCT and /TABLE are ONE starter id namespace (ERROR 79), so the
        two synthesized curves come from state.next_curve_id()."""
        cards = _cards(_block(self.starter, "/INTER/TYPE2/20"))
        ids = {int(cards[1][30:40]), int(cards[1][40:50])}
        emitted = [ln for ln in self.starter.splitlines()
                   if ln.startswith(("/FUNCT/", "/TABLE/"))]
        for fid in ids:
            self.assertIn(f"/FUNCT/{fid}", emitted)
        # no duplicate-id warning from the deck-wide scan
        self.assertFalse([w for w in self.result.warnings
                          if "CURVE ID" in w and "more than one card" in w])

    def test_shell_secondary_side_picks_spotflag_21(self):
        """i2surfs.F:70-73 --- ILEV 21 zeroes the SOLID contribution, so a node
        with no attached shell would be ERROR 670. The Spotflag follows the
        secondary side's element census."""
        shell_mesh = _MESH.replace(
            "*SECTION_SOLID\n         1         1\n",
            "*SECTION_SOLID\n         1         1\n"
            "*SECTION_SHELL\n         3         2\n       1.0\n")
        shell_mesh = shell_mesh.replace(
            "*PART\nlower\n         1         1         1\n",
            "*PART\nlower\n         1         3         1\n")
        shell_mesh = shell_mesh.replace(
            "*ELEMENT_SOLID\n"
            "       1       1       1       2       3       4       5       6       7       8\n",
            "*ELEMENT_SHELL\n       1       1       1       2       3       4\n"
            "*ELEMENT_SOLID\n")
        _, starter = _convert("*KEYWORD\n" + shell_mesh
                              + _auto_tiebreak(6, "50.0", "20.0", "0.005")
                              + _TAIL)
        cards = _cards(_block(starter, "/INTER/TYPE2/20"))
        self.assertEqual(cards[0][30:40], "        21")


# ═════════════════════════════════════════════════════════════════════════════
# 6. The refusal guards --- each downgrades to a permanent tie, loudly
# ═════════════════════════════════════════════════════════════════════════════

class RuptureRefusals(unittest.TestCase):
    def _tie_only(self, starter, cid=20):
        cards = _cards(_block(starter, f"/INTER/TYPE2/{cid}"))
        self.assertEqual(len(cards), 2, cards)     # card 1 + the penalty card
        self.assertEqual(cards[0][30:40], "        27")
        return cards

    def test_conformal_mesh_falls_back_to_the_auto_penalty_tie(self):
        """The two surfaces share nodes 5-8, so Spotflag 20/21/22 would raise
        ERROR 556 for each of them (chktyp2.F:82/98). MEASURED on the same
        mesh: Spotflag 5 and 22 gave 3 x ERROR 556 + ERROR TERMINATION, 27 and
        28 gave 0 errors and NORMAL TERMINATION."""
        result, starter = _convert(
            "*KEYWORD\n" + _MESH_CONFORMAL
            + _auto_tiebreak(6, "50.0", "20.0", "0.005") + _TAIL)
        self._tie_only(starter)
        hit = [w for w in result.warnings if "CONFORMALLY meshed" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("4 node(s)", hit[0])
        self.assertIn("ERROR 556", hit[0])

    def test_nonconformal_twin_does_rupture(self):
        """The other half of the split: the identical card on a mesh whose two
        parts share no node gets the rupture cards."""
        _, starter = _convert("*KEYWORD\n" + _MESH
                              + _auto_tiebreak(6, "50.0", "20.0", "0.005")
                              + _TAIL)
        self.assertEqual(len(_cards(_block(starter, "/INTER/TYPE2/20"))), 3)

    def test_missing_ccrit_is_named(self):
        result, starter = _convert("*KEYWORD\n" + _MESH
                                   + _auto_tiebreak(6, "50.0", "20.0", "0.0")
                                   + _TAIL)
        self._tie_only(starter)
        self.assertTrue(any("PARAM = CCRIT" in w for w in result.warnings),
                        result.warnings)

    def test_zero_nfls_or_sfls_is_refused_not_written(self):
        """"Both NFLS and SFLS must be defined" (p.11-73 Remark 2), and the
        manual's idiom for "no failure in this mode" is 1e10, never 0. A zero
        cannot be written either: hm_read_inter_type02.F:373 turns
        Fscalestress = 0 into ONE pressure unit."""
        for nfls, sfls in (("0.0", "20.0"), ("50.0", "0.0")):
            with self.subTest(nfls=nfls, sfls=sfls):
                result, starter = _convert(
                    "*KEYWORD\n" + _MESH
                    + _auto_tiebreak(6, nfls, sfls, "0.005") + _TAIL)
                self._tie_only(starter)
                self.assertTrue(any("must be defined" in w
                                    for w in result.warnings), result.warnings)

    def test_implicit_deck_refuses_the_rupture(self):
        """Reference Guide p.1947 Comment 6: "This failure option (Spotflag =
        20, 21 or 22) can not be used in implicit." """
        deck = ("*KEYWORD\n" + _MESH
                + _auto_tiebreak(6, "50.0", "20.0", "0.005")
                + "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n" + _TAIL)
        result, starter = _convert(deck)
        self._tie_only(starter)
        self.assertTrue(any("can not be used in implicit" in w
                            for w in result.warnings), result.warnings)

    def test_dt_noda_cst_deck_refuses_the_rupture(self):
        """Same Comment 6: "not compatible with nodel time step /DT/NODA/CST".
        Neither the starter nor the engine checks it, so this is a
        conversion-time refusal."""
        deck = ("*KEYWORD\n" + _MESH
                + _auto_tiebreak(6, "50.0", "20.0", "0.005")
                + "*CONTROL_TIMESTEP\n       0.0       0.9         0"
                  "       0.0   -1.0E-7\n" + _TAIL)
        result, starter, engine = _convert_both(deck)
        self._tie_only(starter)
        self.assertIn("/DT/NODA/CST/0", engine)
        self.assertTrue(any("/DT/NODA/CST" in w and "PERMANENT tie" in w
                            for w in result.warnings), result.warnings)

    def test_dangling_secondary_side_drops_the_interface(self):
        result, starter = _convert(
            "*KEYWORD\n" + _MESH
            + _auto_tiebreak(6, "50.0", "20.0", "0.005").replace(
                "         1         2         3         3",
                "       999         2         3         3") + _TAIL)
        self.assertEqual(_block(starter, "/INTER/TYPE2/20"), [])
        self.assertTrue(any("resolved to 0 node(s)" in w
                            for w in result.warnings), result.warnings)
        self.assertTrue([kw for kw, _ in result.recognized_not_emitted
                         if "TIEBREAK" in kw], result.recognized_not_emitted)

    def test_dangling_main_side_drops_the_interface(self):
        result, starter = _convert(
            "*KEYWORD\n" + _MESH
            + _auto_tiebreak(6, "50.0", "20.0", "0.005").replace(
                "         1         2         3         3",
                "         1       999         3         3") + _TAIL)
        self.assertEqual(_block(starter, "/INTER/TYPE2/20"), [])
        self.assertTrue(any("resolved to no contact surface" in w
                            for w in result.warnings), result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# 7. Post-failure contact
# ═════════════════════════════════════════════════════════════════════════════

class PostFailureContact(unittest.TestCase):
    """p.11-39 Remark 1 --- a non-_ONLY tiebreak "behaves as a
    surface-to-surface contact" after failure; p.11-71/11-73 Remark 3 --- the
    _ONLY spellings "stop acting as a contact altogether".

    A totally ruptured /INTER/TYPE2 node is a FREE particle (``i2for10.F`` has
    branches for IRUPT==0 and IRUPT==-1 and none for IRUPT==1), so the _ONLY
    semantics are the bare tie and the others need a companion.

    MEASURED with/without on the emitted deck (break, then drive the freed body
    back down at -20 mm/s): without the companion, node 11 keeps the full
    -20.0 mm/s and sinks 0.0548034 mm through the other body; with it,
    -13.3090 mm/s and 0.0364657 mm, and the external work rises from 7.73 to
    1439 mJ."""

    def _rupture(self, keyword, **kw):
        deck = ("*KEYWORD\n" + _MESH
                + _auto_tiebreak(6, "50.0", "20.0", "0.005",
                                 keyword=keyword, **kw) + _TAIL)
        return _convert(deck)

    def test_non_only_gets_a_companion_type25(self):
        result, starter = self._rupture(
            "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK")
        t25 = [ln for ln in starter.splitlines()
               if ln.startswith("/INTER/TYPE25/")]
        self.assertEqual(len(t25), 1, starter)
        comp_id = int(t25[0].rsplit("/", 1)[1])
        cards = _cards(_block(starter, t25[0]))
        # Card 1: surf_ID1 surf_ID2 Istf Ithe Igap Irem_i2 <blank> Idel Iedge.
        # Irem_i2 = 3 ("no change to secondary nodes"). At the /DEFAULT value 1
        # the starter removes the TYPE2-tied nodes once and for all
        # (i7remnode.F:882-901) and the whole card is inert.
        self.assertEqual(cards[0][50:60], "         3")
        # Inacti = 5 keeps it inert BEFORE failure (measured onset shift
        # -0.155 %) --- card 5 cols 31-40 (blank7 + IBC 3 + blank10 + IVIS2).
        self.assertEqual(cards[4][30:40], "         5")
        # Two surfaces, not the one-way form: both sides are parts here.
        self.assertNotEqual(cards[0][0:10].strip(), "0")
        self.assertNotEqual(cards[0][10:20].strip(), "0")
        # Its id is allocated, distinct, and recorded for the registry walks.
        self.assertNotEqual(comp_id, 20)
        self.assertTrue(any(f"/INTER/TYPE25/{comp_id}" in w
                            for w in result.warnings), result.warnings)

    def test_only_spelling_gets_no_companion(self):
        """The keyword FORBIDS a post-failure contact --- do not bolt one on."""
        deck = ("*KEYWORD\n" + _MESH
                + "*CONTACT_TIEBREAK_SURFACE_TO_SURFACE_ONLY\n"
                  "         1         2         3         3         0         0         0         0\n"
                  "       0.0       0.0       0.0       0.0       0.0         0       0.0       0.0\n"
                  "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                  "     100.0     200.0         0         0\n"
                + _TAIL)
        _, starter = _convert(deck)
        self.assertFalse([ln for ln in starter.splitlines()
                          if ln.startswith("/INTER/TYPE25/")], starter)
        self.assertNotIn("post_rupture_contact_", starter)

    def test_a_permanent_tie_gets_no_companion(self):
        """No rupture means no post-failure state to catch, so a companion
        would only add pre-failure stiffness."""
        result, starter = _convert(
            "*KEYWORD\n" + _MESH
            + _auto_tiebreak(1, "1000.0", "1000.0", "0.0") + _TAIL)
        self.assertFalse([ln for ln in starter.splitlines()
                          if ln.startswith("/INTER/TYPE25/")], starter)


# ═════════════════════════════════════════════════════════════════════════════
# 8. Registry / allocator audit
# ═════════════════════════════════════════════════════════════════════════════

class RegistryAudit(unittest.TestCase):
    RUPTURE = ("*KEYWORD\n" + _MESH
               + _auto_tiebreak(6, "50.0", "20.0", "0.005")
               + "*DATABASE_RCFORC\n    1.0E-5\n" + _TAIL)

    def test_th_inter_lists_the_tie_and_its_companion(self):
        """_make_starter_th_inter is built from the PARSED contact containers,
        so a new container AND the minted companion ids both have to be added
        or *DATABASE_RCFORC silently misses the whole post-failure load path."""
        _, starter = _convert(self.RUPTURE)
        th = _block(starter, [ln for ln in starter.splitlines()
                              if ln.startswith("/TH/INTER/")][0])
        listed = {int(ln) for ln in th[6:] if ln.strip().isdigit()}
        comp = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                if ln.startswith("/INTER/TYPE25/")}
        self.assertIn(20, listed)
        self.assertTrue(comp <= listed, (listed, comp))

    def test_th_inter_omits_a_dropped_tiebreak(self):
        """A contact whose side resolved to nothing is in dropped_inter_ids and
        NO /INTER was written --- listing it is starter WARNING 257."""
        deck = self.RUPTURE.replace(
            "         1         2         3         3",
            "       999         2         3         3")
        _, starter = _convert(deck)
        hdr = [ln for ln in starter.splitlines() if ln.startswith("/TH/INTER/")]
        if hdr:
            th = _block(starter, hdr[0])
            listed = {int(ln) for ln in th[6:] if ln.strip().isdigit()}
            self.assertNotIn(20, listed)

    def test_all_interface_ids_are_unique(self):
        """Every /INTER type shares ONE starter id namespace (ERROR 117). This
        is the first contact that can produce two interfaces, so the deck-wide
        scan has to see them."""
        result, starter = _convert(self.RUPTURE)
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/INTER/")]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse([w for w in result.warnings
                          if "INTERFACE ID" in w and "more than one" in w])

    def test_grnod_surf_and_funct_ids_are_all_distinct(self):
        _, starter = _convert(self.RUPTURE)
        minted = [ln for ln in starter.splitlines()
                  if ln.startswith(("/GRNOD/", "/SURF/", "/FUNCT/", "/INTER/",
                                    "/TH/"))]
        ids = [ln.rsplit("/", 1)[1] for ln in minted
               if ln.rsplit("/", 1)[1].isdigit()]
        self.assertEqual(len(ids), len(set(ids)), minted)

    def test_implicit_stub_is_not_added_beside_a_tiebreak_tie(self):
        """k2rad/__init__ injects an all-parts self-contact stub on an implicit
        deck that has NO contact. Before #131 a tiebreak lived in
        contacts_surf2surf and blocked it; moving it to its own container
        without updating the guard would add a parasitic penalty interface
        across the tied gaps — the exact reason the guard already lists
        contacts_tied and contacts_spotweld."""
        deck = ("*KEYWORD\n" + _MESH
                + _auto_tiebreak(1, "1000.0", "1000.0", "0.0")
                + "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n" + _TAIL)
        result, starter = _convert(deck)
        self.assertFalse(
            [ln for ln in starter.splitlines()
             if ln.startswith("/INTER/TYPE7/")], starter)
        self.assertFalse(
            [w for w in result.warnings
             if "auto_implicit_stabilization" in w], result.warnings)

    def test_auto_gapmin_names_the_tiebreak_instead_of_going_silent(self):
        """--auto-gapmin walks contacts_single + contacts_surf2surf only, and
        /INTER/TYPE2 has no Gapmin at all. Leaving the tiebreak out silently
        would make a tiebreak-only deck report "no contact interfaces found to
        analyze" --- a false statement about a deck that has one."""
        from k2rad.gapmin import suggest_gapmins
        state = _dispatch("*KEYWORD\n" + _MESH
                          + _auto_tiebreak(1, "1000.0", "1000.0", "0.0")
                          + _TAIL)
        suggestions, skipped = suggest_gapmins(state)
        self.assertEqual(suggestions, {})
        self.assertIn(20, skipped)
        self.assertIn("no Gapmin", skipped[20])

    def test_inter_gapmin_override_on_a_tie_says_why(self):
        """Not "unknown interface id": the id exists, it is just a tie."""
        result, _ = _convert(
            "*KEYWORD\n" + _MESH
            + _auto_tiebreak(1, "1000.0", "1000.0", "0.0") + _TAIL,
            inter_gapmin={20: 0.5})
        hit = [w for w in result.warnings if "--inter-gapmin 20=0.5" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("has no Gapmin field", hit[0])
        self.assertNotIn("unknown interface id", hit[0])

    def test_deformable_recipe_walk_excludes_the_tie(self):
        """The recipe sets /INTER/TYPE7 Inacti=5 against active-set chatter; a
        kinematic tie has no active set and no Inacti column. contacts_tied and
        contacts_spotweld were never in this walk either."""
        from k2rad.writer.contacts import deformable_deformable_inter_ids
        state = _dispatch("*KEYWORD\n" + _MESH
                          + _auto_tiebreak(1, "1000.0", "1000.0", "0.0")
                          + _TAIL)
        self.assertEqual(deformable_deformable_inter_ids(state), [])

    def test_transducer_parent_pool_excludes_the_tie(self):
        """/INTER/SUB needs a penalty parent with segments; a /INTER/TYPE2 tie
        is not one, which is why contacts_tied was never in the pool either.
        The verdict is 'correctly excluded', asserted so a later refactor that
        adds contacts_tiebreak to the pool fails here."""
        from k2rad.writer import contacts as C
        import inspect
        src = inspect.getsource(C._select_parent_interface)
        self.assertNotIn("contacts_tiebreak", src)
        self.assertNotIn("companion_inter_ids", src)
        src2 = inspect.getsource(C._match_parent_interface)
        self.assertNotIn("contacts_tiebreak", src2)


# ═════════════════════════════════════════════════════════════════════════════
# 9. Named warn-drops --- every cell accounted for, and nothing over-claimed
# ═════════════════════════════════════════════════════════════════════════════

class NamedDrops(unittest.TestCase):
    def _warns(self, deck):
        result, _ = _convert(deck)
        return result.warnings

    def test_option_1_does_not_claim_a_lost_failure(self):
        """OPTION 1 has NO failure criterion in LS-DYNA either (p.11-36), and
        NFLS/SFLS/ERATEN are not in its field list (p.11-38/39). Saying "the
        failure is DROPPED" there would state a fact the deck does not
        contain."""
        warns = self._warns("*KEYWORD\n" + _MESH
                            + _auto_tiebreak(1, "1000.0", "1000.0", "0.0",
                                             eraten="1.0") + _TAIL)
        tie = [w for w in warns if "PERMANENT tie" in w]
        self.assertEqual(len(tie), 1, warns)
        self.assertIn("NEVER FAILS in LS-DYNA either", tie[0])
        self.assertNotIn("the FAILURE is DROPPED", tie[0])
        inert = [w for w in warns if "INERT in LS-DYNA too" in w]
        self.assertEqual(len(inert), 1, warns)
        for cell in ("NFLS=1000", "SFLS=1000", "ERATEN=1"):
            self.assertIn(cell, inert[0])

    def test_option_2_does_claim_a_lost_failure(self):
        warns = self._warns("*KEYWORD\n" + _MESH
                            + _auto_tiebreak(2, "50.0", "20.0", "0.0") + _TAIL)
        tie = [w for w in warns if "PERMANENT tie" in w]
        self.assertEqual(len(tie), 1, warns)
        self.assertIn("the FAILURE is DROPPED", tie[0])
        lost = [w for w in warns if "no OpenRadioss counterpart" in w]
        self.assertIn("NFLS=50/SFLS=20", lost[0])

    def test_energy_release_rates_are_named_where_they_are_live(self):
        """ERATEN/ERATES are read "For OPTION = 7, +-9, 10, +-11 only", so on
        OPTION 7 they are a real drop and on OPTION 1 they are inert."""
        warns = self._warns("*KEYWORD\n" + _MESH
                            + _auto_tiebreak(7, "50.0", "20.0", "30.0",
                                             eraten="1.5", erates="2.5")
                            + _TAIL)
        lost = [w for w in warns if "no OpenRadioss counterpart" in w]
        self.assertEqual(len(lost), 1, warns)
        self.assertIn("ERATEN=1.5/ERATES=2.5", lost[0])
        self.assertIn("PARAM=30", lost[0])

    def test_user_mortar_damping_suffixes_are_named(self):
        for kw, needle in (
                ("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_USER",
                 "_USER flavour"),
                ("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_MORTAR",
                 "_MORTAR flavour"),
                ("CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK_DAMPING",
                 "_DAMPING flavour")):
            with self.subTest(kw=kw):
                warns = self._warns(
                    "*KEYWORD\n" + _MESH
                    + _auto_tiebreak(9, "50.0", "20.0", "1.0", keyword=kw)
                    + _TAIL)
                self.assertTrue(any(needle in w for w in warns), warns)

    def test_nodes_family_names_the_force_to_stress_mismatch(self):
        warns = self._warns(
            "*KEYWORD\n" + _MESH
            + "*CONTACT_TIEBREAK_NODES_TO_SURFACE\n"
              "         1         2         3         3         0         0         0         0\n"
              "       0.0       0.0       0.0       0.0       0.0         0       0.0       0.0\n"
              "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
              "   10000.0   50000.0       1.0       3.0\n" + _TAIL)
        lost = [w for w in warns if "no OpenRadioss counterpart" in w]
        self.assertEqual(len(lost), 1, warns)
        self.assertIn("NEN=1/MES=3", lost[0])
        self.assertIn("are FORCES", lost[0])
        self.assertIn("*SET_NODE DA1..DA4", lost[0])

    def test_surface_family_names_tblcid_and_thkoff(self):
        warns = self._warns(
            "*KEYWORD\n" + _MESH
            + "*CONTACT_TIEBREAK_SURFACE_TO_SURFACE\n"
              "         1         2         3         3         0         0         0         0\n"
              "       0.0       0.0       0.0       0.0       0.0         0       0.0       0.0\n"
              "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
              "     100.0     200.0         7         1\n" + _TAIL)
        lost = [w for w in warns if "no OpenRadioss counterpart" in w]
        self.assertEqual(len(lost), 1, warns)
        self.assertIn("TBLCID=7", lost[0])
        self.assertIn("THKOFF=1", lost[0])

    def test_missing_card4_is_named_not_silently_zeroed(self):
        """A blank/absent Card 4 gives OPTION 0, which is not a legal value ---
        the card is REQUIRED for this keyword (p.11-6)."""
        deck = ("*KEYWORD\n" + _MESH
                + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK\n"
                  "         1         2         3         3         0         0         0         0\n"
                  "       0.3       0.2       0.0       0.0       0.0         0       0.0       0.0\n"
                  "       1.0       1.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
                + _TAIL)
        warns = self._warns(deck)
        self.assertTrue(any("OPTION) reads 0" in w for w in warns), warns)


# ═════════════════════════════════════════════════════════════════════════════
# 10. Corpus carriers + no leakage into tiebreak-free decks
# ═════════════════════════════════════════════════════════════════════════════

class CorpusCarriers(unittest.TestCase):
    """The census over the repo, C:/openradioss_run, the Ryan-Lee examples,
    dynaexamples_r14 and E:/foxcore_data found exactly two carrier SHAPES:
    nine copies of the user's Kurbel model (all OPTION 1) and one
    *CONTACT_TIEBREAK_NODES_ONLY. Everything else in this module is
    synthetic-validation-only, which the CHANGELOG says out loud."""

    KURBEL = Path("C:/openradioss_run/getriebekette/wip_quang/"
                  "openradioss_super-fine-mesh_badamid-konditioniert_"
                  "tiebreak-ok/319_rigid_bodies_plastic_feinseite_"
                  "kurbel-super-fine-mesh.k")
    PLATES = Path("C:/Users/pmqua/PycharmProjects/FEM_solver/verification/"
                  "dynaexamples_r14_ton-mm-s/intro-by-k.-weimar/spotweld/"
                  "spotweld-iv/plates.tied.k")

    @unittest.skipUnless(PLATES.exists(), "corpus deck not on this machine")
    def test_nodes_only_carrier_is_no_longer_a_silent_skip(self):
        """Before this batch the ONLY joint between the two plates vanished
        into skipped_keywords with no warning at all."""
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, self.PLATES.name)
            shutil.copy(self.PLATES, dst)
            result = convert(dst, write_log=False)
            starter = Path(result.starter_path).read_text()
        self.assertNotIn("CONTACT_TIEBREAK_NODES_ONLY", result.skipped_keywords)
        tie = [ln for ln in starter.splitlines()
               if ln.startswith("/INTER/TYPE2/")]
        self.assertEqual(len(tie), 1, starter)
        cards = _cards(_block(starter, tie[0]))
        self.assertEqual(cards[0][30:40], "        28")   # NODES -> Spotflag 28
        self.assertTrue(any("CONTACT_TIEBREAK_NODES_ONLY" in w
                            and "PERMANENT tie" in w for w in result.warnings),
                        result.warnings)
        # _ONLY: no companion contact, because the keyword forbids one. (The
        # deck's own *CONTACT_AUTOMATIC_SINGLE_SURFACE does emit an unrelated
        # /INTER/TYPE25, so the check is on the companion's own title.)
        self.assertNotIn("post_rupture_contact_", starter)

    @unittest.skipUnless(KURBEL.exists(), "corpus deck not on this machine")
    def test_kurbel_prime_carrier(self):
        """The prime carrier is a CONFORMAL self-tiebreak at OPTION 1 --- a
        permanent stick with no failure. It must convert to the auto-penalty
        tie under its own deck id, and it must start clean (measured: 0 ERROR,
        WARNING 1071 only, from the whole-part secondary side)."""
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, self.KURBEL.name)
            shutil.copy(self.KURBEL, dst)
            result = convert(dst, write_log=False)
            starter = Path(result.starter_path).read_text()
        block = _block(starter, "/INTER/TYPE2/10")
        self.assertTrue(block, "no /INTER/TYPE2/10 emitted")
        self.assertEqual(block[1], "Kurbel self tiebreak contact")
        cards = _cards(block)
        self.assertEqual(cards[0][30:40], "        27")
        self.assertEqual(len(cards), 2)          # no rupture card at OPTION 1
        self.assertEqual([], [ln for ln in starter.splitlines()
                              if ln.startswith("/INTER/TYPE25/")])
        tie = [w for w in result.warnings if "PERMANENT tie" in w]
        self.assertEqual(len(tie), 1, result.warnings)
        self.assertIn("4540 secondary nodes", tie[0])
        self.assertIn("NEVER FAILS in LS-DYNA either", tie[0])


class NoLeakIntoTiebreakFreeDecks(unittest.TestCase):
    def test_goldens_are_unchanged(self):
        """A deck with no tiebreak must be byte-identical: the batch touches
        the shared _emit_inter_type2, _emit_inter_type25 and
        _read_contact_ignore, and tied_weld.k exercises the first of those."""
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
