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

from ..state import Airbag, AirbagVent, ConversionState, GasSpecies
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
    "_emit_monvol_fvmbag2",
    "_emit_mat_gas_csta",
    "_emit_mat_gas_mass",
    "_emit_mat_gas_mole",
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

#: ``/MONVOL`` ``Ittf`` — how the vent and porosity CLOCKS relate to the
#: injector's time-to-fire. **0, always, and that is a deliberate deviation
#: from dyna2rad.**
#:
#: ``engine/source/airbag/airbagb1.F`` evaluates every vent TIME function at
#: ``TT1 = TT - TTF`` (and at ``TT - TTF - TVENT`` when the input ``Ittf`` is
#: 3), where ``TTF = RVOLU(60)`` is the injector SENSOR's time-to-fire. With no
#: sensor, ``TTF = 0`` and ``TT1 = TT`` — the absolute time an LS-DYNA LCC23 /
#: LCTC23 curve is already written against.
#:
#: dyna2rad instead strips the leading zero-flow run off each ``LCIDM``,
#: re-emits the curve shifted by ``-TTF``, arms a ``/SENSOR/TIME`` with
#: ``Tdelay = TTF`` and writes ``Ittf = 3`` (``convertcontrolvols.cxx:2686``,
#: ``:2760``, ``:3216``). On the INJECTOR that is a wash — ``airbaga1.F``
#: reads the mass curve at ``TSG = (TT - TSTART)/ASTIME`` with ``TSTART`` the
#: same sensor's start, so the shift and the delay cancel exactly. On the VENT
#: it is not: d2r writes ``LCC23``/``LCP23`` RAW while ``Ittf = 3`` makes the
#: engine evaluate them ``TTF`` seconds early. Doing neither is both simpler
#: and strictly more faithful, and it costs one ``/SENSOR/TIME`` and one
#: rebuilt ``/FUNCT`` per gas that carried no information.
#:
#: The same reasoning settles ``Tswitch`` on FVMBAG2, which ``fv_up_switch.F``
#: measures as ``TT - TTF``: with no sensor it is measured from t = 0, which is
#: exactly what LS-DYNA's ``TSW`` means.
ITTF_NO_SHIFT = 0

#: ``/MONVOL/FVMBAG2`` numerics, from ``convertcontrolvols.cxx:2258-2265``.
#: ``Dtsca`` equals the cfg default; ``Cgmerg`` deliberately COARSENS the
#: finite-volume merge (the cfg default is 0.02, ``monvol_fvmbag2.cfg:231``),
#: which keeps the FV count — and hence the bag's own time step — from
#: collapsing as the bag folds.
_FVMBAG2_CGMERG = 0.05
_FVMBAG2_DTSCA = 0.9

#: ``Dtmin`` per LS-DYNA ``*AIRBAG_PARTICLE`` card-3 ``UNIT``. The flag's own
#: table (Vol I R17 p.3-100) is 0 = kg-mm-ms-K, 1 = SI, 2 = tonne-mm-s-K,
#: 3 = user-defined. 1e-4 in a *ms* system and 1e-7 in the two *s* systems is
#: the SAME floor — 1e-4 ms = 1e-7 s — so the split is one number expressed
#: twice, not two policies. UNIT = 3 (user-defined conversion factors) has no
#: entry: its time unit is whatever card 6 says, so no floor can be assumed and
#: ``Dtmin`` is left 0, which the starter promotes to its own 1e-20.
_FVMBAG2_DTMIN = {0: 1e-4, 1: 1e-7, 2: 1e-7}

#: The pressure/time sentinel the vent block uses for "this criterion can never
#: fire". The starter uses the same magnitude itself — ``hm_read_monvol_type11.F
#: :809-810`` sets ``DPDEF = INFINITY, TVENT = INFINITY`` for a zero-area vent —
#: and it is what makes a POP-OPEN pressure work at all: ``airbagb1.F:290`` ORs
#: the time criterion with the pressure one, so a vent whose ``Tstart`` is 0
#: opens on the first cycle no matter what ``dPdef`` says.
_VENT_NEVER = 1.0e30

#: SI factor of each unit name the ``/BEGIN`` block can carry, used to
#: reproduce the starter's own conversion of the universal gas constant:
#: ``hm_read_matgas.F:293`` sets ``R_IGC1 = R_IGC / FAC_M / FAC_L / FAC_L *
#: FAC_T**2`` and stores it as ``PM(27)``. Unknown names simply skip the check.
_UNIT_FAC_M = {"kg": 1.0, "g": 1e-3, "mg": 1e-6, "Mg": 1e3, "t": 1e3,
               "ton": 1e3, "tonne": 1e3, "lbm": 0.45359237, "slug": 14.5939029}
_UNIT_FAC_L = {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "dm": 1e-1, "km": 1e3,
               "in": 0.0254, "ft": 0.3048, "micro_m": 1e-6}
_UNIT_FAC_T = {"s": 1.0, "ms": 1e-3, "micro_s": 1e-6, "mus": 1e-6,
               "min": 60.0, "h": 3600.0}

#: The universal gas constant in SI, as the starter holds it before scaling.
#: The value is the solver's own ``R_IGC`` (``common_source/modules/
#: constant_mod.F:932``), NOT the textbook 8.314 — confirmed by the starter
#: echo on an AIRBAG1 probe, ``MOLECULAR WEIGHT = 2.8970286405876E-05``, i.e.
#: ``R_IGC1 = 8314.47`` in Mg/mm/s. A 0.0057 % offset that no threshold here
#: turns on, but ``_radioss_gas_constant`` claims to reproduce
#: ``hm_read_matgas.F:293`` EXACTLY, so it uses the exact constant.
_R_IGC_SI = 8.314472


def _radioss_gas_constant(state: ConversionState):
    """``R`` in the deck's WORK units, or ``None`` when they are not known.

    Reproduces ``hm_read_matgas.F:293`` exactly. This is the number the starter
    uses to derive ``Cv = Cp - R/MW``, and it is NOT the deck's own GASC — so a
    card whose Cp polynomial and MW are stated in a different unit system from
    the mesh produces a wrong Cv with no starter diagnostic at all.
    """
    mass, length, time = state.units
    fac_m = _UNIT_FAC_M.get(mass)
    fac_l = _UNIT_FAC_L.get(length)
    fac_t = _UNIT_FAC_T.get(time)
    if not (fac_m and fac_l and fac_t):
        return None
    return _R_IGC_SI / fac_m / fac_l / fac_l * (fac_t * fac_t)


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


def _part_scope_pids(state: ConversionState, sid: int, is_set: bool,
                     ref: str, what: str) -> List[int]:
    """``[pid, …]`` of an LS-DYNA PART-or-PART-SET reference.

    The one place batch 2 turns a ``(id, type-flag)`` pair into parts:
    ``*AIRBAG_PARTICLE``'s SD1/SD2 and its ``SID3``/``STYPE3`` vent rows, and
    ``*AIRBAG_HYBRID``'s negative ``A23``. All three use the SAME convention —
    **0 = a PART, non-zero = a PART SET** — which is the OPPOSITE of the
    ``SIDTYP`` on card 1 of the other five models (0 = *SET_SEGMENT). Getting
    it backwards silently swaps a single vent part for whatever set shares its
    id, so the flag is passed in already decided by the caller.

    A reference that resolves to neither returns ``[]`` and says so; the caller
    decides whether that is fatal for it.
    """
    if sid <= 0:
        return []
    if is_set:
        ps = state.part_sets.get(sid)
        if ps is not None:
            return list(ps[1])
        if sid in state.parts:
            state.warn(
                f"{ref}: {what} names *SET_PART {sid}, which this deck does "
                f"not define — but *PART {sid} exists. The single part is "
                "used. Set the type flag to 0 to say so explicitly.")
            return [sid]
        state.warn(
            f"{ref}: {what} names *SET_PART {sid}, which this deck defines "
            "neither as a part set nor as a part. It resolves to no shell at "
            "all.")
        return []
    if sid in state.parts:
        return [sid]
    ps = state.part_sets.get(sid)
    if ps is not None:
        state.warn(
            f"{ref}: {what} names *PART {sid}, which this deck does not "
            f"define — but *SET_PART {sid} exists. The SET is used. Set the "
            "type flag to 1 to say so explicitly.")
        return list(ps[1])
    state.warn(
        f"{ref}: {what} names *PART {sid}, which this deck defines neither as "
        "a part nor as a part set. It resolves to no shell at all.")
    return []


def _eids_of_pids(state: ConversionState, pids: List[int], ref: str,
                  what: str) -> List[int]:
    """The SHELL element ids of a part list, with the same empty-part and
    solid-part screen ``_airbag_surface_eids`` applies to a bag surface.

    A ``/MONVOL`` surface — external, internal, vent or nozzle alike — has to
    be element-backed and shell-backed: ``check_surf.F:55-62`` sets
    ``IGRSURF%ISH4N3N`` only for ELTYP 3 and 7, and every ``hm_read_monvol_*``
    answers ``ERROR 18`` for anything else.
    """
    pid_set = set(pids)
    if not pid_set:
        return []
    eids = sorted(e.eid for e in state.shell_elems if e.pid in pid_set)
    empty = sorted(p for p in pid_set
                   if not any(e.pid == p for e in state.shell_elems))
    if empty:
        solid = sorted(p for p in empty
                       if any(e.pid == p for e in state.solid_elems)
                       or any(e.pid == p for e in state.tshell_elems))
        state.warn(
            f"{ref}: part(s) {empty} named by {what} carry NO SHELL elements, "
            "so they contribute nothing to that surface"
            + (f" — {solid} hold SOLID/thick-shell elements, and a /MONVOL "
               "surface built over those is starter ERROR 18 (\"SURFACE ID IS "
               "NOT DEFINED WITH SHELLS\"), which aborts the run. They are "
               "left out rather than emitted."
               if solid else
               ". Check the set: an empty part is usually a PID typo."))
    return eids


def _particle_surface_eids(state: ConversionState, ab: Airbag) -> List[int]:
    """``*AIRBAG_PARTICLE``'s EXTERNAL surface: ``SD1 \\ SD2``.

    SD1 is the whole CPM bag scope; SD2 is the subset of it that is INTERNAL
    (baffles, diaphragms, tethers). The finite-volume mesher needs the two
    apart — ``surf_IDex`` bounds the volume it fills with tetrahedra and
    ``surf_IDin`` splits that volume into chambers — so an internal part left
    in the external surface is a T-connection on every one of its edges
    (``WARNING 1882``, *"EXTERNAL SURFACE CONTAINS T-CONNECTIONS CANNOT BE
    ORIENTED BY RADIOSS STARTER"``) and the orientation pass gives up on the
    WHOLE bag.

    ``ab.in_quad_eids`` / ``ab.in_tri_eids`` are filled here as well, because
    the difference and the internal set have to be taken from one reading of
    the two scopes.
    """
    ref = f"*{ab.keyword} (SD1 {ab.sd1})"
    outer = _part_scope_pids(state, ab.sd1, ab.stype1 != 0, ref, "SD1")
    inner = _part_scope_pids(state, ab.sd2, ab.stype2 != 0, ref, "SD2") \
        if ab.sd2 > 0 else []
    inner_set = set(inner)
    stray = sorted(p for p in inner_set if p not in set(outer))
    if stray:
        state.warn(
            f"{ref}: part(s) {stray} are named by SD2 (the INTERNAL surface) "
            "but are not in SD1 (the bag surface). LS-DYNA's SD2 is a SUBSET "
            "of SD1 — it marks which of the bag's own parts are internal "
            "baffles — so a part in only SD2 describes an internal wall of a "
            "cavity it does not bound. It is still emitted as the internal "
            "surface; check the two sets.")
    ext_eids = _eids_of_pids(state, [p for p in outer if p not in inner_set],
                             ref, "SD1 minus SD2")
    in_eids = _eids_of_pids(state, inner, ref, "SD2")
    ab.in_quad_eids, ab.in_tri_eids = _split_shell_eids_by_topology(
        state, in_eids)
    return ext_eids


def _airbag_surface_eids(state: ConversionState, ab: Airbag) -> List[int]:
    """The shell element ids of one airbag's external surface.

    SIDTYP == 0 → a *SET_SEGMENT, resolved to the owning shells (see above).
    SIDTYP != 0 → a *SET_PART (already flattened past *SET_PART_ADD by
    ``_flatten_part_set_adds``); a bare *PART id is accepted as well, with a
    warning, because a deck that writes one is common enough and the intent is
    never in doubt.

    ``*AIRBAG_PARTICLE`` is the one model whose card 1 is not the shared
    ``SID SIDTYP …`` — it states SD1/STYPE1 and SD2/STYPE2 — so it branches
    off to :func:`_particle_surface_eids` before any of that applies.
    """
    if ab.model == "PARTICLE":
        return _particle_surface_eids(state, ab)
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
            # next_monvol_id, not next_id: the auto stream must also dodge the
            # ids the deck ITSELF states, or a *AIRBAG_..._ID at or above the
            # auto-id base collides with a later renumbered bag and the pair is
            # starter ERROR 79.
            mid = state.next_monvol_id(
                used_monvol_ids | {a.airbag_id for a in state.airbags
                                   if a.airbag_id > 0})
        used_monvol_ids.add(mid)
        ab.monvol_id = mid
        ab.surf_id = state.next_id()
        _resolve_airbag_model(state, ab)
    # AFTER every bag knows its own /MONVOL type: an *AIRBAG_INTERACTION can
    # only be resolved once both of its partners have one, and it PROMOTES
    # them, so it cannot run inside the per-bag loop.
    _resolve_airbag_interactions(state)
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
    ab.ittf = ITTF_NO_SHIFT
    if ab.model == "SIMPLE_PRESSURE_VOLUME":
        ab.radioss_type = "PRES"
        _resolve_spv(state, ab, _add_auto_curve)
    elif ab.model == "LOAD_CURVE":
        ab.radioss_type = "PRES"
        _resolve_load_curve(state, ab, _add_auto_curve)
    elif ab.model == "ADIABATIC_GAS_MODEL":
        ab.radioss_type = "GAS"
        _resolve_adiabatic_gas(state, ab)
    elif ab.model == "SIMPLE_AIRBAG_MODEL":
        ab.radioss_type = "AIRBAG1"
        _resolve_simple_airbag(state, ab, _add_auto_curve)
    elif ab.model == "LINEAR_FLUID":
        ab.radioss_type = "LFLUID"
        _resolve_linear_fluid(state, ab, _add_auto_curve)
    elif ab.model == "HYBRID":
        ab.radioss_type = "AIRBAG1"
        _resolve_hybrid(state, ab, _add_auto_curve)
    elif ab.model == "PARTICLE":
        ab.radioss_type = ("AIRBAG1" if state.options.airbag_particle_uniform
                           else "FVMBAG2")
        _resolve_particle(state, ab, _add_auto_curve)
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
        _warn_gas_gamma(state, ab)
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
    if ab.pe == 0.0:
        state.warn(
            f"{kw}: PE (external pressure) is 0, which LS-DYNA reads as "
            "\"no ambient pressure\" — the bag applies its full ABSOLUTE "
            "pressure to the structure. Radioss reads a blank Pext as a "
            "REQUEST FOR ONE ATMOSPHERE: hm_read_monvol_type7.F:417-418 "
            "substitutes 101325 Pa rescaled into the /BEGIN unit system, and "
            ":421 then sets PINI = PEXT and :536 derives the initial gas mass "
            "MI = PINI*(VOL+VEPS)/(RMWI*TI) from it. So the converted bag "
            "pushes P - 1 atm on the fabric AND starts pre-filled at 1 atm, "
            "with 0 ERROR(S) either way. State PE explicitly — a tiny "
            "non-zero value is enough to keep the substitution from firing.")
    _resolve_airbag_vent(state, ab, add_curve)


def _warn_gas_gamma(state: ConversionState, ab: Airbag) -> None:
    """Compute the gamma the STARTER will compute for a ``/MAT/GAS/MASS``, and
    say so when it is not a usable ratio of specific heats.

    This is an "assert the effect" check, and it exists because the failure it
    catches is silent. ``hm_read_monvol_type7.F`` forms::

        CPI  = Cpa + Cpb*T0 + Cpc*T0^2 + Cpd*T0^3 + Cpe/T0^2 + Cpf*T0^4
        RMWI = R_IGC1 / MW          ! R_IGC1 = PM(27), NOT the deck's GASC
        CVI  = CPI - RMWI
        GAMAI = CPI / CVI

    and ``R_IGC1`` is 8.314 rescaled into the ``/BEGIN`` unit system
    (``hm_read_matgas.F:293``). A card whose Cp and MW are stated in SI while
    the mesh is in Mg/mm/s therefore gets an R three orders of magnitude too
    large, ``CVI`` goes NEGATIVE, and the starter reports
    ``GAMMA AT INITIAL TEMPERATURE = -3.61E-03`` with **0 ERROR(S)** and
    TERMINATION WITH WARNING. MEASURED on a probe deck: a bag whose gas would
    then expand the wrong way, on a run that looks clean.

    Only the ``/MAT/GAS/MASS`` branch is at risk. ``/MAT/GAS/CSTA`` takes Cp
    and Cv directly and gamma is their unit-free ratio (the starter derives MW
    from ``R/(Cp-Cv)`` there instead), which the Cp > Cv check already covers.
    """
    if ab.gas_mat_kind != "MASS" or ab.mw <= 0.0:
        return
    r_work = _radioss_gas_constant(state)
    if r_work is None:
        return
    t0 = ab.t_ext if ab.t_ext != 0.0 else 295.0
    cpa = ab.hc_a / ab.mw
    cpb = ab.hc_b / ab.mw
    cpi = cpa + cpb * t0
    cvi = cpi - r_work / ab.mw
    if cvi > 0.0 and cpi / cvi > 1.0:
        return
    gama = cpi / cvi if cvi != 0.0 else float("inf")
    state.warn(
        f"*{ab.keyword}: the /MAT/GAS/MASS this card converts to gives the "
        f"starter Cv = Cp - R/MW = {cpi:.6g} - {r_work / ab.mw:.6g} = "
        f"{cvi:.6g} at T0 = {t0:g}, i.e. GAMMA = {gama:.6g} — not a usable "
        "ratio of specific heats. Radioss does NOT use the card's own GASC: it "
        "uses its own universal gas constant rescaled into the /BEGIN unit "
        f"system ({state.units[0]}/{state.units[1]}/{state.units[2]} here, so "
        f"R = {r_work:.6g}), hm_read_matgas.F:293. The usual cause is a card "
        "whose CV/CP/A/B/MW are in SI while the mesh is in mm — the starter "
        "reports the resulting negative GAMMA and still finishes with 0 "
        "ERROR(S), so nothing else will tell you. Restate the gas constants "
        "in the deck's own unit system, or give CV and CP directly (the "
        "/MAT/GAS/CSTA path, whose gamma is their unit-free ratio).")


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
    elif area_curve or mu_curve:
        # ONE of the two is a curve; the other is the constant it multiplies.
        # A ZERO constant is not a missing value to default to 1 — LS-DYNA's
        # leak mass flow is proportional to mu*A, so a blank MU with an AREA
        # curve is an orifice that is CLOSED, and substituting 1.0 would vent
        # a bag LS-DYNA seals at the full curve area (or, the other way round,
        # put a dimensionless porosity into the AREA slot).
        partner, pname, cname = ((mu, "MU", "AREA") if area_curve
                                 else (area, "AREA", "MU"))
        src = area_curve or mu_curve
        if partner == 0.0:
            state.warn(
                f"{kw}: {cname} is the curve {src} but {pname} is 0, so "
                "LS-DYNA's mu*A product is ZERO and the bag does NOT vent. No "
                "vent hole is emitted. (A 0 here is easy to leave by "
                f"accident: state {pname} if the curve was meant to open a "
                "real orifice.)")
            ab.avent = 0.0
            src = 0
        else:
            ab.avent = partner
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
# Batch 2 — the multi-gas inflators
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_gas_species(state: ConversionState, ab: Airbag, sp: GasSpecies,
                         add_curve) -> None:
    """One species → one ``/MAT/GAS/MOLE`` and, when it has a mass-flow curve,
    one ``/PROP/INJECT1`` row.

    **The Cp coefficients are copied 1:1 and are NOT divided by MW.** That is
    the whole difference between this and batch 1's
    ``*AIRBAG_SIMPLE_AIRBAG_MODEL`` path, and it is a divide-once rule:
    LS-DYNA's A/B/C are molar on both keywords, but batch 1's target
    ``/MAT/GAS/MASS`` wants a mass-specific Cp (so the CONVERTER divides,
    ``_make_monvols``: ``cpa = ab.hc_a / mw``) while ``/MAT/GAS/MOLE`` wants
    the molar one and the SOLVER divides (``hm_read_matgas.F:295-302``:
    ``CPA = CPA / MW * FAC``). Dividing here as well would state a Cp smaller
    by a factor MW — on a 0.028 kg/mol gas, a factor of 36.

    ``Cpd``/``Cpe``/``Cpf`` are 0: LS-DYNA's hybrid inflator card carries only
    the constant, linear and quadratic terms, so the Shomate ``E/T^2`` and the
    quartic ``F*T^4`` of the Radioss polynomial have no source.
    """
    kw = f"*{ab.keyword}"
    sp.mat_id = state.next_mat_id()
    if sp.mw <= 0.0:
        state.warn(
            f"{kw}: gas {sp.index} states MW={sp.mw:g}. /MAT/GAS/MOLE needs "
            "MW > 0 (starter ERROR 710) — it divides the whole Cp polynomial "
            "by it (hm_read_matgas.F:295) and then forms Cv = Cp - R/MW — so "
            "the starter refuses the gas and the deck with it. Give the "
            "species' molecular weight in the DECK's mass-per-mole unit: on an "
            "Mg/mm/s deck air is 2.896e-05, not the SI 0.02896.")
    if sp.lcid_m > 0 and sp.lcid_m not in state.curves:
        state.warn(
            f"{kw}: gas {sp.index} names inflator mass-flow curve "
            f"{sp.lcid_m}, which this deck does not define. The "
            "/PROP/INJECT1 row references it anyway; a missing injector "
            "function is starter ERROR 708 and the deck is refused.")
    if sp.lcid_t > 0 and sp.lcid_t not in state.curves:
        state.warn(
            f"{kw}: gas {sp.index} names inflator temperature curve "
            f"{sp.lcid_t}, which this deck does not define (starter "
            "ERROR 708).")
    if sp.lcid_m < 0 or sp.lcid_t < 0:
        state.warn(
            f"{kw}: gas {sp.index} states a NEGATIVE inflator curve id "
            f"(LCIDM={sp.lcid_m}, LCIDT={sp.lcid_t}), which is LS-DYNA's "
            "request for CUBIC-SPLINE interpolation of |id| rather than the "
            "piecewise-linear default. Radioss /FUNCT is piecewise linear "
            "only, so |id| is referenced and the interpolation order is "
            "DROPPED — a difference that shows up between the curve's own "
            "points, not at them.")
    sp.fun_m = abs(sp.lcid_m)
    if sp.lcid_t != 0:
        sp.fun_t = abs(sp.lcid_t)
    else:
        # Radioss wants the injected temperature as a FUNCTION of time and
        # LS-DYNA left it blank. A flat curve at the ambient temperature is
        # the only defensible reading, and it is named so the deck says so.
        # (fun_ID_T = 0 would make the starter take Fscale_T as a constant —
        # which this converter writes as 0, i.e. injection at absolute zero.)
        t_inj = ab.t_ext if ab.t_ext > 0.0 else 295.0
        fid = state.next_curve_id()
        add_curve(state, fid,
                  f"MONVOL_{ab.monvol_id}_INJECT_T_GAS_{sp.index}",
                  [(0.0, t_inj), (1.0, t_inj)])
        sp.fun_t = fid
        if sp.lcid_m > 0:
            state.warn(
                f"{kw}: gas {sp.index} gives an inflator mass-flow curve but "
                f"no temperature curve (LCIDT=0). /PROP/INJECT1 has no "
                "constant-temperature column that this conversion can use "
                "(Fscale_T is written 0 and the starter promotes it to 1 K, "
                f"not to a temperature), so a flat function at {t_inj:g} — "
                "the card's ambient temperature — is synthesized as function "
                f"{fid}. State LCIDT if the inflator gas is hotter than "
                "ambient, which it always is.")
    sp.injected = sp.lcid_m != 0


def _resolve_gas_mixture(state: ConversionState, ab: Airbag,
                         initial: List[GasSpecies]):
    """``(MW, Cpa, Cpb, Cpc)`` of the bag's INITIAL gas fill — one
    ``/MAT/GAS/MOLE`` standing for the mixture named by the ``INITM`` column.

    LS-DYNA's ``INITM`` is a **mass fraction** ("Initial mass fraction of gas
    component present in the airbag, prior to injection… The sum of INITM of
    all gas components should be 1.0", Vol I R17 p.3-50) while ``MW`` and
    ``A``/``B``/``C`` are **molar**. Averaging molar quantities with mass
    weights is not a mixture rule, so the fractions are converted first::

        x_i = (w_i / M_i) / sum_j (w_j / M_j)        mole fractions
        M   = sum_i x_i M_i  =  1 / sum_i (w_i / M_i)
        Cp  = sum_i x_i Cp_i                          (molar)

    which is exact, and lands where it should: ``/MAT/GAS/MOLE`` divides the
    result by M, giving ``sum_i w_i * (Cp_i / M_i)`` — the mass-fraction
    average of the mass-specific heat capacities, which is what Dalton's law
    says a mixture's ``c_p`` is.

    **dyna2rad does the arithmetic mean instead** — ``convertcontrolvols.cxx
    :2494-2497`` accumulates ``radMW += MW_i*INITM_i/sum(INITM)`` and the same
    for A/B/C — and then feeds it to the same ``/MAT/GAS/MOLE`` divide. The two
    agree only when every species has the same molecular weight. For a
    50/50-by-mass argon/helium fill (M = 0.03995 / 0.004) d2r states
    M = 0.0220 where the mixture's is 0.00727, a factor of 3.
    d2r also gates on ``INITM >= 1.0``, so a species carrying its documented
    fraction — 0.79 nitrogen, 0.21 oxygen — contributes to NEITHER the mixture
    NOR an injector, and vanishes from the deck entirely.
    """
    kw = f"*{ab.keyword}"
    usable = [s for s in initial if s.mw > 0.0]
    dropped = [s.index for s in initial if s.mw <= 0.0]
    if dropped:
        state.warn(
            f"{kw}: gas(es) {dropped} carry an initial mass fraction but no "
            "usable MW, so they cannot enter the initial-mixture average "
            "(every term of it divides by the molecular weight). The bag's "
            "initial fill is built from the remaining species only.")
    if not usable:
        return None
    inv = sum(s.initm / s.mw for s in usable)
    if inv <= 0.0:                                       # pragma: no cover
        return None
    mw = 1.0 / inv
    xs = [(s, (s.initm / s.mw) / inv) for s in usable]
    return (mw,
            sum(x * s.hc_a for s, x in xs),
            sum(x * s.hc_b for s, x in xs),
            sum(x * s.hc_c for s, x in xs))


def _resolve_species_block(state: ConversionState, ab: Airbag,
                           add_curve) -> None:
    """The gas half of a multi-species inflator: one ``/MAT/GAS/MOLE`` per
    species, one more for the initial mixture, and the ``/PROP/INJECT1`` that
    ties the injected ones to their curves.

    Shared by ``*AIRBAG_HYBRID`` and ``*AIRBAG_PARTICLE`` because the two
    state the same physics in the same columns — species, molar Cp, one
    mass-flow-rate curve and one temperature curve each. Only where the
    INITIAL fill comes from differs, and that is decided by the caller before
    this runs (``INITM`` on HYBRID, the ``IAIR`` air card on PARTICLE).
    """
    kw = f"*{ab.keyword}"
    for sp in ab.species:
        _resolve_gas_species(state, ab, sp, add_curve)
    injected = [s for s in ab.species if s.injected]
    if not injected:
        state.warn(
            f"{kw}: not one of the {len(ab.species)} gas species gives an "
            "inflator mass-flow curve, so the bag receives NO GAS at all — it "
            "holds its initial fill and the monitored volume is inert. No "
            "/PROP/INJECT1 is emitted (an injector with N_gases = 0 is starter "
            "ERROR 696). Give LCIDM/LCMi on at least one species.")
        return
    ab.inject_prop_id = state.next_prop_id()
    if len(injected) > 100:
        state.warn(
            f"{kw}: {len(injected)} injected gas species. /PROP/INJECT1 "
            "accepts 1 to 100 (starter ERROR 696) and LS-DYNA's own limit is "
            "17, so this card is beyond both. It is emitted as written.")


def _resolve_vent_surface(state: ConversionState, ab: Airbag, vent: AirbagVent,
                          pids: List[int], what: str) -> None:
    """Give one vent hole a NAMED ``/SURF``, built from its own parts and
    screened against the bag's.

    Three rules, all of them enforced here rather than discovered by the
    starter:

    1. **Shell-backed.** ``surf_IDv`` must resolve to shells —
       ``hm_read_monvol_type9.F`` answers ``ERROR 330`` for a segment-based
       surface and ``ERROR 532`` for an undefined one. ``_eids_of_pids``
       applies the same screen the external surface gets.
    2. **A SUBSET of the bag surface.** A vent hole is a patch OF the bag: the
       engine computes the outflow area as ``AOUT = Avent * <current area of
       surf_IDv>`` and applies the pressure to the bag's own segments, so a
       vent part outside ``surf_IDex`` scales the leak by an area that is not
       part of the cavity. Radioss states the same rule explicitly for the
       communicating-surface case — ``ERROR 902``, *"COMMUNICATING SURFACE ID
       = %d IS NOT INCLUDED INTO AIRBAG SURFACE ID = %d"* — and elements
       outside the bag are dropped here with that quoted.
    3. **Shared elements are REQUIRED, not double counting.** The vent's
       elements are the same elements as the bag's, in a second ``/SURF``.
       ``surf_IDex`` measures the VOLUME; ``surf_IDv`` scales an AREA. Nothing
       is summed across the two, and rule 2 is only satisfiable by sharing.

    A vent whose surface resolves to nothing keeps ``surf_id = 0``, which is
    the whole-bag mode — so the caller must re-read ``Avent`` as an absolute
    area, and does.
    """
    ref = f"*{ab.keyword} (SID {ab.sid})"
    vent.pids = list(pids)
    eids = _eids_of_pids(state, pids, ref, what)
    bag = set(ab.quad_eids) | set(ab.tri_eids)
    inside = [e for e in eids if e in bag]
    outside = [e for e in eids if e not in bag]
    if outside:
        state.warn(
            f"{ref}: {len(outside)} of {len(eids)} shell element(s) named by "
            f"{what} are NOT part of the monitored volume's own external "
            "surface. A vent surface has to be a patch OF the bag — the "
            "engine scales the outflow area by that surface's current area "
            "while applying the pressure to the bag's segments — and Radioss "
            "states the rule outright for the communicating-surface case "
            "(ERROR 902, \"IS NOT INCLUDED INTO AIRBAG SURFACE ID\"). Those "
            "elements are LEFT OUT of the vent surface; the vent still opens "
            "over the ones that do belong. Check that the vent part is really "
            "one of the bag's parts.")
    if not inside:
        state.warn(
            f"{ref}: {what} resolves to no shell element that belongs to the "
            "bag, so the vent hole gets NO named surface and falls back to "
            "whole-bag mode — in which Avent is read as an absolute AREA "
            "rather than as a scale factor on a surface. The vent is emitted "
            "with Avent = 0, i.e. sealed, rather than with a scale factor "
            "the starter would multiply by the wrong thing.")
        vent.surf_id = 0
        vent.avent = 0.0
        return
    vent.quad_eids, vent.tri_eids = _split_shell_eids_by_topology(state, inside)
    vent.surf_id = state.next_id()


def _gauge_shifted_curve(state: ConversionState, ab: Airbag, add_curve,
                         src: int, role: str) -> int:
    """A copy of an ABSOLUTE-pressure curve with every abscissa moved to the
    GAUGE pressure Radioss's ``fct_IDP`` is a function of, or ``src`` when no
    shift is needed.

    ``engine/source/airbag/airbagb1.F`` evaluates a vent's pressure function as
    ``GET_U_FUNC(IPORP, (P - PEXT)*SCALP, …)`` — the only absolute-pressure
    path in the whole engine is ``/MAT/FABRIC`` with ``ILEAKAGE == 2``. So a
    LS-DYNA curve documented against absolute pressure has to be shifted by
    ``-Pext`` before it can be referenced, and this is the single most
    unit-sensitive number in the batch: if PE is stated in a different pressure
    unit from the curve, the whole vent law slides.
    """
    kw = f"*{ab.keyword}"
    if src <= 0:
        return 0
    curve = state.curves.get(src)
    if curve is None or not curve.pts:
        state.warn(
            f"{kw}: the {role} curve {src} is not defined in this deck. The "
            "vent block references it anyway; a missing porosity function is "
            "starter ERROR 332 and the deck is refused.")
        return src
    if ab.pe == 0.0:
        return src
    fid = state.next_curve_id()
    add_curve(state, fid, f"MONVOL_{ab.monvol_id}_{role}_GAUGE",
              [(x - ab.pe, y) for x, y in curve.pts])
    state.warn(
        f"{kw}: the {role} curve {src} is a function of ABSOLUTE pressure "
        "(LS-DYNA) while the Radioss vent's fct_IDP is a function of the "
        f"GAUGE pressure P - Pext. Curve {fid} is a copy with every abscissa "
        f"shifted by -Pext = {-ab.pe:g}. Check that the ambient pressure "
        "really is in the deck's pressure unit — this shift is the most "
        "unit-sensitive number in the conversion.")
    return fid


def _resolve_hybrid_vents(state: ConversionState, ab: Airbag,
                          add_curve) -> None:
    """``*AIRBAG_HYBRID`` card 4 + card 5 → the vent-hole blocks.

    Card 4 states TWO leak paths in eight columns: the ORIFICE
    (``C23 LCC23 A23 LCA23``) and the FABRIC POROSITY
    (``CP23 LCP23 AP23 LCAP23``). Both become vent holes.

    **Why the porosity is a vent hole and not a porous surface.** Radioss has
    a ``Nporsurf`` block that looks like the natural target, and dyna2rad uses
    it (``Iformps = 0``, Bernoulli). Two things argue against copying that.
    The vent-hole sub-block is the one whose layout is pinned as identical
    across the three monitored volumes this batch writes —
    ``venthole1.cfg:17`` calls itself *"SUBOBJECT of AIRBAG1, COMMU1 AND
    FVMBAG1"* — while the porous block's is documented only for
    ``/MONVOL/COMMU1`` (type 9), and there ``hm_read_monvol_type9.F`` then
    DISCARDS half of what d2r writes into it::

        IF (IFVENT(NVENTHOLES + II) == 0) THEN
           IF (CLEAK(...) > ZERO) IPORT(...) = 0
           IF (AVENT(...) > ZERO) IPORA(...) = 0
           IPVENT(...) = 0
           IBLOCKAGE(...) = 0

    — MEASURED in the card-format probe: a porous surface written with
    ``surf_IDps=8005, Iblockage=1, fct_IDcps=106, fct_IDaps=108`` echoes back
    ``POROUS SURFACE ID = 0`` and both functions 0. Second, ``CP23`` is a
    dimensionless orifice coefficient and ``AP23`` an area, so their PRODUCT
    is an effective leak area — exactly the shape of batch 1's ``MU*AREA``,
    and exactly what ``Avent`` means with no named surface. Stating it as a
    second vent hole uses only pinned layout and only arithmetic that is
    already validated. ``Nporsurf`` is therefore 0 on every batch-2 card.

    **``OPT`` is the gate d2r never reads.** LS-DYNA zeroes CP23/LCP23/AP23/
    LCAP23 whenever ``OPT != 0`` and takes the porosity from ``*MAT_FABRIC``'s
    FLC/FAC instead (Vol I R17 p.3-48, and the reader cfg mirrors it at
    ``subobj_airbag_hybrid.cfg:43``). d2r converts those four columns
    regardless — ``grep LSD_OPTHybrid`` over the whole of
    ``convertcontrolvols.cxx`` returns nothing — so an ``OPT != 0`` deck gets a
    porosity LS-DYNA itself deleted.
    """
    kw = f"*{ab.keyword}"
    # ── the vent orifice ────────────────────────────────────────────────
    c23 = ab.c23
    fct_t = 0
    if c23 != 0.0 and ab.lcc23 != 0:
        state.warn(
            f"{kw}: card 4 states BOTH C23={c23:g} and LCC23={ab.lcc23}. "
            "LS-DYNA's rule is that a non-zero C23 overrides the curve, so "
            "the constant is used and the curve is DROPPED. (dyna2rad does "
            "the opposite — convertcontrolvols.cxx:2801 forces C23 to 1.0 and "
            "keeps the curve — which silently discards the orifice "
            "coefficient the deck states.)")
    elif c23 == 0.0 and ab.lcc23 > 0:
        # A vent coefficient vs TIME. fct_IDt is exactly that slot, and with
        # no injector sensor its abscissa is absolute time (see ITTF_NO_SHIFT).
        fct_t = ab.lcc23
        c23 = 1.0
        if ab.lcc23 not in state.curves:
            state.warn(
                f"{kw}: LCC23={ab.lcc23} names a *DEFINE_CURVE this deck does "
                "not define. The vent references it anyway; a missing vent "
                "function is starter ERROR 331 and the deck is refused.")
    elif c23 == 0.0 and ab.lcc23 < 0:
        state.warn(
            f"{kw}: LCC23={ab.lcc23} is negative, which in LS-DYNA makes "
            f"|LCC23| = {-ab.lcc23} a curve of the vent orifice coefficient "
            "against the RELATIVE pressure ratio P_ambient/P_bag (Anagonye & "
            "Wang 1999). A Radioss vent function takes the gauge pressure "
            "difference P - Pext, not a ratio, and the two cannot be mapped "
            "point by point without knowing P_bag. The curve is DROPPED and "
            "the orifice coefficient defaults to 1. (dyna2rad drops it too, "
            "silently — convertcontrolvols.cxx:2809-2818.)")
        c23 = 1.0

    vents: List[AirbagVent] = []
    a23_curve = _gauge_shifted_curve(state, ab, add_curve, ab.lca23, "LCA23") \
        if ab.lca23 > 0 else 0
    if ab.a23 < 0.0:
        # |A23| names a PART (LCA23 != -1) or a PART SET (LCA23 == -1), i.e.
        # the vent is a NAMED PATCH of the bag rather than a scalar area.
        # Avent is then a SCALE FACTOR on that surface's current area.
        v = AirbagVent(title="VENT_A23", avent=c23 if c23 != 0.0 else 1.0,
                       fct_t=fct_t, fct_p=a23_curve)
        is_set = ab.lca23 == -1
        pids = _part_scope_pids(state, int(-ab.a23), is_set,
                                f"*{ab.keyword} (SID {ab.sid})",
                                f"A23={ab.a23:g} (a negative A23 names a "
                                + ("*SET_PART" if is_set else "*PART") + ")")
        _resolve_vent_surface(state, ab, v, pids, "the A23 vent part(s)")
        vents.append(v)
    elif ab.a23 > 0.0 or fct_t or a23_curve:
        # A scalar whole-bag orifice: Avent is the ABSOLUTE area A23*C23.
        vents.append(AirbagVent(
            title="VENT_A23", avent=ab.a23 * (c23 if c23 != 0.0 else 1.0),
            fct_t=fct_t, fct_p=a23_curve))

    # ── the fabric porosity ─────────────────────────────────────────────
    poro_stated = (ab.cp23 != 0.0 or ab.lcp23 != 0
                   or ab.ap23 != 0.0 or ab.lcap23 != 0)
    if ab.opt != 0 and poro_stated:
        state.warn(
            f"{kw}: OPT={ab.opt} on card 5, so LS-DYNA ITSELF zeroes CP23/"
            "LCP23/AP23/LCAP23 (Vol I R17 p.3-48) and takes the fabric "
            "porosity from *MAT_FABRIC's FLC/FAC instead. Those four columns "
            "are therefore IGNORED here as well — carrying them would emit a "
            "leak path the LS-DYNA run does not have. The *MAT_FABRIC "
            "leakage path itself is NOT converted by this batch, so the bag "
            "loses its fabric porosity and will over-pressurise relative to "
            "LS-DYNA. (dyna2rad never reads OPT at all and converts CP23/AP23 "
            "regardless, which is the opposite error.)")
    elif ab.opt != 0:
        state.warn(
            f"{kw}: OPT={ab.opt} selects a fabric-venting formula "
            + {1: "Wang-Nefske", 2: "Wang-Nefske with contact blockage",
               3: "Graefe-Krummheuer-Siejak",
               4: "Graefe-Krummheuer-Siejak with contact blockage",
               5: "porous-media flow", 6: "porous-media flow with blockage",
               7: "gas-volume-outflow vs absolute pressure",
               8: "gas-volume-outflow vs absolute pressure with blockage",
               }.get(ab.opt, "outside the documented 1-8 range")
            + ", whose leakage data lives on *MAT_FABRIC (FLC/FAC/FVOPT). "
            "This batch does not convert the *MAT_FABRIC leakage path, so "
            "nothing is emitted for it and the bag does not leak through its "
            "fabric.")
    elif poro_stated:
        cp = ab.cp23
        p_fct_t = 0
        if cp != 0.0 and ab.lcp23 > 0:
            state.warn(
                f"{kw}: card 4 states BOTH CP23={cp:g} and LCP23={ab.lcp23}; "
                "the constant overrides and the curve is DROPPED, the same "
                "rule LS-DYNA applies to C23/LCC23.")
        elif cp == 0.0 and ab.lcp23 > 0:
            p_fct_t = ab.lcp23
            cp = 1.0
        elif cp == 0.0:
            cp = 1.0
        p_fct_p = _gauge_shifted_curve(state, ab, add_curve, ab.lcap23,
                                       "LCAP23") if ab.lcap23 > 0 else 0
        vents.append(AirbagVent(
            title="VENT_FABRIC", avent=ab.ap23 * cp,
            fct_t=p_fct_t, fct_p=p_fct_p))
        state.warn(
            f"{kw}: the fabric porosity (CP23={ab.cp23:g}, AP23={ab.ap23:g}) "
            f"is emitted as a SECOND VENT HOLE with Avent = CP23*AP23 = "
            f"{ab.ap23 * cp:g}, not as a /MONVOL porous surface. CP23 is a "
            "dimensionless orifice coefficient and AP23 an area, so their "
            "product is an effective leak area — which is exactly what Avent "
            "means with no named surface — and the vent-hole sub-block is the "
            "one whose layout is identical on AIRBAG1, COMMU1 and FVMBAG1 "
            "(venthole1.cfg:17). The porous block would additionally have "
            "half its columns discarded by the type-9 reader "
            "(hm_read_monvol_type9.F, IFVENT == 0 branch), MEASURED.")

    # ── PVENT: the pressure the vent OPENS at ───────────────────────────
    #
    # It gates the ORIFICE only, not the fabric porosity. PVENT sits on card 5
    # beside OPT and VNTOPT — the vent-formula and vent-area options — and
    # "the pressure defining the start of the venting" describes a flap that
    # bursts, which a woven fabric's permeability is not: a weave leaks
    # whenever there is a pressure difference across it. Putting the threshold
    # on both paths would SEAL a leak LS-DYNA has open from t=0.
    orifice = [v for v in vents if v.title == "VENT_A23"]
    if ab.pvent != 0.0 and orifice:
        for v in orifice:
            v.dpdef = ab.pvent
            # Tstart has to be pushed out of reach, because airbagb1.F:290 ORs
            # the two opening criteria:
            #     IF(IDEF==0 .AND. TT>TVENT .AND. TT<TSTOPE) IDEF=1
            # With Tstart = 0 the TIME criterion fires on the first cycle and
            # the vent is open before dPdef is ever tested — which is why
            # dyna2rad's dPdef = 1e30 does NOT seal a vent, and why writing
            # PVENT into dPdef alone would not open one either.
            v.tstart = _VENT_NEVER
        state.warn(
            f"{kw}: PVENT={ab.pvent:g} is the GAUGE pressure at which venting "
            f"begins. It is emitted as the vent's dPdef with Tstart = "
            f"{_VENT_NEVER:g}: the engine ORs the time and pressure opening "
            "criteria (airbagb1.F:290), so a Tstart of 0 would open the hole "
            "on the first cycle and PVENT would never be tested. Once open, "
            "the hole stays open — the same latching LS-DYNA does. It is put "
            "on the ORIFICE only: the fabric porosity, if any, leaks from "
            "t=0, because a weave's permeability is not a flap that bursts "
            "and sealing it until PVENT would close a leak LS-DYNA has open.")
    elif ab.pvent != 0.0:
        state.warn(
            f"{kw}: PVENT={ab.pvent:g} states a venting-onset pressure but "
            "card 4 defines no vent orifice (C23/A23), so there is no vent "
            "hole to put it on. Any fabric porosity still leaks from t=0.")
    ab.vents = vents
    if not vents:
        state.warn(
            f"{kw}: card 4 gives neither a vent orifice (C23/A23) nor a "
            "fabric porosity (CP23/AP23), so this bag has NO VENT at all. "
            "That matches the deck; a sealed bag reaches a much higher "
            "pressure than a vented one, so check it is intended.")


def _warn_hybrid_dropped(state: ConversionState, ab: Airbag) -> None:
    """Every ``*AIRBAG_HYBRID`` field with no Radioss expression, by name and
    by value — including the ones dyna2rad drops in silence."""
    kw = f"*{ab.keyword}"
    if ab.atmosd != 0.0:
        state.warn(
            f"{kw}: ATMOSD={ab.atmosd:g} (ambient density) has no "
            "/MONVOL/AIRBAG1 column and is DROPPED. The starter derives the "
            "bag's initial gas mass from the ideal-gas law instead, "
            "MI = Pext*(V+Veps)/(R/MW * T0), so the initial state is set by "
            "ATMOSP/ATMOST and the mixture's MW rather than by this number.")
    if ab.gc != 0.0:
        r_work = _radioss_gas_constant(state)
        state.warn(
            f"{kw}: GC={ab.gc:g} (the deck's universal gas constant) is "
            "DROPPED — Radioss uses its OWN, rescaled into the /BEGIN unit "
            "system (hm_read_matgas.F:293)"
            + (f", which is {r_work:.6g} for "
               f"{state.units[0]}/{state.units[1]}/{state.units[2]}"
               if r_work is not None else "")
            + ". If GC is not that number in the deck's own units, the whole "
            "gas is stated in a different unit system from the mesh and every "
            "Cv the starter derives will be wrong, with no diagnostic.")
    if ab.cc not in (0.0, 1.0):
        state.warn(
            f"{kw}: CC={ab.cc:g} (the conversion constant) has no Radioss "
            "counterpart and is DROPPED. It multiplies LS-DYNA's own "
            "gas-constant arithmetic, so a value other than 1 means the gas "
            "constants are not in the deck's unit system.")
    if ab.hconv < 0.0:
        state.warn(
            f"{kw}: HCONV={ab.hconv:g} is negative, so |HCONV| is a load "
            "curve giving the convective heat-transfer coefficient against "
            "time. /MONVOL's Hconv is a single constant with no function "
            "slot, so the curve is DROPPED and Hconv is written 0 — the bag "
            "loses no heat to its surroundings and runs hotter, which matters "
            "on a long-duration bag and not on a 100 ms deployment.")
    if ab.lcefr:
        state.warn(
            f"{kw}: LCEFR={ab.lcefr} gives the vent EXIT FLOW RATE (a mass "
            "per unit time) against the bag's gauge pressure. A Radioss vent "
            "hole takes an AREA, not a mass flow — the engine derives the "
            "flow from the Wang-Nefske isentropic expression itself — so the "
            "curve cannot be carried and is DROPPED. The nearest expression "
            "is a Chemkin porous surface (Iformps=2), which wants an outflow "
            "VELOCITY; restate the curve as one if it is load-bearing. "
            "(dyna2rad drops it silently.)")
    if ab.lcidm0:
        state.warn(
            f"{kw}: LCIDM0={ab.lcidm0} gives the TOTAL inflator mass inflow "
            "rate, which changes the meaning of every per-gas card: LCIDM "
            "becomes a MOLAR FRACTION curve and INITM an initial molar ratio "
            "(Vol I R17 p.3-48). Radioss states exactly that with "
            "/PROP/INJECT2 (one common mass-flow and temperature curve plus a "
            "per-gas molar fraction), which this batch does not emit. The "
            "per-gas curves are converted as if they were mass flows, which "
            "they are not — this bag's inflator is WRONG by the ratio of the "
            "total flow to each fraction. Split LCIDM0 into per-gas mass-flow "
            "curves, or convert this bag by hand.")
    if ab.vntopt:
        state.warn(
            f"{kw}: VNTOPT={ab.vntopt} selects an alternative definition of "
            "the vent AREA (eroded area included, or the A23<0 part-area "
            "variants). Radioss computes the vent area from surf_IDv and "
            "Avent alone, so the option is DROPPED and the area is the one "
            "card 4 states.")
    if ab.rbid:
        # _warn_card1_extras already names RBID; this adds what it costs HERE.
        state.warn(
            f"{kw}: with RBID={ab.rbid} the inflator is armed by a sensor, "
            "and this batch writes sens_ID = 0 on the injector, so the "
            "hybrid inflator starts at t=0. On a hybrid deck that is usually "
            "the whole timing of the deployment.")
    fm = [s.index for s in ab.species if s.fmass != 0.0]
    if fm:
        state.warn(
            f"{kw}: gas(es) {fm} state FMASS (the fraction of additional "
            "ASPIRATED mass drawn in with the inflator jet). Radioss's "
            "injector adds only the mass its own curve states, so FMASS is "
            "DROPPED and the bag fills with less gas than LS-DYNA's. "
            "(dyna2rad never reads the FMASS card at all.)")
    if ab.jetting:
        _warn_hybrid_jetting(state, ab)


def _warn_hybrid_jetting(state: ConversionState, ab: Airbag) -> None:
    """``_JETTING`` — every field gets a verdict, mapped or named-and-dropped.

    Radioss's jet block is NODE-based: ``Ijet``, ``node_ID1`` (the jet focal
    point), ``node_ID2`` (a point on the axis), ``node_ID3`` (0 for a CONICAL
    jet, non-zero for a DIHEDRAL one) and three pressure functions of time, of
    the off-axis angle and of the distance. LS-DYNA states the same geometry
    twice over — as coordinates AND, optionally, as nodes that OVERRIDE them —
    so the node form maps 1:1 and the coordinate-only form does not map at
    all.

    ``Ijet`` is written 1 and never more. The cfg gates the jet card on
    ``if(ABG_Ijet == 1)`` while the reader gates it on ``IF (IJET(II) > 0)``,
    so a 2 shifts the whole block by one line: MEASURED on a probe, ``Ijet=2``
    produced ``WARNING 100213`` on the injector line and then ``ERROR 100103``
    ("Cannot read an integer value") on the vent card below it.
    """
    kw = f"*{ab.keyword}"
    if ab.jet_n1 and ab.jet_n2:
        shape = "DIHEDRAL" if ab.jet_n3 else "CONICAL"
        state.warn(
            f"{kw}: _JETTING is converted — node_ID1={ab.jet_n1}, "
            f"node_ID2={ab.jet_n2}, node_ID3={ab.jet_n3} give Radioss a "
            f"{shape} jet (node_ID3 = 0 is conical, non-zero dihedral, "
            "hm_read_monvol_type9.F formats 1460/1461). LS-DYNA's NODE1/NODE2/"
            "NODE3 OVERRIDE the XJFP/XJVH/XSJFP coordinates on the same "
            "cards, so the coordinates are not needed and are not used.")
    else:
        state.warn(
            f"{kw}: _JETTING states the jet geometry as COORDINATES "
            f"(XJFP={ab.jet_fp}, XJVH={ab.jet_vh}, XSJFP={ab.jet_sfp}) and "
            "gives no NODE1/NODE2. Radioss's jet is defined by NODES only — "
            "node_ID1 the focal point, node_ID2 a point on the axis — and "
            "this converter does not create nodes, so the jet is DROPPED and "
            "the bag is loaded by UNIFORM PRESSURE. The directional loading "
            "of the deployment is the whole point of a jetting card, so this "
            "is a real loss: add *NODE at the focal point and on the axis and "
            "name them in NODE1/NODE2 to convert it. (dyna2rad drops the "
            "entire jetting block either way, silently.)")
    if ab.jet_ca != 0.0:
        state.warn(
            f"{kw}: CA={ab.jet_ca:g} is the jet cone "
            + ("angle in RADIANS" if ab.jet_ca > 0 else
               f"angle as time curve {-ab.jet_ca:g}")
            + ". Radioss states the angular shape as a FUNCTION of the "
            "off-axis angle (fct_IDPTheta) rather than as a half-angle, and "
            "a single number is not one — a cone angle says where the jet "
            "stops, a function says how the pressure falls off inside it. It "
            "is DROPPED and the jet carries no angular decay.")
    if ab.jet_beta != 0.0:
        state.warn(
            f"{kw}: BETA={ab.jet_beta:g} (the Bernoulli efficiency factor of "
            "the jet) has no Radioss column — the three FscaleP* factors "
            "scale the three jet functions, and with no functions there is "
            "nothing to scale. DROPPED.")
    if ab.jet_psid:
        state.warn(
            f"{kw}: PSID={ab.jet_psid} restricts the jet pressure to one part "
            "set. Radioss applies the jet to whichever of the bag's segments "
            "fall inside the cone, with no part filter, so PSID is DROPPED "
            "and the jet reaches every part of the bag it geometrically "
            "covers.")
    if ab.jet_nreact:
        state.warn(
            f"{kw}: NREACT={ab.jet_nreact} (_CM: the node the jet's REACTION "
            "force is applied to) has no Radioss counterpart and is DROPPED. "
            "The bag's jet pushes on the fabric but nothing pushes back on "
            "the inflator housing.")


def _resolve_hybrid(state: ConversionState, ab: Airbag, add_curve) -> None:
    """``*AIRBAG_HYBRID`` → ``/MONVOL/AIRBAG1`` with ``N_gases > 1``.

    **Why AIRBAG1 and not COMMU1.** dyna2rad writes ``/MONVOL/COMMU1``
    (``convertcontrolvols.cxx:2428``) and gives no reason anywhere in the
    tree. Reading the two card definitions against each other, COMMU1 has
    exactly one capability AIRBAG1 lacks — the communicating-bag block — and
    d2r never uses it:

    * *"The one genuine feature COMMU1 has that AIRBAG1 lacks is the
      communicating-bag block* (``monvol_commu1.cfg:120-131``). *d2r never
      writes NBAG or any communication row — the block is emitted empty. So
      COMMU1 is used here as 'AIRBAG1 with flat arrays', not for
      communication."*
    * ``N_gases`` is not a reason: it lives on ``/PROP/INJECT1``, which both
      monitored volumes reference identically.
    * Vents are not a reason: ``venthole1.cfg:17`` calls itself *"SUBOBJECT of
      AIRBAG1, COMMU1 AND FVMBAG1"* — one layout, one meaning.
    * Jetting is not a reason: ``ABG_Ijet``/``ABG_N1..N3`` exist on AIRBAG1
      via ``injector1.cfg:24-29`` and on COMMU1 via ``monvol_commu1.cfg:47-51``,
      *"d2r sets neither"*.
    * Porosity is not a reason: *"both have ``Nporsurf``"*.

    And COMMU1 with an empty block is not even well-formed:
    ``monvol_commu1.cfg:255-259`` carries ``CHECK(COMMON) { NBAG > 0; NBAG <=
    20; }``. The two share the whole solver anyway — ``monvol0.F`` dispatches
    ``ITYP==7 .OR. ITYP==9`` to the same ``AIRBAGA1``/``AIRBAGB1`` pair — so
    the promotion is loss-free in the direction that matters, and it is done
    the moment an ``*AIRBAG_INTERACTION`` gives the ``Nbag`` block something to
    hold (``_resolve_airbag_interactions``). One further consequence: d2r's
    COMMU1 bags get NO ``/TH/MONV`` at all, because
    ``p_CreateTHMonVolForDBAbstat`` runs at ``ConvertEntities():47``, before
    ``ConvertAirbagHybrid`` at ``:53``, so its ``SelectionRead`` cannot see
    them. On AIRBAG1 the batch-1 time-history table already applies.
    """
    kw = f"*{ab.keyword}"
    initial = [s for s in ab.species if s.initm != 0.0]
    tot = sum(s.initm for s in initial)
    if initial and abs(tot - 1.0) > 1e-6 and tot > 0.0:
        state.warn(
            f"{kw}: the INITM column sums to {tot:g}, not to 1. LS-DYNA reads "
            "INITM as a MASS FRACTION of the gas already in the bag at t=0 "
            "(\"The sum of INITM of all gas components should be 1.0\", "
            "Vol I R17 p.3-50), and the initial mixture is built from the "
            "fractions as given — normalised by their own sum, so a sum other "
            "than 1 changes nothing about the mixture's composition but says "
            "the card was not written as a fraction. Check it.")
    mix = _resolve_gas_mixture(state, ab, initial) if initial else None
    if mix is None:
        if ab.species:
            state.warn(
                f"{kw}: no gas species carries a non-zero INITM, so the deck "
                "states no initial bag fill. /MONVOL/AIRBAG1 REQUIRES a "
                "mat_ID (starter ERROR 699 without one) and derives the "
                "initial gas mass from it, so gas 1's properties are used as "
                "the fill. NGAS is documented to include the initial air "
                "(Vol I R17 p.3-48) — give that species its INITM. "
                "(dyna2rad leaves mat_ID unset here, which the starter "
                "refuses.)")
            s0 = ab.species[0]
            mix = (s0.mw, s0.hc_a, s0.hc_b, s0.hc_c)
        else:
            ab.dropped = True
            state.warn(
                f"{kw}: the card declares no gas species at all, so there is "
                "no /MAT/GAS to fill the bag with and no /PROP/INJECT1 to "
                "inflate it. NO /MONVOL is emitted.")
            return
    ab.gas_mat_id = state.next_mat_id()
    ab.gas_mat_kind = "MOLE"
    ab.mw, ab.hc_a, ab.hc_b, ab.hc_c = mix
    _resolve_species_block(state, ab, add_curve)
    if ab.pe == 0.0:
        state.warn(
            f"{kw}: ATMOSP is 0, so the bag has no ambient pressure. Radioss "
            "reads a blank Pext as a REQUEST FOR ONE ATMOSPHERE — "
            "hm_read_monvol_type7.F:417-418 substitutes 101325 Pa rescaled "
            "into the /BEGIN unit system, :421 then sets PINI = PEXT and :536 "
            "derives the initial gas mass MI = PINI*(VOL+VEPS)/(RMWI*TI) from "
            "it. So the converted bag both pushes P - 1 atm on the fabric and "
            "starts pre-filled at 1 atm, with 0 ERROR(S) either way. State "
            "ATMOSP explicitly.")
    if ab.atmost <= 0.0:
        state.warn(
            f"{kw}: ATMOST={ab.atmost:g} is the ambient temperature and "
            "Radioss uses it as both the bag's initial temperature and the "
            "reference the Hconv term loses heat to (RVOLU(25) is re-read by "
            "the engine as TEXT). A zero is replaced by the starter's own "
            "default of 295 K; state it in Kelvin.")
    _resolve_hybrid_vents(state, ab, add_curve)
    _warn_hybrid_dropped(state, ab)


# ─────────────────────────────────────────────────────────────────────────────
# Batch 2 — the corpuscular (CPM) inflator
# ─────────────────────────────────────────────────────────────────────────────

#: Every ``*AIRBAG_PARTICLE`` field that describes PARTICLES rather than gas,
#: with the physics each one carries. Reported ONCE per bag rather than one
#: warning per field, because they are all one fact: the corpuscular model is
#: replaced by a continuum one.
_CPM_ONLY_FIELDS = (
    ("NP", "np", "the number of particles the inflator gas is discretised "
     "into — a finite-volume bag has no particles"),
    ("BLOCK", "block", "how a contacting segment blocks particle outflow and "
     "porosity; the FV bag's blockage is the Iblockage column of a porous "
     "surface, which needs a fabric-leakage source this batch does not read"),
    ("NPDATA", "npdata", "per-part heat transfer and particle friction"),
    ("FRIC", "fric", "the particle-to-fabric friction factor, which is what "
     "makes a CPM bag deploy stiffly out of its fold"),
    ("IRPD", "irpd", "the particle-decomposition option"),
    ("VISFLG", "visflg", "which particle data is written to the d3plot"),
    ("TEND", "tend", "the time the inflator STOPS; the injector curves keep "
     "running past it if they carry data there"),
    ("NPAIR", "npair", "the particle count of the initial air"),
    ("NPRLX", "nprlx", "the initial-air relaxation cycle count"),
    ("CD_EXT", "cd_ext", "the external drag coefficient on escaped particles"),
)


def _warn_particle_cpm_fields(state: ConversionState, ab: Airbag) -> None:
    """The CPM-only columns, once, with what the substitution costs."""
    stated = [(name, getattr(ab, attr), why)
              for name, attr, why in _CPM_ONLY_FIELDS
              if getattr(ab, attr)]
    kw = f"*{ab.keyword}"
    state.warn(
        f"{kw}: the CORPUSCULAR PARTICLE METHOD is replaced by a CONTINUUM "
        "gas model. LS-DYNA tracks discrete molecules that carry momentum "
        "into the fabric one impact at a time; Radioss solves a "
        + ("finite-volume Euler field on a tetrahedral mesh of the bag's "
           "interior" if ab.radioss_type == "FVMBAG2" else
           "single uniform-pressure control volume")
        + ". The gas species, the inflator curves, the vents and the "
        "thermodynamics carry over exactly; the EARLY deployment does not — a "
        "CPM bag punches out of its fold with directed particle momentum "
        "before any pressure field exists, and neither Radioss model has "
        "that. Expect a softer, more symmetric early unfolding."
        + (" The particle-only inputs stated on this card and dropped: "
           + "; ".join(f"{n}={v:g}" if isinstance(v, float) else f"{n}={v}"
                       for n, v, _w in stated) + "."
           if stated else ""))
    for name, val, why in stated:
        if name in ("TEND", "FRIC", "BLOCK"):
            state.warn(
                f"{kw}: {name}="
                + (f"{val:g}" if isinstance(val, float) else f"{val}")
                + f" — {why}. DROPPED.")


def _resolve_particle_air(state: ConversionState, ab: Airbag) -> None:
    """The bag's INITIAL fill, from the ``IAIR`` branch.

    ``IAIR = 0`` is LS-DYNA's "no initial air", and Radioss has no way to say
    it: ``mat_ID`` is required (``ERROR 699``) and the starter derives the
    initial mass from ``Pext``, ``T0`` and that material whatever it is. So the
    bag is filled with Radioss's built-in ``AIR`` at the card's TATM/PATM —
    a real semantic change, named rather than hidden. (dyna2rad does the same
    thing without saying so, ``convertcontrolvols.cxx:1102-1116``.)

    ``IAIR`` 1 (control-volume air) and 2 (particle air) differ only in HOW
    LS-DYNA carries the initial gas, which an FV bag does not distinguish, so
    both take the card's own XMAIR/AAIR/BAIR/CAIR.
    """
    kw = f"*{ab.keyword}"
    ab.gas_mat_id = state.next_mat_id()
    if ab.iair == 0:
        ab.gas_mat_kind = "PREDEF"
        ab.pe = ab.patm
        ab.t_ext = ab.tatm
        state.warn(
            f"{kw}: IAIR=0 says the bag holds NO initial air, and Radioss "
            "cannot state that — /MONVOL requires a mat_ID (starter "
            "ERROR 699) and derives the initial gas mass from it as "
            "MI = Pext*(V+Veps)/(R/MW*T0). The bag is therefore filled with "
            "Radioss's built-in AIR (/MAT/GAS/PREDEF, MW = 0.02896 kg/mol "
            f"rescaled into the deck's units) at PATM={ab.patm:g} and "
            f"TATM={ab.tatm:g}. On a bag that starts folded and empty the "
            "extra mass is small; on a large one it is not.")
        return
    ab.pe = ab.pair
    ab.t_ext = ab.tair
    if ab.xmair < 0.0:
        ab.gas_mat_kind = "PREDEF"
        state.warn(
            f"{kw}: XMAIR={ab.xmair:g} is negative, so |XMAIR| = "
            f"{-ab.xmair:g} names a *DEFINE_CPM_GAS_PROPERTIES card and "
            "AAIR/BAIR/CAIR are ignored (Vol I R17). That keyword is not "
            "converted by this batch, so the initial fill falls back to "
            "Radioss's built-in AIR at PAIR/TAIR. State XMAIR, AAIR, BAIR and "
            "CAIR directly to convert the real gas.")
        return
    if ab.xmair <= 0.0:
        ab.gas_mat_kind = "PREDEF"
        state.warn(
            f"{kw}: IAIR={ab.iair} says the bag starts filled with air but "
            f"the air card states XMAIR={ab.xmair:g}. /MAT/GAS/MOLE needs "
            "MW > 0 (starter ERROR 710), so the fill falls back to Radioss's "
            "built-in AIR at PAIR/TAIR rather than emitting a gas the starter "
            "refuses.")
        return
    ab.gas_mat_kind = "MOLE"
    ab.mw, ab.hc_a, ab.hc_b, ab.hc_c = (ab.xmair, ab.aair, ab.bair, ab.cair)
    if ab.iair in (2, 4, -4):
        state.warn(
            f"{kw}: IAIR={ab.iair} selects the PARTICLE initial-air method"
            + (" with gas-front tracking" if abs(ab.iair) == 4 else "")
            + ". The initial gas is the same gas either way — only how "
            "LS-DYNA carries it differs — so it converts as the "
            "control-volume form, and the distinction is lost with no "
            "consequence for a continuum bag.")


def _resolve_particle_nozzles(state: ConversionState, ab: Airbag) -> None:
    """The NORIF orifice rows → the FVMBAG2 inflator-nozzle ``/SURF``.

    Radioss's ``surf_IDinj`` is a SURFACE the incoming gas enters through, at
    a hard-coded 300 m/s (``hm_read_monvol_type11.F``: ``FVEL(II) = THREE100 *
    FAC_T_WORK / FAC_L_WORK``). LS-DYNA's orifices are POINTS with a direction,
    so only the forms whose direction is a shell normal carry over: ``VDi`` of
    −1 or −2 (and −3/−4 with an offset) make ``NIDi`` a SHELL ELEMENT id
    rather than a node id, and those elements ARE the nozzle surface. A
    positive ``VDi`` is a ``*DEFINE_VECTOR`` and ``NIDi`` is then a node, which
    has no surface to be.

    That restriction is dyna2rad's too — it raises message 200035, *"Inflator
    nozzles can be defined only by shells VID=-1 or VID=-2"* — but its
    implementation has three defects this does not copy:

    1. ``sh4n``/``sh3n`` are declared OUTSIDE the loop and never reset
       (``:1467-1483``), so once one NIDi resolves as a ``/SHELL`` every later
       one is pushed into the quad list whatever it really is.
    2. Both branches write ``surf_IDinj`` row 0, so a bag with quad AND tria
       nozzles loses the quads: the SH3N write at ``:1518`` overwrites the
       SHELL write at ``:1501``.
    3. Both sets are written with the ``/PART`` entity type for what are
       element ids.

    Here each id is classified on its own and a mixed set is wrapped in a
    ``/SURF/SURF``, the same way the bag's own external surface is.
    """
    kw = f"*{ab.keyword}"
    if not ab.orifices:
        return
    shell_ids = {e.eid for e in state.shell_elems}
    good: List[int] = []
    bad: List[int] = []
    unknown: List[int] = []
    for nid, _an, vdi, _ca, _info, _imom, _iang, _chm in ab.orifices:
        if vdi in (-1.0, -2.0, -3.0, -4.0):
            (good if nid in shell_ids else unknown).append(nid)
        else:
            bad.append(nid)
    if bad:
        state.warn(
            f"{kw}: {len(bad)} inflator nozzle(s) state a VDi that is not "
            "-1/-2/-3/-4, so NIDi is a NODE id and the direction comes from a "
            "*DEFINE_VECTOR. Radioss's inflator inlet is a SURFACE "
            "(surf_IDinj) with a hard-coded 300 m/s normal injection velocity "
            "— there is no point-with-a-vector form — so those nozzles are "
            "DROPPED. Radioss states the same restriction itself: dyna2rad "
            "message 200035, \"Inflator nozzles can be defined only by shells "
            "VID=-1 or VID=-2\". Restate the nozzle as a shell element with "
            f"VDi=-1 to convert it. Nozzle NIDi: {bad}.")
    if unknown:
        state.warn(
            f"{kw}: nozzle(s) {unknown} give VDi = -1/-2 (so NIDi is a SHELL "
            "ELEMENT id, not a node id) but this deck defines no shell with "
            "those ids. They are left out of the inflator surface; naming an "
            "element the deck does not define is starter ERROR 70 and refuses "
            "the whole run.")
    if not good:
        state.warn(
            f"{kw}: no inflator nozzle resolved to a shell element, so the "
            "/MONVOL/FVMBAG2 gets NO surf_IDinj. The gas then enters the "
            "finite-volume mesh with no inlet surface — the injector still "
            "adds mass and enthalpy, but it does so everywhere at once rather "
            "than through the nozzle, which is exactly the directional detail "
            "an FV bag exists to resolve.")
        return
    ab.inj_quad_eids, ab.inj_tri_eids = _split_shell_eids_by_topology(
        state, sorted(set(good)))
    ab.surf_inj_id = state.next_id()
    momentum = [n for (n, _a, _v, _c, _i, imom, _ia, _ch) in ab.orifices
                if imom]
    if momentum:
        state.warn(
            f"{kw}: nozzle(s) {momentum} set IMOM, which makes LS-DYNA apply "
            "the jet's MOMENTUM — and its reaction on the inflator housing — "
            "as well as its mass. Radioss injects at a fixed normal velocity "
            "through surf_IDinj and applies no reaction, so IMOM is DROPPED: "
            "the bag gains the gas but the housing feels no thrust.")
    angled = [n for (n, _a, _v, ca, _i, _im, iang, _ch) in ab.orifices
              if iang and ca not in (0.0, 30.0)]
    if angled:
        state.warn(
            f"{kw}: nozzle(s) {angled} set IANG with a non-default cone angle "
            "CAi. Radioss's inflator surface has no cone: the gas enters "
            "along each segment's own normal. The angle is DROPPED.")
    if any(an for (_n, an, _v, _c, _i, _im, _ia, _ch) in ab.orifices):
        state.warn(
            f"{kw}: the nozzle AREA column ANi is DROPPED — Radioss takes the "
            "inlet area from surf_IDinj's own geometry and echoes it as "
            "\"INITIAL SURFACE OF INFLATOR\". If ANi differs from the area of "
            "the shells named by NIDi, the converted inlet is the shells'.")
    if any(chm for (_n, _a, _v, _c, _i, _im, _ia, chm) in ab.orifices) or ab.chm:
        state.warn(
            f"{kw}: the card names *DEFINE_CPM_CHAMBER ids (CHM / CHM_ID), so "
            "this bag is MULTI-CHAMBER. Radioss splits a finite-volume bag "
            "into chambers with the INTERNAL surface (surf_IDin) built from "
            "SD2, not with a chamber card, and *DEFINE_CPM_CHAMBER is not "
            "converted by this batch. The bag becomes SINGLE-CHAMBER unless "
            "SD2 already names the dividing parts. (dyna2rad has no chamber "
            "handling at all — grep \"CHAMBER\" over its whole tree returns "
            "nothing.)")


def _resolve_particle_vents(state: ConversionState, ab: Airbag,
                            add_curve) -> None:
    """The ``NVENT`` vent rows → named vent holes.

    ``SID3``/``STYPE3`` name the vent patch (0 a PART, 1 or 2 a PART SET),
    ``C23`` is the vent coefficient — a SCALE FACTOR here, because a named
    surface supplies the area — and ``LCTC23``/``LCPC23`` scale it against time
    and against pressure. LS-DYNA multiplies the three and clamps:
    ``min(max(C23 x LCTC23 x LCPC23, 0), 1)``; Radioss multiplies them too
    (``airbagb1.F``: ``AOUT = FPORA*AVENT*f_A``, then ``*f_t``, then ``*f_P``)
    but does not clamp, so a product above 1 vents through more area than the
    surface has.

    ``PPOP`` is the pop-open pressure, and it is a real dyna2rad gap: *"a vent
    that should stay shut until PPOP now opens at t=0"*. It becomes ``dPdef``
    with ``Tstart`` pushed out of reach, for the reason ``_VENT_NEVER``
    documents.
    """
    kw = f"*{ab.keyword}"
    if ab.nvent > 10:
        state.warn(
            f"{kw}: NVENT={ab.nvent}. All of them are read and emitted, but "
            "the Radioss /TH per-vent channels only go up to AOUT10/HOUT10, "
            "so vents 11 and beyond have no individual time history. "
            "(dyna2rad writes Nvent = NVENT while only filling ten blocks, "
            "leaving the rest with surf_IDv = 0 and Avent = 0.)")
    for k, (sid3, stype3, c23, lctc23, lcpc23, enh_v, ppop) in enumerate(
            ab.vent_rows, start=1):
        v = AirbagVent(title=f"VENT{k}", avent=c23 if c23 != 0.0 else 1.0)
        pids = _part_scope_pids(state, sid3, stype3 != 0,
                                f"*{ab.keyword} (SID {ab.sid})",
                                f"vent {k}'s SID3")
        _resolve_vent_surface(state, ab, v, pids, f"vent {k}'s SID3")
        if lctc23 > 0:
            v.fct_t = lctc23
            if lctc23 not in state.curves:
                state.warn(
                    f"{kw}: vent {k} names time curve {lctc23}, which this "
                    "deck does not define — starter ERROR 331.")
        if lcpc23 > 0:
            # LS-DYNA does NOT document LCPC23's abscissa as an absolute
            # pressure (unlike *AIRBAG_HYBRID's LCA23/LCAP23, which it does),
            # so it is referenced as written rather than shifted by -Pext. A
            # wrong shift is as damaging as a missing one and there is no
            # source that settles it, so the ambiguity is reported instead.
            v.fct_p = lcpc23
            state.warn(
                f"{kw}: vent {k}'s LCPC23={lcpc23} scales the vent "
                "coefficient against pressure, and LS-DYNA does not say "
                "whether that pressure is absolute or gauge. Radioss's "
                "fct_IDP is a function of the GAUGE pressure P - Pext "
                "(airbagb1.F evaluates it at (P-PEXT)*SCALP), so the curve is "
                "referenced UNSHIFTED — i.e. read as a gauge-pressure curve. "
                f"If it was written against absolute pressure, shift its "
                f"abscissae by {-ab.pe:g} yourself. (*AIRBAG_HYBRID's LCA23 "
                "and LCAP23 ARE documented as absolute and this converter "
                "does shift those.)")
        if ppop != 0.0:
            v.dpdef = ppop
            v.tstart = _VENT_NEVER
            state.warn(
                f"{kw}: vent {k} states PPOP={ppop:g}, the pressure ABOVE "
                "ambient at which the vent pops open and then latches. It is "
                f"emitted as dPdef with Tstart = {_VENT_NEVER:g}, because the "
                "engine ORs the time and pressure criteria (airbagb1.F:290) "
                "and a Tstart of 0 opens the hole on the first cycle. "
                "(dyna2rad never reads PPOP, so a vent that should stay shut "
                "opens at t=0 there.)")
        if enh_v:
            state.warn(
                f"{kw}: vent {k} states ENH_V={enh_v} (the enhanced-venting "
                "option). Radioss's vent is the Wang-Nefske isentropic "
                "orifice with an optional area function; the option has no "
                "column and is DROPPED.")
        if c23 < 0.0:
            state.warn(
                f"{kw}: vent {k} states C23={c23:g}, so |C23| names a "
                "*DEFINE_CPM_VENT card. That keyword is not converted by this "
                "batch, so the vent coefficient falls back to 1 — the vent "
                "opens over its whole named surface.")
            v.avent = 1.0
        ab.vents.append(v)


def _resolve_particle(state: ConversionState, ab: Airbag, add_curve) -> None:
    """``*AIRBAG_PARTICLE`` → ``/MONVOL/FVMBAG2`` (or ``/MONVOL/AIRBAG1``).

    **FVMBAG2 is the faithful target and it cannot run here.**
    ``init_monvol.F`` demotes it to FVMBAG1 immediately after reading —
    *"FVMABG2 are in fact FVMBAG1 with simplified input"* — and then meshes the
    bag's interior with tetrahedra. ``hm_read_monvol_type11.F:299`` hard-wires
    ``KMESH = 14``, ``init_monvol.F`` dispatches ``CASE (12, 14)`` to
    ``HYPERMESH_TETRA``, and in an open-source build that is
    ``starter/stub/fvmbags_stub.F``::

        SUBROUTINE HYPERMESH_TETRA(...)
          WRITE(6,*) "FVMBAGS require a mesher"
          STOP
        END SUBROUTINE

    MEASURED on a probe deck: the reader echoes the entire /MONVOL cleanly and
    the starter then prints that line and dies before writing a restart file.
    The card is emitted anyway, because it is the correct conversion and a
    commercial build runs it — and ``--airbag-particle-uniform`` trades the
    finite-volume pressure field for a bag that inflates on this build.
    """
    kw = f"*{ab.keyword}"
    _resolve_particle_air(state, ab)
    _resolve_species_block(state, ab, add_curve)
    _resolve_particle_vents(state, ab, add_curve)
    if ab.radioss_type == "FVMBAG2":
        _resolve_particle_nozzles(state, ab)
        if ab.in_quad_eids or ab.in_tri_eids:
            ab.surf_in_id = state.next_id()
        ab.cgmerg = _FVMBAG2_CGMERG
        ab.dtsca = _FVMBAG2_DTSCA
        ab.dtmin = _FVMBAG2_DTMIN.get(ab.unit, 0.0)
        if ab.unit not in _FVMBAG2_DTMIN:
            state.warn(
                f"{kw}: UNIT={ab.unit} is outside the 0/1/2 table (0 = "
                "kg-mm-ms-K, 1 = SI, 2 = tonne-mm-s-K), so no minimum "
                "finite-volume time step can be assumed and Dtmin is left "
                "blank — the starter then uses its own 1e-20, which lets the "
                "bag's own step collapse without a floor. UNIT=3 states the "
                "conversion factors on its own card, which this converter "
                "does not read. Give UNIT 0, 1 or 2.")
        ab.tswitch = ab.tsw
        if ab.tsw:
            state.warn(
                f"{kw}: TSW={ab.tsw:g} is the time the CPM bag switches to a "
                "uniform-pressure control volume. It is emitted as Tswitch "
                "WITH Iswitch = 1, so it actually fires — dyna2rad copies TSW "
                "and leaves Iswitch at 0, which is \"No switch to uniform "
                "pressure\", making the value inert "
                "(convertcontrolvols.cxx:2255 vs monvol_fvmbag2.cfg:393). "
                "Radioss measures it from the injector's time-to-fire, which "
                "this conversion leaves at 0, so it is measured from t=0 — "
                "exactly what TSW means.")
        state.warn(
            f"{kw}: /MONVOL/FVMBAG2 IS EMITTED AND WILL NOT RUN ON AN "
            "OPEN-SOURCE OPENRADIOSS BUILD. hm_read_monvol_type11.F:299 "
            "hard-wires KMESH=14, init_monvol.F dispatches that to "
            "HYPERMESH_TETRA, and starter/stub/fvmbags_stub.F is a stub that "
            "prints \"FVMBAGS require a mesher\" and STOPs — MEASURED: the "
            "reader echoes the whole /MONVOL cleanly and the starter then "
            "dies before writing a restart file. The card is correct and a "
            "commercial build meshes it. Re-run with "
            "--airbag-particle-uniform to get a /MONVOL/AIRBAG1 instead: same "
            "gas, same injector, same vents, uniform pressure instead of a "
            "finite-volume field.")
    else:
        if ab.sd2 > 0:
            state.warn(
                f"{kw}: --airbag-particle-uniform emits /MONVOL/AIRBAG1, "
                f"which has no internal-surface column, so SD2={ab.sd2} is "
                "DROPPED. The bag's internal baffles still exist as "
                "structure and still carry contact, but they no longer split "
                "the gas into chambers: one pressure acts on both sides of "
                "each of them.")
        if ab.orifices:
            state.warn(
                f"{kw}: --airbag-particle-uniform emits /MONVOL/AIRBAG1, "
                f"which has no inflator-inlet surface, so the {len(ab.orifices)} "
                "nozzle definition(s) are DROPPED. The gas appears throughout "
                "the bag at once, which is what a uniform-pressure model "
                "means.")
        if ab.tsw:
            state.warn(
                f"{kw}: TSW={ab.tsw:g} switches a CPM bag to uniform "
                "pressure. --airbag-particle-uniform makes it uniform from "
                "t=0, so TSW is already satisfied and is DROPPED.")
    if ab.mole_fraction:
        state.warn(
            f"{kw}: _MOLEFRACTION makes LCMi a time-dependent MOLAR FRACTION "
            f"of the total flow given by LCMASS={ab.lcmass}, not a mass flow "
            "rate. Radioss states exactly that with /PROP/INJECT2 (one common "
            "mass-flow and temperature curve plus a per-gas molar fraction), "
            "which this batch does not emit. The per-gas curves are converted "
            "as if they were mass flows — this inflator is WRONG by the ratio "
            "of the total flow to each fraction. Restate the gases with "
            "per-species mass-flow curves, or convert this bag by hand.")
    if ab.decomposition:
        state.warn(
            f"{kw}: _DECOMPOSITION adds no card of its own — it makes "
            "LS-DYNA insert *CONTROL_MPP_DECOMPOSITION_BAGREF and "
            "_ARRANGE_PARTS automatically. It is an MPP domain-decomposition "
            "hint with no physics and no Radioss counterpart, so nothing is "
            "lost by dropping it.")
    infg = sorted({s.infg for s in ab.species if s.infg > 1})
    if infg:
        state.warn(
            f"{kw}: the gas species name more than one inflator "
            f"(INFGi = {infg}). Radioss's /PROP/INJECT1 is ONE injector whose "
            "rows share a single inlet surface and a single sensor, so all "
            "species are injected together through the same nozzles. Split "
            "the bag into one *AIRBAG per inflator if they fire at different "
            "times or through different nozzles.")
    _warn_particle_cpm_fields(state, ab)


# ─────────────────────────────────────────────────────────────────────────────
# Batch 2 — *AIRBAG_INTERACTION: the COMMU1 promotion
# ─────────────────────────────────────────────────────────────────────────────

#: The ``/MONVOL`` types a communicating-bag row can be attached to. COMMU1's
#: gas model IS AIRBAG1's — ``monvol0.F`` dispatches ``ITYP==7 .OR. ITYP==9``
#: to the same ``AIRBAGA1``/``AIRBAGB1`` pair — so promoting an AIRBAG1 bag
#: costs nothing. PRES and LFLUID have no gas to exchange, GAS is a closed
#: adiabatic volume with no injector, and FVMBAG2 is a different solver whose
#: ``AC``/``UC`` channels are structurally zero.
_COMMU1_PROMOTABLE = ("AIRBAG1",)


def _resolve_airbag_interactions(state: ConversionState) -> None:
    """``*AIRBAG_INTERACTION`` → reciprocal ``Nbag`` rows on two
    ``/MONVOL/COMMU1``.

    **dyna2rad has no path here at all** — ``grep AIRBAG_INTERACTION`` over
    ``reader/source/dyna2rad`` returns zero hits, so the keyword is silently
    dropped there and two bags that should share gas simply do not. Everything
    below is k2rad exceeding the reference converter.

    The Radioss block is NOT reciprocal: *"each COMMU1 must carry its own
    ``Nbag`` entry pointing at the other"*, and the engine only ever pushes
    gas DOWNHILL — ``airbagb1.F`` guards the whole flow with
    ``IF(IDEF==1 .AND. P>PVOIS .AND. …)``. So LS-DYNA's two-way ``IFLOW = 0``
    is two rows and a one-way IFLOW is one, which is exactly the mapping.

    Both bags keep their own ``/MONVOL`` id and their own external surface;
    only the card type changes, and it changes for BOTH — a COMMU1 row naming
    an AIRBAG1 partner is not expressible.
    """
    if not state.airbag_interactions:
        return
    by_id: Dict[int, Airbag] = {}
    for ab in state.airbags:
        if ab.airbag_id > 0:
            by_id.setdefault(ab.airbag_id, ab)
    for it in state.airbag_interactions:
        kw = f"*{it.keyword}"
        ref = f"{kw} (AB1 {it.ab1}, AB2 {it.ab2})"
        a, b = by_id.get(it.ab1), by_id.get(it.ab2)
        missing = [i for i, x in ((it.ab1, a), (it.ab2, b)) if x is None]
        if missing:
            state.warn(
                f"{ref}: airbag id(s) {missing} are not defined by any "
                "*AIRBAG_* card in this deck (the ids are the ABID of an "
                "_ID/_TITLE card, not the *SET ids). NO gas exchange is "
                "emitted — both bags stay sealed from each other and each "
                "reaches a higher pressure than LS-DYNA's.")
            continue
        bad = [(x.airbag_id, x.radioss_type)
               for x in (a, b)
               if x.dropped or x.radioss_type not in _COMMU1_PROMOTABLE]
        if bad:
            state.warn(
                f"{ref}: gas exchange needs BOTH bags on /MONVOL/COMMU1, and "
                + ", ".join(f"airbag {i} converts to "
                            + (f"/MONVOL/{t}" if t else "nothing")
                            for i, t in bad)
                + ". Only a /MONVOL/AIRBAG1 bag can be promoted — it shares "
                "COMMU1's whole gas model (monvol0.F sends ITYP 7 and 9 to "
                "the same AIRBAGA1/AIRBAGB1), while a PRES or LFLUID volume "
                "has no gas to exchange, a GAS volume is closed and adiabatic "
                "with no injector, and an FVMBAG2 bag is a different solver "
                "whose communication channels read zero. The interaction "
                f"between airbags {it.ab1} and {it.ab2} is DROPPED and both "
                "stay sealed.")
            continue
        _promote_commu1(state, it, a, b)


def _promote_commu1(state: ConversionState, it, a: Airbag, b: Airbag) -> None:
    """Turn one resolved ``*AIRBAG_INTERACTION`` into the two ``Nbag`` rows."""
    kw = f"*{it.keyword}"
    ref = f"{kw} (AB1 {it.ab1}, AB2 {it.ab2})"
    if it.lcid:
        state.warn(
            f"{ref}: LCID={it.lcid} gives the mass flow between the bags "
            "directly, as a function of their pressure difference, and "
            "LS-DYNA then ignores AREA, SF and PID entirely. A Radioss "
            "communicating volume has no mass-flow slot — it derives the flow "
            "from a Wang-Nefske isentropic expansion through Acom "
            "(airbagb1.F) — so the curve is DROPPED and the AREA/SF/PID "
            "columns are used instead, which LS-DYNA does not. Check the "
            "resulting flow: if AREA and SF are blank, the two bags exchange "
            "nothing.")
    if it.excp:
        state.warn(
            f"{ref}: EXCP={it.excp} excludes the orifice part from the bag "
            "pressure. Radioss applies the bag pressure to every segment of "
            "surf_IDex, with no per-part exclusion, so EXCP is DROPPED.")
    # ── the shared partition surface ────────────────────────────────────
    surf_a = surf_b = 0
    made_a = made_b = None
    if it.pid:
        pid = abs(it.pid)
        if it.pid < 0:
            state.warn(
                f"{ref}: PID={it.pid} is negative, which asks LS-DYNA to "
                "block the orifice where the two bags are in contact. "
                "Radioss's communicating block has no blockage column — that "
                "exists only on a porous surface (Iblockage) — so the sign is "
                "DROPPED and the orifice stays fully open. |PID| is used as "
                "the partition surface.")
        va = AirbagVent(title=f"COMMU_{b.monvol_id}")
        vb = AirbagVent(title=f"COMMU_{a.monvol_id}")
        _resolve_vent_surface(state, a, va, [pid], f"the partition PART {pid}")
        _resolve_vent_surface(state, b, vb, [pid], f"the partition PART {pid}")
        surf_a, surf_b = va.surf_id, vb.surf_id
        if surf_a and surf_b:
            # Into commu_surfs, NOT into vents: a communicating surface moves
            # gas to the PARTNER, not to the outside, and a vent-hole block
            # over the same elements would leak the bag to atmosphere as well.
            # Each bag builds its own /SURF over the SAME parts because
            # Radioss checks the containment per volume — ERROR 902,
            # "COMMUNICATING SURFACE ID IS NOT INCLUDED INTO AIRBAG SURFACE ID".
            a.commu_surfs.append(va)
            b.commu_surfs.append(vb)
            made_a, made_b = va, vb
        else:
            state.warn(
                f"{ref}: PART {pid} is not a shell part of BOTH bags' "
                "external surfaces, so it cannot be the partition they share. "
                "Radioss refuses that outright — ERROR 902, \"COMMUNICATING "
                "SURFACE ID=%d IS NOT INCLUDED INTO AIRBAG SURFACE ID=%d\" — "
                "so the surface is dropped and the orifice falls back to the "
                "scalar AREA. The two chambers have to SHARE the partition "
                "elements for this to work.")
            surf_a = surf_b = 0
    # ── area and coefficient ────────────────────────────────────────────
    area = it.area
    fct_p = 0
    if area < 0.0:
        state.warn(
            f"{ref}: AREA={area:g} is negative, so |AREA| = {-area:g} is a "
            "curve of orifice area against ABSOLUTE pressure. Radioss "
            "evaluates a communicating vent's pressure function against the "
            "PARTNER pressure difference instead — airbagb1.F reads it at "
            "(P - PVOIS)*SCALP, not at (P - Pext) and not at P — so an "
            "absolute-pressure curve cannot be shifted onto that abscissa "
            "without knowing the partner's pressure. The curve is DROPPED and "
            "the orifice gets no area at all unless PID names a surface. "
            "State a constant AREA, or a PID.")
        area = 0.0
    sf = it.sf
    fct_t = 0
    if sf < 0.0:
        fct_t = int(-sf)
        sf = 1.0
        state.warn(
            f"{ref}: SF={it.sf:g} is negative, so |SF| = {fct_t} is a curve "
            "of the vent coefficient against RELATIVE TIME. It is emitted as "
            "the communicating row's fct_IDCt, whose abscissa is the run time "
            "(no injector sensor is created, so nothing shifts it — see "
            "ITTF_NO_SHIFT). If LS-DYNA's 'relative' meant relative to the "
            "bag's own activation, shift the curve yourself.")
        if fct_t not in state.curves:
            state.warn(
                f"{ref}: the vent-coefficient curve {fct_t} is not defined in "
                "this deck. The row references it anyway; a missing "
                "communicating function is starter ERROR 331.")
    elif sf == 0.0:
        sf = 1.0
    # With a partition surface, Acom is a SCALE FACTOR on that surface's area;
    # without one it is an ABSOLUTE area. Same column, decided by surf_IDc.
    acom_a = sf if surf_a else area * sf
    acom_b = sf if surf_b else area * sf
    if not surf_a and area == 0.0:
        state.warn(
            f"{ref}: AREA is 0 and no usable PID surface was found, so the "
            "orifice between the two bags has no area and NO GAS FLOWS. "
            "LS-DYNA reads AREA=0 as \"use the surface area of PID\", which "
            "needs a PID that is a shell part of both bags.")
    row_a = (b.monvol_id, surf_a, acom_a, fct_t, fct_p)
    row_b = (a.monvol_id, surf_b, acom_b, fct_t, fct_p)
    if it.iflow < 0:
        rows = ((a, row_a),)
        note = f"ONE-WAY, airbag {it.ab1} -> {it.ab2}"
    elif it.iflow > 0:
        rows = ((b, row_b),)
        note = f"ONE-WAY, airbag {it.ab2} -> {it.ab1}"
    else:
        rows = ((a, row_a), (b, row_b))
        note = "TWO-WAY"
    carrying = {id(bag) for bag, _row in rows}
    for bag, row in rows:
        bag.commu_rows.append(row)
        bag.radioss_type = "COMMU1"
    for bag, vent in ((a, made_a), (b, made_b)):
        if id(bag) not in carrying and vent is not None:
            # A one-way IFLOW gives the RECEIVING bag no row of its own, so it
            # stays /MONVOL/AIRBAG1 — which is right twice over: its AC/UC
            # channels would read zero anyway (nothing to sum over), and a
            # COMMU1 with Nbag = 0 is what monvol_commu1.cfg:255-259 refuses
            # ("CHECK(COMMON) { NBAG > 0; }"), the very thing this batch does
            # not copy from dyna2rad. The partition /SURF it just built would
            # then be referenced by nothing, so it is dropped rather than
            # emitted as an orphan.
            bag.commu_surfs = [v for v in bag.commu_surfs if v is not vent]
    state.warn(
        f"{ref}: converted — airbags {it.ab1} and {it.ab2} are promoted from "
        f"/MONVOL/AIRBAG1 to /MONVOL/COMMU1 with a {note} communicating "
        "block. Radioss's rows are not reciprocal (each volume carries its "
        "own entry naming the other) and the engine only ever pushes gas "
        "downhill — airbagb1.F guards the flow with IF(IDEF==1 .AND. "
        "P>PVOIS), so a two-way IFLOW needs both rows and a one-way IFLOW "
        "needs one. dyna2rad does not convert *AIRBAG_INTERACTION at all, so "
        "there the two bags stay sealed."
        + ("" if it.iflow == 0 else
           " With a one-way flow only the SENDING bag becomes a COMMU1; the "
           "receiving one stays /MONVOL/AIRBAG1, which is the same gas model "
           "(monvol0.F) with no communicating block of its own — its AC/UC "
           "time-history channels would read zero either way."))


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


def _vent_block(v: AirbagVent) -> List[str]:
    """One vent hole's four cards (five with ``Iform == 2``).

    The layout is the ``/PROP/AIRBAGVENTHOLE`` sub-block, and it is the ONE
    sub-block pinned as identical across every monitored volume this converter
    writes: ``radioss140/PROP/venthole1.cfg:17`` names itself *"SUBOBJECT of
    AIRBAG1, COMMU1 AND FVMBAG1"*, and the card-format probe read the same
    columns back off a COMMU1 and an FVMBAG2 deck::

        surf_IDv(1-10) Iform(11-20) Avent(21-40) Bvent(41-60) <20> title(81-100)
        Tstart(1-20) Tstop(21-40) dPdef(41-60) dtPdef(61-80) <10> IdtPdef(91-100)
        fct_IDt(1-10) fct_IDP(11-20) fct_IDA(21-30) <10> Fscalet(41-60)
                                            FscaleP(61-80) FscaleA(81-100)
        fct_IDt'  fct_IDP'  fct_IDA'   ... the AFTER-CONTACT set

    ``Tstop = 0`` is the starter's INFINITY (never deactivate) and every
    ``Fscale*`` of 0 is promoted to 1.0, so the zeros here are real defaults
    and not omissions. The primed row is the area the vent keeps once the hole
    is blocked by contact; LS-DYNA has no such pair, so it stays 0 — with
    ``Bvent = 0`` the engine never reaches it.
    """
    b10, b20 = " " * 10, " " * 20
    lines = [
        "# surf_IDv     Iform               Avent               Bvent"
        "                              vent_title",
        # surf_IDv = 0 is the whole-bag mode, in which Avent is the vent AREA
        # and Bvent is forced to 0 by the reader; with a named surface Avent
        # is a SCALE FACTOR on that surface's current area.
        f"{_i(v.surf_id)}{_i(v.iform)}{_f(v.avent)}{_f(v.bvent)}{b20}"
        + f"{v.title[:20]:>20}",
        "#             Tstart               Tstop               dPdef"
        "              dtPdef             IdtPdef",
        f"{_f(v.tstart)}{_f(0.0)}{_f(v.dpdef)}{_f(0.0)}{b10}{_i(0)}",
        "#  fct_IDt   fct_IDP   fct_IDA                       Fscalet"
        "             FscaleP             FscaleA",
        f"{_i(v.fct_t)}{_i(v.fct_p)}{_i(v.fct_a)}{b10}"
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "# fct_IDt'  fct_IDP'  fct_IDA'                      Fscalet'"
        "            FscaleP'            FscaleA'",
        f"{_i(0)}{_i(0)}{_i(0)}{b10}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
    ]
    return lines


def _commu_block(ab: Airbag) -> List[str]:
    """The ``Nbag`` communicating-volume block of a ``/MONVOL/COMMU1``.

    ``hm_read_monvol_type9.F``, verified column by column against a two-chamber
    probe's starter echo::

        Nbag(1-10)
        bag_ID(1-10) surf_IDc(11-20) DeltaPCdef(21-40) Acom(41-60)
                                     Tcom(61-80) DeltatPCdef(81-100)
        fct_IDCt(1-10) fct_IDCP(11-20) FscaleCt(21-40) FscaleCP(41-60)

    ``Acom`` is a SCALE FACTOR when ``surf_IDc != 0`` and an ABSOLUTE AREA when
    it is 0 (a negative one is ``ERROR 1002``), and a non-zero ``surf_IDc``
    must be a subset of THIS bag's ``surf_IDex`` — ``ERROR 902``,
    *"COMMUNICATING SURFACE ID=%d IS NOT INCLUDED INTO AIRBAG SURFACE ID=%d"*.
    ``Tcom = 0`` opens the passage on the first cycle, which is what an
    ``*AIRBAG_INTERACTION`` with no delay column means. Both ``Fscale`` are
    promoted from 0 to 1.0 by the starter.
    """
    lines = ["#     Nbag", f"{_i(len(ab.commu_rows))}"]
    for bag_id, surf_c, acom, fct_t, fct_p in ab.commu_rows:
        lines += [
            "#   bag_ID  surf_IDc          DeltaPCdef                Acom"
            "                Tcom         DeltatPCdef",
            f"{_i(bag_id)}{_i(surf_c)}{_f(0.0)}{_f(acom)}{_f(0.0)}{_f(0.0)}",
            "# fct_IDCt  fct_IDCP            FscaleCt            FscaleCP",
            f"{_i(fct_t)}{_i(fct_p)}{_f(0.0)}{_f(0.0)}",
        ]
    return lines


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

    ``/MONVOL/COMMU1`` (ITYPE 9) is written by the SAME function, because it is
    the same card plus a trailing ``Nbag`` block: card for card, column for
    column, ``monvol_commu1.cfg`` and ``airbag1.cfg`` agree up to that block,
    and ``monvol0.F`` sends ``ITYP==7 .OR. ITYP==9`` to the same
    ``AIRBAGA1``/``AIRBAGB1`` pair. Splitting them into two emitters would be
    two sources for one layout.

    ``Ijet`` is written 0 or 1 and never more. The cfg gates the jetting card
    on ``if(ABG_Ijet == 1)`` while the reader gates it on ``IF (IJET(II) > 0)``
    — MEASURED on a probe, ``Ijet=2`` shifted the whole block by one line and
    produced ``WARNING 100213`` on the injector row followed by
    ``ERROR 100103`` ("Cannot read an integer value") on the vent card below.
    """
    b10 = " " * 10
    t0 = ab.t_ext if ab.t_ext != 0.0 else 295.0
    commu = ab.radioss_type == "COMMU1"
    rad = "COMMU1" if commu else "AIRBAG1"
    hconv = ab.hconv if ab.hconv > 0.0 else 0.0
    ijet = 1 if (ab.jet_n1 and ab.jet_n2) else 0
    lines = [
        f"/MONVOL/{rad}/{ab.monvol_id}",
        (ab.title or f"MONVOL_{rad}_{ab.monvol_id}")[:100],
        "#surf_IDex                         Hconv",
        f"{_i(ab.surf_id)}{b10}{_f(hconv)}",
        "#            AscaleT             AscaleP             AscaleS"
        "             AscaleA             AscaleD",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#   mat_ID                            Mu                Pext"
        "                  T0     Iequi      Ittf",
        f"{_i(ab.gas_mat_id)}{b10}{_f(0.0)}{_f(ab.pe)}{_f(t0)}{_i(0)}"
        f"{_i(ab.ittf)}",
        "#     Njet",
        f"{_i(1 if ab.inject_prop_id else 0)}",
    ]
    if ab.inject_prop_id:
        lines += [
            "#inject_ID   sens_ID      Ijet  node_ID1  node_ID2  node_ID3",
            f"{_i(ab.inject_prop_id)}{_i(0)}{_i(ijet)}"
            f"{_i(ab.jet_n1)}{_i(ab.jet_n2)}{_i(ab.jet_n3)}",
        ]
        if ijet:
            # Read only when Ijet == 1. The three functions shape the jet
            # pressure in time, in the off-axis angle and in the distance;
            # LS-DYNA supplies none of them (its CA/BETA are a half-angle and
            # an efficiency, not functions), so all six columns stay 0 and the
            # jet carries the bag's uniform pressure along its own geometry.
            lines += [
                "# fct_IDPtfctIDPThetfctIDPDelt                      FscalePt"
                "        FscalePTheta        FscalePDelta",
                f"{_i(0)}{_i(0)}{_i(0)}{b10}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            ]
    vents = _airbag1_vents(ab)
    lines += ["#    Nvent  Nporsurf", f"{_i(len(vents))}{_i(0)}"]
    for v in vents:
        lines += _vent_block(v)
    if commu:
        lines += _commu_block(ab)
    lines.append(HDR)
    return lines


def _airbag1_vents(ab: Airbag) -> List[AirbagVent]:
    """The vent holes of an AIRBAG1/COMMU1 card, from either batch's fields.

    Batch 1 resolves ONE whole-bag hole into the scalar ``avent`` /
    ``vent_fct_p`` pair; batch 2 resolves a LIST. Both land here so the emitter
    has one shape, and the batch-1 pair produces byte-identical output to what
    it produced before the list existed.
    """
    if ab.vents:
        return ab.vents
    if ab.avent > 0.0 or ab.vent_fct_p:
        return [AirbagVent(title="VENT", avent=ab.avent,
                           fct_p=ab.vent_fct_p)]
    return []


def _emit_monvol_fvmbag2(ab: Airbag) -> List[str]:
    """/MONVOL/FVMBAG2 (ITYPE 11) — ``radioss2021/CONTROLVOL/monvol_fvmbag2.cfg
    FORMAT(radioss2021)``, reader ``hm_read_monvol_type11.F``::

        /MONVOL/FVMBAG2/<id>
        <title, 100>
        surf_IDex(10) surf_IDin(10) Hconv(20)          [IH3D(10) is 2023+ ONLY]
        mat_ID(10) <30 blank> Pext(20) T0(20) <10 blank> Ittf(10)
        Njet(10)
          inject_ID(10) sens_ID(10) surf_IDinj(10)
        Nvent(10) Nporsurf(10)
          ... vent blocks, byte-identical to AIRBAG1's
        Cgmerg(20) Tswitch(20) <10 blank> Iswitch(10) Pswitch(20)
        Dtsca(20) Dtmin(20)

    **``IH3D`` is not written.** It appears at columns 41-50 of card 1 from
    ``FORMAT(radioss2023)`` on, and this converter writes ``/BEGIN 2022``.
    MEASURED on a twin-deck probe: writing it at 2022 costs ``WARNING 100213``
    ("unsupported field exists at the end of line") and the field is dropped
    with no shift — survivable, but a warning for a column that carries
    nothing here.

    The injector row is ONE card, not AIRBAG1's six columns plus a jetting
    card: FVMBAG2 has no ``Ijet`` and no jet nodes, because the gas enters
    through ``surf_IDinj`` at a hard-coded normal velocity
    (``hm_read_monvol_type11.F``: ``FVEL(II) = THREE100 * FAC_T_WORK /
    FAC_L_WORK``, i.e. 300 m/s in the deck's units).

    ``Iswitch = 1`` is written whenever ``Tswitch`` is, and that is deliberate:
    ``fv_up_switch.F`` gates the whole switch on ``IVOLU(74)``, so dyna2rad's
    ``Tswitch`` with ``Iswitch = 0`` can never fire
    (``convertcontrolvols.cxx:2255`` vs ``monvol_fvmbag2.cfg:393``, "0: No
    switch to uniform pressure").
    """
    b10, b30 = " " * 10, " " * 30
    t0 = ab.t_ext if ab.t_ext != 0.0 else 295.0
    hconv = ab.hconv if ab.hconv > 0.0 else 0.0
    lines = [
        f"/MONVOL/FVMBAG2/{ab.monvol_id}",
        (ab.title or f"MONVOL_FVMBAG2_{ab.monvol_id}")[:100],
        "#surf_IDex surf_IDin               Hconv",
        f"{_i(ab.surf_id)}{_i(ab.surf_in_id)}{_f(hconv)}",
        "#   mat_ID                                              Pext"
        "                  T0                Ittf",
        f"{_i(ab.gas_mat_id)}{b30}{_f(ab.pe)}{_f(t0)}{b10}{_i(ab.ittf)}",
        "#     Njet",
        f"{_i(1 if ab.inject_prop_id else 0)}",
    ]
    if ab.inject_prop_id:
        lines += [
            "#inject_ID   sens_IDsurf_IDinj",
            f"{_i(ab.inject_prop_id)}{_i(0)}{_i(ab.surf_inj_id)}",
        ]
    lines += ["#    Nvent  Nporsurf", f"{_i(len(ab.vents))}{_i(0)}"]
    for v in ab.vents:
        lines += _vent_block(v)
    iswitch = 1 if ab.tswitch > 0.0 else 0
    lines += [
        "#             Cgmerg             Tswitch             Iswitch"
        "             Pswitch",
        f"{_f(ab.cgmerg)}{_f(ab.tswitch)}{b10}{_i(iswitch)}{_f(0.0)}",
        "#              Dtsca               Dtmin",
        f"{_f(ab.dtsca)}{_f(ab.dtmin)}",
        HDR,
    ]
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


def _emit_mat_gas_mole(mat_id: int, title: str, mw: float, cpa: float,
                       cpb: float, cpc: float) -> List[str]:
    """``/MAT/GAS/MOLE`` — a MOLAR Cp polynomial plus the molar mass,
    ``radioss120/MAT/mat_gas.cfg FORMAT(radioss120)``::

        /MAT/GAS/MOLE/<mid>
        <title>
        MW(1-20)
        Cpa(1-20) Cpb(21-40) Cpc(41-60) Cpd(61-80) Cpe(81-100)

    **There is NO ``Cpf`` card.** ``hm_read_matgas.F`` reads ``MAT_F`` only
    when ``IGAS == 2`` (the ``MASS`` variant) and forces ``CPF = 0`` for
    ``IGAS == 1``; a sixth line written after a MOLE gas is not a Cpf, it is
    the next keyword read as one, and everything below it shifts. This is the
    one structural difference from ``_emit_mat_gas_mass``, which does write it.

    The values are MOLAR because the reader divides them::

        IF (IMOLE == 1) THEN
          CPA = CPA / MW * FAC   ...   CPF = CPF / MW * FAC

    so ``MW`` must be in deck-mass per mole and ``Cp*`` in deck-energy per
    mole per K. MEASURED (probe ``mole_0000.rad``, an Mg/mm/s deck):
    ``MW=2.896e-05`` with ``Cpa=26789.065`` echoes exactly what
    ``/MAT/GAS/PREDEF AIR`` does, while the naive SI pair is taken silently
    and is wrong by 1e6. The cfg's own ``DIMENSION="thermal_massic_capacity"``
    tag on these cells contradicts the FORTRAN and is wrong for MOLE.
    """
    return [
        f"/MAT/GAS/MOLE/{mat_id}",
        title[:100],
        "#                 MW",
        f"{_f(mw)}",
        "#                Cpa                 Cpb                 Cpc"
        "                 Cpd                 Cpe",
        f"{_f(cpa)}{_f(cpb)}{_f(cpc)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]


def _emit_mat_gas_predef(mat_id: int, title: str,
                         gas: str = "AIR") -> List[str]:
    """``/MAT/GAS/PREDEF`` — one of the fourteen gases the starter carries
    hard-coded, ``mat_gas.cfg`` + ``hm_read_matgas.F:158-273``::

        /MAT/GAS/PREDEF/<mid>
        <title>
        Gas Name (columns 1-8, A8, LEFT justified)

    The name is matched by PREFIX, in a fixed order, so ``N2O`` is tested
    before ``N2``, ``CO2`` before ``CO`` and ``H2O`` before ``H2``. An unknown
    name is ``ERROR 722``. AIR is MW = 0.02896 kg/mol with the Shomate
    coefficients 26.789065 / 7.7213E-03 / -1.8027E-06 / 1.4705E-10 /
    1.1359E+04, rescaled from SI into the run's own units by the reader — the
    one gas source in the batch that needs no unit thought at all.
    """
    return [
        f"/MAT/GAS/PREDEF/{mat_id}",
        title[:100],
        "# Gas",
        f"{gas[:8]:<8}",
        HDR,
    ]


def _emit_prop_inject1(prop_id: int, title: str,
                       rows: List[Tuple[int, int, int]]) -> List[str]:
    """``/PROP/INJECT1`` — ONE row per injected gas, ``PROP/prop_inject1.cfg
    FORMAT(radioss100)``, reader ``properties/injector/hm_read_inject1.F``::

        /PROP/INJECT1/<id>
        <title, 100>
        N_gases(10) Iflow(10) Ascale_T(20)
        Mat_ID(10) fun_ID_M(10) fun_ID_T(10) <10 blank> Fscale_M(20) Fscale_T(20)
                                                            ... x N_gases

    ``rows`` is ``[(mat_ID, fun_ID_M, fun_ID_T), …]`` and ``N_gases`` is its
    length — 1 to 100 (``ERROR 696``; LS-DYNA's own limit is 17).

    **The temperature is PER GAS, not common.** Each row carries its own
    ``fun_ID_T`` and ``Fscale_T``, and the engine uses THAT gas's own Cp
    polynomial at THAT gas's own injected temperature to form the enthalpy it
    adds — ``airbaga1.F``: ``EFAC = T*(Cpa + Cpb*T/2 + …)``, then
    ``RIGHT += DGMASS*EFAC``. A multi-species inflator whose gases enter at
    different temperatures is therefore stated exactly, not averaged.

    ``Iflow = 1`` — see ``INJECT1_IFLOW_MASS_RATE``. ``Ascale_T = 1.0`` is
    written explicitly rather than left to the default: it DIVIDES the time
    abscissa while the ``IFLU == 1`` integration multiplies by DT1 without
    dividing, so the two paths disagree for any other value.
    """
    b10 = " " * 10
    lines = [
        f"/PROP/INJECT1/{prop_id}",
        title[:100],
        "#  N_gases     Iflow            Ascale_T",
        f"{_i(len(rows))}{_i(INJECT1_IFLOW_MASS_RATE)}{_f(1.0)}",
        "#   Mat_ID  fun_ID_M  fun_ID_T                      Fscale_M"
        "            Fscale_T",
    ]
    for mat_id, fun_m, fun_t in rows:
        lines.append(
            f"{_i(mat_id)}{_i(fun_m)}{_i(fun_t)}{b10}{_f(0.0)}{_f(0.0)}")
    lines.append(HDR)
    return lines


def _emit_shell_surface(state: ConversionState, surf_id: int, title: str,
                        quad_eids: List[int], tri_eids: List[int],
                        ref: str, what: str) -> List[str]:
    """One shell-backed ``/SURF`` under a caller-supplied id.

    Quads and triangles go into a ``/GRSHEL/SHEL`` and a ``/GRSH3N/SH3N``
    respectively; with both present the two ``/SURF`` are wrapped in a
    ``/SURF/SURF``. Same split ``_make_master_surface`` applies to a contact
    scope, and for the same reason: a ``/GRSHEL/SHEL`` group resolves only
    4-node ``/SHELL`` ids, and a ``/SH3N`` id put in one is starter ERROR 70.

    Every ``/SURF`` a monitored volume references goes through here — the
    external one, ``surf_IDin``, ``surf_IDinj`` and each named vent — so the
    element screen against the EMITTED mesh is applied once and identically to
    all of them.
    """
    lines: List[str] = []
    quads = [e for e in quad_eids if e in state.shell_elem_ids]
    tris = [e for e in tri_eids if e in state.sh3n_elem_ids]
    lost = (len(quad_eids) - len(quads)) + (len(tri_eids) - len(tris))
    if lost:
        state.warn(
            f"{ref}: {lost} shell element(s) of {what} were never WRITTEN to "
            "the deck (their *PART is missing, or they were screened out), so "
            "they are left out of the /SURF. Naming an element the deck does "
            "not define is starter ERROR 70 and the whole run is refused, "
            "which is strictly worse than a surface that is short by those "
            "segments.")
    if quads and tris:
        g1, s1 = state.next_id(), state.next_id()
        g2, s2 = state.next_id(), state.next_id()
        lines += _emit_grshel(g1, f"{title}_grshel", quads)
        lines += _emit_surf_grshel(s1, f"{title}_shells", g1)
        lines += _emit_grsh3n(g2, f"{title}_grsh3n", tris)
        lines += _emit_surf_grsh3n(s2, f"{title}_tris", g2)
        lines += _emit_surf_surf(surf_id, title, [s1, s2])
    elif quads:
        g1 = state.next_id()
        lines += _emit_grshel(g1, f"{title}_grshel", quads)
        lines += _emit_surf_grshel(surf_id, title, g1)
    elif tris:
        g2 = state.next_id()
        lines += _emit_grsh3n(g2, f"{title}_grsh3n", tris)
        lines += _emit_surf_grsh3n(surf_id, title, g2)
    else:
        return []
    return lines


def _emit_airbag_surface(state: ConversionState, ab: Airbag) -> List[str]:
    """The external ``/SURF`` of one monitored volume, built from SHELL
    ELEMENTS (never from segments — ``/SURF/SEG`` is ERROR 18).
    """
    return _emit_shell_surface(
        state, ab.surf_id, f"MONVOL_{ab.monvol_id}_SURF",
        ab.quad_eids, ab.tri_eids,
        f"*{ab.keyword} (SID {ab.sid})", "the monitored volume's surface")


def _emit_airbag_extra_surfaces(state: ConversionState,
                                ab: Airbag) -> List[str]:
    """The ``/SURF`` cards a batch-2 monitored volume references BESIDES its
    external one: every named vent hole, FVMBAG2's internal surface and its
    inflator-nozzle surface.

    Emitted before the ``/MONVOL`` that names them, in the same section, so a
    reader following the deck top to bottom meets each surface before its
    reference. A vent whose surface came back empty carries ``surf_id = 0``
    and contributes nothing here — the ``/MONVOL`` then reads its ``Avent``
    as a whole-bag area, which ``_resolve_vent_surface`` already set to 0.
    """
    ref = f"*{ab.keyword} (SID {ab.sid})"
    lines: List[str] = []
    if ab.surf_in_id:
        lines += _emit_shell_surface(
            state, ab.surf_in_id, f"MONVOL_{ab.monvol_id}_SURF_IN",
            ab.in_quad_eids, ab.in_tri_eids, ref,
            "the bag's INTERNAL surface (SD2)")
    if ab.surf_inj_id:
        lines += _emit_shell_surface(
            state, ab.surf_inj_id, f"MONVOL_{ab.monvol_id}_SURF_INJ",
            ab.inj_quad_eids, ab.inj_tri_eids, ref,
            "the inflator-nozzle surface")
    for k, v in enumerate(ab.vents, start=1):
        if v.surf_id:
            lines += _emit_shell_surface(
                state, v.surf_id, f"MONVOL_{ab.monvol_id}_SURF_{v.title}",
                v.quad_eids, v.tri_eids, ref, f"vent {k}'s surface")
    for v in ab.commu_surfs:
        lines += _emit_shell_surface(
            state, v.surf_id, f"MONVOL_{ab.monvol_id}_SURF_{v.title}",
            v.quad_eids, v.tri_eids, ref,
            "the surface shared with the communicating bag")
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
        lines += _emit_airbag_extra_surfaces(state, ab)
        lines += _emit_airbag_gas(state, ab)
        rad = ab.radioss_type
        if rad in ("AIRBAG1", "COMMU1"):
            lines += _emit_monvol_airbag1(ab)
        elif rad == "FVMBAG2":
            lines += _emit_monvol_fvmbag2(ab)
        elif rad == "GAS":
            lines += _emit_monvol_gas(ab)
        elif rad == "LFLUID":
            lines += _emit_monvol_lfluid(ab)
        else:                                    # PRES: SPV and LOAD_CURVE
            lines += _emit_monvol_pres(ab)
        state.monvol_ids.append((ab.monvol_id, ab.title))
    return lines if len(lines) > 2 else []


def _emit_airbag_gas(state: ConversionState, ab: Airbag) -> List[str]:
    """The ``/MAT/GAS`` and ``/PROP/INJECT1`` of one gas-carrying monitored
    volume — nothing at all for PRES / GAS / LFLUID, which have no injector.

    Four ``/MAT/GAS`` variants reach here, and which one is a per-model
    decision made in the resolver:

      ``CSTA``   batch 1, ``*AIRBAG_SIMPLE_AIRBAG_MODEL`` with ``CV != 0`` —
                 Cp and Cv verbatim, MW derived by the starter as R/(Cp-Cv).
      ``MASS``   batch 1, ``CV == 0`` — the CONVERTER divides A and B by MW,
                 because the slot is mass-specific and LS-DYNA's are molar.
      ``MOLE``   batch 2 — the SOLVER divides, so A/B/C are copied as they
                 stand. Dividing here as well is the one arithmetic error that
                 would look right in the .rad and be wrong by a factor MW.
      ``PREDEF`` batch 2, ``*AIRBAG_PARTICLE`` with no usable air card — the
                 starter's own hard-coded AIR.
    """
    if ab.radioss_type not in ("AIRBAG1", "COMMU1", "FVMBAG2"):
        return []
    lines: List[str] = []
    gtitle = f"MONVOL_{ab.monvol_id}_GAS"
    if ab.gas_mat_kind == "CSTA":
        lines += _emit_mat_gas_csta(ab.gas_mat_id, gtitle, ab.cp, ab.cv)
    elif ab.gas_mat_kind == "MOLE":
        lines += _emit_mat_gas_mole(ab.gas_mat_id, gtitle, ab.mw,
                                    ab.hc_a, ab.hc_b, ab.hc_c)
    elif ab.gas_mat_kind == "PREDEF":
        lines += _emit_mat_gas_predef(ab.gas_mat_id, gtitle, "AIR")
    else:
        mw = ab.mw
        cpa = ab.hc_a / mw if mw else 0.0
        cpb = ab.hc_b / mw if mw else 0.0
        lines += _emit_mat_gas_mass(ab.gas_mat_id, gtitle, mw, cpa, cpb)
    if not ab.inject_prop_id:
        return lines
    if ab.species:
        for sp in ab.species:
            if sp.injected:
                lines += _emit_mat_gas_mole(
                    sp.mat_id, f"{gtitle}_{sp.index}", sp.mw,
                    sp.hc_a, sp.hc_b, sp.hc_c)
        rows = [(sp.mat_id, sp.fun_m, sp.fun_t)
                for sp in ab.species if sp.injected]
    else:                                    # batch 1: one gas, no species
        rows = [(ab.gas_mat_id, max(0, ab.lcid), ab.inject_temp_fct)]
    lines += _emit_prop_inject1(
        ab.inject_prop_id, f"MONVOL_{ab.monvol_id}_INJECTOR", rows)
    return lines
