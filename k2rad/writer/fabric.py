"""
k2rad.writer.fabric  –  *MAT_FABRIC (*MAT_034) → /MAT/LAW19 + /PROP/TYPE9
                        or /MAT/LAW58 + /PROP/TYPE16.

Its own module, beside ``composites.py`` / ``tshell.py`` / ``sph.py``, because
the fabric law and its property are ONE decision: the starter's
material/property class check accepts /MAT/LAW19 only on the orthotropic-shell
property family (PROP_SHELL 2 → /PROP/TYPE9) and /MAT/LAW58 only on the
anisotropic one (PROP_SHELL 4 → /PROP/TYPE16), and crossing them — or leaving
the fabric part on the isotropic /PROP/SHELL its *SECTION_SHELL would give it —
is starter ``ERROR 3047``. Splitting the law into ``materials.py`` and the
property into ``mesh.py`` would put the two halves of one rule in two files.

Contents
  _resolve_mat_fabric   – LAW19-vs-LAW58 routing, derived moduli, FORM warnings
  _assign_fabric_props  – build_starter prepass: one /PROP id per fabric part
  _make_fabric_materials – the /MAT/LAW19 and /MAT/LAW58 cards
  _emit_fabric_props    – the paired /PROP/TYPE9 and /PROP/TYPE16 cards
  _emit_prop_type16     – the layered anisotropic shell property (new in k2rad)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..state import (
    ConversionState, MatFabric, SectionShell,
    FABRIC_CURVE_FORMS, FABRIC_ELASTIC_FORMS,
)
from .common import HDR, _f, _i, _elform_to_ishell

__all__ = [
    "_resolve_mat_fabric",
    "_assign_fabric_props",
    "_make_fabric_materials",
    "_emit_fabric_props",
    "_emit_prop_type16",
    "_emit_mat_law19",
    "_emit_mat_law58",
    "_fabric_law",
    "FABRIC_FORM_NOTES",
]


#: FORM → the LS-DYNA specialisation that has NO faithful Radioss target and is
#: therefore named as dropped. The MATERIAL still converts (to whichever of
#: LAW19/LAW58 the routing picks); what is dropped is the model refinement the
#: FORM number selects. Sourced from Vol II R16 pp.2-320…2-330.
FABRIC_FORM_NOTES: Dict[int, str] = {
    1: "FORM=1 (the 'more accurate' large-strain update of FORM 0) — Radioss "
       "LAW19 has a single orthotropic update, so the refinement is dropped; "
       "the elastic constants are converted unchanged",
    2: "FORM=2 (FORM 1 with the material angle updated by the element rotation)"
       " — Radioss carries the angle on the property (Phi) and does not "
       "co-rotate it with the yarns, so the update is dropped",
    3: "FORM=3 (FORM 2 with NON-ORTHOGONAL yarn kinematics) — the shear "
       "response of a sheared weave has no LAW19 counterpart and LAW58's "
       "AlphaT is a LOCKING angle, not an initial weave angle, so nothing "
       "faithful can be written for it; the fabric converts as ORTHOTROPIC",
    4: "FORM=4 (tabulated stress/strain with no unloading model)",
    8: "FORM=8 (FORM 0 with the *MAT_FABRIC liner treated as a separate "
       "layer) — Radioss has no liner slot at all; the liner is dropped",
    12: "FORM=12 (Ivanov fabric model) — the Ivanov biaxial coupling has no "
        "Radioss counterpart; the fabric converts as plain orthotropic",
    13: "FORM=13 (Ivanov with the shear specialisation) — same as FORM 12, "
        "plus a shear model Radioss does not have; converts as orthotropic",
    24: "FORM=24 (FORM 14 with a reloading path) — the RL reloading parameter "
        "has no LAW58 slot; the unloading curves are converted and reloading "
        "follows them",
}


def _fabric_law(mat: MatFabric) -> int:
    """19 or 58 — the Radioss law this ``*MAT_FABRIC`` converts to.

    A pure function of the CARD, so the material writer, the property writer
    and ``mesh._target_mat_law`` cannot drift apart (the #100 one-map rule).

    The branch is **FORM in {4, 14, -14, 24} AND at least one card-7 curve**.
    Those four FORMs are the only ones whose card 7 exists at all, and without a
    curve on it there is nothing tabulated to put in LAW58's FCT_ID1..6 — the
    material is then a plain orthotropic elastic fabric and LAW19 states it
    exactly, with fewer starter preconditions (LAW58 forces all three loading
    curves as soon as any unloading one is set, ERROR 1578/1579/1580).

    Same predicate as dyna2rad's (``convertmats.cxx:2043`` and the mirrored
    property branch at ``convertprops.cxx:701``), widened from {14, -14} to the
    manual's full card-7 set so a FORM=4 or FORM=24 deck's curves are not
    silently discarded onto LAW19.
    """
    return 58 if (mat.form in FABRIC_CURVE_FORMS and mat.has_curves()) else 19


def _fabric_nu12(mat: MatFabric) -> float:
    """The Poisson's ratio written into LAW19's ``NU12``.

    Radioss defines ``nu21 = NU12 * E22 / E11`` (``hm_read_mat19.F``), i.e.
    ``NU12 / E11 == nu21 / E22`` — the standard reciprocity, so ``NU12`` is the
    ratio that pairs with **E11**, the warp/a direction. LS-DYNA's PRAB is
    ``nu_ab`` with a ↔ 1, so **PRAB is the field that maps**, and PRBA is its
    reciprocal partner.

    PRAB is nevertheless blank on a great many decks — "For an isotropic
    elastic fabric material, only EA and PRBA are defined" (Vol II R16 p.2-315)
    — so PRBA is used when PRAB is not given. On an isotropic fabric the two
    are equal and the choice is immaterial; on an orthotropic one taking PRBA
    is what dyna2rad does (``convertmats.cxx:2049``) and is the best available
    reading of a card that states only the minor ratio.
    """
    return mat.prab if mat.prab != 0.0 else mat.prba


def _resolve_mat_fabric(state: ConversionState) -> None:
    """build_starter prepass: route each ``*MAT_FABRIC`` to LAW19 or LAW58,
    fill the derived elastic constants, and name every dropped field.

    Runs before ``_assign_fabric_props`` (which needs ``use_law58`` to pick the
    property type), before ``_make_materials`` and before ``_resolve_xref_parts``
    — that gate reads ``mesh._target_mat_law``, and while neither LAW19 nor
    LAW58 is on the starter's SOLID-/XREF whitelist, a fabric part is a SHELL
    part and the shell arm keeps it with no law check, so the entry is what
    stops the gate reporting "no /MAT at all" for a material that plainly
    exists.
    """
    if not state.mat_fabric:
        return
    for mid, mat in sorted(state.mat_fabric.items()):
        mat.use_law58 = _fabric_law(mat) == 58
        mat.nu12 = _fabric_nu12(mat)
        mat.e22 = mat.eb if mat.eb != 0.0 else mat.ea
        # G12 fallback: the isotropic shear modulus of the warp direction. The
        # commented-out legacy in dyna2rad (cm:2107) reads EA*2*(1+nu); the live
        # code divides, which is the correct G = E / (2(1+nu)).
        iso_g = mat.ea / (2.0 * (1.0 + mat.nu12)) if mat.ea else 0.0
        mat.g12 = mat.gab if mat.gab != 0.0 else iso_g
        mat.g23 = mat.gbc if mat.gbc != 0.0 else (
            mat.gab if mat.gab != 0.0 else iso_g)
        mat.g31 = mat.gca if mat.gca != 0.0 else (
            mat.gab if mat.gab != 0.0 else iso_g)
        # CSE → R_E, the starter's RCOMP ("COMPRESSION REDUCTION FACTOR /
        # RCOMP=E11C/E11=E22C/E22"). LS-DYNA CSE=1 means "eliminate compressive
        # stress", which Radioss cannot do exactly — RCOMP is a REDUCTION, and
        # hm_read_mat19.F:143-149 floors it at 1e-3 with WARNING 1572. 0.01 is
        # the approximation dyna2rad picked, deliberately one decade above that
        # floor so the starter does not clamp it and warn.
        mat.r_e = 1.0 if mat.cse == 0.0 else 0.01
        # TSRFAC ("tensile stress reduction factor for the reference geometry")
        # is the closest LS-DYNA field to Radioss's ZEROSTRESS ("REF-STATE
        # STRESS RELAXATION FACTOR"); neither is a rename of the other, so the
        # value is carried only when it is in range and 1.0 (arm the reference
        # state fully) is used otherwise — the unconditional value dyna2rad
        # writes. Both are inert unless a /XREF or /EREF covers the part.
        if 0.0 < mat.tsrfac <= 1.0:
            mat.zerostress = mat.tsrfac
        else:
            mat.zerostress = 1.0
            if mat.tsrfac != 0.0:
                state.warn(
                    f"*MAT_FABRIC {mid}: TSRFAC={mat.tsrfac:g} is outside the "
                    "0..1 range Radioss ZEROSTRESS accepts (matl19_fabri.cfg "
                    "range-checks it), so ZEROSTRESS=1.0 is written instead. "
                    "TSRFAC and ZEROSTRESS are the closest pair, not the same "
                    "quantity; the field is inert unless a reference geometry "
                    "covers the part.")
        # RGBRTH ("material-dependent reference-geometry birth time") → the
        # SENS_ID slot of the law, which the starter stores as
        # MATPARAM%IPARAM(1) and uses to arm the reference state. It is a
        # /SENSOR/TIME with Tdelay = RGBRTH, the same mechanism *LOAD_SEGMENT's
        # AT already uses (writer/loads.py::_emit_sensor_time). The sensor is
        # allocated here, in the prepass, so the id is fixed before any section
        # is written.
        if mat.rgbrth > 0.0:
            mat.sensor_id = state.next_id()
            mat.sensor_tdelay = mat.rgbrth
        _warn_fabric_form(state, mid, mat)
        _warn_fabric_dropped_fields(state, mid, mat)


def _warn_fabric_form(state: ConversionState, mid: int, mat: MatFabric) -> None:
    """Name the FORM specialisation that does not survive the conversion.

    Every FORM converts — to LAW19 or LAW58 — so this is never a drop of the
    MATERIAL. What is dropped is the model refinement the number selects, and
    it is named rather than left to be discovered in the results.
    """
    law = 58 if mat.use_law58 else 19
    if mat.form in FABRIC_ELASTIC_FORMS and mat.form != 12:
        note = FABRIC_FORM_NOTES.get(mat.form)
        if note is None:
            return                      # FORM 0 — LAW19 IS the faithful target
        state.warn(f"*MAT_FABRIC {mid}: {note}. → /MAT/LAW{law}.")
        return
    if mat.form in FABRIC_CURVE_FORMS and mat.use_law58:
        # The tabulated branch: 14 and -14 ARE what LAW58 models, so only the
        # two refinements on top of them are reported.
        if mat.form == -14:
            state.warn(
                f"*MAT_FABRIC {mid}: FORM=-14 selects the no-hysteresis "
                "variant plus the card-8 BIAXIAL curves (LCAA/LCBB), the "
                "normalized hysteresis H and the coat layer "
                "(ECOAT/SCOAT/TCOAT). /MAT/LAW58 has slots for the six "
                "UNIAXIAL warp/weft/shear curves only, so the biaxial pair, H "
                "and the coat are DROPPED; the sign of FORM is otherwise "
                "treated as +14.")
        elif mat.form == 24:
            state.warn(f"*MAT_FABRIC {mid}: {FABRIC_FORM_NOTES[24]}.")
        elif mat.form == 4:
            state.warn(
                f"*MAT_FABRIC {mid}: {FABRIC_FORM_NOTES[4]} → /MAT/LAW58 with "
                "the card-7 loading curves. LAW58 always supports unloading "
                "(it copies the loading curves when FCT_ID4/5/6 are blank), so "
                "the converted material unloads along its loading path rather "
                "than retracing it exactly.")
        return
    if mat.form in FABRIC_CURVE_FORMS:
        state.warn(
            f"*MAT_FABRIC {mid}: FORM={mat.form} declares the tabulated "
            "stress/strain card 7 (LCA/LCB/LCAB/LCUA/LCUB/LCUAB) but every "
            "curve id on it is 0, so there is nothing for /MAT/LAW58's "
            "FCT_ID1..6 to hold — the material converts to the analytic "
            "/MAT/LAW19 (+ /PROP/TYPE9) from EA/EB/GAB/PRBA instead. Give the "
            "card-7 curves if the tabulated model was the point.")
        return
    note = FABRIC_FORM_NOTES.get(mat.form)
    if note:
        state.warn(f"*MAT_FABRIC {mid}: {note}. → /MAT/LAW{law}.")
    else:
        state.warn(
            f"*MAT_FABRIC {mid}: FORM={mat.form} is not one of the forms this "
            "converter maps (0/1/2/12 → /MAT/LAW19, 4/14/-14/24 with card-7 "
            f"curves → /MAT/LAW58). The material converts to /MAT/LAW{law} "
            "from its elastic constants and the FORM specialisation is "
            "DROPPED — check the result against LS-DYNA before trusting it.")


def _warn_fabric_dropped_fields(state: ConversionState, mid: int,
                                mat: MatFabric) -> None:
    """Name the *MAT_FABRIC fields that reach no Radioss slot at all."""
    if mat.lratio != 0.0 or mat.el != 0.0:
        state.warn(
            f"*MAT_FABRIC {mid}: the LINER (EL={mat.el:g}, PRL={mat.prl:g}, "
            f"LRATIO={mat.lratio:g}) is DROPPED — neither /MAT/LAW19 nor "
            "/MAT/LAW58 has a liner layer, and LS-DYNA's liner carries its own "
            "elastic-plastic response over LRATIO of the thickness. The "
            "converted fabric is the base weave alone, so it is softer in "
            "compression and in shear than the LS-DYNA model. Model the liner "
            "as a second co-located shell part if it is load-bearing.")
    if mat.flc != 0.0 or mat.fac != 0.0 or mat.fvopt != 0.0:
        state.warn(
            f"*MAT_FABRIC {mid}: the POROSITY / leakage fields (FLC="
            f"{mat.flc:g}, FAC={mat.fac:g}, FVOPT={mat.fvopt:g}) are DROPPED. "
            "In Radioss fabric leakage is a property of the MONITORED VOLUME, "
            "not of the material — it is a porous-surface block (Nporsurf) on "
            "/MONVOL/AIRBAG1 or a /LEAK/MAT — and neither is emitted by this "
            "batch. The converted bag does not leak through its fabric, so it "
            "holds MORE pressure than the LS-DYNA model; add the vent area to "
            "*AIRBAG_SIMPLE_AIRBAG_MODEL's MU/AREA if the leakage matters.")
    if mat.ela != 0.0 or mat.lnrc != 0.0:
        state.warn(
            f"*MAT_FABRIC {mid}: ELA={mat.ela:g} / LNRC={mat.lnrc:g} (the "
            "slack-region 'effective linear analysis' modulus and the "
            "no-compression-after-slack flag) are DROPPED — Radioss states the "
            "same idea as the single R_E compression-reduction factor, which "
            f"is written from CSE ({mat.cse:g} → R_E {mat.r_e:g}).")
    if mat.x0 != 0.0 or mat.x1 != 0.0:
        state.warn(
            f"*MAT_FABRIC {mid}: the seal-vent leakage-area parameters "
            f"X0={mat.x0:g} / X1={mat.x1:g} are DROPPED (no Radioss "
            "counterpart; see the porosity note above).")
    if mat.a0ref != 0.0:
        state.warn(
            f"*MAT_FABRIC {mid}: A0REF={mat.a0ref:g} (the reference element "
            "area the leakage model measures against) is DROPPED with the "
            "porosity fields it belongs to.")
    if mat.isrefg:
        state.warn(
            f"*MAT_FABRIC {mid}: ISREFG={mat.isrefg} asks LS-DYNA to "
            "initialize the stress from *AIRBAG_REFERENCE_GEOMETRY. In Radioss "
            "that is not a material flag — emitting a /XREF (or /EREF) for the "
            "part IS the request, and both fabric laws honour it "
            "(cepsini.F::CMLAWI dispatches ILAW 1, 19 and 58). No field is "
            "written for ISREFG; the reference state comes from the "
            "*AIRBAG_REFERENCE_GEOMETRY card alone. Note ISREFG is documented "
            "for FORM=12 only.")


# ─────────────────────────────────────────────────────────────────────────────
# Property assignment
# ─────────────────────────────────────────────────────────────────────────────

def _fabric_part_ids(state: ConversionState) -> Set[int]:
    """Every *PART whose material is a *MAT_FABRIC."""
    return {pid for pid, part in state.parts.items()
            if part.mid in state.mat_fabric}


def _assign_fabric_props(state: ConversionState) -> None:
    """build_starter prepass: one synthesized /PROP id per fabric part.

    The #110 honeycomb shape, for the same class of reason and a stricter one.
    The honeycomb's ``/PROP/TYPE6`` is needed because the starter ACCEPTS
    LAW50 on a plain /PROP/SOLID but never builds its orthotropy tensor there;
    the fabric's property is needed because the starter REFUSES the wrong one:

      * ``/MAT/LAW19`` → ``PROP_SHELL = 2`` (``hm_read_mat19.F:236``
        ``INIT_MAT_KEYWORD(MATPARAM,"SHELL_ORTHOTROPIC")``), which
        ``check_mat_elem_prop_compatibility.F:174-179`` accepts on IGTYP 9 and
        rejects on IGTYP 16 and on the isotropic IGTYP 1;
      * ``/MAT/LAW58`` → ``PROP_SHELL = 4`` (``hm_read_mat58.F:334``
        ``"SHELL_ANISOTROPIC"``), accepted on IGTYP 16 (``:194-197``) and
        rejected on IGTYP 9.

    Either mismatch is ``ERROR 3047`` — "PROPERTY ID %d OF TYPE %d IS NOT
    COMPATIBLE WITH MATERIAL ID %d OF TYPE %d" — and refuses the whole deck.
    A *SECTION_SHELL shared with a non-fabric part cannot simply be RETYPED,
    so the fabric parts are repointed at a per-PID property and the section
    keeps its own /PROP/SHELL for everyone else. That per-PID allocation also
    sidesteps the SECID namespace entirely, which is why fabric needs no
    ``_split_mixed_family_sections`` of its own (#120/#121).

    Runs BEFORE ``_assign_composite_props`` / ``_assign_ortho_props`` /
    ``_assign_hourglass_props`` (all three skip a part claimed here), before
    ``_make_parts_and_elements`` (which repoints the /PART) and before
    ``_make_properties`` (which suppresses the now-unused section property).
    """
    if not state.mat_fabric:
        return
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    tshell_pids = {e.pid for e in state.tshell_elems}
    beam_pids = {e.pid for e in state.beam_elems}
    sph_pids = {c.pid for c in state.sph_elems}
    for pid in sorted(_fabric_part_ids(state)):
        part = state.parts[pid]
        mat = state.mat_fabric[part.mid]
        law = 58 if mat.use_law58 else 19
        prop = "TYPE16" if mat.use_law58 else "TYPE9"
        if pid in shell_pids:
            state.fabric_prop_ids[pid] = state.next_prop_id()
            continue
        if pid in solid_pids or pid in tshell_pids or pid in beam_pids \
                or pid in sph_pids:
            kind = ("solid" if pid in solid_pids else
                    "thick-shell" if pid in tshell_pids else
                    "beam" if pid in beam_pids else "SPH")
            state.warn(
                f"*MAT_FABRIC {part.mid} on part {pid}: the part holds {kind} "
                f"elements, but /MAT/LAW{law} is a SHELL-ONLY law — LS-DYNA "
                "itself says *MAT_FABRIC is \"valid for 3 and 4 node membrane "
                "elements only\" (Vol II R16 p.2-312) and the Radioss starter "
                f"declares it {'SHELL_ANISOTROPIC' if mat.use_law58 else 'SHELL_ORTHOTROPIC'} "
                "with no solid class at all (ERROR 3046). No "
                f"/PROP/{prop} is synthesized for this part — re-mesh the "
                "fabric as shells, or give the part an isotropic material.")
            continue
        # Element-free part: no group reaches the compatibility check
        # (check_mat_elem_prop_compatibility.F loops over NGROUP), so the
        # starter accepts it. Read as a MESH check, exactly like the composite
        # element-free arm.
        state.warn(
            f"*MAT_FABRIC {part.mid} on part {pid}: the part has no elements, "
            f"so no /PROP/{prop} is synthesized and no fabric physics is "
            "attached. The starter accepts this (its material/property check "
            "runs per ELEMENT GROUP and an empty part contributes none) — read "
            "it as a mesh check: a fabric material is normally written for a "
            "meshed part, so an empty one is usually a PID typo or an "
            "*INCLUDE that did not resolve.")


# ─────────────────────────────────────────────────────────────────────────────
# /MAT/LAW19 (FABRI) and /MAT/LAW58 (FABR_A)
# ─────────────────────────────────────────────────────────────────────────────

def _emit_mat_law19(mat: MatFabric) -> List[str]:
    """/MAT/LAW19 (FABRI) — orthotropic elastic fabric.

    Column layout from ``MAT/matl19_fabri.cfg FORMAT(radioss120)``, the newest
    block at /BEGIN 2022 (no later CFG dir overrides it), reader
    ``materials/mat/mat019/hm_read_mat19.F``::

        /MAT/LAW19/<mid>
        <title, 100>
        RHO_I(20) [RHO_O(20)]
        E11(20) E22(20) NU12(20)
        G12(20) G23(20) G31(20)
        R_E(20) <20 DEAD> ZEROSTRESS(20) FSCALE_POR(20) SENS_ID(10)

    Two traps on the last card, both verified by a starter twin-probe:

      * columns 21-40 are a **dead slot** the reader never touches (the cfg
        calls it ``a_r``); a value written there is echoed nowhere. ZEROSTRESS
        is at columns 41-60, NOT 21-40.
      * RHO_O (card-1 columns 21-40) switches the card layout through a
        ``CARD_PREREAD`` on non-blank, so it is left blank unless wanted —
        the starter then defaults ``RHOR = RHO0``.

    Starter hard checks respected by ``_resolve_mat_fabric``'s fallbacks: any
    of E11/E22/G12/G23/G31 equal to zero is ``ERROR 306``, and
    ``1 - NU12*NU21 <= 0`` is ``ERROR 307``.
    """
    b20 = " " * 20
    return [
        f"/MAT/LAW19/{mat.mid}",
        (mat.title or f"FABRIC_{mat.mid}")[:100],
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                E11                 E22                NU12",
        f"{_f(mat.ea)}{_f(mat.e22)}{_f(mat.nu12)}",
        "#                G12                 G23                 G31",
        f"{_f(mat.g12)}{_f(mat.g23)}{_f(mat.g31)}",
        "#                R_E                              ZEROSTRESS"
        "          FSCALE_POR   SENS_ID",
        f"{_f(mat.r_e)}{b20}{_f(mat.zerostress)}{_f(0.0)}{_i(mat.sensor_id)}",
        HDR,
    ]


def _emit_mat_law58(mat: MatFabric) -> List[str]:
    """/MAT/LAW58 (FABR_A) — anisotropic fabric with tabulated warp/weft/shear.

    Column layout from ``MAT/matl58_fabr_a.cfg FORMAT(radioss2017)`` (no later
    override), reader ``materials/mat/mat058/hm_read_mat58.F``::

        /MAT/LAW58/<mid>
        <title, 100>
        RHO_I(20) [RHO_O(20)]
        E1(20) B1(20) E2(20) B2(20) Flex(20)
        G0(20) GT(20) AlphaT(20) Gsh(20) <10 blank> sensor_ID(10)
        Df(20) Ds(20) GFROT(20) <20 blank> ZERO_STRESS(20)
        N1(10) N2(10) S1(20) S2(20) FLEX1(20) FLEX2(20)
        [FCT_ID1(10) <10 blank> Fscale1(20)]      — optional FREE_CARDs
        [FCT_ID2(10) <10 blank> Fscale2(20)]
        [FCT_ID3(10) <10 blank> Fscale3(20)]
        [FCT_ID4(10) FCT_ID5(10) Fscale4(20) Fscale5(20) FCT_ID6(10) Fscale6(20)]

    The reader's own rule for the optional cards (``hm_read_mat58.F``):

      a) with no unloading function the loading curves are optional, and
         analytic and tabulated loading may be mixed;
      b) as soon as ANY unloading curve is given, all three LOADING curves
         become mandatory — a missing one is ``ERROR 1578/1579/1580`` — and
         Radioss fills a missing unloading curve from its loading twin.

    ``_law58_curve_cards`` enforces (b) by refusing to write the unloading card
    when a loading curve is missing, rather than emitting a deck the starter
    refuses.

    ``Flex`` is the LAW58 analogue of LAW19's ``R_E``: LS-DYNA CSE=0 keeps the
    compressive stiffness (Flex = 1.0) and CSE=1 eliminates it (Flex = 0.01,
    the same one-decade-above-the-floor approximation R_E uses).
    """
    b10, b20 = " " * 10, " " * 20
    flex = 1.0 if mat.cse == 0.0 else 0.01
    # G0 = the initial shear modulus; GT the tangent one. With GAB given, GAB
    # IS the initial modulus and GT is left 0 so the starter derives it
    # (0 → 0.25*(E1+E2)). Without GAB, both are left 0 and the starter's own
    # defaults apply — which is strictly better than dyna2rad's EA/2 guess
    # (convertmats.cxx:2146 carries a "??? to be checked (with spec)" comment
    # on that very line) plus its GT = EA and AlphaT = 18 degrees.
    g0 = mat.gab
    lines = [
        f"/MAT/LAW58/{mat.mid}",
        (mat.title or f"FABRIC_{mat.mid}")[:100],
        "#              RHO_I",
        f"{_f(mat.rho)}",
        "#                 E1                  B1                  E2"
        "                  B2                Flex",
        f"{_f(mat.ea)}{_f(0.0)}{_f(mat.e22)}{_f(0.0)}{_f(flex)}",
        "#                 G0                  GT              AlphaT"
        "                 Gsh           sensor_ID",
        f"{_f(g0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{b10}{_i(mat.sensor_id)}",
        "#                 Df                  Ds               GFROT"
        "                                 ZERO_STRESS",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{b20}{_f(mat.zerostress)}",
        "#       N1        N2                  S1                  S2"
        "               FLEX1               FLEX2",
        f"{_i(0)}{_i(0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
    ]
    lines += _law58_curve_cards(mat)
    lines.append(HDR)
    return lines


def _law58_curve_cards(mat: MatFabric) -> List[str]:
    """The optional FCT_ID1..6 cards of a /MAT/LAW58, in reader order."""
    out: List[str] = []
    b10 = " " * 10
    loading = (mat.lca, mat.lcb, mat.lcab)
    unloading = (mat.lcua, mat.lcub, mat.lcuab)
    for label, fid in zip(("1", "2", "3"), loading):
        if fid:
            out += [f"#  FCT_ID{label}                       Fscale{label}",
                    f"{_i(fid)}{b10}{_f(0.0)}"]
    if any(unloading) and all(loading):
        out += ["#  FCT_ID4   FCT_ID5             Fscale4             Fscale5"
                "   FCT_ID6             Fscale6",
                f"{_i(mat.lcua)}{_i(mat.lcub)}{_f(0.0)}{_f(0.0)}"
                f"{_i(mat.lcuab)}{_f(0.0)}"]
    return out


def _make_fabric_materials(state: ConversionState) -> List[str]:
    """Every ``*MAT_FABRIC`` → its /MAT/LAW19 or /MAT/LAW58 card, preceded by
    the /SENSOR/TIME any reference-geometry birth time needs.

    The sensor is the LS-DYNA birth-time equivalent: ``SENS_ID`` on the law is
    ``MATPARAM%IPARAM(1)``, the reference-state activation sensor, and
    ``/SENSOR/TIME``'s ``Tdelay`` is when it fires. Emitted here rather than
    with the loads so that a fabric material and the sensor it names stay in
    one block; the starter resolves entities by id, not by order.
    """
    if not state.mat_fabric:
        return []
    from .loads import _emit_sensor_time      # local: loads imports mesh
    lines = ["#-  FABRIC MATERIALS (*MAT_FABRIC):", HDR]
    for _mid, mat in sorted(state.mat_fabric.items()):
        if mat.sensor_id:
            lines += _emit_sensor_time(
                mat.sensor_id, f"FABRIC_{mat.mid}_REF_BIRTH", mat.sensor_tdelay)
    for _mid, mat in sorted(state.mat_fabric.items()):
        lines += (_emit_mat_law58(mat) if mat.use_law58
                  else _emit_mat_law19(mat))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# /PROP/TYPE9 (SH_ORTH) and /PROP/TYPE16 (SH_FABR) for the fabric parts
# ─────────────────────────────────────────────────────────────────────────────

#: Radioss ``Ip`` (reference-direction flag) written on every fabric property.
#:
#: 2 = "the reference direction is defined by the first two nodes of each
#: element, projected into the shell plane". A CLOSED airbag has no single
#: global direction that is non-normal to every one of its shells, and a
#: Vx/Vy/Vz that IS nearly normal to one is starter ``ERROR 197`` —
#: "REFERENCE DIRECTION IS ALMOST NORMAL TO SHELL ID=%d", raised ONCE PER
#: ELEMENT, so a bag of 5000 shells produces 5000 errors. Ip=2 is per element
#: and cannot be normal to its own shell by construction. AOPT 2/3 (an explicit
#: A or V vector) is honoured instead where the deck states one — see
#: ``_fabric_ref_axis``.
_FABRIC_IP_ELEMENT_NODES = 2


def _fabric_ref_axis(state: ConversionState, pid: int,
                     mat: MatFabric) -> Tuple[Tuple[float, float, float],
                                              float, int]:
    """``((Vx, Vy, Vz), Phi, Ip)`` for one fabric part, from the material AOPT.

    AOPT semantics (Vol II R16 p.2-317): 0 = local axis from element nodes 1,2,4
    plus BETA; 2 = the global vector A1/A2/A3; 3 = rotate the projection of V
    about the element normal by BETA; < 0 = a *DEFINE_COORDINATE_* id.

      * ``AOPT 0`` → ``Ip = 2`` (element-node reference direction) + ``Phi =
        BETA``. Exactly LS-DYNA's meaning and immune to ERROR 197.
      * ``AOPT 2`` → the A vector in Vx/Vy/Vz with ``Ip = 0``, ``Phi = BETA``.
      * ``AOPT 3`` → the V vector, ``Ip = 0``, ``Phi = BETA + 90`` — AOPT 3
        measures the angle from ``v x n``, i.e. from the perpendicular of the
        projection, which is a quarter turn from Radioss's Phi datum
        (dyna2rad applies the same +90, convertprops.cxx:1794).
      * ``AOPT < 0`` → warn and fall back to ``Ip = 2``; a
        *DEFINE_COORDINATE_* reference would need a synthesized /SKEW that
        this batch does not build.
    """
    aopt = int(round(mat.aopt))
    beta = mat.beta
    if aopt == 2 and (mat.a1 or mat.a2 or mat.a3):
        return (mat.a1, mat.a2, mat.a3), beta, 0
    if aopt == 3 and (mat.v1 or mat.v2 or mat.v3):
        return (mat.v1, mat.v2, mat.v3), beta + 90.0, 0
    if aopt < 0:
        state.warn(
            f"*MAT_FABRIC {mat.mid} on part {pid}: AOPT={mat.aopt:g} names a "
            "*DEFINE_COORDINATE_* system for the yarn directions. This batch "
            "does not synthesize the /SKEW that would carry it, so the "
            "property falls back to Ip=2 (the reference direction taken from "
            "each element's first two nodes) with Phi=BETA. That is the mesh's "
            "own direction, not the coordinate system's — check the warp "
            "orientation if the fabric is strongly orthotropic.")
    elif aopt == 2 or aopt == 3:
        state.warn(
            f"*MAT_FABRIC {mat.mid} on part {pid}: AOPT={mat.aopt:g} asks for a "
            "vector-defined yarn direction but the vector "
            f"({'A1/A2/A3' if aopt == 2 else 'V1/V2/V3'}) is all zero. The "
            "property falls back to Ip=2 (element-node reference direction) "
            "with Phi=BETA.")
    return (0.0, 0.0, 0.0), beta, _FABRIC_IP_ELEMENT_NODES


def _fabric_nip(sec: Optional[SectionShell]) -> int:
    """Through-thickness integration points / layers for a fabric property.

    dyna2rad collapses NIP to 1 for the membrane-family ELFORMs 2/5/9/16 and
    defaults a blank NIP to 2 (``convertprops.cxx:1710-1717``). k2rad keeps the
    deck's NIP where it states one, and only applies the collapse for the pure
    MEMBRANE formulation ELFORM=9: a membrane carries no bending, so its
    through-thickness points are all identical and integrating five of them
    costs five times the work for the same answer. ELFORM 2/5/16 are ordinary
    shells whose NIP is real, and quietly reducing them to one point would
    remove the bending stiffness the deck asked for.
    """
    if sec is None:
        return 1
    if sec.elform == 9:
        return 1
    return sec.nip if sec.nip > 0 else 2


def _emit_prop_type16(prop_id: int, title: str, sec: Optional[SectionShell],
                      nlayer: int, thick: float, mat_id: int,
                      is_implicit: bool, istrain: int, state: ConversionState,
                      refvec=(0.0, 0.0, 0.0), phi: float = 0.0,
                      ip: int = 2, dm: float = 0.0) -> List[str]:
    """/PROP/TYPE16 (SH_FABR) — the layered ANISOTROPIC shell property.

    Column layout from ``PROP/prop_p16_sh_fabr.cfg FORMAT(radioss2022)``, the
    newest block overall, reader ``properties/shell/hm_read_prop16.F``::

        /PROP/TYPE16/<id>
        <title, 100>
        Ishell(10) Ismstr(10) Ish3n(10) <30 blank> P_Thick_Fail(20)
        Hm(20) Hf(20) Hr(20) Dm(20) Dn(20)
        N(10) Istrain(10) Thick(20) Ashear(20) <10 blank> Ithick(10)
        Vx(20) Vy(20) Vz(20) Skew_ID(10) Ipos(10) <10 blank> Ip(10)
        [ Phi_i(20) Alpha_i(20) T_i(20) Z_i(20) mat_IDi(10) ] x N

    Note ``Ipos`` IS present at columns 71-80 on TYPE16 at /BEGIN 2022 — unlike
    ``/PROP/TYPE9``, whose card-4 columns 81-90 hold nothing at 2022 and become
    ``Ipos`` only from radioss2024, silently. It is written as 0 here.

    ``Alpha_i`` (columns 21-40 of each layer card) is the fabric-specific
    column: the angle between the layer's axis 1 and axis 2, i.e. the WEAVE
    angle. 90 degrees is an orthogonal weave, which is what *MAT_FABRIC's
    orthotropic constants describe, so 90 is written.

    The layer thicknesses are made to SUM to ``Thick``: the property
    renormalizes them otherwise and reports ``WARNING ID 29`` (SHELL THICKNESS
    DISCREPANCY WITH SUM OF LAYER THICKNESSES IS %d PERCENT).
    """
    ishell = _elform_to_ishell(sec.elform, is_implicit,
                              state.options.shell_default_ishell) if sec else 24
    vx, vy, vz = refvec
    b10, b30 = " " * 10, " " * 30
    n = max(1, nlayer)
    t_layer = thick / n
    # Layer z positions: mid-plane of each equal-thickness layer, bottom to top.
    lines = [
        f"/PROP/TYPE16/{prop_id}",
        title,
        "#   Ishell    Ismstr     Ish3n                                      P_Thick_Fail",
        f"{_i(ishell)}{_i(4)}{_i(2)}{b30}{_f(0.0)}",
        "#                 Hm                  Hf                  Hr"
        "                  Dm                  Dn",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(dm)}{_f(0.0)}",
        "#        N   Istrain               Thick              Ashear              Ithick",
        f"{_i(n)}{_i(istrain)}{_f(thick)}{_f(0.0)}{b10}{_i(0)}",
        "#                 Vx                  Vy                  Vz   Skew_ID      Ipos                  Ip",
        f"{_f(vx)}{_f(vy)}{_f(vz)}{_i(0)}{_i(0)}{b10}{_i(ip)}",
        "#              Phi_i             Alpha_i                 T_i"
        "                 Z_i   mat_IDi",
    ]
    for k in range(n):
        z = -thick / 2.0 + (k + 0.5) * t_layer
        lines.append(f"{_f(phi)}{_f(90.0)}{_f(t_layer)}{_f(z)}{_i(mat_id)}")
    lines.append(HDR)
    return lines


def _emit_prop_type9_fabric(prop_id: int, title: str,
                            sec: Optional[SectionShell], nip: int,
                            thick: float, is_implicit: bool, istrain: int,
                            state: ConversionState,
                            refvec=(0.0, 0.0, 0.0), phi: float = 0.0,
                            ip: int = 2, dm: float = 0.0) -> List[str]:
    """/PROP/TYPE9 (SH_ORTH) for a /MAT/LAW19 fabric part.

    ``mesh._emit_prop_type9`` cannot be reused verbatim: it hard-codes
    ``Ismstr = 0``, ``Ish3n = 0``, ``Ip = 0`` and ``Dm = 0`` in its literal card
    strings, and every one of those is load-bearing for fabric —

      * ``Ismstr = 4`` (full geometric non-linearity, large strain) is what a
        membrane that deploys from a folded state needs; at small strain the
        fabric would carry the fold as stiffness. dyna2rad sets 4 as well
        (``convertprops.cxx:1834``).
      * ``Ish3n = 2`` gives the standard 3-node shell formulation, so a bag
        meshed with triangles behaves like the quads beside it.
      * ``Ip = 2`` takes the reference direction from each element's own nodes;
        a global Vx/Vy/Vz that happens to be normal to any shell of a CLOSED
        bag is ``ERROR 197`` once per element.
      * ``Dm`` carries the card-2 DAMP, which is where *MAT_FABRIC's Rayleigh
        damping has to go — Radioss has no damping field on LAW19.

    Column layout is the same ``PROP/prop_p9_sh_orth.cfg FORMAT(radioss2022)``
    block ``_emit_prop_type9`` documents. Card-4 columns 81-90 are left BLANK:
    at /BEGIN 2022 the format has no cell there, and at 2024+ the very same
    columns become ``Ipos`` with no warning either way, so writing anything
    there is a silent version-dependent change of meaning. ``Ip`` is at columns
    91-100 at every version.
    """
    ishell = _elform_to_ishell(sec.elform, is_implicit,
                              state.options.shell_default_ishell) if sec else 24
    vx, vy, vz = refvec
    b10, b20 = " " * 10, " " * 20
    return [
        f"/PROP/TYPE9/{prop_id}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill                            P_Thick_Fail",
        f"{_i(ishell)}{_i(4)}{_i(2)}{_i(0)}{b20}{_f(0.0)}",
        "#                 Hm                  Hf                  Hr"
        "                  Dm                  Dn",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(dm)}{_f(0.0)}",
        "#        N   ISTRAIN               Thick              Ashear     Iskew    ITHICK     IPLAS",
        f"{_i(nip)}{_i(istrain)}{_f(thick)}{_f(0.0)}{_i(0)}{_i(0)}{_i(0)}",
        "#                 Vx                  Vy                  Vz                 Phi                  Ip",
        f"{_f(vx)}{_f(vy)}{_f(vz)}{_f(phi)}{b10}{_i(ip)}",
        HDR,
    ]


def _emit_fabric_props(state: ConversionState) -> List[str]:
    """The synthesized /PROP/TYPE9 and /PROP/TYPE16 cards, one per fabric part.

    ``Istrain = 1`` on every one of them, and that is not cosmetic: the
    reference-state initial-strain pass is gated on it —
    ``elements/shell/coque/cinit3.F:529`` reads ``IF (ISTRAIN == 1 .AND. NXREF >
    0) CALL CEPSINI(...)``, and ``CEPSINI``'s ``CMLAWI`` dispatch is what routes
    ILAW 19 to ``CM19INI`` and ILAW 58 to ``CM58_REFSTA``. With Istrain 0 an
    emitted /XREF or /EREF on the bag would be read by the starter, echoed, and
    then do nothing.
    """
    if not state.fabric_prop_ids:
        return []
    lines = ["#-  FABRIC PROPERTIES (*MAT_FABRIC parts):", HDR]
    for pid, prop_id in sorted(state.fabric_prop_ids.items()):
        part = state.parts[pid]
        mat = state.mat_fabric[part.mid]
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_shells.get(secid)
        thick = sec.t1 if sec is not None and sec.t1 > 0 else 0.0
        if thick <= 0.0:
            state.warn(
                f"*MAT_FABRIC part {pid}: its *SECTION_SHELL ({secid}) states "
                f"no positive thickness (T1={thick:g}), so the synthesized "
                f"fabric property carries Thick={thick:g}. The starter rejects "
                "a non-positive shell thickness — set T1 on the section.")
        refvec, phi, ip = _fabric_ref_axis(state, pid, mat)
        title = f"FABRIC_PART_{pid}"
        nip = _fabric_nip(sec)
        if mat.use_law58:
            lines += _emit_prop_type16(
                prop_id, title, sec, nip, thick, mat.mid,
                state.is_implicit, 1, state, refvec=refvec, phi=phi, ip=ip,
                # dyna2rad hard-codes Dm=0.05 on its TYPE16 and IGNORES the
                # card's DAMP (convertprops.cxx:3362). The deck's own value is
                # used here instead: 0.05 is the LS-DYNA manual's RECOMMENDED
                # DAMP, not a conversion constant, and overriding a stated 0.0
                # with it would add damping the deck did not ask for.
                dm=mat.damp)
        else:
            lines += _emit_prop_type9_fabric(
                prop_id, title, sec, nip, thick, state.is_implicit, 1, state,
                refvec=refvec, phi=phi, ip=ip, dm=mat.damp)
    return lines
