"""
k2rad.writer  –  Generate OpenRadioss Starter and Engine strings from
                 ConversionState.

Starter output order:
  BEGIN / TITLE / ANALY / DEF_SHELL / DEF_SOLID
  Materials → Nodes → BCS → SKEW → Parts+Elements → Properties
  Functions → Groups → Interfaces → RBODYs → IMPDISP/IMPVEL → TH → END

Engine output order:
  RUN / TFILE / PRINT / ANIM → IMPL/* → CLOAD
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .state import (
    ConversionState,
    NodeData, ShellElem, SolidElem, BeamElem,
    MatElastic, MatPlasTAB, MatPlasKin, MatRigid, MatNull,
    SectionShell, SectionSolid, SectionBeam,
    PartData, Curve, CoordSys,
    BcsSpc, PrescribedMotionRigid, PrescribedMotionSet, LoadRigidBody,
    ContactAutoSingle, ContactAutoSurf2Surf,
)

HDR = "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|"


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v: float, w: int = 20) -> str:
    """Right-aligned float field of width *w*."""
    if v == 0.0:
        s = "0"
    elif abs(v) >= 1e15 or (0.0 < abs(v) < 1e-4):
        s = f"{v:.6E}"
    else:
        s = f"{v:.10G}"
    return s.rjust(w)


def _i(v: int, w: int = 10) -> str:
    return str(v).rjust(w)


def _dof_string(dx: int, dy: int, dz: int) -> str:
    return f"{dx}{dy}{dz}"


def _elform_to_ishell(elform: int, is_implicit: bool) -> int:
    if is_implicit:
        return 24   # QBAT – recommended for implicit
    return 24 if elform in {-16, 9, 20, 21, 26} else 12


def _elform_to_isolid(elform: int) -> int:
    # 17 = 8-node full integration (iso-parametric) — correct for structural solids in implicit.
    # 14 = tet4 (Kessler).  2 = HEPH.
    return {0: 17, 1: 17, 2: 2, 10: 14, 13: 14, 16: 17, -1: 17}.get(elform, 17)


# ─────────────────────────────────────────────────────────────────────────────
# Group emitters (shared by Starter sections)
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grnod_node(grnod_id: int, title: str, nids: List[int]) -> List[str]:
    lines = [f"/GRNOD/NODE/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for n in nids:
        row.append(str(n).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_grshel(grshel_id: int, title: str, eids: List[int]) -> List[str]:
    lines = [f"/GRSHEL/SHEL/{grshel_id}", title or f"GRSHEL_{grshel_id}"]
    row: List[str] = []
    for e in eids:
        row.append(str(e).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_part(surf_id: int, title: str, pids: List[int]) -> List[str]:
    lines = [f"/SURF/PART/EXT/{surf_id}", title or f"SURF_PART_{surf_id}"]
    row: List[str] = []
    for p in pids:
        row.append(_i(p))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_grshel(surf_id: int, title: str, grshel_id: int) -> List[str]:
    return [
        f"/SURF/GRSHEL/{surf_id}",
        title or f"SURF_GRSHEL_{surf_id}",
        f"{_i(grshel_id)}",
        HDR,
    ]


def _emit_surf_surf(surf_id: int, title: str, sub_surf_ids: List[int]) -> List[str]:
    lines = [f"/SURF/SURF/{surf_id}", title or f"SURF_SURF_{surf_id}"]
    row: List[str] = []
    for s in sub_surf_ids:
        row.append(_i(s))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _make_master_surface(state: ConversionState, surf_id: int, title: str,
                         pids: List[int], out_lines: List[str]) -> bool:
    """Emit a master surface (for /INTER) from a list of PIDs."""
    shell_eids: List[int] = []
    solid_pids: List[int] = []
    for pid in sorted(pids):
        eids_in_pid = [e.eid for e in state.shell_elems if e.pid == pid]
        has_solids = any(e.pid == pid for e in state.solid_elems)
        if eids_in_pid:
            shell_eids.extend(eids_in_pid)
        elif has_solids:
            solid_pids.append(pid)

    shell_eids.sort()

    if shell_eids and not solid_pids:
        grshel_id = state.next_id()
        out_lines += _emit_grshel(grshel_id, f"{title}_grshel", shell_eids)
        out_lines += _emit_surf_grshel(surf_id, title, grshel_id)
        return True
    if solid_pids and not shell_eids:
        out_lines += _emit_surf_part(surf_id, title, solid_pids)
        return True
    if shell_eids and solid_pids:
        grshel_id = state.next_id()
        sub_shell = state.next_id()
        sub_solid = state.next_id()
        out_lines += _emit_grshel(grshel_id, f"{title}_grshel", shell_eids)
        out_lines += _emit_surf_grshel(sub_shell, f"{title}_shells", grshel_id)
        out_lines += _emit_surf_part(sub_solid, f"{title}_solids", solid_pids)
        out_lines += _emit_surf_surf(surf_id, title, [sub_shell, sub_solid])
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Starter: header & defaults
# ─────────────────────────────────────────────────────────────────────────────

def _make_header(state: ConversionState) -> List[str]:
    title = state.model_title[:80].ljust(80)
    return [
        "#RADIOSS STARTER",
        HDR,
        "/BEGIN",
        title,
        "      2022         0",
        "                  kg                   m                   s",
        "                  kg                   m                   s",
        HDR,
    ]


def _make_title(state: ConversionState) -> List[str]:
    return ["/TITLE", state.model_title, HDR]


def _make_analysis_defaults(state: ConversionState) -> List[str]:
    cs = state.ctrl_shell
    ithick = 0
    if cs and cs.istupd:
        ithick = 2 if cs.istupd >= 2 else 1

    lines = [
        "/ANALY",
        "         0         0         0",
        HDR,
        "/DEF_SHELL",
    ]
    if ithick > 0:
        lines.append(f"         0         0{_i(ithick)}")
    else:
        lines.append("         0")
    lines += [HDR, "/DEF_SOLID", "         0", HDR]
    lines += ["/IOFLAG", "         0         0", HDR]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: materials
# ─────────────────────────────────────────────────────────────────────────────

def _make_materials(state: ConversionState) -> List[str]:
    lines = ["#-  MATERIALS:", HDR]
    for mat in state.mat_elastic.values():
        lines += _emit_mat_elastic(mat)
    for mat in state.mat_plas_tab.values():
        lines += _emit_mat_law36(mat)
    for mat in state.mat_plas_kin.values():
        lines += _emit_mat_law44(mat)
    for mat in state.mat_rigid.values():
        lines += _emit_mat_elast_for_rigid(mat)
    for mat in state.mat_null.values():
        lines += _emit_mat_void(mat)
    return lines


def _emit_mat_elastic(mat: MatElastic) -> List[str]:
    return [
        f"/MAT/ELAST/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu",
        f"{_f(mat.E)}{_f(mat.nu)}",
        HDR,
    ]


def _emit_mat_elast_for_rigid(mat: MatRigid) -> List[str]:
    return [
        f"/MAT/ELAST/{mat.mid}",
        (mat.title or f"MAT_{mat.mid}") + " (rigid body material)",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu",
        f"{_f(mat.E)}{_f(mat.nu)}",
        HDR,
    ]


def _emit_mat_void(mat: MatNull) -> List[str]:
    return [
        f"/MAT/VOID/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I                   E                  nu",
        f"{_f(mat.rho)}{_f(mat.E)}{_f(mat.nu)}",
        HDR,
    ]


def _emit_mat_law36(mat: MatPlasTAB) -> List[str]:
    fid = mat.funct_id
    fail = mat.fail if 0.0 < mat.fail < 1e19 else 0.0
    fail_str = _f(fail) if fail > 0.0 else "                   0"
    lines = [
        f"/MAT/LAW36/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu          Eps_p_max",
        f"{_f(mat.E)}{_f(mat.nu)}{fail_str}",
        "# N_funct   F_smooth",
        "         1         0",
        "# fct_IDp      Fscale",
        "         0                 1.0",
        "# fct_ID1",
        f"{_i(fid)}",
        "# Fscale1",
        "                 1.0",
        HDR,
    ]
    return lines


def _emit_mat_law44(mat: MatPlasKin) -> List[str]:
    epmax = mat.fs if mat.fs > 0.0 else 0.0
    return [
        f"/MAT/LAW44/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu",
        f"{_f(mat.E)}{_f(mat.nu)}",
        "#                  a                   b                   n               Chard              SIGmax0",
        f"{_f(mat.sigy)}{_f(mat.etan)}{_f(1.0)}{_f(mat.beta)}{_f(0.0)}",
        "#                  c                   p     ICC  Fsmooth                Fcut    VP",
        f"{_f(mat.src)}{_f(mat.srp)}         0         0{_f(0.0)}{_i(mat.vp)}",
        "#              EpsMax                 Et1                 Et2",
        f"{_f(epmax)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: nodes
# ─────────────────────────────────────────────────────────────────────────────

def _make_nodes(state: ConversionState) -> List[str]:
    if not state.nodes:
        return []
    lines = ["#-  NODES:", HDR, "/NODE",
             "#  Node ID               X               Y               Z"]
    for nid, nd in sorted(state.nodes.items()):
        lines.append(f"{_i(nid)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}")
    lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: boundary conditions
# ─────────────────────────────────────────────────────────────────────────────

def _make_bcs(state: ConversionState, rbody_info: Dict) -> List[str]:
    if not state.bcs_spcs:
        return []
    lines = ["#-  BOUNDARY CONDITIONS:", HDR]
    
    node_to_ind = {}
    for pid, info in rbody_info.items():
        ind_node = info["ind_node"]
        for node in info["nodes"]:
            node_to_ind[node] = ind_node

    for bc in state.bcs_spcs:
        nsid = bc.nsid
        raw_nids = state.node_sets.get(nsid, ("", []))[1]
        
        mapped_nids = set()
        for n in raw_nids:
            if n in node_to_ind:
                mapped_nids.add(node_to_ind[n])
            else:
                mapped_nids.add(n)
                
        if not mapped_nids:
            state.warn(f"BCS {bc.bc_id} (nsid={nsid}): all nodes mapped to empty set – skipped")
            continue

        tra = _dof_string(bc.dofx, bc.dofy, bc.dofz)
        rot = _dof_string(bc.dofrx, bc.dofry, bc.dofrz)
        lines += [
            f"/BCS/{bc.bc_id}",
            f"BC_{bc.bc_id}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}         0{_i(nsid)}",
            HDR,
        ]
        set_title = state.node_sets.get(nsid, ("", []))[0]
        lines += _emit_grnod_node(nsid, set_title or f"SET_{nsid}", sorted(mapped_nids))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: skews
# ─────────────────────────────────────────────────────────────────────────────

def _make_skews(state: ConversionState) -> List[str]:
    if not state.coord_sys:
        return []
    lines = ["#-  SKEWS / COORDINATE SYSTEMS:", HDR]
    for cid, cs in sorted(state.coord_sys.items()):
        lines += [
            f"/SKEW/FIX/{cid}",
            f"SKEW_{cid}",
            "#  Ox            Oy            Oz",
            f"{_f(cs.xo)}{_f(cs.yo)}{_f(cs.zo)}",
            "#  Xx            Xy            Xz",
            f"{_f(cs.xl)}{_f(cs.yl)}{_f(cs.zl)}",
            "#  Yx            Yy            Yz",
            f"{_f(cs.xp)}{_f(cs.yp)}{_f(cs.zp)}",
            HDR,
        ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: parts + elements
# ─────────────────────────────────────────────────────────────────────────────

def _make_parts_and_elements(state: ConversionState) -> List[str]:
    if not state.parts:
        return []
    lines = ["#-  PARTS AND ELEMENTS:", HDR]

    shells_by_pid: Dict[int, List[ShellElem]] = defaultdict(list)
    for e in state.shell_elems:
        shells_by_pid[e.pid].append(e)

    solids_by_pid: Dict[int, List[SolidElem]] = defaultdict(list)
    for e in state.solid_elems:
        solids_by_pid[e.pid].append(e)

    beams_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    for e in state.beam_elems:
        beams_by_pid[e.pid].append(e)

    for pid, part in sorted(state.parts.items()):
        secid = part.secid if part.secid > 0 else pid
        
        lines += [
            f"/PART/{pid}",
            part.title or f"PART_{pid}",
            f"{_i(secid)}{_i(part.mid)}         0",
            HDR,
        ]
        if pid in shells_by_pid:
            lines.append(f"/SHELL/{pid}")
            for e in shells_by_pid[pid]:
                row = _i(e.eid)
                for n in e.nodes:
                    row += _i(n)
                pad = 4 - len(e.nodes)
                if pad > 0:
                    row += "         0" * pad
                row += "         0"
                lines.append(row)
            lines.append(HDR)
        if pid in solids_by_pid:
            lines.append(f"/BRICK/{pid}")
            for e in solids_by_pid[pid]:
                nodes = list(e.nodes)
                if len(nodes) == 4:
                    nodes += [nodes[-1]] * 4
                elif len(nodes) < 8:
                    nodes += [nodes[-1]] * (8 - len(nodes))
                row = _i(e.eid)
                for n in nodes[:8]:
                    row += _i(n)
                lines.append(row)
            lines.append(HDR)
        if pid in beams_by_pid:
            lines.append(f"/BEAM/{pid}")
            for e in beams_by_pid[pid]:
                lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}{_i(e.n3)}")
            lines.append(HDR)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: properties
# ─────────────────────────────────────────────────────────────────────────────

def _make_properties(state: ConversionState) -> List[str]:
    lines = ["#-  PROPERTIES:", HDR]

    missing_shells = set()
    missing_solids = set()
    missing_beams = set()
    
    part_secids = {p.pid: p.secid if p.secid > 0 else p.pid for p in state.parts.values()}

    for e in state.shell_elems:
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_shells:
            missing_shells.add(secid)
    for e in state.solid_elems:
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_solids:
            missing_solids.add(secid)
    for e in state.beam_elems:
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_beams:
            missing_beams.add(secid)

    for ms in missing_shells:
        state.sec_shells[ms] = SectionShell(ms, f"AutoPropShell_{ms}", 2, 3, 0.0)
    for ms in missing_solids:
        state.sec_solids[ms] = SectionSolid(ms, f"AutoPropSolid_{ms}", 1)
    for ms in missing_beams:
        state.sec_beams[ms] = SectionBeam(ms, f"AutoPropBeam_{ms}", 2)

    for sec in sorted(state.sec_shells.values(), key=lambda s: s.secid):
        ishell = _elform_to_ishell(sec.elform, state.is_implicit)
        nip = max(2, sec.nip)
        lines += [
            f"/PROP/SHELL/{sec.secid}",
            sec.title or f"PROP_{sec.secid}",
            "#   Ishell    Ismstr     Ish3n    Idrill",
            f"{_i(ishell)}         0         0         0",
            "#                 hm                  hf                  hr                  dm                  dn",
            "                   0                   0                   0                   0                   0",
            "#        N   Istrain               Thick              Ashear              Ithick     Iplas",
            f"{_i(nip)}         0{_f(sec.t1)}                   0                   0         0",
            HDR,
        ]
    for sec in sorted(state.sec_solids.values(), key=lambda s: s.secid):
        isolid = _elform_to_isolid(sec.elform)
        lines += [
            f"/PROP/SOLID/{sec.secid}",
            sec.title or f"PROP_{sec.secid}",
            "#   Isolid    Ismstr               Icpre               Inpts    Itetra    Iframe                  dn",
            f"{_i(isolid)}         0                   0                   0         0         0                   0",
            "#                q_a                 q_b                   h            LAMBDA_V                MU_V",
            "                   0                   0                   0                   0                   0",
            "#             dt_min   istrain      IHKT",
            "                   0         0         0",
            HDR,
        ]
    for sec in sorted(state.sec_beams.values(), key=lambda s: s.secid):
        lines += _emit_prop_beam(sec)
    return lines


def _emit_prop_beam(sec: SectionBeam) -> List[str]:
    return [
        f"/PROP/BEAM/{sec.secid}",
        sec.title or f"PROP_{sec.secid}",
        "#             Ismstr",
        "                   0",
        "#                 dm                  df",
        "                   0                   0",
        "#               Area                 Iyy                 Izz                 Ixx",
        f"{_f(sec.area)}{_f(sec.iyy)}{_f(sec.izz)}{_f(sec.ixx)}",
        "# OmegaDof    Ishear",
        "   000 000         0",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: functions
# ─────────────────────────────────────────────────────────────────────────────

def _make_functions(state: ConversionState) -> List[str]:
    if not state.curves:
        return []
    lines = ["#-  FUNCTIONS:", HDR]
    for lcid, curve in sorted(state.curves.items()):
        lines += [
            f"/FUNCT/{lcid}",
            curve.title or f"FUNCT_{lcid}",
            "#                  X                   Y",
        ]
        for a, o in curve.pts:
            lines.append(f"{_f(a)}{_f(o)}")
        lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: extra groups (node sets not already emitted)
# ─────────────────────────────────────────────────────────────────────────────

def _make_extra_groups(state: ConversionState) -> List[str]:
    emitted: Set[int] = {bc.nsid for bc in state.bcs_spcs}
    lines: List[str] = []
    for nsid, (title, nids) in sorted(state.node_sets.items()):
        if nsid not in emitted:
            lines += _emit_grnod_node(nsid, title, nids)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: interfaces
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_contact_slave(state: ConversionState, sid: int, styp: int, rigid_nodes: Set[int], out_lines: List[str]) -> int:
    nids = set()
    def add_part_nodes(pid: int):
        for e in state.shell_elems:
            if e.pid == pid: nids.update(e.nodes)
        for e in state.solid_elems:
            if e.pid == pid: nids.update(e.nodes)

    if styp == 4:
        if sid in state.node_sets:
            nids.update(state.node_sets[sid][1])
    elif styp == 3:
        add_part_nodes(sid)
    elif styp == 2:
        if sid in state.part_sets:
            for pid in state.part_sets[sid][1]:
                add_part_nodes(pid)
    elif styp == 0 or styp == 1:
        if sid in state.parts:
            add_part_nodes(sid)
        elif sid in state.part_sets:
            for pid in state.part_sets[sid][1]:
                add_part_nodes(pid)
        elif sid in state.node_sets:
            nids.update(state.node_sets[sid][1])

    clean_nids = [n for n in sorted(nids) if n > 0 and n not in rigid_nodes]
    if not clean_nids:
        return 0
    grnod_id = state.next_id()
    out_lines += _emit_grnod_node(grnod_id, f"contact_slave_{sid}", clean_nids)
    return grnod_id


def _resolve_contact_master(state: ConversionState, sid: int, styp: int, out_lines: List[str]) -> int:
    pids = set()
    if styp == 3:
        pids.add(sid)
    elif styp == 2:
        if sid in state.part_sets:
            pids.update(state.part_sets[sid][1])
    elif styp == 0 or styp == 1:
        if sid in state.parts:
            pids.add(sid)
        elif sid in state.part_sets:
            pids.update(state.part_sets[sid][1])

    clean_pids = sorted(pids)
    if not clean_pids:
        return 0
    surf_id = state.next_id()
    if not _make_master_surface(state, surf_id, f"contact_master_{sid}", clean_pids, out_lines):
        return 0
    return surf_id


def _make_interfaces(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    if not state.contacts_single and not state.contacts_surf2surf:
        return []
    lines = ["#-  INTERFACES:", HDR]

    all_shell_nodes: List[int] = sorted(
        {n for e in state.shell_elems
         if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
         for n in e.nodes if n > 0 and n not in rigid_nodes}
    )
    all_pids: List[int] = sorted(state.parts.keys())

    for c in state.contacts_single:
        if c.ssid == 0:
            if not all_shell_nodes or not all_pids:
                continue
            slav_grnod = state.next_id()
            mast_surf = state.next_id()
            lines += _emit_grnod_node(slav_grnod, f"contact_{c.inter_id}_slave", all_shell_nodes)
            if not _make_master_surface(state, mast_surf, f"contact_{c.inter_id}_master",
                                        all_pids, lines):
                continue
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs)
        else:
            slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
            mast_surf = _resolve_contact_master(state, c.ssid, c.sstyp, lines)
            if slav_grnod and mast_surf:
                lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs)

    for c in state.contacts_surf2surf:
        slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
        mast_surf = _resolve_contact_master(state, c.msid, c.mstyp, lines)
        if slav_grnod and mast_surf:
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs)

    return lines


def _emit_inter_type7(inter_id: int, title: str, slav_id: int,
                      mast_id: int, fric: float) -> List[str]:
    return [
        f"/INTER/TYPE7/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "#  Slav_id   Mast_id      Istf      Ithe      Igap                Ibag      Idel     Icurv      Iadm",
        f"{_i(slav_id)}{_i(mast_id)}         4         0         0                   0         2         0         0",
        "#          Fscalegap             GAP_MAX             Fpenmax",
        "                   0                   0                   0",
        "#              Stmin               Stmax          %mesh_size               dtmin  Irem_gap",
        "                1000                   0                   0                   0         0",
        "#              Stfac                Fric              Gapmin              Tstart               Tstop",
        f"                   0{_f(fric)}                   0                   0                   0",
        "#      IBC                        Inacti                VisS                VisF              Bumult",
        "       000                             0                   0                   0                   0",
        "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID",
        "         0         0                   0         2         0",
        HDR,
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

    if not nodes_by_pid:
        for mid in rigid_mids:
            state.warn(f"*MAT_RIGID mid={mid}: no elements found; /RBODY not emitted")
        return lines, rigid_nodes, rbody_info

    lines.append("#-  RIGID BODIES:")
    lines.append(HDR)

    for pid, all_nodes in sorted(nodes_by_pid.items()):
        part = state.parts.get(pid)
        if not part: continue
        mat = state.mat_rigid.get(part.mid)
        if not mat: continue
        unique_nodes = sorted(set(n for n in all_nodes if n > 0))
        if not unique_nodes: continue

        ind_node = unique_nodes[0]
        grnod_id = state.next_id()
        ind_grnod_id = state.next_id()
        rigid_nodes.update(unique_nodes)
        rbody_info[pid] = {
            "ind_node": ind_node,
            "grnod_id": grnod_id,
            "ind_grnod_id": ind_grnod_id,
            "nodes": unique_nodes,
        }

        lines += [
            f"/RBODY/{ind_node}",
            part.title or f"RBODY_{pid}",
            "#  node_ID   sens_ID   Skew_ID    Ispher",
            f"{_i(ind_node)}         0         0         0",
            "#                Jxx                 Jyy                 Jxy                 Jyz  Ioptoff   Ifail",
            "                   0                   0                   0                   0         0         0",
            "#               Mass                 Jzz                 Jxz",
            "                   0                   0                   0",
            "#  grnd_ID    Ikrem     ICoG   surf_ID",
            f"{_i(grnod_id)}         0         0         0",
        ]
        lines += _emit_grnod_node(grnod_id, f"rb_nodes_pid{pid}", unique_nodes)
        lines += _emit_grnod_node(ind_grnod_id, f"rb_indnode_pid{pid}", [ind_node])

        if mat.cmo == 1.0 and (mat.con1 or mat.con2):
            bc_id_auto = state.next_id()
            tra = _con1_to_tra(mat.con1)
            rot = _con2_to_rot(mat.con2)
            lines += [
                f"/BCS/{bc_id_auto}",
                f"BC_rigid_{pid}",
                "#  Tra rot   skew_ID  grnod_ID",
                f"   {tra} {rot}         0{_i(ind_grnod_id)}",
                HDR,
            ]

    return lines, rigid_nodes, rbody_info


def _con1_to_tra(con1: int) -> str:
    return {0: "000", 1: "100", 2: "010", 3: "001", 4: "110", 5: "011", 6: "101", 7: "111"}.get(con1, "000")


def _con2_to_rot(con2: int) -> str:
    return {0: "000", 1: "100", 2: "010", 3: "001", 4: "110", 5: "011", 6: "101", 7: "111"}.get(con2, "000")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: imposed motions
# ─────────────────────────────────────────────────────────────────────────────

_DOF_DIR = {1: "X", 2: "Y", 3: "Z", 4: "X", 5: "XX", 6: "YY", 7: "ZZ", 8: "XX"}


def _make_imposed_motions(state: ConversionState, rbody_info: Dict) -> List[str]:
    lines: List[str] = []
    if not state.prescribed_motions:
        return lines
    lines.append("#-  IMPOSED MOTIONS:")

    motion_counter = 1
    for pm in state.prescribed_motions:
        info = rbody_info.get(pm.pid)
        if not info:
            state.warn(f"BOUNDARY_PRESCRIBED_MOTION_RIGID pid={pm.pid}: no RBODY found; motion skipped")
            continue

        grnod_id = info["grnod_id"]
        dir_str = _DOF_DIR.get(pm.dof, "X").rjust(10)
        fscale = pm.sf
        tstart = pm.birth if pm.birth < 1e27 else 0.0
        tstop = pm.death if pm.death < 1e27 else 0.0

        keyword = {0: "IMPVEL", 1: "IMPACC", 2: "IMPDISP"}.get(pm.vad, "IMPDISP")
        lines += [
            f"/{keyword}/{motion_counter}",
            f"Motion_{motion_counter}",
            "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID  frame_ID     Icoor",
            f"{_i(pm.lcid)}{dir_str}         0         0{_i(grnod_id)}         0         0",
            "#           Ascale_x            Fscale_Y              Tstart               Tstop",
            f"                   1{_f(fscale)}{_f(tstart)}{_f(tstop)}",
            HDR,
        ]
        motion_counter += 1
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: time history outputs
# ─────────────────────────────────────────────────────────────────────────────

def _make_starter_th(state: ConversionState) -> List[str]:
    if not state.db_histories:
        return []
    lines = ["#-  TIME HISTORY OUTPUTS:", HDR]
    counter = 1
    type_map = {"SHELL": "SHEL", "SOLID": "BRIC", "NODE": "NODE"}
    for dbh in state.db_histories:
        rad_type = type_map.get(dbh.db_type, dbh.db_type)
        lines += [
            f"/TH/{rad_type}/{counter}",
            f"TH_{rad_type}_{counter}",
            "#     var1      var2",
            "DEF       ",
        ]
        for eid in dbh.ids:
            lines.append(_i(eid))
        counter += 1
    lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: energy control
# ─────────────────────────────────────────────────────────────────────────────

def _make_energy(state: ConversionState) -> List[str]:
    e = state.ctrl_energy
    if not e: return []
    ihge  = 1 if e.hgen   > 0 else 0
    idamp = 1 if e.rylen  > 0 else 0
    return [
        "/ENERGY",
        "#  Istor  Igrav   Iref  Iplas  Idamp Itherm   Ihge",
        f"       1      0      0      1{_i(idamp, 7)}      0{_i(ihge, 7)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: imposed motions for node sets
# ─────────────────────────────────────────────────────────────────────────────

def _make_imposed_motions_set(state: ConversionState) -> List[str]:
    lines: List[str] = []
    if not state.prescribed_motion_sets:
        return lines

    for pm in state.prescribed_motion_sets:
        if pm.nsid not in state.node_sets:
            state.warn(f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: node set not found – skipped")
            continue

        set_title, nids = state.node_sets[pm.nsid]
        grnod_id = state.next_id()
        motion_id = state.next_id()
        dir_str = _DOF_DIR.get(pm.dof, "X").rjust(10)
        fscale = pm.sf if pm.sf != 0.0 else 1.0
        tstart = pm.birth if pm.birth < 1e27 else 0.0
        tstop  = pm.death if pm.death < 1e27 else 0.0

        keyword = {0: "IMPVEL", 1: "IMPACC", 2: "IMPDISP"}.get(pm.vad, "IMPDISP")
        lines += [
            f"/{keyword}/{motion_id}",
            f"Motion_{motion_id}",
            "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID  frame_ID     Icoor",
            f"{_i(pm.lcid)}{dir_str}         0         0{_i(grnod_id)}         0         0",
            "#           Ascale_x            Fscale_Y              Tstart               Tstop",
            f"                   1{_f(fscale)}{_f(tstart)}{_f(tstop)}",
            HDR,
        ]
        lines += _emit_grnod_node(grnod_id, set_title or f"SET_{pm.nsid}", nids)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: skipped keyword comment block
# ─────────────────────────────────────────────────────────────────────────────

def _make_skipped_comment(state: ConversionState) -> List[str]:
    if not state.skipped_keywords:
        return []
    unique = sorted(set(state.skipped_keywords))
    lines = ["#", "# -- SKIPPED (unsupported) keywords --"]
    for kw in unique:
        lines.append(f"#-- SKIPPED: *{kw}")
    lines.append("#")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Post-processing: resolve auto-generated function IDs for LAW36
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_mat_plas_tab(state: ConversionState) -> None:
    for mat in state.mat_plas_tab.values():
        if mat.funct_id:
            continue

        if mat.lcss > 0:
            mat.funct_id = mat.lcss

        elif any(v != 0.0 for v in mat.eps_pts) and any(v != 0.0 for v in mat.es_pts):
            pts = [(eps, es) for eps, es in zip(mat.eps_pts, mat.es_pts)
                   if eps != 0.0 or es != 0.0]
            if not pts:
                pts = [(0.0, mat.sigy), (1.0, mat.sigy)]
            fid = state.next_id()
            _add_auto_curve(state, fid, f"Auto_EPS_ES_mid{mat.mid}", pts)
            mat.funct_id = fid

        else:
            sigy = mat.sigy if mat.sigy > 0 else 1.0
            etan = mat.etan
            pts = [(0.0, sigy), (1.0, sigy + etan)]
            fid = state.next_id()
            _add_auto_curve(state, fid, f"Auto_SY_ET_mid{mat.mid}", pts)
            mat.funct_id = fid


def _add_auto_curve(state: ConversionState, fid: int, title: str,
                    pts: List[Tuple[float, float]]) -> None:
    class _C:
        pass
    c = _C()
    c.lcid = fid; c.title = title
    c.sfa = c.sfo = 1.0; c.offa = c.offo = 0.0
    c.pts = pts
    state.curves[fid] = c


# ─────────────────────────────────────────────────────────────────────────────
# Engine file sections
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine_header(state: ConversionState) -> List[str]:
    import re as _re
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    safe_title = _re.sub(r"[^A-Za-z0-9_-]", "_", state.model_title)[:40]
    return [f"/RUN/{safe_title}/1", f"{endtim:.6G}", "#"]


def _make_engine_output(state: ConversionState) -> List[str]:
    lines: List[str] = []
    dt_th = (state.db_nodout_dt or state.db_elout_dt or state.db_glstat_dt
             or state.db_matsum_dt or 1e-3)
    lines += ["/TFILE", f"{dt_th:.6G}", "#", "/PRINT/-1", "#"]

    dt_anim = 0.0
    if state.db_d3plot:
        dt_anim = state.db_d3plot.dt
        if dt_anim == 0.0 and state.db_d3plot.npltc > 0:
            endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
            dt_anim = endtim / state.db_d3plot.npltc
    if dt_anim == 0.0:
        dt_anim = (state.ctrl_termination.endtim / 40.0
                   if state.ctrl_termination else 0.01)
    lines += ["/ANIM/DT", f"0. {dt_anim:.6G}"]

    ext = state.db_extent_binary
    lines.append("/ANIM/ELEM/EPSP")
    lines.append("/ANIM/ELEM/VONM")
    lines.append("/ANIM/ELEM/ENER")
    lines.append("/ANIM/ELEM/THICK")
    if ext and ext.shge:
        lines.append("/ANIM/ELEM/HOUR")
    lines.append("/ANIM/VECT/DISP")
    lines.append("/ANIM/VECT/VEL")
    if state.db_intfor_dt > 0.0:
        lines.append("/ANIM/VECT/CONT")
    lines.append("#")
    return lines


def _make_engine_implicit(state: ConversionState) -> List[str]:
    if not state.is_implicit:
        return []
    gen  = state.ctrl_implicit_gen
    dyn  = state.ctrl_implicit_dyn
    auto = state.ctrl_implicit_auto

    dt0 = gen.dt0 if gen and gen.dt0 > 0 else 0.01
    dtmin = auto.dtmin if auto and auto.dtmin > 0 else max(dt0 * 1e-4, 1e-10)
    dtmax = auto.dtmax if auto and auto.dtmax > 0 else 0.0
    iteopt = auto.iteopt if auto else 0
    kfail  = auto.kfail  if auto else 0

    lines: List[str] = ["/IMPL/NONLIN/1", "  0 2 0"]
    if dyn and dyn.imass > 0:
        gamma = dyn.gamma if dyn.gamma > 0 else 0.6
        beta  = dyn.beta  if dyn.beta  > 0 else 0.25
        lines += ["/IMPL/DYNA/NEWMARK", f"  {gamma:.4G}  {beta:.4G}"]

    lines += ["/IMPL/QSTAT/DTSCAL", " 1000", "/IMPL/PRINT/NONL/-1", "/IMPL/SOLVER/2", "  0 0 0 0",
              "/IMPL/DTINI", f" {dt0:.4G}"]
    dtmax_str = f"    {dtmax:.4G}" if dtmax > 0 else "    0.0"
    lines += ["/IMPL/DT/STOP", f"  {dtmin:.2E}{dtmax_str}"]
    if iteopt > 0 or kfail > 0:
        lines += ["/IMPL/DT/2", f"  {iteopt}    0  {kfail}    0    0"]
    else:
        lines += ["/IMPL/DT/2", "  0    0    0    0    0"]
    lines.append("#")
    return lines


def _make_engine_cpu(state: ConversionState) -> List[str]:
    if not state.ctrl_cpu:
        return []
    return ["/CPU", f"{_f(state.ctrl_cpu.cputim)}         2", "#"]


def _make_engine_load_rigid_bodies(state: ConversionState) -> List[str]:
    if not state.load_rigid_bodies:
        return []

    _DOF_DIR_FORCE = {1: "X", 2: "Y", 3: "Z", 5: "XX", 6: "YY", 7: "ZZ"}
    lines: List[str] = []
    load_id = 1
    for lb in state.load_rigid_bodies:
        ind_grnod_id = state.rbody_ind_grnods.get(lb.pid)
        if ind_grnod_id is None:
            state.warn(f"LOAD_RIGID_BODY pid={lb.pid}: rigid body not found – skipped")
            continue

        if lb.dof == 4:
            dirs_to_emit = [("X", lb.sf), ("Y", lb.sf), ("Z", lb.sf)]
        else:
            d = _DOF_DIR_FORCE.get(lb.dof)
            if d is None:
                state.warn(f"LOAD_RIGID_BODY pid={lb.pid} DOF={lb.dof}: unknown DOF – skipped")
                continue
            dirs_to_emit = [(d, lb.sf)]

        if not lines:
            lines.append("#-  RIGID BODY LOADS:")
        for dir_str, sf in dirs_to_emit:
            lines += [
                f"/CLOAD/{load_id}",
                f"LoadRB_{load_id}",
                "#funct_IDT       Dir   skew_ID  sens_ID  grnd_ID",
                f"{_i(lb.lcid)}{dir_str.rjust(10)}{_i(lb.cid)}         0{_i(ind_grnod_id)}",
                "#  Ascalex  Fscaley",
                f"                   1{_f(sf)}",
                HDR,
            ]
            load_id += 1
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Top-level assemblers
# ─────────────────────────────────────────────────────────────────────────────

def build_starter(state: ConversionState) -> str:
    _resolve_mat_plas_tab(state)

    rbody_lines, rigid_nodes, rbody_info = _make_rbodies(state)
    state.rbody_grnods = {pid: info["grnod_id"] for pid, info in rbody_info.items()}
    state.rbody_ind_grnods = {pid: info["ind_grnod_id"] for pid, info in rbody_info.items()}

    sections = [
        _make_header(state),
        _make_title(state),
        _make_analysis_defaults(state),
        _make_materials(state),
        _make_nodes(state),
        _make_bcs(state, rbody_info),
        _make_skews(state),
        _make_parts_and_elements(state),
        _make_properties(state),
        _make_functions(state),
        _make_extra_groups(state),
        _make_interfaces(state, rigid_nodes),
        rbody_lines,
        _make_imposed_motions(state, rbody_info),
        _make_imposed_motions_set(state),
        _make_starter_th(state),
        _make_skipped_comment(state),
        ["/END", HDR],
    ]
    lines: List[str] = []
    for sec in sections:
        lines.extend(sec)
    return "\n".join(lines) + "\n"


def build_engine(state: ConversionState) -> str:
    sections = [
        _make_engine_header(state),
        _make_engine_output(state),
        _make_engine_implicit(state),
        _make_engine_load_rigid_bodies(state),
        _make_engine_cpu(state),
        ["/MON/ON", "#"],
    ]
    lines: List[str] = []
    for sec in sections:
        lines.extend(sec)
    return "\n".join(lines) + "\n"
