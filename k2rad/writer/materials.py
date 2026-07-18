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
    Curve,
    MatHighExplosiveBurn,
    EosJwl,
    EosCard,
)
from .common import HDR, _f, _i, _part_node_sets, _spotweld_beam_pids
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
    "_resolve_mat_hyper_rubber",
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
    # "Carries" = shares the EOS id (the legacy pairing convention) OR is bound
    # to a supported *EOS_* by a *PART EOSID field.
    eos_mids = set(state.eos_cards) | set(state.eos_jwl)
    eos_bound_nulls = set(_null_part_eos_bindings(state))
    for mat in state.mat_null.values():
        if mat.mid not in eos_mids and mat.mid not in eos_bound_nulls:
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
    # Hyperelastic rubber batch (routing resolved by _resolve_mat_hyper_rubber)
    for mat in state.mat_blatz_ko.values():
        lines += _emit_mat_law42_blatz_ko(mat)
    for mat in state.mat_mooney_rivlin.values():
        lines += _emit_mat_mooney_rivlin(mat)
    for mat in state.mat_ogden.values():
        lines += _emit_mat_ogden_rubber(mat)
    for mat in state.mat_hyper_rubber.values():
        lines += _emit_mat_hyper_rubber(mat)
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
    for eosid in sorted(set(state.eos_jwl) - set(state.mat_high_explosive)
                        - jc_consumed):
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


def _emit_mat_law2_plas_johns(mat: MatJohnsonCook,
                              state: ConversionState) -> List[str]:
    """/MAT/LAW2 (PLAS_JOHNS) — classic a,b,n Johnson-Cook input (Iflag=0).

    Layout audited against hm_cfg_files MAT/matl2_plas_johns.cfg
    FORMAT(radioss140) — the block a /BEGIN 2022 deck is read with (the
    flagVP column only exists from FORMAT(radioss2023) on):
      RHO_I(20) / E(20) Nu(20) Iflag(10) /
      a(20) b(20) n(20) EPS_p_max(20) SIG_max0(20) /
      c(20) EPS_DOT_0(20) ICC(10) Fsmooth(10) F_cut(20) Chard(20) /
      m(20) T_melt(20) rhoC_p(20) T_r(20)
    Blank(0) fields keep the starter defaults: n→1, EPS_p_max/SIG_max0→1e30,
    ICC→1, T_melt→1e20 (softening off), T_r→300, m→1."""
    if mat.pc != 0.0:
        state.warn(
            f"*MAT_JOHNSON_COOK mid={mat.mid}: PC={mat.pc:g} (pressure cutoff) "
            "has no slot on /MAT/LAW2 — dropped. It only maps to the "
            "hydrodynamic /MAT/LAW4 Pmin, which needs an *EOS_* attached to "
            "the part.")
    return [
        f"/MAT/LAW2/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  Nu     Iflag",
        f"{_f(mat.e)}{_f(mat.nu)}{_i(0)}",
        "#                  a                   b                   n           EPS_p_max            SIG_max0",
        f"{_f(mat.a)}{_f(mat.b)}{_f(mat.n)}{_f(mat.eps_p_max)}{_f(mat.sig_max0)}",
        "#                  c           EPS_DOT_0       ICC   Fsmooth               F_cut               Chard",
        f"{_f(mat.c)}{_f(mat.epso)}{_i(0)}{_i(mat.fsmooth)}{_f(0.0)}{_f(0.0)}",
        "#                  m              T_melt              rhoC_p                 T_r",
        f"{_f(mat.m)}{_f(mat.tmelt)}{_f(mat.rhocp)}{_f(mat.tref)}",
        HDR,
    ]


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
        lines += _emit_mat123_extra_fail(mat, state)
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
    lines += _emit_mat123_extra_fail(mat, state)
    return lines


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
    lines = [
        f"/VISC/PRONY/{mid}",
        "#        M                           K_v      Itab    Ishape",
        f"{_i(len(gis))}{' ' * 10}{_f(0.0)}{_i(0)}{_i(0)}",
        "#                G_i              Beta_i                  Ki             Beta_ki",
    ]
    for g, b in zip(gis, betais):
        lines.append(f"{_f(g)}{_f(b)}{_f(0.0)}{_f(0.0)}")
    lines.append(HDR)
    return lines


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
    REF=1 material has no reference-geometry coverage to initialize from."""
    flagged = [(kw, m) for kw, mats in (
        ("*MAT_BLATZ-KO_RUBBER", state.mat_blatz_ko),
        ("*MAT_MOONEY-RIVLIN_RUBBER", state.mat_mooney_rivlin),
        ("*MAT_OGDEN_RUBBER", state.mat_ogden),
        ("*MAT_HYPERELASTIC_RUBBER", state.mat_hyper_rubber),
    ) for m in mats.values() if m.ref != 0.0]
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
    table_ids = getattr(state, "law76_table_ids", set())
    lines = ["#-  FUNCTIONS:", HDR]
    for lcid, curve in sorted(state.curves.items()):
        if lcid in table_ids:
            # LAW76 yield curves must be /TABLE (1D). Layout from CURVE/table_1.cfg:
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
