"""Tests for the R14 CAMPAIGN TRIAGE batch, round 9 — PART A:

  A1  a *CONSTRAINED_NODAL_RIGID_BODY sharing a *MAT_RIGID part's PID: the
      part-keyed cards drive the PART (LS Warning 10177)
      (default ON, --no-rigid-part-pid-precedence)
  A2  implicit node-to-surface contacts as a one-way /INTER/TYPE7, the stub
      kept and friction-faithful (default ON, --no-implicit-n2s-type7)
  A3  the texts that ride A1 + A2 (no flag)
  A4  implicit rigid-body gravity keeps the rigid parts' own nodes
      (default ON, --no-implicit-rigid-gravity-nodes)
  A5  a rigid-only *SECTION_BEAM ELFORM 7 section from TS1
      (default ON, --no-elform7-beam-thickness-section)
  A6  *BOUNDARY_SPC on a *DEFINE_COORDINATE_VECTOR CID in that frame
      (default ON, --no-spc-vector-frames)
  A7  a refused *MAT_ACOUSTIC part becomes /MAT/VOID on a modal deck
      (default ON, --no-modal-acoustic-void)
  A8  a stated SF 0.0 on *BOUNDARY_PRESCRIBED_MOTION_* is the default 1.0
      (default ON, --no-prescribed-motion-sf-default)
  A9  a RIGID_LOCAL drive shares its body's CMO -1 /BCS skew
      (default ON, --no-rigid-local-shared-skew)
  A10 Igap 3 + half the thinnest shell on a mixed shell + solid main
      (OPT-IN, --mixed-main-thickness-gap)
  A11 --arclength-riks writes no /IMPL/QSTAT unless --qstat-dtscal is given
  A13 the records: the CNRB _SPC opt-out frame, the wiring, the ROADMAP /
      CHANGELOG records and the retraction guards

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_1.py / _4.py / _7.py
/ _8.py, test_gravity.py and test_motion_load_variants.py as MODULES
(functions, deck constants and the two wiring base classes, which T9
subclasses; no earlier TestCase is bound in this namespace, so none runs
twice).

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

    def test_a3_the_stub_sentence_follows_the_stub(self):
        """The fix round (F-A2-1): the routed warning said 'The all-parts
        implicit stub stays beside it' on every deck, but the stub is
        injected only into an implicit deck WITHOUT a contact of its own -
        beside an AUTOMATIC_SINGLE_SURFACE or a TIED contact no stub is
        written. The sentence now says which; the injected case keeps the
        round-9 wording (doorbeam's sentence unchanged)."""
        ss = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID\n" + _row(77) + "\n"
              + _row(1, 0, 3, 0) + "\n" + _row(0.1, 0.0, 0.0, 0.0, 0.0)
              + "\n" + _row() + "\n")
        tied = ("*SET_NODE_LIST\n" + _row(6) + "\n" + _row(4, 5) + "\n"
                "*CONTACT_TIED_NODES_TO_SURFACE_ID\n" + _row(88) + "\n"
                + _row(6, 1, 4, 3) + "\n" + _row() + "\n" + _row() + "\n")
        res, st, _e = _convert(a2_plain_implicit())
        self.assertIn(_STUB_TITLE, st)
        self.assertTrue(_has(res.warnings, _W_A2 + "78", "The all-parts "
                             "implicit stub stays beside it."))
        for name, extra, fam in (("single", ss, "single-surface"),
                                 ("tied", tied, "tied")):
            with self.subTest(name):
                r2, st2, _e = _convert(_shell_plate(_IMPL1,
                                                    _SET5 + _n2s() + extra))
                self.assertNotIn(_STUB_TITLE, st2)
                self.assertIn("/INTER/TYPE7/78", st2)
                hits = [w for w in r2.warnings if _W_A2 + "78" in w]
                self.assertEqual(len(hits), 1, r2.warnings)
                self.assertNotIn("stub stays beside it", hits[0])
                self.assertIn("NO all-parts implicit stub is written beside "
                              "it: k2rad injects the stub only into an "
                              "implicit deck without a contact of its own, "
                              f"and this deck has {fam} contact(s)", hits[0])

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
        # the fix round (F-A4-1 + the solver-physics wording): the mechanism
        # is cited, not 'unlocated', and the step dependence is named
        self.assertTrue(_has(res.warnings, _W_A4,
                             "gravit_imp.F:84-91 weighs an active rigid "
                             "body's main node with RBY(15)",
                             "inirby.F:836-837", "within 0.7 % at ex_16's "
                             "dtmax 1e-4 s", "13-14 % short at the fifths"))
        self.assertFalse(_has(res.warnings, "not located"))
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
                # the fix round (F-A5-1): gravity DOES load ex_16's wall
                # (*LOAD_BODY_Y on every part); its sag is what is inert
                self.assertTrue(_has(res.warnings, _W_A5, "gravity sags it "
                                     "by m g / k = 4.4e-10 mm"))
                self.assertFalse(_has(res.warnings, "nothing else loads"))
                self.assertFalse(_has(res.warnings, _REFUSAL))

    def test_the_cell_text_is_k2rads_float_format(self):
        _r, st, _e = _convert(a5_rigid_wall())
        row = [b for h, b in _blocks(st, "/PROP/BEAM/")][0][3]
        self.assertEqual(row, "                 0.1        8.333333E-05"
                              "        8.333333E-05     0.0001666666667")

    def test_a_deformable_member_and_ELFORM_8_keep_the_refusal(self):
        # the fix round (F5): ONE section shared by the rigid wall and a
        # deformable *MAT_ELASTIC member keeps the refusal too - an
        # all() -> any() mutant gave the deformable member the TS1 section
        # and survived the round-9 suite. STARTER (nt 4,
        # rcv_r9i_fixpr_a5mixed): ERRORs 274 / 275 / 314-317, the named
        # refusal.
        mixed = _a5_deck().replace(
            "*SECTION_BEAM", "*PART\nbeam deformable\n" + _row(8, 5, 10)
            + "\n*SECTION_BEAM", 1).replace(
            "*END", "*MAT_ELASTIC\n" + _row(10, 7.85e-9, 210000.0, 0.3)
            + "\n*NODE\n" + f"{4:>8}{50.8:>16}{0.0:>16}{0.0:>16}"
            + "\n*ELEMENT_BEAM\n" + "".join(f"{v:>8}" for v in (2, 8, 2, 4, 3))
            + "\n*END", 1)
        for deck in (_a5_deck(mat="elastic"), _a5_deck(elform=8), mixed):
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

    def test_3d_an_anti_parallel_frame_keeps_both_skews(self):
        """The fix round's F1: LCO 9 = CON1 7 turned 180 degrees about z'
        (x'' = -x', y'' = -y', z'' = z') passed the round-9 |e . e'| test and
        the drive went into /SKEW/7 with 'the frames are equal at t 0' -
        measured -0.0100 mm for the prescribed +0.01 mm (implicit, nt 4,
        9 cycles NORMAL; the 386444e bytes +0.0075). The SIGNED test keeps
        the two skews and names condition (b); the LCO = CON1 control and
        test_3b's equal-axes frame still share."""
        rot180 = ("*DEFINE_COORDINATE_SYSTEM\n"
                  + _row(9, 0.0, 0.0, 5.0, -2.0, -1.0, 4.0, 0) + "\n"
                  + _row(5.0, -7.5, 2.5) + "\n")
        res, st, _e = _convert(_w1i(lco=9, extra_cs=rot180))
        self.assertNotEqual(_imp_skews(st), [7])
        self.assertFalse(_has(res.warnings, _W_A9))
        self.assertTrue(_has(res.warnings, _W_A9_KEPT, "(b) the drive's "
                             "frame at t 0 is not the /BCS"))
        r_c, st_c, _e = _convert(_w1i(lco=7))
        self.assertEqual(_imp_skews(st_c), [7])
        self.assertTrue(_has(r_c.warnings, _W_A9 + "7"))

    def test_6_an_explicit_twin_keeps_the_386444e_bytes(self):
        """Decision A9 'explicit unchanged' (the fix round re-derived this
        test from the round-9 'follows the same bytes rule'): on an explicit
        deck the two skews impose the motion exactly (an explicit two-card
        coupon with a step-setting shell: x1.0000 in both arms, 665
        cycles, nt 4), so the rule is gated on /IMPL and the explicit twin
        converts as with --no-rigid-local-shared-skew."""
        res, st, eng = _convert(_w1i(implicit=False))
        self.assertNotEqual(_imp_skews(st), [7])
        self.assertFalse(_has(res.warnings, _W_A9))
        self.assertFalse(_has(res.warnings, _W_A9_KEPT))
        r_off, st_off, eng_off = _convert(_w1i(implicit=False),
                                          rigid_local_shared_skew=False)
        self.assertEqual((st, eng), (st_off, eng_off))
        self.assertEqual(res.warnings, r_off.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# A7 — a refused *MAT_ACOUSTIC part becomes /MAT/VOID on the modal recipe only
# ═════════════════════════════════════════════════════════════════════════════

import test_r14_triage_1 as _t1  # noqa: E402

_A7_EIGEN = "*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(10) + "\n"
# A second (elastic) brick on top of T1's unit brick, sharing its face 5-6-7-8.
_A7_BRICK2 = """*NODE
         9             0.0             0.0             2.0
        10             1.0             0.0             2.0
        11             1.0             1.0             2.0
        12             0.0             1.0             2.0
*ELEMENT_SOLID
       2       2       5       6       7       8       9      10      11      12
"""


def _a7_deck(modal: bool = True, nrf=(), second: bool = False,
             kw: str = "*MAT_ACOUSTIC", extra: str = "") -> str:
    """T1:919-969's *MAT_ACOUSTIC deck (RefusedMaterialTests._deck: one unit
    brick, part 1, RO 1.0E-9) - *modal* adds *CONTROL_IMPLICIT_EIGENVALUE
    NEIG 10; *second* an elastic brick (part 2) sharing the face 5-6-7-8;
    *nrf* the segments of a *SET_SEGMENT 5 named by a
    *BOUNDARY_NON_REFLECTING."""
    out = ["*KEYWORD\n", "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"]
    if modal:
        out.append(_A7_EIGEN)
    out += [_t1._BRICK, "*PART\np1\n" + _row(1, 1, 1) + "\n",
            "*SECTION_SOLID\n" + _row(1, 1) + "\n",
            kw + "\n" + _row(1, "1.0E-9", 1500.0, 0.0, 0.0) + "\n"]
    if second:
        out += [_A7_BRICK2, "*PART\np2\n" + _row(2, 1, 2) + "\n",
                "*MAT_ELASTIC\n" + _row(2, "7.85E-9", 210000.0, 0.3) + "\n"]
    if nrf:
        out += ["*SET_SEGMENT\n" + _row(5) + "\n"
                + "".join(_row(*s) + "\n" for s in nrf),
                "*BOUNDARY_NON_REFLECTING\n" + _row(5) + "\n"]
    out += [extra, "*END\n"]
    return "".join(out)


def a7_modal_twin() -> str:
    return _a7_deck()


def a7_modal_nrf() -> str:
    """The modal twin with a *BOUNDARY_NON_REFLECTING on the void's y = 0
    face (nodes 1-2-6-5)."""
    return _a7_deck(nrf=[(1, 2, 6, 5)])


def a7_modal_nrf_mixed() -> str:
    """Two bricks; the segment set holds the void's y = 0 face AND the
    elastic brick's top face (9-10-11-12)."""
    return _a7_deck(nrf=[(1, 2, 6, 5), (9, 10, 11, 12)], second=True)


def a7_time_domain_nrf() -> str:
    """T1's time-domain deck with the same *BOUNDARY_NON_REFLECTING."""
    return _a7_deck(modal=False, nrf=[(1, 2, 6, 5)])


_A7_TWIN_386444E_SHA = "13c7fbe9a85c5a769d2a85eb89a7574fdb8c55ae34a619bb0d9f27f7cf26fc48"
_A7_TIME_DOMAIN_386444E_SHA = ("aad2ecfc4ac8607daef2244c890926b1"
                               "84546ea65d5f79c71c7380a216548d5b")
_W_A7 = "on a MODAL deck: written as /MAT/VOID/"
_W_REFUSED = "is REFUSED BY NAME"


def _void_block(starter: str, mid: int):
    """``(title, (RHO_I, E, nu))`` of /MAT/VOID/<mid>, None when absent."""
    for head, body in _blocks(starter, f"/MAT/VOID/{mid}"):
        if head == f"/MAT/VOID/{mid}":
            row = body[1]
            return body[0], tuple(float(row[i:i + 20] or 0)
                                  for i in (0, 20, 40))
    return None


def _surf_rows(starter: str, surf_id: int):
    for head, body in _blocks(starter, f"/SURF/SEG/{surf_id}"):
        if head == f"/SURF/SEG/{surf_id}":
            return [[int(t) for t in ln.split()][1:] for ln in body[1:]]
    return None


class ModalAcousticVoid(unittest.TestCase):
    """A7 (part-A spec A7): on a MODAL deck a *PART on a refused
    *MAT_ACOUSTIC is written /MAT/VOID/<mid> with RHO_I = RO, E 0, nu 0; a
    time-domain deck keeps the refusal (T1:919-969 still asserts it); an
    /EBCS on the void's faces goes (iniebcs.F:428-441, ERROR 1602).

    STARTER RUNS (nt 4): a7_modal_twin() default (p_a7twin_n4): 0 ERROR /
    0 WARNING; its 386444e bytes (p_a7twinOff_n4): ERROR 179 + 760;
    a7_modal_nrf() (p_a7nrf_n4, the /EBCS dropped): 0 ERROR / 0 WARNING;
    a7_modal_nrf_mixed() (p_a7mix_n4): ERROR 1602 - the KEPT segment on the
    elastic brick, the starter's own refusal of an EBCS outside the ALE /
    Euler framework, i.e. the reason the void's segments are dropped;
    a7_time_domain_nrf() = the 386444e bytes (p_a7td_n4): ERROR 179 + 760 +
    1602.

    ENGINE: 9.3.ssd_acoustic_box (nvh/example-09-03, mid 1, RO 1.22E-12;
    branch _0000.rad sha256 436267e4dfa6 = the part-A spec's void arm):
    386444e ERROR 179 + 760; the void 0 ERROR / 1 WARNING (1084, the shell
    property), NORMAL TERMINATION in 2 cycles at nt 4 AND nt 2, the
    exported stiffness byte-identical at both (2346 DOFs on the 402 shell
    nodes of 726). Starter TOTAL MASS 0.2818 = the shells' 0.2808 + the
    0.001 probe body: the Isolid-17 void bricks get no mass
    (inivoid.F:254).
    """

    def test_a_the_modal_twin_writes_the_void_with_RO(self):
        res, st, _e = _convert(a7_modal_twin())
        self.assertEqual(_void_block(st, 1),
                         ("ACOUSTIC_VOID_1", (1.0e-9, 0.0, 0.0)))
        self.assertTrue(_has(res.warnings, "*MAT_ACOUSTIC 1 (part(s) [1]) "
                             + _W_A7 + "1", "RHO_I = 1e-09 (E 0, nu 0)",
                             "STRUCTURE's alone", "inivoid.F:254",
                             "ERROR 179", "IE RMS 168.69 %",
                             "--no-modal-acoustic-void"))
        # the fix round (F-A7-1): the 8.3 void arm's energy does NOT decay
        # (the census: 'the LS energy decays to zero, the OR energy does
        # not') - the void removes the radiation sink, it absorbs nothing
        self.assertTrue(_has(res.warnings, _W_A7 + "1", "carries no wave "
                             "and removes the fluid's radiation sink"))
        self.assertFalse(_has(res.warnings, "absorbs the wave"))
        self.assertFalse(_has(res.warnings, _W_REFUSED))
        self.assertFalse(_has(res.warnings, "reference a material id that "
                              "NO /MAT"))
        self.assertNotIn("MAT_ACOUSTIC",
                         [k for k, _ in res.recognized_not_emitted])
        self.assertNotIn("/EBCS", st)

    def test_b_the_card_title_and_the_numeric_alias(self):
        _r, st, _e = _convert(_a7_deck(kw="*MAT_ACOUSTIC_TITLE\nair"))
        self.assertEqual(_void_block(st, 1), ("air", (1.0e-9, 0.0, 0.0)))
        res, st9, _e = _convert(_a7_deck(kw="*MAT_090"))
        self.assertEqual(_void_block(st9, 1),
                         ("ACOUSTIC_VOID_1", (1.0e-9, 0.0, 0.0)))
        self.assertTrue(_has(res.warnings, "*MAT_090 1 (part(s) [1]) "
                             + _W_A7 + "1"))

    def test_c_the_opt_out_restores_the_386444e_bytes(self):
        res, st, _e = _convert(a7_modal_twin(), modal_acoustic_void=False)
        self.assertEqual(_sha(st), _A7_TWIN_386444E_SHA)
        self.assertIsNone(_void_block(st, 1))
        self.assertTrue(_has(res.warnings, "*MAT_ACOUSTIC 1:", _W_REFUSED))
        self.assertIn("MAT_ACOUSTIC",
                      [k for k, _ in res.recognized_not_emitted])

    def test_d_a_time_domain_deck_keeps_the_refusal_and_its_EBCS(self):
        res, st, _e = _convert(a7_time_domain_nrf())
        self.assertEqual(_sha(st), _A7_TIME_DOMAIN_386444E_SHA)
        self.assertIsNone(_void_block(st, 1))
        self.assertTrue(re.search(r"^/EBCS/NRF/\d+$", st, re.M))
        self.assertTrue(_has(res.warnings, "*MAT_ACOUSTIC 1:", _W_REFUSED))
        self.assertFalse(_has(res.warnings, _W_A7))

    def test_e_the_modal_route_drops_the_EBCS_on_the_void_faces(self):
        res, st, _e = _convert(a7_modal_nrf())
        self.assertIsNotNone(_void_block(st, 1))
        self.assertNotIn("/EBCS", st)
        self.assertNotIn("/SURF/SEG/", st)
        self.assertTrue(_has(res.warnings, "nsid=5: 1 of 1 segment(s)",
                             "part(s) [1]", "iniebcs.F:428-441",
                             "ERROR 1602", "the /EBCS/NRF is DROPPED"))

    def test_f_a_mixed_segment_set_keeps_its_other_segments(self):
        res, st, _e = _convert(a7_modal_nrf_mixed())
        ebcs = _blocks(st, "/EBCS/NRF/")
        self.assertEqual(len(ebcs), 1)
        surf = int(ebcs[0][1][1].split()[0])
        self.assertEqual(_surf_rows(st, surf), [[9, 10, 11, 12]])
        self.assertTrue(_has(res.warnings, "nsid=5: 1 of 2 segment(s)",
                             "keeps the other 1"))

    def test_g_an_acoustic_mid_no_part_uses_stays_refused(self):
        spare = "*MAT_ACOUSTIC\n" + _row(9, "1.0E-9", 1500.0) + "\n"
        res, st, _e = _convert(_a7_deck(extra=spare))
        self.assertIsNotNone(_void_block(st, 1))
        self.assertIsNone(_void_block(st, 9))
        self.assertTrue(_has(res.warnings, "*MAT_ACOUSTIC 9:", _W_REFUSED,
                             "No /PART names this material"))
        # the note stays while a refused mid of the spelling is left
        self.assertIn("MAT_ACOUSTIC",
                      [k for k, _ in res.recognized_not_emitted])


# ═════════════════════════════════════════════════════════════════════════════
# A10 - OPT-IN --mixed-main-thickness-gap: Igap 3 + Gapmin = t_min / 2 on an
#       AUTOMATIC contact's mixed shell + solid main
# ═════════════════════════════════════════════════════════════════════════════

def _a10_single(sst: float = 0.0) -> str:
    """gapc07.k's contact: AUTOMATIC_SINGLE_SURFACE over part set 1."""
    return "\n".join([
        "*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID", _row(1) + "gap coupon contact",
        _row(1, 0, 2, 0, 0, 0, 0, 0),
        _row(0.0, 0.0, 0.0, 0.0, 20.0, 0, 0.0, "1E+17"),
        _row(1.0, 1.0, sst, 0.0, 1.0, 1.0, 1.0, 1.0)])


def _a10_gapc(zmid: float = 0.7, block_h: float = 2.0, t: float = 1.0,
              t_b: float = 0.0, contact: str = "", sst: float = 0.0,
              extra: str = "", implicit: bool = False,
              optt: float = 0.0) -> str:
    """g3i's gap coupon (R9P/g3i/coupon/gapc07.k / gapc10.k rebuilt): a
    10 x 10 solid block (part 1, z from -block_h to 0, 2 x 2 hexes) and a
    shell plate (part 2, thickness t, 2 x 2 shells at z = zmid; *t_b*
    gives the second row of shells its own *ELEMENT_SHELL_THICKNESS; *optt*
    makes the plate a *PART_CONTACT with that OPTT), the block fixed, the
    plate driven down at 100 mm/s, one AUTOMATIC_SINGLE_SURFACE over the
    part set {1, 2} (or *contact*)."""
    nodes = []
    nid = 1
    for z in (-block_h, 0.0, zmid):
        for y in (0.0, 5.0, 10.0):
            for x in (0.0, 5.0, 10.0):
                nodes.append(f"{nid:>8}{x:>16.6f}{y:>16.6f}{z:>16.6f}"
                             f"{0:>8}{0:>8}")
                nid += 1
    hexes = [(1, 2, 5, 4, 10, 11, 14, 13), (2, 3, 6, 5, 11, 12, 15, 14),
             (4, 5, 8, 7, 13, 14, 17, 16), (5, 6, 9, 8, 14, 15, 18, 17)]
    quads = [(19, 20, 23, 22), (20, 21, 24, 23), (22, 23, 26, 25),
             (23, 24, 27, 26)]
    shells = [f"{5 + k:>8}{2:>8}" + "".join(f"{n:>8}" for n in q)
              for k, q in enumerate(quads)]
    out = ["*KEYWORD", "*TITLE", f"gap coupon zmid {zmid:g}",
           "*CONTROL_TERMINATION", _row(0.01, 0, 0.0, 0.0, 0.0, 0)]
    if implicit:
        out += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 1.0e-3)]
    out += ["*CONTROL_CONTACT", _row(0.1, 1.0, 2, 0, 1, 0, 1, 0),
            _row(0, 0, 0, 0, 4.0, 0, 0, 0),
            _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            _row(2, 0, 0, 1, 2, 1, 0.0, 0),
            "*DATABASE_GLSTAT", _row(0.00005, 0, 0, 1), "*NODE"] + nodes
    out += ["*PART", "block", _row(1, 1, 1, 0, 0, 0, 0, 0),
            "*SECTION_SOLID", _row(1, 1, 0),
            "*MAT_ELASTIC", _row(1, "7.85E-09", 210000.0, 0.3),
            "*PART_CONTACT" if optt else "*PART", "plate",
            _row(2, 2, 2, 0, 0, 0, 0, 0),
            _row(0.0, 0.0, 0.0, 0.0, optt, 0.0, 0.0, 0) if optt else "",
            "*SECTION_SHELL", _row(2, 16, 1.0, 5, 1, 0, 0, 1),
            _row(t, t, t, t, 0.0, 0.0, 0.0, 0),
            "*MAT_ELASTIC", _row(2, "7.85E-09", 210000.0, 0.3),
            "*ELEMENT_SOLID"]
    out += [f"{k + 1:>8}{1:>8}" + "".join(f"{n:>8}" for n in h)
            for k, h in enumerate(hexes)]
    if t_b:
        out.append("*ELEMENT_SHELL_THICKNESS")
        for k, s in enumerate(shells):
            tk = t_b if k >= 2 else t
            out += [s, _row(tk, tk, tk, tk)]
    else:
        out += ["*ELEMENT_SHELL"] + shells
    out += ["*SET_NODE_LIST", _row(1), _row(*range(1, 9)), _row(9),
            "*SET_NODE_LIST", _row(2), _row(*range(19, 27)), _row(27),
            "*BOUNDARY_SPC_SET", _row(1, 0, 1, 1, 1, 1, 1, 1),
            "*BOUNDARY_SPC_SET", _row(2, 0, 1, 1, 0, 1, 1, 1),
            "*BOUNDARY_PRESCRIBED_MOTION_SET",
            _row(2, 3, 0, 1, -100.0, 0, 0.0, 0.0),
            "*DEFINE_CURVE", _row(1), f"{0.0:>20}{1.0:>20}",
            f"{1.0:>20}{1.0:>20}",
            "*SET_PART_LIST", _row(1), _row(1, 2),
            contact.rstrip("\n") or _a10_single(sst), extra.rstrip("\n"),
            "*END"]
    return "\n".join(ln for ln in out if ln) + "\n"


def a10_gapc07() -> str:
    return _a10_gapc()


def _type7_igap_gapmin(starter: str, iid: int):
    """``(Igap, Gapmin)`` of /INTER/TYPE7/<iid> (None when absent)."""
    for head, body in _blocks(starter, f"/INTER/TYPE7/{iid}"):
        if head == f"/INTER/TYPE7/{iid}":
            return int(body[1][40:50]), float(body[4][40:60] or 0)
    return None


_A10_GAPC07_386444E_SHA = ("16463ded4b0419b724285dc45e82abc8"
                           "18cffeb08388ec0d76a9b2e903ea9802")
_W_A10 = "--mixed-main-thickness-gap: the main mixes shells and solids"
_ON = {"mixed_main_thickness_gap": True}


class MixedMainThicknessGap(unittest.TestCase):
    """A10 (part-A spec A10.1; OPT-IN, D1): with the flag an AUTOMATIC
    contact's /INTER/TYPE7 whose main mixes shells and solids, with no gap
    stated or derived, gets Igap 3 + Gapmin = min(t_min / 2, half the
    smallest main side); without it the 386444e bytes.

    STARTER RUNS (nt 4): a10_gapc07() with the flag (p_a10on_n4): 0 ERROR,
    no WARNING 343 - 0 initial penetrations; without it = the 386444e
    bytes (p_a10off_n4): 0 ERROR, WARNING 343 "THERE ARE 48 INITIAL
    PENETRATIONS (CONCERNING 18 NODES)" - the plate 0.7 inside the
    starter's constant default gap (the coupon is gapc07.k rebuilt: its
    comment lines and *DATABASE_RCFORC dropped).

    The carriers under the flag (convert only): mainboltaexpl's
    /INTER/TYPE7/10001 Igap 0 -> 3, Gapmin 0 -> 0.5 (_0000.rad sha256
    e72ecb94f505 = the part-A gate's variant H, whose engine run is the
    W-A10 record), EXP_SC_PRELOAD's /INTER/TYPE7/1 Gapmin 0.2.
    """

    def test_a_the_coupon_gets_Igap_3_and_half_the_shell(self):
        res, st, _e = _convert(a10_gapc07(), **_ON)
        self.assertEqual(_type7_igap_gapmin(st, 1), (3, 0.5))
        self.assertTrue(_has(res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE"
                             " 1: " + _W_A10, "Gapmin 0.5 = half the "
                             "thinnest main shell (1)", "i7sti3.F:1055-1066",
                             "2916 -> 7557", "1758.5", "not a default"))

    def test_a2_the_default_is_the_386444e_bytes(self):
        res, st, _e = _convert(a10_gapc07())
        self.assertEqual(_sha(st), _A10_GAPC07_386444E_SHA)
        self.assertEqual(_type7_igap_gapmin(st, 1), (0, 0.0))
        self.assertFalse(_has(res.warnings, _W_A10))

    def test_b_two_thicknesses_take_the_thinner_and_OPTT_wins(self):
        _r, st, _e = _convert(_a10_gapc(t_b=0.6), **_ON)
        self.assertEqual(_type7_igap_gapmin(st, 1), (3, 0.3))
        _r2, st2, _e = _convert(_a10_gapc(optt=0.8), **_ON)
        self.assertEqual(_type7_igap_gapmin(st2, 1), (3, 0.4))

    def test_c_the_edge_cap(self):
        res, st, _e = _convert(_a10_gapc(block_h=0.4), **_ON)
        self.assertEqual(_type7_igap_gapmin(st, 1), (3, 0.2))
        self.assertTrue(_has(res.warnings, _W_A10, "capped at half the "
                             "smallest main edge 0.4"))

    def test_d_a_solid_only_main_keeps_the_shell_offset(self):
        s2s = "\n".join([
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID", _row(1) + "s2s",
            _row(2, 1, 3, 3, 0, 0, 0, 0),
            _row(0.0, 0.0, 0.0, 0.0, 20.0, 0, 0.0, "1E+17"),
            _row(1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)])
        res, st, _e = _convert(_a10_gapc(contact=s2s), **_ON)
        self.assertEqual(_type7_igap_gapmin(st, 1), (0, 0.5))
        self.assertFalse(_has(res.warnings, _W_A10))

    def test_e_the_refusals(self):
        cases = {
            "SST stated": (_a10_gapc(sst=0.3), {}),
            "--inter-gapmin": (a10_gapc07(), {"inter_gapmin": {1: 0.25}}),
            "non-AUTOMATIC": (_a10_gapc(contact=_a10_single().replace(
                "AUTOMATIC_SINGLE_SURFACE", "SINGLE_SURFACE")), {}),
        }
        for name, (deck, kw) in cases.items():
            with self.subTest(name):
                res, st, _e = _convert(deck, **_ON, **kw)
                self.assertNotEqual(_type7_igap_gapmin(st, 1)[0], 3)
                self.assertFalse(_has(res.warnings, _W_A10))

    def test_d2_a_shell_only_main_stands_down(self):
        """The fix round (F6): the single surface over a part set holding
        ONLY the shell plate - a shell-only main has no solid face, so the
        rule stands down (Igap 0, the starter default, no sentence);
        dropping 'faces' from the mixed test gave (3, 0.5) with the false
        'the main mixes shells and solids' and survived the round-9
        suite. STARTER (nt 4, rcv_r9i_fixpr_a10shell, flag on): 0
        ERROR(S) / 2 WARNING(S) (1084)."""
        contact = "\n".join([
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID",
            _row(1) + "shell-only main",
            _row(3, 0, 2, 0, 0, 0, 0, 0),
            _row(0.0, 0.0, 0.0, 0.0, 20.0, 0, 0.0, "1E+17"),
            _row(1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)])
        deck = _a10_gapc(contact=contact,
                         extra="*SET_PART_LIST\n" + _row(3) + "\n" + _row(2))
        res, st, _e = _convert(deck, **_ON)
        self.assertEqual(_type7_igap_gapmin(st, 1), (0, 0.0))
        self.assertFalse(_has(res.warnings, _W_A10))
        _r0, st0, _e0 = _convert(deck)
        self.assertEqual(st, st0)

    def test_e2_the_implicit_stub_is_never_reached(self):
        """An implicit coupon with no contact card gets k2rad's all-parts
        stub - a mixed main - which the rule must leave alone."""
        res, st, _e = _convert(_a10_gapc(implicit=True,
                                         contact="*DATABASE_BNDOUT\n"
                                         + _row(1.0e-4)), **_ON)
        self.assertIn("auto_implicit_stabilization_self_contact", st)
        self.assertNotIn("  3                   0         2", st)
        self.assertFalse(_has(res.warnings, _W_A10))

    def test_f_a_MORTAR_spelling_is_reached(self):
        mortar = _a10_single().replace("SINGLE_SURFACE_ID",
                                       "SINGLE_SURFACE_MORTAR_ID")
        res, st, _e = _convert(_a10_gapc(contact=mortar), **_ON)
        self.assertEqual(_type7_igap_gapmin(st, 1), (3, 0.5))


# ═════════════════════════════════════════════════════════════════════════════
# A11 - --arclength-riks implies no /IMPL/QSTAT unless --qstat-dtscal is given
# ═════════════════════════════════════════════════════════════════════════════

import test_r14_triage_4 as _t4  # noqa: E402


def a11_riks_deck() -> str:
    """T4's quasi-static implicit brick with NSOLVR 6 (ex_07's arc-length
    request)."""
    return _t4._implicit_deck(nsolvr=6)


def _qstat(engine: str):
    m = re.search(r"^/IMPL/QSTAT/DTSCAL\n(.*)$", engine, re.M)
    return m.group(1).strip() if m else None


class ArclengthRiksNoQstat(unittest.TestCase):
    """A11 (part-A spec A11; inside the existing opt-in, 0 default bytes):
    --arclength-riks writes /IMPL/DT/3 and NO /IMPL/QSTAT unless
    --qstat-dtscal was GIVEN (qstat_dtscal_stated); without the flag QSTAT
    10 as before. MEASURED on the branch bytes (ex_07 under the flag = the
    386444e flag bytes with the QSTAT card removed, engine file sha256
    9219da82fbb6), five runs of identical bytes: NORMAL 1206 / 1192 cycles
    at nt 4 and 1202 / 1202 at nt 2, ERROR once at nt 4 (MESSAGE 79 at
    cycle 1421, the load factor back at 0); the converged load factor down
    to -0.4412 on every run (LS-DYNA's glstat path turns once, at 0.3745,
    and never goes below 0). ex_05: MESSAGE 79 at load factor 0.8548 (nt 4)
    / 0.8698 (nt 2).
    """

    def test_a_the_flag_drops_the_QSTAT_card(self):
        res, _s, engine = _convert(a11_riks_deck(), arclength_riks=True)
        self.assertIn("/IMPL/DT/3", engine)
        self.assertIsNone(_qstat(engine))
        self.assertTrue(_has(res.warnings, "--arclength-riks was passed: "
                             "/IMPL/DT/3 replaces /IMPL/DT/2 and NO "
                             "/IMPL/QSTAT card is written",
                             "negative load factors", "4 of 5", "UNMATCHED",
                             "pass --qstat-dtscal to keep one"))

    def test_b_a_stated_value_keeps_the_card(self):
        res, _s, engine = _convert(a11_riks_deck(), arclength_riks=True,
                                   qstat_dtscal=10.0,
                                   qstat_dtscal_stated=True)
        self.assertEqual(_qstat(engine), "10")
        self.assertTrue(_has(res.warnings, "the /IMPL/QSTAT card "
                             "--qstat-dtscal asked for is kept"))

    def test_c_without_the_flag_QSTAT_10_as_before(self):
        res, _s, engine = _convert(a11_riks_deck())
        self.assertNotIn("/IMPL/DT/3", engine)
        self.assertEqual(_qstat(engine), "10")
        self.assertTrue(_has(res.warnings, "It is NOT emitted",
                             "Pass --arclength-riks to emit it"))

    def test_d_the_flag_on_a_deck_that_asks_for_nothing_keeps_QSTAT(self):
        _r, _s, engine = _convert(_t4._implicit_deck(nsolvr=2),
                                  arclength_riks=True)
        self.assertEqual(_qstat(engine), "10")

    def test_e_the_recipe_keeps_its_0_05(self):
        """T4's deformable/deformable two-brick deck + NSOLVR 6: the recipe
        branch is evaluated first and keeps 0.05 under the flag too."""
        gen = "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
        base = _t4.QstatDtscalRecipeStillWinsTests._DEFDEF
        self.assertIn(gen, base)
        deck = base.replace(gen, gen + "*CONTROL_IMPLICIT_SOLUTION\n"
                            + _row(6, 0, 0, 0, 0, 0, 0, 0) + "\n"
                            + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n"
                            + _row(0, 1, 0.0, 1, 2, 0, 0, 0) + "\n")
        _r, _s, engine = _convert(deck, arclength_riks=True,
                                  deformable_contact_recipe=True)
        self.assertIn("/IMPL/DT/3", engine)
        self.assertEqual(_qstat(engine), "0.05")

    def test_f_the_cli_records_whether_the_value_was_given(self):
        from k2rad import cli
        p = cli.build_parser()
        cases = {
            ("m.k",): False,
            ("m.k", "--arclength-riks"): False,
            ("m.k", "--arclength-riks", "--qstat-dtscal", "10"): True,
            ("m.k", "--qstat-dtscal", "none"): True,
        }
        for argv, stated in cases.items():
            with self.subTest(argv=argv):
                args = p.parse_args(list(argv))
                self.assertIs(args.qstat_dtscal_stated, stated)
        self.assertEqual(p.parse_args(["m.k"]).qstat_dtscal, 10.0)

    def test_g_the_three_defaults_agree_and_the_gui_states_a_filled_box(self):
        import inspect
        import os
        import tempfile
        import k2rad_gui
        from k2rad import cli, convert
        from k2rad.state import ConvertOptions
        self.assertIs(ConvertOptions().qstat_dtscal_stated, False)
        self.assertIs(inspect.signature(convert).parameters[
            "qstat_dtscal_stated"].default, False)
        self.assertIs(cli.build_parser().parse_args(["m.k"])
                      .qstat_dtscal_stated, False)
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "a.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        base = dict(ground_springs=False, ground_spring_k_text="",
                    soften_stfac_text="")
        kw = k2rad_gui.build_convert_kwargs(path, "", ("Mg", "mm", "s"),
                                            **base, qstat_dtscal_text="10")
        self.assertIs(kw["qstat_dtscal_stated"], True)
        kw0 = k2rad_gui.build_convert_kwargs(path, "", ("Mg", "mm", "s"),
                                             **base)
        self.assertNotIn("qstat_dtscal_stated", kw0)
        tmp.cleanup()


# ═════════════════════════════════════════════════════════════════════════════
# A12 - OPT-IN --implicit-bfgs: /IMPL/NONLIN/2 without /IMPL/QSTAT on an
#       NSOLVR 12 (or blank) deck
# ═════════════════════════════════════════════════════════════════════════════

def _nonlin(engine: str):
    m = re.search(r"^/IMPL/NONLIN/(\d+)$", engine, re.M)
    return int(m.group(1)) if m else None


def _no_solution_card(deck: str) -> str:
    """T4's implicit deck with its *CONTROL_IMPLICIT_SOLUTION removed."""
    lines = deck.split("\n")
    k = lines.index("*CONTROL_IMPLICIT_SOLUTION")
    return "\n".join(lines[:k] + lines[k + 4:])


_W_A12 = "--implicit-bfgs: /IMPL/NONLIN/2 (Quasi-Newton BFGS)"


class ImplicitBfgs(unittest.TestCase):
    """A12 (part-A spec A12; OPT-IN): with the flag an implicit, non-modal
    deck whose NSOLVR is 12 or blank gets /IMPL/NONLIN/2 and no
    /IMPL/QSTAT unless qstat_dtscal_stated; any other NSOLVR keeps
    /IMPL/NONLIN/1 and is named; without the flag the 386444e bytes.

    MEASURED on the branch bytes (nt 4 AND nt 2, identical where marked):
    ex_06_beam_elform_1 NORMAL in 277 cycles, IE END -0.0934 %, RMS 0.09 %
    of the LS peak over 121 LS times in (0.01, 1.0] (nt 4 = nt 2), where
    the default stops at t 0.1601 (IE -59.58 %); doorbeam (A1 + A2) NORMAL
    in 40 cycles, IE END -8.64 / -6.06 %, the punch = LS at every fifth;
    the same pair on the TYPE25 route (--no-implicit-n2s-type7): a NORMAL
    banner (387 / 110 cycles) with IE END -1.1e10 / -7.7e8 % - the SILENT
    failure; tensile2 NORMAL 75 -> 43 cycles, IE RMS 2.48 -> 5.61 % (END
    -0.54 -> +26.88 %, nt 4 = nt 2).
    """

    def test_a_NSOLVR_12_gets_BFGS_and_no_QSTAT(self):
        res, _s, engine = _convert(_t4._implicit_deck(nsolvr=12),
                                   implicit_bfgs=True)
        self.assertEqual(_nonlin(engine), 2)
        self.assertIsNone(_qstat(engine))
        self.assertTrue(_has(res.warnings, _W_A12, "for NSOLVR 12",
                             "with no /IMPL/QSTAT card", "SILENT"))

    def test_b_a_blank_NSOLVR_and_no_card_are_the_family(self):
        for name, deck in (("blank", _t4._implicit_deck(nsolvr=0)),
                           ("no card",
                            _no_solution_card(_t4._implicit_deck()))):
            with self.subTest(name):
                self.assertNotIn("*CONTROL_IMPLICIT_SOLUTION\n"
                                 + _row(2), deck)
                res, _s, engine = _convert(deck, implicit_bfgs=True)
                self.assertEqual(_nonlin(engine), 2)
                self.assertIsNone(_qstat(engine))
                self.assertTrue(_has(res.warnings, _W_A12, "NSOLVR blank"))

    def test_c_another_NSOLVR_keeps_NONLIN_1_and_is_named(self):
        # 2 is LS-DYNA's older BFGS spelling: the decision scoped the opt-in
        # to NSOLVR 12 / blank (the measured family), so 2 is refused like
        # any other value (the fix round, F7: adding 2 to the family
        # survived the round-9 suite)
        for n in (1, 2, 6):
            with self.subTest(nsolvr=n):
                res, _s, engine = _convert(_t4._implicit_deck(nsolvr=n),
                                           implicit_bfgs=True)
                self.assertEqual(_nonlin(engine), 1)
                self.assertTrue(_has(res.warnings, "--implicit-bfgs: "
                                     f"*CONTROL_IMPLICIT_SOLUTION NSOLVR {n}"
                                     " is not the family"))
                self.assertFalse(_has(res.warnings, _W_A12))

    def test_d_a_stated_QSTAT_is_kept(self):
        res, _s, engine = _convert(_t4._implicit_deck(nsolvr=12),
                                   implicit_bfgs=True, qstat_dtscal=10.0,
                                   qstat_dtscal_stated=True)
        self.assertEqual(_nonlin(engine), 2)
        self.assertEqual(_qstat(engine), "10")
        self.assertTrue(_has(res.warnings, _W_A12, "the /IMPL/QSTAT card "
                             "--qstat-dtscal asked for is kept"))

    def test_e_without_the_flag_the_default_bytes(self):
        deck = _t4._implicit_deck(nsolvr=12)
        res, st, engine = _convert(deck)
        res2, st2, engine2 = _convert(deck, implicit_bfgs=False)
        self.assertEqual((st, engine), (st2, engine2))
        self.assertEqual(_nonlin(engine), 1)
        self.assertEqual(_qstat(engine), "10")
        self.assertFalse(_has(res.warnings, "--implicit-bfgs"))


# ═════════════════════════════════════════════════════════════════════════════
# A13 - the CNRB _SPC CMO -1 frame under --no-rigid-local-constraints: a
#       VECTOR CON1 is a written /SKEW/FIX (no "will dangle"); only a CON1
#       in no registry is named, with what it costs
# ═════════════════════════════════════════════════════════════════════════════

_A13_FRAMES = {
    "vector": ("*DEFINE_COORDINATE_VECTOR\n"
               + _row(5, 1.0, 2.0, 2.0, 2.0, 1.0, -2.0, 0) + "\n"),
    "system": ("*DEFINE_COORDINATE_SYSTEM\n"
               + _row(5, 0.0, 0.0, 0.0, 3.0, 6.0, 6.0, 0) + "\n"
               + _row(6.0, 3.0, -6.0) + "\n"),
    "missing": "",
}


def _a13_cnrb_frame(kind: str = "vector", con1: int = 5) -> str:
    """g3j's closed-form coupon (R9P/g3j/coupon/cnrb_vec.k / cnrb_sys.k,
    comments dropped): an elastic cube on a *CONSTRAINED_NODAL_RIGID_BODY_SPC
    CMO -1 CON1 5 / CON2 011111 (only the local x free) under gravity
    (1000, 2000, 3000), a free second hex for the explicit step; frame 5 is
    the VECTOR x = (1,2,2)/3, v = (2,1,-2) or its SYSTEM twin."""
    nodes = [(1, 0, 0, 0), (2, 10, 0, 0), (3, 10, 10, 0), (4, 0, 10, 0),
             (5, 0, 0, 10), (6, 10, 0, 10), (7, 10, 10, 10), (8, 0, 10, 10),
             (21, 100, 0, 0), (22, 110, 0, 0), (23, 110, 10, 0),
             (24, 100, 10, 0), (25, 100, 0, 10), (26, 110, 0, 10),
             (27, 110, 10, 10), (28, 100, 10, 10)]
    return "".join([
        "*KEYWORD\n*TITLE\ng3j CNRB_SPC CMO -1 frame coupon\n",
        "*CONTROL_TERMINATION\n", _row(0.01, 0, 0.0, 0.0, 0.0), "\n",
        "*DATABASE_GLSTAT\n", _row("1.0E-4", 0, 0, 1), "\n",
        "*DATABASE_HISTORY_NODE\n", _row(1, 7), "\n",
        "*DATABASE_NODOUT\n", _row("1.0E-4", 0, 0, 1), "\n",
        _A13_FRAMES[kind],
        "*PART\ncube\n", _row(1, 1, 1, 0, 0, 0, 0, 0), "\n",
        "*SECTION_SOLID\n", _row(1, 1, 0), "\n",
        "*MAT_ELASTIC\n", _row(1, "7.85E-9", 210000.0, 0.3), "\n",
        "*SET_NODE_LIST\n", _row(1, 0.0, 0.0, 0.0, 0.0), "\n",
        _row(1, 2, 3, 4, 5, 6, 7, 8), "\n",
        "*CONSTRAINED_NODAL_RIGID_BODY_SPC\n", _row(100, 0, 1, 0, 0, 0, 0),
        "\n", _row(-1.0, con1, 11111), "\n",
        "*DEFINE_CURVE\n", _row(1, 0, 1.0, 1.0), "\n",
        f"{0.0:>20}{1.0:>20}\n{1.0:>20}{1.0:>20}\n",
        "*LOAD_BODY_X\n", _row(1, 1000.0), "\n",
        "*LOAD_BODY_Y\n", _row(1, 2000.0), "\n",
        "*LOAD_BODY_Z\n", _row(1, 3000.0), "\n",
        "*ELEMENT_SOLID\n",
        "       1       1       1       2       3       4       5       6       7"
        "       8\n",
        "       2       1      21      22      23      24      25      26      27"
        "      28\n",
        "*NODE\n",
        "".join(f"{n:>8}{float(x):>16}{float(y):>16}{float(z):>16}\n"
                for n, x, y, z in nodes),
        "*END\n"])


def a13_cnrb_vector_optout() -> str:
    return _a13_cnrb_frame("vector")


def a13_cnrb_missing_optout() -> str:
    return _a13_cnrb_frame("missing", con1=9)


def _no_titles(starter: str) -> str:
    """The starter with every /SKEW block's title line blanked (the twins
    differ only there)."""
    out, lines = [], starter.splitlines()
    for i, ln in enumerate(lines):
        if i and lines[i - 1].startswith("/SKEW/"):
            ln = "<title>"
        out.append(ln)
    return "\n".join(out)


class CnrbSpcFrameOptOut(unittest.TestCase):
    """A13 (part-A spec A13, the CNRB _SPC "will dangle" sentence; D-4: a
    BEHAVIOURAL guard, the needle would kill 14 true sentences of other
    features): under --no-rigid-local-constraints a VECTOR CON1 is written
    in /SKEW/FIX/5 like its SYSTEM twin and names nothing; a CON1 in no
    registry names what it costs.

    STARTER RUNS (nt 4): a13_cnrb_vector_optout() under the opt-out
    (p_a13vec_n4): 0 ERROR / 0 WARNING; a13_cnrb_missing_optout() under
    the opt-out (p_a13miss_n4): ERROR 137 "UNDEFINED SKEW OR FRAME ID=9"
    on BC_cnrb_100 - the sentence's claim. ENGINE (g3j, the round-9
    census, 10002 cycles each with /DTIX 1.0E-6): VECTOR = SYSTEM to every
    printed digit,
    u . e1 = -0.179721 mm at t 0.009901 = the closed form within 1.37e-7,
    transverse <= 1.33e-10 mm.
    """

    def test_the_twins_write_the_same_cards_on_both_paths(self):
        for kw in ({}, {"rigid_local_constraints": False}):
            with self.subTest(**kw):
                r_v, s_v, _e = _convert(_a13_cnrb_frame("vector"), **kw)
                r_s, s_s, _e = _convert(_a13_cnrb_frame("system"), **kw)
                self.assertEqual(_no_titles(s_v), _no_titles(s_s))
                for r in (r_v, r_s):
                    self.assertFalse(_has(r.warnings, "will dangle"))
                    self.assertFalse(_has(r.warnings,
                                          "names no *DEFINE_COORDINATE_"))

    def test_a_CON1_in_no_registry_names_ERROR_137(self):
        res, _s, _e = _convert(a13_cnrb_missing_optout(),
                               rigid_local_constraints=False)
        self.assertTrue(_has(res.warnings, "pid=100: CON1 9 names no "
                             "*DEFINE_COORDINATE_* system",
                             "the starter stops (ERROR 137)"))
        self.assertFalse(_has(res.warnings, "will dangle"))


# ═════════════════════════════════════════════════════════════════════════════
# A13 - the round-9 part-A flags reach every wiring site
# ═════════════════════════════════════════════════════════════════════════════

import test_r14_triage_8 as _t8  # noqa: E402


class Round9FlagWiringA(_t7.Round7FlagWiringA):
    """Every round-9 part-A DEFAULT-ON lever reaches the parser (with its
    --no- twin), the README prose, the --help render with its measured
    figures (matched on the collapsed render), the GUI end to end,
    convert() / ConvertOptions (default True) and cli.main()'s call - the
    round-7 checks, for this round's eight flags (A5's findings spelling
    --2d-beam-thickness-section is an alias: TwoDBeamThicknessSection)."""

    _FLAGS = {
        "--rigid-part-pid-precedence": "rigid_part_pid_precedence",
        "--implicit-n2s-type7": "implicit_n2s_type7",
        "--implicit-rigid-gravity-nodes": "implicit_rigid_gravity_nodes",
        "--elform7-beam-thickness-section": "elform7_beam_thickness_section",
        "--spc-vector-frames": "spc_vector_frames",
        "--modal-acoustic-void": "modal_acoustic_void",
        "--prescribed-motion-sf-default": "prescribed_motion_sf_default",
        "--rigid-local-shared-skew": "rigid_local_shared_skew",
    }
    _HELP_FIGURES = {
        "--rigid-part-pid-precedence": (
            "Warning 10177", "32.30 / 65.32 / 95.32 / 132.8 / 135.0 mm",
            "+582.00 %", "+53.91 %", "RMS 393.31 -> 81.05 %",
            "-15.85 .. -28.08 %", "RMS 10.34 .. 15.25 %"),
        "--implicit-n2s-type7": (
            "imp_int_k.F:111-200", "ind_glob_k.F:4601-4605 MESSAGE 232",
            "-15.85 .. -28.08 %", "twelve runs, nt 4 and nt 2", "(silent)"),
        "--implicit-rigid-gravity-nodes": (
            "gravit_imp.F:84-91", "inirby.F:836-837", "1101 cycles",
            "+0.42 / +0.20 / +0.14 %", "Explicit decks unchanged"),
        "--elform7-beam-thickness-section": (
            "TS1 x 1", "TS1^3 / 12", "ERROR 314-317", "5.68x"),
        "--spc-vector-frames": (
            "0.3352 -> 1.8e-8 mm", "4611 -> 0.024 N", "271 = 271 cycles",
            "48 rows"),
        "--modal-acoustic-void": (
            "9.3.ssd_acoustic_box", "179 (+ 760) -> 0", "modal recipe only",
            "IE RMS 168.69 %"),
        "--prescribed-motion-sf-default": (
            "read_impdisp.F:239", "Vol I p.759", "Fscale 1"),
        "--rigid-local-shared-skew": (
            "WARNING 312", "x0.750 / x-0.5625", "x1.000"),
    }


class Round9OptInWiring(_t8.Round8OptInWiringB):
    """Every round-9 part-A OPT-IN lever (default OFF) reaches the parser
    (with its --no- twin), the README prose (its POSITIVE spelling) and its
    own README ### heading, the --help render with its measured figures,
    the GUI end to end, convert() / ConvertOptions (default False) and
    cli.main()'s call - round 8's opt-in checks for A10."""

    _OPT_IN = {"--mixed-main-thickness-gap": "mixed_main_thickness_gap",
               "--implicit-bfgs": "implicit_bfgs"}
    _HELP_FIGURES = {
        "--mixed-main-thickness-gap": ("2.196 -> 1.995 mm", "LS 1.817",
                                       "2916 -> 7557", "LS 1758.5",
                                       "OFF by default"),
        "--implicit-bfgs": ("/IMPL/NONLIN/2", "ex_06", "IE RMS 0.09 %",
                            "SILENTLY", "TYPE25 route"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# A13 - the ROADMAP and CHANGELOG records of part A
# ═════════════════════════════════════════════════════════════════════════════

class Round9RoadmapRecordA(unittest.TestCase):
    """A13: ONE ``**Round 9:**`` line on each round-8 NOT entry part A
    closes or re-states (11, 13, 15, 16, 18, 19, 20, 27), the round-8 list
    still numbered 1-27 (Round8RoadmapRecord), and part A's two records for
    the round-9 list in place."""

    _ENTRIES = (11, 13, 15, 16, 18, 19, 20, 27)

    @classmethod
    def setUpClass(cls):
        cls.lines = _t7._read7("ROADMAP.md").splitlines()

    def _at(self, prefix: str) -> int:
        hits = [k for k, ln in enumerate(self.lines) if ln.startswith(prefix)]
        self.assertEqual(len(hits), 1, prefix)
        return hits[0]

    def test_each_part_A_entry_carries_one_round_9_line(self):
        s = self._at("**What round 8 deliberately does NOT close**")
        # part B's round-9 sections sit between this list and the
        # starter-failure paragraph
        e = self._at("**What round 9 closes, and what it does NOT.**")
        starts = {int(m.group(1)): k for k, m in
                  ((k, re.match(r"^(\d+)\. \*\*", self.lines[k]))
                   for k in range(s, e)) if m}
        ends = sorted(starts.values()) + [e]
        for n in self._ENTRIES:
            with self.subTest(entry=n):
                a = starts[n]
                b = ends[ends.index(a) + 1]
                block = "\n".join(self.lines[a:b])
                self.assertEqual(block.count("**Round 9:**"), 1)

    def test_part_A_records_for_the_round_9_list(self):
        text = _t7._collapse("\n".join(self.lines))
        self.assertIn("**Round 9, part A - two records for the round-9 NOT "
                      "list:**", text)
        for needle in ("9 keys / 5 models", "imp_dt.F:55-56",
                       "ex_14_solid_elform_1",
                       "4.3_General_Nonlinearity as its second bolt-preload"
                       " carrier"):
            self.assertIn(needle, text)


class Round9ChangelogReSumsA(unittest.TestCase):
    """A13: the "re-add every headline total" rule - part A's header
    sentence re-sums from its per-item counts minus the keys several items
    share, and each item bullet states its own count."""

    #: the keys several part-A items move (the union is the sum minus these)
    _SHARED = {"doorbeam": ("A1", "A2"), "ex_16": ("A4", "A5"),
               "the Yaris roof crush": ("A4", "A8", "A9"),
               "the door sag": ("A4", "A8")}

    def test_the_part_A_total_re_sums(self):
        text = _t7._collapse(_t7._read7("CHANGELOG.md"))
        m = re.search(
            r"Part A's default bytes move (\d+) deck keys / (\d+) emitted "
            r"models \(A1 (\d+) / (\d+), A2 (\d+) / (\d+), A4 (\d+) / (\d+), "
            r"A5 (\d+) / (\d+), A6 (\d+) / (\d+), A7 (\d+) / (\d+), "
            r"A8 (\d+) / (\d+), A9 (\d+) / (\d+);", text)
        self.assertIsNotNone(m)
        tot_k, tot_m, *items = map(int, m.groups())
        shared = sum(len(v) - 1 for v in self._SHARED.values())
        self.assertEqual(sum(items[0::2]) - shared, tot_k)
        self.assertEqual(sum(items[1::2]) - shared, tot_m)
        for name in self._SHARED:
            self.assertIn(name, m.string[m.end():m.end() + 400])


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
    # A11: ex_07 under --arclength-riks loops through negative load factors
    # and ends NORMAL in 4 of 5 runs - "ERROR on the last increment" is
    # stale ("the engine never prints its last increment", the ECTOL
    # sentence, is another subject and is not needled)
    "on the last increment",
    # A13 B-i: implicit CMO -1 was MEASURED on a coupon (round 9)
    "by source only",
    # A13 / A8: the starter reads a zero Fscale as 1.0 (read_impdisp.F:239);
    # "Fscale 0" as LS-DYNA's reading of SF 0 is retracted (the true
    # Fscale_Y = 0 sentences of loads.py are not needled)
    "written as Fscale 0",
    "with Fscale 0 (entry 19)",
)

#: (relative path, a replacement that IS shipped there)
_REPLACEMENTS_ROUND_9_A = (
    ("k2rad/writer/contacts.py", "imp_int_k.F:111-200 has no TYPE25 branch; "
     "ind_glob_k.F:4601-4605 prints MESSAGE 232"),
    ("k2rad/cli.py", "can stop early OR end NORMAL with the load path lost"),
    ("README.md", "`imp_int_k.F:111-200` has no TYPE25 branch"),
    ("ROADMAP.md", "**Round 9:** CLOSED by A2 (implicit N2S -> one-way TYPE7 "
     "+ the stub, friction-faithful"),
    ("k2rad/writer/assembly.py", "the run ends NORMAL in 4 of 5 runs of "
     "identical bytes"),
    ("README.md", "**Since round 9 (A11) the flag writes NO `/IMPL/QSTAT` "
     "card unless `--qstat-dtscal` is given**"),
    ("ROADMAP.md", "**Round 9:** implicit CMO −1 MEASURED on a coupon"),
    ("ROADMAP.md", "19. **SF = 0 on `*BOUNDARY_PRESCRIBED_MOTION_*`** (new)"),
    ("k2rad/writer/rbody.py", "names no *DEFINE_COORDINATE_* system: the "
     "/BCS skew_ID is undefined and the starter stops (ERROR 137)"),
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


# ═════════════════════════════════════════════════════════════════════════════
# PART B
# ═════════════════════════════════════════════════════════════════════════════
#
# B1  *BOUNDARY_THERMAL_WELD_TRAJECTORY -> windowed /IMPFLUX VOLUMIC on the
#     screened class + the S2 /ANIM/DT cap + the TEMP group
#     (default ON, --no-weld-trajectory-impflux; --weld-trajectory-window S)
# (B2 .. B9 below, each under its own banner.)

import math  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

from k2rad import convert  # noqa: E402


def _f10(*v):
    out = ""
    for x in v:
        if x is None:
            out += " " * 10
        elif isinstance(x, int):
            out += "%10d" % x
        else:
            s = "%10.6g" % x
            out += s if len(s) <= 10 else "%10.3e" % x
    return out


def b1_synw(var="base", d3plot=0.001):
    """SYN-W (round 9, B1; the part-B spec's fixture, gen_synw.py): a block
    x 0..10, y -2..2, z -2..0 of 1 mm bricks (80 bricks, 165 nodes); part 3
    = the seam strip y -1..1, z -1..0 (20 bricks, TMID 2 = *MAT_THERMAL_CWM
    born at -1 s, MID 0); NSID1 = the 7 nodes x 2..8 on y 0 z 0; NSID2 -1 =
    the 12 top faces under the path; SPD1 -301, LCID 302 = (0,0) (0.1,1)
    (1.9,1) (2,0) (10,0); Q 1000; a b cf cr Ff Fr = 1.5 1 1 2 0.6 1.4; SOLN
    1, ENDTIM 3.0, d3plot *d3plot* (0.001); T0 293.15; a convection boundary
    on the side faces. *var* names one variant (a refusal class or a
    control; "ptyp0" states PTYP 0, "convcurve" puts the convection T_inf on
    a curve that ends at t 1.0)."""
    nx, ny, nz = 10, 4, 2

    def nid(i, j, k):
        return 1 + i * (ny + 1) * (nz + 1) + j * (nz + 1) + k
    L = ["*KEYWORD", "*TITLE", "SYN-W weld trajectory fixture (%s)" % var]
    L += ["*CONTROL_SOLUTION", _f10(2 if var == "soln2" else 1),
          "*CONTROL_TERMINATION", _f10(3.0),
          "*CONTROL_THERMAL_SOLVER", _f10(1, 1, 11),
          "*CONTROL_THERMAL_TIMESTEP", _f10(1, 1.0, 0.01, 0.0, 0.1, 0.0, 0.0),
          "*DATABASE_BINARY_D3PLOT", _f10(d3plot)]
    if var == "soln2":
        L += ["*CONTROL_TIMESTEP", _f10(0.0, 0.9)]
    tmid3 = {"isotropic": 1, "notmid": 9}.get(var, 2)
    L += ["*PART", "seam", _f10(3, 3, 9 if var == "soln2" else 0, 0, 0, 0,
                                0, tmid3)]
    if var == "shellpid":
        L += ["*PART", "seam shell", _f10(4, 4, 9, 0, 0, 0, 0, 2),
              "*SECTION_SHELL", _f10(4, 2), _f10(1.0, 1.0, 1.0, 1.0),
              "*MAT_ELASTIC", _f10(9, 7.85e-9, 210000.0, 0.3)]
    if var == "soln2":
        L += ["*MAT_ELASTIC", _f10(9, 7.85e-9, 210000.0, 0.3)]
    L += ["*PART", "base metal", _f10(1, 3, 0, 0, 0, 0, 0, 1),
          "*MAT_THERMAL_ISOTROPIC", _f10(1, 7.85e-9), _f10(4.6e8, 40.0)]
    L += ["*SECTION_SOLID", _f10(3, 1)]
    if var not in ("isotropic", "notmid"):
        tist, tiend, tlend = -2.0, -1.0, -1000.0
        if var == "born_late":
            tist, tiend = 0.5, 1.0
        if var == "tlend_hot":
            tlend = 400.0
        lchc = 999 if var == "nocwmcurve" else 106
        L += ["*MAT_THERMAL_CWM",
              _f10(2, 7.85e-9, 0, 0.0, 5.11e8, 0.001, 0.0, 0.0),
              _f10(lchc, 107, -1001.0, tlend, tist, tiend, 5.11e8, 0.001)]
    hc3 = 1500.0 if var == "cpspread" else 750.0
    L += ["*DEFINE_CURVE", _f10(106, 0, 1.0, 1.0e6),
          "%20.6g%20.6g" % (273.0, 500.0), "%20.6g%20.6g" % (473.0, 550.0),
          "%20.6g%20.6g" % (10000.0, hc3)]
    L += ["*DEFINE_CURVE", _f10(107), "%20.6g%20.6g" % (273.0, 15.0),
          "%20.6g%20.6g" % (473.0, 20.0), "%20.6g%20.6g" % (10000.0, 30.0)]
    shape = [(0.0, 0.0), (0.1, 1.0), (1.9, 1.0), (2.0, 0.0), (10.0, 0.0)]
    for lc in (301, 302):
        L += ["*DEFINE_CURVE", _f10(lc)] + ["%20.6g%20.6g" % p for p in shape]
    L += ["*NODE"]
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                L.append("%8d%16.8g%16.8g%16.8g" % (
                    nid(i, j, k), float(i), float(j - 2), float(k - 2)))
    L += ["*ELEMENT_SOLID"]
    e = 1
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                c = [nid(i, j, k), nid(i + 1, j, k), nid(i + 1, j + 1, k),
                     nid(i, j + 1, k), nid(i, j, k + 1), nid(i + 1, j, k + 1),
                     nid(i + 1, j + 1, k + 1), nid(i, j + 1, k + 1)]
                pid = 3 if (j in (1, 2) and k == 1) else 1
                L.append("%8d%8d" % (e, pid) + "".join("%8d" % x for x in c))
                e += 1
    if var == "shellpid":
        L += ["*ELEMENT_SHELL", "%8d%8d%8d%8d%8d%8d" % (
            1001, 4, nid(0, 0, 2), nid(1, 0, 2), nid(1, 1, 2), nid(0, 1, 2))]
    path = [nid(i, 2, 2) for i in range(2, 9)]
    if var == "short":
        path = path[:2]
    L += ["*SET_NODE_LIST", _f10(1)]
    for c in range(0, len(path), 8):
        L.append(_f10(*path[c:c + 8]))
    segs = []
    for i in range(2, 8):
        for j in (1, 2):
            segs.append([nid(i, j, 2), nid(i + 1, j, 2), nid(i + 1, j + 1, 2),
                         nid(i, j + 1, 2)])
    if var == "noaim":
        segs = segs[2:]
    L += ["*SET_SEGMENT", _f10(1)] + [_f10(*s) for s in segs]
    side = []
    for i in range(nx):
        for k in range(nz):
            side.append([nid(i, 0, k), nid(i + 1, 0, k), nid(i + 1, 0, k + 1),
                         nid(i, 0, k + 1)])
            side.append([nid(i, ny, k), nid(i, ny, k + 1),
                         nid(i + 1, ny, k + 1), nid(i + 1, ny, k)])
    L += ["*SET_SEGMENT", _f10(2)] + [_f10(*s) for s in side]
    if var == "convcurve":
        L += ["*BOUNDARY_CONVECTION_SET", _f10(2),
              _f10(0, 0.01, 303, 293.15, 0.0), "*DEFINE_CURVE", _f10(303),
              "%20.6g%20.6g" % (0.0, 1.0), "%20.6g%20.6g" % (1.0, 1.0)]
    else:
        L += ["*BOUNDARY_CONVECTION_SET", _f10(2),
              _f10(0, 0.01, 0, 293.15, 0.0)]
    L += ["*INITIAL_TEMPERATURE_SET", _f10(0, 293.15)]
    pid, ptyp = 3, 1
    if var == "ptyp2":
        L += ["*SET_PART_LIST", _f10(7), _f10(3)]
        pid, ptyp = 7, 2
    if var == "ptyp3":
        ptyp = 3
    if var == "ptyp0":
        ptyp = 0
    if var == "shellpid":
        pid = 4
    nsid2 = {"nsid2_0": 0, "nsid2_pos": 1}.get(var, -1)
    iform = {"iform1": 1, "iform3": 3, "iform4": 4, "iform5": 5}.get(var, 2)
    a_ax = 0.0 if var == "axis0" else 1.5
    L += ["*BOUNDARY_THERMAL_WELD_TRAJECTORY",
          _f10(pid, ptyp, 1, -301, nsid2, -301, 5,
               1 if var == "relvel1" else 0),
          _f10(iform, 0 if var == "lcid0" else 302,
               -1000.0 if var == "qneg" else 1000.0,
               5 if var == "lcrot" else 0, 0, 0, 0.0,
               1 if var == "enfor1" else 0),
          _f10(a_ax, 1.0, 1.0, 2.0, 0.6, 1.4, 0.0, 0.0)]
    if var == "driven":
        L += ["*BOUNDARY_PRESCRIBED_MOTION_NODE",
              _f10(path[0], 3, 2, 302, 1.0)]
    if var == "nowtraj":
        L = L[:L.index("*BOUNDARY_THERMAL_WELD_TRAJECTORY")]
    L += ["*DATABASE_HISTORY_NODE", _f10(nid(0, 0, 0), nid(10, 4, 0))]
    L += ["*END", ""]
    return "\n".join(L)


def _impflux_set(starter: str):
    """``{(TSTART, TSTOP, FSCALE, frozenset(bricks))}`` over every /IMPFLUX
    + its /GRBRIC/BRIC (ids, titles and comments excluded) and the raw
    /IMPFLUX data lines, in file order."""
    lines = starter.splitlines()
    grb = {}
    for head, body in _blocks(starter, "/GRBRIC/BRIC/"):
        grb[int(head.split("/")[3])] = frozenset(
            int(t) for ln in body[1:] for t in ln.split())
    out, rows = set(), []
    for i, ln in enumerate(lines):
        if ln.startswith("/IMPFLUX/"):
            a, b = lines[i + 3], lines[i + 5]
            cells = [int(a[k:k + 10]) for k in range(0, 40, 10)]
            vals = [float(b[k:k + 20]) for k in range(0, 80, 20)]
            rows.append((cells, vals))
            out.add((round(vals[2], 9), round(vals[3], 9), vals[1],
                     grb[cells[3]]))
    return out, rows


def _funct_points(starter: str, title: str):
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/FUNCT/") and lines[i + 1].strip() == title:
            pts = []
            j = i + 2
            while j < len(lines) and not lines[j].startswith("/"):
                if not lines[j].startswith("#"):
                    pts.append(tuple(float(t) for t in lines[j].split()))
                j += 1
            return int(ln.split("/")[2]), pts
    return None, None


#: the 386444e (pristine10) test-path digests of b1_synw("base") - the
#: opt-out must reproduce them (computed once by the implement agent through
#: this module's _convert path on C:/Users/pmqua/PycharmProjects/
#: k2rad-wt-pristine10, porcelain --ignored empty before and after)
_B1_SYNW_386444E_STARTER = (
    "c93e1066c9a93afc22c91d813dc30403a447da613b0512ded727a6c3777b716a")
_B1_SYNW_386444E_ENGINE = (
    "50fbc4f7004d128d8602d07f3a3dd339b8b0b021984b0b979f9effcf6c438dad")
#: ... and of the SYN-W deck WITHOUT the trajectory (a CWM never converts
#: alone: the default reproduces them)
_B1_NOWTRAJ_386444E_STARTER = (
    "c68a99475f78bdbd42f4d0100b72df1864a3f32e96294eb042e2dede155c969b")
_B1_NOWTRAJ_386444E_ENGINE = (
    "fbc638ff02793693cb64984f28c66f2737e7cca04dccaaf1e0c467625572b9a1")

_W_B1_OK = "*BOUNDARY_THERMAL_WELD_TRAJECTORY on part 3 (PTYP 1) -> "
_W_B1_REFUSED = "*BOUNDARY_THERMAL_WELD_TRAJECTORY on part"


def _b1_independent_energy(window: float = 0.25, short: bool = False):
    """An INDEPENDENT ~25-line reference of the vfs rule on SYN-W (no k2rad
    function): returns (energy, groups) with groups = {(t0, t1, key,
    frozenset(bricks))}."""
    g4 = (-0.75, -0.25, 0.25, 0.75)
    path = [(float(i), 0.0, 0.0) for i in range(2, 4 if short else 9)]
    lpath = len(path) - 1.0

    def lin(t):
        pts = [(0.0, 0.0), (0.1, 1.0), (1.9, 1.0), (2.0, 0.0), (10.0, 0.0)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= t <= x1:
                return y0 + (y1 - y0) * (t - x0) / (x1 - x0)
        return 0.0
    qf = 3 * 0.6 * 1000.0 / (2 * math.pi * 1.5 * 1.0 * 1.0)
    qr = 3 * 1.4 * 1000.0 / (2 * math.pi * 1.5 * 1.0 * 2.0)
    seam = {}
    e = 1
    for i in range(10):
        for j in range(4):
            for k in range(2):
                if j in (1, 2) and k == 1:     # unit cubes, corner (i, j-2, k-2)
                    seam[e] = [(i + 0.5 * (1 + u), j - 2 + 0.5 * (1 + v),
                                -1 + 0.5 * (1 + w)) for u in g4 for v in g4
                               for w in g4]
                e += 1
    energy, groups, nwin = 0.0, set(), int(math.ceil(2.0 / window - 1e-9))
    for kw in range(nwin):
        t0, t1 = kw * window, min((kw + 1) * window, 2.0)
        q = {}
        for m in range(10):
            tm = t0 + (m + 0.5) * (t1 - t0) / 10
            s = sum(lin((n + 0.5) * tm / 400) for n in range(400)) * tm / 400
            if s > lpath:
                continue
            x0 = 2.0 + s                        # r = +x, s-axis = +y, t = +z
            for eid, pts in seam.items():
                nf = sum(1 for p in pts if p[0] >= x0 and ((p[0] - x0) / 1.0)
                         ** 2 + (p[1] / 1.5) ** 2 + (p[2] / 1.0) ** 2 <= 1.0)
                nr = sum(1 for p in pts if p[0] < x0 and ((p[0] - x0) / 2.0)
                         ** 2 + (p[1] / 1.5) ** 2 + (p[2] / 1.0) ** 2 <= 1.0)
                q[eid] = q.get(eid, 0.0) + lin(tm) * (qf * nf + qr * nr) / 64
        keys = {}
        for eid, v in q.items():
            if v / 10 > 0:
                keys.setdefault(float("%.3g" % (v / 10)), []).append(eid)
        for key, els in keys.items():
            groups.add((round(t0, 9), round(t1, 9), key, frozenset(els)))
            energy += key * len(els) * (t1 - t0)
    return energy, groups


class WeldTrajectoryImpflux(unittest.TestCase):
    """B1 (R14 triage round 9): an accepted *BOUNDARY_THERMAL_WELD_TRAJECTORY
    becomes windowed /IMPFLUX VOLUMIC cards on /GRBRIC groups, its
    *MAT_THERMAL_CWM the part's live /HEAT/MAT, the d3plot cadence is capped
    (S2) and the TEMP history is the path + history nodes; every refusal
    class keeps today's bytes with one named sentence. Every deck is
    written by the test (no F: dependency). STARTER (nt 4,
    C:/Users/pmqua/rcv_r9i_implB_synw, harvested and deleted): the
    production SYN-W _0000.rad reads 0 ERROR(S) / 0 WARNING(S) with 64
    VOLUMIC HEAT FLUX DENSITY brick lines; the refusal probes' bytes are the
    opt-out's = 386444e's (ERROR 179 + 3046 where the CWM part is the heated
    part)."""

    @classmethod
    def setUpClass(cls):
        cls.res, cls.st, cls.eng = _convert(b1_synw())

    def test_default_converts_the_trajectory(self):
        st = self.st
        self.assertEqual(len([ln for ln in st.splitlines()
                              if re.match(r"^/IMPFLUX/\d+$", ln)]), 32)
        self.assertEqual(len([ln for ln in st.splitlines()
                              if re.match(r"^/GRBRIC/BRIC/\d+$", ln)]), 32)
        fid, pts = _funct_points(st, "weld_trajectory_unit")
        self.assertEqual(pts, [(0.0, 1.0), (1000.0, 1.0)])
        sets, rows = _impflux_set(st)
        grb_ids = {int(h.split("/")[3]) for h, _b in
                   _blocks(st, "/GRBRIC/BRIC/")}
        for cells, vals in rows:
            self.assertEqual(cells[0], 0)            # SURF_ID 0: VOLUMIC
            self.assertEqual(cells[1], fid)          # the shared unit FUNCT
            self.assertEqual(cells[2], 0)            # no sensor
            self.assertIn(cells[3], grb_ids)
            self.assertEqual(vals[0], 1.0)           # ASCALE
        self.assertEqual(sorted({(r[1][2], r[1][3]) for r in rows}),
                         [(0.25 * k, 0.25 * (k + 1)) for k in range(8)])
        self.assertTrue(_has(self.res.warnings, _W_B1_OK,
                             "32 /IMPFLUX VOLUMIC cards on 32 /GRBRIC groups",
                             "8 windows to t 2", "delivers 0.8625 of Q",
                             "fixflux.F:115-128", "721-2075 s",
                             "ONE LS run, so the evidence base is one model",
                             "NCYC 5 is not used"))

    def test_window_groups_window0_and_1(self):
        sets, _rows = _impflux_set(self.st)
        w0 = {(fs, tuple(sorted(b))) for t0, t1, fs, b in sets if t0 == 0.0}
        w1 = {(fs, tuple(sorted(b))) for t0, t1, fs, b in sets if t0 == 0.25}
        self.assertEqual(w0, {(1.19, (28, 30)), (70.4, (4, 6)),
                              (118.0, (20, 22)), (155.0, (12, 14))})
        self.assertEqual(w1, {(21.5, (28, 30)), (52.9, (4, 6)),
                              (176.0, (20, 22)), (181.0, (12, 14))})

    def test_delivered_sum_against_an_independent_loop(self):
        sets, _rows = _impflux_set(self.st)
        energy = sum(fs * len(b) * (t1 - t0) for t0, t1, fs, b in sets)
        ref, ref_groups = _b1_independent_energy()
        self.assertAlmostEqual(energy, 1638.72, delta=1e-9 * 1638.72)
        self.assertAlmostEqual(ref, energy, delta=1e-9 * energy)
        self.assertEqual(sets, ref_groups)
        self.assertEqual(round(energy / 1900.0, 6), 0.862484)

    def test_lobe_fractions_vs_analytic(self):
        """The production sub-point / lobe / volume functions on an all-seam
        0.25 mm block (32 x 16 x 8 bricks), torch at (4, 0, 0), r +x, t +z,
        a = b = cf = 1, cr = 2: sum(phi V) against pi a b c / 3."""
        from k2rad.writer import thermal as th
        h = 0.25
        sf = sr = 0.0
        for i in range(32):
            for j in range(16):
                for k in range(8):
                    x0, y0, z0 = i * h, -2.0 + j * h, -2.0 + k * h
                    xs = [(x0 + h * (sx > 0), y0 + h * (sy > 0),
                           z0 + h * (sz > 0)) for sx, sy, sz in th._HEX_SIGNS]
                    ff, fr = th._weld_lobe_fractions(
                        th._hexa_subpoints(xs), (4.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                        1.0, 1.0, 1.0, 2.0)
                    v = th._hexa_volume(xs)
                    sf += ff * v
                    sr += fr * v
        self.assertAlmostEqual(sf, 1.053223, places=6)
        self.assertAlmostEqual(sr, 2.095703, places=6)
        self.assertLess(abs(sf / (math.pi / 3.0) - 1.0), 0.01)
        self.assertLess(abs(sr / (2.0 * math.pi / 3.0) - 1.0), 0.01)
        qf = 3 * 0.6 * 1000.0 / (2 * math.pi)
        qr = 3 * 1.4 * 1000.0 / (2 * math.pi * 2.0)
        self.assertAlmostEqual(qf * sf + qr * sr, 1002.163240, places=5)

    def test_source_off_past_the_path_end(self):
        res, st, _e = _convert(b1_synw("short"))
        sets, _rows = _impflux_set(st)
        self.assertEqual(len(sets), 19)
        self.assertEqual({t0 for t0, _t1, _f, _b in sets},
                         {0.0, 0.25, 0.5, 0.75, 1.0})   # windows 5-7: none
        self.assertEqual(len([s for s in sets if s[0] == 1.0]), 3)
        energy = sum(fs * len(b) * (t1 - t0) for t0, t1, fs, b in sets)
        self.assertAlmostEqual(energy, 862.66, delta=1e-9 * 862.66)
        ref, ref_groups = _b1_independent_energy(short=True)
        self.assertEqual(sets, ref_groups)

    def test_material_standin_numbers(self):
        st = self.st
        part3 = [b for h, b in _blocks(st, "/PART/3")][0]
        mid = int(part3[1][10:20])
        heat = [b for h, b in _blocks(st, f"/HEAT/MAT/{mid}")][0]
        self.assertEqual([float(heat[0][k:k + 20]) for k in range(0, 80, 20)],
                         [293.15, 4.71, 16.98821235, 0.00130610115])
        self.assertEqual([float(heat[1][k:k + 20]) for k in range(0, 80, 20)],
                         [0.0, 16.98821235, 0.00130610115, 1.0])
        mat = [b for h, b in _blocks(st, f"/MAT/ELAST/{mid}")][0]
        self.assertEqual(float(mat[1]), 7.85e-9)
        self.assertEqual([float(t) for t in mat[2].split()], [1.0, 0.3])
        self.assertTrue(_has(self.res.warnings, "The *MAT_THERMAL_CWM 2 of "
                             "part(s) [3] (born before t 0: TISTART -2, "
                             "TIEND -1, TLEND -1000 < T0 293.15)",
                             "RHO0_CP 4.71", "AS = AL 16.98821235",
                             "BS = BL 0.00130610115"))
        rne = dict(self.res.recognized_not_emitted)
        self.assertNotIn("MAT_THERMAL_CWM", rne)
        self.assertNotIn("BOUNDARY_THERMAL_WELD_TRAJECTORY", rne)

    def test_cwm_never_converts_alone(self):
        res, st, eng = _convert(b1_synw("nowtraj"))
        self.assertEqual(_sha(st), _B1_NOWTRAJ_386444E_STARTER)
        self.assertEqual(_sha(eng), _B1_NOWTRAJ_386444E_ENGINE)
        part3 = [b for h, b in _blocks(st, "/PART/3")][0]
        self.assertEqual(int(part3[1][10:20]), 0)
        rne = dict(res.recognized_not_emitted)
        self.assertIn("ZERO-HEATING", rne["MAT_THERMAL_CWM"])
        self.assertIn("never converts ALONE", rne["MAT_THERMAL_CWM"])
        self.assertTrue(_has(res.warnings, "a weld that never heats"))

    def test_every_refusal_class(self):
        """One probe per CLASS: the .rad pair equals the opt-out's (= today's
        bytes) and the named reason is printed."""
        probes = {
            "iform1": "IFORM 1: only the IFORM-2 double ellipsoid",
            "iform3": "IFORM 3: only the IFORM-2",
            "iform4": "IFORM 4: only the IFORM-2",
            "iform5": "IFORM 5: only the IFORM-2",
            "enfor1": "ENFOR 1: an enforced-temperature source",
            "qneg": "Q -1000 <= 0",
            "axis0": "every IFORM-2 semi-axis must be > 0",
            "soln2": "SOLN 2: only the thermal-only solution is measured; a "
                     "coupled run is a different card set",
            "relvel1": "RELVEL 1: a source moving relative to a moving body",
            "lcrot": "LCROT 5 / LCMOV 0 / LCLAT 0",
            "driven": "NSID1 node 39 is on driven / loaded part",
            "nsid2_0": "NSID2 0: only an aim by a segment set",
            "nsid2_pos": "NSID2 1: only an aim by a segment set",
            "noaim": "NSID1 edge 39-54 lies on no segment of set 1",
            "ptyp3": "PTYP 3: only 1 (part) and 2 (part set) exist",
            "shellpid": "part 4 carries shell elements: the source is "
                        "volumetric",
            "born_late": "is not born before t 0 (TISTART 0.5, TIEND 1",
            "tlend_hot": "TLEND 400 vs T0 293.15",
            "nocwmcurve": "LCHC 999 / LCTC 107, and a curve",
            "cpspread": "varies by more than 2x",
            "notmid": "TMID 9 names neither a *MAT_THERMAL_CWM nor a "
                      "converted thermal material",
            "lcid0": "LCID 0: the power curve is missing",
        }
        for var, reason in probes.items():
            with self.subTest(probe=var):
                deck = b1_synw(var)
                res, st, eng = _convert(deck)
                _r, st_off, eng_off = _convert(
                    deck, weld_trajectory_impflux=False)
                self.assertEqual(_sha(st), _sha(st_off))
                self.assertEqual(_sha(eng), _sha(eng_off))
                self.assertFalse(re.search(r"^/IMPFLUX/", st, re.M))
                self.assertTrue(_has(res.warnings, _W_B1_REFUSED,
                                     ": not converted - ", reason,
                                     "the part keeps today's output"),
                                [w for w in res.warnings if "WELD" in w])
                rne = dict(res.recognized_not_emitted)
                self.assertIn("BOUNDARY_THERMAL_WELD_TRAJECTORY", rne)

    def test_ptyp_positive_controls(self):
        """PTYP 1 (base) AND PTYP 2 (a *SET_PART_LIST of part 3) convert to
        the SAME deposit - the round-8 spec's 'PTYP != 0' refusal would have
        refused both."""
        _r, st2, _e = _convert(b1_synw("ptyp2"))
        self.assertEqual(_impflux_set(st2)[0], _impflux_set(self.st)[0])
        self.assertEqual(len(_impflux_set(st2)[0]), 32)
        # the fix round (F-B1-1): a STATED PTYP 0 is the default 1 (Vol I
        # R17 Appendix V: LS-DYNA replaces a 0 by the default), not a
        # refusal - the same deposit and the PTYP-1 sentence
        r0, st0, _e = _convert(b1_synw("ptyp0"))
        self.assertEqual(_impflux_set(st0)[0], _impflux_set(self.st)[0])
        self.assertTrue(_has(r0.warnings, "on part 3 (PTYP 1) -> 32 "
                             "/IMPFLUX VOLUMIC cards"))
        self.assertFalse(_has(r0.warnings, "PTYP 0: only 1"))

    def test_s2_cap_boundary_1000_frames(self):
        """S2 caps a SOLN-1 weld deck that requests MORE than 1000 frames:
        d3plot 0.003 over ENDTIM 3.0 is exactly 1000 and stays uncapped,
        3.0 / 1001 (0.002997 in the 10-wide cell) is 1001 and is capped at
        ENDTIM / 100 = 0.03 with the S2 sentence (the fix round, F3: '<='
        -> '<' survived the round-9 suite)."""
        r1, _s1, e1 = _convert(b1_synw(d3plot=0.003))
        self.assertIn("/ANIM/DT\n0. 0.003\n", e1)
        self.assertFalse(_has(r1.warnings, "animation frames over "
                              "OpenRadioss's explicit conduction"))
        r2, _s2, e2 = _convert(b1_synw(d3plot=3.0 / 1001))
        self.assertIn("/ANIM/DT\n0. 0.03\n", e2)
        self.assertTrue(_has(r2.warnings, "/ANIM/DT 0.03 = max(the d3plot dt "
                             "0.002997, ENDTIM / 100)", "1001 animation "
                             "frames"))

    def test_trajectory_on_isotropic_part(self):
        res, st, _e = _convert(b1_synw("isotropic"))
        self.assertEqual(len(_impflux_set(st)[0]), 32)
        self.assertFalse(_has(res.warnings, "The *MAT_THERMAL_CWM"))
        self.assertTrue(_has(res.warnings, "on part 3 (PTYP 1) -> 32 "
                             "/IMPFLUX VOLUMIC cards"))

    def test_s2_anim_cap_and_temp_group(self):
        self.assertIn("/ANIM/DT\n0. 0.03\n", self.eng)
        self.assertEqual(_th_node(self.st, "TH_temperature"),
                         [39, 54, 69, 84, 99, 114, 129, 1, 163])
        self.assertTrue(_has(self.res.warnings, "/ANIM/DT 0.03 = max(the "
                             "d3plot dt 0.001, ENDTIM / 100)",
                             "3000 animation frames", "351.5 MB instead of "
                             "34.80 GB", "the 9 NSID1 + "
                             "*DATABASE_HISTORY_NODE nodes"))
        _r, st_off, eng_off = _convert(b1_synw(),
                                       weld_trajectory_impflux=False)
        self.assertIn("/ANIM/DT\n0. 0.001\n", eng_off)
        self.assertNotEqual(_th_node(st_off, "TH_temperature"),
                            [39, 54, 69, 84, 99, 114, 129, 1, 163])

    def test_window_option(self):
        res, st, _e = _convert(b1_synw(), weld_trajectory_window=0.5)
        sets, _rows = _impflux_set(st)
        self.assertEqual(len({s[0] for s in sets}), 4)
        self.assertEqual(len(sets), 16)
        self.assertEqual(sum(len(s[3]) for s in sets), 32)
        energy = sum(fs * len(b) * (t1 - t0) for t0, t1, fs, b in sets)
        self.assertAlmostEqual(energy, 1645.4, delta=1e-9 * 1645.4)
        self.assertEqual(round(energy / 1900.0, 6), 0.866)
        ref, ref_groups = _b1_independent_energy(window=0.5)
        self.assertEqual(sets, ref_groups)
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(b1_synw())
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(window=bad):
                with self.assertRaises(ValueError):
                    convert(path, write_log=False,
                            weld_trajectory_window=bad)
        tmp.cleanup()
        from k2rad import cli
        p = cli.build_parser()
        self.assertEqual(p.parse_args(["d.k"]).weld_trajectory_window, 0.25)
        self.assertIs(p.parse_args(["d.k"]).weld_trajectory_impflux, True)
        self.assertEqual(p.parse_args(
            ["d.k", "--weld-trajectory-window", "0.5"]
        ).weld_trajectory_window, 0.5)
        self.assertIs(p.parse_args(["d.k", "--no-weld-trajectory-impflux"]
                                   ).weld_trajectory_impflux, False)
        # the optional positional output_stem is NOT swallowed. The
        # positional comes BEFORE the flag: argparse before Python 3.12
        # cannot place an nargs='?' positional after an optional (3.9.13 /
        # 3.10.11 exit 2 on ["d.k", "--flag", "out/stem"] with any flag),
        # and tests.yml runs 3.9 / 3.10 / 3.11.
        ns = p.parse_args(["d.k", "out/stem", "--weld-trajectory-impflux"])
        self.assertEqual(ns.output_stem, "out/stem")
        self.assertIs(ns.weld_trajectory_impflux, True)
        ns = p.parse_args(["d.k", "out/stem", "--no-weld-trajectory-impflux"])
        self.assertEqual(ns.output_stem, "out/stem")
        self.assertIs(ns.weld_trajectory_impflux, False)
        for bad in ("0", "-1", "nan", "inf", "x"):
            with self.subTest(cli=bad):
                with self.assertRaises(SystemExit):
                    p.parse_args(["d.k", "--weld-trajectory-window", bad])
        self.assertIn("--weld-trajectory-window", p.format_help())

    def test_opt_out_is_386444e(self):
        res, st, eng = _convert(b1_synw(), weld_trajectory_impflux=False)
        self.assertEqual(_sha(st), _B1_SYNW_386444E_STARTER)
        self.assertEqual(_sha(eng), _B1_SYNW_386444E_ENGINE)
        self.assertFalse(_has(res.warnings, "WELD_TRAJECTORY"))
        rne = dict(res.recognized_not_emitted)
        self.assertIn("which does not convert", rne["MAT_THERMAL_CWM"])
        self.assertIn("53 /IMPFLUX + 53 /GRBRIC per seam at 0.25 s",
                      rne["BOUNDARY_THERMAL_WELD_TRAJECTORY"])

    def test_far_skip_is_exact(self):
        """The bounding-sphere pre-check skips only bricks no sub-point of
        which can be in a lobe: the plan with the reach set to infinity (no
        skip) is identical on SYN-W and on the short variant."""
        from k2rad.writer import thermal as th
        for var in ("base", "short"):
            with self.subTest(variant=var):
                tmp = tempfile.TemporaryDirectory()
                path = os.path.join(tmp.name, "d.k")
                with open(path, "w") as fh:
                    fh.write(b1_synw(var))
                from k2rad.parser import parse_k_file
                from k2rad.handlers import dispatch
                from k2rad.state import ConversionState
                state = ConversionState()
                for block in parse_k_file(path):
                    dispatch(block, state)
                tr = state.weld_trajectories[0]
                orig = th._weld_lobe_fractions
                calls = []

                def spy(*a, **k):
                    calls.append(1)
                    return orig(*a, **k)
                try:
                    th._weld_lobe_fractions = spy
                    plan = th._weld_plan(state, tr, 0.25)
                    n_skip = len(calls)
                    th._WELD_FAR_SKIP = False
                    plan_noskip = th._weld_plan(state, tr, 0.25)
                finally:
                    th._weld_lobe_fractions = orig
                    th._WELD_FAR_SKIP = True
                self.assertEqual(
                    [(g.window, g.fscale, g.bricks) for g in plan.groups],
                    [(g.window, g.fscale, g.bricks)
                     for g in plan_noskip.groups])
                self.assertEqual(plan.energy, plan_noskip.energy)
                # the pre-check really skipped bricks (else it tests nothing)
                self.assertLess(n_skip, len(calls) - n_skip)
                tmp.cleanup()

    def test_truncated_cards_are_recorded_not_skipped(self):
        """One card line per spelling (the thermal-solver alias test's shape):
        both records are kept, nothing lands in skipped_keywords, and the
        writer's screen refuses the incomplete trajectory (IFORM 0) instead
        of raising."""
        deck = ("*KEYWORD\n*MAT_THERMAL_CWM\n" + _row(7, 1.0) + "\n"
                "*BOUNDARY_THERMAL_WELD_TRAJECTORY\n" + _row(500, 1.0)
                + "\n*END\n")
        state = _t7._dispatch(deck)
        self.assertEqual(state.skipped_keywords, [])
        self.assertEqual(sorted(state.thermal_cwm), [7])
        self.assertEqual(state.weld_trajectories[0].pid, 500)
        self.assertEqual(state.weld_trajectories[0].iform, 0)
        from k2rad.writer.thermal import _weld_refusal
        self.assertIn("IFORM 0: only the IFORM-2",
                      _weld_refusal(state, state.weld_trajectories[0]))


# ═════════════════════════════════════════════════════════════════════════════
# B2 - axisymmetric ELFORM 14 / 15 -> the OpenRadioss 2-D route, with the 2-D
#      DT2MS density cell (default ON, --no-axisymmetric-2d,
#      --no-positive-dt2ms-mass-scaling)
# ═════════════════════════════════════════════════════════════════════════════

def b2_ax15(dt2ms=1e-4, var="base"):
    """AX-15 (round 9, B2; the part-B spec's fixture, gen_ax.py): 3 x 2 quads
    of 1 mm (r = x in 0..3, axis = y in 0..2, z 0) on *SECTION_SHELL ELFORM
    15, *MAT_ELASTIC RO 7.85e-9 E 210000 PR 0.3; the axis nodes (x 0) held in
    x, the bottom nodes held in y, the top nodes driven in y (DOF 2, VAD 2) on
    curve 1 = (0, 0) (1e-3, -0.01); ENDTIM 1e-3; *CONTROL_TIMESTEP DT2MS
    *dt2ms*. Per-radian mass RO x int(r dA) = 7.85e-9 x 4.5 x 2 = 7.065e-8.
    *var*: a refusal class or a control."""
    nx, ny = 3, 2

    def nid(i, j):
        return 1 + j * (nx + 1) + i
    elform = 14 if var == "elform14" else 15
    L = ["*KEYWORD", "*TITLE", "AX-15 axisymmetric fixture (%s)" % var,
         "*CONTROL_TERMINATION", _f10(1.0e-3),
         "*CONTROL_TIMESTEP", _f10(0.0, 0.0, 0, 0.0, dt2ms),
         "*DATABASE_GLSTAT", _f10(1.0e-5), "*DATABASE_MATSUM", _f10(1.0e-5),
         "*DATABASE_HISTORY_SHELL", _f10(1),
         "*PART", "ring", _f10(1, 1, 1),
         "*SECTION_SHELL", _f10(1, elform, 1.0, 2), _f10(1.0, 1.0, 1.0, 1.0)]
    if var == "rigid":
        L += ["*MAT_RIGID", _f10(1, 7.85e-9, 210000.0, 0.3), _f10(0.0, 0, 0),
              _f10(0.0)]
    else:
        L += ["*MAT_ELASTIC", _f10(1, 7.85e-9, 210000.0, 0.3)]
    if var == "mixed1415":
        L += ["*PART", "ring14", _f10(2, 2, 1), "*SECTION_SHELL",
              _f10(2, 14, 1.0, 2), _f10(1.0, 1.0, 1.0, 1.0)]
    if var == "elform16":
        L += ["*PART", "ring16", _f10(2, 2, 1), "*SECTION_SHELL",
              _f10(2, 16, 1.0, 2), _f10(1.0, 1.0, 1.0, 1.0)]
    L += ["*NODE"]
    for j in range(ny + 1):
        for i in range(nx + 1):
            x = float(i) - (0.5 if var == "xneg" and i == 0 else 0.0)
            z = 0.001 if (var == "zoff" and i == 3 and j == 2) else 0.0
            L.append("%8d%16.8g%16.8g%16.8g" % (nid(i, j), x, float(j), z))
    L += ["*ELEMENT_SHELL"]
    e = 1
    for j in range(ny):
        for i in range(nx):
            n = [nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)]
            pid = 2 if (var in ("mixed1415", "elform16") and e == 6) else 1
            if var in ("tri", "tricontact") and e == 6:
                n = [n[0], n[1], n[2], n[2]]
            if var == "cw" and e == 1:
                n = [n[0], n[3], n[2], n[1]]
            L.append("%8d%8d" % (e, pid) + "".join("%8d" % x for x in n))
            e += 1
    axis = [nid(0, j) for j in range(ny + 1)]
    bottom = [nid(i, 0) for i in range(nx + 1)]
    top = [nid(i, ny) for i in range(nx + 1)]
    L += ["*SET_NODE_LIST", _f10(1), _f10(*axis), "*SET_NODE_LIST", _f10(2),
          _f10(*bottom), "*SET_NODE_LIST", _f10(3), _f10(*top)]
    L += ["*BOUNDARY_SPC_SET", _f10(1, 0, 1, 0, 0, 0, 0, 0),
          "*BOUNDARY_SPC_SET", _f10(2, 0, 0, 1, 0, 0, 0, 0)]
    dof = 3 if var == "dof3" else 2
    L += ["*BOUNDARY_PRESCRIBED_MOTION_SET", _f10(3, dof, 2, 1, 1.0)]
    L += ["*DEFINE_CURVE", _f10(1), "%20.6g%20.6g" % (0.0, 0.0),
          "%20.6g%20.6g" % (1.0e-3, -0.01)]
    if var in ("contact", "tricontact"):
        L += ["*CONTACT_2D_AUTOMATIC_SINGLE_SURFACE", _f10(1, 2)]
    if var == "loadnode":
        L += ["*LOAD_NODE_POINT", _f10(nid(3, 1), 1, 1, 1.0)]
    if var == "elmass":
        L += ["*ELEMENT_MASS", "%8d%8d%16.6g" % (100, nid(3, 2), 1.0e-6)]
    if var == "inivel":
        L += ["*INITIAL_VELOCITY_NODE", _f10(nid(3, 2), 0.0, -10.0, 0.0)]
    if var == "rigidwall":
        L += ["*RIGIDWALL_PLANAR", _f10(0),
              _f10(0.0, -1.0, 0.0, 0.0, 1.0, 0.0)]
    if var == "adaptive":
        L += ["*CONTROL_ADAPTIVE", _f10(1.0e-4, 5.0)]
    if var == "solid":
        L += ["*PART", "block", _f10(9, 9, 1), "*SECTION_SOLID", _f10(9, 1),
              "*NODE"] + ["%8d%16.8g%16.8g%16.8g" % (
                  100 + k, 10.0 + (k & 1), 10.0 + ((k >> 1) & 1),
                  float(k >> 2)) for k in range(8)] + \
            ["*ELEMENT_SOLID", "%8d%8d" % (100, 9) + "".join(
                "%8d" % (100 + k) for k in (0, 1, 3, 2, 4, 5, 7, 6))]
    if var == "beam":
        L += ["*PART", "rod", _f10(9, 9, 1), "*SECTION_BEAM", _f10(9, 1),
              _f10(1.0, 1.0), "*ELEMENT_BEAM",
              "%8d%8d%8d%8d" % (100, 9, nid(0, 0), nid(1, 0))]
    L += ["*END", ""]
    return "\n".join(L)


#: the 386444e (pristine10) test-path digests of b2_ax15() - the opt-out
#: --no-axisymmetric-2d must reproduce them (computed once by the implement
#: agent on C:/Users/pmqua/PycharmProjects/k2rad-wt-pristine10)
_B2_AX15_386444E_STARTER = (
    "1d6aca67bfb87cb1bf149289d7fb451aced6cc02279467282183df60ea5ff575")
_B2_AX15_386444E_ENGINE = (
    "48a32f057cdc960f8a54cf02cf4e4faa6c9393fa3f6ca716ce478e24a4d1f269")
_W_B2_ROUTED = "-> the 2-D AXISYMMETRIC route (/ANALY N2D3D 1)"
_W_B2_REFUSED = "the 2-D axisymmetric route is NOT used - "
_W_B2_DENSITY = "> 0 on the routed 2-D deck: the density of material(s)"


def _data_after(starter: str, head: str, k: int = 0):
    """The k-th non-comment data line after the header line *head*."""
    lines = starter.splitlines()
    i = lines.index(head)
    data = [ln for ln in lines[i + 1:] if not ln.startswith("#")]
    return data[k]


class Axisymmetric2D(unittest.TestCase):
    """B2 (R14 triage round 9): an all-ELFORM-14 / 15 deck is written as the
    OpenRadioss 2-D axisymmetric deck, a positive DT2MS scales its density
    by (DT2MS / dt0)^2 with dt0 in closed form; every refusal class keeps
    the 3-D bytes with its named reason. STARTER (nt 4,
    C:/Users/pmqua/rcv_r9i_implB_<name>): the production AX-15 _0000.rad
    reads 0 ERROR(S) / 0 WARNING(S), N2D3D 1, TOTAL MASS 0.12527037 (density
    cell on) and 7.065E-08 under --no-positive-dt2ms-mass-scaling."""

    @classmethod
    def setUpClass(cls):
        cls.res, cls.st, cls.eng = _convert(b2_ax15())

    def test_routed_cards(self):
        st = self.st
        self.assertEqual(_data_after(st, "/ANALY")[:10], "         1")
        rows = {int(ln.split()[0]): ln.split()[1:] for ln in
                [b for h, b in _blocks(st, "/NODE")][0]}
        self.assertEqual(rows[4], ["0", "3", "0"])
        self.assertEqual(rows[12], ["0", "3", "2"])
        self.assertTrue(all(v[0] == "0" for v in rows.values()))
        quad = [b for h, b in _blocks(st, "/QUAD/1")][0]
        self.assertEqual([[int(t) for t in ln.split()] for ln in quad],
                         [[1, 1, 2, 6, 5], [2, 2, 3, 7, 6], [3, 3, 4, 8, 7],
                          [4, 5, 6, 10, 9], [5, 6, 7, 11, 10],
                          [6, 7, 8, 12, 11]])
        self.assertFalse(re.search(r"^/SHELL/", st, re.M))
        self.assertFalse(re.search(r"^/PROP/SHELL/", st, re.M))
        prop = [b for h, b in _blocks(st, "/PROP/SOLID/1")][0]
        self.assertEqual(prop[1].split()[0], "2")         # Isolid 2
        self.assertEqual(float(prop[2].split()[2]), 0.1)  # h
        bcs = sorted(ln.split()[0] for h, b in _blocks(st, "/BCS/")
                     for ln in b[1:])
        self.assertEqual(bcs, ["001", "010"])
        self.assertEqual(_data_after(st, "/IMPDISP/90002", 1)[10:20].strip(),
                         "Z")
        self.assertEqual([b for h, b in _blocks(st, "/TH/QUAD/1")][0][-1]
                         .split(), ["1"])
        self.assertTrue(_has(self.res.warnings, _W_B2_ROUTED,
                             "6 /SHELL become /QUAD (0 re-ordered",
                             "Isolid 2 (h 0.1)", "J = 0",
                             "5.7080700E-06", "0.2199439E-03"))
        self.assertFalse(_has(self.res.warnings, _WA7B_R9))
        self.assertFalse(_has(self.res.warnings, "Ishell=12"))

    def test_density_cell_closed_form(self):
        rho = _data_after(self.st, "/MAT/ELAST/1", 1)
        self.assertEqual(rho.strip(), "1.391893E-02")
        self.assertAlmostEqual(7.85e-9 * 1773111.708199, 1.391893e-2,
                               places=8)
        self.assertTrue(_has(self.res.warnings, _W_B2_DENSITY,
                             "= 1.77311e+06 with dt0 = 7.509862e-08 s",
                             "resol.F:2711-2729", "24 807 cycles",
                             "IE END -0.45 %", "RMS 0.24 %"))
        res0, st0, _e = _convert(b2_ax15(dt2ms=0.0))
        self.assertEqual(_data_after(st0, "/MAT/ELAST/1", 1).strip(),
                         "7.850000E-09")
        self.assertFalse(_has(res0.warnings, _W_B2_DENSITY))
        self.assertTrue(_has(res0.warnings, _W_B2_ROUTED))
        res1, st1, _e = _convert(b2_ax15(),
                                 positive_dt2ms_mass_scaling=False)
        self.assertEqual(_data_after(st1, "/MAT/ELAST/1", 1).strip(),
                         "7.850000E-09")
        self.assertTrue(re.search(r"^/QUAD/1", st1, re.M))
        self.assertFalse(_has(res1.warnings, _W_B2_DENSITY))

    def test_dt0_metal_forming_numbers(self):
        from k2rad.writer.axisym2d import dt0_closed_form
        quads = [[(3.0 * i, 3.0 * j), (3.0 * i + 3, 3.0 * j),
                  (3.0 * i + 3, 3.0 * j + 3), (3.0 * i, 3.0 * j + 3)]
                 for i in range(3) for j in range(6)]
        dt0 = dt0_closed_form(quads, 210000.0, 0.28, 7.83e-9, 0.67)
        self.assertAlmostEqual(dt0 / 2.308935e-07, 1.0, places=6)
        self.assertAlmostEqual((1e-4 / dt0) ** 2 / 187575.7263, 1.0,
                               places=7)
        dt9 = dt0_closed_form(quads, 210000.0, 0.28, 7.83e-9, 0.9)
        self.assertAlmostEqual(dt9 / (0.9 / 0.67 * dt0), 1.0, places=12)
        ax = dt0_closed_form([[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0),
                               (0.0, 1.0)]], 210000.0, 0.3, 7.85e-9, 0.67)
        self.assertAlmostEqual(ax / 7.509862e-08, 1.0, places=6)

    def test_dt2ms_negative_writes_no_noda_cst(self):
        for kw in ({}, {"ams": True}):
            with self.subTest(**kw):
                res, st, eng = _convert(b2_ax15(dt2ms=-1e-4), **kw)
                self.assertNotIn("/DT/NODA/CST", eng)
                self.assertNotIn("/DT/AMS", eng)
                self.assertEqual(_data_after(st, "/MAT/ELAST/1", 1).strip(),
                                 "7.850000E-09")
                self.assertTrue(_has(res.warnings, "DT2MS -0.0001 < 0 on the "
                                     "routed 2-D deck: /DT/NODA/CST is NOT "
                                     "written"))
        _r, _s, eng3 = _convert(b2_ax15(dt2ms=-1e-4), axisymmetric_2d=False)
        self.assertIn("/DT/NODA/CST/0", eng3)

    def test_every_refusal_class(self):
        probes = {
            "mixed1415": "ELFORM 14 and 15 together",
            # the fix round (F-T-1): another ELFORM beside 15 - without this
            # screen the transform turns EVERY /SHELL into /QUAD (it has no
            # per-part ELFORM test); the round-9 suite let that mutant live
            "elform16": "a *SECTION_SHELL of ELFORM [16] beside the "
                        "axisymmetric ones",
            "tri": "1 3-node shell(s): a degenerate 2-D /QUAD creates energy",
            "contact": "*CONTACT_2D_AUTOMATIC_SINGLE_SURFACE: OpenRadioss 2-D "
                       "decks accept only /INTER/TYPE1 / 2 / 3 / 5",
            "zoff": "node 12 has z = 0.001 / x = 3: the axisymmetric section",
            "xneg": "node 1 has z = 0 / x = -0.5",
            "loadnode": "*LOAD_NODE_POINT has no 2-D mapping in k2rad",
            "elmass": "a *ELEMENT_MASS element: OpenRadioss 2-D decks carry "
                      "quads only",
            "inivel": "*INITIAL_VELOCITY_NODE has no 2-D mapping",
            "rigidwall": "*RIGIDWALL_PLANAR has no 2-D mapping",
            "dof3": "*BOUNDARY_PRESCRIBED_MOTION_{NODE|SET} DOF 3 has no 2-D "
                    "mapping",
            "adaptive": "*CONTROL_ADAPTIVE has no 2-D mapping",
            "solid": "a solid element: OpenRadioss 2-D decks carry quads only "
                     "(initia.F:953-955 ERROR 603 for solids)",
            "beam": "a beam element: OpenRadioss 2-D decks carry quads only",
        }
        for var, reason in probes.items():
            with self.subTest(probe=var):
                deck = b2_ax15(var=var)
                res, st, eng = _convert(deck)
                _r, st_off, eng_off = _convert(deck, axisymmetric_2d=False)
                self.assertEqual(_sha(st), _sha(st_off))
                self.assertEqual(_sha(eng), _sha(eng_off))
                self.assertFalse(re.search(r"^/QUAD/", st, re.M))
                self.assertTrue(_has(res.warnings, _W_B2_REFUSED, reason,
                                     "the sections stay 3-D /SHELL"),
                                [w for w in res.warnings if "2-D" in w])
                self.assertTrue(_has(res.warnings, _WA7B_R9,
                                     "the 2-D axisymmetric route is refused "
                                     "for this deck"))
        res, _s, _e = _convert(b2_ax15(var="tricontact"))
        self.assertTrue(_has(res.warnings, _W_B2_REFUSED, "3-node shell(s)",
                             "*CONTACT_2D_AUTOMATIC_SINGLE_SURFACE"))

    def test_elform14_and_rigid_route(self):
        res, st, _e = _convert(b2_ax15(var="elform14"))
        self.assertTrue(re.search(r"^/QUAD/1", st, re.M))
        self.assertTrue(_has(res.warnings, "ELFORM 14 on part(s) [1] -> the "
                             "2-D AXISYMMETRIC route"))
        res, st, _e = _convert(b2_ax15(var="rigid"))
        self.assertTrue(re.search(r"^/QUAD/1", st, re.M))
        rb = [b for h, b in _blocks(st, "/RBODY/")][0]
        self.assertEqual([float(v) for v in rb[2].split()], [0.0, 0.0, 0.0])
        self.assertEqual([float(v) for v in rb[3].split()], [0.0, 0.0, 0.0])
        self.assertFalse(_has(res.warnings, "J = -SUM(IN)"))
        self.assertFalse(_has(res.warnings, _W_B2_DENSITY))   # rigid: no cell

    def test_bcs_skewed_keeps_digits_global_rot_permuted(self):
        """The fix round (F-B2-1 / F2). The node map P(v) = (vz, vx, vy) is a
        proper rotation. (a) A *BOUNDARY_SPC_SET on CID 5 (local x along LS
        y, local y along -x) holding local x: LS-DYNA holds LS y = Radioss
        Z. The /SKEW/FIX/5 vectors are permuted (Y' = (0, -1, 0), Z' =
        (1, 0, 0), so X' = Y' x Z' = (0, 0, 1) = Radioss Z) and the code must
        stay '100' in skew 5 - the round-9 rewrite wrote '010' (Y' = LS -x,
        the wrong axis, no warning). (b) A rigid part with CMO 1 CON2 3
        (LS z rotation, the out-of-plane axis): P maps it to rot X = '100',
        which an N2D-1 rigid body does not carry (rgbodv.F:158-180 keeps
        VR(3) only); the round-9 rewrite wrote '001' = the spin about the
        axis of revolution, which LS-DYNA leaves free. CON2 2 (LS y = the
        axis) -> '001'. The base deck's global translations stay '010' /
        '001'. Corpus reach 0 (metal-forming and 2Dlag hold Rot 111).
        STARTER (nt 4, C:/Users/pmqua/rcv_r9i_fixpr_<name>, harvested and
        deleted): (a) b2skew, (b) b2rig3 and b2rig2 each 0 ERROR(S) / 0
        WARNING(S), N2D3D 1."""
        skew_spc = ("*DEFINE_COORDINATE_SYSTEM\n"
                    + _f10(5, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0) + "\n"
                    + _f10(-1.0, 0.0, 0.0) + "\n"
                    + "*SET_NODE_LIST\n" + _f10(7) + "\n" + _f10(8) + "\n"
                    + "*BOUNDARY_SPC_SET\n" + _f10(7, 5, 1, 0, 0, 0, 0, 0)
                    + "\n")
        res, st, _e = _convert(b2_ax15().replace("*END", skew_spc + "*END"))
        self.assertTrue(re.search(r"^/QUAD/1", st, re.M))
        rows = sorted((t, r, s) for t, r, s, _g in _bcs_rows(st))
        self.assertEqual(rows, [("001", "000", 0), ("010", "000", 0),
                                ("100", "000", 5)])
        sk = [b for h, b in _blocks(st, "/SKEW/FIX/5")][0]
        self.assertEqual([[float(v) for v in ln.split()] for ln in sk[1:4]],
                         [[0.0, 0.0, 0.0], [0.0, -1.0, 0.0],
                          [1.0, 0.0, 0.0]])

        def rigid(con2):
            return ("*PART\nrigid tool\n" + _f10(2, 2, 2) + "\n"
                    "*SECTION_SHELL\n" + _f10(2, 15, 1.0, 2) + "\n"
                    + _f10(1.0, 1.0, 1.0, 1.0) + "\n"
                    "*MAT_RIGID\n" + _f10(2, 7.85e-9, 210000.0, 0.3) + "\n"
                    + _f10(1.0, 0, con2) + "\n" + _f10(0.0) + "\n"
                    "*NODE\n" + "".join(
                        "%8d%16.8g%16.8g%16.8g\n" % (
                            200 + k, 5.0 + (k in (1, 2)), float(k in (2, 3)),
                            0.0) for k in range(4))
                    + "*ELEMENT_SHELL\n" + "%8d%8d" % (50, 2)
                    + "".join("%8d" % (200 + k) for k in range(4)) + "\n")
        for con2, rot in ((3, "100"), (2, "001")):
            with self.subTest(con2=con2):
                r2, st2, _e = _convert(b2_ax15().replace(
                    "*END", rigid(con2) + "*END"))
                self.assertTrue(re.search(r"^/QUAD/1", st2, re.M))
                body = [(t, r) for t, r, s, _g in _bcs_rows(st2)
                        if r != "000"]
                self.assertEqual(body, [("000", rot)])

    def test_clockwise_quad_reordered(self):
        res, st, _e = _convert(b2_ax15(var="cw"))
        quad = [b for h, b in _blocks(st, "/QUAD/1")][0]
        self.assertEqual([int(t) for t in quad[0].split()], [1, 1, 2, 6, 5])
        self.assertTrue(_has(res.warnings, "6 /SHELL become /QUAD (1 "
                             "re-ordered counter-clockwise)"))

    def test_opt_out_is_386444e(self):
        res, st, eng = _convert(b2_ax15(), axisymmetric_2d=False)
        self.assertEqual(_sha(st), _B2_AX15_386444E_STARTER)
        self.assertEqual(_sha(eng), _B2_AX15_386444E_ENGINE)
        self.assertTrue(_has(res.warnings, _WA7B_R9, "--no-axisymmetric-2d "
                             "keeps the 3-D shell; the default writes the 2-D "
                             "route"))
        self.assertFalse(_has(res.warnings, _W_B2_ROUTED))

    def test_non_axisymmetric_decks_untouched(self):
        for e in (13, 2):
            with self.subTest(elform=e):
                deck = _t8._quad_deck(elform=e)
                _r, a, ea = _convert(deck)
                _r, b, eb = _convert(deck, axisymmetric_2d=False)
                self.assertEqual(_sha(a), _sha(b))
                self.assertEqual(_sha(ea), _sha(eb))
                self.assertFalse(re.search(r"^/QUAD/", a, re.M))

    def test_transform_guard(self):
        """Screen 7: an emitted card the transform does not map (a synthetic
        /GRAV block) makes it return the 3-D lines and the reason."""
        from k2rad.writer import axisym2d
        from k2rad.state import AxisymPlan
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(b2_ax15())
        from k2rad.parser import parse_k_file
        from k2rad.handlers import dispatch
        from k2rad.state import ConversionState
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        tmp.cleanup()
        plan = AxisymPlan(candidate=True, routed=True, elform=15, pids=[1])
        lines = ["/NODE", "         1                   0                 "
                 "  0                   0", "/GRAV/1", "g", "#"]
        out, why, _c = axisym2d._transform_starter_lines(state, lines, plan)
        self.assertEqual(out, lines)
        self.assertEqual(why, "/GRAV/1")
        out2, why2, c2 = axisym2d._transform_starter_lines(
            state, lines[:2], plan)
        self.assertEqual(why2, "")
        self.assertEqual(out2[1].split(), ["1", "0", "0", "0"])
        self.assertEqual(c2["node"], 1)


_WA7B_R9 = "is a 2-D AXISYMMETRIC formulation"


# ═════════════════════════════════════════════════════════════════════════════
# B3 - *SECTION_SHELL ELFORM 12 stating no thickness -> Thick 1.0
#      (default ON, --no-plane-stress-unit-thickness)
# ═════════════════════════════════════════════════════════════════════════════

_W_B3 = ("ELFORM 12 (2-D plane stress) states no thickness (T1..T4 = 0 / "
         "blank), so the /PROP/SHELL thickness is 1.0")
#: the 386444e (pristine10) test-path digest of _t8._quad_deck(elform=12,
#: t=(0.0, "", "", "")) - the opt-out must reproduce it
_B3_T0_386444E_STARTER = (
    "9e5e750ea88f4264f5956beca7cf91bbb5687839aee26998d47412295d18e83f")


class PlaneStressUnitThickness(unittest.TestCase):
    """B3 (R14 triage round 9): a 2-D plane-stress *SECTION_SHELL (ELFORM 12)
    whose Card 2 states NO thickness is written with thickness 1.0 (LS-DYNA
    integrates a unit thickness: main_fsi's rigid mass 0.23410459 = rho x
    area x 1.0); a stated T1 > 0 is kept. STARTER (nt 4): the production
    main_fsi _0000.rad reads 0 ERROR(S) / 1 WARNING (1084), TOTAL MASS
    0.2341045880 (386444e: 117 ERROR(S)); the rigid probe below reads its
    /RBODY mass 7.85e-7 = rho x 100 x 1.0."""

    def test_1_no_thickness_gives_one(self):
        for t in ((0.0, "", "", ""), (0.0, 0.0, 0.0, 0.0), ("", "", "", "")):
            with self.subTest(card2=t):
                res, st, _e = _convert(_t8._quad_deck(elform=12, t=t))
                self.assertEqual(_t8._prop_thick(st), 1.0)
                self.assertTrue(_has(res.warnings, _W_B3, "0.23410459",
                                     "a stated T1 > 0 is kept",
                                     "117 ERROR(S) -> 0"))

    def test_2_a_stated_thickness_is_kept(self):
        res, st, _e = _convert(_t8._quad_deck(elform=12,
                                              t=(25.4, "", "", "")))
        self.assertEqual(_t8._prop_thick(st), 25.4)
        self.assertFalse(_has(res.warnings, _W_B3))

    def test_3_a_partial_card_keeps_the_A4_reading(self):
        """T1 0 with a nonzero T2 (decision B3-a): today's A4 mean
        (0 + 2 + 0 + 0) / 4 = 0.5, not 1.0."""
        res, st, _e = _convert(_t8._quad_deck(elform=12,
                                              t=(0.0, 2.0, 0.0, 0.0)))
        self.assertEqual(_t8._prop_thick(st), 0.5)
        self.assertFalse(_has(res.warnings, _W_B3))

    def test_4_the_opt_out_is_386444e(self):
        res, st, _e = _convert(_t8._quad_deck(elform=12, t=(0.0, "", "", "")),
                               plane_stress_unit_thickness=False)
        self.assertEqual(_t8._prop_thick(st), 0.0)
        self.assertEqual(_sha(st), _B3_T0_386444E_STARTER)
        self.assertFalse(_has(res.warnings, _W_B3))

    def test_5_other_elforms_are_not_this_rule(self):
        _r, st2, _e = _convert(_t8._quad_deck(elform=2, t=(0.0, "", "", "")))
        self.assertEqual(_t8._prop_thick(st2), 0.0)
        r13, st13, _e = _convert(_t8._quad_deck(elform=13,
                                                t=(0.0, "", "", "")))
        self.assertEqual(_t8._prop_thick(st13), 1.0)     # A7, not B3
        self.assertFalse(_has(r13.warnings, _W_B3))

    def test_6_a_rigid_plane_stress_part(self):
        res, st, _e = _convert(_t8._quad_deck(elform=12, t=(0.0, "", "", ""),
                                              rigid=True))
        self.assertEqual(_t8._prop_thick(st), 1.0)
        self.assertTrue(re.search(r"^/RBODY/", st, re.M))
        self.assertTrue(_has(res.warnings, _W_B3))


# ═════════════════════════════════════════════════════════════════════════════
# B5 - an applied-load /FUNCT is zero off scale at BOTH ends, written at
#      emission (default ON, --no-load-curve-offscale-zero)
# ═════════════════════════════════════════════════════════════════════════════

def b5_punch(var="base"):
    """PUNCH-OFFA (round 9, B5; the part-B spec's probe, gen_b5.py): a rigid
    punch (one 10 x 10 mm *MAT_RIGID shell, part 2, node 101 first) driven in
    z by *BOUNDARY_PRESCRIBED_MOTION_RIGID (DOF 3, VAD 0, LCID 1, SF -20)
    above a 2 x 2 x 1 elastic block (part 1, base held), no contact; curve 1
    = the cup-draw's first points with OFFA 0.002 -> (0.002, 0) (0.0023,
    1.644664) (0.0026, 3.287704) (0.0036, 3.287704); ENDTIM 0.004 (the curve
    ends before it: an end side too). *var* names a forbidden class or a
    control."""
    sfa, offa, dattyp = 1.0, 0.002, 0
    pts = [(0.0, 0.0), (0.0003, 1.644664), (0.0006, 3.287704),
           (0.0016, 3.287704)]
    if var in ("dattyp1", "offa_neg", "offa0", "sfa2", "matcurve",
               "matonly"):
        pts = [(0.0, 0.0), (0.0003, 1.644664), (0.0006, 3.287704),
               (0.01, 3.287704)]
    if var == "dattyp1":
        dattyp = 1
    if var == "offa_neg":
        offa = -0.0001
    if var == "offa0":
        offa = 0.0
    if var == "sfa2":
        sfa = 2.0
    if var == "covering":
        offa = 0.0
        pts = [(0.0, 0.0), (0.0003, 1.644664), (0.0006, 3.287704),
               (0.01, 3.287704)]
    if var == "endonly":
        offa = 0.0
        pts = [(0.0, 3.287704), (0.003, 3.287704)]
    L = ["*KEYWORD", "*TITLE", "B5 PUNCH-OFFA probe (%s)" % var,
         "*CONTROL_TERMINATION", _f10(0.004),
         "*DATABASE_GLSTAT", _f10(1.0e-5), "*DATABASE_MATSUM", _f10(1.0e-5),
         "*DATABASE_NODOUT", _f10(1.0e-5),
         "*DATABASE_HISTORY_NODE", _f10(101),
         "*PART", "block", _f10(1, 1, 1), "*SECTION_SOLID", _f10(1, 1),
         "*MAT_ELASTIC", _f10(1, 7.85e-9, 210000.0, 0.3),
         "*PART", "punch", _f10(2, 2, 2), "*SECTION_SHELL", _f10(2, 2, 1.0, 2),
         _f10(1.0, 1.0, 1.0, 1.0),
         "*MAT_RIGID", _f10(2, 7.85e-9, 210000.0, 0.3), _f10(0.0, 0, 0),
         _f10(0.0)]
    if var in ("matcurve", "matonly"):
        L += ["*PART", "plastic", _f10(3, 1, 3),
              "*MAT_PIECEWISE_LINEAR_PLASTICITY",
              _f10(3, 7.85e-9, 210000.0, 0.3, 200.0, 0.0, 0.0, 0.0),
              _f10(0.0, 0.0, 1, 0), _f10(0.0), _f10(0.0)]
    L += ["*NODE"]
    k = 1
    for z in (0.0, 1.0):
        for y in (0.0, 1.0, 2.0):
            for x in (0.0, 1.0, 2.0):
                L.append("%8d%16.8g%16.8g%16.8g" % (k, x, y, z))
                k += 1
    for p in [(101, -4.0, -4.0, 1.5), (102, 6.0, -4.0, 1.5),
              (103, 6.0, 6.0, 1.5), (104, -4.0, 6.0, 1.5)]:
        L.append("%8d%16.8g%16.8g%16.8g" % p)
    if var in ("matcurve", "matonly"):
        for p in [(201, 10.0, 0.0, 0.0), (202, 11.0, 0.0, 0.0),
                  (203, 11.0, 1.0, 0.0), (204, 10.0, 1.0, 0.0),
                  (205, 10.0, 0.0, 1.0), (206, 11.0, 0.0, 1.0),
                  (207, 11.0, 1.0, 1.0), (208, 10.0, 1.0, 1.0)]:
            L.append("%8d%16.8g%16.8g%16.8g" % p)
    L += ["*ELEMENT_SOLID"]

    def n(i, j, kk):
        return 1 + kk * 9 + j * 3 + i
    e = 1
    for j in range(2):
        for i in range(2):
            c = [n(i, j, 0), n(i + 1, j, 0), n(i + 1, j + 1, 0),
                 n(i, j + 1, 0), n(i, j, 1), n(i + 1, j, 1),
                 n(i + 1, j + 1, 1), n(i, j + 1, 1)]
            L.append("%8d%8d" % (e, 1) + "".join("%8d" % x for x in c))
            e += 1
    if var in ("matcurve", "matonly"):
        L.append("%8d%8d" % (9, 3) + "".join("%8d" % x
                                              for x in range(201, 209)))
    L += ["*ELEMENT_SHELL", "%8d%8d%8d%8d%8d%8d" % (101, 2, 101, 102, 103,
                                                     104)]
    base = [n(i, j, 0) for j in range(3) for i in range(3)]
    L += ["*SET_NODE_LIST", _f10(1)] + [_f10(*base[c:c + 8])
                                        for c in range(0, len(base), 8)]
    L += ["*BOUNDARY_SPC_SET", _f10(1, 0, 1, 1, 1, 1, 1, 1)]
    birth = {"birth": 0.0005, "birth3": 0.003}.get(var, 0.0)
    if var != "matonly":
        L += ["*BOUNDARY_PRESCRIBED_MOTION_RIGID",
              _f10(2, 3, 0, 1, -20.0, 0, 1.0e28, birth)]
    L += ["*DEFINE_CURVE", _f10(1, 0, sfa, 1.0, offa, 0.0, dattyp)] + [
        "%20.8g%20.8g" % p for p in pts]
    L += ["*END", ""]
    return "\n".join(L)


_W_B5 = ("an applied-load curve is zero off its abscissa range in LS-DYNA "
         "(Vol I R17 *DEFINE_CURVE Remark 5")
#: the 386444e (pristine10) test-path digest of b5_punch() - the opt-out
#: must reproduce it
_B5_PUNCH_386444E_STARTER = (
    "79b8e9c574c47bcf343f11aabe1c1580b13d7b22ee08b1f8686021a79b89baaa")


def _funct_rows(starter: str, fid: int):
    head = f"/FUNCT/{fid}"
    lines = starter.splitlines()
    i = lines.index(head)
    out = []
    for ln in lines[i + 2:]:
        if ln.startswith("/"):
            break
        if not ln.startswith("#"):
            out.append(ln)
    return out


class LoadCurveOffscaleZero(unittest.TestCase):
    """B5 (R14 triage round 9): a mechanical applied-load consumer reads a
    COPY of its curve with LS-DYNA's zero points (Remark 4a before the first
    abscissa, Remark 5 after the last) where OpenRadioss would extrapolate it
    nonzero inside the consumer's window; state.curves and every other
    consumer keep the deck's curve. STARTER + ENGINE (nt 4,
    C:/Users/pmqua/rcv_r9i_implB_b5P / _b5B, base-paired): the probe's punch
    node 101 holds at DZ 0 until 2 ms and moves forward after; the opt-out
    drives it backward first (+0.0959 mm at 0.5 ms)."""

    def test_a_thermal_consumer_keeps_its_curve(self):
        """The fix round (F8): a THERMAL consumer is never padded - the
        synthetic weld deck with its convection T_inf on curve 303, which
        ends at t 1.0 before ENDTIM 3.0, writes no offscale copy and no B5
        sentence (routing that /CONVEC through load_funct_id survived the
        round-9 suite)."""
        res, st, _e = _convert(b1_synw("convcurve"))
        self.assertIn("/CONVEC/", st)
        self.assertNotIn("offscale_zero", st)
        self.assertFalse(_has(res.warnings, _W_B5))
        _r0, st0, _e0 = _convert(b1_synw("convcurve"),
                                 load_curve_offscale_zero=False)
        self.assertEqual(st, st0)

    def test_punch_probe_both_ends(self):
        res, st, _e = _convert(b5_punch())
        fid, pts = _funct_points(st, "FUNCT_1_offscale_zero")
        self.assertEqual(pts, [(0.0, 0.0), (0.001998, 0.0), (0.002, 0.0),
                               (0.0023, 1.644664), (0.0026, 3.287704),
                               (0.0036, 3.287704), (0.00360036, 0.0),
                               (0.008, 0.0)])
        self.assertEqual(len([ln for ln in st.splitlines()
                              if ln == "FUNCT_1_offscale_zero"]), 1)
        imp = [b for h, b in _blocks(st, "/IMPVEL/")][0]
        self.assertEqual(int(imp[1][:10]), fid)
        _r0, st0, _e0 = _convert(b5_punch(), load_curve_offscale_zero=False)
        self.assertEqual(_funct_rows(st, 1), _funct_rows(st0, 1))
        self.assertTrue(_has(res.warnings, _W_B5, "/IMPVEL consumer(s)",
                             "at both ends",
                             f"/FUNCT/1 -> /FUNCT/{fid} ((0, 0) and "
                             "(0.001998, 0) before 0.002; (0.00360036, 0) and "
                             "(0.008, 0) after 0.0036)",
                             "+6.09 -> +13.10 %", "MIXED",
                             "KE END +91.96 -> +23.42 %"))
        state = _t7._dispatch(b5_punch())
        self.assertEqual(state.curves[1].pts,
                         [(0.002, 0.0), (0.0023, 1.644664),
                          (0.0026, 3.287704), (0.0036, 3.287704)])

    def test_forbidden_classes_are_byte_identical(self):
        for var in ("dattyp1", "offa_neg", "offa0", "sfa2", "covering"):
            with self.subTest(probe=var):
                deck = b5_punch(var)
                res, st, _e = _convert(deck)
                _r0, st0, _e0 = _convert(deck, load_curve_offscale_zero=False)
                self.assertEqual(_sha(st), _sha(st0))
                self.assertFalse(_has(res.warnings, _W_B5))
        from k2rad.writer.loadcurves import load_funct_id
        state = _t7._dispatch(b5_punch())
        self.assertEqual(load_funct_id(state, 1, "IMPVEL", sensor_id=7), 1)
        self.assertEqual(state.offscale_functs, {})
        self.assertNotEqual(load_funct_id(state, 1, "IMPVEL"), 1)

    def test_material_and_preload_consumers_keep_the_original(self):
        # (a) a curve feeding ONLY a material: no consumer asks for a copy
        _r, st, _e = _convert(b5_punch("matonly"))
        _r0, st0, _e0 = _convert(b5_punch("matonly"),
                                 load_curve_offscale_zero=False)
        self.assertEqual(_sha(st), _sha(st0))
        self.assertNotIn("FUNCT_1_offscale_zero", st)
        # (c) the same curve feeding a load AND a material: the load reads
        # the copy, the material keeps /FUNCT/1 as stated
        res, stc, _e = _convert(b5_punch("matcurve"))
        _r0, stc0, _e0 = _convert(b5_punch("matcurve"),
                                  load_curve_offscale_zero=False)
        fid, pts = _funct_points(stc, "FUNCT_1_offscale_zero")
        self.assertEqual(pts[:2], [(0.0, 0.0), (0.001998, 0.0)])
        self.assertEqual(_funct_rows(stc, 1), _funct_rows(stc0, 1))
        imp = [b for h, b in _blocks(stc, "/IMPVEL/")][0]
        self.assertEqual(int(imp[1][:10]), fid)
        mat = [b for h, b in _blocks(stc, "/MAT/LAW36/3")]
        self.assertTrue(mat)
        self.assertNotIn(str(fid), "".join(mat[0]))

    def test_end_side_only(self):
        _r, st, _e = _convert(b5_punch("endonly"))
        _fid, pts = _funct_points(st, "FUNCT_1_offscale_zero")
        self.assertEqual(pts, [(0.0, 3.287704), (0.003, 3.287704),
                               (0.0030003, 0.0), (0.008, 0.0)])

    def test_birth_inside_the_lead_in(self):
        _r, st, _e = _convert(b5_punch("birth"))
        _fid, pts = _funct_points(st, "FUNCT_1_offscale_zero")
        self.assertEqual(pts[:2], [(0.0, 0.0), (0.001998, 0.0)])
        _r, st3, _e = _convert(b5_punch("birth3"))
        _fid, pts3 = _funct_points(st3, "FUNCT_1_offscale_zero")
        self.assertEqual(pts3[0], (0.002, 0.0))     # no start points
        self.assertEqual(pts3[-2:], [(0.00360036, 0.0), (0.008, 0.0)])

    def test_ascale_x_maps_the_window(self):
        from k2rad.writer.loadcurves import load_funct_id
        state = _t7._dispatch(b5_punch("endonly"))
        state.curves[1].pts = [(0.0, 3.287704), (0.0025, 3.287704)]
        # ENDTIM 0.004 with Ascale_x 2: x_b = 0.002 < 0.0025 -> no end side
        self.assertEqual(load_funct_id(state, 1, "IMPVEL", ascale_x=2.0), 1)
        # Ascale_x 1: x_b = 0.004 > 0.0025 -> the end side
        self.assertNotEqual(load_funct_id(state, 1, "IMPVEL"), 1)

    def test_the_curve_pins_are_untouched(self):
        """The emission-side rule never edits state.curves (a parse-time
        prepend would fail tests/test_converter.py's CurveOffsetScaleOrder,
        tests/test_r14_triage_8.py:887-891 and
        tests/test_preload_inistate.py:781-788): the probe's curve keeps
        the handler's ((a + OFFA) SFA, (o + OFFO) SFO) points after a full
        conversion."""
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(b5_punch())
        from k2rad.parser import parse_k_file
        from k2rad.handlers import dispatch
        from k2rad.state import ConversionState
        from k2rad.writer.assembly import build_starter
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        before = list(state.curves[1].pts)
        build_starter(state)
        self.assertEqual(state.curves[1].pts, before)
        self.assertEqual(len(state.offscale_functs), 1)
        tmp.cleanup()

    def test_opt_out_is_386444e(self):
        res, st, _e = _convert(b5_punch(), load_curve_offscale_zero=False)
        self.assertEqual(_sha(st), _B5_PUNCH_386444E_STARTER)
        self.assertFalse(_has(res.warnings, _W_B5))


# ═════════════════════════════════════════════════════════════════════════════
# B6 - the A4 warning's mechanism clause (the cup-draw energy balance)
# ═════════════════════════════════════════════════════════════════════════════

class B6MechanismClause(unittest.TestCase):
    """B6 (R14 triage round 9; text only): round 8's A4 mean-thickness
    sentence names WHY OpenRadioss's energy error grows on the cup-draw - the
    ENERGY ERROR counts no interface energy (ecrit.F:500-511) and the TYPE7
    VisS damping work has no channel (i7for3.F:1077-1120) - with the
    measured numbers (cG4: VisS 0.05 vs 1e-6 vs T1, with and without the T01
    CONTACT_ENERGY). The round-8 figure pins stay (the needle "-4.39 ->
    -17.88 %" is kept verbatim); both A4 carriers (the cup-draw and
    section_shell.hourglassing) print the one shared sentence."""

    def test_the_warning_carries_the_mechanism(self):
        res, _st, _e = _convert(_t8._quad_deck(t=(2.0, 4.0, "", 0.0)))
        self.assertTrue(_has(
            res.warnings, "the /PROP/SHELL thickness is their MEAN",
            "OpenRadioss's energy error grows: mean -4.39 -> -17.88 %",
            "ecrit.F:500-511", "i7for3.F:1077-1120",
            "k2rad maps VDC 5 to VisS 0.05", "-5.04 %", "1426.1 N.mm",
            "141.0", "-38.10 %", "-14.52 / -1.41 / -1.79 %"))
        self.assertFalse(_has(res.warnings, "mechanism not closed"))

    def test_the_help_carries_the_mechanism(self):
        from k2rad import cli
        flat = _t7._collapse(cli.build_parser().format_help())
        self.assertIn("ecrit.F:500-511, i7for3.F:1077-1120; with VisS 1e-6 "
                      "the mean is -5.04 %", flat)
        self.assertIn("-4.39 -> -17.88 %", flat)


# ═════════════════════════════════════════════════════════════════════════════
# B7 - the F1 hourglass-guard cap h' = min(h_eff, 0.14 / Tsca) / max(1, R)
#      (inside --mat-null-pc-mu)
# ═════════════════════════════════════════════════════════════════════════════

def _b7_deck(c: str, hourglass: str = "", tssfac: str = "") -> str:
    """Round 8's viscous brick (one 1 mm ELFORM-6 cube, *MAT_NULL RO 1e-9 MU
    1e-5 -> Nu 1e4, *EOS_GRUNEISEN C *c*: R = 10 Nu / (c dmin) = 1e5 / c),
    optionally on *HOURGLASS IHQ 1 QH *hourglass* and *CONTROL_TIMESTEP
    TSSFAC *tssfac*."""
    deck = _t8._visc_brick_deck(sizes=(1.0,), c=c, hourglass=hourglass)
    if tssfac:
        deck = deck.replace("*KEYWORD\n", "*KEYWORD\n*CONTROL_TIMESTEP\n"
                            + _row(0.0, float(tssfac)) + "\n", 1)
    return deck


def _b7_h(starter: str) -> float:
    props = [ln for ln in starter.splitlines()
             if ln.startswith("/PROP/SOLID/")]
    return float(_t8._prop_h(starter, int(props[0].rsplit("/", 1)[1])))


class HourglassGuardCap(unittest.TestCase):
    """B7 (R14 triage round 9): round 8's F1 guard divided a STATED h by R
    only; cG1's Couette coupon (critic_G1/gen_cou_c.py, nt 4) left QH 0.2 at
    R 1.2 unstable after the division (h 0.1667: energy error +16.2 %,
    hourglass energy 732.6 mJ) and stable with the cap (h 0.1296: 8.0e-12
    mJ). Hand values: Nu = 1e-5 / 1e-9 = 1e4; R = 1e5 / C; the cap 0.14 /
    0.9 = 0.155556 (0.2 at TSSFAC 0.7)."""

    def test_1_r12_qh02_is_capped_then_divided(self):
        res, st, _e = _convert(_b7_deck("83333.3333", hourglass="0.2"))
        self.assertAlmostEqual(_b7_h(st), 0.14 / 0.9 / 1.2, places=9)
        self.assertAlmostEqual(_b7_h(st), 0.1296296296, places=9)
        self.assertTrue(_has(res.warnings, "R = 10 Nu / (c0 dmin) = 1.2 > 1",
                             "= min(0.2, 0.14 / Tsca) / R",
                             "is first capped at 0.14 / Tsca = 0.155556 "
                             "(Tsca 0.9)", "732.6 mJ", "8.0e-12 mJ"))

    def test_2_r095_qh02_is_capped_with_its_own_sentence(self):
        res, st, _e = _convert(_b7_deck("105263.158", hourglass="0.2"))
        self.assertAlmostEqual(_b7_h(st), 0.14 / 0.9, places=9)
        self.assertTrue(_has(res.warnings, "R = 0.95 <= 1, but the stated "
                             "hourglass coefficient 0.2 exceeds 0.14 / Tsca "
                             "= 0.155556, so h is written 0.155556",
                             "--no-mat-null-pc-mu"))

    def test_3_the_default_h_is_unchanged(self):
        _r, st, _e = _convert(_b7_deck("31622.7766"))
        self.assertEqual(_t8._prop_h(st, 1), "        0.0316227766")

    def test_4_a_stated_h_below_the_cap_keeps_todays_bytes(self):
        deck = _b7_deck("105263.158", hourglass="0.1")
        res, st, _e = _convert(deck)
        _r0, st0, _e0 = _convert(deck, mat_null_pc_mu=False)
        self.assertAlmostEqual(_b7_h(st), 0.1, places=12)
        self.assertEqual(_b7_h(st), _b7_h(st0))
        self.assertFalse(_has(res.warnings, "0.14 / Tsca"))

    def test_5_tssfac_moves_the_cap(self):
        res, st, _e = _convert(_b7_deck("83333.3333", hourglass="0.3",
                                        tssfac="0.7"))
        self.assertAlmostEqual(_b7_h(st), 0.2 / 1.2, places=9)
        self.assertTrue(_has(res.warnings, "capped at 0.14 / Tsca = 0.2 "
                             "(Tsca 0.7)"))

    def test_6_the_opt_out_keeps_the_stated_h(self):
        res, st, _e = _convert(_b7_deck("83333.3333", hourglass="0.2"),
                               mat_null_pc_mu=False)
        self.assertAlmostEqual(_b7_h(st), 0.2, places=12)
        self.assertFalse(_has(res.warnings, "0.14 / Tsca"))


# ═════════════════════════════════════════════════════════════════════════════
# B8 - OPT-IN --ale-flow-tracking: *ALE_REFERENCE_SYSTEM_GROUP PRTYPE 4 ->
#      /ALE/GRID/FLOW-TRACKING
# ═════════════════════════════════════════════════════════════════════════════

def b8_bird(card: bool = True, prtype: int = 4, prid: int = 0,
            bctran: int = 3, bcexp: int = 7, bcrot: int = 0, icr: int = 0,
            stype: int = 0, set_parts=(4, 5), n_cards: int = 1,
            extra: str = "", tc: int = 3, void: bool = True,
            clis: bool = False, mu: str = "1E-05") -> str:
    """bird_B in miniature (round 9, B8): two ELFORM-12 hexes on ONE
    *MAT_NULL 2 (RO 7.81e-10, PC -1, MU *mu*) + *EOS_LINEAR_POLYNOMIAL 2 -
    part 4 (x 0..1, the host, *INITIAL_VOID_PART when *void*) and part 5 (x
    1..2, the bird) - every ALE node at *NODE TC *tc*; a one-quad shell plate
    part 3 at x 3 (ELFORM 2, *MAT_ELASTIC 1); *CONTROL_ALE as bird_B's;
    *SET_PART_LIST 1 = *set_parts*; *n_cards* *ALE_REFERENCE_SYSTEM_GROUP
    cards (SID 1, STYPE *stype*, PRTYPE *prtype*, PRID *prid*, BCTRAN
    *bctran*, BCEXP *bcexp*, BCROT *bcrot*, ICR *icr*) when *card*; *extra*
    ("NODE", "CURVE", "SWITCH") adds an *ALE_REFERENCE_SYSTEM_<extra> card;
    *clis* couples the plate to set 1 with bird_B's
    *CONSTRAINED_LAGRANGE_IN_SOLID."""
    out = ["*KEYWORD", "*TITLE", "b8 bird",
           "*CONTROL_ALE",
           _row(0, 1, 1, -1.0, 0.0, 0.0, 0.0, 0.0),
           _row(0.0, "1E+17", 1.0, "1.00000E-6", 0, 0, 0.0, 0),
           "*CONTROL_TERMINATION", _row("1.0E-4"),
           "*PART", "plate", _row(3, 1, 1),
           "*SECTION_SHELL", _row(1, 2, 1.0, 2), _row(1.0, 1.0, 1.0, 1.0),
           "*MAT_ELASTIC", _row(1, "1E-09", 1000, 0.0),
           "*PART", "void host", _row(4, 2, 2, 2),
           "*PART", "bird", _row(5, 2, 2, 2),
           "*SECTION_SOLID", _row(2, 12),
           "*MAT_NULL", _row(2, "7.81E-10", -1, mu),
           "*EOS_LINEAR_POLYNOMIAL", _row(2, 0.0, 1, 0.0, 0.0, 0.0, 0.0, 0.0),
           _row(0.0, 0.0)]
    if void:
        out += ["*INITIAL_VOID_PART", _row(4)]
    out += ["*SET_PART_LIST", _row(1), _row(*set_parts)]
    if card:
        for _k in range(n_cards):
            out += ["*ALE_REFERENCE_SYSTEM_GROUP",
                    _row(1, stype, prtype, prid, bctran, bcexp, bcrot, icr),
                    _row(0.0, 0.0, 0.0, 0.0, 0.0, "", 0.0, 0)]
    if extra:
        out += [f"*ALE_REFERENCE_SYSTEM_{extra}", _row(1, 0, 0)]
    if clis:
        out += ["*CONSTRAINED_LAGRANGE_IN_SOLID",
                _row(3, 1, 1, 0, 2, 4, 2, 1),
                _row(0.0, 10000000, 0.1, 0.0, 0.5, 0, 0, 0.0),
                _row(0.0, 0.0, 0.0, 0, 0.1, 0, 0, 0)]
    out.append("*ELEMENT_SOLID")
    for i, pid in ((0, 4), (1, 5)):
        n = [1 + (i + di) * 4 + dj * 2 + dk
             for (di, dj, dk) in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                                  (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))]
        out.append(f"{i + 1:>8}{pid:>8}" + "".join(f"{v:>8}" for v in n))
    out += ["*ELEMENT_SHELL", f"{11:>8}{3:>8}{101:>8}{102:>8}{103:>8}{104:>8}"]
    out.append("*NODE")
    for i in range(3):
        for j in range(2):
            for k in range(2):
                out.append(f"{1 + i * 4 + j * 2 + k:>8}{float(i):>16}"
                           f"{float(j):>16}{float(k):>16}{tc:>8}{0:>8}")
    for nid, (y, z) in zip((101, 102, 103, 104),
                           ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        out.append(f"{nid:>8}{3.0:>16}{y:>16}{z:>16}{0:>8}{0:>8}")
    out.append("*END")
    return "\n".join(out) + "\n"


#: the 386444e (pristine10) test-path digests of the B8 probes - the default
#: must reproduce them (porcelain --ignored empty before and after)
_B8_BASE_386444E_STARTER = (
    "3febbf8332019d8c14eeef1d14fb7a0ad5eb5b09ff3c2f7e4122c5b245e742a7")
_B8_NOCARD_386444E_STARTER = (
    "4dd744d05b356c143d392549a6cd8324ea4112337e785de1311568364a316dcc")
#: ... and of the warning list of b8_bird(card=False, mu="0.0") (no
#: *ALE_REFERENCE_SYSTEM_* card, no Nu sentence: today's list exactly)
_B8_NOCARD_MU0_386444E_WARNINGS = (
    "af288acf84ce9bd87899eeaee1e229831ef73d83f8dd06255c5f64852e4451ed")
#: the branch's flag-on digest of b8_bird() (starter-run below)
_B8_BASE_FT_STARTER = (
    "13459cdc3b531c90dcd77f8ca6328615ad9b3205573717b88ff1a1ee4c26b53c")
_B8_CARD = ["/ALE/GRID/FLOW-TRACKING",
            "#    I_def           scale_def",
            "        -1                   0",
            "#    I_rot           scale_rot",
            "         1                   0"]
_W_B8_SKIP = ("*ALE_REFERENCE_SYSTEM_GROUP 1 (PRTYPE 4) is skipped: its "
              "OpenRadioss analogue /ALE/GRID/FLOW-TRACKING is written only "
              "under --ale-flow-tracking")
_W_B8_REFUSED = ("*ALE_REFERENCE_SYSTEM_GROUP: not converted under "
                 "--ale-flow-tracking - ")


class AleFlowTracking(unittest.TestCase):
    """B8 (R14 triage round 9): OPT-IN --ale-flow-tracking writes ONE
    *ALE_REFERENCE_SYSTEM_GROUP PRTYPE 4 card (PRID 0, ICR 0, BCEXP 7, BCROT
    0 / 7, a set covering every Iale part, BCTRAN held by the ALE nodes' own
    /BCS) as /ALE/GRID/FLOW-TRACKING right after /DEF_SOLID in _0000.rad;
    anything else is refused by name. STARTER runs (nt 4,
    C:/Users/pmqua/rcv_r9i_implB_<name>, harvested and deleted): b8_bird()
    default (sha256 3febbf833201..., = 386444e) 0 ERROR(S) / 1 WARNING
    (1084); flag-on (13459cdc3b53...) 0 / 2 - 1084 + WARNING ID 100211
    "Unsupported option /ALE/GRID/FLOW-TRACKING in format < 2024", the card
    read; b8_bird(bcrot=7) flag-on (eddd1dbc8cf0...) 0 / 2 (the same pair);
    b8_bird(card=False) (4dd744d05b35...) 0 / 1 (1084);
    b8_bird(card=False, clis=True) (b04093e4bde1...) 0 / 2 (1084 x2). On
    bird_B itself the flag-on bytes equal the census arm
    rcv_r9p_g1a_gFT22's but for its kept '#-- SKIPPED:' line and its own
    /TH/PART."""

    def test_default_is_386444e(self):
        res, st, _e = _convert(b8_bird())
        self.assertEqual(_sha(st), _B8_BASE_386444E_STARTER)
        self.assertNotIn("/ALE/GRID", st)
        self.assertIn("#-- SKIPPED: *ALE_REFERENCE_SYSTEM_GROUP", st)
        hits = [w for w in res.warnings if w.startswith(_W_B8_SKIP)]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("RMS 253.09 -> 749.89 %", hits[0])
        # a *CONTROL_ALE deck WITHOUT a reference-system card: today's
        # bytes and today's warning list exactly (the generic note unchanged)
        res0, st0, _e0 = _convert(b8_bird(card=False, mu="0.0"))
        self.assertEqual(_sha(st0), _B8_NOCARD_386444E_STARTER)
        self.assertEqual(_sha("\n".join(res0.warnings)),
                         _B8_NOCARD_MU0_386444E_WARNINGS)
        self.assertTrue(_has(res0.warnings, "Mesh smoothing (*ALE_SMOOTHING "
                             "/ *ALE_REFERENCE_SYSTEM_*) has no /ALE 1:1 and "
                             "is not converted."))

    def test_card_bytes_bcrot0_and_bcrot7(self):
        res, st, eng = _convert(b8_bird(), ale_flow_tracking=True)
        self.assertEqual(_sha(st), _B8_BASE_FT_STARTER)
        lines = st.splitlines()
        i = lines.index("/ALE/GRID/FLOW-TRACKING")
        self.assertEqual(lines[i:i + 5], _B8_CARD)
        self.assertEqual(lines[i - 2:i], ["/DEF_SOLID", "         0"])
        self.assertEqual(st.count("/ALE/GRID"), 1)
        self.assertNotIn("/ALE/GRID", eng)
        self.assertIn("      2022         0", lines[:8])
        self.assertNotIn("#-- SKIPPED: *ALE_REFERENCE_SYSTEM_GROUP", st)
        self.assertNotIn("ALE_REFERENCE_SYSTEM_GROUP", res.skipped_keywords)
        self.assertTrue(_has(res.warnings, "*ALE_REFERENCE_SYSTEM_GROUP 1 "
                             "(PRTYPE 4, BCEXP 7, BCROT 0, BCTRAN 3) -> "
                             "/ALE/GRID/FLOW-TRACKING I_def -1 I_rot 1",
                             "alew7.F:186-227", "WARNING 100211",
                             "BCTRAN 3 is carried by the ALE nodes' own /BCS",
                             "+1484.66 -> +17.00 %", "253.09 -> 749.89 %",
                             "NEGATIVE RHO"), res.warnings)
        self.assertFalse(_has(res.warnings, _W_B8_SKIP))
        _r7, st7, _e7 = _convert(b8_bird(bcrot=7), ale_flow_tracking=True)
        lines7 = st7.splitlines()
        j = lines7.index("/ALE/GRID/FLOW-TRACKING")
        self.assertEqual(lines7[j + 4], "        -1                   0")
        self.assertEqual(lines7[j + 2], "        -1                   0")

    def test_every_refusal_class(self):
        cases = (
            ({"prtype": 0}, "PRTYPE 0: only PRTYPE 4 has an OpenRadioss "
                            "analogue (FLOW-TRACKING)"),
            ({"prtype": 5}, "PRTYPE 5: only PRTYPE 4"),
            ({"prtype": 3}, "PRTYPE 3: only PRTYPE 4"),
            ({"prid": 1}, "PRID 1: FLOW-TRACKING averages over every ALE "
                          "node"),
            ({"icr": 1}, "ICR 1: FLOW-TRACKING turns about the centre of "
                         "mass"),
            ({"bcexp": 0}, "BCEXP 0: FLOW-TRACKING's deformation term is "
                           "all-or-nothing (only BCEXP 7 = no expansion "
                           "maps)"),
            ({"bcexp": 3}, "BCEXP 3: FLOW-TRACKING's deformation term"),
            ({"bcrot": 4}, "BCROT 4: only BCROT 0 / 7 map to I_rot +1 / -1"),
            ({"set_parts": (5,)}, "set 1 misses ALE part(s) [4]"),
            # the fix round (F-T-1): the STYPE screen had no probe - its
            # removal survived the round-9 suite; STYPE 1 reads SID as a
            # PART id (part 1 does not exist), not as set 1 (which covers
            # both ALE parts and would be accepted)
            ({"stype": 2}, "STYPE 2: only a part set (0) or a part (1) names "
                           "the ALE parts"),
            ({"stype": 1}, "part 1 is not defined in the deck"),
            ({"n_cards": 2}, "2 *ALE_REFERENCE_SYSTEM_GROUP cards: "
                             "FLOW-TRACKING is one grid formulation for the "
                             "deck"),
            ({"extra": "NODE"}, "*ALE_REFERENCE_SYSTEM_NODE has no "
                                "OpenRadioss analogue"),
            ({"tc": 0}, "BCTRAN 3: OpenRadioss's FLOW-TRACKING has no "
                        "translation constraint and the ALE nodes do not all "
                        "hold direction(s) z"),
        )
        for kw, reason in cases:
            with self.subTest(case=kw):
                res, st, eng = _convert(b8_bird(**kw), ale_flow_tracking=True)
                self.assertNotIn("/ALE/GRID", st + eng)
                self.assertIn("#-- SKIPPED: *ALE_REFERENCE_SYSTEM_GROUP", st)
                hits = [w for w in res.warnings
                        if w.startswith(_W_B8_REFUSED)]
                self.assertEqual(len(hits), 1, res.warnings)
                self.assertIn(reason, hits[0])
                self.assertTrue(hits[0].endswith("; it stays listed as "
                                                 "skipped."))
                self.assertFalse(_has(res.warnings, _W_B8_SKIP))

    def test_keyed_on_the_card_only(self):
        """A void + *CONSTRAINED_LAGRANGE_IN_SOLID probe WITHOUT a
        reference-system card under the flag: byte-identical to the flag-off
        conversion (cG1: FLOW-TRACKING on quadrature_B, which states no card,
        drives the energy error -46.5 -> +99.9 %)."""
        deck = b8_bird(card=False, clis=True)
        r_on, s_on, e_on = _convert(deck, ale_flow_tracking=True)
        r_off, s_off, e_off = _convert(deck)
        self.assertEqual((s_on, e_on), (s_off, e_off))
        self.assertEqual(r_on.warnings, r_off.warnings)
        self.assertNotIn("/ALE/GRID", s_on)

    def test_w_n3_text(self):
        res, _s, _e = _convert(b8_bird())
        hits = [w for w in res.warnings
                if w.startswith("*MAT_NULL MU is NOT carried")
                and "+20691.23 %" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("*ALE_REFERENCE_SYSTEM_GROUP PRTYPE 4",
                       "--ale-flow-tracking", "+59.2 %", "+1504.57 %",
                       "the void / TYPE18 coupling item",
                       "OPEN fixed-grid ALE faces", "-0.1 %", "+2.4 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("the reference-system item first", hits[0])
        self.assertNotIn("which k2rad skips", hits[0])

    def test_the_other_spellings_are_recorded_and_skipped(self):
        for extra in ("NODE", "CURVE", "SWITCH"):
            with self.subTest(extra=extra):
                res, st, _e = _convert(b8_bird(card=False, extra=extra))
                self.assertIn(f"#-- SKIPPED: *ALE_REFERENCE_SYSTEM_{extra}",
                              st)
                self.assertTrue(_has(res.warnings,
                                     f"*ALE_REFERENCE_SYSTEM_{extra} has no "
                                     "OpenRadioss analogue and is skipped."))
        res, _s, _e = _convert(b8_bird(prtype=3))
        self.assertTrue(_has(res.warnings, "*ALE_REFERENCE_SYSTEM_GROUP 1 "
                             "(PRTYPE 3) has no OpenRadioss analogue and is "
                             "skipped."))


# ═════════════════════════════════════════════════════════════════════════════
# B4 - *CONSTRAINED_SHELL_IN_SOLID: the gate FAILED, so the re-tune (Gap 0.55
#      + /DT/INTER/CST on an SIS-alone deck) ships INSIDE the opt-in
#      --shell-in-solid-coupling; the default bytes are unchanged
# ═════════════════════════════════════════════════════════════════════════════

#: the 386444e (pristine10) test-path digests of _t8._sis_ale_deck() - the
#: default must reproduce them
_B4_SIS_386444E_STARTER = (
    "2d37f113f5e23c6c305944b6a950dfd4ba442e124a29f433f1cf30dd46355348")
_B4_SIS_386444E_ENGINE = (
    "2b92d74a3bda805d8ebefb7c5facc176f75329530be03139cc5e4c37b7b65176")
_W_B4_ROUND8 = ("*CONSTRAINED_SHELL_IN_SOLID (--shell-in-solid-coupling): "
                "this deck carries ")


def _b4_f10(*vals) -> str:
    out = ""
    for v in vals:
        if v is None:
            out += " " * 10
        elif isinstance(v, int):
            out += "%10d" % v
        else:
            s = "%10.4g" % v
            if len(s) > 10:
                s = "%10.3e" % v
            out += s
    return out


def b4_wh(xp: float = 20.5) -> str:
    """cG1's water-hammer SIS coupon (critic_G1/gen_wh_c.py, the generator
    rebuilt as a function): a 1-D ALE column 30 x 1 x 1 mm (ELFORM 12, 1 mm
    cells, y / z held), fluid part 2 = x 0..20 (*MAT_NULL RO 1e-9 +
    *EOS_GRUNEISEN C 1.5e6) at u0 1e4 mm/s, *INITIAL_VOID host part 1 = x
    20..30, a fixed 2 x 2 mm steel shell plate part 3 at x = *xp* (20.5 =
    mid-cell), *CONSTRAINED_SHELL_IN_SOLID_ID shells part 3 / solids part 1,
    TSSFAC 0.9, t_end 1e-4."""
    def nid(i, j, k):
        return 1 + i * 4 + j * 2 + k
    f10 = _b4_f10
    L = ["*KEYWORD", "*TITLE", "b4 water hammer XP=%g" % xp]
    L += ["*CONTROL_ALE", f10(3, 1, 1, 0.0, 0.0, 0.0, 0.0, 0.0),
          f10(0.0, 0.0, 0.0, 1.0e-6, 0, 0, 0.0, 0),
          f10(1, 50, 0, 0.0, 0.0, 0, 0.0, 0.0), f10(0, 0, 0, 1.0e-5)]
    L += ["*CONTROL_TERMINATION", f10(1.0e-4), "*CONTROL_TIMESTEP",
          f10(0.0, 0.9)]
    for pid, title in ((1, "void host"), (2, "fluid")):
        L += ["*PART", title, f10(pid, pid, pid, pid), "*SECTION_SOLID",
              f10(pid, 12), "*MAT_NULL",
              f10(pid, 1.0e-9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
              "*EOS_GRUNEISEN",
              f10(pid, 1.5e6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), f10(0.0)]
    L += ["*PART", "plate", f10(3, 3, 3), "*SECTION_SHELL",
          f10(3, 2, 0.0, 3, 1), f10(1.0, 1.0, 1.0, 1.0), "*MAT_ELASTIC",
          f10(3, 7.85e-9, 210000.0, 0.3)]
    L += ["*INITIAL_VOID_PART", f10(1), "*NODE"]
    for i in range(31):
        for j in (0, 1):
            for k in (0, 1):
                L.append("%8d%16.8g%16.8g%16.8g" % (nid(i, j, k), float(i),
                                                     float(j), float(k)))
    for p in ((1001, xp, -0.5, -0.5), (1002, xp, 1.5, -0.5),
              (1003, xp, 1.5, 1.5), (1004, xp, -0.5, 1.5)):
        L.append("%8d%16.8g%16.8g%16.8g" % p)
    L.append("*ELEMENT_SOLID")
    for i in range(30):
        pid = 2 if i < 20 else 1
        n = [nid(i, 0, 0), nid(i + 1, 0, 0), nid(i + 1, 1, 0), nid(i, 1, 0),
             nid(i, 0, 1), nid(i + 1, 0, 1), nid(i + 1, 1, 1), nid(i, 1, 1)]
        L.append("%8d%8d" % (i + 1, pid) + "".join("%8d" % x for x in n))
    L += ["*ELEMENT_SHELL", "%8d%8d%8d%8d%8d%8d" % (1001, 3, 1001, 1002,
                                                    1003, 1004)]
    L.append("*INITIAL_VELOCITY_NODE")
    for i in range(21):
        for j in (0, 1):
            for k in (0, 1):
                L.append(f10(nid(i, j, k), 1.0e4, 0.0, 0.0, 0.0, 0.0, 0.0, 0))
    ale = [nid(i, j, k) for i in range(31) for j in (0, 1) for k in (0, 1)]
    L += ["*SET_NODE_LIST", f10(1)]
    for c in range(0, len(ale), 8):
        L.append(f10(*ale[c:c + 8]))
    L += ["*SET_NODE_LIST", f10(2), f10(1001, 1002, 1003, 1004)]
    L += ["*BOUNDARY_SPC_SET", f10(1, 0, 0, 1, 1, 0, 0, 0),
          "*BOUNDARY_SPC_SET", f10(2, 0, 1, 1, 1, 1, 1, 1)]
    L += ["*SET_PART_LIST", f10(1), f10(3), "*SET_PART_LIST", f10(2),
          f10(1)]
    L += ["*CONSTRAINED_SHELL_IN_SOLID_ID", f10(1), f10(1, 2, 0, 0)]
    L += ["*END", ""]
    return "\n".join(L)


def _b4_blocks(contact: bool) -> str:
    """Two 10 mm steel bricks (parts 5 / 6, ELFORM 1, *MAT_ELASTIC 5) away
    from the SIS block, with a *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE between
    them when *contact* (the gate coupon's TYPE7 pair, in miniature)."""
    out = ["*NODE"]
    nid = 5000
    ids = {}
    for b, x0 in ((5, 100.0), (6, 112.5)):
        for k in range(2):
            for j in range(2):
                for i in range(2):
                    nid += 1
                    ids[(b, i, j, k)] = nid
                    out.append(f"{nid:>8}{x0 + 10.0 * i:>16.4f}"
                               f"{10.0 * j:>16.4f}{10.0 * k:>16.4f}")
    out.append("*ELEMENT_SOLID")
    for e, b in ((5001, 5), (5002, 6)):
        hx = [ids[(b, 0, 0, 0)], ids[(b, 1, 0, 0)], ids[(b, 1, 1, 0)],
              ids[(b, 0, 1, 0)], ids[(b, 0, 0, 1)], ids[(b, 1, 0, 1)],
              ids[(b, 1, 1, 1)], ids[(b, 0, 1, 1)]]
        out.append("".join(f"{v:>8}" for v in [e, b] + hx))
    out += ["*PART", "block A", _row(5, 5, 5), "*PART", "block B",
            _row(6, 5, 5), "*SECTION_SOLID", _row(5, 1), "*MAT_ELASTIC",
            _row(5, 7.85e-9, 210000.0, 0.3)]
    if contact:
        out += ["*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", _row(5, 6, 3, 3),
                _row(0.1, 0.0)]
    return "\n".join(out) + "\n"


def _b4_f(*vals) -> str:
    """k2rad's own 20-wide cells (writer.common._f) of *vals*."""
    return "".join(_t8._f(v) for v in vals)


def _b4_cst(engine: str):
    """``[(Tsca, Tmin)]`` of every /DT/INTER/CST block of an engine deck."""
    lines = engine.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if ln.startswith("/DT/INTER/CST"):
            cells = lines[i + 2]
            out.append((float(cells[:20]), float(cells[20:40])))
    return out


class ShellInSolidRetune(unittest.TestCase):
    """B4 (R14 triage round 9): the gate FAILED (/DT/INTER/CST is global -
    dtnoda.F:661-722, every node tagged at :111-122 - and on a water-hammer
    coupon with a TYPE7 pair beside the SIS it added mass to the pair's nodes
    in every arm), so the default keeps the 386444e bytes and the re-tune
    ships inside the opt-in: on a deck that is the SIS problem alone, Gap
    0.55 x the mean host edge + ONE /DT/INTER/CST Tsca Tmin, Tmin = 0.5 x
    Tsca x min(host edge / c_host, shortest SIS shell edge / c_shell); any
    other deck keeps the round-8 form; DT2MS < 0 refuses the card. STARTER
    run (nt 4, C:/Users/pmqua/rcv_r9i_implB_<name>): b4_wh() under the flag
    (Gap 0.55, /DT/INTER/CST 0.9 1.659925E-07) 0 ERROR(S); bird-el under the
    flag (its bytes: the census arm rcv_r9c_G1_eRule's starter, the engine's
    Tmin 5.797843E-07 by this rule with the plate's own RO 7.83e-9 - the
    census's 5.8052E-7 used RO 7.85e-9) runs NORMAL in 2839 cycles, plate
    IE -29.06 %, deck IE END +39.41 % / KE -42.96 %, mass added 1.815e-7 t
    on 50 void ALE nodes and 0 of the 50 plate nodes (nt 4)."""

    def test_default_bytes_unchanged(self):
        res, st, eng = _convert(_t8._sis_ale_deck())
        self.assertEqual(_sha(st), _B4_SIS_386444E_STARTER)
        self.assertEqual(_sha(eng), _B4_SIS_386444E_ENGINE)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLID", st)
        self.assertNotIn("/INTER/TYPE18", st)
        self.assertNotIn("/DT/INTER", eng)
        hits = [w for w in res.warnings
                if w.startswith("*CONSTRAINED_SHELL_IN_SOLID: 1 card(s)")]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("2812.5", "-29.06 %", "1.140x", "-32.6 -> -35.0 %",
                       "GLOBAL", "x 21.4", "MESSAGE 205 + 207", "2.227e-4",
                       "3.6 %", "dtnoda.F:661-722"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])

    def test_optin_retune_on_an_sis_alone_deck(self):
        """Tmin = 0.5 x 0.5 x min(12.5 / 1.5e6, 12.5 / 5.421933e6) =
        5.763627e-7 (c_shell = sqrt(210000 / (7.85e-9 x 0.91)))."""
        deck = _t8._sis_ale_deck(extra="*CONTROL_TIMESTEP\n" + _row(0.0, 0.5))
        res, st, eng = _convert(deck, shell_in_solid_coupling=True)
        self.assertEqual(_t8._type18(st)[2],
                         _b4_f(2812.5, 0.0, 6.875, 0.0, 0.0))
        lines = eng.splitlines()
        i = lines.index("/DT")
        self.assertEqual(lines[i + 1][:20].strip(), "0.5")
        self.assertEqual(lines[i + 3], "/DT/INTER/CST")
        cst = _b4_cst(eng)
        self.assertEqual(len(cst), 1)
        self.assertEqual(cst[0][0], 0.5)
        self.assertAlmostEqual(cst[0][1] / 5.763627e-7, 1.0, places=6)
        hits = [w for w in res.warnings
                if "(--shell-in-solid-coupling): shell part(s)" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("Gap 6.875 = 0.55 x the mean host edge",
                       "/DT/INTER/CST 0.5 5.76363e-07", "-29.06 %",
                       "1.140x", "1.815e-7 t on 50 void ALE nodes",
                       "-32.6 to -35.0 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertFalse(_has(res.warnings, _W_B4_ROUND8))

    def test_tsca_fallback_09(self):
        """No *CONTROL_TIMESTEP: no /DT block, the CST block alone with Tsca
        0.9 and Tmin = 0.45 x 2.305450e-6 = 1.037453e-6."""
        _r, _s, eng = _convert(_t8._sis_ale_deck(),
                               shell_in_solid_coupling=True)
        self.assertNotIn("/DT", eng.splitlines())
        cst = _b4_cst(eng)
        self.assertEqual(len(cst), 1)
        self.assertEqual(cst[0][0], 0.9)
        self.assertAlmostEqual(cst[0][1] / 1.037453e-6, 1.0, places=6)

    def test_non_cubic_host_second_shell_material(self):
        """Host bricks 10 x 10 x 20, plate squares 10 x 10 in TWO shell
        parts of the SHSID set (steel, and E 300000 / RO 1.85e-9 / nu 0.3):
        Gap 0.55 x 10 = 5.5; Tmin = 0.45 x min(10 / 1.5e6, 10 / 5.421933e6,
        10 / 1.334916e7) = 3.370998e-7 - the second material decides."""
        deck = _t8._sis_ale_deck(host=(10.0, 10.0, 20.0), plate=10.0)
        for eid in (11, 12):
            old = f"{eid:>8}{3:>8}"
            self.assertEqual(deck.count(old), 1)
            deck = deck.replace(old, f"{eid:>8}{4:>8}")
        old_set = "*SET_PART_LIST\n" + _row(1) + "\n" + _row(3) + "\n"
        self.assertEqual(deck.count(old_set), 1)
        deck = deck.replace(old_set, "*SET_PART_LIST\n" + _row(1) + "\n"
                            + _row(3, 4) + "\n")
        deck = deck.replace("*END\n", "*PART\nplate 2\n" + _row(4, 3, 4)
                            + "\n*MAT_ELASTIC\n"
                            + _row(4, 1.85e-9, 300000.0, 0.3) + "\n*END\n")
        res, st, eng = _convert(deck, shell_in_solid_coupling=True)
        surf, _grb, line2 = _t8._type18(st)
        self.assertEqual(surf, [3, 4])
        self.assertEqual(line2[40:60], _b4_f(5.5))
        cst = _b4_cst(eng)
        self.assertEqual(len(cst), 1)
        self.assertAlmostEqual(cst[0][1] / 3.370998e-7, 1.0, places=6)

    def test_dt2ms_negative_refuses(self):
        deck = _t8._sis_ale_deck(extra="*CONTROL_TIMESTEP\n"
                                 + _row(0.0, 0.0, 0, 0.0, -1.0e-7))
        r_on, s_on, e_on = _convert(deck, shell_in_solid_coupling=True)
        _r0, s_off, e_off = _convert(deck)
        self.assertEqual((s_on, e_on), (s_off, e_off))
        self.assertIn("/DT/NODA/CST/0", e_on)
        self.assertNotIn("/DT/INTER", e_on)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLID", s_on)
        self.assertTrue(_has(r_on.warnings, "not converted under "
                             "--shell-in-solid-coupling - DT2MS -1e-07 < 0 "
                             "makes k2rad write /DT/NODA/CST/0",
                             "1.406e6 -> 5.635e6", "MESSAGE 167",
                             "it stays listed as skipped."), r_on.warnings)

    def test_type7_beside_sis_keeps_the_round8_form(self):
        """The screen reads the EMITTED interfaces: a TYPE7 pair (and its
        Lagrangian blocks) or an all-parts contact keeps the round-8 form; a
        contact k2rad refuses (undefined sets) emits nothing, so the same
        SIS deck DOES get the re-tune."""
        allc = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 5, 0)
                + "\n" + _row(0.1, 0.0) + "\n")
        refc = ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n" + _row(99, 98, 2, 2)
                + "\n" + _row(0.1, 0.0) + "\n")
        for name, extra, gap, what in (
                ("TYPE7 pair", _b4_blocks(True), 6.25,
                 "Lagrangian part(s) [5, 6] and 1 other interface(s) "
                 "(TYPE7)"),
                ("all-parts contact", allc, 6.25,
                 "1 other interface(s) (TYPE25)"),
                ("refused contact", refc, 6.875, "")):
            with self.subTest(case=name):
                res, st, eng = _convert(_t8._sis_ale_deck(extra=extra),
                                        shell_in_solid_coupling=True)
                self.assertEqual(_t8._type18(st)[2][40:60],
                                 _b4_f(gap))
                hits = [w for w in res.warnings
                        if w.startswith(_W_B4_ROUND8)]
                if what:
                    self.assertEqual(_b4_cst(eng), [])
                    self.assertEqual(len(hits), 1, res.warnings)
                    self.assertIn(what + " beside the embedded shells",
                                  hits[0])
                    self.assertIn("8.939x", hits[0])
                    self.assertTrue(_has(res.warnings, "Gap 6.25 = 0.5 x "
                                         "the mean host edge (the round-8 "
                                         "form"))
                else:
                    self.assertEqual(len(_b4_cst(eng)), 1)
                    self.assertEqual(hits, [])

    def test_lagrangian_part_beside_sis_keeps_the_round8_form(self):
        res, st, eng = _convert(_t8._sis_ale_deck(extra=_b4_blocks(False)),
                                shell_in_solid_coupling=True)
        self.assertEqual(_t8._type18(st)[2][40:60], _b4_f(6.25))
        self.assertEqual(_b4_cst(eng), [])
        self.assertTrue(_has(res.warnings, _W_B4_ROUND8 + "Lagrangian "
                             "part(s) [5, 6] beside the embedded shells"),
                        res.warnings)

    def test_dt_inter_guard(self):
        from k2rad.state import ConversionState
        from k2rad.writer.blast_ale import (sis_dt_inter_guard,
                                            sis_dt_inter_lines)
        state = ConversionState()
        state.sis_dt_inter_cst = (0.9, 1.0e-6)
        ours = sis_dt_inter_lines(state)
        self.assertEqual(ours[0], "/DT/INTER/CST")
        alone = ["/DT", "                 0.9                   0", "#"] + ours
        self.assertEqual(sis_dt_inter_guard(state, list(alone)), alone)
        self.assertEqual(state.warnings, [])
        other = ["/DT/INTER/DEL", "                 0.9               1e-08",
                 "#"]
        out = sis_dt_inter_guard(state, other + ours + ["/MON/ON", "#"])
        self.assertEqual(out, other + ["/MON/ON", "#"])
        self.assertTrue(_has(state.warnings, "another /DT/INTER card",
                             "is NOT added"), state.warnings)
        state.sis_dt_inter_cst = None
        self.assertEqual(sis_dt_inter_lines(state), [])

    def test_mid_cell_plate_couples_at_055(self):
        """cG1's water hammer (plate at x 20.5, mid-cell) under the flag:
        Gap 0.55, Tmin = 0.45 x min(1 / 1.5e6, 2 / 5.421933e6) = 1.659925e-7
        (the census's 1.6599E-7); the starter run of these bytes reads 0
        ERROR(S) (cG1's engine on the same cards, wz50rule: the plate
        coupled, first-event impulse J1 1.856 P0)."""
        res, st, eng = _convert(b4_wh(), shell_in_solid_coupling=True)
        self.assertEqual(_t8._type18(st)[2],
                         _b4_f(3600.0, 0.0, 0.55, 0.0, 0.0))
        cst = _b4_cst(eng)
        self.assertEqual(len(cst), 1)
        self.assertEqual(cst[0][0], 0.9)
        self.assertAlmostEqual(cst[0][1] / 1.659925e-7, 1.0, places=6)

    def test_clis_decks_untouched(self):
        deck = _t8._sis_ale_deck(clis=True)
        r_on, s_on, e_on = _convert(deck, shell_in_solid_coupling=True)
        _r0, s_off, e_off = _convert(deck)
        self.assertEqual((s_on, e_on), (s_off, e_off))
        self.assertNotIn("/DT/INTER", e_on)
        self.assertFalse(_has(r_on.warnings, _W_B4_ROUND8))


# ═════════════════════════════════════════════════════════════════════════════
# PART B - the round-9 part-B flags reach every wiring site
# ═════════════════════════════════════════════════════════════════════════════

class Round9FlagWiringB(_t7.Round7FlagWiringA):
    """Every round-9 part-B DEFAULT-ON lever reaches the parser (with its
    --no- twin), the README prose, the --help render with its measured
    figures (matched on the collapsed render), the GUI end to end,
    convert() / ConvertOptions (default True) and cli.main()'s call - the
    round-7 checks, for this round's part-B flags. B1's window is a VALUE
    option and has its own test (WeldTrajectoryImpflux.test_window_option)."""

    _FLAGS = {
        "--weld-trajectory-impflux": "weld_trajectory_impflux",
        "--axisymmetric-2d": "axisymmetric_2d",
        "--positive-dt2ms-mass-scaling": "positive_dt2ms_mass_scaling",
        "--plane-stress-unit-thickness": "plane_stress_unit_thickness",
        "--load-curve-offscale-zero": "load_curve_offscale_zero",
    }
    _HELP_FIGURES = {
        "--weld-trajectory-impflux": (
            "66 323 cycles", "-0.30 % of LS-DYNA's source energy",
            "721-2075 s", "PTYP 1 / 2", "-11.81..-13.46 %"),
        "--axisymmetric-2d": (
            "/ANALY N2D3D 1", "Isolid 2", "(x, y, 0) -> (0, x, y)",
            "the 3-D route -77.78 %"),
        "--positive-dt2ms-mass-scaling": (
            "(DT2MS / dt0)^2", "never /DT/NODA/CST on a 2-D deck",
            "24 807 cycles", "IE END -0.45 %", "RMS 0.24 %"),
        "--plane-stress-unit-thickness": (
            "ELFORM 12", "0.23410459", "117 ERROR(S) -> 0",
            "a stated T1 > 0 is kept"),
        "--load-curve-offscale-zero": (
            "Remarks 4a and 5", "+6.09 -> +13.10 % (MIXED)",
            "+91.96 -> +23.42 %", "Material, preload and thermal curves are "
            "never changed"),
    }

    def test_the_window_option_reaches_convert_and_the_gui(self):
        import inspect
        import k2rad_gui
        from k2rad.state import ConvertOptions
        self.assertEqual(
            inspect.signature(convert).parameters[
                "weld_trajectory_window"].default, 0.25)
        self.assertEqual(ConvertOptions().weld_trajectory_window, 0.25)
        for bad in (0.0, -2.0, float("nan"), float("inf")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ConvertOptions(weld_trajectory_window=bad)
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        kw = k2rad_gui.build_convert_kwargs(
            path, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", soften_stfac_text="",
            weld_trajectory_window_text="0.5")
        self.assertEqual(kw["weld_trajectory_window"], 0.5)
        captured = []
        app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
        app._append = captured.append
        k2rad_gui.ConverterGUI._describe_options(app, kw)
        self.assertIn("--weld-trajectory-window", "".join(captured))
        kw0 = k2rad_gui.build_convert_kwargs(
            path, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", soften_stfac_text="")
        self.assertNotIn("weld_trajectory_window", kw0)
        for bad in ("0", "-1", "x"):
            with self.subTest(gui=bad):
                with self.assertRaises(ValueError):
                    k2rad_gui.build_convert_kwargs(
                        path, "", ("Mg", "mm", "s"), ground_springs=False,
                        ground_spring_k_text="", soften_stfac_text="",
                        weld_trajectory_window_text=bad)
        from k2rad import cli
        import k2rad
        seen = {}

        def fake_convert(*a, **k):
            seen.update(k)
            raise SystemExit(0)
        saved = k2rad.convert
        k2rad.convert = fake_convert
        try:
            with self.assertRaises(SystemExit):
                cli.main([path, "--weld-trajectory-window", "0.75"])
        finally:
            k2rad.convert = saved
        self.assertEqual(seen.get("weld_trajectory_window"), 0.75)
        tmp.cleanup()


class Round9OptInWiringB(_t8.Round8OptInWiringB):
    """Every round-9 part-B OPT-IN lever (default OFF) reaches the parser
    (with its --no- twin), the README prose (its POSITIVE spelling) and its
    own README ### heading, the --help render with its measured figures,
    the GUI end to end, convert() / ConvertOptions (default False) and
    cli.main()'s call - round 8's opt-in checks for B8."""

    _OPT_IN = {"--ale-flow-tracking": "ale_flow_tracking"}
    _HELP_FIGURES = {
        "--ale-flow-tracking": ("/ALE/GRID/FLOW-TRACKING",
                                "I_def -1 for BCEXP 7",
                                "+1484.66 -> +17.00 %",
                                "1189.95 -> 27.74 %",
                                "253.09 -> 749.89 %", "OFF by default"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# B9 - the half-B texts, the round-9 PART-B retraction guard, the ROADMAP and
#      CHANGELOG records of part B, and every round-9 flag in README prose
# ═════════════════════════════════════════════════════════════════════════════

#: Round-9 PART-B retractions (B9.6). CHANGELOG may quote them; no other
#: shipped text may (adjacent literals joined, whitespace collapsed). Each
#: needle is cut at a line end, never inside a ``#`` comment run.
_RETRACTED_ROUND_9_B = (
    # B6: the A4 warning's cost now names its mechanism
    "mechanism not closed",
    # B9.2: the unscaled EFAIL rupture against LS's output bracket
    "1.12650e-3",
    # B9.3: round 6's rule-1 combined arm (before EFAIL and DT converted)
    "4983 cycles", "+82.0 %", "7.80x", "7.80×",
    "EFAIL has no /PROP/TYPE13 slot", "MAT_100's DT is dropped",
    # B1: the weld-trajectory package is built
    "specified and not built",
    # B2: the axisymmetric route is built (NOT the bare "named, never
    # changed" / "are named, not changed", which ship for other features)
    "no axisymmetric route is built",
    "axisymmetric ELFORM 14 / 15 / 44 are named",
    "14 / 15 / 44 are named whatever the flag",
    "157.5): named, never changed",
    "Next: a real 2-D route",
)

#: ... and the re-measured replacements, each in the file that ships it
_REPLACEMENTS_ROUND_9_B = (
    ("k2rad/writer/mesh.py", "counts no interface energy, ecrit.F:500-511"),
    ("k2rad/writer/loads.py", "fails at 1.12229e-3 s, 65.3 us before "
     "LS-DYNA's swforc failure time 1.1876e-3 s"),
    ("k2rad/writer/loads.py", "the last cycle 1332 = LS-DYNA's 1332; IE END "
     "-31.18 %, KE END +30.76 %"),
    ("k2rad/writer/loads.py", "KE END +30.76 % (unscaled +38.90 %)"),
    ("k2rad/writer/loads.py", "an emitted ``/INTER/TYPE2`` with Spotflag "
     "25-28"),
    ("k2rad/cli.py", "rupture 1.12229e-3 s, 65.3 us before LS-DYNA's swforc "
     "failure time 1.1876e-3 s"),
    ("k2rad/__init__.py", "the weld ruptures 65.3 us before LS-DYNA's "
     "(1.12229e-3 vs 1.1876e-3 s)"),
    ("k2rad/state.py", "1.12229e-3 s, 65.3 us before LS-DYNA's swforc failure "
     "time 1.1876e-3 s"),
    ("k2rad_gui.py", "spotweld.k rupture 1.12229e-3 s, 65.3 us before LS's "
     "1.1876e-3 s"),
    ("README.md", "**both** end at LS-DYNA's own cycle count 1332 with IE END "
     "−31.18 %"),
    ("README.md", "rupture 1.12229e-3 s, 65.3 µs before LS-DYNA's swforc "
     "failure time 1.1876e-3 s"),
    ("ROADMAP.md", "the next step was a 2-D route of its own"),
    ("ROADMAP.md", "was specified in round 8 and built in round 9 (B1"),
)


class Round9RetractedStatementsB(unittest.TestCase):
    """B9.6 (R14 triage round 9): no shipped text (README, ROADMAP, the GUI,
    every package module, docs/*.md, tools/*.py; CHANGELOG exempt) carries a
    retracted part-B spelling; the guard fires on each needle split across
    two adjacent literals; the replacements ARE shipped; CHANGELOG still
    quotes every old spelling (the history)."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _t7._SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_9_B:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_9_B:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "')
                        + ' y')
                self.assertIn(_t7._collapse(needle).lower(), _t7._collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_t7._SHIPPED_TEXTS())
        for rel, needle in _REPLACEMENTS_ROUND_9_B:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_t7._collapse(needle), texts[key])

    def test_changelog_still_quotes_each_old_spelling(self):
        text = _t7._collapse(_t7._read7("CHANGELOG.md")).lower()
        for needle in _RETRACTED_ROUND_9_B:
            with self.subTest(needle=needle):
                self.assertIn(_t7._collapse(needle).lower(), text)


class Round9RoadmapRecordB(unittest.TestCase):
    """B9: the ROADMAP record of round 9 - the queue table's round-9 column
    (every row as wide as its header), ONE ``**Round 9:**`` line on every
    round-8 NOT entry 1-27 (part A wrote 8, B9 the other 19), the round-9
    NOT list numbered 1-28 with no placeholder and entries 3 / 4 written
    from the gate outcomes, the closes paragraph's EXPECTED ledger and the
    residue restated."""

    @classmethod
    def setUpClass(cls):
        cls.lines = _t7._read7("ROADMAP.md").splitlines()

    def _at(self, prefix: str) -> int:
        hits = [k for k, ln in enumerate(self.lines) if ln.startswith(prefix)]
        self.assertEqual(len(hits), 1, prefix)
        return hits[0]

    def _items(self, s: int, e: int):
        starts = [k for k in range(s, e)
                  if re.match(r"^\d+\. \*\*", self.lines[k])]
        return list(zip(starts, starts[1:] + [e]))

    def test_the_queue_table_has_a_round_9_column(self):
        rows = []
        for ln in self.lines[self._at("| # | class | decks | closed by "
                                      "round 1 |"):]:
            if not ln.startswith("|"):
                break
            rows.append(ln)
        self.assertTrue(rows[0].endswith("| round 8 | round 9 |"), rows[0])
        self.assertEqual(len(rows), 10)
        width = _t7._md_cells(rows[0])
        for r in rows[1:]:
            with self.subTest(row=r[:48]):
                self.assertEqual(_t7._md_cells(r), width)
        last = rows[2].rstrip(" |").rsplit("|", 1)[1]
        self.assertIn("B1", last)
        self.assertIn("66 323 cycles", last)

    def test_every_round_8_entry_carries_one_round_9_line(self):
        s = self._at("**What round 8 deliberately does NOT close**")
        e = self._at("**What round 9 closes, and what it does NOT.**")
        items = self._items(s, e)
        self.assertEqual(len(items), 27)
        for n, (a, b) in enumerate(items, 1):
            with self.subTest(entry=n):
                self.assertTrue(self.lines[a].startswith(f"{n}. **"))
                self.assertEqual(
                    sum("**Round 9:**" in ln for ln in self.lines[a:b]), 1)

    def test_the_round_9_not_list_is_numbered_1_to_28(self):
        s = self._at("**What round 9 deliberately does NOT close**")
        e = self._at("**52 of the 59 starter failures.**")
        nums = [int(m.group(1)) for m in
                (re.match(r"^(\d+)\. \*\*", ln) for ln in self.lines[s:e])
                if m]
        self.assertEqual(nums, list(range(1, 29)))
        self.assertNotRegex("\n".join(self.lines[s:e]), r"<[a-z_ ]+>")

    def test_entries_3_4_17_24_26_as_decided(self):
        s = self._at("**What round 9 deliberately does NOT close**")
        e = self._at("**52 of the 59 starter failures.**")
        block = {n: _t7._collapse("\n".join(self.lines[a:b]))
                 for n, (a, b) in enumerate(self._items(s, e), 1)}
        for needle in ("B4's gate FAILED", "1.140×", "MESSAGE 205 + 207",
                       "1.815e-7 t on 50 void ALE nodes"):
            self.assertIn(needle, block[3])
        for needle in ("--mixed-main-thickness-gap", "NO-GO",
                       "4.3_General_Nonlinearity"):
            self.assertIn(needle, block[4])
        for n in (17, 24, 26):
            with self.subTest(entry=n):
                self.assertIn("USER's decision", block[n])

    def test_the_closes_paragraph_states_the_EXPECTED_ledger(self):
        s = self._at("**What round 9 closes, and what it does NOT.**")
        e = self._at("**What round 9 deliberately does NOT close**")
        para = _t7._collapse("\n".join(self.lines[s:e]))
        for needle in ("EXPECTED", "normal 293 → 299", "error_starter 12 → 7",
                       "17 deck keys on 17 emitted models",
                       "part A 10 / 10; part B 7 / 7",
                       "the implicit residue 27 / 27 → 24 / 24"):
            with self.subTest(needle=needle):
                self.assertIn(needle, para)

    def test_the_residue_is_restated_for_round_9(self):
        text = _t7._collapse("\n".join(self.lines))
        self.assertIn("so the residue is **24 keys / 24 models** by the same "
                      "rule", text)


class Round9ChangelogReSumsB(unittest.TestCase):
    """B9: the "re-add every headline total" rule for part B - the header's
    byte-mover count re-sums from its per-item counts (no key is shared),
    each item bullet states its own count, and the round total in ROADMAP is
    part A's plus part B's (the halves are disjoint)."""

    def test_the_part_B_total_re_sums(self):
        text = _t7._collapse(_t7._read7("CHANGELOG.md"))
        m = re.search(
            r"Part B's default bytes move (\d+) deck keys / (\d+) emitted "
            r"models \(B1 (\d+) / (\d+), B2 (\d+) / (\d+), B3 (\d+) / (\d+), "
            r"B5 (\d+) / (\d+); no key is shared\)", text)
        self.assertIsNotNone(m)
        tot_k, tot_m, *items = map(int, m.groups())
        self.assertEqual((sum(items[0::2]), sum(items[1::2])),
                         (tot_k, tot_m))
        self.assertEqual((tot_k, tot_m), (7, 7))

    def test_the_item_bullets_state_the_same_counts(self):
        text = _t7._collapse(_t7._read7("CHANGELOG.md"))
        for needle in (
                "Movers: bytes 2 deck keys / 2 emitted models (05_4_1, "
                "05_5_1)",
                "Movers: bytes 2 deck keys / 2 emitted models (metal-forming, "
                "2Dlag)",
                "Movers 1 deck key / 1 emitted model (main_fsi",
                "Movers 2 deck keys / 2 emitted models (the cup-draw, "
                "thick.k)",
                "Movers: default bytes 0 / 0; warning text 1 deck key / 1 "
                "emitted model (bird_B",
                "default bytes 0 / 0 (bird-el and the round-8 fixture "
                "byte-identical"):
            with self.subTest(needle=needle[:40]):
                self.assertIn(needle, text)

    def test_the_round_total_is_the_two_halves(self):
        text = _t7._collapse(_t7._read7("CHANGELOG.md"))
        a = re.search(r"Part A's default bytes move (\d+) deck keys / (\d+) "
                      r"emitted models", text)
        b = re.search(r"Part B's default bytes move (\d+) deck keys / (\d+) "
                      r"emitted models \(B1", text)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        tot = (int(a.group(1)) + int(b.group(1)),
               int(a.group(2)) + int(b.group(2)))
        road = _t7._collapse(_t7._read7("ROADMAP.md"))
        self.assertIn(f"Round 9's default bytes move {tot[0]} deck keys on "
                      f"{tot[1]} emitted models", road)


class Round9FlagsInReadme(unittest.TestCase):
    """Every round-9 flag of BOTH halves is named in README prose - the
    default-ON levers by their ``--no-`` spelling, the opt-ins by their
    positive one, B1's window option as itself - and each opt-in has its own
    README ### heading (the round-5 rule)."""

    def _readme(self) -> str:
        return _t7._read7("README.md")

    def test_every_round_9_flag_is_in_README_prose(self):
        readme = self._readme()
        body = [ln for ln in readme.splitlines()
                if not re.match(r"^\s*[-*]?\s*\[.*\]\(#.*\)\s*$", ln)]
        on = list(Round9FlagWiringA._FLAGS) + list(Round9FlagWiringB._FLAGS)
        opt = list(Round9OptInWiring._OPT_IN) + list(
            Round9OptInWiringB._OPT_IN)
        spellings = (["--no-" + f[2:] for f in on] + opt
                     + ["--weld-trajectory-window"])
        # part A: 8 default levers + 2 opt-ins; part B: 5 default levers +
        # 1 opt-in + B1's window option
        self.assertEqual(len(spellings), 17)
        for flag in spellings:
            with self.subTest(flag=flag):
                self.assertTrue(any(flag in ln for ln in body),
                                f"{flag} is not in README.md prose")

    def test_every_round_9_opt_in_has_its_own_heading(self):
        headings = re.findall(r"^#{2,4}\s+(.*)$", self._readme(), re.M)
        for flag in (list(Round9OptInWiring._OPT_IN)
                     + list(Round9OptInWiringB._OPT_IN)):
            with self.subTest(flag=flag):
                self.assertTrue(any(h.startswith(f"`{flag}`")
                                    for h in headings), flag)


if __name__ == "__main__":
    unittest.main()
