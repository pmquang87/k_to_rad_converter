"""Starter rigid bodies: /RBODY, constrained nodal rigid bodies, merges, probe rigid body."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple
from ..state import CnrbSpcBc, ConversionState, NodeData, PartData
from .common import HDR, _emit_grnod_node, _f, _i

__all__ = [
    "_make_rbodies",
    "_resolve_rigid_body_merges",
    "_con1_to_tra",
    "_con2_to_rot",
    "_resolve_cnrb_spc",
    "_make_cnrb_rbodies",
    "_make_probe_rbody",
]


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
        return lines, rigid_nodes, rbody_info

    rigid_mids: Set[int] = set(state.mat_rigid.keys())

    nodes_by_pid: Dict[int, List[int]] = defaultdict(list)
    for e in state.shell_elems:
        if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[e.pid].extend(e.nodes)
    for e in state.solid_elems:
        if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid in rigid_mids:
            nodes_by_pid[e.pid].extend(e.nodes)
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
        return lines, rigid_nodes, rbody_info

    lines.append("#-  RIGID BODIES:")
    lines.append(HDR)

    # --rigid-cog-master: synthesize element-free masters (new node ids above the
    # current maximum, coordinates at the part's nodal centroid).
    _next_free = (max(state.nodes) + 1 if state.nodes else 90000001)

    for pid, all_nodes in sorted(nodes_by_pid.items()):
        part = state.parts.get(pid)
        if not part: continue
        mat = state.mat_rigid.get(part.mid)
        if not mat: continue
        unique_nodes = sorted(set(n for n in all_nodes if n > 0))
        if not unique_nodes: continue

        if state.options.rigid_cog_master:
            # Element-free master at the nodal centroid (the CNRB treatment):
            # a mesh-node master is an element corner (WARNING 448/1624) and is
            # relocated to the CoM at runtime, so its coordinates appear to
            # change in post-processing. A synthesized master keeps every mesh
            # node put; OpenRadioss still moves the master itself to the true
            # CoM (ICoG default), which is harmless for a free node.
            pts = [state.nodes[n] for n in unique_nodes if n in state.nodes]
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
        grnod_id = state.next_id()
        ind_grnod_id = state.next_id()
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
        if added_mass > 0:
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
        # though np=1 tolerates it. Inertia is 0 (OpenRadioss computes it from the
        # node distribution); Ioptoff=Iexpams=Ifail=0 = defaults.
        lines += [
            f"/RBODY/{ind_node}",
            part.title or f"RBODY_{pid}",
            "#  node_ID   sens_ID   skew_ID    Ispher                Mass   grnd_ID     Ikrem      ICoG   surf_ID",
            f"{_i(ind_node)}{_i(0)}{_i(0)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(0)}{_i(0)}",
            "#                Jxx                 Jyy                 Jzz",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            "#                Jxy                 Jyz                 Jxz",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
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
    """*CONSTRAINED_NODAL_RIGID_BODY[_SPC] → /RBODY (+ /BCS for the _SPC option).

    Returns (rad_lines, rigid_node_set, rbody_info_dict) in the same shape as
    _make_rbodies so the two can be merged: the rbody_info feeds /LOAD_RIGID_BODY
    → /CLOAD, /BOUNDARY_PRESCRIBED_MOTION_RIGID → /IMPDISP, /INITIAL_VELOCITY_
    RIGID_BODY → /INIVEL, and the /TH/NODE reaction readout — all keyed by part ID.
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
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2, e.n3))
    # Synthesize new free node IDs above the current maximum (avoids collisions).
    _next_free = [max(state.nodes) + 1 if state.nodes else 90000001]

    def _new_master_at_centroid(member_nodes: List[int]) -> int:
        pts = [state.nodes[n] for n in member_nodes if n in state.nodes]
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

        # Master/primary node. It MUST be element-free (see elem_nodes note): the
        # ICoG move would otherwise invert the elements it belongs to. Reuse an
        # explicit PNODE only when it is element-free; otherwise synthesize a free
        # node at the set's centroid (mirrors LS-DYNA, which for PNODE=0 creates an
        # internal node at the centre of mass). The secondary group is the node
        # set itself — the master stays separate (not slaved to itself).
        secondary_nodes = unique_nodes
        if cnrb.pnode > 0 and cnrb.pnode not in elem_nodes:
            ind_node = cnrb.pnode
        else:
            ind_node = _new_master_at_centroid(unique_nodes)
            if cnrb.pnode > 0:
                state.warn(
                    f"*CONSTRAINED_NODAL_RIGID_BODY pid={cnrb.pid}: PNODE "
                    f"{cnrb.pnode} is attached to elements; using a synthesized "
                    "free master node at the centroid instead (a meshed master "
                    "moved to the CoG by ICoG would invert its elements)."
                )

        grnod_id = state.next_id()
        ind_grnod_id = state.next_id()
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
        if added_mass > 0:
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY pid={cnrb.pid}: added mass "
                f"{added_mass:.6G} placed in /RBODY Mass field."
            )

        # /RBODY — same 4-card form as _make_rbodies (Card1 + Jxx Jyy Jzz +
        # Jxy Jyz Jxz + Ioptoff Iexpams; all four required or np>1 segfaults). ICoG=0
        # (=default 1, RefGuide p.1879) MOVES the master node to the computed
        # center of gravity, so a /CLOAD force from *LOAD_RIGID_BODY acts through
        # the CoG as a pure force with no spurious moment — matching LS-DYNA,
        # which likewise relocates PNODE to the center of mass.
        lines += [
            f"/RBODY/{ind_node}",
            cnrb.title or f"CNRB_{cnrb.pid}",
            "#  node_ID   sens_ID   skew_ID    Ispher                Mass   grnd_ID     Ikrem      ICoG   surf_ID     Ifail",
            f"{_i(ind_node)}{_i(0)}{_i(0)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}",
            "#                Jxx                 Jyy                 Jzz",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            "#                Jxy                 Jyz                 Jxz",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
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
    n1 = max(state.nodes) + 1
    slave_grnod = state.next_id()
    master_grnod = state.next_id()
    bcs_id = state.next_id()
    lines = [
        "#-  INERT PROBE RIGID BODY (implicit no-rigid-body segfault guard):",
        HDR,
        "/NODE",
        "#  Node ID               X               Y               Z",
    ]
    for k in range(3):
        lines.append(f"{_i(n1 + k)}{_f(x0 + k * spacing)}{_f(y0)}{_f(z0)}")
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
