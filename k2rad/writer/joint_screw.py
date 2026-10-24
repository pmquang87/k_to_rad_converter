"""*CONSTRAINED_JOINT_SCREW -> /GJOINT/RACK + the contact split (R14 triage
round 7, B2; default ON, ``--no-joint-screw-gjoint``).

LS-DYNA's screw joint (Vol I R17 p.10-61..76, Figure 10-29): "The second
body (nodes 2, 4, and 6) translates in response to the spin of the first
body (nodes 1, 3, and 5)", PARM = x_dot / omega. OpenRadioss has no screw
joint (``/PROP/TYPE45`` KJOINT2 Types 1-9, ``prop_p45_kjoint2.cfg``), but its
Lagrange-multiplier gear joint ``/GJOINT/RACK`` relates the ROTATION of
node_ID1 about r1 to the TRANSLATION of node_ID2 along r2, both measured
against a reference node_ID0 - so the screw is a rack whose reference is a
synthesized CARRIAGE that turns with nothing and translates with the
spinning body.

ONE decision per deck (``_resolve_joint_screws``, memoised on
``state.joint_screw_plan``, a ``build_starter`` prepass run BEFORE the
/RBODY producers), read by every site the conversion touches:

* ``writer/rbody._make_rbodies`` - the *MAT_RIGID CMO ``/BCS`` of A and B is
  not written (a standard condition on a Lagrange-held node is incompatible;
  the rack's links carry it), and A1's ``rigid_auto_bcs`` record skips them
  by the same predicate; on an UNDRIVEN screw (round 8, B8 q-i) A's J row
  gets the transverse inertia pad (``screw_pad``);
* ``writer/loads._make_bcs`` and the ``*NODE`` TC/RC pass - a code a body
  member states on DOFs the joint already holds is written nowhere (round
  8, B8 q-ii; ``screw_merged_members``);
* ``writer/rbody._make_screw_carriage_rbodies`` - /RBODY producer 6 of 6, the
  carriage (an element-free /RBODY at A's main node with two massless
  element-free secondaries, Mass 1e-6, J 1e-6 x 3, ICoG 3);
* ``writer/contacts._make_interfaces`` - the A-B pair is split out of an
  all-parts self-contact (``lagrange_held_pairs``, round 8);
* ``writer/loads._make_imposed_motions`` - A's drive is not written as an
  /IMPDISP;
* ``_make_joint_screws`` (this module) - the carriage main group, the two
  ``/BCS/LAGMUL``, the drive as ``/IMPVEL/LAGMUL`` (a VAD 2 displacement
  curve DIFFERENTIATED into a velocity /FUNCT) and the ``/GJOINT/RACK``.

A screw outside the pattern keeps today's skip (its ``#-- SKIPPED:`` line,
0 bytes) and gets ONE named warning; the pattern's eleven conditions are in
``_screw_refusal``.
"""

from __future__ import annotations

import math
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from ..state import (BodyCondition, ConversionState, ConstrainedJointScrew,
                     JointScrewPlan, PrescribedMotionRigid)
from .common import HDR, _dof_string, _f, _i, _emit_grnod_node

#: the spelling the pattern converts; _LOCAL / _FAILURE / _COOR_ are named
_PLAIN_SCREW = "CONSTRAINED_JOINT_SCREW"

#: |cos| tolerance of "parallel" / "along a global axis", and the relative
#: distance tolerance of "on the line N1-N3"
_AXIS_TOL = 1.0e-6

#: the carriage /RBODY's mass and inertia (the measured arm's values): non-zero
#: because the Lagrange joint refuses a node with a null mass or inertia
#: (lgmini_gj.F:74 / :87, ERROR 535 / 536), tiny so it carries nothing
_CARRIAGE_MASS = 1.0e-6

#: the carriage's two secondaries sit 0.1 x |N1N3| off its main node along the
#: two global axes normal to the screw axis - a stated geometric CONVENTION
#: (the secondaries are massless, element-free nodes), not a measured rule
_CARRIAGE_OFFSET = 0.1

#: the width of the ramp that replaces a slope step of a differentiated drive
#: curve (capped at 1 % of the curve's shortest segment)
_RAMP = 1.0e-7

_AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_DIRS = ("XX", "YY", "ZZ")


def _vsub(a, b) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _code(axis: int, inside: str) -> str:
    """'1' on the two axes normal to the screw axis, *inside* on it."""
    return "".join(inside if i == axis else "1" for i in range(3))


def screw_drive_derivative(pts) -> List[Tuple[float, float]]:
    """The time DERIVATIVE of a piecewise-linear displacement curve, as the
    points of a velocity /FUNCT: ``(x_0, s_0)``, then at every interior point
    whose slope CHANGES the pair ``(x_i, s_{i-1}), (x_i + w, s_i)`` (a step
    written as a ramp of width ``w = min(1e-7, 0.01 x the shortest
    segment)``), then ``(x_{n-1}, s_{n-2})``. A breakpoint between two equal
    slopes (round-off only: ``|s_i - s_{i-1}| <= 1e-9 max(1, |s_{i-1}|)``)
    is dropped. The points are the curve's EFFECTIVE ones (``state.curves``
    already applies SFA / SFO / OFFA / OFFO); the drive's SF goes to the
    /IMPVEL/LAGMUL ``Fscale_y``, never into the points."""
    p = [(float(x), float(y)) for x, y in pts]
    seg = [p[i + 1][0] - p[i][0] for i in range(len(p) - 1)]
    s = [(p[i + 1][1] - p[i][1]) / seg[i] for i in range(len(p) - 1)]
    w = min(_RAMP, 0.01 * min(seg))
    out = [(p[0][0], s[0])]
    for i in range(1, len(p) - 1):
        if abs(s[i] - s[i - 1]) > 1e-9 * max(1.0, abs(s[i - 1])):
            out.append((p[i][0], s[i - 1]))
            out.append((p[i][0] + w, s[i]))
    out.append((p[-1][0], s[-1]))
    return out


def _node_parts(state: ConversionState) -> Dict[int, Set[int]]:
    """node -> the parts whose ELEMENTS use it (shells, solids, thick shells,
    beams; SPH and discrete elements are not body nodes of a *MAT_RIGID part
    the pattern accepts)."""
    out: Dict[int, Set[int]] = {}
    for elems in (state.shell_elems, state.solid_elems, state.tshell_elems):
        for e in elems:
            for n in e.nodes:
                if n > 0:
                    out.setdefault(n, set()).add(e.pid)
    for b in state.beam_elems:
        for n in (b.n1, b.n2):
            if n > 0:
                out.setdefault(n, set()).add(b.pid)
    return out


def _side_touches(state: ConversionState, sid: int, styp: int,
                  pid: int, pid_nodes: Set[int]) -> bool:
    """Does one contact side reach part *pid*? CONSERVATIVE: an all-parts
    side (SID 0, STYP 5 / 6) touches everything; a part / part-set side by
    id; any other side when its nodes meet the part's nodes."""
    from .contacts import _side_node_ids      # local: contacts imports us
    if sid == 0 or styp in (5, 6):
        return True
    if styp == 3:
        return sid == pid
    if styp == 2:
        ps = state.part_sets.get(sid)
        return ps is not None and pid in ps[1]
    return bool(_side_node_ids(state, sid, styp) & pid_nodes)


def _contact_conflict(state: ConversionState, a: int, b: int,
                      a_nodes: Set[int], b_nodes: Set[int]
                      ) -> Tuple[Optional[str], List[int]]:
    """``(the first contact that holds the A-B pair and the split cannot
    handle, in words, or None; the explicit all-parts self-contacts the split
    WILL handle)``."""
    split: List[int] = []
    for c in state.contacts_single:
        if c.ssid == 0 and not state.is_implicit:
            split.append(c.inter_id)
            continue
        if (_side_touches(state, c.ssid, c.sstyp, a, a_nodes)
                and _side_touches(state, c.ssid, c.sstyp, b, b_nodes)):
            return (f"*{c.keyword or 'CONTACT_AUTOMATIC_SINGLE_SURFACE'} "
                    f"{c.inter_id}"), split
    for bucket in (state.contacts_surf2surf, state.contacts_general,
                   state.contacts_type25, state.contacts_tied,
                   state.contacts_tiebreak, state.contacts_spotweld):
        for c in bucket:
            sides = ((c.ssid, c.sstyp), (c.msid, c.mstyp))
            if (any(_side_touches(state, s, t, a, a_nodes) for s, t in sides)
                    and any(_side_touches(state, s, t, b, b_nodes)
                            for s, t in sides)):
                kw = getattr(c, "keyword", "") or "CONTACT"
                return f"*{kw} {c.inter_id}", split
    return None, split


def _rigid_own_body(state: ConversionState, pid: int,
                    cnrb_nodes: Set[int], pid_nodes: Set[int]
                    ) -> Optional[str]:
    """Why part *pid* is NOT a *MAT_RIGID part that becomes its OWN /RBODY,
    or None when it is."""
    part = state.parts.get(pid)
    if part is None:
        return f"part {pid} has no *PART"
    if pid in state.deformable_to_rigid:
        return f"part {pid} is a *DEFORMABLE_TO_RIGID part"
    if part.mid not in state.mat_rigid:
        return f"part {pid} is not a *MAT_RIGID part"
    for slave, master in state.rigid_body_merges:
        if pid in (slave, master):
            return f"part {pid} is merged by *CONSTRAINED_RIGID_BODIES"
    if pid in state.extra_rigid_nodes:
        return f"part {pid} carries *CONSTRAINED_EXTRA_NODES"
    if any(getattr(c, "pid", 0) == pid for c in state.cnrbs):
        if state.options.rigid_part_pid_precedence:
            # round 9, A1: the part keeps its record, but the screw still
            # refuses a body whose id two rigid bodies share
            return (f"a *CONSTRAINED_NODAL_RIGID_BODY shares PID {pid} with "
                    "the part (LS Warning 10177)")
        return (f"a *CONSTRAINED_NODAL_RIGID_BODY uses PID {pid}, so its "
                "record would replace the part's")
    if pid_nodes & cnrb_nodes:
        return f"part {pid} shares nodes with a *CONSTRAINED_NODAL_RIGID_BODY"
    return None


def _cnrb_nodes(state: ConversionState) -> Set[int]:
    out: Set[int] = set()
    for c in state.cnrbs:
        nsid = getattr(c, "nsid", 0)
        if nsid in state.node_sets:
            out.update(state.node_sets[nsid][1])
    return out


def _more(nodes: List[int]) -> str:
    return "" if len(nodes) < 2 else f" (and {len(nodes) - 1} more node(s))"


def _body_conditions(state: ConversionState, nodes: Set[int]
                     ) -> List[BodyCondition]:
    """EVERY standard kinematic condition the deck states on a body's element
    *nodes* (round 8, B8 q-ii; round 7 stopped at the first), one per
    ``*NODE`` TC/RC code, per ``*CONSTRAINED_GLOBAL`` code, per
    ``*BOUNDARY_SPC`` card and per nodal prescribed motion. The codes reach
    the body's /RBODY main node as standard cards - rule (a) of the ``*NODE``
    TC/RC pass and ``_make_bcs`` re-point a member's code onto it (and unite
    the codes of all members) - where the starter reports one beside the
    joint's ``/BCS/LAGMUL`` as an incompatible kinematic condition (WARNING
    312, BOUNDARY CONDITION / LAGRANGE MULTIPLIERS: measured with a redundant
    ``*BOUNDARY_SPC`` and a redundant ``*NODE`` TC on EXP_SC_JOINT_SCREW); a
    nodal prescribed motion is written on the member it names. Mirrors what
    is WRITTEN: ``--no-node-tc-rc-bcs`` drops the ``*NODE`` cells (no
    condition), and ``--no-constrained-global`` leaves
    ``state.constrained_global_tc_rc`` empty. A rigid wall is not screened
    (it is not a /BCS; unmeasured)."""
    from .loads import _TC_RC_DIGITS, _box_contains   # local: loads imports us
    out: List[BodyCondition] = []
    if state.options.node_tc_rc_bcs:
        by_code: Dict[Tuple[int, int], List[int]] = {}
        for n in sorted(nodes):
            code = state.node_tc_rc.get(n, (0, 0))
            if code != (0, 0):
                by_code.setdefault(code, []).append(n)
        for (tc, rc), ns in sorted(by_code.items(), key=lambda kv: kv[1][0]):
            out.append(BodyCondition(
                "node_tc_rc", ns[0], _TC_RC_DIGITS[tc], _TC_RC_DIGITS[rc],
                f"the *NODE TC {tc} / RC {rc} of its node {ns[0]}"
                + _more(ns)))
    g_code: Dict[Tuple[int, int], List[int]] = {}
    for n in sorted(nodes):
        if n in state.constrained_global_tc_rc:
            g_code.setdefault(state.constrained_global_tc_rc[n], []).append(n)
    for (tc, rc), ns in sorted(g_code.items(), key=lambda kv: kv[1][0]):
        out.append(BodyCondition(
            "constrained_global", ns[0], _TC_RC_DIGITS[tc], _TC_RC_DIGITS[rc],
            f"a *CONSTRAINED_GLOBAL plane through its node {ns[0]}"
            + _more(ns)))
    for bc in state.bcs_spcs:
        hit = sorted(set(state.node_sets.get(bc.nsid, ("", []))[1]) & nodes)
        if hit:
            from .loads import spc_cid_skew       # round 9, A6
            skew = spc_cid_skew(state, bc.cid)
            out.append(BodyCondition(
                "bcs_spc", hit[0], _dof_string(bc.dofx, bc.dofy, bc.dofz),
                _dof_string(bc.dofrx, bc.dofry, bc.dofrz),
                f"the *BOUNDARY_SPC (/BCS/{bc.bc_id}) of its node {hit[0]}"
                + _more(hit), skew))
    for pm in state.prescribed_motion_sets:
        cand = (set(state.node_sets.get(pm.nsid, ("", []))[1]) & nodes
                if pm.nsid else set(nodes))
        if pm.boxid:
            box = state.boxes.get(pm.boxid)
            cand = {n for n in cand if box is not None and n in state.nodes
                    and _box_contains(box, state.nodes[n].x,
                                      state.nodes[n].y, state.nodes[n].z)}
        elif not pm.nsid:
            continue
        if cand:
            out.append(BodyCondition(
                "node_motion", min(cand), "000", "000",
                "a *BOUNDARY_PRESCRIBED_MOTION_NODE / _SET on its node "
                f"{min(cand)}"))
    return out


def _held_dofs(label: str, axis: int) -> Set[int]:
    """The DOFs (0-2 the translations, 3-5 the rotations, global axes) the
    converted joint HOLDS on body *label* (round 8, B8 q-ii): on both bodies
    the two translations normal to the screw axis (A's by its
    ``/BCS/LAGMUL``, B's by the rack against the carriage, whose own
    ``/BCS/LAGMUL`` holds it on the axis), the two rotations normal to the
    axis on A, all three rotations on B. Free: the axial translation of both
    bodies, and A's spin on an UNDRIVEN screw (on a driven one the spin is
    the drive's DOF)."""
    normal = {i for i in range(3) if i != axis}
    if label == "A":
        return normal | {3 + i for i in normal}
    return normal | {3, 4, 5}


def _condition_class(cond: BodyCondition, held: Set[int], label: str,
                     axis: int, driven: bool) -> str:
    """``held`` (every DOF of the code is held: merged, written nowhere),
    ``motion`` (a nodal prescribed motion), ``skew`` (a code in a local
    system: its digits are not the joint's global DOFs), ``drive`` (the
    code touches A's rotation about the axis on a DRIVEN screw) or ``free``
    (it touches a DOF the joint leaves free) - the last four refuse the
    joint."""
    if cond.kind == "node_motion":
        return "motion"
    if cond.skew:
        return "skew"
    dofs = {i for i, c in enumerate(cond.tra + cond.rot) if c == "1"}
    if dofs <= held:
        return "held"
    if label == "A" and driven and (3 + axis) in dofs:
        return "drive"
    return "free"


def _class_why(cls: str, cond: BodyCondition, label: str, axis: int,
               driven: bool) -> str:
    """The class in words, for refusal 11's sentence."""
    if cls == "motion":
        return ("a nodal prescribed motion (written on the member node it "
                "names; the joint's Lagrange conditions on the same body are "
                "not combined with it - unmeasured)")
    if cls == "skew":
        return (f"in a local system (/SKEW {cond.skew}: its digits are not "
                "the joint's global DOFs) - which k2rad writes as a standard "
                "condition on the body's /RBODY main node beside the joint's "
                "Lagrange conditions (an incompatible kinematic condition: "
                "starter WARNING 312)")
    if cls == "drive":
        what = "on the drive's DOF (A's rotation about the screw axis)"
    else:
        dofs = {i for i, c in enumerate(cond.tra + cond.rot) if c == "1"}
        free = []
        if axis in dofs:
            free.append("the axial translation")
        if label == "A" and not driven and (3 + axis) in dofs:
            free.append("A's spin about the screw axis")
        what = ("on a free DOF of the joint (" + " and ".join(free) + ")")
    return (what + " - which k2rad writes as a standard condition on the "
            "body's /RBODY main node beside the joint's Lagrange conditions "
            "(an incompatible kinematic condition: starter WARNING 312)")


def _screw_refusal(state: ConversionState, s: ConstrainedJointScrew,
                   node_parts: Dict[int, Set[int]], cnrb_nodes: Set[int],
                   taken: Set[int]
                   ) -> Tuple[Optional[str], Optional[JointScrewPlan]]:
    """``(the reason the screw is NOT converted, None)`` or ``(None, the
    plan)``. The ten conditions of the round-7 B2 spec, in order, and an
    eleventh from the validation round (no other kinematic condition on
    either body, :func:`_body_conditions`); every one has reach 0 on every
    corpus (the only carrier, EXP_SC_JOINT_SCREW, passes all eleven), so each
    is pinned by a hand-built probe. Round 8 (B8) widens two of them: 9
    accepts a screw whose deck states NO drive on either body (q-i), and 11
    merges a code on DOFs the joint already holds instead of refusing (q-ii)."""
    # 2. the plain spelling only
    if s.keyword != _PLAIN_SCREW:
        return ("the _COOR_SCREW / _LOCAL / _FAILURE spelling is not converted "
                "(unmeasured)"), None
    # 3. explicit decks only (Lagrange joints on the implicit path are
    #    unmeasured)
    if state.is_implicit:
        return "the deck is implicit", None
    # 4. PARM
    if s.parm == 0.0:
        return "PARM is 0", None
    # 5. N1 / N3 / N5 on one *MAT_RIGID part A, N2 / N4 / N6 on another, B
    owners: List[int] = []
    for n in (s.n1, s.n3, s.n5, s.n2, s.n4, s.n6):
        pids = node_parts.get(n, set())
        if len(pids) != 1:
            why = ("on no element" if not pids
                   else f"on the elements of parts {sorted(pids)}")
            return (f"node {n} is not an element node of a single *MAT_RIGID "
                    f"part with its own /RBODY ({why})"), None
        owners.append(next(iter(pids)))
    a, b = owners[0], owners[3]
    if len(set(owners[:3])) != 1 or len(set(owners[3:])) != 1 or a == b:
        return ("N1 / N3 / N5 and N2 / N4 / N6 are not on two different rigid "
                "parts"), None
    pid_nodes = {pid: {n for n, ps in node_parts.items() if pid in ps}
                 for pid in (a, b)}
    for pid in (a, b):
        why = _rigid_own_body(state, pid, cnrb_nodes, pid_nodes[pid])
        if why is not None:
            n = s.n1 if pid == a else s.n2
            return (f"node {n} is not an element node of a single *MAT_RIGID "
                    f"part with its own /RBODY ({why})"), None
        if pid in taken:
            return (f"part {pid} is already a body of another converted "
                    "screw"), None
    # 6. coaxial
    xyz = {}
    for n in (s.n1, s.n2, s.n3, s.n4):
        nd = state.nodes.get(n)
        if nd is None:
            return (f"node {n} is not an element node of a single *MAT_RIGID "
                    "part with its own /RBODY (not defined)"), None
        xyz[n] = (nd.x, nd.y, nd.z)
    u13 = _vsub(xyz[s.n1], xyz[s.n3])
    u24 = _vsub(xyz[s.n2], xyz[s.n4])
    l13, l24 = _norm(u13), _norm(u24)
    if l13 <= 0.0 or l24 <= 0.0:
        return ("N1-N3 and N2-N4 are not coaxial (a zero-length pair: "
                f"|N1N3| {l13:g}, |N2N4| {l24:g})"), None
    r = (u13[0] / l13, u13[1] / l13, u13[2] / l13)
    cos = _dot(u13, u24) / (l13 * l24)
    if abs(cos) < 1.0 - _AXIS_TOL:
        return (f"N1-N3 and N2-N4 are not coaxial (the two pairs are not "
                f"parallel: |cos| {abs(cos):.9g})"), None
    for n in (s.n2, s.n4):
        d = _norm(_cross(_vsub(xyz[n], xyz[s.n3]), r))
        if d > _AXIS_TOL * l13:
            return (f"N1-N3 and N2-N4 are not coaxial (node {n} is {d:g} off "
                    "the N1-N3 line)"), None
    # 7. a global screw axis
    axis = next((k for k in range(3) if abs(r[k]) >= 1.0 - _AXIS_TOL), -1)
    if axis < 0:
        rr = "(" + ", ".join(f"{v:.6g}" for v in r) + ")"
        return (f"the screw axis {rr} is not along a global axis (a "
                "/SKEW-frame carriage is not built)"), None
    r = tuple(round(v) if abs(v) >= 1.0 - _AXIS_TOL else 0.0 for v in r)
    # 8. the screw's own *MAT_RIGID CMO pattern
    from .rbody import _con1_to_tra, _con2_to_rot   # local: rbody imports us

    def _cmo(pid: int) -> str:
        m = state.mat_rigid[state.parts[pid].mid]
        if m.cmo != 1.0:
            return f"CMO {m.cmo:g}"
        return f"{_con1_to_tra(m.con1)} {_con2_to_rot(m.con2)}"
    want_a = f"{_code(axis, '0')} {_code(axis, '0')}"
    want_b = f"{_code(axis, '0')} 111"
    if _cmo(a) != want_a or _cmo(b) != want_b:
        return (f"the *MAT_RIGID constraints are not the screw's own (A "
                f"{_cmo(a)}, B {_cmo(b)}; expected A {want_a}, B "
                f"{want_b})"), None
    # 9. the drive: one rotation about the axis on A, nothing on B - or, since
    #    round 8 (B8 q-i), NO drive stated on either body: the UNDRIVEN screw
    #    (the deck's statement, state.pm_rigid_stated_pids, not the converted
    #    registry - a refused VAD 3 / 4 drive is not "no drive")
    on_a = [pm for pm in state.prescribed_motions if pm.pid == a]
    on_b = [pm for pm in state.prescribed_motions if pm.pid == b]
    if on_b or b in state.pm_rigid_stated_pids:
        return f"the drive: part {b} (the translating body) is driven too", None
    pm: Optional[PrescribedMotionRigid] = None
    if a not in state.pm_rigid_stated_pids:
        pass                                    # the UNDRIVEN screw
    elif len(on_a) != 1:
        return ("the drive: " + (
            f"the *BOUNDARY_PRESCRIBED_MOTION_RIGID on part {a} is not "
            "converted (a VAD 3 / 4 card is not converted at all; a refused "
            "drive is not 'no drive')" if not on_a else
            f"part {a} carries {len(on_a)} prescribed motions"), None)
    else:
        pm = on_a[0]
        endtim = (state.ctrl_termination.endtim
                  if state.ctrl_termination is not None else 0.0)
        if pm.local:
            return "the drive is _LOCAL (unmeasured)", None
        if pm.dof != 5 + axis or pm.vid:
            return (f"the drive: DOF {pm.dof} is not the rotation about the "
                    f"screw axis (DOF {5 + axis})"), None
        if pm.vad not in (0, 2):
            return (f"the drive: VAD {pm.vad} is not converted (unmeasured)",
                    None)
        if pm.birth != 0.0 or (0.0 < pm.death < endtim):
            return (f"the drive has a time window (birth {pm.birth:g}, death "
                    f"{pm.death:g})"), None
        curve = state.curves.get(pm.lcid)
        if (curve is None or pm.lcid in state.funct_smooth_ids
                or len(curve.pts) < 2
                or any(curve.pts[i + 1][0] <= curve.pts[i][0]
                       for i in range(len(curve.pts) - 1))):
            return (f"the drive's curve {pm.lcid} is not a plain "
                    "*DEFINE_CURVE with two or more increasing abscissae"), None
    # 10. contacts: the pair may sit only in an explicit all-parts
    #     self-contact (the split handles it)
    conflict, split = _contact_conflict(state, a, b, pid_nodes[a],
                                        pid_nodes[b])
    if conflict is not None:
        return (f"parts {a} and {b} share contact {conflict}, which the split "
                "does not handle"), None
    # 11. no other kinematic condition on either body that the joint does not
    #     already hold: it would land on a Lagrange-held main node as a
    #     standard card (round-7 fix round, from the validators' probes).
    #     Round 8 (B8 q-ii): split by DOF class - a code on DOFs the joint
    #     HOLDS is merged (written nowhere, named by the joint section); one
    #     on the drive's DOF, on a free DOF, in a local system, or a nodal
    #     prescribed motion still refuses.
    driven = pm is not None
    merged: List[Tuple[str, int, BodyCondition]] = []
    for label, pid in (("A", a), ("B", b)):
        held = _held_dofs(label, axis)
        for cond in _body_conditions(state, pid_nodes[pid]):
            cls = _condition_class(cond, held, label, axis, driven)
            if cls == "held":
                merged.append((label, pid, cond))
                continue
            return (f"body {label} (part {pid}) carries {cond.text}, "
                    + _class_why(cls, cond, label, axis, driven)), None
    return None, JointScrewPlan(
        screw=s, a_pid=a, b_pid=b, axis=axis,
        r=(float(r[0]), float(r[1]), float(r[2])), length=l13, drive=pm,
        split_inter_ids=split, merged=merged,
        body_nodes=frozenset(pid_nodes[a] | pid_nodes[b]))


def _resolve_joint_screws(state: ConversionState) -> List[JointScrewPlan]:
    """The ONE decision over every ``*CONSTRAINED_JOINT_SCREW``, memoised on
    ``state.joint_screw_plan``. Draws no id: a refused screw leaves its deck
    byte-identical to ``--no-joint-screw-gjoint``."""
    if state.joint_screw_plan is not None:
        return state.joint_screw_plan
    plans: List[JointScrewPlan] = []
    state.joint_screw_plan = plans
    if not state.joint_screws:
        return plans
    if not state.options.joint_screw_gjoint:
        state.warn(
            f"--no-joint-screw-gjoint: {len(state.joint_screws)} "
            "*CONSTRAINED_JOINT_SCREW card(s) left unconverted (listed as "
            "skipped, as before round 7): the screw relation between the two "
            "rigid bodies is lost (EXP_SC_JOINT_SCREW: nut travel 0 against "
            "LS-DYNA's 183.59 mm at the converted run's last sample, t "
            "0.09995).")
        return plans
    node_parts = _node_parts(state)
    cnrb_nodes = _cnrb_nodes(state)
    taken: Set[int] = set()
    for s in state.joint_screws:
        why, plan = _screw_refusal(state, s, node_parts, cnrb_nodes, taken)
        if plan is None:
            state.warn(
                f"*{s.keyword} {s.jid}: NOT converted - {why}; the joint is "
                "listed as skipped and the two bodies keep their *MAT_RIGID "
                "constraints and drive (no screw relation between them).")
            continue
        taken.update((plan.a_pid, plan.b_pid))
        plans.append(plan)
    return plans


def screw_cmo_skip_pids(state: ConversionState) -> Set[int]:
    """The *MAT_RIGID parts whose CMO ``/BCS`` (and A1's ``rigid_auto_bcs``
    record of it) is NOT written: both bodies of every converted screw. The
    ONE predicate the /RBODY producer reads."""
    return {p for plan in (state.joint_screw_plan or [])
            for p in (plan.a_pid, plan.b_pid)}


def screw_drives(state: ConversionState) -> List[PrescribedMotionRigid]:
    """The rotation drives the joint section re-writes as /IMPVEL/LAGMUL (the
    imposed-motion section skips them, by identity). An undriven screw (round
    8, B8 q-i) has none."""
    return [plan.drive for plan in (state.joint_screw_plan or [])
            if plan.drive is not None]


def screw_merged_members(state: ConversionState) -> Set[int]:
    """The element nodes of both bodies of every converted screw (round 8, B8
    q-ii): every standard code the deck states on one of them was classified
    by refusal 11 and is HELD by the joint (any other code refused it), so
    the writers that re-point a member's code onto the body's /RBODY main
    node - ``_make_bcs`` and the ``*NODE`` TC/RC pass (which also carries the
    ``*CONSTRAINED_GLOBAL`` cells) - write it nowhere. The ONE predicate
    both read, at the member, before the re-point (a member, not the main
    node: a node the classification did not see keeps today's card)."""
    return {n for plan in (state.joint_screw_plan or [])
            for n in plan.body_nodes}


def screw_pad_pids(state: ConversionState) -> Dict[int, JointScrewPlan]:
    """Part A of every converted UNDRIVEN screw (round 8, B8 q-i) -> its
    plan: the /RBODY producer pads that body's J row (:func:`screw_pad`)."""
    return {plan.a_pid: plan for plan in (state.joint_screw_plan or [])
            if plan.drive is None}


def screw_pad(state: ConversionState, plan: JointScrewPlan, nodes: Set[int],
              j_vals: Tuple[float, ...],
              lumped: Tuple[Dict[int, float], Dict[int, float]],
              icog4: bool) -> Tuple[float, ...]:
    """A's J row plus the transverse inertia pad of an UNDRIVEN screw (round
    8, B8 q-i), recorded on the plan for the joint's sentence.

    OpenRadioss's Lagrange solver corrects a rotational acceleration with
    ONE scalar per node, ``AR = AR - XLL / IN`` (``lag_mult_solv.F:393``),
    and the starter sets a rigid body's main-node ``IN`` to its SMALLEST
    principal inertia (``inirby.F:838``). Without a drive the rack turns A
    about the screw axis, so the scalar must be A's inertia about THAT axis:
    ``dJ = I_axis`` is added to the two diagonal J cells normal to it (the
    J cells ADD to the tensor ``inirby.F`` assembles). ``I_axis`` is the
    starter's tensor on the axis: the point masses of the lumped masses about
    their centre of mass (``rbody._body_tensor``), the nodal ``IN`` and the
    J cells already in the row (A2's ``-SUM(IN)`` included) - or the J
    cells alone under ``*PART_INERTIA`` (ICoG 4: the deck's tensor). A's
    transverse rotations are held by its ``/BCS/LAGMUL``, so the pad acts on
    locked DOFs only."""
    from ..lumping import _sym3_eigen
    from .rbody import _body_tensor           # local: rbody imports us
    mass_by_node, in_by_node = lumped
    if icog4:
        t = [[0.0] * 3 for _ in range(3)]
    else:
        t = _body_tensor(state, nodes, mass_by_node)
        sum_in = math.fsum(in_by_node.get(n, 0.0) for n in sorted(nodes))
        for i in range(3):
            t[i][i] += sum_in
    for i in range(3):
        t[i][i] += j_vals[i]
    for (p, q), v in (((0, 1), j_vals[3]), ((1, 2), j_vals[4]),
                      ((0, 2), j_vals[5])):
        t[p][q] += v
        t[q][p] += v
    k = plan.axis
    i_axis = t[k][k]
    pad = (i_axis if k != 0 else 0.0, i_axis if k != 1 else 0.0,
           i_axis if k != 2 else 0.0)
    for i in range(3):
        t[i][i] += pad[i]
    plan.pad = pad
    plan.i_axis = i_axis
    plan.padded_min = min(_sym3_eigen(t)[0])
    return (j_vals[0] + pad[0], j_vals[1] + pad[1], j_vals[2] + pad[2],
            j_vals[3], j_vals[4], j_vals[5])


class LagrangePair(NamedTuple):
    """Two rigid bodies whose RELATIVE motion an emitted Lagrange set
    prescribes (round 8, B8 q-iii): *tag* names the split's surfaces and
    interface, *label* the joint in the warning."""
    a_pid: int
    b_pid: int
    tag: str
    label: str


def lagrange_held_pairs(state: ConversionState,
                        inter_id: int) -> List[LagrangePair]:
    """The rigid pairs the all-parts self-contact *inter_id* must split out
    (round 8, B8 q-iii; round 7's ``screw_splits`` predicate, moved here): a
    contact force on a rigid body whose main node a Lagrange condition holds
    is cancelled on the main node alone (RBYVIT, ``resol.F:7572``, runs
    before LAG_MULT, ``:7901``). Today the converted screws' pairs only; a
    future ``/GJOINT`` gear / pulley / rack-and-pinion or an ``/MPC`` on
    rigid nodes inherits the split by registering its pairs here."""
    return [LagrangePair(plan.a_pid, plan.b_pid, f"screw_{plan.screw.jid}",
                         f"*CONSTRAINED_JOINT_SCREW {plan.screw.jid}")
            for plan in (state.joint_screw_plan or [])
            if inter_id in plan.split_inter_ids]


def _vec_row(v) -> str:
    return f"{_f(v[0])}{_f(v[1])}{_f(v[2])}"


def _make_joint_screws(state: ConversionState, rbody_info: Dict) -> List[str]:
    """The joint cards of every converted screw (after the /RBODY producers,
    whose carriage producer filled the plan's node ids):

    * ``/GRNOD/NODE`` - the carriage main node;
    * ``/BCS/LAGMUL`` on the carriage: Tra '1' except '0' on the screw axis,
      Rot 111 - it may only slide along the axis;
    * ``/BCS/LAGMUL`` on A's main: Tra 000, Rot '1' except '0' on the axis -
      A may only spin about it;
    * the drive (none on an undriven screw, round 8):
      ``/IMPVEL/LAGMUL`` Dir XX / YY / ZZ on A's main, on the
      differentiated displacement curve (VAD 2) or the deck's own velocity
      curve (VAD 0), ``Ascale_x 1`` / ``Fscale_y SF`` (the radioss110 card
      the /BEGIN 2022 deck reads; ``read_impvel_lagmul.F:160-161``, zeros
      defaulted at ``:181-187``);
    * ``/GJOINT/RACK``: node_ID0 = the carriage, FscaleV = -1/PARM (the
      reader inverts the cell, ``hm_read_gjoint.F:221``), node_ID1 = A's main
      (the spinning body), node_ID2 = B's main, r1 = r2 = the unit screw axis
      (N3 -> N1), every Mass / Inertia cell 0 (the carriage /RBODY supplies
      node_ID0's).

    The keyword leaves ``skipped_keywords`` here, at the line that writes the
    ``/GJOINT``."""
    from .loads import _pm_sf                 # local: loads imports us
    plans = state.joint_screw_plan or []
    if not plans:
        return []
    lines: List[str] = ["#-  SCREW JOINTS (*CONSTRAINED_JOINT_SCREW -> "
                        "/GJOINT/RACK):", HDR]
    for plan in plans:
        s = plan.screw
        jid = s.jid
        k = plan.axis
        pm = plan.drive
        g_n0 = state.next_grnod_id()
        lines += _emit_grnod_node(g_n0, f"SCREW_{jid}_carriage_main",
                                  [plan.n0])
        bc_car = state.next_id()
        lines += [f"/BCS/LAGMUL/{bc_car}", f"SCREW_{jid}_carriage",
                  "#  Tra rot   skew_ID  grnod_ID",
                  f"   {_code(k, '0')} 111{_i(0)}{_i(g_n0)}", HDR]
        bc_a = state.next_id()
        lines += [f"/BCS/LAGMUL/{bc_a}", f"SCREW_{jid}_body_A",
                  "#  Tra rot   skew_ID  grnod_ID",
                  f"   000 {_code(k, '0')}{_i(0)}{_i(plan.a_ind_grnod)}", HDR]
        drive_clause = ""
        # an UNDRIVEN screw (round 8, B8 q-i) writes no drive and no /FUNCT,
        # and draws no id for them
        if pm is not None:
            if pm.vad == 2:
                fid = state.next_curve_id()
                pts = state.curves[pm.lcid].pts
                deriv = screw_drive_derivative(pts)
                w = min(_RAMP, 0.01 * min(pts[i + 1][0] - pts[i][0]
                                          for i in range(len(pts) - 1)))
                lines += _emit_drive_funct(
                    fid, f"SCREW_{jid}_dTHETA_dt_{pm.lcid}", deriv)
                drive_clause = (
                    f"; the drive's VAD 2 displacement curve {pm.lcid} is "
                    f"DIFFERENTIATED into /FUNCT/{fid} (slope steps as "
                    f"{w:g}-wide ramps), so a slope corner at the termination "
                    "time moves the last cycle's kinetic energy "
                    "(EXP_SC_JOINT_SCREW: the 250 -> 170 rad/s corner sits "
                    "exactly at t_end 0.1; one printed cycle earlier the KE "
                    "reads +0.17 % where the last reads -16.51 %)")
            else:
                fid = pm.lcid
            imp = state.next_id()
            lines += [f"/IMPVEL/LAGMUL/{imp}", f"SCREW_{jid}_drive",
                      "#  fct_IDT       Dir   Skew_ID             grnd_ID",
                      f"{_i(fid)}{_DIRS[k]:>10}{_i(0)}{'':10}"
                      f"{_i(plan.a_ind_grnod)}",
                      "#           Ascale_x            Fscale_y",
                      f"{_f(1.0)}{_f(_pm_sf(state, pm))}", HDR]
        gid = state.next_id()
        fs = -1.0 / s.parm
        lines += [f"/GJOINT/RACK/{gid}", f"SCREW_{jid}",
                  "# node_ID0             FscaleV                Mass"
                  "             Inertia  node_ID1  node_ID2  node_ID3",
                  f"{_i(plan.n0)}{_f(fs)}{_f(0.0)}{_f(0.0)}{_i(plan.a_main)}"
                  f"{_i(plan.b_main)}{_i(0)}",
                  "#              Mass1            Inertia1"
                  "                 r1x                 r1y                 r1z",
                  f"{_f(0.0)}{_f(0.0)}{_vec_row(plan.r)}",
                  "#              Mass2            Inertia2"
                  "                 r2x                 r2y                 r2z",
                  f"{_f(0.0)}{_f(0.0)}{_vec_row(plan.r)}",
                  "#              Mass3            Inertia3"
                  "                 r3x                 r3y                 r3z",
                  f"{_f(0.0)}{_f(0.0)}{_vec_row((0.0, 0.0, 0.0))}", HDR]
        state.skipped_keywords.remove(s.keyword)
        rr = "(" + ", ".join(f"{v:g}" for v in plan.r) + ")"
        rewritten = ("the bodies' *MAT_RIGID constraints and the drive are "
                     "re-written as /BCS/LAGMUL and /IMPVEL/LAGMUL"
                     if pm is not None else
                     "the bodies' *MAT_RIGID constraints are re-written as "
                     "/BCS/LAGMUL")
        work = (" On this path EXT-WORK prints 0 and the energy error "
                "0.0 % (LAG_MULT runs after the REAC* bracket, resol.F:7305 / "
                ":7386 / :7901): the drive's work is E(t) - E(0) of the global "
                "energies." if pm is not None else "")
        state.warn(
            f"*CONSTRAINED_JOINT_SCREW {jid} -> /GJOINT/RACK/{gid} (Lagrange "
            f"multipliers): node_ID1 = the spinning body {plan.a_pid}'s main "
            f"node {plan.a_main}, node_ID2 = {plan.b_pid}'s {plan.b_main}, "
            f"node_ID0 = a synthesized carriage /RBODY/{plan.n0} (Mass and "
            "inertia 1e-6; its two massless secondaries sit 0.1 x |N1N3| off "
            "the axis - a geometric convention) that translates with "
            f"{plan.a_pid} along the screw axis {rr}; FscaleV = -1/PARM = "
            f"{fs:g} (the reader inverts it, hm_read_gjoint.F:221); "
            f"{rewritten} (a standard condition on a "
            f"Lagrange node is incompatible){drive_clause}. This joint is "
            "EXACT, where LS-DYNA's default joint (no *CONTROL_RIGID: LMF 0) "
            f"is a PENALTY joint that yields (RPS {s.rps:g} is not used): on "
            "EXP_SC_JOINT_SCREW LS-DYNA's nut moved 12.08-12.35 mm/rad at "
            "the fifths of the run (12.25 at its t_end) against the exact "
            "12.5, so the converted nut runs +1.15 % ahead at its last "
            "sample (185.70 vs LS-DYNA's 183.59 mm at the same instant, t "
            "0.09995; travel RMS 0.88 % of the LS-DYNA peak) and meets the "
            "shells about 0.6 ms early (IE +42.76 % at the end, from -100 %; "
            "nt 4, 0.9998x cycles) - no penalty screw exists in OpenRadioss "
            "(/PROP/TYPE45 Types 1-9, prop_p45_kjoint2.cfg). SMP ONLY: with "
            "-np > 1 the engine stops in its first cycle, before any row is "
            "printed, with '** ERROR: BCS WITH LAGRANGE MULTIPLIER NOT "
            "ENABLED FOR NSPMD > 1' (lag_mult.F:667-671, the two "
            "/BCS/LAGMUL; the JOINT check at :682-686 would follow) - run "
            f"-np 1 with threads.{work}"
            + ("" if pm is not None else " " + _undriven_sentence(plan)))
        for label, pid, cond in plan.merged:
            state.warn(
                f"*CONSTRAINED_JOINT_SCREW {jid}: {cond.text} on body {label} "
                f"(part {pid}) acts on DOFs the converted joint already holds "
                "(its /BCS/LAGMUL and /GJOINT/RACK links): not written - a "
                "second, standard condition on the Lagrange-held main node is "
                "starter WARNING 312. MEASURED on EXP_SC_JOINT_SCREW (nt 4): "
                "such a redundant code moves the result only inside the "
                "deck's null band (the internal energy at the last fifth "
                "moves 0 .. +2.59 % under physically empty edits of the "
                "joint; a kept *BOUNDARY_SPC DOFY -0.07 %, a kept *NODE TC 3 "
                "+2.57 %).")
    return lines


def _undriven_sentence(plan: JointScrewPlan) -> str:
    """The undriven screw's sentence (round 8, B8 q-i), appended to the rack
    sentence; the pad's figures come from the /RBODY producer's record."""
    jid = plan.screw.jid
    head = (f"*CONSTRAINED_JOINT_SCREW {jid} has NO drive: converted without "
            "/IMPVEL/LAGMUL - the rack alone ties A's spin to B's travel "
            "(x_B - x_A = PARM x theta, PARM = x_dot / omega per radian, "
            "Vol I R17 p.10-65 / Figure 10-29). ")
    if plan.pad is None:
        return head + (
            f"A's /RBODY (part {plan.a_pid}) was not written by the part "
            "producer, so no inertia pad was added: OpenRadioss's Lagrange "
            "solver divides a rotational acceleration by the main node's IN "
            "= the smallest principal inertia (inirby.F:838; "
            "lag_mult_solv.F:393), which then stands in for the screw-axis "
            "inertia.")
    d_j = max(plan.pad)
    below = ""
    if plan.padded_min < plan.i_axis * (1.0 - 1e-6):
        pct = 100.0 * (plan.i_axis - plan.padded_min) / plan.i_axis
        below = (f", {pct:.3g} % below it: A's products of inertia couple "
                 "the screw axis to its normals")
    return head + (
        f"A's /RBODY gets an added inertia {d_j:g} about the two axes normal "
        "to the screw axis, so that its smallest principal inertia is its "
        f"screw-axis inertia {plan.i_axis:g} (now {plan.padded_min:g}{below}): "
        "OpenRadioss's Lagrange solver divides a rotational acceleration by "
        "ONE scalar, the main node's IN = the smallest principal inertia "
        "(inirby.F:838; lag_mult_solv.F:393), and A's transverse rotations "
        "are held by /BCS/LAGMUL, so the pad acts on locked DOFs only. "
        "MEASURED on EXP_SC_JOINT_SCREW without its drive (nt 4): a free "
        "spin of 150 rad/s projects to 147.716 rad/s, the closed form "
        "(145.989 rad/s = -1.17 % without the pad, the smallest principal "
        "inertia 1110.2 standing in for 1972.3); under a constant axial load "
        "pair the spin follows its closed form within 0.05 % before contact "
        "with a 0.0 % energy error (+75.5 % too fast and a +75.6 % energy "
        "error behind NORMAL TERMINATION without the pad).")


def _emit_drive_funct(fid: int, title: str,
                      pts: List[Tuple[float, float]]) -> List[str]:
    """The differentiated drive curve as a plain /FUNCT (the abscissae are
    strictly increasing by construction)."""
    out = [f"/FUNCT/{fid}", title[:100], "#                  X                   Y"]
    out += [f"{_f(x)}{_f(y)}" for x, y in pts]
    out.append(HDR)
    return out
