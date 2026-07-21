"""Starter interfaces: TYPE7/TYPE25 contacts, force transducers, TYPE2 tied contacts."""

from __future__ import annotations

from typing import Dict, List, Optional, Set
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
    "_emit_inter_type11",
    "_emit_inter_type19",
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
                lines += _emit_inter_type25_self(
                    c.inter_id, c.title, self_surf, c.fs,
                    _ignore_to_inacti(c.ignore, state, c.inter_id, 0.0),
                    _stfac_for(state, c.sfs, c.inter_id) or 1.0)
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
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin),
                                       viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                       gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id))
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
            lines += _emit_inter_type7(c.inter_id, c.title, slav_grnod, mast_surf, c.fs,
                                       _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin),
                                       viss=_vdc_to_viss(c.vdc, state, c.inter_id),
                                       gapmin=gapmin, stfac=_stfac_for(state, c.sfs, c.inter_id))

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
    """
    for c in state.contacts_single:
        if c.ssid == 0:
            return c.inter_id
    if state.contacts_single:
        return state.contacts_single[0].inter_id
    if state.contacts_surf2surf:
        return state.contacts_surf2surf[0].inter_id
    # A SOFT-routed general contact is also a real interface a transducer can
    # parent on (before the SOFT-routing split, AUTOMATIC_GENERAL lived in
    # contacts_single and was picked up here). /INTER/SUB needs a surface-based
    # parent, so offer only the surface routes (-7 → TYPE7, -19 → TYPE19); a
    # -11 edge/line interface cannot host an /INTER/SUB.
    for c in state.contacts_general:
        if c.soft in (-7, -19):
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
    state.warn(
        f"CONTACT {inter_id}: ignore=0 mapped to Inacti=5. LS-DYNA "
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
                      istf: int = 4, igap: int = 0) -> List[str]:
    # istf/igap default to the ordinary single-surface/surf2surf values (Istf=4
    # minimum stiffness, Igap=0 constant gap) so those validated paths stay
    # byte-identical. The SOFT=-7 AUTOMATIC_GENERAL route overrides them to
    # Istf=2, Igap=2 to match dyna2rad's routed TYPE7 (convertcontacts.cxx map
    # cc:52 Igap=2, and cc:626 Istf=2 for SOFT<1).
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
        "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID",
        "         0         0                   0         2         0",
        HDR,
    ]


def _emit_inter_type25_self(inter_id: int, title: str, surf_id: int, fric: float,
                            inacti: int = 5, stfac: float = 1.0) -> List[str]:
    """*CONTACT_AUTOMATIC_SINGLE_SURFACE → /INTER/TYPE25 self-contact (explicit).

    surf_id is ONE surface (surf_ID1); surf_ID2=0 → self-impact, so every segment
    of the surface contacts every node of the same surface (symmetric). This is
    how the native OpenRadioss reader converts ASS; the TYPE7 node-group→surface
    k2rad emits otherwise is an asymmetric ~half-model contact whose driven part
    blows through, flying the model apart in explicit dynamics. Params match the
    native TYPE25 echo: Istf=4, Igap=2, Iedge=1000 (no edge), Inacti from ignore,
    Stfac, Coulomb Fric.
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
        "         0         0                   0                   0                   0                   0",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: *CONTACT_AUTOMATIC_GENERAL SOFT-sentinel interfaces
#   SOFT -7 → /INTER/TYPE7 · -11 → /INTER/TYPE11 (edge) · -19 → /INTER/TYPE19
# ─────────────────────────────────────────────────────────────────────────────

def _emit_inter_type11(inter_id: int, title: str, line_ids: int, line_idm: int,
                       fric: float, inacti: int = 6, viss: float = 0.0,
                       visf: float = 0.0, gapmin: float = 0.0,
                       stfac: float = 0.0) -> List[str]:
    """/INTER/TYPE11 edge-to-edge (line) contact (FORMAT radioss2020).

    ``line_ids``/``line_idm`` are /LINE group ids (NOT /SURF or /GRNOD). A
    ``line_idm`` of 0 makes the interface self edge-impact of ``line_ids``.
    Matches dyna2rad's routed TYPE11 (Idel=2, Igap=0, Istf=2, Fric=FS).
    """
    return [
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
        HDR,
    ]


def _emit_inter_type19(inter_id: int, title: str, surf_ids: int, surf_idm: int,
                       fric: float, inacti: int = 6, viss: float = 0.0,
                       visf: float = 0.0, gapmin: float = 0.0,
                       stfac: float = 0.0) -> List[str]:
    """/INTER/TYPE19 combined surface + edge contact (FORMAT radioss2021).

    Both entities are /SURF ids; the starter auto-generates the child TYPE7
    (node→segment) and TYPE11 (edge-to-edge) from the two surfaces' edges — the
    low-effort route to edge contact (no hand-built /LINE). ``surf_idm`` may
    equal ``surf_ids`` for self-contact. Iedge=2 = all segment edges.
    Matches dyna2rad's routed TYPE19 (Idel=1, Igap=0, Istf=2).
    """
    return [
        f"/INTER/TYPE19/{inter_id}",
        title or f"CONTACT_{inter_id}",
        "# surf_IDs  surf_IDm      Istf      Ithe      Igap     Iedge      Ibag      Idel     Icurv",
        f"{_i(surf_ids)}{_i(surf_idm)}         2         0         0         2         0         1         0",
        "#          Fscalegap             GAP_MAX",
        "                   0                   0",
        "#              Stmin               Stmax          %mesh_size               dtmin  Irem_gap  Irem_i2",
        "                   0                   0                   0                   0         0         0",
        "#              Stfac                Fric              Gapmin              Tstart               Tstop",
        f"{_f(stfac)}{_f(fric)}{_f(gapmin)}                   0                   0",
        "#      IBC                        Inacti                VISs                VISf              Bumult",
        f"       000{_i(inacti, 30)}{_f(viss)}{_f(visf)}                   0",
        "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID",
        "         0         0                   0         2         0",
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
    for c in state.contacts_general:
        self_contact = (c.ssid, c.sstyp) == (c.msid, c.mstyp)
        if c.soft == -11:
            tname = "TYPE11"
        elif c.soft == -19:
            tname = "TYPE19"
        else:
            tname = "TYPE7"
        gapmin = _sst_mst_to_gapmin(c.sst, c.mst, state, c.inter_id, target=tname)
        inacti = _ignore_to_inacti(c.ignore, state, c.inter_id, gapmin)
        viss = _vdc_to_viss(c.vdc, state, c.inter_id)
        stfac = _stfac_for(state, c.sfs, c.inter_id)

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
            lines += _emit_inter_type7(c.inter_id, c.title, slav, mast, c.fs,
                                       inacti, viss=viss, gapmin=gapmin, stfac=stfac,
                                       istf=2, igap=2)
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
            lines += _emit_inter_type19(c.inter_id, c.title, surf_s, surf_m, c.fs,
                                        inacti, viss=viss, gapmin=gapmin, stfac=stfac)
            state.warn(
                f"*CONTACT_AUTOMATIC_GENERAL {c.inter_id}: SOFT=-19 -> "
                f"/INTER/TYPE19 (surface+edge {'self-' if self_contact else ''}"
                "contact; the starter derives the edge lines from the two "
                "/SURF, dyna2rad sentinel routing).")
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
            lines += _emit_inter_type11(c.inter_id, c.title, line_s, line_m, c.fs,
                                        inacti, viss=viss, gapmin=gapmin, stfac=stfac)
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


def _emit_inter_type2(inter_id: int, title: str, grnod_id: int, surf_id: int,
                      spotflag: int, dsearch: float) -> List[str]:
    """/INTER/TYPE2 card (FORMAT radioss2017 — unchanged through /BEGIN 2022):
    grnd_IDs surf_IDm Ignore Spotflag Level Isearch Idel2 <blank10> dsearch(20).

    Ignore=2: secondary nodes with no main segment within dsearch are removed
    from the tie by the starter (and printed), and a dsearch of 0 is replaced
    by the starter's average-main-segment-size default. Isearch=2 = improved
    closest-segment search. Idel2=0 = engine default (no deletion).

    Spotflag 25/26/27/28 (the penalty and auto-penalty formulations — see
    _TIED_SPOTFLAG) read one EXTRA card that the purely kinematic ones do not:
    Stfac(1-20) Visc(21-40) <blank 41-60> Istf(61-70) (hm_read_inter_type02.F
    "Optional Card2 : ILEV = 25,26,27,28"). The values written are the starter's
    own defaults for a blank card (Stfac 0->1, Visc 0->0.05, Istf 0->2) and
    match the native reader's echo, so the penalty branch of the tie is scaled
    exactly as dyna2rad scales it.
    """
    lines = [
        f"/INTER/TYPE2/{inter_id}",
        title or f"TIED_CONTACT_{inter_id}",
        "#  Grnd_id   Surf_id    Ignore  Spotflag     Level   Isearch     Idel2                       dsearch",
        f"{_i(grnod_id)}{_i(surf_id)}{_i(2)}{_i(spotflag)}{_i(0)}{_i(2)}{_i(0)}          {_f(dsearch)}",
    ]
    if spotflag in _TIED_PENALTY_SPOTFLAGS:
        lines += [
            "#              Stfac                Visc                          Istf",
            f"{_f(1.0)}{_f(0.05)}                    {_i(2)}",
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
    from ..gapmin import _segment_triangles, _surface_triangles
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
                  verts, faces) -> float:
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
                f"TIED CONTACT {c.inter_id}: SECONDARY side ssid={c.ssid} "
                f"sstyp={c.sstyp} is a whole part/part set -> dsearch={floor:g} "
                "from the negative Card-3 SST/MST absolute tie distance (the "
                "measured worst-node distance is not used for a part side: it "
                "would return the part's diameter, not the tie gap)."
            )
            return floor
        state.warn(
            f"TIED CONTACT {c.inter_id}: SECONDARY side ssid={c.ssid} "
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
