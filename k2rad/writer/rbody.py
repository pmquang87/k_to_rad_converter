"""Starter rigid bodies: /RBODY, constrained nodal rigid bodies, merges, probe rigid body."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from ..state import (
    CnrbSpcBc, ConversionState, MatRigid, NodeData, RigidInertia,
)
from .common import (HDR, _emit_grnod_node, _f, _i, _truss_pids, _vcross,
                     _vnorm)
from .mesh import _emit_skew_fix

__all__ = [
    "_make_rbodies",
    "_resolve_rigid_body_merges",
    "_con1_to_tra",
    "_con2_to_rot",
    "_resolve_cnrb_spc",
    "_make_cnrb_rbodies",
    "_make_shell_to_solid_rbodies",
    "_make_generalized_weld_butt_rbodies",
    "_make_probe_rbody",
    "_inertia_element_nodes",
    "_resolve_inertia",
    "ICOG_DEFINED_PROPERTIES",
    "_RBODY_CARD1_HDR",
    "_RBODY_IOPTOFF_HDR",
]


#: The /RBODY card-1 comment, shared by EVERY producer so the shape cannot
#: drift between them again.
#:
#: NINE fields. ``hm_cfg_files/config/CFG/radioss2021/RBODY/rbody.cfg`` card 1
#: is ``CARD("%10d%10d%10d%10d%20lg%10d%10d%10d%10d", independentnode, ISENSOR,
#: SKEW_CSID, ISPHERE, MASS, dependentnodeset, IKREM, ICOG, SURF_ID)`` and the
#: reader stops there (``hm_read_rbody.F:260-274``). ``Ifail`` is NOT a card-1
#: column: ``hm_read_rbody.F:286-289`` reads ``Ioptoff``, ``Iexpams``, then
#: ``Ifail`` as the THIRD value of the card below the inertia pair. Between
#: round 1 and round 5 the CNRB producer wrote a tenth ``Ifail`` column here
#: and a two-field ``Ioptoff`` card; the fixed-column reader stops at nine, so
#: the emitted zero was never read and no behaviour changed — but the card was
#: not the card the cfg describes.
_RBODY_CARD1_HDR = (
    "#  node_ID   sens_ID   skew_ID    Ispher                Mass"
    "   grnd_ID     Ikrem      ICoG   surf_ID")

#: The /RBODY ``Ioptoff`` card comment — THREE fields, ``Ifail`` last.
_RBODY_IOPTOFF_HDR = "#  Ioptoff   Iexpams     Ifail"


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
    # A TRUSS contributes ONLY (n1, n2): /TRUSS has no third-node column, so a
    # deck-stated N3 on an ELFORM=3 *ELEMENT_BEAM is a node the element does
    # not touch at all. Safe-direction today (an extra node in an "attached"
    # set), wrong in principle — see writer/truss.py.
    truss_pids = _truss_pids(state)
    for e in state.beam_elems:
        if e.pid in truss_pids:
            elem_nodes.update((e.n1, e.n2))
        else:
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


#: The relative margin of the ``J = -SUM(IN)`` correction (round 7, A2): the
#: corrected tensor's smallest principal value must exceed ``RIGID_IN_MARGIN``
#: x its largest, or the body keeps ``J = 0`` and is named. The margin is the
#: starter's own threshold on its DEFAULT path (the round-7 validation round;
#: it was 1e-6, set against ERROR 274): k2rad writes Ispher 0, which
#: ``hm_read_rbody.F:243`` reads as 2, and ``inirby.F:753-758`` then raises
#: every principal value at or below 1e-3 x the largest by 0.1 x the largest
#: (WARNING 275) before ERROR 274 tests ``<= 0`` (``:823-830``) - so a
#: corrected tensor under 1e-3 does not reach LS-DYNA's point-mass value, it
#: gets 10 % of the largest. MEASURED (starter only): a sliver body at a
#: point-mass ratio of 7.5e-5 passed the old margin and read 1.31e-8 on its
#: minimum axis, 1334x LS-DYNA's point-mass 9.8e-12, where J = 0 gives
#: 9.9e-10. It is not ``lumping._INERTIA_RANK_TOL``: that one guards a
#: division in the momentum average. Reach on the 356 roster keys: 2 deck
#: keys on 2 emitted models, one body each (forging_A, forging_B: ratio
#: 3.12e-4; both stop at starter ERROR 179 first); the next smallest ratio
#: among the rule's bodies is 1.73e-3 (the Yaris suspension giants).
RIGID_IN_MARGIN = 1.0e-3


def _rbody_in_skip_reason(state: ConversionState, nodes: Set[int]
                          ) -> str:
    """Why ``k2rad.lumping``'s nodal ``IN`` would NOT be the starter's for a
    body over *nodes*, or ``""``.

    The lumper computes ``IN = (m/4)(A + t^2)/12`` per ``/SHELL`` corner —
    the ``cinmas.F:1379`` value at ``FAC = 12`` (Ishell >= 11,
    ``:919-925``), ``ZSHIFT = 0``, one layer, the SECTION thickness — and
    for a ``/SH3N`` (three distinct corners) the whole-element
    ``m (A/4.5 + t^2/12)`` of ``c3inmas.F:1111``, spread by the corner
    angles (the round-7 validation round; before it a triangle got the quad
    formula and 41 of the 153 bodies the rule then wrote, on 15 roster keys,
    kept up to 9.2 % of their SUM(IN)). Any shell on the body that the starter lumps
    differently makes ``-SUM(IN)`` the wrong amount, so the body is skipped
    by name: Ishell < 11 (FAC 9), a layered property
    (``*PART_COMPOSITE``, ``ICOMP = 1``; the only shells k2rad writes with an
    offset, since a plain shell's NLOC and *ELEMENT_SHELL_OFFSET are dropped
    at read time), an element-level thickness, or a shell with no
    *SECTION_SHELL.

    ONE function for both callers - the default ``J = -SUM(IN)`` of
    :func:`_make_rbodies` (round 7, A2) and ``--mass-weighted-inivel``'s pass
    ``loads._apply_mass_weighted_rbody_inertia`` (round 6, A7). The
    ``_elform_to_ishell`` import stays a CALL-time import: a test probes the
    unreachable Ishell < 11 arm by patching ``common._elform_to_ishell``
    (k2rad writes Ishell 12 / 24 only)."""
    from .common import _elform_to_ishell
    for e in state.shell_elems:
        if not any(n in nodes for n in e.nodes):
            continue
        part = state.parts.get(e.pid)
        if part is None:
            continue
        if part.secid == 0 and e.pid in state.part_composites:
            return (f"part {e.pid} is a *PART_COMPOSITE (a layered property: "
                    "the starter lumps IN per layer, cinmas.F:926-1290)")
        sec = state.sec_shells.get(part.secid)
        if sec is None:
            return f"part {e.pid} has no *SECTION_SHELL"
        if sec.icomp == 1:
            return (f"section {sec.secid} is ICOMP 1 (a layered property: the "
                    "starter lumps IN per layer, cinmas.F:926-1290)")
        if any(e.thick_nodes):
            return (f"shell {e.eid} states its own thickness "
                    "(*ELEMENT_SHELL_THICKNESS; the lumper uses the section's)")
        ishell = _elform_to_ishell(sec.elform, state.is_implicit,
                                   state.options.shell_default_ishell)
        if ishell < 11:
            return (f"section {sec.secid} is Ishell {ishell} < 11: the starter "
                    "lumps IN with FAC 9 (cinmas.F:919-925), which k2rad's "
                    "lumper does not model")
    return ""


def _body_tensor(state: ConversionState, nodes: Set[int],
                 mass_by_node: Dict[int, float]) -> List[List[float]]:
    """The point-mass inertia tensor of the lumped masses on *nodes*, about
    their lumped centre of mass - what ``inirby.F`` sums for ICoG 1/2/3
    before the nodal ``IN`` and the ``/RBODY`` J cells are added."""
    import math
    pts = [(state.nodes[n].x, state.nodes[n].y, state.nodes[n].z,
            mass_by_node.get(n, 0.0)) for n in sorted(nodes)
           if n in state.nodes]
    m_tot = math.fsum(p[3] for p in pts)
    if m_tot > 0.0:
        cx = math.fsum(p[0] * p[3] for p in pts) / m_tot
        cy = math.fsum(p[1] * p[3] for p in pts) / m_tot
        cz = math.fsum(p[2] * p[3] for p in pts) / m_tot
    else:
        cx = cy = cz = 0.0
    t = [[0.0] * 3 for _ in range(3)]
    for x, y, z, m in pts:
        d = (x - cx, y - cy, z - cz)
        r2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        for a in range(3):
            for b in range(3):
                t[a][b] += m * ((r2 if a == b else 0.0) - d[a] * d[b])
    return t


def _rigid_shell_in_correction(
        state: ConversionState, nodes: Set[int], j_old: Tuple[float, ...],
        lumped: Tuple[Dict[int, float], Dict[int, float]],
        tri_nodes: Optional[Set[int]] = None
) -> Tuple[Tuple[float, ...], str, Dict]:
    """``J = J_old - SUM(IN)`` on the diagonal of ONE ``*MAT_RIGID`` /
    ``*DEFORMABLE_TO_RIGID`` part body (round 7, A2) -> ``(J, status,
    facts)``.

    *status* is ``"applied"`` (J written), ``"skipped"`` (the lumper is not
    the starter's for this body: ``facts["reason"]``), ``"refused"`` (the
    corrected tensor's smallest principal value is not above
    ``RIGID_IN_MARGIN`` x the largest) or ``""`` (no shell IN on the body at
    all - nothing is written, no ``-0`` either: icfd's main_fsi.k states
    ``*SECTION_SHELL t1 = 0.0`` on its rigid shells). ``SUM(IN)`` is the
    lumper's ``IN`` (``k2rad.lumping.nodal_masses_from_state``, shells only:
    the ``cinmas.F:1379`` value for a ``/SHELL``, the ``c3inmas.F:1111`` one
    for a ``/SH3N``) summed ONCE over *nodes* - the body's
    secondaries and its main node, i.e. every node the starter adds ``IN``
    for (``inirby.F:166-168`` the main node, ``:355-363`` the secondaries),
    merged deformable shells and a ``*CONSTRAINED_RIGID_BODIES`` union
    included. The off-diagonal cells are left as they were. *tri_nodes*
    (``lumping.triangle_shell_nodes``) only counts the body's ``/SH3N``
    corners into ``facts["n_tri"]`` for the warning."""
    import math
    from ..lumping import _sym3_eigen
    mass_by_node, in_by_node = lumped
    shell_nodes = sorted(n for n in nodes if in_by_node.get(n, 0.0) > 0.0)
    sum_in = math.fsum(in_by_node[n] for n in shell_nodes)
    facts: Dict = {"sum_in": sum_in, "n_shell": len(shell_nodes),
                   "n_tri": len(nodes & tri_nodes) if tri_nodes else 0}
    if sum_in <= 0.0:
        return j_old, "", facts
    why = _rbody_in_skip_reason(state, nodes)
    if why:
        facts["reason"] = why
        return j_old, "skipped", facts
    j_new = (j_old[0] - sum_in, j_old[1] - sum_in, j_old[2] - sum_in,
             j_old[3], j_old[4], j_old[5])
    # the tensor the starter will assemble with j_new: the point masses, the
    # nodal IN it adds on the diagonal, and the J cells
    t = _body_tensor(state, nodes, mass_by_node)
    for a in range(3):
        t[a][a] += sum_in + j_new[a]
    t[0][1] += j_new[3]
    t[1][0] += j_new[3]
    t[1][2] += j_new[4]
    t[2][1] += j_new[4]
    t[0][2] += j_new[5]
    t[2][0] += j_new[5]
    ev = sorted(_sym3_eigen(t)[0])
    facts["ev_min"], facts["ev_max"] = ev[0], ev[-1]
    if not (ev[-1] > 0.0 and ev[0] > RIGID_IN_MARGIN * ev[-1]):
        return j_old, "refused", facts
    return j_new, "applied", facts


def _warn_rigid_shell_in(state: ConversionState,
                         applied: List[Tuple[int, int, int]],
                         skipped: List[Tuple[str, int, int, str]],
                         refused: List[Tuple[str, int, int, Dict]]) -> None:
    """The A2 warnings (round 7): ONE line per deck for the bodies that were
    written (with the measured evidence; *applied* rows are ``(pid, main,
    /SH3N corners on the body)``), one line per body kept by name."""
    if applied:
        ids = [main for _pid, main, _ntri in applied]
        shown = ", ".join(f"/RBODY/{m}" for m in ids[:5]) + (
            f" and {len(ids) - 5} more" if len(ids) > 5 else "")
        n_tri = sum(1 for _pid, _main, ntri in applied if ntri)
        tri = (f" On {n_tri} of these bodies some shells are /SH3N, whose "
               "IN the starter takes from c3inmas.F:1111 instead: the whole "
               "element's m (A/4.5 + t^2/12), spread by the corner angles / "
               "pi (spmd_msin.F:556-557) - and so does the subtraction."
               if n_tri else "")
        state.warn(
            "*MAT_RIGID / *DEFORMABLE_TO_RIGID: J = -SUM(IN) written into the "
            f"Jxx/Jyy/Jzz cells of {len(ids)} /RBODY block(s) ({shown}): the "
            "starter ADDS every shell node's lumped rotary inertia IN = "
            "(m/n)(A + t^2)/12 (cinmas.F:1379, FAC 12) to a rigid body's "
            "tensor for ICoG 1/2/3 (inirby.F:166-168 for the main node, "
            ":355-363 for the secondaries), while LS-DYNA's rigid-part inertia "
            "is the point-mass sum of the nodal masses (MEASURED, not quoted: "
            "the reference d3hsp tensor equals it on 18 of 18 bodies within "
            "0.04 %; Theory R16 eq. 29.23's density integral J_rho is not what "
            "it prints - revo-stiff's one-shell body reads 1.977e-3, the "
            "point-mass value, where the integral gives 6.66e-4). MEASURED "
            "(nt 4): a spun 20 x 20 x "
            "2 mm rigid plate's rotational KE +16.83 % (normal axis) / +33.66 % "
            "(in-plane) -> 0.00 % against the closed form; "
            "intro-by-j.-day/joint/joint-i/revo-stiff.k IE / KE history RMS "
            f"{_A2_REVO_RMS} % of the LS peak at {_A2_REVO_CYCLES} the cycles "
            "(the main node's rotational step shrinks with J)." + tri + " Pass "
            "--no-rigid-shell-rotary-inertia to keep J = 0.")
    for kw, pid, main, why in skipped:
        state.warn(
            f"{kw} pid={pid}: /RBODY/{main} keeps J = 0 - {why}, so -SUM(IN) "
            "would take out the wrong amount; its spin carries the lumped "
            "rotary-inertia residual.")
    for kw, pid, main, facts in refused:
        state.warn(
            f"{kw} pid={pid}: /RBODY/{main} keeps J = 0 - with J = -SUM(IN) = "
            f"{-facts['sum_in']:g} its point-mass tensor's smallest principal "
            f"value {facts['ev_min']:g} would not exceed {RIGID_IN_MARGIN:g} x "
            f"the largest {facts['ev_max']:g} (a near-collinear or sliver "
            "body). At the default Ispher (0, read as 2: hm_read_rbody.F:243) "
            "the starter raises every principal value at or below 1e-3 x the "
            "largest by 0.1 x the largest (WARNING 275, inirby.F:753-758), "
            "far above the point-mass value LS-DYNA uses, so the shell IN "
            "the starter adds is kept instead; ERROR 274 (inirby.F:823-830) "
            "fires only below -0.1 x the largest.")


#: The revo-stiff figures the A2 warning quotes, ONE copy (the same
#: measurement must not ship as two numbers): IE / KE history RMS in % of the
#: LS peak, base -> J arm, scored over the LS glstat blocks up to the last
#: printed OpenRadioss cycle (OR interpolated at each LS time), nt 4; and the
#: base-paired cycle ratio of the same window.
_A2_REVO_RMS = "4.96 / 2.94 -> 0.78 / 0.73"
_A2_REVO_CYCLES = "1.156x"


def _warn_unapplied_part_inertias(state: ConversionState, applied: Set[int],
                                  rigid_pids: Set[int],
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
        elif pid not in rigid_pids:
            reason = (f"its material {part.mid} is not a *MAT_RIGID (and no "
                      "*DEFORMABLE_TO_RIGID card names the part), and "
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

def _warn_deformable_to_rigid(state: ConversionState, pid: int,
                              lrb: int) -> None:
    """The per-part *DEFORMABLE_TO_RIGID note, with the measured consequence.

    Split out so the ELEMENT-deactivation fact and the pend.imp numbers are
    stated once, where the /RBODY is actually emitted.
    """
    part = state.parts.get(pid)
    law = (f"*PART {pid}'s own material {part.mid}" if part is not None
           else "the part's own material")
    merge = ""
    if lrb:
        merge = (f" LRB = {lrb} merges this part into part {lrb}'s single "
                 "/RBODY, through the same union-find *CONSTRAINED_RIGID_BODIES "
                 "uses. (Reach of a non-zero LRB on every corpus this converter "
                 "is measured against: 0 cards.)")
    state.warn(
        f"*DEFORMABLE_TO_RIGID PID {pid}: the part is rigid FROM t = 0 (Vol I "
        "R17 p.18-1: \"Deformable parts may be switched to rigid at the start "
        "of the calculation by specifying them on the *DEFORMABLE_TO_RIGID "
        "card\") and is emitted as an /RBODY through the same path a *MAT_RIGID "
        f"part takes — {law} is KEPT and only supplies the body's element mass "
        "and contact stiffness; /RBODY merely constrains the nodes. Its "
        "elements are DEACTIVATED (hm_read_rbody.F:700-722 sets ISOLOFF for "
        "every solid whose 8 nodes are in the group), so the part no longer "
        "controls the time step: MEASURED on "
        "intro-by-k.-weimar/misc/pendulum-i/pend.imp.k, the controlling element "
        "goes SOLID at dt 1.360e-06 to TRUSS at dt 1.794e-05, which is "
        "LS-DYNA's own 1.79363E-05, and the deck's energy error goes 99.9 % to "
        "-0.0 % (internal energy 5.162e5 to 5.901e-06 against the LS-DYNA "
        "reference 5.03545e-06) in 9 480 cycles where LS-DYNA takes 9 479."
        " That -0.0 % is the ENGINE's own energy balance, not a deviation "
        "from the reference: the campaign row still reads ie_dev +17.19 % and "
        "stays a deviation, both energies being structural zeros on a gravity "
        "pendulum. The FIDELITY channel here is the KINETIC energy - 21.8702 "
        "against 21.874, -0.017 %, the whole trajectory inside +/-0.07 % at "
        "11 matched times."
        + merge +
        " Mass and inertia come from the MESH, as in LS-DYNA. Pass "
        "--no-deformable-to-rigid to leave the part deformable.")


def _deformable_to_rigid_map(state: ConversionState) -> Dict[int, int]:
    """``{pid: LRB}`` for the *DEFORMABLE_TO_RIGID parts this run will convert.

    Empty (with the loss recorded) under ``--no-deformable-to-rigid``. This is
    the only site that WARNS about the option, so the refusal message has one
    home. The shared predicate ``writer.common.rigid_part_ids`` reads the same
    flag — it has to, or the six consumers that ask "is this part rigid?" would
    answer yes about a part this function leaves deformable.
    """
    if not state.deformable_to_rigid:
        return {}
    if state.options.deformable_to_rigid:
        return dict(state.deformable_to_rigid)
    pids = sorted(state.deformable_to_rigid)
    state.warn(
        f"--no-deformable-to-rigid: *DEFORMABLE_TO_RIGID part(s) {pids} were "
        "left DEFORMABLE. LS-DYNA makes them rigid at t = 0 (Vol I R17 "
        "p.18-1), so the converted model is SOFTER than the source deck, its "
        "time step is controlled by elements LS-DYNA deactivates, and its "
        "internal energy is not comparable to the reference: measured on "
        "pend.imp, 5.162e5 against an LS-DYNA reference of 5.03545e-06.")
    state.note_recognized_not_emitted(
        "DEFORMABLE_TO_RIGID",
        f"--no-deformable-to-rigid: part(s) {pids} stay deformable, so no "
        "/RBODY was emitted for them.")
    return {}


def _make_rbodies(state: ConversionState) -> Tuple[List[str], Set[int], Dict]:
    """Return (rad_lines, rigid_node_set, rbody_info_dict)."""
    lines: List[str] = []
    rigid_nodes: Set[int] = set()
    rbody_info: Dict = {}
    # The BC_rigid_<pid> records (round 7, A1) and their stabilisation digits
    # mirror the cards emitted below: reset BEFORE the early returns.
    state.rigid_auto_bcs = {}
    state.rigid_auto_stab = {}
    # ... and round 8's CMO -1 records (A1): the skewed cards and the CON1-0
    # main nodes, with the t = 0 /SKEW/FIX of a FLAG-1 CON1 drawn once per call
    state.rigid_skewed_bcs = {}
    state.rigid_auto_cmo_neg = set()
    t0_cache: Dict[int, int] = {}
    # round 8, A8: which rigid nodes keep their *ELEMENT_MASS in a Mass field
    # (main nodes, ICoG-4 members) and which secondary masses move to /ADMAS
    state.rbody_folded_mass_nodes = set()
    state.rbody_secondary_masses = {}
    from .joint_screw import screw_cmo_skip_pids, screw_pad, screw_pad_pids
    screw_skip = screw_cmo_skip_pids(state)
    # round 8, B8 (q-i): part A of an UNDRIVEN screw -> its plan (the pad)
    screw_pads = screw_pad_pids(state)

    # *MAT_RIGID parts AND *DEFORMABLE_TO_RIGID parts, through the ONE
    # predicate — see writer.common.rigid_part_ids for why a consumer left on
    # state.mat_rigid alone is a defect. Every downstream consumer that reads
    # the three values this function returns (the /GRAV scope's rbody_info
    # tags, the /INIVEL classification, the contacts' rigid_nodes screen,
    # /BCS's node_to_ind, state.rbody_ids -> /TH/RBODY, _make_added_masses'
    # skip-rigid rule) is therefore correct for free.
    d2r: Dict[int, int] = _deformable_to_rigid_map(state)
    rigid_pids: Set[int] = {p for p, part in state.parts.items()
                            if part.mid in state.mat_rigid} | set(d2r)

    if not rigid_pids:
        for pid in sorted(state.extra_rigid_nodes):
            state.warn(
                f"*CONSTRAINED_EXTRA_NODES pid={pid}: part is not a *MAT_RIGID "
                "part — extra nodes not attached (deformable-part extra nodes "
                "have no /RBODY to join).")
        _warn_unapplied_part_inertias(state, set(), set(), {}, rbody_info)
        return lines, rigid_nodes, rbody_info

    nodes_by_pid: Dict[int, List[int]] = defaultdict(list)
    for e in state.shell_elems:
        if e.pid in rigid_pids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for e in state.solid_elems:
        if e.pid in rigid_pids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for e in state.tshell_elems:              # /BRICK too — see above
        if e.pid in rigid_pids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for c in state.sph_elems:                 # SPH nodes join like any other
        if c.pid in rigid_pids:
            nodes_by_pid[c.pid].extend(c.nodes)
    for e in state.beam_elems:
        if e.pid in rigid_pids:
            nodes_by_pid[e.pid].extend([e.n1, e.n2])

    # *CONSTRAINED_EXTRA_NODES_NODE/_SET: extra nodes rigidly attached to the
    # part join its /RBODY secondary-node group (they also let an element-free
    # *MAT_RIGID part form a rigid body at all).
    for pid, extra in state.extra_rigid_nodes.items():
        if pid not in rigid_pids:
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
    merge_root = _resolve_rigid_body_merges(state, rigid_pids, d2r)
    for slave, master in sorted(merge_root.items()):
        moved = nodes_by_pid.pop(slave, [])
        if moved:
            nodes_by_pid[master].extend(moved)

    if not nodes_by_pid:
        for mid in sorted(state.mat_rigid):
            state.warn(f"*MAT_RIGID mid={mid}: no elements found; /RBODY not emitted")
        for pid in sorted(d2r):
            state.warn(f"*DEFORMABLE_TO_RIGID pid={pid}: no elements found; "
                       "/RBODY not emitted — the part is NOT rigid in the "
                       "converted model.")
        _warn_unapplied_part_inertias(state, set(), rigid_pids, merge_root,
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

    emitted_pids: Set[int] = set()
    # J = -SUM(IN) (round 7, A2): the lumper runs once, lazily, and the three
    # outcomes are reported after the loop
    lumped: Optional[Tuple[Dict[int, float], Dict[int, float]]] = None
    tri_nodes: Set[int] = set()
    a2_applied: List[Tuple[int, int, int]] = []
    a2_skipped: List[Tuple[str, int, int, str]] = []
    a2_refused: List[Tuple[str, int, int, Dict]] = []
    for pid, all_nodes in sorted(nodes_by_pid.items()):
        part = state.parts.get(pid)
        if not part: continue
        # A *DEFORMABLE_TO_RIGID part has NO *MAT_RIGID card at all — it keeps
        # its own deformable law — so `mat` is legitimately None here and the
        # old `if not mat: continue` would have dropped the whole body. Every
        # read of `mat` below is guarded; the keyword name travels with it so
        # the warnings say which card made the part rigid.
        mat: Optional[MatRigid] = state.mat_rigid.get(part.mid)
        is_d2r = pid in d2r
        if mat is None and not is_d2r: continue
        kw = "*DEFORMABLE_TO_RIGID" if mat is None else "*MAT_RIGID"
        unique_nodes = sorted(set(n for n in all_nodes if n > 0))
        if not unique_nodes: continue
        if is_d2r:
            _warn_deformable_to_rigid(state, pid, d2r[pid])
        emitted_pids.add(pid)

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

        # `inr is not None` is redundant: `props` is only ever built as
        # `_resolve_inertia(...) if inr is not None else None` above, so a
        # non-None `props` already implies it. Stated so the narrowing is local.
        if props is not None and inr is not None:
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
                f"{kw} pid={pid}: /RBODY master is a synthesized "
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
            # The ICoG cell this body's /RBODY carries, for the ONE consumer
            # that needs to know WHERE the main node ends up:
            # --mass-weighted-inivel writes v_cm on it, which is only the
            # rigid field's value there when the starter has moved the node to
            # the centre of mass (ICoG 0/1, inirby.F:186-211). Read, never
            # re-derived -- a second copy of the rule is how the two disagree.
            "icog": icog,
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
        a8 = state.options.rigid_element_mass_admas and props is None
        if a8:
            # round 8, A8 (default ON, --no-rigid-element-mass-admas): only the
            # MAIN node's own *ELEMENT_MASS stays in the Mass field. A mass on
            # any other member becomes /ADMAS/0 on its node
            # (_make_added_masses): the starter counts it there, so the body's
            # centre of mass and inertia include it - folded into Mass it sat
            # at the main node, which the starter moves to the CoG of the
            # secondaries WITHOUT it (foam: CoG z 121.4891 vs LS-DYNA's
            # 150.96326); under --no-rigid-cog-master it was dropped.
            node_added = state.added_node_masses.get(ind_node, 0.0)
            state.rbody_folded_mass_nodes.add(ind_node)
            for n in unique_nodes:
                if n != ind_node and state.added_node_masses.get(n, 0.0) > 0:
                    state.rbody_secondary_masses[n] = (
                        pid, "folded" if state.options.rigid_cog_master
                        else "dropped")
        elif state.options.rigid_cog_master:
            # The synthesized master carries no *ELEMENT_MASS of its own, and
            # _make_added_masses skips rigid-body nodes (their /ADMAS belongs to
            # the /RBODY) — so fold the *ELEMENT_MASS of ALL of the part's nodes
            # into the Mass field, not just the old master's.
            node_added = sum(state.added_node_masses.get(n, 0.0)
                             for n in unique_nodes)
        else:
            node_added = state.added_node_masses.get(ind_node, 0.0)
        if props is not None:
            # ICoG 4: TM supersedes every lumped mass of the body (round 8,
            # A8 leaves these bodies as they were)
            state.rbody_folded_mass_nodes.update(unique_nodes)
            state.rbody_folded_mass_nodes.add(ind_node)
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
                         and not a8 else f"node {ind_node}")
                sources.append(f"*ELEMENT_MASS on {where}={node_added:.6G}")
            if part_add > 0:
                sources.append(f"*ELEMENT_MASS_PART ADDMASS={part_add:.6G}")
            if part_fin > 0:
                sources.append(f"*ELEMENT_MASS_PART FINMASS={part_fin:.6G}")
            state.warn(
                f"{kw} pid={pid}: total added mass {added_mass:.6G} "
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
        #
        # J = -SUM(IN) (round 7, A2, default ON; --no-rigid-shell-rotary-
        # inertia keeps J = 0): the starter ADDS every shell node's lumped
        # rotary inertia to the body tensor for ICoG 1/2/3 (inirby.F:166-168,
        # :355-363), LS-DYNA's rigid-part inertia is the point-mass sum. Written
        # HERE, in the producer, before rbody_info meets the CNRB records: a
        # CNRB PID equal to this part id replaces the part's record in the
        # merge (doorbeam's part 4), so a post-pass keyed on the merged dict
        # would never see this body. ICoG 4 (props) keeps the deck's tensor:
        # inirby.F:266-280 adds no secondary IN there.
        j_status = ""
        # round 9, B2: a deck routed to the 2-D axisymmetric deck writes
        # J = 0 (in 2-D I_xx = I_yy + I_zz exactly, inirby.F:366-398, and quad
        # nodes carry no rotary inertia to cancel), so the correction - and
        # its sentence - are skipped there.
        routed = (state.axisym_plan is not None
                  and state.axisym_plan.routed)
        if (props is None and state.options.rigid_shell_rotary_inertia
                and not routed):
            if lumped is None:
                from ..lumping import (nodal_masses_from_state,
                                       triangle_shell_nodes)
                lumped = nodal_masses_from_state(state)
                tri_nodes = triangle_shell_nodes(state)
            j_vals, j_status, j_facts = _rigid_shell_in_correction(
                state, set(unique_nodes) | {ind_node}, j_vals, lumped,
                tri_nodes)
            if j_status == "applied":
                a2_applied.append((pid, ind_node, j_facts["n_tri"]))
            elif j_status == "skipped":
                a2_skipped.append((kw, pid, ind_node, j_facts["reason"]))
            elif j_status == "refused":
                a2_refused.append((kw, pid, ind_node, j_facts))
        rbody_info[pid]["j_in"] = j_status
        # round 8, B8 (q-i): the spinning body of an UNDRIVEN screw gets its
        # screw-axis inertia ADDED about the two axes normal to the axis, on
        # top of whatever the row holds (A2's -SUM(IN) included), so the main
        # node's IN - its smallest principal inertia, inirby.F:838, the ONE
        # scalar lag_mult_solv.F:393 divides by - is the axis inertia
        if pid in screw_pads:
            if lumped is None:
                from ..lumping import (nodal_masses_from_state,
                                       triangle_shell_nodes)
                lumped = nodal_masses_from_state(state)
                tri_nodes = triangle_shell_nodes(state)
            j_vals = screw_pad(state, screw_pads[pid],
                               set(unique_nodes) | {ind_node}, j_vals,
                               lumped, props is not None)
        lines += inertia_extra
        # The #106 register, /RBODY producer 1 of 6 (*MAT_RIGID parts, and
        # with them *PART_INERTIA, the element-free CoG masters and the
        # *CONSTRAINED_RIGID_BODIES merge masters). *DATABASE_RBDOUT lists this
        # set; rbody_info cannot stand in for it (see _make_starter_th_rbody).
        state.rbody_ids.add(ind_node)
        lines += [
            f"/RBODY/{ind_node}",
            part.title or f"RBODY_{pid}",
            _RBODY_CARD1_HDR,
            f"{_i(ind_node)}{_i(0)}{_i(skew_id)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(icog)}{_i(0)}",
        ]
        lines += _inertia_lines(j_vals)
        # The J cells exactly as written, for the one post-pass that may
        # rewrite them (--mass-weighted-inivel, loads.
        # _apply_mass_weighted_rbody_inertia), which asserts the row it
        # replaces against this record.
        rbody_info[pid]["j"] = tuple(j_vals)
        lines += [
            _RBODY_IOPTOFF_HDR,
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
        # A *DEFORMABLE_TO_RIGID part has no CMO/CON1/CON2 cells at all
        # (the card is three fields, Vol I R17 p.18-2), so it is free in
        # every DOF and gets no /BCS — which is what LS-DYNA does too.
        tra_chars = list(_con1_to_tra(mat.con1)
                         if mat is not None and mat.cmo == 1.0 else "000")
        rot_chars = list(_con2_to_rot(mat.con2)
                         if mat is not None and mat.cmo == 1.0 else "000")
        # CMO -1 (round 8, A1; default ON, --no-rigid-local-constraints writes
        # nothing as before): CON2's six-digit code in the /SKEW of CON1, by
        # the helper the CNRB _SPC option shares. A screw body's constraints
        # are re-written by the joint, so the helper is not even asked there
        # (a refused or skipped card allocates no skew id).
        local: Optional[Tuple[str, str, int, List[str], str]] = None
        skew_bc = 0
        if (mat is not None and state.options.rigid_local_constraints
                and pid not in screw_skip):
            if mat.cmo == -1.0:
                local = _local_constraint(
                    state, f"*MAT_RIGID mid={mat.mid} (part {pid})",
                    mat.con1, mat.con2, t0_cache)
                if local is not None:
                    tra_chars, rot_chars = list(local[0]), list(local[1])
                    skew_bc = local[2]
            elif abs(mat.cmo) == 2.0:
                state.warn(
                    f"*MAT_RIGID mid={mat.mid} (part {pid}): CMO {mat.cmo:g} "
                    "constrains the body at XSPC/YSPC/ZSPC or node SPCNID, not "
                    "its centre of mass; an /RBODY holds a /BCS on its main "
                    "node only, so NO /BCS is written (as before, now said).")
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
        stab_chars = ["0", "0", "0"]      # the digits ONLY this rule adds
        if (state.is_implicit and loaded_tra_idx and user_added_mass <= 0
                and skew_bc != 0):
            # round 8, A1: a CMO -1 card in a skew - its digits are axes of
            # that skew and the node takes ONE skew (ERROR 148), so a global
            # stabilisation digit can be neither merged into it nor written
            # beside it
            if any(tra_chars[i] == "0" and i not in loaded_tra_idx
                   for i in (0, 1, 2)):
                state.warn(
                    f"{kw} pid={pid}: implicit deck: the stabilisation of an "
                    "unloaded free translation is NOT added to "
                    f"BC_rigid_{pid}, whose /BCS sits in /SKEW/{skew_bc} (one "
                    "node takes one skew, ERROR 148, hm_read_bcs.F:199-205); "
                    "state the free translation in the body's own CON2 if the "
                    "implicit stiffness needs it.")
        elif state.is_implicit and loaded_tra_idx and user_added_mass <= 0:
            for i in (0, 1, 2):
                if tra_chars[i] == "0" and i not in loaded_tra_idx:
                    tra_chars[i] = "1"
                    stab_chars[i] = "1"
                    added_stab = True
        if added_stab and local is not None:
            free_axes = [("X", "Y", "Z")[i] for i in range(3)
                         if stab_chars[i] == "1"]
        elif added_stab:
            free_axes = [("X","Y","Z")[i] for i in range(3) if tra_chars[i] == "1"
                         and (mat is None or mat.con1 == 0
                              or _con1_to_tra(mat.con1)[i] == "0")]
        if added_stab:
            state.warn(
                f"{kw} pid={pid}: auto-constrained non-loaded free "
                f"translation(s) {','.join(free_axes)} on rigid body master "
                f"to stabilize implicit K. Add *ELEMENT_MASS_PART to skip this."
            )
        elif state.is_implicit and loaded_tra_idx and user_added_mass > 0:
            state.warn(
                f"{kw} pid={pid}: user-added mass {user_added_mass:.6G} "
                f"detected — skipping auto Z constraint (mass provides stability)."
            )
        tra = "".join(tra_chars)
        rot = "".join(rot_chars)
        # A converted *CONSTRAINED_JOINT_SCREW (round 7, B2) re-writes both
        # bodies' constraints as /BCS/LAGMUL: a standard /BCS on a node the
        # Lagrange joint holds is incompatible, so neither the card nor A1's
        # record of it is written (ONE predicate, screw_cmo_skip_pids).
        if (tra != "000" or rot != "000") and pid not in screw_skip:
            if local is not None:
                lines += local[3]          # a FLAG-1 CON1's t = 0 /SKEW/FIX
            bc_id_auto = state.next_id()
            if skew_bc:
                # round 8, A1: a SKEWED card - its own record (the round-7
                # 3-tuple pins skew 0); the TC/RC pass and _make_bcs drop a
                # code in another skew on this node (ERROR 148)
                state.rigid_skewed_bcs.setdefault(ind_node, []).append(
                    (tra, rot, skew_bc, f"BC_rigid_{pid}"))
            else:
                # The EMITTED digits (CON1/CON2 OR the implicit stabilisation
                # above), at skew 0: screen (c') of loads._make_node_tc_rc_bcs
                # merges a member TC/RC code re-pointed onto this main node
                # into this card instead of writing a second /BCS (round 7,
                # A1).
                _old = state.rigid_auto_bcs.get(ind_node)
                state.rigid_auto_bcs[ind_node] = (
                    (tra, rot, f"BC_rigid_{pid}") if _old is None else
                    ("".join("1" if "1" in (a, b) else "0"
                             for a, b in zip(_old[0], tra)),
                     "".join("1" if "1" in (a, b) else "0"
                             for a, b in zip(_old[1], rot)),
                     f"{_old[2]}, BC_rigid_{pid}"))
                if local is not None:
                    state.rigid_auto_cmo_neg.add(ind_node)
            if added_stab:
                _st = state.rigid_auto_stab.get(ind_node, "000")
                state.rigid_auto_stab[ind_node] = "".join(
                    "1" if "1" in (a, b) else "0"
                    for a, b in zip(_st, stab_chars))
            lines += [
                f"/BCS/{bc_id_auto}",
                f"BC_rigid_{pid}",
                "#  Tra rot   skew_ID  grnod_ID",
                f"   {tra} {rot}{_i(skew_bc)}{_i(ind_grnod_id)}",
                HDR,
            ]
            if local is not None and mat is not None:
                state.warn(_cmo_neg_sentence(
                    f"*MAT_RIGID mid={mat.mid} (part {pid})",
                    f"{abs(int(mat.con2)):06d}", bc_id_auto,
                    "".join(local[0]), "".join(local[1]), skew_bc, ind_node,
                    int(mat.con1), local[4],
                    state.coord_nodes.get(int(mat.con1))))

    # A *DEFORMABLE_TO_RIGID part whose elements never reached a /RBODY is NOT
    # rigid in the converted model, and that has to be said: LS-DYNA deactivates
    # those elements at t = 0 and k2rad would leave them controlling the time
    # step. The *MAT_RIGID half already has its own mid-keyed warning on the
    # all-empty path above.
    for pid in sorted(set(d2r) - emitted_pids - set(merge_root)):
        state.warn(
            f"*DEFORMABLE_TO_RIGID pid={pid}: no shell/solid/beam/SPH element "
            "of this part was found, so NO /RBODY was emitted for it and the "
            "part is NOT rigid in the converted model. LS-DYNA makes it rigid "
            "at t = 0 and deactivates its elements (Vol I R17 p.18-1).")

    _warn_unapplied_part_inertias(state, inertia_applied, rigid_pids, merge_root,
                                  rbody_info)
    _warn_rigid_shell_in(state, a2_applied, a2_skipped, a2_refused)
    # round 8, A1: a merged slave's own CMO -1 / +-2 code is not written - the
    # merged /RBODY carries the lead's card only (the loop above reads the
    # lead's material). Said where the two codes differ (reach 0).
    if state.options.rigid_local_constraints:
        for slave, lead in sorted(merge_root.items()):
            sp, lp = state.parts.get(slave), state.parts.get(lead)
            sm = state.mat_rigid.get(sp.mid) if sp is not None else None
            lm = state.mat_rigid.get(lp.mid) if lp is not None else None
            if sm is None or sm.cmo not in (-1.0, 2.0, -2.0):
                continue
            if lm is not None and (lm.cmo, lm.con1, lm.con2) == (
                    sm.cmo, sm.con1, sm.con2):
                continue
            state.warn(
                f"*CONSTRAINED_RIGID_BODIES: part {slave} (mid {sm.mid}, CMO "
                f"{sm.cmo:g} CON1 {sm.con1} CON2 {sm.con2}) is merged into "
                f"part {lead}; the merged /RBODY carries only the lead's "
                "code, so the slave's constraint is NOT written.")

    # *CONSTRAINED_RIGID_BODIES: repoint each merged slave pid at its master's
    # rigid-body info so a *LOAD_RIGID_BODY / *BOUNDARY_PRESCRIBED_MOTION_RIGID /
    # *INITIAL_VELOCITY_RIGID_BODY / TH readout keyed on the slave pid resolves
    # to the surviving master's master node.
    for slave, master in merge_root.items():
        if master in rbody_info:
            rbody_info[slave] = rbody_info[master]

    return lines, rigid_nodes, rbody_info


def _resolve_rigid_body_merges(state: ConversionState, rigid_pids: Set[int],
                               d2r: Optional[Dict[int, int]] = None
                               ) -> Dict[int, int]:
    """*CONSTRAINED_RIGID_BODIES (PIDM, PIDS) pairs → {slave_pid: root_master_pid}.

    Union-find with the master (PIDM) side as the representative, so chained
    merges (A<-B, B<-C) all resolve to the ultimate master A. Only pairs whose
    BOTH parts are RIGID are honoured — a *MAT_RIGID part or a
    *DEFORMABLE_TO_RIGID one, tested on the PART and not on its material,
    because a *DEFORMABLE_TO_RIGID part keeps its own deformable law. Others
    are warned and dropped. The root master itself is not in the returned map
    (it keeps its own /RBODY).

    *DEFORMABLE_TO_RIGID's own ``LRB`` field folds through the SAME union-find:
    Vol I R17 p.18-2 defines it as the "Part ID of the lead rigid body to which
    the part is merged", which is exactly a (master, slave) pair. Measured reach
    of a non-zero LRB on every corpus this converter is checked against: 0
    cards, so the path ships stated rather than validated against a reference."""
    parent: Dict[int, int] = {}

    def find(p: int) -> int:
        parent.setdefault(p, p)
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    pairs: List[Tuple[str, int, int]] = [
        ("*CONSTRAINED_RIGID_BODIES", m, s) for m, s in state.rigid_body_merges]
    pairs += [("*DEFORMABLE_TO_RIGID LRB", lrb, pid)
              for pid, lrb in sorted((d2r or {}).items()) if lrb]
    for kw, pidm, pids in pairs:
        if pidm not in rigid_pids or pids not in rigid_pids:
            state.warn(
                f"{kw} ({pidm},{pids}): both parts must be rigid (a *MAT_RIGID "
                "part or a *DEFORMABLE_TO_RIGID one) to merge into one rigid "
                "body — merge skipped.")
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


def _local_constraint(state: ConversionState, label: str, con1: int,
                      con2: int, t0_cache: Dict[int, int]
                      ) -> Optional[Tuple[str, str, int, List[str], str]]:
    """A CMO = -1 constraint (``*MAT_RIGID`` and the CNRB ``_SPC`` option alike,
    round 8 A1) -> ``(Tra, Rot, skew_ID, extra_lines, frame)``, or None when
    no ``/BCS`` may be written.

    Vol II R17 *MAT_RIGID: with CMO -1, CON1 is the local coordinate system
    ("This coordinate system is fixed in time") and CON2 a six-digit code,
    100000 = x translation ... 000001 = z rotation; LCO plays no part. The
    starter reads the digits as axes of the /BCS skew
    (``radioss51/LOADS/bcs.cfg:98``; ``hm_read_bcs.F:164-172`` resolves the
    skew, ERROR 137 when it is missing; ``:179-185`` refuses a digit >= 2,
    ERROR 1051). So:

      * more than six digits or a digit outside {0, 1} -> None + a warning;
        ``000000`` -> None silently (nothing is constrained);
      * CON1 0 -> the GLOBAL frame (skew 0);
      * a ``*DEFINE_COORDINATE_SYSTEM`` / ``_VECTOR`` -> its own /SKEW/FIX;
      * a ``*DEFINE_COORDINATE_NODES`` FLAG 0 -> its /SKEW/FIX; FLAG 1 (the
        co-rotating /SKEW/MOV) -> a NEW /SKEW/FIX at the t = 0 axes, because
        the manual fixes the CMO -1 frame in time (one per CON1 per producer
        call, ``t0_cache``); missing or collinear nodes -> None + a warning;
      * an undefined CON1 -> None + a warning (ERROR 137 otherwise).

    The skew id of a FLAG-1 frame is drawn AFTER every refusal, so a refused
    card allocates nothing. *frame* names the class for the caller's
    sentence (``global`` / ``SYSTEM`` / ``VECTOR`` / ``NODES FLAG 0`` /
    ``NODES FLAG 1``).
    """
    v = abs(int(con2))
    code = f"{v:06d}"
    if len(code) > 6 or set(code) - {"0", "1"}:
        state.warn(
            f"{label}: CMO -1 CON2 {con2} is not a six-digit 0/1 code "
            "(100000 = x translation ... 000001 = z rotation, Vol II R17 "
            "*MAT_RIGID): the starter refuses a digit >= 2 (ERROR 1051, "
            "hm_read_bcs.F:179-185) and cannot read a seventh - NO /BCS "
            "written, the body is free in every DOF this card meant to fix.")
        return None
    if code == "000000":
        return None
    tra, rot, cid = code[:3], code[3:], int(con1)
    if cid == 0:
        return tra, rot, 0, [], "global"
    if cid in state.coord_sys:
        return tra, rot, cid, [], "SYSTEM"
    if cid in state.coord_vectors:
        return tra, rot, cid, [], "VECTOR"
    cn = state.coord_nodes.get(cid)
    if cn is None:
        state.warn(
            f"{label}: CMO -1 CON1 {cid} names no *DEFINE_COORDINATE_* system "
            "(a /BCS in a missing skew is starter ERROR 137, "
            "hm_read_bcs.F:164-172) - NO /BCS written, the body is free in "
            f"every DOF of CON2 {code}.")
        return None
    from .mesh import _skew_axes_from_nodes
    axes = _skew_axes_from_nodes(state, cn)
    if axes is None:
        state.warn(
            f"{label}: CMO -1 CON1 {cid} is a *DEFINE_COORDINATE_NODES whose "
            f"nodes {cn.n1}/{cn.n2}/{cn.n3} are missing or collinear at t = 0, "
            "so the local frame of CON2 is undefined - NO /BCS written, the "
            f"body is free in every DOF of CON2 {code}.")
        return None
    if cn.flag != 1:
        return tra, rot, cid, [], "NODES FLAG 0"
    sid = t0_cache.get(cid)
    extra: List[str] = []
    if sid is None:
        sid = state.reserve_skew_id(state.next_id())
        origin, X, Y = axes
        extra = _emit_skew_fix(sid, f"SKEW_CON1_T0_{cid}", origin, Y,
                               _vcross(X, Y))
        t0_cache[cid] = sid
    return tra, rot, sid, extra, "NODES FLAG 1"


def _cmo_neg_sentence(label: str, code: str, bc_id: int, tra: str, rot: str,
                      skew: int, ind: int, con1: int, frame: str,
                      cn=None) -> str:
    """W1 / W2 / W3 of round 8 A1: what the CMO -1 card became, with the LS-DYNA
    fact it follows and the measured effect."""
    head = (f"{label}: CMO -1 CON2 {code} written as /BCS/{bc_id} "
            f"'{tra} {rot}'")
    if frame == "global":
        return (
            f"{head} in the GLOBAL frame on the /RBODY main node {ind}: CON1 "
            "is 0. LS-DYNA's d3hsp prints the processed constraint of such a "
            "card as 000000, but its results hold the code "
            "(control_timestep.billet-forge: x-rbv = y-rbv = 0.0 at all 151 "
            "matsum outputs). Before round 8 nothing was written. MEASURED "
            "there (nt 4): IE END -99.97 -> +0.13 %, history RMS 41.95 -> "
            "0.056 % of the LS peak (150 LS blocks 0 < t <= 0.0015, the "
            "last row of a printed time), energy error -24.1 -> -3.7 %, "
            "12501 = 12501 cycles. --no-rigid-local-constraints writes "
            "nothing.")
    if frame == "NODES FLAG 1":
        nodes = f" (nodes {cn.n1}/{cn.n2}/{cn.n3})" if cn is not None else ""
        return (
            f"{head} on the /RBODY main node {ind}: CON1 {con1} is a "
            "*DEFINE_COORDINATE_NODES with FLAG 1 (the co-rotating "
            f"/SKEW/MOV/{con1}), but the CMO -1 frame is fixed in time (Vol "
            "II R17 *MAT_RIGID CON1), so the code is written in a NEW "
            f"/SKEW/FIX/{skew} at that frame's t = 0 axes{nodes}. No corpus "
            "deck carries this case; the rule follows the manual. "
            "--no-rigid-local-constraints writes nothing.")
    return (
        f"{head} in /SKEW/{skew} on the /RBODY main node {ind}: the frame is "
        f"CON1 {con1} ({frame}), not LCO, fixed in time (Vol II R17 "
        "*MAT_RIGID CON1). Before round 8 nothing was written. MEASURED on "
        "mat_rigid.block-slide (nt 4): KE END +100.10 -> +0.05 % (fifths "
        "within 0.05 %), history RMS 44.81 -> 0.006 % of the LS peak (500 "
        "LS blocks 0 < t <= 0.01), 2512 = 2512 cycles; the same code in "
        "the GLOBAL frame stays at +100.10 %. --no-rigid-local-constraints "
        "writes nothing.")


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

    The FLAG-1 /SKEW/FIX lines a CMO < 0 card may need are returned by
    :func:`_resolve_cnrb_spc_lines`, which the producer calls.
    """
    tra, rot, skew, _extra = _resolve_cnrb_spc_lines(state, cnrb, {})
    return tra, rot, skew


def _resolve_cnrb_spc_lines(state: ConversionState, cnrb,
                            t0_cache: Dict[int, int]
                            ) -> Tuple[str, str, int, List[str]]:
    """:func:`_resolve_cnrb_spc` plus the extra lines (round 8, A1).

    With ``--rigid-local-constraints`` (the default) a CMO < 0 card goes
    through :func:`_local_constraint`, the helper the ``*MAT_RIGID`` producer
    shares: a ``*DEFINE_COORDINATE_VECTOR`` CON1 is a real /SKEW/FIX (and
    no warning says otherwise), a FLAG-1 ``*DEFINE_COORDINATE_NODES`` frame
    gets a /SKEW/FIX at its t = 0 axes (CON1 is "fixed in time"), and a code
    with more than six digits or a digit >= 2, an undefined CON1 or a
    degenerate node frame writes NO card (and no record). Without it, the
    4f5b6e8 branch below runs unchanged.
    """
    cmo = cnrb.cmo
    extra: List[str] = []
    if cmo == 0.0:
        return "000", "000", 0, extra
    if cmo > 0.0:
        tra = _con1_to_tra(cnrb.con1)
        rot = _con2_to_rot(cnrb.con2)
        skew = 0
    elif state.options.rigid_local_constraints:
        label = f"*CONSTRAINED_NODAL_RIGID_BODY_SPC pid={cnrb.pid}"
        res = _local_constraint(state, label, cnrb.con1, cnrb.con2, t0_cache)
        if res is None:
            tra, rot, skew = "000", "000", 0
        else:
            tra, rot, skew, extra, frame = res
            if frame == "NODES FLAG 1" and extra:
                cn = state.coord_nodes.get(int(cnrb.con1))
                state.warn(
                    f"{label}: CMO -1 CON1 {cnrb.con1} is a "
                    "*DEFINE_COORDINATE_NODES with FLAG 1 (the co-rotating "
                    f"/SKEW/MOV/{cnrb.con1}), but the CMO -1 frame is fixed in "
                    "time (Vol II R17 *MAT_RIGID CON1), so CON2 "
                    f"{abs(int(cnrb.con2)):06d} is written in a NEW "
                    f"/SKEW/FIX/{skew} at that frame's t = 0 axes"
                    + (f" (nodes {cn.n1}/{cn.n2}/{cn.n3})" if cn else "")
                    + ". No corpus deck carries this case; the rule follows "
                    "the manual. --no-rigid-local-constraints keeps the "
                    "moving skew.")
    else:
        skew = cnrb.con1
        code = f"{abs(cnrb.con2):06d}"[-6:]
        tra, rot = code[0:3], code[3:6]
        # R14 triage round 9, A13: a *DEFINE_COORDINATE_VECTOR CON1 IS a
        # written /SKEW/FIX/<cid> (writer/mesh._synthesize_vector_skews), and
        # the starter accepts it (g3j's coupon: identical bytes to the SYSTEM
        # twin but the titles, VECTOR = SYSTEM to every printed digit) - so
        # only a CON1 in NO registry is named, and with what it costs.
        if (skew and skew not in state.coord_nodes
                and skew not in state.coord_sys
                and skew not in state.coord_vectors):
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY_SPC pid={cnrb.pid}: CON1 "
                f"{skew} names no *DEFINE_COORDINATE_* system: the /BCS "
                "skew_ID is undefined and the starter stops (ERROR 137)."
            )
    if abs(cmo) == 2.0:
        state.warn(
            f"*CONSTRAINED_NODAL_RIGID_BODY_SPC pid={cnrb.pid}: |CMO|=2 "
            "(constraint at XSPC/YSPC/ZSPC or SPCNID) — the offset point is not "
            "applied; the /BCS acts on the rigid body's master node."
        )
    return tra, rot, skew, extra


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
    # one t = 0 /SKEW/FIX per FLAG-1 CON1 in this call (round 8, A1)
    t0_cache: Dict[int, int] = {}

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
    # A TRUSS contributes ONLY (n1, n2): /TRUSS has no third-node column, so a
    # deck-stated N3 on an ELFORM=3 *ELEMENT_BEAM is a node the element does
    # not touch at all. Safe-direction today (an extra node in an "attached"
    # set), wrong in principle — see writer/truss.py.
    truss_pids = _truss_pids(state)
    for e in state.beam_elems:
        if e.pid in truss_pids:
            elem_nodes.update((e.n1, e.n2))
        else:
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
        # round 9, A1: a CNRB that gives way to the rigid PART of its PID
        # leaves the triad to the part's /RBODY (_make_rbodies already took
        # it) - one node in two /RBODY is refused by the starter
        helpers = (None if cnrb.pid in state.cnrb_record_key
                   else state.local_frame_nodes.get(cnrb.pid))
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
        # `inr is not None` is redundant — see the *PART_INERTIA site above:
        # `props` is `_resolve_inertia(...) if inr is not None else None`.
        if props is not None and inr is not None:
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
            "icog": icog,      # see the *MAT_RIGID site for why

        }

        # Optional added mass on the master node / part (same sources as
        # _make_rbodies): *ELEMENT_MASS[_NODE_SET] on the master node and
        # *ELEMENT_MASS_PART[_SET] on this part go into the /RBODY Mass field.
        node_added = state.added_node_masses.get(ind_node, 0.0)
        # round 8, A8: a mass on a SECONDARY node of this body was dropped
        # (neither folded here nor written by _make_added_masses, which
        # skipped every rigid node); it becomes /ADMAS/0 on its node now.
        # An ICoG-4 body keeps every lumped mass out (TM supersedes them).
        state.rbody_folded_mass_nodes.add(ind_node)
        if props is not None:
            state.rbody_folded_mass_nodes.update(secondary_nodes)
        elif state.options.rigid_element_mass_admas:
            for n in secondary_nodes:
                if n != ind_node and state.added_node_masses.get(n, 0.0) > 0:
                    state.rbody_secondary_masses[n] = (cnrb.pid, "dropped")
        # round 9, A1: *ELEMENT_MASS_PART names a PART id; when the CNRB gives
        # way to the rigid part of that id, the part's /RBODY carries the
        # mass (_make_rbodies) and the CNRB none - never counted twice
        part_add, part_fin = ((0.0, 0.0) if cnrb.pid in state.cnrb_record_key
                              else state.element_mass_parts.get(
                                  cnrb.pid, (0.0, 0.0)))
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
        # Jxy Jyz Jxz + Ioptoff Iexpams Ifail; all four required or np>1
        # segfaults). Card 1 and the Ioptoff comment come from the SHARED
        # constants so this producer's shape cannot drift from the other four
        # again.
        # Without _INERTIA, ICoG=0 (=default 1, RefGuide p.1879) MOVES the master
        # node to the computed center of gravity, so a /CLOAD force from
        # *LOAD_RIGID_BODY acts through the CoG as a pure force with no spurious
        # moment — matching LS-DYNA, which likewise relocates PNODE to the center
        # of mass. With _INERTIA, ICoG=4 pins it at the stated centre of mass
        # instead and the mesh contribution is ignored.
        lines += inertia_extra
        state.rbody_ids.add(ind_node)          # producer 2 of 6 (CNRB)
        lines += [
            f"/RBODY/{ind_node}",
            cnrb.title or f"CNRB_{cnrb.pid}",
            _RBODY_CARD1_HDR,
            f"{_i(ind_node)}{_i(0)}{_i(skew_id)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(icog)}{_i(0)}",
        ]
        lines += _inertia_lines(j_vals)
        rbody_info[cnrb.pid]["j"] = tuple(j_vals)     # see the *MAT_RIGID site
        lines += [
            _RBODY_IOPTOFF_HDR,
            f"{_i(0)}{_i(0)}{_i(0)}",
        ]
        lines += _emit_grnod_node(grnod_id, f"cnrb_nodes_pid{cnrb.pid}", secondary_nodes)
        lines += _emit_grnod_node(ind_grnod_id, f"cnrb_indnode_pid{cnrb.pid}", [ind_node])

        # _SPC constraint → /BCS on the master node (global or local skew).
        if cnrb.has_spc:
            tra, rot, skew, extra = _resolve_cnrb_spc_lines(state, cnrb,
                                                            t0_cache)
            if tra != "000" or rot != "000":
                lines += extra            # a FLAG-1 CON1's t = 0 /SKEW/FIX
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
                # reaction consumers read both lists; see CnrbSpcBc. The skew
                # and the title let the *NODE TC/RC pass merge a member code
                # into a skew-0 card (round 7, A1).
                state.cnrb_spc_bcs.append(CnrbSpcBc(
                    bc_id, ind_node, tra, rot, skew=skew,
                    title=f"BC_cnrb_{cnrb.pid}"))

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

    THE GUARD READS BOTH REGISTRIES. ``rbody_info`` alone is not "does this
    deck have a rigid body": producers 4 and 5 (``_make_shell_to_solid_rbodies``
    and ``_make_generalized_weld_butt_rbodies``, both added in round 5) emit a
    real ``/RBODY`` and deliberately do NOT populate that dict — they have no
    LS-DYNA PART id to key it by. An implicit deck whose only rigid body were a
    shell-to-solid tie or a butt weld would otherwise get the probe, its three
    synthesized nodes and its ``/BCS`` on top of a body it already has, under a
    warning claiming it has none. ``state.rbody_ids`` is the set every producer
    registers into, so it is read here too. Reach today is 0 — both new
    carriers are explicit decks — which is why this costs no deck a byte; it is
    the #138 rule (grep every consumer of a flag you add a producer for)
    applied before the case exists.
    """
    if (not state.is_implicit or rbody_info or state.rbody_ids
            or not state.nodes):
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
    # Producer 3 of 6. This one is NOT in rbody_info at all (it is only
    # appended to rbody_lines), so a deck whose only rigid body is the probe
    # would get no /TH/RBODY group if *DATABASE_RBDOUT read that dict instead.
    state.rbody_ids.add(n1)
    lines += [
        f"/RBODY/{n1}",
        "inert_probe_rbody",
        _RBODY_CARD1_HDR,
        f"{_i(n1)}{_i(0)}{_i(0)}{_i(0)}{_f(1e-3)}{_i(slave_grnod)}{_i(0)}{_i(0)}{_i(0)}",
        "#                Jxx                 Jyy                 Jzz",
        f"{_f(1e-3)}{_f(1e-3)}{_f(1e-3)}",
        "#                Jxy                 Jyz                 Jxz",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        _RBODY_IOPTOFF_HDR,
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


# ─────────────────────────────────────────────────────────────────────────────
# *CONSTRAINED_SHELL_TO_SOLID and *CONSTRAINED_GENERALIZED_WELD_BUTT
# ─────────────────────────────────────────────────────────────────────────────

def _bcs_constrained_nodes(state: ConversionState) -> Set[int]:
    """Every node this deck puts a /BCS on, from both sources.

    ``*NODE`` TC/RC (``state.node_tc_rc``, the dome's own symmetry planes) and
    ``*BOUNDARY_SPC_{NODE,SET}`` (``state.bcs_spcs``, resolved through the node
    sets). Used ONLY to say, before the run, which bodies will make the starter
    raise WARNING ID 312 INCOMPATIBLE KINEMATIC CONDITIONS.
    """
    out: Set[int] = {nid for nid, (tc, rc) in state.node_tc_rc.items()
                     if tc or rc}
    # round 6 (B5): *CONSTRAINED_GLOBAL is a second /BCS producer of the same
    # TC/RC pass
    out |= set(state.constrained_global_tc_rc)
    for bc in state.bcs_spcs:
        if not any((bc.dofx, bc.dofy, bc.dofz,
                    bc.dofrx, bc.dofry, bc.dofrz)):
            continue
        entry = state.node_sets.get(bc.nsid)
        if entry is None:
            if bc.nsid in state.nodes:
                out.add(bc.nsid)        # a _NODE card names the node itself
            continue
        out.update(n for n in entry[1] if n > 0)
    return out


def _next_rbody_id(state: ConversionState, preferred: int) -> int:
    """*preferred* if it is free, else a fresh auto id.

    /RBODY has no allocator of its own — its id IS its main node id, the
    convention all three pre-round-5 producers follow and what
    ``writer/output._make_starter_th_rbody`` lists. A duplicate is starter
    ERROR 79, so a collision takes ``next_id()`` instead.
    """
    return preferred if preferred not in state.rbody_ids else state.next_id()


def _coincidence_tolerance(state: ConversionState) -> float:
    """``max(1e-6, 1e-9 * mesh bounding-box diagonal)``.

    Absolute PLUS relative, because the criterion's degeneracy is geometric,
    not unit-dependent: a pair the deck means to be coincident is written at
    identical coordinates, and the only spread to allow for is the deck's own
    print precision, which scales with the model.
    """
    if not state.nodes:
        return 1.0e-6
    xs = [nd.x for nd in state.nodes.values()]
    ys = [nd.y for nd in state.nodes.values()]
    zs = [nd.z for nd in state.nodes.values()]
    diag = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2) ** 0.5
    return max(1.0e-6, 1.0e-9 * diag)


def _warn_shell_to_solid_dropped(state: ConversionState) -> None:
    """--no-shell-to-solid-rbody: say what is lost, once for the deck."""
    n = len(state.shell_to_solids)
    state.note_recognized_not_emitted(
        "CONSTRAINED_SHELL_TO_SOLID",
        "--no-shell-to-solid-rbody: the shell node and its brick fibre are "
        "left UNCONNECTED")
    state.warn(
        f"*CONSTRAINED_SHELL_TO_SOLID: {n} card(s) were NOT converted "
        "(--no-shell-to-solid-rbody). The shell node and the brick fibre it "
        "names are then UNCONNECTED - on constrained.shell_solid.dome that "
        "arm reads IE 0.6693 against LS-DYNA's 642.206 (-99.90 %) and KE "
        "1.290e5 against 1040.33 (+12299.9 %), i.e. the shell simply flies "
        "off the dome. Drop the flag to tie them with an /RBODY.")


def _make_shell_to_solid_rbodies(state: ConversionState) -> List[str]:
    """*CONSTRAINED_SHELL_TO_SOLID -> one /RBODY per card. Producer 4 of 6.

    LS-DYNA names the substitute in the card's own Purpose sentence (Vol I R17
    p.10-182): *"Define a tie between a shell edge and solid elements. Nodal
    rigid bodies can perform the same function and may also be used."* The
    shell node ``NID`` is the main node, the ``NSID`` set is the secondary
    group, and Mass/Inertia stay 0 so Radioss lumps the body from the nodes.

    ``ICoG = 3`` — NOT the reader default 1. ``inirby.F``'s ``ELSEIF(ICDG==3)``
    keeps ``XG(J) = X(J,M)``, i.e. the main node stays where the mesh put it;
    the default MOVES a main node to the computed centre of gravity, which on
    a general fibre displaces a MESHED shell node at t = 0. (The CNRB producer
    synthesizes a free centroid node for exactly that reason — here the main
    node is the card's own, so the flag has to do the work.) MEASURED on
    ``constrained.shell_solid.dome`` at nt 4: ICoG 3 and ICoG blank give the
    same 48190 cycles and the same IE/KE/EXT to four significant figures, so
    the choice costs nothing and removes the hazard.

    THE TIED NODES ARE DELIBERATELY NOT ADDED TO ``rigid_nodes``, and this is
    a MEASURED decision, not an oversight. That set does not mean "a node of
    some rigid body"; it means "a node whose constraints, masses and initial
    velocities must be RE-POINTED to a ``/RBODY`` main node that
    ``rbody_info`` knows", and ``rbody_info`` is keyed by LS-DYNA PART id —
    which a shell-to-solid tie does not have. Registering them anyway sends
    ``_make_node_tc_rc_bcs`` (``writer/loads.py``) down its
    ``main_of.get(nid) is None`` branch: measured on the dome, **12 of the
    deck's 132 stated ``*NODE`` TC/RC constraints were DROPPED** — the
    symmetry conditions on the tied nodes — under a warning that blames a
    ``*CONSTRAINED_RIGID_BODIES`` merge the deck does not contain. Leaving
    them out keeps every constraint the deck states; the redundant ``/BCS``
    then costs a starter WARNING ID 312 at 0 ERRORs, which is what the per-card
    warning below says and what was measured (60 conditions on the dome).

    WHAT THAT CHOICE ALSO COSTS, named rather than left to be found: a tied
    node is invisible to every other consumer of ``rigid_nodes``. The one that
    matters is ``_warn_inivel_on_rigid_members`` (``writer/loads.py``) — an
    ``*INITIAL_VELOCITY`` landing on a tied brick node is emitted with no
    warning that ``inirby.F:1033-1048`` will overwrite it from the body's main
    node at t = 0. Reach is 0 on every corpus here (the dome states no
    ``*INITIAL_VELOCITY``), and the fix, if a carrier ever appears, is a
    SEPARATE set the TC/RC re-point does not read — not registering these nodes
    in ``rigid_nodes``, which is the thing measured to drop 12 constraints.
    """
    cards = state.shell_to_solids
    if not cards:
        return []
    if not state.options.shell_to_solid_rbody:
        _warn_shell_to_solid_dropped(state)
        return []
    constrained = _bcs_constrained_nodes(state)
    lines: List[str] = ["#-  SHELL-TO-SOLID TIES (-> /RBODY):", HDR]
    emitted = False
    for c in cards:
        label = f"*CONSTRAINED_SHELL_TO_SOLID NID={c.nid} NSID={c.nsid}"
        if c.nid <= 0 or c.nid not in state.nodes:
            state.warn(f"{label}: the shell node has no coordinates - tie NOT "
                       "converted.")
            continue
        entry = state.node_sets.get(c.nsid) if c.nsid > 0 else None
        if entry is None:
            state.warn(f"{label}: node set {c.nsid} not found - tie NOT "
                       "converted.")
            continue
        fibre = [n for n in dict.fromkeys(entry[1])
                 if n > 0 and n in state.nodes and n != c.nid]
        if not fibre:
            state.warn(f"{label}: node set {c.nsid} resolves to no usable "
                       "fibre node - tie NOT converted.")
            continue
        if c.nid in entry[1]:
            state.warn(f"{label}: the shell node is ALSO a member of the "
                       "solid node set; it is the /RBODY main node and was "
                       "removed from the secondary group (a body cannot be "
                       "its own secondary).")
        if len(fibre) > 9:
            state.warn(f"{label}: {len(fibre)} fibre nodes - LS-DYNA states "
                       "\"A shell node may be tied to up to nine brick "
                       "nodes\" (Vol I R17 p.10-182). The tie was converted "
                       "anyway; check that the set really is one fibre.")
        rb_id = _next_rbody_id(state, c.nid)
        grnod_id = state.next_grnod_id()
        state.rbody_ids.add(rb_id)          # producer 4 of 6
        lines += [
            f"/RBODY/{rb_id}",
            c.title or f"shell_to_solid_{c.nid}_set{c.nsid}",
            _RBODY_CARD1_HDR,
            f"{_i(c.nid)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}{_i(grnod_id)}"
            f"{_i(0)}{_i(3)}{_i(0)}",
        ]
        lines += _inertia_lines((0.0,) * 6)
        lines += [
            _RBODY_IOPTOFF_HDR,
            f"{_i(0)}{_i(0)}{_i(0)}",
        ]
        lines += _emit_grnod_node(grnod_id,
                                  f"shell_to_solid_fibre_{c.nsid}", fibre)
        emitted = True
        state.warn(
            f"{label}: the shell node is tied to the set's {len(fibre)} fibre "
            f"node(s) by /RBODY/{rb_id} (Mass 0, ICoG 3, Ifail 0) - LS-DYNA's "
            "own Purpose sentence names the substitute (\"Nodal rigid bodies "
            "can perform the same function and may also be used\", Vol I R17 "
            "p.10-182). WHAT IT COSTS: LS-DYNA lets the brick nodes \"move "
            "relative to each other in the fiber direction\" while the shell "
            "node keeps its relative spacing (p.10-183); an /RBODY makes the "
            "whole fibre rigid, so the fibre can no longer stretch. MEASURED "
            "on constrained.shell_solid.dome (7 cards, 5 nodes each, nt 4): "
            "NORMAL 48190 cycles (+0.27 % over the drop arm's 48060), "
            "external work 1.290e5 -> 1689 against LS-DYNA's 1692.55 "
            "(-0.21 %), IE 0.6693 -> 873.9 (-99.90 % -> +36.08 % against "
            "642.206), KE 1.290e5 -> 806.4 (+12299.9 % -> -22.49 % against "
            "1040.33). Pass --no-shell-to-solid-rbody to go back to dropping "
            "the keyword.")
        hits = sorted(n for n in [c.nid] + fibre if n in constrained)
        if hits:
            state.warn(
                f"{label}: {len(hits)} of this body's nodes {hits[:10]}"
                + (" ..." if len(hits) > 10 else "")
                + (" also carry a /BCS from *NODE TC/RC, *CONSTRAINED_GLOBAL "
                   "or *BOUNDARY_SPC_*, so "
                   if any(n in state.constrained_global_tc_rc for n in hits)
                   else " also carry a /BCS from *NODE TC/RC or "
                        "*BOUNDARY_SPC_*, so ")
                + "the starter will raise WARNING ID 312 INCOMPATIBLE "
                  "KINEMATIC CONDITIONS (BOUNDARY CONDITION / RIGID BODY). "
                  "MEASURED on the dome: 60 flagged conditions and 0 ERRORs, "
                  "NORMAL TERMINATION. WHICH of the two conditions Radioss "
                  "keeps was NOT measured here - kinchk.F:944-951 raises 312 "
                  "as a SUMMARY OF POSSIBLE INCOMPATIBLE KINEMATIC CONDITIONS "
                  "and does not say who wins. The RIGID BODY does: MEASURED "
                  "on a purpose-built coupon (a 4-brick column tied to a "
                  "shell strip, one fibre node carrying *NODE TC=7/RC=7, "
                  "nt 2) the tie arm and the SAME deck with that constraint "
                  "DELETED are numerically identical - IE 3613, engine "
                  "energy error -97.9 %, 3252 cycles in both - so the /BCS "
                  "is simply gone; moving that one /BCS onto the rigid "
                  "body's MAIN node instead (ICoG and the member set held "
                  "fixed) reproduces the *CONSTRAINED_NODAL_RIGID_BODY twin "
                  "exactly - IE 707.4, energy error -0.0 %, 2524 cycles - "
                  "and WARNING 312 disappears with it. So the cost is not "
                  "only a lost constraint: it can be the whole answer, at "
                  "0 starter ERRORs and NORMAL TERMINATION on both arms. "
                  "(On the dome itself the same 60 conditions cost -0.5 % of "
                  "energy error, so the range is wide.) Check it if the "
                  "constrained direction is NOT along the fibre.")
    return lines if emitted else []


def _warn_generalized_weld_butt_dropped(state: ConversionState) -> None:
    """--no-generalized-weld-butt: say what is lost, once for the deck."""
    n = len(state.generalized_weld_butts)
    state.note_recognized_not_emitted(
        "CONSTRAINED_GENERALIZED_WELD_BUTT",
        "--no-generalized-weld-butt: the welded node pairs are left "
        "UNCONNECTED")
    state.warn(
        f"*CONSTRAINED_GENERALIZED_WELD_BUTT: {n} card(s) were NOT converted "
        "(--no-generalized-weld-butt). The welded node pairs are then "
        "UNCONNECTED - on constrained.butt-weld that arm reads IE 1.048e-6 "
        "against LS-DYNA's 10974.0 (-100 %), i.e. the plates carry no load at "
        "all. Drop the flag to tie them with an /RBODY whose Ifail criterion "
        "reproduces the weld's own failure force.")


def _make_generalized_weld_butt_rbodies(
        state: ConversionState) -> List[str]:
    """*CONSTRAINED_GENERALIZED_WELD_BUTT -> one /RBODY with Ifail=1 per card.
    Producer 5 of 6.

    LS-DYNA's own model of this weld IS a nodal rigid body: *"When the failure
    time, tf, is reached the nodal rigid body becomes inactive"* (Vol I R17
    p.10-32), and its brittle criterion is
    ``beta*sqrt(sig_n^2 + 3*(tau_n^2 + tau_t^2)) >= sig_f`` with *"The
    component sigma_n is nonzero for tensile values only."*

    ``hm_read_rbody.F:290-300`` reads ``FN FT expN expT`` when ``Ifail == 1``
    and ``rgbodv.F:249-269`` evaluates
    ``(FN/FNmax)^expN + (FT/FTmax)^expT >= 1``, with ``FN`` the TENSILE part of
    the reaction along the main->secondary direction. With ``sig = F/(L*D)``
    the two criteria agree at ``FNmax = SIGY*L*D/BETA``.

    COINCIDENT PAIRS ONLY. ``rgbodv.F:249-256`` takes the direction from the
    main->secondary GEOMETRY: on a coincident pair ``NN = 1/EM20`` and
    ``U = 0``, so ``FN`` is identically 0 and the criterion collapses to
    ``|R| >= FTmax`` — numerically LS-DYNA's ``beta*sig_n >= sig_f`` for an
    axial weld, which is why ``FTmax = FNmax`` and not ``FNmax/sqrt(3)``.
    On an OFFSET pair that vector is an arbitrary geometric offset with no
    relation to the weld normal ``L x D`` defines, so any normal/shear split
    k2rad picked there would be invented — such a pair is refused by name.
    Roster reach of the refusal: 0 cards.
    """
    cards = state.generalized_weld_butts
    if not cards:
        return []
    if not state.options.generalized_weld_butt:
        _warn_generalized_weld_butt_dropped(state)
        return []
    tol = _coincidence_tolerance(state)
    lines: List[str] = ["#-  GENERALIZED BUTT WELDS (-> /RBODY Ifail=1):", HDR]
    emitted = False
    for c in cards:
        label = f"*CONSTRAINED_GENERALIZED_WELD_BUTT NSID={c.nsid}"
        entry = state.node_sets.get(c.nsid)
        if entry is None:
            state.warn(f"{label}: node set not found - weld NOT converted.")
            continue
        pair = [n for n in dict.fromkeys(entry[1])
                if n > 0 and n in state.nodes]
        if len(pair) != 2:
            state.warn(
                f"{label}: the node set resolves to {len(pair)} node(s), and a "
                "BUTT weld is exactly ONE nodal pair (Vol I R17 p.10-32: "
                "\"This requires 3 separate *CONSTRAINED_GENERALIZED_WELD_BUTT "
                "definitions, one for each nodal pair\") - weld NOT "
                "converted.")
            continue
        n1, n2 = pair
        a, b = state.nodes[n1], state.nodes[n2]
        d = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
        if d > tol:
            state.warn(
                f"{label}: the pair {n1}/{n2} is NOT coincident (|dx| = "
                f"{d:.6G} against a tolerance of {tol:.6G}) - weld NOT "
                "converted. Radioss's /RBODY failure criterion takes its "
                "normal direction from the main->secondary vector "
                "(rgbodv.F:249-256), which on an offset pair is a geometric "
                "offset unrelated to the weld normal that L and D define, so "
                "the normal/shear split would be invented. Merge the nodes, "
                "or tie the pair with *CONSTRAINED_SPOTWELD, which k2rad "
                "converts to a force-criterion spring.")
            continue
        beta = c.beta if c.beta > 0.0 else 1.0
        fn_max = 0.0
        if c.sigy > 0.0 and c.length > 0.0 and c.depth > 0.0:
            fn_max = c.sigy * c.length * c.depth / beta
        ifail = 1 if fn_max > 0.0 else 0
        rb_id = _next_rbody_id(state, n1)
        grnod_id = state.next_grnod_id()
        state.rbody_ids.add(rb_id)          # producer 5 of 6
        lines += [
            f"/RBODY/{rb_id}",
            c.title or f"gen_weld_butt_{n1}_{n2}",
            _RBODY_CARD1_HDR,
            f"{_i(n1)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}{_i(grnod_id)}"
            f"{_i(0)}{_i(3)}{_i(0)}",
        ]
        lines += _inertia_lines((0.0,) * 6)
        lines += [
            _RBODY_IOPTOFF_HDR,
            f"{_i(0)}{_i(0)}{_i(ifail)}",
        ]
        if ifail:
            lines += [
                "#                 FN                  FT"
                "                expN                expT",
                f"{_f(fn_max)}{_f(fn_max)}{_f(2.0)}{_f(2.0)}",
            ]
        lines += _emit_grnod_node(grnod_id,
                                  f"gen_weld_butt_secondary_{n2}", [n2])
        emitted = True
        dropped = [nm for nm, v in (("EPSF", c.epsf), ("TFAIL", c.tfail))
                   if v and 0.0 < v < 1e19]
        if c.cid:
            dropped.append("CID")
        if ifail:
            state.warn(
                f"{label} (nodes {n1} & {n2}): converted to /RBODY/{rb_id} "
                f"with Ifail=1, FN = FT = SIGY*L*D/BETA = {c.sigy:g}*"
                f"{c.length:g}*{c.depth:g}/{beta:g} = {fn_max:.6G}, "
                "expN = expT = 2. LS-DYNA's own model of this weld IS a nodal "
                "rigid body (\"When the failure time is reached the nodal "
                "rigid body becomes inactive\", Vol I R17 p.10-32), and its "
                "brittle criterion beta*sqrt(sig_n^2 + 3*(tau_n^2 + tau_t^2)) "
                ">= sig_f maps onto rgbodv.F:267's (FN/FNmax)^expN + "
                "(FT/FTmax)^expT >= 1 with sig = F/(L*D). THE PAIR IS "
                "COINCIDENT, so Radioss takes its normal direction from the "
                "main->secondary geometry (rgbodv.F:249-256) and gets a ZERO "
                "vector: FN is identically 0 and the whole reaction lands in "
                "FT. FT is therefore set to FNmax, not FNmax/sqrt(3) - on an "
                "axial weld that is LS-DYNA's own beta*sig_n >= sig_f, but "
                "the normal/shear DISTINCTION is lost, so a weld that fails "
                "in pure SHEAR fails sqrt(3) late. MEASURED on "
                "constrained.butt-weld (nt 4): NORMAL 2082 cycles (+0.63 % "
                "over the drop arm's 2069), IE 1.048e-6 -> 1.149e4 "
                "(-100.00 % -> +4.70 % against LS-DYNA's 10974.0), KE 4.699 "
                "-> 4.966 (-30.79 % -> -26.85 % against 6.78908). Radioss "
                "sets off the SAME two welds LS-DYNA's own .messag records "
                "(35 & 23 and 37 & 25): the criterion trips at t 1.269e-3 "
                "(cycle 872) against LS-DYNA's own 1.26914e-3 and the bodies "
                "are SET OFF at t 1.272e-3 (cycle 874). The starter echoes "
                "NORMAL FORCE AT FAILURE 5556. / SHEAR FORCE AT FAILURE "
                "5556., and FNmax 5555.556 is 0.099 % below the xl-force "
                "5561.04 that .messag reports at failure. Pass "
                "--no-generalized-weld-butt to go back to dropping the "
                "keyword.")
        else:
            state.warn(
                f"{label} (nodes {n1} & {n2}): converted to /RBODY/{rb_id} as "
                f"an UNBREAKABLE tie (Ifail 0) - SIGY={c.sigy:g}, L="
                f"{c.length:g}, D={c.depth:g} do not give a positive failure "
                "force, and the card's own Default row makes SIGY 1e16 = "
                "\"never fails\" (Vol I R17 p.10-31). Fill SIGY/L/D in if the "
                "weld is meant to break; the same emitted deck with Ifail "
                "forced to 0 reads IE 2.775e4 = +152.87 % and KE 0.9026 = "
                "-86.71 % on constrained.butt-weld, against +4.70 % / "
                "-26.85 % with the failure model, so the criterion is the "
                "load-bearing half.")
        if dropped:
            state.warn(
                f"{label}: {', '.join(dropped)} have no /RBODY slot and were "
                "DROPPED. EPSF is the ductile plastic-strain failure strain, "
                "TFAIL a timed failure and CID the local output system; the "
                "/RBODY Ifail criterion is force-based only "
                "(rgbodv.F:249-269), has no time window and no output frame. "
                "FILTER, WINDOW, NPR and NPRT are force-filtering and "
                "pair-count cells with no equivalent either.")
    return lines if emitted else []


def _make_screw_carriage_rbodies(state: ConversionState,
                                 rbody_info: Dict) -> List[str]:
    """The CARRIAGE of every converted *CONSTRAINED_JOINT_SCREW (R14 triage
    round 7, B2): /RBODY producer 6 of 6.

    The ``/GJOINT/RACK`` node_ID0 must be a node with a mass and an inertia
    (the Lagrange joint refuses a null one, ``lgmini_gj.F:74`` / ``:87``,
    ERROR 535 / 536 - the card's own Mass / Inertia cells do not satisfy it,
    measured in round 5), so the reference is a tiny element-free /RBODY: its
    main node at A's main-node position, two massless element-free
    secondaries ``0.1 x |N1N3|`` off it along the two global axes normal to
    the screw axis (in increasing order - a stated geometric convention),
    Mass 1e-6, J 1e-6 x 3, ICoG 3 (the centre of gravity at the main node,
    ``radioss2021/RBODY/rbody.cfg:135-139``). The three nodes are drawn from
    ``state.next_node_id()`` and registered in ``state.nodes`` BEFORE the
    /NODE section is written. Registered in ``state.rbody_ids`` (the #106
    register) but NOT in ``rbody_info`` / ``rigid_nodes`` - producers 4 and
    5's rule: a carriage has no LS-DYNA PART id. Appended after the probe
    body; the joint section (``writer/joint_screw._make_joint_screws``)
    reads the node ids from the plan."""
    from .joint_screw import _CARRIAGE_MASS, _CARRIAGE_OFFSET
    lines: List[str] = []
    for plan in state.joint_screw_plan or []:
        info_a = rbody_info.get(plan.a_pid)
        info_b = rbody_info.get(plan.b_pid)
        if info_a is None or info_b is None:      # the plan checked both
            continue
        plan.a_main = info_a["ind_node"]
        plan.b_main = info_b["ind_node"]
        plan.a_ind_grnod = info_a["ind_grnod_id"]
        p = state.nodes[plan.a_main]
        off = _CARRIAGE_OFFSET * plan.length
        others = [i for i in range(3) if i != plan.axis]
        ids: List[int] = []
        for dx in ((0.0, 0.0, 0.0),
                   tuple(off if i == others[0] else 0.0 for i in range(3)),
                   tuple(off if i == others[1] else 0.0 for i in range(3))):
            nid = state.next_node_id()
            state.nodes[nid] = NodeData(p.x + dx[0], p.y + dx[1], p.z + dx[2])
            ids.append(nid)
        plan.n0, plan.n1, plan.n2 = ids
        g_car = state.next_grnod_id()
        jid = plan.screw.jid
        state.rbody_ids.add(plan.n0)          # producer 6 of 6 (carriage)
        lines += [
            f"/RBODY/{plan.n0}",
            f"SCREW_{jid}_CARRIAGE",
            _RBODY_CARD1_HDR,
            f"{_i(plan.n0)}{_i(0)}{_i(0)}{_i(0)}{_f(_CARRIAGE_MASS)}"
            f"{_i(g_car)}{_i(0)}{_i(3)}{_i(0)}",
        ]
        lines += _inertia_lines((_CARRIAGE_MASS, _CARRIAGE_MASS,
                                 _CARRIAGE_MASS, 0.0, 0.0, 0.0))
        lines += [_RBODY_IOPTOFF_HDR, f"{_i(0)}{_i(0)}{_i(0)}", HDR]
        lines += _emit_grnod_node(g_car, f"SCREW_{jid}_carriage_secondaries",
                                  [plan.n1, plan.n2])
    return lines
