"""Tests for the gravity conversions:

  *LOAD_GRAVITY_PART[_SET]   -> /GRAV
  *LOAD_BODY_{X,Y,Z}         -> /GRAV  (Fscale_Y = -SF)
  *LOAD_BODY_PARTS           -> the part-set scope of the above

Three things decide whether a converted gravity deck is right, and none is
visible by eye in the .rad:

* the SIGN. A base acceleration accelerates the coordinate system, so the
  inertial load on the model is of opposite sign — LS-DYNA Manual Vol I R16
  p.33-27/33-28, whose own *LOAD_BODY_Z example is annotated "Note: Positive
  body load acts in the negative direction." The Radioss dyna-reader negates
  both keywords (``convertloads.cxx:247`` and ``:859``). That file is not part
  of this repo, but reading the same ``.k`` straight into ``starter_win64.exe``
  reproduces it: ``SF = +9810`` echoes ``SCALE_Y = -9810`` and ``SF = -9810``
  echoes ``SCALE_Y = +9810``.
* the MAGNITUDE. *LOAD_GRAVITY_PART's load is ACCEL x factor(t): LC "defines
  factor as a function of time" and ACCEL "will be multiplied by factor from
  curve" (p.33-57), so a curve does not replace ACCEL.
* the /GRNOD. /GRAV adds an ACCELERATION to every node in its group
  (``gravit.F:147``), and ``resol.F`` runs GRAVIT (6884) after RBYFOR (5502)
  has already summed the rigid secondaries into the main node, and before
  RBYVIT/``rgbodv.F`` (7572) OVERWRITES the secondaries' acceleration from the
  main. Gravity landing on a rigid secondary node is therefore worth exactly
  nothing, and with the default --rigid-cog-master the main node is a
  synthesized element-free node that no /GRNOD/PART can ever contain. Measured
  on a free rigid block: as converted the block never moved (526 cycles, all
  displacements 0, KE = 0); with the main node in the group it free-falls
  exactly (DY 4.727803E-01 vs the analytic 4.727802E-01 mm).

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_connectors.py and tests/test_joints.py).
"""

import os
import re
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Deck fragments
#
# Nodes 1-4  = part 1, deformable
#       5-8  = part 2, *MAT_RIGID
#       9-12 = part 3, deformable (the host of the optional CNRB on 9..12)
#      13-16 = part 4, *MAT_RIGID  (only in the two-rigid-body decks)
# ─────────────────────────────────────────────────────────────────────────────

HEAD = """\
*KEYWORD
*TITLE
gravity test deck
*CONTROL_TERMINATION
      0.01
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             2.0             0.0             0.0
       6             3.0             0.0             0.0
       7             3.0             1.0             0.0
       8             2.0             1.0             0.0
       9             5.0             0.0             0.0
      10             6.0             0.0             0.0
      11             6.0             1.0             0.0
      12             5.0             1.0             0.0
      13             8.0             0.0             0.0
      14             9.0             0.0             0.0
      15             9.0             1.0             0.0
      16             8.0             1.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
       3       3       9      10      11      12
*PART
deformable plate
         1         1         1
*PART
rigid block
         2         1         2
*PART
cnrb host plate
         3         1         1
*SECTION_SHELL
         1         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_PLASTIC_KINEMATIC
         1    7850.02.10000E11       0.31.200000E91.10000E10       0.0
*MAT_RIGID
         2    7850.02.10000E11       0.3
       0.0         0         0
"""

# a second *MAT_RIGID part, so a deck can carry two independent rigid bodies
SECOND_RIGID = """\
*ELEMENT_SHELL
       4       4      13      14      15      16
*PART
second rigid block
         4         1         2
"""

CNRB = """\
*SET_NODE_LIST
        50
         9        10        11        12
*CONSTRAINED_NODAL_RIGID_BODY
       900         0        50
"""

# constant +1.0 curve — the shape of the manual's own *LOAD_BODY_Z example
CURVE = """\
*DEFINE_CURVE
         1         0       1.0       1.0
                 0.0                 1.0
                 1.0                 1.0
"""

END = "*END\n"


def _gravity_part(pid, dof=2, lc=0, accel="      9810"):
    return ("*LOAD_GRAVITY_PART\n"
            f"{pid:>10}{dof:>10}{lc:>10}{accel:>10}\n")


def _load_body(axis="Y", lcid=1, sf="       1.0"):
    return f"*LOAD_BODY_{axis}\n{lcid:>10}{sf:>10}\n"


def _convert(deck, **kw):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path, encoding="utf-8") as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _parse(deck):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


# ─────────────────────────────────────────────────────────────────────────────
# .rad readers
# ─────────────────────────────────────────────────────────────────────────────

_GRNOD_RE = re.compile(r"^/GRNOD/(\w+)/(\d+)\s*$")


def _grnods(starter):
    """{group id: (subtype, [entity ids])} for every /GRNOD in the deck."""
    out = {}
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        m = _GRNOD_RE.match(ln)
        if not m:
            continue
        ids = []
        for s in lines[i + 2:]:                 # skip the title line
            if not s or s[0] in "#/":
                break
            ids += [int(t) for t in s.split()]
        out[int(m.group(2))] = (m.group(1), ids)
    return out


def _grav_cards(starter):
    """[(grav_id, data line)] for every /GRAV, in deck order."""
    lines = starter.splitlines()
    return [(int(ln.rsplit("/", 1)[1]), lines[i + 3])
            for i, ln in enumerate(lines) if ln.startswith("/GRAV/")]


def _grav_scope(starter, which=0):
    """(part ids, node ids) the /GRAV's group covers, expanding a union."""
    card = _grav_cards(starter)[which][1]
    gid = int(card[40:50])
    groups = _grnods(starter)
    kind, ids = groups[gid]
    members = list(ids) if kind == "GRNOD" else [gid]
    parts, nodes = set(), set()
    for m in members:
        k, v = groups[m]
        (parts if k == "PART" else nodes).update(v)
    return parts, nodes


def _rbody_mains(starter):
    """Every /RBODY primary node id."""
    lines = starter.splitlines()
    return {int(lines[i + 3][:10]) for i, ln in enumerate(lines)
            if ln.startswith("/RBODY/")}


def _rbody_main_of(starter, title_sub):
    """The primary node of the one /RBODY whose title contains *title_sub*."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/RBODY/") and title_sub in lines[i + 1]:
            return int(lines[i + 3][:10])
    raise AssertionError(f"no /RBODY titled *{title_sub}*")


# ─────────────────────────────────────────────────────────────────────────────
# Sign + card layout
# ─────────────────────────────────────────────────────────────────────────────

class GravitySignTests(unittest.TestCase):
    """Fscale_Y = -SF / -ACCEL, and the /GRAV card's column layout.

    The layout is not cosmetic. grav.cfg's FORMAT(radioss51) card is
    ``%10d%10s%10d%10d%10d          %20lg%20lg`` — TEN literal blank columns
    between grnod_ID and Ascale_x — so the data line is 100 characters with
    Fscale_Y at 81-100. k2rad used to pack the fields with no gap, which read
    back correctly only while the rendered number was <= 10 characters; at 11
    the field boundary cut the minus sign off the front and the starter took
    the value POSITIVE (measured: -0.00980665 echoed as 9.8066500000000E-03).
    Signed Fscale_Y is now the norm on both paths, so the gap has to be there.
    """

    def test_load_body_negates_a_positive_sf(self):
        deck = HEAD + CURVE + _load_body(sf="       1.0") + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[0:10].strip(), "1")          # funct_IDT = LCID
        self.assertEqual(card[10:20].strip(), "Y")         # DIR
        self.assertEqual(card[80:100].strip(), "-1")       # Fscale_Y = -SF

    def test_load_body_negates_a_negative_sf(self):
        deck = HEAD + CURVE + _load_body(sf="      -2.5") + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[80:100].strip(), "2.5")

    def test_gravity_part_negates_accel(self):
        deck = HEAD + _gravity_part(1, dof=3) + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[0:10].strip(), "0")          # constant form
        self.assertEqual(card[10:20].strip(), "Z")
        self.assertEqual(card[80:100].strip(), "-9810")

    def test_gravity_part_curve_form_keeps_accel(self):
        """The load is ACCEL x factor(t), not one or the other: LC "defines
        factor as a function of time" and ACCEL "will be multiplied by factor
        from curve" (Manual p.33-57). Writing Fscale_Y = -1 whenever LC > 0
        dropped ACCEL entirely — a factor-9810 under-load on exactly the ramped
        staged-construction decks the keyword exists for."""
        deck = HEAD + CURVE + _gravity_part(1, lc=1) + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[0:10].strip(), "1")           # fct_IDT = LC
        self.assertEqual(card[80:100].strip(), "-9810")     # ... x ACCEL

    def test_gravity_part_blank_accel_with_a_curve_takes_the_curve(self):
        """ACCEL's own default is 0, so a blank ACCEL beside a curve means the
        curve carries the acceleration. The literal reading (0 x factor) would
        be no load at all, so substitute 1.0 — and say so."""
        deck = HEAD + CURVE + _gravity_part(1, lc=1, accel="       0.0") + END
        result, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[0:10].strip(), "1")
        self.assertEqual(card[80:100].strip(), "-1")
        self.assertTrue(any("taken as ACCEL = 1.0" in w
                            for w in result.warnings))

    def test_card_is_100_columns_with_ascale_at_61_80(self):
        deck = HEAD + _gravity_part(1) + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(len(card), 100)
        self.assertEqual(card[50:60], " " * 10)            # the cfg's gap
        self.assertEqual(card[60:80].strip(), "1")         # Ascale_x

    def test_eleven_character_fscale_keeps_its_sign(self):
        """The regression that made the sign fix worth having: 0.00980665 is
        the routine mm/ms gravity magnitude and renders as 11 characters."""
        deck = HEAD + _gravity_part(1, accel="0.00980665") + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[60:80].strip(), "1")
        self.assertEqual(card[80:100].strip(), "-0.00980665")

    def test_zero_accel_emits_no_grav_at_all(self):
        """Fscale_Y = 0 does NOT mean "no gravity": hm_read_grav.F:190 turns a
        zero into the unit-system factor, i.e. 1.0. So emit nothing."""
        deck = HEAD + _gravity_part(1, accel="       0.0") + END
        result, starter = _convert(deck)
        self.assertNotIn("/GRAV/", starter)
        self.assertTrue(any("ACCEL = 0" in w for w in result.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# The rest of the *LOAD_BODY card: CID and LCIDDR
# ─────────────────────────────────────────────────────────────────────────────

COORD = ("*DEFINE_COORDINATE_SYSTEM\n"
         "         7       0.0       0.0       0.0       0.0       0.0       1.0\n"
         "       1.0       0.0       0.0\n")


class LoadBodyRestOfCardTests(unittest.TestCase):
    """*LOAD_BODY's card is ``LCID SF LCIDDR XC YC ZC CID``. Only LCID and SF
    used to be read; CID and LCIDDR were dropped without a word."""

    def _body_with(self, lciddr=0, cid=0):
        return ("*LOAD_BODY_Y\n"
                f"{1:>10}{'1.0':>10}{lciddr:>10}{'0.0':>10}{'0.0':>10}"
                f"{'0.0':>10}{cid:>10}\n")

    def test_cid_becomes_the_grav_skew(self):
        """"The accelerations (LCID) are with respect to CID" (p.33-27). The
        engine honours /GRAV skew_ID: for ISK > 1 gravit.F:150-162 adds
        SKEW(3*N2-2..3*N2, ISK) * AA instead of the global axis."""
        deck = HEAD + CURVE + COORD + self._body_with(cid=7) + END
        _r, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[20:30].strip(), "7")
        self.assertIn("/SKEW/FIX/7", starter)

    def test_unknown_cid_stays_global_and_warns(self):
        """A /GRAV naming a skew id that is not emitted is MSGID=137, a starter
        ERROR — so an unresolvable CID must fall back to the global axis."""
        deck = HEAD + CURVE + self._body_with(cid=7) + END
        result, starter = _convert(deck)
        card = _grav_cards(starter)[0][1]
        self.assertEqual(card[20:30].strip(), "0")
        self.assertTrue(any("CID=7 not found" in w for w in result.warnings))

    def test_no_cid_keeps_the_skew_column_zero(self):
        deck = HEAD + CURVE + _load_body() + END
        _r, starter = _convert(deck)
        self.assertEqual(_grav_cards(starter)[0][1][20:30].strip(), "0")

    def test_lciddr_is_warned_like_the_gravity_path(self):
        """*LOAD_GRAVITY_PART's LCDR has always been warned about; LCIDDR is
        the same field on the other keyword and was silent."""
        deck = HEAD + CURVE + self._body_with(lciddr=1) + END
        result, _s = _convert(deck)
        self.assertTrue(any("LCIDDR=1" in w and "dynamic-relaxation" in w
                            for w in result.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# Rigid bodies in the /GRAV group
# ─────────────────────────────────────────────────────────────────────────────

class GravityRigidBodyTests(unittest.TestCase):
    """The /RBODY main node has to be in the /GRAV's node group, or the rigid
    body gets no gravity at all."""

    def test_mat_rigid_main_node_is_in_the_group(self):
        deck = HEAD + _gravity_part(1) + _gravity_part(2) + END
        _r, starter = _convert(deck)
        mains = _rbody_mains(starter)
        self.assertEqual(len(mains), 1)
        parts, nodes = _grav_scope(starter)
        self.assertTrue(mains <= nodes)

    def test_rigid_part_is_replaced_by_its_main_not_kept(self):
        """dyna2rad's mapping (convertloads.cxx:887-902): a part that became an
        /RBODY is swapped OUT of the /GRNOD/PART. Leaving the secondaries in
        changes no displacement (rgbodv.F overwrites them) but inflates WFEXT,
        because the starter does not zero secondary masses."""
        deck = HEAD + _gravity_part(1) + _gravity_part(2) + END
        _r, starter = _convert(deck)
        parts, _nodes = _grav_scope(starter)
        self.assertEqual(parts, {1})                       # 2 is the rigid one

    def test_group_is_a_union_of_the_part_and_node_groups(self):
        deck = HEAD + _gravity_part(1) + _gravity_part(2) + END
        _r, starter = _convert(deck)
        gid = int(_grav_cards(starter)[0][1][40:50])
        groups = _grnods(starter)
        self.assertEqual(groups[gid][0], "GRNOD")          # /GRNOD/GRNOD
        kinds = {groups[m][0] for m in groups[gid][1]}
        self.assertEqual(kinds, {"PART", "NODE"})

    def test_scope_of_only_rigid_parts_needs_no_part_group(self):
        deck = HEAD + _gravity_part(2) + END
        _r, starter = _convert(deck)
        gid = int(_grav_cards(starter)[0][1][40:50])
        groups = _grnods(starter)
        self.assertEqual(groups[gid][0], "NODE")
        self.assertEqual(set(groups[gid][1]), _rbody_mains(starter))

    def test_cnrb_main_is_added_and_its_host_part_is_kept(self):
        """A CNRB's secondaries are ordinary nodes of a DEFORMABLE part, so the
        part cannot be swapped out — the main is added on top. Load is not
        doubled: the main carries exactly the summed mass of the secondaries
        whose own contribution the engine discards."""
        deck = HEAD + CNRB + _gravity_part(3) + END
        _r, starter = _convert(deck)
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {3})                       # host part kept
        # only the CNRB's main: the *MAT_RIGID part is out of this load's scope
        self.assertEqual(nodes, {_rbody_main_of(starter, "CNRB_900")})

    def test_cnrb_outside_the_scope_is_not_pulled_in(self):
        deck = HEAD + CNRB + _gravity_part(1) + END
        _r, starter = _convert(deck)
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1})
        self.assertEqual(nodes, set())

    def test_no_rigid_cog_master_lists_the_mesh_node_master(self):
        """With --no-rigid-cog-master the main IS the part's lowest-id mesh
        node, so those decks already worked. The group still names it
        explicitly, so both flag states go down one code path."""
        deck = HEAD + _gravity_part(1) + _gravity_part(2) + END
        _r, starter = _convert(deck, rigid_cog_master=False)
        self.assertEqual(_rbody_mains(starter), {5})       # part 2's node 5
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1})
        self.assertEqual(nodes, {5})

    def test_two_rigid_bodies_both_mains_listed(self):
        deck = (HEAD + SECOND_RIGID + _gravity_part(1) + _gravity_part(2)
                + _gravity_part(4) + END)
        _r, starter = _convert(deck)
        mains = _rbody_mains(starter)
        self.assertEqual(len(mains), 2)
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1})
        self.assertEqual(nodes, mains)

    def test_mat_rigid_and_cnrb_mains_coexist(self):
        deck = (HEAD + CNRB + _gravity_part(1) + _gravity_part(2)
                + _gravity_part(3) + END)
        _r, starter = _convert(deck)
        mains = _rbody_mains(starter)
        self.assertEqual(len(mains), 2)                    # MAT_RIGID + CNRB
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1, 3})
        self.assertEqual(nodes, mains)

    def test_merged_rigid_bodies_dedupe_on_the_main_node(self):
        """*CONSTRAINED_RIGID_BODIES aliases the slave pid's record onto the
        master's, so several pids share one ind_node — dedupe on the node."""
        deck = (HEAD + SECOND_RIGID
                + "*CONSTRAINED_RIGID_BODIES\n         2         4\n"
                + _gravity_part(1) + _gravity_part(2) + _gravity_part(4) + END)
        _r, starter = _convert(deck)
        mains = _rbody_mains(starter)
        self.assertEqual(len(mains), 1)                    # one merged body
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1})
        self.assertEqual(nodes, mains)

    def test_warning_names_the_main_nodes(self):
        deck = HEAD + _gravity_part(1) + _gravity_part(2) + END
        result, _s = _convert(deck)
        self.assertTrue(any("/RBODY main node" in w for w in result.warnings))

    def test_body_load_over_a_rigid_part_gets_the_main(self):
        deck = HEAD + CURVE + _load_body() + END
        _r, starter = _convert(deck)
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1, 3})                    # 2 swapped out
        self.assertEqual(nodes, _rbody_mains(starter))

    def test_body_load_whole_model_takes_every_main(self):
        """*LOAD_BODY without _PARTS is the whole problem (Manual p.33-25), so
        every rigid body's main is in — including a CNRB whose host part
        carries no gravity of its own."""
        deck = HEAD + SECOND_RIGID + CNRB + CURVE + _load_body() + END
        _r, starter = _convert(deck)
        _parts, nodes = _grav_scope(starter)
        self.assertEqual(nodes, _rbody_mains(starter))
        self.assertEqual(len(nodes), 3)


class GravityNoRigidBodyTests(unittest.TestCase):
    """A deck with no rigid body must emit the same /GRNOD cards it always has:
    one /GRNOD/PART per /GRAV, no extra groups, the same titles, and the same
    two ids drawn in the same order. The /GRAV card itself DOES change on every
    gravity deck (the cfg's 10-column gap, and the *LOAD_BODY sign) — this
    class pins the group half of that claim. (The five golden fixtures carry no
    gravity at all, so nothing else pins it.)"""

    NO_RIGID = HEAD.replace(
        "*MAT_RIGID\n         2    7850.02.10000E11       0.3\n"
        "       0.0         0         0\n",
        "*MAT_ELASTIC\n         2    7850.02.10000E11       0.3\n")

    def test_single_part_group_and_consecutive_ids(self):
        deck = self.NO_RIGID + _gravity_part(1) + _gravity_part(2) + END
        _r, starter = _convert(deck)
        self.assertNotIn("/GRNOD/GRNOD/", starter)
        grav_id, card = _grav_cards(starter)[0]
        gid = int(card[40:50])
        groups = _grnods(starter)
        self.assertEqual(groups[gid][0], "PART")
        self.assertEqual(set(groups[gid][1]), {1, 2})
        # the part group is still allocated immediately before the /GRAV
        self.assertEqual(gid + 1, grav_id)

    def test_group_title_is_unchanged(self):
        deck = self.NO_RIGID + _gravity_part(1) + END
        _r, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/PART/"))
        self.assertTrue(lines[i + 1].startswith("gravity_parts_"))

    def test_body_load_group_title_is_unchanged(self):
        deck = self.NO_RIGID + CURVE + _load_body() + END
        _r, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/PART/"))
        self.assertTrue(lines[i + 1].startswith("body_load_allparts_"))
        self.assertNotIn("/GRNOD/GRNOD/", starter)


# ─────────────────────────────────────────────────────────────────────────────
# *LOAD_BODY_PARTS
# ─────────────────────────────────────────────────────────────────────────────

PSET = "*SET_PART_LIST\n        77\n         1         2\n"


class LoadBodyPartsTests(unittest.TestCase):
    """*LOAD_BODY_PARTS restricts EVERY *LOAD_BODY_* to a part set — deck-wide,
    one card per deck, last one wins (Manual Vol I R16 p.33-25; the Radioss
    dyna-reader keeps a single int, convertloads.cxx:167-182). It used to have
    no handler at all, so a scoped deck silently got whole-model gravity."""

    def test_psid_is_parsed_and_not_skipped(self):
        deck = HEAD + PSET + CURVE + "*LOAD_BODY_PARTS\n        77\n" + \
            _load_body() + END
        state = _parse(deck)
        self.assertEqual(state.body_load_psid, 77)
        result, _s = _convert(deck)
        self.assertNotIn("LOAD_BODY_PARTS", result.skipped_keywords)

    def test_scope_is_the_part_set(self):
        deck = HEAD + PSET + CURVE + "*LOAD_BODY_PARTS\n        77\n" + \
            _load_body() + END
        _r, starter = _convert(deck)
        parts, nodes = _grav_scope(starter)
        self.assertEqual(parts, {1})                       # 2 is rigid
        self.assertEqual(nodes, _rbody_mains(starter))     # ... via its main
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/PART/"))
        self.assertTrue(lines[i + 1].startswith("body_load_pset77_"))

    def test_unscoped_deck_still_covers_every_part(self):
        deck = HEAD + CURVE + _load_body() + END
        _r, starter = _convert(deck)
        parts, _nodes = _grav_scope(starter)
        self.assertEqual(parts, {1, 3})

    def test_missing_set_falls_back_to_the_whole_model(self):
        deck = HEAD + CURVE + "*LOAD_BODY_PARTS\n        99\n" + \
            _load_body() + END
        result, starter = _convert(deck)
        parts, _nodes = _grav_scope(starter)
        self.assertEqual(parts, {1, 3})
        self.assertTrue(any("part set 99" in w and "not found" in w
                            for w in result.warnings))

    def test_second_card_wins_and_warns(self):
        deck = (HEAD + PSET + "*SET_PART_LIST\n        78\n         3\n"
                + CURVE + "*LOAD_BODY_PARTS\n        77\n"
                + "*LOAD_BODY_PARTS\n        78\n" + _load_body() + END)
        result, starter = _convert(deck)
        parts, _nodes = _grav_scope(starter)
        self.assertEqual(parts, {3})
        self.assertTrue(any("replaces the earlier PSID 77" in w
                            for w in result.warnings))

    def test_unconsumed_card_is_logged_not_silent(self):
        """A *LOAD_BODY_PARTS with no *LOAD_BODY_* to scope emits nothing. It
        has a handler, so it never reaches skipped_keywords either — without
        the recognized-but-not-emitted channel the log says nothing at all."""
        deck = HEAD + PSET + "*LOAD_BODY_PARTS\n        77\n" + END
        result, starter = _convert(deck)
        self.assertNotIn("/GRAV/", starter)
        self.assertIn("LOAD_BODY_PARTS",
                      [kw for kw, _r in result.recognized_not_emitted])


# ─────────────────────────────────────────────────────────────────────────────
# /GRNOD id namespace
# ─────────────────────────────────────────────────────────────────────────────

class GravityGrnodIdTests(unittest.TestCase):
    """The synthesized gravity groups share the /GRNOD id namespace with the
    user's own *SET_NODE groups, which k2rad re-emits verbatim under their SID
    (_make_extra_groups, and /GRNOD/NODE/<nsid> on the SPC path). A duplicate
    /GRNOD id is not cosmetic: the starter aborts the whole deck with
    ``ERROR ID : 79 ** ERROR: DUPLICATE ID / IN NODE GROUP DEFINITION``."""

    # 90005 and 90006 are exactly the ids the mains group and the union draw on
    # a rigid-body gravity deck, so an unguarded allocator collides on both
    COLLIDING = ("*SET_NODE_LIST\n     90005\n         1         2\n"
                 "*SET_NODE_LIST\n     90006\n         3         4\n")

    def _ids(self, starter):
        return [int(m.group(2)) for m in
                (_GRNOD_RE.match(ln) for ln in starter.splitlines()) if m]

    def test_no_duplicate_ids_with_a_user_set_in_the_auto_range(self):
        deck = HEAD + CURVE + self.COLLIDING + _load_body() + END
        _r, starter = _convert(deck)
        ids = self._ids(starter)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(90005, ids)                          # the user's own
        self.assertIn(90006, ids)

    def test_gravity_part_path_is_guarded_too(self):
        deck = (HEAD + self.COLLIDING + _gravity_part(1) + _gravity_part(2)
                + END)
        _r, starter = _convert(deck)
        ids = self._ids(starter)
        self.assertEqual(len(ids), len(set(ids)))

    def test_guard_is_a_no_op_without_a_colliding_set(self):
        """The guard must not shift ids on an ordinary deck."""
        deck = HEAD + CURVE + _load_body() + END
        _r, starter = _convert(deck)
        grav_id, card = _grav_cards(starter)[0]
        gid = int(card[40:50])
        groups = _grnods(starter)
        self.assertEqual(groups[gid][0], "GRNOD")
        part_gid, mains_gid = groups[gid][1]
        self.assertEqual(part_gid + 1, grav_id)            # unchanged order
        self.assertEqual(grav_id + 1, mains_gid)
        self.assertEqual(mains_gid + 1, gid)


# ─────────────────────────────────────────────────────────────────────────────
# Shared scope, and the honesty warnings
# ─────────────────────────────────────────────────────────────────────────────

class GravityScopeWarningTests(unittest.TestCase):

    def test_three_body_loads_share_one_group_set(self):
        """The *LOAD_BODY_PARTS scope is deck-global, so all three axes take
        the same nodes. Rebuilding the groups per card emitted three identical
        /GRNOD/PART + /GRNOD/NODE + /GRNOD/GRNOD triples."""
        deck = (HEAD + CURVE + _load_body("X") + _load_body("Y")
                + _load_body("Z") + END)
        _r, starter = _convert(deck)
        cards = _grav_cards(starter)
        self.assertEqual(len(cards), 3)
        gids = {int(c[40:50]) for _id, c in cards}
        self.assertEqual(len(gids), 1)
        self.assertEqual(starter.count("/GRNOD/GRNOD/"), 1)
        self.assertEqual([c[10:20].strip() for _id, c in cards],
                         ["X", "Y", "Z"])

    def test_partial_cluster_scope_warns_about_the_upper_bound(self):
        """A rigid body has ONE main node and ONE mass, so it cannot be loaded
        fractionally. A *CONSTRAINED_RIGID_BODIES merge whose partner is out of
        scope therefore accelerates whole at g, where LS-DYNA gives
        g*m_scoped/m_cluster — an upper bound the user has to know about."""
        deck = (HEAD + SECOND_RIGID
                + "*CONSTRAINED_RIGID_BODIES\n         2         4\n"
                + _gravity_part(4) + END)
        result, _s = _convert(deck)
        self.assertTrue(any("only PART of the rigid body" in w
                            for w in result.warnings))

    def test_cnrb_reaching_outside_the_scope_warns(self):
        deck = (HEAD
                + "*SET_NODE_LIST\n        51\n"
                  "         3         4         9        10\n"
                  "*CONSTRAINED_NODAL_RIGID_BODY\n       901         0        51\n"
                + _gravity_part(3) + END)
        result, _s = _convert(deck)
        self.assertTrue(any("only PART of the rigid body" in w
                            for w in result.warnings))

    def test_fully_scoped_cluster_does_not_warn(self):
        deck = (HEAD + SECOND_RIGID
                + "*CONSTRAINED_RIGID_BODIES\n         2         4\n"
                + _gravity_part(2) + _gravity_part(4) + END)
        result, _s = _convert(deck)
        self.assertFalse(any("only PART of the rigid body" in w
                             for w in result.warnings))

    def test_whole_model_body_load_never_warns_about_partial_scope(self):
        deck = HEAD + CNRB + CURVE + _load_body() + END
        result, _s = _convert(deck)
        self.assertFalse(any("only PART of the rigid body" in w
                             for w in result.warnings))

    def test_cnrb_pid_colliding_with_a_rigid_part_is_reported(self):
        """rbody_info merges two id namespaces — *MAT_RIGID records keyed by
        PART id, CNRB records by the CNRB's own PID — so a colliding PID
        silently replaces the part's record. Invalid LS-DYNA input, but it must
        not be silent."""
        deck = (HEAD
                + "*SET_NODE_LIST\n        52\n"
                  "         9        10        11        12\n"
                  "*CONSTRAINED_NODAL_RIGID_BODY\n         2         0        52\n"
                + CURVE + _load_body() + END)
        result, _s = _convert(deck)
        self.assertTrue(any("PID 2 collides" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
