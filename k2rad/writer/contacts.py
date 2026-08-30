"""Starter interfaces: TYPE7/TYPE25 contacts, force transducers, TYPE2 tied contacts."""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Set, Tuple
from ..state import ConversionState, PartData
from .common import (
    HDR,
    _emit_grnod_node,
    _emit_line_seg,
    _emit_line_surf,
    _emit_surf_part,
    _emit_surf_seg,
    _f,
    _i,
    _make_master_surface,
    _ordered_unique_nodes,
    _part_node_sets,
)

__all__ = [
    "_resolve_contact_slave",
    "_resolve_contact_master",
    "_contact_master_pids",
    "_solid_contact_master_pids",
    "_warn_implicit_solid_contact_np1",
    "_side_has_deformable_part",
    "deformable_deformable_inter_ids",
    "_recipe_active",
    "_warn_deformable_deformable_contact",
    "_gapmin_override",
    "_sfs_to_stfac",
    "_stfac_for",
    "_describe_empty_secondary",
    "_warn_partial_rigid_secondary",
    "_drop_interface",
    "_note_dropped_interfaces",
    "_make_interfaces",
    "_select_parent_interface",
    "_contact_slave_pids",
    "_match_parent_interface",
    "_transducer_side_pids",
    "_part_node_ids",
    "_make_force_transducers",
    "_ignore_to_inacti",
    "_vdc_to_viss",
    "_sst_mst_to_gapmin",
    "_emit_inter_type7",
    "_emit_inter_type25_self",
    "_emit_inter_type25",
    "_emit_inter_type11",
    "_emit_inter_type19",
    "_TYPE25_IDEL",
    "_TYPE25_DEFAULT_VISS",
    "_FRIC_ID_TYPES",
    "_bind_friction_table",
    "_contact_friction",
    "_type25_viss",
    "_type25_stfac",
    "_type25_istf_iedge",
    "_type25_surface",
    "_solid_pids_by_part",
    "_warn_eroding_card4",
    "_warn_eroding_smp_friction",
    "_make_type25_interfaces",
    "_segment_set_edges",
    "_general_line_group",
    "_make_general_interfaces",
    "_TIED_SPOTFLAG",
    "_TIED_DSEARCH_MARGIN",
    "_emit_inter_type2",
    "_tied_interface_type",
    "_emit_inter_type10",
    "_tied_slave_nids",
    "_tied_master_surface",
    "_tied_dsearch",
    "_make_tied_interfaces",
    "_SPOTWELD_SPOTFLAG",
    "_SPOTWELD_IDEL2",
    "_SPOTWELD_DSEARCH_FRACTION",
    "_spotweld_dsearch",
    "_spotweld_slave_nids",
    "_make_spotweld_interfaces",
]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: interfaces
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_contact_slave(state: ConversionState, sid: int, styp: int,
                           rigid_nodes: Set[int], out_lines: List[str],
                           diag: Optional[Dict[str, int]] = None) -> int:
    """Emit the /GRNOD for a contact SECONDARY side; 0 when nothing is left.

    ``diag``, when given, is filled with ``raw`` (nodes the side resolved to
    before filtering), ``rigid_removed`` (how many of those were dropped for
    belonging to a rigid body) and ``clean`` (what actually reached the
    /GRNOD). A caller that gets 0 back needs that breakdown to tell the user
    WHY: "ssid names nothing" and "ssid is a rigid platen" are different
    mistakes with different remedies, and returning a bare 0 for both is how
    this drop stayed invisible. See _describe_empty_secondary.
    """
    nids = set()
    def add_part_nodes(pid: int):
        for e in state.shell_elems:
            if e.pid == pid: nids.update(e.nodes)
        for e in state.solid_elems:
            if e.pid == pid: nids.update(e.nodes)
        # Thick shells are /BRICK in the emitted deck, so a *PART of them is a
        # perfectly good contact side. The container is empty on every deck
        # without *ELEMENT_TSHELL, so this cannot move any other conversion.
        for e in state.tshell_elems:
            if e.pid == pid: nids.update(e.nodes)
        # A 1D SEATBELT is a /SPRING, but it is the one spring family that
        # genuinely belongs on a contact SECONDARY side: LS-DYNA gives
        # *SECTION_SEATBELT its own AREA and THICK for exactly that, and a
        # shoulder belt that does not touch the occupant restrains nothing.
        # Without this, SSTYP=2/3 (part / part set) over a belt part resolves
        # to ZERO nodes and only the *SET_NODE spelling reaches the webbing —
        # the SPH situation before the SPH batch, one family further on. (2D
        # belt elements are folded into state.shell_elems by
        # seatbelts._assign_seatbelt_props and are covered by the walk above.)
        for e in state.seatbelt_elems:
            if e.pid == pid and not e.is_2d:
                nids.update((e.n1, e.n2))
        # SPH particles are deformable by construction and belong on the
        # SECONDARY (node) side of any contact that scopes their part. This is
        # what makes SSTYP=2/3 (part / part set) work at all; before the SPH
        # batch only the *SET_NODE spelling reached them, and then only by
        # accident. They are deliberately NOT added to the MAIN-surface route
        # (_solid_contact_master_pids / _solid_pids_by_part): a particle has no
        # face to build a /SURF from.
        for c in state.sph_elems:
            if c.pid == pid: nids.update(c.nodes)

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

    raw_nids = [n for n in sorted(nids) if n > 0]
    clean_nids = [n for n in raw_nids if n not in rigid_nodes]
    if diag is not None:
        diag["raw"] = len(raw_nids)
        diag["rigid_removed"] = len(raw_nids) - len(clean_nids)
        diag["clean"] = len(clean_nids)
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
    # Thick shells are /BRICK, so a thick-shell part on a contact MAIN side
    # wants the same /SURF/PART/EXT (external surface of a solid part) an
    # ordinary brick part gets. Empty on every deck without *ELEMENT_TSHELL.
    #
    # SPH parts are deliberately NOT here. A particle has no face, so
    # /SURF/PART/EXT over an SPH part is a surface over nothing; in Radioss an
    # SPH<->structure contact is a /INTER/TYPE7 (or TYPE25) with the PARTICLES
    # as the SECONDARY node group, which is the side they DO join (see
    # add_part_nodes / _part_node_ids). _make_master_surface names the loss when
    # a contact's MAIN scope reaches an SPH-only part.
    all_solid_pids = ({e.pid for e in state.solid_elems}
                      | {e.pid for e in state.tshell_elems})
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
    for c in state.contacts_type25:
        out |= _contact_master_pids(state, c.ssid, c.sstyp) & all_solid_pids
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
        "when run multi-domain. RUN THIS DECK WITH np=1 (one MPI domain) — the "
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


# -----------------------------------------------------------------------------
# Never drop an interface silently
#
# A /INTER that is not emitted changes the PHYSICS of the converted model: the
# two surfaces stop interacting, the load path disappears, and the run does not
# fail — it produces a plausible-looking answer that is wrong. That is strictly
# worse than a missing output card, so every path in this module that declines
# to emit an interface must (a) warn with an actionable message and (b) register
# the loss in the conversion log's accounting via note_recognized_not_emitted(),
# so "skipped : 0 unsupported keyword(s)" can no longer coexist with a missing
# /INTER. The helpers below are that single choke point.
# -----------------------------------------------------------------------------

#: What a dropped interface costs the user; appended to every drop message.
_DROP_CONSEQUENCE = (
    "PHYSICAL CONSEQUENCE: these two surfaces will NOT interact in the "
    "converted model — they pass through each other, the load path is "
    "missing, and the run does not fail: the reaction force simply stays flat "
    "(or appears only once the parts overlap by their full thickness) while "
    "internal and contact energy climb."
)

#: Why an all-rigid secondary side is a side-order mistake, not a modelling one.
_RIGID_SECONDARY_REMEDY = (
    "REMEDY: swap the sides — put the DEFORMABLE part on the SECONDARY (SSID) "
    "side and the rigid part on the MAIN (MSID) side. /INTER/TYPE7 is an "
    "asymmetric node-to-surface contact, so the deformable side is the one "
    "that must supply the tracked nodes. k2rad deliberately does NOT swap them "
    "for you: that would silently convert a model different from the one you "
    "wrote."
)


def _describe_empty_secondary(diag: Dict[str, int], sid: int, styp: int) -> str:
    """One clause explaining why a contact SECONDARY side produced no nodes."""
    raw = diag.get("raw", 0)
    removed = diag.get("rigid_removed", 0)
    if raw == 0:
        return (f"the SECONDARY (SSID) side ssid={sid} sstyp={styp} resolved to "
                "no nodes at all — it names no part, part set or node set that "
                "carries shell/solid elements in this deck")
    if removed == raw:
        return (f"the SECONDARY (SSID) side ssid={sid} sstyp={styp} resolved to "
                f"{raw} node(s) and ALL {raw} of them belong to a rigid body (a "
                "*MAT_RIGID part or a *CONSTRAINED_*_RIGID_BODY), leaving an "
                "empty secondary node group — a rigid loading platen or "
                "impactor placed on the secondary side is the usual cause")
    return (f"the SECONDARY (SSID) side ssid={sid} sstyp={styp} resolved to "
            f"{raw} node(s), of which {removed} were rigid-body nodes, leaving "
            "an empty secondary node group")


def _warn_partial_rigid_secondary(state: ConversionState, keyword: str,
                                  inter_id: int, diag: Dict[str, int],
                                  sid: int) -> None:
    """Flag a secondary side that KEPT its interface but lost some nodes.

    The same filter that empties an all-rigid side quietly thins a mixed one.
    The interface is still emitted (so this warns rather than dropping), but the
    share of the contact those rigid nodes carried is gone from the converted
    model and the user is entitled to know."""
    removed = diag.get("rigid_removed", 0)
    if removed <= 0 or removed == diag.get("raw", 0):
        return
    state.warn(
        f"*{keyword or 'CONTACT'} {inter_id}: {removed} of the "
        f"{diag.get('raw', 0)} node(s) on the SECONDARY side (ssid={sid}) "
        "belong to a rigid body and were removed from the secondary node "
        f"group; the interface is emitted with the remaining "
        f"{diag.get('clean', 0)} node(s). Those rigid nodes carry no contact in "
        "the converted model — if that part of the surface is load-bearing, "
        "make it the MAIN (MSID) side of its own contact instead."
    )


def _drop_interface(state: ConversionState, dropped: Dict[str, List[int]],
                    keyword: str, inter_id: int, cause: str,
                    remedy: str) -> None:
    """Record an interface k2rad refused to emit: loud warning + accounting.

    ``dropped`` accumulates ``{keyword: [inter_id, ...]}`` for
    _note_dropped_interfaces, which turns it into the conversion log's
    "Recognized but not emitted" entry. Never drop an interface without going
    through here."""
    kw = keyword or "CONTACT"
    state.warn(
        f"*{kw} {inter_id}: {cause}, so NO /INTER was emitted for this "
        f"contact. {_DROP_CONSEQUENCE} {remedy}"
    )
    dropped.setdefault(kw, []).append(inter_id)
    # Also record it model-wide. /TH/INTER is built from the PARSED contact
    # records, so without this a dropped interface is still listed and the
    # starter answers WARNING 257 "NONEXISTENT INTER <id>". Every contact
    # writer drops through here and all of them run before starter_th_inter in
    # the section registry, so the set is complete by the time it is read.
    state.dropped_inter_ids.add(inter_id)


def _note_dropped_interfaces(state: ConversionState,
                             dropped: Dict[str, List[int]]) -> None:
    """Fold the dropped interfaces into the conversion log's accounting.

    One entry per *CONTACT spelling (note_recognized_not_emitted deduplicates on
    the keyword), naming every interface id that was lost, so the log's summary
    counts the loss instead of reporting a clean conversion."""
    for kw, ids in sorted(dropped.items()):
        state.note_recognized_not_emitted(
            kw,
            f"{len(ids)} contact(s) produced no /INTER (interface id(s) "
            f"{sorted(ids)}): a contact side resolved to no usable geometry, so "
            "those surfaces do not interact in the converted model. See the "
            "per-interface warnings for the cause and the remedy."
        )


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

    # Interfaces this pass could not emit, {keyword: [inter_id, ...]}. Filled
    # only through _drop_interface (which also warns) and folded into the
    # conversion log's accounting by _note_dropped_interfaces at the end.
    dropped: Dict[str, List[int]] = {}

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
        | {n for e in state.tshell_elems          # /BRICK too — see above
           if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
           for n in e.nodes if n > 0 and n not in rigid_nodes}
        | {n for c in state.sph_elems             # SPH: deformable by nature
           if state.parts.get(c.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
           for n in c.nodes if n > 0 and n not in rigid_nodes}
        | {n for e in state.seatbelt_elems        # 1D belt — see above
           if not e.is_2d
           and state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
           for n in (e.n1, e.n2) if n > 0 and n not in rigid_nodes}
    )
    all_pids: List[int] = sorted(state.parts.keys())

    for c in state.contacts_single:
        if c.ssid == 0:
            if not all_deformable_nodes or not all_pids:
                _drop_interface(
                    state, dropped, c.keyword, c.inter_id,
                    "it is an all-parts self-contact (SSID=0) but the deck has "
                    + ("no parts at all" if not all_pids else
                       "no deformable nodes left for the secondary side (every "
                       "shell/solid node belongs to a rigid body)"),
                    "REMEDY: a self-contact needs at least one deformable part "
                    "to supply the tracked nodes. If the model really is "
                    "all-rigid, replace the self-contact with an explicit "
                    "surface-to-surface contact between the rigid parts, or "
                    "give the impacted part a deformable material.")
                continue
            if not state.is_implicit:
                # EXPLICIT: surfa=0 self-contact → native-style /INTER/TYPE25 over ONE
                # all-parts surface (self-impact). The TYPE7 node→surface path (below)
                # makes only the deformable nodes secondary against a master surface —
                # an asymmetric ~half-model contact that the native reader does NOT
                # produce; in explicit dynamics the driven part blows through it and the
                # model flies apart. TYPE25 self-contact reproduces the native scope and
                # holds the load path. Kept TYPE7 only for implicit (validated recipe).
                state.warn(
                    f"*CONTACT_AUTOMATIC_SINGLE_SURFACE {c.inter_id}: explicit analysis "
                    "→ /INTER/TYPE25 all-parts self-contact (matches the native "
                    "OpenRadioss reader; TYPE7 node→surface is kept for implicit only)."
                )
                self_surf = state.next_id()
                lines += _emit_surf_part(self_surf, f"contact_{c.inter_id}_self", all_pids)
                fric, fric_id = _contact_friction(
                    state, c.fs, c.fd, c.inter_id, c.keyword, "TYPE25")
                lines += _emit_inter_type25_self(
                    c.inter_id, c.title, self_surf, fric,
                    _ignore_to_inacti(c.ignore, state, c.inter_id, 0.0),
                    _stfac_for(state, c.sfs, c.inter_id) or 1.0,
                    fric_id=fric_id)
                continue
            # IMPLICIT: keep the validated TYPE7 node→surface (deformable-contact recipe).
            slav_grnod = state.next_id()
            mast_surf = state.next_id()
            lines += _emit_grnod_node(slav_grnod, f"contact_{c.inter_id}_slave", all_deformable_nodes)
            if not _make_master_surface(state, mast_surf, f"contact_{c.inter_id}_master",
                                        all_pids, lines):
                _drop_interface(
                    state, dropped, c.keyword, c.inter_id,
                    "it is an all-parts self-contact (SSID=0) but no contact "
                    f"surface could be built from the deck's {len(all_pids)} "
                    "part(s) — none of them carries shell or solid elements a "
                    "/SURF can be made from",
                    "REMEDY: check that the parts this contact is meant to "
                    "cover actually have *ELEMENT_SHELL / *ELEMENT_SOLID "
                    "elements in the deck.")
                continue
            gapmin = _gapmin_override(state, c.inter_id,
                                      _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id),
                                      gapmin_overrides)
            fric, fric_id = _contact_friction(
                state, c.fs, c.fd, c.inter_id, c.keyword, "TYPE7")
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, fric,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin),
                                       viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                       gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id),
                                       fric_id=fric_id)
        else:
            diag: Dict[str, int] = {}
            slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes,
                                                lines, diag=diag)
            mast_surf = _resolve_contact_master(state, c.ssid, c.sstyp, lines)
            if not slav_grnod:
                _drop_interface(state, dropped, c.keyword, c.inter_id,
                                _describe_empty_secondary(diag, c.ssid, c.sstyp),
                                _RIGID_SECONDARY_REMEDY
                                if diag.get("raw") else
                                "REMEDY: check that SSID names a part, part set "
                                "or node set that exists in this deck and "
                                "carries elements.")
                continue
            if not mast_surf:
                _drop_interface(
                    state, dropped, c.keyword, c.inter_id,
                    f"the MAIN side sid={c.ssid} styp={c.sstyp} resolved to no "
                    "contact surface (it names no part or part set carrying "
                    "shell/solid elements)",
                    "REMEDY: point the contact at a part or part set that "
                    "exists in this deck; a *SET_NODE or *SET_SEGMENT cannot "
                    "supply the main surface of this interface.")
                continue
            _warn_partial_rigid_secondary(state, c.keyword, c.inter_id, diag, c.ssid)
            gapmin = _gapmin_override(state, c.inter_id,
                                      _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id),
                                      gapmin_overrides)
            fric, fric_id = _contact_friction(
                state, c.fs, c.fd, c.inter_id, c.keyword, "TYPE7")
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, fric,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin),
                                       viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                       gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id),
                                       fric_id=fric_id)

    for c in state.contacts_surf2surf:
        diag = {}
        slav_grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes,
                                            lines, diag=diag)
        mast_surf = _resolve_contact_master(state, c.msid, c.mstyp, lines)
        if not slav_grnod:
            _drop_interface(state, dropped, c.keyword, c.inter_id,
                            _describe_empty_secondary(diag, c.ssid, c.sstyp),
                            _RIGID_SECONDARY_REMEDY
                            if diag.get("raw") else
                            "REMEDY: check that SSID names a part, part set or "
                            "node set that exists in this deck and carries "
                            "elements.")
            continue
        if not mast_surf:
            _drop_interface(
                state, dropped, c.keyword, c.inter_id,
                f"the MAIN (MSID) side msid={c.msid} mstyp={c.mstyp} resolved "
                "to no contact surface (it names no part or part set carrying "
                "shell/solid elements)",
                "REMEDY: point MSID at a part or part set that exists in this "
                "deck; a *SET_NODE or *SET_SEGMENT cannot supply the main "
                "surface of a /INTER/TYPE7.")
            continue
        _warn_partial_rigid_secondary(state, c.keyword, c.inter_id, diag, c.ssid)
        gapmin = _gapmin_override(state, c.inter_id,
                                  _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id),
                                  gapmin_overrides)
        inacti = (5 if c.inter_id in recipe_inacti_ids
                  else _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin))
        fric, fric_id = _contact_friction(
            state, c.fs, c.fd, c.inter_id, c.keyword, "TYPE7")
        lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, fric,
                                   inacti,
                                   viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                   gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id),
                                   fric_id=fric_id)

    for iid, val in sorted(gapmin_overrides.items()):
        state.warn(
            f"--inter-gapmin {iid}={val:g}: no /INTER/TYPE7/{iid} was emitted "
            "(unknown interface id) — override ignored. Use the id printed in the "
            ".rad (auto-assigned contacts are numbered from 90001 in definition "
            "order)."
        )

    _note_dropped_interfaces(state, dropped)
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

    Every candidate is filtered through ``state.dropped_inter_ids``: a contact
    whose side resolved to nothing is registered there and NO /INTER was
    written for it, so parenting on it is a dangling reference — starter
    ERROR 581 from /INTER/SUB, or WARNING 257 "NONEXISTENT INTER" from the
    /TH/INTER block that also calls this. All FIVE contact writers — interfaces,
    general_interfaces, type25_interfaces, tied_interfaces, spotweld_interfaces
    (writer/assembly.py registry positions 19-23) — run before both call sites
    (force_transducers 24, starter_th_inter 60), so the set is complete here.
    """
    def live(c) -> bool:
        return c.inter_id not in state.dropped_inter_ids

    for c in state.contacts_single:
        if c.ssid == 0 and live(c):
            return c.inter_id
    for c in state.contacts_single:
        if live(c):
            return c.inter_id
    for c in state.contacts_surf2surf:
        if live(c):
            return c.inter_id
    # /INTER/TYPE25 hosts an /INTER/SUB the same way TYPE7 does, but only when
    # it actually has a main surface — the ILEV=3 one-way node-to-surface form
    # (surf_ID1=0) has no secondary SEGMENTS for a sub-interface to sit on.
    for c in state.contacts_type25:
        if c.variant != "NODES_TO_SURFACE" and live(c):
            return c.inter_id
    # A SOFT-routed general contact is also a real interface a transducer can
    # parent on (before the SOFT-routing split, AUTOMATIC_GENERAL lived in
    # contacts_single and was picked up here). /INTER/SUB needs a surface-based
    # parent, so offer only the surface routes (-7 → TYPE7, -19 → TYPE19); a
    # -11 edge/line interface cannot host an /INTER/SUB.
    for c in state.contacts_general:
        if c.soft in (-7, -19) and live(c):
            return c.inter_id
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
    for c in state.contacts_type25:
        if c.variant == "NODES_TO_SURFACE":
            continue        # ILEV=3 has no secondary segments (see _select_parent_interface)
        main_sid, main_styp = ((c.ssid, c.sstyp) if c.variant == "SINGLE_SURFACE"
                               else (c.msid, c.mstyp))
        candidates.append((c.inter_id,
                           _contact_master_pids(state, main_sid, main_styp),
                           _contact_slave_pids(state, c.ssid, c.sstyp)))

    # An interface the writers refused to emit is not in the deck, so it cannot
    # parent anything — see _select_parent_interface.
    for inter_id, mast, slav in candidates:
        if inter_id in state.dropped_inter_ids:
            continue
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
    for e in state.tshell_elems:              # /BRICK too — see above
        if e.pid in pidset:
            nodes.update(n for n in e.nodes if n > 0)
    for c in state.sph_elems:                 # SPH: the particle IS its node
        if c.pid in pidset:
            nodes.update(n for n in c.nodes if n > 0)
    for e in state.seatbelt_elems:            # 1D belt — see _resolve_contact_slave
        if e.pid in pidset and not e.is_2d:
            nodes.update(n for n in (e.n1, e.n2) if n > 0)
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
    skipped_ft: List[int] = []

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
            skipped_ft.append(ft.inter_id)
            continue

        sec_nodes = _part_node_ids(state, sec_pids, rigid_nodes)
        if not sec_nodes:
            state.warn(
                f"CONTACT_FORCE_TRANSDUCER {ft.inter_id}: secondary side has no "
                "deformable nodes (parts may be all-rigid) -> skipped."
            )
            skipped_ft.append(ft.inter_id)
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
            skipped_ft.append(ft.inter_id)
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

    # Read-out caveat (emitted once when any transducer was written).
    #
    # The T01 contact channels are a time INTEGRAL of the force, not the force:
    # engine/source/interfaces/int07/i7for3.F:1443 heads the block "SAUVEGARDE
    # DE L'IMPULSION NORMALE" and :1459-1476 accumulates IMPX = F*DT12 into
    # FSAV(1..3) (tangential at :3055-3079, /INTER/SUB at :1559-1561);
    # engine/source/output/th/thkin.F:56 writes FSAV out undivided, and nothing
    # resets it on the writing rank (hist2.F:616-622 zeroes FSAV only for
    # ISPMD/=0; sortie_main.F:1945 resets only monvol, FSAV(26), FSAV(29)).
    #
    # This corrects the earlier wording here, which was right that the channel
    # is "impulse-scaled" but wrong that a CONSTANT recovers the force. There
    # is no universal factor: the ratio between the raw channel and the force
    # is the elapsed accumulation time, which grows as the run goes on. The
    # "x2 recovered the applied load to ~1%" observation was one deck at one
    # instant, not a conversion rule. The dimensionally correct recovery is
    # d(FNX)/dt across T01 samples — tools/th_to_csv.py writes that column.
    if state.th_sub_ids:
        state.warn(
            "Force-transducer read-out: OpenRadioss writes contact "
            "(sub-)interface forces to the T01 as a time-ACCUMULATED IMPULSE "
            "(force x time), not as a force — the engine adds F*dt every cycle "
            "(i7for3.F:1459-1476, comment 'SAUVEGARDE DE L'IMPULSION NORMALE') "
            "and never resets it on the writing rank. Recover the force by "
            "differentiating with respect to time (F = d(FNX)/dt, e.g. "
            "numpy.gradient, or tools/th_to_csv.py which writes the "
            "differentiated column); there is NO constant correction factor — "
            "the ratio is the elapsed accumulation time and grows with the "
            "run, so an earlier 'multiply by about 2' rule of thumb only held "
            "at one instant of one deck. HyperView/HyperGraph convert on read; "
            "the applied *LOAD_RIGID_BODY / reaction remains a good "
            "cross-check."
        )

    if skipped_ft:
        state.note_recognized_not_emitted(
            "CONTACT_FORCE_TRANSDUCER",
            f"{len(skipped_ft)} transducer(s) produced no /INTER/SUB (id(s) "
            f"{sorted(skipped_ft)}): no usable parent interface, secondary "
            "node group or main surface. The requested contact-force channel "
            "is missing from the T01 — see the per-transducer warnings.")
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
            f"CONTACT {inter_id}: ignore={ignore} mapped to Inacti=5 "
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
    # ``ignore={ignore}``, not a hard-coded 0: any value outside {0,1,2} lands
    # here too, and printing "ignore=0" for it would state a fact the deck does
    # not contain. Renders identically for the 0 that reaches it in practice.
    state.warn(
        f"CONTACT {inter_id}: ignore={ignore} mapped to Inacti=5. LS-DYNA "
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
                       inter_id: int, target: str = "TYPE7") -> float:
    """Map LS-DYNA *CONTACT Card3 SST/MST (optional contact thickness per side)
    → OpenRadioss /INTER/<target> Gapmin (``target`` names the interface in the
    log; the mapping is identical for TYPE7/TYPE10/TYPE11/TYPE19).

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
            f"CONTACT {inter_id}: SST/MST contact thickness -> /INTER/{target} "
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
                      gapmin: float = 0.0, stfac: float = 0.0,
                      istf: int = 4, igap: int = 0,
                      fric_id: int = 0) -> List[str]:
    # istf/igap default to the ordinary single-surface/surf2surf values (Istf=4
    # minimum stiffness, Igap=0 constant gap) so those validated paths stay
    # byte-identical. The SOFT=-7 AUTOMATIC_GENERAL route overrides them to
    # Istf=2, Igap=2 to match dyna2rad's routed TYPE7 (convertcontacts.cxx map
    # cc:52 Igap=2, and cc:626 Istf=2 for SOFT<1).
    #
    # Card 6 is `%10d%10d%20lg%10d%10d%10d%20lg%10d` at radioss2020 (the FORMAT
    # /BEGIN 2022 selects — inter_type7.cfg has no newer block): Ifric Ifiltr
    # Xfreq Iform sens_ID fct_IDF AscaleF **fric_ID**, so the /FRICTION binding
    # lives in cols 91-100. The three trailing columns are only written when a
    # table is actually bound, which keeps every fric_ID-free deck byte-identical.
    fric_card = "         0         0                   0         2         0"
    if fric_id:
        fric_card += f"         0{_f(0.0)}{_i(fric_id)}"
    return [
        f"/INTER/TYPE7/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "#  Slav_id   Mast_id      Istf      Ithe      Igap                Ibag      Idel     Icurv      Iadm",
        f"{_i(slav_id)}{_i(mast_id)}{_i(istf)}         0{_i(igap)}                   0         2         0         0",
        "#          Fscalegap             GAP_MAX             Fpenmax",
        "                   0                   0                   0",
        "#              Stmin               Stmax          %mesh_size               dtmin  Irem_gap",
        "                1000                   0                   0                   0         0",
        "#              Stfac                Fric              Gapmin              Tstart               Tstop",
        f"{_f(stfac)}{_f(fric)}{_f(gapmin)}                   0                   0",
        "#      IBC                        Inacti                VisS                VisF              Bumult",
        f"       000{_i(inacti, 30)}{_f(viss)}{_f(visf)}                   0",
        ("#    Ifric    Ifiltr               Xfreq     Iform   sens_ID   fct_IDF"
         "             AscaleF   fric_ID" if fric_id else
         "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID"),
        fric_card,
        HDR,
    ]


def _emit_inter_type25_self(inter_id: int, title: str, surf_id: int, fric: float,
                            inacti: int = 5, stfac: float = 1.0,
                            fric_id: int = 0) -> List[str]:
    """*CONTACT_AUTOMATIC_SINGLE_SURFACE → /INTER/TYPE25 self-contact (explicit).

    surf_id is ONE surface (surf_ID1); surf_ID2=0 → self-impact, so every segment
    of the surface contacts every node of the same surface (symmetric). This is
    how the native OpenRadioss reader converts ASS; the TYPE7 node-group→surface
    k2rad emits otherwise is an asymmetric ~half-model contact whose driven part
    blows through, flying the model apart in explicit dynamics. Params match the
    native TYPE25 echo: Istf=4, Igap=2, Iedge=1000 (no edge), Inacti from ignore,
    Stfac, Coulomb Fric.

    NB there are TWO hand-written /INTER/TYPE25 layouts in this module — this
    one and :func:`_emit_inter_type25`, which the eroding / node-to-surface
    families use. They differ deliberately: this one writes the radioss2026
    card-1 width (100 cols, with the trailing IPSTIF column) and spells the
    "take the default" values out (Gap_max_s/m = 1e30, Igap0 = 1000,
    Stmax = 1e30, card-6 header labelled DTSTIF), while _emit_inter_type25
    writes the radioss2022 width (90) and leaves those fields 0 — which the
    starter turns back into exactly the same values (2022 Reference Guide
    p.366; ``hm_read_inter_type25.F:539,565,566``). Behaviourally equivalent at
    /BEGIN 2022, confirmed by the starter echo (MAXIMUM STIFFNESS 1.0E+30 both
    ways), but KEEP THEM IN SYNC: a column added to one belongs in the other.
    They stay separate only because merging them would rewrite the bytes of the
    solver-validated *CONTACT_AUTOMATIC_SINGLE_SURFACE path for no gain.
    """
    return [
        f"/INTER/TYPE25/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "# surf_ID1  surf_ID2      Istf      Ithe      Igap   Irem_i2                Idel     Iedge    IPSTIF",
        f"{_i(surf_id)}         0         4         0         2         0                   2      1000         0",
        "# grnd_IDs                     Gap_scale          %mesh_size           Gap_max_s           Gap_max_m",
        "         0                           1.0                   0                1e30                1e30",
        "#              Stmin               Stmax     Igap0    Ishape          Edge_angle          STFAC_MDT",
        "                   0                1e30      1000         0                   0                   0",
        "#              Stfac                Fric           Tpressfit              Tstart               Tstop",
        f"{_f(stfac)}{_f(fric)}                   0                   0                   0",
        "#      IBC               IVIS2    Inacti                VISs    Ithick                          Pmax",
        f"       000                   0{_i(inacti)}                0.05         0                             0",
        "#    Ifric    Ifiltr               Xfreq             sens_ID              DTSTIF             fric_ID",
        f"         0         0                   0                   0                   0{_i(fric_id, 20)}",
        HDR,
    ]


#: /INTER/TYPE25 Idel. 2 = "when A 4-node shell, 3-node shell or solid element
#: is deleted, the corresponding segment is removed from the main side"
#: (radioss2022/INTER/inter_type25.cfg:230-236); 1 is the ALL-quorum variant
#: (the segment survives until EVERY attached element is gone).
#:
#: dyna2rad writes Idel=1 for every TYPE25 — a copy of its per-type default
#: table (convertcontacts.cxx:47) with no eroding-specific logic at all.
#:
#: WHAT ACTUALLY MATTERS on the eroding path is only that Idel be > 0: that is
#: the flag which ARMS solid erosion (``i25surfi.F:607-625`` sets IPARI(100)=1
#: on ``IDEL > 0 .AND. SOLID_SEGMENT > 0``). Once it is armed, 1 and 2 are
#: EQUIVALENT — ``check_surface_state.F:138`` defines
#:     TYPE_INTER = (ITY==7 .OR. 10 .OR. 22 .OR. 24 .OR.
#:                   (IPARI(100,NIN)==0 .AND. ITY==25))
#: so a TYPE25 with erosion armed has TYPE_INTER false, the ``IDEL==2`` branch
#: at :170 is unreachable, and :155 takes the ``IPARI(100)/=0 .AND. ITY==25``
#: half regardless of Idel. Do NOT read the two engine branches as an Idel
#: 1-vs-2 switch on an eroding contact; they are not.
#:
#: k2rad still writes 2, for the case where Idel IS observable — a TYPE25 whose
#: main side carries no solids (IPARI(100)==0, TYPE_INTER true). There 2
#: reproduces LS-DYNA's per-element segment removal, while 1 keeps the segment
#: alive until EVERY attached element is gone (the CHECK_ACTIVE_ELEM_EDGE
#: ALL-quorum). It is also already the k2rad convention on every other penalty
#: interface (_emit_inter_type7, _emit_inter_type25_self, _emit_inter_type11).
_TYPE25_IDEL = 2


def _emit_inter_type25(inter_id: int, title: str, surf_id1: int, surf_id2: int,
                       grnod_id: int = 0, istf: int = 2, igap: int = 2,
                       idel: int = _TYPE25_IDEL, iedge: int = 1000,
                       gap_scale: float = 1.0, stfac: float = 0.0,
                       fric: float = 0.0, tstart: float = 0.0,
                       tstop: float = 0.0, inacti: int = 5,
                       viss: float = 0.05, fric_id: int = 0,
                       irem_i2: int = 0) -> List[str]:
    """/INTER/TYPE25, FORMAT(radioss2022) — the exact card set /BEGIN 2022 reads.

    Column map, verbatim from ``radioss2022/INTER/inter_type25.cfg:503-527``::

      1  %10d%10d%10d%10d%10d%10d%10s%10d%10d
         surf_ID1 surf_ID2 Istf Ithe Igap Irem_i2 <blank> Idel Iedge
      2  %10d%10s%20lg%20lg%20lg%20lg
         grnd_IDs <blank> Gap_scale %mesh_size Gap_max_s Gap_max_m
      3  %20lg%20lg%10d%10d%20lg      Stmin Stmax Igap0 Ishape Edge_angle
      4  %20lg%20lg%20lg%20lg%20lg    Stfac Fric Tpressfit Tstart Tstop
      5  %7s%1d%1d%1d%10s%10d%10d%20lg%10d%10s%20lg
         <blank7> IBC-X IBC-Y IBC-Z <blank> IVIS2 Inacti VISs Ithick <blank> Pmax
      6  %10d%10d%20lg%10s%10d%30s%10d
         Ifric Ifiltr Xfreq <blank> sens_ID <blank30> fric_ID

    Note there is NO Iform and NO VISF column on TYPE25 — friction critical
    damping is zeroed for NTY 24/25 in the engine regardless
    (``frictionparts_model.F:108-112``), which is why VIS_f on a bound
    /FRICTION does not reach this interface either.

    ``surf_ID2 = 0`` makes it self-impact of ``surf_ID1`` (ILEV=1);
    ``surf_ID1 = 0`` with a ``grnod_id`` makes it a ONE-WAY node-to-surface
    contact against ``surf_ID2`` (ILEV=3) — ``hm_read_inter_type25.F:399-434``.
    Gap_max_s/Gap_max_m are written 0, which the starter turns back into 1e30
    (``:565-566``), and a Tstop of 0 likewise becomes EP30 (``:579``).

    ``irem_i2`` is card-1 column 51-60 — *"Flag for deactivating the secondary
    node, if the same contact pair (nodes) has been defined in interface
    TYPE2"* (``inter_type25.cfg:29``). It is written 0 = "take
    /DEFAULT/INTER/TYPE25" for every ordinary contact, and ``definter.F`` turns
    that into **1 = remove those nodes**. A companion contact placed behind a
    RUPTURING /INTER/TYPE2 must write **3 = no change**, or the starter removes
    (once, permanently — ``i7remnode.F:882-901`` builds the exclusion list at
    initialization and never restores it) exactly the nodes that are supposed
    to fall into contact after the tie breaks. MEASURED on a break-then-coast
    twin: with ``Irem_i2 = 1`` the freed brick descended to a final gap of
    -0.660121 mm, byte-identical to having no companion at all and with 0.000
    contact energy; with ``Irem_i2 = 3`` the descent was arrested and reversed
    (+0.0936 -> +0.715 mm) and the contact energy was 0.0334 mJ. The card is
    legal, echoes correctly and does NOTHING at the default.
    """
    return [
        f"/INTER/TYPE25/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "# surf_ID1  surf_ID2      Istf      Ithe      Igap   Irem_i2"
        "                Idel     Iedge",
        f"{_i(surf_id1)}{_i(surf_id2)}{_i(istf)}         0{_i(igap)}"
        f"{_i(irem_i2)}          {_i(idel)}{_i(iedge)}",
        "# grnd_IDs                     Gap_scale          %mesh_size"
        "           Gap_max_s           Gap_max_m",
        f"{_i(grnod_id)}          {_f(gap_scale)}                   0"
        "                   0                   0",
        "#              Stmin               Stmax     Igap0    Ishape"
        "          Edge_angle",
        "                   0                   0         0         0"
        "                   0",
        "#              Stfac                Fric           Tpressfit"
        "              Tstart               Tstop",
        f"{_f(stfac)}{_f(fric)}                   0{_f(tstart)}{_f(tstop)}",
        "#      IBC               IVIS2    Inacti                VISs    Ithick"
        "                          Pmax",
        f"       000                   0{_i(inacti)}{_f(viss)}         0"
        "                             0",
        "#    Ifric    Ifiltr               Xfreq             sens_ID"
        "                                 fric_ID",
        f"         0         0                   0                   0"
        f"                              {_i(fric_id)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: *CONTACT_AUTOMATIC_GENERAL SOFT-sentinel interfaces
#   SOFT -7 → /INTER/TYPE7 · -11 → /INTER/TYPE11 (edge) · -19 → /INTER/TYPE19
# ─────────────────────────────────────────────────────────────────────────────

def _emit_inter_type11(inter_id: int, title: str, line_ids: int, line_idm: int,
                       fric: float, inacti: int = 6, viss: float = 0.0,
                       visf: float = 0.0, gapmin: float = 0.0,
                       stfac: float = 0.0, fric_id: int = 0) -> List[str]:
    """/INTER/TYPE11 edge-to-edge (line) contact (FORMAT radioss2020).

    ``line_ids``/``line_idm`` are /LINE group ids (NOT /SURF or /GRNOD). A
    ``line_idm`` of 0 makes the interface self edge-impact of ``line_ids``.
    Matches dyna2rad's routed TYPE11 (Idel=2, Igap=0, Istf=2, Fric=FS).

    A bound /FRICTION table needs one EXTRA card after the IBC card —
    ``radioss2020/INTER/inter_type11.cfg:409-410`` is 90 blank columns then
    ``%10d`` — which is written only when ``fric_id`` is set, so every
    table-free deck stays byte-identical.
    """
    lines = [
        f"/INTER/TYPE11/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "# line_IDs  line_IDm      Istf      Ithe      Igap                            Idel",
        f"{_i(line_ids)}{_i(line_idm)}         2         0         0                             2",
        "#              Stmin               Stmax          %mesh_size               dtmin     Iform   sens_ID",
        "                   0                   0                   0                   0         0         0",
        "#              Stfac                Fric              GAPmin              Tstart               Tstop",
        f"{_f(stfac)}{_f(fric)}{_f(gapmin)}                   0                   0",
        "#      IBC                        Inacti                VIS_S               VIS_F              Bumult",
        f"       000{_i(inacti, 30)}{_f(viss)}{_f(visf)}                   0",
    ]
    if fric_id:
        lines += [
            "#" + " " * 92 + "fric_ID",
            " " * 90 + _i(fric_id),
        ]
    lines.append(HDR)
    return lines


def _emit_inter_type19(inter_id: int, title: str, surf_ids: int, surf_idm: int,
                       fric: float, inacti: int = 6, viss: float = 0.0,
                       visf: float = 0.0, gapmin: float = 0.0,
                       stfac: float = 0.0, fric_id: int = 0,
                       istf: int = 2, ibag: int = 0, idel: int = 1) -> List[str]:
    """/INTER/TYPE19 combined surface + edge contact (FORMAT radioss2021).

    Both entities are /SURF ids; the starter auto-generates the child TYPE7
    (node→segment) and TYPE11 (edge-to-edge) from the two surfaces' edges — the
    low-effort route to edge contact (no hand-built /LINE). ``surf_idm`` may
    equal ``surf_ids`` for self-contact. Iedge=2 = all segment edges.
    Matches dyna2rad's routed TYPE19 (Idel=1, Igap=0, Istf=2).

    ``istf`` / ``ibag`` / ``idel`` are parametrised for the AIRBAG flavour of
    the same sentinel route (``*CONTACT_AIRBAG_SINGLE_SURFACE`` with
    ``SOFT = -19``), which dyna2rad gives Istf=4, Idel=2 and Ibag=1
    (``convertcontacts.cxx:659-664``). The defaults are the pre-existing
    *CONTACT_AUTOMATIC_GENERAL values, so that route stays byte-identical.

    **``Ibag = 1`` only makes sense with a /MONVOL in the deck.** It means
    "close the vent holes where contact occurs", and ``hm_read_inter_type07.F:
    403-410`` resets it to 0 with ``WARNING 614`` when ``NVOLU == 0``. The
    reader expands a /INTER/TYPE19 into a child TYPE7 pair plus a TYPE11 and
    propagates Ibag to the TYPE7s only (``GlobalModelSdi.cpp:1204/1298``),
    which is right — it is a surface flag.

    ``Edge_scale_gap`` (dyna2rad writes 0.9 here) is deliberately NOT emitted:
    it is field 3 of card 2 and exists only from **radioss2024**
    (``radioss2024/INTER/inter_type19.cfg:844-845`` adds it to the
    ``Fscalegap | Gap_max`` pair), while k2rad declares ``/BEGIN 2022``.

    A bound /FRICTION table extends the LAST card by 30 blank columns and a
    ``%10d`` fric_ID (``radioss2021/INTER/inter_type19.cfg:801-802``); the
    columns are written only when ``fric_id`` is set, so a table-free deck
    stays byte-identical. The hm_reader carries the binding onto every child
    interface the TYPE19 expands into (``GlobalModelSdi.cpp:1247/1341/1432``).
    """
    fric_card = "         0         0                   0         2         0"
    if fric_id:
        fric_card += " " * 30 + _i(fric_id)
    return [
        f"/INTER/TYPE19/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "# surf_IDs  surf_IDm      Istf      Ithe      Igap     Iedge      Ibag      Idel     Icurv",
        f"{_i(surf_ids)}{_i(surf_idm)}{_i(istf)}         0         0         2"
        f"{_i(ibag)}{_i(idel)}         0",
        "#          Fscalegap             GAP_MAX",
        "                   0                   0",
        "#              Stmin               Stmax          %mesh_size               dtmin  Irem_gap  Irem_i2",
        "                   0                   0                   0                   0         0         0",
        "#              Stfac                Fric              Gapmin              Tstart               Tstop",
        f"{_f(stfac)}{_f(fric)}{_f(gapmin)}                   0                   0",
        "#      IBC                        Inacti                VISs                VISf              Bumult",
        f"       000{_i(inacti, 30)}{_f(viss)}{_f(visf)}                   0",
        ("#    Ifric    Ifiltr               Xfreq     Iform   sens_ID"
         "                                 fric_ID" if fric_id else
         "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID"),
        fric_card,
        HDR,
    ]


def _segment_set_edges(segments) -> List:
    """All unique edges of a list of 3/4-node segments: each segment's
    consecutive node pairs (with wrap) become one /LINE/SEG edge, de-duplicated
    across segments by unordered node pair.

    This keeps interior/shared edges — an edge between two adjacent segments is
    kept once (not dropped as a free-boundary extraction would) — which is the
    right behaviour for AUTOMATIC_GENERAL edge contact, whose /INTER/TYPE11 acts
    on every shell edge, not only the free perimeter. (NB: not boundary-only.)"""
    seen: Set = set()
    edges: List = []
    for seg in segments:
        nodes = [n for n in seg if n and n > 0]
        k = len(nodes)
        for i in range(k):
            a, b = nodes[i], nodes[(i + 1) % k]
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            edges.append((a, b))
    return edges


def _general_line_group(state: ConversionState, sid: int, styp: int,
                        tag: str, out_lines: List[str]) -> int:
    """Build a /LINE group for one side of an edge (TYPE11) contact.

    A segment set (styp 0/1 → *SET_SEGMENT) is emitted as an explicit
    /LINE/SEG from its segment edges. Parts / part sets are emitted as a /SURF
    (via _make_master_surface, the same surface the TYPE7/25 path builds) wrapped
    in a /LINE/SURF, letting the starter derive the surface's segment edges.
    Returns the /LINE id, or 0 when no geometry resolves.
    """
    if styp in (0, 1) and sid in state.segment_sets:
        ss = state.segment_sets[sid]
        edges = _segment_set_edges(ss.segments)
        if not edges:
            return 0
        line_id = state.next_id()
        out_lines += _emit_line_seg(line_id, ss.title or tag, edges)
        return line_id
    pids = sorted(_contact_master_pids(state, sid, styp))
    if not pids:
        return 0
    surf_id = state.next_id()
    if not _make_master_surface(state, surf_id, f"{tag}_surf", pids, out_lines):
        return 0
    line_id = state.next_id()
    out_lines += _emit_line_surf(line_id, tag, [surf_id])
    return line_id


def _make_general_interfaces(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """*CONTACT_AUTOMATIC_GENERAL with a SOFT sentinel → /INTER/TYPE7|11|19.

    Only the sentinel-routed contacts (SOFT -7/-11/-19) live in
    ``state.contacts_general``; ordinary AUTOMATIC_GENERAL uses the single-
    surface path. Gapmin comes from the Card-3 SST/MST (``_sst_mst_to_gapmin``),
    Inacti from IGNORE (``_ignore_to_inacti``), VisS from VDC, Stfac from SFS,
    and scalar Fric from FS — the same plumbing as the TYPE7/TYPE25 path.
    (``--inter-gapmin`` / ``--auto-gapmin`` do NOT reach these sentinel-routed
    interfaces; their engagement gap is the Card-3 SST/MST only.)

    Deliberate deviations from dyna2rad, all consistent with k2rad's existing
    (solver-validated) TYPE7 path and harmless for the common self-contact deck:
      * Gapmin = (|SST|+|MST|)/2 (``_sst_mst_to_gapmin``), NOT dyna2rad's
        scale-weighted fabs(SST*SFST + MST*SFMT)/2. These coincide whenever the
        Card-3 scale factors are blank/unit and SST/MST share a sign (the usual
        case); they differ only for non-unit SFST/SFMT or mixed-sign thicknesses.
      * Inacti via ``_ignore_to_inacti`` (=5 explicit) rather than dyna2rad's
        fixed 6 — Inacti=5 is the validated k2rad convention (node-moving
        Inacti=3/6 seg-faulted the engine on rigid-body secondary nodes).
      * Scalar Coulomb Fric = FS with Ifric=0 (as the whole k2rad TYPE7 family),
        not dyna2rad's FD*FSF + C5/C6 decay + Ifric=2 for the -7/-19 routes;
        identical when FS==FD.
    Only the SOFT=-7 route's Istf=2 / Igap=2 are matched to dyna2rad exactly
    (see ``_emit_inter_type7``), since those were a plain emitter-default gap.

    Side geometry for the -7 (both sides) and -19 (both sides) routes resolves
    through the part/part-set resolvers, so a *SET_SEGMENT or *SET_NODE side is
    dropped with a warning (only the -11 route synthesizes a /LINE from a
    segment set). Restrict those contacts to parts, or use -11, if a set side is
    load-bearing.
    """
    if not state.contacts_general:
        return []
    lines = ["#-  GENERAL EDGE/SOFT INTERFACES (*CONTACT_AUTOMATIC_GENERAL SOFT):", HDR]
    dropped: Dict[str, List[int]] = {}
    # Ibag=1 means "close the airbag's vent holes where contact occurs", and
    # hm_read_inter_type07.F:403-410 resets it to 0 with WARNING 614 whenever
    # the deck has NVOLU == 0. Emitting it on a deck with no monitored volume
    # would therefore trade a real setting for a warning; the flag is gated on
    # a bag that actually converted.
    #
    # `dropped` is the PREPASS verdict, not the final one: _resolve_airbags (a
    # build_starter prepass) sets it for a bag whose surface resolves to no
    # shell, but _make_monvols sets it AGAIN when _emit_airbag_surface finds
    # none of those shells in the emitted mesh — and this section runs first
    # (_starter_section_registry: general_interfaces at :1469, monvols at
    # :1507), so state.monvol_ids is still empty here and cannot be used. The
    # residual case is therefore a bag that resolves in the prepass and then
    # emits nothing: Ibag=1 with NVOLU == 0, which the starter resets to 0
    # with WARNING 614. Warning-level, and strictly better than the mirror
    # error of dropping Ibag on a deck whose bag DOES convert.
    has_monvol = any(not a.dropped for a in state.airbags)
    for c in state.contacts_general:
        self_contact = (c.ssid, c.sstyp) == (c.msid, c.mstyp)
        if c.soft == -11:
            tname = "TYPE11"
        elif c.soft == -19:
            tname = "TYPE19"
        else:
            tname = "TYPE7"
        if c.airbag:
            # The airbag card has NO MST column — it is single-sided — so the
            # two-sided (|SST| + |MST|)/2 helper would silently read a blank as
            # a second thickness. dyna2rad's formula for this keyword is the
            # scale-weighted single-sided one (convertcontacts.cxx:659-660),
            # and it is passed explicitly rather than through the helper.
            sfst = c.sfst if c.sfst != 0.0 else 1.0
            gapmin = abs(c.sst) / 2.0 * sfst
            # The two diagnostics _sst_mst_to_gapmin would have emitted. They
            # are not part of the arithmetic, and skipping the helper for the
            # single-sided formula silently skipped them too — a negative SST
            # was absolutised with nothing said.
            if c.sst < 0.0:
                state.warn(
                    f"CONTACT {c.inter_id}: negative SST ({c.sst:g}) — using "
                    "the magnitude for the Gapmin mapping; the "
                    "negative-thickness projection semantics have no "
                    f"/INTER/{tname} equivalent.")
            if gapmin > 0.0:
                state.warn(
                    f"CONTACT {c.inter_id}: SST contact thickness -> "
                    f"/INTER/{tname} Gapmin={gapmin:g} (|SST|/2 * SFST — the "
                    "airbag card is SINGLE-sided and has no MST column, so "
                    "the two-sided (|SST|+|MST|)/2 form does not apply). On "
                    "an implicit deck, keep ignore=0 to retain Inacti=0 if "
                    "Gapmin exceeds the physical clearance; ignore=1/2 (and "
                    "any explicit deck) maps to Inacti=5, which shrinks the "
                    "gap back to the clearance.")
        else:
            gapmin = _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id,
                                        target=tname)
        inacti = _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin)
        viss = _vdc_to_viss(c.vdc, state, c.inter_id)
        stfac = _stfac_for(state, c.sfs, c.inter_id)
        # All three sentinel routes can hold a /FRICTION binding: TYPE7,
        # TYPE11 and TYPE19 each carry fric_ID in cols 91-100 of their last
        # card at /BEGIN 2022 — see _FRIC_ID_TYPES for the CFG lines.
        fric, fric_id = _contact_friction(
            state, c.fs, c.fd, c.inter_id, "CONTACT_AUTOMATIC_GENERAL", tname)

        if c.soft == -7:
            slav = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes, lines)
            mast = _resolve_contact_master(state, c.msid, c.mstyp, lines)
            if not slav or not mast:
                _drop_interface(
                    state, dropped, "CONTACT_AUTOMATIC_GENERAL", c.inter_id,
                    f"(SOFT=-7 -> TYPE7) ssid={c.ssid}/msid={c.msid} resolved "
                    "to no secondary node group / main surface",
                    "REMEDY: restrict the contact to parts or part sets that "
                    "exist in this deck (a *SET_SEGMENT or *SET_NODE side does "
                    "not resolve on the -7 route), or use SOFT=-11 for an edge "
                    "contact built from a segment set.")
                continue
            lines += _emit_inter_type7(c.inter_id, c.title, slav, mast, fric,
                                       inacti, viss=viss, gapmin=gapmin, stfac=stfac,
                                       istf=2, igap=2, fric_id=fric_id)
            state.warn(
                f"*CONTACT_AUTOMATIC_GENERAL {c.inter_id}: SOFT=-7 -> "
                f"/INTER/TYPE7 (penalty node->surface {'self-' if self_contact else ''}"
                "contact, dyna2rad sentinel routing; Istf=2, Igap=2).")
        elif c.soft == -19:
            surf_s = _resolve_contact_master(state, c.ssid, c.sstyp, lines)
            surf_m = surf_s if self_contact else _resolve_contact_master(
                state, c.msid, c.mstyp, lines)
            if not surf_s or not surf_m:
                _drop_interface(
                    state, dropped, "CONTACT_AUTOMATIC_GENERAL", c.inter_id,
                    f"(SOFT=-19 -> TYPE19) ssid={c.ssid}/msid={c.msid} "
                    "resolved to no surface",
                    "REMEDY: restrict the contact to parts or part sets that "
                    "exist in this deck (a *SET_SEGMENT or *SET_NODE side does "
                    "not resolve on the -19 route), or use SOFT=-11 for an "
                    "edge contact built from a segment set.")
                continue
            # The AIRBAG flavour of the same sentinel: Istf=4 (the stiffness
            # comes from the property, not from the master side), Idel=2
            # (delete the interface segment when its element dies, matching a
            # bag that can tear) and Ibag=1 (close the vent holes where the
            # fabric self-contacts). dyna2rad sets all three,
            # convertcontacts.cxx:659-664.
            lines += _emit_inter_type19(
                c.inter_id, c.title, surf_s, surf_m, fric, inacti, viss=viss,
                gapmin=gapmin, stfac=stfac, fric_id=fric_id,
                **({"istf": 4, "idel": 2, "ibag": 1 if has_monvol else 0}
                   if c.airbag else {}))
            kw = c.keyword or "CONTACT_AUTOMATIC_GENERAL"
            state.warn(
                f"*{kw} {c.inter_id}: SOFT=-19 -> "
                f"/INTER/TYPE19 (surface+edge {'self-' if self_contact else ''}"
                "contact; the starter derives the edge lines from the two "
                "/SURF, dyna2rad sentinel routing)."
                + (" Airbag flavour: Istf=4, Idel=2"
                   + (", Ibag=1 (contact closes the monitored volume's vent "
                      "holes)." if has_monvol else
                      ". Ibag is left 0 because this deck has NO /MONVOL — "
                      "the starter would reset it anyway, with WARNING 614 "
                      "(hm_read_inter_type07.F:403-410).")
                   + " Edge_scale_gap (dyna2rad writes 0.9) is NOT emitted: "
                     "that column exists only from /BEGIN 2024 and k2rad "
                     "declares 2022."
                   if c.airbag else ""))
        else:  # c.soft == -11
            line_s = _general_line_group(state, c.ssid, c.sstyp,
                                         f"general_{c.inter_id}_s", lines)
            line_m = 0 if self_contact else _general_line_group(
                state, c.msid, c.mstyp, f"general_{c.inter_id}_m", lines)
            if not line_s:
                _drop_interface(
                    state, dropped, "CONTACT_AUTOMATIC_GENERAL", c.inter_id,
                    f"(SOFT=-11 -> TYPE11) ssid={c.ssid} resolved to no "
                    "edge/line geometry",
                    "REMEDY: point SSID at a *SET_SEGMENT that has segments, "
                    "or at a part / part set carrying shell or solid "
                    "elements.")
                continue
            lines += _emit_inter_type11(c.inter_id, c.title, line_s, line_m, fric,
                                        inacti, viss=viss, gapmin=gapmin, stfac=stfac,
                                        fric_id=fric_id)
            state.warn(
                f"*CONTACT_AUTOMATIC_GENERAL {c.inter_id}: SOFT=-11 -> "
                f"/INTER/TYPE11 edge-to-edge {'self-' if self_contact else ''}"
                "contact. k2rad synthesizes the /LINE group(s) the interface "
                "needs (a /LINE/SEG from a *SET_SEGMENT's edges, else a "
                "/LINE/SURF over the part surface so the starter derives the "
                "edges) — dyna2rad instead forwards the raw set and lets the "
                "starter build the edges.")
    _note_dropped_interfaces(state, dropped)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_FRICTION binding  (*CONTACT Card-2 FS sentinels → /FRICTION fric_ID)
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA *CONTACT Card-2 FS sentinels (Vol I pp. 11-27 … 11-31).
_FS_PART_CONTACT = -1.0      # "the *PART_CONTACT coefficients are to be used"
_FS_DEFINE_FRICTION = -2.0   # "use the one *DEFINE_FRICTION table / the FD id"
_FS_DEFINE_TABLE = 2.0       # "FD is a *DEFINE_TABLE id: mu(pressure, velocity)"

#: Radioss interface types whose /BEGIN 2022 input FORMAT carries a ``fric_ID``
#: column, so a /FRICTION table can be bound to them. All four put it in cols
#: 91-100 of the card named below:
#:   * TYPE7  — radioss2020/INTER/inter_type7.cfg  card 6 (Ifric…fric_ID)
#:   * TYPE11 — radioss2020/INTER/inter_type11.cfg:409-410, a card of its OWN
#:     after the IBC card: ``%10s%10s%10s%10s%20s%20s%10s%10d`` = 90 blank
#:     columns then fric_ID. Read by ``hm_read_inter_type11.F:185``
#:     (``HM_GET_INTV('Fric_ID',INTFRIC,…)`` → ``IPARI(72)``, echoed at :584).
#:   * TYPE19 — radioss2021/INTER/inter_type19.cfg:801-802, appended to the
#:     Ifric card: ``…%10d%10s%10s%10s%10d`` = sens_ID, 30 blank columns,
#:     fric_ID. TYPE19 has no starter reader of its own — the hm_reader expands
#:     it into TYPE7 + symmetric TYPE7 + TYPE11 and carries the binding onto all
#:     three (``GlobalModelSdi.cpp:929`` reads it, ``:1247``/``:1341``/``:1432``
#:     re-emit it).
#:   * TYPE25 — radioss2022/INTER/inter_type25.cfg card 6
#: TYPE2 and TYPE10 are excluded because they are TIED interfaces with no
#: friction model at all. The table is not silently lost on those —
#: _bind_friction_table says so, naming the interface.
_FRIC_ID_TYPES = ("TYPE7", "TYPE11", "TYPE19", "TYPE25")


def _bind_friction_table(state: ConversionState, fd: float, inter_id: int,
                         keyword: str, target: str) -> int:
    """Resolve *CONTACT ``FS = -2`` to a /FRICTION id, or 0 with a loud warning.

    dyna2rad's rules (``convertcontacts.cxx:341-390``), reproduced:
      * exactly ONE *DEFINE_FRICTION in the model → it is bound to EVERY
        FS=-2 interface, whatever the contact pointed at ("same friction to
        apply to all interfaces in the model");
      * several → bind the one whose id is in the FD column;
      * none, or no match → warning (dyna2rad message 200029, "Friction card
        for contact is not defined, friction is set to 0") and FS = FD = 0.

    One deliberate improvement: dyna2rad reads the table id from
    ``LSDYNA_FD_DefineFriction``, an attribute the LS-DYNA CFG only fills for
    the ``_AUTOMATIC_`` node-to-surface spelling
    (``contact_option_nodes_to_surface.cfg:2506-2548`` gates the FS pre-read on
    ``ContactOption == 2``). For plain ``*CONTACT_NODES_TO_SURFACE`` and
    ``*CONTACT_ERODING_NODES_TO_SURFACE`` it stays 0, so with two or more
    tables in the deck dyna2rad zeroes the friction of a contact whose table
    exists. k2rad reads the raw FD column itself and does not have that hole.
    """
    kw = keyword or "CONTACT"
    tables = state.define_frictions

    def edge_caveat(fid: int) -> None:
        """TYPE11 takes the table's per-pair COEFFICIENTS but not its LAW.

        ``inter_dcod_friction.F:80`` accepts a fric_ID on NTYP 7/11/19/21/24/25
        and resolves it, but ``:101-112`` then warns for NTYP==11 whenever the
        table's ``FRICMOD > 0`` (k2rad always writes Ifric=2) and copies only
        ``FRICFORM`` into ``IPARI(30)``. The engine matches: ``i11mainf.F:
        233-241`` pulls TABCOUPLEPARTS_FRIC / TABCOEF_FRIC and ``i11cor3.F:386``
        resolves the part pair, but ``i11for3.F`` uses the flat ``FRICC`` only —
        no ``C5*exp(C6*v)`` term anywhere. So the pair coefficients act and the
        velocity decay does not. Confirmed on the starter: the echo reads
        "INTERFACE FRICTION MODEL. 5" AND raises WARNING 1595.
        """
        if target not in ("TYPE11", "TYPE19"):
            return
        via = ("" if target == "TYPE11" else
               " — /INTER/TYPE19 is expanded by the reader into a TYPE7 plus a "
               "TYPE11, and it is the TYPE11 half that is limited; the TYPE7 "
               "half gets the full law")
        state.warn(
            f"*{kw} {inter_id}: /FRICTION/{fid} is bound to /INTER/{target}, "
            "and the per-part-pair COEFFICIENTS do act, but the Ifric=2 "
            "Darmstad velocity decay does NOT on an edge (TYPE11) contact"
            f"{via}. Expect starter WARNING 1595 'THE FRICTION MODEL DEFINED IN "
            "FRICTION INTERFACE IS NOT COMPATIBLE WITH INTERFACE TYPE 11' — it "
            "is informational, not an error, and the contact is NOT "
            "frictionless. Only the DC decay term is lost; mu falls back to the "
            "pair's FRIC (= LS-DYNA FD).")

    if target not in _FRIC_ID_TYPES:
        state.warn(
            f"*{kw} {inter_id}: Card-2 FS=-2 asks for a *DEFINE_FRICTION "
            f"table, but this contact converts to /INTER/{target}, a TIED "
            "interface with no friction model and so no fric_ID column. The "
            f"friction table is NOT bound and /INTER/{target} runs "
            "FRICTIONLESS. Convert this pair with a sliding contact "
            "(TYPE7/TYPE11/TYPE19/TYPE25 all carry fric_ID) if the friction is "
            "load-bearing.")
        return 0
    if not tables:
        state.warn(
            f"*{kw} {inter_id}: Card-2 FS=-2 selects a *DEFINE_FRICTION table, "
            "but the deck defines NONE — friction set to 0 on this interface "
            "(same as dyna2rad warning 200029). Add the *DEFINE_FRICTION the "
            "contact refers to, or put an ordinary FS/FD on Card 2.")
        return 0
    if len(tables) == 1:
        fid = next(iter(tables))
        state.warn(
            f"*{kw} {inter_id}: Card-2 FS=-2 -> /FRICTION/{fid} bound via "
            f"fric_ID on /INTER/{target}. The deck has exactly one "
            "*DEFINE_FRICTION, so it applies to every FS=-2 contact regardless "
            "of the FD column (LS-DYNA Vol I p.17-279; dyna2rad "
            "convertcontacts.cxx:350-357). The interface's own Fric/Ifric are "
            "dead while fric_ID is set (2022 Reference Guide p.268 remark 16).")
        edge_caveat(fid)
        return fid
    want = int(fd)
    if want in tables:
        state.warn(
            f"*{kw} {inter_id}: Card-2 FS=-2 with FD={want} -> /FRICTION/{want} "
            f"bound via fric_ID on /INTER/{target} (the deck has "
            f"{len(tables)} *DEFINE_FRICTION tables, so FD names the one to "
            "use). The interface's own Fric/Ifric are dead while fric_ID is "
            "set.")
        edge_caveat(want)
        return want
    state.warn(
        f"*{kw} {inter_id}: Card-2 FS=-2 but FD={fd:g} matches none of the "
        f"{len(tables)} *DEFINE_FRICTION ids in the deck "
        f"({sorted(tables)}) — friction set to 0 on this interface (dyna2rad "
        "warning 200029; LS-DYNA itself calls this an error termination, Vol I "
        "p.17-279). Point FD at the friction table's ID.")
    return 0


def _contact_friction(state: ConversionState, fs: float, fd: float,
                      inter_id: int, keyword: str, target: str,
                      fsf: float = 1.0):
    """(*Fric*, *fric_ID*) for one contact, honouring the FS sentinels.

    ``FS >= 0`` (the ordinary case) is unchanged: scalar Coulomb ``Fric = FS``
    with ``Ifric = 0``, no binding, no new warning — every deck that converted
    before still converts byte-for-byte. Only the three sentinel values move.
    """
    kw = keyword or "CONTACT"
    if fs == _FS_DEFINE_FRICTION:
        return 0.0, _bind_friction_table(state, fd, inter_id, kw, target)
    if fs == _FS_PART_CONTACT:
        state.warn(
            f"*{kw} {inter_id}: Card-2 FS=-1 means 'take the friction "
            "coefficients from the *PART_CONTACT cards', which k2rad does not "
            f"convert -> /INTER/{target} Fric=0 (FRICTIONLESS) for this "
            "interface. Writing FS through literally would put a NEGATIVE "
            "Coulomb coefficient on the card. Put the real FS/FD on *CONTACT "
            "Card 2, or collect the per-part values into a *DEFINE_FRICTION "
            "table and reference it with FS=-2.")
        return 0.0, 0
    if fs == _FS_DEFINE_TABLE:
        tid = int(fd)
        named = (f"names *DEFINE_TABLE {tid}" if tid > 0
                 else f"should name a *DEFINE_TABLE in FD, but FD={fd:g}")
        known = ("" if tid > 0 and tid in getattr(state, "define_tables", {})
                 else " (that table is not in this deck either — check the "
                      "*INCLUDE tree, or whether it is a *DEFINE_TABLE_2D/_3D, "
                      "which k2rad does not parse)")
        state.warn(
            f"*{kw} {inter_id}: Card-2 FS=2 is the LS-DYNA sentinel for "
            f"'FD is a friction TABLE id' — mu(contact pressure, relative "
            f"velocity), Vol I p.11-28 'FS.EQ.2: Table ID …'. This one {named}"
            f"{known}. OpenRadioss has no pressure-AND-velocity friction table "
            "(Ifric=1/2 are polynomial/exponential in p and v only), so "
            f"/INTER/{target} gets Fric=0 (FRICTIONLESS) and the table is "
            "DROPPED. Writing FS through literally would put mu=2.0 on the "
            "card — 4-40x a typical table's 0.05-0.5. Replace the table with a "
            "*DEFINE_FRICTION (FS/FD/DC) and reference it with FS=-2 to keep "
            "the velocity dependence. NB: LS-DYNA itself falls back to a "
            "literal mu=2.0 for SMP non-Mortar AUTOMATIC/FORMING contacts with "
            "SOFT=0/1 (Vol I p.11-31 remark 1) — if the source run really did "
            "that, put the 2.0 on Card 2 as FD with FS blank.")
        return 0.0, 0
    return fs * fsf, 0


# ─────────────────────────────────────────────────────────────────────────────
# Starter: /INTER/TYPE25 interfaces
#   *CONTACT_ERODING_{SINGLE_SURFACE,SURFACE_TO_SURFACE,NODES_TO_SURFACE}
#   *CONTACT_{,AUTOMATIC_}NODES_TO_SURFACE
# ─────────────────────────────────────────────────────────────────────────────

#: /INTER/TYPE25 VISs when the deck gives no VDC. The Radioss CFG default is
#: 0.05 and dyna2rad leaves it there; k2rad's existing TYPE25 self-contact
#: emitter writes the same. (LS-DYNA's own VDC default is 0, but a TYPE25 with
#: zero contact-normal damping rings on impact, which is exactly the load case
#: an eroding contact is written for.)
_TYPE25_DEFAULT_VISS = 0.05

#: Iedge = 1000 ("no edge contact") is the Radioss default and what every k2rad
#: TYPE25 gets, except the dyna2rad SOFT=2 route below.
_TYPE25_IEDGE_NONE = 1000
_TYPE25_IEDGE_ALL_SOLID_AND_SHELL = 22


def _type25_viss(vdc: float, state: ConversionState, inter_id: int,
                 keyword: str = "CONTACT") -> float:
    """LS-DYNA Card-2 VDC (% of critical) → /INTER/TYPE25 VISs, defaulting to
    the Radioss 0.05 rather than to 0 (see _TYPE25_DEFAULT_VISS)."""
    if vdc and vdc > 0.0:
        viss = vdc / 100.0
        state.warn(f"*{keyword} {inter_id}: Card-2 VDC={vdc:g} (% critical) -> "
                   f"/INTER/TYPE25 VISs={viss:g} (normal contact damping).")
        return viss
    return _TYPE25_DEFAULT_VISS


def _type25_stfac(state: ConversionState, c) -> float:
    """/INTER/TYPE25 Stfac = min(SFS, SFM) with LS-DYNA's blank→1.0 defaulting,
    which is dyna2rad's rule for this family (``convertcontacts.cxx:459-464``,
    ``stfac = min(lsdSFS, lsdSFM)`` after ``:410-414`` resets 0 to 1).
    ``--soften-stfac``, when given, overrides it as everywhere else."""
    if state.options.soften_stfac is not None:
        return state.options.soften_stfac
    sfs = c.sfs if c.sfs != 0.0 else 1.0
    sfm = c.sfm if c.sfm != 0.0 else 1.0
    stfac = min(sfs, sfm)
    if stfac != 1.0:
        state.warn(
            f"*{c.keyword or 'CONTACT'} {c.inter_id}: Card-3 SFS={c.sfs:g}/"
            f"SFM={c.sfm:g} -> /INTER/TYPE25 Stfac={stfac:g} (dyna2rad's "
            "min(SFS,SFM); 1.0 is the Radioss default = no scaling).")
    return stfac


def _type25_istf_iedge(state: ConversionState, c):
    """(Istf, Iedge) for one TYPE25 contact, following dyna2rad's SOFT if-chain.

    dyna2rad splits the families across two branches that treat SOFT
    differently — an asymmetry that is documented nowhere and is simply how the
    chain fell out, but it IS the reference behaviour:

      * ``convertcontacts.cxx:583-613`` — ERODING_SURFACE_TO_SURFACE and
        AUTOMATIC_NODES_TO_SURFACE: ``Istf=2`` by default, ``4`` for SOFT==1,
        and for SOFT==2 ``Istf=2`` plus ``IPSTIF=1`` and ``Iedge=22``.
      * ``convertcontacts.cxx:614-628`` — ERODING_SINGLE_SURFACE,
        ERODING_NODES_TO_SURFACE and plain NODES_TO_SURFACE: the coarse
        ``Istf = 4 if SOFT>=1 else 2``, never IPSTIF, never Iedge.

    ``IPSTIF`` is not a /BEGIN 2022 column (TYPE25 card 1 ends at Iedge, col
    90), so a SOFT=2 contact loses the segment-based penalty stiffness and is
    warned about. Istf: 2 = average of the two sides' stiffness, 4 = minimum
    (``radioss2026/INTER/inter_type25.cfg:208-216``).
    """
    base = (c.keyword or "").replace("_MPP", "")
    full_soft_rule = ("ERODING_SURFACE_TO_SURFACE" in base
                      or "AUTOMATIC_NODES_TO_SURFACE" in base)
    iedge = _TYPE25_IEDGE_NONE
    if full_soft_rule:
        if c.soft == 2:
            istf = 2
            iedge = _TYPE25_IEDGE_ALL_SOLID_AND_SHELL
            state.warn(
                f"*{c.keyword} {c.inter_id}: optional-Card-A SOFT=2 "
                "(segment-based penalty) -> /INTER/TYPE25 Istf=2 with "
                f"Iedge={iedge} (secondary and main edges = all external solid "
                "segments + all shell segments), matching dyna2rad "
                "convertcontacts.cxx:593-611. Its companion IPSTIF=1 has NO "
                "column in the /BEGIN 2022 TYPE25 format (card 1 ends at Iedge, "
                "col 90) and is dropped — the contact uses the ordinary nodal "
                "penalty stiffness.")
        else:
            istf = 4 if c.soft == 1 else 2
    else:
        istf = 4 if c.soft >= 1 else 2
    return istf, iedge


def _solid_pids_by_part(state: ConversionState) -> Dict[int, int]:
    """``{part id: the largest node count of any solid in it}`` in ONE pass.

    Both facts _type25_surface needs about a part — "does it carry solids at
    all" and "are any of them quadratic (>8 distinct nodes)" — come out of the
    same walk. Built per call site rather than per part: the membership test
    used to be ``any(e.pid == p for e in state.solid_elems)`` evaluated once
    per pid, which is O(|pids| x |solid_elems|) per contact SIDE and does not
    short-circuit at all for a part that carries no solids (0.45 s at 200k
    solids / 40-part side, 1.24 s at 500k). _solid_contact_master_pids already
    uses the one-pass form.
    """
    out: Dict[int, int] = {}
    # Thick shells are /BRICK, so they answer both questions the same way an
    # ordinary hex does (and are never quadratic — always 8 slots). Chained
    # rather than concatenated: this runs per contact side on the whole solid
    # table, and copying both lists there is what the rewrite removed.
    #
    # SPH is absent for the reason it is absent from _solid_contact_master_pids:
    # this map answers "build a solid /SURF for this part?", and a particle has
    # no face to put in one.
    for e in itertools.chain(state.solid_elems, state.tshell_elems):
        n = len(_ordered_unique_nodes(list(e.nodes)))
        if n > out.get(e.pid, 0):
            out[e.pid] = n
    return out


def _type25_surface(state: ConversionState, c, sid: int, styp: int,
                    tag: str, out_lines: List[str],
                    sid_zero_is_all_parts: bool = False) -> int:
    """Emit one side's /SURF for a TYPE25 contact and return its id (0 = none).

    The whole point of the eroding batch lives here: for an ``*CONTACT_ERODING_*``
    whose side resolves to SOLID parts, the surface is built with ``/SURF/PART/
    ALL`` (every face, interior ones included) instead of the ``/SURF/PART/EXT``
    every other k2rad contact uses. Without it the eroding contact converts to a
    card that LOOKS right and then fails SILENTLY: the starter arms solid
    erosion on ``Idel>0`` alone (``i25surfi.F:607-625``, ``IPARI(100)=1``) but
    the segment list holds no interior faces, so when a brick dies the crater
    face it exposes has no segment, no stiffness and no friction. dyna2rad has
    exactly this gap — it builds every contact surface from a bare ``PART``
    clause with no ``opt_A`` (``convertcontacts.cxx:264-274``).

    SCOPE, measured: this matters when the eroding part supplies the contact
    SEGMENTS, i.e. when it is a /SURF side. A driven punch ground through a
    six-layer plate kept live contact in 4 of 6 layers with /ALL (384 bricks
    eroded, contact impulse 0.2093) and only 1 of 6 with --eroding-surf-ext
    (303 bricks, 0.1294). But the same plate on the NODE side of a plain
    non-eroding *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE eroded all 384 anyway
    (impulse 0.2031): k2rad builds a TYPE7 secondary side as a /GRNOD over
    EVERY node of the part, interior nodes included, and a node outlives the
    elements that used to own it. So "only TYPE25 keeps working through
    erosion" is true of the segment side, not of the node side.
    """
    # SURFATYP/SURFBTYP 5 is "include all non-spot-weld parts" on EITHER side
    # (Vol I p.11-25), so it always expands. A bare id of 0 does NOT: p.11-24
    # reads "SURFA … EQ.0: Includes all parts IN THE CASE OF SINGLE SURFACE
    # CONTACT TYPES", and for SURFB "EQ.0: SURFB side is not applicable for
    # single surface contact types" — there is no all-parts reading of a blank
    # main side at all. Expanding it anyway (as this did) turns a deck with a
    # dropped MSID into a plausible-looking global contact that also puts the
    # secondary part on both sides. `sid_zero_is_all_parts` is therefore passed
    # true only for the SSID of a SINGLE_SURFACE; every other side falls
    # through to _contact_master_pids and, if that is empty, to _drop_interface
    # with its MSID/SSID remedy text.
    # _contact_master_pids models neither form (it is written for the 0/1/2/3
    # part forms), so they are resolved here.
    if styp == 5 or (sid == 0 and sid_zero_is_all_parts):
        pids = set(state.parts.keys())
    else:
        pids = _contact_master_pids(state, sid, styp)
    if not pids:
        return 0
    solid_max_nodes = _solid_pids_by_part(state)
    solid_pids = {p for p in pids if p in solid_max_nodes}
    solid_all = False
    if c.eroding and solid_pids:
        quad_pids = sorted(p for p in solid_pids if solid_max_nodes[p] > 8)
        if state.options.eroding_surf_ext:
            state.warn(
                f"*{c.keyword} {c.inter_id}: --eroding-surf-ext -> the solid "
                f"side(s) {sorted(solid_pids)} use /SURF/PART/EXT (external "
                "skin only), reproducing LS-DYNA SMP's literal IADJ=0. The "
                "contact then CANNOT re-expose an interior face when a brick "
                "erodes: only segments already in the list can be woken "
                "(engine check_surface_state.F:174-203 flips a dormant "
                "negative-stiffness segment active), and /EXT puts none there. "
                "Drop the flag for erosion-correct behaviour.")
        elif quad_pids:
            state.warn(
                f"*{c.keyword} {c.inter_id}: solid part(s) {quad_pids} carry "
                "QUADRATIC elements (TET10/HEX20), so their side uses "
                "/SURF/PART/EXT, not the eroding-correct /SURF/PART/ALL — the "
                "2022 Reference Guide p.372 recommends /EXT for quadratic "
                "solids because only then are the mid-side nodes used in the "
                "contact treatment. CONSEQUENCE: a face exposed by an eroded "
                "quadratic solid gets no contact segment. Convert with "
                "--tet10-to-tet4 if the erosion behaviour matters more than "
                "the quadratic accuracy.")
        else:
            solid_all = True
            state.warn(
                f"*{c.keyword} {c.inter_id}: eroding contact on solid part(s) "
                f"{sorted(solid_pids)} -> /SURF/PART/ALL (every face, INTERIOR "
                "faces included) instead of the /SURF/PART/EXT k2rad uses "
                "elsewhere. That is what makes erosion work: the starter puts "
                "each interior (two-solid) face in the segment list with a "
                "NEGATIVE stiffness (i25sti3.F:950-951) and the engine flips it "
                "active the moment one of its two solids dies "
                "(check_surface_state.F:174-203), which is LS-DYNA's IADJ=1 / "
                "EROSOP=1 behaviour exactly. Two caveats: the 2022 Reference "
                "Guide p.372 states '/SURF/PART/ALL is not available with "
                "TYPE25' — the current OpenRadioss starter implements it and "
                "has no check that rejects it, but an older binary may not; and "
                "the segment count grows with the interior mesh, so contact "
                "sorting costs more. --eroding-surf-ext falls back to /EXT.")
    surf_id = state.next_id()
    if not _make_master_surface(state, surf_id, tag, sorted(pids), out_lines,
                                solid_all=solid_all):
        return 0
    return surf_id


def _warn_eroding_card4(state: ConversionState, c) -> None:
    """Report the ERODING Card-4 fields k2rad cannot express.

    dyna2rad parses ISYM/EROSOP/IADJ in the CFG and then discards all three
    without a word (a grep for ``EROSOP|IADJ|ISYM`` over the whole dyna2rad
    tree returns zero hits) — including EROSOP, whose entire purpose is to
    enable eroding contact.
    """
    if c.isym == 1:
        state.warn(
            f"*{c.keyword} {c.inter_id}: ERODING Card-4 ISYM=1 ('do not "
            "include faces with normal boundary constraints', i.e. drop "
            "symmetry-plane faces) has NO /SURF or /INTER equivalent and is "
            "DROPPED — the symmetry-plane faces stay in the contact surface. "
            "On a half-model this can let the symmetry plane contact itself. "
            "Build the contact side from an explicit *SET_SEGMENT that omits "
            "those faces if it matters.")
    if c.erosop == 0:
        state.warn(
            f"*{c.keyword} {c.inter_id}: ERODING Card-4 EROSOP=0 ('only "
            "exterior boundary information is saved') is treated as 1. "
            "LS-DYNA hardcodes EROSOP to 1 in both SMP and MPP (Vol I "
            "p.11-65), so a 0 in the deck is a legacy no-op there too — "
            "reading it literally would switch eroding contact off in a "
            "keyword whose whole purpose is eroding contact.")
    if c.iadj == 0:
        state.warn(
            f"*{c.keyword} {c.inter_id}: ERODING Card-4 IADJ=0/blank means "
            "'solid element faces are included only for free boundaries' in "
            "LS-DYNA SMP, but MPP HARDCODES IADJ=1 (Vol I p.11-66), so a blank "
            "IADJ in an MPP-authored deck means interior faces. k2rad assumes "
            "1 and builds the solid side with /SURF/PART/ALL; the alternative "
            "(/EXT) fails silently — no warning from the solver, just no "
            "contact on the newly exposed crater face. Use --eroding-surf-ext "
            "to force the literal IADJ=0 reading.")


#: The two eroding families LS-DYNA's SMP solver runs FRICTIONLESS unless
#: SOFT=2 — Vol I p.11-65 remark 4, verbatim: "SMP LS-DYNA does not consider
#: contact friction for *CONTACT_ERODING_NODES_TO_SURFACE and *CONTACT_ERODING_
#: SURFACE_TO_SURFACE unless SOFT is set to 2 on Optional Card A. MPP LS-DYNA
#: has no such exclusion." (ERODING_SINGLE_SURFACE is NOT in the exclusion.)
_SMP_FRICTIONLESS_ERODING = ("ERODING_NODES_TO_SURFACE",
                             "ERODING_SURFACE_TO_SURFACE")


def _warn_eroding_smp_friction(state: ConversionState, c, fric: float,
                               fric_id: int) -> None:
    """Warn when /INTER/TYPE25 will apply friction the SMP source run did not.

    This is the one direction the rest of the batch does not cover: every other
    inexpressible field (SST/MST, DC, ISYM, EROSOP, IADJ, VC, IPSTIF) is
    friction k2rad DROPS, and is warned about. Here k2rad writes friction that
    may never have acted in the reference model — silently, because the deck
    itself cannot say whether it was run under SMP or MPP.
    """
    if not c.eroding or (not fric and not fric_id):
        return
    base = (c.keyword or "").replace("_MPP", "")
    if not any(v in base for v in _SMP_FRICTIONLESS_ERODING) or c.soft == 2:
        return
    got = (f"/FRICTION/{fric_id}" if fric_id else f"Fric={fric:g}")
    state.warn(
        f"*{c.keyword} {c.inter_id}: SOFT={c.soft} (not 2) on optional Card A, "
        "so if this deck was run with SMP LS-DYNA the contact was FRICTIONLESS "
        "there — "
        "SMP ignores contact friction on *CONTACT_ERODING_NODES_TO_SURFACE and "
        "*CONTACT_ERODING_SURFACE_TO_SURFACE unless SOFT=2 (Vol I p.11-65 "
        f"remark 4). MPP has no such exclusion. /INTER/TYPE25 applies {got} "
        "UNCONDITIONALLY, so an SMP-authored deck gains friction it did not "
        "have. Set FS=FD=0 on Card 2 to reproduce the SMP run, or leave it if "
        "the reference was MPP (or if the friction is what you actually want).")


def _make_type25_interfaces(state: ConversionState,
                            rigid_nodes: Set[int]) -> List[str]:
    """*CONTACT_ERODING_* and *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE →
    /INTER/TYPE25 (see :class:`~k2rad.state.ContactType25`).

    The three side topologies map onto the starter's ILEV classification
    (``hm_read_inter_type25.F:399-434``):

      ===================  =========  =========  =========  ====
      variant              surf_ID1   surf_ID2   grnd_IDs   ILEV
      ===================  =========  =========  =========  ====
      SINGLE_SURFACE       SSID surf  0          0          1
      SURFACE_TO_SURFACE   SSID surf  MSID surf  0          2
      NODES_TO_SURFACE     0          MSID surf  SSID nodes 3
      ===================  =========  =========  =========  ====

    ILEV=3 is a GENUINE one-way node-to-surface contact: the secondary nodes
    are tracked against the main surface and the main surface's own nodes are
    never secondary. dyna2rad does not symmetrize this family either — it sets
    ``surfAttrNames[0] = "grnd_IDs"`` (``convertcontacts.cxx:128-129, 212-216``)
    — so k2rad does not, and the LS-DYNA one-way semantics survive the
    conversion unchanged. (The *symmetrizing* bug dyna2rad does have is in
    ``AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE``, a different keyword, which k2rad
    routes elsewhere.)

    Idel is 2 on every one of them — see _TYPE25_IDEL for why that differs from
    dyna2rad's 1 — and Idel>0 is also what arms the solid-erosion machinery at
    all.
    """
    if not state.contacts_type25:
        return []
    lines = ["#-  ERODING / NODE-TO-SURFACE INTERFACES (/INTER/TYPE25):", HDR]
    dropped: Dict[str, List[int]] = {}

    for c in state.contacts_type25:
        kw = c.keyword or "CONTACT"
        if c.eroding:
            _warn_eroding_card4(state, c)
        if c.sst or c.mst:
            state.warn(
                f"*{kw} {c.inter_id}: Card-3 SST={c.sst:g}/MST={c.mst:g} "
                "(explicit per-side contact thickness) is DROPPED. "
                "/INTER/TYPE25 has no Gapmin column, and the Igap=5 route that "
                "carries THICK_S/THICK_M is a radioss2026-only card that a "
                "/BEGIN 2022 deck cannot hold — the gap comes from the "
                "elements' own thickness/size instead (Igap=2). Scale it with "
                "Gap_scale by hand if the explicit thickness is load-bearing.")
        istf, iedge = _type25_istf_iedge(state, c)
        fric, fric_id = _contact_friction(state, c.fs, c.fd, c.inter_id, kw,
                                          "TYPE25", fsf=c.fsf)
        if c.dc and not fric_id:
            state.warn(
                f"*{kw} {c.inter_id}: Card-2 DC={c.dc:g} (exponential "
                "static→dynamic friction decay) is DROPPED — k2rad writes a "
                "scalar Coulomb Fric with Ifric=0 on this interface. Collect "
                "FS/FD/DC into a *DEFINE_FRICTION table and reference it with "
                "FS=-2 to get the decay law (/FRICTION Ifric=2, exact).")
        _warn_eroding_smp_friction(state, c, fric, fric_id)
        inacti = _ignore_to_inacti(c.ignore, state, c.inter_id, 0.0)
        viss = _type25_viss(c.vdc, state, c.inter_id, kw)
        stfac = _type25_stfac(state, c)
        # LS-DYNA's blank DT is 1e20; TYPE25 turns a Tstop of 0 back into EP30
        # (hm_read_inter_type25.F:579), so "no death time" is written as 0.
        tstop = 0.0 if c.dt >= 1e19 else c.dt

        surf1 = surf2 = grnod = 0
        if c.variant == "NODES_TO_SURFACE":
            diag: Dict[str, int] = {}
            grnod = _resolve_contact_slave(state, c.ssid, c.sstyp, rigid_nodes,
                                           lines, diag=diag)
            if not grnod:
                _drop_interface(state, dropped, kw, c.inter_id,
                                _describe_empty_secondary(diag, c.ssid, c.sstyp),
                                _RIGID_SECONDARY_REMEDY if diag.get("raw") else
                                "REMEDY: for a node-to-surface contact SSID "
                                "should name a *SET_NODE_LIST holding every "
                                "node that may become exposed as elements "
                                "erode (LS-DYNA Vol I p.11-24); a part or part "
                                "set works too, but it must exist and carry "
                                "elements.")
                continue
            surf2 = _type25_surface(state, c, c.msid, c.mstyp,
                                    f"contact_{c.inter_id}_main", lines)
            if not surf2:
                _drop_interface(
                    state, dropped, kw, c.inter_id,
                    f"the MAIN (MSID) side msid={c.msid} mstyp={c.mstyp} "
                    "resolved to no contact surface (it names no part or part "
                    "set carrying shell/solid elements)",
                    "REMEDY: point MSID at a part or part set that exists in "
                    "this deck; a *SET_NODE or *SET_SEGMENT cannot supply the "
                    "main surface of a /INTER/TYPE25.")
                continue
            _warn_partial_rigid_secondary(state, kw, c.inter_id, diag, c.ssid)
            state.warn(
                f"*{kw} {c.inter_id} -> /INTER/TYPE25/{c.inter_id} ONE-WAY "
                "node-to-surface (surf_ID1=0, grnd_IDs=secondary node group, "
                "surf_ID2=main surface -> starter ILEV=3, "
                "hm_read_inter_type25.F:399-434). The main surface's own nodes "
                "are NOT tracked against the secondary side — the LS-DYNA "
                "one-way semantics are preserved, not symmetrized.")
        else:
            single = c.variant == "SINGLE_SURFACE"
            tag = ("self" if single else "secnd")
            # Only a SINGLE_SURFACE reads SSID=0 as "all parts" (Vol I p.11-24).
            surf1 = _type25_surface(state, c, c.ssid, c.sstyp,
                                    f"contact_{c.inter_id}_{tag}", lines,
                                    sid_zero_is_all_parts=single)
            if not surf1:
                _drop_interface(
                    state, dropped, kw, c.inter_id,
                    f"the SECONDARY (SSID) side ssid={c.ssid} sstyp={c.sstyp} "
                    "resolved to no contact surface (it names no part or part "
                    "set carrying shell/solid elements)",
                    "REMEDY: LS-DYNA Vol I p.11-24 requires a part id or a "
                    "part set id on an ERODING_SINGLE_SURFACE / "
                    "ERODING_SURFACE_TO_SURFACE contact — point SSID at one "
                    "that exists in this deck.")
                continue
            if c.variant == "SURFACE_TO_SURFACE":
                surf2 = _type25_surface(state, c, c.msid, c.mstyp,
                                        f"contact_{c.inter_id}_main", lines)
                if not surf2:
                    _drop_interface(
                        state, dropped, kw, c.inter_id,
                        f"the MAIN (MSID) side msid={c.msid} mstyp={c.mstyp} "
                        "resolved to no contact surface",
                        "REMEDY: point MSID at a part or part set that exists "
                        "in this deck and carries shell/solid elements.")
                    continue
                state.warn(
                    f"*{kw} {c.inter_id} -> /INTER/TYPE25/{c.inter_id} "
                    "surface-to-surface (surf_ID1=secondary, surf_ID2=main -> "
                    f"starter ILEV=2, symmetric), Istf={istf}, Igap=2, "
                    f"Idel={_TYPE25_IDEL}, Iedge={iedge}.")
            else:
                state.warn(
                    f"*{kw} {c.inter_id} -> /INTER/TYPE25/{c.inter_id} "
                    "self-contact (surf_ID1=the one surface, surf_ID2=0 -> "
                    f"starter ILEV=1, self-impact), Istf={istf}, Igap=2, "
                    f"Idel={_TYPE25_IDEL}, Iedge={iedge}.")

        lines += _emit_inter_type25(
            c.inter_id, c.title, surf1, surf2, grnod_id=grnod, istf=istf,
            igap=2, idel=_TYPE25_IDEL, iedge=iedge, stfac=stfac, fric=fric,
            tstart=c.bt, tstop=tstop, inacti=inacti, viss=viss,
            fric_id=fric_id)

    if any(c.eroding for c in state.contacts_type25):
        state.warn(
            "Eroding contact converted: the interface can only retreat as fast "
            "as the elements actually FAIL, and k2rad's default shell "
            "formulation Ishell=12 (fully integrated) needs 4 in-plane x 2 "
            "through-thickness = 8 failure events to delete a shell under "
            "/FAIL/JOHNSON Ifail_sh=2, against the 2 an under-integrated "
            "LS-DYNA ELFORM=2 implies — up to ~1.7x under-erosion, measured. "
            "On an eroding-contact deck that means the eroding surface barely "
            "retreats. Convert with --shell-formulation qeph (Ishell=24, "
            "reduced integration) if the erosion rate matters. Solid erosion "
            "additionally needs a failure model (/FAIL/*, or *MAT_ADD_EROSION) "
            "on the eroding parts: without one nothing is ever deleted and the "
            "contact behaves like an ordinary TYPE25.")
    _note_dropped_interfaces(state, dropped)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: tied interfaces  (*CONTACT_TIED_* → /INTER/TYPE2 | /INTER/TYPE10)
# ─────────────────────────────────────────────────────────────────────────────

# LS-DYNA tied variant → /INTER/TYPE2 Spotflag. NODES_/SHELL_EDGE_TO_SURFACE
# welds get the spotweld formulation: the secondary node is joined to the main
# segment by a rigid link of constant stiffness, so the offset between a tied
# node and the main shell MID-PLANE (typically half the plate thickness) carries
# force and moment without exciting hourglass modes. SURFACE_TO_SURFACE is
# LS-DYNA's mesh-transition glue → the standard formulation.
#
# Both are emitted as the AUTO-PENALTY variant of that formulation (28 = "like
# Spotflag=1", 27 = "like Spotflag=5", each with an automatic switch to a
# penalty tie on the individual nodes where a kinematic condition is
# incompatible) rather than the purely kinematic 1/5. A purely kinematic TYPE2
# ELIMINATES its secondary nodes' DOFs, and the starter refuses that as soon as
# such a node is also needed elsewhere:
#
#   * chktyp2.F only tags a TYPE2's secondary nodes when Spotflag is NOT one of
#     25/26/27/28, and every MAIN node carrying that tag raises the hard
#     ERROR 556 "MAIN NODE ID=n IS ALSO SECONDARY NODE OF ANOTHER INTERFACE
#     TYPE2". Two CONFORMALLY meshed parts tied to each other share nodes along
#     their common boundary, so those shared nodes sit in both the secondary
#     /GRNOD and the main /SURF — reproduced on the Kurbel deck as 62 x
#     ERROR 556 (3061 of the 4540 tied nodes are shared) with Spotflag=5, and
#     zero errors with 27.
#   * itagsl2.F implements the fallback for 27/28 only: a secondary node that
#     collides with an /RBE2, /RBE3 or a TETRA10 mid-side condition is switched
#     to the penalty tie (WARNING 1179) instead of failing the run.
#
# This is also what the reference converter does — dyna2rad defaults every
# routed /INTER/TYPE2 to Spotflag=28 (convertcontacts.cxx:49), which is why the
# same deck read natively by OpenRadioss starts clean.
_TIED_SPOTFLAG = {
    "NODES_TO_SURFACE":      28,
    "SHELL_EDGE_TO_SURFACE": 28,
    "SURFACE_TO_SURFACE":    27,
}

#: Spotflag values that take the extra penalty Card 2 (Stfac/Visc/Istf).
_TIED_PENALTY_SPOTFLAGS = (25, 26, 27, 28)

# dsearch margin over the measured worst node-to-segment gap: covers the exact
# half-thickness mid-plane offset plus mesh roundoff without reaching across to
# an unrelated segment one element away.
_TIED_DSEARCH_MARGIN = 1.2


#: Spotflag values that take the two RUPTURE cards. ``hm_read_inter_type02.F:
#: 343`` gates them on ``ILEV == 20 .OR. ILEV == 21 .OR. ILEV == 22`` and ``:301``
#: gates the penalty Stfac/Visc/Istf card on 25/26/27/28 — the two sets are
#: DISJOINT, so there is no penalty formulation of the rupture tie.
_TIED_RUPTURE_SPOTFLAGS = (20, 21, 22)


def _emit_inter_type2(inter_id: int, title: str, grnod_id: int, surf_id: int,
                      spotflag: int, dsearch: float, idel2: int = 0,
                      rupture: Optional[Tuple[int, int, float, float, float]] = None
                      ) -> List[str]:
    """/INTER/TYPE2 card (FORMAT radioss2017 — unchanged through /BEGIN 2022):
    grnd_IDs surf_IDm Ignore Spotflag Level Isearch Idel2 <blank10> dsearch(20).

    Ignore=2: secondary nodes with no main segment within dsearch are removed
    from the tie by the starter (and printed), and a dsearch of 0 is replaced
    by the starter's average-main-segment-size default. Isearch=2 = improved
    closest-segment search. Idel2=0 = engine default (no deletion); the
    *CONTACT_SPOTWELD path passes idel2=1 (dyna2rad's spotweld default,
    convertcontacts.cxx:49) so the tie dies with the sheet segment it welds.

    Cols 71-80 are left BLANK on purpose. FORMAT(radioss2025) puts a second
    secondary-surface id (surf_IDs) there; the 2022 format has no such field,
    and a blank reads as 0 in both — the one value that is safe either way.

    Spotflag 25/26/27/28 (the penalty and auto-penalty formulations — see
    _TIED_SPOTFLAG) read one EXTRA card that the purely kinematic ones do not:
    Stfac(1-20) Visc(21-40) <blank 41-60> Istf(61-70) (hm_read_inter_type02.F
    "Optional Card2 : ILEV = 25,26,27,28"). The values written are the starter's
    own defaults for a blank card (Stfac 0->1, Visc 0->0.05, Istf 0->2) and
    match the native reader's echo, so the penalty branch of the tie is scaled
    exactly as dyna2rad scales it.

    Spotflag 20/21/22 (the rupture formulations) read TWO different extra
    cards instead — ``inter_type2.cfg`` ``FORMAT(radioss2017)``, gated
    ``if (WFLAG==20 || WFLAG==21 || WFLAG==22)``::

      %10d%10d%10d%10d%10d%10d%20lg%20lg
      Rupt Ifiltr fct_IDsr fct_IDsn fct_IDst Isym Max_N_Dist Max_T_Dist
      %20lg%20lg%20lg%20lg%20lg
      Fscalestress Fscalestr_rate Fscaledist Alpha Area

    ``rupture`` is ``(fct_IDsn, fct_IDst, Fscalestress, Max_N_Dist,
    Max_T_Dist)`` — the five cells a converted cohesive bond fills. The rest
    are fixed and each for a stated reason:

    * ``Rupt = 2`` ALWAYS. ``Rupt = 1`` (the elliptic criterion) is broken in
      this OpenRadioss build: ``ruptint2.F:147-150`` normalises into ``DIS_NA``
      and ``DIS_T`` but then evaluates ``SQRT(DIS_N*DIS_N + DIS_T*DIS_T) > 1``
      with the RAW, un-normalised ``DIS_N`` — a length added to a ratio, so the
      normal term ignores ``Max_N_Dist`` entirely. 2 is also the starter's own
      default (``hm_read_inter_type02.F:372``).
    * ``Ifiltr = 0`` / ``Alpha = 0`` — LS-DYNA filters nothing.
    * ``fct_IDsr = 0`` / ``Fscalestr_rate = 0`` — no strain-rate scaling
      function; ``ruptint2.F:126`` then leaves ``SSR = 1``.
    * ``Isym = 1`` (asymmetric = traction only). LS-DYNA Vol I R17 p.11-40
      Remark 3 / p.11-73 Remark 2: *"Compressive stress does not contribute to
      the failure equation."* ``ruptint2.F:161-173`` is that clause exactly —
      the cap and the release act only while the node is OPENING.
    * ``Fscaledist = 1`` — the two functions' abscissae are written in model
      LENGTH units, so no abscissa rescaling is wanted.
    * ``Area = 0`` — a FALLBACK ONLY. ``i2surfs.F:286`` uses it just when the
      computed nodal area is zero (``IF (AREA(I) == ZERO) AREA(I) = AREA0``);
      MEASURED, a deck with ``Area = 1000`` produced byte-identical rupture
      times to the same deck with 0.
    """
    lines = [
        f"/INTER/TYPE2/{inter_id}",
        title or f"TIED_CONTACT_{inter_id}",
        "#  Grnd_id   Surf_id    Ignore  Spotflag     Level   Isearch     Idel2                       dsearch",
        f"{_i(grnod_id)}{_i(surf_id)}{_i(2)}{_i(spotflag)}{_i(0)}{_i(2)}{_i(idel2)}          {_f(dsearch)}",
    ]
    if spotflag in _TIED_PENALTY_SPOTFLAGS:
        lines += [
            "#              Stfac                Visc                          Istf",
            f"{_f(1.0)}{_f(0.05)}                    {_i(2)}",
        ]
    elif spotflag in _TIED_RUPTURE_SPOTFLAGS and rupture is not None:
        fct_sn, fct_st, scal_f, max_n, max_t = rupture
        lines += [
            "#     Rupt    Ifiltr  fct_IDsr  fct_IDsn  fct_IDst      Isym"
            "          Max_N_Dist          Max_T_Dist",
            f"{_i(2)}{_i(0)}{_i(0)}{_i(fct_sn)}{_i(fct_st)}{_i(1)}"
            f"{_f(max_n)}{_f(max_t)}",
            "#       Fscalestress      Fscalestr_rate          Fscaledist"
            "               Alpha                Area",
            f"{_f(scal_f)}{_f(0.0)}{_f(1.0)}{_f(0.0)}{_f(0.0)}",
        ]
    lines.append(HDR)
    return lines


def _tied_interface_type(c) -> str:
    """dyna2rad discriminator (convertcontacts.cxx cc:220) for a
    *CONTACT_TIED_SURFACE_TO_SURFACE[_OFFSET…]: (SFST*SST + SFMT*MST)/2 < 0 →
    the penalty tie /INTER/TYPE10, otherwise the kinematic tie /INTER/TYPE2.

    The discriminator uses the RAW Card-3 SFST/SFMT (no zero→1 defaulting), so a
    blank SFST/SFMT (0) always yields dSearch=0 ≥ 0 → TYPE2 regardless of
    SST/MST — TYPE10 needs a nonzero SFST/SFMT together with a negative SST/MST
    (LS-DYNA's "maintain the physical offset" flag). NODES_/SHELL_EDGE tied
    variants are always kinematic TYPE2 (the discriminator is a
    SURFACE_TO_SURFACE construct)."""
    if c.variant != "SURFACE_TO_SURFACE":
        return "TYPE2"
    dsearch = (c.sfst * c.sst + c.sfmt * c.mst) / 2.0
    return "TYPE10" if dsearch < 0.0 else "TYPE2"


def _emit_inter_type10(inter_id: int, title: str, grnod_id: int, surf_id: int,
                       gap: float) -> List[str]:
    """/INTER/TYPE10 penalty tied contact (FORMAT radioss120).

    grnod_id (secondary /GRNOD) + surf_id (main /SURF), same entities as TYPE2.
    Unlike the kinematic TYPE2, TYPE10 bonds by a penalty spring over a GAP, so
    its secondary nodes may coexist with /RBODY. Matches dyna2rad's routed
    TYPE10 (Idel=1, STFAC=0 engine-auto, GAP from SST/MST, ITIED=0, INACTI=0,
    VIS_S=0, BUMULT=0). No Fric field exists on TYPE10 (a tie does not slide).

    Card columns (FORMAT radioss120):
      C1  grnod_id(1-10) surf_id(11-20) <blank 21-70> Idel(71-80)
      C2  STFAC(1-20) <blank 21-40> GAP(41-60) Tstart(61-80) Tstop(81-100)
      C3  <blank 1-20> ITIED(21-30) INACTI(31-40) VIS_S(41-60) <blank 61-80> BUMULT(81-100)
    """
    blank20 = " " * 20
    return [
        f"/INTER/TYPE10/{inter_id}",
        title or f"TIED_CONTACT_{inter_id}",
        "#  grnod_id   surf_id                                                        Idel",
        f"{_i(grnod_id)}{_i(surf_id)}{_i(1, 60)}",
        "#              STFAC                                     GAP              Tstart               Tstop",
        f"{_f(0.0)}{blank20}{_f(gap)}{_f(0.0)}{_f(0.0)}",
        "#                              ITIED    INACTI               VIS_S                              BUMULT",
        f"{blank20}{_i(0)}{_i(0)}{_f(0.0)}{blank20}{_f(0.0)}",
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
        for e in state.tshell_elems:          # /BRICK too — see above
            if e.pid == pid:
                nids.update(e.nodes)
        for c in state.sph_elems:             # SPH: secondary side only
            if c.pid == pid:
                nids.update(c.nodes)
        for e in state.seatbelt_elems:        # 1D belt: secondary side — above
            if e.pid == pid and not e.is_2d:
                nids.update((e.n1, e.n2))

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


def _tied_master_surface(state: ConversionState, c, out_lines: List[str],
                         tag: str = "tied", measure: bool = True):
    """Emit the main /SURF of a tied contact; returns (surf_id, verts, faces)
    where verts/faces are the surface triangles used to measure the tied gap
    (empty when the geometry is unknown). MSTYP 0 = *SET_SEGMENT → /SURF/SEG;
    3 = part, 2 = part set → the part surface (0/1 fall back to parts too).

    ``measure=False`` skips the triangle extraction — the *CONTACT_SPOTWELD
    path takes its dsearch from the card, never from a measured distance, and
    tessellating every sheet of a car body to throw the result away is the
    expensive half of this function."""
    from ..gapmin import _segment_triangles, _surface_triangles
    if c.mstyp in (0, 1) and c.msid in state.segment_sets:
        ss = state.segment_sets[c.msid]
        if not ss.segments:
            return 0, [], []
        surf_id = state.next_id()
        out_lines += _emit_surf_seg(surf_id, ss.title or f"{tag}_{c.inter_id}_master",
                                    ss.segments)
        if not measure:
            return surf_id, [], []
        verts, faces = _segment_triangles(state, ss.segments)
        return surf_id, verts, faces
    pids = sorted(_contact_master_pids(state, c.msid, c.mstyp))
    if not pids:
        return 0, [], []
    surf_id = state.next_id()
    if not _make_master_surface(state, surf_id, f"{tag}_{c.inter_id}_master",
                                pids, out_lines):
        return 0, [], []
    if not measure:
        return surf_id, [], []
    verts, faces = _surface_triangles(state, pids)
    return surf_id, verts, faces


def _tied_slave_is_part_side(state: ConversionState, sid: int, styp: int) -> bool:
    """True when a tied contact's SECONDARY side names a whole PART / PART SET
    (rather than a node set or a segment set). Mirrors _tied_slave_nids."""
    if styp == 4:
        return False
    if styp == 3:
        return True
    if styp == 2:
        return sid in state.part_sets
    if styp in (0, 1):
        return (sid not in state.segment_sets
                and (sid in state.parts or sid in state.part_sets))
    return False


def _tied_dsearch(state: ConversionState, c, slave_nids: List[int],
                  verts, faces, label: str = "TIED CONTACT") -> float:
    """/INTER/TYPE2 dsearch for one tied contact: the measured WORST secondary
    node-to-main-segment distance × a small margin, so every tied node finds
    its segment even when the main side is a shell whose segments sit on the
    MID-PLANE half a thickness away from the physically-touching tied nodes.

    That worst-case measurement is only meaningful when the secondary side is
    the TIE SURFACE itself — a *SET_NODE_LIST weld line or a *SET_SEGMENT. When
    the side names a whole PART (or part set) the secondary group is the part's
    ENTIRE node cloud, so the "worst" node is the one on the far side of the
    part and the measurement returns a part DIAMETER, not a surface offset. On
    the Kurbel deck that produced dsearch=33.98 mm against a genuine tie gap
    below 0.03 mm, tying 3846 of 4540 nodes where the native reader ties 81 —
    the whole volume welded to the mating surface. For those sides dsearch is
    therefore left 0 and the starter's own average-main-segment default is used
    (what dyna2rad emits unconditionally).

    A negative LS-DYNA Card-3 SST/MST (absolute tie-criterion distance) is
    honoured as a floor in every case — it is an explicit request from the deck.
    0 is returned when the gap cannot be measured — Ignore=2 then makes the
    starter default dsearch to the average main segment size."""
    from ..gapmin import _coords_for, _round_sig, max_node_to_triangles
    floor = max(-c.sst if c.sst < 0.0 else 0.0,
                -c.mst if c.mst < 0.0 else 0.0)
    if _tied_slave_is_part_side(state, c.ssid, c.sstyp):
        if floor > 0.0:
            state.warn(
                f"{label} {c.inter_id}: SECONDARY side ssid={c.ssid} "
                f"sstyp={c.sstyp} is a whole part/part set -> dsearch={floor:g} "
                "from the negative Card-3 SST/MST absolute tie distance (the "
                "measured worst-node distance is not used for a part side: it "
                "would return the part's diameter, not the tie gap)."
            )
            return floor
        state.warn(
            f"{label} {c.inter_id}: SECONDARY side ssid={c.ssid} "
            f"sstyp={c.sstyp} is a whole part/part set, so its node group is "
            "the part's entire node cloud, not a tie surface -> dsearch left 0 "
            "and the starter uses its average-main-segment default (Ignore=2), "
            "matching the native OpenRadioss reader. Nodes beyond it are "
            "dropped from the tie and printed in the starter output. Give the "
            "tie a *SET_NODE_LIST/*SET_SEGMENT secondary side, or a negative "
            "Card-3 SST/MST, if you need an explicit tie distance."
        )
        return 0.0
    gap = max_node_to_triangles(_coords_for(state, slave_nids), verts, faces)
    if gap is None:
        if floor > 0.0:
            state.warn(
                f"{label} {c.inter_id}: node-to-segment gap not measurable "
                f"(missing coordinates) — dsearch={floor:g} taken from the "
                "negative Card-3 SST/MST absolute tie distance."
            )
            return floor
        state.warn(
            f"{label} {c.inter_id}: node-to-segment gap not measurable "
            "(missing coordinates) — dsearch left 0, so the starter defaults it "
            "to the average main-segment size (Ignore=2). If tied nodes sit "
            "further than that from the main shell mid-plane, the starter "
            "deletes them from the tie (they are printed in the starter output)."
        )
        return 0.0
    dsearch = _round_sig(max(gap * _TIED_DSEARCH_MARGIN, floor), 4)
    if dsearch > 0.0:
        state.warn(
            f"{label} {c.inter_id}: worst secondary-node-to-main-segment "
            f"distance is {gap:g} (a mid-plane offset of ~half the main shell "
            f"thickness is expected for shell welds) -> /INTER/TYPE2 "
            f"dsearch={dsearch:g} so every tied node finds its main segment. "
            "Nodes beyond dsearch would be dropped from the tie by the starter "
            "(Ignore=2)."
        )
    return dsearch


def _make_tied_interfaces(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """*CONTACT_TIED_* → /INTER/TYPE2 (kinematic) or /INTER/TYPE10 (penalty tie).

    The dyna2rad discriminator (SFST*SST + SFMT*MST)/2 < 0 picks the penalty tie
    /INTER/TYPE10 (physical offset kept, secondary nodes may coexist with
    /RBODY); otherwise the kinematic /INTER/TYPE2 (secondary nodes projected onto
    the main segment). Both take a /GRNOD secondary side + /SURF main side.
    """
    if not state.contacts_tied:
        return []
    lines = ["#-  TIED INTERFACES (*CONTACT_TIED_* -> /INTER/TYPE2 | /INTER/TYPE10):", HDR]
    dropped: Dict[str, List[int]] = {}
    for c in state.contacts_tied:
        itype = _tied_interface_type(c)
        if c.fs == _FS_DEFINE_FRICTION:
            # Not silently dropped: _bind_friction_table names the interface,
            # the target type and why neither TYPE2 nor TYPE10 can hold the
            # binding. (Friction on a tie is meaningless until the tie fails,
            # so this is rarely load-bearing — but "rarely" is not "never".)
            _bind_friction_table(state, 0.0, c.inter_id,
                                 f"CONTACT_TIED_{c.variant}", itype)
        nids = _tied_slave_nids(state, c.ssid, c.sstyp)
        if itype == "TYPE10":
            # Penalty tie: rigid-body secondary nodes are permitted (the bond is
            # a spring, not a kinematic constraint), so they are kept.
            clean = list(nids)
        else:
            clean = [n for n in nids if n not in rigid_nodes]
            if len(clean) < len(nids):
                state.warn(
                    f"TIED CONTACT {c.inter_id}: {len(nids) - len(clean)} secondary "
                    "node(s) belong to a rigid body and were removed from the tie "
                    "(/INTER/TYPE2 is a kinematic condition — it cannot share a "
                    "node with /RBODY)."
                )
        if not clean:
            all_rigid = bool(nids)
            _drop_interface(
                state, dropped, f"CONTACT_TIED_{c.variant}", c.inter_id,
                (f"the SECONDARY (SSID) side ssid={c.ssid} sstyp={c.sstyp} "
                 f"resolved to {len(nids)} node(s) and ALL of them belong to a "
                 "rigid body, leaving an empty secondary node group "
                 "(/INTER/TYPE2 is a kinematic tie: it cannot share a node "
                 "with a /RBODY)" if all_rigid else
                 f"the SECONDARY (SSID) side ssid={c.ssid} sstyp={c.sstyp} "
                 "resolved to no nodes at all"),
                ("REMEDY: swap the sides so the DEFORMABLE part supplies the "
                 "tied nodes, or give the tie a negative Card-3 SST/MST so it "
                 "routes to the penalty tie /INTER/TYPE10, which does accept "
                 "rigid-body secondary nodes." if all_rigid else
                 "REMEDY: check that SSID names a part, part set, node set or "
                 "segment set that exists in this deck and carries nodes."))
            continue
        master_lines: List[str] = []
        surf_id, verts, faces = _tied_master_surface(state, c, master_lines)
        if not surf_id:
            _drop_interface(
                state, dropped, f"CONTACT_TIED_{c.variant}", c.inter_id,
                f"the MAIN (MSID) side msid={c.msid} mstyp={c.mstyp} resolved "
                "to no contact surface",
                "REMEDY: point MSID at a part, part set or *SET_SEGMENT that "
                "exists in this deck and carries shell/solid elements.")
            continue
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"tied_{c.inter_id}_slave", clean)
        lines += master_lines
        if itype == "TYPE10":
            gap = _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id, target="TYPE10")
            lines += _emit_inter_type10(c.inter_id, c.title, grnod_id, surf_id, gap)
            state.warn(
                f"*CONTACT_TIED_SURFACE_TO_SURFACE{'_OFFSET' if c.offset else ''} "
                f"{c.inter_id} -> /INTER/TYPE10/{c.inter_id} (penalty tie: "
                f"(SFST*SST + SFMT*MST)/2 = {(c.sfst * c.sst + c.sfmt * c.mst) / 2.0:g} "
                f"< 0, LS-DYNA's negative offset). GAP={gap:g}, {len(clean)} "
                "secondary nodes. Unlike TYPE2 this bonds by penalty (rigid-body "
                "secondary nodes allowed) and does not tie rotations."
            )
            continue
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
            f"{c.inter_id} -> /INTER/TYPE2/{c.inter_id} (tied interface, "
            f"Spotflag={spotflag}, {len(clean)} secondary nodes). Spotflag "
            f"{spotflag} is the kinematic tie with an AUTOMATIC SWITCH TO A "
            "PENALTY tie on any secondary node whose kinematic condition is "
            "incompatible — a purely kinematic Spotflag (1/5) makes the starter "
            "fail with ERROR 556 as soon as a tied node is also needed by "
            "another interface, which happens whenever the two tied parts are "
            "conformally meshed and share nodes." + rot_note
        )
    _note_dropped_interfaces(state, dropped)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: cohesive tiebreak contacts (*CONTACT_..._TIEBREAK → /INTER/TYPE2)
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA tiebreak Card-4 family → the /INTER/TYPE2 Spotflag of the PERMANENT
#: tie (the route taken whenever the failure criterion is not expressible).
#: Both are the AUTO-PENALTY formulations for the reason spelled out at
#: _TIED_SPOTFLAG: chktyp2.F:82 tags the secondary nodes of every TYPE2 outside
#: {25,26,27,28} and any MAIN node carrying that tag is hard ERROR 556, which
#: is exactly the shape of a conformally meshed tiebreak.
_TIEBREAK_TIE_SPOTFLAG = {
    "AUTOMATIC": 27,
    "SURFACE":   27,
    "NODES":     28,
}

#: The bond classes of handlers._TIEBREAK_OPTION_CLASS that /INTER/TYPE2's
#: rupture can reproduce. ONLY "CCRIT" (LS-DYNA OPTION 6 and 8) qualifies, and
#: the reason is one field: Radioss releases a tie on DISPLACEMENT and nothing
#: else (``ruptint2.F:138`` for Rupt=2: ``IRUPT = 1`` when
#: ``|d_n| > Max_N_Dist .OR. d_t > Max_T_Dist``), while the stress functions
#: only CAP the transmitted traction (``:130-136``, ``FACN = MIN(1,
#: |SIGNMAX/SIGN|)``) and set the PARTIAL-rupture state ``IRUPT = -1``. OPTION
#: 6/8 is the one class that states a release distance:
#:
#:   "After the failure stress tiebreak criterion is met, damage is a linear
#:    function of the distance between points initially in contact. When the
#:    distance equals PARAM, damage is fully developed, and interface failure
#:    occurs."                                        (Vol I R17 p.11-37)
#:
#: A constant fct_IDsn with no Max_N_Dist would be a tie that is force-capped
#: FOREVER and never releases — legal, accepted by the starter, and the wrong
#: physics.
_TIEBREAK_RUPTURE_CLASSES = ("CCRIT",)


def _tiebreak_secondary_classes(state: ConversionState,
                                nids: Set[int]) -> Tuple[bool, bool]:
    """(has_shell, has_solid) over the elements attached to *nids*.

    Picks the rupture Spotflag, because 20/21/22 differ ONLY in where the
    secondary node's tributary AREA comes from (``i2surfs.F:70-73``:
    ``ILEV 11/21 -> ISOL = 0``, ``ILEV 12/22 -> ICOQ = 0``) and a node with no
    element of the selected class gets AREA = 0, which is ``ERROR 670``.
    """
    has_shell = has_solid = False
    for e in state.shell_elems:
        if not nids.isdisjoint(e.nodes):
            has_shell = True
            break
    for tab in (state.solid_elems, state.tshell_elems):
        if has_solid:
            break
        for e in tab:
            if not nids.isdisjoint(e.nodes):
                has_solid = True
                break
    return has_shell, has_solid


def _tiebreak_option_note(c) -> str:
    """One sentence naming what LS-DYNA's OPTION does, for the warnings."""
    from ..handlers import _TIEBREAK_OPTION_CLASS, _TIEBREAK_USER_OPTIONS
    if c.family == "NODES":
        return ("the FORCE criterion (|fn|/NFLF)^NEN + (|fs|/SFLF)^MES >= 1 "
                f"with NFLF={c.nflf:g}, SFLF={c.sflf:g}, NEN={c.nen:g}, "
                f"MES={c.mes:g}")
    if c.option in _TIEBREAK_USER_OPTIONS:
        return f"OPTION {c.option} (a _USER failure subroutine)"
    cls = _TIEBREAK_OPTION_CLASS.get(c.option)
    if cls is None:
        return f"OPTION {c.option} (not in the Vol I R17 p.11-36..11-38 list)"
    return f"OPTION {c.option} — {cls[1]}"


def _tiebreak_bond_class(c) -> str:
    """The bond class of one record (see handlers._TIEBREAK_OPTION_CLASS)."""
    from ..handlers import _TIEBREAK_OPTION_CLASS, _TIEBREAK_USER_OPTIONS
    if c.family == "NODES":
        return "FORCE"
    if c.option in _TIEBREAK_USER_OPTIONS:
        return "USER"
    entry = _TIEBREAK_OPTION_CLASS.get(c.option)
    return entry[0] if entry else "UNKNOWN"


def _tiebreak_dt_noda_cst(state: ConversionState) -> bool:
    """True when the engine deck will carry /DT/NODA/CST — mirrors
    ``writer/assembly._make_engine_timestep``.

    Radioss Reference Guide p.1947 Comment 6: *"Spotflag = 20, 21 or 22 can
    include falure and be used to model a glue connection. It is not compatible
    with nodel time step /DT/NODA/CST."* Neither the starter nor the engine
    guards it (a grep over ``starter/source/interfaces`` for a NODADT + ILEV
    test returns nothing), so the refusal has to happen at conversion time."""
    ts = state.ctrl_timestep
    return bool(ts is not None and not state.is_implicit and not state.is_modal
                and ts.dt2ms < 0.0 and not state.options.ams)


def _tiebreak_rupture_plan(state: ConversionState, c, sec_nids: Set[int],
                           main_nids: Set[int]):
    """Decide whether this tiebreak gets the /INTER/TYPE2 RUPTURE cards.

    Returns ``(spotflag, ccrit)`` for a rupture tie, or ``None`` for the
    permanent tie. Every ``None`` return warns and names the field or the
    solver constraint that forced it — a silently downgraded bond is exactly
    the loss this batch exists to stop.
    """
    kw, iid = c.keyword, c.inter_id
    cls = _tiebreak_bond_class(c)

    # ── 1. the class must state a RELEASE DISTANCE ────────────────────────
    if cls not in _TIEBREAK_RUPTURE_CLASSES:
        return None
    ccrit = c.param
    if ccrit <= 0.0:
        state.warn(
            f"*{kw} {iid}: OPTION {c.option} needs PARAM = CCRIT, the "
            "crack-opening distance at which damage is fully developed (Vol I "
            f"R17 p.11-37), and the card gives PARAM={c.param:g}. Without it "
            "there is no release distance to write into /INTER/TYPE2's "
            "Max_N_Dist, so the bond is converted as a PERMANENT tie instead "
            "of a rupturing one. REMEDY: state PARAM on Card 4.")
        return None

    # ── 2. NFLS and SFLS must both be defined ─────────────────────────────
    # Vol I R17 p.11-73 Remark 2 / p.11-70 Remark 2: "Both NFLS and SFLS must
    # be defined ... If failure in only tension or shear is required, then set
    # the other failure force to a large value (10**10)." So a 0 or blank cell
    # is a MALFORMED card, not a "no failure in this mode" request — the
    # manual's own idiom for that is a huge value. It also cannot be written:
    # hm_read_inter_type02.F:373 turns Fscalestress = 0 into ONE pressure
    # unit, so a zero NFLS would silently become a 1 MPa bond.
    if c.nfls <= 0.0 or c.sfls <= 0.0:
        state.warn(
            f"*{kw} {iid}: NFLS={c.nfls:g} SFLS={c.sfls:g} — LS-DYNA requires "
            "BOTH ('Both NFLS and SFLS must be defined', Vol I R17 p.11-73 "
            "Remark 2) and its idiom for 'no failure in this mode' is a LARGE "
            "value (1e10), never zero. A zero cannot be written either: "
            "hm_read_inter_type02.F:373 turns Fscalestress = 0 into ONE "
            "pressure unit, which would silently become a 1-unit bond. "
            "Converted as a PERMANENT tie; state both stresses to get the "
            "rupture card.")
        return None

    # ── 3. the rupture Spotflags are KINEMATIC — the ERROR 556 trap ───────
    # chktyp2.F:82 tags a TYPE2's secondary nodes whenever Spotflag is NOT one
    # of 25/26/27/28 — 20/21/22 ARE tagged — and :98-104 raises the hard
    # ERROR 556 for every MAIN node carrying the tag. There is no escape via
    # the auto-penalty flavours: hm_read_inter_type02.F:343 gates the rupture
    # cards on 20/21/22 and :301 gates the penalty card on 25/26/27/28, and the
    # IRUPT array 27/28 would need is already taken (itagsl2.F:225-241 reuses
    # it as the per-node kinematic/penalty switch). MEASURED on two
    # conformally adjacent bricks: Spotflag 5 and 22 both gave 3 x ERROR 556 +
    # ERROR TERMINATION; 27 and 28 gave 0 errors and NORMAL TERMINATION.
    shared = sec_nids & main_nids
    if shared:
        state.warn(
            f"*{kw} {iid}: the two tiebreak surfaces are CONFORMALLY meshed — "
            f"{len(shared)} node(s) belong to both the secondary side "
            f"(ssid={c.ssid}) and the main side (msid={c.msid}). "
            "/INTER/TYPE2's rupture formulations (Spotflag 20/21/22) are "
            "KINEMATIC, and chktyp2.F:82/98 raises the hard ERROR 556 'MAIN "
            "NODE IS ALSO SECONDARY NODE OF ANOTHER INTERFACE TYPE2' for "
            "every one of them, so the starter would refuse the deck. There "
            "is no penalty flavour of the rupture tie (the rupture cards are "
            "gated on Spotflag 20/21/22 and the penalty card on 25/26/27/28 — "
            "hm_read_inter_type02.F:343 and :301 — and the two sets are "
            "disjoint). Converted as the auto-penalty PERMANENT tie, which "
            "does start clean; the failure is DROPPED. REMEDY: separate the "
            "two surfaces' meshes (no shared nodes) if the release matters.")
        return None

    # ── 4. solver-mode restrictions on 20/21/22 ───────────────────────────
    if state.is_implicit:
        state.warn(
            f"*{kw} {iid}: the /INTER/TYPE2 rupture (Spotflag 20/21/22) "
            "cannot be used in an IMPLICIT run — Radioss Reference Guide "
            "p.1947 Comment 6: 'This failure option (Spotflag = 20, 21 or 22) "
            "can not be used in implicit.' Converted as a PERMANENT tie; the "
            "failure is DROPPED.")
        return None
    if _tiebreak_dt_noda_cst(state):
        state.warn(
            f"*{kw} {iid}: this deck scales the time step with /DT/NODA/CST "
            "(*CONTROL_TIMESTEP DT2MS < 0), and Radioss Reference Guide "
            "p.1947 Comment 6 states the rupture Spotflags are 'not compatible "
            "with nodel time step /DT/NODA/CST'. Neither the starter nor the "
            "engine checks it, so the refusal is made here: converted as a "
            "PERMANENT tie, failure DROPPED. REMEDY: drop DT2MS (or pass "
            "--ams, which emits /DT/AMS instead) if the rupture matters.")
        return None

    # ── 5. Spotflag from the secondary side's element classes (ERROR 670) ──
    has_shell, has_solid = _tiebreak_secondary_classes(state, sec_nids)
    if has_shell and has_solid:
        spotflag = 20
        state.warn(
            f"*{kw} {iid}: the secondary side carries BOTH shells and solids, "
            "so Spotflag=20 is used and i2surfs.F sums BOTH contributions "
            "into each node's tributary area (quads A/4, trias A/3, bricks "
            "(F_a+F_b+F_c)/12). On a node where a shell and a solid meet, the "
            f"effective bond force is NFLS={c.nfls:g} times that SUM, i.e. "
            "larger than the segment-area normalisation LS-DYNA uses. Split "
            "the tie so the secondary side is homogeneous if that matters.")
    elif has_shell:
        spotflag = 21
    elif has_solid:
        spotflag = 22
    else:
        state.warn(
            f"*{kw} {iid}: no shell or solid element is attached to the "
            "secondary nodes, so /INTER/TYPE2's rupture has no tributary area "
            "to turn the nodal force into a stress — i2surfs.F:287-292 raises "
            "ERROR 670 on a zero secondary area. Converted as a PERMANENT "
            "tie; the failure is DROPPED.")
        return None
    return spotflag, ccrit


def _tiebreak_area_note(spotflag: int, nfls: float) -> str:
    """The NFLS -> Fscalestress normalisation caveat, per Spotflag.

    LS-DYNA normalises the tie force by the reference SEGMENT area; Radioss by
    the secondary node's own tributary area from ``i2surfs.F``. For SHELLS the
    two are the same quantity — ``AREA(node) = sum(A_quad)/4 + sum(A_tri)/3``
    (``i2surfs.F:110,136``) is exactly the node's share of the mid-surface, and
    a three-way probe on one mesh confirmed it to 0.000 % (predicted 1250.0 N,
    measured 1250.0 N). For SOLIDS ``i2surfs.F:265-278`` sums the THREE brick
    faces meeting at the node over 12, so with a bond face a x b and a
    thickness t normal to it the ratio to the tributary bond area ab/4 is
    ``(1 + t/a + t/b)/3`` — 1 for a cube, 2/3 at t = a/2 (measured 0.6667),
    1/3 in the thin-plate limit. That factor is per-node mesh geometry, so it
    is STATED, never fitted into the card.
    """
    if spotflag == 21:
        return ("Secondary side is shells, so the stress normalisation is "
                "exact: i2surfs.F gives each node sum(A_quad)/4 + sum(A_tri)/3, "
                "the same tributary mid-surface area LS-DYNA divides by "
                "(measured 0.000 % error on a probe coupon).")
    return (
        f"Secondary side is solids: Fscalestress={nfls:g} is applied to the "
        "node's tributary area from i2surfs.F:265-278, (F_a+F_b+F_c)/12 over "
        "the three brick faces meeting at the node, while LS-DYNA divides by "
        "the reference SEGMENT area. For a bond face a x b on elements of "
        "thickness t the ratio is (1 + t/a + t/b)/3 — exactly 1 for cubic "
        "elements, 2/3 at t = a/2, 1/3 in the thin-plate limit. No constant "
        "conversion factor exists (it is per-node mesh geometry), so NFLS is "
        "written through unchanged and the mesh dependence is stated here.")


def _make_tiebreak_interfaces(state: ConversionState,
                              rigid_nodes: Set[int]) -> List[str]:
    """``*CONTACT_..._TIEBREAK`` → ``/INTER/TYPE2`` (+ a companion
    ``/INTER/TYPE25`` behind a rupturing tie).

    The pre-failure state of every spelling routed here is a TIE (Vol I R17
    p.11-9), so the tie is what gets emitted. Whether it also RUPTURES is
    decided by :func:`_tiebreak_rupture_plan`.
    """
    from .loads import _emit_funct
    if not state.contacts_tiebreak:
        return []
    lines = ["#-  TIEBREAK INTERFACES (*CONTACT_..._TIEBREAK -> /INTER/TYPE2):",
             HDR]
    dropped: Dict[str, List[int]] = {}
    for c in state.contacts_tiebreak:
        nids = _tied_slave_nids(state, c.ssid, c.sstyp)
        clean = [n for n in nids if n not in rigid_nodes]
        if len(clean) < len(nids):
            state.warn(
                f"*{c.keyword} {c.inter_id}: {len(nids) - len(clean)} secondary "
                "node(s) belong to a rigid body and were removed from the tie "
                "(/INTER/TYPE2 is a kinematic condition — it cannot share a "
                "node with /RBODY).")
        if not clean:
            _drop_interface(
                state, dropped, c.keyword, c.inter_id,
                f"the SURFA (secondary) side ssid={c.ssid} sstyp={c.sstyp} "
                f"resolved to {len(nids)} node(s)"
                + (" and ALL of them belong to a rigid body" if nids else ""),
                "REMEDY: check that SURFA names a part, part set, node set or "
                "segment set that exists in this deck and carries nodes; a "
                "tiebreak whose bonded side is rigid has nothing to tie.")
            continue
        master_lines: List[str] = []
        surf_id, verts, faces = _tied_master_surface(state, c, master_lines,
                                                     tag="tiebreak")
        if not surf_id:
            _drop_interface(
                state, dropped, c.keyword, c.inter_id,
                f"the SURFB (main) side msid={c.msid} mstyp={c.mstyp} resolved "
                "to no contact surface",
                "REMEDY: point SURFB at a part, part set or *SET_SEGMENT that "
                "exists in this deck and carries shell/solid elements.")
            continue
        sec_set = set(clean)
        main_set = set(_tied_slave_nids(state, c.msid, c.mstyp))
        plan = _tiebreak_rupture_plan(state, c, sec_set, main_set)

        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"tiebreak_{c.inter_id}_slave",
                                  clean)
        lines += master_lines
        dsearch = _tied_dsearch(state, c, clean, verts, faces,
                                label="TIEBREAK CONTACT")

        title = c.title or f"TIEBREAK_CONTACT_{c.inter_id}"
        if plan is None:
            spotflag = _TIEBREAK_TIE_SPOTFLAG[c.family]
            lines += _emit_inter_type2(c.inter_id, title, grnod_id, surf_id,
                                       spotflag, dsearch)
            # The consequence text is NOT the same for every class. For
            # OPTION 1/-1 LS-DYNA's bond never fails either, so a permanent tie
            # loses NOTHING about the failure — saying "the failure is dropped,
            # the joint is unbreakable" there would state a fact the source
            # deck does not contain.
            if _tiebreak_bond_class(c) == "NOFAIL":
                consequence = (
                    "That bond NEVER FAILS in LS-DYNA either, so the permanent "
                    "tie reproduces it: nothing about the failure is lost. "
                    "What OpenRadioss cannot follow is the GROWING tie set — "
                    "LS-DYNA also sticks nodes that come into contact later, "
                    "while the starter fixes the tied pairs once, at "
                    "initialization.")
            else:
                consequence = (
                    "OpenRadioss releases a /INTER/TYPE2 tie on DISPLACEMENT "
                    "and nothing else (ruptint2.F:138: IRUPT=1 when "
                    "|d_n| > Max_N_Dist or d_t > Max_T_Dist; the stress "
                    "functions only CAP the transmitted traction, :130-136), "
                    "so a criterion that states no release DISTANCE cannot be "
                    "reproduced and the FAILURE is DROPPED — the joint is "
                    "unbreakable and transmits force past the LS-DYNA "
                    "threshold. Everything up to failure is faithful: LS-DYNA "
                    "ties these surfaces too (Vol I R17 p.11-9, 'TIEBREAK is a "
                    "special case of a tied contact allowing failure'). "
                    "REMEDY: restate the bond as OPTION 6 (solids/thick "
                    "shells) or 8 (offset shells) with PARAM = the "
                    "crack-opening distance at full damage — that pair "
                    "converts to a real rupture tie.")
            state.warn(
                f"*{c.keyword} {c.inter_id} -> /INTER/TYPE2/{c.inter_id} "
                f"(PERMANENT tie, Spotflag={spotflag}, {len(clean)} secondary "
                f"nodes). The LS-DYNA bond is {_tiebreak_option_note(c)}. "
                + consequence)
            _tiebreak_report_dropped_cells(state, c, ruptured=False)
            continue

        spotflag, ccrit = plan
        # The two traction-separation functions. ruptint2.F:130-131:
        #   SIGNMAX = SSR * SCAL_F * f_sn(|d_n| / SCAL_D)
        #   SIGTMAX = SSR * SCAL_F * f_st( d_t  / SCAL_D)
        # with SSR = 1 (no rate function) and SCAL_D = 1 (abscissae in model
        # length units). Writing SCAL_F = NFLS and the ordinates as the LINEAR
        # 1 -> 0 ramp over [0, CCRIT] reproduces OPTION 6/8's "damage is a
        # linear function of the distance between points initially in contact,
        # fully developed at PARAM" term for term, and puts NFLS in a slot the
        # starter ECHOES (the RUPTURE PARAMETERS block prints SCAL_F), so the
        # transfer is independently checkable. The shear ordinate SFLS/NFLS is
        # a ratio of two card cells — not a conversion factor.
        #
        # The one term LS-DYNA has and Radioss does not is the INTERACTION:
        # LS-DYNA fails on (sn/NFLS)^2 + (ss/SFLS)^2 >= 1 while ruptint2.F caps
        # the two components INDEPENDENTLY. Under pure tension or pure shear
        # the two agree exactly; under mixed loading the Radioss tie is
        # stronger. Named in the warning below, never fudged.
        fct_sn = state.next_curve_id()
        fct_st = state.next_curve_id()
        lines += _emit_funct(
            fct_sn, f"tiebreak_{c.inter_id}_sigma_n",
            [(0.0, 1.0), (ccrit, 0.0), (2.0 * ccrit, 0.0)])
        lines += _emit_funct(
            fct_st, f"tiebreak_{c.inter_id}_sigma_t",
            [(0.0, c.sfls / c.nfls), (ccrit, 0.0), (2.0 * ccrit, 0.0)])
        lines += _emit_inter_type2(
            c.inter_id, title, grnod_id, surf_id, spotflag, dsearch,
            rupture=(fct_sn, fct_st, c.nfls, ccrit, ccrit))
        state.warn(
            f"*{c.keyword} {c.inter_id} -> /INTER/TYPE2/{c.inter_id} with "
            f"RUPTURE (Spotflag={spotflag}, Rupt=2, {len(clean)} secondary "
            f"nodes). OPTION {c.option}'s PARAM (CCRIT) = {ccrit:g} is written "
            f"1:1 as Max_N_Dist = Max_T_Dist; NFLS={c.nfls:g} as "
            f"Fscalestress; the linear damage ramp as /FUNCT/{fct_sn} "
            f"(1 -> 0 over [0, {ccrit:g}]) and /FUNCT/{fct_st} "
            f"(SFLS/NFLS = {c.sfls / c.nfls:g} -> 0). Isym=1 reproduces "
            "'compressive stress does not contribute to the failure equation'. "
            "DIFFERENCE TO NAME: LS-DYNA's criterion couples the two "
            "components, (sn/NFLS)^2 + (ss/SFLS)^2 >= 1, while ruptint2.F caps "
            "them INDEPENDENTLY — identical under pure tension or pure shear, "
            "and the converted tie is stronger under mixed loading. "
            + _tiebreak_area_note(spotflag, c.nfls))
        state.warn(
            f"/INTER/TYPE2/{c.inter_id}: the engine prints 'START RUPTURE "
            "SECONDARY NODE <n>' and 'TOTAL RUPTURE SECONDARY NODE <n>' with "
            "the time for every node it releases (ruptint2.F:201-213), and "
            "/ANIM/NODA/DAMA2 carries the per-node damage percentage. Use "
            "them to check the bond actually breaks when it should.")
        _tiebreak_report_dropped_cells(state, c, ruptured=True)

        # ── the post-failure contact ──────────────────────────────────────
        if c.only:
            state.warn(
                f"*{c.keyword} {c.inter_id}: no companion contact interface is "
                "emitted, and that is the FAITHFUL answer — the _ONLY spelling "
                "'stops acting as a contact altogether' after failure (Vol I "
                "R17 p.11-73 Remark 3 / p.11-71 Remark 3), and a totally "
                "ruptured /INTER/TYPE2 secondary node is likewise a completely "
                "free particle: i2for10.F has branches for IRUPT==0 (kinematic "
                "transfer) and IRUPT==-1 (spring) and NO branch for IRUPT==1, "
                "so nothing at all is applied. The two semantics coincide "
                "exactly.")
            continue
        lines += _tiebreak_companion_contact(state, c, grnod_id, surf_id)
    _note_dropped_interfaces(state, dropped)
    return lines


def _tiebreak_companion_contact(state: ConversionState, c, grnod_id: int,
                                surf_id: int) -> List[str]:
    """The post-failure ``/INTER/TYPE25`` behind a RUPTURING tiebreak tie.

    Vol I R17 p.11-39 Remark 1 / p.11-73 Remark 3: a non-``_ONLY`` tiebreak
    *"behaves as a surface-to-surface contact"* once the bond fails. A bare
    ``/INTER/TYPE2`` gives no such thing — a totally ruptured node is free
    (``i2for10.F`` has no ``IRUPT==1`` branch) — so the contact has to be a
    second interface. MEASURED on a break-then-coast twin: bare tie, final gap
    **-0.660121 mm** (straight through the other body) and 0.000 contact
    energy; with this companion at ``Irem_i2 = 3`` the descent was arrested and
    reversed (+0.0936 -> +0.715 mm) at 0.0334 mJ contact energy.

    ``Irem_i2 = 3`` is the load-bearing cell — see ``_emit_inter_type25``. The
    same twin at the DEFAULT (``Irem_i2 = 1``) was byte-identical to having no
    companion at all.

    ``Inacti = 5`` is what keeps it inert while the tie still holds: the same
    coupon with and without the companion moved the rupture onset from
    0.918598647E-03 s to 0.917179015E-03 s, **-0.155 %** — no double stiffness
    and no t = 0 force spike. Emitted per the #125 rule with its OWN allocated
    interface id, recorded in ``state.companion_inter_ids`` so /TH/INTER
    carries it.
    """
    comp_id = state.next_id()
    sec_pids = sorted(_contact_master_pids(state, c.ssid, c.sstyp))
    out: List[str] = []
    sec_surf = 0
    if sec_pids:
        cand = state.next_id()
        if _make_master_surface(state, cand, f"tiebreak_{c.inter_id}_post_surfa",
                                sec_pids, out):
            sec_surf = cand
    if sec_surf:
        out += _emit_inter_type25(comp_id,
                                  f"post_rupture_contact_{c.inter_id}",
                                  sec_surf, surf_id, istf=4, inacti=5,
                                  fric=c.fs, irem_i2=3)
        shape = (f"symmetric surface-to-surface (/SURF/{sec_surf} vs "
                 f"/SURF/{surf_id})")
    else:
        # ILEV=3 one-way node-to-surface (hm_read_inter_type25.F:399-434):
        # surf_ID1 = 0 with a grnd_IDs. The natural shape when SURFA is a node
        # set or a segment set, which has no part surface to build.
        out += _emit_inter_type25(comp_id,
                                  f"post_rupture_contact_{c.inter_id}",
                                  0, surf_id, grnod_id=grnod_id, istf=4,
                                  inacti=5, fric=c.fs, irem_i2=3)
        shape = (f"one-way node-to-surface (/GRNOD/NODE/{grnod_id} vs "
                 f"/SURF/{surf_id})")
    state.companion_inter_ids.append(comp_id)
    state.warn(
        f"*{c.keyword} {c.inter_id}: post-failure contact emitted as the "
        f"COMPANION /INTER/TYPE25/{comp_id}, {shape}, Irem_i2=3, Inacti=5, "
        f"Fric=FS={c.fs:g}. LS-DYNA's non-_ONLY tiebreak 'behaves as a "
        "surface-to-surface contact' after failure (Vol I R17 p.11-39 Remark "
        "1), but a totally ruptured /INTER/TYPE2 node is a FREE particle — "
        "i2for10.F has no IRUPT==1 branch, so nothing is applied — and "
        "measured on a break-then-coast probe the bare tie let the freed body "
        "pass 0.66 mm THROUGH the other one at 0.000 contact energy. Irem_i2=3 "
        "('no change to secondary nodes') is what makes the companion live: at "
        "the /DEFAULT value 1 the starter removes the TYPE2-tied nodes from it "
        "once and for all (i7remnode.F:882-901) and the card is byte-identical "
        "to having none. Inacti=5 keeps it inert before failure (measured "
        "rupture-onset shift -0.155 %).")
    return out


#: Card-4 cell -> the OPTIONs that actually READ it, quoted from the field list
#: on Vol I R17 p.11-38/11-39. A cell outside its OPTION's scope is INERT in
#: LS-DYNA too, so reporting it as "dropped" would state a loss the source deck
#: does not contain (the #130 class: an exclusion's stated reason needs the same
#: audit as a warning's). OPTION 13/14 additionally void NFLS/SFLS/ERATEN/ERATES
#: outright — p.11-42 Remark 7: "NFLS, SFLS, ERATEN, and ERATES are not used."
_TIEBREAK_FIELD_SCOPE = {
    # "Normal failure stress for OPTION = 2, 3, 4, 6, 7, 8, +-9, 10, or +-11"
    "NFLS":   (2, -2, 3, -3, 4, 6, 7, 8, 9, -9, 10, 11, -11),
    # "Shear failure stress for OPTION = 2, 3, 6, 7, 8, +-9, 10, or +-11"
    "SFLS":   (2, -2, 3, -3, 6, 7, 8, 9, -9, 10, 11, -11),
    # "For OPTION = 7, +-9, 10, +-11 only."
    "ERATEN": (7, 9, -9, 10, 11, -11),
    "ERATES": (7, 9, -9, 10, 11, -11),
    # "The ratio of the tangential stiffness to the normal stiffness for
    #  OPTION = 9, 11, 13, and 14."
    "CT2CN":  (9, 11, 13, 14),
    # "Normal stiffness (stress/length) for OPTION = 9, 11, 13, and 14 and for
    #  OPTION = 2, 4, 6, 7, and 8 for the MORTAR option only."
    "CN":     (9, 11, 13, 14),
    "CN_MORTAR": (2, 4, 6, 7, 8, 9, 11, 13, 14),
}


def _tiebreak_field_live(c, field: str) -> bool:
    """Does LS-DYNA READ this Card-4 cell at this record's OPTION?"""
    if c.family != "AUTOMATIC":
        return True
    if field == "CN" and c.mortar:
        return c.option in _TIEBREAK_FIELD_SCOPE["CN_MORTAR"]
    return c.option in _TIEBREAK_FIELD_SCOPE.get(field, ())


def _tiebreak_report_dropped_cells(state: ConversionState, c,
                                   ruptured: bool) -> None:
    """Name every Card-4 cell that has no counterpart, per record.

    Hoisted into a helper so BOTH exits (rupture tie and permanent tie) run it
    — a refusal path that skips the dropped-field inventory loses it on
    exactly the cards a reader most needs it (#129 round 2).

    A cell OUTSIDE its OPTION's documented scope (``_TIEBREAK_FIELD_SCOPE``) is
    reported as INERT, not as dropped: on the prime carrier
    (``OPTION 1, NFLS 1000, SFLS 1000, ERATEN 1.0``) all three cells are read by
    neither code, and calling them a loss would be a false fact in a warning.
    """
    lost: List[str] = []
    inert: List[str] = []
    if c.family == "AUTOMATIC":
        for name, val in (("NFLS", c.nfls), ("SFLS", c.sfls),
                          ("ERATEN", c.eraten), ("ERATES", c.erates),
                          ("CT2CN", c.ct2cn), ("CN", c.cn)):
            if val and not _tiebreak_field_live(c, name):
                inert.append(f"{name}={val:g}")
        if (c.eraten or c.erates) and _tiebreak_field_live(c, "ERATEN"):
            lost.append(
                f"ERATEN={c.eraten:g}/ERATES={c.erates:g} (normal/shear energy "
                "release rates) — /INTER/TYPE2's rupture is "
                "displacement-triggered and has no energy input")
        if c.ct2cn and _tiebreak_field_live(c, "CT2CN"):
            lost.append(
                f"CT2CN={c.ct2cn:g} (tangential/normal stiffness ratio) — the "
                "TYPE2 tie is a kinematic constraint with no stiffness input "
                "at Spotflag 20/21/22 (the Stfac/Visc/Istf card is gated on "
                "25/26/27/28, hm_read_inter_type02.F:301)")
        if c.cn and _tiebreak_field_live(c, "CN"):
            lost.append(f"CN={c.cn:g} (normal stiffness) — same reason")
        if c.param and c.option not in (6, 8):
            lost.append(
                f"PARAM={c.param:g} (OPTION {c.option} reads it as a friction "
                "angle, a damage exponent or a layer thickness, not as a "
                "distance) — no counterpart")
    elif c.family == "SURFACE":
        if c.tblcid:
            lost.append(
                f"TBLCID={c.tblcid} (the post-failure resisting-tension curve, "
                "SMP only) — after a total rupture OpenRadioss releases the "
                "node completely and cannot hold residual tension")
        if c.thkoff:
            lost.append(
                f"THKOFF={c.thkoff} (thickness offsets; LS-DYNA implements it "
                "by substituting *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK "
                f"OPTION {c.option}, which is the classification used here) — "
                "the offset itself is not represented: /INTER/TYPE2 projects "
                "the secondary node onto its main segment")
    else:                                        # NODES
        if c.nen not in (0.0, 2.0) or c.mes not in (0.0, 2.0):
            lost.append(
                f"NEN={c.nen:g}/MES={c.mes:g} (the failure exponents) — "
                "OpenRadioss releases on displacement and has no exponent")
        lost.append(
            f"NFLF={c.nflf:g}/SFLF={c.sflf:g} are FORCES (Vol I R17 p.11-70 "
            "Remark 2), while /INTER/TYPE2's Fscalestress is a STRESS; the "
            "conversion would need each secondary node's tributary area from "
            "i2surfs.F, which is mesh geometry the card does not carry")
        lost.append(
            "the per-node override of NFLF/SFLF/NEN/MES through the "
            "*SET_NODE DA1..DA4 attributes (p.11-70 Remark 1)")
    if (not ruptured and c.family in ("AUTOMATIC", "SURFACE")
            and (_tiebreak_field_live(c, "NFLS") or c.family == "SURFACE")):
        lost.append(
            f"NFLS={c.nfls:g}/SFLS={c.sfls:g} (the failure stresses "
            "themselves)")
    if c.family == "AUTOMATIC" and c.option in (3, -3):
        lost.append(
            "the GROWING tie set — OPTION "
            f"{c.option} also sticks nodes that come into contact LATER "
            "(p.11-36), while OpenRadioss fixes the tied pairs once, in the "
            "starter")
    msg = ""
    if lost:
        msg += ("Card-4 cells with no OpenRadioss counterpart, dropped by "
                "name — " + "; ".join(lost) + ".")
    if inert:
        msg += (
            (" " if msg else "")
            + "Card-4 cells outside this OPTION's field list (Vol I R17 "
            "p.11-38/39) and therefore INERT in LS-DYNA too, not lost — "
            + ", ".join(inert) + ".")
    if c.option in (-1, -2, -3):
        msg += (
            (" " if msg else "")
            + f"The negative OPTION {c.option} transfers MOMENTS through the "
            "bond; /INTER/TYPE2 ties rotations as well, so that half IS "
            "carried over — stated because the sign is otherwise silent.")
    if not msg:
        return
    state.warn(f"*{c.keyword} {c.inter_id}: " + msg)


# ─────────────────────────────────────────────────────────────────────────────
# Starter: spot-weld contacts  (*CONTACT_SPOTWELD → /INTER/TYPE2 Spotflag=28)
# ─────────────────────────────────────────────────────────────────────────────

# /INTER/TYPE2 Spotflag for a *CONTACT_SPOTWELD. 28 is the AUTO-PENALTY
# spotweld formulation and it is what dyna2rad emits for every routed TYPE2
# (convertcontacts.cxx:49 interTypeVsMapDefaultVals["TYPE2"] =
# {Ignore 2, Idel2 1, Spotflag 28}; the SPOTWELD keyword reaches that table
# through the routing branch at :183-189).
#
# The kinematic spotflags (0/1/5) are NOT an option here, and not as a matter
# of taste: chktyp2.F:82 tags a TYPE2's secondary nodes only when Spotflag is
# outside {25,26,27,28}, and any MAIN node carrying that tag is hard ERROR 556
# "MAIN NODE ID=n IS ALSO SECONDARY NODE OF ANOTHER INTERFACE TYPE2". A weld
# part meshed conformally with the sheets it joins puts the same node in both
# the secondary /GRNOD and the main /SURF, so a kinematic spotflag fails the
# starter on exactly the decks this keyword exists for. itagsl2.F:225-245
# supplies the other half: for 27/28 ONLY, a secondary node that collides with
# a rigid body, an /RBE2/RBE3 or another tie is switched to a penalty tie
# (WARNING 1179) instead of failing.
_SPOTWELD_SPOTFLAG = 28

# Idel2=1 — the tie is deleted together with the main segment it is welded to.
# dyna2rad's spotweld default (convertcontacts.cxx:49); it survives the
# starter's whitelist because 28 is in it (hm_read_inter_type02.F:269). The
# *CONTACT_TIED_* path deliberately keeps Idel2=0: a mesh-transition glue
# should not vanish, but a weld to an eroded sheet has nothing left to hold.
_SPOTWELD_IDEL2 = 1

# Fraction of (SST + MST) used as the tie search distance when the card
# supplies both. Same formula dyna2rad applies to the sibling tied contacts
# (convertcontacts.cxx:205, dSearch = 0.6*(lsdSST + lsdMST)) and the same
# expression the starter forms internally when dsearch is left 0
# (i2cor3.F:198, GAPV = MAX(0.05*DD, 0.6*(THKSECND + THKMAIN))).
_SPOTWELD_DSEARCH_FRACTION = 0.6


def _spotweld_dsearch(c) -> float:
    """/INTER/TYPE2 dsearch for one *CONTACT_SPOTWELD, from the card alone.

    dyna2rad leaves this at 0.0 for *CONTACT_SPOTWELD (convertcontacts.cxx:61,
    :318) — the 0.6*(SST+MST) branch at :205 is entered only for
    TIED_NODES_TO_SURFACE / TIEBREAK_NODES, so a spotweld's SST/MST are read
    and then dropped. That is a gap, not a decision: the starter's own default
    for dsearch=0 (i2cor3.F:198) contains the very same 0.6*(t_s + t_m) term,
    so feeding it the deck's thicknesses can only agree better with LS-DYNA
    than ignoring them. Both thicknesses must be positive, exactly as
    dyna2rad's own branch requires.

    A NEGATIVE Card-3 SST/MST is LS-DYNA's "absolute tie-criterion distance"
    (Vol I R16: a negative SAST/SBST is allowed for the tied family and means a
    separation distance, not a thickness). It is an explicit instruction from
    the deck, so it wins over the computed value.

    0 means "let the starter pick" — with Ignore=2 that is its
    average-main-segment default, which is what the native reader always gets.
    """
    floor = max(-c.sst if c.sst < 0.0 else 0.0,
                -c.mst if c.mst < 0.0 else 0.0)
    if floor > 0.0:
        return floor
    if c.sst > 0.0 and c.mst > 0.0:
        return _SPOTWELD_DSEARCH_FRACTION * (c.sst + c.mst)
    return 0.0


def _spotweld_slave_nids(state: ConversionState, sid: int, styp: int) -> List[int]:
    """Node ids of a *CONTACT_SPOTWELD secondary (weld) side.

    SSTYP 0 = segment set, 1 = shell element set, 2 = part set, 3 = part id,
    4 = node set (LS-DYNA Vol I R16, SURFATYP). 0/1 fall back to part /
    part-set / node-set lookups the way the other contact resolvers do, so a
    deck that mislabels its set type still converts.

    Unlike _tied_slave_nids this counts BEAM end nodes as part nodes, and that
    difference is what makes the keyword work at all: a spot weld's secondary
    side is the WELD, and a weld part is *ELEMENT_BEAM nuggets (SSID=3
    SSTYP=3 on every W16/W17 deck in the corpus). Resolving it over shells and
    solids only returns an empty group, and the interface is then dropped for
    "no nodes at all" — leaving the welds attached to nothing.
    """
    part_nodes = _part_node_sets(state)
    nids: Set[int] = set()

    def add_part(pid: int) -> None:
        nids.update(part_nodes.get(pid, ()))

    def add_part_set(psid: int) -> None:
        for pid in state.part_sets.get(psid, ("", []))[1]:
            add_part(pid)

    if styp == 4:
        if sid in state.node_sets:
            nids.update(state.node_sets[sid][1])
    elif styp == 3:
        add_part(sid)
    elif styp == 2:
        if sid in state.part_sets:
            add_part_set(sid)
    elif styp == 1 and sid in state.shell_sets:
        by_eid = {e.eid: e for e in state.shell_elems}
        for eid in state.shell_sets[sid][1]:
            e = by_eid.get(eid)
            if e is not None:
                nids.update(n for n in e.nodes if n > 0)
    elif styp in (0, 1):
        if sid in state.segment_sets:
            for seg in state.segment_sets[sid].segments:
                nids.update(seg)
        elif sid in state.parts:
            add_part(sid)
        elif sid in state.part_sets:
            add_part_set(sid)
        elif sid in state.node_sets:
            nids.update(state.node_sets[sid][1])
    return sorted(n for n in nids if n > 0)


def _styp_note(styp: int) -> str:
    """Extra remedy text for the SURFATYP values k2rad does not resolve.

    LS-DYNA SURFATYP 5 is "include all" (every part in the model) and 6 is
    "part set exempted" (everything except the named *SET_PART); a blank SSID
    with SSTYP=0 means the same "all" (Vol I R16, *CONTACT). Neither has a
    k2rad resolver — _spotweld_slave_nids and _contact_master_pids both key on
    a named id — so the side comes back empty and the whole interface is
    dropped. Say so by name: dyna2rad DOES convert all three (into a
    /SET/GENERAL with a KEY_type=ALL clause, plus an opt_D exemption clause for
    6), so a native re-read of the same deck produces a tie where k2rad
    produces none, and the user should know that rather than infer it from an
    "resolved to no nodes" message.
    """
    if styp == 5:
        return (" NOTE: SURFATYP=5 is LS-DYNA's \"include ALL parts\", which "
                "k2rad has no resolver for — this is a converter limitation, "
                "not a fault in the deck. dyna2rad converts it (/SET/GENERAL "
                "with an ALL clause), so a native OpenRadioss read of this "
                "deck WOULD produce a tie here. Name the parts explicitly "
                "(a *SET_PART with SURFATYP=2) to convert it with k2rad.")
    if styp == 6:
        return (" NOTE: SURFATYP=6 is LS-DYNA's \"all parts EXCEPT the named "
                "*SET_PART\", which k2rad has no resolver for — a converter "
                "limitation, not a fault in the deck. dyna2rad converts it "
                "(an ALL clause minus the set), so a native OpenRadioss read "
                "WOULD produce a tie here. Invert the set by hand into an "
                "explicit *SET_PART with SURFATYP=2 to convert it with k2rad.")
    return ""


def _make_spotweld_interfaces(state: ConversionState,
                              rigid_nodes: Set[int]) -> List[str]:
    """*CONTACT_SPOTWELD[...] → /INTER/TYPE2 (Ignore=2, Spotflag=28, Idel2=1).

    LS-DYNA's spotweld contact is what attaches the weld elements to the sheets
    they join. Skipping it is not a soft loss: on W16_spotweld_E1 the four
    MAT_100 weld beams share ZERO nodes with the 2058-node sheet mesh, so
    without this interface they float free and the weld force stays 0.000 N for
    the whole run.

    Same two entities as the tied path — a secondary /GRNOD of weld nodes and a
    main /SURF of sheet surface — but the secondary side is resolved over beams
    as well (see _spotweld_slave_nids) and Idel2 is 1 rather than 0.
    """
    if not state.contacts_spotweld:
        return []
    lines = ["#-  SPOT-WELD CONTACTS (*CONTACT_SPOTWELD -> /INTER/TYPE2 Spotflag=28):",
             HDR]
    dropped: Dict[str, List[int]] = {}
    for c in state.contacts_spotweld:
        kw = "CONTACT_SPOTWELD" + (f"_{c.variant}" if c.variant else "")
        nids = _spotweld_slave_nids(state, c.ssid, c.sstyp)
        clean = [n for n in nids if n not in rigid_nodes]
        if len(clean) < len(nids):
            state.warn(
                f"*{kw} {c.inter_id}: {len(nids) - len(clean)} secondary weld "
                "node(s) belong to a rigid body and were removed from the tie "
                "(/INTER/TYPE2 is a kinematic condition — it cannot share a "
                "node with /RBODY). Those welds carry no force in the "
                "converted model.")
        if not clean:
            _drop_interface(
                state, dropped, kw, c.inter_id,
                (f"the SECONDARY (SSID) side ssid={c.ssid} sstyp={c.sstyp} "
                 f"resolved to {len(nids)} node(s) and ALL of them belong to a "
                 "rigid body, leaving an empty weld node group"
                 if nids else
                 f"the SECONDARY (SSID) side ssid={c.ssid} sstyp={c.sstyp} "
                 "resolved to no nodes at all"),
                ("REMEDY: the SECONDARY side of a spot-weld contact must be "
                 "the WELD (its beam/solid nugget part, or a node set of weld "
                 "nodes), and it may not be rigid. Check that SSID names a "
                 "deformable part, part set, node set or segment set that "
                 "exists in this deck." + _styp_note(c.sstyp)))
            continue
        master_lines: List[str] = []
        surf_id, _verts, _faces = _tied_master_surface(
            state, c, master_lines, tag="spotweld", measure=False)
        if not surf_id:
            _drop_interface(
                state, dropped, kw, c.inter_id,
                f"the MAIN (MSID) side msid={c.msid} mstyp={c.mstyp} resolved "
                "to no contact surface",
                "REMEDY: point MSID at the part, part set or *SET_SEGMENT of "
                "the SHEETS being welded — it must exist in this deck and "
                "carry shell/solid elements." + _styp_note(c.mstyp))
            continue
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"spotweld_{c.inter_id}_slave", clean)
        lines += master_lines
        dsearch = _spotweld_dsearch(c)
        lines += _emit_inter_type2(c.inter_id,
                                   c.title or f"SPOTWELD_CONTACT_{c.inter_id}",
                                   grnod_id, surf_id,
                                   _SPOTWELD_SPOTFLAG, dsearch,
                                   idel2=_SPOTWELD_IDEL2)
        where = (f"dsearch={dsearch:g} from the Card-3 SST/MST"
                 if dsearch > 0.0 else
                 "dsearch=0, so the starter uses its own average-main-segment "
                 "default (what the native reader always gets: dyna2rad drops "
                 "SST/MST for this keyword)")
        state.warn(
            f"*{kw} {c.inter_id} -> /INTER/TYPE2/{c.inter_id} (spot-weld tie, "
            f"Spotflag={_SPOTWELD_SPOTFLAG}, Ignore=2, Idel2={_SPOTWELD_IDEL2}, "
            f"{len(clean)} weld node(s) tied to the msid={c.msid} surface, "
            f"{where}). Spotflag 28 is the auto-penalty spotweld formulation: "
            "a purely kinematic one (0/1/5) makes the starter fail with "
            "ERROR 556 as soon as the weld shares a node with the sheet it is "
            "welded to. Ignore=2 means a weld node that finds NO main segment "
            "within dsearch is silently DROPPED from the tie by the starter "
            "(WARNING 1071, i2tid3.F:116) instead of failing the run — read "
            "the starter output and confirm that count is 0, because a weld "
            "that quietly vanishes carries no load.")
    _note_dropped_interfaces(state, dropped)
    return lines
