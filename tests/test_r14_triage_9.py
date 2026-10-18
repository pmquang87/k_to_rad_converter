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
        for n in (1, 6):
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
            "gravit_imp.F", "1101 cycles", "+0.42 / +0.20 / +0.14 %",
            "Explicit decks unchanged"),
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
        e = self._at("**52 of the 59 starter failures.**")
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


if __name__ == "__main__":
    unittest.main()
