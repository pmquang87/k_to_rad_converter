"""Joint constraints: *CONSTRAINED_JOINT_* -> /PROP/TYPE45 (KJOINT2) + /SPRING.

One LS-DYNA joint becomes one synthesized /PROP/TYPE45 + /PART + 2..4-node
/SPRING, plus a /SKEW/FIX carrying the joint frame computed from the joint's own
node geometry. *CONSTRAINED_JOINT_STIFFNESS_GENERALIZED / _TRANSLATIONAL fills
that property's per-DOF stiffness / damping / friction / stop blocks.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from ..state import (
    ConversionState, ConstrainedJoint, JointStiffness,
    JOINT_TYPE45, JOINT_NNOD_REQ, JOINT_TYPE45_DOFS,
)
from .common import HDR, _f, _i, _part_node_sets, _vcross, _vnorm, _vsub
from .mesh import _emit_skew_fix, _skew_axes_from_nodes

__all__ = [
    "DEG2RAD",
    "JointDof",
    "_transverse_axes",
    "_joint_frame",
    "_coord_axes",
    "_resolve_joints",
    "_emit_type45_dof",
    "_emit_prop_type45",
    "_match_joint_stiffness",
    "_stiffness_dof_map",
    "_make_joints",
]

#: LS-DYNA stop angles (NSA*/PSA*/SAAL/NSABT/PSABT) are DEGREES; the Radioss
#: SA+/SA- stop angles and the abscissae of rotational functions are RADIANS.
#: dyna2rad hard-codes 0.01745; the exact factor costs nothing and is not a
#: 5-significant-digit truncation of a value that multiplies every stop angle.
DEG2RAD = math.pi / 180.0

#: |cos| above which a *DEFINE_COORDINATE axis counts as "the joint axis" when
#: deciding which GENERALIZED Euler channel (phi/theta/psi) drives Radioss Rx.
#: dyna2rad uses the same 0.99 (convertconstrainedjoints.cxx:292-302).
_AXIS_MATCH_COS = 0.99

#: |cos(x, y)| at or above which GET_SKEW45 rejects the two frame-defining
#: vectors as colinear (rini45.F:556, 611 -> ERROR 1009).
_COLINEAR_COS = 0.98


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class JointDof:
    """The three cards of one /PROP/TYPE45 free DOF.

    Field names follow the rotational spelling; the translational counterparts
    occupy the same columns (Ktx/Ctx/Kftx/FFx/SDx+- instead of
    Krx/Crx/Kfrx/FMx/SAx+-).
    """

    __slots__ = ("k", "fct_k", "smin", "smax", "c", "fct_c", "kf", "flim",
                 "fct_f")

    def __init__(self, k: float = 0.0, fct_k: int = 0, smin: float = 0.0,
                 smax: float = 0.0, c: float = 0.0, fct_c: int = 0,
                 kf: float = 0.0, flim: float = 0.0, fct_f: int = 0):
        self.k = k              # Kt/Kr    linear stiffness (or the function's
        self.fct_k = fct_k      # fct_Kt/fct_Kr   ordinate scale when fct != 0)
        self.smin = smin        # SD-/SA-  negative stop (must be <= 0)
        self.smax = smax        # SD+/SA+  positive stop (must be >= 0)
        self.c = c              # Ct/Cr    viscous damping
        self.fct_c = fct_c      # fct_Ct/fct_Cr
        self.kf = kf            # Kft/Kfr  elastic stiffness for friction+stops
        self.flim = flim        # FF/FM    friction force / moment limit
        self.fct_f = fct_f      # fct_ff/fct_fm

    def is_empty(self) -> bool:
        return not (self.k or self.fct_k or self.smin or self.smax or self.c
                    or self.fct_c or self.kf or self.flim or self.fct_f)


# ─────────────────────────────────────────────────────────────────────────────
# Joint frame (the /SKEW/FIX axes)
# ─────────────────────────────────────────────────────────────────────────────

def _transverse_axes(x):
    """GET_SKEW45's transverse-axis rule for a frame defined by one vector only
    (rini45.F:455-488): with HH the 1-based index of the largest |x| component,
    ``HH < 3 -> y = (-x2, x1, 0)``, otherwise ``y = (0, x3, -x2)``; then
    ``z = x cross y``. Both candidates are perpendicular to x by construction,
    and picking the largest component keeps y well away from zero length.

    Returns (y, z) as unit vectors, or None when x is degenerate.
    """
    hh = max(range(3), key=lambda i: abs(x[i]))     # 0-based; Fortran HH-1
    if hh < 2:
        y = _vnorm((-x[1], x[0], 0.0))
    else:
        y = _vnorm((0.0, x[2], -x[1]))
    if y is None:
        return None
    z = _vnorm(_vcross(x, y))
    if z is None:
        return None
    return y, z


def _joint_frame(state: ConversionState, jtype: int, nodes: List[int]):
    """(origin, x, y, z) of the joint's local frame from its /SPRING node list.

    Mirrors GET_SKEW45 (rini45.F:380-658) branch for branch, so the emitted
    /SKEW/FIX is the SAME frame the starter would build from the nodes — the
    skew is a fallback (the node branches are tested first, the Skew_ID1 branch
    last), not an override. Writing it anyway is what suppresses ERROR 936 when
    a joint carries fewer nodes than its Type requires.

      2 nodes            x = N2 - N1, transverse rule
      3 nodes            x = N3 - N1, transverse rule       (ERROR 935 if zero)
      >=4, Type != 5     x = N3 - N1, ybar = N4 - N1, z = x X ybar, y = z X x
      >=4, Type == 5     y = N3 - N1, z = N4 - N1, x = y X z   (universal)

    Returns None when a node is missing, the axis is degenerate, or the two
    frame-defining vectors are colinear (the starter's own ERROR 934/935/1009
    conditions).
    """
    pts = []
    for nid in nodes:
        nd = state.nodes.get(nid)
        if nd is None:
            return None
        pts.append((nd.x, nd.y, nd.z))
    if len(pts) < 2:
        return None
    origin = pts[0]

    if len(pts) >= 4:
        a = _vnorm(_vsub(pts[2], pts[0]))
        b = _vnorm(_vsub(pts[3], pts[0]))
        if a is None or b is None:
            return None
        if abs(_dot(a, b)) >= _COLINEAR_COS:
            return None
        if jtype == 5:
            # Universal: the two cross-axle directions ARE local y and z.
            y, z0 = a, b
            x = _vnorm(_vcross(y, z0))
            if x is None:
                return None
            z = _vnorm(_vcross(x, y))
            if z is None:
                return None
            return origin, x, y, z
        x = a
        z = _vnorm(_vcross(x, b))
        if z is None:
            return None
        y = _vnorm(_vcross(z, x))
        if y is None:
            return None
        return origin, x, y, z

    tip = pts[2] if len(pts) >= 3 else pts[1]
    x = _vnorm(_vsub(tip, pts[0]))
    if x is None:
        return None
    yz = _transverse_axes(x)
    if yz is None:
        return None
    return origin, x, yz[0], yz[1]


def _coord_axes(state: ConversionState, cid: int):
    """The right-handed orthonormal (X, Y, Z) triad of a *DEFINE_COORDINATE_*,
    identical to the frame k2rad's /SKEW/FIX/<cid> already carries (so index 0
    is exactly that skew's local X). Returns None when cid is unknown or
    degenerate.

    dyna2rad's own p_GetLocalAxesFromDefineCoordinate returns a LEFT-handed and
    (for the _SYSTEM/_VECTOR form) unnormalised triad — it computes
    ``axis2 = axis1 x axis3``, which is the negative of the second axis. That is
    why its skew writer has to sprinkle minus signs. k2rad reuses the converted
    coordinate systems instead, so the triad is right-handed by construction.
    """
    cs = state.coord_sys.get(cid)
    if cs is not None:
        origin = (cs.xo, cs.yo, cs.zo)
        x = _vnorm(_vsub((cs.xl, cs.yl, cs.zl), origin))
        if x is None:
            return None
        z = _vnorm(_vcross(x, _vsub((cs.xp, cs.yp, cs.zp), origin)))
        if z is None:
            return None
        return x, _vcross(z, x), z
    cn = state.coord_nodes.get(cid)
    if cn is not None:
        axes = _skew_axes_from_nodes(state, cn)
        if axes is None:
            return None
        _o, x, y = axes
        return x, y, _vcross(x, y)
    cv = state.coord_vectors.get(cid)
    if cv is not None:
        x = _vnorm((cv.xx, cv.yx, cv.zx))
        if x is None:
            return None
        z = _vnorm(_vcross((cv.xx, cv.yx, cv.zx), (cv.xv, cv.yv, cv.zv)))
        if z is None:
            return None
        return x, _vcross(z, x), z
    return None


# ─────────────────────────────────────────────────────────────────────────────
# build_starter prepass
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_joints(state: ConversionState) -> None:
    """build_starter prepass: reserve a /SKEW id for every joint whose frame is
    computable, and register every joint /SPRING node.

    Both jobs must happen before the sections run, not inside _make_joints:

    * /SKEW and /FRAME share ONE starter id namespace (state.all_skew_ids), so
      an id claimed later than /FRAME allocation can collide -> ERROR 79.
    * the implicit free-node guard (_make_free_node_constraints) would otherwise
      see a joint node attached to no element and /BCS 111 111 it, welding the
      joint solid. Registering here makes that independent of section order.
    """
    if not state.constrained_joints:
        return
    reserved = state.all_skew_ids()

    for idx, jnt in enumerate(state.constrained_joints):
        nodes = jnt.spring_nodes()
        # Same admission test _make_joints applies: a joint that will be
        # dropped emits no spring, so its nodes must stay visible to the
        # free-node guard (they may genuinely be dangling).
        if jnt.n1 <= 0 or jnt.n2 <= 0 or any(n not in state.nodes
                                             for n in nodes):
            continue
        state.joint_spring_nodes.update(nodes)
        if len(nodes) < 2:
            continue
        jtype = JOINT_TYPE45.get(jnt.kind, 0)
        if _joint_frame(state, jtype, nodes) is None:
            continue
        sid = state.next_id()
        while sid in reserved:
            sid = state.next_id()
        reserved.add(sid)
        state.joint_skew_ids[idx] = sid


# ─────────────────────────────────────────────────────────────────────────────
# /PROP/TYPE45 card emission
# ─────────────────────────────────────────────────────────────────────────────

def _emit_type45_dof(name: str, d: JointDof) -> List[str]:
    """The three cards of one /PROP/TYPE45 free DOF.

    Card A  ``%20lg%10d%20lg%20lg%10d``   K, fct_K, stop-, stop+, Icomb
    Card B  ``%20lg%10d``                 C, fct_C
    Card C  ``%20lg%20lg%10d``            Kf, friction limit, fct_f

    Icomb is always 0: combining stops across DOFs needs at least two flagged
    DOFs carrying IDENTICAL stop values (hm_read_prop45.F:1020-1068), otherwise
    the starter raises ERROR 1598/1599/1600. Nothing in *CONSTRAINED_JOINT_
    STIFFNESS expresses a combined stop, so leaving them independent is the only
    safe reading.
    """
    rot = name[0] == "R"
    ax = name[1]
    k, kf, c = (f"Kr{ax}", f"Kfr{ax}", f"Cr{ax}") if rot else \
               (f"Kt{ax}", f"Kft{ax}", f"Ct{ax}")
    stop = f"SA{ax}" if rot else f"SD{ax}"
    icomb = f"Icomb_r{ax}" if rot else f"Icomb_t{ax}"
    lim = f"FM{ax}" if rot else f"FF{ax}"
    fct_f = f"fct_fm{ax}" if rot else f"fct_ff{ax}"
    return [
        f"#{k:>19}{('fct_' + k):>10}{(stop + '-'):>20}{(stop + '+'):>20}{icomb:>10}",
        f"{_f(d.k)}{_i(d.fct_k)}{_f(d.smin)}{_f(d.smax)}{_i(0)}",
        f"#{c:>19}{('fct_' + c):>10}",
        f"{_f(d.c)}{_i(d.fct_c)}",
        f"#{kf:>19}{lim:>20}{fct_f:>10}",
        f"{_f(d.kf)}{_f(d.flim)}{_i(d.fct_f)}",
    ]


def _emit_prop_type45(prop_id: int, title: str, jtype: int, scf: float,
                      skew1: int = 0, skew2: int = 0,
                      dofs: Optional[Dict[str, JointDof]] = None) -> List[str]:
    """/PROP/TYPE45 (= /PROP/KJOINT2). Layout: prop_p45_kjoint2.cfg
    FORMAT(radioss2019) — the newest TYPE45 reader format <= /BEGIN-2022
    (radioss2020/2021/2022 ship no TYPE45 cfg at all). The Icomb_* column
    (cols 71-80 of every stiffness card) was ADDED in 2019; a 2017/2018 header
    would not read it.

    Card 1 ``%10d%20lg%20lg%20lg%10d%10d%10d``:
        Type Kn ScF Cr sens_ID Skew_ID1 Skew_ID2

    ``Kn = 0`` always: zero means "compute the blocked-DOF stiffness from the
    time step", which is what an LS-DYNA joint asks for — its RPS is a
    dimensionless multiplier on an internally computed penalty, not a stiffness.
    ``Cr = 0`` likewise takes the starter's 0.05 (hm_read_prop45.F:155); a value
    outside [0,1] would be ERROR 388.

    The per-DOF blocks are ALL-OR-NOTHING. The starter counts them and compares
    against the Type's requirement (0 or 3 for Type 1, 0 or 2 for Type 3/5/7,
    0 or 3 for Type 4, 0 or 6 for Type 9) -> ERROR 973 ``ONLY %d DOF DEFINED %d
    REQUIRED`` on a partial set. Passing ``dofs=None`` emits header + title +
    card 1 only, which is a complete and valid pure-kinematic joint.
    """
    lines = [
        f"/PROP/TYPE45/{prop_id}",
        title[:100],
        "#     Type                  Kn                 ScF                  Cr   sens_ID  Skew_ID1  Skew_ID2",
        f"{_i(jtype)}{_f(0.0)}{_f(scf)}{_f(0.0)}{_i(0)}{_i(skew1)}{_i(skew2)}",
    ]
    if dofs:
        for name in JOINT_TYPE45_DOFS.get(jtype, ()):
            lines += _emit_type45_dof(name, dofs.get(name) or JointDof())
    lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# *CONSTRAINED_JOINT_STIFFNESS -> DOF blocks
# ─────────────────────────────────────────────────────────────────────────────

def _match_joint_stiffness(state: ConversionState
                           ) -> Dict[int, JointStiffness]:
    """Attach every *CONSTRAINED_JOINT_STIFFNESS card to a joint index.

    JID given  -> the joint with that _ID id.
    JID blank  -> node membership, dyna2rad's rule (joints.cxx:170-183): a joint
                  qualifies when any of N1..N4 lies in PIDA's node inventory AND
                  any lies in PIDB's. Part nodes are the element nodes plus the
                  *CONSTRAINED_EXTRA_NODES attached to that part — a joint node
                  on a rigid body usually arrives that way.
    """
    matched: Dict[int, JointStiffness] = {}
    if not state.joint_stiffnesses:
        return matched
    by_jid = {j.jid: i for i, j in enumerate(state.constrained_joints) if j.jid}

    pnodes: Dict[int, set] = {p: set(v) for p, v in
                              _part_node_sets(state).items()}
    for pid, extra in state.extra_rigid_nodes.items():
        pnodes.setdefault(pid, set()).update(n for n in extra if n > 0)

    for st in state.joint_stiffnesses:
        targets: List[int] = []
        if st.jid:
            idx = by_jid.get(st.jid)
            if idx is None:
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid}: "
                    f"JID={st.jid} matches no *CONSTRAINED_JOINT_*_ID card — "
                    "the stiffness/damping/stop data is NOT converted. (Only a "
                    "joint written with the _ID or _TITLE option carries an id "
                    "a JID can point at.)")
                continue
            targets = [idx]
        else:
            a = pnodes.get(st.pida, set())
            b = pnodes.get(st.pidb, set())
            for i, j in enumerate(state.constrained_joints):
                cand = [n for n in (j.n1, j.n2, j.n3, j.n4) if n > 0]
                if any(n in a for n in cand) and any(n in b for n in cand):
                    targets.append(i)
            if not targets:
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid}: "
                    f"no joint has a node on both PIDA={st.pida} and "
                    f"PIDB={st.pidb} — the stiffness/damping/stop data is NOT "
                    "converted. Give the card a JID (and the joint an _ID) to "
                    "bind it explicitly, or attach the joint nodes to the two "
                    "parts with *CONSTRAINED_EXTRA_NODES.")
                continue
            if len(targets) > 1:
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid}: "
                    f"{len(targets)} joints connect PIDA={st.pida} to "
                    f"PIDB={st.pidb}, so the card is ambiguous — it was applied "
                    "to ALL of them. Add a JID to bind it to one joint.")
        for idx in targets:
            if idx in matched:
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid}: "
                    "a second stiffness card targets the same joint; only the "
                    f"first (JSID={matched[idx].jsid}) is converted. One "
                    "/PROP/TYPE45 holds one set of DOF blocks.")
                continue
            matched[idx] = st
    return matched


def _stiffness_dof_map(jtype: int, option: str, axis_index: int
                       ) -> Dict[str, int]:
    """{DOF name -> stiffness-card channel index} for one joint Type.

    GENERALIZED carries three ROTATIONAL channels (phi, theta, psi — z-y-z Euler
    angles of body B relative to body A in CIDA); TRANSLATIONAL carries three
    TRANSLATIONAL ones (x, y, z of CIDA).

    A single-free-axis joint (revolute 2, cylindrical 3, translational 6) has
    exactly one DOF about/along the joint axis, so *axis_index* — which CIDA
    axis the joint axis is aligned with — selects the channel that drives it.
    That is exact: for a revolute joint the manual's own worked example is
    phi about local x of CIDA.

    A multi-DOF joint (spherical 1, planar 4, universal 5) gets the direct
    phi->Rx, theta->Ry, psi->Rz mapping, which is an APPROXIMATION: z-y-z Euler
    angles are not the Radioss local rotations. Channels whose DOF the Type does
    not have are dropped by the caller (which warns).
    """
    dofs = JOINT_TYPE45_DOFS.get(jtype, ())
    if option == "GENERALIZED":
        if jtype in (2, 3) and "Rx" in dofs:
            return {"Rx": axis_index}
        return {n: i for n, i in (("Rx", 0), ("Ry", 1), ("Rz", 2))
                if n in dofs}
    if jtype in (3, 6) and "Tx" in dofs:
        return {"Tx": axis_index}
    return {n: i for n, i in (("Tx", 0), ("Ty", 1), ("Tz", 2)) if n in dofs}


def _build_dofs(state: ConversionState, ref: str, jtype: int,
                st: JointStiffness, axis_index: int) -> Dict[str, JointDof]:
    """Fill the Type's DOF blocks from one stiffness card, warning about every
    channel that carries data the Type has no DOF for."""
    rot = st.option == "GENERALIZED"
    chan_names = ("phi", "theta", "psi") if rot else ("x", "y", "z")
    # The LS-DYNA elastic-stop-stiffness field name of each channel, so a
    # warning names the column the user has to edit.
    es_names = ("ESPH", "EST", "ESPS") if rot else ("ESX", "ESY", "ESZ")
    used = _stiffness_dof_map(jtype, st.option, axis_index)
    out: Dict[str, JointDof] = {}

    for name, ch in sorted(used.items()):
        d = JointDof()
        # Kr/Kt is the ORDINATE SCALE when a function is given; the starter
        # forces it to 1.0 if left blank (LEC_DOF_JNT:1420). A linear
        # LS-DYNA stiffness is only ever expressed as a curve here, so the
        # magnitude field stays 0 and the curve carries the physics.
        d.fct_k = st.lcid[ch]
        d.fct_c = st.dlcid[ch]
        d.kf = st.es[ch]
        fm = st.fm[ch]
        if fm < 0.0:
            # LS-DYNA: a negative FM*/FF* means -FM* is a curve (or table) id
            # for the yield moment/force. Radioss has a separate field for
            # that, and the magnitude must then stay blank (scale -> 1.0).
            d.fct_f = int(round(-fm))
        else:
            d.flim = fm
        # Stops: sign-forced regardless of how the .k wrote them. SA-/SD- > 0
        # is starter ERROR 943 and SA+/SD+ < 0 is ERROR 944.
        scale = DEG2RAD if rot else 1.0
        d.smin = -abs(st.nstop[ch]) * scale
        d.smax = abs(st.pstop[ch]) * scale
        if (d.smin or d.smax) and d.kf == 0.0:
            state.warn(
                f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid} "
                f"({ref}, {chan_names[ch]} -> {name}): stop "
                f"{'angles' if rot else 'displacements'} are set but "
                f"{es_names[ch]}=0, and a /PROP/TYPE45 stop with "
                "zero elastic stiffness (Kfr/Kft) is simply violated — the "
                "joint will rotate/slide straight through it. Give the LS-DYNA "
                "card a non-zero elastic stiffness for the stop.")
        for fid, what in ((d.fct_k, "stiffness"), (d.fct_c, "damping"),
                          (d.fct_f, "friction-limit")):
            if fid and fid not in state.curves:
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid} "
                    f"({ref}, {chan_names[ch]} -> {name}): the {what} curve "
                    f"{fid} is not defined by any *DEFINE_CURVE — /PROP/TYPE45 "
                    "would reference a missing /FUNCT. Reference dropped.")
        d.fct_k = d.fct_k if d.fct_k in state.curves else 0
        d.fct_c = d.fct_c if d.fct_c in state.curves else 0
        d.fct_f = d.fct_f if d.fct_f in state.curves else 0
        out[name] = d

    # Anything the Type cannot hold.
    for ch in range(3):
        if ch in used.values():
            continue
        if not (st.lcid[ch] or st.dlcid[ch] or st.es[ch] or st.fm[ch]
                or st.nstop[ch] or st.pstop[ch]):
            continue
        free = ", ".join(JOINT_TYPE45_DOFS.get(jtype, ()))
        state.warn(
            f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid} ({ref}): "
            f"the {chan_names[ch]} channel carries data but /PROP/TYPE45 Type "
            f"{jtype} has no matching free DOF "
            f"(free DOFs: {free or 'none, every DOF is blocked'}), so that "
            "channel is DROPPED. LS-DYNA is describing a DOF the joint "
            "kinematics do not have.")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Section builder
# ─────────────────────────────────────────────────────────────────────────────

def _make_joints(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """*CONSTRAINED_JOINT_<KIND> -> /PROP/TYPE45 + /PART + /SPRING (+ /SKEW/FIX).

    One property PER JOINT, not one per joint KIND. dyna2rad shares a single
    /PROP/TYPE45 across every joint of a kind in the model, which silently
    throws away the RPS of every joint after the first and makes per-joint stops
    impossible; the properties are tiny, so there is no reason to.
    """
    joints = state.constrained_joints
    if not joints:
        return []

    stiff = _match_joint_stiffness(state)
    lines: List[str] = [
        "#-  JOINTS (*CONSTRAINED_JOINT_* -> /PROP/TYPE45 (KJOINT2) + /SPRING):",
        HDR]
    emitted = False
    th_elems: List[int] = []

    for idx, jnt in enumerate(joints):
        ref = f"jid={jnt.jid}" if jnt.jid else f"#{idx + 1}"
        tag = f"*{jnt.keyword or ('CONSTRAINED_JOINT_' + jnt.kind)} {ref}"
        jtype = JOINT_TYPE45[jnt.kind]
        nodes = jnt.spring_nodes()

        # dyna2rad's own guard: N1 and N2 must both resolve, or there is no
        # joint. It drops such a card silently; a missing constraint changes
        # the kinematics, so say so.
        if jnt.n1 <= 0 or jnt.n2 <= 0:
            state.warn(
                f"{tag}: N1={jnt.n1}/N2={jnt.n2} — both body-A and body-B nodes "
                "are required. Joint NOT converted; the two bodies are left "
                "unconstrained.")
            continue
        missing = [n for n in nodes if n not in state.nodes]
        if missing:
            state.warn(
                f"{tag}: node(s) {missing} are not defined by any *NODE card — "
                "joint NOT converted.")
            continue

        st = stiff.get(idx)
        frame = _joint_frame(state, jtype, nodes)
        skew_id = state.joint_skew_ids.get(idx, 0)
        if frame is None:
            skew_id = 0

        # Frame fallback and diagnostics. GET_SKEW45 needs NNOD_REQ nodes; below
        # that, and with Skew_ID1 = 0, the starter aborts with ERROR 936.
        need = JOINT_NNOD_REQ.get(jtype, 2)
        if skew_id == 0 and st is not None and st.cida:
            # No node geometry to build a frame from (a spherical joint's N1/N2
            # are coincident by design), but the stiffness card names the frame
            # its angles are measured in — which is exactly what Rx/Ry/Rz should
            # be about. Reuse the converted /SKEW/FIX/<cid> directly.
            if _coord_axes(state, st.cida) is not None:
                skew_id = st.cida
                state.warn(
                    f"{tag}: no joint frame is derivable from the node geometry, "
                    f"so Skew_ID1 = the converted /SKEW of CIDA={st.cida} — the "
                    "coordinate system the LS-DYNA stiffness angles are measured "
                    "in. Verify that this is the intended joint frame.")
        if skew_id == 0 and len(nodes) < need:
            state.warn(
                f"{tag}: /PROP/TYPE45 Type {jtype} needs {need} spring nodes and "
                f"the card supplies {len(nodes)} (N3/N4/N5 missing or zero), and "
                "no local frame could be built to stand in for them. The "
                "OpenRadioss starter will reject this joint with ERROR 936 "
                "(SPRING ID / KJOINT TYPE). Fill in the missing node(s).")
        elif skew_id == 0 and jtype not in (1, 8):
            state.warn(
                f"{tag}: the joint axis is degenerate — spring nodes {nodes} are "
                "coincident or colinear, so no local frame could be computed. "
                "The starter will fall back to its own construction and may "
                "abort with ERROR 935 (NODE 1 AND NODE 3 ARE COINCIDENT) or "
                "ERROR 1009 (colinear frame vectors).")

        # Which Euler / translation channel of the stiffness card drives the
        # single free axis of a revolute / cylindrical / translational joint.
        axis_index = 0
        if st is not None and jtype in (2, 3, 6):
            axis_index = _axis_channel(state, tag, st, frame)

        dofs = None
        if st is not None:
            dofs = _build_dofs(state, ref, jtype, st, axis_index)
            if all(d.is_empty() for d in dofs.values()):
                dofs = None
            if st.option == "GENERALIZED" and jtype in (1, 4, 5):
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED JSID={st.jsid} "
                    f"({ref}): LS-DYNA's phi/theta/psi are z-y-z EULER angles in "
                    f"CIDA={st.cida}, not the Radioss local Rx/Ry/Rz of a "
                    f"Type-{jtype} joint. They were mapped phi->Rx, theta->Ry, "
                    "psi->Rz, which is exact only for a single-free-rotation "
                    "joint. Check the stop angles and moment curves against a "
                    "single-joint reference run.")
            if st.cidb and st.cidb != st.cida:
                state.warn(
                    f"*CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid} "
                    f"({ref}): CIDA={st.cida} and CIDB={st.cidb} differ, so the "
                    "LS-DYNA joint starts at a non-zero angle/offset. "
                    "/PROP/TYPE45 can only express that through Skew_ID2, which "
                    "k2rad does not write (two skews that are not both within "
                    "0.98 of the joint axis are starter ERROR 3076). The joint "
                    "therefore starts at zero — shift the stop values and curve "
                    "abscissae if the initial offset matters.")

        scf = _scale_factor(state, tag, jnt, st)
        prop_id = state.next_id()
        part_id = state.next_part_id()
        elem_id = state.next_id()
        label = jnt.title or f"CONSTRAINED_JOINT_{jnt.kind}"

        if skew_id and frame is not None:
            origin, _x, y, z = frame
            lines.append(f"#-- {tag}: local frame from nodes {nodes}")
            lines += _emit_skew_fix(skew_id, f"SKEW_JOINT_{skew_id}",
                                    origin, y, z)
        lines += _emit_prop_type45(prop_id, f"{label} (KJOINT2 Type {jtype})",
                                   jtype, scf, skew_id, 0, dofs)
        ncol = len(nodes)
        lines += [
            f"/PART/{part_id}",
            label[:100],
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{part_id}",
            "# sprg_ID" + "".join(f"  node_ID{i}" for i in range(1, ncol + 1)),
            _i(elem_id) + "".join(_i(n) for n in nodes),
            HDR,
        ]
        th_elems.append(elem_id)
        emitted = True
        _warn_dropped_options(state, tag, jnt)
        _warn_rigid_attachment(state, tag, nodes, rigid_nodes)

    lines += _make_joint_th(state, th_elems)
    return lines if emitted else []


def _axis_channel(state: ConversionState, tag: str, st: JointStiffness,
                  frame) -> int:
    """Which CIDA axis (0/1/2) the joint axis is aligned with — i.e. which of
    phi/theta/psi (or x/y/z) drives the joint's single free DOF.

    Falls back to channel 0 with a loud warning when CIDA is unusable or no axis
    comes within |cos| > 0.99. dyna2rad leaves that branch's warning commented
    out and writes nothing, which silently loses the whole stiffness definition.
    """
    if frame is None:
        return 0
    axes = _coord_axes(state, st.cida)
    if axes is None:
        state.warn(
            f"{tag}: *CONSTRAINED_JOINT_STIFFNESS_{st.option} JSID={st.jsid} "
            f"names CIDA={st.cida}, which is not a converted "
            "*DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR. The first channel "
            f"({'phi' if st.option == 'GENERALIZED' else 'x'}) was assumed to "
            "be the joint axis — verify it.")
        return 0
    jx = frame[1]
    for i, a in enumerate(axes):
        if abs(_dot(a, jx)) > _AXIS_MATCH_COS:
            return i
    state.warn(
        f"{tag}: no axis of CIDA={st.cida} lies within {_AXIS_MATCH_COS} of the "
        f"joint axis {tuple(round(v, 6) for v in jx)}, so which of "
        f"{'phi/theta/psi' if st.option == 'GENERALIZED' else 'x/y/z'} drives "
        "the free DOF is ambiguous. The first channel was used — check that the "
        "LS-DYNA coordinate system really is the joint's frame.")
    return 0


def _scale_factor(state: ConversionState, tag: str, jnt: ConstrainedJoint,
                  st: Optional[JointStiffness]) -> float:
    """LS-DYNA RPS -> /PROP/TYPE45 ScF, dyna2rad's rule: RPS when positive, else
    0.01 (joints.cxx:1614-1617 and the six identical branches).

    These are NOT the same quantity. LS-DYNA's RPS is a dimensionless relative
    penalty-stiffness multiplier; Radioss's ScF is a length^2-dimensioned floor
    inside ``KR = Kn * MAX(ScF, LEN2)`` (rini45.F:283) where LEN2 is the squared
    joint length in the joint frame. Carrying the number across is what dyna2rad
    does and is the only defensible mapping, but a tuned RPS does not transfer.
    """
    rps = jnt.rps
    if st is not None and st.rps > 0.0:
        rps = st.rps
    if rps > 0.0:
        if rps != 1.0:
            state.warn(
                f"{tag}: RPS={rps:g} was carried into /PROP/TYPE45 ScF. RPS is a "
                "dimensionless relative penalty multiplier in LS-DYNA; ScF is a "
                "length-squared floor in Kn*MAX(ScF, L^2) with Kn auto-computed "
                "from the time step. The number transfers, the meaning does not "
                "— check the joint's constraint violation in the run.")
        return rps
    state.warn(
        f"{tag}: RPS={jnt.rps:g} is not positive. A negative RPS means -RPS is a "
        "load-curve id for the penalty scale (spherical/revolute/cylindrical "
        "only), which /PROP/TYPE45 cannot express — ScF was set to 0.01, "
        "dyna2rad's fallback, so the blocking stiffness comes purely from the "
        "time step.")
    return 0.01


def _warn_dropped_options(state: ConversionState, tag: str,
                          jnt: ConstrainedJoint) -> None:
    """Everything on the LS-DYNA card that /PROP/TYPE45 has no home for."""
    if jnt.damp != 1.0:
        state.warn(
            f"{tag}: DAMP={jnt.damp:g} was DROPPED. LS-DYNA's DAMP scales an "
            "internally computed joint damping; Radioss's Cr is an absolute "
            "critical-damping ratio in [0,1] whose blank value the starter "
            "replaces with 0.05. Writing DAMP into Cr would silently change the "
            "damping by more than an order of magnitude, so Cr is left at the "
            "0.05 default. dyna2rad never reads DAMP at all.")
    if jnt.has_local:
        state.warn(
            f"{tag}: the _LOCAL option (RAID/LST) was DROPPED. It only rotates "
            "the REPORTED joint force resultants into a rigid body's or "
            "accelerometer's frame — it does not change the joint kinematics — "
            "and /TH/SPRING reports in the global frame. Results are correct; "
            "the force components are in global axes. dyna2rad parses the card "
            "and never reads it either.")
    if jnt.has_failure:
        state.warn(
            f"{tag}: the _FAILURE option (CID/TFAIL/COUPL + NXX/NYY/NZZ/MXX/MYY/"
            "MZZ) was DROPPED — /PROP/TYPE45 has no failure criterion, so this "
            "joint NEVER FAILS. If the LS-DYNA model relies on the joint "
            "breaking, the converted run will be stiffer than the original. "
            "dyna2rad drops it silently.")
    if jnt.kind == "TRANSLATIONAL" and (jnt.n5 > 0 or jnt.n6 > 0):
        state.warn(
            f"{tag}: N5={jnt.n5}/N6={jnt.n6} were DROPPED. On a translational "
            "joint they fix the ROLL about the sliding axis; the /SPRING carries "
            "N1/N2/N3 only, so the starter picks the transverse axes by its own "
            "largest-component rule instead. The kinematics are unaffected — "
            "Type 6 leaves only Tx free and blocks all rotation either way — but "
            "the joint's local y/z, and therefore the sign convention of the "
            "reported transverse forces, will not match LS-DYNA's.")


def _warn_rigid_attachment(state: ConversionState, tag: str,
                           nodes: List[int], rigid_nodes: Set[int]) -> None:
    """A joint constrains two RIGID BODIES. Its nodes must already be secondary
    nodes of an /RBODY (from *MAT_RIGID, *PART_INERTIA or *CONSTRAINED_NODAL_
    RIGID_BODY); on a free or deformable node the joint just ties two points of
    a mesh together and the constraint means something else entirely.

    k2rad does not attach them silently: adding a node to a rigid body changes
    the model's inertia and its constrained set, which is the user's call. This
    is the check dyna2rad does not make — it assumes the attachment happened
    elsewhere and issues nothing when it did not.
    """
    loose = [n for n in nodes if n not in rigid_nodes]
    if not loose:
        return
    state.warn(
        f"{tag}: node(s) {loose} belong to no /RBODY. An LS-DYNA joint acts "
        "between two RIGID bodies (N1/N3/N5 on body A, N2/N4/N6 on body B); on "
        "nodes that are not rigid-body secondary nodes the /PROP/TYPE45 spring "
        "constrains bare mesh points instead of the bodies. Attach them with "
        "*CONSTRAINED_EXTRA_NODES to the rigid part, or confirm the joint is "
        "meant to act on the deformable mesh.")


def _make_joint_th(state: ConversionState, elems: List[int]) -> List[str]:
    """*DATABASE_JNTFORC -> /TH/SPRING over the joint springs.

    JNTFORC is the joint-force database; the joints are /SPRING elements here,
    so /TH/SPRING is where their forces and moments land in the T01. The group
    id comes from state.next_id(): /TH ids are ONE namespace across every /TH
    type, and a hard-coded id already cost this converter an ERROR 79 / no
    restart file once (PR #83).
    """
    if not elems or not state.db_jntforc_dt:
        return []
    tid = state.next_id()
    lines = [
        f"#-- *DATABASE_JNTFORC -> joint spring forces (dt={state.db_jntforc_dt:g})",
        f"/TH/SPRING/{tid}",
        f"TH_JOINTS_{tid}",
        "#     var1      var2",
        "DEF       ",
    ]
    lines += [_i(e) for e in elems]
    lines.append(HDR)
    return lines
