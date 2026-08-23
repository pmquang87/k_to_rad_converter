"""Thermal expansion and the minimal temperature-driver foothold.

  ``*MAT_ADD_THERMAL_EXPANSION``            → ``/THERM_STRESS/MAT`` + ``/HEAT/MAT``
  ``*MAT_THERMAL_ISOTROPIC`` via ``*PART`` TMID → the ``/HEAT/MAT`` values
  ``*INITIAL_TEMPERATURE_{SET,NODE}``       → ``/INITEMP`` on a ``/GRNOD``
  ``*LOAD_THERMAL_{CONSTANT,LOAD_CURVE,VARIABLE}[_NODE]`` → ``/IMPTEMP``
  ``*BOUNDARY_TEMPERATURE_{SET,NODE}``      → ``/IMPTEMP``

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

from ..state import ConversionState, Curve, InitialTemperature
from .common import HDR, _emit_grnod_node, _f, _i

__all__ = [
    "_resolve_thermal",
    "_make_thermal",
    "_thermal_solve_active",
    "_emit_heat_mat",
    "_emit_therm_stress",
]


#: ``EFRAC`` — the fraction of strain energy converted into heat. The reader
#: clamps it to (0, 1] and turns a BLANK/0 into **1.0**
#: (``hm_read_therm.F:241``), i.e. "convert all of it", which is the opposite of
#: what a structural deck driving its temperature from outside states. LS-DYNA's
#: ``*LOAD_THERMAL_*`` and ``*BOUNDARY_TEMPERATURE`` prescribe the temperature
#: field outright — no plastic-work conversion is part of that model — so the
#: cell carries the smallest positive number instead of the blank that would
#: mean 1.0. It also keeps the capacity term away from a 0/0.
_EFRAC_OFF = 1.0e-20

#: The placeholder volumetric heat capacity used when the deck states no
#: ``*MAT_THERMAL_*`` for the material. With ``AS = BS = 0`` there is no
#: conduction and with ``EFRAC = 1e-20`` no strain-energy source, so the nodal
#: heat balance has no term at all and the capacity NEVER divides anything that
#: is non-zero: any positive value gives bit-identical results. It exists only
#: so the cell is not zero — ``hm_read_therm.F:236-237`` guards its own division
#: with ``max(1e-20, RHO_CP)``, but the engine's capacity matrix does not.
_RHO_CP_PLACEHOLDER = 1.0


def _thermal_solve_active(state: ConversionState) -> bool:
    """True when the converted deck really runs a thermal solve.

    Both halves are required: a ``/HEAT/MAT`` arms ``MAT_PARAM%ITHERM``
    (``hm_read_therm.F:253``) and a driver is what makes the temperature CHANGE.
    Used to gate the temperature output channels — the #122 rule: ``/TH ... TEMP``
    without a thermal solve runs clean and writes states of exactly 0.0, and the
    starter warns only for ``/TH/NODE`` (WARNING 1087), never for ``/TH/BRIC``.
    """
    return bool(state.heat_mat_cards
                and (state.initial_temperatures or state.imposed_temperatures))


# ─────────────────────────────────────────────────────────────────────────────
# Card emitters
# ─────────────────────────────────────────────────────────────────────────────

def _emit_heat_mat(mid: int, t0: float, rho0_cp: float, a_s: float, bs: float,
                   t1: float, efrac: float) -> List[str]:
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

    ``AS``/``BS`` are the SOLID-phase conductivity ``k = AS + BS·T``;
    ``AL``/``BL`` the liquid-phase pair above ``T1``, left blank because no
    LS-DYNA thermal card in this batch states a phase change.
    """
    return [
        f"/HEAT/MAT/{mid}",
        "#                 T0             RHO0_CP                  AS"
        "                  BS",
        f"{_f(t0)}{_f(rho0_cp)}{_f(a_s)}{_f(bs)}",
        "#                 T1                  AL                  BL"
        "               EFRAC",
        f"{_f(t1)}{_f(0.0)}{_f(0.0)}{_f(efrac)}",
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
    """Every ``mid -> dataclass`` material dict a /MAT is emitted from, plus the
    per-mid /FAIL riders that must travel with a cloned material."""
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
            or mid in state.mat_transverse_aniso or mid in state.mat_hill_3r
            or mid in state.mat_aniso_visco or mid in state.mat_fabric
            or mid in state.mat_soft_tissue)


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
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION on material {mid}: LCID="
                f"{card.lcid} names no *DEFINE_CURVE in the deck (or one with "
                "fewer than two points). A Fct_ID_T the starter cannot resolve "
                "is NOT an error — hm_read_therm_stress.F90:121-128's "
                "unknown-function branch is dead code (ifunc_alpha is pre-set "
                "before the search loop), so the id would be stored raw and "
                "reinterpreted as an internal function INDEX, giving a "
                "silently wrong coefficient. No /THERM_STRESS/MAT is emitted "
                "for this material.")
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
    return fid, 0.0


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
    """The ``*MAT_THERMAL_ISOTROPIC`` a part names through ``*PART`` TMID."""
    part = state.parts.get(pid)
    if part is None or not part.tmid:
        return None
    return state.mat_thermal_isotropic.get(part.tmid)


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
    """Decide every /HEAT/MAT, /THERM_STRESS/MAT and driver in one prepass.

    Runs BEFORE ``_make_functions`` (it registers the synthesized coefficient
    and driver curves in ``state.curves``) and before ``_make_materials`` (it
    can SPLIT a material, which changes what that writer emits and what
    ``_target_mat_law`` answers).
    """
    if (state.mat_add_thermal_expansion or state.initial_temperatures
            or state.imposed_temperatures or state.mat_thermal_isotropic):
        _resolve_expansion(state)
        _resolve_heat_materials(state)
        _resolve_drivers(state)
    _note_tprint(state)


def _note_tprint(state: ConversionState) -> None:
    """*DATABASE_TPRINT — the thermal ASCII database. Answered here, not at
    parse time, because the answer depends on whether the CONVERTED deck ends up
    with a thermal solve, which only this prepass knows.

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
            "a temperature driver), so the nodal temperature IS written - "
            "/ANIM/NODA/TEMP in the engine deck and a /TH/NODE TEMP group over "
            "the driven nodes. Its dt is deliberately NOT folded into the "
            "/TFILE minimum: the TEMP channel rides the groups already there "
            "rather than pacing one of its own.")
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
        "*MAT_ADD_THERMAL_EXPANSION or *MAT_THERMAL_ISOTROPIC + *PART TMID, "
        "plus a *LOAD_THERMAL_* / *BOUNDARY_TEMPERATURE / *INITIAL_TEMPERATURE "
        "driver, and the channel appears.")


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
    mids_with_groups: Dict[int, int] = defaultdict(int)
    for (mid, _k, _t) in groups:
        mids_with_groups[mid] += 1

    for (mid, _key, _tmid), pids in sorted(
            groups.items(), key=lambda kv: (kv[0][0], min(kv[1]))):
        # Refuse BEFORE the split: a clone made for a material that then gets no
        # thermal card at all is a pointless duplicate /MAT in the deck.
        if _refuse_law109(state, mid, pids):
            continue
        card = by_pid[pids[0]]
        all_pids = sorted(p for p, q in state.parts.items() if q.mid == mid)
        target = mid
        if mids_with_groups[mid] > 1 or set(pids) != set(all_pids):
            clone = _clone_material(state, mid)
            if clone is None:
                state.warn(
                    f"*MAT_ADD_THERMAL_EXPANSION on part(s) {pids}: material "
                    f"{mid} is not converted to any /MAT, so it cannot be "
                    "split off for the expansion — card dropped.")
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
                f"has the expansion, and mid {mid} keeps the parts the deck did "
                "not name. dyna2rad instead expands every part on the shared "
                "material (convertmats.cxx:12236 resolves PID to the part's MID "
                "and stops there).")
            target = clone
        func_id, fscale = _resolve_alpha_function(state, target, card)
        if func_id == 0:
            continue
        _warn_orthotropic_slots(state, target, card)
        state.therm_stress_cards[target] = (func_id, fscale)

    for mid, card in sorted(direct.items()):
        if _refuse_law109(state, mid, None):
            continue
        if not any(p.mid == mid for p in state.parts.values()):
            state.warn(
                f"*MAT_ADD_THERMAL_EXPANSION: ID=-{mid} names a material no "
                "*PART uses — card dropped.")
            continue
        func_id, fscale = _resolve_alpha_function(state, mid, card)
        if func_id == 0:
            continue
        _warn_orthotropic_slots(state, mid, card)
        state.therm_stress_cards[mid] = (func_id, fscale)


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
        if d.sid or d.is_node:
            continue                    # not a model-wide driver
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
            "shape of a THERMAL-ONLY LS-DYNA deck (*CONTROL_SOLUTION SOLN=1), "
            "which Radioss has no run mode for; give the parts a structural "
            "*MAT_* as well if they need thermal properties.")
    if not wanted:
        return

    t0_global = _global_initial_temperature(state)
    refused: List[int] = []
    for mid in sorted(wanted):
        if mid in state.mat_tabulated_jc:
            # The *MAT_ADD_THERMAL_EXPANSION route already refused (and named)
            # this in _resolve_expansion; this catches the other way in - a
            # *PART TMID naming a *MAT_THERMAL_* on a LAW109 part.
            refused.append(mid)
            state.therm_stress_cards.pop(mid, None)
            continue
        tm = None
        for pid, part in state.parts.items():
            if part.mid == mid:
                tm = _thermal_material_for_part(state, pid) or tm
        rho = _structural_density(state, mid)
        if tm is not None:
            rho_cp = (tm.tro or rho) * tm.hc
            a_s = tm.tc
            dropped = [n for n, v in (("TGRLC", tm.tgrlc), ("TGMULT", tm.tgmult),
                                      ("TLAT", tm.tlat), ("HLAT", tm.hlat))
                       if v]
            if dropped:
                state.warn(
                    f"*MAT_THERMAL_ISOTROPIC {tm.tmid} -> /HEAT/MAT/{mid}: "
                    + ", ".join(dropped) + " dropped. /HEAT/MAT has no "
                    "volumetric heat-generation slot and no latent-heat slot "
                    "(its T1/AL/BL cells are a phase-change CONDUCTIVITY pair, "
                    "not a latent heat).")
            if rho_cp <= 0.0:
                state.warn(
                    f"*MAT_THERMAL_ISOTROPIC {tm.tmid} -> /HEAT/MAT/{mid}: the "
                    f"volumetric capacity (TRO or RO) x HC is {rho_cp:g}. HC is "
                    "the specific heat per unit MASS in LS-DYNA and RHO0_CP is "
                    "per unit VOLUME in Radioss (hm_read_therm.F:244 stores it "
                    "in PM(69), the same slot LAW2's adiabatic heating reads), "
                    "so a blank HC or a blank density leaves the material with "
                    "no capacity at all.")
                rho_cp = _RHO_CP_PLACEHOLDER
        else:
            rho_cp = _RHO_CP_PLACEHOLDER
            a_s = 0.0
            state.warn(
                f"/HEAT/MAT/{mid}: no *MAT_THERMAL_* is bound to this material "
                "(no *PART TMID names one), so its CONDUCTIVITY is unknown and "
                "AS = BS = 0 is written: heat does NOT flow between nodes. That "
                "is faithful for a structural-only deck whose temperatures are "
                "all prescribed by *LOAD_THERMAL_* or *BOUNDARY_TEMPERATURE — "
                "the thermal expansion then reads exactly the field the deck "
                "states — but any node NOT covered by a driver keeps its "
                f"initial temperature forever. RHO0_CP = {_RHO_CP_PLACEHOLDER:g} "
                "is a placeholder: with no conduction and no strain-energy "
                "source the nodal heat balance has no term, so its value cannot "
                "change any result. Add *MAT_THERMAL_ISOTROPIC + *PART TMID if "
                "the model needs real conduction.")
        t1 = _law_melt_temperature(state, mid)
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
                "WILL BE USED'). The law's adiabatic plastic-work heating now "
                "uses the /HEAT/MAT value.")
        state.heat_mat_cards[mid] = (
            t0_global if t0_global is not None else 0.0,
            rho_cp, a_s, 0.0, t1, _EFRAC_OFF)

    if refused:
        state.warn(
            f"/HEAT/MAT: material(s) {refused} are *MAT_TABULATED_JOHNSON_COOK "
            "(/MAT/LAW109), which integrate their OWN element temperature from "
            "plastic work. A /HEAT/MAT would switch LAW109 to the "
            "imposed-temperature path and kill that self-heating "
            "(sigeps109.F:411-414), so none is written even though a *PART TMID "
            "names a *MAT_THERMAL_* for them - the thermal properties are "
            "DROPPED rather than the law's own physics.")


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

def _driver_nodes(state: ConversionState, sid: int, is_node: bool,
                  label: str, seen: Optional[Set[Tuple[int, bool]]] = None
                  ) -> List[int]:
    """The node ids one driver applies to.

    ``sid = 0`` on a set-based card means EVERY node in the model (Vol I R17,
    ``*INITIAL_TEMPERATURE_SET``: *"NSID = 0 ... all nodes"*; the
    ``*LOAD_THERMAL_*`` cards default the same way).

    *seen* de-duplicates the "set is not defined" warning: the emitter asks for
    the same driver twice (once for the /IMPTEMP, once for the /TH/NODE TEMP
    group) and one missing set must not be reported twice.
    """
    if is_node:
        return [sid] if sid in state.nodes else []
    if sid == 0:
        return sorted(state.nodes)
    ns = state.node_sets.get(sid)
    if ns is None:
        if seen is None or (sid, is_node) not in seen:
            state.warn(
                f"{label}: *SET_NODE {sid} is not defined in the converted "
                "deck, so there is no /GRNOD to impose the temperature on — "
                "card dropped. (A *SET_NODE_GENERAL or *SET_NODE_COLUMN the "
                "converter does not read leaves exactly this hole.)")
        if seen is not None:
            seen.add((sid, is_node))
        return []
    nodes = ns[1] if isinstance(ns, tuple) else ns
    return [n for n in nodes if n in state.nodes]


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
            if d.offset:
                # T = TB + TS*f(t) (Vol I R17, *LOAD_THERMAL_VARIABLE Remark 1).
                # /IMPTEMP computes Fscale_y*f((t-T_start)/Ascale_x) only
                # (fixtemp.F:180-200) — there is no additive slot — so the
                # offset is baked into a synthesized copy of the curve.
                fid = state.next_curve_id()
                state.curves[fid] = Curve(
                    lcid=fid, title=f"Auto_imptemp_{fid}",
                    sfa=1.0, sfo=1.0, offa=0.0, offo=0.0,
                    pts=[(x, d.offset + d.scale * y) for x, y in curve.pts])
                state.curve_order.append(fid)
                d.func_id = fid
                d.scale = 1.0
                d.initial_temp = d.offset + d.scale * curve.pts[0][1]
            else:
                d.func_id = d.lcid
                d.initial_temp = d.scale * curve.pts[0][1]
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
            state.initial_temperatures.append(InitialTemperature(
                sid=d.sid, temp=d.initial_temp, is_node=d.is_node))


# ─────────────────────────────────────────────────────────────────────────────
# Emission
# ─────────────────────────────────────────────────────────────────────────────

def _make_thermal(state: ConversionState) -> List[str]:
    """/HEAT/MAT + /THERM_STRESS/MAT + /INITEMP + /IMPTEMP (+ their /GRNODs)."""
    if not (state.heat_mat_cards or state.therm_stress_cards):
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
    for it in state.initial_temperatures:
        label = f"*INITIAL_TEMPERATURE (set/node {it.sid})"
        nodes = _driver_nodes(state, it.sid, it.is_node, label, seen)
        if not nodes:
            continue
        if it.loc:
            state.warn(
                f"{label}: LOC={it.loc} names a thick-thermal-shell SURFACE; "
                "/INITEMP sets one temperature per NODE, so the "
                "through-thickness distinction is dropped.")
        gid = state.next_grnod_id()
        tid = state.next_id()
        lines += _emit_grnod_node(gid, f"INITEMP_{tid}", nodes)
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
        nodes = _driver_nodes(state, d.sid, d.is_node, label, seen)
        if not nodes:
            continue
        gid = state.next_grnod_id()
        tid = state.next_id()
        lines += _emit_grnod_node(gid, f"IMPTEMP_{tid}", nodes)
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
    lines += _make_thermal_output(state, seen)
    return lines


def _make_thermal_output(state: ConversionState,
                         seen: Set[Tuple[int, bool]]) -> List[str]:
    """A /TH/NODE TEMP group over the driven nodes — ONLY when the deck really
    runs a thermal solve.

    The #122 rule: ``/TH ... TEMP`` on a deck with no thermal solve is accepted,
    runs clean and writes state after state of exactly 0.0, and the starter
    warns only for ``/TH/NODE`` (WARNING 1087) — never for ``/TH/BRIC``. So the
    channel is emitted only when a ``/HEAT/MAT`` AND a driver both exist, i.e.
    when the temperature can actually change. (``/TH/SHEL`` has no temperature
    variable at all — its list is DEF/STRESS/STRAIN/PLAS/FAILURE/F1/F2/F12/
    Q1/Q2 plus moments, and asking for TEMP there is ERROR 260.)
    """
    if not _thermal_solve_active(state):
        return []
    nodes: List[int] = []
    have: Set[int] = set()
    for d in state.imposed_temperatures:
        for n in _driver_nodes(state, d.sid, d.is_node, d.source, seen):
            if n not in have:
                have.add(n)
                nodes.append(n)
    if not nodes:
        for it in state.initial_temperatures:
            for n in _driver_nodes(state, it.sid, it.is_node,
                                   "*INITIAL_TEMPERATURE", seen):
                if n not in have:
                    have.add(n)
                    nodes.append(n)
    if not nodes:
        return []
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (nodal temperature of the driven nodes):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_temperature",
        "      TEMP",
    ]
    lines += [_i(n) for n in nodes]
    lines.append(HDR)
    return lines


def _warn_expansion_consumers(state: ConversionState) -> None:
    """Name the parts whose /THERM_STRESS/MAT cannot be consumed, and the one
    element family whose behaviour needs re-checking on the user's own deck.

    Two measured facts drive this:

    * A ``/MAT/ELAST`` (LAW1) SHELL gets **no expansion at all**. LAW1 always
      runs global integration (``WARNING 1084 ... FORMULATION IS SWITCHED TO
      GLOBAL INTEGRATION N=0``) and ``thermexpc.F``'s ``IORTH == 0`` branch then
      builds its thermal force from ``A1 + A2``, which are zero there. Measured
      on both QEPH and QBAT: ``F1 ~ -0.02 ~ 0`` against ``-257.95`` for the same
      deck on LAW2. A LAW2 shell explicitly forced to ``N = 0`` is converted BACK
      to NPT = 3 by ``WARNING 1912`` and works.
    * On SOLIDS the physics is exact under symmetry mounts (measured -0.12 % on a
      free cube, -0.16 % on a free bar and -0.14 % on a fully restrained one)
      but a face-clamped, laterally free bar produced a spurious stress of about
      11 GPa that is INDEPENDENT of both dT and alpha (11457 / 11064 / 11150 MPa
      for dT = 0.001 / 1 / 100 K; identical at alpha = 1.2e-9 and 1.2e-5). The
      dT-independence proves it is not a stiff-but-real response. The mechanism
      was not isolated, so the card is emitted and the risk is named.
    """
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
            "/MAT/ELAST (LAW1) material, which gets NO thermal expansion. LAW1 "
            "always runs GLOBAL integration (starter WARNING 1084 'NUMBER OF "
            "INTEGRATION POINTS IS HIGHER THAN 1 ... SWITCHED TO GLOBAL "
            "INTEGRATION N=0') and thermexpc.F's isotropic branch builds its "
            "thermal force from A1 + A2, which are zero in that path — measured "
            "on both QEPH and QBAT shells: the clamped reaction was -0.02 "
            "against -257.95 for the identical deck on /MAT/LAW2. The card is "
            "emitted (a mixed deck's solid and multi-integration-point shell "
            "parts DO expand) but these parts will not move. Restate them on a "
            "through-thickness-integrated law - *MAT_PIECEWISE_LINEAR_"
            "PLASTICITY (LAW36) or *MAT_PLASTIC_KINEMATIC (LAW44) with an "
            "elastic yield - if their expansion matters.")
    if solids:
        state.warn(
            f"/THERM_STRESS/MAT: solid part(s) {solids} expand through the "
            "SOLID path (mmain.F90:757-786), which is exact under symmetry "
            "mounts - measured -0.12 % on a free cube, -0.16 % on a free bar "
            "and -0.14 % on a fully restrained one against the closed-form "
            "alpha*dT - but WRONG when the bar is clamped over a whole face "
            "with a laterally free interior. Measured on a k2rad-converted "
            "deck, a 10-hex bar at alpha = 1.2e-5 and dT = 100 K gave a free-end "
            "DX of -0.4190 mm where +0.012 mm is the closed form: wrong sign, "
            "35x the magnitude. The same mount produces a spurious stress of "
            "about 11 GPa that is INDEPENDENT of both dT (11457 / 11064 / "
            "11150 MPa at dT = 0.001 / 1 / 100 K) and alpha, which rules out a "
            "stiff-but-real response; swapping the face clamp for symmetry "
            "planes on the SAME deck restores the exact answer (0.011984 mm, "
            "-0.13 %). The mechanism was not isolated, so check the mount and "
            "the first states of your own run before trusting solid thermal "
            "stresses. Shells with a multi-integration-point law are robust in "
            "both mounts. Note also "
            "that the solid gate is jthe < 0 and skips t = 0 "
            "(sgrtails.F:1462 stores -ABS(JTHE) for Lagrangian solids), so "
            "nothing happens on the very first cycle.")
    if state.is_implicit:
        state.warn(
            "/THERM_STRESS/MAT is emitted on a deck that also carries "
            "/IMPL/* (an implicit run). The implicit engine on this build has "
            "NO thermal solve at all: FIXTEMP, TEMPUR, CONVEC, RADIATION and "
            "THERMBILAN are all called from the EXPLICIT integration loop in "
            "resol.F and none is reached from imp_solv (grep ITHERM over "
            "engine/source/implicit returns nothing). The thermal expansion "
            "will therefore not act. Run the thermal-expansion phase "
            "explicitly.")
