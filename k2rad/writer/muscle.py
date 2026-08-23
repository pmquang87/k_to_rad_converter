"""``*MAT_MUSCLE`` (156) and ``*MAT_SPRING_MUSCLE`` (S15) → ``/PROP/TYPE46``.

Both LS-DYNA cards state a Hill-type muscle: an active contractile element in
parallel with a passive elastic one, plus a damper. ``/PROP/TYPE46``
(``SPR_MUSCLE``) is the Radioss counterpart and its force law is term for term
the same sum (``engine/source/elements/spring/ruser46.F:168-211``)::

    TT  = t / Scale_t
    Epsi = 0 :  dL  = L/L0 - 1                       (strain)
                dLd = (L/L0)*VX/Vel_max / Scale_v    (normalised rate)
    Epsi = 1 :  dL  = X / Scale_x                    (elongation)
                dLd = VX / Scale_v                   (velocity)
    FX = Force*f1(TT)*f2(dL)*f3(dLd) + Scale_F*f4(dL) + Damp*clamp(VX, +-Vel_max)

so ``Force*f1*f2*f3`` is the active term, ``Scale_F*f4`` the passive one and
``Damp*VX`` the damper. Every one of the four function slots is measured to
behave exactly as written (probe decks ``w2``/``w6``/``w7``/``w8``/``w9``/
``w11``/``w12``/``w13``/``w14``/``w15``: predicted vs measured agree to 4
significant digits, e.g. ``f_v(-0.198)*100 = 85.15 N`` against 85.151 measured).

**The product form is a trap.** ``GET_U_FUNC(IFUNC = 0)`` reads ``NPF(0)``
(``ufunc.F:183``, ``eng_callback_c.c:176``) and returns 0 — so a single unset
``fct_id1``/``2``/``3`` makes the WHOLE active force identically zero, at 0
starter errors and 0 warnings (measured on four separate decks). Every slot is
therefore always written, with a synthesized constant when the LS-DYNA card
leaves the corresponding factor unspecified.

Two deliberate departures from dyna2rad, both defects measured on this build:

* ``Force`` never lands on d2r's ``*MAT_MUSCLE`` path — ``radProp.SetValue(...,
  sdiIdentifier("Force"), ...)`` at ``convertprops.cxx:2617`` fails to resolve
  while the identical call with ``"Scale_F"`` one line later succeeds, so the
  echoed ``MAXIMUM FORCE`` is 0.0 for every PIS. A hand-written card with the
  same value in card-1 column 4 echoes it correctly, so the starter is fine and
  the converted muscle simply has no ACTIVE force at all.
* ``Vel_max <- SRM``, ``Damp <- DMP`` and ``Mass <- RO*A`` are dimensionally
  wrong (``SRM`` is a strain rate, not a velocity; ``DMP`` multiplies a strain
  rate, not a velocity) and ``SNO`` / ``SFR`` / ``SV`` are dropped outright.
  The conversions below carry the element length and ``SNO`` through instead —
  see :func:`_muscle_beam_part`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from ..state import ConversionState, MatMuscle, MatSpringMuscle
from .common import HDR, _f, _i, _muscle_beam_pids, _muscle_discrete_pids

__all__ = [
    "_emit_prop_type46",
    "_make_muscle_springs",
    "_muscle_exponential_ssp",
    "_muscle_exponential_fpe",
]


#: Abscissa samples of the two built-in exponential passive laws, as the
#: MULTIPLIER of the LS-DYNA reference length: one point at -1 (the whole
#: "shorter than the reference" half, where the passive force is identically 0)
#: and then 0.00, 0.01, ... 1.00. dyna2rad uses exactly this sampling
#: (``convertprops.cxx:2831-2875`` / ``:3236-3306``) and it is the one piece of
#: its muscle conversion that is algebraically correct, so it is kept.
_PASSIVE_SAMPLES = [-1.0] + [j / 100.0 for j in range(101)]


def _emit_prop_type46(prop_id: int, title: str, mass: float, stiffness: float,
                      vel_max: float, force: float, xk: float,
                      fct1: int, fct2: int, fct3: int, fct4: int, idens: int,
                      damp: float, epsi: int,
                      scale_t: float, scale_x: float, scale_v: float,
                      scale_f: float) -> List[str]:
    """/PROP/TYPE46 (SPR_MUSCLE).

    Layout audited against ``hm_cfg_files/config/CFG/radioss140/PROP/
    prop_p46_SPR_MUSCLE.cfg`` — its only FORMAT block is ``FORMAT(radioss140)``,
    so this is exactly what a ``/BEGIN 2022`` deck reads (starter-verified, 0
    errors, every field echoed):

      C1: Mass(20) Stiffness(20) Vel_max(20) Force(20) Xk(20)
      C2: fct_id1(10) fct_id2(10) fct_id3(10) fct_id4(10) [10 blanks] Idens(10)
      C3: Damp(20) Epsi(10)
      C4: Scale_t(20) Scale_x(20) Scale_v(20) Scale_F(20)

    Note the TEN blank columns on card 2 — ``Idens`` sits in columns 51-60, not
    41-50, and writing it one cell left would silently make a per-unit-length
    mass into a per-element one.

    Zero-valued fields take the reader's defaults (``hm_read_prop46.F:167-179``):
    ``Xk = Stiffness``, ``Vel_max -> 1e30``, ``Scale_t/x/v/F -> 1``. ``Stiffness``
    and ``Xk`` contribute NO force at all (measured: a 1000-stiffness TYPE46
    driven 4 mm reports exactly 0 elastic force) — they set the element time
    step and the contact stiffness only.
    """
    return [
        f"/PROP/TYPE46/{prop_id}",
        title[:100],
        "#               Mass           Stiffness             Vel_max"
        "               Force                  Xk",
        f"{_f(mass)}{_f(stiffness)}{_f(vel_max)}{_f(force)}{_f(xk)}",
        "#  fct_id1   fct_id2   fct_id3   fct_id4               Idens",
        f"{_i(fct1)}{_i(fct2)}{_i(fct3)}{_i(fct4)}{' ' * 10}{_i(idens)}",
        "#               Damp      Epsi",
        f"{_f(damp)}{_i(epsi)}",
        "#            Scale_t             Scale_x             Scale_v"
        "             Scale_F",
        f"{_f(scale_t)}{_f(scale_x)}{_f(scale_v)}{_f(scale_f)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# The two built-in exponential passive laws
# ─────────────────────────────────────────────────────────────────────────────

def _muscle_exponential_ssp(ssm: float, cer: float):
    """*MAT_MUSCLE ``SSP = 0``: the dimensionless passive stress ``h(eps)``.

    Vol II R17 p.2-1073, verbatim::

        h = 0                                             (lambda < 1)
        h = (1/(exp(CER)-1)) * [exp((CER/SSM)*eps) - 1]    (lambda >= 1, CER != 0)
        h = eps/SSM                                       (lambda >= 1, CER = 0)

    with ``eps = lambda - 1``. Returns ``[(eps, h)]`` — the caller maps ``eps``
    onto the Radioss abscissa. ``None`` when the card cannot produce a curve
    (``SSM = 0`` divides by zero; dyna2rad has no guard there).
    """
    if ssm == 0.0:
        return None
    try:
        denom = math.exp(cer) - 1.0 if cer != 0.0 else 0.0
        if cer != 0.0 and denom == 0.0:
            return None
        pts = []
        for eps in _PASSIVE_SAMPLES:
            if eps < 0.0:
                y = 0.0
            elif cer != 0.0:
                y = (math.exp(cer * eps / ssm) - 1.0) / denom
            else:
                y = eps / ssm
            pts.append((eps, y))
    except (OverflowError, ZeroDivisionError):
        return None
    return pts


def _muscle_exponential_fpe(lmax: float, ksh: float):
    """*MAT_SPRING_MUSCLE ``FPE = 0``: the NORMALIZED passive force ``f_PE(L)``.

    Vol II R17 p.2-2097, verbatim::

        f_PE = F_PE/F_MAX = 0                                        (L <= 1)
        f_PE = (1/(exp(Ksh)-1)) * {exp[(Ksh/Lmax)*(L-1)] - 1}        (L > 1)

    Returns ``[(L-1, f_PE)]``; the caller maps ``L-1`` onto the Radioss
    abscissa and puts ``FMAX`` in ``Scale_F`` (SDMAT15.cfg:38 types the sibling
    ``FPE`` curve as *"Normalized force, as a function of length for parallel
    elastic element"*, so both branches are normalized and share one scale).

    ``Ksh = 0`` is not stated by the manual; the limit of the expression is
    ``(L-1)/Lmax``, which is exactly the linear form the SIBLING card
    (*MAT_MUSCLE ``CER = 0``, p.2-1073) states for the identical formula — so
    the continuation is taken rather than invented. ``Lmax = 0`` divides by zero
    and returns ``None`` (dyna2rad silently emits no function at all there).
    """
    if lmax == 0.0:
        return None
    try:
        denom = math.exp(ksh) - 1.0 if ksh != 0.0 else 0.0
        if ksh != 0.0 and denom == 0.0:
            return None
        pts = []
        for u in _PASSIVE_SAMPLES:
            if u <= 0.0:
                y = 0.0
            elif ksh != 0.0:
                y = (math.exp(ksh * u / lmax) - 1.0) / denom
            else:
                y = u / lmax
            pts.append((u, y))
    except (OverflowError, ZeroDivisionError):
        return None
    return pts


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _elem_length(state: ConversionState, n1: int, n2: int) -> float:
    a, b = state.nodes.get(n1), state.nodes.get(n2)
    if a is None or b is None:
        return 0.0
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def _reference_length(state: ConversionState, pairs: Sequence[Tuple[int, int]],
                      label: str) -> Optional[float]:
    """The ONE initial element length the property's scale factors are built on.

    ``/PROP/TYPE46`` is a PROPERTY: it carries one ``Vel_max``, one ``Damp`` and
    one ``Mass`` for every element on the part, while the LS-DYNA muscle states
    its rate and damping against each element's OWN reference length
    (``eps_dot = v/l_orig``). The two agree exactly only when all the part's
    muscle elements are the same length — the mean is used otherwise, and the
    spread is reported, because silently averaging a rate normalisation is the
    kind of thing that shows up as a 30 % force error and nothing else.
    """
    lengths = [ln for ln in (_elem_length(state, a, b) for a, b in pairs)
               if ln > 0.0]
    if not lengths:
        return None
    lo, hi = min(lengths), max(lengths)
    mean = sum(lengths) / len(lengths)
    if hi - lo > 1.0e-6 * max(hi, 1.0e-30):
        state.warn(
            f"{label}: the part's {len(lengths)} muscle element(s) are NOT all "
            f"the same length ({lo:g} .. {hi:g}). /PROP/TYPE46 carries ONE "
            "Vel_max, ONE Damp and ONE Mass for the whole part while the "
            "LS-DYNA muscle normalises its strain rate and its damping against "
            "each element's own reference length (eps_dot = v/l_orig, Vol II "
            f"R17 p.2-1072), so the mean length {mean:g} is used for all of "
            "them: the rate factor f3 and the damper are then off by "
            f"(l_elem/{mean:g}) per element. Split the part so each "
            "/PROP/TYPE46 serves one element length if that matters.")
    return mean


def _const_curve(value: float):
    """A 2-point constant function, bracketed wide enough that the whole
    plausible abscissa range is INSIDE the definition (a Radioss /FUNCT is a
    piecewise-linear table; a flat one is flat under extrapolation too, but a
    bracket that spans the operating range keeps the card readable)."""
    return [(-1.0, value), (2.0, value)]


# ─────────────────────────────────────────────────────────────────────────────
# The writer
# ─────────────────────────────────────────────────────────────────────────────

def _make_muscle_springs(state: ConversionState) -> List[str]:
    """*MAT_MUSCLE / *MAT_SPRING_MUSCLE parts → /PART + /PROP/TYPE46 + /SPRING.

    The two LS-DYNA keywords reach the same Radioss property from opposite
    sides — 156 sits on a ``*SECTION_BEAM`` truss part, S15 on a
    ``*SECTION_DISCRETE`` one — so which one applies is decided by the PROPERTY
    the part carries, never by the material keyword alone
    (``common._muscle_beam_pids`` / ``_muscle_discrete_pids``; dyna2rad branches
    the same way, ``convertprops.cxx:305-312`` and ``:1240-1243``).

    No ``/MAT`` is written for either: the whole law lives in the property and
    the ``/PART`` carries ``mat_ID = 0``, which the starter accepts on a TYPE46
    spring part (verified).
    """
    from .loads import _emit_funct

    beam_pids = sorted(_muscle_beam_pids(state))
    disc_pids = sorted(_muscle_discrete_pids(state))
    if not beam_pids and not disc_pids:
        return []
    lines: List[str] = [
        "#-  MUSCLE CONNECTORS (*MAT_MUSCLE / *MAT_SPRING_MUSCLE -> "
        "/PROP/TYPE46 + /SPRING):",
        HDR,
    ]
    beams_by_pid: Dict[int, List] = defaultdict(list)
    for e in state.beam_elems:
        beams_by_pid[e.pid].append(e)
    disc_by_pid: Dict[int, List] = defaultdict(list)
    for e in state.discrete_elems:
        disc_by_pid[e.pid].append(e)

    emitted = False
    for pid in beam_pids:
        out = _muscle_beam_part(state, pid, beams_by_pid.get(pid, []),
                                _emit_funct)
        if out:
            lines += out
            emitted = True
    for pid in disc_pids:
        out = _muscle_discrete_part(state, pid, disc_by_pid.get(pid, []),
                                    _emit_funct)
        if out:
            lines += out
            emitted = True
    return lines if emitted else []


def _spring_rows(state: ConversionState, part_id: int, pairs, label: str):
    """The ``/SPRING`` block for one muscle part, plus the eids it wrote.

    A grounded (``N2 = 0``) or coincident-node element is DROPPED, not given a
    synthesized ground node the way an *ELEMENT_DISCRETE spring is: the ground
    node would sit on top of the anchor, and a ZERO-LENGTH TYPE46 has no
    reference length to normalise with — ``rini46.F`` answers
    ``**ERROR: ZERO LENGTH SPRING`` (with no ancmsg and no error count, i.e. a
    line in the .out and nothing else). Naming the elements beats emitting a
    spring that cannot compute a force.
    """
    rows: List[str] = []
    eids: List[int] = []
    dropped: List[int] = []
    for eid, n1, n2 in pairs:
        if n1 <= 0 or n2 <= 0 or n1 not in state.nodes or n2 not in state.nodes:
            dropped.append(eid)
            continue
        if _elem_length(state, n1, n2) <= 0.0:
            dropped.append(eid)
            continue
        rows.append(f"{_i(eid)}{_i(n1)}{_i(n2)}")
        eids.append(eid)
    if dropped:
        state.warn(
            f"{label}: element(s) {sorted(dropped)} are grounded (N2=0), "
            "reference a node with no *NODE record, or have coincident nodes — "
            "dropped. A /PROP/TYPE46 muscle normalises its stretch against the "
            "element's own initial length (ruser46.F:176-181), so a zero-length "
            "one produces '**ERROR: ZERO LENGTH SPRING' in the .out and no "
            "force; unlike an *ELEMENT_DISCRETE spring it cannot be grounded "
            "with a coincident node.")
    if not rows:
        return None, []
    return ([f"/SPRING/{part_id}", "# sprg_ID  node_ID1  node_ID2"] + rows
            + [HDR]), eids


def _muscle_beam_part(state: ConversionState, pid: int, elems, emit_funct):
    """One *MAT_MUSCLE (156) truss part → /PROP/TYPE46 + /PART + /SPRING.

    The LS-DYNA law (Vol II R17 pp.2-1071..2-1073) is

      sigma = PIS*a(t)*f(lambda)*g(eps_bar_dot) + PIS*h(lambda)
              + DMP*lambda*eps_dot

    with ``lambda = l/l_orig``, ``l_orig = l0/SNO``, ``eps_dot = v/l_orig`` and
    ``eps_bar_dot = lambda*eps_dot/(SFR*SRM)``. Multiplying through by the
    section AREA and matching the Radioss law term by term gives, with ``L0``
    the element's initial length:

      ==============  ============================================
      Radioss slot    value
      ==============  ============================================
      ``Force``       ``PIS*A``      the peak isometric FORCE
      ``Scale_F``     ``PIS*A``      the passive term shares it
      ``Mass``        ``RHO*A/SNO``  with ``Idens = 0`` (per unit length), so
                                     the element mass is ``RHO*A*L0/SNO`` =
                                     ``RHO*A*l_orig`` — the manual's "the
                                     nodal masses are based on RO/SNO"
      ``Vel_max``     ``SRM*L0/SNO`` the maximum shortening VELOCITY that the
                                     maximum strain rate SRM corresponds to;
                                     it is also the damper's clamp
      ``Scale_v``     ``SFR/SNO``    so that
                                     ``Vel_max*Scale_v = SRM*SFR*L0/SNO**2``,
                                     which makes the Radioss abscissa
                                     ``(L/L0)*v/(Vel_max*Scale_v)`` identical
                                     to ``eps_bar_dot``
      ``Damp``        ``DMP*A*SNO**2/L0``
      ``Epsi``        0              (the strain form)
      ==============  ============================================

    ``Damp`` is the one LINEARISED value. LS-DYNA's damper force is
    ``A*DMP*lambda*eps_dot = A*DMP*SNO**2*(L/L0)*v/L0``, which is quadratic in
    the stretch, while Radioss offers ``Damp*v`` only. It is matched at the
    element's INITIAL configuration (``L = L0``), so it is exact at t = 0 and
    drifts with ``L/L0``. Named in the per-part warning.

    The f2/f4 abscissa transform is ``lambda -> lambda/SNO - 1``: the Radioss
    abscissa is ``L/L0 - 1`` and ``lambda = SNO*L/L0``. dyna2rad uses plain
    ``lambda - 1``, i.e. it assumes ``SNO = 1`` (it drops SNO entirely), and it
    applies that shift to the RAW *DEFINE_CURVE points before letting a
    /MOVE_FUNCT apply SFA/OFFA, so its abscissa is ``SFA*(x_raw-1)+OFFA``
    instead of ``SFA*x_raw+OFFA-1``. k2rad reads ``state.curves``, whose points
    are already scaled and offset at parse time (handlers.py:4397-4417), so the
    ordering defect cannot occur here.
    """
    part = state.parts.get(pid)
    if part is None:
        return None
    mat = state.mat_muscle.get(part.mid)
    if mat is None:
        return None
    label = f"*MAT_MUSCLE {mat.mid} on part {pid}"
    if not elems:
        state.warn(f"{label}: the part has no *ELEMENT_BEAM — no "
                   "/PROP/TYPE46 muscle emitted.")
        return None
    secid = part.secid if part.secid > 0 else pid
    sec = state.sec_beams.get(secid)
    area = sec.area if sec is not None else 0.0
    if sec is None:
        state.warn(f"{label}: no *SECTION_BEAM {secid} — the cross-section "
                   "AREA is unknown, so PIS (a STRESS) cannot be turned into "
                   "the /PROP/TYPE46 Force (a FORCE) and the muscle would pull "
                   "with zero force. Part skipped.")
        return None
    if sec.elform not in (0, 3):
        state.warn(
            f"{label}: the *SECTION_BEAM states ELFORM={sec.elform}, but "
            "*MAT_156 is defined for TRUSS elements only (Vol II R17 p.2-1071, "
            "'This is Material Type 156 for truss elements'), i.e. ELFORM=3. "
            "The part is still converted to a /PROP/TYPE46 axial muscle — its "
            "bending and torsional resultants are DROPPED, because the muscle "
            "spring has no rotational degree of freedom at all.")
    if area <= 0.0:
        state.warn(
            f"{label}: *SECTION_BEAM {secid} states no cross-section AREA "
            "(field A of the ELFORM-3 card 2 is blank or zero), so PIS*A = 0 "
            "and the muscle would pull with zero force. Part skipped — set A "
            "in the .k file.")
        return None

    pairs = [(e.eid, e.n1, e.n2) for e in elems]
    l0 = _reference_length(state, [(a, b) for _e, a, b in pairs], label)
    if l0 is None:
        state.warn(f"{label}: none of its {len(elems)} beam element(s) has two "
                   "resolvable, distinct nodes — no /PROP/TYPE46 emitted.")
        return None
    sno = mat.sno if mat.sno else 1.0
    # SFR scales the strain-rate normalisation. As a CURVE it is a function of
    # something /PROP/TYPE46's Scale_v — a single number applied every cycle
    # (ruser46.F:199) — cannot follow, so it is named and dropped with SFR = 1.
    sfr = mat.sfr if mat.sfr else 1.0
    if mat.sfr_lcid:
        state.warn(
            f"{label}: SFR is stated as curve {mat.sfr_lcid} (the scale factor "
            "on the maximum strain rate SRM, Vol II R17 p.2-1072). "
            "/PROP/TYPE46's Scale_v is ONE number applied unconditionally "
            "(ruser46.F:199), so a varying rate scale has no slot — dropped, "
            "SFR = 1.0 is used, and the normalised abscissa of the f3 velocity "
            "function is then eps_bar_dot at SFR = 1. dyna2rad drops SFR "
            "silently in both branches.")
        sfr = 1.0

    funct_lines: List[str] = []

    def _new_funct(title: str, pts) -> int:
        fid = state.next_curve_id()
        funct_lines.extend(emit_funct(fid, title, pts))
        return fid

    # ── f1: activation a(t). The Radioss abscissa is t/Scale_t, and Scale_t
    # stays at its 1.0 default, so an LS-DYNA a(t) curve is used verbatim.
    fct1 = _resolve_activation(state, label, mat.alm, mat.alm_lcid,
                               "ALM", _new_funct, f"MatL156_ALM_{mat.mid}")
    # ── f2: active tension vs stretch ratio.
    fct2 = _resolve_lambda_curve(
        state, label, mat.svs, mat.svs_lcid, "SVS", sno, 0.0, 1.0,
        _new_funct, f"MatL156_SVS_{mat.mid}")
    # ── f3: active tension vs NORMALISED strain rate. Vel_max*Scale_v is built
    # so the Radioss abscissa IS eps_bar_dot, so the curve needs no transform.
    if mat.svr_lcid:
        fct3 = _verbatim_curve(state, label, mat.svr_lcid, "SVR",
                               _new_funct, f"MatL156_SVR_{mat.mid}", 1.0)
    else:
        fct3 = _new_funct(f"MatL156_SVR_{mat.mid}", _const_curve(1.0))
    # ── f4: passive stress h(lambda), dimensionless (Scale_F = PIS*A carries
    # the units).
    fct4 = _resolve_ssp(state, label, mat, sno, _new_funct)

    force = mat.pis * area
    prop_id = _muscle_prop_id(state, pid)
    title = part.title or f"MUSCLE_{pid}"
    lines = list(funct_lines)
    lines += _emit_prop_type46(
        prop_id, title,
        mass=mat.rho * area / sno,
        stiffness=0.0,
        vel_max=mat.srm * l0 / sno,
        force=force,
        xk=0.0,
        fct1=fct1, fct2=fct2, fct3=fct3, fct4=fct4,
        idens=0,                      # Mass is per UNIT LENGTH
        damp=mat.dmp * area * sno * sno / l0,
        epsi=0,                       # strain form
        scale_t=0.0,                  # -> 1.0
        scale_x=0.0,                  # -> 1.0 (unused at Epsi=0)
        scale_v=sfr / sno,
        scale_f=force)
    lines += [f"/PART/{pid}", title,
              # mat_ID 0: the whole law lives in the property (verified — the
              # starter accepts a TYPE46 part with no material).
              f"{_i(prop_id)}{_i(0)}{_i(0)}"]
    rows, eids = _spring_rows(state, pid, pairs, label)
    if rows is None:
        return None
    lines += rows
    for eid in eids:
        # /SPRING producer 8 of 8, recorded AT the write line. NOT in
        # beam_elem_ids: these ids are /SPRING in the emitted deck, which is
        # what makes the *SET_BEAM family split (writer/output.py) route them
        # to /TH/SPRING instead of /TH/BEAM.
        state.spring_elem_ids.add(eid)
        state.muscle_spring_eids.add(eid)
    state.warn(
        f"{label} -> /PROP/TYPE46/{prop_id} (SPR_MUSCLE) + {len(eids)} "
        f"/SPRING element(s). Force = PIS*A = {force:g}; Mass = RHO*A/SNO = "
        f"{mat.rho * area / sno:g} per unit length; Vel_max = SRM*L0/SNO = "
        f"{mat.srm * l0 / sno:g} on the reference length L0 = {l0:g}; "
        f"Damp = DMP*A*SNO^2/L0 = {mat.dmp * area * sno * sno / l0:g}, which "
        "is the LS-DYNA damper sigma3 = DMP*lambda*eps_dot LINEARISED at the "
        "element's initial configuration (the Radioss damper is Damp*v only, "
        "with no stretch factor, so it drifts with L/L0). Radioss has no truss "
        "element, so the axial-only muscle becomes a SPRING: the part carries "
        "no bending or torsional stiffness, which is what an LS-DYNA truss "
        "states anyway. Per-element force history is NOT available — /TH/SPRING "
        "on a TYPE46 writes 15 channels of exact zero (measured, including the "
        "OFF flag, while a /PROP/TYPE4 spring in the SAME group reports "
        "correctly); use /TH/NODE REACX on an anchor node (an accumulated "
        "impulse — differentiate it) or the global SPRING ENERGY channel. "
        f"NOTE: the generic *SECTION_BEAM {secid} ELFORM warning does NOT "
        "apply to this part — no /PROP/BEAM is written for it at all, its "
        "AREA is consumed by the muscle property above.")
    return lines


def _muscle_discrete_part(state: ConversionState, pid: int, elems, emit_funct):
    """One *MAT_SPRING_MUSCLE (S15) discrete part → /PROP/TYPE46 + /PART +
    /SPRING.

    The LS-DYNA law (Vol II R17 pp.2-2095..2-2097) is

      F_M = F_PE + a(t)*F_max*f_TL(L)*f_TV(V),
      L = L_M/L0,   V = V_M/(V_max*S_v)

    which is already in FORCE and ELONGATION terms, so this side maps onto
    ``Epsi = 1`` (the elongation form) with ``Force = FMAX``,
    ``Vel_max = VMAX`` and ``Scale_F = FMAX``:

      * ``f1`` is ``a(t)``, abscissa = time (``Scale_t`` default 1);
      * ``f2`` is ``f_TL``, whose abscissa is the dimensionless length ratio
        ``L = L_M/L0``. The Radioss abscissa is the ELONGATION ``X``, so the
        transform is ``X = L*L0 - l_init`` with ``l_init`` the element's actual
        initial length. dyna2rad writes ``(L-1)*L0``, which is the same thing
        under the card's own assumption ``l_init = L0`` and silently wrong when
        the deck states an L0 the mesh does not have.
      * ``f3`` is ``f_TV``, whose abscissa is ``V = V_M/(V_max*S_v)``. The
        Radioss abscissa is the raw velocity (``Scale_v`` default 1), so the
        transform is ``v = V*VMAX*SV``. dyna2rad multiplies by VMAX and drops
        ``SV`` entirely.
      * ``f4`` is ``f_PE``, the NORMALIZED passive force (SDMAT15.cfg:38), so
        the ordinate is carried as stated and ``Scale_F = FMAX`` supplies the
        units. dyna2rad instead bakes FMAX into the exponential's ordinate and
        leaves ``Scale_F`` at 1 — numerically the same for that branch, but its
        ``FPE < 0`` curve branch then gets NEITHER the abscissa transform nor
        the scale and is off by both.

    No mass is written. ``*MAT_SPRING_MUSCLE`` has no density and no mass cell
    of any kind, so inventing one would be inventing inertia; the elements'
    mass has to come from ``*ELEMENT_MASS`` (which k2rad converts to /ADMAS)
    exactly as it does in LS-DYNA. The per-part warning says so.
    """
    part = state.parts.get(pid)
    if part is None:
        return None
    mat = state.mat_spring_muscle.get(part.mid)
    if mat is None:
        return None
    label = f"*MAT_SPRING_MUSCLE {mat.mid} on part {pid}"
    if not elems:
        state.warn(f"{label}: the part has no *ELEMENT_DISCRETE — no "
                   "/PROP/TYPE46 muscle emitted.")
        return None
    pairs = [(e.eid, e.n1, e.n2) for e in elems]
    l_init = _reference_length(state, [(a, b) for _e, a, b in pairs], label)
    if l_init is None:
        state.warn(f"{label}: none of its {len(elems)} discrete element(s) has "
                   "two resolvable, distinct nodes — no /PROP/TYPE46 emitted. "
                   "A muscle spring cannot be grounded: a zero-length TYPE46 "
                   "has no reference length (rini46.F).")
        return None
    l0 = mat.l0 if mat.l0 else 1.0
    if abs(l0 - l_init) > 1.0e-6 * max(abs(l_init), 1.0):
        state.warn(
            f"{label}: the card states L0 = {l0:g} but the element(s) are "
            f"{l_init:g} long. L0 is the muscle's REFERENCE length and every "
            "TL/FPE abscissa is the ratio L = L_M/L0 (Vol II R17 p.2-2096), so "
            "the emitted /FUNCT abscissae are X = L*L0 - l_init, i.e. the "
            "curves are evaluated exactly where LS-DYNA would evaluate them — "
            "but a deck whose L0 does not match its mesh starts the muscle away "
            "from its reference length, which is almost always a card error "
            "(a blank L0 defaults to 1.0, not to the element length).")

    funct_lines: List[str] = []

    def _new_funct(title: str, pts) -> int:
        fid = state.next_curve_id()
        funct_lines.extend(emit_funct(fid, title, pts))
        return fid

    fct1 = _resolve_activation(state, label, mat.a, mat.a_lcid, "A",
                               _new_funct, f"MatS15_A_{mat.mid}")
    # SV scales the velocity abscissa. As a CURVE it is a function of the
    # activation level, which /PROP/TYPE46 has no slot for (Scale_v is one
    # number) — named and dropped, with SV = 1.
    sv = mat.sv
    if mat.sv_lcid:
        state.warn(
            f"{label}: SV is stated as curve {mat.sv_lcid} (the scale factor "
            "for VMAX as a function of the ACTIVE STATE, Vol II R17 p.2-2096). "
            "/PROP/TYPE46's Scale_v is a single number and the engine applies "
            "it unconditionally (ruser46.F:199), so an activation-dependent "
            "velocity scale cannot be expressed — dropped, SV = 1.0 is used. "
            "The velocity factor f_TV is then evaluated at the UNSCALED "
            "velocity ratio.")
        sv = 1.0
    if sv == 0.0:
        sv = 1.0
    fct2 = _resolve_length_curve(state, label, mat.tl, mat.tl_lcid, "TL",
                                 l0, l_init, _new_funct,
                                 f"MatS15_TL_{mat.mid}")
    fct3 = _resolve_velocity_curve(state, label, mat.tv, mat.tv_lcid, "TV",
                                   mat.vmax, sv, _new_funct,
                                   f"MatS15_TV_{mat.mid}")
    fct4 = _resolve_fpe(state, label, mat, l0, l_init, _new_funct)

    prop_id = _muscle_prop_id(state, pid)
    title = part.title or f"MUSCLE_{pid}"
    lines = list(funct_lines)
    lines += _emit_prop_type46(
        prop_id, title,
        mass=0.0,                     # the card states none — never invented
        stiffness=0.0,
        vel_max=mat.vmax,
        force=mat.fmax,
        xk=0.0,
        fct1=fct1, fct2=fct2, fct3=fct3, fct4=fct4,
        idens=0,
        damp=0.0,                     # *MAT_S15 has no damping field
        epsi=1,                       # elongation form
        scale_t=0.0,                  # -> 1.0
        scale_x=0.0,                  # -> 1.0 (the transform is in the curve)
        scale_v=0.0,                  # -> 1.0 (ditto)
        scale_f=mat.fmax)
    lines += [f"/PART/{pid}", title, f"{_i(prop_id)}{_i(0)}{_i(0)}"]
    rows, eids = _spring_rows(state, pid, pairs, label)
    if rows is None:
        return None
    lines += rows
    for eid in eids:
        state.spring_elem_ids.add(eid)
        state.muscle_spring_eids.add(eid)
    state.warn(
        f"{label} -> /PROP/TYPE46/{prop_id} (SPR_MUSCLE) + {len(eids)} "
        f"/SPRING element(s), Epsi=1 (elongation form): Force = FMAX = "
        f"{mat.fmax:g}, Vel_max = VMAX = {mat.vmax:g}, Scale_F = FMAX (the "
        "passive function f_PE is NORMALIZED by FMAX, SDMAT15.cfg:38). The "
        "property carries NO MASS: *MAT_SPRING_MUSCLE states neither a density "
        "nor a mass, so none is invented — give the muscle nodes their mass "
        "with *ELEMENT_MASS if the model needs it. Per-element force history is "
        "NOT available: /TH/SPRING on a TYPE46 writes 15 channels of exact zero "
        "(measured), so these elements are deliberately left out of the "
        "*DATABASE_DEFORC group; use /TH/NODE REACX on an anchor node (an "
        "accumulated impulse — differentiate it) or the global SPRING ENERGY "
        "channel.")
    return lines


def _muscle_prop_id(state: ConversionState, pid: int) -> int:
    """A /PROP id for the muscle property of *pid*.

    The LS-DYNA SECID is preferred (it keeps the emitted deck readable against
    the source) but never reused blindly: /PROP is ONE Radioss namespace and
    k2rad writes /PROP/SHELL|SOLID|BEAM under the SECID verbatim, so a section
    that is ALSO used by a meshed part would collide — ERROR 79.
    """
    part = state.parts.get(pid)
    secid = (part.secid if part is not None and part.secid > 0 else pid)
    taken = (set(state.sec_shells) | set(state.sec_solids)
             | set(state.sec_beams) | set(state.sec_tshells)
             | set(state.sec_sph) | set(state.sec_seatbelts)
             | set(state.sec_discrete))
    if secid in taken:
        return state.next_prop_id()
    return secid


# ─────────────────────────────────────────────────────────────────────────────
# Function-slot resolvers (shared by the two sides)
# ─────────────────────────────────────────────────────────────────────────────

def _curve_points(state: ConversionState, lcid: int):
    c = state.curves.get(lcid)
    if c is None or len(c.pts) < 2:
        return None
    # state.curves points are ALREADY scaled and offset by the parser
    # (handlers.py:4397-4417 applies SFA/SFO/OFFA/OFFO at parse time), so the
    # LS-DYNA abscissa is exactly what is stored — the /MOVE_FUNCT ordering
    # defect dyna2rad has (shift-then-scale instead of scale-then-shift) cannot
    # arise here.
    return list(c.pts)


def _resolve_activation(state, label, value, lcid, field, new_funct, title):
    """``ALM`` / ``A`` → fct_id1: the activation level, abscissa = time."""
    if lcid:
        pts = _curve_points(state, lcid)
        if pts is None:
            state.warn(
                f"{label}: {field} names curve {lcid}, which the deck does not "
                "define (or which has fewer than two points). The activation "
                "level is the whole ACTIVE force of the muscle, so a constant "
                "ZERO curve is emitted instead of an invented activation — the "
                "muscle keeps only its passive term. Every /PROP/TYPE46 "
                "function slot must be non-zero: GET_U_FUNC(0) returns 0 and "
                "would silently kill the active product anyway (ruser46.F:207).")
            return new_funct(title + "_missing", _const_curve(0.0))
        return lcid
    return new_funct(title, _const_curve(value))


def _verbatim_curve(state, label, lcid, field, new_funct, title, fallback):
    """A curve slot whose abscissa needs no transform."""
    pts = _curve_points(state, lcid)
    if pts is None:
        state.warn(
            f"{label}: {field} names curve {lcid}, which the deck does not "
            f"define (or which has fewer than two points) — a constant "
            f"{fallback:g} function is emitted in its place. A zero fct_id is "
            "NOT an option: GET_U_FUNC(0) returns 0 and the whole active force "
            "product collapses to zero at 0 starter errors (ruser46.F:207, "
            "measured).")
        return new_funct(title + "_missing", _const_curve(fallback))
    return lcid


def _resolve_lambda_curve(state, label, value, lcid, field, sno,
                          _unused, fallback, new_funct, title):
    """``SVS`` → fct_id2: active tension vs the STRETCH RATIO lambda.

    Radioss's Epsi=0 abscissa is ``L/L0 - 1`` and ``lambda = SNO*L/L0``, so the
    transform is ``x = lambda/SNO - 1``.
    """
    if not lcid:
        return new_funct(title, _const_curve(fallback))
    pts = _curve_points(state, lcid)
    if pts is None:
        state.warn(
            f"{label}: {field} names curve {lcid}, which the deck does not "
            f"define — a constant {fallback:g} function is emitted in its "
            "place (a zero fct_id would kill the whole active product).")
        return new_funct(title + "_missing", _const_curve(fallback))
    return new_funct(title, [(lam / sno - 1.0, y) for lam, y in pts])


def _resolve_length_curve(state, label, value, lcid, field, l0, l_init,
                          new_funct, title):
    """``TL`` → fct_id2 on the S15 side: active tension vs the length ratio
    ``L = L_M/L0``. Radioss's Epsi=1 abscissa is the ELONGATION, so
    ``X = L*L0 - l_init``."""
    if not lcid:
        return new_funct(title, _const_curve(value if value else 1.0))
    pts = _curve_points(state, lcid)
    if pts is None:
        state.warn(
            f"{label}: {field} names curve {lcid}, which the deck does not "
            "define — a constant 1.0 function is emitted in its place (a zero "
            "fct_id would kill the whole active product).")
        return new_funct(title + "_missing", _const_curve(1.0))
    return new_funct(title, [(ratio * l0 - l_init, y) for ratio, y in pts])


def _resolve_velocity_curve(state, label, value, lcid, field, vmax, sv,
                            new_funct, title):
    """``TV`` → fct_id3 on the S15 side: active tension vs the normalised
    velocity ``V = V_M/(V_max*S_v)``. Radioss's Epsi=1 abscissa is the raw
    velocity, so ``v = V*VMAX*SV``."""
    if not lcid:
        return new_funct(title, _const_curve(value if value else 1.0))
    pts = _curve_points(state, lcid)
    if pts is None:
        state.warn(
            f"{label}: {field} names curve {lcid}, which the deck does not "
            "define — a constant 1.0 function is emitted in its place (a zero "
            "fct_id would kill the whole active product).")
        return new_funct(title + "_missing", _const_curve(1.0))
    scale = vmax * sv
    if scale == 0.0:
        state.warn(
            f"{label}: {field} is a normalised-velocity curve but VMAX*SV = 0, "
            "so its abscissa cannot be de-normalised — a constant 1.0 function "
            "is emitted instead (the velocity dependence of the active force "
            "is LOST). Set VMAX on the *MAT_SPRING_MUSCLE card.")
        return new_funct(title + "_novmax", _const_curve(1.0))
    return new_funct(title, [(v * scale, y) for v, y in pts])


def _resolve_ssp(state, label, mat: MatMuscle, sno: float, new_funct) -> int:
    """``SSP`` → fct_id4 on the 156 side: the dimensionless passive stress."""
    title = f"MatL156_SSP_{mat.mid}"
    if mat.ssp_lcid:
        if mat.ssp_lcid in state.define_tables or \
                mat.ssp_lcid in state.define_tables_3d:
            state.warn(
                f"{label}: SSP names TABLE {mat.ssp_lcid} — the manual's "
                "h(eps_bar_dot, lambda) form, a passive stress that depends on "
                "BOTH the stretch and the strain rate (Vol II R17 p.2-1073). "
                "/PROP/TYPE46's fct_id4 is a 1-D function of the stretch only "
                "(ruser46.F:210), so the rate dependence has no slot: the "
                "passive term is DROPPED (a constant-zero function) rather "
                "than silently reinterpreting one row of the table as the whole "
                "law. dyna2rad hands the table id straight to fct_id4 as if it "
                "were a /FUNCT.")
            return new_funct(title + "_table", _const_curve(0.0))
        pts = _curve_points(state, mat.ssp_lcid)
        if pts is None:
            state.warn(
                f"{label}: SSP names curve {mat.ssp_lcid}, which the deck does "
                "not define — the passive term is dropped (constant-zero "
                "function).")
            return new_funct(title + "_missing", _const_curve(0.0))
        return new_funct(title, [(lam / sno - 1.0, y) for lam, y in pts])
    if mat.ssp > 0.0:
        # "GT.0.0: constant value of 0.0 is used" (mat_156.cfg:57).
        return new_funct(title + "_zero", _const_curve(0.0))
    pts = _muscle_exponential_ssp(mat.ssm, mat.cer)
    if pts is None:
        state.warn(
            f"{label}: SSP = 0 selects the built-in exponential passive law "
            f"h(eps), but SSM = {mat.ssm:g} and CER = {mat.cer:g} make it "
            "undefined (h = (exp(CER*eps/SSM)-1)/(exp(CER)-1) divides by SSM "
            "and by exp(CER)-1, Vol II R17 p.2-1073). The passive term is "
            "dropped (constant-zero function) — dyna2rad has no guard here and "
            "divides by zero.")
        return new_funct(title + "_undef", _const_curve(0.0))
    return new_funct(title, [((1.0 + eps) / sno - 1.0, y) for eps, y in pts])


def _resolve_fpe(state, label, mat: MatSpringMuscle, l0: float, l_init: float,
                 new_funct) -> int:
    """``FPE`` → fct_id4 on the S15 side: the NORMALIZED passive force."""
    title = f"MatS15_FPE_{mat.mid}"
    if mat.fpe_lcid:
        pts = _curve_points(state, mat.fpe_lcid)
        if pts is None:
            state.warn(
                f"{label}: FPE names curve {mat.fpe_lcid}, which the deck does "
                "not define — the passive term is dropped (constant-zero "
                "function).")
            return new_funct(title + "_missing", _const_curve(0.0))
        return new_funct(title, [(ratio * l0 - l_init, y) for ratio, y in pts])
    if mat.fpe > 0.0:
        return new_funct(title + "_zero", _const_curve(0.0))
    pts = _muscle_exponential_fpe(mat.lmax, mat.ksh)
    if pts is None:
        state.warn(
            f"{label}: FPE = 0 selects the built-in exponential passive law, "
            f"but LMAX = {mat.lmax:g} makes it undefined "
            "(f_PE = (exp(Ksh*(L-1)/Lmax)-1)/(exp(Ksh)-1), Vol II R17 "
            "p.2-2097). The passive term is dropped (constant-zero function) — "
            "dyna2rad leaves fct_id4 at 0 here, which is an out-of-bounds "
            "GET_U_FUNC(0) read rather than a documented 'no function'.")
        return new_funct(title + "_undef", _const_curve(0.0))
    return new_funct(title, [((1.0 + u) * l0 - l_init, y) for u, y in pts])
