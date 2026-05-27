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
    MatElastic, MatPlasTAB, MatPlasKin, MatRigid, MatNull, MatPowerLaw,
    SectionShell, SectionSolid, SectionBeam,
    PartData, Curve, CoordSys,
    BcsSpc, PrescribedMotionRigid, PrescribedMotionSet, LoadRigidBody,
    ContactAutoSingle, ContactAutoSurf2Surf,
    InitialVelocityNode, InitialVelocityRigidBody, PressureLoad,
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
    # /BEGIN block embeds the unit system (Reference Guide).
    # Format:
    #   /BEGIN
    #   <title (80 chars)>
    #   <version>  <flag>
    #   <input mass>  <input length>  <input time>     ← .k file units
    #   <work mass>   <work length>   <work time>      ← internal units
    # LS-DYNA default unit system is ton (Mg) mm s N MPa.
    # Mg = megagram = 1000 kg = 1 tonne. Use Mg/mm/s to match the .k file.
    title = state.model_title[:80].ljust(80)
    unit_line = "                  Mg                  mm                   s"
    return [
        "#RADIOSS STARTER",
        HDR,
        "/BEGIN",
        title,
        "      2022         0",
        unit_line,
        unit_line,
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
        "         0",
        HDR,
        "/DEF_SHELL",
    ]
    if ithick > 0:
        lines.append(f"         0         0{_i(ithick)}")
    else:
        lines.append("         0")
    lines += [HDR, "/DEF_SOLID", "         0", HDR]
    lines += ["/IOFLAG", "         0", HDR]
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
    for mat in state.mat_power_law.values():
        lines += _emit_mat_law36_powerlaw(mat)
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


def _emit_mat_law36_powerlaw(mat: MatPowerLaw) -> List[str]:
    fail_str = _f(mat.epsf) if 0.0 < mat.epsf < 1e19 else "                   0"
    return [
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
        f"{_i(mat.funct_id)}",
        "# Fscale1",
        "                 1.0",
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

    all_deformable_nodes: List[int] = sorted(
        {n for e in state.shell_elems
         if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
         for n in e.nodes if n > 0 and n not in rigid_nodes}
        | {n for e in state.solid_elems
           if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
           for n in e.nodes if n > 0 and n not in rigid_nodes}
    )
    all_pids: List[int] = sorted(state.parts.keys())

    for c in state.contacts_single:
        if c.ssid == 0:
            if not all_deformable_nodes or not all_pids:
                continue
            slav_grnod = state.next_id()
            mast_surf = state.next_id()
            lines += _emit_grnod_node(slav_grnod, f"contact_{c.inter_id}_slave", all_deformable_nodes)
            if not _make_master_surface(state, mast_surf, f"contact_{c.inter_id}_master",
                                        all_pids, lines):
                continue
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id))
        else:
            slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
            mast_surf = _resolve_contact_master(state, c.ssid, c.sstyp, lines)
            if slav_grnod and mast_surf:
                lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                           _ignore_to_inacti(c.ignore, state, c.inter_id))

    for c in state.contacts_surf2surf:
        slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
        mast_surf = _resolve_contact_master(state, c.msid, c.mstyp, lines)
        if slav_grnod and mast_surf:
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id))

    return lines


def _ignore_to_inacti(ignore: int, state: ConversionState, inter_id: int) -> int:
    """Map LS-DYNA *CONTACT ignore → OpenRadioss /INTER/TYPE7 Inacti.

    LS-DYNA ignore=1 ("track but don't push apart; contact otherwise normal")
    → Inacti=1 (deactivate stiffness on penetrating nodes only). Preserves
    geometry — necessary when penetrating nodes belong to a rigid body, since
    Inacti=3/6 modify coordinates and break /RBODY kinematic consistency
    (observed on `implicit_hr-anlenkung`: Inacti=3 moved 21 cylinder rigid-body
    nodes → engine seg-faulted during initialization). Inacti=5 absorbs the
    penetration into a variable gap, but that silently suppresses contact for
    those nodes (saw 7 cycles I-energy=0, K≈ext-work, free body).
    Inacti=1 is safe for rigid bodies and only loses contact at the few
    penetrating nodes; every other surface node engages normally.
    ignore=2 → Inacti=2 (deactivate stiffness on elements containing
    penetrating nodes) for the same reason.
    """
    if ignore == 1:
        state.warn(f"CONTACT {inter_id}: ignore=1 mapped to /INTER/TYPE7 Inacti=1 "
                   "(deactivate stiffness on penetrating nodes; geometry preserved).")
        return 1
    if ignore == 2:
        state.warn(f"CONTACT {inter_id}: ignore=2 mapped to /INTER/TYPE7 Inacti=2 "
                   "(deactivate stiffness on penetrating elements; geometry preserved).")
        return 2
    return 0


def _emit_inter_type7(inter_id: int, title: str, slav_id: int,
                      mast_id: int, fric: float, inacti: int = 0) -> List[str]:
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
        f"       000{_i(inacti, 30)}                   0                   0                   0",
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

        # /RBODY format: 2 data cards (one per logical record).
        # The W7-style 4-card-with-comments format makes OpenRadioss read
        # grnd_ID as 0 (silently defaulting), giving NUMBER OF NODES = 0 →
        # malformed rigid body → engine segfault. Using the proper 10-field
        # single data line ensures grnd_ID is read correctly.
        # Card 3 (10 fields, 110 chars):
        #   node_ID(I10) sens_ID(I10) skew_ID(I10) Ispher(I10) Mass(F20)
        #   grnd_ID(I10) Ikrem(I10) ICoG(I10) surf_ID(I10) Ifail(I10)
        # Card 4 (6 floats, 120 chars):
        #   Jxx(F20) Jyy(F20) Jzz(F20) Jxy(F20) Jxz(F20) Jyz(F20)
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
                sources.append(f"*ELEMENT_MASS on node {ind_node}={node_added:.6G}")
            if part_add > 0:
                sources.append(f"*ELEMENT_MASS_PART ADDMASS={part_add:.6G}")
            if part_fin > 0:
                sources.append(f"*ELEMENT_MASS_PART FINMASS={part_fin:.6G}")
            state.warn(
                f"*MAT_RIGID pid={pid}: total added mass {added_mass:.6G} "
                f"({', '.join(sources)}) placed in /RBODY Mass field."
            )
        # /RBODY format — 2-card variant that empirically works with OpenRadioss
        # 2024+ in this configuration. The Reference Guide p.1877 documents a
        # 4-card format (cards 3,4,5,6) but using it triggers ERROR 760 segfault
        # during element-group setup. The legacy 2-card form below produces a
        # WARNING 100217 "card is missing" but otherwise solves correctly.
        # Card 3 (10 fields):
        #   node_ID(I10) sens_ID(I10) Skew_ID(I10) Ispher(I10) Mass(F20)
        #   grnd_ID(I10) Ikrem(I10) ICoG(I10) surf_ID(I10) Ifail(I10)
        # Card 4 (6 inertia floats):
        #   JXX(F20) JYY(F20) JZZ(F20) JXY(F20) JYZ(F20) JXZ(F20)
        lines += [
            f"/RBODY/{ind_node}",
            part.title or f"RBODY_{pid}",
            "#  node_ID   sens_ID   skew_ID    Ispher                Mass   grnd_ID     Ikrem      ICoG   surf_ID     Ifail",
            f"{_i(ind_node)}{_i(0)}{_i(0)}{_i(0)}{_f(added_mass)}{_i(grnod_id)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}",
            "#                Jxx                 Jyy                 Jzz                 Jxy                 Jxz                 Jyz",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
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

        # LS-DYNA convention: *BOUNDARY_PRESCRIBED_MOTION_SET with sf=0 means
        # "fix this DOF" (zero × any_curve = 0 displacement = fixed).
        # Emit a /BCS (constraint) instead of /IMPDISP with bogus unit scale.
        # This is critical for symmetry BCs — if treated as IMPDISP with sf=1,
        # the symmetry plane nodes get spurious motion from the load curve,
        # making the stiffness matrix singular.
        if pm.sf == 0.0:
            bc_id = state.next_id()
            grnod_id = state.next_id()
            # Translation char string: "100"=X, "010"=Y, "001"=Z
            # Rotation char string: "100"=Rx, "010"=Ry, "001"=Rz
            tra = "000"
            rot = "000"
            if pm.dof == 1: tra = "100"
            elif pm.dof == 2: tra = "010"
            elif pm.dof == 3: tra = "001"
            elif pm.dof == 4: rot = "100"
            elif pm.dof == 5: rot = "010"
            elif pm.dof == 6: rot = "001"
            lines += [
                f"/BCS/{bc_id}",
                set_title or f"BC_set_{pm.nsid}",
                "#  Tra rot   skew_ID  grnod_ID",
                f"   {tra} {rot}         0{_i(grnod_id)}",
                HDR,
            ]
            lines += _emit_grnod_node(grnod_id, set_title or f"SET_{pm.nsid}", nids)
            continue

        # Non-zero scale: real prescribed motion → /IMPDISP, /IMPVEL, /IMPACC
        grnod_id = state.next_id()
        motion_id = state.next_id()
        dir_str = _DOF_DIR.get(pm.dof, "X").rjust(10)
        fscale = pm.sf
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
# Starter: initial conditions
# ─────────────────────────────────────────────────────────────────────────────

def _make_inivel(state: ConversionState, rbody_info: Dict) -> List[str]:
    lines: List[str] = []

    vel_groups: Dict[Tuple, List[int]] = defaultdict(list)
    for iv in state.inivel_nodes:
        vel_groups[(iv.vx, iv.vy, iv.vz, iv.vxr, iv.vyr, iv.vzr)].append(iv.nid)

    for vel_key, nids in vel_groups.items():
        vx, vy, vz, vxr, vyr, vzr = vel_key
        inivel_id = state.next_id()
        grnod_id  = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_{inivel_id}", sorted(nids))
        lines += [
            f"/INIVEL/NODE/{inivel_id}",
            f"InitVel_{inivel_id}",
            "#  grnod_ID",
            _i(grnod_id),
            "#                  Vx                  Vy                  Vz",
            f"{_f(vx)}{_f(vy)}{_f(vz)}",
            "#                  Wx                  Wy                  Wz",
            f"{_f(vxr)}{_f(vyr)}{_f(vzr)}",
            HDR,
        ]

    for iv in state.inivel_rbodies:
        info = rbody_info.get(iv.pid)
        if not info:
            state.warn(f"INITIAL_VELOCITY_RIGID_BODY pid={iv.pid}: no RBODY found – skipped")
            continue
        grnod_id  = info["grnod_id"]
        inivel_id = state.next_id()
        lines += [
            f"/INIVEL/RBODY/{inivel_id}",
            f"InitVelRB_{inivel_id}",
            "#  grnod_ID",
            _i(grnod_id),
            "#                  Vx                  Vy                  Vz",
            f"{_f(iv.vx)}{_f(iv.vy)}{_f(iv.vz)}",
            "#                  Wx                  Wy                  Wz",
            f"{_f(iv.vxr)}{_f(iv.vyr)}{_f(iv.vzr)}",
            HDR,
        ]

    if lines:
        lines = ["#-  INITIAL CONDITIONS:", HDR] + lines
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: pressure loads
# ─────────────────────────────────────────────────────────────────────────────

def _make_pressure_loads(state: ConversionState) -> List[str]:
    if not state.pressure_loads:
        return []
    groups: Dict[Tuple, List[List[int]]] = defaultdict(list)
    for pl in state.pressure_loads:
        groups[(pl.lcid, pl.sf)].append(pl.nodes)

    lines: List[str] = ["#-  PRESSURE LOADS:", HDR]
    pload_id = 1
    for (lcid, sf), segs in groups.items():
        lines += [
            f"/PLOAD/{pload_id}",
            f"PLOAD_{pload_id}",
            "#funct_ID       Dir   skew_ID   sens_ID",
            f"{_i(lcid)}         N         0         0",
            "#           Ascalex             Fscaley              Tstart               Tstop",
            f"                   1{_f(sf)}                   0                   0",
            "#  n1        n2        n3        n4",
        ]
        for nodes in segs:
            pad = 4 - len(nodes)
            lines.append("".join(_i(n) for n in nodes) + "         0" * pad)
        lines.append(HDR)
        pload_id += 1
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


def _resolve_mat_power_law(state: ConversionState) -> None:
    eps_pts = [0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0]
    for mat in state.mat_power_law.values():
        if mat.funct_id:
            continue
        k = mat.k if mat.k > 0 else 1.0
        n = mat.n if mat.n > 0 else 0.2
        eps_max = mat.epsf if 0.0 < mat.epsf < 1e19 else 1.0
        pts: List[Tuple[float, float]] = []
        for eps in eps_pts:
            e = min(eps, eps_max)
            if mat.sigy > 0:
                sigma = mat.sigy + k * (e ** n) if e > 0 else mat.sigy
            else:
                sigma = k * ((e + 1e-9) ** n)
            pts.append((e, sigma))
            if e >= eps_max:
                break
        fid = state.next_id()
        _add_auto_curve(state, fid, f"Auto_PL_mid{mat.mid}", pts)
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

    # ── Vector outputs ────────────────────────────────────────────
    lines.append("/ANIM/VECT/DISP")
    lines.append("/ANIM/VECT/VEL")
    lines.append("/ANIM/VECT/ACC")
    lines.append("/ANIM/VECT/CONT")
    lines.append("/ANIM/VECT/CONT2")
    lines.append("/ANIM/VECT/PCONT")

    # ── Shell tensor outputs (membrane / upper / lower) ───────────
    lines.append("/ANIM/SHELL/TENS/STRESS/MEMB")
    lines.append("/ANIM/SHELL/TENS/STRESS/UPPER")
    lines.append("/ANIM/SHELL/TENS/STRESS/LOWER")
    lines.append("/ANIM/SHELL/TENS/STRAIN/MEMB")
    lines.append("/ANIM/SHELL/TENS/STRAIN/UPPER")
    lines.append("/ANIM/SHELL/TENS/STRAIN/LOWER")
    lines.append("/ANIM/SHELL/EPSP/UPPER")
    lines.append("/ANIM/SHELL/EPSP/LOWER")

    # ── Solid (brick) tensor outputs ──────────────────────────────
    lines.append("/ANIM/BRICK/TENS/STRESS")
    lines.append("/ANIM/BRICK/TENS/STRAIN")

    # ── Element scalar outputs ────────────────────────────────────
    lines.append("/ANIM/ELEM/EPSP")
    lines.append("/ANIM/ELEM/VONM")
    lines.append("/ANIM/ELEM/ENER")
    lines.append("/ANIM/ELEM/THICK")
    if ext and ext.shge:
        lines.append("/ANIM/ELEM/HOUR")

    # ── Nodal scalar outputs ──────────────────────────────────────
    lines.append("/ANIM/NODA/DT")
    lines.append("/ANIM/NODA/DMAS")

    # ── Spring force output ───────────────────────────────────────
    lines.append("/ANIM/SPRING/FORC")

    lines.append("#")
    return lines


def _make_engine_implicit(state: ConversionState) -> List[str]:
    if not state.is_implicit:
        return []
    gen  = state.ctrl_implicit_gen
    dyn  = state.ctrl_implicit_dyn
    auto = state.ctrl_implicit_auto

    dt0_in = gen.dt0    if gen  and gen.dt0    > 0 else 0.01
    dtmax  = auto.dtmax if auto and auto.dtmax > 0 else 0.0
    iteopt = auto.iteopt if auto else 0
    kfail  = auto.kfail  if auto else 0

    # For dynamic implicit with rigid bodies that have free DOFs (only contact-
    # constrained), the K_eff = K + M/(β·Δt²) needs a small Δt for the mass
    # contribution to stabilize the matrix. LS-DYNA's DT0=0.05 is too large
    # for OpenRadioss's MUMPS direct solver on this large model (568k DOFs)
    # with tiny rigid-body masses (~0.27 g). Use a much smaller initial step
    # so M/(β·Δt²) provides ~2500× more stabilization. The auto time-step
    # control (/IMPL/DT/2) will grow Δt back up as iterations converge.
    is_dynamic_pre = dyn and dyn.imass > 0
    dt0 = min(dt0_in, 1e-3) if is_dynamic_pre else dt0_in
    dtmin  = auto.dtmin if auto and auto.dtmin > 0 else max(dt0 * 1e-4, 1e-10)

    # /IMPL/NONLIN/1: Iupdate=0 (every step), Ialgo=2 (modified Newton-Raphson),
    # Ilin=0 (matches W7 reference)
    lines: List[str] = ["/IMPL/NONLIN/1", "  0 2 0"]

    # Per OpenRadioss 2022 Reference Guide (pages 2942-2943):
    #   /IMPL/DYNA/1 = HHT method, ONE parameter α (-1/3 < α < 0)
    #   /IMPL/DYNA/2 = Newmark method, TWO parameters (γ, β)
    # LS-DYNA's *CONTROL_IMPLICIT_DYNAMICS provides γ and β (Newmark), so
    # we MUST use /IMPL/DYNA/2 — using /IMPL/DYNA/1 with two values is wrong
    # and the matrix factorization then fails.
    is_dynamic = dyn and dyn.imass > 0
    if is_dynamic:
        gamma = dyn.gamma if dyn.gamma > 0 else 0.5
        beta  = dyn.beta  if dyn.beta  > 0 else 0.25
        lines += ["/IMPL/DYNA/2", f" {gamma:.6G}  {beta:.6G}"]
    else:
        lines += ["/IMPL/QSTAT/DTSCAL", " 1000"]

    # /IMPL/SOLVER format (Reference Guide p.2976-2978):
    #   /IMPL/SOLVER/N  with data card: Iprec  It_max  Itol  Tol
    # N=2 is MUMPS direct solver. (N=7 Auto solver is NO LONGER SUPPORTED
    # in OpenRadioss 2024+ per MESSAGE ID 296 — it now falls back to MUMPS.)
    # /IMPL/MUMPS/AUTOC enables MUMPS automatic out-of-core mode (M_OCORE=-1
    # → sets ICNTL(22)=1 when MUMPS estimates exceed in-core budget).
    # Undocumented in the 2022 Reference Guide; parsed in
    # engine/source/input/freimpl.F line 533 of the OpenRadioss source.
    # Prevents MUMPS -13 "workspace too large" failures (MUMPS defaults
    # ICNTL(23) = INFOG(16) × 1.2; with tight contact stiffness the actual
    # numerical fill can overshoot the 20% relaxation buffer).
    lines += ["/IMPL/PRINT/NONL/-1",
              "/IMPL/SOLVER/2", "  0 0 0 0",
              "/IMPL/MUMPS/AUTOC",
              "/IMPL/DTINI", _f(dt0)]
    lines += ["/IMPL/DT/STOP", f"{_f(dtmin)}{_f(dtmax)}"]
    if iteopt > 0 or kfail > 0:
        lines += ["/IMPL/DT/2", f"{_i(iteopt)}{_i(0)}{_i(kfail)}{_i(0)}{_i(0)}"]
    else:
        # /IMPL/DT/2 data: It_w  L_arc  L_dtn  Tsca_dn  Tsca_up
        # (Reference Guide p.2981)
        #   It_w   = converge-iter threshold for time-step increase (default 6)
        #   L_arc  = arc length (0 = auto)
        #   L_dtn  = MAX iterations before timestep cut (default 20 — too low
        #            for highly nonlinear contact-driven problems with rigid
        #            bodies). Set to 50 to allow more iterations per step.
        #   Tsca_dn = scale for decreasing (0 = 0.67)
        #   Tsca_up = scale for increasing (0 = 1.1)
        lines += ["/IMPL/DT/2", "  8 0 50 0 0"]
    lines.append("#")
    return lines


def _make_engine_cpu(state: ConversionState) -> List[str]:
    if not state.ctrl_cpu:
        return []
    return ["/CPU", f"{_f(state.ctrl_cpu.cputim)}         2", "#"]


def _make_starter_cloads(state: ConversionState) -> List[str]:
    """/CLOAD is a Starter keyword – concentrated loads on node groups."""
    if not state.load_rigid_bodies:
        return []

    _DOF_DIR_FORCE = {1: "X", 2: "Y", 3: "Z", 5: "XX", 6: "YY", 7: "ZZ"}
    lines: List[str] = ["#-  CONCENTRATED LOADS (RIGID BODY):"]
    load_id = 1
    emitted = False
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

        for dir_str, sf in dirs_to_emit:
            lines += [
                f"/CLOAD/{load_id}",
                f"LoadRB_{load_id}",
                "#funct_IDT       Dir   skew_ID  sens_ID  grnd_ID",
                f"{_i(lb.lcid)}{dir_str.rjust(10)}{_i(lb.cid)}         0{_i(ind_grnod_id)}",
                "#              Ascalex             Fscaley",
                f"                   1{_f(sf)}",
                HDR,
            ]
            load_id += 1
            emitted = True

    return lines if emitted else []


# ─────────────────────────────────────────────────────────────────────────────
# Top-level assemblers
# ─────────────────────────────────────────────────────────────────────────────

def build_starter(state: ConversionState) -> str:
    _resolve_mat_plas_tab(state)
    _resolve_mat_power_law(state)

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
        _make_inivel(state, rbody_info),
        _make_pressure_loads(state),
        _make_starter_cloads(state),
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
        _make_engine_cpu(state),
        ["/MON/ON", "#"],
    ]
    lines: List[str] = []
    for sec in sections:
        lines.extend(sec)
    return "\n".join(lines) + "\n"
