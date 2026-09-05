"""Tests for the R14 CAMPAIGN TRIAGE batch, round 2.

Round 1 cleared the STARTER-error classes. Round 2 attacks the two open ENGINE
classes the 356-deck dynaexamples R14 campaign then measured — 69 decks that
terminate NORMAL with an internal energy below 1 % of their LS-DYNA reference,
and 42 whose implicit engine will not advance.

  A1  ``*NODE`` card 1's own TC/RC constraint cells
                                    -> one /GRNOD/NODE + /BCS per distinct
                                       (TC, RC) pair, DEFAULT ON, opt out with
                                       ``--no-node-tc-rc-bcs``; four screening
                                       rules, each counted in the message
  A2  the modal chain and TC/RC     -> a measured NON-item (no tools/ change);
                                       see ``TestModalChainNeedsNoTcRcArm``
  A3  starter ERROR 611             -> the synthesized implicit-stabilization
                                       stub takes Inacti = 1, and every
                                       /INTER/TYPE7 whose Inacti is 3/4/5/6
                                       gains an Fpenmax

Part B (set spellings, SSTYP = 0, /EOS/GRUNEISEN, the modal beam mass arm)
extends this module.

Kept in its own module, the repo's one-module-per-batch convention.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the four helpers of tests/test_r14_triage_1.py) ─────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _row16(*vals) -> str:
    """LS-DYNA *DEFINE_CURVE point row (2 x 16-char fields)."""
    return "".join(f"{v:>16}" for v in vals)


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


def _state_and_starter(deck: str, **kw):
    """Parse + dispatch + build_starter, returning the FINAL state (every
    writer prepass and every write-line register filled) and the deck text."""
    from k2rad.writer import build_starter
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState(**kw)
    for block in parse_k_file(path):
        dispatch(block, state)
    starter = build_starter(state)
    tmp.cleanup()
    return state, starter


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


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


def _n16(nid, x, y, z) -> str:
    return f"{nid:>8}{x:>16.9G}{y:>16.9G}{z:>16.9G}"


def _n16c(nid, x, y, z, tc, rc) -> str:
    """A *NODE row in the FIXED layout with its TC/RC cells filled: Vol I R17
    p.35-2 gives card 1 the grid (I8, 3E16.0, 2I8), so TC is cols 57-64 and RC
    cols 65-72."""
    return _n16(nid, x, y, z) + f"{tc:>8}{rc:>8}"


def _bcs_groups(starter: str):
    """``{(Tra, Rot): [node ids]}`` for every ``/BCS`` in the TC/RC block.

    Reads the EMITTED text rather than any internal register, so a group that
    is built but not written cannot pass. The ``/GRNOD/NODE`` a ``/BCS``
    references is looked up by the id in its data row, which is what the
    starter itself resolves.
    """
    lines = starter.splitlines()
    grnods = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("/GRNOD/NODE/"):
            gid = int(lines[i].rsplit("/", 1)[1])
            ids = []
            for data in lines[i + 2:]:
                if data.startswith("/") or data.startswith("#"):
                    break
                ids.extend(int(t) for t in data.split())
            grnods[gid] = ids
        i += 1
    out = {}
    for i, ln in enumerate(lines):
        if not ln.startswith("/BCS/"):
            continue
        row = lines[i + 3]
        tra, rot = row.split()[0], row.split()[1]
        gid = int(row.split()[-1])
        out[(tra, rot)] = grnods.get(gid, [])
    return out


# ── A1: *NODE TC/RC -> /GRNOD/NODE + /BCS ────────────────────────────────────

_SHELL_TAIL = [
    "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "plate", _row(1, 1, 1),
    "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]


def _plate(*node_rows) -> str:
    return "\n".join(
        ["*KEYWORD", "*NODE"] + list(node_rows)
        + ["*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)


class TestNodeTcRcToBcs(unittest.TestCase):
    """``*NODE`` card 1 is ``NID X Y Z TC RC`` (Vol I R17 p.35-2/35-3), and the
    codes are the ``*BOUNDARY_SPC`` triples in the GLOBAL system: 0 none, 1 x,
    2 y, 3 z, 4 x+y, 5 y+z, 6 z+x, 7 x+y+z.

    The decode is not asserted from the manual alone. It reproduces LS-DYNA's
    OWN ``nodal spc summary on *NODE cards`` d3hsp echo on 162 139 nodes across
    155 R14 reference decks with zero translation-code disagreements, and an
    explicit deck's ``nodout`` confirms the constraint holds
    (``intro-by-j.-day/joint/joint-i/revo-stiff``: node 5 states ``TC 7 RC 7``,
    the deck has no ``*BOUNDARY_SPC``, and all six components read exactly
    ``0.00000E+00`` at every sample while the free node 3 moves).
    """

    def test_each_distinct_code_pair_gets_its_own_group(self):
        starter = _convert(_plate(
            _n16c(1, 0.0, 0.0, 0.0, 7, 7),
            _n16c(2, 10.0, 0.0, 0.0, 4, 0),
            _n16c(3, 10.0, 10.0, 0.0, 4, 0),
            _n16(4, 0.0, 10.0, 0.0)))[1]
        groups = _bcs_groups(starter)
        self.assertEqual(groups.get(("111", "111")), [1])
        self.assertEqual(groups.get(("110", "000")), [2, 3])

    def test_every_code_maps_to_the_manuals_own_triple(self):
        """0-7 on TC and on RC, one node each, checked against the table Vol I
        p.35-2 prints (and LS-DYNA's own echo reproduces)."""
        expect = {0: "000", 1: "100", 2: "010", 3: "001",
                  4: "110", 5: "011", 6: "101", 7: "111"}
        rows = []
        for code in range(1, 8):
            rows.append(_n16c(code, float(code), 0.0, 0.0, code, 0))
            rows.append(_n16c(10 + code, float(code), 1.0, 0.0, 0, code))
        deck = "\n".join(["*KEYWORD", "*NODE"] + rows
                         + ["*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)]
                         + _SHELL_TAIL)
        groups = _bcs_groups(_convert(deck)[1])
        for code in range(1, 8):
            with self.subTest(code=code):
                self.assertEqual(groups.get((expect[code], "000")), [code])
                self.assertEqual(groups.get(("000", expect[code])), [10 + code])

    def test_the_group_ids_come_from_the_guarded_allocator(self):
        """Every synthesized /GRNOD goes through ``state.next_grnod_id()`` (the
        #131 rule): a user ``*SET_NODE`` re-emitted verbatim at or above the
        90001 auto base collides otherwise, and that is starter ERROR 79 /
        IN NODE GROUP DEFINITION with no restart file. The probe puts a user
        set exactly on the id the allocator would hand out first."""
        deck = "\n".join(
            ["*KEYWORD", "*NODE",
             _n16c(1, 0.0, 0.0, 0.0, 7, 7),
             _n16(2, 10.0, 0.0, 0.0), _n16(3, 10.0, 10.0, 0.0),
             _n16(4, 0.0, 10.0, 0.0),
             "*SET_NODE_LIST", _row(90001), _row(2, 3),
             "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)
        starter = _convert(deck)[1]
        ids = [int(ln.rsplit("/", 1)[1]) for ln in _headers(starter, "/GRNOD/NODE/")]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate /GRNOD id in {ids}")
        self.assertIn(90001, ids)

    def test_the_free_format_layout_is_read_too(self):
        """The comma form keeps an empty field between commas, so
        ``1,0.,0.,0.,,7`` is TC 0 / RC 7 and not TC 7."""
        deck = "\n".join(
            ["*KEYWORD", "*NODE",
             "1,0.0,0.0,0.0,,7", "2,10.0,0.0,0.0,5,0",
             "3,10.0,10.0,0.0", "4,0.0,10.0,0.0",
             "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)
        groups = _bcs_groups(_convert(deck)[1])
        self.assertEqual(groups.get(("000", "111")), [1])
        self.assertEqual(groups.get(("011", "000")), [2])

    def test_real_corpus_rows_are_read_verbatim(self):
        """Three ``*NODE`` rows copied byte-for-byte out of R14 decks, not
        rebuilt by the test's own formatter — a helper that pads the way the
        reader expects only proves it is self-consistent.

        Row 1 is ``component1.k``'s (plain decimals, ``tc 7 rc 0``), rows 2-3
        are ``taylor1.k``'s (``E`` notation with a NEGATIVE first coordinate,
        which is the layout that welded the id to the coordinate under a
        whitespace split and cost 58 303 rows in #132), and row 4 is
        ``control_contact.hemi-draw.k``'s ``tc 6 rc 7``.

        **Format census, stated rather than assumed**: every TC/RC carrier in
        both corpus roots writes this fixed ``(I8, 3E16.0, 2I8)`` layout. The
        ``i10=y`` (``*NODE %``) and ``newformat=long`` (``*NODE +``) variants
        have ZERO occurrences, and neither sigil is handled anywhere in the
        parser — a named non-item, not coverage this batch claims.
        """
        rows = [
            "       1             0.0             0.0             0.0       7       0",
            "       2-1.000000000E+01-1.000000000E+01-7.000000000E+00       7       0",
            "       3-1.000000000E+01 1.000000000E+01-7.000000000E+00       7       0",
            "       4             0.0            10.0             0.0       6       7",
        ]
        state = _dispatch("\n".join(["*KEYWORD", "*NODE"] + rows + ["*END", ""]))
        self.assertEqual(state.node_tc_rc,
                         {1: (7, 0), 2: (7, 0), 3: (7, 0), 4: (6, 7)})
        # The #132 guard: the E-notation rows must keep their own ids and
        # coordinates, not collapse into a phantom node 0.
        self.assertEqual(sorted(state.nodes), [1, 2, 3, 4])
        self.assertEqual((state.nodes[2].x, state.nodes[2].y, state.nodes[2].z),
                         (-10.0, -10.0, -7.0))

    def test_a_deck_without_the_cells_emits_no_block(self):
        starter = _convert(_plate(
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 10.0, 0.0, 0.0),
            _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)))[1]
        self.assertNotIn("*NODE TC/RC", starter)
        self.assertEqual(_headers(starter, "/BCS/"), [])

    def test_an_out_of_range_code_is_named_and_not_guessed(self):
        """Vol I gives both cells exactly eight values. There is no mask for a
        ninth, and clamping one would pin DOFs the deck never asked for."""
        res, starter = _convert(_plate(
            _n16c(1, 0.0, 0.0, 0.0, 9, 0),
            _n16(2, 10.0, 0.0, 0.0), _n16(3, 10.0, 10.0, 0.0),
            _n16(4, 0.0, 10.0, 0.0)))
        self.assertEqual(len(_warns(res, "eight legal values")), 1)
        self.assertEqual(_headers(starter, "/BCS/"), [])


class TestNodeTcRcOptOut(unittest.TestCase):
    """``--no-node-tc-rc-bcs`` / ``convert(node_tc_rc_bcs=False)``."""

    DECK = _plate(_n16c(1, 0.0, 0.0, 0.0, 7, 7),
                  _n16(2, 10.0, 0.0, 0.0), _n16(3, 10.0, 10.0, 0.0),
                  _n16(4, 0.0, 10.0, 0.0))

    def test_off_emits_nothing_and_says_the_dofs_are_free(self):
        res, starter = _convert(self.DECK, node_tc_rc_bcs=False)
        self.assertEqual(_headers(starter, "/BCS/"), [])
        w = _warns(res, "are FREE in the converted model")
        self.assertEqual(len(w), 1)
        self.assertIn("--no-node-tc-rc-bcs", w[0])

    def test_on_is_the_default(self):
        res, starter = _convert(self.DECK)
        self.assertEqual(_bcs_groups(starter).get(("111", "111")), [1])
        self.assertEqual(_warns(res, "are FREE in the converted model"), [])

    def test_the_cli_flag_exists_and_defaults_on(self):
        from k2rad import cli
        args = cli.build_parser().parse_args(["deck.k"])
        self.assertTrue(args.node_tc_rc_bcs)
        args = cli.build_parser().parse_args(["deck.k", "--no-node-tc-rc-bcs"])
        self.assertFalse(args.node_tc_rc_bcs)

    def test_the_help_renders_and_names_the_flag(self):
        """The #135 rule: a bare ``%`` in an argparse help string kills
        ``--help``, and this batch's help quotes measured percentages."""
        from k2rad import cli
        text = cli.build_parser().format_help()
        self.assertIn("--no-node-tc-rc-bcs", text)

    def test_the_gui_mirrors_the_flag(self):
        """Every opt-out has a GUI checkbox and a summary line; a flag wired
        into the CLI only is invisible to half the users."""
        import inspect
        import k2rad_gui
        src = inspect.getsource(k2rad_gui)
        self.assertIn("self.node_tc_rc_bcs = tk.BooleanVar(value=True)", src)
        self.assertIn("variable=self.node_tc_rc_bcs", src)
        self.assertIn("node_tc_rc_bcs=self.node_tc_rc_bcs.get()", src)
        self.assertIn('kwargs["node_tc_rc_bcs"] = bool(node_tc_rc_bcs)', src)
        self.assertIn("(--no-node-tc-rc-bcs)", src)


class TestNodeTcRcScreeningRigidBodies(unittest.TestCase):
    """Rule (a): a node belonging to a rigid body is DROPPED, not re-pointed.

    Vol I R17 p.35-3 Remark 1, verbatim: *"No attempt should be made to apply
    boundary conditions to nodes belonging to rigid bodies (see \\*MAT_RIGID for
    application of rigid body constraints)."* LS-DYNA says the same in its own
    listing — ``ex_16_thin_shell_elform_13.d3hsp`` prints ``*** Warning 60257
    (IMP+257) skipping spc on rigid body node 1003 / tcode = 6 rcode = 7`` for
    cells that live in that deck's ``*NODE`` columns 57-72.

    And a ``/BCS`` there is inert in OpenRadioss: ``resol.F:7073`` runs
    ``BCS10`` (which zeroes V and A on the coded DOFs) but ``resol.F:7572``
    then runs ``RBYVIT`` -> ``rgbodv.F:150-155``, which rebuilds every
    secondary node's acceleration from the body's own velocity field. MEASURED
    on a three-arm twin — a ``*MAT_RIGID`` brick falling under
    ``*LOAD_BODY_Z`` — ``/BCS 111 111`` on the member nodes gives K-ENERGY
    0.3720E-03 at t = 9.955E-04, identical to the no-``/BCS`` control and to
    the closed form 1/2 m v^2; re-pointing the same constraint onto the body's
    main node gives 0.000, i.e. holds a body both solvers let fall.
    """

    DECK = "\n".join([
        "*KEYWORD", "*NODE",
        _n16c(1, 0.0, 0.0, 0.0, 7, 7),
        _n16c(2, 10.0, 0.0, 0.0, 7, 7),
        _n16c(3, 10.0, 10.0, 0.0, 7, 7),
        _n16c(4, 0.0, 10.0, 0.0, 7, 7),
        _n16c(5, 0.0, 0.0, 10.0, 4, 0),
        _n16(6, 10.0, 0.0, 10.0), _n16(7, 10.0, 10.0, 10.0),
        _n16(8, 0.0, 10.0, 10.0),
        "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4), _row(2, 2, 5, 6, 7, 8),
        "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
        "*MAT_RIGID", _row(1, "7.85E-9", "2.1E5", "0.3"),
        _row("0.0", "7", "7"), _row("0.0", "0.0", "0.0"),
        "*MAT_ELASTIC", _row(2, "7.85E-9", "2.1E5", "0.3"),
        "*PART", "rigid_tool", _row(1, 1, 1),
        "*PART", "blank", _row(2, 1, 2),
        "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])

    def test_the_rigid_nodes_are_dropped_and_the_deformable_one_is_kept(self):
        res, starter = _convert(self.DECK)
        groups = _bcs_groups(starter)
        # Node 5 is the only TC/RC node on the deformable part.
        self.assertEqual(groups.get(("110", "000")), [5])
        for nids in groups.values():
            self.assertNotIn(1, nids)
            self.assertNotIn(4, nids)
        w = _warns(res, "belong to a rigid body and were DROPPED")
        self.assertEqual(len(w), 1)
        self.assertIn("4 node(s)", w[0])

    def test_the_message_carries_the_rule_its_own_evidence(self):
        res, _starter = _convert(self.DECK)
        w = _warns(res, "belong to a rigid body and were DROPPED")[0]
        self.assertIn("p.35-3 Remark 1", w)
        self.assertIn("Warning 60257", w)
        self.assertIn("rgbodv.F:150-155", w)
        self.assertIn("*MAT_RIGID CMO/CON1/CON2", w)


class TestNodeTcRcScreeningPrescribedMotion(unittest.TestCase):
    """Rule (b): a DOF an imposed motion already drives is left to it.

    MEASURED on a one-brick twin (bottom face ``/BCS 111 111``, top face driven
    by ``/IMPVEL X`` at 100 mm/s): with a ``/BCS 100 000`` on the SAME top face
    the starter reports WARNING 312 and the engine reports EXT-WORK 13.66
    against an I-ENERGY of 1688 — a 99.9 % energy error on every cycle, because
    ``fixvel.F`` forms its work increment from a V and an AOLD that ``BCS10``
    has already zeroed. The complementary split (``/BCS 011 111`` beside the
    same ``/IMPVEL X``) measures EXT-WORK = I-ENERGY = 4002, 0.0 %, and no
    warning. That control is what makes this a SPLIT rather than a drop: the
    node's other five DOFs stay pinned.
    """

    def _deck(self, dof: int) -> str:
        return "\n".join([
            "*KEYWORD", "*NODE",
            _n16c(1, 0.0, 0.0, 0.0, 7, 7),
            _n16c(2, 10.0, 0.0, 0.0, 7, 7),
            _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0),
            "*SET_NODE_LIST", _row(10), _row(2),
            "*DEFINE_CURVE", _row(1), _row16("0.0", "0.0"),
            _row16("1.0", "1.0"),
            "*BOUNDARY_PRESCRIBED_MOTION_SET",
            _row(10, dof, 0, 1, "1.0"),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)

    def test_the_driven_dof_is_cleared_and_the_rest_stay_pinned(self):
        res, starter = _convert(self._deck(1))       # dof 1 = global x
        groups = _bcs_groups(starter)
        self.assertEqual(groups.get(("111", "111")), [1])
        self.assertEqual(groups.get(("011", "111")), [2])
        w = _warns(res, "already driven by a *BOUNDARY_PRESCRIBED_MOTION")
        self.assertEqual(len(w), 1)
        self.assertIn("1 DOF(s) on 1 node(s)", w[0])

    def test_a_rotational_drive_clears_a_rotational_bit_only(self):
        res, starter = _convert(self._deck(6))       # dof 6 = rotation about y
        groups = _bcs_groups(starter)
        self.assertEqual(groups.get(("111", "101")), [2])
        self.assertEqual(len(
            _warns(res, "already driven by a *BOUNDARY_PRESCRIBED_MOTION")), 1)

    def test_an_undriven_node_keeps_every_bit(self):
        """The control: the same deck with the motion on a node that has no
        TC/RC cell must leave both TC/RC nodes fully pinned."""
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            _n16c(1, 0.0, 0.0, 0.0, 7, 7),
            _n16c(2, 10.0, 0.0, 0.0, 7, 7),
            _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0),
            "*SET_NODE_LIST", _row(10), _row(3),
            "*DEFINE_CURVE", _row(1), _row16("0.0", "0.0"),
            _row16("1.0", "1.0"),
            "*BOUNDARY_PRESCRIBED_MOTION_SET", _row(10, 1, 0, 1, "1.0"),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)
        res, starter = _convert(deck)
        self.assertEqual(_bcs_groups(starter).get(("111", "111")), [1, 2])
        self.assertEqual(
            _warns(res, "already driven by a *BOUNDARY_PRESCRIBED_MOTION"), [])


class TestNodeTcRcScreeningBoundarySpc(unittest.TestCase):
    """Rule (c): a DOF a ``*BOUNDARY_SPC`` already states is merged, not
    restated.

    ``hm_read_bcs.F:198`` unions the codes (``ICODE(NOSYS) = MY_OR(IC,
    ICODE(NOSYS))``), so a second ``/BCS`` changes no physics — but
    ``kinset``/``kinchk`` still count it, and a coupon with two identical
    ``/BCS`` on one ``/GRNOD`` measures 1 x starter WARNING 312 / 8
    INCOMPATIBLE KINEMATIC CONDITIONS. All 16 overlap decks on the R14 roster
    are exact duplication (``ex_12_solid_elform_1``: 32 nodes ``TC 3`` and a
    ``*BOUNDARY_SPC_SET dofz = 1`` on the same 32).
    """

    def _deck(self, dofs, cid=0) -> str:
        return "\n".join([
            "*KEYWORD", "*NODE",
            _n16c(1, 0.0, 0.0, 0.0, 7, 7),
            _n16(2, 10.0, 0.0, 0.0), _n16(3, 10.0, 10.0, 0.0),
            _n16(4, 0.0, 10.0, 0.0),
            "*SET_NODE_LIST", _row(10), _row(1),
            "*BOUNDARY_SPC_SET", _row(10, cid, *dofs),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)

    def test_a_duplicated_dof_is_not_restated(self):
        res, starter = _convert(self._deck((1, 1, 1, 0, 0, 0)))
        groups = _bcs_groups(starter)
        # The *BOUNDARY_SPC already pins all three translations; only the
        # rotations are left for the TC/RC pass.
        self.assertEqual(groups.get(("000", "111")), [1])
        self.assertIsNone(groups.get(("111", "111")))
        w = _warns(res, "merged rather than restated")
        self.assertEqual(len(w), 1)
        self.assertIn("3 DOF(s) on 1 node(s)", w[0])
        self.assertIn("hm_read_bcs.F:198", w[0])

    def test_a_fully_duplicated_node_gets_no_second_bcs(self):
        res, starter = _convert(self._deck((1, 1, 1, 1, 1, 1)))
        self.assertNotIn("*NODE TC/RC", starter)
        self.assertEqual(len(_warns(res, "had every stated DOF removed")), 1)

    def test_a_disjoint_spc_leaves_the_tc_rc_bits_alone(self):
        """The control: an SPC that pins only z must not cancel x or y."""
        _res, starter = _convert(self._deck((0, 0, 1, 0, 0, 0)))
        self.assertEqual(_bcs_groups(starter).get(("110", "111")), [1])


class TestNodeTcRcRotationalCodesAreNamed(unittest.TestCase):
    """Rule (d): a rotational code on a mesh with no rotational DOF is EMITTED
    and named, not dropped.

    ``bcs10.F:66`` applies the Rot digits only inside ``IF(IRODDL/=0)``, so on
    a solid-only model they are inert — and LS-DYNA drops them too: 71 885
    ``*NODE`` rotational codes across 22 solid/ALE R14 decks are stated in the
    deck and absent from its ``nodal spc summary`` echo
    (``control_energy.bar-impact``'s 864 ``TC 0 / RC 7`` nodes produce no echo
    row at all). Emitting them costs nothing on either side; predicting
    ``IRODDL`` in order to drop them would cost a guess.
    """

    SOLID = "\n".join([
        "*KEYWORD", "*NODE",
        _n16c(1, 0.0, 0.0, 0.0, 5, 7), _n16c(2, 1.0, 0.0, 0.0, 5, 7),
        _n16c(3, 1.0, 1.0, 0.0, 5, 7), _n16c(4, 0.0, 1.0, 0.0, 5, 7),
        _n16(5, 0.0, 0.0, 1.0), _n16(6, 1.0, 0.0, 1.0),
        _n16(7, 1.0, 1.0, 1.0), _n16(8, 0.0, 1.0, 1.0),
        "*ELEMENT_SOLID", _row(1, 1), _row(1, 2, 3, 4, 5, 6, 7, 8),
        "*SECTION_SOLID", _row(1, 1),
        "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
        "*PART", "block", _row(1, 1, 1),
        "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])

    def test_the_rotational_code_is_emitted_and_reported_inert(self):
        res, starter = _convert(self.SOLID)
        self.assertEqual(_bcs_groups(starter).get(("011", "111")), [1, 2, 3, 4])
        w = _warns(res, "rotational code on a mesh with no shell")
        self.assertEqual(len(w), 1)
        self.assertIn("bcs10.F:66", w[0])
        self.assertIn("4 node(s)", w[0])

    def test_a_shell_mesh_does_not_get_the_note(self):
        res, _starter = _convert(_plate(
            _n16c(1, 0.0, 0.0, 0.0, 5, 7),
            _n16(2, 10.0, 0.0, 0.0), _n16(3, 10.0, 10.0, 0.0),
            _n16(4, 0.0, 10.0, 0.0)))
        self.assertEqual(_warns(res, "rotational code on a mesh with no shell"), [])


class TestNodeTcRcAndTheFreeNodeGuard(unittest.TestCase):
    """Rule (e): the implicit free-node guard subtracts a node the TC/RC pass
    has ALREADY pinned in all six DOFs, and keeps every other one.

    The guard's mask is ``111 111``, i.e. the SUPERSET of any TC/RC code, so it
    can only drop the exact-match case: a free node the TC/RC pass pinned
    partially must still reach it or its remaining DOFs stay zero rows in the
    implicit tangent (the #120 failure with the sign reversed). Two ``/BCS`` on
    one node are starter WARNING 312, measured.
    """

    def _deck(self, tc: int, rc: int) -> str:
        return "\n".join([
            "*KEYWORD", "*NODE",
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 10.0, 0.0, 0.0),
            _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0),
            _n16c(99, 50.0, 50.0, 50.0, tc, rc),       # attached to nothing
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4),
            "*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1")] + _SHELL_TAIL)

    def test_a_fully_pinned_free_node_is_not_pinned_twice(self):
        _res, starter = _convert(self._deck(7, 7))
        pinning = [nids for key, nids in _bcs_groups(starter).items()
                   if 99 in nids]
        self.assertEqual(len(pinning), 1, f"node 99 pinned {len(pinning)} times")

    def test_a_partially_pinned_free_node_still_reaches_the_guard(self):
        _res, starter = _convert(self._deck(1, 0))
        groups = _bcs_groups(starter)
        self.assertIn(99, groups.get(("100", "000"), []))
        guard = [nids for key, nids in groups.items()
                 if key == ("111", "111") and 99 in nids]
        self.assertTrue(guard, "the free-node guard must still pin node 99")


class TestModalChainNeedsNoTcRcArm(unittest.TestCase):
    """A2, and it is a MEASURED verdict rather than an omission.

    ``tools/modal_solve.py`` builds the mass matrix on the DOFs of the
    stiffness matrix the ENGINE exported (``/IMPL/PRINT/STIF``) from the
    CONVERTED ``.rad`` — its own docstring says "Only free (unconstrained,
    non-rigid-slaved) DOFs appear" — so a DOF this pass pins simply has no row
    by the time ``build_mass_diagonal`` runs. Neither ``modal_common`` nor
    ``modal_solve`` reads ``*BOUNDARY_SPC`` either, for the same reason. The
    modal chain therefore inherits item A through the emitted deck, and adding
    a second TC/RC reader in ``tools/`` would be a second source of truth for
    a constraint the first one already applied.

    What this test pins is the property the verdict rests on: the constraint
    reaches the ``.rad`` on a MODAL deck too, so the exported stiffness matrix
    is the supported one.
    """

    def test_a_modal_deck_still_gets_the_tc_rc_constraint(self):
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            _n16c(1, 0.0, 0.0, 0.0, 7, 7), _n16c(2, 10.0, 0.0, 0.0, 7, 7),
            _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0),
            "*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1"),
            "*CONTROL_IMPLICIT_EIGENVALUE", _row(3),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4)] + _SHELL_TAIL)
        state, starter = _state_and_starter(deck)
        self.assertTrue(state.is_modal)
        self.assertEqual(_bcs_groups(starter).get(("111", "111")), [1, 2])

    def test_tools_do_not_reimplement_the_reader(self):
        """A second TC/RC reader in ``tools/`` would be a second source of
        truth. If one is ever added, this test is the place that says why the
        first one was enough."""
        import inspect
        from tools import modal_common
        self.assertNotIn("node_tc_rc", inspect.getsource(modal_common))


# ── A3: starter ERROR 611 ────────────────────────────────────────────────────

class TestImplicitStabilizationStubInacti(unittest.TestCase):
    """The synthesized ``auto_implicit_stabilization_self_contact`` takes
    ``Inacti = 1``.

    ``i7pwr3.F:113-114`` computes ``DN = |N|^2`` for the vector from the
    projection point on a main sub-triangle to the secondary node; ``DN <=
    1e-30`` means the node lies EXACTLY on the segment, so there is no
    direction to depenetrate it along. ``:118`` then refuses the deck —
    ``IF(INACTI/=1.AND.INACTI/=2.AND.FPENMAX==ZERO)`` -> ``ANCMSG(MSGID=611)``
    — so Inacti 5 AND 6 both fail and only 1/2 (or a non-zero Fpenmax) pass.

    MEASURED: ``thermal/welding-new/welding-solids/05_1_welding_solid``, whose
    conformal weld mesh puts 310 secondary nodes exactly on the stub's own
    surface, goes from 310 starter ERRORS to 0 ERRORS / 1 WARNING.

    Inacti = 1 is also what the stub already claimed to be: "it carries no load
    unless parts actually touch" — a node that already touches gets zero
    stiffness rather than a t = 0 pre-load.
    """

    IMPLICIT_SOLID = "\n".join([
        "*KEYWORD", "*NODE",
        _n16(1, 0.0, 0.0, 0.0), _n16(2, 1.0, 0.0, 0.0),
        _n16(3, 1.0, 1.0, 0.0), _n16(4, 0.0, 1.0, 0.0),
        _n16(5, 0.0, 0.0, 1.0), _n16(6, 1.0, 0.0, 1.0),
        _n16(7, 1.0, 1.0, 1.0), _n16(8, 0.0, 1.0, 1.0),
        "*ELEMENT_SOLID", _row(1, 1), _row(1, 2, 3, 4, 5, 6, 7, 8),
        "*SECTION_SOLID", _row(1, 1),
        "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
        "*PART", "block", _row(1, 1, 1),
        "*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1"),
        "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])

    def _stub_rows(self, starter: str):
        body = _block(starter, "/INTER/TYPE7/90001")
        self.assertIsNotNone(body, "no stabilization stub emitted")
        return [ln for ln in body if not ln.startswith("#")]

    def test_the_stub_carries_inacti_1(self):
        res, starter = _convert(self.IMPLICIT_SOLID)
        rows = self._stub_rows(starter)
        # The IBC / Inacti / VisS / VisF / Bumult row is the 6th data row.
        ibc_row = [r for r in rows if r.strip().startswith("000")][0]
        self.assertEqual(int(ibc_row.split()[1]), 1)
        self.assertEqual(len(_warns(res, "with Inacti=1")), 1)

    def test_the_stub_warning_carries_the_starter_line_and_the_measurement(self):
        res, _starter = _convert(self.IMPLICIT_SOLID)
        w = _warns(res, "with Inacti=1")[0]
        self.assertIn("i7pwr3.F:114-129", w)
        self.assertIn("ERROR 611", w)
        self.assertIn("05_1_welding_solid", w)

    def test_the_stub_gets_no_fpenmax(self):
        """Inacti 1 is exempt at the gate itself, so the Fpenmax fallback is
        neither needed nor written — the field stays at the starter default."""
        _res, starter = _convert(self.IMPLICIT_SOLID)
        rows = self._stub_rows(starter)
        # rows[0] is the title; rows[2] is the Fscalegap / GAP_MAX / Fpenmax row.
        self.assertEqual(rows[2].split(), ["0", "0", "0"])


class TestType7FpenmaxFallback(unittest.TestCase):
    """A USER contact keeps its faithful ``Inacti`` and gains an ``Fpenmax``.

    ``4.3_General_Nonlinearity`` states ``IGNORE = 1`` on its own ``*CONTACT``
    card, which ``_ignore_to_inacti`` maps to ``Inacti = 5`` — a faithful
    translation, not a k2rad default and not ``--deformable-contact-recipe``.
    Flipping it would throw away the W13 evidence that Inacti 5 is right for an
    initially-resting contact. Fpenmax instead turns the REFUSAL into a
    deactivation of exactly the nodes that cannot be depenetrated:
    ``i7pwr3.F:193-195`` zeroes ``STFN`` when ``PENE > Fpenmax*GAPV``, and
    ``PENE = GAPV - d``, so at 0.99 only ``d < 0.01*GAPV`` is affected.

    It is a STARTER-only field (``hm_read_inter_type07.F:275`` ->
    ``FRIGAP(27)``; the engine's only ``VARIABLES(27)`` use is
    ``i21main_tri.F``, i.e. TYPE21) and MEASURED inert on two control decks
    whose decoded ``T01`` channels are byte-identical with and without it.
    """

    def _deck(self, ignore: int) -> str:
        return "\n".join([
            "*KEYWORD", "*NODE",
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 1.0, 0.0, 0.0),
            _n16(3, 1.0, 1.0, 0.0), _n16(4, 0.0, 1.0, 0.0),
            _n16(5, 0.0, 0.0, 2.0), _n16(6, 1.0, 0.0, 2.0),
            _n16(7, 1.0, 1.0, 2.0), _n16(8, 0.0, 1.0, 2.0),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4), _row(2, 2, 5, 6, 7, 8),
            "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*PART", "a", _row(1, 1, 1),
            "*PART", "b", _row(2, 1, 1),
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
            _row(1, 2, 3, 3), _row("0.1", "0.1"), _row(),
            _row(0, 0, 0, ignore),
            "*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])

    def _fpenmax_row(self, starter: str, inter_id: int):
        body = _block(starter, f"/INTER/TYPE7/{inter_id}")
        self.assertIsNotNone(body, "no /INTER/TYPE7 emitted")
        # [0] title, [1] Slav/Mast, [2] Fscalegap / GAP_MAX / Fpenmax.
        return [ln for ln in body if not ln.startswith("#")][2].split()

    def test_inacti_5_gains_the_fpenmax(self):
        res, starter = _convert(self._deck(1))
        ids = [int(ln.rsplit("/", 1)[1]) for ln in _headers(starter, "/INTER/TYPE7/")]
        self.assertEqual(self._fpenmax_row(starter, ids[0]),
                         ["0", "0", "0.99"])
        w = _warns(res, "Fpenmax=0.99")
        self.assertEqual(len(w), 1)
        self.assertIn("i7pwr3.F:114-129", w[0])
        self.assertIn("ERROR 611", w[0])

    def test_the_faithful_inacti_is_not_changed(self):
        """``IGNORE = 1`` still maps to Inacti 5 — the fallback is additive."""
        _res, starter = _convert(self._deck(1))
        ids = [int(ln.rsplit("/", 1)[1]) for ln in _headers(starter, "/INTER/TYPE7/")]
        body = _block(starter, f"/INTER/TYPE7/{ids[0]}")
        rows = [ln for ln in body if not ln.startswith("#")]
        ibc_row = [r for r in rows if r.strip().startswith("000")][0]
        self.assertEqual(int(ibc_row.split()[1]), 5)

    def test_an_explicit_deck_with_no_type7_is_untouched(self):
        """The control that keeps the blast radius honest: an explicit
        single-surface contact converts to /INTER/TYPE25, which
        ``i7pwr3.F``/``i20pwr3.F`` never reach (a grep of the whole starter
        finds MSGID 611/612 in those two files only), so no Fpenmax is
        written there."""
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 10.0, 0.0, 0.0),
            _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4),
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE",
            _row(0, 0, 5, 5), _row("0.1", "0.1")] + _SHELL_TAIL)
        res, starter = _convert(deck)
        self.assertTrue(_headers(starter, "/INTER/TYPE25/"))
        self.assertEqual(_headers(starter, "/INTER/TYPE7/"), [])
        self.assertEqual(_warns(res, "Fpenmax="), [])


if __name__ == "__main__":                             # pragma: no cover
    unittest.main()
