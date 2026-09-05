"""``*SECTION_BEAM`` ELFORM=3 → ``/PROP/TYPE2`` (TRUSS) and its
``*ELEMENT_BEAM`` rows → ``/TRUSS``.

Radioss DOES have a truss element. ``starter/source/elements/reader/
hm_read_truss.F`` reads ``/TRUSS`` and ``starter/source/properties/truss/
hm_read_prop02.F`` reads ``/PROP/TYPE2``; ``engine/source/elements/truss/
tforc3.F`` integrates it. (``ROADMAP.md``'s muscle item used to say the
opposite — corrected with this batch.)

The ELEMENT block and the PROPERTY are emitted from ``writer/mesh.py``, beside
their ``/BEAM`` and ``/PROP/BEAM`` siblings, so the ``/PART`` they belong to is
written once; everything that is truss-SPECIFIC — the card layouts, the
material-compatibility gate and the two screens the LS-DYNA card needs — lives
here.

The elements are NOT moved into a container of their own: see
``common._truss_secids`` for why the flag beats a second registry.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set, Tuple

from ..state import BeamElem, ConversionState, SectionBeam
from .common import HDR, _f, _i

__all__ = [
    "_TRUSS_LAWS",
    "_emit_prop_truss",
    "_emit_truss_block",
    "_truss_section_is_emittable",
    "_warn_truss_material",
    "_warn_truss_releases",
    "_warn_truss_section_cells",
]


def _emit_truss_block(state: ConversionState, pid: int,
                      elems: List[BeamElem]) -> List[str]:
    """``/TRUSS/<part_ID>`` — THREE cells per row and no more.

    ``radioss41/ELEM/truss.cfg`` (the only ``ELEM/truss.cfg`` in the overlay;
    its newest FORMAT block <= 2022 is ``FORMAT(radioss110)``)::

        HEADER("/TRUSS/%d",PART);
        COMMENT("#  beam_ID  node_ID1  node_ID2");
        FREE_CARD_LIST(COUNT) { CARD("%10d%10d%10d",id,node_ID1,node_ID2); }

    Confirmed against the reader: ``hm_read_truss.F`` uses ``NIXT = 5`` where
    only ``IXT(5)`` (the user id) and ``IXT(2:3)`` (the nodes) come from the
    card — ``IXT(1)`` (material) and ``IXT(4)`` (property) are taken from the
    ``/PART`` at :157-158. There is no third node, no orientation cell and no
    offset cell, so a beam's ``n3`` — whether the deck stated one or
    ``_synthesize_beam_orientation_nodes`` minted it — has nowhere to go and
    nothing to do: a truss has no cross-section frame. dyna2rad reaches the
    same conclusion from the other side (``convertelements.cxx:200``
    ``elemNodes.resize(2)``; :203 guards the whole ``_ORIENTATION``/N3 block
    with ``if (destElem != "/TRUSS")``).

    The ids register in ``state.truss_elem_ids`` AT the line that writes the
    row (the #106 rule) — never derived from ``state.beam_elems``, because a
    beam whose part this loop never visits is not in the deck at all.
    """
    lines = [f"/TRUSS/{pid}", "#  beam_ID  node_ID1  node_ID2"]
    for e in elems:
        lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}")
        state.truss_elem_ids.add(e.eid)
    lines.append(HDR)
    return lines


def _emit_prop_truss(sec: SectionBeam) -> List[str]:
    """``/PROP/TYPE2`` — AREA and GAP, and nothing else.

    ``radioss110/PROP/prop_p2_trus.cfg``, newest FORMAT <= 2022 is
    ``FORMAT(radioss51)``: a title card then ``%20lg%20lg`` = AREA, GAP.
    ``hm_read_prop02.F:110-112`` reads exactly those two into ``GEO(1)`` and
    ``GEO(2) = MAX(ZERO,GAP)``; ``initia.F:3650-3652`` is literally
    ``IF(IGTYP==2)THEN`` / ``C---------- truss, nothing``, so there is no
    ``Ismstr``, no ``dm/df``, no ``Ishear`` and no ``OmegaDof`` on this
    property.

    **GAP is written as 0, always.** It is not a tolerance: a non-zero
    ``GEO(2)`` turns the truss into a COMPRESSION-ONLY gap element —
    ``tforc3.F:184-186`` ``IF (GEO(2,PID(I))>ZERO .AND. GBUF%OFF(I)>ZERO)
    OFF(I)=ZERO`` and :203-206 re-arms the element only once the gap has
    closed. Nothing on ``*SECTION_BEAM`` ELFORM 3 maps to it. (The cfg's
    ``CHECK { GAP > 0.0; }`` contradicts its own ``DEFAULTS { GAP = 0; }``; the
    starter is the authority and clamps a zero or negative gap silently — the
    #115 "a cfg can lie" rule.)

    ``AREA <= 0`` is ``ANCMSG(MSGID=497)`` "TRUSS AREA (%f) IS <= 0.0"
    (:117-124), which is why ``_truss_section_is_emittable`` screens it BEFORE
    this is called.
    """
    return [
        f"/PROP/TYPE2/{sec.secid}",
        sec.title or f"PROP_{sec.secid}",
        "#               AREA             GAP_ini",
        f"{_f(sec.area)}{_f(0.0)}",
        HDR,
    ]


def _truss_section_is_emittable(state: ConversionState,
                                sec: SectionBeam) -> bool:
    """False (with a warning) when ``/PROP/TYPE2`` would be starter ERROR 497.

    ``AREA <= 0`` is the only refusal, and it has exactly one reachable cause:
    ``*SECTION_BEAM`` card 2b, the NAMED standard-section dialect. p.41-9 —
    "Card 2b. Include this card when ELFORM is 2, **3**, or 12 and the first 7
    characters of the card spell out 'SECTION.'" — so an ELFORM 3 section CAN
    state its geometry as ``STYPE D1..D6`` instead of ``A RAMPT STRESS``, and
    ``handlers._beam_card2_kind`` routes it to the ``2b`` branch, which reads no
    area at all. Before this batch such a section became a ``/PROP/BEAM`` with
    Area=0 (ERROR 314); it must not now become a ``/PROP/TYPE2`` with Area=0
    (ERROR 497) — a different id for the same unrunnable deck.

    dyna2rad derives two of the standard sections (``convertprops.cxx:1415-1447``
    — ``SECTION_08`` -> ``pi*D1**2``, ``SECTION_11`` -> ``D1*D2``); that is not
    ported here, because :1420's ``M_PI * pow(lsdD1, 2.0f)`` assumes D1 is a
    RADIUS and no corpus deck exercises either shape. The refusal names the
    remedy instead.
    """
    if sec.area > 0.0:
        return True
    state.warn(
        f"*SECTION_BEAM {sec.secid}: ELFORM=3 is a TRUSS, but the section "
        f"states no positive cross-section AREA (A={sec.area:g}), so its "
        "/PROP/TYPE2 is NOT emitted — hm_read_prop02.F:117-124 raises ERROR "
        "497 'TRUSS AREA IS <= 0.0' on it and the deck would not start. The "
        "usual cause is card 2b, the NAMED standard-section dialect "
        "('SECTION_01'...'STYPE D1..D6'), which states the geometry as "
        "dimensions rather than as an area: k2rad has no path for those. "
        "Restate the section numerically as card 2d 'A RAMPT STRESS'. The "
        "part(s) on this section keep their /PART and their /TRUSS elements, "
        "so the starter will report the missing property (ERROR 178) against "
        "the id named here.")
    return False


def _warn_truss_section_cells(state: ConversionState,
                              secs: List[SectionBeam]) -> None:
    """RAMPT / STRESS — screened, then mapped or named. Never dropped silently,
    and never announced as a loss when the source deck loses them too.

    Vol I R17 p.41-18, verbatim: "RAMPT - Optional ramp-up time for **dynamic
    relaxation**. At the end of the ramp-up time, a uniform stress, STRESS,
    exists in the truss element." The pair is therefore live ONLY while a
    dynamic-relaxation phase runs. ``ex_05_beam_elform_3_&_6.k`` states
    ``RAMPT = STRESS = 1.0`` and has NO ``*CONTROL_DYNAMIC_RELAXATION`` and no
    curve with ``SIDR`` in {1,2} — the cells are inert in LS-DYNA as well, so a
    "DROPPED" message there would be a false alarm (the #125 class).

    When the deck DOES have a relaxation phase and STRESS is non-zero, the
    honest statement is that Radioss expresses the pre-tension elsewhere —
    ``/PRELOAD/AXIAL`` on a ``/GRTRUS`` group (``hm_read_preload_axial.F90:
    284-291`` scans ``ngrtrus`` and sets ``itype = 4``) takes a FORCE, so the
    equivalent is ``STRESS x A``. That is named rather than synthesized: a
    ``/PRELOAD/AXIAL`` needs a curve and a window this card does not state, and
    inventing them would be a fabricated load (the #124 rule).
    """
    stated = [s for s in secs if s.rampt or s.prestress]
    if not stated:
        return
    dr = _has_dynamic_relaxation(state)
    ids = ", ".join(str(s.secid) for s in sorted(stated, key=lambda x: x.secid))
    if not dr:
        state.warn(
            f"*SECTION_BEAM {ids}: card 2d states RAMPT and/or STRESS (the "
            "dynamic-relaxation pre-tension pair, Vol I R17 p.41-18: 'ramp-up "
            "time for dynamic relaxation. At the end of the ramp-up time, a "
            "uniform stress, STRESS, exists in the truss element'). This deck "
            "has NO dynamic-relaxation phase — no *CONTROL_DYNAMIC_RELAXATION "
            "and no *DEFINE_CURVE with SIDR = 1 or 2 — so the pair is INERT in "
            "LS-DYNA too and nothing is lost by leaving it out of "
            "/PROP/TYPE2. Stated here only so the two cells are accounted "
            "for.")
        return
    for s in sorted(stated, key=lambda x: x.secid):
        state.warn(
            f"*SECTION_BEAM {s.secid}: card 2d states RAMPT={s.rampt:g} and "
            f"STRESS={s.prestress:g}, and this deck DOES run a "
            "dynamic-relaxation phase, so the pair is live in LS-DYNA: at the "
            "end of the ramp the truss carries a uniform pre-stress. "
            "/PROP/TYPE2 has no such column and k2rad does NOT synthesize a "
            "substitute — the equivalent Radioss card is /PRELOAD/AXIAL on a "
            "/GRTRUS group (hm_read_preload_axial.F90:284-291 scans ngrtrus "
            "and sets itype = 4), whose Preload is a FORCE: "
            f"STRESS x A = {s.prestress * s.area:g} in deck units. It also "
            "needs a ramp CURVE and a window this card does not state, which "
            "is why the value is named instead of invented. The converted "
            "truss therefore starts UNSTRESSED.")


def _has_dynamic_relaxation(state: ConversionState) -> bool:
    """Does this deck run a dynamic-relaxation phase at all?

    Two independent triggers, both from Vol I R17: an explicit
    ``*CONTROL_DYNAMIC_RELAXATION`` card, and a ``*DEFINE_CURVE`` whose
    ``SIDR`` is 1 (relaxation phase only) or 2 (both phases) — a deck can start
    a relaxation phase from the curve alone (p.17-104).

    ``*CONTROL_DYNAMIC_RELAXATION`` is ``handle_skip``, so the card leaves its
    trace in ``skipped_keywords`` rather than on a state field; that is where
    this reads it, and it is a genuine presence test either way.
    """
    if "CONTROL_DYNAMIC_RELAXATION" in state.skipped_keywords:
        return True
    return any(c.sidr in (1, 2) for c in state.curves.values())


def _warn_truss_releases(state: ConversionState,
                         elems: List[BeamElem]) -> None:
    """``*ELEMENT_BEAM`` RT1/RT2 on a truss — expressible in LS-DYNA,
    unmappable in Radioss, and never droppable in silence.

    "RT1, RT2 - Release conditions for TRANSLATIONS at nodes N1 and N2 ...
    EQ.7: x, y and z (3DOF)" (Vol I R17 p.19-6). ``/TRUSS`` has three cells and
    none of them is a release, so a stated ``RT != 0`` cannot be carried. On a
    truss that is not a partial loss: axial translation is the element's ONLY
    load path, so a released end makes the element carry nothing at all, and
    the converted model is stiffer than the source by exactly that element.

    RR1/RR2 (rotations) and LOCAL are NOT reported: a truss transmits no
    moment, so a rotational release changes nothing, and LOCAL is only the
    FRAME of a stated release. Listing them as "dropped" would be the same
    false alarm the RAMPT screen avoids.
    """
    hit = [e.eid for e in elems if e.rt1 or e.rt2]
    if not hit:
        return
    from .common import _fmt_eid_list
    state.warn(
        f"*ELEMENT_BEAM: {len(hit)} TRUSS element(s) {_fmt_eid_list(hit)} "
        "state a TRANSLATIONAL release (RT1/RT2, Vol I R17 p.19-6) — DROPPED. "
        "/TRUSS carries exactly three cells (id, node_ID1, node_ID2; "
        "truss.cfg + hm_read_truss.F, which takes the material and property "
        "from the /PART) and has no release column. On a truss this is a TOTAL "
        "loss of that element's freedom, not a partial one: axial translation "
        "is its only load path, so LS-DYNA's released end transmits nothing "
        "while the converted /TRUSS is fully connected. Model the release with "
        "a coincident node pair plus a /SPRING (or delete the element) if it "
        "carries the model's kinematics. Rotational releases (RR1/RR2) and "
        "LOCAL are NOT reported: a truss transmits no moment, so they are "
        "inert on both sides.")


# ─────────────────────────────────────────────────────────────────────────────
# /PROP/TYPE2 (IGTYP 2) material compatibility
# ─────────────────────────────────────────────────────────────────────────────

# The Radioss laws a /TRUSS accepts. The gate is on the MATERIAL, not the
# property — the same shape as the /PROP/BEAM table in writer/mesh.py, one
# property type over:
#
#     CASE (4)   ! ITY == 4 = TRUSS
#       IF (MAT_PARAM(IMAT)%PROP_TRUSS == 0) COMPAT_ELEM = .FALSE.
#         — check_mat_elem_prop_compatibility.F:331-335, ERROR 3046
#     CASE (2)   ! IGTYP == 2 = truss property
#       IF (MAT_PARAM(IMAT)%PROP_TRUSS /= 1) COMPAT_PROP = .FALSE.
#         — :373-374, ERROR 3047
#
# ``PROP_TRUSS = 1`` is set only by ``INIT_MAT_KEYWORD(MATPARAM,"TRUSS")``
# (init_mat_keyword.F:269-270). Grepping EVERY such call site under
# starter/source/materials/ gives the complete list — six laws, all
# unconditional:
#
#   LAW0  /MAT/VOID       mat000/hm_read_mat00.F:134
#   LAW1  /MAT/ELAST      mat001/hm_read_mat01.F:149
#   LAW2  PLAS_JOHNS      mat002/hm_read_mat02_jc.F90:382, _zerilli.F90:343,
#                                _predef.F90:393
#   LAW13 RIGID           mat013/hm_read_mat13.F:129
#   LAW34 BOLTZMANN       mat034/hm_read_mat34.F:161
#   LAW44 COWPER          mat044/hm_read_mat44.F:320
#
# Every OTHER law fails a truss. LAW36 (*MAT_024, *MAT_PIECEWISE_LINEAR_
# PLASTICITY — the most common LS-DYNA metal law) is BEAM_INTEGRATED only and
# is NOT on this list, so it is one deck away from a refused truss.
_TRUSS_LAWS = frozenset({0, 1, 2, 13, 34, 44})

# LAW0 (void) and LAW13 (rigid) are on the list and carry NO force by design;
# every other law that reaches the engine's truss dispatch must be one of
# LAW1/2/34/44, because tforc3.F:189-224 is a closed IF/ELSEIF chain with NO
# default arm — an MTN outside it never writes GBUF%FOR and the truss carries
# exactly zero force at zero diagnostics. The starter gate above is the only
# thing between a deck and that outcome, which is why the warning below fires
# on the CONVERTED law rather than on the LS-DYNA keyword.
_TRUSS_ZERO_FORCE_LAWS = frozenset({0, 13})


def _warn_truss_material(state: ConversionState,
                         part_secids: Dict[int, int],
                         truss_pids: Set[int],
                         emitted_truss_secids: Set[int]) -> None:
    """Name every truss part whose material converts to a law ``/TRUSS``
    rejects — the twin of ``mesh._warn_beam_type3_material``.

    Driven by *emitted_truss_secids*, the sections that ACTUALLY wrote a
    ``/PROP/TYPE2``, COLLECTED in the emit loop rather than re-derived: a
    section refused by ``_truss_section_is_emittable`` never enters the set and
    is never warned about twice.
    """
    if not emitted_truss_secids:
        return
    from .mesh import _target_mat_law
    groups: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    inert: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for pid in sorted(truss_pids):
        part = state.parts.get(pid)
        if part is None or part_secids.get(pid) not in emitted_truss_secids:
            continue
        law = _target_mat_law(state, part.mid)
        # None = k2rad emits no /MAT for this id at all, which is a different
        # (and already reported) problem; do not guess a law for it.
        if law is None:
            continue
        if law in _TRUSS_ZERO_FORCE_LAWS:
            inert[(part.mid, law)].append(pid)
        elif law not in _TRUSS_LAWS:
            groups[(part.mid, law)].append(pid)
    for (mid, law), pids in sorted(inert.items()):
        plural = "s" if len(pids) > 1 else ""
        state.warn(
            f"*SECTION_BEAM ELFORM=3 (TRUSS): part{plural} "
            + ", ".join(str(p) for p in pids)
            + f" carry mid {mid}, which converts to /MAT/LAW{law} — a law the "
            "starter DOES accept on a /TRUSS "
            "(INIT_MAT_KEYWORD(...,'TRUSS')) but whose engine arm carries NO "
            "FORCE by design (tforc3.F:189-224 dispatches only MTN 1, 2, 34 "
            "and 44; LAW0 is void and LAW13 is rigid). The elements exist, "
            "have mass and a time step, and transmit nothing.")
    if not groups:
        return
    entries = []
    for (mid, law), pids in sorted(groups.items()):
        plural = "s" if len(pids) > 1 else ""
        entries.append(
            f"part{plural} " + ", ".join(str(p) for p in pids)
            + f" on mid {mid} (/MAT/LAW{law})")
    state.warn(
        "*SECTION_BEAM ELFORM=3 (TRUSS): " + "; ".join(entries)
        + ". A /TRUSS accepts ONLY the laws that declare "
        "INIT_MAT_KEYWORD(MATPARAM,'TRUSS') — LAW0 (VOID), LAW1 (ELAST), LAW2 "
        "(PLAS_JOHNS), LAW13 (RIGID), LAW34 (BOLTZMANN) and LAW44 (COWPER), "
        "the complete list of call sites under starter/source/materials/. "
        "Anything else is refused by "
        "check_mat_elem_prop_compatibility.F:331-335 (ERROR 3046, "
        "'ELEMENTS OF TYPE TRUSS ARE NOT COMPATIBLE WITH MATERIAL ID n') and "
        ":373-374 (ERROR 3047 on the property), so the deck will not start. "
        "*MAT_PIECEWISE_LINEAR_PLASTICITY -> /MAT/LAW36 is the common case and "
        "is BEAM_INTEGRATED only. Restate the material as "
        "*MAT_PLASTIC_KINEMATIC (LAW44) or *MAT_ELASTIC (LAW1), or model the "
        "member as an ELFORM=2 beam, which takes a wider law set.")
