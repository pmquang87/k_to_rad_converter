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
converted part can NEVER stay on the isotropic section property or the starter
aborts with **ERROR 3047**. Each part therefore gets a dedicated orthotropic
property, allocated by ``_assign_composite_props`` into
``state.composite_prop_ids`` and emitted by ``_emit_composite_props``; this is
the same /PROP-split mechanism the LAW128 (MAT_103) path uses.

Note this is precisely the bug dyna2rad has: ``p_ConvertSectionShell``
(``convertprops.cxx:734-765``) matches neither MAT_054/055 nor
*MAT_ANISOTROPIC_ELASTIC, so both fall through to ``/PROP/TYPE1`` and hard-fail
the starter.
"""

from __future__ import annotations

from typing import List, Optional, Set

from ..state import (
    ConversionState,
    MatOrthotropicElastic,
    MatEnhancedCompositeDamage,
    MatTransverselyAnisotropic,
    MatLaminatedGlass,
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
    "_make_composite_materials",
    "_emit_composite_props",
    "_emit_mat_law93",
    "_emit_mat_law127",
    "_emit_mat_law43",
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
# *MAT_054/055 TFAIL: the boundary between LS-DYNA's ABSOLUTE minimum-time-step
# form (0 < TFAIL <= 0.1) and its RATIO form (TFAIL > 0.1), Manual Vol II R17
# p.2-441. Only the absolute form has a Radioss counterpart (/FAIL/GENE1 dtmin).
_TFAIL_ABSOLUTE_MAX = 0.1


def _composite_material_mids(state: ConversionState) -> Set[int]:
    """Every MID handled by this module (used by the /PROP-split prepasses)."""
    return (set(state.mat_orthotropic) | set(state.mat_enhanced_composite)
            | set(state.mat_transverse_aniso) | set(state.mat_laminated_glass))


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


# ─────────────────────────────────────────────────────────────────────────────
# Prepass: per-part /PROP allocation
# ─────────────────────────────────────────────────────────────────────────────

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
    shell_only_laws = {}
    for mid in state.mat_transverse_aniso:
        shell_only_laws[mid] = ("*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC",
                                "/MAT/LAW43")
    for mid in state.mat_laminated_glass:
        shell_only_laws[mid] = ("*MAT_LAMINATED_GLASS", "/MAT/PLAS_BRIT (LAW27)")

    for pid, part in sorted(state.parts.items()):
        if pid in state.composite_prop_ids:
            continue
        pc = state.part_composites.get(pid)
        is_composite_part = pc is not None and _layup_is_convertible(pc)
        if not is_composite_part and part.mid not in comp_mids:
            continue
        if pid not in shell_pids and pid not in solid_pids:
            state.warn(
                f"Composite part {pid}: no shell or solid elements found, so no "
                "orthotropic property can be synthesized. The part keeps its "
                "default property, which the starter rejects as incompatible "
                "with an orthotropic material (ERROR 3047) — check the mesh.")
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
    b10 = " " * 10
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
    lines = [
        f"/MAT/LAW43/{mat.mid}",
        mat.title or f"MAT_{mat.mid}",
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                  E                  NU",
        f"{_f(mat.E)}{_f(mat.nu)}",
        "#FUNCT_IDE                          EINF                  CE",
        f"{_i(mat.idscale)}{b10}{_f(mat.ea)}{_f(mat.coe)}",
        "#                r00                 r45                 r90              C_hard   Iyield0",
        f"{_f(r)}{_f(r)}{_f(r)}{_f(0.0)}{_i(0)}",
        "#           EPSP_max               EPS_t               EPS_m                Fcut   Fsmooth",
        f"{_f(1.0e30)}{_f(1.0e30)}{_f(2.0e30)}{_f(0.0)}{_i(0)}",
        "# func_IDi                      Fscale_i           EPS_dot_i",
        f"{_i(mat.hard_func_id)}{b10}{_f(1.0)}{_f(0.0)}",
        HDR,
    ]
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
        if mid in state.mat_laminated_glass:
            lines += _emit_laminated_glass_prop(
                state, state.mat_laminated_glass[mid], pid, prop_id, sec, istrain)
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
                                      istrain, state)
        else:
            mat = (state.mat_orthotropic.get(mid)
                   or state.mat_enhanced_composite.get(mid))
            if mat is None:
                continue
            is_solid = pid in solid_pids and pid not in shell_pids
            axis = _composite_ref_axis(mat, state, label, prop_id,
                                       for_solid=is_solid)
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
            "resolution is reduced (matches dyna2rad's own clamp).")
        nip = _MAX_SHELL_LAYERS
    return nip


def _emit_single_material_type11(state: ConversionState, prop_id: int, pid: int,
                                 mid: int, sec: SectionShell, axis: "_RefAxis",
                                 istrain: int, law: str) -> List[str]:
    """A one-material layered shell: /PROP/TYPE11 with NIP identical layers.

    dyna2rad routes *MAT_002 here (``convertprops.cxx:736``) but drops MAT_054/055
    through to /PROP/TYPE1, which the starter then rejects (ERROR 3047) because
    /MAT/LAW127 registers PROP_SHELL=2 (orthotropic) and IGTYP 1 accepts only
    classes 1 and 5. Both laws are routed to TYPE11 here.
    """
    nip = _shell_layer_count(sec, state, pid)
    thick = sec.t1
    if thick <= 0.0:
        state.warn(
            f"/PROP/TYPE11/{prop_id} (part {pid}): shell thickness is "
            f"{thick:g} (<=0), which the starter rejects. Set the "
            "*SECTION_SHELL thickness for this composite part.")
    layers = [(0.0, thick / nip, mid) for _ in range(nip)]
    state.warn(
        f"/PROP for composite part {pid}: {law} is orthotropic-class, so the "
        f"part is repointed at a synthesized /PROP/TYPE11 (SH_SANDW) {prop_id} "
        f"with {nip} layer(s) of the section thickness — the isotropic "
        "/PROP/SHELL is rejected by the starter (ERROR 3047)."
        + ("" if law != "/MAT/LAW127" else
           " (dyna2rad leaves MAT_054/055 on /PROP/TYPE1, which hard-fails.)"))
    return _emit_prop_type11(prop_id, f"COMPOSITE_PROP_{prop_id} (part {pid})",
                             sec, state, layers, thick, axis, istrain)


def _emit_laminated_glass_prop(state: ConversionState, glass: MatLaminatedGlass,
                               pid: int, prop_id: int, sec: SectionShell,
                               istrain: int) -> List[str]:
    """*MAT_LAMINATED_GLASS → the layered /PROP/TYPE11 that binds the synthesized
    glass and polymer materials to the integration points.

    **F_i polarity.** LS-DYNA: ``F_i = 0.0`` → glass, ``1.0`` → polymer. dyna2rad
    has TWO contradictory implementations of this — ``ConvertSecShellsRelatedMat
    Laminate`` (``convertprops.cxx:1620-1641``) inverts it AND mutates the
    /PART's mat_ID inside the layer loop, so every layer after the first
    polymer one also becomes polymer; the ``*INTEGRATION_SHELL`` path
    (``:2024-2050``) gets it right. The correct (IRID) polarity is used here.

    With no F array at all every layer is glass, matching dyna2rad.
    """
    nip = _shell_layer_count(sec, state, pid)
    fvals = glass.f
    if fvals and len(fvals) != nip:
        state.warn(
            f"*MAT_LAMINATED_GLASS {glass.mid} on part {pid}: the F array has "
            f"{len(fvals)} entries but the *SECTION_SHELL declares NIP={nip} "
            "integration points. Layers beyond the F array default to GLASS; "
            "make NIP match the F count (LS-DYNA also requires an "
            "*INTEGRATION_SHELL rule with NIPTS = the F count).")
    thick = sec.t1
    layers = []
    n_poly = 0
    for i in range(nip):
        fi = fvals[i] if i < len(fvals) else 0.0
        if fi:
            layers.append((0.0, thick / nip, glass.mid))       # polymer
            n_poly += 1
        else:
            layers.append((0.0, thick / nip, glass.glass_mid))  # glass
    state.warn(
        f"*MAT_LAMINATED_GLASS {glass.mid} on part {pid}: /PROP/TYPE11 "
        f"{prop_id} binds {nip - n_poly} glass and {n_poly} polymer layer(s) "
        f"(F_i = 0 → glass, F_i != 0 → polymer). Layer thicknesses are the "
        "section thickness split EVENLY — LS-DYNA takes them from the "
        "*INTEGRATION_SHELL rule the material requires, which k2rad does not "
        "read, so an unequal glass/interlayer stack needs the layer thicknesses "
        "edited by hand.")
    axis = _RefAxis(ip=20, note="isotropic LAW27 phases (no material axes)")
    return _emit_prop_type11(prop_id, f"LAMINATED_GLASS_PROP_{prop_id} "
                             f"(part {pid})", sec, state, layers, thick, axis,
                             istrain)


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
