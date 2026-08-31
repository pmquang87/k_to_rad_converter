"""Post-review round of the SIDE-DEFECT batch.

Two blockers, three majors and six minors found by reviewing the batch itself.
Each test carries the MEASUREMENT that settles it — a twin conversion, the
manual sentence, or the starter/engine source line — because in every one of
these the first implementation was self-consistent and wrong.

  * ``_plane_cut``'s degenerate-normal arm returned a 4-tuple while both call
    sites unpacked 5, so a zero XCT->XCH killed the WHOLE conversion.
  * ``*PARAMETER_LOCAL`` was DEFINED and then discarded before anything could
    use it: k2rad resolves ``&name`` lazily, in the handlers, long after the
    file that owns the LOCAL name is closed.
  * ``*PARAMETER_TYPE`` is a definition (p.36-11), not a hint to drop.
  * ``TSID`` was resolved in the ``*SET_SHELL`` registry — a different LS-DYNA
    id namespace.
  * ``RADIUS < 0`` was resolved against ``state.nodes`` in the HANDLER, so the
    result depended on whether the card came before or after ``*NODE``.
  * The comma-delimited ``*PARAMETER_EXPRESSION`` — the form the manual uses in
    its own worked example — was split at column 10.
  * The ``_PLANE`` spring arm reported a force LS-DYNA's ``secforc`` does not.
  * ``Iframe`` was 0 where the card's ID cell defaults to "global".
  * The section ``/GRNOD`` came from the bare allocator.
  * A ``RecursionError`` escaped both ``except ExprError`` sites.
  * A UTF-8 em-dash reached the emitted ``.rad``.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                            # noqa: E402
from k2rad import parser as _parser                  # noqa: E402
from k2rad import paramexpr as _paramexpr            # noqa: E402
from k2rad.parser import parse_k_file                # noqa: E402
from k2rad.writer.inistate import _plane_cut         # noqa: E402
from k2rad.state import ConversionState, CrossSection  # noqa: E402


# ── harness ──────────────────────────────────────────────────────────────────

def _row(*vals) -> str:
    out = "".join(f"{v:>10}" for v in vals)
    assert len(out) == 10 * len(vals), f"field overflow in {out!r}"
    return out


def _node16(nid: int, x: float, y: float, z: float) -> str:
    return f"{nid:>8}{x:>16.9G}{y:>16.9G}{z:>16.9G}"


def _i8(*vals) -> str:
    return "".join(f"{v:>8}" for v in vals)


def _convert_files(files: dict, main: str = "main.k", **kw):
    """Write a whole multi-file deck and convert its main file.

    ``*PARAMETER_LOCAL`` scoping cannot be tested on a single file: the manual
    defines it in terms of "the file in which they appear".
    """
    tmp = tempfile.TemporaryDirectory()
    for name, text in files.items():
        with open(os.path.join(tmp.name, name), "w") as fh:
            fh.write(text)
    result = convert(os.path.join(tmp.name, main), write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _convert(deck: str, **kw):
    return _convert_files({"main.k": deck}, **kw)


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _prop_thick(starter: str, pid: int) -> float:
    """The Thick cell of ``/PROP/SHELL/<pid>``'s second data card."""
    lines = starter.splitlines()
    i = lines.index(f"/PROP/SHELL/{pid}")
    data = [ln for ln in lines[i + 1:i + 14] if not ln.startswith("#")]
    # title, card1 (Ishell..Idrill), card2 (hm..dn), card3 (N Istrain Thick ..)
    return float(data[3][20:40])


def _prop_nip(starter: str, pid: int) -> int:
    lines = starter.splitlines()
    i = lines.index(f"/PROP/SHELL/{pid}")
    data = [ln for ln in lines[i + 1:i + 14] if not ln.startswith("#")]
    return int(data[3][0:10])


# A one-shell model every parameter probe shares, so only the parameter
# machinery varies between them.
_MESH = "\n".join([
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4),
    "*PART", "plate", _row(1, 1, 1),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"), ""])


def _section(pid: int, ref: str) -> str:
    return "\n".join(["*SECTION_SHELL", _row(pid, 2),
                      _row(ref, ref, ref, ref), ""])


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 1 — the degenerate-normal arm's arity
# ─────────────────────────────────────────────────────────────────────────────

_ZERO_NORMAL = "\n".join([
    "*KEYWORD", "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    _node16(5, 0.0, 0.0, 10.0), _node16(6, 10.0, 0.0, 10.0),
    _node16(7, 10.0, 10.0, 10.0), _node16(8, 0.0, 10.0, 10.0),
    "*ELEMENT_SOLID", _i8(1, 1), _i8(1, 2, 3, 4, 5, 6, 7, 8),
    "*SECTION_SOLID", _row(1, 1),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "brick", _row(1, 1, 1),
    "*DATABASE_CROSS_SECTION_PLANE",
    _row(0, "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
    _row("0.0", "0.0", "0.0", "0.0"),
    "*CONTROL_TERMINATION", _row("1.0"),
    "*END", ""])


class TestPlaneCutDegenerateArity(unittest.TestCase):
    """A ``*DATABASE_CROSS_SECTION_PLANE`` whose XCT->XCH is a ZERO vector.

    Every field defaults to 0.0 (Vol I R17 p.16-49), so an all-blank card is
    legal input. ``_vnorm`` then returns None and ``_plane_cut`` took its early
    exit — which returned ``([], [], [], [])`` while every other path and BOTH
    call sites unpack FIVE arms since the spring arm was added.

    MEASURED before the fix: ``ValueError: not enough values to unpack
    (expected 5, got 4)`` out of ``writer/assembly.py``, the conversion dead
    and NO deck written at all. Master converts this deck and warns. No corpus
    deck carries the shape, so the sweep cannot see it.
    """

    def test_the_conversion_survives_a_zero_length_plane_normal(self):
        res, starter = _convert(_ZERO_NORMAL)
        self.assertEqual(_headers(starter, "/SECT/"), [])
        self.assertEqual(len(_warns(res, "the plane cuts no element")), 1)

    def test_every_return_path_has_five_arms(self):
        """Arity check on the degenerate branch itself, so the next arm added
        to ``_plane_cut`` cannot repeat this: the caller's unpack is the only
        thing that noticed."""
        state = ConversionState()
        cs = CrossSection(csid=1, title="", kind="PLANE")   # all coords 0.0
        self.assertEqual(len(_plane_cut(state, cs)), 5)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 2 — *PARAMETER_LOCAL scoping under LAZY resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestParameterLocalReachesTheCard(unittest.TestCase):
    """Vol I R17 p.36-4 Remark 5: a LOCAL parameter *"disappears when the input
    parser ﬁnishes reading the ﬁle in which"* it appears, and *"LOCAL variables
    can temporarily mask non-LOCAL variables."*

    Scoping is a PARSE-TIME concept in LS-DYNA. k2rad resolves ``&name``
    LAZILY — ``parse_k_file`` only records ``Block.raw`` and the handlers call
    ``to_float`` during dispatch, after the whole deck (every include) has been
    read — so popping the frame at the end of each file deleted the binding
    before any field could use it.

    MEASURED before the fix, on the three decks below: ``/PROP/SHELL Thick 0``
    with *"'&lthk' is undefined"* on a perfectly valid deck (starter
    ``ERROR ID : 495 ** ERROR IN SHELL DEFINITION``, ERROR TERMINATION), and
    the masking case silently emitting the OUTER value. Master emitted 2.5 and
    9 respectively — it modelled no scoping at all, which is right for the
    common case and wrong after the file ends.

    The fix is not "stop popping": each Block carries the LOCAL bindings that
    were live where it was READ (``Block.scope``), and ``dispatch`` installs
    them for the duration of the handler. So both halves hold at once.
    """

    def test_a_top_level_LOCAL_parameter_reaches_the_emitted_card(self):
        res, starter = _convert("\n".join([
            "*KEYWORD",
            "*PARAMETER_LOCAL", _row("R lthk", "2.5"),
            _MESH, _section(1, "&lthk"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]))
        self.assertAlmostEqual(_prop_thick(starter, 1), 2.5)
        self.assertEqual(_warns(res, "'&lthk' is undefined"), [])

    def test_a_LOCAL_inside_an_include_reaches_that_files_card(self):
        res, starter = _convert_files({
            "main.k": "\n".join([
                "*KEYWORD", "*INCLUDE", "mesh.inc", "*INCLUDE", "sec.k",
                "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]),
            "mesh.inc": _MESH,
            "sec.k": "\n".join([
                "*PARAMETER_LOCAL", _row("R lthk", "2.5"),
                _section(1, "&lthk"), "*END", ""])})
        self.assertAlmostEqual(_prop_thick(starter, 1), 2.5)
        self.assertEqual(_warns(res, "'&lthk' is undefined"), [])

    def test_a_LOCAL_masks_the_outer_value_INSIDE_its_own_file(self):
        """The manual's own worked example: inside the include the LOCAL wins.
        Before the fix this emitted the restored OUTER value at ZERO
        diagnostics — the silent half."""
        _res, starter = _convert_files({
            "main.k": "\n".join([
                "*KEYWORD", "*PARAMETER", _row("R thk", "1.0"),
                "*INCLUDE", "mesh.inc", "*INCLUDE", "sec.k",
                "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]),
            "mesh.inc": _MESH,
            "sec.k": "\n".join([
                "*PARAMETER_LOCAL", _row("R thk", "9.0"),
                _section(1, "&thk"), "*END", ""])})
        self.assertAlmostEqual(_prop_thick(starter, 1), 9.0)

    def test_the_outer_value_comes_back_after_the_include(self):
        """p.36-5: *"In main.k, after returning from ﬁle1, we will see ...
        VAL2 = 2.0"*. This is the half MASTER got wrong (its table was
        last-wins, so the outer card kept reading 9.0 forever)."""
        _res, starter = _convert_files({
            "main.k": "\n".join([
                "*KEYWORD", "*PARAMETER", _row("R thk", "1.0"),
                "*INCLUDE", "mesh.inc", "*INCLUDE", "sec.k",
                "*SECTION_SHELL", _row(2, 2),
                _row("&thk", "&thk", "&thk", "&thk"),
                "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]),
            "mesh.inc": _MESH,
            "sec.k": "\n".join([
                "*PARAMETER_LOCAL", _row("R thk", "9.0"),
                _section(1, "&thk"), "*END", ""])})
        self.assertAlmostEqual(_prop_thick(starter, 1), 9.0)   # inside
        self.assertAlmostEqual(_prop_thick(starter, 2), 1.0)   # after

    def test_a_LOCAL_that_masked_nothing_is_gone_after_its_file(self):
        """p.36-5: *"VAL4 will not exist."* The reference outside the include
        is a genuine deck error and must be NAMED, not silently resolved."""
        res, starter = _convert_files({
            "main.k": "\n".join([
                "*KEYWORD", "*INCLUDE", "mesh.inc", "*INCLUDE", "sec.k",
                "*SECTION_SHELL", _row(2, 2),
                _row("&val4", "&val4", "&val4", "&val4"),
                "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]),
            "mesh.inc": _MESH,
            "sec.k": "\n".join([
                "*PARAMETER_LOCAL", _row("R val4", "40.0"),
                _section(1, "&val4"), "*END", ""])})
        self.assertAlmostEqual(_prop_thick(starter, 1), 40.0)
        self.assertAlmostEqual(_prop_thick(starter, 2), 0.0)
        self.assertEqual(len(_warns(res, "'&val4' is undefined")), 1)

    def test_a_LOCAL_masking_another_LOCAL_triggers_the_duplication_actions(
            self):
        """p.36-6 Remark 1, verbatim: *"A LOCAL variable appearing in a ﬁle,
        which masks a non-LOCAL parameter, won't trigger these actions;
        however, a LOCAL that masks another LOCAL or a non-LOCAL that masks a
        non-LOCAL will."* The exemption was scoped to "any LOCAL that masks
        anything", which also exempted the LOCAL-over-LOCAL case the sentence
        explicitly includes."""
        res, starter = _convert_files({
            "main.k": "\n".join([
                "*KEYWORD", "*PARAMETER_LOCAL", _row("R thk", "3.0"),
                "*INCLUDE", "mesh.inc", "*INCLUDE", "sec.k",
                "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]),
            "mesh.inc": _MESH,
            "sec.k": "\n".join([
                "*PARAMETER_LOCAL", _row("R thk", "9.0"),
                _section(1, "&thk"), "*END", ""])})
        # DFLAG defaults to 1 = warn + keep the FIRST definition (p.36-6).
        self.assertAlmostEqual(_prop_thick(starter, 1), 3.0)
        self.assertEqual(len(_warns(res, "'thk' is defined more than once")), 1)

    def test_a_LOCAL_masking_a_NON_local_is_exempt_from_them(self):
        """The other half of the same sentence: no duplication warning here."""
        res, _starter = _convert_files({
            "main.k": "\n".join([
                "*KEYWORD", "*PARAMETER", _row("R thk", "1.0"),
                "*INCLUDE", "mesh.inc", "*INCLUDE", "sec.k",
                "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]),
            "mesh.inc": _MESH,
            "sec.k": "\n".join([
                "*PARAMETER_LOCAL", _row("R thk", "9.0"),
                _section(1, "&thk"), "*END", ""])})
        self.assertEqual(_warns(res, "'thk' is defined more than once"), [])

    def test_a_deck_without_LOCAL_parameters_carries_no_scope_at_all(self):
        """Cost check: the snapshot is None on every ordinary deck, so a
        100k-block model pays nothing for a feature it does not use."""
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*PARAMETER\n" + _row("R thk", "1.0") + "\n"
                     + _MESH + _section(1, "&thk") + "*END\n")
        blocks = parse_k_file(path)
        tmp.cleanup()
        self.assertTrue(blocks)
        self.assertTrue(all(b.scope is None for b in blocks))


# ─────────────────────────────────────────────────────────────────────────────
# MAJOR — TSID lives in its own LS-DYNA id namespace
# ─────────────────────────────────────────────────────────────────────────────

def _tsid_deck(setkw: str, member: int) -> str:
    """A shell 101 and a solid 201, a node set, and a
    ``*DATABASE_CROSS_SECTION_SET`` whose TSID is 5. ``setkw`` decides which
    registry the id 5 lands in."""
    return "\n".join([
        "*KEYWORD", "*NODE",
        _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
        _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
        _node16(5, 0.0, 0.0, 10.0), _node16(6, 10.0, 0.0, 10.0),
        _node16(7, 10.0, 10.0, 10.0), _node16(8, 0.0, 10.0, 10.0),
        "*ELEMENT_SHELL", _i8(101, 1, 1, 2, 3, 4),
        "*ELEMENT_SOLID", _i8(201, 2), _i8(1, 2, 3, 4, 5, 6, 7, 8),
        "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
        "*SECTION_SOLID", _row(2, 1),
        "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
        "*PART", "plate", _row(1, 1, 1),
        "*PART", "block", _row(2, 2, 1),
        setkw, _row(5), _row(member),
        "*SET_NODE_LIST", _row(100), _row(1, 2, 3, 4),
        "*DATABASE_CROSS_SECTION_SET", _row(100, 0, 0, 0, 5, 0),
        "*CONTROL_TERMINATION", _row("1.0"),
        "*END", ""])


class TestSectTsidNamespace(unittest.TestCase):
    """``TSID`` names a ``*SET_TSHELL``. ``*SET_TSHELL``, ``*SET_SOLID`` and
    ``*SET_SHELL`` are three separate LS-DYNA SID namespaces and this converter
    reads no ``*SET_TSHELL`` at all.

    Resolving TSID in ``state.shell_sets`` therefore adopted whatever SHELLS
    happened to carry that number. MEASURED before the fix, on
    ``_tsid_deck("*SET_SHELL_LIST", 101)``: ``/GRBRIC/BRIC/90003`` containing
    element **101**, a SHELL id, which the starter resolves against the BRICK
    table. ``writer/rarecards.py:110-118`` states the same rule for
    ``*DEFINE_ELEMENT_DEATH_THICK_SHELL_SET`` — the guard existed one file
    over and this site had not been given it.
    """

    def _bric_group(self, starter: str):
        return _headers(starter, "/GRBRIC/BRIC/")

    def test_a_SET_SHELL_of_the_same_number_is_not_adopted(self):
        res, starter = _convert(_tsid_deck("*SET_SHELL_LIST", 101))
        self.assertEqual(self._bric_group(starter), [])
        self.assertNotIn("101", "".join(_headers(starter, "/GRBRIC")))
        w = _warns(res, "TSID names *SET_TSHELL 5")
        self.assertEqual(len(w), 1)
        self.assertIn("*SET_SHELL of the same number is deliberately NOT "
                      "accepted", w[0])

    def test_a_SET_SOLID_of_that_number_IS_adopted(self):
        """The documented fallback stays: a thick shell IS a /BRICK in the
        emitted deck, and decks do restate a tshell list as a *SET_SOLID."""
        res, starter = _convert(_tsid_deck("*SET_SOLID_LIST", 201))
        grp = self._bric_group(starter)
        self.assertEqual(len(grp), 1)
        gid = grp[0].rsplit("/", 1)[1]
        lines = starter.splitlines()
        i = lines.index(f"/GRBRIC/BRIC/{gid}")
        members = [int(t) for ln in lines[i + 2:i + 4]
                   if not ln.startswith("#") for t in ln.split()]
        self.assertEqual(members, [201])
        self.assertEqual(_warns(res, "TSID names *SET_TSHELL"), [])


# ─────────────────────────────────────────────────────────────────────────────
# MAJOR — RADIUS < 0 must not depend on where the card sits in the deck
# ─────────────────────────────────────────────────────────────────────────────

_RADNEG_MESH = "\n".join([
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    _node16(5, 0.0, 0.0, 10.0), _node16(6, 10.0, 0.0, 10.0),
    _node16(7, 10.0, 10.0, 10.0), _node16(8, 0.0, 10.0, 10.0),
    _node16(11, 20.0, 0.0, 0.0), _node16(12, 20.0, 10.0, 0.0),
    _node16(13, 20.0, 0.0, 10.0), _node16(14, 20.0, 10.0, 10.0),
    _node16(21, 5.0, 5.0, 5.0), _node16(22, 15.0, 5.0, 5.0),
    "*ELEMENT_SOLID", _i8(1, 1), _i8(1, 2, 3, 4, 5, 6, 7, 8),
    _i8(2, 1), _i8(2, 11, 12, 3, 6, 13, 14, 7),
    "*SECTION_SOLID", _row(1, 1),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "bar", _row(1, 1, 1), ""])

_RADNEG_CARD = "\n".join([
    "*DATABASE_CROSS_SECTION_PLANE",
    # XCT/XCH are NODE IDS because RADIUS < 0; the 999.0 cells are the
    # YCT/ZCT/YCH/ZCH the manual says are IGNORED.
    _row(0, 21, "999.0", "999.0", 22, "999.0", "999.0", "-12.0"), ""])


class TestCrossSectionNodeEndpointsAreResolvedLate(unittest.TestCase):
    """``RADIUS < 0`` makes XCT and XCH node ids (Vol I R17 p.16-50). The
    handler resolved them against ``state.nodes`` — but handlers are dispatched
    in DECK-BLOCK ORDER and ``handle_node`` fills that table in the SAME pass,
    so a card written before ``*NODE`` saw an EMPTY table.

    MEASURED on the twin below, which differs only in card order and has both
    nodes in both files: the card-first deck printed *"XCT=21 and XCH=22 NODE
    IDS ..., but they are not nodes of this deck — the cross section was
    SKIPPED"* and emitted no ``/SECT``. The nodes ARE in the deck; the message
    was untrue and it prescribed fixing a correct deck (#125/#131). No corpus
    deck uses RADIUS < 0, so the sweep is blind to it.
    """

    HEAD = "*KEYWORD\n"
    TAIL = "*CONTROL_TERMINATION\n" + _row("1.0") + "\n*END\n"

    def test_the_card_before_and_after_NODE_give_the_same_section(self):
        after = self.HEAD + _RADNEG_MESH + _RADNEG_CARD + self.TAIL
        before = self.HEAD + _RADNEG_CARD + _RADNEG_MESH + self.TAIL
        res_a, st_a = _convert(after)
        res_b, st_b = _convert(before)
        self.assertEqual(len(_headers(st_a, "/SECT/")), 1)
        self.assertEqual(len(_headers(st_b, "/SECT/")), 1)
        for res in (res_a, res_b):
            self.assertEqual(_warns(res, "not nodes of this deck"), [])
        # The plane is node 21 -> node 22, i.e. through (5,5,5) along +X, so
        # both decks must cut exactly the same element set.
        self.assertEqual([ln for ln in st_a.splitlines()
                          if ln.startswith("/GRBRIC/BRIC/")],
                         [ln for ln in st_b.splitlines()
                          if ln.startswith("/GRBRIC/BRIC/")])

    def test_the_ignored_cells_stay_ignored(self):
        """p.16-50: *"YCT, ZCT, YCH, and ZCH are ignored."* The 999.0 decoys
        must not reach the frame: N1 is node 21's own position."""
        _res, starter = _convert(
            self.HEAD + _RADNEG_MESH + _RADNEG_CARD + self.TAIL)
        lines = starter.splitlines()
        i = lines.index([ln for ln in lines if ln.startswith("/SECT/")][0])
        card1 = [ln for ln in lines[i + 1:i + 6] if not ln.startswith("#")][1]
        n1 = int(card1[0:10])
        xyz = None
        for j, ln in enumerate(lines):
            if ln.startswith("/NODE"):
                for row in lines[j + 1:j + 5]:
                    if row.startswith("#") or not row.strip():
                        continue
                    if int(row[0:10]) == n1:
                        xyz = (float(row[10:30]), float(row[30:50]),
                               float(row[50:70]))
        self.assertIsNotNone(xyz)
        for got, want in zip(xyz, (5.0, 5.0, 5.0)):
            self.assertAlmostEqual(got, want, places=9)

    def test_a_genuinely_absent_node_is_still_refused_after_the_full_parse(
            self):
        deck = (self.HEAD + _RADNEG_MESH
                + _RADNEG_CARD.replace(_row(0, 21, "999.0", "999.0", 22,
                                            "999.0", "999.0", "-12.0"),
                                       _row(0, 777, "999.0", "999.0", 888,
                                            "999.0", "999.0", "-12.0"))
                + self.TAIL)
        res, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/SECT/"), [])
        w = _warns(res, "XCT=777 and XCH=888 NODE IDS")
        self.assertEqual(len(w), 1)
        self.assertIn("neither is a node of this deck", w[0])


# ─────────────────────────────────────────────────────────────────────────────
# MAJOR — the comma-delimited *PARAMETER_EXPRESSION
# ─────────────────────────────────────────────────────────────────────────────

class TestParameterExpressionCommaForm(unittest.TestCase):
    """Vol I R17 p.36-8 Remark 1's OWN worked example is comma-delimited::

        *parameter
        rterm, 0.2, istates,  80
        *parameter_expression
        rplot,term/(states-30)

    and the manual states it is equivalent to ``<term/(states-30)>``, i.e.
    ``plot = 0.2/50 = 0.004``.

    Taking PRMR from ``line[:10]`` and the expression from ``line[10:]``
    unconditionally cut that to ``/(states-30)`` — the leading ``term`` eaten
    by the 10-column field — and lost a whole record when the value fits inside
    ten columns (``rxmin, -96`` is EXACTLY ten characters, so the expression
    came out empty). Real corpus carrier: dynaexamples
    ``IGA_tensile_test_input/tensile_test_iga.k`` writes four such base
    parameters plus eight box parameters that reference them.
    """

    def _params(self, text: str):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "p.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n" + text + "*END\n")
        parse_k_file(path)
        out = dict(_parser._PARAMS), list(_parser.PARSER_WARNINGS)
        tmp.cleanup()
        return out

    def test_the_manuals_own_worked_example(self):
        p, w = self._params("*parameter\n"
                            "rterm, 0.2, istates,  80\n"
                            "*parameter_expression\n"
                            "rplot,term/(states-30)\n")
        self.assertEqual(float(p["plot"]), 0.004)
        self.assertEqual([x for x in w if "could not be evaluated"], [])

    def test_a_value_that_fits_inside_ten_columns_is_not_lost(self):
        p, _w = self._params("*parameter_expression\n"
                             "rxmin, -96\n"
                             "rxmax, 96\n"
                             "rbox1xmin, &xmin-1.0\n")
        self.assertEqual(float(p["xmin"]), -96.0)
        self.assertEqual(float(p["xmax"]), 96.0)
        self.assertEqual(float(p["box1xmin"]), -97.0)

    def test_a_comma_INSIDE_a_fixed_format_expression_is_not_a_split(self):
        """The rule is "a comma in the PRMR field", not "any comma": a fixed
        format record whose expression calls a two-argument intrinsic carries a
        comma well past column 10 and must keep it."""
        p, w = self._params("*parameter\n" + _row("I n", "3") + "\n"
                            "*parameter_expression\n"
                            + f"{'Rsg':<10}" + "max(n,7)\n")
        self.assertEqual([x for x in w if "could not be evaluated"], [])
        self.assertEqual(float(p["sg"]), 7.0)

    def test_the_continuation_rule_is_unchanged(self):
        """p.36-7: a continuation leaves the first 10 characters blank."""
        p, _w = self._params("*parameter_expression\n"
                             "rlong,    1.0\n"
                             "             + 2.0\n")
        self.assertEqual(float(p["long"]), 3.0)


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — the evaluator refuses deep nesting BY NAME
# ─────────────────────────────────────────────────────────────────────────────

class TestParamExprDepthCap(unittest.TestCase):
    """``*PARAMETER_EXPRESSION`` supports continuation lines (p.36-7), so an
    arbitrarily long — and arbitrarily nested — expression is legal input.
    A deeply nested one raised ``RecursionError``, which neither
    ``except ExprError`` site in parser.py catches, so the whole conversion
    died with a traceback instead of refusing one parameter by name."""

    def test_a_deeply_nested_expression_is_an_ExprError_not_a_crash(self):
        src = "(" * 400 + "1" + ")" * 400
        with self.assertRaises(_paramexpr.ExprError) as cm:
            _paramexpr.evaluate(src, lambda n: None)
        self.assertIn("nests more than", str(cm.exception))

    def test_ordinary_nesting_still_evaluates(self):
        self.assertEqual(_paramexpr.evaluate("((((1+2))))", lambda n: None),
                         (3, True))

    def test_the_refusal_reaches_the_deck_as_a_warning(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "p.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*PARAMETER_EXPRESSION\n"
                     + f"{'Rdeep':<10}" + "(" * 400 + "1" + ")" * 400
                     + "\n*END\n")
        parse_k_file(path)
        warns = list(_parser.PARSER_WARNINGS)
        tmp.cleanup()
        self.assertTrue([w for w in warns if "nests more than" in w])


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — the section /GRNOD must dodge a user *SET_NODE
# ─────────────────────────────────────────────────────────────────────────────

_GRNOD_MESH = "\n".join([
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    _node16(5, 0.0, 0.0, 10.0), _node16(6, 10.0, 0.0, 10.0),
    _node16(7, 10.0, 10.0, 10.0), _node16(8, 0.0, 10.0, 10.0),
    "*ELEMENT_SOLID", _i8(1, 1), _i8(1, 2, 3, 4, 5, 6, 7, 8),
    "*SECTION_SOLID", _row(1, 1),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "brick", _row(1, 1, 1), ""])

_GRNOD_CARD = ("*DATABASE_CROSS_SECTION_PLANE\n"
               + _row(0, "5.0", "0.0", "0.0", "6.0", "0.0", "0.0", "0.0")
               + "\n")


def _grnod_deck(extra: str = "") -> str:
    return ("*KEYWORD\n" + _GRNOD_MESH + extra + _GRNOD_CARD
            + "*CONTROL_TERMINATION\n" + _row("1.0") + "\n*END\n")


class TestSectGrnodDodgesAUserSet(unittest.TestCase):
    """``_make_cross_sections`` minted its node group with the bare
    ``state.next_id()`` while ``_make_extra_groups`` re-emits every user
    ``*SET_NODE`` under its own SID — so a deck-stated node set at the auto-id
    base collides and the starter aborts with ``ERROR ID : 79 ** ERROR:
    DUPLICATE ID / IN NODE GROUP DEFINITION``.

    The probe targets the id the allocator ACTUALLY takes (#131's rule): the
    set-free twin is measured first, and only then is the user set planted on
    exactly that number. MEASURED against master on this deck:
    ``/GRNOD/NODE/90002`` emitted TWICE.
    """

    def test_the_bare_allocator_would_take_90002(self):
        """Allocation order, stated before the collision is built: /SECT takes
        90001 and its node group 90002."""
        _res, starter = _convert(_grnod_deck())
        self.assertEqual(_headers(starter, "/SECT/"), ["/SECT/90001"])
        self.assertIn("/GRNOD/NODE/90002", starter)

    def test_a_user_set_on_that_id_is_dodged(self):
        user = ("*SET_NODE_LIST\n" + _row(90002) + "\n" + _row(5, 6) + "\n")
        _res, starter = _convert(_grnod_deck(user))
        ids = [ln.rsplit("/", 1)[1] for ln in _headers(starter, "/GRNOD/NODE/")]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate /GRNOD: {ids}")
        self.assertIn("90002", ids)      # the user's own set, verbatim
        self.assertIn("90003", ids)      # the section's, moved out of the way


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — the emitted deck stays ASCII
# ─────────────────────────────────────────────────────────────────────────────

class TestStarterDeckIsAscii(unittest.TestCase):
    """A ``.rad`` is read by LS-PrePost, by the ``hm_reader`` and by cp1252
    consoles. A ``/TH/SECTIO`` header comment carried a UTF-8 em-dash — the
    first non-ASCII byte this converter had ever emitted (three bytes,
    ``\\xe2\\x80\\x94``). The starter accepts it, which is exactly why nothing
    caught it."""

    def test_a_section_deck_carries_no_byte_above_127(self):
        _res, starter = _convert(_grnod_deck())
        self.assertIn("/TH/SECTIO", starter)          # the carrier is present
        bad = [(i, ln) for i, ln in enumerate(starter.splitlines(), 1)
               if any(ord(c) > 127 for c in ln)]
        self.assertEqual(bad, [])


if __name__ == "__main__":                             # pragma: no cover
    unittest.main()
