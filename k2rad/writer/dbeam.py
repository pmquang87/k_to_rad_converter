"""Discrete beams: *SECTION_BEAM ELFORM=6 -> 6-DOF /SPRING connectors.

An LS-DYNA "discrete beam" is not a beam at all: the section card carries only a
lumped ``VOL``/``INER`` and the material states a stiffness (or a load curve) per
LOCAL DOF. The Radioss counterpart is a 6-DOF spring property:

  * ``/PROP/TYPE8`` (SPR_GENE)  — SKEW oriented. ``r2buf3.F`` builds the local
    triad entirely from a skew (per-element ``/SPRING`` ``Skew_ID`` first, then
    the property ``skew_ID``, then global). This is where a ``*SECTION_BEAM``
    ``CID`` belongs.
  * ``/PROP/TYPE13`` (SPR_BEAM) — NODE oriented. ``r4buf3.F:145`` sets local X
    along ``node_ID1 -> node_ID2`` and takes the XY plane from ``node_ID3``,
    falling back to the property skew's Y'.

Those two card bodies are byte-identical to ``/MAT/LAW108`` and ``/MAT/LAW113``
respectively, with an absolute ``Mass``/``Inertia`` in place of ``RHO`` and the
``/PROP/TYPE23`` ``Volume``. dyna2rad emits the mat-driven pair (LAW108 or
LAW113 on a TYPE23, `convertmats.cxx:3359-3376` switching on ``SCOOR = +/-2``);
k2rad emits the property-driven twin, which behaves identically and avoids
TYPE23's extra rule that the ``/PART`` must carry a MID whose law is
108/113/114/135 (``hm_read_part.F``, ERROR 179 and ERROR 1715).

Frame choice — the ONE rule, stated positively rather than as dyna2rad's law
switch:

  * ``|SCOOR| == 2`` means "the local r-axis is realigned along n1->n2"
    (Manual Vol I R17, *SECTION_BEAM card 1) — that IS ``/PROP/TYPE13``. It is
    also what *MAT_066/067/068/196 require for a finite-length discrete beam,
    and exactly the test dyna2rad uses to pick LAW113.
  * otherwise a resolvable ``CID`` gives a real triad -> ``/PROP/TYPE8`` with
    that ``/SKEW``.
  * otherwise ``/PROP/TYPE13``, because with no CID a TYPE8 would silently fall
    back to the GLOBAL axes. dyna2rad has that hole (``convertprops.cxx:1471``
    leaves ``skew_ID`` 0 when the id does not resolve); k2rad promotes and says
    so instead.
  * ``*MAT_CABLE_DISCRETE_BEAM`` and ``*MAT_ELASTIC_SPRING_DISCRETE_BEAM`` are
    always ``/PROP/TYPE13`` (both are axial 1-DOF springs acting along the
    element; dyna2rad likewise forces LAW113 for them).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Tuple

from ..state import ConversionState, BeamElem
from .common import HDR, _i, _discrete_beam_pids
from .loads import (
    SpringDof, _curve_slope_at_origin, _emit_funct, _emit_prop_type8,
    _emit_prop_type13, _plastic_to_total_disp,
)

__all__ = [
    "_UNMAPPED_DISCRETE_BEAM_LOSS",
    "_odd_extend_curve",
    "_dbeam_unload_hflag",
    "_dbeam_failure",
    "_make_discrete_beam_connectors",
]

#: Token mass/inertia for a connector whose section states none. Same value the
#: discrete-spring and spotweld connectors use: big enough to clear
#: hm_read_prop04's 1e-15 floor and the WARNING 445 inertia clamp, small enough
#: to be invisible in the model's total mass.
_TOKEN_MASS = 1.0e-4
_TOKEN_INERTIA = 1.0e-6

#: What each dyna2rad-unmapped discrete-beam material actually models, so the
#: warn-drop can name the physics that is lost instead of just the keyword.
#: None of these has a Radioss spring counterpart: dyna2rad routes them to its
#: ``default:`` branch, which builds the target card name by POINTER ARITHMETIC
#: on a string literal (``convertutils.cxx:1011``) and produces no usable /MAT,
#: silently (the unsupported-material error at convertmats.cxx:530 is commented
#: out).
_UNMAPPED_DISCRETE_BEAM_LOSS = {
    "MAT_069": ("*MAT_SID_DAMPER_DISCRETE_BEAM", "the tabulated orifice/piston "
                "damper (ST/D/R/H bleed geometry, per-orifice scale factors "
                "and the fluid compressibility)"),
    "MAT_070": ("*MAT_HYDRAULIC_GAS_DAMPER_DISCRETE_BEAM", "the "
                "hydraulic+gas strut law (CO gas constant, N polytropic "
                "exponent, orifice area vs. stroke curve and the "
                "clearance/return factors)"),
    "MAT_093": ("*MAT_ELASTIC_6DOF_SPRING_DISCRETE_BEAM", "the 6-DOF "
                "elastic spring with its own per-DOF unloading and the "
                "SCOOR-driven co-rotational update"),
    "MAT_094": ("*MAT_INELASTIC_SPRING_DISCRETE_BEAM", "the 1-DOF inelastic "
                "spring with tension/compression yield offsets"),
    "MAT_095": ("*MAT_INELASTIC_6DOF_SPRING_DISCRETE_BEAM", "the 6-DOF "
                "inelastic spring with per-DOF yield offsets"),
    "MAT_097": ("*MAT_GENERAL_JOINT_DISCRETE_BEAM", "the penalty-stiffness "
                "general joint (translational/rotational DOF release flags "
                "plus the joint damping) - model it as a "
                "*CONSTRAINED_JOINT_*, which k2rad converts to /PROP/TYPE45"),
    "MAT_146": ("*MAT_1DOF_GENERALIZED_SPRING", "the generalized 1-DOF spring "
                "acting between two arbitrary nodal DOFs (DOFN1/DOFN2 on "
                "*SECTION_BEAM card 2g)"),
}


def _odd_extend_curve(pts):
    """Extend a one-sided force-displacement curve by ODD symmetry.

    A discrete-beam loading curve given only for positive deformation has to
    reach into the third quadrant, because Radioss reads a spring function over
    the whole deformation range and extrapolates the end segments. dyna2rad
    mirrors it through the origin (``convertmats.cxx:3611-3621``); the result is
    the antisymmetric continuation ``F(-d) = -F(d)``, which is what a symmetric
    spring does.

    A curve that already carries negative abscissae is returned unchanged.
    """
    pts = sorted((float(a), float(o)) for a, o in pts)
    if len(pts) < 2 or pts[0][0] < 0.0:
        return pts
    return [(-a, -o) for a, o in reversed(pts) if a != 0.0] + pts


def _clamp_tension_only(pts):
    """Clamp a shifted cable curve at zero force, inserting the exact crossing.

    ``*MAT_071``'s force law is ``F = max(F0 + K·strain, 0)`` — the ``max``
    is what makes a cable go SLACK. A plain ordinate shift by F0 (what dyna2rad
    writes, ``convertmats.cxx:4205``) loses it and leaves the cable PUSHING with
    F0 in compression. Walking the points and cutting them at the zero crossing
    reproduces the clamp exactly on a piecewise-linear function."""
    out = []
    prev = None
    for a, o in pts:
        if prev is not None:
            pa, po = prev
            if (po < 0.0) != (o < 0.0) and o != po:
                x0 = pa + (a - pa) * (0.0 - po) / (o - po)
                if out and x0 > out[-1][0]:
                    out.append((x0, 0.0))
        out.append((a, max(o, 0.0)))
        prev = (a, o)
    return out


def _shift_curve(pts, dy: float):
    """Add a constant force/moment *dy* to every ordinate — the discrete-beam
    preload (FOR/FOS/FOT/MOR/MOS/MOT, MAT_071's F0, MAT_074's F0).

    dyna2rad passes the preload as ``CreateCurve``'s y-offset for MAT_067/071/
    074 but as its X-offset for MAT_068 and MAT_196 (a 7-argument call where an
    8-argument one was meant, ``convertmats.cxx:3827`` and ``:6603``), which
    shifts the DISPLACEMENT by a force. k2rad shifts the ordinate everywhere."""
    return [(a, o + dy) for a, o in pts]


def _dbeam_unload_hflag(iunld: int) -> int:
    """LS-DYNA ``IUNLD``/``UNLDOPT`` -> the Radioss spring hardening flag H.

    ==== ============================================ =====================
    IUNLD LS-DYNA meaning                              H
    ==== ============================================ =====================
    0     load and unload on the loading curve         0  elastic
    1     unload on a separate unloading curve         6  iso. hardening +
                                                          nonlinear unloading
    2     unload along KT/KR to the unloading curve    7  elastic hysteresis
    3     quadratic unload to a permanent offset       5  uncoupled nonlinear
                                                          (un)reloading
    ==== ============================================ =====================

    dyna2rad maps 3 only for MAT_121 (``convertmats.cxx:6062``) and leaves
    MAT_119's IUNLD=3 unmapped, so its springs come out purely elastic; the same
    LS-DYNA option means the same thing on both cards, so k2rad maps both.

    H=4 (kinematic) is deliberately never emitted: ``hm_read_mat108.F:164``
    rejects it unconditionally (ERROR 230) and ``hm_read_prop04.F:157`` rejects
    it whenever K=0.
    """
    return {0: 0, 1: 6, 2: 7, 3: 5}.get(iunld, 0)


def _apply_unload_guard(state: ConversionState, label: str, dof: SpringDof,
                        slot: int) -> None:
    """Demote a hardening flag whose required curves are missing.

    ``hm_read_prop04.F:150-201`` (and the identical block in prop08/prop13 and
    hm_read_mat108.F) makes these HARD errors, so the guard has to run before
    the card is written or the deck cannot start:

      * H=5 with fct_ID1 or fct_ID3 blank  -> ERROR 231
      * H=6 with fct_ID1 or fct_ID3 blank  -> ERROR 1057
      * H=7 with fct_ID1 blank             -> ERROR 1058
      * H=7 with fct_ID3 blank             -> WARNING 1059, H silently -> 2
    """
    if dof.h in (5, 6) and (not dof.fct1 or not dof.fct3):
        state.warn(
            f"{label}: DOF {slot} asks for H={dof.h} (unloading on a separate "
            "curve) but "
            + ("the loading curve is blank" if not dof.fct1
               else "no unloading curve is given")
            + " — H=5/6 without both functions is starter ERROR "
            + ("231" if dof.h == 5 else "1057")
            + ", so the DOF was DEMOTED to H=0 (nonlinear elastic: it unloads "
            "along the loading curve and dissipates nothing).")
        dof.h = 0
    elif dof.h == 7 and not dof.fct1:
        state.warn(f"{label}: DOF {slot} asks for H=7 (elastic hysteresis) "
                   "with no loading curve — that is starter ERROR 1058, so "
                   "the DOF was DEMOTED to H=0 (linear elastic on K).")
        dof.h = 0


def _dbeam_failure(disp: List[float], force: List[float],
                   disp_first: bool) -> Tuple[int, List[Tuple[float, float]]]:
    """(Ifail2, per-DOF (min, max)) from a discrete beam's two failure card
    pairs.

    LS-DYNA states one limit per DOF and uses it in both directions; Radioss
    wants a signed interval, and its CFG constrains ``MIN_RUP <= 0``. The
    interval is therefore ``(-|v|, +|v|)`` — dyna2rad writes ``(-v, +v)``, so a
    negative input inverts its interval there.

    Which pair wins is a real dyna2rad inconsistency: MAT_067 prefers the
    DISPLACEMENT limits (``convertmats.cxx:3680``) and MAT_068 the FORCE ones
    (``:3848``), and 067 tests ``sum > 0`` (so mixed signs can cancel and
    suppress the whole block) where 068 tests ``any != 0``. k2rad always tests
    "any non-zero" and keeps each material's documented priority via
    *disp_first*.

    Ifail2: 1 = displacement/rotation criterion, 2 = force/moment. 0 = none.
    """
    order = ((disp, 1), (force, 2)) if disp_first else ((force, 2), (disp, 1))
    for vals, ifail2 in order:
        if any(v != 0.0 for v in vals):
            return ifail2, [(-abs(v), abs(v)) if v else (0.0, 0.0)
                            for v in vals]
    return 0, [(0.0, 0.0)] * 6


def _mean_beam_length(state: ConversionState, beams: List[BeamElem]) -> float:
    lens = []
    for e in beams:
        a, b = state.nodes.get(e.n1), state.nodes.get(e.n2)
        if a is not None and b is not None:
            lens.append(((a.x - b.x) ** 2 + (a.y - b.y) ** 2
                         + (a.z - b.z) ** 2) ** 0.5)
    return (sum(lens) / len(lens)) if lens else 0.0


def _resolve_inertia(state: ConversionState, label: str, iner: float,
                     vol: float, mass: float, length: float) -> float:
    """*SECTION_BEAM card 2f ``INER`` -> the spring property's Inertia.

    ``-1.0`` means "compute it as a solid sphere of volume VOL" and ``-2.0``
    (MAT_196 only) "pick it so the rotational time step matches the
    translational one" (Manual Vol I R17 p.41-20). Radioss has neither
    shortcut, so both are resolved here: the sphere exactly, the auto value as
    the lumped ``m·L²/12`` the other connectors use, with a warning."""
    if iner > 0.0:
        return iner
    if iner <= -0.5 and iner > -1.5 and vol > 0.0 and mass > 0.0:
        r = (3.0 * vol / (4.0 * math.pi)) ** (1.0 / 3.0)
        i = 0.4 * mass * r * r
        state.warn(f"{label}: INER=-1 (rotary inertia of a SOLID SPHERE of "
                   f"volume VOL={vol:g}) was resolved to {i:.6G} — sphere "
                   f"radius {r:.6G} with the lumped mass {mass:.6G}. Radioss "
                   "has no equivalent shortcut, so the number is baked into "
                   "the property.")
        return i
    if iner <= -1.5:
        i = max(mass * length * length / 12.0, _TOKEN_INERTIA)
        state.warn(f"{label}: INER={iner:g} (let LS-DYNA pick the inertia so "
                   "the rotational time step matches the translational one) "
                   f"has no Radioss equivalent — the lumped m·L²/12 = {i:.6G} "
                   "was used instead. Check the rotational time step in the "
                   "starter's element table if the connector governs it.")
        return i
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Per-material payload builders. Each returns (dofs, ifail, ifail2, ileng,
# funct_lines, kind) or None when the material cannot be converted.
# ─────────────────────────────────────────────────────────────────────────────

def _dof_label(i: int) -> str:
    return ("Tx (r)", "Ty (s)", "Tz (t)", "Rx (r)", "Ry (s)", "Rz (t)")[i]


def _build_mat066(state, label, mat, fid_alloc):
    """*MAT_066 — linear stiffness + damping per DOF; a non-zero preload
    becomes a 2-point stiffness function whose y-intercept IS the preload
    (dyna2rad convertmats.cxx:3392-3451)."""
    dofs = [SpringDof(k=mat.k[i], c=mat.c[i]) for i in range(6)]
    funct: List[str] = []
    for i in range(6):
        p = mat.preload[i]
        if not p:
            continue
        fid = fid_alloc()
        funct += _emit_funct(fid, f"MAT066_preload_dof{i + 1}_mid{mat.mid}",
                             [(0.0, p), (1.0, mat.k[i] + p)])
        dofs[i].fct1 = fid
        state.warn(f"{label}: DOF {i + 1} {_dof_label(i)} carries a preload of "
                   f"{p:.6G}, which no Radioss spring field holds — it was "
                   f"baked into /FUNCT/{fid}, a 2-point line of slope "
                   f"K={mat.k[i]:.6G} through (0, {p:.6G}). Radioss "
                   "extrapolates the last segment, so the stiffness continues "
                   "past the second point.")
    return dofs, 0, 0, funct, "linear elastic discrete beam"


def _build_mat067(state, label, mat, fid_alloc, curves):
    """*MAT_067 — a loading curve and a damping curve per DOF, plus the
    FFAIL/MFAIL and UFAIL/TFAIL limit pairs."""
    dofs = [SpringDof() for _ in range(6)]
    funct: List[str] = []
    slope_dofs = []
    for i in range(6):
        lcid = mat.lcid[i]
        p = mat.preload[i]
        if lcid:
            crv = curves.get(lcid)
            if crv is not None and len(crv.pts) >= 2:
                # MAT_067 states NO stiffness at all, and a Radioss spring with
                # K=0 contributes zero nodal stiffness to the explicit time
                # step (r1len3.F:81-105 only fills STI when XK or XC is
                # non-zero). With H=0 the force comes entirely from the
                # function, so K is free to carry the tangent at the origin —
                # which is what LS-DYNA itself uses to size the discrete beam's
                # time step. dyna2rad leaves it 0.
                slope = abs(_curve_slope_at_origin(crv))
                if slope > 0.0:
                    dofs[i].k = slope
                    slope_dofs.append(i + 1)
            if crv is None or len(crv.pts) < 2:
                state.warn(f"{label}: DOF {i + 1} {_dof_label(i)} loading curve "
                           f"{lcid} is not defined — that DOF carries NO force "
                           "at all (K is 0 on this material).")
            elif p or crv.pts[0][0] >= 0.0:
                pts = _odd_extend_curve(crv.pts)
                mirrored = len(pts) != len(crv.pts)
                if p:
                    pts = _shift_curve(pts, p)
                fid = fid_alloc()
                funct += _emit_funct(
                    fid, f"MAT067_dof{i + 1}_lc{lcid}_mid{mat.mid}", pts)
                dofs[i].fct1 = fid
                state.warn(
                    f"{label}: DOF {i + 1} {_dof_label(i)} loading curve "
                    f"{lcid} -> /FUNCT/{fid}"
                    + (" (mirrored through the origin so it spans compression "
                       "as well — Radioss extrapolates the end segments)"
                       if mirrored else "")
                    + (f" with the preload {p:.6G} added to every ordinate"
                       if p else "") + ".")
            else:
                dofs[i].fct1 = lcid
        elif p:
            state.warn(f"{label}: DOF {i + 1} {_dof_label(i)} has a preload "
                       f"{p:.6G} but no loading curve — the preload is "
                       "DROPPED (there is nothing to shift, and this material "
                       "has no stiffness field).")
        if mat.lcid_damp[i]:
            dofs[i].fct4 = mat.lcid_damp[i]
            dofs[i].hscale = 1.0
    ifail2, limits = _dbeam_failure(mat.ufail, mat.ffail, disp_first=True)
    for i in range(6):
        dofs[i].dmin, dofs[i].dmax = limits[i]
    if slope_dofs:
        state.warn(f"{label}: MAT_067 states no stiffness, so DOF(s) "
                   f"{slope_dofs} took K from the SLOPE OF THE LOADING CURVE "
                   "AT THE ORIGIN. With H=0 the force still comes entirely "
                   "from the function — K only feeds the explicit time step, "
                   "which a K=0 spring would not contribute to at all.")
    return dofs, (1 if ifail2 else 0), ifail2, funct, \
        "nonlinear elastic discrete beam"


def _build_mat068(state, label, mat, fid_alloc, curves):
    """*MAT_068 — MAT_066's K/C plus a PLASTIC-displacement yield curve per DOF
    (H=1, isotropic hardening). The curve is only emitted where the DOF has a
    stiffness, because the plastic->total conversion divides by it."""
    dofs = [SpringDof(k=mat.k[i], c=mat.c[i]) for i in range(6)]
    funct: List[str] = []
    for i in range(6):
        lcid = mat.lcp[i]
        if not lcid:
            continue
        crv = curves.get(lcid)
        if crv is None or len(crv.pts) < 2:
            state.warn(f"{label}: DOF {i + 1} {_dof_label(i)} yield curve "
                       f"{lcid} is not defined — that DOF stays LINEAR "
                       f"ELASTIC on K={mat.k[i]:.6G}.")
            continue
        if mat.k[i] == 0.0:
            state.warn(f"{label}: DOF {i + 1} {_dof_label(i)} has yield curve "
                       f"{lcid} but K=0, so the elastic part F/K of the "
                       "plastic-displacement abscissa is undefined — the "
                       "curve is DROPPED and that DOF carries no force. Give "
                       "the DOF a stiffness.")
            continue
        pts = _plastic_to_total_disp(crv.pts, mat.k[i])
        if not pts:
            state.warn(f"{label}: DOF {i + 1} {_dof_label(i)} yield curve "
                       f"{lcid} could not be converted from plastic to total "
                       "displacement — the DOF stays LINEAR ELASTIC.")
            continue
        if mat.preload[i]:
            pts = _shift_curve(pts, mat.preload[i])
        fid = fid_alloc()
        funct += _emit_funct(fid, f"MAT068_dof{i + 1}_lc{lcid}_mid{mat.mid}",
                             pts)
        dofs[i].fct1 = fid
        dofs[i].h = 1
        state.warn(
            f"{label}: DOF {i + 1} {_dof_label(i)} yield curve {lcid} is given "
            "against PLASTIC displacement; every abscissa gained the elastic "
            f"part F/K (K={mat.k[i]:.6G}) and the curve was mirrored through "
            f"the origin -> /FUNCT/{fid}, H=1 (isotropic hardening, unloading "
            "along K)"
            + (f", with the preload {mat.preload[i]:.6G} added to every "
               "ordinate" if mat.preload[i] else "") + ".")
    ifail2, limits = _dbeam_failure(mat.ufail, mat.ffail, disp_first=False)
    for i in range(6):
        dofs[i].dmin, dofs[i].dmax = limits[i]
    if mat.ryld:
        state.warn(f"{label}: RYLD={mat.ryld:g} (the yield-force scale that "
                   "LS-DYNA applies on top of the LCPD*/LCPM* curves) has no "
                   "Radioss spring slot — DROPPED. Pre-scale the curve "
                   "ordinates by RYLD if it is not 1.")
    return dofs, (1 if ifail2 else 0), ifail2, funct, \
        "nonlinear plastic discrete beam"


def _build_mat071(state, label, mat, sec, fid_alloc, curves):
    """*MAT_071 cable — a TENSION-ONLY axial spring on DOF 1, Ileng=1.

    ``E < 0`` means the value already IS the stiffness; otherwise K = E·CA with
    CA from the *SECTION_BEAM card 2f. With ``Ileng=1`` the stiffness, the
    curve abscissae and the mass are all per unit length, which is exactly
    LS-DYNA's cable formulation (F = E·A·strain)."""
    if mat.e < 0.0:
        k = abs(mat.e)
    else:
        k = mat.e * sec.ca
        if sec.ca <= 0.0:
            state.warn(f"{label}: E={mat.e:g} > 0 means the stiffness is E·CA, "
                       f"but *SECTION_BEAM {sec.secid} card 2f gives CA="
                       f"{sec.ca:g} — the cable gets ZERO stiffness. Fill in "
                       "CA (the cable cross-section area), or state a negative "
                       "E to give the stiffness directly.")
    funct: List[str] = []
    fid = 0
    keep_f0 = mat.f0 != 0.0 and mat.tmaxf0 == 0.0
    if mat.lcid and mat.lcid in curves and len(curves[mat.lcid].pts) >= 2:
        if keep_f0:
            fid = fid_alloc()
            funct += _emit_funct(
                fid, f"MAT071_cable_lc{mat.lcid}_mid{mat.mid}",
                _clamp_tension_only(
                    _shift_curve(sorted(curves[mat.lcid].pts), mat.f0)))
        else:
            fid = mat.lcid
    else:
        if mat.lcid:
            state.warn(f"{label}: force-vs-engineering-strain curve LCID="
                       f"{mat.lcid} is not defined — the cable falls back to "
                       "the linear tension-only law F = K·strain.")
        fid = fid_alloc()
        if keep_f0 and k > 0.0:
            # F = max(F0 + K·strain, 0): the cable is already stretched by
            # F0/K, so it only goes slack once it is shortened by that much.
            x0 = -mat.f0 / k
            pts = [(x0 - 1.0, 0.0), (x0, 0.0), (x0 + 1.0, k)]
        else:
            pts = [(-1.0, 0.0), (0.0, 0.0), (1.0, k)]
            if keep_f0:
                pts = _clamp_tension_only(_shift_curve(pts, mat.f0))
        funct += _emit_funct(fid, f"MAT071_cable_mid{mat.mid}", pts)
    state.warn(f"{label}: cable -> a TENSION-ONLY /PROP/TYPE13 DOF 1 with "
               f"K={k:.6G} and Ileng=1 (stiffness, curve abscissae and mass "
               f"are per unit length), force function /FUNCT/{fid}. The "
               "compression branch is flat at zero force, so the cable goes "
               "slack exactly as in LS-DYNA.")
    if mat.f0 and not keep_f0:
        state.warn(f"{label}: F0={mat.f0:g} (initial tension) is only applied "
                   f"until TMAXF0={mat.tmaxf0:g}; a Radioss spring carries the "
                   "offset for the whole run or not at all, so the "
                   "time-limited pretension is DROPPED (dyna2rad does the "
                   "same). Model it as a short *LOAD or an /IMPDISP if it "
                   "matters.")
    elif keep_f0:
        state.warn(f"{label}: F0={mat.f0:g} (initial tension) was added to "
                   "every ordinate of the force function and the result "
                   "CLAMPED at zero force, so the cable starts pretensioned "
                   "and still goes slack once it is shortened by F0/K. "
                   "dyna2rad shifts without the clamp, which leaves the cable "
                   "PUSHING with F0 in compression.")
    if mat.tramp:
        state.warn(f"{label}: TRAMP={mat.tramp:g} (the time over which F0 is "
                   "ramped in) has no Radioss spring slot — the pretension is "
                   "applied from t=0.")
    dofs = [SpringDof(k=k, fct1=fid)] + [SpringDof() for _ in range(5)]
    return dofs, 0, 0, funct, "cable discrete beam"


def _build_mat074(state, label, mat, fid_alloc, curves):
    """*MAT_074 — a 1-DOF elastic spring with rate terms and displacement
    failure limits."""
    funct: List[str] = []
    fid = 0
    if mat.flcid and mat.flcid in curves and len(curves[mat.flcid].pts) >= 2:
        if mat.f0:
            fid = fid_alloc()
            funct += _emit_funct(
                fid, f"MAT074_lc{mat.flcid}_mid{mat.mid}",
                _shift_curve(curves[mat.flcid].pts, mat.f0))
        else:
            fid = mat.flcid
    elif mat.flcid:
        state.warn(f"{label}: force-vs-deflection curve FLCID={mat.flcid} is "
                   f"not defined — the spring falls back to the linear law "
                   f"F = K·d with K={mat.k:g}.")
    if not fid and mat.f0:
        # No curve, but a preload: a 3-point line of slope K through (0, F0)
        # carries both (dyna2rad convertmats.cxx:4436).
        fid = fid_alloc()
        funct += _emit_funct(fid, f"MAT074_preload_mid{mat.mid}",
                             [(-1.0, -mat.k + mat.f0), (0.0, mat.f0),
                              (1.0, mat.k + mat.f0)])
        state.warn(f"{label}: F0={mat.f0:g} (initial force) has no Radioss "
                   f"spring field — it was baked into /FUNCT/{fid}, a line of "
                   f"slope K={mat.k:g} through (0, {mat.f0:g}).")
    dof = SpringDof(k=mat.k, c=mat.d, b=mat.c2, d=mat.dle, e=mat.c1,
                    fct1=fid, fct2=mat.hlcid,
                    dmin=-abs(mat.cdf), dmax=abs(mat.tdf))
    if mat.hlcid and mat.hlcid not in curves:
        state.warn(f"{label}: rate-scale curve HLCID={mat.hlcid} is not "
                   "defined — the fct_ID21 reference would dangle, so it was "
                   "dropped and the spring is rate-independent.")
        dof.fct2 = 0
    if mat.glcid:
        state.warn(f"{label}: GLCID={mat.glcid} (the optional force-vs-"
                   "deflection curve used when the spring is in tension only) "
                   "has no Radioss spring slot — DROPPED. dyna2rad writes it "
                   "to a `fct_ID51` field that does not exist on LAW113, so "
                   "it is lost there too. Fold the two branches into one "
                   "asymmetric FLCID if the tension response differs.")
    ifail2 = 1 if (mat.cdf or mat.tdf) else 0
    return [dof] + [SpringDof() for _ in range(5)], 0, ifail2, funct, \
        "elastic spring discrete beam"


def _build_mat119(state, label, mat, curves):
    """*MAT_119 — the full 6-DOF general nonlinear discrete beam."""
    hval = _dbeam_unload_hflag(mat.iunld)
    dofs = []
    for i in range(6):
        k = mat.kt if i < 3 else mat.kr
        d = SpringDof(k=k, fct1=mat.lcid[i], fct3=mat.lcid_unld[i],
                      fct4=mat.lcid_damp[i],
                      hscale=1.0 if mat.lcid_damp[i] else 0.0,
                      dmin=-abs(mat.ucfail[i]), dmax=abs(mat.utfail[i]))
        # "same curve on both slots" and "no unloading curve" both mean the
        # spring is nonlinear ELASTIC on that DOF (dyna2rad convertmats.cxx:
        # 5795); the flag would otherwise trip the starter's H guards, and the
        # duplicate reference would suggest a hysteresis that is not there.
        if d.fct3 and d.fct3 != d.fct1:
            d.h = hval
        else:
            d.fct3 = 0
        _apply_unload_guard(state, label, d, i + 1)
        dofs.append(d)
    for name, ids in (("loading", mat.lcid), ("unloading", mat.lcid_unld),
                      ("damping", mat.lcid_damp)):
        missing = sorted({c for c in ids if c and c not in curves})
        if missing:
            state.warn(f"{label}: {name} curve(s) {missing} are not defined in "
                       "the deck — the reference would dangle (starter ERROR "
                       "on an unknown fct_ID), so those slots were CLEARED "
                       "and the affected DOFs fall back to their linear "
                       "stiffness.")
            for d, c in zip(dofs, ids):
                if c in missing:
                    if d.fct1 == c:
                        d.fct1 = 0
                    if d.fct3 == c:
                        d.fct3 = 0
                    if d.fct4 == c:
                        d.fct4 = 0
                    d.h = 0
    if any(mat.lcid_elast):
        state.warn(f"{label}: card 5's LCIDTE*/LCIDRE* elastic-scale curves "
                   f"{[c for c in mat.lcid_elast if c]} have no Radioss spring "
                   "slot — DROPPED. The Radioss law scales the loading "
                   "function by [A + B·ln(rate) + E·g(rate)] only, and both "
                   "rate slots are already taken by the damping curve.")
    if mat.offset:
        state.warn(f"{label}: OFFSET={mat.offset:g} (the permanent-set "
                   "fraction IUNLD=3 unloads towards) has no Radioss spring "
                   "field — the H=5 unloading follows the unloading CURVE "
                   "instead, so the residual deformation comes from that "
                   "curve rather than from OFFSET.")
    if mat.dampf:
        state.warn(f"{label}: DAMPF={mat.dampf:g} (the stiffness-proportional "
                   "damping factor) has no per-DOF Radioss spring slot — "
                   "DROPPED. Add a /DAMP on the part if the numerical damping "
                   "carries load.")
    if mat.fcrit:
        state.warn(f"{label}: FCRIT={mat.fcrit:g} (the failure-criterion "
                   "exponent that couples the six DOFs) has no Radioss "
                   "equivalent — the converted spring uses Ifail=1 "
                   "(multi-directional) with the per-DOF limits instead.")
    has_fail = any(v != 0.0 for v in mat.utfail + mat.ucfail)
    return dofs, (1 if has_fail else 0), (1 if has_fail else 0), [], \
        "general nonlinear 6-DOF discrete beam"


def _build_mat121(state, label, mat, curves):
    """*MAT_121 — the 1-DOF flavour of MAT_119."""
    d = SpringDof(k=mat.k, fct1=mat.lcidt, fct3=mat.lcidtu, fct4=mat.lcidtd,
                  hscale=1.0 if mat.lcidtd else 0.0,
                  dmin=-abs(mat.ucfail), dmax=abs(mat.utfail))
    if d.fct3 and d.fct3 != d.fct1:
        d.h = _dbeam_unload_hflag(mat.iunld)
    else:
        d.fct3 = 0
    for slot, role, cid in (("fct1", "loading", d.fct1),
                            ("fct3", "unloading", d.fct3),
                            ("fct4", "damping", d.fct4)):
        if cid and cid not in curves:
            state.warn(f"{label}: the {role} curve {cid} is not defined in the "
                       "deck — the slot was CLEARED so the reference cannot "
                       "dangle, and the spring falls back to its linear "
                       f"stiffness K={mat.k:g}.")
            setattr(d, slot, 0)
            d.h = 0
    _apply_unload_guard(state, label, d, 1)
    if mat.lcidte:
        state.warn(f"{label}: LCIDTE={mat.lcidte} (the elastic-scale curve) "
                   "has no Radioss spring slot — DROPPED.")
    if mat.offset:
        state.warn(f"{label}: OFFSET={mat.offset:g} (the permanent-set "
                   "fraction IUNLD=3 unloads towards) has no Radioss spring "
                   "field — DROPPED; the unloading follows the unloading "
                   "curve instead.")
    if mat.dampf:
        state.warn(f"{label}: DAMPF={mat.dampf:g} (the stiffness-proportional "
                   "damping factor) has no Radioss spring slot — DROPPED.")
    has_fail = bool(mat.utfail or mat.ucfail)
    return [d] + [SpringDof() for _ in range(5)], 0, \
        (1 if has_fail else 0), [], "general nonlinear 1-DOF discrete beam"


def _build_mat196(state, label, mat, fid_alloc, curves):
    """*MAT_196 — one card PAIR per active DOF; the pair names its own slot."""
    dofs = [SpringDof() for _ in range(6)]
    funct: List[str] = []
    for (dof_no, dtype, k, d, cdf, tdf, flcid, hlcid, c1, c2, dle,
         glcid) in mat.dofs:
        i = dof_no - 1
        s = dofs[i]
        s.k, s.c, s.b, s.d, s.e = k, d, c2, dle, c1
        s.dmin, s.dmax = -abs(cdf), abs(tdf)
        if hlcid:
            if hlcid in curves:
                s.fct2 = hlcid
            else:
                state.warn(f"{label}: DOF {dof_no} rate-scale curve HLCID="
                           f"{hlcid} is not defined — the slot was cleared.")
        if flcid:
            crv = curves.get(flcid)
            if crv is None or len(crv.pts) < 2:
                state.warn(f"{label}: DOF {dof_no} force curve FLCID={flcid} "
                           f"is not defined — that DOF stays LINEAR ELASTIC "
                           f"on K={k:.6G}.")
            elif dtype:
                pts = _plastic_to_total_disp(crv.pts, k)
                if not pts:
                    state.warn(f"{label}: DOF {dof_no} is TYPE={dtype} "
                               "(inelastic), so FLCID is a PLASTIC-"
                               f"displacement curve, but K={k:g} gives no "
                               "elastic branch to add — the curve was DROPPED "
                               "and the DOF stays linear.")
                else:
                    fid = fid_alloc()
                    funct += _emit_funct(
                        fid, f"MAT196_dof{dof_no}_lc{flcid}_mid{mat.mid}", pts)
                    s.fct1, s.h = fid, 1
                    state.warn(
                        f"{label}: DOF {dof_no} is TYPE={dtype} (inelastic), "
                        f"so FLCID {flcid} is read against PLASTIC "
                        f"displacement; every abscissa gained F/K (K={k:.6G}) "
                        f"and the curve was mirrored -> /FUNCT/{fid} with H=1 "
                        "(isotropic hardening). dyna2rad never sets H here, "
                        "which leaves an INELASTIC DOF converted as nonlinear "
                        "elastic.")
            else:
                s.fct1 = flcid
        if glcid:
            state.warn(f"{label}: DOF {dof_no} GLCID={glcid} has no Radioss "
                       "spring slot — DROPPED (dyna2rad loses it too).")
    missing = [i + 1 for i in range(6) if not any(
        (dofs[i].k, dofs[i].c, dofs[i].fct1, dofs[i].fct2))]
    if missing:
        state.warn(f"{label}: DOF(s) {missing} were not given a card pair, so "
                   "they carry NO stiffness and NO damping — the connector is "
                   "free in those directions, exactly as in LS-DYNA.")
    if mat.mdfail:
        state.warn(f"{label}: MDFAIL={mat.mdfail} (0 = the largest "
                   "deflection/limit ratio over all DOFs, 1 = separate "
                   "tension and compression criteria, 2 = combined) selects "
                   "how the per-DOF limits are COUPLED. Radioss offers only "
                   "Ifail 0/1, so the connector is written with the per-DOF "
                   "CDF/TDF limits checked independently (Ifail=0) — a "
                   "coupled criterion would fail earlier.")
    if mat.dospot:
        state.warn(f"{label}: DOSPOT={mat.dospot} (report the connector in "
                   "the spot-weld force file) has no Radioss counterpart — "
                   "the springs still appear in /TH/SPRING.")
    has_fail = any(d.dmin or d.dmax for d in dofs)
    return dofs, 0, (1 if has_fail else 0), funct, "general spring discrete beam"


# ─────────────────────────────────────────────────────────────────────────────
# Emission
# ─────────────────────────────────────────────────────────────────────────────

def _make_discrete_beam_connectors(state: ConversionState) -> List[str]:
    """*SECTION_BEAM ELFORM=6 discrete-beam parts -> /PROP/TYPE8 or
    /PROP/TYPE13 6-DOF /SPRING connectors (see the module docstring)."""
    pids = sorted(_discrete_beam_pids(state))
    if not pids:
        return []
    lines: List[str] = [
        "#-  DISCRETE BEAM CONNECTORS (*SECTION_BEAM ELFORM=6 -> 6-DOF /SPRING):",
        HDR]
    emitted = False

    beams_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    for e in state.beam_elems:
        beams_by_pid[e.pid].append(e)
    curves = state.curves

    for pid in pids:
        part = state.parts[pid]
        beams = beams_by_pid.get(pid, [])
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_beams.get(secid)
        label = f"*SECTION_BEAM {secid} (ELFORM=6) part {pid}"
        if sec is None or sec.elform != 6:
            state.warn(
                f"Discrete-beam part {pid}: its material is a discrete-beam "
                f"material but *SECTION_BEAM {secid} is "
                + ("missing" if sec is None else f"ELFORM={sec.elform}, not 6")
                + f" — {len(beams)} element(s) NOT converted. A discrete-beam "
                "material only means anything on an ELFORM=6 section (that is "
                "where VOL, INER and CID live).")
            continue

        fid_alloc = state.next_curve_id
        mat066 = state.mat_dbeam_linear.get(part.mid)
        mat067 = state.mat_dbeam_nl_elastic.get(part.mid)
        mat068 = state.mat_dbeam_nl_plastic.get(part.mid)
        mat071 = state.mat_cable_dbeam.get(part.mid)
        mat074 = state.mat_elastic_spring_dbeam.get(part.mid)
        mat119 = state.mat_gnl_6dof.get(part.mid)
        mat121 = state.mat_gnl_1dof.get(part.mid)
        mat196 = state.mat_general_spring_dbeam.get(part.mid)
        rho = 0.0
        ileng = 0
        force_type13 = False
        if mat066 is not None:
            rho = mat066.rho
            built = _build_mat066(state, label, mat066, fid_alloc)
        elif mat067 is not None:
            rho = mat067.rho
            built = _build_mat067(state, label, mat067, fid_alloc, curves)
        elif mat068 is not None:
            rho = mat068.rho
            built = _build_mat068(state, label, mat068, fid_alloc, curves)
        elif mat071 is not None:
            rho, force_type13, ileng = mat071.rho, True, 1
            built = _build_mat071(state, label, mat071, sec, fid_alloc, curves)
        elif mat074 is not None:
            rho, force_type13 = mat074.rho, True
            built = _build_mat074(state, label, mat074, fid_alloc, curves)
        elif mat119 is not None:
            rho = mat119.rho
            built = _build_mat119(state, label, mat119, curves)
        elif mat121 is not None:
            rho = mat121.rho
            built = _build_mat121(state, label, mat121, curves)
        elif mat196 is not None:
            rho = mat196.rho
            built = _build_mat196(state, label, mat196, fid_alloc, curves)
        else:
            rho = state.mat_unsupported_dbeam.get(part.mid, ("", 0.0))[1]
            built = _unsupported_payload(state, label, part.mid)
        dofs, ifail, ifail2, funct_lines, kind = built

        # ── frame: TYPE13 (node oriented) vs TYPE8 (skew oriented) ──────────
        skew_id = 0
        if sec.cid:
            skew_id = _resolve_section_skew(state, label, sec.cid)
        use13 = force_type13 or abs(sec.scoor) == 2.0 or not skew_id
        if force_type13 and skew_id:
            state.warn(f"{label}: CID={sec.cid} is not used — {kind} acts "
                       "along the element's own axis (node1->node2), so the "
                       "connector is a node-oriented /PROP/TYPE13 and the "
                       "coordinate system would be ignored.")
        elif use13 and not skew_id and abs(sec.scoor) != 2.0:
            state.warn(
                f"{label}: SCOOR={sec.scoor:g} and no usable CID, so there is "
                "no coordinate triad to orient a skew-based spring with. The "
                "connector was written as a NODE-oriented /PROP/TYPE13 (local "
                "X = node1->node2, XY plane from the beam's third node) rather "
                "than a /PROP/TYPE8 whose frame would silently fall back to "
                "the GLOBAL axes — which is what dyna2rad emits here. Set "
                "|SCOOR|=2 to say so explicitly, or give the section a CID.")

        length = _mean_beam_length(state, beams)
        if mat071 is not None:
            # Ileng=1 makes the property's Mass a mass PER UNIT LENGTH
            # (rinit3.F:408-412), which is exactly LS-DYNA's Imass=1 rho*CA*L.
            mass = rho * sec.ca
        else:
            mass = rho * sec.vol
        if mass <= 0.0:
            state.warn(f"{label}: RO={rho:g} x "
                       + (f"CA={sec.ca:g}" if mat071 is not None
                          else f"VOL={sec.vol:g}")
                       + f" gives a non-positive connector mass — the token "
                       f"mass {_TOKEN_MASS:g} was used instead so the "
                       "explicit time step stays finite. Fill in the "
                       "*SECTION_BEAM card 2f if the connector's inertia "
                       "matters.")
            mass = _TOKEN_MASS
        inertia = _resolve_inertia(state, label, sec.iner, sec.vol, mass,
                                   length)
        if inertia <= 0.0:
            inertia = max(mass * length * length / 12.0, _TOKEN_INERTIA)

        if ileng:
            short = [e.eid for e in beams
                     if _beam_length(state, e) <= 1e-12]
            if short:
                state.warn(
                    f"{label}: Ileng=1 (per-unit-length stiffness and mass) "
                    f"needs a finite element length, and element(s) {short[:5]}"
                    + (" …" if len(short) > 5 else "")
                    + " are zero-length or node-less — the starter answers "
                    "ERROR 328 (rinit3.F) and refuses the deck. Those "
                    "element(s) were NOT written.")
                beams = [e for e in beams if _beam_length(state, e) > 1e-12]

        dropped = [n for n, v in (("OFFSET", sec.cable_offset),
                                  ("RRCON", sec.rrcon), ("SRCON", sec.srcon),
                                  ("TRCON", sec.trcon)) if v]
        if dropped:
            state.warn(
                f"{label}: card 2f's {', '.join(dropped)} have no Radioss "
                "spring slot — DROPPED. RRCON/SRCON/TRCON free or lock the "
                "triad's rotation about local r/s/t; the converted connector "
                "always co-rotates. OFFSET is the cable's slack length; state "
                "it as a shifted force function instead.")

        prop_id = state.next_prop_id()
        title = (part.title or f"DISCRETE_BEAM_{pid}")
        lines += funct_lines
        if use13:
            lines += _emit_prop_type13(
                prop_id, f"{title} ({kind})", mass, inertia, ifail, ifail2,
                dofs, ileng=ileng)
        else:
            lines += _emit_prop_type8(
                prop_id, f"{title} ({kind})", mass, inertia, skew_id, dofs,
                ifail=ifail, ifail2=ifail2)
        lines += [
            f"/PART/{pid}",
            title,
            # mat_id 0: the whole material lives in the property, and a /PART
            # on TYPE8/TYPE13 needs no /MAT (unlike TYPE23, ERROR 179).
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
        ]
        if beams:
            lines += [f"/SPRING/{pid}",
                      "# sprg_ID  node_ID1  node_ID2  node_ID3"]
            no_n3 = 0
            for e in beams:
                n3 = e.n3 if e.n3 in state.nodes else 0
                if not n3:
                    no_n3 += 1
                lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}{_i(n3)}")
                state.dbeam_spring_eids.add(e.eid)
            if use13 and no_n3:
                state.warn(
                    f"{label}: {no_n3} element(s) carry no third node, so the "
                    "node-oriented /PROP/TYPE13 has nothing to set its XY "
                    "plane from and falls back to the property skew's Y' (or "
                    "the global axes). The AXIAL DOF is still correct; the two "
                    "shear and two bending DOFs may be rotated about it. Give "
                    "the beams a third node, or use *ELEMENT_BEAM_ORIENTATION.")
        lines.append(HDR)
        emitted = True

        state.warn(
            f"{label}: {kind} (MID {part.mid}) -> "
            f"/PROP/TYPE{'13' if use13 else '8'}/{prop_id} + "
            f"{len(beams)} /SPRING element(s) on /PART/{pid}"
            + (f", skew_ID={skew_id} from CID={sec.cid}" if not use13 else "")
            + f". Mass={mass:.6G}"
            + (" per unit length (Ileng=1)" if ileng else "")
            + f", Inertia={inertia:.6G}. A discrete beam is a SPRING, not a "
            "beam: it has no cross-section and carries only the per-DOF "
            "stiffness the material states.")

    return lines if emitted else []


def _beam_length(state: ConversionState, e: BeamElem) -> float:
    a, b = state.nodes.get(e.n1), state.nodes.get(e.n2)
    if a is None or b is None:
        return 0.0
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5


def _resolve_section_skew(state: ConversionState, label: str,
                          cid: int) -> int:
    """*SECTION_BEAM card 2f CID -> an emitted /SKEW id, 0 when it does not
    resolve. Every *DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR keeps its CID as
    the /SKEW id, so the lookup is the identity — but it must still CHECK, or
    the property would reference a skew the deck never writes (ERROR 137)."""
    if cid in state.coord_sys or cid in state.coord_nodes \
            or cid in state.coord_vectors:
        return cid
    state.warn(f"{label}: CID={cid} does not name any converted "
               "*DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR, so there is no "
               "/SKEW to attach — referencing it would be starter ERROR 137. "
               "The connector falls back to the node-oriented frame.")
    return 0


def _unsupported_payload(state: ConversionState, label: str, mid: int):
    """An ELFORM=6 part whose material k2rad cannot turn into a spring law.

    The connector is still written, with every DOF inert: the elements stay
    addressable (a /TH/SPRING, a *SET_BEAM member or a /GRNOD/PART all
    reference them) and the deck still starts, which it would not if the part
    kept its /PROP/BEAM (an ELFORM=6 section states no cross-section at all,
    so the starter answers ERROR 314-317 on Area/Iyy/Izz/Ixx)."""
    kw, _rho = state.mat_unsupported_dbeam.get(mid, ("", 0.0))
    if kw and kw in _UNMAPPED_DISCRETE_BEAM_LOSS:
        name, loss = _UNMAPPED_DISCRETE_BEAM_LOSS[kw]
        state.warn(
            f"{label}: material {mid} is {name}, which has NO OpenRadioss "
            f"spring counterpart — {loss} is LOST. The connector was written "
            "with zero stiffness and zero damping on every DOF, so the parts "
            "it joins are free: the run will start and the elements stay "
            "addressable, but the deck no longer models that device. "
            "(dyna2rad does not convert it either, and says nothing.)")
    else:
        state.warn(
            f"{label}: material {mid} is not a discrete-beam material k2rad "
            "converts (MAT_066/067/068/071/074/119/121/196) — the connector "
            "was written with zero stiffness and zero damping on every DOF, "
            "so the parts it joins are FREE. An ELFORM=6 *SECTION_BEAM states "
            "no cross-section, so it cannot stay a /PROP/BEAM either (starter "
            "ERROR 314-317). Give the part a discrete-beam material, or model "
            "it as *ELEMENT_DISCRETE + *SECTION_DISCRETE.")
    return [SpringDof() for _ in range(6)], 0, 0, [], "unsupported discrete beam"
