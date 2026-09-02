"""Thermal expansion, the temperature drivers, and the heat-source boundaries.

  ``*MAT_ADD_THERMAL_EXPANSION``            → ``/THERM_STRESS/MAT`` + ``/HEAT/MAT``
  ``*MAT_THERMAL_ISOTROPIC`` via ``*PART`` TMID → the ``/HEAT/MAT`` values
  ``*MAT_THERMAL_ISOTROPIC_TD[_LC]``        → the same, by a LEAST-SQUARES fit
  ``*MAT_THERMAL_ORTHOTROPIC``              → the same, when K1 = K2 = K3
  ``*INITIAL_TEMPERATURE_{SET,NODE}``       → ``/INITEMP`` on a ``/GRNOD``
  ``*LOAD_THERMAL_{CONSTANT,LOAD_CURVE,VARIABLE}[_NODE]`` → ``/IMPTEMP``
  ``*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_<FAMILY>`` → ``/IMPTEMP``
  ``*BOUNDARY_TEMPERATURE_{SET,NODE}``      → ``/IMPTEMP``
  ``*BOUNDARY_FLUX_{SEGMENT,SET}``          → ``/IMPFLUX``   (the SIGN is FLIPPED)
  ``*BOUNDARY_CONVECTION_{SEGMENT,SET}``    → ``/CONVEC``
  ``*BOUNDARY_RADIATION_{SEGMENT,SET}``     → ``/RADIATION`` (E = FMULT / sigma)

The two ENGINE thermal keywords ``/DT/THERM`` and ``/THERM`` live in
``writer/assembly.py::_make_engine_thermal``, beside the ``/DT`` family they
belong to.

**Why the drivers ship WITH the expansion card.** Radioss's thermal expansion is
INCREMENTAL, not secant: the engine computes ``ETH = alpha(T)·Fscale ·
(T_n − T_{n−1})`` and accumulates it cycle by cycle (shells ``cmain3.F:235-240``
via ``thermexpc.F:172-174``, solids inline at ``mmain.F90:770-786``). With a
``/HEAT/MAT`` but no temperature driver, ``DTEMP`` is identically zero on every
cycle, so the emitted ``/THERM_STRESS/MAT`` does exactly nothing while the
starter reports 0 errors and echoes it happily. Shipping the card alone would be
unverifiable by construction.

**The three gates that decide whether anything happens at all.**

* ``/THERM_STRESS/MAT`` on a material with no ``/HEAT/MAT`` is a HARD
  ``ERROR 1129`` (``hm_read_therm_stress.F90:130-132``: ``jthe =
  mat_param(imat)%itherm; if (jthe == 0) ancmsg(msgid=1129, msgtype=msgerror)``).
  The pair is mandatory, so every expanding material gets both.
* ``Fct_ID_T = 0`` with a scale factor produces **NO expansion at all** —
  ``alpha = FINTER(0, T)·Fscale = 0``. Measured twice on independent code paths:
  a free solid bar gave ``DX ≡ 0`` and a clamped LAW2 shell ``F1 ≡ 0``. That is
  exactly the card dyna2rad writes for a constant coefficient
  (``convertmats.cxx:12261-12266``), so a constant LS-DYNA ``MULT`` must become
  a synthesized two-point ``/FUNCT``, never a bare scale.
* A ``Fct_ID_T`` the deck does not define is **accepted at 0 errors** and
  reinterpreted as an internal function index — ``hm_read_therm_stress.F90:
  121-128``'s "unknown function" path is dead code (``ifunc_alpha = func_id`` is
  pre-set before the search loop, so ``if (ifunc_alpha == 0)`` can never fire).
  Every function id is therefore resolved here, at conversion time.

**Isotropic only, on this build.** The single ``mat_THERM_STRESS.cfg`` in the cfg
tree declares exactly two cells — ``COMMENT("# Fct_ID_T            Fscale_y")`` /
``CARD("%10d%20lg", FUNCT_ID, CLOAD_SCALE_Y)`` — and the reader reads only those
two. dyna2rad's ``Fscale_x/y/z`` + ``Fct_ID_Tx/T/Tz`` is a NEWER card shape, so
five of its six writes go nowhere and the two that land are the wrong pair
(``Fct_ID_T ← LCIDY``, ``Fscale_y ← MULTY``): measured on the corpus carrier's
own numbers, the converted coefficient came out **1.0 instead of 1.2e-5**, a
factor 8.3e4, silently. Here ``LCID``/``MULT`` are the pair that is carried.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from ..state import (ConversionState, Curve, ImposedTemperature,
                     InitialTemperature, MatPlasTAB,
                     MatThermalIsotropicTD, MatThermalOrthotropic)
from .common import HDR, _emit_grnod_node, _emit_surf_seg, _f, _i

__all__ = [
    "_resolve_thermal",
    "_make_thermal",
    "_thermal_solve_active",
    "_emit_heat_mat",
    "_emit_therm_stress",
    "_sigma_deck",
]


#: ``EFRAC`` — the fraction of strain energy converted into heat. The reader
#: clamps it to (0, 1] and turns a BLANK/0 into **1.0**
#: (``hm_read_therm.F:241``), i.e. "convert all of it", which is the opposite of
#: what a structural deck driving its temperature from outside states. LS-DYNA's
#: ``*LOAD_THERMAL_*`` and ``*BOUNDARY_TEMPERATURE`` prescribe the temperature
#: field outright — no plastic-work conversion is part of that model — so the
#: cell carries the smallest positive number instead of the blank that would
#: mean 1.0. It also keeps the capacity term away from a 0/0.
#:
#: It really does reach BOTH engine source paths, which is worth stating because
#: they look independent. ``hm_read_therm.F:251`` stores it in ``PM(90)``, and
#: for a law with ``HEAT_FLAG = 0`` — every law in this converter except LAW4/
#: 74/84/104/109 — ``cmain3.F:360`` computes the nodal source as
#: ``DIE = d(EINT)·PM(90)`` before ``cforc3.F:696`` hands ``DIE`` to ``THERMC``
#: (``thermc.F:83``: ``A = DIE/4`` per node). The ``FHEAT`` accumulators the
#: laws fill themselves (``sigeps02c.F:222``) are only read on the
#: ``HEAT_FLAG = 1`` branch.
_EFRAC_OFF = 1.0e-20

#: The last-resort volumetric heat capacity, used when neither a
#: ``*MAT_THERMAL_*`` nor the mechanical law itself states one. With
#: ``AS = BS = 0`` there is no conduction, and on a deck with no
#: ``*CONTROL_THERMAL_SOLVER`` (``EFRAC = _EFRAC_OFF``) no strain-energy source
#: either, so the nodal heat balance has no term at all and the capacity NEVER
#: divides anything that is non-zero. It exists only so the cell is not zero —
#: ``hm_read_therm.F:236-237`` guards its own division with
#: ``max(1e-20, RHO_CP)``, but the engine's capacity matrix does not. A deck
#: that DOES state FWORK is told, where the placeholder is chosen, that the
#: source is live and the capacity therefore paces a real temperature.
_RHO_CP_PLACEHOLDER = 1.0


#: The Stefan-Boltzmann constant in SI, ``constant_mod.F:933``
#: (``STEFBOLTZ = 5.6704/EP08``). The STARTER supplies it itself —
#: ``hm_read_radiation.F:140-142`` computes
#: ``SIGMA = STEFBOLTZ*FAC_T**3/FAC_M`` and stores ``FAC(3) = EMI*SIGMA`` — so
#: the ``E`` cell of ``/RADIATION`` is a bare EMISSIVITY while LS-DYNA's
#: ``FMULT`` is ``f = sigma*eps*F`` with sigma already in it (Vol I R17
#: p.5-117 Remark 1). The two differ by exactly this number in the deck's own
#: unit system, which is why ``_sigma_deck`` exists.
_STEFAN_BOLTZMANN_SI = 5.6704e-8

#: SI value of one deck unit, per ``unit_code.F:99-151``: the metric prefix
#: table, then ``IF (KEY(1:4) == 'MASS') FAC = FAC*1e-3`` because *"L'unite SI
#: de masse est le kg et pas le g"*. Only mass and time are needed (sigma has
#: dimension ``M T^-3 Theta^-4``), and the starter reads exactly those two
#: (``FAC_M_WORK``, ``FAC_T_WORK``).
_SI_PREFIX = {
    "y": 1e-24, "z": 1e-21, "a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9,
    "u": 1e-6, "mu": 1e-6, "m": 1e-3, "c": 1e-2, "d": 1e-1, "": 1.0,
    "da": 1e1, "h": 1e2, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
    "P": 1e15, "E": 1e18, "Z": 1e21, "Y": 1e24,
}


def _unit_factor(label: str, base: str) -> Optional[float]:
    """The SI value of the unit spelled *label* (e.g. ``"Mg"`` → 1e3).

    *base* is the SI base symbol the label must end in (``g``, ``m``, ``s``);
    ``unit_code.F:153-158`` answers ERROR 573 for anything else, so an
    unrecognised label returns ``None`` and the caller refuses rather than
    guessing.
    """
    if not label.endswith(base):
        return None
    fac = _SI_PREFIX.get(label[:-len(base)])
    if fac is None:
        return None
    return fac * (1e-3 if base == "g" else 1.0)


def _sigma_deck(state: ConversionState) -> Optional[float]:
    """The Stefan-Boltzmann constant in the deck's own units, or ``None``.

    ``sigma_deck = STEFBOLTZ * FAC_T**3 / FAC_M`` — the starter's own line,
    with ``FAC_*_WORK`` taken from the WORK unit line of ``/BEGIN``
    (``writer/output.py`` writes ``state.units`` to both /BEGIN lines).
    For the default ``Mg mm s`` this is ``5.6704e-8 * 1 / 1e3 = 5.6704e-11``
    — MEASURED on a one-segment /RADIATION probe (predicted 0.05625161 mJ from
    that value, engine reported 0.056251513; the SI value would have given
    56.25 mJ, 1000x off), and independently confirmed by Vol I R17 p.12-567,
    whose hot-stamping (Mg-mm-s) example writes ``sbc = 5.67e-11``.
    """
    mass, _length, time = state.units
    fac_m = _unit_factor(mass, "g")
    fac_t = _unit_factor(time, "s")
    if fac_m is None or fac_t is None or fac_m <= 0.0:
        return None
    return _STEFAN_BOLTZMANN_SI * fac_t ** 3 / fac_m


def _min_element_edge(state: ConversionState) -> float:
    """The shortest node-pair distance in the connectivity walk, or 0.0.

    A cheap, slightly CONSERVATIVE proxy for the engine's own ``DELTAX``: on a
    well-shaped hexahedron ``DELTAX`` is the volume over the largest face area,
    which equals the edge length on a cube and is smaller on a sliver — so a
    thermal step estimated from this length is never smaller than the engine's,
    and the guard it feeds errs toward warning.

    It is deliberately NOT called "the shortest element edge": the walk is
    ``n[i] -> n[(i+1) % len(n)]`` over the element's cyclic node list, so on an
    8-node hexahedron it also measures 4->5 and 8->1, which are face/body
    diagonals rather than edges. That only makes the answer SMALLER (sqrt(2) on
    a unit cube), i.e. more conservative, so no guard is weakened by it — but
    the quantity is a node-pair distance, and the messages say so.
    """
    best = 0.0
    nodes = state.nodes

    def _edge(a: int, b: int) -> None:
        nonlocal best
        na, nb = nodes.get(a), nodes.get(b)
        if na is None or nb is None:
            return
        d = ((na.x - nb.x) ** 2 + (na.y - nb.y) ** 2
             + (na.z - nb.z) ** 2) ** 0.5
        if d > 0.0 and (best == 0.0 or d < best):
            best = d

    for e in state.solid_elems:
        n = [x for x in e.nodes if x]
        for i in range(len(n)):
            _edge(n[i], n[(i + 1) % len(n)])
    for cont in (state.shell_elems, state.tshell_elems):
        for e in cont:
            n = [x for x in e.nodes if x]
            for i in range(len(n)):
                _edge(n[i], n[(i + 1) % len(n)])
    for e in state.beam_elems:
        _edge(e.n1, e.n2)
    return best


def _surface_load_concentration(state: ConversionState) -> float:
    """How many loaded faces one node carries per element that feeds it.

    The thermal sources split a segment's heat over the segment's own nodes
    (``convec.F:152``, ``radiation.F:155``, ``fixflux.F:167``) while the node's
    capacity ``MCP`` is the sum over the elements that touch it
    (``cinmas.F``). For a node touched by ``s`` loaded segments and ``e``
    elements of edge ``Lc``, one explicit step moves it by

        dT_step = (s · h·ΔT·dt·Lc²/4) / (e · rhoCp·Lc³/8) = 2·(s/e)·dt/tau·ΔT

    with ``tau = rhoCp·Lc/h``. So ``r = max(s/e)`` is the factor by which a
    node's real surface time constant is SHORTER than ``tau``, and it is a
    property of the emitted deck, not an assumption:

    * a thick mesh whose outer layer is loaded on one side gives ``r = 1``
      (a face-interior node sees 4 loaded segments and 4 elements; a corner
      node sees 1 and 1) — the case the guard was written for;
    * a body ONE element thick with all six faces loaded gives ``r = 3``, and
      its true lumped constant is ``rhoCp·(V/A)/h = tau/6``, which is exactly
      ``tau/(2r)``.

    Returns 1.0 when nothing can be counted, so the guard degrades to its
    previous arithmetic rather than to a weaker one.
    """
    seg_count: Dict[int, int] = defaultdict(int)
    for bc in state.thermal_boundaries:
        if not bc.surf_id or not bc.segments:
            continue
        for seg in bc.segments:
            for nid in set(seg):
                seg_count[nid] += 1
    if not seg_count:
        return 1.0
    elem_count: Dict[int, int] = defaultdict(int)
    for cont in (state.solid_elems, state.shell_elems, state.tshell_elems):
        for e in cont:
            for nid in {x for x in e.nodes if x}:
                elem_count[nid] += 1
    best = 1.0
    for nid, s in seg_count.items():
        e = elem_count.get(nid, 0)
        if e > 0:
            best = max(best, s / e)
    return best


def _thermal_step_estimate(state: ConversionState) -> Optional[float]:
    """The conduction stability step ``/DT/THERM`` will pace the run with.

    ``dt_therm = DTFACTHERM · 0.5 · DELTAX² · RHO0_CP / max(k, 1e-20)`` —
    ``mqviscb.F:666`` for solids and ``dttherm.F90:116`` for shells, with
    ``DTFACTHERM`` at its default 0.9 and ``k = AS + BS·T`` evaluated at the
    deck's own ``T0``. The WORST (smallest) material is what paces the run, so
    the largest ``k/RHO0_CP`` wins.

    ``None`` when no emitted ``/HEAT/MAT`` states a conductivity — the step is
    then unbounded (``max(k, 1e-20)``) and the run is paced by ``TSTOP``.
    """
    lc = _min_element_edge(state)
    if lc <= 0.0:
        return None
    worst = None
    for t0, rho_cp, a_s, bs, _t1, _al, _bl, _ef in state.heat_mat_cards.values():
        k = a_s + bs * t0
        if k <= 0.0 or rho_cp <= 0.0:
            continue
        dt = 0.9 * 0.5 * lc * lc * rho_cp / k
        if worst is None or dt < worst:
            worst = dt
    return worst


def _thermal_solve_active(state: ConversionState) -> bool:
    """True when the converted deck really MAKES A TEMPERATURE CHANGE.

    Both halves are required, and both are read from what was actually
    EMITTED, never from what was parsed:

    * a ``/HEAT/MAT`` arms ``MAT_PARAM%ITHERM`` (``hm_read_therm.F:253``),
      which ``hm_read_part.F:366`` → ``ale_euler_init.F:193-201`` turns into
      ``GLOB_THERM%ITHERM_FE`` for every PART on that material. That flag is
      the gate on EVERY thermal action in the engine — ``resol.F:2994``
      (CONVEC), ``:3006`` (RADIATION), ``:3025`` (FIXFLUX), ``:1802``/``:7450``
      (FIXTEMP) and ``:6736`` (TEMPUR) — so it stays mandatory;
    * a temperature-moving card was actually WRITTEN, never merely parsed.
      ``thermal_driver_emitted`` is set at the line that writes an ``/IMPTEMP``
      and ``thermal_source_emitted`` at the line that writes a ``/CONVEC``,
      ``/RADIATION`` or ``/IMPFLUX``, i.e. after the set has been resolved.
      Several corpus decks state a driver whose ``*SET_NODE_GENERAL`` /
      ``*SET_NODE_LIST_GENERATE`` k2rad does not read, so the driver is dropped
      at emission — reading the PARSED list here would call those decks
      "thermal" and ship a frozen fringe.

    All four cards were MEASURED to move the temperature on their own. The
    ``/CONVEC`` probe is the discriminating one, because it needs neither an
    ``/IMPTEMP`` nor an engine card: ``/HEAT/MAT`` + ``/CONVEC``, every node in
    ``/BCS 111 111``, ran 7011 cycles and the engine's own accounting
    (``thermbilan.F:71-76``) reported ``CONVECTION HEAT = 68.120647`` mJ =
    ``HEAT STORED``; the twin with the ``/CONVEC`` removed stored 7.4e-32.

    An ``/INITEMP`` alone is deliberately NOT enough: it is a STATE, not a
    driver. A uniform initial temperature with nothing to change it leaves
    ``DTEMP`` identically zero on every cycle, so the /THERM_STRESS does
    nothing and the TEMP channel is a flat line — the #122 case exactly.

    **An IMPLICIT or MODAL run is not enough either, for the same reason.**
    MEASURED on a twin pair of converted decks (a 10-brick bar, /HEAT/MAT
    AS = 50, an /IMPTEMP holding the x = 0 face at 400 K against an /INITEMP of
    300): the EXPLICIT deck carries the far end 300 -> 399.731 -> 400.000 K
    over 84 111 cycles, while the same ``.k`` plus a
    ``*CONTROL_IMPLICIT_GENERAL`` runs 61 implicit cycles with the far end at
    exactly 300.000 K at every state and ``HEAT STORED = 0.0000000``.

    The MECHANISM is not "the thermal routines are unreachable from the
    implicit path" — they ARE reached: ``resol.F:1802/2994/3006/3025`` gate
    FIXTEMP / CONVEC / RADIATION / FIXFLUX on ``GLOB_THERM%ITHERM_FE`` alone,
    with no ``IMPL_S`` test, so the imposed nodes really are reset and the
    source counters really do fill. What is dead is the accumulation:
    ``resol.F:6547``, inside ``IF (IMPL_S == 1)``, is a ``GOTO 111`` to the
    label at ``:7949``, which skips the ``IF (ILAG + IALE + IEULER /= 0)``
    block opened at ``:6552`` — and the single ``CALL TEMPUR`` lives inside it
    at ``:6736``. ``tempur.F:51-58`` is the whole integrator
    (``TEMP += FTHE/MCP``) and the only writer of ``HEAT_STORED``, so on an
    implicit cycle FTHE is filled and never spent. A temperature channel on an
    implicit deck would therefore be the flat fringe this predicate exists to
    prevent, and ``_make_engine_thermal`` excludes the same two run types for
    the same reason.
    """
    if state.is_implicit or state.is_modal:
        return False
    return bool(state.heat_mat_cards
                and (state.thermal_driver_emitted
                     or state.thermal_source_emitted))


# ─────────────────────────────────────────────────────────────────────────────
# Card emitters
# ─────────────────────────────────────────────────────────────────────────────

def _emit_heat_mat(mid: int, t0: float, rho0_cp: float, a_s: float, bs: float,
                   t1: float, al: float, bl: float, efrac: float) -> List[str]:
    """/HEAT/MAT/<mat_ID>.

    Layout audited against ``hm_cfg_files/config/CFG/radioss2022/MAT/
    mat_HEAT.cfg`` — the 2022 FORMAT block, which is what a ``/BEGIN 2022`` deck
    reads:
      C1: T0(20) RHO0_CP(20) AS(20) BS(20)
      C2: T1(20) AL(20) BL(20) EFRAC(20)
    There is **no title line** and **no Iform cell**. The 2018 block adds
    ``Iform`` in columns 81-90; twin-decked at both ``/BEGIN`` versions, writing
    it at 2022 gives ``WARNING 100213 "unsupported field exists at the end of
    line"`` and the cell is dropped — benign but pointless, so it is never
    written (the #119 rule, case (a)).

    **``AL``/``BL`` are the SECOND SEGMENT of a piecewise-linear k(T), not a
    liquid-phase afterthought, and they must never be left at 0 beside a real
    ``T1``.** ``dttherm.F90:102-106`` (shells) and ``mqviscb.F:653-657``
    (solids) both read

        if (tempel(i) < tmelt) then ; akk = as + bs*tempel(i)
        else                        ; akk = al + bl*tempel(i)

    **What ``AL = BL = 0`` breaks is NOT the conduction.** Those two are the
    thermal TIME-STEP routines (``dttherm.F90``'s six callers all gate on
    ``JTHE /= 0 .AND. GLOB_THERM%IDT_THERM == 1``; ``mqviscb.F:644`` is
    ``JTHE < 0 .AND. IDT_THERM == 1``), and every Lagrangian conduction
    operator reads ``AS``/``BS`` (``PM(75)``/``PM(76)``) unconditionally and
    never looks at ``AL``/``BL``/``TMELT`` — ``stherm.F:106``, ``s4therm.F:84``,
    ``s4therm-itet1.F:135``, ``s8etherm.F:110``, ``s10therm.F:81``,
    ``s20therm.F:79``, ``sctherm.F:94``, ``s6ctherm.F:95``, ``thermc.F:69``,
    ``therm3c.F:72``, ``cbatherm.F:67``, ``pforc3.F:382``. So a zero second
    segment costs the ``/DT/THERM`` step (which becomes
    ``DTFACTHERM*0.5*Lc^2*rhoCp/1e-20`` above ``T1`` and jumps the whole run in
    one step) and the element conductance ``CONDE`` the same loop computes —
    not the heat flow. It is still wrong to leave at 0, which is why the caller
    mirrors ``AS``/``BS`` into ``AL``/``BL`` unless the deck states a second
    segment of its own; the mirror ALSO keeps the ALE (``atherm.F:137``), SPH
    (``forintp.F:336/350``), ``/INTER/TYPE9`` (``i9grd2.F:140``,
    ``i9grd3.F:164``) and rigid-wall (``rgwat2.F:176``, ``rgwat3.F:213``)
    readers of ``PM(77)``/``PM(78)`` seeing the same line.
    """
    return [
        f"/HEAT/MAT/{mid}",
        "#                 T0             RHO0_CP                  AS"
        "                  BS",
        f"{_f(t0)}{_f(rho0_cp)}{_f(a_s)}{_f(bs)}",
        "#                 T1                  AL                  BL"
        "               EFRAC",
        f"{_f(t1)}{_f(al)}{_f(bl)}{_f(efrac)}",
        HDR,
    ]


def _emit_therm_stress(mid: int, func_id: int, fscale: float) -> List[str]:
    """/THERM_STRESS/MAT/<mat_ID>.

    Layout audited against ``hm_cfg_files/config/CFG/radioss110/MAT/
    mat_THERM_STRESS.cfg`` — the only such cfg in the tree, whose newest FORMAT
    block is ``radioss90``, so that is what a 2022 deck reads:
      ``# Fct_ID_T            Fscale_y`` / ``%10d%20lg``
    One line, no title, isotropic.
    """
    return [
        f"/THERM_STRESS/MAT/{mid}",
        "# Fct_ID_T            Fscale_y",
        f"{_i(func_id)}{_f(fscale)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Resolution
# ─────────────────────────────────────────────────────────────────────────────

def _material_registries(state: ConversionState):
    """Every ``mid -> dataclass`` material dict a /MAT is emitted from and that
    a ``*MAT_ADD_THERMAL_EXPANSION`` may have to SPLIT.

    Four /MAT producers are deliberately NOT here, because a
    ``dataclasses.replace(..., mid=new)`` of their record does not give a
    working copy — each needs a second card that is keyed elsewhere:
    ``mat_high_explosive`` (``_emit_mat_law5`` takes its JWL from
    ``state.eos_jwl.get(mid)``, a SECOND dict keyed by the old mid that a
    record copy does not bring — the clone would come out with no /EOS),
    ``mat_laminated_glass`` (a LAW27 PAIR: ``_emit_mat_law27_pair`` writes one
    card under ``mat.mid`` and one under the record's own reserved
    ``glass_mid``, and a copy KEEPS that second id — so the clone would write
    a duplicate ``/MAT/LAW27/{glass_mid}``, starter ERROR 79),
    ``mat_seatbelt`` (LAW114/119 is synthesized per belt PROPERTY, not per mid)
    and ``mat_spotweld`` (its /MAT/ELAST fallback is written by the connector
    writer). A card naming one of them is warn-dropped rather than half-split;
    the warning says so by name instead of claiming the material is unconverted.

    ``mat_composite_damage`` used to be a fifth, on the ground that *MAT_022's
    shell arm writes a companion ``/FAIL/CHANG`` a bare copy would strand. That
    reason was FALSE and is why the entry is here now: ``_emit_fail_chang``
    writes ``f"/FAIL/CHANG/{mat.mid}"`` from the record it is handed, so the
    rider is GENERATED for the clone and follows it. That is the opposite of
    both cases above — nothing is looked up in a second dict, and no second id
    travels on the record to be duplicated. Adding it also gives
    ``_structural_density`` a MAT_022 ``rho`` to read.
    """
    return [
        state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
        state.mat_johnson_cook, state.mat_aniso_visco, state.mat_rigid,
        state.mat_null, state.mat_power_law, state.mat_samp,
        state.mat_crushable_foam, state.mat_low_density_foam,
        state.mat_fu_chang_foam, state.mat_honeycomb, state.mat_soil_and_foam,
        state.mat_low_density_viscous_foam, state.mat_modified_honeycomb,
        state.mat_deshpande_fleck, state.mat_hill_foam, state.mat_blatz_ko,
        state.mat_mooney_rivlin, state.mat_ogden, state.mat_hyper_rubber,
        state.mat_orthotropic, state.mat_enhanced_composite,
        state.mat_transverse_aniso, state.mat_iso_elas_plas,
        state.mat_strain_rate_plas, state.mat_gurson, state.mat_hill_3r,
        state.mat_plas_comp_tens, state.mat_viscoelastic,
        state.mat_kelvin_maxwell, state.mat_general_visco,
        state.mat_simplified_rubber, state.mat_soft_tissue,
        state.mat_cohesive_mixed_mode, state.mat_arup_adhesive,
        state.mat_cohesive_mm_epr, state.mat_toughened_adhesive,
        state.mat_tabulated_jc, state.mat_jh_ceramics, state.mat_jh_concrete,
        state.mat_elastic_fluid, state.mat_fabric, state.mat_shape_memory,
        state.mat_composite_damage,
    ]


def _clone_material(state: ConversionState, mid: int) -> Optional[int]:
    """Duplicate material *mid* under a fresh id and return it.

    ``*MAT_ADD_THERMAL_EXPANSION`` is keyed on a PART while
    ``/THERM_STRESS/MAT`` is keyed on a MATERIAL, so a material shared by a part
    that carries the card and a part that does not cannot be expressed at all
    without splitting it. The corpus carrier has exactly that shape — PIDs 1, 2
    and 3 on MID 1 with the card on PID 1 only — and dyna2rad simply expands all
    three.

    Every per-mid rider travels with the copy (``*MAT_ADD_EROSION`` →
    /FAIL/GENE1, ``*MAT_ADD_DAMAGE_GISSMO`` → /FAIL/TAB2,
    ``*MAT_ADD_DAMAGE_DIEM`` → /FAIL/INIEVO): a clone that lost its failure model
    would be a DIFFERENT material, not a copy of one.

    ``None`` when the mid names no converted material — the caller then leaves
    the parts alone rather than repointing them at nothing.
    """
    src = None
    holder = None
    for d in _material_registries(state):
        if mid in d:
            src, holder = d[mid], d
            break
    if src is None:
        return None
    new_mid = state.next_mat_id()
    holder[new_mid] = dataclasses.replace(src, mid=new_mid)
    for rider in (state.mat_add_erosion, state.fail_gissmo, state.fail_diem):
        if mid in rider:
            rider[new_mid] = dataclasses.replace(rider[mid], mid=new_mid)
    return new_mid


def _expansion_key(card) -> tuple:
    """What makes two ``*MAT_ADD_THERMAL_EXPANSION`` cards the SAME card."""
    return (card.lcid, card.mult, card.lcidy, card.multy,
            card.lcidz, card.multz, card.tref, card.has_tref)


def _warn_orthotropic_slots(state: ConversionState, mid: int, card) -> None:
    """Name the y/z direction pair — but only when it says something different.

    Manual rule (Vol II R17 p.2-147): *"For isotropic material models, LCID is
    the load curve ID ... In this case, LCIDY, MULTY, LCIDZ and MULTZ are
    ignored"*, and for the anisotropic case *"If zero, the coefficient ... is
    constant and equal to MULTY. **If MULTY = 0 as well, LCID and MULT define
    the coefficient**"*. So ``LCIDY = 0`` with ``MULTY = 1.0`` — which is what
    all five corpus carriers write — is NOT an orthotropic statement, it is the
    cfg's own default echoed back, and warning about it would fire on every
    correct deck (the #125 class). Only a y/z pair that genuinely differs from
    the x one is reported.
    """
    if not _is_anisotropic(state, mid):
        # "For isotropic material models ... LCIDY, MULTY, LCIDZ and MULTZ are
        # IGNORED" - by LS-DYNA itself. All five corpus carriers are isotropic
        # *MAT_ELASTIC and write MULTY = MULTZ = 1.0, so a warning that fired on
        # them would fire on every correct deck (the #125 class).
        return
    diffs = []
    for axis, lc, mult in (("y", card.lcidy, card.multy),
                           ("z", card.lcidz, card.multz)):
        if lc and lc != card.lcid:
            diffs.append(f"LCID{axis.upper()}={lc}")
        elif not lc and mult and card.lcid == 0 and mult != card.mult:
            diffs.append(f"MULT{axis.upper()}={mult:g}")
    if not diffs:
        return
    state.warn(
        f"*MAT_ADD_THERMAL_EXPANSION on material {mid}: "
        + ", ".join(diffs) +
        " state a DIFFERENT b-/c-direction expansion coefficient from the "
        "a-direction one, and this build's /THERM_STRESS/MAT is ISOTROPIC — its "
        "cfg (radioss110/MAT/mat_THERM_STRESS.cfg) is one line, 'Fct_ID_T "
        "Fscale_y', and hm_read_therm_stress.F90:119-120 reads exactly those "
        "two cells. Only the a-direction (LCID/MULT) pair is emitted; the "
        "orthotropic directions are DROPPED. (dyna2rad writes Fscale_x/y/z and "
        "Fct_ID_Tx/T/Tz, a NEWER card shape of which five of six writes go "
        "nowhere on this reader.)")


def _is_anisotropic(state: ConversionState, mid: int) -> bool:
    """True when the material is one of the ANISOTROPIC / ORTHOTROPIC families.

    This is the test the manual's own wording turns on: *"For isotropic
    material models, LCID is the load curve ID defining the thermal expansion
    coefficient ... In this case, LCIDY, MULTY, LCIDZ, and MULTZ are ignored"*
    (Vol II R17 p.2-147). On an isotropic material the y/z cells are not a
    statement at all, so nothing about them is worth reporting.
    """
    return (mid in state.mat_orthotropic or mid in state.mat_enhanced_composite
            or mid in state.mat_composite_damage
            or mid in state.mat_transverse_aniso or mid in state.mat_hill_3r
            or mid in state.mat_aniso_visco or mid in state.mat_fabric
            or mid in state.mat_soft_tissue)


def _expansion_is_resolvable(state: ConversionState, mid: int, card) -> bool:
    """Can ``_resolve_alpha_function`` produce a Fct_ID_T for this card?

    Asked BEFORE any material is cloned. ``_resolve_alpha_function`` has one
    failure mode — an ``LCID`` naming no usable ``*DEFINE_CURVE`` — and it has
    to be known in advance, because a clone made for a card that then emits no
    /THERM_STRESS/MAT is a duplicate /MAT referenced by a repointed part and
    carrying no thermal card at all: exactly the "pointless duplicate" the
    LAW109 refusal is ordered before the split to avoid.
    """
    if not card.lcid:
        return True                      # constant MULT -> synthesized /FUNCT
    curve = state.curves.get(card.lcid)
    if curve is not None and len(curve.pts) >= 2:
        return True
    state.warn(
        f"*MAT_ADD_THERMAL_EXPANSION on material {mid}: LCID={card.lcid} "
        "names no *DEFINE_CURVE in the deck (or one with fewer than two "
        "points). A Fct_ID_T the starter cannot resolve is NOT an error — "
        "hm_read_therm_stress.F90:121-128's unknown-function branch is dead "
        "code (ifunc_alpha is pre-set before the search loop), so the id would "
        "be stored raw and reinterpreted as an internal function INDEX, giving "
        "a silently wrong coefficient. No /THERM_STRESS/MAT is emitted for "
        "this material, and the material is NOT split off for it either.")
    return False


def _resolve_alpha_function(state: ConversionState, mid: int,
                            card) -> Tuple[int, float]:
    """The ``(Fct_ID_T, Fscale_y)`` pair for one material.

    * ``LCID > 0`` → the curve is ``alpha(T)`` and ``MULT`` scales it
      (*"Scale factor scaling load curve given by LCID"*). ``MULT = 0`` is the
      cfg's own default, which the reader turns into 1.0
      (``hm_read_therm_stress.F90:135``), so it is written as a blank.
    * ``LCID = 0`` → *"the thermal expansion coefficient is constant and equal
      to MULT"*. A SYNTHESIZED two-point ``/FUNCT`` carries it, because
      ``Fct_ID_T = 0`` + ``Fscale_y = alpha`` is measurably inert (see the
      module docstring).

    **Secant vs tangent.** LS-DYNA's ``TREF`` *"activates the secant
    approach"*: the thermal strain becomes ``alpha_sec(T)·(T − TREF)`` instead
    of the default incremental ``d(eps_th) = alpha(T) dT`` (Vol II p.2-148).
    Radioss has ONLY the incremental form, and the tangent coefficient of a
    secant law is ``alpha_tan(T) = alpha_sec(T) + (T − TREF)·d(alpha_sec)/dT``.
    For a CONSTANT coefficient the second term vanishes and the two conventions
    coincide exactly — which is the case in every corpus carrier — so nothing is
    transformed there. A non-constant curve WOULD need differentiating, and
    ``TREF`` has no Radioss slot at all, so both are warned about rather than
    silently reinterpreted.
    """
    if card.has_tref and card.tref != 0.0:
        state.warn(
            f"*MAT_ADD_THERMAL_EXPANSION on material {mid}: TREF="
            f"{card.tref:g} activates LS-DYNA's SECANT approach — the thermal "
            "strain becomes alpha(T)*(T-TREF) measured from that reference "
            "temperature (Vol II R17 p.2-148). Radioss is strictly INCREMENTAL "
            "(ETH = alpha(T)*(T_n - T_(n-1)), cmain3.F:235-240 / "
            "mmain.F90:770-786) and has no reference-temperature slot: the "
            "reference is whatever T the first cycle sees. TREF is DROPPED. "
            "For a CONSTANT coefficient the two conventions are identical, so "
            "this only matters when LCID names a temperature-dependent curve.")
    if card.lcid:
        curve = state.curves.get(card.lcid)
        if curve is None or len(curve.pts) < 2:
            # Unreachable in practice: every caller pre-checks (and reports)
            # this with _expansion_is_resolvable, so that a material is never
            # cloned for a card that ends up emitting nothing.
            return 0, 0.0
        if len(curve.pts) > 2 and any(
                abs(y - curve.pts[0][1]) > 1e-12 * max(abs(y), 1.0)
                for _x, y in curve.pts):
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION on material {mid}: LCID="
                f"{card.lcid} is a TEMPERATURE-DEPENDENT coefficient. It is "
                "carried through unchanged, which is right when the LS-DYNA "
                "card states a TANGENT coefficient (the default, TREF = 0) and "
                "wrong when it states a SECANT one — the tangent curve Radioss "
                "needs is then alpha_sec(T) + (T-TREF)*d(alpha_sec)/dT. Check "
                "TREF on the card; a constant coefficient is identical either "
                "way.")
        return card.lcid, card.mult
    # Constant coefficient -> a synthesized two-point /FUNCT.
    alpha = card.mult
    fid = state.next_curve_id()
    state.curves[fid] = Curve(
        lcid=fid, title=f"Auto_thermal_expansion_mat{mid}",
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
        pts=[(0.0, alpha), (1.0e6, alpha)])
    state.curve_order.append(fid)
    # Fscale_y is written as an explicit 1.0, not left at 0 for
    # hm_read_therm_stress.F90:135 to substitute: MULT is already IN the
    # synthesized ordinate, so the cell means "no further scaling" and should
    # say so. (Consumed value unchanged — the starter echoes THERMAL EXPANSION
    # FUNCTION SCALE FACTOR = 1.0 either way.)
    return fid, 1.0


def _law_melt_temperature(state: ConversionState, mid: int) -> float:
    """The mechanical law's own melting temperature, when it has one.

    ``/HEAT/MAT`` OVERWRITES it: ``hm_read_therm.F`` sets
    ``MAT_PARAM%THERM%TMELT = T1`` and that is exactly the variable
    ``mmain.F90:790`` divides by for the Johnson-Cook ``T*``. Measured on a
    LAW2 deck: the material echo says ``MELTING TEMPERATURE K = 1800`` while the
    ``/HEAT/MAT`` echo says ``TMELT = 1.0e+20``, so ``T* ≈ 0`` and the thermal
    softening is DEAD — at 0 warnings, because ``WARNING 764`` is gated on the
    Zerilli form only. Copying the law's own value into ``T1`` is what keeps it
    alive.
    """
    m = state.mat_johnson_cook.get(mid)
    if m is not None and getattr(m, "tmelt", 0.0) > 0.0:
        return m.tmelt
    return 0.0


def _thermal_material_for_part(state: ConversionState, pid: int):
    """The ``*MAT_THERMAL_*`` a part names through ``*PART`` TMID.

    Vol II R17 p.3-1: *"Thermal material properties are specified by a thermal
    material ID number (TMID). This number is INDEPENDENT of the material ID
    number (MID) ... In the same analysis identical TMID and MID numbers may
    exist."* — so TMID is its own namespace, but ONE namespace shared by every
    ``*MAT_THERMAL_*`` type. The three converted types are searched in a FIXED
    order so a deck that reuses one TMID gets a stable answer rather than a
    dict-order coin flip; ``_warn_duplicate_tmid`` is what NAMES such a deck.
    """
    part = state.parts.get(pid)
    if part is None or not part.tmid:
        return None
    for d in (state.mat_thermal_isotropic, state.mat_thermal_iso_td,
              state.mat_thermal_ortho):
        tm = d.get(part.tmid)
        if tm is not None:
            return tm
    return None


def _warn_duplicate_tmid(state: ConversionState) -> None:
    """One TMID used by two different ``*MAT_THERMAL_*`` types.

    TMID is ONE namespace shared by every thermal material type (Vol II R17
    p.3-1), so a deck that writes ``*MAT_THERMAL_ISOTROPIC 9`` and
    ``*MAT_THERMAL_ISOTROPIC_TD 9`` has stated two different materials under
    one id. ``_thermal_material_for_part`` resolves that deterministically, but
    silently — and a reader has no way to tell which card won. Named here.
    """
    order = (("*MAT_THERMAL_ISOTROPIC", state.mat_thermal_isotropic),
             ("*MAT_THERMAL_ISOTROPIC_TD[_LC]", state.mat_thermal_iso_td),
             ("*MAT_THERMAL_ORTHOTROPIC", state.mat_thermal_ortho))
    seen: Dict[int, List[str]] = defaultdict(list)
    for name, reg in order:
        for tmid in reg:
            seen[tmid].append(name)
    for tmid in sorted(seen):
        names = seen[tmid]
        if len(names) < 2:
            continue
        state.warn(
            f"TMID {tmid} is stated by {len(names)} different thermal "
            "material types (" + ", ".join(names) + "). TMID is ONE namespace "
            "shared by every *MAT_THERMAL_* type (Vol II R17 p.3-1), so this "
            "deck defines the same thermal material twice. k2rad resolves it "
            f"in a fixed order and uses the {names[0]} card; the other(s) are "
            "IGNORED for every *PART that names this TMID. Renumber them if "
            "two distinct materials were meant.")


def _unparsed_thermal_tmid(state: ConversionState, mid: int) -> int:
    """A ``*PART`` TMID that names a thermal material k2rad did not parse.

    ``_thermal_material_for_part`` searches the three registries this converter
    fills. Vol II R17 p.2-9 lists eighteen ``*MAT_T##`` slots and this batch
    parses four of them, so a ``*PART`` can perfectly well carry a TMID whose
    card landed in ``skipped_keywords`` — and then "no *PART TMID names one"
    would be a false premise. Returns the TMID, or 0.
    """
    for pid, part in sorted(state.parts.items()):
        if part.mid != mid:
            continue
        tmid = getattr(part, "tmid", 0)
        if tmid and _thermal_material_for_part(state, pid) is None:
            return tmid
    return 0


def _structural_density(state: ConversionState, mid: int) -> float:
    for d in _material_registries(state):
        m = d.get(mid)
        if m is not None:
            for name in ("rho", "ro", "rho_i"):
                v = getattr(m, name, None)
                if v:
                    return float(v)
    return 0.0


def _resolve_thermal(state: ConversionState) -> None:
    """Decide every /HEAT/MAT, /THERM_STRESS/MAT, boundary card and driver in
    one prepass.

    Runs BEFORE ``_make_functions`` (it registers the synthesized coefficient,
    driver and boundary-condition curves in ``state.curves``) and before
    ``_make_materials`` (it can SPLIT a material, which changes what that
    writer emits and what ``_target_mat_law`` answers).

    The entry gate lists every source of a thermal card. It has to: a deck
    whose only thermal content is a ``*BOUNDARY_CONVECTION`` still needs a
    ``/HEAT/MAT`` resolved for it, because ``ITHERM_FE`` is what gates the
    engine's ``CONVEC`` call (``resol.F:2994``) — the ``/CONVEC`` alone would
    be read, echoed and completely inert.
    """
    _warn_control_thermal_solver(state)
    if (state.mat_add_thermal_expansion or state.initial_temperatures
            or state.imposed_temperatures or state.mat_thermal_isotropic
            or state.mat_thermal_iso_td or state.mat_thermal_ortho
            or state.thermal_boundaries or state.load_thermal_elements):
        # FIRST, so nothing announces a conversion this then takes back: the
        # element resolver prints "-> /IMPTEMP over the elements' OWN nodes"
        # as it builds its records, and a drop two passes later would leave
        # that sentence standing on a deck that emits no /IMPTEMP at all
        # (the #130 class — a statement of what the deck will emit that does
        # not mirror the emitter's own drop conditions).
        _drop_load_thermal_on_thermal_soln(state)
        _resolve_load_thermal_elements(state)
        _resolve_expansion(state)
        _warn_duplicate_tmid(state)
        _resolve_heat_materials(state)
        _resolve_drivers(state)
        _resolve_thermal_boundaries(state)
    # Outside the gate: both read what was DECIDED above, and both have
    # something to say about a deck that states a *CONTROL_* card and no
    # thermal content at all.
    _warn_fwork(state)
    _warn_soln0_thermal(state)


#: *CONTROL_THERMAL_SOLVER's per-field verdicts, in card order. Each entry is
#: (attribute, printed name, the sentence that says why it has no counterpart).
#: Only FWORK (-> /HEAT/MAT EFRAC) and TSF (-> the engine /THERM) are absent
#: from this table, because they are the two that MAP; SBC gets its own arm
#: below, because it is a CROSS-CHECK rather than a drop.
_CT_SOLVER_DROPS = (
    ("atype", "ATYPE",
     "the thermal analysis type (0 steady state / 1 transient, Vol I R17 "
     "p.12-573). Radioss integrates the temperature FORWARD IN TIME and only "
     "that (tempur.F:48-55: TEMP += FTHE/MCP, then FTHE is zeroed), so a "
     "steady-state solve has no counterpart at all — the converted run is "
     "transient and has to be given enough physical time to settle"),
    ("ptype", "PTYPE",
     "the problem type (0 linear / 1 properties at the gauss-point "
     "temperature / 2 at the element average). Radioss always evaluates k(T) "
     "from the ELEMENT temperature (stherm.F:106 KC = (AS + BS*TEMPEL)*VOL, "
     "and the same line in s4therm.F:84, s10therm.F:81, cbatherm.F:67), i.e. "
     "it behaves as PTYPE = 2 unconditionally"),
    ("solver", "SOLVER",
     "the linear-algebra choice for the thermal matrix (11 direct, 12-19 "
     "iterative, 30, 90). Radioss assembles NO thermal matrix"),
    ("gpt", "GPT",
     "the number of Gauss points for the thermal solve in solids. Radioss's "
     "thermal degrees of freedom are NODAL and its capacity is lumped"),
    ("msglvl", "MSGLVL", "the iterative solver's output level"),
    ("maxitr", "MAXITR", "the iterative solver's iteration cap"),
    ("abstol", "ABSTOL", "the iterative solver's absolute tolerance"),
    ("reltol", "RELTOL", "the iterative solver's relative tolerance"),
    ("omega", "OMEGA", "the SOR relaxation parameter of SOLVER 14/16"),
    ("ninner", "NINNER", "the GMRES inner-iteration count of SOLVER 17"),
    ("nouter", "NOUTER", "the GMRES outer-iteration count of SOLVER 17"),
    ("mxdmp", "MXDMP", "the matrix-dump control"),
    ("varden", "VARDEN",
     "variable thermal density. Radioss builds its nodal capacity ONCE at "
     "initialisation (initia.F) and never rebuilds it"),
    ("ncycl", "NCYCL",
     "the matrix reassembly frequency — there is no matrix to reassemble"),
    ("dtvf", "DTVF",
     "the view-factor update interval, which belongs to the ENCLOSURE "
     "radiation forms this converter drops by name"),
)


def _warn_control_thermal_solver(state: ConversionState) -> None:
    """Name every ``*CONTROL_THERMAL_SOLVER`` cell that does not map.

    Two map and are handled elsewhere — ``FWORK`` becomes ``/HEAT/MAT``'s
    ``EFRAC`` (``_efrac``) and ``TSF`` the engine ``/THERM``
    (``_make_engine_thermal``). ``SBC`` is neither: Vol I R17 p.12-575 scopes
    it to *"enclosure radiation surfaces"*, which this converter drops, and
    ``hm_read_radiation.F:140-142`` derives its own sigma from the ``/BEGIN``
    unit line — so the cell becomes a CROSS-CHECK on that unit line, which is
    the one thing that could silently corrupt every ``/RADIATION``.
    """
    ct = state.ctrl_thermal_solver
    if ct is None:
        return
    named = []
    for attr, name, _why in _CT_SOLVER_DROPS:
        v = getattr(ct, attr)
        if v:
            named.append(f"{name}={v:g}" if isinstance(v, float)
                         else f"{name}={v}")
    detail = ", ".join(named) if named else "all at their defaults"
    state.warn(
        "*CONTROL_THERMAL_SOLVER: of this card's cells only FWORK (-> "
        "/HEAT/MAT EFRAC, both 'fraction of mechanical work converted into "
        "heat' and both turning a stated 0 into 1.0) and TSF (-> the engine "
        "/THERM's THEACCFACT) reach the converted deck. The rest are DROPPED "
        f"by name — {detail} — because they configure an implicit matrix solve "
        "Radioss does not perform: "
        + "; ".join(f"{name} is {why}" for _a, name, why in _CT_SOLVER_DROPS)
        + ".")
    if ct.eqheat and ct.eqheat != 1.0:
        state.warn(
            f"*CONTROL_THERMAL_SOLVER: EQHEAT={ct.eqheat:g} is the mechanical "
            "equivalent of heat (Vol I R17 p.12-574), the factor that "
            "reconciles a deck whose mechanical and thermal units are NOT "
            "consistent. Radioss has no such cell — it assumes one consistent "
            "system throughout — so the value is dropped. On a consistent "
            "deck EQHEAT is 1.0, and a value that is not 1.0 means the "
            "converted deck's strain-energy-to-heat conversion is off by "
            f"exactly {ct.eqheat:g}."
            + (" A NEGATIVE EQHEAT names a load curve, which is further "
               "beyond reach." if ct.eqheat < 0 else ""))
    if not ct.sbc:
        return
    sigma = _sigma_deck(state)
    if sigma is None:
        return
    if abs(ct.sbc - sigma) <= 1e-3 * sigma:
        return
    state.warn(
        f"*CONTROL_THERMAL_SOLVER: SBC={ct.sbc:g} (the deck's "
        "Stefan-Boltzmann constant) does NOT match the "
        f"{sigma:g} this converter's emitted /BEGIN unit system "
        f"{state.units} implies. The cell itself has no counterpart — Vol I "
        "R17 p.12-575 scopes it to 'enclosure radiation surfaces', which are "
        "dropped by name here, and hm_read_radiation.F:140-142 makes Radioss "
        "derive its own sigma (STEFBOLTZ*FAC_T**3/FAC_M) from /BEGIN. But the "
        "MISMATCH is worth acting on: it means the deck's real unit system and "
        "the one written to /BEGIN disagree, which would put every converted "
        "/RADIATION emissivity off by the same ratio "
        f"({ct.sbc / sigma:.6g}x) with no starter diagnostic whatever. Pass "
        "--units for the deck's real system.")


#: A driver whose ``source`` starts with this came from the ``*LOAD_THERMAL_*``
#: family, which Vol I R17 p.33-162 scopes to structural-only analyses.
_LOAD_THERMAL = "*LOAD_THERMAL_"


def _drop_load_thermal_on_thermal_soln(state: ConversionState) -> None:
    """``*LOAD_THERMAL_*`` is a STRUCTURAL-ONLY load — drop it on SOLN 1 or 2.

    Vol I R17 p.33-162, the family's own head page, verbatim: *"Nodal
    temperatures defined by the *LOAD_THERMAL_OPTION method are all applied in
    a structural only analysis. They are IGNORED in a thermal only or coupled
    thermal/structural analysis, see *CONTROL_THERMAL_OPTION."*

    So on a ``*CONTROL_SOLUTION`` SOLN = 1 or 2 deck these cards do NOTHING in
    LS-DYNA. ``/IMPTEMP`` is not "nothing": ``fixtemp.F:180-199`` writes
    ``TEMP(node)`` every cycle, which is a HARD Dirichlet reset that overrides
    whatever the ``/CONVEC``, ``/RADIATION`` or ``/IMPFLUX`` solve just
    computed on those nodes. Emitting it would state a load the deck does not
    — and would do it in the direction that silently wins. The records are
    dropped by name instead.

    This composition is NEW with the heat-source boundaries: before them a
    k2rad thermal deck had no source, so ``/IMPTEMP`` was the only thing
    moving the temperature and there was nothing for it to override.
    ``*BOUNDARY_TEMPERATURE`` and ``*INITIAL_TEMPERATURE`` are untouched —
    p.33-162 scopes its sentence to ``*LOAD_THERMAL_OPTION`` alone, and a
    prescribed boundary temperature is a genuine thermal boundary condition in
    a thermal analysis.
    """
    if state.ctrl_solution_soln not in (1, 2):
        return
    # BOTH registries: the nodal spellings land in `imposed_temperatures` at
    # dispatch time, the `_ELEMENT_<F>` ones in `load_thermal_elements` and
    # only become drivers later. Screening one would let the other through.
    doomed = [d for d in state.imposed_temperatures
              if d.source.startswith(_LOAD_THERMAL)]
    elems = list(state.load_thermal_elements)
    if not doomed and not elems:
        return
    names = sorted({d.source for d in doomed}
                   | {r.source for r in elems})
    kind = ("THERMAL-ONLY" if state.ctrl_solution_soln == 1
            else "COUPLED structural/thermal")
    state.imposed_temperatures[:] = [
        d for d in state.imposed_temperatures
        if not d.source.startswith(_LOAD_THERMAL)]
    state.load_thermal_elements.clear()
    state.warn(
        f"*CONTROL_SOLUTION SOLN={state.ctrl_solution_soln} makes this a "
        f"{kind} analysis, and LS-DYNA IGNORES the whole *LOAD_THERMAL_* "
        "family there: Vol I R17 p.33-162 says its nodal temperatures 'are all "
        "applied in a structural only analysis. They are ignored in a thermal "
        "only or coupled thermal/structural analysis'. "
        f"{len(doomed) + len(elems)} record(s) from " + ", ".join(names)
        + " are therefore "
        "DROPPED rather than emitted as /IMPTEMP. The difference matters: "
        "/IMPTEMP is a HARD Dirichlet reset applied every cycle "
        "(fixtemp.F:180-199 writes TEMP(node) directly), so on this deck it "
        "would override the very thermal solve the deck asks for, on exactly "
        "the nodes it names. Restate them as *BOUNDARY_TEMPERATURE if a "
        "prescribed boundary temperature was meant — that card IS a thermal "
        "boundary condition and converts.")


def _warn_soln0_thermal(state: ConversionState) -> None:
    """A deck that STATES ``SOLN = 0`` and then states thermal cards.

    LS-DYNA runs no thermal analysis at all in that case
    (``*CONTROL_SOLUTION`` p.12-532: *"EQ.0: Structural analysis only"*), so
    every ``*MAT_THERMAL_*``, ``*BOUNDARY_FLUX``, ``*BOUNDARY_CONVECTION`` and
    ``*BOUNDARY_RADIATION`` on it is inert there while the converted deck runs
    a real solve.

    It is named, not dropped, and the asymmetry with
    ``_drop_load_thermal_on_thermal_soln`` is deliberate: there LS-DYNA's own
    rule is explicit AND the emitted card would OVERRIDE the deck's solve; here
    the emitted cards only ADD physics the deck spells out card by card, and
    silently converting a fully specified thermal model into nothing would be
    the worse failure. ``*CONTROL_SOLUTION`` is often simply absent, so only a
    STATED zero is called out.
    """
    if not state.ctrl_solution_present or state.ctrl_solution_soln != 0:
        return
    kinds = sorted({_BC_CARD[b.kind] for b in state.thermal_boundaries})
    if not kinds and not state.heat_mat_cards:
        return
    what = (", ".join(kinds) if kinds
            else f"{len(state.heat_mat_cards)} /HEAT/MAT card(s)")
    state.warn(
        "*CONTROL_SOLUTION states SOLN=0 (structural analysis ONLY, Vol I R17 "
        "p.12-532) while the deck also states thermal cards, and the converted "
        f"deck emits {what}. In LS-DYNA those cards are inert on a SOLN=0 run "
        "— there is no thermal solve to attach them to — so the converted deck "
        "computes MORE than the source does. They are emitted anyway, because "
        "the deck spells the thermal model out card by card and dropping it "
        "silently would be the larger surprise, but the difference is real: "
        "set SOLN=2 if a coupled run was meant, or remove the thermal cards.")


def _warn_fwork(state: ConversionState) -> None:
    """What ``FWORK`` actually reaches, and what actually reads it.

    Runs after ``_resolve_heat_materials`` so it can say whether any
    ``/HEAT/MAT`` carries the value at all. Split from
    ``_warn_control_thermal_solver`` (which runs first, before any card is
    decided) for exactly that reason.
    """
    ct = state.ctrl_thermal_solver
    if ct is None:
        return
    efrac = _efrac(state)
    if not state.heat_mat_cards:
        state.warn(
            f"*CONTROL_THERMAL_SOLVER: FWORK = {ct.fwork:g} would become "
            "/HEAT/MAT's EFRAC cell, but this deck emits no /HEAT/MAT at all, "
            "so it reaches nothing.")
        return
    state.warn(
        f"*CONTROL_THERMAL_SOLVER: FWORK = {ct.fwork:g} is written to every "
        f"/HEAT/MAT's EFRAC cell (emitted value {efrac:g})"
        + ("" if ct.has_fwork else
           " — the cell is BLANK on this card, and p.12-573's Card 1 Default "
           "row prints '1.' under FWORK, so a blank means full conversion "
           "exactly as a stated 1.0 does; there is no third state")
        + ". What CONSUMES it is not quite the same quantity on the two sides. "
        "LS-DYNA converts a fraction of the mechanical WORK; Radioss scales "
        "the element's TOTAL internal-energy increment, elastic part included, "
        "for every law whose HEAT_FLAG is 0 — mmain.F90:2035-2037 for solids "
        "('die = eint*vol - die', then 'die *= efrac') and cmain3.F:360 for "
        "shells of law < 28 or law 32 (PM(90) = EFRAC) — plus pforc3.F:321 for "
        "beams. Only /MAT/LAW2's shell branch scales real plastic work "
        "(sigeps02c.F:223, SIGY*DPLA*VOL*EFRAC). Over a load-unload cycle the "
        "elastic part nets out (the increment is signed), but instantaneously "
        "the converted deck's heat source is not the LS-DYNA one.")


def _element_nodes_by_family(state: ConversionState, family: str):
    """``{eid: [node ids]}`` for one ``*LOAD_THERMAL_*_ELEMENT_<FAMILY>``.

    Keyed per FAMILY rather than over a union registry, because element ids
    live in separate namespaces per type: an ``*ELEMENT_BEAM 50`` beside an
    ``*ELEMENT_SHELL 50`` is legal, and a union lookup would give a
    ``..._ELEMENT_BEAM`` card the shell's nodes (the #125/#128 two-namespace
    class).
    """
    if family == "SHELL":
        return {e.eid: list(e.nodes) for e in state.shell_elems}
    if family == "SOLID":
        return {e.eid: list(e.nodes) for e in state.solid_elems}
    if family == "TSHELL":
        return {e.eid: list(e.nodes) for e in state.tshell_elems}
    if family == "BEAM":
        return {e.eid: [n for n in (e.n1, e.n2) if n]
                for e in state.beam_elems}
    return {}


def _resolve_load_thermal_elements(state: ConversionState) -> None:
    """``*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_<F>`` → /IMPTEMP, or a
    named drop when the element → node expansion is over-determined.

    **What the LS-DYNA card states.** *"Define a uniform ELEMENT temperature"*
    (Vol I R17 p.33-168) / *"Define ELEMENT temperature that is variable"*
    (p.33-184) — an element-centric field, and neither page ever mentions
    nodes. Radioss has no element-centric temperature card at all: ``/IMPTEMP``
    writes ``TEMP(node)`` (``fixtemp.F:196-205``) and ``/INITEMP`` a nodal
    initial value.

    **When the expansion is faithful.** A node shared by two elements that
    state DIFFERENT temperatures is over-determined: LS-DYNA holds two element
    fields there, a nodal card can hold one, and "last writer wins" would
    fabricate a field the deck never states. So the node → temperature map is
    built first and the whole card set is refused, by name and with the
    colliding elements listed, the moment one node is claimed twice. A card
    covering a whole part (the ordinary spelling) has no interior collision at
    all and converts exactly.

    **The REFERENCE state is NOT carried across, for either spelling.** Vol I
    R17 p.33-168 says a ``_CONSTANT_ELEMENT`` temperature is measured from a
    *"null state"*, i.e. LS-DYNA develops ``alpha·T`` of thermal strain from a
    card that never changes. Radioss has no reference cell at all — the
    expansion is incremental (``mmain.F90:772-775``: ``tempel0 = lbuf%temp``,
    the PREVIOUS step's value, and ``eth = alpha·(tempel - tempel0)``), so its
    reference is whatever temperature the first cycle sees, which is the
    companion ``/INITEMP`` this writer synthesizes at the driver's own t = 0
    value. A driver that never moves therefore produces exactly ZERO thermal
    strain. That is a pre-existing property of every ``*LOAD_THERMAL_*``
    spelling, nodal ones included, and it is stated where it can bite:
    ``_warn_constant_driver_expansion`` names it whenever a
    ``/THERM_STRESS/MAT`` sits beside drivers that are all constant.
    """
    if not state.load_thermal_elements:
        return
    by_key: Dict[Tuple, List] = defaultdict(list)
    for rec in state.load_thermal_elements:
        by_key[(rec.source, rec.family)].append(rec)
    for (source, family), recs in sorted(by_key.items()):
        table = _element_nodes_by_family(state, family)
        if not table:
            state.warn(
                f"{source}: the converted deck has no {family or 'element'} "
                "elements at all, so none of its "
                f"{len(recs)} element temperature(s) has a target — card "
                "dropped. (Element ids are per-FAMILY namespaces, so this "
                "lookup is deliberately not a union over every element table.)")
            continue
        missing = [r.eid for r in recs if r.eid not in table]
        wanted = [r for r in recs if r.eid in table]
        if missing:
            state.warn(
                f"{source}: element(s) {sorted(missing)[:20]}"
                + (" ..." if len(missing) > 20 else "")
                + f" are not in the converted deck's {family} table, so their "
                "temperature has no target — those rows are dropped.")
        if not wanted:
            continue
        # value → the nodes it claims, and the reverse map for the collision
        # screen. The value is the WHOLE prescription, so two elements agree
        # only when their temperature histories agree cell for cell.
        claim: Dict[int, Tuple] = {}
        collide: Dict[int, List[int]] = defaultdict(list)
        for r in wanted:
            val = (r.temp, r.scale, r.offset, r.lcid)
            for n in table[r.eid]:
                if n not in state.nodes:
                    continue
                prev = claim.get(n)
                if prev is not None and prev != val:
                    collide[n].append(r.eid)
                else:
                    claim[n] = val
        if collide:
            examples = sorted(collide)[:10]
            state.warn(
                f"{source}: the element temperatures are OVER-DETERMINED at "
                f"{len(collide)} shared node(s) — node(s) {examples}"
                + (" ..." if len(collide) > 10 else "")
                + " each belong to two elements that state DIFFERENT "
                "temperatures. LS-DYNA holds a uniform temperature PER ELEMENT "
                "(Vol I R17 p.33-168 'a uniform element temperature'), while "
                "Radioss has no element-centric temperature card: /IMPTEMP "
                "writes TEMP(node) (fixtemp.F:196-205). Letting the last "
                "element win would fabricate a nodal field the deck never "
                "states, so the WHOLE card is dropped. Split the elements onto "
                "*LOAD_THERMAL_VARIABLE_NODE / _CONSTANT_NODE cards, or give "
                "the neighbouring elements the same temperature, if this "
                "should convert.")
            continue
        # One /IMPTEMP per distinct value, over exactly the nodes that value
        # claims — the honest nodal statement of an element-wise field.
        groups: Dict[Tuple, List[int]] = defaultdict(list)
        for n, val in claim.items():
            groups[val].append(n)
        for val, nodes in sorted(groups.items(),
                                 key=lambda kv: (kv[0], min(kv[1]))):
            temp, scale, offset, lcid = val
            rec = ImposedTemperature(
                source=f"{source} ({family})", sid=0, nids=sorted(nodes))
            if lcid or scale:
                rec.lcid, rec.scale, rec.offset = lcid, scale, offset
            else:
                rec.const = temp + offset
                rec.initial_temp = temp + offset
            state.imposed_temperatures.append(rec)
        state.warn(
            f"{source} -> /IMPTEMP over the elements' OWN nodes "
            f"({len(claim)} node(s), {len(groups)} distinct temperature(s)). "
            "The LS-DYNA card is element-centric ('a uniform element "
            "temperature', Vol I R17 p.33-168/33-184) and Radioss has only the "
            "nodal /IMPTEMP, so each element's temperature is imposed on the "
            "nodes it owns; that is exact here because no node is claimed by "
            "two different temperatures. Note LS-DYNA IGNORES the whole "
            "*LOAD_THERMAL_* family in a thermal-only or coupled analysis "
            "(p.33-162) — it is a STRUCTURAL-only load — while /IMPTEMP is a "
            "hard Dirichlet reset in the one thermal solve Radioss has.")


def _note_tprint(state: ConversionState) -> None:
    """*DATABASE_TPRINT — the thermal ASCII database. Answered at the END of
    the EMISSION pass, not at parse time and not in the prepass: the answer
    depends on whether an /IMPTEMP was actually written, which is only known
    after ``_driver_nodes`` has resolved every driver's node set.

    dyna2rad switches on ``/ANIM/NODA TEMP`` + ``/ANIM/ELEM TEMP`` and appends
    ``TEMP`` to every existing /TH/NODE and /TH/BRIC group (dyna2rad.cxx:497-551)
    with no check that a thermal solution was ever requested. Measured on a
    576-brick converted deck with no thermal solve, those fields come out ALL
    ZERO (/MAT/ELAST) or a frozen 300 (/MAT/PLAS_JOHNS, which allocates
    ``GBUF%TEMP`` and never integrates it) — a flat fringe that reads as data.
    The starter says so only on the /TH side (``WARNING 1087 OUTPUT TEMP WHILE
    TEMPERATURE IS NOT COMPUTED (NO HEAT/MAT)``, hm_read_thgrne.F:228-236) and
    never on the ANIM side. So the channels are emitted exactly when a
    /HEAT/MAT AND a temperature driver both exist.
    """
    if not state.db_tprint_dt:
        return
    if _thermal_solve_active(state):
        state.warn(
            "*DATABASE_TPRINT: the deck arms a thermal solve (a /HEAT/MAT plus "
            "a temperature driver or a heat-source boundary), so the nodal "
            "temperature IS written - /ANIM/NODA/TEMP in the engine deck and a "
            "/TH/NODE TEMP group over the driven and loaded nodes. Its dt is "
            "deliberately NOT folded into the /TFILE minimum: the TEMP channel "
            "rides the groups already there rather than pacing one of its own. "
            "The whole-model heat balance is in the engine .out instead of a "
            "/TH group, because none exists: thermbilan.F:71-76 prints "
            "'** THERMAL ANALYSIS **' with the imposed-flux, strain-energy, "
            "convection, radiation and stored heat once per printout, while "
            "/TH/SURF's variable list (hm_read_thgrou.F:1255) is AREA, "
            "MASSFLOW, VELOCITY, P, A, MASS - there is no thermal channel on "
            "any /TH group for /IMPFLUX, /CONVEC or /RADIATION at all.")
        return
    state.note_recognized_not_emitted(
        "DATABASE_TPRINT",
        "the thermal ASCII database has no target on THIS deck: no material "
        "receives a /HEAT/MAT (which is the only thing that arms "
        "MAT_PARAM%ITHERM, hm_read_therm.F:253) and/or no temperature driver "
        "is converted, so the run computes no temperature. An emitted "
        "/ANIM/*/TEMP or /TH ... TEMP would be accepted, run clean and write "
        "state after state of exactly 0.0 (measured), or a frozen 300 on a law "
        "that allocates a temperature it never integrates; the starter says so "
        "only on the /TH side (WARNING 1087 OUTPUT TEMP WHILE TEMPERATURE IS "
        "NOT COMPUTED, hm_read_thgrne.F:228) and never on the ANIM side. The "
        "dt is not folded into the /TFILE minimum either, because no channel "
        "it would pace exists. Add "
        "*MAT_ADD_THERMAL_EXPANSION or *MAT_THERMAL_* + *PART TMID, plus one "
        "of the temperature-moving cards - a *LOAD_THERMAL_* or "
        "*BOUNDARY_TEMPERATURE driver, or a *BOUNDARY_FLUX / _CONVECTION / "
        "_RADIATION heat source - and the channel appears. "
        "(*INITIAL_TEMPERATURE alone is a STATE, not a driver.)")


def _resolve_expansion(state: ConversionState) -> None:
    """``*MAT_ADD_THERMAL_EXPANSION`` → ``state.therm_stress_cards``, splitting
    a shared material where the deck names only some of its parts."""
    if not state.mat_add_thermal_expansion:
        return
    by_pid: Dict[int, object] = {}
    direct: Dict[int, object] = {}
    for card in state.mat_add_thermal_expansion:
        if card.pid < 0:
            # "GT.0: Part ID, LT.0: Material ID |ID|" (Vol II R17 p.2-146).
            # dyna2rad cannot read this form at all — its cfg types the cell
            # VALUE(COMPONENT) and the whole deck dies with ERROR 109999.
            direct[-card.pid] = card
            continue
        if card.pid not in state.parts:
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION: PID={card.pid} has no *PART "
                "record, so there is no material to attach the expansion to — "
                "card dropped.")
            continue
        if card.pid in by_pid and _expansion_key(by_pid[card.pid]) \
                != _expansion_key(card):
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION: part {card.pid} carries TWO "
                "different cards; the LAST one wins, as it does in LS-DYNA.")
        by_pid[card.pid] = card

    # Group the part-keyed cards by (material, card, thermal material). Two
    # parts that share a MID but state different cards - or different *PART
    # TMIDs - cannot share one /THERM_STRESS/MAT either.
    groups: Dict[tuple, List[int]] = defaultdict(list)
    for pid, card in sorted(by_pid.items()):
        part = state.parts[pid]
        groups[(part.mid, _expansion_key(card), part.tmid)].append(pid)

    order = sorted(groups.items(), key=lambda kv: (kv[0][0], min(kv[1])))
    # PASS 1 — decide which groups survive, BEFORE any part is repointed. Both
    # refusals (LAW109, an unresolvable LCID) are ordered before the split
    # because a clone made for a material that then gets no thermal card at all
    # is a pointless duplicate /MAT in the deck.
    accepted: List[Tuple[tuple, List[int]]] = []
    for key, pids in order:
        mid = key[0]
        if _refuse_law109(state, mid, pids):
            continue
        if not _expansion_is_resolvable(state, mid, by_pid[pids[0]]):
            continue
        accepted.append((key, pids))

    # Every list below is computed ONCE, from the SURVIVING grouping, before any
    # part is repointed — recomputing "the parts on this mid" after the first
    # clone made the second warning describe a state that no longer existed.
    # A REFUSED group claims none of its parts, so its pids must stay out of
    # `covered`: otherwise the last surviving group on a shared mid would pass
    # the "these groups name every part" test, keep the ORIGINAL material id,
    # and the refused parts — still pointing at it — would silently inherit the
    # OTHER card's expansion while the emitted warning says the material was
    # neither carded nor split.
    all_pids_of: Dict[int, List[int]] = {}
    covered: Dict[int, Set[int]] = defaultdict(set)
    last_group_on: Dict[int, tuple] = {}
    for key, pids in accepted:
        mid = key[0]
        all_pids_of.setdefault(
            mid, sorted(p for p, q in state.parts.items() if q.mid == mid))
        covered[mid].update(pids)
        last_group_on[mid] = key

    # PASS 2 — clone where needed and emit.
    for key, pids in accepted:
        mid = key[0]
        card = by_pid[pids[0]]
        all_pids = all_pids_of[mid]
        target = mid
        # The LAST group on a mid may keep the original id — but only when the
        # groups together name every part on it. Otherwise the parts the deck
        # did not name still need the original material, and cloning for all
        # of them would leave /MAT/<mid> referenced by nobody.
        keeps_original = (covered[mid] == set(all_pids)
                          and last_group_on[mid] == key)
        if not keeps_original and (len(pids) != len(all_pids)
                                   or set(pids) != set(all_pids)):
            clone = _clone_material(state, mid)
            if clone is None:
                state.warn(
                    f"*MAT_ADD_THERMAL_EXPANSION on part(s) {pids}: material "
                    f"{mid} cannot be SPLIT off for the expansion — it is "
                    "either not converted to any /MAT at all, or one of the "
                    "four producers whose /MAT needs a companion card a plain "
                    "copy would not carry (*MAT_HIGH_EXPLOSIVE_BURN + its "
                    "/EOS, *MAT_LAMINATED_GLASS's LAW27 pair, "
                    "*MAT_SEATBELT's per-property LAW114/119, *MAT_SPOTWELD's "
                    "connector fallback). Card dropped. Give the part its own material "
                    "id in the .k file if it must expand on its own.")
                continue
            for pid in pids:
                state.parts[pid] = dataclasses.replace(state.parts[pid],
                                                       mid=clone)
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION names part(s) {pids} but material "
                f"{mid} is shared by part(s) {all_pids}. The LS-DYNA card is "
                "PER PART while /THERM_STRESS/MAT is PER MATERIAL "
                "(hm_read_therm_stress.F90 keys on mat_ID), so the material was "
                f"SPLIT: part(s) {pids} now carry a copy under mid {clone} that "
                f"has the expansion, and mid {mid} keeps part(s) "
                f"{[p for p in all_pids if p not in set(pids)]}. dyna2rad "
                "instead expands every part on the shared material "
                "(convertmats.cxx:12236 resolves PID to the part's MID and "
                "stops there).")
            target = clone
        func_id, fscale = _resolve_alpha_function(state, target, card)
        if func_id == 0:
            continue
        _warn_orthotropic_slots(state, target, card)
        state.therm_stress_cards[target] = (func_id, fscale)
        _restate_law1_shells(state, target)

    for mid, card in sorted(direct.items()):
        if _refuse_law109(state, mid, None):
            continue
        if not any(p.mid == mid for p in state.parts.values()):
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION: ID=-{mid} names a material no "
                "*PART uses — card dropped.")
            continue
        if not _expansion_is_resolvable(state, mid, card):
            continue
        func_id, fscale = _resolve_alpha_function(state, mid, card)
        if func_id == 0:
            continue
        _warn_orthotropic_slots(state, mid, card)
        state.therm_stress_cards[mid] = (func_id, fscale)
        _restate_law1_shells(state, mid)


#: The unreachable yield stress of the restated LAW36. Stated as a MULTIPLE of
#: the material's own E so it carries no unit assumption: a yield strain of
#: 1000 cannot occur in any structural run, and the emitted curve is flat, so
#: the law never leaves its elastic branch.
_FAR_YIELD_OVER_E = 1.0e3


def _has_initial_state(state: ConversionState, pids: Set[int]) -> bool:
    """True when any shell on *pids* carries an /INISHE stress or strain
    record — directly or through a ``*SET_SHELL``."""
    if not (state.ini_stress_shells or state.ini_strain_shells):
        return False
    # state.shell_elems holds every *ELEMENT_SHELL, quads and 3-node tris
    # alike (the /SHELL vs /SH3N split happens at the write line).
    eids = {e.eid for e in state.shell_elems if e.pid in pids}
    for rec in state.ini_stress_shells:
        if rec.eid in eids:
            return True
    for rec in state.ini_strain_shells:
        if getattr(rec, "is_set", False):
            members = state.shell_sets.get(rec.eid)
            if members and set(members[1]) & eids:
                return True
        elif rec.eid in eids:
            return True
    return False


def _restate_law1_shells(state: ConversionState, mid: int) -> None:
    """A ``*MAT_ELASTIC`` SHELL part cannot expand under /MAT/LAW1 — restate it
    as /MAT/LAW36 with a far-yield flat curve.

    **Why.** LAW1 is the one law Radioss integrates GLOBALLY through the
    thickness: it answers ``N > 1`` with ``WARNING 1084 FORMULATION IS SWITCHED
    TO GLOBAL INTEGRATION N=0``, and the shell thermal-expansion routine
    reaches the per-integration-point stresses (``thermexpc.F``'s
    ``IF (NPT /= 0)`` block). With ``NPT = 0`` there is nothing for it to
    correct. Measured on this branch's own converted decks, a 10 x 1 mm strip
    at ``alpha = 1.2e-5`` over ``dT = 100 K`` (closed form 0.012 mm):

      ==================================  ==============  =========
      shell                               free-edge DX    vs 0.012
      ==================================  ==============  =========
      *MAT_ELASTIC, *SECTION_SHELL NIP 5   2.66e-07 mm    -100 %
      *MAT_ELASTIC, *SECTION_SHELL NIP 1  -5.11e-08 mm    -100 %
      the LAW36 restatement, NIP 5         0.0120078 mm   +0.065 %
      ==================================  ==============  =========

    The integration-point COUNT is not the cure — LAW1 discards it. Only a law
    that keeps a through-thickness state does.

    **Why it is safe.** The restatement is elastically neutral. The same strip
    with NO thermal card, pulled to a prescribed 0.05 mm over 5 ms, gives an
    identical membrane stress under both laws (measured at t = 1/2/3/4 ms:
    209.977 / 419.561 / 628.914 / 838.231 MPa under LAW1 against 210.003 /
    419.709 / 629.086 / 838.410 under the restated LAW36 — **+0.012 % to
    +0.035 %**, against the closed form ``E*eps`` = 210.0 / 420.0 / 630.0 /
    840.0), and the free edge follows the imposed motion to 8 digits in both.
    The one real cost is the time step: 1.506e-7 s under LAW1 against 1.436e-7
    under LAW36 (**-4.6 %**), because the restated law integrates through the
    thickness.

    **Scope.** Only when EVERY part on the material carries shell elements or a
    ``*SECTION_SHELL``. Solids are left alone — ``mmain.F90:757`` applies the
    expansion before the law dispatch, so a LAW1 SOLID expands correctly and
    was measured exact. Restricting to shells also keeps the change clear of
    the starter's solid-/XREF law whitelist, which ``hm_read_xref.F`` gates on
    ``ITYP == 2`` (solid parts only).
    """
    mat = state.mat_elastic.get(mid)
    if mat is None:
        return
    pids = sorted(p for p, q in state.parts.items() if q.mid == mid)
    if not pids:
        return
    shell_pids = {e.pid for e in state.shell_elems}
    if not all(p in shell_pids or state.parts[p].secid in state.sec_shells
               for p in pids):
        return
    if _has_initial_state(state, set(pids)):
        # The #127 mixed-deck rule. An /INISHE record carries one stress or
        # strain station per THROUGH-THICKNESS integration point, and the
        # writer cross-checks that count against the /PROP/SHELL N
        # (hm_read_inistate_d00.F's npg/nb_integr checks answer ERROR 26 +
        # ERROR 1904 on a mismatch). Restating LAW1 -> LAW36 turns a globally
        # integrated shell (N forced to 0) into an N-point one, which moves
        # exactly that count. Two cards that share a reader flag must be
        # validated together or not combined at all — so the law is left alone
        # and the inertness is reported instead.
        state.warn(
            f"*MAT_ELASTIC {mid} carries a thermal expansion on shell part(s) "
            f"{pids}, but those parts also carry *INITIAL_STRESS_SHELL / "
            "*INITIAL_STRAIN_SHELL records. Restating the material as "
            "/MAT/LAW36 (which is what would let a LAW1 shell expand at all) "
            "would change the shell from GLOBAL integration to N "
            "through-thickness points, and an /INISHE record's station count "
            "is cross-checked against exactly that N. The law is left as LAW1, "
            "so the thermal expansion on these parts is INERT — give them "
            "their own material and restate it by hand, or drop the initial "
            "state, if the expansion matters.")
        return
    sigy = _FAR_YIELD_OVER_E * mat.E
    if sigy <= 0.0:
        return
    fid = state.next_curve_id()
    state.curves[fid] = Curve(
        lcid=fid, title=f"Auto_far_yield_mat{mid}",
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
        pts=[(0.0, sigy), (1.0, sigy)])
    state.curve_order.append(fid)
    del state.mat_elastic[mid]
    state.law1_shells_restated.add(mid)
    state.mat_plas_tab[mid] = MatPlasTAB(
        mid=mid, title=mat.title, rho=mat.rho, E=mat.E, nu=mat.nu,
        sigy=sigy, etan=0.0, fail=0.0, lcss=0, C=0.0, P=0.0,
        funct_id=fid)
    state.warn(
        f"*MAT_ELASTIC {mid} carries a thermal expansion and every part on it "
        f"is a SHELL ({pids}), so it is RESTATED as /MAT/LAW36 with a flat "
        f"yield curve at {sigy:g} (= 1000 x E, a strain of 1000 — the law "
        "never leaves its elastic branch). /MAT/LAW1 is the one law Radioss "
        "integrates GLOBALLY through the thickness (it answers N > 1 with "
        "WARNING 1084 'FORMULATION IS SWITCHED TO GLOBAL INTEGRATION N=0'), "
        "and the shell expansion routine only reaches the per-integration-"
        "point stresses — measured, a LAW1 shell strip expands by 2.7e-07 mm "
        "where the closed form is 0.012 mm, at NIP 1 and NIP 5 alike, while "
        "the restatement gives 0.0120078 mm (+0.065 %). The elastic response "
        "is unchanged: the same strip pulled mechanically reports 209.977 vs "
        "210.003 MPa (+0.012 %) at the same elongation. The one cost is a "
        "-4.6 % time step, because the restated law integrates through the "
        "thickness. SOLID parts are NOT restated — a LAW1 solid expands "
        "correctly (mmain.F90:757 applies the expansion before the law "
        "dispatch).")


def _refuse_law109(state: ConversionState, mid: int,
                   pids: Optional[List[int]]) -> bool:
    """*MAT_TABULATED_JOHNSON_COOK (/MAT/LAW109) cannot take the pair.

    LAW109 integrates its OWN element temperature from plastic work, and a
    /HEAT/MAT switches it to the imposed-temperature path and kills that update
    (``sigeps109.F:411-414``; writer/materials.py::_emit_mat_law109 states the
    policy). /THERM_STRESS/MAT without a /HEAT/MAT is a hard ERROR 1129
    (``hm_read_therm_stress.F90:130-132``), so the two cards cannot be had on
    this law at all — trading the tabulated law's self-heating for a linear
    expansion coefficient would be a silent change of physics.
    """
    if mid not in state.mat_tabulated_jc:
        return False
    where = f"part(s) {pids}" if pids else f"material {mid} (the ID<0 form)"
    state.warn(
        f"*MAT_ADD_THERMAL_EXPANSION on {where}: material {mid} is a "
        "*MAT_TABULATED_JOHNSON_COOK (/MAT/LAW109), which integrates its OWN "
        "element temperature from plastic work. A /HEAT/MAT switches LAW109 to "
        "the imposed-temperature path and kills that self-heating "
        "(sigeps109.F:411-414), and /THERM_STRESS/MAT without a /HEAT/MAT is a "
        "hard ERROR 1129 (hm_read_therm_stress.F90:130-132) - so the pair "
        "cannot be had on this law at all and NO thermal-expansion card is "
        "emitted for it. Trading the tabulated law's self-heating for a linear "
        "expansion coefficient would be a silent change of physics.")
    return True


def _global_initial_temperature(state: ConversionState) -> Optional[float]:
    """The deck's model-wide starting temperature, if it states one."""
    for it in state.initial_temperatures:
        if not it.is_node and it.sid == 0:
            return it.temp
    for d in state.imposed_temperatures:
        if d.sid or d.is_node or d.nids:
            # Not a model-wide driver. `nids` matters as much as `sid` here:
            # a *LOAD_THERMAL_*_ELEMENT record carries sid = 0 (it names no
            # set at all) beside an EXPLICIT node list, so testing sid alone
            # would read a handful of elements' temperature as the whole
            # model's t = 0 state.
            continue
        if d.initial_temp is not None:
            return d.initial_temp
        if d.lcid:
            # "The temperature at time = 0 becomes the REFERENCE temperature
            # for the thermal material" (*LOAD_THERMAL_LOAD_CURVE, Purpose).
            # Read from the raw curve: this runs BEFORE _resolve_drivers, so
            # the resolved value is not there yet.
            curve = state.curves.get(d.lcid)
            if curve is not None and curve.pts:
                return d.offset + d.scale * curve.pts[0][1]
    return None


def _efrac(state: ConversionState) -> float:
    """``/HEAT/MAT``'s ``EFRAC`` cell — the fraction of mechanical work that
    becomes heat.

    ``*CONTROL_THERMAL_SOLVER`` ``FWORK`` is *"Fraction of mechanical work
    converted into heat"* (Vol I R17 p.12-575) and ``EFRAC`` is echoed by the
    starter as *"FRACTION OF STRAIN ENERGY CONVERTED INTO HEAT"* — the same
    quantity, and both sides turn a stated 0 into 1.0 (p.12-575 *"EQ.0.0: Use
    default value 1.0"*; ``hm_read_therm.F:239-241`` clamps to (0, 1] with
    ``0 -> 1``).

    **A BLANK cell is 1.0 too, and the presence of the card is what decides.**
    p.12-573's Card 1 Default row prints ``1.`` under FWORK, so LS-DYNA reads a
    blank cell as full conversion — there is no third state. A gate on "was the
    cell physically typed" would give the same card two different physics
    depending on whitespace, on exactly the coupled thermo-mechanical deck the
    keyword exists for. So the whole card's presence is the test.

    A deck that states NO ``*CONTROL_THERMAL_SOLVER`` at all keeps
    ``_EFRAC_OFF``: its temperature field is prescribed from outside
    (``*LOAD_THERMAL_*``, ``*BOUNDARY_TEMPERATURE``, or one of the three
    heat-source boundaries) and no plastic-work conversion is part of that
    model, so writing the 1.0 that a blank ``/HEAT/MAT`` cell would mean adds a
    heat source the deck never asked for. The smallest positive number is
    written instead, because the READER turns a literal 0 into 1.0.
    """
    ct = state.ctrl_thermal_solver
    if ct is None:
        return _EFRAC_OFF
    fwork = ct.fwork
    if fwork == 0.0:                    # "EQ.0.0: Use default value 1.0"
        fwork = 1.0
    return min(1.0, max(_EFRAC_OFF, fwork))


def _td_name(tm) -> str:
    """How to NAME a tabulated thermal material in a message.

    The deck's own spelling wins — ``*MAT_T10`` is a legal way to write
    ``*MAT_THERMAL_ISOTROPIC_TD_LC`` (Vol II R17 p.2-9) and a reader looking
    for the offending card wants the string that is in the file. The canonical
    name is appended when the two differ, so the manual page is still findable.
    """
    canon = "*MAT_THERMAL_ISOTROPIC_TD" + ("_LC" if tm.is_lc else "")
    spelling = getattr(tm, "spelling", "") or canon
    return spelling if spelling == canon else f"{spelling} ({canon})"


def _thermal_material_usable(state: ConversionState, tm, mid: int) -> bool:
    """Screen a ``*MAT_THERMAL_*`` record that cannot become a /HEAT/MAT.

    Two refusals, both stated rather than silently averaged:

    * ``*MAT_THERMAL_ORTHOTROPIC`` with ``K1 != K2 != K3``. /HEAT/MAT holds ONE
      conductivity pair; an "average conductivity" would be a material the deck
      never states. ``K1 == K2 == K3`` IS an isotropic card written on the
      orthotropic keyword and converts exactly.
    * ``*MAT_THERMAL_ISOTROPIC_TD_LC`` whose ``HCHSV``/``TCHSV``/``TGHSV``
      makes a property depend on a MECHANICAL history variable.
    """
    if isinstance(tm, MatThermalOrthotropic):
        ks = (tm.k1, tm.k2, tm.k3)
        kmax, kmin = max(ks), min(ks)
        if kmax - kmin > 1e-9 * max(1.0, abs(kmax)):
            ratio = (f"; ratio {kmax / kmin:.4g}x" if kmin
                     else ", one of them zero")
            state.warn(
                f"*MAT_THERMAL_ORTHOTROPIC {tm.tmid} -> /HEAT/MAT/{mid}: the "
                f"three conductivities differ (K1={tm.k1:g}, K2={tm.k2:g}, "
                f"K3={tm.k3:g}{ratio}). /HEAT/MAT is ISOTROPIC "
                "— one conductivity pair per phase (hm_read_therm.F:157-166 "
                "reads AS, BS, AL, BL and nothing else), and Radioss has no "
                "orthotropic thermal material at any cfg version. Picking K1, "
                "or averaging the three, would state a material the deck does "
                "not, so the thermal properties are DROPPED. (AOPT and the "
                "material-axis cards XP/YP/ZP/A1..A3/D1..D3 have no "
                "counterpart either.) Restate the card as "
                "*MAT_THERMAL_ISOTROPIC with the conductivity that matters if "
                "the anisotropy is not essential.")
            return False
        if tm.aopt or tm.k1:
            state.warn(
                f"*MAT_THERMAL_ORTHOTROPIC {tm.tmid} -> /HEAT/MAT/{mid}: "
                f"K1 = K2 = K3 = {tm.k1:g}, so the card is ISOTROPIC in fact "
                "and converts exactly. AOPT"
                + (f" = {tm.aopt:g}" if tm.aopt else "")
                + " and the material-axis cards (XP/YP/ZP, A1..A3, D1..D3) are "
                "INERT here — they orient three conductivities that are "
                "equal — so nothing is lost by dropping them.")
        return True
    if isinstance(tm, MatThermalIsotropicTD) and tm.lc_hsv[0]:
        name, val = tm.lc_hsv
        state.warn(
            f"{_td_name(tm)} {tm.tmid} -> /HEAT/MAT/{mid}: "
            f"{name}={val} makes a thermal property a function of a MECHANICAL "
            "HISTORY VARIABLE (|1-6| a stress component, 7 the plastic strain, "
            "7+k the law's own history slot k — Vol II R17 p.3-39). Radioss's "
            "/HEAT/MAT holds constants and two linear conductivity segments; "
            "no Radioss thermal input reads a stress or a plastic strain at "
            "all. The thermal properties are DROPPED.")
        return False
    return True


def _warn_thermal_generation_drops(state: ConversionState, tm, mid: int) -> None:
    """``TGRLC``/``TGMULT``/``TLAT``/``HLAT`` — the four cells every
    ``*MAT_THERMAL_*`` carries and /HEAT/MAT has no slot for."""
    dropped = [n for n, v in (("TGRLC", tm.tgrlc), ("TGMULT", tm.tgmult),
                              ("TLAT", tm.tlat), ("HLAT", tm.hlat)) if v]
    if not dropped:
        return
    state.warn(
        f"*MAT_THERMAL_* {tm.tmid} -> /HEAT/MAT/{mid}: "
        + ", ".join(dropped) + " dropped. /HEAT/MAT has no volumetric "
        "heat-generation slot and no latent-heat slot. Its T1/AL/BL cells are "
        "not one either: they are a second conductivity segment that ONLY the "
        "thermal time-step routines read (dttherm.F90:102-106 and "
        "mqviscb.F:653-657 select AS + BS*T below T1 and AL + BL*T above, both "
        "gated on IDT_THERM == 1), while the conduction itself is AS + BS*T "
        "everywhere (stherm.F:106).")


def _least_squares_line(pts: List[Tuple[float, float]]) -> Tuple[float, float]:
    """``(intercept, slope)`` of the least-squares line through *pts*.

    One point (or a degenerate abscissa spread) gives the horizontal line
    through it, which is the right answer for a single stated value.
    """
    n = len(pts)
    if n == 0:
        return 0.0, 0.0
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    if n == 1:
        return pts[0][1], 0.0
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    den = n * sxx - sx * sx
    if abs(den) <= 1e-30 * max(1.0, abs(sxx)):
        return sy / n, 0.0
    slope = (n * sxy - sx * sy) / den
    return (sy - slope * sx) / n, slope


#: The largest ratio ``max(C_i)/min(C_i)`` a ``*MAT_THERMAL_ISOTROPIC_TD``
#: table may show and still be represented by /HEAT/MAT's ONE ``RHO0_CP``
#: cell. Conductivity gets a LINE — ``AS + BS*T_element``, which every
#: conduction operator reads (see ``_fit_td_conductivity``) — so a real k(T)
#: fits well; the volumetric capacity gets a single constant with no
#: temperature dependence available at ANY cfg version, so a table that varies
#: by more than this is not a material /HEAT/MAT can carry and the record is
#: refused by name instead of averaged into a different material.
_TD_CP_SPREAD_LIMIT = 2.0


def _sample_curve(state: ConversionState, lcid: int,
                  temps: List[float]) -> List[float]:
    """The ``*DEFINE_CURVE`` *lcid* evaluated at each abscissa in *temps*."""
    curve = state.curves.get(lcid)
    if curve is None or len(curve.pts) < 2:
        return []
    pts = sorted(curve.pts)
    out: List[float] = []
    for t in temps:
        if t <= pts[0][0]:
            out.append(pts[0][1])
        elif t >= pts[-1][0]:
            out.append(pts[-1][1])
        else:
            for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
                if xa <= t <= xb:
                    w = 0.0 if xb == xa else (t - xa) / (xb - xa)
                    out.append(ya + w * (yb - ya))
                    break
    return out


def _sample_td_lc_curves(state: ConversionState, tm) -> None:
    """Turn a ``*MAT_THERMAL_ISOTROPIC_TD_LC``'s two curves into the same
    ``(T, C, K)`` table the ``_TD`` spelling states directly.

    Sampled on the UNION of the two curves' own abscissae, so neither property
    is resampled onto a grid coarser than the deck states it on. Done HERE and
    not in the handler because a ``*DEFINE_CURVE`` may sit anywhere in the
    deck, including after the material — dispatch would not have read it yet.
    """
    if not tm.is_lc or tm.temps or tm.lc_hsv[0]:
        return
    xs: List[float] = []
    for cid in (tm.hclc, tm.tclc):
        c = state.curves.get(cid)
        if c is not None:
            xs.extend(x for x, _ in c.pts)
    temps = sorted(set(xs))
    if len(temps) < 2:
        return
    cps = _sample_curve(state, tm.hclc, temps)
    ks = _sample_curve(state, tm.tclc, temps)
    if len(cps) == len(temps) and len(ks) == len(temps):
        tm.temps, tm.cps, tm.ks = temps, cps, ks


def _fit_td_conductivity(state: ConversionState, tm, mid: int,
                         t1: float) -> Optional[Tuple[float, float, float,
                                                      float, float]]:
    """``(RHO0_CP, AS, BS, AL, BL)`` fitted from a tabulated thermal material.

    **Why this is a fit and not a drop.** ``/HEAT/MAT`` takes no function ids
    at ANY cfg version — ``hm_read_therm.F:157-166`` reads exactly nine scalar
    cells and the newest FORMAT block (``radioss2022``) has eight — so a
    tabulated ``k(T)`` cannot be carried as a table. ONE straight line through
    the deck's own points is what the conduction operator can read, and the fit
    states its own worst deviation so the reader can judge it.

    **Why ONE line and not the two segments the T1/AL/BL cells suggest.**
    ``AL``/``BL`` never enter the Lagrangian conduction. TWELVE conduction
    operators were enumerated and every one reads ``AS``/``BS``
    (``PM(75)``/``PM(76)``) and nothing else — solids ``stherm.F:82-83/106``,
    ``s8etherm.F:86/110``, ``s4therm.F:67/84``, ``s4therm-itet1.F:118/135``,
    ``s10therm.F:61/81``, ``s20therm.F:60/79``; thick shells ``sctherm.F:94``
    and ``s6ctherm.F:95``; shells ``thermc.F:62/69``, ``therm3c.F:62/72`` and
    ``cbatherm.F:61/67``; beams ``pforc3.F:379-380/382`` — all of them
    ``KC = (AS + BS*T_element)``. Fitting two segments would therefore put
    half the deck's table into cells the heat flow never reads, and above
    ``T1`` the run would silently extrapolate the LOWER line anyway.

    The two-segment ``if (tempel < tmelt) … else`` form is NOT confined to the
    thermal time-step routines, which an earlier draft claimed. It also lives
    in the ALE conduction (``atherm.F:137``), the SPH conductivity
    (``forintp.F:336/350``), ``/INTER/TYPE9`` thermal contact
    (``i9grd2.F:140``, ``i9grd3.F:164``) and rigid-wall heat exchange
    (``rgwat2.F:176``, ``rgwat3.F:213``) — none of which this converter emits —
    and the time-step readers themselves are not uniformly ``IDT_THERM``-gated:
    ``mqviscb.F:282``/``:592``, ``mqvisc8.F:170`` and ``mdtsph.F:142`` gate on
    ``JTHE > 0`` alone (the ALE/Euler framework), while ``mqviscb.F:644`` and
    ``dttherm.F90``'s six callers do carry ``IDT_THERM == 1``. The AS→AL
    mirror below makes every one of those readers see the identical line, so
    the policy is unaffected either way.

    So one least-squares line is fitted over the whole tabulated range and
    MIRRORED into ``AL``/``BL``. The mirror is not cosmetic: with
    ``AL = BL = 0`` a ``/DT/THERM`` run whose elements are above ``T1`` gets
    ``dt = DTFACTHERM·0.5·Lc²·rhoCp/1e-20`` and jumps the whole run in one
    step, and ``CONDE`` (the element conductance the same loop computes for
    interface heat exchange) collapses to 0.

    ``T1`` itself still matters and is NOT free to be chosen as a fit elbow: it
    is ``MAT_PARAM%THERM%TMELT``, the same variable ``mmain.F90:790`` divides
    by for the Johnson-Cook ``T*``. It is carried from the mechanical law
    unchanged.

    Returns ``None`` — a refusal — when the table is unusable or when the
    capacity varies more than ``_TD_CP_SPREAD_LIMIT``.
    """
    pairs = [(t, k) for t, k in zip(tm.temps, tm.ks)]
    if len(pairs) < 2:
        state.warn(
            f"{_td_name(tm)} {tm.tmid} "
            f"-> /HEAT/MAT/{mid}: the card states fewer than two "
            "(temperature, conductivity) points"
            + (f" — curves {tm.hclc}/{tm.tclc} are missing from the deck or "
               "have fewer than two points" if tm.is_lc else "")
            + ", so there is nothing to fit. Vol II R17 p.3-7 requires 'a "
            "minimum of two and a maximum of eight data points'. The thermal "
            "properties are DROPPED.")
        return None
    pairs.sort()
    cps = [c for c in tm.cps if c]
    if not cps:
        state.warn(
            f"{_td_name(tm)} {tm.tmid} "
            f"-> /HEAT/MAT/{mid}: every stated specific heat is 0, so the "
            "material has no heat capacity at all — the thermal properties "
            "are DROPPED rather than emitted with a fabricated RHO0_CP.")
        return None
    spread = max(cps) / min(cps)
    if spread > _TD_CP_SPREAD_LIMIT:
        state.warn(
            f"{_td_name(tm)} {tm.tmid} "
            f"-> /HEAT/MAT/{mid}: the specific heat varies by a factor "
            f"{spread:.3g} over the stated temperature range "
            f"({min(cps):g} .. {max(cps):g}), and /HEAT/MAT's RHO0_CP is ONE "
            "constant with no temperature dependence at any cfg version "
            "(hm_read_therm.F:157-166 reads eight scalars; there is no "
            "function-id form). Collapsing that to a mean would be a "
            "DIFFERENT material, so the thermal properties are DROPPED. "
            "(The conductivity would have converted: /HEAT/MAT's conduction is "
            "AS + BS*T_element — stherm.F:106 and its siblings — so a "
            "least-squares line through the table carries it.) State "
            "*MAT_THERMAL_ISOTROPIC with a representative HC if the capacity "
            "variation is not essential.")
        return None
    rho = tm.tro or _structural_density(state, mid)
    cp_mean = sum(cps) / len(cps)
    rho_cp = rho * cp_mean
    # ONE line over the whole tabulated range, mirrored into AL/BL: the
    # conduction operators read AS/BS only (see the docstring), so a second
    # segment would land in cells the heat flow never reads.
    a_s, bs = _least_squares_line(pairs)
    al, bl = a_s, bs
    dev = 0.0
    for t, k in pairs:
        dev = max(dev, abs(a_s + bs * t - k))
    kmax = max(abs(k) for _, k in pairs) or 1.0
    state.warn(
        f"{_td_name(tm)} {tm.tmid} -> "
        f"/HEAT/MAT/{mid}: the tabulated conductivity is FITTED onto ONE "
        "straight line (there is NO function-id form of /HEAT/MAT at any cfg "
        f"version). Fitted over {len(pairs)} point(s) on "
        f"T = {pairs[0][0]:g} .. {pairs[-1][0]:g}: "
        f"AS = {a_s:.6g}, BS = {bs:.6g}, mirrored into AL = {al:.6g}, "
        f"BL = {bl:.6g}, with T1 = {t1:g}"
        + (" (the mechanical law's own melting temperature, which /HEAT/MAT "
           "overwrites)" if t1 else " (blank; hm_read_therm.F:238 turns that "
           "into 1e20)")
        + ". The T1/AL/BL cells are deliberately NOT used as a second fit "
        "segment: NO Lagrangian solid, thick-shell, shell or beam conduction "
        "operator reads AL/BL — twelve of them were enumerated and every one "
        "computes AS + BS*T_element and nothing else (stherm.F:106, "
        "s8etherm.F:110, s4therm.F:84, s4therm-itet1.F:135, s10therm.F:81, "
        "s20therm.F:79, sctherm.F:94, s6ctherm.F:95, thermc.F:69, "
        "therm3c.F:72, cbatherm.F:67, pforc3.F:382). The 'below/above T1' "
        "branch lives in the thermal TIME-STEP routines (dttherm.F90:102-106, "
        "mqviscb.F:653-657) and in the ALE / SPH / TYPE9 / rigid-wall paths "
        "(atherm.F:137, forintp.F:336, i9grd2.F:140, rgwat2.F:176), none of "
        "which this converter emits. The mirror keeps the /DT/THERM step and "
        "the interface conductance CONDE sane above T1 — AL = BL = 0 there "
        "would give dt = 0.5*Lc^2*rhoCp/1e-20 — and makes every AL/BL reader "
        "see the same line as every AS/BS reader."
        + f" Maximum deviation {dev:.6g} = {100.0 * dev / kmax:.3g}% of the "
        f"largest tabulated value. RHO0_CP = {rho_cp:.6g} = rho {rho:g} x the "
        f"MEAN specific heat {cp_mean:.6g} (stated range {min(cps):g} .. "
        f"{max(cps):g}, spread {spread:.3g}x) — that cell is a single "
        "constant, so the capacity's temperature dependence is the loss this "
        "card actually takes."
        + (f" Sampled from curves HCLC={tm.hclc} and TCLC={tm.tclc}."
           if tm.is_lc else ""))
    return rho_cp, a_s, bs, al, bl


def _resolve_heat_materials(state: ConversionState) -> None:
    """Fill ``state.heat_mat_cards`` — ONCE per material id (#125)."""
    wanted: Set[int] = set(state.therm_stress_cards)
    # A *PART TMID naming a *MAT_THERMAL_* is the deck saying "this part has
    # thermal properties", so it gets a /HEAT/MAT even with no expansion card:
    # that is what lets a temperature driver reach its nodes at all.
    for pid, part in state.parts.items():
        if _thermal_material_for_part(state, pid) is not None:
            wanted.add(part.mid)
    # A /PART with mat_ID 0 is a connector part (or a thermal-only deck whose
    # parts state no structural material at all). /HEAT/MAT/0 names no material
    # and hm_read_therm.F:135-152 answers ERROR 1663 for a mat_ID it cannot
    # resolve, so those parts get nothing.
    zero = 0 in wanted
    wanted.discard(0)
    if zero:
        state.warn(
            "*PART TMID names a *MAT_THERMAL_* on part(s) whose mat_ID is 0 "
            "(no structural material in the converted deck). /HEAT/MAT is keyed "
            "on a MATERIAL id, and one the starter cannot resolve is ERROR 1663 "
            "(hm_read_therm.F:135-152), so no thermal material is written for "
            "them — their conduction and heat capacity are LOST. This is the "
            "shape of a THERMAL-ONLY LS-DYNA deck (*CONTROL_SOLUTION SOLN=1). "
            "Radioss DOES have a thermal-only run mode — the engine card "
            "/DT/THERM, which freezes every nodal DOF (resol.F:1738) and paces "
            "the run by the conduction stability step — but it is still armed "
            "per MATERIAL by /HEAT/MAT, so give the parts a structural *MAT_* "
            "as well if they need thermal properties.")
    if not wanted:
        return

    t0_global = _global_initial_temperature(state)
    if t0_global == 0.0:
        # A written T0 of exactly 0.0 is indistinguishable from "not stated" on
        # BOTH cards. hm_read_therm.F:236-237 turns it into PM(23)/RHO_CP and
        # then into 300 K, and cinmas.F:900-905 (c3inmas.F:1516, pmass.F:233)
        # overwrite every node whose /INITEMP value is still exactly 0.0 with
        # that TINI. Measured on thermal-load/main_steel_frame.k, whose header
        # says "The temperature at time 0 is T=0": the starter echoes
        # T0 (INITIAL TEMPERATURE) = 300.0.
        state.warn(
            "The deck's model-wide temperature at t = 0 is exactly 0.0, which "
            "is the one value Radioss cannot tell from 'not stated'. "
            "hm_read_therm.F:236-237 replaces a zero /HEAT/MAT T0 by 300 K, "
            "and cinmas.F:900-905 then overwrites every node whose /INITEMP "
            "value is still exactly 0.0 with that same 300 K. On a deck whose "
            "/IMPTEMP covers every node this is harmless (resol.F:1801-1803 "
            "calls FIXTEMP once before the first element loop), but a deck "
            "driven only by an /INITEMP at 0.0, or whose /IMPTEMP covers a "
            "subset, starts 300 K away from where it says it starts. Shift the "
            "whole temperature field by a documented offset if that matters.")
    refused: List[int] = []
    for mid in sorted(wanted):
        if mid in state.mat_tabulated_jc:
            # The *MAT_ADD_THERMAL_EXPANSION route already refused (and named)
            # this in _resolve_expansion; this catches the other way in - a
            # *PART TMID naming a *MAT_THERMAL_* on a LAW109 part.
            refused.append(mid)
            state.therm_stress_cards.pop(mid, None)
            continue
        # ONE /HEAT/MAT per material id, but *PART TMID is per PART — so two
        # parts sharing a mid may name two DIFFERENT *MAT_THERMAL_ISOTROPICs.
        # Only one set of values can be written; say which, instead of letting
        # the dict-iteration order decide silently.
        tms = {}
        for pid, part in sorted(state.parts.items()):
            if part.mid != mid:
                continue
            t = _thermal_material_for_part(state, pid)
            if t is not None:
                tms.setdefault(t.tmid, t)
        tm = next(iter(tms.values())) if tms else None
        if len(tms) > 1:
            state.warn(
                f"/HEAT/MAT/{mid}: the parts on this material name "
                f"{len(tms)} DIFFERENT *MAT_THERMAL_* materials "
                f"{sorted(tms)} through their *PART TMID. /HEAT/MAT is keyed "
                "on the MATERIAL id (hm_read_therm.F:135-152), so only ONE "
                f"set of thermal properties can be written — TMID {tm.tmid} "
                "is used and the others are DROPPED. (The expansion path "
                "splits the material on a differing TMID; a TMID-only part "
                "has no card of its own to split on.) Give the parts distinct "
                "structural material ids if they need distinct conductivities.")
        rho = _structural_density(state, mid)
        t1 = _law_melt_temperature(state, mid)
        bs = al = bl = 0.0
        # A thermal material that IS bound but could not be converted must not
        # come out under the "no *MAT_THERMAL_* is bound to this material (no
        # *PART TMID names one)" message below: that premise would be false,
        # and a true conclusion resting on a false premise still misinforms
        # (the #129 lesson). The refusal itself has already been named.
        refused_tm = None
        unparsed = _unparsed_thermal_tmid(state, mid) if tm is None else 0
        if tm is not None and not _thermal_material_usable(state, tm, mid):
            refused_tm, tm = tm, None
        if isinstance(tm, MatThermalIsotropicTD):
            _sample_td_lc_curves(state, tm)
            fit = _fit_td_conductivity(state, tm, mid, t1)
            if fit is None:
                refused_tm, tm = tm, None
            else:
                rho_cp, a_s, bs, al, bl = fit
                _warn_thermal_generation_drops(state, tm, mid)
        elif tm is not None:
            # T01 and the isotropic-in-fact T02 both land here: ONE
            # conductivity, so k = AS with BS = 0, and AL/BL mirror it.
            rho_cp = (tm.tro or rho) * tm.hc
            a_s = getattr(tm, "tc", 0.0) or getattr(tm, "k1", 0.0)
            al = a_s
            _warn_thermal_generation_drops(state, tm, mid)
            if rho_cp <= 0.0:
                state.warn(
                    f"*MAT_THERMAL_* {tm.tmid} -> /HEAT/MAT/{mid}: the "
                    f"volumetric capacity (TRO or RO) x HC is {rho_cp:g}. HC is "
                    "the specific heat per unit MASS in LS-DYNA and RHO0_CP is "
                    "per unit VOLUME in Radioss (hm_read_therm.F:244 stores it "
                    "in PM(69), the same slot LAW2's adiabatic heating reads), "
                    "so a blank HC or a blank density leaves the material with "
                    "no capacity at all.")
                rho_cp = _RHO_CP_PLACEHOLDER
        if tm is None:
            # The mechanical law's own volumetric rhoC_p beats the placeholder
            # whenever it has one: with the local adiabatic branch switched off
            # (see _warn_law2_self_heating) the FE thermal path is what paces
            # any heat that does appear, and it divides by exactly this cell.
            rho_cp = _law_own_rho_cp(state, mid) or _RHO_CP_PLACEHOLDER
            a_s = 0.0
            if refused_tm is not None:
                why = (f"*MAT_THERMAL_* {refused_tm.tmid} IS bound to this "
                       "material through a *PART TMID but could NOT be "
                       "converted (see the refusal above)")
            elif unparsed:
                # The third case, and the premise of the other two would be
                # FALSE here: a *PART TMID DOES name a thermal material, but
                # it is a *MAT_THERMAL_* spelling this converter does not
                # parse, so it never reached any registry (the #130 class —
                # a true conclusion on a false premise still misinforms).
                why = (f"*PART TMID names thermal material {unparsed}, whose "
                       "*MAT_THERMAL_* spelling k2rad does not parse (it is "
                       "listed under 'Skipped (unsupported) keywords')")
            else:
                why = ("no *MAT_THERMAL_* is bound to this material "
                       "(no *PART TMID names one)")
            state.warn(
                f"/HEAT/MAT/{mid}: {why}, so its CONDUCTIVITY is unknown and "
                "AS = BS = 0 is written: heat does NOT flow between nodes. That "
                "is faithful for a structural-only deck whose temperatures are "
                "all prescribed by *LOAD_THERMAL_* or *BOUNDARY_TEMPERATURE — "
                "the thermal expansion then reads exactly the field the deck "
                "states — but any node NOT covered by a driver keeps its "
                "initial temperature forever, and a deck driven by a HEAT "
                "SOURCE (*BOUNDARY_FLUX / _CONVECTION / _RADIATION) instead has "
                "nowhere for that heat to go: it piles up on the loaded surface "
                "nodes. (That case gets its own warning where the boundary "
                f"cards are resolved.) RHO0_CP = {rho_cp:g} is "
                + ("the mechanical law's own volumetric rhoC_p."
                   if rho_cp != _RHO_CP_PLACEHOLDER else
                   "a placeholder. With no conduction and no strain-energy "
                   f"source the nodal heat balance has no term at all, so its "
                   "value cannot change any result — and EFRAC is written at "
                   f"{_efrac(state):g} here"
                   + (", which switches that source off (it scales the nodal "
                      "term at cmain3.F:360 for shells and mmain.F90:2036 for "
                      "solids)."
                      if _efrac(state) <= _EFRAC_OFF else
                      " because *CONTROL_THERMAL_SOLVER states FWORK, which "
                      "does NOT switch it off: mechanical work becomes heat "
                      "here (cmain3.F:360 for shells, mmain.F90:2036 for "
                      "solids) and this placeholder capacity then paces the "
                      "temperature it produces. State the material's real "
                      "capacity with *MAT_THERMAL_ISOTROPIC + *PART TMID."))
                + " Add *MAT_THERMAL_ISOTROPIC + *PART TMID if the model needs "
                "real conduction.")
        if t1:
            state.warn(
                f"/HEAT/MAT/{mid}: T1 is set to the material's own melting "
                f"temperature ({t1:g}) rather than left blank. /HEAT/MAT "
                "OVERWRITES MAT_PARAM%THERM%TMELT, which is the variable "
                "mmain.F90:790 divides by for the Johnson-Cook T*, and a blank "
                "T1 defaults to 1e20 — measured: the law echoes MELTING "
                "TEMPERATURE 1800 while /HEAT/MAT echoes 1e20, T* collapses to "
                "0 and the thermal softening is dead at 0 warnings.")
        law_rhocp = _law_own_rho_cp(state, mid)
        if law_rhocp and abs(law_rhocp - rho_cp) > 1e-12 * max(law_rhocp, 1.0):
            state.warn(
                f"/HEAT/MAT/{mid}: RHO0_CP = {rho_cp:g} OVERRIDES the material "
                f"law's own rhoC_p = {law_rhocp:g} (starter WARNING 765, "
                "'SPECIFIC HEAT DEFINED IS DIFFERENT FROM ... /HEAT/MAT ... "
                "WILL BE USED'). It is the FE thermal solve's nodal capacity "
                "from here on; the law's own value is no longer used for "
                "anything, because its local adiabatic branch is switched off "
                "by the presence of the /HEAT/MAT.")
        _warn_law2_self_heating(state, mid)
        state.heat_mat_cards[mid] = (
            t0_global if t0_global is not None else 0.0,
            rho_cp, a_s, bs, t1, al, bl, _efrac(state))

    if refused:
        state.warn(
            f"/HEAT/MAT: material(s) {refused} are *MAT_TABULATED_JOHNSON_COOK "
            "(/MAT/LAW109), which integrate their OWN element temperature from "
            "plastic work. A /HEAT/MAT would switch LAW109 to the "
            "imposed-temperature path and kill that self-heating "
            "(sigeps109.F:411-414), so none is written even though a *PART TMID "
            "names a *MAT_THERMAL_* for them - the thermal properties are "
            "DROPPED rather than the law's own physics.")


def _warn_law2_self_heating(state: ConversionState, mid: int) -> None:
    """A /HEAT/MAT takes *MAT_015 (/MAT/LAW2, /MAT/LAW4) OFF its own adiabatic
    plastic-work heating — a silent change of physics that must be named.

    Both element families gate the LOCAL update on there being NO thermal
    solve, not on the capacity:
      ``sigeps02c.F:220-231``  ``IF (JTHE /= 0) THEN FHEAT += SIGY*DPLA*VOL*EFRAC``
                               ``ELSEIF (RHOCP > ZERO) TEMPEL += SIGY*DPLA/RHOCP``
      ``m2law.F:547-560``      the same pair for solids.
    With a ``/HEAT/MAT`` present ``JTHE /= 0``, so the ``ELSEIF`` never runs and
    the element temperature stops rising from plastic work. What replaces it is
    the FE thermal path, and LAW2 leaves ``MAT_PARAM%HEAT_FLAG = 0`` (only
    mat004/074/084/104/109 set it, ``hm_read_mat04.F:274`` &c.), so
    ``cforc3.F:696`` feeds ``THERMC`` the EFRAC-scaled deformation energy
    ``DIE`` (``cmain3.F:360``) rather than the law's own ``FHEAT``.

    **What EFRAC then is depends on the deck**, so the message READS the
    emitted value instead of asserting a constant: a ``*CONTROL_THERMAL_SOLVER``
    FWORK reaches it (``_efrac``), and a deck with no such card keeps
    ``_EFRAC_OFF`` because ``*MAT_ADD_THERMAL_EXPANSION`` /
    ``*MAT_THERMAL_ISOTROPIC`` state nothing about heat generation. The two
    cases are a different physics story and the warning tells them apart.

    The pair is still emitted (the deck asked for the expansion, and the
    Johnson-Cook ``T*`` softening still follows the PRESCRIBED field, with
    ``T1`` carrying the law's own melting temperature). Refusing it — the
    LAW109 treatment — is not right here: LAW109 integrates a temperature the
    /HEAT/MAT would overwrite outright, while LAW2 only loses a source term.
    But it is a different model from the one the .k file states, so it is
    reported, not assumed acceptable.
    """
    m = state.mat_johnson_cook.get(mid)
    if m is None:
        return
    efrac = _efrac(state)
    state.warn(
        f"/HEAT/MAT/{mid} on a *MAT_015-derived law (/MAT/LAW2 or LAW4): the "
        "law's OWN adiabatic plastic-work heating is switched OFF by the "
        "presence of a thermal solve. sigeps02c.F:220 (shells) and "
        "m2law.F:547 (solids) read 'IF (JTHE /= 0) ... ELSEIF (RHOCP > ZERO) "
        "TEMPEL += SIGY*DPLA/RHOCP', so the local branch is skipped as soon as "
        "the material has a /HEAT/MAT. What replaces it is the FE thermal "
        "path, whose nodal source is EFRAC-scaled (cmain3.F:360 for shells, "
        f"PM(90) = EFRAC; mmain.F90:2036 for solids), and EFRAC is {efrac:g} "
        "on this deck"
        + (" because no *CONTROL_THERMAL_SOLVER states FWORK and "
           "*MAT_ADD_THERMAL_EXPANSION / *MAT_THERMAL_ISOTROPIC say nothing "
           "about heat generation. Net effect: the element temperature now "
           "follows ONLY the prescribed *LOAD_THERMAL_* / "
           "*BOUNDARY_TEMPERATURE field (or a heat-source boundary), and the "
           "Johnson-Cook thermal softening no longer develops from plastic "
           "work. If the run needs adiabatic self-heating, drop the thermal "
           "card from THIS part (the material can be split by giving the part "
           "its own *MAT_015)."
           if efrac <= _EFRAC_OFF else
           " (*CONTROL_THERMAL_SOLVER FWORK). So the plastic work DOES still "
           "become heat — but through the FE path and on a different "
           "quantity: Radioss scales the element's TOTAL internal-energy "
           "increment, elastic part included, where LS-DYNA's FWORK applies "
           "to mechanical work. The temperature is then spread by conduction "
           "instead of staying in the element, so the Johnson-Cook softening "
           "follows a smoother field than the adiabatic one the .k states."))


def _law_own_rho_cp(state: ConversionState, mid: int) -> float:
    """The volumetric ``rhoC_p`` a material law already carries (LAW2/LAW4 from
    ``*MAT_015``; k2rad pre-multiplies LS-DYNA's per-mass CP by RHO there)."""
    m = state.mat_johnson_cook.get(mid)
    if m is not None:
        return float(getattr(m, "rhocp", 0.0) or 0.0)
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Temperature drivers
# ─────────────────────────────────────────────────────────────────────────────

def _driver_key(d) -> Tuple:
    """The identity of a driver's node scope, for the /GRNOD memo.

    An element-expanded record (``nids`` non-empty) has no ``sid`` to key on —
    ``sid = 0`` would mean "every node in the model" and would make two
    different element groups share one /GRNOD.
    """
    if getattr(d, "nids", None):
        return ("nids", tuple(d.nids))
    return (d.sid, d.is_node, d.nsidex, d.boxid, d.drive_exempt)


def _driver_nodes(state: ConversionState, sid: int, is_node: bool,
                  label: str, seen: Optional[Set[Tuple[int, bool]]] = None,
                  nsidex: int = 0, boxid: int = 0,
                  quiet: bool = False,
                  drive_exempt: bool = False,
                  nids: Optional[List[int]] = None) -> List[int]:
    """The node ids one driver applies to.

    *nids*, when given, is an EXPLICIT node list that wins over ``sid`` — the
    ``*LOAD_THERMAL_*_ELEMENT_<FAMILY>`` path expands elements to their own
    nodes, which are not any ``*SET_NODE`` the deck defines.

    ``sid = 0`` on a set-based card means EVERY node in the model (Vol I R17,
    ``*INITIAL_TEMPERATURE_SET``: *"NSID = 0 ... all nodes"*; the
    ``*LOAD_THERMAL_*`` cards default the same way).

    ``NSIDEX`` is *"Nodal set ID containing nodes that are exempted from the
    imposed temperature"* (pp.33-166/33-179) and is SUBTRACTED here: /IMPTEMP
    is a hard Dirichlet reset applied every cycle (fixtemp.F:180-200), so a
    node the card excludes must not be in its /GRNOD at all. ``BOXID``
    restricts NSID to a ``*DEFINE_BOX``, which k2rad does not resolve — it is
    named rather than silently ignored.

    *drive_exempt* INVERTS the NSIDEX step: the record is the card's second
    driver, the one that holds the exempted nodes at TE (or TBE + TSE·f), so it
    wants NSIDEX ∩ NSID rather than NSID − NSIDEX. The two records together
    partition the set exactly as the LS-DYNA card does.

    *seen* de-duplicates the missing-set warning: the emitter asks for the same
    driver twice (once for the /IMPTEMP, once for the /TH/NODE TEMP group) and
    one missing set must not be reported twice. *quiet* silences the per-driver
    diagnostics for the second, node-list-only pass.
    """
    if nids:
        return [n for n in nids if n in state.nodes]
    if is_node:
        return [sid] if sid in state.nodes else []
    if sid == 0:
        nodes: List[int] = sorted(state.nodes)
    else:
        ns = state.node_sets.get(sid)
        if ns is None:
            if seen is None or (sid, is_node) not in seen:
                state.warn(
                    f"{label}: *SET_NODE {sid} is not defined in the converted "
                    "deck, so there is no /GRNOD to impose the temperature on "
                    "— card dropped. (A *SET_NODE_GENERAL or *SET_NODE_COLUMN "
                    "the converter does not read leaves exactly this hole.)")
            if seen is not None:
                seen.add((sid, is_node))
            return []
        nodes = [n for n in (ns[1] if isinstance(ns, tuple) else ns)
                 if n in state.nodes]
    if boxid and not quiet:
        state.warn(
            f"{label}: BOXID={boxid} restricts the driven nodes to the ones "
            "inside a *DEFINE_BOX ('All nodes in box which belong to NSID are "
            "initialized. Others are excluded', Vol I R17 p.33-166). k2rad "
            "does not resolve *DEFINE_BOX for this card, so the restriction is "
            "IGNORED and the temperature reaches every node of the set — "
            "replace the box by an explicit *SET_NODE if that matters.")
    if nsidex:
        ex = state.node_sets.get(nsidex)
        if ex is None:
            if not quiet:
                state.warn(
                    f"{label}: NSIDEX={nsidex} names the nodes EXEMPTED from "
                    "the imposed temperature, but that *SET_NODE is not in the "
                    "converted deck, so nothing can be subtracted — the "
                    "temperature reaches nodes the card excludes.")
            if drive_exempt:
                return []
        else:
            drop = set(ex[1] if isinstance(ex, tuple) else ex)
            if drive_exempt:
                return [n for n in nodes if n in drop]
            kept = [n for n in nodes if n not in drop]
            if not quiet and len(kept) != len(nodes):
                state.warn(
                    f"{label}: NSIDEX={nsidex} exempts "
                    f"{len(nodes) - len(kept)} node(s) from the imposed "
                    "temperature (Vol I R17 p.33-166); they are left OUT of "
                    "the /IMPTEMP group, because /IMPTEMP is a hard Dirichlet "
                    "reset every cycle (fixtemp.F:180-200) and would otherwise "
                    "drive them anyway.")
            nodes = kept
    return nodes


def _resolve_drivers(state: ConversionState) -> None:
    """Resolve every driver's /FUNCT (and warn when nothing can consume it)."""
    if not (state.initial_temperatures or state.imposed_temperatures):
        return
    if not state.heat_mat_cards:
        state.warn(
            "The deck states a temperature driver (*INITIAL_TEMPERATURE / "
            "*LOAD_THERMAL_* / *BOUNDARY_TEMPERATURE) but NO material in the "
            "converted deck has a /HEAT/MAT, so no thermal solve is armed at "
            "all (hm_read_therm.F:253 is the only thing that sets "
            "MAT_PARAM%ITHERM). /INITEMP and /IMPTEMP on such a deck are "
            "accepted at 0 starter errors and do nothing — the guard in "
            "hm_read_initemp.F:108-113 is commented out — so they are NOT "
            "emitted. Add *MAT_ADD_THERMAL_EXPANSION (for expansion) or "
            "*MAT_THERMAL_ISOTROPIC + *PART TMID (for conduction) to give the "
            "temperature field something to act on.")
        state.initial_temperatures.clear()
        state.imposed_temperatures.clear()
        return

    for d in state.imposed_temperatures:
        label = f"{d.source} (set/node {d.sid})"
        if d.lcid:
            curve = state.curves.get(d.lcid)
            if curve is None or len(curve.pts) < 2:
                state.warn(
                    f"{label}: curve {d.lcid} is not defined in the deck (or "
                    "has fewer than two points). /IMPTEMP's func_IDT is "
                    "MANDATORY — hm_read_imptemp.F answers ERROR 120 'WRONG "
                    "REFERENCE TO FUNCTION ID=0' once PER NODE — so the driver "
                    "is dropped rather than emitted with a dangling id.")
                continue
            pts = list(curve.pts)
            shifted = False
            if d.tbirth:
                shifted = True
                # /IMPTEMP's T_start does TWO things where LS-DYNA's TBIRTH
                # does one. fixtemp.F:118-129 computes TS = TT - STARTT and
                # evaluates the function at TS*FACX, so T_start is BOTH the
                # activation gate AND the curve's time origin; LS-DYNA reads
                # its (t, T) pairs at absolute time and only ignores the
                # constraint before TBIRTH ("Before this point in time the
                # temperature constraint is ignored", Vol I R17 p.5-151).
                # Pre-shifting the abscissae by -TBIRTH makes the engine
                # evaluate f(t) again: g(t - TBIRTH) = f(t). Points before
                # TBIRTH are kept (negative abscissae are never reached inside
                # the window) so the interpolation at t = TBIRTH is exact.
                pts = [(x - d.tbirth, y) for x, y in pts]
                state.warn(
                    f"{label}: TBIRTH={d.tbirth:g} becomes /IMPTEMP's T_start, "
                    "which is BOTH the activation gate and the curve's time "
                    "origin (fixtemp.F:118-129 evaluates the function at "
                    "t - T_start, while LS-DYNA reads its (t, T) pairs at "
                    "absolute time). The driver curve is therefore emitted as "
                    f"a copy shifted by -{d.tbirth:g} so the two agree; the "
                    "shifted copy is what the deck carries, not the original "
                    "curve id.")
            ts = d.scale
            if d.offset or shifted:
                # T = TB + TS*f(t) (Vol I R17, *LOAD_THERMAL_VARIABLE Remark 1).
                # /IMPTEMP computes Fscale_y*f((t-T_start)/Ascale_x) only
                # (fixtemp.F:180-200) — there is no additive slot — so the
                # offset is baked into a synthesized copy of the curve.
                fid = state.next_curve_id()
                state.curves[fid] = Curve(
                    lcid=fid, title=f"Auto_imptemp_{fid}",
                    sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
                    pts=[(x, d.offset + ts * y) for x, y in pts])
                state.curve_order.append(fid)
                d.func_id = fid
                d.scale = 1.0
            else:
                d.func_id = d.lcid
            # "T0 = TB + TS x f(0)" (Vol I R17 p.33-180 Remark 1) — always
            # computed from the ORIGINAL scale, never from the 1.0 the
            # synthesized curve has just absorbed.
            d.initial_temp = d.offset + ts * curve.pts[0][1]
            continue
        # Constant temperature: a two-point function, never func_IDT = 0.
        value = d.const + d.offset
        fid = state.next_curve_id()
        state.curves[fid] = Curve(
            lcid=fid, title=f"Auto_imptemp_const_{fid}",
            sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
            pts=[(0.0, value), (1.0e6, value)])
        state.curve_order.append(fid)
        d.func_id = fid
        d.scale = 1.0
        d.initial_temp = value
    state.imposed_temperatures[:] = [d for d in state.imposed_temperatures
                                     if d.func_id]

    # A driver states the temperature at t = 0 as well - "The temperature at
    # time = 0 becomes the REFERENCE temperature for the thermal material"
    # (*LOAD_THERMAL_LOAD_CURVE, Purpose). /HEAT/MAT's T0 cannot carry it: the
    # reader turns a BLANK OR ZERO T0 into 300 K (hm_read_therm.F:236-237), and
    # a deck whose curve starts at 0 would then begin 300 K away from where it
    # states it begins. /INITEMP can - it wins over /HEAT/MAT T0 (measured:
    # /INITEMP 20 against T0 500 gives 20) and writes its value verbatim - so
    # one is synthesized per driver when the deck states no
    # *INITIAL_TEMPERATURE of its own.
    if not state.initial_temperatures:
        for d in state.imposed_temperatures:
            if d.initial_temp is None:
                continue
            # The companion must carry the driver's OWN scope. An /INITEMP over
            # the whole set beside an /IMPTEMP over set-minus-NSIDEX would
            # initialise the exempted nodes at the very temperature the card
            # exempts them from, and (with no driver of their own) leave them
            # there.
            state.initial_temperatures.append(InitialTemperature(
                sid=d.sid, temp=d.initial_temp, is_node=d.is_node,
                nsidex=d.nsidex, boxid=d.boxid,
                drive_exempt=d.drive_exempt, nids=list(d.nids)))


# ─────────────────────────────────────────────────────────────────────────────
# *BOUNDARY_{FLUX,CONVECTION,RADIATION} → /IMPFLUX, /CONVEC, /RADIATION
# ─────────────────────────────────────────────────────────────────────────────

#: What each converted boundary card is called, for messages and titles.
_BC_CARD = {"FLUX": "/IMPFLUX", "CONVEC": "/CONVEC",
            "RADIATION": "/RADIATION"}


def _bc_segments(state: ConversionState, bc) -> Optional[List[List[int]]]:
    """The segment list one boundary record applies to, or ``None``.

    ``_SET`` resolves the ``*SET_SEGMENT``; ``_SEGMENT`` uses the card's own
    ``N1..N4``, collapsed to three nodes for the ``N4 = N3`` triangle spelling
    exactly as ``handle_set_segment`` does — ``hm_read_surf.F:318-321`` puts
    the degenerate corner back inside the starter.
    """
    if any(bc.nodes):
        # POSITIONAL, exactly like handle_set_segment: only a TRAILING zero (or
        # the N4 = N3 spelling) makes a triangle — Vol I R17 p.43-63 *"To define
        # a triangular segment, set N4 = N3"*, and hm_read_surf.F:318-321
        # restores the degenerate corner inside the starter. A zero in N2 or N3
        # is a malformed card, and squeezing it out would silently build a
        # DIFFERENT triangle out of the corners that remain.
        nodes = list(bc.nodes)
        while len(nodes) > 3 and (nodes[-1] == 0 or nodes[-1] == nodes[-2]):
            nodes.pop()
        missing = [n for n in nodes if n not in state.nodes]
        if len(nodes) < 3 or missing:
            state.warn(
                f"{bc.source}: the segment's node(s) {missing or nodes} are "
                "not in the converted deck (a zero in N1..N3 is a malformed "
                "card — only a TRAILING zero or N4 = N3 makes a triangle), so "
                "no /SURF/SEG can be built — card dropped.")
            return None
        return [nodes]
    ss = state.segment_sets.get(bc.ssid)
    if ss is None:
        state.warn(
            f"{bc.source}: *SET_SEGMENT {bc.ssid} is not defined in the "
            f"converted deck, so there is no /SURF for {_BC_CARD[bc.kind]} to "
            "name — card dropped. (This is a guard k2rad has to own: "
            "hm_read_convec.F:139-170 and hm_read_radiation.F:148-182 wrap the "
            "whole segment loop in IF(IS > 0) with NO else branch and NO "
            "ANCMSG, so an unresolvable surf_ID is a total no-op at 0 ERROR "
            "and 0 WARNING — MEASURED: the card is not even echoed.)")
        return None
    segs = [list(s) for s in ss.segments]
    if not segs:
        state.warn(f"{bc.source}: *SET_SEGMENT {bc.ssid} is empty — card "
                   "dropped.")
        return None
    return segs


def _bc_constant_function(state: ConversionState, value: float,
                          tag: str) -> int:
    """A synthesized two-point ``/FUNCT`` of constant ordinate *value*.

    ``fct_IDT`` is MANDATORY on all three cards: a blank or zero id is
    ``ERROR 120 WRONG REFERENCE TO FUNCTION ID=0``, measured once per card.
    The three sites are consecutive loops in ``starter/source/system/fsdcod.F``
    — ``:1591-1603`` for ``/CONVEC`` (whose message text is MISLABELLED
    ``C1='FIXED FLUX'``), ``:1607-1619`` for ``/RADIATION``
    (``'FIXED RADIATIVE FLUX'``) and ``:1623-1635`` for ``/IMPFLUX``
    (``'FIXED HEAT FLUX'``). So the constant form of every LS-DYNA cell that
    Radioss carries as a curve gets a real function — the same treatment
    ``*BOUNDARY_TEMPERATURE``'s TLCID = 0 form already gets.
    """
    fid = state.next_curve_id()
    state.curves[fid] = Curve(
        lcid=fid, title=f"Auto_{tag}_{fid}",
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
        pts=[(0.0, value), (1.0e6, value)])
    state.curve_order.append(fid)
    return fid


def _bc_scaled_function(state: ConversionState, lcid: int, mult: float,
                        tag: str) -> int:
    """A copy of curve *lcid* with *mult* BAKED INTO THE ORDINATE.

    Used for ``/RADIATION`` **and** ``/CONVEC``, and it is a workaround for two
    measured OpenRadioss defects, not a stylistic choice. Both live in the
    ``/PARITH/ON`` branch (the engine DEFAULT — k2rad writes ``/PARITH`` only
    when the deck carries a ``*CONTROL_PARALLEL``), and both concern the
    ``Fscale_y`` cell the two cards call ``FCY``:

    ``/RADIATION`` — COMPOUNDING.
        ``radiation.F:249`` places ``T_INF = FCY*T_INF`` OUTSIDE the
        ``IF(IFUNC_OLD /= IFUNC .OR. TS_OLD /= TS)`` cache guard it opens at
        ``:239``, so the ordinate scale is re-applied ONCE PER SEGMENT: with
        six segments and ``FSCALE = 1000`` the environment temperature ran
        1e3, 1e6, … 1e18 and ``Inf**4 - Inf**4`` produced NaN within a few
        cycles. Four-run isolation: 6 segments + FSCALE 1000 + P/ON → NaN; the
        same deck with T_inf in the curve and FSCALE 1 → 0.33750793 (correct);
        P/OFF → 0.33750793; one segment + FSCALE 1000 → correct either way.

    ``/CONVEC`` — a STALE CACHE, which is a different defect with the same
    cure. ``convec.F:241`` really does put the multiply INSIDE its guard, so
    convection never compounds — but the guard's KEY at ``convec.F:234`` is
    ``IF(IFUNC_OLD /= IFUNC .OR. TS_OLD /= TS)`` and ``FCY_OLD`` is missing
    from it, while the ``/PARITH/OFF`` branch at ``convec.F:127`` does carry
    ``.OR. FCY_OLD /= FCY``. So two ``/CONVEC`` cards that share ONE ``funct``
    at different ``Fscale_y`` values silently reuse the FIRST card's ``T_INF``.
    Worse, ``IFUNC_OLD``/``TS_OLD`` are OMP-private, so the answer depends on
    the THREAD COUNT. MEASURED on converter output (1 mm brick,
    ``RHO0_CP = 3.611``, six faces, h = 100, two ``*BOUNDARY_CONVECTION_SET``
    records both on TLCID 900 at TMULT 1.0 and 2.0, ENDTIM 2.4e-3): the
    unfixed deck stores ``CONVECTION HEAT = 1389.1850`` mJ at ``nt=1`` and
    ``1425.3912`` at ``nt=6``; the fixed deck stores ``2381.4601`` at BOTH,
    against a closed form of ``2381.4170`` (+0.0018 %). All four runs: 16 823
    cycles, 0 ERROR / 0 WARNING / NORMAL TERMINATION. The ``nt=1`` figure is
    the clean collapse — 1389.16 is the closed form with BOTH cards reading the
    first one's ``T_inf`` — which identifies the mechanism exactly.

    Writing ``FSCALE = 1.0`` neutralises BOTH exactly — 1.0 re-applied N times
    is 1.0, and a stale 1.0 is the same 1.0 — with no engine patch.
    ``/IMPFLUX`` needs no such treatment — ``fixflux.F:278-288`` caches the
    UNSCALED ``FLUX_DENS`` and applies ``FCY`` per record at ``:300``/``:322``/
    ``:338``, outside the guard — and neither does ``/IMPTEMP``, whose
    ``fixtemp.F:180-199`` multiplies by ``FAC = VAL(4,N)`` once per entry with
    no cache at all.
    """
    src = state.curves[lcid]
    fid = state.next_curve_id()
    state.curves[fid] = Curve(
        lcid=fid, title=f"Auto_{tag}_{fid}",
        sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
        pts=[(x, mult * y) for x, y in src.pts])
    state.curve_order.append(fid)
    return fid


def _bc_common_drops(state: ConversionState, bc) -> None:
    """The two cells every one of the three cards carries and none can hold."""
    if bc.loc:
        state.warn(
            f"{bc.source}: LOC={bc.loc} selects a thick-thermal-shell SURFACE "
            "(-1 lower, 0 middle, +1 upper). Radioss applies a thermal "
            f"boundary to the SEGMENT's nodes ({_BC_CARD[bc.kind]} splits the "
            "segment's heat equally over them), and its nodes carry one "
            "temperature each, so the through-thickness distinction is "
            "dropped.")
    if bc.pserod:
        # The erosion paragraph is a DIFFERENT page and remark number on each
        # of the three cards; one citation copied across all three would be
        # wrong on two of them.
        cite = {"FLUX": "p.5-49 Remark 5",
                "CONVEC": "p.5-32 Remark 4",
                "RADIATION": "p.5-124 Remark 4"}[bc.kind]
        state.warn(
            f"{bc.source}: PSEROD={bc.pserod} asks LS-DYNA to re-apply this "
            "boundary condition to segments newly EXPOSED as solid elements "
            f"erode (Vol I R17 {cite}). Radioss has no such mechanism "
            "at all: convecoff.F/radiatoff.F only DEACTIVATE existing segments "
            "and run solely from DESACTI (the /ACTIV path), and there is no "
            "fixfluxoff at all — so the boundary stays on the ORIGINAL "
            "segments for the whole run, including after their elements are "
            "deleted. The field is dropped.")


def _resolve_thermal_boundaries(state: ConversionState) -> None:
    """Decide every /IMPFLUX, /CONVEC and /RADIATION — the per-field verdicts.

    Runs after ``_resolve_heat_materials`` because the first question is
    whether any material has a ``/HEAT/MAT`` at all: ``ITHERM_FE`` is the gate
    on the engine's ``CONVEC`` / ``RADIATION`` / ``FIXFLUX`` calls
    (``resol.F:2994/3006/3025``), so on a deck with none the three cards are
    read, echoed and completely inert — measured: a ``/CONVEC`` on a part with
    no ``/HEAT/MAT`` gives 0 ERROR and no diagnostic at all beyond the
    ``/TH``-side ``WARNING 1087``.
    """
    if not state.thermal_boundaries:
        return
    if not state.heat_mat_cards:
        kinds = sorted({_BC_CARD[b.kind] for b in state.thermal_boundaries})
        # A *PART TMID naming a *MAT_THERMAL_* spelling k2rad does not parse
        # never reaches _resolve_heat_materials' `wanted` set at all (it is
        # built from the parts whose TMID DOES resolve), so that function's own
        # "unparsed" arm cannot fire on this shape. Without this screen the
        # message below prescribed exactly what the deck already has — the
        # #125 class. Measured: a deck whose *PART TMID names a
        # *MAT_THERMAL_ORTHOTROPIC_TD beside a *BOUNDARY_CONVECTION_SET.
        unparsed = sorted({
            part.tmid for pid, part in state.parts.items()
            if getattr(part, "tmid", 0)
            and _thermal_material_for_part(state, pid) is None})
        state.warn(
            "The deck states a thermal boundary condition "
            "(*BOUNDARY_FLUX / _CONVECTION / _RADIATION) but NO material in "
            "the converted deck has a /HEAT/MAT, so no thermal solve is armed "
            "at all: hm_read_therm.F:253 is the only thing that sets "
            "MAT_PARAM%ITHERM, hm_read_part.F:366 -> ale_euler_init.F:193-201 "
            "turns that into GLOB_THERM%ITHERM_FE, and resol.F:2994/3006/3025 "
            "gate CONVEC, RADIATION and FIXFLUX on it. "
            + ", ".join(kinds) + " on such a deck would be accepted at 0 "
            "starter errors and do NOTHING, so none is emitted. "
            + (f"*PART TMID {unparsed} names a thermal material whose "
               "*MAT_THERMAL_* spelling k2rad does not parse (it is in the "
               "skipped-keyword list), so the binding the deck states is "
               "there but its properties never arrive — state the material "
               "as *MAT_THERMAL_ISOTROPIC or *MAT_THERMAL_ISOTROPIC_TD, which "
               "this converter reads."
               if unparsed else
               "Add *MAT_THERMAL_ISOTROPIC + *PART TMID (which also gives the "
               "heat somewhere to conduct to) and the cards appear."))
        state.thermal_boundaries.clear()
        return
    conduction = any(c[2] or c[3] for c in state.heat_mat_cards.values())
    kept = []
    for bc in state.thermal_boundaries:
        # The SEGMENT SOURCE is resolved FIRST, before any per-kind resolver
        # announces what the record converts to and before any /FUNCT is minted
        # for it. It used to be resolved at emission time, two passes later,
        # which meant a record naming an undefined *SET_SEGMENT printed a full
        # "-> /CONVEC with H = 100 ..." sentence and left an orphan curve
        # behind before the drop message arrived (the #130 class: a statement
        # of what the deck will emit that does not mirror the emitter's own
        # drop conditions).
        bc.segments = _bc_segments(state, bc)
        if bc.segments is None:
            _bc_common_drops(state, bc)
            continue
        if bc.kind == "FLUX":
            ok = _resolve_flux(state, bc)
        elif bc.kind == "CONVEC":
            ok = _resolve_convec(state, bc)
        else:
            ok = _resolve_radiation(state, bc)
        # The dropped-field accounting runs for EVERY record, refused ones
        # included. Each of the three resolvers has four or five early
        # refusals, and hanging the accounting off the success path would
        # lose the field inventory on exactly the cards a reader most needs
        # it (the #129 "a refusal continue must not skip the accounting"
        # lesson, from the /DYNAIN writer).
        _bc_common_drops(state, bc)
        if ok:
            kept.append(bc)
    state.thermal_boundaries[:] = kept
    if kept and not conduction:
        state.warn(
            f"{len(kept)} thermal boundary condition(s) are emitted onto a "
            "deck whose /HEAT/MAT cards all have AS = BS = 0, i.e. NO "
            "CONDUCTIVITY. The heat has nowhere to go: every source term adds "
            "energy to the SEGMENT's own nodes (convec.F:152, radiation.F:155, "
            "fixflux.F:165) and tempur.F:51 turns it into that node's "
            "temperature, but with k = 0 nothing spreads to the interior — the "
            "loaded surface will heat (or cool) without bound while the rest "
            "of the model stays at its initial temperature. Give the parts a "
            "*MAT_THERMAL_ISOTROPIC through *PART TMID so the conductivity is "
            "stated.")


def _resolve_flux(state: ConversionState, bc) -> bool:
    """*BOUNDARY_FLUX card 2 → /IMPFLUX. **The sign is INVERTED.**

    Vol I R17 p.5-49 Remark 1, verbatim: *"The segment normal has no bearing on
    the flux. A negative flux transfers energy INTO the volume; a positive flux
    transfers energy OUT of the volume."* Radioss is the other way round —
    ``fixflux.F:165-172`` computes ``FLUX = AREA*FLUX_DENS*DT1N`` and then
    ``FTHE(Ni) += FLUX/n``, and ``tempur.F:51`` raises the temperature by
    ``FTHE/MCP``, so a POSITIVE ``FLUX_DENS`` HEATS. ``Fscale_y`` therefore
    carries ``-MLC``. Shipping this unflipped would invert every flux boundary
    condition in the deck at 0 starter diagnostics.

    ``MLC1..MLC4`` are PER-NODE multipliers — Vol I R17 p.5-48 defines each one
    as *"curve multiplier at node Nk"*. ``/IMPFLUX`` has one ``Fscale_y`` and
    splits the segment's heat evenly (``fixflux.F:167``: ``FLUX =
    FOURTH*FLUX``), so unequal weights are inexpressible and the record is
    refused rather than averaged into a load the deck never states.

    **Only the cells that HAVE a node are compared.** On a triangular segment
    — ``N1 N2 N3`` with a trailing blank, or the ``N4 = N3`` spelling of
    p.43-63 — there is no node N4, so MLC4 is blank by construction and takes
    p.5-47's Card 2 default of ``0.``. Comparing it against three stated
    multipliers refused a fully convertible boundary and told the reader to
    "give all four the same multiplier" on a segment this converter itself had
    already read as three-noded (the #125 class). ``bc.segments`` is resolved
    before this runs, so the node count is known: a set that MIXES quads and
    triangles compares all four, because its quads do have an N4.

    ``LCID < 0`` makes the flux a function of TEMPERATURE; ``/IMPFLUX``'s
    ``fct_IDT`` is evaluated at ``(t - TSTART)/ASCALE`` and nothing else
    (``fixflux.F:140``), so that form is refused too.
    """
    mlcs = list(bc.mlcs) or [bc.mult]
    # The widest segment decides: three on an all-triangle card, four as soon
    # as one quad is in the set.
    n = max(len(s) for s in bc.segments) if bc.segments else len(mlcs)
    n = min(max(n, 1), len(mlcs))
    used = mlcs[:n]
    spread = max(used) - min(used)
    if spread > 1e-12 * max(1.0, abs(bc.mult)):
        state.warn(
            f"{bc.source}: MLC1..MLC{n} are PER-NODE flux multipliers and they "
            f"differ (spread {spread:g} about MLC1 = {bc.mult:g}). /IMPFLUX "
            "carries ONE Fscale_y and splits the segment's heat EVENLY over "
            "its nodes (fixflux.F:167-172, FLUX = FOURTH*FLUX), so a per-node "
            "weighting cannot be expressed. Averaging them would state a load "
            "the deck does not — the record is DROPPED. Split the segment, or "
            f"give all {n} the same multiplier."
            + ("" if n == len(mlcs) else
               f" (Only MLC1..MLC{n} are read: the widest segment on this "
               f"record has {n} nodes, and MLCk is 'the curve multiplier at "
               "node Nk', Vol I R17 p.5-48.)"))
        return False
    ignored = [f"MLC{j + 1}={v:g}"
               for j, v in enumerate(mlcs[n:], start=n) if v != 0.0]
    if ignored:
        state.warn(
            f"{bc.source}: " + ", ".join(ignored) + " names a node the "
            f"segment(s) do not have — the widest segment on this record has "
            f"{n} nodes, and MLCk is 'the curve multiplier at node Nk' "
            "(Vol I R17 p.5-48). The cell is IGNORED (it is not compared "
            "against the others and does not scale the emitted /IMPFLUX). "
            "Check the segment's N4 if a four-node face was meant.")
    if bc.lcid < 0:
        state.warn(
            f"{bc.source}: LCID={bc.lcid} < 0 makes the flux a function of "
            f"TEMPERATURE (curve {abs(bc.lcid)} of (temperature, flux) pairs, "
            "Vol I R17 p.5-48). /IMPFLUX evaluates its function at "
            "(t - TSTART)/ASCALE only (fixflux.F:140 FINTER(IFUNC, TS*FCX)) — "
            "there is no temperature-dependent flux anywhere in Radioss — so "
            "the record is dropped.")
        return False
    # LS-DYNA flux OUT of the volume is positive; Radioss FLUX_DENS heats.
    bc.fscale = -bc.mult
    if bc.lcid:
        curve = state.curves.get(bc.lcid)
        if curve is None or len(curve.pts) < 2:
            state.warn(
                f"{bc.source}: curve {bc.lcid} is not defined in the deck (or "
                "has fewer than two points). /IMPFLUX's funct_ID is MANDATORY "
                "— fsdcod.F answers ERROR 120 'WRONG REFERENCE TO FUNCTION "
                "ID=0' — so the record is dropped rather than emitted with a "
                "dangling id.")
            return False
        bc.func_id = bc.lcid
    else:
        # "EQ.0: a constant flux is applied to each node defined by the values
        # MLC1..MLC4" (p.5-48). The magnitude rides Fscale_y, so the function
        # is the constant 1.0.
        bc.func_id = _bc_constant_function(state, 1.0, "impflux_const")
    if bc.fscale == 0.0:
        state.warn(
            f"{bc.source}: the flux resolves to exactly 0. /IMPFLUX cannot "
            "express that — hm_read_impflux.F:150 replaces a zero FSCALE with "
            "the unit-system dimension factor ('IF (FCY == ZERO) FCY = "
            "FCY_DIM'), i.e. the card would run at FULL unit amplitude, the "
            "opposite of what the cell says. The record is DROPPED instead.")
        return False
    state.warn(
        f"{bc.source} -> /IMPFLUX with Fscale_y = {bc.fscale:g}, the NEGATIVE "
        f"of the deck's MLC = {bc.mult:g}. The sign convention is opposite on "
        "the two sides: Vol I R17 p.5-49 Remark 1 says 'a negative flux "
        "transfers energy INTO the volume; a positive flux transfers energy "
        "OUT of the volume', while fixflux.F:165-172 adds "
        "+AREA*FLUX_DENS*dt to the nodal heat and tempur.F:51 turns that into "
        "a temperature RISE. The segment normal is irrelevant on both sides "
        "(Radioss uses |AREA| from a cross-product magnitude), so this ONE "
        "flip is the whole conversion.")
    return True


def _resolve_convec(state: ConversionState, bc) -> bool:
    """*BOUNDARY_CONVECTION card 2 → /CONVEC. **No sign flip.**

    LS-DYNA: ``q'' = h(T_surface - T_inf)`` (Vol I R17 p.5-32 Remark 1), the
    flux OUT of the surface. Radioss: ``FLUX = AREA*H*(T_INF - TE)*DT1``
    added to the nodal heat (``convec.F:152``), i.e. the flux IN. The two
    expressions mirror, so ``h`` maps 1:1 and positive.

    ``HLCID`` is the only refusal: ``GT.0`` makes h a function of time and
    ``LT.0`` a function of the film temperature, while ``/CONVEC``'s ``H`` is
    a raw constant (``hm_read_convec.F:165`` ``FAC(3,K) = H``) and its ONE
    function slot is already spent on ``T_inf``. Flattening the curve to its
    first ordinate would state a coefficient the deck does not.
    """
    hlcid = bc.coef_lcid
    if hlcid:
        state.warn(
            f"{bc.source}: HLCID={hlcid} makes the convection coefficient h a "
            + ("function of TIME" if hlcid > 0 else
               "function of the FILM temperature (T_surface + T_inf)/2")
            + " (Vol I R17 p.5-31). /CONVEC's H is a raw constant "
            "(hm_read_convec.F:165 stores FAC(3,K) = H and convec.F:152 reads "
            "it once per segment per cycle) and the card's ONE function slot "
            "already carries T_inf, so a varying h is inexpressible. "
            "Flattening the curve to a single value would state a coefficient "
            "the deck never does — the record is DROPPED. Set HLCID = 0 and "
            "state h in HMULT if a constant coefficient was meant.")
        return False
    if bc.coef == 0.0:
        state.warn(
            f"{bc.source}: HLCID = 0 makes h the constant HMULT, which is "
            "blank/zero here, so the card imposes no convection at all "
            "(convec.F:152 multiplies the whole flux by H). The record is "
            "dropped rather than emitted as a card that does nothing.")
        return False
    if bc.coef < 0.0:
        state.warn(
            f"{bc.source}: HMULT = {bc.coef:g} is NEGATIVE. Radioss stores it "
            "verbatim (hm_read_convec.F:165, no sign check) and convec.F:152 "
            "computes AREA*H*(T_INF - TE), so a negative h makes the surface "
            "run AWAY from the environment temperature without bound. It is "
            "emitted as stated, because the deck states it — check the sign.")
    if bc.lcid < 0:
        state.warn(
            f"{bc.source}: TLCID={bc.lcid} < 0 is not a form Vol I R17 p.5-31 "
            "defines for the environment temperature (only GT.0 = a curve of "
            "time and EQ.0 = the constant TMULT). The record is dropped rather "
            "than guessed at.")
        return False
    if bc.lcid:
        curve = state.curves.get(bc.lcid)
        if curve is None or len(curve.pts) < 2:
            state.warn(
                f"{bc.source}: TLCID={bc.lcid} names the environment "
                "temperature curve, but the deck defines no such "
                "*DEFINE_CURVE (or one with fewer than two points). /CONVEC's "
                "funct_ID is MANDATORY (ERROR 120), so the record is dropped.")
            return False
        if bc.fscale == 0.0:
            # The *BOUNDARY_TEMPERATURE TMULT ambiguity again: a printed
            # default of 0. beside a curve would literally mean T_inf = 0, and
            # hm_read_convec.F:132 turns a zero FSCALE into the dimension
            # factor 1.0 anyway — so the cell would MEAN the opposite of what
            # it does. 1.0 is written and the ambiguity is named.
            state.warn(
                f"{bc.source}: TLCID={bc.lcid} names a curve but TMULT is "
                "blank/zero. TMULT is the 'environment temperature curve "
                "multiplier' with a printed default of 0. (Vol I R17 p.5-31), "
                "which literally read would impose T_inf = 0. It is resolved "
                "to FSCALE = 1.0 here: writing the literal zero would rely on "
                "hm_read_convec.F:132 ('IF (FCY == ZERO) FCY = FCY_DIM') "
                "turning it into 1.0 anyway, i.e. a cell meaning the opposite "
                "of what it does. State TMULT on the .k card if a different "
                "scale was meant.")
            bc.fscale = 1.0
        mult = bc.fscale
        # TMULT is BAKED into a copy of the curve rather than written to the
        # card — see _bc_scaled_function for the measured /PARITH/ON defect it
        # dodges (convec.F:234's cache key has no FCY_OLD, so a second card
        # sharing this curve at a different multiplier would silently reuse the
        # FIRST card's T_inf). A multiplier of exactly 1.0 needs no copy: a
        # stale 1.0 is the same 1.0, so the deck keeps its own curve id.
        bc.func_id = (bc.lcid if mult == 1.0 else
                      _bc_scaled_function(state, bc.lcid, mult, "convec_tinf"))
        minted = (None if bc.func_id == bc.lcid
                  else (bc.lcid, bc.func_id, mult))
    else:
        bc.func_id = _bc_constant_function(state, bc.fscale, "convec_tinf")
        minted = None
    bc.fscale = 1.0
    state.warn(
        f"{bc.source} -> /CONVEC with H = {bc.coef:g}, carried through with NO "
        "sign change. LS-DYNA writes the flux OUT of the surface, "
        "q'' = h(T_surface - T_inf) (Vol I R17 p.5-32 Remark 1); Radioss "
        "writes the heat IN, FLUX = AREA*H*(T_INF - TE)*dt (convec.F:152). The "
        "two expressions mirror, so a positive h means the same thing on both "
        "sides. The environment temperature is emitted inside the /FUNCT with "
        "Fscale_y = 1.0, which sidesteps an OpenRadioss defect: convec.F:234's "
        "/PARITH/ON cache key is 'IFUNC_OLD /= IFUNC .OR. TS_OLD /= TS' with "
        "no FCY_OLD in it (the /PARITH/OFF branch at convec.F:127 HAS it), so "
        "two cards sharing one T_inf curve at different Fscale_y values "
        "silently reuse the first card's T_inf — and the cache is per OMP "
        "THREAD, so the answer moves with the thread count. MEASURED on this "
        "converter's own output: 1389.1850 mJ at nt=1 and 1425.3912 at nt=6, "
        "against a correct 2381.4601 at both, at 0 ERROR / 0 WARNING / NORMAL "
        "TERMINATION."
        + ("" if minted is None else
           f" TMULT = {minted[2]:g} is therefore NOT written to the card: the "
           f"deck's *DEFINE_CURVE {minted[0]} is COPIED to a synthesized "
           f"/FUNCT/{minted[1]} with its ordinates multiplied by "
           f"{minted[2]:g}, and the /CONVEC names that copy. Both ids are in "
           "the emitted deck; the original curve is untouched."))
    return True


def _resolve_radiation(state: ConversionState, bc) -> bool:
    """*BOUNDARY_RADIATION card 2 → /RADIATION. **FMULT is not emissivity.**

    Vol I R17 p.5-117: ``FLCID``/``FMULT`` state *"the radiation heat transfer
    coefficient, f = sigma*eps*F"*, with Remark 1
    ``q'' = sigma*eps*F(T_s^4 - T_inf^4) = f(T_s^4 - T_inf^4)`` — so the
    LS-DYNA cell ALREADY CONTAINS the Stefan-Boltzmann constant. Radioss's
    ``E`` cell does not: ``hm_read_radiation.F:140-142/174`` computes
    ``SIGMA = STEFBOLTZ*FAC_T**3/FAC_M`` from the ``/BEGIN`` unit line and
    stores ``FAC(3,K) = EMI*SIGMA``. So

        E = FMULT / sigma_deck

    and writing ``FMULT`` straight through would over-scale radiation by
    1/sigma — a factor 1.76e10 on a Mg-mm-s deck. This is the single
    highest-risk cell in the batch, and it is invisible to the starter.

    The de-scaled result is a DIMENSIONLESS emissivity-times-view-factor, so
    ``E > 1`` or ``E <= 0`` means the deck's ``f`` and the emitted unit system
    disagree; both numbers are printed rather than a physically impossible
    emissivity being emitted silently.
    """
    flcid = bc.coef_lcid
    if flcid:
        state.warn(
            f"{bc.source}: FLCID={flcid} makes the radiation coefficient "
            "f = sigma*eps*F a "
            + ("function of TIME" if flcid > 0 else
               "function of the SURFACE temperature")
            + " (Vol I R17 p.5-117/118). /RADIATION's E cell is a scalar "
            "emissivity (hm_read_radiation.F:174 stores FAC(3,K) = EMI*SIGMA) "
            "and its ONE function slot already carries T_inf, so a varying f "
            "is inexpressible — the record is DROPPED. Set FLCID = 0 and "
            "state f in FMULT if a constant coefficient was meant.")
        return False
    sigma = _sigma_deck(state)
    if sigma is None:
        state.warn(
            f"{bc.source}: the emitted /BEGIN unit system "
            f"{state.units} is one this converter cannot turn into a "
            "Stefan-Boltzmann constant (unit_code.F:99-158 accepts a metric "
            "prefix plus g / m / s only). /RADIATION's E cell is a bare "
            "emissivity while LS-DYNA's FMULT is f = sigma*eps*F, so the "
            "conversion NEEDS sigma in deck units — the record is dropped "
            "rather than emitted at the wrong scale.")
        return False
    if bc.coef == 0.0:
        state.warn(
            f"{bc.source}: FLCID = 0 makes f the constant FMULT, which is "
            "blank/zero here, so the card radiates nothing (radiation.F:155 "
            "multiplies the whole flux by EMISIG). The record is dropped "
            "rather than emitted as a card that does nothing.")
        return False
    emi = bc.coef / sigma
    if emi <= 0.0 or emi > 1.0:
        state.warn(
            f"{bc.source}: FMULT = {bc.coef:g} is 'f = sigma*eps*F' (Vol I R17 "
            "p.5-117 Remark 1), so the emissivity Radioss wants is "
            f"FMULT/sigma = {emi:g} with sigma = {sigma:g} in this deck's "
            f"{state.units} unit system (hm_read_radiation.F:140-142: "
            "SIGMA = STEFBOLTZ*FAC_T**3/FAC_M). That is not a physical "
            "emissivity-times-view-factor (it must lie in (0, 1]), which means "
            "the deck's f and the emitted /BEGIN unit system disagree. The "
            "record is DROPPED rather than emitted at a scale that would be "
            "invisible to the starter — pass --units for the deck's real unit "
            "system, or check FMULT.")
        return False
    if bc.lcid < 0:
        state.warn(
            f"{bc.source}: TLCID={bc.lcid} < 0 is not a form Vol I R17 p.5-118 "
            "defines for the environment temperature (only GT.0 = a curve of "
            "time and EQ.0 = the constant TMULT). The record is dropped rather "
            "than guessed at.")
        return False
    t_inf_const = bc.fscale
    if bc.lcid:
        curve = state.curves.get(bc.lcid)
        if curve is None or len(curve.pts) < 2:
            state.warn(
                f"{bc.source}: TLCID={bc.lcid} names the environment "
                "temperature curve, but the deck defines no such "
                "*DEFINE_CURVE (or one with fewer than two points). "
                "/RADIATION's funct_ID is MANDATORY (ERROR 120), so the "
                "record is dropped.")
            return False
        if bc.fscale == 0.0:
            # The SAME named substitution _resolve_convec makes, on the same
            # grounds: it used to happen silently here, so a radiation deck's
            # reader never learned the blank cell was resolved to 1.0 rather
            # than to the literal 0 the card's printed default states.
            state.warn(
                f"{bc.source}: TLCID={bc.lcid} names a curve but TMULT is "
                "blank/zero. TMULT is the 'curve multiplier for T_inf' with a "
                "printed default of 0. (Vol I R17 p.5-123 for the _SET "
                "spelling, p.5-118 for _SEGMENT), which literally read would "
                "impose T_inf = 0. It is resolved to FSCALE = 1.0 here: "
                "writing the literal zero would rely on "
                "hm_read_radiation.F:137 ('IF (FCY == ZERO) FCY = FCY_DIM') "
                "turning it into 1.0 anyway, i.e. a cell meaning the opposite "
                "of what it does. State TMULT on the .k card if a different "
                "scale was meant. NOTE that T_inf enters radiation.F:155 to "
                "the FOURTH POWER, so a wrong scale here is not a linear "
                "error.")
            bc.fscale = 1.0
        mult = bc.fscale
        # FSCALE is BAKED into a copy of the curve rather than written to the
        # card — see _bc_scaled_function for the measured /PARITH/ON defect it
        # dodges. A multiplier of exactly 1.0 needs no copy: writing
        # Fscale_y = 1.0 already neutralises the defect (1.0 re-applied per
        # segment is still 1.0), so the deck keeps its own curve id.
        bc.func_id = (bc.lcid if mult == 1.0 else
                      _bc_scaled_function(state, bc.lcid, mult,
                                          "radiation_tinf"))
        minted = (None if bc.func_id == bc.lcid
                  else (bc.lcid, bc.func_id, mult))
        t_inf_const = None
    else:
        bc.func_id = _bc_constant_function(state, bc.fscale, "radiation_tinf")
        minted = None
    bc.fscale = 1.0
    fmult = bc.coef
    bc.coef = emi
    state.warn(
        f"{bc.source} -> /RADIATION with E = {emi:g}, which is the deck's "
        f"FMULT = {fmult:g} DIVIDED by sigma = {sigma:g}. LS-DYNA's "
        "cell is 'f = sigma*eps*F' with the Stefan-Boltzmann constant already "
        "in it (Vol I R17 p.5-117 Remark 1); Radioss's cell is a bare "
        "EMISSIVITY and the starter supplies sigma itself from the /BEGIN unit "
        f"line ({state.units}, hm_read_radiation.F:140-142). Writing FMULT "
        "straight through would over-scale the radiation by 1/sigma. The "
        "environment temperature is emitted inside the /FUNCT with "
        "Fscale_y = 1.0, which sidesteps an OpenRadioss defect: "
        "radiation.F:249 applies Fscale_y OUTSIDE its own cache guard, so "
        "under /PARITH/ON a multi-segment card with Fscale_y != 1 re-scales "
        "T_inf once per segment and reaches NaN (measured). /CONVEC gets the "
        "same treatment for a DIFFERENT flavour of the same cell: its multiply "
        "IS inside the guard (convec.F:241), so it never compounds, but "
        "FCY_OLD is missing from that guard's key (convec.F:234) and two cards "
        "sharing one curve reuse the first one's T_inf. NOTE Vol I R17 "
        "p.5-110: radiation needs an ABSOLUTE temperature scale on both sides "
        "— a deck in Celsius is wrong in LS-DYNA too."
        + ("" if t_inf_const is None else f" T_inf = {t_inf_const:g}.")
        + ("" if minted is None else
           f" TMULT = {minted[2]:g} is therefore NOT written to the card: the "
           f"deck's *DEFINE_CURVE {minted[0]} is COPIED to a synthesized "
           f"/FUNCT/{minted[1]} with its ordinates multiplied by "
           f"{minted[2]:g}, and the /RADIATION names that copy. Both ids are "
           "in the emitted deck; the original curve is untouched."))
    return True


def _emit_thermal_boundary(bc, card_id: int, surf_id: int) -> List[str]:
    """One /IMPFLUX, /CONVEC or /RADIATION card.

    Layouts audited against the ONLY FORMAT block each cfg has (all <= 2022, so
    a /BEGIN 2022 deck reads exactly these — no version-gating risk):

      radioss2018/LOADS/impflux.cfg
        /IMPFLUX/<id> / <title,%-100s>
        SURF_ID FUNCT_ID SENSOR_ID GRBRIC_ID  (%10d x4)
        ASCALE FSCALE TSTART TSTOP            (%20lf x4)
      radioss100/LOADS/convec.cfg
        /CONVEC/<id> / <title>
        SURF_ID FUNCT_ID SENSOR_ID            (%10d x3)
        ASCALE FSCALE TSTART TSTOP H          (%20lf x5)
      radioss110/LOADS/radiation.cfg — the same shape with E in place of H.

    All three carry a MANDATORY title line. ``ASCALE`` is written as 1.0
    because the starter INVERTS it (``FAC(2,K) = ONE/FCX``, all three readers)
    and the curve is already in the deck's own time; ``TSTART`` 0 and ``TSTOP``
    blank (the reader turns a blank TSTOP into 1e30), because the LS-DYNA
    cards carry no activation window of their own.
    """
    card = _BC_CARD[bc.kind]
    lines = [
        f"{card}/{card_id}",
        f"{card.lstrip('/').lower()}_{card_id}",
    ]
    if bc.kind == "FLUX":
        lines += [
            "#  SURF_ID  FUNCT_ID SENSOR_ID GRBRIC_ID",
            f"{_i(surf_id)}{_i(bc.func_id)}{_i(0)}{_i(0)}",
            "#             ASCALE              FSCALE              TSTART"
            "               TSTOP",
            f"{_f(1.0)}{_f(bc.fscale)}{_f(0.0)}{_f(0.0)}",
        ]
    else:
        tail = "H" if bc.kind == "CONVEC" else "E"
        lines += [
            "#  SURF_ID  FUNCT_ID SENSOR_ID",
            f"{_i(surf_id)}{_i(bc.func_id)}{_i(0)}",
            "#             ASCALE              FSCALE              TSTART"
            "               TSTOP" + tail.rjust(20),
            f"{_f(1.0)}{_f(bc.fscale)}{_f(0.0)}{_f(0.0)}{_f(bc.coef)}",
        ]
    lines.append(HDR)
    return lines


def _make_thermal_boundaries(state: ConversionState) -> List[str]:
    """Emit the /SURF/SEGs and the three boundary cards."""
    if not state.thermal_boundaries:
        return []
    lines: List[str] = [
        "#-  THERMAL BOUNDARY CONDITIONS (*BOUNDARY_FLUX / _CONVECTION / "
        "_RADIATION):",
        HDR,
    ]
    # ONE /SURF/SEG per *SET_SEGMENT, reused across every card that names it —
    # the blast/EBCS/contact convention (blast_ale.py:239-246). Explicit
    # _SEGMENT records get their own surface, keyed on the node tuple so two
    # identical segments still share one.
    surfs: Dict[Tuple, int] = {}
    for bc in state.thermal_boundaries:
        # Resolved in _resolve_thermal_boundaries, which already refused every
        # record whose segments could not be built.
        segs = bc.segments
        if segs is None:
            continue
        key = ("set", bc.ssid) if not any(bc.nodes) else \
            ("seg", tuple(tuple(s) for s in segs))
        surf_id = surfs.get(key)
        if surf_id is None:
            surf_id = state.next_id()
            surfs[key] = surf_id
            title = (state.segment_sets[bc.ssid].title
                     if key[0] == "set" else "")
            lines += _emit_surf_seg(
                surf_id, title or f"thermal_bc_surf_{surf_id}", segs)
        bc.surf_id = surf_id
        card_id = state.next_id()
        lines += _emit_thermal_boundary(bc, card_id, surf_id)
        state.thermal_source_emitted = True
    if len(lines) <= 2:
        return []
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Emission
# ─────────────────────────────────────────────────────────────────────────────

def _make_thermal(state: ConversionState) -> List[str]:
    """/HEAT/MAT + /THERM_STRESS/MAT + /INITEMP + /IMPTEMP + the three thermal
    boundary cards (+ their /GRNODs and /SURFs).

    The three boundary cards live INSIDE this section rather than in one of
    their own, for two reasons: they need the same ``/HEAT/MAT`` bookkeeping
    (``_resolve_thermal_boundaries`` clears them when no material arms
    ``ITHERM_FE``), and a separate section registered after ``thermal`` could
    not set ``thermal_source_emitted`` before ``_make_thermal_output`` reads it.
    """
    if not (state.heat_mat_cards or state.therm_stress_cards):
        _note_tprint(state)
        return []
    lines: List[str] = [
        "#-  THERMAL (*MAT_ADD_THERMAL_EXPANSION / *MAT_THERMAL_* / "
        "temperature drivers):",
        HDR,
    ]
    for mid in sorted(state.heat_mat_cards):
        lines += _emit_heat_mat(mid, *state.heat_mat_cards[mid])
    for mid in sorted(state.therm_stress_cards):
        lines += _emit_therm_stress(mid, *state.therm_stress_cards[mid])
    _warn_expansion_consumers(state)

    seen: Set[Tuple[int, bool]] = set()
    grnods: Dict[Tuple, int] = {}

    def _group(key: Tuple, tag: str, nodes: List[int]) -> Tuple[int, List[str]]:
        """One /GRNOD per distinct node list, reused across drivers.

        A driver over NSID = 0 carries the WHOLE node table, and a deck with
        several such drivers (07_metalstrip.k has three *INITIAL_TEMPERATURE
        rows differing only in LOC) would otherwise write the full table once
        per driver AND again for the /TH group.
        """
        gid = grnods.get(key)
        if gid is not None:
            return gid, []
        gid = state.next_grnod_id()
        grnods[key] = gid
        return gid, _emit_grnod_node(gid, f"{tag}_{gid}", nodes)

    # Rows that differ only in a cell Radioss has no slot for (LOC) state the
    # SAME /INITEMP; emitting each one writes a duplicate group and a duplicate
    # card that the later one simply overwrites.
    uniq_init: List[InitialTemperature] = []
    init_seen: Set[Tuple] = set()
    for it in state.initial_temperatures:
        k = _driver_key(it) + (it.temp,)
        if k in init_seen:
            continue
        init_seen.add(k)
        uniq_init.append(it)

    for it in uniq_init:
        label = f"*INITIAL_TEMPERATURE (set/node {it.sid})"
        # quiet on a SYNTHESIZED companion (the only kind that can carry
        # NSIDEX/BOXID): its sibling /IMPTEMP row reports the same scope one
        # loop below, and one card must not warn twice.
        nodes = _driver_nodes(state, it.sid, it.is_node, label, seen,
                              it.nsidex, it.boxid,
                              quiet=bool(it.nsidex or it.boxid),
                              drive_exempt=it.drive_exempt, nids=it.nids)
        if not nodes:
            continue
        if it.loc:
            state.warn(
                f"{label}: LOC={it.loc} names a thick-thermal-shell SURFACE; "
                "/INITEMP sets one temperature per NODE, so the "
                "through-thickness distinction is dropped.")
        gid, grp = _group(_driver_key(it), "TEMPNODES", nodes)
        tid = state.next_id()
        lines += grp
        lines += [
            f"/INITEMP/{tid}",
            f"initial_temperature_{tid}",
            "#                 T0   grnd_ID  fld_type",
            f"{_f(it.temp)}{_i(gid)}{_i(0)}",
            HDR,
        ]
        # fld_type 0 (the GROUP form) is the only usable one: fld_type = 1
        # takes a per-node list, is accepted at 0 errors and the per-node
        # temperatures are LOST (measured — every node came back at the group
        # value), so one /INITEMP per distinct temperature is emitted instead.

    for d in state.imposed_temperatures:
        label = f"{d.source} (set/node {d.sid})"
        nodes = _driver_nodes(state, d.sid, d.is_node, label, seen,
                              d.nsidex, d.boxid,
                              drive_exempt=d.drive_exempt, nids=d.nids)
        if not nodes:
            continue
        state.thermal_driver_emitted = True
        gid, grp = _group(_driver_key(d), "TEMPNODES", nodes)
        tid = state.next_id()
        lines += grp
        stop = d.tdeath if 0.0 < d.tdeath < 1.0e19 else 0.0
        lines += [
            f"/IMPTEMP/{tid}",
            f"imposed_temperature_{tid}",
            "# func_IDT sensor_ID  grnod_ID",
            f"{_i(d.func_id)}{_i(0)}{_i(gid)}",
            "#           Ascale_x            Fscale_y             T_start"
            "              T_stop",
            f"{_f(0.0)}{_f(d.scale)}{_f(d.tbirth)}{_f(stop)}",
            HDR,
        ]
        state.warn(
            f"{label} -> /IMPTEMP/{tid} over {len(nodes)} node(s), func_IDT="
            f"{d.func_id}, Fscale_y={d.scale:g}. /IMPTEMP is a HARD Dirichlet "
            "reset applied every cycle while T_start <= t <= T_stop "
            "(fixtemp.F:180-200); outside that window the nodes are untouched "
            "and simply conduct.")
    # The three heat-SOURCE cards come after the drivers, so that
    # `thermal_source_emitted` is set before _warn_inert_expansion and
    # _make_thermal_output read it.
    lines += _make_thermal_boundaries(state)
    _warn_inert_expansion(state)
    _warn_constant_driver_expansion(state)
    lines += _make_thermal_output(state, seen)
    _note_tprint(state)
    return lines


def _warn_inert_expansion(state: ConversionState) -> None:
    """The mirror of the "driver but no /HEAT/MAT" guard in ``_resolve_drivers``.

    Radioss's thermal expansion is INCREMENTAL — ``ETH = alpha(T)·(T_n −
    T_{n−1})`` — so with no temperature-moving card in the emitted deck
    ``DTEMP`` is identically zero on every cycle and the
    ``/THERM_STRESS/MAT`` does exactly nothing while the starter reports 0
    errors and echoes it happily. The pair is still WRITTEN (dropping it would
    lose the deck's own statement, and an /INITEMP-only deck is a legitimate
    restart-ready state), but it must not pass for a working expansion.

    The gate is the UNION of the two emission flags, not just ``/IMPTEMP``: a
    ``/CONVEC``, ``/RADIATION`` or ``/IMPFLUX`` moves the temperature too
    (measured), so a deck driven only by one of those has a LIVE expansion and
    must not be told its cards are inert.
    """
    if not state.therm_stress_cards or state.thermal_driver_emitted \
            or state.thermal_source_emitted:
        return
    restated = sorted(state.law1_shells_restated & set(state.therm_stress_cards))
    if restated:
        state.warn(
            f"*MAT_ELASTIC {restated} was RESTATED as /MAT/LAW36 for a thermal "
            "expansion that turns out to be INERT on this deck (no /IMPTEMP is "
            "emitted, see the next warning). The restatement is kept because "
            "the /THERM_STRESS/MAT pair is kept — both are the deck's own "
            "statement and both start working the moment a resolvable "
            "temperature driver is added — but it is not free: the restated "
            "law integrates through the thickness, which cost -4.6 % of the "
            "time step on the measured strip, and it moves the membrane stress "
            "by +0.012 % to +0.035 %. Delete the *MAT_ADD_THERMAL_EXPANSION "
            "card if the expansion is not wanted, and the material stays "
            "/MAT/LAW1.")
    state.warn(
        "/THERM_STRESS/MAT on material(s) "
        f"{sorted(state.therm_stress_cards)} is INERT on this deck: no "
        "/IMPTEMP was emitted, so no node's temperature ever changes. Radioss "
        "expansion is incremental (ETH = alpha(T)*(T_n - T_(n-1)), "
        "cmain3.F:235-240 / mmain.F90:770-786), and an /INITEMP alone is a "
        "STATE, not a driver — the field it sets is simply held. The cards are "
        "still written (they are the deck's own statement and the starter "
        "accepts them at 0 errors), but nothing expands until the deck carries "
        "a *LOAD_THERMAL_* / *BOUNDARY_TEMPERATURE whose node set k2rad can "
        "resolve, or a *BOUNDARY_FLUX / _CONVECTION / _RADIATION whose segment "
        "set it can. The temperature OUTPUT channels are left out for the same "
        "reason.")


def _warn_constant_driver_expansion(state: ConversionState) -> None:
    """A ``/THERM_STRESS/MAT`` beside drivers that NEVER MOVE.

    One level up from ``_warn_inert_expansion``: there the deck has no driver
    at all; here it has one, so the expansion is not "inert" by that test — and
    it still produces exactly zero thermal strain, because every driver is a
    CONSTANT and this writer synthesizes the companion ``/INITEMP`` at that
    same constant.

    Why the /INITEMP has to be there: ``/HEAT/MAT``'s ``T0`` cannot carry a
    starting temperature of 0 (``hm_read_therm.F:236-237`` turns a blank or
    zero into 300 K), so a driver's own t = 0 value is written as an
    ``/INITEMP``. The consequence on a constant driver is that
    ``mmain.F90:772-775`` — ``tempel0 = lbuf%temp`` (the previous step) and
    ``eth = alpha·(tempel - tempel0)`` — sees no increment, ever.

    LS-DYNA does not agree. ``*LOAD_THERMAL_CONSTANT`` and its ``_NODE`` /
    ``_ELEMENT`` spellings measure from a *"null state"* (Vol I R17 p.33-168,
    p.33-169), i.e. the structure carries ``alpha·T`` of thermal strain from a
    card that never changes. That difference is stated here rather than
    engineered around: writing the companion ``/INITEMP`` at 0 instead would
    start an absolute-temperature model at 0 K, which is wrong for every other
    consumer of the field (conduction, Johnson-Cook ``T*``, radiation), and
    changing the reference of the whole ``*LOAD_THERMAL_*`` family is a bigger
    decision than this batch's.
    """
    if not state.therm_stress_cards or not state.thermal_driver_emitted:
        return
    if state.thermal_source_emitted:
        return                       # a heat source moves the field for real
    movers = [d for d in state.imposed_temperatures if d.lcid]
    if movers:
        return
    # Every driver is a constant. It only pins the field FLAT where an
    # /INITEMP over the same scope starts those nodes at the same value —
    # which is what this writer synthesizes whenever the deck states no
    # *INITIAL_TEMPERATURE of its own. A deck that states a DIFFERENT initial
    # temperature does get one step of real expansion, so it is not warned.
    init_by_key: Dict[Tuple, Set[float]] = defaultdict(set)
    for it in state.initial_temperatures:
        init_by_key[_driver_key(it)].add(it.temp)
    for d in state.imposed_temperatures:
        if init_by_key.get(_driver_key(d)) != {d.const + d.offset}:
            return
    consts = sorted({round(d.const + d.offset, 12)
                     for d in state.imposed_temperatures})
    alphas = ", ".join(str(m) for m in sorted(state.therm_stress_cards))
    state.warn(
        f"/THERM_STRESS/MAT on material(s) {alphas} sits beside drivers that "
        "NEVER MOVE: every emitted /IMPTEMP is a constant "
        + (f"({', '.join(f'{c:g}' for c in consts[:6])}"
           + (" ..." if len(consts) > 6 else "") + ")")
        + " and its companion /INITEMP starts the same nodes at that same "
        "value, so the increment Radioss expands on is identically zero "
        "(mmain.F90:772-775: tempel0 = the PREVIOUS step's temperature, "
        "eth = alpha*(tempel - tempel0)). The converted deck therefore "
        "develops NO thermal strain from these cards, at 0 starter errors. "
        "LS-DYNA does: *LOAD_THERMAL_CONSTANT* measures from a 'null state' "
        "(Vol I R17 p.33-168/33-169), i.e. alpha*T of strain from a constant "
        "card. Radioss has no reference-temperature cell to express that — "
        "/INITEMP at 0 would start an ABSOLUTE-temperature model at 0 K and "
        "corrupt conduction, Johnson-Cook T* and radiation alike. State the "
        "temperature history the structure really goes through "
        "(*LOAD_THERMAL_VARIABLE / _LOAD_CURVE, or *BOUNDARY_TEMPERATURE with "
        "a curve) if the expansion is meant to load the model.")


def _make_thermal_output(state: ConversionState,
                         seen: Set[Tuple[int, bool]]) -> List[str]:
    """A /TH/NODE TEMP group over the driven nodes — ONLY when the deck really
    runs a thermal solve.

    The #122 rule: ``/TH ... TEMP`` on a deck with no thermal solve is accepted,
    runs clean and writes state after state of exactly 0.0, and the starter
    warns only for ``/TH/NODE`` (WARNING 1087) — never for ``/TH/BRIC``. So the
    channel is emitted only when a ``/HEAT/MAT`` AND a temperature-moving card
    both exist, i.e. when the temperature can actually change. (``/TH/SHEL``
    has no temperature variable at all — its list is DEF/STRESS/STRAIN/PLAS/
    FAILURE/F1/F2/F12/Q1/Q2 plus moments, and asking for TEMP there is
    ERROR 260.)

    **The group covers the heat-source segments too, and NOTHING new is wired
    beside it.** A ``/CONVEC``-only deck has no ``/IMPTEMP`` and so no "driven
    nodes"; without this the deck would run a real thermal solve and write no
    temperature history at all. The boundary cards' own nodes are the ones
    whose temperature the deck is about, so they go in the same group.
    ``/IMPFLUX``, ``/CONVEC`` and ``/RADIATION`` have NO ``/TH`` group of their
    own — ``hm_read_thgrou.F:1255-1256`` gives ``/TH/SURF`` exactly
    ``AREA, MASSFLOW, VELOCITY, P, A, MASS`` and there is no thermal-load
    ``/TH`` family anywhere in the starter — so there is not even a
    legal-but-zero channel to be tempted by (#122). The whole-model heat
    balance is in the engine ``.out`` instead: ``thermbilan.F:71-76`` prints
    ``** THERMAL ANALYSIS **`` with IMPOSED FLUX_DENSITY HEAT / HEAT CONVERTED
    FROM STRAIN ENERGY / CONVECTION HEAT / RADIATION HEAT / HEAT STORED once
    per printout, and that is what the validation coupons were checked against.
    """
    if not _thermal_solve_active(state):
        return []
    nodes: List[int] = []
    have: Set[int] = set()
    for d in state.imposed_temperatures:
        for n in _driver_nodes(state, d.sid, d.is_node, d.source, seen,
                               d.nsidex, d.boxid, quiet=True,
                               drive_exempt=d.drive_exempt, nids=d.nids):
            if n not in have:
                have.add(n)
                nodes.append(n)
    for bc in state.thermal_boundaries:
        if not bc.surf_id:
            continue                    # the record was dropped at emission
        for seg in (bc.segments or []):
            for n in seg:
                if n in state.nodes and n not in have:
                    have.add(n)
                    nodes.append(n)
    if not nodes:
        return []
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (nodal temperature of the driven / loaded nodes):",
        HDR,
        f"/TH/NODE/{th_id}",
        "TH_temperature",
        "      TEMP",
    ]
    lines += [_i(n) for n in nodes]
    lines.append(HDR)
    return lines


def _warn_solid_expansion(state: ConversionState, solids: List[int]) -> None:
    """The solid path: exact where the engine is stable, and the instability
    has a sharp, MEASURED trigger.

    Every number below comes from this branch's own converted decks — the same
    10-hex bar (10 x 1 x 1 mm, *MAT_ELASTIC, alpha = 1.2e-5, 20 -> 120 K over
    5 ms, closed-form free-end DX = 0.012 mm), one variable changed at a time:

      ==============================================  ==============  =========
      mount / variant                                 free-end DX     dt held?
      ==============================================  ==============  =========
      quarter symmetry at every cross-section          0.01198664 mm   yes
      end face pinned in x + 3 DOFs, nothing else     **-3.6886 mm**   NO (2e-19)
      the same end pinning + lateral anchors           0.01198628 mm   yes
      encastre end face + lateral anchors              0.01229825 mm   yes
      ONE hex, end face pinned in x + 3 DOFs           0.01198825 mm   yes
      ==============================================  ==============  =========

    So the trigger is a run of elements free to TRANSLATE laterally as a group,
    and a single lateral anchor per cross-section removes it. It is NOT:

    * the end clamp — the encastre face WITH lateral anchors is stable and
      energy-balanced (I-ENERGY 0.1315 against EXT-WORK 0.1312);
    * the thermal solve — a ``/HEAT/MAT`` with NO ``/THERM_STRESS`` on the
      diverging mount held dt for 46 000 cycles at zero energy;
    * the card — the same deck with a CONSTANT imposed temperature (DTEMP = 0)
      held dt for 45 000 cycles;
    * the load size — alpha 1.2e-9, 10 000x smaller, diverges identically;
    * the element formulation — Isolid 17 / 24 / 1, Ismstr 4 / 10 and Icpre 1
      all diverge (Isolid 12 "stabilises" only by making the expansion inert,
      DX = 0, and the starter calls it obsolete, WARNING 1160);
    * the material law — LAW1 and LAW36 solids diverge alike;
    * the mesh alone — ONE element on the diverging mount is exact.

    ``/DT/NODA/CST`` is NOT a cure either: with ``DT2MS = -1e-7`` the same deck
    stops at cycle 1000 while PRINTING **NORMAL TERMINATION**, with I-ENERGY
    3.089e5 against EXT-WORK 0.099 — the #MISTAKES "NORMAL TERMINATION is not
    success" case in its purest form.

    No card-level cure was found, so the card is emitted and the trigger is
    named. Refusing solids would be wrong: the stable mounts are exact, and
    they are the ordinary way a thermal-expansion model is set up.
    """
    state.warn(
        f"/THERM_STRESS/MAT: solid part(s) {solids} expand through the SOLID "
        "path (mmain.F90:757-786), which is EXACT where the engine is stable "
        "(measured -0.11 % on a symmetry-mounted 10-hex bar and on a single "
        "hex) but DIVERGES when a run of elements is free to TRANSLATE "
        "LATERALLY as a group. Measured on k2rad-converted twins of the same "
        "bar: with only its end face pinned the free end reached -3.6886 mm "
        "against a closed-form +0.012 mm and the time step collapsed to "
        "2e-19; adding one lateral anchor per cross-section to the SAME "
        "pinning gives 0.01198628 mm (-0.11 %) with dt held. It is not the "
        "clamp (an encastre face WITH lateral anchors is stable and balanced, "
        "I-ENERGY 0.1315 vs EXT-WORK 0.1312), not the thermal solve (a "
        "/HEAT/MAT without /THERM_STRESS held dt for 46000 cycles), not the "
        "card (a CONSTANT imposed temperature held dt), not alpha (1.2e-9 "
        "diverges identically), not Isolid/Ismstr/Icpre (17/24/1, Ismstr 4/10, "
        "Icpre 1 all diverge), not the law (LAW1 and LAW36 alike), and it "
        "needs more than one element. /DT/NODA/CST does NOT cure it: with "
        "DT2MS = -1e-7 the run stops at cycle 1000 while PRINTING NORMAL "
        "TERMINATION, I-ENERGY 3.089e5 against EXT-WORK 0.099 — so check the "
        "CYCLE COUNT, the I-ENERGY/EXT-WORK balance and the time step, never "
        "the termination banner. PRESCRIPTION: give every cross-section "
        "transverse to the expansion an anchor that holds it LATERALLY — a "
        "symmetry plane, or a support that removes BOTH transverse "
        "translations. One node restrained in only ONE transverse direction "
        "is NOT enough: measured on the same bar, one node per cross-section "
        "fixed in dy AND dz gives 0.01198565 mm (-0.12 %) with dt held, a "
        "single y = 0 symmetry plane the same, but dy ALONE still diverges "
        "(+0.389 mm, I-ENERGY 2036 against EXT-WORK 4.283) under a NORMAL "
        "TERMINATION banner. Or model the part with SHELLS on a "
        "through-thickness-integrated law, which is exact in every mount "
        "tested. Note also that the solid gate is jthe < 0 and skips t = 0 "
        "(sgrtails.F:1462 stores -ABS(JTHE) for Lagrangian solids), so nothing "
        "happens on the very first cycle.")


def _warn_expansion_consumers(state: ConversionState) -> None:
    """Name the parts whose /THERM_STRESS/MAT cannot be consumed, and the one
    element family whose behaviour needs re-checking on the user's own deck.

    Two measured facts drive this, both re-measured on this branch's own
    converted decks:

    * A ``/MAT/ELAST`` (LAW1) SHELL gets **no expansion at all** — LAW1 always
      runs global integration (``WARNING 1084 ... FORMULATION IS SWITCHED TO
      GLOBAL INTEGRATION N=0``) and ``thermexpc.F`` only reaches the
      per-integration-point stresses. Measured: 2.66e-07 mm against a
      closed-form 0.012 mm, at NIP 1 and NIP 5 alike. ``_restate_law1_shells``
      converts the ordinary case (every part on the material is a shell) to
      LAW36, so this warning is left for the MIXED case, where a material
      carries both shell and solid parts and cannot be restated.
    * On SOLIDS the physics is exact wherever the engine is stable, and the
      instability has a sharp, measured trigger: a run of elements free to
      TRANSLATE laterally as a group. See ``_warn_solid_expansion``.
    """
    if state.is_implicit and not state.therm_stress_cards \
            and (state.thermal_boundaries or state.imposed_temperatures):
        # The same guard the /THERM_STRESS arm below carries, hoisted so it is
        # reached on a deck that has a thermal BOUNDARY or driver but no
        # expansion card (that arm early-returns without one). Conditioned on
        # there being no expansion card so a deck with both is told ONCE.
        state.warn(
            "A thermal solve is armed on a deck that also carries /IMPL/* (an "
            "implicit run). The implicit engine on this build does NOT "
            "integrate the temperature. MEASURED on a twin pair of converted "
            "decks (10-brick bar, /HEAT/MAT AS = 50, an /IMPTEMP holding one "
            "end at 400 K against an /INITEMP of 300): explicit carries the "
            "far end 300 -> 399.731 -> 400.000 K, while the same .k plus a "
            "*CONTROL_IMPLICIT_GENERAL leaves it at exactly 300.000 K at every "
            "state, with HEAT STORED = 0.0000000, at 0 ERROR / 0 WARNING / "
            "NORMAL TERMINATION. THE MECHANISM, read at source: the thermal "
            "SOURCE routines are NOT skipped — resol.F:1802 (FIXTEMP), :2994 "
            "(CONVEC), :3006 (RADIATION) and :3025 (FIXFLUX) are all gated on "
            "GLOB_THERM%ITHERM_FE alone, with no IMPL_S test, so they run and "
            "fill FTHE and their own counters normally. What is dead is the "
            "ACCUMULATION: resol.F:6547, inside 'IF (IMPL_S == 1)', is a "
            "'GOTO 111' that jumps to the label at resol.F:7949, skipping the "
            "'IF (ILAG + IALE + IEULER /= 0)' block that opens at :6552 — and "
            "TEMPUR, the ONLY caller-site of the routine that does "
            "TEMP += FTHE/MCP and accumulates HEAT_STORED (tempur.F:51-58), "
            "sits inside it at :6736. SO READ THE .out PAST THE FIRST LINE: "
            "the '** THERMAL ANALYSIS **' block shows a perfectly plausible "
            "IMPOSED FLUX_DENSITY / CONVECTION / RADIATION HEAT beside a "
            "HEAT STORED of exactly 0.0000000, and only that last number "
            "reveals that nothing was integrated. The /IMPTEMP, /CONVEC, "
            "/RADIATION and /IMPFLUX cards are emitted and accepted, and the "
            "field they describe will not develop. The /ANIM/NODA/TEMP and "
            "/TH ... TEMP channels are left OUT for that reason (they would be "
            "flat), and so are the engine cards /DT/THERM and /THERM. Run the "
            "thermal phase explicitly.")
    if not state.therm_stress_cards:
        return
    from .mesh import _target_mat_law
    shell_pids = {e.pid for e in state.shell_elems} | \
                 {e.pid for e in state.tshell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    inert_law1: List[int] = []
    solids: List[int] = []
    for pid, part in sorted(state.parts.items()):
        if part.mid not in state.therm_stress_cards:
            continue
        if pid in shell_pids and _target_mat_law(state, part.mid) == 1:
            inert_law1.append(pid)
        if pid in solid_pids:
            solids.append(pid)
    if inert_law1:
        state.warn(
            f"/THERM_STRESS/MAT: shell part(s) {inert_law1} sit on a "
            "/MAT/ELAST (LAW1) material, which gets NO thermal expansion, and "
            "the material could NOT be restated as LAW36 because it also "
            "carries non-shell parts. LAW1 always runs GLOBAL integration "
            "(starter WARNING 1084 'NUMBER OF INTEGRATION POINTS IS HIGHER "
            "THAN 1 ... SWITCHED TO GLOBAL INTEGRATION N=0') and thermexpc.F "
            "only reaches the per-integration-point stresses, so there is "
            "nothing for it to correct - measured, a LAW1 shell strip expands "
            "by 2.66e-07 mm where the closed form is 0.012 mm, at NIP 1 and "
            "NIP 5 alike. The card is emitted (the material's SOLID parts DO "
            "expand) but these shells will not move. Give them their own "
            "material id, or restate them on a through-thickness-integrated "
            "law - *MAT_PIECEWISE_LINEAR_PLASTICITY (LAW36) or "
            "*MAT_PLASTIC_KINEMATIC (LAW44) with a far yield - if their "
            "expansion matters.")
    if solids:
        _warn_solid_expansion(state, solids)
    if state.is_implicit:
        state.warn(
            "/THERM_STRESS/MAT is emitted on a deck that also carries "
            "/IMPL/* (an implicit run). The implicit engine on this build does "
            "NOT integrate the temperature, so there is no DTEMP for the "
            "expansion to act on. MEASURED on a twin pair of converted decks "
            "(10-brick bar, /HEAT/MAT AS = 50, an /IMPTEMP holding one end at "
            "400 K against an /INITEMP of 300): explicit carries the far end "
            "300 -> 399.731 -> 400.000 K over 84 111 cycles, while the same .k "
            "plus a *CONTROL_IMPLICIT_GENERAL leaves it at exactly 300.000 K "
            "at every one of its 61 implicit cycles, with HEAT STORED = "
            "0.0000000, at 0 ERROR / 0 WARNING / NORMAL TERMINATION. Only the "
            "imposed nodes move (resol.F:1802 FIXTEMP is reached); nothing "
            "conducts. Run the thermal-expansion phase explicitly.")
