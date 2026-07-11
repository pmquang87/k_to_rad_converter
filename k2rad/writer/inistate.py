"""Initial state: /INISHE, /INIBRI initial stresses and /SECT cross-sections."""

from __future__ import annotations

from typing import List, Optional, Set, Tuple
from ..state import ConversionState
from .common import (
    HDR,
    _elform_to_ishell,
    _elform_to_isolid,
    _emit_grnod_node,
    _emit_grshel,
    _emit_id_group,
    _f,
    _fmt_eid_list,
    _i,
    _ordered_unique_nodes,
    _vcross,
    _vnorm,
    _vsub,
)

__all__ = [
    "_shell_sec_for_part",
    "_solid_sec_for_part",
    "_make_inishe",
    "_make_inibri",
    "_make_initial_stresses",
    "_sect_frame_nodes",
    "_plane_cut",
    "_make_cross_sections",
    "_make_starter_th_sectio",
]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: initial stresses (*INITIAL_STRESS_SHELL/_SOLID → /INISHE, /INIBRI)
# ─────────────────────────────────────────────────────────────────────────────

def _shell_sec_for_part(state: ConversionState, pid: int):
    part = state.parts.get(pid)
    secid = part.secid if part and part.secid > 0 else pid
    return state.sec_shells.get(secid)


def _solid_sec_for_part(state: ConversionState, pid: int):
    part = state.parts.get(pid)
    secid = part.secid if part and part.secid > 0 else pid
    return state.sec_solids.get(secid)


def _make_inishe(state: ConversionState) -> List[str]:
    """*INITIAL_STRESS_SHELL → /INISHE/STRS_F/GLOB (ILOC=0, the LS-DYNA default:
    global-frame components) or /INISHE/STRS_F (ILOC=1: element-local).

    Card layouts follow hm_cfg_files inishe_strs_f_glob_sub.cfg
    FORMAT(radioss2021) and inishe_strs_f_sub.cfg FORMAT(radioss120):
      Card1  shell_ID nb_integr npg Thick        (%10d%10d%10d%20lg)
      Card2  Em Eb [H1 H2 H3]                    (energies unknown → 0)
      then nb_integr×npg point records, LAYER-major with the in-plane Gauss
      point innermost (starter hm_read_inistate_d00.F: DO N=1,NIP{DO K=1,NPG}).
    Constraints honoured against the /PROP/SHELL this converter emits:
      * nb_integr must equal the property N (= max(2, *SECTION_SHELL NIP); the
        starter cross-checks and rejects) — mismatched elements warn + skip;
      * npg must be 4 for Ishell 12/24 (starter MSGID 26 otherwise) — the
        per-layer LS-DYNA value is replicated across the 4 in-plane points
        (exact for the layer-averaged data);
      * Thick = 0 keeps the property thickness (guarded by /=ZERO in the
        starter, thickini.F).
    GLOB carries σzz, eps_p AND the thickness position (pos_nip) 1:1; the
    local flavour has no σzz/position slot → dropped with a warning.
    """
    if not state.ini_stress_shells:
        return []
    eid2pid = {e.eid: e.pid for e in state.shell_elems}
    glob_entries: List[Tuple] = []
    loc_entries: List[Tuple] = []
    missing: List[int] = []
    mismatched: List[int] = []
    for iss in state.ini_stress_shells:
        pid = eid2pid.get(iss.eid)
        sec = _shell_sec_for_part(state, pid) if pid is not None else None
        if sec is None:
            missing.append(iss.eid)
            continue
        n_eff = max(2, sec.nip)
        if iss.nthick != n_eff:
            mismatched.append(iss.eid)
            continue
        ishell = _elform_to_ishell(sec.elform, state.is_implicit)
        npg = 4 if ishell in (12, 24) else 1
        (glob_entries if iss.iloc == 0 else loc_entries).append((iss, npg))
    if missing:
        state.warn("*INITIAL_STRESS_SHELL: element(s) "
                   f"{_fmt_eid_list(missing)} not found in the shell mesh — "
                   "their initial stresses were skipped.")
    if mismatched:
        state.warn("*INITIAL_STRESS_SHELL: NTHICK differs from the /PROP/SHELL "
                   "integration-point count N (= max(2, *SECTION_SHELL NIP)) for "
                   f"element(s) {_fmt_eid_list(mismatched)} — the OpenRadioss "
                   "starter rejects such /INISHE records, so these elements were "
                   "skipped. Align NIP and re-run to keep their initial stress.")
    if not glob_entries and not loc_entries:
        return []

    lines = ["#-  INITIAL STATE (*INITIAL_STRESS_SHELL):", HDR]
    if glob_entries:
        lines.append("/INISHE/STRS_F/GLOB")
        for iss, npg in glob_entries:
            lines += [
                "# shell_ID nb_integr       npg               Thick",
                f"{_i(iss.eid)}{_i(iss.nthick)}{_i(npg)}{_f(0.0)}",
                "#                 Em                  Eb                  H1                  H2                  H3",
                _f(0.0) * 5,
            ]
            for (t, sxx, syy, szz, sxy, syz, szx, eps) in iss.layers:
                rec = [f"{_f(sxx)}{_f(syy)}{_f(szz)}",
                       f"{_f(sxy)}{_f(syz)}{_f(szx)}{_f(eps)}{_f(t)}"]
                lines += rec * npg      # layer value at each in-plane Gauss point
        lines.append(HDR)
    if loc_entries:
        szz_lost = [iss.eid for iss, _npg in loc_entries
                    if any(abs(layer[3]) > 0.0 for layer in iss.layers)]
        if szz_lost:
            state.warn("*INITIAL_STRESS_SHELL (ILOC=1): the local /INISHE/STRS_F "
                       "flavour is plane-stress (no sigma_zz slot) — nonzero "
                       f"SIGZZ dropped on element(s) {_fmt_eid_list(szz_lost)}.")
        state.warn("*INITIAL_STRESS_SHELL (ILOC=1): the local /INISHE/STRS_F "
                   "flavour has no thickness-position field — the T coordinates "
                   "are dropped and the layer ORDER maps onto the property's "
                   "integration scheme (verify the layer positions match).")
        lines.append("/INISHE/STRS_F")
        for iss, npg in loc_entries:
            lines += [
                "# shell_ID nb_integr       npg               Thick",
                f"{_i(iss.eid)}{_i(iss.nthick)}{_i(npg)}{_f(0.0)}",
            ]
            if npg <= 1:
                lines += [
                    "#                 Em                  Eb                  H1                  H2                  H3",
                    _f(0.0) * 5,
                ]
            else:
                lines += [
                    "#                 Em                  Eb",
                    _f(0.0) * 2,
                ]
            for (_t, sxx, syy, _szz, sxy, syz, szx, eps) in iss.layers:
                rec = [f"{_f(sxx)}{_f(syy)}{_f(sxy)}",
                       f"{_f(syz)}{_f(szx)}{_f(eps)}"]
                lines += rec * npg
        lines.append(HDR)
    return lines


def _make_inibri(state: ConversionState) -> List[str]:
    """*INITIAL_STRESS_SOLID → /INIBRI/STRS_FGLO (LS-DYNA defines the solid
    stress components in the GLOBAL system → the global flavour).

    Card layout follows hm_cfg_files inibri_strs_fglo_sub.cfg
    FORMAT(radioss2021):
      Card1  brick_ID Nb_integr Isolnod Isolid nptr npts nptt nlay grbric_ID
      per IP, layout A when (Isolnod==8 and Nb_integr in (1,8) and Isolid!=14)
      or (Isolnod==4 and Nb_integr==1):
        (Eint RHO) / (SIGMA1 SIGMA2 SIGMA3) / (SIGMA12 SIGMA23 SIGMA31) /
        (Epsilon_p)
      otherwise layout B:
        (SIGMA1-3) / (SIGMA12,23,31) / (Epsilon_p Eint RHO)
    Eint/RHO are unknown at conversion and written 0 — the starter keeps the
    material's values for zero fields (sigin3b.F: 'IF (SIGSP(..) /= ZERO)').
    Component order confirmed against the cfg: σ1 σ2 σ3 = σxx σyy σzz and
    σ12 σ23 σ31 = σxy σyz σzx.

    Nb_integr must match the point count of the /PROP/SOLID this converter
    emits (starter lec_inistate_d00_brick-check.F, MSGID 695): 8 for Isolid
    12/17/18 hexas, 4 for tet10, 1 otherwise. NINT=1 data is replicated onto
    an 8-point formulation (exact: a constant stress state); NINT>1 onto a
    1-point formulation is averaged with a warning; any other mismatch warns
    and skips the element.
    """
    if not state.ini_stress_solids:
        return []
    elems = {e.eid: e for e in state.solid_elems}
    entries: List[Tuple] = []
    missing: List[int] = []
    mismatched: List[int] = []
    averaged: List[int] = []
    for iss in state.ini_stress_solids:
        e = elems.get(iss.eid)
        sec = _solid_sec_for_part(state, e.pid) if e is not None else None
        if e is None or sec is None:
            missing.append(iss.eid)
            continue
        isolid_prop = 0 if sec.iale else _elform_to_isolid(sec.elform)
        uniq = _ordered_unique_nodes(e.nodes)
        if len(e.nodes) == 10:
            isolnod, isolid, expected = 10, 1, 4
        elif len(uniq) <= 4:
            isolnod, isolid, expected = 4, 1, 1
        else:
            isolnod = 8
            isolid = isolid_prop if isolid_prop > 0 else 1
            expected = 8 if isolid in (12, 17, 18) else 1
        pts = iss.points
        if len(pts) == expected:
            out = pts
        elif len(pts) == 1 and expected > 1:
            out = pts * expected          # constant stress replicated — exact
        elif expected == 1 and len(pts) > 1:
            out = [tuple(sum(p[k] for p in pts) / len(pts) for k in range(7))]
            averaged.append(iss.eid)
        else:
            mismatched.append(iss.eid)
            continue
        entries.append((iss.eid, isolnod, isolid, expected, out))
    if missing:
        state.warn("*INITIAL_STRESS_SOLID: element(s) "
                   f"{_fmt_eid_list(missing)} not found in the solid mesh — "
                   "their initial stresses were skipped.")
    if averaged:
        state.warn("*INITIAL_STRESS_SOLID: NINT>1 data mapped onto a 1-point "
                   "/PROP/SOLID formulation by AVERAGING the integration points "
                   f"on element(s) {_fmt_eid_list(averaged)}.")
    if mismatched:
        state.warn("*INITIAL_STRESS_SOLID: NINT does not match the integration-"
                   "point count of the emitted /PROP/SOLID formulation for "
                   f"element(s) {_fmt_eid_list(mismatched)} — the OpenRadioss "
                   "starter rejects such /INIBRI records (MSGID 695), so these "
                   "elements were skipped.")
    if not entries:
        return []

    lines = ["#-  INITIAL STATE (*INITIAL_STRESS_SOLID):", HDR,
             "/INIBRI/STRS_FGLO"]
    for eid, isolnod, isolid, npt, pts in entries:
        nax = 2 if npt == 8 else 1
        lines += [
            "# brick_ID Nb_integr   Isolnod    Isolid      nptr      npts      nptt      nlay grbric_ID",
            f"{_i(eid)}{_i(npt)}{_i(isolnod)}{_i(isolid)}"
            f"{_i(nax)}{_i(nax)}{_i(nax)}{_i(1)}{_i(0)}",
        ]
        layout_a = ((isolnod == 8 and npt in (1, 8) and isolid != 14)
                    or (isolnod == 4 and npt == 1))
        for (sxx, syy, szz, sxy, syz, szx, eps) in pts:
            if layout_a:
                lines += [
                    _f(0.0) * 2,                       # Eint RHO (0 = keep material values)
                    f"{_f(sxx)}{_f(syy)}{_f(szz)}",
                    f"{_f(sxy)}{_f(syz)}{_f(szx)}",
                    _f(eps),
                ]
            else:
                lines += [
                    f"{_f(sxx)}{_f(syy)}{_f(szz)}",
                    f"{_f(sxy)}{_f(syz)}{_f(szx)}",
                    f"{_f(eps)}{_f(0.0)}{_f(0.0)}",     # Epsilon_p Eint RHO
                ]
    lines.append(HDR)
    return lines


def _make_initial_stresses(state: ConversionState) -> List[str]:
    return _make_inishe(state) + _make_inibri(state)


# ─────────────────────────────────────────────────────────────────────────────
# Starter: cross sections (*DATABASE_CROSS_SECTION_* → /SECT, → /TH/SECTIO)
# ─────────────────────────────────────────────────────────────────────────────

def _sect_frame_nodes(state: ConversionState, group_nids: List[int],
                      extra_nids: List[int]) -> Tuple[int, int, int]:
    """Pick three non-colinear nodes defining the /SECT output frame (N1 =
    origin, N1→N2 = first axis, N3 fixes the plane — the /SKEW/MOV convention).
    N1/N2 are taken from the section node group; N3 may fall back to any other
    node of the section's elements (the frame only orients the force output)."""
    def _coord(n):
        nd = state.nodes.get(n)
        return (nd.x, nd.y, nd.z) if nd else None

    cands = [n for n in group_nids if n in state.nodes]
    if not cands:
        return (0, 0, 0)
    n1 = cands[0]
    p1 = _coord(n1)
    pool = cands[1:] + [n for n in extra_nids
                        if n in state.nodes and n not in group_nids]
    best2, best_d2 = 0, 0.0
    for n in pool:
        p = _coord(n)
        v = _vsub(p, p1)
        d2 = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
        if d2 > best_d2:
            best2, best_d2 = n, d2
    if best2 == 0:
        return (n1, 0, 0)
    p2 = _coord(best2)
    v12 = _vsub(p2, p1)
    best3, best_a2 = 0, 0.0
    for n in pool:
        if n == best2:
            continue
        c = _vcross(v12, _vsub(_coord(n), p1))
        a2 = c[0] * c[0] + c[1] * c[1] + c[2] * c[2]
        if a2 > best_a2:
            best3, best_a2 = n, a2
    if best3 == 0 or best_a2 <= 1e-20 * best_d2 * best_d2:
        return (n1, best2, 0)
    return (n1, best2, best3)


def _plane_cut(state: ConversionState, cs) -> Tuple[List[int], List[int],
                                                    List[int], List[int]]:
    """Geometric resolver for *DATABASE_CROSS_SECTION_PLANE: an element is cut
    when the signed distances d = (x - tail)·n̂ of its nodes change sign across
    the plane (tail→head = the plane normal), restricted to the parts of PSID
    (0 = all) and — when RADIUS > 0 — to elements whose centroid lies within
    RADIUS of the tail point measured IN the plane. The section node group is
    the cut elements' nodes on the TAIL side (d <= 0): this is the standard
    /SECT construction (section forces = what the tail-side nodes of the cut
    elements transmit through the plane).

    Returns (node_ids, shell_eids, solid_eids, beam_eids).
    """
    nhat = _vnorm((cs.xch - cs.xct, cs.ych - cs.yct, cs.zch - cs.zct))
    if nhat is None:
        return ([], [], [], [])
    tail = (cs.xct, cs.yct, cs.zct)
    pids: Optional[Set[int]] = None
    if cs.psid > 0:
        entry = state.part_sets.get(cs.psid)
        if entry is None:
            state.warn(f"*DATABASE_CROSS_SECTION_PLANE: part set {cs.psid} not "
                       "found — the plane was intersected with the WHOLE model.")
        else:
            pids = set(entry[1])
    r2 = cs.radius * cs.radius if cs.radius > 0.0 else 0.0

    def _dist(nid):
        nd = state.nodes.get(nid)
        if nd is None:
            return None
        return ((nd.x - tail[0]) * nhat[0] + (nd.y - tail[1]) * nhat[1]
                + (nd.z - tail[2]) * nhat[2])

    def _in_radius(nids) -> bool:
        if r2 <= 0.0:
            return True
        pts = [state.nodes[n] for n in nids if n in state.nodes]
        if not pts:
            return False
        cx = sum(p.x for p in pts) / len(pts) - tail[0]
        cy = sum(p.y for p in pts) / len(pts) - tail[1]
        cz = sum(p.z for p in pts) / len(pts) - tail[2]
        dn = cx * nhat[0] + cy * nhat[1] + cz * nhat[2]
        px, py, pz = cx - dn * nhat[0], cy - dn * nhat[1], cz - dn * nhat[2]
        return px * px + py * py + pz * pz <= r2

    node_ids: Set[int] = set()
    shell_eids: List[int] = []
    solid_eids: List[int] = []
    beam_eids: List[int] = []

    def _try(nids, eid, pid, out):
        if pids is not None and pid not in pids:
            return
        ds = [(n, _dist(n)) for n in nids if n]
        ds = [(n, d) for n, d in ds if d is not None]
        if not ds:
            return
        dmin = min(d for _n, d in ds)
        dmax = max(d for _n, d in ds)
        if not (dmin < 0.0 < dmax):
            return
        if not _in_radius([n for n, _d in ds]):
            return
        out.append(eid)
        node_ids.update(n for n, d in ds if d <= 0.0)

    for e in state.shell_elems:
        _try(e.nodes, e.eid, e.pid, shell_eids)
    for e in state.solid_elems:
        _try(e.nodes, e.eid, e.pid, solid_eids)
    for e in state.beam_elems:
        _try([e.n1, e.n2], e.eid, e.pid, beam_eids)
    return (sorted(node_ids), shell_eids, solid_eids, beam_eids)


def _make_cross_sections(state: ConversionState) -> List[str]:
    """*DATABASE_CROSS_SECTION_PLANE/_SET → /SECT (radioss100 card layout from
    hm_cfg_files sect.cfg):
        /SECT/<id> / title
        node_ID1 node_ID2 node_ID3 grnod_ID ISAVE Frame_ID deltaT alpha
        file_name
        grbric_ID <blank> grshel_ID grtrus_ID grbeam_ID grsprg_ID grtria_ID
        Niter <blank> Iframe
    ISAVE=0 (no section file), no moving frame, Iframe=0 (local skew origin).
    All shells this converter emits are 4-node /SHELL (triangles are degenerate
    quads), so shell sets go into grshel_ID; grtria stays 0.
    """
    if not state.cross_sections:
        return []
    lines = ["#-  CROSS SECTIONS (*DATABASE_CROSS_SECTION_* -> /SECT):", HDR]
    used_ids: Set[int] = set()
    emitted = False
    for cs in state.cross_sections:
        label = f"id={cs.csid}" if cs.csid else f"'{cs.title}'" if cs.title else "(no id)"
        if cs.kind == "SET":
            entry = state.node_sets.get(cs.nsid)
            if entry is None:
                state.warn(f"*DATABASE_CROSS_SECTION_SET {label}: node set "
                           f"{cs.nsid} not found — /SECT skipped.")
                continue
            nids = entry[1]
            shell_eids = solid_eids = beam_eids = []
            if cs.ssid:
                se = state.shell_sets.get(cs.ssid)
                if se is None:
                    state.warn(f"*DATABASE_CROSS_SECTION_SET {label}: shell set "
                               f"{cs.ssid} not found — dropped from the /SECT.")
                else:
                    shell_eids = se[1]
            if cs.hsid:
                se = state.solid_sets.get(cs.hsid)
                if se is None:
                    state.warn(f"*DATABASE_CROSS_SECTION_SET {label}: solid set "
                               f"{cs.hsid} not found — dropped from the /SECT.")
                else:
                    solid_eids = se[1]
            if cs.bsid:
                se = state.beam_sets.get(cs.bsid)
                if se is None:
                    state.warn(f"*DATABASE_CROSS_SECTION_SET {label}: beam set "
                               f"{cs.bsid} not found — dropped from the /SECT.")
                else:
                    beam_eids = se[1]
        else:
            nids, shell_eids, solid_eids, beam_eids = _plane_cut(state, cs)
            if not nids:
                state.warn(f"*DATABASE_CROSS_SECTION_PLANE {label}: the plane "
                           "cuts no element (or the normal is zero / all cut "
                           "elements are outside RADIUS) — /SECT skipped.")
                continue
        if not nids:
            state.warn(f"*DATABASE_CROSS_SECTION_SET {label}: empty node set — "
                       "/SECT skipped.")
            continue
        if not (shell_eids or solid_eids or beam_eids):
            state.warn(f"*DATABASE_CROSS_SECTION_* {label}: no element group — "
                       "the /SECT is emitted but will record zero force until "
                       "an element set is added.")

        elem_nids: List[int] = []
        if shell_eids or solid_eids or beam_eids:
            shells = {e.eid: e for e in state.shell_elems}
            solids = {e.eid: e for e in state.solid_elems}
            beams = {e.eid: e for e in state.beam_elems}
            for eid in shell_eids:
                if eid in shells:
                    elem_nids.extend(shells[eid].nodes)
            for eid in solid_eids:
                if eid in solids:
                    elem_nids.extend(solids[eid].nodes)
            for eid in beam_eids:
                if eid in beams:
                    elem_nids.extend([beams[eid].n1, beams[eid].n2])
        n1, n2, n3 = _sect_frame_nodes(state, nids, elem_nids)
        if n3 == 0:
            state.warn(f"*DATABASE_CROSS_SECTION_* {label}: could not find three "
                       "non-colinear section nodes for the /SECT output frame — "
                       "the starter may reject the section; add a node set with "
                       "an in-plane spread of nodes.")

        sect_id = cs.csid if cs.csid > 0 and cs.csid not in used_ids else state.next_id()
        used_ids.add(sect_id)
        title = cs.title or f"SECT_{sect_id}"
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"{title}_nodes", nids)
        grshel_id = grbric_id = grbeam_id = 0
        if shell_eids:
            grshel_id = state.next_id()
            lines += _emit_grshel(grshel_id, f"{title}_shells", shell_eids)
        if solid_eids:
            grbric_id = state.next_id()
            lines += _emit_id_group("GRBRIC/BRIC", grbric_id, f"{title}_bricks",
                                    solid_eids)
        if beam_eids:
            grbeam_id = state.next_id()
            lines += _emit_id_group("GRBEAM/BEAM", grbeam_id, f"{title}_beams",
                                    beam_eids)
        lines += [
            f"/SECT/{sect_id}",
            title,
            "#  node_ID1  node_ID2  node_ID3  grnod_ID     ISAVE  Frame_ID              deltaT               alpha",
            f"{_i(n1)}{_i(n2)}{_i(n3)}{_i(grnod_id)}{_i(0)}{_i(0)}{_f(0.0)}{_f(0.0)}",
            "#file_name (unused: ISAVE=0; a blank line could be skipped by the reader)",
            f"SECT_{sect_id}",
            "#grbric_ID           grshel_ID grtrus_ID grbeam_ID grsprg_ID grtria_ID     Niter              Iframe",
            f"{_i(grbric_id)}{' ' * 10}{_i(grshel_id)}{_i(0)}{_i(grbeam_id)}"
            f"{_i(0)}{_i(0)}{_i(0)}{' ' * 10}{_i(0)}",
            HDR,
        ]
        state.sect_ids.append((sect_id, title))
        emitted = True
    return lines if emitted else []


def _make_starter_th_sectio(state: ConversionState) -> List[str]:
    """*DATABASE_SECFORC → /TH/SECTIO on every emitted /SECT (the secforc file's
    section force/moment resultants, written to the T01 at the /TFILE
    frequency). Emitted whenever sections exist, even without a *DATABASE_SECFORC
    request — harmless and the only way to read the sections back."""
    if not state.sect_ids:
        return []
    if not state.db_secforc_dt:
        state.warn("Cross section(s) defined without *DATABASE_SECFORC — "
                   "/TH/SECTIO emitted anyway so the /SECT forces are recorded "
                   "(T01, /TFILE frequency); add *DATABASE_SECFORC to control "
                   "the output interval.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_SECFORC -> section forces):", HDR,
        f"/TH/SECTIO/{th_id}",
        "TH_SECTIONS",
        "#     var1",
        "DEF       ",
    ]
    lines += [_i(sid) for sid, _title in state.sect_ids]
    lines.append(HDR)
    return lines
