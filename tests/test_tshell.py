"""The THICK-SHELL batch:

  *ELEMENT_TSHELL (+ _BETA / _COMPOSITE / unknown)  -> /BRICK, verbatim n1..n8
  *SECTION_TSHELL ICOMP=0, isotropic material       -> /PROP/TYPE20 (TSHELL)
  *SECTION_TSHELL ICOMP=0, orthotropic material     -> /PROP/TYPE21 (TSH_ORTH)
  *SECTION_TSHELL ICOMP=1                           -> /PROP/TYPE22 (TSH_COMP)
  *PART_COMPOSITE_TSHELL on a thick-shell mesh      -> /PROP/TYPE22, real plies

Everything here is invisible in the .rad unless it is asserted by COLUMN, so
that is how it is asserted. The conventions that carry the most risk, and why
each is pinned:

* **The thickness direction is carried by ``Icstr = 010`` plus a VERBATIM
  connectivity copy, and nothing else.** LS-DYNA's "n1 to n4 define the lower
  surface, and nodes n5 to n8 define the upper surface" (Vol I R16 p.2703
  Remark 1) is the same pairing Radioss reads at ``Icstr = 010`` —
  ``scdtchk3.F:84-246`` takes the through-thickness edges as (1-5) (2-6) (3-7)
  (4-8) there. So a permutation would be a bug, not a fix (the /TETRA10 lesson
  in reverse), and a BLANK Icstr would desync the TYPE22 layer cards.
* **``Inpts`` is a PACKED ijk field with an unpack gate at 200.** The CFG only
  splits the digits when ``NBP > 200``, so a leading digit below 2 is read as a
  bare ``Inpts_S`` with zero points in r and t. Every Isolid=14 value is
  therefore asserted to be ``2 j 2``, not just "contains the NIP".
* **``ti/t`` is a FRACTION and the starter checks the sum.** ``INT(sum*100)``
  must land within 1 of 100 (``hm_read_prop22.F:395-405``, ERROR 675), so the
  ply fractions are summed in the test rather than compared one at a time.
* **The layer count comes from the middle digit, or from ``Iint`` when that
  digit is 0.** Both encodings are exercised, because the >9-ply one is the
  only way Radioss can hold more than nine layers and it is easy to get right
  for 12 and wrong for 10.
* **A per-element angle or layup cannot exist on a /BRICK.** Radioss has no
  per-element column at all (unlike /SHELL's ``Phi``, which the #91 finding
  showed is itself read for only some IGTYPs), so ``_BETA`` folds into the
  PROPERTY when the section agrees and warn-drops when it does not, and
  ``_COMPOSITE`` promotes to a per-part /PROP/TYPE22 only when every element
  of the part declares the same stack.
* **AOPT=3 needs a -90 degree shift.** LS-DYNA's direction 1 is ``v x n``;
  Radioss PROJECTS the reference vector onto the mid-plane instead
  (``scmorth3.F:185-199``), and ``v x n == R(-90) proj(v)`` for any v. dyna2rad
  copies v and leaves Phi at 0, i.e. swaps directions 1 and 2.
* **The mesh survives every spelling.** dyna2rad's CFG declares no BETA
  attribute and no option on this keyword at all, so it cannot even match the
  header of ``*ELEMENT_TSHELL_BETA`` and drops the whole block, elements
  included. On master k2rad did the same for the BARE keyword: all nine r14
  thick-shell decks emitted a /PART on a placeholder /PROP/SHELL and no
  elements whatsoever, with no MESH LOSS warning to say so.
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


# ── Harness ──────────────────────────────────────────────────────────────────

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
    """A property block's DATA lines: after the title, comments removed."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(result, needle: str):
    return [w for w in result.warnings if needle in w]


def _row(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


# ── Decks ────────────────────────────────────────────────────────────────────
#
# One unit-height hex (nodes 1-4 at z=0, 5-8 at z=2) and a second one beside it
# sharing the 2-3-6-7 face, so a two-element part is available without a second
# node block.
NODES = "*NODE\n" + "".join(
    f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
        (5, 0.0, 0.0, 2.0), (6, 10.0, 0.0, 2.0),
        (7, 10.0, 10.0, 2.0), (8, 0.0, 10.0, 2.0),
        (9, 20.0, 0.0, 0.0), (10, 20.0, 10.0, 0.0),
        (11, 20.0, 0.0, 2.0), (12, 20.0, 10.0, 2.0)))

# EID PID N1..N8, ten I8 fields.
TSH1 = ("*ELEMENT_TSHELL\n"
        "       1       1       1       2       3       4       5       6       7       8\n")
TSH2 = (TSH1
        + "       2       1       2       9      10       3       6      11      12       7\n")

PART = "*PART\ntshell part\n" + _row(1, 1, 1) + "\n"

MAT_ISO = "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
MAT_ISO2 = "*MAT_ELASTIC\n" + _row(2, 2.7e-9, 70000.0, 0.33) + "\n"


def mat_ortho(aopt=2.0, a=(0.6, 0.8, 0.0), v=(0.0, 1.0, 0.0), beta=0.0,
              mid=1):
    """*MAT_ORTHOTROPIC_ELASTIC (002) -> /MAT/LAW93, PROP_SOLID class 2.

    Card 2 field 4 is AOPT; card 3 fields 4-6 are A1/A2/A3; card 4 fields 1-3
    are V1/V2/V3 and field 7 is BETA.
    """
    return ("*MAT_ORTHOTROPIC_ELASTIC\n"
            + _row(mid, 7.85e-9, 200000.0, 10000.0, 10000.0, 0.3, 0.3, 0.3)
            + "\n" + _row(5000.0, 5000.0, 5000.0, aopt, 0.0, 0.0) + "\n"
            + _row(0.0, 0.0, 0.0, a[0], a[1], a[2], 0) + "\n"
            + _row(v[0], v[1], v[2], 0.0, 0.0, 0.0, beta, 0.0) + "\n")


def sec(elform=2, shrf="", nip=4, propt="", qr="", icomp="", tshear="",
        betas=()):
    """One *SECTION_TSHELL card set: SECID ELFORM SHRF NIP PROPT QR ICOMP
    TSHEAR, plus ceil(NIP/8) angle cards when ICOMP=1."""
    out = "*SECTION_TSHELL\n" + _row(1, elform, shrf, nip, propt, qr,
                                     icomp, tshear) + "\n"
    for k in range(0, len(betas), 8):
        out += _row(*betas[k:k + 8]) + "\n"
    return out


def deck(elem=TSH1, section=None, mat=MAT_ISO, part=PART, extra=""):
    return ("*KEYWORD\n" + NODES + elem + part
            + (sec() if section is None else section) + mat + extra + "*END\n")


# ═════════════════════════════════════════════════════════════════════════════
class TshellElements(unittest.TestCase):
    """*ELEMENT_TSHELL -> /BRICK."""

    def test_connectivity_is_verbatim_and_column_exact(self):
        """n1..n8 copied 1:1 into /BRICK slots 1-8, ten right-justified I10
        fields. The order IS the thickness direction: with Icstr=010 Radioss
        pairs (1-5) (2-6) (3-7) (4-8) (scdtchk3.F), which is exactly LS-DYNA's
        lower face n1-n4 / upper face n5-n8."""
        _, starter = _convert(deck())
        card = _block(starter, "/BRICK/1")[1]
        self.assertEqual(card, _row(1, 1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual(len(card), 90)

    def test_thick_shells_do_not_land_in_the_solid_bucket(self):
        """A thick shell must never be split by distinct-node count the way
        *ELEMENT_SOLID is: a degenerate 6-node one has only 6 distinct ids and
        the /TETRA4 test looks at exactly that. Emitted as /BRICK, always."""
        _, starter = _convert(deck(
            elem="*ELEMENT_TSHELL\n" + _row(1, 1, 1, 2, 3, 3, 5, 6, 7, 7)
                 + "\n"))
        self.assertEqual(_blocks(starter, "/TETRA4"), [])
        self.assertEqual(_block(starter, "/BRICK/1")[1],
                         _row(1, 1, 2, 3, 3, 5, 6, 7, 7))

    def test_degenerate_wedge_keeps_the_collapsed_eight_slot_form(self):
        """LS-DYNA writes a 6-node thick shell as n1 n2 n3 n3 n4 n5 n6 n6, and
        that collapsed form must survive. Written with trailing ZEROS instead,
        Radioss classifies it ISOLNOD=6 (hm_read_solid.F:166) and then refuses
        it on a thick-shell property unless Isolid=15 — ERROR 639, whose own
        text names the collapsed connectivity as the alternative."""
        _, starter = _convert(deck(
            elem="*ELEMENT_TSHELL\n" + _row(1, 1, 1, 2, 3, 3, 5, 6, 7, 7)
                 + "\n"))
        card = _block(starter, "/BRICK/1")[1]
        self.assertEqual([_col_i(card, 1 + 10 * k, 10 + 10 * k)
                          for k in range(9)],
                         [1, 1, 2, 3, 3, 5, 6, 7, 7])
        self.assertNotIn(0, [_col_i(card, 11 + 10 * k, 20 + 10 * k)
                             for k in range(8)])

    def test_short_card_is_padded_by_repeating_not_zeroed(self):
        """Same reason: a zero slot changes the element CLASS. A card that
        names only six nodes is padded by repeating the last id."""
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL\n" + _row(1, 1, 1, 2, 3, 4, 5, 6) + "\n"))
        self.assertEqual(_block(starter, "/BRICK/1")[1],
                         _row(1, 1, 2, 3, 4, 5, 6, 6, 6))
        self.assertTrue(_warns(result, "fewer than eight nodes"))

    def test_a_ply_card_is_never_mistaken_for_an_element(self):
        """`1 0.6 0.0 - 2 0.4 90.0` free-splits to SIX fields, which is enough
        to pass the connectivity length test — it would become an element on
        node ids 0, 2, 0, 90. An interior zero is what rules it out: a thick
        shell fills every slot it uses."""
        from k2rad.handlers import _parse_tshell_base
        self.assertIsNone(_parse_tshell_base(
            _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "")))
        self.assertEqual(
            _parse_tshell_base(_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8)),
            (1, 1, [1, 2, 3, 4, 5, 6, 7, 8]))

    def test_every_option_spelling_is_registered(self):
        """*ELEMENT_TSHELL_{OPTION} with OPTION in {<blank>, BETA, COMPOSITE}
        (Vol I R16 p.2703). dispatch() is an exact dict lookup, and a miss on an
        ELEMENT keyword is not a soft failure: _make_parts_and_elements emits
        elements inside the state.parts loop, so the part is left empty and
        silent."""
        for opt in ("", "_BETA", "_COMPOSITE"):
            self.assertIn("ELEMENT_TSHELL" + opt, HANDLERS, opt)
            self.assertIn("ELEMENT_TSHELL" + opt, _OFFSET_SPECS, opt)

    def test_tshell_is_not_matched_by_the_element_shell_prefix(self):
        """The prefix fallback matches on a TOKEN boundary, so ELEMENT_TSHELL
        is not an ELEMENT_SHELL spelling and needs its own row. Without it the
        keyword falls through to skipped_keywords."""
        state = _dispatch("*KEYWORD\n" + NODES
                          + "*ELEMENT_TSHELL_NOSUCHOPTION\n"
                          + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                          + "*END\n")
        self.assertEqual(state.skipped_keywords, [])
        self.assertEqual(len(state.tshell_elems), 1)
        self.assertEqual(state.shell_elems, [])

    def test_unknown_suffix_keeps_the_mesh(self):
        """The #91 rule. The option's own cards are dropped, the elements are
        not, and the surviving count is reported."""
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL_FOO\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + _row(10, 10, 10, 10) + "\n"))
        self.assertEqual(_block(starter, "/BRICK/1")[1],
                         _row(1, 1, 2, 3, 4, 5, 6, 7, 8))
        w = _warns(result, "option '_FOO' is not implemented")
        self.assertEqual(len(w), 1, result.warnings)
        self.assertIn("1 element(s) were kept as plain /BRICK (thick shell)",
                      w[0])
        self.assertIn("The MESH is preserved", w[0])
        self.assertEqual(result.skipped_keywords, [])

    def test_provisional_candidates_are_screened_against_the_node_table(self):
        """The content test (all fields positive integers) is NECESSARY but not
        SUFFICIENT: an option card written with whole numbers passes it, and an
        element invented from one names node ids the deck never defines —
        starter ERROR 78, a HARD failure where the old behaviour was a silent
        skip. Here the second line is all-integer AND ten fields wide, so only
        the node-table check can reject it."""
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL_FOO\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + _row(2, 1, 901, 902, 903, 904, 905, 906, 907, 908) + "\n"))
        self.assertEqual(len(_block(starter, "/BRICK/1")), 2)   # header + 1
        self.assertIn("named node ids the deck does not define",
                      _warns(result, "'_FOO'")[0])

    def test_thick_shell_nodes_are_dampable(self):
        """/DAMP is NODE-based Rayleigh damping over a /GRNOD, with no
        element-type restriction, so a thick shell's nodes are damped exactly
        like a brick's. The r14 ex_15 decks reported "*DAMPING_*: no target
        deformable nodes found" on master purely because the whole mesh was
        missing — this is the tshell half of the #119 scope caveat.

        (Contrast /DAMP/FREQUENCY_RANGE, which enters as a viscous stress INSIDE
        the shell/solid material law and genuinely cannot reach a thick shell;
        that path's own "come out COMPLETELY UNDAMPED" warning stays correct.)"""
        result, starter = _convert(deck(
            extra="*DAMPING_GLOBAL\n" + _row(0, 5.0) + "\n"))
        self.assertEqual(
            [w for w in result.warnings if "no target deformable nodes" in w],
            [])
        self.assertIn("/DAMP", starter)

    def test_a_thick_shell_part_is_a_usable_contact_side(self):
        """A thick shell IS a `/BRICK` in the emitted deck, so every place that
        classifies a part as "solid" for contact has to see it. Otherwise the
        side resolves EMPTY — the silent-drop class, and worse than the old
        behaviour only because the mesh now exists to be missed."""
        contact = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                   + _row(1, 0, 3, 0) + "\n" + _row(0.2, 0.2) + "\n")
        result, starter = _convert(deck(extra=contact))
        self.assertIn("/INTER/TYPE7", starter)
        self.assertEqual(
            [w for w in result.warnings if "names nothing" in w
             or "resolved to an EMPTY" in w], [], result.warnings)
        grnod = [ln for ln in starter.splitlines() if ln.startswith("/GRNOD")]
        self.assertTrue(grnod, "the secondary side found no nodes")

    def test_a_rigid_thick_shell_part_reaches_its_rbody(self):
        """*MAT_RIGID gathers its /RBODY secondary nodes from the element
        tables; a thick-shell part missing from that walk would be a rigid body
        with no nodes at all."""
        rigid = ("*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                 + _row(1, 7, 7) + "\n" + _row(0.0) + "\n")
        _, starter = _convert(deck(mat=rigid))
        body = _block(starter, "/RBODY/")
        self.assertTrue(body)
        # /RBODY card 1: node_ID sens_ID skew_ID Ispher (4 x I10), Mass (F20),
        # then grnd_ID at 61-70.
        grnod_id = _col_i(_cards(body)[0], 61, 70)
        self.assertGreater(grnod_id, 0)
        ids = " ".join(_block(starter, f"/GRNOD/NODE/{grnod_id}")[2:]).split()
        self.assertEqual(sorted(int(x) for x in ids), list(range(1, 9)))

    def test_an_implicit_thick_shell_deck_gets_the_contact_stub(self):
        """The implicit no-contact stub exists because the OpenRadioss implicit
        engine segfaults in setup without an /INTER; its gate read "no
        deformable surface to build the interface from", which a thick-shell
        mesh silently failed. Every r14 *ELEMENT_TSHELL deck is implicit."""
        impl = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.1) + "\n")
        result, starter = _convert(deck(extra=impl))
        self.assertIn("/INTER/TYPE7", starter)
        self.assertTrue(_warns(result, "Injected an inert all-parts "
                                       "self-contact"), result.warnings)

    def test_orphan_thick_shells_are_reported_as_mesh_loss(self):
        """An element whose PID has no *PART is never reached by the emit loop.
        Thick shells join the orphan census so that silence cannot happen."""
        result, _ = _convert(deck(
            elem="*ELEMENT_TSHELL\n" + _row(1, 77, 1, 2, 3, 4, 5, 6, 7, 8)
                 + "\n" + TSH1))
        w = _warns(result, "MESH LOSS")
        self.assertEqual(len(w), 1, result.warnings)
        self.assertIn("PID 77 (1 tshell)", w[0])


# ═════════════════════════════════════════════════════════════════════════════
class SectionTshellCards(unittest.TestCase):
    """*SECTION_TSHELL parsing: card positions, defaults, card-set walk."""

    def test_card1_fields(self):
        state = _dispatch("*KEYWORD\n"
                          + sec(elform=5, shrf=0.7, nip=6, propt=2, qr=1.0,
                                icomp=0, tshear=1) + "*END\n")
        s = state.sec_tshells[1]
        self.assertEqual((s.elform, s.nip, s.icomp, s.tshear), (5, 6, 0, 1))
        self.assertAlmostEqual(s.shrf, 0.7)
        self.assertAlmostEqual(s.propt, 2.0)
        self.assertAlmostEqual(s.qr, 1.0)

    def test_blank_elform_is_the_manual_default_1(self):
        """"EQ.1: one point reduced integration (default)" (Vol I R16 p.3717).
        dyna2rad reads the blank as 0, which falls into the `else` of its
        `elform == 1 ? 15 : 14` test and gives the deck the FULL-integration
        HA8 — the opposite element class."""
        state = _dispatch("*KEYWORD\n" + sec(elform="") + "*END\n")
        self.assertEqual(state.sec_tshells[1].elform, 1)
        self.assertTrue(state.sec_tshells[1].elform_blank)

    def test_blank_nip_is_the_manual_default_2(self):
        """"EQ.0: set to 2 integration points" (Vol I R16 p.3717). dyna2rad
        keeps the raw 0, which on the composite branch writes zero ply cards
        against a property expecting one — ERROR 675."""
        state = _dispatch("*KEYWORD\n" + sec(nip="") + "*END\n")
        self.assertEqual(state.sec_tshells[1].nip, 2)

    def test_icomp_angles_are_card_2_not_card_3(self):
        """*SECTION_TSHELL has NO thickness card — a thick shell's thickness is
        the distance between its faces in *NODE — so the B_i block follows card
        1 directly. Reading it one card late would take the first angle card as
        the next set's card 1."""
        state = _dispatch("*KEYWORD\n"
                          + sec(nip=4, icomp=1, betas=(0.0, 45.0, -45.0, 90.0))
                          + "*END\n")
        self.assertEqual(state.sec_tshells[1].betas, [0.0, 45.0, -45.0, 90.0])

    def test_icomp_angle_block_wraps_at_eight_per_card(self):
        angles = tuple(float(k * 10) for k in range(10))
        state = _dispatch("*KEYWORD\n"
                          + sec(nip=10, icomp=1, betas=angles) + "*END\n")
        self.assertEqual(state.sec_tshells[1].betas, list(angles))

    def test_a_blank_angle_card_is_a_CARD_not_whitespace(self):
        """The #117 rule. An all-zero angle card is written blank, and the walk
        consumes by COUNT — skipping it as padding would read the SECOND set's
        card 1 as this set's angles and lose that section."""
        two = ("*SECTION_TSHELL\n"
               + _row(1, 2, "", 9, "", "", 1, "") + "\n"
               + "\n"                                  # B1..B8 all zero
               + _row(0.0, 30.0) + "\n"                # B9, B10 (unused tail)
               + _row(2, 3, "", 3, "", "", "", "") + "\n")
        state = _dispatch("*KEYWORD\n" + two + "*END\n")
        self.assertEqual(sorted(state.sec_tshells), [1, 2])
        self.assertEqual(state.sec_tshells[1].betas[:8], [0.0] * 8)
        self.assertEqual(state.sec_tshells[1].betas[8], 0.0)
        self.assertEqual(state.sec_tshells[2].elform, 3)

    def test_every_card_set_under_one_header_is_read(self):
        three = ("*SECTION_TSHELL\n"
                 + _row(1, 1, "", 2) + "\n"
                 + _row(2, 2, "", 3) + "\n"
                 + _row(3, 5, "", 4) + "\n")
        state = _dispatch("*KEYWORD\n" + three + "*END\n")
        self.assertEqual([state.sec_tshells[k].elform for k in (1, 2, 3)],
                         [1, 2, 5])

    def test_title_option_reads_one_title_per_set(self):
        two = ("*SECTION_TSHELL_TITLE\n"
               "outer skin\n" + _row(1, 2, "", 3) + "\n"
               "core\n" + _row(2, 1, "", 5) + "\n")
        state = _dispatch("*KEYWORD\n" + two + "*END\n")
        self.assertEqual(state.sec_tshells[1].title, "outer skin")
        self.assertEqual(state.sec_tshells[2].title, "core")

    def test_walk_stops_loudly_on_a_card_it_cannot_stride(self):
        result, _ = _convert(deck(section="*SECTION_TSHELL\n"
                                          + _row(1, 2, "", 3) + "\n"
                                          + "not a section card\n"))
        self.assertTrue(_warns(result, "the walk STOPPED there"),
                        result.warnings)

    def test_duplicate_secid_warns(self):
        result, _ = _convert(deck(section="*SECTION_TSHELL\n"
                                          + _row(1, 2, "", 3) + "\n"
                                          + _row(1, 1, "", 5) + "\n"))
        self.assertTrue(_warns(result, "*SECTION_TSHELL 1 is defined more "
                                       "than once"), result.warnings)

    def test_section_keyword_is_dispatched(self):
        self.assertIn("SECTION_TSHELL", HANDLERS)
        self.assertIn("SECTION_TSHELL", _OFFSET_SPECS)


# ═════════════════════════════════════════════════════════════════════════════
class PropType20(unittest.TestCase):
    """/PROP/TYPE20 — the isotropic thick shell, radioss2018 layout."""

    def test_card_layout_is_column_exact(self):
        """radioss2018/PROP/prop_p20_tshell.cfg writes
        "%10d%10d                    %10d%10d%10d          %20lg": Isolid 1-10,
        Ismstr 11-20, TWENTY dead columns, Icstr 41-50, Inpts 51-60, Iint 61-70,
        ten blanks, Dn 81-100."""
        _, starter = _convert(deck(section=sec(elform=2, nip=5)))
        c = _cards(_block(starter, "/PROP/TYPE20/1"))
        self.assertEqual(_col_i(c[0], 1, 10), 14)      # Isolid
        self.assertEqual(_col_i(c[0], 11, 20), 0)      # Ismstr -> /DEF_SOLID
        self.assertEqual(c[0][20:40], " " * 20)        # dead
        self.assertEqual(_col_i(c[0], 41, 50), 10)     # Icstr = 010
        self.assertEqual(_col_i(c[0], 51, 60), 252)    # 2 x 5 x 2
        self.assertEqual(_col_i(c[0], 61, 70), 0)      # Iint (inert here)
        self.assertEqual(c[0][70:80], " " * 10)
        self.assertEqual(_col_f(c[0], 81, 100), 0.0)   # Dn
        self.assertEqual(_col_f(c[1], 1, 20), 0.0)     # qa
        self.assertEqual(_col_f(c[1], 21, 40), 0.0)    # qb
        self.assertEqual(_col_f(c[1], 41, 60), 0.0)    # h
        self.assertEqual(_col_f(c[2], 1, 20), 0.0)     # DeltaT_min
        self.assertEqual(len(c), 3)

    def test_ismstr_is_never_a_total_strain_value(self):
        """sgrtails.F:793 refuses Ismstr 10/11/12 on any thick shell —
        ERROR 3027 THICK-SHELL IS NOT COMPATIBLE WITH TOTAL STRAIN ISMSTR."""
        for elform in (1, 2, 3, 5, 6, 7):
            _, starter = _convert(deck(section=sec(elform=elform, nip=3)))
            card = _cards(_block(starter, "/PROP/TYPE20/1"))[0]
            self.assertNotIn(_col_i(card, 11, 20), (10, 11, 12))

    def test_elform_1_is_the_only_isolid_15(self):
        """dyna2rad's total map (convertprops.cxx:4324-4332), byte-identical in
        all three of its writers: elform == 1 -> 15, everything else -> 14."""
        for elform, want in ((1, 15), (2, 14), (3, 14), (5, 14), (6, 14),
                             (7, 14)):
            _, starter = _convert(deck(section=sec(elform=elform, nip=3)))
            card = _cards(_block(starter, "/PROP/TYPE20/1"))[0]
            self.assertEqual(_col_i(card, 1, 10), want, f"ELFORM={elform}")

    def test_isolid_15_writes_a_plain_unpacked_nip(self):
        _, starter = _convert(deck(section=sec(elform=1, nip=7)))
        card = _cards(_block(starter, "/PROP/TYPE20/1"))[0]
        self.assertEqual(_col_i(card, 51, 60), 7)

    def test_isolid_14_packs_two_by_nip_by_two_above_the_unpack_gate(self):
        """The CFG splits Inpts into r/s/t ONLY when NBP > 200. A leading digit
        below 2 is read as a bare Inpts_S with zero points in r and t, so every
        packed value must be >= 212."""
        for nip in range(1, 10):
            _, starter = _convert(deck(section=sec(elform=2, nip=nip)))
            nbp = _col_i(_cards(_block(starter, "/PROP/TYPE20/1"))[0], 51, 60)
            self.assertEqual(nbp, 200 + 10 * nip + 2, f"NIP={nip}")
            self.assertGreater(nbp, 200)
            self.assertEqual(nbp // 100, 2)
            self.assertEqual(nbp % 10, 2)
            self.assertEqual((nbp // 10) % 10, nip)

    def test_nip_above_nine_is_clamped_on_both_formulations(self):
        """Isolid=14 clamps the middle digit (a packed digit cannot exceed 9);
        Isolid=15 is clamped too, which dyna2rad does NOT do — it passes the raw
        value through and the starter refuses the deck with MSGID 563."""
        _, s14 = _convert(deck(section=sec(elform=2, nip=15)))
        self.assertEqual(_col_i(_cards(_block(s14, "/PROP/TYPE20/1"))[0],
                                51, 60), 292)
        result, s15 = _convert(deck(section=sec(elform=1, nip=15)))
        self.assertEqual(_col_i(_cards(_block(s15, "/PROP/TYPE20/1"))[0],
                                51, 60), 9)
        self.assertTrue(_warns(result, "is CLAMPED to 9"), result.warnings)

    def test_a_sectionless_thick_shell_part_gets_a_placeholder(self):
        """A /PART pointing at a property id nothing emits is starter ERROR 178
        and kills the whole run."""
        result, starter = _convert(deck(section=""))
        card = _cards(_block(starter, "/PROP/TYPE20/1"))[0]
        self.assertEqual(_col_i(card, 1, 10), 15)      # ELFORM 1 default
        self.assertEqual(_col_i(card, 51, 60), 2)      # NIP 2 default
        self.assertTrue(_warns(result, "PLACEHOLDER thick-shell property"),
                        result.warnings)

    def test_an_element_free_part_still_gets_its_thick_shell_property(self):
        """`_element_free_part_ids` treats a defined `sec_tshells` entry as
        resolved and hands out NO placeholder, so this loop has to emit under
        the SECID even when the part carries no elements — otherwise the /PART
        points at a property id nothing writes: starter ERROR 178."""
        two = (PART + "*PART\nempty tshell part\n" + _row(2, 2, 1) + "\n")
        secs = ("*SECTION_TSHELL\n" + _row(1, 2, "", 3) + "\n"
                + _row(2, 1, "", 4) + "\n")
        _, starter = _convert(deck(part=two, section=secs))
        self.assertEqual(_col_i(_cards(_block(starter, "/PART/2"))[0], 1, 10),
                         2)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE20/2")), 1)

    def test_an_unreferenced_section_emits_nothing(self):
        """No *PART names it, so nothing could point at the property — and an
        ICOMP=1 section with no part has no MATERIAL either, which would be a
        /PROP/TYPE22 with mat_IDi = 0 (starter ERROR 676). dyna2rad never
        converts an unreferenced *SECTION at all; reported on the
        recognized-not-emitted channel rather than as a warning."""
        secs = ("*SECTION_TSHELL\n" + _row(1, 2, "", 3) + "\n"
                + _row(9, 2, "", 4, "", "", 1, "") + "\n" + _row(0.0) + "\n")
        result, starter = _convert(deck(section=secs))
        self.assertEqual(_blocks(starter, "/PROP/TYPE20/9"), [])
        self.assertEqual(_blocks(starter, "/PROP/TYPE22"), [])
        self.assertTrue(any(kw == "SECTION_TSHELL"
                            for kw, _ in result.recognized_not_emitted),
                        result.recognized_not_emitted)

    def test_a_shell_part_on_a_tshell_section_does_not_duplicate_the_id(self):
        """The shell family auto-creates a *SECTION_SHELL under the SAME id, so
        emitting both would be two /PROP cards on one id — starter ERROR 79.
        The element family wins and the thick-shell property is reported."""
        thin = ("*KEYWORD\n" + NODES
                + "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
                + PART + sec() + MAT_ISO + "*END\n")
        result, starter = _convert(thin)
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/1")), 1)
        self.assertEqual(_blocks(starter, "/PROP/TYPE20"), [])
        self.assertTrue(_warns(result, "not thick shells"), result.warnings)

    def test_property_sits_under_the_secid_so_the_part_is_not_repointed(self):
        _, starter = _convert(deck(section=sec(elform=2, nip=3)))
        self.assertEqual(_col_i(_cards(_block(starter, "/PART/1"))[0], 1, 10),
                         1)
        self.assertIn("/PROP/TYPE20/1", starter)


# ═════════════════════════════════════════════════════════════════════════════
class PropType21(unittest.TestCase):
    """/PROP/TYPE21 — the orthotropic thick shell."""

    def test_an_orthotropic_material_selects_type21(self):
        """dyna2rad's ICOMP=0 branch splits on the PART MATERIAL, not on the
        section. Keying on the emitted law's own PROP_SOLID class states the
        actual constraint: LAW93 is class 2 (SOLID_ORTHOTROPIC), which TYPE20
        REJECTS with ERROR 3047 and TYPE21 accepts."""
        _, starter = _convert(deck(mat=mat_ortho()))
        self.assertEqual(_blocks(starter, "/PROP/TYPE20"), [])
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE21/1")), 1)

    def test_card_layout_is_column_exact(self):
        """radioss2018/PROP/prop_p21_tsh_orth.cfg. Three differences from
        TYPE20 that are easy to get wrong: no Iint column (61-80 are dead),
        card 4 has no h field, and deltaT_min is its own card AFTER Phi."""
        _, starter = _convert(deck(section=sec(elform=2, nip=4),
                                   mat=mat_ortho(aopt=2.0, a=(0.6, 0.8, 0.0))))
        c = _cards(_block(starter, "/PROP/TYPE21/1"))
        self.assertEqual(_col_i(c[0], 1, 10), 14)
        self.assertEqual(_col_i(c[0], 11, 20), 0)
        self.assertEqual(c[0][20:40], " " * 20)
        self.assertEqual(_col_i(c[0], 41, 50), 10)
        self.assertEqual(_col_i(c[0], 51, 60), 242)
        self.assertEqual(c[0][60:80], " " * 20)        # NO Iint on TYPE21
        self.assertEqual(_col_f(c[0], 81, 100), 0.0)
        self.assertEqual(len(c[1]), 40)                # qa + qb only, no h
        self.assertEqual(_col_i(c[2], 61, 70), 1)      # skew_ID
        self.assertEqual(_col_i(c[2], 71, 80), 0)      # Iorth
        self.assertEqual(_col_f(c[3], 1, 20), 0.0)     # Phi
        self.assertEqual(_col_f(c[4], 1, 20), 0.0)     # deltaT_min
        self.assertEqual(len(c), 5)

    def test_aopt2_becomes_a_skew_whose_first_axis_is_a(self):
        """scmorth3.F:131-133 reads SKEW(1:3, ISKV) — the skew's FIRST axis —
        as the reference vector whenever skew_ID is set. The /SKEW/FIX MUST be
        emitted, or the id dangles (ERROR 184)."""
        _, starter = _convert(deck(mat=mat_ortho(aopt=2.0, a=(0.6, 0.8, 0.0))))
        card = _cards(_block(starter, "/PROP/TYPE21/1"))[2]
        skew_id = _col_i(card, 61, 70)
        self.assertGreater(skew_id, 0)
        self.assertEqual([_col_f(card, 1, 20), _col_f(card, 21, 40),
                          _col_f(card, 41, 60)], [0.0, 0.0, 0.0])
        self.assertEqual(len(_blocks(starter, f"/SKEW/FIX/{skew_id}")), 1)

    def test_aopt3_shifts_phi_by_minus_ninety(self):
        """LS-DYNA AOPT=3 makes direction 1 the CROSS PRODUCT v x n, rotated by
        BETA. Radioss PROJECTS the reference vector onto the mid-plane instead
        (scmorth3.F CASE(3)), and for any v, ``v x n == R(-90) proj(v)`` — the
        out-of-plane part of v drops out of the cross product. So the exact
        mapping is V = v with Phi = BETA - 90. dyna2rad copies v and leaves Phi
        at 0, i.e. swaps material directions 1 and 2."""
        _, starter = _convert(deck(
            mat=mat_ortho(aopt=3.0, v=(0.0, 1.0, 0.0), beta=15.0)))
        c = _cards(_block(starter, "/PROP/TYPE21/1"))
        self.assertEqual([_col_f(c[2], 1, 20), _col_f(c[2], 21, 40),
                          _col_f(c[2], 41, 60)], [0.0, 1.0, 0.0])
        self.assertEqual(_col_i(c[2], 61, 70), 0)      # no skew
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 15.0 - 90.0)

    def test_aopt_negative_uses_the_define_coordinate_skew(self):
        """|AOPT| is a *DEFINE_COORDINATE_* id, which k2rad already emits as
        /SKEW under that same id — and a skew's first axis is exactly what the
        thick-shell card reads."""
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _row(7, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _row(0.0, 1.0, 0.0) + "\n")
        _, starter = _convert(deck(mat=mat_ortho(aopt=-7.0), extra=coord))
        self.assertEqual(
            _col_i(_cards(_block(starter, "/PROP/TYPE21/1"))[2], 61, 70), 7)

    def test_element_frame_and_point_modes_fall_back_to_global_x(self):
        """AOPT 0 (element nodes 1/2/4), 1 (a point) and 4 (cylindrical) have
        no thick-shell expression — the card holds ONE global vector and has no
        Ip column. A ZERO vector, which is what dyna2rad writes there, is
        starter ERROR 526 on EVERY element."""
        for aopt in (0.0, 1.0, 4.0):
            result, starter = _convert(deck(mat=mat_ortho(aopt=aopt)))
            card = _cards(_block(starter, "/PROP/TYPE21/1"))[2]
            self.assertEqual([_col_f(card, 1, 20), _col_f(card, 21, 40),
                              _col_f(card, 41, 60)], [1.0, 0.0, 0.0],
                             f"AOPT={aopt}")
            self.assertTrue(_warns(result, "falls back to global X"),
                            result.warnings)

    def test_shrf_is_warn_dropped_on_type20_and_type21(self):
        """Neither card has a transverse-shear column at all (only the
        composite TYPE22 does). dyna2rad drops it without a message."""
        for mat, ptype in ((MAT_ISO, 20), (mat_ortho(), 21)):
            result, _ = _convert(deck(section=sec(shrf=0.833), mat=mat))
            w = _warns(result, f"/PROP/TYPE{ptype}. Dropped")
            self.assertTrue(w, result.warnings)
            self.assertIn("SHRF=0.833", w[0])


# ═════════════════════════════════════════════════════════════════════════════
class PropType22(unittest.TestCase):
    """/PROP/TYPE22 — the layered thick shell, radioss90 layout."""

    def test_icomp_selects_type22_whatever_the_material(self):
        """dyna2rad tests ICOMP FIRST, so an isotropic material with ICOMP=1
        still takes the composite property."""
        for mat in (MAT_ISO, mat_ortho()):
            _, starter = _convert(deck(
                section=sec(nip=4, icomp=1, betas=(0.0, 45.0, -45.0, 90.0)),
                mat=mat))
            self.assertEqual(len(_blocks(starter, "/PROP/TYPE22/1")), 1)
            self.assertEqual(_blocks(starter, "/PROP/TYPE20"), [])

    def test_card_layout_and_ply_cards_are_column_exact(self):
        """radioss110/PROP/prop_p22_tsh_comp.cfg FORMAT(radioss90) — the newest
        block at or below 2022, since that file jumps straight from radioss90
        to radioss2023. The layer card is Phi(1-20) ti/t(21-40) Zi(41-60)
        mat_IDi(61-70)."""
        _, starter = _convert(deck(
            section=sec(elform=2, nip=4, shrf=0.9, icomp=1,
                        betas=(0.0, 45.0, -45.0, 90.0)),
            mat=mat_ortho(aopt=2.0)))
        c = _cards(_block(starter, "/PROP/TYPE22/1"))
        self.assertEqual(_col_i(c[0], 1, 10), 14)
        self.assertEqual(c[0][20:40], " " * 20)
        self.assertEqual(_col_i(c[0], 41, 50), 10)     # Icstr, NEVER blank
        self.assertEqual(_col_i(c[0], 51, 60), 242)
        self.assertEqual(_col_i(c[0], 61, 70), 0)      # Iint = layer count
        self.assertEqual(len(c[1]), 40)                # qa + qb
        self.assertEqual(_col_i(c[2], 81, 90), 0)      # Ipos = auto-stack
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 0.9)    # Ashear <- SHRF
        plies = c[4:8]
        self.assertEqual([_col_f(p, 1, 20) for p in plies],
                         [0.0, 45.0, -45.0, 90.0])
        self.assertEqual([_col_f(p, 21, 40) for p in plies], [0.25] * 4)
        self.assertEqual([_col_f(p, 41, 60) for p in plies], [0.0] * 4)
        self.assertEqual([_col_i(p, 61, 70) for p in plies], [1] * 4)
        self.assertEqual(_col_f(c[8], 1, 20), 0.0)     # DeltaT_min
        self.assertEqual(len(c), 9)

    def test_icstr_is_never_blank_on_type22(self):
        """THE trap. The CFG counts the layer cards itself in a chain that
        matches only Icstr == 100/10/1, so a blank column leaves N unset and the
        reader consumes the wrong number of cards while the starter expects
        NPTS. Measured on a blank-Icstr deck: WARNING 100213 'unsupported field
        exists at the end of line' then ERROR 675 with an EMPTY last layer —
        a SILENT wrong stack-up whenever the fractions happen to sum to 1."""
        for nip in (2, 5, 9):
            _, starter = _convert(deck(
                section=sec(elform=2, nip=nip, icomp=1,
                            betas=tuple(0.0 for _ in range(nip)))))
            card = _cards(_block(starter, "/PROP/TYPE22/1"))[0]
            self.assertEqual(_col_i(card, 41, 50), 10)
            self.assertEqual(_col_i(card, 51, 60), 200 + 10 * nip + 2)

    def test_ply_fractions_sum_to_one_within_the_starter_tolerance(self):
        """hm_read_prop22.F:395-405 computes INT(sum*100) and raises ERROR 675
        unless it is 100 +/- 1."""
        for nip in (2, 3, 4, 6, 7, 9):
            _, starter = _convert(deck(
                section=sec(elform=1, nip=nip, icomp=1,
                            betas=tuple(0.0 for _ in range(nip)))))
            c = _cards(_block(starter, "/PROP/TYPE22/1"))
            fracs = [_col_f(ln, 21, 40) for ln in c[4:4 + nip]]
            self.assertEqual(len(fracs), nip)
            self.assertEqual(abs(int(sum(fracs) * 100) - 100) <= 1, True,
                             f"NIP={nip} sum={sum(fracs)}")

    def test_more_than_nine_layers_use_the_iint_encoding(self):
        """A packed digit cannot exceed 9, so >9 layers zero the THICKNESS digit
        and put the count in Iint: hm_read_prop22.F:272-275 reads NLY from IINT
        only when NPTS is 0, and the CFG mirrors it."""
        angles = tuple(float(k) for k in range(12))
        _, starter = _convert(deck(
            section=sec(elform=2, nip=12, icomp=1, betas=angles)))
        c = _cards(_block(starter, "/PROP/TYPE22/1"))
        self.assertEqual(_col_i(c[0], 51, 60), 202)    # 2 . 0 . 2
        self.assertEqual(_col_i(c[0], 61, 70), 12)     # Iint = NLY
        self.assertEqual([_col_f(ln, 1, 20) for ln in c[4:16]], list(angles))

    def test_more_than_nine_layers_on_isolid_15_switch_formulation(self):
        """The >9-ply Iint encoding exists ONLY on Isolid=14 — on 15 the layer
        count IS Inpts, which the reader caps at 9. Writing 12 layer cards under
        an Inpts that says 9 desyncs the reader, so the property has to move to
        Isolid=14, and that changes the element formulation, so it is announced.
        (Clamping the CARD count instead would silently drop three plies.)"""
        angles = tuple(float(k) for k in range(12))
        result, starter = _convert(deck(
            section=sec(elform=1, nip=12, icomp=1, betas=angles)))
        c = _cards(_block(starter, "/PROP/TYPE22/1"))
        self.assertEqual(_col_i(c[0], 1, 10), 14)
        self.assertEqual(_col_i(c[0], 51, 60), 202)
        self.assertEqual(_col_i(c[0], 61, 70), 12)
        self.assertEqual(len([ln for ln in c[4:] if _col_i(ln, 61, 70)]), 12)
        self.assertTrue(_warns(result, "switches to the full-integration "
                                       "Isolid=14"), result.warnings)

    def test_the_layer_card_count_always_matches_the_declared_count(self):
        """The one invariant that makes a TYPE22 readable at all: the number of
        cards the CFG computes from Icstr + the unpacked Inpts digits (or from
        Iint when the thickness digit is 0) must equal the number written."""
        for elform in (1, 2):
            for nip in (1, 2, 5, 9, 10, 12):
                _, starter = _convert(deck(
                    section=sec(elform=elform, nip=nip, icomp=1,
                                betas=tuple(0.0 for _ in range(nip)))))
                c = _cards(_block(starter, "/PROP/TYPE22/1"))
                isolid = _col_i(c[0], 1, 10)
                nbp, iint = _col_i(c[0], 51, 60), _col_i(c[0], 61, 70)
                if isolid == 15:
                    declared = nbp             # NLY = Inpts, no packing
                elif iint > 9:
                    declared = iint            # thickness digit zeroed
                else:
                    declared = (nbp // 10) % 10        # Icstr=010 -> NPTS
                written = len(c) - 5          # cards 3,4,5,6 + DeltaT_min
                self.assertEqual(declared, nip, f"{elform}/{nip}")
                self.assertEqual(written, nip, f"{elform}/{nip}")

    def test_nine_layers_still_use_the_packed_digit(self):
        """The boundary: 9 fits the digit, 10 does not."""
        _, starter = _convert(deck(
            section=sec(elform=2, nip=9, icomp=1,
                        betas=tuple(0.0 for _ in range(9)))))
        c = _cards(_block(starter, "/PROP/TYPE22/1"))
        self.assertEqual(_col_i(c[0], 51, 60), 292)
        self.assertEqual(_col_i(c[0], 61, 70), 0)

    def test_icomp_layers_all_carry_the_parts_own_material(self):
        """LS-DYNA's ICOMP states one ANGLE per integration point and nothing
        else — no per-layer material and no per-layer thickness — so a
        heterogeneous laminate is not expressible through this card. Same as
        dyna2rad, which pushes matEntityRead.GetId() NIP times."""
        result, starter = _convert(deck(
            section=sec(nip=3, icomp=1, betas=(0.0, 90.0, 0.0))))
        plies = _cards(_block(starter, "/PROP/TYPE22/1"))[4:7]
        self.assertEqual({_col_i(p, 61, 70) for p in plies}, {1})
        self.assertTrue(_warns(result, "needs *PART_COMPOSITE_TSHELL instead"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class PerElementOptions(unittest.TestCase):
    """_BETA and _COMPOSITE: data Radioss has no per-element home for."""

    def test_beta_rides_on_columns_65_to_80_of_a_five_by_f16_card(self):
        """The manual's 10-column table for card 2a is wrong; an LS-PrePost
        round trip re-emits the ruler "$# - - - - beta", i.e. five F16 cells
        with BETA last."""
        state = _dispatch("*KEYWORD\n" + NODES
                          + "*ELEMENT_TSHELL_BETA\n"
                          + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                          + " " * 64 + f"{30.0:>16}" + "\n" + "*END\n")
        self.assertEqual(len(state.tshell_elems), 1)
        self.assertAlmostEqual(state.tshell_elems[0].beta, 30.0)

    def test_beta_folds_into_the_property_angle(self):
        """/BRICK has no per-element angle column at all, so a section-wide
        angle moves onto /PROP/TYPE21's Phi and the element's own value is
        zeroed — the deck then states it exactly once."""
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL_BETA\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + " " * 64 + f"{30.0:>16}" + "\n",
            mat=mat_ortho(aopt=2.0)))
        self.assertAlmostEqual(
            _col_f(_cards(_block(starter, "/PROP/TYPE21/1"))[3], 1, 20), 30.0)
        self.assertTrue(_warns(result, "was FOLDED into the"),
                        result.warnings)

    def test_a_mixed_beta_is_dropped_not_guessed_at(self):
        """Two different angles on one section cannot both reach a per-SECTION
        property, and grouping the elements would be a guess at what the user
        meant."""
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL_BETA\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + " " * 64 + f"{30.0:>16}" + "\n"
                 + _row(2, 1, 2, 9, 10, 3, 6, 11, 12, 7) + "\n"
                 + " " * 64 + f"{60.0:>16}" + "\n",
            mat=mat_ortho(aopt=2.0)))
        self.assertEqual(len(_block(starter, "/BRICK/1")), 3)   # both kept
        self.assertAlmostEqual(
            _col_f(_cards(_block(starter, "/PROP/TYPE21/1"))[3], 1, 20), 0.0)
        self.assertTrue(_warns(result, "carry DIFFERENT per-element angles"),
                        result.warnings)

    def test_beta_on_an_isotropic_section_is_reported_as_dropped(self):
        result, _ = _convert(deck(
            elem="*ELEMENT_TSHELL_BETA\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + " " * 64 + f"{30.0:>16}" + "\n"))
        self.assertTrue(_warns(result, "isotropic /PROP/TYPE20, which has no "
                                       "material direction to rotate"),
                        result.warnings)

    def test_composite_ply_cards_are_read_and_the_walk_does_not_desync(self):
        """Card 2b is MID1 THICK1 B1 - MID2 THICK2 B2 -, variable length, and
        the block ends only where the next element's connectivity card starts.
        A desync here turns a ply card into an element on undefined nodes."""
        state = _dispatch(
            "*KEYWORD\n" + NODES
            + "*ELEMENT_TSHELL_COMPOSITE\n"
            + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
            + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n"
            + _row(2, 1, 2, 9, 10, 3, 6, 11, 12, 7) + "\n"
            + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n" + "*END\n")
        self.assertEqual([e.eid for e in state.tshell_elems], [1, 2])
        self.assertEqual([(p.mid, p.thick, p.beta)
                          for p in state.tshell_elem_plies[1]],
                         [(1, 0.6, 0.0), (2, 0.4, 90.0)])

    def test_a_uniform_element_layup_is_promoted_to_a_part_type22(self):
        """Radioss states a layup on the PROPERTY, never on the element, so the
        promotion is valid only when every thick shell of the part agrees."""
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL_COMPOSITE\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n"
                 + _row(2, 1, 2, 9, 10, 3, 6, 11, 12, 7) + "\n"
                 + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n",
            mat=MAT_ISO + MAT_ISO2))
        prop = _block(starter, "/PROP/TYPE22/")
        prop_id = int(prop[0].rsplit("/", 1)[1])
        # The /PART is repointed at the synthesized property.
        self.assertEqual(_col_i(_cards(_block(starter, "/PART/1"))[0], 1, 10),
                         prop_id)
        plies = _cards(prop)[4:6]
        self.assertEqual([_col_i(p, 61, 70) for p in plies], [1, 2])
        self.assertEqual([_col_f(p, 21, 40) for p in plies], [0.6, 0.4])
        self.assertTrue(_warns(result, "declare one identical ply stack"),
                        result.warnings)

    def test_a_ragged_element_layup_is_dropped_and_the_mesh_survives(self):
        result, starter = _convert(deck(
            elem="*ELEMENT_TSHELL_COMPOSITE\n"
                 + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n"
                 + _row(2, 1, 2, 9, 10, 3, 6, 11, 12, 7) + "\n"
                 + _row(1, 0.3, 0.0, "", 2, 0.7, 45.0, "") + "\n",
            mat=MAT_ISO + MAT_ISO2))
        self.assertEqual(len(_block(starter, "/BRICK/1")), 3)
        self.assertEqual(_blocks(starter, "/PROP/TYPE22"), [])
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE20/1")), 1)
        self.assertTrue(_warns(result, "DIFFERENT per-element ply stacks"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class PartCompositeTshell(unittest.TestCase):
    """*PART_COMPOSITE_TSHELL -> a real /PROP/TYPE22.

    dyna2rad dispatches this keyword on the substring "COMPOSITE" alone
    (convertprops.cxx:92) and emits the THIN-shell /PROP/TYPE51 +
    /PROP/TYPE19 sandwich, which its own starter then refuses on the bricks:
    ERROR 60 INVALID PROPERTY ID=1 (TYPE = 51) FOR BRICK ELEMENT, then
    ERROR 226 WRONG SOLID PROPERTY TYPE 51. Its ply thicknesses also go out as
    ABSOLUTE lengths, where TYPE22 wants a fraction.
    """

    PC = ("*PART_COMPOSITE_TSHELL\n"
          "laminated thick shell\n"
          + _row(1, 2, 0.7, "", "", 0, "", 0) + "\n"
          + _row(1, 0.6, 0.0, "", 2, 0.4, 45.0, "") + "\n")

    def test_layup_becomes_a_type22_with_real_per_ply_data(self):
        _, starter = _convert(deck(part=self.PC, section="",
                                   mat=mat_ortho(aopt=2.0) + MAT_ISO2))
        self.assertEqual(_blocks(starter, "/PROP/TYPE51"), [])
        self.assertEqual(_blocks(starter, "/PROP/TYPE19"), [])
        c = _cards(_block(starter, "/PROP/TYPE22/"))
        self.assertEqual(_col_i(c[0], 1, 10), 14)      # ELFORM 2 on card 3b
        self.assertEqual(_col_i(c[0], 41, 50), 10)
        self.assertEqual(_col_i(c[0], 51, 60), 222)    # 2 layers
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 0.7)    # Ashear <- SHRF
        plies = c[4:6]
        self.assertEqual([_col_i(p, 61, 70) for p in plies], [1, 2])

    def test_thicknesses_become_relative_fractions(self):
        """"For thick shells, the total thickness is obtained from the
        positions of the nodes ... the THICKi are also scaled to conform to the
        geometry" (Vol I R16 p.3529) — which IS /PROP/TYPE22's ti/t semantic.
        So ti/t = THICKi / sum(THICKj), no absolute length anywhere."""
        pc = ("*PART_COMPOSITE_TSHELL\n"
              "laminate\n" + _row(1, 2, "", "", "", 0, "", 0) + "\n"
              + _row(1, 1.5, 0.0, "", 2, 0.5, 90.0, "") + "\n")
        _, starter = _convert(deck(part=pc, section="",
                                   mat=mat_ortho() + MAT_ISO2))
        plies = _cards(_block(starter, "/PROP/TYPE22/"))[4:6]
        self.assertEqual([_col_f(p, 21, 40) for p in plies], [0.75, 0.25])
        self.assertAlmostEqual(sum(_col_f(p, 21, 40) for p in plies), 1.0)

    def test_layer_positions_are_left_to_the_starter(self):
        """Zi = 0 with Ipos = 0 makes the starter stack from the bottom itself:
        Z1 = -0.5 + t1/2, Zk = Z(k-1) + (tk + t(k-1))/2 (prop22:429-433). The
        #98 lesson: writing a SAMPLING coordinate into Zi with Ipos = 1 makes it
        derive the stack from the layer ENVELOPE and leaves gaps."""
        _, starter = _convert(deck(part=self.PC, section="",
                                   mat=mat_ortho() + MAT_ISO2))
        c = _cards(_block(starter, "/PROP/TYPE22/"))
        self.assertEqual(_col_i(c[2], 81, 90), 0)             # Ipos
        self.assertEqual([_col_f(p, 41, 60) for p in c[4:6]], [0.0, 0.0])

    def test_a_thin_shell_mesh_keeps_the_old_fallback(self):
        """The pre-existing path must not change: a _TSHELL spelling whose
        elements are thin shells has nowhere to put a thick-shell layup, so it
        still warn-falls back to a plain shell property carrying the summed
        thickness — and never loses the mesh."""
        thin = ("*KEYWORD\n" + NODES
                + "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
                + self.PC + MAT_ISO + MAT_ISO2 + "*END\n")
        result, starter = _convert(thin)
        self.assertEqual(_blocks(starter, "/PROP/TYPE22"), [])
        self.assertEqual(len(_blocks(starter, "/SHELL/1")), 1)
        self.assertTrue(_warns(result, "only the thin-shell form converts"),
                        result.warnings)

    def test_tshear_on_card_3b_is_named_not_silently_lost(self):
        """Card 3b puts TSHEAR in the column the thin-shell card 3a uses for
        THSHEL, so it needs its own read. Naming it on the *SECTION_TSHELL path
        and dropping it silently here would be worse than either."""
        pc = ("*PART_COMPOSITE_TSHELL\n"
              "laminate\n" + _row(1, 2, "", "", "", 0, "", 1) + "\n"
              + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n")
        result, _ = _convert(deck(part=pc, section="",
                                  mat=mat_ortho() + MAT_ISO2))
        self.assertTrue(_warns(result, "TSHEAR=1"), result.warnings)

    def test_a_dangling_ply_material_is_named(self):
        pc = ("*PART_COMPOSITE_TSHELL\n"
              "laminate\n" + _row(1, 2, "", "", "", 0, "", 0) + "\n"
              + _row(1, 0.6, 0.0, "", 44, 0.4, 90.0, "") + "\n")
        result, _ = _convert(deck(part=pc, section="", mat=mat_ortho()))
        self.assertTrue(_warns(result, "ply material 44 is NOT emitted"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class MaterialCompatibility(unittest.TestCase):
    """The pre-starter ERROR 3046 / 3047 / WARNING 791 report.

    check_mat_elem_prop_compatibility.F:198-234 gates each thick-shell property
    on the material's PROP_SOLID class: TYPE20 takes 1/5/6, TYPE21 takes 1/2/6,
    TYPE22 takes 1/2/3/6. Measured on starter_win64: /MAT/LAW12 on a TYPE20
    gives ERROR 3047, and the same LAW12 on a TYPE21 is accepted.
    """

    def test_law1_integration_reset_is_warned(self):
        """sgrtails.F:694-704 force-resets Inpts to 2 / 222 for a LAW1 thick
        shell and raises WARNING 791, silently discarding the deck's NIP.
        TYPE22 is exempt."""
        result, _ = _convert(deck(section=sec(elform=2, nip=5)))
        w = _warns(result, "WARNING 791")
        self.assertEqual(len(w), 1, result.warnings)
        self.assertIn("sets Inpts to 222", w[0])

    def test_law1_at_the_reset_value_is_not_warned(self):
        """The starter only resets when the value DIFFERS, so a NIP that
        already lands on 222 / 2 costs nothing and must not be reported."""
        result, _ = _convert(deck(section=sec(elform=2, nip=2)))
        self.assertEqual(_warns(result, "WARNING 791"), [])
        result, _ = _convert(deck(section=sec(elform=1, nip=2)))
        self.assertEqual(_warns(result, "WARNING 791"), [])

    def test_law1_on_type22_is_exempt(self):
        result, _ = _convert(deck(
            section=sec(elform=2, nip=5, icomp=1,
                        betas=(0.0, 0.0, 0.0, 0.0, 0.0))))
        self.assertEqual(_warns(result, "WARNING 791"), [])

    def test_a_shell_only_law_is_reported_as_error_3046(self):
        """*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC -> /MAT/LAW43, which
        declares no solid class at all: the ELEMENT test fails one step before
        any property is examined."""
        mat37 = ("*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC\n"
                 + _row(1, 7.85e-9, 210000.0, 0.3, 200.0, 1000.0, 1.5) + "\n"
                 + _row(0.0, 0.0, 0.0) + "\n")
        result, _ = _convert(deck(mat=mat37))
        w = _warns(result, "ERROR 3046")
        self.assertTrue(w, result.warnings)
        self.assertIn("/MAT/LAW43", w[0])

    def test_a_porous_law_on_the_composite_property_is_error_3047(self):
        """/MAT/LAW6 is SOLID_POROUS (class 5), which only the ISOTROPIC TYPE20
        accepts — hm_read_mat06.F:185-194. On a TYPE22 it is ERROR 3047."""
        fluid = ("*MAT_ELASTIC_FLUID\n"
                 + _row(1, 1.0e-9, 2200.0, 0.0, 0.0, 0.0, 0.0, 2200.0) + "\n")
        result, _ = _convert(deck(
            section=sec(nip=2, icomp=1, betas=(0.0, 0.0)), mat=fluid))
        w = _warns(result, "ERROR 3047")
        self.assertTrue(w, result.warnings)
        self.assertIn("class is 5", w[0])

    def test_an_orthotropic_law_never_lands_on_type20(self):
        """Which is the whole point of the ICOMP=0 split: class 2 is exactly
        what TYPE20 rejects."""
        _, starter = _convert(deck(mat=mat_ortho()))
        self.assertEqual(_blocks(starter, "/PROP/TYPE20"), [])
        self.assertEqual(_warns(_convert(deck(mat=mat_ortho()))[0],
                                "ERROR 3047"), [])


# ═════════════════════════════════════════════════════════════════════════════
class DroppedFields(unittest.TestCase):
    """PROPT / QR / TSHEAR — read, warned, and not written. dyna2rad drops all
    three without a message."""

    def test_tshear_is_named_as_a_physics_change(self):
        result, _ = _convert(deck(section=sec(tshear=1)))
        w = _warns(result, "Dropped")
        self.assertTrue(w, result.warnings)
        self.assertIn("TSHEAR=1", w[0])
        self.assertIn("parabolic", w[0])

    def test_propt_is_named_as_output_only(self):
        result, _ = _convert(deck(section=sec(propt=3)))
        self.assertIn("PROPT=3", _warns(result, "Dropped")[0])

    def test_a_negative_qr_names_the_integration_rule_it_loses(self):
        """QR < 0 makes |QR| an *INTEGRATION_SHELL rule id (Vol I R16 p.29-1).
        A thick shell has no user quadrature rule in Radioss."""
        result, _ = _convert(deck(section=sec(qr=-7.0)))
        w = _warns(result, "Dropped")
        self.assertIn("*INTEGRATION_SHELL rule 7", w[0])

    def test_elform_losses_are_named_per_formulation(self):
        """1/2/6 are extruded THIN shells with an uncoupled thickness-direction
        stiffness; every Radioss thick shell is a 3D-stress element. 5 and 6 are
        reduced-integration and land on the full-integration HA8."""
        result, _ = _convert(deck(section=sec(elform=6, nip=3)))
        w = _warns(result, "loses")
        self.assertTrue(w, result.warnings)
        self.assertIn("REDUCED integration", w[0])
        self.assertIn("PLANE-STRESS", w[0])

    def test_an_out_of_range_elform_is_reported(self):
        """The thick-shell set is 1/2/3/5/6/7 — there is no ELFORM 4."""
        result, _ = _convert(deck(section=sec(elform=4, nip=3)))
        self.assertTrue(_warns(result, "is not a thick-shell formulation"),
                        result.warnings)

    def test_a_blank_elform_states_the_dyna2rad_divergence(self):
        result, _ = _convert(deck(section=sec(elform="", nip=3)))
        self.assertTrue(_warns(result, "dyna2rad reads the blank as 0"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class IncludeTransformOffsets(unittest.TestCase):
    """*INCLUDE_TRANSFORM id offsetting must mirror the handler's own walks, or
    an included deck keeps its original ids while the rest is offset."""

    OFF = {"n": 1000, "e": 2000, "p": 30, "r": 40, "m": 50}

    def _off(self, keyword: str, body: str):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n" + keyword + "\n" + body + "*END\n")
        blocks = [b for b in parse_k_file(path) if b.keyword == keyword[1:]]
        assert len(blocks) == 1
        _offset_block(blocks[0], _OFFSET_SPECS[keyword[1:]], self.OFF,
                      lambda m: None)
        tmp.cleanup()
        return blocks[0].raw

    def test_element_tshell_offsets_eid_pid_and_all_eight_nodes(self):
        raw = self._off("*ELEMENT_TSHELL",
                        "       1       1       1       2       3       4"
                        "       5       6       7       8\n")
        got = [int(raw[0][k * 8:(k + 1) * 8]) for k in range(10)]
        self.assertEqual(got, [2001, 31, 1001, 1002, 1003, 1004,
                               1005, 1006, 1007, 1008])

    def test_the_beta_card_is_stridden_and_left_alone(self):
        """Card 2a holds no id, but eating it as if it were a connectivity card
        would offset the NEXT element wrongly — or worse, rewrite a float."""
        raw = self._off("*ELEMENT_TSHELL_BETA",
                        "       1       1       1       2       3       4"
                        "       5       6       7       8\n"
                        + " " * 64 + f"{30.0:>16}" + "\n"
                        "       2       1       2       9      10       3"
                        "       6      11      12       7\n"
                        + " " * 64 + f"{60.0:>16}" + "\n")
        self.assertEqual(int(raw[0][:8]), 2001)
        self.assertEqual(raw[1].strip(), "30.0")
        self.assertEqual(int(raw[2][:8]), 2002)
        self.assertEqual(raw[3].strip(), "60.0")

    def test_the_composite_ply_card_offsets_its_material_ids(self):
        """Card 2b's MID columns are the only *MAT reference on any *ELEMENT_
        card in the converter, so IDMOFF has to reach them."""
        raw = self._off("*ELEMENT_TSHELL_COMPOSITE",
                        "       1       1       1       2       3       4"
                        "       5       6       7       8\n"
                        + _row(1, 0.6, 0.0, "", 2, 0.4, 90.0, "") + "\n")
        self.assertEqual(int(raw[0][:8]), 2001)
        self.assertEqual(int(raw[1][0:10]), 51)      # MID1 + IDMOFF
        self.assertEqual(int(raw[1][40:50]), 52)     # MID2 + IDMOFF
        # The thicknesses and angles on the same card must come through
        # untouched — a re-slice that rewrote them would corrupt the layup.
        self.assertEqual([float(raw[1][10:20]), float(raw[1][20:30]),
                          float(raw[1][50:60]), float(raw[1][60:70])],
                         [0.6, 0.0, 0.4, 90.0])

    def test_section_tshell_offsets_every_set_secid(self):
        raw = self._off("*SECTION_TSHELL",
                        _row(1, 2, "", 3) + "\n"
                        + _row(2, 1, "", 5) + "\n")
        self.assertEqual(int(raw[0][:10]), 41)
        self.assertEqual(int(raw[1][:10]), 42)

    def test_section_tshell_strides_the_icomp_angle_block(self):
        """The angle block is card 2 here, one card EARLIER than on
        *SECTION_SHELL — striding it as if it were card 3 would offset the next
        set's SECID out of an angle card."""
        raw = self._off("*SECTION_TSHELL",
                        _row(1, 2, "", 9, "", "", 1, "") + "\n"
                        + _row(0.0, 45.0, -45.0, 90.0, 0.0, 45.0, -45.0, 90.0)
                        + "\n"
                        + _row(0.0) + "\n"
                        + _row(2, 1, "", 5) + "\n")
        self.assertEqual(int(raw[0][:10]), 41)
        self.assertEqual(raw[1], _row(0.0, 45.0, -45.0, 90.0,
                                      0.0, 45.0, -45.0, 90.0))
        self.assertEqual(int(raw[3][:10]), 42)

    def test_the_negated_qr_reference_moves_with_the_rule(self):
        raw = self._off("*SECTION_TSHELL", _row(1, 2, "", 3, "", -7.0) + "\n")
        self.assertEqual(int(raw[0][:10]), 41)
        self.assertAlmostEqual(float(raw[0][50:60]), -47.0)


# ═════════════════════════════════════════════════════════════════════════════
class NoRegressionWithoutTheKeyword(unittest.TestCase):
    """A deck with no thick shell must come out BYTE-IDENTICAL: the batch adds
    a container, a prepass and an emit block, every one of which is gated."""

    DECK = ("*KEYWORD\n" + NODES
            + "*ELEMENT_SOLID\n" + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
            + "*PART\nsolid part\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + MAT_ISO + "*END\n")

    def test_a_solid_deck_is_untouched(self):
        result, starter = _convert(self.DECK)
        self.assertIn("/PROP/SOLID/1", starter)
        self.assertEqual(_blocks(starter, "/PROP/TYPE20"), [])
        self.assertEqual(_blocks(starter, "/PROP/TYPE21"), [])
        self.assertEqual(_blocks(starter, "/PROP/TYPE22"), [])
        self.assertEqual([w for w in result.warnings if "TSHELL" in w], [])

    def test_the_solid_bucket_still_splits_tets_from_bricks(self):
        """The thick-shell bucket must not have stolen anything from it."""
        tet = ("*KEYWORD\n" + NODES
               + "*ELEMENT_SOLID\n" + _row(1, 1, 1, 2, 3, 5, 5, 5, 5, 5) + "\n"
               + "*PART\ntet part\n" + _row(1, 1, 1) + "\n"
               + "*SECTION_SOLID\n" + _row(1, 10) + "\n" + MAT_ISO + "*END\n")
        _, starter = _convert(tet)
        self.assertEqual(len(_blocks(starter, "/TETRA4/1")), 1)

    def test_next_prop_id_skips_a_tshell_secid(self):
        """/PROP/TYPE20|21|22 sits under the SECID verbatim, so it is a FOURTH
        SECID-keyed /PROP namespace: a *SECTION_TSHELL at or above the auto-id
        base would otherwise collide with a synthesized property."""
        state = ConversionState()
        state.sec_tshells[90001] = object()
        self.assertNotEqual(state.next_prop_id(), 90001)


if __name__ == "__main__":
    unittest.main()
