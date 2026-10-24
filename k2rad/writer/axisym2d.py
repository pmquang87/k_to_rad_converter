"""R14 triage round 9, B2: an all-ELFORM-14 / 15 *SECTION_SHELL deck -> the
OpenRadioss 2-D AXISYMMETRIC deck (default ON, ``--no-axisymmetric-2d``), with
the 2-D DT2MS density cell (default ON, ``--no-positive-dt2ms-mass-scaling``).

LS-DYNA's ELFORM 14 (area-weighted) and 15 (volume-weighted) axisymmetric
shells live in the xy-plane with x the radius and y the axis of revolution
(Vol I R17 *SECTION_SHELL Remark 6) and integrate PER RADIAN. A 3-D shell
cannot reproduce that with any thickness (2Dlag's rigid body weighs
0.21994391E-03 per radian, the 3-D shell 0.0346368 = x157.5). OpenRadioss's 2-D
analysis (/ANALY N2D3D 1, ``hm_read_analy.F:78``) has the counterpart: the
/QUAD element on a /PROP/SOLID (``qinit2.F:185-195``), its volume weighted by
the radius Y (``qvoli2.F:91-96``) and its mass lumped from it
(``qmasi2.F:66``), with Radioss Y the radius and Z the axis of revolution.

The route is ONE post-pass on the emitted lines (decision B2-a): every 3-D
writer runs as before and :func:`transform_starter_lines` rewrites the cards
the 2-D deck needs, so the opt-out is simply "do not call the pass" and every
non-routed deck is byte-identical by construction. The screen
(:func:`resolve_axisym_plan`) reads the parsed deck and names EVERY failing
class (decision B2-b).
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Set, Tuple

from ..state import AxisymPlan, ConversionState

__all__ = [
    "resolve_axisym_plan",
    "transform_starter_lines",
    "transform_engine_lines",
    "axisym_routed",
    "dt0_closed_form",
]

#: the /PROP/SOLID q_b cell is written 0, which the starter turns into 0.05
#: (hm_read_prop14.F:354-355 ``IF (QB == ZERO) QB = FIVEEM2``)
_QB = 0.05
#: the starter's 2-D default time-step factor when no /DT Tsca is written
#: (contrl.F:1148 ``IF(DTFAC==ZERO.AND.N2D/=0)DTFAC=0.67``)
_F2D_DEFAULT = 0.67
#: the starter's own default hourglass coefficient for a 0 cell
#: (hm_read_prop14.F:363-366)
_H_DEFAULT = 0.1
#: the plane test's relative round-off band: a node is in the xy-plane when
#: |z| <= _PLANE_TOL x the largest absolute coordinate of the shell nodes
#: (screen 4 and the /NODE transform read the same AxisymPlan.z_tol)
_PLANE_TOL = 1.0e-9
#: the reminder line of a /TH/NODE REAC* group (writer/output.py writes it
#: for the reaction / SPCFORC / BNDOUT groups) and its 2-D reading: a 2-D
#: REAC* is per radian per unit radius (the post-review round, F14)
_REAC_PREFIX = "#  REAC* accumulates m*a*dt over the run: "
_REAC_FORCE = "force = d(REAC*)/dt"
_REAC_FORCE_2D = ("force per radian = Y_node * d(REAC*)/dt (2-D axisymmetric: "
                  "REAC* is per unit radius)")

#: ELEMENT keyword families that a 2-D deck cannot carry (screen 2)
_FAMILY_PREFIXES = (
    ("ELEMENT_SOLID", "solid"), ("ELEMENT_TSHELL", "thick-shell"),
    ("ELEMENT_BEAM", "beam"), ("ELEMENT_DISCRETE", "discrete"),
    ("ELEMENT_SEATBELT", "seatbelt"), ("ELEMENT_SPH", "SPH"),
    ("ELEMENT_MASS", "*ELEMENT_MASS"), ("ELEMENT_INERTIA", "*ELEMENT_INERTIA"),
    ("ELEMENT_PLOTEL", "plotel"),
)
#: keyword prefixes the 2-D transform has no mapping for (screen 6)
_UNMAPPED_PREFIXES = (
    "LOAD_SEGMENT", "LOAD_SHELL", "LOAD_NODE", "LOAD_BODY", "LOAD_RIGID_BODY",
    "INITIAL_VELOCITY", "RIGIDWALL", "CONTROL_ADAPTIVE",
    "PART_ADAPTIVE_FAILURE", "CONSTRAINED_",
)

#: emitted starter cards the transform leaves unchanged: no coordinate, no
#: direction, no shell reference (anything not here and not mapped below
#: aborts the transform - screen 7)
_NEUTRAL_RE = re.compile(
    r"^/(BEGIN|TITLE|IOFLAG|DEF_SOLID|DEF_SHELL|END)\s*$"
    r"|^/PART/\d+\s*$|^/MAT/[A-Z0-9_]+(/[A-Z0-9_]+)*/\d+\s*$"
    r"|^/EOS/[A-Z0-9_]+/\d+\s*$|^/HEAT/MAT/\d+\s*$"
    r"|^/THERM_STRESS/MAT/\d+\s*$|^/FUNCT(_SMOOTH)?/\d+\s*$"
    r"|^/TABLE/\d+/\d+\s*$|^/GRNOD/NODE/\d+\s*$|^/INITEMP/\d+\s*$"
    r"|^/IMPTEMP/\d+\s*$|^/TH/NODE/\d+\s*$|^/TH/PART/\d+\s*$"
    r"|^/TH/RBODY/\d+\s*$")
_THERMAL_RE = re.compile(r"^/(HEAT/MAT|INITEMP|IMPTEMP|THERM_STRESS)/")


def axisym_routed(state: ConversionState) -> bool:
    """True when the deck takes the 2-D route (and the transform has not
    aborted)."""
    plan = state.axisym_plan
    return plan is not None and plan.routed and not plan.aborted


def _axisym_parts(state: ConversionState) -> Tuple[List[int], Set[int]]:
    """``(the pids that own shell elements, the secids they use)``."""
    shell_pids = sorted({e.pid for e in state.shell_elems
                         if e.pid in state.parts})
    used = {state.parts[p].secid for p in shell_pids}
    return shell_pids, used


def _material_modulus(state: ConversionState, mid: int
                      ) -> Optional[Tuple[float, float, float]]:
    """``(E, nu, rho)`` of a converted material with an elastic pair, else
    None (a hyperelastic, a fluid EOS, an unknown id)."""
    from .thermal import _material_registries
    for reg in _material_registries(state):
        rec = reg.get(mid)
        if rec is None:
            continue
        e = getattr(rec, "E", None)
        if e is None:
            e = getattr(rec, "e", None)
        nu = getattr(rec, "nu", None)
        rho = getattr(rec, "rho", None)
        if e and nu is not None and rho and e > 0.0 and rho > 0.0 \
                and -1.0 < nu < 0.5:
            return float(e), float(nu), float(rho)
        return None
    return None


def dt0_closed_form(quads: List[List[Tuple[float, float]]], e: float,
                    nu: float, rho: float, f2d: float) -> float:
    """OpenRadioss's own cycle-0 element step of 2-D quads (spec B2.3):
    ``f2d x min_e AIRE_e / sqrt(ALMX_e) / (c (qb + sqrt(1 + qb^2)))`` with
    AIRE the quad area in the (r, z) plane (qdlen2.F:113), ALMX the largest
    squared edge or diagonal (qdlen2.F:85 / :89 / :94), c the elastic P-wave
    speed and qb 0.05 (mqviscb.F:215 / :259-260; at cycle 0 the viscous and
    velocity terms are 0)."""
    c = math.sqrt(e * (1.0 - nu) / ((1.0 + nu) * (1.0 - 2.0 * nu)) / rho)
    fac = _QB + math.sqrt(1.0 + _QB * _QB)
    best = None
    for p in quads:
        d13 = (p[2][0] - p[0][0], p[2][1] - p[0][1])
        d24 = (p[3][0] - p[1][0], p[3][1] - p[1][1])
        area = 0.5 * abs(d13[0] * d24[1] - d13[1] * d24[0])
        e2 = [(p[(k + 1) % 4][0] - p[k][0]) ** 2
              + (p[(k + 1) % 4][1] - p[k][1]) ** 2 for k in range(4)]
        g2 = [d13[0] ** 2 + d13[1] ** 2, d24[0] ** 2 + d24[1] ** 2]
        dx = area / math.sqrt(max(e2 + g2))
        if best is None or dx < best:
            best = dx
    return f2d * (best or 0.0) / (c * fac)


def resolve_axisym_plan(state: ConversionState) -> AxisymPlan:
    """The route decision (memoised on ``state.axisym_plan``; computed in
    build_starter BEFORE the writers, draws no id). A deck whose used shell
    sections include no ELFORM 14 / 15 - or a run under
    ``--no-axisymmetric-2d`` - gets an empty plan and nothing changes."""
    if state.axisym_plan is not None:
        return state.axisym_plan
    plan = AxisymPlan()
    state.axisym_plan = plan
    pids, used = _axisym_parts(state)
    secs = [state.sec_shells[s] for s in sorted(used) if s in state.sec_shells]
    elforms = sorted({s.elform for s in secs})
    if not state.options.axisymmetric_2d or not any(
            ef in (14, 15) for ef in elforms):
        return plan
    plan.candidate = True
    plan.pids = pids
    plan.elform = 15 if 15 in elforms else 14
    reasons: List[str] = []
    # 1: every used shell section ELFORM 14 or 15, never both
    if 44 in elforms:
        reasons.append("ELFORM 44 (EFG) has no Radioss 2-D element")
    other = [ef for ef in elforms if ef not in (14, 15, 44)]
    if other:
        reasons.append(f"a *SECTION_SHELL of ELFORM {other} beside the "
                       "axisymmetric ones (the route needs every used shell "
                       "section to be ELFORM 14 or 15)")
    if 14 in elforms and 15 in elforms:
        reasons.append("ELFORM 14 and 15 together (LS-DYNA forbids mixing "
                       "them, Vol I R17 p.41-66)")
    # 2: no other element family
    kws = state.deck_keywords
    fams: List[str] = []
    for prefix, family in _FAMILY_PREFIXES:
        if any(k == prefix or k.startswith(prefix + "_") for k in kws):
            fams.append(family)
    if state.solid_elems and "solid" not in fams:
        fams.append("solid")
    if state.beam_elems and "beam" not in fams:
        fams.append("beam")
    for family in fams:
        reasons.append(f"a {family} element: OpenRadioss 2-D decks carry "
                       "quads only (initia.F:953-955 ERROR 603 for solids)")
    # 3: no 3-node shell
    tri = [e.eid for e in state.shell_elems
           if len(e.nodes) == 3 or (len(e.nodes) == 4
                                    and e.nodes[2] == e.nodes[3])]
    if tri:
        reasons.append(
            f"{len(tri)} 3-node shell(s): a degenerate 2-D /QUAD creates "
            "energy (cG3 mf2dRT: IE fifths +11.50 .. +66.73 %, energy error "
            "up to 99.9 %) and a 2-D /TRIA needs LAW151 "
            "(check_mat_elem_prop_compatibility.F:141-147)")
    # 4: the section in the xy-plane, x >= 0 (element nodes). "In the plane"
    # is |z| <= _PLANE_TOL x the largest absolute coordinate: a z of round-off
    # size (the SPR main giant's node 1 sits at z = -5.55e-18, x = 0.099) is
    # in the plane, not a refusal class (the post-review round, E3)
    scale = 0.0
    for el in state.shell_elems:
        for n in el.nodes:
            p = state.nodes.get(n)
            if p is not None:
                scale = max(scale, abs(p.x), abs(p.y), abs(p.z))
    plan.z_tol = _PLANE_TOL * scale
    for el in state.shell_elems:
        bad = None
        for n in el.nodes:
            p = state.nodes.get(n)
            if p is not None and (abs(p.z) > plan.z_tol or p.x < 0.0):
                bad = (n, p)
                break
        if bad is not None:
            n, p = bad
            reasons.append(
                f"node {n} has z = {p.z:g} / x = {p.x:g}: the axisymmetric "
                "section must lie in the xy-plane with x >= 0 (Vol I R17 "
                "*SECTION_SHELL Remark 6)")
            break
    # 5: no contact
    contacts = sorted(k for k in kws if k.startswith("CONTACT_"))
    for k in contacts:
        reasons.append(
            f"*{k}: OpenRadioss 2-D decks accept only /INTER/TYPE1 / 2 / 3 / "
            "5 (hm_read_interfaces.F:175-179, ERROR 2097 otherwise) and k2rad "
            "converts no *CONTACT_2D (ROADMAP)")
    # 6: no card the transform does not map
    unmapped = sorted(k for k in kws
                      if any(k == p or k.startswith(p) for p in
                             _UNMAPPED_PREFIXES))
    for pm in state.prescribed_motions:
        # a record naming no part is not a motion the writer emits (the
        # _ID spelling's second heading line parses as one - pid 0)
        if pm.pid in state.parts and pm.dof not in (1, 2):
            unmapped.append(f"BOUNDARY_PRESCRIBED_MOTION_RIGID DOF {pm.dof}")
    for ps in state.prescribed_motion_sets:
        if ps.dof not in (1, 2):
            unmapped.append(f"BOUNDARY_PRESCRIBED_MOTION_{{NODE|SET}} DOF "
                            f"{ps.dof}")
    for k in dict.fromkeys(unmapped):
        reasons.append(
            f"*{k} has no 2-D mapping in k2rad (round 9 maps nodes, quads, "
            "/BCS, the DOF-1 / DOF-2 prescribed motions, skews, detonation "
            "points, rigid bodies and the shell time history)")
    plan.reasons = reasons
    if reasons:
        state.warn(
            f"*SECTION_SHELL ELFORM {plan.elform} on part(s) {pids}: the 2-D "
            "axisymmetric route is NOT used - " + "; ".join(reasons)
            + "; the sections stay 3-D /SHELL with Card 2's thickness T1, so "
            "their mass, inertia and stress state are NOT LS-DYNA's (LS-DYNA "
            "integrates per radian: 2Dlag 0.21994391E-03 where the 3-D shell "
            "weighs 0.0346368 = x157.5).")
        return plan
    plan.routed = True
    # the 2-D DT2MS density cell (B2.1.c; per material, add-only: B2-d)
    ts = state.ctrl_timestep
    plan.dt2ms = ts.dt2ms if ts is not None else 0.0
    plan.f2d = ts.tssfac if ts is not None and ts.tssfac > 0.0 \
        else _F2D_DEFAULT
    if plan.dt2ms > 0.0 and state.options.positive_dt2ms_mass_scaling:
        from .common import rigid_part_ids
        rigid = rigid_part_ids(state)
        quads: Dict[int, List[List[Tuple[float, float]]]] = {}
        for el in state.shell_elems:
            if el.pid in rigid or el.pid not in state.parts:
                continue
            mid = state.parts[el.pid].mid
            pts = [(state.nodes[n].x, state.nodes[n].y) for n in el.nodes[:4]
                   if n in state.nodes]
            if len(pts) == 4:
                quads.setdefault(mid, []).append(pts)
        for mid in sorted(quads):
            mod = _material_modulus(state, mid)
            if mod is None:
                plan.no_modulus.append(mid)
                continue
            dt0 = dt0_closed_form(quads[mid], mod[0], mod[1], mod[2],
                                  plan.f2d)
            if dt0 > 0.0:
                plan.dt0[mid] = dt0
                plan.density[mid] = max(1.0, (plan.dt2ms / dt0) ** 2)
        if plan.no_modulus:
            state.warn(
                f"material(s) {plan.no_modulus}: no elastic (E, nu) pair to "
                "compute the 2-D step; the density cell is not applied to "
                "them (the routed deck runs at their raw 2-D step).")
    return plan


def _node_xy(state: ConversionState, n: int) -> Tuple[float, float]:
    p = state.nodes[n]
    return (p.x, p.y)


def _prop_solid(pid: str, title: str, h: float) -> List[str]:
    """radioss2022/PROP/prop_p14_solid.cfg FORMAT(radioss2022), Isolid 2."""
    return [
        f"/PROP/SOLID/{pid}",
        title,
        "#   Isolid    Ismstr      Iale     Icpre  Itetra10     Inpts   "
        "Itetra4    Iframe                  Dn",
        "         2         0         0         0         0         0"
        "         0         0",
        "#                q_a                 q_b                   h"
        "            LAMBDA_V                MU_V",
        f"{0:20d}{0:20d}{h:20g}{0:20d}{0:20d}",
        "#             dt_min   istrain      IHKT",
        "                   0         1         0",
    ]


def _part_qh(state: ConversionState, pid: int) -> float:
    """The part's hourglass coefficient: its *HOURGLASS QM, else
    *CONTROL_HOURGLASS QH; 0 / none = the starter default 0.1."""
    part = state.parts.get(pid)
    if part is not None and part.hgid in state.hourglass_defs:
        qm = state.hourglass_defs[part.hgid].qm
        if qm > 0.0:
            return qm
    ch = state.ctrl_hourglass
    if ch is not None and ch.qh > 0.0:
        return ch.qh
    return _H_DEFAULT


def _split_blocks(lines: List[str]) -> List[List[str]]:
    out: List[List[str]] = []
    cur: Optional[List[str]] = None
    for ln in lines:
        if ln.startswith("/"):
            if cur is not None:
                out.append(cur)
            cur = [ln]
        elif cur is None:
            out.append([ln])
        else:
            cur.append(ln)
    if cur is not None:
        out.append(cur)
    return out


def _data_rows(block: List[str]) -> List[int]:
    """Indices of a block's data rows (not the header, not comments)."""
    return [i for i in range(1, len(block))
            if block[i].strip() and not block[i].startswith("#")]


class _Abort(Exception):
    pass


def _transform_starter_lines(state: ConversionState, lines: List[str],
                             plan: AxisymPlan
                             ) -> Tuple[List[str], str, Dict[str, int]]:
    """The 2-D rewrite of the emitted starter lines (spec B2.1.b), or the
    untouched lines and the reason when a card it does not map is met
    (screen 7). Returns ``(lines, abort_reason, counts)``."""
    counts = {"node": 0, "quad": 0, "flip": 0, "prop": 0, "bcs": 0,
              "imp": 0, "skew": 0, "det": 0, "rbody": 0, "th": 0, "rho": 0,
              "thermal": 0}
    prop_pids: Dict[str, int] = {}
    for pid in plan.pids:
        part = state.parts[pid]
        prop_pids.setdefault(str(part.secid), pid)
    scaled = dict(plan.density)
    out: List[str] = []
    try:
        for b in _split_blocks(lines):
            head = b[0]
            if not head.startswith("/"):
                out.extend(b)
                continue
            if head.startswith("/ANALY"):
                rows = _data_rows(b)
                if not rows or b[rows[0]][:10].strip() != "0":
                    raise _Abort(f"{head.strip()} (its N2D3D cell is not 0)")
                b = list(b)
                b[rows[0]] = "         1" + b[rows[0]][10:]
            elif head.rstrip() == "/NODE":
                nb = [head]
                for x in b[1:]:
                    if x.startswith("#") or not x.strip():
                        nb.append(x)
                        continue
                    t = x.split()
                    if len(t) != 4 or abs(float(t[3])) > plan.z_tol:
                        raise _Abort(f"/NODE {t[0] if t else '?'} (off the "
                                     "xy-plane)")
                    nb.append(f"{int(t[0]):10d}{'0':>20s}{t[1]:>20s}"
                              f"{t[2]:>20s}")
                    counts["node"] += 1
                b = nb
            elif re.match(r"^/SHELL/\d+\s*$", head):
                pid = head.split("/")[2].strip()
                nb = [f"/QUAD/{pid}"]
                for x in b[1:]:
                    if x.startswith("#") or not x.strip():
                        nb.append(x)
                        continue
                    t = x.split()
                    eid = int(t[0])
                    ns = [int(v) for v in t[1:5]]
                    if len(ns) != 4 or ns[2] == ns[3]:
                        raise _Abort(f"/SHELL/{pid} element {eid} (not a "
                                     "4-node quad)")
                    pts = [_node_xy(state, n) for n in ns]
                    a2 = sum(pts[i][0] * pts[(i + 1) % 4][1]
                             - pts[(i + 1) % 4][0] * pts[i][1]
                             for i in range(4))
                    if a2 == 0.0:
                        raise _Abort(f"/SHELL/{pid} element {eid} (zero "
                                     "area)")
                    if a2 < 0.0:
                        ns = [ns[0], ns[3], ns[2], ns[1]]
                        counts["flip"] += 1
                    nb.append("".join(f"{v:10d}" for v in [eid] + ns))
                    counts["quad"] += 1
                b = nb
            elif re.match(r"^/PROP/SHELL/\d+\s*$", head):
                prop = head.split("/")[3].strip()
                title = b[1] if len(b) > 1 else f"PROP_{prop}"
                trailing: List[str] = []
                for x in reversed(b):
                    if x.startswith("#") or not x.strip():
                        trailing.insert(0, x)
                    else:
                        break
                h = _part_qh(state, prop_pids.get(prop, 0))
                b = _prop_solid(prop, title, h) + trailing
                counts["prop"] += 1
            elif re.match(r"^/BCS/\d+\s*$", head):
                # The node map is the cyclic permutation P(v) = (vz, vx, vy),
                # a proper rotation. A GLOBAL code holds LS (x, y, z) DOFs,
                # so its translation AND rotation digits move with P: (dx,
                # dy, dz) -> (dz, dx, dy). A SKEWED code holds the axes of
                # its /SKEW/FIX, whose vectors the /SKEW/FIX branch below
                # rotates by P - its local axes ARE the images of LS's
                # local axes (P(y') x P(z') = P(x')), so its digits stay.
                # (The fix round: the round-9 rewrite permuted the Tra
                # digits of every /BCS, skewed too, and no rot digit.)
                nb = list(b)
                for i in _data_rows(b)[1:]:
                    m = re.match(r"^(\s*)([01]{3})(\s+)([01]{3})(.*)$", nb[i])
                    if not m:
                        raise _Abort(f"{head.strip()} (an unreadable Tra / rot "
                                     "row)")
                    tail = m.group(5).split()
                    try:
                        skew = int(tail[0]) if tail else 0
                    except ValueError:
                        raise _Abort(f"{head.strip()} (an unreadable skew "
                                     "cell)")
                    if skew != 0:
                        counts["bcs_skewed"] = counts.get("bcs_skewed", 0) + 1
                        continue
                    t_, r_ = m.group(2), m.group(4)
                    nb[i] = (m.group(1) + t_[2] + t_[0] + t_[1] + m.group(3)
                             + r_[2] + r_[0] + r_[1] + m.group(5))
                    counts["bcs"] += 1
                b = nb
            elif re.match(r"^/IMP(DISP|VEL|ACC)/\d+\s*$", head):
                nb = list(b)
                rows = _data_rows(b)
                row = next((i for i in rows if len(nb[i].split()) >= 2
                            and nb[i][10:20].strip() in
                            ("X", "Y", "Z", "XX", "YY", "ZZ")), None)
                if row is None:
                    raise _Abort(f"{head.strip()} (no direction cell)")
                d = nb[row][10:20].strip()
                if d not in ("X", "Y"):
                    raise _Abort(f"{head.strip()} (direction {d})")
                nb[row] = nb[row][:10] + f"{'Y' if d == 'X' else 'Z':>10s}" \
                    + nb[row][20:]
                counts["imp"] += 1
                b = nb
            elif re.match(r"^/SKEW/FIX/\d+\s*$", head):
                nb = list(b)
                rows = _data_rows(b)
                for i in rows[1:4]:
                    t = nb[i].split()
                    if len(t) < 3:
                        raise _Abort(f"{head.strip()} (an unreadable vector)")
                    nb[i] = f"{t[2]:>20s}{t[0]:>20s}{t[1]:>20s}" + nb[i][60:]
                counts["skew"] += 1
                b = nb
            elif re.match(r"^/DFS/DETPOINT/\d+\s*$", head):
                nb = list(b)
                rows = _data_rows(b)
                if not rows:
                    raise _Abort(f"{head.strip()} (no point row)")
                i = rows[0]
                t = nb[i][:60].split()
                if len(t) < 3:
                    raise _Abort(f"{head.strip()} (an unreadable point)")
                nb[i] = f"{t[2]:>20s}{t[0]:>20s}{t[1]:>20s}" + nb[i][60:]
                counts["det"] += 1
                b = nb
            elif re.match(r"^/RBODY/\d+\s*$", head):
                nb = list(b)
                for i in range(len(nb) - 1):
                    if nb[i].startswith("#") and ("Jxx" in nb[i]
                                                  or "Jxy" in nb[i]):
                        nb[i + 1] = f"{0:20d}{0:20d}{0:20d}"
                counts["rbody"] += 1
                b = nb
            elif re.match(r"^/TH/SHEL/\d+\s*$", head):
                b = ["/TH/QUAD/" + head.split("/")[3].strip()] + b[1:]
                counts["th"] += 1
            elif re.match(r"^/TH/NODE/\d+\s*$", head) and any(
                    x.startswith(_REAC_PREFIX) for x in b):
                # the post-review round (F14): a 2-D nodal mass is per
                # radian PER UNIT RADIUS (fixvel.F:361 weighs the imposed
                # motion's work by AXI = Y), so the reminder's force reading
                # takes the node's radius
                b = [x.replace(_REAC_FORCE, _REAC_FORCE_2D)
                     if x.startswith(_REAC_PREFIX) else x for x in b]
                counts["reac"] = counts.get("reac", 0) + 1
            elif re.match(r"^/AMS(/\d+)?\s*$", head):
                # --ams: the starter half of /DT/AMS, which a 2-D deck never
                # carries (resol.F:2711-2729; the engine half is dropped by
                # transform_engine_lines) - the block is left out
                counts["ams"] = counts.get("ams", 0) + 1
                continue
            elif re.match(r"^/MAT/", head) and _NEUTRAL_RE.match(head):
                mid = int(head.rstrip().split("/")[-1])
                if mid in scaled:
                    nb = list(b)
                    rows = _data_rows(b)
                    if len(rows) < 2:
                        raise _Abort(f"{head.strip()} (no RHO_I row)")
                    i = rows[1]                 # rows[0] is the title line
                    rho = float(nb[i][:20])
                    nb[i] = f"{rho * scaled[mid]:20.6E}" + nb[i][20:]
                    counts["rho"] += 1
                    b = nb
            elif _NEUTRAL_RE.match(head):
                if _THERMAL_RE.match(head):
                    counts["thermal"] += 1
            else:
                raise _Abort(head.strip())
            out.extend(b)
    except _Abort as exc:
        return lines, str(exc), counts
    return out, "", counts


def transform_starter_lines(state: ConversionState,
                            lines: List[str]) -> List[str]:
    """Apply the 2-D route to the emitted starter (a no-op unless routed).
    Writes the routed sentence (a), the density sentence (b) and the thermal
    sentence (g), or the screen-7 sentence when the transform aborts."""
    plan = state.axisym_plan
    if plan is None or not plan.routed:
        return lines
    flat = "\n".join(lines).split("\n")
    new, why, c = _transform_starter_lines(state, flat, plan)
    if why:
        plan.aborted = True
        state.warn(
            f"*SECTION_SHELL ELFORM {plan.elform}: the 2-D transform met "
            f"{why}, which it does not map; the deck keeps the 3-D route (its "
            "/RBODY J rows carry no -SUM(IN) correction: the route had been "
            "decided before the transform ran).")
        return lines
    qh = sorted({_part_qh(state, p) for p in plan.pids})
    state.warn(
        f"*SECTION_SHELL ELFORM {plan.elform} on part(s) {plan.pids} -> the "
        "2-D AXISYMMETRIC route (/ANALY N2D3D 1): every node (x, y, 0) is "
        "written (0, x, y) - Radioss Y = LS x = the radius, Radioss Z = LS y "
        "= the axis of revolution (Reference Guide: 'Y is the radial "
        f"direction and Z is the axis of revolution') - {c['quad']} /SHELL "
        f"become /QUAD ({c['flip']} re-ordered counter-clockwise) on "
        f"/PROP/SOLID Isolid 2 (h {', '.join(f'{h:g}' for h in qh)}), the "
        "/BCS and the prescribed-motion directions are permuted the same "
        "way, rigid bodies get J = 0 (a 2-D rigid body's inertia is its "
        "members' I_xx = I_yy + I_zz, inirby.F:366-398) and the shell time "
        "history is /TH/QUAD. Masses and energies are per radian in both "
        "codes (LS d3hsp 'for 2D axisymmetric problems the following masses "
        "are reported per radian'; OpenRadioss qvoli2.F:91-96 weights the "
        "volume by Y). The /TH/NODE channels keep Radioss's names: their Y is "
        "the radius and Z the axis."
        + (" Their reaction channels (REAC*) are per radian PER UNIT RADIUS "
           "(fixvel.F:361 weighs the imposed motion's work by AXI = Y): the "
           "per-radian force of a node is Y_node x d(REAC*)/dt, 0 on the axis "
           "- not the d(REAC*)/dt a 3-D deck reads."
           if c.get("reac") else "")
        + " Both ELFORM 14 and 15 run as "
        "OpenRadioss's area-weighted quad (QFORC2; the volume-weighted branch "
        "is not reachable from input, hm_read_prop14.F:247-250). MEASURED on "
        "thermal/metal-forming/metal-forming.k (nt 4): starter TOTAL MASS "
        "5.7080700E-06 = LS-DYNA's 0.57080700E-05 per radian (the 3-D route: "
        "1.26846E-06); 2Dlag (giant, starter only): ERROR 3046 cleared, its "
        "rigid body 0.2199439E-03 = LS-DYNA (the 3-D shell 0.0346368). "
        "--no-axisymmetric-2d keeps the 3-D shells.")
    if plan.density:
        mids = sorted(plan.density)
        f = plan.density[mids[0]]
        dt0 = plan.dt0[mids[0]]
        state.warn(
            f"*CONTROL_TIMESTEP DT2MS {plan.dt2ms:g} > 0 on the routed 2-D "
            f"deck: the density of material(s) {mids} is multiplied by (DT2MS "
            f"/ dt0)^2 = {f:.6g} with dt0 = {dt0:.6e} s, OpenRadioss's own "
            f"cycle-0 step of these quads ({plan.f2d:g} x min(area / longest "
            "edge or diagonal) / (c (qb + sqrt(1 + qb^2))), qdlen2.F:113, "
            "mqviscb.F:259-260, starter contrl.F:1148), so the run starts at "
            "DT2MS - LS-DYNA's own scaled / physical mass ratio is not "
            "computable at conversion (metal-forming: LS-DYNA 85901, its "
            "element step gives 53026). /DT/NODA/CST is never written on a 2-D "
            "deck: resol.F:2711-2729 rebuilds the 2-D nodal masses every cycle "
            "(measured there: energy error +99.9 % at every fifth). "
            "OpenRadioss's KE is then the SCALED-mass KE while LS-DYNA's glstat "
            "KE is the physical one. MEASURED on metal-forming (nt 4, the 500 "
            "LS times in (0.0032, 1.6], the fifths at k x 1.6 / 5): NORMAL in "
            "24 807 cycles, 30.5 s (the 3-D row: a timeout at t 0.2075 of "
            "1.6), IE END -0.45 %, fifths +0.01 / -0.20 / -0.38 / -0.53 / "
            "-0.45 %, RMS 0.24 % of the LS peak (LS-DYNA's own ratio x85901: "
            "IE END -0.20 %, RMS 0.21 % in 38 304 cycles). "
            "--no-positive-dt2ms-mass-scaling keeps the physical density."
            + (" Per material: " + "; ".join(
                f"{m}: dt0 {plan.dt0[m]:.6e} s, x {plan.density[m]:.6g}"
                for m in mids) if len(mids) > 1 else ""))
    if c["thermal"]:
        state.warn(
            "the 2-D axisymmetric deck keeps its thermal cards, but "
            "OpenRadioss has no 2-D heat conduction (the conduction routines "
            "are called from the 3-D solid and shell elements only): "
            "temperatures move only through imposed temperatures and fluxes "
            "on their own nodes.")
    return new


def transform_engine_lines(state: ConversionState,
                           lines: List[str]) -> List[str]:
    """On a routed deck drop /DT/NODA/CST and /DT/AMS (resol.F:2711-2729
    rebuilds the 2-D nodal masses every cycle) with sentence (f)."""
    if not axisym_routed(state):
        return lines
    out: List[str] = []
    skip = False
    dropped = False
    for ln in lines:
        if ln.startswith("/"):
            skip = ln.startswith("/DT/NODA/CST") or ln.startswith("/DT/AMS")
            dropped = dropped or skip
        if not skip:
            out.append(ln)
    plan = state.axisym_plan
    if dropped and plan is not None and not plan.engine_dt_dropped:
        plan.engine_dt_dropped = True
        state.warn(
            f"*CONTROL_TIMESTEP DT2MS {plan.dt2ms:g} < 0 on the routed 2-D "
            "deck: /DT/NODA/CST is NOT written (resol.F:2711-2729 rebuilds "
            "the 2-D nodal masses every cycle; measured on metal-forming's 2-D "
            "arm: energy error +99.9 % at every fifth) and no density cell "
            "replaces it (LS-DYNA's LT.0 rule adds mass element by element); "
            "the deck runs at its raw 2-D step.")
    return out
