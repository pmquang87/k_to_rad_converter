"""Starter materials: /MAT laws, EOS, failure cards, /FUNCT curves and table resolution."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
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
    MatSoilAndFoam,
    MatLowDensityViscousFoam,
    MatModifiedHoneycomb,
    MatDeshpandeFleckFoam,
    MatHillFoam,
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
    MatCohesiveMixedMode,
    MatArupAdhesive,
    MatCohesiveMMEPR,
    MatToughenedAdhesive,
    FailDiem,
    MatTabulatedJC,
    MatJHCeramics,
    MatJHConcrete,
    MatElasticFluid,
    AutoTable,
    Curve,
    MatHighExplosiveBurn,
    EosJwl,
    EosCard,
    MatShapeMemory,
    MatCWM,
    MatElasticPlasticThermal,
    MatElasticPlasticHydro,
    MatLaw3,
    MatLaw106,
    MatVacuum,
)
from .common import (HDR, _elform_to_isolid, _f, _i, _part_node_sets,
                     _ref_flag_materials, _spotweld_beam_pids)
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
    "_resolve_mat_foams",
    "_emit_mat_law21",
    "_emit_mat_law90",
    "_emit_mat_law50_modified",
    "_emit_mat_law115",
    "_emit_mat_law62",
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
    "_emit_mat_law117",
    "_emit_mat_law169",
    "_emit_mat_law116",
    "_emit_mat_law120",
    "_emit_fail_inievo",
    "_resolve_mat_adhesives",
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
    "_emit_mat_law109",
    "_emit_mat224_tab1",
    "_resolve_mat_tabulated_jc",
    "_emit_mat_law79",
    "_emit_mat_law126",
    "_emit_mat_elastic_fluid",
    "_resolve_mat_impact",
    "_resolve_define_tables_3d",
    "_make_functions",
    "_resolve_define_tables",
    "_resolve_mat_plas_tab",
    "_resolve_mat_power_law",
    "_add_auto_curve",
    # Rare materials batch
    "_resolve_mat_shape_memory",
    "_emit_mat_law71",
    # R14 triage batch, round 1
    "_resolve_mat_law106",
    "_emit_mat_law106",
    "_interp_table",
    "_resolve_mat_law3",
    "_emit_mat_law3",
    "_emit_fail_spalling",
    "_emit_mat_vacuum",
    "_warn_refused_materials",
    "_resolve_he_bunreacted",
    "_ammg_member_mids",
    "_jwl_unreacted_bulk",
    "_apply_zero_density_floor",
    "_ZERO_DENSITY_FLOOR",
    "_resolve_ale_submaterials",
    "_submaterial_has_eos",
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
    # The SPH twins of the LAW44 cards above (see _emit_plas_kin_as_law2).
    lines += _emit_sph_mat_clones(state)
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
    # *MAT_VACUUM lands on the SAME /MAT/VOID: a region that carries no stress
    # at all. It exists so the vacuum *PART resolves (ERROR 179 otherwise);
    # _resolve_ale_submaterials keeps it OUT of the /MAT/LAW51 phase list,
    # where Radioss's void is the undeclared balance of the volume fractions.
    for vac in state.mat_vacuum.values():
        lines += _emit_mat_vacuum(vac)
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
    # Foam batch (curve synthesis, slot wiring and every semantic warning are
    # resolved by _resolve_mat_foams; MAT_126's orthotropic /PROP/TYPE6 lives
    # in writer/composites.py like the other material-driven ortho props)
    for mat in state.mat_soil_and_foam.values():
        lines += _emit_mat_law21(mat)
        if mat.latched_tension_failure:
            lines += _emit_fail_spalling(mat.mid, mat.pc)
    for mat in state.mat_low_density_viscous_foam.values():
        lines += _emit_mat_law90(mat)
    for mat in state.mat_modified_honeycomb.values():
        lines += _emit_mat_law50_modified(mat)
    for mat in state.mat_deshpande_fleck.values():
        lines += _emit_mat_law115(mat)
    for mat in state.mat_hill_foam.values():
        lines += _emit_mat_law62(mat)
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
    # Adhesives / cohesive batch (curve wiring resolved by
    # _resolve_mat_adhesives; the cohesive /PROP/TYPE43 routing lives in
    # writer/mesh.py::_make_properties)
    for mat in state.mat_cohesive_mixed_mode.values():
        lines += _emit_mat_law117(mat, state)
    for mat in state.mat_arup_adhesive.values():
        lines += _emit_mat_law169(mat, state)
    for mat in state.mat_cohesive_mm_epr.values():
        lines += _emit_mat_law116(mat, state)
    for mat in state.mat_toughened_adhesive.values():
        lines += _emit_mat_law120(mat, state)
    # Tabulated Johnson-Cook batch (every curve/table routing decision and
    # warning is resolved by _resolve_mat_tabulated_jc; the /FAIL/TAB1 rides
    # the same MID like the MAT_081 pattern, and only when a usable LCF
    # exists — deliberately unlike dyna2rad's unconditional /FAIL/TAB2,
    # which is starter ERROR 3000 on an LCF-less deck)
    for mat in state.mat_tabulated_jc.values():
        lines += _emit_mat_law109(mat)
        if mat.emit_fail:
            lines += _emit_mat224_tab1(mat)
    # Impact / blast batch (guards, the EPS0 substitution, FS -> IDEL and every
    # warning are resolved by _resolve_mat_impact). Neither Johnson-Holmquist
    # law takes an /EOS — K1/K2/K3 are their own polynomial pressure law — but
    # the fluid ALWAYS carries one, emitted inline by its own emitter so the
    # /MAT and its same-id /EOS/POLYNOMIAL stay adjacent.
    for mat in state.mat_jh_ceramics.values():
        lines += _emit_mat_law79(mat)
    for mat in state.mat_jh_concrete.values():
        lines += _emit_mat_law126(mat)
    for mat in state.mat_elastic_fluid.values():
        lines += _emit_mat_elastic_fluid(mat)
    # Rare materials batch. *MAT_156 / *MAT_S15 have no loop here on purpose:
    # both live entirely inside a /PROP/TYPE46 (writer/loads.py) and emit no
    # /MAT at all, exactly like the *MAT_Sxx spring family.
    for mat in state.mat_shape_memory.values():
        lines += _emit_mat_law71(mat)
    # R14 triage batch: *MAT_004 and *MAT_270 both land on /MAT/LAW106, and
    # both are routed by _resolve_mat_law106 into the single resolved registry
    # this loop reads — a source card the resolver refused leaves no entry, so
    # its /PART reports a dangling material rather than getting a half-built
    # card. The matching /THERM_STRESS/MAT + /HEAT/MAT pair is written by the
    # thermal section (both are keyed on the material id).
    for law106 in state.mat_law106.values():
        lines += _emit_mat_law106(law106)
    # *MAT_010 -> /MAT/LAW3 + the same-id /EOS, emitted TOGETHER (Radioss binds
    # an equation of state to the material of the same id) exactly as the LAW4
    # HYD_JCOOK route does. _law3_consumed_eos_ids keeps the orphan-EOS arm of
    # _make_explosive_and_eos_materials from claiming the same id a second
    # time — or, worse, telling the reader the EOS was not emitted (#129).
    for law3 in state.mat_law3.values():
        lines += _emit_mat_law3(law3, state)
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
    # *MAT_ADD_DAMAGE_DIEM rides the same rider pattern: an independent /FAIL
    # entity bound by the trailing mat id, so it coexists with a /FAIL/TAB2
    # (GISSMO) and/or /FAIL/GENE1 (ADD_EROSION) on the same MID — different
    # /FAIL types on one material are legal in Radioss.
    for diem in state.fail_diem.values():
        lines += _emit_fail_inievo(diem, state)
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
        f"{_f(0.0)}{_f(0.0)}{_f(heb.bunreacted)}",
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
    # An *EOS_* emitted BESIDE a /MAT/LAW3 is likewise not an orphan: it is
    # written by _emit_mat_law3 under the same id. Without this the owner arm
    # below would tell the reader "the equation of state was NOT emitted"
    # about one this converter does write (#129) — measured on the three
    # *MAT_ELASTIC_PLASTIC_HYDRO corpus decks.
    jc_consumed |= _law3_consumed_eos_ids(state)
    # ... and the ids the impact/blast batch already owns, which the shared-id
    # carrier convention below must not claim a second time (ERROR 79).
    impact_claimed = _impact_claimed_mids(state)
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
            # ── A BARE *EOS_* — no *MAT_NULL of its id, no *PART EOSID ─────
            #
            # k2rad used to mint a /MAT/LAW6 CARRIER under the EOS id here.
            # That branch is removed: it could never produce a runnable pair,
            # and on a colliding id it produced an UNRUNNABLE one.
            #
            #   * No density exists to give it. NONE of the three *EOS_*
            #     spellings k2rad reads carries a density cell — LS-DYNA takes
            #     the density from the *PART's own *MAT (Vol I R17 p.37-6,
            #     EOSID "Nonzero only for solid elements using an equation of
            #     state to compute pressure") — so every handler stores
            #     ``rho0 = 0.0`` and the carrier's RHO_I was structurally 0.
            #     /MAT/LAW6 is NOT in the density exemption list at
            #     ``hm_read_mat.F90:1575-1583`` (only laws 0/20/51/151/108/999
            #     are), so RHO_I 0 is starter ``ERROR ID : 683 ... DENSITY IS
            #     LESS THAN OR EQUAL TO ZERO`` and the deck is refused.
            #     MEASURED on twin probes a_rho0 / a_rho0b: the /EOS reference
            #     density does not rescue the /MAT either.
            #   * On a colliding id it ALSO cost an ERROR 79. The old guard was
            #     a hand-kept list of three families (_impact_claimed_mids), so
            #     any OTHER family's id went straight through — measured on
            #     dynaexamples_r14/ale-s-ale/s-ale/wavestructure/2Dlag.k, whose
            #     orphan *EOS_LINEAR_POLYNOMIAL 3 sits on a *MAT_JOHNSON_COOK:
            #     ``/MAT/LAW4/3`` AND ``/MAT/HYD_VISC/3`` (ERROR 79, IN
            #     MATERIAL DEFINITION) plus ``/EOS/GRUNEISEN/3`` AND
            #     ``/EOS/POLYNOMIAL/3``, which hm_read_eos.F does not diagnose
            #     at all (no UDOUBLE anywhere in it) — the second block
            #     silently replaces the material's real pressure law.
            #   * And dropping is FAITHFUL, not a loss: an *EOS_* that no
            #     *PART names through its EOSID field is unused by LS-DYNA
            #     too, and dyna2rad never converts one either
            #     (convertmats.cxx:572 reaches the EOS only from a *PART).
            #
            # So the two arms below both refuse; the collision arm is first
            # because naming the id's real owner is the more actionable
            # message. _warn_duplicate_eos_ids covers what neither can see.
            owner = _mat_namespace_owner(state, eosid)
            if owner:
                if eosid in state.mat_elastic_fluid:
                    why = ("that material already emits its OWN "
                           f"/EOS/POLYNOMIAL/{eosid} built from the card's "
                           "bulk modulus K, which IS the fluid's pressure law")
                elif eosid in impact_claimed:
                    why = ("that law computes pressure from its own K1/K2/K3 "
                           "polynomial and declares no EOS class, so it "
                           "neither needs nor accepts a companion /EOS")
                else:
                    why = ("a /MAT id is ONE starter table across every "
                           "material law (hm_read_mat.F90:1613 checks the "
                           "merged table)")
                state.warn(
                    f"{eos.label()}: id {eosid} is already held by "
                    f"a {owner}, and {why}. The equation of state was NOT "
                    "emitted and no /MAT/LAW6 carrier was created — doing "
                    "either would put a SECOND /MAT under id "
                    f"{eosid} (starter ERROR 79, DUPLICATE ID, IN MATERIAL "
                    "DEFINITION) and, worse, a second /EOS: hm_read_eos.F has "
                    "no duplicate check at all, so a second /EOS is accepted "
                    "at 0 ERROR / 0 WARNING and SILENTLY REPLACES that "
                    "material's equation of state (last block wins). Note "
                    "k2rad's shared-id pairing is a "
                    "convenience convention: in LS-DYNA an *EOS_* binds only "
                    "through the *PART EOSID field, so a material that does "
                    "not name this EOS has no EOS at all. Renumber the "
                    "*EOS_* if it was meant for a different material.")
                continue
            # A *PART whose MID is this id means the deck DOES have a material
            # here and this converter did not convert it — the actionable
            # fact, and the one the reader needs instead of "add a *MAT_NULL".
            # MEASURED on three corpus decks (sph/bar-iv/taylor1.k, bar-v/
            # taylor2.k, sieve/hvi.k): each pairs *MAT_ELASTIC_PLASTIC_HYDRO
            # with an *EOS_GRUNEISEN of the same id, that material is a
            # SKIPPED keyword, and the carrier used to fill the hole with a
            # zero-density /MAT/HYD_VISC — a viscous fluid standing in for an
            # elastic-plastic hydrodynamic solid, which the starter refused
            # for its density (ERROR 683) rather than for being the wrong
            # law. Without the carrier the /PART dangles and
            # _warn_dangling_part_materials names it, which is the true
            # diagnosis: the deck's own material never arrived.
            owners = sorted({p.pid for p in state.parts.values()
                             if p.mid == eosid})
            state.warn(
                f"{eos.label()}: no *MAT_NULL of that id and no "
                "*PART binds it through an EOSID field, so there is no "
                f"material to attach it to — neither /MAT/HYD_VISC/{eosid} "
                f"nor /EOS/{eos.kind}/{eosid} was emitted. A synthesized "
                "/MAT/LAW6 carrier is not an option: no *EOS_* keyword "
                "carries a density (LS-DYNA takes it from the *PART's *MAT), "
                "and a /MAT/LAW6 with RHO_I 0 is starter ERROR 683 (DENSITY "
                "IS LESS THAN OR EQUAL TO ZERO), which refuses the whole "
                "deck. "
                + (f"NOTE *PART(s) {owners} name {eosid} as their MID, so "
                   "this deck DOES state a material here and it is this "
                   "converter that did not produce one — check the skipped-"
                   "keyword list for the *MAT_* card of that id. Until it "
                   "converts, those parts have no /MAT and the starter stops "
                   "with ERROR 179; a /MAT/LAW6 carrier would only have "
                   "substituted a VISCOUS FLUID for whatever law the deck "
                   "actually states."
                   if owners else
                   "Nothing physical is lost: LS-DYNA does not use this EOS "
                   "either. Add a same-id *MAT_NULL (with RO), or name the "
                   "EOS from a *PART's EOSID field, to get the fluid."))
            continue
        _derive_ideal_gas_p0(state, eos, state.mat_null[null_mids[0]].rho)
        for mid in null_mids:
            carrier = state.mat_null[mid]
            lines += _emit_mat_law6_carrier(mid, carrier.title, carrier.rho)
            if mid == eosid:
                lines += _emit_eos(eos)
            else:
                state.warn(
                    f"{eos.label()}: bound to *MAT_NULL {mid} via "
                    f"a *PART EOSID — emitted as /EOS/{eos.kind}/{mid} on "
                    "the /MAT/LAW6 carrier of that id (Radioss binds an "
                    "/EOS to the material of the SAME id).")
                lines += _emit_eos(EosCard(eosid=mid, kind=eos.kind,
                                           params=eos.params, rho0=eos.rho0,
                                           note=eos.note,
                                           keyword=eos.keyword))
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


def _emit_mat_vacuum(mat: MatVacuum) -> List[str]:
    """``*MAT_VACUUM`` → ``/MAT/VOID`` — the same card a bare ``*MAT_NULL``
    takes, under the vacuum material's own id.

    ``RHO_I`` is written verbatim, ``0.0`` included: ``hm_read_mat.F90:
    1575-1583`` exempts law 0 from ``ERROR 683``, so a corpus deck stating
    ``RHO = 0`` (``ale_wavehitcol.k``) needs no density substitution.
    """
    return [
        f"/MAT/VOID/{mat.mid}",
        mat.title or f"VACUUM_{mat.mid}",
        "#              RHO_I                   E                  nu",
        f"{_f(mat.rho)}{_f(0.0)}{_f(0.0)}",
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
                f"but {state.eos_cards[mat.mid].label()} shares "
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


def _impact_claimed_mids(state: ConversionState) -> set:
    """Material ids owned by the impact/blast batch, whose EOS-adjacency
    deserves a SPECIFIC "why" in the bare-*EOS_* refusal.

    This used to be the GUARD on the standalone /MAT/LAW6 carrier, and as a
    guard it was the #124 class: a hand-kept list of three families standing in
    for the semantic quantity "does any other emitter put a /MAT under this
    id?". Measured miss: ``2Dlag.k``'s orphan ``*EOS_LINEAR_POLYNOMIAL 3``
    sits on a ``*MAT_JOHNSON_COOK`` — in none of the three — and the carrier
    went straight through into a duplicate ``/MAT`` (ERROR 79) and a duplicate
    ``/EOS`` (undiagnosed). :func:`_mat_namespace_owner` is the guard now, over
    the whole converted-*MAT namespace; this set only refines the message,
    because these three families are the ones a reader would expect to PAIR
    with an EOS: both Johnson-Holmquist laws compute pressure from their own
    K1/K2/K3 polynomial and declare no EOS class, and the elastic fluid
    already emits its OWN /EOS/POLYNOMIAL under its mid.
    """
    return (set(state.mat_jh_ceramics) | set(state.mat_jh_concrete)
            | set(state.mat_elastic_fluid))


def _mat_namespace_owner(state: ConversionState, mid: int) -> str:
    """Which converted *MAT family already owns ``/MAT/<law>/<mid>``, as a
    human-readable "*KEYWORD -> /MAT/LAWn" phrase, or "" when the id is free.

    The generalisation of :func:`_impact_claimed_mids`, which is a hand-kept
    list of THREE families. The screen the carrier needs is the SEMANTIC
    quantity — "does any other emitter put a /MAT under this id?" — not a
    family list, because a /MAT id is ONE starter table across every law
    (``hm_read_mat.F90:1613`` runs ``vdouble(ipm(1,1), ..., 'MATERIAL
    DEFINITION')`` over the merged table, ERROR 79 at ``sysfus.F:938``) and
    every k2rad material emitter writes the LS-DYNA MID verbatim. Measured on
    ``dynaexamples_r14/ale-s-ale/s-ale/wavestructure/2Dlag.k``: the deck's
    ``*EOS_LINEAR_POLYNOMIAL 3`` is claimed by neither Johnson-Holmquist law
    nor an elastic fluid, so the three-family guard let the carrier through
    and the deck came out with ``/MAT/LAW4/3`` AND ``/MAT/HYD_VISC/3`` —
    starter ``ERROR ID : 79 ... IN MATERIAL DEFINITION ID=3 is DUPLICATED``.

    ``all_mat_ids()`` is the whole converted-*MAT namespace, so the answer is
    exhaustive by construction; the per-family lookups below only make the
    message name the owner. (#124 class: gate on the semantic quantity, not
    the card name.)"""
    if mid not in state.all_mat_ids():
        return ""
    named = (
        (state.mat_jh_ceramics, "*MAT_JOHNSON_HOLMQUIST_CERAMICS -> /MAT/LAW79"),
        (state.mat_jh_concrete, "*MAT_JOHNSON_HOLMQUIST_CONCRETE -> /MAT/LAW126"),
        (state.mat_elastic_fluid, "*MAT_ELASTIC_FLUID -> /MAT/LAW6"),
        (state.mat_johnson_cook, "*MAT_JOHNSON_COOK -> /MAT/LAW2 or /MAT/LAW4"),
        (state.mat_high_explosive, "*MAT_HIGH_EXPLOSIVE_BURN -> /MAT/LAW5"),
        (state.mat_null, "*MAT_NULL -> /MAT/VOID or /MAT/LAW6"),
        (state.mat_rigid, "*MAT_RIGID -> /MAT/ELAST"),
        (state.mat_elastic, "*MAT_ELASTIC -> /MAT/ELAST"),
    )
    for reg, label in named:
        if mid in reg:
            return label
    return "another converted *MAT card"


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
                f"{eos.label()} is emitted as "
                f"/EOS/{eos.kind}/{mat.mid} — Radioss binds an /EOS to the "
                "material of the SAME id.")
        lines += _emit_eos(EosCard(eosid=mat.mid, kind=eos.kind,
                                   params=eos.params, rho0=eos.rho0,
                                   note=eos.note, keyword=eos.keyword))
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


def _plas_kin_b(mat: MatPlasKin) -> float:
    """LS-DYNA ETAN is the tangent modulus of the bilinear TOTAL stress-strain
    curve; LAW44's (and LAW2's) ``b`` with ``n = 1`` is dSigma/dEps_PLASTIC, so
    the plastic hardening modulus ``H = E*ETAN/(E-ETAN)`` is what carries
    through, not raw ETAN."""
    return (mat.E * mat.etan / (mat.E - mat.etan)
            if 0.0 < mat.etan < mat.E else mat.etan)


def _sph_only_mid(state: ConversionState, mid: int) -> bool:
    """True when EVERY *PART on *mid* carries SPH particles (and at least one
    does) — the case where the material can simply BE LAW2, with no clone."""
    pids = [pid for pid, p in state.parts.items() if p.mid == mid]
    if not pids:
        return False
    sph_pids = {c.pid for c in state.sph_elems}
    return all(pid in sph_pids for pid in pids)


def _plas_kin_law2_expressible(mat: MatPlasKin) -> bool:
    """Can this *MAT_PLASTIC_KINEMATIC be written as /MAT/LAW2 with NOTHING
    lost? See :func:`_emit_plas_kin_as_law2` for what the two exclusions are.

    The single expressibility test. Read by the emitter, by
    ``mesh._target_mat_law`` (which is what ``writer/sph.py``'s ERROR-3046
    report keys on) and by ``sph._resolve_sph_materials`` (which decides
    whether to clone), so a disagreement between any two of them would either
    warn about a refusal the deck no longer earns or stay quiet about one it
    does.
    """
    if mat.src or mat.srp:
        return False                    # Cowper-Symonds: no LAW2 column
    return not (mat.beta < 1.0 and _plas_kin_b(mat) > 0.0)


def _plas_kin_law2_eligible(state: ConversionState, mat: MatPlasKin) -> bool:
    """Does this *MAT_PLASTIC_KINEMATIC become LAW2 UNDER ITS OWN ID?

    ONE reason today: an SPH part, because LAW44 is not SPH-declared and the
    starter answers a particle on it with ERROR 3046.

    An ``*ALE_MULTI-MATERIAL_GROUP`` member looks like a second reason — LAW44
    is not on ``fill_buffer_51.F:210``'s allowed phase list either — and it is
    NOT, because a restatement could never make such a material a legal phase:
    ``:281`` refuses any non-explosive submaterial whose ``EOS_TYPE`` is 0 with
    ``MISSING SUBMATERIAL EOS``, and a ``*MAT_PLASTIC_KINEMATIC`` carries no
    equation of state in this converter or in the deck. MEASURED on
    ``cylinder_impact_A``, whose restated LAW2 phase answered BOTH
    ``SUBMATERIAL EOS IS NOT COMPATIBLE WITH MATERIAL LAW 51`` and ``MISSING
    SUBMATERIAL EOS``. So the phase is dropped by name instead
    (``_resolve_ale_submaterials``) and the material keeps LAW44, which is what
    its Lagrangian side needs anyway.
    """
    return _sph_only_mid(state, mat.mid) and _plas_kin_law2_expressible(mat)


def _emit_sph_mat_clones(state: ConversionState) -> List[str]:
    """The extra /MAT/LAW2 cards ``sph._resolve_sph_materials`` asked for — one
    per *MAT_PLASTIC_KINEMATIC shared between SPH and non-SPH parts."""
    lines: List[str] = []
    for mid, clone_id in sorted(state.sph_mat_clones.items()):
        mat = state.mat_plas_kin.get(mid)
        if mat is None:
            continue
        lines += _emit_plas_kin_as_law2(mat, state, clone_id=clone_id)
    return lines


def _emit_mat_law44(mat: MatPlasKin, state: ConversionState) -> List[str]:
    if _plas_kin_law2_eligible(state, mat):
        return _emit_plas_kin_as_law2(mat, state)
    b = _plas_kin_b(mat)
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


def _emit_plas_kin_as_law2(mat: MatPlasKin, state: ConversionState,
                           clone_id: int = 0) -> List[str]:
    """*MAT_PLASTIC_KINEMATIC → /MAT/LAW2, for the SPH parts that need it.

    Two ways in, both gated on :func:`_plas_kin_law2_expressible`:

    * ``clone_id = 0`` — every *PART on the material carries particles, so the
      material simply IS LAW2 under its own MID;
    * ``clone_id > 0`` — the material is SHARED with shells or solids, which
      still need LAW44, so a SECOND /MAT card is written under a synthesized id
      and only the SPH parts are repointed at it (``sph._resolve_sph_materials``
      allocates the id and does the repointing). The clone is not an
      approximation of the original: the expressibility gate is exactly the
      condition under which LAW2 and LAW44 describe the SAME curve, so the two
      cards are one material written twice.

    /MAT/LAW44 (COWPER) is the faithful target for this keyword everywhere
    else, and it stays the target everywhere else. But ``hm_read_mat44.F``
    declares BEAM_ALL / ELASTO_PLASTIC / EOS / INCREMENTAL / LARGE_STRAIN /
    SHELL_ISOTROPIC / SOLID_ISOTROPIC / TRUSS and NOT ``"SPH"``, so
    ``check_mat_elem_prop_compatibility.F`` refuses the whole deck with
    **ERROR 3046** ("ELEMENTS OF TYPE SPH ARE NOT COMPATIBLE WITH MATERIAL ID
    ... OF TYPE 44") the moment a particle sits on it. Two decks in the r14
    corpus do exactly that (``sph/bar-i/bar1.k``, ``sph/bar-ii/bar2.k``) and
    LS-DYNA runs both.

    /MAT/LAW2 (PLAS_JOHNS) IS SPH-declared (``mat002/hm_read_mat02_jc.F90:383``)
    and expresses the same law EXACTLY as long as the deck uses neither of the
    two features LAW2 has no slot for:

    * the Cowper-Symonds rate term SRC/SRP. LAW2's rate term is Johnson-Cook's
      LOGARITHMIC ``1 + c*ln(eps_dot/eps_dot_0)``, a different function — there
      is no faithful transcription, so a rate-dependent material keeps LAW44
      and the ERROR-3046 warning.
    * kinematic hardening. BETA < 1 asks for a Prager-Ziegler back stress and
      LAW2 has no Chard column. It only MATTERS when there is hardening to
      split: with ETAN = 0 the material is perfectly plastic and BETA is inert,
      which is why ``bar1.k`` (BETA 0, ETAN 0) converts losslessly too.

    Everything else is 1:1 — ``a = SIGY``, ``b = E*ETAN/(E-ETAN)``, ``n = 1``
    is the same bilinear plastic branch LAW44 is given, and FS goes to the same
    /FAIL/JOHNSON the LAW44 path writes.
    """
    hardening = _plas_kin_b(mat)
    dropped = []
    if mat.vp:
        dropped.append(f"VP={mat.vp} (the rate formulation flag, which selects "
                       "between two readings of a rate term this material does "
                       "not have)")
    if mat.beta < 1.0:
        dropped.append(
            f"BETA={mat.beta:g} (the kinematic/isotropic hardening split) — "
            f"inert here, because ETAN={mat.etan:g} leaves no hardening to "
            "split between the two")
    out_id = clone_id or mat.mid
    where = (f"every *PART on this material carries SPH particles, so the "
             f"material itself is written as LAW2 under MID {mat.mid}"
             if not clone_id else
             f"the material is SHARED with parts that carry shells or solids "
             f"and still need LAW44, so a SECOND /MAT card is written as "
             f"/MAT/LAW2/{clone_id} and only the SPH part(s) "
             f"{sorted(p for p, c in state.sph_mat_ids.items() if c == clone_id)}"
             " are repointed at it")
    state.warn(
        f"*MAT_PLASTIC_KINEMATIC {mat.mid} → /MAT/LAW2 (PLAS_JOHNS) instead of "
        f"the usual /MAT/LAW44 (COWPER): {where}. LAW44 does NOT declare SPH "
        "compatibility (hm_read_mat44.F states BEAM_ALL / ELASTO_PLASTIC / EOS "
        "/ INCREMENTAL / LARGE_STRAIN / SHELL_ISOTROPIC / SOLID_ISOTROPIC / "
        "TRUSS, no 'SPH'), so the starter would refuse the WHOLE DECK with "
        "ERROR 3046 ('ELEMENTS OF TYPE SPH ARE NOT COMPATIBLE WITH MATERIAL ID "
        f"{mat.mid} OF TYPE 44'). LAW2 is SPH-declared "
        "(mat002/hm_read_mat02_jc.F90:383) and carries this material EXACTLY: "
        f"a = SIGY = {mat.sigy:g}, b = E*ETAN/(E-ETAN) = {hardening:g}, n = 1 "
        "is the same bilinear plastic branch LAW44 would have been given, and "
        "E, nu, rho and FS are unchanged. The re-route is refused — and the "
        "ERROR-3046 warning kept — whenever the deck uses a Cowper-Symonds "
        "rate term (SRC/SRP) or real kinematic hardening, because LAW2 has no "
        "column for either."
        + (" Dropped: " + "; ".join(dropped) + "." if dropped else ""))
    lines = _law2_plas_johns_lines(out_id, mat.title, mat.rho, mat.E, mat.nu,
                                   mat.sigy, hardening, 1.0)
    epmax = mat.fs if 0.0 < mat.fs < 1e19 else 0.0
    if epmax > 0.0:
        lines += _emit_fail_johnson_all_layers(out_id, epmax, state)
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
# Foam batch: MAT_005 / MAT_073 / MAT_126 / MAT_154 / MAT_177
# (MAT_126's orthotropic /PROP/TYPE6 rides writer/composites.py; the
#  *CONTACT_INTERIOR resolution lives in writer/mesh.py.)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_mat_foams(state: ConversionState) -> None:
    """build_starter prepass for the foam batch: synthesize the MAT_005 P(mu)
    function and the MAT_126 V/V0-recomputed yield curves (both BEFORE
    _make_functions, which emits them), resolve the MAT_126 slot wiring and
    LCSR rate samples, compute the MAT_177 Ogden pairs, and raise every
    material-level warning. Runs before _resolve_xref_parts, whose law gate
    reads these containers through _target_mat_law (LAW90 is on the starter's
    solid-/XREF whitelist, so *MAT_073 parts newly RECEIVE a /XREF; LAW21/50/
    62/115 are off-whitelist and warn-skip naming the law)."""
    _resolve_mat_soil_and_foam(state)
    _resolve_mat_low_density_viscous_foam(state)
    _resolve_mat_modified_honeycomb(state)
    _resolve_mat_deshpande_fleck(state)
    _resolve_mat_hill_foam(state)


def _warn_soil_foam_failure_latch(state: ConversionState,
                                  mat: MatSoilAndFoam) -> None:
    """Name what the ``/FAIL/SPALLING`` rider buys over a bare ``/MAT/LAW21``.

    The exclusion this replaces gave a d2r fact as its reason (#130); the real
    question is what the keyword's ONE extra sentence needs, and LAW21 alone
    does not supply it: ``m21law.F:189`` is ``p = max(pmin,p)*off`` and
    ``:196-200`` zeroes ``A0/A1/A2`` while ``P < PMIN`` — both recomputed from
    the CURRENT pressure every step, so a cell that has been in tension
    RECOVERS its full strength the moment the pressure comes back up. The
    latch is what makes it MAT_014.
    """
    state.warn(
        f"*MAT_SOIL_AND_FOAM_FAILURE {mat.mid} -> /MAT/LAW21 + "
        f"/FAIL/SPALLING/{mat.mid} (Ifail_so = 1, P_min = {mat.pc:g}, "
        "D1..D5 = 0). Vol II R17 p.2-209 states the whole keyword in one "
        "sentence: 'The input for this model is the same as for "
        "*MATERIAL_SOIL_AND_FOAM (Type 5); however, when the pressure reaches "
        "the tensile failure pressure, the element loses its ability to carry "
        "tension.' /MAT/LAW21 ALONE does not do that: m21law.F:189 clamps "
        "p = max(pmin,p)*off and :196-200 zeroes A0/A1/A2 while P < PMIN, both "
        "recomputed from the CURRENT pressure every step — so a cell that has "
        "been in tension RECOVERS its full strength when the pressure comes "
        "back up. /FAIL/SPALLING with Ifail_so = 1 supplies the LATCH: "
        "fail_spalling_s.F90:241-268 accumulates dfmax = max(dfmax, "
        "min(p,0)/P_min) MONOTONICALLY, zeroes the stress tensor once when it "
        "reaches 1, and thereafter writes sigxx = sigyy = sigzz = -max(p,0) "
        "with all shears 0 — compression only, no deviator, and the element is "
        "NOT deleted. D1..D5 stay 0 and Ifail_so = 1 keeps the Johnson-Cook "
        "branches (iflag 2/3/4) and the deletion out of it entirely. "
        "Everything else on the card is read exactly as *MAT_SOIL_AND_FOAM."
        + ("" if mat.pc else
           " NOTE PC = 0 on this card: hm_read_fail_spalling.F90:103 turns a "
           "zero P_min into -1e20, so the latch can never trip and the "
           "material behaves as plain *MAT_SOIL_AND_FOAM — state a negative "
           "tensile cutoff if the failure is meant to occur."))


def _resolve_mat_soil_and_foam(state: ConversionState) -> None:
    """*MAT_SOIL_AND_FOAM: the pressure-curve axis transform and the
    field-level approximation warnings.

    THE transform (the classic trap of this batch, taken from the engine
    sources, not intuition): LS-DYNA tabulates pressure against volumetric
    strain EPS = ln(V/V0), NEGATIVE in compression (Manual Vol II R17 Remark
    1); the LAW21 engine evaluates its function at mu = rho/rho0 - 1
    = V0/V - 1, POSITIVE in compression (mmain.F90:686-692 `amu = one/df -
    one`, m21law.F:161 `P = FACY*FINTER(IFUNC, MU, ...)`). So mu =
    exp(-EPS) - 1, the point order REVERSES (LS-DYNA's increasing-compression
    order is decreasing EPS), and the ordinate is unchanged (P is positive in
    compression in BOTH codes: m21law.F:143 `POLD = -THIRD*(SIG1+SIG2+SIG3)`).
    dyna2rad implements exactly this for curves with negative abscissae
    (CM:800-859) but silently creates NO function when every abscissa is
    positive (both its branches require cptneg > 0, CM:814/837) — k2rad
    converts that case too, reading positive abscissae as |EPS|."""
    kw = "*MAT_SOIL_AND_FOAM"
    if not state.mat_soil_and_foam:
        return
    shell_parts = _shell_parts_by_mid(state)
    for mat in state.mat_soil_and_foam.values():
        if mat.latched_tension_failure:
            _warn_soil_foam_failure_latch(state, mat)
        g, k = mat.g, mat.kun
        denom = 3.0 * k + g
        E = 9.0 * g * k / denom if denom != 0.0 else 0.0
        dnu = 6.0 * k + 2.0 * g
        nu_raw = (3.0 * k - 2.0 * g) / dnu if dnu != 0.0 else 0.0
        mat.e_res = E
        mat.nu_res = min(max(nu_raw, 0.0), 0.495)
        if mat.nu_res != nu_raw:
            state.warn(
                f"{kw} mid={mat.mid}: G={g:g} / KUN={k:g} imply Nu = "
                f"(3K-2G)/(6K+2G) = {nu_raw:g}, outside the [0, 0.495] "
                f"range /MAT/LAW21 accepts — CLAMPED to {mat.nu_res:g} "
                "(dyna2rad applies the same clamp, silently). The emitted "
                "elastic constants no longer reproduce the card's G/KUN "
                "pair exactly; check the two moduli (they are the SHEAR "
                "and UNLOADING BULK modulus, not E and nu).")
        if g <= 0.0 or k <= 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: G={g:g} / KUN={k:g} must both be "
                f"positive — the derived E={E:g} and Kt land on /MAT/LAW21, "
                "whose starter requires a positive tensile bulk modulus "
                "(ERROR 829 'TENSILE BULK MODULUS IS LOWER OR EQUAL TO "
                "0.').")
        elif mat.vcr != 1.0:
            state.warn(
                f"{kw} mid={mat.mid}: Kt = B = KUN = {k:g}, so the LAW21 "
                "unloading/reloading bulk modulus equals LS-DYNA's KUN at "
                "every compression AND in tension. This deliberately "
                "diverges from dyna2rad's Kt = KUN/100 (+ B = KUN, Mu_max "
                "unset): the engine interpolates the unloading bulk as "
                "alpha*B + (1-alpha)*Kt with alpha = mu/Mu_max, and the "
                "unset Mu_max becomes 1e20 (hm_read_mat21.F), so alpha ~ 0 "
                "and d2r's B field is DEAD — its converted soil/foam "
                "unloads at KUN/100 in BOTH signs, retraces the loading "
                "curve and dissipates ~nothing (measured: -0.12% retained "
                "IE vs LS-DYNA's elastic-line unload).")
        if mat.vcr == 1.0:
            state.warn(
                f"{kw} mid={mat.mid}: VCR=1 (no volumetric crushing — "
                "unloading follows the loading curve) has no exact LAW21 "
                "counterpart. dyna2rad's mapping B=0 + Kt=KUN/100 is kept "
                f"HERE (Kt={k / 100.0:g}): the starter substitutes "
                "B=Kt with its own WARNING 829, and that soft unloading "
                "bulk makes the engine's min(elastic, curve) pressure "
                "RETRACE the loading curve wherever the curve is steeper "
                "than KUN/100 (measured) — i.e. a close approximation of "
                "VCR=1's load=unload semantics. Tension is 100x softer "
                "than LS-DYNA's K; verify if the foam sees tension.")
        elif mat.vcr != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: VCR={mat.vcr:g} is neither 0 nor 1 — "
                "treated as 0 (volumetric crushing on, elastic unloading "
                "with B=KUN), which is what LS-DYNA does with any VCR != 1.")
        if mat.pc > 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PC={mat.pc:g} is POSITIVE. LS-DYNA "
                "defines the pressure cutoff for tensile fracture as a "
                "NEGATIVE number, and /MAT/LAW21 P_min copies it verbatim — "
                f"a positive P_min forbids every pressure below {mat.pc:g}, "
                "including the unloaded state. Check the sign on the card.")
        elif mat.pc == 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PC is 0/blank. LS-DYNA's default "
                "cutoff IS an active floor at zero — 'if the pressure drops "
                "below the cutoff value specified, it is reset to that "
                "value' (Manual Vol II R17 MAT_005 Remark 1), i.e. the "
                "material carries NO tensile pressure. /MAT/LAW21 P_min=0 "
                "means the opposite: the starter substitutes -INFINITY "
                "(hm_read_mat21.F: PMIN==0 -> -1e20), i.e. UNLIMITED "
                "tension through Kt. P_min is copied verbatim (dyna2rad "
                "does the same) — set P_min to a small negative value "
                "(e.g. -1e-20) by hand if the no-tension behaviour "
                "matters.")
        # ── The pressure curve ────────────────────────────────────────────
        pts: Optional[List[Tuple[float, float]]] = None
        src = ""
        if mat.lcid:
            crv = state.curves.get(mat.lcid)
            if crv is None or not crv.pts:
                state.warn(
                    f"{kw} mid={mat.mid}: LCID={mat.lcid} has no parsed "
                    "*DEFINE_CURVE — falling back to the EPS1..10/P1..10 "
                    "card pairs.")
            else:
                pts = list(crv.pts)
                src = f"LCID={mat.lcid}"
        from_pairs = pts is None
        if pts is None:                  # `from_pairs` is read further down
            pairs = list(zip(mat.eps, mat.p))
            while pairs and pairs[-1] == (0.0, 0.0):
                pairs.pop()          # unused trailing card slots, not data
            pts = pairs
            src = "the EPS/P card pairs"
        neg = [x for x, _ in pts if x < 0.0]
        pos = [x for x, _ in pts if x > 0.0]
        kept = pts
        if neg and pos:
            kept = [(x, y) for x, y in pts if x >= 0.0]
            state.warn(
                f"{kw} mid={mat.mid}: the pressure curve ({src}) mixes "
                f"negative and positive abscissae — following dyna2rad "
                f"(CM:814-836), the {len(pts) - len(kept)} negative-EPS "
                "point(s) are DROPPED and the positive abscissae are read as "
                "|ln(V/V0)| compressive strain. A pure LS-DYNA-convention "
                "curve is all-negative; check which convention the card "
                "really uses.")
        elif pos and not neg:
            state.warn(
                f"{kw} mid={mat.mid}: every pressure-curve abscissa ({src}) "
                "is POSITIVE — LS-DYNA's convention is EPS = ln(V/V0), "
                "negative in compression, so the abscissae are read as "
                "|ln(V/V0)| (an already-positive compression measure) and "
                "transformed mu = exp(|EPS|)-1 all the same. dyna2rad "
                "creates NO function at all for this case (both its "
                "branches require a negative abscissa, CM:814/837) and the "
                "deck would fail downstream; verify the curve convention.")
        else:
            kept = [(x, y) for x, y in pts if x <= 0.0]
        # exp() guard: |EPS| beyond ~709.78 overflows a double. A volumetric
        # strain that large is not physical data — it almost always means the
        # LCID points at the wrong curve (time series, force curve ...), the
        # input class every other branch here degrades gracefully on.
        huge = [x for x, _ in kept if abs(x) > 700.0]
        if huge:
            state.warn(
                f"{kw} mid={mat.mid}: {len(huge)} pressure-curve point(s) "
                f"with |EPS| > 700 dropped (abscissae {huge[:4]}"
                + ("..." if len(huge) > 4 else "") + ") — "
                "mu = exp(|EPS|)-1 overflows a float there, and a "
                "volumetric strain |ln(V/V0)| above 700 is not soil data; "
                "check that LCID points at the pressure curve.")
            kept = [(x, y) for x, y in kept if abs(x) <= 700.0]
        mu_pts: List[Tuple[float, float]] = []
        collapsed = []
        for x, y in sorted((math.exp(abs(x)) - 1.0, y) for x, y in kept):
            if mu_pts and x == mu_pts[-1][0]:
                # duplicated abscissa (e.g. two (0,0) slots, or +EPS/-EPS
                # folding onto one mu): keep the LAST ordinate — a /FUNCT
                # with a repeated X is not a valid Radioss function.
                if y != mu_pts[-1][1]:
                    collapsed.append(x)
                mu_pts[-1] = (x, y)
                continue
            mu_pts.append((x, y))
        if collapsed:
            state.warn(
                f"{kw} mid={mat.mid}: the transformed pressure curve had "
                f"{len(collapsed)} duplicated mu abscissa(e) with DIFFERENT "
                f"pressures (mu = {collapsed[:4]}"
                + ("..." if len(collapsed) > 4 else "") + ") — collapsed "
                "to the last point each (a /FUNCT cannot carry a vertical "
                "step). A pressure step in the source curve loses its "
                "jump; restate it with two closely-spaced abscissae.")
        if from_pairs and mu_pts and mu_pts[0][0] > 0.0:
            # LS-DYNA auto-generates the (0,0) first point when EPS1 != 0
            # (Manual Vol II R17, MAT_005 Remark 1) — mirror it.
            mu_pts.insert(0, (0.0, 0.0))
        if len(mu_pts) < 2:
            state.warn(
                f"{kw} mid={mat.mid}: no usable pressure-curve points "
                f"(source: {src}) — /MAT/LAW21 is emitted with func_IDf=0, "
                "which leaves the material without a P(mu) function to "
                "evaluate. Give the card an LCID curve or at least two "
                "EPS/P pairs.")
        else:
            fid = state.next_curve_id()
            _add_auto_curve(state, fid, f"Auto_MAT005_P_mu_mid{mat.mid}",
                            mu_pts)
            mat.func_id = fid
            state.warn(
                f"{kw} mid={mat.mid}: pressure curve ({src}) converted to "
                f"/FUNCT {fid} with the LAW21 axis transform mu = exp(-EPS) "
                "- 1: LS-DYNA tabulates P vs EPS = ln(V/V0) (negative in "
                "compression), the LAW21 engine evaluates P at mu = "
                "rho/rho0 - 1 = V0/V - 1 (positive in compression, "
                "mmain.F90:686-692) — abscissae transformed and re-sorted "
                "ascending, ordinates unchanged (P is compression-positive "
                "in both codes).")
        shell_pids = shell_parts.get(mat.mid, [])
        if shell_pids:
            state.warn(
                f"{kw} mid={mat.mid}: part(s) {shell_pids} are SHELL parts, "
                "but /MAT/LAW21 declares only SOLID_ISOTROPIC and SPH "
                "(hm_read_mat21.F:223-224) — the starter rejects the "
                "combination with ERROR 3046. Use a shell-capable foam/soil "
                "law or re-mesh as solids.")


def _resolve_mat_low_density_viscous_foam(state: ConversionState) -> None:
    """*MAT_073: dropped-field warnings and the /VISC/PRONY branch report.
    The card wiring itself (E→E0, LCID→the single loading function, HU→Hys,
    SHAPE→Shape, Gi/BETAi→/VISC/PRONY of the same id) follows dyna2rad
    p_ConvertMatL73 (CM:4275-4338) exactly and needs no synthesis."""
    kw = "*MAT_LOW_DENSITY_VISCOUS_FOAM"
    if not state.mat_low_density_viscous_foam:
        return
    shell_parts = _shell_parts_by_mid(state)
    for mat in state.mat_low_density_viscous_foam.values():
        if not mat.lcid:
            state.warn(
                f"{kw} mid={mat.mid}: no loading curve (LCID=0) — "
                "/MAT/LAW90's function row carries fct_IDL=0, which the "
                "starter rejects (ERROR 126). Add the nominal stress-strain "
                "curve.")
        elif mat.lcid not in state.curves:
            state.warn(
                f"{kw} mid={mat.mid}: LCID={mat.lcid} has no parsed "
                "*DEFINE_CURVE — the /MAT/LAW90 function reference dangles "
                "and the starter will reject it; add the curve to the deck.")
        if mat.lcid2 > 0:
            state.warn(
                f"{kw} mid={mat.mid}: LCID2={mat.lcid2} selects the "
                "relaxation-curve branch, where LS-DYNA least-squares fits "
                f"the Gi/BETAi series itself (BSTART={mat.bstart:g}, "
                f"TRAMP={mat.tramp:g}, NV={mat.nv}). Neither dyna2rad nor "
                "k2rad performs that fit — NO /VISC/PRONY is emitted and the "
                "foam converts RATE-INDEPENDENT (quasi-static branch only). "
                "State the explicit Gi/BETAi cards (LCID2=0) to keep the "
                "viscosity.")
        elif mat.lcid2 == -1:
            state.warn(
                f"{kw} mid={mat.mid}: LCID2=-1 selects the frequency-data "
                f"branch (LCID3={mat.lcid3}, LCID4={mat.lcid4}) — "
                "unsupported by dyna2rad and k2rad alike; NO /VISC/PRONY is "
                "emitted and the foam converts rate-independent.")
        else:
            dropped = [t for t in mat.prony if t[1] <= 0.0]
            if dropped:
                state.warn(
                    f"{kw} mid={mat.mid}: {len(dropped)} Gi/BETAi term(s) "
                    "with BETAi <= 0 dropped from the /VISC/PRONY series "
                    "(a non-positive decay constant is a permanent extra "
                    "stiffness the G_i/Beta_i pair cannot express; dyna2rad "
                    "filters identically, CM:4317-4333).")
        if mat.tc != 0.0 and mat.tc < 1.0e19:
            state.warn(
                f"{kw} mid={mat.mid}: tension cutoff TC={mat.tc:g} — "
                "/MAT/LAW90's Tcut field exists only from the radioss2026 "
                "card revision, and a /BEGIN 2022 deck has no slot for it — "
                "DROPPED (LAW90 tension follows the loading curve's negative "
                "branch, uncut).")
        if mat.fail != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: FAIL={mat.fail:g} (tensile stress "
                "reset to zero past the cutoff) — LAW90's FAIL flag is "
                "radioss2026-only; DROPPED at /BEGIN 2022.")
        if mat.kcon != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: contact-stiffness modulus "
                f"KCON={mat.kcon:g} — LAW90's Kcont field is radioss2026-"
                "only; DROPPED at /BEGIN 2022 (contact stiffness follows "
                "E0).")
        if mat.beta != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: HU decay constant BETA={mat.beta:g} "
                "has no /MAT/LAW90 field — dropped (LAW90's hysteretic "
                "unloading is governed by Hys/Shape alone).")
        if mat.bvflag != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: bulk-viscosity flag "
                f"BVFLAG={mat.bvflag:g} has no /MAT/LAW90 field — dropped.")
        if mat.damp != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: viscous damping DAMP={mat.damp:g}"
                + (" (the LS-DYNA default 0.05 — the card left it blank)"
                   if mat.damp == 0.05 else "")
                + " is DROPPED: dyna2rad moves it onto the solid property "
                "(/PROP/TYPE14 Mu=DAMP, Lambda=DAMP/3, CP:484-495), but "
                "k2rad keeps the section-derived /PROP/SOLID — the same "
                "policy as its *MAT_LOW_DENSITY_FOAM (057) handling — so "
                "the foam converts without the Navier damping (the "
                "Ismstr=10 pin from that same d2r rule IS adopted, see "
                "the property warning). Add LAMBDA_V/MU_V on the "
                "/PROP/SOLID by hand if the foam needs it.")
        shell_pids = shell_parts.get(mat.mid, [])
        if shell_pids:
            state.warn(
                f"{kw} mid={mat.mid}: part(s) {shell_pids} are SHELL parts, "
                "but /MAT/LAW90 declares only SOLID_ISOTROPIC "
                "(hm_read_mat90.F:233) — the starter rejects the "
                "combination with ERROR 3046.")


# LAW50 direction slots in card order — 11, 22, 33 then 12, 23, 31
# (hm_read_mat50.F90:308-315 and the starter's YIELD STRESS 11/22/33/12/23/31
# printout).
_LAW50_SLOTS = ("11", "22", "33", "12", "23", "31")


def _mat126_curve(state: ConversionState, mat, cid: int, slot: str,
                  cache: dict) -> int:
    """One MAT_126 yield curve → the /FUNCT id LAW50 should reference,
    applying dyna2rad's RecomputeCurvesBasedOnFirstAbcissa (CM:9215-9266):
    a curve whose FIRST abscissa is > 0 is taken as stress vs relative
    volume V/V0 and every abscissa is replaced by 1 - V/V0 (volumetric
    engineering strain, compression positive), re-sorted ascending, into a
    new /FUNCT; a curve starting at 0 (or negative) is already strain-based
    and is referenced by its original id."""
    if cid in cache:
        return cache[cid]
    crv = state.curves.get(cid)
    if crv is None or not crv.pts:
        state.warn(
            f"*MAT_MODIFIED_HONEYCOMB mid={mat.mid}: yield curve {cid} "
            f"(slot {slot}) has no parsed *DEFINE_CURVE — the slot is left "
            "EMPTY (funID=0: no yield function, the direction stays "
            "elastic); add the curve to the deck.")
        cache[cid] = 0
        return 0
    if crv.pts[0][0] > 0.0:
        fid = state.next_curve_id()
        pts: List[Tuple[float, float]] = []
        for x, y in sorted((1.0 - x, y) for x, y in crv.pts):
            if pts and x == pts[-1][0]:
                if y != pts[-1][1]:
                    state.warn(
                        f"*MAT_MODIFIED_HONEYCOMB mid={mat.mid}: yield curve "
                        f"{cid} repeats the abscissa V/V0={1.0 - x:g} with "
                        "different ordinates — collapsed to the last point "
                        "(a /FUNCT cannot carry a vertical step).")
                pts[-1] = (x, y)
                continue
            pts.append((x, y))
        _add_auto_curve(state, fid,
                        (crv.title or f"FUNCT_{cid}") + "_MatL50_recomputed",
                        pts)
        state.warn(
            f"*MAT_MODIFIED_HONEYCOMB mid={mat.mid}: yield curve {cid} "
            f"starts at abscissa {crv.pts[0][0]:g} > 0, which dyna2rad's "
            "RecomputeCurvesBasedOnFirstAbcissa reads as stress vs RELATIVE "
            "VOLUME V/V0 — abscissae replaced by 1 - V/V0 (volumetric "
            "engineering strain, compression positive) and re-sorted "
            f"ascending as /FUNCT {fid}; ordinates unchanged, the original "
            "curve is kept. If the curve was already strain-based, prepend "
            "its (0, y0) point so the first abscissa is 0.")
        cache[cid] = fid
        return fid
    cache[cid] = cid
    return cid


def _resolve_mat_modified_honeycomb(state: ConversionState) -> None:
    """*MAT_126 → LAW50 wiring, following dyna2rad p_ConvertMatL26 +
    UpdateMatConvertingLoadCurves (CM:1744-1815, 8923-9213):

    * normal surface (LCA >= 0): identity slot map a→11 b→22 c→33 ab→12
      bc→23 ca→31 with the LS-DYNA fallback chain (missing normal → LCA,
      missing shear → LCS → LCA); moduli EAAU..GCAU with 0 → E (E-row) and
      0 → E/2(1+PR) (G-row); Iflag1 = Iflag2 = -1 (yield vs -strain, i.e.
      compression-positive).
    * LCA < 0 (transversely isotropic surface): dyna2rad's remap fun11←LCB,
      fun22=fun33←LCC, all shears←LCS; E11=EAAU, E22=E33=EBBU, G12=GBCU,
      G23=G31=GABU; Iflag1=0, Iflag2=1 — an APPROXIMATION (the LS-DYNA
      damage curves become yield curves), warned loudly.
    * LCSR > 0: up to 5 (rate, scale) samples — the curve's FIRST FIVE
      points (the "MODIFIED" rule, CM:9017-9021: points 1-4, then point 5
      when the curve has more; the plain MAT_026 rule takes points 1-4 plus
      the LAST point instead); each direction's base function is replicated
      per rate with Fscale = the sampled ordinate. LCSR = -1 (per-direction
      rate curves) is dropped like dyna2rad, loudly.
    """
    kw = "*MAT_MODIFIED_HONEYCOMB"
    if not state.mat_modified_honeycomb:
        return
    for mat in state.mat_modified_honeycomb.values():
        cache: dict = {}
        G0 = (mat.E / (2.0 * (1.0 + mat.nu)) if mat.nu > -1.0
              else mat.E / 2.0)
        if mat.lca < 0:
            state.warn(
                f"{kw} mid={mat.mid}: LCA={mat.lca} < 0 selects the SECOND "
                "(transversely isotropic) yield surface, which /MAT/LAW50 "
                "does not have. dyna2rad's remap is followed (CM:8955, "
                "1784, 1802-1812): LCB (strong-axis hardening) → the 11 "
                "yield function, LCC (weak-axis) → 22 and 33, and the LCS "
                "curve → ALL THREE shear slots — but in this variant "
                "LCS/LCAB/LCBC/LCCA are shear DAMAGE curves, not yield "
                "curves, so the converted shear response is a DIFFERENT "
                "physical quantity. E11=EAAU, E22=E33=EBBU, G12=GBCU, "
                "G23=G31=GABU (ECCU/GCAU discarded); Iflag1=0 (yield vs "
                "volumetric strain), Iflag2=1. Validate against a known "
                "crush case before trusting this material.")
            if mat.eccu < 0.0:
                state.warn(
                    f"{kw} mid={mat.mid}: ECCU={mat.eccu:g} < 0 activates "
                    "the THIRD yield surface (|ECCU| = initial shear yield, "
                    "GCAU re-read as the hydrostatic yield) — no LAW50 "
                    "counterpart, DROPPED (dyna2rad discards both in this "
                    "variant too).")
            base = mat.lcb
            f11 = _mat126_curve(state, mat, base, "11", cache) if base else 0
            f22 = _mat126_curve(state, mat, mat.lcc or base, "22", cache) \
                if (mat.lcc or base) else 0
            f33 = _mat126_curve(state, mat, mat.lcc or base, "33", cache) \
                if (mat.lcc or base) else 0
            fsh = _mat126_curve(state, mat, mat.lcs or base, "12/23/31",
                                cache) if (mat.lcs or base) else 0
            mat.fun_ids = [f11, f22, f33, fsh, fsh, fsh]
            mat.moduli = [mat.eaau or mat.E, mat.ebbu or mat.E,
                          mat.ebbu or mat.E, mat.gbcu or G0,
                          mat.gabu or G0, mat.gabu or G0]
            mat.iflag1, mat.iflag2 = 0, 1
        else:
            lcb = mat.lcb or mat.lca
            lcc = mat.lcc or mat.lca
            lcs = mat.lcs or mat.lca
            lcab = mat.lcab or lcs
            lcbc = mat.lcbc or lcs
            lcca = mat.lcca or lcs
            srcs = (mat.lca, lcb, lcc, lcab, lcbc, lcca)
            if not mat.lca:
                state.warn(
                    f"{kw} mid={mat.mid}: no yield curve at all (LCA=0) — "
                    "every /MAT/LAW50 direction is emitted without a yield "
                    "function and the honeycomb has no crush resistance; "
                    "add the LCA..LCCA curves.")
            fids = []
            for slot, cid in zip(_LAW50_SLOTS, srcs):
                fids.append(_mat126_curve(state, mat, cid, slot, cache)
                            if cid else 0)
            mat.fun_ids = fids
            mat.moduli = [mat.eaau or mat.E, mat.ebbu or mat.E,
                          mat.eccu or mat.E, mat.gabu or G0,
                          mat.gbcu or G0, mat.gcau or G0]
            mat.iflag1, mat.iflag2 = -1, -1
        # ── LCSR strain-rate scaling ──────────────────────────────────────
        mat.rates, mat.scales = [], []
        if mat.lcsr == -1.0:
            state.warn(
                f"{kw} mid={mat.mid}: LCSR=-1 supplies PER-DIRECTION rate "
                f"curves (LCSRA..LCSRCA = {mat.lcsr_dirs}) — dyna2rad never "
                "reads that card and k2rad follows it: ALL strain-rate data "
                "is DROPPED and the honeycomb converts rate-independent. "
                "Re-state a single LCSR curve to keep an (isotropic) rate "
                "scaling.")
        elif mat.lcsr > 0.0:
            rc = state.curves.get(int(mat.lcsr))
            if rc is None or not rc.pts:
                state.warn(
                    f"{kw} mid={mat.mid}: LCSR={mat.lcsr:g} has no parsed "
                    "*DEFINE_CURVE — the rate scaling is dropped and the "
                    "honeycomb converts rate-independent.")
            else:
                samp = list(rc.pts[:4])
                if len(rc.pts) > 4:
                    samp.append(rc.pts[4])
                mat.rates = [x for x, _ in samp]
                mat.scales = [y for _, y in samp]
                state.warn(
                    f"{kw} mid={mat.mid}: LCSR={int(mat.lcsr)} sampled into "
                    f"{len(samp)} (strain-rate, scale) pair(s) — dyna2rad's "
                    "MODIFIED-honeycomb rule: the curve's FIRST FIVE points "
                    "(CM:9017-9021; the plain MAT_026 rule instead takes "
                    "the first 4 plus the LAST point). Each direction's "
                    "base yield function is REPLICATED per rate with "
                    "Fscale = the sampled ordinate (rate dependence as a "
                    "pure ordinate scale); LCSR points beyond the fifth "
                    "are dropped — including the high-rate end of a long "
                    "curve.")
        # ── Inexpressible / dropped fields ───────────────────────────────
        if mat.E or mat.nu or mat.sigy or mat.vf:
            state.warn(
                f"{kw} mid={mat.mid}: the fully-compacted continuum "
                f"(E={mat.E:g}, PR={mat.nu:g}, SIGY={mat.sigy:g}, "
                f"VF={mat.vf:g}) maps onto /MAT/LAW50's ECOMP/NU/SIGY/"
                "VCOMP compaction card, which exists only in the "
                "radioss2025 LAW50 format — a /BEGIN 2022 deck reads "
                "mat_law50.cfg FORMAT(radioss90), 24 cards, no compaction "
                "card — so it is DROPPED and the converted honeycomb NEVER "
                "stiffens into the compacted solid. E and PR still serve "
                "as the fallback for blank EAAU..GCAU moduli.")
        for label, val in (("viscosity coefficient MU", mat.mu),
                           ("bulk-viscosity flag BULK", mat.bulk),
                           ("VREF", mat.vref), ("TREF", mat.tref),
                           ("SHDFLG", mat.shdflg), ("RFAC", mat.rfac)):
            if val != 0.0:
                state.warn(
                    f"{kw} mid={mat.mid}: {label}={val:g} has no "
                    "/MAT/LAW50 field — dropped.")
        if mat.pru != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PRU={mat.pru:g} (Poisson effect "
                "during compaction"
                + (f", ratios {mat.pru_ratios}" if mat.pru_ratios else "")
                + ") has no /MAT/LAW50 counterpart — dropped; LAW50 keeps "
                "the uncoupled orthotropic behaviour up to compaction.")
        if mat.macf not in (0, 1):
            state.warn(
                f"{kw} mid={mat.mid}: MACF={mat.macf} switches the material "
                "axes — no counterpart on the synthesized /PROP/TYPE6; "
                "dropped. Restate the axes directly via AOPT.")
        if mat.tsef < 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: TSEF={mat.tsef:g} < 0 means |TSEF| is "
                "a failure-strain CURVE id — /MAT/LAW50's Eps_max is a "
                "constant; the curve form is dropped (Eps_max11/22/33 = 0, "
                "no tensile failure).")
        if mat.ssef < 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: SSEF={mat.ssef:g} < 0 means |SSEF| is "
                "a failure-strain CURVE id — dropped (Eps_max12/23/31 = 0, "
                "no shear failure).")


def _resolve_mat_deshpande_fleck(state: ConversionState) -> None:
    """*MAT_154 → LAW115: the 1:1 map needs no synthesis; the warnings cover
    the two fields whose MEANING has no counterpart (DERFI, NUM), the
    starter's own bound checks so they fail here, not at starter time, and
    the Isolid=24 routing (the hex default Isolid=17 is engine-fatal for
    LAW115 — announced here, applied in _make_properties)."""
    kw = "*MAT_DESHPANDE_FLECK_FOAM"
    if not state.mat_deshpande_fleck:
        return
    shell_parts = _shell_parts_by_mid(state)
    sqrt45 = math.sqrt(4.5)
    # Loop-invariants hoisted (the _shell_parts_by_mid rule: an O(n_elems)
    # scan inside a per-material loop is O(n_elems x n_mats) for nothing).
    solid_pids = {e.pid for e in state.solid_elems}
    parts_sorted = sorted(state.parts.items())
    for mat in state.mat_deshpande_fleck.values():
        if mat.derfi != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: DERFI={mat.derfi:g} selects the "
                "analytical yield-surface derivative — /MAT/LAW115's Ires "
                "flag chooses the return-mapping ALGORITHM (1 NICE explicit "
                "/ 2 Newton implicit), not the derivative evaluation, so "
                "DERFI is dropped and Ires stays at the starter default "
                "Newton (Ires=2). No accuracy loss expected.")
        if mat.pfail > 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: PFAIL={mat.pfail:g} maps to LAW115 "
                "SIGP_F (max principal stress at failure) — note LS-DYNA "
                f"deletes the element only after NUM={mat.num} consecutive "
                "violated timesteps, while Radioss deletes on the FIRST "
                "violation, so the converted foam can erode earlier under "
                "spiky loads. (dyna2rad's cfg never parses PFAIL at all — "
                "its SIGP_F is silently always 0; k2rad carries it.)")
        if mat.alpha < 0.0 or mat.alpha > sqrt45:
            state.warn(
                f"{kw} mid={mat.mid}: ALPHA={mat.alpha:g} is outside "
                f"[0, sqrt(4.5)={sqrt45:g}] — the starter REJECTS it "
                "(ERROR 1897).")
        if mat.nu < 0.0 or mat.nu >= 0.5:
            state.warn(
                f"{kw} mid={mat.mid}: PR={mat.nu:g} is outside [0, 0.5) — "
                "the starter REJECTS it (ERROR 49).")
        shell_pids = shell_parts.get(mat.mid, [])
        if shell_pids:
            state.warn(
                f"{kw} mid={mat.mid}: part(s) {shell_pids} are SHELL parts, "
                "but /MAT/LAW115 declares only SOLID_ISOTROPIC "
                "(hm_read_mat115.F:319) — the starter rejects the "
                "combination with ERROR 3046.")
        routed = []
        gated = []
        for pid, part in parts_sorted:
            if part.mid != mat.mid or pid not in solid_pids:
                continue
            sec = state.sec_solids.get(part.secid if part.secid > 0 else pid)
            isolid = _elform_to_isolid(sec.elform) if sec else 17
            if isolid == 17:
                routed.append(pid)
            elif 2 < isolid < 21:
                gated.append((pid, isolid))
        if routed:
            state.warn(
                f"{kw} mid={mat.mid}: part(s) {routed} would land on "
                "k2rad's ELFORM-derived full-integration /PROP/SOLID "
                "Isolid=17, where /MAT/LAW115 is UNRUNNABLE: the starter "
                "only answers WARNING 1905 (sgrtails.F:631 gates JHBE "
                "3..20), but the ENGINE collapses the solid time step "
                "below DTMIN at cycle 0, jumps past the end time and "
                "prints NORMAL TERMINATION after 1 cycle — a silent empty "
                "run (measured on this starter/engine pair; the identical "
                "deck at Isolid=24 runs to completion, 0 warnings). Their "
                "/PROP/SOLID is emitted with Isolid=24 (HEPH — also "
                "dyna2rad's default hex formulation for MAT_154 decks); "
                "any non-LAW115 part sharing the *SECTION_SOLID switches "
                "along (warned separately).")
        if gated:
            state.warn(
                f"{kw} mid={mat.mid}: part(s) "
                f"{[p for p, _ in gated]} land on /PROP/SOLID Isolid="
                f"{sorted({i for _, i in gated})} (k2rad's ELFORM-derived "
                "formulation), and the starter answers WARNING 1905 for any "
                "/MAT/LAW115 group at Isolid 3..20 (sgrtails.F:631). Only "
                "the hex Isolid=17 pairing is auto-routed to 24 (the one "
                "measured to kill the engine time step); this formulation "
                "is left as derived — LAW115's preferred pairings are the "
                "under-integrated linear solids Isolid 1/2/24, so VERIFY "
                "the engine time step survives cycle 0, and reformulate "
                "the foam mesh as bricks if it does not.")


def _hill_foam_nu(n: float) -> float:
    """MAT_177 N → LAW62 Nu = N/(1+2N), the standard Hill-foam relation
    (dyna2rad CM:9773-9775)."""
    denom = 1.0 + 2.0 * n
    return n / denom if denom != 0.0 else 0.0


def _resolve_mat_hill_foam(state: ConversionState) -> None:
    """*MAT_177 (LCID=0 branch) → LAW62 constants: mu_i = Ci*Bi/2, alpha_i =
    Bi per the exact Hill→Ogden identity, INDEX-ALIGNED over the nonzero-C
    slots — dyna2rad compacts the C and B lists independently, so a zero Ci
    mid-list makes it read Bi out of alignment/range (CM:9877-9883); k2rad
    keeps each Ci with ITS OWN Bi."""
    kw = "*MAT_HILL_FOAM"
    if not state.mat_hill_foam:
        return
    for mat in state.mat_hill_foam.values():
        mat.mu_i, mat.alpha_i = [], []
        dead = []
        for i in range(min(len(mat.c), len(mat.b))):
            if mat.c[i] == 0.0:
                continue
            mat.mu_i.append(mat.c[i] * mat.b[i] / 2.0)
            mat.alpha_i.append(mat.b[i])
            if mat.b[i] == 0.0:
                dead.append(i + 1)
        if dead:
            state.warn(
                f"{kw} mid={mat.mid}: C{'/C'.join(str(i) for i in dead)} "
                "nonzero with a ZERO B in the same slot — the Ogden pair "
                "mu_i = Ci*Bi/2 degenerates to 0 (the starter then defaults "
                "alpha_i to 1), i.e. the term contributes nothing. Check "
                "the C/B pairing on the card. (dyna2rad compacts the two "
                "lists independently here and reads B values out of "
                "alignment.)")
        if not mat.mu_i:
            state.warn(
                f"{kw} mid={mat.mid}: no nonzero Ci constant — /MAT/LAW62 "
                "is emitted with law order N=0, which the starter REJECTS "
                "(ERROR 559). Provide the C1..C8/B1..B8 constants.")
        nu = _hill_foam_nu(mat.n)
        if nu < 0.0 or nu >= 0.5:
            state.warn(
                f"{kw} mid={mat.mid}: N={mat.n:g} gives Nu = N/(1+2N) = "
                f"{nu:g}"
                + (" — the starter clamps Nu >= 0.5 to 0.499"
                   if nu >= 0.5 else " (negative)")
                + "; check N (the LS-DYNA card's 4th field, Manual Vol II "
                "R17 p.2-1216: MID RO K N MU).")
        if mat.k != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: bulk modulus K={mat.k:g} has no "
                "/MAT/LAW62 field — LAW62 derives the bulk response from "
                f"Nu = N/(1+2N) = {nu:g} and the mu_i; verify the converted "
                "compressibility matches.")
        if mat.mu != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: damping coefficient MU={mat.mu:g} "
                "has no /MAT/LAW62 field — dropped (LAW62's viscous branch "
                "is a Maxwell gamma_i/tau_i series, not a damping "
                "coefficient).")
        if mat.lcsr:
            state.warn(
                f"{kw} mid={mat.mid}: LCSR={mat.lcsr} (stretch-ratio curve "
                "of the fit branch) has no /MAT/LAW62 counterpart — "
                "dropped; the conversion is rate-independent.")
        if mat.r != 0.0 or mat.m != 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: Mullins-effect card (R={mat.r:g}, "
                f"M={mat.m:g}) has no /MAT/LAW62 counterpart — dropped "
                "(no stress softening on reloading).")


def _emit_mat_law21(mat: MatSoilAndFoam) -> List[str]:
    """*MAT_SOIL_AND_FOAM (MAT_005) → /MAT/LAW21 (DPRAG). Column layout from
    matl21_dprag.cfg FORMAT(radioss130) (the block a /BEGIN 2022 deck reads):
    RHO_I; E Nu; A0 A1 A2 Amax; [func_IDf(10) + 10 literal blanks + Kt +
    FscaleP]; P_min P_ext; B Mu_max. E and Nu derive from the card's G/KUN
    exactly as dyna2rad (CM:742-757): E = 9GK/(3K+G), Nu = (3K-2G)/(6K+2G)
    clamped to [0, 0.495] — resolved (and clamp-warned) in
    _resolve_mat_soil_and_foam. A0/A1/A2 copy verbatim (identical yield
    algebra), P_min = PC verbatim (no sign change — both codes' tension
    cutoff is negative; PC=0's semantic flip is warned in the resolver).

    Kt = B = KUN for VCR=0 — a conscious fix over dyna2rad's Kt = KUN/100:
    with Mu_max unset the starter substitutes 1e20 (hm_read_mat21.F) and the
    engine's unloading bulk alpha*B + (1-alpha)*Kt with alpha = mu/Mu_max
    degenerates to Kt for every reachable mu (m21law.F:166-170), so d2r's B
    is a DEAD field and its soil unloads at KUN/100 in BOTH signs (measured:
    the loading curve is retraced, ~0% dissipation). Kt = KUN makes the
    unloading/reloading modulus LS-DYNA's KUN everywhere, tension included
    (LS-DYNA has a single bulk modulus for both). VCR=1 keeps d2r's B=0 +
    Kt=KUN/100: the starter substitutes B=Kt (WARNING 829) and the soft
    modulus reproduces VCR=1's unload-along-the-curve semantics (measured).
    Amax/FscaleP/P_ext/Mu_max are written 0, matching dyna2rad's unset
    fields → the starter substitutes 1e30 / 1.0 / 0 / 1e20."""
    k = mat.kun
    vcr1 = mat.vcr == 1.0
    b = 0.0 if vcr1 else k
    kt = k / 100.0 if vcr1 else k
    return [
        f"/MAT/LAW21/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu",
        f"{_f(mat.e_res)}{_f(mat.nu_res)}",
        "#                 A0                  A1                  A2                Amax",
        f"{_f(mat.a0)}{_f(mat.a1)}{_f(mat.a2)}{_f(0.0)}",
        "#  func_IDf                              Kt             FscaleP",
        f"{_i(mat.func_id)}{' ' * 10}{_f(kt)}{_f(0.0)}",
        "#              P_min               P_ext",
        f"{_f(mat.pc)}{_f(0.0)}",
        "#                  B              Mu_max",
        f"{_f(b)}{_f(0.0)}",
        HDR,
    ]


def _emit_fail_spalling(mid: int, pc: float) -> List[str]:
    """``/FAIL/SPALLING`` — the LATCHED tensile cutoff of
    ``*MAT_SOIL_AND_FOAM_FAILURE`` (``*MAT_014``).

    Card layout from ``radioss2018/FAIL/fail_spalling.cfg``
    ``FORMAT(radioss130)``, the newest block a ``/BEGIN 2022`` deck reads::

        C1: D1(20) D2(20) D3(20) D4(20) D5(20)
        C2: Epsilon_Dot_0(20) P_min(20) Ifail_so(10)

    ``D1..D5`` are written 0 and ``Ifail_so = 1``, which is the PURE ``P_min``
    branch: ``hm_read_fail_spalling.F90:98-104`` clamps
    ``isolid = max(1, min(6, Ifail_so))`` into ``fail%iparam(1)``, and
    ``fail_spalling_s.F90:104-131`` maps ``iflag = 1`` to ``ispall = 1`` with
    no ``idel``/``idev``, so the Johnson-Cook branches (``iflag == 2/3/4``)
    and the element deletion never run.

    What ``ispall = 1`` does, at ``fail_spalling_s.F90:241-268``: it
    accumulates ``dfmax(i,3) = max(dfmax(i,3), min(p,0)/pmin)`` — MONOTONE, so
    once the cell has seen ``p <= P_min`` the damage stays at 1 — zeroes the
    whole stress tensor once, and from then on writes
    ``sigxx = sigyy = sigzz = -max(p,0)`` with all shears 0: compression only,
    no deviator, **element not deleted**. That is exactly Vol II R17 p.2-209's
    *"the element loses its ability to carry tension"*.

    Dispatch verified: ``mmain.F90:2242`` gates the ``/FAIL`` loop on
    ``nfail > 0 .and. (mtn < 28 .or. mtn == 49)`` and LAW21 is ``mtn = 21``;
    the ``do ir = 1,nfail`` loop is a SIBLING of the ``istrain`` block at
    ``:2243``, so it runs regardless of the ``/PROP`` ``istrain`` flag, and the
    spalling criterion reads only ``lbuf%sig``.
    """
    return [
        f"/FAIL/SPALLING/{mid}",
        "#                 D1                  D2                  D3"
        "                  D4                  D5",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#      EPSILON_DOT_0               P_MIN  IFAIL_SO",
        f"{_f(0.0)}{_f(pc)}{_i(1)}",
        HDR,
    ]


def _emit_mat_law90(mat: MatLowDensityViscousFoam) -> List[str]:
    """*MAT_LOW_DENSITY_VISCOUS_FOAM (MAT_073) → /MAT/LAW90 [+ /VISC/PRONY].
    Column layout from LAW90.cfg FORMAT(radioss2022) (the block a /BEGIN 2022
    deck reads — TFLAG/FAIL/Kcont/Tcut are 2024/2026-only and absent here):
    Rho_I; E0 Nu; [NL(10) Ismooth(10) Fcut Shape Hys Alpha]; then NL rows of
    [fct_IDL(10) Eps_dot(20) Fscale(20)]. Fixed values exactly as dyna2rad
    (CM:4289-4299): NL=1 (the single quasi-static loading curve, referenced
    BY ID, rate 0), Ismooth=1, Fcut=0; HU→Hys, SHAPE→Shape; Nu/Alpha/Fscale
    written 0 → starter defaults (0 / 1.0 / 1.0). The Gi/BETAi terms with
    BETAi > 0 ride a /VISC/PRONY of the SAME id (Radioss pairs them by id
    alone — dyna2rad CM:4305-4333; the misleadingly-named radTimeRel/
    radGammaArr there map 1:1 GI→G_i, BETAI→Beta_i)."""
    lines = [
        f"/MAT/LAW90/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              Rho_I",
        f"{_f(mat.rho)}",
        "#                 E0                  Nu",
        f"{_f(mat.E)}{_f(0.0)}",
        "#       NL   Ismooth                Fcut               Shape                 Hys               Alpha",
        f"{_i(1)}{_i(1)}{_f(0.0)}{_f(mat.shape)}{_f(mat.hu)}{_f(0.0)}",
        "#  fct_IDL             Eps_dot              Fscale",
        f"{_i(mat.lcid)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]
    if mat.lcid2 == 0:
        gis = [t[0] for t in mat.prony if t[1] > 0.0]
        betais = [t[1] for t in mat.prony if t[1] > 0.0]
        if gis:
            lines += _emit_visc_prony(mat.mid, gis, betais)
    return lines


def _emit_mat_law50_modified(mat: MatModifiedHoneycomb) -> List[str]:
    """*MAT_MODIFIED_HONEYCOMB (MAT_126) → /MAT/LAW50 (VISC_HONEY). Same
    mat_law50.cfg FORMAT(radioss90) column layout as _emit_mat_law50
    (MAT_063) above, but per-direction: fun_ids/moduli/Iflags come resolved
    from _resolve_mat_modified_honeycomb, TSEF fills the normal Eps_max
    components and SSEF the shear ones (both 0 when negative = the
    unsupported curve form), and the LCSR samples replicate each direction's
    base function into slots 2..5 with Eps_rate = the sampled abscissa and
    Fscale = its ordinate (dyna2rad CM:9196-9208 — rate dependence is a pure
    ordinate scale). The radioss2025-only compaction card (ECOMP NU SIGY ET
    VCOMP) is NOT emitted: under /BEGIN 2022 the starter reads 24 cards and
    a 25th line would be a stray card, not compaction data."""
    e11, e22, e33, g12, g23, g31 = mat.moduli
    n = max(1, len(mat.rates))
    rates = mat.rates or [0.0]
    scales = mat.scales or [1.0]
    tmax = mat.tsef if mat.tsef > 0.0 else 0.0
    smax = mat.ssef if mat.ssef > 0.0 else 0.0

    def _dir(label: str, f: int) -> List[str]:
        fids = [(f if i < n else 0) for i in range(5)]
        fsc = [(scales[i] if i < n and i < len(scales) else 0.0)
               for i in range(5)]
        eps = [(rates[i] if i < n and i < len(rates) else 0.0)
               for i in range(5)]
        return [
            f"#funID{label}-1 funID{label}-2 funID{label}-3 funID{label}-4 funID{label}-5",
            "".join(_i(x) for x in fids),
            f"#        Fscale_{label}-1         Fscale_{label}-2         Fscale_{label}-3         Fscale_{label}-4         Fscale_{label}-5",
            "".join(_f(x) for x in fsc),
            f"#      Eps_rate_{label}-1       Eps_rate_{label}-2       Eps_rate_{label}-3       Eps_rate_{label}-4       Eps_rate_{label}-5",
            "".join(_f(x) for x in eps),
        ]

    f11, f22, f33, f12, f23, f31 = mat.fun_ids
    lines = [
        f"/MAT/LAW50/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                E11                 E22                 E33",
        f"{_f(e11)}{_f(e22)}{_f(e33)}",
        "#                G12                 G23                 G31",
        f"{_f(g12)}{_f(g23)}{_f(g31)}",
        "#             asrate",
        f"{_f(0.0)}",
        "#   Iflag1           Eps_max11           Eps_max22           Eps_max33",
        f"{_i(mat.iflag1)}{_f(tmax)}{_f(tmax)}{_f(tmax)}",
    ]
    lines += _dir("11", f11) + _dir("22", f22) + _dir("33", f33)
    lines += [
        "#   Iflag2           Eps_max12           Eps_max23           Eps_max31",
        f"{_i(mat.iflag2)}{_f(smax)}{_f(smax)}{_f(smax)}",
    ]
    lines += _dir("12", f12) + _dir("23", f23) + _dir("31", f31)
    lines.append(HDR)
    return lines


def _emit_mat_law115(mat: MatDeshpandeFleckFoam) -> List[str]:
    """*MAT_DESHPANDE_FLECK_FOAM (MAT_154) → /MAT/LAW115 (DESHFLECK).
    Column layout from matl115_deshfleck.cfg FORMAT(radioss2021) (the block
    a /BEGIN 2022 deck reads), deterministic Istat=0 branch: RHO_I; [E(20)
    nu(20) Ires(10) Istat(10)]; [ALPHA EPSVP_F SIGP_F]; [SIGP GAMMA EPSD
    ALPHA2 BETA]. LAW115 IS the Deshpande-Fleck surface — no formulation
    selector exists; the hardening constants transfer verbatim (identical
    law sigma_y = SIGP + GAMMA*(e/EPSD) + ALPHA2*ln[1/(1-(e/EPSD)^BETA)]).
    Ires/Istat are written 0 → starter defaults (Newton return mapping,
    deterministic card). CFAIL → EPSVP_F and PFAIL → SIGP_F — the latter is
    a conscious fix over dyna2rad, whose cfg has no PFAIL attribute so its
    CopyValue silently no-ops and SIGP_F is always 0."""
    return [
        f"/MAT/LAW115/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu      Ires     Istat",
        f"{_f(mat.E)}{_f(mat.nu)}{_i(0)}{_i(0)}",
        "#              ALPHA             EPSVP_F              SIGP_F",
        f"{_f(mat.alpha)}{_f(mat.cfail)}{_f(mat.pfail)}",
        "#               SIGP               GAMMA                EPSD              ALPHA2                BETA",
        f"{_f(mat.sigp)}{_f(mat.gamma)}{_f(mat.epsd)}{_f(mat.alpha2)}{_f(mat.beta)}",
        HDR,
    ]


def _emit_mat_law62(mat: MatHillFoam) -> List[str]:
    """*MAT_HILL_FOAM (MAT_177, LCID=0) → /MAT/LAW62 (VISC_HYP). Column
    layout from matl62_visc_hyp.cfg FORMAT(radioss2022): RHO_I; [Nu(20)
    N(10) M(10) mu_max(20) Flag_Visc(10) Flag_Rigi(10)]; then the
    CELL_LIST blocks, 5 cells of 20 columns per line: mu_i (ceil(N/5)
    lines), alpha_i, and nu_i — the nu_i block is part of the 2022 format
    (undocumented in the 2022 Reference Guide but read by the starter), so
    it is emitted explicitly as zeros: any nonzero nu_i would OVERRIDE the
    card-2 Nu (hm_read_mat62.F ITAG branch). M=0 (no Maxwell terms — MAT_177
    has none), mu_max=0 → starter 1e20, Flag_Visc/Flag_Rigi 0 — all exactly
    dyna2rad's fixed values (CM:9889-9891)."""
    nu = _hill_foam_nu(mat.n)
    order = len(mat.mu_i)

    def _rows5(vals: List[float]) -> List[str]:
        return ["".join(_f(v) for v in vals[i:i + 5])
                for i in range(0, len(vals), 5)]

    lines = [
        f"/MAT/LAW62/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                 Nu         N         M              mu_max Flag_Visc Flag_Rigi",
        f"{_f(nu)}{_i(order)}{_i(0)}{_f(0.0)}{_i(0)}{_i(0)}",
    ]
    if order:
        lines.append("#               mu_i")
        lines += _rows5(mat.mu_i)
        lines.append("#            alpha_i")
        lines += _rows5(mat.alpha_i)
        lines.append("#               nu_i")
        lines += _rows5([0.0] * order)
    lines.append(HDR)
    return lines


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


# ─────────────────────────────────────────────────────────────────────────────
# Adhesives / cohesive batch: LAW117, LAW169, LAW116, LAW120, /FAIL/INIEVO
# ─────────────────────────────────────────────────────────────────────────────

def _cohesive_intfail_to_idel(state: ConversionState, kw: str, mid: int,
                              intfail: float) -> int:
    """LS-DYNA INTFAIL → LAW116/117 Idel (failed-IP count to delete).

    INTFAIL > 0 = Gauss scheme, delete at INTFAIL failed IPs; < 0 =
    Newton-Cotes, delete at |INTFAIL|; = 0 = Newton-Cotes and NEVER delete.
    /PROP/TYPE43 integrates at 4 fixed mid-plane Gauss points, so only the
    count carries over: the scheme choice is warned once, and the
    LS-DYNA "never delete" state is inexpressible — the starter coerces
    Idel 0 → 1 (hm_read_mat117.F:141 / mat116:141), i.e. delete on the FIRST
    failed IP, which is warned loudly rather than shipped silently.

    Deliberate deviation from dyna2rad on MAT_240: dyna2rad collapses ANY
    positive INTFAIL to Idel=1 (convertmats.cxx:6754), throwing the count
    away; k2rad transfers |INTFAIL| for both materials.
    """
    if intfail == 0.0:
        state.warn(
            f"{kw} mid={mid}: INTFAIL=0 means the element is NEVER deleted in "
            "LS-DYNA (tractions just stay at their damaged value); Radioss "
            "LAW116/117 has no never-delete state — the starter coerces "
            "Idel 0 -> 1 (delete when 1 of the 4 Gauss points fails). The "
            "element will therefore ERODE in Radioss where LS-DYNA kept it. "
            "Set INTFAIL explicitly (e.g. 4 = all IPs) to control the count.")
        return 0
    if intfail < 0.0:
        state.warn(
            f"{kw} mid={mid}: INTFAIL={intfail:g} < 0 selects the "
            "Newton-Cotes integration scheme in LS-DYNA; /PROP/TYPE43 always "
            "uses 4 mid-plane Gauss points, so only the failed-IP count "
            f"|INTFAIL|={abs(intfail):g} is transferred (Idel).")
    return int(round(abs(intfail)))


def _emit_mat_law117(mat: MatCohesiveMixedMode,
                     state: ConversionState) -> List[str]:
    """*MAT_COHESIVE_MIXED_MODE (138) → /MAT/LAW117. Layout audited against
    hm_cfg_files MAT/mat117.cfg FORMAT(radioss2022) — the block a /BEGIN 2022
    deck is read with (NOT the radioss2021 block, which lacks the whole
    Fct_TN/Fct_TT/Fscale_x card and reads GAMMA as an integer):

      RHO_I(20) /
      EN(20) ET(20) Imass(10) Idel(10) Irupt(10) /
      Fct_TN(10) Fct_TT(10) TN(20) TT(20) Fscale_x(20) /
      GIC(20) GIIC(20) EXP_G(20) EXP_BK(20) GAMMA(20)

    Field semantics follow dyna2rad p_ConvertMatL138 (convertmats.cxx:
    6248-6360): ROFLG 0 → Imass=2 (volume) / 1 → Imass=1 (area) — written
    EXPLICITLY because the starter coerces a blank Imass to 1 (area), which
    would silently flip the LS-DYNA volume-density default; EN/ET copy raw
    (stiffness per unit length on BOTH sides — no thickness rescale); XMU>0 →
    Irupt=1 power law with EXP_G=XMU, XMU<0 → Irupt=2 Benzeggagh-Kenane with
    EXP_BK=|XMU| (EXP_BK has NO starter default, so it must be written);
    T/S<0 → |id| is a peak-traction-vs-element-size curve → Fct_TN/TT with
    TMAX=1.0; T=0 with UND>0 → TN = 2·GIC/UND (the LS-DYNA fallback
    GIC = T·UND/2 inverted); GAMMA copies raw (0 → starter default 1.0, the
    LS-DYNA default — dyna2rad's `GAMMA==0 → 2` branch is dead code, its
    post-handler attribMap copy overwrites it, CM:6357 vs 609).

    Starter floors GIC at TN²/(2·EN) and GIIC at TT²/(2·ET) with its own
    WARNINGs 3016/3017 (hm_read_mat117.F:146-157) — the LS-DYNA identity
    GIC = T·UND/2 keeps consistent inputs below those floors automatically.
    """
    imass = 1 if mat.roflg == 1 else 2
    idel = _cohesive_intfail_to_idel(state, "*MAT_COHESIVE_MIXED_MODE",
                                     mat.mid, mat.intfail)
    gic, giic = mat.gic, mat.giic
    if gic < 0.0:
        state.warn(
            f"*MAT_COHESIVE_MIXED_MODE mid={mat.mid}: GIC={gic:g} < 0 is the "
            f"LS-DYNA curve form (|GIC| = curve {int(abs(gic))} of energy "
            "release rate vs element size); LAW117 has no curve slot for GIC "
            "— the field is left 0 and the starter floors it at TN^2/(2*EN) "
            "with its WARNING 3016. Supply a scalar GIC for the real "
            "toughness.")
        gic = 0.0
    if giic < 0.0:
        state.warn(
            f"*MAT_COHESIVE_MIXED_MODE mid={mat.mid}: GIIC={giic:g} < 0 is "
            f"the LS-DYNA curve form (|GIIC| = curve {int(abs(giic))} vs "
            "element size); LAW117 has no curve slot — left 0, starter floors "
            "it at TT^2/(2*ET) with WARNING 3017.")
        giic = 0.0
    # T: scalar / curve / UND-fallback (dyna2rad CM:6268-6281, 6335-6336).
    fct_tn, tn = 0, 0.0
    if mat.t < 0.0:
        fct_tn, tn = int(round(-mat.t)), 1.0
        if fct_tn not in state.curves:
            state.warn(
                f"*MAT_COHESIVE_MIXED_MODE mid={mat.mid}: T={mat.t:g} "
                f"references load curve {fct_tn} (peak traction vs element "
                "size) that is not in the model — the LAW117 Fct_TN "
                "reference will dangle.")
    elif mat.t > 0.0:
        tn = mat.t
    elif mat.und > 0.0 and gic > 0.0:
        tn = 2.0 * gic / mat.und
    fct_tt, tt = 0, 0.0
    if mat.s < 0.0:
        fct_tt, tt = int(round(-mat.s)), 1.0
        if fct_tt not in state.curves:
            state.warn(
                f"*MAT_COHESIVE_MIXED_MODE mid={mat.mid}: S={mat.s:g} "
                f"references load curve {fct_tt} that is not in the model — "
                "the LAW117 Fct_TT reference will dangle.")
    elif mat.s > 0.0:
        tt = mat.s
    elif mat.utd > 0.0 and giic > 0.0:
        tt = 2.0 * giic / mat.utd
    if tn == 0.0 and fct_tn == 0:
        state.warn(
            f"*MAT_COHESIVE_MIXED_MODE mid={mat.mid}: no peak normal traction "
            "(T=0 and no usable UND/GIC pair to back-compute TN=2*GIC/UND) — "
            "TN is written 0, which LAW117 treats as no mode-I strength. "
            "Check the card.")
    if tt == 0.0 and fct_tt == 0:
        # Mirror of the TN case, and worse in the starter: hm_read_mat117.F:
        # 162-166 derives DELTA0S = TT/ET and then UTD = 2*GIIC/(DELTA0S*ET)
        # — a DIVISION BY ZERO in the derived ultimate displacement when
        # TT = 0.
        state.warn(
            f"*MAT_COHESIVE_MIXED_MODE mid={mat.mid}: no peak shear traction "
            "(S=0 and no usable UTD/GIIC pair to back-compute TT=2*GIIC/UTD) "
            "— TT is written 0, which LAW117 treats as no mode-II strength, "
            "and the starter's derived ultimate displacement "
            "UTD=2*GIIC/(DELTA0S*ET) divides by DELTA0S=TT/ET=0 "
            "(hm_read_mat117.F:162-166). Check the card.")
    # XMU sign = power-law / Benzeggagh-Kenane switch (CM:6305-6316).
    if mat.xmu > 0.0:
        irupt, exp_g, exp_bk = 1, mat.xmu, 0.0
    elif mat.xmu < 0.0:
        irupt, exp_g, exp_bk = 2, 0.0, abs(mat.xmu)
    else:
        irupt, exp_g, exp_bk = 0, 0.0, 0.0   # starter defaults: Irupt 1, EXP_G 2
    return [
        f"/MAT/LAW117/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                 EN                  ET     Imass      Idel     Irupt",
        f"{_f(mat.en)}{_f(mat.et)}{_i(imass)}{_i(idel)}{_i(irupt)}",
        "#   Fct_TN    Fct_TT                  TN                  TT            Fscale_x",
        f"{_i(fct_tn)}{_i(fct_tt)}{_f(tn)}{_f(tt)}{_f(0.0)}",
        "#                GIC                GIIC               EXP_G              EXP_BK               GAMMA",
        f"{_f(gic)}{_f(giic)}{_f(exp_g)}{_f(exp_bk)}{_f(mat.gamma)}",
        HDR,
    ]


def _emit_mat_law169(mat: MatArupAdhesive,
                     state: ConversionState) -> List[str]:
    """*MAT_ARUP_ADHESIVE (169) → /MAT/LAW169 (dyna2rad p_ConvertMatL169).
    Layout audited against hm_cfg_files radioss2025/MAT/LAW169.cfg — the ONLY
    format block this card has:

      Rho_I(20) /
      E(20) PR(20) SHT_SL(20) TENMAX(20) GCTEN(20) /
      SHRMAX(20) GCSHR(20) PWRT(10,int) PWRS(10,int) SHRP(20)

    Two layout traps: SHT_SL moves from *MAT_169 card 2 field 4 to the MIDDLE
    of LAW169 card 2 (between PR and TENMAX), and PWRT/PWRS are floats in
    LS-DYNA but %10d INTEGERS here (rounded, warned when the value changes).

    /MAT/LAW169 is registered only from the radioss2025 profile; under
    k2rad's /BEGIN 2022 the starter prints non-fatal WARNING 100211
    ("Unsupported option ... in format < 2025") and then parses the card with
    the 2025 FORMAT anyway — verified NORMAL TERMINATION with a
    byte-identical field echo vs a /BEGIN 2025 run. The warning below names
    that so the starter output does not read as a conversion defect.

    Everything LAW169 does not implement is warned per field: the rate
    scaling (EDOT0/EDOT2 + SDFAC/SGFAC/SDEFAC/SGEFAC), the EXTRA edge cards,
    THKDIR, BTHK, and the negative-value curve forms of the strengths.
    """
    kw = f"*MAT_ARUP_ADHESIVE mid={mat.mid}"

    def _strength(name: str, v: float) -> float:
        if v < 0.0:
            if name == "SHRP":
                # SHRP is the shear PLATEAU ratio, not a strength: LAW169
                # defaults it to 0 (it is absent from LAW169.cfg's
                # DEFAULTS(COMMON) block — only the four strengths/energies
                # get the 1e20 no-failure default), so the dropped curve
                # leaves NO plateau, not "no failure".
                state.warn(
                    f"{kw}: SHRP={v:g} < 0 is the LS-DYNA curve form "
                    f"(|value| = function {int(abs(v))}); /MAT/LAW169 has "
                    "no curve inputs — SHRP is written 0, i.e. NO shear "
                    "plateau (the LAW169 default). Supply a scalar ratio "
                    "to keep the plateau.")
            else:
                state.warn(
                    f"{kw}: {name}={v:g} < 0 is the LS-DYNA curve form "
                    f"(|value| = function {int(abs(v))}); /MAT/LAW169 has "
                    "no curve inputs — the field is left blank and defaults "
                    f"to 1e20, i.e. NO {name} failure. Supply a scalar to "
                    "keep the failure mode.")
            return 0.0
        return v

    tenmax = _strength("TENMAX", mat.tenmax)
    gcten  = _strength("GCTEN", mat.gcten)
    shrmax = _strength("SHRMAX", mat.shrmax)
    gcshr  = _strength("GCSHR", mat.gcshr)
    shrp   = _strength("SHRP", mat.shrp)

    def _power(name: str, v: float) -> int:
        p = int(round(v)) if v else 2
        if v and abs(v - p) > 1e-9:
            state.warn(
                f"{kw}: {name}={v:g} is not an integer — /MAT/LAW169 reads "
                f"{name} as a %10d integer, so it is ROUNDED to {p}. The "
                "yield-surface exponent changes accordingly.")
        return p

    pwrt = _power("PWRT", mat.pwrt)
    pwrs = _power("PWRS", mat.pwrs)
    if mat.edot0 not in (0.0, 1.0) or mat.edot2 != 0.0:
        state.warn(
            f"{kw}: rate dependence (EDOT0={mat.edot0:g}, EDOT2={mat.edot2:g}"
            " and the SDFAC/SGFAC/SDEFAC/SGEFAC card it gates) has no "
            "/MAT/LAW169 slot — the adhesive converts RATE-INDEPENDENT at "
            "the static strengths/energies. dyna2rad drops the same fields "
            "silently (LAW169.cfg comments them out).")
    if mat.extra in (1, 3):
        state.warn(
            f"{kw}: EXTRA={mat.extra} activates the edge-specific cards "
            "(TMAXE/GCTE/SMAXE/GCSE/PWRTE/PWRSE + FACET/FACCT/FACES/FACCS/"
            "SOFTT/SOFTS) — /MAT/LAW169 has no edge data; interior values "
            "apply everywhere. DROPPED.")
    if mat.extra in (2, 3) and mat.bthk != 0.0:
        state.warn(
            f"{kw}: BTHK={mat.bthk:g} (bond thickness override) has no "
            "/MAT/LAW169 slot — the element's geometric height governs. "
            "DROPPED.")
    if mat.thkdir != 1.0:
        # "Unless THKDIR = 1, the smallest dimension of the element is
        # assumed to be the through-thickness dimension of the bond"
        # (R16 Vol II p.2-1128) — THKDIR=0 is the DEFAULT. /PROP/TYPE43 has
        # no such detection: the bond normal is always face 1-2-3-4 to face
        # 5-6-7-8 (the THKDIR=1 convention, which therefore needs no
        # warning). An element whose smallest dimension is NOT its
        # 1234->5678 axis gets its traction-separation directions rotated
        # 90 deg with no starter complaint.
        state.warn(
            f"{kw}: THKDIR={mat.thkdir:g} means LS-DYNA detects the bond "
            "thickness direction as the SMALLEST dimension of each element; "
            "/PROP/TYPE43 always takes it from face 1-2-3-4 to face 5-6-7-8 "
            "(the THKDIR=1 convention) and LAW169 has no slot to change "
            "that. Verify the element connectivity is oriented with the "
            "bondline as the 1234->5678 axis — otherwise the "
            "traction-separation directions rotate 90 deg SILENTLY.")
    state.warn(
        f"{kw}: /MAT/LAW169 is a radioss2025 card; under the emitted "
        "/BEGIN 2022 header the starter prints non-fatal WARNING 100211 "
        "(\"Unsupported option /MAT/LAW169 in format < 2025\") and then "
        "parses the card with the 2025 layout — verified byte-identical "
        "field echo and NORMAL TERMINATION. No action needed; the warning "
        "is the version gate, not a data error.")
    return [
        f"/MAT/LAW169/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              Rho_I",
        f"{_f(mat.rho)}",
        "#                  E                  PR              SHT_SL              TENMAX               GCTEN",
        f"{_f(mat.e)}{_f(mat.pr)}{_f(mat.sht_sl)}{_f(tenmax)}{_f(gcten)}",
        "#             SHRMAX               GCSHR      PWRT      PWRS                SHRP",
        f"{_f(shrmax)}{_f(gcshr)}{_i(pwrt)}{_i(pwrs)}{_f(shrp)}",
        HDR,
    ]


def _emit_mat_law116(mat: MatCohesiveMMEPR,
                     state: ConversionState) -> List[str]:
    """*MAT_240 (option-free) → /MAT/LAW116. Layout audited against
    hm_cfg_files radioss2021/MAT/mat116.cfg FORMAT(radioss2021) — there is no
    2022 revision, so this is the block a /BEGIN 2022 deck reads with:

      RHO_I(20) /
      E(20) G(20) Thick(20) Imass(10) Idel(10) Icrit(10) /
      GC1_ini(20) GC1_inf(20) SRATG1(20) FG1(20) /
      GC2_ini(20) GC2_inf(20) SRATG2(20) FG2(20) /
      SIGA1(20) SIGB1(20) SRATE1(20) ORDER1(10) FAIL1(10) /
      SIGA2(20) SIGB2(20) SRATE2(20) ORDER2(10) FAIL2(10)

    E/G are TRUE moduli — the starter divides by Thick itself
    (UPARAM(1)=E/THICK, hm_read_mat116.F:197), so no per-length conversion
    here (dividing twice was the trap this comment guards).

    Rate forms follow dyna2rad p_ConvertMatL240 (convertmats.cxx:6619-6757)
    with TWO conscious deviations, both documented in the CHANGELOG:
      * mode II gates GC2_inf/SRATG2 on G2C_0 < 0 — the same convention as
        mode I and as the LS-DYNA manual ("G1C_0 <= 0 activates the
        rate-dependent branch"); dyna2rad gates on EDOT_G2 < 0 (CM:6715), a
        transcription slip that both loses the mode-II reference rate for
        every valid deck (EDOT_G2 is a positive rate) and would smuggle a
        negative one through as-is.
      * Idel carries |INTFAIL| (dyna2rad hard-codes 1, CM:6754).
    INICRT maps onto Icrit against the ENGINE kernel (sigeps116.F:226): 0
    (quadratic nominal stress) → starter default Icrit=1 = quadratic
    interaction; 1/2 (maximum nominal stress) → Icrit=2 = pure-mode maximum
    criterion; negative INICRT (mixed-mode with flexible exponent) has no
    LAW116 slot. dyna2rad never reads the field (its cfg mislabels it
    OUTPUT).
    """
    kw = "*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE"
    imass = 1 if mat.roflg == 1 else 2
    idel = _cohesive_intfail_to_idel(state, kw, mat.mid, mat.intfail)
    icrit = 0
    if mat.inicrt in (1.0, 2.0):
        icrit = 2
        if mat.inicrt == 2.0:
            state.warn(
                f"{kw} mid={mat.mid}: INICRT=2 additionally outputs the "
                "maximum nominal strain as LS-DYNA history variable #15 — "
                "LAW116 has no such output; the criterion itself (maximum "
                "nominal stress, Icrit=2) is converted.")
    elif mat.inicrt < 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: INICRT={mat.inicrt:g} < 0 selects the "
            f"mixed-mode initiation criterion with exponent {abs(mat.inicrt):g}"
            " — LAW116 only has the quadratic (Icrit=1) and maximum-stress "
            "(Icrit=2) criteria; left at the quadratic default.")
    elif mat.inicrt != 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: INICRT={mat.inicrt:g} is not a defined "
            "LS-DYNA value (0/1/2 or negative exponent) — left at the "
            "quadratic default Icrit=1.")
    # THICK "LE.0.0: initial thickness is calculated from nodal coordinates"
    # (R16) — zero and negative are the same LS-DYNA state. The starter's
    # default guard is `IF (THICK == ZERO)` ONLY (hm_read_mat116.F:149-151),
    # so a negative value copied through would survive to UPARAM(1)=E/THICK
    # as a NEGATIVE stiffness; it is written 0.0 instead so the starter's
    # 1.0-length-unit default applies (and is warned like the zero case).
    thick = max(mat.thick, 0.0)
    if mat.thick <= 0.0:
        state.warn(
            f"{kw} mid={mat.mid}: THICK={mat.thick:g} <= 0 means LS-DYNA "
            "uses each element's GEOMETRIC thickness for the cohesive "
            "stiffness EMOD/thickness; LAW116 instead defaults a zero Thick "
            "to 1.0 LENGTH UNIT (hm_read_mat116.F:149-152), so the "
            "stiffness becomes E/1.0 regardless of the element height "
            "(a negative Thick is written 0 — copied raw it would pass the "
            "starter's ==0 guard and turn into a NEGATIVE stiffness "
            "E/Thick). Set THICK to the real adhesive-layer thickness (or "
            "add *SECTION_SOLID_MISC COHTHK) for matching stiffness.")
    # Mode I toughness/yield rate forms. T1/EDOT_T are "only considered if
    # T0 < 0" (R16 Vol II p.2-1545) — at the static limit (T0 >= 0) LS-DYNA
    # runs a constant yield |T0| whatever sits in T1/EDOT_T, while the LAW116
    # ENGINE switches rate hardening on for ANY SIGB1 > 0 (sigeps116.F:143:
    # YLD = SIGA1 + SIGB1*LOG(EPSP/RATE1), and the starter fills ORDER 0 -> 1,
    # hm_read_mat116.F:142). So the rate terms are gated on T0's sign, with a
    # warning when that zeroes live fields; dyna2rad copies them
    # unconditionally (CM:6725) — the same defect class as its EDOT_G2 slip.
    rate1 = mat.g1c_0 < 0.0
    gc1_ini = abs(mat.g1c_0)
    gc1_inf = abs(mat.g1c_inf) if rate1 else 0.0
    sratg1 = mat.edot_g1 if rate1 else 0.0
    siga1 = abs(mat.t0)
    sigb1 = abs(mat.t1) if mat.t0 < 0.0 else 0.0
    srate1 = mat.edot_t if sigb1 > 0.0 else 0.0
    order1 = 2 if (mat.t0 < 0.0 and mat.t1 > 0.0) else \
        (1 if (mat.t0 < 0.0 and mat.t1 < 0.0) else 0)
    fail1 = 1 if mat.fg1 > 0.0 else (2 if mat.fg1 < 0.0 else 0)
    # Mode II — same gate as mode I (G2C_0 < 0), NOT dyna2rad's EDOT_G2 < 0.
    rate2 = mat.g2c_0 < 0.0
    gc2_ini = abs(mat.g2c_0)
    gc2_inf = abs(mat.g2c_inf) if rate2 else 0.0
    sratg2 = mat.edot_g2 if rate2 else 0.0
    siga2 = abs(mat.s0)
    sigb2 = abs(mat.s1) if mat.s0 < 0.0 else 0.0
    srate2 = mat.edot_s if sigb2 > 0.0 else 0.0
    order2 = 2 if (mat.s0 < 0.0 and mat.s1 > 0.0) else \
        (1 if (mat.s0 < 0.0 and mat.s1 < 0.0) else 0)
    fail2 = 1 if mat.fg2 > 0.0 else (2 if mat.fg2 < 0.0 else 0)
    for mode, x0, x1, xdot in (("I (T0)", mat.t0, mat.t1, mat.edot_t),
                               ("II (S0)", mat.s0, mat.s1, mat.edot_s)):
        if x0 >= 0.0 and (x1 != 0.0 or xdot != 0.0):
            state.warn(
                f"{kw} mid={mat.mid}: mode {mode} static yield "
                f"{x0:g} >= 0 — LS-DYNA considers the rate terms "
                f"({x1:g}/{xdot:g}) ONLY when the yield field is negative, "
                "but LAW116 activates rate hardening for any SIGB > 0 "
                "(sigeps116.F:143) — SIGB/SRATE are zeroed to keep the "
                "constant yield LS-DYNA ran. Make the yield field negative "
                "in the source deck if rate dependence was intended.")
    for mode, fg, gc in ((1, mat.fg1, gc1_ini), (2, mat.fg2, gc2_ini)):
        if fg == 0.0 or gc == 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: FG{mode}={fg:g} / G{mode}C_0={gc:g} — "
                "the starter DISABLES the mode-"
                + ("I" if mode == 1 else "II")
                + " failure criterion when either is zero (hm_read_mat116.F:"
                "147-148, IFAIL:=0): the traction-separation law then never "
                "softens in that mode. If failure was intended, supply both.")
    for name, lc in (("LCG1C", mat.lcg1c), ("LCG2C", mat.lcg2c)):
        if lc:
            state.warn(
                f"{kw} mid={mat.mid}: {name}={lc} (fracture toughness vs "
                "cohesive thickness curve) has no /MAT/LAW116 slot — LS-DYNA "
                "IGNORES G*C_0/G*C_INF when this curve is set, so the "
                "scalar toughness k2rad emits is NOT what the LS-DYNA run "
                "used unless the curve is flat. Replace the curve by its "
                "value at the actual bondline thickness.")
    if any((mat.rfiltf, mat.compy, mat.smolim, mat.xmu)):
        state.warn(
            f"{kw} mid={mat.mid}: optional card 6 (RFILTF={mat.rfiltf:g}, "
            f"COMPY={mat.compy:g}, SMOLIM={mat.smolim:g}, XMU={mat.xmu:g}) "
            "has no /MAT/LAW116 counterpart — rate filtering, "
            "yield-in-compression and the mixed-mode exponent are DROPPED "
            "(LAW116 filters the rate with a fixed exponential-average "
            "ALPHA=0.005, hm_read_mat116.F:153).")
    return [
        f"/MAT/LAW116/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                   G               Thick     Imass      Idel     Icrit",
        f"{_f(mat.emod)}{_f(mat.gmod)}{_f(thick)}{_i(imass)}{_i(idel)}{_i(icrit)}",
        "#            GC1_ini             GC1_inf              SRATG1                 FG1",
        f"{_f(gc1_ini)}{_f(gc1_inf)}{_f(sratg1)}{_f(abs(mat.fg1))}",
        "#            GC2_ini             GC2_inf              SRATG2                 FG2",
        f"{_f(gc2_ini)}{_f(gc2_inf)}{_f(sratg2)}{_f(abs(mat.fg2))}",
        "#              SIGA1               SIGB1              SRATE1    ORDER1     FAIL1",
        f"{_f(siga1)}{_f(sigb1)}{_f(srate1)}{_i(order1)}{_i(fail1)}",
        "#              SIGA2               SIGB2              SRATE2    ORDER2     FAIL2",
        f"{_f(siga2)}{_f(sigb2)}{_f(srate2)}{_i(order2)}{_i(fail2)}",
        HDR,
    ]


def _emit_mat_law120(mat: MatToughenedAdhesive,
                     state: ConversionState) -> List[str]:
    """*MAT_TOUGHENED_ADHESIVE_POLYMER (252) → /MAT/LAW120 (TAPO). Layout
    audited against hm_cfg_files radioss2022/MAT/mat120_tapo.cfg
    FORMAT(radioss2022):

      RHO_I(20)                     <- cols 21-40 MUST stay blank: a
                                       CARD_PREREAD there switches the reader
                                       to the two-field reference-density form
      E(20) nu(20) Iform(10) Itrx(10) Idam(10) blank(10) THICK(20) /
      Table_Id(10) Xscale(20) Yscale(20) /
      T0(20) Q(20) Beta(20) H(20) /
      AF1(20) AF2(20) AH1(20) AH2(20) AS(20) /
      C(20) EPSD0(20) EPSDF(20) /
      D1C(20) D2C(20) D1F(20) D2F(20) /
      Dtrx(20) Djc(20) EXP_N(20)

    Copies follow dyna2rad p_ConvertMatL252 (convertmats.cxx:6759-6815)
    including D1→D1F, D2→D2F, D3→Dtrx, D4→Djc — LAW120 IS the TAPO model, so
    the Johnson-Cook-style damage constants map 1:1. Flag enums verified
    against the ENGINE kernels (sigeps120_*.F:108-111): FLG 0 → Iform=1
    (Drucker-Prager cap) / 2 → Iform=2 (von Mises); JCFL 0 → Itrx=2 (no
    pressure dependency for T<0, i.e. triaxiality factor in tension only) /
    1 → Itrx=1 (pressure dependent for ALL T); DOPT 0 → Idam=2 (damage
    plastic strain, increments scaled by 1-D) / 1 → Idam=1 (plain plastic
    arc length). The JCFL=1/DOPT=1 branches are conscious FIXES of dyna2rad,
    whose switch tests `== 2` (dead — JCFL/DOPT are 0/1 in LS-DYNA) and so
    silently converts JCFL=1 decks to tension-only triaxiality (CM:6783-6790).

    When LCSS is set both codes ignore the analytic yield inputs (LS-DYNA
    drops TAU0..GAMM; the LAW120 reader zeroes Y0/Q/B/H/EPSPMIN/EPSPMAX,
    hm_read_mat120.F:183-189), so copying both is exact either way.
    """
    kw = f"*MAT_TOUGHENED_ADHESIVE_POLYMER mid={mat.mid}"
    if mat.flg == 0:
        iform = 1
    elif mat.flg == 2:
        iform = 2
    else:
        iform = 0
        state.warn(
            f"{kw}: FLG={mat.flg} is not a defined LS-DYNA value (0 = "
            "Drucker-Prager cap, 2 = von Mises cap) — Iform left at the "
            "starter default 1 (Drucker-Prager).")
    if mat.jcfl == 0:
        itrx = 2
    elif mat.jcfl == 1:
        itrx = 1
    else:
        itrx = 0
        state.warn(
            f"{kw}: JCFL={mat.jcfl} is not a defined LS-DYNA value (0/1) — "
            "Itrx left at the starter default 2 (triaxiality factor in "
            "tension only).")
    if mat.dopt == 0:
        idam = 2
    elif mat.dopt == 1:
        idam = 1
    else:
        idam = 0
        state.warn(
            f"{kw}: DOPT={mat.dopt} is not a defined LS-DYNA value (0/1) — "
            "Idam left at the starter default 2 (damage plastic strain).")
    if mat.srfilt != 0.0:
        state.warn(
            f"{kw}: SRFILT={mat.srfilt:g} (exponential-moving-average strain-"
            "rate filter) has no /MAT/LAW120 slot — the rate entering the "
            "C/GAM0/GAMM terms and the D_JC damage factor is unfiltered. "
            "DROPPED.")
    if mat.ihis != 0.0:
        # IHIS >= 1 is INPUT, not output: it reads per-element scaling
        # factors for stiffness/plasticity/damage (and a pre-damage D2) from
        # *INITIAL_STRESS_SOLID history data — process-simulation mapping
        # (R16 Vol II p.2-1663 + Remark 1).
        state.warn(
            f"{kw}: IHIS={mat.ihis:g} initializes stiffness/plasticity/"
            "damage parameters PER ELEMENT from *INITIAL_STRESS_SOLID "
            "history data (prior process simulation, R16 Remark 1) — "
            "/MAT/LAW120 has no such input, so that initialization is LOST "
            "and every element starts from the nominal card values. "
            "DROPPED.")
    return [
        f"/MAT/LAW120/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu     Iform      Itrx      Idam                           THICK",
        f"{_f(mat.e)}{_f(mat.pr)}{_i(iform)}{_i(itrx)}{_i(idam)}{' ' * 10}{_f(0.0)}",
        "# Table_Id              Xscale              Yscale",
        f"{_i(mat.lcss)}{_f(0.0)}{_f(0.0)}",
        "#                 T0                   Q                Beta                   H",
        f"{_f(mat.tau0)}{_f(mat.q)}{_f(mat.b)}{_f(mat.h)}",
        "#                AF1                 AF2                 AH1                 AH2                  AS",
        f"{_f(mat.a10)}{_f(mat.a20)}{_f(mat.a1h)}{_f(mat.a2h)}{_f(mat.a2s)}",
        "#                  C               EPSD0               EPSDF",
        f"{_f(mat.c)}{_f(mat.gam0)}{_f(mat.gamm)}",
        "#                D1C                 D2C                 D1F                 D2F",
        f"{_f(mat.d1c)}{_f(mat.d2c)}{_f(mat.d1)}{_f(mat.d2)}",
        "#               Dtrx                 Djc               EXP_N",
        f"{_f(mat.d3)}{_f(mat.d4)}{_f(mat.pow)}",
        HDR,
    ]


def _diem_collapse_q1_table(state: ConversionState, mid: int,
                            tid: int) -> float:
    """DETYP=0 with Q1 < 0: |Q1| is a plastic-displacement table (vs
    triaxiality and damage). /FAIL/INIEVO DISP is a scalar, so dyna2rad
    collapses the table to its MINIMUM ordinate — the most conservative
    (earliest-failing) displacement (convertmats.cxx:10335-10475). k2rad
    reproduces that and says so. k2rad curve points are stored already
    scaled ((y+OFFO)·SFO baked in at parse), so the minimum is direct."""
    ys: List[float] = []
    curve = state.curves.get(tid)
    if curve is not None and curve.pts:
        ys = [y for _, y in curve.pts]
    else:
        tab = state.define_tables.get(tid)
        if tab is not None and tab.resolved:
            for _, lcid in tab.rows:
                c = state.curves.get(lcid)
                if c is not None:
                    ys.extend(y for _, y in c.pts)
    if not ys:
        state.warn(
            f"*MAT_ADD_DAMAGE_DIEM mid={mid}: Q1 references table/curve "
            f"{tid} which is not in the model — the plastic displacement at "
            "failure is written 0, which /FAIL/INIEVO rejects (starter "
            "ERROR 2089). Define the table or give Q1 as a scalar.")
        return 0.0
    dmin = min(ys)
    state.warn(
        f"*MAT_ADD_DAMAGE_DIEM mid={mid}: Q1 is the table form (|Q1|={tid}, "
        "plastic displacement at failure vs triaxiality/damage) — "
        "/FAIL/INIEVO DISP is a scalar, so the table is COLLAPSED to its "
        f"minimum ordinate {dmin:g} (the most conservative displacement; "
        "same rule as dyna2rad). Elements at other triaxialities fail "
        "earlier than in LS-DYNA.")
    return dmin


def _emit_fail_inievo(diem: FailDiem, state: ConversionState) -> List[str]:
    """*MAT_ADD_DAMAGE_DIEM → /FAIL/INIEVO. Layout audited against
    hm_cfg_files radioss2022/FAIL/fail_inievo.cfg FORMAT(radioss2022) and
    hm_read_fail_inievo.F — no title line, bound by the trailing mat id:

      C1  NINIEVO(10) ISHEAR(10) ILEN(10) blank(40) FAILIP(10) PTHICKFAIL(20)
      then EXACTLY four lines per criterion, NINIEVO times, no separators:
      L2  INITYPE(10) EVOTYPE(10) EVOSHAP(10) COMPTYP(10)
      L3  TAB_ID(10) SR_REF(20) FSCALE(20) PARAM(20)
      L4  TAB_EL(10) EL_REF(20) ELSCAL(20)
      L5  DISP(20) ALPHA(20) ENER(20)      <- DISP, ALPHA, ENER — the
                                              starter's own listing prints a
                                              different order; the CARD is
                                              this one.

    Mapping follows dyna2rad p_ConvertMatAddDamageDiem (convertmats.cxx:
    10111-10515): DITYP 0..4 → INITYPE 1..5 (same criterion order), P1 →
    TAB_ID, P2/P3 → PARAM per DITYP, P5 → TAB_EL, DETYP 0/1 → EVOTYPE 1/2,
    DCTYP 0/1 → COMPTYP 1/2, Q1 → DISP or ENER, Q3 → ALPHA with EVOSHAP=2,
    P4 → ISHEAR INVERTED (LS-DYNA P4=0 *includes* the transverse shear
    stresses, Radioss ISHEAR=1 *considers* them — hm_read_fail_inievo.F:
    291-293 — so the flags have opposite sense and d2r's inversion is
    correct; written explicitly because the Radioss blank default 0 would
    silently EXCLUDE what the LS-DYNA default includes).

    Deliberate deviations from dyna2rad, each warned: NUMFIP resolves
    against the parts that actually reference this MID (FAILIP for solid
    use, PTHICKFAIL via the same NUMFIP rule /FAIL/GENE1 uses for shell use)
    instead of d2r's whole-model element-count heuristic with its stale
    per-part NIP; and a conflicting per-criterion P4 is warned (d2r lets the
    last criterion win silently — the last still wins here, for parity).
    """
    mid = diem.mid
    kw = f"*MAT_ADD_DAMAGE_DIEM mid={mid}"
    if not diem.criteria:
        state.warn(f"{kw}: NDIEMC={diem.ndiemc} defines no criterion — no "
                   "/FAIL/INIEVO emitted.")
        return []
    if diem.dinit != 0.0:
        state.warn(f"{kw}: DINIT={diem.dinit:g} (initial damage) has no "
                   "/FAIL/INIEVO slot — the damage starts at 0. DROPPED.")
    if diem.deps != 0.0:
        state.warn(f"{kw}: DEPS={diem.deps:g} has no /FAIL/INIEVO slot. "
                   "DROPPED.")
    if diem.volfrac not in (0.0, 0.5):
        state.warn(f"{kw}: VOLFRAC={diem.volfrac:g} (failed-volume fraction "
                   "for solid deletion) has no /FAIL/INIEVO slot — solids "
                   "delete on the FAILIP failed-IP count instead. DROPPED.")
    solid_pids = {e.pid for e in state.solid_elems}
    shell_pids = {e.pid for e in state.shell_elems}
    solid_use = any(p.mid == mid and pid in solid_pids
                    for pid, p in state.parts.items())
    shell_use = any(p.mid == mid and pid in shell_pids
                    for pid, p in state.parts.items())
    failip = 0
    pthk = 0.0
    if solid_use and diem.numfip > 0.0:
        failip = int(round(diem.numfip))
    if shell_use:
        numfip = diem.numfip
        if numfip < -100.0:
            # _numfip_to_pthickfail carries *MAT_ADD_EROSION's
            # "NUMFIP < -100 -> (|NUMFIP|-100) integration points"
            # convention; DIEM has NO such form — its LT.0 is a percentage
            # of layers only (R16 Vol II p.2-56) — so a raw pass-through
            # would silently reinterpret the field as an IP count.
            state.warn(
                f"{kw}: NUMFIP={diem.numfip:g} < -100 — *MAT_ADD_DAMAGE_"
                "DIEM defines a negative NUMFIP as a PERCENTAGE of layers "
                "only (the *MAT_ADD_EROSION '(|NUMFIP|-100) integration "
                "points' form does not exist for DIEM) — clamped to -100, "
                "i.e. ALL layers must fail.")
            numfip = -100.0
        pthk, needs_nptt = _numfip_to_pthickfail(
            numfip, _shell_nptt_for_mid(state, mid))
        if needs_nptt:
            state.warn(
                f"{kw}: NUMFIP={diem.numfip:g} is an integration-point count "
                "but no *SECTION_SHELL NIP was found for the material — "
                "PTHICKFAIL left at the default (delete on the first failed "
                "IP). Verify the shell integration scheme.")
    if solid_use and diem.numfip < 0.0:
        state.warn(
            f"{kw}: NUMFIP={diem.numfip:g} < 0 is the percent-of-layers form, "
            "defined for shells; the material also has SOLID parts, whose "
            "FAILIP (failed-IP count) cannot take a percentage — FAILIP is "
            "left at the default 1 for them.")
    # ISHEAR: per-criterion P4, inverted; conflict warned, last wins (d2r
    # parity — CM:10273 writes the global from inside the per-criterion loop).
    ishear_vals = [1 if c.p4 == 0.0 else 0 for c in diem.criteria]
    if len(set(ishear_vals)) > 1:
        state.warn(
            f"{kw}: the criteria disagree on P4 (plane-stress transverse-"
            f"shear flag): {[c.p4 for c in diem.criteria]} — /FAIL/INIEVO "
            "has ONE global ISHEAR, so the LAST criterion's value "
            f"(ISHEAR={ishear_vals[-1]}) applies to all of them (same "
            "last-wins rule as dyna2rad, but warned).")
    ishear = ishear_vals[-1]
    lines = [
        f"/FAIL/INIEVO/{mid}",
        "#  NINIEVO    ISHEAR      ILEN                                                  FAILIP          PTHICKFAIL",
        f"{_i(len(diem.criteria))}{_i(ishear)}{_i(0)}{' ' * 40}{_i(failip)}{_f(pthk)}",
    ]
    for n, c in enumerate(diem.criteria, start=1):
        if 0 <= c.dityp <= 4:
            initype = c.dityp + 1
        else:
            initype = 0
            state.warn(f"{kw}: criterion {n}: DITYP={c.dityp} is not a "
                       "defined LS-DYNA value (0..4) — INITYPE left at the "
                       "starter default 1 (ductile, triaxiality).")
        if c.detyp in (0, 1):
            evotype = c.detyp + 1
        else:
            evotype = 0
            state.warn(f"{kw}: criterion {n}: DETYP={c.detyp} is not a "
                       "defined LS-DYNA value (0/1) — EVOTYPE left at the "
                       "starter default (plastic displacement).")
        if c.dctyp in (0, 1):
            comptyp = c.dctyp + 1
        else:
            comptyp = 0
            if c.dctyp == -1:
                state.warn(
                    f"{kw}: criterion {n}: DCTYP=-1 (damage NOT coupled to "
                    "the stress) has no /FAIL/INIEVO counterpart — COMPTYP "
                    "falls to the default 1 (maximum damage), so this "
                    "criterion DOES soften the stress in Radioss. Remove the "
                    "criterion if it was output-only.")
            else:
                state.warn(f"{kw}: criterion {n}: DCTYP={c.dctyp} is not a "
                           "defined LS-DYNA value (-1/0/1) — COMPTYP left at "
                           "the starter default 1 (maximum damage).")
        if c.p1 == 0:
            state.warn(
                f"{kw}: criterion {n}: P1=0 — the initiation curve/table is "
                "MANDATORY (TAB_ID=0 is starter ERROR 2088). The card is "
                "emitted as-is so the starter names it; supply P1.")
        if c.dityp in (1, 4):
            param = c.p2
        elif c.dityp in (2, 3):
            param = c.p3
            if c.p2 != 0.0:
                state.warn(
                    f"{kw}: criterion {n}: P2={c.p2:g} (MSFLD/FLD layer "
                    "selection, 0=mid 1=outer) has no /FAIL/INIEVO slot — "
                    "the criterion evaluates per integration point. DROPPED.")
        else:
            param = 0.0
        if c.dityp == 1 and c.p3 != 0.0:
            state.warn(
                f"{kw}: criterion {n}: P3={c.p3:g} (shell shear-stress "
                "formulation flag for DITYP=1) has no /FAIL/INIEVO slot. "
                "DROPPED.")
        disp, alpha, ener, evoshap = 0.0, 0.0, 0.0, 0
        if evotype == 2:
            ener = c.q1
            if ener <= 0.0:
                state.warn(
                    f"{kw}: criterion {n}: DETYP=1 (energy evolution) needs "
                    f"a positive fracture energy, got Q1={c.q1:g} — "
                    "/FAIL/INIEVO rejects ENER=0 (starter ERROR 2090).")
        else:
            if c.q1 > 0.0:
                disp = c.q1
                if c.q3 > 0.0:
                    alpha, evoshap = c.q3, 2
            elif c.q1 < 0.0:
                disp = _diem_collapse_q1_table(state, mid,
                                               int(round(-c.q1)))
            else:
                state.warn(
                    f"{kw}: criterion {n}: DETYP=0 (displacement evolution) "
                    f"needs a positive plastic displacement, got Q1={c.q1:g} "
                    "— /FAIL/INIEVO rejects DISP=0 (starter ERROR 2089).")
        if c.q3 > 0.0 and evoshap == 0 and evotype != 2 and c.q1 < 0.0:
            state.warn(
                f"{kw}: criterion {n}: Q3={c.q3:g} (nonlinear evolution "
                "exponent) applies only to a SCALAR Q1 in LS-DYNA — with the "
                "table form it is ignored there and here (linear evolution).")
        if c.q4 != 0.0:
            state.warn(
                f"{kw}: criterion {n}: Q4={c.q4:g} (regularization curve "
                "scaling Q1 by element size) has no /FAIL/INIEVO slot — "
                "only the initiation-side regularization (P5 → TAB_EL) "
                "carries over. DROPPED.")
        lines += [
            "#  INITYPE   EVOTYPE   EVOSHAP   COMPTYP",
            f"{_i(initype)}{_i(evotype)}{_i(evoshap)}{_i(comptyp)}",
            "#   TAB_ID              SR_REF              FSCALE               PARAM",
            f"{_i(c.p1)}{_f(0.0)}{_f(0.0)}{_f(param)}",
            "#   TAB_EL              EL_REF              ELSCAL",
            f"{_i(c.p5)}{_f(0.0)}{_f(0.0)}",
            "#               DISP               ALPHA                ENER",
            f"{_f(disp)}{_f(alpha)}{_f(ener)}",
        ]
    lines.append(HDR)
    return lines


def _resolve_mat_adhesives(state: ConversionState) -> None:
    """Adhesives-batch curve wiring — build_starter prepass, AFTER
    _resolve_define_tables (table membership must be final) and BEFORE
    _make_functions (curves consumed through TABLE slots must be re-routed to
    1-D /TABLE/1 via state.table_1d_ids — the LAW76/LAW52 mechanism).

    /MAT/LAW120's Table_Id and /FAIL/INIEVO's TAB_ID/TAB_EL are TABLE slots
    (read through the starter's table interface), so a *DEFINE_CURVE
    referenced there must be emitted as /TABLE/1, not /FUNCT. A
    *DEFINE_TABLE keeps its id (already a /TABLE/1). Dangling references are
    warned here, naming the starter error the user would otherwise meet.
    MAT_138's Fct_TN/Fct_TT are FUNCTION slots — their curves stay /FUNCT
    (checked at emit time). The DIEM Q1 displacement tables are NOT wired:
    they are collapsed to a scalar at emit and never referenced.

    Also warns two batch-wide semantic traps that need the resolved model:
    a DIEM P1 table whose first rate value is negative (LS-DYNA's
    log-rate-axis convention, which /TABLE reads literally) and a cohesive
    material referenced by SHELL parts (starter ERROR 3046/658 — Radioss has
    no cohesive-shell element).
    """
    for mat in state.mat_toughened_adhesive.values():
        if mat.lcss == 0:
            continue
        if mat.lcss in state.curves:
            state.table_1d_ids.add(mat.lcss)
        elif mat.lcss in state.define_tables:
            tab = state.define_tables[mat.lcss]
            if not tab.resolved:
                state.warn(
                    f"*MAT_TOUGHENED_ADHESIVE_POLYMER mid={mat.mid}: "
                    f"LCSS={mat.lcss} references a *DEFINE_TABLE that could "
                    "not be resolved — the /MAT/LAW120 Table_Id will dangle "
                    "(starter ERROR 779) and the analytic TAU0/Q/B/H "
                    "parameters (which both codes ignore when a table is "
                    "set) will NOT take over. Fix the table or clear LCSS.")
        else:
            state.warn(
                f"*MAT_TOUGHENED_ADHESIVE_POLYMER mid={mat.mid}: "
                f"LCSS={mat.lcss} references a *DEFINE_CURVE/_TABLE that is "
                "not in the deck — the /MAT/LAW120 Table_Id will dangle "
                "(starter ERROR 779).")
    for diem in state.fail_diem.values():
        for n, c in enumerate(diem.criteria, start=1):
            for name, tid in (("P1", c.p1), ("P5", c.p5)):
                if tid == 0:
                    continue
                if tid in state.curves:
                    state.table_1d_ids.add(tid)
                elif tid in state.define_tables:
                    # "If the first strain rate value in the table is
                    # negative, it is assumed to be given with respect to
                    # logarithmic strain rate" — the R16 P1 description for
                    # every DITYP. Radioss /TABLE interpolation reads the
                    # same abscissae as LITERAL rates, silently changing the
                    # rate axis. (P5 has no such convention — its table axes
                    # are element size and the P1-criterion abscissa.)
                    tab = state.define_tables[tid]
                    if (name == "P1" and tab.resolved and tab.rows
                            and tab.rows[0][0] < 0.0):
                        state.warn(
                            f"*MAT_ADD_DAMAGE_DIEM mid={diem.mid}: criterion "
                            f"{n}: P1 table {tid} has a NEGATIVE first "
                            f"strain-rate value ({tab.rows[0][0]:g}) — "
                            "LS-DYNA then reads the whole rate axis as "
                            "LOGARITHMIC strain rate; /FAIL/INIEVO TAB_ID "
                            "interpolation reads the same values as LITERAL "
                            "rates. Rewrite the table's rate values as "
                            "exp(value) to keep the LS-DYNA axis.")
                else:
                    state.warn(
                        f"*MAT_ADD_DAMAGE_DIEM mid={diem.mid}: criterion "
                        f"{n}: {name}={tid} references a curve/table that is "
                        "not in the deck — the /FAIL/INIEVO "
                        + ("TAB_ID" if name == "P1" else "TAB_EL")
                        + " reference will dangle (starter ERROR 779).")
    # Cohesive material on SHELL parts: legal in LS-DYNA (MAT_138/240 run on
    # cohesive shells, *SECTION_SHELL ELFORM 29; MAT_169 is solids-only there
    # too) but Radioss has NO cohesive shell element — the conversion emits
    # /MAT/LAW116/117/169 + /PROP/SHELL and the starter refuses the pair
    # (live-confirmed: ERROR 3046 "ELEMENTS OF TYPE SHELL ARE NOT COMPATIBLE
    # WITH MATERIAL ... TYPE 117" + ERROR 658). Without this warning the only
    # k2rad message is the generic ELFORM->Ishell remap note, which mislabels
    # the cohesive-shell formulation as an ordinary integration choice.
    cohesive_shell_fams = (
        ("*MAT_COHESIVE_MIXED_MODE", state.mat_cohesive_mixed_mode, 117),
        ("*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE",
         state.mat_cohesive_mm_epr, 116),
        ("*MAT_ARUP_ADHESIVE", state.mat_arup_adhesive, 169),
    )
    if any(fam for _, fam, _ in cohesive_shell_fams):
        shell_pids = {e.pid for e in state.shell_elems}
        for kwname, fam, law in cohesive_shell_fams:
            for mid in fam:
                pids = sorted(pid for pid, p in state.parts.items()
                              if p.mid == mid and pid in shell_pids)
                if pids:
                    state.warn(
                        f"{kwname} mid={mid}: SHELL part(s) {pids} reference "
                        "this cohesive material — Radioss has NO "
                        "cohesive-shell element (LS-DYNA's *SECTION_SHELL "
                        f"ELFORM 29 path), so the emitted /MAT/LAW{law} + "
                        "/PROP/SHELL pairing is refused by the starter "
                        f"(ERROR 3046 'ELEMENTS OF TYPE SHELL ARE NOT "
                        f"COMPATIBLE WITH MATERIAL ... TYPE {law}' + ERROR "
                        "658). Model the bondline with cohesive SOLIDS "
                        "(*SECTION_SOLID ELFORM 19/20) to convert it.")


# ─────────────────────────────────────────────────────────────────────────────
# Tabulated Johnson-Cook batch: *MAT_224 → /MAT/LAW109 [+ /FAIL/TAB1],
# *DEFINE_TABLE_3D → /TABLE/1 Ndim=3
# ─────────────────────────────────────────────────────────────────────────────

def _interp_curve(pts: List[Tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation on a curve's points, clamped at the
    ends — the same lookup the starter's own function reader performs."""
    if not pts:
        return 0.0
    p = sorted(pts)
    if x <= p[0][0]:
        return p[0][1]
    if x >= p[-1][0]:
        return p[-1][1]
    for (x0, y0), (x1, y1) in zip(p, p[1:]):
        if x0 <= x <= x1:
            return y1 if x1 == x0 else y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return p[-1][1]


# /FUNCT and /TABLE share ONE starter id namespace (hm_read_table.F:88 counts
# "/TABLE + /FUNCT" into one UDOUBLE duplicate scan → ERROR 79), so EVERY
# synthesized curve or table allocates through state.next_curve_id(), which
# dodges the curve registry AND the three table registries.


# The engine clamps the ISMOOTH=2/3 log-interpolation SAMPLE to 1e-10
# (table2d_vinterp_log.F:206 XX2=MAX(XX,EM10)) but then EXTRAPOLATES in
# log10 with the bracket clamped to the first axis interval — at the zero
# plastic strain rate every element carries through its whole elastic phase,
# R2 = (log10(x2)-log10(1e-10))/(log10(x2)-log10(x1)) reaches O(5..10) and
# the yield goes NEGATIVE (e.g. rates [1,100,1000]: 6*Y1-5*Y2), which
# silently diverges the run (measured: dt collapse 3.8e-8 → 1.6e-9 s with
# I-ENERGY < 0 under NORMAL TERMINATION). A duplicate of the LOWEST-rate
# curve anchored at exactly 1e-10 makes the below-range lookup identically
# FLAT (at the clamp R2 == 1), which is LS-DYNA's own behaviour — table
# lookups clamp to the closest curve outside the tabulated rate range.
_LOG_RATE_ANCHOR = 1.0e-10


def _rate_table_autotable(state: ConversionState, rows, title: str) -> int:
    """Register a 2-D (εp, rate) AutoTable for LAW109's tab_ID_h from *rows*
    = [(rate, fct_id)] (already exp()-unwrapped if the deck used a natural-log
    axis), adding BOTH flat-extrapolation clamp rows that reproduce LS-DYNA's
    outside-the-range behaviour under I_smooth=2:

      * the last curve duplicated at 10·max+1 — dyna2rad's high-rate sentinel
        (CM:11231), starter-verified;
      * the FIRST curve duplicated at the engine's own sample clamp 1e-10 —
        without it the log10 lookup extrapolates below the lowest rate and
        the yield stress goes negative at εṗ=0 (see _LOG_RATE_ANCHOR above).
        Solver-validated: the anchored deck runs to NORMAL TERMINATION on the
        log10 prediction to 0.0000% where the bare one collapses its dt.
    """
    rows = sorted(rows)
    last_rate, last_lcid = rows[-1]
    rows.append((last_rate * 10.0 + 1.0, last_lcid))
    if rows[0][0] > _LOG_RATE_ANCHOR:
        rows.insert(0, (_LOG_RATE_ANCHOR, rows[0][1]))
    tid = state.next_curve_id()
    state.auto_tables[tid] = AutoTable(
        tid=tid, title=title, ndim=2,
        rows=[(lcid, (a,), 1.0) for a, lcid in rows])
    return tid


def _resolve_define_tables_3d(state: ConversionState) -> None:
    """Validate *DEFINE_TABLE_3D entries and build their flat Ndim=3 /TABLE/1
    emission — build_starter prepass, AFTER _resolve_define_tables (the inner
    2-D tables' rows must be final) and BEFORE _resolve_mat_tabulated_jc
    (whose LCK1 slices the same nesting).

    The flat form is the starter-verified /TABLE/1 recipe: one row per
    (inner VALUE, outer VALUE) pair — fct_ID = the leaf curve, A = the INNER
    table's VALUE (dim 2), B = the OUTER card's VALUE (dim 3), Scale_y = 1.0,
    rows ascending by (B, A); dim 1 is the leaf curves' own abscissa, so the
    nesting order TABLE_3D(V) → TABLE(A) → CURVE(x) is preserved. Two
    conscious fixes over dyna2rad's generic 3-D path (convertcurves.cxx:
    109-149): the inner tables' own SFA/OFFA reach their VALUEs (k2rad scales
    them at parse; d2r never reads them), and the inner VALUE sits on dim 2
    with the outer on dim 3 (d2r transposes — moot there only because its
    lone 3-D consumer ARRETs the engine).

    hm_read_table2_1.F:238-303 requires a COMPLETE rectangular secondary grid
    (every A under every B, else starter ERROR 3089 — negative-control-
    verified), so a 3-D table whose planes carry different inner grids is
    warned and NOT emitted flat; consumers that slice individual planes
    (*MAT_224 LCK1) still work off the parsed nesting.
    """
    for tbid, tab in sorted(state.define_tables_3d.items()):
        rows = []
        bad = []
        for v, tid in tab.rows:
            inner = state.define_tables.get(tid)
            if inner is None or not inner.resolved or not inner.rows:
                bad.append(tid)
                continue
            rows.append((v, inner))
        if bad:
            state.warn(
                f"*DEFINE_TABLE_3D tbid={tbid}: dropped row(s) referencing "
                f"missing/unresolved *DEFINE_TABLE(s) {sorted(set(bad))} — a "
                "dangling fct_ID would be starter ERROR 781.")
        if not rows:
            state.warn(
                f"*DEFINE_TABLE_3D tbid={tbid}: no usable rows — not emitted.")
            continue
        grids = {tuple(a for a, _ in inner.rows) for _, inner in rows}
        if len(grids) > 1:
            state.warn(
                f"*DEFINE_TABLE_3D tbid={tbid}: its inner *DEFINE_TABLEs do "
                "not share one secondary-abscissa grid — /TABLE/1 requires a "
                "COMPLETE rectangular grid (a function for every (A,B) "
                "combination, starter ERROR 3089), so the flat Ndim=3 table "
                "is NOT emitted. Consumers that slice individual planes "
                "(*MAT_224 LCK1) still convert; re-tabulate the inner tables "
                "on one shared value list to emit the 3-D table itself.")
            continue
        vals = [v for v, _ in rows]
        if len(set(vals)) != len(vals):
            dup = sorted({v for v in vals if vals.count(v) > 1})
            state.warn(
                f"*DEFINE_TABLE_3D tbid={tbid}: outer VALUE(s) {dup} appear "
                "on more than one row — the flat /TABLE/1 would carry the "
                "same (A,B) coordinate under two function ids, which the "
                "starter rejects as contradictory data (ERROR 3088, "
                "hm_read_table2_1.F:228). The flat Ndim=3 table is NOT "
                "emitted; deduplicate the point cards to emit it.")
            continue
        flat: List[Tuple[int, Tuple[float, ...], float]] = []
        for v, inner in sorted(rows, key=lambda r: r[0]):
            for a, lcid in inner.rows:
                flat.append((lcid, (a, v), 1.0))
        if len(flat) < 2:
            state.warn(
                f"*DEFINE_TABLE_3D tbid={tbid}: only one (VALUE, curve) row "
                "survives — a /TABLE/1 with a single row is starter ERROR "
                "778 (NFUN==1, hm_read_table2_1.F:126). The flat Ndim=3 "
                "table is NOT emitted.")
            continue
        state.auto_tables[tbid] = AutoTable(
            tid=tbid, title=tab.title or f"TABLE3D_{tbid}", ndim=3, rows=flat)
        tab.resolved = True


def _flip_triax_curve(state: ConversionState, lcid: int, mid: int) -> int:
    """Duplicate curve *lcid* with its abscissa NEGATED and re-sorted — the
    LS-DYNA→Radioss triaxiality flip (LS-DYNA *MAT_224 LCF tabulates the
    pressure-based p/σvm, compression-positive; /FAIL/TAB1 interpolates
    TRIAX = σm/σvm, tension-positive — fail_tab_s.F:163-172; dyna2rad applies
    the same ×(−1), CM:11616-11618). The *DEFINE_CURVE SFA/SFO/OFFA/OFFO are
    already baked into the parsed points, so the flip lands on the physical
    axis — avoiding dyna2rad's Ashiftx=OFFA slip (CM:11623: DYNA semantics
    need SFA·OFFA), which mis-shifts any flipped curve with OFFA≠0.

    Returns 0 (no curve synthesized) when the source curve parsed to zero
    points — a /FUNCT with a title and no X-Y pairs is a starter reject, so
    the caller must drop the row (or the whole /FAIL) instead."""
    if not state.curves[lcid].pts:
        return 0
    pts = sorted((-x, y) for x, y in state.curves[lcid].pts)
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, f"Auto_MAT224_LCF_flip{lcid}_mid{mid}",
                    list(pts))
    return fid


# Degenerate strain-rate axis for a Lode-dependent LCF with no LCG: dim 2 of
# a 3-D /FAIL/TAB1 failure table IS the plastic strain rate (fail_tab_s.F:
# 316-333), so the Lode angle must sit on dim 3 — two identical flat planes
# keep the lookup rate-independent. TWO planes because (a) the starter
# rejects only a single-ROW table (ERROR 778 fires on NFUN==1, the total row
# count — hm_read_table2_1.F:126 — not on a per-dimension count), but (b) the
# engine's bracketed interpolation reads VALUES(N) and VALUES(N+1) in every
# dimension, so each dimension still needs >= 2 distinct values to be safe.
_MAT224_FLAT_RATE_AXIS = ((0.0, 1.0), (1.0e30, 1.0))


def _resolve_mat_tabulated_jc(state: ConversionState) -> None:
    """*MAT_TABULATED_JOHNSON_COOK (224) wiring — build_starter prepass,
    AFTER _resolve_define_tables + _resolve_define_tables_3d (table rows must
    be final) and BEFORE _make_functions (synthesized curves/AutoTables and
    the table_1d_ids re-routing must exist when functions are emitted).

    ── Flow stress (LCK1/LCKT → tab_ID_h/tab_ID_t) ──────────────────────────
    LAW109's yield lookup is STRICTLY 2-D — σy = k1(εp, rate) scaled by
    kt(εp,T)/kt(εp,T_ref) — and its interpolator hard-stops on NDIM>2
    (table2d_vinterp_log.F:93-97, ANCMSG 36 + ARRET(2) at the FIRST engine
    cycle), so:
      * LCK1 curve       → 1-D /TABLE/1 under its own id (state.table_1d_ids;
        dyna2rad leaves tab_ID_h=0 here, CM:11196 — deck broken; fixed).
      * LCK1 2-D table   → referenced by id under I_smooth=1. EVERY
        I_smooth=2 table — the _LOG_INTERPOLATION spelling, or a NEGATIVE
        first rate VALUE (LS-DYNA's natural-log axis, Vol II p.357, every
        rate exp()-unwrapped) — is rebuilt as an AutoTable carrying BOTH
        flat-clamp rows: dyna2rad's sentinel (last curve duplicated at
        10·max+1, CM:11219-11250) and the first curve anchored at rate
        1e-10 (see _LOG_RATE_ANCHOR: without it the log10 lookup
        extrapolates to a NEGATIVE yield at εṗ=0 and diverges silently).
      * LCK1 3-D table   → SPLIT, never referenced whole (dyna2rad passes the
        3-D id through and the engine ARRETs — not replicated): tab_ID_h =
        the 2-D plane nearest T_ref, tab_ID_t = a synthesized (εp,T) table
        from every plane's LOWEST-rate curve. Exact iff the deck's
        σ(εp,rate,T) is multiplicatively separable — warned; when the
        selected plane is not AT T_ref, Yscale_h = kt(T_ref)/kt(T_plane)
        cancels the constant separable-factor offset. LCKT is ignored
        alongside (LS-DYNA ignores LCKT when LCK1 is 3-D).
      * LCKT 2-D table   → tab_ID_t by id (Radioss forms the kt ratio
        internally, sigeps109.F:230-244 — pass absolute yield curves).
        A plain-curve LCKT carries no temperature family (the ratio would be
        ≡1) → warned drop; dyna2rad drops it silently (CM:11169-11181).

    ── Taylor-Quinney (BETA → ETA/TAB_ETA) ──────────────────────────────────
    BETA ≥ 0 is the scalar ETA (engine clamps FTHERM=MIN(ETA·f,1)). BETA < 0:
    a curve becomes a 1-D TAB_ETA on the rate axis. A negative first
    abscissa makes the WHOLE axis natural-log rates (Vol II R17, LCG entry:
    "the natural logarithm of the strain rate value is used for ALL abscissa
    values" — the same convention every LCK1/LCG axis follows), so EVERY
    point is exp()-unwrapped; dyna2rad (CM:11318-11327) instead exp()s only
    the negative points — scrambling any mixed-sign axis — and forces the
    YIELD table's I_smooth to 2 off a BETA curve; neither defect is
    replicated. A 2-D table maps directly: TAB_ETA reads (rate, T, εp)
    (sigeps109.F:162-184) and LS-DYNA's 2-D BETA nesting is T → curves-over-
    rate — the manual's own level tags for the 3-D/4-D forms ("temperature
    (TABLE_3D), strain rate (TABLE), plastic strain (CURVE)", Vol II R17
    p.1593) put T above rate above εp in every BETA form, and dyna2rad's
    pass-through of the 2-D id (CM:11342) embodies the same reading — so
    rate lands on dim 1 and T on dim 2, the TAB_ETA order, with no
    transpose. A TABLE_3D would need a full axis TRANSPOSE with curve
    resampling ((T, rate, εp) nesting vs (rate, T, εp) lookup) → warned
    drop of the table, with a representative scalar ETA sampled at (lowest
    rate, plane nearest T_ref, εp→0) instead of the old flat 1.0 (a deck
    tabulating β≈0.35 would otherwise heat ~3× too fast). BFLG≠0
    reinterprets the BETA tables entirely → warned drop.

    ── Failure (LCF/LCG/LCH/LCI/NUMINT → /FAIL/TAB1) ────────────────────────
    Emitted ONLY when a usable LCF exists (dyna2rad writes /FAIL/TAB2 for
    every MAT_224 and hits starter ERROR 3000 on an LCF-less deck — not
    replicated). table1_ID = the triaxiality-FLIPPED failure-strain family;
    a Lode-dependent LCF (2-D table) adds dim 3 with θ = (2/π)·asin(ξ) — the
    engine interpolates on the normalized Lode ANGLE θ = 1 − 2·acos(ξ)/π
    (fail_tab_s.F:180) while LCF tabulates the Lode PARAMETER ξ = 27J₃/2σvm³,
    and the two coincide only at −1/0/+1 (shells evaluate dim 3 at θ=0).
    LCG (rate scale) has NO function slot on TAB1 — the rate must be table
    dim 2, so the grid is the PRE-MULTIPLIED tensor product εpf(triax)·g(rate)
    via per-row Scale_y (a natural-log LCG axis is exp()-unwrapped — dyna2rad
    forgets this one, CM: raw copy to FCT_SR). LCH is ALWAYS dropped loudly:
    TAB1's fct_IDT is evaluated at TSTAR and no LAW109 engine path ever
    fills TSTAR (only the Johnson-Cook-family laws do), so a mapped LCH(T)
    would be read at abscissa 0 every cycle — for an absolute-temperature
    curve that multiplies every failure strain by ~LCH(0)≈0 and erodes the
    mesh at cycle 1. LCI → fct_IDel with EI_ref blank (default 1.0 length
    unit ⇒ abscissa l_c/EI_ref = absolute element size, same as LCI);
    NUMINT>0 → Ifail_sh=1 (count 1) or P_thickfail=count/NIP (Ifail_sh=2);
    NUMINT<0 → P_thickfail=|NUMINT|/100 (percent→fraction — dyna2rad's
    FAILIP=NUMINT/100 integer-truncation loses every 0<NUMINT<100, not
    replicated); NUMINT=−200 (no erosion) → NO /FAIL at all, warned.
    """
    for mat in state.mat_tabulated_jc.values():
        kw = "*MAT_TABULATED_JOHNSON_COOK"
        tr_eff = mat.tr if mat.tr != 0.0 else 293.0
        # ── E (negative = temperature-dependent curve) ─────────────────────
        mat.e_eff = mat.e
        if mat.e < 0.0:
            cid = int(round(-mat.e))
            crv = state.curves.get(cid)
            if crv is not None and crv.pts:
                mat.e_eff = _interp_curve(crv.pts, tr_eff)
                state.warn(
                    f"{kw} mid={mat.mid}: E={mat.e:g} references curve {cid} "
                    "(temperature-dependent Young's modulus). /MAT/LAW109 "
                    "has a SCALAR E only, so the curve is sampled at T_ref: "
                    f"E({tr_eff:g}) = {mat.e_eff:g}; the modulus loses its "
                    "temperature dependence (the yield tables keep theirs). "
                    "dyna2rad instead takes the curve's FIRST ordinate "
                    "regardless of TR (CM:11141-11161).")
            else:
                mat.e_eff = 0.0
                state.warn(
                    f"{kw} mid={mat.mid}: E={mat.e:g} references curve {cid} "
                    "which is not in the deck — E stays 0 and the starter "
                    "will reject the material (LAW109 requires E > 0).")
        # ── I_smooth base (the _LOG_INTERPOLATION spelling) ────────────────
        mat.ismooth = 2 if mat.log_interpolation else 1
        # ── LCK1 → tab_ID_h [+ tab_ID_t from a 3-D split] ──────────────────
        lck1_is_3d = mat.lck1 in state.define_tables_3d
        if mat.lck1 == 0:
            state.warn(
                f"{kw} mid={mat.mid}: LCK1=0 — LAW109 has NO analytic "
                "hardening fallback, tab_ID_h stays 0 and the engine cannot "
                "run this material (sigeps109.F reads the yield table "
                "unconditionally). Supply LCK1.")
        elif mat.lck1 in state.curves:
            state.table_1d_ids.add(mat.lck1)
            mat.tab_h = mat.lck1
        elif mat.lck1 in state.define_tables:
            tab = state.define_tables[mat.lck1]
            if not tab.resolved or not tab.rows:
                state.warn(
                    f"{kw} mid={mat.mid}: LCK1={mat.lck1} references a "
                    "*DEFINE_TABLE that could not be resolved — tab_ID_h "
                    "dangles (starter ERROR 781).")
            elif tab.rows[0][0] < 0.0:
                rows = [(math.exp(a), lcid) for a, lcid in tab.rows]
                top = max(a for a, _ in rows) * 10.0 + 1.0
                tid = _rate_table_autotable(
                    state, rows,
                    f"Duplicate_table_ID_{mat.lck1}_MatL224_ID_{mat.mid}")
                mat.tab_h = tid
                mat.ismooth = 2
                state.warn(
                    f"{kw} mid={mat.mid}: LCK1={mat.lck1} has a NEGATIVE "
                    "first strain-rate value — LS-DYNA's natural-log rate "
                    "axis. Rebuilt as /TABLE/1 "
                    f"{tid} with every rate exp()-unwrapped, the last curve "
                    f"duplicated at {top:g} (dyna2rad's "
                    "flat-extrapolation sentinel, CM:11219-11250), the FIRST "
                    "curve duplicated at rate 1e-10 (the engine clamps the "
                    "log-lookup SAMPLE there but EXTRAPOLATES the table — "
                    "unanchored, the yield goes NEGATIVE at zero plastic "
                    "strain rate, i.e. through every elastic phase, and the "
                    "run diverges silently) and I_smooth=2 (log-basis rate "
                    "interpolation, matching LS-DYNA's linear-in-ln(rate) "
                    "lookup).")
            elif mat.ismooth == 2:
                # The _LOG_INTERPOLATION spelling with an already-linear
                # (positive) rate axis: referencing the user table by id
                # would leave I_smooth=2's log10 lookup free to extrapolate
                # below the lowest tabulated rate — negative yield at
                # eps_dot=0 — so the table is rebuilt with the same two
                # flat-clamp rows as the ln-unwrap path above.
                tid = _rate_table_autotable(
                    state, list(tab.rows),
                    f"Duplicate_table_ID_{mat.lck1}_MatL224_ID_{mat.mid}")
                mat.tab_h = tid
                state.warn(
                    f"{kw} mid={mat.mid}: _LOG_INTERPOLATION with "
                    f"LCK1={mat.lck1} — rebuilt as /TABLE/1 {tid} with the "
                    "first curve duplicated at rate 1e-10 and the last at "
                    "10·max+1: I_smooth=2 EXTRAPOLATES in log10 outside the "
                    "tabulated rates (table2d_vinterp_log.F:206 clamps only "
                    "the SAMPLE, to 1e-10), so an unanchored table returns "
                    "a NEGATIVE yield stress at the zero rate of every "
                    "elastic phase and the run diverges silently; LS-DYNA "
                    "clamps flat outside the tabulated range.")
            else:
                mat.tab_h = mat.lck1
        elif lck1_is_3d:
            t3 = state.define_tables_3d[mat.lck1]
            planes = sorted(
                (v, tid) for v, tid in t3.rows
                if (tid in state.define_tables
                    and state.define_tables[tid].resolved
                    and state.define_tables[tid].rows))
            if not planes:
                state.warn(
                    f"{kw} mid={mat.mid}: LCK1={mat.lck1} is a "
                    "*DEFINE_TABLE_3D with no usable temperature plane — "
                    "tab_ID_h stays 0 and the engine cannot run this "
                    "material (LAW109 has no analytic hardening fallback).")
            else:
                if len({v for v, _ in planes}) != len(planes):
                    seen: set = set()
                    uniq = []
                    for v, tid in planes:
                        if v in seen:
                            continue
                        seen.add(v)
                        uniq.append((v, tid))
                    state.warn(
                        f"{kw} mid={mat.mid}: LCK1={mat.lck1} lists more "
                        "than one plane at the same temperature — "
                        "contradictory input (the synthesized tab_ID_t "
                        "would repeat an outer value, starter ERROR 3088). "
                        "Keeping the FIRST plane per temperature; "
                        "deduplicate the *DEFINE_TABLE_3D point cards.")
                    planes = uniq
                v_sel, tid_sel = min(planes,
                                     key=lambda p: abs(p[0] - tr_eff))
                plane = state.define_tables[tid_sel]
                if plane.rows[0][0] < 0.0:
                    rows = [(math.exp(a), lcid) for a, lcid in plane.rows]
                    tid = _rate_table_autotable(
                        state, rows,
                        f"Duplicate_table_ID_{tid_sel}_MatL224_ID_{mat.mid}")
                    mat.tab_h = tid
                    mat.ismooth = 2
                elif mat.ismooth == 2:
                    # _LOG_INTERPOLATION spelling: same negative-yield trap
                    # as the 2-D branch — rebuild the plane with the two
                    # flat-clamp rows instead of referencing it by id.
                    tid = _rate_table_autotable(
                        state, list(plane.rows),
                        f"Duplicate_table_ID_{tid_sel}_MatL224_ID_{mat.mid}")
                    mat.tab_h = tid
                else:
                    mat.tab_h = tid_sel
                trows: List[Tuple[int, Tuple[float, ...], float]] = [
                    (state.define_tables[tid].rows[0][1], (v,), 1.0)
                    for v, tid in planes]
                if len(trows) >= 2:
                    ttid = state.next_curve_id()
                    state.auto_tables[ttid] = AutoTable(
                        tid=ttid,
                        title=f"Auto_MAT224_LCKT_from3D_mid{mat.mid}",
                        ndim=2, rows=trows)
                    mat.tab_t = ttid
                # Constant separable-factor correction: the engine rebuilds
                # σ = Yscale·k1(εp,rate)·kt(εp,T)/kt(εp,T_ref) with k1 taken
                # from the plane at T=v_sel, so even a perfectly separable
                # deck σ = k(εp,rate)·f(T) comes out scaled by f(v_sel)/
                # f(T_ref) whenever the nearest plane is not AT T_ref.
                # Yscale_h = kt(T_ref)/kt(v_sel) — sampled from the same
                # lowest-rate family tab_ID_t carries, at the selected
                # plane's first strain point — cancels that factor exactly
                # under separability (and is the identity when v_sel==T_ref
                # or T_ref lies outside the tabulated planes, since
                # _interp_curve clamps at the ends).
                yscale_note = ""
                if mat.tab_t and v_sel != tr_eff:
                    pts_sel = state.curves[plane.rows[0][1]].pts
                    eps0 = min((x for x, _ in pts_sel), default=None)
                    kt_pts = []
                    if eps0 is not None:
                        for v, ptid in planes:
                            cpts = state.curves[
                                state.define_tables[ptid].rows[0][1]].pts
                            kt_pts.append((v, _interp_curve(cpts, eps0)))
                    if kt_pts and all(val > 0.0 for _, val in kt_pts):
                        kt_ref = _interp_curve(kt_pts, tr_eff)
                        kt_sel = _interp_curve(kt_pts, v_sel)
                        c = kt_ref / kt_sel
                        if abs(c - 1.0) > 1.0e-12:
                            mat.yscale_h = c
                            yscale_note = (
                                f" Yscale_h={c:.10g} (= kt(T_ref)/kt(T="
                                f"{v_sel:g}) at εp={eps0:g}) corrects the "
                                "constant factor the reconstruction would "
                                "otherwise carry because the selected plane "
                                "sits at T≠T_ref.")
                state.warn(
                    f"{kw} mid={mat.mid}: LCK1={mat.lck1} is a 3-D table "
                    "σ(εp, rate, T), but LAW109's yield lookup is strictly "
                    "2-D (table2d_vinterp_log.F ARRETs the engine on NDIM>2 "
                    "— dyna2rad wires the 3-D id through and produces "
                    "exactly that crash). SPLIT instead: tab_ID_h = plane "
                    f"{tid_sel} at T={v_sel:g} (nearest T_ref={tr_eff:g}), "
                    "tab_ID_t = the (εp, T) table of every plane's "
                    "lowest-rate curve"
                    + (f" (/TABLE/1 {mat.tab_t})" if mat.tab_t else
                       " — single plane, no temperature variation to carry")
                    + ". LAW109 then reconstructs σ = k1(εp,rate) · "
                    "kt(εp,T)/kt(εp,T_ref); EXACT only if the tabulated "
                    "σ(εp,rate,T) is multiplicatively separable in rate and "
                    "temperature — verify against the source data."
                    + yscale_note)
                if mat.lckt:
                    state.warn(
                        f"{kw} mid={mat.mid}: LCKT={mat.lckt} is IGNORED "
                        "because LCK1 is a 3-D table (LS-DYNA's own rule, "
                        "Vol II p.1592) — tab_ID_t comes from the LCK1 "
                        "split above.")
        else:
            state.warn(
                f"{kw} mid={mat.mid}: LCK1={mat.lck1} references a curve/"
                "table that is not in the deck — tab_ID_h dangles (starter "
                "ERROR 781).")
        # ── LCKT → tab_ID_t (when not consumed by the 3-D split) ───────────
        if mat.lckt and not lck1_is_3d:
            if mat.lckt in state.define_tables:
                tab = state.define_tables[mat.lckt]
                if tab.resolved and tab.rows:
                    mat.tab_t = mat.lckt
                else:
                    state.warn(
                        f"{kw} mid={mat.mid}: LCKT={mat.lckt} references a "
                        "*DEFINE_TABLE that could not be resolved — "
                        "tab_ID_t dangles (starter ERROR 781).")
            elif mat.lckt in state.curves:
                state.warn(
                    f"{kw} mid={mat.mid}: LCKT={mat.lckt} is a plain "
                    "*DEFINE_CURVE — it carries no temperature family, and "
                    "tab_ID_t works as the RATIO kt(εp,T)/kt(εp,T_ref) "
                    "(sigeps109.F:230-244), which a 1-D σ(εp) table makes "
                    "identically 1. DROPPED (temperature scaling of the "
                    "yield ≡ 1); dyna2rad drops it too, silently "
                    "(CM:11169-11181 has no curve branch). Restate LCKT as "
                    "a *DEFINE_TABLE over temperature.")
            elif mat.lckt in state.define_tables_3d:
                state.warn(
                    f"{kw} mid={mat.mid}: LCKT={mat.lckt} is a "
                    "*DEFINE_TABLE_3D — LCKT is a 2-D table (per T, a "
                    "quasi-static σ(εp) curve) in LS-DYNA and tab_ID_t is "
                    "read 2-D; DROPPED (temperature scaling ≡ 1).")
            else:
                state.warn(
                    f"{kw} mid={mat.mid}: LCKT={mat.lckt} references a "
                    "curve/table that is not in the deck — tab_ID_t dangles "
                    "(starter ERROR 781).")
        # ── BETA → ETA / TAB_ETA ───────────────────────────────────────────
        if mat.beta >= 0.0:
            mat.eta = mat.beta
            if mat.beta > 1.0:
                state.warn(
                    f"{kw} mid={mat.mid}: BETA={mat.beta:g} > 1 — the "
                    "engine clamps the heat fraction to 1 "
                    "(FTHERM=MIN(ETA,1), sigeps109.F:189).")
        elif mat.bflg:
            state.warn(
                f"{kw} mid={mat.mid}: BFLG={mat.bflg} reinterprets the "
                f"BETA={mat.beta:g} tables as β(max shear strain / rate / "
                "element size) — /MAT/LAW109's TAB_ETA reads (rate, T, εp) "
                "and cannot express that; the BETA table is DROPPED and the "
                "heat fraction stays ETA=1.0.")
        else:
            bid = int(round(-mat.beta))
            if bid in state.curves:
                crv = state.curves[bid]
                if not crv.pts:
                    state.warn(
                        f"{kw} mid={mat.mid}: BETA curve {bid} has no "
                        "points — DROPPED (ETA stays 1.0); an empty "
                        "/TABLE/1 would be a starter reject.")
                elif min(x for x, _ in crv.pts) < 0.0:
                    pts = sorted((math.exp(x), y) for x, y in crv.pts)
                    fid = state.next_curve_id()
                    _add_auto_curve(
                        state, fid, f"Auto_MAT224_TAB_ETA_mid{mat.mid}",
                        list(pts))
                    state.table_1d_ids.add(fid)
                    mat.tab_eta = fid
                    state.warn(
                        f"{kw} mid={mat.mid}: BETA curve {bid} has a "
                        "negative strain-rate abscissa — LS-DYNA's "
                        "natural-log convention makes the WHOLE axis "
                        "ln(rate) ('the natural logarithm of the strain "
                        "rate value is used for all abscissa values', Vol "
                        "II R17), so EVERY point is exp()-unwrapped into "
                        f"/TABLE/1 {fid}. dyna2rad (CM:11318-11327) exp()s "
                        "only the negative points — a mixed-sign axis comes "
                        "out physically scrambled (an abscissa of 0 is rate "
                        "1, not 0) — and forces the YIELD table's I_smooth "
                        "to 2 off a BETA curve; neither is replicated. "
                        "Radioss interpolates TAB_ETA linearly in rate "
                        "(TABLE_VINTERP) where LS-DYNA interpolated "
                        "linearly in ln(rate).")
                else:
                    state.table_1d_ids.add(bid)
                    mat.tab_eta = bid
            elif bid in state.define_tables:
                tab = state.define_tables[bid]
                if tab.resolved and tab.rows:
                    mat.tab_eta = bid
                else:
                    state.warn(
                        f"{kw} mid={mat.mid}: BETA table {bid} could not be "
                        "resolved — TAB_ETA dangles (starter ERROR 781).")
            elif bid in state.define_tables_3d:
                # The table itself is inexpressible without a full pivot,
                # but a representative SCALAR at the reference state —
                # lowest rate, plane nearest T_ref, εp → 0 — is strictly
                # better than the old flat 1.0 (a deck tabulating β≈0.35
                # would heat ~3× too fast under ETA=1).
                sample = None
                s_v = s_rate = None
                t3 = state.define_tables_3d[bid]
                bplanes = [(v, tid) for v, tid in t3.rows
                           if (tid in state.define_tables
                               and state.define_tables[tid].resolved
                               and state.define_tables[tid].rows)]
                if bplanes:
                    s_v, btid = min(bplanes,
                                    key=lambda p: abs(p[0] - tr_eff))
                    s_rate, blcid = state.define_tables[btid].rows[0]
                    bcrv = state.curves.get(blcid)
                    if bcrv is not None and bcrv.pts:
                        sample = _interp_curve(bcrv.pts, 0.0)
                if sample is not None and sample > 0.0:
                    mat.eta = sample
                    state.warn(
                        f"{kw} mid={mat.mid}: BETA={mat.beta:g} references "
                        f"*DEFINE_TABLE_3D {bid} — LS-DYNA nests it (T → "
                        "rate → εp), i.e. flat dims (εp, rate, T), while "
                        "LAW109's TAB_ETA reads (rate, T, εp) "
                        "(sigeps109.F:162-184): a full axis TRANSPOSE with "
                        "curve resampling would be required, so the TABLE "
                        "is dropped. A representative scalar "
                        f"ETA={sample:g} is baked instead, sampled at the "
                        f"reference state (lowest rate {s_rate:g}, plane "
                        f"T={s_v:g} nearest T_ref={tr_eff:g}, εp→0); the "
                        "rate/temperature/strain variation of the heat "
                        "fraction is lost.")
                else:
                    state.warn(
                        f"{kw} mid={mat.mid}: BETA={mat.beta:g} references "
                        f"*DEFINE_TABLE_3D {bid} — LS-DYNA nests it (T → "
                        "rate → εp), i.e. flat dims (εp, rate, T), while "
                        "LAW109's TAB_ETA reads (rate, T, εp) "
                        "(sigeps109.F:162-184): a full axis TRANSPOSE with "
                        "curve resampling would be required. DROPPED — no "
                        "usable curve to sample a representative scalar "
                        "from, the heat fraction stays ETA=1.0.")
            else:
                state.warn(
                    f"{kw} mid={mat.mid}: BETA={mat.beta:g} references "
                    f"curve/table {bid} which is not in the deck (a "
                    "*DEFINE_TABLE_4D is not supported either) — DROPPED, "
                    "ETA stays 1.0.")
        # ── Failure: LCF/LCG/LCH/LCI + NUMINT → /FAIL/TAB1 ─────────────────
        _resolve_mat224_failure(state, mat, kw)
        # ── Optional card 3 + BFLG drops ───────────────────────────────────
        if mat.failopt:
            state.warn(
                f"{kw} mid={mat.mid}: FAILOPT={mat.failopt} (load-path-"
                f"independent F2=εp/εpf criterion, NUMAVG={mat.numavg}, "
                f"NCYFAIL={mat.ncyfail}) has no /FAIL/TAB1 counterpart — "
                "DROPPED; the converted criterion is the accumulated "
                "F = ∫dεp/εpf ≥ 1 only.")
        if mat.erode:
            state.warn(
                f"{kw} mid={mat.mid}: ERODE={mat.erode} (keep failed solids "
                "with zeroed/uncoupled stresses instead of eroding) has no "
                "/FAIL/TAB1 counterpart — DROPPED (failed elements are "
                "deleted).")
        if mat.lcps:
            state.warn(
                f"{kw} mid={mat.mid}: LCPS={mat.lcps} (1st-principal-stress "
                "limit, post-processing history variable #17 only in "
                "LS-DYNA) has no Radioss counterpart — DROPPED.")
        if mat.bflg and mat.beta >= 0.0:
            state.warn(
                f"{kw} mid={mat.mid}: BFLG={mat.bflg} without a BETA table "
                "has no effect in LS-DYNA and no LAW109 counterpart — "
                "ignored.")


def _resolve_mat224_failure(state: ConversionState, mat: MatTabulatedJC,
                            kw: str) -> None:
    """The /FAIL/TAB1 half of _resolve_mat_tabulated_jc (see its docstring
    for the full semantics). Sets emit_fail/fail_table1/fct_idel/ifail_sh/
    ifail_so/pthickfail on *mat*."""
    if mat.numint == -200.0:
        state.warn(
            f"{kw} mid={mat.mid}: NUMINT=-200 disables erosion in LS-DYNA "
            "(damage is tracked but elements are never deleted). /FAIL/TAB1 "
            "always deletes at D ≥ Dcrit and Radioss has no track-but-never-"
            "delete mode, so NO /FAIL card is emitted — the LCF/LCG/LCH/LCI "
            "damage bookkeeping is DROPPED rather than converted into "
            "erosion LS-DYNA would not perform.")
        return
    if mat.lcf == 0:
        extras = [f"{n}={v}" for n, v in
                  (("LCG", mat.lcg), ("LCH", mat.lch), ("LCI", mat.lci)) if v]
        if extras:
            state.warn(
                f"{kw} mid={mat.mid}: LCF=0 but {', '.join(extras)} set — "
                "LCG/LCH/LCI are multiplicative scales ON the LCF failure "
                "strain and are DROPPED without it. No /FAIL/TAB1 is "
                "emitted (dyna2rad emits one for every MAT_224 and hits "
                "starter ERROR 3000 when no failure table exists — not "
                "replicated).")
        return
    # ── LCF → the (flipped) failure-strain family ──────────────────────────
    # (theta | None, flipped fct id): the curve arm below stores None in slot 0
    # and the *DEFINE_TABLE arm a real Lode angle, and the dispatch further down
    # keys on exactly that difference — so the slot is genuinely heterogeneous.
    base: Optional[List[Tuple[Any, int]]] = None
    if mat.lcf in state.curves:
        if not state.curves[mat.lcf].pts:
            state.warn(
                f"{kw} mid={mat.mid}: LCF curve {mat.lcf} has no points — "
                "no /FAIL/TAB1 emitted.")
            return
        base = [(None, _flip_triax_curve(state, mat.lcf, mat.mid))]
    elif mat.lcf in state.define_tables:
        tab = state.define_tables[mat.lcf]
        if not tab.resolved or not tab.rows:
            state.warn(
                f"{kw} mid={mat.mid}: LCF={mat.lcf} references a "
                "*DEFINE_TABLE that could not be resolved — no /FAIL/TAB1 "
                "emitted (an empty table1_ID would be starter ERROR 2068).")
            return
        base = []
        clamped = []
        empty = []
        for xi, lcid in tab.rows:
            fid = _flip_triax_curve(state, lcid, mat.mid)
            if fid == 0:
                empty.append(lcid)
                continue
            xi_c = min(1.0, max(-1.0, xi))
            if xi_c != xi:
                clamped.append(xi)
            base.append(((2.0 / math.pi) * math.asin(xi_c), fid))
        if empty:
            state.warn(
                f"{kw} mid={mat.mid}: LCF table {mat.lcf} row(s) reference "
                f"curve(s) {sorted(set(empty))} that parsed to zero points "
                "— row(s) dropped (an empty /FUNCT is a starter reject).")
        if not base:
            state.warn(
                f"{kw} mid={mat.mid}: no usable LCF row survives — no "
                "/FAIL/TAB1 emitted.")
            return
        base.sort(key=lambda t: t[0])
        state.warn(
            f"{kw} mid={mat.mid}: LCF={mat.lcf} is Lode-dependent — its "
            "table values are the Lode PARAMETER ξ = 27J₃/(2σvm³), while "
            "/FAIL/TAB1 interpolates dim 3 on the normalized Lode ANGLE "
            "θ = 1 − 2·acos(ξ)/π (fail_tab_s.F:180); each value is remapped "
            "θ = (2/π)·asin(ξ), which IS the engine's formula (acos = π/2 − "
            "asin) — the remap is needed because ξ and θ themselves "
            "coincide only at −1/0/+1. SHELL "
            "elements evaluate the Lode axis at θ=0 (fail_tab_c.F:215-225 — "
            "'only 2D tables' per the Radioss manual); solids use the full "
            "3-D lookup."
            + (f" Value(s) {clamped} outside [-1,1] were clamped."
               if clamped else ""))
    elif mat.lcf in state.define_tables_3d:
        state.warn(
            f"{kw} mid={mat.mid}: LCF={mat.lcf} is a *DEFINE_TABLE_3D — "
            "LS-DYNA defines LCF as a curve (εpf vs triaxiality) or a 2-D "
            "table (per Lode parameter) only, and /FAIL/TAB1's temperature-"
            "free (triax, rate, Lode) table cannot absorb a third LCF axis. "
            "No /FAIL/TAB1 is emitted (dyna2rad's 'TABLE' branch reads the "
            "3-D card's absent CurveIds and emits an EMPTY table — starter "
            "error — not replicated).")
        return
    else:
        state.warn(
            f"{kw} mid={mat.mid}: LCF={mat.lcf} references a curve/table "
            "that is not in the deck — no /FAIL/TAB1 emitted (a dangling "
            "table1_ID would be starter ERROR 781/2068).")
        return
    # ── LCG → the rate axis (pre-multiplied Scale_y grid) ──────────────────
    rates = None         # list of (rate, scale)
    if mat.lcg:
        if mat.lcg in state.curves:
            pts = sorted(state.curves[mat.lcg].pts)
            if len(pts) >= 2:
                if pts[0][0] < 0.0:
                    rates = sorted((math.exp(x), y) for x, y in pts)
                    state.warn(
                        f"{kw} mid={mat.mid}: LCG curve {mat.lcg} has a "
                        "negative first abscissa — LS-DYNA reads the WHOLE "
                        "axis as natural-log strain rates (Vol II p.1593); "
                        "exp()-unwrapped onto the table1_ID rate axis "
                        "(dyna2rad copies the log axis raw into its rate "
                        "slot — not replicated). Radioss interpolates the "
                        "rate dimension linearly in rate.")
                else:
                    rates = pts
            else:
                state.warn(
                    f"{kw} mid={mat.mid}: LCG curve {mat.lcg} has fewer "
                    "than 2 points — unusable as a rate axis (/TABLE/1 "
                    "needs ≥ 2 rows per dimension, starter ERROR 778); "
                    "rate scaling DROPPED (g ≡ 1).")
        elif (mat.lcg in state.define_tables
              or mat.lcg in state.define_tables_3d):
            state.warn(
                f"{kw} mid={mat.mid}: LCG={mat.lcg} is a *DEFINE_TABLE — "
                "LS-DYNA defines LCG as a CURVE of εpf-scale vs plastic "
                "strain rate; a table here is not defined and cannot be "
                "mapped — rate scaling DROPPED (g ≡ 1).")
        else:
            state.warn(
                f"{kw} mid={mat.mid}: LCG={mat.lcg} references a curve that "
                "is not in the deck — rate scaling DROPPED (g ≡ 1).")
    # ── assemble table1_ID ─────────────────────────────────────────────────
    if base[0][0] is None:                      # triaxiality-only LCF
        flip_fid = base[0][1]
        if rates is None:
            mat.fail_table1 = flip_fid          # 1-D function in the table
        else:                                   # slot — MAT_081 precedent
            tid = state.next_curve_id()
            state.auto_tables[tid] = AutoTable(
                tid=tid, title=f"Auto_MAT224_LCFxLCG_mid{mat.mid}", ndim=2,
                rows=[(flip_fid, (r,), g) for r, g in rates])
            mat.fail_table1 = tid
    else:                                       # Lode-dependent LCF
        rate_axis = rates if rates is not None else list(_MAT224_FLAT_RATE_AXIS)
        rows: List[Tuple[int, Tuple[float, ...], float]] = [
            (fid, (r, theta), g)
            for theta, fid in base for r, g in rate_axis]
        rows.sort(key=lambda t: (t[1][1], t[1][0]))
        tid = state.next_curve_id()
        state.auto_tables[tid] = AutoTable(
            tid=tid, title=f"Auto_MAT224_LCF_lode_mid{mat.mid}", ndim=3,
            rows=rows)
        mat.fail_table1 = tid
    mat.emit_fail = True
    # ── LCH: inexpressible under LAW109 ────────────────────────────────────
    if mat.lch:
        state.warn(
            f"{kw} mid={mat.mid}: LCH={mat.lch} (failure-strain scale vs "
            "temperature) is DROPPED (h(T) ≡ 1): /FAIL/TAB1's fct_IDT is "
            "evaluated at TSTAR (fail_tab_s.F:200) and NO LAW109 engine "
            "path ever fills TSTAR (only the Johnson-Cook-family laws do), "
            "so a mapped LCH would be read at abscissa 0 every cycle — for "
            "an absolute-temperature curve that multiplies every failure "
            "strain by ~LCH(0)≈0 and erodes the whole mesh at cycle 1. "
            "The temperature dependence of the failure strain cannot be "
            "expressed under /MAT/LAW109 + /FAIL/TAB1.")
    # ── LCI → fct_IDel ─────────────────────────────────────────────────────
    if mat.lci:
        if mat.lci in state.curves:
            mat.fct_idel = mat.lci
        elif mat.lci in state.define_tables:
            tab = state.define_tables[mat.lci]
            if tab.resolved and len(tab.rows) == 1:
                mat.fct_idel = tab.rows[0][1]
                state.warn(
                    f"{kw} mid={mat.mid}: LCI={mat.lci} is a 1-row table — "
                    "collapsed to its only curve "
                    f"{mat.fct_idel} for fct_IDel (the single-value "
                    "triaxiality axis carries no variation).")
            else:
                state.warn(
                    f"{kw} mid={mat.mid}: LCI={mat.lci} is a per-"
                    "triaxiality table of element-size curves — "
                    "/FAIL/TAB1's regularization is a single FUNCTION of "
                    "element size (fct_IDel), with no triaxiality axis; "
                    "DROPPED (no element-size regularization). Re-state LCI "
                    "as one curve to convert it.")
        elif mat.lci in state.define_tables_3d:
            state.warn(
                f"{kw} mid={mat.mid}: LCI={mat.lci} is a *DEFINE_TABLE_3D "
                "(size × triaxiality × Lode) — /FAIL/TAB1's fct_IDel is a "
                "single function of element size; DROPPED (no element-size "
                "regularization).")
        else:
            state.warn(
                f"{kw} mid={mat.mid}: LCI={mat.lci} references a curve that "
                "is not in the deck — fct_IDel left 0 (no element-size "
                "regularization).")
    # ── NUMINT → Ifail_sh / Ifail_so / P_thickfail ─────────────────────────
    if mat.numint < 0.0:
        mat.ifail_sh = 2
        mat.pthickfail = min(abs(mat.numint) / 100.0, 1.0)
        state.warn(
            f"{kw} mid={mat.mid}: NUMINT={mat.numint:g} (negative = PERCENT "
            "of failed layers) → Ifail_sh=2 with P_thickfail="
            f"{mat.pthickfail:g} (fraction; dyna2rad's FAILIP=|NUMINT|/100 "
            "route is a TAB2 field — on TAB1 the fraction lands on "
            "P_thickfail, which the reader honours only for Ifail_sh>1).")
    else:
        count = int(round(mat.numint))
        if count <= 1:
            mat.ifail_sh = 1        # first failed layer deletes the shell
            mat.ifail_so = 1        # first failed IP deletes the solid
        else:
            nptt = _shell_nptt_for_mid(state, mat.mid)
            if nptt:
                mat.ifail_sh = 2
                mat.pthickfail = min(count / nptt, 1.0)
                state.warn(
                    f"{kw} mid={mat.mid}: NUMINT={count} (integration-point "
                    "COUNT) → Ifail_sh=2 with P_thickfail="
                    f"{mat.pthickfail:g} = {count}/{nptt} of the shell's "
                    "NIP stack (dyna2rad's FAILIP=NUMINT/100 integer-"
                    "truncates every 0<NUMINT<100 to 0 → starter default 1 "
                    "— not replicated).")
            else:
                mat.ifail_sh = 2
                state.warn(
                    f"{kw} mid={mat.mid}: NUMINT={count} > 1 but no shell "
                    "part with a *SECTION_SHELL NIP references this "
                    "material — the count cannot become a thickness "
                    "fraction. Ifail_sh=2 (whole stack must fail) is the "
                    "closest conservative mapping.")
        solid_pids = {e.pid for e in state.solid_elems}
        mat_solid_pids = [pid for pid, p in state.parts.items()
                          if p.mid == mat.mid and pid in solid_pids]
        if count > 1 and mat_solid_pids:
            # Exact special case: NUMINT equal to the element's own IP count
            # is LS-DYNA's "ALL integration points must fail" — a rule
            # /FAIL/TAB1 does have: Ifail_so=2 = "element deleted when
            # rupture in all integration points" (fail_tab_s.F:258). It is
            # exact when every solid part on this material is an 8-IP
            # LS-DYNA formulation (*SECTION_SOLID ELFORM 2/-1/-2, the fully
            # integrated hexas) converting to the 8-IP Isolid 17 — the
            # k2rad hex default, unless hourglass control remapped it.
            from .mesh import _effective_solid_isolid  # local: mesh imports us

            def _exact_all_ip(pid: int) -> bool:
                sec = state.sec_solids.get(state.parts[pid].secid)
                return (sec is not None and sec.elform in (2, -1, -2)
                        and _effective_solid_isolid(state, pid, sec) == 17)

            if count == 8 and all(_exact_all_ip(pid)
                                  for pid in mat_solid_pids):
                mat.ifail_so = 2
                state.warn(
                    f"{kw} mid={mat.mid}: NUMINT=8 on fully integrated "
                    "SOLID part(s) (ELFORM 2/-1/-2 → Isolid 17, 8 IPs on "
                    "both sides) → Ifail_so=2: deletion when ALL "
                    "integration points fail — exactly LS-DYNA's 8-of-8 "
                    "rule (fail_tab_s.F:258).")
            else:
                state.warn(
                    f"{kw} mid={mat.mid}: NUMINT={count} on SOLID part(s) "
                    "— /FAIL/TAB1's Ifail_so has no integration-point "
                    "count (1 = delete on first failed IP; 2 = all IPs "
                    "must fail, exact only when NUMINT equals the "
                    "element's IP count), so solids erode EARLIER than "
                    f"LS-DYNA's {count}-IP rule.")


def _emit_mat_law109(mat: MatTabulatedJC) -> List[str]:
    """*MAT_TABULATED_JOHNSON_COOK (224) → /MAT/LAW109 (elasto-plastic
    tabulated). Layout audited against hm_cfg_files MAT/mat109.cfg — its ONLY
    format block is FORMAT(radioss2021), so a /BEGIN 2022 deck reads exactly
    this (starter-verified, 0 errors, every field echoed):
      C1: RHO_I(20)
      C2: E(20) Nu(20)
      C3: C_p(20) ETA(20) T_ref(20) T_ini(20)
      C4: tab_ID_h(10) tab_ID_t(10) Xscale_h(20) Yscale_h(20) [30 blanks]
          I_smooth(10)
      C5: TAB_ETA(10) Xscale_ETA(20) — NOT optional: the CFG always reads it
          (omitting the line would consume the next card).
    Blank(0) fields keep the starter defaults (hm_read_mat109.F:118-136):
    Xscale_h/Yscale_h/Xscale_ETA → 1.0, T_ref 0 → 293, T_ini 0 → T_ref; the
    rate filter is hardwired FCUT = 10 kHz. C_p is the per-MASS specific
    heat, copied 1:1 from LS-DYNA CP — the engine divides by RHO itself
    (sigeps109.F:419: TEMP += FTHERM·YLD·DPLA/(CP·RHO)) — deliberately NOT
    the rho-premultiplied rhoC_p of the LAW2/LAW4 (MAT_015) convention.
    Adiabatic self-heating needs NO /HEAT/MAT — emitting one would SWITCH
    LAW109 to the imposed-temperature path and kill the self-heating update
    (sigeps109.F:411-414; Reference Guide p.693) — so none is written.

    Xscale_h MUST stay blank (= 1.0): the engine applies 1/Xscale_h to the
    rate sample in the PRE-yield lookup only (sigeps109.F:221 XVEC=EPSD*
    XSCALE) and feeds the raw EPSD to the in-loop plastic re-lookup
    (sigeps109.F:349) — the two lookups agree only at Xscale_h=1, so no
    LS-DYNA rate-scale may ever be mapped onto this field. Yscale_h carries
    the 3-D-split separable-factor correction when the selected temperature
    plane is not at T_ref (0.0 = default 1.0 otherwise)."""
    return [
        f"/MAT/LAW109/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu",
        f"{_f(mat.e_eff)}{_f(mat.pr)}",
        "#                C_p                 ETA               T_ref               T_ini",
        f"{_f(mat.cp)}{_f(mat.eta)}{_f(mat.tr)}{_f(0.0)}",
        "# tab_ID_h  tab_ID_t            Xscale_h            Yscale_h                                I_smooth",
        f"{_i(mat.tab_h)}{_i(mat.tab_t)}{_f(0.0)}{_f(mat.yscale_h)}{' ' * 30}{_i(mat.ismooth)}",
        "#  TAB_ETA          Xscale_ETA",
        f"{_i(mat.tab_eta)}{_f(0.0)}",
        HDR,
    ]


def _emit_mat224_tab1(mat: MatTabulatedJC) -> List[str]:
    """*MAT_224 LCF/LCG/LCI/NUMINT → /FAIL/TAB1. Layout from hm_cfg_files
    FAIL/fail_tab1.cfg FORMAT(radioss2021) — the block a /BEGIN 2022 deck
    reads with; the literal space runs on cards 1 and 5 are documented on
    _emit_mat123_tab1. The header id is the MATERIAL id and there is no
    title line; Shear_limit/Biax_limit are 2021+ fields, legal at 2022
    (blank keeps their defaults −1/1 = no triaxiality cutoffs).

    Card 2 all-blank keeps the starter's damage defaults Dcrit=1, D=0, n=1,
    Dadv=Dcrit (hm_read_fail_tab1.F:139-177): damage accumulates as
    dD = dεp/εpf and the element erodes the instant D ≥ 1, with NO softening
    (no TABLE2 and FAD_EXP=0 leave DMG_FLAG=0) — exactly MAT_224's
    F = ∫dεp/εpf ≥ 1 instant-deletion criterion, nothing double-counted.
    table1_ID carries the pre-flipped triaxiality axis (and the θ-remapped
    Lode axis / pre-multiplied LCG rate axis — see _resolve_mat_tabulated_jc);
    a plain-curve family is referenced as a 1-D /FUNCT, which the TAB1
    reader accepts in a table slot (MAT_081 precedent, live-verified).
    fct_IDel takes LCI with Fscale_el/EI_ref blank → 1.0, so the abscissa
    l_c/EI_ref is the ABSOLUTE element size, same as LCI; Ch_i_f blank → 1
    (size scaling applies to the fracture strain — LCI's role). fct_IDT
    stays 0 ALWAYS (the LCH trap — see the resolver warning)."""
    sp20, sp10, sp30 = " " * 20, " " * 10, " " * 30
    return [
        f"/FAIL/TAB1/{mat.mid}",
        "# IFAIL_SH  IFAIL_SO                             P_THICKFAIL          P_thinfail               Ixfem",
        f"{_i(mat.ifail_sh)}{_i(mat.ifail_so)}{sp20}{_f(mat.pthickfail)}{_f(0.0)}{sp10}{_i(0)}",
        "#              Dcrit                   D                   N                Dadv   fct_IDD",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
        "#TABLE1_ID             Xscale1             Xscale2 TABLE2_ID             Xscale3             Xscale4",
        f"{_i(mat.fail_table1)}{_f(0.0)}{_f(0.0)}{_i(0)}{_f(0.0)}{_f(0.0)}",
        "# fct_IDEL           Fscale_EL              EI_REF          INST_START             FAD_EXP    CH_I_F",
        f"{_i(mat.fct_idel)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
        "#  fct_IDT             FscaleT                              Shear_limit             Biax_limit",
        f"{_i(0)}{_f(0.0)}{sp30}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Impact / blast materials batch
#   *MAT_JOHNSON_HOLMQUIST_CERAMICS (110)   → /MAT/LAW79  (JOHN_HOLM)
#   *MAT_JOHNSON_HOLMQUIST_CONCRETE (111)   → /MAT/LAW126
#   *MAT_ELASTIC _FLUID option      (001)   → /MAT/LAW6 + /EOS/POLYNOMIAL
#
# The batch's defining property is that NOTHING is normalized on conversion.
# Both Johnson-Holmquist laws are written in the same normalized-strength form
# LS-DYNA uses, and the Radioss starter/engine re-derive every normalizer with
# the identical definitions: sigma_HEL = 1.5*(HEL-PHEL) and T* = T/PHEL for
# JH-2 (hm_read_mat79.F:211-213), P* = P/FC and T* = T/FC for JHC
# (sigeps126.F90:264,338). A converter that "helpfully" divided T by PHEL/FC,
# or passed sigma_HEL where HEL belongs, would double-apply the normalization
# and silently soften the material — this is the classic trap of the family.
# dyna2rad copies all 18/21 fields verbatim for exactly this reason, and so
# does k2rad.
# ─────────────────────────────────────────────────────────────────────────────

# LS-DYNA's documented "no cavitation" sentinel for *MAT_ELASTIC_FLUID CP
# (Vol II R16 p.2-148, mat_001.cfg:52 DEFAULTS). A CP at or above it is the
# card default, not a real cut-off, and must map to Radioss Pmin = -INFINITY
# (written as a blank 0, hm_read_mat06.F:154) rather than to -1e20.
_LSD_CP_NO_CAVITATION = 1.0e20

# ...but the literal 1e20 is a RAW NUMBER, so testing it alone is unit-system
# dependent. The corpus proves it on one material: the W11 bird-strike "Head"
# fluid writes CP = 1.0e20 in its SI (kg-m-s) copy and CP = 1e14 in the
# unit-converted ton-mm-s copy — the same 1e20 Pa, the same physical material,
# one hitting the sentinel and one missing it. A cut-off this far above the
# material's OWN bulk modulus is unreachable in either code (Pmin = -CP is
# reached at a volumetric strain of CP/K), so it is the card default in
# disguise. 1e6 is deliberately far above any physical cavitation pressure,
# which is at most a fraction of K.
_CP_UNREACHABLE_BULK_FACTOR = 1.0e6

# SI multiplier prefixes exactly as the starter's own /BEGIN unit-label parser
# reads them (unit_code.F:99-143). A time label is at most THREE characters,
# the last of which must be 's'; the leading one or two are the prefix. Any
# other spelling is starter ERROR 573, so returning None for it is right.
_SI_PREFIX_FACTORS: Dict[str, float] = {
    "y": 1.0e-24, "z": 1.0e-21, "a": 1.0e-18, "f": 1.0e-15, "p": 1.0e-12,
    "n": 1.0e-9, "mu": 1.0e-6, "u": 1.0e-6, "m": 1.0e-3, "c": 1.0e-2,
    "d": 1.0e-1, "": 1.0, "da": 1.0e1, "h": 1.0e2, "k": 1.0e3, "K": 1.0e3,
    "M": 1.0e6, "G": 1.0e9, "T": 1.0e12, "P": 1.0e15, "E": 1.0e18,
    "Z": 1.0e21, "Y": 1.0e24,
}

# The quasi-static threshold strain rate substituted for an unusable EPS0, in
# 1/SECOND. 1 s^-1 is the reference rate of the Johnson-Holmquist papers both
# laws come from, and it is what the starter's own C == 0 default
# (hm_read_mat79.F:159, hm_read_mat126.F90:161) means on a seconds-based deck.
_QUASI_STATIC_RATE_PER_S = 1.0

# Bracket for LS-DYNA's mu_hel iteration (see _mat110_mu_hel). mu_hel is O(0.1)
# for every real ceramic; mu = 1 is a doubled density and far outside any
# elastic limit, so a root beyond it means the card is not a JH-2 card.
_MU_HEL_MAX = 1.0
_MU_HEL_SCAN_STEPS = 10000


def _time_unit_in_seconds(label: str) -> Optional[float]:
    """Seconds per one deck time unit, parsed the way the starter parses the
    /BEGIN unit labels itself (unit_code.F:99-143): ``'s'`` -> 1.0,
    ``'ms'`` -> 1e-3, ``'mus'``/``'us'`` -> 1e-6. ``None`` for any label the
    starter would itself reject (more than 3 characters, not ending in 's', or
    an unknown prefix), so a caller can fall back instead of guessing.
    """
    key = (label or "").strip()
    if not key or len(key) > 3 or key[-1] != "s":
        return None
    return _SI_PREFIX_FACTORS.get(key[:-1])


def _quasi_static_eps0(state: ConversionState) -> Tuple[float, str]:
    """The EPS0 substituted for an unusable one, expressed in the DECK's time
    unit, plus a phrase naming that unit for the warning.

    EPS0 is a 1/time quantity (Vol II R16 *MAT_015: "input in units of
    [time]^-1 ... if the system of units for the model input is {kg, mm, ms},
    then EPS0 should be set to 10^-5") and k2rad rescales nothing — the /BEGIN
    input units ARE the work units — so a bare 1.0 means one per DECK time
    unit, i.e. 1000 s^-1 on a ton-mm-ms deck. That is not "quasi-static": both
    engines clamp the rate factor to 1 BELOW EPS0 (sigeps79.F:178-182,
    sigeps126.F90:279), so an over-large EPS0 switches rate hardening off over
    the whole range of interest instead of merely shifting its onset.
    """
    fac = _time_unit_in_seconds(state.units[2])
    if fac is None:
        # Unparseable label: the deck will not reach the engine anyway
        # (starter ERROR 573), so keep the starter's own raw default.
        return _QUASI_STATIC_RATE_PER_S, ""
    value = _QUASI_STATIC_RATE_PER_S * fac
    return value, (f" per the deck's time unit '{state.units[2]}' "
                   f"(= {_QUASI_STATIC_RATE_PER_S:g} s^-1)")


def _mat110_mu_hel(hel: float, g: float,
                   k1: float, k2: float, k3: float) -> Optional[float]:
    """Smallest positive root of LS-DYNA's own mu_hel equation, Vol II R16
    p.2-763::

        HEL = k1*mu + k2*mu^2 + k3*mu^3 + (4/3)*g*mu/(1+mu)

    "Given HEL and G, mu_hel can be found iteratively from ..." — and p.2-764:
    "These are calculated automatically by LS-DYNA if p_hel is zero on input."

    f(0) = -HEL < 0, so a linear scan finds the first sign change and bisection
    refines it; scanning rather than Newton keeps the SMALLEST root when K2 < 0
    makes the polynomial non-monotonic. ``None`` when no root lies in
    (0, _MU_HEL_MAX], which is the signal to leave PHEL alone and warn.
    """
    def f(mu: float) -> float:
        return (k1 * mu + k2 * mu * mu + k3 * mu * mu * mu
                + (4.0 / 3.0) * g * mu / (1.0 + mu) - hel)

    step = _MU_HEL_MAX / _MU_HEL_SCAN_STEPS
    lo = 0.0
    hi = None
    for i in range(1, _MU_HEL_SCAN_STEPS + 1):
        mu = i * step
        if f(mu) >= 0.0:
            hi = mu
            break
        lo = mu
    if hi is None:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:
            break
        if f(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _resolve_mat_impact(state: ConversionState) -> None:
    """Guards, defaults and warnings for the impact/blast material batch.

    Every routing decision lands in the ``*_eff`` / ``idel`` / ``bulk`` /
    ``pmin`` fields of the dataclasses; the three emitters below only format
    cards. ``_shell_parts_by_mid`` is built ONCE and shared by the three
    solid-only checks (the LAW21/LAW40/LAW115 precedent — an O(n_shells) scan
    inside a per-material loop is O(n_shells x n_materials)).
    """
    if not (state.mat_jh_ceramics or state.mat_jh_concrete
            or state.mat_elastic_fluid):
        return
    shell_parts = _shell_parts_by_mid(state)
    _resolve_mat110(state, shell_parts)
    _resolve_mat111(state, shell_parts)
    _resolve_mat_elastic_fluid(state, shell_parts)


def _warn_impact_shell_parts(state: ConversionState, shell_parts: dict,
                             mid: int, tag: str, law: str,
                             classes: str, ref: str, remedy: str) -> None:
    """The PR #110 solid-only shell-part warning, shared by the three laws of
    this batch. None of LAW79 / LAW126 / LAW6 declares any SHELL_* class, so a
    shell part on any of them is starter ERROR 3046; dyna2rad checks none of
    the three (its converters never look at the element type at all)."""
    pids = shell_parts.get(mid, [])
    if not pids:
        return
    state.warn(
        f"{tag}: part(s) {pids} are SHELL parts, but {law} declares only "
        f"{classes} ({ref}) — no shell class at all. The starter rejects the "
        "combination with ERROR 3046 (material/element compatibility). "
        f"dyna2rad never checks this. {remedy}")


def _resolve_mat110(state: ConversionState, shell_parts: dict) -> None:
    """*MAT_JOHNSON_HOLMQUIST_CERAMICS (110) → /MAT/LAW79.

    Five of LAW79's six starter hard-errors are un-fixable physics and are
    reported as-is; the sixth (ERROR 910, EPS0 <= 0 with C != 0) is repaired
    with the starter's OWN rate-free default so an otherwise valid ceramic
    still converts to a runnable deck.

    The one field that does NOT come straight off the card is PHEL: a blank/0
    PHEL is a documented LS-DYNA derivation request (Vol II R16 p.2-763/764)
    that Radioss does not implement, so the iteration is reproduced here and
    the derived value goes into ``phel_eff``.
    """
    kw = "*MAT_JOHNSON_HOLMQUIST_CERAMICS"
    eps0_sub, eps0_unit = _quasi_static_eps0(state)
    for mat in state.mat_jh_ceramics.values():
        tag = f"{kw} mid={mat.mid}"
        mat.eps0_eff = mat.eps0
        mat.phel_eff = mat.phel
        # ERROR 910 (hm_read_mat79.F:164-198) — fatal, and repairable. The
        # starter already substitutes EPS0 = 1 when C == 0 (:159); do the same
        # substitution for C != 0, where it refuses to, because the LS-DYNA
        # card is just as undefined there (1 + C*ln(eps_dot/0)).
        if mat.c != 0.0 and mat.eps0 <= 0.0:
            mat.eps0_eff = eps0_sub
            state.warn(
                f"{tag}: EPS0={mat.eps0:g} with C={mat.c:g} != 0 is a FATAL "
                "input for /MAT/LAW79 — the starter stops with ERROR 910 "
                "(NEGATIVE OR ZERO REFERENCE STRAIN RATE, "
                "hm_read_mat79.F:164-198), which is exactly what a "
                "dyna2rad-converted deck does (it copies the 0 through). "
                f"k2rad writes EPS0 = {eps0_sub:g}{eps0_unit} instead — the "
                "starter's own rate-free substitution when C == 0 (:159), "
                "expressed in the deck's time unit because EPS0 is a 1/time "
                "quantity (Vol II R16 *MAT_015, which this card's EPS0 refers "
                "to) and k2rad rescales nothing. The rate term becomes "
                f"1 + C*ln(eps_dot/{eps0_sub:g}), and note the engine CLAMPS "
                "it to 1 below EPS0 (sigeps79.F:178-182), so an over-large "
                "EPS0 switches rate hardening off rather than shifting it. "
                "The LS-DYNA card is equally undefined at EPS0 = 0, so set the "
                "real quasi-static threshold rate on card 2 field 1 if the "
                "rate sensitivity matters.")
        # PHEL is the JH-2 pressure normalizer: the starter divides by it
        # (T* = TMAX/PHEL, P* = P/PHEL) and guards ONLY the PHEL > HEL case,
        # so a zero PHEL poisons the run with Inf/NaN and no diagnostic.
        # A zero PHEL is NOT a malformed card, though: it is a documented
        # LS-DYNA input mode in which LS-DYNA derives mu_hel, PHEL and
        # sigma_HEL itself (Vol II R16 p.2-763/764). Radioss has no such
        # derivation, so the converter has to do it — this is the one field of
        # the batch whose LS-DYNA value is not the number on the card.
        if mat.phel <= 0.0:
            mu_hel = None
            if mat.hel > 0.0 and mat.k1 > 0.0 and mat.g > 0.0:
                mu_hel = _mat110_mu_hel(mat.hel, mat.g,
                                        mat.k1, mat.k2, mat.k3)
            if mu_hel is not None:
                mat.phel_eff = (mat.k1 * mu_hel + mat.k2 * mu_hel ** 2
                                + mat.k3 * mu_hel ** 3)
                sig_hel = 1.5 * (mat.hel - mat.phel_eff)
                state.warn(
                    f"{tag}: PHEL is blank/0, which in LS-DYNA is not a "
                    "defect but a REQUEST — \"These are calculated "
                    "automatically by LS-DYNA if p_hel is zero on input\" "
                    "(Vol II R16 p.2-764): given HEL and G it solves "
                    "HEL = K1*mu + K2*mu^2 + K3*mu^3 + (4/3)*G*mu/(1+mu) for "
                    "mu_hel, then PHEL = K1*mu + K2*mu^2 + K3*mu^3 and "
                    "sigma_HEL = 1.5*(HEL-PHEL). /MAT/LAW79 has NO such "
                    "derivation — hm_read_mat79.F:211 forms T* = T/PHEL "
                    "directly and its only guard is PHEL > HEL (ERROR 907) — "
                    "so a copied-through 0 passes the starter with 0 ERROR / "
                    "0 WARNING and then poisons every P* and T* with Inf/NaN "
                    "for the whole run (that is what a dyna2rad-converted deck "
                    "does). k2rad reproduces LS-DYNA's own derivation instead "
                    f"and writes the DERIVED PHEL = {mat.phel_eff:g} "
                    f"(mu_hel = {mu_hel:g}, sigma_HEL = 1.5*(HEL-PHEL) = "
                    f"{sig_hel:g}, which the starter re-forms itself at "
                    ":212). Put that value on card 2 field 5 if you want the "
                    "two decks to read identically.")
            else:
                state.warn(
                    f"{tag}: PHEL={mat.phel:g} <= 0. PHEL is the JH-2 PRESSURE "
                    "NORMALIZER — the starter forms T* = T/PHEL "
                    "(hm_read_mat79.F:211) and the engine P* = P/PHEL "
                    "(sigeps79.F:153) — and its ONLY guard is PHEL > HEL "
                    "(ERROR 907), so this passes the starter with NO error and "
                    "NO warning and then poisons every stress evaluation with "
                    "Inf/NaN. LS-DYNA's own automatic derivation from HEL and "
                    "G (Vol II R16 p.2-763/764) cannot be reproduced here "
                    f"either: it needs HEL > 0 (got {mat.hel:g}), K1 > 0 (got "
                    f"{mat.k1:g}) and G > 0 (got {mat.g:g}) and a root of "
                    "HEL = K1*mu + K2*mu^2 + K3*mu^3 + (4/3)*G*mu/(1+mu) "
                    f"below mu = {_MU_HEL_MAX:g}. Supply the real pressure at "
                    "the Hugoniot elastic limit (card 2 field 5).")
        elif mat.phel > mat.hel:
            state.warn(
                f"{tag}: PHEL={mat.phel:g} > HEL={mat.hel:g}. The starter "
                "rejects this with ERROR 907 (hm_read_mat79.F:164-198): the "
                "pressure at the Hugoniot elastic limit cannot exceed the "
                "limit itself, and sigma_HEL = 1.5*(HEL-PHEL) would come out "
                "NEGATIVE. Check that card 2 fields 4 and 5 are HEL then "
                "PHEL, in that order.")
        if mat.g <= 0.0:
            state.warn(
                f"{tag}: G={mat.g:g} <= 0 — the starter stops with ERROR 908 "
                "(NEGATIVE OR ZERO SHEAR MODULUS, hm_read_mat79.F:164-198). "
                "Supply the elastic shear modulus on card 1 field 3.")
        if mat.k1 <= 0.0:
            state.warn(
                f"{tag}: K1={mat.k1:g} <= 0 — the starter stops with ERROR "
                "909. K1 is the linear term of LAW79's OWN polynomial EOS "
                "(P = K1*mu + K2*mu^2 + K3*mu^3, sigeps79.F:143-147), i.e. "
                "the bulk modulus, and it also sets the printed E and nu "
                "(PARMAT 2/3). Supply it on card 3 field 3.")
        if mat.beta < 0.0 or mat.beta > 1.0:
            state.warn(
                f"{tag}: BETA={mat.beta:g} is outside [0, 1] — the starter "
                "stops with ERROR 911. BETA is the DIMENSIONLESS fraction of "
                "the elastic energy loss converted to hydrostatic bulking "
                "(sigeps79.F:265-273), not an energy.")
        # FS: LAW79's IDEL/EPSMAX live on the radioss2023 card 8 only. At the
        # /BEGIN 2022 this converter writes, the CFG in play is
        # radioss120/MAT/matl79_79.cfg, whose card 8 is "%20lg%20lg" (D1, D2)
        # — the fields do not exist and cannot be written. FS = 0 is the
        # LS-DYNA default "no failure" AND the LAW79 default IDEL = 0 "no
        # deletion", so only a non-zero FS loses anything.
        if mat.fs != 0.0:
            if mat.fs > 0.0:
                lost = (f"FS={mat.fs:g} > 0 means 'delete when the plastic "
                        "strain exceeds FS', which /MAT/LAW79 expresses as "
                        f"IDEL=2 with EPSMAX={mat.fs:g}")
            else:
                lost = (f"FS={mat.fs:g} < 0 means 'delete when p* + t* < 0' "
                        "(tensile), which /MAT/LAW79 expresses as IDEL=1")
            state.warn(
                f"{tag}: {lost} — but IDEL and EPSMAX are radioss2023 fields "
                "(matl79_79.cfg FORMAT(radioss2023) card 8; the "
                "FORMAT(radioss120) block a /BEGIN 2022 deck reads ends at "
                "D1/D2), so the failure criterion is NOT EXPRESSIBLE in the "
                "emitted deck and is DROPPED: the converted ceramic never "
                "erodes. dyna2rad drops MAT_110's FS SILENTLY at every "
                "format version (it is absent from p_ConvertMatL110's attrib "
                "map, CM:12491-12506) even though it implements the same flag "
                "for MAT_111. Remedies: add a *MAT_ADD_EROSION to this MID "
                "(converted to a /FAIL card, which is version-independent), "
                "or raise the /BEGIN version to 2023+ and re-add IDEL/EPSMAX "
                "by hand. Note the tensile pressure cutoff PMIN = "
                "-T*.PHEL.(1-D) IS still applied at IDEL=0 "
                "(sigeps79.F:149-151), so tensile softening is not lost, only "
                "element deletion.")
        _warn_impact_shell_parts(
            state, shell_parts, mat.mid, tag, "/MAT/LAW79",
            "SOLID_ISOTROPIC and SPH", "hm_read_mat79.F:233-234",
            "*MAT_110 is a solid/SPH ceramic model on both sides "
            "(mat_110.cfg's own SUPPORT block lists only "
            "BRICK/TETRA4/LINEAR_3D); re-mesh the part as solids.")


def _resolve_mat111(state: ConversionState, shell_parts: dict) -> None:
    """*MAT_JOHNSON_HOLMQUIST_CONCRETE (111) → /MAT/LAW126.

    hm_read_mat126.F90 contains NO ANCMSG check at all — G <= 0, K1 <= 0 and
    EPS0 <= 0 all pass silently, and the two compaction divisions have no zero
    guard — so every diagnostic for this law has to come from the converter.
    """
    kw = "*MAT_JOHNSON_HOLMQUIST_CONCRETE"
    eps0_sub, eps0_unit = _quasi_static_eps0(state)
    for mat in state.mat_jh_concrete.values():
        tag = f"{kw} mid={mat.mid}"
        mat.eps0_eff = mat.eps0
        # FS -> IDEL/EPS_MAX (dyna2rad CM:5656-5672). Unlike LAW79 this DOES
        # work at /BEGIN 2022: LAW126's card 9 IDEL/EPS_MAX are in the
        # FORMAT(radioss2024) block, which is what a 2022 deck falls forward
        # into. The three LS-DYNA meanings and the three IDEL codes line up
        # one-for-one — note both differ from MAT_110's, whose FS = 0 means
        # "no failure" where MAT_111's means "tensile".
        if mat.fs > 0.0:
            mat.idel = 2          # plastic strain > EPS_MAX
        elif mat.fs < 0.0:
            mat.idel = 3          # SIGY <= 0 (damage strength exhausted)
        else:
            mat.idel = 1          # tensile P* + T* <= 0 — the LS-DYNA default
        # Copied unconditionally, exactly as dyna2rad does, INCLUDING the
        # meaningless negative value at FS < 0: IDEL=3 never reads EPS_MAX
        # (only IDEL=2 does), so it is inert, and keeping the copy verbatim
        # leaves the source FS visible in the converted deck.
        mat.eps_max = mat.fs
        if mat.c != 0.0 and mat.eps0 <= 0.0:
            mat.eps0_eff = eps0_sub
            state.warn(
                f"{tag}: EPS0={mat.eps0:g} with C={mat.c:g} != 0. "
                "hm_read_mat126.F90 substitutes EPS0 = 1 only when C == 0 "
                "(:161) and has NO error check of its own, so a copied-through "
                "0 passes the starter with no diagnostic and the engine then "
                "evaluates C*log(eps_dot/0) every cycle "
                "(sigeps126.F90) — that is what a dyna2rad-converted deck "
                f"does. k2rad writes EPS0 = {eps0_sub:g}{eps0_unit} instead — "
                "the starter's own rate-free default, expressed in the deck's "
                "time unit because EPS0 is a 1/time quantity (Vol II R16 "
                "*MAT_015) and k2rad rescales nothing — so the run is finite. "
                "Note the engine applies the rate factor ONLY above EPS0 "
                "(sigeps126.F90:279), so an over-large EPS0 switches rate "
                "hardening off rather than shifting it. Set the real "
                "quasi-static threshold rate on card 2 field 2 if the rate "
                "sensitivity matters.")
        # The two unguarded divisions of hm_read_mat126.F90:140,146.
        for name, val, expr, consequence in (
                ("UC", mat.uc, "k0 = PC/MUC (:140)",
                 "the region-1 bulk modulus becomes Infinity and the printed "
                 "YOUNG MODULUS / POISSON'S RATIO both become NaN"),
                ("UL", mat.ul, "h = (PL-PC)/MUL (:146)",
                 "the region-2 tangent bulk modulus becomes Infinity")):
            if val == 0.0:
                state.warn(
                    f"{tag}: {name}=0 (the {'crushing' if name == 'UC' else 'locking'} "
                    f"volumetric strain, LAW126 {'MUC' if name == 'UC' else 'MUL'}). "
                    f"The starter divides by it unguarded — {expr} — so "
                    f"{consequence}, and it reports 0 ERROR / 0 WARNING while "
                    "doing it. This is a SILENT NaN, not a survivable default: "
                    "supply the real compaction strain (card 2 field "
                    f"{6 if name == 'UC' else 8}).")
        if mat.g <= 0.0:
            state.warn(
                f"{tag}: G={mat.g:g} <= 0. Unlike /MAT/LAW79 (ERROR 908), "
                "hm_read_mat126.F90 has NO ANCMSG check anywhere, so this "
                "passes the starter silently and produces a zero/negative "
                "elastic shear response. Supply the shear modulus on card 1 "
                "field 3.")
        if mat.k1 <= 0.0:
            state.warn(
                f"{tag}: K1={mat.k1:g} <= 0. K1 is the linear term of "
                "LAW126's OWN fully-compacted polynomial EOS (uparam(14..16); "
                "no /EOS card is emitted or needed) and is also PARMAT(1). "
                "LAW126 performs no validation, so this passes the starter "
                "silently.")
        if mat.fc <= 0.0:
            state.warn(
                f"{tag}: FC={mat.fc:g} <= 0. FC is the JHC NORMALIZER for "
                "every strength quantity — the engine forms P* = P/FC, "
                "sigma* = sigma_VM/FC and T* = T/FC and multiplies the yield "
                "back up by FC (sigeps126.F90:264,305,338,383) — so a "
                "zero/negative FC makes the whole yield surface Inf/NaN or "
                "sign-flipped. There is no starter check. Supply the "
                "quasi-static uniaxial compressive strength on card 1 "
                "field 8.")
        # k0 = PC/MUC together with G fixes the printed elastic constants; a
        # too-stiff crush pair drives Poisson negative with no complaint.
        if mat.uc != 0.0 and mat.g > 0.0:
            k0 = mat.pc / mat.uc
            denom = 6.0 * k0 + 2.0 * mat.g
            if denom != 0.0:
                nu = (3.0 * k0 - 2.0 * mat.g) / denom
                if nu < 0.0 or nu >= 0.5:
                    state.warn(
                        f"{tag}: the Poisson's ratio /MAT/LAW126 derives from "
                        f"k0 = PC/MUC = {mat.pc:g}/{mat.uc:g} = {k0:g} and "
                        f"G={mat.g:g} is {nu:g}, outside [0, 0.5) "
                        "(hm_read_mat126.F90:140-146). The starter prints it "
                        "and continues without a diagnostic. Check that PC "
                        "and UC are the crushing PRESSURE and its VOLUMETRIC "
                        "STRAIN (card 2 fields 5 and 6) and not swapped.")
        _warn_impact_shell_parts(
            state, shell_parts, mat.mid, tag, "/MAT/LAW126",
            "SOLID_ISOTROPIC, SPH, COMPRESSIBLE, INCREMENTAL, LARGE_STRAIN, "
            "HYDRO_EOS and ISOTROPIC", "hm_read_mat126.F90:247-255",
            "*MAT_111 is a solid/SPH concrete model on both sides; re-mesh "
            "the part as solids.")
        # The version gate, reported once per material so the starter's own
        # output does not read as a conversion defect (the LAW169 precedent).
        state.warn(
            f"{tag}: /MAT/LAW126 is first registered in the radioss2024 "
            "profile (radioss2022/data_hierarchy.cfg has no LAW126 entry at "
            "all); under the /BEGIN 2022 header this converter writes, the "
            "starter prints one non-fatal WARNING 100211 (\"Unsupported "
            "option ... in format < 2024\") and then parses the card with the "
            "2024 FORMAT, which is exactly the layout emitted here. No action "
            "needed. One real consequence of the gate: IFAILSO (post-failure "
            "stress handling) is a radioss2025 field and is unreachable at "
            "2022, so it stays at its clamped default 1 — dyna2rad never "
            "sets it either, so nothing is lost relative to that converter.")


def _resolve_mat_elastic_fluid(state: ConversionState,
                               shell_parts: dict) -> None:
    """*MAT_ELASTIC with the _FLUID option (001) → /MAT/LAW6 + /EOS/POLYNOMIAL.

    Three deliberate departures from dyna2rad, all recorded in the warnings:
    the K == 0 fallback uses the REAL Poisson ratio, VC is not copied into a
    slot that means something else, and a defaulted CP does not become a
    finite pressure cut-off — where "defaulted" is judged against the
    material's own bulk modulus as well as against the raw 1e20 literal, so
    the emitted card does not depend on the deck's unit system.
    """
    kw = "*MAT_ELASTIC_FLUID"
    for mat in state.mat_elastic_fluid.values():
        tag = f"{kw} mid={mat.mid}"
        # ── Bulk modulus → /EOS/POLYNOMIAL C1 ─────────────────────────────
        # LS-DYNA Remark 5: under FLUID, K must be defined, E and PR are
        # ignored, and G is set to 0. K = E/(3(1-2nu)) is the manual's own
        # relation and the documented fallback.
        derived = 0.0
        if mat.pr < 0.5:
            denom = 3.0 * (1.0 - 2.0 * mat.pr)
            if denom > 0.0:
                derived = mat.e / denom
        if mat.k > 0.0:
            mat.bulk = mat.k
        elif mat.pr >= 0.5:
            # `derived` is still its 0.0 SENTINEL here — the expression is
            # singular at PR == 0.5 and negative above it, so there is no
            # value to quote and no fallback to announce. One warning, not the
            # "derived as ... = 0" wording plus a contradiction.
            mat.bulk = 0.0
            state.warn(
                f"{tag}: K={mat.k:g} on card 1 field 7 is blank/0 or negative "
                f"AND PR={mat.pr:g} >= 0.5, so the manual's fallback "
                "K = E/(3(1-2*PR)) (Vol II R16 p.2-148, Remark 5) is infinite "
                "or negative and cannot be used — the /EOS/POLYNOMIAL C1 is "
                "written 0. A LAW6 whose EOS gives C1 = 0 passes the starter "
                "with 0 errors and 0 warnings but has ZERO bulk modulus and "
                "zero sound speed (PM(32) = C1, hm_read_mat06.F), so the fluid "
                "is inert. Supply K on card 1 field 7.")
        else:
            mat.bulk = derived
            if mat.k < 0.0:
                state.warn(
                    f"{tag}: K={mat.k:g} is NEGATIVE. A bulk modulus must be "
                    "positive; dyna2rad matches neither of its two branches "
                    "here (K > 0 copy, K == 0 expression) and so leaves the "
                    "/EOS bulk modulus at 0 — a fluid with zero sound speed, "
                    "silently (CM:12093-12136). k2rad substitutes "
                    f"K = E/(3(1-2*PR)) = {derived:g} from card 1 fields 3 "
                    "and 4 instead. Fix the sign on card 1 field 7.")
            else:
                state.warn(
                    f"{tag}: K is blank/0 on card 1 field 7, so the bulk "
                    f"modulus is derived from the card's E={mat.e:g} and "
                    f"PR={mat.pr:g} as K = E/(3(1-2*PR)) = {derived:g} — the "
                    "relation the LS-DYNA manual itself states for the FLUID "
                    "option (Vol II R16 p.2-148, Remark 5). NOTE this is a "
                    "FIX of a dyna2rad defect: its expression uses the token "
                    "'NU' where the attribute is spelled 'Nu' (solver name "
                    "'PR'), identifier lookup is case-sensitive, and an "
                    "unresolved token silently becomes 0 "
                    "(convertutilsbase.cxx:192) — so dyna2rad computes E/3 "
                    f"({mat.e / 3.0 if mat.e else 0.0:g}) and loses Poisson's "
                    "ratio entirely. Supplying K explicitly avoids the "
                    "question.")
        if mat.bulk <= 0.0 and mat.k >= 0.0 and mat.pr < 0.5:
            state.warn(
                f"{tag}: the /EOS/POLYNOMIAL C1 (bulk modulus) resolves to "
                f"{mat.bulk:g}. The starter takes PM(32) = C1 as the bulk "
                "modulus for the sound speed, the timestep and the TYPE7 "
                "contact stiffness, and accepts 0 with no diagnostic — the "
                "fluid would be completely inert. Supply K on card 1 field 7 "
                "(or a non-zero E with PR < 0.5).")
        # ── VC: dimensionless coefficient vs kinematic viscosity ──────────
        # LS-DYNA VC scales an ARTIFICIAL deviatoric stress
        # S'ij = VC*dL*a*rho*edot'ij (dL the characteristic element length, a
        # the bulk sound speed); Radioss Nu (DAMP1, DIMENSION eddyviscosity =
        # L^2/T) is a TRUE kinematic viscosity used as sigma_dev = 2*rho*Nu*
        # edot_dev. The two differ by the factor dL*a, which is per-element
        # and not knowable at material-conversion time, so a verbatim copy
        # (what dyna2rad does) is wrong by that factor.
        mat.nu_visc = 0.0
        if mat.vc != 0.0:
            if mat.bulk > 0.0 and mat.rho > 0.0:
                sound = math.sqrt(mat.bulk / mat.rho)
                recipe = (f"nu ~= VC*dL*a = {mat.vc:g}*dL*{sound:g} = "
                          f"{mat.vc * sound:g}*dL")
            else:
                sound = 0.0
                recipe = ("nu ~= VC*dL*a with a = sqrt(K/rho) (not computable "
                          "here: K and/or RHO is 0)")
            state.warn(
                f"{tag}: VC={mat.vc:g} is DROPPED (the /MAT/LAW6 kinematic "
                "viscosity Nu is written 0). LS-DYNA's VC is a DIMENSIONLESS "
                "tensor-viscosity coefficient scaling an artificial "
                "deviatoric stress S'ij = VC*dL*a*rho*edot'ij (dL = element "
                "characteristic length, a = bulk sound speed), while Radioss "
                "Nu is a TRUE kinematic viscosity in L^2/T "
                "(mat_law6.cfg DAMP1, DIMENSION=eddyviscosity) entering as "
                "sigma_dev = 2*rho*Nu*edot_dev. dyna2rad copies the number "
                "verbatim into that slot (CM:12093-12136), which is wrong by "
                "the factor dL*a — orders of magnitude on any real mesh. To "
                f"restore the damping by hand: {recipe}, with dL the "
                "characteristic length of the fluid elements.")
        # ── CP cavitation pressure → Pmin cut-off ─────────────────────────
        # Radioss Pmin is a LOWER pressure cut-off (negative); LS-DYNA CP is
        # the positive cavitation pressure, default 1e20 = "no limit". A
        # blank/defaulted CP must therefore leave Pmin at 0, which the starter
        # turns into -INFINITY (hm_read_mat06.F:154).
        # The raw 1e20 test is unit-dependent, so a CP that is unreachable
        # relative to the material's OWN bulk modulus counts as the default
        # too — otherwise the same physical fluid converts to two different
        # cards depending only on the deck's units.
        unreachable = (mat.bulk > 0.0
                       and abs(mat.cp)
                       >= _CP_UNREACHABLE_BULK_FACTOR * mat.bulk)
        if not mat.cp_given or abs(mat.cp) >= _LSD_CP_NO_CAVITATION:
            mat.pmin = 0.0
        elif unreachable:
            mat.pmin = 0.0
            state.warn(
                f"{tag}: CP={mat.cp:g} is {abs(mat.cp) / mat.bulk:g} x the "
                f"bulk modulus K={mat.bulk:g}, i.e. a tension cut-off that "
                "would need a volumetric strain of that order to reach and can "
                "never bind. LS-DYNA's 'no cavitation' card default is the RAW "
                "literal 1e20 (mat_001.cfg:52), and a unit-converted deck "
                "carries it RESCALED — the same bird-strike fluid reads "
                "CP=1e20 in its kg-m-s copy and CP=1e14 in the ton-mm-s one — "
                "so testing the literal alone would make the emitted card "
                "depend on the deck's units. k2rad treats this as the default "
                "and writes Pmin = 0, which the starter turns into -INFINITY "
                "(hm_read_mat06.F:154), the same card the SI copy gets. Supply "
                "a CP within a few multiples of K if a real cavitation cut-off "
                "is meant.")
        elif mat.cp > 0.0:
            mat.pmin = -mat.cp
        elif mat.cp < 0.0:
            mat.pmin = -abs(mat.cp)
            state.warn(
                f"{tag}: CP={mat.cp:g} is negative. LS-DYNA's cavitation "
                "pressure is defined positive (the fluid cavitates when the "
                "pressure falls below it); the Radioss Pmin cut-off is the "
                f"negative-going one, so this is written Pmin = {mat.pmin:g}. "
                "Check the sign convention on card 2 field 2.")
        else:
            # An EXPLICIT CP = 0.0 means "cavitate at zero pressure", which is
            # NOT the same as a blank cell. Radioss cannot say it: Pmin = 0 is
            # the reader's "no cut-off" sentinel.
            mat.pmin = 0.0
            state.warn(
                f"{tag}: CP=0.0 is written explicitly on card 2, i.e. "
                "'cavitate as soon as the pressure reaches 0'. That exact "
                "threshold is NOT EXPRESSIBLE: Radioss reads Pmin = 0 as the "
                "sentinel for NO cut-off at all (hm_read_mat06.F:154 "
                "IF (PMIN == ZERO) PMIN = -INFINITY), so the converted fluid "
                "sustains unlimited tension. dyna2rad has the same loss, "
                "silently. Use a small negative Pmin (a fraction of the bulk "
                "modulus) on the emitted /MAT/HYD_VISC if the cavitation "
                "cut-off matters.")
        if mat.da != 0.0 or mat.db != 0.0:
            state.warn(
                f"{tag}: DA={mat.da:g} / DB={mat.db:g} (axial and bending "
                "damping constants) are DROPPED — they act on BEAM elements "
                "only, and *MAT_ELASTIC_FLUID is a solid-element material on "
                "both sides. dyna2rad drops them too.")
        if mat.e != 0.0 or mat.pr != 0.0:
            if mat.k > 0.0:
                state.warn(
                    f"{tag}: E={mat.e:g} and PR={mat.pr:g} are DROPPED. Under "
                    "the FLUID option LS-DYNA itself ignores both and sets "
                    "the shear modulus to zero (Vol II R16 p.2-148, "
                    "Remark 5); /MAT/LAW6 has no shear-modulus field at all, "
                    "so the pure-hydrodynamic response is exact rather than "
                    "an approximation. The deviatoric stress comes only from "
                    "the viscosity Nu.")
        _warn_impact_shell_parts(
            state, shell_parts, mat.mid, tag, "/MAT/LAW6 (HYD_VISC)",
            "EOS, HYDRO_EOS, INCOMPRESSIBLE, SOLID_POROUS and SPH",
            "hm_read_mat06.F:185-194",
            "The FLUID option is solid-elements-only in LS-DYNA too. Note "
            "SOLID_POROUS (not SOLID_ISOTROPIC) additionally limits LAW6 to "
            "/PROP/TYPE14 and TYPE15 solid properties — an orthotropic or "
            "composite solid property on this material is ERROR 3047 "
            "(init_mat_keyword.F:212-231).")


def _emit_mat_law79(mat: MatJHCeramics) -> List[str]:
    """*MAT_JOHNSON_HOLMQUIST_CERAMICS (110) → /MAT/LAW79 (JOHN_HOLM, JH-2).

    Layout audited against hm_cfg_files radioss120/MAT/matl79_79.cfg
    FORMAT(radioss120):207-236 — the newest LAW79 block a /BEGIN 2022 deck
    reads (radioss2022/data_hierarchy.cfg:1301-1307 registers LAW79 natively,
    so there is NO version warning), and identical to the worked Al2O3 example
    in the Altair Radioss 2022 Reference Guide p.634::

      C1: rho_i(20) [rho_0(20)]
      C2: G(20)
      C3: a(20) b(20) m(20) n(20)
      C4: c(20) EPS0(20) SIGMA_FMAX(20)
      C5: T(20) HEL(20) PHEL(20)
      C6: D1(20) D2(20)
      C7: K1(20) K2(20) K3(20) BETA(20)

    Card 1 is written with ONE field: the CFG runs a
    ``CARD_PREREAD("%20s", DUMMY)`` on columns 21-40 and any non-blank there
    switches the card to the two-field rho_i/rho_0 form, so omitting the
    reference density entirely is the unambiguous way to say "same as rho_i".

    **No normalization, by design.** a/b/c/m/n and SIGMA_FMAX are dimensionless
    in both codes; T, HEL and PHEL are copied as PHYSICAL stresses. The starter
    derives sigma_HEL = 1.5*(HEL-PHEL) and T* = T/PHEL itself
    (hm_read_mat79.F:211-213) and the engine forms P* = P/PHEL and
    sigma* = sigma_VM/sigma_HEL (sigeps79.F:153,190) — bit-identical to the
    LS-DYNA definitions (Vol II R16 p.2-763). K1/K2/K3 are LAW79's own
    polynomial EOS, so NO /EOS block is emitted.

    The one field that is NOT a straight copy is PHEL: a blank/0 PHEL is the
    documented LS-DYNA mode in which LS-DYNA solves for ``mu_hel`` itself
    (p.2-764), which Radioss does not implement, so ``phel_eff`` carries either
    the card value or the reproduced derivation — see ``_resolve_mat110``.

    Two field-order traps vs the LS-DYNA card: *MAT_110 card 1 runs
    ``... C M N`` while LAW79 card 3 runs ``a b m n`` with c moving to card 4,
    and BETA moves from LS-DYNA card 2 to the END of LAW79 card 7.

    Not emitted at /BEGIN 2022: Fcut (card 4 field 4) and IDEL/EPSMAX (card 6
    fields 4/5) are radioss2023 additions — see the FS warning in
    ``_resolve_mat110``. Starter defaults fill the rest: SIGMA_FMAX 0 →
    INFINITY, EPSMAX → INFINITY, IDEL → 0.
    """
    return [
        f"/MAT/LAW79/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  G",
        f"{_f(mat.g)}",
        "#                  a                   b                   m                   n",
        f"{_f(mat.a)}{_f(mat.b)}{_f(mat.m)}{_f(mat.n)}",
        "#                  c                EPS0          SIGMA_FMAX",
        f"{_f(mat.c)}{_f(mat.eps0_eff)}{_f(mat.sfmax)}",
        "#                  T                 HEL                PHEL",
        f"{_f(mat.t)}{_f(mat.hel)}{_f(mat.phel_eff)}",
        "#                 D1                  D2",
        f"{_f(mat.d1)}{_f(mat.d2)}",
        "#                 K1                  K2                  K3                BETA",
        f"{_f(mat.k1)}{_f(mat.k2)}{_f(mat.k3)}{_f(mat.beta)}",
        HDR,
    ]


def _emit_mat_law126(mat: MatJHConcrete) -> List[str]:
    """*MAT_JOHNSON_HOLMQUIST_CONCRETE (111) → /MAT/LAW126.

    Layout audited against hm_cfg_files
    radioss2024/MAT/matl126_johnson_holmquist_concrete.cfg
    FORMAT(radioss2024):189-202 — the OLDEST block that exists for this law and
    therefore the one a /BEGIN 2022 deck falls forward into (one cosmetic
    WARNING 100211, reported by ``_resolve_mat111``)::

      C1: rho_i(20)                    <- SINGLE field: no CARD_PREREAD and no
                                          Refer_Rho attribute, unlike LAW79
      C2: G(20)
      C3: A(20) B(20) N(20) FC(20) T(20)
      C4: C(20) EPS0(20) FCUT(20) SFMAX(20) EFMIN(20)
      C5: PC(20) MUC(20) PL(20) MUL(20)
      C6: K1(20) K2(20) K3(20)
      C7: D1(20) D2(20) [10 blanks] IDEL(10, INT) EPS_MAX(20)

    Card 7's IDEL is a ``%10d`` INTEGER at columns 51-60 preceded by a 10-char
    blank — ``CARD("%20lg%20lg%10s%10d%20lg", D1, D2, _BLANK_, IDEL, EPSMAX)``.
    The cfg's own card-1 banner reads "Init. dens."; the k2rad-standard RHO_I
    label is used here for consistency across the emitters (banner lines are
    comments the starter never parses).

    **No normalization, by design.** FC is the JHC normalizer and is copied as
    a PHYSICAL stress alongside T, PC, PL, K1..K3 and G; A, B, N, SFMAX, EFMIN,
    D1, D2 and the volumetric strains MUC/MUL are dimensionless. The engine
    forms P* = P/FC, sigma* = sigma_VM/FC and T* = T/FC and multiplies the
    yield back up by FC (sigeps126.F90:264,305,338,383), so pre-dividing T by
    FC would apply the normalization twice. K1/K2/K3 are LAW126's own
    fully-compacted polynomial EOS (uparam(14..16)) — the HYDRO_EOS class tag
    is a pressure-treatment capability, NOT a request for a companion /EOS
    block, so none is emitted.

    Field-name traps: LS-DYNA ``UC``/``UL`` are Radioss ``MUC``/``MUL``, and
    *MAT_111 card 1 field 7/8 are N and FC where *MAT_110 has M and N.

    Not emitted at /BEGIN 2022: FCUT is written blank (0 = no rate filter,
    ISRATE off), IFAILSO is a radioss2025 field and CT/POWT/CC/POWC a
    radioss2026 card — both are omitted, and the starter clamps IFAILSO to its
    default 1. EPS_MAX carries FS verbatim including a negative value at
    IDEL=3, matching dyna2rad; it is inert there (only IDEL=2 reads it).
    """
    return [
        f"/MAT/LAW126/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  G",
        f"{_f(mat.g)}",
        "#                  A                   B                   N                  FC                   T",
        f"{_f(mat.a)}{_f(mat.b)}{_f(mat.n)}{_f(mat.fc)}{_f(mat.t)}",
        "#                  C                EPS0                FCUT               SFMAX               EFMIN",
        f"{_f(mat.c)}{_f(mat.eps0_eff)}{_f(0.0)}{_f(mat.sfmax)}{_f(mat.efmin)}",
        "#                 PC                 MUC                  PL                 MUL",
        f"{_f(mat.pc)}{_f(mat.uc)}{_f(mat.pl)}{_f(mat.ul)}",
        "#                 K1                  K2                  K3",
        f"{_f(mat.k1)}{_f(mat.k2)}{_f(mat.k3)}",
        "#                 D1                  D2                IDEL             EPS_MAX",
        f"{_f(mat.d1)}{_f(mat.d2)}{' ' * 10}{_i(mat.idel)}{_f(mat.eps_max)}",
        HDR,
    ]


def _emit_mat_elastic_fluid(mat: MatElasticFluid) -> List[str]:
    """*MAT_ELASTIC _FLUID option (001) → /MAT/HYD_VISC (LAW6) +
    /EOS/POLYNOMIAL of the SAME id.

    LAW6 layout audited against hm_cfg_files radioss2020/MAT/mat_law6.cfg
    FORMAT(radioss2018):318-326 — the newest LAW6 block a /BEGIN 2022 deck
    reads — and identical to the ``_emit_mat_law6_carrier`` form the official
    Drop_Container FSI example uses::

      C1: rho_i(20) [rho_0(20)]
      C2: Nu(20) Pmin(20)

    The modern 2-card form is emitted, NOT the legacy embedded-EOS form: that
    one is gated on the trailing free-card COUNT (hm_read_mat06.F:105,113-116)
    and needs exactly 3 or exactly 0 trailing cards, and it binds Pmin twice
    (card 2 col 21-40 and card 4 col 1-20) with the LATER one winning.

    **The /EOS is mandatory, not optional.** A 2-card LAW6 with no /EOS passes
    the starter with 0 errors and 0 warnings but leaves IEOS = 0 and
    PM(32) = C1 = 0, i.e. zero bulk modulus and zero sound speed. The /EOS
    block binds by id (eosid == mid), so it is emitted for every fluid.

    /EOS/POLYNOMIAL is used where dyna2rad writes /EOS/LINEAR (CM:12093-12136,
    EOS_Options 13): the two express the same law — P = C0 + C1*mu with
    C0 = 0 IS the linear form, and the 2022 Reference Guide p.1060 Comment 3
    confirms C2/C3 are simply not evaluated for a linear volumetric material —
    but POLYNOMIAL is native to the radioss2022 profile this converter targets
    and is the block k2rad already emits for *EOS_LINEAR_POLYNOMIAL. All of
    C0, C2, C3, C4, C5, E0 and Psh stay 0: a Mie-Grueneisen Gamma would be
    C4 = C5 = Gamma, and there is none for a linear fluid.

    Fields: RHO_I from card 1 field 2; Nu from VC and Pmin from CP, both
    resolved by ``_resolve_mat_impact`` (VC is NOT a 1:1 copy and a defaulted
    CP is NOT a finite cut-off — see the warnings there); C1 from K, or the
    manual's K = E/(3(1-2*PR)) when K is absent. E, PR, DA and DB are not
    transferred: LS-DYNA ignores E/PR under FLUID and sets G = 0, and LAW6 has
    no shear-modulus field, so the pure-hydrodynamic response is exact.
    """
    return [
        f"/MAT/HYD_VISC/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                 Nu                Pmin",
        f"{_f(mat.nu_visc)}{_f(mat.pmin)}",
    ] + _emit_eos(EosCard(
        eosid=mat.mid, kind="POLYNOMIAL", rho0=0.0,
        params={"c0": 0.0, "c1": mat.bulk, "c2": 0.0, "c3": 0.0,
                "c4": 0.0, "c5": 0.0, "e0": 0.0, "psh": 0.0, "rho0": 0.0}))


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
    # Local import: writer/loads.py imports writer/mesh.py, which imports THIS
    # module at load time, so a top-level import here would close the cycle —
    # the same shape as the _target_mat_law imports below.
    from .loads import _monotonic_abscissae
    tables_2d = {tbid: t for tbid, t in state.define_tables.items()
                 if t.resolved and t.rows}
    if not state.curves and not tables_2d and not state.auto_tables:
        return []
    table_ids = state.table_1d_ids
    lines = ["#-  FUNCTIONS:", HDR]
    for lcid, curve in sorted(state.curves.items()):
        # Precedence note: the table branch is tested FIRST, so a curve that a
        # material law consumes through a TABLE slot goes out as /TABLE/1 even
        # if it came from a *DEFINE_CURVE_SMOOTH. Deliberate — a law's Tab_ID
        # slot resolves /TABLE ids, and ISMOOTH is a time-interpolation flag the
        # /IMP* consumers read, not something a stress-strain table uses.
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
        elif lcid in state.funct_smooth_ids:
            # *DEFINE_CURVE_SMOOTH -> /FUNCT_SMOOTH. Same id namespace as
            # /FUNCT and /TABLE (one hm_read_funct.F reads all three into
            # NPC/PLD; a collision is starter ERROR 79), which is exactly why
            # the curve lives in state.curves and is only FLAGGED here.
            #
            # The extra card is the difference from /FUNCT
            # (radioss2020/CURVE/funct_smooth.cfg:52-62): Ascalex Fscaley
            # Ashiftx Fshifty, applied as scale THEN shift
            # (hm_read_funct.F:232-233). *DEFINE_CURVE_SMOOTH has no scale or
            # offset fields at all, so all four are written neutral — 1/1/0/0
            # rather than blank, because hm_read_funct.F:217-218 turns a ZERO
            # scale into 1 and a blank card would be one more thing to reason
            # about.
            #
            # /FUNCT_SMOOTH is the only faithful target, not a nicety: the
            # ISMOOTH flag it sets (NPC(2*NFUNCT+L+1) = 1) makes the /IMP*
            # consumers interpolate with the quintic smoothstep
            # S(u) = u^3(10 - 15u + 6u^2) instead of linearly. On /IMPVEL it
            # ALSO clamps outside the point range — fixvel.F:314/316 goes to
            # VINTER_SMOOTH, which returns the segment end ordinate there
            # (vinter_smooth.F:68-71) — and measured on the same four points a
            # plain /FUNCT drove the probe node BACKWARDS past TEND
            # (10.000 -> 9.296) where /FUNCT_SMOOTH held it at 10.000. The
            # clamp is a property of THAT consumer, not of the flag:
            # /IMPDISP/FGEO dispatches to FINTER2_SMOOTH instead
            # (fixfingeo.F:199), and finter_smooth.F:116-152 has no clamp — it
            # extrapolates the last segment with the same quintic.
            #
            # Consumers outside the documented list
            # (/IMPDISP, /IMPVEL, /IMPACC, /IMPDISP/FGEO, /IMPVEL/FGEO,
            # /IMPVEL/LAGMUL, /PLOAD, /CLOAD, /GRAV, /IMPTEMP, /IMPFLUX --
            # Reference Guide p.2243 comment 3) do not dispatch on ISMOOTH and
            # read the very same points piecewise-linearly, i.e. exactly as
            # they would read a /FUNCT.
            lines += [
                f"/FUNCT_SMOOTH/{lcid}",
                curve.title or f"FUNCT_SMOOTH_{lcid}",
                "#            Ascalex             Fscaley             "
                "Ashiftx             Fshifty",
                f"{_f(1.0)}{_f(1.0)}{_f(0.0)}{_f(0.0)}",
                "#                  X                   Y",
            ]
        else:
            lines += [
                f"/FUNCT/{lcid}",
                curve.title or f"FUNCT_{lcid}",
                "#                  X                   Y",
            ]
        # The #113 guard, on the MAIN emitter at last. It lived on
        # writer/loads.py::_emit_funct (the connector-inline /FUNCT writer) and
        # on handle_define_curve_smooth's builder, and this — the one emitter
        # every *DEFINE_CURVE goes through — wrote curve.pts verbatim, so a
        # deck whose curve reverses direction went out unrepaired and the
        # starter refused the whole model (ERROR 156). Measured carrier:
        # mat_spring.belted-dummy's curve 50, point 26 at x = 0.1125 after
        # 0.1195. A tie keeps its ordinate; a REVERSAL is re-anchored onto the
        # value LS-DYNA itself evaluates there — see _monotonic_abscissae.
        for a, o in _monotonic_abscissae(
                curve.pts, state, f"*DEFINE_CURVE {lcid}"):
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
    for tid, tab in sorted(state.auto_tables.items()):
        # Synthesized multi-dimensional /TABLE/1 (the MAT_224 wiring and the
        # *DEFINE_TABLE_3D flat form). Same CURVE/table_1.cfg
        # FORMAT(radioss110) layout; the Ndim=3 row moves Scale_y's 40-blank
        # run to B(20 chars, cols 41-60) + 20 blanks:
        #   fct_ID(%10d) blank(10) A(%20lg) [B(%20lg)] blank(40|20) Scale_y.
        lines += [
            f"/TABLE/1/{tid}",
            tab.title or f"TABLE_{tid}",
            "#dimension",
            f"{_i(tab.ndim)}",
        ]
        if tab.ndim == 2:
            lines.append("#  fct_ID1                             A                                                    Scale_y1")
            for lcid, coords, sy in tab.rows:
                lines.append(
                    f"{_i(lcid)}{' ' * 10}{_f(coords[0])}{' ' * 40}{_f(sy)}")
        else:
            lines.append("#  fct_ID1                             A                   B                                Scale_y1")
            for lcid, coords, sy in tab.rows:
                lines.append(
                    f"{_i(lcid)}{' ' * 10}{_f(coords[0])}{_f(coords[1])}"
                    f"{' ' * 20}{_f(sy)}")
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

        # LCSS pointing at a *DEFINE_TABLE_3D: LS-DYNA reads a 3-D LCSS as
        # sigma(eps_p, rate, T), and LAW36's rate-function family has no
        # temperature dimension — without this guard the 3-D id would be
        # wired into funct_id as if it were a /FUNCT (dangling reference,
        # starter ERROR 779) with no message.
        if mat.lcss > 0 and mat.lcss in state.define_tables_3d:
            state.warn(
                f"*MAT mid={mat.mid}: LCSS={mat.lcss} is a *DEFINE_TABLE_3D "
                "(temperature-dependent hardening family) — /MAT/LAW36 has "
                "no temperature dimension, so the 3-D form is not "
                "convertible here; falling back to SIGY/ETAN bilinear "
                "hardening. Re-tabulate the working temperature's plane as a "
                "2-D *DEFINE_TABLE to keep the rate family.")
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


# ─────────────────────────────────────────────────────────────────────────────
# Rare materials batch: *MAT_030 / *MAT_SHAPE_MEMORY → /MAT/LAW71
# ─────────────────────────────────────────────────────────────────────────────

#: The LS-DYNA bound on ``*MAT_030`` ALPHA, and the Radioss bound on
#: /MAT/LAW71 ``alpha`` — the SAME number, because the two cells are the same
#: quantity in the same normalisation:
#:
#: LS-DYNA (Vol II R17 p.2-307 Remark 1, quoted verbatim):
#:     alpha = sqrt(2/3)·(-sig_s[AS,-] - sig_s[AS,+]) /
#:                       (-sig_s[AS,-] + sig_s[AS,+]),
#:     -sqrt(2/3) < alpha < sqrt(2/3),
#:     sig_s[AS,-] = (alpha + sqrt(2/3))/(alpha - sqrt(2/3)) · sig_s[AS,+]
#: Radioss (engine/source/materials/mat/mat071/sigeps71.F):
#:     :171  SQDT = SQRT(TWO/THREE)
#:     :245  RSAS = YLD_ASS*(SQDT + ALPHA)
#:     :277  FS   = SV + THREE*ALPHA*P
#: For uniaxial compression ||dev|| = sqrt(2/3)·sig and p = -sig/3, so the
#: Radioss onset is sig_ASS·(sqrt(2/3) + alpha)/(sqrt(2/3) - alpha) — term for
#: term the manual's closed form. ALPHA is therefore copied **1:1**.
#:
#: Note that ALPHA is sqrt(2/3) TIMES the asymmetry ratio, not the ratio: the
#: measured pair (tension 399.45, compression 513.97 for sig_sas 400 / ALPHA
#: 0.1 written verbatim) gives (sig_C - sig_T)/(sig_C + sig_T) = 0.1225 =
#: ALPHA/sqrt(2/3), which is exactly what Remark 1 asks for. Reading that ratio
#: as ALPHA itself is what makes the shrink look right; it is not.
#: Starter-measured with the card written both ways at sig_sas 400 / ALPHA 0.1:
#: alpha = 0.1 gives a compression onset of 513.50 against the LS-DYNA closed
#: form 511.65 (+0.36 %), while alpha = sqrt(2/3)·0.1 gives 490.52 (-4.1 %).
#: dyna2rad's ``SetExpressionValue("sqrt(2/3)*ALPHA", "alpha")``
#: (convertmats.cxx:1931) is a d2r DEFECT and is deliberately not reproduced.
_SMA_ALPHA_MAX = math.sqrt(2.0 / 3.0)


def _resolve_mat_shape_memory(state: ConversionState) -> None:
    """Every *MAT_030 → /MAT/LAW71 guard and warning, in one prepass.

    The two ORDERING guards are hard starter errors, so they are reported with
    the id the starter will raise (hm_read_mat71.F:139-153):
      * ``sig_sas >= sig_fas``  → ERROR 1122
      * ``sig_ssa <= sig_fsa``  → ERROR 1123
    and the range guard at :154-160 → ERROR 1124 for ``alpha > sqrt(2/3)``.

    They are NOT silently repaired: each one means the LS-DYNA card itself
    states an impossible transformation sequence (forward loading must finish
    above where it starts, reverse unloading below), and inventing a number to
    make the starter accept it would hide the deck's real defect.
    """
    for mat in state.mat_shape_memory.values():
        if mat.e <= 0.0:
            state.warn(
                f"*MAT_SHAPE_MEMORY mid={mat.mid} → /MAT/LAW71: E={mat.e:g} "
                "is not positive. hm_read_mat71.F:113-114 reads E and Nu as "
                "mandatory (there is no default), so the austenite branch has "
                "no stiffness — check the card.")
        if mat.sig_ass >= mat.sig_asf:
            state.warn(
                f"*MAT_SHAPE_MEMORY mid={mat.mid}: SIG_ASS={mat.sig_ass:g} is "
                f"not below SIG_ASF={mat.sig_asf:g}. The forward "
                "(austenite→martensite) transformation must FINISH above where "
                "it starts; hm_read_mat71.F:140-146 refuses the card with "
                "ERROR 1122 ('sigma_SAS should be lower than sigma_FAS') and "
                "the starter stops. Both values are written through verbatim — "
                "fix them in the .k file.")
        if mat.sig_sas <= mat.sig_saf:
            state.warn(
                f"*MAT_SHAPE_MEMORY mid={mat.mid}: SIG_SAS={mat.sig_sas:g} is "
                f"not above SIG_SAF={mat.sig_saf:g}. The reverse "
                "(martensite→austenite) transformation must FINISH below where "
                "it starts; hm_read_mat71.F:147-153 refuses the card with "
                "ERROR 1123 and the starter stops. Both values are written "
                "through verbatim — fix them in the .k file.")
        if abs(mat.alpha) >= _SMA_ALPHA_MAX:
            state.warn(
                f"*MAT_SHAPE_MEMORY mid={mat.mid}: ALPHA={mat.alpha:g} is "
                "outside the range the model is defined on — Vol II R17 "
                "p.2-307 Remark 1 bounds it as -sqrt(2/3) < alpha < sqrt(2/3) "
                f"(|ALPHA| < {_SMA_ALPHA_MAX:.7g}), and at |ALPHA| = sqrt(2/3) "
                "the compression onset sig_ASS*(sqrt(2/3)+alpha)/"
                "(sqrt(2/3)-alpha) is a division by zero. The value is written "
                "1:1 (it is the SAME quantity on both sides), so an ALPHA "
                "strictly above the bound is refused by hm_read_mat71.F:"
                "154-160 with ERROR 1124 ('Parameter ALPHA is too high') and "
                "the starter stops. The two cases the starter does NOT catch "
                "are worse: its test is a strict 'ALPHA > SQRT(TWO/THREE)', so "
                "ALPHA = sqrt(2/3) exactly is accepted and then sigeps71.F's "
                "compression loading function |sig|*(sqrt(2/3)-ALPHA) is "
                "identically zero (the material never transforms in "
                "compression), and a NEGATIVE ALPHA has no guard at all and "
                "runs with an inverted asymmetry. Fix it in the .k file.")
        if 0.0 < mat.e < mat.ymrt:
            state.warn(
                f"*MAT_SHAPE_MEMORY mid={mat.mid}: YMRT={mat.ymrt:g} (the "
                f"martensite modulus) is ABOVE E={mat.e:g}. The card is "
                "emitted as stated (E_mart), but a superelastic SMA's "
                "martensite phase is normally the softer one — verify the "
                "column order in the .k file.")


def _emit_mat_law71(mat: MatShapeMemory) -> List[str]:
    """*MAT_SHAPE_MEMORY (*MAT_030) → /MAT/LAW71 (superelastic SMA).

    Layout audited against hm_cfg_files/config/CFG/radioss140/MAT/matl71_71.cfg
    — its only FORMAT block is FORMAT(radioss140), so this is exactly what a
    /BEGIN 2022 deck reads (starter-verified: every field echoed, 0 errors):
      C1: RHO_I(20) [RHO_O(20)]
      C2: E(20) Nu(20) E_mart(20)
      C3: sig_sas(20) sig_fas(20) sig_ssa(20) sig_fsa(20) alpha(20)
      C4: EpsL(20) CAS(20) CSA(20) TSAS(20) TFAS(20)
      C5: TSSA(20) TFSA(20) CP(20) TINI(20)

    RHO_O is left off card 1: the cfg reads columns 21-40 through a CARD_PREREAD
    and defaults RHO_O to RHO_I (hm_read_mat71.F:222), which is what an LS-DYNA
    *MAT_030 (one density) states.

    ``E_mart`` blank/0 is a REAL option, not a missing value: :176-177
    ``IF (EMART /= ZERO) EFLAG = 1`` — with 0 the model runs single-modulus on
    E, which is exactly LS-DYNA's own "YMRT ... defaults to the austenite
    modulus" rule. Measured: post-transformation slope 46000 vs E=50000 with the
    field blank, against 22750 vs E_mart=25000 with it set. dyna2rad NEVER
    reaches this slot — ``CopyValue("YMTR","E_mart")`` (convertmats.cxx:1929)
    misspells the cfg's ``YMRT``, the lookup silently does nothing and every
    converted SMA runs single-modulus (measured: MARTENSITE YOUNG'S MODULUS =
    0.0 for a card stating 50000).

    The eight TEMPERATURE terms stay BLANK. LS-DYNA MAT_030 has no counterpart
    for any of them, and they are NOT inert defaults: TSAS/TFAS/TSSA/TFSA blank
    → 298.0 K and TINI blank → 360.0 K (:168-175), so a non-zero CAS or CSA
    would shift every threshold by ``CAS*(TINI - TSAS)/sqrt(2/3)`` (measured:
    sig_sas 400 → onset 478 MPa with CAS=CSA=1). CP blank → 1e20 pins the
    adiabatic self-heating term at TINI (sigeps71.F:238), which is what makes
    the CAS=CSA=0 choice self-consistent.

    ``EpsL`` is written 1:1 — the engine renormalises it internally
    (sigeps71.F:164 ``EPSL = UPARAM(11)/(SQRT(TWO_THIRD)+ALPHA)``), so the card
    cell IS the uniaxial TENSILE residual strain, exactly LS-DYNA's
    "recoverable strain or maximum residual strain" (Vol II R17 p.2-306).
    Measured: EpsL 0.05 → 0.05 in tension, 0.0391 in compression at alpha 0.1.
    """
    return [
        f"/MAT/LAW71/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu              E_mart",
        f"{_f(mat.e)}{_f(mat.nu)}{_f(mat.ymrt)}",
        "#            sig_sas             sig_fas             sig_ssa"
        "             sig_fsa               alpha",
        f"{_f(mat.sig_ass)}{_f(mat.sig_asf)}{_f(mat.sig_sas)}"
        f"{_f(mat.sig_saf)}{_f(mat.alpha)}",
        "#               EpsL                 CAS                 CSA"
        "                TSAS                TFAS",
        f"{_f(mat.epsl)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#               TSSA                TFSA                  CP"
        "                TINI",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# R14 triage batch, round 1: *MAT_004 / *MAT_270 → /MAT/LAW106
# ─────────────────────────────────────────────────────────────────────────────

#: The yield stress written for a THERMO-ELASTIC card. Vol II R17 p.2-177
#: Remark 2: *"If a thermo-elastic material is considered, do not define SIGY
#: and ETAN"* — so ``SIGY = 0`` means "never yields", not "yields at zero".
#: ``hm_read_mat106.F90``'s default block substitutes ``infinity`` for a blank
#: ``epsmax`` and ``sigmax`` but NOT for ``MAT_SIGY``, so a copied 0 would make
#: the material perfectly plastic at zero stress. 1e20 is the deck's own idiom
#: — ``thermal-stress.k`` states exactly that in its own ``SIGY1..SIGY6``.
_LAW106_NO_YIELD = 1.0e20


def _interp_table(xs: List[float], ys: List[float], x: float) -> float:
    """Piecewise-linear ``y(x)`` on an increasing ``xs``, clamped at both ends.

    Radioss clamps nothing — it EXTRAPOLATES a ``/FUNCT`` past its last point,
    where LS-DYNA *"will terminate if a material temperature falls outside the
    range specified in the input"* (Vol II R17 p.2-177 Remark 2). That
    difference is NAMED in the per-card warning rather than papered over; this
    helper is only used to read the card AT the reference temperature, which
    is inside the range by construction.
    """
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            span = xs[i] - xs[i - 1]
            if span <= 0.0:
                return ys[i]
            f = (x - xs[i - 1]) / span
            return ys[i - 1] + f * (ys[i] - ys[i - 1])
    return ys[-1]


def _law106_reference_temperature(state: ConversionState,
                                  xs: List[float]) -> Tuple[float, str]:
    """The temperature at which the card's scalars are frozen, and WHY.

    LAW106 carries ``E(T)``, ``nu(T)`` and ``alpha(T)`` as functions, so the
    reference temperature is only a NORMALISATION for those three — the
    emitted ``E·f(T)`` is the deck's own ``E(T)`` at every temperature whatever
    reference is chosen. Where it really decides something is the yield stress
    and the hardening modulus, which LAW106 can only hold as CONSTANTS.

    The deck's own model-wide temperature at t = 0 is therefore the right
    choice when it states one and it lies inside the stated table: that is the
    state the structure starts from, and on the five corpus decks whose
    properties are constant it changes nothing at all. Otherwise the table's
    FIRST point is used — never an average, never a mid-range value, both of
    which would be invented.
    """
    from .thermal import _global_initial_temperature
    t0 = _global_initial_temperature(state)
    if t0 is not None and xs and xs[0] <= t0 <= xs[-1]:
        return t0, (f"the deck's own model-wide temperature at t = 0 ({t0:g}), "
                    "which lies inside the stated range")
    if t0 is not None and xs:
        return xs[0], (
            f"the table's first point ({xs[0]:g}); the deck's t = 0 "
            f"temperature {t0:g} lies OUTSIDE the stated range "
            f"[{xs[0]:g}, {xs[-1]:g}]")
    return ((xs[0] if xs else 0.0),
            "the table's first point (the deck states no model-wide "
            "temperature at t = 0)")


def _law106_thermal_rho_cp(state: ConversionState, mid: int) -> float:
    """``RHO_Cp`` for the card's line 6, from the deck's own ``*MAT_THERMAL_*``.

    A ``/HEAT/MAT`` OVERWRITES ``MAT_PARAM%THERM%RHOCP``
    (``hm_read_therm.F:244``), and this batch emits one for every LAW106
    material, so this cell is informational on a deck that has a thermal
    material and the only capacity the law has on a deck that does not.
    Reading it from the same TRO·HC the ``/HEAT/MAT`` uses keeps the two lines
    saying the same thing.
    """
    from .thermal import _thermal_material_for_part
    for pid, part in sorted(state.parts.items()):
        if part.mid != mid:
            continue
        tm = _thermal_material_for_part(state, pid)
        if tm is None:
            continue
        rho = float(getattr(tm, "tro", 0.0) or 0.0)
        hc = float(getattr(tm, "hc", 0.0) or 0.0)
        if rho > 0.0 and hc > 0.0:
            return rho * hc
    return 0.0


def _law106_curve_points(state: ConversionState,
                         lcid: int) -> Optional[List[Tuple[float, float]]]:
    """A ``*DEFINE_CURVE``'s (x, y) points, ready to use.

    ``Curve.pts`` is ALREADY scaled: ``handle_define_curve`` stores
    ``((x + OFFA)·SFA, (y + OFFO)·SFO)`` and keeps ``sfa``/``sfo``/``offa``/
    ``offo`` beside it only as a record of the source card. Re-applying them
    here would square the factor — MEASURED on ``05_1_welding_solid.k``, whose
    ``LCAT`` carries ``SFO = 1e-6`` with ordinates 17 … 22: the doubly-scaled
    ``/FUNCT`` came out at ``1.7e-11`` instead of the correct ``1.7e-5``, a
    factor 1e6 on the thermal expansion coefficient, at zero diagnostics.
    """
    curve = state.curves.get(lcid)
    if curve is None or len(curve.pts) < 2:
        return None
    return list(curve.pts)


def _law106_normalised_function(state: ConversionState, mid: int, tag: str,
                                pts: List[Tuple[float, float]],
                                ref: float) -> int:
    """Register a ``/FUNCT`` of ``(T, y(T)/y_ref)`` and return its id.

    ``hm_read_mat106.F90:250-263`` copies the three tables with
    ``fscale(1:2) = e`` and ``fscale(3) = nu``, so the function the card names
    is a MULTIPLIER on the scalar beside it, not the quantity itself.
    """
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, f"Auto_law106_{tag}_mat{mid}",
                    [(x, y / ref) for x, y in pts])
    state.curve_order.append(fid)
    return fid


def _law106_alpha_function(state: ConversionState, mid: int,
                           pts: List[Tuple[float, float]]) -> int:
    """Register the ``/THERM_STRESS/MAT`` ``alpha(T)`` function, 1:1.

    **No conversion factor, and that is a derivation, not an assumption.**
    Vol II R17 ``*MAT_004`` Remark 1: *"The coefficient of thermal expansion is
    defined as the INSTANTANEOUS value"*, i.e. ``d(eps_T) = alpha(T) dT``.
    Radioss is the same form, incremental: ``ETH = alpha(T)·Fscale·(T_n −
    T_{n−1})`` (``mmain.F90:770-786`` for solids, ``thermexpc.F:172-174`` for
    shells). Two term-for-term identical closed forms need no factor (#128,
    where d2r's invented ``sqrt(2/3)`` on ``*MAT_030`` ALPHA was the defect).
    """
    fid = state.next_curve_id()
    _add_auto_curve(state, fid, f"Auto_law106_alpha_mat{mid}", list(pts))
    state.curve_order.append(fid)
    return fid


def _law106_spread(name: str, xs: List[float],
                   ys: List[float]) -> Optional[str]:
    """``"SIGY 435 … 1 over T = 273 … 10000 (factor 435)"`` — or ``None`` when
    the quantity is constant over the stated range and nothing is lost."""
    lo, hi = min(ys), max(ys)
    if hi - lo <= 1e-12 * max(abs(hi), 1.0):
        return None
    factor = (f"factor {hi / lo:g}" if lo > 0.0 else
              f"down to {lo:g}, so no finite ratio")
    return (f"{name} {ys[0]:g} … {ys[-1]:g} over T = {xs[0]:g} … {xs[-1]:g} "
            f"({factor})")


def _resolve_mat_law106(state: ConversionState) -> None:
    """``*MAT_004`` and ``*MAT_270`` → ``state.mat_law106`` (+ the
    ``/THERM_STRESS/MAT`` their expansion coefficient needs).

    **Why LAW106 and nothing else.** The complete MAT cfg availability map at
    ``/BEGIN 2022`` (the union of ``radioss41 … radioss2022``) leaves exactly
    one law that carries ``E(T)`` and ``nu(T)`` as plain functions of
    temperature on an ordinary elasto-plastic backbone. ``/MAT/LAW129``
    (``func_young``/``func_nu``/``func_yld``/``func_alpha``) is the perfect
    target and first appears in ``radioss2025``; ``/MAT/LAW80`` has a Young
    function but is the hot-stamping boron-steel law and demands the whole
    austenite/ferrite/bainite/martensite kinetics; ``/MAT/LAW121``'s
    ``Fct_YOUN`` is a function of STRAIN RATE, not temperature; LAW2/4/49/103/
    104/109/110 carry a melting temperature for the FLOW STRESS only.

    **What is carried exactly.** ``E(T)`` and ``nu(T)`` become ``/FUNCT``
    multipliers on the scalars beside them (``fct_ID1 = fct_ID2`` for E,
    ``fct_ID3`` for nu — ``sigeps106.F90:231-240`` picks table(2) only while
    the element is COOLING, so leaving it 0 would use the unscaled ``E`` on
    every cooling step), and ``alpha(T)`` becomes the ``/THERM_STRESS/MAT``
    function 1:1. MEASURED that ``E(T)`` is CONSUMED, not merely echoed: two
    one-brick coupons in confined compression, identical but for the card-6
    ``Tr`` cell, gave ``sigma_zz`` 32.2609 at ``f(T) = 1`` and 11.5218 at
    ``f(T) = 0.357143`` — a ratio of 0.357143, exactly ``f(T)`` — with
    ``sigma_xx/sigma_zz = nu/(1-nu) = 0.428571`` in both.

    **What is lost, and it is named per card.** LAW106's yield temperature
    dependence is the Johnson-Cook power law ``1 − ((T−Tref)/(Tmelt−Tref))^m``
    (``sigeps106.F90:306-310``), not a table, so ``SIGY(T)`` and ``ETAN(T)``
    are frozen at the reference temperature. Fitting ``m`` to the welding
    decks' 273→493 pair (435→100 MPa) predicts 63.2 MPa at 1273 K against a
    stated 20 — 3.2x wrong — so nothing is fitted (#124). ``Tmelt`` is left
    BLANK, which ``hm_read_mat106.F90:150`` turns into infinity and which makes
    ``thsoft`` identically 1, so ``A`` means exactly ``sigma_y(T_ref)`` rather
    than a value the engine then knocks down.

    **Version-gated dead cells**, at ``/BEGIN 2022`` and measured on a starter
    probe: the emitted card is the ``radioss2020/MAT/mat_law106.cfg``
    ``FORMAT(radioss2019)`` layout, whose cells
    ``MAT_PC``/``MAT_TMAX``/``MLAW106_COEF``/``MLAW106_TC`` are NOT what the
    current reader asks for (``MAT_FCUT``, ``MLAW106_VP``, ``MLAW106_CJC``,
    ``MLAW106_DEPS0``, ``MLAW106_ETA``, ``MLAW106_T0``). ``Pmin``, ``Tmax``,
    the Taylor-Quinney ``eta`` (defaults to 1), ``T0`` (defaults to ``Tref``),
    the Johnson-Cook rate coefficient ``C``, ``deps0`` and ``Fcut`` are
    therefore unreachable — lost BY VERSION, not by mapping. ``Nmax``, ``Tol``,
    ``m``, ``Tmelt`` and ``Tr`` sit at identical columns in both layouts, so
    writing the 2026 layout instead would only add ``WARNING 100213/100214``
    and drop the same cells (#119 case (a)); at ``/BEGIN 2026`` the card must
    change.
    """
    if not (state.mat_ep_thermal or state.mat_cwm):
        return
    for mid in sorted(state.mat_ep_thermal):
        _resolve_one_mat004(state, state.mat_ep_thermal[mid])
    for mid in sorted(state.mat_cwm):
        _resolve_one_mat270(state, state.mat_cwm[mid])
    _resolve_law106_shells(state)


def _law106_shell_pids(state: ConversionState,
                       mid: int) -> Tuple[List[int], List[int]]:
    """The parts on material ``mid``, split into SHELL and everything else.

    A ``*ELEMENT_TSHELL`` is deliberately NOT a shell here: k2rad writes thick
    shells as ``/BRICK``, so they take the SOLID engine path
    (``mmain.F90``), where the expansion is applied to the strain increment
    before the law dispatch and LAW106 was measured exact.
    """
    shell_pids = {e.pid for e in state.shell_elems}
    shells, others = [], []
    for pid, part in sorted(state.parts.items()):
        if part.mid != mid:
            continue
        if pid in shell_pids or part.secid in state.sec_shells:
            shells.append(pid)
        else:
            others.append(pid)
    return shells, others


def _resolve_law106_shells(state: ConversionState) -> None:
    """A ``/MAT/LAW106`` SHELL part cannot expand — restate it as ``/MAT/LAW36``.

    **The mechanism, from the engine source.** ``cmain3.F:348`` runs
    ``THERMEXPC`` AFTER ``MULAWC`` at ``:320``, and all THERMEXPC does on an
    ordinary ``/PROP/SHELL`` (``IGTYP = 1``, so ``IORTH_LAY = 0`` and
    ``IORTH = 0``) is SUBTRACT the thermal stress ``P = (A11 + A12)*eth`` from
    the stress the law just produced (``thermexpc.F:283-300``). That works only
    for a law that carries its stress forward: ``sigeps36c.F:276`` is
    ``SIGNXX = SIGOXX + A1*DEPSXX + A2*DEPSYY``, so LAW36 reads back exactly
    what THERMEXPC left. ``sigeps106c.F90:297-298`` is
    ``signxx = aii*(epsxx − eplaxx) + aij*(epsyy − eplayy)`` — a TOTAL-strain
    rebuild that never reads ``sigoxx`` for the normal components — so the
    subtraction is DISCARDED on the very next cycle and the shell never
    expands. SOLIDS are unaffected and are left alone: there the expansion goes
    into the strain increment BEFORE the law dispatch, and the LAW106 solid
    coupon was measured correct.

    **MEASURED**, four controlled coupons that differ ONLY in the element
    family and the law — same 10 mm edge, same ``*BOUNDARY_TEMPERATURE_SET``
    20 -> 120 K driver, same ``alpha = 1.2e-5``, ``NIP = 3`` on the shells —
    against the closed form ``alpha*dT*L = 1.2e-2 mm``, all four at 0 ERROR and
    NORMAL TERMINATION:

      ================================================  =============  =========
      coupon                                            free edge      vs 1.2e-2
      ================================================  =============  =========
      ``*MAT_004`` -> /MAT/LAW106, SOLID                1.2000000e-02  +0.000 %
      ``*MAT_004`` -> /MAT/LAW106, SHELL                0.0000000e+00  **-100 %**
      ``*MAT_004`` -> the LAW36 restatement, SHELL      1.2000000e-02  +0.000 %
      ``*MAT_024`` + expansion -> /MAT/LAW36, SHELL     1.2000000e-02  +0.000 %
      ================================================  =============  =========

    (Displacements to the anim file's own printed precision.) The restated
    shell and the ``*MAT_024`` control are not merely close, they are the SAME
    RUN to every printed digit of the T01: internal energy 6.219282e-02,
    external work 2.180456e-04, last time step 1.437983e-06 in both. The
    kept-LAW106 shell reads internal energy -4.759515e-05 instead — 1307x
    smaller and of the wrong sign — while its starter echoes THERMAL MATERIAL
    EXPANSION and NIP 3 identically. The emitted cards are correct; the loss is
    in the engine path, so no card change can reach it.

    **What the restatement costs, and it is named per card.** LAW36 carries no
    temperature dependence at all, so ``E(T)``, ``nu(T)`` and ``sigma_y(T)``
    are frozen at the reference temperature the LAW106 record already resolved.
    The warning prints each table's own measured spread, so a card whose E is
    flat (``tempcyl.vari``, ``ex_20``, ``main_steel_frame`` — all three state a
    CONSTANT E and nu) loses NOTHING, and one that is not (``05_2``'s steel,
    ``E`` 210000 -> 1000) says by how much.

    **Scope.** Only a material whose parts are ALL shells, and only when it
    actually carries a ``/THERM_STRESS/MAT`` — with no expansion coefficient
    there is nothing to rescue and LAW106's ``E(T)`` is strictly better. A
    material shared between shell and solid parts keeps LAW106 and is WARNED
    by name, because restating it would take the T-dependence away from solids
    that expand correctly as they are. ``--no-law106-shell-restate`` keeps
    LAW106 everywhere.
    """
    if not state.mat_law106:
        return
    from .thermal import _has_initial_state
    for mid in sorted(state.mat_law106):
        rec = state.mat_law106[mid]
        shells, others = _law106_shell_pids(state, mid)
        if not shells:
            continue
        if mid not in state.therm_stress_cards:
            # No alpha at all: nothing to rescue, and LAW36 would only throw
            # E(T) away. Silent by design — this is the correct outcome.
            continue
        if others:
            state.warn(
                f"{rec.source} {mid} -> /MAT/LAW106 is shared between SHELL "
                f"part(s) {shells} and non-shell part(s) {others}, and a "
                "/MAT/LAW106 SHELL DOES NOT THERMALLY EXPAND AT ALL. "
                "cmain3.F:348 runs THERMEXPC after MULAWC at :320 and all it "
                "does on a /PROP/SHELL is SUBTRACT the thermal stress from the "
                "stress the law just produced (thermexpc.F:283-300), while "
                "sigeps106c.F90:297-298 rebuilds signxx/signyy from the TOTAL "
                "strain (aii*(epsxx-eplaxx) + aij*(epsyy-eplayy)) and never "
                "reads sigoxx — so the subtraction is discarded on the next "
                "cycle. MEASURED on four controlled coupons that differ ONLY "
                "in the element family and the law (10 mm edge, "
                "*BOUNDARY_TEMPERATURE_SET 20 -> 120 K, alpha 1.2e-5, NIP 3, "
                "closed form 1.2e-2 mm): the LAW106 SHELL moves 0.0000000e+00 "
                "(-100 %) where the LAW106 SOLID moves 1.2000000e-02 "
                "(+0.000 %). k2rad restates a SHELL-ONLY material as "
                "/MAT/LAW36, which reproduces the *MAT_024 control run to "
                "EVERY printed T01 digit — but this "
                "one also carries solids, which expand correctly under LAW106 "
                "and would LOSE E(T) in the restatement, so the law is left "
                "alone and the shell parts get NO expansion. Give the shells "
                "their own *MAT_ELASTIC_PLASTIC_THERMAL / *MAT_CWM id if the "
                "expansion on them matters.")
            continue
        if not state.options.law106_shell_restate:
            state.warn(
                f"{rec.source} {mid} -> /MAT/LAW106 on SHELL part(s) {shells}: "
                "--no-law106-shell-restate was passed, so the law is KEPT and "
                "these parts get NO THERMAL EXPANSION AT ALL — "
                "sigeps106c.F90:297-298 rebuilds the stress from the total "
                "strain, discarding what THERMEXPC (cmain3.F:348, after MULAWC "
                "at :320) subtracts. MEASURED: the free edge does not move at "
                "all (0.0000000e+00 against a closed "
                "form on a controlled coupon. E(T) and nu(T) are carried "
                "exactly; the expansion is not carried at all.")
            continue
        if _has_initial_state(state, set(shells)):
            # The #127 mixed-deck rule, exactly as _restate_law1_shells states
            # it: an /INISHE record's station count is cross-checked against
            # the /PROP/SHELL N, and LAW106 and LAW36 need not agree on it.
            state.warn(
                f"{rec.source} {mid} -> /MAT/LAW106 on SHELL part(s) {shells} "
                "would be restated as /MAT/LAW36 so the parts can expand at "
                "all, but they also carry *INITIAL_STRESS_SHELL / "
                "*INITIAL_STRAIN_SHELL records whose station count is "
                "cross-checked against the through-thickness point count "
                "(ERROR 26 + ERROR 1904). The law is LEFT AS LAW106 and the "
                "thermal expansion on these parts is INERT (measured "
                "0.0000000e+00 against a closed-form 1.2e-2 mm on a controlled "
                "coupon). Drop the initial state, "
                "or give these parts their own material, if the expansion "
                "matters.")
            continue
        _restate_law106_shell(state, rec, shells)


def _restate_law106_shell(state: ConversionState, rec: MatLaw106,
                          shells: List[int]) -> None:
    """Swap one shell-only ``/MAT/LAW106`` for the ``/MAT/LAW36`` that can
    actually expand, and say exactly what the swap froze."""
    from .thermal import _FAR_YIELD_OVER_E
    thermo_elastic = rec.a >= _LAW106_NO_YIELD
    if thermo_elastic:
        sigy = _FAR_YIELD_OVER_E * rec.e
        pts = [(0.0, sigy), (1.0, sigy)]
        yield_note = (f"a flat far-yield curve at {sigy:g} (= 1000 x E, a "
                      "plastic strain of 1000 — the law never leaves its "
                      "elastic branch), because the source card states no "
                      "yield")
    else:
        sigy = rec.a
        pts = [(0.0, sigy), (1.0, sigy + rec.b)]
        yield_note = (
            f"a two-point yield curve ({sigy:g} at eps_p = 0, "
            f"{sigy + rec.b:g} at eps_p = 1), i.e. the SAME yield "
            f"sigma_y(T_ref) = {sigy:g} and the SAME plastic modulus "
            f"B = {rec.b:g} the /MAT/LAW106 card carried")
    if sigy <= 0.0:
        state.warn(
            f"{rec.source} {rec.mid} -> /MAT/LAW106 on SHELL part(s) {shells} "
            f"cannot be restated as /MAT/LAW36: the yield at the reference "
            f"temperature is {sigy:g}, and /MAT/LAW36 needs a positive one. "
            "The law is LEFT AS LAW106 and its thermal expansion on these "
            "parts is INERT (sigeps106c.F90:297-298 rebuilds the stress from "
            "the total strain, discarding what cmain3.F:348's THERMEXPC "
            "subtracts — measured 0.0000000e+00 against a closed-form "
            "1.2e-2 mm on a controlled coupon).")
        return
    fid = state.next_curve_id()
    state.curves[fid] = Curve(
        lcid=fid, title=f"Auto_law106_shell_yield_mat{rec.mid}",
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0, pts=pts)
    state.curve_order.append(fid)
    del state.mat_law106[rec.mid]
    state.law106_shells_restated.add(rec.mid)
    state.mat_plas_tab[rec.mid] = MatPlasTAB(
        mid=rec.mid, title=rec.title, rho=rec.rho, E=rec.e, nu=rec.nu,
        sigy=sigy, etan=0.0, fail=0.0, lcss=0, C=0.0, P=0.0, funct_id=fid)
    frozen = ", ".join(s for s in state.law106_spreads.get(rec.mid, [])
                       if s) or "nothing — every table on the card is CONSTANT"
    state.warn(
        f"{rec.source} {rec.mid} is on SHELL part(s) {shells} only, so it is "
        f"RESTATED as /MAT/LAW36 with {yield_note}. WHY: a /MAT/LAW106 SHELL "
        "DOES NOT THERMALLY EXPAND AT ALL. cmain3.F:348 runs THERMEXPC after "
        "MULAWC at :320, and on a /PROP/SHELL all THERMEXPC does is SUBTRACT "
        "the thermal stress from the stress the law just produced "
        "(thermexpc.F:283-300); sigeps106c.F90:297-298 then rebuilds "
        "signxx/signyy from the TOTAL strain "
        "(aii*(epsxx-eplaxx) + aij*(epsyy-eplayy)) without ever reading "
        "sigoxx, so the subtraction is discarded on the next cycle. LAW36 is "
        "incremental (sigeps36c.F:276, SIGNXX = SIGOXX + A1*DEPSXX + "
        "A2*DEPSYY) and reads it back. MEASURED on three controlled coupons "
        "(alpha 1.2e-5, dT 100 K, L 10 mm, NIP 3, closed form 1.2e-2 mm, all "
        "0 ERROR, all NORMAL TERMINATION): LAW106 SHELL 0.0000000e+00 "
        "(-100 %, internal energy -4.759515e-05), the LAW36 restatement "
        "1.2000000e-02 (+0.000 %, internal energy 6.219282e-02), the "
        "*MAT_024 + *MAT_ADD_THERMAL_EXPANSION control 1.2000000e-02 with an "
        "internal energy, external work and last time step IDENTICAL to the "
        "restatement at every printed T01 digit, and LAW106 SOLID "
        "1.2000000e-02 (+0.000 %). "
        f"WHAT IT COSTS: /MAT/LAW36 has no temperature dependence, so "
        f"E = {rec.e:g}, nu = {rec.nu:g} and the yield are FROZEN at the "
        f"reference temperature Tr = {rec.tr:g}. Frozen on this card: "
        f"{frozen}. The alpha(T) /THERM_STRESS/MAT and the /HEAT/MAT are "
        "unchanged and still temperature-dependent. SOLID parts are never "
        "restated (mmain.F90 applies the expansion before the law dispatch, "
        "and the LAW106 solid was measured exact). Pass "
        "--no-law106-shell-restate (convert(law106_shell_restate=False)) to "
        "keep /MAT/LAW106 and its E(T) at the price of zero expansion.")


def _law106_register(state: ConversionState, rec: MatLaw106,
                     alpha_pts: Optional[List[Tuple[float, float]]]) -> None:
    """Store the resolved card and, when the source states one, its
    ``alpha(T)`` → ``/THERM_STRESS/MAT``.

    ``state.therm_stress_cards`` is what ``writer/thermal.py::
    _resolve_heat_materials`` reads to decide which materials get a
    ``/HEAT/MAT`` — and the pair is MANDATORY (``ERROR 1129``,
    ``hm_read_therm_stress.F90:130-132``), so the two must be filled together
    or not at all.
    """
    state.mat_law106[rec.mid] = rec
    if alpha_pts is None:
        return
    if rec.mid in state.therm_stress_cards:
        state.warn(
            f"{rec.source} {rec.mid}: a *MAT_ADD_THERMAL_EXPANSION already "
            "claimed this material's /THERM_STRESS/MAT. /THERM_STRESS is keyed "
            "on the MATERIAL id and Radioss allows ONE per material, so the "
            "*MAT_ADD_THERMAL_EXPANSION card WINS and this card's own "
            "temperature-dependent expansion coefficient is DROPPED. Delete "
            "one of the two if that is not what the deck means.")
        return
    fid = _law106_alpha_function(state, rec.mid, alpha_pts)
    state.therm_stress_cards[rec.mid] = (fid, 1.0)


def _law106_plastic_modulus(state: ConversionState, kw: str, mid: int,
                            e_ref: float, etan: float) -> float:
    """``*MAT_004`` ``ETAN`` → the LAW106 ``B`` cell.

    LS-DYNA's ``ETAN`` is the TOTAL-strain tangent modulus while LAW106's
    ``B·eps_p^n`` is the PLASTIC branch, so ``B = E·ETAN/(E − ETAN)`` — the
    same derivation ``_plas_kin_b`` already applies to ``*MAT_003``. **It must
    NOT be applied to ``*MAT_CWM``'s ``LCHR``**, which Vol II R17 p.2-1836
    Remark 2 already states as the hardening modulus of
    ``sigma_Y(T) + beta·H(T)·eps_p``.
    """
    if etan <= 0.0:
        return 0.0
    if etan >= e_ref:
        state.warn(
            f"{kw} {mid}: ETAN = {etan:g} at the reference temperature is not "
            f"below E = {e_ref:g}, so the plastic modulus E·ETAN/(E−ETAN) is "
            "undefined (a tangent modulus at or above the elastic one is not a "
            "physical hardening curve). B = 0 (perfectly plastic) is written "
            "instead; check the card's ETAN row.")
        return 0.0
    return e_ref * etan / (e_ref - etan)


def _resolve_one_mat004(state: ConversionState,
                        mat: MatElasticPlasticThermal) -> None:
    """One ``*MAT_ELASTIC_PLASTIC_THERMAL`` card → its ``/MAT/LAW106``."""
    from ..handlers import _mat004_live_points
    n = _mat004_live_points(mat.t)
    kw = "*MAT_ELASTIC_PLASTIC_THERMAL"
    if n < 2:
        state.warn(
            f"{kw} {mat.mid}: only {n} temperature point(s) can be read from "
            f"T1..T8 = {[f'{v:g}' for v in mat.t]}. Vol II R17 p.2-177 Remark "
            "2 requires at least two, in increasing order — an unused slot is "
            "written 0.0 and the live count is the longest strictly increasing "
            "prefix. The material is SKIPPED and its /PART reports a dangling "
            "material id, which names the deck's real problem.")
        return
    xs = mat.t[:n]
    es = mat.e[:n]
    nus = mat.pr[:n]
    alphas = mat.alpha[:n]
    sigys = mat.sigy[:n]
    etans = mat.etan[:n]
    if mat.rho <= 0.0 and not state.options.zero_density_floor:
        # With the floor ON (the default) the density is substituted by
        # _apply_zero_density_floor, which runs AFTER this resolver, so the
        # emitted card is never the ERROR-683 one this refusal describes. The
        # density is pure inertia for LAW106 — E(T), nu(T), alpha(T) and the
        # yield all come from the temperature table — so the substitution
        # rescues the material without touching its constitutive answer. That
        # is NOT true of /MAT/LAW3, whose refusal one function down stays
        # unconditional: LAW3 derives K0 = rho0 * C^2 from its /EOS, so a
        # floored density would make the bulk modulus (and with it nu and E)
        # numerically meaningless rather than merely massless.
        state.warn(
            f"{kw} {mat.mid}: RO = {mat.rho:g}. /MAT/LAW106 is not on the "
            "starter's zero-density exemption list (hm_read_mat.F90:1575-1583 "
            "exempts only laws 0/20/51/151/108/999), so the card would be "
            "ERROR 683 (DENSITY IS LESS THAN OR EQUAL TO ZERO) and refuse the "
            "whole deck. The material is SKIPPED. (--no-zero-density-floor is "
            "set; with the default floor ON the density would have been "
            "substituted and this material converted.)")
        return
    t_ref, why_ref = _law106_reference_temperature(state, xs)
    e_ref = _interp_table(xs, es, t_ref)
    nu_ref = _interp_table(xs, nus, t_ref)
    if e_ref <= 0.0:
        state.warn(
            f"{kw} {mat.mid}: the Young's modulus at the reference temperature "
            f"{t_ref:g} is {e_ref:g}. /MAT/LAW106 carries E(T) as a FUNCTION "
            "SCALED BY E (hm_read_mat106.F90:262, fscale(1:2) = e), so a zero "
            "or negative scalar makes the whole temperature dependence "
            "identically zero. The material is SKIPPED.")
        return
    fct_e = _law106_normalised_function(
        state, mat.mid, "E", list(zip(xs, es)), e_ref)
    fct_nu = 0
    if nu_ref != 0.0:
        fct_nu = _law106_normalised_function(
            state, mat.mid, "nu", list(zip(xs, nus)), nu_ref)
    # Vol II R17 p.2-177 Remark 2: a thermo-elastic MAT_004 states SIGY = 0.
    thermo_elastic = all(v == 0.0 for v in sigys)
    a = _LAW106_NO_YIELD if thermo_elastic else _interp_table(xs, sigys, t_ref)
    etan_ref = _interp_table(xs, etans, t_ref)
    b = _law106_plastic_modulus(state, kw, mat.mid, e_ref, etan_ref)
    alpha_stated = any(v != 0.0 for v in alphas)
    _law106_register(state, MatLaw106(
        mid=mat.mid, title=mat.title, rho=mat.rho, e=e_ref, nu=nu_ref,
        fct_e=fct_e, fct_nu=fct_nu, a=a, b=b, n=1.0,
        rho_cp=_law106_thermal_rho_cp(state, mat.mid), tr=t_ref, source=kw),
        list(zip(xs, alphas)) if alpha_stated else None)
    _law106_report(state, kw, mat.mid, t_ref, why_ref, fct_e, fct_nu,
                   a, b, thermo_elastic,
                   [_law106_spread("E", xs, es),
                    _law106_spread("nu", xs, nus),
                    _law106_spread("SIGY", xs, sigys),
                    _law106_spread("ETAN", xs, etans)],
                   alpha_stated=alpha_stated,
                   range_lo=xs[0], range_hi=xs[-1])


def _resolve_one_mat270(state: ConversionState, mat: MatCWM) -> None:
    """One ``*MAT_CWM`` card → its ``/MAT/LAW106``.

    Same target family as ``*MAT_004`` with load curves instead of eight-point
    tables — and the field the two do NOT share is the hardening one.
    ``LCHR`` is the PLASTIC hardening modulus ``H(T)`` of Vol II R17 p.2-1838
    Remark 2's ``sigma_Y = sigma_Y(T) + BETA·H(T)·eps_p``, so MAT_004's
    ``E·ETAN/(E−ETAN)`` total-strain conversion must NOT be applied to it.
    What it does need is the ``BETA`` split: the same Remark makes the back
    stress evolve as ``kappa_dot = (1−BETA)·H(T)·eps_dot_p`` and p.2-1836 calls
    ``BETA`` the *"Fraction of isotropic hardening between 0 and 1"*
    (``EQ.0.0`` kinematic, ``EQ.1.0`` isotropic). ``/MAT/LAW106`` is purely
    isotropic, so ``B = BETA·H(T_ref)`` — the isotropic part exactly. Getting
    either half wrong is a silent factor error, and ``BETA = 0`` is the case
    where LS-DYNA has NO isotropic hardening at all.
    """
    kw = "*MAT_CWM"
    if mat.rho <= 0.0:
        state.warn(
            f"{kw} {mat.mid}: RO = {mat.rho:g}, which is starter ERROR 683 for "
            "/MAT/LAW106 (hm_read_mat.F90:1575-1583 exempts only laws "
            "0/20/51/151/108/999). The material is SKIPPED.")
        return
    e_pts = _law106_curve_points(state, mat.lcem)
    if e_pts is None:
        state.warn(
            f"{kw} {mat.mid}: LCEM = {mat.lcem} names no *DEFINE_CURVE with at "
            "least two points in the converted deck, so the temperature-"
            "dependent Young's modulus — the one quantity /MAT/LAW106 carries "
            "exactly — cannot be built. The material is SKIPPED and its /PART "
            "reports a dangling material id.")
        return
    xs = [x for x, _y in e_pts]
    es = [y for _x, y in e_pts]
    t_ref, why_ref = _law106_reference_temperature(state, xs)
    e_ref = _interp_table(xs, es, t_ref)
    if e_ref <= 0.0:
        state.warn(
            f"{kw} {mat.mid}: LCEM gives E = {e_ref:g} at the reference "
            f"temperature {t_ref:g}. /MAT/LAW106 scales its E(T) function by "
            "the E cell (hm_read_mat106.F90:262), so a zero scalar makes the "
            "whole dependence identically zero. The material is SKIPPED.")
        return
    fct_e = _law106_normalised_function(state, mat.mid, "E", e_pts, e_ref)
    nu_pts = _law106_curve_points(state, mat.lcpr)
    nu_ref, fct_nu = 0.0, 0
    if nu_pts is not None:
        nu_ref = _interp_table([x for x, _y in nu_pts],
                               [y for _x, y in nu_pts], t_ref)
        if nu_ref != 0.0:
            fct_nu = _law106_normalised_function(
                state, mat.mid, "nu", nu_pts, nu_ref)
    if nu_ref == 0.0:
        # A zero Poisson ratio is not a neutral default: it changes the bulk
        # modulus from E/(3(1-2nu)) to E/3 and removes the transverse coupling
        # entirely. Every corpus carrier states all five curves, so nothing
        # reaches this today — but a card that omits LCPR (or names a curve
        # this deck does not define) must not get it silently.
        state.warn(
            f"{kw} {mat.mid}: LCPR = {mat.lcpr} resolves to no usable "
            "*DEFINE_CURVE, so the /MAT/LAW106 card is written with "
            "nu = 0 — the card's own default and NOT a neutral one: it makes "
            "the bulk modulus E/3 instead of E/(3(1-2nu)) and removes the "
            "transverse coupling, so a confined or plane-strain response is "
            "wrong by that factor. State LCPR, or a constant Poisson ratio "
            "curve, if that matters.")
    sy_pts = _law106_curve_points(state, mat.lcsy)
    a = (_interp_table([x for x, _y in sy_pts],
                       [y for _x, y in sy_pts], t_ref)
         if sy_pts is not None else _LAW106_NO_YIELD)
    h_pts = _law106_curve_points(state, mat.lchr)
    # LCHR is ALREADY the plastic hardening modulus (Remark 2) — no
    # E·Et/(E−Et) conversion here, unlike *MAT_004's ETAN. What it DOES need is
    # the BETA split: Vol II R17 p.2-1838 Remark 2 gives the effective yield as
    # sigma_Y = sigma_Y(T) + BETA*H(T)*eps_p with a back stress evolving as
    # kappa_dot = (1-BETA)*H(T)*eps_dot_p, and the BETA field itself is
    # "Fraction of isotropic hardening between 0 and 1: EQ.0.0 kinematic,
    # EQ.1.0 isotropic" (p.2-1836). /MAT/LAW106 is purely isotropic, so the
    # ISOTROPIC modulus BETA*H(T) is the only part it can carry — writing H(T)
    # raw would make the card 1/BETA too stiff.
    h_ref = (_interp_table([x for x, _y in h_pts],
                           [y for _x, y in h_pts], t_ref)
             if h_pts is not None else 0.0)
    b = mat.beta * h_ref
    alpha_pts = _law106_curve_points(state, mat.lcat)
    _law106_register(state, MatLaw106(
        mid=mat.mid, title=mat.title, rho=mat.rho, e=e_ref, nu=nu_ref,
        fct_e=fct_e, fct_nu=fct_nu, a=a, b=b, n=1.0,
        rho_cp=_law106_thermal_rho_cp(state, mat.mid), tr=t_ref, source=kw),
        alpha_pts)
    spreads = [_law106_spread("E(LCEM)", xs, es)]
    if nu_pts is not None:
        spreads.append(_law106_spread(
            "nu(LCPR)", [x for x, _y in nu_pts], [y for _x, y in nu_pts]))
    if sy_pts is not None:
        spreads.append(_law106_spread(
            "sigma_y(LCSY)", [x for x, _y in sy_pts],
            [y for _x, y in sy_pts]))
    if h_pts is not None:
        spreads.append(_law106_spread(
            "H(LCHR)", [x for x, _y in h_pts], [y for _x, y in h_pts]))
    _law106_report(state, kw, mat.mid, t_ref, why_ref, fct_e, fct_nu, a, b,
                   sy_pts is None, spreads,
                   alpha_stated=alpha_pts is not None,
                   range_lo=xs[0], range_hi=xs[-1],
                   hardening_note=(
                       "LCHR is ALREADY the PLASTIC hardening modulus (Vol II "
                       "R17 p.2-1838 Remark 2, sigma_Y = sigma_Y(T) + "
                       "BETA*H(T)*eps_p), so the E*Et/(E-Et) derivation "
                       "*MAT_004's total-strain ETAN needs would be a silent "
                       f"factor error here. B = BETA*H(T_ref) = {mat.beta:g}*"
                       f"{h_ref:g} = {b:g}: /MAT/LAW106 is purely isotropic and "
                       "BETA is the ISOTROPIC fraction (p.2-1836), so writing "
                       "H(T_ref) raw would make the card 1/BETA too stiff"))
    _warn_cwm_dropped_cells(state, mat)


def _law106_report(state: ConversionState, kw: str, mid: int, t_ref: float,
                   why_ref: str, fct_e: int, fct_nu: int, a: float, b: float,
                   thermo_elastic: bool, spreads: List[Optional[str]], *,
                   alpha_stated: bool, range_lo: float, range_hi: float,
                   hardening_note: str = "") -> None:
    """The per-card statement of what was carried and what was frozen."""
    lost = [s for s in spreads if s]
    # Kept for _resolve_law106_shells: the shell restatement freezes ALL of
    # them (LAW36 has no temperature dependence at all), and it names the ones
    # this card actually has rather than the abstraction.
    state.law106_spreads[mid] = list(lost)
    frozen = [s for s in lost
              if s.startswith(("SIGY", "ETAN", "sigma_y", "H("))]
    carried = [s for s in lost if s not in frozen]
    state.warn(
        f"{kw} {mid} -> /MAT/LAW106 (the only law available at /BEGIN 2022 "
        "that carries E(T) and nu(T) as plain functions of temperature; "
        "/MAT/LAW129, the exact target, first appears in radioss2025). "
        f"Reference temperature Tr = {t_ref:g}, chosen as {why_ref}. "
        f"E(T) is carried EXACTLY as /FUNCT {fct_e} on both fct_ID1 (heating) "
        "and fct_ID2 (cooling) — sigeps106.F90:231-240 picks the cooling table "
        "only while the element cools, so one function must fill both"
        + (f"; nu(T) as /FUNCT {fct_nu} on fct_ID3" if fct_nu else
           "; nu is a constant (no fct_ID3)")
        + (f". alpha(T) is carried 1:1 on /THERM_STRESS/MAT/{mid} with "
           "Fscale = 1: LS-DYNA's coefficient is the INSTANTANEOUS one "
           "(Vol II R17 *MAT_004 Remark 1) and Radioss's is incremental "
           "(ETH = alpha(T)*(T_n - T_(n-1)), mmain.F90:770-786), two "
           "term-for-term identical forms that need no conversion factor"
           if alpha_stated else
           ". The card states no thermal expansion coefficient, so no "
           "/THERM_STRESS/MAT is written")
        + ((". FROZEN AT Tr, because LAW106's yield temperature dependence is "
            "the Johnson-Cook power law 1 - ((T-Tref)/(Tmelt-Tref))^m "
            "(sigeps106.F90:306-310) and not a table: " + "; ".join(frozen)
            + f". A = {a:g} and B = {b:g} are those values AT Tr; Tmelt is "
              "left BLANK (hm_read_mat106.F90:150 turns that into infinity) so "
              "the power law is identically 1 and A means exactly sigma_y(Tr) "
              "rather than a value the engine then knocks down. NOTHING IS "
              "FITTED: fitting m to the welding decks' 273 -> 493 K pair "
              "predicts 63.2 MPa at 1273 K against a stated 20, a factor 3.2")
           if frozen else
           f". A = {a:g} and B = {b:g} are constant over the whole stated "
           "range, so nothing is lost there")
        + ((". The card is THERMO-ELASTIC (SIGY = 0, which Vol II R17 p.2-177 "
            f"Remark 2 means as 'do not define'), so A = {_LAW106_NO_YIELD:g} "
            "is written: hm_read_mat106.F90 substitutes infinity for a blank "
            "epsmax and sigmax but NOT for MAT_SIGY, and a copied 0 would make "
            "the material perfectly plastic at zero stress")
           if thermo_elastic else "")
        + ((". " + hardening_note) if hardening_note else "")
        + (". Carried without loss: " + "; ".join(carried) if carried else "")
        + ". RANGE: LS-DYNA 'will terminate if a material temperature falls "
          f"outside the range specified in the input' ({range_lo:g} … "
          f"{range_hi:g}); Radioss does NOT terminate — it EXTRAPOLATES the "
          "/FUNCT past its last point, so a run that leaves the table gets a "
          "silently linear-extrapolated modulus instead of a stop. "
          "Version-gated dead cells at /BEGIN 2022 (measured on a starter "
          "probe): Pmin, Tmax, the Taylor-Quinney eta (defaults to 1), T0 "
          "(defaults to Tref), the Johnson-Cook rate coefficient C, deps0 and "
          "Fcut — the 2019 cfg names cells the current reader does not ask "
          "for, so they are lost BY VERSION, not by mapping.")


def _warn_cwm_dropped_cells(state: ConversionState, mat: MatCWM) -> None:
    """The three ``*MAT_CWM`` mechanisms LAW106 has no counterpart for, and the
    four cells that lose NOTHING.

    Named in full because a welding deck's whole point is the residual-stress
    field, and these three are what produce it. The honest statement is that
    the converted deck STARTS and TERMINATES NORMALLY and its residual
    stresses are not validated — presenting a green run as a converted weld
    would be the #122 "legal, accepted, misleading" trap at deck scale.
    """
    losses = []
    if mat.tastart or mat.taend:
        losses.append(
            f"ANNEALING (TASTART={mat.tastart:g}, TAEND={mat.taend:g}): "
            "Vol II R17 p.2-1838 Remark 3 scales the accumulated plastic "
            "strain and the back stress by max[0, min(1, (T-TAend)/"
            "(TAstart-TAend))] before every stress update, i.e. the plastic "
            "strain is RESET through the annealing window. /MAT/LAW106 "
            "accumulates plastic strain monotonically and has no such window. "
            "For a multi-pass weld this is the single largest physics loss")
    if mat.tlstart or mat.tlend or mat.eghost or mat.pghost or mat.aghost:
        losses.append(
            f"GHOST -> LIVE weld-metal deposition (TLSTART={mat.tlstart:g}, "
            f"TLEND={mat.tlend:g}, EGHOST={mat.eghost:g}, "
            f"PGHOST={mat.pghost:g}, AGHOST={mat.aghost:g}): Remark 1 blends "
            "each element's properties by gamma = min(1, max(0, (T_max - "
            "TLstart)/(TLend - TLstart))) from its OWN running maximum "
            "temperature, so an unmelted element carries the quiet (ghost) "
            "moduli. Radioss's nearest machinery is /ACTIV + /SENSOR/TEMP, but "
            "/SENSOR/TEMP triggers on a /GRNOD (read_sensor_temp.F:81-87), so "
            "per-element birth would need one sensor, one group and one /ACTIV "
            "per weld element — and a deactivated solid also stops CONDUCTING "
            "(STHERM multiplies by OFF). Out of scope for this batch")
    if mat.beta != 1.0:
        losses.append(
            f"BETA={mat.beta:g} splits the hardening between isotropic and "
            "KINEMATIC. Vol II R17 p.2-1838 Remark 2 makes the effective yield "
            "sigma_Y = sigma_Y(T) + BETA*H(T)*eps_p with a back stress "
            "kappa_dot = (1-BETA)*H(T)*eps_dot_p, and p.2-1836 calls BETA the "
            "'Fraction of isotropic hardening between 0 and 1' (EQ.0.0 "
            "kinematic, EQ.1.0 isotropic). /MAT/LAW106 is purely isotropic, so "
            f"k2rad writes B = BETA*H(T_ref) — the isotropic part exactly — and "
            f"the KINEMATIC fraction 1-BETA = {1.0 - mat.beta:g} is DROPPED "
            "(no back stress, so no Bauschinger effect on load reversal, which "
            "is what a multi-pass weld is made of)"
            + (". At BETA = 0 LS-DYNA has NO isotropic hardening at all, so "
               "B = 0 and the restated law is perfectly plastic"
               if mat.beta == 0.0 else
               ". Only BETA = 1 is lossless here"))
    if mat.epsini:
        losses.append(
            f"EPSINI={mat.epsini:g} (uniform initial plastic strain) has no "
            "/MAT/LAW106 cell — state it as an *INITIAL_STRESS_* record "
            "instead")
    if losses:
        state.warn(
            f"*MAT_CWM {mat.mid} -> /MAT/LAW106: NOT carried — "
            + "; ".join(losses)
            + ". A welding deck exists to produce a residual-stress field and "
              "these are what produce it, so the converted deck will START and "
              "TERMINATE NORMALLY with the correct temperature-dependent "
              "elasticity and expansion and a residual stress that is NOT "
              "VALIDATED. Do not read a green run as a converted weld.")
    if mat.has_card3 and (mat.t2phase or mat.t1phase or mat.dtemp
                          or mat.postv):
        state.warn(
            f"*MAT_CWM {mat.mid}: card 3 (T2PHASE={mat.t2phase:g}, "
            f"T1PHASE={mat.t1phase:g}, DTEMP={mat.dtemp:g}, "
            f"POSTV={mat.postv}) is POST-PROCESSING ONLY and loses NOTHING "
            "mechanical. Vol II R17 p.2-1839 Remark 4: the phase-change cells "
            "only fill HISTORY VARIABLE 11, an average temperature rate; "
            "Remark 5: POSTV selects extra history variables; DTEMP sub-cycles "
            "the bookkeeping that feeds that same variable. ANOPT = 0 is 'no "
            "modification for thermal expansion' and DOSPOT = 0 leaves "
            "spot-weld thinning inactive — both are the card's own defaults "
            "here.")


def _emit_mat_law106(mat: MatLaw106) -> List[str]:
    """``/MAT/LAW106`` — the ``FORMAT(radioss2019)`` block of
    ``radioss2020/MAT/mat_law106.cfg``, which is what a ``/BEGIN 2022`` deck
    reads.

    ::

        C1: RHO_I(20)
        C2: E(20)  nu(20)  fct_ID1(10) fct_ID2(10) fct_ID3(10)
        C3: A(20)  B(20)   n(20)       epsmax(20)  sigmax(20)
        C4: Pmin(20) ..10.. Nmax(10)   Tol(20)
        C5: ..40.. m(20) Tmelt(20) Tmax(20)
        C6: RHO_Cp(20) Coef(20) Tc(20) Tr(20)

    Cards 4 and 5 are written BLANK on purpose. ``epsmax``/``sigmax`` blank →
    infinity (``hm_read_mat106.F90:145-147``), ``m`` blank → 1 and ``Tmelt``
    blank → infinity (``:150``), which is what makes the Johnson-Cook thermal
    knockdown identically 1 so that ``A`` means ``sigma_y(Tr)`` and nothing
    else. ``Nmax``/``Tol`` blank take the reader's own return-mapping defaults
    (3 or 6 iterations, ``tol = 1e-20``).

    **At /BEGIN 2026 this card must change**: the current reader asks for
    ``MAT_FCUT``, ``MLAW106_VP``, ``MLAW106_NMAX``, ``MLAW106_TOL``,
    ``MLAW106_CJC``, ``MLAW106_DEPS0`` on line 3 and ``MAT_SPHEAT``,
    ``MLAW106_ETA``, ``MLAW106_T0``, ``MLAW106_TR`` on line 5, i.e. the 2026
    layout is ``Fcut VP Nmax Tol C deps0`` at 100 columns on a five-line card.
    Writing that at 2022 raises ``WARNING 100213/100214`` and drops the cells —
    benign, because ``Nmax``, ``Tol``, ``m``, ``Tmelt`` and ``Tr`` sit at
    identical columns in both layouts (#119 case (a), not a field shift) — but
    pointless, so the 2019 layout is what is written.
    """
    return [
        f"/MAT/LAW106/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu   fct_ID1   fct_ID2"
        "   fct_ID3",
        f"{_f(mat.e)}{_f(mat.nu)}{_i(mat.fct_e)}{_i(mat.fct_e)}"
        f"{_i(mat.fct_nu)}",
        "#                  A                   B                   n"
        "              epsmax              sigmax",
        f"{_f(mat.a)}{_f(mat.b)}{_f(mat.n)}{_f(0.0)}{_f(0.0)}",
        "#               Pmin                Nmax                 Tol",
        "",
        "#                                                          m"
        "               Tmelt                Tmax",
        "",
        "#             RHO_Cp                Coef                  Tc"
        "                  Tr",
        f"{_f(mat.rho_cp)}{_f(0.0)}{_f(0.0)}{_f(mat.tr)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# R14 triage batch, round 1: *MAT_010 → /MAT/LAW3 (HYDPLA) + its same-id /EOS
# ─────────────────────────────────────────────────────────────────────────────

def _law3_bulk_from_eos(eos: EosCard, rho0: float) -> Optional[float]:
    """The unstressed bulk modulus ``K0`` the companion ``*EOS_*`` states.

    * ``GRUNEISEN``: ``K0 = rho0·C²``. ``C`` is the intercept of the
      ``us = C + S1·up`` shock Hugoniot, i.e. the BULK sound speed at zero
      compression, so ``rho0·C²`` is the definition of the unstressed bulk
      modulus — two stated cells, no fitted constant.
    * ``POLYNOMIAL``: ``K0 = C1``, the linear term of
      ``p = C0 + C1·mu + C2·mu² + …`` evaluated at ``mu → 0``.

    ``None`` for any other kind: an ideal gas has no unstressed bulk modulus at
    all (``K = gamma·p``, which is zero at zero pressure), so nothing can be
    derived from it.
    """
    if eos.kind == "GRUNEISEN":
        c = float(eos.params.get("c", 0.0))
        if rho0 > 0.0 and c > 0.0:
            return rho0 * c * c
        return None
    if eos.kind == "POLYNOMIAL":
        c1 = float(eos.params.get("c1", 0.0))
        return c1 if c1 > 0.0 else None
    return None


def _law3_consumed_eos_ids(state: ConversionState) -> set:
    """``*EOS_*`` ids emitted BESIDE a ``/MAT/LAW3``.

    ``_make_explosive_and_eos_materials``'s orphan-EOS arm must skip these, or
    it would tell the reader *"the equation of state was NOT emitted"* about
    one this batch writes two blocks further up — a false statement of the
    #129 class, on the three corpus decks that carry the pair.
    """
    return {m.eos_id for m in state.mat_law3.values() if m.eos_id}


def _resolve_mat_law3(state: ConversionState) -> None:
    """``*MAT_010`` → ``state.mat_law3``, deriving the E-nu pair from the
    material's own ``RO`` and its companion EOS's sound speed.

    **Why a derivation is needed at all.** ``*MAT_010`` states a SHEAR modulus
    and nothing else elastic — LS-DYNA takes the pressure from the ``*EOS_*``
    the ``*PART`` binds. ``/MAT/LAW3``'s card is the isotropic pair ``E, nu``,
    and ``hm_read_mat03.F:190`` recovers ``G = E/(2(1+nu))`` from it, so ANY
    (E, nu) with the right ``G`` reproduces the deviatoric response exactly —
    which is what ``m3law.F:60,107-112`` uses, the pressure coming from
    ``eosmain`` (``mmain.F90:805``, ``:1971-1985``, ``sig = s − pnew``).

    **The pair that is chosen, and its one visible consequence.** With
    ``K0 = rho0·C²`` from the EOS,

        nu = (3K0 − 2G) / (2(3K0 + G)),      E = 9·K0·G / (3K0 + G)

    which is the unique pair whose bulk modulus is the EOS's own. That matters
    because ``hm_read_mat03.F:191`` sets ``PM(32) = E/(3(1−2nu))`` for every
    ``INVERS >= 2018`` deck — the material's stored bulk modulus, which the
    ``/INTER/TYPE7`` and ``TYPE20`` contact stiffness reads. Deriving it from
    two stated physical cells makes that number agree with the pressure law
    instead of with an invented Poisson ratio.

    MEASURED cross-check on the corpus: ``taylor1``'s own
    ``*MAT_PLASTIC_KINEMATIC`` twin for the same copper states ``E = 1e5,
    PR = 0.33``, i.e. ``G = 37593.98`` — the deck author's own ``G = 37593`` to
    five figures. The EOS-consistent pair (nu 0.376303, E 103478.736) returns
    ``E/(2(1+nu)) = 37593.000`` exactly and differs from the author's only in
    the bulk (139425.3 vs 98039), which the EOS supplies anyway.

    **``EH`` goes into ``b`` UNCONVERTED.** Vol II R17 p.2-193 Remark 2 states
    the flow law as ``sigma_y = sigma_0 + E_h·eps_p + …``, so ``EH`` is already
    the plastic modulus; the ``E_t E/(E − E_t)`` form on the same page is the
    derivation FROM a tangent. Applying it here would be the silent factor
    error ``*MAT_003``'s ``ETAN`` legitimately needs.
    """
    if not state.mat_ep_hydro:
        return
    kw = "*MAT_ELASTIC_PLASTIC_HYDRO"
    for mid in sorted(state.mat_ep_hydro):
        mat = state.mat_ep_hydro[mid]
        if mat.spall_option:
            state.warn(
                f"{kw}_SPALL {mid}: the _SPALL option adds the "
                f"pressure-hardening pair A1={mat.a1:g}, A2={mat.a2:g} (the "
                "'(a1 + p*a2)*max[p,0]' term of Vol II R17 p.2-193 Remark 2) "
                f"and the spall model selector SPALL={mat.spall:g}. "
                "/MAT/LAW3's yield is a + b*eps_p^n with no pressure term and "
                "no spall selector, so the option cannot be expressed. The "
                "material is REFUSED (its /PART then reports a dangling "
                "material id) rather than converted with the pressure "
                "hardening silently dropped.")
            continue
        if mat.rho <= 0.0:
            # UNCONDITIONAL, unlike the LAW106 twin above: the zero-density
            # floor cannot rescue a LAW3 material, because this law's whole
            # elastic pair is DERIVED from the density — K0 = rho0 * C^2 out
            # of the *EOS_GRUNEISEN (or C1 out of the polynomial), then
            # nu = (3K0-2G)/(2(3K0+G)) and E = 9K0G/(3K0+G). At rho = 1e-24
            # the bulk modulus is numerically zero and nu comes out at the
            # incompressible/negative edge, so the substitution would turn a
            # refused deck into a silently wrong one.
            state.warn(
                f"{kw} {mid}: RO = {mat.rho:g}. /MAT/LAW3 is not on the "
                "starter's zero-density exemption list "
                "(hm_read_mat.F90:1575-1583 exempts only laws "
                "0/20/51/151/108/999), so the card would be ERROR 683 and "
                "refuse the whole deck. The material is SKIPPED. The "
                "zero-density floor does NOT apply here: LAW3 derives its "
                "bulk modulus as K0 = rho0*C^2 from the *EOS_*, so a "
                "substituted density would make E and nu meaningless instead "
                "of merely making the material massless.")
            continue
        if mat.g <= 0.0:
            state.warn(
                f"{kw} {mid}: G = {mat.g:g}. The shear modulus is the card's "
                "only elastic cell and /MAT/LAW3 recovers it as E/(2(1+nu)) "
                "(hm_read_mat03.F:190), so there is nothing to derive an E-nu "
                "pair from. The material is SKIPPED.")
            continue
        if any(v != 0.0 for v in mat.eps) or any(v != 0.0 for v in mat.es):
            state.warn(
                f"{kw} {mid}: the card states a TABULATED yield curve "
                "(EPS1..16 / ES1..16). /MAT/LAW3's yield is the analytic "
                "a + b*eps_p^n and cannot hold an arbitrary 16-point table, "
                "and the law that could (/MAT/LAW36, which is both SPH- and "
                "EOS-declared) is not wired to an /EOS by this converter yet. "
                "The material is REFUSED rather than converted with its "
                "hardening curve replaced by the card-1 constants SIG0/EH, "
                "which would be a different material at 0 starter errors. "
                "Re-state the hardening as SIG0 + EH*eps_p if the table is "
                "close to linear, or convert the part by hand.")
            continue
        eos = state.eos_cards.get(mid)
        if eos is None:
            state.warn(
                f"{kw} {mid}: no *EOS_* of the same id in the converted deck. "
                "*MAT_010 states a SHEAR modulus and no bulk modulus at all — "
                "LS-DYNA takes the pressure from the equation of state the "
                "*PART binds — so without one there is no second elastic "
                "constant to build /MAT/LAW3's E-nu pair from, and inventing "
                "a Poisson ratio would be a fabricated value. The material is "
                "SKIPPED; its /PART reports a dangling material id, which "
                "names the deck's real problem.")
            continue
        bulk = _law3_bulk_from_eos(eos, mat.rho)
        if bulk is None or bulk <= 0.0:
            state.warn(
                f"{kw} {mid}: {eos.label()} states no usable unstressed bulk "
                "modulus (K0 = rho0*C^2 for a Gruneisen EOS, K0 = C1 for a "
                "polynomial one; an ideal gas has none at all, since "
                "K = gamma*p is zero at zero pressure). Without it the E-nu "
                "pair cannot be derived and the material is SKIPPED.")
            continue
        nu = (3.0 * bulk - 2.0 * mat.g) / (2.0 * (3.0 * bulk + mat.g))
        e = 9.0 * bulk * mat.g / (3.0 * bulk + mat.g)
        if not (-1.0 < nu < 0.5) or e <= 0.0:
            state.warn(
                f"{kw} {mid}: the stated G = {mat.g:g} against the EOS's "
                f"K0 = {bulk:g} gives nu = {nu:g}, outside the physical range "
                "(-1, 0.5) that /MAT/LAW3's isotropic pair must lie in. The "
                "material is SKIPPED; check the EOS's sound speed C and the "
                "card's G against each other.")
            continue
        state.mat_law3[mid] = MatLaw3(
            mid=mid, title=mat.title, rho=mat.rho, e=e, nu=nu,
            a=mat.sig0, b=mat.eh, n=1.0, eps_max=mat.fs, sigma_max=0.0,
            # -abs(0.0) is -0.0, which formats as "-0" and reads as a
            # typo; a stated 0 means "no cutoff" and is written as a plain 0
            # for hm_read_mat03.F:182 to turn into -1e20.
            pmin=(-abs(mat.pc) if mat.pc else 0.0),
            eos_id=mid, bulk=bulk)
        _law3_report(state, kw, mat, e, nu, bulk)


def _law3_report(state: ConversionState, kw: str,
                 mat: MatElasticPlasticHydro, e: float, nu: float,
                 bulk: float) -> None:
    """Name the derivation, its consequence and every cell that was dropped."""
    dropped = []
    if mat.charl:
        dropped.append(
            f"CHARL={mat.charl:g} (Vol II R17 p.2-192: the characteristic "
            "element thickness for 2-D deletion, which has no counterpart — "
            "Radioss deletes on the failure criterion, not on thinning)")
    state.warn(
        f"{kw} {mat.mid} -> /MAT/LAW3 (HYDPLA) + the same-id "
        f"/EOS/{state.eos_cards[mat.mid].kind}/{mat.mid}. *MAT_010 states a "
        f"SHEAR modulus G = {mat.g:g} and no bulk modulus (LS-DYNA takes the "
        "pressure from the EOS the *PART binds), while /MAT/LAW3's card is the "
        "isotropic pair E, nu. DERIVED from two stated physical cells — the "
        f"material's RO = {mat.rho:g} and the EOS's sound speed — as "
        f"K0 = rho0*C^2 = {bulk:g}, nu = (3K0-2G)/(2(3K0+G)) = {nu:.6f}, "
        f"E = 9*K0*G/(3K0+G) = {e:.6f}, which returns E/(2(1+nu)) = "
        f"{e / (2.0 * (1.0 + nu)):.6f} = G exactly. Its ONE visible "
        "consequence: hm_read_mat03.F:191 stores PM(32) = E/(3(1-2nu)) for "
        "every INVERS >= 2018 deck, and that is the bulk modulus the "
        "/INTER/TYPE7 and TYPE20 CONTACT STIFFNESS reads — so the contact "
        "stiffness now agrees with the pressure law instead of with an "
        "invented Poisson ratio. The deviatoric response is unaffected either "
        "way (m3law.F:60,107-112 uses G alone; the pressure comes from "
        f"eosmain). a = SIG0 = {mat.sig0:g}; b = EH = {mat.eh:g} is written "
        "UNCONVERTED, because Vol II R17 p.2-193 Remark 2 states the flow law "
        "as sigma_y = sigma_0 + E_h*eps_p, i.e. EH is ALREADY the plastic "
        "hardening modulus and the E_t*E/(E-E_t) form on that page is the "
        "derivation FROM a tangent — applying it here would be a silent factor "
        "error. n = 1 is written; hm_read_mat03.F:187 substitutes 1.0001 for a "
        "stated 1 (it avoids the derivative singularity of eps^1 at eps = 0), "
        f"a 0.05% effect at eps_p = 0.01. Pmin = "
        + f"{(-abs(mat.pc) if mat.pc else 0.0):g} from "
        + ("PC (a stated 0 becomes the reader's own -1e20, "
           "hm_read_mat03.F:182 — no cutoff)" if mat.pc == 0.0 else
           f"PC = {mat.pc:g}")
        + f"; eps_max = {mat.fs:g} from FS"
        + (" (a stated 0 becomes the reader's own 1e20 — no erosion)"
           if mat.fs == 0.0 else " (effective plastic strain at element "
                                 "deletion)")
        + ((". DROPPED: " + "; ".join(dropped)) if dropped else "")
        + ".")


def _emit_mat_law3(mat: MatLaw3, state: ConversionState) -> List[str]:
    """``/MAT/LAW3`` (``/MAT/HYDPLA``) + its same-id ``/EOS``.

    Card layout from ``radioss2020/MAT/matl3_hydpla.cfg``
    ``FORMAT(radioss2018)``::

        C1: RHO_I(20)
        C2: E(20) nu(20)
        C3: a(20) b(20) n(20) eps_max(20) sigma_max(20)
        C4: Pmin(20)

    The ``/EOS`` is emitted immediately after the ``/MAT``, under the SAME id —
    Radioss binds an equation of state to the material of the same id, the way
    ``_emit_mat_law4_hyd_jcook`` already pairs the LAW4 route. It is NOT the
    embedded card-5 form: ``hm_read_mat03.F:152-158`` disables ``EOS_EMBEDDED``
    for every ``INVERS >= 2018`` deck, so an inline polynomial would be read as
    part of no card at all.
    """
    lines = [
        f"/MAT/LAW3/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  nu",
        f"{_f(mat.e)}{_f(mat.nu)}",
        "#                  a                   b                   n"
        "             eps_max           sigma_max",
        f"{_f(mat.a)}{_f(mat.b)}{_f(mat.n)}{_f(mat.eps_max)}"
        f"{_f(mat.sigma_max)}",
        "#               Pmin",
        f"{_f(mat.pmin)}",
        HDR,
    ]
    eos = state.eos_cards.get(mat.eos_id)
    if eos is not None:
        lines += _emit_eos(eos)
    return lines


def _element_count_by_pid(state: ConversionState) -> Dict[int, Dict[str, int]]:
    """``pid -> {family: count}`` over every element family a ``*PART`` can
    hold.

    Written as an explicit family walk, not a union registry: element ids live
    in separate namespaces per type and the point of the count is to tell the
    reader WHAT the refused material was carrying (500 solids reads very
    differently from one). Families with no ``pid`` attribute (SPH cells carry
    one, springs and seatbelts do too) are listed the same way, so a new family
    added later shows up here as a missing arm rather than a silent zero
    (#120).
    """
    out: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    families: Tuple[Tuple[str, List[Any]], ...] = (
        ("solid", state.solid_elems),
        ("shell", state.shell_elems),
        ("tshell", state.tshell_elems),
        ("beam", state.beam_elems),
        ("discrete", state.discrete_elems),
        ("seatbelt", state.seatbelt_elems),
        ("sph", state.sph_elems))
    for fam, elems in families:
        for e in elems:
            pid = getattr(e, "pid", 0)
            if pid:
                out[pid][fam] += 1
    return {pid: dict(fams) for pid, fams in out.items()}


def _warn_refused_materials(state: ConversionState) -> None:
    """Name every REFUSED material with the parts and elements it costs.

    ``handlers._material_refused`` runs while the deck is being parsed, before
    the mesh is read, so it can only record the law and the reason. This pass
    runs once ``state.parts`` and every element list are complete and supplies
    the half a reader actually needs: the starter answers ``ERROR 179`` one
    part at a time and says nothing at all about how much of the model the
    refusal takes with it.

    The parts are NOT dropped. Three starter probes settle why (one brick each,
    ``/BEGIN 2022``): a ``/PART`` with a dangling ``mat_ID`` plus its
    ``/BRICK`` gives 3 errors (``179`` PART→MATERIAL, ``3046`` BRICK vs
    MATERIAL ID 0 TYPE 0, ``61`` INVALID MATERIAL ID FOR BRICK ELEMENT); the
    ``/PART`` removed with its ``/BRICK`` KEPT gives ``ERROR 402`` *"1 PART(S)
    REFERENCED BY ELEMENTS DO(ES) NOT EXIST"* — strictly worse; both removed
    gives 0 ERROR / 0 WARNING. So dropping is only ever right as a PAIR, and
    then only after every other card that names the part (sets, contacts,
    ``/TH``, ``/INIVOL``, ``/RBODY``, ``*DATABASE_HISTORY_*``) has been
    screened too, or the next ``ERROR 402``-class failure just moves one card
    along. That screening is its own item; until it exists a readable
    ``ERROR 179`` naming the law beats a silently smaller model.
    """
    if not state.refused_materials:
        return
    counts = _element_count_by_pid(state)
    for mid in sorted(state.refused_materials):
        seen, what, why = state.refused_materials[mid]
        pids = sorted(pid for pid, p in state.parts.items() if p.mid == mid)
        tally: Dict[str, int] = defaultdict(int)
        for pid in pids:
            for fam, n in counts.get(pid, {}).items():
                tally[fam] += n
        held = (", ".join(f"{n} {fam}" for fam, n in sorted(tally.items()))
                if tally else "no elements")
        state.warn(
            f"*{seen} {mid}: {what} is REFUSED BY NAME — {why}. "
            + (f"/PART(s) {pids} name this material and hold {held}; they are "
               "emitted with a mat_ID no /MAT defines, which the starter "
               "answers with ERROR 179 (MATERIAL ID DOES NOT EXIST) plus "
               "ERROR 3046 / ERROR 61 per element family. The parts are NOT "
               "dropped: measured on one-brick starter probes, removing the "
               "/PART while keeping its elements is ERROR 402 (PART(S) "
               "REFERENCED BY ELEMENTS DO(ES) NOT EXIST) — strictly worse — "
               "and removing both only moves the dangling reference to "
               "whatever set, contact, /TH or /RBODY still names the part. A "
               "readable ERROR 179 naming the law beats a silently smaller "
               "model."
               if pids else
               "No /PART names this material, so nothing in the emitted deck "
               "references it and the refusal costs the model nothing.")
            )


# ─────────────────────────────────────────────────────────────────────────────
# R14 triage batch, round 1: the /MAT/LAW5 `Bunreacted` cell
# ─────────────────────────────────────────────────────────────────────────────

def _ammg_member_mids(state: ConversionState) -> Set[int]:
    """Material ids reached by an ``*ALE_MULTI-MATERIAL_GROUP`` entry.

    The ONE predicate for "is this material a LAW51 phase?", read by the
    ``Bunreacted`` derivation and by the phase list itself (there is no third
    reader: the submaterial RESTATEMENT was removed in ``ff7a82d`` — see
    :func:`_resolve_ale_submaterials` (b)). If the two disagreed, a material
    would be derived for a card it never lands on, or land on one with no
    derivation.
    """
    from .blast_ale import _part_pids
    mids: Set[int] = set()
    for mmg in state.ale_mmgs:
        for sid, idtype in mmg.entries:
            for pid in _part_pids(state, sid, idtype == 1):
                part = state.parts.get(pid)
                if part is not None and part.mid:
                    mids.add(part.mid)
    return mids


def _jwl_unreacted_bulk(jwl: EosJwl) -> float:
    """``K_s(V = 1)`` — the slope of the JWL's PRINCIPAL ISENTROPE at the
    unreacted density.

    The principal isentrope is the JWL's own reference curve for the
    condensed (unreacted) solid, ``p_s(V) = A·e^{-R1·V} + B·e^{-R2·V}``, with
    the energy term ``omega·E0/V`` added at the stated ``E0``. Its bulk modulus
    ``K = -V dp_s/dV`` evaluated at ``V = 1`` is

        K_s(1) = A·R1·e^{-R1} + B·R2·e^{-R2} + omega·E0

    Every term comes from a cell the ``*EOS_JWL`` states — nothing is fitted
    and nothing is looked up. On ``underwater_C``'s TNT (A 371000, B 3230,
    R1 4.15, R2 0.95, omega 0.3, E0 4300) that is
    24271.684 + 1186.715 + 1290.000 = **26748.4 MPa**.

    **This is NOT the tangent modulus of the full EOS the solver evaluates**,
    and the difference is named rather than hidden: ``jwl51.F:191``
    (``P0 = B1*(1 - W1/R1M)*ER1M + B2*(1 - W1/R2M)*ER2M``) and
    ``m5law.F:126-129`` (``WDR1V = A - A*W/(R1*DF)``) both carry the
    ``(1 - omega/(R_i·V))`` factors the principal isentrope does not, so
    differentiating THAT gives ``_jwl_full_eos_bulk`` — 23801 on the same card,
    11 % lower. Both are legitimate proxies for the unreacted solid's
    stiffness; a three-value sweep spanning 37x on ``underwater_C`` moved the
    last time step 0.14 %, the internal energy 1.1 % and the kinetic energy
    0.19 %, so the choice does not decide the answer. The warning prints both.
    """
    return (jwl.a * jwl.r1 * math.exp(-jwl.r1)
            + jwl.b * jwl.r2 * math.exp(-jwl.r2)
            + jwl.omega * jwl.e0)


def _jwl_full_eos_bulk(jwl: EosJwl) -> float:
    """``-V dp/dV`` at ``V = 1`` for the FULL JWL the solver evaluates.

    ``p(V, E0) = A(1 - omega/(R1·V))e^{-R1·V} + B(1 - omega/(R2·V))e^{-R2·V}
    + omega·E0/V`` — the form ``jwl51.F:191`` and ``m5law.F:126-129`` build —
    differentiates to

        K(1) = A·e^{-R1}(R1 - omega/R1 - omega)
             + B·e^{-R2}(R2 - omega/R2 - omega) + omega·E0

    Printed beside the value actually written so a reader can see the size of
    the modelling choice (11 % on ``underwater_C``'s TNT: 23801 against
    26748.4). Not used as the substitution itself — which is why a degenerate
    ``R1``/``R2`` of 0 (where the ``omega/R_i`` term is undefined) drops that
    exponential's contribution instead of raising: this number only ever
    appears inside a sentence.
    """
    out = jwl.omega * jwl.e0
    for coef, r in ((jwl.a, jwl.r1), (jwl.b, jwl.r2)):
        if r:
            out += coef * math.exp(-r) * (r - jwl.omega / r - jwl.omega)
    return out


def _resolve_he_bunreacted(state: ConversionState) -> None:
    """Fill every ``/MAT/LAW5``'s ``Bunreacted`` cell, deriving it where the
    deck states ``K = 0`` and the material is a LAW51 phase.

    **What the cell is.** ``hm_read_mat05.F:160/234`` reads ``BUNREACTED`` into
    ``PM(44)``; ``fill_buffer_51.F:438/471`` copies it into ``UPARAM(50)``, and
    the engine's ``jwl51.F:197`` uses it as the UNREACTED solid's LINEAR
    pressure law ``Psol = C01 + C11*MU1`` (``:172 C11 = UPARAM(50)``), blended
    with the product pressure by the burn fraction at ``:205``. ``:214`` also
    makes it the unreacted sound speed ``sqrt(C11/RHO10)``, which enters the
    CFL step. LS-DYNA's ``K`` is the same quantity in the same form (Vol II R17
    p.2-188: *"Before detonation, pressure is given by
    p^{n+1} = K(1/V^{n+1} - 1)"*), so a stated ``K`` is copied 1:1.

    **Why a derivation is needed at all.** ``fill_buffer_51.F:496-499`` refuses
    ``C14 <= 0`` outright — *"BULK MODULUS OF LAW5 (JWL) MUST BE PROVIDED FOR
    UNREACTED EXPLOSIVE"*, ``ERROR 99`` — and the four ``underwater_*`` corpus
    decks all state ``K = 0`` with ``BETA = 0``. That is CORRECT LS-DYNA input,
    not a deck defect: ``K`` is *"Bulk modulus (BETA = 2.0 only)"*, and with
    ``BETA = 0`` ("beta burn plus programmed burn", ``F = max(F1,F2)``) the
    unburnt explosive obeys ``p = F·p_eos`` with ``F = 0``, i.e. LS-DYNA
    carries NO unreacted stress at all. Radioss has no such branch, so a value
    is required and the honest thing is to derive one from the deck's own
    physics and NAME it.

    **The derivation, and the two alternatives.** Three candidates exist from
    stated cells: the slope of the JWL's PRINCIPAL ISENTROPE at the unreacted
    density (:func:`_jwl_unreacted_bulk`, what is written); the tangent modulus
    of the FULL JWL the solver evaluates, which carries the
    ``(1 - omega/(R_i·V))`` factors of ``jwl51.F:191`` /
    ``m5law.F:126-129`` (:func:`_jwl_full_eos_bulk`); and ``rho0*D^2``, which
    the starter itself already computes at ``fill_buffer_51.F:488``
    (``UPARAM(275) = RHO40*SSP4^2`` with ``SSP4 = VDET``). On ``underwater_C``
    they are 26748.4, 23801 and 100188.9 MPa. The principal isentrope is what
    is written because it is the JWL's own reference curve for the condensed,
    unreacted solid — the quantity the cell asks for — and it is 3.7x softer
    than ``rho0*D^2``, so it perturbs the pre-burn state (which LS-DYNA leaves
    at zero) less. All three are printed in the warning, and MEASUREMENT says
    the choice is not what decides the run: a three-value sweep spanning 37x on
    ``underwater_C`` moved the last time step 0.14 %, the internal energy 1.1 %
    and the kinetic energy 0.19 %. Neither raises the time step risk:
    ``PM(27)`` already holds ``D`` (``:492``), and a SMALLER ``C11`` gives a
    LARGER, never smaller, unreacted-sound-speed step.

    **Where the value is actually consumed — and it is NOT only LAW51.** The
    substitution is triggered by an ``ERROR 99`` that lives in the LAW51
    ``Iform = 12`` branch, but the cell is written on the material's OWN
    ``/MAT/LAW5``, and on all four ``underwater_*`` carriers it is that
    stand-alone card, referenced by a real ``/PART``, that the engine runs —
    the emitted ``/MAT/LAW51`` is referenced by no ``/PART`` at all
    (``blast_ale._make_ale_multimaterial`` says so in capitals). So the live
    consumer is ``m5law.F``, where ``:135-146`` makes the cell a BRANCH SWITCH:
    ``BULK == 0`` gives the FULL product pressure in every cell with no
    burn-fraction weighting, and a positive ``BULK`` gives the
    ``(1-BFRAC)·(P0 + BULK·mu) + BFRAC·(...)`` blend. The warning states that
    rather than the ``jwl51.F`` path, which on these decks never executes.

    **Scope.** The substitution fires only when the source ``K`` is 0 AND the
    material is an ``*ALE_MULTI-MATERIAL_GROUP`` member, because ``ERROR 99``
    lives in the ``Iform = 12`` branch alone: a stand-alone ``/MAT/LAW5``
    (``underwater_A``/``_B``, ``exploding-sphere``, ``2Dlag``) reads the cell
    only through ``hm_read_mat05.F`` and is perfectly startable with 0 there,
    so writing a derived stiffness onto it would change four decks that have no
    problem. ``--he-bunreacted <value>`` overrides the derivation everywhere.
    """
    if not state.mat_high_explosive:
        return
    members = _ammg_member_mids(state)
    override = state.options.he_bunreacted
    for mid in sorted(state.mat_high_explosive):
        heb = state.mat_high_explosive[mid]
        jwl = state.eos_jwl.get(mid)
        dropped = []
        if heb.g:
            dropped.append(f"G={heb.g:g}")
        if heb.sigy:
            dropped.append(f"SIGY={heb.sigy:g}")
        if dropped:
            state.warn(
                f"*MAT_HIGH_EXPLOSIVE_BURN {mid}: " + " and ".join(dropped)
                + " have no /MAT/LAW5 cell — LAW5 is a pure pressure law with "
                "no deviator at all (jwl51.F computes only P), so the "
                "unreacted explosive's shear response and yield are DROPPED. "
                "Both are 'BETA = 2.0 only' cells in LS-DYNA "
                "(Vol II R17 p.2-186), so they are inert on a BETA = 0 or 1 "
                "card there too.")
        if override is not None:
            heb.bunreacted = override
            heb.bunreacted_note = (
                f"the --he-bunreacted override ({override:g})")
        elif heb.k > 0.0:
            heb.bunreacted = heb.k
            heb.bunreacted_note = f"the card's own stated K = {heb.k:g}"
        elif mid not in members:
            heb.bunreacted = 0.0
            heb.bunreacted_note = ""
            continue
        elif jwl is None:
            state.warn(
                f"*MAT_HIGH_EXPLOSIVE_BURN {mid} is an "
                "*ALE_MULTI-MATERIAL_GROUP member with K = 0, and "
                "fill_buffer_51.F:496 refuses a /MAT/LAW51 phase whose LAW5 "
                "Bunreacted is <= 0 (ERROR 99, 'BULK MODULUS OF LAW5 (JWL) "
                "MUST BE PROVIDED FOR UNREACTED EXPLOSIVE'). The derivation "
                "reads the companion *EOS_JWL's own coefficients and this "
                "material has none, so Bunreacted is left 0 and the starter "
                "will refuse the deck. Add the *EOS_JWL, state K on the "
                "*MAT_HIGH_EXPLOSIVE_BURN card, or pass --he-bunreacted.")
            continue
        else:
            derived = _jwl_unreacted_bulk(jwl)
            if derived <= 0.0:
                # BOTH arms of a back-solve must refuse the same degeneracies
                # (#129). Every sibling derivation in this batch screens its
                # own — LAW3 refuses `bulk <= 0`, LAW106 refuses `e_ref <= 0`,
                # and the `jwl is None` arm two branches up refuses by name —
                # and without this the ratio printed in the warning below is a
                # ZeroDivisionError that aborts the whole conversion with no
                # output and no diagnostic. A *EOS_JWL stating A = B = E0 = 0
                # reaches it exactly.
                heb.bunreacted = 0.0
                heb.bunreacted_note = ""
                state.warn(
                    f"*MAT_HIGH_EXPLOSIVE_BURN {mid} is an "
                    "*ALE_MULTI-MATERIAL_GROUP member with K = 0, and its "
                    f"companion *EOS_JWL (A = {jwl.a:g}, B = {jwl.b:g}, "
                    f"R1 = {jwl.r1:g}, R2 = {jwl.r2:g}, "
                    f"omega = {jwl.omega:g}, E0 = {jwl.e0:g}) gives a "
                    f"principal-isentrope slope of {derived:g}, which is not a "
                    "positive bulk modulus — so there is nothing to derive "
                    "Bunreacted from. It is left 0 and fill_buffer_51.F:496 "
                    "will answer ERROR 99 ('BULK MODULUS OF LAW5 (JWL) MUST BE "
                    "PROVIDED FOR UNREACTED EXPLOSIVE'). State K on the "
                    "*MAT_HIGH_EXPLOSIVE_BURN card, fix the *EOS_JWL "
                    "coefficients, or pass --he-bunreacted <value>.")
                continue
            heb.bunreacted = derived
            heb.bunreacted_note = (
                "a DERIVED value: the slope of the JWL's PRINCIPAL ISENTROPE "
                "at the unreacted density, K = -V dp_s/dV at V = 1 for "
                "p_s(V) = A*exp(-R1*V) + B*exp(-R2*V) + omega*E0/V, i.e. "
                "A*R1*exp(-R1) + B*R2*exp(-R2) + omega*E0 = "
                f"{jwl.a:g}*{jwl.r1:g}*exp(-{jwl.r1:g}) + "
                f"{jwl.b:g}*{jwl.r2:g}*exp(-{jwl.r2:g}) + {jwl.omega:g}*"
                f"{jwl.e0:g} = {heb.bunreacted:g}")
            state.warn(
                f"*MAT_HIGH_EXPLOSIVE_BURN {mid} -> /MAT/LAW5 Bunreacted = "
                f"{heb.bunreacted:g}, SUBSTITUTED. The deck states K = 0, "
                f"which is CORRECT LS-DYNA input on this card: K is 'Bulk "
                "modulus (BETA = 2.0 only)' (Vol II R17 p.2-186) and with "
                f"BETA = {heb.beta:g} the unburnt explosive obeys p = F*p_eos "
                "with F = 0, i.e. LS-DYNA carries NO unreacted stress at all. "
                "Radioss has no such branch: this material is an "
                "*ALE_MULTI-MATERIAL_GROUP member and fill_buffer_51.F:496 "
                "refuses a phase whose LAW5 Bunreacted is <= 0 (ERROR 99, "
                "'BULK MODULUS OF LAW5 (JWL) MUST BE PROVIDED FOR UNREACTED "
                f"EXPLOSIVE'). The value written is {heb.bunreacted_note}. "
                "WHERE IT IS CONSUMED, and it is NOT only the /MAT/LAW51 the "
                "starter complained about: the SAME cell rides on this "
                "material's own /MAT/LAW5, whose /PART-referenced elements run "
                "through m5law.F — and there the cell is a BRANCH SWITCH, not "
                "an added stiffness. m5law.F:135-138 is 'IF (BULK == ZERO) "
                "P = P0 + (WDR1V*ER1V + WDR2V*ER2V + DR1V)', the FULL JWL "
                "product pressure in every cell with no burn-fraction "
                "weighting at all; :140-146 is the ELSE, "
                "'P = (1-BFRAC)*(P0 + BULK*AMU) + BFRAC*(...)'. So a positive "
                "Bunreacted moves the unburnt cells from LS-DYNA's zero stress "
                "AND from Radioss's own product-pressure fallback onto "
                "P = K*mu, i.e. it changes the explosive's pressure law "
                "everywhere, not just before burn. (Inside /MAT/LAW51 the same "
                "number is jwl51.F:197's 'Psol = C01 + C11*MU1', blended at "
                ":205, with sqrt(C11/rho) as the unreacted sound speed at "
                ":214.) MEASURED on underwater_C: a three-value sweep spanning "
                "37x (2674.84 / 26748.40 / 100188.90) moves the last time step "
                "0.14 %, the internal energy 1.1 % and the kinetic energy "
                "0.19 % — so the CHOICE of value is not what decides the "
                "answer, but its PRESENCE is not free. "
                "THE OTHER TWO CANDIDATES, both from stated cells: "
                f"rho0*D^2 = {heb.rho * heb.d * heb.d:g}, which the starter "
                "already computes at fill_buffer_51.F:488 as UPARAM(275) and "
                f"which is {(heb.rho * heb.d * heb.d) / heb.bunreacted:.3g}x "
                "stiffer; and the tangent modulus of the FULL JWL the solver "
                "evaluates — jwl51.F:191 and m5law.F:126-129 both carry the "
                "(1 - omega/(R_i*V)) factors the principal isentrope does not, "
                "giving A*exp(-R1)*(R1 - omega/R1 - omega) + "
                "B*exp(-R2)*(R2 - omega/R2 - omega) + omega*E0 = "
                f"{_jwl_full_eos_bulk(jwl):g}, about "
                f"{100.0 * (1.0 - _jwl_full_eos_bulk(jwl) / heb.bunreacted):.3g}"
                " % below the value written. The principal isentrope is used "
                "because it is the JWL's own reference curve for the unreacted "
                "solid; the measurement above says the difference does not "
                "decide the run. Neither costs time step (PM(27) already holds "
                "D, and a SMALLER C11 raises the unreacted-sound-speed limit). "
                "Use --he-bunreacted <value> to state your own.")


# ─────────────────────────────────────────────────────────────────────────────
# R14 triage batch, round 1: the /MAT/LAW51 submaterial list
# ─────────────────────────────────────────────────────────────────────────────

#: The ONLY laws ``/MAT/LAW51`` accepts as a phase, from the starter's own
#: test: ``fill_buffer_51.F:210`` gates on
#: ``MLN == 2/3/4/5/6/10/102/133`` and ``:237`` answers anything else with
#: ``ERROR 99  SUBMATERIAL CAN ONLY BE DEFINED FROM LAWS 2,3,4,5,6,10 102 OR
#: 133``. k2rad's own ``*MAT_003 -> /MAT/LAW44`` route is exactly the case that
#: falls outside it.
_LAW51_ALLOWED_SUBMAT_LAWS = frozenset({2, 3, 4, 5, 6, 10, 102, 133})


def _submaterial_has_eos(state: ConversionState, mid: int, law: int) -> bool:
    """Does the ``/MAT`` k2rad EMITS for *mid* carry an equation of state?

    **A LAW51 phase must have one, and that MEASUREMENT corrects the source's
    own comment.** ``fill_buffer_51.F:213-219`` reads

        IF(EOS_TYPE /= 0 .AND. EOS_TYPE /= 12 .AND. EOS_TYPE /= 15
                          .AND. EOS_TYPE <= 21 ) THEN
          !all EoS expected <=0, 12, 15, >21
        ELSE
          chain1='SUBMATERIAL EOS IS NOT COMPATIBLE WITH MATERIAL LAW 51'

    — the comment says those types are EXPECTED, while the THEN branch is empty
    and the ELSE raises the error on exactly them, ``EOS_TYPE = 0`` included.
    ``:281`` says the same thing without ambiguity:
    ``IF(EOS_TYPE == 0 .AND. MLN /= 5) -> 'MISSING SUBMATERIAL EOS'``. The
    starter settles it: on ``cylinder_impact_A`` a ``/MAT/LAW51`` whose only
    phase was a ``/MAT/LAW2`` with no ``/EOS`` answered BOTH messages, while
    ``underwater_C`` — a ``/MAT/LAW5`` beside a ``/MAT/HYD_VISC`` +
    ``/EOS/GRUNEISEN`` — started at 0 ERROR / 0 WARNING.

    ``MLN == 5`` is exempt on both lines, because ``/MAT/LAW5`` carries its JWL
    inside the material.

    The screen is on what is EMITTED, never on ``state.eos_cards`` membership:
    a bare ``*EOS_*`` whose id happens to match another material is NOT written
    at all (``_make_explosive_and_eos_materials`` refuses it and says so), so
    the parse registry would claim an equation of state the deck does not
    contain (#130). Only the PRESENCE is screened, not the TYPE — one accepted
    type is measured (GRUNEISEN) and guessing the numbering of the rest would
    be inventing a table; a type the starter still refuses surfaces as its own
    ``ERROR 99``, which names the material.
    """
    if law == 5:
        return True                     # the JWL lives inside /MAT/LAW5
    if mid in state.mat_law3 or mid in state.mat_elastic_fluid:
        return True                     # both emit an /EOS of the same id
    jc = state.mat_johnson_cook.get(mid)
    if jc is not None and getattr(jc, "use_law4", False) \
            and getattr(jc, "eos_id", 0):
        return True                     # the LAW4 route rebinds its /EOS
    if mid in state.mat_null and mid not in _void_null_mids(state):
        return True                     # the /MAT/LAW6 carrier + its /EOS
    return mid in _null_part_eos_bindings(state)


# ─────────────────────────────────────────────────────────────────────────────
# RO <= 0: the density floor (starter ERROR 683)
# ─────────────────────────────────────────────────────────────────────────────

#: The density k2rad substitutes when a material states ``RO <= 0``, in the
#: DECK'S OWN unit system — DERIVED from LS-DYNA's measured behaviour, not
#: chosen.
#:
#: LS-DYNA accepts ``RO = 0.0`` and silently substitutes a floor. MEASURED on
#: the campaign's own reference results (``F:/dynaexamples_r14_ton-mm-s``,
#: LS-DYNA R14 in ton-mm-s), five decks and four element families:
#:
#:   ============================================  ==============  =========  =========
#:   deck (.d3hsp "total mass of part")            reported mass   volume     implied rho
#:   ============================================  ==============  =========  =========
#:   3.1_Elastic_Beams_etc  (hex/tet/shell/beam)   2.0483830E-20   20483.83   1.000e-24
#:   3.5_..._Plate_Hex                             2.0324782E-19   203247.82  1.000e-24
#:   3.5_..._Plate_Shell                           2.0324782E-19   203247.82  1.000e-24
#:   3.5_..._Plate_Tet                             2.0324782E-19   203247.82  1.000e-24
#:   6.2.PSD_Beam_Example_LSTC (beam)              4.0967660E-20   40967.66   1.000e-24
#:   ============================================  ==============  =========  =========
#:
#: Seven significant figures, five decks, four families — and LS-DYNA reports
#: ``*** Warning 30131 total number of massless nodes = 20`` rather than an
#: error. The floor is therefore ABSOLUTE and unit-agnostic, exactly as
#: LS-DYNA's is.
#:
#: A deck-RELATIVE rule ("1e-6 x the smallest positive density in the deck")
#: was considered and REFUTED by measurement: all eight corpus carriers state
#: RO = 0 on EVERY material they define, so such a rule has no input on any of
#: them.
_ZERO_DENSITY_FLOOR = 1.0e-24

#: The Radioss laws ``hm_read_mat.F90:1575-1583`` exempts from ERROR 683,
#: verbatim::
#:
#:     if (ilaw/=0   .and. ilaw/=20 .and. ilaw/=51 .and. ilaw/=151 .and.&
#:       ilaw/=108 .and. ilaw /= 999) then
#:       if (matparam%rho0 <= zero) then
#:         call ancmsg(msgid=683, ...
#:
#: A material that converts to one of these may state RO = 0 and is left
#: ALONE: on ``ale_wavehitcol.k`` the ``*MAT_VACUUM`` -> ``/MAT/VOID`` (LAW0)
#: density of 0.0 is the card's own MEANING, and flooring it would rewrite the
#: deck rather than rescue it.
_RHO_EXEMPT_LAWS = frozenset({0, 20, 51, 108, 151, 999})

#: The attribute names a material record spells its density with. Checked in
#: this order; the FIRST one the record has decides, so a record carrying both
#: cannot be floored twice.
_RHO_ATTRS = ("rho", "ro", "rho_i", "rho0", "density")


def _zero_density_records(state: ConversionState):
    """``[(field_name, mid, attr)]`` for every material record stating a
    density <= 0 whose target law is NOT exempt from ERROR 683.

    DISCOVERED, not enumerated. The scan walks every ``ConversionState`` field
    whose name starts with ``mat_`` and whose value is a ``mid -> dataclass``
    dict, so a material family added later is covered the day it is added —
    the inverse of the #120 trap, where a hand-kept list of registries goes
    stale and the new family is silently missed. (There are 80 such fields
    today, of which ``_material_registries`` deliberately lists only 47.)

    The law screen is ``mesh._target_mat_law``, the ONE mid -> law map in the
    codebase, and it is read in the SAFE direction: a material is floored
    unless its law is on ``_RHO_EXEMPT_LAWS``. ``None`` — "this map has no
    entry" — therefore floors, which is right for both of its cases: a
    material k2rad emits under a law the map has not learned yet still meets
    the starter's ERROR-683 gate, and a material k2rad emits no ``/MAT`` for
    at all has no density cell for the substitution to reach.
    """
    import dataclasses
    out: List[Tuple[str, int, str]] = []
    from .mesh import _target_mat_law
    for f in dataclasses.fields(state):
        if not f.name.startswith("mat_"):
            continue
        holder = getattr(state, f.name)
        if not isinstance(holder, dict):
            continue
        for mid, rec in sorted(holder.items()):
            if not isinstance(mid, int) or not dataclasses.is_dataclass(rec):
                continue
            for attr in _RHO_ATTRS:
                v = getattr(rec, attr, None)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    continue
                if v <= 0.0 and _target_mat_law(state, mid) \
                        not in _RHO_EXEMPT_LAWS:
                    out.append((f.name, mid, attr))
                break
    return out


def _apply_zero_density_floor(state: ConversionState) -> None:
    """Substitute ``RO = 1e-24`` for a material stating ``RO <= 0``, and say so.

    Eight decks of the R14 corpus state ``RO = 0.0`` literally and ran NORMAL
    TERMINATION in LS-DYNA; the OpenRadioss starter refuses every one of them
    with ``ERROR ID : 683 ... DENSITY IS LESS THAN OR EQUAL TO ZERO``. They are
    ``*CONTROL_IMPLICIT_GENERAL`` linear-static and ``*CONTROL_IMPLICIT_
    EIGENVALUE`` decks, where the mass matrix does not enter the answer — which
    is why LS-DYNA accepts the card at all.

    The substitution is applied to EVERY deck, not only an implicit one, and
    deliberately: the substitution IS what LS-DYNA does (there is no field-level
    check on either side), and restricting it to implicit decks would leave an
    explicit ``RO = 0`` deck failing at ERROR 683 with no explanation, which is
    worse than starting with a warning that says exactly why the run will crawl.
    The explicit case gets the harder sentence instead.

    Runs as a ``build_starter`` prepass AFTER every material-routing pass (so
    ``_target_mat_law`` answers for the final containers) and after
    ``_resolve_thermal`` (whose ``*MAT_ADD_THERMAL_EXPANSION`` split can CLONE a
    material — a clone made before this pass inherits the zero and is floored
    with its original, one made after would not be). Mutating the record rather
    than the emitted cell is the faithful model of what LS-DYNA does: its own
    d3hsp reports the substituted density in the part MASS, so every consumer
    downstream — the element time step, ``/HEAT/MAT``'s RHO0_CP, the modal
    chain's lumped masses — sees the same number the source code did.
    """
    if not state.options.zero_density_floor:
        return
    hits = _zero_density_records(state)
    if not hits:
        return
    from .mesh import _target_mat_law
    laws: Dict[int, Optional[int]] = {}
    stated: Dict[int, float] = {}
    for field_name, mid, attr in hits:
        holder = getattr(state, field_name)
        stated.setdefault(mid, float(getattr(holder[mid], attr)))
        setattr(holder[mid], attr, _ZERO_DENSITY_FLOOR)
        state.zero_density_floored.add(mid)
        laws[mid] = _target_mat_law(state, mid)
    mids = sorted({m for _f, m, _a in hits})
    # The MID and the TARGET LAW, not the LS-DYNA keyword: this pass discovers
    # its records by walking every ``mat_*`` dict on the state (so a material
    # family added later is covered the day it is added), and there is no
    # mid -> source-keyword map to read the spelling out of — each resolver
    # hard-codes its own ``kw`` string. Inventing one here would be exactly the
    # hand-kept list this scan exists to avoid. The MID is what the reader greps
    # the deck for, and the law says which card family it landed on.
    named = ", ".join(
        f"MID {mid} (RO = {stated[mid]:g}"
        + (f" -> /MAT/LAW{laws[mid]}" if laws[mid] is not None else "")
        + ")"
        for mid in mids)
    unknown = "" if all(laws[m] is not None for m in mids) else (
        " (a MID listed without a law converts to one mesh._target_mat_law "
        "has no entry for; the /MAT is still written and still meets the "
        "ERROR-683 gate, which is why it is floored too.)")
    state.warn(
        f"DENSITY: {named} — the source deck states a non-positive density on "
        f"each of them — and k2rad SUBSTITUTED rho = "
        f"{_ZERO_DENSITY_FLOOR:g} in the deck's own unit system. "
        "WHY THE VALUE: LS-DYNA makes the SAME substitution and its own d3hsp "
        "reports it — 'total mass of part = 0.20483830E-19' for the "
        "20483.83 mm3 part of 3.1_Elastic_Beams_etc is rho = 1.000e-24 to "
        "seven figures, measured identically on five reference decks and four "
        "element families, with 'Warning 30131 total number of massless nodes' "
        "instead of an error. "
        "WHY AT ALL: hm_read_mat.F90:1575-1583 refuses rho <= 0 outright "
        "(ERROR 683, DENSITY IS LESS THAN OR EQUAL TO ZERO), exempting only "
        "laws 0/20/51/151/108/999 — none of them a structural law — so the "
        "deck does not start without it. "
        "WHAT IT COSTS: a STATIC answer is unchanged — MEASURED, a 20x2x2 HEX8 "
        "cantilever run at rho = 1e-9, 1e-15 and 1e-24 gave the identical tip "
        "deflection -4.4916980000E-01 mm to all eight printed digits across "
        "nine decades — because /IMPL/QSTAT's "
        "inertia stabilization is S ~ M/dt^2 (imp_dyna.F:604-635) and is never "
        "divided by the mass, so it simply vanishes with it; a MODAL or PSD "
        "answer picks up a bounded shift df/f ~ -0.5 * rho*V / M_effective, "
        "which on 6.2.PSD_Beam_Example_LSTC is 2.1e-17 — below double "
        "precision; a TRANSIENT answer is not meaningful at all, because the "
        "model has no inertia. "
        "MASS DIAGNOSTICS ARE MEANINGLESS on such a deck: k2rad's injected "
        "implicit probe rigid body carries a hard-coded Mass = 0.001, some 17 "
        "orders of magnitude above the model's own, so TOTAL MASS, MAS.ERR and "
        "any /TH mass channel report that body and not the structure. "
        "Pass --no-zero-density-floor (convert(zero_density_floor=False)) to "
        "copy the deck's own RO through and let the starter refuse it."
        + unknown)
    if not state.is_implicit:
        state.warn(
            "DENSITY: this deck is EXPLICIT, and a substituted rho = "
            f"{_ZERO_DENSITY_FLOOR:g} makes the element time step collapse: "
            "the bar wave speed is c = sqrt(E/rho), so a steel-modulus "
            "material at this density gives c ~ 2.6e14 mm/s and dt ~ 1e-14 s. "
            "The starter will accept the deck and the engine will never reach "
            "the termination time. RO = 0 has a defensible meaning only on an "
            "implicit STATIC or EIGENVALUE deck, where the mass matrix does "
            "not enter the answer — state a real density for a transient run.")


def _resolve_ale_submaterials(state: ConversionState) -> None:
    """Decide each ``*ALE_MULTI-MATERIAL_GROUP``'s ``/MAT/LAW51`` phase list.

    Three things happen here, and each is the fix for one measured starter
    error on the R14 corpus:

    **(a) A VACUUM phase is dropped from the list, not carried as MID 0.**
    ``hm_read_mat51.F:608-627`` reads exactly ``MIP`` rows and a ``tMID <= 0``
    inside that range is a fatal *INCORRECT MATERIAL IDENTIFIER*, so a vacuum
    cannot be declared at all — and it does not need to be: ``:639-646`` checks
    only ``SUM(alpha) > 1``, so a sum BELOW one is legal and the undeclared
    balance IS the void. `stagnation_A/B` and `cylinder_impact_A/B` are this
    shape (*"NON EXISTING SUBMATERIAL IDENTIFIER"*, ``ERROR 99``).

    **(b) A member with no ``/EOS`` is dropped, whatever its law.** This screen
    is what a research plan to RESTATE ``*MAT_PLASTIC_KINEMATIC`` as
    ``/MAT/LAW2`` was replaced by, and the replacement was MEASURED (commit
    ``ff7a82d``). ``fill_buffer_51.F:213-219``'s THEN branch is empty and its
    ELSE raises on exactly the ``EOS_TYPE`` values its own comment calls
    expected — ``EOS_TYPE = 0`` included — and ``:281`` states it plainly:
    ``IF(EOS_TYPE == 0 .AND. MLN /= 5)`` → *"MISSING SUBMATERIAL EOS"*. So a
    restatement could never produce a legal phase: it clears the law test and
    dies on the EOS one. ``cylinder_impact_A`` carrying the restatement
    answered BOTH messages; ``underwater_C`` (LAW5 + LAW6 with an
    ``/EOS/GRUNEISEN``) started at 0 ERROR. The restatement machinery — and the
    AMMG clone path that went with it — was therefore REMOVED rather than
    shipped as a capability that cannot work, and such a phase is dropped by
    name while the material keeps its ``/MAT/LAW44``.

    **(c) Anything else that is not on the allowed list is dropped by name.**
    A phase k2rad emits under an unlisted law is ``ERROR 99`` and refuses the
    whole deck; dropping it leaves a legal card and a warning that says which
    phase is gone and why. ``*MAT_ELASTIC`` (LAW1) is the case to watch — it is
    NOT an AMMG member on any corpus deck (``stagnation``'s AMMG lists parts 1
    and 2, and its ``*MAT_ELASTIC`` is the Lagrangian shell part 3 coupled by
    ``*CONSTRAINED_LAGRANGE_IN_SOLID``), and the manual route if it ever is
    would be ``/MAT/LAW2`` with an unreachable yield.

    What this does NOT do is consolidate the ALE mesh — see
    ``blast_ale._make_ale_multimaterial``, whose warning states in one sentence
    that the emitted ``/MAT/LAW51`` is referenced by no ``/PART`` and that the
    run therefore does not reproduce the LS-DYNA model.
    """
    if not state.ale_mmgs:
        return
    from .blast_ale import _part_pids
    from .mesh import _target_mat_law
    for k, mmg in enumerate(state.ale_mmgs):
        kept: List[int] = []
        dropped: List[str] = []
        seen: Set[int] = set()
        for sid, idtype in mmg.entries:
            for pid in _part_pids(state, sid, idtype == 1):
                part = state.parts.get(pid)
                if part is None or not part.mid or part.mid in seen:
                    continue
                mid = part.mid
                seen.add(mid)
                if mid in state.refused_materials:
                    kw = state.refused_materials[mid][0]
                    dropped.append(
                        f"MID {mid} (*{kw}) — refused by name; see its own "
                        "warning")
                    continue
                if mid in state.mat_vacuum:
                    dropped.append(
                        f"MID {mid} (*MAT_VACUUM -> /MAT/VOID) — Radioss "
                        "represents void as the UNDECLARED BALANCE of the "
                        "phase volume fractions, not as a phase: LAW0 is not "
                        "on fill_buffer_51.F:210's list and a tMID <= 0 inside "
                        "the MIP rows is fatal (hm_read_mat51.F:608-627), "
                        "while :639-646 checks only that the fractions SUM "
                        "ABOVE 1. The vacuum *PART keeps its /MAT/VOID so it "
                        "resolves")
                    continue
                law = _target_mat_law(state, mid)
                if law is None:
                    dropped.append(
                        f"MID {mid} — no /MAT is emitted for it at all, so a "
                        "phase naming it would be ERROR 99 'NON EXISTING "
                        "SUBMATERIAL IDENTIFIER' (fill_buffer_51.F:202)")
                    continue
                # The EOS screen comes FIRST: a phase with no equation of
                # state is refused whatever its law, so a material that fails
                # it must never be restated into one that passes the law test
                # and then dies here anyway (measured on cylinder_impact_A).
                if not _submaterial_has_eos(state, mid, law):
                    dropped.append(
                        f"MID {mid} (/MAT/LAW{law}) — it carries no /EOS, and "
                        "fill_buffer_51.F:213-219 refuses a non-explosive "
                        "phase with EOS_TYPE 0 ('SUBMATERIAL EOS IS NOT "
                        "COMPATIBLE WITH MATERIAL LAW 51' plus 'MISSING "
                        "SUBMATERIAL EOS'). MEASURED on cylinder_impact_A: a "
                        "LAW51 whose only phase was a /MAT/LAW2 with no /EOS "
                        "answered both, while underwater_C's LAW5 + "
                        "LAW6+/EOS/GRUNEISEN pair started at 0 ERROR. NOTE the "
                        "source's own comment at :214 reads the opposite way; "
                        "the solver follows the code. A LAW51 phase is a FLUID "
                        "with an equation of state — give the material an "
                        "*EOS_* if it is meant to be one")
                    continue
                if law in _LAW51_ALLOWED_SUBMAT_LAWS:
                    kept.append(mid)
                    continue
                # A GUARD, and today an unreachable one: every material this
                # converter gives an /EOS to lands on law 3, 4, 5 or 6, and all
                # four are on the list — so nothing gets past the screen above
                # and fails here. It is written because the rule is the
                # starter's, not because a corpus deck needs it (#120: write
                # the screen where the risk is), and it costs one branch and no
                # output.
                dropped.append(
                    f"MID {mid} (/MAT/LAW{law}) — fill_buffer_51.F:210 accepts "
                    "only laws 2, 3, 4, 5, 6, 10, 102 and 133 as a phase "
                    "(:237 'SUBMATERIAL CAN ONLY BE DEFINED FROM LAWS "
                    "2,3,4,5,6,10 102 OR 133')"
                    + (" — a *MAT_ELASTIC member would be /MAT/LAW2 with an "
                       "unreachable yield (a = 1e20, b = 0) AND an /EOS; state "
                       "it that way if the phase is meant to be there"
                       if law == 1 else ""))
        state.ale_mmg_submats[k] = kept
        if dropped:
            state.warn(
                f"*ALE_MULTI-MATERIAL_GROUP #{k + 1}: {len(dropped)} phase(s) "
                "DROPPED from the /MAT/LAW51 submaterial list — "
                + "; ".join(dropped)
                + f". MIP falls to {len(kept)}. That is legal: "
                "hm_read_mat51.F:639-646 checks only that the volume fractions "
                "SUM ABOVE 1, so a sum below 1 is accepted and the undeclared "
                "balance is how Radioss represents void — but any phase "
                "dropped for another reason is MODEL CONTENT that is gone, "
                "not void.")


