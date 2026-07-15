"""Starter materials: /MAT laws, EOS, failure cards, /FUNCT curves and table resolution."""

from __future__ import annotations

from typing import List, Optional, Tuple
from ..state import (
    ConversionState,
    MatElastic,
    MatPlasTAB,
    MatPlasKin,
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
    Curve,
    MatHighExplosiveBurn,
    EosJwl,
    EosCard,
)
from .common import HDR, _f, _i, _spotweld_beam_pids
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
    "_emit_mat_law44",
    "_emit_mat_law128",
    "_emit_mat_law36_powerlaw",
    "_emit_mat_law76",
    "_emit_mat_law50",
    "_emit_mat_law38",
    "_emit_mat_law70",
    "_emit_mat_law28",
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
    for mat in state.mat_aniso_visco.values():
        lines += _emit_mat_law128(mat, state)
    for mat in state.mat_rigid.values():
        lines += _emit_mat_elast_for_rigid(mat)
    # A *MAT_NULL that carries a companion *EOS_* becomes a hydro /MAT/LAW6 (with
    # that /EOS) below; a bare *MAT_NULL stays /MAT/VOID (vacuum/void ALE phase).
    eos_mids = set(state.eos_cards) | set(state.eos_jwl)
    for mat in state.mat_null.values():
        if mat.mid not in eos_mids:
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


def _emit_mat_add_erosion(ero: MatAddErosion, state: ConversionState) -> List[str]:
    """*MAT_ADD_EROSION → /FAIL. Only the strain criteria map: MXEPS (max
    principal strain) → /FAIL/TENSSTRAIN, EFFEPS (max effective strain) →
    /FAIL/JOHNSON. Everything else is reported and left out."""
    lines: List[str] = []
    if ero.idam:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: IDAM={ero.idam} (GISSMO/DIEM in "
                   "the erosion card) is not converted — use "
                   "*MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2 instead.")
    if ero.mxeps > 0.0:
        lines += [
            f"/FAIL/TENSSTRAIN/{ero.mid}",
            "#         EPSILON_T1          EPSILON_T2    FCT_ID          EPSILON_F1          EPSILON_F2     S_Flag",
            f"{_f(ero.mxeps)}{_f(ero.mxeps)}{_i(0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
            HDR,
        ]
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: MXEPS={ero.mxeps:g} → "
                   "/FAIL/TENSSTRAIN (element erodes at that maximum principal "
                   "tensile strain).")
    if ero.effeps > 0.0:
        lines += _emit_fail_johnson_all_layers(ero.mid, ero.effeps, state)
    if ero.other:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: criteria "
                   f"{', '.join(ero.other)} are not converted (only EFFEPS and "
                   "MXEPS map to an OpenRadioss /FAIL model).")
    if not lines and not ero.idam:
        state.warn(f"*MAT_ADD_EROSION {ero.mid}: no convertible criterion "
                   "(EFFEPS/MXEPS) found — no /FAIL emitted.")
    return lines


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


def _make_explosive_and_eos_materials(state: ConversionState) -> List[str]:
    """/MAT/LAW5 explosives and /MAT/LAW6+/EOS fluids for the coupled ALE path."""
    if not (state.mat_high_explosive or state.eos_cards or state.eos_jwl):
        return []
    lines: List[str] = []
    # JWL high explosives: *MAT_HIGH_EXPLOSIVE_BURN + *EOS_JWL → /MAT/LAW5
    for mid, heb in sorted(state.mat_high_explosive.items()):
        lines += _emit_mat_law5(state, heb, state.eos_jwl.get(mid))
    for eosid in sorted(set(state.eos_jwl) - set(state.mat_high_explosive)):
        state.warn(f"*EOS_JWL {eosid}: no companion *MAT_HIGH_EXPLOSIVE_BURN "
                   "(same id) — the JWL parameters have no material to attach to "
                   "and were not emitted (add the explosive material).")
    # Other fluids: carrier /MAT/LAW6 (HYD_VISC) + /EOS/<kind>
    for eosid, eos in sorted(state.eos_cards.items()):
        carrier = state.mat_null.get(eosid)
        rho = carrier.rho if carrier else eos.params.get("rho0", 0.0)
        title = carrier.title if carrier else ""
        if not carrier and rho <= 0.0:
            state.warn(f"*EOS_{eos.kind} {eosid}: no companion *MAT_NULL to give a "
                       "density for the /MAT/LAW6 carrier and no reference "
                       "density — RHO_I left 0; set the fluid density.")
        # Radioss /EOS/IDEAL-GAS requires a POSITIVE initial pressure. LS-DYNA
        # gives specific heats + temperature, so derive P0 = rho*(Cp-Cv)*T0.
        if eos.kind == "IDEAL-GAS" and eos.params.get("p0", 0.0) <= 0.0:
            cv = eos.params.get("cv", 0.0)
            cp = eos.params.get("cp", 0.0)
            t0 = eos.params.get("t0", 0.0)
            if rho > 0.0 and cp > cv > 0.0 and t0 > 0.0:
                eos.params["p0"] = rho * (cp - cv) * t0
            else:
                state.warn(f"*EOS_IDEAL_GAS {eosid}: could not derive a positive "
                           "initial pressure (need density, Cv<Cp and T0) — "
                           "/EOS/IDEAL-GAS P0 left 0, which the starter rejects; "
                           "set P0 manually.")
        lines += _emit_mat_law6_carrier(eosid, title, rho)
        lines += _emit_eos(eos)
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
                                  state: ConversionState) -> List[str]:
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
    """
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
        f"{_f(epsf)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#      EPSILON_DOT_0  IFAIL_SH  IFAIL_SO                                    DADV",
        f"{_f(0.0)}         2         1                    {_f(0.0)}",
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
        nf_card = f"{_i(len(fam))}{_i(0)}"
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
    return lines


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
        f"{_f(mat.epfail)}{_f(mat.deprpt)}",
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
