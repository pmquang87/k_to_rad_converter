"""Starter composites: the orthotropic / composite /MAT laws, the per-ply layup
properties, and the LS-DYNA AOPT → Radioss orthotropy-axis mapping.

Conversion targets (dyna2rad ``convertmats.cxx`` / ``convertprops.cxx``
semantics, card layouts from ``hm_cfg_files`` at the revision a ``/BEGIN 2022``
deck reads):

  ``*MAT_ORTHOTROPIC_ELASTIC`` (002)          → ``/MAT/LAW93``  (ORTH_HILL)
  ``*MAT_ENHANCED_COMPOSITE_DAMAGE`` (054/55) → ``/MAT/LAW127`` (ENHANCED_COMPOSITE)
                                                 [+ ``/FAIL/GENE1`` on TFAIL]
  ``*MAT_TRANSVERSELY_ANISOTROPIC_...`` (037) → ``/MAT/LAW43``  (HILL_TAB)
                                                 [+ ``/FAIL/FLD`` on ICFLD]
  ``*MAT_LAMINATED_GLASS`` (032)              → a ``/MAT/PLAS_BRIT`` (LAW27) PAIR
  ``*PART_COMPOSITE``                         → ``/PROP/TYPE51`` + ``/PROP/TYPE19``/ply

Every one of these laws registers as orthotropic- or composite-class in the
starter (``PROP_SHELL = 2``), and ``/PROP/SHELL`` (IGTYP 1) accepts only
``PROP_SHELL`` 1 or 5 (``check_mat_elem_prop_compatibility.F:173-176``) — so a
converted part that HOLDS ELEMENTS can never stay on the isotropic section
property or the starter aborts with **ERROR 3047**. Each such part therefore
gets a dedicated orthotropic property, allocated by ``_assign_composite_props``
into ``state.composite_prop_ids`` and emitted by ``_emit_composite_props``;
this is the same /PROP-split mechanism the LAW128 (MAT_103) path uses.

The "holds elements" qualifier is load-bearing: that check runs
``DO NG = 1,NGROUP`` over ELEMENT GROUPS and only then over each group's layers
(same file, the loop at its head), so a part with no elements contributes no
group and is never tested — an element-free *PART on an orthotropic law is
starter-clean, see ``_assign_composite_props``.

Note this is precisely the bug dyna2rad has: ``p_ConvertSectionShell``
(``convertprops.cxx:734-765``) matches neither MAT_054/055 nor
*MAT_ANISOTROPIC_ELASTIC, so both fall through to ``/PROP/TYPE1`` and hard-fail
the starter.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set

from ..state import (
    ConversionState,
    IntegrationShell,
    MatOrthotropicElastic,
    MatEnhancedCompositeDamage,
    MatTransverselyAnisotropic,
    MatLaminatedGlass,
    MatHill3R,
    PartComposite,
    SectionShell,
)
from .common import HDR, _f, _i, _elform_to_ishell, _vcross, _vnorm
from .materials import _add_auto_curve
from .mesh import (
    _auto_section_shell,
    _emit_prop_type9,
    _emit_skew_fix,
    _ortho_skew_axes,
)

__all__ = [
    "_resolve_composites",
    "_assign_composite_props",
    "_resolve_integration_shells",
    "_resolve_icomp_sections",
    "_fold_element_beta",
    "_make_composite_materials",
    "_emit_composite_props",
    "_emit_mat_law93",
    "_emit_mat_law127",
    "_emit_mat_law43",
    "_law43_lines",
    "_emit_mat_hill_3r",
    "_emit_mat_law32_hill",
    "_resolve_hill_3r",
    "_emit_mat_law27_pair",
    "_emit_prop_type11",
    "_emit_prop_type51",
    "_emit_prop_type19",
    "_composite_ref_axis",
    "_composite_material_mids",
]

# LAW93 is an orthotropic HILL-PLASTICITY law; MAT_002 is purely elastic, so the
# yield surface is pushed out of reach and the Hill ratios left isotropic.
_LAW93_ELASTIC_SIGY = 1.0e30
# Radioss default transverse-shear reduction factor (5/6).
_ASHEAR_DEFAULT = 0.833333
# TYPE11 layer count clamp — dyna2rad clamps *SECTION_SHELL NIP the same way.
_MAX_SHELL_LAYERS = 10
# Layer clamp for an *INTEGRATION_SHELL-driven layup: the /PROP/TYPE11 card's
# own limit, "NIP <= 100" (prop_p11_sh_sandw.cfg:121). Deliberately NOT
# _MAX_SHELL_LAYERS: that 10 mirrors dyna2rad's cap on a plain *SECTION_SHELL
# NIP, i.e. on QUADRATURE points sampling one homogeneous material, where
# dropping points costs through-thickness resolution only. A rule's points are
# real physical layers with their own thickness and material, so clamping them
# at 10 would DELETE material from the laminate.
_MAX_RULE_LAYERS = 100
# *MAT_054/055 TFAIL: the boundary between LS-DYNA's ABSOLUTE minimum-time-step
# form (0 < TFAIL <= 0.1) and its RATIO form (TFAIL > 0.1), Manual Vol II R17
# p.2-441. Only the absolute form has a Radioss counterpart (/FAIL/GENE1 dtmin).
_TFAIL_ABSOLUTE_MAX = 0.1


def _composite_material_mids(state: ConversionState) -> Set[int]:
    """Every MID handled by this module (used by the /PROP-split prepasses)."""
    return (set(state.mat_orthotropic) | set(state.mat_enhanced_composite)
            | set(state.mat_transverse_aniso) | set(state.mat_laminated_glass)
            | set(state.mat_hill_3r))


# ─────────────────────────────────────────────────────────────────────────────
# AOPT → Radioss orthotropy reference direction
# ─────────────────────────────────────────────────────────────────────────────

class _RefAxis:
    """The resolved orthotropy reference system for one /PROP card.

    ``ip`` / ``vec`` / ``skew_id`` / ``phi`` land verbatim on the property's
    Vx-Vy-Vz-skew_ID-Ipos-Ip card; ``lines`` carries a synthesized ``/SKEW/FIX``
    when one was built. ``mapped`` is False when the AOPT mode has no Radioss
    counterpart and the caller fell back to the element frame.

    ``pt`` is the reference POINT of the two point-based solid modes (Ip=21,
    Ip=24). It is deliberately a separate field from ``vec``: on /PROP/TYPE6
    the point lives in the card-4 Px/Py/Pz columns and the vector in the
    card-3 Vx/Vy/Vz columns, and Ip=24 needs BOTH at once
    (``hm_read_prop06.F:500``).
    """

    def __init__(self, ip=20, vec=(1.0, 0.0, 0.0), skew_id=0, phi=0.0,
                 note="", mapped=True, lines=None, pt=(0.0, 0.0, 0.0)):
        self.ip = ip
        self.vec = vec
        self.pt = pt
        self.skew_id = skew_id
        self.phi = phi
        self.note = note
        self.mapped = mapped
        self.lines: List[str] = lines or []


def _axis_triad(a, d):
    """LS-DYNA AOPT=2 frame from the vectors ``a`` and ``d``: X' = a,
    Z' = a x d, Y' = Z' x X'. Returns the ``(Y', Z')`` pair /SKEW/FIX wants (its
    two vector cards are the LOCAL Y and Z axes, not X and Y), or None when
    ``a`` is null or ``d`` is missing/collinear — the caller then falls back to
    the arbitrary-transverse-pair construction, which is what dyna2rad uses for
    shells and is equivalent there (only X' survives the in-plane projection).
    """
    x = _vnorm(a)
    if x is None:
        return None
    z = _vnorm(_vcross(x, d))
    if z is None:
        return None
    y = _vcross(z, x)
    return y, z


def _composite_ref_axis(mat, state: ConversionState,
                        label: str, prop_id: int, for_solid: bool = False):
    """Map a material's LS-DYNA AOPT axis definition to a Radioss /PROP
    reference system, following dyna2rad's ``/PROP/SH_SANDW`` branch
    (``convertprops.cxx:3974-4120``) — the correct one of its several
    inconsistent AOPT handlers.

    ==========  ================================================================
    raw AOPT    Radioss
    ==========  ================================================================
    0           ``Ip=20`` — first direction from the element connectivity N1→N2,
                plus the BETA rotation. This is LS-DYNA's own AOPT=0 semantic
                (axes from element nodes 1,2,4), so it is an exact match.
    1           point P: LS-DYNA defines it for SOLIDS only. On a solid it maps
                to ``Ip=21`` (first direction from the point Pj), written to the
                /PROP/TYPE6 card-4 ``Px/Py/Pz`` columns — NOT ``Vx/Vy/Vz``,
                which the starter's Ip=21 branch never looks at; on a shell it
                has no counterpart → warn + element frame.
    2           vectors ``a`` (+ ``d``) → a synthesized ``/SKEW/FIX`` whose X' is
                ``a``, referenced with ``Ip=22`` (skew 1st axis + angle φ).
    3           vector ``v`` → ``Ip=23`` (V + angle φ), ``Vx/Vy/Vz = v``. Note
                that in BOTH codes direction 1 is the CROSS PRODUCT of ``v``
                with the element normal, so ``v`` is transverse to the fibre —
                the mapping is 1:1 but the vector is not the fibre direction.
    4           ``v`` + point P (cylindrical): on a solid ``Ip=24`` carries both
                (V on card 3, P on card 4); on a shell there is no single global
                direction → warn.
    < 0         ``|AOPT|`` is a ``*DEFINE_COORDINATE_*`` CID, which k2rad already
                emits as ``/SKEW`` under that same id → ``Ip=0`` + ``skew_ID``.
    ==========  ================================================================

    Two deliberate divergences from dyna2rad, both defect-class:

    * dyna2rad's ``/PROP/TYPE51`` branch (``convertprops.cxx:3608-3634``) reads
      the AOPT=1 *point* out of the ``a`` slots and its ``AOPT < 0`` branch is
      DEAD CODE (``axisOptFlag`` is never negative after the cfg's enum remap),
      so a ``*PART_COMPOSITE`` with a ``*DEFINE_COORDINATE`` system silently
      loses its material axes entirely. Here every branch is either converted or
      warned, on both property types.
    * dyna2rad applies BETA only when ``> 0``, silently dropping a negative
      rotation. A negative BETA is a legal LS-DYNA rotation, so it is applied
      whenever nonzero.
    """
    aopt_raw = getattr(mat, "aopt", 0.0)
    aopt = int(round(aopt_raw)) if abs(aopt_raw - round(aopt_raw)) < 1e-9 else None
    # MAT_002 spells the material-axis rotation BETA; MAT_054 spells it MANGLE
    # (card 3 field 7) and keeps BETA for the shear-term weighting. dyna2rad
    # never reads MANGLE at all — carrying it is a fidelity fix.
    beta = getattr(mat, "beta", 0.0)
    if isinstance(mat, MatEnhancedCompositeDamage):
        beta = mat.mangle
    a = (getattr(mat, "a1", 0.0), getattr(mat, "a2", 0.0), getattr(mat, "a3", 0.0))
    d = (getattr(mat, "d1", 0.0), getattr(mat, "d2", 0.0), getattr(mat, "d3", 0.0))
    v = (getattr(mat, "v1", 0.0), getattr(mat, "v2", 0.0), getattr(mat, "v3", 0.0))
    p = (getattr(mat, "xp", 0.0), getattr(mat, "yp", 0.0), getattr(mat, "zp", 0.0))

    if aopt is not None and aopt < 0:
        cid = abs(aopt)
        if cid in state.coord_sys or cid in state.coord_nodes \
                or cid in state.coord_vectors:
            return _RefAxis(ip=0, vec=(0.0, 0.0, 0.0), skew_id=cid, phi=0.0,
                            note=(f"AOPT={aopt_raw:g} → the *DEFINE_COORDINATE "
                                  f"system {cid}, which is emitted as /SKEW/{cid} "
                                  "(Ip=0: the skew's 1st axis is the material "
                                  "direction 1)"))
        state.warn(
            f"{label}: AOPT={aopt_raw:g} references *DEFINE_COORDINATE id {cid}, "
            "which is NOT defined in the deck — the orthotropy axes fall back to "
            "the element frame (Ip=20, material direction 1 = element N1→N2). "
            "Add the *DEFINE_COORDINATE_SYSTEM/_VECTOR/_NODES card, or set the "
            "reference direction on the /PROP by hand. (dyna2rad loses a "
            "negative AOPT on /PROP/TYPE51 entirely and silently — its handler "
            "is dead code.)")
        return _RefAxis(ip=20, phi=beta, mapped=False,
                        note=f"AOPT={aopt_raw:g} (undefined coordinate id {cid})")

    if aopt == 0:
        return _RefAxis(ip=20, phi=beta,
                        note=("AOPT=0 → Ip=20, material direction 1 from the "
                              "element connectivity N1→N2 (LS-DYNA's own "
                              "element-node convention)"
                              + (f", rotated by {beta:g}deg" if beta else "")))
    if aopt == 2 and any(a):
        axes = _axis_triad(a, d) or _ortho_skew_axes(a, 0.0)
        if axes is not None:
            skew_id = state.reserve_skew_id(prop_id)
            note = (f"AOPT=2 global vector a=({a[0]:g}, {a[1]:g}, {a[2]:g})"
                    + (f" with d=({d[0]:g}, {d[1]:g}, {d[2]:g})" if any(d) else "")
                    + f" → /SKEW/FIX {skew_id} (X'=a), Ip=22"
                    + (f" + Phi={beta:g}deg" if beta else ""))
            return _RefAxis(ip=22, vec=(0.0, 0.0, 0.0), skew_id=skew_id, phi=beta,
                            note=note,
                            lines=_emit_skew_fix(
                                skew_id, f"COMPOSITE_ORTHO_SKEW_{skew_id}",
                                (0.0, 0.0, 0.0), axes[0], axes[1]))
    if aopt == 3 and any(v):
        return _RefAxis(ip=23, vec=v, phi=beta,
                        note=(f"AOPT=3 vector v=({v[0]:g}, {v[1]:g}, {v[2]:g}) → "
                              "Ip=23, i.e. material direction 1 = v CROSSED "
                              "with the element normal — v itself is transverse "
                              "to the fibre, not along it (LS-DYNA Vol II R17 "
                              "p.2-385 'the cross product of the vector v with "
                              "the element normal'; Radioss corthini.F CASE(23) "
                              "computes n x v, the same axis)"
                              + (f" + Phi={beta:g}deg" if beta else "")))
    if aopt == 1 and for_solid and any(p):
        return _RefAxis(ip=21, vec=(0.0, 0.0, 0.0), pt=p, phi=beta,
                        note=(f"AOPT=1 point P=({p[0]:g}, {p[1]:g}, {p[2]:g}) → "
                              "/PROP/TYPE6 Ip=21 with P on the card-4 Px/Py/Pz "
                              "columns (direction 1 = element centre → P)"))
    if aopt == 4 and for_solid and any(v):
        return _RefAxis(ip=24, vec=v, pt=p, phi=beta,
                        note=(f"AOPT=4 cylindrical: axis v=({v[0]:g}, {v[1]:g}, "
                              f"{v[2]:g}) through P=({p[0]:g}, {p[1]:g}, "
                              f"{p[2]:g}) → /PROP/TYPE6 Ip=24, which carries "
                              "BOTH (V on card 3, P on card 4)"))

    reason = (f"AOPT={aopt_raw:g}" if aopt is not None
              else f"AOPT={aopt_raw!r} (not an integer)")
    detail = {
        1: "a reference POINT, which LS-DYNA defines for solids only",
        2: "vectors a/d, but the a-vector is null",
        3: "a reference vector v, but v is null",
        4: "a cylindrical system (v + point P), which has no single global "
           "direction on a shell",
    }.get(aopt if aopt is not None else -99,
          "an axis mode with no Radioss counterpart")
    state.warn(
        f"{label}: {reason} selects {detail} — the orthotropy reference "
        "direction falls back to the ELEMENT frame (Ip=20, material direction 1 "
        "= element N1→N2). Set Vx/Vy/Vz + Ip on the synthesized /PROP, or "
        "re-state the material axes as AOPT=0/2/3 (or a *DEFINE_COORDINATE "
        "system), if the fibre direction matters.")
    return _RefAxis(ip=20, phi=beta, mapped=False, note=reason)


# ─────────────────────────────────────────────────────────────────────────────
# Prepass: material-level resolution + warnings
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_composites(state: ConversionState) -> None:
    """build_starter prepass: allocate the ids and curves the composite
    materials need, and raise every material-level warning.

    Runs BEFORE ``_assign_composite_props`` (which needs the MAT_032 glass id to
    exist) and before ``_make_functions`` (which emits the synthesized /FUNCTs).
    """
    # ── MAT_032: allocate the synthesized GLASS companion id ────────────────
    for glass in state.mat_laminated_glass.values():
        if glass.glass_mid:
            continue
        glass.glass_mid = state.next_mat_id()
    if state.mat_laminated_glass:
        pairs = ", ".join(
            f"mid {g.mid} → polymer /MAT/LAW27/{g.mid} + glass /MAT/LAW27/"
            f"{g.glass_mid}" for g in sorted(
                state.mat_laminated_glass.values(), key=lambda m: m.mid))
        state.warn(
            "*MAT_LAMINATED_GLASS has no single Radioss counterpart: each card "
            "is split into a /MAT/PLAS_BRIT (LAW27) PAIR — a brittle glass and a "
            f"ductile polymer — bound per layer by a /PROP/TYPE11 ({pairs}). "
            "Following dyna2rad, the POLYMER keeps the LS-DYNA MID (so existing "
            "references resolve) and the GLASS takes the synthesized id.")

    # ── MAT_037: the LAW43 hardening curve ──────────────────────────────────
    for mat in state.mat_transverse_aniso.values():
        if mat.hlcid > 0:
            if mat.hlcid not in state.curves and mat.hlcid not in state.define_tables:
                state.warn(
                    f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: "
                    f"HLCID={mat.hlcid} references a *DEFINE_CURVE that is NOT in "
                    "the deck — /MAT/LAW43 is tabular-only, so the starter will "
                    "reject the dangling function id. Add the curve or clear "
                    "HLCID (SIGY/ETAN then synthesize a bilinear one).")
            mat.hard_func_id = mat.hlcid
            continue
        # LAW43 has no SIGY/ETAN slot — synthesize the bilinear hardening curve.
        #
        # MAT_037's ETAN is ALREADY the plastic hardening modulus, which is
        # exactly what the LAW43 card-6 function (stress vs PLASTIC strain)
        # wants, so it is copied verbatim. The manual is explicit that this
        # field is NOT the same quantity as *MAT_003's: Vol II R17 p.2-398 says
        # MAT_037 ETAN = "Plastic hardening modulus", against p.2-172 MAT_003
        # ETAN = "Tangent modulus, see Figure M3-1". Only the latter needs the
        # H = E*ETAN/(E-ETAN) conversion k2rad applies on the LAW44 path.
        #
        # (dyna2rad writes {(0, SIGY), (1, SIGY + |ETAN|)} here, which is the
        # same value — but it never actually BINDS the curve: a missing pair of
        # braces at convertmats.cxx:3100-3102 overwrites func_IDi[0] with
        # HLCID = 0 in both branches, leaving NUM_CURVES=1 pointing at function
        # 0 → starter ANCMSG 366. The curve is bound properly here.)
        if mat.sigy <= 0.0:
            state.warn(
                f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: "
                f"HLCID=0 and SIGY={mat.sigy:g} (<=0), so no hardening curve can "
                "be synthesized — /MAT/LAW43 is tabular-only and the starter "
                "rejects a material with no yield function (ERROR 366). Supply "
                "SIGY (+ETAN) or a HLCID curve.")
            continue
        # ETAN < 0 is LS-DYNA's flag for including the through-thickness normal
        # stresses (it needs *LOAD_SURFACE_STRESS); the hardening modulus is the
        # magnitude, exactly as R < 0 selects a scheme with |R| as the ratio.
        h = abs(mat.etan)
        if mat.etan < 0.0:
            state.warn(
                f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: "
                f"ETAN={mat.etan:g} is negative, which in LS-DYNA REQUESTS that "
                "contact/pressure normal stresses be included (and requires "
                "*LOAD_SURFACE_STRESS) rather than meaning a negative modulus. "
                "/MAT/LAW43 has no such option — the flag is DROPPED and "
                f"|ETAN|={h:g} is used as the plastic hardening modulus.")
        fid = state.next_curve_id()
        _add_auto_curve(state, fid, f"Auto_MAT037_hardening_mid{mat.mid}",
                        [(0.0, mat.sigy), (1.0, mat.sigy + h)])
        mat.hard_func_id = fid
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: HLCID=0, "
            f"so the bilinear SIGY={mat.sigy:g}/ETAN={mat.etan:g} hardening was "
            f"synthesized as /FUNCT/{fid} = [(0, {mat.sigy:g}), "
            f"(1, {mat.sigy + h:g})] — /MAT/LAW43 (HILL_TAB) is TABULAR-ONLY and "
            "has no SIGY/ETAN slot. The curve is stress vs PLASTIC strain and "
            "MAT_037's ETAN is already the PLASTIC hardening modulus (Manual "
            "Vol II R17 p.2-398), so the slope is ETAN verbatim — this field is "
            "NOT the total-curve tangent modulus that *MAT_PLASTIC_KINEMATIC "
            "spells with the same name and that needs the E*ET/(E-ET) rescale.")

    _resolve_hill_3r(state)


def _resolve_hill_3r(state: ConversionState) -> None:
    """*MAT_HILL_3R (122): pick the target law from HR and give the tabular
    branches their hardening /FUNCT.

      HR = 1  linear      → LAW43 with a synthesized bilinear curve
      HR = 2  exponential → LAW32 (analytic Swift form, no curve needed)
      HR = 3  load curve  → LAW43 with LCID

    P1/P2 for HR=1 are ``tangent modulus`` and ``yield stress`` IN THAT ORDER
    (Vol II R17 p.2-852) — dyna2rad builds ``{(0, P1), (1, P1+P2)}``, i.e. it
    reads P1 as the yield stress and P2 as the modulus, which swaps the two.
    P1 is the TOTAL-curve tangent modulus (the manual's own word for HR=1), so
    the plastic slope on a stress-vs-PLASTIC-strain curve is
    ``H = E*P1/(E-P1)`` — the same rescale /MAT/LAW44 applies to *MAT_003's
    ETAN, and deliberately NOT the verbatim copy the MAT_037 path uses (whose
    ETAN the manual calls the plastic hardening modulus, p.2-398).
    """
    for mat in state.mat_hill_3r.values():
        hr = int(round(mat.hr)) if mat.hr else 1
        if hr == 2:
            mat.use_law32 = True
            continue
        if hr == 3:
            if mat.lcid <= 0:
                state.warn(
                    f"*MAT_HILL_3R {mat.mid}: HR=3 selects the load-curve "
                    "hardening rule but LCID is 0 — /MAT/LAW43 is tabular-only "
                    "and the starter rejects a material with no yield function "
                    "(ERROR 366). Add the curve, or use HR=1 with P1/P2.")
            elif mat.lcid not in state.curves:
                # func_IDi is a FUNCTION slot, so a *DEFINE_TABLE id is not a
                # valid target either — checking state.curves only keeps the
                # diagnostic alive for that case.
                state.warn(
                    f"*MAT_HILL_3R {mat.mid}: HR=3 LCID={mat.lcid} references "
                    "a *DEFINE_CURVE that is NOT in the deck — the /MAT/LAW43 "
                    "func_IDi will dangle (starter ERROR 366).")
            mat.hard_func_id = mat.lcid
            continue
        if hr != 1:
            state.warn(
                f"*MAT_HILL_3R {mat.mid}: HR={mat.hr:g} is not one of the "
                "three documented hardening rules (1 linear / 2 exponential / "
                "3 load curve) — treated as HR=1 (linear) with P1/P2.")
        # HR = 1: sigma_Y = P2 + H*eps_p, sampled at eps_p = 0 and 1 and left
        # to the reader's linear extrapolation.
        if mat.p2 <= 0.0:
            state.warn(
                f"*MAT_HILL_3R {mat.mid}: HR=1 (linear hardening) with "
                f"P2={mat.p2:g} — P2 IS the yield stress on this card "
                "(Vol II R17 p.2-852) and it must be positive. No hardening "
                "curve can be synthesized, and /MAT/LAW43 rejects a material "
                "with no yield function (ERROR 366).")
            continue
        h = mat.p1
        if 0.0 < h < mat.E:
            h = mat.E * h / (mat.E - h)
        fid = state.next_curve_id()
        _add_auto_curve(state, fid, f"Auto_MAT122_hardening_mid{mat.mid}",
                        [(0.0, mat.p2), (1.0, mat.p2 + h)])
        mat.hard_func_id = fid
        state.warn(
            f"*MAT_HILL_3R {mat.mid}: HR=1, so the linear hardening was "
            f"synthesized as /FUNCT/{fid} = [(0, {mat.p2:g}), "
            f"(1, {mat.p2 + h:g})] — /MAT/LAW43 (HILL_TAB) is TABULAR-ONLY. "
            f"P1={mat.p1:g} is the TANGENT modulus and P2={mat.p2:g} the YIELD "
            "STRESS (Vol II R17 p.2-852, the opposite of dyna2rad's reading), "
            "and the curve is stress vs PLASTIC strain, so the slope is the "
            f"plastic modulus E*P1/(E-P1) = {h:g}.")


# ─────────────────────────────────────────────────────────────────────────────
# Prepass: per-part /PROP allocation
# ─────────────────────────────────────────────────────────────────────────────

def _warn_composite_beam_part(state: ConversionState, pid: int, mid: int,
                              own_mat_is_composite: bool,
                              is_composite_part: bool) -> None:
    """A part whose only elements are BEAMS, reached by the composite prepass.

    Split out of the element-free branch because the two are opposites. An
    element-free part is starter-clean (the compatibility loop runs per element
    GROUP and it contributes none, measured 0 ERROR(S) 0 WARNING(S)); a
    beam-only part contributes a group, and the ortho/composite laws are
    rejected on it. Measured on ``starter_win64`` (nt=6) — two ``*ELEMENT_BEAM``
    on one ``*SECTION_BEAM`` ELFORM=2, part material ``*MAT_ORTHOTROPIC_ELASTIC``
    (/MAT/LAW93) — ``1 ERROR(S)``, ``ERROR TERMINATION``::

        ERROR ID :   3046
        ** ERROR IN MATERIAL/ELEMENT COMPATIBILITY
        DESCRIPTION :
           THE FOLLOWING MATERIAL LAW/ELEMENT TYPE COMBINATIONS ARE NOT
           SUPPORTED:
           ELEMENTS OF TYPE BEAM ARE NOT COMPATIBLE WITH MATERIAL ID 2 OF
           TYPE 93

    3046 and not 3047: every composite law k2rad emits (LAW93/127/43/27) leaves
    ``PROP_BEAM`` at the 0 default from ``ini_mat_elem.F:89``, which fails the
    MATERIAL/ELEMENT test in ``check_mat_elem_prop_compatibility.F`` before any
    property is examined — so no property this prepass could synthesize would
    change the outcome, and the fix is necessarily a deck change.

    When the part's OWN material is not composite and only a ``*PART_COMPOSITE``
    brought it here, nothing is rejected: the layup is simply dropped, the same
    way the solid branch drops it, and this reports only that.
    """
    if not own_mat_is_composite:
        state.warn(
            f"*PART_COMPOSITE {pid} holds BEAM elements — the per-ply "
            "/PROP/TYPE51 layup is a SHELL property. The layup is DROPPED and "
            "the part keeps its beam property and its own *PART material; a "
            "beam has no through-thickness stack for the plies to describe.")
        return
    state.warn(
        f"Composite part {pid} holds BEAM elements and no shell or solid ones, "
        "so no orthotropic property is synthesized"
        + (" and its *PART_COMPOSITE layup is DROPPED"
           if is_composite_part else "")
        + f". This one does NOT pass the starter: mid {mid} converts to an "
        "orthotropic/composite law, and the material/element compatibility "
        "check REJECTS every one of them on a beam — measured on "
        "starter_win64, a two-element beam part on *MAT_ORTHOTROPIC_ELASTIC "
        "(mid 2, /MAT/LAW93) gives 1 ERROR(S) and ERROR TERMINATION, verbatim "
        "'ERROR ID : 3046 / ** ERROR IN MATERIAL/ELEMENT COMPATIBILITY / "
        "ELEMENTS OF TYPE BEAM ARE NOT COMPATIBLE WITH MATERIAL ID 2 OF "
        "TYPE 93'. The "
        "composite laws (LAW93/127/43/27) leave PROP_BEAM at its 0 default "
        "(ini_mat_elem.F:89), which fails the ELEMENT test in "
        "check_mat_elem_prop_compatibility.F before any property is looked "
        "at, so no synthesized property could rescue it — the DECK has to "
        "change: give the beam part a beam-capable material (*MAT_ELASTIC → "
        "/MAT/LAW1, *MAT_PLASTIC_KINEMATIC → /MAT/LAW44, *MAT_JOHNSON_COOK → "
        "/MAT/LAW2), or re-mesh it as shells if the orthotropy is the point. "
        "(The /PROP/BEAM material-compatibility warning names the same "
        "ERROR 3046 from the property side.)")


def _assign_composite_props(state: ConversionState) -> None:
    """build_starter prepass: give every composite/orthotropic part its own
    property id.

    Runs BEFORE ``_assign_ortho_props`` / ``_assign_hourglass_props`` (both skip
    a part already claimed here), before ``_make_parts_and_elements`` (which
    repoints the /PART) and before ``_make_properties`` (which suppresses the
    section's now-unused isotropic /PROP).
    """
    comp_mids = _composite_material_mids(state)
    if not comp_mids and not state.part_composites:
        return
    _resolve_part_composite_fallbacks(state)
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    beam_pids = {e.pid for e in state.beam_elems}
    shell_only_laws = {}
    for mid in state.mat_transverse_aniso:
        shell_only_laws[mid] = ("*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC",
                                "/MAT/LAW43")
    for mid, hill in state.mat_hill_3r.items():
        # LAW32 declares SHELL_ORTHOTROPIC only, exactly like LAW43.
        shell_only_laws[mid] = ("*MAT_HILL_3R",
                                "/MAT/LAW32" if hill.use_law32 else "/MAT/LAW43")
    for mid in state.mat_laminated_glass:
        shell_only_laws[mid] = ("*MAT_LAMINATED_GLASS", "/MAT/PLAS_BRIT (LAW27)")

    for pid, part in sorted(state.parts.items()):
        if pid in state.composite_prop_ids:
            continue
        pc = state.part_composites.get(pid)
        is_composite_part = pc is not None and _layup_is_convertible(pc)
        if not is_composite_part and part.mid not in comp_mids:
            continue
        if pid in beam_pids and pid not in shell_pids \
                and pid not in solid_pids:
            # NOT the element-free case below, even though "no shell or solid
            # elements" is true of it as well: this part HAS a mesh, and the
            # starter hard-fails on it. See _warn_composite_beam_part.
            _warn_composite_beam_part(state, pid, part.mid,
                                      part.mid in comp_mids, is_composite_part)
            continue
        if pid not in shell_pids and pid not in solid_pids:
            # A MESH sanity check, NOT a hard-failure prediction. This used to
            # promise starter ERROR 3047; it does not happen.
            # check_mat_elem_prop_compatibility.F runs `DO NG = 1,NGROUP` over
            # ELEMENT GROUPS and only then over each group's layers, so the
            # MAT/PROP class test never reaches a part that contributes no
            # group. Measured on starter_win64: an element-free *PART on
            # *MAT_002 (/MAT/LAW93, PROP_SHELL=2) pointing at the placeholder
            # /PROP/SHELL an element-free part gets (writer/mesh.py
            # `_element_free_part_ids`) reads 0 ERROR(S) 0 WARNING(S), and the
            # starter echoes it as an ISOTROPIC SHELL PROPERTY SET without
            # complaint. Same for *MAT_054 (/MAT/LAW127).
            state.warn(
                f"Composite part {pid}: no shell or solid elements found, so "
                "no orthotropic property is synthesized"
                + (" and its *PART_COMPOSITE layup is DROPPED"
                   if is_composite_part else "")
                + ". The part keeps its ordinary property, and the starter "
                "ACCEPTS that: its material/property compatibility check runs "
                "per ELEMENT GROUP (check_mat_elem_prop_compatibility.F loops "
                "over NGROUP), and a part with no elements contributes none. "
                "No physics goes with it either — there is no element for the "
                "orthotropy to act on. Read this as a MESH check: an "
                "orthotropic or composite material is normally written for a "
                "meshed part, so an empty one is usually a PID typo or an "
                "*INCLUDE that did not resolve. A deliberately element-free "
                "part — an *INTEGRATION_SHELL PID_i material carrier, say — is "
                "idiomatic and needs no fix.")
            continue
        if pid in solid_pids and pid not in shell_pids:
            if is_composite_part:
                state.warn(
                    f"*PART_COMPOSITE {pid} holds SOLID elements — the per-ply "
                    "/PROP/TYPE51 layup is a SHELL property. The layup is "
                    "DROPPED and the part keeps a plain solid property; convert "
                    "it via *SECTION_TSHELL with ICOMP=1 if it is a thick-shell "
                    "composite.")
                continue
            law = shell_only_laws.get(part.mid)
            if law is not None:
                state.warn(
                    f"{law[0]} on part {pid}: {law[1]} is a SHELL-ONLY law "
                    "(starter PROP_SHELL=2 with no solid class), but the part "
                    "holds solid elements. No orthotropic property is "
                    "synthesized and the starter will reject the combination — "
                    "re-mesh as shells or pick a solid-capable law.")
                continue
        state.composite_prop_ids[pid] = state.next_prop_id()


# ─────────────────────────────────────────────────────────────────────────────
# *INTEGRATION_SHELL — the user through-thickness integration rule
# ─────────────────────────────────────────────────────────────────────────────

def _part_secid(state: ConversionState, pid: int) -> int:
    """The *SECTION id a part uses (LS-DYNA lets SECID default to the PID)."""
    part = state.parts.get(pid)
    return part.secid if part is not None and part.secid > 0 else pid


def _usable_rule(state: ConversionState,
                 sec: Optional[SectionShell]) -> Optional[IntegrationShell]:
    """The *INTEGRATION_SHELL a section binds, if it can drive anything at all.

    PURE — every diagnostic behind a ``None`` here is raised exactly once by
    ``_resolve_integration_shells``, so this predicate can be called freely from
    the allocation prepass and from the emitters without duplicating warnings.
    """
    if sec is None or sec.irid <= 0:
        return None
    rule = state.integration_shells.get(sec.irid)
    if rule is None or rule.nip <= 0 or rule.esop not in (0, 1):
        return None
    if rule.esop == 1:
        # NIP equal layers, no point cards: nothing to carry beyond the layer
        # COUNT, which the resolve pass has already pushed onto sec.nip.
        return rule
    if not rule.points or sum(p.wf for p in rule.points) <= 0.0:
        return None
    return rule


def _layered_rule(state: ConversionState,
                  sec: Optional[SectionShell]) -> Optional[IntegrationShell]:
    """The rule iff it needs a LAYERED property — i.e. ESOP = 0, where the
    per-point WF/PID make the layers differ from one another. An ESOP = 1 rule
    is NIP identical layers, which the ordinary section path already emits."""
    rule = _usable_rule(state, sec)
    return rule if rule is not None and rule.esop == 0 else None


def _rule_layer_count(rule: IntegrationShell, state: ConversionState,
                      label: str) -> int:
    """How many layers an ESOP=0 rule contributes, clamped at the layered-shell
    limit. Deliberately does NOT name a property: which one carries the layup is
    only decided once the layer MATERIALS are known (see ``_type11_carries``)."""
    n = len(rule.points)
    if n > _MAX_RULE_LAYERS:
        state.warn(
            f"{label}: the rule defines {n} integration points but a layered "
            f"Radioss shell property carries at most {_MAX_RULE_LAYERS} layers "
            f"(/PROP/TYPE11 'NIP <= 100', prop_p11_sh_sandw.cfg:121) — CLAMPED "
            f"to {_MAX_RULE_LAYERS}. The dropped layers take their thickness "
            "and their material with them, so the laminate is THINNER than the "
            "deck's; merge adjacent plies of the same material to fit.")
        n = _MAX_RULE_LAYERS
    return n


def _rule_layers(state: ConversionState, rule: IntegrationShell, sec: SectionShell,
                 pid: int, prop_id: int, thick: float, angles: List[float],
                 inherit_mid: int,
                 glass: Optional[MatLaminatedGlass] = None):
    """The ordered ``(phi, thickness, mat_id)`` layer list of an ESOP=0 rule.

    ``t_i = WF_i / sum(WF) * T1`` — the sum-normalization is real, not an
    assumption that LS-DYNA's "the WF should sum to 1" convention was honoured;
    dyna2rad normalizes the same way (``convertprops.cxx:1993-1996``, verified
    against a rule with WF = 1, 2, 1 producing 0.5, 1.0, 0.5 on T1 = 2.0).

    **Layer POSITION is the cumulative-WF stack (Radioss ``Ipos = 0``), not
    ``S_i``.** ``S_i`` is a quadrature SAMPLING coordinate in [-1, +1]; a Radioss
    layer is a physical slab whose Zi is its own MIDDLE. Writing
    ``Zi = S_i*T1/2`` with ``Ipos = 1`` — which is what dyna2rad does
    (``convertprops.cxx:2015``) — makes the starter derive the shell thickness
    from the layer ENVELOPE (``stackgroup.F``: ``THICKT = max(Zi+t_i/2) -
    min(Zi-t_i/2)``), which for the canonical rule with S reaching +/-1 pushes
    half of the outer layers outside the shell and leaves gaps between the rest.
    Stacking by cumulative WF reproduces T1 exactly and tiles without gaps; the
    caller's warning quotes both numbers.

    Layer ORDER is bottom-up by ``S`` (a STABLE sort, so a rule whose S column is
    blank or constant keeps its card order, which is the same order Radioss
    ``Ipos = 0`` would stack anyway).
    """
    label = (f"*INTEGRATION_SHELL {rule.irid} on part {pid} "
             f"(*SECTION_SHELL {sec.secid})")
    n = _rule_layer_count(rule, state, label)
    pts = rule.points[:n]
    wsum = sum(p.wf for p in pts)
    if wsum <= 0.0:                       # guarded by _usable_rule; belt-and-braces
        return [], label
    missing_parts: Set[int] = set()
    tuples = []
    for i, p in enumerate(pts):
        mid = inherit_mid
        if p.pid > 0:
            src = state.parts.get(p.pid)
            if src is not None and src.mid > 0:
                mid = src.mid
            else:
                missing_parts.add(p.pid)
                mid = _rule_inherit_mid(glass, i, inherit_mid)
        else:
            mid = _rule_inherit_mid(glass, i, inherit_mid)
        phi = angles[i] if i < len(angles) else 0.0
        tuples.append((p.s, phi, thick * p.wf / wsum, mid))

    order = sorted(range(n), key=lambda k: tuples[k][0])
    if order != list(range(n)):
        state.warn(
            f"{label}: the rule's S coordinates run "
            + ("TOP-DOWN" if order == list(reversed(range(n))) else "OUT OF ORDER")
            + " ([" + ", ".join(f"{t[0]:g}" for t in tuples)
            + "]), so the layers were RE-ORDERED bottom-up before being written. "
            "LS-DYNA leaves the ordering of a user rule's integration points "
            "arbitrary (Vol I R17 Figure 29-25) but a Radioss Ipos=0 stack is "
            "built in list order from the bottom face, so the card order cannot "
            "be copied verbatim. dyna2rad copies it verbatim and relies on its "
            "explicit Zi to undo it.")
    layers = [(tuples[k][1], tuples[k][2], tuples[k][3]) for k in order]
    # Which property actually carries the layup is decided by the layer
    # MATERIALS, so it is only knowable here — and it must be, because an
    # ordinary isotropic part (the common foam-core / glass-interlayer stack)
    # lands on TYPE51 + TYPE19, not TYPE11. Naming TYPE11 unconditionally sent
    # users grepping the deck for a property that was never emitted.
    prop_kind = ("/PROP/TYPE11" if _type11_carries(state, pid, layers)
                 else "/PROP/TYPE51")

    if missing_parts:
        state.warn(
            f"{label}: integration point PID(s) "
            + ", ".join(str(q) for q in sorted(missing_parts))
            + " reference no *PART with a material, so those layers fall back to "
            f"the element's own part material {inherit_mid}"
            + ("" if glass is None else
               " (or, on this *MAT_LAMINATED_GLASS part, to the F_i glass/"
               "polymer pick)")
            + ". LS-DYNA takes the layer's constitutive constants and density "
            "from that part, so a typo there silently changes the laminate. "
            "dyna2rad resolves the same dangling handle in silence.")
    for mid in sorted({t[3] for t in tuples}):
        if not _mid_is_known(state, mid):
            state.warn(
                f"{label}: layer material {mid} is NOT emitted as a /MAT by "
                "this conversion — either the deck defines no *MAT with that "
                "id, or its law is one k2rad does not convert. The layer "
                f"carrying mat_ID={mid} on the {prop_kind}/{prop_id} "
                "synthesized for this part"
                + ("" if prop_kind == "/PROP/TYPE11" else
                   " (on its own /PROP/TYPE19 ply)")
                + " will dangle and the starter will reject the property.")
    out_of_range = [t[0] for t in tuples if abs(t[0]) > 1.0]
    if out_of_range:
        state.warn(
            f"{label}: integration point coordinate(s) ["
            + ", ".join(f"{s:g}" for s in out_of_range)
            + "] lie outside the legal S range -1 .. +1 (Vol I R17 p.29-16). "
            "They are used as written for the layer ORDER only, so the layup is "
            "still emitted, but check the rule: a point outside the shell is "
            "almost always a mis-keyed column.")
    # WF is a thickness FRACTION (Delta_t_i / t, Vol I R17 p.29-17). Only the
    # SUM is guarded upstream, so a negative weight whose sum is still positive
    # slips through and turns into a negative ply thickness — which no Radioss
    # layered property can mean anything by.
    negative_wf = [(i + 1, p.wf) for i, p in enumerate(pts) if p.wf < 0.0]
    if negative_wf:
        state.warn(
            f"{label}: integration point(s) "
            + ", ".join(f"{i} (WF={v:g})" for i, v in negative_wf)
            + " carry a NEGATIVE weighting factor. WF is a thickness FRACTION, "
            "so each of those becomes a layer of negative thickness in the "
            f"emitted {prop_kind} — physically meaningless, and the layers "
            "around it no longer stack to the section thickness. The rule is "
            "converted as written; fix the sign in the deck.")

    # The measured cost of NOT copying dyna2rad's Zi = S_i*T1/2 (see the
    # docstring). zmin/zmax reproduce stackgroup.F's envelope exactly.
    half = thick / 2.0
    zlo = min(t[0] * half - t[2] / 2.0 for t in tuples)
    zhi = max(t[0] * half + t[2] / 2.0 for t in tuples)
    state.warn(
        f"{label}: {prop_kind}/{prop_id} carries the rule's OWN "
        f"{n} layer thickness(es) ["
        + ", ".join(f"{t:g}" for _, t, _ in layers)
        + f"] (t_i = WF_i/sum(WF) * T1, T1 = {thick:g}"
        + (f", sum(WF) = {wsum:g} != 1 so the weights were NORMALIZED"
           if abs(wsum - 1.0) > 1e-9 else "")
        + ") and materials ["
        + ", ".join(str(m) for _, _, m in layers)
        + "], bottom layer first — the section thickness is NO LONGER split "
        "evenly. Layer POSITIONS are the cumulative-WF stack (Ipos=0), which "
        f"reproduces the LS-DYNA shell thickness {thick:g} exactly and tiles "
        "without gaps; the rule's S_i are quadrature sampling coordinates, not "
        f"slab centres. dyna2rad instead writes Zi = S_i*T1/2 with Ipos=1, "
        f"which makes the starter derive a {zhi - zlo:g} thick shell "
        f"({(zhi - zlo) / thick if thick else 0:.4g}x the deck's) from the "
        "layer envelope. BOTH HALVES OF THAT TRADE: the emitted stack "
        "reproduces T1 and the layer thicknesses exactly, but it integrates at "
        "the cumulative-WF layer CENTRES ["
        + ", ".join(f"{z:g}" for z in _stack_centres(layers, thick))
        + "] rather than at the rule's own sampling stations S_i*T1/2 ["
        + ", ".join(f"{tuples[k][0] * half:g}" for k in order)
        + "], so the through-thickness SAMPLING is not the deck's quadrature "
        "rule — a rule whose outermost S is +/-1 no longer samples the outer "
        "fibre, and sum(t_i * z_i^2) (hence the bending response) shifts with "
        "it. FAILOPT and the rule's S_i are the only fields not carried.")
    return layers, label


def _stack_centres(layers, thick: float) -> List[float]:
    """The mid-plane-relative Zi of each layer of a cumulative-WF (Ipos=0)
    stack — where the emitted property actually integrates. Mirrors the
    starter's own bottom-up tiling, so the numbers quoted in the conversion
    warning are the ones the echo prints."""
    z = -thick / 2.0
    out: List[float] = []
    for _, t, _m in layers:
        out.append(z + t / 2.0)
        z += t
    return out


def _type11_carries(state: ConversionState, pid: int, layers) -> bool:
    """Whether /PROP/TYPE11 can legally carry these layer materials.

    ``hm_read_prop11.F:505-563`` makes TYPE11 a **single-law** property: layer
    1's Radioss law must be 15, 25, 27 or >= 29 (ERROR 30, *"PLEASE USE ONE OF
    THE FOLLOWING COMPATIBLE MATERIAL LAWS: 15,25,27, OR > 28"*) and every other
    layer must repeat it (ERROR 334). k2rad cannot know the Radioss law behind an
    arbitrary LS-DYNA MID, but it knows the two layer sets that are law-uniform
    and whitelisted BY CONSTRUCTION:

      * every layer on the part's own ``*MAT_002``/``*MAT_054`` material
        (/MAT/LAW93, /MAT/LAW127 — both >= 29);
      * every layer on the ``*MAT_032`` glass/polymer pair, which are two
        /MAT/PLAS_BRIT (LAW27) cards.

    Everything else — a foreign ``PID_i`` material, or an ordinary isotropic
    part material — goes to /PROP/TYPE51 + /PROP/TYPE19 instead, which carries
    its materials on per-ply objects and has no law whitelist at all. That is
    also the target dyna2rad picks for this keyword.
    """
    mids = {m for _, _, m in layers}
    part = state.parts.get(pid)
    own = part.mid if part is not None else 0
    glass = state.mat_laminated_glass.get(own)
    if glass is not None:
        return mids <= {glass.mid, glass.glass_mid}
    if own in state.mat_orthotropic or own in state.mat_enhanced_composite:
        return mids <= {own}
    return False


def _emit_rule_layup(state: ConversionState, prop_id: int, pid: int, title: str,
                     sec: SectionShell, layers, thick: float, axis: "_RefAxis",
                     istrain: int) -> List[str]:
    """Emit a rule-driven layup on whichever layered property the starter
    accepts for these layer materials — TYPE11 when it legally carries them
    (see ``_type11_carries``), TYPE51 + one TYPE19 per layer otherwise."""
    if _type11_carries(state, pid, layers):
        return _emit_prop_type11(prop_id, title, sec, state, layers, thick,
                                 axis, istrain)
    ishell = _elform_to_ishell(sec.elform, state.is_implicit,
                               state.options.shell_default_ishell)
    ply_ids: List[int] = []
    ply_lines: List[str] = []
    for k, (phi, t, mid) in enumerate(layers):
        ply_prop = state.next_prop_id()
        ply_ids.append(ply_prop)
        # The per-layer angle rides on the ply's own delta_phi, applied on top
        # of the stack's reference direction — the same composition
        # *PART_COMPOSITE's per-ply B_i uses.
        ply_lines += _emit_prop_type19(ply_prop, f"{title} - layer {k + 1}"[:100],
                                       mid, t, phi)
    state.warn(
        f"/PROP for part {pid}: the *INTEGRATION_SHELL layup is emitted as "
        f"/PROP/TYPE51/{prop_id} with {len(layers)} /PROP/TYPE19 layer "
        f"propert(ies) {ply_ids} rather than a single /PROP/TYPE11, because "
        "TYPE11 is a SINGLE-LAW property — its reader accepts only Radioss "
        "laws 15, 25, 27 and >= 29 and requires every layer to repeat layer "
        "1's law (hm_read_prop11.F ERROR 30 / ERROR 334), which these layer "
        "material(s) "
        + ", ".join(str(m) for m in sorted({m for _, _, m in layers}))
        + " do not satisfy. TYPE51 carries its materials on per-ply objects and "
        "has no such whitelist; it is also dyna2rad's own target for this "
        "keyword.")
    # The CALLER owns axis.lines. _emit_composite_props already emits the
    # synthesized /SKEW/FIX before it reaches _emit_single_material_type11, and
    # the other two callers build a local _RefAxis whose .lines is empty — so
    # re-emitting them here wrote the same skew id TWICE and the starter
    # ERROR-terminated on UDOUBLE (hm_read_skw.F -> ERROR 79 DUPLICATE ID) for
    # every AOPT that synthesizes a skew.
    lines = _emit_prop_type51(prop_id, title, ishell, 0, 0.0,
                              _ASHEAR_DEFAULT, axis, ply_ids, istrain)
    return lines + ply_lines


def _rule_inherit_mid(glass: Optional[MatLaminatedGlass], i: int,
                      inherit_mid: int) -> int:
    """The material a rule layer takes when ``PID_i`` resolves nothing.

    Ordinary part: the element's own part material. On *MAT_LAMINATED_GLASS the
    ``F_i`` flag picks instead — ``F_i != 0`` -> the POLYMER (which inherits the
    LS-DYNA MID), ``F_i == 0`` -> the synthesized GLASS. ``PID_i`` still WINS
    over ``F_i`` when it resolves, which is dyna2rad's precedence too
    (``convertprops.cxx:2017-2050``: the ``isMat032`` test sits in the ``else``
    of ``if (matHandle.IsValid())``).
    """
    if glass is None:
        return inherit_mid
    fi = glass.f[i] if i < len(glass.f) else 0.0
    return glass.mid if fi else glass.glass_mid


def _resolve_integration_shells(state: ConversionState) -> None:
    """build_starter prepass: bind every ``*SECTION_SHELL`` QR/IRID reference to
    its ``*INTEGRATION_SHELL`` rule, let the rule's NIP win over the section's,
    claim a dedicated /PROP for every part the rule turns into a real laminate,
    and report every route the rule cannot reach.

    Runs AFTER ``_resolve_composites`` (a rule on a *MAT_032 part needs the
    synthesized glass id to exist) and AFTER ``_assign_composite_props`` (it only
    ADDS parts that pass did not already claim), and BEFORE
    ``_resolve_icomp_sections`` (whose "the angles are DROPPED" ladder must not
    fire for a part the rule now routes to a layered /PROP/TYPE11), before
    ``_assign_ortho_props`` / ``_assign_hourglass_props`` (both skip a
    composite-claimed part) and before the parts are repointed and the
    properties emitted.
    """
    if not state.integration_shells and not any(
            s.irid for s in state.sec_shells.values()):
        return
    referenced: Set[int] = set()
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}

    # ── Section-level: bind, validate, and let the rule's NIP win ────────────
    for sec in sorted(state.sec_shells.values(), key=lambda s: s.secid):
        if sec.irid <= 0:
            continue
        rule = state.integration_shells.get(sec.irid)
        if rule is None:
            state.warn(
                f"*SECTION_SHELL {sec.secid}: card-1 field 6 (QR/IRID) is "
                f"-{sec.irid}, which references an *INTEGRATION_SHELL rule "
                f"{sec.irid} that the deck does NOT define. The section falls "
                f"back to its own NIP={sec.nip} with the thickness split "
                "evenly, so any unequal ply thicknesses or per-ply materials "
                "the rule carried are LOST. dyna2rad drops the same dangling "
                "reference in silence.")
            continue
        referenced.add(rule.irid)
        if rule.nip <= 0:
            state.warn(
                f"*INTEGRATION_SHELL {rule.irid} (referenced by *SECTION_SHELL "
                f"{sec.secid}): NIP={rule.nip} defines no integration point at "
                "all, so the rule is DROPPED and the section keeps its own "
                f"NIP={sec.nip} with an even thickness split. NIP has no "
                "default on this card (the CFG uses 0; the manual prints no "
                "Default row) — write it explicitly.")
            continue
        if rule.esop not in (0, 1):
            state.warn(
                f"*INTEGRATION_SHELL {rule.irid} (referenced by *SECTION_SHELL "
                f"{sec.secid}): ESOP={rule.esop} is neither 0 (explicit S/WF/PID "
                "cards) nor 1 (equal spacing), so the rule is DROPPED and the "
                f"section keeps its own NIP={sec.nip}. dyna2rad's bare "
                "switch(ESOP) has no default branch and emits a property "
                "declaring NIP plies with NO ply objects at all — a broken "
                "deck rather than a reported one.")
            continue
        if rule.esop == 0 and (not rule.points
                               or sum(p.wf for p in rule.points) <= 0.0):
            state.warn(
                f"*INTEGRATION_SHELL {rule.irid} (referenced by *SECTION_SHELL "
                f"{sec.secid}): the weighting factors sum to 0, so no layer "
                "thickness can be derived and the rule is DROPPED (the section "
                f"keeps its own NIP={sec.nip}, split evenly). dyna2rad divides "
                "by that sum unguarded and writes inf/nan thicknesses.")
            continue
        if rule.failopt:
            state.warn(
                f"*INTEGRATION_SHELL {rule.irid}: FAILOPT={rule.failopt} is "
                "DROPPED — /PROP/TYPE11 carries ONE global P_Thick_Fail, not a "
                "per-layer failure policy, so LS-DYNA's 'element failure cannot "
                "occur while some layers have no failure option' rule has no "
                "counterpart. Element deletion will follow the Radioss default "
                "instead. dyna2rad never reads the field at all.")
        # The rule's NIP WINS over the section's — dyna2rad reads NIP off the
        # rule and never off the section (convertprops.cxx:1890-1892), and a
        # 4-point rule on a NIP=5 section really does produce 4 layers. Pushing
        # it onto sec.nip makes it win for EVERY consumer at once: the shared
        # /PROP/SHELL integration-point count, /INISHE's layer count, and the
        # *MAT NUMFIP count-to-ratio conversion.
        eff = len(rule.points) if rule.esop == 0 else rule.nip
        eff = min(eff, _MAX_RULE_LAYERS)
        # ...but sec.nip is written as N on the SHARED /PROP/SHELL (and on
        # /PROP/TYPE9), and BOTH readers cap N at 10 — hm_read_prop01.F:260
        # ERROR 788 "NUMBER OF INTEGRATION POINTS SHOULD BE LOWER OR EQUAL TO
        # 10", hm_read_prop09.F:368 ERROR 33. So the rule count is clamped at
        # _MAX_SHELL_LAYERS on the way onto the section, and only there: the
        # LAYERED property the rule drives counts its plies off rule.points and
        # is capped at 100 instead (hm_read_prop11.F:130 NLYMAX), so clamping
        # here never deletes a laminate layer. Writing the raw count through
        # made any rule with more than 10 points ERROR-terminate the starter on
        # a deck that master converted cleanly.
        n_shell = min(eff, _MAX_SHELL_LAYERS)
        if eff > _MAX_SHELL_LAYERS:
            state.warn(
                f"*INTEGRATION_SHELL {rule.irid} (referenced by *SECTION_SHELL "
                f"{sec.secid}): the rule has {eff} integration points, but a "
                f"Radioss /PROP/SHELL carries at most {_MAX_SHELL_LAYERS} "
                "(starter ERROR 788 / ERROR 33), so the SHARED section property "
                f"is written with N={_MAX_SHELL_LAYERS}. The layered property "
                f"the rule drives keeps all {eff} layers — only the "
                "through-thickness quadrature count of the parts that STAY on "
                "the shared property is reduced.")
        if n_shell != sec.nip:
            state.warn(
                f"*SECTION_SHELL {sec.secid}: NIP={sec.nip} is OVERRIDDEN by "
                f"the {eff} integration point(s) of *INTEGRATION_SHELL "
                f"{rule.irid}"
                + (f" (clamped to {n_shell} on the shared /PROP/SHELL)"
                   if n_shell != eff else "")
                + ". Once a user rule is referenced the section's own NIP field "
                "is dead in LS-DYNA — the rule defines both the count and the "
                "locations.")
            sec.nip = n_shell

    # NOTE the element-free `PID_i` material-carrier part — "It may reference a
    # part with no elements" (Vol I R17 p.29-17), the idiomatic way to declare a
    # layer material — needs nothing from this pass. It used to: k2rad emitted a
    # /PART for every *PART record and one with neither elements nor a *SECTION
    # got no property, which is starter ERROR 178 PROPERTY ID DOES NOT EXIST. The
    # element-free-*PART fix gives every such part a placeholder /PROP/SHELL and
    # reports it by name (`_element_free_part_ids` in writer/mesh.py, which cites
    # this very idiom), so warning again here would only repeat it — and repeat
    # the now-false claim that the deck still hits ERROR 178.

    # ── Rules nobody references ─────────────────────────────────────────────
    orphans = sorted(set(state.integration_shells) - referenced)
    if orphans:
        state.note_recognized_not_emitted(
            "*INTEGRATION_SHELL",
            "rule(s) " + ", ".join(str(r) for r in orphans)
            + " are defined but no *SECTION_SHELL references them (card-1 field "
            "6, QR/IRID, must be the NEGATIVE of the rule id) — an integration "
            "rule has no standalone Radioss counterpart, so nothing is emitted "
            "for them")

    # ── Part-level: claim a /PROP, or report why the rule cannot reach one ───
    for pid, part in sorted(state.parts.items()):
        sec = state.sec_shells.get(_part_secid(state, pid))
        rule = _layered_rule(state, sec)
        if rule is None or sec is None:
            continue
        label = (f"*INTEGRATION_SHELL {rule.irid} on part {pid} "
                 f"(*SECTION_SHELL {sec.secid})")
        pc = state.part_composites.get(pid)
        if pc is not None and _layup_is_convertible(pc):
            state.warn(
                f"{label}: the part ALSO carries a *PART_COMPOSITE layup, which "
                "WINS — it replaces the *PART/*SECTION_SHELL pair outright in "
                "LS-DYNA, so the section (and with it the integration rule it "
                "references) is never consulted. The rule's layer thicknesses "
                "and materials are IGNORED; delete one of the two if that is "
                "not what the deck meant.")
            continue
        if pid in solid_pids and pid not in shell_pids:
            state.warn(
                f"{label}: the rule is DROPPED — the part holds SOLID elements "
                "and a shell section's through-thickness layers have no "
                "/PROP/SOLID counterpart. Model a layered thick shell as "
                "*SECTION_TSHELL (no k2rad path yet) or as stacked shells.")
            continue
        if pid not in shell_pids:
            state.warn(
                f"{label}: the rule is DROPPED — the part has no elements at "
                "all, so no property can be synthesized for it.")
            continue
        if part.mid in state.mat_rigid:
            # A rigid part deforms not at all, so a through-thickness layup is
            # meaningless on it in EITHER code — this is not a conversion loss.
            # (It also converts to /MAT/ELAST for the /RBODY's inertia, so it
            # would hit the same LAW1 gate below, but saying so would send the
            # user hunting for an elasto-plastic law a rigid body must not have.)
            state.warn(
                f"{label}: the rule is DROPPED — part {pid}'s material "
                f"{part.mid} is *MAT_RIGID, so the part becomes an /RBODY with "
                "no through-thickness state and no stress integration at all. "
                "An integration rule has nothing to act on there; the layup is "
                "irrelevant rather than lost. Make the part deformable if its "
                "laminate is meant to carry load.")
            continue
        if part.mid in state.mat_elastic:
            # Not a converter limitation — a Radioss one, and an unavoidable
            # one. hm_read_part.F:289-290 rejects LAW1 on EVERY layered or
            # orthotropic shell property (IGTYP 9/10/11/16/17/51/52) with
            # ERROR 658, checked on the /PART's own material, so no property
            # k2rad could emit would carry the layup. LAW1 is the purely
            # elastic law Radioss integrates GLOBALLY (it answers N > 1 with
            # WARNING 1084 "FORMULATION IS SWITCHED TO GLOBAL INTEGRATION
            # N=0"), i.e. it has no through-thickness state to layer.
            state.warn(
                f"{label}: the rule is DROPPED — the part's material "
                f"{part.mid} converts to /MAT/ELAST (LAW1), which Radioss "
                "refuses on every layered or orthotropic shell property "
                "(IGTYP 9/10/11/16/17/51/52, starter ERROR 658 in "
                "hm_read_part.F). LAW1 is integrated globally and carries no "
                "through-thickness state, so there is nothing for the rule's "
                "layers to vary. The part keeps its plain /PROP/SHELL with the "
                f"rule's {len(rule.points)} integration point(s) but a UNIFORM "
                "thickness; give the part an elasto-plastic law (e.g. "
                "*MAT_PLASTIC_KINEMATIC or *MAT_PIECEWISE_LINEAR_PLASTICITY) "
                "if the laminate matters.")
            continue
        if part.mid in state.mat_transverse_aniso:
            state.warn(
                f"{label}: the rule is DROPPED — "
                "*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC converts to "
                "/MAT/LAW43 on a /PROP/TYPE9 (SH_ORTH), a single-layer "
                "orthotropic shell with no per-layer thickness or material "
                "column. Restate the layup as *PART_COMPOSITE if the unequal "
                "plies matter.")
            continue
        if part.mid in state.mat_aniso_visco:
            state.warn(
                f"{label}: the rule is DROPPED — *MAT_ANISOTROPIC_VISCOPLASTIC "
                "converts to /MAT/LAW128 on a /PROP/TYPE9 (SH_ORTH), a "
                "single-layer orthotropic shell with no per-layer thickness or "
                "material column. Restate the layup as *PART_COMPOSITE if the "
                "unequal plies matter.")
            continue
        if pid not in state.composite_prop_ids:
            # An ordinary ISOTROPIC material with a user rule is perfectly legal
            # in LS-DYNA (a foam-core or glass/interlayer stack), and it is the
            # one case _assign_composite_props does not already cover: without a
            # dedicated /PROP the part would keep the section's shared
            # /PROP/SHELL and the whole laminate would vanish. /PROP/TYPE11 is
            # IGTYP 11, which accepts PROP_SHELL 1..5 — an isotropic law
            # included (check_mat_elem_prop_compatibility.F:183-188).
            state.composite_prop_ids[pid] = state.next_prop_id()


def _resolve_icomp_sections(state: ConversionState) -> None:
    """build_starter prepass: report every ``*SECTION_SHELL ICOMP=1`` layup whose
    angles CANNOT reach a Radioss property, and pin the ``*PART_COMPOSITE``
    precedence rule.

    Runs AFTER ``_assign_composite_props``, whose ``composite_prop_ids`` decide
    which parts get the layered /PROP/TYPE11 that can carry them. The angles are
    carried when — and only when — the part is a SHELL part on
    ``*MAT_ORTHOTROPIC_ELASTIC`` (LAW93) or ``*MAT_ENHANCED_COMPOSITE_DAMAGE``
    (LAW127); every other route ends on a single-layer or isotropic property with
    no per-layer angle column at all. Silence there would be the exact fidelity
    loss this pass exists to report, so each case says which property it landed
    on and what to do instead.

    Only a layup with a NONZERO angle is reported: an all-zero ICOMP block is
    informationally identical to the plain section it degrades to.
    """
    if not any(s.icomp == 1 for s in state.sec_shells.values()):
        return
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    for pid, part in sorted(state.parts.items()):
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_shells.get(secid)
        if sec is None or sec.icomp != 1 or not any(sec.betas):
            continue
        shown = ", ".join(f"{b:g}" for b in sec.betas)
        pc = state.part_composites.get(pid)
        if pc is not None and _layup_is_convertible(pc):
            state.warn(
                f"Part {pid} has BOTH a *PART_COMPOSITE layup and a "
                f"*SECTION_SHELL {secid} with ICOMP=1 (angles [{shown}] deg). "
                "*PART_COMPOSITE WINS — it replaces the *PART/*SECTION_SHELL "
                "pair outright in LS-DYNA (its own card carries ELFORM/SHRF and "
                "no SECID), so the per-ply MID/THICK/B_i of the layup are what "
                "the /PROP/TYPE51 emits and the section's ICOMP angles are "
                "IGNORED. Delete one of the two if that is not what the deck "
                "meant.")
            continue
        if pid in solid_pids and pid not in shell_pids:
            state.warn(
                f"*SECTION_SHELL {secid} on part {pid}: ICOMP=1 angles "
                f"[{shown}] deg are DROPPED — the part holds SOLID elements, "
                "and a shell section's layer angles have no /PROP/SOLID "
                "counterpart. Model a thick-shell composite as *SECTION_TSHELL "
                "(no k2rad path yet) or as stacked shells.")
            continue
        if part.mid in state.mat_orthotropic or part.mid in state.mat_enhanced_composite:
            continue                      # carried by _emit_single_material_type11
        if part.mid in state.mat_laminated_glass:
            state.warn(
                f"*SECTION_SHELL {secid} on part {pid}: ICOMP=1 angles "
                f"[{shown}] deg are DROPPED — *MAT_LAMINATED_GLASS becomes a "
                "pair of /MAT/PLAS_BRIT (LAW27) phases, which are ISOTROPIC and "
                "have no material direction for an angle to rotate. (LS-DYNA "
                "lists no such combination either: ICOMP applies to the "
                "orthotropic/anisotropic laws, and 032 is not among them.)")
            continue
        if part.mid in state.mat_transverse_aniso:
            state.warn(
                f"*SECTION_SHELL {secid} on part {pid}: ICOMP=1 angles "
                f"[{shown}] deg are DROPPED — "
                "*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC converts to "
                "/MAT/LAW43 on a /PROP/TYPE9 (SH_ORTH), a SINGLE-direction "
                "orthotropic shell with no per-layer angle column. Restate the "
                "layup as *PART_COMPOSITE if the per-layer angles matter.")
            continue
        if part.mid in state.mat_aniso_visco:
            state.warn(
                f"*SECTION_SHELL {secid} on part {pid}: ICOMP=1 angles "
                f"[{shown}] deg are DROPPED — *MAT_ANISOTROPIC_VISCOPLASTIC "
                "converts to /MAT/LAW128 on a /PROP/TYPE9 (SH_ORTH), a "
                "SINGLE-direction orthotropic shell with no per-layer angle "
                "column. Restate the layup as *PART_COMPOSITE if the per-layer "
                "angles matter.")
            continue
        if (_layered_rule(state, sec) is not None
                and pid in state.composite_prop_ids):
            # ICOMP=1 and a QR/IRID rule COMPOSE: LS-DYNA gives each
            # integration point one B_i angle and the rule gives the same point
            # its thickness and material, so the layered /PROP/TYPE11 the rule
            # synthesizes carries both. Reported by the rule's own warning.
            continue
        state.warn(
            f"*SECTION_SHELL {secid} on part {pid}: ICOMP=1 angles [{shown}] "
            f"deg are DROPPED — the part's material {part.mid} is not converted "
            "to an orthotropic or composite Radioss law, so the property stays "
            "an isotropic /PROP/SHELL on which a material angle has no meaning. "
            "LS-DYNA applies ICOMP only to its orthotropic/anisotropic laws "
            "(Manual Vol I R17 p.41-67); check that the *PART points at the "
            "material the layup was meant for.")


def _resolve_part_composite_fallbacks(state: ConversionState) -> None:
    """Warn-and-fallback for every *PART_COMPOSITE whose layup cannot become a
    /PROP/TYPE51 — an unsupported OPTION1 variant, or a layup with no usable ply.

    The part's MESH must never be lost, so it keeps a plain shell property. That
    property would otherwise come from ``_auto_section_shell``, whose thickness
    is ZERO (the starter rejects a zero-thickness shell), because a
    *PART_COMPOSITE has no *SECTION to inherit one from. Synthesize the section
    here instead, carrying the SUMMED layup thickness, so the fallback is a
    physically usable shell rather than a broken one.
    """
    for pid, pc in sorted(state.part_composites.items()):
        if _layup_is_convertible(pc):
            continue
        total = _layup_thickness(pc)
        secid = pid
        part = state.parts.get(pid)
        if part is not None and part.secid > 0:
            secid = part.secid            # the deck also gave it a *SECTION
        if secid not in state.sec_shells and total > 0.0:
            state.sec_shells[secid] = SectionShell(
                secid, f"PART_COMPOSITE_FALLBACK_{secid}",
                pc.elform if pc.elform > 0 else 2,
                max(len(_valid_plies(pc)), 2), total)
        if pc.variant:
            state.warn(
                f"*PART_COMPOSITE_{pc.variant} {pid}: only the thin-shell form "
                "converts to a per-ply /PROP/TYPE51 layup. The part and ALL its "
                "elements are still emitted, on a plain shell property with the "
                f"summed layup thickness ({total:g}) — the ply materials, "
                "angles and stacking sequence are DROPPED. Model it as a "
                "thin-shell *PART_COMPOSITE to keep the layup.")
        elif not _valid_plies(pc):
            state.warn(
                f"*PART_COMPOSITE {pid}: no valid plies (every layer has MID<=0 "
                "or zero thickness), so no layup property is emitted. The part "
                "and its elements are still converted, on a plain shell "
                "property — but with NO thickness, which the starter rejects: "
                "give at least one ply a positive MID and THICK.")


def _layup_thickness(pc: PartComposite) -> float:
    return sum(p.thick for p in pc.plies if p.mid > 0 and p.thick > 0.0)


def _valid_plies(pc: PartComposite):
    """The layers that become Radioss plies.

    A layer with ``THICK = 0`` and ``MID = -1`` is LS-DYNA's *missing ply* — it
    exists only to keep integration-point numbering aligned and must not become
    a Radioss layer. dyna2rad counts these out of ``NIP`` but then still walks
    the LEADING indices, so a hole in the middle silently drops the LAST ply
    instead; filtering by identity avoids that.
    """
    return [p for p in pc.plies if p.mid > 0 and p.thick > 0.0]


def _layup_is_convertible(pc: PartComposite) -> bool:
    return not pc.variant and bool(_valid_plies(pc))


# ─────────────────────────────────────────────────────────────────────────────
# Materials
# ─────────────────────────────────────────────────────────────────────────────

def _make_composite_materials(state: ConversionState) -> List[str]:
    """Every composite / orthotropic /MAT (plus its companion /FAIL card)."""
    lines: List[str] = []
    for mat in sorted(state.mat_orthotropic.values(), key=lambda m: m.mid):
        lines += _emit_mat_law93(mat, state)
    for mat in sorted(state.mat_enhanced_composite.values(), key=lambda m: m.mid):
        lines += _emit_mat_law127(mat, state)
    for mat in sorted(state.mat_transverse_aniso.values(), key=lambda m: m.mid):
        lines += _emit_mat_law43(mat, state)
    for mat in sorted(state.mat_hill_3r.values(), key=lambda m: m.mid):
        lines += _emit_mat_hill_3r(mat, state)
    for mat in sorted(state.mat_laminated_glass.values(), key=lambda m: m.mid):
        lines += _emit_mat_law27_pair(mat, state)
    if lines:
        lines = ["#-  COMPOSITE MATERIALS:", HDR] + lines
    return lines


def _emit_mat_law93(mat: MatOrthotropicElastic,
                    state: ConversionState) -> List[str]:
    """*MAT_ORTHOTROPIC_ELASTIC (002) → /MAT/LAW93 (ORTH_HILL).

    Column layout from ``MAT/matl93_ORTH_HILL.cfg FORMAT(radioss2021)`` — the
    block a ``/BEGIN 2022`` deck reads with.

    **The Poisson conversion is the one real numeric trap in this batch.**
    LS-DYNA states the compliance matrix with ``−ν_ba/E_b`` in the (1,2) slot
    (Manual Vol II R16 p.2-156) and calls ``PRBA`` the MINOR ratio when EA > EB;
    Radioss states it with ``−NU12/E11`` (``hm_read_mat93.F:203`` ``C12 =
    -NU12/E11``, and ``:192`` ``NU21 = NU12*E22/E11``), i.e. ``NU12`` is the
    MAJOR ratio tied to E11. Reciprocity ν₁₂/E₁₁ = ν₂₁/E₂₂ therefore gives::

        NU12 = PRBA · EA/EB        NU13 = PRCA · EA/EC        NU23 = PRCB · EB/EC

    A naive ``NU12 ← PRBA`` is wrong by the factor EA/EB — for a typical UD ply
    (EA/EB ≈ 15) that is an order of magnitude. Note the OPPOSITE holds for
    /MAT/LAW127 (§ ``_emit_mat_law127``), which consumes the LS-DYNA minor
    ratios verbatim; the two must never share a helper.

    Also note the shear swap: ``GBC → G23`` and ``GCA → G13``.

    MAT_002 is purely elastic while LAW93 is orthotropic Hill PLASTICITY, so the
    yield stress is written at 1e30 and every Hill ratio at 1.0 — the surface is
    never reached. (dyna2rad achieves the same by writing nothing and letting the
    cfg defaults apply; writing them explicitly keeps the deck self-describing.)
    """
    ea, eb, ec = mat.ea, mat.eb, mat.ec
    # Starter fallbacks (hm_read_mat93.F:186-187) applied here so the Poisson
    # divisions below see the same moduli the solver will.
    if eb == 0.0:
        eb = ea
    if ec == 0.0:
        ec = eb
    if ea <= 0.0:
        state.warn(
            f"*MAT_ORTHOTROPIC_ELASTIC {mat.mid}: EA={mat.ea:g} (<=0) — "
            "/MAT/LAW93 needs a positive E11; the starter will reject the "
            "material. Check the card.")

    def _nu(minor, e_num, e_den, name, src):
        """Rescale an LS-DYNA minor ratio to the Radioss major one."""
        if e_den == 0.0:
            state.warn(
                f"*MAT_ORTHOTROPIC_ELASTIC {mat.mid}: {name} = {src}*"
                f"{'EA' if e_num == ea else 'EB'}/"
                f"{'EB' if e_den == eb else 'EC'} cannot be evaluated (the "
                "denominator modulus is zero) — written as 0. Supply EB/EC. "
                "(dyna2rad evaluates the same expression with no zero guard and "
                "emits inf/NaN.)")
            return 0.0
        return minor * e_num / e_den

    nu12 = _nu(mat.prba, ea, eb, "NU12", "PRBA")
    nu13 = _nu(mat.prca, ea, ec, "NU13", "PRCA")
    nu23 = _nu(mat.prcb, eb, ec, "NU23", "PRCB")
    # Starter stability checks (hm_read_mat93.F:197-249): NUij*NUji >= 1 aborts.
    for nu_ij, minor, tag in ((nu12, mat.prba, "NU12*NU21"),
                              (nu13, mat.prca, "NU13*NU31"),
                              (nu23, mat.prcb, "NU23*NU32")):
        if abs(nu_ij * minor) >= 1.0:
            state.warn(
                f"*MAT_ORTHOTROPIC_ELASTIC {mat.mid}: {tag} = "
                f"{nu_ij * minor:.4g} >= 1 after the LS-DYNA→Radioss Poisson "
                "rescale — the starter rejects this as a non-positive-definite "
                "compliance matrix (ERROR 3068/3069/3070). Check the "
                "PRBA/PRCA/PRCB vs EA/EB/EC pairing: LS-DYNA wants the MINOR "
                "ratios there.")
    g12 = mat.gab
    g13 = mat.gca          # GCA → G13
    g23 = mat.gbc          # GBC → G23
    if mat.macf not in (0, 1):
        state.warn(
            f"*MAT_ORTHOTROPIC_ELASTIC {mat.mid}: MACF={mat.macf} (material-axis "
            "swap) has no /MAT/LAW93 or /PROP counterpart and is DROPPED — the "
            "orthotropy axes are NOT permuted. Re-order EA/EB/EC and the "
            "AOPT vectors by hand if the swap matters. (dyna2rad never reads "
            "MACF either.)")
    return [
        f"/MAT/LAW93/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              Rho_i",
        f"{_f(mat.rho)}",
        "#                E11                 E22                 E33                 G12                NU12",
        f"{_f(ea)}{_f(eb)}{_f(ec)}{_f(g12)}{_f(nu12)}",
        "#                G13                 G23                NU13                NU23",
        f"{_f(g13)}{_f(g23)}{_f(nu13)}{_f(nu23)}",
        "#       NL        VP                Fcut",
        f"{_i(0)}{_i(0)}{_f(0.0)}",
        "#            sigma_y                 QR1                 CR1                 QR2                 CR2",
        f"{_f(_LAW93_ELASTIC_SIGY)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#                R11                 R22                 R12",
        f"{_f(1.0)}{_f(1.0)}{_f(1.0)}",
        "#                R33                 R13                 R23",
        f"{_f(1.0)}{_f(1.0)}{_f(1.0)}",
        HDR,
    ]


def _emit_mat_law127(mat: MatEnhancedCompositeDamage,
                     state: ConversionState) -> List[str]:
    """*MAT_ENHANCED_COMPOSITE_DAMAGE (054/055) → /MAT/LAW127.

    Column layout from ``MAT/matl127_enhanced_composite.cfg``. LAW127 is a
    MAT_054 clone, so the strengths, SLIM* limits, DFAIL* strains and rate
    curves are 1:1.

    **Poisson: RAW, no rescale.** ``hm_read_mat127.F90:127-129`` reads
    ``LSDYNA_PRBA → nu21``, ``LSDYNA_PRCB → nu32``, ``LSDYNA_PRCA → nu31`` and
    then derives ``nu12 = nu21*e1/e2`` itself (``:186-198``) — so the law already
    performs the reciprocity step that /MAT/LAW93 expects the CONVERTER to do.
    Applying the LAW93 ``E·ν/E`` factor here would double-apply it.

    LAW127 is a **2026-format law**: a ``/BEGIN 2022`` deck draws one cosmetic
    ``WARNING 100211`` ("Unsupported option /MAT/LAW127 in format < 2025") but
    the starter reads every field correctly — verified against
    ``starter_win64.exe`` (0 errors; the echo reproduces E1/E2/E3, G12/G13/G23,
    nu21/nu31/nu32, XT/XC/YT/YC/SC and the SLIM* factors exactly). This is the
    same trade-off /MAT/LAW128 already ships under.
    """
    b10 = " " * 10
    # LAW127 derives the major ratios itself (nu12 = nu21*E1/E2) and then
    # enforces nu12*nu21 < 1 (ERROR 3068) and a positive compliance determinant
    # (ERROR 307). By far the most common authoring mistake is putting a MAJOR
    # Poisson ratio in PRBA/PRCA/PRCB, which those slots do not hold — catch it
    # here, where the message can say which field is wrong.
    for minor, e_num, e_den, field, ratio in (
            (mat.prba, mat.ea, mat.eb, "PRBA", "NU12*NU21"),
            (mat.prca, mat.ea, mat.ec, "PRCA", "NU13*NU31"),
            (mat.prcb, mat.eb, mat.ec, "PRCB", "NU23*NU32")):
        if e_den > 0.0 and abs(minor * minor * e_num / e_den) >= 1.0:
            state.warn(
                f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: {field}={minor:g} "
                f"gives {ratio} = {minor * minor * e_num / e_den:.4g} >= 1, "
                "which the starter rejects as numerically unstable (ERROR 3068 "
                "/ ERROR 307, determinant of the material matrix < 0). "
                f"/MAT/LAW127 takes {field} VERBATIM as the MINOR ratio and "
                f"derives the major one itself, so for a stiff-fibre ply "
                f"(E1/E2 = {e_num / e_den:.3g} here) {field} must be the SMALL "
                "value (typically 0.01-0.05), not the ~0.3 major ratio. Check "
                "which convention the source deck used.")
    # CRIT (card 6 field 6) picks the failure criterion independently of the
    # keyword spelling; the keyword is only the default.
    crit = int(round(mat.crit)) if mat.crit else (55 if mat.keyword_is_55 else 54)
    if crit == 55:
        state.warn(
            f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: CRIT=55 selects the "
            "TSAI-WU matrix criterion, but /MAT/LAW127 implements CHANG-CHANG "
            "ONLY — there is no switch (the cfg declares LSD_CRIT but no CARD() "
            "ever writes it). The material is emitted with Chang-Chang, which "
            "predicts matrix failure from YT/YC and SC independently instead of "
            "through the coupled Tsai-Wu interaction: expect different matrix-"
            "failure onset. /MAT/LAW25 (COMPSH) Iform=0 is the Tsai-Wu law if "
            "that criterion is essential. (dyna2rad drops CRIT silently — its "
            "MAT_054 and MAT_055 output is byte-identical.)")
    dropped = []
    if mat.soft not in (0.0, 1.0):
        dropped.append(f"SOFT={mat.soft:g}")
    if mat.soft2 not in (0.0, 1.0):
        dropped.append(f"SOFT2={mat.soft2:g}")
    if mat.softg not in (0.0, 1.0):
        dropped.append(f"SOFTG={mat.softg:g}")
    if mat.kf:
        dropped.append(f"KF={mat.kf:g}")
    if mat.dt:
        dropped.append(f"DT={mat.dt:g}")
    if dropped:
        state.warn(
            f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: {', '.join(dropped)} "
            "have NO /MAT/LAW127 column and are DROPPED. SOFT/SOFT2/SOFTG are "
            "the crashfront softening factors (they reduce strength in elements "
            "adjacent to a failed one, so a delamination/crush front will "
            "propagate less readily than in LS-DYNA); KF is the failed-material "
            "bulk modulus; DT is the strain-rate averaging window. dyna2rad "
            "drops all of them silently.")
    # PFL (% of layers that must fail to delete the element) has no PFL slot;
    # dyna2rad routes it to LAW127's own element-deletion RATIO.
    ratio = abs(mat.pfl)
    if mat.pfl:
        state.warn(
            f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: PFL={mat.pfl:g} "
            f"(percent of failed layers before element deletion) → /MAT/LAW127 "
            f"RATIO={ratio:g}, following dyna2rad. Note RATIO is a Radioss-side "
            "deletion ratio, not a percentage — check the deletion threshold if "
            "PFL was given in percent.")
    lines = [
        f"/MAT/LAW127/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#        Init. dens.",
        f"{_f(mat.rho)}",
        "#                 E1                  E2                  E3",
        f"{_f(mat.ea)}{_f(mat.eb)}{_f(mat.ec)}",
        "#                G12                 G13                 G23",
        f"{_f(mat.gab)}{_f(mat.gca)}{_f(mat.gbc)}",
        "#               Nu21                Nu31                Nu32",
        f"{_f(mat.prba)}{_f(mat.prca)}{_f(mat.prcb)}",
        "#                 XT              SLIMT1                LCXT             SCALCXT",
        f"{_f(mat.xt)}{_f(mat.slimt1)}{b10}{_i(mat.lcxt)}{_f(1.0)}",
        "#                 YT              SLIMT2                LCYT             SCALCYT",
        f"{_f(mat.yt)}{_f(mat.slimt2)}{b10}{_i(mat.lcyt)}{_f(1.0)}",
        "#                 SC              SLIMSC                LCSC             SCALCSC",
        f"{_f(mat.sc)}{_f(mat.slims)}{b10}{_i(mat.lcsc)}{_f(1.0)}",
        "#                 XC              SLIMC1                LCXC             SCALCXC",
        f"{_f(abs(mat.xc))}{_f(mat.slimc1)}{b10}{_i(mat.lcxc)}{_f(1.0)}",
        "#                 YC              SLIMC2                LCYC             SCALCYC",
        f"{_f(mat.yc)}{_f(mat.slimc2)}{b10}{_i(mat.lcyc)}{_f(1.0)}",
        "#               FCUT",
        f"{_f(0.0)}",
        "#               ALPH                BETA      2WAY        TI",
        f"{_f(mat.alph)}{_f(mat.beta)}{_i(int(round(mat.two_way)))}"
        f"{_i(int(round(mat.ti)))}",
        "#             DFAILT              DFAILC              DFAILS              DFAILM               RATIO",
        f"{_f(mat.dfailt)}{_f(mat.dfailc)}{_f(mat.dfails)}{_f(mat.dfailm)}{_f(ratio)}",
        "#             NCYRED               TFAIL                FBRT               YCFAC",
        f"{b10}{_i(int(round(mat.ncyred)))}{_f(mat.tfail)}{_f(mat.fbrt)}"
        f"{_f(mat.ycfac)}",
        "#                EFS                EPSF                EPSR                TSMD",
        f"{_f(mat.efs)}{_f(mat.epsf)}{_f(mat.epsr)}{_f(mat.tsmd)}",
        HDR,
    ]
    if mat.xc < 0.0:
        state.warn(
            f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: XC={mat.xc:g} is "
            "negative, which in LS-DYNA is the FLAG 'switch the Poisson effect "
            "off after failure (PRBA=0)' with |XC| as the strength. "
            f"/MAT/LAW127 takes the magnitude ({abs(mat.xc):g}) and has no such "
            "flag — the post-failure Poisson coupling stays active.")
    for lc, name in ((mat.lcxt, "LCXT"), (mat.lcyt, "LCYT"), (mat.lcsc, "LCSC"),
                     (mat.lcxc, "LCXC"), (mat.lcyc, "LCYC")):
        if lc > 0 and lc not in state.curves and lc not in state.define_tables:
            state.warn(
                f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: {name}={lc} "
                "references a *DEFINE_CURVE that is NOT in the deck — the "
                "/MAT/LAW127 function id will dangle at the starter. Add the "
                "curve or clear the field.")
    # TFAIL is LS-DYNA's element-deletion time-step criterion, and WHICH form it
    # selects turns on 0.1, not on 1.0 (Manual Vol II R17 p.2-441 verbatim):
    #
    #   LE 0.0            no deletion by time step
    #   GT 0.0 and LE 0.1 ABSOLUTE — delete when the element's dt < TFAIL
    #   GT 0.1            RATIO    — delete when dt / dt_original < TFAIL
    #
    # /FAIL/GENE1's dtmin is ABSOLUTE (engine fail_gene1_c.F:398
    # `IF (GBUF_DT(I)*DTFAC1(1) <= DTMIN)`), so ONLY the first form converts.
    # dyna2rad gates its companion card on 0 < TFAIL < 1 (convertmats.cxx:
    # 3205-3219), which re-reads every ratio in (0.1, 1) as an absolute dt: in a
    # Mg/mm/s deck (dt ~ 1e-7) a TFAIL of 0.5 would then delete every element of
    # the part on cycle 1. That is a defect, so the band here is the manual's.
    if 0.0 < mat.tfail <= _TFAIL_ABSOLUTE_MAX:
        lines += _emit_fail_gene1_dtmin(mat.mid, mat.tfail, state)
    elif mat.tfail > _TFAIL_ABSOLUTE_MAX:
        state.warn(
            f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mat.mid}: TFAIL={mat.tfail:g} is "
            f"> {_TFAIL_ABSOLUTE_MAX:g}, which selects LS-DYNA's RATIO form of "
            "the time-step deletion criterion (delete the element when its time "
            "step falls below TFAIL x its ORIGINAL time step). Radioss has no "
            "counterpart — /FAIL/GENE1's dtmin is an ABSOLUTE time step and "
            "there is no dt/dt0 criterion — so the whole criterion is DROPPED: "
            "no element of this material will be deleted on time step, and the "
            "SOFT/SOFT2/SOFTG crashfront softening (which LS-DYNA activates "
            "only when TFAIL > 0) is inactive with it. The /MAT/LAW127 card "
            "keeps a TFAIL column for layout fidelity, but the starter never "
            "reads it (hm_read_mat127.F90 fetches no TFAIL field), so the value "
            "does NOT survive there either. Restate the criterion as an "
            f"absolute minimum time step (0 < TFAIL <= {_TFAIL_ABSOLUTE_MAX:g}, "
            "in the deck's time unit) if the deletion matters. (dyna2rad "
            "converts this range as if it were an absolute dt, which deletes "
            "the part immediately on any deck whose dt is below the ratio.)")
    return lines


def _emit_fail_gene1_dtmin(mid: int, dtmin: float,
                           state: ConversionState) -> List[str]:
    """A minimal /FAIL/GENE1 carrying only the ``dtmin`` element-deletion time
    step (card 1 cols 81-100). Bound to the material of the SAME id — Radioss
    pairs a /FAIL with its /MAT by unit id, there is no reference field.
    Layout from ``FAIL/fail_gene1.cfg FORMAT(radioss2022)``."""
    b10 = " " * 10
    state.warn(
        f"*MAT_ENHANCED_COMPOSITE_DAMAGE {mid}: TFAIL={dtmin:g} (0 < TFAIL <= "
        f"{_TFAIL_ABSOLUTE_MAX:g}) is LS-DYNA's ABSOLUTE minimum-time-step "
        f"deletion criterion → a companion /FAIL/GENE1/{mid} with "
        f"dtmin={dtmin:g}. That /FAIL card is what applies the criterion: the "
        "/MAT/LAW127 TFAIL column is written for card-layout fidelity but the "
        "starter never reads it (hm_read_mat127.F90 fetches no TFAIL field).")
    return [
        f"/FAIL/GENE1/{mid}",
        "#               Pmin                Pmax           SigP1_max            Time_max               dtmin",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(dtmin)}",
        "# fct_IDsm                    Eps_dot_sm             Sig_max                Sigr                   K",
        f"{_i(0)}{b10}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "# fct_IDps                    Eps_dot_ps             Eps_max             Eps_eff             Eps_vol",
        f"{_i(0)}{b10}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#            Eps_min               Eps_s fct_IDg12 fct_IDg13 fct_IDe1c",
        f"{_f(0.0)}{_f(0.0)}{_i(0)}{_i(0)}{_i(0)}",
        "#tab_IDfld      Itab         Eps_dot_fld     Nstep   Ismooth   Istrain                        Thinning",
        f"{_i(0)}{_i(0)}{_f(0.0)}{_i(0)}{_i(0)}{_i(0)}{b10}{_f(0.0)}",
        "#            Volfrac          Pthickfail       NCS                        Temp_max",
        f"{_f(0.0)}{_f(0.0)}{_i(0)}{b10}{_f(0.0)}",
        "# fct_IDel           Fscale_el              El_ref",
        f"{_i(0)}{b10}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _law43_lines(mid: int, title: str, rho: float, e: float, nu: float,
                 funct_ide: int, einf: float, ce: float,
                 r00: float, r45: float, r90: float,
                 curves: List, c_hard: float = 0.0,
                 iyield0: int = 0) -> List[str]:
    """The /MAT/LAW43 (HILL_TAB) card body, shared by every keyword that lands
    on it (*MAT_037, *MAT_122).

    Column layout from ``MAT/matl43_HILL_TAB.cfg FORMAT(radioss2021)``:
      RHO_I(20) / E(20) NU(20) /
      FUNCT_IDE(10) blank(10) EINF(20) CE(20) /
      r00(20) r45(20) r90(20) C_hard(20) Iyield0(10) /
      EPSP_max(20) EPS_t(20) EPS_m(20) Fcut(20) Fsmooth(10) /
      FREE_CARD_LIST: func_IDi(10) blank(10) Fscale_i(20) EPS_dot_i(20)

    *curves* is the card-6 rate family as (func_ID, Fscale, EPS_dot) triples —
    one entry for a rate-independent material. The reader hard-fails with
    ERROR 366 if the list is empty, so the caller must supply at least one."""
    b10 = " " * 10
    lines = [
        f"/MAT/LAW43/{mid}",
        title or f"MAT_{mid}",
        "#              RHO_I",
        f"{_f(rho)}",
        "#                  E                  NU",
        f"{_f(e)}{_f(nu)}",
        "#FUNCT_IDE                          EINF                  CE",
        f"{_i(funct_ide)}{b10}{_f(einf)}{_f(ce)}",
        "#                r00                 r45                 r90              C_hard   Iyield0",
        f"{_f(r00)}{_f(r45)}{_f(r90)}{_f(c_hard)}{_i(iyield0)}",
        "#           EPSP_max               EPS_t               EPS_m                Fcut   Fsmooth",
        f"{_f(1.0e30)}{_f(1.0e30)}{_f(2.0e30)}{_f(0.0)}{_i(0)}",
        "# func_IDi                      Fscale_i           EPS_dot_i",
    ]
    for fid, fscale, eps_dot in sorted(curves, key=lambda t: t[2]):
        lines.append(f"{_i(fid)}{b10}{_f(fscale)}{_f(eps_dot)}")
    lines.append(HDR)
    return lines


def _emit_mat_law32_hill(mat: MatHill3R, state: ConversionState) -> List[str]:
    """*MAT_HILL_3R (122) with HR=2 → /MAT/LAW32 (HILL), the analytic twin.

    LS-DYNA's exponential hardening rule is ``sigma_Y = k*(E0 + eps_p)^n`` with
    ``k = P1``, ``n = P2`` and ``E0`` from card 2 — which is exactly the Swift
    law /MAT/LAW32 states as ``sigma = A*(EPSILON_0 + eps_p)^n``. Routing HR=2
    here keeps it EXACT instead of sampling it onto a LAW43 table (dyna2rad
    emits nothing at all for HR=2: its ``if HR==1 / else if HR==3`` has no
    third branch, so the material silently gets NUM_CURVES=0 and hard-fails
    the starter with ERROR 366).

    Column layout from ``MAT/matl32_hill.cfg FORMAT(radioss140)``:
      RHO_I(20) / E(20) NU(20) /
      A(20) EPSILON_0(20) n(20) EPS_max(20) SIGMA_max(20) /
      EPS_DOT_0(20) m(20) /
      r00(20) r45(20) r90(20) blank(20) Iyield0(10)
    Blank(0) fields keep the reader's defaults: A→INFINITY, n→1.0,
    EPS_max/SIGMA_max→INFINITY, each r→1.0 (von Mises).
    """
    r00, r45, r90 = _hill_3r_values(mat, state, "/MAT/LAW32")
    if mat.p1 <= 0.0 or mat.p2 <= 0.0:
        state.warn(
            f"*MAT_HILL_3R {mat.mid}: HR=2 (exponential hardening) needs "
            f"P1 = k > 0 and P2 = n > 0, but P1={mat.p1:g}, P2={mat.p2:g}. "
            "/MAT/LAW32 reads A=0 as INFINITY and n=0 as 1.0, so the yield "
            "surface will not be the deck's — state both.")
    state.warn(
        f"*MAT_HILL_3R {mat.mid}: HR=2 (exponential) → /MAT/LAW32 (HILL) "
        f"rather than /MAT/LAW43, because LAW32's analytic Swift law "
        f"sigma = A*(eps_0 + eps_p)^n reproduces k*(E0 + eps_p)^n EXACTLY "
        f"(A={mat.p1:g}, eps_0={mat.e0:g}, n={mat.p2:g}) — a tabulated LAW43 "
        "would only sample it.")
    return [
        f"/MAT/LAW32/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  NU",
        f"{_f(mat.E)}{_f(mat.nu)}",
        "#                  A           EPSILON_0                   n             EPS_max           SIGMA_max",
        f"{_f(mat.p1)}{_f(mat.e0)}{_f(mat.p2)}{_f(0.0)}{_f(0.0)}",
        "#          EPS_DOT_0                   m",
        f"{_f(0.0)}{_f(0.0)}",
        "#                r00                 r45                 r90                           Iyield0",
        f"{_f(r00)}{_f(r45)}{_f(r90)}{_f(0.0)}{_i(0)}",
        HDR,
    ]


def _hill_3r_values(mat: MatHill3R, state: ConversionState, law: str):
    """The three Lankford values, with the reader's silent 0 → 1.0 fallback
    reported. MAT_122's R00/R45/R90 are independent, unlike MAT_037's single
    r-bar which the LAW43 path copies into all three slots."""
    vals = []
    blank = []
    for name, v in (("R00", mat.r00), ("R45", mat.r45), ("R90", mat.r90)):
        if v <= 0.0:
            blank.append(name)
            vals.append(1.0)
        else:
            vals.append(v)
    if blank:
        state.warn(
            f"*MAT_HILL_3R {mat.mid}: {', '.join(blank)} is 0 or negative, and "
            f"the {law} reader silently replaces a zero r-value with 1.0 — "
            "that direction becomes plain VON MISES with no planar anisotropy. "
            "State all three Lankford parameters if the sheet anisotropy is "
            "the point.")
    return vals[0], vals[1], vals[2]


def _emit_mat_hill_3r(mat: MatHill3R, state: ConversionState) -> List[str]:
    """*MAT_HILL_3R (122) → /MAT/LAW43 (HILL_TAB), or /MAT/LAW32 for HR=2.

    The hardening curve (HR=1 synthesized bilinear, HR=3 the deck's LCID) is
    resolved by ``_resolve_composites``; ``C_hard = 0`` because MAT_122 has no
    isotropic/kinematic split and ``Iyield0 = 0`` because its yield stress is
    the r-value average form, not a direction-1 value.
    """
    if mat.use_law32:
        return _emit_mat_law32_hill(mat, state)
    r00, r45, r90 = _hill_3r_values(mat, state, "/MAT/LAW43")
    if mat.nu >= 0.5 or mat.nu < 0.0:
        state.warn(
            f"*MAT_HILL_3R {mat.mid}: PR={mat.nu:g} is outside the "
            "/MAT/LAW43 range 0 <= NU < 0.5 and the starter will reject it.")
    if mat.e0 and int(round(mat.hr)) != 2:
        state.warn(
            f"*MAT_HILL_3R {mat.mid}: E0={mat.e0:g} is the strain offset of "
            f"the EXPONENTIAL hardening rule, but HR={mat.hr:g} — LS-DYNA "
            "ignores it there too, so it is DROPPED.")
    return _law43_lines(mat.mid, mat.title, mat.rho, mat.E, mat.nu,
                        0, 0.0, 0.0, r00, r45, r90,
                        [(mat.hard_func_id, 1.0, 0.0)])


def _emit_mat_law43(mat: MatTransverselyAnisotropic,
                    state: ConversionState) -> List[str]:
    """*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC (037) → /MAT/LAW43.

    Column layout from ``MAT/matl43_HILL_TAB.cfg FORMAT(radioss2021)``.

    MAT_037 is transversely isotropic in the sheet plane: ONE Lankford r-bar
    covers all three directions, so ``r00 = r45 = r90 = |R|``. (dyna2rad computes
    ``r45 = (2|R|+1)/2 − 0.5``, which collapses algebraically to |R| — the same
    value by a longer route.) ``R < 0`` selects a stabilized integration scheme
    in LS-DYNA, not a negative ratio, hence the magnitude. LS-DYNA MAT_037 has
    no isotropic/kinematic split, so ``C_hard = 0``; the r-bar is the average
    form, so ``Iyield0 = 0``.

    The hardening curve is resolved by ``_resolve_composites`` (HLCID, or a
    synthesized bilinear /FUNCT when HLCID = 0) — LAW43 is tabular-only.
    ``IDSCALE`` → ``FUNCT_IDE``; the ``_ECHANGE`` Young's-modulus evolution
    ``EA``/``COE`` → ``EINF``/``CE``.
    """
    r = abs(mat.r)
    if r == 0.0:
        # hm_read_mat43.F:166-168 replaces a zero r-value with 1.0 (von Mises).
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: R=0, so "
            "/MAT/LAW43 falls back to r00=r45=r90=1.0 — that is plain VON MISES "
            "plasticity with no transverse anisotropy at all. Set R if the "
            "sheet anisotropy matters.")
        r = 1.0
    if mat.r < 0.0:
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: R="
            f"{mat.r:g} is negative, which in LS-DYNA requests a STABILIZED "
            f"integration scheme with |R|={r:g} as the ratio, not a negative "
            "anisotropy. /MAT/LAW43 uses the magnitude; the alternative "
            "integration scheme has no counterpart.")
    if mat.idscale:
        if mat.idscale not in state.curves and mat.idscale not in state.define_tables:
            state.warn(
                f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: "
                f"IDSCALE={mat.idscale} references a *DEFINE_CURVE that is NOT "
                "in the deck — the /MAT/LAW43 FUNCT_IDE will dangle.")
    if mat.nu >= 0.5 or mat.nu < 0.0:
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: PR="
            f"{mat.nu:g} is outside the /MAT/LAW43 range 0 <= NU < 0.5 and the "
            "starter will reject it.")
    lines = _law43_lines(mat.mid, mat.title, mat.rho, mat.E, mat.nu,
                         mat.idscale, mat.ea, mat.coe, r, r, r,
                         [(mat.hard_func_id, 1.0, 0.0)])
    if mat.ea or mat.coe:
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: the "
            f"_ECHANGE Young's-modulus evolution (EA={mat.ea:g}, COE="
            f"{mat.coe:g}) → /MAT/LAW43 EINF/CE — the same Yoshida form "
            "E = E0 - (E0-EINF)*(1-exp(-CE*eps_p)).")
    if mat.icfld:
        lines += _emit_fail_fld_icfld(mat, state)
    return lines


def _emit_fail_fld_icfld(mat: MatTransverselyAnisotropic,
                         state: ConversionState) -> List[str]:
    """MAT_037 ``_NLP_FAILURE`` / ``_NLP2`` ``ICFLD`` → /FAIL/FLD.

    Layout from ``FAIL/fail_fld.cfg FORMAT(radioss2019)``. ``Ifail_sh=2`` deletes
    the shell once ALL layers have failed, and ``Istrain`` follows the
    ECHANGE_OPTION enum exactly as dyna2rad maps it (3/5 = engineering strain
    with filtering → 2; 4 = engineering strain → 1).
    """
    if mat.icfld not in state.curves and mat.icfld not in state.define_tables:
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: "
            f"ICFLD={mat.icfld} references a forming-limit *DEFINE_CURVE that "
            "is NOT in the deck. /FAIL/FLD requires a valid fct_ID (starter "
            "ERROR 2001) — add the curve.")
    istrain = 0
    if mat.echange_option in (3, 5):
        istrain = 2
    elif mat.echange_option == 4:
        istrain = 1
    if istrain == 2 and mat.strainlt:
        state.warn(
            f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: "
            f"STRAINLT={mat.strainlt:g} (the NLP filtering coefficient) maps to "
            "the /FAIL/FLD ALPHA field, which does NOT exist in the "
            "FORMAT(radioss2019) block a /BEGIN 2022 deck reads — it is "
            "DROPPED. Istrain=2 still selects engineering strain with "
            "filtering, but at the solver's default cutoff frequency rather "
            "than the deck's.")
    state.warn(
        f"*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC {mat.mid}: ICFLD="
        f"{mat.icfld} (forming-limit diagram) → /FAIL/FLD/{mat.mid} with "
        f"Ifail_sh=2 (delete the shell when every layer has failed), "
        f"Istrain={istrain}.")
    return [
        f"/FAIL/FLD/{mat.mid}",
        "#   FCT_ID  IFAIL_SH    I_MARG FCT_IDADV                RANI                DADV   ISTRAIN     IXFEM",
        f"{_i(mat.icfld)}{_i(2)}{_i(1)}{_i(0)}{_f(0.0)}{_f(0.0)}{_i(istrain)}{_i(0)}",
        HDR,
    ]


def _emit_mat_law27_pair(mat: MatLaminatedGlass,
                         state: ConversionState) -> List[str]:
    """*MAT_LAMINATED_GLASS (032) → two /MAT/PLAS_BRIT (LAW27) materials.

    Column layout from ``MAT/matl27_plas_brit.cfg FORMAT(radioss2019)``.

    The polymer keeps the LS-DYNA MID and the glass takes the synthesized
    ``glass_mid`` (dyna2rad's convention, so any surviving reference to the
    original MID still resolves). Only the GLASS can fail in LS-DYNA, so only it
    gets brittle-damage strains; the polymer stays on the LAW27 cfg defaults
    (EPS_t 1e30 etc., i.e. never damages).

    The damage window is dyna2rad's: ``EPS_t = EFG`` (damage onset),
    ``EPS_m = EFG + 0.05`` (full damage) and ``EPS_f = EFG + 0.1`` (element
    deletion) — LS-DYNA gives only the single failure strain EFG, so the
    softening band is a converter-chosen ramp, not deck data.

    LS-DYNA ETG/ETP are already PLASTIC hardening moduli — Manual Vol II R17
    p.2-314/2-315 names them "Plastic hardening modulus for glass" and "...for
    polymer" — which is exactly what LAW27's ``b`` is with ``n = 1``
    (``dSigma/dEps_plastic``), so both are copied verbatim. Only the fields the
    manual calls a TANGENT modulus (e.g. *MAT_PLASTIC_KINEMATIC's ETAN) need the
    ``H = E·ET/(E−ET)`` rescale k2rad applies on that path.
    """
    b20 = " " * 20

    def _law27(mid, name, rho, e, nu, sigy, b, eps_t, eps_m, eps_f):
        return [
            f"/MAT/LAW27/{mid}",
            name,
            "#              RHO_I",
            f"{_f(rho)}",
            "#                  E                  NU",
            f"{_f(e)}{_f(nu)}",
            "#                  a                   b                   n                                SIG_max0",
            f"{_f(sigy)}{_f(b)}{_f(1.0)}{b20}{_f(1.0e30)}",
            "#                  c           EPS_DOT_0       ICC   Fsmooth      Fcut",
            f"{_f(0.0)}{_f(0.0)}{_i(1)}{_i(0)}{_f(1.0e30)}",
            "#             EPS_t1              EPS_m1              d_max1              EPS_f1",
            f"{_f(eps_t)}{_f(eps_m)}{_f(0.999)}{_f(eps_f)}",
            "#             EPS_t2              EPS_m2              d_max2              EPS_f2",
            f"{_f(eps_t)}{_f(eps_m)}{_f(0.999)}{_f(eps_f)}",
            HDR,
        ]

    base = mat.title or f"MAT_{mat.mid}"
    efg = mat.efg if mat.efg > 0.0 else 1.0e30
    eps_m = efg + 0.05 if mat.efg > 0.0 else 1.1e30
    eps_f = efg + 0.1 if mat.efg > 0.0 else 1.2e30
    if mat.efg <= 0.0:
        state.warn(
            f"*MAT_LAMINATED_GLASS {mat.mid}: EFG={mat.efg:g} (<=0) — the glass "
            "phase gets NO brittle failure (the LAW27 defaults, 1e30). Set EFG "
            "for the glass plies to crack.")
    lines = _law27(mat.glass_mid, f"{base} - Glass"[:100], mat.rho,
                   mat.eg, mat.prg, mat.syg, max(mat.etg, 0.0),
                   efg, eps_m, eps_f)
    lines += _law27(mat.mid, f"{base} - polymer"[:100], mat.rho,
                    mat.ep, mat.prp, mat.syp, max(mat.etp, 0.0),
                    1.0e30, 1.1e30, 1.2e30)
    if mat.efg > 0.0:
        state.warn(
            f"*MAT_LAMINATED_GLASS {mat.mid}: the glass failure strain "
            f"EFG={mat.efg:g} becomes a /MAT/LAW27 brittle-damage RAMP — "
            f"EPS_t={efg:g} (damage onset), EPS_m={eps_m:g} (full damage), "
            f"EPS_f={eps_f:g} (element deletion). LS-DYNA gives only the single "
            "failure strain, so the +0.05/+0.1 softening band is a converter "
            "choice (dyna2rad's); narrow it if the glass should shatter more "
            "abruptly.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Prepass: *ELEMENT_SHELL_BETA on an orthotropic part
# ─────────────────────────────────────────────────────────────────────────────

def _fold_element_beta(state: ConversionState) -> None:
    """Move a per-element BETA onto the property, because the solver reads it
    only there.

    k2rad writes BETA into the /SHELL // SH3N ``Phi`` column, the starter reads
    it back correctly (verified: 90 deg echoes as 1.570796326795 rad under
    ``/IOFLAG`` IPRI=5) — **and then throws it away** on every property class
    except three. ``starter/source/elements/shell/coque/corthini.F`` builds the
    layer angle from the PROPERTY alone::

        IF (IGTYP == 1)                RETURN                        (:110)
        IF (IGTYP == 9)   PHI1(1,I) = GEO(10,PID)                    (:202)
        ELSEIF (IGTYP == 10/11)  PHI1(J,I) = GEO(IPANG+J,PID)        (:206-217)
        ELSEIF (IGTYP == 16)     PHI1(J,I) = GEO(IPANG+J,PID)        (:429-435)

    and only IGTYP 17/51/52 do ``PHI1(J,I) = ANGLE(I) + …``. Measured on a
    *MAT_002 plate with E1/E2 = 100 pulled along global X: per-element BETA=90
    on a /PROP/TYPE11 part gives 103094.25 MPa, byte-identical to its BETA=0
    twin (ratio 1.000000) where Q22 = 25789.81 was required — the 90 deg fibre
    rotation did nothing at all. The same 90 deg on a *PART_COMPOSITE part
    (/PROP/TYPE51) DOES work (ratio 0.250084), and so does the angle when it
    reaches the TYPE11 layer Phi column instead (25773.52, dev -0.063%).

    So: when every shell of such a part carries the SAME angle, fold it into the
    property's own reference angle and zero the element field, which reproduces
    the LS-DYNA physics exactly. When the angles differ element by element there
    is no single property angle to write — one property serves the whole part —
    and the only honest outcome is a loud warning.

    Runs as a build_starter prepass after ``_assign_composite_props`` /
    ``_assign_ortho_props`` (it needs to know which parts get a synthesized
    orthotropic property) and before the elements and properties are emitted.
    """
    betas: Dict[int, Set[float]] = defaultdict(set)
    for e in state.shell_elems:
        betas[e.pid].add(e.beta)
    for pid, vals in sorted(betas.items()):
        if vals == {0.0}:
            continue
        # /PROP/TYPE51 (*PART_COMPOSITE): corthini DOES add ANGLE(I) there, so
        # the per-element column is live and must be left exactly as written.
        pc = state.part_composites.get(pid)
        if pid in state.composite_prop_ids and pc is not None \
                and _layup_is_convertible(pc):
            continue
        prop_id = (state.composite_prop_ids.get(pid)
                   or state.ortho_prop_ids.get(pid))
        angles = ", ".join(f"{v:g}" for v in sorted(vals))
        if prop_id is None:
            state.warn(
                f"*ELEMENT_SHELL_BETA on part {pid}: the part sits on an "
                "ISOTROPIC /PROP/SHELL (IGTYP 1), and corthini.F:110 returns "
                "before any material angle is read there — the angle(s) "
                f"{angles} deg have no effect. BETA only means something for an "
                "orthotropic or composite material; give the part one (then "
                "k2rad folds the angle into its property) or drop the option.")
            continue
        if len(vals) > 1:
            state.warn(
                f"*ELEMENT_SHELL_BETA on part {pid}: the elements carry "
                f"DIFFERENT angles ({angles} deg) and OpenRadioss ignores the "
                "per-element /SHELL Phi column on this property class "
                "(corthini.F:202-217/429-435 take the layer angle from the "
                "property for IGTYP 9/10/11/16; only IGTYP 17/51/52 add it). "
                "One /PROP serves the whole part, so a per-element variation "
                "CANNOT be represented — the fibres run along the property's "
                "own reference direction for every element. Split the part per "
                "angle, or model it as a *PART_COMPOSITE (→ /PROP/TYPE51, where "
                "the element angle IS honoured).")
            continue
        fold = next(iter(vals))
        state.part_beta_fold[pid] = fold
        for e in state.shell_elems:
            if e.pid == pid:
                e.beta = 0.0
        state.warn(
            f"*ELEMENT_SHELL_BETA on part {pid}: all elements share BETA="
            f"{fold:g} deg, which was FOLDED into the synthesized orthotropic "
            f"/PROP {prop_id} (added to its reference angle) instead of being "
            "left in the /SHELL Phi column. OpenRadioss reads that column only "
            "for IGTYP 17/51/52 (corthini.F:202-217/429-435), so the element "
            "field would have been silently ignored; the folded property angle "
            "reproduces the LS-DYNA fibre direction.")


# ─────────────────────────────────────────────────────────────────────────────
# Properties
# ─────────────────────────────────────────────────────────────────────────────

def _emit_composite_props(state: ConversionState,
                          istrain: Optional[int] = None) -> List[str]:
    """Emit the synthesized orthotropic / layup property for every part
    ``_assign_composite_props`` claimed.

    *istrain* defaults to the same *DATABASE_EXTENT_BINARY strflg rule
    ``_make_properties`` applies (strain output needs Istrain=1 in the property
    or the engine writes empty strain channels)."""
    if not state.composite_prop_ids:
        return []
    if istrain is None:
        ext = state.db_extent_binary
        istrain = 1 if (ext and ext.strflg > 0) else 0
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    part_secids = {pid: (p.secid if p.secid > 0 else pid)
                   for pid, p in state.parts.items()}
    lines: List[str] = ["#-  COMPOSITE PROPERTIES:", HDR]
    for pid, prop_id in sorted(state.composite_prop_ids.items()):
        part = state.parts.get(pid)
        if part is None:
            continue
        pc = state.part_composites.get(pid)
        sec = (state.sec_shells.get(part_secids.get(pid, pid))
               or _auto_section_shell(part_secids.get(pid, pid)))
        if pc is not None and _layup_is_convertible(pc):
            lines += _emit_part_composite_prop(state, pc, prop_id, istrain)
            continue
        mid = part.mid
        label = f"/PROP for composite part {pid}"
        # A uniform *ELEMENT_SHELL_BETA folded here by _fold_element_beta: the
        # starter ignores the per-element Phi column on IGTYP 9/10/11/16, so the
        # angle has to ride on the property's own reference angle.
        beta_fold = state.part_beta_fold.get(pid, 0.0)
        if mid in state.mat_laminated_glass:
            lines += _emit_laminated_glass_prop(
                state, state.mat_laminated_glass[mid], pid, prop_id, sec,
                istrain, beta_fold)
        elif mid in state.mat_transverse_aniso:
            # MAT_037 → /MAT/LAW43 is a Hill sheet-plasticity law: dyna2rad puts
            # it on /PROP/TYPE9 (SH_ORTH), the single-material orthotropic shell.
            state.warn(
                f"{label}: *MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC → "
                "/MAT/LAW43 is orthotropic-class, so the part is repointed at a "
                f"synthesized /PROP/TYPE9 (SH_ORTH) {prop_id} instead of the "
                "isotropic section property (starter ERROR 3047 otherwise). "
                "MAT_037 has no AOPT card, so the reference direction is the "
                "default global X — set Vx/Vy/Vz on the /PROP if the rolling "
                "direction matters.")
            lines += _emit_prop_type9(prop_id, f"LAW43_ORTHO_PROP_{prop_id} "
                                      f"(part {pid})", sec, state.is_implicit,
                                      istrain, state, phi=beta_fold)
        elif mid in state.mat_hill_3r:
            lines += _emit_hill_3r_prop(state, state.mat_hill_3r[mid], pid,
                                        prop_id, sec, istrain, beta_fold)
        else:
            mat = (state.mat_orthotropic.get(mid)
                   or state.mat_enhanced_composite.get(mid))
            if mat is None:
                # A part claimed purely because its *SECTION_SHELL binds an
                # *INTEGRATION_SHELL rule: the material is an ordinary
                # (isotropic) one with no orthotropy system, but the rule's
                # unequal layers and per-layer materials still need a LAYERED
                # property to live on.
                rule = _layered_rule(state, sec)
                if rule is not None:
                    lines += _emit_rule_shell_prop(state, prop_id, pid, mid,
                                                   sec, rule, istrain,
                                                   beta_fold)
                continue
            is_solid = pid in solid_pids and pid not in shell_pids
            axis = _composite_ref_axis(mat, state, label, prop_id,
                                       for_solid=is_solid)
            axis.phi += beta_fold
            law = ("/MAT/LAW93" if mid in state.mat_orthotropic
                   else "/MAT/LAW127")
            if axis.mapped:
                state.warn(f"{label}: orthotropy axes from the material "
                           f"{axis.note}.")
            lines += axis.lines
            if is_solid:
                lines += _emit_composite_solid_prop(state, prop_id, pid, axis,
                                                    istrain, law)
            else:
                lines += _emit_single_material_type11(
                    state, prop_id, pid, mid, sec, axis, istrain, law)
    return lines


def _emit_hill_3r_prop(state: ConversionState, mat: MatHill3R, pid: int,
                       prop_id: int, sec: SectionShell, istrain: int,
                       beta_fold: float) -> List[str]:
    """The /PROP/TYPE9 (SH_ORTH) a *MAT_HILL_3R part is repointed at, carrying
    the material-axis definition of its AOPT card set.

    Unlike MAT_037, MAT_122 HAS an AOPT block (cards 3-5), but Radioss keeps
    the orthotropy direction on the PROPERTY, not the material — so it lands
    here. /PROP/TYPE9's reference system is a single Vx/Vy/Vz vector plus the
    Phi rotation (card 4), which covers AOPT=2 exactly; the other modes have
    no TYPE9 column and fall back to the default global X with a warning.
    dyna2rad reads none of this block at all.
    """
    law = "/MAT/LAW32" if mat.use_law32 else "/MAT/LAW43"
    aopt = (int(round(mat.aopt))
            if abs(mat.aopt - round(mat.aopt)) < 1e-9 else None)
    refvec = (1.0, 0.0, 0.0)
    axis_note = ("AOPT=2 is not set, so the reference direction is the default "
                 "global X")
    if aopt == 2 and any((mat.a1, mat.a2, mat.a3)):
        refvec = (mat.a1, mat.a2, mat.a3)
        axis_note = (f"AOPT=2 vector a=({mat.a1:g}, {mat.a2:g}, {mat.a3:g}) "
                     "→ the /PROP/TYPE9 Vx/Vy/Vz reference direction")
    elif aopt in (None, 0) and not any((mat.v1, mat.v2, mat.v3)):
        # AOPT=0 is the card's DEFAULT and what a blank field means, so it
        # gets its own message: the generic "AOPT=2 is not set" clause does
        # not say that a real, stated material-axis rule was dropped, and on a
        # Hill sheet law the rolling direction is the whole point.
        state.warn(
            f"*MAT_HILL_3R {mat.mid} on part {pid}: AOPT=0 takes the material "
            "axes from the ELEMENT's own nodes 1, 2 and 4 (as "
            "*DEFINE_COORDINATE_NODES would), then rotates them about the "
            "shell normal by BETA (Vol II R17 p.2-853). /PROP/TYPE9 carries "
            "one global Vx/Vy/Vz reference vector for the whole property and "
            "has no per-element node rule, so that is DROPPED and the r00 "
            "rolling direction falls back to global X (BETA is then applied "
            "relative to global X, not to the element frame). If the mesh was "
            "built so that element edge 1-2 IS the rolling direction, set "
            f"Vx/Vy/Vz on /PROP/TYPE9/{prop_id} to match, or restate the axes "
            "as AOPT=2.")
    else:
        state.warn(
            f"*MAT_HILL_3R {mat.mid} on part {pid}: AOPT={mat.aopt:g} has no "
            "/PROP/TYPE9 counterpart — only AOPT=2 with a stated vector a "
            "maps onto the property's single Vx/Vy/Vz reference direction. "
            "AOPT=3 (v CROSSED with the element normal) and a negative AOPT "
            "(the |AOPT| *DEFINE_COORDINATE_* system) are DROPPED and the "
            "rolling direction falls back to global X. Set Vx/Vy/Vz on "
            f"/PROP/TYPE9/{prop_id} by hand, or restate the material axes as "
            "AOPT=2 with A1/A2/A3.")
    phi = mat.beta + beta_fold
    state.warn(
        f"/PROP for part {pid}: *MAT_HILL_3R → {law} is orthotropic-class, so "
        f"the part is repointed at a synthesized /PROP/TYPE9 (SH_ORTH) "
        f"{prop_id} instead of the isotropic section property (starter "
        f"ERROR 3047 otherwise). {axis_note}"
        + (f", rotated by BETA={mat.beta:g} deg" if mat.beta else "") + ".")
    return _emit_prop_type9(prop_id, f"HILL_3R_ORTHO_PROP_{prop_id} "
                            f"(part {pid})", sec, state.is_implicit,
                            istrain, state, refvec=refvec, phi=phi)


def _emit_composite_solid_prop(state: ConversionState, prop_id: int, pid: int,
                               axis: "_RefAxis", istrain: int,
                               law: str) -> List[str]:
    """Orthotropic SOLID property /PROP/TYPE6 for a MAT_002 / MAT_054 brick part.

    Reuses the same Ip semantics as the shell path; a skew built from AOPT=2
    binds the axes exactly (Ip=0 + skew_ID), which on a free tet mesh is the only
    element-independent option — see ``_emit_prop_type6``'s note in
    ``writer/mesh.py``.
    """
    from .mesh import _emit_prop_type6      # local: mesh must not import this
    tet10 = any(e.pid == pid and len(e.nodes) == 10 for e in state.solid_elems)
    part = state.parts.get(pid)
    secid = part.secid if part and part.secid > 0 else pid
    sec = state.sec_solids.get(secid)
    ip = axis.ip
    if axis.skew_id:
        ip = 0
    state.warn(
        f"/PROP for composite part {pid}: {law} is orthotropic-class, so the "
        f"solid part is repointed at a synthesized /PROP/TYPE6 (SOL_ORTH) "
        f"{prop_id} rather than the isotropic /PROP/SOLID (starter ERROR 3047).")
    return _emit_prop_type6(prop_id, f"COMPOSITE_SOLID_PROP_{prop_id} "
                            f"(part {pid})", sec, 1000 if tet10 else 0, istrain,
                            refvec=axis.vec, ip=ip, phi=axis.phi,
                            skew_id=axis.skew_id, refpoint=axis.pt)


def _shell_layer_count(sec: SectionShell, state: ConversionState,
                       pid: int) -> int:
    """*SECTION_SHELL NIP → /PROP/TYPE11 layer count (dyna2rad clamps at 10)."""
    nip = sec.nip if sec.nip > 0 else 2
    if nip > _MAX_SHELL_LAYERS:
        state.warn(
            f"/PROP/TYPE11 for part {pid}: *SECTION_SHELL NIP={nip} exceeds the "
            f"{_MAX_SHELL_LAYERS} layers a layered Radioss shell property "
            f"carries — CLAMPED to {_MAX_SHELL_LAYERS}. Through-thickness "
            "resolution is reduced (matches dyna2rad's own clamp)."
            + ("" if sec.icomp != 1 else
               " Only the first "
               f"{_MAX_SHELL_LAYERS} ICOMP=1 layer angle(s) survive with it."))
        nip = _MAX_SHELL_LAYERS
    return nip


def _icomp_layer_angles(sec: SectionShell, nip: int,
                        state: ConversionState) -> List[float]:
    """The per-layer material angle each /PROP/TYPE11 layer carries.

    ``0.0`` for every layer of an ordinary (ICOMP=0) section — the layup is then
    just NIP identical copies of the section — and the deck's own ``B_i`` for an
    ICOMP=1 one. The value is used VERBATIM, no sign flip: both codes measure the
    angle counter-clockwise about the shell normal from the material's reference
    direction (LS-DYNA Vol I R17 p.41-70 "β_i, material angle at the ith
    integration point"; Radioss ``prop_p11_sh_sandw.cfg`` ``Phi_i`` "angle
    between direction 1 and the projection of the reference vector"). It is then
    ADDED to the material's own AOPT/BETA rotation by ``_emit_prop_type11``,
    which is the same composition ``*PART_COMPOSITE``'s per-ply ``B_i`` uses.

    dyna2rad reads ``LSD_B`` verbatim into ``Phi`` on its *SECTION_TSHELL
    composite path (``convertprops.cxx:4528-4540``) and nowhere else — its thin
    shell ``p_ConvertSectionShell`` (``convertprops.cxx:641-765``) dispatches
    purely on the MATERIAL keyword and reads ``LSD_ICOMP`` only as a *MAT_FABRIC
    NIP-normalization switch (``:1704-1713``, ``:3346-3351``), so an ICOMP=1
    thin-shell layup loses every angle there.
    """
    if sec.icomp != 1:
        return [0.0] * nip
    return (list(sec.betas) + [0.0] * nip)[:nip]


def _emit_single_material_type11(state: ConversionState, prop_id: int, pid: int,
                                 mid: int, sec: SectionShell, axis: "_RefAxis",
                                 istrain: int, law: str) -> List[str]:
    """A one-material layered shell: /PROP/TYPE11 with NIP identical layers.

    dyna2rad routes *MAT_002 here (``convertprops.cxx:736``) but drops MAT_054/055
    through to /PROP/TYPE1, which the starter then rejects (ERROR 3047) because
    /MAT/LAW127 registers PROP_SHELL=2 (orthotropic) and IGTYP 1 accepts only
    classes 1 and 5. Both laws are routed to TYPE11 here.

    With ``ICOMP = 1`` the layers are no longer identical: each takes its own
    ``B_i`` material angle off the section's card-3 angle block, which is the
    whole point of the flag — a [0/45/-45/90] layup emitted as four 0-degree
    layers is a UNIDIRECTIONAL laminate with several times the axial and a
    fraction of the shear stiffness of the deck's.
    """
    thick = sec.t1
    if thick <= 0.0:
        state.warn(
            f"/PROP/TYPE11/{prop_id} (part {pid}): shell thickness is "
            f"{thick:g} (<=0), which the starter rejects. Set the "
            "*SECTION_SHELL thickness for this composite part.")
    layers, nip, angles = _shell_layup(state, sec, pid, prop_id, thick, mid)
    state.warn(
        f"/PROP for composite part {pid}: {law} is orthotropic-class, so the "
        f"part is repointed at a synthesized /PROP/TYPE11 (SH_SANDW) {prop_id} "
        f"with {nip} layer(s) of the section thickness — the isotropic "
        "/PROP/SHELL is rejected by the starter (ERROR 3047)."
        + ("" if law != "/MAT/LAW127" else
           " (dyna2rad leaves MAT_054/055 on /PROP/TYPE1, which hard-fails.)"))
    if sec.icomp == 1:
        ruled = _layered_rule(state, sec) is not None
        state.warn(
            f"*SECTION_SHELL {sec.secid} on part {pid}: ICOMP=1 → the "
            f"/PROP/TYPE11/{prop_id} layers carry the deck's own B_i material "
            "angles ["
            + ", ".join(f"{a:g}" for a in angles)
            + "] deg, bottom layer first, each added to the material's "
            f"AOPT/BETA reference direction (Phi={axis.phi:g} deg). "
            + (f"The layer THICKNESSES come from the *INTEGRATION_SHELL "
               f"{sec.irid} rule this section references (card-1 field 6, "
               "QR/IRID), so angles and unequal plies are BOTH carried — the "
               "two keywords compose, one B_i and one S/WF/PID per integration "
               "point."
               if ruled else
               f"The section thickness {thick:g} is still split EVENLY over "
               f"the {nip} layers — *SECTION_SHELL ICOMP=1 carries angles ONLY "
               "(card 3 is B1..B8), so unequal ply thicknesses need an "
               "*INTEGRATION_SHELL rule (referenced from card-1 field 6 as a "
               "NEGATIVE QR/IRID) or *PART_COMPOSITE.")
            + " dyna2rad drops these angles entirely on a thin shell.")
    return _emit_rule_layup(state, prop_id, pid,
                            f"COMPOSITE_PROP_{prop_id} (part {pid})", sec,
                            layers, thick, axis, istrain)


def _shell_layup(state: ConversionState, sec: SectionShell, pid: int,
                 prop_id: int, thick: float, mid: int):
    """The ``(layers, nip, angles)`` of a single-material shell section.

    Without a rule this is the historical behaviour verbatim — NIP identical
    copies of the section thickness, each carrying its ICOMP ``B_i`` angle. With
    an ``*INTEGRATION_SHELL`` bound it is the rule's own per-layer thickness and
    material, with the ICOMP angles riding along on the same integration points.
    """
    rule = _layered_rule(state, sec)
    if rule is None:
        nip = _shell_layer_count(sec, state, pid)
        angles = _icomp_layer_angles(sec, nip, state)
        return [(angles[i], thick / nip, mid) for i in range(nip)], nip, angles
    npts = len(rule.points)
    # The card-3 B_i block was read with the SECTION's own NIP, so a rule with
    # more integration points than the section declared leaves _icomp_layer_
    # angles padding the tail with 0 deg. Silent padding turns a [0/45/90]
    # layup into [0, 45, 90, 0, 0] — report it rather than inventing plies.
    if sec.icomp == 1 and len(sec.betas) < npts:
        state.warn(
            f"*SECTION_SHELL {sec.secid} on part {pid}: ICOMP=1 supplies only "
            f"{len(sec.betas)} material angle(s) {list(sec.betas)} but "
            f"*INTEGRATION_SHELL {rule.irid} defines {npts} integration "
            f"point(s), so the last {npts - len(sec.betas)} layer(s) are "
            "emitted at 0 deg. LS-DYNA reads one B_i per integration point — "
            "extend the card-3 angle block to the rule's point count (the "
            "section's own NIP field is dead once a rule is referenced, so it "
            "is the B_i COUNT that has to grow, not NIP).")
    angles = _icomp_layer_angles(sec, npts, state)
    layers, _ = _rule_layers(state, rule, sec, pid, prop_id, thick, angles, mid)
    return layers, len(layers), [phi for phi, _, _ in layers]


def _emit_rule_shell_prop(state: ConversionState, prop_id: int, pid: int,
                          mid: int, sec: SectionShell, rule: IntegrationShell,
                          istrain: int, beta_fold: float = 0.0) -> List[str]:
    """An ORDINARY (non-composite) material whose *SECTION_SHELL binds an
    *INTEGRATION_SHELL rule → the layered /PROP/TYPE11 the rule needs.

    Perfectly legal in LS-DYNA — a foam-core sandwich or a glass/interlayer
    stack is normally written as isotropic layers plus a rule — and it is the
    one route ``_assign_composite_props`` does not already cover, because the
    part's MATERIAL says nothing about the layup. The layup lands on TYPE51 +
    TYPE19 unless ``_type11_carries`` says the single-law TYPE11 can hold it;
    an ordinary material never can.
    """
    thick = sec.t1
    if thick <= 0.0:
        state.warn(
            f"/PROP for part {pid}: shell thickness is {thick:g} (<=0), which "
            "the starter rejects. Set the *SECTION_SHELL thickness for this "
            "layered part.")
    layers, nip, _ = _shell_layup(state, sec, pid, prop_id, thick, mid)
    state.warn(
        f"*INTEGRATION_SHELL {rule.irid} on part {pid}: the part is repointed "
        f"from the shared isotropic /PROP/SHELL/{sec.secid} at a synthesized "
        f"layered property {prop_id} with {nip} layer(s) — an ordinary material "
        "carries no layup, so the rule's unequal thicknesses and per-point "
        f"materials have nowhere else to live. Every OTHER part on "
        f"*SECTION_SHELL {sec.secid} that the rule does not reach keeps the "
        "shared property.")
    axis = _RefAxis(ip=20, phi=beta_fold,
                    note="element frame (the layer material is isotropic)")
    return _emit_rule_layup(state, prop_id, pid,
                            f"INTEGRATION_RULE_PROP_{prop_id} (part {pid})",
                            sec, layers, thick, axis, istrain)


def _emit_laminated_glass_prop(state: ConversionState, glass: MatLaminatedGlass,
                               pid: int, prop_id: int, sec: SectionShell,
                               istrain: int, beta_fold: float = 0.0) -> List[str]:
    """*MAT_LAMINATED_GLASS → the layered /PROP/TYPE11 that binds the synthesized
    glass and polymer materials to the integration points.

    **F_i polarity.** LS-DYNA: ``F_i = 0.0`` → glass, ``1.0`` → polymer. dyna2rad
    has TWO contradictory implementations of this — ``ConvertSecShellsRelatedMat
    Laminate`` (``convertprops.cxx:1620-1641``) inverts it AND mutates the
    /PART's mat_ID inside the layer loop, so every layer after the first
    polymer one also becomes polymer; the ``*INTEGRATION_SHELL`` path
    (``:2024-2050``) gets it right. The correct (IRID) polarity is used here.

    With no F array at all every layer is glass, matching dyna2rad.

    **Layer thicknesses.** LS-DYNA takes them from the ``*INTEGRATION_SHELL``
    rule the material requires ("the constitutive properties ... are specified
    through the integration rule"), so when the section binds one the layers get
    the rule's real ``WF_i`` thicknesses and the even split — and the warning
    that names it as a fidelity loss — is retired. Without a rule there is
    nothing in the deck to derive them from and the even split stands.
    """
    thick = sec.t1
    fvals = glass.f
    rule = _layered_rule(state, sec)
    if rule is not None:
        # The LAW27 phases are isotropic, so no layer carries an angle; the
        # per-layer glass/polymer pick rides on _rule_inherit_mid's F_i branch,
        # which PID_i overrides when it resolves (dyna2rad's precedence too).
        layers, _ = _rule_layers(state, rule, sec, pid, prop_id, thick,
                                 [0.0] * len(rule.points), glass.mid,
                                 glass=glass)
        nip = len(layers)
    else:
        nip = _shell_layer_count(sec, state, pid)
        layers = []
        for i in range(nip):
            fi = fvals[i] if i < len(fvals) else 0.0
            layers.append((0.0, thick / nip,
                           glass.mid if fi else glass.glass_mid))
    if fvals and len(fvals) != nip:
        state.warn(
            f"*MAT_LAMINATED_GLASS {glass.mid} on part {pid}: the F array has "
            f"{len(fvals)} entries but the layup has {nip} integration point(s)"
            + (f" (from *INTEGRATION_SHELL {sec.irid}, whose NIP wins over the "
               "section's)" if rule is not None else
               " (the *SECTION_SHELL NIP)")
            + ". Layers beyond the F array default to GLASS; make the counts "
            "match — LS-DYNA requires an *INTEGRATION_SHELL rule whose NIP is "
            "the F count.")
    n_poly = sum(1 for _, _, m in layers if m == glass.mid)
    state.warn(
        f"*MAT_LAMINATED_GLASS {glass.mid} on part {pid}: /PROP/TYPE11 "
        f"{prop_id} binds {nip - n_poly} glass and {n_poly} polymer layer(s) "
        f"(F_i = 0 → glass, F_i != 0 → polymer). "
        + (f"Layer thicknesses come from the *INTEGRATION_SHELL {sec.irid} rule "
           "the material requires, so an unequal glass/interlayer stack "
           "converts as written."
           if rule is not None else
           # _layered_rule() is None for an ESOP=1 rule BY DESIGN (equal layers
           # need no layered property), and also for a rule that was dropped —
           # so "this section references none" would be a flat lie whenever
           # sec.irid is set. Say which of the three cases actually holds.
           "Layer thicknesses are the section thickness split EVENLY. "
           + ("LS-DYNA takes them from the *INTEGRATION_SHELL rule the "
              "material requires, and this section references none (card-1 "
              "field 6, QR/IRID, is not a negative rule id), so an unequal "
              "glass/interlayer stack needs either that rule added or the "
              "layer thicknesses edited by hand."
              if sec.irid <= 0 else
              f"The *INTEGRATION_SHELL {sec.irid} rule this section "
              "references is ESOP=1, i.e. NIP layers of EQUAL thickness with "
              "no S/WF/PID cards — so the even split IS the rule, faithfully. "
              "Give the rule ESOP=0 and per-point WF if the glass and the "
              "interlayer are meant to differ in thickness."
              if _usable_rule(state, sec) is not None else
              f"The *INTEGRATION_SHELL {sec.irid} rule this section "
              "references was DROPPED (see the warning above it), so an "
              "unequal glass/interlayer stack is LOST until the rule is "
              "fixed.")))
    axis = _RefAxis(ip=20, phi=beta_fold,
                    note="isotropic LAW27 phases (no material axes)")
    return _emit_rule_layup(state, prop_id, pid,
                            f"LAMINATED_GLASS_PROP_{prop_id} (part {pid})",
                            sec, layers, thick, axis, istrain)


def _emit_prop_type11(prop_id: int, title: str, sec: SectionShell,
                      state: ConversionState, layers, thick: float,
                      axis: "_RefAxis", istrain: int) -> List[str]:
    """/PROP/TYPE11 (SH_SANDW) — the layered shell property that carries
    ``mat_ID + thickness + angle`` inline per layer, with no /PLY object graph.

    Column layout from ``PROP/prop_p11_sh_sandw.cfg FORMAT(radioss2022)``:
    card 2 always has all five Hm/Hf/Hr/Dm/Dn fields (no Ishell branch, unlike
    TYPE51/TYPE17), and each layer is ONE line ``Phi Thick Z m _ F_weight``.

    *layers* is a list of ``(phi, thickness, mat_id)``.
    """
    ishell = _elform_to_ishell(sec.elform, state.is_implicit,
                               state.options.shell_default_ishell)
    b10, b20 = " " * 10, " " * 20
    lines = [
        f"/PROP/TYPE11/{prop_id}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill                            P_Thick_Fail",
        f"{_i(ishell)}{_i(0)}{_i(0)}{_i(0)}{b20}{_f(0.0)}",
        "#                 Hm                  Hf                  Hr                  Dm                  Dn",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#        N   Istrain               Thick              Ashear              Ithick     Iplas",
        f"{_i(len(layers))}{_i(istrain)}{_f(thick)}{_f(_ASHEAR_DEFAULT)}{b10}"
        f"{_i(0)}{_i(0)}",
        "#                 Vx                  Vy                  Vz     Iskew     Iorth      Ipos        Ip",
        f"{_f(axis.vec[0])}{_f(axis.vec[1])}{_f(axis.vec[2])}{_i(axis.skew_id)}"
        f"{_i(0)}{_i(0)}{_i(axis.ip)}",
        "#                Phi               Thick                   Z         m                      F_weight",
    ]
    for (phi, t, m) in layers:
        lines.append(f"{_f(phi + axis.phi)}{_f(t)}{_f(0.0)}{_i(m)}{b10}{_f(0.0)}")
    lines.append(HDR)
    return lines


def _emit_part_composite_prop(state: ConversionState, pc: PartComposite,
                              prop_id: int, istrain: int) -> List[str]:
    """*PART_COMPOSITE → /PROP/TYPE51 (stack) + one /PROP/TYPE19 (PLY) per ply,
    following dyna2rad's ``p_ConvertPartComposites``.

    ``Ishell`` comes from ``_elform_to_ishell`` — the SAME mapping (and the same
    ``convert(shell_formulation=...)`` / ``--shell-formulation`` user option)
    every other k2rad shell property honours, so one LS-DYNA ELFORM cannot
    produce two different Radioss formulations depending on whether the part
    happened to use *SECTION_SHELL or *PART_COMPOSITE. ``NLOC`` maps onto
    ``Ipos`` (0 = mid-surface, -1 = bottom → Ipos 4, +1 = top → Ipos 3).

    The orthotropy system comes from the FIRST ORTHOTROPIC ply material, which is
    what LS-DYNA specifies (*PART_COMPOSITE Remark 1: "the orthotropic material
    orientation parameters from the material model of the first orthotropic
    integration point apply to all"; AOPT/BETA of later plies are ignored).
    dyna2rad reads ply 0 unconditionally, which loses the axes when ply 0 happens
    to be an isotropic layer.

    The per-ply angle ``B_i`` rides on each ply's own ``delta_phi``, applied on
    top of that shared reference direction.
    """
    plies = _valid_plies(pc)
    dropped = len(pc.plies) - len(plies)
    ishell = _elform_to_ishell(pc.elform, state.is_implicit,
                               state.options.shell_default_ishell)
    ipos, z0 = 0, 0.0
    if pc.nloc <= -1.0:
        ipos = 4                     # bottom of the layup = element mid-surface
    elif pc.nloc >= 1.0:
        ipos = 3                     # top of the layup = element mid-surface
    # SHRF is carried only when the deck actually gave it (the handler records a
    # blank field as 0.0). Defaulting a blank to LS-DYNA's own 1.0 would make
    # the part 20% stiffer in transverse shear than Radioss's 5/6 default, which
    # is what dyna2rad leaves in place and what every other k2rad shell property
    # writes — a silent divergence driven by a default rather than deck data.
    ashear = pc.shrf if 0.0 < pc.shrf <= 1.0 else _ASHEAR_DEFAULT
    total_t = sum(p.thick for p in plies)

    # Material axes from the first ORTHOTROPIC ply material.
    axis = _RefAxis(ip=20, note="element frame (no orthotropic ply material)")
    for ply in plies:
        mat = (state.mat_orthotropic.get(ply.mid)
               or state.mat_enhanced_composite.get(ply.mid))
        if mat is not None:
            axis = _composite_ref_axis(
                mat, state, f"/PROP/TYPE51 for *PART_COMPOSITE {pc.pid}",
                prop_id)
            if axis.mapped:
                state.warn(
                    f"*PART_COMPOSITE {pc.pid}: the layup orthotropy system is "
                    f"taken from ply material {ply.mid} (the first orthotropic "
                    f"ply) — {axis.note}. Per-ply B_i angles are applied on top "
                    "of it, as LS-DYNA specifies.")
            break

    ply_ids: List[int] = []
    ply_lines: List[str] = []
    for k, ply in enumerate(plies):
        ply_prop = state.next_prop_id()
        ply_ids.append(ply_prop)
        ply_lines += _emit_prop_type19(
            ply_prop, f"{pc.title or f'PART_{pc.pid}'} - ply {k + 1}"[:100],
            ply.mid, ply.thick, ply.beta)
        if ply.tmid:
            state.warn(
                f"*PART_COMPOSITE {pc.pid} ply {k + 1}: TMID={ply.tmid} "
                "(thermal material) has no /PROP/TYPE19 counterpart and is "
                "DROPPED — k2rad converts no thermal solver cards.")

    # axis.lines carries the /SKEW/FIX an AOPT=2 ply material synthesized — it
    # MUST be emitted, or the TYPE51's skew_ID dangles (starter ERROR 184 WRONG
    # SKEW SYSTEM ID, then ERROR 1923 INVALID ZERO SKEW_ID WITH IP=22).
    lines = list(axis.lines)
    lines += _emit_prop_type51(prop_id,
                               f"{pc.title or f'PART_COMPOSITE_{pc.pid}'}"[:100],
                               ishell, ipos, z0, ashear, axis, ply_ids, istrain)
    lines += ply_lines
    notes = []
    if dropped:
        notes.append(
            f"{dropped} layer(s) with MID<=0 or zero thickness were skipped "
            "(LS-DYNA's 'missing ply' padding, which only keeps integration-"
            "point numbering aligned)")
    if pc.irpl:
        notes.append(
            f"the OPTCARD IRPL={pc.irpl} through-thickness integration rule is "
            "DROPPED (Radioss plies carry Npt_ply=1, i.e. one point at each "
            "ply mid-surface)")
    if pc.marea:
        notes.append(
            f"MAREA={pc.marea:g} (non-structural mass per unit area) is DROPPED, "
            "so the part comes out LIGHTER than the LS-DYNA original — which "
            "changes both its inertia and its nodal time step. dyna2rad DOES "
            "convert this field (to an /ADMAS type 2 over a /SET/GENERAL of the "
            "part); add an equivalent /ADMAS by hand if the added mass matters")
    if pc.optt:
        notes.append(
            f"the _CONTACT OPTT={pc.optt:g} contact thickness is DROPPED "
            "(Radioss takes the contact gap from the /INTER card)")
    if pc.adpopt or pc.thshel:
        notes.append("ADPOPT/THSHEL (adaptivity, thermal shell) are DROPPED")
    state.warn(
        f"*PART_COMPOSITE {pc.pid}: per-ply layup → /PROP/TYPE51/{prop_id} with "
        f"{len(plies)} /PROP/TYPE19 ply properties {ply_ids} (total thickness "
        f"{total_t:g}, Ishell={ishell}, Ipos={ipos}, Ashear={ashear:g}). The "
        "part is repointed at it and its *SECTION-derived property is no longer "
        "used."
        + ("" if not notes else " Dropped: " + "; ".join(notes) + "."))
    # The check is against the MATERIAL namespace only. Testing `ply.mid` against
    # state.parts as well (PIDs) silently suppressed the warning whenever any
    # *PART happened to carry the ply material's number — two unrelated LS-DYNA
    # id spaces. Ryan_Lee_Examples/W6_SETUP_SandwichImpact.k is exactly that
    # shape: plies with MID=1 (*MAT_COMPOSITE_DAMAGE, not converted) and a
    # *PART with PID=1, so the dangling reference went out unreported.
    for mid in sorted({p.mid for p in plies}):
        if not _mid_is_known(state, mid):
            state.warn(
                f"*PART_COMPOSITE {pc.pid}: ply material {mid} is NOT emitted "
                "as a /MAT by this conversion — either the deck defines no "
                "*MAT with that id, or its law is one k2rad does not convert. "
                f"The /PROP/TYPE19 mat_ID={mid} will dangle and the starter "
                "will reject the property; supply a supported material for "
                "that ply.")
    return lines


def _mid_is_known(state: ConversionState, mid: int) -> bool:
    return mid in state.all_mat_ids()


def _emit_prop_type51(prop_id: int, title: str, ishell: int, ipos: int,
                      z0: float, ashear: float, axis: "_RefAxis",
                      ply_ids: List[int], istrain: int) -> List[str]:
    """/PROP/TYPE51 — the stack property referencing one /PROP/TYPE19 per ply.

    Column layout from ``PROP/prop_p51.cfg FORMAT(radioss2022)``. Card 2 carries
    the ``Dn`` field only for the physically-stabilized Ishell 12/24 (a
    ``CARD_PREREAD`` on card 1 picks the variant); both values k2rad emits are in
    that set, so the five-field form is always used.

    **Each ply takes TWO lines** — the ply card and a mandatory BLANK line. The
    importer counts free cards and divides by two (``Phi_Zi_Size =
    _GET_NB_FREE_CARDS() / 2``), so omitting the blank line halves the ply count
    silently.
    """
    b10 = " " * 10
    lines = [
        f"/PROP/TYPE51/{prop_id}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill        P_thick_fail                  Z0",
        f"{_i(ishell)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}{_f(z0)}",
        "#                 Hm                  Hf                  Hr                  Dm                  Dn",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#             Istrain              Ashear                Iint              Ithick                Fexp",
        f"{b10}{_i(istrain)}{_f(ashear)}{b10}{_i(0)}{b10}{_i(1)}{_f(1.0)}",
        "#                 Vx                  Vy                  Vz   skew_ID     Iorth      Ipos        Ip",
        f"{_f(axis.vec[0])}{_f(axis.vec[1])}{_f(axis.vec[2])}{_i(axis.skew_id)}"
        f"{_i(0)}{_i(ipos)}{_i(axis.ip)}",
        "#   Ply_id                 Phi                  Zi         P_thickfail           F_weighti",
    ]
    for pid19 in ply_ids:
        lines.append(f"{_i(pid19)}{_f(axis.phi)}{_f(0.0)}{_f(0.0)}{_f(0.0)}")
        lines.append("")                 # mandatory second line per ply
    lines.append(HDR)
    return lines


def _emit_prop_type19(prop_id: int, title: str, mat_id: int, thick: float,
                      delta_phi: float) -> List[str]:
    """/PROP/TYPE19 (PLY) — one ply of a TYPE51 stack.

    Column layout from ``PLY/prop_ply.cfg FORMAT(radioss2017)``:
    ``mat_ID(10) t(20) delta_phi(20) grsh4n_ID(10) grsh3n_ID(10) Npt_ply(10)
    alpha_i(20)``. Both group ids are 0, which scopes the ply to every element
    of the part. ``alpha_i`` (the angle between orthotropy directions 1 and 2) is
    left at 0 → the reader's 90-degree default. The optional
    ``drape_ID / def_orth`` card is omitted, so ``def_orth`` keeps its default 2
    (take the orientation from the stack's skew/vector) — writing 1 there would
    make the ply ignore the TYPE51 reference direction entirely.
    """
    return [
        f"/PROP/TYPE19/{prop_id}",
        title,
        "#   mat_ID                   t           delta_phi grsh4n_ID grsh3n_ID   Npt_ply             alpha_i",
        f"{_i(mat_id)}{_f(thick)}{_f(delta_phi)}{_i(0)}{_i(0)}{_i(1)}{_f(0.0)}",
        HDR,
    ]
