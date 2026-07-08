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
    MatElastic, MatPlasTAB, MatPlasKin, MatRigid, MatNull, MatPowerLaw, MatSAMP,
    SectionShell, SectionSolid, SectionBeam,
    PartData, Curve, CoordSys,
    BcsSpc, PrescribedMotionRigid, PrescribedMotionSet, LoadRigidBody,
    ContactAutoSingle, ContactAutoSurf2Surf,
    InitialVelocityNode, InitialVelocityRigidBody, PressureLoad,
    MatHighExplosiveBurn, EosJwl, EosCard, InitialDetonation,
    AleMultiMaterialGroup, ConstrainedLagrangeInSolid, InitialVolumeFraction,
    BoundaryNonReflecting, ControlAle,
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


# ── Small 3-vector helpers (for /SKEW/FIX axis construction) ──────────────────

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vnorm(a):
    import math
    m = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if m == 0.0:
        return None
    return (a[0] / m, a[1] / m, a[2] / m)


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
    # Mg = megagram = 1000 kg = 1 tonne. Default is Mg/mm/s to match the .k file;
    # callers may override via convert(units=...) / the CLI --units flag.
    title = state.model_title[:80].ljust(80)
    mass, length, time = state.units
    unit_line = f"{mass.rjust(20)}{length.rjust(20)}{time.rjust(20)}"
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
        lines += _emit_mat_law36(mat, state)
    for mat in state.mat_plas_kin.values():
        lines += _emit_mat_law44(mat, state)
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
    lines += _make_explosive_and_eos_materials(state)
    lines += _make_ale_multimaterial(state)
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


def _emit_mat_law36(mat: MatPlasTAB, state: ConversionState) -> List[str]:
    fid = mat.funct_id
    fail = mat.fail if 0.0 < mat.fail < 1e19 else 0.0
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
    ordinate scale, no XFAC and no IFORM/IQUAD in this card, so those take the
    LAW76 defaults (1.0 / 1.0 / 0 / 0)."""
    xfac = 1.0
    fsmooth = 1                       # ISRATE: strain-rate smoothing on
    fcut = mat.asrate if mat.asrate > 0.0 else 1e30
    fscale1 = 1.0 if mat.fct_id1 else 0.0
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
        f"{_i(0)}{_i(0)}{_i(mat.iconv)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: nodes
# ─────────────────────────────────────────────────────────────────────────────

def _make_nodes(state: ConversionState, progress=None) -> List[str]:
    if not state.nodes:
        return []
    lines = ["#-  NODES:", HDR, "/NODE",
             "#  Node ID               X               Y               Z"]
    items = sorted(state.nodes.items())
    total = len(items)
    step = max(1, total // 20)
    for idx, (nid, nd) in enumerate(items):
        lines.append(f"{_i(nid)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}")
        if progress is not None and idx % step == 0:
            progress(idx / total)
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

def _emit_skew_fix(skew_id: int, title: str, origin, yaxis, zaxis) -> List[str]:
    """Emit /SKEW/FIX. The two vector cards are the LOCAL Y and Z axes — NOT X
    and Y: per the Reference Guide (and cfg attrs globalyaxis/globalzaxis),
    X1Y1Z1 = Y', X2Y2Z2 = Z', and the starter builds X' = Y' × Z' then
    re-orthogonalizes Y'' = Z' × X'. Passing X/Y here would yield a cyclically
    permuted frame (Radioss-X = intended Z) and rotate every skewed BCS/CLOAD.
    """
    return [
        f"/SKEW/FIX/{skew_id}",
        title,
        "#                 Ox                  Oy                  Oz",
        f"{_f(origin[0])}{_f(origin[1])}{_f(origin[2])}",
        "#                 X1                  Y1                  Z1   (local Y axis)",
        f"{_f(yaxis[0])}{_f(yaxis[1])}{_f(yaxis[2])}",
        "#                 X2                  Y2                  Z2   (local Z axis)",
        f"{_f(zaxis[0])}{_f(zaxis[1])}{_f(zaxis[2])}",
        HDR,
    ]


def _make_skews(state: ConversionState) -> List[str]:
    if not state.coord_sys and not state.coord_nodes:
        return []
    lines = ["#-  SKEWS / COORDINATE SYSTEMS:", HDR]
    for cid, cs in sorted(state.coord_sys.items()):
        # *DEFINE_COORDINATE_SYSTEM gives POINTS: origin O, a point L on the
        # local x-axis and a point P in the local x-y plane — convert to axis
        # vectors before emitting (raw point coordinates are only valid vectors
        # when the origin happens to be (0,0,0)).
        origin = (cs.xo, cs.yo, cs.zo)
        xv = _vnorm(_vsub((cs.xl, cs.yl, cs.zl), origin))
        zv = None
        if xv is not None:
            zv = _vnorm(_vcross(xv, _vsub((cs.xp, cs.yp, cs.zp), origin)))
        if zv is None:
            state.warn(
                f"*DEFINE_COORDINATE_SYSTEM cid={cid}: degenerate axis points - "
                "global axes used for /SKEW/FIX."
            )
            yv, zv = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        else:
            yv = _vcross(zv, xv)
        lines += _emit_skew_fix(cid, f"SKEW_{cid}", origin, yv, zv)
    for cid, cn in sorted(state.coord_nodes.items()):
        lines += _emit_skew_from_nodes(state, cn)
    return lines


def _skew_axes_from_nodes(state: ConversionState, cn):
    """Compute the local (X, Y, Z) orthonormal axes of a *DEFINE_COORDINATE_NODES
    system at t=0 from node coordinates, honouring LS-DYNA's `dir` convention.

    n1->n2 is the `dir` axis; n3 (with n1) fixes the next cyclic axis (toward n3).
    Returns ((Ox,Oy,Oz), Xaxis, Yaxis) or None if a node/geometry is degenerate.
    """
    n1 = state.nodes.get(cn.n1)
    n2 = state.nodes.get(cn.n2)
    n3 = state.nodes.get(cn.n3)
    if not (n1 and n2 and n3):
        return None
    origin = (n1.x, n1.y, n1.z)
    a = _vsub((n2.x, n2.y, n2.z), origin)       # n1->n2 = the `dir` axis
    b = _vsub((n3.x, n3.y, n3.z), origin)       # n1->n3 lies in the dir/next plane
    e_dir = _vnorm(a)
    nrm = _vnorm(_vcross(a, b))                  # plane normal (a x b)
    if e_dir is None or nrm is None:
        return None
    inplane = _vnorm(_vcross(nrm, e_dir))        # perp to dir, in plane, toward n3
    if inplane is None:
        return None
    # Cyclic assignment X->Y->Z->X: dir axis = e_dir, next (in-plane) = inplane,
    # the one after = nrm. This reproduces /SKEW/MOV's documented axes exactly.
    if cn.dir == "Y":
        X, Y, Z = nrm, e_dir, inplane
    elif cn.dir == "Z":
        X, Y, Z = inplane, nrm, e_dir
    else:  # "X" (default)
        X, Y, Z = e_dir, inplane, nrm
    return origin, X, Y


def _emit_skew_from_nodes(state: ConversionState, cn) -> List[str]:
    """Emit a /SKEW for a *DEFINE_COORDINATE_NODES system.

    flag=1 (co-rotating) -> /SKEW/MOV with the SAME (N1, N2, N3, Dir) card, which
    OpenRadioss recomputes every step. flag=0 (fixed) -> /SKEW/FIX with the axes
    evaluated once from the t=0 node coordinates. If the nodes are missing/
    degenerate, fall back to /SKEW/MOV so the skew_ID still resolves.
    """
    axes = _skew_axes_from_nodes(state, cn)
    if cn.flag == 1 or axes is None:
        if cn.flag != 1 and axes is None:
            state.warn(
                f"*DEFINE_COORDINATE_NODES cid={cn.cid}: nodes "
                f"{cn.n1}/{cn.n2}/{cn.n3} missing or collinear at t=0 — emitted a "
                "moving /SKEW/MOV instead of a fixed /SKEW/FIX."
            )
        else:
            state.warn(
                f"*DEFINE_COORDINATE_NODES cid={cn.cid}: flag=1 -> co-rotating "
                f"/SKEW/MOV (N1={cn.n1}, N2={cn.n2}, N3={cn.n3}, Dir={cn.dir})."
            )
        return [
            f"/SKEW/MOV/{cn.cid}",
            f"SKEW_NODES_{cn.cid}",
            "#  node_ID1  node_ID2  node_ID3       Dir",
            f"{_i(cn.n1)}{_i(cn.n2)}{_i(cn.n3)}{cn.dir.rjust(10)}",
            HDR,
        ]
    origin, X, Y = axes
    state.warn(
        f"*DEFINE_COORDINATE_NODES cid={cn.cid}: flag={cn.flag} -> fixed "
        f"/SKEW/FIX with axes computed at t=0 (Dir={cn.dir}); set flag=1 in the "
        ".k file for a co-rotating /SKEW/MOV."
    )
    return _emit_skew_fix(cn.cid, f"SKEW_NODES_{cn.cid}", origin, Y, _vcross(X, Y))


# ─────────────────────────────────────────────────────────────────────────────
# Starter: parts + elements
# ─────────────────────────────────────────────────────────────────────────────

def _ordered_unique_nodes(nodes: List[int]) -> List[int]:
    """Distinct positive node IDs, preserving first-seen order.

    LS-DYNA stores a 4-node tet either as 4 IDs or as an 8-slot hex with
    nodes 5-8 collapsed onto node 4 (e.g. n1 n2 n3 n4 n4 n4 n4 n4). Either
    way this returns the 4 distinct corners, so callers can detect tets.
    """
    seen: Set[int] = set()
    out: List[int] = []
    for n in nodes:
        if n > 0 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# Mid-edge node -> (corner A, corner B) of its edge, in the node order this
# converter emits (verified empirically against the real mesh): node5=mid(1,2),
# node6=mid(2,3), node7=mid(1,3), node8=mid(2,4), node9=mid(3,4), node10=mid(1,4).
_TET10_MIDEDGE = [(4, 0, 1), (5, 1, 2), (6, 0, 2), (7, 1, 3), (8, 2, 3), (9, 0, 3)]


def _snap_tet10_midsides(state: ConversionState) -> int:
    """Move every 10-node tet's mid-edge nodes onto the exact midpoints of their
    corner edges (straight-edged "sub-parametric" /TETRA10).

    A mid-edge node displaced from the midpoint can fold the quadratic Jacobian
    (det J changes sign inside the element) → OpenRadioss ERROR 489 "BADLY SHAPED
    10-NODE TETRA". Crucially this is NOT predicted by mid-edge deviation or corner
    aspect ratio alone — it's the corner+midside interaction — so the only robust,
    deterministic cure is to straighten the edges: a straight-edged tetra has a
    constant-sign Jacobian for any non-degenerate corner tet, so it cannot fold.
    Shared mid-edge nodes map to the same midpoint, so the pass is consistent;
    curved boundary elements are flattened slightly (still quadratic interior).
    Returns the number of distinct mid-edge nodes actually moved.
    """
    moved: Set[int] = set()
    for e in state.solid_elems:
        if len(e.nodes) != 10:
            continue
        cs = [state.nodes.get(e.nodes[k]) for k in range(4)]
        if any(c is None for c in cs):
            continue
        for mi, a, b in _TET10_MIDEDGE:
            mnid = e.nodes[mi]
            m = state.nodes.get(mnid)
            if m is None:
                continue
            mx = 0.5 * (cs[a].x + cs[b].x)
            my = 0.5 * (cs[a].y + cs[b].y)
            mz = 0.5 * (cs[a].z + cs[b].z)
            if abs(m.x - mx) > 1e-9 or abs(m.y - my) > 1e-9 or abs(m.z - mz) > 1e-9:
                m.x, m.y, m.z = mx, my, mz
                moved.add(mnid)
    return len(moved)


def _tet_corner_metrics(
    state: ConversionState, nodes: List[int]
) -> Optional[Tuple[float, float, float, float]]:
    """Shape metrics of the tetrahedron spanned by the first 4 node IDs:
    (lmin, lmax, lmean, vol) with vol = |signed volume| and lmin/lmax/lmean over
    the 6 corner edges. Returns None if any corner node is missing.
    """
    import math
    pts = []
    for n in nodes[:4]:
        nd = state.nodes.get(n)
        if nd is None:
            return None
        pts.append((nd.x, nd.y, nd.z))
    if len(pts) < 4:
        return None
    c0, c1, c2, c3 = pts

    def dist(a, b):
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)

    L = [dist(pts[a], pts[b]) for a in range(4) for b in range(a + 1, 4)]
    a = (c1[0] - c0[0], c1[1] - c0[1], c1[2] - c0[2])
    b = (c2[0] - c0[0], c2[1] - c0[1], c2[2] - c0[2])
    d = (c3[0] - c0[0], c3[1] - c0[1], c3[2] - c0[2])
    cx = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    vol = abs(cx[0] * d[0] + cx[1] * d[1] + cx[2] * d[2]) / 6.0
    return min(L), max(L), sum(L) / 6.0, vol


def _tet10_badly_shaped(state: ConversionState, nodes: List[int]) -> bool:
    """True if a 10-node tet's 4-corner shape is a sliver/degenerate tetra that
    OpenRadioss rejects as /TETRA10 (ERROR 489: BADLY SHAPED 10-NODE TETRA).

    Quadratic tets fail the Jacobian check when the underlying tetra is nearly
    flat. Criterion (on the 4 corners, independent of mid-edge ordering): shortest
    edge < 1/8 of the longest (aspect ratio > 8), OR normalized volume
    V / mean_edge^3 < 0.02, OR non-positive volume. These sliver elements have
    ~zero volume (negligible stiffness), so the writer drops them rather than keep
    a deck OpenRadioss won't read.
    """
    m = _tet_corner_metrics(state, nodes)
    if m is None:
        return False
    lmin, lmax, lmean, vol = m
    if lmin <= 0.0:
        return True
    if lmax / lmin > 8.0:
        return True
    return lmean > 0.0 and vol / (lmean ** 3) < 0.02


# 4-node tet sliver thresholds. Warn at the same shape limits that already
# condemn a /TETRA10 (aspect ratio > 8 or V/Lmean^3 < 0.02); drop only extreme
# cases — OpenRadioss *reads* sliver /TETRA4 fine, so dropping is justified only
# where the element is so degenerate that implicit contact crushes it to zero
# volume (stiffness vanishes -> AUTOSPC dimension-flip dt-cut loops, or element
# inversion polluting the energy balance).
_TET4_WARN_AR = 8.0
_TET4_WARN_NVOL = 0.02
_TET4_DROP_AR = 40.0
_TET4_DROP_NVOL = 0.001
_TET4_DROP_LMIN_FRAC = 0.05


def _tet4_sliver_class(state: ConversionState, nodes: List[int]) -> Optional[str]:
    """Classify a 4-node tet's corner shape for implicit runs.

    Returns "drop" for extreme slivers (aspect ratio > 40, V/Lmean^3 < 0.001,
    shortest edge < 5% of the mean edge, or degenerate/zero volume), "warn" for
    moderate slivers (the /TETRA10 limits: aspect ratio > 8 or V/Lmean^3 < 0.02),
    and None for sound elements or missing nodes.
    """
    m = _tet_corner_metrics(state, nodes)
    if m is None:
        return None
    lmin, lmax, lmean, vol = m
    if lmin <= 0.0 or lmean <= 0.0 or vol <= 0.0:
        return "drop"
    nvol = vol / (lmean ** 3)
    if (lmax / lmin > _TET4_DROP_AR or nvol < _TET4_DROP_NVOL
            or lmin < _TET4_DROP_LMIN_FRAC * lmean):
        return "drop"
    if lmax / lmin > _TET4_WARN_AR or nvol < _TET4_WARN_NVOL:
        return "warn"
    return None


def _fmt_eid_list(eids: List[int], limit: int = 25) -> str:
    """Comma-separated element IDs, truncated past *limit* with a count."""
    s = ", ".join(str(e) for e in eids[:limit])
    if len(eids) > limit:
        s += f", ... (+{len(eids) - limit} more)"
    return s


def _screen_sliver_tets(state: ConversionState) -> None:
    """Remove sliver tets from state.solid_elems before any section is built.

    Screening must mutate the element list (not just skip at write time): the
    free-node guard (_make_free_node_constraints) decides "attached to an
    element" from state.solid_elems, so a node referenced only by a dropped
    sliver must look free there to get its /BCS — otherwise it carries zero
    stiffness rows into the implicit tangent (singular matrix).

    Three screens run here:
      * Solids with fewer than 4 distinct nodes (collapsed to a point, edge,
        or triangle) are dropped unconditionally — they have exactly zero
        volume, and written as /BRICK the starter rejects the whole deck
        (ERROR 245: ZERO OR NEGATIVE 3D SOLID VOLUME).
      * 10-node tets failing _tet10_badly_shaped are dropped unconditionally —
        OpenRadioss refuses to read them as /TETRA10 (ERROR 489).
      * 4-node tets are screened for implicit decks only (explicit reads and
        runs slivers, merely slowly): extreme slivers are dropped, moderate
        ones kept but warned with their element list, since under contact
        pressure they crush flat — stiffness vanishes and the run stalls in
        AUTOSPC dimension-flip dt cuts or inverts and pollutes the energy.
    """
    bad_t10: Dict[int, int] = defaultdict(int)            # pid -> count
    null_solid: Dict[int, List[int]] = defaultdict(list)  # pid -> eids
    drop_t4: Dict[int, List[int]] = defaultdict(list)     # pid -> eids
    warn_t4: Dict[int, List[int]] = defaultdict(list)     # pid -> eids
    kept: List[SolidElem] = []
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            if _tet10_badly_shaped(state, e.nodes):
                bad_t10[e.pid] += 1
                continue
        else:
            uniq = _ordered_unique_nodes(e.nodes)
            if len(uniq) < 4:
                null_solid[e.pid].append(e.eid)
                continue
            if state.is_implicit and len(uniq) == 4:
                shape = _tet4_sliver_class(state, uniq)
                if shape == "drop":
                    drop_t4[e.pid].append(e.eid)
                    continue
                if shape == "warn":
                    warn_t4[e.pid].append(e.eid)
        kept.append(e)
    state.solid_elems = kept

    for pid, eids in sorted(null_solid.items()):
        state.warn(
            f"PART {pid}: dropped {len(eids)} degenerate solid(s) with fewer "
            "than 4 distinct nodes (collapsed to a point, edge, or triangle — "
            "exactly zero volume). Emitted as /BRICK the OpenRadioss starter "
            "rejects the whole deck (ERROR 245: zero or negative 3D solid "
            "volume). They carry no volume, mass, or stiffness, so dropping "
            "them is physically negligible; on implicit decks any node left "
            "unattached is constrained by the free-node guard. "
            f"Dropped element(s): {_fmt_eid_list(eids)}"
        )
    for pid, n in sorted(bad_t10.items()):
        state.warn(
            f"PART {pid}: dropped {n} near-degenerate (sliver) 10-node "
            "tet(s) that OpenRadioss rejects as /TETRA10 (ERROR 489: badly "
            "shaped). Their volume is ~0 so the physical effect is negligible; "
            "clean/remesh them to retain the full element count."
        )
    for pid, eids in sorted(drop_t4.items()):
        state.warn(
            f"PART {pid}: dropped {len(eids)} extreme-sliver 4-node tet(s) "
            f"(aspect ratio > {_TET4_DROP_AR:g}, V/Lmean^3 < {_TET4_DROP_NVOL:g}, "
            f"or shortest edge < {_TET4_DROP_LMIN_FRAC:.0%} of the mean edge). "
            "Under implicit contact load such slivers crush to zero volume — "
            "their stiffness vanishes and the run stalls in AUTOSPC "
            "dimension-flip dt cuts or inverts and pollutes the energy balance. "
            "Their volume is ~0 so dropping them is physically negligible; any "
            "node left unattached is constrained by the free-node guard. "
            f"Dropped element(s): {_fmt_eid_list(eids)}"
        )
    for pid, eids in sorted(warn_t4.items()):
        state.warn(
            f"PART {pid}: {len(eids)} sliver 4-node tet(s) kept (aspect ratio "
            f"> {_TET4_WARN_AR:g} or V/Lmean^3 < {_TET4_WARN_NVOL:g}). They may "
            "hinder implicit convergence under load; consider remeshing. "
            f"Element(s): {_fmt_eid_list(eids)}"
        )


def _referenced_node_ids(state: ConversionState) -> Set[int]:
    """Every node id still referenced by a retained entity — elements, node sets,
    beams, initial velocities, added masses, coordinate-node systems, pressure
    loads, and NODE time-histories. Used to find nodes orphaned by a mesh
    transform so they can be dropped without breaking any reference."""
    ref: Set[int] = set()
    for e in state.shell_elems:
        ref.update(n for n in e.nodes if n > 0)
    for e in state.solid_elems:
        ref.update(n for n in e.nodes if n > 0)
    for e in state.beam_elems:
        ref.update(n for n in (e.n1, e.n2, e.n3) if n > 0)
    for _title, nids in state.node_sets.values():
        ref.update(n for n in nids if n > 0)
    for iv in state.inivel_nodes:
        if iv.nid > 0:
            ref.add(iv.nid)
    ref.update(n for n in state.added_node_masses if n > 0)
    for cn in state.coord_nodes.values():
        ref.update(n for n in (cn.n1, cn.n2, cn.n3) if n > 0)
    for pl in state.pressure_loads:
        ref.update(n for n in pl.nodes if n > 0)
    for h in state.db_histories:
        if h.db_type == "NODE":
            ref.update(n for n in h.ids if n > 0)
    return ref


def _downgrade_tet10_to_tet4(state: ConversionState) -> None:
    """Convert every 10-node quadratic tet to a 4-node linear tet (opt-in:
    --tet10-to-tet4). Keeps the 4 corner nodes (the writer then emits /TETRA4),
    drops the 6 mid-edge nodes, and removes those mid-edge nodes from /NODE when
    nothing else references them.

    A no-op when the option is off → byte-identical output. Linear tets are
    markedly stiffer and less accurate than quadratic ones (bending / near-
    incompressible locking), so this trades stress fidelity for a smaller, faster
    model — handy when only a TET10 source .k is available but a TET4 run is
    wanted. Contact surfaces (/SURF/PART/EXT) and the grounding-spring / Gapmin /
    Stfac stabilization are unaffected. Runs before _snap_tet10_midsides and
    _screen_sliver_tets so those prepasses operate on the linear mesh; Itetra10
    then turns off automatically (no 10-node solids remain).
    """
    if not state.options.tet10_to_tet4:
        return
    midedge: Set[int] = set()
    affected_pids: Set[int] = set()
    n_down = 0
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            midedge.update(n for n in e.nodes[4:10] if n > 0)
            e.nodes = e.nodes[:4]               # keep the 4 corners → /TETRA4
            affected_pids.add(e.pid)
            n_down += 1
    if n_down == 0:
        state.warn("--tet10-to-tet4: no 10-node tetrahedra found; mesh unchanged.")
        return

    # Mid-edge nodes are now in no element. Any that a NODE SET still references
    # must be pruned from that set, not kept: otherwise the node survives only to
    # carry the set's condition (e.g. a symmetry SPC from *BOUNDARY_PRESCRIBED_
    # MOTION_SET) AND, being element-less, the implicit free-node guard's /BCS —
    # two boundary conditions on one node, which OpenRadioss rejects as WARNING
    # 312 INCOMPATIBLE KINEMATIC CONDITIONS (seen as 6152 orphaned symmetry-plane
    # mid-edge nodes x 3 DOFs = 18456 on the elevator TET4 downgrade). The
    # surviving corner nodes on the same plane still carry the condition, so the
    # SPC is unchanged for the linear mesh. Genuinely-needed references (coord-node
    # systems, inivel, pressure, added mass, beams, node TH) keep the node — those
    # carry no second BCS, so the free-node guard constrains them harmlessly.
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(n for n in e.nodes if n > 0)
    for e in state.solid_elems:
        elem_nodes.update(n for n in e.nodes if n > 0)
    for e in state.beam_elems:
        elem_nodes.update(n for n in (e.n1, e.n2, e.n3) if n > 0)
    gone = {n for n in midedge if n not in elem_nodes}     # removed from the mesh

    n_pruned = 0
    n_sets_pruned = 0
    for nsid, (title, nids) in list(state.node_sets.items()):
        kept = [n for n in nids if n not in gone]
        if len(kept) != len(nids):
            n_pruned += len(nids) - len(kept)
            n_sets_pruned += 1
            state.node_sets[nsid] = (title, kept)

    referenced = _referenced_node_ids(state)
    dropped = [nid for nid in gone if nid not in referenced and nid in state.nodes]
    for nid in dropped:
        del state.nodes[nid]
    state.warn(
        f"--tet10-to-tet4: downgraded {n_down} /TETRA10 to /TETRA4 (kept the 4 "
        f"corner nodes, dropped {len(dropped)} now-unreferenced mid-edge node(s)) "
        f"on part(s) {sorted(affected_pids)}. Linear tets are stiffer and less "
        "accurate than quadratic tets (bending / near-incompressible locking) — "
        "expect coarser stress; remesh for production accuracy."
    )
    if n_pruned:
        state.warn(
            f"--tet10-to-tet4: removed {n_pruned} dropped mid-edge node(s) from "
            f"{n_sets_pruned} node set(s) so their SPC/BC now applies to the "
            "surviving corner nodes only (prevents orphan nodes carrying both a "
            "node-set BC and the implicit free-node /BCS — OpenRadioss WARNING 312)."
        )


def _make_parts_and_elements(state: ConversionState, progress=None) -> List[str]:
    if not state.parts:
        return []
    lines = ["#-  PARTS AND ELEMENTS:", HDR]

    # Progress is driven off the solid elements (the dominant count); a single
    # part can hold every tet, so the counter ticks inside the emission loops.
    _emitted = 0
    _total = max(1, len(state.solid_elems))
    _step = max(1, _total // 30)

    def _tick():
        nonlocal _emitted
        _emitted += 1
        if progress is not None and _emitted % _step == 0:
            progress(_emitted / _total)

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
            # Emit 4-node tetrahedra as proper /TETRA4. Writing a tet as an
            # 8-node /BRICK with collapsed nodes reintroduces spurious
            # hourglass modes (a real tet has none) -> the load energy goes
            # into zero-stress hourglassing and the stress is garbage on
            # tet-meshed parts (observed on implicit_hr-anlenkung: I-ENERGY
            # ~0.8 J vs EXT-WORK ~690 J, -99.9% energy error). 5-8 unique
            # nodes stay /BRICK (a wedge/pyramid as a degenerate hex is ok).
            # 10-node solids are quadratic tets -> /TETRA10 (all 10 nodes kept).
            # Degenerate (<4 distinct nodes, ERROR 245) and sliver screening
            # (tet10 always, tet4 for implicit) already ran in
            # _screen_sliver_tets, so every element here is emitted.
            tets = []     # (eid, [n1, n2, n3, n4])
            tets10 = []   # SolidElem with 10 nodes (quadratic tet)
            bricks = []   # SolidElem with >4 distinct nodes
            for e in solids_by_pid[pid]:
                if len(e.nodes) == 10:
                    tets10.append(e)
                    continue
                uniq = _ordered_unique_nodes(e.nodes)
                if len(uniq) == 4:
                    tets.append((e.eid, uniq))
                else:
                    bricks.append(e)
            if tets10 and (tets or bricks):
                state.warn(
                    f"PART {pid}: mixes 10-node tets with 4-node/brick solids. "
                    "OpenRadioss requires /TETRA10 to use a part_ID distinct from "
                    "/TETRA4 and /BRICK; emitted together under one /PART, which the "
                    "starter may reject — split the part by element type if so."
                )
            if tets:
                lines.append(f"/TETRA4/{pid}")
                for eid, nd in tets:
                    row = _i(eid)
                    for n in nd:
                        row += _i(n)
                    lines.append(row)
                    _tick()
                lines.append(HDR)
            if tets10:
                # /TETRA10: 2 lines per element — tetra_ID, then the 10 node IDs
                # (10 fixed-width fields). Node order matches LS-DYNA/Abaqus tet10.
                lines.append(f"/TETRA10/{pid}")
                for e in tets10:
                    lines.append(_i(e.eid))
                    lines.append("".join(_i(n) for n in e.nodes[:10]))
                    _tick()
                lines.append(HDR)
            if bricks:
                lines.append(f"/BRICK/{pid}")
                for e in bricks:
                    nodes = list(e.nodes)
                    if len(nodes) < 8:
                        nodes += [nodes[-1]] * (8 - len(nodes))
                    row = _i(e.eid)
                    for n in nodes[:8]:
                        row += _i(n)
                    lines.append(row)
                    _tick()
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

    # LS-DYNA *DATABASE_EXTENT_BINARY strflg>0 requests strain-tensor output (and
    # its tens digit selects the plastic-strain tensor — the user's strflg=11
    # means "strain + plastic strain"). OpenRadioss only computes/stores element
    # strains for post-processing when Istrain=1 in the property; with Istrain=0
    # the engine's /ANIM/.../TENS/STRAIN — and, for solids, /ANIM/ELEM/EPSP — come
    # out empty. So enable Istrain whenever the deck asks for strain output.
    # (The plastic-strain channels /ANIM/ELEM/EPSP + /ANIM/SHELL/EPSP are always
    # emitted in the engine, see _make_engine_output.)
    ext = state.db_extent_binary
    istrain = 1 if (ext and ext.strflg > 0) else 0

    missing_shells = set()
    missing_solids = set()
    missing_beams = set()

    part_secids = {p.pid: p.secid if p.secid > 0 else p.pid for p in state.parts.values()}

    # Sections whose parts carry 10-node tets need the quadratic Itetra10 flag set
    # in /PROP/SOLID so /TETRA10 elements use the quadratic formulation.
    tet10_secids: Set[int] = set()
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            sid = part_secids.get(e.pid)
            if sid:
                tet10_secids.add(sid)

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
            f"{_i(nip)}{_i(istrain)}{_f(sec.t1)}                   0                   0         0",
            HDR,
        ]
    for sec in sorted(state.sec_solids.values(), key=lambda s: s.secid):
        # ALE/Euler elements need an ALE-compatible solid formulation; the
        # full-integration Lagrangian Isolid 17 is rejected (ERROR 131/608
        # "INCOMPATIBLE ELEMENT TYPE WITH ALE/EULER FRAMEWORK"). Isolid 0 =
        # the default, which resolves to the co-located ALE brick (the value
        # used by the reference Drop_Container FSI deck).
        isolid = 0 if sec.iale else _elform_to_isolid(sec.elform)
        # /PROP/SOLID card 1 (cfg radioss2022): Isolid Ismstr Iale Icpre Itetra10
        # Inpts Itetra4 Iframe Dn — note the Iale column at 21-30 (the 2022 PDF
        # p.1738 omits it; writing the PDF's 8-field layout shifts Itetra10 into
        # Icpre and silently drops it). Itetra10=1000 = quadratic /TETRA10 with
        # 4 integration points, for parts that have 10-node tets; 0 otherwise
        # (ignored by /TETRA4/brick). Do NOT use Itetra10=2 (same formulation
        # plus a /TETRA4-equivalent time step): its internal mid-side-node
        # treatment makes the starter reject any deck where kinematic
        # conditions (/RBODY, /BCS, CNRB...) touch tet10 nodes — ERROR 1216
        # "CONFLICT OF TETRA10&ITET=2 WITH KINEMATIC CONDITIONS" — and the
        # time-step benefit only matters for explicit runs anyway.
        itetra10 = 1000 if sec.secid in tet10_secids else 0
        lines += [
            f"/PROP/SOLID/{sec.secid}",
            sec.title or f"PROP_{sec.secid}",
            "#   Isolid    Ismstr      Iale     Icpre  Itetra10     Inpts   Itetra4    Iframe                  Dn",
            f"{_i(isolid)}         0{_i(sec.iale)}         0{_i(itetra10)}         0         0         0",
            "#                q_a                 q_b                   h            LAMBDA_V                MU_V",
            "                   0                   0                   0                   0                   0",
            "#             dt_min   istrain      IHKT",
            f"                   0{_i(istrain)}         0",
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


def _contact_master_pids(state: ConversionState, sid: int, styp: int) -> Set[int]:
    """Part IDs a contact MAIN side (sid/styp) resolves to (same rules as
    _resolve_contact_master)."""
    pids: Set[int] = set()
    if styp == 3:
        pids.add(sid)
    elif styp == 2:
        if sid in state.part_sets:
            pids.update(state.part_sets[sid][1])
    elif styp in (0, 1):
        if sid in state.parts:
            pids.add(sid)
        elif sid in state.part_sets:
            pids.update(state.part_sets[sid][1])
    return pids


def _solid_contact_master_pids(state: ConversionState) -> Set[int]:
    """Solid PIDs that appear on the MAIN side of some contact interface.

    These are emitted as a /SURF/PART/EXT (the external surface of a solid part).
    See _warn_implicit_solid_contact_np1 for why that matters in implicit np>1.
    """
    all_solid_pids = {e.pid for e in state.solid_elems}
    if not all_solid_pids:
        return set()
    out: Set[int] = set()
    for c in state.contacts_single:
        if c.ssid == 0:
            out |= all_solid_pids                      # all-parts self-contact
        else:
            out |= _contact_master_pids(state, c.ssid, c.sstyp) & all_solid_pids
    for c in state.contacts_surf2surf:
        out |= _contact_master_pids(state, c.msid, c.mstyp) & all_solid_pids
    return out


def _warn_implicit_solid_contact_np1(state: ConversionState) -> None:
    """Warn that an implicit deck with a solid-part contact surface must be run
    single-domain (np=1).

    The OpenRadioss SPMD engine segfaults (MESSAGE ID 44 / Segmentation
    Violation) at the FIRST implicit solve when this kind of model is run
    multi-domain (np>1).  It was verified (elevator-linkage, MUMPS 5.5.1) that
    the crash is in the distributed implicit solve, NOT in the contact surface:
    the identical model crashes the same way whether the contact MAIN is the
    solid's /SURF/PART/EXT or a /SURF/GRSHEL of an equivalent null-shell skin,
    and it reaches CYCLE 0 (past all surface/contact setup) before dying.  np=1
    is unaffected.  This is an upstream engine limitation we cannot rewrite the
    deck around, so flag it loudly.
    """
    if not state.is_implicit:
        return
    solid_pids = _solid_contact_master_pids(state)
    if not solid_pids:
        return
    state.warn(
        "Implicit deck with a solid-part contact surface (parts "
        f"{sorted(solid_pids)}): the OpenRadioss SPMD engine segfaults "
        "(MESSAGE ID 44, Segmentation Violation) at the first implicit solve "
        "when run multi-domain. RUN THIS DECK WITH np=1 (one MPI domain) -- the "
        "starter and the np=1 engine are unaffected. This is an upstream "
        "OpenRadioss engine limitation: the crash is in the distributed implicit "
        "solve, independent of the contact-surface representation (verified with "
        "both /SURF/PART/EXT and a /SURF/GRSHEL null-shell skin), so the "
        "converter cannot rewrite the deck around it."
    )


def _side_has_deformable_part(state: ConversionState, pids: Set[int]) -> bool:
    """True if *pids* is non-empty and contains at least one deformable part.
    A part is rigid iff its material is a *MAT_RIGID (mid in state.mat_rigid)."""
    return any(
        p in state.parts and state.parts[p].mid not in state.mat_rigid
        for p in pids
    )


def deformable_deformable_inter_ids(state: ConversionState) -> List[int]:
    """Interface IDs of surface-to-surface contacts that are deformable-vs-
    deformable: both sides resolve to deformable (non-rigid) parts and the two
    sides are distinct parts (a genuine deformable pair — not a rigid-backed
    contact, not pure self-contact).

    These are the interfaces prone to the active-set chatter + force-control
    soft-mode step-overshoot that stall the implicit solve, and the ones the
    opt-in deformable-contact recipe stabilizes (Inacti=5 here, plus the global
    /IMPL/DT/2 L_dtn=50 and /IMPL/QSTAT/DTSCAL=0.05). See
    _warn_deformable_deformable_contact.
    """
    out: List[int] = []
    for c in state.contacts_surf2surf:
        sp = _contact_master_pids(state, c.ssid, c.sstyp)   # generic sid/styp→pids
        mp = _contact_master_pids(state, c.msid, c.mstyp)
        if not sp or not mp or sp == mp:
            continue
        if _side_has_deformable_part(state, sp) and _side_has_deformable_part(state, mp):
            out.append(c.inter_id)
    return out


def _recipe_active(state: ConversionState) -> bool:
    """True when the opt-in deformable-contact recipe should actually be emitted:
    the flag is set, the deck is implicit, AND it really has a deformable-vs-
    deformable interface. Off, or on a deck without such contact, the recipe is a
    no-op (so the engine globals L_dtn/QSTAT and the per-interface Inacti are all
    unchanged) — turning the flag on never alters an unrelated deck."""
    return (state.options.deformable_contact_recipe
            and state.is_implicit
            and bool(deformable_deformable_inter_ids(state)))


def _warn_deformable_deformable_contact(state: ConversionState) -> None:
    """Flag implicit deformable-vs-deformable contact, and either point to the
    opt-in stabilization recipe or confirm it was applied.

    Such a contact is prone to two stalls the default deck does not survive:
    an active-set chatter (a sub-mesh-scale Gapmin flips contact nodes in/out
    each Newton iteration) and a force-control soft-mode step-overshoot
    2-cycle. The converter does NOT silently apply the heavier stabilization
    those decks need — it flags the interface(s) and points to the opt-in
    recipe (--deformable-contact-recipe / the GUI checkbox). With the recipe on
    it instead confirms exactly what was applied.
    """
    if not state.is_implicit:
        return
    ids = deformable_deformable_inter_ids(state)
    if not ids:
        return
    if state.options.deformable_contact_recipe:
        state.warn(
            f"Deformable-deformable contact recipe APPLIED to interface(s) {ids}: "
            "/INTER/TYPE7 Inacti=5 (mesh-scale engagement gap, no t=0 force "
            "spike), /IMPL/DT/2 L_dtn=50 (iteration cap for the slow linear "
            "contact-force convergence), and /IMPL/QSTAT/DTSCAL=0.05 (anchors "
            "the force-control soft mode). Validated to run a 6 kN force-control "
            "pull through a clearance-fit deformable pin to full load. The "
            "interface keeps its mesh-scale Card-3 SST/MST Gapmin — even with "
            "--auto-gapmin on, the recipe protects it from being shrunk."
        )
    else:
        state.warn(
            f"Deformable-deformable contact detected on interface(s) {ids} in an "
            "implicit deck. This is prone to an active-set chatter and a force-"
            "control soft-mode step-overshoot that stall the implicit solve with "
            "the default L_dtn=20 cap / QSTAT/DTSCAL=0.1. If the solve diverges "
            "or stalls, re-convert with the known working recipe: "
            "--deformable-contact-recipe (GUI: 'Deformable-deformable contact "
            "recipe') = Inacti=5 + L_dtn=50 + QSTAT/DTSCAL=0.05 with a mesh-scale "
            "(Card-3 SST/MST) Gapmin."
        )


def _gapmin_override(state: ConversionState, inter_id: int, base: float,
                     requested: Dict[int, float]) -> float:
    """Apply a --inter-gapmin override to *base* for *inter_id*, consuming the
    entry from *requested* (leftovers are warned about as unknown ids).

    Dropping a pulled clearance-fit interface's Gapmin below its nodal clearance
    so it starts with 0 initial penetrations is the key fix for the contact
    limit cycle: pre-engaged nodes on the releasing side otherwise flip-flop in
    and out of the penalty gap and the force residual never converges (open item
    0 / durable lesson #3)."""
    if inter_id in requested:
        val = requested.pop(inter_id)
        state.warn(
            f"INTER {inter_id}: Gapmin overridden {base:g} -> {val:g} via "
            "--inter-gapmin (drop a pulled clearance-fit interface below its "
            "nodal clearance so it has 0 initial penetrations and engages "
            "cleanly under load — avoids the pre-engaged-node contact limit cycle)."
        )
        return val
    return base


def _sfs_to_stfac(sfs: float, state: ConversionState, inter_id: int) -> float:
    """Map LS-DYNA *CONTACT Card 3 SFS (slave penalty stiffness scale factor) →
    OpenRadioss /INTER/TYPE7 Stfac.

    LS-DYNA SFS default is 1.0 (0/blank also reset to 1.0) = "no scaling"; that
    maps to Stfac=0 (OpenRadioss auto — byte-identical to the converter's prior
    default). A deliberately non-unit SFS carries through as the interface
    stiffness scale: SFS<1 softens the penalty (e.g. 0.3 = the validated
    contact-chatter insurance for force control, durable lesson #10), SFS>1
    stiffens it. The global --soften-stfac flag, when set, overrides this.
    """
    if sfs <= 0.0 or sfs == 1.0:
        return 0.0
    state.warn(
        f"CONTACT {inter_id}: SFS={sfs:g} (Card-3 slave penalty stiffness scale) "
        f"-> /INTER/TYPE7 Stfac={sfs:g} (SFS=1.0/0/blank would leave the engine "
        "default Stfac=0)."
    )
    return sfs


def _stfac_for(state: ConversionState, sfs: float, inter_id: int) -> float:
    """Per-interface Stfac: the global --soften-stfac override if given, else the
    per-contact *CONTACT Card-3 SFS mapping."""
    if state.options.soften_stfac is not None:
        return state.options.soften_stfac
    return _sfs_to_stfac(sfs, state, inter_id)


def _make_interfaces(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    if not state.contacts_single and not state.contacts_surf2surf:
        return []
    lines = ["#-  INTERFACES:", HDR]

    # Stfac (penalty stiffness scale) is per-contact from *CONTACT Card-3 SFS
    # (_stfac_for / _sfs_to_stfac); --soften-stfac, when given, overrides it on
    # EVERY interface. Both leave Stfac=0 (engine auto) by default → the output
    # is byte-identical to before when neither is in play.
    if state.options.soften_stfac is not None:
        state.warn(
            f"--soften-stfac: Stfac={state.options.soften_stfac:g} forced on all "
            "/INTER/TYPE7 interfaces (overrides any *CONTACT Card-3 SFS). Softer "
            "penalty so threshold contact nodes transition smoothly instead of "
            "chattering; flag absent leaves Stfac from SFS (default 0 = engine auto)."
        )
    # --inter-gapmin ID=VAL: per-interface Gapmin overrides, consumed as applied.
    gapmin_overrides = dict(state.options.inter_gapmin)

    # Deformable-contact recipe (opt-in): force Inacti=5 (mesh-scale engagement
    # gap, no t=0 force spike) on each deformable-vs-deformable interface. This is
    # the per-interface half of the recipe; the global halves (/IMPL/DT/2 L_dtn=50
    # and /IMPL/QSTAT/DTSCAL=0.05) are emitted in the engine deck. See
    # _warn_deformable_deformable_contact.
    recipe_inacti_ids: Set[int] = (
        set(deformable_deformable_inter_ids(state)) if _recipe_active(state) else set()
    )

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
            gapmin = _gapmin_override(state, c.inter_id,
                                      _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id),
                                      gapmin_overrides)
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin),
                                       viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                       gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id))
        else:
            slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
            mast_surf = _resolve_contact_master(state, c.ssid, c.sstyp, lines)
            if slav_grnod and mast_surf:
                gapmin = _gapmin_override(state, c.inter_id,
                                          _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id),
                                          gapmin_overrides)
                lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                           _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin),
                                           viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                           gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id))

    for c in state.contacts_surf2surf:
        slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
        mast_surf = _resolve_contact_master(state, c.msid, c.mstyp, lines)
        if slav_grnod and mast_surf:
            gapmin = _gapmin_override(state, c.inter_id,
                                      _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id),
                                      gapmin_overrides)
            inacti = (5 if c.inter_id in recipe_inacti_ids
                      else _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin))
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                       inacti,
                                       viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                       gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id))

    for iid, val in sorted(gapmin_overrides.items()):
        state.warn(
            f"--inter-gapmin {iid}={val:g}: no /INTER/TYPE7/{iid} was emitted "
            "(unknown interface id) — override ignored. Use the id printed in the "
            ".rad (auto-assigned contacts are numbered from 90001 in definition "
            "order)."
        )

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Force transducers  (*CONTACT_FORCE_TRANSDUCER → /INTER/SUB)
# ─────────────────────────────────────────────────────────────────────────────

def _select_parent_interface(state: ConversionState) -> Optional[int]:
    """Pick a fallback parent /INTER for a /INTER/SUB sub-interface.

    A LS-DYNA force transducer is standalone, but /INTER/SUB must reference an
    existing parent interface. Prefer an all-parts single-surface contact (it
    covers any surface pair); otherwise fall back to the first contact defined.
    Used only when _match_parent_interface finds no surface-compatible parent.
    """
    for c in state.contacts_single:
        if c.ssid == 0:
            return c.inter_id
    if state.contacts_single:
        return state.contacts_single[0].inter_id
    if state.contacts_surf2surf:
        return state.contacts_surf2surf[0].inter_id
    return None


def _contact_slave_pids(state: ConversionState, sid: int, styp: int) -> Optional[Set[int]]:
    """Part IDs whose nodes form a contact secondary side, or None when the side
    is not part-resolvable (an explicit node set): None = cannot verify, treat
    as matching anything."""
    if styp == 4:
        return None
    if styp == 3:
        return {sid} if sid in state.parts else set()
    if styp == 2:
        ps = state.part_sets.get(sid)
        return set(ps[1]) if ps else set()
    if styp in (0, 1):
        if sid in state.parts:
            return {sid}
        if sid in state.part_sets:
            return set(state.part_sets[sid][1])
        if sid in state.node_sets:
            return None
    return set()


def _match_parent_interface(state: ConversionState, main_pids: Set[int],
                            sec_pids: Set[int]) -> Optional[int]:
    """First /INTER whose MAIN surface covers *main_pids* and whose secondary
    node group covers *sec_pids*.

    /INTER/SUB segments and nodes must be subsets of the parent interface's
    main surface / secondary group, or the starter dies with one ERROR 581 per
    foreign segment ("IS NOT A MAIN SEGMENT OF INTERFACE ID=n"). With several
    split per-pair contacts (e.g. bracket-self, bracket-pin, bracket-cyl) the
    old "first contact defined" fallback parented every transducer on whichever
    contact came first — only a transducer measuring that exact pair survived
    the starter. Matching by part coverage picks the right pair regardless of
    definition order, and supports several transducers with different parents.
    """
    candidates = []
    all_pids = set(state.parts.keys())
    for c in state.contacts_single:
        if c.ssid == 0:
            candidates.append((c.inter_id, all_pids, None))
        else:
            candidates.append((c.inter_id,
                               _contact_master_pids(state, c.ssid, c.sstyp),
                               _contact_slave_pids(state, c.ssid, c.sstyp)))
    for c in state.contacts_surf2surf:
        candidates.append((c.inter_id,
                           _contact_master_pids(state, c.msid, c.mstyp),
                           _contact_slave_pids(state, c.ssid, c.sstyp)))

    for inter_id, mast, slav in candidates:
        if main_pids and not (main_pids <= mast):
            continue
        if sec_pids and slav is not None and not (sec_pids <= slav):
            continue
        return inter_id
    return None


def _transducer_side_pids(state: ConversionState, sid: int, styp: int) -> List[int]:
    """Resolve a transducer SURFA/SURFB to part IDs.

    LS-DYNA surf type: 2 = part-set ID, 3 = part ID, 5 = all parts.
    """
    if styp == 5 or sid == 0:
        return sorted(state.parts.keys())
    if styp == 2:
        ps = state.part_sets.get(sid)
        return list(ps[1]) if ps else []
    return [sid] if sid in state.parts else []


def _part_node_ids(state: ConversionState, pids: List[int], exclude: Set[int]) -> List[int]:
    """All node IDs used by the given parts' elements, minus *exclude* (rigid nodes)."""
    pidset = set(pids)
    nodes: Set[int] = set()
    for e in state.shell_elems:
        if e.pid in pidset:
            nodes.update(n for n in e.nodes if n > 0)
    for e in state.solid_elems:
        if e.pid in pidset:
            nodes.update(n for n in e.nodes if n > 0)
    for e in state.beam_elems:
        if e.pid in pidset:
            nodes.update(n for n in (e.n1, e.n2) if n > 0)
    return sorted(nodes - exclude)


def _make_force_transducers(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """Emit a /INTER/SUB sub-interface for every *CONTACT_FORCE_TRANSDUCER.

    A force transducer is a measurement-only "contact": it reports the contact
    force already acting between two surfaces (from the model's real contacts)
    and adds NO stiffness of its own. The OpenRadioss equivalent is /INTER/SUB,
    a sub-interface of an existing parent /INTER that outputs the force applied
    by a secondary node group on a main surface.

    The (sub_id, title) pairs are recorded on state.th_sub_ids so a /TH/INTER
    block can be emitted to actually write the force to the time-history file.
    """
    if not state.force_transducers:
        return []

    fallback_parent = _select_parent_interface(state)
    lines: List[str] = ["#-  FORCE TRANSDUCERS (/INTER/SUB):", HDR]

    for ft in state.force_transducers:
        title = ft.title or f"FORCE_TRANSD_{ft.inter_id}"

        pids_a = _transducer_side_pids(state, ft.surfa, ft.satyp)
        pids_b = _transducer_side_pids(state, ft.surfb, ft.sbtyp)
        all_pids = [p for p in (pids_a + pids_b) if p in state.parts]

        # Secondary side = deformable parts' nodes (those that live in the parent's
        # secondary node group). Main side = the remaining (rigid) parts' segments.
        # If the split is not clean, fall back to LS-DYNA's convention that SURFA
        # is the secondary side and SURFB the main side.
        def_pids = [p for p in all_pids if state.parts[p].mid not in state.mat_rigid]
        rig_pids = [p for p in all_pids if state.parts[p].mid in state.mat_rigid]
        if def_pids and rig_pids:
            sec_pids, main_pids = def_pids, rig_pids
        else:
            sec_pids = [p for p in pids_a if p in state.parts] or all_pids
            main_pids = [p for p in pids_b if p in state.parts] or all_pids

        parent_id = _match_parent_interface(state, set(main_pids), set(sec_pids))
        if parent_id is None and fallback_parent is not None:
            parent_id = fallback_parent
            state.warn(
                f"CONTACT_FORCE_TRANSDUCER {ft.inter_id}: no contact interface "
                f"covers its surfaces (main parts {sorted(set(main_pids))}, "
                f"secondary parts {sorted(set(sec_pids))}); parenting /INTER/SUB "
                f"on /INTER {fallback_parent} — the starter may reject foreign "
                "segments (ERROR 581). Define a contact for this pair."
            )
        if parent_id is None:
            state.warn(
                f"CONTACT_FORCE_TRANSDUCER {ft.inter_id}: no existing /INTER to act "
                "as parent; /INTER/SUB requires a parent interface -> skipped."
            )
            continue

        sec_nodes = _part_node_ids(state, sec_pids, rigid_nodes)
        if not sec_nodes:
            state.warn(
                f"CONTACT_FORCE_TRANSDUCER {ft.inter_id}: secondary side has no "
                "deformable nodes (parts may be all-rigid) -> skipped."
            )
            continue

        grnod_id = state.next_id()
        main_surf = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"{title}_secnd", sec_nodes)
        if not _make_master_surface(state, main_surf, f"{title}_main",
                                    sorted(set(main_pids)), lines):
            state.warn(
                f"CONTACT_FORCE_TRANSDUCER {ft.inter_id}: could not build a main "
                "surface from its parts -> skipped."
            )
            continue

        # /INTER/SUB/sub_ID  →  parent inter_ID, main surface, secondary node group
        lines += [
            f"/INTER/SUB/{ft.inter_id}",
            title,
            "#  inter_ID  Main_surf  Secn_grnd",
            f"{_i(parent_id)}{_i(main_surf)}{_i(grnod_id)}",
            HDR,
        ]
        state.th_sub_ids.append((ft.inter_id, title))
        state.warn(
            f"CONTACT_FORCE_TRANSDUCER {ft.inter_id} -> /INTER/SUB/{ft.inter_id} "
            f"(parent /INTER {parent_id}); force written to T01 via /TH/INTER. "
            "Measurement-only (adds no contact stiffness)."
        )

    # Read-out caveat (emitted once when any transducer was written). OpenRadioss
    # stores contact interface / sub-interface forces in the T01 time-history as
    # impulse-scaled values, NOT true forces (upstream behavior, OpenRadioss
    # GitHub discussion #2451). A raw T01 read (or th_to_csv) therefore
    # under-reports the contact force — about HALF on the validated implicit deck,
    # where x2 recovered the applied load to ~1%. HyperView/HyperGraph convert it
    # correctly on read.
    if state.th_sub_ids:
        state.warn(
            "Force-transducer read-out: OpenRadioss writes contact (sub-)interface "
            "forces to the T01 time-history as impulse-scaled values, NOT true "
            "forces (upstream behavior — OpenRadioss GitHub discussion #2451). A "
            "raw T01 read / th_to_csv under-reports the contact load (~half on the "
            "validated implicit deck; x2 recovered the applied load to ~1%). Read "
            "the T01 in HyperView/HyperGraph (auto-converts), or take the load from "
            "the applied *LOAD_RIGID_BODY / reaction."
        )

    return lines


def _ignore_to_inacti(ignore: int, state: ConversionState, inter_id: int,
                      gapmin: float = 0.0) -> int:
    """Map LS-DYNA *CONTACT ignore → OpenRadioss /INTER/TYPE7 Inacti.

    LS-DYNA never applies a contact force to *initial* penetrations, whatever
    ignore is set to — ignore only selects HOW they are neutralized at
    initialization:

      * ignore=0 (default): MOVE the penetrating tracked nodes back to the
        surface, eliminating the penetration geometrically.
      * ignore=1/2: leave the nodes in place, *remember* the initial
        penetration, subtract it so it produces no force at t=0, but keep the
        contact fully ACTIVE for any subsequent (incremental) penetration.
        (ignore=2 = ignore=1 plus printed warnings.)

    The faithful OpenRadioss equivalent for both is **Inacti=5** (variable gap:
    the per-node gap is reduced to gap0 − P0 so the node starts just-touching
    with zero initial force and re-engages as soon as it moves further in).
    Mapping ignore=0 to Inacti=0 — the pre-2026-07 behavior — instead applies
    the FULL penalty force to every initially penetrated node at cycle 0: on
    W13_BlastVehicle z-ground (vehicle resting on the ground plane, 250 initial
    penetrations against a 41.7 mm starter-default gap) that pre-loaded
    3.4e10 mJ of elastic contact energy at t=0 and blew kinetic energy up 5
    orders of magnitude over the LS-DYNA reference before the blast wave even
    arrived. (Inacti=3 would mimic the ignore=0 node-moving literally, but
    moving rigid-body secondary nodes seg-faulted the engine during init —
    see below — so the no-node-motion Inacti=5 is used for ignore=0 too.)

    The ONE deliberate exception: an implicit deck that pre-engages the
    contact via SST/MST → Gapmin (or --inter-gapmin) keeps Inacti=0, because
    that documented bootstrap (see _sst_mst_to_gapmin) NEEDS the t=0 spring
    force as Newton's stiffness path at zero load.

    This corrects an earlier mapping to Inacti=1 (deactivate / zero the stiffness
    of penetrating secondary nodes). On `implicit_hr-anlenkung` that mapping was
    the load-path killer: a geometry pen-check (folder 6kN_claude-pencheck) showed
    there are NO geometric initial penetrations — the loading pin sits in its hole
    with ~0.105 mm clearance (≈ one shell thickness). The starter's "16 INITIAL
    PENETRATIONS" are a variable-gap artifact: the TYPE7 gap (~0.109 mm) slightly
    exceeds that clearance for the 16 closest pin nodes (penetration ~0.5–5 µm).
    Inacti=1 then ZEROES exactly those 16 nodes — the closest, most load-bearing
    nodes on the loaded (+y) face — so the rigid pin has no contact stiffness in
    the load direction at t=0, Newton can build no Y-reaction, and the solve hits
    an irreducible force residual with I-ENERGY ≡ 0 (every solver knob exhausted).

    Inacti=5 is both correct AND safe here:
      * It does NOT modify node coordinates, so it is safe for rigid-body
        secondary nodes (unlike Inacti=3/6, where moving 21 rigid-body nodes
        seg-faulted the engine during init).
      * Because the penetrations are sub-5-µm against a ~0.109 mm gap, the
        adjusted gap stays ~0.105 mm — i.e. the nodes keep essentially their full
        gap and remain active. (The old worry that "Inacti=5 silently suppresses
        contact" only applies when P0 ≈ gap0, i.e. deep penetration — not this
        case.)
    """
    if ignore in (1, 2):
        state.warn(
            f"CONTACT {inter_id}: ignore={ignore} mapped to /INTER/TYPE7 Inacti=5 "
            "(variable gap = gap0 - initial penetration; contact stays active, no "
            "t=0 force spike). Matches LS-DYNA 'ignore initial penetration' intent "
            "and keeps load-path nodes active (was Inacti=1, which deletes them)."
        )
        return 5
    if state.is_implicit and gapmin > 0.0:
        state.warn(
            f"CONTACT {inter_id}: ignore=0 with an explicit engagement Gapmin "
            f"({gapmin:g}) on an implicit deck -> Inacti=0 kept (pre-engagement "
            "bootstrap: the t=0 spring force is the Newton stiffness path). "
            "Set ignore=1 on *CONTACT if you want initial penetrations "
            "neutralized instead."
        )
        return 0
    state.warn(
        f"CONTACT {inter_id}: ignore=0 mapped to /INTER/TYPE7 Inacti=5. LS-DYNA "
        "removes initial penetrations at initialization (moves nodes; no t=0 "
        "force) — Inacti=0 would instead apply the full penalty force to every "
        "initially penetrated node at cycle 0 and can inject huge kinetic "
        "energy into a model that merely rests in contact."
    )
    return 5


def _vdc_to_viss(vdc: float, state: ConversionState, inter_id: int) -> float:
    """Map LS-DYNA *CONTACT Card2 vdc (viscous damping, % of critical) →
    OpenRadioss /INTER/TYPE7 VisS (fraction of critical, normal direction).

    Undamped penalty contact (VisS=0) in implicit dynamic analysis is prone to
    a chattering limit cycle: the active contact set flips every Newton
    iteration, |r|/|r0| never drops below 1, the solver bisects the timestep
    and kinetic energy blows up (observed on `implicit_hr-anlenkung`: with
    addmass=1 the run is clean to NC=42 / T=187 ms, then ND=5 contact chatters
    → K-energy 6e3 → 3e4 J while ext-work is frozen at 57 J). Carrying vdc
    through to VisS damps the contact-normal oscillation and lets Newton
    converge through the contact event.
    """
    if vdc and vdc > 0.0:
        viss = vdc / 100.0
        state.warn(f"CONTACT {inter_id}: vdc={vdc:g} (% critical) -> "
                   f"/INTER/TYPE7 VisS={viss:g} (normal contact damping).")
        return viss
    if state.is_implicit:
        state.warn(f"CONTACT {inter_id}: vdc=0 -> VisS=0 (no contact damping). "
                   "Implicit dynamic penalty contact often chatters without it; "
                   "set vdc (% of critical, e.g. 20-100) on *CONTACT Card2 if the "
                   "solve diverges with a kinetic-energy blow-up.")
    return 0.0


def _sst_mst_to_gapmin(sst: float, mst: float, state: ConversionState,
                       inter_id: int) -> float:
    """Map LS-DYNA *CONTACT Card3 SST/MST (optional contact thickness per side)
    → OpenRadioss /INTER/TYPE7 Gapmin.

    LS-DYNA offsets each contact surface by half its contact thickness, so the
    two sides engage at a separation of (SST + MST)/2.  TYPE7 (Igap=0,
    constant gap) engages at gap = max(Gapmin, property-derived default), so
    Gapmin = (SST + MST)/2 carries the .k file's per-contact engagement
    distance through.

    This is the .k-side knob for force control through a clearance fit: per
    PAIR interfaces, each with Gapmin just above that pair's clearance
    (+ ignore=0 → Inacti=0), pre-engage the contact so a stiffness path exists
    at zero load.  One global Gapmin > all clearances also bootstraps, but
    over-closes every pair by a different amount and bakes a load-independent
    press-fit stress into the model from t=0 — on `implicit_hr-anlenkung` that
    artifact was 20 % of the full-load strain energy at F≈0.6 N.

    LS-DYNA gives negative SST/MST a side meaning (the magnitude is the
    contact thickness; the sign suppresses thickness-projection details with
    no TYPE7 equivalent), so magnitudes are used and a warning issued.
    """
    if sst < 0.0 or mst < 0.0:
        state.warn(
            f"CONTACT {inter_id}: negative SST/MST ({sst:g}/{mst:g}) — using "
            "the magnitudes for the Gapmin mapping; the negative-thickness "
            "projection semantics have no /INTER/TYPE7 equivalent."
        )
    gapmin = (abs(sst) + abs(mst)) / 2.0
    if gapmin > 0.0:
        state.warn(
            f"CONTACT {inter_id}: SST/MST contact thickness -> /INTER/TYPE7 "
            f"Gapmin={gapmin:g} (engagement distance (SST+MST)/2). On an "
            "implicit deck, keep ignore=0 to retain Inacti=0 if Gapmin "
            "exceeds the physical clearance (pre-engagement bootstrap) — "
            "ignore=1/2 (and any explicit deck) maps to Inacti=5, which "
            "shrinks the gap back to the clearance and cancels the "
            "pre-engagement."
        )
    return gapmin


def _emit_inter_type7(inter_id: int, title: str, slav_id: int,
                      mast_id: int, fric: float, inacti: int = 0,
                      viss: float = 0.0, visf: float = 0.0,
                      gapmin: float = 0.0, stfac: float = 0.0) -> List[str]:
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
        f"{_f(stfac)}{_f(fric)}{_f(gapmin)}                   0                   0",
        "#      IBC                        Inacti                VisS                VisF              Bumult",
        f"       000{_i(inacti, 30)}{_f(viss)}{_f(visf)}                   0",
        "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID",
        "         0         0                   0         2         0",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: tied interfaces  (*CONTACT_TIED_* → /INTER/TYPE2)
# ─────────────────────────────────────────────────────────────────────────────

# LS-DYNA tied variant → /INTER/TYPE2 Spotflag. NODES_/SHELL_EDGE_TO_SURFACE
# welds get the spotweld formulation (Spotflag=1): the secondary node is joined
# to the main segment by a rigid link of constant stiffness, so the offset
# between a tied node and the main shell MID-PLANE (typically half the plate
# thickness) carries force and moment without exciting hourglass modes.
# SURFACE_TO_SURFACE is LS-DYNA's mesh-transition glue → the standard
# formulation (Spotflag=5).
_TIED_SPOTFLAG = {
    "NODES_TO_SURFACE":      1,
    "SHELL_EDGE_TO_SURFACE": 1,
    "SURFACE_TO_SURFACE":    5,
}

# dsearch margin over the measured worst node-to-segment gap: covers the exact
# half-thickness mid-plane offset plus mesh roundoff without reaching across to
# an unrelated segment one element away.
_TIED_DSEARCH_MARGIN = 1.2


def _emit_inter_type2(inter_id: int, title: str, grnod_id: int, surf_id: int,
                      spotflag: int, dsearch: float) -> List[str]:
    """/INTER/TYPE2 card (FORMAT radioss2017 — unchanged through /BEGIN 2022):
    grnd_IDs surf_IDm Ignore Spotflag Level Isearch Idel2 <blank10> dsearch(20).

    Ignore=2: secondary nodes with no main segment within dsearch are removed
    from the tie by the starter (and printed), and a dsearch of 0 is replaced
    by the starter's average-main-segment-size default. Isearch=2 = improved
    closest-segment search. Idel2=0 = engine default (no deletion).
    """
    return [
        f"/INTER/TYPE2/{inter_id}",
        title or f"TIED_CONTACT_{inter_id}",
        "#  Grnd_id   Surf_id    Ignore  Spotflag     Level   Isearch     Idel2                       dsearch",
        f"{_i(grnod_id)}{_i(surf_id)}{_i(2)}{_i(spotflag)}{_i(0)}{_i(2)}{_i(0)}          {_f(dsearch)}",
        HDR,
    ]


def _tied_slave_nids(state: ConversionState, sid: int, styp: int) -> List[int]:
    """Node ids of a tied-contact slave side. SSTYP 4 = node set, 3 = part,
    2 = part set, 0 = segment set (the nodes of its segments); 0/1 fall back to
    part / part-set / node-set lookups like the penalty-contact resolver."""
    nids: Set[int] = set()

    def add_part_nodes(pid: int) -> None:
        for e in state.shell_elems:
            if e.pid == pid:
                nids.update(e.nodes)
        for e in state.solid_elems:
            if e.pid == pid:
                nids.update(e.nodes)

    if styp == 4:
        if sid in state.node_sets:
            nids.update(state.node_sets[sid][1])
    elif styp == 3:
        add_part_nodes(sid)
    elif styp == 2:
        if sid in state.part_sets:
            for pid in state.part_sets[sid][1]:
                add_part_nodes(pid)
    elif styp in (0, 1):
        if sid in state.segment_sets:
            for seg in state.segment_sets[sid].segments:
                nids.update(seg)
        elif sid in state.parts:
            add_part_nodes(sid)
        elif sid in state.part_sets:
            for pid in state.part_sets[sid][1]:
                add_part_nodes(pid)
        elif sid in state.node_sets:
            nids.update(state.node_sets[sid][1])
    return sorted(n for n in nids if n > 0)


def _tied_master_surface(state: ConversionState, c, out_lines: List[str]):
    """Emit the main /SURF of a tied contact; returns (surf_id, verts, faces)
    where verts/faces are the surface triangles used to measure the tied gap
    (empty when the geometry is unknown). MSTYP 0 = *SET_SEGMENT → /SURF/SEG;
    3 = part, 2 = part set → the part surface (0/1 fall back to parts too)."""
    from .gapmin import _segment_triangles, _surface_triangles
    if c.mstyp in (0, 1) and c.msid in state.segment_sets:
        ss = state.segment_sets[c.msid]
        if not ss.segments:
            return 0, [], []
        surf_id = state.next_id()
        out_lines += _emit_surf_seg(surf_id, ss.title or f"tied_{c.inter_id}_master",
                                    ss.segments)
        verts, faces = _segment_triangles(state, ss.segments)
        return surf_id, verts, faces
    pids = sorted(_contact_master_pids(state, c.msid, c.mstyp))
    if not pids:
        return 0, [], []
    surf_id = state.next_id()
    if not _make_master_surface(state, surf_id, f"tied_{c.inter_id}_master",
                                pids, out_lines):
        return 0, [], []
    verts, faces = _surface_triangles(state, pids)
    return surf_id, verts, faces


def _tied_dsearch(state: ConversionState, c, slave_nids: List[int],
                  verts, faces) -> float:
    """/INTER/TYPE2 dsearch for one tied contact: the measured WORST secondary
    node-to-main-segment distance × a small margin, so every tied node finds
    its segment even when the main side is a shell whose segments sit on the
    MID-PLANE half a thickness away from the physically-touching tied nodes.

    A negative LS-DYNA Card-3 SST/MST (absolute tie-criterion distance) is
    honoured as a floor. 0 is returned when the gap cannot be measured —
    Ignore=2 then makes the starter default dsearch to the average main
    segment size."""
    from .gapmin import _coords_for, _round_sig, max_node_to_triangles
    floor = max(-c.sst if c.sst < 0.0 else 0.0,
                -c.mst if c.mst < 0.0 else 0.0)
    gap = max_node_to_triangles(_coords_for(state, slave_nids), verts, faces)
    if gap is None:
        if floor > 0.0:
            state.warn(
                f"TIED CONTACT {c.inter_id}: node-to-segment gap not measurable "
                f"(missing coordinates) — dsearch={floor:g} taken from the "
                "negative Card-3 SST/MST absolute tie distance."
            )
            return floor
        state.warn(
            f"TIED CONTACT {c.inter_id}: node-to-segment gap not measurable "
            "(missing coordinates) — dsearch left 0, so the starter defaults it "
            "to the average main-segment size (Ignore=2). If tied nodes sit "
            "further than that from the main shell mid-plane, the starter "
            "deletes them from the tie (they are printed in the starter output)."
        )
        return 0.0
    dsearch = _round_sig(max(gap * _TIED_DSEARCH_MARGIN, floor), 4)
    if dsearch > 0.0:
        state.warn(
            f"TIED CONTACT {c.inter_id}: worst secondary-node-to-main-segment "
            f"distance is {gap:g} (a mid-plane offset of ~half the main shell "
            f"thickness is expected for shell welds) -> /INTER/TYPE2 "
            f"dsearch={dsearch:g} so every tied node finds its main segment. "
            "Nodes beyond dsearch would be dropped from the tie by the starter "
            "(Ignore=2)."
        )
    return dsearch


def _make_tied_interfaces(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """*CONTACT_TIED_* → /INTER/TYPE2 (+ /GRNOD secondary side, /SURF main side)."""
    if not state.contacts_tied:
        return []
    lines = ["#-  TIED INTERFACES (*CONTACT_TIED_* -> /INTER/TYPE2):", HDR]
    for c in state.contacts_tied:
        nids = _tied_slave_nids(state, c.ssid, c.sstyp)
        clean = [n for n in nids if n not in rigid_nodes]
        if len(clean) < len(nids):
            state.warn(
                f"TIED CONTACT {c.inter_id}: {len(nids) - len(clean)} secondary "
                "node(s) belong to a rigid body and were removed from the tie "
                "(/INTER/TYPE2 is a kinematic condition — it cannot share a "
                "node with /RBODY)."
            )
        if not clean:
            state.warn(
                f"TIED CONTACT {c.inter_id} (*CONTACT_TIED_{c.variant}): slave "
                f"side ssid={c.ssid} sstyp={c.sstyp} resolved to no nodes — "
                "interface skipped."
            )
            continue
        master_lines: List[str] = []
        surf_id, verts, faces = _tied_master_surface(state, c, master_lines)
        if not surf_id:
            state.warn(
                f"TIED CONTACT {c.inter_id} (*CONTACT_TIED_{c.variant}): master "
                f"side msid={c.msid} mstyp={c.mstyp} resolved to no surface — "
                "interface skipped."
            )
            continue
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"tied_{c.inter_id}_slave", clean)
        lines += master_lines
        dsearch = _tied_dsearch(state, c, clean, verts, faces)
        spotflag = _TIED_SPOTFLAG.get(c.variant, 1)
        lines += _emit_inter_type2(c.inter_id, c.title, grnod_id, surf_id,
                                   spotflag, dsearch)
        rot_note = (
            " Note: TYPE2 also ties the secondary nodes' ROTATIONS to the main "
            "segment (a moment-carrying weld); the LS-DYNA keyword tied "
            "translations only." if c.variant != "SHELL_EDGE_TO_SURFACE" else ""
        )
        state.warn(
            f"*CONTACT_TIED_{c.variant}{'_OFFSET' if c.offset else ''} "
            f"{c.inter_id} -> /INTER/TYPE2/{c.inter_id} (tied kinematic "
            f"interface, Spotflag={spotflag}, {len(clean)} secondary nodes)."
            + rot_note
        )
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: grounding springs  (force-control bootstrap stabilization)
# ─────────────────────────────────────────────────────────────────────────────

# *LOAD_RIGID_BODY translational DOF (1=Fx,2=Fy,3=Fz) → global axis index.
_FORCE_DOF_AXIS = {1: 0, 2: 1, 3: 2}


def _emit_spr_gene_dof(k: float) -> List[str]:
    """The 3 data lines of one /PROP/TYPE8 (SPR_GENE) DOF: a linear spring with
    only the stiffness K set (C=A=B=D=0, no function, no failure).

    Layout verified against the OpenRadioss source + hm_cfg and a validated run
    (add_grounding_springs.py): the reader forces A=1,B=0 and ±1e30 failure
    displacements when no function is given, so only K matters here.
    """
    return [
        "#                 K                   C                   A                   B                   D",
        f"{_f(k)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#  fct_ID1         H   fct_ID2   fct_ID3   fct_ID4                      DeltaMin            DeltaMax",
        f"{_i(0) * 5}          {_f(0.0)}{_f(0.0)}",
        "#                 F                   E              Ascale              Hscale",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
    ]


def _make_grounding_springs(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Inject soft /PROP/TYPE8 grounding springs on force-loaded rigid bodies
    (opt-in: --ground-springs). Returns [] when off → byte-identical output.

    A *LOAD_RIGID_BODY that pulls a rigid body held to ground only by
    clearance-fit penalty contact has a singular tangent in the loaded DOFs at
    t=0 (a rigid-body mode → MUMPS zero pivot / frozen residual; force control
    cannot bootstrap because load≈0 → the gap never closes → no stiffness). The
    Altair-documented fix (User Guide p.483) is a weak artificial spring on the
    free loaded DOFs: it removes the singular mode yet stays soft enough that
    contact carries the load once engaged (spring reaction ≈ k·u — a few % of
    the applied force at k=100 N/mm). Displacement control sidesteps this by
    imposing the motion; force control does not. See durable lesson #3.

    One zero-length SPR_GENE spring per loaded rigid body, from its /RBODY
    master node to a new fully-fixed ground node at the same location, with K on
    each loaded translational axis. A soft K on a DOF that is otherwise /BCS-
    constrained is inert, so spring-on-loaded-axes is safe and reproduces the
    validated RB_pull result (free Y+Z carry the pull; X stays fixed).
    """
    if not state.options.ground_springs or not state.load_rigid_bodies:
        return []

    # Union the loaded translational axes per rigid-body part (a |F| load, dof
    # 4, grounds all three; moments dof 5/6/7 are not sprung).
    axes_by_pid: Dict[int, Set[int]] = defaultdict(set)
    for lb in state.load_rigid_bodies:
        if lb.dof == 4:
            axes_by_pid[lb.pid] |= {0, 1, 2}
        elif lb.dof in _FORCE_DOF_AXIS:
            axes_by_pid[lb.pid].add(_FORCE_DOF_AXIS[lb.dof])

    if not axes_by_pid:
        return []

    k = state.options.ground_spring_k
    lines: List[str] = [
        "#-  GROUNDING SPRINGS (force-control bootstrap stabilization):", HDR]
    next_ground_node = (max(state.nodes) if state.nodes else 0) + 1
    emitted = False

    for pid, axes in sorted(axes_by_pid.items()):
        info = rbody_info.get(pid)
        if info is None:
            state.warn(
                f"--ground-springs: *LOAD_RIGID_BODY pid={pid} has no rigid body "
                "(no /RBODY master node) — grounding spring skipped."
            )
            continue
        master = info["ind_node"]
        nd = state.nodes.get(master)
        if nd is None:
            state.warn(
                f"--ground-springs: rigid body pid={pid} master node {master} has "
                "no coordinates — grounding spring skipped."
            )
            continue

        ground_node = next_ground_node
        next_ground_node += 1
        grnod_id = state.next_id()
        bcs_id = state.next_id()
        prop_id = state.next_id()
        part_id = state.next_id()
        elem_id = state.next_id()
        kx = k if 0 in axes else 0.0
        ky = k if 1 in axes else 0.0
        kz = k if 2 in axes else 0.0
        axis_names = ",".join(
            n for n, on in zip("XYZ", (0 in axes, 1 in axes, 2 in axes)) if on)

        lines += [
            f"#-- master node {master}, axes {axis_names}, K={k:g} N/mm per loaded axis",
            "/NODE",
            f"{_i(ground_node)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}",
            f"/GRNOD/NODE/{grnod_id}",
            f"spring_ground_pid{pid}",
            f"{_i(ground_node)}",
            f"/BCS/{bcs_id}",
            f"fix_spring_ground_pid{pid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   111 111         0{_i(grnod_id)}",
            f"/PROP/TYPE8/{prop_id}",
            f"soft_ground_spring_pid{pid}",
            "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
            f"{_f(1.0e-4)}{_f(1.0e-6)}{_i(0) * 6}",
        ]
        # 6 DOF blocks: X Y Z RX RY RZ — K only on the loaded translational axes.
        lines += (_emit_spr_gene_dof(kx) + _emit_spr_gene_dof(ky) + _emit_spr_gene_dof(kz)
                  + _emit_spr_gene_dof(0.0) + _emit_spr_gene_dof(0.0) + _emit_spr_gene_dof(0.0))
        # Trailing strain-rate card (Fsmooth/Fcut). FORMAT(radioss2018) — the newest
        # SPR_GENE reader cfg ≤ /BEGIN-2022 — closes the /PROP/TYPE8 block with one
        # more "%10d%20lg" card (ISRATE, Asrate). Omitting it makes the reader run
        # past the property into the following /PART and raise WARNING 100217
        # ("card is missing"). Strain-rate smoothing off (ISRATE=0) → Asrate inert.
        lines += [
            "#  Fsmooth                Fcut",
            f"{_i(0)}{_f(0.0)}",
        ]
        lines += [
            f"/PART/{part_id}",
            f"soft_ground_spring_part_pid{pid}",
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{part_id}",
            "# sprg_ID  node_ID1  node_ID2",
            f"{_i(elem_id)}{_i(master)}{_i(ground_node)}",
            HDR,
        ]
        emitted = True
        state.warn(
            f"--ground-springs: injected a /PROP/TYPE8 grounding spring (K={k:g} "
            f"N/mm on axis/axes {axis_names}) from rigid-body pid={pid} master "
            f"node {master} to new fixed ground node {ground_node}. Removes the "
            "t=0 rigid-body singularity in the loaded DOFs; carries negligible "
            "load once contact engages. Remove if this is not force control "
            "through a clearance-fit contact."
        )

    return lines if emitted else []


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
                f"*MAT_RIGID pid={pid}: --rigid-cog-master synthesized "
                f"element-free /RBODY master node {ind_node} at the part's "
                "nodal centroid (mesh nodes keep their coordinates; loads/"
                "readouts on the rigid body now address this node).")
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

    return lines, rigid_nodes, rbody_info


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

    return lines, rigid_nodes, rbody_info


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

        # Impose the motion on the rigid body's PRIMARY (master) node only, NOT on
        # every node of the rigid part. The secondary nodes are slaved by /RBODY;
        # adding /IMPDISP on them creates "incompatible kinematic conditions"
        # (Starter WARNING ID 312) which OpenRadioss resolves in favour of the
        # rigid body — silently dropping the imposed motion so the part never moves
        # (zero reaction → zero strain energy → zero stress). Driving the master
        # node (the same node the rigid-body /BCS constrains) translates the whole
        # body correctly.
        grnod_id = info["ind_grnod_id"]
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
# Starter: imposed motions for node sets
# ─────────────────────────────────────────────────────────────────────────────

# LS-DYNA *BOUNDARY_PRESCRIBED_MOTION DOF → (translation, rotation) /BCS codes.
# 1/2/3 = Tx/Ty/Tz, 5/6/7 = Rx/Ry/Rz. DOF 4 (translation along vector VID) and
# 8 (rotation about VID) have no global X/Y/Z /BCS code and are not mapped here.
_PM_DOF_TO_BCS = {
    1: ("100", "000"), 2: ("010", "000"), 3: ("001", "000"),
    5: ("000", "100"), 6: ("000", "010"), 7: ("000", "001"),
}


def _or_dof_codes(codes: List[str]) -> str:
    """OR a list of 3-char DOF codes, e.g. ['100','001'] → '101'."""
    out = ["0", "0", "0"]
    for c in codes:
        for i in range(3):
            if c[i] == "1":
                out[i] = "1"
    return "".join(out)


def _make_imposed_motions_set(state: ConversionState) -> List[str]:
    lines: List[str] = []
    if not state.prescribed_motion_sets:
        return lines

    # LS-DYNA convention: *BOUNDARY_PRESCRIBED_MOTION_SET with sf=0 means "fix this
    # DOF" (zero x any_curve = 0 displacement = fixed). Emit a /BCS (constraint)
    # instead of an /IMPDISP with a bogus unit scale — critical for symmetry BCs
    # (treated as IMPDISP with sf=1 the plane nodes would get spurious motion and
    # the stiffness matrix would go singular). All fixed DOFs of one node set are
    # combined into ONE /BCS (OpenRadioss applies the union) rather than one card
    # per DOF — fewer cards and no dependence on whether multiple /BCS stack.
    fix_tra: Dict[int, List[str]] = defaultdict(list)
    fix_rot: Dict[int, List[str]] = defaultdict(list)
    fix_order: List[int] = []
    motions: List = []
    for pm in state.prescribed_motion_sets:
        if pm.nsid not in state.node_sets:
            state.warn(f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: node set not found – skipped")
            continue
        if pm.sf == 0.0:
            mapped = _PM_DOF_TO_BCS.get(pm.dof)
            if mapped is None:
                state.warn(
                    f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: dof={pm.dof} is "
                    "not a global X/Y/Z translation (1-3) or rotation (5-7) — e.g. "
                    "4/8 act along a vector — so no zero-motion /BCS was emitted."
                )
                continue
            if pm.nsid not in fix_tra:
                fix_order.append(pm.nsid)
            fix_tra[pm.nsid].append(mapped[0])
            fix_rot[pm.nsid].append(mapped[1])
        else:
            motions.append(pm)

    for nsid in fix_order:
        set_title, nids = state.node_sets[nsid]
        tra = _or_dof_codes(fix_tra[nsid])
        rot = _or_dof_codes(fix_rot[nsid])
        bc_id = state.next_id()
        grnod_id = state.next_id()
        lines += [
            f"/BCS/{bc_id}",
            set_title or f"BC_set_{nsid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}         0{_i(grnod_id)}",
            HDR,
        ]
        lines += _emit_grnod_node(grnod_id, set_title or f"SET_{nsid}", nids)

    # Non-zero scale: real prescribed motion → /IMPDISP, /IMPVEL, /IMPACC
    for pm in motions:
        set_title, nids = state.node_sets[pm.nsid]
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
# Starter: gravity loads
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grnod_part(grnod_id: int, title: str, pids: List[int]) -> List[str]:
    """/GRNOD/PART — a node group holding all nodes of the listed parts."""
    lines = [f"/GRNOD/PART/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for p in pids:
        row.append(str(p).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _make_gravity_loads(state: ConversionState) -> List[str]:
    """*LOAD_GRAVITY_PART → /GRAV (non-modal decks).

    LS-DYNA applies the load along the NEGATIVE DOF axis (an all-positive card
    means "downward"), and Radioss' own dyna-reader maps the keyword to /GRAV
    the same way — so Fscale_Y carries a minus sign: -accel for the constant
    form (lc = 0, fct_IDT = 0 → constant gravity = Fscale_Y), or -1 × curve lc
    for the time-dependent form.  Parts sharing (dof, lc, accel) are grouped
    into one /GRAV on a /GRNOD/PART.

    Modal decks emit NO /GRAV: gravity does not change a non-prestressed
    eigenproblem, and the stiffness-export run must stay load-consistent with
    the eigensolve.  A NOTE (not a bare "skipped") records that.
    """
    if not state.gravity_loads:
        return []
    if state.is_modal:
        state.warn(
            "NOTE: *LOAD_GRAVITY_PART is not emitted for a modal deck - "
            "gravity does not affect a non-prestressed eigenproblem, so the "
            "stiffness-export/eigen run omits /GRAV. (A non-modal conversion "
            "maps it to /GRAV.)")
        return [
            "#-  *LOAD_GRAVITY_PART: intentionally NOT converted for the modal",
            "#-  (eigenvalue) run - gravity is irrelevant to a non-prestressed",
            "#-  eigenproblem. A non-modal conversion emits /GRAV instead.",
            HDR,
        ]
    _DIR = {1: "X", 2: "Y", 3: "Z"}
    groups: Dict[Tuple[int, int, float], List[int]] = {}
    for g in state.gravity_loads:
        groups.setdefault((g.dof, g.lc, g.accel), []).append(g.pid)
        if g.lcdr:
            state.warn(f"LOAD_GRAVITY_PART pid={g.pid}: dynamic-relaxation "
                       f"curve LCDR={g.lcdr} has no OpenRadioss mapping - "
                       "ignored (only the transient gravity is converted).")
        if g.stga or g.stgr:
            state.warn(f"LOAD_GRAVITY_PART pid={g.pid}: staged-construction "
                       f"stages STGA/STGR={g.stga}/{g.stgr} are not supported "
                       "- gravity is applied for the whole run.")
    lines: List[str] = ["#-  GRAVITY LOADS (*LOAD_GRAVITY_PART):", HDR]
    for (dof, lc, accel), pids in sorted(groups.items()):
        if lc > 0 and lc not in state.curves:
            state.warn(f"LOAD_GRAVITY_PART: load curve {lc} not found - "
                       f"gravity on part(s) {pids} skipped.")
            continue
        grnod_id = state.next_id()
        grav_id = state.next_id()
        lines += _emit_grnod_part(grnod_id, f"gravity_parts_{grav_id}",
                                  sorted(set(pids)))
        # lc>0: curve gives |g|(t), Fscale_Y=-1 flips to the -DOF direction;
        # lc=0: constant gravity, fct_IDT=0 and Fscale_Y = -accel.
        fct = lc if lc > 0 else 0
        fscale = -1.0 if lc > 0 else -accel
        lines += [
            f"/GRAV/{grav_id}",
            f"Gravity_{_DIR[dof]}_parts_" + "_".join(str(p) for p in sorted(set(pids))),
            "#  fct_IDT       Dir   skew_ID   sens_ID   grnd_ID             Ascalex             FscaleY",
            f"{_i(fct)}{_DIR[dof].rjust(10)}{_i(0)}{_i(0)}{_i(grnod_id)}"
            f"{_f(1.0)}{_f(fscale)}",
            HDR,
        ]
    return lines if len(lines) > 2 else []


def _make_body_loads(state: ConversionState) -> List[str]:
    """*LOAD_BODY_{X,Y,Z} → /GRAV applied to every part (whole-model body load).

    The load is a base acceleration g(t) = SF × lcid(t) along the named axis.
    LS-DYNA's base-acceleration sign convention is transcribed directly
    (/GRAV Fscale = SF, fct = lcid) over a /GRNOD/PART of all parts; the two
    codes can differ by a sign, so the direction is flagged for the user to
    confirm. Modal decks emit nothing (a body load is a static preload,
    irrelevant to a non-prestressed eigenproblem).
    """
    if not state.body_loads or state.is_modal:
        return []
    all_pids = sorted(state.parts)
    if not all_pids:
        return []
    lines: List[str] = ["#-  BODY LOADS (*LOAD_BODY_* -> /GRAV):", HDR]
    emitted = False
    for bl in state.body_loads:
        if bl.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_{bl.dir}: load curve {bl.lcid} not found "
                       "— skipped.")
            continue
        emitted = True
        grnod_id = state.next_id()
        grav_id = state.next_id()
        lines += _emit_grnod_part(grnod_id, f"body_load_allparts_{grav_id}", all_pids)
        lines += [
            f"/GRAV/{grav_id}",
            f"Body_accel_{bl.dir}",
            "#  fct_IDT       Dir   skew_ID   sens_ID   grnd_ID             Ascalex             FscaleY",
            f"{_i(bl.lcid)}{bl.dir.rjust(10)}{_i(0)}{_i(0)}{_i(grnod_id)}"
            f"{_f(1.0)}{_f(bl.sf)}",
            HDR,
        ]
    if not emitted:
        return []
    state.warn(
        "*LOAD_BODY_* mapped to /GRAV over all parts. LS-DYNA base-acceleration "
        "and OpenRadioss /GRAV can differ by a sign — verify the body-load / "
        "gravity direction and flip the *LOAD_BODY SF if it acts the wrong way.")
    return lines


_AXIS_VEC = {
    "X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}


def _blast_target_bbox(state: ConversionState, segset):
    """((xmin,xmax),(ymin,ymax),(zmin,zmax)) of a segment set's nodes, or None."""
    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    for seg in segset.segments:
        for nid in seg:
            nd = state.nodes.get(nid)
            if nd:
                xs.append(nd.x); ys.append(nd.y); zs.append(nd.z)
    if not xs:
        return None
    return ((min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs)))


def _infer_blast_up_axis(det, bbox) -> Optional[str]:
    """Signed axis the ground normal should point (charge → target).

    The vertical axis is the one the charge sits most clearly *beyond* the target
    bounding box on: charge below the box → up = +axis, above → up = -axis.
    Returns None when the charge is within the target's range on every axis (no
    confident inference).
    """
    (xmn, xmx), (ymn, ymx), (zmn, zmx) = bbox
    best: Optional[str] = None
    best_out = 0.0
    for name, dv, lo, hi in (("X", det[0], xmn, xmx),
                             ("Y", det[1], ymn, ymx),
                             ("Z", det[2], zmn, zmx)):
        if dv < lo:                      # charge below target → up = +axis
            out, axis = lo - dv, name
        elif dv > hi:                    # charge above target → up = -axis
            out, axis = dv - hi, "-" + name
        else:
            continue
        if out > best_out:
            best_out, best = out, axis
    return best


def _infer_blast_up_axis_enclosed(det, bbox) -> Optional[str]:
    """Fallback up-axis when the charge sits INSIDE the target bbox on every axis.

    An under-body / internal charge (the charge is surrounded by structure, e.g.
    an under-vehicle blast) defeats the strict "charge beyond the box" test, so
    without this the converter would fall through to OpenRadioss's degenerate
    perpendicular-to-Z default — which flags a large fraction of segments as
    "Rg too close to the charge" and computes a bad ground reflection. Here the
    vertical axis is guessed as the one on which the charge is closest to a
    bounding face (the most likely up/down direction for a near-surface burst),
    with the normal pointing away from that nearer face (toward the target bulk).
    Returns None only for a degenerate (zero-size) box.
    """
    best_axis: Optional[str] = None
    best_gap: Optional[float] = None
    for name, dv, lo, hi in (("X", det[0], bbox[0][0], bbox[0][1]),
                             ("Y", det[1], bbox[1][0], bbox[1][1]),
                             ("Z", det[2], bbox[2][0], bbox[2][1])):
        if hi <= lo:
            continue
        d_lo, d_hi = dv - lo, hi - dv
        gap = min(d_lo, d_hi)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            # charge nearer the low face → it sits at the bottom → up = +axis
            best_axis = name if d_lo <= d_hi else "-" + name
    return best_axis


def _synthesize_blast_ground(state: ConversionState, det, axis: str):
    """Build an infinite /SURF/PLANE ground through the charge, normal along
    `axis` (which faces the target). Returns (lines, surf_id).

    /SURF/PLANE is defined by two points: M lies on the plane (the charge, so the
    charge is on the ground), and the vector M→M1 is the normal. OpenRadioss
    loads target segments on the +normal side, so the normal points at the
    target. No mesh is needed — the plane is pure geometry.
    """
    n = _AXIS_VEC[axis]
    m = (det[0], det[1], det[2])                 # charge lies on the ground
    m1 = (det[0] + n[0], det[1] + n[1], det[2] + n[2])   # M→M1 = +axis = normal
    surf_id = state.next_id()
    lines = [
        f"/SURF/PLANE/{surf_id}",
        f"blast_ground_{axis}",
        "#                 XM                  YM                  ZM",
        _f(m[0]) + _f(m[1]) + _f(m[2]),
        "#                XM1                 YM1                 ZM1",
        _f(m1[0]) + _f(m1[1]) + _f(m1[2]),
        HDR,
    ]
    return lines, surf_id


def _resolve_blast_ground(state: ConversionState, src, segset):
    """Resolve the Ground_ID for a surface-burst /LOAD/PBLAST per
    ``options.blast_ground``.

    Returns ``(ground_id, ground_lines)`` — ground_id 0 and empty lines when no
    ground is emitted (OpenRadioss then assumes ⊥Z through the charge, which the
    returned warning explains).
    """
    mode = (state.options.blast_ground or "auto").strip()
    det = (src.xbo, src.ybo, src.zbo)
    bbox = _blast_target_bbox(state, segset)

    default_warn = (
        f"*LOAD_BLAST_ENHANCED bid={src.bid}: surface burst -> /LOAD/PBLAST "
        "Exp_data=2 (ground reflection) with NO Ground_ID — OpenRadioss assumes "
        f"the ground is perpendicular to Z through the charge (Z={src.zbo:g}) and "
        "will NOT load target segments on the far side. Set blast_ground to the "
        "vertical axis (e.g. 'Y') or leave it 'auto' to synthesize the plane.")

    if mode.lower() == "none":
        state.warn(default_warn)
        return 0, []

    axis = None
    inferred_guess = False
    if mode.upper() in _AXIS_VEC:
        axis = mode.upper()
    elif mode.lower() == "auto" and bbox is not None:
        axis = _infer_blast_up_axis(det, bbox)          # confident: charge beyond box
        if axis is None:                                # enclosed charge → best guess
            axis = _infer_blast_up_axis_enclosed(det, bbox)
            inferred_guess = axis is not None

    if axis is None:
        if mode.lower() == "auto":
            state.warn(
                f"*LOAD_BLAST_ENHANCED bid={src.bid}: could not infer the vertical "
                "axis for the ground plane (the target has no nodes). " + default_warn)
        else:
            state.warn(default_warn)
        return 0, []

    ground_lines, surf_id = _synthesize_blast_ground(state, det, axis)
    if inferred_guess:
        state.warn(
            f"*LOAD_BLAST_ENHANCED bid={src.bid}: the charge sits inside the "
            "target's bounding box on every axis (e.g. an under-body blast), so the "
            f"vertical axis was GUESSED as {axis} (the axis on which the charge is "
            "closest to a bounding face) and a /SURF/PLANE reflecting ground was "
            "synthesized. This avoids OpenRadioss's degenerate perpendicular-to-Z "
            "default (which flags many segments 'Rg too close to the charge' and "
            "computes a bad reflection); VERIFY the axis and override with "
            "blast_ground=<axis> if it is wrong.")
    else:
        state.warn(
            f"*LOAD_BLAST_ENHANCED bid={src.bid}: surface burst -> Exp_data=2; "
            f"synthesized a /SURF/PLANE reflecting ground (normal {axis}, through the "
            "charge) as Ground_ID so all target segments load. Override with "
            "blast_ground=<axis> or 'none' if the vertical axis differs.")
    return surf_id, ground_lines


def _make_blast_loads(state: ConversionState) -> List[str]:
    """*LOAD_BLAST_ENHANCED + *LOAD_BLAST_SEGMENT_SET → /SURF/SEG + /LOAD/PBLAST.

    OpenRadioss /LOAD/PBLAST is the TM5-1300 (ConWep) empirical air-blast model,
    the direct counterpart of LS-DYNA's *LOAD_BLAST_ENHANCED. The loaded segment
    set becomes a /SURF/SEG; the blast source supplies the equivalent TNT mass
    and the detonation point/time. The LS-DYNA `blast` type maps to Exp_data:
      blast 1 (hemispherical surface burst) -> Exp_data 2 (ground reflection)
      blast 2 (spherical free-air burst)    -> Exp_data 1 (free air)
      blast 3 (air burst, Mach stem)        -> no equivalent (warn; uses 1)

    The blast formula is unit-dependent; convert() has already set /BEGIN to the
    system implied by the LOAD_BLAST_ENHANCED UNIT flag (handlers._blast_unit_system)
    so that /LOAD/PBLAST converts its internal {cm,g,µs} data correctly. Card
    layout follows FORMAT(radioss2022) in hm_cfg_files .../LOADS/pblast.cfg.
    """
    if not state.blast_segment_loads:
        if state.blast_sources:
            state.warn("*LOAD_BLAST_ENHANCED present but no "
                       "*LOAD_BLAST_SEGMENT_SET applies it — no /LOAD/PBLAST "
                       "emitted.")
        return []
    if state.is_modal:
        state.warn("NOTE: blast load (*LOAD_BLAST_*) not emitted for a modal "
                   "deck — a blast is irrelevant to a non-prestressed eigenproblem.")
        return []

    lines: List[str] = ["#-  BLAST LOADS (*LOAD_BLAST_ENHANCED -> /LOAD/PBLAST):", HDR]
    surf_for_ssid: Dict[int, int] = {}
    emitted = False
    for load in state.blast_segment_loads:
        src = state.blast_sources.get(load.bid)
        if src is None and len(state.blast_sources) == 1:
            # Legacy *LOAD_BLAST / a bid=0 segment card: fall back to the sole
            # blast source (there is only one implicit charge).
            src = next(iter(state.blast_sources.values()))
        if src is None:
            state.warn(f"*LOAD_BLAST_SEGMENT[_SET] bid={load.bid}: no matching "
                       "*LOAD_BLAST[_ENHANCED] — skipped.")
            continue
        segset = state.segment_sets.get(load.ssid)
        if segset is None or not segset.segments:
            state.warn(f"*LOAD_BLAST_SEGMENT_SET ssid={load.ssid}: segment set "
                       "not found or empty — skipped.")
            continue

        # /SURF/SEG (built once per segment set, reused across blast loads)
        surf_id = surf_for_ssid.get(load.ssid)
        if surf_id is None:
            surf_id = state.next_id()
            surf_for_ssid[load.ssid] = surf_id
            # Remember the loaded surface for the *DATABASE_BINARY_BLSTFOR
            # /TH/SURF output (build_starter emits that block later).
            state.blast_surf_ids.append(
                (surf_id, segset.title or f"blast_segset_{load.ssid}"))
            lines += [
                f"/SURF/SEG/{surf_id}",
                (segset.title or f"blast_segset_{load.ssid}")[:100],
                "#   seg_ID        n1        n2        n3        n4",
            ]
            for seg_no, nodes in enumerate(segset.segments, start=1):
                quad = (list(nodes) + [0, 0, 0, 0])[:4]
                lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
            lines.append(HDR)

        ground_id = 0
        if src.blast == 2:
            exp_data = 1                       # spherical free-air burst
        elif src.blast in (0, 1):
            exp_data = 2                       # hemispherical surface / ground reflection
            ground_id, ground_lines = _resolve_blast_ground(state, src, segset)
            lines += ground_lines
        else:
            exp_data = 1
            state.warn(f"*LOAD_BLAST_ENHANCED bid={src.bid}: BLAST={src.blast} "
                       "(air burst / Mach stem) has no /LOAD/PBLAST equivalent "
                       "— using Exp_data=1 (free-air spherical); verify the result.")
        if load.scalep not in (0.0, 1.0):
            state.warn(f"*LOAD_BLAST_SEGMENT_SET bid={load.bid}: SCALEP="
                       f"{load.scalep} (pressure scale) has no /LOAD/PBLAST "
                       "field — applied the unscaled charge (scaling TNT mass is "
                       "NOT equivalent). Adjust manually if the scale matters.")
        tstop = src.death if 0.0 < src.death < 1e19 else 1.0e20

        pblast_id = state.next_id()
        lines += [
            f"/LOAD/PBLAST/{pblast_id}",
            f"blast_bid{src.bid}_ssid{load.ssid}"[:100],
            "#  surf_ID  Exp_data  I_tshift       Ndt        IZ    Imodel                                 Node_id",
            (_i(surf_id) + _i(exp_data) + _i(1) + _i(100) + _i(2) + _i(1)
             + " " * 30 + _i(0)),
            "#               Xdet                Ydet                Zdet                Tdet                WTNT",
            _f(src.xbo) + _f(src.ybo) + _f(src.zbo) + _f(src.tbo) + _f(src.m),
            "#               Pmin               Tstop",
            _f(0.0) + _f(tstop),
            "#Ground_ID",
            _i(ground_id),
            HDR,
        ]
        emitted = True

    return lines if emitted else []


def _make_detonations(state: ConversionState) -> List[str]:
    """*INITIAL_DETONATION → /DFS/DETPOINT — the JWL burn origin/time.

    Each detonation lights a /MAT/LAW5 explosive: pid>0 resolves part → material,
    pid=0 lights every explosive material. Card: Xdet Ydet Zdet Tdet mat_ID.
    Modal decks emit nothing (a detonation is irrelevant to an eigenproblem).
    """
    if not state.detonations or state.is_modal:
        return []
    if not state.mat_high_explosive:
        state.warn("*INITIAL_DETONATION present but no *MAT_HIGH_EXPLOSIVE_BURN "
                   "(/MAT/LAW5) explosive to light — /DFS/DETPOINT not emitted.")
        return []
    lines = ["#-  DETONATION POINTS (*INITIAL_DETONATION -> /DFS/DETPOINT):", HDR]
    emitted = False
    for det in state.detonations:
        if det.pid > 0:
            part = state.parts.get(det.pid)
            mid = part.mid if part else 0
            if mid not in state.mat_high_explosive:
                # LS-DYNA names a part, but tolerate a deck that names the
                # explosive material id directly.
                mid = det.pid if det.pid in state.mat_high_explosive else 0
            if mid == 0:
                state.warn(f"*INITIAL_DETONATION pid={det.pid}: not an explosive "
                           "(/MAT/LAW5) part/material — /DFS/DETPOINT skipped.")
                continue
            mids = [mid]
        else:
            mids = sorted(state.mat_high_explosive)      # pid=0 → all explosives
        for mid in mids:
            did = state.next_id()
            # /DFS/DETPOINT has NO title line — the data card follows the header
            # directly (cfg LOADS/detpoint.cfg FORMAT(radioss140)).
            lines += [
                f"/DFS/DETPOINT/{did}",
                "#               XDET                YDET                ZDET                TDET mat_IDDET",
                f"{_f(det.x)}{_f(det.y)}{_f(det.z)}{_f(det.lt)}{_i(mid)}",
                HDR,
            ]
            emitted = True
    return lines if emitted else []


# ─────────────────────────────────────────────────────────────────────────────
# Coupled ALE / fluid-structure coupling / non-reflecting boundaries
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grbric_part(grbric_id: int, title: str, pids: List[int]) -> List[str]:
    """A /GRBRIC/PART brick group (the ALE fluid side of an FSI coupling)."""
    lines = [f"/GRBRIC/PART/{grbric_id}", title or f"GRBRIC_{grbric_id}"]
    row: List[str] = []
    for p in pids:
        row.append(_i(p))
        if len(row) == 10:
            lines.append("".join(row)); row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_seg(surf_id: int, title: str, segments) -> List[str]:
    """A /SURF/SEG from a list of node lists (shared by blast/EBCS/FSI)."""
    lines = [f"/SURF/SEG/{surf_id}", (title or f"surf_seg_{surf_id}")[:100],
             "#   seg_ID        n1        n2        n3        n4"]
    for seg_no, nodes in enumerate(segments, start=1):
        quad = (list(nodes) + [0, 0, 0, 0])[:4]
        lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
    lines.append(HDR)
    return lines


def _part_pids(state: ConversionState, sid: int, is_part: bool) -> List[int]:
    """Expand a part id or part-set id to a list of part ids."""
    if is_part:
        return [sid] if sid in state.parts else []
    ps = state.part_sets.get(sid)
    return list(ps[1]) if ps else []


def _make_ale_multimaterial(state: ConversionState) -> List[str]:
    """*ALE_MULTI-MATERIAL_GROUP → /MAT/LAW51 (MULTIMAT), Iform=12.

    The AMMG order becomes the ordered submaterial list; each submaterial is the
    material of the referenced part(s) (a /MAT/LAW6+/EOS fluid or /MAT/LAW5
    explosive already emitted). Card layout from MAT/mat_law51.cfg
    FORMAT(radioss2023). The single-part-consolidation of the LS-DYNA multi-part
    ALE mesh is left to the user (warned).
    """
    if not state.ale_mmgs:
        return []
    lines: List[str] = []
    for mmg in state.ale_mmgs:
        submats: List[int] = []
        for sid, idtype in mmg.entries:
            for pid in _part_pids(state, sid, idtype == 1):
                part = state.parts.get(pid)
                if part and part.mid and part.mid not in submats:
                    submats.append(part.mid)
        if not submats:
            state.warn("*ALE_MULTI-MATERIAL_GROUP: could not resolve any "
                       "submaterial (no known parts/materials) — /MAT/LAW51 not "
                       "emitted.")
            continue
        law_id = state.next_id()
        lines += [
            f"/MAT/LAW51/{law_id}",
            f"ale_multimat_{law_id}",
            "",                                     # Card 1 (general) — blank
            "#    Iform",
            "        12",
            "#                                     NU              Nu_Vol",
            "",                                     # NU / Nu_Vol — blank
            "#    MatID           ALPHA_MAT",
        ]
        for k, mid in enumerate(submats):
            lines.append(_i(mid) + _f(1.0 if k == 0 else 0.0))
        lines.append(HDR)
        expl = [m for m in submats if m in state.mat_high_explosive]
        if expl:
            state.warn(
                f"*ALE_MULTI-MATERIAL_GROUP: /MAT/LAW51/{law_id} includes JWL "
                f"explosive submaterial(s) {expl}; a LAW5 used inside a multi-"
                "material ALE needs a non-zero unreacted-explosive bulk modulus "
                "(Bunreacted) on its /MAT/LAW5 (ERROR 99 otherwise) — set it.")
        state.warn(
            f"*ALE_MULTI-MATERIAL_GROUP -> /MAT/LAW51/{law_id} listing submaterials "
            f"{submats} (phase order). In OpenRadioss the ALE domain is ONE part "
            f"referencing this /MAT/LAW51 with the initial fill set by /INIVOL; "
            "consolidate the LS-DYNA per-fluid ALE parts onto one mesh that "
            f"references material {law_id}.")
    return lines


def _mean_brick_edge(state: ConversionState, pids: Set[int]) -> float:
    """Rough mean first-edge length of the solid elements of *pids* (for a
    default FSI gap). Samples up to 200 elements."""
    tot = 0.0
    n = 0
    for e in state.solid_elems:
        if e.pid in pids and len(e.nodes) >= 2:
            a = state.nodes.get(e.nodes[0])
            b = state.nodes.get(e.nodes[1])
            if a and b:
                tot += ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
                n += 1
                if n >= 200:
                    break
    return (tot / n) if n else 0.0


def _make_fsi_coupling(state: ConversionState) -> List[str]:
    """*CONSTRAINED_LAGRANGE_IN_SOLID → /INTER/TYPE18 (penalty ALE/Lagrange FSI).

    slave (Lagrangian structure) → /SURF/PART/EXT (or /SURF/SEG); master (ALE
    fluid) → /GRBRIC/PART. Card layout from INTER/inter_type18.cfg
    FORMAT(radioss2022). Stfval/Gap must be > 0 (a mesh-derived default Gap and a
    unit Stfval are emitted and warned for tuning). TYPE22 (cut-cell) is the more
    accurate alternative for demanding FSI.
    """
    if not state.lagrange_in_solid:
        return []
    lines: List[str] = []
    for cls in state.lagrange_in_solid:
        # structure surface
        if cls.sstyp == 2 and cls.slave in state.segment_sets:
            surf_id = state.next_id()
            lines += _emit_surf_seg(surf_id, f"fsi_struct_{cls.slave}",
                                    state.segment_sets[cls.slave].segments)
        else:
            spids = _part_pids(state, cls.slave, cls.sstyp == 1)
            if not spids:
                state.warn(f"*CONSTRAINED_LAGRANGE_IN_SOLID: slave {cls.slave} "
                           "not a known part/part-set/segment set — /INTER/TYPE18 "
                           "skipped.")
                continue
            surf_id = state.next_id()
            lines += _emit_surf_part(surf_id, f"fsi_struct_{cls.slave}", spids)
        # fluid brick group
        mpids = _part_pids(state, cls.master, cls.mstyp == 1)
        if not mpids:
            state.warn(f"*CONSTRAINED_LAGRANGE_IN_SOLID: master (fluid) "
                       f"{cls.master} not a known part/part-set — /INTER/TYPE18 "
                       "skipped.")
            continue
        grbric_id = state.next_id()
        lines += _emit_grbric_part(grbric_id, f"fsi_fluid_{cls.master}", mpids)

        edge = _mean_brick_edge(state, set(mpids))
        gap = 0.5 * edge if edge > 0 else 1.0
        inter_id = state.next_id()
        lines += [
            f"/INTER/TYPE18/{inter_id}",
            f"fsi_coupling_{inter_id}",
            "#            surf_ID grbric_id                Igap               Ipres      Idel",
            (" " * 10 + _i(surf_id) + _i(grbric_id) + " " * 10 + _i(0)
             + " " * 10 + _i(0) + _i(0)),
            "#             Stfval                Vref                 Gap              Tstart               Tstop",
            _f(1.0) + _f(0.0) + _f(gap) + _f(cls.start) + _f(cls.end),
            HDR,
        ]
    if lines:
        state.warn(
            "*CONSTRAINED_LAGRANGE_IN_SOLID -> /INTER/TYPE18 (penalty FSI): a unit "
            "interface stiffness (Stfval=1) and a mesh-derived Gap were emitted — "
            "tune Stfval/Gap for your coupling, or switch to /INTER/TYPE22 "
            "(cut-cell) for demanding fluid-structure interaction.")
    return lines


def _make_ebcs(state: ConversionState) -> List[str]:
    """*BOUNDARY_NON_REFLECTING → /EBCS/NRF on the named segment set.

    Card layout from LOADS/ebcs_nrf.cfg FORMAT(radioss2022): a /SURF/SEG built
    from the *SET_SEGMENT + the /EBCS/NRF referencing it (relaxation times left 0
    = auto).
    """
    if not state.non_reflecting:
        return []
    lines: List[str] = []
    surf_for_ssid: Dict[int, int] = {}
    for nrf in state.non_reflecting:
        segset = state.segment_sets.get(nrf.nsid)
        if segset is None or not segset.segments:
            state.warn(f"*BOUNDARY_NON_REFLECTING nsid={nrf.nsid}: segment set not "
                       "found or empty — /EBCS/NRF skipped.")
            continue
        surf_id = surf_for_ssid.get(nrf.nsid)
        if surf_id is None:
            surf_id = state.next_id()
            surf_for_ssid[nrf.nsid] = surf_id
            lines += _emit_surf_seg(surf_id, segset.title or f"nrf_{nrf.nsid}",
                                    segset.segments)
        ebcs_id = state.next_id()
        lines += [
            f"/EBCS/NRF/{ebcs_id}",
            f"non_reflecting_{nrf.nsid}",
            "#  surf_ID",
            _i(surf_id),
            "#            TCAR_P             TCAR_VF",
            _f(0.0) + _f(0.0),
            HDR,
        ]
    return lines


def _make_inivol_notes(state: ConversionState) -> List[str]:
    """*INITIAL_VOLUME_FRACTION_GEOMETRY → /INIVOL (recognize + warn).

    /INIVOL fills an ALE part with a phase up to a geometric /SURF. The LS-DYNA
    container geometry (plane/box/sphere/cylinder) has no single infinite-/SURF
    primitive except the plane, so a first-pass conversion recognises the fill
    and points the user at a manual /INIVOL + /SURF (writer._synthesize_blast_
    ground emits the /SURF/PLANE for a plane container). No card is emitted here
    to avoid a wrongly-positioned fill boundary.
    """
    if not state.volume_fractions:
        return []
    parts = ", ".join(str(vf.part) for vf in state.volume_fractions)
    state.warn(
        f"*INITIAL_VOLUME_FRACTION_GEOMETRY (part(s) {parts}) -> /INIVOL: the ALE "
        "initial fill was recognised but its geometric container needs a manual "
        "/SURF (plane/box/sphere/cylinder). Add /INIVOL/<part>/<id> with a "
        "/SURF (a plane container can reuse a /SURF/PLANE) and ALE_PHASE = the "
        "AMMG phase index; see docs/BLAST_ALE_JWL_MAPPING.md §B5.")
    return []


def _make_control_ale_notes(state: ConversionState) -> List[str]:
    """*CONTROL_ALE → an informational note (advection defaults are kept)."""
    if state.control_ale is None:
        return []
    meth = state.control_ale.meth
    hint = ("Van-Leer/HIS second-order advection -> add /ALE/MUSCL"
            if meth in (2, 3) else "donor-cell advection → OpenRadioss default (upwind)")
    state.warn(
        f"*CONTROL_ALE (METH={meth}): OpenRadioss keeps its default ALE advection "
        f"(stable in the reference FSI example); {hint} if you need to reproduce "
        "the exact scheme. Mesh smoothing (*ALE_SMOOTHING / "
        "*ALE_REFERENCE_SYSTEM_*) has no /ALE 1:1 and is not converted.")
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Starter: offline frequency-domain post-processing notes
# ─────────────────────────────────────────────────────────────────────────────

def _make_freq_domain_notes(state: ConversionState) -> List[str]:
    """*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG + *MAT_ADD_FATIGUE.

    OpenRadioss has no frequency-domain binary databases and no S-N fatigue
    material add-on; instead of listing these as bare "skipped" keywords, note
    where the results come from: the offline modal post-processing chain
    (tools/modal_solve.py → tools/modal_shapes_export.py mode shapes;
    tools/modal_random_response.py PSD/RMS/Dirlik fatigue honouring the deck's
    D3PSD band, PSD curve and *MAT_ADD_FATIGUE S-N data).
    """
    kinds = sorted(state.db_freq_binary)
    if not kinds and not state.mat_add_fatigue:
        return []
    what = [f"*DATABASE_FREQUENCY_BINARY_{k}" for k in kinds]
    if state.mat_add_fatigue:
        mids = ", ".join(str(m) for m in sorted(state.mat_add_fatigue))
        what.append(f"*MAT_ADD_FATIGUE (mid {mids})")
    listing = ", ".join(what)
    if state.is_modal:
        state.warn(
            f"NOTE: {listing}: no OpenRadioss equivalent - these results are "
            "produced OFFLINE from the modal solution: run tools/"
            "modal_solve.py (eigenmodes), then tools/modal_shapes_export.py "
            "(mode-shape d3plot + VTK) and tools/modal_random_response.py "
            "(response PSD / RMS / Dirlik fatigue per the deck's D3PSD band, "
            "PSD curve and S-N data). See the README modal section.")
    else:
        state.warn(
            f"NOTE: {listing}: no OpenRadioss equivalent, and the deck is not "
            "a modal (*CONTROL_IMPLICIT_EIGENVALUE) deck - the offline "
            "random-vibration post-processing (tools/modal_random_response.py)"
            " needs the modal solution, so these requests produce no output "
            "here.")
    lines = [
        "#-  FREQUENCY-DOMAIN REQUESTS (no OpenRadioss equivalent - handled OFFLINE):",
    ]
    for w in what:
        lines.append(f"#-    {w}")
    lines += [
        "#-  Results come from the offline modal chain: tools/modal_solve.py ->",
        "#-  tools/modal_shapes_export.py (mode shapes for LS-PrePost/ParaView) ->",
        "#-  tools/modal_random_response.py (PSD / RMS / Dirlik fatigue).",
        HDR,
    ]
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

def _emit_inivel(kind: str, inivel_id: int, title: str, grnod_id: int,
                 v: Tuple[float, float, float]) -> List[str]:
    """One /INIVEL/TRA|ROT block — a single data card after the title:
    Vx(20) Vy(20) Vz(20) Gnod_id(10) Skew_id(10)."""
    return [
        f"/INIVEL/{kind}/{inivel_id}",
        title,
        "#                 Vx                  Vy                  Vz   Gnod_id   Skew_id",
        f"{_f(v[0])}{_f(v[1])}{_f(v[2])}{_i(grnod_id)}{_i(0)}",
        HDR,
    ]


def _make_inivel(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Initial velocities → /INIVEL/TRA (+ /INIVEL/ROT for rotational DOFs).

    The only valid /INIVEL subtypes are TRA/ROT (cfg inivel.cfg); rotational
    components need their own /INIVEL/ROT block. For rigid bodies the velocity
    goes on the MASTER node only — its 6 DOFs drive the body, and secondary-
    node values are overridden by /RBODY kinematics anyway.
    """
    lines: List[str] = []

    vel_groups: Dict[Tuple, List[int]] = defaultdict(list)
    for iv in state.inivel_nodes:
        vel_groups[(iv.vx, iv.vy, iv.vz, iv.vxr, iv.vyr, iv.vzr)].append(iv.nid)

    for vel_key, nids in vel_groups.items():
        vx, vy, vz, vxr, vyr, vzr = vel_key
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_nodes_{grnod_id}", sorted(nids))
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVel_{inivel_id}",
                              grnod_id, (vx, vy, vz))
        if vxr or vyr or vzr:
            rot_id = state.next_id()
            lines += _emit_inivel("ROT", rot_id, f"InitVelRot_{rot_id}",
                                  grnod_id, (vxr, vyr, vzr))

    for iv in state.inivel_rbodies:
        info = rbody_info.get(iv.pid)
        if not info:
            state.warn(f"INITIAL_VELOCITY_RIGID_BODY pid={iv.pid}: no RBODY found – skipped")
            continue
        grnod_id = info["ind_grnod_id"]
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVelRB_{inivel_id}",
                              grnod_id, (iv.vx, iv.vy, iv.vz))
        if iv.vxr or iv.vyr or iv.vzr:
            rot_id = state.next_id()
            lines += _emit_inivel("ROT", rot_id, f"InitVelRBRot_{rot_id}",
                                  grnod_id, (iv.vxr, iv.vyr, iv.vzr))

    if lines:
        lines = ["#-  INITIAL CONDITIONS:", HDR] + lines
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: pressure loads
# ─────────────────────────────────────────────────────────────────────────────

def _make_pressure_loads(state: ConversionState) -> List[str]:
    """*LOAD_SEGMENT → /SURF/SEG + /PLOAD.

    /PLOAD has ONE data card referencing a surface:
      surf_ID(10) fct_IDT(10) sens_ID(10) <blank to col 60> Ascale_x(20) Fscale_y(20)
    The segments themselves must be a /SURF/SEG entity (seg_ID n1 n2 n3 n4,
    five 10-char fields per line; n4=0 → triangle). Pressure acts along the
    segment normal, so LS-DYNA's segment orientation carries the direction.
    """
    if not state.pressure_loads:
        return []
    groups: Dict[Tuple, List[List[int]]] = defaultdict(list)
    for pl in state.pressure_loads:
        groups[(pl.lcid, pl.sf)].append(pl.nodes)

    lines: List[str] = ["#-  PRESSURE LOADS:", HDR]
    pload_id = 1
    for (lcid, sf), segs in groups.items():
        surf_id = state.next_id()
        lines += [
            f"/SURF/SEG/{surf_id}",
            f"PLOAD_{pload_id}_segments",
            "#   seg_ID        n1        n2        n3        n4",
        ]
        for seg_no, nodes in enumerate(segs, start=1):
            quad = (list(nodes) + [0, 0, 0, 0])[:4]
            lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
        lines += [
            f"/PLOAD/{pload_id}",
            f"PLOAD_{pload_id}",
            "#  surf_ID  functIDT sensor_ID                                          Ascale_x            Fscale_y",
            f"{_i(surf_id)}{_i(lcid)}         0" + " " * 30 + f"{_f(1.0)}{_f(sf)}",
            HDR,
        ]
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
    state.curves[fid] = Curve(
        lcid=fid, title=title,
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
        pts=pts,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Engine file sections
# ─────────────────────────────────────────────────────────────────────────────

def _make_added_masses(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """*ELEMENT_MASS lumped masses on ORDINARY nodes → /ADMAS/0.

    state.added_node_masses holds every *ELEMENT_MASS nodal mass. Masses on
    rigid-body nodes are already accounted for via the /RBODY Mass field
    (_make_rbodies folds the master-node mass), so /ADMAS is emitted only for
    nodes that are NOT part of any rigid body. /ADMAS/0 adds its Mass value to
    EACH node of the referenced /GRNOD, so nodes are grouped by identical mass
    value (one /GRNOD + /ADMAS/0 per distinct value). Before this, ordinary-node
    *ELEMENT_MASS was silently dropped (writer consumed added_node_masses only
    for rigid masters) — a real mass/dynamics error on any deck with point masses.
    """
    masses_by_value: Dict[float, List[int]] = {}
    skipped_rigid = 0
    for nid, mass in state.added_node_masses.items():
        if mass <= 0 or nid not in state.nodes:
            continue
        if nid in rigid_nodes:
            skipped_rigid += 1          # folded into its /RBODY already
            continue
        masses_by_value.setdefault(mass, []).append(nid)
    if not masses_by_value:
        return []
    lines: List[str] = [HDR, "#-  ADDED MASSES (*ELEMENT_MASS on ordinary nodes):"]
    n_nodes = 0
    total = 0.0
    for mass, nids in sorted(masses_by_value.items()):
        nids = sorted(nids)
        n_nodes += len(nids)
        total += mass * len(nids)
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"added_mass_{mass:g}_nodes", nids)
        admas_id = state.next_id()
        lines += [
            f"/ADMAS/0/{admas_id}",
            f"added_mass_{mass:g}",
            "#               MASS   grnd_ID",
            f"{_f(mass)}{_i(grnod_id)}",
            HDR,
        ]
    note = (f"*ELEMENT_MASS: emitted /ADMAS/0 for {n_nodes} ordinary node(s) "
            f"(total added mass {total:g}).")
    if skipped_rigid:
        note += (f" {skipped_rigid} mass(es) on rigid-body nodes were left to the "
                 "/RBODY (master-node mass is folded into its Mass field).")
    state.warn(note)
    return lines


def _make_eig(state: ConversionState) -> List[str]:
    """*CONTROL_IMPLICIT_EIGENVALUE → /EIG (normal-modes request) — opt-in.

    Emitted only with ``--eig`` (options.emit_eig): the open-source OpenRadioss
    engine cannot solve /EIG (the eigensolver kernel is not in the source
    release — the engine segfaults at init the moment NEIG>0), so /EIG output is
    reserved for commercial Altair Radioss users. The default modal conversion
    uses the stiffness-export recipe instead (see _make_engine_modal).

    grnd_ID=0 → modes of the whole structure AS constrained by the model's /BCS;
    grnd_bc=0 → ITYP=1 free eigenmodes (no extra interface static modes). The
    actual eigensolve is driven by /IMPL/LINEAR in the engine. Cutfreq/Freqmin
    stay 0 (engine default shift / no upper cutoff) unless the deck gave a finite
    frequency window.
    """
    eig = state.ctrl_implicit_eig
    if not state.is_modal or eig is None or not state.options.emit_eig:
        return []
    nmod = eig.neig or 100
    eig_id = state.next_id()
    return [
        HDR,
        "#-  EIGENVALUE / MODAL REQUEST (*CONTROL_IMPLICIT_EIGENVALUE):",
        f"/EIG/{eig_id}",
        "modal_eigenvalue_analysis",
        "#  grnd_ID   grnd_bc    Trarot     Ifile",
        "         0         0   000 000         0",
        "#     Nmod     Inorm             Cutfreq             Freqmin",
        f"{_i(nmod)}{_i(0)}{_f(eig.cutfreq)}{_f(eig.freqmin)}",
        "#    Nbloc      Incv     Niter      Ipri                 Tol",
        f"{_i(0)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}",
        HDR,
    ]


def _make_engine_modal(state: ConversionState) -> List[str]:
    """Engine cards for a normal-modes run.

    Default (validated stiffness-export recipe): the open-source OpenRadioss
    engine ships the /EIG eigensolver only as a no-op stub (the kernel is gated
    behind an undefined DNC build macro and the real com/eig/*.F source is not
    released), so the engine cannot compute modes itself. Instead the deck runs
    ONE linear implicit step (/IMPL/LINEAR, /IMPL/DTINI = the run end) and the
    undocumented /IMPL/PRINT/STIF keyword (engine freimpl.F; data line
    ``PRSTIFMAT_TOL PRSTIFMAT_NC PRSTIFMAT_IT`` = ``0 1 0``) makes MUMPS write
    the EXACT assembled stiffness matrix it factorizes to
    ``local_stiffness_matrix_domain0`` (run np=1). The eigenproblem is then
    solved offline with scipy — see tools/modal_solve.py. Validated on the W14
    bogie: a static solve from the exported K matches the engine to 0.000%, and
    the eigenfrequencies match an explicit impulse ring-down FFT.

    With ``--eig`` (options.emit_eig): the classic one-shot /EIG eigensolve
    engine for commercial Altair Radioss (which has the real /EIG kernel).
    """
    if state.options.emit_eig:
        return [
            "#-  MODAL (normal-modes) ENGINE",
            "#   /EIG (starter) requests the eigenmodes; /IMPL/LINEAR does the single",
            "#   linear factorization the shift-invert eigensolve needs. No time march.",
            "#   NOTE: only commercial Altair Radioss can solve /EIG — the open-source",
            "#   engine segfaults at init (eigensolver kernel not in the source release).",
            "/IMPL/LINEAR",
            "/IMPL/PRINT/NONL/-1",
            "/IMPL/SOLVER/2",
            "  0 0 0 0",
            "/IMPL/MUMPS/AUTOCORE",
            "#",
        ]
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    return [
        "#-  MODAL (normal-modes) ENGINE - stiffness-matrix export recipe",
        "#   The open-source OpenRadioss engine cannot solve /EIG, so this deck runs",
        "#   ONE linear implicit step and /IMPL/PRINT/STIF makes MUMPS print the",
        "#   assembled stiffness matrix to 'local_stiffness_matrix_domain0'.",
        "#   Run np=1, then solve the eigenproblem offline (needs numpy+scipy):",
        "#       python tools/modal_solve.py <run_dir>/local_stiffness_matrix_domain0 <model.k>",
        "#   Stock-engine caveats (both fixed by 1-line patches, see k2rad README):",
        "#     * the matrix is printed with FORMAT E10.2 (2 significant digits) ->",
        "#       ~1% stiffness rounding, ~0.5% eigenfrequency error;",
        "#     * after '--STIFFNESS MATRIX IS PRINTED--' the np=1 run can hang in an",
        "#       O(NZ^2) domain-merge scan - kill it; the per-domain file is complete.",
        "/IMPL/LINEAR",
        "/IMPL/PRINT/NONL/-1",
        "/IMPL/PRINT/STIF",
        "0 1 0",
        "/IMPL/SOLVER/2",
        "  0 0 0 0",
        "/IMPL/MUMPS/AUTOCORE",
        "/IMPL/DTINI",
        f"{endtim:.6G}",
        "#",
    ]


def _make_engine_header(state: ConversionState) -> List[str]:
    import re as _re
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    safe_title = _re.sub(r"[^A-Za-z0-9_-]", "_", state.model_title)[:40]
    return [f"/RUN/{safe_title}/1", f"{endtim:.6G}", "#"]


def _make_engine_output(state: ConversionState) -> List[str]:
    lines: List[str] = []
    dt_th = (state.db_nodout_dt or state.db_elout_dt or state.db_glstat_dt
             or state.db_matsum_dt or state.db_spcforc_dt
             or state.db_ncforc_dt or state.db_blstfor_dt or 1e-3)
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
    if state.db_spcforc_dt and state.bcs_spcs:
        # *DATABASE_SPCFORC: constraint-reaction nodal vectors (the /TH/NODE
        # REAC* channels carry the per-node time history; see writer starter).
        lines.append("/ANIM/VECT/FREAC")
        if _spc_constrains_rotations(state):
            lines.append("/ANIM/VECT/MREAC")
    if state.db_blstfor_dt and state.blast_segment_loads:
        # *DATABASE_BINARY_BLSTFOR: the blast loading as external nodal force
        # vectors (/LOAD/PBLAST accumulates into FEXT — engine pblast_1.F).
        lines.append("/ANIM/VECT/FEXT")

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
    if state.db_blstfor_dt and state.blast_segment_loads:
        # *DATABASE_BINARY_BLSTFOR: nodal blast-pressure fringe (element
        # /LOAD/PBLAST pressures averaged onto the loaded-surface nodes).
        lines.append("/ANIM/NODA/PEXT")

    # ── Spring force output ───────────────────────────────────────
    lines.append("/ANIM/SPRING/FORC")

    lines.append("#")
    return lines


def _make_engine_implicit(state: ConversionState) -> List[str]:
    if state.is_modal:
        # Normal-modes (/EIG) → one-shot linear eigensolve, not the QSTAT/NONLIN
        # time-marching engine below.
        return _make_engine_modal(state)
    if not state.is_implicit:
        return []
    gen  = state.ctrl_implicit_gen
    dyn  = state.ctrl_implicit_dyn
    auto = state.ctrl_implicit_auto

    dt0_in = gen.dt0    if gen  and gen.dt0    > 0 else 0.01
    dtmax  = auto.dtmax if auto and auto.dtmax > 0 else 0.0
    iteopt = auto.iteopt if auto else 0

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

    # /IMPL/NONLIN/N data line (Reference Guide p.2969-2970): L_A  Itol  Toli
    #   L_A  = max iterations between stiffness-matrix reforms (0 -> 6 for the
    #          direct/MUMPS solver; smaller = fresher tangent). Default 2 here for
    #          robust convergence on rigid-body-contact models (the default 6 left
    #          the tangent too stale: |r|/|r0| plateaued ~7e-3 and never dropped).
    #   Itol = termination criterion (1=energy, 2=force, 3=displacement).
    #   Toli = tolerance. The force default is 5e-3; we use 1e-2 (Altair's own
    #          combined-criteria force default), which clears the ~7e-3 residual
    #          plateau seen when a free rigid body engages contact.
    # Overridable from LS-DYNA *CONTROL_IMPLICIT_SOLUTION: ilimit -> L_A, and
    # rctol/ectol/dctol -> Itol(2/1/3) + Toli (whichever tolerance the user set).
    sol = state.ctrl_implicit_sol
    l_a, itol, toli = 2, 2, 0.01
    if sol:
        if sol.ilimit and sol.ilimit > 0:
            l_a = sol.ilimit
        # OpenRadioss Toli is a RELATIVE convergence tolerance, so a sane value is
        # 0 < Toli < 1. Accept the tightest LS-DYNA tolerance the user actually set
        # but ignore implausible values (>= 1.0): those do not come from a real
        # "100%+ tolerance" but from a mis-aligned fixed-format card — e.g. an
        # all-blank leading card in *CONTROL_IMPLICIT_SOLUTION collapses (blank
        # lines are dropped during parsing), shifting the next card's columns so a
        # stray value lands in the dctol slot. Falling back to the robust default
        # avoids silently emitting a useless tolerance (Toli=2.0 => the solver
        # "converges" at iteration 1 and the reaction force is meaningless).
        if sol.rctol and 0.0 < sol.rctol < 1.0:      # force (LS-DYNA rctol)
            itol, toli = 2, sol.rctol
        elif sol.ectol and 0.0 < sol.ectol < 1.0:    # energy (LS-DYNA ectol)
            itol, toli = 1, sol.ectol
        elif sol.dctol and 0.0 < sol.dctol < 1.0:    # displacement (LS-DYNA dctol)
            itol, toli = 3, sol.dctol
        for name, val in (("rctol", sol.rctol), ("ectol", sol.ectol), ("dctol", sol.dctol)):
            if val and val >= 1.0:
                state.warn(
                    f"*CONTROL_IMPLICIT_SOLUTION {name}={val:g} is >= 1.0 (not a valid "
                    "relative tolerance); ignored. This usually means an all-blank "
                    "leading card shifted the fixed-format columns — check the card. "
                    f"Using robust /IMPL/NONLIN default Toli={toli:g}.")
    lines: List[str] = ["/IMPL/NONLIN/1", "# L_A Itol Toli",
                        f"  {l_a} {itol} {toli:g}"]

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
        # /IMPL/QSTAT/DTSCAL: inertia-stabilization scale; stabilization grows as
        # 1/DTSCAL^2 (Reference Guide p.2973). 0.1 (=> x100 stiffness) anchors free
        # rigid bodies connected only by contact. For nonlinear analysis it only
        # affects convergence speed, not the result, so a strong (small) value is
        # safe. (The SEAT example's 1000 is too weak for free-body-via-contact:
        # the body sloshed in its rigid mode and the solve never converged.)
        #
        # The deformable-deformable contact recipe tightens this to 0.05 (=> x400):
        # a compliant contact under force control adds a soft mode that 0.1 leaves
        # a step-overshoot 2-cycle on, while 0.01 over-damps and freezes the solve;
        # 0.05 anchors it without over-stiffening the tangent. Physics-neutral for
        # nonlinear analysis (the stabilization vanishes at equilibrium). See
        # _warn_deformable_deformable_contact.
        dtscal = "0.05" if _recipe_active(state) else "0.1"
        lines += ["/IMPL/QSTAT/DTSCAL", f" {dtscal}"]

    # /IMPL/SOLVER format (Reference Guide p.2976-2978):
    #   /IMPL/SOLVER/N  with data card: Iprec  It_max  Itol  Tol
    # N=2 is MUMPS direct solver. (N=7 Auto solver is NO LONGER SUPPORTED
    # in OpenRadioss 2024+ per MESSAGE ID 296 — it now falls back to MUMPS.)
    #
    # MUMPS memory mode: /IMPL/MUMPS/AUTOCORE. MUMPS starts in-core (fast, no
    # disk I/O) and automatically switches to out-of-core ONLY if the factors do
    # not fit in available memory (Altair Radioss 2026 /IMPL/MUMPS/AUTOCORE).
    # This supersedes the two older modes we used to choose between by mesh size:
    #   - /IMPL/MUMPS/AUTOC is OBSOLETE (and in this build never reliably spilled
    #     to disk, so it crashed silently when the factors overflowed RAM);
    #   - /IMPL/MUMPS/OUTCORE forces always-on-disk streaming -- safe but slow.
    # AUTOCORE gives in-core speed with an automatic disk fallback, so one mode
    # covers both the ~190k-node hr-anlenkung and the ~834k-node / 2.4M-DOF
    # elevator-linkage. Validated on the elevator (np=1 -nt 12): runs in-core and
    # writes results, far faster than OUTCORE. Hand-edit this to
    # /IMPL/MUMPS/OUTCORE only to force disk streaming on a RAM-starved machine.
    lines += ["/IMPL/PRINT/NONL/-1",
              "/IMPL/SOLVER/2", "  0 0 0 0",
              "/IMPL/MUMPS/AUTOCORE",
              "/IMPL/DTINI", _f(dt0)]
    lines += ["/IMPL/DT/STOP", f"{_f(dtmin)}{_f(dtmax)}"]
    # /IMPL/DT/2 data: It_w  L_arc  L_dtn  Tsca_dn  Tsca_up
    # (Reference Guide p.2981)
    #   It_w   = converge-iter threshold for time-step increase (default 6).
    #            LS-DYNA *CONTROL_IMPLICIT_AUTO ITEOPT maps here when given.
    #   L_arc  = arc length (0 = auto)
    #   L_dtn  = MAX iterations before a timestep cut. 0 => engine default (20).
    #            We do NOT force a non-default value by default: a higher cap is
    #            only needed for the slow LINEAR force-residual convergence of a
    #            deformable-deformable penalty contact (~30 iters/step), so it
    #            ships behind the opt-in deformable-contact recipe (L_dtn=50),
    #            announced by _warn_deformable_deformable_contact. (LS-DYNA KFAIL
    #            is "failed steps before abort", NOT this per-step cap, so it is
    #            never written into this slot.)
    #   Tsca_dn = scale for decreasing (0 = 0.67)
    #   Tsca_up = scale for increasing (0 = 1.1)
    it_w = iteopt if iteopt > 0 else 8
    l_dtn = 50 if _recipe_active(state) else 0
    lines += ["/IMPL/DT/2", f"{_i(it_w)}{_i(0)}{_i(l_dtn)}{_i(0)}{_i(0)}"]

    # /IMPL/DT/FIXPOINT — force the implicit time-step controller to land EXACTLY
    # on evenly spaced times (k/N × the run end, for k = 1 … N) so a clean
    # animation / time-history state is produced at each milestone instead of
    # wherever the variable implicit step happens to fall. Without it the auto
    # time step (/IMPL/DT/2) can stride past a requested output time, and that
    # interval's animation is then written late, at the overshooting time. The
    # engine reads the points free-format over as many lines as supplied, sorts
    # them ascending and caps the list at 100 (OpenRadioss
    # engine/source/input/freimpl.F). It is honoured by /IMPL/DT/1 and /IMPL/DT/2
    # (our default); only /IMPL/DT/3 (RIKS) ignores it. N is
    # options.fixpoint_count (default 100 → a point every 1% of the run); we
    # clamp it to the engine's 1…100 range here, and 0 disables the card.
    n_fix = min(max(int(state.options.fixpoint_count), 0), 100)
    if n_fix > 0 and state.ctrl_termination and state.ctrl_termination.endtim > 0:
        endtim = state.ctrl_termination.endtim
        fixpts = [endtim * k / n_fix for k in range(1, n_fix + 1)]  # 1/N … N/N
        lines.append("/IMPL/DT/FIXPOINT")
        for i in range(0, len(fixpts), 5):                   # ≤5 fields → ≤100 cols
            lines.append("".join(_f(t) for t in fixpts[i:i + 5]))

    lines.append("#")
    return lines


def _make_engine_cpu(state: ConversionState) -> List[str]:
    if not state.ctrl_cpu:
        return []
    return ["/CPU", f"{_f(state.ctrl_cpu.cputim)}         2", "#"]


def _make_starter_cloads(state: ConversionState) -> List[str]:
    """/CLOAD is a Starter keyword – concentrated loads on node groups.

    Card layout (one 100-col data card after the title — same columns from
    radioss51 through 2026; cfg radioss2023+ reads cols 51-60 as Itypfun,
    older input versions blank-skip them):
      fct_IDT(10) Dir(10) skew_ID(10) sens_ID(10) grnd_ID(10) Itypfun(10)
      Ascalex(20) Fscaley(20)
    Itypfun stays BLANK (= default 1, abscissa is time, matching
    *LOAD_RIGID_BODY LCID semantics): /BEGIN-2022 readers flag any non-blank
    text in skipped columns with WARNING 100214 "unsupported field exists",
    while 2023+ readers take blank as 1 — blank is warning-free either way.
    """
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
                "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
                f"{_i(lb.lcid)}{dir_str.rjust(10)}{_i(lb.cid)}         0{_i(ind_grnod_id)}"
                f"          {_f(1.0)}{_f(sf)}",
                HDR,
            ]
            load_id += 1
            emitted = True

    return lines if emitted else []


def _make_modal_dummy_cload(state: ConversionState,
                            rigid_nodes: Set[int]) -> List[str]:
    """Dummy unit load for the modal stiffness-export run.

    The implicit engine refuses to start a solve with no loading data at all
    (MESSAGE ID 79 ``SOLVER IMPLICIT STOPPED DUE TO LOADING DATA``) — and a
    modal deck usually has none, because its LS-DYNA loads (e.g. gravity) are
    irrelevant to the eigenproblem and are skipped by the conversion. So give
    the one /IMPL/LINEAR step a unit /CLOAD on a free structural node: the
    exported stiffness matrix is load-independent, and the resulting static
    solution doubles as the validation reference — the same load solved
    offline (``tools/modal_solve.py --static <node> Z 1``) must reproduce the
    engine displacements to ~0% (exact-K check; W14 bogie: 0.000%).
    """
    if not state.is_modal or state.options.emit_eig:
        return []
    if (state.load_rigid_bodies or state.pressure_loads
            or state.prescribed_motions or state.prescribed_motion_sets):
        return []                       # the deck already loads something
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2))
    constrained: Set[int] = set()
    for bc in state.bcs_spcs:
        constrained.update(state.node_sets.get(bc.nsid, ("", []))[1])
    candidates = elem_nodes - constrained - rigid_nodes
    if not candidates:
        state.warn(
            "Modal stiffness-export run has no load and no free node to put a "
            "dummy /CLOAD on — the engine will stop with MESSAGE ID 79. Add "
            "any load to the deck manually.")
        return []
    node = max(candidates)              # deterministic, away from low-id corners
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    funct_id = state.next_id()
    grnod_id = state.next_id()
    cload_id = state.next_id()
    state.warn(
        "Modal stiffness-export run: the deck has no load, but the implicit "
        "engine refuses to start without loading data (MESSAGE ID 79). Added "
        f"a dummy unit /CLOAD (node {node}, dir Z). The exported stiffness "
        "matrix is load-independent; the static solution can be cross-checked "
        f"with: tools/modal_solve.py <matrix> --static {node} Z 1"
    )
    lines = [
        "#-  DUMMY STATIC LOAD (modal stiffness-export run needs loading data):",
        HDR,
        f"/FUNCT/{funct_id}",
        "const_unit_load",
        "#                  X                   Y",
        f"{_f(0.0)}{_f(1.0)}",
        f"{_f(max(2.0 * endtim, 1.0))}{_f(1.0)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, "modal_dummy_load_node", [node])
    lines += [
        f"/CLOAD/{cload_id}",
        "modal_dummy_static_load",
        "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
        f"{_i(funct_id)}{'Z'.rjust(10)}{_i(0)}         0{_i(grnod_id)}"
        f"          {_f(1.0)}{_f(1.0)}",
        HDR,
    ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Top-level assemblers
# ─────────────────────────────────────────────────────────────────────────────

def _make_damping(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """Emit /DAMP from *DAMPING_GLOBAL and *DAMPING_PART_STIFFNESS.

    Rayleigh damping: C = α·M + β·K.
    - α from *DAMPING_GLOBAL valdmp (mass-proportional, damps low-freq modes)
    - β from *DAMPING_PART_STIFFNESS coef (stiffness-prop, damps high-freq waves)

    OpenRadioss /DAMP (Reference Guide p.130):
    - Format 1: single α, all DOFs
    - Format 2: per-DOF α and β, 6 lines

    Target nodes:
    - If *DAMPING_PART_STIFFNESS specifies parts, damp those parts' nodes only
    - Otherwise damp all deformable nodes (non-rigid-body)
    OpenRadioss /DAMP does NOT accept grnod_ID=0 as "all nodes" — we always
    emit an explicit /GRNOD/NODE block.

    Note: LS-DYNA's per-part β semantics (β_part = 2·coef/ω_max) cannot be
    exactly preserved without ω_max — we pass the largest coef as-is and warn
    if multiple parts have different values.
    """
    if state.damping_global is None and not state.damping_part_stiffness:
        return []

    alpha = state.damping_global.valdmp if state.damping_global else 0.0
    # Aggregate β from *DAMPING_PART_STIFFNESS — use max coef across all parts
    beta = 0.0
    target_pids: Set[int] = set()
    if state.damping_part_stiffness:
        coefs = [d.coef for d in state.damping_part_stiffness]
        beta = max(coefs)
        target_pids = {d.pid for d in state.damping_part_stiffness}
        unique_pids = sorted(target_pids)
        if len(set(coefs)) > 1:
            state.warn(
                f"*DAMPING_PART_STIFFNESS: multiple different coefs across parts "
                f"{unique_pids} - using max={beta:.6G} as global beta (per-part "
                f"damping not directly mappable to /DAMP)."
            )
        state.warn(
            f"*DAMPING_PART_STIFFNESS pid(s) {unique_pids}: coef={beta:.6G} "
            f"used as /DAMP beta directly. LS-DYNA scales by 2/omega_max"
            f" - if waves aren't damped enough, try beta ~ 1e-7 to 1e-6."
        )

    # Resolve target node set
    if target_pids:
        target_nodes = sorted(
            {n for e in state.shell_elems if e.pid in target_pids
             for n in e.nodes if n > 0 and n not in rigid_nodes}
            | {n for e in state.solid_elems if e.pid in target_pids
               for n in e.nodes if n > 0 and n not in rigid_nodes}
        )
        grnod_title = f"damping_target_pids_{'_'.join(str(p) for p in sorted(target_pids))}"
    else:
        # No specific parts → all deformable nodes (rigid bodies excluded —
        # they translate as a unit, damping their nodes is meaningless)
        target_nodes = sorted(
            {n for e in state.shell_elems
             if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
             for n in e.nodes if n > 0 and n not in rigid_nodes}
            | {n for e in state.solid_elems
               if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
               for n in e.nodes if n > 0 and n not in rigid_nodes}
        )
        grnod_title = "damping_target_all_deformable"

    if not target_nodes:
        state.warn("*DAMPING_*: no target deformable nodes found - /DAMP not emitted.")
        return []

    grnod_id = state.next_id()
    damp_id = state.next_id()
    lines = _emit_grnod_node(grnod_id, grnod_title, target_nodes)

    # If only α and no β, use Format 1 (simpler, smaller deck)
    if beta == 0.0:
        d = state.damping_global
        per_dof = (d.stx, d.sty, d.stz, d.srx, d.sry, d.srz)
        if any(s != 0.0 for s in per_dof):
            state.warn(
                f"*DAMPING_GLOBAL: per-DOF scale factors (stx..srz) ignored; "
                f"using uniform alpha={alpha:.6G} on all DOFs (/DAMP Format 1)."
            )
        # The /DAMP card always reads Beta from cols 21-40 — there is no
        # "alpha-only" card layout. Beta must be written explicitly as 0,
        # otherwise the grnod_ID digits land in the Beta field and are parsed
        # as a (huge) stiffness-damping coefficient.
        lines += [
            f"/DAMP/{damp_id}",
            f"Rayleigh mass damping (alpha={alpha:.6G})",
            "#               alpha                beta   grnod_ID   skew_ID              Tstart               Tstop",
            f"{_f(alpha)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
            HDR,
        ]
        return lines

    # Format 2: per-DOF α + β. Use uniform (αx=αy=...=α, βx=βy=...=β).
    title = f"Rayleigh damping (alpha={alpha:.6G}, beta={beta:.6G})"
    lines += [
        f"/DAMP/{damp_id}",
        title,
        "#               alpha                beta   grnod_ID   skew_ID              Tstart               Tstop",
        f"{_f(alpha)}{_f(beta)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        HDR,
    ]
    return lines


def _make_starter_th_inter(state: ConversionState) -> List[str]:
    """Emit /TH/INTER so contact-interface forces reach the T01 time-history file.

    Two requesters share the block:
      * *CONTACT_FORCE_TRANSDUCER → /INTER/SUB: a sub-interface's force is
        written as a channel of its parent interface, so the parent interface
        must be requested in a /TH/INTER block.
      * *DATABASE_NCFORC (nodal contact forces): OpenRadioss has no per-node
        contact-force time history (no /TH/NODE contact variable exists), so
        the request maps to the per-interface force resultants of EVERY
        converted contact interface here (T01, /TFILE frequency); the
        nodal-resolution view is the contact-force/pressure animation vectors
        /ANIM/VECT/CONT + /ANIM/VECT/PCONT the engine deck already carries.
    Only emitted when a transducer or *DATABASE_NCFORC exists, so other decks
    are unchanged.
    """
    all_inter_ids = ([c.inter_id for c in state.contacts_single]
                     + [c.inter_id for c in state.contacts_surf2surf]
                     + [c.inter_id for c in state.contacts_tied])
    want_ncforc = bool(state.db_ncforc_dt) and bool(all_inter_ids)
    if state.db_ncforc_dt and not all_inter_ids:
        state.warn(
            "*DATABASE_NCFORC requested but no *CONTACT was converted — "
            "there is no interface to output (no /TH/INTER emitted).")
    if not state.th_sub_ids and not want_ncforc:
        return []
    # List the parent interface (total contact force) and each force-transducer
    # sub-interface id — a sub-interface is written to the T01 only when its own
    # id is requested here (listing just the parent leaves OUTPUT TO TH = 0).
    ids: List[int] = []
    if state.th_sub_ids:
        parent_id = _select_parent_interface(state)
        if parent_id is not None:
            ids.append(parent_id)
        ids += [sid for sid, _ in state.th_sub_ids]
    if want_ncforc:
        state.warn(
            "*DATABASE_NCFORC (nodal contact forces): OpenRadioss has no "
            "per-node contact-force time history — mapped to /TH/INTER force "
            "resultants for every converted contact interface (T01 file, "
            "/TFILE frequency). The per-node field is in the animation "
            "vectors /ANIM/VECT/CONT + /ANIM/VECT/PCONT (at the /ANIM/DT "
            "frequency), which the engine deck emits by default.")
        ids += [i for i in all_inter_ids if i not in ids]
    if not ids:
        return []
    lines = [
        "#-  TIME HISTORY (interface / force-transducer):", HDR,
        "/TH/INTER/1",
        "TH_interface_forces",
        "#     var1",
        "DEF",
    ]
    lines += [_i(i) for i in ids]
    lines.append(HDR)
    return lines


def _make_starter_th_node_reac(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Emit /TH/NODE writing reaction + displacement on the master node of each
    displacement-/velocity-controlled rigid body.

    Under displacement control the reaction at the imposed-motion node IS the
    load being 'measured' (the force the structure pushes back with). For a rigid
    body that reaction is assembled at the /RBODY master node, so REACX/Y/Z there
    gives the applied force vs. the imposed DX/Y/Z. This complements the
    /INTER/SUB force transducer as an independent reaction readout. Only emitted
    when a *BOUNDARY_PRESCRIBED_MOTION_RIGID exists, so other decks are unchanged.
    """
    if not state.prescribed_motions:
        return []
    nodes: List[int] = []
    seen: Set[int] = set()
    for pm in state.prescribed_motions:
        info = rbody_info.get(pm.pid)
        if not info:
            continue
        nd = info["ind_node"]
        if nd not in seen:
            seen.add(nd)
            nodes.append(nd)
    if not nodes:
        return []
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (imposed-motion reaction force on rigid-body master):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_reaction",
        "#  reaction (REACX/Y/Z) + displacement (DX/Y/Z) of the master node",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in ("DX", "DY", "DZ", "REACX", "REACY", "REACZ")),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines


def _make_starter_th_surf(state: ConversionState) -> List[str]:
    """*DATABASE_BINARY_BLSTFOR → /TH/SURF (P, A) on each blast-loaded surface.

    LS-DYNA's blstfor binary database records the blast pressure applied to
    the *LOAD_BLAST_SEGMENT[_SET] segments over time. OpenRadioss has no
    per-segment binary equivalent, but /LOAD/PBLAST feeds three outputs that
    together carry the same information (engine pblast_1.F):
      * /TH/SURF on the loaded /SURF/SEG — the P channel is the surface-
        average external pressure, A the loaded area (P*A = total blast
        force), written to the T01 at the /TFILE frequency;
      * /ANIM/NODA/PEXT — the nodal blast-pressure fringe (the spatial
        pressure field the blstfor file is fringed for in LS-PrePost);
      * /ANIM/VECT/FEXT — the external (blast) nodal force vectors.
    The two /ANIM options are added engine-side at the /ANIM/DT frequency.
    Emitted only when the deck requests *DATABASE_BINARY_BLSTFOR, so other
    decks are unchanged.
    """
    if not state.db_blstfor_dt:
        return []
    if not state.blast_surf_ids:
        state.warn(
            "*DATABASE_BINARY_BLSTFOR requested but no blast-loaded surface "
            "was emitted (no /LOAD/PBLAST) — there is no blast pressure to "
            "output (no /TH/SURF emitted).")
        return []
    state.warn(
        "*DATABASE_BINARY_BLSTFOR: no binary blast database exists in "
        "OpenRadioss — mapped to /TH/SURF (P = average blast pressure, "
        "A = loaded area; T01 at the /TFILE frequency) on the /LOAD/PBLAST "
        "surface plus /ANIM/NODA/PEXT (nodal pressure fringe) and "
        "/ANIM/VECT/FEXT (external force vectors) at the /ANIM/DT frequency.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_BINARY_BLSTFOR -> blast surface pressure):", HDR,
        f"/TH/SURF/{th_id}",
        "TH_blast_surf",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "#     var1      var2",
        "".join(v.rjust(10) for v in ("P", "A")),
    ]
    lines += [_i(sid) for sid, _title in state.blast_surf_ids]
    lines.append(HDR)
    return lines


def _spc_constrains_rotations(state: ConversionState) -> bool:
    """True when any *BOUNDARY_SPC constrains a rotational DOF — gates the
    REACXX/YY/ZZ /TH channels and the /ANIM/VECT/MREAC moment vectors."""
    return any(bc.dofrx or bc.dofry or bc.dofrz for bc in state.bcs_spcs)


def _make_starter_th_node_spc(state: ConversionState, rbody_info: Dict) -> List[str]:
    """*DATABASE_SPCFORC → /TH/NODE with REACX/Y/Z (+REACXX/YY/ZZ) on every
    /BCS-constrained node.

    LS-DYNA's spcforc file lists the SPC reaction force (and, for rotational
    constraints, moment) per constrained node. OpenRadioss computes exactly
    that when reaction output is requested: /TH/NODE REAC* (or /ANIM/VECT/
    FREAC) switches the engine's constraint-reaction assembly on (engine
    reactions.F), so REACX/Y/Z on the /BCS node groups IS the spcforc
    content, written to the T01 at the /TFILE frequency. Rigid-body member
    nodes are mapped to the /RBODY master node — the /BCS acts there and the
    reaction is assembled there. The whole-model nodal-field view is added
    engine-side as /ANIM/VECT/FREAC (+MREAC). Emitted only when the deck
    requests *DATABASE_SPCFORC, so other decks are unchanged.
    """
    if not state.db_spcforc_dt:
        return []
    if not state.bcs_spcs:
        state.warn(
            "*DATABASE_SPCFORC requested but the deck has no *BOUNDARY_SPC — "
            "no node is SPC-constrained, so there is no reaction to output "
            "(no /TH/NODE emitted).")
        return []
    node_to_ind = {}
    for pid, info in rbody_info.items():
        for node in info["nodes"]:
            node_to_ind[node] = info["ind_node"]
    mapped: Set[int] = set()
    for bc in state.bcs_spcs:
        for n in state.node_sets.get(bc.nsid, ("", []))[1]:
            mapped.add(node_to_ind.get(n, n))
    nodes = sorted(mapped)
    if not nodes:
        state.warn(
            "*DATABASE_SPCFORC: every *BOUNDARY_SPC node set is empty — "
            "no /TH/NODE reaction output emitted.")
        return []
    if len(nodes) > 1000:
        state.warn(
            f"*DATABASE_SPCFORC: {len(nodes)} SPC-constrained nodes get REAC* "
            "/TH channels (matching LS-DYNA's per-node spcforc output) — the "
            "T01 file will be correspondingly large. Trim the /TH/NODE block "
            "by hand if you only need a subset.")
    th_vars = ["REACX", "REACY", "REACZ"]
    if _spc_constrains_rotations(state):
        th_vars += ["REACXX", "REACYY", "REACZZ"]
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_SPCFORC -> SPC reaction force per /BCS node):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_spc_reactions",
        "#  reaction force (REACX/Y/Z) [+ moment (REACXX/YY/ZZ)] per constrained node",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in th_vars),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines


def _make_free_node_constraints(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """Implicit guard: fix nodes attached to no element and no rigid body.

    A free node carries no stiffness, so its DOFs are zero rows in the implicit
    tangent → a singular matrix → the MUMPS factorization fails (or floods the
    solver with null pivots). LS-DYNA tolerates such reference nodes — e.g.
    *DEFINE_COORDINATE_NODES nodes (we bake those into /SKEW/FIX coordinates so
    they end up unreferenced) and lone origin markers — but OpenRadioss implicit
    does not. Constrain them (they drive nothing, so fixing them is inert).

    Nodes of a MOVING skew (/SKEW/MOV, *DEFINE_COORDINATE_NODES flag=1) are left
    free so the frame can co-rotate. Explicit runs skip this entirely.
    """
    if not state.is_implicit or not state.nodes:
        return []
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2, e.n3))
    keep_free: Set[int] = set()
    for cn in state.coord_nodes.values():
        if cn.flag == 1:
            keep_free.update((cn.n1, cn.n2, cn.n3))
    free = sorted(n for n in state.nodes
                  if n > 0 and n not in elem_nodes and n not in rigid_nodes
                  and n not in keep_free)
    if not free:
        return []
    state.warn(
        f"{len(free)} free node(s) attached to no element or rigid body were "
        "constrained with /BCS to keep the implicit tangent non-singular (e.g. "
        "*DEFINE_COORDINATE_NODES reference nodes baked into /SKEW/FIX, or origin "
        "markers). They drive nothing, so the constraint is inert."
    )
    bc_id = state.next_id()
    grnod_id = state.next_id()
    lines = [
        "#-  FREE-NODE CONSTRAINTS (implicit singularity guard):", HDR,
        f"/BCS/{bc_id}",
        "fix_free_reference_nodes",
        "#  Tra rot   skew_ID  grnod_ID",
        f"   111 111         0{_i(grnod_id)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, "free_reference_nodes", free)
    return lines


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


def build_starter(state: ConversionState, progress=None) -> str:
    _resolve_mat_plas_tab(state)
    _resolve_mat_power_law(state)

    # Optional TET10 -> TET4 linear downgrade (opt-in). Runs first so the tet10
    # snap and sliver prepasses below operate on the resulting linear mesh.
    _downgrade_tet10_to_tet4(state)

    # Straighten 10-node tet edges (mid-edge nodes -> edge midpoints) so no
    # quadratic Jacobian folds (OpenRadioss ERROR 489). Must run before nodes are
    # emitted and before CNRB centroids are computed from node coordinates.
    n_snapped = _snap_tet10_midsides(state)
    if n_snapped:
        state.warn(
            f"{n_snapped} /TETRA10 mid-edge node(s) snapped onto their edge "
            "midpoints (straight-edged sub-parametric tets) to avoid folded "
            "quadratic Jacobians (OpenRadioss ERROR 489: badly shaped 10-node "
            "tetra). Curved boundary elements are flattened slightly; remesh with "
            "better element quality to retain exact curved edges."
        )

    # Drop sliver tets (tet10 always — ERROR 489; extreme tet4 for implicit)
    # BEFORE any section is built, so the free-node guard sees the post-drop
    # connectivity and constrains any node the drops left unattached.
    _screen_sliver_tets(state)

    rbody_lines, rigid_nodes, rbody_info = _make_rbodies(state)
    # *CONSTRAINED_NODAL_RIGID_BODY produces additional /RBODY entries that must
    # be visible to every rigid-body-keyed section below, so merge their info,
    # rigid-node set, and rad lines with the *MAT_RIGID ones.
    cnrb_lines, cnrb_rigid_nodes, cnrb_info = _make_cnrb_rbodies(state)
    rigid_nodes = rigid_nodes | cnrb_rigid_nodes
    rbody_info = {**rbody_info, **cnrb_info}
    rbody_lines = rbody_lines + cnrb_lines
    # Implicit deck without any rigid body: the engine segfaults at solver init
    # (MESSAGE ID 44) — give it an inert fully-fixed probe rigid body.
    rbody_lines = rbody_lines + _make_probe_rbody(state, rbody_info)
    state.rbody_grnods = {pid: info["grnod_id"] for pid, info in rbody_info.items()}
    state.rbody_ind_grnods = {pid: info["ind_grnod_id"] for pid, info in rbody_info.items()}

    def _rep(frac: float, label: str) -> None:
        if progress is not None:
            progress(frac, label)

    # Sections are appended in the SAME order as before; the two heavy ones
    # (nodes, elements) report sub-progress so a large mesh shows a moving bar.
    sections: List[List[str]] = []
    sections.append(_make_header(state))
    sections.append(_make_title(state))
    sections.append(_make_analysis_defaults(state))
    sections.append(_make_materials(state))
    _rep(0.08, "Writing nodes")
    sections.append(_make_nodes(
        state, progress=lambda fr: _rep(0.08 + 0.32 * fr, "Writing nodes")))
    sections.append(_make_bcs(state, rbody_info))
    sections.append(_make_skews(state))
    _rep(0.40, "Writing elements")
    sections.append(_make_parts_and_elements(
        state, progress=lambda fr: _rep(0.40 + 0.50 * fr, "Writing elements")))
    _rep(0.90, "Finalizing starter deck")
    sections.append(_make_properties(state))
    sections.append(_make_functions(state))
    sections.append(_make_extra_groups(state))
    sections.append(_make_interfaces(state, rigid_nodes))
    sections.append(_make_tied_interfaces(state, rigid_nodes))
    sections.append(_make_force_transducers(state, rigid_nodes))
    sections.append(rbody_lines)
    sections.append(_make_imposed_motions(state, rbody_info))
    sections.append(_make_imposed_motions_set(state))
    sections.append(_make_inivel(state, rbody_info))
    sections.append(_make_pressure_loads(state))
    sections.append(_make_gravity_loads(state))
    sections.append(_make_body_loads(state))
    sections.append(_make_blast_loads(state))
    sections.append(_make_detonations(state))
    sections.append(_make_fsi_coupling(state))
    sections.append(_make_ebcs(state))
    sections.append(_make_inivol_notes(state))
    sections.append(_make_control_ale_notes(state))
    sections.append(_make_starter_cloads(state))
    sections.append(_make_modal_dummy_cload(state, rigid_nodes))
    sections.append(_make_grounding_springs(state, rbody_info))
    sections.append(_make_added_masses(state, rigid_nodes))
    sections.append(_make_eig(state))
    sections.append(_make_free_node_constraints(state, rigid_nodes))
    sections.append(_make_damping(state, rigid_nodes))
    sections.append(_make_starter_th(state))
    sections.append(_make_starter_th_inter(state))
    sections.append(_make_starter_th_node_reac(state, rbody_info))
    sections.append(_make_starter_th_node_spc(state, rbody_info))
    sections.append(_make_starter_th_surf(state))
    sections.append(_make_freq_domain_notes(state))
    sections.append(_make_skipped_comment(state))
    sections.append(["/END", HDR])

    lines: List[str] = []
    for sec in sections:
        lines.extend(sec)
    _rep(1.0, "Starter deck ready")
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
