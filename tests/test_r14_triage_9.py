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
import re
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
        bytes and neither prints a clash sentence. STARTER RUN (nt 4,
        rcv_r9i_implA_p_a1defo_n4, sha256 f2a3b65b3b82...): 0 ERROR / 1
        WARNING (1084)."""
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


# ═════════════════════════════════════════════════════════════════════════════
# A2 — implicit *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE -> a one-way
#      /INTER/TYPE7, the implicit stub KEPT and friction-faithful
# ═════════════════════════════════════════════════════════════════════════════

_shell_plate = _t7._shell_plate
_IMPL1 = _t7._IMPL1
_STUB_TITLE = "auto_implicit_stabilization_self_contact"
_W_A2 = "implicit deck -> ONE-WAY /INTER/TYPE7/"
_W_A2_STUB = "is KEPT beside the routed contact(s)"
_W_A2_MIX = "state different (or no scalar) friction coefficients"
_W_A2_GAP = "--inter-gapmin 0.05 written on the routed /INTER/TYPE7/78"
_MODAL = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
          "*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(5) + "\n"
          "*CONTROL_TERMINATION\n" + _row(0.01) + "\n")
_EXPLICIT = "*CONTROL_TERMINATION\n" + _row(0.01) + "\n"


def _n2s(kw: str = "*CONTACT_NODES_TO_SURFACE_ID", iid: int = 78,
         card2=(0.1,), card3=(), mpp: bool = False, card4=None) -> str:
    """One node-to-surface contact on the shell plate: the node set 5 (nodes
    1-3) against part 1 (T8's _N2S_78 shape)."""
    out = f"{kw}\n" + _row(iid) + "\n"
    if mpp:
        out += _row(0, 200, 0, 3, 2, 1.0005) + "\n"
    out += _row(5, 1, 4, 3) + "\n" + _row(*card2) + "\n" + _row(*card3) + "\n"
    if card4 is not None:
        out += _row(*card4) + "\n"
    return out


_SET5 = "*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2, 3) + "\n"


def a2_plain_implicit() -> str:
    """(a): T8's _N2S_78 deck - an implicit plate, FS 0.1."""
    return _shell_plate(_IMPL1, _SET5 + _n2s())


def a2_explicit() -> str:
    """(c): the same contact on an explicit deck."""
    return _shell_plate(_EXPLICIT, _SET5 + _n2s())


def a2_bt_dt() -> str:
    """(j): FS 0.2, BT 0.001, DT 0.009 (card 2 cells 7 / 8)."""
    return _shell_plate(_IMPL1, _SET5 + _n2s(
        card2=(0.2, 0.0, 0.0, 0.0, 0.0, 0, 0.001, 0.009)))


def _inter_block(starter: str, head: str):
    """The data lines of the /INTER block whose header is *head*."""
    for h, body in _blocks(starter, head):
        if h == head:
            return body
    return None


def _type7_cells(starter: str, iid: int):
    """``{Slav, Mast, Istf, Igap, Fpenmax, Stfac, Fric, Gapmin, Tstart,
    Tstop, Inacti, VisS}`` of /INTER/TYPE7/<iid> (2022 layout)."""
    b = _inter_block(starter, f"/INTER/TYPE7/{iid}")
    if b is None:
        return None
    c1 = b[1].split()
    row5 = b[4]
    row6 = b[5]
    return {"Slav": int(c1[0]), "Mast": int(c1[1]), "Istf": int(c1[2]),
            "Igap": int(c1[4]), "Fpenmax": float(b[2][40:60]),
            "Stfac": float(row5[0:20]), "Fric": float(row5[20:40]),
            "Gapmin": float(row5[40:60]), "Tstart": float(row5[60:80]),
            "Tstop": float(row5[80:100]), "Inacti": int(row6[10:40]),
            "VisS": float(row6[40:60])}


def _type25_groups(starter: str, iid: int):
    """``(grnd_IDs, surf_ID2)`` of /INTER/TYPE25/<iid>."""
    b = _inter_block(starter, f"/INTER/TYPE25/{iid}")
    if b is None:
        return None
    return int(b[2].split()[0]), int(b[1].split()[1])


def _stub_id(starter: str):
    lines = starter.splitlines()
    ids = [int(lines[i - 1].rsplit("/", 1)[1])
           for i, ln in enumerate(lines) if ln == _STUB_TITLE]
    return ids[0] if len(ids) == 1 else ids


# the 386444e conversions (PR10) and the branch's default of the A2 probes
_A2_PLAIN_386444E_SHA = "ec7e3d3fa5ca310d70c6045f96fd15ff97fc1457d03862f87b85f079ec305892"
_A2_PLAIN_DEFAULT_SHA = "d4713df234697e6b54ddb8c447ec075c98a93965525af302ff19c16bd6561787"
_A2_EXPLICIT_386444E_SHA = "a59634d1c0e64cd5c43be08ef26ce6c036d498110f5d89f7790860443befd647"


class ImplicitN2sType7(unittest.TestCase):
    """A2 (part-A spec A2.7): on an implicit, non-modal deck a
    *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE becomes a one-way /INTER/TYPE7 on
    the groups the TYPE25 route resolves; the all-parts stub is kept and
    carries the routed FS.

    STARTER RUNS (nt 4, C:/Users/pmqua/rcv_r9i_implA_<name>, harvested and
    deleted): a2_plain_implicit() default (p_a2plain_n4, sha256
    d4713df23469...), a2_explicit() (p_a2expl_n4, a59634d1c0e6... =
    386444e) and a2_bt_dt() (p_a2btdt_n4, a6928afafbc8...): 0 ERROR / 1
    WARNING (1084) each.

    SOLVER PINS (branch bytes, the part-A spec's coupons; nt 4 AND nt 2):
    The two-block coupons (the upper block 0.1 mm above a 2 x 2 x 1-hex
    base, its top pushed 0.3 mm; IMFLAG 1, DT0 0.1, ENDTIM 1.0; gap101 =
    (5.1 + DZ101) - (5.0 + mean DZ of nodes 10 / 11 / 13 / 14) at t 0.2 /
    0.4 / 0.6 / 0.8 / 1.0; every arm nt 4 = nt 2 to the printed digit):
    b6t (elastic base; T8's _B6T_DECK) default NORMAL 11 cycles, gap101
    +0.0751 / +0.0580 / +0.0459 / +0.0371 / +0.0303 mm, at t 1.0 the base
    reaction 6.985e5 N = the routed TYPE7 3.683e5 + the stub 3.323e5; the
    opt-out NORMAL 11, gap101 +0.0675 .. +0.0190 mm, the TYPE25 0 N at
    every row, MESSAGE 232. b6r (a RIGID base): default NORMAL 11 cycles
    WITH THE BLOCK THROUGH (gap101 -0.1481 / -0.2218 mm at t 0.8 / 1.0,
    both contacts 0 N at t 1.0 - the silent failure W-A2 names); the
    opt-out stops loudly (23 ITERATION DIVERGE, MESSAGE 79, gap101 -0.1216
    at t 0.8). b6s (the secondary a 0.1 mm SHELL skin on the upper block,
    solid main): default NORMAL 11, gap101 +0.0753 .. +0.0298 mm; the
    opt-out ERROR TERMINATION (23 DIVERGE, MESSAGE 79 / 232) and the
    route with --inter-gapmin 90001=0.05 (= t/2) ERROR TERMINATION (24
    DIVERGE, MESSAGE 79) - why the route keeps the starter's default gap
    (D2). doorbeam (sha256 2926b1300fb6..., the A1 + A2 bytes): NORMAL 35
    cycles in all six runs of this batch (nt 4 x3, nt 2 x3; the 386444e
    base 39 cycles = 0.897x in the same window), IE END -28.0774 /
    -27.9855 / -27.9855 % (nt 4) and -28.0774 / -28.0774 / -28.0314 % (nt
    2), RMS 15.21 .. 15.25 % over the 25 LS times in (1e-5, 1.1e-3]; with
    the part-A spec's six runs of the same bytes (two at nt 2 on a -15.85 %
    / RMS 10.34 % branch) the shipped band is END -15.85 .. -28.08 %, RMS
    10.34 .. 15.25 %; the punch node 1 DY = the LS nodout at every fifth
    (32.3 / 65.32 / 95.32 / 132.8 / 135 mm).
    """

    def test_a_the_plain_spelling_is_a_one_way_TYPE7_beside_the_stub(self):
        res, st, _e = _convert(a2_plain_implicit())
        self.assertEqual(_sha(st), _A2_PLAIN_DEFAULT_SHA)
        self.assertNotIn("/INTER/TYPE25/", st)
        cells = _type7_cells(st, 78)
        self.assertIsNotNone(cells, st)
        self.assertEqual((cells["Istf"], cells["Igap"]), (4, 0))
        self.assertEqual(cells["Fric"], 0.1)
        self.assertEqual(cells["Gapmin"], 0.0)
        self.assertEqual(cells["Fpenmax"], 0.999999)
        self.assertEqual(cells["Inacti"], 5)
        self.assertEqual(cells["Tstop"], 0.0)       # DT blank = never
        stub = _stub_id(st)
        self.assertEqual(_type7_cells(st, stub)["Fric"], 0.1)
        self.assertTrue(_has(res.warnings, _W_A2 + "78", "MESSAGE 232",
                             "imp_int_k.F:111-200", "ind_glob_k.F:4601-4605",
                             "intfop2.F:595", "-15.85 .. -28.08 %",
                             "10.34 .. 15.25 %", "gap -0.2218 mm",
                             "--no-implicit-n2s-type7"))
        self.assertTrue(_has(res.warnings, _W_A2_STUB, "[78]", "FS 0.1",
                             f"/INTER/TYPE7 {stub}"))
        self.assertFalse(_has(res.warnings,
                              "Implicit deck with TYPE25-route contact(s)"))

    def test_a2_the_routed_groups_are_the_TYPE25_routes(self):
        """The TYPE7's Slav / Mast are the groups the TYPE25 route resolved
        (grnd_IDs / surf_ID2 of the opt-out), with the same group blocks."""
        _r, st, _e = _convert(a2_plain_implicit())
        _r, st_off, _e = _convert(a2_plain_implicit(),
                                  implicit_n2s_type7=False)
        cells = _type7_cells(st, 78)
        grnd, surf = _type25_groups(st_off, 78)
        self.assertEqual((cells["Slav"], cells["Mast"]), (grnd, surf))
        g_on, g_off = _grnod_by_id(st), _grnod_by_id(st_off)
        self.assertEqual(g_on[grnd], g_off[grnd])

    def test_b_the_AUTOMATIC_MPP_spelling_routes_the_same_way(self):
        deck = _shell_plate(_IMPL1, _SET5 + _n2s(
            "*CONTACT_AUTOMATIC_NODES_TO_SURFACE_MPP_ID", mpp=True))
        res, st, _e = _convert(deck)
        self.assertNotIn("/INTER/TYPE25/", st)
        cells = _type7_cells(st, 78)
        self.assertEqual((cells["Istf"], cells["Igap"], cells["Fric"]),
                         (4, 0, 0.1))
        self.assertEqual(_type7_cells(st, _stub_id(st))["Fric"], 0.1)

    def test_c_an_explicit_deck_keeps_the_TYPE25_bytes(self):
        res, st, _e = _convert(a2_explicit())
        self.assertEqual(_sha(st), _A2_EXPLICIT_386444E_SHA)
        self.assertIn("/INTER/TYPE25/78", st)
        self.assertNotIn(_STUB_TITLE, st)
        self.assertFalse(_has(res.warnings, _W_A2))

    def test_d_an_implicit_ERODING_spelling_keeps_the_TYPE25(self):
        deck = _shell_plate(_IMPL1, _SET5 + _n2s(
            "*CONTACT_ERODING_NODES_TO_SURFACE_ID", card4=(0, 1, 0)))
        res, st, _e = _convert(deck)
        self.assertIn("/INTER/TYPE25/78", st)
        self.assertIsNone(_type7_cells(st, 78))
        self.assertFalse(_has(res.warnings, _W_A2))
        self.assertEqual(_type7_cells(st, _stub_id(st))["Fric"], 0.0)

    def test_e_a_modal_deck_keeps_the_TYPE25_and_no_stub(self):
        res, st, _e = _convert(_shell_plate(_MODAL, _SET5 + _n2s()))
        self.assertIn("/INTER/TYPE25/78", st)
        self.assertNotIn(_STUB_TITLE, st)
        self.assertFalse(_has(res.warnings, _W_A2))

    def test_f_the_opt_out_restores_the_386444e_bytes_and_sentences(self):
        res, st, _e = _convert(a2_plain_implicit(), implicit_n2s_type7=False)
        self.assertEqual(_sha(st), _A2_PLAIN_386444E_SHA)
        self.assertTrue(_has(res.warnings,
                             "Implicit deck with TYPE25-route contact(s) [78]"))
        self.assertFalse(_has(res.warnings, _W_A2))
        self.assertFalse(_has(res.warnings, _W_A2_STUB))
        self.assertEqual(_type7_cells(st, _stub_id(st))["Fric"], 0.0)

    def test_g_an_all_rigid_SSID_follows_the_TYPE25_routes_plan(self):
        """The TYPE25 route's all-rigid-SSID plan (swap / keep) is run before
        the route: the TYPE7 takes whatever groups the plan resolved."""
        rigid = ("*PART\nrigid plate\n" + _row(2, 1, 2) + "\n"
                 "*MAT_RIGID\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
                 + _row(1.0, 7, 7) + "\n" + _row(0.0) + "\n"
                 "*NODE\n"
                 + "".join(f"{n:>8}{x:>16.1f}{y:>16.1f}{5.0:>16.1f}\n"
                           for n, x, y in ((11, 0, 0), (12, 10, 0),
                                           (13, 10, 10), (14, 0, 10)))
                 + "*ELEMENT_SHELL\n"
                 + "".join(f"{v:>8}" for v in (11, 2, 11, 12, 13, 14)) + "\n"
                 "*CONTACT_NODES_TO_SURFACE_ID\n" + _row(78) + "\n"
                 + _row(2, 1, 3, 3) + "\n" + _row(0.1) + "\n" + _row() + "\n")
        res, st, _e = _convert(_shell_plate(_IMPL1, rigid))
        r_off, st_off, _e = _convert(_shell_plate(_IMPL1, rigid),
                                     implicit_n2s_type7=False)
        cells = _type7_cells(st, 78)
        groups = _type25_groups(st_off, 78)
        if groups is None:
            # the plan dropped the contact on both arms
            self.assertIsNone(cells)
        else:
            self.assertEqual((cells["Slav"], cells["Mast"]), groups)
        plan_on = [w for w in res.warnings if "all-rigid" in w.lower()
                   or "ALL " in w and "rigid body" in w]
        plan_off = [w for w in r_off.warnings if "all-rigid" in w.lower()
                    or "ALL " in w and "rigid body" in w]
        self.assertEqual(plan_on, plan_off)

    def test_h_the_gap_rules_that_reach_the_route(self):
        """D2: SST / MST dropped (the route keeps the starter's default gap);
        an explicit --inter-gapmin is honoured and named; --derived-gapmin
        never reaches the route."""
        deck = _shell_plate(_IMPL1, _SET5 + _n2s(card3=(0.0, 0.0, 0.5)))
        res, st, _e = _convert(deck)
        self.assertEqual(_type7_cells(st, 78)["Gapmin"], 0.0)
        self.assertTrue(_has(res.warnings, "SST=0.5", "keeps the starter's "
                             "default gap"))
        self.assertFalse(_has(res.warnings, "SST=0.5", "Gap_scale"))
        r2, st2, _e = _convert(a2_plain_implicit(), inter_gapmin={78: 0.05})
        self.assertEqual(_type7_cells(st2, 78)["Gapmin"], 0.05)
        self.assertTrue(_has(r2.warnings, _W_A2_GAP, "IE END -96.57 %"))
        self.assertFalse(_has(r2.warnings, "--inter-gapmin 78=0.05: "))
        r3, st3, _e = _convert(a2_plain_implicit(), derived_gapmin=True)
        self.assertEqual(_type7_cells(st3, 78)["Gapmin"], 0.0)

    def test_i_two_routed_contacts_disagreeing_on_FS_leave_the_stub_bare(self):
        deck = _shell_plate(_IMPL1, _SET5 + _n2s(card2=(0.2,))
                            + _n2s(iid=79, card2=(0.3,)))
        res, st, _e = _convert(deck)
        self.assertEqual(_type7_cells(st, 78)["Fric"], 0.2)
        self.assertEqual(_type7_cells(st, 79)["Fric"], 0.3)
        self.assertEqual(_type7_cells(st, _stub_id(st))["Fric"], 0.0)
        self.assertTrue(_has(res.warnings, _W_A2_MIX, "[78, 79]", "0.2, 0.3"))
        self.assertFalse(_has(res.warnings, _W_A2_STUB))

    def test_j_BT_and_DT_reach_the_TYPE7_line(self):
        res, st, _e = _convert(a2_bt_dt())
        cells = _type7_cells(st, 78)
        self.assertEqual((cells["Tstart"], cells["Tstop"]), (0.001, 0.009))
        self.assertEqual(cells["Fric"], 0.2)
        self.assertTrue(_has(res.warnings, _W_A2 + "78",
                             "Tstart 0.001 / Tstop 0.009"))

    def test_k_the_B6_opt_in_keys_on_the_TYPE25_records_only(self):
        """A routed-only deck keeps its stub under the B6 opt-in (no B6
        sentence); a routed N2S beside an ERODING TYPE25 defers on the
        TYPE25 alone."""
        res, st, _e = _convert(a2_plain_implicit(),
                               skip_implicit_stub_with_type25=True)
        self.assertIsInstance(_stub_id(st), int)
        self.assertIsNotNone(_type7_cells(st, 78))
        self.assertFalse(_has(res.warnings, "--skip-implicit-stub-with-type25"))
        deck = _shell_plate(_IMPL1, _SET5 + _n2s() + _n2s(
            "*CONTACT_ERODING_NODES_TO_SURFACE_ID", iid=79, card4=(0, 1, 0)))
        from k2rad import _inject_implicit_contact_stub
        stt = _t7._dispatch(deck)
        stt.options.skip_implicit_stub_with_type25 = True
        _inject_implicit_contact_stub(stt)
        self.assertEqual(stt.implicit_stub_deferred_for, [79])
        self.assertEqual(stt.contacts_single, [])


# ═════════════════════════════════════════════════════════════════════════════
# A4 + A5 — implicit rigid-body gravity keeps the rigid parts' own nodes in
#           /GRAV; a rigid-only *SECTION_BEAM ELFORM 7 takes its section from
#           TS1 (only with A4 on an implicit deck)
# ═════════════════════════════════════════════════════════════════════════════

import test_gravity as _tg  # noqa: E402

_IMPL_LINE = "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n"
_TG_HEAD_IMPL = _tg.HEAD.replace("*CONTROL_TERMINATION\n      0.01\n",
                                 "*CONTROL_TERMINATION\n      0.01\n"
                                 + _IMPL_LINE)
_W_A4 = "on an IMPLICIT deck: the rigid part(s)"


def a4_implicit_disk() -> str:
    """An implicit rigid shell disk: eight ELFORM-2 shells of one *MAT_RIGID
    part 1 (a 4 x 2 grid, nodes 1-15) under *LOAD_BODY_Y on a constant
    curve; nothing else. Converted, the main node is the synthesized 16."""
    nodes = ["*NODE"]
    nid = 0
    for j in range(3):
        for i in range(5):
            nid += 1
            nodes.append(f"{nid:>8}{10.0 * i:>16}{10.0 * j:>16}{0.0:>16}")
    elems = ["*ELEMENT_SHELL"]
    eid = 0
    for j in range(2):
        for i in range(4):
            eid += 1
            n1 = j * 5 + i + 1
            elems.append("".join(f"{v:>8}" for v in
                                 (eid, 1, n1, n1 + 1, n1 + 6, n1 + 5)))
    return "\n".join(
        ["*KEYWORD", "*CONTROL_TERMINATION", _row(0.05),
         "*CONTROL_IMPLICIT_GENERAL", _row(1, 0.005),
         "*PART", "rigid disk", _row(1, 1, 1),
         "*SECTION_SHELL", _row(1, 2), _row(1.0, 1.0, 1.0, 1.0),
         "*MAT_RIGID", _row(1, 7.85e-9, 2.1e5, 0.3), _row(0.0, 0, 0),
         _row(0.0)] + nodes + elems
        + ["*DEFINE_CURVE", _row(1), f"{0.0:>20}{1.0:>20}",
           f"{1.0:>20}{1.0:>20}", "*LOAD_BODY_Y", _row(1, 9810.0),
           "*END", ""])


_A4_DISK_386444E_SHA = "205d70284e9d239501a6b83091bb359ca73f413ae75c4a90686b012ecfc30715"


class ImplicitRigidGravityNodes(unittest.TestCase):
    """A4 (part-A spec A4.2): on an IMPLICIT deck the rigid parts stay in
    the /GRAV's /GRNOD/PART beside their /RBODY main node; explicit decks
    keep the swap (tests/test_gravity.py GravityRigidBodyTests, unchanged).

    STARTER RUN (nt 4, rcv_r9i_implA_p_a4disk_n4, a4_implicit_disk()):
    a4_implicit_disk() bytes (sha256 ea92abf9ca80...): 0 ERROR / 1 WARNING
    (1084).

    ENGINE (ex_16, the A4 + A5 bytes sha256 5f85c259cfe4..., implicit):
    NORMAL TERMINATION in 1101 cycles in all six runs (nt 4 x3, nt 2 x3;
    the 386444e base stops at the starter, ERRORs 274 + 314-317), KE END
    +439.6714 %, fifths +0.42 / +0.20 / +0.14 / +60.22 / +439.67 %, RMS
    59.56 % of the LS peak over the 1100 LS times in (1e-4, 0.11], IE END
    +31.8085 % / RMS 18.7 % - identical to every printed digit across the
    six runs (the 4th / 5th fifths are the disk passing the wall: the
    *CONTACT_2D is not converted)."""

    def test_the_rigid_part_stays_beside_its_main(self):
        deck = _TG_HEAD_IMPL + _tg._gravity_part(1) + _tg._gravity_part(2) \
            + _tg.END
        res, starter = _tg._convert(deck)
        parts, nodes = _tg._grav_scope(starter)
        self.assertEqual(parts, {1, 2})
        self.assertTrue(_tg._rbody_mains(starter) <= nodes)
        self.assertTrue(_has(res.warnings, "*LOAD_GRAVITY_PART", _W_A4,
                             "gravit_imp.F", "+0.42 / +0.20 / +0.14 %",
                             "--no-implicit-rigid-gravity-nodes"))
        self.assertFalse(_has(res.warnings, "instead of their mesh nodes"))

    def test_the_group_is_still_the_part_node_union(self):
        deck = _TG_HEAD_IMPL + _tg._gravity_part(1) + _tg._gravity_part(2) \
            + _tg.END
        _r, starter = _tg._convert(deck)
        gid = int(_tg._grav_cards(starter)[0][1][40:50])
        groups = _tg._grnods(starter)
        self.assertEqual(groups[gid][0], "GRNOD")
        self.assertEqual({groups[m][0] for m in groups[gid][1]},
                         {"PART", "NODE"})

    def test_a_rigid_only_scope_now_has_a_part_group_too(self):
        deck = _TG_HEAD_IMPL + _tg._gravity_part(2) + _tg.END
        _r, starter = _tg._convert(deck)
        parts, nodes = _tg._grav_scope(starter)
        self.assertEqual(parts, {2})
        self.assertEqual(nodes, _tg._rbody_mains(starter))

    def test_body_loads_keep_every_rigid_part(self):
        _r, st = _tg._convert(_TG_HEAD_IMPL + _tg.CURVE + _tg._load_body()
                              + _tg.END)
        parts, nodes = _tg._grav_scope(st)
        self.assertEqual(parts, {1, 2, 3})
        self.assertEqual(nodes, _tg._rbody_mains(st))
        r2, st2 = _tg._convert(_TG_HEAD_IMPL + _tg.SECOND_RIGID + _tg.CNRB
                               + _tg.CURVE + _tg._load_body() + _tg.END)
        parts2, nodes2 = _tg._grav_scope(st2)
        self.assertEqual(parts2, {1, 2, 3, 4})
        self.assertEqual(nodes2, _tg._rbody_mains(st2))
        self.assertEqual(len(nodes2), 3)
        self.assertTrue(_has(r2.warnings, "*LOAD_BODY_*", _W_A4))

    def test_the_opt_out_and_an_explicit_deck_keep_the_swap(self):
        imp = _TG_HEAD_IMPL + _tg._gravity_part(1) + _tg._gravity_part(2) \
            + _tg.END
        r_off, st_off = _tg._convert(imp, implicit_rigid_gravity_nodes=False)
        self.assertEqual(_tg._grav_scope(st_off)[0], {1})
        self.assertFalse(_has(r_off.warnings, _W_A4))
        self.assertTrue(_has(r_off.warnings, "instead of their mesh nodes"))
        exp = _tg.HEAD + _tg._gravity_part(1) + _tg._gravity_part(2) \
            + _tg.END
        r_x, st_x = _tg._convert(exp)
        self.assertEqual(_tg._grav_scope(st_x)[0], {1})
        self.assertFalse(_has(r_x.warnings, _W_A4))

    def test_an_implicit_CNRB_only_scope_is_unchanged(self):
        """A CNRB swaps no part: no rigid part record is kept, so the bytes
        and the sentence are the opt-out's (the door sag's class)."""
        deck = _TG_HEAD_IMPL + _tg.CNRB + _tg._gravity_part(3) + _tg.END
        r_on, st_on = _tg._convert(deck)
        r_off, st_off = _tg._convert(deck, implicit_rigid_gravity_nodes=False)
        self.assertEqual(_sha(st_on), _sha(st_off))
        self.assertFalse(_has(r_on.warnings, _W_A4))

    def test_the_implicit_rigid_disk(self):
        res, st, _e = _convert(a4_implicit_disk())
        parts, nodes = _tg._grav_scope(st)
        self.assertEqual(parts, {1})
        self.assertEqual(nodes, _tg._rbody_mains(st))
        self.assertTrue(_has(res.warnings, "*LOAD_BODY_*", _W_A4, "1 stay"))
        _r, st_off, _e = _convert(a4_implicit_disk(),
                                  implicit_rigid_gravity_nodes=False)
        self.assertEqual(_sha(st_off), _A4_DISK_386444E_SHA)
        self.assertEqual(_tg._grav_scope(st_off)[0], set())


_W_A5 = "ELFORM 7 (2-D plane-strain beam) states its section as TS1"
_W_A5_PAIR = "the section from TS1 is written only together"
_REFUSAL = "the starter REFUSES"


def _a5_deck(mat: str = "rigid", elform: int = 7, implicit: bool = False,
             ts=(0.1, 0.1)) -> str:
    """One ELFORM *elform* beam (part 7, section 5, nodes 1 -> 2, orientation
    node 3) on *MAT_RIGID (CMO 1, CON1 7, CON2 7) or *MAT_ELASTIC."""
    m = ("*MAT_RIGID\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
         + _row(1.0, 7, 7) + "\n" + _row(0.0)
         if mat == "rigid" else
         "*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3))
    ctrl = ["*CONTROL_TERMINATION", _row(0.01)]
    if implicit:
        ctrl += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 0.001)]
    return "\n".join(
        ["*KEYWORD"] + ctrl + [
            "*NODE",
            f"{1:>8}{0.0:>16}{0.0:>16}{0.0:>16}",
            f"{2:>8}{25.4:>16}{0.0:>16}{0.0:>16}",
            f"{3:>8}{0.0:>16}{1.0:>16}{0.0:>16}",
            "*ELEMENT_BEAM", "".join(f"{v:>8}" for v in (1, 7, 1, 2, 3)),
            "*PART", "beam wall", _row(7, 5, 9),
            "*SECTION_BEAM", _row(5, elform, 1.0, 0.0, 0), _row(*ts),
            m, "*END", ""])


def a5_rigid_wall() -> str:
    return _a5_deck()


def a5_rigid_wall_implicit() -> str:
    return _a5_deck(implicit=True)


_A5_WALL_386444E_SHA = "b13e9b25a86899ab0039226a80cad38ac9809fa1df24a5b42872acd491fb5124"


def _beam_cells(starter: str):
    for head, body in _blocks(starter, "/PROP/BEAM/"):
        row = body[3]        # title, Ismstr, dm df, Area Iyy Izz Ixx
        return tuple(float(row[20 * k:20 * (k + 1)]) for k in range(4))
    return None


class TwoDBeamThicknessSection(unittest.TestCase):
    """A5 (part-A spec A5.2, scope D3): a rigid-only ELFORM 7 section gets
    Area = TS1, I = TS1^3 / 12.

    STARTER RUNS (nt 4): a5_rigid_wall() and a5_rigid_wall_implicit()
    (both _0000.rad sha256 fbc2533d5a1c...): 0 ERROR / 0 WARNING; ex_16's
    386444e bytes (the zero section) stop on ERRORs 274 + 314-317
    (e16Base_n4)."""

    _CELLS = (0.1, 0.1 ** 3 / 12.0, 0.1 ** 3 / 12.0, 2 * 0.1 ** 3 / 12.0)

    def _assert_cells(self, got):
        self.assertIsNotNone(got)
        for g, w in zip(got, self._CELLS):
            self.assertAlmostEqual(g, w, delta=1e-9 * max(1.0, abs(w)))

    def test_a_rigid_wall_gets_the_TS1_section(self):
        for deck in (a5_rigid_wall(), a5_rigid_wall_implicit()):
            with self.subTest(implicit="IMPLICIT" in deck):
                res, st, _e = _convert(deck)
                self._assert_cells(_beam_cells(st))
                self.assertTrue(_has(res.warnings, _W_A5, "5.68 x rho",
                                     "0.15414498E-10",
                                     "--no-elform7-beam-thickness-section"))
                self.assertFalse(_has(res.warnings, _REFUSAL))

    def test_the_cell_text_is_k2rads_float_format(self):
        _r, st, _e = _convert(a5_rigid_wall())
        row = [b for h, b in _blocks(st, "/PROP/BEAM/")][0][3]
        self.assertEqual(row, "                 0.1        8.333333E-05"
                              "        8.333333E-05     0.0001666666667")

    def test_a_deformable_member_and_ELFORM_8_keep_the_refusal(self):
        for deck in (_a5_deck(mat="elastic"), _a5_deck(elform=8)):
            with self.subTest():
                res, st, _e = _convert(deck)
                self.assertEqual(_beam_cells(st), (0.0, 0.0, 0.0, 0.0))
                self.assertTrue(_has(res.warnings, _REFUSAL, "ERROR 314"))
                self.assertFalse(_has(res.warnings, _W_A5))

    def test_implicit_without_A4_keeps_the_refusal_and_says_why(self):
        res, st, _e = _convert(a5_rigid_wall_implicit(),
                               implicit_rigid_gravity_nodes=False)
        self.assertEqual(_beam_cells(st), (0.0, 0.0, 0.0, 0.0))
        self.assertTrue(_has(res.warnings, _W_A5_PAIR,
                             "--implicit-rigid-gravity-nodes", "frozen"))
        self.assertFalse(_has(res.warnings, _W_A5))

    def test_the_opt_out_restores_the_386444e_bytes(self):
        res, st, _e = _convert(a5_rigid_wall(),
                               elform7_beam_thickness_section=False)
        self.assertEqual(_sha(st), _A5_WALL_386444E_SHA)
        self.assertTrue(_has(res.warnings, _REFUSAL))

    def test_the_findings_spelling_is_an_alias(self):
        from k2rad import cli
        ns = cli.build_parser().parse_args(["d.k",
                                            "--no-2d-beam-thickness-section"])
        self.assertIs(ns.elform7_beam_thickness_section, False)


# ═════════════════════════════════════════════════════════════════════════════
# A6 — *BOUNDARY_SPC on a *DEFINE_COORDINATE_VECTOR CID is written in that
#      frame, through one helper for its five consumers
# ═════════════════════════════════════════════════════════════════════════════

_VEC3 = ("*DEFINE_COORDINATE_VECTOR\n"
         + _row(3, 1.0, 2.0, 2.0, 2.0, 1.0, -2.0) + "\n")
_W_A6 = "card(s) name a *DEFINE_COORDINATE_VECTOR CID"
_W_A6_OFF = "--no-spc-vector-frames writes the constraint in the GLOBAL"
_NOT_FOUND = "not found — constraint applied in the GLOBAL system"


def _a6_block(spc: str, extra: str = "", implicit: bool = False,
              free_node: bool = False) -> str:
    """One elastic hex (part 1, nodes 1-8, a 10 mm cube) + *spc*."""
    pts = [(1, 0, 0, 0), (2, 10, 0, 0), (3, 10, 10, 0), (4, 0, 10, 0),
           (5, 0, 0, 10), (6, 10, 0, 10), (7, 10, 10, 10), (8, 0, 10, 10)]
    if free_node:
        pts.append((50, 30, 0, 0))
    ctrl = ["*CONTROL_TERMINATION", _row(0.001)]
    if implicit:
        ctrl += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 0.0001)]
    return "\n".join(
        ["*KEYWORD"] + ctrl + ["*NODE"]
        + [f"{n:>8}{float(x):>16}{float(y):>16}{float(z):>16}"
           for n, x, y, z in pts]
        + ["*ELEMENT_SOLID",
           "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4, 5, 6, 7, 8)),
           "*PART", "block", _row(1, 1, 1),
           "*SECTION_SOLID", _row(1, 1),
           "*MAT_ELASTIC", _row(1, 7.85e-9, 210000.0, 0.3),
           (_VEC3 + extra + spc).rstrip("\n"), "*END", ""])


def a6_vector_spc() -> str:
    """(a): nodes 1-4 (set 10) held in x' / y' of the VECTOR frame 3."""
    return _a6_block("*SET_NODE_LIST\n" + _row(10) + "\n" + _row(1, 2, 3, 4)
                     + "\n*BOUNDARY_SPC_SET\n" + _row(10, 3, 1, 1, 0, 0, 0, 0)
                     + "\n")


_A6_VECTOR_386444E_SHA = "6803105a17895fa762cdcf26bd3422b6b8419c5f82e0409c24bd004502554dcc"


def _bcs_rows(starter: str):
    """[(Tra, Rot, skew_ID, grnod_ID)] of every /BCS."""
    out = []
    for head, body in _blocks(starter, "/BCS/"):
        d = body[1].split()
        out.append((d[0], d[1], int(d[2]), int(d[3])))
    return out


def a6_free_node_vector_spc() -> str:
    """(b) / (d): an IMPLICIT block whose free node 50 carries a VECTOR-CID
    SPC (x', y', z' held)."""
    return _a6_block("*BOUNDARY_SPC_NODE\n" + _row(50, 3, 1, 1, 1, 0, 0, 0)
                     + "\n", implicit=True, free_node=True)


class SpcVectorFrames(unittest.TestCase):
    """A6 (part-A spec A6): ONE helper (writer/loads.spc_cid_skew) for the
    five *BOUNDARY_SPC consumers; a VECTOR CID is written in its existing
    /SKEW/FIX/<cid>.

    STARTER RUNS (nt 4, rcv_r9i_implA_<name>): a6_vector_spc() default
    (p_a6vec_n4) and --no-spc-vector-frames (p_a6vecOff_n4, = 386444e): 0
    ERROR / 0 WARNING each. a6_free_node_vector_spc() default
    (p_a6free_n4): ERROR 148 + WARNING 312 - the named outcome: the
    free-node guard's global card on a node whose SPC sits in /SKEW 3 is
    the one-skew-per-node pair its sentence names (reach 0: every roster
    VECTOR-CID SPC row is on the explicit cylinder).

    ENGINE (control_adaptive.cylinder, explicit nt 4, the branch bytes vs
    the 386444e base in one window, 271 = 271 cycles; an output-only
    displacement /TH block on the 14 rotated-frame SPC nodes): the
    constrained local displacement max 0.33518 mm (node 86, frame 6) ->
    1.81e-8 mm, the free-DOF reaction max 4610.9 -> 0.0239 N (RMS 1105.7 ->
    0.0019 N), all 271 states; IE END +5.3989 -> +5.3776 %, KE END +20.6080
    -> +20.2914 % (19 LS times in (1.8828e-05, 3.79839e-04]); a second run
    of the branch bytes identical to every digit.
    """

    def test_a_a_VECTOR_CID_is_the_BCS_skew(self):
        res, st, _e = _convert(a6_vector_spc())
        self.assertIn(("110", "000", 3, 10), _bcs_rows(st))
        self.assertTrue(re.search(r"^/SKEW/FIX/3$", st, re.M))
        self.assertTrue(_has(res.warnings, _W_A6, "(3)", "0.3352 mm",
                             "4611 N", "--no-spc-vector-frames"))
        self.assertFalse(_has(res.warnings, _NOT_FOUND))

    def test_a2_the_opt_out_restores_the_bytes_with_a_true_sentence(self):
        res, st, _e = _convert(a6_vector_spc(), spc_vector_frames=False)
        self.assertEqual(_sha(st), _A6_VECTOR_386444E_SHA)
        self.assertIn(("110", "000", 0, 10), _bcs_rows(st))
        self.assertTrue(_has(res.warnings, _W_A6_OFF, "CID 3"))
        self.assertFalse(_has(res.warnings, _NOT_FOUND))
        self.assertFalse(_has(res.warnings, _W_A6))

    def test_a3_a_CID_in_no_registry_keeps_the_true_not_found(self):
        deck = _a6_block("*SET_NODE_LIST\n" + _row(10) + "\n"
                         + _row(1, 2, 3, 4) + "\n*BOUNDARY_SPC_SET\n"
                         + _row(10, 9, 1, 1, 0, 0, 0, 0) + "\n")
        for kw in ({}, {"spc_vector_frames": False}):
            with self.subTest(**kw):
                res, st, _e = _convert(deck, **kw)
                self.assertIn(("110", "000", 0, 10), _bcs_rows(st))
                self.assertTrue(_has(res.warnings, "cid=9", _NOT_FOUND))

    def test_b_a_VECTOR_SPC_is_not_a_global_bit_for_the_free_node_guard(self):
        """_global_spc_dofs: the VECTOR-CID free node is NOT a global SPC
        bit, so the implicit free-node guard keeps its 111 111 card on it
        and names the ERROR 148 pair (d); under the opt-out the SPC is
        global and the guard writes only the remaining DOFs."""
        deck = a6_free_node_vector_spc()
        res, st, _e = _convert(deck)
        groups = _grnod_by_id(st)
        guard = {(t, r, s): groups[g][1] for t, r, s, g in _bcs_rows(st)
                 if g in groups and groups[g][0].startswith("free_reference")}
        self.assertEqual(guard, {("111", "111", 0): [50]})
        self.assertTrue(_has(res.warnings, "Free-node guard: free node(s)",
                             "50", "/SKEW 3", "ERROR 148"))
        r_off, st_off, _e = _convert(deck, spc_vector_frames=False)
        self.assertFalse(_has(r_off.warnings, "/SKEW 3", "ERROR 148"))
        self.assertTrue(_has(r_off.warnings, "Free-node guard x "
                             "*BOUNDARY_SPC"))

    def test_c_the_CONSTRAINED_LINEAR_screen_sees_the_skew(self):
        import test_r14_triage_6 as _t6
        spc = (_VEC3 + "*BOUNDARY_SPC_NODE\n"
               + _row(40, 3, 0, 0, 1, 0, 0, 0) + "\n")
        r_on, _s, _e = _convert(_t6._linear_deck(extra=spc))
        r_off, _s, _e = _convert(_t6._linear_deck(extra=spc),
                                 spc_vector_frames=False)
        self.assertTrue(_has(r_on.warnings, "node 40 DOF 3 already carries",
                             "a skewed *BOUNDARY_SPC /BCS"))
        self.assertTrue(_has(r_off.warnings, "node 40 DOF 3 already carries",
                             "*BOUNDARY_SPC /BCS"))
        self.assertFalse(_has(r_off.warnings, "a skewed *BOUNDARY_SPC /BCS"))

    def test_e_the_screw_body_condition_carries_the_skew(self):
        mod = _t7._screw_synthetic()
        start = mod.TOP_NODE - (27 + 27 + 9 * len(mod.PLATES)) + 1
        extra = (_VEC3 + "*BOUNDARY_SPC_NODE\n"
                 + _row(start, 3, 1, 0, 0, 0, 0, 0) + "\n")
        deck = mod.build_deck(extra=extra)
        r_on, _s, _e = _convert(deck)
        r_off, _s, _e = _convert(deck, spc_vector_frames=False)
        self.assertTrue(_has(r_on.warnings, "in a local system (/SKEW 3"))
        self.assertFalse(_has(r_off.warnings, "in a local system (/SKEW 3"))


# ═════════════════════════════════════════════════════════════════════════════
# A8 — a stated SF 0.0 on *BOUNDARY_PRESCRIBED_MOTION_* is LS-DYNA's default
#      1.0; a NODE / SET row stays a /BCS hold only for a zero motion
# ═════════════════════════════════════════════════════════════════════════════

import test_motion_load_variants as _tmv  # noqa: E402

_imp_cards = _tmv._imp_cards
_W_A8_SET = "SF = 0.0 is read as the card's default 1.0"
_W_A8_RIGID = "SF = 0.0 written as the default Fscale 1.0"
_RAMP_7 = ("*DEFINE_CURVE\n" + _row(7) + "\n" + f"{0.0:>20}{0.0:>20}\n"
           + f"{1.0:>20}{10.0:>20}\n")
_ZERO_8 = ("*DEFINE_CURVE\n" + _row(8) + "\n" + f"{0.0:>20}{0.0:>20}\n"
           + f"{1.0:>20}{0.0:>20}\n")


def _a8_set(vad: int = 0, lcid: int = 7, sf: float = 0.0, dof: int = 2,
            implicit: bool = False, free_node: bool = False) -> str:
    """The shell plate (nodes 1-6) + node set 5 (nodes 1 2 3 [+ the free
    node 50]) driven by *BOUNDARY_PRESCRIBED_MOTION_SET (DOF *dof*)."""
    ctrl = _IMPL1 if implicit else _EXPLICIT
    nodes = [1, 2, 3] + ([50] if free_node else [])
    extra = ""
    if free_node:
        extra += "*NODE\n" + f"{50:>8}{40.0:>16}{0.0:>16}{0.0:>16}\n"
    extra += ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(*nodes) + "\n"
              + _RAMP_7 + _ZERO_8 + "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
              + _row(5, dof, vad, lcid, sf) + "\n")
    return _shell_plate(ctrl, extra)


def a8_set_ramp() -> str:
    """(a): SF 0.0, VAD 0 on the ramp curve 7."""
    return _a8_set()


def a8_vad1_inivel() -> str:
    """(d)'s engine deck: VAD 1 on the zero curve 8 (SF 0.0) over nodes 1-3
    which start at VY 100 mm/s (*INITIAL_VELOCITY on set 5), explicit, t
    0.01; node 1 in a *DATABASE_HISTORY_NODE. A zero imposed acceleration
    keeps the initial velocity: DY(t) = 100 t (1.0 mm at t 0.01)."""
    deck = _a8_set(vad=1, lcid=8)
    return deck.replace(
        "*END\n", "*INITIAL_VELOCITY\n" + _row(5) + "\n"
        + _row(0.0, 100.0, 0.0) + "\n*DATABASE_HISTORY_NODE\n" + _row(1)
        + "\n*DATABASE_NODOUT\n" + _row(1.0e-4) + "\n*END\n")


def a8_rigid_sf0() -> str:
    """(f): *BOUNDARY_PRESCRIBED_MOTION_RIGID SF 0.0 on the A1 probe's
    rigid plate (no CNRB clash: the CNRB takes PID 3)."""
    return _a1_probe(_PM.replace(_row(1, 3, 2, 1, 1.0), _row(1, 3, 2, 1, 0.0)),
                     cnrb_pid=3)


_A8_SET_386444E_SHA = "9425c3c6da12cbd94952a68d64032214c37715236b394c10967ce90b0bacc469"
_A8_RIGID_386444E_SHA = "555a6647813579642d1ed08cce3fa85e96b32a506d98f0cae613cea5fe906f02"


class PrescribedMotionSfDefault(unittest.TestCase):
    """A8 (part-A spec A8): a stated SF 0.0 is LS-DYNA's default 1.0 (Vol I
    R17 p.759; Appendix V p.73-9). NO measured-gain sentence ships (both
    runnable movers die at 9 % of t_end in both arms).

    STARTER RUNS (nt 4, rcv_r9i_implA_<name>): a8_set_ramp() (p_a8set_n4)
    and a8_rigid_sf0() (p_a8rig_n4) default bytes: 0 ERROR / 1 WARNING
    (1084) each.

    ENGINE (d), D11 (a8vad1_n4, explicit nt 4, NORMAL 6643 cycles): the
    VAD 1 row on the zero curve as /IMPACC Fscale 1 keeps the initial
    velocity - node 1 VY 100 at every state, DY 0.200095 / 0.500012 /
    0.990087 mm at t 2.00095e-3 / 5.00012e-3 / 9.90087e-3 (= 100 t).

    stagnation_A / _B (the physics movers, explicit nt 4, base-paired):
    both arms of both decks ERROR TERMINATION (MESSAGE 167, NEGATIVE RHO)
    at 9 % of t_end - 825 cycles at 386444e, 832 on the branch; IE END
    -222.95 -> -100.21 % (A), RMS 33.43 -> 15.34 % (A) and 3366.19 -> 32.16
    % (B) over 44 vs 45 LS times (windows differ by one time: MIXED);
    EXT-WORK 3.120 at t 1.81e-3 on the branch (0 at 386444e) - hence no
    gain sentence ships."""

    def test_a_a_non_zero_curve_is_imposed_with_Fscale_1(self):
        res, st, _e = _convert(a8_set_ramp())
        imps = _imp_cards(st)
        self.assertEqual([(c[0], c[3], c[10]) for c in imps],
                         [("/IMPVEL", "Y", 1.0)])
        self.assertFalse(any(r[0] == "010" for r in _bcs_rows(st)))
        self.assertTrue(_has(res.warnings, _W_A8_SET, "curve 7 (VAD 0)",
                             "/IMPVEL Fscale 1", "Vol I R17 p.759",
                             "--no-prescribed-motion-sf-default"))

    def test_b_c_e_a_zero_motion_stays_a_BCS_hold(self):
        for name, deck in (("zero curve, VAD 0", _a8_set(lcid=8)),
                           ("zero curve, VAD 2", _a8_set(vad=2, lcid=8)),
                           ("LCID 0", _a8_set(lcid=0)),
                           ("undefined LCID", _a8_set(lcid=99))):
            with self.subTest(name):
                res, st, _e = _convert(deck)
                self.assertIn(("010", "000"),
                              [(r[0], r[1]) for r in _bcs_rows(st)])
                self.assertEqual(_imp_cards(st), [])
                self.assertFalse(_has(res.warnings, _W_A8_SET))

    def test_d_VAD_1_on_a_zero_curve_is_an_imposed_acceleration(self):
        """D11: a zero imposed acceleration keeps the initial velocity, so
        it is not a hold."""
        res, st, _e = _convert(_a8_set(vad=1, lcid=8))
        self.assertEqual([(c[0], c[3], c[10]) for c in _imp_cards(st)],
                         [("/IMPACC", "Y", 1.0)])
        self.assertTrue(_has(res.warnings, _W_A8_SET, "VAD 1"))

    def test_f_RIGID_writes_Fscale_1(self):
        res, st, _e = _convert(a8_rigid_sf0())
        self.assertEqual([(c[0], c[10]) for c in _imp_cards(st)],
                         [("/IMPDISP", 1.0)])
        self.assertTrue(_has(res.warnings, _W_A8_RIGID, "read_impdisp.F:239"))

    def test_g_only_the_kept_holds_are_global_SPC_bits(self):
        """_global_spc_dofs: the imposed row's free node 50 is not a
        global bit (the implicit free-node guard fixes all six of its
        DOFs); the held row's is (the guard writes the remainder only)."""
        r_a, st_a, _e = _convert(_a8_set(implicit=True, free_node=True))
        g_a = _grnod_by_id(st_a)
        guard_a = {(r[0], r[1]): g_a[r[3]][1] for r in _bcs_rows(st_a)
                   if g_a.get(r[3], ("",))[0].startswith("free_reference")}
        self.assertEqual(guard_a, {("111", "111"): [50]})
        r_b, st_b, _e = _convert(_a8_set(lcid=8, implicit=True,
                                         free_node=True))
        g_b = _grnod_by_id(st_b)
        guard_b = {(r[0], r[1]): g_b[r[3]][1] for r in _bcs_rows(st_b)
                   if g_b.get(r[3], ("",))[0].startswith(
                       "fix_free_reference")}
        self.assertEqual(guard_b, {("101", "111"): [50]})

    def test_h_the_screw_drive_writes_Fscale_1(self):
        mod = _t7._screw_synthetic()
        drive = ("*BOUNDARY_PRESCRIBED_MOTION_RIGID_ID\n"
                 + f"{mod.DRIVE_ID:>10}screw drive\n"
                 + _row(mod.PART_A, 5, 2, mod.LCID, 0.0, 0, 1e28, 0.0) + "\n")
        deck = mod.build_deck(drive=False, extra=drive)
        for kw, want in (({}, 1.0),
                         ({"prescribed_motion_sf_default": False}, 0.0)):
            with self.subTest(**kw):
                _r, st, _e = _convert(deck, **kw)
                blk = [b for h, b in _blocks(st, "/IMPVEL/LAGMUL/")]
                self.assertEqual(len(blk), 1, st)
                self.assertEqual(float(blk[0][2][20:40]), want)

    def test_i_the_opt_out_restores_the_386444e_bytes(self):
        r1, st1, _e = _convert(a8_set_ramp(),
                               prescribed_motion_sf_default=False)
        self.assertEqual(_sha(st1), _A8_SET_386444E_SHA)
        self.assertFalse(_has(r1.warnings, _W_A8_SET))
        r2, st2, _e = _convert(a8_rigid_sf0(),
                               prescribed_motion_sf_default=False)
        self.assertEqual(_sha(st2), _A8_RIGID_386444E_SHA)
        self.assertFalse(_has(r2.warnings, _W_A8_RIGID))

    def test_j_a_stated_non_zero_SF_is_untouched(self):
        res, st, _e = _convert(_a8_set(sf=2.0))
        self.assertEqual([(c[0], c[10]) for c in _imp_cards(st)],
                         [("/IMPVEL", 2.0)])
        self.assertFalse(_has(res.warnings, _W_A8_SET))


# ═════════════════════════════════════════════════════════════════════════════
# A9 — a RIGID_LOCAL drive and the CMO -1 /BCS of its body in ONE shared skew
# ═════════════════════════════════════════════════════════════════════════════

def _w1i_nodes() -> str:
    """The 27 nodes of g2g's W1i coupon (a 10 mm cube, 3 x 3 x 3 nodes)."""
    out = ["*NODE"]
    nid = 0
    for k in range(3):
        for j in range(3):
            for i in range(3):
                nid += 1
                out.append(f"{nid:>8}{5.0 * i:>16.6f}{5.0 * j:>16.6f}"
                           f"{5.0 * k:>16.6f}{0:>8}{0:>8}")
    return "\n".join(out) + "\n"


def _w1i(con2: str = "011111", lco: int = 7, dof: int = 1, vad: int = 2,
         implicit: bool = True, extra_cs: str = "", cnrb: bool = False) -> str:
    """g2g's W1i coupon (SCR/r9pre/g2g/coupon_b3/W1i.k), rebuilt: an elastic
    base (part 1, bottom fixed) and a block (part 2) on top, the block a
    *MAT_RIGID CMO -1 body in the *DEFINE_COORDINATE_NODES 7 frame (nodes 10
    / 24 / 25, an oblique frame), its CON2 *con2*, LCO *lco*; a
    *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL drives DOF *dof* (VAD *vad*,
    0 -> 0.01 mm). *cnrb* makes the block deformable and its body a
    *CONSTRAINED_NODAL_RIGID_BODY_SPC 50 (CID 7, CMO -1 CON1 7)."""
    ctrl = ["*CONTROL_TERMINATION", _row(1.0)]
    if implicit:
        ctrl += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 0.1)]
    if cnrb:
        mat2 = ["*MAT_ELASTIC", _row(2, 7.85e-9, 210000.0, 0.3)]
        body = ["*SET_NODE_LIST", _row(60), _row(10, 11, 12, 13, 14, 15, 16,
                                                 17), _row(18, 19, 20, 21, 22,
                                                           23, 24, 25),
                _row(26, 27),
                "*CONSTRAINED_NODAL_RIGID_BODY_SPC", _row(50, 7, 60),
                _row(-1.0, 7, int(con2))]
        pid = 50
    else:
        mat2 = ["*MAT_RIGID", _row(2, 7.85e-9, 210000.0, 0.3),
                f"{-1.0:>10}{7:>10}{con2:>10}", _row(lco)]
        body = []
        pid = 2
    return "\n".join(
        ["*KEYWORD"] + ctrl + [
            "*DEFINE_COORDINATE_NODES", _row(7, 10, 24, 25, 0, "X"),
            extra_cs.rstrip("\n"),
            "*PART", "base", _row(1, 1, 1), "*PART", "block", _row(2, 1, 2),
            "*SECTION_SOLID", _row(1, 1),
            "*MAT_ELASTIC", _row(1, 7.85e-9, 1000.0, 0.3)] + mat2
        + [_w1i_nodes().rstrip("\n"), "*ELEMENT_SOLID"]
        + ["".join(f"{v:>8}" for v in row) for row in (
            (1, 1, 1, 2, 5, 4, 10, 11, 14, 13), (2, 1, 2, 3, 6, 5, 11, 12, 15,
                                                 14),
            (3, 1, 4, 5, 8, 7, 13, 14, 17, 16), (4, 1, 5, 6, 9, 8, 14, 15, 18,
                                                 17),
            (5, 2, 10, 11, 14, 13, 19, 20, 23, 22), (6, 2, 11, 12, 15, 14, 20,
                                                     21, 24, 23),
            (7, 2, 13, 14, 17, 16, 22, 23, 26, 25), (8, 2, 14, 15, 18, 17, 23,
                                                     24, 27, 26))]
        + ["*SET_NODE_LIST", _row(1), _row(1, 2, 3, 4, 5, 6, 7, 8), _row(9),
           "*BOUNDARY_SPC_SET", _row(1, 0, 1, 1, 1, 1, 1, 1),
           "*DEFINE_CURVE", _row(2), f"{0.0:>20}{0.0:>20}",
           f"{1.0:>20}{0.01:>20}"] + body
        + ["*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL",
           _row(pid, dof, vad, 2, 1.0), "*END", ""])


def a9_w1i() -> str:
    return _w1i()


_A9_W1I_386444E_SHA = "286cbf6756803b12a4321e547fa2101b9d37fd8d9e4668d7750aa2b199f2cffa"
_W_A9 = "the drive is written in /SKEW/"
_W_A9_KEPT = "the drive keeps its co-rotating /SKEW/MOV/"


def _imp_skews(starter: str):
    return [c[4] for c in _imp_cards(starter)]


def _bcs_skews(starter: str):
    return sorted({r[2] for r in _bcs_rows(starter) if r[2]})


class RigidLocalSharedSkew(unittest.TestCase):
    """A9 (part-A spec A9): the drive shares the CMO -1 /BCS skew when (a)
    Rot 111, (b) the frames are equal at t 0, (c) no DOF is held and
    driven; one refusal probe per condition.

    STARTER RUNS (nt 4): a9_w1i() default (p_a9w1i_n4): 0 ERROR / 0
    WARNING - no WARNING 312; its 386444e bytes (p_a9w1iOff_n4, the
    pristine checkout): 0 ERROR, WARNING 312 (kinset.F:103-105).

    ENGINE (the W1i coupon, implicit IMFLAG 1, an output-only /TH on block
    node 23; nt 4 AND nt 2, identical to every digit; 9 cycles NORMAL on
    both arms): the block moves u . e1 = 0.0100 mm along the local x' =
    (2, 1, 1) / sqrt 6 at t 1.0 = x1.0000 of the prescribed 0.01 mm, no
    transverse motion, IE 0.54459 = the work of the drive; the 386444e
    bytes (two skews on the main node) move 0.0075 mm = x0.7500, IE
    0.30637 - the frame-dependent wrong displacement behind an energy
    error of 0.0 %.
    """

    def test_1_the_drive_takes_the_BCS_skew(self):
        res, st, _e = _convert(a9_w1i())
        self.assertEqual(_bcs_skews(st), [7])
        self.assertEqual(_imp_skews(st), [7])
        self.assertTrue(re.search(r"^/SKEW/MOV/\d+$", st, re.M))  # inert
        self.assertTrue(_has(res.warnings, _W_A9 + "7", "x0.750 / x-0.5625",
                             "WARNING 312", "--no-rigid-local-shared-skew"))

    def test_2_the_opt_out_restores_the_round_8_bytes(self):
        res, st, _e = _convert(a9_w1i(), rigid_local_shared_skew=False)
        self.assertEqual(_sha(st), _A9_W1I_386444E_SHA)
        self.assertNotEqual(_imp_skews(st), [7])
        self.assertFalse(_has(res.warnings, _W_A9))

    def test_3a_a_free_rotation_keeps_both_skews(self):
        res, st, _e = _convert(_w1i(con2="011110"))
        self.assertNotEqual(_imp_skews(st), [7])
        self.assertTrue(_has(res.warnings, _W_A9_KEPT, "(a)", "Rot 110"))

    def test_3b_LCO_unlike_CON1_shares_only_with_equal_axes(self):
        same = ("*DEFINE_COORDINATE_NODES\n" + _row(9, 10, 24, 25, 0, "X")
                + "\n")
        other = ("*DEFINE_COORDINATE_NODES\n" + _row(8, 10, 11, 13, 0, "X")
                 + "\n")
        r_s, st_s, _e = _convert(_w1i(lco=9, extra_cs=same))
        self.assertEqual(_imp_skews(st_s), [7])
        self.assertTrue(_has(r_s.warnings, _W_A9 + "7"))
        r_o, st_o, _e = _convert(_w1i(lco=8, extra_cs=other))
        self.assertNotEqual(_imp_skews(st_o), [7])
        self.assertTrue(_has(r_o.warnings, _W_A9_KEPT, "(b)"))

    def test_3c_a_held_and_driven_DOF_keeps_both_skews(self):
        res, st, _e = _convert(_w1i(con2="111111"))
        self.assertNotEqual(_imp_skews(st), [7])
        self.assertTrue(_has(res.warnings, _W_A9_KEPT, "(c)", "HOLDS the "
                             "driven DOF X"))

    def test_4_a_CNRB_SPC_body_shares(self):
        res, st, _e = _convert(_w1i(cnrb=True))
        self.assertEqual(_imp_skews(st), [7])
        self.assertTrue(_has(res.warnings, _W_A9 + "7"))

    def test_5_a_VAD_0_drive_shares(self):
        res, st, _e = _convert(_w1i(vad=0))
        self.assertEqual(_imp_skews(st), [7])

    def test_6_an_explicit_twin_follows_the_same_bytes_rule(self):
        res, st, _e = _convert(_w1i(implicit=False))
        self.assertEqual(_imp_skews(st), [7])
        self.assertTrue(_has(res.warnings, _W_A9 + "7"))


# ═════════════════════════════════════════════════════════════════════════════
# The round-9 part-A retractions: no shipped text carries a retracted
# spelling (CHANGELOG, the history, is exempt)
# ═════════════════════════════════════════════════════════════════════════════

#: Part-A statements round 9 measured wrong or superseded. CHANGELOG may quote
#: them (the history); no other shipped text may.
_RETRACTED_ROUND_9_A = (
    # A3 (d): round 8's dT7 figures - measured while the prescribed motion
    # drove the CNRB, so the deck contact carried 0.0 at every TH row
    "304.95",
    "601.76",
    # A3 (b): only the crossing-search filter; the no-tangent facts are
    # imp_int_k.F:111-200 + ind_glob_k.F:4601-4605 + intfop2.F:595
    "imp_int_k.F:847",
    # A3 (c): g2e's residual / tangent mechanism for the one-way
    # pass-through, refuted at source (TTOFF identical; SINT7/2 earlier)
    "residual stiffens",
    "tangent uses a constant",
)

#: (relative path, a replacement that IS shipped there)
_REPLACEMENTS_ROUND_9_A = (
    ("k2rad/writer/contacts.py", "imp_int_k.F:111-200 has no TYPE25 branch; "
     "ind_glob_k.F:4601-4605 prints MESSAGE 232"),
    ("k2rad/cli.py", "can stop early OR end NORMAL with the load path lost"),
    ("README.md", "`imp_int_k.F:111-200` has no TYPE25 branch"),
    ("ROADMAP.md", "**Round 9:** CLOSED by A2 (implicit N2S -> one-way TYPE7 "
     "+ the stub, friction-faithful"),
)


class Round9RetractedStatementsA(unittest.TestCase):
    """No shipped text (README, ROADMAP, the GUI, every package module,
    docs/*.md, tools/*.py; CHANGELOG exempt) carries a retracted part-A
    spelling; the guard fires on each needle split across two adjacent
    literals; a PREFIX still fires; the replacements ARE shipped."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _t7._SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_9_A:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        """The companion: each retracted spelling fed through the same
        normalisation (split across two adjacent literals) is caught."""
        for needle in _RETRACTED_ROUND_9_A:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "')
                        + ' y')
                self.assertIn(_t7._collapse(needle).lower(), _t7._collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_9_A:
            with self.subTest(needle=needle):
                self.assertIn(_t7._collapse(needle[:max(4, len(needle) // 2)]),
                              _t7._collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_t7._SHIPPED_TEXTS())
        for rel, needle in _REPLACEMENTS_ROUND_9_A:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_t7._collapse(needle), texts[key])


if __name__ == "__main__":
    unittest.main()
