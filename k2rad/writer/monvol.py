"""
k2rad.writer.monvol  –  *AIRBAG_<MODEL> → /MONVOL (monitored volumes).

  *AIRBAG_SIMPLE_PRESSURE_VOLUME  → /MONVOL/PRES     (ITYPE 2)
  *AIRBAG_SIMPLE_AIRBAG_MODEL     → /MONVOL/AIRBAG1  (ITYPE 7) + /MAT/GAS
                                    + /PROP/INJECT1 [+ one vent hole]
  *AIRBAG_ADIABATIC_GAS_MODEL     → /MONVOL/GAS      (ITYPE 3)
  *AIRBAG_LOAD_CURVE              → /MONVOL/PRES     (Itypfun = 1)
  *AIRBAG_LINEAR_FLUID            → /MONVOL/LFLUID   (ITYPE 10)

THE SURFACE IS THE WHOLE PROBLEM, and it has one hard rule: **the external
surface must be element-backed.** ``check_surf.F:55-62`` sets
``IGRSURF%ISH4N3N`` only for ELTYP 3 (4-node shell) and 7 (SH3N), a
``/SURF/SEG`` never resolves back to an element at all (``tsurftag.F:293``
passes ``0, 0``), and every ``hm_read_monvol_type*.F`` then answers

    ERROR ID :     18   -- SURFACE ID: %d IS NOT DEFINED WITH SHELLS
    ERROR ID :     54   ** ERROR IN INPUT FORMAT

and aborts (starter exit 172, measured). An LS-DYNA ``SIDTYP=0`` airbag names
a *SET_SEGMENT — the COMMON case — so the segments are resolved back to their
OWNING SHELL ELEMENTS and the surface is built out of those, never out of the
segments.

ORIENTATION IS THE STARTER'S JOB, and this module deliberately does not do it.
Every MONVOL reader runs the same three helpers, in this order::

    CALL MONVOL_CHECK_SURFCLOSE(...)      ! find free edges, triangulate holes
    CALL MONVOL_ORIENT_SURF(..., ITYPE)   ! all normals onto the same side
    CALL MONVOL_COMPUTE_VOLUME(...)
    CALL MONVOL_REVERSE_NORMALS(..., VOL) ! IF (VOL < ZERO) flip everything

``MONVOL_ORIENT_SURF`` (``monvol_struct_mod.F:1111``) rewrites ``SURF%NODES``
in place — SHELL swaps 2<->4, SH3N swaps 1<->2 — and ``MONVOL_REVERSE_NORMALS``
(``:1782``) flips the lot when the signed volume comes out negative. So an
inward-wound bag is corrected automatically, and a converter-side flip would
be a second correction of an already-correct surface. What k2rad does instead
is MEASURE and report: the same signed volume the engine computes
(``get_volume_area.F90:156-169``), the free-edge count and the non-manifold
edge count, warned when any of them says the bag is not a closed manifold. The
two starter failure modes those predict are ``WARNING 1875`` (UNABLE TO CLOSE
EXTERNAL SURFACE) and ``WARNING 1882`` (T-CONNECTIONS CANNOT BE ORIENTED).
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from ..state import Airbag, ConversionState
from .common import (
    HDR, _emit_grsh3n, _emit_grshel, _emit_surf_grsh3n, _emit_surf_grshel,
    _emit_surf_surf, _f, _i, _split_shell_eids_by_topology,
)

__all__ = [
    "_resolve_airbags",
    "_make_monvols",
    "_surface_volume_and_edges",
    "_emit_monvol_pres",
    "_emit_monvol_gas",
    "_emit_monvol_airbag1",
    "_emit_monvol_lfluid",
    "_emit_mat_gas_csta",
    "_emit_mat_gas_mass",
    "_emit_prop_inject1",
]

#: Radioss ``/MONVOL/PRES`` ``Itypfun`` — what the pressure function's ABSCISSA
#: is. From the engine, ``engine/source/airbag/volpfv.F:61-88``, and echoed
#: verbatim by the reader (``hm_read_monvol_type2.F`` FORMAT 1200):
#:   0 : P = F(1/V)   XFUN = (V0-Vinc)/(VOL-Vinc)   -> the COMPRESSION ratio
#:   1 : P = F(T)     XFUN = TT
#:   2 : P = F(V)     XFUN = (VOL-Vinc)/(V0-Vinc)   -> the RELATIVE volume
#:   3 : P = (1/V)F(T)  XFUN = TT, result * (V0-Vinc)/(VOL-Vinc)
ITYPFUN_INV_VOLUME = 0
ITYPFUN_TIME = 1
ITYPFUN_REL_VOLUME = 2
ITYPFUN_TIME_OVER_VOLUME = 3

#: ``/PROP/INJECT1`` ``Iflow``. **1, always.**
#:
#: ``airbaga1.F:349-362`` reads the injector's mass function with
#: ``IFLU = IGEO(24, I_INJ)``::
#:
#:     GMASS = HALF * FMASS * (FINTER(...TSG...) + FINTER(...TSG2...))
#:     IF (IFLU == 1) GMASS = GMASS*DT1 + GMASS_OLD
#:     DGMASS = MAX(ZERO, GMASS - GMASS_OLD)
#:
#: so ``Iflow = 0`` means the curve IS the accumulated injected mass m(t) and
#: the engine DIFFERENCES it, while ``Iflow = 1`` means it is the rate dm/dt
#: and the engine INTEGRATES it. LS-DYNA's LCID is a rate — "Load curve ID
#: specifying input mass flow rate" (Vol I R16 p.3-13) and Remark 2, "The
#: inflow mass flow rate is given by the load curve ID, LCID". Leaving Iflow at
#: 0 therefore differentiates a rate curve: a silent error of order 1/dt with
#: no starter diagnostic at all.
INJECT1_IFLOW_MASS_RATE = 1


# ─────────────────────────────────────────────────────────────────────────────
# The surface
# ─────────────────────────────────────────────────────────────────────────────

def _shell_by_corner_nodes(state: ConversionState) -> Dict[frozenset, int]:
    """``{frozenset(corner nodes): eid}`` over every shell element.

    The map a ``*SET_SEGMENT`` airbag surface is resolved through: a segment is
    a face of exactly one shell, and its corner-node SET identifies that shell
    regardless of which corner the segment starts at or which way it winds.
    Both are free variables in LS-DYNA — the segment normal is the load side
    for a *LOAD_SEGMENT, but a monitored volume's surface is oriented by the
    starter, so the winding carries no information here.
    """
    out: Dict[frozenset, int] = {}
    for e in state.shell_elems:
        key = frozenset(n for n in e.nodes if n > 0)
        if len(key) >= 3:
            out.setdefault(key, e.eid)
    return out


def _airbag_surface_eids(state: ConversionState, ab: Airbag) -> List[int]:
    """The shell element ids of one airbag's external surface.

    SIDTYP == 0 → a *SET_SEGMENT, resolved to the owning shells (see above).
    SIDTYP != 0 → a *SET_PART (already flattened past *SET_PART_ADD by
    ``_flatten_part_set_adds``); a bare *PART id is accepted as well, with a
    warning, because a deck that writes one is common enough and the intent is
    never in doubt.
    """
    kw = f"*{ab.keyword}"
    ref = f"{kw} (SID {ab.sid})"
    segset = state.segment_sets.get(ab.sid)
    partset = state.part_sets.get(ab.sid)
    # LS-DYNA's set-id namespaces are PER FAMILY, so id 11 can be a
    # *SET_SEGMENT, a *SET_PART and a *SET_NODE at once and SIDTYP is the only
    # thing that says which one an airbag means. When the named family has no
    # set with that id but the OTHER one does, the deck's SIDTYP is simply
    # wrong — measured on the r14 corpus deck
    # introduction/intro-by-a.-tabiei/misc/airbag-i/volume.k, which writes
    # SIDTYP=0 and then defines *SET_PART_LIST 11 and *SET_NODE_LIST 11 and no
    # segment set at all. Falling back is the difference between converting
    # that bag and dropping it, and the mismatch is named either way.
    if ab.sidtyp == 0 and segset is None and partset is not None:
        state.warn(
            f"{ref}: SIDTYP=0 says the set is a *SET_SEGMENT, but this deck "
            f"defines no segment set {ab.sid} — it defines a *SET_PART with "
            "that id. LS-DYNA's set-id namespaces are per family, so the two "
            "can coexist and only SIDTYP distinguishes them; the PART set is "
            "used here. Set SIDTYP to 1 to say so explicitly.")
        segset = None
    elif ab.sidtyp != 0 and partset is None and segset is not None:
        state.warn(
            f"{ref}: SIDTYP={ab.sidtyp} says the set is a *SET_PART, but this "
            f"deck defines no part set {ab.sid} — it defines a *SET_SEGMENT "
            "with that id. The SEGMENT set is used here (resolved to its "
            "owning shells). Set SIDTYP to 0 to say so explicitly.")
        partset = None
    elif ab.sidtyp == 0 and segset is None:
        state.warn(
            f"{ref}: SIDTYP=0 names a *SET_SEGMENT that this deck does not "
            "define, so the monitored volume has NO surface and is "
            "dropped. Note LS-DYNA's SIDTYP is inverted from the "
            "intuitive reading — 0 is a SEGMENT set and non-zero is a PART "
            "set — so check which kind SID really is.")
        return []

    if segset is not None and (ab.sidtyp == 0 or partset is None):
        by_nodes = _shell_by_corner_nodes(state)
        eids: List[int] = []
        missed = 0
        for seg in segset.segments:
            key = frozenset(n for n in seg if n > 0)
            eid = by_nodes.get(key)
            if eid is None:
                missed += 1
            else:
                eids.append(eid)
        if missed:
            state.warn(
                f"{ref}: {missed} of {len(segset.segments)} segment(s) in the "
                "*SET_SEGMENT match no SHELL element, so they are LEFT OUT of "
                "the monitored volume's surface. A /MONVOL surface has to be "
                "element-backed — a /SURF/SEG is starter ERROR 18 (\"SURFACE "
                "ID IS NOT DEFINED WITH SHELLS\") plus ERROR 54 and the run "
                "aborts — so segments on solid faces or on nothing at all "
                "cannot be carried. The bag's volume will be short by their "
                "area; re-mesh the bag as shells if they were load-bearing.")
        return sorted(set(eids))
    pids = list(partset[1]) if partset is not None else None
    if pids is None:
        if ab.sid in state.parts:
            state.warn(
                f"{ref}: SIDTYP={ab.sidtyp} means a *SET_PART id, but {ab.sid} "
                "is a *PART id and there is no *SET_PART with that id. The "
                "single part is used as the surface scope; give the airbag a "
                "*SET_PART_LIST if more parts belong to the bag.")
            pids = [ab.sid]
        else:
            state.warn(
                f"{ref}: SIDTYP={ab.sidtyp} names a *SET_PART that this deck "
                "does not define (and no *PART has that id either), so the "
                "monitored volume has NO surface and is dropped.")
            return []
    pid_set = set(pids)
    eids = sorted(e.eid for e in state.shell_elems if e.pid in pid_set)
    empty = sorted(p for p in pid_set
                   if not any(e.pid == p for e in state.shell_elems))
    if empty:
        solid = sorted(p for p in empty
                       if any(e.pid == p for e in state.solid_elems)
                       or any(e.pid == p for e in state.tshell_elems))
        state.warn(
            f"{ref}: part(s) {empty} in the airbag's *SET_PART carry NO SHELL "
            "elements, so they contribute nothing to the monitored volume's "
            "surface"
            + (f" — {solid} hold SOLID/thick-shell elements, and a /MONVOL "
               "surface built over those is starter ERROR 18 (\"SURFACE ID IS "
               "NOT DEFINED WITH SHELLS\"), which aborts the run. They are "
               "left out rather than emitted."
               if solid else
               ". Check the part set: an empty part is usually a PID typo."))
    return eids


def _surface_volume_and_edges(state: ConversionState, eids: List[int]):
    """``(volume, n_free_edges, n_nonmanifold_edges, n_segments)`` of a shell
    surface — the CONVERSION-TIME check on a bag the starter will orient.

    The volume is the engine's own formula, ``get_volume_area.F90:156-169``::

        normal(:,i) = half * (x13 x x24)
        f2(i)       = third * (normal(:,i) . x_centroid)
        VOL         = sum(f2)

    i.e. the divergence-theorem sum ``V = (1/3) * integral(x . n dA)``, with the
    same ``N1N3 x N2N4`` area vector /PLOAD uses. A 3-node shell is the
    degenerate quad ``n1 n2 n3 n3``, for which ``half*(x13 x x24)`` reduces
    exactly to the triangle's own area vector ``half*((x2-x1) x (x3-x1))``.

    The sign is INFORMATION, not a fault: ``MONVOL_REVERSE_NORMALS`` flips the
    whole surface when the volume comes out negative, so an inward-wound bag is
    corrected by the starter. What a NEAR-ZERO volume means is different — the
    segments cancel each other, i.e. the winding is MIXED and there is nothing
    consistent to flip — and that is what ``MONVOL_ORIENT_SURF`` exists to fix,
    unless the surface has T-connections (``WARNING 1882``).

    An edge used by exactly one segment is a FREE edge: the bag is open there.
    The starter triangulates such holes and only warns (``WARNING 1875``) when
    it cannot close them; an edge used by more than two is non-manifold, which
    is the T-connection case that defeats the orientation pass outright.
    """
    nodes = state.nodes
    shells = {e.eid: e for e in state.shell_elems}
    vol = 0.0
    edge_use: Dict[Tuple[int, int], int] = {}
    nseg = 0
    for eid in eids:
        e = shells.get(eid)
        if e is None:
            continue
        corners: List[int] = []
        for n in e.nodes:
            if n > 0 and n not in corners:
                corners.append(n)
        if len(corners) < 3 or any(n not in nodes for n in corners):
            continue
        nseg += 1
        for k, a in enumerate(corners):
            b = corners[(k + 1) % len(corners)]
            key = (a, b) if a < b else (b, a)
            edge_use[key] = edge_use.get(key, 0) + 1
        quad = corners if len(corners) == 4 else [corners[0], corners[1],
                                                  corners[2], corners[2]]
        p = [(nodes[n].x, nodes[n].y, nodes[n].z) for n in quad]
        x13 = (p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2])
        x24 = (p[3][0] - p[1][0], p[3][1] - p[1][1], p[3][2] - p[1][2])
        nx = 0.5 * (x13[1] * x24[2] - x13[2] * x24[1])
        ny = 0.5 * (x13[2] * x24[0] - x13[0] * x24[2])
        nz = 0.5 * (x13[0] * x24[1] - x13[1] * x24[0])
        m = len(corners)
        cx = sum(q[0] for q in p[:m]) / m
        cy = sum(q[1] for q in p[:m]) / m
        cz = sum(q[2] for q in p[:m]) / m
        vol += (nx * cx + ny * cy + nz * cz) / 3.0
    free = sum(1 for v in edge_use.values() if v == 1)
    nonman = sum(1 for v in edge_use.values() if v > 2)
    return vol, free, nonman, nseg


def _warn_surface_quality(state: ConversionState, ab: Airbag,
                          eids: List[int]) -> None:
    """Report what the starter is about to find in this bag's surface."""
    vol, free, nonman, nseg = _surface_volume_and_edges(state, eids)
    ref = f"*{ab.keyword} (SID {ab.sid})"
    if free:
        state.warn(
            f"{ref}: the monitored volume's surface is NOT CLOSED — {free} "
            f"free edge(s) over {nseg} segment(s). The starter attempts an "
            "automatic closure (MONVOL_CHECK_SURFCLOSE triangulates each hole) "
            "and reports WARNING 1875 \"UNABLE TO CLOSE EXTERNAL SURFACE\" only "
            "if it cannot; the run continues either way, on whatever volume "
            "the closure produced. Check that the bag is a closed shell if the "
            "pressure matters.")
    if nonman:
        state.warn(
            f"{ref}: {nonman} edge(s) of the monitored volume's surface are "
            "shared by MORE THAN TWO segments (T-connections). "
            "MONVOL_ORIENT_SURF cannot orient such a surface — it gives up "
            "with WARNING 1882 and MONVOL_REVERSE_NORMALS then returns "
            "immediately, so the normals stay as written and the volume can "
            "come out negative or wrong. Split the bag from whatever else "
            "shares those edges.")
    if nseg and abs(vol) < 1e-12:
        state.warn(
            f"{ref}: the monitored volume's initial volume computes to "
            f"{vol:g} over {nseg} segment(s) — effectively ZERO, which means "
            "the segment normals CANCEL, i.e. the surface is not consistently "
            "wound (a doubled-over or self-overlapping bag). The starter's "
            "orientation pass may recover it; if it does not, the pressure "
            "law divides by a zero volume. Check the mesh.")
    elif nseg:
        state.warn(
            f"{ref}: monitored-volume surface checked — {nseg} shell segment(s)"
            f", initial volume {abs(vol):.6g}"
            + (", wound INWARD (the signed volume is negative). No node order "
               "is changed: the starter's MONVOL_REVERSE_NORMALS flips the "
               "whole surface when the volume comes out negative, so a second "
               "flip here would undo the correct one."
               if vol < 0 else ", wound outward."))


# ─────────────────────────────────────────────────────────────────────────────
# The prepass
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_airbags(state: ConversionState) -> None:
    """build_starter prepass: resolve every ``*AIRBAG_*`` to its surface, its
    ids and its synthesized curves.

    Runs after the element lists are final (the surface is built from shells)
    and after ``_flatten_part_set_adds`` (a *SET_PART_ADD scope), and BEFORE
    ``_make_functions`` — the SPV unit-slope function, the injector's
    constant-temperature function and the LFLUID pressure cap are real
    ``/FUNCT`` cards that pass through ``state.curves``.
    """
    if not state.airbags:
        return
    used_monvol_ids: Set[int] = set()
    for ab in state.airbags:
        eids = _airbag_surface_eids(state, ab)
        if not eids:
            ab.dropped = True
            state.warn(
                f"*{ab.keyword} (SID {ab.sid}): no shell element resolved for "
                "the monitored volume's surface, so NO /MONVOL is emitted. "
                "The bag does not inflate — the deck still runs, and it runs "
                "to termination, which is why this is worth reading.")
            continue
        _warn_surface_quality(state, ab, eids)
        ab.quad_eids, ab.tri_eids = _split_shell_eids_by_topology(state, eids)
        # /MONVOL ids share ONE Radioss namespace across PRES / AIRBAG1 / GAS /
        # LFLUID, while LS-DYNA's *AIRBAG_<MODEL>_ID ids are per keyword — so
        # a *AIRBAG_SIMPLE_PRESSURE_VOLUME_ID 5 and a *AIRBAG_LOAD_CURVE_ID 5
        # are both legal and both want id 5. dyna2rad's second CreateEntity
        # then fails its IsValid() guard and the airbag VANISHES with no
        # message (convertcontrolvols.cxx:85). Renumbered here instead.
        mid = ab.airbag_id
        if mid <= 0 or mid in used_monvol_ids:
            if mid > 0:
                state.warn(
                    f"*{ab.keyword}: airbag id {mid} is already used by "
                    "another *AIRBAG_* card. The /MONVOL id namespace is "
                    "shared across PRES/AIRBAG1/GAS/LFLUID while LS-DYNA's is "
                    "per keyword, so this monitored volume is RENUMBERED. "
                    "(dyna2rad drops the second bag silently.)")
            mid = state.next_id()
        used_monvol_ids.add(mid)
        ab.monvol_id = mid
        ab.surf_id = state.next_id()
        _resolve_airbag_model(state, ab)
    if any(not a.dropped for a in state.airbags):
        _warn_shared_surfaces(state)


def _warn_shared_surfaces(state: ConversionState) -> None:
    """Two monitored volumes over the same parts/segments is legal and each
    gets its own surface — but the two bags then measure the SAME cavity."""
    seen: Dict[Tuple[int, int], List[int]] = {}
    for ab in state.airbags:
        if not ab.dropped:
            seen.setdefault((ab.sid, 1 if ab.sidtyp else 0),
                            []).append(ab.monvol_id)
    for (sid, styp), ids in sorted(seen.items()):
        if len(ids) > 1:
            state.warn(
                f"/MONVOL {ids} all take their external surface from the same "
                f"LS-DYNA set {sid} ({'part' if styp else 'segment'} set). "
                "Each gets its own /SURF, and the starter orients, closes and "
                "measures each independently — but they describe ONE cavity, "
                "so their pressures are applied to the same shells and ADD. "
                "That is what LS-DYNA does too; check it is intended.")


def _resolve_airbag_model(state: ConversionState, ab: Airbag) -> None:
    """Per-model id allocation and curve synthesis, plus the card-1 fields no
    Radioss monitored volume can express."""
    from .materials import _add_auto_curve
    kw = f"*{ab.keyword}"
    _warn_card1_extras(state, ab)
    if ab.model == "SIMPLE_PRESSURE_VOLUME":
        _resolve_spv(state, ab, _add_auto_curve)
    elif ab.model == "LOAD_CURVE":
        _resolve_load_curve(state, ab, _add_auto_curve)
    elif ab.model == "ADIABATIC_GAS_MODEL":
        _resolve_adiabatic_gas(state, ab)
    elif ab.model == "SIMPLE_AIRBAG_MODEL":
        _resolve_simple_airbag(state, ab, _add_auto_curve)
    elif ab.model == "LINEAR_FLUID":
        _resolve_linear_fluid(state, ab, _add_auto_curve)
    else:                                                # pragma: no cover
        state.warn(f"{kw}: unhandled airbag model {ab.model!r}.")


def _warn_card1_extras(state: ConversionState, ab: Airbag) -> None:
    """RBID / VSCA / PSCA / VINI / MWD / SPSF — the card-1 fields whose Radioss
    expression is partial or absent.

    The scaling contract (Vol I R16 p.3-4, verbatim): ``V_cvolume = (VSCA x
    V_femodel) - VINI`` and ``P_femodel = PSCA x P_cvolume``. So VSCA/PSCA are
    a UNIT BRIDGE between the FE model and the thermodynamics, and VINI is
    subtracted AFTER the volume scale — it is the Radioss ``Vinc``
    (incompressible volume) in model units, ``VINI / VSCA``. Only /MONVOL/GAS
    has a ``Vinc`` column, so on the other three models a non-zero VINI has to
    be reported.
    """
    kw = f"*{ab.keyword}"
    if ab.rbid:
        state.warn(
            f"{kw}: RBID={ab.rbid} arms the inflator from a "
            + ("USER activation subroutine" if ab.rbid > 0 else
               "built-in acceleration/velocity/displacement SENSOR")
            + " on a rigid body. That is DROPPED: the monitored volume is "
            "active from t=0 instead. Radioss expresses the same idea as a "
            "/SENSOR on the injector's sens_ID slot (/SENSOR/ACCE, /VEL or "
            "/DIST), which this batch does not synthesize — the bag will "
            "therefore start inflating earlier than in LS-DYNA.")
    if ab.vsca != 1.0 or ab.psca != 1.0:
        state.warn(
            f"{kw}: VSCA={ab.vsca:g} / PSCA={ab.psca:g} are a UNIT BRIDGE "
            "between the FE model and the control volume's own unit system "
            "(Vol I p.3-4: V_cvolume = VSCA*V_femodel - VINI, P_femodel = "
            "PSCA*P_cvolume). Radioss has no such pair"
            + (" — PSCA is folded into the /MONVOL pressure Fscale"
               if ab.model in ("SIMPLE_PRESSURE_VOLUME", "LOAD_CURVE")
               else " and PSCA is DROPPED")
            + ", and VSCA is DROPPED. On a PRES bag VSCA cancels out of the "
              "V0/V ratio exactly, so only a non-unit VSCA with a non-zero "
              "VINI actually loses anything; on the gas models it rescales "
              "the volume the state equation sees. Convert the deck to one "
              "consistent unit system if either is not 1.")
    if ab.vini != 0.0 and ab.model != "ADIABATIC_GAS_MODEL":
        state.warn(
            f"{kw}: VINI={ab.vini:g} is the INCOMPRESSIBLE volume (it is "
            "subtracted after the volume scale, Vol I p.3-4 — not an 'initial "
            "fill'). Radioss states it as Vinc, which exists on /MONVOL/GAS "
            "only, so on this model it is DROPPED and the bag's working volume "
            "is larger than LS-DYNA's by that amount.")
    if ab.mwd != 0.0:
        state.warn(
            f"{kw}: MWD={ab.mwd:g} (mass-weighted damping of the bag fabric) "
            "has no /MONVOL counterpart and is DROPPED. The nearest Radioss "
            "equivalent is a /DAMP on the bag part, or the Dm column of the "
            "fabric property (which carries *MAT_FABRIC's own DAMP).")
    if ab.spsf != 0.0:
        state.warn(
            f"{kw}: SPSF={ab.spsf:g} (stagnation-pressure scale factor) has no "
            "Radioss counterpart and is DROPPED.")


def _resolve_spv(state: ConversionState, ab: Airbag, add_curve) -> None:
    """``*AIRBAG_SIMPLE_PRESSURE_VOLUME`` → /MONVOL/PRES.

    LS-DYNA's law (Vol I R16 p.3-10) is::

        Pressure = BETA * CN / (Relative Volume),  Relative Volume = V / V0

    i.e. ``p = BETA*CN*V0/V``. Radioss ``Itypfun = 0`` feeds the function
    exactly ``V0/V`` (``volpfv.F``: ``XFUN = (V0-VINC)/(VOL-VINC)``), so the
    faithful emission is a UNIT-SLOPE function with ``Fscale = BETA*CN``:

        p = Fscale * f(V0/V) = BETA*CN * V0/V                       exact

    dyna2rad instead bakes ``BETA*CN*x`` into a 27-point table
    (``convertcontrolvols.cxx:117-128``) — which silently absorbs a factor V0
    and is right only when V0 == 1 in deck units.

    ``LCID`` wins over CN when given: it "defines pressure as a function of
    RELATIVE VOLUME", which is Radioss ``Itypfun = 2`` (``XFUN = V/V0``) with
    the curve referenced as-is. ``CN < 0`` means ``|CN|`` is a curve giving
    CN(t): that is ``Itypfun = 3`` (``P = (1/V) F(T)``), the one slot that
    multiplies a time function by V0/V.
    """
    kw = f"*{ab.keyword}"
    beta = ab.beta if ab.beta != 0.0 else 1.0
    if ab.lcid > 0:
        ab.fct_id = ab.lcid
        ab.itypfun = ITYPFUN_REL_VOLUME
        ab.fscale = 0.0 if ab.psca == 1.0 else ab.psca
        if ab.cn != 0.0 or ab.beta != 0.0:
            state.warn(
                f"{kw}: LCID={ab.lcid} is given, so LS-DYNA ignores CN and "
                f"BETA (\"Define if the load curve ID, LCID, is unspecified\"); "
                "they are ignored here too. The curve is referenced as "
                "pressure vs RELATIVE VOLUME (Radioss Itypfun=2, XFUN=V/V0), "
                "which is exactly LS-DYNA's abscissa.")
    elif ab.cn < 0.0:
        ab.fct_id = int(-ab.cn)
        ab.itypfun = ITYPFUN_TIME_OVER_VOLUME
        ab.fscale = beta * ab.psca
        state.warn(
            f"{kw}: CN={ab.cn:g} is negative, so |CN| is the curve giving "
            "CN(t). It is emitted as Radioss Itypfun=3 (\"P = (1/V) F(T)\"), "
            "which evaluates the curve at t and multiplies by V0/V — exactly "
            "LS-DYNA's p = BETA*CN(t)*V0/V, with BETA in Fscale.")
    else:
        fid = state.next_curve_id()
        # A UNIT-SLOPE function, so Fscale carries the whole physics. Two
        # points is exact for a straight line and OpenRadioss extrapolates
        # linearly on the END SLOPE, so f(x) = x for every x the engine can
        # ask for.
        add_curve(state, fid, f"MONVOL_{ab.monvol_id}_PRES_UNIT_SLOPE",
                  [(0.0, 0.0), (1.0, 1.0)])
        ab.fct_id = fid
        ab.itypfun = ITYPFUN_INV_VOLUME
        ab.fscale = beta * ab.cn * ab.psca
        if ab.cn == 0.0:
            state.warn(
                f"{kw}: CN=0 and no LCID, so the emitted /MONVOL/PRES applies "
                "ZERO pressure. Give CN and BETA, or an LCID.")
    if ab.lciddr:
        state.warn(
            f"{kw}: LCIDDR={ab.lciddr} (the dynamic-relaxation pressure ramp) "
            "is DROPPED — Radioss has no dynamic-relaxation phase for a "
            "monitored volume to ramp over. The bag is at full pressure from "
            "t=0.")


def _resolve_load_curve(state: ConversionState, ab: Airbag, add_curve) -> None:
    """``*AIRBAG_LOAD_CURVE`` → /MONVOL/PRES with ``Itypfun = 1`` (P = F(t)).

    ``STIME`` ("Time at which pressure is applied. LCID is offset by this
    amount") has no column on /MONVOL/PRES, so it is folded into a REBUILT
    curve: every abscissa is shifted by +STIME and a ``(0, 0)`` point is
    prepended when the shifted curve no longer covers t=0, so the pressure is
    exactly zero at the start of the run.

    dyna2rad prepends ``(-1, 0)`` instead (``convertcontrolvols.cxx:524-526``).
    That leaves a NON-ZERO pressure at t=0 for any STIME > 1 — the segment from
    (-1, 0) to (STIME, y0) is already well above zero by then — so the leading
    point is put at t=0 here.
    """
    kw = f"*{ab.keyword}"
    ab.itypfun = ITYPFUN_TIME
    ab.fscale = 0.0 if ab.psca == 1.0 else ab.psca
    if ab.lcid <= 0:
        state.warn(
            f"{kw}: LCID is 0, so LS-DYNA computes the pressure from the gas "
            "state (P = C*rho*(T - T0)) instead of from a curve. That branch "
            "has no /MONVOL/PRES expression — the card is a pressure FUNCTION "
            "and an absent fct_ID is starter ERROR 9 — so NO /MONVOL is "
            "emitted for this airbag. Re-state the bag as "
            "*AIRBAG_ADIABATIC_GAS_MODEL (which does carry RO/GAMMA/P0/PE) or "
            "give an LCID.")
        ab.dropped = True
        return
    curve = state.curves.get(ab.lcid)
    if curve is None or not curve.pts:
        state.warn(
            f"{kw}: LCID={ab.lcid} names a *DEFINE_CURVE this deck does not "
            "define (or one with no points). The /MONVOL/PRES still references "
            f"function {ab.lcid}; if it really is missing the starter answers "
            "ERROR 9 (UNDEFINED LOAD CURVE FOR PRESSURE) and refuses the deck.")
        ab.fct_id = ab.lcid
        return
    if ab.stime == 0.0:
        ab.fct_id = ab.lcid
        return
    pts = [(x + ab.stime, y) for x, y in curve.pts]
    if pts[0][0] > 0.0:
        pts.insert(0, (0.0, 0.0))
        if curve.pts[0][1] != 0.0:
            state.warn(
                f"{kw}: STIME={ab.stime:g} shifts the pressure curve, and its "
                f"first point is non-zero ({curve.pts[0][1]:g}). The rebuilt "
                "function gets a leading (0, 0) point so the pressure is zero "
                "at t=0, which means it RAMPS from 0 to that value over "
                "[0, STIME] rather than stepping at STIME as LS-DYNA does. A "
                "step would need a duplicate abscissa, which the engine's "
                "linear interpolation cannot represent cleanly.")
    fid = state.next_curve_id()
    add_curve(state, fid, f"MONVOL_{ab.monvol_id}_PRES_T_SHIFT", pts)
    ab.fct_id = fid
    if any(v != 0.0 for v in (ab.ro, ab.pe, ab.p0, ab.t, ab.t0)):
        state.warn(
            f"{kw}: RO/PE/P0/T/T0 are stated but LCID={ab.lcid} is given, and "
            "LS-DYNA itself ignores all five in that case (\"ignored if "
            "LCID > 0\"). They are dropped here for the same reason — this is "
            "parity, not a loss.")


def _resolve_adiabatic_gas(state: ConversionState, ab: Airbag) -> None:
    """``*AIRBAG_ADIABATIC_GAS_MODEL`` → /MONVOL/GAS.

    The gauge/absolute conversion is the whole of it. LS-DYNA (Vol I R16
    p.3-18) states ``p = (gamma-1) rho e`` with ``e_0 = (p_0 + p_e) /
    (rho (gamma-1))``, i.e. **P0 is a GAUGE pressure** and the initial
    ABSOLUTE pressure is ``P0 + PE``. Radioss feeds ``Pini`` straight into
    ``EI = PINI*(V+VEPS-VINC)/(GAMMA-1)`` and applies ``DP = Q + PRES - PEXT``,
    so ``Pini`` is absolute: **Pini = P0 + PE**.

    dyna2rad writes ``Pini = PSF*P0`` and adds no PE
    (``convertcontrolvols.cxx:395``), which under-pressurises the bag by PE —
    one atmosphere on any SI deck.
    """
    kw = f"*{ab.keyword}"
    if ab.gamma <= 0.0:
        state.warn(
            f"{kw}: GAMMA={ab.gamma:g} is not a usable ratio of specific "
            "heats. /MONVOL/GAS needs Gamma > 1 — the starter rejects exactly "
            "1.0 (ERROR 641) but NOT 0, and a 0 gives 1/(gamma-1) = -1, i.e. a "
            "negative internal energy. No /MONVOL is emitted; set GAMMA "
            "(1.4 for air).")
        ab.dropped = True
        return
    if ab.gamma == 1.0:
        state.warn(
            f"{kw}: GAMMA=1.0 is starter ERROR 641 (\"GAS CONSTANT GAMMA "
            "CANNOT BE EQUAL TO 1.0\") — the pressure law divides by "
            "gamma - 1. No /MONVOL is emitted.")
        ab.dropped = True
        return
    if ab.psf not in (0.0, 1.0):
        state.warn(
            f"{kw}: PSF={ab.psf:g} scales the APPLIED gauge pressure "
            "(p_s = PSF*(p - p_e), Vol I p.3-18). /MONVOL/GAS has no such "
            "factor — its pressure comes from the gas state alone — so PSF is "
            "DROPPED and the bag pushes with the unscaled gauge pressure. "
            "Rescale P0/PE, or use *AIRBAG_LOAD_CURVE with a pre-scaled curve, "
            "if PSF is load-bearing. (dyna2rad folds PSF into Pini instead, "
            "which scales the initial STATE rather than the applied force.)")
    if ab.lcid:
        state.warn(
            f"{kw}: LCID={ab.lcid} (the optional preload flag curve) is "
            "DROPPED — Radioss has no preload phase for a monitored volume. "
            "The bag is at its initial pressure from t=0. (A /MONVOL/GAS "
            "Trelax with I_equi=1 or 2 is the nearest mechanism, but it ramps "
            "from Pext to Pini rather than following a curve.)")
    if ab.ro == 0.0:
        state.warn(
            f"{kw}: RO=0, so /MONVOL/GAS Rhoi is 0 and the starter cannot "
            "compute the gas's Cv (RVOLU(19) is only formed when RHOI is "
            "non-zero). The pressure law still runs on Gamma and Pini; the "
            "temperature and heat-capacity channels of /TH/MONV will be "
            "meaningless. (dyna2rad drops RO unconditionally.)")


def _resolve_simple_airbag(state: ConversionState, ab: Airbag,
                           add_curve) -> None:
    """``*AIRBAG_SIMPLE_AIRBAG_MODEL`` → /MONVOL/AIRBAG1 + /MAT/GAS
    + /PROP/INJECT1 [+ one vent hole].

    **The Cp/Cv slot.** ``/MAT/GAS`` carries a MASS-SPECIFIC Cp polynomial in T
    and Radioss derives Cv itself — ``hm_read_monvol_type7.F``::

        CPI  = CPAI + CPBI*TI + CPCI*TI*TI + CPDI*TI**3 + CPEI/(TI*TI) + CPFI*TI**4
        RMWI = R_IGC1 / MWI
        CVI  = CPI - RMWI
        GAMAI = CPI / CVI

    LS-DYNA's own rule (Vol I R16 p.3-16 Remark 3) is the same split: with
    ``CV != 0`` the card's CV and CP are used directly (both mass-specific,
    J/kg/K) and with ``CV == 0`` they come from ``c_p = (a + bT)/MW`` — so
    card 4a's A and B are MOLAR and get divided by MW. Hence:

      CV != 0 → ``/MAT/GAS/CSTA`` with ``Cp | Cv`` verbatim
      CV == 0 → ``/MAT/GAS/MASS`` with ``MW``, ``Cpa = A/MW``, ``Cpb = B/MW``

    Writing LS-DYNA's CV into a Cp slot would invert the gas.

    **The injector.** ``fun_ID_M`` = LCID with ``Iflow = 1`` — see
    ``INJECT1_IFLOW_MASS_RATE``. ``fun_ID_T`` is a synthesized two-point
    constant at the card's T (Radioss wants the injected-gas temperature as a
    function of time, LS-DYNA states one number). ``Ascale_T`` is written as
    an explicit 1.0: it DIVIDES the time abscissa (``airbaga1.F:255``,
    ``TSG = (TT - TSTART)/ASTIME``) while the ``IFLU == 1`` integration
    multiplies by DT1 WITHOUT dividing, so the two disagree for any other
    value.
    """
    kw = f"*{ab.keyword}"
    ab.gas_mat_id = state.next_mat_id()
    if ab.cv != 0.0:
        ab.gas_mat_kind = "CSTA"
        if ab.cp <= 0.0 or ab.cv <= 0.0:
            state.warn(
                f"{kw}: /MAT/GAS/CSTA needs Cp > 0 and Cv > 0 (starter "
                f"ERROR 916); this card states CP={ab.cp:g}, CV={ab.cv:g}. The "
                "gas is emitted as written and the starter will refuse it — "
                "fix the card.")
        elif ab.cp <= ab.cv:
            state.warn(
                f"{kw}: /MAT/GAS/CSTA needs Cp > Cv (starter ERROR 917); this "
                f"card states CP={ab.cp:g} <= CV={ab.cv:g}, which is "
                "thermodynamically impossible (Cp - Cv = R/MW > 0). The gas is "
                "emitted as written and the starter will refuse it.")
    else:
        ab.gas_mat_kind = "MASS"
        if ab.mw <= 0.0:
            state.warn(
                f"{kw}: CV=0 selects the molar heat-capacity form "
                "(c_p = (A + B*T)/MW, Vol I p.3-16 Remark 3), but card 4a "
                f"states MW={ab.mw:g}. /MAT/GAS needs MW > 0 — it forms "
                "Cv = Cp - R/MW — so the starter will refuse the gas "
                "(ERROR 710). Give MW, or give CV and CP directly.")
        if ab.gasc not in (0.0,) and abs(ab.gasc - 8.314) > 0.5 * 8.314:
            state.warn(
                f"{kw}: GASC={ab.gasc:g} is the universal gas constant in the "
                "deck's units. Radioss uses its OWN R (PM(27) = 8.314, echoed "
                "as UNIVERSAL GAS CONSTANT) to form Cv = Cp - R/MW and has no "
                "column to override it, so a deck whose R is not ~8.314 is "
                "working in a unit system Radioss's /MAT/GAS does not share. "
                "Convert the deck to consistent SI-like units, or state CV and "
                "CP directly (the /MAT/GAS/CSTA path, which needs no R).")
    # Injector: N_gases = 1, Iflow = 1, the LS-DYNA LCID as fun_ID_M and a
    # 2-point constant-T curve as fun_ID_T.
    ab.inject_prop_id = state.next_prop_id()
    t_inj = ab.t
    tfid = state.next_curve_id()
    add_curve(state, tfid, f"MONVOL_{ab.monvol_id}_INJECT_T",
              [(0.0, t_inj), (1.0, t_inj)])
    ab.inject_temp_fct = tfid
    if ab.lcid <= 0:
        state.warn(
            f"{kw}: LCID is 0, so no mass-flow curve reaches the injector and "
            "the bag receives NO GAS at all — it stays at its initial mass "
            "and the /MONVOL/AIRBAG1 is inert. Give the inflator mass-flow "
            "curve.")
    if t_inj <= 0.0:
        state.warn(
            f"{kw}: T={t_inj:g} is the temperature of the INJECTED gas and "
            "Radioss needs it as an absolute temperature (it forms "
            "P = (sum m_k R/MW_k) T / V). A zero or negative value gives a "
            "zero-pressure bag; state T in Kelvin.")
    _resolve_airbag_vent(state, ab, add_curve)


def _resolve_airbag_vent(state: ConversionState, ab: Airbag,
                         add_curve) -> None:
    """MU / AREA / LOU → one whole-bag vent hole on /MONVOL/AIRBAG1.

    LS-DYNA (Vol I R16 p.3-15 Remark 2) offers two exclusive leak paths: the
    ``mu * A`` orifice, whose mass flow is the Wang-Nefske isentropic
    expression, or a ``LOU`` curve of mass-flow-out vs GAUGE pressure with "mu
    and A must both be set to zero".

    The orifice maps 1:1: a vent hole with ``surf_IDv = 0`` (whole-bag
    porosity, no named hole surface), ``Iform = 1`` (isenthalpic ~ Wang-Nefske)
    and ``Avent = mu*A``. A NEGATIVE MU or AREA is a curve of that quantity vs
    ABSOLUTE pressure, which becomes the vent's ``fct_IDP`` porosity function
    — and ``fct_IDP`` is a function of the GAUGE pressure ``P - Pext``, so the
    curve's abscissae are shifted by ``-PE``. That shift is the single most
    unit-sensitive number in this batch.
    """
    kw = f"*{ab.keyword}"
    mu_curve = int(-ab.mu) if ab.mu < 0.0 else 0
    area_curve = int(-ab.area) if ab.area < 0.0 else 0
    mu = ab.mu if ab.mu > 0.0 else 0.0
    area = ab.area if ab.area > 0.0 else 0.0

    if mu_curve and area_curve:
        state.warn(
            f"{kw}: BOTH MU and AREA are given as curves ({mu_curve} and "
            f"{area_curve}). A Radioss vent hole has ONE porosity-vs-pressure "
            f"function, so only the AREA curve {area_curve} is used and the "
            "shape-factor curve is DROPPED (Avent = 1). dyna2rad instead "
            "combines the two point-by-point, ADDING their abscissae and "
            "scaling the ordinate by the AREA curve's abscissa factor — two "
            "defects in four lines (convertcontrolvols.cxx:253-256). Fold the "
            "shape factor into the area curve if the product matters.")
        ab.avent = 1.0
        src = area_curve
    elif area_curve:
        ab.avent = mu if mu else 1.0
        src = area_curve
    elif mu_curve:
        ab.avent = area if area else 1.0
        src = mu_curve
    else:
        ab.avent = mu * area
        src = 0

    if src:
        curve = state.curves.get(src)
        if curve is None or not curve.pts:
            state.warn(
                f"{kw}: the vent curve {src} is not defined in this deck. The "
                "vent hole references it anyway; a missing porosity function "
                "is starter ERROR 332 and the deck is refused.")
            ab.vent_fct_p = src
        elif ab.pe != 0.0:
            fid = state.next_curve_id()
            add_curve(state, fid, f"MONVOL_{ab.monvol_id}_VENT_GAUGE",
                      [(x - ab.pe, y) for x, y in curve.pts])
            ab.vent_fct_p = fid
            state.warn(
                f"{kw}: the vent curve {src} is a function of ABSOLUTE "
                "pressure (LS-DYNA) while the Radioss vent's fct_IDP is a "
                f"function of the GAUGE pressure P - Pext. Curve {fid} is a "
                f"copy with every abscissa shifted by -PE = {-ab.pe:g}. Check "
                "that PE really is in the deck's pressure unit — this shift is "
                "the most unit-sensitive number in the conversion.")
        else:
            ab.vent_fct_p = src

    if ab.lou:
        if ab.avent == 0.0:
            state.warn(
                f"{kw}: LOU={ab.lou} gives the vent mass flow OUT as a "
                "function of the bag's gauge pressure. /MONVOL/AIRBAG1's vent "
                "holes take a POROSITY (an area fraction), not a mass flow, so "
                "the curve cannot be carried and the bag DOES NOT VENT — it "
                "will over-pressurise relative to LS-DYNA. The nearest Radioss "
                "expressions are a porous surface with Iformps=2 (Chemkin) or "
                "/MONVOL/GAS with a fct_IDP vent; both need the flow restated "
                "as an area or a velocity. dyna2rad divides LOU by the ambient "
                "density RO and feeds it to Iform=2/fct_IDvvh, which is a "
                "volumetric OUTFLOW VELOCITY — only valid when the ambient "
                "density it divides by is the density AT THE HOLE.")
        else:
            state.warn(
                f"{kw}: LOU={ab.lou} is given together with a non-zero MU*A. "
                "LS-DYNA requires \"mu and A must both be set to zero\" when "
                "LOU is used, so the deck states two exclusive leak paths. The "
                "MU*A orifice is converted and LOU is DROPPED.")
    if ab.avent == 0.0 and not ab.lou:
        state.warn(
            f"{kw}: MU*AREA is 0 and no LOU curve is given, so this bag has NO "
            "VENT at all — no vent-hole block is emitted. That matches the "
            "deck; a sealed bag inflates to a much higher pressure than a "
            "vented one, so check it is intended.")
    if ab.ro != 0.0:
        state.warn(
            f"{kw}: RO={ab.ro:g} (ambient density) has no /MONVOL/AIRBAG1 "
            "column and is DROPPED — the starter derives the bag's initial "
            "gas mass from the ideal-gas law itself "
            "(MI = Pext*(V+Veps)/(R/MW * T0)). The value is only used by "
            "LS-DYNA's own vent expression, which this conversion states as an "
            "orifice area instead.")


def _resolve_linear_fluid(state: ConversionState, ab: Airbag,
                          add_curve) -> None:
    """``*AIRBAG_LINEAR_FLUID`` → /MONVOL/LFLUID.

    A 1:1 map, and the engine agrees term for term with LS-DYNA
    (``volp_lfluid.F``: ``PRES = BULK*MAX(0, LOG(V0/V)) + P0``, clamped to
    ``PMAX``, vs Vol I R16 p.3-42 ``P(t) = K(t) ln[V0(t)/V(t)] + L(t)``) —
    except that Radioss clamps the logarithm at 0, so it applies no negative
    gauge pressure on expansion past V0.

    **The Pmax trap.** ``hm_read_monvol_type10.F`` overwrites the scale factor
    whenever no function is given::

        IF (IFPMAX > 0) THEN
           IF (SFPMAX == ZERO) SFPMAX = ONE * FAC_GEN
        ELSE
           SFPMAX = INFINITY * FAC_GEN

    Measured: ``fct_Pmax = 0`` with ``Fscale_Pmax = 5.5E+06`` echoes
    ``MAXIMUM PRESSURE TIME FUNCTION SCALE FACTOR = 1.0000000200409E+20``. A
    constant P_LIMIT therefore CANNOT be set through the scale factor and has
    to go through a flat /FUNCT. (``Fscale_Padd`` with ``fct_Padd = 0`` IS
    honoured — probe: 1234.0 preserved — which is why BULK rides its scale
    factor directly and P_LIMIT does not.)
    """
    kw = f"*{ab.keyword}"
    # Every function id /MONVOL/LFLUID references is checked by the starter and
    # a missing one is ERROR 9 ("UNDEFINED LOAD CURVE FOR %s FUNCTION ID=%d"),
    # which refuses the deck — so a dangling reference is named here rather
    # than discovered at run time.
    missing = sorted({fid for fid in (ab.lcbulk, ab.lcint, ab.lcoutt,
                                      ab.lcoutp, ab.lcfit, ab.p_limlc)
                      if fid > 0 and fid not in state.curves})
    if missing:
        state.warn(
            f"{kw}: curve id(s) {missing} are referenced by the fluid model "
            "but this deck defines no *DEFINE_CURVE with those ids. The "
            "/MONVOL/LFLUID still references them; a missing function is "
            "starter ERROR 9 and the whole deck is refused.")
    if ab.p_limlc > 0:
        ab.pmax_fct = ab.p_limlc
    elif ab.p_limit > 0.0:
        fid = state.next_curve_id()
        add_curve(state, fid, f"MONVOL_{ab.monvol_id}_PMAX",
                  [(0.0, ab.p_limit), (1.0, ab.p_limit)])
        ab.pmax_fct = fid
    if ab.lcbulk <= 0 and ab.bulk <= 0.0:
        state.warn(
            f"{kw}: neither BULK nor LCBULK gives a bulk modulus, so the "
            "fluid has no stiffness and the bag applies only the LCFIT added "
            "pressure (if any). Give BULK.")
    if ab.ro <= 0.0:
        state.warn(
            f"{kw}: RO={ab.ro:g} is the fluid density and the engine forms the "
            "uncompressed volume as V0 = GMASS/RHOI. A zero density makes that "
            "a division by zero. Give RO.")
    if ab.lcid:
        state.warn(
            f"{kw}: LCID={ab.lcid} (pressure as a function of time) is DROPPED "
            "— /MONVOL/LFLUID has no prescribed-pressure slot; its pressure "
            "comes from the bulk law K*ln(V0/V) + Padd. If the prescribed "
            "curve was the point, restate the bag as *AIRBAG_LOAD_CURVE, which "
            "converts to /MONVOL/PRES with Itypfun=1 (P = F(t)).")
    if ab.nonull:
        state.warn(
            f"{kw}: NONULL={ab.nonull} has no Radioss counterpart and is "
            "DROPPED.")


# ─────────────────────────────────────────────────────────────────────────────
# Emitters
# ─────────────────────────────────────────────────────────────────────────────

def _emit_monvol_pres(ab: Airbag) -> List[str]:
    """/MONVOL/PRES (ITYPE 2) — ``MONVOL/pres.cfg FORMAT(radioss140)``,
    reader ``airbag/hm_read_monvol_type2.F``::

        /MONVOL/PRES/<id>
        <title, 100>
        surf_IDex(10)
        Ascalet(20)
        fct_ID(10) Fscale(20) <10 blank> Itypfun(10)

    Card 2 holds ONLY Ascalet at 2022 (radioss110/130 had five slots;
    radioss140 trimmed it to one) — the reader hard-overwrites AscaleP/S/A/D
    with ``ONE * FAC_*`` regardless of input. ``Ascalet = 0`` and
    ``Fscale = 0`` are deliberate: the starter turns both into ``1 x unit``.
    """
    b10 = " " * 10
    return [
        f"/MONVOL/PRES/{ab.monvol_id}",
        (ab.title or f"MONVOL_PRES_{ab.monvol_id}")[:100],
        "#surf_IDex",
        f"{_i(ab.surf_id)}",
        "#            Ascalet",
        f"{_f(0.0)}",
        "#   fct_ID              Fscale             Itypfun",
        f"{_i(ab.fct_id)}{_f(ab.fscale)}{b10}{_i(ab.itypfun)}",
        HDR,
    ]


def _emit_monvol_gas(ab: Airbag) -> List[str]:
    """/MONVOL/GAS (ITYPE 3) — ``CONTROLVOL/monvol_gas.cfg FORMAT(radioss2020)``,
    reader ``hm_read_monvol_type3.F``::

        /MONVOL/GAS/<id>
        <title, 100>
        surf_IDex(10) I_equi(10)
        Ascalet(20) AscaleP(20) AscaleS(20) AscaleA(20) AscaleD(20)
        Gamma(20) Mu(20) Trelax(20) Tini(20) Rhoi(20)
        Pext(20) Pini(20) Pmax(20) Vinc(20) Mini(20)
        Nvent(10)

    ``Gamma`` is gamma ITSELF, not 1/gamma — the engine uses
    ``PRES = (GAMA-ONE)*ENERGY/(VOL-VINC)``. Every blank is a real starter
    default: Mu 0 -> 0.01, Tini 0 -> 295 K, Pmax 0 -> INFINITY (no bursting),
    every Ascale* 0 -> ``1 x unit``.
    """
    pini = ab.p0 + ab.pe          # LS-DYNA P0 is GAUGE; Radioss Pini absolute
    vinc = ab.vini / ab.vsca if ab.vsca else ab.vini
    return [
        f"/MONVOL/GAS/{ab.monvol_id}",
        (ab.title or f"MONVOL_GAS_{ab.monvol_id}")[:100],
        "#surf_IDex    I_equi",
        f"{_i(ab.surf_id)}{_i(0)}",
        "#            Ascalet             AscaleP             AscaleS"
        "             AscaleA             AscaleD",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#              Gamma                  Mu              Trelax"
        "                Tini                Rhoi",
        f"{_f(ab.gamma)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(ab.ro)}",
        "#               Pext                Pini                Pmax"
        "                Vinc                Mini",
        f"{_f(ab.pe)}{_f(pini)}{_f(0.0)}{_f(vinc)}{_f(0.0)}",
        "#    Nvent",
        f"{_i(0)}",
        HDR,
    ]


def _emit_monvol_airbag1(ab: Airbag) -> List[str]:
    """/MONVOL/AIRBAG1 (ITYPE 7) — ``MONVOL/airbag1.cfg FORMAT(radioss140)``,
    reader ``hm_read_monvol_type7.F``::

        /MONVOL/AIRBAG1/<id>
        <title, 100>
        surf_IDex(10) <10 blank> Hconv(20)
        AscaleT(20) AscaleP(20) AscaleS(20) AscaleA(20) AscaleD(20)
        mat_ID(10) <10 blank> Mu(20) Pext(20) T0(20) Iequi(10) Ittf(10)
        Njet(10)
          inject_ID(10) sens_ID(10) Ijet(10) node_ID1(10) node_ID2(10) node_ID3(10)
        Nvent(10) Nporsurf(10)
          surf_IDv(10) Iform(10) Avent(20) Bvent(20) <20 blank> vent_title(20)
          Tstart(20) Tstop(20) dPdef(20) dtPdef(20) <10 blank> IdtPdef(10)
          fct_IDt(10) fct_IDP(10) fct_IDA(10) <10 blank> Fscalet(20) FscaleP(20) FscaleA(20)
          fct_IDt'(10) fct_IDP'(10) fct_IDA'(10) <10 blank> ...'

    **There is no Pini field**: the reader sets ``PINI = PEXT`` unconditionally
    and derives the initial gas mass from it, ``MI = PINI*(VOL+VEPS)/(RMWI*TI)``.
    ``T0`` is both the initial bag temperature AND the ambient temperature the
    Hconv term uses (``RVOLU(25)`` is re-read by the engine as TEXT).
    """
    b10, b20 = " " * 10, " " * 20
    t0 = ab.t_ext if ab.t_ext != 0.0 else 295.0
    lines = [
        f"/MONVOL/AIRBAG1/{ab.monvol_id}",
        (ab.title or f"MONVOL_AIRBAG1_{ab.monvol_id}")[:100],
        "#surf_IDex                         Hconv",
        f"{_i(ab.surf_id)}{b10}{_f(0.0)}",
        "#            AscaleT             AscaleP             AscaleS"
        "             AscaleA             AscaleD",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#   mat_ID                            Mu                Pext"
        "                  T0     Iequi      Ittf",
        f"{_i(ab.gas_mat_id)}{b10}{_f(0.0)}{_f(ab.pe)}{_f(t0)}{_i(0)}{_i(0)}",
        "#     Njet",
        f"{_i(1)}",
        "#inject_ID   sens_ID      Ijet  node_ID1  node_ID2  node_ID3",
        f"{_i(ab.inject_prop_id)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}",
    ]
    nvent = 1 if (ab.avent > 0.0 or ab.vent_fct_p) else 0
    lines += ["#    Nvent  Nporsurf", f"{_i(nvent)}{_i(0)}"]
    if nvent:
        lines += [
            "# surf_IDv     Iform               Avent               Bvent"
            "                              vent_title",
            # surf_IDv = 0 is the whole-bag porosity mode, in which Avent is
            # the vent AREA (with a named surface it would be a scale factor)
            # and Bvent is forced to 0 by the reader.
            f"{_i(0)}{_i(1)}{_f(ab.avent)}{_f(0.0)}{b20}"
            + f"{'VENT':>20}",
            "#             Tstart               Tstop               dPdef"
            "              dtPdef             IdtPdef",
            # Tstart = Tstop = dPdef = dtPdef = 0 makes the hole open from t=0
            # (hm_read_monvol_type7.F: IBAGHOL(1,II) = 1).
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{b10}{_i(0)}",
            "#  fct_IDt   fct_IDP   fct_IDA                       Fscalet"
            "             FscaleP             FscaleA",
            f"{_i(0)}{_i(ab.vent_fct_p)}{_i(0)}{b10}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            "# fct_IDt'  fct_IDP'  fct_IDA'                      Fscalet'"
            "            FscaleP'            FscaleA'",
            f"{_i(0)}{_i(0)}{_i(0)}{b10}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        ]
    lines.append(HDR)
    return lines


def _emit_monvol_lfluid(ab: Airbag) -> List[str]:
    """/MONVOL/LFLUID (ITYPE 10) — ``CONTROLVOL/monvol_lfluid.cfg
    FORMAT(radioss2019)``, reader ``hm_read_monvol_type10.F``::

        /MONVOL/LFLUID/<id>
        <title, 100>
        surf_IDex(10)
        Ascalet(20) AscaleP(20)
        Rho(20)
        fct_K(10) fct_Mtin(10) Fscale_K(20) Fscale_Mtin(20)
        fct_Mtout(10) fct_Mpout(10) Fscale_Mtout(20) Fscale_Mpout(20)
        fct_Padd(10) fct_Pmax(10) Fscale_Padd(20) Fscale_Pmax(20)

    Where a function id is 0 the paired scale factor is used as a CONSTANT
    (``volp_lfluid.F``: ``BULK = SCALEF`` or ``SCALEF*F_K(TT)``), which is how
    a scalar BULK is carried — the one exception being Fscale_Pmax, which the
    STARTER overwrites with INFINITY unless a function is present (see
    ``_resolve_linear_fluid``).
    """
    fscale_k = 0.0 if ab.lcbulk > 0 else ab.bulk
    return [
        f"/MONVOL/LFLUID/{ab.monvol_id}",
        (ab.title or f"MONVOL_LFLUID_{ab.monvol_id}")[:100],
        "#surf_IDex",
        f"{_i(ab.surf_id)}",
        "#            Ascalet             AscaleP",
        f"{_f(0.0)}{_f(0.0)}",
        "#                Rho",
        f"{_f(ab.ro)}",
        "#    fct_K  fct_Mtin            Fscale_K         Fscale_Mtin",
        f"{_i(max(0, ab.lcbulk))}{_i(max(0, ab.lcint))}{_f(fscale_k)}{_f(0.0)}",
        "#fct_Mtout fct_Mpout        Fscale_Mtout        Fscale_Mpout",
        f"{_i(max(0, ab.lcoutt))}{_i(max(0, ab.lcoutp))}{_f(0.0)}{_f(0.0)}",
        "# fct_Padd  fct_Pmax         Fscale_Padd         Fscale_Pmax",
        f"{_i(max(0, ab.lcfit))}{_i(ab.pmax_fct)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_mat_gas_csta(mat_id: int, title: str, cp: float,
                       cv: float) -> List[str]:
    """``/MAT/GAS/CSTA`` — constant Cp and Cv, ``MAT/mat_gas.cfg``.

    One card, ``Cp`` at columns 1-20 and ``Cv`` at 21-40. Both are
    MASS-specific, exactly like LS-DYNA's CV/CP ("e.g. Joules/kg/oK").
    """
    return [
        f"/MAT/GAS/CSTA/{mat_id}",
        title[:100],
        "#                 Cp                  Cv",
        f"{_f(cp)}{_f(cv)}",
        HDR,
    ]


def _emit_mat_gas_mass(mat_id: int, title: str, mw: float, cpa: float,
                       cpb: float) -> List[str]:
    """``/MAT/GAS/MASS`` — a mass-specific Cp POLYNOMIAL in T plus the molecular
    weight, ``MAT/mat_gas.cfg FORMAT(radioss120)``::

        /MAT/GAS/MASS/<mid>
        <title>
        MW(20)
        Cpa(20) Cpb(20) Cpc(20) Cpd(20) Cpe(20)
        Cpf(20)

    Radioss forms ``CPI = Cpa + Cpb*T + Cpc*T^2 + Cpd*T^3 + Cpe/T^2 + Cpf*T^4``
    and then ``CVI = CPI - R/MW`` — so Cv is DERIVED and must never be written
    into a Cp slot. LS-DYNA's card-4a A and B are MOLAR (J/mol/K, J/mol/K^2),
    hence ``Cpa = A/MW`` and ``Cpb = B/MW``.
    """
    return [
        f"/MAT/GAS/MASS/{mat_id}",
        title[:100],
        "#                 MW",
        f"{_f(mw)}",
        "#                Cpa                 Cpb                 Cpc"
        "                 Cpd                 Cpe",
        f"{_f(cpa)}{_f(cpb)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#                Cpf",
        f"{_f(0.0)}",
        HDR,
    ]


def _emit_prop_inject1(prop_id: int, title: str, mat_id: int, fun_m: int,
                       fun_t: int) -> List[str]:
    """``/PROP/INJECT1`` — one injected gas, ``PROP/prop_inject1.cfg
    FORMAT(radioss100)``, reader ``properties/injector/hm_read_inject1.F``::

        /PROP/INJECT1/<id>
        <title, 100>
        N_gases(10) Iflow(10) Ascale_T(20)
        Mat_ID(10) fun_ID_M(10) fun_ID_T(10) <10 blank> Fscale_M(20) Fscale_T(20)

    ``Iflow = 1`` — see ``INJECT1_IFLOW_MASS_RATE``. ``Ascale_T = 1.0`` is
    written explicitly rather than left to the default: it DIVIDES the time
    abscissa while the ``IFLU == 1`` integration multiplies by DT1 without
    dividing, so the two paths disagree for any other value.
    """
    b10 = " " * 10
    return [
        f"/PROP/INJECT1/{prop_id}",
        title[:100],
        "#  N_gases     Iflow            Ascale_T",
        f"{_i(1)}{_i(INJECT1_IFLOW_MASS_RATE)}{_f(1.0)}",
        "#   Mat_ID  fun_ID_M  fun_ID_T                      Fscale_M"
        "            Fscale_T",
        f"{_i(mat_id)}{_i(fun_m)}{_i(fun_t)}{b10}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_airbag_surface(state: ConversionState, ab: Airbag) -> List[str]:
    """The external ``/SURF`` of one monitored volume, built from SHELL
    ELEMENTS (never from segments — ``/SURF/SEG`` is ERROR 18).

    Quads and triangles go into a ``/GRSHEL/SHEL`` and a ``/GRSH3N/SH3N``
    respectively; with both present the two ``/SURF`` are wrapped in a
    ``/SURF/SURF``. Same split ``_make_master_surface`` applies to a contact
    scope, and for the same reason: a ``/GRSHEL/SHEL`` group resolves only
    4-node ``/SHELL`` ids, and a ``/SH3N`` id put in one is starter ERROR 70.
    """
    lines: List[str] = []
    quads = [e for e in ab.quad_eids if e in state.shell_elem_ids]
    tris = [e for e in ab.tri_eids if e in state.sh3n_elem_ids]
    lost = (len(ab.quad_eids) - len(quads)) + (len(ab.tri_eids) - len(tris))
    if lost:
        state.warn(
            f"*{ab.keyword} (SID {ab.sid}): {lost} shell element(s) of the "
            "monitored volume's surface were never WRITTEN to the deck (their "
            "*PART is missing, or they were screened out), so they are left "
            "out of the /SURF. Naming an element the deck does not define is "
            "starter ERROR 70 and the whole run is refused, which is strictly "
            "worse than a surface that is short by those segments.")
    title = f"MONVOL_{ab.monvol_id}_SURF"
    if quads and tris:
        g1, s1 = state.next_id(), state.next_id()
        g2, s2 = state.next_id(), state.next_id()
        lines += _emit_grshel(g1, f"{title}_grshel", quads)
        lines += _emit_surf_grshel(s1, f"{title}_shells", g1)
        lines += _emit_grsh3n(g2, f"{title}_grsh3n", tris)
        lines += _emit_surf_grsh3n(s2, f"{title}_tris", g2)
        lines += _emit_surf_surf(ab.surf_id, title, [s1, s2])
    elif quads:
        g1 = state.next_id()
        lines += _emit_grshel(g1, f"{title}_grshel", quads)
        lines += _emit_surf_grshel(ab.surf_id, title, g1)
    elif tris:
        g2 = state.next_id()
        lines += _emit_grsh3n(g2, f"{title}_grsh3n", tris)
        lines += _emit_surf_grsh3n(ab.surf_id, title, g2)
    else:
        return []
    return lines


def _make_monvols(state: ConversionState) -> List[str]:
    """Every converted ``*AIRBAG_*`` → its ``/SURF``, its gas material and
    injector where it has them, and its ``/MONVOL``.

    ``state.monvol_ids`` is filled AT THE LINE that writes the /MONVOL card,
    never derived from ``state.airbags`` — a bag whose surface resolves to no
    shell element is dropped, and *DATABASE_ABSTAT's /TH/MONV must list only
    what really exists (the #106 rule: a /TH group naming an absent entity is
    refused outright, which is worse than losing the channel).
    """
    live = [a for a in state.airbags if not a.dropped]
    if not live:
        return []
    lines = ["#-  MONITORED VOLUMES (*AIRBAG_* -> /MONVOL):", HDR]
    for ab in live:
        surf = _emit_airbag_surface(state, ab)
        if not surf:
            ab.dropped = True
            state.warn(
                f"*{ab.keyword} (SID {ab.sid}): every shell element of its "
                "surface is absent from the emitted deck, so no /SURF and no "
                "/MONVOL are written and the bag does not inflate.")
            continue
        lines += surf
        if ab.model == "SIMPLE_AIRBAG_MODEL":
            gtitle = f"MONVOL_{ab.monvol_id}_GAS"
            if ab.gas_mat_kind == "CSTA":
                lines += _emit_mat_gas_csta(ab.gas_mat_id, gtitle, ab.cp, ab.cv)
            else:
                mw = ab.mw
                cpa = ab.hc_a / mw if mw else 0.0
                cpb = ab.hc_b / mw if mw else 0.0
                lines += _emit_mat_gas_mass(ab.gas_mat_id, gtitle, mw, cpa, cpb)
            lines += _emit_prop_inject1(
                ab.inject_prop_id, f"MONVOL_{ab.monvol_id}_INJECTOR",
                ab.gas_mat_id, max(0, ab.lcid), ab.inject_temp_fct)
            lines += _emit_monvol_airbag1(ab)
        elif ab.model == "ADIABATIC_GAS_MODEL":
            lines += _emit_monvol_gas(ab)
        elif ab.model == "LINEAR_FLUID":
            lines += _emit_monvol_lfluid(ab)
        else:                                    # PRES: SPV and LOAD_CURVE
            lines += _emit_monvol_pres(ab)
        state.monvol_ids.append((ab.monvol_id, ab.title))
    return lines if len(lines) > 2 else []
