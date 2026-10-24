"""Blast loads, detonations, ALE multi-material, FSI coupling, EBCS, INIVOL notes."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple
from ..state import AleFlowTrackingPlan, ConversionState, ShellInSolidPlan
from .common import (HDR, _ams_is_emitted, _emit_surf_part, _emit_surf_seg,
                     _f, _i, _part_scoped_segment_set)

__all__ = [
    "_AXIS_VEC",
    "_blast_target_bbox",
    "_infer_blast_up_axis",
    "_infer_blast_up_axis_enclosed",
    "_synthesize_blast_ground",
    "_resolve_blast_ground",
    "_make_blast_loads",
    "_make_detonations",
    "_emit_grbric_part",
    "_part_pids",
    "_make_ale_multimaterial",
    "_mean_brick_edge",
    "_make_fsi_coupling",
    "_resolve_shell_in_solid",
    "_make_shell_in_solid_coupling",
    "finalize_shell_in_solid",
    "sis_dt_inter_lines",
    "sis_dt_inter_guard",
    "_make_ebcs",
    "_make_inivol_notes",
    "_make_control_ale_notes",
    "_resolve_ale_flow_tracking",
    "ale_flow_tracking_lines",
    "_make_ale_reference_notes",
]


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
        if _part_scoped_segment_set(state, load.ssid,
                                    "*LOAD_BLAST_SEGMENT_SET",
                                    "The blast load is DROPPED."):
            continue
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
            # Imodel=2 (the Radioss default, hm_read_pblast.F blank→2) solves the
            # Friedlander decay coefficient b so the pulse reproduces the TABULATED
            # Kingery-Bulmash impulse — which is what LS-DYNA's *LOAD_BLAST_ENHANCED
            # does (both trace to Randers-Pehrson & Bannister 1997). Imodel=1 pins
            # b=1.0 (pblast_mod.F90 forces decay_inci=decay_refl=1.0 for Imodel/=2):
            # peak pressure and positive-phase duration stay correct, but since
            # I = P*t0*(b-1+exp(-b))/b^2 the delivered IMPULSE is wrong, and wrong
            # non-uniformly — under-delivering close to the charge and over-
            # delivering in the far field. Impulse is what sets the structural
            # response of a blast-loaded panel, so this must not be hard-coded to 1.
            (_i(surf_id) + _i(exp_data) + _i(1) + _i(100) + _i(2) + _i(2)
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


def _part_pids(state: ConversionState, sid: int, is_part: bool) -> List[int]:
    """Expand a part id or part-set id to a list of part ids."""
    if is_part:
        return [sid] if sid in state.parts else []
    ps = state.part_sets.get(sid)
    return list(ps[1]) if ps else []


def _warn_ale_multimaterial_omitted(state: ConversionState) -> List[str]:
    """State the ``*ALE_MULTI-MATERIAL_GROUP`` that got no ``/MAT/LAW51``.

    Nothing is silently dropped: the phase list the card would have carried, the
    modelling gap it never closed, and the way to get it back are all named —
    the card itself said none of this to the solver, because no ``/PART``
    referenced it.
    """
    for k, mmg in enumerate(state.ale_mmgs):
        submats = list(state.ale_mmg_submats.get(k, []))
        if not submats:
            state.warn(
                f"*ALE_MULTI-MATERIAL_GROUP #{k + 1}: no submaterial survives "
                "— either no *PART/material of the group is known to this "
                "converter, or every phase was dropped by the LAW51 "
                "submaterial screen (see the warning above). /MAT/LAW51 not "
                "emitted.")
            continue
        state.warn(
            f"*ALE_MULTI-MATERIAL_GROUP #{k + 1} (phases {submats}, in order): "
            "NO /MAT/LAW51 is emitted, and this is deliberate. k2rad writes "
            "the LS-DYNA per-fluid ALE layout — each fluid on its own /PART "
            "with its own single-material /MAT and Iale = 1 on its "
            "/PROP/SOLID — so no /PART in the emitted deck could reference a "
            "synthesized /MAT/LAW51: it would be an ORPHAN BY CONSTRUCTION. "
            "MEASURED, so 'orphan' is not an assumption: on a converted "
            "underwater_C, deleting the whole block left all 164 T01 channels "
            "identical at all 172 samples (max |difference| exactly "
            "0.000000e+00) at 0 ERROR / 0 WARNING / NORMAL TERMINATION. What "
            "the card was NOT free of is its own starter check — "
            "fill_buffer_51.F:496 refuses a /MAT/LAW5 phase whose Bunreacted "
            "is <= 0 (ERROR 99) — which forced a positive Bunreacted onto the "
            "material's own LIVE /MAT/LAW5, where mjwl.F:166 turns it into an "
            "added (1-F)*K*mu pre-burn stiffness that an LS-DYNA BETA = 0 card "
            "(p = F*p_eos, Vol II R17 p.2-186) does not carry. Omitting the "
            "card lets Bunreacted stay 0, which IS that LS-DYNA rule. WHAT IS "
            "STILL NOT REPRODUCED, card or no card: in OpenRadioss the ALE "
            "domain is ONE part referencing a LAW51 material with the initial "
            "fill set by /INIVOL, and k2rad emits neither. The converted deck "
            "starts and runs, but the phases CANNOT MIX: on a blast deck the "
            "detonation products cannot expand into the water region, and on a "
            "volume-fraction deck the initial fill is not the deck's. THIS "
            "CONVERTED DECK DOES NOT REPRODUCE THE LS-DYNA MODEL. To "
            "reproduce it, consolidate the per-fluid ALE parts onto one mesh, "
            "re-run with --ale-multimat-law51 to get the /MAT/LAW51 back, "
            "point that one /PART at it, and give each phase its /INIVOL fill "
            "by hand — noting that the card's ALPHA_MAT values are a "
            "PLACEHOLDER (1.0 on the first phase, 0.0 on the rest) with no "
            "relation to the deck's *INITIAL_VOLUME_FRACTION*. Also measured "
            "on these decks: underwater_C runs to its full target time with a "
            "kinetic energy 54x the LS-DYNA glstat's and an engine energy "
            "error reaching 99.9 %, and stagnation_A's engine stops at cycle "
            "18 (t = 3.9e-5 of ENDTIM 2e-2) with no termination line at all. "
            "The starter fix is real; the engine result is not the LS-DYNA "
            "answer.")
    return []


def _make_ale_multimaterial(state: ConversionState) -> List[str]:
    """*ALE_MULTI-MATERIAL_GROUP → /MAT/LAW51 (MULTIMAT), Iform=12 — under
    ``--ale-multimat-law51`` only.

    The AMMG order becomes the ordered submaterial list; each submaterial is the
    material of the referenced part(s) (a /MAT/LAW6+/EOS fluid or /MAT/LAW5
    explosive already emitted). Card layout from MAT/mat_law51.cfg
    FORMAT(radioss2023). The single-part-consolidation of the LS-DYNA multi-part
    ALE mesh is left to the user (warned).

    **Why the card is OFF by default.** k2rad writes the LS-DYNA per-fluid ALE
    layout — each fluid on its own ``/PART`` with its own single-material
    ``/MAT`` and ``Iale = 1`` on its ``/PROP/SOLID`` — so no ``/PART`` k2rad
    emits ever references the synthesized ``/MAT/LAW51``. It is an orphan BY
    CONSTRUCTION, not by accident on some decks, and MEASURED inert: deleting
    the block from a converted ``underwater_C`` left all 164 T01 channels
    identical at all 172 samples (max ``|difference|`` exactly
    ``0.000000e+00``), at 0 ERROR / 0 WARNING / NORMAL TERMINATION and the same
    172 cycles. (The T01 *file* is 52 bytes shorter and hashes differently —
    that is entity metadata in the header, not data.)

    **What the orphan card COST.** Its own starter check,
    ``fill_buffer_51.F:496``, refuses a ``/MAT/LAW5`` phase whose ``Bunreacted``
    is ``<= 0`` (``ERROR 99``) — so keeping it forced a positive ``Bunreacted``
    onto the material's own ``/MAT/LAW5``, which a ``/PART`` really does
    reference. ``mjwl.F:166`` has NO branch on that cell:
    ``PNEW = -PSH + (1-F)·(P0 + BULK·mu) + (F·JWL terms)/(...)``, so a positive
    value is an ADDED ``(1-F)·K·mu`` pre-burn stiffness at every burn fraction,
    which an LS-DYNA ``BETA = 0`` card (``p = F·p_eos``, Vol II R17 p.2-186)
    does not carry. Dropping the card lets ``Bunreacted`` stay 0, which IS that
    LS-DYNA rule. MEASURED on ``underwater_C``, four variants each run to
    completion: card + derived value → clean; card removed, value kept →
    identical to it in every channel; card removed, value 0 → 0 ERROR /
    0 WARNING / NORMAL TERMINATION, 172 cycles, and closer to the LS-DYNA
    ``glstat`` kinetic energy at all five sampled times (ratio 12.08 / 29.93 /
    66.39 / 66.46 / 54.13 against 12.64 / 30.14 / 66.61 / 66.57 / 54.19);
    card kept, value 0 → ``ERROR 99``, i.e. the deck ``--he-bunreacted 0`` used
    to produce was unstartable.
    """
    if not state.ale_mmgs:
        return []
    if not state.options.ale_multimat_law51:
        return _warn_ale_multimaterial_omitted(state)
    lines: List[str] = []
    for k, mmg in enumerate(state.ale_mmgs):
        # The phase list is DECIDED by writer/materials._resolve_ale_submaterials
        # (which drops the vacuum entry, every submaterial with no /EOS, and
        # every law fill_buffer_51.F:210 refuses), never re-derived here: two
        # walks of the same entries would be two answers to one question. There
        # is no law RESTATEMENT on this path — the *MAT_PLASTIC_KINEMATIC ->
        # /MAT/LAW2 idea was MEASURED not to work (fill_buffer_51.F:281 refuses
        # a phase with no EOS whatever its law), so such a phase is dropped by
        # name and the material keeps its LAW44.
        submats = list(state.ale_mmg_submats.get(k, []))
        if not submats:
            state.warn(
                f"*ALE_MULTI-MATERIAL_GROUP #{k + 1}: no submaterial survives "
                "— either no *PART/material of the group is known to this "
                "converter, or every phase was dropped by the LAW51 "
                "submaterial screen (see the warning above). /MAT/LAW51 not "
                "emitted.")
            continue
        # next_mat_id(), not a bare next_id(): the synthesized /MAT/LAW51 shares
        # the starter /MAT namespace with every converted *MAT, so a user MID at
        # or above the auto-id base (90001) would collide (ERROR 79 DUPLICATE
        # ID). A no-op on any deck without such a MID.
        law_id = state.next_mat_id()
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
            # This used to end "set it" — a prescription k2rad now carries out
            # itself in writer/materials._resolve_he_bunreacted, so leaving it
            # would tell the reader to supply a value the emitted deck already
            # has (the #129 cited-fact rule). What is worth saying is which
            # value went in and where it came from.
            for m in expl:
                heb = state.mat_high_explosive[m]
                state.warn(
                    f"*ALE_MULTI-MATERIAL_GROUP: /MAT/LAW51/{law_id} includes "
                    f"JWL explosive submaterial {m}, whose /MAT/LAW5 "
                    f"Bunreacted is written as {heb.bunreacted:g}"
                    + (f" from {heb.bunreacted_note}."
                       if heb.bunreacted_note else
                       " — nothing on the card or its *EOS_JWL could supply "
                       "one, so fill_buffer_51.F:496 will refuse the phase "
                       "with ERROR 99 ('BULK MODULUS OF LAW5 (JWL) MUST BE "
                       "PROVIDED FOR UNREACTED EXPLOSIVE'); state K on the "
                       "*MAT_HIGH_EXPLOSIVE_BURN card or pass "
                       "--he-bunreacted.")
                    + " A LAW5 used inside a multi-material ALE needs a "
                      "POSITIVE unreacted bulk modulus; a stand-alone "
                      "/MAT/LAW5 does not (the check is in the Iform = 12 "
                      "branch alone).")
        state.warn(
            f"*ALE_MULTI-MATERIAL_GROUP -> /MAT/LAW51/{law_id} listing "
            f"submaterials {submats} (phase order), with ALPHA_MAT = 1.0 on "
            "the first phase and 0.0 on the rest. READ THIS BEFORE TRUSTING "
            "THE RUN: **no /PART in the emitted deck references this "
            "/MAT/LAW51**, and no /INIVOL is written. In OpenRadioss the ALE "
            "domain is ONE part referencing the LAW51 material with the "
            "initial fill set by /INIVOL; what k2rad emits instead is the "
            "LS-DYNA per-fluid layout — each fluid on its own /PART with its "
            "own single-material /MAT and Iale = 1 on its /PROP/SOLID. That "
            "starts and runs, but the phases CANNOT MIX: on a blast deck the "
            "detonation products cannot expand into the water region, and on a "
            "volume-fraction deck the initial fill is not the deck's. THIS "
            "CONVERTED DECK DOES NOT REPRODUCE THE LS-DYNA MODEL. The "
            "ALPHA_MAT values are a PLACEHOLDER with no relation to the deck's "
            "*INITIAL_VOLUME_FRACTION*: they are inert exactly because nothing "
            "references the card, and they would be wrong by construction if "
            "anything did. To reproduce the model, consolidate the per-fluid "
            f"ALE parts onto one mesh that references material {law_id} and "
            "give each phase its /INIVOL fill by hand. MEASURED, so the word "
            "'inert' is not an assumption: deleting this entire /MAT/LAW51 "
            "block from a converted underwater_C left the run at 0 ERROR / "
            "0 WARNING, NORMAL TERMINATION and the same 172 cycles, with max "
            "|difference| over all 164 T01 channels and all 172 samples "
            "exactly 0.000000e+00. (The T01 FILE is 52 bytes shorter and "
            "hashes differently — that is entity metadata in the header, not "
            "data.) The card exists to answer the starter, nothing more, which "
            "is why it is emitted only under --ale-multimat-law51. What is NOT "
            "inert is the Bunreacted its own check then forces for a JWL "
            "phase: that cell rides on the material's own /MAT/LAW5, which a "
            "/PART DOES reference, and mjwl.F:166 adds it to the applied "
            "pressure as (1-F)*K*mu at every burn fraction "
            "(see the *MAT_HIGH_EXPLOSIVE_BURN warning). Also measured on "
            "these decks: underwater_C runs to its full target time with a "
            "kinetic energy 54.5x the LS-DYNA glstat's and an engine energy "
            "error reaching 99.9 %, and stagnation_A's engine stops at cycle "
            "18 (t = 3.9e-5 of ENDTIM 2e-2) with no termination line at all. "
            "The starter fix is real; the engine result is not the LS-DYNA "
            "answer.")
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
        if (cls.sstyp == 2 and cls.slave in state.segment_sets
                and not _part_scoped_segment_set(
                    state, cls.slave, "*CONSTRAINED_LAGRANGE_IN_SOLID",
                    "The coupling falls back to the part resolver below.")):
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
        grbric_id = state.next_elem_group_id()
        lines += _emit_grbric_part(grbric_id, f"fsi_fluid_{cls.master}", mpids)

        edge = _mean_brick_edge(state, set(mpids))
        gap = 0.5 * edge if edge > 0 else 1.0
        inter_id = state.next_id()
        _warn_clis_dropped_cells(state, cls, inter_id)
        _warn_initial_void_in_fsi(state, cls, mpids, inter_id)
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


def _warn_clis_dropped_cells(state: ConversionState, cls, inter_id: int) -> None:
    """The ``*CONSTRAINED_LAGRANGE_IN_SOLID`` cells that reach no ``/INTER`` cell.

    ``handle_constrained_lagrange_in_solid`` reads card-1 fields 1-4 and 6 and
    card-2 fields 1-3; ``ConstrainedLagrangeInSolid`` stores ``slave master
    sstyp mstyp ctype pfac start end``; and this writer uses ``slave``,
    ``master``, ``sstyp``, ``mstyp``, ``start``, ``end`` and NOTHING ELSE —
    ``ctype`` and ``pfac`` are parsed and never read, and EVERY OTHER CELL of
    the keyword is never parsed at all.

    The inventory is the whole point of this warning, so it is enumerated per
    card against the deck's own ``$#`` headers rather than summarised:
    card 1's ``NQUAD``, ``DIREC`` and ``MCOUP``; card 2's ``FRIC`` (the
    coupling friction coefficient — a physics cell, not a control), ``FRCMIN``,
    ``NORM``, ``NORMTYP`` and ``DAMP``; the whole of card 3 (``K``/``CQ``,
    ``HMIN``, ``HMAX``, ``ILEAK``, ``PLEAK``, ``LCIDPOR``, ``NVENT``,
    ``BLOCKAGE``); and the whole of the optional card 4 where a deck writes one
    (``IBOXID``, ``IPENCHK``, ``INTFORC``, ``IALESOF``, ``LAGMUL``, ``PFACMM``,
    ``THKF``). Censused over the 12 CLIS cards on ``F:`` and
    ``C:/openradioss_run``: every unnamed cell is 0 or its default except
    ``stagnation_A``/``_B``'s ``K 1.4013E-45``, ``BLOCKAGE 2113929216`` and
    ``IBOXID 1073741824`` — so nothing real is lost on this corpus today, which
    is a reason to name them, not a reason to leave them out.

    That the drop is real, not a bookkeeping quibble, has a controlled
    experiment in the corpus itself: ``quadrature_B`` and ``quadrature_C``
    differ in EXACTLY one cell (``NQUAD`` 1 vs 3) and emit BYTE-IDENTICAL
    ``_0000.rad`` files.

    Per CLIS card; the card ids are in the text so a deck with several is
    readable.
    """
    state.warn(
        f"*CONSTRAINED_LAGRANGE_IN_SOLID (slave {cls.slave} / master "
        f"{cls.master}) -> /INTER/TYPE18/{inter_id}: every coupling cell "
        "except the two sides and the two times is NOT PARSED at all. Vol I "
        "R17 p.10-113/114's Card Summary has SIX cards and all six are "
        "inventoried here - card 1 NQUAD, DIREC, MCOUP; card 2 FRIC (the "
        "coupling FRICTION coefficient), FRCMIN, NORM, NORMTYP, DAMP; the "
        "whole of card 3 (K, HMIN, HMAX, ILEAK, PLEAK, LCIDPOR, NVENT, IBLOCK "
        "- which the corpus decks' own $# header still spells 'blockage'); "
        "the whole of the optional card 4 (IBOXID, IPENCHK, INTFORC, IALESOF, "
        "LAGMUL, PFACMM, THKF); card 5, required for CTYPE 11/12 (A1, B1, A2, "
        "B2, A3, B3, POREINI); and card 6, one per vent hole (VENTSID, "
        "VENTYP, VTCOEF, POPPRES, COEFLC). Cards 5 and 6 have ZERO carriers on "
        "this corpus - every CLIS deck on F: writes at most cards 1-4 (plus a "
        "_TITLE id line, which is what makes ale_wavehitcol's block five lines "
        f"long) - so that half is a statement, not a measured loss. CTYPE="
        f"{cls.ctype} and PFAC={cls.pfac:g} are parsed and "
        "never read. The emitted interface uses a CONSTANT UNIT stiffness "
        "(Stfval = 1.0, Vref = 0.0, Iauto left blank so the starter takes "
        "ISTIFF = 1, 'constant user value' - hm_read_inter_type18.F:131 and "
        ":158-159) and a mesh-derived Gap = 0.5 x the mean brick edge. The "
        "corpus carries the controlled experiment for how much that costs: "
        "quadrature_B and quadrature_C differ in EXACTLY one cell (NQUAD 1 vs "
        "3) and convert to byte-identical files. HOW FAR the unit stiffness "
        "is from the solver's own idea of one: with Iauto = 2 the starter "
        "computes it itself as SCALE * Vref^2 * rho_max * A_mean / Gap "
        "(insurf_dx.F:114). MEASURED on cylinder_impact_B AS CONVERTED, with "
        "Iauto = 2 and Vref 2e5 written into the emitted card by hand (nt 4, "
        "0 starter ERROR): COMPUTED STIFFNESS VALUE 3.528, USING DENSITY "
        "1.0000000000000E-12, USING MEAN AREA 441.0 - i.e. 3.5x the 1.0 "
        "emitted here, not four orders. The rho_max the starter uses is the "
        "ALE group's, and this deck's ALE bricks are *MAT_VACUUM rho 1e-12: "
        "the *INITIAL_VOLUME_FRACTION_GEOMETRY fill that would put the "
        "*MAT_PLASTIC_KINEMATIC rho 8e-9 into them is not converted (see the "
        "ALE FILL note). WITH that fill present the same formula gives "
        "1 * (2e5)^2 * 8e-9 * 441 / 5 = 28224, which is the four-orders "
        "figure this sentence used to publish for the converted deck. NOTE "
        "ALSO that a NEGATIVE "
        "PFAC is a LOAD CURVE id, not a scale: cylinder_impact_B states -1 "
        "and stagnation_B -2, i.e. a penalty-stiffness curve, and "
        "/INTER/TYPE18 has no field for one at all. Tune Stfval/Gap by hand "
        "for your coupling.")


def _warn_initial_void_in_fsi(state: ConversionState, cls, mpids: List[int],
                              inter_id: int) -> None:
    """An ``*INITIAL_VOID_*`` part that IS the ALE fluid group of this coupling.

    The void is skipped (no Radioss card expresses it — see
    ``handlers.handle_initial_void``), so the region LS-DYNA empties converts
    as ORDINARY FLUID. On a deck where a Lagrangian body starts inside it, the
    FSI penalty then loads that body from cycle 0 against material that should
    not be there, and the run is not a wrong number, it is a different model.

    What k2rad DOES write on such a deck is the ELFORM-12 cavitation floor
    (``Pmin = -1e-20`` on the fluid's ``/MAT/HYD_VISC``, round 6), decided ONCE
    by ``materials._resolve_initial_void_floor``; this warning reads that
    record (never the option) and names it. The floor turns quadrature_B's
    timeout into a NORMAL run — the void's low density does NOT, on either
    coupled carrier: it STALLS bird_B on the /INTER/TYPE18 SORT step
    (``intcrit.F:508-518``) and costs quadrature_B 47.2x the cycles, both on
    near-massless void nodes, so it is not written.

    The predicate is the INTERSECTION, not the presence of either card, and
    BOTH controls are measured. A void with no coupling (``bird-el.k``) is a
    dropped cell and nothing more, and stays silent. A coupling with no void —
    ``stagnation_A.k``, ``stagnation_B.k``, ``cylinder_impact_B.k`` and
    ``ale_wavehitcol.k``, each of which emits its ``/INTER/TYPE18`` and gets
    the CLIS inventory but NOT this warning — is correct as emitted.
    (``quadrature_A.k`` used to be named as that control and cannot be: it
    carries NEITHER card. Its whole keyword list is a pure Lagrangian-velocity
    ALE model — ``*MAT_NULL`` + ``*EOS_GRUNEISEN`` + ``*MAT_RIGID``, no
    ``*CONSTRAINED_LAGRANGE_IN_SOLID`` and no ``*INITIAL_VOID`` — so it never
    reaches this function at all and proved nothing about either arm. It is
    still the right name for the velocity sibling below.)
    """
    if not state.initial_void_parts:
        return
    mset = set(mpids)
    hit: List[tuple] = []
    for sid, is_set in state.initial_void_parts:
        if set(_part_pids(state, sid, not is_set)) & mset:
            if (sid, is_set) not in hit:
                hit.append((sid, is_set))
    if not hit:
        return
    # The floor is decided ONCE; a direct caller of _make_fsi_coupling (no
    # materials section before it) still sees the same decision. Imported
    # here because materials.py imports this module at load time.
    from .materials import _resolve_initial_void_floor
    floor = _resolve_initial_void_floor(state)
    if floor:
        floor_clause = ("k2rad writes the cavitation floor Pmin = -1e-20 on "
                        f"/MAT/HYD_VISC {sorted(floor)}.")
    else:
        floor_clause = ("The cavitation floor is NOT written: "
                        + (state.initial_void_floor_refusal
                           or "no qualifying ELFORM-12 void") + ".")
    for sid, is_set in sorted(hit):
        kw = "*INITIAL_VOID_SET" if is_set else "*INITIAL_VOID_PART"
        state.warn(
            f"{kw} {sid} is the ALE fluid group of the emitted /INTER/TYPE18 "
            f"coupling (interface {inter_id}). {floor_clause} The region "
            "LS-DYNA empties is still converted as ORDINARY FLUID at full "
            "density, so a Lagrangian body that starts inside it is loaded by "
            "the FSI penalty from cycle 0: THE FSI RESULT ON THIS DECK IS NOT "
            "VALID. MEASURED on quadrature_B (a rigid impactor at vy = -5000 "
            "mm/s starting inside part 1), floor written: NORMAL in 1095 "
            "cycles, IE 820.4 against the LS-DYNA reference's 166.47 "
            "(+394 %), KE 7359 against 1.24046e4 (-40.7 %), engine energy "
            "error -46.5 %. The void's own low density is NOT written on a "
            "void that is a TYPE18 fluid group, because both coupled carriers "
            "measure it worse: on bird_B it fixes the initial state (cycle-0 "
            "KE 11.74 against LS-DYNA's 11.737) and then STALLS at t 2.227e-4 "
            "of 6e-4 with the step at 2.15e-18 - the /INTER/TYPE18 SORT step "
            "(intcrit.F:508-518, 0.9 x Gap over the spread of the fluid-node "
            "velocities, i7buce_crit.F:85-101; TYPE18's own kinematic step is "
            "commented out, i18for3.F:296-309, and /DT/INTER/DEL keeps a "
            "deleted node in that spread, i18for3.F:607-617) follows one "
            "near-massless void node (node 2029 at 3.34e6 mm/s against the "
            "bird's 5.1e4); on quadrature_B it costs 47.2x the floor-only "
            "cycles (51673 against 1095) on the TYPE18 nodal step of the "
            "near-massless void nodes. A correct mapping needs a void PHASE "
            "(/MAT/LAW51 multi-material + /INIVOL, or a /MAT/VOID region); "
            "not implemented. What LS-DYNA means by the card is on Vol I R17 "
            "p.28-134 (paraphrased, not quoted): evacuated fluid elements are "
            "approximated as fluid elements at a very low density, the void "
            "material's constitutive properties must be identical to those "
            "of the material that will later fill it, and the option is "
            "incompatible with *ALE_MULTI-MATERIAL_GROUP.")


def _acoustic_void_faces(state: ConversionState
                         ) -> Tuple[Set[Tuple[int, ...]], List[int]]:
    """``(faces, pids)`` of the parts on a *MAT_ACOUSTIC written as
    ``/MAT/VOID`` (round 9, A7): every corner face of their solids as a
    sorted tuple of DISTINCT node ids (a degenerate face keys like the
    triangle it is), and the part ids. Empty unless the modal route ran."""
    if not state.acoustic_void:
        return set(), []
    from .contacts import _HEX_FACE_IDX, _TET4_FACE_IDX
    pids = sorted(pid for pid, p in state.parts.items()
                  if p.mid in state.acoustic_void)
    pidset = set(pids)
    faces: Set[Tuple[int, ...]] = set()
    for e in state.solid_elems:
        if e.pid not in pidset:
            continue
        nds = list(e.nodes)
        table: Tuple[Tuple[int, ...], ...] = (
            _HEX_FACE_IDX if len(nds) >= 8 else _TET4_FACE_IDX)
        for f in table:
            if max(f) < len(nds):
                faces.add(tuple(sorted({nds[i] for i in f})))
    return faces, pids


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
    void_faces, void_pids = _acoustic_void_faces(state)
    void_named: Set[int] = set()
    for nrf in state.non_reflecting:
        segset = state.segment_sets.get(nrf.nsid)
        if _part_scoped_segment_set(state, nrf.nsid,
                                    "*BOUNDARY_NON_REFLECTING",
                                    "The /EBCS/NRF is DROPPED."):
            continue
        if segset is None or not segset.segments:
            state.warn(f"*BOUNDARY_NON_REFLECTING nsid={nrf.nsid}: segment set not "
                       "found or empty — /EBCS/NRF skipped.")
            continue
        segments = segset.segments
        if void_faces:
            kept = [s for s in segments
                    if tuple(sorted({n for n in s if n})) not in void_faces]
            if len(kept) < len(segments):
                if nrf.nsid not in void_named:
                    void_named.add(nrf.nsid)
                    state.warn(
                        f"*BOUNDARY_NON_REFLECTING nsid={nrf.nsid}: "
                        f"{len(segments) - len(kept)} of {len(segments)} "
                        f"segment(s) lie on faces of part(s) {void_pids}, a "
                        "*MAT_ACOUSTIC written as /MAT/VOID on this modal deck "
                        "(round 9, A7). The starter refuses an /EBCS on any "
                        "element outside the ALE / Euler framework "
                        "(iniebcs.F:428-441, ERROR 1602), and the void is "
                        "Lagrangian, so "
                        + ("the /EBCS/NRF is DROPPED." if not kept else
                           f"those segments are dropped and the /EBCS/NRF "
                           f"keeps the other {len(kept)}.")
                        + " --no-modal-acoustic-void keeps the refusal and "
                        "the full /EBCS.")
                if not kept:
                    continue
                segments = kept
        surf_id = surf_for_ssid.get(nrf.nsid)
        if surf_id is None:
            surf_id = state.next_id()
            surf_for_ssid[nrf.nsid] = surf_id
            lines += _emit_surf_seg(surf_id, segset.title or f"nrf_{nrf.nsid}",
                                    segments)
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


def _shell_in_solid_side(state: ConversionState, sid: int, styp: int) -> str:
    """One side of a *CONSTRAINED_SHELL_IN_SOLID card in words: STYP 1 = a
    *PART id, 0 (default) = a *SET_PART id; an undefined set is named."""
    if styp == 1:
        return str([sid])
    ps = state.part_sets.get(sid)
    if ps is None:
        return f"(set {sid} not defined)"
    return str(sorted(ps[1]))


#: the fraction of the solid-segment stiffness K A^2 / V the constraint form
#: of *CONSTRAINED_SHELL_IN_SOLID takes (LS-DYNA's own default coupling
#: fraction: PSSF, Vol I R17 p.10-181, and *CONSTRAINED_LAGRANGE_IN_SOLID
#: PFAC, p.10-117, both default 0.1)
_SIS_FRACTION = 0.1


def _sis_side_pids(state: ConversionState, sid: int,
                   styp: int) -> Optional[List[int]]:
    """The part ids one side of a *CONSTRAINED_SHELL_IN_SOLID card names
    (STYP 1 = a *PART id, 0 = a *SET_PART id), or None when it names
    nothing the deck defines."""
    if styp == 1:
        return [sid] if sid in state.parts else None
    ps = state.part_sets.get(sid)
    return sorted(ps[1]) if ps is not None else None


def _sis_host_modulus(state: ConversionState, pid: int
                      ) -> Tuple[float, float, str]:
    """``(K, RO, '')`` of one ALE host part, or ``(0, 0, the refusal)``: an
    ELFORM 11 / 12 solid (k2rad writes Iale 1) on a ``*MAT_NULL`` whose EOS
    is ``*EOS_GRUNEISEN`` (K = RO C^2) or ``*EOS_LINEAR_POLYNOMIAL`` (K =
    C1), the EOS found the way the materials writer binds it (the same-id
    EOS, else the *PART EOSID)."""
    part = state.parts[pid]
    sec = state.sec_solids.get(part.secid)
    if sec is None or not sec.iale:
        return 0.0, 0.0, (
            f"host part {pid} is not an ALE solid (k2rad writes it with Iale "
            "0, and an /INTER/TYPE18 couples to ALE cells)")
    mat = state.mat_null.get(part.mid)
    eos = state.eos_cards.get(part.mid)
    if eos is None and part.eosid:
        eos = state.eos_cards.get(part.eosid)
    if mat is None or eos is None:
        return 0.0, 0.0, (f"host part {pid} is not a *MAT_NULL fluid with an "
                          "*EOS_GRUNEISEN / *EOS_LINEAR_POLYNOMIAL")
    # the deck's own RO: a stated RO <= 0 was floored to 1e-24 by
    # materials._apply_zero_density_floor, which records the mid
    ro = 0.0 if part.mid in state.zero_density_floored else mat.rho
    if eos.keyword == "EOS_GRUNEISEN":
        c = eos.params.get("c", 0.0)
        if ro <= 0.0 or c <= 0.0:
            return 0.0, 0.0, (
                f"host part {pid}: RO {ro:g} / C {c:g} - the stiffness "
                "RO C^2 would not be positive (starter ERROR 1115)")
        return ro * c * c, ro, ""
    if eos.keyword == "EOS_LINEAR_POLYNOMIAL":
        c1 = eos.params.get("c1", 0.0)
        if ro <= 0.0 or c1 <= 0.0:
            return 0.0, 0.0, (
                f"host part {pid}: RO {ro:g} / C1 {c1:g} - the stiffness "
                "C1 would not be positive (starter ERROR 1115)")
        return c1, ro, ""
    return 0.0, 0.0, (f"host part {pid}: its EOS is *{eos.keyword}, not "
                      "*EOS_GRUNEISEN / *EOS_LINEAR_POLYNOMIAL (no bulk "
                      "modulus k2rad reads)")


def _sis_brick_volume(state: ConversionState, e) -> float:
    """One host brick's volume: the 6-tet split of an 8-node element (a
    degenerate hexa by its distinct nodes), the corner tet otherwise - the
    lumper's own rule (``lumping._HEXA_TETS``)."""
    from ..lumping import _HEXA_TETS, _tet_volume
    try:
        p = [(state.nodes[n].x, state.nodes[n].y, state.nodes[n].z)
             for n in e.nodes]
    except KeyError:
        return 0.0
    if len(p) >= 8:
        return math.fsum(_tet_volume(p[a], p[b], p[c], p[d])
                         for a, b, c, d in _HEXA_TETS)
    if len(p) >= 4:
        return _tet_volume(p[0], p[1], p[2], p[3])
    return 0.0


def _sis_shell_area(state: ConversionState, e) -> float:
    """One shell segment's area: a quad 0.5 |d13 x d24|, a triangle (three
    distinct corners) 0.5 |e12 x e13|."""
    ids = [n for n in e.nodes if n > 0]
    distinct = list(dict.fromkeys(ids))
    try:
        p = [(state.nodes[n].x, state.nodes[n].y, state.nodes[n].z)
             for n in distinct]
    except KeyError:
        return 0.0

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0])

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
    if len(p) >= 4:
        c = cross(sub(p[2], p[0]), sub(p[3], p[1]))
    elif len(p) == 3:
        c = cross(sub(p[1], p[0]), sub(p[2], p[0]))
    else:
        return 0.0
    return 0.5 * math.sqrt(c[0] * c[0] + c[1] * c[1] + c[2] * c[2])


def _sis_refusal(state: ConversionState, card) -> Tuple[str, Optional[Dict]]:
    """``('', the measured cells)`` for a card ``--shell-in-solid-coupling``
    converts, or ``(the refusal in words, None)``. Draws no id."""
    if card.start < 0.0:
        return ("START < 0 (the coupling is followed during dynamic "
                "relaxation; k2rad converts no dynamic-relaxation phase)",
                None)
    if card.end == -9999.0:
        return ("END -9999 (START names a curve / table: not converted)",
                None)
    if card.end < 0.0:
        return ("END < 0 (a dynamic-relaxation statement; k2rad converts no "
                "dynamic-relaxation phase)", None)
    shell_side = _sis_side_pids(state, card.shsid, card.shstyp)
    host_side = _sis_side_pids(state, card.ssid, card.sstyp)
    if shell_side is None:
        return (f"SHSID {card.shsid} is not a defined "
                + ("*PART" if card.shstyp == 1 else "*SET_PART"), None)
    if host_side is None:
        return (f"SSID {card.ssid} is not a defined "
                + ("*PART" if card.sstyp == 1 else "*SET_PART"), None)
    shell_parts = {e.pid for e in state.shell_elems}
    shell_pids = [p for p in shell_side if p in shell_parts]
    if not shell_pids:
        return (f"SHSID {card.shsid} names no part with shell elements "
                f"({shell_side})", None)
    hosts = [p for p in host_side if p in state.parts]
    if not hosts:
        return f"SSID {card.ssid} names no defined part ({host_side})", None
    k_by: Dict[int, float] = {}
    ro_by: Dict[int, float] = {}
    for pid in hosts:
        k, ro, why = _sis_host_modulus(state, pid)
        if why:
            return why, None
        k_by[pid], ro_by[pid] = k, ro
    vols: Dict[int, List[float]] = {p: [] for p in hosts}
    for e in state.solid_elems:
        if e.pid in vols:
            vols[e.pid].append(_sis_brick_volume(state, e))
    all_vols = [v for p in hosts for v in vols[p]]
    if not all_vols or math.fsum(all_vols) <= 0.0:
        return (f"SSID {card.ssid}: the host part(s) {hosts} carry no solid "
                "element", None)
    areas = [_sis_shell_area(state, e) for e in state.shell_elems
             if e.pid in set(shell_pids)]
    a_seg = math.fsum(areas) / len(areas)
    v_host = math.fsum(all_vols) / len(all_vols)
    # several host parts: the volume-weighted mean bulk modulus
    w = {p: math.fsum(vols[p]) for p in hosts}
    k_host = math.fsum(k_by[p] * w[p] for p in hosts) / math.fsum(w.values())
    edge = _mean_brick_edge(state, set(hosts))
    if a_seg <= 0.0 or edge <= 0.0:
        return (f"the shell segments of {shell_pids} or the host bricks of "
                f"{hosts} have no size", None)
    fraction = card.pssf if card.penalty else _SIS_FRACTION
    return "", {
        "shell_pids": shell_pids, "host_pids": hosts, "fraction": fraction,
        "k_host": k_host, "a_seg": a_seg, "v_host": v_host,
        "stfval": fraction * k_host * a_seg * a_seg / v_host,
        # round 9, B4: the round-8 factor; the end-of-starter re-tune
        # (finalize_shell_in_solid) writes 0.55 x edge on an SIS-alone deck
        "gap": 0.5 * edge, "edge": edge, "ro": ro_by,
        "tstart": card.start,
        "tstop": card.end if 0.0 < card.end < 1.0e20 else 0.0}


def _resolve_shell_in_solid(state: ConversionState) -> List[ShellInSolidPlan]:
    """The ONE decision of ``--shell-in-solid-coupling`` (R14 triage round 8,
    B10), memoised on ``state.shell_in_solid_plan``; a ``build_starter``
    prepass, BEFORE the materials and the parts are written (both read its
    void density). Draws no id except a COPY MID for a void host whose
    ``*MAT_NULL`` another part shares. Empty under the default, so a
    default deck is byte-identical to 4f5b6e8.

    The void density is written ONLY on an ``*INITIAL_VOID`` host of a
    converted card - never on a ``*CONSTRAINED_LAGRANGE_IN_SOLID`` host,
    where the same cell was measured to fail (round 8: bird_B stalls on the
    TYPE18 sort step at t 2.227e-4, quadrature_B reaches 3.6 % of its run in
    600 s): ``RHO_I = VFACT x RO`` (``*CONTROL_ALE`` VFACT, default 1e-6) with
    the ``/EOS`` ``RHO_0`` cell stated as RO (without it the reference
    density IS RHO_I, ``hm_read_mat06.F:155-157``; a positive EOS RHO_0
    overrides it, ``hm_read_eos_gruneisen.F:117-123``)."""
    if state.shell_in_solid_plan is not None:
        return state.shell_in_solid_plan
    plans: List[ShellInSolidPlan] = []
    state.shell_in_solid_plan = plans
    if not state.options.shell_in_solid_coupling:
        return plans
    void_pids: Set[int] = set()
    for sid, is_set in state.initial_void_parts:
        if is_set:
            ps = state.part_sets.get(sid)
            if ps is not None:
                void_pids.update(ps[1])
        else:
            void_pids.add(sid)
    vfact = (state.control_ale.vfact if state.control_ale is not None
             else 1.0e-6)
    # round 9, B4 (step 1): a DT2MS < 0 deck's mass-scaling engine card
    # refuses every card the round-8 screen accepts - before any id is drawn
    dt2ms_card = _sis_dt2ms_card(state)
    for card in state.shell_in_solid_cards:
        why, cells = _sis_refusal(state, card)
        if cells is not None and dt2ms_card:
            why, cells = _sis_dt2ms_refusal(state, dt2ms_card), None
        if cells is None:
            state.warn(
                f"*CONSTRAINED_SHELL_IN_SOLID {card.coupid or '(no id)'}: not "
                f"converted under --shell-in-solid-coupling - {why}; it stays "
                "listed as skipped.")
            continue
        plans.append(ShellInSolidPlan(
            card=card, shell_pids=cells["shell_pids"],
            host_pids=cells["host_pids"], fraction=cells["fraction"],
            k_host=cells["k_host"], a_seg=cells["a_seg"],
            v_host=cells["v_host"], stfval=cells["stfval"],
            gap=cells["gap"], tstart=cells["tstart"], tstop=cells["tstop"],
            void_parts=[p for p in cells["host_pids"] if p in void_pids],
            edge=cells["edge"]))
    # the void density: one cell pair per *MAT_NULL id, a copy MID when a
    # part outside the void hosts shares it
    dense = {p for plan in plans for p in plan.void_parts}
    for pid in sorted(dense):
        mid = state.parts[pid].mid
        ro = state.mat_null[mid].rho
        cells_pair = (vfact * ro, ro)
        sharers = {q for q, part in state.parts.items()
                   if part.mid == mid and q not in dense}
        if sharers:
            copy = next((c for c, m in state.sis_copy_mids.items()
                         if m == mid), 0)
            if not copy:
                copy = state.next_mat_id()
                state.sis_copy_mids[copy] = mid
                state.sis_density[copy] = cells_pair
            state.sis_part_mids[pid] = copy
        else:
            state.sis_density[mid] = cells_pair
    return plans


def _make_shell_in_solid_coupling(state: ConversionState) -> List[str]:
    """The ``/INTER/TYPE18`` of every card ``--shell-in-solid-coupling``
    converted (R14 triage round 8, B10): ``/SURF/PART/EXT`` over the shell
    parts, ``/GRBRIC/PART`` over the ALE host parts, line 1 written exactly
    as ``_make_fsi_coupling`` writes it (Igap 0, Ipres 0, Idel 0, Iauto
    blank = ISTIFF 1, a constant Stfval, ``hm_read_inter_type18.F:158``),
    ``Stfval = F x K A^2 / V``, Vref 0, Gap = half the mean host edge (the
    CLIS rule), Tstart = START, Tstop = END when 0 < END < 1e20, else 0 (the
    starter's 1e30, ``:250``). Every id is drawn here, after the last
    refusal screen; the keyword leaves ``skipped_keywords`` at the line that
    writes the card. Round 9 (B4): the card's sentence and the Gap factor
    are decided at the end of the starter (``finalize_shell_in_solid``),
    once every interface is written."""
    plans = _resolve_shell_in_solid(state)
    if not plans:
        return []
    lines: List[str] = []
    for k, plan in enumerate(plans):
        card = plan.card
        tag = str(card.coupid) if card.coupid else str(k + 1)
        surf_id = state.next_id()
        lines += _emit_surf_part(surf_id, f"shell_in_solid_{tag}_shells",
                                 plan.shell_pids)
        grbric_id = state.next_elem_group_id()
        lines += _emit_grbric_part(grbric_id, f"shell_in_solid_{tag}_host",
                                   plan.host_pids)
        inter_id = state.next_id()
        lines += [
            f"/INTER/TYPE18/{inter_id}",
            f"shell_in_solid_{tag}",
            "#            surf_ID grbric_id                Igap               Ipres      Idel",
            (" " * 10 + _i(surf_id) + _i(grbric_id) + " " * 10 + _i(0)
             + " " * 10 + _i(0) + _i(0)),
            "#             Stfval                Vref                 Gap              Tstart               Tstop",
            _f(plan.stfval) + _f(0.0) + _f(plan.gap) + _f(plan.tstart)
            + _f(plan.tstop),
            HDR,
        ]
        plan.inter_id = inter_id
        state.skipped_keywords.remove(card.keyword)
    return lines


#: round 9, B4: the re-tuned opt-in's Gap factor (cG1 G1-7: the mid-cell
#: plate is coupled at 0.55 x the host edge, J1 1.856 P0) - written only with
#: /DT/INTER/CST, never alone (any factor > 0.5 couples a void plane)
_SIS_RETUNE_GAP = 0.55

#: the measured re-tuned opt-in on the one carrier (round 9, B4; cG1 eRule,
#: nt 4, the campaign rule; the plate by /TH/PART against LS-DYNA's matsum)
_SIS_MEASURED = (
    "MEASURED on intro-by-j.-day/misc/bird-ale/bird-el.k (nt 4, the 500 LS "
    "times to t 2.5e-3): the plate's internal energy -100 % -> -29.06 % "
    "against LS-DYNA (RMS 83.22 -> 24.97 %), the deck END IE +1134.62 -> "
    "+39.41 % and KE -92.06 -> -42.96 % (RMS 1102.65 / 162.68 -> 28.42 / "
    "4.66 % of the LS peak), at 1.140x the cycles, mass added 1.815e-7 t on "
    "50 void ALE nodes and none on the plate - but OpenRadioss's energy "
    "error grows from -32.6 to -35.0 % at t_end (not explained). The void "
    "density FAILS on a *CONSTRAINED_LAGRANGE_IN_SOLID void host (bird_B "
    "stalls on the TYPE18 sort step at t 2.227e-4; quadrature_B reaches "
    "3.6 % of its run in 600 s), so it is written only on an *INITIAL_VOID "
    "host of this card. Evidence base: one carrier on five corpora.")

#: the round-8 form's own limits (a deck that is not SIS-alone keeps it)
_SIS_ROUND8_LIMITS = (
    "The void density FAILS on a *CONSTRAINED_LAGRANGE_IN_SOLID void host "
    "(bird_B stalls on the TYPE18 sort step at t 2.227e-4; quadrature_B "
    "reaches 3.6 % of its run in 600 s), so it is written only on an "
    "*INITIAL_VOID host of this card. At Gap 0.5 x the host edge a shell "
    "plate exactly at mid-cell has both neighbouring host node planes at "
    "distance = Gap and is never coupled (the solver-physics validator's "
    "coupon: 0 plate impulse), and a coupled host node that is still void "
    "sets the interface step.")


def _sis_dt2ms_card(state: ConversionState) -> str:
    """The mass-scaling engine card a DT2MS < 0 explicit deck gets
    (``/DT/NODA/CST/0``, or ``/DT/AMS`` under ``--ams``) - round 9, B4's
    refusal key; '' when the engine deck carries neither."""
    ts = state.ctrl_timestep
    if ts is None or ts.dt2ms >= 0.0 or state.is_implicit or state.is_modal:
        return ""
    return "/DT/AMS" if _ams_is_emitted(state) else "/DT/NODA/CST/0"


def _sis_dt2ms_refusal(state: ConversionState, card_name: str) -> str:
    """Round 9, B4 (d): why a DT2MS < 0 deck keeps the card skipped."""
    ts = state.ctrl_timestep
    dt2ms = ts.dt2ms if ts is not None else 0.0
    ams = (" (--ams; the same refusal as /DT/NODA/CST/0)"
           if card_name == "/DT/AMS" else "")
    return (f"DT2MS {dt2ms:g} < 0 makes k2rad write {card_name}{ams}, and "
            "with the TYPE18 coupling that blows up at once (bird-el with the "
            "coupling + /DT/NODA/CST/0 0.5 1e-7, nt 4: KE 1.406e6 -> 5.635e6 "
            "in ONE cycle, MESSAGE 167 NEGATIVE RHO on brick 410, no "
            "termination line; /DT/NODA excludes ALE nodes, "
            "dtnoda.F:124-131)")


def _sis_shell_speed(state: ConversionState, mid: int) -> float:
    """``sqrt(E / (RO (1 - nu^2)))`` of an embedded shell's material (the
    plane-stress wave speed), 0.0 when its family states no E / nu / RO
    k2rad reads (*MAT_ELASTIC, the piecewise / kinematic / power-law
    plasticity cards, *MAT_JOHNSON_COOK)."""
    for fam in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                state.mat_power_law, state.mat_johnson_cook):
        rec = fam.get(mid)
        if rec is None:
            continue
        rho = float(getattr(rec, "rho", 0.0) or 0.0)
        e = getattr(rec, "E", None)
        if e is None:
            e = getattr(rec, "e", 0.0)
        nu = getattr(rec, "nu", None)
        if rho > 0.0 and e and float(e) > 0.0 and nu is not None \
                and -1.0 < float(nu) < 1.0:
            return math.sqrt(float(e) / (rho * (1.0 - float(nu) ** 2)))
        return 0.0
    return 0.0


def _sis_shell_shortest_edge(state: ConversionState, e) -> float:
    """The shortest edge of one shell element (its distinct corners in
    order, the closing edge included)."""
    ids = [n for n in e.nodes if n > 0]
    ring = list(dict.fromkeys(ids))
    if len(ring) < 3:
        return 0.0
    best = 0.0
    for a, b in zip(ring, ring[1:] + ring[:1]):
        na, nb = state.nodes.get(a), state.nodes.get(b)
        if na is None or nb is None:
            continue
        d = math.sqrt((na.x - nb.x) ** 2 + (na.y - nb.y) ** 2
                      + (na.z - nb.z) ** 2)
        if d > 0.0 and (best == 0.0 or d < best):
            best = d
    return best


def _sis_dt_inter_cells(state: ConversionState,
                        plans: List[ShellInSolidPlan]
                        ) -> Tuple[float, float, str]:
    """``(Tsca, Tmin, '')`` of the re-tune's ``/DT/INTER/CST``, or ``(Tsca,
    0, why)``: Tsca = TSSFAC if > 0 else 0.9 (the ``/DT`` writer's rule);
    ``Tmin = 0.5 x Tsca x min(mean host edge / c_host, shortest SIS shell
    edge / c_shell)`` over every converted card - c_host = sqrt(K / RO) with
    the K the Stfval uses (``_sis_host_modulus``), c_shell the shell's
    plane-stress wave speed."""
    ts = state.ctrl_timestep
    tsca = ts.tssfac if ts is not None and ts.tssfac and ts.tssfac > 0.0 \
        else 0.9
    cands: List[float] = []
    for p in plans:
        for pid in p.host_pids:
            k, ro, why = _sis_host_modulus(state, pid)
            if not why and k > 0.0 and ro > 0.0 and p.edge > 0.0:
                cands.append(p.edge / math.sqrt(k / ro))
    shells = {pid for p in plans for pid in p.shell_pids}
    speed: Dict[int, float] = {}
    missing: Set[int] = set()
    for e in state.shell_elems:
        if e.pid not in shells:
            continue
        mid = state.parts[e.pid].mid
        if mid not in speed:
            speed[mid] = _sis_shell_speed(state, mid)
        if speed[mid] <= 0.0:
            missing.add(mid)
            continue
        le = _sis_shell_shortest_edge(state, e)
        if le > 0.0:
            cands.append(le / speed[mid])
    if missing:
        return tsca, 0.0, (f"embedded-shell material(s) {sorted(missing)} "
                           "without an E / nu / RO k2rad reads")
    if not cands:
        return tsca, 0.0, "no host or shell size to set Tmin"
    return tsca, 0.5 * tsca * min(cands), ""


def _sis_other_interfaces(lines: List[str], sis_ids: Set[int]) -> List[str]:
    """The kind of every emitted ``/INTER/<kind>/<id>`` card but the SIS
    TYPE18s - the screen reads what the starter WRITES (a refused contact
    emits nothing and does not count)."""
    kinds: List[str] = []
    for ln in lines:
        if not ln.startswith("/INTER/"):
            continue
        head, _sep, tail = ln.strip().rpartition("/")
        if not tail.isdigit():
            continue
        kind = head[len("/INTER/"):]
        if kind == "TYPE18" and int(tail) in sis_ids:
            continue
        kinds.append(kind)
    return kinds


def _sis_lagrangian_parts(state: ConversionState,
                          plans: List[ShellInSolidPlan]) -> List[int]:
    """Every part with an element that is neither on an ALE part (Iale >= 1)
    nor on a shell part of a converted card's SHSID side."""
    ale = set(_ale_part_ids(state))
    shells = {pid for p in plans for pid in p.shell_pids}
    lag: Set[int] = set()
    for cont in (state.solid_elems, state.shell_elems, state.tshell_elems,
                 state.beam_elems, state.sph_elems, state.discrete_elems,
                 state.seatbelt_elems):
        for e in cont:
            pid = getattr(e, "pid", None)
            if pid is None or pid in ale or pid in shells:
                continue
            lag.add(int(pid))
    return sorted(lag)


def _sis_patch_gap(lines: List[str], plan: ShellInSolidPlan) -> None:
    """Rewrite the Gap cell of the plan's emitted ``/INTER/TYPE18`` line 2
    (content-asserted: the header and the line-1 / line-2 layout are the
    ones ``_make_shell_in_solid_coupling`` wrote)."""
    i = lines.index(f"/INTER/TYPE18/{plan.inter_id}")
    data = [j for j in range(i + 2, min(i + 7, len(lines)))
            if not lines[j].startswith("#")]
    j = data[1]
    old = (_f(plan.stfval) + _f(0.0) + _f(0.5 * plan.edge) + _f(plan.tstart)
           + _f(plan.tstop))
    assert lines[j] == old, (lines[j], old)
    lines[j] = (_f(plan.stfval) + _f(0.0) + _f(plan.gap) + _f(plan.tstart)
                + _f(plan.tstop))


def finalize_shell_in_solid(state: ConversionState,
                            lines: List[str]) -> List[str]:
    """Round 9, B4: the ``--shell-in-solid-coupling`` re-tune, decided once
    the WHOLE starter is written (``build_starter``'s post-pass; a no-op
    without a converted card). On a deck that is the SIS problem alone -
    every element on an ALE part or on an SHSID shell part, no emitted
    ``/INTER`` but the SIS TYPE18s, an explicit engine deck and a shell
    wave speed for Tmin - each card's Gap becomes 0.55 x the mean host edge
    and the engine deck gets ONE ``/DT/INTER/CST Tsca Tmin``
    (``state.sis_dt_inter_cst``). Any other deck keeps the round-8 form
    (Gap 0.5 x, no card) and is told why: ``/DT/INTER/CST`` is global
    (``dtnoda.F:661-722``, every node tagged at ``:111-122``), and the
    round-9 gate measured it adding mass to a TYPE7 pair's nodes beside the
    SIS in every arm. Writes every card's sentence."""
    plans = state.shell_in_solid_plan or []
    if not plans:
        return lines
    whats: List[str] = []
    lag = _sis_lagrangian_parts(state, plans)
    if lag:
        whats.append(f"Lagrangian part(s) {lag}")
    others = _sis_other_interfaces(lines, {p.inter_id for p in plans})
    if others:
        whats.append(f"{len(others)} other interface(s) "
                     f"({', '.join(sorted(set(others)))})")
    if state.is_implicit or state.is_modal:
        whats.append("an implicit / modal solution (its engine deck has no "
                     "/DT card)")
    tsca, tmin, why = _sis_dt_inter_cells(state, plans)
    if why:
        whats.append(why)
    retune = not whats
    if retune:
        for p in plans:
            p.gap = _SIS_RETUNE_GAP * p.edge
            _sis_patch_gap(lines, p)
        state.sis_dt_inter_cst = (tsca, tmin)
    for k, plan in enumerate(plans):
        card = plan.card
        pssf = (f"; _PENALTY PSSF {plan.fraction:g}" if card.penalty else "")
        dens = []
        for pid in plan.void_parts:
            mid = state.sis_part_mids.get(pid, state.parts[pid].mid)
            rho_i, rho0 = state.sis_density[mid]
            copy = (f", a copy of *MAT_NULL {state.sis_copy_mids[mid]} that "
                    f"part {pid} now points at (the material is shared)"
                    if mid in state.sis_copy_mids else "")
            dens.append(
                f" The *INITIAL_VOID host part {pid} gets the void density: "
                f"/MAT/HYD_VISC/{mid} RHO_I {rho_i:g} (VFACT x RO) with its "
                f"/EOS RHO_0 cell {rho0:g} (the deck density){copy}.")
        if retune:
            tail = (
                f" The engine deck also gets /DT/INTER/CST {tsca:g} "
                f"{tmin:.6g} (Tmin = 0.5 x Tsca x min(mean host edge / "
                "c_host, shortest SIS shell edge / c_shell)): a coupled host "
                "node that is still void has a nodal step of about "
                "sqrt(VFACT) of a full node's (9.317e-9 s on bird-el), and "
                "the card adds 0.5 x STIFN x (Tmin / Tsca)^2 to every node of "
                "the deck below Tmin - on this deck only ALE nodes and the "
                "SIS shells can be there (the deck has no other Lagrangian "
                "part and no other interface; that is the condition for this "
                "card). " + _SIS_MEASURED)
            gap_clause = f"Gap {plan.gap:g} = 0.55 x the mean host edge."
        else:
            tail = " " + _SIS_ROUND8_LIMITS
            gap_clause = (f"Gap {plan.gap:g} = 0.5 x the mean host edge (the "
                          "round-8 form - see the next sentence).")
        state.warn(
            f"*CONSTRAINED_SHELL_IN_SOLID {card.coupid or '(no id)'} -> "
            f"/INTER/TYPE18/{plan.inter_id} (--shell-in-solid-coupling): "
            f"shell part(s) {plan.shell_pids} coupled to ALE host part(s) "
            f"{plan.host_pids} by a penalty interface - OpenRadioss has no "
            "embedded-shell constraint and TYPE18 is penalty-only, so the "
            f"stiffness is a stated choice: Stfval = {plan.fraction:g} x K "
            f"{plan.k_host:g} x A^2 {plan.a_seg:g}^2 / V {plan.v_host:g} = "
            f"{plan.stfval:g} (LS-DYNA's own default coupling fraction 0.1 of "
            f"the solid-segment stiffness K A^2 / V{pssf}), " + gap_clause
            + "".join(dens) + tail)
    if not retune:
        state.warn(
            "*CONSTRAINED_SHELL_IN_SOLID (--shell-in-solid-coupling): this "
            f"deck carries {' and '.join(whats)} beside the embedded shells, "
            "so the coupling is written in its round-8 form (Gap 0.5 x the "
            "mean host edge, no /DT/INTER/CST): the CST card is global and, "
            "on a water-hammer SIS coupon with a TYPE7 block pair beside it, "
            "added mass to the blocks' nodes in every arm (0.5 mm bricks x "
            "21.4; 2 mm bricks +15 % on the contact nodes) and killed the run "
            "at contact when the step sat below Tmin. Expect the void node to "
            "set the step (bird-el's round-8 form: 8.939x the cycles).")
    return lines


def sis_dt_inter_lines(state: ConversionState) -> List[str]:
    """The re-tune's ``/DT/INTER/CST`` engine block (round 9, B4), written
    by ``assembly._make_engine_timestep`` right after the ``/DT`` block (or
    alone when the deck states no TSSFAC); ``[]`` by default. The engine
    reads it free-format (``freform.F``: ``KEY2 'INTER'`` + ``KEY3 'CST'``
    -> the NODA slot, ``:1057-1059`` / ``:1131-1143``)."""
    cst = state.sis_dt_inter_cst
    if cst is None:
        return []
    return ["/DT/INTER/CST", "#              Tscale                Tmin",
            _f(cst[0]) + _f(cst[1]), "#"]


def sis_dt_inter_guard(state: ConversionState,
                       lines: List[str]) -> List[str]:
    """Round 9, B4 (step 3): if the engine deck already holds another
    ``/DT/INTER`` card (no k2rad writer emits one today), the re-tune's CST
    block is left out and named - a second ``/DT/INTER`` card would compete
    for the same NODA slot. A no-op without the re-tune."""
    if state.sis_dt_inter_cst is None:
        return lines
    ours = sis_dt_inter_lines(state)
    starts = [i for i, ln in enumerate(lines) if ln.startswith("/DT/INTER")]
    mine = [i for i in starts if lines[i:i + len(ours)] == ours]
    if not mine or len(starts) == len(mine):
        return lines
    i = mine[0]
    state.warn(
        "*CONSTRAINED_SHELL_IN_SOLID (--shell-in-solid-coupling): the engine "
        "deck already holds another /DT/INTER card, so /DT/INTER/CST "
        f"{state.sis_dt_inter_cst[0]:g} {state.sis_dt_inter_cst[1]:.6g} is "
        "NOT added - the starter's TYPE18 Gap 0.55 x the host edge then "
        "stands without it; remove the other card or convert without "
        "--shell-in-solid-coupling.")
    return lines[:i] + lines[i + len(ours):]


def _make_shell_in_solid_notes(state: ConversionState) -> List[str]:
    """``*CONSTRAINED_SHELL_IN_SOLID[_PENALTY]`` → ONE named warning per deck
    over the cards NOT converted (R14 triage round 7, B5; 0 bytes, draws no
    id; round 8, B10: a card ``--shell-in-solid-coupling`` converts is named
    by its own sentence instead).

    The card is recorded by ``handlers.handle_constrained_shell_in_solid`` and
    stays in ``skipped_keywords`` (its ``#-- SKIPPED:`` line is part of the
    ``.rad``). OpenRadioss has no embedded-shell constraint, so the embedded
    shells receive nothing from the solids they sit in. The measured arms are
    round 8's on ``bird-el`` (nt 4, the campaign rule): the shipped deck 2492
    cycles; the opt-in's ``/INTER/TYPE18`` (Stfval = 0.1 K A^2 / V) with the
    void density 22269 (8.936x). Round 9 (B4) re-tuned the opt-in (Gap 0.55
    x the host edge + ``/DT/INTER/CST``: 2839 cycles, 1.140x) and
    measured why it stays opt-in (the gate: the CST card is global)."""
    converted = {id(p.card) for p in (state.shell_in_solid_plan or [])}
    cards = [c for c in state.shell_in_solid_cards if id(c) not in converted]
    if not cards:
        return []
    per_card = "; ".join(
        f"{c.coupid or '(no id)'} - shell part(s) "
        f"{_shell_in_solid_side(state, c.shsid, c.shstyp)} in solid part(s) "
        f"{_shell_in_solid_side(state, c.ssid, c.sstyp)}"
        + (" (_PENALTY)" if c.penalty else "")
        for c in cards)
    state.warn(
        f"*CONSTRAINED_SHELL_IN_SOLID: {len(cards)} card(s) ({per_card}) are "
        "NOT converted and stay listed as skipped: OpenRadioss has no "
        "embedded-shell constraint (no radioss2022-2026 CFG card; dyna2rad "
        "does not convert it either), so those shells receive nothing from "
        "the solids they sit in, where LS-DYNA constrains them to move with "
        "them (Vol I R17 p.10-179). MEASURED on bird-el (nt 4, against "
        "LS-DYNA, the round-6 floored void deck): the plate's internal energy "
        "is 0 against LS-DYNA's 4.9377e5 (-100 %), and the deck ends IE "
        "+1134.62 % / KE -92.06 % (RMS 1102.65 / 162.68 % of the LS-DYNA "
        "peak) - mostly from the void, which is converted as full-density "
        "fluid (its part carries KE 1.125e7 at cycle 0, LS-DYNA's 10.2). "
        "--shell-in-solid-coupling (opt-in) writes the card as an "
        "/INTER/TYPE18 with Stfval = 0.1 K A^2 / V (2812.5 on this deck), "
        "Gap 0.55 x the mean host edge, the void density on the "
        "*INITIAL_VOID host and the engine card /DT/INTER/CST: the plate "
        "-29.06 % (RMS 24.97 %), the deck IE +39.41 / KE -42.96 % (RMS "
        "28.42 / 4.66 %) at 1.140x the cycles, with OpenRadioss's energy "
        "error -32.6 -> -35.0 %. It is not the default because "
        "/DT/INTER/CST is GLOBAL to the engine deck: it adds mass to every "
        "node whose nodal step falls below Tmin (dtnoda.F:661-722, every "
        "node tagged, :111-122). MEASURED on a water-hammer SIS coupon with "
        "a TYPE7 block pair beside it (nt 4): the blocks' nodes gained mass "
        "in every arm with the card (0.5 mm bricks: all 1458 nodes x 21.4, "
        "the model 1.0562e-6 -> 6.1894e-6 t; 2 mm bricks: the 16 contact "
        "nodes +15 %), and with the step held below Tmin the contact nodes' "
        "mass ran away and killed the run at contact (MESSAGE 205 + 207); "
        "the opt-in therefore writes the card only on a deck with no other "
        "Lagrangian part and no other interface, and the density half fails "
        "on both *CONSTRAINED_LAGRANGE_IN_SOLID void hosts (bird_B stalls at "
        "t 2.227e-4; quadrature_B reaches 3.6 % of its run in 600 s).")
    return []


def _make_control_ale_notes(state: ConversionState) -> List[str]:
    """*CONTROL_ALE → an informational note (advection defaults are kept)."""
    if state.control_ale is None:
        return []
    meth = state.control_ale.meth
    hint = ("Van-Leer/HIS second-order advection -> add /ALE/MUSCL"
            if meth in (2, 3) else "donor-cell advection → OpenRadioss default (upwind)")
    # the post-review round (F1): under an ACCEPTED --ale-flow-tracking plan
    # (resolved earlier, by _make_analysis_defaults) the GROUP card IS
    # converted - only then is the generic clause qualified, so no default
    # carrier of this note moves (it fires on 6 match rows)
    ft = state.ale_flow_tracking_plan
    smoothing = ("Mesh smoothing (*ALE_SMOOTHING / *ALE_REFERENCE_SYSTEM_*) "
                 "has no /ALE 1:1 and is not converted.")
    if ft is not None and ft.card is not None:
        smoothing = (
            "Mesh smoothing (*ALE_SMOOTHING) has no /ALE 1:1 and is not "
            f"converted; the *ALE_REFERENCE_SYSTEM_GROUP {ft.card.sid} card IS "
            "converted under --ale-flow-tracking (/ALE/GRID/FLOW-TRACKING, its "
            "own sentence).")
    state.warn(
        f"*CONTROL_ALE (METH={meth}): OpenRadioss keeps its default ALE advection "
        f"(stable in the reference FSI example); {hint} if you need to reproduce "
        "the exact scheme. " + smoothing)
    return []


# --- round 9, B8: *ALE_REFERENCE_SYSTEM_GROUP PRTYPE 4 -> ---------------------
#     /ALE/GRID/FLOW-TRACKING, OPT-IN (--ale-flow-tracking)

#: a *NODE TC / BCTRAN / BCROT code -> the directions it constrains
_AFT_DIRS = {0: "", 1: "x", 2: "y", 3: "z", 4: "xy", 5: "yz", 6: "zx",
             7: "xyz"}

#: the bird_B measurement every B8 sentence carries (cG1 bB / bFT, nt 4)
_AFT_MEASURED = (
    "MEASURED on ale/bird/bird-b/bird_B (nt 4, 600 LS times to t "
    "5.9992e-4): END IE +1484.66 -> +17.00 %, IE RMS 1189.95 -> 27.74 %, the "
    "energy error's worst -20.4 -> -8.7 %, and the plate takes load for the "
    "first time - but too much (IE / KE +513.69 / +130.43 % at t 5.9916e-4) "
    "- while the deck KE gets WORSE (END +25.88 -> +1542.16 %, RMS 253.09 -> "
    "749.89 %; plate KE RMS 71.60 -> 93.93 %): the void is still converted "
    "at full density (cycle-0 KE 101.5 against LS-DYNA's 11.737), so the "
    "grid motion carries 9x the bird's mass.")


def _ale_part_ids(state: ConversionState) -> List[int]:
    """Every part k2rad converts with Iale >= 1: a part with solid elements
    on an ELFORM 11 / 12 ``*SECTION_SOLID`` (``handlers`` sets ``iale``)."""
    pids: Set[int] = set()
    for e in state.solid_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        sec = state.sec_solids.get(part.secid)
        if sec is not None and sec.iale:
            pids.add(e.pid)
    return sorted(pids)


def _ale_nodes_unheld(state: ConversionState, pids: List[int],
                      dirs: str) -> str:
    """The directions of *dirs* that NOT every node of the ALE parts *pids*
    holds by a global ``/BCS`` k2rad writes from the deck's own cards: the
    ``*NODE`` TC cells (unless ``--no-node-tc-rc-bcs``), the
    ``*CONSTRAINED_GLOBAL`` cells and the ``*BOUNDARY_SPC`` / zero-hold
    prescribed-motion rows (``loads._global_spc_dofs``, skewed cards
    excluded)."""
    from .loads import _TC_RC_DIGITS, _global_spc_dofs
    pset = set(pids)
    nodes: Set[int] = set()
    for e in state.solid_elems:
        if e.pid in pset:
            nodes.update(n for n in e.nodes if n > 0)
    node_cells = (state.node_tc_rc if state.options.node_tc_rc_bcs else {})
    glob_cells = state.constrained_global_tc_rc
    spc = _global_spc_dofs(state)
    missing = ""
    for k, d in enumerate("xyz"):
        if d not in dirs:
            continue
        for nid in nodes:
            if _TC_RC_DIGITS.get(node_cells.get(nid, (0, 0))[0],
                                 "000")[k] == "1":
                continue
            if _TC_RC_DIGITS.get(glob_cells.get(nid, (0, 0))[0],
                                 "000")[k] == "1":
                continue
            if spc.get(nid, ("000", "000"))[0][k] == "1":
                continue
            missing += d
            break
    return missing


def _resolve_ale_flow_tracking(state: ConversionState) -> AleFlowTrackingPlan:
    """The ONE decision of ``--ale-flow-tracking`` (round 9, B8), memoised on
    the state. A card is accepted only when ALL hold: exactly one
    ``*ALE_REFERENCE_SYSTEM_GROUP`` and no ``_NODE`` / ``_CURVE`` /
    ``_SWITCH`` card (one grid formulation per deck, ``hm_read_ale_grid.F``
    ERROR 1118 on a second card); PRTYPE 4, PRID 0 (FLOW-TRACKING averages
    over every ALE node), ICR 0 (it turns about the centre of mass); BCEXP 7
    -> IS_DEF -1 (its deformation term is all-or-nothing); BCROT 0 / 7 ->
    IS_ROT +1 / -1; STYPE 0 / 1 naming every part k2rad converts with Iale >=
    1 (one VMEAN moves every ALE node, ``alew7.F:186-227``); and every
    direction BCTRAN constrains already held on every ALE node by a global
    ``/BCS`` (FLOW-TRACKING has no translation constraint). Otherwise
    ``reasons`` lists every failing class and nothing is written. Without the
    flag (or without a reference-system card) the plan is empty."""
    if state.ale_flow_tracking_plan is not None:
        return state.ale_flow_tracking_plan
    plan = AleFlowTrackingPlan()
    state.ale_flow_tracking_plan = plan
    groups = state.ale_reference_groups
    if not state.options.ale_flow_tracking or not (
            groups or state.ale_reference_others):
        return plan
    reasons: List[str] = []
    for kw in sorted(set(state.ale_reference_others)):
        reasons.append(f"*{kw} has no OpenRadioss analogue")
    if len(groups) > 1:
        reasons.append(f"{len(groups)} *ALE_REFERENCE_SYSTEM_GROUP cards: "
                       "FLOW-TRACKING is one grid formulation for the deck")
    if len(groups) == 1:
        g = groups[0]
        if g.prtype != 4:
            reasons.append(f"PRTYPE {g.prtype}: only PRTYPE 4 has an "
                           "OpenRadioss analogue (FLOW-TRACKING)")
        if g.prid != 0:
            reasons.append(f"PRID {g.prid}: FLOW-TRACKING averages over every "
                           "ALE node")
        if g.icr != 0:
            reasons.append(f"ICR {g.icr}: FLOW-TRACKING turns about the centre "
                           "of mass")
        if g.bcexp != 7:
            reasons.append(f"BCEXP {g.bcexp}: FLOW-TRACKING's deformation term "
                           "is all-or-nothing (only BCEXP 7 = no expansion "
                           "maps)")
        if g.bcrot not in (0, 7):
            reasons.append(f"BCROT {g.bcrot}: only BCROT 0 / 7 map to I_rot "
                           "+1 / -1")
        ale = _ale_part_ids(state)
        if not ale:
            reasons.append("the deck converts no ALE part (Iale >= 1)")
        if g.stype not in (0, 1):
            reasons.append(f"STYPE {g.stype}: only a part set (0) or a part "
                           "(1) names the ALE parts")
        else:
            named = _sis_side_pids(state, g.sid, 1 if g.stype == 1 else 0)
            what = "part" if g.stype == 1 else "set"
            if named is None:
                reasons.append(f"{what} {g.sid} is not defined in the deck")
            else:
                miss = sorted(set(ale) - set(named))
                if miss:
                    reasons.append(f"{what} {g.sid} misses ALE part(s) {miss}")
        dirs = _AFT_DIRS.get(g.bctran)
        if dirs is None:
            reasons.append(f"BCTRAN {g.bctran}: not a constraint code (0-7)")
        elif dirs and ale:
            unheld = _ale_nodes_unheld(state, ale, dirs)
            if unheld:
                reasons.append(
                    f"BCTRAN {g.bctran}: OpenRadioss's FLOW-TRACKING has no "
                    "translation constraint and the ALE nodes do not all "
                    f"hold direction(s) {unheld}")
        if not reasons:
            plan.card = g
            plan.idef = -1
            plan.irot = 1 if g.bcrot == 0 else -1
    plan.reasons = reasons
    return plan


def ale_flow_tracking_lines(state: ConversionState) -> List[str]:
    """The ``/ALE/GRID/FLOW-TRACKING`` card of an accepted plan (round 9,
    B8), written by ``output._make_analysis_defaults`` right after
    ``/DEF_SOLID`` in ``_0000.rad`` only (an engine deck refuses a
    formulation switch, ``lectur.F:889-902`` MESSAGE 229) - the 2024 CFG
    grammar ``%10d%20lg`` (``ale_grid_flow-tracking.cfg``) under ``/BEGIN``
    2022, which prints WARNING 100211 and reads it. The keyword leaves
    ``skipped_keywords`` here, at the line that writes the card."""
    plan = _resolve_ale_flow_tracking(state)
    g = plan.card
    if g is None:
        return []
    state.skipped_keywords.remove(g.keyword)
    carried = (f"BCTRAN {g.bctran} is carried by the ALE nodes' own /BCS"
               if g.bctran else "BCTRAN 0 constrains no direction")
    state.warn(
        f"*ALE_REFERENCE_SYSTEM_GROUP {g.sid} (PRTYPE 4, BCEXP {g.bcexp}, "
        f"BCROT {g.bcrot}, BCTRAN {g.bctran}) -> /ALE/GRID/FLOW-TRACKING "
        f"I_def {plan.idef} I_rot {plan.irot} (--ale-flow-tracking): the ALE "
        "grid moves with the mass-weighted mean velocity of the ALE material "
        "about its centre of mass (alew7.F:186-227), as LS-DYNA's PRTYPE 4 "
        f"does; {carried}. The /BEGIN 2022 starter prints WARNING 100211 "
        "('format < 2024') and reads the card (engine echo 'FORMULATION : "
        "FLOW-TRACKING'). " + _AFT_MEASURED + " It is opt-in because that KE "
        "regression makes the row MIXED; the light-void coupling that would "
        "remove it is open (FT + a 1e-6 void dies at t 1.043e-4 with "
        "NEGATIVE RHO).")
    return ["/ALE/GRID/FLOW-TRACKING",
            "#    I_def           scale_def",
            _i(plan.idef) + _f(0.0),
            "#    I_rot           scale_rot",
            _i(plan.irot) + _f(0.0)]


def _make_ale_reference_notes(state: ConversionState) -> List[str]:
    """The ``*ALE_REFERENCE_SYSTEM_*`` sentences (round 9, B8); writes no
    card and draws no id. Under ``--ale-flow-tracking`` a refused deck gets
    ONE sentence naming every failing class; without the flag each card gets
    its own skip sentence (a PRTYPE-4 GROUP card names the opt-in). The
    generic ``*CONTROL_ALE`` note (it fires on 6 match rows) changes only
    under an ACCEPTED plan, where its 'not converted' clause would contradict
    the B8 sentence (the post-review round, F1)."""
    groups = state.ale_reference_groups
    others = sorted(set(state.ale_reference_others))
    if not groups and not others:
        return []
    if state.options.ale_flow_tracking:
        plan = _resolve_ale_flow_tracking(state)
        if plan.card is None and plan.reasons:
            head = ("*ALE_REFERENCE_SYSTEM_GROUP" if groups
                    else f"*{others[0]}")
            state.warn(f"{head}: not converted under --ale-flow-tracking - "
                       + "; ".join(plan.reasons)
                       + "; it stays listed as skipped.")
        return []
    for g in groups:
        if g.prtype == 4:
            state.warn(
                f"*ALE_REFERENCE_SYSTEM_GROUP {g.sid} (PRTYPE 4) is skipped: "
                "its OpenRadioss analogue /ALE/GRID/FLOW-TRACKING is written "
                "only under --ale-flow-tracking (opt-in - on bird_B it fixes "
                "the IE history, END +1484.66 -> +17.00 %, but worsens the "
                "deck KE through the full-density void, RMS 253.09 -> "
                "749.89 %).")
        else:
            state.warn(
                f"*ALE_REFERENCE_SYSTEM_GROUP {g.sid} (PRTYPE {g.prtype}) has "
                "no OpenRadioss analogue and is skipped.")
    for kw in others:
        state.warn(f"*{kw} has no OpenRadioss analogue and is skipped.")
    return []
