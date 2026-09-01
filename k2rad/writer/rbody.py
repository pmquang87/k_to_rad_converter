"""Starter rigid bodies: /RBODY, constrained nodal rigid bodies, merges, probe rigid body."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple
from ..state import (
    CnrbSpcBc, ConversionState, NodeData, PartData, RigidInertia,
)
from .common import HDR, _emit_grnod_node, _f, _i, _vcross, _vnorm
from .mesh import _emit_skew_fix

__all__ = [
    "_make_rbodies",
    "_resolve_rigid_body_merges",
    "_con1_to_tra",
    "_con2_to_rot",
    "_resolve_cnrb_spc",
    "_make_cnrb_rbodies",
    "_make_probe_rbody",
    "_inertia_element_nodes",
    "_resolve_inertia",
    "ICOG_DEFINED_PROPERTIES",
]


# ─────────────────────────────────────────────────────────────────────────────
# _INERTIA: the *PART_INERTIA / *CONSTRAINED_NODAL_RIGID_BODY_INERTIA transfer
# ─────────────────────────────────────────────────────────────────────────────

#: /RBODY ICoG for a body whose mass properties are DEFINED, not computed.
#:
#: 4 is the only value that reproduces LS-DYNA's `_INERTIA` semantics. Starter
#: ground truth, ``inirby.F:266-282`` + the gate at ``:322``:
#:
#:   ELSEIF(ICDG==4)THEN
#:     DO J=1,3 ; XG(J)=X(J,M) ; ENDDO      ! COG = the main node, unmoved
#:     MASRB=MS(M)                          ! secondary mesh mass IGNORED
#:   ENDIF
#:   ...
#:   IF(ICDG<=3)THEN                        ! <- 4 skips ALL of the transport
#:
#: i.e. the mesh's mass and inertia are not counted, the main node is not moved,
#: and the user's tensor is not parallel-axis transported. Every other value ADDS
#: the mesh contribution on top of the user's numbers (double counting), and
#: ICoG=1/2 additionally MOVE the centre of gravity away from the XC/YC/ZC the
#: card specifies. Measured on five otherwise-identical bodies (probe ``pinE``,
#: user Mass 1e-6, mesh mass 7.86e-7, main node at x = n*100 + 0, secondaries
#: centred 20 further out):
#:
#:   ICoG | starter NEW X | starter NEW MASS
#:      1 |      108.8018 | 1.786e-6   (combined centroid; mesh mass added)
#:      2 |      220.0000 | 1.786e-6   (secondary centroid; main node MOVED)
#:      3 |      300.0000 | 1.786e-6   (main node kept; mesh mass still added)
#:      4 |      400.0000 | 1.000e-6   (main node kept; mesh mass DROPPED)
#:  blank |      508.8018 | 1.786e-6   (= 1, and Ispher echoes 2)
#:
#: Residual to respect: ``inirby.F:146,166-169`` ALWAYS adds the main node's own
#: ``MS(M)`` and ``IN(M)``, whatever ICoG is. So the main node must be
#: element-free and must carry no /ADMAS, or the body gains mass the card never
#: asked for. Every main node this module writes for an `_INERTIA` body is a
#: synthesized free node (or an explicitly element-free NODEID).
ICOG_DEFINED_PROPERTIES = 4


def _inertia_element_nodes(state: ConversionState) -> Set[int]:
    """Every node that belongs to at least one element.

    Built on demand only — an `_INERTIA` main node has to be element-free
    (ICOG_DEFINED_PROPERTIES), and this is the test. Scanning the element tables
    costs O(elements), which on a 1M-element deck is not free, so callers gate it
    on ``state.part_inertias`` / a CNRB inertia actually being present.
    """
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    # Thick shells are /BRICK in the emitted deck and carry real stiffness, so
    # their nodes are "attached to an element" exactly like a hex's. The
    # container is empty on every deck without *ELEMENT_TSHELL.
    for e in state.tshell_elems:
        elem_nodes.update(e.nodes)
    # An SPH particle carries mass and kernel stiffness, so its node is
    # "attached to an element" exactly like a hex's — and on a *PART_INERTIA
    # part it is one of the nodes the fabricated CoG/inertia has to cover.
    for c in state.sph_elems:
        elem_nodes.update(c.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2, e.n3))
    # A 1D SEATBELT node carries the belt's lumped mass — rinit3.F:464,474
    # ``mass = Area * max(L0,LMIN) * rho``, split over the two spring nodes —
    # so it is "attached to an element" in exactly the sense this test asks
    # about: treating it as element-free would let an ``_INERTIA`` body take it
    # as its main node and gain the webbing's mass on top of the mass the card
    # states. Same argument the SPH arm above is here for. (2D belt elements
    # are in state.shell_elems already.)
    for e in state.seatbelt_elems:
        if not e.is_2d:
            elem_nodes.update((e.n1, e.n2))
    return elem_nodes


def _inertia_frame(state: ConversionState, label: str,
                   inr: RigidInertia) -> Tuple[int, List[str]]:
    """``IRCS`` → the /RBODY ``Skew_ID`` that expresses the tensor's frame.

    Returns ``(skew_id, extra_lines)``; ``extra_lines`` holds a synthesized
    /SKEW/FIX when card 6 gives two vectors instead of a ``CID``.

    ``Skew_ID`` IS the exact route for ``IRCS = 1``. ``inirby.F:161-164`` applies
    ``CALL CHBAS(SKEW(1,NOSKEW),RBY(1,NRB))`` to the packed 3x3 before any mesh
    contribution, and ``chbas.F`` computes ``M_out = A*M_in*A^T`` where ``A`` is
    filled column-major from ``SKEW`` — i.e. ``A = [X'|Y'|Z']`` = R (local→global),
    giving ``J_global = R*J_local*R^T``. That is LS-DYNA's ``IRCS=1`` definition
    exactly. Confirmed by running a +90°-about-Z skew on ``J = (100,200,250 /
    10,0,0)``: the starter echoed ``200 100 250 / -10 0 0`` — Ixx<->Iyy swapped and
    Ixy negated, which is what ``R J R^T`` gives.

    ``IRCS = 0`` binds NOTHING. dyna2rad's CNRB path binds card-1 ``CID`` as
    ``Skew_ID`` when ``IRCS == 0`` (``convertrigids.cxx:126-127``), which rotates a
    tensor LS-DYNA defines in the GLOBAL frame — measured: a global
    ``4.11 5.22 6.33`` came out as ``5.22 6.33 4.11``. k2rad does not reproduce
    that; card-1 CID stays what LS-DYNA says it is (the body's output/local system,
    consumed by _local_body_basis).
    """
    if inr.ircs != 1:
        return 0, []
    if inr.cid:
        # A *DEFINE_COORDINATE_* id. k2rad emits /SKEW/FIX under the cid verbatim,
        # so the reference is 1:1 — but a dangling id is starter ERROR 137 (WRONG
        # SKEW SYSTEM), a hard stop, so it is checked here instead.
        if (inr.cid in state.coord_sys or inr.cid in state.coord_nodes
                or inr.cid in state.coord_vectors):
            return inr.cid, []
        state.warn(
            f"{label}: IRCS=1 names local system CID={inr.cid} on the inertia "
            "card, but no *DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR with that id "
            "is in the deck. Binding it as /RBODY Skew_ID would be starter "
            "ERROR 137 (WRONG SKEW SYSTEM), so the tensor is written in the "
            "GLOBAL frame instead — it is WRONG by that rotation. Add the "
            "*DEFINE_COORDINATE_* card, or restate IXX..IZZ globally with IRCS=0.")
        return 0, []
    # Card 6's two vectors: local x-axis (XL,YL,ZL) and an in-plane vector
    # (XLIP,YLIP,ZLIP), origin at (0,0,0) — *PART Remark 4: "The reference
    # coordinate system defines the orientation of the axes, not the origin", and
    # /RBODY never reads SKEW(10:12) anyway.
    xl = (inr.xl, inr.yl, inr.zl)
    vip = (inr.xlip, inr.ylip, inr.zlip)
    ex = _vnorm(xl)
    ez = _vnorm(_vcross(xl, vip)) if ex is not None else None
    if ex is None or ez is None:
        # Two distinct source-deck defects reach this point, and the remedy
        # differs: a card 6 that is simply NOT THERE (the block ended after card
        # 5, so ``_read_rigid_inertia`` never set has_local_card) versus a card 6
        # that is there and states two zero or parallel vectors.
        if not inr.has_local_card:
            state.warn(
                f"{label}: IRCS=1 but the block ENDS before card 6, so the local "
                "system it promises was never read. Card 6 is mandatory with "
                "IRCS=1 ('optional unless IRCS = 1', Card Summary Vol I R17 "
                "p.37-4). The tensor is written in the GLOBAL frame, so it is "
                "WRONG by whatever rotation was intended — add the card (XL YL ZL "
                "XLIP YLIP ZLIP CID), or restate IXX..IZZ globally with IRCS=0.")
        else:
            state.warn(
                f"{label}: IRCS=1 but the inertia card's local system is degenerate "
                f"(XL={xl}, XLIP={vip} are zero or parallel, and CID is blank). The "
                "tensor is written in the GLOBAL frame, so it is WRONG by whatever "
                "rotation was intended. Give two non-parallel vectors, or name a "
                "*DEFINE_COORDINATE_* in the card's CID field.")
        return 0, []
    ey = _vcross(ez, ex)
    # /SKEW/FIX's two vector cards are the local Y' and Z' (NOT X' and Y'); the
    # starter rebuilds X' = Y' x Z'. See _emit_skew_fix.
    skew_id = state.reserve_skew_id(state.next_id())
    return skew_id, _emit_skew_fix(
        skew_id, f"SKEW_INERTIA_{skew_id}", (0.0, 0.0, 0.0), ey, ez)


def _resolve_inertia(state: ConversionState, label: str, inr: RigidInertia):
    """``(mass, (Jxx, Jyy, Jzz, Jxy, Jyz, Jxz), skew_id, extra_lines)`` or None.

    None means "do not override" — the /RBODY keeps its mesh-derived mass and
    inertia, which is what LS-DYNA itself does without the `_INERTIA` option.
    That is the answer whenever the card set cannot produce a body the starter
    will accept, because ICOG_DEFINED_PROPERTIES throws the mesh contribution
    away and there is then nothing to fall back on:

      * ``TM <= 0`` → total mass 0 → ``ERROR 679`` (``inirby.F:273``);
      * ANY diagonal ``IXX``/``IYY``/``IZZ`` zero → ``ERROR 274``, min principal
        inertia <= 0 (``inirby.F:824``).

    The diagonal is checked TERM BY TERM, not as "all three blank". A partial
    tensor is the more plausible defect of the two — the CNRB Card 4 Default row
    in the manual reads ``none 0 0 none 0 0``, so a deck can leave ``IZZ`` empty
    and look complete — and it is just as fatal: with ICoG=4 the parallel-axis
    block is skipped (``inirby.F:322``, ``IF(ICDG<=3)``) and the main node is a
    fresh free node (``IN(M)=0``), so nothing ever fills the zero in. Measured
    before this guard was per-term: ``TM=7.25 IXX=20 IYY=IZZ=0`` emitted /RBODY
    ICoG=4 with ``Jxx=20 Jyy=0 Jzz=0`` and ZERO warnings.

    Both are source-deck defects by *PART Remark 3 ("all mass and inertia
    properties of the body must be specified.  There are no default values"), so
    they are warned in full rather than silently patched with an epsilon.

    The tensor is copied VERBATIM — only the field ORDER changes. See
    ``state.RigidInertia`` for the two quotes that settle the sign.
    """
    zero_diag = [n for n, v in (("IXX", inr.ixx), ("IYY", inr.iyy),
                                ("IZZ", inr.izz)) if not v]
    if inr.tm <= 0.0 or zero_diag:
        missing = []
        if inr.tm <= 0.0:
            missing.append(
                f"TM={inr.tm:g} (starter ERROR 679, total rigid-body mass <= 1e-30)")
        if zero_diag:
            missing.append(
                f"{'='.join(zero_diag)}=0 (starter ERROR 274, min principal "
                "inertia <= 0)")
        state.warn(
            f"{label}: the _INERTIA cards are INCOMPLETE — {'; '.join(missing)}. "
            "*PART Remark 3 requires all of them ('There are no default "
            "values'), and /RBODY ICoG=4 — the only flag that reproduces "
            "'defined rather than calculated from the finite element mesh' — "
            "IGNORES the mesh's own mass and inertia, so the body would be "
            "unrunnable. The mass-property override is DROPPED and the rigid "
            "body keeps its MESH-derived mass and inertia (what LS-DYNA does "
            "without the option). Fill in TM and IXX/IYY/IZZ.")
        return None
    skew_id, extra = _inertia_frame(state, label, inr)
    # LS-DYNA card 4 order: IXX IXY IXZ IYY IYZ IZZ.
    # Radioss line 3: Jxx Jyy Jzz.  Line 4: Jxy Jyz Jxz.  A pure permutation.
    return (inr.tm,
            (inr.ixx, inr.iyy, inr.izz, inr.ixy, inr.iyz, inr.ixz),
            skew_id, extra)


def _inertia_main_node(state: ConversionState, label: str, inr: RigidInertia,
                       elem_nodes: Set[int], secondary: Set[int]) -> int:
    """The /RBODY main node for an `_INERTIA` body: the specified centre of mass.

    ``NODEID`` beats ``XC/YC/ZC`` — "If nodal point NODEID is defined, XC, YC, and
    ZC are ignored, and the coordinates of NODEID are taken as the center of mass"
    (Vol I R17 p.37-7). The node is REUSED only when it is element-free and not a
    secondary of this body; otherwise a free node is synthesized at its
    coordinates, because ICoG=4 still adds the main node's own ``MS(M)``/``IN(M)``
    (``inirby.F:146,166-169``) and a meshed main node is also WARNING 448 / ERROR
    1066 under AMS.

    dyna2rad loses this position outright: with ``NODEID != 0`` on a
    `*PART_INERTIA` the starter reports ``PRIMARY NODE`` at (0,0,0) and NODEID's
    coordinates *and* XC/YC/ZC are both discarded (reproduced on three separate
    decks), and its ``NODEID == 0`` fallback calls ``GetCentroid`` through an
    invalid handle so the node lands on the global ORIGIN — an error that scales
    with the body's distance from it (measured: a body at x ~ 100 gained
    ``NEW INERTIA yy = 5.68e11``).
    """
    if inr.nodeid > 0:
        nd = state.nodes.get(inr.nodeid)
        if nd is None:
            state.warn(
                f"{label}: the inertia card's NODEID={inr.nodeid} is not a *NODE "
                f"in the deck; the centre of mass falls back to XC/YC/ZC = "
                f"({inr.xc:g}, {inr.yc:g}, {inr.zc:g}).")
        elif inr.nodeid in elem_nodes or inr.nodeid in secondary:
            where = ("attached to elements" if inr.nodeid in elem_nodes
                     else "a secondary node of this rigid body")
            nid = state.next_node_id()
            state.nodes[nid] = NodeData(nd.x, nd.y, nd.z)
            state.warn(
                f"{label}: the inertia card's NODEID={inr.nodeid} is {where}, so "
                f"the /RBODY main node is a synthesized free node {nid} at the "
                "SAME coordinates. ICoG=4 still adds the main node's own nodal "
                "mass and rotary inertia (inirby.F:146,166-169), so reusing a "
                "meshed node would add mass TM never accounted for — and a main "
                "node on an element is WARNING 448, or ERROR 1066 with --ams.")
            return nid
        else:
            return inr.nodeid
    nid = state.next_node_id()
    state.nodes[nid] = NodeData(inr.xc, inr.yc, inr.zc)
    return nid


#: Zero inertia — the mesh-derived body's two /RBODY inertia cards.
_J_ZERO: Tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _inertia_lines(j: Tuple[float, ...]) -> List[str]:
    """The two /RBODY inertia cards. Order: ``Jxx Jyy Jzz`` / ``Jxy Jyz Jxz``.

    The second card's order is the one that is easy to get wrong — it is NOT
    ``Jxy Jxz Jyz``. Pinned empirically: a body fed ``Jxx=100 Jyy=200 Jzz=250 /
    Jxy=10 Jyz=0 Jxz=0`` echoed ``ADDED INERTIA 100.0 200.0 250.0 10.00 0.000
    0.000``, and the starter prints that row as ``Mass, Jxx, Jyy, Jzz, Jxy, Jyz,
    Jxz`` in reader-storage order (``hm_read_rbody.F:553``).
    """
    return [
        "#                Jxx                 Jyy                 Jzz",
        f"{_f(j[0])}{_f(j[1])}{_f(j[2])}",
        "#                Jxy                 Jyz                 Jxz",
        f"{_f(j[3])}{_f(j[4])}{_f(j[5])}",
    ]


def _warn_unapplied_part_inertias(state: ConversionState, applied: Set[int],
                                  rigid_mids: Set[int],
                                  merge_root: Dict[int, int],
                                  rbody_info: Dict) -> None:
    """Report every `*PART_INERTIA` whose properties never reached an `/RBODY`.

    LS-DYNA is explicit that the option "applies to rigid bodies (see *MAT_RIGID)
    only" (Vol I R17 p.37-2), so a deformable `*PART_INERTIA` is invalid input —
    but dyna2rad drops it SILENTLY: its part selection is
    ``FilterValue(sdiIdentifier("MID"), <*MAT_RIGID ids>)``
    (``convertrigids.cxx:177-179``), so a non-rigid MID yields no /RBODY, no mass
    and no inertia with no diagnostic at all. A lost ``TM`` changes the model's
    total mass, so it is said out loud, per part, with the number.

    Called from EVERY return path of _make_rbodies, including the two early ones —
    a deck with no `*MAT_RIGID` at all is exactly the case where the whole
    override vanishes.
    """
    for pid in sorted(state.part_inertias):
        if pid in applied:
            continue
        part = state.parts.get(pid)
        if part is None:
            reason = "no *PART card defines that id"
        elif part.mid not in rigid_mids:
            reason = (f"its material {part.mid} is not a *MAT_RIGID, and "
                      "*PART_INERTIA 'applies to rigid bodies (see *MAT_RIGID) "
                      "only'")
        elif pid in merge_root:
            reason = ("*CONSTRAINED_RIGID_BODIES merged the part into rigid body "
                      f"{merge_root[pid]}, whose own Mass/inertia would have to be "
                      "the merged TOTAL about the merged centre of mass — not "
                      "something k2rad can compute from the two cards")
        elif pid in rbody_info:
            continue                  # refused by _resolve_inertia, warned there
        else:
            reason = "the part has no elements, so no /RBODY was emitted for it"
        state.warn(
            f"*PART_INERTIA {pid}: the mass/inertia cards are DROPPED because "
            f"{reason}. The converted model's total mass and rotary inertia are "
            f"lower than the source deck's by TM={state.part_inertias[pid].tm:g}. "
            "Move the properties onto the rigid body that survives, or make the "
            "part rigid.")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: rigid bodies
# ─────────────────────────────────────────────────────────────────────────────

def _make_rbodies(state: ConversionState) -> Tuple[List[str], Set[int], Dict]:
    """Return (rad_lines, rigid_node_set, rbody_info_dict)."""
    lines: List[str] = []
    rigid_nodes: Set[int] = set()
    rbody_info: Dict = {}

    if not state.mat_rigid:
        for pid in sorted(state.extra_rigid_nodes):
            state.warn(
                f"*CONSTRAINED_EXTRA_NODES pid={pid}: part is not a *MAT_RIGID "
                "part — extra nodes not attached (deformable-part extra nodes "
                "have no /RBODY to join).")
        _warn_unapplied_part_inertias(state, set(), set(), {}, rbody_info)
        return lines, rigid_nodes, rbody_info

    rigid_mids: Set[int] = set(state.mat_rigid.keys())

    nodes_by_pid: Dict[int, List[int]] = defaultdict(list)
    for e in state.shell_elems:
        if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for e in state.solid_elems:
        if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for e in state.tshell_elems:              # /BRICK too — see above
        if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for c in state.sph_elems:                 # SPH nodes join like any other
        if state.parts.get(c.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[c.pid].extend(c.nodes)
    for e in state.beam_elems:
        if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[e.pid].extend([e.n1, e.n2])

    # *CONSTRAINED_EXTRA_NODES_NODE/_SET: extra nodes rigidly attached to the
    # part join its /RBODY secondary-node group (they also let an element-free
    # *MAT_RIGID part form a rigid body at all).
    for pid, extra in state.extra_rigid_nodes.items():
        part = state.parts.get(pid)
        if part is None or part.mid not in rigid_mids:
            state.warn(
                f"*CONSTRAINED_EXTRA_NODES pid={pid}: part is not a *MAT_RIGID "
                "part — extra nodes not attached (deformable-part extra nodes "
                "have no /RBODY to join).")
            continue
        nodes_by_pid[pid].extend(extra)

    # *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL: the three synthesized nodes that
    # carry the body's co-rotating /SKEW/MOV triad must be rigid secondaries, or
    # the triad does not turn with the body. They are element-free, so they add
    # no mass and no inertia. Silent by design here — the prepass that created
    # them (_synthesize_local_motion_frames) already warned about the whole
    # construction; a part that is not rigid never gets nodes in the first place
    # (the motion needs an /RBODY to drive at all).
    for pid, helpers in state.local_frame_nodes.items():
        if pid in nodes_by_pid:
            nodes_by_pid[pid].extend(helpers)

    # *CONSTRAINED_RIGID_BODIES: fold each slave rigid part's nodes into its
    # master so only the master emits an /RBODY. Chains (A<-B, B<-C) resolve
    # transitively via union-find with the master as the representative.
    merge_root = _resolve_rigid_body_merges(state, rigid_mids)
    for slave, master in sorted(merge_root.items()):
        moved = nodes_by_pid.pop(slave, [])
        if moved:
            nodes_by_pid[master].extend(moved)

    if not nodes_by_pid:
        for mid in rigid_mids:
            state.warn(f"*MAT_RIGID mid={mid}: no elements found; /RBODY not emitted")
        _warn_unapplied_part_inertias(state, set(), rigid_mids, merge_root,
                                      rbody_info)
        return lines, rigid_nodes, rbody_info

    lines.append("#-  RIGID BODIES:")
    lines.append(HDR)

    # --rigid-cog-master: synthesize element-free masters (new node ids above the
    # current maximum, coordinates at the part's nodal centroid).
    _next_free = (max(state.nodes) + 1 if state.nodes else 90000001)

    # *PART_INERTIA: which rigid parts actually received the override, so the
    # sweep at the end of this function can name the ones that did not (and why).
    inertia_applied: Set[int] = set()
    elem_nodes: Set[int] = (_inertia_element_nodes(state)
                            if state.part_inertias else set())

    for pid, all_nodes in sorted(nodes_by_pid.items()):
        part = state.parts.get(pid)
        if not part: continue
        mat = state.mat_rigid.get(part.mid)
        if not mat: continue
        unique_nodes = sorted(set(n for n in all_nodes if n > 0))
        if not unique_nodes: continue

        # *PART_INERTIA cards 3-6. ``inr`` is the parsed record (used for the
        # card-5 velocities even when the mass override is refused); ``props`` is
        # the accepted (mass, tensor, skew) triple or None.
        inr = state.part_inertias.get(pid)
        props = _resolve_inertia(
            state, f"*PART_INERTIA {pid}", inr) if inr is not None else None
        icog = 0
        skew_id = 0
        j_vals = _J_ZERO
        inertia_extra: List[str] = []
        if props is not None:
            inertia_mass, j_vals, skew_id, inertia_extra = props
            icog = ICOG_DEFINED_PROPERTIES
            inertia_applied.add(pid)

        if props is not None:
            # The main node IS the specified centre of mass, and must be
            # element-free — see _inertia_main_node / ICOG_DEFINED_PROPERTIES.
            # This overrides --no-rigid-cog-master: a mesh-node main would add its
            # own nodal mass on top of TM and sit at the wrong point.
            ind_node = _inertia_main_node(
                state, f"*PART_INERTIA {pid}", inr, elem_nodes,
                set(unique_nodes))
            rigid_nodes.add(ind_node)
            if not state.options.rigid_cog_master:
                state.warn(
                    f"*PART_INERTIA {pid}: --no-rigid-cog-master is ignored for "
                    "this part. The /RBODY main node has to BE the centre of "
                    "mass the inertia card specifies (ICoG=4 does not move it), "
                    "and it has to be element-free so its own nodal mass is not "
                    f"added to TM — so main node {ind_node} was synthesized there "
                    "anyway.")
        elif state.options.rigid_cog_master:
            # Element-free master at the nodal centroid (the CNRB treatment):
            # a mesh-node master is an element corner (WARNING 448/1624) and is
            # relocated to the CoM at runtime, so its coordinates appear to
            # change in post-processing. A synthesized master keeps every mesh
            # node put; OpenRadioss still moves the master itself to the true
            # CoM (ICoG default), which is harmless for a free node.
            #
            # The centroid is taken over the MESH nodes only. The _LOCAL /SKEW/MOV
            # helper triad was folded into unique_nodes above (it has to be an
            # /RBODY secondary to co-rotate), and its three offsets are 0.1x the
            # body's span — averaging them in shifted the written master
            # coordinate by ~0.9% of the span. Inert at runtime (ICoG relocates
            # the master to the true CoM and the helpers are massless) but a
            # silently wrong pre-run coordinate, and wrong outright the moment
            # ICoG=2 "keep coordinates" is ever emitted.
            helpers = set(state.local_frame_nodes.get(pid, ()))
            pts = [state.nodes[n] for n in unique_nodes
                   if n in state.nodes and n not in helpers]
            # Skip anything already taken. The open-coded counter is only safe
            # while it is the ONLY allocator in the loop, and the _INERTIA branch
            # above now draws from state.next_node_id() as well — two allocators
            # sharing a range hand the same id out twice, and because state.nodes
            # is a dict the second write silently REPLACES the first node (a rigid
            # body's main node teleported onto another's). A no-op when no
            # *PART_INERTIA is present, so it shifts no existing deck.
            while _next_free in state.nodes:
                _next_free += 1
            ind_node = _next_free
            _next_free += 1
            if pts:
                k = len(pts)
                state.nodes[ind_node] = NodeData(sum(p.x for p in pts) / k,
                                                 sum(p.y for p in pts) / k,
                                                 sum(p.z for p in pts) / k)
            else:
                state.nodes[ind_node] = NodeData(0.0, 0.0, 0.0)
            rigid_nodes.add(ind_node)
            state.warn(
                f"*MAT_RIGID pid={pid}: /RBODY master is a synthesized "
                f"element-free node {ind_node} at the part's nodal centroid "
                "(default; mesh nodes keep their coordinates and loads/readouts "
                "on the rigid body now address this node — pass "
                "--no-rigid-cog-master to reuse the part's lowest-id mesh node).")
        else:
            ind_node = unique_nodes[0]
        grnod_id = state.next_grnod_id()
        ind_grnod_id = state.next_grnod_id()
        rigid_nodes.update(unique_nodes)
        rbody_info[pid] = {
            "ind_node": ind_node,
            "grnod_id": grnod_id,
            "ind_grnod_id": ind_grnod_id,
            "nodes": unique_nodes,
            # a whole *MAT_RIGID PART: consumers keyed on the part id (the
            # /GRAV group builder) may swap the part out for its main node
            "kind": "part",
        }

        # /RBODY format: 2 data cards (one per logical record).
        # The W7-style 4-card-with-comments format makes OpenRadioss read
        # grnd_ID as 0 (silently defaulting), giving NUMBER OF NODES = 0 →
        # malformed rigid body → engine segfault. Using the proper 10-field
        # single data line ensures grnd_ID is read correctly.
        # Card 3 (10 fields, 110 chars):
        #   node_ID(I10) sens_ID(I10) skew_ID(I10) Ispher(I10) Mass(F20)
        #   grnd_ID(I10) Ikrem(I10) ICoG(I10) surf_ID(I10) Ifail(I10)
        # Cards 4-5 (3 floats each): Jxx Jyy Jzz  /  Jxy Jyz Jxz
        #   (inertia MUST be two separate cards — see detailed note below)
        # The Mass field is ADDITIONAL mass added to the rigid body on top of
        # whatever is computed from element distribution + material density.
        # Sources combined:
        #   • *ELEMENT_MASS / *ELEMENT_MASS_NODE_SET on the rigid master node
        #   • *ELEMENT_MASS_PART (or _SET) with this part's pid → ADDMASS
        #   • *ELEMENT_MASS_PART with FINMASS → (FINMASS − inherent), where
        #     inherent is taken as 0 here because OpenRadioss computes inherent
        #     mass from rigid-body elements automatically (Mass field is purely
        #     additive). User should set FINMASS = desired total - inherent if
        #     they need exact total control.
        # This is the primary stabilization mechanism for implicit analyses
        # where the inherent rigid-body mass is too small.
        if state.options.rigid_cog_master:
            # The synthesized master carries no *ELEMENT_MASS of its own, and
            # _make_added_masses skips rigid-body nodes (their /ADMAS belongs to
            # the /RBODY) — so fold the *ELEMENT_MASS of ALL of the part's nodes
            # into the Mass field, not just the old master's.
            node_added = sum(state.added_node_masses.get(n, 0.0)
                             for n in unique_nodes)
        else:
            node_added = state.added_node_masses.get(ind_node, 0.0)
        part_add, part_fin = state.element_mass_parts.get(pid, (0.0, 0.0))
        if part_fin > 0:
            # FINMASS specified — treat as added mass (OpenRadioss /RBODY Mass
            # is additive; for exact final-mass control the user can compensate)
            part_mass_total = part_fin
        else:
            part_mass_total = part_add
        added_mass = node_added + part_mass_total
        # Gated on `props is None`: with an accepted *PART_INERTIA the Mass field
        # holds TM, not this sum, so saying it is "placed in /RBODY Mass field"
        # would be false — and the SUPERSEDED warning a few lines down already
        # names the same number with the right verb. Exactly one of the two fires.
        if added_mass > 0 and props is None:
            sources = []
            if node_added > 0:
                where = ("the part's nodes" if state.options.rigid_cog_master
                         else f"node {ind_node}")
                sources.append(f"*ELEMENT_MASS on {where}={node_added:.6G}")
            if part_add > 0:
                sources.append(f"*ELEMENT_MASS_PART ADDMASS={part_add:.6G}")
            if part_fin > 0:
                sources.append(f"*ELEMENT_MASS_PART FINMASS={part_fin:.6G}")
            state.warn(
                f"*MAT_RIGID pid={pid}: total added mass {added_mass:.6G} "
                f"({', '.join(sources)}) placed in /RBODY Mass field."
            )
        if props is not None:
            # TM is the TOTAL, not an increment: LS-DYNA's _INERTIA option defines
            # the properties "rather than calculated from the finite element mesh",
            # and Remark 2 says the deformable contributions to shared nodes
            # "should be considered part of the rigid body" — i.e. TM already
            # accounts for them. With ICoG=4 Radioss likewise takes Mass verbatim,
            # so anything added here would EXCEED TM.
            #
            # A NODEID main node outside the part is in NEITHER sum above
            # (``node_added`` runs over the part's own nodes), and its /ADMAS is
            # skipped too — _make_added_masses passes over rigid nodes, and
            # ind_node joined rigid_nodes above. Dropping it is right under
            # ICoG=4; going unmentioned is not, so it is folded into the number
            # this warning reports.
            superseded = added_mass
            if ind_node not in unique_nodes:
                superseded += state.added_node_masses.get(ind_node, 0.0)
            if superseded > 0:
                state.warn(
                    f"*PART_INERTIA {pid}: the {superseded:.6G} of "
                    "*ELEMENT_MASS/_PART mass on this part (and on its main node) "
                    f"is SUPERSEDED by TM={inertia_mass:.6G}, not added to it. TM "
                    "is the body's total (Remark 3: all mass properties must be "
                    "specified; Remark 2: contributions from deformable bodies to "
                    "shared nodes should be considered part of the rigid body), "
                    "and /RBODY ICoG=4 takes Mass verbatim — summing them would "
                    f"make the body {superseded:.6G} heavier than the deck states. "
                    "Fold the lumped mass into TM if it is meant to count.")
            added_mass = inertia_mass
        # /RBODY format (cfg radioss2021, selected for /BEGIN 2022) — FOUR cards
        # after title:
        #   Card 1 (9 fields):  node_ID sens_ID Skew_ID Ispher Mass(20)
        #                       grnd_ID Ikrem ICoG surf_ID          (= 100 cols)
        #   Card 2 (3 floats):  Jxx Jyy Jzz
        #   Card 3 (3 floats):  Jxy Jyz Jxz
        #   Card 4 (3 ints):    Ioptoff Iexpams [Ifail]
        # All four cards are REQUIRED. Two failure modes if any are missing:
        #   * inertia on one 6-value line -> reader stops after Jxx Jyy Jzz;
        #   * omitting card 4 -> reader stops after the inertia;
        # either way it hits the next keyword (/GRNOD/NODE) where it still
        # expects a card -> WARNING 100217 "card is missing" + a malformed rigid
        # body. Ioptoff is the rigid-body domain-decomposition flag for HMPP, so
        # the malformed body segfaults the SPMD (np>1) setup (MESSAGE ID 44) even
        # though np=1 tolerates it. Without *PART_INERTIA the inertia is 0
        # (OpenRadioss computes it from the node distribution) and ICoG/Skew_ID
        # stay 0 (= the reader's ICoG=1 default, global frame);
        # Ioptoff=Iexpams=Ifail=0 = defaults. Iexpams MUST stay 0/blank: the cfg
        # DEFAULTS block says 2, which the reader reads as "no AMS expansion over
        # this rigid body" — the documented route into starter ERROR 1066.
        lines += inertia_extra
        # The #106 register, /RBODY producer 1 of 3 (*MAT_RIGID parts, and
        # with them *PART_INERTIA, the element-free CoG masters and the
        # *CONSTRAINED_RIGID_BODIES merge masters). *DATABASE_RBDOUT lists this
        # set; rbody_info cannot stand in for it (see _make_starter_th_rbody).
        state.rbody_ids.add(ind_node)
        lines += [
            f"/RBODY/{ind_node}",
            part.title or f"RBODY_{pid}",
            "#  node_ID   sens_ID   skew_ID    Ispher                Mass   grnd_ID     Ikrem      ICoG   surf_ID",
            f"{_i(ind_node)}{_i(0)}{_i(skew_id)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(icog)}{_i(0)}",
        ]
        lines += _inertia_lines(j_vals)
        lines += [
            "#  Ioptoff   Iexpams     Ifail",
            f"{_i(0)}{_i(0)}{_i(0)}",
        ]
        lines += _emit_grnod_node(grnod_id, f"rb_nodes_pid{pid}", unique_nodes)
        lines += _emit_grnod_node(ind_grnod_id, f"rb_indnode_pid{pid}", [ind_node])

        # Emit /BCS from *MAT_RIGID CMO/CON1/CON2.
        # For implicit analyses with loaded rigid bodies that have FREE
        # translation DOFs in non-loaded directions, auto-add constraints
        # on those DOFs UNLESS the user has explicitly added mass via
        # *ELEMENT_MASS or *ELEMENT_MASS_PART (which provides enough M
        # contribution to K_eff to stabilize without artificial constraint).
        # Tested empirically: without either added mass OR the auto-constraint,
        # the engine segfaults on RANK 0 due to ill-conditioned K_eff.
        tra_chars = list(_con1_to_tra(mat.con1) if mat.cmo == 1.0 else "000")
        rot_chars = list(_con2_to_rot(mat.con2) if mat.cmo == 1.0 else "000")
        # Determine which translation DOFs this rigid body is loaded on.
        # /LOAD_RIGID_BODY dof: 1=Fx, 2=Fy, 3=Fz, 5=Mx, 6=My, 7=Mz
        loaded_tra_idx: set = set()
        for lb in state.load_rigid_bodies:
            if lb.pid == pid and lb.dof in (1, 2, 3):
                loaded_tra_idx.add(lb.dof - 1)
        # Skip auto-constraint if user provided explicit mass for this rigid body
        node_added_mass = state.added_node_masses.get(ind_node, 0.0)
        part_add_mass, part_fin_mass = state.element_mass_parts.get(pid, (0.0, 0.0))
        user_added_mass = node_added_mass + max(part_add_mass, part_fin_mass)
        # Auto-constrain unloaded, unconstrained translation DOFs (only when
        # no user-added mass — the user is responsible for stabilization once
        # they explicitly add mass)
        added_stab = False
        if state.is_implicit and loaded_tra_idx and user_added_mass <= 0:
            for i in (0, 1, 2):
                if tra_chars[i] == "0" and i not in loaded_tra_idx:
                    tra_chars[i] = "1"
                    added_stab = True
        if added_stab:
            free_axes = [("X","Y","Z")[i] for i in range(3) if tra_chars[i] == "1"
                         and (mat.con1 == 0 or _con1_to_tra(mat.con1)[i] == "0")]
            state.warn(
                f"*MAT_RIGID pid={pid}: auto-constrained non-loaded free "
                f"translation(s) {','.join(free_axes)} on rigid body master "
                f"to stabilize implicit K. Add *ELEMENT_MASS_PART to skip this."
            )
        elif state.is_implicit and loaded_tra_idx and user_added_mass > 0:
            state.warn(
                f"*MAT_RIGID pid={pid}: user-added mass {user_added_mass:.6G} "
                f"detected — skipping auto Z constraint (mass provides stability)."
            )
        tra = "".join(tra_chars)
        rot = "".join(rot_chars)
        if tra != "000" or rot != "000":
            bc_id_auto = state.next_id()
            lines += [
                f"/BCS/{bc_id_auto}",
                f"BC_rigid_{pid}",
                "#  Tra rot   skew_ID  grnod_ID",
                f"   {tra} {rot}         0{_i(ind_grnod_id)}",
                HDR,
            ]

    _warn_unapplied_part_inertias(state, inertia_applied, rigid_mids, merge_root,
                                  rbody_info)

    # *CONSTRAINED_RIGID_BODIES: repoint each merged slave pid at its master's
    # rigid-body info so a *LOAD_RIGID_BODY / *BOUNDARY_PRESCRIBED_MOTION_RIGID /
    # *INITIAL_VELOCITY_RIGID_BODY / TH readout keyed on the slave pid resolves
    # to the surviving master's master node.
    for slave, master in merge_root.items():
        if master in rbody_info:
            rbody_info[slave] = rbody_info[master]

    return lines, rigid_nodes, rbody_info


def _resolve_rigid_body_merges(state: ConversionState, rigid_mids: Set[int]) -> Dict[int, int]:
    """*CONSTRAINED_RIGID_BODIES (PIDM, PIDS) pairs → {slave_pid: root_master_pid}.

    Union-find with the master (PIDM) side as the representative, so chained
    merges (A<-B, B<-C) all resolve to the ultimate master A. Only pairs whose
    BOTH parts are *MAT_RIGID are honoured; others are warned and dropped. The
    root master itself is not in the returned map (it keeps its own /RBODY)."""
    parent: Dict[int, int] = {}

    def find(p: int) -> int:
        parent.setdefault(p, p)
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for pidm, pids in state.rigid_body_merges:
        mp = state.parts.get(pidm)
        sp = state.parts.get(pids)
        if (mp is None or mp.mid not in rigid_mids
                or sp is None or sp.mid not in rigid_mids):
            state.warn(
                f"*CONSTRAINED_RIGID_BODIES ({pidm},{pids}): both parts must be "
                "*MAT_RIGID to merge into one rigid body — merge skipped.")
            continue
        rm, rs = find(pidm), find(pids)
        if rm != rs:
            # Attach the slave's root under the master's root.
            parent[rs] = rm
    return {p: find(p) for p in parent if find(p) != p}


def _con1_to_tra(con1: int) -> str:
    return {0: "000", 1: "100", 2: "010", 3: "001", 4: "110", 5: "011", 6: "101", 7: "111"}.get(con1, "000")


def _con2_to_rot(con2: int) -> str:
    return {0: "000", 1: "100", 2: "010", 3: "001", 4: "110", 5: "011", 6: "101", 7: "111"}.get(con2, "000")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: constrained nodal rigid bodies
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_cnrb_spc(state: ConversionState, cnrb) -> Tuple[str, str, int]:
    """Map a *CONSTRAINED_NODAL_RIGID_BODY_SPC constraint card to an OpenRadioss
    /BCS (Tra, Rot, skew_ID). Returns ("000", "000", 0) when nothing is fixed.

    CMO>0: global constraints — con1 = translation code (0-7), con2 = rotation
           code (0-7), in the global frame (skew_ID = 0).
    CMO<0: local constraints — con1 = the local coordinate-system ID (the /SKEW),
           con2 = a 6-digit local DOF code (Tx Ty Tz Rx Ry Rz).
    |CMO|=2 also moves the constraint point to XSPC/YSPC/ZSPC or SPCNID; for a
           rigid body the whole body shares each DOF, so that offset is reported
           but not applied (the /BCS acts through the master node).
    """
    cmo = cnrb.cmo
    if cmo == 0.0:
        return "000", "000", 0
    if cmo > 0.0:
        tra = _con1_to_tra(cnrb.con1)
        rot = _con2_to_rot(cnrb.con2)
        skew = 0
    else:
        skew = cnrb.con1
        code = f"{abs(cnrb.con2):06d}"[-6:]
        tra, rot = code[0:3], code[3:6]
        if skew and skew not in state.coord_nodes and skew not in state.coord_sys:
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY_SPC pid={cnrb.pid}: local SPC "
                f"coordinate system {skew} (CON1) not found among "
                "*DEFINE_COORDINATE_* — /BCS skew_ID will dangle."
            )
    if abs(cmo) == 2.0:
        state.warn(
            f"*CONSTRAINED_NODAL_RIGID_BODY_SPC pid={cnrb.pid}: |CMO|=2 "
            "(constraint at XSPC/YSPC/ZSPC or SPCNID) — the offset point is not "
            "applied; the /BCS acts on the rigid body's master node."
        )
    return tra, rot, skew


def _make_cnrb_rbodies(state: ConversionState) -> Tuple[List[str], Set[int], Dict]:
    """*CONSTRAINED_NODAL_RIGID_BODY[_SPC][_INERTIA] → /RBODY (+ /BCS for _SPC).

    Returns (rad_lines, rigid_node_set, rbody_info_dict) in the same shape as
    _make_rbodies so the two can be merged: the rbody_info feeds /LOAD_RIGID_BODY
    → /CLOAD, /BOUNDARY_PRESCRIBED_MOTION_RIGID → /IMPDISP, /INITIAL_VELOCITY_
    RIGID_BODY → /INIVEL, and the /TH/NODE reaction readout — all keyed by part ID.

    With `_INERTIA` the mass properties come from the card instead of the mesh:
    ``Mass``/``Jxx..Jxz`` are written verbatim, ``ICoG=4`` pins the centre of
    gravity at the main node and ignores the secondaries' mesh contribution, and
    the main node is placed at ``NODEID`` / ``XC,YC,ZC``. `_INERTIA` with a
    ``NODEID`` is also the one case where dyna2rad does not merely lose data — it
    hard-crashes the hm LS-DYNA reader (starter exit 3, no listing at all;
    reproduced on four independent decks, with NODEID inside and outside the node
    set).
    """
    lines: List[str] = []
    rigid_nodes: Set[int] = set()
    rbody_info: Dict = {}
    # Rebuilt from scratch each call: the /BCS records below mirror the cards
    # this function emits, so a second call must not double them up.
    state.cnrb_spc_bcs = []
    if not state.cnrbs:
        return lines, rigid_nodes, rbody_info

    # Nodes that belong to at least one element. A /RBODY main node is moved to
    # the centre of gravity (ICoG, RefGuide p.1879); if that node is attached to
    # deformable elements the move INVERTS them, which crashes the implicit
    # factorization on the first step. So the CNRB master must be element-free.
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    # Thick shells are /BRICK in the emitted deck and carry real stiffness, so
    # their nodes are "attached to an element" exactly like a hex's. The
    # container is empty on every deck without *ELEMENT_TSHELL.
    for e in state.tshell_elems:
        elem_nodes.update(e.nodes)
    for c in state.sph_elems:                 # SPH: the particle IS its node
        elem_nodes.update(c.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2, e.n3))
    # A 1D SEATBELT node cannot serve as the master either. A 2-node /SPRING
    # does not INVERT the way a shell does, but the ICoG move relocates the
    # node, and the belt's whole response is geometric: L0 is taken from the
    # MOVED position at TT==0 (r23l114def3.F:263), so the webbing silently
    # changes length and path, and it also carries mass onto a body that did
    # not ask for it. Synthesize a free master instead.
    for e in state.seatbelt_elems:
        if not e.is_2d:
            elem_nodes.update((e.n1, e.n2))
    # Synthesize new free node IDs above the current maximum (avoids collisions).
    _next_free = [max(state.nodes) + 1 if state.nodes else 90000001]

    def _new_master_at_centroid(member_nodes: List[int]) -> int:
        pts = [state.nodes[n] for n in member_nodes if n in state.nodes]
        # Skip anything already taken — the _INERTIA branch below draws from
        # state.next_node_id(), so this counter is no longer the only allocator
        # in the loop. See the matching note in _make_rbodies.
        while _next_free[0] in state.nodes:
            _next_free[0] += 1
        nid = _next_free[0]
        _next_free[0] += 1
        if pts:
            k = len(pts)
            state.nodes[nid] = NodeData(sum(p.x for p in pts) / k,
                                        sum(p.y for p in pts) / k,
                                        sum(p.z for p in pts) / k)
        else:
            state.nodes[nid] = NodeData(0.0, 0.0, 0.0)
        return nid

    lines.append("#-  CONSTRAINED NODAL RIGID BODIES:")
    lines.append(HDR)

    for cnrb in state.cnrbs:
        node_set = state.node_sets.get(cnrb.nsid)
        if not node_set:
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY pid={cnrb.pid}: node set "
                f"{cnrb.nsid} not found — /RBODY not emitted."
            )
            continue
        _set_title, nids = node_set
        unique_nodes = sorted({n for n in nids if n > 0})
        if not unique_nodes:
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY pid={cnrb.pid}: node set "
                f"{cnrb.nsid} is empty — /RBODY not emitted."
            )
            continue
        # *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL on this CNRB: the three
        # synthesized nodes carrying its co-rotating /SKEW/MOV triad have to be
        # secondaries of THIS body. They are element-free and massless, so they
        # only ever shifted the centroid the master is placed at — and the master
        # is now placed from mesh_nodes, i.e. the node set alone, so the written
        # coordinate is the same with and without a _LOCAL card.
        mesh_nodes = unique_nodes
        helpers = state.local_frame_nodes.get(cnrb.pid)
        if helpers:
            unique_nodes = sorted(set(unique_nodes) | set(helpers))

        # _INERTIA cards 3-6. ``inr`` is the parsed record (the card-5 velocities
        # are used even when the mass override is refused); ``props`` is the
        # accepted (mass, tensor, skew) triple or None.
        inr = cnrb.inertia
        label = f"*CONSTRAINED_NODAL_RIGID_BODY_INERTIA pid={cnrb.pid}"
        props = _resolve_inertia(state, label, inr) if inr is not None else None
        icog = 0
        skew_id = 0
        j_vals = _J_ZERO
        inertia_extra: List[str] = []
        if props is not None:
            inertia_mass, j_vals, skew_id, inertia_extra = props
            icog = ICOG_DEFINED_PROPERTIES

        # Master/primary node. It MUST be element-free (see elem_nodes note): the
        # ICoG move would otherwise invert the elements it belongs to. Reuse an
        # explicit PNODE only when it is element-free; otherwise synthesize a free
        # node at the set's centroid (mirrors LS-DYNA, which for PNODE=0 creates an
        # internal node at the centre of mass). The secondary group is the node
        # set itself — the master stays separate (not slaved to itself).
        secondary_nodes = unique_nodes
        if props is not None:
            # With defined properties the main node IS the stated centre of mass:
            # ICoG=4 does not move it, so its coordinates are where Mass and J act.
            # PNODE cannot serve — LS-DYNA relocates PNODE to the centre of mass
            # itself, i.e. it is a readout node, not the datum.
            ind_node = _inertia_main_node(state, label, inr, elem_nodes,
                                          set(unique_nodes))
            if cnrb.pnode > 0 and cnrb.pnode != ind_node:
                state.warn(
                    f"{label}: PNODE {cnrb.pnode} is NOT used as the /RBODY main "
                    f"node — main node {ind_node} sits at the centre of mass the "
                    "inertia card states (NODEID, else XC/YC/ZC), because ICoG=4 "
                    "pins Mass and J there and does not relocate it. LS-DYNA moves "
                    "PNODE to the centre of mass too, so it is a readout node "
                    "rather than the datum; loads and readouts on this body now "
                    f"address node {ind_node}.")
        elif cnrb.pnode > 0 and cnrb.pnode not in elem_nodes:
            ind_node = cnrb.pnode
        else:
            ind_node = _new_master_at_centroid(mesh_nodes)
            if cnrb.pnode > 0:
                state.warn(
                    f"*CONSTRAINED_NODAL_RIGID_BODY pid={cnrb.pid}: PNODE "
                    f"{cnrb.pnode} is attached to elements; using a synthesized "
                    "free master node at the centroid instead (a meshed master "
                    "moved to the CoG by ICoG would invert its elements)."
                )

        grnod_id = state.next_grnod_id()
        ind_grnod_id = state.next_grnod_id()
        rigid_nodes.update(secondary_nodes)
        rigid_nodes.add(ind_node)
        rbody_info[cnrb.pid] = {
            "ind_node": ind_node,
            "grnod_id": grnod_id,
            "ind_grnod_id": ind_grnod_id,
            "nodes": secondary_nodes,
            # a *CONSTRAINED_NODAL_RIGID_BODY over nodes of DEFORMABLE parts:
            # keyed by the CNRB's own pid, never a whole rigid part
            "kind": "cnrb",
        }

        # Optional added mass on the master node / part (same sources as
        # _make_rbodies): *ELEMENT_MASS[_NODE_SET] on the master node and
        # *ELEMENT_MASS_PART[_SET] on this part go into the /RBODY Mass field.
        node_added = state.added_node_masses.get(ind_node, 0.0)
        part_add, part_fin = state.element_mass_parts.get(cnrb.pid, (0.0, 0.0))
        added_mass = node_added + (part_fin if part_fin > 0 else part_add)
        # `props is None` — see the matching gate in _make_rbodies: with _INERTIA
        # accepted the Mass field holds TM and the SUPERSEDED warning below is the
        # true one, so the two must not both fire.
        if added_mass > 0 and props is None:
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY pid={cnrb.pid}: added mass "
                f"{added_mass:.6G} placed in /RBODY Mass field."
            )
        if props is not None:
            # TM is the body's TOTAL, and ICoG=4 takes Mass verbatim — see the
            # matching note in _make_rbodies.
            if added_mass > 0:
                state.warn(
                    f"{label}: the {added_mass:.6G} of *ELEMENT_MASS/_PART mass on "
                    f"this body is SUPERSEDED by TM={inertia_mass:.6G}, not added "
                    "to it (/RBODY ICoG=4 takes Mass verbatim, and card 4's own "
                    "Default row marks IXX/IYY as required — the card is meant to "
                    "be complete). Fold the lumped mass into TM if it should "
                    "count.")
            added_mass = inertia_mass

        # /RBODY — same 4-card form as _make_rbodies (Card1 + Jxx Jyy Jzz +
        # Jxy Jyz Jxz + Ioptoff Iexpams; all four required or np>1 segfaults).
        # Without _INERTIA, ICoG=0 (=default 1, RefGuide p.1879) MOVES the master
        # node to the computed center of gravity, so a /CLOAD force from
        # *LOAD_RIGID_BODY acts through the CoG as a pure force with no spurious
        # moment — matching LS-DYNA, which likewise relocates PNODE to the center
        # of mass. With _INERTIA, ICoG=4 pins it at the stated centre of mass
        # instead and the mesh contribution is ignored.
        lines += inertia_extra
        state.rbody_ids.add(ind_node)          # producer 2 of 3 (CNRB)
        lines += [
            f"/RBODY/{ind_node}",
            cnrb.title or f"CNRB_{cnrb.pid}",
            "#  node_ID   sens_ID   skew_ID    Ispher                Mass   grnd_ID     Ikrem      ICoG   surf_ID     Ifail",
            f"{_i(ind_node)}{_i(0)}{_i(skew_id)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(icog)}{_i(0)}{_i(0)}",
        ]
        lines += _inertia_lines(j_vals)
        lines += [
            "#  Ioptoff   Iexpams",
            f"{_i(0)}{_i(0)}",
        ]
        lines += _emit_grnod_node(grnod_id, f"cnrb_nodes_pid{cnrb.pid}", secondary_nodes)
        lines += _emit_grnod_node(ind_grnod_id, f"cnrb_indnode_pid{cnrb.pid}", [ind_node])

        # _SPC constraint → /BCS on the master node (global or local skew).
        if cnrb.has_spc:
            tra, rot, skew = _resolve_cnrb_spc(state, cnrb)
            if tra != "000" or rot != "000":
                bc_id = state.next_id()
                lines += [
                    f"/BCS/{bc_id}",
                    f"BC_cnrb_{cnrb.pid}",
                    "#  Tra rot   skew_ID  grnod_ID",
                    f"   {tra} {rot}{_i(skew)}{_i(ind_grnod_id)}",
                    HDR,
                ]
                # Register the constraint so *DATABASE_SPCFORC can see it. This
                # is a SECOND source of /BCS besides *BOUNDARY_SPC_* — the card
                # above is written inline here, so it must not go into
                # state.bcs_spcs (_make_bcs would emit it a second time). The
                # reaction consumers read both lists; see CnrbSpcBc.
                state.cnrb_spc_bcs.append(CnrbSpcBc(bc_id, ind_node, tra, rot))

    return lines, rigid_nodes, rbody_info


def _make_probe_rbody(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Implicit no-rigid-body guard: an inert, fully fixed probe rigid body.

    The OpenRadioss implicit engine segfaults during solver init (MESSAGE ID 44,
    right after the input echo, before the /IMPL option echo) when the model
    contains NO /RBODY — for every implicit flavor (LINEAR, QSTAT/NONLIN, modal)
    and independent of whether the model has contact. One rigid body anywhere
    fixes it. So when an implicit deck has none, add three nodes far outside the
    model and tie them into a minimal rigid body:

      * Mass = Jxx = Jyy = Jzz = 1e-3 — nonzero because a rigid body with zero
        inertia is starter ERROR 274 (the three probe nodes are collinear, so
        the computed inertia alone would be singular);
      * master /BCS 111 111 — all 6 DOFs fixed, so the body adds no equations,
        carries no load, and has zero effect on the solution, the eigenmodes,
        or the exported stiffness matrix.

    Validated on the W14 bogie (contact-free /IMPL/LINEAR static + modal
    stiffness export): without the probe the engine segfaults; with it the run
    terminates normally with 0 warnings and the results are unaffected.
    """
    if not state.is_implicit or rbody_info or not state.nodes:
        return []
    xs = [nd.x for nd in state.nodes.values()]
    ys = [nd.y for nd in state.nodes.values()]
    zs = [nd.z for nd in state.nodes.values()]
    diag = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
    x0 = max(xs) + 2.0 * diag           # well clear of the mesh
    y0, z0 = max(ys), max(zs)
    spacing = 0.1 * diag                # distinct, non-coincident node positions
    # Drawn from state.next_node_id() rather than open-coded off
    # max(state.nodes)+1: these three nodes are NOT registered in state.nodes
    # (they must stay invisible to the free-node singularity guard, which the
    # master's own /BCS already covers and whose /BCS on the two secondaries
    # would fight the /RBODY), so a later site computing max(state.nodes)+1
    # would hand the SAME ids out again — measured, the /PRELOAD frame nodes
    # collided with all three on the implicit General_Nonlinearity deck.
    # next_node_id() also skips ids it has already returned, so reserving here
    # closes the hole while returning the identical n1 on every existing deck.
    n1 = state.next_node_id()
    for _ in range(2):
        state.next_node_id()
    slave_grnod = state.next_grnod_id()
    master_grnod = state.next_grnod_id()
    bcs_id = state.next_id()
    lines = [
        "#-  INERT PROBE RIGID BODY (implicit no-rigid-body segfault guard):",
        HDR,
        "/NODE",
        "#  Node ID               X               Y               Z",
    ]
    for k in range(3):
        lines.append(f"{_i(n1 + k)}{_f(x0 + k * spacing)}{_f(y0)}{_f(z0)}")
    # Producer 3 of 3. This one is NOT in rbody_info at all (it is only
    # appended to rbody_lines), so a deck whose only rigid body is the probe
    # would get no /TH/RBODY group if *DATABASE_RBDOUT read that dict instead.
    state.rbody_ids.add(n1)
    lines += [
        f"/RBODY/{n1}",
        "inert_probe_rbody",
        "#  node_ID   sens_ID   skew_ID    Ispher                Mass   grnd_ID     Ikrem      ICoG   surf_ID",
        f"{_i(n1)}{_i(0)}{_i(0)}{_i(0)}{_f(1e-3)}{_i(slave_grnod)}{_i(0)}{_i(0)}{_i(0)}",
        "#                Jxx                 Jyy                 Jzz",
        f"{_f(1e-3)}{_f(1e-3)}{_f(1e-3)}",
        "#                Jxy                 Jyz                 Jxz",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#  Ioptoff   Iexpams     Ifail",
        f"{_i(0)}{_i(0)}{_i(0)}",
    ]
    lines += _emit_grnod_node(slave_grnod, "inert_probe_slaves", [n1 + 1, n1 + 2])
    lines += _emit_grnod_node(master_grnod, "inert_probe_master", [n1])
    lines += [
        f"/BCS/{bcs_id}",
        "inert_probe_fix",
        "#  Tra rot   skew_ID  grnod_ID",
        f"   111 111         0{_i(master_grnod)}",
        HDR,
    ]
    state.warn(
        "Implicit deck has no rigid body — the OpenRadioss implicit engine "
        "segfaults at solver init (MESSAGE ID 44) without one, independent of "
        f"contact. Injected an inert probe rigid body (/RBODY {n1}, 3 far-away "
        f"nodes {n1}-{n1 + 2}, master fully fixed): it adds no equations and has "
        "zero effect on results. Remove it if you add a real rigid body."
    )
    return lines
