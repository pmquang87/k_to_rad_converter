"""Bolt pre-tension: *INITIAL_STRESS_SECTION → /PRELOAD and
*INITIAL_AXIAL_FORCE_BEAM → /PRELOAD/AXIAL."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from ..state import ConversionState, NodeData
from .common import (
    HDR,
    _emit_grnod_node,
    _emit_id_group,
    _f,
    _fmt_eid_list,
    _i,
    _vcross,
    _vnorm,
)
from .inistate import _plane_cut, _solid_sec_for_part
from .loads import _emit_funct
from .mesh import _effective_solid_isolid

__all__ = [
    "_preload_curve_window",
    "_preload_truncated_points",
    "_frame_nodes_for_normal",
    "_make_preload",
]


# ─────────────────────────────────────────────────────────────────────────────
# The LS-DYNA "initialization window" of a preload curve
# ─────────────────────────────────────────────────────────────────────────────

def _preload_truncated_points(pts):
    """The leading NON-DECREASING run of a preload curve.

    LS-DYNA Remark 2, identical wording for both preload keywords (Vol I R17
    p.3063 for *INITIAL_AXIAL_FORCE_BEAM, p.3144 for *INITIAL_STRESS_SECTION):
    "When the end of the load curve is reached, **or when the value of the load
    decreases from its maximum value**, the initialization stops."

    So: point 0 is always kept; every later point is kept while its ordinate is
    ``>=`` the running maximum (equal ordinates are a plateau and ARE kept);
    the first strictly LOWER ordinate ends the curve and everything after it is
    discarded. This is dyna2rad's ``/PRELOAD/AXIAL`` rule
    (convertinitialaxialforces.cxx:118-133) — the one place its two preload
    converters disagree, and the faithful one. (Its ``/PRELOAD`` ``radTstop``
    loop, convertinitialstresses.cxx:781-793, truncates only on an EXACT zero
    ordinate, so a curve that decays to a lower positive value is not truncated
    at all.)

    Points are sorted by abscissa first: only the ORDINATE monotonicity is a
    physical rule, the abscissa order is bookkeeping.
    """
    ordered = sorted(pts, key=lambda p: p[0])
    if not ordered:
        return []
    kept = [ordered[0]]
    running = ordered[0][1]
    for x, y in ordered[1:]:
        if y < running:
            break
        running = y
        kept.append((x, y))
    return kept


def _preload_curve_window(pts):
    """``(t_start, t_stop, plateau)`` of a preload curve, or ``None``.

    ``t_start`` = the curve's first abscissa (where the tightening begins),
    ``t_stop`` = the last abscissa of the leading non-decreasing run (where
    LS-DYNA's initialization stops), ``plateau`` = the largest ordinate on that
    run. ``None`` when the window is degenerate (a single point, or a curve
    that decreases immediately): the Radioss bolt law divides by
    ``0.3*(Tstop-Tstart)`` (sboltlaw.F) and a zero-length window is a division
    by zero — or, once ``TFIN==0`` becomes ``EP30`` at hm_read_preload.F:152, a
    part left at 1e-4 of its modulus for the whole run.
    """
    kept = _preload_truncated_points(pts)
    if len(kept) < 2:
        return None
    t_start, t_stop = kept[0][0], kept[-1][0]
    if not (t_stop > t_start):
        return None
    return (t_start, t_stop, max(y for _x, y in kept))


# ─────────────────────────────────────────────────────────────────────────────
# The /SECT frame that REALIZES the preload direction
# ─────────────────────────────────────────────────────────────────────────────

def _orthonormal_pair(nhat):
    """``(e1, e2)``, orthonormal and perpendicular to ``nhat``, with
    ``e1 x e2 == nhat`` exactly."""
    a = (1.0, 0.0, 0.0) if abs(nhat[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = a[0] * nhat[0] + a[1] * nhat[1] + a[2] * nhat[2]
    e1 = _vnorm((a[0] - d * nhat[0], a[1] - d * nhat[1], a[2] - d * nhat[2]))
    if e1 is None:                                   # pragma: no cover
        return None
    return (e1, _vcross(nhat, e1))


def _frame_nodes_for_normal(origin, nhat, scale: float):
    """Coordinates of three nodes N1,N2,N3 whose ``(N2-N1) x (N3-N1)`` is
    parallel to (and same-signed as) ``nhat``.

    ``hm_read_preload.F:203-217`` takes the pretension direction from exactly
    that cross product of the /SECT's ``node_ID1/2/3`` and refuses
    ``|n|^2 < 1e-20`` with ERROR 1244. ``_sect_frame_nodes`` — the frame the
    reporting /SECT uses — instead picks the three best-CONDITIONED nodes of
    the cut, which has nothing to do with the cutting-plane normal: measured on
    a 1x1x2 bar cut at x=0.5 with normal (1,0,0) it produced a starter-echoed
    NX/NY/NZ of (-0.707, 0, 0.707), i.e. 45 degrees off, at zero diagnostics.
    Three purpose-built nodes make the direction exact by construction.
    """
    pair = _orthonormal_pair(nhat)
    if pair is None:                                 # pragma: no cover
        return None
    e1, e2 = pair
    s = scale if scale > 0.0 else 1.0
    return (tuple(origin),
            tuple(origin[k] + s * e1[k] for k in range(3)),
            tuple(origin[k] + s * e2[k] for k in range(3)))


def _vector_direction(state: ConversionState, vid: int):
    """The unit direction of a *DEFINE_VECTOR[_NODES], or ``None``."""
    v = state.define_vectors.get(vid)
    if v is None:
        return None
    if v.is_nodes:
        nt, nh = state.nodes.get(v.nodet), state.nodes.get(v.nodeh)
        if nt is None or nh is None:
            return None
        return _vnorm((nh.x - nt.x, nh.y - nt.y, nh.z - nt.z))
    return _vnorm((v.xh - v.xt, v.yh - v.yt, v.zh - v.zt))


def _node_cloud_normal(state: ConversionState, nids: List[int]):
    """Best-conditioned plane normal of a node cloud, or ``None``.

    Used for a ``*DATABASE_CROSS_SECTION_SET`` whose ``*INITIAL_STRESS_SECTION``
    states no VID. LS-DYNA requires one there ("VID must be set when the SET
    variant of *DATABASE_CROSS_SECTION is used", Vol I R17 p.3144) precisely
    because the node ORDER in the set carries no plane information — which is
    why dyna2rad, which never reads VID, falls back to a dummy
    (0,0,0)/(1,0,0)/(0,1,0) triad and silently preloads along global +Z
    (convertcrosssections.cxx:246-251). Fitting the plane the section nodes
    actually lie in is the honest best effort: exact for a planar cut, and the
    caller says out loud that it was a fit.
    """
    pts = [state.nodes[n] for n in nids if n in state.nodes]
    if len(pts) < 3:
        return None
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    cz = sum(p.z for p in pts) / len(pts)
    rel = [(p.x - cx, p.y - cy, p.z - cz) for p in pts]
    u = max(rel, key=lambda v: v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if u[0] ** 2 + u[1] ** 2 + u[2] ** 2 <= 0.0:
        return None
    best, best_a2 = None, 0.0
    for v in rel:
        c = _vcross(u, v)
        a2 = c[0] ** 2 + c[1] ** 2 + c[2] ** 2
        if a2 > best_a2:
            best, best_a2 = c, a2
    if best is None or best_a2 <= 0.0:
        return None
    return _vnorm(best)


# ─────────────────────────────────────────────────────────────────────────────
# *INITIAL_STRESS_SECTION → /PRELOAD
# ─────────────────────────────────────────────────────────────────────────────

#: /PROP/SOLID Isolid values that actually carry a bolt preload on this build.
#: Measured on a 1x1x4 hex bar, /PRELOAD Itype=2 Preload=200 MPa, engine to
#: 4e-4 s, reading /TH/BRIC SZ of the preloaded brick:
#:   Isolid 14 -> 200.0 at t=0, 199.7 during, ~200 after Tstop   (cleanest)
#:   Isolid 17 -> 200.0 at t=0, mild ringing, ~200 after Tstop
#:   Isolid  5 -> 200.0 at t=0, 203.1 during, 199.1 after Tstop  (as good as 17)
#:   Isolid  1 -> ZERO OR NEGATIVE VOLUME at cycle 0, T01 dies at 2.2e-5
#:   Isolid  2 -> garbage (-1347 / 20511 / 3899 MPa)
#:   Isolid 12 -> 0 MPa for the whole run: a SILENT no-op
#:   Isolid 24 -> diverges at ~0.95*Tstop to 1400-1500 MPa, permanently
#:
#: Isolid 5 is what *CONTROL_HOURGLASS IHQ 4/5 maps to, so leaving it out made
#: the warning fire on decks whose bolt preload is in fact fine — re-measured
#: (0 ERRORS, NORMAL TERMINATION, 2813 cycles) and added.
_PRELOAD_STABLE_ISOLID = frozenset({5, 14, 17})


def _preload_sect_scale(state: ConversionState, origin, nids: List[int]) -> float:
    """A length scale for the synthesized frame, taken from the section itself
    so the three new nodes land in the cut's own neighbourhood instead of one
    deck unit away from it (which in a metre model would be a metre)."""
    best = 0.0
    for n in nids:
        nd = state.nodes.get(n)
        if nd is None:
            continue
        d = math.sqrt((nd.x - origin[0]) ** 2 + (nd.y - origin[1]) ** 2
                      + (nd.z - origin[2]) ** 2)
        best = max(best, d)
    return best if best > 0.0 else 1.0


def _make_preload_sections(state: ConversionState,
                           used_preload: Set[int]) -> List[str]:
    """*INITIAL_STRESS_SECTION[_TITLE] → /PRELOAD, on a DEDICATED /SECT.

    Card layout (hm_cfg_files radioss2018/LOADS/preload.cfg, the newest FORMAT
    at or below the /BEGIN 2022 this converter writes)::

        /PRELOAD/preload_ID
        preload_title
        #  sect_ID   sens_ID     Itype  <BLANK>             Preload              Tstart               Tstop
        CARD("%10d%10d%10d%10s%20lg%20lg%20lg")

    **The Fct_ID column is deliberately left blank.** It exists only in
    FORMAT(radioss2026); at /BEGIN 2019..2025 the hm_reader drops the value
    into the radioss2018 ``_BLANK_`` and reports ``WARNING 100214 unsupported
    field exists`` — twin decks differing ONLY in the /BEGIN line echoed
    ``IFUNC 0`` at 2019/2021/2022/2023/2024/2025 and ``IFUNC 900`` at 2026, and
    the 2022 pair with and without the function produced byte-identical engine
    T01 histories. Emitting a function id here would be the exact
    ``Preload = 0 + Fct_ID`` shape dyna2rad ships
    (convertinitialstresses.cxx:801-805), which is identically zero stress:
    the Radioss function is a dimensionless SCALE on ``Preload``
    (sboltini.F:76-81 builds ``LOAD*n(x)n``, boltst.F:83-89 applies
    ``SIG = SFAC*BPRELD``), and the only warning, MSGID 1255, is gated on
    ``IFUN==0``.

    So the LCID is resolved HERE: ``Preload`` = the curve's plateau stress and
    ``Tstart``/``Tstop`` = the window LS-DYNA's Remark 2 defines, with the lost
    ramp shape named in a warning. The window is not cosmetic — sboltlaw.F
    holds the preloaded part at 1e-4 of its modulus until ``Tstart+0.4*dT``,
    ramps it to full at ``Tstart+0.7*dT`` and then rewrites the reference
    density so the preload LOCKS, so the tightening DURATION survives even
    though the ramp does not.
    """
    if not state.ini_stress_sections:
        return []
    by_csid: Dict[int, object] = {}
    for cs in state.cross_sections:
        if cs.csid > 0:
            by_csid.setdefault(cs.csid, cs)
    used_sect = {sid for sid, _t in state.sect_ids}
    lines: List[str] = []
    emitted = False

    for iss in state.ini_stress_sections:
        label = (f"*INITIAL_STRESS_SECTION {iss.issid}"
                 + (f" '{iss.title}'" if iss.title else ""))
        cs = by_csid.get(iss.csid)
        if cs is None:
            state.warn(f"{label}: *DATABASE_CROSS_SECTION id {iss.csid} not "
                       "found — no /PRELOAD emitted (a /PRELOAD naming an "
                       "unknown section is starter ERROR 1243).")
            continue
        curve = state.curves.get(iss.lcid)
        if curve is None or not curve.pts:
            state.warn(f"{label}: LCID {iss.lcid} resolves to no converted "
                       "*DEFINE_CURVE — no /PRELOAD emitted. The curve is the "
                       "only statement of HOW MUCH pre-tension the bolt "
                       "carries; inventing a magnitude is not an option.")
            continue
        window = _preload_curve_window(curve.pts)
        if window is None:
            state.warn(f"{label}: curve {iss.lcid} states no usable preload "
                       "window (a single point, or an ordinate that decreases "
                       "from the very first segment), so LS-DYNA's "
                       "initialization would stop immediately — no /PRELOAD "
                       "emitted. A ramp from the origin to the target stress "
                       "is what this card needs (Vol I R17 p.3144, Remark 2).")
            continue
        t_start, t_stop, plateau = window
        if plateau <= 0.0:
            state.warn(
                f"{label}: curve {iss.lcid} peaks at {plateau:.6G}, i.e. the "
                "'pre-tension' is zero or COMPRESSIVE. The starter answers "
                "WARNING 1255 ('NEGATIVE BOLT PRELOADING VALUE MIGHT GET "
                "DIVERGING RESULTS; INPUT RAMPING FUNCTION WILL HELP', "
                "hm_read_preload.F:143-150, which fires exactly because k2rad "
                "cannot pass a ramping function at /BEGIN 2022) and the bolt "
                "law still softens the section to 1e-4 of E for 40% of the "
                "window. Check the sign and the SFO of the curve.")

        # ── the part scope: the section's own PSID intersected with this
        # card's PSID (Vol I R17 p.3144, "included in both").
        extra: Optional[Set[int]] = None
        if iss.psid > 0:
            entry = state.part_sets.get(iss.psid)
            if entry is None:
                state.warn(f"{label}: part set {iss.psid} not found — the "
                           "preload scope fell back to the cross-section's own "
                           "parts. Check the *SET_PART id.")
            else:
                extra = set(entry[1])

        if cs.kind == "SET":
            nids, solid_eids, normal, why = _set_section_scope(state, cs, iss,
                                                               extra, label)
        else:
            nids, _sh, solid_eids, _bm = _plane_cut(
                state, cs, extra_pids=extra, warn_missing_psid=False)
            normal = _vnorm((cs.xch - cs.xct, cs.ych - cs.yct,
                             cs.zch - cs.zct))
            why = "the cutting plane normal XCT->XCH"
            if iss.vid:
                vdir = _vector_direction(state, iss.vid)
                if vdir is None:
                    state.warn(f"{label}: VID {iss.vid} resolves to no "
                               "*DEFINE_VECTOR — the pretension direction fell "
                               "back to the cutting plane normal XCT->XCH.")
                else:
                    normal, why = vdir, f"*DEFINE_VECTOR {iss.vid}"
        if normal is None:
            state.warn(f"{label}: the pretension direction could not be "
                       "resolved (zero-length plane normal / vector) — no "
                       "/PRELOAD emitted (starter ERROR 1244).")
            continue
        # A thick shell rides in solid_eids because it shares the /BRICK card
        # (inistate.py's _plane_cut appends state.tshell_elems on purpose, so a
        # section through a thick-shell part still records force). It cannot be
        # PRE-TENSIONED though: SBOLTINI is reached only from sinit3, s4init3,
        # s8zinit3 and s10init3, never from the thick-shell initialisers, so a
        # thick shell in the preload group keeps a zero BPRELD while still being
        # counted in the starter's NS. LS-DYNA does not support it either
        # (Vol I R17 p.3145 Remark 4 lists solid types only). Drop them from the
        # preload group — the reporting /SECT keeps them — and say so.
        tshell_ids = {e.eid for e in state.tshell_elems}
        cut_tshells = [e for e in solid_eids if e in tshell_ids]
        if cut_tshells:
            solid_eids = [e for e in solid_eids if e not in tshell_ids]
            state.warn(
                f"{label}: the cross section also cuts thick-shell element(s) "
                f"{_fmt_eid_list(cut_tshells)} (*ELEMENT_TSHELL). They were "
                "left OUT of the /PRELOAD element group: they share the /BRICK "
                "card but not the solid initialiser, so SBOLTINI is never "
                "called for them and they would sit in the group carrying no "
                "pre-stress at all. LS-DYNA does not pre-tension thick shells "
                "either (Vol I R17 p.3145 Remark 4 lists solid element types "
                "only). The reporting cross-section still contains them.")
        if not solid_eids:
            state.warn(f"{label}: the cross section cuts no SOLID element "
                       "inside the preload part scope — no /PRELOAD emitted. "
                       "hm_read_preload.F:233-237 refuses such a section with "
                       "ERROR 1251 ('THERE IS NO SOLID ELEMENT IN SECTION ID'), "
                       "and iboltini/sboltini tag bricks only: shells and beams "
                       "in the section cannot be pre-tensioned at all.")
            continue

        if not nids:
            # hm_read_sect.F builds the section from grnod_ID (the nodes ON the
            # cut) as well as the element groups, and an empty /GRNOD/NODE
            # gives NSTRF(K0+6)=0. Reachable only for a _SET section whose NSID
            # is empty or missing; the plane cut always yields the tail-side
            # nodes of the elements it cut.
            state.warn(f"{label}: the cross section has an empty node group — "
                       "no /PRELOAD emitted. A /SECT needs the nodes on the cut "
                       "plane (the _SET variant takes them from NSID).")
            continue

        _warn_preload_formulation(state, solid_eids, label)

        origin = ((cs.xct, cs.yct, cs.zct) if cs.kind != "SET"
                  else _nid_centroid(state, nids))
        scale = _preload_sect_scale(state, origin, nids)
        frame = _frame_nodes_for_normal(origin, normal, scale)
        if frame is None:                                # pragma: no cover
            state.warn(f"{label}: could not build a frame perpendicular to the "
                       "pretension direction — no /PRELOAD emitted.")
            continue
        fn_ids = [state.next_node_id() for _ in range(3)]
        for nid, xyz in zip(fn_ids, frame):
            state.nodes[nid] = NodeData(xyz[0], xyz[1], xyz[2])

        sect_id = state.next_id()
        while sect_id in used_sect:
            sect_id = state.next_id()
        used_sect.add(sect_id)
        if iss.issid > 0 and iss.issid not in used_preload:
            pre_id = iss.issid
        else:
            pre_id = state.next_id()
            while pre_id in used_preload:        # same retry as /SECT above
                pre_id = state.next_id()
        used_preload.add(pre_id)
        title = iss.title or f"PRELOAD_{pre_id}"
        # next_grnod_id(), not next_id(): k2rad re-emits every user *SET_NODE
        # under its own SID, so a SID at or above the auto base would collide
        # here — starter ERROR 79 over the merged /GRNOD table, a refused deck.
        grnod_id = state.next_grnod_id()
        grbric_id = state.next_id()

        lines += ["/NODE"]
        for nid, xyz in zip(fn_ids, frame):
            lines.append(f"{_i(nid)}{_f(xyz[0])}{_f(xyz[1])}{_f(xyz[2])}")
        lines.append(HDR)
        lines += _emit_grnod_node(grnod_id, f"{title}_sect_nodes", nids)
        lines += _emit_id_group("GRBRIC/BRIC", grbric_id,
                                f"{title}_sect_bricks", solid_eids)
        lines += [
            f"/SECT/{sect_id}",
            f"{title}_SECT",
            "#  node_ID1  node_ID2  node_ID3  grnod_ID     ISAVE  Frame_ID              deltaT               alpha",
            f"{_i(fn_ids[0])}{_i(fn_ids[1])}{_i(fn_ids[2])}{_i(grnod_id)}"
            f"{_i(0)}{_i(0)}{_f(0.0)}{_f(0.0)}",
            "#file_name (unused: ISAVE=0)",
            f"SECT_{sect_id}",
            "#grbric_ID           grshel_ID grtrus_ID grbeam_ID grsprg_ID grtria_ID     Niter              Iframe",
            f"{_i(grbric_id)}{' ' * 10}{_i(0)}{_i(0)}{_i(0)}"
            f"{_i(0)}{_i(0)}{_i(0)}{' ' * 10}{_i(0)}",
            HDR,
            f"/PRELOAD/{pre_id}",
            title[:100],
            "#  sect_ID   sens_ID     Itype                          Preload              Tstart               Tstop",
            f"{_i(sect_id)}{_i(0)}{_i(2)}{' ' * 10}"
            f"{_f(plateau)}{_f(t_start)}{_f(t_stop)}",
            HDR,
        ]
        emitted = True

        state.warn(
            f"{label}: LCID {iss.lcid} ramps the bolt stress to {plateau:.6G} "
            f"over [{t_start:.6G}, {t_stop:.6G}] — the RAMP SHAPE is not "
            "expressible at /BEGIN 2022 and was dropped; /PRELOAD carries the "
            f"plateau {plateau:.6G} as Itype=2 (stress) with Tstart="
            f"{t_start:.6G} and Tstop={t_stop:.6G}. The Fct_ID column exists "
            "only in FORMAT(radioss2026): written at 2022 it lands in the "
            "radioss2018 _BLANK_ and is dropped to IFUNC=0 with WARNING "
            "100214 (measured on twin decks, byte-identical engine results "
            "with and without it). So the stress appears as a STEP at Tstart "
            "(boltst.F:59-74) instead of following the curve, cushioned by the "
            "bolt law's reduced modulus: sboltlaw.F holds the preloaded "
            "elements at 1e-4 of E until Tstart+0.4*(Tstop-Tstart), ramps to "
            "full at Tstart+0.7*(Tstop-Tstart) and then rebases the reference "
            "density so the preload LOCKS. Tstop ends the window per LS-DYNA "
            "Remark 2 (the curve's end, or its first decrease from the "
            "maximum).")
        state.warn(
            f"{label}: the /PRELOAD hangs on a DEDICATED /SECT/{sect_id} with "
            f"three synthesized frame nodes ({fn_ids[0]}, {fn_ids[1]}, "
            f"{fn_ids[2]}) built so that (N2-N1)x(N3-N1) is exactly "
            f"{why} = ({normal[0]:.6G}, {normal[1]:.6G}, {normal[2]:.6G}) — "
            "hm_read_preload.F:203-217 takes the pretension direction from "
            "that cross product alone. The *DATABASE_CROSS_SECTION's own /SECT "
            "and its /TH/SECTIO channel are left untouched, so the reported "
            "section force keeps the scope and frame it had.")
        # The preload window has to CLOSE inside the run or the bolted parts
        # never get their stiffness back: sboltlaw.F:119-128 holds them at
        # REDUC1 = 1e-4 of E until Tstart+0.4*dT and reaches 1.0 only at
        # Tstart+0.7*dT. An LS-DYNA deck that tightened the bolt inside a
        # dynamic-relaxation phase states that window in DR pseudo-time
        # (Vol I R17 p.3144 Remark 1 is written entirely about DR), which has
        # nothing to do with ENDTIM — and k2rad warn-skips
        # *CONTROL_DYNAMIC_RELAXATION, so nothing else would catch it.
        run_end = (state.ctrl_termination.endtim
                   if state.ctrl_termination else 1.0)
        t_full = t_start + 0.7 * (t_stop - t_start)
        if run_end > 0.0 and t_full > run_end:
            state.warn(
                f"{label}: the preload window closes at Tstart+0.7*(Tstop-"
                f"Tstart) = {t_full:.6G}, AFTER the run ends at "
                f"{run_end:.6G} (*CONTROL_TERMINATION ENDTIM). sboltlaw.F:119-"
                "128 holds every preloaded element at 1e-4 of its Young's "
                "modulus until Tstart+0.4*(Tstop-Tstart) and restores the full "
                "modulus only at Tstart+0.7*(Tstop-Tstart), so on this deck "
                "the bolted parts stay ~10000x too soft for the WHOLE "
                "analysis, at zero starter or engine diagnostics. This is the "
                "normal shape when the source deck tightened the bolt inside a "
                "*CONTROL_DYNAMIC_RELAXATION phase, whose pseudo-time is "
                "unrelated to ENDTIM. Rescale the *DEFINE_CURVE abscissae into "
                "the transient time base, or raise ENDTIM past "
                f"{t_full:.6G}.")
        dropped = []
        if iss.izshear:
            dropped.append(
                f"IZSHEAR={iss.izshear} (LS-DYNA would let shear"
                + (" and bending" if iss.izshear == 2 else "")
                + " develop and prescribe only the MEAN normal stress per bolt;"
                " Radioss always prescribes the full sigma*n(x)n at every "
                "integration point, sboltini.F:76-81 — i.e. the IZSHEAR=0 "
                "behaviour, section infinitely weak in bending and shear while "
                "the preload acts)")
        if iss.istiff:
            dropped.append(
                f"ISTIFF={iss.istiff} ("
                + ("LS-DYNA's linearly elastic GHOST elements inside the cut, "
                   "which stop the section distorting while the bolt tightens"
                   if iss.istiff > 0 else
                   f"the negative spelling: |{iss.istiff}| is a load curve id "
                   "giving the stiffness fraction as a function of time, with "
                   "the preload stress auto-adjusted +/-10% so the TOTAL "
                   "section stress follows LCID — Vol I R17 p.3144. The curve "
                   "id is stated as written on the card, un-offset, because "
                   "the field is dropped before any *INCLUDE_TRANSFORM offset "
                   "would matter")
                + "; /PRELOAD has no equivalent, so a coarse or irregular bolt "
                "mesh may distort more than in LS-DYNA)")
        if dropped:
            state.warn(f"{label}: " + "; ".join(dropped)
                       + " — no /PRELOAD slot at any Radioss version, dropped.")
    return lines if emitted else []


def _nid_centroid(state: ConversionState, nids: List[int]):
    pts = [state.nodes[n] for n in nids if n in state.nodes]
    if not pts:
        return (0.0, 0.0, 0.0)
    return (sum(p.x for p in pts) / len(pts),
            sum(p.y for p in pts) / len(pts),
            sum(p.z for p in pts) / len(pts))


def _set_section_scope(state: ConversionState, cs, iss, extra, label: str):
    """Node group, brick list and pretension direction of a
    ``*DATABASE_CROSS_SECTION_SET``-based preload."""
    entry = state.node_sets.get(cs.nsid)
    nids = list(entry[1]) if entry else []
    solids = {e.eid: e for e in state.solid_elems}
    solids.update({e.eid: e for e in state.tshell_elems})
    eids: List[int] = []
    if cs.hsid:
        se = state.solid_sets.get(cs.hsid)
        if se is not None:
            for eid in se[1]:
                e = solids.get(eid)
                if e is None:
                    continue
                if extra is not None and e.pid not in extra:
                    continue
                eids.append(eid)
    if iss.vid:
        vdir = _vector_direction(state, iss.vid)
        if vdir is not None:
            return (nids, eids, vdir, f"*DEFINE_VECTOR {iss.vid}")
        state.warn(f"{label}: VID {iss.vid} resolves to no *DEFINE_VECTOR.")
    normal = _node_cloud_normal(state, nids)
    state.warn(
        f"{label}: the cross section is the _SET variant and states "
        + (f"an unresolvable VID {iss.vid}" if iss.vid else "no VID")
        + ", but LS-DYNA requires one there — 'VID must be set when the SET "
        "variant of *DATABASE_CROSS_SECTION is used' (Vol I R17 p.3144), "
        "because a node SET carries no plane orientation. The pretension "
        "direction was FITTED to the plane the section nodes lie in"
        + (f" = ({normal[0]:.6G}, {normal[1]:.6G}, {normal[2]:.6G})"
           if normal else " and the fit FAILED (fewer than three "
                          "non-colinear section nodes)")
        + ". That is exact for a planar cut and an approximation otherwise — "
        "add a *DEFINE_VECTOR and point VID at it to state the axis exactly. "
        "(dyna2rad never reads VID and falls back to a dummy triad, i.e. "
        "global +Z, silently.)")
    return (nids, eids, normal, "a plane fitted to the section nodes")


def _warn_preload_formulation(state: ConversionState, solid_eids: List[int],
                              label: str) -> None:
    """Name every preloaded part whose /PROP/SOLID formulation does not carry
    the preload on this build (see ``_PRELOAD_STABLE_ISOLID``)."""
    # Solids only: thick shells are filtered out of the preload group by the
    # caller (they cannot be pre-tensioned at all), and _solid_sec_for_part
    # would return None for them anyway — every check below would `continue`
    # past them without a word, which is the gap that filter closed.
    elems = {e.eid: e for e in state.solid_elems}
    bad: Dict[int, Set[int]] = {}
    penta: Set[int] = set()
    ismstr10: Set[int] = set()
    for eid in solid_eids:
        e = elems.get(eid)
        if e is None:
            continue
        # Classify on the EMITTED /BRICK row, not on the LS-DYNA connectivity.
        # hm_read_solid.F:167 only sets ISOLNOD=6 when cells 7 AND 8 are blank
        # (`IXS(8,I)+IXS(9,I)==0`), and mesh.py's /BRICK writer pads a short
        # node list with nodes[-1], so a wedge written the usual LS-DYNA way —
        # 6 ids, or 8 with n3=n4 and n7=n8 — leaves k2rad as a DEGENERATE HEX8
        # and IS pre-tensioned. Measured on a 8-wedge bolt bar: the starter
        # echoes AREA 1.000E+00 (identical to the hex twin) and /TH/BRIC SZ on
        # both cut wedges reads 200.00 MPa at t=0 and ~200 past Tstop. Only a
        # deck that spells the wedge with literal ZEROS in cells 7-8 reaches
        # ISOLNOD=6, and only that one loses the preload.
        emitted_nodes = list(e.nodes)
        if emitted_nodes and len(emitted_nodes) < 8:
            emitted_nodes += [emitted_nodes[-1]] * (8 - len(emitted_nodes))
        emitted_nodes = emitted_nodes[:8]
        if len(emitted_nodes) == 8 and emitted_nodes[6] + emitted_nodes[7] == 0:
            penta.add(e.pid)
        sec = _solid_sec_for_part(state, e.pid)
        if sec is None:
            continue
        if (e.pid in state.ismstr10_solid_pids
                or sec.secid in state.ismstr10_solid_secids):
            ismstr10.add(e.pid)
        isolid = _effective_solid_isolid(state, e.pid, sec)
        if isolid not in _PRELOAD_STABLE_ISOLID:
            bad.setdefault(isolid, set()).add(e.pid)
    for isolid, pids in sorted(bad.items()):
        state.warn(
            f"{label}: preloaded part(s) {sorted(pids)} emit /PROP/SOLID "
            f"Isolid={isolid}. Measured on this build with /PRELOAD Itype=2 at "
            "200 MPa, only Isolid 5, 14 and 17 hold the pre-tension (14 "
            "cleanest: 200.0 MPa at t=0, still ~200 after Tstop). Isolid 1 and "
            "2 hit ZERO OR NEGATIVE VOLUME at cycle 0, Isolid 12 is a "
            "completely SILENT no-op (0 MPa for the whole run, 0 errors, 0 "
            "warnings) and Isolid 24 diverges shortly after "
            "0.7*(Tstop-Tstart) to 1400-1500 MPa. Set the part's "
            "*SECTION_SOLID ELFORM — or its *CONTROL_HOURGLASS IHQ, which also "
            "picks Isolid — to one of the three, or the bolt pre-tension will "
            "not do what this card says.")
    if ismstr10:
        state.warn(
            f"{label}: preloaded part(s) {sorted(ismstr10)} carry /PROP/SOLID "
            "Ismstr=10 (total strain), which k2rad sets because they are /XREF "
            "or /MAT/LAW95 / LAW90 parts that need it. A PRELOADED element "
            "group cannot keep it: sgrtails.F:1387-1412 shifts Ismstr 10 -> 4 "
            "(11 -> 1, 12 -> 2) with WARNING 1775 'PRELOADED ELEMENTS CANNOT "
            "USE TOTAL STRAIN FORMULATION'. So the bolt preload silently takes "
            "the total-strain formulation away from the very parts that were "
            "given it — split the bolted region onto its own *SECTION_SOLID, "
            "or drop the preload there.")
    if penta:
        state.warn(
            f"{label}: preloaded part(s) {sorted(penta)} contain 6-node PENTA "
            "solids spelled with BLANK cells 7-8, which the starter reads as "
            "ISOLNOD=6 (hm_read_solid.F:167) and CANNOT pre-tension. SBOLTINI "
            "is called only from sinit3 (HEX8), s4init3/s10init3 (tetra) and "
            "s8zinit3, never from S6ZINIT3, so such a penta keeps a zero "
            "BPRELD and carries no pre-stress at all; SECTAREA likewise has no "
            "ISOLNOD==6 branch, so those elements add nothing to the echoed "
            "section AREA. Measured on an ALL-penta section spelled that way: "
            "AREA echoes 0.000E+00, every element stress stays 0 for the whole "
            "run, at 0 starter errors and 0 warnings. A MIXED section still "
            "preloads its hexas and tetras, so the bolt simply carries less "
            "than the card asks — silently, either way. Repeating the last "
            "node into cells 7-8 (LS-DYNA's usual n1 n2 n3 n3 n5 n6 n7 n7 "
            "wedge) makes it a degenerate HEX8, which IS pre-tensioned; "
            "remeshing as hexas or tetras also works.")


# ─────────────────────────────────────────────────────────────────────────────
# *INITIAL_AXIAL_FORCE_BEAM → /PRELOAD/AXIAL
# ─────────────────────────────────────────────────────────────────────────────

def _make_preload_axial(state: ConversionState,
                        used_preload: Set[int]) -> List[str]:
    """*INITIAL_AXIAL_FORCE_BEAM → /PRELOAD/AXIAL, one card per emitted family.

    Card layout (hm_cfg_files radioss2024/LOADS/preload_axial.cfg — the ONLY
    FORMAT block this keyword has)::

        /PRELOAD/AXIAL/preload_ID
        preload_axialtitle
        #   set_id   sens_id                             curveid             Preload                Damp
        CARD("%10d%10d%10s%10d%20lg%20lg")

    **Emitted at the /BEGIN 2022 this converter writes.** The version gate here
    behaves the OPPOSITE way to /PRELOAD's Fct_ID: a whole new KEYWORD falls
    back to the newest format and parses correctly, while a new FIELD inside an
    old keyword is dropped. Twin decks at /BEGIN 2022 / 2024 / 2026 echoed an
    identical ``BOLT 1D-ELEMENT PRELOADINGS`` table and produced bit-identical
    engine T01 histories; 2022 adds only the advisory

        WARNING ID : 100211  Unsupported option /PRELOAD/AXIAL in format < 2024

    which this converter restates rather than hiding.

    ``Preload`` is the function's Y-SCALE, which is exactly what LS-DYNA's
    SCALE is: ``hm_read_preload_axial.F90:255-259`` reads it (turning 0 into 1)
    and ``preload_axial.F90:33`` computes
    ``f1 = stf_f*f1 + y_scal*preload1 + damp*v12`` with ``stf_f`` hard-zero, so
    inside the window the element's own axial force is REPLACED by
    ``SCALE * f(t)``. No rescaling of any kind is needed.

    The curve is MANDATORY: ``hm_pre_read_preload_axial.F90:100-101`` does
    ``if (ifun == 0) cycle`` so a card without one is not even counted, and the
    real read then calls ``ancmsg(msgid=154)`` with no ``if (ifun>0)`` guard.
    Measured: Fct_ID=0 gives no table, no error, no warning and zero force for
    the whole run. An unresolvable LCID therefore emits nothing at all.
    """
    if not state.ini_axial_force_beams:
        return []
    lines: List[str] = []
    emitted = False
    for rec in state.ini_axial_force_beams:
        label = f"*INITIAL_AXIAL_FORCE_BEAM BSID={rec.bsid}"
        entry = state.beam_sets.get(rec.bsid)
        if entry is None:
            state.warn(f"{label}: *SET_BEAM {rec.bsid} not found — no "
                       "/PRELOAD/AXIAL emitted (the bolt carries no "
                       "pre-tension).")
            continue
        curve = state.curves.get(rec.lcid)
        if curve is None or not curve.pts:
            state.warn(
                f"{label}: LCID {rec.lcid} resolves to no converted "
                "*DEFINE_CURVE — no /PRELOAD/AXIAL emitted. The function is "
                "mandatory on this card: hm_pre_read_preload_axial.F90:100 "
                "skips a block with curveid=0 so it is not even counted, and "
                "hm_read_preload_axial.F90:244-252 then raises ERROR 154 for a "
                "function it cannot find. Measured with Fct_ID=0: no BOLT "
                "1D-ELEMENT PRELOADINGS table, no diagnostic, zero force.")
            continue

        beam_eids: List[int] = []
        spring_eids: List[int] = []
        unusable: List[int] = []
        not_emitted: List[int] = []
        for eid in entry[1]:
            if eid in state.beam_elem_ids:
                beam_eids.append(eid)
            elif eid in state.spring_elem_ids:
                (spring_eids if eid in state.spring_axial_preloadable
                 else unusable).append(eid)
            else:
                not_emitted.append(eid)
        if not_emitted:
            state.warn(f"{label}: element(s) {_fmt_eid_list(not_emitted)} of "
                       "the *SET_BEAM reached neither a /BEAM nor a /SPRING in "
                       "the converted deck (their part or section was dropped "
                       "upstream) — they were left out of the preload group. "
                       "Naming an element the deck does not define is starter "
                       "ERROR 69 and would refuse the whole run.")
        if unusable:
            state.warn(
                f"{label}: element(s) {_fmt_eid_list(unusable)} became "
                "/SPRING connectors whose property does NOT satisfy the "
                "/PRELOAD/AXIAL gate — dropped from the preload. rinit3.F:"
                "1627-1690 accepts only /PROP/TYPE4 and /PROP/TYPE13 with a "
                "non-zero axial fct_ID1 AND a hardening flag H in 1..7 (else "
                "ERROR 3057), or /PROP/TYPE23 paired with /MAT/LAW113 (else "
                "ERROR 3053 'SPRING PROPERTY TYPE %d IS NOT COMPATIBLE WITH "
                "/PRELOAD/AXIAL'). Both are hard stops, so emitting the card "
                "anyway would refuse the deck instead of losing one bolt.")
        if not beam_eids and not spring_eids:
            state.warn(f"{label}: no preloadable 1D element left in *SET_BEAM "
                       f"{rec.bsid} — no /PRELOAD/AXIAL emitted.")
            continue

        pts = _preload_truncated_points(curve.pts)
        if len(pts) < 2:
            state.warn(f"{label}: curve {rec.lcid} states no usable preload "
                       "ramp (a single point, or an ordinate that decreases "
                       "from the first segment) — no /PRELOAD/AXIAL emitted.")
            continue
        fid = state.next_curve_id()
        lines += _emit_funct(
            fid, f"PRELOAD_AXIAL_{rec.bsid}_from_LCID_{rec.lcid}", pts)

        families = []
        if spring_eids:
            families.append(("GRSPRI/SPRI", "SPRING", spring_eids))
        if beam_eids:
            families.append(("GRBEAM/BEAM", "BEAM", beam_eids))
        for keyword, fam, eids in families:
            grp = state.next_id()
            pre_id = state.next_id()
            while pre_id in used_preload:
                pre_id = state.next_id()
            used_preload.add(pre_id)
            title = rec.title or f"AXIAL_PRELOAD_BSID_{rec.bsid}"
            lines += _emit_id_group(keyword, grp,
                                    f"{title}_{fam.lower()}s", eids)
            lines += [
                f"/PRELOAD/AXIAL/{pre_id}",
                f"{title} ({fam})"[:100],
                "#   set_id   sens_id                             curveid"
                "             Preload                Damp",
                f"{_i(grp)}{_i(0)}{' ' * 10}{_i(fid)}"
                f"{_f(rec.scale)}{_f(0.0)}",
                HDR,
            ]
            emitted = True

        if beam_eids and spring_eids:
            state.warn(
                f"{label}: *SET_BEAM {rec.bsid} straddles two Radioss element "
                f"families — {len(beam_eids)} /BEAM and {len(spring_eids)} "
                "/SPRING — so it was split into TWO /PRELOAD/AXIAL cards on "
                "two groups. One set_id resolves to exactly ONE family: "
                "hm_read_preload_axial.F90:262-292 scans /GRSPRI, then "
                "/GRBEAM, then /GRTRUSS and takes the FIRST non-empty match, "
                "so a single card would have preloaded the springs and "
                "silently dropped the beams.")
        state.warn(
            f"{label}: /PRELOAD/AXIAL exists only as FORMAT(radioss2024) and "
            "this deck is written at /BEGIN 2022, so the starter reports "
            "'WARNING ID : 100211 Unsupported option /PRELOAD/AXIAL in format "
            "< 2024'. It is ADVISORY: measured on twin decks, the hm_reader "
            "falls back to the newest format and the BOLT 1D-ELEMENT "
            "PRELOADINGS echo plus the engine T01 are identical at 2022, 2024 "
            "and 2026.")
        state.warn(
            f"{label}: LCID {rec.lcid} was truncated to its leading "
            f"non-decreasing run and written as /FUNCT/{fid} "
            f"({len(pts)} point(s), last abscissa {pts[-1][0]:.6G}); "
            f"Preload = SCALE = {rec.scale:.6G} scales it "
            "(preload_axial.F90:33 f1 = y_scal*f(t), the element's own axial "
            "force fully REPLACED inside the window). That last abscissa is "
            "what ENDS the preload — get_preload_axial takes t_stop from the "
            "function's own x-range — and it is the right place to end it: "
            "LS-DYNA stops the initialization at the curve's end or its first "
            "decrease from the maximum (Vol I R17 p.3063, Remark 2), and "
            "measured, Radioss does NOT snap the force back there either — "
            "the element's rate-form law resumes from the force it holds "
            "(F1 oscillating about the plateau, mean 1000 N in the probe). "
            "Keeping the descending tail would instead keep pushing the bolt "
            "along the curve. Damp=0 and sens_id=0: LS-DYNA states neither.")
        if rec.kbend:
            state.warn(
                f"{label}: KBEND={rec.kbend} has no /PRELOAD/AXIAL slot — "
                "dropped. KBEND=1 keeps the beam's bending stiffness by "
                "retaining the axial-stress gradient across the section; "
                "KBEND=2 additionally allows SEVERAL beams in line per bolt, "
                "with LS-DYNA imposing internal constraints on the "
                "intermediate nodes and controlling the length reduction by "
                "displacement (Vol I R17 p.3062). Radioss prescribes one axial "
                "force per element with no gradient and no inter-element "
                "constraint, i.e. the KBEND=0 behaviour"
                + (" — a multi-beam bolt shank will NOT hold together the way "
                   "it does in LS-DYNA." if rec.kbend == 2 else "."))
    return lines if emitted else []


def _make_preload(state: ConversionState) -> List[str]:
    """Both bolt-pretension keywords, sharing ONE ``/PRELOAD`` id set.

    ``/PRELOAD`` and ``/PRELOAD/AXIAL`` are one keyword to the starter's option
    loop — ``hm_read_preload.F:110`` reads every ``/PRELOAD`` block and skips
    the AXIAL ones with ``IF (KEY(1:LEN_TRIM(KEY))=='AXIAL') CYCLE``, and
    ``hm_read_preload_axial.F90`` does the mirror image — so the two flavours
    must not reuse an id between them (#125: one memo per shared namespace,
    plus the deck-wide scan in assembly._warn_duplicate_preload_ids).
    """
    used_preload: Set[int] = set()
    body = _make_preload_sections(state, used_preload)
    body += _make_preload_axial(state, used_preload)
    if not body:
        return []
    return ["#-  BOLT PRE-TENSION (*INITIAL_STRESS_SECTION -> /PRELOAD, "
            "*INITIAL_AXIAL_FORCE_BEAM -> /PRELOAD/AXIAL):",
            HDR] + body
