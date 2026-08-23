"""Initial state: /INISHE, /INIBRI initial stresses and /SECT cross-sections."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from ..state import ConversionState
from .mesh import _effective_solid_isolid, _target_mat_law
from .common import (
    HDR,
    _elform_to_ishell,
    _emit_grnod_node,
    _emit_grsh3n,
    _emit_grshel,
    _emit_id_group,
    _f,
    _fmt_eid_list,
    _i,
    _ordered_unique_nodes,
    _split_shell_eids_by_topology,
    _part_node_sets,
    _ref_flag_materials,
    _vcross,
    _vnorm,
    _vsub,
)

__all__ = [
    "_shell_sec_for_part",
    "_solid_sec_for_part",
    "_make_inishe",
    "_make_inibri",
    "_make_inistra",
    "_make_initial_stresses",
    "_make_xref",
    "_resolve_xref_parts",
    "_airbag_ref_nodes",
    "_resolve_airbag_eref",
    "_make_eref",
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
        ishell = _elform_to_ishell(sec.elform, state.is_implicit,
                                  state.options.shell_default_ishell)
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
        # The EFFECTIVE Isolid the part's /PROP/SOLID emits — not the raw ELFORM
        # one — so Nb_integr matches the property's integration order after
        # per-part hourglass control remaps a full-integration hex (17) to an
        # under-integrated 1/5/24. Using the ELFORM Isolid here would declare
        # Nb_integr=8 against a 1-point /PROP and the starter would reject it
        # (MSGID 695). For a hex this collapses NINT>1 data onto 1 point (warned
        # via `averaged` below), which is correct once the formulation is 1-point.
        isolid_prop = _effective_solid_isolid(state, e.pid, sec)
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


#: The `npg` this converter writes on every /INISHE|/INISH3 /STRA_F/GLOB card.
#:
#: Measured on this build with one 1x1 shell, /PROP/SHELL Istrain=1 and
#: /TH/SHEL E1..K12 read at t=0:
#:
#:   Ishell 1 (BT)     npg=1 -> E1 = 0.01   npg=4 -> starter ERROR 1904
#:   Ishell 12 (BATOZ) npg=1 -> E1 = 0.01   npg=4 -> E1 = 0.01
#:   Ishell 24 (QEPH)  npg=1 -> E1 = 0.01   npg=4 -> E1 = 0, SILENT NO-OP
#:   SH3N  1 / 30      npg=1 -> E1 = 0.01   npg=3 -> E1 = 0.01
#:
#: The 2022 Reference Guide p.2048 pairs npg=4 with Ishell=12 — but npg=1 also
#: works for BATOZ (the starter replicates the single value over the element's
#: real Gauss points, cstraini4.F:162-166), while npg=4 on QEPH is discarded
#: with no ANCMSG at all (hm_read_inistate_d00.F:2508-2512 writes a leading NPG
#: marker and shifts PT only IF (IHBE==24); csigini4 skips QEPH via IHBE/=23).
#: One uniform npg=1 is therefore the only form with no formulation lookup and
#: no silent-drop branch.
_STRA_F_NPG = 1


def _stra_f_stations(layers):
    """Reduce a record's through-thickness stations to the (bottom, top) pair
    the starter stores, returning ``(bot, top, forced_t, dropped)``.

    ``hm_read_inistate_d00.F:2525-2528`` reads ``NPP*NPG`` values and then keeps
    ``DO N=1,MIN(2,NPP)`` — at most TWO through-thickness stations, whatever
    ``nb_integr`` says. (The STRS_F branches at :2207/:2274/:3348/:3417 use the
    full ``DO N=1,NIP``; only the STRA_F pair is capped.) The two survivors are
    reconstructed into membrane + one curvature with ``AA = HALF*THKE`` and
    ``kappa = (E2-E1)/(AA*(T2-T1))`` (cstraini4.F:120,153-158), so passing the
    two EXTREME stations through with their own T values is exact for a linear
    through-thickness field and the best possible fit otherwise.

    ``T1 == T2`` is starter ERROR 1904 ("SAME PARAMETRIC POSITION Z= ... WITH
    DIFFERENT IP"), so a single station — or a record whose T column is all
    zeros — is written at T = -1 and +1 with the SAME values: a pure membrane
    state with zero curvature, which is exactly what "one strain value for the
    whole thickness" means. ``forced_t`` reports that substitution.
    """
    if not layers:
        return (None, None, False, 0)
    ordered = sorted(layers, key=lambda p: p[0])
    bot, top = ordered[0], ordered[-1]
    dropped = max(0, len(ordered) - 2)
    if len(ordered) == 1 or _f(bot[0]) == _f(top[0]):
        # Same printed T on both ends: a one-station record, or a deck that
        # left the T column blank. Keep the FIRST and LAST record as read
        # (LS-DYNA's two-card form is inner then outer) at T = -1 / +1.
        bot, top = layers[0], layers[-1]
        return ((-1.0,) + tuple(bot[1:]), (1.0,) + tuple(top[1:]), True, dropped)
    return (bot, top, False, dropped)


def _make_inistra(state: ConversionState) -> List[str]:
    """*INITIAL_STRAIN_SHELL[_SET] → /INISHE/STRA_F/GLOB (4-node /SHELL) and
    /INISH3/STRA_F/GLOB (/SH3N).

    Card layout, hm_cfg_files inishe_stra_f_glob_sub.cfg FORMAT(radioss2021)
    (byte-identical to the radioss2024 block, so nothing is version-gated at
    the /BEGIN 2022 this converter writes)::

        # shell_ID nb_integr       npg               Thick
        CARD("%10d%10d%10d%20lg")
        nb_integr2 = (nb_integr>0 ? nb_integr : 2) * (npg>0 ? npg : 1) records:
        CARD("%20lg%20lg%20lg",      eps_XX, eps_YY, eps_ZZ)
        CARD("%20lg%20lg%20lg%20lg", eps_XY, eps_YZ, eps_ZX, T)

    Choices, each measured on this build:

    * ``npg = 1`` unconditionally — see ``_STRA_F_NPG``.
    * ``nb_integr = 2``, the two extreme through-thickness stations. The
      starter keeps only ``MIN(2,NPP)`` of them anyway
      (hm_read_inistate_d00.F:2528) and the MSGID-26 layer-count cross-check
      that guards the STRS_F variants does NOT fire here: with only STRA_F
      present ``ITHKSHEL=2`` and ``ISIGSH=0``, so both branches of
      csigini.F:144-163 are skipped (verified: nb_integr=2 against /PROP N=5
      runs clean and the strain is consumed).
    * ``Thick = 0`` keeps the property thickness, the same rule ``_make_inishe``
      uses — and ``Thick`` is what sets ``AA = HALF*THKE`` in the curvature
      reconstruction, so an invented value would rescale the curvature.
    * ``eps_XY/YZ/ZX`` are copied 1:1. The Radioss card carries the TENSOR
      component: ``CG2LEPS`` (scigini4.F:791-834) rotates the full 3x3 tensor
      into the element frame and outputs ``EPS(3)=TWO*UXY`` etc., i.e. the
      starter itself doubles them into the engineering shear stored in
      ``GBUF%STRA`` (measured: eps_XY=0.01 on the card reads back as E12=0.02
      in /TH/SHEL). LS-DYNA's EPSij is likewise a component of a strain TENSOR
      "defined in the GLOBAL Cartesian system" (Vol I R17 p.3121), which is why
      dyna2rad copies it unscaled too — the writer states the assumption in a
      warning whenever a shear component is non-zero.
    """
    if not state.ini_strain_shells:
        return []
    shells = {e.eid: e for e in state.shell_elems}
    _quad_ids, tri_ids = _split_shell_eids_by_topology(
        state, [e.eid for e in state.shell_elems])
    tri_set = set(tri_ids)

    quad_entries: List[Tuple[int, Tuple, Tuple]] = []
    tri_entries: List[Tuple[int, Tuple, Tuple]] = []
    missing: List[int] = []
    local_skipped: List[int] = []
    missing_sets: List[int] = []
    forced_t: List[int] = []
    layers_dropped: List[int] = []
    shear_carried = False
    nip_clash: List[int] = []
    stress_eids = {iss.eid for iss in state.ini_stress_shells}

    for rec in state.ini_strain_shells:
        if rec.ilocal == 1:
            local_skipped.append(rec.eid)
            continue
        if rec.is_set:
            entry = state.shell_sets.get(rec.eid)
            if entry is None:
                missing_sets.append(rec.eid)
                continue
            targets = list(entry[1])
        else:
            targets = [rec.eid]
        bot, top, forced, dropped = _stra_f_stations(rec.layers)
        if bot is None:
            missing.append(rec.eid)
            continue
        if any(abs(v) > 0.0 for v in (bot[4], bot[5], bot[6],
                                      top[4], top[5], top[6])):
            shear_carried = True
        for eid in targets:
            if eid not in shells:
                missing.append(eid)
                continue
            if forced:
                forced_t.append(eid)
            if dropped:
                layers_dropped.append(eid)
            if eid in stress_eids:
                sec = _shell_sec_for_part(state, shells[eid].pid)
                if sec is not None and max(2, sec.nip) != 2:
                    nip_clash.append(eid)
            (tri_entries if eid in tri_set else quad_entries).append(
                (eid, bot, top))

    if missing:
        state.warn("*INITIAL_STRAIN_SHELL: element(s) "
                   f"{_fmt_eid_list(missing)} are not 4-node /SHELL or /SH3N "
                   "elements of the converted mesh (no such id, or the id "
                   "names a solid/beam) — their initial strains were skipped.")
    if missing_sets:
        state.warn("*INITIAL_STRAIN_SHELL_SET: shell set(s) "
                   f"{_fmt_eid_list(missing_sets)} not found — their initial "
                   "strains were skipped.")
    if local_skipped:
        state.warn(
            "*INITIAL_STRAIN_SHELL ILOCAL=1 on element(s) "
            f"{_fmt_eid_list(local_skipped)}: DROPPED, not converted. LS-DYNA "
            "itself documents this value as 'local (not supported)' (Vol I R17 "
            "p.3121), so the components' frame is undefined on the source side; "
            "and the Radioss local card /INISHE/STRA_F is not the local twin of "
            "/INISHE/STRA_F/GLOB but a DIFFERENT quantity — membrane strains "
            "plus curvatures (eps_1 eps_2 eps_12 eps_23 eps_31 / k1 k2 k12), "
            "one group per npg, with no eps_ZZ and no T "
            "(radioss110/TABLE/inishe_stra_f_sub.cfg). Writing element-local "
            "components into the GLOB card would ask the starter to rotate an "
            "already-local tensor (CG2LEPS). Set ILOCAL=0 (global) and re-run "
            "to keep these strains.")
    if forced_t:
        state.warn("*INITIAL_STRAIN_SHELL: element(s) "
                   f"{_fmt_eid_list(forced_t)} state one through-thickness "
                   "station (or leave the T column blank), so the two /INISHE "
                   "records were written at T=-1 and T=+1 with identical "
                   "values — a pure membrane state, zero curvature. Two "
                   "records at the SAME T is starter ERROR 1904.")
    if layers_dropped:
        state.warn("*INITIAL_STRAIN_SHELL: NTHICK>2 on element(s) "
                   f"{_fmt_eid_list(layers_dropped)} — only the two EXTREME "
                   "through-thickness stations were written. The starter reads "
                   "at most two anyway (hm_read_inistate_d00.F:2528 "
                   "'DO N=1,MIN(2,NPP)') and reconstructs membrane + one "
                   "curvature from them, so any non-linear part of the "
                   "through-thickness profile is lost in Radioss regardless.")
    if nip_clash:
        state.warn("*INITIAL_STRAIN_SHELL: element(s) "
                   f"{_fmt_eid_list(nip_clash)} carry BOTH an initial strain "
                   "and an *INITIAL_STRESS_SHELL record while their "
                   "/PROP/SHELL N is not 2. Both readers write SIGSH(2) "
                   "(hm_read_inistate_d00.F:2489), so whichever block the "
                   "starter reads last decides the layer count csigini.F:144 "
                   "cross-checks against N — with ISIGSH/=0 a mismatch is "
                   "ERROR 26. Set *SECTION_SHELL NIP=2 on those parts, or drop "
                   "one of the two initial-state blocks.")
    if shear_carried:
        state.warn(
            "*INITIAL_STRAIN_SHELL: EPSxy/EPSyz/EPSzx were copied 1:1 into "
            "eps_XY/eps_YZ/eps_ZX, i.e. both sides are read as TENSOR shear "
            "components. The Radioss side is measured: CG2LEPS "
            "(scigini4.F:809,826-828) outputs 'EPS(3)=TWO*UXY', so the starter "
            "doubles the card value into the engineering shear held in "
            "GBUF%STRA (eps_XY=0.01 reads back as /TH/SHEL E12=0.02). LS-DYNA "
            "documents EPSij only as 'the ij strain component ... in the "
            "GLOBAL Cartesian system' (Vol I R17 p.3121) and dyna2rad copies "
            "it unscaled as well. If your source deck holds ENGINEERING shears "
            "(gamma = 2*epsilon), halve them before converting.")

    if not quad_entries and not tri_entries:
        return []

    def _records(entries: List[Tuple[int, Tuple, Tuple]], keyword: str) -> List[str]:
        out = [keyword]
        for eid, bot, top in entries:
            out += [
                "# shell_ID nb_integr       npg               Thick",
                f"{_i(eid)}{_i(2)}{_i(_STRA_F_NPG)}{_f(0.0)}",
            ]
            for st in (bot, top):
                t, exx, eyy, ezz, exy, eyz, ezx = st
                out += [
                    "#             eps_XX              eps_YY              eps_ZZ",
                    f"{_f(exx)}{_f(eyy)}{_f(ezz)}",
                    "#             eps_XY              eps_YZ              eps_ZX                   T",
                    f"{_f(exy)}{_f(eyz)}{_f(ezx)}{_f(t)}",
                ]
        out.append(HDR)
        return out

    lines = ["#-  INITIAL STATE (*INITIAL_STRAIN_SHELL):", HDR]
    if quad_entries:
        lines += _records(quad_entries, "/INISHE/STRA_F/GLOB")
    if tri_entries:
        lines += _records(tri_entries, "/INISH3/STRA_F/GLOB")
    return lines


def _make_initial_stresses(state: ConversionState) -> List[str]:
    return _make_inishe(state) + _make_inibri(state) + _make_inistra(state)


# ─────────────────────────────────────────────────────────────────────────────
# Starter: reference geometry (*INITIAL_FOAM_REFERENCE_GEOMETRY → /XREF)
# ─────────────────────────────────────────────────────────────────────────────

# Radioss law numbers the starter accepts for a SOLID-part /XREF
# (hm_read_xref.F:222-226, else ERROR 2014). Shell parts skip the check.
#
# The mid → law resolution is NOT done here: ``mesh.py::_target_mat_law`` is the
# single map of what k2rad really emits per material container, and this gate
# reads it. It used to have a private 7-family copy, which returned None — "some
# other law" — for the two families that convert to /MAT/ELAST by a route other
# than ``*MAT_ELASTIC``: ``*MAT_RIGID`` and the ``*MAT_SPOTWELD`` fallback. Both
# are LAW1, LAW1 is on the whitelist above, so both were dropped under a warning
# that claimed a law violation that does not exist.
_XREF_SOLID_LAWS = frozenset({1, 35, 38, 42, 70, 88, 90})


def _airbag_ref_nodes(state: ConversionState) -> Dict[int, Tuple[float, float, float]]:
    """``{nid: (x, y, z)}`` merged over every ``*AIRBAG_REFERENCE_GEOMETRY``
    block, with the ``_ID`` card's SX/SY/SZ scaling already applied.

    Radioss ``/XREF`` has no scale and no origin column, so the ``_ID`` card's
    ``SX SY SZ`` about ``NIDO`` has to be baked into the coordinates at
    CONVERSION time::

        x' = x0 + (x - x0) * SX          (and likewise y, z)

    The origin ``x0`` is NIDO's own REFERENCE coordinate when the table lists
    it, and its structural ``/NODE`` coordinate otherwise. Scaling the
    reference shape about a point of the reference shape keeps the operation
    inside one geometry; dyna2rad takes the structural position unconditionally
    (``convertcontrolvols.cxx:3316-3322``), which mixes the two whenever the
    origin node has moved. NIDO blank defaults to the FIRST listed node
    (Vol I R16), which is also LS-DYNA's own default.

    Later blocks win per node id — LS-DYNA's last-definition order, the same
    merge ``_make_xref`` already applies across *INITIAL_FOAM_REFERENCE_GEOMETRY
    instances.
    """
    merged: Dict[int, Tuple[float, float, float]] = {}
    for ref in state.airbag_ref_geoms:
        if not ref.nodes:
            continue
        nid0 = ref.nid0 or next(iter(ref.nodes))
        if (ref.sx, ref.sy, ref.sz) == (1.0, 1.0, 1.0):
            merged.update(ref.nodes)
            continue
        origin = ref.nodes.get(nid0)
        if origin is None:
            nd = state.nodes.get(nid0)
            origin = (nd.x, nd.y, nd.z) if nd is not None else (0.0, 0.0, 0.0)
            if nd is None:
                state.warn(
                    f"*{ref.keyword}: NIDO={nid0} is neither in the reference "
                    "node table nor in *NODE, so the SX/SY/SZ scaling is "
                    "applied about the GLOBAL ORIGIN instead of about that "
                    "node. Give a NIDO that exists, or state the scaled "
                    "coordinates directly.")
        for nid, (x, y, z) in ref.nodes.items():
            merged[nid] = (origin[0] + (x - origin[0]) * ref.sx,
                           origin[1] + (y - origin[1]) * ref.sy,
                           origin[2] + (z - origin[2]) * ref.sz)
    return merged


def _warn_airbag_ref_options(state: ConversionState) -> None:
    """``_RDT`` and ``_BIRTH`` — the two reference-geometry options that do not
    map onto a ``/XREF`` column.

    ``_RDT`` ("the time step size will be based on the reference geometry once
    the solution time exceeds the birth time") has no Radioss counterpart at
    all. ``_BIRTH`` does: it is the same idea as *MAT_FABRIC's RGBRTH, i.e. a
    ``/SENSOR/TIME`` on the fabric law's ``SENS_ID`` — so it is carried through
    to every fabric material the reference geometry's parts use, and the
    material's own RGBRTH wins where both are stated (LS-DYNA documents RGBRTH
    as the per-material override).
    """
    for ref in state.airbag_ref_geoms + state.airbag_shell_ref_geoms:
        if ref.has_rdt:
            state.warn(
                f"*{ref.keyword}: the _RDT option asks LS-DYNA to base the TIME "
                "STEP on the reference geometry once the birth time passes. "
                "Radioss computes the element time step from the CURRENT "
                "geometry with no such switch, so _RDT is DROPPED. On a bag "
                "whose reference shape is much smaller than the modelled one "
                "this makes the converted run's time step LARGER than "
                "LS-DYNA's, i.e. less conservative — watch the energy balance.")
    birth = max((r.birth for r in state.airbag_ref_geoms), default=0.0)
    if birth <= 0.0:
        return
    pnodes = _part_node_sets(state)
    ref_nids = set(_airbag_ref_nodes(state))
    hit_mids = {state.parts[pid].mid for pid, nids in pnodes.items()
                if pid in state.parts and (nids & ref_nids)}
    armed = []
    for mid in sorted(hit_mids & set(state.mat_fabric)):
        mat = state.mat_fabric[mid]
        if mat.sensor_id:
            continue                       # its own RGBRTH already won
        # next_sensor_id, not next_id — see writer/fabric.py's RGBRTH twin: the
        # /SENSOR namespace now carries USER ids (*ELEMENT_SEATBELT_SENSOR).
        mat.sensor_id = state.next_sensor_id()
        mat.sensor_tdelay = birth
        armed.append(mid)
    if armed:
        state.warn(
            f"*AIRBAG_REFERENCE_GEOMETRY_BIRTH: BIRTH={birth:g} arms the "
            f"reference geometry of *MAT_FABRIC {armed} through a "
            "/SENSOR/TIME on the law's SENS_ID (the starter's "
            "MATPARAM%IPARAM(1) reference-state activation sensor) — the same "
            "mechanism *MAT_FABRIC's own RGBRTH uses. LS-DYNA notes the card "
            "\"does not support multiple birth times\" and the LAST value read "
            "is used for all preceding blocks; the largest is used here.")
    elif hit_mids:
        state.warn(
            f"*AIRBAG_REFERENCE_GEOMETRY_BIRTH: BIRTH={birth:g} is DROPPED — "
            "the parts the reference geometry covers carry no *MAT_FABRIC, and "
            "SENS_ID (the reference-state activation sensor) exists only on "
            "/MAT/LAW19 and /MAT/LAW58. The reference geometry is active from "
            "t=0 instead.")


def _resolve_xref_parts(state: ConversionState) -> None:
    """Decide which parts receive a /XREF block (state.xref_part_ids) —
    build_starter prepass, after the tet10 downgrade/screening (connectivity
    final) and before properties (solid sections serving these parts switch
    to Ismstr=10, see _make_properties).

    dyna2rad emits a /XREF for EVERY part intersecting the reference-geometry
    node table; the OpenRadioss starter then hard-rejects most of them:
    solid parts need a law in 1/35/38/42/70/88/90 (ERROR 2014), 8/4-node
    elements and a 1-integration-point or Ismstr>=10 formulation (ERROR 2013).
    k2rad instead skips the un-runnable combinations with a loud warning
    (deliberate deviation — the converted deck must pass the starter) and
    fixes the formulation side by emitting Ismstr=10 for the kept parts.

    One skip is NOT a starter rule but a physics one: a ``*MAT_RIGID`` part.
    It converts to an /RBODY, so every node it owns is kinematically slaved to
    the rigid master and the part has no strain state a stress-free reference
    geometry could define. The starter takes the block quite happily — its
    /MAT/ELAST is LAW1, on the whitelist, and a rigid brick carrying a /XREF
    measures 0 ERROR(S) 0 WARNING(S) on ``starter_win64`` — it just does
    nothing, while on the solid side it drags the part's *SECTION_SOLID to
    Ismstr=10 (and, through the shared-section rule in ``_emit_prop_solid``,
    any deformable part sharing that section with it). Skipped for both solid
    and shell rigid parts, so the rule is one rule with one reason.

    The kept parts are then checked back against the material REF flags. The
    /XREF is still emitted for a REF=0 material — that is dyna2rad's rule and
    the pre-existing k2rad behaviour, and changing it silently would alter
    already-validated rubber decks — but LS-DYNA would NOT apply the reference
    geometry there ("EQ.0.0: Off"), so the deviation is warned rather than left
    to be discovered in the results."""
    state.xref_part_ids = set()
    # BEFORE the early return: _warn_airbag_ref_options also covers
    # *AIRBAG_SHELL_REFERENCE_GEOMETRY, which never reaches this function's
    # /XREF path at all (it becomes an /EREF), so gating it on the /XREF
    # inputs left a _RDT on a shell-only deck silently dropped.
    _warn_airbag_ref_options(state)
    if not state.foam_ref_geoms and not state.airbag_ref_geoms:
        return
    ref_nids = set()
    for ref in state.foam_ref_geoms:
        ref_nids |= set(ref.nodes)
    ref_nids |= set(_airbag_ref_nodes(state))
    # Which KEYWORD the warnings below should name. Both spellings feed one
    # /XREF per part, so a deck carrying both gets both names rather than a
    # message that points at the wrong card.
    _kws = []
    if state.foam_ref_geoms:
        _kws.append("*INITIAL_FOAM_REFERENCE_GEOMETRY")
    if state.airbag_ref_geoms:
        _kws.append("*AIRBAG_REFERENCE_GEOMETRY")
    kw = " / ".join(_kws)
    pnodes = _part_node_sets(state)
    solid_pids = {e.pid for e in state.solid_elems}
    shell_pids = {e.pid for e in state.shell_elems}
    tet10_pids = {e.pid for e in state.solid_elems if len(e.nodes) == 10}
    sph_hit = sorted({c.pid for c in state.sph_elems if c.nid in ref_nids})
    if sph_hit:
        state.warn(
            f"{kw}: part(s) {sph_hit} hold SPH "
            "particles whose nodes are named by the reference geometry — "
            "SKIPPED. /XREF is reference geometry for SOLID elements "
            "(8/4-node only, else starter ERROR 2013) and an SPH particle is "
            "neither; Radioss has no stress-free reference state for a "
            "particle at all. Those particles start UNSTRESSED, which is what "
            "they would do anyway. (dyna2rad converts no reference geometry of "
            "any kind.)")
    any_hit = False
    for pid, part in sorted(state.parts.items()):
        if not (pnodes.get(pid, set()) & ref_nids):
            continue
        any_hit = True
        if part.mid in state.mat_rigid:
            state.warn(
                f"{kw}: part {pid} (mid "
                f"{part.mid}) is a *MAT_RIGID part — it converts to an /RBODY, "
                "so all of its nodes are kinematically slaved to the rigid "
                "master and it has no strain state for a stress-free "
                "reference geometry to define; /XREF skipped. This is NOT a "
                "starter rejection: the part's /MAT/ELAST is LAW1, which IS "
                "on the solid-/XREF whitelist, and a rigid brick carrying the "
                "block measures 0 ERROR(S) 0 WARNING(S). It is skipped "
                "because it would change no physics while forcing the part's "
                "*SECTION_SOLID to Ismstr=10 — which any deformable part "
                "sharing that section is dragged along into. If the reference "
                "geometry was meant for a deformable part, check the node "
                "table: it currently reaches a rigid one.")
            continue
        if pid in solid_pids:
            if pid in tet10_pids:
                state.warn(
                    f"{kw}: part {pid} has 10-node "
                    "tets — the starter only accepts /XREF on 8/4-node solids "
                    "(ERROR 2013); /XREF skipped for this part, it starts "
                    "unstressed (or convert with --tet10-to-tet4).")
                continue
            law = _target_mat_law(state, part.mid)
            if law not in _XREF_SOLID_LAWS:
                state.warn(
                    f"{kw}: part {pid} (mid "
                    f"{part.mid}) converts to "
                    + (f"/MAT/LAW{law}, which is" if law is not None
                       else "no /MAT at all, so it is")
                    + " outside the starter's solid-/XREF whitelist "
                      "(LAW 1/35/38/42/70/88/90, else ERROR 2014) — /XREF "
                      "skipped for this part, it starts unstressed at the "
                      "modeled coordinates. (dyna2rad emits it and the "
                      "starter then rejects the deck.)")
                continue
            state.xref_part_ids.add(pid)
        elif pid in shell_pids:
            # Shell /XREF passes the starter without law/formulation checks.
            state.xref_part_ids.add(pid)
        else:
            state.warn(
                f"{kw}: part {pid} has no solid/"
                "shell elements — a reference geometry is meaningless for it; "
                "/XREF skipped.")
    if not any_hit and not sph_hit:
        state.warn(
            f"{kw}: its node table intersects no "
            "part's element nodes — no /XREF emitted (check node ids).")
    _warn_xref_on_ref_zero(state, kw)


def _warn_xref_on_ref_zero(state: ConversionState, kw: str) -> None:
    """A /XREF kept by _resolve_xref_parts whose material card says REF=0.

    LS-DYNA reads *INITIAL_FOAM_REFERENCE_GEOMETRY only for materials whose own
    REF flag is on (EQ.0.0: Off / EQ.1.0: On — MAT_181 R17 p.2-1231, MAT_183
    p.2-1240, MAT_091/092 p.2-669, and the four hyperelastic rubbers).
    dyna2rad never reads those flags, and neither does the emission above; the
    part therefore starts from the reference coordinates in Radioss and from
    the modelled ones in LS-DYNA. Reported per part, not per material, because
    that is the granularity at which the block is actually written."""
    if not state.xref_part_ids:
        return
    ref_flag = {}
    for kw, mats in _ref_flag_materials(state):
        for mid, m in mats.items():
            ref_flag[mid] = (kw, m.ref)
    for pid in sorted(state.xref_part_ids):
        part = state.parts.get(pid)
        if part is None:
            continue
        hit = ref_flag.get(part.mid)
        if hit is None or hit[1] != 0.0:
            continue
        kw, _ = hit
        state.warn(
            f"{kw}: part {pid} gets a /XREF, but "
            f"its material ({kw} mid={part.mid}) has REF=0, which in LS-DYNA "
            "means the reference geometry is NOT used for that material "
            "(EQ.0.0: Off). The block is still emitted — dyna2rad converts the "
            "keyword unconditionally and k2rad follows it — so the converted "
            "part starts stress-free at the REFERENCE coordinates while "
            "LS-DYNA starts it at the MODELLED ones. Set REF=1 on the card if "
            "that is intended, or drop the part's nodes from the reference "
            "node table if it is not.")


def _make_xref(state: ConversionState) -> List[str]:
    """*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] → one /XREF per kept part
    (state.xref_part_ids, see _resolve_xref_parts) holding the part's
    stress-free reference coordinates (the hyperelastic-rubber REF=1
    mechanism).

    Follows dyna2rad ConvertInitialFoamReferenceGeometry (CCV:542-653):
    conversion is unconditional (the material REF flags never gate it — they
    only drive the coverage warnings in _resolve_mat_hyper_rubber), node list
    ascending, block named "XREF_PART_<pid>", Nitrs = the _RAMP NDTRRG when
    > 0 (else 0 → starter default). Unlike dyna2rad's per-keyword-instance
    emission, ALL *INITIAL_FOAM_REFERENCE_GEOMETRY blocks are merged into
    exactly ONE /XREF per part (later instances win per node id, LS-DYNA
    last-definition order). A part whose reference coordinates are split
    across several keyword instances would otherwise emit duplicate /XREF
    ids — the current starter happens to tolerate that (hm_read_xref.F tags
    nodes per option and only overwrites tagged ones, so duplicate-id blocks
    union to the same reference state, starter-verified), but the Radioss
    spec defines one /XREF per component and the merged block is the
    canonical form (single echo, no reliance on the reader's duplicate-id
    tolerance). Conflicting _RAMP NDTRRG values feeding one part resolve to
    the largest, warned (the starter itself keeps a global
    NITRS = MAX(all options, floor 100) — the per-part max feeds it
    identically). Card layout audited against hm_cfg_files
    INITIAL_GEOMETRY/xref.cfg FORMAT(radioss90), the block a /BEGIN 2022 deck
    is read with — the header id is the PART (component) id, NOT a material:
      /XREF/<part_ID> / title(100) / Nitrs(10) /
      rows: node_ID(10) X(20) Y(20) Z(20)
    """
    if not state.xref_part_ids:
        return []
    if not state.foam_ref_geoms and not state.airbag_ref_geoms:
        return []
    pnodes = _part_node_sets(state)
    # *AIRBAG_REFERENCE_GEOMETRY feeds the SAME per-part /XREF: it is the same
    # keyword shape (node id + reference X/Y/Z) with the same target, and the
    # starter has no law restriction on a SHELL part's /XREF at all
    # (hm_read_xref.F's MTN whitelist is gated on ITYP == 2, i.e. SOLID parts).
    # Its _ID scaling is already baked into the coordinates by
    # _airbag_ref_nodes; it has no Nitrs equivalent, so a part covered only by
    # an airbag reference geometry gets the starter default.
    airbag_nodes = _airbag_ref_nodes(state)
    lines: List[str] = ["#-  REFERENCE GEOMETRY (/XREF):", HDR]
    for pid in sorted(state.xref_part_ids):
        part_nids = pnodes.get(pid, set())
        merged: Dict[int, Tuple[float, float, float]] = {}
        nitrs_vals: List[int] = []
        for ref in state.foam_ref_geoms:
            common = part_nids & set(ref.nodes)
            if not common:
                continue
            for nid in common:
                merged[nid] = ref.nodes[nid]
            if ref.ndtrrg > 0:
                nitrs_vals.append(ref.ndtrrg)
        for nid in part_nids & set(airbag_nodes):
            merged[nid] = airbag_nodes[nid]
        if not merged:
            continue
        if len(set(nitrs_vals)) > 1:
            state.warn(
                f"*INITIAL_FOAM_REFERENCE_GEOMETRY_RAMP: part {pid} is covered "
                f"by keyword instances with different NDTRRG values "
                f"{sorted(set(nitrs_vals))} — the merged /XREF/{pid} can carry "
                f"only one Nitrs; using the largest ({max(nitrs_vals)}).")
        lines += [
            f"/XREF/{pid}",
            f"XREF_PART_{pid}",
            "#    Nitrs",
            f"{_i(max(nitrs_vals) if nitrs_vals else 0)}",
            "#  node_ID                   X                   Y                   Z",
        ]
        for nid in sorted(merged):
            x, y, z = merged[nid]
            lines.append(f"{_i(nid)}{_f(x)}{_f(y)}{_f(z)}")
        lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: *AIRBAG_SHELL_REFERENCE_GEOMETRY → /EREF/SHELL + /EREF/SH3N
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_airbag_eref(state: ConversionState) -> None:
    """Decide which elements get an ``/EREF`` row.

    Called from ``_make_eref``, NOT from the build_starter prepass block, and
    that is load-bearing: the screens below read ``state.shell_elem_ids`` /
    ``sh3n_elem_ids``, which are filled at the lines that WRITE each element
    row in ``_make_parts_and_elements`` (the #106 "registry filled at the write
    line" rule). A prepass would see them empty and drop every row.

    ``/EREF`` is the per-ELEMENT reference geometry: the row lists GHOST node
    ids whose CURRENT ``/NODE`` coordinates become the reference shape
    (``hm_read_eref.F``: ``XREFC(IN,1,IE) = X(1,NN)``), so the ghost nodes must
    exist and, to carry anything at all, must be DIFFERENT from the element's
    structural nodes.

    Three screens, each guarding a hard starter failure:

      * an element id that is not in the emitted mesh — ``ERROR 1011``
        ("%s ELEMENT ID=%d DOES NOT EXIST");
      * a ghost node id that is in no ``/NODE`` — ``USR2SYS`` refuses it;
      * a node used by BOTH an ``/EREF`` and a ``/XREF`` — ``ERROR 1098``
        ("COMMON NODE IN EREF AND XREF OPTIONS NODE ID: %d"). This is the one
        that really bites, because the two airbag reference-geometry keywords
        are written TOGETHER in LS-DYNA: the node card gives the coordinates
        and the shell card names the elements. Radioss cannot take both on one
        part, so the /XREF wins (it carries real coordinates; the /EREF would
        only re-point at nodes the /XREF already moved) and the /EREF is
        dropped for that part, named.
    """
    state.airbag_eref_rows = {}
    if not state.airbag_shell_ref_geoms:
        return
    quad_pid = {e.eid: e.pid for e in state.shell_elems}
    own_nodes = {e.eid: {n for n in e.nodes if n > 0}
                 for e in state.shell_elems}
    pnodes = _part_node_sets(state)
    xref_nodes: Set[int] = set()
    for pid in state.xref_part_ids:
        xref_nodes |= pnodes.get(pid, set())
    missing_elems: List[int] = []
    missing_nodes: Set[int] = set()
    short_rows: List[int] = []
    noop_elems: List[int] = []
    clash_parts: Set[int] = set()
    rows: Dict[int, Tuple[List[Tuple[int, List[int]]],
                          List[Tuple[int, List[int]]]]] = {}
    for ref in state.airbag_shell_ref_geoms:
        for eid, nodes in ref.elems:
            pid = quad_pid.get(eid)
            if pid is None or (eid not in state.shell_elem_ids
                               and eid not in state.sh3n_elem_ids):
                missing_elems.append(eid)
                continue
            bad = [n for n in nodes if n not in state.nodes]
            if bad:
                missing_nodes.update(bad)
                continue
            # A truncated card leaves NO node ids at all (the handler filters
            # n > 0 down to []), and the `bad` screen above passes vacuously on
            # an empty list. Without this the row reaches _make_eref as an
            # element id with zero node columns.
            if len(nodes) < 3:
                short_rows.append(eid)
                continue
            if pid in state.xref_part_ids:
                clash_parts.add(pid)
                continue
            if set(nodes) == own_nodes.get(eid, set()):
                noop_elems.append(eid)
            quads, tris = rows.setdefault(pid, ([], []))
            if eid in state.sh3n_elem_ids:
                tris.append((eid, nodes[:3]))
            else:
                quads.append((eid, (nodes + nodes[-1:] * 4)[:4]))
    if missing_elems:
        state.warn(
            "*AIRBAG_SHELL_REFERENCE_GEOMETRY: element(s) "
            f"{_fmt_eid_list(sorted(set(missing_elems)))} are not in the "
            "emitted shell mesh, so they get no /EREF row. Naming one is "
            "starter ERROR 1011 (\"ELEMENT ID DOES NOT EXIST\") and the deck "
            "is refused, which is strictly worse than losing their reference "
            "state.")
    if missing_nodes:
        state.warn(
            "*AIRBAG_SHELL_REFERENCE_GEOMETRY: node id(s) "
            f"{sorted(missing_nodes)[:10]} named as reference nodes are in no "
            "*NODE, so their elements get no /EREF row. A /EREF row takes the "
            "CURRENT coordinates of the nodes it lists, so those nodes have to "
            "exist in the model.")
    if short_rows:
        state.warn(
            "*AIRBAG_SHELL_REFERENCE_GEOMETRY: element(s) "
            f"{_fmt_eid_list(sorted(set(short_rows)))} list fewer than three "
            "reference node ids (a truncated card), so they get no /EREF row. "
            "An /EREF row is an element id followed by its reference nodes; "
            "one with no node columns is not a shape.")
    if noop_elems:
        state.warn(
            "*AIRBAG_SHELL_REFERENCE_GEOMETRY: "
            f"{len(noop_elems)} element(s) list their OWN structural nodes as "
            "the reference nodes, so the /EREF reference shape is identical to "
            "the modelled one and the block does nothing. In LS-DYNA the "
            "reference COORDINATES come from *AIRBAG_REFERENCE_GEOMETRY and "
            "the shell card only names the elements; without that companion "
            "card the shell card alone carries no geometry. Add the node card "
            "if a stress-free reference shape was intended.")
    if clash_parts:
        state.warn(
            f"*AIRBAG_SHELL_REFERENCE_GEOMETRY: part(s) {sorted(clash_parts)} "
            "are ALREADY covered by a /XREF from *AIRBAG_REFERENCE_GEOMETRY, "
            "and Radioss refuses a node that appears in both (ERROR 1098, "
            "\"COMMON NODE IN EREF AND XREF OPTIONS\"). The /XREF is kept — it "
            "carries the real reference COORDINATES, while the /EREF would "
            "only re-point at nodes the /XREF has already placed — and the "
            "/EREF rows for those parts are DROPPED. Nothing is lost: the two "
            "LS-DYNA cards describe one reference shape.")
    state.airbag_eref_rows = {pid: v for pid, v in rows.items() if v[0] or v[1]}


def _make_eref(state: ConversionState) -> List[str]:
    """``*AIRBAG_SHELL_REFERENCE_GEOMETRY`` → ``/EREF/SHELL`` and ``/EREF/SH3N``,
    one of each per owning part.

    Card layout from ``INITIAL_GEOMETRY/eref_shell.cfg`` and ``eref_sh3n.cfg``
    ``FORMAT(radioss120)``, reader
    ``loads/reference_state/eref/hm_read_eref.F``::

        /EREF/SHELL/<part_ID>
        <title, 100>
        shell_ID(10) node_ID1(10) node_ID2(10) node_ID3(10) node_ID4(10)

        /EREF/SH3N/<part_ID>
        <title, 100>
        tria_ID(10) node_ID1(10) node_ID2(10) node_ID3(10)

    The header id is the PART, exactly as on ``/XREF`` — LS-DYNA's own PID
    column on the element row is read and discarded ("the part ID is not used
    in this section"), because the owning part is the one the ELEMENT belongs
    to and Radioss takes it from the header. There is no ``Nitrs`` card here.
    """
    if not state.airbag_shell_ref_geoms:
        return []
    _resolve_airbag_eref(state)
    rows = state.airbag_eref_rows
    if not rows:
        return []
    lines: List[str] = ["#-  REFERENCE GEOMETRY (/EREF):", HDR]
    for pid in sorted(rows):
        quads, tris = rows[pid]
        if quads:
            lines += [
                f"/EREF/SHELL/{pid}",
                f"EREF_SHELL_PART_{pid}",
                "# shell_ID  node_ID1  node_ID2  node_ID3  node_ID4",
            ]
            for eid, nds in sorted(quads):
                lines.append(_i(eid) + "".join(_i(n) for n in nds))
            lines.append(HDR)
        if tris:
            lines += [
                f"/EREF/SH3N/{pid}",
                f"EREF_SH3N_PART_{pid}",
                "#  tria_ID  node_ID1  node_ID2  node_ID3",
            ]
            for eid, nds in sorted(tris):
                lines.append(_i(eid) + "".join(_i(n) for n in nds))
            lines.append(HDR)
    return lines


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


def _plane_cut(state: ConversionState, cs,
               extra_pids: Optional[Set[int]] = None,
               warn_missing_psid: bool = True
               ) -> Tuple[List[int], List[int], List[int], List[int]]:
    """Geometric resolver for *DATABASE_CROSS_SECTION_PLANE: an element is cut
    when the signed distances d = (x - tail)·n̂ of its nodes change sign across
    the plane (tail→head = the plane normal), restricted to the parts of PSID
    (0 = all) and — when RADIUS > 0 — to elements whose centroid lies within
    RADIUS of the tail point measured IN the plane. The section node group is
    the cut elements' nodes on the TAIL side (d <= 0): this is the standard
    /SECT construction (section forces = what the tail-side nodes of the cut
    elements transmit through the plane).

    *warn_missing_psid* is False for the second walk of the same section (the
    bolt-preload re-resolve), so a missing part set is reported once.

    *extra_pids* is a SECOND, independent part restriction intersected with the
    card's own PSID — ``*INITIAL_STRESS_SECTION``'s PSID field, which Vol I R17
    p.3144 defines as "Stress is initialized on only those parts included in
    both PSID from this card and the PSID field from the associated
    *DATABASE_CROSS_SECTION card". ``None`` (the default, and every pre-existing
    caller) means no extra restriction, so the emitted /SECT is unchanged.

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
            # warn_missing_psid=False for the bolt-preload re-resolve: the same
            # cross-section is walked twice (once for the reporting /SECT, once
            # for the PSID-intersected preload group) and the message would be
            # printed twice for one deck problem.
            if warn_missing_psid:
                state.warn(
                    f"*DATABASE_CROSS_SECTION_PLANE: part set {cs.psid} not "
                    "found — the plane was intersected with the WHOLE model.")
        else:
            pids = set(entry[1])
    if extra_pids is not None:
        pids = set(extra_pids) if pids is None else (pids & set(extra_pids))
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
    # A thick shell is a /BRICK in the emitted deck, so the same face logic
    # applies and its eid belongs in the /GRBRIC the section references.
    # Without this a *DATABASE_CROSS_SECTION_PLANE through a thick-shell part
    # cut nothing and no /SECT was emitted at all.
    for e in state.tshell_elems:
        _try(e.nodes, e.eid, e.pid, solid_eids)
    # SPH particles are deliberately NOT cut. ``_try`` needs a sign CHANGE
    # across the plane (``dmin < 0 < dmax``) and a particle has exactly one
    # node, so the test could never fire — but that inertness is the point: a
    # /SECT has no SPH group to put the id in either, so an arm here would be
    # dead code that implied a channel exists. ``_warn_sect_sph_scope`` names
    # the loss on the caller's side instead.
    for e in state.beam_elems:
        _try([e.n1, e.n2], e.eid, e.pid, beam_eids)
    return (sorted(node_ids), shell_eids, solid_eids, beam_eids)


def _warn_sect_sph_scope(state: ConversionState, cs, label: str) -> None:
    """A ``*DATABASE_CROSS_SECTION_PLANE`` whose PSID scope reaches SPH parts.

    A ``/SECT`` is a CUT THROUGH ELEMENTS: the starter builds it from the
    element groups grbric/grshel/grtrus/grbeam/grsprg/grtria and sums what the
    tail-side nodes of those elements transmit across the plane. There is no
    SPH group on the card at any version, and an SPH particle has neither a face
    to be cut nor two nodes to be on opposite sides of a plane — so the
    particles' contribution to the section force is simply absent. Reported,
    because "the /SECT converted" plus "the number is too small" is exactly the
    kind of silence that survives a review. (dyna2rad converts no
    *DATABASE_CROSS_SECTION at all.)
    """
    if not state.sph_elems:
        return
    sph_pids = {c.pid for c in state.sph_elems}
    if cs.psid > 0:
        entry = state.part_sets.get(cs.psid)
        scoped = sorted(sph_pids & set(entry[1])) if entry else []
    else:
        scoped = sorted(sph_pids)
    if not scoped:
        return
    state.warn(
        f"*DATABASE_CROSS_SECTION_PLANE {label}: its scope includes SPH "
        f"part(s) {scoped}, whose particles CANNOT be cut. A /SECT sums the "
        "force the cut ELEMENTS transmit across the plane and its card carries "
        "brick/shell/truss/beam/spring/tria groups only — there is no SPH "
        "group at any Radioss version, and a particle has no face to cut and "
        "no second node to put on the far side. The section is emitted from "
        "whatever structural elements the plane does cut, so the reported "
        "force UNDER-REPORTS by the whole SPH contribution.")


def _make_cross_sections(state: ConversionState) -> List[str]:
    """*DATABASE_CROSS_SECTION_PLANE/_SET → /SECT (radioss100 card layout from
    hm_cfg_files sect.cfg):
        /SECT/<id> / title
        node_ID1 node_ID2 node_ID3 grnod_ID ISAVE Frame_ID deltaT alpha
        file_name
        grbric_ID <blank> grshel_ID grtrus_ID grbeam_ID grsprg_ID grtria_ID
        Niter <blank> Iframe
    ISAVE=0 (no section file), no moving frame, Iframe=0 (local skew origin).
    A cut shell set is split by topology: 4-node /SHELL ids go into a
    /GRSHEL/SHEL referenced by grshel_ID, 3-node /SH3N ids go into a
    /GRSH3N/SH3N referenced by grtria_ID. Both are needed since d1ade12 made
    triangles real /SH3N elements — a /SH3N id listed in grshel_ID's group is
    not resolved, so those triangles contribute no force to the section.
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
            _warn_sect_sph_scope(state, cs, label)
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
            # Thick shells share the /BRICK id space and the solid_eids list.
            solids.update({e.eid: e for e in state.tshell_elems})
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
        grshel_id = grbric_id = grbeam_id = grtria_id = 0
        quad_eids, tri_eids = _split_shell_eids_by_topology(state, shell_eids)
        if quad_eids:
            grshel_id = state.next_id()
            lines += _emit_grshel(grshel_id, f"{title}_shells", quad_eids)
        if tri_eids:
            grtria_id = state.next_id()
            lines += _emit_grsh3n(grtria_id, f"{title}_sh3n", tri_eids)
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
            f"{_i(0)}{_i(grtria_id)}{_i(0)}{' ' * 10}{_i(0)}",
            HDR,
        ]
        state.sect_ids.append((sect_id, title))
        emitted = True
    return lines if emitted else []


def _make_starter_th_sectio(state: ConversionState) -> List[str]:
    """*DATABASE_SECFORC → /TH/SECTIO on every emitted /SECT (the secforc file's
    section force/moment resultants, written to the T01 at the /TFILE
    frequency). Emitted whenever sections exist, even without a *DATABASE_SECFORC
    request — harmless and the only way to read the sections back.

    **The DEF channels are time-ACCUMULATED impulses, not the instantaneous
    section resultants.** engine/source/tools/sect/section_c.F:459-467 (shells;
    section_s.F:565-572 for solids) accumulates ``FSAV(k) = FSAV(k) +
    DT12*FST(k)`` for k = 1..9 — the six force components and the three
    moments — and engine/source/output/th/thkin.F:56 copies FSAV into the T01
    buffer undivided. Nothing resets it on the writing rank: hist2.F:616-622
    zeroes FSAV only for ISPMD/=0, and sortie_main.F:1945 ("TRAITEMENT SUR FSAV
    NON CUMULE") resets only the monvol block, FSAV(26) and FSAV(29).

    So FNX/Y/Z and FTX/Y/Z carry force x time and M1/M2/M3 moment x time, and
    the channel rises steadily under a steady load. This is NOT LS-DYNA's
    secforc, which reports the instantaneous resultant: the equivalent is
    d(FNX)/dt (tools/th_to_csv.py writes that column). Same defect class as the
    /TH/NODE REAC* and /TH/INTER channels — one shared FSAV convention, three
    keywords affected."""
    if not state.sect_ids:
        return []
    if not state.db_secforc_dt:
        state.warn("Cross section(s) defined without *DATABASE_SECFORC — "
                   "/TH/SECTIO emitted anyway so the /SECT forces are recorded "
                   "(T01, /TFILE frequency); add *DATABASE_SECFORC to control "
                   "the output interval.")
    state.warn(
        "/TH/SECTIO FNX/Y/Z, FTX/Y/Z, M1/M2/M3: these channels are a "
        "time-ACCUMULATED impulse (force x time) and angular impulse "
        "(moment x time), not the instantaneous section resultants LS-DYNA's "
        "secforc reports — the engine adds DT12*FST every cycle "
        "(section_c.F:459-467, section_s.F:565-572) and never resets the "
        "accumulator on the rank that writes the T01 (hist2.F:616-622 zeroes "
        "FSAV only for ISPMD/=0). Differentiate with respect to time "
        "(F = d(FNX)/dt, e.g. numpy.gradient, or tools/th_to_csv.py which "
        "writes the differentiated column) before comparing against secforc.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_SECFORC -> section force impulses):", HDR,
        f"/TH/SECTIO/{th_id}",
        "TH_SECTIONS",
        "#  DEF = FNX/Y/Z, FTX/Y/Z, M1/M2/M3: IMPULSE (force x time), not force",
        "#  FSAV accumulates F*dt every cycle: section force = d(FNX)/dt",
        "#     var1",
        "DEF       ",
    ]
    lines += [_i(sid) for sid, _title in state.sect_ids]
    lines.append(HDR)
    return lines
