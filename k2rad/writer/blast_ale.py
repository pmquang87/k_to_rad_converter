"""Blast loads, detonations, ALE multi-material, FSI coupling, EBCS, INIVOL notes."""

from __future__ import annotations

from typing import Dict, List, Optional, Set
from ..state import ConversionState
from .common import (HDR, _emit_surf_part, _emit_surf_seg, _f, _i,
                     _part_scoped_segment_set)

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
    "_make_ebcs",
    "_make_inivol_notes",
    "_make_control_ale_notes",
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
        if _part_scoped_segment_set(state, nrf.nsid,
                                    "*BOUNDARY_NON_REFLECTING",
                                    "The /EBCS/NRF is DROPPED."):
            continue
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
