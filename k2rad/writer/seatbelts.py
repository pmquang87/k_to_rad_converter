"""
k2rad.writer.seatbelts  –  the *ELEMENT_SEATBELT* restraint chain.

    *ELEMENT_SEATBELT (1D)          -> /SPRING on /PROP/TYPE23 + /MAT/LAW114
    *ELEMENT_SEATBELT (2D, N3/N4)   -> /SHELL  on /PROP/TYPE9  + /MAT/LAW119
    *SECTION_SEATBELT               -> /PROP/TYPE23 (SPR_MAT)
    *MAT_SEATBELT / *MAT_B01 (+_2D) -> /MAT/LAW114 or /MAT/LAW119
    *ELEMENT_SEATBELT_SLIPRING      -> /SLIPRING/SPRING or /SLIPRING/SHELL
    *ELEMENT_SEATBELT_RETRACTOR     -> /RETRACTOR/SPRING
    *ELEMENT_SEATBELT_PRETENSIONER  -> the retractor's card 3
    *ELEMENT_SEATBELT_SENSOR        -> /SENSOR/ACCE | /SENSOR/TIME | /SENSOR/DIST
    *ELEMENT_SEATBELT_ACCELEROMETER -> /ACCEL + /SKEW/MOV + /ADMAS
    *DATABASE_SBTOUT                -> /TH/SLIPRING + /TH/RETRACTOR (output.py)

Its own module, beside ``dbeam.py`` / ``fabric.py``, because the whole chain is
ONE decision: the belt element, its property and its material are inseparable
(``/MAT/LAW114`` is a SPRING law that only exists on ``/PROP/TYPE23`` — a
``/PART`` naming it on any other property is starter ERROR 179/1715,
``hm_read_part.F``), and the four devices are all defined BY ELEMENT ID against
the springs this module writes.

The physics, in one place, because every mapping decision below turns on it
(``redef_seatbelt.F90`` via ``elements/spring/r23l114def3.F:508``)::

    eps = (L - L0) / max(L0, LMIN)                        r23l114def3.F:366
    F   = Fscale * f_load(eps / Xscale) + C * d(eps)/dt   redef_seatbelt.F90:459,540

so the curve's abscissa is ENGINEERING STRAIN and its ordinate is FORCE — the
starter names it on the listing itself, ``FORCE-ENGINEERING STRAIN CURVE``.
That is exactly what LS-DYNA's LLCID/ULCID are ("the points of which are
(Strain, Force). Strain is defined as engineering strain"), so **no abscissa or
ordinate transform is performed, and none is required**. This is the one place
in k2rad where a curve crosses between two solvers untouched, and it is worth
saying out loud: it is a measured fact, not an omission.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

from ..state import (ConversionState, MatSeatbelt, SeatbeltElem,
                     SeatbeltSensor)
from .common import (HDR, _emit_grnod_node, _f, _i, _seatbelt_2d_part_ids,
                     _seatbelt_mat_law, _seatbelt_part_ids)

__all__ = [
    "_seatbelt_mat_law",
    "_seatbelt_part_ids",
    "_seatbelt_2d_part_ids",
    "_assign_seatbelt_props",
    "_split_device_anchor_nodes",
    "_make_seatbelts",
    "_make_seatbelt_2d_materials",
    "_emit_seatbelt_2d_props",
    "_emit_prop_type23",
    "_emit_mat_law114",
    "_emit_mat_law119",
]


# ─────────────────────────────────────────────────────────────────────────────
# Routing: which law, which parts
# ─────────────────────────────────────────────────────────────────────────────

def _split_device_anchor_nodes(state: ConversionState) -> None:
    """Give every slipring and retractor an anchorage node OFF the belt.

    **The rule LS-DYNA states but does not enforce, and Radioss enforces with
    a hard error.**

    Both manuals ask for the same topology. Vol I
    *ELEMENT_SEATBELT_SLIPRING, Remark 1: "The two elements must have a common
    node COINCIDENT WITH the slip ring node ... belt elements should not be
    connected to this node directly"; *ELEMENT_SEATBELT_RETRACTOR, Remark 1:
    "Do not connect belt elements to this node directly. ... The mouth element
    should have a node coincident with the retractor". So the device node is
    NOT supposed to be a node of the belt in LS-DYNA either — but LS-DYNA
    accepts a deck that shares it, and real decks (and dyna2rad's output on
    them) do. Radioss refuses that outright —
    ``hm_read_retractor.F:341-345``::

        IF (RETRACTOR(I)%NODE(2) == RETRACTOR(I)%ANCHOR_NODE) THEN
          CALL ANCMSG(MSGID=2030, MSGTYPE=MSGERROR, ...)

    (``ERROR 2030 ANCHORAGE NODE ID=n CANNOT BE ON THE SEATBELT``; the slipring
    has the same rule as ``ERROR 2029``, plus ``ERROR 2004`` if the two are not
    coincident). MEASURED: copying ``SBRNID`` straight through — which is
    exactly what dyna2rad does, ``convertelements.cxx:862``
    ``CopyValue(*sel, radRetractorEdit, "SBRNID", "Node_ID")`` — gives
    ``ERROR TERMINATION / 1 ERROR(S) / --- SEATBELTS`` on the very first probe
    deck built from a faithful LS-DYNA belt.

    So the belt gets a NEW node at the same coordinates and the ORIGINAL keeps
    its id and every structural attachment it has (the rigid body, the /BCS,
    the seat-frame shells). That direction and not the other one: the anchorage
    is the thing bolted to the car, and a brand-new node has nothing holding
    it, so anchoring to a fresh node would let the whole belt drift.

    Nothing else has to constrain the new node. The device imposes the tie
    itself, as a KINEMATIC CONDITION — ``kine_seatbelt_force.F:112-127`` adds
    the mouth node's whole force and stiffness onto the anchor and then ZEROES
    the mouth node's acceleration, and ``kine_seatbelt_vel.F:188-190`` sets its
    velocity to the anchor's plus the material flow along the strand. That is
    precisely the LS-DYNA behaviour Remark 1 describes ("its motion will
    automatically be constrained to follow the slip ring node") — and it is
    also why the anchorage must NOT be pinned by the implicit free-node guard
    (``loads._make_free_node_constraints``): it receives the belt's force and
    stiffness every cycle.

    Runs in the build_starter prepass, before the /NODE block is written and
    before ``_make_seatbelts`` writes the /SPRING rows that carry the ids.
    """
    if not (state.seatbelt_sliprings or state.seatbelt_retractors):
        return
    by_eid = {e.eid: e for e in state.seatbelt_elems}
    # How many belt elements touch each node: replacing a node in the device's
    # own elements is safe only while no OTHER belt element shares it, or the
    # webbing chain would be cut at that point.
    touch: Dict[int, int] = {}
    for e in state.seatbelt_elems:
        for n in (e.n1, e.n2, e.n3, e.n4):
            if n > 0:
                touch[n] = touch.get(n, 0) + 1
    split: List[str] = []
    unsafe: List[str] = []

    def _twin(node: int) -> Optional[int]:
        nd = state.nodes.get(node)
        if nd is None:
            return None
        from ..state import NodeData
        nid = state.next_node_id()
        state.nodes[nid] = NodeData(nd.x, nd.y, nd.z)
        return nid

    for r in sorted(state.seatbelt_retractors, key=lambda x: x.sbrid):
        e = by_eid.get(r.sbid)
        if e is None or r.sbrnid <= 0 or r.sbrnid not in state.nodes:
            continue
        if r.sbrnid not in (e.n1, e.n2):
            continue                      # already a separate node - nothing to do
        if touch.get(r.sbrnid, 0) > 1:
            unsafe.append(
                f"retractor {r.sbrid} (node {r.sbrnid} is shared by "
                f"{touch[r.sbrnid]} belt elements)")
            continue
        nid = _twin(r.sbrnid)
        if nid is None:
            continue
        if e.n1 == r.sbrnid:
            e.n1 = nid
        else:
            e.n2 = nid
        split.append(f"retractor {r.sbrid}: element {e.eid} node "
                     f"{r.sbrnid} -> {nid}")

    for s in sorted(state.seatbelt_sliprings, key=lambda x: x.sbsrid):
        e1, e2 = by_eid.get(s.sbid1), by_eid.get(s.sbid2)
        if e1 is None or e2 is None or s.sbrnid <= 0 \
                or s.sbrnid not in state.nodes:
            continue
        shared = {e1.n1, e1.n2} & {e2.n1, e2.n2}
        if s.sbrnid not in shared:
            continue                      # already a separate node
        if touch.get(s.sbrnid, 0) > 2:
            unsafe.append(
                f"slipring {s.sbsrid} (node {s.sbrnid} is shared by "
                f"{touch[s.sbrnid]} belt elements, not just the ring's two)")
            continue
        nid = _twin(s.sbrnid)
        if nid is None:
            continue
        for e in (e1, e2):
            if e.n1 == s.sbrnid:
                e.n1 = nid
            if e.n2 == s.sbrnid:
                e.n2 = nid
        split.append(f"slipring {s.sbsrid}: elements {s.sbid1}/{s.sbid2} node "
                     f"{s.sbrnid} -> {nid}")

    if split:
        state.warn(
            f"SEATBELTS: {len(split)} device node(s) were SPLIT so the "
            "anchorage node is not on the belt — "
            + "; ".join(split[:6]) + (" ..." if len(split) > 6 else "")
            + ". LS-DYNA lets the device node BE a belt node; Radioss requires "
            "a separate node at the same coordinates and refuses the deck "
            "otherwise (ERROR 2030 ANCHORAGE NODE CANNOT BE ON THE SEATBELT, "
            "hm_read_retractor.F:341; ERROR 2029/2004 for a slipring). The "
            "ORIGINAL node keeps its id and every attachment it has and stays "
            "the anchorage; the BELT gets the new one. Nothing else "
            "constrains it — the device ties the two together itself "
            "(kine_seatbelt_force.F:112-127 moves the belt node's force and "
            "stiffness onto the anchor and zeroes its acceleration), which is "
            "exactly what the shared node expressed. dyna2rad copies SBRNID "
            "straight through (convertelements.cxx:862) and the deck does not "
            "start.")
    if unsafe:
        state.warn(
            "SEATBELTS: the anchorage node of "
            + "; ".join(unsafe[:6]) + (" ..." if len(unsafe) > 6 else "")
            + " could NOT be split off the belt, because splitting it would "
            "cut the webbing chain at that node — more belt elements meet "
            "there than the device names. The node is written as the "
            "anchorage unchanged and the starter will answer ERROR 2030 "
            "(retractor) or ERROR 2029 (slipring). Remesh so the device's "
            "elements meet at a node of their own.")


def _assign_seatbelt_props(state: ConversionState) -> None:
    """build_starter prepass: one synthesized ``/PROP/TYPE9`` id per 2D belt
    part, the 2D belt elements folded into ``state.shell_elems``, and the
    device anchorage nodes split off the belt.

    Three jobs, all of which have to happen before the mesh is written:

    * A ``*ELEMENT_SEATBELT`` with N3 and N4 set IS a four-node shell
      (``convertelements.cxx:88-91`` builds ``/SHELL`` from exactly those four
      nodes in that order), and everything downstream of the mesh writer —
      the element block, ``shell_elem_ids``, the contact scoping, the /TH
      screen — reads ``state.shell_elems``. Folding it in here rather than
      teaching six writers about a second shell container is the same move
      ``_screen_provisional_elements`` makes for the ambiguous ``*ELEMENT_``
      blocks.
    * The property claim, in the shape ``_assign_fabric_props`` established.
      Runs BEFORE it and before ``_assign_composite_props`` /
      ``_assign_ortho_props`` / ``_assign_hourglass_props``, all of which skip
      a part already claimed — a belt part must not also receive a composite
      layup or an hourglass overlay, because LAW119 accepts exactly one
      property class.
    * The device anchorage split, :func:`_split_device_anchor_nodes` - it
      RENUMBERS a node on a belt element, so it must run before the /SPRING
      rows and before the /NODE block that carries the new node.
    """
    from ..state import ShellElem
    if state.seatbelt_elems:
        known = {e.eid: e.pid for e in state.shell_elems}
        clash: List[str] = []
        for e in state.seatbelt_elems:
            if not e.is_2d:
                continue
            if e.eid in known:
                clash.append(f"{e.eid} (part {e.pid}, taken by *ELEMENT_SHELL "
                             f"on part {known[e.eid]})")
                continue
            state.shell_elems.append(
                ShellElem(e.eid, e.pid, [e.n1, e.n2, e.n3, e.n4]))
        if clash:
            # Never silently: *ELEMENT_SEATBELT and *ELEMENT_SHELL are separate
            # LS-DYNA id namespaces that both land on /SHELL, so a collision is
            # legal upstream and a lost element here. Reported in the shape
            # loads.py::_spring_eid_families uses for the /SPRING namespaces.
            state.warn(
                f"*ELEMENT_SEATBELT: {len(clash)} 2D (shell) belt element(s) "
                "carry an EID an *ELEMENT_SHELL already uses — "
                + "; ".join(clash[:6])
                + (" ..." if len(clash) > 6 else "")
                + ". The two are separate LS-DYNA id namespaces but both "
                "become /SHELL, where one id is one element, so the belt "
                "element is DROPPED: that strip of webbing carries no force "
                "and its /TH channel is lost. Renumber the belt elements.")
    for pid in sorted(_seatbelt_2d_part_ids(state)):
        if pid in state.seatbelt_prop_ids:
            continue
        state.seatbelt_prop_ids[pid] = state.next_prop_id()
    _split_device_anchor_nodes(state)


# ─────────────────────────────────────────────────────────────────────────────
# Card emitters
# ─────────────────────────────────────────────────────────────────────────────

def _emit_prop_type23(prop_id: int, title: str, area: float,
                      inertia: float = 0.0, skew_id: int = 0,
                      sens_id: int = 0, isflag: int = 0) -> List[str]:
    """/PROP/TYPE23 (SPR_MAT) — ``prop_p23_SPR_MAT.cfg FORMAT(radioss2020)``,
    the newest TYPE23 reader format at or below /BEGIN-2022::

        CARD("%10d          %20lg%20lg%10d%10d%10d",
             Imass, CELL_COND(if(Imass==1) AREA; else Volume;),
             INERTIA, SKEW_CSID, ISENSOR, ISFLAG)

    Note the TEN LITERAL BLANK COLUMNS at 11-20 — the card has six values in
    what looks like a seven-cell grid, and writing the area at columns 11-30
    puts an ``Imass`` of 0 next to a ``Volume`` the reader never sees.

    ``Imass`` is written as 1 (AREA) ALWAYS, and that is a deliberate deviation
    from dyna2rad, which writes 2 (Volume) whenever the material states no
    cross-section (``convertprops.cxx:2549``). It costs nothing numerically:
    ``rinit3.F:331-334`` and ``:453-456`` force ``IMASS = 1`` for ``MTN == 114``
    regardless, so the mass is ``GEO(1)*LENGTH*RHO`` either way — MEASURED on a
    twin probe deck differing only in that cell, total mass, total inertia and
    every element and nodal time step came out bit-identical and only the echo
    label changed (``SPRING VOLUME`` vs ``SPRING AREA``). Writing 2 therefore
    makes the starter listing state a volume for a number that is an area,
    which is a lie in the one artefact an engineer reads to check the model.

    ``Inertia`` (columns 41-60) is written but INERT for LAW114 as well:
    ``rinit3.F:470`` recomputes it from the material's ``I``/``J``/``R`` as
    ``UINER = max(1e-20, R*max(rho*A*L^3/12 + rho*J*L, rho*I*L))``. GEO(2) is
    only read by LAW108/113.
    """
    return [
        f"/PROP/TYPE23/{prop_id}",
        title,
        "#    Imass                   Volume/Area             Inertia"
        "   skew_ID   sens_ID    Isflag",
        f"{_i(1)}{' ' * 10}{_f(area)}{_f(inertia)}"
        f"{_i(skew_id)}{_i(sens_id)}{_i(isflag)}",
        HDR,
    ]


def _emit_mat_law114(mat_id: int, title: str, rho: float, lmin: float,
                     k: float, c: float, fct_load: int, fct_uload: int,
                     xscale: float, fscale: float, e: float, ibend: float,
                     itors: float, fmax: float, mmax: float,
                     shear_area: float, rfac: float) -> List[str]:
    """/MAT/LAW114 (SPR_SEATBELT) — ``mat114_spr_seatbelt.cfg
    FORMAT(radioss2022)``, five cards.

    ``RHO_I`` is a DENSITY here (the cfg declares ``SCALAR(MAT_RHO)
    {DIMENSION="density";}``), unlike LAW119's, which is a lineic mass. The
    mass a spring gets is ``GEO(1) * max(L0, LMIN) * RHO`` (``rinit3.F:464,
    474``), so ``rho * area`` must equal the deck's MPUL — see
    :func:`_seatbelt_1d_mass` for which of the two carries it.

    ``K`` (STIFF1) is a force per unit ENGINEERING STRAIN, not a force per unit
    length, because the strain the engine forms is already dimensionless
    (``redef_seatbelt.F90:162`` ``dx(i)=dx(i)/xl0(i)``). Leaving it 0 is the
    safe choice and what this writer does: ``law114_upd.F:80,126`` then raises
    it to ``max(slope)/Xscale`` over both curves — the exact tangent — and a
    non-zero input that is too small only earns WARNING 1640 and gets
    overwritten anyway.
    """
    return [
        f"/MAT/LAW114/{mat_id}",
        title,
        "#              RHO_I                LMIN",
        f"{_f(rho)}{_f(lmin)}",
        "#                  K                   C",
        f"{_f(k)}{_f(c)}",
        "# fct_load fct_uload              Xscale              Fscale",
        f"{_i(fct_load)}{_i(fct_uload)}{_f(xscale)}{_f(fscale)}",
        "#                  E                   I                   J"
        "                FMAX                MMAX",
        f"{_f(e)}{_f(ibend)}{_f(itors)}{_f(fmax)}{_f(mmax)}",
        "#                 AS                   R",
        f"{_f(shear_area)}{_f(rfac)}",
        HDR,
    ]


def _emit_mat_law119(mat_id: int, title: str, rho: float, lmin: float,
                     k: float, c: float, re: float, fct_load: int,
                     fct_uload: int, fscale1: float, fscale2: float,
                     ireload: int, e22: float, nu12: float, g12: float,
                     fscale22: float, ecoat: float, nucoat: float,
                     tcoat: float) -> List[str]:
    """/MAT/LAW119 (SH_SEATBELT) — ``mat119_sh_seatbelt.cfg
    FORMAT(radioss2022)``, five cards.

    ``RHO_I`` is a MASS PER UNIT LENGTH here, not a density — the cfg declares
    ``SCALAR(MAT_RHO){DIMENSION="lineic_mass";}`` and the starter echoes it as
    ``MASS PER UNIT LENGTH``, then divides by the belt SECTION it computes
    itself (``create_seatbelt.F:894`` ``RHO0=PM(1,MID)/SECTION_MAT(MID)``). So
    ``MPUL`` goes in unchanged, and this is the ONE place in the chain where a
    lineic mass is the right thing to write into a density-named cell.

    Three cells are RESCALED INSIDE the reader and must be pre-divided here or
    the deck states something else than it means:
    ``Fscale1``/``Fscale2`` are multiplied by 0.01 and ``Fscale22`` by 100
    (measured on a probe: an input 1.75 echoes as 1.75e-2, an input 0.02 as
    2.0). ``Fscale22`` in particular is a transverse stiffness RATIO after that
    ×100, and it also sets ``N21 = N12 * 100 * Fscale22``
    (``create_seatbelt.F:903``) — see :func:`_seatbelt_2d_weft` for the
    determinant constraint that follows.
    """
    return [
        f"/MAT/LAW119/{mat_id}",
        title,
        "#              RHO_I                LMIN",
        f"{_f(rho)}{_f(lmin)}",
        "#                  K                   C                  RE",
        f"{_f(k)}{_f(c)}{_f(re)}",
        "# fct_load fct_uload             Fscale1             Fscale2   Ireload",
        f"{_i(fct_load)}{_i(fct_uload)}{_f(fscale1)}{_f(fscale2)}{_i(ireload)}",
        "#                E22                 V12                 G12"
        "            Fscale22",
        f"{_f(e22)}{_f(nu12)}{_f(g12)}{_f(fscale22)}",
        "#                 EC                  VC                  TC",
        f"{_f(ecoat)}{_f(nucoat)}{_f(tcoat)}",
        HDR,
    ]


def _emit_slipring(slip_id: int, title: str, shell: bool, el1: int, el2: int,
                   node: int, node2: int, sens_id: int, flow_flag: int,
                   a: float, ed_factor: float, fct1: int, fct2: int,
                   fricd: float, fct3: int, fct4: int,
                   frics: float) -> List[str]:
    """/SLIPRING/SPRING or /SLIPRING/SHELL — ``slipring.cfg`` /
    ``slipring_shell.cfg``, both ``FORMAT(radioss2022)``, three cards.

    The SHELL card 1 has ONE FIELD FEWER: there is no ``Node_ID2``
    (orientation node) at all, so ``Sens_ID`` sits at columns 31-40 instead of
    41-50 and every later cell shifts left by ten. Cards 2 and 3 are
    byte-identical between the two.

    Cards 2 and 3 put the ORDINATE scale BEFORE the abscissa scale —
    ``Fct_ID1 Fct_ID2 Fricd Xscale1 Yscale2 Xscale2`` — while the starter's
    echo prints them the other way round (``FUNC1 ABCISSA``, ``FUNC2
    ORDINATE``, ``FUNC2 ABCISSA``). Reading the echo as the card order swaps
    the scale of the normal-force friction curve with its abscissa.

    All four scale cells are left 0 on purpose: ``hm_read_slipring.F:168-190``
    then supplies the unit-consistent defaults (``IF (IFUNC(1)>0) { IF
    (FRICD==0) FRICD=1; IF (XSCALE1==0) XSCALE1=1*unit; }`` and the three
    mirrors), which is the only way to get a dimensioned default right without
    knowing the deck's unit system.
    """
    head = (f"/SLIPRING/{'SHELL' if shell else 'SPRING'}/{slip_id}", title)
    if shell:
        card1 = ("#  EL_SET1   EL_SET2  Node_SET   Sens_ID Flow_flag"
                 "                   A           Ed_factor",
                 f"{_i(el1)}{_i(el2)}{_i(node)}{_i(sens_id)}"
                 f"{_i(flow_flag)}{_f(a)}{_f(ed_factor)}")
    else:
        card1 = ("#   El1_ID    El2_ID   Node_ID  Node_ID2   Sens_ID Flow_flag"
                 "                   A           Ed_factor",
                 f"{_i(el1)}{_i(el2)}{_i(node)}{_i(node2)}{_i(sens_id)}"
                 f"{_i(flow_flag)}{_f(a)}{_f(ed_factor)}")
    return [
        head[0], head[1], card1[0], card1[1],
        "#  Fct_ID1   Fct_ID2               Fricd             Xscale1"
        "             Yscale2             Xscale2",
        f"{_i(fct1)}{_i(fct2)}{_f(fricd)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#  Fct_ID3   Fct_ID4               Frics             Xscale3"
        "             Yscale4             Xscale4",
        f"{_i(fct3)}{_i(fct4)}{_f(frics)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_retractor(ret_id: int, title: str, el_id: int, node_id: int,
                    elem_size: float, sens_id1: int, pullout: float,
                    fct1: int, fct2: int, sens_id2: int, tens_typ: int,
                    force: float, fct3: int) -> List[str]:
    """/RETRACTOR/SPRING — ``retractor.cfg FORMAT(radioss2022)``, three cards.

    Cards 2 and 3 put the ORDINATE scale before the abscissa scale, like the
    slipring's; both are left 0 so ``hm_read_retractor.F:180-192`` supplies the
    unit-consistent defaults, and so that ``IF (IFUNC(2)==0) IFUNC(2)=IFUNC(1)``
    and ``IF (FORCE==0) FORCE=EP30`` (``:198``) keep their meaning.

    There is NO ``Tdel`` field on this card. Locking happens in the SAME cycle
    the lock sensor's ``TSTART`` is passed (``material_flow.F:695-702``), gated
    only by ``LOCK_PULL >= Pullout`` — so LS-DYNA's ``TDEL`` has to be folded
    into the SENSOR's own ``Tdelay``, which is what
    :func:`_resolve_retractor_sensor` does.
    """
    return [
        f"/RETRACTOR/SPRING/{ret_id}",
        title,
        "#    EL_ID   Node_ID           Elem_size",
        f"{_i(el_id)}{_i(node_id)}{_f(elem_size)}",
        "# Sens_ID1             Pullout   Fct_ID1   Fct_ID2"
        "             Yscale1             Xscale1",
        f"{_i(sens_id1)}{_f(pullout)}{_i(fct1)}{_i(fct2)}{_f(0.0)}{_f(0.0)}",
        "# Sens_ID2  Tens_typ               Force   Fct_ID3"
        "             Yscale2             Xscale2",
        f"{_i(sens_id2)}{_i(tens_typ)}{_f(force)}{_i(fct3)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_sensor_acce(sens_id: int, title: str, tdelay: float, accel_id: int,
                      direction: str, tomin: float, tmin: float) -> List[str]:
    """/SENSOR/ACCE — ``sensor_acce.cfg FORMAT(radioss2020)``, three cards.

    ``Nacc`` is its own card (a count, up to six accelerometer rows may
    follow); one row is written here because an ``*ELEMENT_SEATBELT_SENSOR`` of
    SBSTYP 1 watches exactly one node in one DOF.

    ``dir`` is a right-justified STRING cell, not an integer — ``%10s`` — and
    the legal values are ``X | Y | Z | XY | YZ | ZX | XYZ``. The starter echoes
    it back as an integer (``DIRECTION = 2``), which is why writing ``2`` there
    looks plausible and is not read at all.
    """
    return [
        f"/SENSOR/ACCE/{sens_id}",
        title,
        "#             Tdelay",
        f"{_f(tdelay)}",
        "#     Nacc",
        f"{_i(1)}",
        "# accel_ID       dir               Tomin                Tmin",
        f"{_i(accel_id)}{direction.rjust(10)}{_f(tomin)}{_f(tmin)}",
        HDR,
    ]


def _emit_sensor_dist(sens_id: int, title: str, tdelay: float, n1: int,
                      n2: int, dmin: float, dmax: float) -> List[str]:
    """/SENSOR/DIST — ``sensor_dist.cfg FORMAT(radioss2022)``, two cards.

    The 2022 card is WIDER than the 2021 one: ``Tmin`` (cols 61-80) and
    ``Dflag`` (81-90) exist only from 2022. Both are written 0 — ``Tmin`` is a
    minimum duration LS-DYNA's sensor has no equivalent for, and ``Dflag``
    selects deactivation-instead-of-activation, which a belt sensor never
    wants.
    """
    return [
        f"/SENSOR/DIST/{sens_id}",
        title,
        "#             Tdelay",
        f"{_f(tdelay)}",
        "# node_ID1  node_ID2                Dmin                Dmax"
        "                Tmin     Dflag",
        f"{_i(n1)}{_i(n2)}{_f(dmin)}{_f(dmax)}{_f(0.0)}{_i(0)}",
        HDR,
    ]


def _emit_sensor_or(sens_id: int, title: str, s1: int, s2: int) -> List[str]:
    """/SENSOR/OR — ``sensor_sens_and_or.cfg FORMAT(radioss2020)``, two cards.

    Exactly TWO inputs (``IPARAM(1)``/``IPARAM(2)``, ``sensor_or.F:75-78``), so
    three or four LS-DYNA sensors need a CHAIN of these.

    ``Tdelay`` is on the card but the engine never reads it — ``sensor_or.F``
    sets ``TSTART = TT`` at activation with no reference to it — which is
    precisely why the delay is folded into the LEAVES rather than here.
    """
    return [
        f"/SENSOR/OR/{sens_id}",
        title,
        "#             Tdelay",
        f"{_f(0.0)}",
        "# sens_ID1  sens_ID2",
        f"{_i(s1)}{_i(s2)}",
        HDR,
    ]


def _emit_accel(accel_id: int, title: str, node: int, skew_id: int,
                fcut: float = 0.0) -> List[str]:
    """/ACCEL — ``radioss110/ACCEL/accel.cfg FORMAT(radioss51)``::

        CARD("%10d%10d%10s%20lg", nodeid, skewid, _BLANK_, cutoff)

    Ten literal BLANK columns at 21-30 before ``Fcut``, the same column-grid
    trap ``/PROP/TYPE23`` and ``/PLOAD`` carry. ``Fcut`` is a 4-pole
    Butterworth corner frequency and is left 0 (no filter): LS-DYNA's
    accelerometer does not filter either, and inventing a corner frequency
    would change every channel the deck asks for.
    """
    return [
        f"/ACCEL/{accel_id}",
        title,
        "#     Node     Iskew                          Fcut",
        f"{_i(node)}{_i(skew_id)}{' ' * 10}{_f(fcut)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 1D belt: mass split, curves, LMIN geometry checks
# ─────────────────────────────────────────────────────────────────────────────

def _seatbelt_1d_mass(mat: MatSeatbelt) -> Tuple[float, float]:
    """``(RHO_I, Area)`` for a 1D belt, such that ``RHO_I * Area == MPUL``.

    The engine's mass is ``GEO(1) * max(L0, LMIN) * RHO`` (``rinit3.F:464,
    474``), so the product is the only thing that decides the belt's mass and
    the SPLIT decides everything else the area touches — the compression
    stiffness ``XK_COMP = E * AREA`` (``r23l114def3.F:224``) and, through it,
    the element time step.

    So the area has to be the belt's real CROSS-SECTION whenever the deck
    states one. That is ``*MAT_SEATBELT``'s card-2 ``A`` — the cross-sectional
    area of the optional beam/bending model — and NOT ``*SECTION_SEATBELT``'s
    ``AREA``, which LS-DYNA uses only for contact stiffness and defaults to
    0.01. dyna2rad reads the same cell (``convertprops.cxx:2538``
    ``LSD_MAT_SEATBELT_A``) and ignores the section entirely, and that is right
    for once: feeding a contact number into ``E*AREA`` would size the belt's
    compression stiffness off a number chosen for a contact search.

    With no card 2 (``E == 0``, the ordinary tension-only belt) there is no
    cross-section to state and no ``E`` for it to multiply, so the area is 1
    and the density carries MPUL whole. That is dimensionally odd — a lineic
    mass in a cell the cfg dimensions as a density — but it is exactly right
    numerically, and the alternative (inventing an area) would invent a
    stiffness with it.
    """
    if mat.has_card2 and mat.a > 0.0:
        return mat.mpul / mat.a, mat.a
    return mat.mpul, 1.0


def _belt_length(state: ConversionState, e: SeatbeltElem) -> Optional[float]:
    n1 = state.nodes.get(e.n1)
    n2 = state.nodes.get(e.n2)
    if n1 is None or n2 is None:
        return None
    return math.dist((n1.x, n1.y, n1.z), (n2.x, n2.y, n2.z))


def _warn_slack(state: ConversionState, elems: List[SeatbeltElem]) -> None:
    """``SLEN`` — the initial slack length — has no Radioss slot anywhere.

    LS-DYNA measures the belt's strain from ``L0 + SLEN``: the element must
    stretch by SLEN before it carries any load. Radioss forms
    ``eps = (L - L0)/max(L0, LMIN)`` with ``L0`` the element's INITIAL
    GEOMETRIC LENGTH, captured at ``TT == 0`` (``r23l114def3.F:263``
    ``X0(I) = ALDP(I)``), and there is no cell on ``/SPRING``,
    ``/PROP/TYPE23`` or ``/MAT/LAW114`` that shifts it — ``LMIN`` floors the
    DENOMINATOR only, leaving the numerator ``(L - L0)`` untouched, so it
    cannot express slack either.

    Not silently dropped, and not silently baked into the mesh: moving the
    belt's nodes to lengthen it would move every other element that shares
    them. The honest answer is to name the loss and its cost — the belt starts
    taut, so the occupant is restrained SLEN earlier and the peak belt force
    rises — and to name the one route that does express it, an ``/INISPRI``
    initial-state block supplying ``X0`` per element.
    """
    slack = [e for e in elems if e.slen > 0.0]
    if not slack:
        return
    total = sum(e.slen for e in slack)
    shown = ", ".join(f"{e.eid} (SLEN={e.slen:g})" for e in slack[:6])
    if len(slack) > 6:
        shown += f", ... ({len(slack)} elements)"
    state.warn(
        f"*ELEMENT_SEATBELT: {len(slack)} element(s) state an initial SLACK "
        f"length totalling {total:g}, which is DROPPED — {shown}. Radioss "
        "forms the belt strain as (L - L0)/max(L0, LMIN) with L0 the initial "
        "GEOMETRIC length (r23l114def3.F:263,366), and neither /SPRING nor "
        "/PROP/TYPE23 nor /MAT/LAW114 has a cell that shifts it (LMIN floors "
        "the denominator only). The converted belt therefore starts TAUT: it "
        "begins carrying load at once instead of after the slack is taken up, "
        "so the occupant is restrained earlier and the peak belt force is "
        "higher than LS-DYNA would give. To model it, either lengthen the belt "
        "path in the mesh or supply the unstretched lengths through an "
        "/INISPRI initial-state block. dyna2rad drops SLEN silently.")


def _warn_lmin_geometry(state: ConversionState, mat: MatSeatbelt,
                        elems: List[SeatbeltElem], label: str) -> None:
    """The LS-DYNA element-length rules that carry over to Radioss verbatim.

    "A belt element which is to be fed into a slipring or retractor must have
    a length > 1.1 * LMIN; an element at a slipring or the mouth of a
    retractor must be > 1.6 * LMIN; LFED must be >= 3 * LMIN" (Vol I,
    *MAT_SEATBELT remarks). Radioss enforces the same thresholds through the
    ``LMIN(I)`` clamps in ``material_flow.F:229-241`` and through
    ``rinit3.F:457`` ``LMIN = MAX(UPARAM(119), UPARAM(126))``, which folds the
    retractor's ``Elem_size`` into the material's LMIN for its own elements.

    Violating them does not raise a starter error — it makes the ring or the
    reel remesh every cycle, which shows up only as a run that will not finish.
    """
    if mat.lmin <= 0.0:
        return
    ring_elems: Set[int] = set()
    for s in state.seatbelt_sliprings:
        ring_elems.update({s.sbid1, s.sbid2})
    mouth_elems = {r.sbid for r in state.seatbelt_retractors}
    short: List[str] = []
    for e in elems:
        if e.eid not in ring_elems and e.eid not in mouth_elems:
            continue
        ln = _belt_length(state, e)
        if ln is not None and ln <= 1.6 * mat.lmin:
            where = "slipring" if e.eid in ring_elems else "retractor mouth"
            short.append(f"{e.eid} ({where}, L={ln:g})")
    if short:
        state.warn(
            f"{label}: {len(short)} belt element(s) sit at a slipring or a "
            f"retractor mouth and are SHORTER than 1.6*LMIN "
            f"({1.6 * mat.lmin:g}) — {', '.join(short[:6])}"
            + (f", ... ({len(short)} elements)" if len(short) > 6 else "")
            + ". LS-DYNA and Radioss impose the same threshold (Vol I "
            "*MAT_SEATBELT remarks; material_flow.F:229-241), and below it the "
            "device remeshes the element on nearly every cycle. Lengthen those "
            "elements or lower LMIN.")
    # Scoped to the retractors whose MOUTH ELEMENT is on this material: LMIN is
    # a property of the material, and rinit3.F:457 folds Elem_size into the
    # LMIN of that retractor's OWN elements. Without the scope a deck with M
    # belt materials and R retractors emits M*R identical LFED warnings, most
    # of them about a pairing that does not exist.
    mine = {e.eid for e in elems}
    for r in state.seatbelt_retractors:
        if r.sbid not in mine:
            continue
        if r.lfed > 0.0 and r.lfed < 3.0 * mat.lmin:
            state.warn(
                f"*ELEMENT_SEATBELT_RETRACTOR {r.sbrid}: LFED={r.lfed:g} is "
                f"below 3*LMIN ({3.0 * mat.lmin:g}) of *MAT_SEATBELT "
                f"{mat.mid}. LS-DYNA requires LFED >= 3*LMIN and Radioss folds "
                "Elem_size into the element LMIN itself (rinit3.F:457), so a "
                "shorter feed length releases elements the material then "
                "refuses to shorten — the retractor pays out in steps instead "
                "of smoothly.")


def _resolve_belt_curve(state: ConversionState, lcid: int, what: str,
                        label: str) -> int:
    """A LLCID / ULCID id, screened and table-flattened.

    Three things can go wrong with a curve id on a belt material and all three
    are silent in dyna2rad:

    * The id names a ``*DEFINE_TABLE``. LAW114/119 have ONE function slot and
      no rate dependence at all (``hm_read_mat114.F:88`` ``ISRATE = 0``), so a
      strain-rate FAMILY cannot be expressed; the first curve is taken and the
      loss named. dyna2rad does the same but dereferences ``funcIdList[0]``
      without an empty check (``convertmats.cxx:9450``).
    * The id names nothing at all. A /MAT/LAW114 pointing at a function the
      deck does not define is a starter error, so the reference is dropped and
      named — the #106 rule.
    * The id is 0. Legal, and means the reader falls back
      (``hm_read_mat114.F:190`` ``IF (IFUNC3 == 0) IFUNC3 = IFUNC1``).
    """
    if lcid <= 0:
        return 0
    if lcid in state.curves:
        return lcid
    tbl = state.define_tables.get(lcid)
    if tbl is not None:
        curves = [c for _a, c in tbl.rows if c in state.curves]
        if curves:
            state.warn(
                f"{label}: {what}={lcid} is a *DEFINE_TABLE (a strain-rate "
                f"family of {len(curves)} curves). /MAT/LAW114 and /MAT/LAW119 "
                "have ONE function slot and no rate dependence at all "
                "(hm_read_mat114.F:88 ISRATE=0), so the FIRST curve "
                f"({curves[0]}) is used and the rate dependence is LOST.")
            return curves[0]
    state.warn(
        f"{label}: {what}={lcid} names no *DEFINE_CURVE in the deck, so the "
        "reference is LEFT OUT of the material. Naming a function the deck "
        "does not define is a starter error that refuses the whole run, which "
        "is strictly worse than the lost curve — check whether the "
        "*DEFINE_CURVE is inside an *INCLUDE that did not resolve.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 2D belt: the weft/Poisson consistency the LAW119 determinant demands
# ─────────────────────────────────────────────────────────────────────────────

def _seatbelt_2d_weft(state: ConversionState, mat: MatSeatbelt
                      ) -> Tuple[float, float, float]:
    """``(E22, NU12, Fscale22)`` for a 2D belt, kept positive-definite.

    LS-DYNA's ``EB`` is the transverse (weft) modulus with a NEGATIVE value
    meaning a RATIO of the LLCID-derived warp modulus, defaulting to -0.1.
    Radioss states the same thing as ``Fscale22``, except that the reader
    multiplies that cell by 100 (measured: an input 0.02 echoes as 2.0) and
    then uses it BOTH for the weft modulus, ``E22 = FSCALET*E11`` when E22 is
    left blank (``create_seatbelt.F:899``), AND for the minor Poisson ratio,
    ``N21 = N12*FSCALET`` (``:903``).

    That second use is a trap dyna2rad walks straight into, because it never
    writes ``Fscale22`` at all and lets the reader default it to 0.1 → FSCALET
    = 10. The determinant is ``DET = 1/(1 - N12*N21) = 1/(1 - N12^2*FSCALET)``
    (``:911``), so with the LS-DYNA default ``PRBA = 0.3`` the product is
    0.9 — positive but one decimal from failure — and ``PRBA = 0.35`` gives
    1.225 and a NEGATIVE determinant. The starter answers that late, from
    ``create_seatbelt.F:920``, as ``ERROR 307 DETERMINANT OF MATERIAL MATRIX IS
    LESS THAN 0`` under the misleading title ``SEATBELT MATERIAL``.

    ``N12*N21 < 1`` is not a Radioss quirk: with ``FSCALET = E22/E11`` it is
    exactly the standard positive-definiteness condition ``nu12*nu21 < 1`` for
    a 2D orthotropic material, so a deck that violates it is stating a material
    that cannot exist. The minimal named repair is to pull ``NU12`` back to the
    boundary — the stiffness ratio is a measured property, the minor Poisson
    ratio is the one the symmetry constrains — and to say so.
    """
    nu12 = mat.prba
    if mat.eb < 0.0:
        ratio = -mat.eb                 # negative EB = ratio of the warp modulus
        e22 = 0.0                       # blank -> E22 = FSCALET * E11
    elif mat.eb > 0.0:
        # An ABSOLUTE weft modulus. E11 = K/section is resolved inside the
        # STARTER (create_seatbelt.F:896) from the shell thickness and the
        # strip width, so the converter cannot form the ratio EB/E11 that
        # Fscale22 wants. E22 is written straight and Fscale22 keeps the
        # LS-DYNA default magnitude, which then only drives N21.
        ratio = 0.1
        e22 = mat.eb
    else:
        ratio = 0.1                     # LS-DYNA EB default is -0.1
        e22 = 0.0
    if nu12 * nu12 * ratio >= 0.99:
        safe = math.sqrt(0.99 / ratio)
        state.warn(
            f"*MAT_SEATBELT{'_2D' if mat.is_2d else ''} {mat.mid}: "
            f"PRBA={mat.prba:g} with a weft/warp stiffness ratio of "
            f"{ratio:g} gives nu12*nu21 = {nu12 * nu12 * ratio:g} >= 1, i.e. a "
            "material matrix that is not positive definite. Radioss forms "
            "N21 = N12*100*Fscale22 and DET = 1/(1 - N12*N21) "
            "(create_seatbelt.F:903,911) and refuses the deck LATE, with "
            "ERROR 307 DETERMINANT OF MATERIAL MATRIX IS LESS THAN 0 under "
            f"the title SEATBELT MATERIAL. NU12 is clamped to {safe:.6G} — the "
            "stiffness ratio is a measured property, the minor Poisson ratio "
            "is the one nu12*nu21 < 1 constrains. Check PRBA and EB.")
        nu12 = safe
    return e22, nu12, ratio / 100.0


#: Appended to every ``RE`` note. RE is a REAL knob but a SMALL one, and a
#: warning that says "this is what a slack belt does physically" without this
#: sentence over-promises what the flag actually moves on a 2D belt.
#:
#: MEASURED on a 4-shell strip at eps = -0.02 (LLCID slope 4.0e6 N/strain): the
#: 8 starter-generated /SPRING strands carry -79998.46 N (analytic slope*eps =
#: -80000 N, dev -0.0019 %) while the LAW119 shell membrane contributes -8.05 N
#: at RE = 0.01 and -800.85 N at RE = 1.0 — so the flag moves 800.8 N out of
#: 80799.3 N, 0.99 % of the total. The ratio is structural, not deck-specific:
#: ``hm_read_mat119.F`` multiplies Fscale1 by 1e-2, so the membrane gets
#: E11 = 0.01*slope/section while the strand chain keeps the RAW slope through
#: ``iecrou = 12`` ("non linear elastic in tension with compression ... for 2d
#: seatbelts only", ``redef_seatbelt.F90:335``), which RE does not touch.
_RE_SCOPE_NOTE = (
    " NOTE the SCOPE: RE scales the LAW119 SHELL membrane only, and on a 2D "
    "belt the membrane is about 1 % of the compressive stiffness. The starter "
    "converts the shells into a 1D /SPRING strand chain "
    "(hm_convert_2d_elements_seatbelt.F) whose /MAT/LAW114 springs carry the "
    "RAW loading-curve slope in compression through iecrou=12 "
    "(redef_seatbelt.F90:335), untouched by RE, while the reader scales the "
    "membrane by 1e-2. MEASURED at eps=-0.02: 79998 N from the strands "
    "against 801 N of membrane at RE=1.0 and 8 N at RE=0.01. Whichever way "
    "this flag lands, it moves about 1 % of the belt's compressive response.")


def _seatbelt_2d_re(state: ConversionState, mat: MatSeatbelt) -> float:
    """``RE`` — the compression reduction factor ``E11c/E11`` — from ``CSE``.

    **CSE only says anything at all when FORM is NON-ZERO, and the manual says
    so in one sentence that is easy to read past.** Vol II R17 *MAT_SEATBELT
    (p.2-2101), the CSE entry: "Compressive stress elimination option **for
    nonzero FORM** that applies to shell elements only (see Remark 6):
    EQ.0.0: Don't eliminate compressive stresses in the shell fabric.
    EQ.1.0: Eliminate compressive stresses in the shell fabric. **Note that for
    FORM = 0, the solver automatically determines whether or not to eliminate
    the compressive stresses.**" Remark 6 (p.2-2105) dates it: "From versions
    R8 through R11, eliminating the compressive stresses was **always
    determined by the solver**. As of R12, **for nonzero FORM**, CSE, which had
    existed prior to R8, was reused to specify the behavior for stress
    elimination." R16 is consistent (p.2-2048: "The old recommended option of
    CSE = 2 ... still works if and only if FORM = 0") and gives no FORM = 0
    table either.

    So there is ONE mapping, not two:

    * ``FORM != 0`` — the R12 table: CSE = 0 KEEPS compression, CSE = 1
      ELIMINATES it, and CSE = 2 is not valid.
    * ``FORM == 0`` (the DEFAULT, and what every R8-era deck writes) — the CSE
      cell controls NOTHING; LS-DYNA decides per element. Whatever RE Radioss
      gets here is the converter's CHOICE, not a copy of a stated value.

    **The shipped cfg does NOT refute this.** Its CSE radio list
    (``0.0: Eliminate ...``; ``1.0: Dont eliminate ...``; ``2.0: ... decided by
    LS-DYNA automatically``) is byte-identical in ``Keyword971_R8.0`` and
    ``Keyword971_R12.0/MAT/SB_MAT.cfg`` — a pre-R8 GUI table nobody updated,
    not solver behaviour. Believing it inverts the flag on every FORM = 0 deck
    that states CSE = 1.

    FORM itself has no Radioss counterpart and is warn-dropped in
    :func:`_make_seatbelt_2d_materials`; it is read HERE only to decide whether
    CSE is a live cell at all.

    Radioss's ``RE`` multiplies the compressive stress directly —
    ``law119_membrane.F:190-191`` ``SIGNXX(I) = (A11*EPSXX + A12*EPSYY)*RCOMP``
    in the compression branch — so ELIMINATING compression means a SMALL RE and
    keeping it means RE = 1.

    **dyna2rad has this backwards.** ``convertmats.cxx:11047`` writes
    ``RE = (lsdCSE == 0) ? 1.0 : 0.01``, so the LS-DYNA DEFAULT — eliminate
    compression, which is what makes a belt a belt — converts to a membrane
    with FULL compressive stiffness, and a deck that explicitly asked to keep
    compression gets it eliminated. Both directions are wrong on every deck
    that states the field. (Its own ``*MAT_FABRIC`` route has the sign right:
    ``convertmats.cxx:2085`` ``R_E = (lsdCSE == 0) ? 0.0 : 0.01``.) k2rad
    deviates.

    0.01 rather than 0 for the eliminate case: ``hm_read_mat119.F:157-163``
    floors RE at 1e-3 with WARNING 1572, so 0 would be silently raised anyway,
    and 0.01 is dyna2rad's own "eliminated" constant — inside the range the
    reader validates, and two orders below the tension stiffness.

    **RE's SCOPE is narrow**, which every warning below says out loud: it
    scales the LAW119 SHELL membrane only, and the membrane is about 1 % of a
    2D belt's compressive stiffness — see :data:`_RE_SCOPE_NOTE`.
    """
    label = f"*MAT_SEATBELT{'_2D' if mat.is_2d else ''} {mat.mid}"
    if not mat.form:
        # FORM = 0: CSE is INERT. Not a table to read the other way round —
        # a cell the solver ignores. Writing the ELIMINATE side is the
        # converter's choice, so say so rather than dress it up as a copy.
        state.warn(
            f"{label}: FORM=0 (the default), so the CSE cell — here "
            f"{mat.cse:g} — controls NOTHING and cannot be mapped. Vol II "
            "*MAT_SEATBELT, CSE: 'Compressive stress elimination option FOR "
            "NONZERO FORM ... Note that for FORM = 0, THE SOLVER "
            "AUTOMATICALLY DETERMINES whether or not to eliminate the "
            "compressive stresses', and Remark 6: 'From versions R8 through "
            "R11, eliminating the compressive stresses was ALWAYS DETERMINED "
            "BY THE SOLVER. As of R12, for nonzero FORM, CSE ... was reused'. "
            "(The shipped cfg's CSE list is a pre-R8 GUI table — byte-"
            "identical in Keyword971_R8.0 and _R12.0 — not solver behaviour.) "
            "Radioss has ONE constant for the whole material (/MAT/LAW119 RE, "
            "the compression reduction factor E11c/E11) and no per-element "
            "decision, so RE=0.01 is written: the ELIMINATE side, which is "
            "what a slack belt does. That is a CHOICE this converter makes, "
            "not a value the deck states." + _RE_SCOPE_NOTE)
        return 0.01
    if mat.cse in (0.0, 1.0):
        if mat.cse != 0.0:
            state.warn(
                f"{label}: FORM={mat.form} is non-zero, so CSE={mat.cse:g} "
                "means ELIMINATE compressive stresses (Vol II *MAT_SEATBELT, "
                "CSE: 'For nonzero FORM: EQ.0.0: Don't eliminate ...; "
                "EQ.1.0: Eliminate ...'). RE=0.01 is written. On a FORM=0 "
                "belt the same cell would mean nothing at all — the solver "
                "decides there. dyna2rad has no FORM branch at all."
                + _RE_SCOPE_NOTE)
        else:
            state.warn(
                f"{label}: FORM={mat.form} is non-zero, so CSE=0 means KEEP "
                "compressive stresses (Vol II *MAT_SEATBELT, CSE) — a "
                "membrane with FULL compressive stiffness, which is NOT what "
                "a belt normally does. RE=1.0 is written. On a FORM=0 belt "
                "the same cell would mean nothing at all — the solver decides "
                "there." + _RE_SCOPE_NOTE)
        return 0.01 if mat.cse == 1.0 else 1.0
    state.warn(
        f"{label}: CSE={mat.cse:g} is only defined for FORM=0 ('the old "
        "recommended option of CSE = 2 ... still works if and only if "
        f"FORM = 0', Vol II *MAT_SEATBELT) and this material states "
        f"FORM={mat.form}. RE=0.01 (eliminate) is written, which is what a "
        "belt normally does; state CSE=0 explicitly if this material really "
        "is meant to carry compression." + _RE_SCOPE_NOTE)
    return 0.01


# ─────────────────────────────────────────────────────────────────────────────
# Sensors: *ELEMENT_SEATBELT_SENSOR -> /SENSOR/<TYPE>, plus the delay folding
# every device needs
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA sensor DOF (1/2/3) -> the ``dir`` STRING /SENSOR/ACCE wants. The
#: cell is ``%10s`` and the legal values are X | Y | Z | XY | YZ | ZX | XYZ;
#: dyna2rad leaves it an EMPTY STRING for any other DOF
#: (``convertelements.cxx:737-779``), which the reader then reads as "no
#: direction" without a word.
_SENSOR_DIR = {1: "X", 2: "Y", 3: "Z"}

#: SBSTYP -> why it has no Radioss target, for the warn-drop.
_SENSOR_UNSUPPORTED = {
    2: "a retractor PULL-OUT RATE trigger (SBRID/PULRAT/PULTIM). Radioss has "
       "no pull-out sensor of any kind — the /SENSOR family is ACCE, TIME, "
       "DIST, DIST_SURF, VEL, RBODY, SECT, WORK, ENERGY, INTER, RWALL, HIC, "
       "TEMP, GAUGE and the logical gates, and none of them can read a "
       "retractor's spool rate",
    5: "a retractor PULL-OUT trigger (SBRID/PULMX/PULMN). Radioss has no "
       "pull-out sensor; the closest expressible idea is a /SENSOR/DIST "
       "between the anchorage node and a node on the belt, which measures a "
       "different quantity (a chord, not the spooled length)",
}


class _SensorPool:
    """The /SENSOR cards this conversion writes, and who may reuse which.

    A single object rather than three parallel dicts because the three
    questions are one question: what Radioss sensor does LS-DYNA sensor N
    become, what does it become with an extra delay D folded in, and which
    lines carry them.
    """

    def __init__(self, state: ConversionState):
        self.state = state
        self.lines: List[str] = []
        self.direct: Dict[int, int] = {}          # SBSID -> /SENSOR id
        self.delayed: Dict[Tuple[int, float], int] = {}
        self.base_delay: Dict[int, float] = {}    # SBSID -> its own Tdelay
        #: node -> the /ACCEL watching it. Keyed on the NODE, not on the
        #: sensor, so a delayed copy of a SBSTYP=1 sensor reuses the same
        #: accelerometer instead of stacking a second one on the same node —
        #: two /ACCELs on one node is legal but produces two identical
        #: channels and one wasted id per delay.
        self.accel_of_node: Dict[int, int] = {}

    # -- construction ------------------------------------------------------
    def _emit(self, sens: SeatbeltSensor, sens_id: int,
              tdelay: float, title: str) -> bool:
        st = self.state
        if sens.sbstyp == 1:
            if sens.nid <= 0 or sens.nid not in st.nodes:
                st.warn(
                    f"*ELEMENT_SEATBELT_SENSOR {sens.sbsid} (SBSTYP=1, node "
                    f"acceleration) names node {sens.nid}, which the converted "
                    "deck does not define — the sensor is DROPPED. Every "
                    "device that triggers on it loses that trigger; see the "
                    "warnings below for which.")
                return False
            direction = _SENSOR_DIR.get(sens.dof, "")
            if not direction:
                st.warn(
                    f"*ELEMENT_SEATBELT_SENSOR {sens.sbsid}: DOF={sens.dof} is "
                    "not 1, 2 or 3, so there is no global axis to watch. "
                    "/SENSOR/ACCE's `dir` cell is a right-justified STRING "
                    "(X|Y|Z|XY|YZ|ZX|XYZ) and X is written as the fallback — "
                    "dyna2rad writes an EMPTY string there, which the reader "
                    "takes as no direction at all, silently.")
                direction = "X"
            # Radioss has no accelerometer-free acceleration sensor:
            # sensor_acce.cfg's accel_ID is a mandatory object reference, so
            # the sensor's node needs an /ACCEL of its own. dyna2rad builds one
            # too (convertelements.cxx:773-778) but never logs it and creates
            # it AFTER its /TH/ACCEL pass, so the channel is invisible; this
            # one is registered in state.accel_ids like every other.
            accel_id = self.accel_of_node.get(sens.nid)
            if accel_id is None:
                accel_id = st.next_accel_id()
                self.accel_of_node[sens.nid] = accel_id
                self.lines += _emit_accel(
                    accel_id, f"SEATBELT_SENSOR_{sens.sbsid}_ACCEL",
                    sens.nid, 0)
            self.lines += _emit_sensor_acce(
                sens_id, title, tdelay, accel_id, direction,
                sens.acc, sens.atime)
            return True
        if sens.sbstyp == 3:
            # TIME + Tdelay, not TIME then Tdelay: /SENSOR/TIME's Tdelay IS the
            # activation instant (sensor_time.F:66-68 sets TSTART = TDELAY), so
            # a device delay simply adds to it. dyna2rad's duplicate sensor
            # loses the original TIME entirely and fires at TDEL alone
            # (convertelements.cxx:906-916), i.e. at the wrong absolute instant.
            self.lines += [
                f"/SENSOR/TIME/{sens_id}",
                title,
                "#             Tdelay",
                f"{_f(sens.time + tdelay)}",
                HDR,
            ]
            return True
        if sens.sbstyp == 4:
            missing = [n for n in (sens.nid1, sens.nid2)
                       if n <= 0 or n not in st.nodes]
            if missing:
                st.warn(
                    f"*ELEMENT_SEATBELT_SENSOR {sens.sbsid} (SBSTYP=4, node "
                    f"distance) names node(s) {missing} that the converted "
                    "deck does not define — the sensor is DROPPED rather than "
                    "written with a node id of 0. That is exactly what "
                    "dyna2rad's duplicated /DIST sensor does emit "
                    "(convertelements.cxx:997-1004 copies only Sensor_Type and "
                    "Tdelay), and the starter answers ERROR 78 NODE ID=0 DOES "
                    "NOT EXIST — twice — refusing the whole run.")
                return False
            # DMN -> Dmin and DMX -> Dmax. The LS-DYNA card lists DMX FIRST,
            # so a position-for-position copy swaps the bounds and, with
            # Dmin > Dmax, gives a sensor that can never fire.
            self.lines += _emit_sensor_dist(
                sens_id, title, tdelay, sens.nid1, sens.nid2,
                sens.dmn, sens.dmx)
            return True
        return False

    def build(self) -> None:
        st = self.state
        for sbsid in sorted(st.seatbelt_sensors):
            sens = st.seatbelt_sensors[sbsid]
            if sens.sbstyp in _SENSOR_UNSUPPORTED:
                st.warn(
                    f"*ELEMENT_SEATBELT_SENSOR {sbsid}: SBSTYP="
                    f"{sens.sbstyp} is {_SENSOR_UNSUPPORTED[sens.sbstyp]}. The "
                    "sensor is DROPPED and every retractor or pretensioner "
                    "that triggers on it loses that trigger — it will not lock "
                    "or fire from this condition. dyna2rad drops SBSTYP 2 and "
                    "5 silently and leaves the retractor's Sens_ID dangling "
                    "(convertelements.cxx:731-813).")
                continue
            if sens.sbstyp not in (1, 3, 4):
                st.warn(
                    f"*ELEMENT_SEATBELT_SENSOR {sbsid}: SBSTYP={sens.sbstyp} "
                    "is not a documented sensor type (1..5), so no /SENSOR is "
                    "written. Every device that triggers on it loses that "
                    "trigger.")
                continue
            if sens.sbsfl == 1:
                st.warn(
                    f"*ELEMENT_SEATBELT_SENSOR {sbsid}: SBSFL=1 asks the "
                    "sensor to stay ACTIVE during dynamic relaxation. Radioss "
                    "/SENSOR has no such flag — a sensor is armed from t=0 of "
                    "the run it is in — so the flag is DROPPED. It only "
                    "matters on a deck that actually runs a relaxation phase.")
            # The USER id is preserved, exactly as dyna2rad preserves it
            # (convertelements.cxx:737,788,804), which is what lets a retractor
            # name SID1 verbatim.
            st.sensor_ids.add(sbsid)
            title = f"SEATBELT_SENSOR_{sbsid}"
            if self._emit(sens, sbsid, 0.0, title):
                self.direct[sbsid] = sbsid
                self.base_delay[sbsid] = sens.time if sens.sbstyp == 3 else 0.0

    # -- consumption -------------------------------------------------------
    def with_delay(self, sbsid: int, delay: float, why: str) -> int:
        """The /SENSOR id for LS-DYNA sensor *sbsid* with *delay* folded in.

        ``delay <= 0`` reuses the sensor itself. Otherwise a FULL COPY is
        written — every type-specific field included — with ``Tdelay`` raised
        by *delay*, because Radioss puts the delay on the sensor and there is
        no ``Tdel`` cell on /RETRACTOR at all (locking happens in the same
        cycle the sensor's TSTART is passed, ``material_flow.F:695-702``).

        This is where dyna2rad's DEFECT 4 lives: its duplicate copies only
        ``Sensor_Type`` and ``Tdelay`` (``convertelements.cxx:906-916`` and
        ``:997-1004``), so an /ACCE copy has ``Nacc = 0`` and no accelerometer,
        a /DIST copy has ``N1 = N2 = Dmin = Dmax = 0`` (starter ERROR 78, and
        an uninitialised title that prints as ``538976288`` = ``0x20202020``),
        and a /TIME copy loses the original ``TIME`` so it fires at ``TDEL``
        instead of ``TIME + TDEL``. All three are VERIFIED on its own probe
        listing. Copying the whole card costs one extra id and fixes all three.
        """
        base = self.direct.get(sbsid)
        if base is None:
            return 0
        if delay <= 0.0:
            return base
        key = (sbsid, delay)
        if key in self.delayed:
            return self.delayed[key]
        sens = self.state.seatbelt_sensors[sbsid]
        new_id = self.state.next_sensor_id()
        title = f"SEATBELT_SENSOR_{sbsid}_DELAYED_{why}"
        if not self._emit(sens, new_id, delay, title[:100]):
            return base
        self.delayed[key] = new_id
        return new_id

    def any_of(self, sens_ids: List[int], title: str) -> int:
        """One sensor id that fires when ANY of *sens_ids* fires.

        ``/SENSOR/OR`` takes exactly TWO inputs (``sensor_or.F:75-78`` reads
        ``IPARAM(1)`` and ``IPARAM(2)``), so three or four are chained left to
        right.

        This is k2rad exceeding dyna2rad deliberately. LS-DYNA gives a
        retractor four lock sensors and a pretensioner four trigger sensors,
        ORed; ``/RETRACTOR/SPRING`` has one ``Sens_ID1`` and one ``Sens_ID2``,
        and dyna2rad simply takes the FIRST NON-ZERO of each four
        (``convertelements.cxx:838-846``, ``:944-951``) — so a belt that should
        lock on either the sled decelerating OR the webbing paying out locks
        only on whichever the deck happened to list first, silently.
        """
        ids = [s for s in sens_ids if s > 0]
        if not ids:
            return 0
        if len(ids) == 1:
            return ids[0]
        acc = ids[0]
        for k, nxt in enumerate(ids[1:], start=1):
            or_id = self.state.next_sensor_id()
            self.lines += _emit_sensor_or(
                or_id, f"{title}_OR{k}"[:100], acc, nxt)
            acc = or_id
        return acc


# ─────────────────────────────────────────────────────────────────────────────
# Sliprings
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA DIRECT -> Radioss Flow_flag. Established from the ENGINE, not from
#: the two cards' field names: ``material_flow.F:266-267`` grows strand 1's
#: unstretched length by ``DELTA_LO`` and shrinks strand 2's by the same
#: amount, so ``DELTA_LO > 0`` means material flowing from element 2 INTO
#: element 1, and ``:253-254`` blocks ``FL_FLAG == 1`` exactly when
#: ``DELTA_LO > 0``. So Flow_flag 1 forbids 2->1, i.e. permits only 1->2 —
#: which is LS-DYNA's ``DIRECT = 12``.
_SLIPRING_FLOW = {0: 0, 12: 1, 21: 2}


def _make_sliprings(state: ConversionState, pool: "_SensorPool",
                    belt_eids: Set[int], belt_2d_eids: Set[int]) -> List[str]:
    """*ELEMENT_SEATBELT_SLIPRING -> /SLIPRING/SPRING or /SLIPRING/SHELL."""
    lines: List[str] = []
    for s in sorted(state.seatbelt_sliprings, key=lambda x: x.sbsrid):
        label = f"*ELEMENT_SEATBELT_SLIPRING {s.sbsrid}"
        if s.sbid1 <= 0 or s.sbid2 <= 0:
            state.warn(
                f"{label}: SBID1={s.sbid1} SBID2={s.sbid2} — a slipring needs "
                "BOTH belt elements, so the ring is DROPPED and the belt runs "
                "straight through where it should turn. dyna2rad drops it "
                "silently, its lock sensor included "
                "(convertelements.cxx:532).")
            continue
        if s.is_shell:
            # |SBRNID| is a *SET_NODE and SBID1/SBID2 are *SET_SHELL_LIST ids.
            # /SLIPRING/SHELL takes a /GRSHEL and a /GRNOD, which k2rad has
            # emitters for — but only once the sets themselves are converted,
            # and *SET_SHELL_LIST -> /GRSHEL is a resolution this batch does
            # not do for slipring scope. Named rather than mis-wired: writing
            # the LS-DYNA set ids straight into EL_SET1/EL_SET2 would point the
            # ring at whatever /GRSHEL happens to carry those ids.
            state.warn(
                f"{label}: SBRNID={s.sbrnid} is negative, which makes this a "
                "SHELL-belt slipring — |SBRNID| is a *SET_NODE and SBID1/SBID2 "
                "are *SET_SHELL_LIST ids. That maps to /SLIPRING/SHELL, whose "
                "EL_SET1/EL_SET2 are /GRSHEL groups and whose Node_SET is a "
                "/GRNOD; this batch resolves 1D (spring) sliprings only, so "
                "the ring is DROPPED and the 2D belt slides through the "
                "guide loop without friction. Note the starter also requires "
                "every anchorage node of a /SLIPRING/SHELL to be collinear "
                "(ERROR 2051) and attached to one rigid body or a "
                "translation-blocked /BCS (ERROR 2081), so the set has to be "
                "built for it, not merely converted.")
            continue
        missing = [e for e in (s.sbid1, s.sbid2) if e not in belt_eids]
        if missing:
            in_2d = [e for e in missing if e in belt_2d_eids]
            state.warn(
                f"{label}: element(s) {missing} are not an emitted 1D belt "
                "/SPRING"
                + (f" ({in_2d} are 2D (shell) belt elements)" if in_2d else "")
                + ", so the ring is DROPPED. Naming one is starter ERROR 2032 "
                "(the element is not a /PROP/TYPE23 + /MAT/LAW114 seatbelt "
                "spring) and the run would not start at all, which is worse "
                "than the lost guide loop.")
            continue
        sens_id = 0
        if s.ltime < 1.0e19:
            # LTIME is the time at which the ring LOCKS. Radioss states that as
            # a /SENSOR/TIME on Sens_ID; an absent LTIME (the LS-DYNA default
            # 1e20) means "never", which is Sens_ID = 0.
            sens_id = state.next_sensor_id()
            lines += [
                f"/SENSOR/TIME/{sens_id}",
                f"SLIPRING_{s.sbsrid}_LOCK",
                "#             Tdelay",
                f"{_f(s.ltime)}",
                HDR,
            ]
        flow = _SLIPRING_FLOW.get(s.direct)
        if flow is None:
            state.warn(
                f"{label}: DIRECT={s.direct} is not 0, 12 or 21, so no "
                "Flow_flag can be derived and 0 (material may flow BOTH ways) "
                "is written. dyna2rad leaves the cell unset in this case "
                "(convertelements.cxx:626-633), which reads as the same 0 "
                "without saying so.")
            flow = 0
        if s.funcid > 0:
            state.warn(
                f"{label}: FUNCID={s.funcid} — a *DEFINE_FUNCTION f(fct, "
                "theta, alpha) giving the friction as a free function of the "
                "wrap angle — is DROPPED. Radioss's angle dependence is fixed "
                "in form: fric = mu * (1 + A*gamma^2) with gamma the SKEW "
                "angle between the strand plane and the anchorage->orientation "
                "vector (material_flow.F:204, kine_seatbelt_vel.F:108), and "
                "there is no function slot for an arbitrary f(theta). The "
                "scalar FC/FCS and the A/DC terms below still convert.")
        if s.onid > 0 and s.onid not in state.nodes:
            state.warn(
                f"{label}: ONID={s.onid} names no node in the converted deck, "
                "so the orientation node is dropped and Node_ID2=0 is written "
                "— the skew angle gamma is then 0 and the K*gamma^2 "
                "orientation-friction term is inert.")
        node2 = s.onid if s.onid in state.nodes else 0
        if s.sbrnid > 0 and s.sbrnid not in state.nodes:
            state.warn(
                f"{label}: SBRNID={s.sbrnid} names no node in the converted "
                "deck, so the ring is DROPPED — the anchorage node is what "
                "holds the slipring in place and the starter refuses a "
                "/SLIPRING whose Node_ID does not exist.")
            continue
        state.slipring_ids.append((s.sbsrid, f"SLIPRING_{s.sbsrid}"))
        lines += _emit_slipring(
            s.sbsrid, f"SLIPRING_{s.sbsrid}", False, s.sbid1, s.sbid2,
            s.sbrnid, node2, sens_id, flow, s.k, s.dc,
            _resolve_belt_curve(state, s.fc_func, "FC (curve)", label),
            _resolve_belt_curve(state, s.lcnffd, "LCNFFD", label),
            s.fc,
            _resolve_belt_curve(state, s.fcs_func, "FCS (curve)", label),
            _resolve_belt_curve(state, s.lcnffs, "LCNFFS", label),
            s.fcs)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Retractors + pretensioners
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA SBPRTY -> Radioss Tens_typ, with what each Radioss type DOES
#: (``engine/source/tools/seatbelts/material_flow.F:544-596``).
#:
#:   1  pull-in LENGTH vs time; deactivates and locks when Force is reached
#:   2  FORCE vs time, F_unlock = max(F_retractor, F_pretens) — never
#:      self-terminates
#:   3  as 2, but deactivates and locks once Pullout is exceeded
#:   4  ADDITIVE force, F_unlock = F_retractor + F_pretens
#:   5  pull-in ENERGY vs time
#:
#: SBPRTY 7 ("independent pretensioner/retractor") maps to Tens_typ 4, not 3:
#: an INDEPENDENT pretensioner adds its force to the retractor's rather than
#: replacing it, which is exactly what type 4 does (``material_flow.F:580,623``
#: ``YY = YY + PRETENS``). dyna2rad maps 6 and 7 both to 3
#: (``convertelements.cxx:1019``) and so never produces Tens_typ 4 at all.
_PRETENSIONER_TENS_TYP = {1: 1, 4: 2, 5: 1, 6: 3, 7: 4, 8: 5}

#: The SBPRTY values whose card-2 ``SBRID`` is a SPRING ELEMENT id rather than
#: a retractor id — Vol I *ELEMENT_SEATBELT_PRETENSIONER, SBRID: "Retractor
#: number (SBPRTY = 1, 4, 5, 6, 7 or 8) or spring element number
#: (SBPRTY = 2, 3 or 9)". One cell, two id namespaces, chosen by a field on the
#: OTHER card — so every walk over it (the retractor map here, the
#: *INCLUDE_TRANSFORM offsetter in assembly.py) has to branch on SBPRTY.
_PRETENSIONER_SPRING_SBRID = frozenset({2, 3, 9})

#: The SBPRTY values with no Radioss target, and what each one costs.
_PRETENSIONER_UNSUPPORTED = {
    2: "a PRE-LOADED SPRING released at the trigger. It is not a retractor "
       "behaviour at all — the force comes from a separate spring element "
       "that LS-DYNA activates — so /RETRACTOR/SPRING has no slot for it",
    3: "the removal of a LOCK SPRING at the trigger, again a separate spring "
       "element rather than a retractor property",
    9: "a pull-in ENERGY vs time pretensioner acting at the BUCKLE or the "
       "ANCHOR rather than at the retractor. Radioss's Tens_typ 5 is the same "
       "energy model but only AT THE REEL, so the force would be applied at "
       "the wrong end of the belt",
}


def _resolve_pretensioners(state: ConversionState
                           ) -> Dict[int, List["object"]]:
    """``retractor id -> its pretensioners``, lowest SBPRID first.

    A MAP built up front, which is the whole fix for dyna2rad's DEFECT B.
    Its ``SelectionRead selSeatbeltPretensioner`` is constructed ONCE outside
    the retractor loop (``convertelements.cxx:826``) and never ``Restart()``ed,
    although ``SelectionRead::Restart()`` exists and it uses it in five other
    places. Both selections iterate in ascending id order, so the pretensioners
    are consumed GLOBALLY: VERIFIED on its own probe decks, a retractor with no
    matching pretensioner eats the rest of the list (``v6``: retractor 42 got
    no Sens_ID2, no Tens_typ, no Force and no Fct_ID3 at all), and two
    pretensioners on one retractor make the second vanish and poison the
    following retractor (``v7``).
    """
    by_ret: Dict[int, List[object]] = {}
    for p in sorted(state.seatbelt_pretensioners, key=lambda x: x.sbprid):
        # Card-2 field 0 is NOT always a retractor. Vol I
        # *ELEMENT_SEATBELT_PRETENSIONER, SBRID: "Retractor number
        # (SBPRTY = 1, 4, 5, 6, 7 or 8) or SPRING ELEMENT NUMBER
        # (SBPRTY = 2, 3 or 9)" — two different id NAMESPACES in one cell.
        # Keying the map on it regardless lets a spring element id that
        # numerically equals a retractor id claim that retractor's card 3:
        # the SBPRTY 2/3/9 record sorts first on SBPRID, takes the single
        # `pretensioners[0]` slot, resolves to Tens_typ 0 — and the REAL
        # pretensioner beside it is then dropped as "extra". So the spring
        # types never enter this map; the unclaimed-pretensioner loop at the
        # end of _make_retractors reports them for the right reason.
        if p.sbprty in _PRETENSIONER_SPRING_SBRID:
            continue
        by_ret.setdefault(p.sbrid, []).append(p)
    return by_ret


def _resolve_retractor_sensor(state: ConversionState, pool: "_SensorPool",
                              sbsids: List[int], delay: float, label: str,
                              role: str) -> int:
    """One ``Sens_ID`` from up to four LS-DYNA sensors and one delay.

    The delay is folded into each LEAF rather than into the OR gate above
    them, because ``/SENSOR/OR`` ignores ``Tdelay`` outright
    (``sensor_or.F`` sets ``TSTART = TT`` at activation with no reference to
    it). For latching sensors that is exact:
    ``min(t1, t2) + d == min(t1 + d, t2 + d)``.
    """
    if not sbsids:
        return 0
    resolved: List[int] = []
    lost: List[int] = []
    for sbsid in sbsids:
        sid = pool.with_delay(sbsid, delay, role)
        if sid > 0:
            resolved.append(sid)
        else:
            lost.append(sbsid)
    if lost:
        state.warn(
            f"{label}: {role} sensor(s) {lost} did not convert, so they are "
            "LEFT OUT of the "
            + ("/SENSOR/OR gate" if len(resolved) > 1 else "wiring")
            + " rather than named as a dangling Sens_ID — a /RETRACTOR "
            "pointing at a sensor the deck does not define is refused by the "
            "starter. See the sensor warnings above for why each was dropped"
            + ("" if resolved else
               f", and note that NO {role} trigger is left: the retractor "
               + ("never locks" if role == "lock" else "never pretensions")))
    return pool.any_of(resolved, f"{label.split()[-1]}_{role.upper()}"[:90])


def _make_retractors(state: ConversionState, pool: "_SensorPool",
                     belt_eids: Set[int], belt_2d_eids: Set[int]
                     ) -> List[str]:
    """*ELEMENT_SEATBELT_RETRACTOR (+ its pretensioner) -> /RETRACTOR/SPRING."""
    lines: List[str] = []
    by_ret = _resolve_pretensioners(state)
    claimed: Set[int] = set()
    for r in sorted(state.seatbelt_retractors, key=lambda x: x.sbrid):
        label = f"*ELEMENT_SEATBELT_RETRACTOR {r.sbrid}"
        if r.is_shell:
            state.warn(
                f"{label}: SBRNID={r.sbrnid} is negative, which makes this a "
                "SHELL-belt retractor — |SBRNID| is a *SET_NODE and SBID is a "
                "*SET_SHELL_LIST. Radioss has NO /RETRACTOR/SHELL card: "
                "hm_cfg_files/config/CFG/radioss2022/SEATBELTS/ holds exactly "
                "retractor.cfg, slipring.cfg and slipring_shell.cfg, and the "
                "starter's own banner reads 'RETRACTOR/SPRING DEFINITIONS' "
                "(hm_read_retractor.F:365). The retractor is DROPPED: the belt "
                "keeps its full length and never spools in or locks. A 2D belt "
                "that needs a retractor has to be modelled with a 1D "
                "(*SECTION_SEATBELT) strand at the reel.")
            continue
        if r.sbid not in belt_eids:
            in_2d = r.sbid in belt_2d_eids
            state.warn(
                f"{label}: SBID={r.sbid} is not an emitted 1D belt /SPRING"
                + (" (it is a 2D (shell) belt element)" if in_2d else "")
                + ", so the retractor is DROPPED. The mouth element must be a "
                "/PROP/TYPE23 + /MAT/LAW114 spring or the starter answers "
                "ERROR 2033 and refuses the run.")
            continue
        if r.sbrnid <= 0 or r.sbrnid not in state.nodes:
            state.warn(
                f"{label}: SBRNID={r.sbrnid} names no node in the converted "
                "deck, so the retractor is DROPPED. The anchorage node has to "
                "be a real node coincident with one node of the mouth element "
                "(starter ERROR 2009) and outside the belt itself "
                "(ERROR 2030).")
            continue
        for name, val in (("DSID", r.dsid), ("LCFL", r.lcfl),
                          ("FLOPT", r.flopt)):
            if val:
                state.warn(
                    f"{label}: {name}={val} is DROPPED — "
                    + {"DSID": "a DEACTIVATION sensor; /RETRACTOR/SPRING has "
                               "Sens_ID1 (lock) and Sens_ID2 (pretension) and "
                               "no third slot, so the retractor cannot be "
                               "switched off again once it locks",
                       "LCFL": "the ADAPTIVE MULTI-LEVEL load limiter — a "
                               "curve whose ABSCISSA is a *SENSOR_SWITCH id "
                               "and whose ordinate is that switch's force "
                               "limit (Vol I *ELEMENT_SEATBELT_RETRACTOR), so "
                               "it is a switch-driven schedule of limits, not "
                               "a force-vs-time curve. Radioss's Force cell is "
                               "ONE value and the pretensioner curve Fct_ID3 "
                               "is already spoken for; *SENSOR_SWITCH has no "
                               "converter at all, so neither half is "
                               "expressible",
                       "FLOPT": "the force-limiter option flag, which selects "
                                "between limiting schemes Radioss does not "
                                "distinguish"}[name] + ".")
        # TDEL folds into the SENSOR, because /RETRACTOR has no Tdel cell at
        # all: material_flow.F:695-702 locks in the SAME cycle the sensor's
        # TSTART is passed, gated only by LOCK_PULL >= Pullout.
        sens1 = _resolve_retractor_sensor(
            state, pool, r.sensor_ids(), r.tdel, label, "lock")
        # The RESOLVED Fct_ID1, not the raw LLCID: _resolve_belt_curve returns
        # 0 for a curve the converted deck does not define, and a Sens_ID1 > 0
        # beside a Fct_ID1 of 0 is what the starter refuses — not a zero in the
        # LS-DYNA field. hm_read_retractor.F:236-242
        # ``IF ((ISENS(1) > 0).AND.(IFUNC(1)==0)) ANCMSG(MSGID=2031)``.
        fct1 = _resolve_belt_curve(state, r.llcid, "LLCID", label)
        fct2 = _resolve_belt_curve(state, r.ulcid, "ULCID", label)
        if sens1 > 0 and fct1 <= 0:
            state.warn(
                f"{label}: a lock sensor is wired but LLCID"
                + (" is 0" if r.llcid <= 0 else
                   f"={r.llcid} resolves to no curve")
                + ". The starter makes the loading curve MANDATORY as soon as "
                "Sens_ID1 > 0 (ERROR 2031, hm_read_retractor.F:236-242), "
                "because a locked reel with no force-vs-pullout curve has "
                "nothing to pull against, so the SENSOR is dropped with it "
                "rather than refusing the deck: the retractor never locks and "
                "the belt spools freely for the whole run. This is the same "
                "answer the pretensioner's ERROR 2025 gets below.")
            sens1 = 0
        pret_sens = 0
        tens_typ = 0
        force = 0.0
        fct3 = 0
        pretensioners = by_ret.get(r.sbrid, [])
        if pretensioners:
            p = pretensioners[0]
            claimed.add(p.sbprid)
            plabel = f"*ELEMENT_SEATBELT_PRETENSIONER {p.sbprid}"
            if len(pretensioners) > 1:
                extra = [q.sbprid for q in pretensioners[1:]]
                state.warn(
                    f"{label}: {len(pretensioners)} pretensioners name this "
                    f"retractor ({p.sbprid} plus {extra}). /RETRACTOR/SPRING "
                    "card 3 holds ONE pretensioner — one Sens_ID2, one "
                    f"Tens_typ, one Force, one Fct_ID3 — so {p.sbprid} (the "
                    "lowest SBPRID) is applied and the rest are DROPPED. "
                    "dyna2rad drops them too, and then also strands the NEXT "
                    "retractor, because its pretensioner iterator is never "
                    "restarted (convertelements.cxx:826 vs :926).")
                for q in pretensioners[1:]:
                    claimed.add(q.sbprid)
            tens_typ = _PRETENSIONER_TENS_TYP.get(p.sbprty, 0)
            if tens_typ == 0:
                why = _PRETENSIONER_UNSUPPORTED.get(
                    p.sbprty,
                    f"SBPRTY={p.sbprty} is not a documented pretensioner type "
                    "(1..9)")
                state.warn(
                    f"{plabel}: {why}. NO pretensioner is written onto "
                    f"/RETRACTOR/SPRING/{r.sbrid} — dyna2rad writes "
                    "Tens_typ=0 with the sensor, the curve and the force still "
                    "attached (convertelements.cxx:1011-1027), which is a "
                    "retractor that carries a pretensioner's data and does "
                    "nothing with it. The belt is NOT pre-tensioned; the "
                    "occupant starts with the deck's slack.")
            else:
                pret_sens = _resolve_retractor_sensor(
                    state, pool, p.sensor_ids(), p.time, plabel, "pretension")
                force = p.lmtfrc
                # "Optional limiting force for retractor types 5 AND 8"
                # (Vol I *ELEMENT_SEATBELT_PRETENSIONER, LMTFRC) — LS-DYNA
                # ignores it on every other type. Radioss reads its Force cell
                # under Tens_typ 1 and 5 ONLY (material_flow.F:546,583), so the
                # two solvers disagree in exactly one place: SBPRTY=1, which
                # maps to Tens_typ 1. There the value would become a
                # deactivation force the source deck does not have. On
                # SBPRTY 4/6/7 (Tens_typ 2/3/4) the cell is inert on BOTH
                # sides, so it is written through unchanged.
                if force and tens_typ in (1, 5) and p.sbprty not in (5, 8):
                    state.warn(
                        f"{plabel}: LMTFRC={force:g} is DROPPED. LS-DYNA "
                        "applies the limiting force to retractor types 5 and 8 "
                        f"only (Vol I, LMTFRC) and this is SBPRTY={p.sbprty}, "
                        "so in the source deck it is INERT — while "
                        "/RETRACTOR/SPRING's Force cell IS live on Tens_typ 1 "
                        "(material_flow.F:546), which SBPRTY=1 maps to. "
                        "Writing it through would deactivate the pretensioner "
                        "at a force the deck never asked for.")
                    force = 0.0
                fct3 = _resolve_belt_curve(state, p.ptlcid, "PTLCID", plabel)
                if pret_sens > 0 and fct3 <= 0:
                    state.warn(
                        f"{plabel}: a pretension sensor is wired but PTLCID "
                        "resolves to no curve. The starter makes Fct_ID3 "
                        "MANDATORY as soon as Sens_ID2 > 0 (ERROR 2025), so "
                        "the sensor is dropped with it rather than refusing "
                        "the deck.")
                    pret_sens = 0
                    tens_typ = 0
                if p.lmtpin:
                    state.warn(
                        f"{plabel}: LMTPIN={p.lmtpin:g} (the pull-in limit) is "
                        "DROPPED — /RETRACTOR/SPRING has one limit cell, "
                        "Force, and it already carries LMTFRC. On Tens_typ 1 "
                        "and 5 the pretensioner deactivates on FORCE "
                        "(material_flow.F:548), never on accumulated pull-in.")
        state.retractor_ids.append((r.sbrid, f"RETRACTOR_{r.sbrid}"))
        lines += _emit_retractor(
            r.sbrid, f"RETRACTOR_{r.sbrid}", r.sbid, r.sbrnid, r.lfed,
            sens1, r.pull, fct1, fct2,
            pret_sens, tens_typ, force, fct3)
    for p in sorted(state.seatbelt_pretensioners, key=lambda x: x.sbprid):
        if p.sbprid in claimed:
            continue
        if p.sbprty in _PRETENSIONER_SPRING_SBRID:
            state.warn(
                f"*ELEMENT_SEATBELT_PRETENSIONER {p.sbprid}: SBPRTY="
                f"{p.sbprty}, so its card-2 SBRID={p.sbrid} is a SPRING "
                "ELEMENT id, not a retractor (Vol I "
                "*ELEMENT_SEATBELT_PRETENSIONER, SBRID). "
                + _PRETENSIONER_UNSUPPORTED[p.sbprty]
                + ", so it is DROPPED whole and the belt is NOT pre-tensioned. "
                "It is deliberately kept out of the retractor map as well: an "
                "element id that happens to equal a retractor id would "
                "otherwise take that retractor's ONE card-3 slot and push its "
                "real pretensioner out.")
            continue
        state.warn(
            f"*ELEMENT_SEATBELT_PRETENSIONER {p.sbprid}: its card-2 SBRID="
            f"{p.sbrid} names no converted *ELEMENT_SEATBELT_RETRACTOR, so "
            "there is no card 3 to fold it onto and it is DROPPED. A "
            "pretensioner is not an entity of its own in Radioss — Sens_ID2, "
            "Tens_typ, Force and Fct_ID3 are cells on /RETRACTOR/SPRING — so "
            "it cannot be written without one.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Accelerometers
# ─────────────────────────────────────────────────────────────────────────────

def _make_seatbelt_accelerometers(state: ConversionState) -> List[str]:
    """*ELEMENT_SEATBELT_ACCELEROMETER -> /ACCEL (+ /SKEW/MOV, + /ADMAS/0).

    LS-DYNA's accelerometer is a THREE-NODE triad (x along N1->N2, z along
    x cross N1->N3, y = z cross x) that reports the acceleration of N1 in that
    co-rotating frame. Radioss's /ACCEL is one node plus a skew, so the triad
    becomes a /SKEW/MOV on (N1, N2, N3) — the two conventions are 1:1, the same
    identity *DEFINE_COORDINATE_NODES already relies on.

    The skew is written only when BOTH N2 and N3 exist, which is dyna2rad's
    gate as well (``convertelements.cxx:453``); without it the /ACCEL reports
    GLOBAL components, which is what LS-DYNA's INTOPT=0 does anyway.

    ``MASS`` becomes an ``/ADMAS/0`` over a /GRNOD of the THREE nodes: LS-DYNA
    distributes the accelerometer mass equally over N1, N2 and N3, and
    ``/ADMAS/0`` "adds Mass to EACH node in the group", so the per-node value
    is ``MASS/3`` and the total is MASS. dyna2rad puts the WHOLE mass on N1
    alone (``convertelements.cxx:471-481``, a one-entry ``/ADMAS/5``), which
    triples the mass at that node and puts none at the other two — and it
    writes the card even when MASS is 0, which every corpus deck's is.
    """
    if not state.seatbelt_accels:
        return []
    lines: List[str] = []
    n_accel = 0
    n_skew = 0
    n_mass = 0
    total = 0.0
    for a in sorted(state.seatbelt_accels, key=lambda x: x.sbacid):
        label = f"*ELEMENT_SEATBELT_ACCELEROMETER {a.sbacid}"
        if a.nid1 <= 0 or a.nid1 not in state.nodes:
            state.warn(
                f"{label}: NID1={a.nid1} names no node in the converted deck, "
                "so no /ACCEL is written and the channel is lost. dyna2rad "
                "skips the card here too, without a word "
                "(convertelements.cxx:448).")
            continue
        skew_id = 0
        have23 = (a.nid2 in state.nodes and a.nid3 in state.nodes
                  and a.nid2 > 0 and a.nid3 > 0)
        if have23:
            # Deferred import: mesh.py reads the seatbelt part-id helpers out
            # of common.py, so importing it at module scope here would close
            # the cycle. The /SKEW/MOV emitter is the only thing this module
            # needs from it, and one call per accelerometer is not a hot path.
            from .mesh import _emit_skew_mov
            skew_id = state.reserve_skew_id(state.next_id())
            lines += _emit_skew_mov(
                skew_id, f"ACCELEROMETER_{a.sbacid}_FRAME",
                a.nid1, a.nid2, a.nid3)
            n_skew += 1
        elif a.nid2 or a.nid3:
            state.warn(
                f"{label}: NID2={a.nid2} NID3={a.nid3} — one of the triad's "
                "nodes is missing from the converted deck, so no /SKEW/MOV is "
                "built and the /ACCEL reports GLOBAL components instead of the "
                "local ones. That matches LS-DYNA's own INTOPT=0 behaviour but "
                "not INTOPT=1.")
        if a.igrav:
            state.warn(
                f"{label}: IGRAV={a.igrav} is DROPPED. It asks LS-DYNA to "
                "remove gravity components from the reported acceleration "
                "(and, above 1, to do so on a curve); Radioss's /ACCEL has "
                "Node, Iskew and Fcut only, and reports the node's TOTAL "
                "acceleration. On a deck with a /GRAV the recorded channel "
                "therefore carries the 1 g the deck applies. dyna2rad drops it "
                "silently.")
        if a.intopt:
            state.warn(
                f"{label}: INTOPT={a.intopt} is DROPPED. It selects whether "
                "LS-DYNA integrates the reported VELOCITIES from the global or "
                "the local accelerations; Radioss records the acceleration "
                "only and the T01's velocity channels come from the node "
                "itself, so the choice has no expressible counterpart. "
                "dyna2rad drops it silently.")
        state.accel_ids.add(a.sbacid)
        # Recorded AT the line that writes the card (the #106 rule): a
        # /TH/ACCEL naming an accelerometer the deck does not define is
        # refused, and every `continue` above skips one.
        state.th_accel_ids.append((a.sbacid, f"ACCELEROMETER_{a.sbacid}"))
        n_accel += 1
        lines += _emit_accel(
            a.sbacid, f"ACCELEROMETER_{a.sbacid}", a.nid1, skew_id)
        if a.mass > 0.0:
            # Over the THREE nodes, MASS/3 each — LS-DYNA distributes it
            # equally. /ADMAS/0 adds its value to EACH node of the /GRNOD.
            nids = sorted({n for n in (a.nid1, a.nid2, a.nid3)
                           if n > 0 and n in state.nodes})
            # next_grnod_id, not next_id: k2rad re-emits every user *SET_NODE
            # under its own SID, so a deck with a *SET_NODE at or above the
            # auto-id base (90001) would land on this group's id and the
            # starter answers ERROR 79 over the merged /GRNOD table. A no-op
            # vs next_id() on any deck without one.
            grnod_id = state.next_grnod_id()
            admas_id = state.next_id()
            per_node = a.mass / len(nids)
            lines += _emit_grnod_node(
                grnod_id, f"ACCELEROMETER_{a.sbacid}_MASS_NODES", nids)
            lines += [
                f"/ADMAS/0/{admas_id}",
                f"ACCELEROMETER_{a.sbacid}_MASS",
                "#               MASS   grnd_ID",
                f"{_f(per_node)}{_i(grnod_id)}",
                HDR,
            ]
            n_mass += 1
            total += per_node * len(nids)
    if lines:
        note = (f"*ELEMENT_SEATBELT_ACCELEROMETER: {n_accel} /ACCEL "
                f"emitted ({n_skew} with a /SKEW/MOV triad from "
                "NID1/NID2/NID3)")
        if n_mass:
            note += (f", {n_mass} carrying an /ADMAS/0 (total added mass "
                     f"{total:g}, split equally over the triad as LS-DYNA "
                     "does)")
        note += (", each recorded by the /TH/ACCEL group below — an /ACCEL "
                 "on its own writes nothing to the T01.")
        state.warn(note)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# 2D belts: /MAT/LAW119 + the synthesized /PROP/TYPE9 the law demands
# ─────────────────────────────────────────────────────────────────────────────

def _belt_curves_intersect(state: ConversionState, load: int,
                           unload: int) -> bool:
    """Do the LAW119 loading and unloading curves CROSS at a positive abscissa?

    A Radioss-only requirement with no LS-DYNA counterpart, and a hard starter
    error when it fails: ``law119_upd.F:105`` runs ``TABLE_INTERS`` over the
    pair and answers ``ERROR 3081 -- NO INTERSECTION FOUND BETWEEN LOADING AND
    UNLOADING CURVES`` when the result is ``XINT == 0 .or. YINT == 0``. The
    intersection is how the law anchors its hysteresis loop; LS-DYNA imposes no
    such rule, and neither does LAW114 on the 1D route, so an ORDINARY LS-DYNA
    pair — unloading everywhere below loading, both leaving the origin —
    converts field-for-field correctly and still refuses to start. MEASURED:
    loading (0,0)(0.1,1000)(0.2,3000) with unloading (0,0)(0.1,800)(0.2,2600)
    gives ``ERROR ID : 3081``.

    This is ``func_inters.F:398-454`` transcribed: first a common-POINT pass
    over the two point lists from their second point on, then a segment-crossing
    pass, both requiring ``S1 > 0``. ``FAC1``/``FAC2`` are dropped because THIS
    WRITER always emits ``Fcoeft1 = Fcoeft2 = 0`` (see the
    :func:`_emit_mat_law119` call in :func:`_make_seatbelt_2d_materials`), so
    ``hm_read_mat119.F`` defaults each to 1 and multiplies both by 1e-2 —
    giving the two curves the SAME positive factor — and a common positive
    ordinate scale changes neither ALPHA, nor BETA, nor whether YINT is zero.
    The reader reads ``Fcoeft1`` and ``Fcoeft2`` as two INDEPENDENT cells
    (``hm_read_mat119.F:113-114``); they coincide here only because both are
    left blank, so a future writer that states either one has to scale the
    point lists below before comparing them.
    ``state.curves[...].pts`` are already SFA/SFO-scaled at parse time, which is
    exactly what the /FUNCT carries.
    """
    c1 = state.curves.get(load)
    c2 = state.curves.get(unload)
    if c1 is None or c2 is None or len(c1.pts) < 2 or len(c2.pts) < 2:
        return True                       # nothing to judge; let the deck speak
    p1, p2 = c1.pts, c2.pts
    for j in range(1, len(p1)):
        s1, t1 = p1[j]
        if s1 <= 0.0:
            continue
        for k in range(1, len(p2)):
            x1, y1 = p2[k]
            if x1 == s1 and y1 == t1:
                return y1 != 0.0
    for j in range(1, len(p1)):
        s1, t1 = p1[j - 1]
        s2, t2 = p1[j]
        if s1 <= 0.0:
            continue
        for k in range(1, len(p2)):
            x1, y1 = p2[k - 1]
            x2, y2 = p2[k]
            if x2 < s1 or s2 < x1:
                continue
            ax, ay = x2 - x1, y2 - y1
            bx, by = s1 - s2, t1 - t2
            dm = ay * bx - ax * by
            if dm == 0.0:
                continue                  # parallel segments
            cx, cy = s1 - x1, t1 - y1
            alpha = (bx * cy - by * cx) / dm
            beta = (ax * cy - ay * cx) / dm
            if 0.0 <= alpha < 1.0 and -1.0 < beta <= 0.0:
                xint = x1 + alpha * ax
                yint = y1 + alpha * ay
                return xint != 0.0 and yint != 0.0
    return False


def _screen_belt_2d_curves(state: ConversionState, label: str,
                           fct_load: int, fct_uload: int) -> int:
    """``fct_uload``, dropped when it would trip ERROR 3081.

    The house answer to a Radioss-only rule the deck cannot satisfy: keep the
    deck STARTABLE and name the loss, the same choice
    :func:`_resolve_belt_curve` makes for a curve the deck never defines.
    Dropping ``FUN_UL`` puts the law on ``FUNC2 = 0``, which the reader reads as
    "no unloading curve" (``hm_read_mat119.F:126`` also collapses
    ``FUNC2 == FUNC1`` to 0) and ``law119_upd.F:88`` then skips the whole
    intersection test — the belt unloads elastically along the loading curve
    instead of down the unloading one, so the HYSTERESIS is lost while the
    backbone is exact.
    """
    if fct_load <= 0 or fct_uload <= 0 or fct_uload == fct_load:
        return fct_uload
    if _belt_curves_intersect(state, fct_load, fct_uload):
        return fct_uload
    state.warn(
        f"{label}: the loading curve {fct_load} and the unloading curve "
        f"{fct_uload} never CROSS at a positive abscissa, so ULCID is DROPPED. "
        "/MAT/LAW119 anchors its hysteresis loop on that intersection and the "
        "starter refuses the whole deck without one (ERROR 3081, "
        "law119_upd.F:105 -> TABLE_INTERS). LS-DYNA imposes no such rule — and "
        "neither does the 1D route's /MAT/LAW114 — so this is a difference "
        "between the two belt models, not a deck error. The belt now unloads "
        "ELASTICALLY along the loading curve: the backbone force is unchanged "
        "and the dissipated (hysteresis) energy is LOST. Give the two curves a "
        "common point at a strain the belt actually reaches if the unloading "
        "branch matters.")
    return 0


def _make_seatbelt_2d_materials(state: ConversionState) -> List[str]:
    """The /MAT/LAW119 cards of every 2D (shell) belt part.

    Emitted here rather than in ``materials.py`` for the reason the fabric laws
    are: the law and its property are ONE decision (``/MAT/LAW119`` declares
    ``SHELL_ORTHOTROPIC`` and only a ``/PROP/TYPE9``-class property satisfies
    it, starter ERROR 3047), so splitting them across two files would put the
    two halves of one rule in two places.

    What the STARTER does afterwards is worth knowing, because it means this
    module must NOT also emit springs for a 2D belt:
    ``starter0.F:782-803`` -> ``hm_convert_2d_elements_seatbelt.F`` walks every
    /PART whose material is LAW119 and generates, by itself, a /PROP/TYPE23, a
    /MAT/LAW114 copying ``MAT_RHO LMIN STIFF1 DAMP1 Fcoeft1 FUN_L FUN_UL``, a
    /PART and one /SPRING per unique shell edge pair — and a companion
    /TH/SPRING for every /TH/SHEL that named those shells. Emitting LAW119 +
    TYPE9 gets all of that for free.
    """
    pids = _seatbelt_2d_part_ids(state)
    if not pids:
        return []
    mids = sorted({state.parts[p].mid for p in pids})
    lines = ["#-  2D SEATBELT MATERIALS (*MAT_SEATBELT on *SECTION_SHELL):",
             HDR]
    for mid in mids:
        mat = state.mat_seatbelt[mid]
        label = f"*MAT_SEATBELT{'_2D' if mat.is_2d else ''} {mid}"
        if not mat.is_2d:
            state.warn(
                f"{label} is on a *SECTION_SHELL part, so it converts to "
                "/MAT/LAW119 (the 2D belt law) even though the keyword has no "
                "_2D suffix — the SECTION decides the law, not the keyword "
                "(dyna2rad convertmats.cxx:517-526 branches on the property "
                "keyword for exactly this reason). Cards 3 and 4 (ECOAT, "
                "TCOAT, EB, PRBA, GAB) are _2D-only, so this material states "
                "none of the weft or coating data and the reader's own "
                "defaults are used for all of it.")
        e22, nu12, fscale22 = _seatbelt_2d_weft(state, mat)
        fct_load = _resolve_belt_curve(state, mat.llcid, "LLCID", label)
        fct_uload = _resolve_belt_curve(state, mat.ulcid, "ULCID", label)
        if mat.gab <= 0.0:
            state.warn(
                f"{label}: GAB is not stated, so /MAT/LAW119 G12 is left 0 and "
                "the reader derives it as E11/(2*(1+NU12)) "
                "(create_seatbelt.F:908). LS-DYNA's own default is "
                "EA/(2*(1+PRBA)) with EA only ONE PERCENT of the "
                "curve-derived modulus, so the converted belt is about 100x "
                "STIFFER IN SHEAR than LS-DYNA's default. Neither converter "
                "can pre-compute the LS-DYNA value: E11 = K/section is "
                "resolved inside the starter from the shell thickness and the "
                "belt's strip width (create_seatbelt.F:896). State GAB "
                "explicitly on card 4 if the shear response matters.")
        for name, val, why in (
                ("SCOAT", mat.scoat,
                 "the coating's YIELD stress. /MAT/LAW119's coating is purely "
                 "elastic — ECOAT, NUCOAT and TCOAT feed A1C/A2C/GC and "
                 "nothing else (hm_read_mat119.F:166-168) — so the coating "
                 "never yields and carries load it should have shed"),
                ("PRAB", mat.prab,
                 "the MAJOR in-plane Poisson ratio. Radioss takes NU12 alone "
                 "and DERIVES the other as N21 = N12*100*Fscale22 "
                 "(create_seatbelt.F:903), so a PRAB inconsistent with that "
                 "derivation cannot be written"),
                ("P1DOFF", mat.p1doff,
                 "the offset applied to the first belt element's node "
                 "numbering for the 2D-to-1D conversion, which is an LS-DYNA "
                 "bookkeeping field with no model meaning in Radioss"),
                ("FORM", float(mat.form),
                 "the belt formulation selector (it names a *MAT_FABRIC FORM) "
                 "and /MAT/LAW119 has one formulation. NOTE that FORM is "
                 "still READ, in _seatbelt_2d_re: it decides which of CSE's "
                 "two OPPOSITE meanings applies")):
            if val:
                state.warn(f"{label}: {name}={val:g} is DROPPED — {why}.")
        if (mat.ecoat or mat.tcoat) and mat.form != -14:
            # "Young's modulus of coat material FOR FORM = -14" / "Thickness of
            # coat material FOR FORM = -14" (Vol II *MAT_SEATBELT). LS-DYNA
            # reads the coating only on that formulation; /MAT/LAW119 has no
            # such gate and applies EC/TC whenever they are non-zero, so the
            # converted belt gains a coating the source deck does not have.
            state.warn(
                f"{label}: ECOAT={mat.ecoat:g} TCOAT={mat.tcoat:g} are stated "
                f"but FORM={mat.form} is not -14. LS-DYNA reads the coating "
                "fields only for FORM = -14 (Vol II *MAT_SEATBELT: 'Young's "
                "modulus of coat material FOR FORM = -14'), so in the source "
                "deck they are INERT — while /MAT/LAW119 has no such gate and "
                "applies EC/TC whenever they are non-zero "
                "(hm_read_mat119.F:166-168 A1C/A2C/GC). They are written "
                "through as stated, so the converted belt is STIFFER than the "
                "LS-DYNA one by the coating's contribution. Blank ECOAT and "
                "TCOAT, or set FORM=-14, if that is not intended.")
        if mat.damp:
            state.warn(
                f"{label}: DAMP={mat.damp:g} is a FRACTION of critical damping "
                "(LS-DYNA's Rayleigh coefficient for the shell belt, default "
                "0.1 = 10 %). /MAT/LAW119's C is a dimensional damping "
                "coefficient, not a fraction, so the value cannot be copied "
                "across; C is left 0 and the reader supplies its own default "
                "of 30 % critical. The converted belt is therefore damped "
                "about 3x more than the deck asked for. There is no cell that "
                "states a fraction, so this cannot be repaired in the deck "
                "either — it is a difference between the two solvers' belt "
                "models.")
        lines += _emit_mat_law119(
            mid, f"SEATBELT_2D_{mid}",
            # RHO_I is a LINEIC MASS on LAW119 (the cfg dimensions MAT_RHO as
            # lineic_mass and the starter echoes MASS PER UNIT LENGTH), so MPUL
            # goes in unchanged and create_seatbelt.F:894 divides by the belt
            # section it computes itself.
            mat.mpul, mat.lmin,
            # K = 0: law119_upd raises it off the curve slope exactly as
            # law114_upd does, which is the correct tangent and needs no
            # section (unknown here).
            0.0, 0.0, _seatbelt_2d_re(state, mat),
            fct_load,
            _screen_belt_2d_curves(state, label, fct_load, fct_uload),
            0.0, 0.0, 0,
            e22, nu12, mat.gab, fscale22,
            mat.ecoat,
            # NUCOAT left 0 on purpose: hm_read_mat119.F:165 then sets it to
            # NU12, which is what a coating with no stated Poisson ratio
            # should get. dyna2rad writes PRBA into this cell instead of into
            # NU12 (convertmats.cxx:11049 CopyValue(..., "PRBA", "VC")), so
            # after its conversion the BELT's minor Poisson ratio is 0 and the
            # COATING carries it.
            0.0, mat.tcoat)
    return lines


def _emit_seatbelt_2d_props(state: ConversionState) -> List[str]:
    """The synthesized /PROP/TYPE9 (SH_ORTH) of every 2D belt part.

    ``Ip = 24`` — the reference direction comes from the property SKEW rather
    than from a global vector — because the starter FORCES it anyway and says
    so: ``WARNING 2076 /PROP/TYPE9 USED WITH 2D SEATBELT MATERIAL - IP
    AUTOMATICALLY SET TO 24``. Writing it removes the warning and makes the
    deck state what it means. dyna2rad writes 24 as well
    (``convertprops.cxx:4157``).

    ``Ishell = 12`` (QEPH, no hourglass) and ``Ismstr = 11`` are dyna2rad's
    choices (``:4159-4160``) and are kept: a belt is a membrane that folds, so
    a hourglass-free formulation with full geometric non-linearity is the right
    pair, and QEPH has no hourglass energy to leak.
    """
    if not state.seatbelt_prop_ids:
        return []
    lines = ["#-  2D SEATBELT PROPERTIES (/MAT/LAW119 parts):", HDR]
    for pid, prop_id in sorted(state.seatbelt_prop_ids.items()):
        part = state.parts[pid]
        mat = state.mat_seatbelt.get(part.mid)
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_shells.get(secid)
        thick = sec.t1 if sec is not None and sec.t1 > 0 else 0.0
        if thick <= 0.0:
            state.warn(
                f"2D seatbelt part {pid}: *SECTION_SHELL {secid} states no "
                f"positive thickness (T1={thick:g}), so the synthesized "
                "/PROP/TYPE9 carries Thick=0. The whole belt is sized off it — "
                "create_seatbelt.F computes the 2D SEATBELT SECTION as "
                "thickness x strip width and then E11 = K/section — so a zero "
                "thickness makes the section 0 and the modulus undefined.")
        # Three integration points when the belt is COATED, one otherwise:
        # the coating is a surface layer, so it needs points off the midplane
        # to be felt at all (dyna2rad convertprops.cxx:4154).
        nip = 3 if (mat is not None and mat.ecoat > 0.0
                    and mat.tcoat > 0.0) else 1
        b10, b20 = " " * 10, " " * 20
        lines += [
            f"/PROP/TYPE9/{prop_id}",
            f"SEATBELT_2D_PART_{pid}",
            "#   Ishell    Ismstr     Ish3n    Idrill"
            "                            P_Thick_Fail",
            f"{_i(12)}{_i(11)}{_i(3)}{_i(0)}{b20}{_f(0.0)}",
            "#                 Hm                  Hf                  Hr"
            "                  Dm                  Dn",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.25)}{_f(0.0)}",
            "#        N   ISTRAIN               Thick              Ashear"
            "     Iskew    ITHICK     IPLAS",
            f"{_i(nip)}{_i(0)}{_f(thick)}{_f(0.0)}{_i(0)}{_i(0)}{_i(0)}",
            "#                 Vx                  Vy                  Vz"
            "                 Phi                  Ip",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{b10}{_i(24)}",
            HDR,
        ]
        state.warn(
            f"2D seatbelt part {pid}: /MAT/LAW119 {part.mid} on a synthesized "
            f"/PROP/TYPE9 (SH_ORTH) {prop_id} instead of the isotropic "
            f"/PROP/SHELL its *SECTION_SHELL {secid} would give it — LAW119 "
            "declares SHELL_ORTHOTROPIC (hm_read_mat119.F:218) and the "
            "isotropic property is starter ERROR 3047. The starter then "
            "converts the shells into 1D /SPRING belts itself "
            "(hm_convert_2d_elements_seatbelt.F), generating its own /PART, "
            "/PROP/TYPE23 and /MAT/LAW114 — leave id headroom above the "
            "converted deck's.")
        if sec is not None and getattr(sec, "nsid", 0):
            state.warn(
                f"2D seatbelt part {pid}: *SECTION_SHELL {secid} names an "
                f"EDGSET ({sec.nsid}), the node set whose first two nodes give "
                "the belt its flow direction. That becomes a /SKEW/MOV on the "
                "property's Iskew (dyna2rad convertprops.cxx:4177-4227); this "
                "batch leaves Iskew 0, so the starter falls back to the shell "
                "edges (n0,n1) and (n3,n2) when it builds the 1D springs "
                "(GlobalModelSdi.cpp:2400-2412). Check that the mesh's local "
                "node order runs ALONG the belt.")
        _warn_2d_belt_direction(state, pid, part.mid)
    return lines


def _edge_run(elems: List[SeatbeltElem],
              pairs: Tuple[Tuple[int, int], Tuple[int, int]]) -> int:
    """Longest RUN of edges the reader would build from one edge pair.

    The reader pushes each shell's two edges as UNORDERED pairs —
    ``GlobalModelSdi.cpp:2409-2410`` ``std::minmax(aNodeId[0], aNodeId[1])`` /
    ``std::minmax(aNodeId[3], aNodeId[2])`` — then sorts them and, at ``:2420``
    ("Create elements deleting dupplicated connectivity"), keeps ONE /SPRING
    per distinct pair. So this de-duplicates the same way before measuring, and
    ORDER is irrelevant: an interior edge that two shells share is one spring,
    not a defect.

    Returns the edge count of the largest connected group, which for the unions
    of simple paths a belt mesh produces is the length of the longest strand.
    Linear in the number of edges.
    """
    edges: Set[Tuple[int, int]] = set()
    for e in elems:
        for i, j in pairs:
            a = getattr(e, f"n{i}")
            b = getattr(e, f"n{j}")
            if a > 0 and b > 0 and a != b:
                edges.add((a, b) if a < b else (b, a))
    if not edges:
        return 0
    adj: Dict[int, List[int]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    group: Dict[int, int] = {}
    n_groups = 0
    for start in adj:
        if start in group:
            continue
        stack = [start]
        group[start] = n_groups
        while stack:
            n = stack.pop()
            for m in adj[n]:
                if m not in group:
                    group[m] = n_groups
                    stack.append(m)
        n_groups += 1
    counts = [0] * n_groups
    for a, _b in edges:
        counts[group[a]] += 1
    return max(counts)


def _warn_2d_belt_direction(state: ConversionState, pid: int,
                            mid: int) -> None:
    """A 2D belt whose local node order runs ACROSS the strip, not along it.

    The starter builds the 1D strand chain from the ``(n1,n2)`` and ``(n4,n3)``
    edge pair. When the connectivity is rotated one place those edges run
    ACROSS the strip instead, the starter groups the shells into strands of a
    different width, and ``create_seatbelt.F:756-759`` answers
    ``ERROR 2075 -- 2D SEATBELT MATERIAL IS USED FOR SEVERAL SEATBELTS with
    different section`` — one LAW119 material reaching two belt entities whose
    ``SECTION`` differs by more than 1e-5, where SECTION is the belt's WIDTH x
    thickness summed along its end frame (``:512``).

    MEASURED as a negative control: the same nodes, the same pull direction,
    connectivity rotated one place — 2 x ERROR 2075, against NORMAL TERMINATION
    (4804 cycles, 0 ERROR) for the along-the-pull ordering.

    **A repeated edge is NOT the symptom.** An earlier version of this check
    flagged any ``(n1,n2)``/``(n4,n3)`` edge that a second shell also carried,
    on the premise that a proper strip never repeats one. That premise holds
    only for a strip ONE element wide: in an n-wide strip row k's ``(n4,n3)``
    IS row k+1's ``(n1,n2)`` by construction, and the reader de-duplicates the
    pair (see :func:`_edge_run`) exactly so that it can. MEASURED false
    positive: an ordinary 2-wide x 2-long strip with ``n1->n2`` along the pull,
    told to rotate connectivity that was already right. Measured on the two
    production restraint models in the examples corpus, which hold three 2D
    belt parts between them, the old test warned on all three and this one
    warns on two — ``BELT_PA_50th_HIII_ml_br19_sr17.k`` part 66000003 (62
    shells, belt-edge runs 53 edges / 1071 mm against 17 edges / 350 mm across)
    is a correct belt and is now silent, while its part 66000002 (16 / 352 mm
    against 71 / 1446 mm) and ``04_belt_pa_030.k`` part 66000002 (269 /
    3274 mm against 349 / 4208 mm) really do run across and are still named.

    What DOES separate the two orientations is which direction the strands run
    in. Both edge pairs de-duplicate to a clean set of chains; the belt's own
    pair should give the LONG ones (a belt is longer than it is wide) and the
    perpendicular pair the short rungs. So the two are measured and the part is
    named only when the perpendicular pair wins. A square patch, where the two
    are equal, is genuinely ambiguous and is left alone — as is a single
    element, or a part whose EDGSET already states the direction.
    """
    elems = [e for e in state.seatbelt_elems if e.is_2d and e.pid == pid]
    if len(elems) < 2:
        return
    belt = _edge_run(elems, ((1, 2), (4, 3)))
    cross = _edge_run(elems, ((2, 3), (1, 4)))
    if cross <= belt:
        return
    state.warn(
        f"2D seatbelt part {pid}: the (n1,n2)/(n4,n3) edges of its "
        f"*ELEMENT_SEATBELT shells chain into strands at most {belt} element(s) "
        f"long, while the PERPENDICULAR (n2,n3)/(n1,n4) pair chains {cross} "
        "long — so the local node order runs ACROSS the strip, not along it. "
        "Those first two edges are what the starter follows to build the "
        "belt's 1D strands (hm_convert_2d_elements_seatbelt.F), so it will "
        "group these shells into strands of the wrong width and the belt "
        "entities on one material end up with different SECTIONs: "
        f"ERROR 2075 (2D SEATBELT MATERIAL {mid} IS USED FOR SEVERAL SEATBELTS "
        "with different section, create_seatbelt.F:756-759). Rotate the "
        "element connectivity so n1->n2 runs along the belt, or state the "
        "direction with an EDGSET on the *SECTION_SHELL. LS-DYNA imposes no "
        "such rule, so this is a difference between the two belt models rather "
        "than a defect in the deck.")


# ─────────────────────────────────────────────────────────────────────────────
# The section
# ─────────────────────────────────────────────────────────────────────────────

def _seatbelt_prop_ids(state: ConversionState, pids: List[int]
                       ) -> Dict[int, int]:
    """``part id -> /PROP/TYPE23 id`` for the 1D belt parts.

    The property is emitted under the SECID verbatim — the shape every
    SECID-keyed /PROP uses — EXCEPT when one ``*SECTION_SEATBELT`` is shared by
    parts whose materials give different AREAS. TYPE23's area comes from the
    MATERIAL (see :func:`_seatbelt_1d_mass`), so a shared section with two
    different belt materials is one card that has to say two things; those
    parts get minted ids instead. That is the same shared-section split
    ``_assign_fabric_props`` and the composite/ortho passes make (#120/#121),
    reached here through the material rather than through the layup.
    """
    area_by_secid: Dict[int, Set[float]] = {}
    for pid in pids:
        part = state.parts[pid]
        secid = part.secid if part.secid > 0 else pid
        mat = state.mat_seatbelt.get(part.mid)
        area = _seatbelt_1d_mass(mat)[1] if mat is not None else 1.0
        area_by_secid.setdefault(secid, set()).add(area)
    out: Dict[int, int] = {}
    split: List[int] = []
    for pid in pids:
        part = state.parts[pid]
        secid = part.secid if part.secid > 0 else pid
        if secid in state.sec_seatbelts and len(area_by_secid[secid]) == 1:
            out[pid] = secid
        else:
            out[pid] = state.next_prop_id()
            if secid in state.sec_seatbelts:
                split.append(pid)
    if split:
        state.warn(
            f"*SECTION_SEATBELT: {len(split)} part(s) {sorted(split)} share a "
            "section with siblings whose *MAT_SEATBELT states a DIFFERENT "
            "cross-sectional area A, so each gets its own /PROP/TYPE23 rather "
            "than one shared card. The area cell is what /MAT/LAW114's density "
            "is paired against (mass = Area x length x rho) and what sets "
            "XK_COMP = E x Area, so one card cannot serve both.")
    return out


def _seatbelt_inert_mat_ids(state: ConversionState,
                            pids: List[int]) -> Dict[int, int]:
    """``part id -> the /MAT/LAW114 id`` for a belt part with NO *MAT_SEATBELT.

    The INERT branch of :func:`_make_seatbelts` has to write SOME /MAT/LAW114,
    because a /PART on a /PROP/TYPE23 must name a law the starter accepts
    (ERROR 1715 otherwise). Writing it under ``part.mid`` verbatim is only safe
    while nothing else owns that id — and the case this branch exists for is
    precisely a belt part pointing at an ORDINARY material, which materials.py
    then also writes. MEASURED: a *PART on a *SECTION_SEATBELT whose MID is a
    *MAT_ELASTIC used by a shell part emits both ``/MAT/ELAST/<mid>`` and
    ``/MAT/LAW114/<mid>`` and the starter answers three errors — ``ERROR 79``
    (DUPLICATE ID, IN MATERIAL DEFINITION), then ``ERROR 1715`` and
    ``ERROR 3046``, because the /PART resolves to whichever card came first.

    So the id is reused ONLY when no other material writer owns it (the
    ``all_mat_ids`` union next_mat_id itself dodges); otherwise a fresh one is
    minted and the /PART row is repointed at it. A blank or zero MID mints too:
    ``/MAT/LAW114/0`` is not an addressable material.
    """
    owned = state.all_mat_ids()
    out: Dict[int, int] = {}
    by_mid: Dict[int, int] = {}
    repointed: List[str] = []
    for pid in pids:
        mid = state.parts[pid].mid
        if mid > 0 and mid in state.mat_seatbelt:
            continue                       # a real belt material: not this path
        if mid > 0 and mid not in owned:
            out[pid] = mid                 # free id, keep it addressable
            continue
        if mid in by_mid:
            out[pid] = by_mid[mid]
            continue
        new = state.next_mat_id()
        by_mid[mid] = new
        out[pid] = new
        repointed.append(f"part {pid}: MID {mid} -> /MAT/LAW114/{new}")
    if repointed:
        state.warn(
            "*ELEMENT_SEATBELT: the INERT belt material(s) of "
            + "; ".join(repointed[:6])
            + (" ..." if len(repointed) > 6 else "")
            + " could not be written under the *PART's own MID — that id is "
            "already emitted as an ordinary /MAT (or is 0), and two cards on "
            "one id is starter ERROR 79 (DUPLICATE ID, IN MATERIAL "
            "DEFINITION) followed by ERROR 1715 / ERROR 3046 on the /PART. A "
            "fresh /MAT id is minted and the /PART row points at it instead, "
            "so the ordinary material keeps serving its own parts.")
    return out


def _make_seatbelts(state: ConversionState) -> List[str]:
    """*ELEMENT_SEATBELT and its four devices -> the whole 1D restraint chain.

    Section order inside the block matters only for readability (the starter
    resolves entities by id), but the ORDER OF RESOLUTION does not: the sensors
    are built first because their ids are USER ids that the retractors name
    verbatim, and building them first also pins those ids before any auto-id
    is drawn for a delayed copy or an OR gate. That is dyna2rad's own ordering
    constraint (``convertelements.cxx:33-48``: elements, accelerometer, sensor,
    slipring, retractor) and it is a real one.
    """
    pids = sorted(_seatbelt_part_ids(state))
    have_devices = (state.seatbelt_sliprings or state.seatbelt_retractors
                    or state.seatbelt_sensors or state.seatbelt_accels
                    or state.seatbelt_pretensioners)
    if not pids and not have_devices:
        return []
    lines: List[str] = ["#-  SEATBELTS / RESTRAINTS:", HDR]

    belts_by_pid: Dict[int, List[SeatbeltElem]] = {}
    for e in state.seatbelt_elems:
        if not e.is_2d:
            belts_by_pid.setdefault(e.pid, []).append(e)
    prop_of = _seatbelt_prop_ids(state, pids)
    inert_of = _seatbelt_inert_mat_ids(state, pids)
    emitted_eids: Set[int] = set()
    # The /PROP/TYPE23 and the /MAT/LAW114 are written ONCE PER ID, not once
    # per part. A shoulder-belt *PART and a lap-belt *PART on one
    # *SECTION_SEATBELT and one *MAT_SEATBELT is the ordinary two-strand
    # restraint layout, and _seatbelt_prop_ids DELIBERATELY hands both parts
    # the same prop id when their areas agree — so without these two sets the
    # normal production deck emits /PROP/TYPE23/<secid> and /MAT/LAW114/<mid>
    # twice and the starter refuses it with ERROR 79 (DUPLICATE ID) over both
    # tables. MEASURED on a two-part probe: 2 ERROR(S), ERROR TERMINATION.
    # The /PART row and the /SPRING block still go out per part.
    written_props: Set[int] = set()
    written_mats: Set[int] = set()
    # The per-SECTION note belongs to the card, not to the part that happens to
    # reach it first (the per-MATERIAL ones ride on `first_mat`): a shared
    # section would otherwise repeat its AREA/THICK note once per belt part.
    noted_secs: Set[int] = set()
    belts_by_mid: Dict[int, List[SeatbeltElem]] = {}
    for pid in pids:
        belts_by_mid.setdefault(state.parts[pid].mid, []).extend(
            belts_by_pid.get(pid, []))

    for pid in pids:
        part = state.parts[pid]
        belts = belts_by_pid.get(pid, [])
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_seatbelts.get(secid)
        mat = state.mat_seatbelt.get(part.mid)
        prop_id = prop_of[pid]
        mat_id = mat.mid if mat is not None else inert_of[pid]
        label = f"*ELEMENT_SEATBELT part {pid}"
        first_prop = prop_id not in written_props
        first_mat = mat_id not in written_mats
        written_props.add(prop_id)
        written_mats.add(mat_id)
        if mat is None:
            # The part was CLAIMED (its section is a *SECTION_SEATBELT), so
            # nothing else will write it — skipping here would delete the
            # /PART along with every *SET_PART member and /GRNOD/PART scope
            # that names it. An INERT belt on a token material keeps the deck
            # startable and the ids addressable, the same answer the
            # discrete-beam connector gives an unsized part.
            state.warn(
                f"{label}: MID {part.mid} is not a *MAT_SEATBELT / *MAT_B01, "
                "so there is no MPUL, no LMIN and no force-strain curve to "
                "build the belt from. Its element(s) are written as an INERT "
                "/SPRING on a /MAT/LAW114 with no curve and no stiffness, and "
                "the material is LOST — the belt carries no force at all. Put "
                "a *MAT_SEATBELT on the part, or move it off the "
                "*SECTION_SEATBELT.")
            rho, area = 1.0e-9, 1.0
            if first_prop:
                lines += _emit_prop_type23(prop_id,
                                           f"SEATBELT_PROP_{prop_id}", area)
            if first_mat:
                lines += _emit_mat_law114(
                    mat_id, f"SEATBELT_INERT_{mat_id}", rho, 0.0,
                    0.0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                    0.0)
        else:
            rho, area = _seatbelt_1d_mass(mat)
            if sec is not None and (sec.area or sec.thick) \
                    and secid not in noted_secs:
                noted_secs.add(secid)
                state.warn(
                    f"*SECTION_SEATBELT {secid}: AREA={sec.area:g} "
                    f"THICK={sec.thick:g} are DROPPED. Both are LS-DYNA "
                    "CONTACT numbers — AREA sets the contact stiffness (its "
                    "default is 0.01, a search parameter, not a webbing "
                    "section) and THICK the contact thickness — while "
                    "/PROP/TYPE23's Area cell is a MASS and STIFFNESS area "
                    "(rinit3.F:474 mass = Area x length x rho; "
                    "r23l114def3.F:224 XK_COMP = E x Area). The belt's real "
                    f"section comes from *MAT_SEATBELT {mat.mid} card 2 (A), "
                    f"so Area={area:g} is written. The belt's NODES do reach "
                    "the secondary side of a *CONTACT that scopes this part "
                    "(part, part-set or node-set spelling alike), but a "
                    "/SPRING has no thickness of its own: state the contact "
                    "clearance as Gapmin on that /INTER, because the THICK "
                    "that used to carry it has no cell to land in.")
            if mat.is_2d and first_mat:
                state.warn(
                    f"*MAT_SEATBELT_2D {mat.mid} is on a *SECTION_SEATBELT "
                    "part, so it converts to /MAT/LAW114 (the 1D belt spring "
                    "law) despite the _2D suffix — the SECTION decides the "
                    "law, exactly as dyna2rad does (convertmats.cxx:517-526). "
                    "Its cards 3 and 4 (ECOAT/TCOAT/SCOAT/EB/PRBA/PRAB/GAB) "
                    "describe a woven MEMBRANE and have no meaning on a "
                    "spring, so they are dropped whole.")
            if mat.cse and not mat.has_card3 and first_mat:
                state.warn(
                    f"*MAT_SEATBELT {mat.mid}: CSE={mat.cse:g} applies to the "
                    "SHELL belt only ('Eliminate compressive stresses in "
                    "shell fabric', Keyword971_R8.0/MAT/SB_MAT.cfg:142-147) "
                    "and this material is on a 1D belt, where compression is "
                    "governed by E and FMAX from card 2 instead. Nothing is "
                    "lost; the field is inert on this route.")
            if mat.damp and first_mat:
                state.warn(
                    f"*MAT_SEATBELT {mat.mid}: DAMP={mat.damp:g} is LS-DYNA's "
                    "RAYLEIGH coefficient for SHELL belts; on a 1D belt "
                    "LS-DYNA computes the damping itself and caps it at "
                    "0.1 x mass x v_rel/dt. /MAT/LAW114's C is left 0 for "
                    "exactly that reason, and the starter then computes its "
                    "own belt damping and echoes it ('SEATBELTS DEFAULT "
                    "DAMPING COMPUTATION'). This is a MATCH, not a loss.")
            fmax, mmax = mat.f, mat.m
            young = mat.e
            if mat.has_card2 and mat.a <= 0.0 and young > 0.0 and first_mat:
                # Card 2 present, E stated, A BLANK (its LS-DYNA default is
                # 0.0). LS-DYNA then has NO compression stiffness at all: the
                # model is E x A = 0, and the shear area AS defaults to A = 0
                # with it. Radioss reads the same product the other way round
                # — XK_COMP = E x Area, r23l114def3.F:224 — and this belt's
                # Area cell carries the neutral 1 that _seatbelt_1d_mass uses
                # to keep rho x Area == MPUL, so writing E through would
                # INVENT a compression stiffness of E x 1 that neither the
                # deck nor LS-DYNA has. The unstated quantity is dropped and
                # named rather than filled in.
                state.warn(
                    f"*MAT_SEATBELT {mat.mid}: card 2 states E={young:g} but "
                    "leaves A blank (LS-DYNA default 0.0), so LS-DYNA's "
                    "bending/compression model is E x A = 0 — inert. There is "
                    "no cross-section to pair E with, and /MAT/LAW114 forms "
                    "XK_COMP = E x Area against the neutral Area=1 this belt "
                    "carries for its mass split, so E is written as 0 rather "
                    "than inventing a compression stiffness of E x 1. State A "
                    "on card 2 if the belt is meant to take compression.")
            if mat.has_card2 and mat.a <= 0.0:
                young = 0.0
            if not mat.has_card2:
                # E == 0 and no card 2: FMAX and MMAX stay 0, which makes the
                # compression tangent E*Area = 0 and the clamp 0 — a
                # TENSION-ONLY belt, exactly LS-DYNA's "zero forces being
                # generated whenever the strain becomes negative".
                # hm_read_mat114.F:169-170 has the F_MAX = INFINITY default
                # COMMENTED OUT, so a blank FMAX really is 0; writing a
                # non-zero one here would give the belt compressive strength
                # the deck never asked for.
                fmax = mmax = 0.0
            if first_prop:
                lines += _emit_prop_type23(
                    prop_id, sec.title if sec is not None
                    else f"SEATBELT_PROP_{prop_id}", area)
            if first_mat:
                lines += _emit_mat_law114(
                    mat.mid, f"SEATBELT_{mat.mid}", rho, mat.lmin,
                    # K and C left 0: law114_upd.F:80,126 raises K to the
                    # maximum curve slope / Xscale (the exact tangent, and
                    # WARNING 1640 if a smaller one is stated), and the
                    # starter computes the belt damping when C is 0.
                    0.0, 0.0,
                    _resolve_belt_curve(state, mat.llcid, "LLCID",
                                        f"*MAT_SEATBELT {mat.mid}"),
                    _resolve_belt_curve(state, mat.ulcid, "ULCID",
                                        f"*MAT_SEATBELT {mat.mid}"),
                    # Xscale and Fscale left 0 (reader default 1.0): the
                    # LS-DYNA curve is already force vs ENGINEERING STRAIN,
                    # which is what LAW114 reads, so there is nothing to
                    # rescale.
                    0.0, 0.0,
                    young, mat.i, mat.j, fmax, mmax, mat.as_, mat.r)
                # Over EVERY belt element on this material, not just this
                # part's: the LMIN geometry check belongs to the card, and a
                # shared material would otherwise report each sibling part's
                # short elements once per part.
                _warn_lmin_geometry(state, mat,
                                    belts_by_mid.get(mat.mid, belts),
                                    f"*MAT_SEATBELT {mat.mid}")
        lines += [
            f"/PART/{pid}",
            part.title or f"SEATBELT_PART_{pid}",
            # A /PART on a /PROP/TYPE23 MUST name a material whose law is
            # 108/113/114/135 — hm_read_part.F answers ERROR 179 / ERROR 1715
            # otherwise. That is why the belt material is written in this
            # section and not left to materials.py: the two are one card pair.
            f"{_i(prop_id)}{_i(mat_id)}{_i(0)}",
        ]
        if belts:
            lines += [f"/SPRING/{pid}", "# sprg_ID  node_ID1  node_ID2"]
            dropped: List[int] = []
            for e in sorted(belts, key=lambda x: x.eid):
                if (e.n1 not in state.nodes or e.n2 not in state.nodes
                        or e.n1 <= 0 or e.n2 <= 0):
                    dropped.append(e.eid)
                    continue
                lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}")
                # Registered AT the line that writes the row, never from
                # `belts`: the `continue` above skips an element whose nodes
                # the deck does not define, and a /TH/SPRING naming an id that
                # was never written is starter ERROR 69 — producer 8 of 9.
                state.spring_elem_ids.add(e.eid)
                emitted_eids.add(e.eid)
            if dropped:
                state.warn(
                    f"{label}: {len(dropped)} belt element(s) {dropped[:8]}"
                    + (" ..." if len(dropped) > 8 else "")
                    + " name a node the converted deck does not define and are "
                    "DROPPED. A /SPRING on a missing node is starter ERROR 78 "
                    "and refuses the whole run.")
        lines.append(HDR)
        if mat is not None:
            state.warn(
                f"{label}: *MAT_SEATBELT {mat.mid} -> /MAT/LAW114 + "
                f"/PROP/TYPE23/{prop_id} + {len(belts)} /SPRING element(s). "
                f"MPUL={mat.mpul:g} is carried as rho={rho:g} x Area={area:g} "
                "(the engine's mass is Area x max(L0,LMIN) x rho, "
                "rinit3.F:464,474). The force-strain curve is passed through "
                "UNCHANGED: LS-DYNA's LLCID and Radioss's fct_load are both "
                "force vs ENGINEERING STRAIN, so Xscale and Fscale stay 1 and "
                "no transform is applied"
                + ("" if mat.has_card2 else
                   ". With no card 2 (E=0) the belt is TENSION-ONLY, which is "
                   "what LS-DYNA's 1D belt always is") + ".")

    _warn_slack(state, [e for e in state.seatbelt_elems if not e.is_2d])
    _warn_orphan_belt_elements(state, emitted_eids)
    _warn_retractor_backlink(state, emitted_eids)
    _warn_implicit_belt_stiffness(state, emitted_eids)

    belt_2d_eids = {e.eid for e in state.seatbelt_elems if e.is_2d}
    pool = _SensorPool(state)
    pool.build()
    device_lines = _make_seatbelt_accelerometers(state)
    device_lines += _make_sliprings(state, pool, emitted_eids, belt_2d_eids)
    device_lines += _make_retractors(state, pool, emitted_eids, belt_2d_eids)
    _warn_device_element_overlap(state)
    lines += pool.lines + device_lines
    if len(lines) == 2:
        return []
    return lines


def _warn_orphan_belt_elements(state: ConversionState,
                               emitted: Set[int]) -> None:
    """1D belt elements that reached no /SPRING because their PART is missing.

    ``assembly._warn_orphan_elements`` reports the PID census for every mesh
    family and now for this one too; this adds the count that only the writer
    can know — elements whose part exists but that the writer still could not
    place.
    """
    wanted = {e.eid for e in state.seatbelt_elems if not e.is_2d}
    lost = sorted(wanted - emitted - {e.eid for e in state.seatbelt_elems
                                      if e.pid not in state.parts})
    if lost:
        state.warn(
            f"*ELEMENT_SEATBELT: {len(lost)} 1D belt element(s) reached no "
            f"/SPRING — {lost[:8]}"
            + (" ..." if len(lost) > 8 else "")
            + ". Any *DATABASE_HISTORY_SEATBELT, slipring or retractor naming "
            "them loses that reference too; see the warnings above.")


def _warn_implicit_belt_stiffness(state: ConversionState,
                                  emitted: Set[int]) -> None:
    """An IMPLICIT deck carrying a 1D belt is not solving the belt.

    The implicit tangent builder dispatches spring stiffness for four property
    types only — ``imp_glob_k.F`` ``ITY==6`` calls ``R4KE3``/``R8KE3``/
    ``R12KE3``/``R13KE3`` for ``IGTYP`` 4, 8, 12 and 13 — and everything else
    falls to the ``IETY=16`` arm, which prints format 1005: ``***** WARNING :
    SPRING ELEMENT PROP.TYPE = 23 IS NOT AVAILABLE FOR STIFFNESS MATRIX
    BUILDING, STIFFNESS IGNORED *****``. ``/PROP/TYPE23`` is not in the list,
    so the belt contributes NOTHING to the matrix.

    MEASURED on a 1D-belt implicit twin: the assembled matrix collapses from
    SYMBOLIC ND=18 NZ=27 to FINAL ND=6 NZ=3 — only the synthesized probe rigid
    body survives — so the run converges on mass and the probe, not on the
    webbing. The explicit route is unaffected; this is an implicit-only hole in
    the engine, not something the converted deck can state its way out of.
    """
    if not state.is_implicit or not emitted:
        return
    state.warn(
        f"*ELEMENT_SEATBELT: this deck is IMPLICIT and carries {len(emitted)} "
        "1D belt /SPRING(s) on /PROP/TYPE23, which the implicit engine gives "
        "NO tangent stiffness: imp_glob_k.F builds spring stiffness for "
        "property types 4, 8, 12 and 13 only and answers '***** WARNING : "
        "SPRING ELEMENT PROP.TYPE = 23 IS NOT AVAILABLE FOR STIFFNESS MATRIX "
        "BUILDING, STIFFNESS IGNORED *****' for the rest. The belt's MASS and "
        "the devices' kinematics still act, and the explicit route is "
        "unaffected, but an implicit run of this deck is NOT solving the belt "
        "— MEASURED, the assembled matrix dropped from ND=18 NZ=27 to ND=6 "
        "NZ=3 on a 1D-belt implicit twin. Run the belt explicitly, or replace "
        "it with a stiffness the implicit solver does build.")


def _warn_retractor_backlink(state: ConversionState,
                             emitted: Set[int]) -> None:
    """An ``*ELEMENT_SEATBELT`` whose SBRID names a retractor that does not
    name it back.

    LS-DYNA states the link twice — the element says which retractor it starts
    inside (``SBRID``) and the retractor says which element is its mouth
    (``SBID``) — while Radioss states it once, on ``/RETRACTOR/SPRING``'s
    ``EL_ID``. So the element-side field is redundant WHEN THE TWO AGREE and a
    modelling error when they do not: an element declaring itself inside a
    retractor that does not claim it is simply an ordinary belt element in the
    converted deck, and the length the user meant to be stowed on the reel is
    out in the open from t=0.

    dyna2rad cannot report this at all — it never reads the element's SBRID
    (``grep '"SBRID"' dyna2rad`` matches only the pretensioner's homonym).
    """
    mouths = {r.sbid for r in state.seatbelt_retractors}
    ret_ids = {r.sbrid for r in state.seatbelt_retractors}
    orphan = sorted(e.eid for e in state.seatbelt_elems
                    if e.sbrid > 0 and e.eid in emitted
                    and e.eid not in mouths)
    if not orphan:
        return
    unknown = sorted({e.sbrid for e in state.seatbelt_elems
                      if e.sbrid > 0 and e.sbrid not in ret_ids})
    state.warn(
        f"*ELEMENT_SEATBELT: {len(orphan)} element(s) {orphan[:8]}"
        + (" ..." if len(orphan) > 8 else "")
        + " declare SBRID (they START INSIDE a retractor) but no converted "
        "*ELEMENT_SEATBELT_RETRACTOR names them as its mouth element (SBID)"
        + (f"; SBRID {unknown} names no retractor at all" if unknown else "")
        + ". Radioss states the link ONCE, on /RETRACTOR/SPRING's EL_ID, so "
        "these elements convert as ordinary belt springs: the webbing they "
        "represent is deployed from t=0 instead of stowed on the reel, and the "
        "belt is that much longer. Check the SBID/SBRID pairing.")


def _warn_device_element_overlap(state: ConversionState) -> None:
    """A belt element claimed by two devices at once.

    ``ERROR 2006 ELEMENT ID nn CANNOT BE INITIALLY IN SEVERAL SLIPRINGS /
    RETRACTORS`` — the starter refuses the deck, so this is caught here where
    the two ids can be named.
    """
    owner: Dict[int, str] = {}
    clash: List[str] = []
    for s in state.seatbelt_sliprings:
        for eid in (s.sbid1, s.sbid2):
            if eid <= 0:
                continue
            who = f"slipring {s.sbsrid}"
            if eid in owner and owner[eid] != who:
                clash.append(f"element {eid}: {owner[eid]} and {who}")
            owner.setdefault(eid, who)
    for r in state.seatbelt_retractors:
        if r.sbid <= 0:
            continue
        who = f"retractor {r.sbrid}"
        if r.sbid in owner and owner[r.sbid] != who:
            clash.append(f"element {r.sbid}: {owner[r.sbid]} and {who}")
        owner.setdefault(r.sbid, who)
    if clash:
        state.warn(
            "SEATBELTS: the same belt element is claimed by two devices — "
            + "; ".join(clash[:6])
            + (" ..." if len(clash) > 6 else "")
            + ". Both cards are written as the deck states them, but the "
            "starter refuses that with ERROR 2006 (ELEMENT ID nn CANNOT BE "
            "INITIALLY IN SEVERAL SLIPRINGS / RETRACTORS). Split the belt so "
            "each device gets its own element.")
