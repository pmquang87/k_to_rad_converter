"""Tests for the R14 CAMPAIGN TRIAGE batch, round 9 — PART A:

  A1  a *CONSTRAINED_NODAL_RIGID_BODY sharing a *MAT_RIGID part's PID: the
      part-keyed cards drive the PART (LS Warning 10177)
      (default ON, --no-rigid-part-pid-precedence)

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_7.py / _8.py
(functions and deck constants only, so no earlier TestCase runs twice).

Every byte-pinning probe deck below was run through the OpenRadioss starter
once (nt 4, C:/Users/pmqua/rcv_r9i_implA_<name>, harvested and deleted); the
named outcome is recorded in the test's docstring.
"""

import hashlib
import unittest

import test_r14_triage_7 as _t7

_row = _t7._row
_convert = _t7._convert
_has = _t7._has


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _blocks(starter: str, prefix: str):
    """``[(header, [body lines])]`` of every block whose header starts with
    *prefix* (comment lines dropped from the body)."""
    lines = starter.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            body = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith("/"):
                if not lines[j].startswith("#"):
                    body.append(lines[j])
                j += 1
            out.append((ln, body))
    return out


def _grnod_by_title(starter: str):
    """``{title: [node ids]}`` over every /GRNOD/NODE block."""
    out = {}
    for head, body in _blocks(starter, "/GRNOD/NODE/"):
        ids = [int(t) for ln in body[1:] for t in ln.split()]
        out[body[0].strip()] = ids
    return out


def _grnod_by_id(starter: str):
    """``{id: (title, [node ids])}`` over every /GRNOD/NODE block."""
    out = {}
    for head, body in _blocks(starter, "/GRNOD/NODE/"):
        gid = int(head.split("/")[3])
        out[gid] = (body[0].strip(),
                    [int(t) for ln in body[1:] for t in ln.split()])
    return out


def _inivel_nodes(starter: str, title_prefix: str):
    """The node ids of every /INIVEL/TRA whose title starts with
    *title_prefix* (Gnod_id = columns 61-70 of the data card), sorted."""
    groups = _grnod_by_id(starter)
    nodes = set()
    for head, body in _blocks(starter, "/INIVEL/TRA/"):
        if body[0].startswith(title_prefix):
            nodes |= set(groups[int(body[1][60:70])][1])
    return sorted(nodes)


def _th_node(starter: str, title: str):
    """The node ids of the /TH/NODE block titled *title* (None if absent)."""
    for head, body in _blocks(starter, "/TH/NODE/"):
        if body and body[0].strip() == title:
            ids = []
            for ln in body[1:]:
                toks = ln.split()
                if toks and all(t.isdigit() for t in toks):
                    ids += [int(t) for t in toks]
            return ids
    return None


# ═════════════════════════════════════════════════════════════════════════════
# A1 — a CNRB sharing a *MAT_RIGID part's PID: the part-keyed cards drive the
#      PART (LS Warning 10177)
# ═════════════════════════════════════════════════════════════════════════════

_W_A1 = "Warning 10177"
_W_A1_OLD = "The CNRB record wins"
# T7:790's substring - in BOTH sentences
_W_CLASH = "collides with the id of a *MAT_RIGID part"


def _a1_probe(extra: str = "", cnrb_pid: int = 1, rigid_card3: str = "",
              cnrb_kw: str = "*CONSTRAINED_NODAL_RIGID_BODY",
              cnrb_tail: str = "", head: str = "") -> str:
    """The part-A spec's A1 consumer probe (SCR/r9/a1/a1_probe.k shape): a
    *MAT_RIGID shell plate (part 1, nodes 1-4; converted main node 9 =
    'rb_indnode_pid1'), a deformable plate (part 2, nodes 5-8) whose nodes
    5 / 6 form a *CONSTRAINED_NODAL_RIGID_BODY of PID *cnrb_pid* (main node
    10 = 'cnrb_indnode_pid1' on the clash), nodes 7 / 8 SPC'd. *extra* adds
    the consumer cards under test."""
    return "\n".join([
        "*KEYWORD",
        "*CONTROL_TERMINATION", _row(1.0e-3),
        "*CONTROL_TIMESTEP", _row(0.0, 0.9),
        "*DATABASE_GLSTAT", _row(1.0e-5),
        "*DATABASE_BNDOUT", _row(1.0e-5),
        "*DATABASE_HISTORY_NODE", _row(1, 5, 7),
        head.rstrip("\n"),
        "*PART", "rigid plate", _row(1, 1, 1),
        "*SECTION_SHELL", _row(1, 2), _row(1.0, 1.0, 1.0, 1.0),
        "*MAT_RIGID", _row(1, 7.85e-9, 2.1e5, 0.3), _row(0.0, 0, 0),
        rigid_card3 or _row(0.0),
        "*PART", "deformable plate", _row(2, 1, 2),
        "*MAT_ELASTIC", _row(2, 7.85e-9, 2.1e5, 0.3),
        "*NODE",
        f"{1:>8}{0.0:>16}{0.0:>16}{0.0:>16}",
        f"{2:>8}{10.0:>16}{0.0:>16}{0.0:>16}",
        f"{3:>8}{10.0:>16}{10.0:>16}{0.0:>16}",
        f"{4:>8}{0.0:>16}{10.0:>16}{0.0:>16}",
        f"{5:>8}{20.0:>16}{0.0:>16}{0.0:>16}",
        f"{6:>8}{30.0:>16}{0.0:>16}{0.0:>16}",
        f"{7:>8}{30.0:>16}{10.0:>16}{0.0:>16}",
        f"{8:>8}{20.0:>16}{10.0:>16}{0.0:>16}",
        "*ELEMENT_SHELL",
        f"{1:>8}{1:>8}{1:>8}{2:>8}{3:>8}{4:>8}",
        f"{2:>8}{2:>8}{5:>8}{6:>8}{7:>8}{8:>8}",
        "*SET_NODE_LIST", _row(9), _row(5, 6),
        cnrb_kw, _row(cnrb_pid, 0, 9) + cnrb_tail,
        "*SET_NODE_LIST", _row(10), _row(7, 8),
        "*BOUNDARY_SPC_SET", _row(10, 0, 1, 1, 1, 1, 1, 1),
        "*DEFINE_CURVE", _row(1),
        f"{0.0:>20}{0.0:>20}", f"{1.0e-3:>20}{1.0:>20}",
        extra.rstrip("\n"),
        "*END", ""])


_PM = "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n" + _row(1, 3, 2, 1, 1.0)


def a1_probe_motion() -> str:
    """(a)'s deck: the displacement-driven rigid motion on PID 1."""
    return _a1_probe(_PM)


def a1_probe_local() -> str:
    """(a')'s deck: a *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL drive on PID 1
    whose *MAT_RIGID states LCO 7, a *DEFINE_COORDINATE_VECTOR with x' along
    the global y."""
    return _a1_probe(
        "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n" + _row(1, 1, 2, 1, 1.0),
        rigid_card3=_row(7.0),
        head="*DEFINE_COORDINATE_VECTOR\n"
             + _row(7, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0))


def a1_probe_deformable_clash() -> str:
    """(f)'s deck: the CNRB takes PID 2 = the ELASTIC part (solidof's
    class) - that part has no /RBODY record, so nothing can clash."""
    return _a1_probe("*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
                     + _row(2, 3, 2, 1, 1.0), cnrb_pid=2)


# the 386444e conversion of a1_probe_motion() (PR10, the pristine checkout):
# the opt-out arm must reproduce it byte for byte
_A1_MOTION_386444E_SHA = "9289858f97878a1257ad27bb7c59cb1290702b13e4a0f00fc158f0e0013db11e"
_A1_DEFORMABLE_386444E_SHA = "f2a3b65b3b82e72ea5313410e782fde7a6e22d010128b5d3ea2c9bf442de5362"


class RigidPartPidPrecedence(unittest.TestCase):
    """A1 (part-A spec A1.7): on a CNRB / *MAT_RIGID PID clash every
    part-keyed consumer addresses the PART's /RBODY main node 9
    ('rb_indnode_pid1'); the CNRB keeps its own /RBODY 10
    ('cnrb_indnode_pid1') under the shadow key -1.

    STARTER RUN (nt 4, C:/Users/pmqua/rcv_r9i_implA_a1p, the bytes of
    a1_probe_motion(), _0000.rad sha256 51e978c2b432...): 0 ERROR / 1
    WARNING (1084); the opt-out bytes (9289858f9787..., = 386444e) the
    same.

    ENGINE RUN - the driven body MOVES (the round-9 lesson; the one engine
    run A1's tests carry, recorded here because a solver test would skip
    on the CI runners and break the Windows skip guard of 15): the same
    deck converted by the branch and run explicit to t 1e-3 (curve 0 -> 1.0
    mm on PID 1 DOF 3), NORMAL TERMINATION in 665 cycles, 4 threads read
    back. Default: the rigid plate's node 1 DZ 0.200245738 / 0.501367152 /
    0.990689397 mm at t 2.00246e-4 / 5.01367e-4 / 9.90689e-4 (the curve
    to 5e-9 mm; the last printed row), the CNRB member node 5 DZ 0 at
    every row. --no-rigid-part-pid-precedence (= the 386444e bytes): node
    1 DZ 0 at every row and node 5 DZ 0.200245708 / 0.50136745 /
    0.990693092 mm - the CNRB is driven, the punch-in-miniature never
    moves (doorbeam's defect).
    """

    def test_a_the_prescribed_motion_and_its_TH_rows_drive_the_part(self):
        res, st, _e = _convert(a1_probe_motion())
        groups = _grnod_by_id(st)
        imp = _blocks(st, "/IMPDISP/")
        self.assertEqual(len(imp), 1)
        grnod = int(imp[0][1][1].split()[4])
        self.assertEqual(groups[grnod], ("rb_indnode_pid1", [9]))
        self.assertEqual(_th_node(st, "TH_reaction"), [9])
        self.assertEqual(_th_node(st, "TH_NODE_BNDOUT"), [9])
        titles = _grnod_by_title(st)
        self.assertEqual(titles["cnrb_indnode_pid1"], [10])
        self.assertIn("/RBODY/10", st.splitlines())
        self.assertIn("/RBODY/9", st.splitlines())
        self.assertTrue(_has(res.warnings, _W_A1, _W_CLASH,
                             "main node 9", "/RBODY 10"))
        self.assertFalse(_has(res.warnings, _W_A1_OLD))

    def test_g_the_opt_out_restores_the_386444e_bytes_and_sentence(self):
        res, st, _e = _convert(a1_probe_motion(),
                               rigid_part_pid_precedence=False)
        self.assertEqual(_sha(st), _A1_MOTION_386444E_SHA)
        self.assertTrue(_has(res.warnings, _W_A1_OLD, _W_CLASH))
        self.assertFalse(_has(res.warnings, _W_A1))
        groups = _grnod_by_id(st)
        imp = _blocks(st, "/IMPDISP/")
        grnod = int(imp[0][1][1].split()[4])
        self.assertEqual(groups[grnod][0], "cnrb_indnode_pid1")

    def test_f_a_deformable_part_clash_never_moves(self):
        """A CNRB PID equal to a DEFORMABLE part's id (solidof's class) has
        no /RBODY record to collide with: both arms write the 386444e
        bytes and neither prints a clash sentence."""
        r_on, st_on, _e = _convert(a1_probe_deformable_clash())
        r_off, st_off, _e = _convert(a1_probe_deformable_clash(),
                                     rigid_part_pid_precedence=False)
        self.assertEqual(_sha(st_on), _sha(st_off))
        self.assertEqual(_sha(st_on), _A1_DEFORMABLE_386444E_SHA)
        for r in (r_on, r_off):
            self.assertFalse(_has(r.warnings, _W_CLASH))

    def test_b_LOAD_RIGID_BODY_loads_the_part(self):
        res, st, _e = _convert(_a1_probe(
            "*LOAD_RIGID_BODY\n" + _row(1, 3, 1, 1.0)))
        groups = _grnod_by_id(st)
        cl = _blocks(st, "/CLOAD/")
        self.assertEqual(len(cl), 1)
        grnod = int(cl[0][1][1].split()[4])
        self.assertEqual(groups[grnod][0], "rb_indnode_pid1")
        _r, st_off, _e = _convert(_a1_probe(
            "*LOAD_RIGID_BODY\n" + _row(1, 3, 1, 1.0)),
            rigid_part_pid_precedence=False)
        g_off = _grnod_by_id(st_off)
        cl_off = _blocks(st_off, "/CLOAD/")
        self.assertEqual(g_off[int(cl_off[0][1][1].split()[4])][0],
                         "cnrb_indnode_pid1")

    def test_c_INITIAL_VELOCITY_RIGID_BODY_starts_the_part(self):
        deck = _a1_probe(
            "*INITIAL_VELOCITY_RIGID_BODY\n" + _row(1, 0.0, 0.0, 10.0))
        for kw, want in (({}, [9]), ({"rigid_part_pid_precedence": False},
                                     [10])):
            with self.subTest(**kw):
                _r, st, _e = _convert(deck, **kw)
                self.assertEqual(_inivel_nodes(st, "InitVelRB_"), want)

    def test_c2_INITIAL_VELOCITY_GENERATION_on_the_part_is_repointed_to_it(
            self):
        deck = _a1_probe(
            "*INITIAL_VELOCITY_GENERATION\n" + _row(1, 2, 0.0, 0.0, 0.0, 10.0)
            + "\n" + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        for kw, want in (({}, [9]), ({"rigid_part_pid_precedence": False},
                                     [1, 2, 3, 4])):
            with self.subTest(**kw):
                _r, st, _e = _convert(deck, **kw)
                groups = _grnod_by_id(st)
                axis = _blocks(st, "/INIVEL/AXIS/")
                self.assertEqual(len(axis), 1)
                gid = int(axis[0][1][1].split()[-1])
                self.assertEqual(groups[gid][1], want)

    def test_c3_the_CNRB_INERTIA_velocity_stays_on_the_CNRB(self):
        """The CNRB's own card-5 velocity is the CNRB's (shadow key -1),
        under both arms."""
        deck = _a1_probe(
            cnrb_kw="*CONSTRAINED_NODAL_RIGID_BODY_INERTIA",
            cnrb_tail="\n" + _row(0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(0.0, 0.0, 10.0, 0.0, 0.0, 0.0))
        for kw in ({}, {"rigid_part_pid_precedence": False}):
            with self.subTest(**kw):
                _r, st, _e = _convert(deck, **kw)
                self.assertEqual(_inivel_nodes(st, "InitVelInertia_"), [10])

    def test_e_gravity_reaches_both_bodies(self):
        """The CNRB's record stays reachable by VALUE: an explicit
        *LOAD_BODY_Z swaps the rigid part 1 for its main 9 AND loads the
        CNRB main 10 (386444e: part 1 stayed in the part group as if it
        were deformable - its record was gone - beside the CNRB main)."""
        body = "*LOAD_BODY_Z\n" + _row(1, 1.0)
        for kw, parts, mains in (({}, [2], [9, 10]),
                                 ({"rigid_part_pid_precedence": False},
                                  [1, 2], [10])):
            with self.subTest(**kw):
                _r, st, _e = _convert(_a1_probe(body), **kw)
                titles = _grnod_by_title(st)
                got_mains = [v for k, v in titles.items()
                             if k.startswith("body_load_rbody_mains_")]
                self.assertEqual(got_mains, [mains])
                got_parts = [
                    [int(t) for ln in b[1:] for t in ln.split()]
                    for _h, b in _blocks(st, "/GRNOD/PART/")
                    if b[0].startswith("body_load_allparts_")]
                self.assertEqual(got_parts, [parts])

    def test_e2_an_SPC_on_a_part_node_is_repointed_onto_the_part_main(self):
        spc = ("*BOUNDARY_SPC_NODE\n" + _row(2, 0, 1, 0, 0, 0, 0, 0))
        _r, st, _e = _convert(_a1_probe(spc))
        _r, st_off, _e = _convert(_a1_probe(spc),
                                  rigid_part_pid_precedence=False)
        bcs_on = _t7._bcs_groups(st)
        bcs_off = _t7._bcs_groups(st_off)
        on_nodes = {n for _c, ids in bcs_on.values() for n in ids}
        off_nodes = {n for _c, ids in bcs_off.values() for n in ids}
        self.assertIn(9, on_nodes)
        self.assertNotIn(2, on_nodes)
        self.assertIn(2, off_nodes)

    def test_i_ELEMENT_MASS_PART_is_carried_once_by_the_part(self):
        em = "*ELEMENT_MASS_PART\n" + _row(1, 0.5)
        _r, st, _e = _convert(_a1_probe(em))
        masses = {}
        for head, body in _blocks(st, "/RBODY/"):
            masses[int(head.split("/")[2])] = float(body[1].split()[4])
        self.assertEqual(masses[9], 0.5)
        self.assertEqual(masses[10], 0.0)

    def test_a2_LOCAL_drive_triad_rides_the_part_in_the_LCO_frame(self):
        """*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL on PID 1 with *MAT_RIGID
        LCO 7 (a *DEFINE_COORDINATE_VECTOR: x' along (0, 1, 0)): the three
        triad helper nodes join 'rb_nodes_pid1' only (one node in two /RBODY
        is refused by the starter) and N1 -> N2 points along the LCO x', not
        the global fallback and not the CNRB's CID 0 (principal) default.
        STARTER RUN (nt 4, C:/Users/pmqua/rcv_r9i_implA_a1loc, _0000.rad
        sha256 6d5ee319505e...): 0 ERROR / 1 WARNING (1084). The
        --no-rigid-part-pid-precedence bytes (= the 386444e merge, where
        both /RBODY producers take the triad): ERROR 3121 twice, 'NODE ID=9
        IS SECONDARY NODE OF 2 RIGID BODIES' (and node 10) + WARNING 312 -
        the 386444e conversion of this deck does not start."""
        deck = a1_probe_local()
        res, st, _e = _convert(deck)
        titles = _grnod_by_title(st)
        helpers = set(titles["rb_nodes_pid1"]) - {1, 2, 3, 4}
        self.assertEqual(len(helpers), 3)
        self.assertFalse(helpers & set(titles["cnrb_nodes_pid1"]))
        coords = {}
        lines = st.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/NODE"):
                j = i + 1
                while j < len(lines) and not lines[j].startswith("/"):
                    t = lines[j].split()
                    if len(t) == 4 and not lines[j].startswith("#"):
                        coords[int(t[0])] = tuple(float(v) for v in t[1:])
                    j += 1
        n1, n2 = sorted(helpers)[:2]
        d = [b - a for a, b in zip(coords[n1], coords[n2])]
        self.assertAlmostEqual(d[0], 0.0, places=9)
        self.assertGreater(d[1], 0.0)
        self.assertAlmostEqual(d[2], 0.0, places=9)
        _r, st_off, _e = _convert(deck, rigid_part_pid_precedence=False)
        t_off = _grnod_by_title(st_off)
        self.assertTrue(set(t_off["cnrb_nodes_pid1"]) - {5, 6})

    def test_h_the_screw_refusal_names_the_shared_PID_under_each_arm(self):
        """The screw still refuses a body whose id a CNRB shares (reach 0);
        only the reason changes with the arm."""
        mod = _t7._screw_synthetic()
        top = mod.TOP_NODE
        plate0 = top - 9 * len(mod.PLATES) + 1
        extra = ("*SET_NODE_LIST\n" + _row(77) + "\n"
                 + _row(plate0, plate0 + 1) + "\n"
                 "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(mod.PART_A, 0, 77))
        deck = mod.build_deck(extra=extra)
        r_on, _s, _e = _convert(deck)
        r_off, _s, _e = _convert(deck, rigid_part_pid_precedence=False)
        self.assertTrue(_has(r_on.warnings, f"shares PID {mod.PART_A} with "
                             "the part (LS Warning 10177)"))
        self.assertFalse(_has(r_on.warnings, "would replace the part's"))
        self.assertTrue(_has(r_off.warnings, f"uses PID {mod.PART_A}, so its "
                             "record would replace the part's"))


if __name__ == "__main__":
    unittest.main()
