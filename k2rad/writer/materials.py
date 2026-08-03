"""Starter materials: /MAT laws, EOS, failure cards, /FUNCT curves and table resolution."""

from __future__ import annotations

from typing import List, Optional, Tuple
from ..state import (
    ConversionState,
    MatElastic,
    MatPlasTAB,
    MatPlasKin,
    MatJohnsonCook,
    MatAnisoViscoplastic,
    MatRigid,
    MatNull,
    MatPowerLaw,
    MatSAMP,
    FailGissmo,
    MatAddErosion,
    MatCrushableFoam,
    MatLowDensityFoam,
    MatFuChangFoam,
    MatHoneycomb,
    MatBlatzKo,
    MatMooneyRivlin,
    MatOgdenRubber,
    MatHyperelasticRubber,
    MatIsoElasPlas,
    MatStrainRatePlas,
    MatGurson,
    MatPlasCompTens,
    MatViscoelastic,
    MatKelvinMaxwell,
    MatGeneralViscoelastic,
    MatSimplifiedRubber,
    MatSoftTissue,
    Curve,
    MatHighExplosiveBurn,
    EosJwl,
    EosCard,
)
from .common import (HDR, _f, _i, _part_node_sets, _ref_flag_materials,
                     _spotweld_beam_pids)
from .blast_ale import _make_ale_multimaterial

__all__ = [
    "_make_materials",
    "_emit_mat_add_erosion",
    "_emit_mat_law5",
    "_emit_mat_law6_carrier",
    "_emit_eos",
    "_make_explosive_and_eos_materials",
    "_emit_mat_elastic",
    "_emit_mat_elast_for_rigid",
    "_emit_mat_void",
    "_emit_fail_johnson_all_layers",
    "_wrap_cells",
    "_emit_mat_law36",
    "_emit_mat_johnson_cook",
    "_emit_mat_law2_plas_johns",
    "_emit_mat_law4_hyd_jcook",
    "_resolve_mat_johnson_cook",
    "_emit_mat_law44",
    "_emit_mat_law128",
    "_emit_mat_law36_powerlaw",
    "_emit_mat_law76",
    "_emit_mat_law50",
    "_emit_mat_law38",
    "_emit_mat_law70",
    "_emit_mat_law28",
    "_emit_mat_law42_blatz_ko",
    "_emit_mat_mooney_rivlin",
    "_emit_mat_ogden_rubber",
    "_emit_mat_hyper_rubber",
    "_emit_visc_prony",
    "_emit_visc_prony_kv",
    "_emit_visc_prony_full",
    "_emit_visc_prony_fit",
    "_resolve_mat_hyper_rubber",
    "_emit_mat_viscoelastic",
    "_emit_mat_kelvin_maxwell",
    "_emit_mat_general_visco",
    "_emit_mat_simplified_rubber",
    "_emit_mat_soft_tissue",
    "_resolve_mat_viscoelastic",
    "_law2_plas_johns_lines",
    "_resolve_mat_iso_elas_plas",
    "_emit_mat_law2_iso_elas_plas",
    "_emit_mat_law121",
    "_resolve_mat_gurson",
    "_emit_mat_law52",
    "_resolve_mat_plas_comp_tens",
    "_emit_mat_law66",
    "_emit_mat081_tab1",
    "_emit_fail_lemaitre",
    "_emit_plas_tab_extra_fail",
    "_emit_fail_tab2",
    "_make_functions",
    "_resolve_define_tables",
    "_resolve_mat_plas_tab",
    "_resolve_mat_power_law",
    "_add_auto_curve",
]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: materials
# ─────────────────────────────────────────────────────────────────────────────

def _make_materials(state: ConversionState) -> List[str]:
    lines = ["#-  MATERIALS:", HDR]
    for mat in state.mat_elastic.values():
        lines += _emit_mat_elastic(mat)
    for mat in state.mat_plas_tab.values():
        lines += _emit_mat_law36(mat, state)
    for mat in state.mat_plas_kin.values():
        lines += _emit_mat_law44(mat, state)
    for mat in state.mat_johnson_cook.values():
        lines += _emit_mat_johnson_cook(mat, state)
    for mat in state.mat_aniso_visco.values():
        lines += _emit_mat_law128(mat, state)
    for mat in state.mat_rigid.values():
        lines += _emit_mat_elast_for_rigid(mat)
    # A *MAT_NULL that carries a companion *EOS_* becomes a hydro /MAT/LAW6 (with
    # that /EOS) below; a bare *MAT_NULL stays /MAT/VOID (vacuum/void ALE phase).
    void_mids = _void_null_mids(state)
    for mat in state.mat_null.values():
        if mat.mid in void_mids:
            lines += _emit_mat_void(mat)
    for mat in state.mat_power_law.values():
        lines += _emit_mat_law36_powerlaw(mat, state)
    for mat in state.mat_samp.values():
        lines += _emit_mat_law76(mat, state)
    for mat in state.mat_crushable_foam.values():
        lines += _emit_mat_law50(mat, state)
    for mat in state.mat_low_density_foam.values():
        lines += _emit_mat_law38(mat, state)
    for mat in state.mat_fu_chang_foam.values():
        lines += _emit_mat_law70(mat, state)
    for mat in state.mat_honeycomb.values():
        lines += _emit_mat_law28(mat, state)
    # Metal plasticity batch 2 (MAT_081/082 and MAT_105 are already covered by
    # the mat_plas_tab loop above; MAT_122 by _make_composite_materials)
    for mat in state.mat_iso_elas_plas.values():
        lines += _emit_mat_law2_iso_elas_plas(mat, state)
    for mat in state.mat_strain_rate_plas.values():
        lines += _emit_mat_law121(mat, state)
    for mat in state.mat_gurson.values():
        lines += _emit_mat_law52(mat, state)
    for mat in state.mat_plas_comp_tens.values():
        lines += _emit_mat_law66(mat, state)
    # Hyperelastic rubber batch (routing resolved by _resolve_mat_hyper_rubber)
    for mat in state.mat_blatz_ko.values():
        lines += _emit_mat_law42_blatz_ko(mat)
    for mat in state.mat_mooney_rivlin.values():
        lines += _emit_mat_mooney_rivlin(mat)
    for mat in state.mat_ogden.values():
        lines += _emit_mat_ogden_rubber(mat)
    for mat in state.mat_hyper_rubber.values():
        lines += _emit_mat_hyper_rubber(mat)
    # Viscoelastic batch (curve wiring resolved by _resolve_mat_viscoelastic)
    for mat in state.mat_viscoelastic.values():
        lines += _emit_mat_viscoelastic(mat)
    for mat in state.mat_kelvin_maxwell.values():
        lines += _emit_mat_kelvin_maxwell(mat)
    for mat in state.mat_general_visco.values():
        lines += _emit_mat_general_visco(mat)
    for mat in state.mat_simplified_rubber.values():
        lines += _emit_mat_simplified_rubber(mat)
    for mat in state.mat_soft_tissue.values():
        lines += _emit_mat_soft_tissue(mat)
    # *MAT_SPOTWELD normally lives entirely in the /PROP/TYPE13 connector (no
    # /MAT emitted). A MAT_100 referenced by a part the connector path cannot
    # take (shell/solid spotwelds, or a part with no beams) still needs a /MAT
    # for the /PART reference to resolve: fall back to /MAT/ELAST and warn.
    spotweld_pids = _spotweld_beam_pids(state)
    for mid, sw in sorted(state.mat_spotweld.items()):
        fallback_pids = [pid for pid, p in state.parts.items()
                         if p.mid == mid and pid not in spotweld_pids]
        if fallback_pids:
            state.warn(
                f"*MAT_SPOTWELD mid={mid}: part(s) "
                f"{sorted(fallback_pids)} are not pure beam-element parts — "
                "the /PROP/TYPE13 spotweld conversion only handles beam "
                "spotwelds, so those parts keep their elements on a plain "
                "/MAT/ELAST (MAT_100 plasticity and failure DROPPED).")
            lines += _emit_mat_elastic(MatElastic(
                mid, (sw.title or f"MAT_{mid}") + " (MAT_100 fallback)",
                sw.rho, sw.E, sw.nu))
    lines += _make_explosive_and_eos_materials(state)
    lines += _make_ale_multimaterial(state)
    for fail in state.fail_gissmo.values():
        lines += _emit_fail_tab2(fail, state)
    for ero in state.mat_add_erosion.values():
        lines += _emit_mat_add_erosion(ero, state)
    return lines


def _shell_nptt_for_mid(state: ConversionState, mid: int) -> Optional[int]:
    """Through-thickness integration-point count for a material, via any shell
    part that uses it (*PART SECID → *SECTION_SHELL NIP). Needed to turn a
    NUMFIP integration-point *count* into the GENE1 Pthickfail *ratio*."""
    for part in state.parts.values():
        if part.mid != mid:
            continue
        sec = state.sec_shells.get(part.secid)
        if sec is not None and sec.nip > 0:
            return sec.nip
    return None


def _numfip_to_pthickfail(numfip: float, nptt: Optional[int]):
    """LS-DYNA NUMFIP → GENE1 Pthickfail. GENE1 keeps the sign verbatim; the
    engine (fail_setoff_c.F) reads Pthk<0 as 'delete when the broken-IP ratio
    count/NPTT >= |Pthk|', which reproduces NUMFIP exactly for the percent form
    and, given NPTT, for the count forms. Returns (pthk, needs_nptt)."""
    if -100.0 <= numfip < 0.0:            # |NUMFIP| percent of IPs (shells)
        return -abs(numfip) / 100.0, False
    if numfip < -100.0:                   # (|NUMFIP|-100) IPs (shells)
        count = abs(numfip) - 100.0
        if nptt:
            return -min(count / nptt, 1.0), False
        return 0.0, True
    if numfip > 1.0:                      # NUMFIP IPs
        if nptt:
            return -min(numfip / nptt, 1.0), False
        return 0.0, True
    # NUMFIP = 1 (default) or any 0 < NUMFIP <= 1 → erode on the first failed IP
    return -1.0e-6, False


def _emit_mat_add_erosion(ero: MatAddErosion, state: ConversionState) -> List[str]:
    """*MAT_ADD_EROSION → /FAIL/GENE1 (the card that subsumes the full card-1/
    card-2 scalar-criteria set; layout audited against hm_cfg_files
    FAIL/fail_gene1.cfg FORMAT(radioss2022), the block a /BEGIN 2022 deck reads
    with — note this block has NO trailing FAILIP on card 6, unlike 2025+):

      C1 Pmin Pmax SigP1_max Time_max dtmin
      C2 fct_IDsm _ Eps_dot_sm Sig_max Sigr K
      C3 fct_IDps _ Eps_dot_ps Eps_max Eps_eff Eps_vol
      C4 Eps_min Eps_s fct_IDg12 fct_IDg13 fct_IDe1c
      C5 tab_IDfld Itab Eps_dot_fld Nstep Ismooth Istrain _ Thinning
      C6 Volfrac Pthickfail NCS _ Temp_max
      C7 fct_IDel _ Fscale_el El_ref

    Signs follow the GENE1 reader (hm_read_fail_gene1.F): it forces Pmin=-ABS,
    Pmax=+ABS, Eps_min=-ABS and maps 0→±INFINITY (a criterion is active iff its
    field /= 0). SIGVM/MXEPS keep the LS-DYNA <0-means-load-curve convention →
    the fct_IDsm/fct_IDps function slots with a 1.0 ordinate scale."""
    if ero.idam:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: IDAM={ero.idam} (GISSMO/DIEM in "
                   "the erosion card) is not converted — the card-1/card-2 "
                   "scalar criteria still map to /FAIL/GENE1; for the damage "
                   "model use *MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2.")

    active = any((ero.mxpres, ero.mneps, ero.effeps, ero.voleps, ero.mnpres,
                  ero.sigp1, ero.sigvm, ero.mxeps, ero.epssh, ero.sigth,
                  ero.impulse, ero.failtm, ero.dtmin))
    if not active:
        if not ero.idam:
            state.warn(f"*MAT_ADD_EROSION {ero.mid}: no active scalar criterion "
                       "(MXPRES/MNPRES/SIGP1/SIGVM/MXEPS/MNEPS/EFFEPS/VOLEPS/"
                       "EPSSH/SIGTH/IMPULSE/FAILTM) — no /FAIL/GENE1 emitted.")
        return []

    if ero.excl != 0.0:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: EXCL={ero.excl:g} is non-default "
                   "— fields equal to it were treated as inactive (GENE1 uses "
                   "0 = inactive). Verify no genuine 0.0 threshold was intended.")

    # Card 1 — pressures / time. The reader re-signs these, but emit the final
    # sign for a human-readable deck.
    pmin = -abs(ero.mnpres) if ero.mnpres else 0.0
    pmax = abs(ero.mxpres) if ero.mxpres else 0.0
    tmax = 0.0
    if ero.failtm > 0.0:
        tmax = ero.failtm
    elif ero.failtm < 0.0:
        tmax = abs(ero.failtm)
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: FAILTM={ero.failtm:g} < 0 "
                   "(inactive during dynamic relaxation in LS-DYNA); GENE1 has "
                   "no such flag — mapped as an always-active failure time "
                   f"{abs(ero.failtm):g}.")
    # SIGP1 < 0 is the LS-DYNA load-curve form (|SIGP1| = a max-principal-stress-
    # vs-strain-rate curve id). GENE1's SigP1_max has no function slot, and its
    # reader would read a negative value as a fixed |value| threshold restricted
    # to positive triaxialities — turning a curve id into a spurious, usually
    # tiny, stress threshold that erodes the element immediately. So drop it
    # (leave SigP1_max inactive) rather than emit that garbage threshold.
    sigp1_out = ero.sigp1 if ero.sigp1 >= 0.0 else 0.0
    if ero.sigp1 < 0.0:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: SIGP1={ero.sigp1:g} < 0 is the "
                   "LS-DYNA load-curve form (|SIGP1| is a stress-vs-strain-rate "
                   "curve id); GENE1 has no SigP1_max function slot, so the "
                   "criterion is DROPPED (left inactive) rather than emitted as "
                   "a spurious fixed stress threshold.")

    # Card 2 — SIGVM: scalar Sig_max (>0) or fct_IDsm (<0 = |SIGVM| curve id).
    if ero.sigvm < 0.0:
        fct_idsm, sig_max = int(-ero.sigvm), 1.0
        _warn_missing_curve(state, ero.mid, fct_idsm, "SIGVM")
    else:
        fct_idsm, sig_max = 0, ero.sigvm
    # Card 3 — MXEPS: scalar Eps_max (>0) or fct_IDps (<0 = |MXEPS| curve id).
    if ero.mxeps < 0.0:
        fct_idps, eps_max = int(-ero.mxeps), 1.0
        _warn_missing_curve(state, ero.mid, fct_idps, "MXEPS")
    else:
        fct_idps, eps_max = 0, ero.mxeps
    eps_eff = abs(ero.effeps) if ero.effeps else 0.0
    eps_min = -abs(ero.mneps) if ero.mneps else 0.0

    # Card 6 — NUMFIP → Pthickfail; NCS.
    pthk, needs_nptt = _numfip_to_pthickfail(
        ero.numfip, _shell_nptt_for_mid(state, ero.mid))
    if needs_nptt:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: NUMFIP={ero.numfip:g} is an "
                   "integration-point count but no *SECTION_SHELL NIP was found "
                   "for the material — Pthickfail left at the default (delete "
                   "near full thickness). Verify the shell integration scheme.")
    ncs = max(1, int(round(ero.ncs)))
    blank = " " * 10

    lines = [
        f"/FAIL/GENE1/{ero.mid}",
        "#               Pmin                Pmax           SigP1_max            Time_max               dtmin",
        f"{_f(pmin)}{_f(pmax)}{_f(sigp1_out)}{_f(tmax)}{_f(ero.dtmin)}",
        "# fct_IDsm                    Eps_dot_sm             Sig_max                Sigr                   K",
        f"{_i(fct_idsm)}{blank}{_f(0.0)}{_f(sig_max)}{_f(ero.sigth)}{_f(ero.impulse)}",
        "# fct_IDps                    Eps_dot_ps             Eps_max             Eps_eff             Eps_vol",
        f"{_i(fct_idps)}{blank}{_f(0.0)}{_f(eps_max)}{_f(eps_eff)}{_f(ero.voleps)}",
        "#            Eps_min               Eps_s fct_IDg12 fct_IDg13 fct_IDe1c",
        f"{_f(eps_min)}{_f(ero.epssh)}{_i(0)}{_i(0)}{_i(0)}",
        "#tab_IDfld      Itab         Eps_dot_fld     Nstep   Ismooth   Istrain                      Thinning",
        f"{_i(0)}{_i(0)}{_f(0.0)}{_i(0)}{_i(0)}{_i(0)}{blank}{_f(0.0)}",
        "#            Volfrac          Pthickfail       NCS                      Temp_max",
        f"{_f(0.0)}{_f(pthk)}{_i(ncs)}{blank}{_f(0.0)}",
        "# fct_IDel                     Fscale_el              El_ref",
        f"{_i(0)}{blank}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]
    return lines


def _warn_missing_curve(state: ConversionState, mid: int, fid: int,
                        field: str) -> None:
    if fid and fid not in state.curves:
        state.warn(f"*MAT_ADD_EROSION {mid}: {field} references load curve "
                   f"{fid} (negative-value form) that is not in the model — the "
                   "/FAIL/GENE1 function reference will dangle.")


def _emit_mat_law5(state: ConversionState, heb: MatHighExplosiveBurn,
                   jwl: Optional[EosJwl]) -> List[str]:
    """*MAT_HIGH_EXPLOSIVE_BURN (+ its *EOS_JWL) → /MAT/LAW5 (JWL).

    Card layout from MAT/matl5_jwl.cfg FORMAT(radioss2019). The JWL A,B,R1,R2,ω,E0
    come from the paired *EOS_JWL (shared id); D and P_CJ from the MAT_008 card.
    """
    if jwl is None:
        state.warn(f"*MAT_HIGH_EXPLOSIVE_BURN {heb.mid}: no companion *EOS_JWL "
                   "(same id) — /MAT/LAW5 emitted with zero JWL coefficients; add "
                   "an *EOS_JWL or the detonation product has no pressure law.")
        a = b = r1 = r2 = omega = e0 = 0.0
    else:
        a, b, r1, r2, omega, e0 = jwl.a, jwl.b, jwl.r1, jwl.r2, jwl.omega, jwl.e0
        if jwl.vo not in (0.0, 1.0):
            state.warn(f"*EOS_JWL {jwl.eosid}: VO={jwl.vo} (initial relative "
                       "volume) has no /MAT/LAW5 field — Radioss references E0 to "
                       "the initial volume; verify the initial state.")
    return [
        f"/MAT/LAW5/{heb.mid}",
        heb.title or f"HE_{heb.mid}",
        "#              RHO_I",
        f"{_f(heb.rho)}",
        "#                  A                   B                  R1                  R2               OMEGA",
        f"{_f(a)}{_f(b)}{_f(r1)}{_f(r2)}{_f(omega)}",
        "#                  D                P_CJ                  E0                Eadd   I_BFRAC      Qopt",
        f"{_f(heb.d)}{_f(heb.pcj)}{_f(e0)}{_f(0.0)}         0         0",
        "#                 P0                 PSH          Bunreacted",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_mat_law6_carrier(mid: int, title: str, rho: float) -> List[str]:
    """A hydrodynamic /MAT/LAW6 (keyword /MAT/HYD_VISC) carrier for an /EOS.

    Minimal form (RHO + blank kinematic-viscosity/Pmin card) exactly as the
    official Drop_Container FSI example pairs it with a separate /EOS block of the
    same id.
    """
    return [
        f"/MAT/HYD_VISC/{mid}",
        title or f"FLUID_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#                 Nu                Pmin",
        f"{_f(0.0)}{_f(0.0)}",
    ]


def _emit_eos(eos: EosCard) -> List[str]:
    """A standalone /EOS/<kind> block (id == its material id). Layout from
    MAT/mat_EOS.cfg FORMAT(radioss2022)."""
    p = eos.params
    head = [f"/EOS/{eos.kind}/{eos.eosid}", f"EOS_{eos.kind}_{eos.eosid}"]
    if eos.kind == "POLYNOMIAL":
        return head + [
            "#                 C0                  C1                  C2                  C3",
            f"{_f(p['c0'])}{_f(p['c1'])}{_f(p['c2'])}{_f(p['c3'])}",
            "#                 C4                  C5                  E0                P_sh               RHO_0",
            f"{_f(p['c4'])}{_f(p['c5'])}{_f(p['e0'])}{_f(p['psh'])}{_f(p['rho0'])}",
            HDR,
        ]
    if eos.kind == "GRUNEISEN":
        return head + [
            "#                  C                  S1                  S2                  S3",
            f"{_f(p['c'])}{_f(p['s1'])}{_f(p['s2'])}{_f(p['s3'])}",
            "#                 Y0                   a                  E0               RHO_0",
            f"{_f(p['y0'])}{_f(p['a'])}{_f(p['e0'])}{_f(p['rho0'])}",
            HDR,
        ]
    if eos.kind == "IDEAL-GAS":
        return head + [
            "#              Gamma                  P0                 PSH                  T0               RHO_0",
            f"{_f(p['gamma'])}{_f(p['p0'])}{_f(p['psh'])}{_f(p['t0'])}{_f(p['rho0'])}",
            HDR,
        ]
    return head + [HDR]


def _null_part_eos_bindings(state: ConversionState) -> dict:
    """*MAT_NULL mid → the *EOS_* id(s) a *PART binds to it via its EOSID
    field (LS-DYNA's actual EOS attachment), in pid order.

    Only nulls that do NOT already own a same-id *EOS_* count — for those the
    legacy shared-id pairing wins — and only supported *EOS_* kinds
    (state.eos_cards) qualify. Same-id bindings (p.eosid == p.mid) are the
    shared-id convention itself and are excluded here."""
    out: dict = {}
    for p in sorted(state.parts.values(), key=lambda q: q.pid):
        if (p.mid in state.mat_null and p.mid not in state.eos_cards
                and p.eosid and p.eosid != p.mid
                and p.eosid in state.eos_cards):
            ids = out.setdefault(p.mid, [])
            if p.eosid not in ids:
                ids.append(p.eosid)
    return out


def _void_null_mids(state: ConversionState) -> set:
    """*MAT_NULL mids that stay a plain /MAT/VOID — no /EOS attaches to them.

    A *MAT_NULL is instead carried by an EOS-bearing material when it
      * shares its id with a supported *EOS_* (the legacy pairing convention)
        → /MAT/LAW6 (HYD_VISC) + /EOS/<kind>, or
      * is bound to one by a *PART EOSID field (_null_part_eos_bindings), or
      * shares its id with a *MAT_HIGH_EXPLOSIVE_BURN **and** an *EOS_JWL
        → /MAT/LAW5 (the JWL pair; a null of that id would collide with it).

    An *EOS_JWL alone does NOT carry the null: OpenRadioss has no standalone
    /EOS/JWL (JWL exists only inside /MAT/LAW5), so with no explosive of that
    id nothing would be emitted and every /PART on the null would dangle
    (starter ERROR 179, "MATERIAL ID=n DOES NOT EXIST"). The null falls back
    to /MAT/VOID and _make_explosive_and_eos_materials says so."""
    carried = set(state.eos_cards)
    carried |= set(state.eos_jwl) & set(state.mat_high_explosive)
    carried |= set(_null_part_eos_bindings(state))
    return {mid for mid in state.mat_null if mid not in carried}


def _derive_ideal_gas_p0(state: ConversionState, eos: EosCard,
                         rho: float) -> None:
    """Radioss /EOS/IDEAL-GAS requires a POSITIVE initial pressure. LS-DYNA
    gives specific heats + temperature, so derive P0 = rho*(Cp-Cv)*T0."""
    if eos.kind != "IDEAL-GAS" or eos.params.get("p0", 0.0) > 0.0:
        return
    cv = eos.params.get("cv", 0.0)
    cp = eos.params.get("cp", 0.0)
    t0 = eos.params.get("t0", 0.0)
    if rho > 0.0 and cp > cv > 0.0 and t0 > 0.0:
        eos.params["p0"] = rho * (cp - cv) * t0
    else:
        state.warn(f"*EOS_IDEAL_GAS {eos.eosid}: could not derive a positive "
                   "initial pressure (need density, Cv<Cp and T0) — "
                   "/EOS/IDEAL-GAS P0 left 0, which the starter rejects; "
                   "set P0 manually.")


def _make_explosive_and_eos_materials(state: ConversionState) -> List[str]:
    """/MAT/LAW5 explosives and /MAT/LAW6+/EOS fluids for the coupled ALE path."""
    if not (state.mat_high_explosive or state.eos_cards or state.eos_jwl):
        return []
    lines: List[str] = []
    # An *EOS_* consumed by a *MAT_JOHNSON_COOK /MAT/LAW4 route is emitted
    # there (rebound to the mat id) — not as a standalone LAW6-carrier fluid.
    jc_consumed = _jc_consumed_eos_ids(state)
    # JWL high explosives: *MAT_HIGH_EXPLOSIVE_BURN + *EOS_JWL → /MAT/LAW5
    for mid, heb in sorted(state.mat_high_explosive.items()):
        lines += _emit_mat_law5(state, heb, state.eos_jwl.get(mid))
    void_mids = _void_null_mids(state)
    for eosid in sorted(set(state.eos_jwl) - set(state.mat_high_explosive)):
        if eosid in void_mids:
            # *MAT_NULL + *EOS_JWL with no explosive: the null keeps its /MAT
            # card (as /MAT/VOID) so the /PART resolves, but the JWL pressure
            # law is gone — OpenRadioss carries JWL only inside /MAT/LAW5.
            state.warn(
                f"*EOS_JWL {eosid}: no companion *MAT_HIGH_EXPLOSIVE_BURN "
                "(same id) — OpenRadioss carries JWL only inside the "
                "/MAT/LAW5 explosive, so the JWL parameters were NOT emitted "
                f"and the same-id *MAT_NULL fell back to /MAT/VOID/{eosid}: "
                "that part now has NEITHER strength NOR pressure (the "
                "detonation-product expansion is lost, so it applies no load "
                "to its surroundings). Add a *MAT_HIGH_EXPLOSIVE_BURN of id "
                f"{eosid} (density, detonation velocity D, P_CJ) to get the "
                "/MAT/LAW5 JWL explosive.")
        elif eosid not in jc_consumed:
            state.warn(f"*EOS_JWL {eosid}: no companion *MAT_HIGH_EXPLOSIVE_BURN "
                       "(same id) — the JWL parameters have no material to attach to "
                       "and were not emitted (add the explosive material).")
    # Other fluids: carrier /MAT/LAW6 (HYD_VISC) + /EOS/<kind>. A carrier is
    # the same-id *MAT_NULL (the legacy shared-id pairing) and/or any *MAT_NULL
    # a *PART binds to this EOS via its EOSID field — the /EOS is then
    # re-emitted under that null's mid, because Radioss binds an /EOS to the
    # /MAT of the SAME id.
    null_bindings = _null_part_eos_bindings(state)
    for mid, ids in sorted(null_bindings.items()):
        if len(ids) > 1:
            state.warn(f"*MAT_NULL {mid}: parts bind different EOS ids "
                       f"{ids} to this material — Radioss binds one /EOS per "
                       f"material id, so only EOS {ids[0]} is used; duplicate "
                       "the material per part to keep distinct equations of "
                       "state.")
    for eosid, eos in sorted(state.eos_cards.items()):
        null_mids = [eosid] if eosid in state.mat_null else []
        null_mids += sorted(m for m, ids in null_bindings.items()
                            if ids[0] == eosid)
        if not null_mids:
            if eosid in jc_consumed:
                continue
            rho = eos.params.get("rho0", 0.0)
            if rho <= 0.0:
                state.warn(f"*EOS_{eos.kind} {eosid}: no companion *MAT_NULL "
                           "to give a density for the /MAT/LAW6 carrier and "
                           "no reference density — RHO_I left 0; set the "
                           "fluid density.")
            _derive_ideal_gas_p0(state, eos, rho)
            lines += _emit_mat_law6_carrier(eosid, "", rho)
            lines += _emit_eos(eos)
            continue
        _derive_ideal_gas_p0(state, eos, state.mat_null[null_mids[0]].rho)
        for mid in null_mids:
            carrier = state.mat_null[mid]
            lines += _emit_mat_law6_carrier(mid, carrier.title, carrier.rho)
            if mid == eosid:
                lines += _emit_eos(eos)
            else:
                state.warn(
                    f"*EOS_{eos.kind} {eosid}: bound to *MAT_NULL {mid} via "
                    f"a *PART EOSID — emitted as /EOS/{eos.kind}/{mid} on "
                    "the /MAT/LAW6 carrier of that id (Radioss binds an "
                    "/EOS to the material of the SAME id).")
                lines += _emit_eos(EosCard(eosid=mid, kind=eos.kind,
                                           params=eos.params, rho0=eos.rho0,
                                           note=eos.note))
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


def _emit_fail_johnson_all_layers(mid: int, epsf: float,
                                  state: ConversionState, *,
                                  d2: float = 0.0, d3: float = 0.0,
                                  d4: float = 0.0, d5: float = 0.0,
                                  eps_dot_0: float = 0.0, ifail_so: int = 1,
                                  warn: bool = True) -> List[str]:
    """LS-DYNA built-in material failure (MAT_003 FS / MAT_024 FAIL / MAT_018
    EPSF) deletes a shell only when the plastic-strain criterion is met at ALL
    through-thickness integration points, so bending that plastifies one face
    does not erode the element. The LAW36/LAW44 built-in Eps_max instead
    deletes on the FIRST integration point that reaches it — on the W13
    BlastVehicle z-ground pair (FS=0.0015, blast + plate ringing) that eroded
    2413 shells where LS-DYNA eroded 428, so the OpenRadioss debris flew off
    with ~5.7e9 mJ of kinetic energy that LS-DYNA instead dissipated as
    plastic work (KE +29% / IE -89% at t=6 ms).

    /FAIL/JOHNSON with D1=epsf and D2..D5=0 makes the damage integral
    D = sum(d_eps_p / eps_f) reach 1 exactly at eps_p = epsf per integration
    point — the same per-point threshold — and Ifail_sh=2 applies the
    LS-DYNA-like ALL-points deletion rule (Ifail_so=1: solids fail on their
    single point as in LS-DYNA ELFORM 1). Card layout audited against
    hm_cfg_files fail_johnson.cfg FORMAT(radioss2017), the block a /BEGIN 2022
    deck is read with: D1-D5 (5x20); EPSILON_DOT_0(20) IFAIL_SH(10)
    IFAIL_SO(10) blank(20) DADV(20).

    The keyword arguments carry the genuine *MAT_JOHNSON_COOK D1-D5 damage law
    (epsf is then D1, ``warn=False`` because nothing is moved or approximated);
    they default to the historical single-criterion output, byte-identical for
    the FS/FAIL/EPSF callers.
    """
    if warn:
        state.warn(
            f"MAT {mid}: failure strain {epsf:g} moved from the material Eps_max "
            "(deletes the shell at the FIRST integration point that fails) to "
            "/FAIL/JOHNSON D1 with Ifail_sh=2 (deletes only when ALL "
            "through-thickness points fail) to match LS-DYNA's built-in "
            "material-failure erosion rule."
        )
    return [
        f"/FAIL/JOHNSON/{mid}",
        "#                 D1                  D2                  D3                  D4                  D5",
        f"{_f(epsf)}{_f(d2)}{_f(d3)}{_f(d4)}{_f(d5)}",
        "#      EPSILON_DOT_0  IFAIL_SH  IFAIL_SO                                    DADV",
        f"{_f(eps_dot_0)}         2{_i(ifail_so)}                    {_f(0.0)}",
        HDR,
    ]


def _resolve_mat_johnson_cook(state: ConversionState) -> None:
    """Route each *MAT_JOHNSON_COOK to /MAT/LAW2 or /MAT/LAW4 and fold DTF>0
    into a /FAIL/GENE1 dtmin.

    dyna2rad's law choice (convertmats.cxx:323-332) triggers on the *PART EOSID
    alone — ANY attached EOS routes MAT_015 to LAW4, even one whose type cannot
    be converted (the EOS is then dropped, here with a warning instead of
    silently). k2rad additionally honours its own shared-id convention
    (eosid == mid, the *MAT_NULL + *EOS_* pairing rule) as a warned fallback,
    but ONLY for an *EOS_* that no *PART in the deck binds via its EOSID —
    a part-bound EOS belongs to THAT binding, and in LS-DYNA a material with
    no part EOSID has no EOS at all, so the material stays LAW2 exactly like
    dyna2rad. A shared-id *EOS_JWL never triggers the fallback (JWL pairs
    only with *MAT_HIGH_EXPLOSIVE_BURN as /MAT/LAW5).

    DTF handling follows dyna2rad exactly: on the plain (LAW2) path DTF>0
    emits ONLY a /FAIL/GENE1 with dtmin=DTF and discards D1-D5; the EOS (LAW4)
    path has no DTF branch, so DTF is ignored there and D1-D5 still apply.
    The GENE1 rides on state.mat_add_erosion so the one-GENE1-per-material
    rule and the existing emitter are shared with *MAT_ADD_EROSION."""
    for mat in state.mat_johnson_cook.values():
        if mat.ortho:
            continue    # MAT_099: always LAW2 (+/FAIL/FLD); no EOS/DTF fields
        part_eosids = sorted({p.eosid for p in state.parts.values()
                              if p.mid == mat.mid and p.eosid})
        if part_eosids:
            mat.use_law4 = True
            mat.eos_id = part_eosids[0]
            if len(part_eosids) > 1:
                state.warn(
                    f"*MAT_JOHNSON_COOK mid={mat.mid}: parts bind different "
                    f"EOS ids {part_eosids} to this material — Radioss binds "
                    "one /EOS per material id, so only EOS "
                    f"{part_eosids[0]} is used; duplicate the material per "
                    "part to keep distinct equations of state.")
            noeos_pids = sorted(p.pid for p in state.parts.values()
                                if p.mid == mat.mid and not p.eosid)
            if noeos_pids:
                state.warn(
                    f"*MAT_JOHNSON_COOK mid={mat.mid}: part(s) {noeos_pids} "
                    "reference this material WITHOUT an EOSID while an "
                    "EOS-attached part routes it to the hydrodynamic "
                    "/MAT/LAW4 — Radioss has one law per material id, so "
                    "those parts get the LAW4 + /EOS too (dyna2rad "
                    "duplicates a multi-part material and keeps "
                    "/MAT/PLAS_JOHNS for the EOS-less parts); duplicate the "
                    "material in the deck to keep a plain LAW2 there.")
        elif (mat.mid in state.eos_cards
              and not any(p.eosid == mat.mid for p in state.parts.values())):
            mat.use_law4 = True
            mat.eos_id = mat.mid
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: no *PART attaches an EOS, "
                f"but *EOS_{state.eos_cards[mat.mid].kind} {mat.mid} shares "
                "the material id and is bound to no other part — rerouted to "
                "/MAT/LAW4 + /EOS by k2rad's shared-id pairing convention. "
                "In LS-DYNA an *EOS_* binds only through the *PART EOSID "
                "field (an unreferenced EOS is inert, and dyna2rad would "
                "keep /MAT/PLAS_JOHNS) — set the part EOSID, or renumber "
                "the EOS, if this pairing is unintended.")

        if mat.dtf <= 0.0:
            continue
        if mat.use_law4:
            # dyna2rad's EOS path has no DTF branch (solids have no
            # minimum-timestep shell deletion) — D1-D5 still apply.
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: DTF={mat.dtf:g} is ignored "
                "on the EOS (/MAT/LAW4) path — LS-DYNA's timestep criterion "
                "applies to shells only, and dyna2rad drops it here too; "
                "D1-D5 (if set) still convert to /FAIL/JOHNSON.")
            continue
        if any((mat.d1, mat.d2, mat.d3, mat.d4, mat.d5)):
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: DTF={mat.dtf:g} > 0 takes "
                "priority over D1-D5 (dyna2rad rule): only /FAIL/GENE1 "
                "dtmin is emitted and the Johnson-Cook damage parameters are "
                "DISCARDED. Clear DTF to keep the D1-D5 damage law.")
        ero = state.mat_add_erosion.get(mat.mid)
        if ero is None:
            state.mat_add_erosion[mat.mid] = MatAddErosion(
                mid=mat.mid, excl=0.0, mxpres=0.0, mneps=0.0, effeps=0.0,
                voleps=0.0, numfip=1.0, ncs=1.0, mnpres=0.0, sigp1=0.0,
                sigvm=0.0, mxeps=0.0, epssh=0.0, sigth=0.0, impulse=0.0,
                failtm=0.0, idam=0, dtmin=mat.dtf)
        elif ero.dtmin == 0.0:
            ero.dtmin = mat.dtf
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: DTF={mat.dtf:g} merged "
                "into this material's existing /FAIL/GENE1 (*MAT_ADD_EROSION) "
                "as dtmin — OpenRadioss keeps one GENE1 per material.")
        elif ero.dtmin != mat.dtf:
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: DTF={mat.dtf:g} conflicts "
                f"with the dtmin={ero.dtmin:g} already on this material's "
                "/FAIL/GENE1 — the existing value is kept.")


def _jc_consumed_eos_ids(state: ConversionState) -> set:
    """*EOS_* ids bound to a *MAT_JOHNSON_COOK /MAT/LAW4 (they are emitted with
    the LAW4, rebound to the mat id — not as standalone LAW6-carrier fluids)."""
    return {m.eos_id for m in state.mat_johnson_cook.values()
            if m.use_law4 and m.eos_id}


def _emit_mat_johnson_cook(mat: MatJohnsonCook,
                           state: ConversionState) -> List[str]:
    """Route one Johnson-Cook material: /MAT/LAW2 (PLAS_JOHNS), or /MAT/LAW4
    (HYD_JCOOK) + its bound /EOS when _resolve_mat_johnson_cook attached one,
    plus the failure trailer (/FAIL/JOHNSON from D1-D5, or /FAIL/FLD from
    MAT_099 PSFAIL; a DTF /FAIL/GENE1 is injected via state.mat_add_erosion)."""
    if mat.use_law4:
        lines = _emit_mat_law4_hyd_jcook(mat, state)
    else:
        lines = _emit_mat_law2_plas_johns(mat, state)

    if mat.ortho:
        if mat.psfail > 0.0:
            lines += _emit_mat099_fld(mat, state)
        return lines

    d_any = any((mat.d1, mat.d2, mat.d3, mat.d4, mat.d5))
    dtf_active = mat.dtf > 0.0 and not mat.use_law4   # → /FAIL/GENE1 dtmin
    if d_any and not dtf_active:
        # Native JC damage: D1-D5 verbatim except D3, which is forced negative
        # (LS-DYNA sigma* = p/sigma_eff is compression-positive, Radioss
        # sigma* = sigma_m/sigma_VM is tension-positive — dyna2rad's -abs(D3)).
        # EPSILON_DOT_0 = EPS0 so the D4 rate term keeps the material's
        # reference rate (dyna2rad leaves it 0 — a documented trap: the D4
        # term would fall to the starter default rate instead of EPS0).
        # EROD != 0 (LS-DYNA "no erosion") → Ifail_so=2 (deviatoric stress
        # vanishes per IP, solid kept); EROD=0 → Ifail_so=1 (delete solid).
        lines += _emit_fail_johnson_all_layers(
            mat.mid, mat.d1, state,
            d2=mat.d2, d3=-abs(mat.d3), d4=mat.d4, d5=mat.d5,
            eps_dot_0=mat.epso,
            ifail_so=2 if mat.erod != 0.0 else 1,
            warn=False)
        if mat.efmin:
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: EFMIN={mat.efmin:g} (lower "
                "bound on the fracture strain) has no EPSF_MIN slot in the "
                "radioss2017-format /FAIL/JOHNSON card a /BEGIN 2022 deck "
                "reads — dropped; the unclamped Johnson-Cook failure strain "
                "applies.")
    return lines


def _law2_plas_johns_lines(mid: int, title: str, rho: float, e: float,
                           nu: float, a: float, b: float, n: float, *,
                           eps_p_max: float = 0.0, sig_max0: float = 0.0,
                           c: float = 0.0, eps_dot_0: float = 0.0,
                           fsmooth: int = 0, m: float = 0.0,
                           t_melt: float = 0.0, rhocp: float = 0.0,
                           t_r: float = 0.0) -> List[str]:
    """The /MAT/LAW2 (PLAS_JOHNS) card body, shared by every keyword that lands
    on it (*MAT_JOHNSON_COOK, *MAT_ISOTROPIC_ELASTIC_PLASTIC).

    Layout audited against hm_cfg_files MAT/matl2_plas_johns.cfg
    FORMAT(radioss140) — the block a /BEGIN 2022 deck is read with (the
    flagVP column only exists from FORMAT(radioss2023) on):
      RHO_I(20) / E(20) Nu(20) Iflag(10) /
      a(20) b(20) n(20) EPS_p_max(20) SIG_max0(20) /
      c(20) EPS_DOT_0(20) ICC(10) Fsmooth(10) F_cut(20) Chard(20) /
      m(20) T_melt(20) rhoC_p(20) T_r(20)
    Blank(0) fields keep the starter defaults: n→1, EPS_p_max/SIG_max0→1e30,
    ICC→1, T_melt→1e20 (softening off), T_r→300, m→1."""
    return [
        f"/MAT/LAW2/{mid}",
        title or f"MAT_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#                  E                  Nu     Iflag",
        f"{_f(e)}{_f(nu)}{_i(0)}",
        "#                  a                   b                   n           EPS_p_max            SIG_max0",
        f"{_f(a)}{_f(b)}{_f(n)}{_f(eps_p_max)}{_f(sig_max0)}",
        "#                  c           EPS_DOT_0       ICC   Fsmooth               F_cut               Chard",
        f"{_f(c)}{_f(eps_dot_0)}{_i(0)}{_i(fsmooth)}{_f(0.0)}{_f(0.0)}",
        "#                  m              T_melt              rhoC_p                 T_r",
        f"{_f(m)}{_f(t_melt)}{_f(rhocp)}{_f(t_r)}",
        HDR,
    ]


def _emit_mat_law2_plas_johns(mat: MatJohnsonCook,
                              state: ConversionState) -> List[str]:
    """*MAT_JOHNSON_COOK → /MAT/LAW2 (PLAS_JOHNS), classic a,b,n input
    (Iflag=0). See _law2_plas_johns_lines for the card layout."""
    if mat.pc != 0.0:
        state.warn(
            f"*MAT_JOHNSON_COOK mid={mat.mid}: PC={mat.pc:g} (pressure cutoff) "
            "has no slot on /MAT/LAW2 — dropped. It only maps to the "
            "hydrodynamic /MAT/LAW4 Pmin, which needs an *EOS_* attached to "
            "the part.")
    return _law2_plas_johns_lines(
        mat.mid, mat.title, mat.rho, mat.e, mat.nu, mat.a, mat.b, mat.n,
        eps_p_max=mat.eps_p_max, sig_max0=mat.sig_max0, c=mat.c,
        eps_dot_0=mat.epso, fsmooth=mat.fsmooth, m=mat.m, t_melt=mat.tmelt,
        rhocp=mat.rhocp, t_r=mat.tref)


def _emit_mat_law4_hyd_jcook(mat: MatJohnsonCook,
                             state: ConversionState) -> List[str]:
    """/MAT/LAW4 (HYD_JCOOK) + the bound /EOS/<kind> of the SAME id — the
    faithful target for *MAT_JOHNSON_COOK on parts that attach an *EOS_*.

    Layout audited against hm_cfg_files MAT/matl4_hyd_jcook.cfg from the
    radioss2020 config directory — the newest one a /BEGIN 2022 deck resolves
    to. NOTE: T0 joined the RHOCP heat card in the radioss2019 config revision
    (the radioss2018 directory's copy ends at RHOCP), so audit against
    radioss2019+ even though the block inside is still labelled
    FORMAT(radioss2018); the starter echo confirms T0 is read from cols 61-80:
      RHO_I(20) / E(20) nu(20) / A(20) B(20) n(20) epsmax(20) sigmax(20) /
      Pmin(20) / C(20) EPS_DOT_0(20) M(20) Tmelt(20) Tmax(20) /
      RHOCP(20) blank(40) T0(20)
    PC → Pmin (forced negative, the tensile-cutoff sign both solvers use).
    TR → T0 (initial/room temperature; the starter defaults T0 to 300 when 0).
    dyna2rad instead writes TR into Tmax ("temperature above which m=1") —
    physically wrong (room temperature would disable thermal hardening), so
    that quirk is deliberately not replicated; Tmax stays 0 → 1e20."""
    lines = [
        f"/MAT/LAW4/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu",
        f"{_f(mat.e)}{_f(mat.nu)}",
        "#                  A                   B                   n              epsmax              sigmax",
        f"{_f(mat.a)}{_f(mat.b)}{_f(mat.n)}{_f(0.0)}{_f(0.0)}",
        "#               Pmin",
        f"{_f(-abs(mat.pc) if mat.pc != 0.0 else 0.0)}",
        "#                  C           EPS_DOT_0                   M               Tmelt                Tmax",
        f"{_f(mat.c)}{_f(mat.epso)}{_f(mat.m)}{_f(mat.tmelt)}{_f(0.0)}",
        "#              RHOCP" + " " * 58 + "T0",
        f"{_f(mat.rhocp)}" + " " * 40 + f"{_f(mat.tref)}",
        HDR,
    ]
    eos = state.eos_cards.get(mat.eos_id)
    if eos is not None:
        if eos.eosid != mat.mid:
            state.warn(
                f"*MAT_JOHNSON_COOK mid={mat.mid}: the *PART-bound "
                f"*EOS_{eos.kind} {eos.eosid} is emitted as "
                f"/EOS/{eos.kind}/{mat.mid} — Radioss binds an /EOS to the "
                "material of the SAME id.")
        lines += _emit_eos(EosCard(eosid=mat.mid, kind=eos.kind,
                                   params=eos.params, rho0=eos.rho0,
                                   note=eos.note))
    elif mat.eos_id in state.eos_jwl:
        state.warn(
            f"*MAT_JOHNSON_COOK mid={mat.mid}: the attached *EOS_JWL "
            f"{mat.eos_id} cannot bind to /MAT/LAW4 (JWL converts only as the "
            "/MAT/LAW5 explosive pair) — the material is emitted as LAW4 "
            "WITHOUT an /EOS, so its volumetric response is undefined; attach "
            "an *EOS_LINEAR_POLYNOMIAL or *EOS_GRUNEISEN instead.")
    else:
        state.warn(
            f"*MAT_JOHNSON_COOK mid={mat.mid}: the *PART references EOSID "
            f"{mat.eos_id} but no supported *EOS_* card with that id was "
            "parsed — the material is emitted as /MAT/LAW4 WITHOUT an /EOS "
            "(dyna2rad routes on the EOSID alone and drops the EOS the same "
            "way), so its volumetric response is undefined.")
    return lines


def _emit_mat099_fld(mat: MatJohnsonCook, state: ConversionState) -> List[str]:
    """*MAT_099 PSFAIL → /FAIL/FLD (dyna2rad p_ConvertMatL99). The mandatory
    forming-limit function is a flat major-strain limit at PSFAIL + A/E (the
    plastic failure strain plus the elastic strain at yield) over minor strain
    -1..1 — dyna2rad's exact 2-point curve. Card layout from hm_cfg_files
    FAIL/fail_fld.cfg FORMAT(radioss2019) (same block the MAT_123 FLD uses);
    Ifail_sh=2, I_marg=1 (no marginal card), Istrain=0, Ixfem=0."""
    limit = mat.psfail + (mat.a / mat.e if mat.e > 0.0 else 0.0)
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, f"Auto_MAT099_FLD_mid{mat.mid}",
                    [(-1.0, limit), (1.0, limit)])
    state.warn(
        f"*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE mid={mat.mid}: "
        f"PSFAIL={mat.psfail:g} → /FAIL/FLD with a flat major-strain limit "
        f"{limit:g} (= PSFAIL + A/E); the orthotropic damage evolution itself "
        "is not reproduced.")
    return [
        f"/FAIL/FLD/{mat.mid}",
        "#   FCT_ID  IFAIL_SH    I_MARG FCT_IDADV                RANI                DADV   ISTRAIN     IXFEM",
        f"{_i(fid)}{_i(2)}{_i(1)}{_i(0)}{_f(0.0)}{_f(0.0)}{_i(0)}{_i(0)}",
        HDR,
    ]


def _wrap_cells(cells: List[str], per_line: int = 5) -> List[str]:
    """Join pre-formatted fixed-width cells into lines of *per_line* cells —
    the cfg CELL_LIST wrapping (5 ids of %10d / 5 floats of %20lg per line)."""
    return ["".join(cells[i:i + per_line])
            for i in range(0, len(cells), per_line)]


def _emit_mat_law36(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    fid = mat.funct_id
    fail = mat.fail if 0.0 < mat.fail < 1e19 else 0.0
    if mat.rate_fcts:
        # Strain-rate function family (N_funct = k). Layout audited against
        # hm_cfg_files MAT/matl36_plas_tab.cfg FORMAT(radioss2017) — the block
        # a /BEGIN 2022 deck is read with:
        #   N_funct(10) F_smooth(10) C_hard(20) F_cut(20) Eps_f(20) 10x VP(10)
        #   fct_IDp(10) Fscale(20) Fct_IDE(10) EInf(20) CE(20)
        #   func_ID_i   CELL_LIST %10d (5 per line)
        #   Fscale_i    CELL_LIST %20lg (5 per line)
        #   Eps_dot_i   CELL_LIST %20lg (5 per line)
        fam = sorted(mat.rate_fcts, key=lambda t: t[2])   # ascending Eps_dot
        # F_smooth = 2 → logarithmic strain-rate interpolation between the yield
        # curves (the *MAT_..._LOG_INTERPOLATION option); 0 → linear (default).
        # Only meaningful with >1 rate curve — the LAW36 reader forces it to 0
        # for a single static curve anyway.
        f_smooth = 2 if mat.log_interp else 0
        nf_card = f"{_i(len(fam))}{_i(f_smooth)}"
        if mat.vp:
            nf_card += " " * 70 + _i(mat.vp)              # VP at cols 91-100
        lines = [
            f"/MAT/LAW36/{mat.mid}",
            mat.title or f"MAT_{mat.mid}",
            "#              RHO_I",
            f"{_f(mat.rho)}",
            "#                  E                  Nu          Eps_p_max",
            f"{_f(mat.E)}{_f(mat.nu)}                   0",
            "#  N_funct  F_smooth              C_hard               F_cut               Eps_f                  VP",
            nf_card,
            "#  fct_IDp              Fscale",
            "         0                 1.0",
            "# func_ID1  func_ID2  func_ID3  func_ID4  func_ID5",
            *_wrap_cells([_i(f) for f, _, _ in fam]),
            "#           Fscale_1            Fscale_2            Fscale_3            Fscale_4            Fscale_5",
            *_wrap_cells([_f(s) for _, s, _ in fam]),
            "#          Eps_dot_1           Eps_dot_2           Eps_dot_3           Eps_dot_4           Eps_dot_5",
            *_wrap_cells([_f(r) for _, _, r in fam]),
            HDR,
        ]
        if fail > 0.0:
            lines += _emit_fail_johnson_all_layers(mat.mid, fail, state)
        lines += _emit_plas_tab_extra_fail(mat, state)
        return lines
    lines = [
        f"/MAT/LAW36/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu          Eps_p_max",
        f"{_f(mat.E)}{_f(mat.nu)}                   0",
        "# N_funct   F_smooth",
        "         1         0",
        "# fct_IDp      Fscale",
        "         0                 1.0",
        "# fct_ID1",
        f"{_i(fid)}",
        "# Fscale1",
        "                 1.0",
        "#          Eps_dot_1",
        "                   0",
        HDR,
    ]
    if fail > 0.0:
        lines += _emit_fail_johnson_all_layers(mat.mid, fail, state)
    lines += _emit_plas_tab_extra_fail(mat, state)
    return lines


def _emit_plas_tab_extra_fail(mat: MatPlasTAB,
                              state: ConversionState) -> List[str]:
    """The failure trailer that rides alongside a /MAT/LAW36, dispatched on the
    LS-DYNA keyword family that filled the record.

    MAT_024 and MAT_098 have none beyond the FAIL → /FAIL/JOHNSON the base
    emitter already wrote, so this is a no-op for them (they route into the
    MAT_123 branch, whose three fields all stay 0)."""
    if mat.family in ("081", "082"):
        return _emit_mat081_tab1(mat, state)
    if mat.family == "105":
        return _emit_fail_lemaitre(mat, state)
    return _emit_mat123_extra_fail(mat, state)


def _emit_mat123_extra_fail(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    """*MAT_123 (*MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY) failure inputs that
    ride alongside the base LAW36 material — the LAW36 card itself is emitted
    unchanged and FAIL still becomes /FAIL/JOHNSON. Only the three MAT_123-only
    card-2 extras act here (they stay 0 for plain MAT_024, so this is a no-op for
    MAT_024): EPSTHIN → /FAIL/TAB1 P_THICKFAIL, EPSMAJ → /FAIL/FLD, NUMINT →
    the failed-integration-point deletion convention. Mirrors dyna2rad
    p_ConvertMatL123 (convertmats.cxx:6169-6246)."""
    lines: List[str] = []
    if mat.epsthin > 0.0:
        lines += _emit_mat123_tab1(mat, state)
    elif mat.epsthin < 0.0:
        state.warn(f"*MAT_123 {mat.mid}: EPSTHIN={mat.epsthin:g} < 0 (averaged "
                   "thinning from element thickness change) is not represented "
                   "by /FAIL/TAB1 P_THICKFAIL — thinning failure dropped.")
    if mat.epsmaj != 0.0:
        lines += _emit_mat123_fld(mat, state)
    if mat.numint != 0.0:
        # NUMINT counts the integration points that must fail before the shell is
        # deleted (0 = ALL). Radioss reproduces the ALL-points rule (Ifail_sh=2)
        # on whichever /FAIL card(s) this material actually emits, not an exact IP
        # count (same limitation as MAT_103's NUMINT). Which cards those are
        # depends on FAIL/EPSTHIN/EPSMAJ, so name them rather than assume JOHNSON.
        emitted = [name for cond, name in (
            (0.0 < mat.fail < 1e19, "/FAIL/JOHNSON"),
            (mat.epsthin > 0.0,     "/FAIL/TAB1"),
            (mat.epsmaj != 0.0,     "/FAIL/FLD"))
            if cond]
        if emitted:
            state.warn(f"*MAT_123 {mat.mid}: NUMINT={mat.numint:g} (integration "
                       "points that must fail before element deletion) is "
                       "approximated by the Ifail_sh=2 all-points rule on "
                       f"{', '.join(emitted)}; the exact IP-count threshold is "
                       "not reproduced.")
        else:
            state.warn(f"*MAT_123 {mat.mid}: NUMINT={mat.numint:g} is set but the "
                       "material emits no /FAIL card (FAIL=0, EPSTHIN=0, "
                       "EPSMAJ=0) — there is no failure criterion for it to "
                       "modify, so NUMINT is dropped.")
    if mat.lcsr:
        state.warn(f"*MAT_123 {mat.mid}: LCSR={mat.lcsr} (strain-rate scaling "
                   "curve) has no /MAT/LAW36 counterpart — ignored (LS-DYNA also "
                   "ignores LCSR when LCSS is a table).")
    return lines


def _emit_mat123_tab1(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    """*MAT_123 EPSTHIN → /FAIL/TAB1 P_THICKFAIL. Layout from hm_cfg_files
    FAIL/fail_tab1.cfg FORMAT(radioss2021) — the block a /BEGIN 2022 deck reads
    with (TAB1 is not redefined after 2021). Card 1 and 5 carry literal space
    runs: C1 is Ifail_sh(10) Ifail_so(10) [20 sp] P_thickfail(20) P_thinfail(20)
    [10 sp] Ixfem(10); C5 is fct_IDt(10) FscaleT(20) [30 sp] Shear_limit(20)
    Biax_limit(20).

    table1_ID is mandatory (else starter ERROR 2068) and is a failure-strain-vs-
    triaxiality table. FAIL already lives on the base /FAIL/JOHNSON, so the table
    here is a flat 'never reached' plateau (eps_f = 10.0, dyna2rad's FAIL==0
    sentinel) across the usual triaxiality bracket [-0.3, 0, +0.3]: the card
    exists purely to carry P_THICKFAIL, avoiding a second plastic-strain
    criterion. Ifail_sh=2 makes the reader honour P_thickfail=EPSTHIN
    (hm_read_fail_tab1.F: P_THICK>0 .and. IFAIL_SH>1 → PTHKF=P_THICK).

    Fidelity note: P_THICKFAIL deletes the shell once a fraction of its own IPs
    have failed, but with the inert plateau table no IP ever fails *via TAB1*
    (the base FAIL/JOHNSON tracks IP failure on its own card, not TAB1's), so
    P_THICKFAIL never actually triggers. EPSTHIN thinning erosion is therefore
    NOT reproduced by this carrier card — matching dyna2rad p_ConvertMatL123,
    which emits the same inert plateau. The card is kept for reference/round-trip
    parity and to document the dropped criterion, not for a live effect."""
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, f"Auto_MAT123_thinfail_mid{mat.mid}",
                    [(-0.3, 10.0), (0.0, 10.0), (0.3, 10.0)])
    sp20, sp10, sp30 = " " * 20, " " * 10, " " * 30
    state.warn(f"*MAT_123 {mat.mid}: EPSTHIN={mat.epsthin:g} is carried into a "
               "/FAIL/TAB1 P_THICKFAIL (Ifail_sh=2), but its strain table is an "
               "inert plateau (FAIL stays on /FAIL/JOHNSON to avoid double-"
               "counting), so no IP fails via TAB1 and P_THICKFAIL never fires — "
               "EPSTHIN thinning erosion is NOT reproduced (matches dyna2rad).")
    return [
        f"/FAIL/TAB1/{mat.mid}",
        "# IFAIL_SH  IFAIL_SO                             P_THICKFAIL          P_thinfail               Ixfem",
        f"{_i(2)}{_i(0)}{sp20}{_f(mat.epsthin)}{_f(0.0)}{sp10}{_i(0)}",
        "#              Dcrit                   D                   N                Dadv   fct_IDD",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
        "#TABLE1_ID             Xscale1             Xscale2 TABLE2_ID             Xscale3             Xscale4",
        f"{_i(fid)}{_f(0.0)}{_f(0.0)}{_i(0)}{_f(0.0)}{_f(0.0)}",
        "# fct_IDEL           Fscale_EL              EI_REF          INST_START             FAD_EXP    CH_I_F",
        f"{_i(0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
        "#  fct_IDT             FscaleT                              Shear_limit             Biax_limit",
        f"{_i(0)}{_f(0.0)}{sp30}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_mat123_fld(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    """*MAT_123 EPSMAJ → /FAIL/FLD. Layout from hm_cfg_files FAIL/fail_fld.cfg
    FORMAT(radioss2019) — the block a /BEGIN 2022 deck reads with: fct_ID(10)
    Ifail_sh(10) I_marg(10) fct_IDadv(10) Rani(20) Dadv(20) Istrain(10) Ixfem(10).

    fct_ID is mandatory (else starter ERROR 2001) — the forming-limit curve. LS-
    DYNA's EPSMAJ is a single triaxiality/minor-strain-independent major-strain
    threshold, so the FLD is a flat line at |EPSMAJ| over the [-0.3, 0, +0.3]
    minor-strain bracket (mirrors dyna2rad). I_marg=1 so no marginal card;
    Istrain=0 (true strain), matching dyna2rad."""
    epsmaj = abs(mat.epsmaj)
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, f"Auto_MAT123_FLD_mid{mat.mid}",
                    [(-0.3, epsmaj), (0.0, epsmaj), (0.3, epsmaj)])
    state.warn(f"*MAT_123 {mat.mid}: EPSMAJ={mat.epsmaj:g} → /FAIL/FLD "
               f"(forming-limit failure, flat major-strain limit {epsmaj:g}).")
    return [
        f"/FAIL/FLD/{mat.mid}",
        "#   FCT_ID  IFAIL_SH    I_MARG FCT_IDADV                RANI                DADV   ISTRAIN     IXFEM",
        f"{_i(fid)}{_i(2)}{_i(1)}{_i(0)}{_f(0.0)}{_f(0.0)}{_i(0)}{_i(0)}",
        HDR,
    ]


# *MAT_081 EPPF / EPPFR "no failure" sentinel. LS-DYNA's own blank defaults are
# 1e12 (EPPF) and 1e14 (EPPFR), but a blank cell is read as 0.0 here, so the
# substitution happens on the writer side — 1e14 for both, matching dyna2rad
# (convertmats.cxx:4727-4731) and far enough above any real plastic strain that
# the corresponding leg of the damage law never engages.
_MAT081_NO_FAIL = 1.0e14


def _emit_mat081_tab1(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    """*MAT_PLASTICITY_WITH_DAMAGE (081/082) EPPF/EPPFR → /FAIL/TAB1.

    Layout from hm_cfg_files FAIL/fail_tab1.cfg FORMAT(radioss2021) — the block
    a /BEGIN 2022 deck reads with (TAB1 is not redefined after 2021); the two
    literal space runs on cards 1 and 5 are documented on _emit_mat123_tab1.

    LS-DYNA's damage is ``omega = (eps_p - EPPF)/(EPPFR - EPPF)``, linear from
    the softening onset EPPF to rupture at EPPFR, knocking the stress down to
    ``(1 - omega)*sigma_y`` on the way (Vol II R17 p.2-606, Figure M81-1).
    /FAIL/TAB1 accumulates ``D += DP*d(eps_p)/eps_f`` and deletes at
    ``D >= Dcrit``, where ``DP = n*D^(1-1/n)`` when no fct_IDd is given
    (fail_tab_c.F:406-429). With the card's blank defaults ``n=1`` and
    ``Dcrit=1`` that is exactly the same linear ramp, so the mapping is:

      * TABLE1_ID (the mandatory FAILURE-strain table) = a flat EPPFR plateau,
      * TABLE2_ID (the INSTABILITY / softening-onset table) = a flat EPPF one,

    both over the triaxiality bracket [-1, +1] — dyna2rad's exact two-point
    tables (convertmats.cxx:4753-4801), emitted here as 1-D /FUNCTs, which the
    TAB1 reader accepts in a table slot (verified live against a starter run).
    Unlike the MAT_123 carrier card this table is LIVE: MAT_081 has no FAIL
    field, so TAB1 is the material's only plastic-strain criterion and nothing
    is double-counted.

    ``FAD_EXP = 1.0`` is what makes the SOFTENING half of that law real, and it
    is not optional. ``hm_read_fail_tab1.F:153-157`` zeroes ECRIT as soon as a
    TABLE2 is given, so ``:170-174`` (``DMG_FLAG = 1`` only if
    ``FADE_EXPO > 0 .or. ECRIT /= 0``) leaves DMG_FLAG at 0 for a blank
    exponent — and ``fail_tab_c.F:441-455`` gates the whole necking block, the
    only place EPSF_N (i.e. EPPF) is ever read, on ``DMG_FLAG == 1``. With
    ``FAD_EXP = 1`` and ``D = 0`` that block gives
    ``DMG_SCALE = 1 - ((eps_p - EPPF)/(EPPFR - EPPF))^1``, LS-DYNA's ``1-omega``
    exactly, and ``mulawc.F90:2656``/``:2724`` multiply the layer stress by it.
    SHELLS ONLY: ``fail_tab_s.F`` reads ITABLF(1) and computes no DMG_SCALE at
    all, so on solid elements the instability table is inert whatever is
    written here and the material carries full yield stress up to EPPFR. The
    rupture strain itself is exact on both. One further Radioss-side nuance:
    ``fail_tab_c.F:444`` accumulates the necking damage only while
    ``SIGM = P/SVM >= 0``, so under a net-COMPRESSIVE mean stress the softening
    never starts — LS-DYNA's omega ramp has no such gate and is driven by
    eps_p alone.

    ``Ifail_sh=2`` (delete only when the whole through-thickness stack has
    failed) is both dyna2rad's choice and the rule k2rad applies to every
    LS-DYNA built-in material failure; it is also what makes the reader honour
    a POSITIVE P_thickfail, which is where NUMINT lands.

    Both strains blank means the LS-DYNA material never softens and never
    ruptures, so NO card is emitted (dyna2rad always writes one with its 1e14
    substitution — equivalent, but a card that can never fire).
    """
    eppf = mat.eppf if mat.eppf > 0.0 else _MAT081_NO_FAIL
    eppfr = mat.eppfr if mat.eppfr > 0.0 else _MAT081_NO_FAIL
    kw = "*MAT_082" if mat.ortho_damage else "*MAT_081"
    no_damage = mat.eppf <= 0.0 and mat.eppfr <= 0.0
    if mat.tdel:
        state.warn(
            f"{kw} {mat.mid}: TDEL={mat.tdel:g} (minimum timestep element "
            "deletion) has no /MAT/LAW36 or /FAIL/TAB1 slot and is DROPPED. "
            "Add *MAT_ADD_EROSION with DTMIN on this material to keep it "
            "(k2rad maps that to the /FAIL/GENE1 dtmin).")
    if no_damage:
        # Both strains blank: LS-DYNA's own defaults (1e12 / 1e14) mean the
        # material never softens and never ruptures, so no failure card is
        # emitted at all rather than an inert one. dyna2rad always writes the
        # TAB1 with its 1e14 substitution, which is equivalent but noise.
        if mat.numint or mat.lcdm:
            state.warn(
                f"{kw} {mat.mid}: EPPF and EPPFR are both blank, so the "
                "material has NO damage and no /FAIL/TAB1 is emitted — "
                + ", ".join(
                    n for n, v in (("NUMINT", mat.numint), ("LCDM", mat.lcdm))
                    if v)
                + " has nothing to act on and is DROPPED with it.")
        return []
    if 0.0 < mat.eppfr <= mat.eppf and mat.eppf > 0.0:
        state.warn(
            f"{kw} {mat.mid}: EPPFR={mat.eppfr:g} is not greater than "
            f"EPPF={mat.eppf:g}, so the LS-DYNA damage ramp "
            "(eps_p-EPPF)/(EPPFR-EPPF) is degenerate. The /FAIL/TAB1 "
            "instability and failure tables are emitted as given; check the "
            "deck — rupture must come after softening onset.")
    # NUMINT → P_thickfail, as a POSITIVE fraction. fail_setoff_c.F:139-146
    # does read a NEGATIVE FAIL%PTHK as "ratio of broken integration points",
    # which is literally NUMINT's meaning — but the TAB1 reader never lets one
    # through: hm_read_fail_tab1.F:181-187 is
    #   IF (P_THICK > 0 .and. IFAIL_SH > 1) PTHKF = P_THICK
    #   ELSEIF (IFAIL_SH == 1) PTHKF = 1e-6
    #   ELSEIF (IFAIL_SH == 2) PTHKF = 1 - 1e-6
    # so with the Ifail_sh=2 written above a negative value is silently
    # REPLACED by "all thickness must fail" (and :216 pins UPARAM(3) to 0 with
    # the comment "not used (P_THICK)"). /FAIL/GENE1 keeps its raw value, TAB1
    # does not. The positive branch is the only channel that survives, so the
    # IP count is expressed as the equivalent broken-THICKNESS fraction
    # NUMINT/NIP: fail_setoff_c.F:163 sums THKLY over the failed points, which
    # coincides with the IP ratio for a uniformly weighted stack and is off by
    # the integration weights otherwise. Without a shell section on the
    # material there is no NIP to divide by.
    pthick = 0.0
    nptt = _shell_nptt_for_mid(state, mat.mid)
    if mat.numint > 0.0:
        if nptt:
            pthick = min(mat.numint / nptt, 1.0)
            state.warn(
                f"{kw} {mat.mid}: NUMINT={mat.numint:g} (integration points "
                f"that must fail before the shell is deleted) → /FAIL/TAB1 "
                f"P_thickfail={pthick:g}, using NIP={nptt} from the "
                "*SECTION_SHELL on this material. APPROXIMATION: the TAB1 "
                "reader DISCARDS the negative form that would mean 'ratio of "
                "failed IPs' (hm_read_fail_tab1.F:181-187 replaces it with "
                "all-thickness), so the count is carried as the equivalent "
                "positive broken-THICKNESS fraction — identical for a "
                "uniformly weighted stack, off by the integration weights for "
                "a Gauss one, where the outer points that fail first carry "
                "less thickness and the element survives slightly longer.")
        else:
            state.warn(
                f"{kw} {mat.mid}: NUMINT={mat.numint:g} counts integration "
                "points, but /FAIL/TAB1 P_thickfail is a RATIO and no "
                "*SECTION_SHELL on this material states a NIP to divide by — "
                "NUMINT is DROPPED and the default all-points rule "
                "(Ifail_sh=2) applies instead.")
    elif mat.numint < 0.0:
        state.warn(
            f"{kw} {mat.mid}: NUMINT={mat.numint:g} < 0 is not a documented "
            "form on this keyword (unlike *MAT_120, where it is a percentage) "
            "— it is DROPPED and the all-points deletion rule applies.")
    if mat.lcdm:
        state.warn(
            f"{kw} {mat.mid}: LCDM={mat.lcdm} (nonlinear damage curve) is "
            "DROPPED. LS-DYNA's LCDM is damage omega as a function of "
            "EFFECTIVE PLASTIC STRAIN, while /FAIL/TAB1's only curve of that "
            "shape (fct_IDd) is a function of the CURRENT DAMAGE D returning a "
            "damage-RATE multiplier — a different independent variable, so a "
            "direct transfer would silently change the softening law. The "
            "material keeps the LINEAR EPPF→EPPFR ramp instead (which is what "
            "LS-DYNA itself uses when LCDM is absent). Use "
            "*MAT_ADD_DAMAGE_GISSMO (→ /FAIL/TAB2) for a tabulated damage "
            "evolution.")
        if mat.eppf > 0.0 and mat.eppfr > 0.0:
            state.warn(
                f"{kw} {mat.mid}: LCDM, EPPF and EPPFR are all non-zero, so "
                "LS-DYNA IGNORES EPPFR (Vol II R17 p.2-604) and uses the LCDM "
                "curve. With LCDM dropped, the converted deck uses BOTH "
                "strains as the linear ramp — the softening between EPPF and "
                f"EPPFR={mat.eppfr:g} will not match the LS-DYNA run.")
    f_rupt = state.next_curve_id()
    _add_auto_curve(state, f_rupt, f"Auto_MAT081_rupture_mid{mat.mid}",
                    [(-1.0, eppfr), (1.0, eppfr)])
    f_inst = state.next_curve_id()
    _add_auto_curve(state, f_inst, f"Auto_MAT081_instability_mid{mat.mid}",
                    [(-1.0, eppf), (1.0, eppf)])
    state.warn(
        f"{kw} {mat.mid}: EPPF={mat.eppf:g} / EPPFR={mat.eppfr:g} → "
        f"/FAIL/TAB1/{mat.mid} with a flat instability table /FUNCT/{f_inst} "
        f"(softening onset {eppf:g}) and a flat failure table /FUNCT/{f_rupt} "
        f"(rupture {eppfr:g}) over triaxiality -1..+1, plus FAD_EXP=1 so the "
        "reader turns the damage flag on and the stress fades linearly as "
        "(1-omega) between the two strains, exactly as in LS-DYNA. That "
        "softening is reproduced on SHELLS only — /FAIL/TAB1's solid kernel "
        "(fail_tab_s.F) has no stress-degradation path at all, so a solid "
        f"element carries full yield stress until it is deleted at {eppfr:g}. "
        f"A blank strain is written as {_MAT081_NO_FAIL:g} so that leg never "
        "engages, matching LS-DYNA's 1e12/1e14 defaults.")
    sp20, sp10, sp30 = " " * 20, " " * 10, " " * 30
    return [
        f"/FAIL/TAB1/{mat.mid}",
        "# IFAIL_SH  IFAIL_SO                             P_THICKFAIL          P_thinfail               Ixfem",
        f"{_i(2)}{_i(1)}{sp20}{_f(pthick)}{_f(0.0)}{sp10}{_i(0)}",
        "#              Dcrit                   D                   N                Dadv   fct_IDD",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
        "#TABLE1_ID             Xscale1             Xscale2 TABLE2_ID             Xscale3             Xscale4",
        f"{_i(f_rupt)}{_f(0.0)}{_f(0.0)}{_i(f_inst)}{_f(0.0)}{_f(0.0)}",
        "# fct_IDEL           Fscale_EL              EI_REF          INST_START             FAD_EXP    CH_I_F",
        f"{_i(0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(1.0)}{_i(0)}",
        "#  fct_IDT             FscaleT                              Shear_limit             Biax_limit",
        f"{_i(0)}{_f(0.0)}{sp30}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_fail_lemaitre(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    """*MAT_DAMAGE_2 (105) card 3 → /FAIL/LEMAITRE — an exact triple.

    Layout from hm_cfg_files FAIL/fail_lemaitre.cfg FORMAT(radioss2026), ONE
    card: EPS_D(20) S_D(20) DC(20) blank(10) FAILIP(10) P_THICKFAIL(20).

    /FAIL/LEMAITRE exists ONLY in the radioss2026 config directory, so a
    /BEGIN 2022 deck reads it with a cosmetic ``WARNING ID : 100211 —
    Unsupported option /FAIL/LEMAITRE in format < 2026``. That is the
    "keyword only in a newer dir" case: the reader still parses the newer
    FORMAT block in full and correctly (verified on a live starter run with
    distinct values planted in every column, 0 ERROR(S)). Contrast
    /FAIL/JOHNSON, which exists in older dirs too and therefore SILENTLY
    truncates 2024+ columns — that trap does not apply here.

    The MAT_105 FAIL → /FAIL/JOHNSON is written by the base LAW36 emitter, so
    the two failure models coexist exactly as in LS-DYNA (a plastic-strain
    cut-off plus the continuum-damage softening)."""
    if mat.tdel:
        state.warn(
            f"*MAT_105 {mat.mid}: TDEL={mat.tdel:g} (minimum timestep element "
            "deletion) has no /MAT/LAW36 slot and is DROPPED. Add "
            "*MAT_ADD_EROSION with DTMIN on this material to keep it.")
    if mat.epsd <= 0.0:
        if mat.damage_s or mat.dc:
            state.warn(
                f"*MAT_105 {mat.mid}: EPSD={mat.epsd:g} (<=0) switches the "
                f"Lemaitre damage off, so S={mat.damage_s:g} and "
                f"DC={mat.dc:g} are DROPPED with it — the material converts as "
                "a plain /MAT/LAW36 elasto-plastic law. Set EPSD (the damage "
                "threshold plastic strain) to keep the continuum damage.")
        return []
    dc = mat.dc
    if dc <= 0.0:
        # LS-DYNA's blank DC default is 0.5; a blank cell reads 0.0 here and
        # the Radioss reader would clamp 0 → 1.0 (no softening before total
        # rupture), which is a materially different law.
        dc = 0.5
        state.warn(
            f"*MAT_105 {mat.mid}: DC is blank, so LS-DYNA's documented default "
            "0.5 (critical damage) is written to /FAIL/LEMAITRE DC — the "
            "reader's own blank default is 1.0, which would delay deletion "
            "until the damage variable reached full rupture.")
    if mat.damage_s <= 0.0:
        state.warn(
            f"*MAT_105 {mat.mid}: S (the Lemaitre damage constant) is blank or "
            "0. LS-DYNA defaults it to sigma_0/200; /FAIL/LEMAITRE reads S_D=0 "
            "as INFINITY, i.e. NO damage growth at all, so the card is written "
            "with S_D=0 and the damage never accumulates. State S explicitly.")
    state.warn(
        f"*MAT_105 {mat.mid}: the Lemaitre continuum-damage triple "
        f"(EPSD={mat.epsd:g}, S={mat.damage_s:g}, DC={dc:g}) → "
        f"/FAIL/LEMAITRE/{mat.mid}. The starter emits a cosmetic WARNING "
        "100211 (the card is only defined from format 2026) but reads every "
        "field correctly under /BEGIN 2022.")
    return [
        f"/FAIL/LEMAITRE/{mat.mid}",
        "#              EPS_D                 S_D                  DC              FAILIP         P_THICKFAIL",
        f"{_f(mat.epsd)}{_f(mat.damage_s)}{_f(dc)}{' ' * 10}{_i(0)}{_f(0.0)}",
        HDR,
    ]


def _emit_mat_law44(mat: MatPlasKin, state: ConversionState) -> List[str]:
    # LS-DYNA ETAN is the tangent modulus of the bilinear TOTAL stress-strain
    # curve; LAW44's b (with n=1) is dSigma/dEps_PLASTIC, so carry the plastic
    # hardening modulus H = E*ETAN/(E-ETAN) through, not raw ETAN.
    b = (mat.E * mat.etan / (mat.E - mat.etan)
         if 0.0 < mat.etan < mat.E else mat.etan)
    # LS-DYNA BETA runs 0=kinematic..1=isotropic; Radioss Chard runs the
    # OPPOSITE way (0=isotropic..1=kinematic Prager-Ziegler): Chard = 1-BETA.
    chard = min(max(1.0 - mat.beta, 0.0), 1.0)
    epmax = mat.fs if 0.0 < mat.fs < 1e19 else 0.0
    lines = [
        f"/MAT/LAW44/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu",
        f"{_f(mat.E)}{_f(mat.nu)}",
        "#                  a                   b                   n               Chard              SIGmax0",
        f"{_f(mat.sigy)}{_f(b)}{_f(1.0)}{_f(chard)}{_f(0.0)}",
        "#                  c                   p       ICC   ISMOOTH               F_CUT                  VP",
        f"{_f(mat.src)}{_f(mat.srp)}         0         0{_f(0.0)}          {_i(mat.vp)}",
        "#              EpsMax                 Et1                 Et2",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]
    if epmax > 0.0:
        lines += _emit_fail_johnson_all_layers(mat.mid, epmax, state)
    return lines


def _emit_mat_law128(mat: MatAnisoViscoplastic, state: ConversionState) -> List[str]:
    """*MAT_ANISOTROPIC_VISCOPLASTIC (MAT_103) → /MAT/LAW128 (HILL_VISC_PLAST).

    Column layout from MAT/Law128_hill_visc_plast.cfg FORMAT(radioss2026).
    LAW128 mirrors MAT_103 almost 1:1, so E/nu/SIGY and the Voce (QR/CR) and
    kinematic (QX/CX) parameters carry over verbatim. Three fields need mapping:

      * CHARD (iso/kin split, 0=iso .. 1=kin): from the FLAG=1 fit split
        (CHARD = 1 − ALPHA) or, when explicit kinematic terms are given, the
        kinematic fraction QX/(QR+QX). LAW128 applies CHARD to the *combined*
        hardening, so it reproduces MAT_103's iso/kin magnitudes but blends the
        per-term saturation rates — verify the cyclic response.
      * The viscous overstress σ_v = VK·ε̇^VM (additive in MAT_103) is
        approximated by LAW128's *multiplicative* Cowper-Symonds factor
        1 + (ε̇/EPSP0)^(1/CP) matched at the initial yield: CP = 1/VM,
        EPSP0 = (SIGY/VK)^(1/VM). A tabulated LCSS carries the rate dependence
        directly (tab_ID) and then VK/VM are ignored.
      * The Hill surface: MAT_103 gives shell Lankford R00/R45/R90 OR brick
        F/G/H/L/M/N in the same card-3 slots. In Lankford mode LAW128 computes
        F/G/H/N from R00/R45/R90 but leaves L, M untouched, so the writer
        supplies the von Mises L=M=N=1.5 to keep transverse shear non-degenerate
        on solids. In brick mode (L/M/N given) R00=R45=R90=0 tells LAW128 to use
        F/G/H/L/M/N directly.

    LAW128 is orthotropic-only; the companion /PROP/TYPE9|TYPE6 is emitted by
    writer.mesh (see _assign_ortho_props).
    """
    # iso/kin split → CHARD
    if mat.flag == 1 and mat.lcss > 0:
        chard = min(max(1.0 - mat.alpha, 0.0), 1.0)
    elif abs(mat.qx1) + abs(mat.qx2) > 0.0:
        kin = abs(mat.qx1) + abs(mat.qx2)
        iso = abs(mat.qr1) + abs(mat.qr2)
        chard = min(max(kin / (iso + kin), 0.0), 1.0) if (iso + kin) > 0.0 else 0.0
        state.warn(
            f"*MAT_ANISOTROPIC_VISCOPLASTIC {mat.mid} → /MAT/LAW128: kinematic "
            f"hardening present (QX1={mat.qx1:g}, QX2={mat.qx2:g}); the iso/kin "
            f"split CHARD was set to {chard:.3g} (kinematic fraction of the total "
            "hardening). LAW128 applies CHARD to the combined QR+QX hardening, so "
            "the iso/kin magnitudes match MAT_103 but the per-term saturation "
            "rates are blended — check the cyclic/Bauschinger response.")
    else:
        chard = 0.0

    # viscous overstress VK·ε̇^VM → Cowper-Symonds EPSP0/CP (unless a rate table
    # LCSS is given, which LAW128 uses directly)
    tab_id = mat.lcss if (mat.flag in (1, 2) and mat.lcss > 0) else 0
    epsp0, cp = 0.0, 0.0
    if tab_id == 0 and mat.vk > 0.0 and mat.vm > 0.0 and mat.sigy > 0.0:
        cp = 1.0 / mat.vm
        epsp0 = (mat.sigy / mat.vk) ** (1.0 / mat.vm)
        state.warn(
            f"*MAT_ANISOTROPIC_VISCOPLASTIC {mat.mid} → /MAT/LAW128: MAT_103's "
            f"additive viscous overstress VK·ε̇^VM (VK={mat.vk:g}, VM={mat.vm:g}) "
            f"was matched at the initial yield by LAW128's Cowper-Symonds factor "
            f"CP={cp:.4g}, EPSP0={epsp0:.4g}. The forms differ (additive vs "
            "multiplicative), so the overstress diverges from MAT_103 at large "
            "plastic strain — verify, or supply LCSS as a strain-rate table.")
    elif tab_id == 0 and mat.vk != 0.0:
        state.warn(
            f"*MAT_ANISOTROPIC_VISCOPLASTIC {mat.mid} → /MAT/LAW128: the viscous "
            f"overstress (VK={mat.vk:g}, VM={mat.vm:g}) could not be mapped to a "
            "Cowper-Symonds factor (needs VK>0, VM>0, SIGY>0) — rate dependence "
            "DROPPED. Provide a strain-rate LCSS table instead.")

    # Hill surface: shell Lankford vs brick F/G/H/L/M/N
    brick_mode = any(v != 0.0 for v in (mat.hl, mat.hm, mat.hn))
    if brick_mode:
        r00 = r45 = r90 = 0.0                      # 0 → LAW128 uses F/G/H/L/M/N
        ff, gg, hh = mat.r00, mat.r45, mat.r90
        ll = mat.hl or 1.5
        mm = mat.hm or 1.5
        nn = mat.hn or 1.5
    else:
        r00 = mat.r00 or 1.0
        r45 = mat.r45 or 1.0
        r90 = mat.r90 or 1.0
        ff = gg = hh = 0.0                          # computed from Lankford
        ll = mm = nn = 1.5                          # von Mises transverse shear

    gap = " " * 10
    lines = [
        f"/MAT/LAW128/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              Rho_i",
        f"{_f(mat.rho)}",
        "#                  E                  NU                SIGY               CHARD",
        f"{_f(mat.E)}{_f(mat.nu)}{_f(mat.sigy)}{_f(chard)}",
        "#   tab_ID                        Fscale              Xscale",
        f"{_i(tab_id)}{gap}{_f(1.0)}{_f(1.0)}",
        "#                QR1                 CR1                 QR2                 CR2",
        f"{_f(mat.qr1)}{_f(mat.cr1)}{_f(mat.qr2)}{_f(mat.cr2)}",
        "#                QX1                 CX1                 QX2                 CX2",
        f"{_f(mat.qx1)}{_f(mat.cx1)}{_f(mat.qx2)}{_f(mat.cx2)}",
        "#             EPSP0                  CP",
        f"{_f(epsp0)}{_f(cp)}",
        "#                R00                 R45                 R90",
        f"{_f(r00)}{_f(r45)}{_f(r90)}",
        "#                  F                   G                   H",
        f"{_f(ff)}{_f(gg)}{_f(hh)}",
        "#                  L                   M                   N",
        f"{_f(ll)}{_f(mm)}{_f(nn)}",
        HDR,
    ]
    fail = mat.fail if 0.0 < mat.fail < 1e19 else 0.0
    if fail > 0.0:
        lines += _emit_fail_johnson_all_layers(mat.mid, fail, state)
        if mat.numint > 0.0:
            state.warn(
                f"*MAT_ANISOTROPIC_VISCOPLASTIC {mat.mid}: NUMINT={mat.numint:g} "
                "(failed integration points before element deletion) is "
                "approximated by /FAIL/JOHNSON Ifail_sh=2 (delete when ALL "
                "through-thickness points fail); the exact IP-count threshold is "
                "not reproduced.")
    return lines


def _emit_mat_law36_powerlaw(mat: MatPowerLaw, state: ConversionState) -> List[str]:
    fail = mat.epsf if 0.0 < mat.epsf < 1e19 else 0.0
    trailer = _emit_fail_johnson_all_layers(mat.mid, fail, state) if fail > 0.0 else []
    return [
        f"/MAT/LAW36/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu          Eps_p_max",
        f"{_f(mat.E)}{_f(mat.nu)}                   0",
        "# N_funct   F_smooth",
        "         1         0",
        "# fct_IDp      Fscale",
        "         0                 1.0",
        "# fct_ID1",
        f"{_i(mat.funct_id)}",
        "# Fscale1",
        "                 1.0",
        "#          Eps_dot_1",
        "                   0",
        HDR,
    ] + trailer


def _emit_mat_law76(mat: MatSAMP, state: ConversionState) -> List[str]:
    """*MAT_187 / *MAT_SAMP-1 → /MAT/LAW76 (SAMP-1). Field order and column
    layout follow MAT/matl76_76.cfg FORMAT(radioss2018). The tension / compression
    / shear yield curves are emitted separately as /TABLE/1 cards (see
    _make_functions); here we only reference their ids. LS-DYNA has no per-table
    ordinate scale, no XFAC and no IFORM/IQUAD in this card, so those take
    sensible LAW76 defaults (Fscale=XFAC=1, IFORM=0)."""
    xfac = 1.0
    fsmooth = 1                       # ISRATE: strain-rate smoothing on
    fcut = mat.asrate if mat.asrate > 0.0 else 1e30
    fscale1 = 1.0 if mat.fct_id1 else 0.0
    # IQUAD=1 (yield surface quadratic in von Mises) is Altair's recommended
    # setting and is what represents SAMP-1's asymmetric, pressure-dependent
    # yield (the whole reason for separate tension/compression/shear curves);
    # IQUAD=0 is only a coarse linear approximation. LS-DYNA *MAT_187 has no
    # IQUAD field to map from, so we pick the recommended value.
    iquad = 1
    # LAW76 looks the Nu_p function up at the UNSIGNED plastic strain, so the
    # compression half of a signed LS-DYNA LCID-P curve is never evaluated.
    pr_curve = state.curves.get(mat.fct_idpr) if mat.fct_idpr else None
    if pr_curve is not None and any(x < 0.0 for x, _ in pr_curve.pts):
        state.warn(f"/MAT/LAW76/{mat.mid}: fct_IDpr curve {mat.fct_idpr} has "
                   "negative-abscissa (compression) points — LAW76 evaluates "
                   "Nu_p at |plastic strain|, so compressive flow uses the "
                   "tension branch of the curve.")
    gap = " " * 20
    return [
        f"/MAT/LAW76/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu",
        f"{_f(mat.E)}{_f(mat.nu)}",
        "#  TAB_IDt   TAB_IDc   TAB_IDs",
        f"{_i(mat.tab_idt)}{_i(mat.tab_idc)}{_i(mat.tab_ids)}",
        "#            Fscalet             Fscalec             Fscales                                    XFAC",
        f"{_f(1.0)}{_f(1.0)}{_f(1.0)}{gap}{_f(xfac)}",
        "#               Nu_p  fct_IDpr           Fscale_pr   Fsmooth                Fcut",
        f"{_f(mat.nu_p)}{_i(mat.fct_idpr)}{_f(0.0)}{_i(fsmooth)}{_f(fcut)}",
        "#        Epsilon_f_p         Epsilon_r_p",
        f"{_f(mat.epfail)}{_f(mat.eps_rupt)}",
        "#  fct_ID1                                 Fscale1",
        f"{_i(mat.fct_id1)}{gap}{_f(fscale1)}",
        "#    IFORM     IQUAD     ICONV",
        f"{_i(0)}{_i(iquad)}{_i(mat.iconv)}",
        HDR,
    ]


def _emit_mat_law50(mat: MatCrushableFoam, state: ConversionState) -> List[str]:
    """*MAT_CRUSHABLE_FOAM (MAT_063) → /MAT/LAW50 (VISC_HONEY). Column layout
    from mat_law50.cfg FORMAT(radioss90) (the block a /BEGIN 2022 deck reads):
    RHO_I; E11 E22 E33; G12 G23 G31; asrate; then per-direction blocks
    [Iflag/Eps_max card] + funID(5) + Fscale(5) + Eps_rate(5) for 11/22/33, an
    Iflag2 card, then the same for 12/23/31. The single LS-DYNA yield curve LCID
    (yield stress vs volumetric strain) drives all six direction yield functions
    → the material stays isotropic. LAW50 has no tensile-cutoff or rate-damping
    field, so TSC and DAMP are dropped."""
    fid = mat.lcid
    # Isotropic shear modulus from the given E and Poisson ratio.
    G = mat.E / (2.0 * (1.0 + mat.nu)) if mat.nu > -1.0 else mat.E / 2.0
    state.warn(
        f"*MAT_CRUSHABLE_FOAM {mat.mid} → /MAT/LAW50: the single yield curve "
        f"(LCID={fid}) is applied to all six direction yield functions "
        "(σ11/σ22/σ33/σ12/σ23/σ31) — the crushable foam is modelled as isotropic, "
        f"with the shear modulus taken as G=E/2(1+ν)={G:g}.")
    if not fid:
        state.warn(f"*MAT_CRUSHABLE_FOAM {mat.mid}: no yield curve (LCID=0) — "
                   "/MAT/LAW50 has no yield function; add one or the foam has no "
                   "crush resistance.")
    if mat.tsc != 0.0:
        state.warn(f"*MAT_CRUSHABLE_FOAM {mat.mid}: tensile stress cutoff "
                   f"TSC={mat.tsc:g} has no /MAT/LAW50 field — dropped.")
    if mat.damp != 0.0:
        state.warn(f"*MAT_CRUSHABLE_FOAM {mat.mid}: rate-damping coefficient "
                   f"DAMP={mat.damp:g} has no /MAT/LAW50 field — dropped.")

    def _dir(label: str, f: int) -> List[str]:
        return [
            f"#funID{label}-1 funID{label}-2 funID{label}-3 funID{label}-4 funID{label}-5",
            f"{_i(f)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}",
            f"#        Fscale_{label}-1         Fscale_{label}-2         Fscale_{label}-3         Fscale_{label}-4         Fscale_{label}-5",
            f"{_f(1.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            f"#      Eps_rate_{label}-1       Eps_rate_{label}-2       Eps_rate_{label}-3       Eps_rate_{label}-4       Eps_rate_{label}-5",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        ]

    lines = [
        f"/MAT/LAW50/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                E11                 E22                 E33",
        f"{_f(mat.E)}{_f(mat.E)}{_f(mat.E)}",
        "#                G12                 G23                 G31",
        f"{_f(G)}{_f(G)}{_f(G)}",
        "#             asrate",
        f"{_f(0.0)}",
        "#   Iflag1           Eps_max11           Eps_max22           Eps_max33",
        f"{_i(0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
    ]
    lines += _dir("11", fid) + _dir("22", fid) + _dir("33", fid)
    lines += [
        "#   Iflag2           Eps_max12           Eps_max23           Eps_max31",
        f"{_i(0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
    ]
    lines += _dir("12", fid) + _dir("23", fid) + _dir("31", fid)
    lines.append(HDR)
    return lines


def _emit_mat_law38(mat: MatLowDensityFoam, state: ConversionState) -> List[str]:
    """*MAT_LOW_DENSITY_FOAM (MAT_057) → /MAT/LAW38 (VISC_TAB). Column layout
    from matl38_visc_tab.cfg FORMAT(radioss2019). E → E0; the LS-DYNA loading
    curve LCID becomes LAW38's single loading function (N_funct=1, strain rate 0);
    TC → CUToff (tension cutoff stress). LAW38 has no direct hysteretic-unloading
    factor, unloading decay or shape factor, so HU / BETA / SHAPE / DAMP are
    approximate / dropped."""
    fid = mat.lcid
    if not fid:
        state.warn(f"*MAT_LOW_DENSITY_FOAM {mat.mid}: no loading curve (LCID=0) — "
                   "/MAT/LAW38 needs a stress-strain loading function.")
    if mat.hu != 0.0:
        state.warn(f"*MAT_LOW_DENSITY_FOAM {mat.mid}: hysteretic-unloading factor "
                   f"HU={mat.hu:g} is only approximated by /MAT/LAW38 — LAW38 has "
                   "no single hysteretic-unloading factor; the unloading follows "
                   "the loading curve. Verify the energy dissipated on unloading.")
    if mat.shape != 0.0:
        state.warn(f"*MAT_LOW_DENSITY_FOAM {mat.mid}: unloading SHAPE={mat.shape:g} "
                   "has no /MAT/LAW38 field — dropped (unloading shape approximate).")
    if mat.beta != 0.0:
        state.warn(f"*MAT_LOW_DENSITY_FOAM {mat.mid}: unloading decay BETA="
                   f"{mat.beta:g} has no /MAT/LAW38 field — dropped.")
    if mat.damp != 0.0:
        state.warn(f"*MAT_LOW_DENSITY_FOAM {mat.mid}: viscous DAMP={mat.damp:g} "
                   "has no /MAT/LAW38 field — dropped.")
    sp10 = " " * 10
    return [
        f"/MAT/LAW38/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#        Init. dens.",
        f"{_f(mat.rho)}",
        "#                 E0                nu_t                nu_c                 R_V     Iflag     Itota",
        f"{_f(mat.E)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}{_i(0)}",
        "#               beta                   H                 R_D       K_R       K_D               Theta",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}{_i(0)}{_f(0.0)}",
        "#    K_air       N_P            Fscale_P",
        f"{_i(0)}{_i(0)}{_f(0.0)}",
        "#                 P0                 R_P               P_max                 Phi",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#      ful                  alpha_unload        Eps_._unload                   a                   b",
        f"{_i(0)}{sp10}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#  N_funct                        CUToff   I_insta",
        f"{_i(1)}{sp10}{_f(mat.tc)}{_i(0)}",
        "#            E-final          Epsi-final              Lambda                VISC                 Tol",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "# Scale factors",
        f"{_f(1.0)}",
        "# Strain rates",
        f"{_f(0.0)}",
        "# Loading functions",
        f"{_i(fid)}",
        "# Unloading functions",
        f"{_i(0)}",
        HDR,
    ]


def _emit_mat_law70(mat: MatFuChangFoam, state: ConversionState) -> List[str]:
    """*MAT_FU_CHANG_FOAM (MAT_083) → /MAT/LAW70 (FOAM_TAB). APPROXIMATE. Column
    layout from matl70_foam_tab.cfg FORMAT(radioss2019): RHO_I; EO NU E_max
    EPS_max Itens; F_cut Ismooth Nload Nunload Iflag Shape Hys; then one
    (funcID, Eps_load, Fscale) card per loading curve. The LS-DYNA TBID load-curve
    family maps onto LAW70's per-strain-rate loading functions; HU → Hys, SHAPE →
    Shape. Fu-Chang's analytic hysteresis/damping constants have no LAW70
    counterpart."""
    fid = mat.tbid
    state.warn(
        f"*MAT_FU_CHANG_FOAM {mat.mid} → /MAT/LAW70 is APPROXIMATE: Fu-Chang's "
        "analytic constitutive constants (D0…C5) and rate-damping have no "
        "/MAT/LAW70 equivalent — only the tabulated stress-strain response is "
        "carried over.")
    state.warn(
        f"*MAT_FU_CHANG_FOAM {mat.mid}: TBID={fid} is referenced as the single "
        "/MAT/LAW70 loading function (strain rate 0). If TBID is a *DEFINE_TABLE "
        "of curves at several strain rates, split it into one /FUNCT per rate and "
        "list them as LAW70 loading functions (funcID/Eps_._load) to recover the "
        "rate dependence.")
    if mat.tc != 0.0:
        state.warn(f"*MAT_FU_CHANG_FOAM {mat.mid}: tension cutoff TC={mat.tc:g} "
                   "has no scalar /MAT/LAW70 field (LAW70 tension is a function) — "
                   "dropped.")
    if mat.damp != 0.0:
        state.warn(f"*MAT_FU_CHANG_FOAM {mat.mid}: rate-damping DAMP={mat.damp:g} "
                   "has no /MAT/LAW70 field — dropped.")
    # Ismooth=0, Nload=1, Nunload=0, Iflag=0. Shape/Hys carry the unloading model.
    return [
        f"/MAT/LAW70/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                 EO                  NU               E_max             EPS_max     Itens",
        f"{_f(mat.E)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
        "#              F_cut   Ismooth     Nload   Nunload     Iflag               Shape                 Hys",
        f"{_f(0.0)}{_i(0)}{_i(1)}{_i(0)}{_i(0)}{_f(mat.shape)}{_f(mat.hu)}",
        "#funcID_id          Eps_._load          Fscale_load",
        f"{_i(fid)}{_f(0.0)}{_f(1.0)}",
        HDR,
    ]


def _emit_mat_law28(mat: MatHoneycomb, state: ConversionState) -> List[str]:
    """*MAT_HONEYCOMB (MAT_026) → /MAT/LAW28 (HONEYCOMB). Column layout from
    matl28_honeycomb.cfg FORMAT(radioss90): RHO_I; E_11 E_22 E_33; G_12 G_23 G_31;
    [fun_ID11 fun_ID22 fun_ID33 Iflag1 Fscale11 Fscale22 Fscale33]; Eps_max11-33;
    [fun_ID12 fun_ID23 fun_ID31 Iflag2 Fscale12 Fscale23 Fscale31]; Eps_max12-31.
    Uncompressed moduli EAAU/EBBU/ECCU → E_11/E_22/E_33 and GABU/GBCU/GCAU →
    G_12/G_23/G_31 (a/b/c ↔ 11/22/33). Normal crush curves LCA/LCB/LCC →
    fun_ID11/22/33, shear LCAB/LCBC/LCCA → fun_ID12/23/31 (LCS as the fallback for
    any missing shear component). LAW28 has no compacted-modulus / SIGY / VF / MU /
    BULK / strain-rate slot, so those LS-DYNA fields are dropped."""
    lcab = mat.lcab or mat.lcs
    lcbc = mat.lcbc or mat.lcs
    lcca = mat.lcca or mat.lcs
    dropped = []
    if mat.E:
        dropped.append(f"E={mat.E:g} (fully-compacted modulus)")
    if mat.sigy:
        dropped.append(f"SIGY={mat.sigy:g}")
    if mat.vf:
        dropped.append(f"VF={mat.vf:g}")
    if mat.mu:
        dropped.append(f"MU={mat.mu:g}")
    if mat.bulk:
        dropped.append(f"BULK={mat.bulk:g}")
    if dropped:
        state.warn(f"*MAT_HONEYCOMB {mat.mid} → /MAT/LAW28: "
                   f"{', '.join(dropped)} have no /MAT/LAW28 field and are dropped "
                   "(LAW28 reaches full compaction from the crush curves).")
    if mat.lcsr:
        state.warn(f"*MAT_HONEYCOMB {mat.mid}: strain-rate scaling curve "
                   f"LCSR={mat.lcsr} has no /MAT/LAW28 field — dropped (LAW28 is "
                   "rate independent).")
    if mat.lcs and (not mat.lcab or not mat.lcbc or not mat.lcca):
        state.warn(f"*MAT_HONEYCOMB {mat.mid}: transverse-shear curve LCS="
                   f"{mat.lcs} used for the shear direction(s) with no dedicated "
                   "LCAB/LCBC/LCCA curve.")
    return [
        f"/MAT/LAW28/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#               E_11                E_22                E_33",
        f"{_f(mat.eaau)}{_f(mat.ebbu)}{_f(mat.eccu)}",
        "#               G_12                G_23                G_31",
        f"{_f(mat.gabu)}{_f(mat.gbcu)}{_f(mat.gcau)}",
        "# fun_ID11  fun_ID22  fun_ID33    Iflag1            Fscale11            Fscale22            Fscale33",
        f"{_i(mat.lca)}{_i(mat.lcb)}{_i(mat.lcc)}{_i(0)}{_f(1.0)}{_f(1.0)}{_f(1.0)}",
        "#          Eps_max11           Eps_max22           Eps_max33",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "# fun_ID12  fun_ID23  fun_ID31    Iflag2            Fscale12            Fscale23            Fscale31",
        f"{_i(lcab)}{_i(lcbc)}{_i(lcca)}{_i(0)}{_f(1.0)}{_f(1.0)}{_f(1.0)}",
        "#          Eps_max12           Eps_max23           Eps_max31",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Metal plasticity batch 2: MAT_012 / MAT_019 / MAT_120 / MAT_124
# (MAT_081/082 and MAT_105 ride the LAW36 path above; MAT_122 lives in
#  writer/composites.py with the other orthotropic laws.)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_mat_iso_elas_plas(state: ConversionState) -> None:
    """*MAT_ISOTROPIC_ELASTIC_PLASTIC (012): derive E and nu from the card's
    SHEAR and BULK moduli, which is the only place they exist.

        E  = 9*K*G / (3*K + G)
        nu = (3*K - 2*G) / (2*(3*K + G))

    dyna2rad evaluates the same two expressions through exprtk with NO
    zero guard (convertutilsbase.cxx:140-276), so a card that omits G or BULK
    writes ``nan`` into the /MAT and the starter reads garbage. Both
    degenerate cases are caught and reported here instead.
    """
    for mat in state.mat_iso_elas_plas.values():
        denom = 3.0 * mat.bulk + mat.g
        if denom <= 0.0:
            state.warn(
                f"*MAT_012 {mat.mid}: G={mat.g:g} and BULK={mat.bulk:g} give "
                f"3K+G = {denom:g} (<=0), so E = 9KG/(3K+G) and "
                "nu = (3K-2G)/(2(3K+G)) cannot be evaluated — the material is "
                "written with E=0/nu=0 and the starter will reject it. Supply "
                "both moduli. (dyna2rad divides anyway and writes NaN.)")
            mat.E, mat.nu = 0.0, 0.0
            continue
        mat.E = 9.0 * mat.bulk * mat.g / denom
        mat.nu = (3.0 * mat.bulk - 2.0 * mat.g) / (2.0 * denom)
        if not (0.0 <= mat.nu < 0.5):
            state.warn(
                f"*MAT_012 {mat.mid}: G={mat.g:g} and BULK={mat.bulk:g} imply "
                f"nu = {mat.nu:g}, outside the physical 0 <= nu < 0.5 range "
                "the /MAT/LAW2 reader accepts. Check the two moduli — they are "
                "the SHEAR and BULK modulus on this card, not E and nu.")


def _emit_mat_law2_iso_elas_plas(mat: MatIsoElasPlas,
                                 state: ConversionState) -> List[str]:
    """*MAT_ISOTROPIC_ELASTIC_PLASTIC (012) → /MAT/LAW2 (PLAS_JOHNS).

    ``a = SIGY``, ``b = ETAN``, ``n = 1``: LS-DYNA documents MAT_012's ETAN as
    the "Plastic hardening modulus" (Vol II R17 p.2-206), which is exactly what
    LAW2's ``b`` with ``n = 1`` is (sigma = a + b*eps_p). This is the same
    distinction the MAT_037 path documents: *MAT_003's identically-named ETAN
    is the TOTAL-curve tangent modulus and needs the E*ET/(E-ET) rescale that
    /MAT/LAW44 applies — MAT_012's does not.

    Everything else on the card stays 0 → starter defaults: no strain-rate
    term, no thermal softening, no failure and no element deletion, which is
    the whole of MAT_012 (dyna2rad case 12, convertmats.cxx:307-322).
    """
    if mat.etan < 0.0:
        state.warn(
            f"*MAT_012 {mat.mid}: ETAN={mat.etan:g} is negative, which would "
            "make the yield stress fall with plastic strain. /MAT/LAW2 takes "
            "it verbatim as the hardening coefficient b — check the deck.")
    return _law2_plas_johns_lines(mat.mid, mat.title, mat.rho, mat.E, mat.nu,
                                  mat.sigy, mat.etan, 1.0)


def _emit_mat_law121(mat: MatStrainRatePlas,
                     state: ConversionState) -> List[str]:
    """*MAT_STRAIN_RATE_DEPENDENT_PLASTICITY (019) → /MAT/LAW121 (PLAS_RATE).

    Column layout from hm_cfg_files MAT/matl121_plasrate.cfg
    FORMAT(radioss2022), the block a /BEGIN 2022 deck reads with:
      RHO_I(20) /
      E(20) Nu(20) Ires(10) Ivisc(10) Fcut(20) DTMIN(20) /
      Fct_SIG0(10) blank(10) Xscale_SIG0(20) Yscale_SIG0(20) /
      Fct_YOUN(10) blank(10) Xscale_YOUN(20) Yscale_YOUN(20) /
      Fct_TANG(10) blank(10) Xscale_TANG(20) TANG(20) /
      Fct_FAIL(10) Ifail(10) Xscale_FAIL(20) Yscale_FAIL(20)

    Two divergences from dyna2rad (p_ConvertMatL19, convertmats.cxx:1234-1282),
    both of which leave a field at 0 where 0 has a DIFFERENT meaning:

    * card 5's ``TANG`` is the constant tangent modulus only while
      ``Fct_TANG == 0``; with a curve it is that curve's ORDINATE SCALE, so it
      must be 1.0 and not the 0 dyna2rad leaves (which would zero the
      hardening).
    * the ``Xscale_*``/``Yscale_*`` factors are written as an explicit 1.0
      whenever their function slot is used, rather than relying on a blank
      default that the reader documents for SIG0 but not for the others.

    ``Ires`` is left 0 → the reader forces 2 (Newton cutting-plane), and
    ``Fcut`` 0 → 10000*FAC_T_WORK, both the solver's own defaults.
    """
    lc1, lc2, lc3, lc4 = mat.lc1, mat.lc2, mat.lc3, mat.lc4
    ivisc = 1 if mat.vp else 0
    # Fct_SIG0/YOUN/TANG/FAIL are FUNCTION slots: a *DEFINE_TABLE id is not a
    # valid target (it becomes a 2-D /TABLE/1, which the function namespace
    # does not carry), so the guard checks state.curves only — accepting a
    # table id here would silence the one diagnostic that catches a mistyped
    # curve id.
    for name, fid in (("LC1", lc1), ("LC2", lc2), ("LC3", lc3), ("LC4", lc4)):
        if fid and fid not in state.curves:
            state.warn(
                f"*MAT_019 {mat.mid}: {name}={fid} references a *DEFINE_CURVE "
                "that is NOT in the deck — the /MAT/LAW121 function id will "
                "dangle.")
    if not lc1:
        state.warn(
            f"*MAT_019 {mat.mid}: LC1 (yield strength vs strain rate) is "
            "missing, but it is the material's ONLY source of yield stress — "
            "MAT_019 has no SIGY field. /MAT/LAW121 hard-fails with starter "
            "ERROR 2060 when both Fct_SIG0 and Yscale_SIG0 are zero. Add the "
            "curve.")
    if ivisc and lc2:
        state.warn(
            f"*MAT_019 {mat.mid}: VP=1 (viscoplastic) together with LC2 "
            "(Young's modulus vs strain rate) — LS-DYNA allows LC2 only when "
            "VP=0, and the /MAT/LAW121 reader raises WARNING 2061 and FORCES "
            "Ivisc back to 0, so the deck silently converts to the "
            "scaled-yield-stress formulation. Drop LC2 or set VP=0.")
    if mat.tdel:
        state.warn(
            f"*MAT_019 {mat.mid}: TDEL={mat.tdel:g} → /MAT/LAW121 DTMIN "
            "(element deleted when its timestep falls below it). LS-DYNA "
            "restricts this criterion to shells; Radioss applies DTMIN to "
            "every element on the law.")
    if mat.rdef and not lc4:
        state.warn(
            f"*MAT_019 {mat.mid}: RDEF={mat.rdef} redefines the failure "
            "variable but LC4 (the failure curve) is missing, so nothing "
            "fails. Ifail is still written; add LC4 to activate it.")
    b10 = " " * 10
    return [
        f"/MAT/LAW121/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu      Ires     Ivisc                Fcut               DTMIN",
        f"{_f(mat.E)}{_f(mat.nu)}{_i(0)}{_i(ivisc)}{_f(0.0)}{_f(mat.tdel)}",
        "# Fct_SIG0                   Xscale_SIG0         Yscale_SIG0",
        f"{_i(lc1)}{b10}{_f(1.0 if lc1 else 0.0)}{_f(1.0 if lc1 else 0.0)}",
        "# Fct_YOUN                   Xscale_YOUN         Yscale_YOUN",
        f"{_i(lc2)}{b10}{_f(1.0 if lc2 else 0.0)}{_f(1.0 if lc2 else 0.0)}",
        "# Fct_TANG                   Xscale_TANG                TANG",
        f"{_i(lc3)}{b10}{_f(1.0 if lc3 else 0.0)}"
        + f"{_f(1.0 if lc3 else mat.etan)}",
        "# Fct_FAIL     Ifail         Xscale_FAIL         Yscale_FAIL",
        f"{_i(lc4)}{_i(max(0, min(3, mat.rdef)))}{_f(1.0 if lc4 else 0.0)}"
        + f"{_f(1.0 if lc4 else 0.0)}",
        HDR,
    ]


# Plastic-strain grid the analytic MAT_120 ATYP=1 power law is sampled on —
# the same one _resolve_mat_power_law uses for *MAT_018.
_GURSON_EPS_SAMPLES = [0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3,
                       0.5, 1.0]


def _resolve_mat_gurson(state: ConversionState) -> None:
    """*MAT_GURSON (120) prepass: pick the LAW52 hardening input and collapse
    the element-length failure curves to the single scalar LAW52 has.

    Hardening precedence follows the manual's own "this value is only used
    if LCSS = 0" wording on every ATYP-driven field: LCSS wins over ATYP.
    """
    for mat in state.mat_gurson.values():
        mat.ff = mat.ff0
        _gurson_hardening(state, mat)
        _gurson_length_curves(state, mat)
        _gurson_report_dropped(state, mat)
        # ERROR 1745: the starter requires f_I <= f_C <= f_F.
        if not (mat.f0 <= mat.fc <= mat.ff):
            state.warn(
                f"*MAT_GURSON {mat.mid}: the void volume fractions end up "
                f"f0={mat.f0:g}, fc={mat.fc:g}, fF={mat.ff:g}, which violates "
                "f0 <= fc <= fF — the /MAT/LAW52 reader rejects that with "
                "starter ERROR 1745. Check F0/FC/FF0 (and any LCF0/LCFC/LCFF "
                "curve, whose value replaces the scalar).")
        elif mat.ff <= 0.0:
            state.warn(
                f"*MAT_GURSON {mat.mid}: the failure void volume fraction fF "
                "is 0 (no FF0, no (L,FF) points and no LCFF curve), so the "
                "f* coalescence term degenerates and the material never "
                "softens. Set FF0.")


def _gurson_hardening(state: ConversionState, mat) -> None:
    """LAW52 A/B/N/Tab_ID/Iyield from LCSS or ATYP (Vol II R17 p.2-828)."""
    # Neutral analytic form (sigma = A + 0*eps_p^1) up front: the reader's
    # CHECK is 0 <= N <= 1, and a table branch that left N at 0 would be
    # writing a value the analytic form never intends.
    mat.hard_b, mat.hard_n = 0.0, 1.0
    if mat.lcss:
        tab = state.define_tables.get(mat.lcss)
        if tab is not None:
            # Only a table _make_functions will actually write may be named in
            # Tab_ID: it skips any entry that is not `resolved and rows`, and a
            # Tab_ID with no /TABLE behind it is starter ERROR 779. Same guard
            # as the MAT_024 LCSS path.
            if tab.resolved and tab.rows:
                mat.tab_id, mat.iyield = mat.lcss, 1
                state.warn(
                    f"*MAT_GURSON {mat.mid}: LCSS={mat.lcss} is a "
                    "*DEFINE_TABLE — used directly as the /MAT/LAW52 Tab_ID "
                    "(yield stress vs plastic strain per strain rate), and "
                    "ATYP/SIGY/N/ETAN are ignored exactly as LS-DYNA ignores "
                    "them.")
                return
            state.warn(
                f"*MAT_GURSON {mat.mid}: LCSS={mat.lcss} references a "
                "*DEFINE_TABLE that could not be resolved (its rows name "
                "curves the deck does not define), so no /TABLE is written "
                "for it — naming it as the /MAT/LAW52 Tab_ID would dangle "
                "(starter ERROR 779). Falling back to the "
                f"ATYP={mat.atyp} hardening of cards 1/2.")
        elif mat.lcss in state.curves:
            mat.tab_id, mat.iyield = mat.lcss, 1
            # LAW52's Tab_ID slot reads a /TABLE, not a /FUNCT, so the curve is
            # re-emitted as a 1-D /TABLE/1 (same mechanism as the LAW76 yield
            # tables — see state.table_1d_ids).
            state.table_1d_ids.add(mat.lcss)
            return
        else:
            state.warn(
                f"*MAT_GURSON {mat.mid}: LCSS={mat.lcss} references a "
                "*DEFINE_CURVE/_TABLE that is NOT in the deck — falling back "
                f"to the ATYP={mat.atyp} hardening of cards 1/2.")
    if mat.atyp == 2:
        # sigma_Y = SIGY + E*ETAN/(E-ETAN) * eps_p, i.e. LAW52's A + B*eps_p^n
        # with n = 1. The manual states the E*ETAN/(E-ETAN) form explicitly on
        # this card (p.2-828), so ETAN is the TOTAL-curve tangent modulus here.
        b = (mat.E * mat.etan / (mat.E - mat.etan)
             if 0.0 < mat.etan < mat.E else mat.etan)
        mat.hard_b, mat.hard_n = b, 1.0
        return
    if mat.atyp == 3:
        pts = _gurson_curve_points(state, mat)
        if pts:
            fid = state.next_curve_id()
            _add_auto_curve(state, fid, f"Auto_MAT120_hardening_mid{mat.mid}",
                            pts)
            state.table_1d_ids.add(fid)
            mat.tab_id, mat.iyield = fid, 1
            return
        mat.hard_b, mat.hard_n = 0.0, 1.0
        return
    if mat.atyp == 1:
        pts = _gurson_power_law_points(state, mat)
        if pts:
            fid = state.next_curve_id()
            _add_auto_curve(state, fid, f"Auto_MAT120_powerlaw_mid{mat.mid}",
                            pts)
            state.table_1d_ids.add(fid)
            mat.tab_id, mat.iyield = fid, 1
            state.warn(
                f"*MAT_GURSON {mat.mid}: ATYP=1 power-law hardening "
                f"sigma_Y = SIGY*((eps_p + SIGY/E)/(SIGY/E))^(1/N) with "
                f"SIGY={mat.sigy:g}, N={mat.n:g} sampled onto a "
                f"{len(pts)}-point /TABLE/1 {fid} over eps_p 0..1 — "
                "/MAT/LAW52's analytic form is A + B*eps_p^n, which cannot "
                "express it. (dyna2rad converts nothing here: its ATYP=1 "
                "branch is an empty '// no conversion available', leaving "
                "LAW52 with n=0.)")
            return
        mat.hard_b, mat.hard_n = 0.0, 1.0
        return
    # ATYP = 0 (or anything else): ideally plastic, sigma_Y = SIGY.
    mat.hard_b, mat.hard_n = 0.0, 1.0
    if mat.atyp not in (0, 1, 2, 3):
        state.warn(
            f"*MAT_GURSON {mat.mid}: ATYP={mat.atyp} is not one of the four "
            "documented hardening types (0 ideal / 1 power law / 2 linear / "
            "3 8-point curve) — the material converts as IDEALLY PLASTIC "
            f"(sigma_Y = SIGY = {mat.sigy:g}).")


def _gurson_curve_points(state: ConversionState, mat):
    """The ATYP=3 (EPS1..8, ES1..8) hardening points, filtered and ordered.

    dyna2rad copies all eight cells verbatim, so a card that states three
    points writes five (0, 0) rows and the table collapses onto the origin.
    Trailing blank pairs are dropped here, exactly as the MAT_024 EPS/ES path
    does; the manual requires the first point to be (0, initial yield stress),
    which is why an all-zero FIRST pair is not special-cased away."""
    pairs = [(e, s) for e, s in zip(mat.eps_pts, mat.es_pts)
             if e != 0.0 or s != 0.0]
    if len(pairs) < 2:
        state.warn(
            f"*MAT_GURSON {mat.mid}: ATYP=3 (8-point curve) but only "
            f"{len(pairs)} non-blank (EPS, ES) pair(s) are given — the manual "
            "asks for at least 2. The material converts as IDEALLY PLASTIC "
            f"(sigma_Y = SIGY = {mat.sigy:g}).")
        return []
    return sorted(pairs)


def _gurson_power_law_points(state: ConversionState, mat):
    """Sample the ATYP=1 law sigma_Y = SIGY*((eps_p + SIGY/E)/(SIGY/E))^(1/N)."""
    if mat.sigy <= 0.0 or mat.E <= 0.0 or mat.n <= 0.0:
        state.warn(
            f"*MAT_GURSON {mat.mid}: ATYP=1 (power law) needs SIGY>0, E>0 and "
            f"N>0 to evaluate SIGY*((eps_p+SIGY/E)/(SIGY/E))^(1/N), but "
            f"SIGY={mat.sigy:g}, E={mat.E:g}, N={mat.n:g} — the hardening is "
            "DROPPED and the material converts as IDEALLY PLASTIC.")
        return []
    e_y = mat.sigy / mat.E
    return [(eps, mat.sigy * ((eps + e_y) / e_y) ** (1.0 / mat.n))
            for eps in _GURSON_EPS_SAMPLES]


def _gurson_length_curves(state: ConversionState, mat) -> None:
    """Collapse the element-length-dependent porosity inputs onto LAW52's
    scalars. LAW52 has no element-size regularization, so each curve becomes
    one number and the collapse is reported.

    Precedence for fF follows the manual (p.2-828): FF0 "is only used if no
    curve is given by (L1, FF1) - (L4, FF4) and LCFF = 0". Whether LCFF
    applied is tracked with a FLAG, not by comparing the result against FF0 —
    a curve whose collapse happens to land on FF0 must still win over the
    (L, FF) table.

    All four length inputs collapse the same way, to the MEAN of the stated
    values: with the mesh-size regularization gone there is no defensible
    "the model runs at this element size" ordinate to prefer, and the mean is
    the only choice that does not depend on how the curve was ordered."""
    ff_from_curve = False
    if mat.lcff:
        crv = state.curves.get(mat.lcff)
        if crv and crv.pts:
            mean = sum(y for _, y in crv.pts) / len(crv.pts)
            mat.ff = mean
            ff_from_curve = True
            state.warn(
                f"*MAT_GURSON {mat.mid}: LCFF={mat.lcff} gives the failure "
                "void volume fraction fF as a function of ELEMENT LENGTH. "
                "/MAT/LAW52's FF is a single number, so the curve is collapsed "
                f"to the mean of its ordinates, FF={mean:g} — the mesh-size "
                "regularization is LOST (a fine mesh will fail at the same fF "
                "as a coarse one). Same collapse as dyna2rad.")
        else:
            state.warn(
                f"*MAT_GURSON {mat.mid}: LCFF={mat.lcff} references a "
                "*DEFINE_CURVE that is NOT in the deck — falling back to the "
                "(L,FF) points / FF0.")
    if not ff_from_curve and any(f != 0.0 for f in mat.ffs):
        used = [f for f in mat.ffs if f != 0.0]
        mat.ff = sum(used) / len(used)
        state.warn(
            f"*MAT_GURSON {mat.mid}: the (L1..L4, FF1..FF4) element-length "
            "table of card 5 gives fF as a function of element length; "
            "/MAT/LAW52 takes one number, so the "
            f"{len(used)} stated value(s) are averaged to FF={mat.ff:g} and "
            "FF0 is not used (as in LS-DYNA). The mesh-size regularization is "
            "LOST. (dyna2rad divides the sum by 4 unconditionally, which "
            "under-reports whenever fewer than four are given — and it applies "
            "the average even when the table is empty, zeroing FF0.)")
    for lcid, attr, label in ((mat.lcf0, "f0", "initial void volume fraction"),
                              (mat.lcfc, "fc", "critical void volume fraction"),
                              (mat.lcfn, "fn", "nucleating void volume fraction")):
        if not lcid:
            continue
        crv = state.curves.get(lcid)
        if not crv or not crv.pts:
            state.warn(
                f"*MAT_GURSON {mat.mid}: the {label} curve {lcid} is NOT in "
                "the deck — the scalar card value is kept.")
            continue
        val = sum(y for _, y in crv.pts) / len(crv.pts)
        setattr(mat, attr, val)
        state.warn(
            f"*MAT_GURSON {mat.mid}: curve {lcid} gives the {label} as a "
            f"function of ELEMENT LENGTH; /MAT/LAW52 takes one number, so the "
            f"mean of its {len(crv.pts)} ordinate(s), {val:g}, is used (the "
            "same collapse as LCFF) and the mesh-size regularization is LOST. "
            "(dyna2rad reads the LCF0 slot under the wrong attribute name and "
            "never applies it at all.)")


def _gurson_report_dropped(state: ConversionState, mat) -> None:
    """MAT_120 fields with no /MAT/LAW52 counterpart."""
    if mat.en < 0.0 or mat.sn < 0.0:
        neg = [n for n, v in (("EN", mat.en), ("SN", mat.sn)) if v < 0.0]
        for name in neg:
            setattr(mat, name.lower(), 0.0)
        state.warn(
            f"*MAT_GURSON {mat.mid}: {', '.join(neg)} < 0 makes |value| a "
            "load-curve id giving the nucleation parameter as a function of "
            "element length. /MAT/LAW52's EpsN/SN are scalars with no curve "
            f"slot, so {', '.join(neg)} is set to 0"
            + (" — and with SN=0 the nucleation term "
               "A = FN/(SN*sqrt(2pi))*exp(...) is switched off entirely"
               if "SN" in neg else "")
            + ". State the value as a positive constant to keep void "
              "nucleation.")
    if mat.numint:
        state.warn(
            f"*MAT_GURSON {mat.mid}: NUMINT={mat.numint:g} (integration points "
            "that must fail before element deletion) has no slot on "
            "/MAT/LAW52 — the law deletes on its own f_F coalescence "
            "criterion, per integration point. Add *MAT_ADD_EROSION with "
            "NUMFIP to state an IP-count rule (k2rad maps that to the "
            "/FAIL/GENE1 Pthickfail).")
    if mat.vgtyp:
        state.warn(
            f"*MAT_GURSON {mat.mid}: VGTYP={mat.vgtyp:g} (void-growth type: "
            "whether voids contract in compression, and below f0) has no "
            "/MAT/LAW52 counterpart — DROPPED. LAW52's Iflag=1 is written, "
            "which is the von Mises equivalent-stress form; Iflag 2/3 suppress "
            "nucleation in compression but are not the same switch.")
    if mat.dexp:
        state.warn(
            f"*MAT_GURSON {mat.mid}: DEXP={mat.dexp:g} only scales LS-DYNA "
            "history variable 16 (a dimensionless post-processing damage "
            "measure) and has no effect on the constitutive law — DROPPED.")
    if mat.variant == "" and any(mat.lengths):
        state.warn(
            f"*MAT_GURSON {mat.mid}: the element lengths L1..L4 of card 5 are "
            "read only to pair with FF1..FF4; /MAT/LAW52 has no element-size "
            "regularization, so the lengths themselves are DROPPED.")


def _emit_mat_law52(mat: MatGurson, state: ConversionState) -> List[str]:
    """*MAT_GURSON (120) → /MAT/LAW52 (GURSON).

    Column layout from hm_cfg_files MAT/matl52_gurson.cfg FORMAT(radioss130) —
    the newest block a /BEGIN 2022 deck resolves to:
      RHO_I(20) /
      E(20) NU_12(20) Iflag(10) Fsmooth(10) Fcut(20) Iyield(10) /
      A(20) B(20) N(20) c(20) p(20) /
      alpha_1(20) alpha_2(20) alpha_3(20) SN(20) EpsN(20) /
      Fi(20) FN(20) Fc(20) FF(20) /
      [Iyield>0] Tab_ID(10) blank(10) XFAC(20) YFAC(20)

    ``alpha_3`` (Gurson q3) is written as ``q1*q1``, the standard Tvergaard
    closure and dyna2rad's own expression — the LAW52 reader does NOT default
    it to q1^2, it stays 0, which would turn the flow surface into a different
    law. ``Iflag=1`` selects the von Mises equivalent stress.
    """
    b10 = " " * 10
    if mat.q1 == 0.0:
        state.warn(
            f"*MAT_GURSON {mat.mid}: Q1=0, so the Gurson flow function "
            "degenerates (the porosity terms 2*q1*f*cosh(...) and (q1*f)^2 "
            "both vanish) and the material behaves as plain von Mises "
            "plasticity. Q1=1.5, Q2=1.0 are the usual Tvergaard values.")
    lines = [
        f"/MAT/LAW52/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E               NU_12     Iflag   Fsmooth                Fcut    Iyield",
        f"{_f(mat.E)}{_f(mat.nu)}{_i(1)}{_i(0)}{_f(0.0)}{_i(mat.iyield)}",
        "#                  A                   B                   N                   c                   p",
        f"{_f(mat.sigy)}{_f(mat.hard_b)}{_f(mat.hard_n)}{_f(0.0)}{_f(0.0)}",
        "#            alpha_1             alpha_2             alpha_3                  SN                EpsN",
        f"{_f(mat.q1)}{_f(mat.q2)}{_f(mat.q1 * mat.q1)}{_f(mat.sn)}{_f(mat.en)}",
        "#                 Fi                  FN                  Fc                  FF",
        f"{_f(mat.f0)}{_f(mat.fn)}{_f(mat.fc)}{_f(mat.ff)}",
    ]
    if mat.iyield > 0:
        lines += [
            "#   Tab_ID                          XFAC                YFAC",
            f"{_i(mat.tab_id)}{b10}{_f(1.0)}{_f(1.0)}",
        ]
    lines.append(HDR)
    if mat.variant == "JC" and any(mat.jc_d):
        lines += _emit_gurson_jc_fail(mat, state)
    return lines


def _emit_gurson_jc_fail(mat: MatGurson, state: ConversionState) -> List[str]:
    """*MAT_GURSON_JC card-5 D1-D4 → a companion /FAIL/JOHNSON.

    D3 is copied VERBATIM here, unlike on the *MAT_JOHNSON_COOK path where it
    is forced negative. The two keywords do not share a triaxiality
    convention:

    * *MAT_015 writes ``sigma* = p/sigma_eff`` with LS-DYNA's PRESSURE, which
      is compression-positive (Theory manual 23.15.3, and "pressures more
      tensile than this limit" for ``p >= pmin``), so it is the negative of
      Radioss's ratio and has to be flipped.
    * *MAT_120_JC writes ``eps_f = [D1 + D2*exp(D3*sigma_H/sigma_M)](1 +
      D4*ln eps_dot)*Lambda`` with sigma_H the MEAN HYDROSTATIC STRESS (Vol II
      R17 p.2-839/2-840). Across the manual that symbol is tension-positive:
      *MAT_ADD_DAMAGE_GISSMO defines the triaxiality "eta = sigma_H/sigma_M,
      with hydrostatic stress sigma_H" (p.2-76), *MAT_252 spells it out as
      "sigma_m = I1/3 ... as in Johnson and Cook [1985]" (p.2-1694), and
      *MAT_124 remark 1 states "a positive mean stress (meaning a negative
      pressure) is indicative of tension" (p.2-877).

    Radioss's /FAIL/JOHNSON uses ``P = (sigxx+sigyy)/3`` — tension-positive
    (fail_johnson_c.F:113-117) — so sigma_H/sigma_M maps 1:1 and any sign
    change would invert the triaxiality dependence. (``-abs()`` would in any
    case not be a negation: it FORCES the sign, leaving an already-negative
    D3 untouched.)"""
    d1, d2, d3, d4 = (list(mat.jc_d) + [0.0] * 4)[:4]
    if mat.jc_lcjc:
        # p.2-838: "If LCJC > 0, parameters D1, D2 and D3 are ignored" — the
        # curve replaces the whole first term as a function of triaxiality.
        # /FAIL/JOHNSON has only the analytic D1+D2*exp(D3*eta) form and no
        # slot for such a curve, so building one from card-5 leftovers would
        # erode on a criterion the source deck never evaluates.
        state.warn(
            f"*MAT_GURSON_JC {mat.mid}: LCJC={mat.jc_lcjc} replaces the whole "
            "D1 + D2*exp(D3*eta) term with a failure-strain curve of "
            "triaxiality, and LS-DYNA then IGNORES D1, D2 and D3 (Vol II R17 "
            "p.2-838). /FAIL/JOHNSON has no slot for that curve and its only "
            "form is the analytic one, so NO Johnson-Cook failure card is "
            f"emitted — D1={d1:g}, D2={d2:g}, D3={d3:g}, D4={d4:g} are inert "
            "in the source deck and are NOT converted. The /MAT/LAW52 f_F "
            "coalescence criterion still applies. Restate the failure as "
            "*MAT_ADD_DAMAGE_GISSMO (→ /FAIL/TAB2) to keep a tabulated "
            "triaxiality dependence.")
        return []
    dropped = [n for n, v in (("LCDAM", mat.jc_lcdam), ("L1", mat.jc_l1),
                              ("L2", mat.jc_l2)) if v]
    if dropped:
        state.warn(
            f"*MAT_GURSON_JC {mat.mid}: {', '.join(dropped)} "
            "(element-length damage scaling / the triaxiality bounds within "
            "which the JC evolution runs) have no /FAIL/JOHNSON counterpart "
            "and are DROPPED — only D1-D4 convert.")
    state.warn(
        f"*MAT_GURSON_JC {mat.mid}: Johnson-Cook damage parameters "
        f"D1={d1:g}, D2={d2:g}, D3={d3:g}, D4={d4:g} → /FAIL/JOHNSON/{mat.mid} "
        "with D3 VERBATIM (this keyword's sigma_H/sigma_M is the "
        "tension-positive triaxiality, the same convention as Radioss's "
        "sigma_m/sigma_VM — unlike *MAT_JOHNSON_COOK, whose sigma* = "
        "p/sigma_eff is compression-positive and is flipped) and Ifail_sh=2 "
        "(delete only when every through-thickness point has failed), the "
        "rule k2rad applies to every LS-DYNA built-in material failure.")
    return _emit_fail_johnson_all_layers(
        mat.mid, d1, state, d2=d2, d3=d3, d4=d4, warn=False)


def _mat124_fill_function_slots(state: ConversionState,
                                mat: MatPlasCompTens) -> None:
    """Fill the /MAT/LAW66 function slots the starter refuses to read as 0.

    ``hm_read_mat66.F:269-278`` loops ``IFUNC(1..MFUNC)`` — MFUNC=2 for the
    yield pair, 4 once Iyld_rate=3 adds the rate pair — and raises
    ``ANCMSG(MSGID=126, MSGERROR)`` "WRONG REFERENCE TO FUNCTION ID=0" for any
    zero, so a HALF-filled pair is an ERROR TERMINATION, not a degraded run.
    LS-DYNA is happy with half of either pair, so both cases must be closed
    here rather than passed through:

    * **LCIDC / LCIDT.** Vol II R17 p.2-877 remark 1: "Two curves must be
      defined giving the yield stress as a function of effective plastic strain
      for both the tension and compression regimes" — a deck with one of them
      is already degenerate LS-DYNA input, and the only reading that keeps its
      stated branch intact is to MIRROR the given curve onto the missing side
      (the material then yields the same either way, as a *MAT_024 would).
    * **LCSRC / LCSRT.** Both are documented "Optional" and independent
      (p.2-875), so an LCSRC-only deck is perfectly valid: LS-DYNA scales the
      compression yield with rate and leaves tension rate-independent. LAW66
      applies IFUNC(3)/IFUNC(4) as multiplicative yield factors
      (``sigeps66.F:481-487``, ``YC = YRATE*YC``), so a synthesized FLAT 1.0
      curve on the missing side reproduces that exactly.
    """
    if bool(mat.lcidc) != bool(mat.lcidt):
        given, given_side, missing, missing_side = (
            ("LCIDC", "compression", "LCIDT", "tension") if mat.lcidc else
            ("LCIDT", "tension", "LCIDC", "compression"))
        fid = mat.lcidc or mat.lcidt
        mat.lcidc = mat.lcidt = fid
        state.warn(
            f"*MAT_124 {mat.mid}: only {given}={fid} is given, but "
            "*MAT_PLASTICITY_COMPRESSION_TENSION needs BOTH yield curves (Vol "
            "II R17 p.2-877 remark 1) and /MAT/LAW66 hard-fails with starter "
            "ERROR 126 (WRONG REFERENCE TO FUNCTION ID=0) on an empty slot. "
            f"The {given_side} curve {fid} is MIRRORED into the {missing} "
            f"slot, so the material yields identically in {missing_side} — "
            f"state the real {missing} curve if the two regimes differ.")
    if bool(mat.lcsrc) != bool(mat.lcsrt):
        given, given_side, missing, missing_side = (
            ("LCSRC", "compression", "LCSRT", "tension") if mat.lcsrc else
            ("LCSRT", "tension", "LCSRC", "compression"))
        given_id = mat.lcsrc or mat.lcsrt
        fid = state.next_curve_id()
        _add_auto_curve(state, fid, f"Auto_MAT124_unit_rate_mid{mat.mid}",
                        [(0.0, 1.0), (1.0, 1.0)])
        if mat.lcsrc:
            mat.lcsrt = fid
        else:
            mat.lcsrc = fid
        state.warn(
            f"*MAT_124 {mat.mid}: {given}={given_id} scales the {given_side} "
            f"yield with strain rate and {missing} is blank, which LS-DYNA "
            f"reads as 'no rate effect in {missing_side}' — but /MAT/LAW66's "
            "Iyld_rate=3 card needs BOTH fnYrt slots and rejects a 0 with "
            f"starter ERROR 126. A flat unit-scale /FUNCT/{fid} (1.0 at every "
            f"rate) is synthesized for {missing}, which reproduces the LS-DYNA "
            "behaviour exactly (LAW66 multiplies the yield by the curve "
            "value).")


def _resolve_mat_plas_comp_tens(state: ConversionState) -> None:
    """*MAT_PLASTICITY_COMPRESSION_TENSION (124) prepass: fill the function
    slots /MAT/LAW66 requires to be non-zero, and report every field with no
    LAW66 counterpart, once, before the emitter runs."""
    for mat in state.mat_plas_comp_tens.values():
        for name, fid in (("LCIDC", mat.lcidc), ("LCIDT", mat.lcidt),
                          ("LCSRC", mat.lcsrc), ("LCSRT", mat.lcsrt)):
            if fid and fid not in state.curves:
                state.warn(
                    f"*MAT_124 {mat.mid}: {name}={fid} references a "
                    "*DEFINE_CURVE that is NOT in the deck — the /MAT/LAW66 "
                    "function id will dangle.")
        if mat.lcfail and mat.lcfail not in state.curves:
            state.warn(
                f"*MAT_124 {mat.mid}: LCFAIL={mat.lcfail} references a "
                "*DEFINE_CURVE that is NOT in the deck — the /FAIL/TENSSTRAIN "
                "function id will dangle.")
        _mat124_fill_function_slots(state, mat)
        if not mat.lcidc and not mat.lcidt:
            state.warn(
                f"*MAT_124 {mat.mid}: neither LCIDC nor LCIDT is given, but "
                "they are the material's only yield input — /MAT/LAW66 is "
                "written with no yield function and the starter will reject "
                "it. Add the tension/compression stress-vs-plastic-strain "
                "curves.")
        if mat.tdel:
            state.warn(
                f"*MAT_124 {mat.mid}: TDEL={mat.tdel:g} (minimum timestep "
                "shell deletion) has no /MAT/LAW66 slot and is DROPPED. Add "
                "*MAT_ADD_EROSION with DTMIN on this material to keep it.")
        if mat.pcutc or mat.pcutt or mat.pcutf:
            state.warn(
                f"*MAT_124 {mat.mid}: the pressure cut-offs PCUTC="
                f"{mat.pcutc:g} / PCUTT={mat.pcutt:g} (PCUTF={mat.pcutf:g}) "
                "are DROPPED — they zero the deviatoric stress once a 3D "
                "stress update reaches the cut-off pressure, and /MAT/LAW66 "
                "has no such criterion. NOTE these are NOT the LAW66 P_c/P_t "
                "columns: those carry PC/PT, the mean stresses at which the "
                "compression and tension yield curves take over (dyna2rad "
                "maps PCUTC/PCUTT there instead, gated on PCUTF, and drops "
                "PC/PT — reproducing that would move the yield-curve blend "
                "band onto unrelated numbers).")
        if mat.srfilt:
            state.warn(
                f"*MAT_124 {mat.mid}: SRFILT={mat.srfilt:g} (exponential "
                "moving-average filter on the strain rate) has no /MAT/LAW66 "
                "counterpart — DROPPED. LAW66's own filter is the F_cut "
                "frequency cutoff, a different formulation.")
        if mat.pc < 0.0 or mat.pt < 0.0:
            state.warn(
                f"*MAT_124 {mat.mid}: PC={mat.pc:g} / PT={mat.pt:g} — LS-DYNA "
                "requires BOTH to be entered as positive values (the sign is "
                "implied by the field). The magnitudes are written to the "
                "/MAT/LAW66 P_c/P_t columns.")


def _emit_mat_law66(mat: MatPlasCompTens, state: ConversionState) -> List[str]:
    """*MAT_PLASTICITY_COMPRESSION_TENSION (124) → /MAT/LAW66.

    Column layout from hm_cfg_files MAT/mat_law66.cfg FORMAT(radioss2022) —
    the block a /BEGIN 2022 deck reads with (EC/RPCT joined card 3 in that
    revision):
      RHO_I(20) /
      E(20) Nu(20) C_hard(20) F_cut(20) F_smooth(10) Iyld_rate(10) /
      P_c(20) P_t(20) EC(20) RPCT(20) /
      [Iyld_rate<=3] funct_IDc(10) funct_IDt(10) Fscalec(20) Fscalet(20) /
      [Iyld_rate<=2] Epsilon_0(20) c(20) Sigma_Y0(20) VP(10) /
      [Iyld_rate==3] fnYrt_IDc(10) fnYrt_IDt(10) Yrate_Fscalec(20) Yrate_Fscalet(20)

    Rate handling: ``Iyld_rate=1`` is the Cowper-Symonds branch, promoted to 3
    when either LCSRC/LCSRT rate-scaling curve exists (LAW66 then has no
    analytic term and no VP column at all).

    Two deliberate divergences from dyna2rad, both traced to the manual:

    * ``P_c``/``P_t`` carry **PC/PT** — "compressive/tensile mean stress at
      which the yield stress follows LCIDC/LCIDT" (Vol II R17 p.2-876), the
      exact meaning of LAW66's "limit pressure in compression/tension". RPCT
      is defined on BOTH sides as a fraction of that same pair, which pins the
      correspondence. dyna2rad writes PCUTC/PCUTT there.
    * ``Epsilon_0`` carries **C**. LS-DYNA's factor is 1 + (eps_dot/C)^(1/P),
      so C is the reference strain rate and P the exponent; dyna2rad maps
      ``c <- P`` correctly but never writes Epsilon_0, so the reference rate is
      lost and the reader substitutes 1.0.
    """
    iyld_rate = 3 if (mat.lcsrc or mat.lcsrt) else 1
    # C = 0 means "no strain-rate effect" in LS-DYNA; writing Epsilon_0 = 0
    # with a non-zero c would make the reader substitute a reference rate of
    # 1.0 out of thin air, so the pair is only carried when both are stated.
    cs_rate, cs_exp = (mat.c, mat.p) if (mat.c > 0.0 and mat.p > 0.0) else (0.0, 0.0)
    if iyld_rate == 1 and (mat.c or mat.p) and not cs_rate:
        state.warn(
            f"*MAT_124 {mat.mid}: the Cowper-Symonds pair is incomplete "
            f"(C={mat.c:g}, P={mat.p:g}) — 1 + (eps_dot/C)^(1/P) needs both, "
            "so the strain-rate term is DROPPED and the material converts "
            "rate-independent.")
    vp = 1 if int(mat.srflag) == 2 else 0
    if iyld_rate == 3:
        if mat.c or mat.p:
            state.warn(
                f"*MAT_124 {mat.mid}: LCSRC/LCSRT are given, so /MAT/LAW66 "
                "uses the two rate-scaling curves (Iyld_rate=3) and its "
                "analytic Cowper-Symonds card does not exist — "
                f"C={mat.c:g}/P={mat.p:g} are DROPPED. LS-DYNA applies the "
                "curves the same way, so this matches the source deck.")
        if vp:
            state.warn(
                f"*MAT_124 {mat.mid}: SRFLAG=2 (viscoplastic / effective "
                "plastic strain rate) cannot be carried: /MAT/LAW66's VP "
                "column only exists on the Iyld_rate<=2 card, and LCSRC/LCSRT "
                "force Iyld_rate=3. The rate curves are then driven by the "
                "TOTAL strain rate.")
    elif int(mat.srflag) == 1:
        state.warn(
            f"*MAT_124 {mat.mid}: SRFLAG=1 (effective/deviatoric strain rate) "
            "has no /MAT/LAW66 flag — VP=0 is written, which is the TOTAL "
            "strain rate. Only SRFLAG=2 maps (to VP=1).")
    lines = [
        f"/MAT/LAW66/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu              C_hard               F_cut  F_smooth Iyld_rate",
        f"{_f(mat.E)}{_f(mat.nu)}{_f(0.0)}{_f(0.0)}{_i(1)}{_i(iyld_rate)}",
        "#                P_c                 P_t                  EC                RPCT",
        f"{_f(abs(mat.pc))}{_f(abs(mat.pt))}{_f(mat.ec)}{_f(mat.rpct)}",
        "#funct_IDc funct_IDt             Fscalec             Fscalet",
        f"{_i(mat.lcidc)}{_i(mat.lcidt)}{_f(1.0)}{_f(1.0)}",
    ]
    if iyld_rate == 3:
        lines += [
            "#fnYrt_IDc fnYrt_IDt       Yrate_Fscalec       Yrate_Fscalet",
            f"{_i(mat.lcsrc)}{_i(mat.lcsrt)}{_f(1.0)}{_f(1.0)}",
        ]
    else:
        lines += [
            "#          Epsilon_0                   c            Sigma_Y0        VP",
            f"{_f(cs_rate)}{_f(cs_exp)}{_f(0.0)}{_i(vp, 10)}",
        ]
    lines.append(HDR)
    if mat.k > 0.0 and mat.gi:
        state.warn(
            f"*MAT_124 {mat.mid}: the {len(mat.gi)}-term Prony viscoelastic "
            f"branch (K={mat.k:g}) → /VISC/PRONY/{mat.mid}, which Radioss "
            "binds to the material by shared id.")
        lines += _emit_visc_prony_kv(mat.mid, mat.gi, mat.betai, mat.k)
    elif mat.gi:
        state.warn(
            f"*MAT_124 {mat.mid}: {len(mat.gi)} Gi/BETAi Prony pair(s) are "
            f"given but K={mat.k:g} (<=0), so LS-DYNA runs the viscoelastic "
            "branch deviatoric-only. /VISC/PRONY needs a bulk modulus to be "
            "meaningful alongside it; following dyna2rad the whole Prony "
            "branch is DROPPED. Set K to keep it.")
    lines += _emit_mat124_fail(mat, state)
    return lines


def _visc_prony_lines(mid: int, m: int, k_v: float = 0.0, itab: int = 0,
                      ishape: int = 0,
                      gis: Optional[List[float]] = None,
                      betais: Optional[List[float]] = None,
                      kis: Optional[List[float]] = None,
                      betakis: Optional[List[float]] = None,
                      fct_g: int = 0, fct_k: int = 0) -> List[str]:
    """The one /VISC/PRONY card writer, shared by every caller so the layout
    cannot drift. Audited against hm_cfg_files MAT/mat_VISC_PRONY.cfg
    FORMAT(radioss2021) — the block a /BEGIN 2022 deck is read with. NOTE: no
    title line after the header, and the M card has a 10-space LITERAL gap
    before K_v (the cfg's own "%10d          %20lg%10d%10d").

      Itab 0: M(10) gap(10) K_v(20) Itab(10) Ishape(10)
              + M x [G_i Beta_i Ki Beta_ki](4x20)
      Itab 1: same first card + EXACTLY two rows
              Ifunc_G(10) XGscale(20) YGscale(20) /
              Ifunc_K(10) XKscale(20) YKscale(20)
              — the starter then least-squares-fits an M-term Prony series to
              the tabulated relaxation curve (LM_LEAST_SQUARE_PRONY).

    Binding is by id alone: the block id must equal the /MAT id or the starter
    raises ERROR 1663 (hm_read_visc.F:106-121). M = 0 is ERROR 2026, so no
    caller may emit this block with an empty series."""
    lines = [
        f"/VISC/PRONY/{mid}",
        "#        M                           K_v      Itab    Ishape",
        f"{_i(m)}{' ' * 10}{_f(k_v)}{_i(itab)}{_i(ishape)}",
    ]
    if itab == 1:
        lines += [
            "#  Ifunc_G             XGscale             YGscale",
            f"{_i(fct_g)}{_f(0.0)}{_f(0.0)}",
            "#  Ifunc_K             XKscale             YKscale",
            f"{_i(fct_k)}{_f(0.0)}{_f(0.0)}",
        ]
    else:
        gis = gis or []
        betais = betais or []
        kis = kis or [0.0] * len(gis)
        betakis = betakis or [0.0] * len(gis)
        lines.append(
            "#                G_i              Beta_i                  Ki             Beta_ki")
        for i, g in enumerate(gis):
            lines.append(f"{_f(g)}{_f(betais[i] if i < len(betais) else 0.0)}"
                         f"{_f(kis[i] if i < len(kis) else 0.0)}"
                         f"{_f(betakis[i] if i < len(betakis) else 0.0)}")
    lines.append(HDR)
    return lines


def _emit_visc_prony_kv(mid: int, gis: List[float], betais: List[float],
                        k_v: float) -> List[str]:
    """/VISC/PRONY with a non-zero bulk modulus — the *MAT_124 form. Same
    layout as _emit_visc_prony (which writes K_v = 0 for the MAT_077_H path);
    the bulk relaxation terms Ki/Beta_ki stay 0 because LS-DYNA's card carries
    only the deviatoric Gi/BETAi pairs."""
    return _visc_prony_lines(mid, len(gis), k_v=k_v, gis=gis, betais=betais)


def _emit_visc_prony_full(mid: int, gis: List[float], betais: List[float],
                          kis: List[float], betakis: List[float],
                          k_v: float = 0.0) -> List[str]:
    """/VISC/PRONY carrying BOTH the deviatoric and the bulk relaxation
    columns — the *MAT_076 form, whose LS-DYNA card really does supply
    GI/BETAI/KI/BETAKI per term. dyna2rad copies GI/BETAI/KI but asks the SDI
    layer for "BETAK", which is not the array's solver name ("BETAKI"), so
    every bulk decay constant is silently dropped and the bulk branch runs with
    K_i != 0 and beta_ki = 0 (CM:4526). k2rad writes all four."""
    return _visc_prony_lines(mid, len(gis), k_v=k_v, gis=gis, betais=betais,
                             kis=kis, betakis=betakis)


def _emit_visc_prony_fit(mid: int, m: int, fct_g: int, fct_k: int) -> List[str]:
    """/VISC/PRONY Itab=1 — the starter fits an M-term Prony series to the
    tabulated relaxation function(s), which is exactly *MAT_076's LCID+NT
    input. dyna2rad intends this branch but never reaches it: it reads the
    LS-DYNA field through sdiIdentifier("LSD_LCIDK"), and the cfg attribute is
    LSD_LCID2 (solver name LCIDK), so the handle is always invalid, the
    Itab=1 test `lcId > 0 && lcIdk > 0` is never true, and its Ifunc_G/Ifunc_K
    would in any case have been written onto the LAW42 MATERIAL, which has no
    such fields (CM:4496-4516)."""
    return _visc_prony_lines(mid, m, itab=1, fct_g=fct_g, fct_k=fct_k)


def _emit_mat124_fail(mat: MatPlasCompTens,
                      state: ConversionState) -> List[str]:
    """*MAT_124 FAIL / LCFAIL → /FAIL/JOHNSON or /FAIL/TENSSTRAIN.

    LCFAIL (failure plastic strain vs strain rate) OVERRIDES FAIL, but only
    when at least one of SRFLAG=2, LCSRC!=0, LCSRT!=0 or a Gi/BETAi pair is
    given (Vol II R17 p.2-878 remark 2) — outside that gate LS-DYNA itself
    ignores LCFAIL, so FAIL applies and k2rad says so rather than emitting
    nothing (dyna2rad's ``else if(lcfailId > 0)`` swallows both).
    """
    lcfail_active = mat.lcfail > 0 and (
        int(mat.srflag) == 2 or mat.lcsrc or mat.lcsrt
        or (any(mat.gi) and any(mat.betai)))
    if mat.fail < 0.0:
        state.warn(
            f"*MAT_124 {mat.mid}: FAIL={mat.fail:g} < 0 selects the LS-DYNA "
            "user failure subroutine matusr_24 in dyn21.F, which has no "
            "OpenRadioss counterpart — NO failure model is emitted.")
        return []
    if mat.lcfail > 0 and not lcfail_active:
        state.warn(
            f"*MAT_124 {mat.mid}: LCFAIL={mat.lcfail} is given but none of the "
            "four conditions that activate it holds (SRFLAG=2, LCSRC!=0, "
            "LCSRT!=0, or Gi/BETAi given), so LS-DYNA IGNORES it too "
            "(Vol II R17 p.2-878) — the rate-dependent failure curve is "
            "DROPPED and "
            + (f"FAIL={mat.fail:g} applies instead."
               if 0.0 < mat.fail < 1e19 else
               "the material has no failure criterion at all."))
    if lcfail_active:
        if 0.0 < mat.fail < 1e19:
            state.warn(
                f"*MAT_124 {mat.mid}: LCFAIL={mat.lcfail} overrides "
                f"FAIL={mat.fail:g} (LS-DYNA's own rule), so only the "
                "rate-dependent curve is converted.")
        state.warn(
            f"*MAT_124 {mat.mid}: LCFAIL={mat.lcfail} (effective plastic "
            f"strain at failure vs strain rate) → /FAIL/TENSSTRAIN/{mat.mid} "
            "with Epsilon_t1=1.0 / Epsilon_t2=1.1 and the curve in the FCT_ID "
            "scaling slot, so failure starts at LCFAIL(eps_dot) and the "
            "element is deleted at 1.1x that. APPROXIMATION: TENSSTRAIN "
            "measures TOTAL tensile strain, not the effective PLASTIC strain "
            "LS-DYNA's curve is written against — they differ by the elastic "
            "part. Same construction as dyna2rad.")
        return [
            f"/FAIL/TENSSTRAIN/{mat.mid}",
            "#         EPSILON_T1          EPSILON_T2    FCT_ID          EPSILON_F1          EPSILON_F2     S_Flag",
            f"{_f(1.0)}{_f(1.1)}{_i(mat.lcfail)}{_f(0.0)}{_f(0.0)}{_i(0)}",
            HDR,
        ]
    if 0.0 < mat.fail < 1e19:
        return _emit_fail_johnson_all_layers(mat.mid, mat.fail, state)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Hyperelastic rubber batch: MAT_007 / MAT_027 / MAT_077_O / MAT_077_H
# ─────────────────────────────────────────────────────────────────────────────

def _law42_lines(mid: int, title: str, rho: float, nu: float, sigma_cut: float,
                 funidbulk: int, fscale_bulk: float, iform: int,
                 mus: List[float], alphas: List[float],
                 gammas: List[float], taus: List[float]) -> List[str]:
    """/MAT/LAW42 (OGDEN) card block. Layout audited against hm_cfg_files
    MAT/matl42_Ogden.cfg FORMAT(radioss140) — the block a /BEGIN 2022 deck is
    read with:
      RHO_I(20) /
      Nu(20) sigma_cut(20) Jstrain(10) funIDbulk(10) Fscale_bulk(20) M(10) I_form(10) /
      Mu_1..Mu_5(5x20) / BLANK / alpha_1..alpha_5(5x20) / BLANK /
      [M>0: Gamma CELL_LIST(5x20/line) / Tau CELL_LIST]
    Two traps: card 2 cols 41-50 are a phantom Jstrain %10d the reader consumes
    but never uses (funIDbulk lives at cols 51-60, NOT 41-50), and the two
    BLANK cards are mandatory (they are the future Mu_6-10/alpha_6-10 slots of
    the radioss2025 layout — omitting them desyncs the reader). Blank(0)
    fields keep the starter defaults: Nu 0→0.495, sigma_cut ≤0→1e20,
    Fscale_bulk 0→1.0, I_form 0→1 (hm_read_mat42.F:147-160)."""
    m = len(gammas)
    lines = [
        f"/MAT/LAW42/{mid}",
        title or f"MAT_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#                 Nu           sigma_cut           funIDbulk         Fscale_bulk         M    I_form",
        f"{_f(nu)}{_f(sigma_cut)}{' ' * 10}{_i(funidbulk)}{_f(fscale_bulk)}{_i(m)}{_i(iform)}",
        "#               Mu_1                Mu_2                Mu_3                Mu_4                Mu_5",
        "".join(_f(v) for v in (mus + [0.0] * 5)[:5]),
        "# blank card",
        "",
        "#            alpha_1             alpha_2             alpha_3             alpha_4             alpha_5",
        "".join(_f(v) for v in (alphas + [0.0] * 5)[:5]),
        "# blank card",
        "",
    ]
    if m > 0:
        lines.append("# Shear modulus")
        lines += _wrap_cells([_f(v) for v in gammas])
        lines.append("# Time relaxation")
        lines += _wrap_cells([_f(v) for v in taus])
    lines.append(HDR)
    return lines


def _law69_lines(mid: int, title: str, rho: float, law_id: int, nu: float,
                 n_pair: int, fct_id1: int) -> List[str]:
    """/MAT/LAW69 (least-squares-fitted Ogden/Mooney-Rivlin) card block.
    Layout audited against hm_cfg_files MAT/matl69_69.cfg FORMAT(radioss120)
    (the block a /BEGIN 2022 deck is read with):
      RHO_I(20) / LAW_ID(10) FCT_ID(10) NU(20) FSCALE(20) N_PAIR(10) ICHECK(10) /
      FCT_ID1(10)
    FCT_ID at cols 11-20 is the BULK-scaling function (unused, 0); the test
    curve goes on the separate FCT_ID1 card. FSCALE/ICHECK/N_PAIR are written
    0 like dyna2rad — the starter defaults them to 1.0 / -3 / 2, and LAW_ID 0
    becomes -1 (automatic fit); LAW_ID outside {-1,1,2} is starter ERROR 882,
    a missing FCT_ID1 curve ERROR 894 (hm_read_mat69.F:134-160)."""
    return [
        f"/MAT/LAW69/{mid}",
        title or f"MAT_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#   LAW_ID    FCT_ID                  NU              FSCALE    N_PAIR    ICHECK",
        f"{_i(law_id)}{_i(0)}{_f(nu)}{_f(0.0)}{_i(n_pair)}{_i(0)}",
        "#  FCT_ID1",
        f"{_i(fct_id1)}",
        HDR,
    ]


def _emit_visc_prony(mid: int, gis: List[float], betais: List[float]) -> List[str]:
    """/VISC/PRONY bound to the /MAT of the SAME id (Radioss pairs them by
    unit id — no separate id namespace). Layout audited against hm_cfg_files
    MAT/mat_VISC_PRONY.cfg FORMAT(radioss2021), the block a /BEGIN 2022 deck
    is read with — NOTE: no title line after the header, and the M card has a
    10-space literal gap before K_v:
      M(10) gap(10) K_v(20) Itab(10) Ishape(10) / M x [G_i Beta_i Ki Beta_ki](4x20)
    dyna2rad (MAT_077_H both branches) writes K_v=0, Itab/Ishape 0, the LS-DYNA
    Gi/BETAi pairs verbatim (Beta_i is the decay constant directly — no 1/BETA
    inversion) and zero bulk terms."""
    return _visc_prony_lines(mid, len(gis), gis=gis, betais=betais)


def _emit_mat_law42_blatz_ko(mat: MatBlatzKo) -> List[str]:
    """*MAT_BLATZ-KO_RUBBER (MAT_007) → /MAT/LAW42 fixed form — dyna2rad
    case 7 verbatim: Mu_1 = G, alpha_1 = 2, Nu = 0.463 (the Poisson value the
    LS-DYNA Blatz-Ko implementation hard-codes), everything else at starter
    defaults (no bulk function, I_form 0→1)."""
    return _law42_lines(mat.mid, mat.title, mat.rho, nu=0.463, sigma_cut=0.0,
                        funidbulk=0, fscale_bulk=0.0, iform=0,
                        mus=[mat.g], alphas=[2.0], gammas=[], taus=[])


def _emit_mat_mooney_rivlin(mat: MatMooneyRivlin) -> List[str]:
    """*MAT_MOONEY-RIVLIN_RUBBER (MAT_027) → /MAT/LAW42 (constants branch) or
    /MAT/LAW69 LAW_ID=2 (curve branch) — routing and the funIDbulk curve were
    resolved by _resolve_mat_hyper_rubber. Constants branch (dyna2rad
    p_ConvertMatL27): Mu_1 = 2A, Mu_2 = -2B, alpha_1 = 2, alpha_2 = -2 (the
    C10/C01 → Ogden equivalences), Nu = PR verbatim (blank → 0 → starter
    0.495); curve branch: the LCID id goes onto FCT_ID1 unmodified — the
    starter runs the Mooney-Rivlin fit itself."""
    if mat.use_law69:
        return _law69_lines(mat.mid, mat.title, mat.rho, law_id=2, nu=mat.pr,
                            n_pair=0, fct_id1=mat.lcid)
    return _law42_lines(mat.mid, mat.title, mat.rho, nu=mat.pr, sigma_cut=0.0,
                        funidbulk=mat.funidbulk, fscale_bulk=0.0, iform=0,
                        mus=[2.0 * mat.a, -2.0 * mat.b], alphas=[2.0, -2.0],
                        gammas=[], taus=[])


def _ogden_kept_prony(mat: MatOgdenRubber):
    """The BETAI>0 terms dyna2rad keeps for the embedded LAW42 Prony arrays:
    Gamma_i = GI, Tau_i = 1/BETAI (CM:4590-4603; BETAI<=0 terms dropped)."""
    kept = [(g, b) for g, b in zip(mat.gi, mat.betai) if b > 0.0]
    return [g for g, _ in kept], [1.0 / b for _, b in kept]


def _emit_mat_ogden_rubber(mat: MatOgdenRubber) -> List[str]:
    """*MAT_OGDEN_RUBBER (MAT_077_O) → /MAT/LAW42 (N=0) or /MAT/LAW69 (N>0).

    N=0 (dyna2rad p_ConvertMatL77): mu/alpha pairs 1:1 (pairs 6-8 have no slot
    in the radioss140 5-pair layout — warned in the resolver), Nu = |PR|,
    I_form = 2 ("modified strain energy density" — dyna2rad sets it
    explicitly), and the BETAI>0 viscous terms embedded as Gamma_i = GI,
    Tau_i = 1/BETAI. N>0: LAW69 with LAW_ID = int(DATA) (0 → starter
    automatic fit, 1 = Ogden, 2 = Mooney-Rivlin), N_PAIR = N and the
    resolver's rescaled FCT_ID1."""
    if mat.n > 0:
        return _law69_lines(mat.mid, mat.title, mat.rho, law_id=int(mat.data),
                            nu=abs(mat.pr), n_pair=mat.n, fct_id1=mat.fct_id1)
    gammas, taus = _ogden_kept_prony(mat)
    return _law42_lines(mat.mid, mat.title, mat.rho, nu=abs(mat.pr),
                        sigma_cut=0.0, funidbulk=0, fscale_bulk=0.0, iform=2,
                        mus=list(mat.mu[:5]), alphas=list(mat.alpha[:5]),
                        gammas=gammas, taus=taus)


def _emit_mat_hyper_rubber(mat: MatHyperelasticRubber) -> List[str]:
    """*MAT_HYPERELASTIC_RUBBER (MAT_077_H) → /MAT/LAW95 (N=0) or /MAT/LAW69
    (N>0), + a /VISC/PRONY trailer of the same id when Gi terms exist (both
    branches — dyna2rad CM:9699-9738).

    LAW95 layout audited against hm_cfg_files MAT/LAW95.cfg
    FORMAT(radioss2020), the block a /BEGIN 2022 deck is read with (NO NU or
    IFORM fields at this format revision — compressibility rides on D1 alone):
      Rho_I(20) / C10 C01 C20 C11 C02 (5x20 — NOTE C20 before C11, the
      Radioss order, NOT the LS-DYNA card order) / C30 C21 C12 C03 Sb /
      D1 D2 D3 (3x20) / A C M KSI TAU_REF (5x20)
    D1 = |2/K| with K = 2G(1+PR)/3/(1-2PR), G = 2(C10+C01) was computed by the
    resolver (d1 field); every Bergstrom-Boyce network-B term stays 0 like
    dyna2rad writes it (A=0 disables creep, and the starter defaults the zero
    C/M/KSI/TAU_REF to their valid values -0.7/1/0.01/unit,
    hm_read_mat95.F:170-202 — starter-validated, 0 errors). The starter also
    force-promotes LAW95 properties to Ismstr=10 (WARNING 1200) — k2rad
    pre-sets that on the serving solid sections (writer.mesh) so the deck is
    warning-clean with the identical formulation."""
    if mat.n > 0:
        lines = _law69_lines(mat.mid, mat.title, mat.rho, law_id=int(mat.data),
                             nu=abs(mat.pr), n_pair=mat.n, fct_id1=mat.fct_id1)
    else:
        lines = [
            f"/MAT/LAW95/{mat.mid}",
            mat.title or f"MAT_{mat.mid}",
            "#              Rho_I",
            f"{_f(mat.rho)}",
            "#                C10                 C01                 C20                 C11                 C02",
            f"{_f(mat.c10)}{_f(mat.c01)}{_f(mat.c20)}{_f(mat.c11)}{_f(mat.c02)}",
            "#                C30                 C21                 C12                 C03                  Sb",
            f"{_f(mat.c30)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            "#                 D1                  D2                  D3",
            f"{_f(mat.d1)}{_f(0.0)}{_f(0.0)}",
            "#                  A                   C                   M                 KSI             TAU_REF",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            HDR,
        ]
    if mat.gi:
        lines += _emit_visc_prony(mat.mid, mat.gi, mat.betai)
    return lines


def _mat027_bulk_points(a: float, b: float, pr: float) -> List[Tuple[float, float]]:
    """The 500-point MAT_027 funIDbulk curve, reproducing dyna2rad
    p_ConvertMatL27 (CM:1845-1863) bit-for-bit:
      mu_p = 2(A+B);  K = 2·mu_p·(1+PR)/(3(1-2PR))
      D = (A(5PR-2) + B(11PR-5))/(2(1-2PR))            [the LS-DYNA MAT_027 D]
      j = 0.01, 500 steps of +=0.01 (accumulated — j never lands exactly on
      1.0, which keeps the 0/0 point finite via float round-off)
      fbulk = (2A(j^0 - j^-5) + 4B(j^0 - j^-5) + 4D·j(j²-1)) / (K(j-1))
    The j^0 terms are dyna2rad's C++ INTEGER divisions pow(j,(-1/3)) and
    pow(j,(1/3)) — both exponents evaluate to 0, so the intended cube-root
    terms are the constant 1.0. Reproduced as-built (the shipped converter's
    output is the validation reference), not "fixed" to the textbook form.

    Engine semantics (sigeps42.F): the funIDbulk ordinate is a DIMENSIONLESS
    multiplier on the Nu-derived bulk modulus — K_eff(J) = RBULK *
    Fscale_bulk * f(J) (Fscale_bulk blank → 1.0, exactly what dyna2rad
    leaves), NOT a pressure. The as-built curve evaluates to f(1) ≈ 1.0, so
    the Nu-implied bulk stiffness is preserved at J ≈ 1 and f stays positive
    over the whole 0.01..5 grid; the integer-division quirk only warps the
    away-from-1 tangent-bulk profile vs. the intended cube-root shape. It
    also bypasses the no-curve branch's anti-buckling P_FAC floor — one of
    the free-explicit near-incompressible caveats documented in the
    CHANGELOG."""
    mu_p = (2.0 * a * 2.0 + -2.0 * b * -2.0) / 2.0
    k = (2.0 * mu_p * (1.0 + pr)) / (3.0 * (1.0 - 2.0 * pr))
    d = (a * (5.0 * pr - 2.0) + b * (11.0 * pr - 5.0)) / (2.0 * (1.0 - 2.0 * pr))
    pts: List[Tuple[float, float]] = []
    j = 0.01
    for _ in range(500):
        jm5 = pow(j, -5)
        fbulk = (2.0 * a * (1.0 - jm5) + 4.0 * b * (1.0 - jm5)
                 + 4.0 * d * j * (pow(j, 2) - 1.0)) / (k * (j - 1.0))
        pts.append((j, fbulk))
        j = j + 0.01
    return pts


def _resolve_law69_curve(state: ConversionState, kw: str, mat) -> None:
    """Shared MAT_077_O/_H N>0 curve resolve (dyna2rad CM:4643-4687 =
    CM:9649-9693): LCID1 rescaled to engineering stress-strain with
    SFA = 1/SGL, SFO = 1/(SW*ST) (blank SGL/SW → 1; dyna2rad leaves ST
    UNGUARDED and would emit an infinite ordinate scale — k2rad treats blank
    ST as 1.0 instead, warned when it matters). A non-unit scale produces a
    "<name>_Duplicate" auto-/FUNCT with the scale applied to the (already
    SFA/SFO/OFFA/OFFO-resolved) points; k2rad applies the extra scale to the
    offset points, which also sidesteps dyna2rad's unscaled-shift quirk
    (its /MOVE_FUNCT shift term misses the extra factor when the original
    curve carries OFFA/OFFO). Also flags an out-of-range DATA: dyna2rad
    writes LAW_ID = int(DATA) blindly, but the starter only accepts 1
    (Ogden) / 2 (Mooney-Rivlin) / -1 automatic fit (blank 0 defaults to -1,
    hm_read_mat69.F) — anything else is starter ERROR 882."""
    if int(mat.data) not in (-1, 0, 1, 2):
        state.warn(
            f"{kw} mid={mat.mid}: DATA={mat.data:g} is not a valid "
            "experimental-data type (1=uniaxial/Ogden fit, 2=Mooney-Rivlin; "
            "-1 or blank = automatic) — /MAT/LAW69 LAW_ID="
            f"{int(mat.data)} is written like dyna2rad does, and the starter "
            "will reject it (ERROR 882); fix the *MAT card.")
    lcid = mat.lcid1
    if lcid <= 0 or lcid not in state.curves:
        if lcid > 0:
            state.warn(
                f"{kw} mid={mat.mid}: LCID1={lcid} has no parsed *DEFINE_CURVE "
                "— /MAT/LAW69 is emitted with FCT_ID1=0, which the starter "
                "rejects (ERROR 894); add the test curve to the deck.")
        else:
            state.warn(
                f"{kw} mid={mat.mid}: N={mat.n} selects the curve-fit input "
                "but no LCID1 test curve is given — /MAT/LAW69 is emitted "
                "with FCT_ID1=0 (starter ERROR 894).")
        mat.fct_id1 = 0
        return
    sgl = mat.sgl if mat.sgl != 0.0 else 1.0
    sw = mat.sw if mat.sw != 0.0 else 1.0
    st = mat.st
    if st == 0.0:
        if mat.sgl != 0.0 or mat.sw != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: ST is blank while SGL={mat.sgl:g}/"
                f"SW={mat.sw:g} are set — ST treated as 1.0 (dyna2rad leaves "
                "1/(SW*ST) unguarded and would write an infinite ordinate "
                "scale); check the specimen dimensions.")
        st = 1.0
    sfa = 1.0 / sgl
    sfo = 1.0 / (sw * st)
    if sfa == 1.0 and sfo == 1.0:
        mat.fct_id1 = lcid
        return
    curve = state.curves[lcid]
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, (curve.title or f"FUNCT_{lcid}") + "_Duplicate",
                    [(x * sfa, y * sfo) for x, y in curve.pts])
    mat.fct_id1 = fid
    state.warn(
        f"{kw} mid={mat.mid}: test curve LCID1={lcid} normalized to "
        f"engineering stress-strain as /FUNCT {fid} (abscissa x{sfa:g} = "
        f"1/SGL, ordinate x{sfo:g} = 1/(SW*ST)) — dyna2rad's specimen "
        "normalization; the original curve is kept unchanged.")


def _warn_mullins(state: ConversionState, kw: str, mid: int, pr: float) -> None:
    """dyna2rad warning 28 ("the Mullins effect is not take into account"):
    PR<0 flags the LS-DYNA Mullins/frequency variants; only |PR| survives."""
    state.warn(
        f"{kw} mid={mid}: PR={pr:g} < 0 (Mullins-effect input flag) — the "
        "Mullins effect is not taken into account; |PR| is used as the "
        "Poisson's ratio (dyna2rad warning 28).")


def _resolve_mat_hyper_rubber(state: ConversionState) -> None:
    """Routing + curve synthesis + drop-warnings for the hyperelastic rubber
    batch, before _make_materials emits. Follows dyna2rad's decision logic:
      MAT_027: parsed LCID curve → LAW69 LAW_ID=2, else LAW42 + the 500-point
               funIDbulk curve; MAT_077_O/_H N>0: the LAW69 FCT_ID1 rescale.
    Every field dyna2rad drops silently is warned here instead (SGL/SW/ST on
    MAT_027, NV/LCID2/BSTART/TRAMP, the 077_O N>0 GI/BETAI loss, 077_H
    G/SIGF/Gj/SIGFj, LAW42 mu/alpha pairs 6-8 at /BEGIN 2022)."""
    for mat in state.mat_mooney_rivlin.values():
        kw = "*MAT_MOONEY-RIVLIN_RUBBER"
        if mat.lcid > 0 and mat.lcid not in state.curves:
            state.warn(
                f"{kw} mid={mat.mid}: LCID={mat.lcid} has no parsed "
                "*DEFINE_CURVE — falling back to the A/B-constants /MAT/LAW42 "
                "branch (dyna2rad routes on the curve handle the same way).")
        mat.use_law69 = mat.lcid > 0 and mat.lcid in state.curves
        if mat.use_law69:
            nontrivial = [f"{n}={v:g}" for n, v in
                          (("SGL", mat.sgl), ("SW", mat.sw), ("ST", mat.st))
                          if v not in (0.0, 1.0)]
            if nontrivial:
                state.warn(
                    f"{kw} mid={mat.mid}: {', '.join(nontrivial)} are IGNORED "
                    "— dyna2rad passes LCID to /MAT/LAW69 unscaled (unlike "
                    "MAT_077), so the curve must already be engineering "
                    "stress vs strain; rescale it if it is specimen "
                    "force vs elongation.")
            continue
        if 1.0 - 2.0 * mat.pr == 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PR=0.5 makes the bulk modulus K "
                "infinite — the funIDbulk curve is skipped (dyna2rad would "
                "emit NaN points) and Nu=0.5 will trip the starter's "
                "incompressibility limit; use PR=0.495-0.4999.")
        elif mat.a + mat.b == 0.0:
            if mat.a == 0.0 and mat.b == 0.0:
                state.warn(
                    f"{kw} mid={mat.mid}: A=B=0 gives a zero shear-modulus "
                    "sum — no funIDbulk curve (dyna2rad would emit NaN/inf "
                    "points) and the all-zero mu pairs are starter ERROR "
                    "828; give A/B or an LCID test curve.")
            else:
                state.warn(
                    f"{kw} mid={mat.mid}: A+B=0 (A={mat.a:g}, B={mat.b:g}) "
                    "gives a zero shear-modulus sum mu_p=2(A+B) — no "
                    "funIDbulk curve (its bulk modulus K=0 makes dyna2rad "
                    "emit inf points); the ±2-power mu pairs are still "
                    "emitted verbatim; check the constants.")
        else:
            fid = state.next_curve_id()
            _add_auto_curve(state, fid, f"Auto_MAT027_fbulk_mid{mat.mid}",
                            _mat027_bulk_points(mat.a, mat.b, mat.pr))
            mat.funidbulk = fid

    for mat in state.mat_ogden.values():
        kw = "*MAT_OGDEN_RUBBER"
        if mat.pr < 0.0:
            _warn_mullins(state, kw, mat.mid, mat.pr)
        if mat.n > 0:
            _resolve_law69_curve(state, kw, mat)
            if mat.gi:
                state.warn(
                    f"{kw} mid={mat.mid}: {len(mat.gi)} viscoelastic GI/BETAI "
                    "term(s) are DROPPED on the N>0 (curve-fit → /MAT/LAW69) "
                    "path — dyna2rad only embeds them in the N=0 LAW42 form; "
                    "the converted material is rate-independent.")
        else:
            extra = [f"MU{i + 1}={mat.mu[i]:g}/ALPHA{i + 1}={mat.alpha[i]:g}"
                     for i in range(5, 8)
                     if mat.mu[i] != 0.0 or mat.alpha[i] != 0.0]
            if extra:
                state.warn(
                    f"{kw} mid={mat.mid}: Ogden pairs 6-8 ({', '.join(extra)}) "
                    "are DROPPED — the radioss140-format /MAT/LAW42 card a "
                    "/BEGIN 2022 deck reads has 5 mu/alpha slots (10 need "
                    "/BEGIN 2025); refit with <= 5 pairs to keep the response.")
            dropped = [(g, b) for g, b in zip(mat.gi, mat.betai) if b <= 0.0]
            if dropped:
                state.warn(
                    f"{kw} mid={mat.mid}: {len(dropped)} viscoelastic term(s) "
                    "with BETAI <= 0 dropped from the LAW42 Prony arrays "
                    "(Tau_i = 1/BETAI is undefined; dyna2rad drops them "
                    "silently).")
        if mat.g > 0.0 and mat.sigf > 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: G={mat.g:g}/SIGF={mat.sigf:g} "
                "(frequency-independent damping) DROPPED — dyna2rad's "
                "/VISC/PLAS target only exists from the radioss2025 input "
                "format on and cannot be read in the /BEGIN 2022 decks k2rad "
                "emits.")
        if mat.lcid2 or mat.bstart or mat.tramp:
            state.warn(
                f"{kw} mid={mat.mid}: LCID2={mat.lcid2}/BSTART={mat.bstart:g}/"
                f"TRAMP={mat.tramp:g} (relaxation-curve viscoelastic fit) "
                "have no dyna2rad mapping — dropped.")

    for mat in state.mat_hyper_rubber.values():
        kw = "*MAT_HYPERELASTIC_RUBBER"
        if mat.n > 0:
            if mat.pr < 0.0:
                _warn_mullins(state, kw, mat.mid, mat.pr)
            _resolve_law69_curve(state, kw, mat)
        else:
            _resolve_law95_d1(state, kw, mat)
        if mat.g or mat.sigf:
            state.warn(
                f"{kw} mid={mat.mid}: header G={mat.g:g}/SIGF={mat.sigf:g} "
                "(frequency-independent damping) are never read by dyna2rad "
                "for MAT_077_H — dropped.")
        if any(mat.gj) or any(mat.sigfj):
            state.warn(
                f"{kw} mid={mat.mid}: per-term Gj/SIGFj damping columns are "
                "never read by dyna2rad — dropped (only Gi/BETAi go to "
                "/VISC/PRONY).")
        if mat.lcid2 or mat.bstart or mat.tramp:
            state.warn(
                f"{kw} mid={mat.mid}: LCID2={mat.lcid2}/BSTART={mat.bstart:g}/"
                f"TRAMP={mat.tramp:g} (relaxation-curve viscoelastic fit) "
                "have no dyna2rad mapping — dropped.")

    _warn_rubber_ref(state)


def _resolve_law95_d1(state: ConversionState, kw: str,
                      mat: MatHyperelasticRubber) -> None:
    """MAT_077_H N=0 compressibility → LAW95 D1 (dyna2rad CM:9580-9601).
    PR<0: Mullins warning, D1 stays 0 (starter defaults nu to 0.495).
    PR>=0: D1 = |2/K|, K = 2G(1+PR)/3/(1-2PR), G = 2(C10+C01). PR=0.5 with
    G>0 gives K=inf → D1=0 (the C++ limit, matched exactly). Guarded
    deviations from dyna2rad's C++: G<=0 (K<=0 → D1 would be inf/NaN on the
    card) and the PR=0.5, G=0 corner both leave D1=0 with a warning instead
    of writing a non-finite number. PR blank (0) is dyna2rad's exact
    behavior K = 2G/3, i.e. nu = 0 — warned, because a zero-Poisson rubber is
    almost never intended."""
    if mat.pr < 0.0:
        _warn_mullins(state, kw, mat.mid, mat.pr)
        mat.d1 = 0.0
        return
    g2 = 2.0 * (mat.c01 + mat.c10)
    if g2 <= 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: C10+C01 = {(mat.c10 + mat.c01):g} <= 0 — "
            "the D1 = 2/K compressibility term is undefined (dyna2rad would "
            "write a non-finite D1); D1 left 0, so the starter uses the "
            "incompressible default nu=0.495.")
        mat.d1 = 0.0
        return
    denom = 1.0 - 2.0 * mat.pr
    if denom == 0.0:
        mat.d1 = 0.0     # K = inf → D1 = 2/inf = 0: exact C++ limit for G>0
        return
    k = 2.0 * g2 * (1.0 + mat.pr) / 3.0 / denom
    mat.d1 = abs(2.0 / k)
    if mat.pr == 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: PR is blank/0 — dyna2rad's exact behavior "
            f"encodes K = 2G/3 (D1={mat.d1:g}), i.e. a Poisson's ratio of 0, "
            "NOT the incompressible 0.495; set PR (e.g. 0.495) if the rubber "
            "is meant to be incompressible.")


def _warn_rubber_ref(state: ConversionState) -> None:
    """REF flags vs *INITIAL_FOAM_REFERENCE_GEOMETRY coverage. dyna2rad
    converts the keyword unconditionally and never reads the REF flags (except
    MAT_007, where REF=1 makes a nodeless /XREF stub — not replicated: with no
    reference coordinates it initializes nothing). k2rad emits the real /XREF
    blocks from the keyword (writer.inistate._make_xref) and warns when a
    REF=1 material has no reference-geometry coverage to initialize from.

    Covers EVERY REF-bearing family through ``_ref_flag_materials`` — including
    *MAT_SIMPLIFIED_RUBBER/FOAM, *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE and
    *MAT_SOFT_TISSUE, whose LAW88/LAW42 targets are on the solid-/XREF
    whitelist just like the four hyperelastic rubbers. The mirror case (a /XREF
    reaching a REF=0 material) is reported by ``_resolve_xref_parts``, which is
    the pass that actually knows which parts kept a block."""
    flagged = [(kw, m) for kw, mats in _ref_flag_materials(state)
               for m in mats.values() if m.ref != 0.0]
    if not flagged:
        return
    if not state.foam_ref_geoms:
        for kw, m in flagged:
            state.warn(
                f"{kw} mid={m.mid}: REF={m.ref:g} requests stress-free "
                "reference-geometry initialization but the deck has no "
                "*INITIAL_FOAM_REFERENCE_GEOMETRY — no /XREF emitted; the "
                "run starts unstressed at the modeled coordinates.")
        return
    ref_nids = set()
    for ref in state.foam_ref_geoms:
        ref_nids |= set(ref.nodes)
    pnodes = _part_node_sets(state)
    for kw, m in flagged:
        mid_nodes = set()
        for pid, part in state.parts.items():
            if part.mid == m.mid:
                mid_nodes |= pnodes.get(pid, set())
        if mid_nodes and not (mid_nodes & ref_nids):
            state.warn(
                f"{kw} mid={m.mid}: REF={m.ref:g} but the "
                "*INITIAL_FOAM_REFERENCE_GEOMETRY node table covers no node "
                "of this material's part(s) — no /XREF reaches it; the run "
                "starts unstressed at the modeled coordinates.")


# ─────────────────────────────────────────────────────────────────────────────
# Viscoelastic batch: MAT_006 / MAT_061 / MAT_076 / MAT_181 / MAT_183 /
#                     MAT_091 / MAT_092
# ─────────────────────────────────────────────────────────────────────────────

def _law34_lines(mid: int, title: str, rho: float, bulk: float, g0: float,
                 gl: float, beta: float) -> List[str]:
    """/MAT/LAW34 (BOLTZMAN) card block. Layout audited against hm_cfg_files
    MAT/matl34_boltzman.cfg FORMAT(radioss51) — the block a /BEGIN 2022 deck is
    read with — and against hm_read_mat34.F:
      Init.dens.(20) / K(20) / G0(20) Gl(20) Beta(20) / P0(20) Phi(20) Gamma0(20)
    All four data cards are UNCONDITIONAL: the P0/Phi/Gamma0 air-in-foam card
    must be present even when every value is zero, or the reader runs off the
    end of the block. G(t) = Gl + (G0-Gl)*exp(-Beta*t) (sigeps34.F:88-101).

    Reference-density trap, shared by LAW34/40/42/62: the reader pre-scans
    columns 21-40 of the density card (CARD_PREREAD) and switches to the
    two-field form if anything non-blank sits there — so the density line must
    be exactly the 20-column field and nothing else. _f() gives that.

    The starter applies NO defaults to K/G0/Gl/Beta; the cfg CHECK block wants
    all of them > 0."""
    return [
        f"/MAT/LAW34/{mid}",
        title or f"MAT_{mid}",
        "#        Init. dens.",
        f"{_f(rho)}",
        "#                  K",
        f"{_f(bulk)}",
        "#                 G0                  Gl                Beta",
        f"{_f(g0)}{_f(gl)}{_f(beta)}",
        "#                 P0                 Phi              Gamma0",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _law40_lines(mid: int, title: str, rho: float, bulk: float, g_inf: float,
                 gs: List[float], betas: List[float]) -> List[str]:
    """/MAT/LAW40 (KELVINMAX) card block. Layout audited against hm_cfg_files
    MAT/matl40_kelvinmax.cfg FORMAT(radioss90) and hm_read_mat40.F:
      RHO_I(20) / K(20) G_inf(20) Astass(20) Bstass(20) Kvm(20) /
      G1..G5(5x20) / BETA1..BETA5(5x20)

    Astass/Bstass/Kvm are written 0 on purpose: hm_read_mat40.F:122-124 turns
    any value <= 1e-20 into INFINITY, which disables the Stassi/von-Mises yield
    surface and leaves pure viscoelasticity — dyna2rad's choice and the right
    one for a *MAT_061.

    FIVE Maxwell branches, hard — the card has no CELL_LIST and no
    continuation, so a series with more terms has to go to LAW42 +
    /VISC/PRONY (up to 100) instead."""
    g5 = (list(gs) + [0.0] * 5)[:5]
    b5 = (list(betas) + [0.0] * 5)[:5]
    return [
        f"/MAT/LAW40/{mid}",
        title or f"MAT_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#                  K               G_inf              Astass              Bstass                 Kvm",
        f"{_f(bulk)}{_f(g_inf)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#                 G1                  G2                  G3                  G4                  G5",
        "".join(_f(v) for v in g5),
        "#              BETA1               BETA2               BETA3               BETA4               BETA5",
        "".join(_f(v) for v in b5),
        HDR,
    ]


def _law88_lines(mid: int, title: str, rho: float, nu: float, k: float,
                 fcut: float, fct_unload: int, fscale_unload: float,
                 hys: float, shape: float, tension: int,
                 fct_load: List[int], rates: List[float]) -> List[str]:
    """/MAT/LAW88 (TABULATED_HYPERELASTIC) card block. Layout audited against
    hm_cfg_files MAT/mat_law88.cfg FORMAT(radioss2017) — the block a /BEGIN
    2022 deck is read with — and against hm_read_mat88.F90:
      RHO_I(20) /
      NU(20) K(20) F_CUT(20) F_SMOOTH(10) NL(10) /
      FCT_ID_UN(10) gap(10) F_SCALE_UN(20) HYS(20) SHAPE(20) TENSION(10) /
      NL x [FCT_ID_LI(10) gap(10) F_SCALE_LI(20) EPSI_LI(20)]

    EXACTLY three cards plus the NL rows. The radioss2026 revision adds an
    SGL/SW/ST/G/SIGF card and a KFAIL/GAM1/GAM2/EH/FAILIP card, and a /BEGIN
    2022 starter SWALLOWS them without an error — measured: SGL=0.05 reads back
    as 1.0 — so emitting them would be silent data loss, not a diagnosable
    version complaint. The specimen normalization is therefore baked into the
    curve POINTS instead (see _law88_curve).

    Three traps: card 2 columns 61-70 (F_SMOOTH) are consumed by the format and
    read by NOBODY in the current starter — written blank; card 3's TENSION
    sits at columns 81-90, past the 80-column mark; and EPSI_LI == 0 on a row
    i > 1 is silently replaced by 1.0 in the unit system, not 0.

    Blank(0) fields keep the starter defaults: F_SCALE_UN/F_SCALE_LI 0 -> 1.0,
    F_CUT 0 -> a sound-speed-derived cut-off, NU <= 0 -> beta = |NU| viscous
    pressure and NU := 0.495 (hm_read_mat88.F90:128-227). NL == 0 is ERROR
    866."""
    lines = [
        f"/MAT/LAW88/{mid}",
        title or f"MAT_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#                 NU                   K               F_CUT  F_SMOOTH        NL",
        f"{_f(nu)}{_f(k)}{_f(fcut)}{' ' * 10}{_i(len(fct_load))}",
        "#FCT_ID_UN                    F_SCALE_UN                 HYS               SHAPE   TENSION",
        f"{_i(fct_unload)}{' ' * 10}{_f(fscale_unload)}{_f(hys)}{_f(shape)}"
        f"{_i(tension)}",
    ]
    if fct_load:
        lines.append(
            "#FCT_ID_LI                    F_SCALE_LI             EPSI_LI")
        for fid, rate in zip(fct_load, rates):
            lines.append(f"{_i(fid)}{' ' * 10}{_f(0.0)}{_f(rate)}")
    lines.append(HDR)
    return lines


def _emit_mat_viscoelastic(mat: MatViscoelastic) -> List[str]:
    """*MAT_VISCOELASTIC (MAT_006) → /MAT/LAW34 (BOLTZMAN) — an exact 1:1.
    BULK/G0/GI/BETA go straight across (BETA is a decay RATE in both codes,
    so there is nothing to convert) and the P0/Phi/Gamma0 air-in-foam term is
    left inactive, exactly like dyna2rad p_ConvertMatL6."""
    return _law34_lines(mat.mid, mat.title, mat.rho, mat.bulk, mat.g0, mat.gi,
                        mat.beta)


def _emit_mat_kelvin_maxwell(mat: MatKelvinMaxwell) -> List[str]:
    """*MAT_KELVIN-MAXWELL_VISCOELASTIC (MAT_061) → /MAT/LAW40 (KELVINMAX),
    dyna2rad p_ConvertMatL61 verbatim: G_inf = GI, G1 = G0 - GI, BETA1 = DC,
    and the four remaining Maxwell branches plus Astass/Bstass/Kvm zeroed."""
    return _law40_lines(mat.mid, mat.title, mat.rho, mat.bulk, mat.gi,
                        [mat.g0 - mat.gi], [mat.dc])


def _emit_mat_general_visco(mat: MatGeneralViscoelastic) -> List[str]:
    """*MAT_GENERAL_VISCOELASTIC (MAT_076) → /MAT/LAW42 (OGDEN) + /VISC/PRONY.

    The elastic carrier is dyna2rad p_ConvertMatL76 verbatim (CM:4457-4472):
    Nu = 0.495, Mu_1 = +0.01*BULK, Mu_2 = -0.01*BULK, alpha = +2/-2 — i.e. a
    Mooney-Rivlin ground state with C10 = C01 = 0.005*BULK. LAW42 has no bulk
    field at all (it derives one from Nu), so the LS-DYNA BULK reaches Radioss
    only through those mu values; the resolve pass reports what that really
    costs. PCF/EF/TREF/A/B and the BSTART/TRAMP fit seeds have no LAW42 slot.

    The Prony series rides the separate /VISC/PRONY block, which is the only
    Radioss card with all four LS-DYNA columns (LAW42's own embedded Gamma/Tau
    arrays have no bulk column, and their Tau is a relaxation TIME while
    LS-DYNA gives decay constants). Itab=1 carries the LCID/NT curve-fit form
    onto the starter's own Levenberg-Marquardt Prony fit."""
    lines = _law42_lines(mat.mid, mat.title, mat.rho, nu=0.495, sigma_cut=0.0,
                         funidbulk=0, fscale_bulk=0.0, iform=0,
                         mus=[0.01 * mat.bulk, -0.01 * mat.bulk],
                         alphas=[2.0, -2.0], gammas=[], taus=[])
    if mat.prony_m > 0 and mat.prony_itab == 1:
        lines += _emit_visc_prony_fit(mat.mid, mat.prony_m, mat.lcid, mat.lcidk)
    elif mat.prony_m > 0:
        lines += _emit_visc_prony_full(mat.mid, mat.gi, mat.betai, mat.ki,
                                       mat.betaki)
    return lines


def _soft_tissue_prony(mat: MatSoftTissue):
    """The (S_i, T_i) pairs that reach LAW42's Gamma_arr/Tau_arr: the NON-ZERO
    ones, COMPACTED. dyna2rad counts every non-zero S_i but then copies slots
    0..M-1 (CM:11010-11021), so an S1 = 0 with S2 != 0 silently converts the
    wrong terms — and it indexes an sdiDoubleList that was only reserve()d, not
    resize()d, which is out of bounds on top of that."""
    kept = [(s, t) for s, t in zip(mat.s, mat.t) if s != 0.0]
    return [s for s, _ in kept], [t for _, t in kept]


def _emit_mat_soft_tissue(mat: MatSoftTissue) -> List[str]:
    """*MAT_SOFT_TISSUE (091) / _VISCO (092) → /MAT/LAW42 (OGDEN), dyna2rad
    p_ConvertMatL91_92 verbatim: Mu_1 = 2*C1, Mu_2 = -2*C2, alpha = +2/-2,
    Nu = 0.495 — the standard Mooney-Rivlin <-> Ogden identity for the
    ISOTROPIC ground substance of LS-DYNA's strain energy. The _VISCO S_i/T_i
    pairs go into LAW42's own Gamma_arr/Tau_arr (relaxation TIMES on both
    sides, so T_i needs no inversion); no /VISC/PRONY is involved.

    Everything transversely isotropic — the C3/C4/C5 collagen fibre term,
    XLAM/XLAM0/FANG, all of AOPT and the three FAILS* modes — has no LAW42
    slot and is enumerated by the resolve pass."""
    gammas, taus = _soft_tissue_prony(mat)
    return _law42_lines(mat.mid, mat.title, mat.rho, nu=0.495, sigma_cut=0.0,
                        funidbulk=0, fscale_bulk=0.0, iform=0,
                        mus=[2.0 * mat.c1, -2.0 * mat.c2], alphas=[2.0, -2.0],
                        gammas=gammas, taus=taus)


def _emit_mat_simplified_rubber(mat: MatSimplifiedRubber) -> List[str]:
    """*MAT_SIMPLIFIED_RUBBER/FOAM (181) / *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE
    (183) → /MAT/LAW88, with the loading/unloading curve family resolved by
    _resolve_mat_viscoelastic (which needs the parsed *DEFINE_CURVE /
    *DEFINE_TABLE and synthesizes the specimen-normalized duplicates).

    NU is the LS-DYNA PR verbatim, unlike dyna2rad's hard 0: LAW88's own
    `nu <= 0 -> beta = |nu|, nu := 0.495` rule (hm_read_mat88.F90:186-191) IS
    the LS-DYNA `PR <= 0` viscous-pressure-decay rule, so passing PR through
    transfers it exactly and still reproduces dyna2rad's output for a blank PR.
    TENSION is transferred too — dyna2rad asks for "TENSIOM" for MAT_181, a
    string that appears nowhere else in the whole Radioss tree, so its
    rate-effect flag never arrives (it gets MAT_183 right).

    F_SMOOTH is written blank because the current starter never reads it.
    MAT_181's optional Gi/BETAi cards become a /VISC/PRONY of the same id."""
    lines = _law88_lines(
        mat.mid, mat.title, mat.rho, nu=mat.pr, k=mat.k, fcut=0.0,
        fct_unload=mat.fct_unload, fscale_unload=0.0, hys=mat.hys,
        shape=mat.shape_out, tension=mat.tension,
        fct_load=mat.fct_load, rates=mat.rates)
    if mat.gi:
        lines += _emit_visc_prony(mat.mid, mat.gi, mat.betai)
    return lines


# Loading functions a /MAT/LAW88 may carry. The starter declares
# `parameter (maxfunc = 128)` (hm_read_mat.F90:294) and sizes
# ifunc/rate/yfac/lambda at maxfunc+1 (hm_read_mat88.F90:103-108), then reads
# `do i = 1,nl` with NO upper bound on NL — so an over-long rate family is an
# out-of-bounds write rather than a diagnosable error.
_LAW88_MAX_NL = 128


def _law88_curve(state: ConversionState, kw: str, mat: MatSimplifiedRubber,
                 lcid: int, role: str, cache: Optional[dict] = None) -> int:
    """One *MAT_181/183 test curve → the /FUNCT id LAW88 should reference.

    LS-DYNA states the curve as specimen FORCE vs CHANGE IN GAUGE LENGTH and
    normalizes it with SGL/SW/ST; LAW88 has SGL/SW/ST fields only from the
    radioss2026 card revision on, and a /BEGIN 2022 starter forces all three to
    1.0 (hm_read_mat88.F90:205-215). The normalization therefore has to be in
    the points: abscissa x 1/SGL (engineering strain), ordinate x 1/(SW*ST)
    (engineering stress). Same construction as dyna2rad, which carries the two
    factors on a /MOVE_FUNCT instead — except that dyna2rad REFUSES to write
    any curve at all unless SGL, SW and ST are ALL non-zero (CM:4955), which
    turns a curve already given in stress-strain form into NL = 0, i.e. starter
    ERROR 866; and for MAT_183 it uses the two scale factors UNINITIALISED in
    that case (CM:5165-5166). k2rad reads a blank dimension as 1.0 — "the curve
    is already engineering stress vs strain", which is also what the starter
    itself assumes.

    *cache* maps a source LCID to the id already synthesized for it inside this
    material, so a curve used twice — the same LCID on LC and LCUNLD, or repeated
    across the rows of a *DEFINE_TABLE — yields ONE duplicate. That is not just
    tidiness: with two distinct ids the starter's self-unloading rule
    (`if ifunc_unload == ifunc(1) then ifunc_unload = 0`,
    hm_read_mat88.F90:221-225) would no longer fire, and the material would
    unload along a separate-but-identical function instead of being flagged
    hysteresis-free."""
    if cache is not None and lcid in cache:
        return cache[lcid]
    crv = state.curves.get(lcid)
    if crv is None or not crv.pts:
        state.warn(
            f"{kw} mid={mat.mid}: {role} curve {lcid} has no parsed "
            "*DEFINE_CURVE — the reference is DROPPED"
            + (", and with no loading curve at all /MAT/LAW88 gets NL=0, "
               "which the starter rejects (ERROR 866)"
               if role == "loading" else "")
            + "; add the curve to the deck.")
        return 0
    xmin = min(x for x, _ in crv.pts)
    if role == "loading" and xmin >= 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: {role} curve {lcid} has NO negative-strain "
            f"(compression) points — its lowest abscissa is "
            f"{xmin:g}. /MAT/LAW88 evaluates this curve "
            "at ALL THREE principal stretches (sigeps88.F90:375-377 feeds "
            "lam1, lam2 and lam3 into the same table), so a uniaxial TENSION "
            "test drives the two lateral stretches into compression — at 100% "
            "axial strain they sit at lam=0.707, i.e. engineering strain "
            "-0.293 — where the curve is EXTRAPOLATED. Measured consequence "
            "on a single-element cell: the lateral stretches bifurcated at "
            "eps=0.65 (lam2 0.79 -> 0.41 while lam3 grew to 1.45, kinetic "
            "energy up 4 orders of magnitude) and the run still reached "
            "NORMAL TERMINATION with wrong results; adding the compression "
            "branch fixed it (lam2=lam3=0.70734 at eps=1, J=1.00066). Extend "
            "the table into negative strain.")
    sgl = mat.sgl if mat.sgl != 0.0 else 1.0
    sw = mat.sw if mat.sw != 0.0 else 1.0
    st = mat.st if mat.st != 0.0 else 1.0
    sfa = 1.0 / sgl
    sfo = 1.0 / (sw * st)
    if sfa == 1.0 and sfo == 1.0:
        if cache is not None:
            cache[lcid] = lcid
        return lcid
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, (crv.title or f"FUNCT_{lcid}") + "_Duplicate",
                    [(x * sfa, y * sfo) for x, y in crv.pts])
    if cache is not None:
        cache[lcid] = fid
    state.warn(
        f"{kw} mid={mat.mid}: {role} curve {lcid} normalized to engineering "
        f"stress-strain as /FUNCT {fid} (abscissa x{sfa:g} = 1/SGL, ordinate "
        f"x{sfo:g} = 1/(SW*ST)) — the /BEGIN 2022 /MAT/LAW88 card has no "
        "SGL/SW/ST fields, so the specimen normalization has to live in the "
        "points; the original curve is kept unchanged.")
    return fid


def _resolve_law88_curves(state: ConversionState, kw: str,
                          mat: MatSimplifiedRubber) -> None:
    """LAW88 FCT_ID_LI / EPSI_LI / FCT_ID_UN, following dyna2rad
    ConvertMatL181ToMatL88 (CM:4953-5145) and p_ConvertMatL183 (CM:5188-5462).

    A *DEFINE_TABLE LC/TBID becomes one loading curve per rate, plus a
    DUPLICATE of the highest-rate curve at 10x that rate — dyna2rad's
    deliberate flat-extrapolation guard, so Radioss does not extrapolate the
    rate axis past the measured data. A *DEFINE_CURVE becomes a single row at
    rate 1.0.

    Unloading, in dyna2rad's priority order: LCUNLD -> HU/SHAPE (181 only,
    and only when the optional card is really there — HU defaults to 1.0, "no
    dissipation") -> the loading curve itself, which the starter then nulls out
    (`if ifunc_unload == ifunc(1) then ifunc_unload = 0`)."""
    fcts: List[int] = []
    rates: List[float] = []
    cache: dict = {}
    tab = state.define_tables.get(mat.lc_tbid)
    if mat.lc_tbid <= 0:
        state.warn(
            f"{kw} mid={mat.mid}: no LC/TBID loading curve is given — "
            "/MAT/LAW88 needs at least one (NL=0 is starter ERROR 866).")
    elif tab is not None and not (tab.resolved and tab.rows):
        # A table that IS in the deck but could not be resolved must not fall
        # through to the single-curve branch: the id would then be reported as
        # a missing *DEFINE_CURVE, which names the wrong keyword entirely.
        state.warn(
            f"{kw} mid={mat.mid}: LC/TBID={mat.lc_tbid} is a *DEFINE_TABLE "
            "that could not be resolved to (rate, curve) rows — the rate "
            "family is DROPPED and /MAT/LAW88 gets NL=0, which the starter "
            "rejects (ERROR 866). See the *DEFINE_TABLE's own warning for why "
            "it did not resolve.")
    elif tab is not None:
        rows = list(tab.rows)
        if len(rows) > _LAW88_MAX_NL - 1:
            state.warn(
                f"{kw} mid={mat.mid}: *DEFINE_TABLE {mat.lc_tbid} has "
                f"{len(rows)} rate rows; /MAT/LAW88 is limited to "
                f"{_LAW88_MAX_NL} loading functions (the starter declares "
                "maxfunc=128 and sizes ifunc/rate/yfac/lambda at maxfunc+1 "
                "without checking NL — hm_read_mat.F90:294, "
                "hm_read_mat88.F90:103-108), so the highest-rate rows past "
                f"{_LAW88_MAX_NL - 1} are DROPPED to leave room for the "
                "flat-extrapolation duplicate.")
            rows = rows[:_LAW88_MAX_NL - 1]
        for rate, lc in rows:
            fid = _law88_curve(state, kw, mat, lc, "loading", cache)
            if fid:
                fcts.append(fid)
                rates.append(rate)
        if fcts:
            extra = rates[-1] * 10.0
            if extra <= rates[-1]:
                # A non-increasing extra rate is starter ERROR 478; dyna2rad
                # multiplies blindly, which for a top rate of 0 repeats it.
                extra = rates[-1] + 1.0
            fcts.append(fcts[-1])
            rates.append(extra)
            state.warn(
                f"{kw} mid={mat.mid}: *DEFINE_TABLE {mat.lc_tbid} converted to "
                f"{len(fcts) - 1} rate-dependent loading curve(s); the highest-"
                f"rate curve is REPEATED at Eps_dot={extra:g} so Radioss holds "
                "it flat instead of extrapolating past the measured rate range "
                "(dyna2rad does the same).")
    else:
        fid = _law88_curve(state, kw, mat, mat.lc_tbid, "loading", cache)
        if fid:
            fcts.append(fid)
            rates.append(1.0)
    mat.fct_load = fcts
    mat.rates = rates
    if mat.lcunld > 0:
        mat.fct_unload = _law88_curve(state, kw, mat, mat.lcunld, "unloading",
                                      cache)
        if mat.fct_unload and mat.family == "181" and mat.has_unload_card \
                and mat.hu != 1.0:
            state.warn(
                f"{kw} mid={mat.mid}: HU={mat.hu:g} is IGNORED because "
                f"LCUNLD={mat.lcunld} is given — LS-DYNA's own rule, and "
                "/MAT/LAW88 applies HYS only when FCT_ID_UN is 0.")
    elif mat.family == "181" and mat.has_unload_card and mat.hu > 0.0:
        mat.hys = mat.hu
        mat.shape_out = mat.shape
    elif fcts:
        # dyna2rad's third branch: point FCT_ID_UN at the loading curve. The
        # starter recognizes that and disables unloading, so the effect is
        # "unload along the loading curve", i.e. no hysteresis.
        mat.fct_unload = fcts[0]


def _resolve_mat_viscoelastic(state: ConversionState) -> None:
    """Routing, curve synthesis and drop-warnings for the viscoelastic batch,
    before _make_materials emits. Runs after _resolve_define_tables (MAT_181's
    LC/TBID may be a table) and before _resolve_xref_parts (LAW42 and LAW88 are
    both on the starter's solid-/XREF law whitelist, so these materials change
    which parts get a /XREF).

    Every field dyna2rad drops in silence is warned here instead — for this
    batch that is most of them, and for *MAT_SOFT_TISSUE it is the entire
    reason the material is not physically equivalent."""
    _resolve_mat006(state)
    _resolve_mat061(state)
    _resolve_mat076(state)
    _resolve_mat181_183(state)
    _resolve_mat091_092(state)


def _resolve_mat006(state: ConversionState) -> None:
    """*MAT_VISCOELASTIC: collapse the temperature curves, then check the
    LAW34 preconditions."""
    kw = "*MAT_VISCOELASTIC"
    for mat in state.mat_viscoelastic.values():
        for attr, name in (("bulk", "BULK"), ("g0", "G0"),
                           ("gi", "GI"), ("beta", "BETA")):
            val = getattr(mat, attr)
            if val >= 0.0:
                continue
            lcid = int(-val)
            crv = state.curves.get(lcid)
            if crv is None or not crv.pts:
                setattr(mat, attr, 0.0)
                state.warn(
                    f"{kw} mid={mat.mid}: {name}={val:g} names temperature "
                    f"curve {lcid}, which has no parsed *DEFINE_CURVE — the "
                    f"field is written 0, and /MAT/LAW34 requires {name} > 0 "
                    "(starter rejects the material); add the curve.")
                continue
            setattr(mat, attr, crv.pts[0][1])
            state.warn(
                f"{kw} mid={mat.mid}: {name}={val:g} is a TEMPERATURE-dependent "
                f"curve (LCID {lcid}). /MAT/LAW34 has no temperature "
                f"dependence, so it is collapsed to {crv.pts[0][1]:g}, the "
                f"value at the lowest tabulated temperature "
                f"({crv.pts[0][0]:g}) — dyna2rad's rule for G0/GI/BETA. "
                + ("(dyna2rad never reads the BULK curve at all and leaves "
                   "K=0, which the starter then rejects.) "
                   if name == "BULK" else "")
                + "The converted material is isothermal; re-state it at the "
                  "working temperature if that is not what the run needs.")
        if mat.g0 == mat.gi:
            state.warn(
                f"{kw} mid={mat.mid}: G0=GI={mat.g0:g}, so G(t) is constant "
                "and the material is purely ELASTIC — there is no relaxation "
                "left to convert. /MAT/LAW34 is still written (dyna2rad raises "
                "its error 200003 here and also continues); use *MAT_ELASTIC "
                "if that is intended.")
        _warn_law34_zero_fields(state, kw, mat)


def _warn_law34_zero_fields(state: ConversionState, kw: str,
                            mat: MatViscoelastic) -> None:
    """Non-positive /MAT/LAW34 fields, graded by what the solver really does.

    The matl34_boltzman.cfg CHECK block asks for BULK/DECAY/G0/GI/RHO > 0, but
    that is a HyperMesh-side rule: hm_read_mat34.F contains no ANCMSG at all —
    it copies BULK/G0/GI/BETA straight into UPARAM(1..4). Each case below was
    measured on starter_win64 + engine_win64 (/BEGIN 2022, single hex, held
    shear) rather than read off the cfg, because the four outcomes differ:

      RHO  = 0  starter ERROR 683, deck stops.               (measured)
      G0   = 0  starter clean, but YOUNG = 9*K*G0/(3*K+G0) = 0 and the solid
                element time step comes out 1.0E+21.        (measured)
      BULK = 0  starter clean, YOUNG = 0, no volumetric stiffness left; the
                element time step stays finite.             (measured)
      GI   = 0  fully LEGAL — G_inf = 0 is "relaxes completely". Starter clean,
                engine clean, sensible energies.            (measured)
      BETA = 0  starter clean, then the ENGINE divides by it: sigeps34.F:101
                computes C2 = -(1-exp(-BETA*dt))/BETA = 0/0, so every
                deviatoric stress increment is NaN — and the run still reports
                NORMAL TERMINATION.                          (measured: 1114
                cycles of NaN I-ENERGY / EXT-WORK)

    So GI = 0 must not be reported as fatal (the old wording pushed the user to
    change a correct card), and BETA = 0 must not be reported as merely
    unreadable (it is a silent NaN run, which is worse)."""
    if mat.rho <= 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: RHO={mat.rho:g} <= 0 — the starter rejects "
            "the material with ERROR 683 (zero density) and the deck does not "
            "read; fill the card in.")
    if mat.beta == 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: BETA=0 — the starter takes the card, but the "
            "LAW34 engine kernel forms C2 = -(1-exp(-BETA*dt))/BETA "
            "(sigeps34.F:101), i.e. 0/0, so every deviatoric stress increment "
            "becomes NaN while the run still ends NORMAL TERMINATION. If no "
            "relaxation is wanted, use *MAT_ELASTIC; if the decay constant is "
            "simply missing from the card, fill it in.")
    elif mat.beta < 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: BETA={mat.beta:g} < 0 makes exp(-BETA*t) "
            "GROW without bound — the viscous shear stress diverges. LAW34 "
            "takes the value unchecked; restate BETA as a positive decay "
            "rate.")
    if mat.g0 <= 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: G0={mat.g0:g} <= 0 — the starter takes the "
            "card, but YOUNG = 9*K*G0/(3*K+G0) collapses to 0 "
            "(hm_read_mat34.F:139) and the part's solid time step was measured "
            "at 1.0E+21, i.e. the material carries no shear stiffness and sets "
            "no stable step. Give the short-time shear modulus.")
    if mat.bulk <= 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: BULK={mat.bulk:g} <= 0 — the starter takes "
            "the card, but the material then has NO volumetric stiffness "
            "(YOUNG and the LAW34 sound speed PM(27) both come out 0). Give "
            "the elastic bulk modulus.")
    if mat.gi < 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: GI={mat.gi:g} < 0 — G_inf is the LONG-TIME "
            "shear modulus and cannot be negative; LAW34 takes it unchecked "
            "and the relaxed stiffness comes out negative.")
    elif mat.gi == 0.0 and mat.g0 > 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: GI=0 means the material relaxes COMPLETELY — "
            f"G(t) decays from G0={mat.g0:g} to zero long-time shear "
            "stiffness. This is a legal card on both sides (LS-DYNA states no "
            "lower bound for GI, and hm_read_mat34.F validates nothing), and "
            "it converts and runs cleanly; flagged only because a blank GI "
            "field reads the same way as a deliberate zero.")


def _shell_parts_by_mid(state: ConversionState) -> dict:
    """{mid: sorted part ids} over the parts that carry shell elements or a
    *SECTION_SHELL.

    Built ONCE per conversion rather than per material: the element scan is
    O(n_shells), so doing it inside a per-material loop costs
    O(n_shells x n_materials) — seconds of pure overhead on a million-shell
    deck with several MAT_061s, in a pass that otherwise only touches the
    material dicts."""
    shell_pids = {e.pid for e in state.shell_elems}
    out: dict = {}
    for pid, p in sorted(state.parts.items()):
        if pid in shell_pids or p.secid in state.sec_shells:
            out.setdefault(p.mid, []).append(pid)
    return out


def _resolve_mat061(state: ConversionState) -> None:
    """*MAT_KELVIN-MAXWELL_VISCOELASTIC: the FO Kelvin branch, the LAW40
    Poisson gate and the solids-only applicability check."""
    kw = "*MAT_KELVIN-MAXWELL_VISCOELASTIC"
    if not state.mat_kelvin_maxwell:
        return
    shell_parts = _shell_parts_by_mid(state)
    for mat in state.mat_kelvin_maxwell.values():
        g1 = mat.g0 - mat.gi
        if mat.fo != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: FO={mat.fo:g} selects the KELVIN "
                f"formulation, in which DC={mat.dc:g} is a RETARDATION time "
                "constant obeying a different evolution equation, not a "
                "Maxwell decay rate. /MAT/LAW40's kernel is exp(-BETA*dt) "
                "(Maxwell only), so DC is written into BETA1 as if FO were 0 "
                "— the same thing dyna2rad does SILENTLY. The converted "
                "relaxation is WRONG for this card; re-state the branch as a "
                "Maxwell one (FO=0) with an equivalent decay rate.")
        if mat.so != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: SO={mat.so:g} (which principal strain "
                "measure LS-DYNA writes to the d3plot history variables) is "
                "DROPPED — it is an output selector with no Radioss "
                "counterpart and does not affect the solution.")
        if g1 < 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: G0={mat.g0:g} < GI={mat.gi:g}, so the "
                f"Maxwell branch modulus G1 = G0-GI is NEGATIVE ({g1:g}). "
                "LS-DYNA expects the instantaneous modulus G0 to exceed the "
                "long-term GI; check the card.")
        elif g1 == 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: G0=GI={mat.g0:g} leaves G1 = G0-GI = 0, "
                "i.e. no Maxwell branch at all — the converted /MAT/LAW40 is "
                "purely elastic with shear modulus G_inf.")
        for label, gsum in (("G_inf", mat.gi), ("G_inf+sum(G_i)", mat.g0)):
            denom = 2.0 * gsum + 6.0 * mat.bulk
            if denom == 0.0:
                nu = -1.0
            else:
                nu = (3.0 * mat.bulk - 2.0 * gsum) / denom
            if nu < 0.0 or nu >= 0.5:
                state.warn(
                    f"{kw} mid={mat.mid}: the Poisson's ratio /MAT/LAW40 "
                    f"derives from BULK={mat.bulk:g} and {label}={gsum:g} is "
                    f"{nu:g}, outside [0, 0.5) — the starter REJECTS this "
                    "material with ERROR 49 (hm_read_mat40.F:126-143). BULK "
                    f"must be at least (2/3)*G0 = {2.0 * mat.g0 / 3.0:g} for "
                    "this card.")
                break
        shell_pids = shell_parts.get(mat.mid, [])
        if shell_pids:
            state.warn(
                f"{kw} mid={mat.mid}: part(s) {shell_pids} are SHELL parts, "
                "but /MAT/LAW40 declares only SOLID_ISOTROPIC and SPH "
                "(hm_read_mat40.F:184-185) and its engine kernel sigeps40 is "
                "never called from the shell path. The starter rejects the "
                "combination with ERROR 3046 (material/element "
                "compatibility). dyna2rad never checks this. Use "
                "*MAT_VISCOELASTIC (006) -> /MAT/LAW34, which IS shell-capable "
                "and has the identical Maxwell G(t), for shell parts.")


def _resolve_mat076(state: ConversionState) -> None:
    """*MAT_GENERAL_VISCOELASTIC: decide the /VISC/PRONY shape and report what
    the LAW42 elastic carrier really encodes."""
    kw = "*MAT_GENERAL_VISCOELASTIC"
    for mat in state.mat_general_visco.values():
        rows = len(mat.gi)
        if rows:
            mat.prony_m = rows
            mat.prony_itab = 0
            if mat.lcid > 0 or mat.lcidk > 0:
                state.warn(
                    f"{kw} mid={mat.mid}: card 2 names LCID={mat.lcid}/"
                    f"LCIDK={mat.lcidk} AND {rows} explicit Prony row(s) are "
                    "given. LS-DYNA takes the explicit rows (card 2 is meant "
                    "to be blank then) — so does k2rad, and the curve-fit "
                    "input is IGNORED.")
            if rows > 100:
                state.warn(
                    f"{kw} mid={mat.mid}: {rows} Prony terms exceed "
                    "/VISC/PRONY's limit of 100 — the extra terms are "
                    "DROPPED.")
                mat.prony_m = 100
                del mat.gi[100:], mat.betai[100:], mat.ki[100:], \
                    mat.betaki[100:]
            if any(k != 0.0 for k in mat.ki):
                state.warn(
                    f"{kw} mid={mat.mid}: the bulk Prony columns KI/BETAKI are "
                    "converted to /VISC/PRONY Ki/Beta_ki. dyna2rad copies KI "
                    "but asks the reader for \"BETAK\" instead of the array's "
                    "real name BETAKI, so every bulk DECAY constant is "
                    "silently lost there (CM:4526) and the bulk branch runs "
                    "with Ki != 0 and Beta_ki = 0.")
        elif mat.lcid > 0 or mat.lcidk > 0:
            # "If zero, the default is 6" applies to a fit that actually RUNS:
            # LS-DYNA fits the shear series only when LCID is given and the bulk
            # series only when LCIDK is (p.2-560). Defaulting the order of the
            # ABSENT curve to 6 would pin M at 6 for every single-curve card,
            # throwing away the user's NT — and, because the starter needs
            # 2*M < npoints (hm_read_visc_prony.F:473, ERROR 1921), turning a
            # 10-point curve that LS-DYNA fits with NT=2 into a dead deck.
            nt = (mat.nt if mat.nt > 0 else 6) if mat.lcid > 0 else 0
            ntk = (mat.ntk if mat.ntk > 0 else 6) if mat.lcidk > 0 else 0
            m = min(max(nt, ntk), 6)
            mat.prony_m = m
            mat.prony_itab = 1
            if nt and ntk and nt != ntk:
                state.warn(
                    f"{kw} mid={mat.mid}: NT={nt} and NTK={ntk} ask for "
                    "DIFFERENT fit orders, but /VISC/PRONY carries ONE M for "
                    f"both the shear and the bulk fit — the larger, M={m}, is "
                    "used for each. Split the material if the two series must "
                    "have different term counts.")
            state.warn(
                f"{kw} mid={mat.mid}: the relaxation-curve form "
                f"(LCID={mat.lcid}, NT={mat.nt}, LCIDK={mat.lcidk}, "
                f"NTK={mat.ntk}) is converted to /VISC/PRONY Itab=1 with "
                f"M={m}, so the STARTER runs the least-squares Prony fit "
                "(LM_LEAST_SQUARE_PRONY) — the same thing LS-DYNA does. "
                "dyna2rad can never reach this branch: it reads the second "
                "curve through the identifier \"LSD_LCIDK\", which does not "
                "exist (the attribute is LSD_LCID2), so its test always fails "
                "and it emits an EMPTY /VISC/PRONY, i.e. starter ERROR 2026.")
            if max(nt, ntk) > 6:
                state.warn(
                    f"{kw} mid={mat.mid}: NT/NTK={max(nt, ntk)} is "
                    "clamped to the 6-term fit dyna2rad uses; /VISC/PRONY "
                    "itself would take up to 100, but more terms also need "
                    "more curve points (2*M >= npoints is starter ERROR "
                    "1921).")
            for lcid, role in ((mat.lcid, "shear G(t)"),
                               (mat.lcidk, "bulk K(t)")):
                if lcid <= 0:
                    continue
                crv = state.curves.get(lcid)
                if crv is None or not crv.pts:
                    state.warn(
                        f"{kw} mid={mat.mid}: the {role} relaxation curve "
                        f"{lcid} has no parsed *DEFINE_CURVE — the starter "
                        "cannot run the fit and stops with ERROR 1928; add "
                        "the curve to the deck.")
                elif 2 * m >= len(crv.pts):
                    state.warn(
                        f"{kw} mid={mat.mid}: the {role} relaxation curve "
                        f"{lcid} has only {len(crv.pts)} point(s) but the fit "
                        f"asks for M={m} Prony terms — the starter requires "
                        f"2*M < npoints and stops with ERROR 1921 "
                        f"(max M here is {len(crv.pts) // 2}).")
            if mat.bstart or mat.tramp or mat.bstartk or mat.trampk:
                state.warn(
                    f"{kw} mid={mat.mid}: the fit seeds BSTART={mat.bstart:g}/"
                    f"TRAMP={mat.tramp:g}/BSTARTK={mat.bstartk:g}/"
                    f"TRAMPK={mat.trampk:g} are DROPPED — /VISC/PRONY's "
                    "Levenberg-Marquardt fit has no slot for a starting decay "
                    "constant or a ramp time and initializes itself.")
        else:
            mat.prony_m = 0
            state.warn(
                f"{kw} mid={mat.mid}: neither Prony rows nor a relaxation "
                "curve is given, so this is an ELASTIC material — NO "
                "/VISC/PRONY is emitted. dyna2rad creates the block "
                "unconditionally with M=0, which is starter ERROR 2026 and "
                "stops the whole deck.")
        state.warn(
            f"{kw} mid={mat.mid}: BULK={mat.bulk:g} does NOT become a bulk "
            "modulus. /MAT/LAW42 has no bulk field — it derives one from Nu — "
            "so dyna2rad's fixed carrier (Nu=0.495, Mu_1=+0.01*BULK, "
            "Mu_2=-0.01*BULK, alpha=+/-2) is reproduced here and gives a "
            f"ground shear modulus of {0.02 * mat.bulk:g} (=0.02*BULK) and an "
            f"effective bulk modulus of {_law42_bulk(0.02 * mat.bulk):g} "
            "(=GS*(1+Nu)/(3*(1-2*Nu)), i.e. about 2x the LS-DYNA BULK). "
            "Check the near-incompressible response against the source deck; "
            "to pin the bulk modulus exactly, restate Nu as "
            f"{_nu_for_bulk(mat.bulk, 0.02 * mat.bulk):g} on the emitted "
            "/MAT/LAW42.")
        if mat.bulk <= 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: BULK={mat.bulk:g} <= 0 leaves every "
                "/MAT/LAW42 mu at 0, so the Ogden sum GS = sum(mu_i*alpha_i) "
                "is not positive and the starter refuses the material "
                "(ERROR 828).")
        if mat.pcf != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PCF={mat.pcf:g} (1 = zero out tensile "
                "pressures) is DROPPED. /MAT/LAW42's nearest field, "
                "sigma_cut, is a STRESS and not a flag — writing 1.0 into it "
                "would impose a 1-unit tensile cut-off — so it is left blank "
                "(starter default 1e20, no cut-off).")
        if mat.ef != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: EF={mat.ef:g} (elastic layer) is "
                "DROPPED — no dyna2rad or Radioss counterpart.")
        if mat.tref or mat.a or mat.b:
            state.warn(
                f"{kw} mid={mat.mid}: the time-temperature shift function "
                f"(TREF={mat.tref:g}, A={mat.a:g}, B={mat.b:g} — WLF when all "
                "three are set, Arrhenius when B=0) is DROPPED; the converted "
                "material relaxes at one temperature only.")
        if mat.moisture:
            state.warn(
                f"{kw} mid={mat.mid}: the _MOISTURE option's whole card "
                "(MO/ALPHA/BETA/GAMMA/MST) is DROPPED and the material "
                "converts as the plain variant — dyna2rad never reads those "
                "fields either.")


def _law42_bulk(g_ground: float, nu: float = 0.495) -> float:
    """The bulk modulus /MAT/LAW42 really runs with, for a ground-state shear
    modulus MU0 = *g_ground*: BULK = GS*(1+Nu)/max(1e-20, 3*(1-2*Nu)) with
    GS = sum(mu_i*alpha_i) = 2*MU0 (hm_read_mat42.F:193-195). LAW42 has no bulk
    input, so this is the ONLY way the LS-DYNA BULK/XK could have arrived —
    used in the warnings that report what dyna2rad's hard-coded Nu = 0.495
    really costs. Starter-verified: MU0 = 60 with Nu = 0.495 echoes
    "BULK MODULUS = 5980.000000000"."""
    return 2.0 * g_ground * (1.0 + nu) / max(1e-20, 3.0 * (1.0 - 2.0 * nu))


def _nu_for_bulk(bulk: float, g_ground: float) -> float:
    """The inverse of _law42_bulk: the Nu that makes LAW42's derived bulk
    modulus equal *bulk* for a ground shear modulus MU0 = *g_ground*.
    3K(1-2v) = GS(1+v) => v = (3K - GS)/(6K + GS), GS = 2*MU0. Reported in a
    warning only — k2rad emits dyna2rad's Nu."""
    gs = 2.0 * g_ground
    denom = 6.0 * bulk + gs
    if denom == 0.0:
        return 0.495
    return (3.0 * bulk - gs) / denom


def _resolve_mat181_183(state: ConversionState) -> None:
    """*MAT_SIMPLIFIED_RUBBER/FOAM and _WITH_DAMAGE: curve wiring plus the long
    list of fields the /BEGIN 2022 LAW88 card cannot carry."""
    for mat in state.mat_simplified_rubber.values():
        kw = ("*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE" if mat.family == "183"
              else "*MAT_SIMPLIFIED_RUBBER/FOAM")
        _resolve_law88_curves(state, kw, mat)
        if 0.0 < mat.pr < 0.49:
            state.warn(
                f"{kw} mid={mat.mid}: PR={mat.pr:g} is in (0, 0.49), which "
                "selects LS-DYNA's COMPRESSIBLE Hill FOAM formulation. "
                "/MAT/LAW88 is an INCOMPRESSIBLE tabulated hyperelastic law "
                "and has no foam branch — the deviatoric response is the "
                "rubber one, and only the compressibility follows PR (written "
                "into NU). dyna2rad has a MAT_181 -> /MAT/LAW70 foam "
                "converter in its source but NO caller for it, so it silently "
                "makes every simplified foam an incompressible rubber. Use "
                "*MAT_LOW_DENSITY_FOAM (057) or *MAT_FU_CHANG_FOAM (083) if "
                "the foam volumetric response matters.")
        elif mat.pr < 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PR={mat.pr:g} < 0 is LS-DYNA's viscous "
                f"pressure-decay input (beta = {abs(mat.pr):g}); it is written "
                "into /MAT/LAW88 NU verbatim, because the starter's own "
                "`nu <= 0 -> beta = |nu|, nu := 0.495` rule is exactly that "
                "(hm_read_mat88.F90:186-191). dyna2rad writes NU=0 and loses "
                "it.")
        if mat.tension and mat.family == "181":
            state.warn(
                f"{kw} mid={mat.mid}: TENSION={mat.tension} is transferred to "
                "/MAT/LAW88 TENSION 1:1. dyna2rad asks for the field name "
                "\"TENSIOM\" for MAT_181 (a typo that appears nowhere else in "
                "the Radioss tree), so its rate-effect flag never arrives and "
                "the material silently falls back to \"rate effect for "
                "compressive loading only\".")
        if mat.rtype:
            state.warn(
                f"{kw} mid={mat.mid}: RTYPE={mat.rtype} (1 = ENGINEERING "
                "strain rate) is DROPPED — /MAT/LAW88's Rtype field only "
                "exists from the radioss2026 card revision on, and k2rad "
                "writes /BEGIN 2022 decks, so the rate axis is always read as "
                "a TRUE strain rate. Rescale the rate abscissas if the "
                "difference matters.")
        if mat.avgopt:
            state.warn(
                f"{kw} mid={mat.mid}: AVGOPT={mat.avgopt:g} (strain-rate "
                "averaging; negative = a time window) is DROPPED. "
                "/MAT/LAW88's nearest control is F_CUT, a cut-off FREQUENCY "
                "with a different meaning, and it is left blank so the starter "
                "picks its own sound-speed-derived value.")
        if mat.mu:
            state.warn(
                f"{kw} mid={mat.mid}: MU={mat.mu:g} (damping coefficient) is "
                "DROPPED. It is not a material field at all — dyna2rad writes "
                "it into the SOLID PROPERTY's viscosity slot, which would need "
                "a per-part /PROP/SOLID split here; k2rad leaves the property "
                "alone and reports the loss.")
        if mat.g or mat.sigf:
            state.warn(
                f"{kw} mid={mat.mid}: G={mat.g:g}/SIGF={mat.sigf:g} "
                "(frequency-independent damping) are DROPPED. /MAT/LAW88 does "
                "have matching G/SIGF fields, but only on the extra card of "
                "the radioss2026 revision — a /BEGIN 2022 starter SWALLOWS "
                "that card without an error (measured), so emitting it would "
                "be silent data loss rather than a diagnosable version "
                "complaint.")
        if mat.with_failure and (mat.kfail or mat.gama1 or mat.gama2 or mat.eh):
            state.warn(
                f"{kw} mid={mat.mid}: the _WITH_FAILURE card "
                f"(K={mat.kfail:g}, GAMA1={mat.gama1:g}, GAMA2={mat.gama2:g}, "
                f"EH={mat.eh:g}) is DROPPED — the converted material NEVER "
                "FAILS. /MAT/LAW88's KFAIL/GAM1/GAM2/EH are the same "
                "Feng-Hallquist criterion and map 1:1, but they live on the "
                "radioss2026 card revision, which a /BEGIN 2022 starter reads "
                "as absent. dyna2rad drops them too, silently.")
        if mat.log_log:
            state.warn(
                f"{kw} mid={mat.mid}: the _LOG_LOG_INTERPOLATION option is "
                "DROPPED — /MAT/LAW88 interpolates its rate family linearly "
                "and has no log-log flag. Rate values far from a tabulated "
                "curve will differ from LS-DYNA.")
        # VISCO is deliberately NOT in this list: it is the gate on the Gi/BETAi
        # branch, not an independent field, and the /VISC/PRONY warning below
        # reports both of its cases (honoured, or overridden when rows exist
        # with VISCO=0). REF is not here either — it is NOT dropped: LAW88 is on
        # the solid-/XREF whitelist, so a *INITIAL_FOAM_REFERENCE_GEOMETRY does
        # reach this material. _warn_rubber_ref reports REF=1 without usable
        # geometry and _resolve_xref_parts the reverse; saying "REF is DROPPED"
        # here contradicted the /XREF the very same run emits.
        dropped = [f"{n}={v:g}" for n, v in (
            ("PRTEN", mat.prten), ("STOL", mat.stol),
            ("HISOUT", float(mat.hisout)),
            ("VFLAG", float(mat.vflag))) if v]
        if dropped:
            state.warn(
                f"{kw} mid={mat.mid}: {', '.join(dropped)} are DROPPED — none "
                "has a /MAT/LAW88 counterpart (PRTEN/STOL/HISOUT are LS-DYNA "
                "solver controls, and VFLAG selects a per-term Prony "
                "formulation Radioss does not offer).")
        if mat.gi:
            state.warn(
                f"{kw} mid={mat.mid}: {len(mat.gi)} viscoelastic Gi/BETAi "
                f"pair(s) -> /VISC/PRONY/{mat.mid}, which Radioss binds to the "
                "material by shared id. LS-DYNA gates this branch on card-4 "
                f"VISCO=1 (here {mat.visco}) and applies it to SOLID elements "
                "only; k2rad emits it whenever the rows are present, like "
                "dyna2rad — delete the rows if the branch is meant to be off.")


def _resolve_mat091_092(state: ConversionState) -> None:
    """*MAT_SOFT_TISSUE / _VISCO: the fidelity warning that makes the silent
    dyna2rad conversion honest."""
    for mat in state.mat_soft_tissue.values():
        kw = "*MAT_SOFT_TISSUE_VISCO" if mat.visco else "*MAT_SOFT_TISSUE"
        mu0 = 2.0 * (mat.c1 + mat.c2)
        fibre = [f"{n}={v:g}" for n, v in (("C3", mat.c3), ("C4", mat.c4),
                                           ("C5", mat.c5), ("XLAM", mat.xlam),
                                           ("XLAM0", mat.xlam0),
                                           ("FANG", mat.fang)) if v]
        state.warn(
            f"{kw} mid={mat.mid}: converts to an ISOTROPIC incompressible "
            "Mooney-Rivlin rubber (/MAT/LAW42 with Mu_1=2*C1="
            f"{2.0 * mat.c1:g}, Mu_2=-2*C2={-2.0 * mat.c2:g}, alpha=+/-2, "
            "Nu=0.495). The transversely-isotropic COLLAGEN FIBRE term"
            + (f" ({', '.join(fibre)})" if fibre else "")
            + " and the fibre DIRECTION "
            + f"(AOPT={mat.aopt:g}, MACF={mat.macf:g}, plus the AX-AZ/BX-BZ "
              "vectors and LA1-LA3) have "
              "no /MAT/LAW42 slot and are DROPPED. For a ligament or tendon, "
              "where the fibre term dominates the response, the converted "
              "material is NOT physically equivalent — dyna2rad performs the "
              "same conversion without saying so.")
        if mat.xk:
            state.warn(
                f"{kw} mid={mat.mid}: the bulk modulus XK={mat.xk:g} is "
                "DROPPED — /MAT/LAW42 derives its bulk modulus from Nu, and "
                "dyna2rad hard-codes Nu=0.495, which for this card gives "
                f"{_law42_bulk(mu0):g} instead. Restate Nu as "
                f"{_nu_for_bulk(mat.xk, mu0):g} on the emitted /MAT/LAW42 to "
                "pin the bulk modulus to XK.")
        fails = [f"{n}={v:g}" for n, v in (("FAILSF", mat.failsf),
                                           ("FAILSM", mat.failsm),
                                           ("FAILSHR", mat.failshr)) if v]
        if fails:
            state.warn(
                f"{kw} mid={mat.mid}: {', '.join(fails)} are DROPPED — no "
                "/FAIL card is emitted and the converted material never "
                "fails.")
        if mat.c1 + mat.c2 <= 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: C1+C2={mat.c1 + mat.c2:g} <= 0 makes the "
                "Ogden sum GS = sum(mu_i*alpha_i) = 4*(C1+C2) non-positive, "
                "and the starter refuses /MAT/LAW42 with ERROR 828.")
        if mat.visco:
            gammas, taus = _soft_tissue_prony(mat)
            extra = [i + 1 for i, (s, t) in enumerate(zip(mat.s, mat.t))
                     if s == 0.0 and t != 0.0]
            if extra:
                state.warn(
                    f"{kw} mid={mat.mid}: term(s) {extra} have T_i set but "
                    "S_i = 0 and are DROPPED (a zero relaxation factor "
                    "contributes nothing). The kept pairs are COMPACTED, "
                    "unlike dyna2rad, which counts the non-zero S_i but then "
                    "copies the FIRST M slots — so a gap in the S list makes "
                    "it convert the wrong terms.")
            if gammas:
                state.warn(
                    f"{kw} mid={mat.mid}: the {len(gammas)} viscoelastic "
                    "term(s) S_i/T_i go into /MAT/LAW42's Gamma_arr/Tau_arr "
                    "(T_i needs no conversion — both codes use relaxation "
                    "TIMES). UNIT MISMATCH, inherited from dyna2rad: LS-DYNA's "
                    "S_i are DIMENSIONLESS relaxation factors, while Radioss "
                    "multiplies Gamma_i by a strain-history term "
                    "(sigeps42.F:475), i.e. it is a shear MODULUS. To carry "
                    "the intended viscous stiffness, scale each S_i by the "
                    f"ground shear modulus MU0 = 2*(C1+C2) = {mu0:g} "
                    "(Gamma_i = "
                    + ", ".join(f"{g * mu0:g}" for g in gammas)
                    + ") before converting, or edit the emitted card.")


def _emit_fail_tab2(fail: FailGissmo, state: ConversionState) -> List[str]:
    """*MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2 (GISSMO). Layout from
    FAIL/fail_tab2.cfg FORMAT(radioss2022). LS-DYNA's sign convention (negative =
    curve id) is resolved into the TAB2 function slots. The referenced curves
    (LCSDG/LCREGD/LCSRS + a curve-valued ECRIT/FADEXP) are ordinary /FUNCT ids —
    TAB2's table fields accept a function id for the 1-D case."""
    blank = " " * 10
    # NUMFIP: >0 → failed integration points (solids); <0 → % thru-thickness (shells)
    failip = int(round(fail.numfip)) if fail.numfip > 0 else 1
    pthk   = abs(fail.numfip) if fail.numfip < 0 else 0.0
    # ECRIT<0 → instability curve; ECRIT>0 → fixed instability strain (no direct
    # TAB2 fixed slot — carried as the ECRIT scale, warn).
    if fail.ecrit < 0:
        inst_id, ecrit_scale = int(-fail.ecrit), 1.0
    else:
        inst_id, ecrit_scale = 0, 0.0
        if fail.ecrit > 0:
            state.warn(f"/FAIL/TAB2/{fail.mid}: LS-DYNA ECRIT={fail.ecrit} is a "
                       "fixed instability strain; TAB2 expects an instability "
                       "curve (INST_ID). Supply a curve or verify the criterion.")
    # FADEXP<0 → fading-exponent curve; >0 → constant exponent
    if fail.fadexp < 0:
        fct_exp, exp = int(-fail.fadexp), 1.0
    else:
        fct_exp, exp = 0, (fail.fadexp if fail.fadexp else 1.0)
    tab_el = fail.lcregd
    ireg   = 1 if tab_el else 0
    fct_sr = int(abs(fail.lcsrs)) if fail.lcsrs else 0
    return [
        f"/FAIL/TAB2/{fail.mid}",
        "#  EPSF_ID               FCRIT              FAILIP          PTHICKFAIL",
        f"{_i(fail.lcsdg)}{_f(1.0)}{blank}{_i(failip)}{_f(pthk)}",
        "#                  N               DCRIT   INST_ID               ECRIT",
        f"{_f(fail.dmgexp)}{_f(fail.dcrit)}{_i(inst_id)}{_f(ecrit_scale)}",
        "#  FCT_EXP             EXP_REF                 EXP",
        f"{_i(fct_exp)}{_f(0.0)}{_f(exp)}",
        "#   TAB_EL      IREG              EL_REF             SR_REF1           FSCALE_EL",
        f"{_i(tab_el)}{_i(ireg)}{_f(0.0)}{_f(0.0)}{_f(1.0)}",
        "#               SHRF               BIAXF",
        f"{_f(0.0)}{_f(0.0)}",
        "#   FCT_SR             SR_REF2           FSCALE_SR             C_JCOOK",
        f"{_i(fct_sr)}{blank}{_f(0.0)}{_f(1.0)}{_f(0.0)}",
        # Card 7 (FCT_DLIM / FSCALE_DLIM) is mandatory: without it the starter
        # reads into the next block ("card is missing", WARNING 100217) and the
        # truncated /FAIL/TAB2 loses its material link (WARNING 3050, failure
        # ignored). No damage-limit function here, so FCT_DLIM=0.
        "# FCT_DLIM         FSCALE_DLIM",
        f"{_i(0)}{_f(0.0)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: functions
# ─────────────────────────────────────────────────────────────────────────────

def _make_functions(state: ConversionState) -> List[str]:
    tables_2d = {tbid: t for tbid, t in state.define_tables.items()
                 if t.resolved and t.rows}
    if not state.curves and not tables_2d:
        return []
    table_ids = getattr(state, "table_1d_ids", set())
    lines = ["#-  FUNCTIONS:", HDR]
    for lcid, curve in sorted(state.curves.items()):
        if lcid in table_ids:
            # A curve a law consumes through a TABLE slot (LAW76's yield curves,
            # LAW52's Tab_ID) must be /TABLE (1D). Layout from CURVE/table_1.cfg:
            # header, title, a "#dimension" card carrying ORDER (=1 for 1D), then
            # the X-Y pairs. Omitting the dimension card triggers starter ERROR 777.
            lines += [
                f"/TABLE/1/{lcid}",
                curve.title or f"TABLE_{lcid}",
                "#dimension",
                f"{_i(1)}",
                "#                  X                   Y",
            ]
        else:
            lines += [
                f"/FUNCT/{lcid}",
                curve.title or f"FUNCT_{lcid}",
                "#                  X                   Y",
            ]
        for a, o in curve.pts:
            lines.append(f"{_f(a)}{_f(o)}")
        lines.append(HDR)
    for tbid, tab in sorted(tables_2d.items()):
        # *DEFINE_TABLE[_2D] → 2-D /TABLE/1. Layout from CURVE/table_1.cfg
        # FORMAT(radioss110) (unchanged through /BEGIN 2022): header, title,
        # "#dimension" card = 2, then one row per entry:
        #   fct_ID(%10d) blank(10) A(%20lg) blank(40) Scale_y(%20lg).
        # Rows were sorted ascending by A in _resolve_define_tables.
        lines += [
            f"/TABLE/1/{tbid}",
            tab.title or f"TABLE_{tbid}",
            "#dimension",
            f"{_i(2)}",
            "#  fct_ID1                             A                                                    Scale_y1",
        ]
        for a, lcid in tab.rows:
            lines.append(f"{_i(lcid)}{' ' * 10}{_f(a)}{' ' * 40}{_f(1.0)}")
        lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Post-processing: resolve auto-generated function IDs for LAW36
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_define_tables(state: ConversionState) -> None:
    """Finalize *DEFINE_TABLE[_2D] entries before materials consume them.

    * Legacy *DEFINE_TABLE (bare VALUE rows): LS-DYNA requires the table's
      curves to be the *DEFINE_CURVE blocks immediately FOLLOWING it in the
      deck, so pair value i with the i-th curve parsed after the table (capped
      at the next legacy table's position). Too few following curves → warn +
      skip the table (resolved stays False; a material referencing it falls
      back to bilinear hardening with its own warning).
    * All tables: drop rows whose LCID has no parsed *DEFINE_CURVE, then sort
      rows ascending by the 2nd-dimension abscissa A (OpenRadioss requires a
      monotonic entry list).
    """
    tables = state.define_tables
    if not tables:
        return
    legacy = sorted((t for t in tables.values() if not t.resolved),
                    key=lambda t: t.curve_seq)
    bounds = [t.curve_seq for t in legacy[1:]] + [len(state.curve_order)]
    for tab, bound in zip(legacy, bounds):
        cands = state.curve_order[tab.curve_seq:bound]
        n = len(tab.pending_values)
        if len(cands) < n:
            state.warn(
                f"*DEFINE_TABLE tbid={tab.tbid}: legacy form lists {n} "
                f"value(s) but only {len(cands)} *DEFINE_CURVE(s) follow it "
                "in the deck — cannot pair values with curves; table skipped.")
            continue
        tab.rows = list(zip(tab.pending_values, cands[:n]))
        tab.resolved = True
        state.warn(
            f"*DEFINE_TABLE tbid={tab.tbid}: legacy form resolved "
            f"positionally — paired its {n} value(s) with the {n} "
            f"*DEFINE_CURVE(s) defined immediately after it "
            f"(lcid {', '.join(str(c) for c in cands[:n])}). Verify the "
            "curve order in the source deck matches the value order.")
    for tab in tables.values():
        if not tab.resolved:
            continue
        good = [(a, lc) for a, lc in tab.rows if lc in state.curves]
        bad = [lc for _, lc in tab.rows if lc not in state.curves]
        if bad:
            state.warn(
                f"*DEFINE_TABLE tbid={tab.tbid}: dropped row(s) referencing "
                f"undefined curve(s) {sorted(set(bad))}.")
        if not good:
            state.warn(
                f"*DEFINE_TABLE tbid={tab.tbid}: no usable rows — skipped.")
            tab.resolved = False
            tab.rows = []
            continue
        tab.rows = sorted(good)


def _resolve_mat_plas_tab(state: ConversionState) -> None:
    for mat in state.mat_plas_tab.values():
        if mat.C:
            state.warn(
                f"*MAT mid={mat.mid}: Cowper-Symonds strain-rate parameters "
                f"(C={mat.C:g}, P={mat.P:g}) have no /MAT/LAW36 mapping — "
                "converted rate-independent.")

        # Pre-sampled Johnson-Cook rate curves (MAT_098, C != 0) → one auto
        # /FUNCT per reference rate, collected as the LAW36 function family.
        if mat.rate_curves and not mat.rate_fcts:
            for eps_dot, pts in sorted(mat.rate_curves):
                fid = state.next_id()
                _add_auto_curve(
                    state, fid, f"Auto_JC_mid{mat.mid}_rate{eps_dot:g}", pts)
                mat.rate_fcts.append((fid, 1.0, eps_dot))
        if mat.rate_fcts or mat.funct_id:
            continue

        # LCSS pointing at a *DEFINE_TABLE (rate-dependent MAT_024): expand
        # the table into the LAW36 rate-function family — fct_ID_i = the
        # table's curves, Eps_dot_i = the table's strain-rate values.
        tab = state.define_tables.get(mat.lcss) if mat.lcss > 0 else None
        if tab is not None:
            if tab.resolved and tab.rows:
                mat.rate_fcts = [(lcid, 1.0, a) for a, lcid in tab.rows]
                state.warn(
                    f"*MAT mid={mat.mid}: LCSS={mat.lcss} is a *DEFINE_TABLE "
                    f"— expanded into a /MAT/LAW36 rate-function family of "
                    f"{len(tab.rows)} curves (Eps_dot = "
                    f"{', '.join(f'{a:g}' for a, _ in tab.rows)}).")
                continue
            state.warn(
                f"*MAT mid={mat.mid}: LCSS={mat.lcss} references a "
                "*DEFINE_TABLE that could not be resolved — falling back to "
                "SIGY/ETAN bilinear hardening.")
            mat.lcss = 0

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
            # LAW36's yield table is stress vs PLASTIC strain, while ETAN is the
            # tangent modulus vs TOTAL strain — convert to the plastic-hardening
            # slope H = E·ETAN/(E−ETAN) (same correction the LAW44 path applies).
            etan = mat.etan
            if 0.0 < etan < mat.E:
                etan = mat.E * etan / (mat.E - etan)
            pts = [(0.0, sigy), (1.0, sigy + etan)]
            fid = state.next_id()
            _add_auto_curve(state, fid, f"Auto_SY_ET_mid{mat.mid}", pts)
            mat.funct_id = fid

    _resolve_plas_tab_lcsr(state)


# LS-DYNA keyword families whose LCSR (yield-stress scale factor vs strain
# rate) k2rad expands into a LAW36 rate-function family. MAT_024/123 are
# deliberately NOT in the set: their LCSR handling is unchanged, so no existing
# deck's output moves.
_LCSR_FAMILIES = ("081", "082", "105")


def _resolve_plas_tab_lcsr(state: ConversionState) -> None:
    """LCSR → the /MAT/LAW36 rate-function family, for the families that carry
    a usable one (*MAT_081/082, *MAT_105).

    LS-DYNA's LCSR is a SCALE FACTOR as a function of strain rate applied to
    the single static yield curve (Vol II R17 p.2-606 remark 1b). LAW36 has no
    such multiplier, but its rate family is a list of (function, ordinate
    scale, strain rate) triples — so the identical law is expressed by
    repeating the ONE static function once per LCSR point with that point's
    ordinate as the scale. This is dyna2rad's construction
    (convertmats.cxx:1417-1459) without its SFA/SFO double-scaling, since
    k2rad's curve reader has already applied the *DEFINE_CURVE scale factors.

    A table LCSS wins over LCSR in LS-DYNA itself ("C, P, LCSR ... are ignored
    if a table ID is defined", p.2-604), so a material that already has a rate
    family from its table is left alone and reported.
    """
    for mat in state.mat_plas_tab.values():
        if mat.family not in _LCSR_FAMILIES or mat.lcsr <= 0:
            continue
        kw = {"081": "*MAT_081", "082": "*MAT_082"}.get(mat.family, "*MAT_105")
        if mat.rate_fcts:
            state.warn(
                f"{kw} {mat.mid}: LCSR={mat.lcsr} is ignored because LCSS is a "
                "*DEFINE_TABLE that already gives the yield curve per strain "
                "rate — LS-DYNA ignores LCSR in exactly the same case.")
            continue
        if not mat.funct_id:
            state.warn(
                f"{kw} {mat.mid}: LCSR={mat.lcsr} scales a static yield curve, "
                "but this material has no single yield function to scale — "
                "LCSR is DROPPED and the material converts rate-independent.")
            continue
        crv = state.curves.get(mat.lcsr)
        if crv is None or len(crv.pts) < 2:
            state.warn(
                f"{kw} {mat.mid}: LCSR={mat.lcsr} references a *DEFINE_CURVE "
                "that is not in the deck (or has fewer than 2 points) — the "
                "strain-rate scaling is DROPPED and the material converts "
                "rate-independent.")
            continue
        pts = sorted(crv.pts)
        mat.rate_fcts = [(mat.funct_id, scale, rate) for rate, scale in pts]
        mat.funct_id = 0
        state.warn(
            f"{kw} {mat.mid}: LCSR={mat.lcsr} (yield-stress scale factor vs "
            f"strain rate) expanded into a /MAT/LAW36 rate-function family of "
            f"{len(pts)} entries — the same static yield function repeated at "
            f"Eps_dot = {', '.join(f'{r:g}' for r, _ in pts)} with that "
            "curve's ordinate as Fscale.")


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
    state.curves[fid] = Curve(
        lcid=fid, title=title,
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
        pts=pts,
    )
