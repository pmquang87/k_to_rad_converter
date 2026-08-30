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

from ..state import ConversionState, Curve, InitialTemperature, MatPlasTAB
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
#: ``AS = BS = 0`` there is no conduction and with ``EFRAC = 1e-20`` no
#: strain-energy source, so the nodal heat balance has no term at all and the
#: capacity NEVER divides anything that is non-zero. It exists only so the cell
#: is not zero — ``hm_read_therm.F:236-237`` guards its own division with
#: ``max(1e-20, RHO_CP)``, but the engine's capacity matrix does not.
_RHO_CP_PLACEHOLDER = 1.0


def _thermal_solve_active(state: ConversionState) -> bool:
    """True when the converted deck really MAKES A TEMPERATURE CHANGE.

    Both halves are required, and both are read from what was actually
    EMITTED, never from what was parsed:

    * a ``/HEAT/MAT`` arms ``MAT_PARAM%ITHERM`` (``hm_read_therm.F:253``);
    * ``state.thermal_driver_emitted`` is set at the line that writes an
      ``/IMPTEMP``, i.e. after ``_driver_nodes`` has resolved the set. Several
      corpus decks state a driver whose ``*SET_NODE_GENERAL`` /
      ``*SET_NODE_LIST_GENERATE`` k2rad does not read, so the driver is dropped
      at emission — reading the PARSED list here would call those decks
      "thermal" and ship a frozen fringe.

    An ``/INITEMP`` alone is deliberately NOT enough: it is a STATE, not a
    driver. A uniform initial temperature with nothing to change it leaves
    ``DTEMP`` identically zero on every cycle, so the /THERM_STRESS does
    nothing and the TEMP channel is a flat line — the #122 case exactly.
    """
    return bool(state.heat_mat_cards and state.thermal_driver_emitted)


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
            # The mechanical law's own volumetric rhoC_p beats the placeholder
            # whenever it has one: with the local adiabatic branch switched off
            # (see _warn_law2_self_heating) the FE thermal path is what paces
            # any heat that does appear, and it divides by exactly this cell.
            rho_cp = _law_own_rho_cp(state, mid) or _RHO_CP_PLACEHOLDER
            a_s = 0.0
            state.warn(
                f"/HEAT/MAT/{mid}: no *MAT_THERMAL_* is bound to this material "
                "(no *PART TMID names one), so its CONDUCTIVITY is unknown and "
                "AS = BS = 0 is written: heat does NOT flow between nodes. That "
                "is faithful for a structural-only deck whose temperatures are "
                "all prescribed by *LOAD_THERMAL_* or *BOUNDARY_TEMPERATURE — "
                "the thermal expansion then reads exactly the field the deck "
                "states — but any node NOT covered by a driver keeps its "
                f"initial temperature forever. RHO0_CP = {rho_cp:g} is "
                + ("the mechanical law's own volumetric rhoC_p."
                   if rho_cp != _RHO_CP_PLACEHOLDER else
                   "a placeholder: with no conduction and no strain-energy "
                   "source (EFRAC = 1e-20 scales the nodal source term at "
                   "cmain3.F:360) the nodal heat balance has no term, so its "
                   "value cannot change any result.")
                + " Add *MAT_THERMAL_ISOTROPIC + *PART TMID if the model needs "
                "real conduction.")
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
                "WILL BE USED'). It is the FE thermal solve's nodal capacity "
                "from here on; the law's own value is no longer used for "
                "anything, because its local adiabatic branch is switched off "
                "by the presence of the /HEAT/MAT.")
        _warn_law2_self_heating(state, mid)
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
    ``DIE`` (``cmain3.F:360``) rather than the law's own ``FHEAT`` — and
    ``EFRAC`` is deliberately written at 1e-20 here, because
    ``*MAT_ADD_THERMAL_EXPANSION`` states nothing about heat generation.

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
    state.warn(
        f"/HEAT/MAT/{mid} on a *MAT_015-derived law (/MAT/LAW2 or LAW4): the "
        "law's OWN adiabatic plastic-work heating is switched OFF by the "
        "presence of a thermal solve. sigeps02c.F:220 (shells) and "
        "m2law.F:547 (solids) read 'IF (JTHE /= 0) ... ELSEIF (RHOCP > ZERO) "
        "TEMPEL += SIGY*DPLA/RHOCP', so the local branch is skipped as soon as "
        "the material has a /HEAT/MAT. What replaces it is the FE thermal "
        "path, whose nodal source is EFRAC-scaled (cmain3.F:360, PM(90) = "
        "EFRAC) and EFRAC is written at 1e-20 because "
        "*MAT_ADD_THERMAL_EXPANSION / *MAT_THERMAL_ISOTROPIC state nothing "
        "about heat generation. Net effect: the element temperature now "
        "follows ONLY the prescribed *LOAD_THERMAL_* / *BOUNDARY_TEMPERATURE "
        "field, and the Johnson-Cook thermal softening no longer develops from "
        "plastic work. If the run needs adiabatic self-heating, drop the "
        "thermal card from THIS part (the material can be split by giving the "
        "part its own *MAT_015).")


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
                  label: str, seen: Optional[Set[Tuple[int, bool]]] = None,
                  nsidex: int = 0, boxid: int = 0,
                  quiet: bool = False,
                  drive_exempt: bool = False) -> List[int]:
    """The node ids one driver applies to.

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
                drive_exempt=d.drive_exempt))


# ─────────────────────────────────────────────────────────────────────────────
# Emission
# ─────────────────────────────────────────────────────────────────────────────

def _make_thermal(state: ConversionState) -> List[str]:
    """/HEAT/MAT + /THERM_STRESS/MAT + /INITEMP + /IMPTEMP (+ their /GRNODs)."""
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
        k = (it.sid, it.is_node, it.temp, it.nsidex, it.boxid, it.drive_exempt)
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
                              drive_exempt=it.drive_exempt)
        if not nodes:
            continue
        if it.loc:
            state.warn(
                f"{label}: LOC={it.loc} names a thick-thermal-shell SURFACE; "
                "/INITEMP sets one temperature per NODE, so the "
                "through-thickness distinction is dropped.")
        gid, grp = _group((it.sid, it.is_node, it.nsidex, it.boxid,
                           it.drive_exempt), "TEMPNODES", nodes)
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
                              drive_exempt=d.drive_exempt)
        if not nodes:
            continue
        state.thermal_driver_emitted = True
        gid, grp = _group((d.sid, d.is_node, d.nsidex, d.boxid,
                           d.drive_exempt), "TEMPNODES", nodes)
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
    _warn_inert_expansion(state)
    lines += _make_thermal_output(state, seen)
    _note_tprint(state)
    return lines


def _warn_inert_expansion(state: ConversionState) -> None:
    """The mirror of the "driver but no /HEAT/MAT" guard in ``_resolve_drivers``.

    Radioss's thermal expansion is INCREMENTAL — ``ETH = alpha(T)·(T_n −
    T_{n−1})`` — so with no ``/IMPTEMP`` in the emitted deck ``DTEMP`` is
    identically zero on every cycle and the ``/THERM_STRESS/MAT`` does exactly
    nothing while the starter reports 0 errors and echoes it happily. The pair
    is still WRITTEN (dropping it would lose the deck's own statement, and an
    /INITEMP-only deck is a legitimate restart-ready state), but it must not
    pass for a working expansion.
    """
    if not state.therm_stress_cards or state.thermal_driver_emitted:
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
        "a *LOAD_THERMAL_* or *BOUNDARY_TEMPERATURE whose node set k2rad can "
        "resolve. The temperature OUTPUT channels are left out for the same "
        "reason.")


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
        for n in _driver_nodes(state, d.sid, d.is_node, d.source, seen,
                               d.nsidex, d.boxid, quiet=True,
                               drive_exempt=d.drive_exempt):
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
            "/IMPL/* (an implicit run). The implicit engine on this build has "
            "NO thermal solve at all: FIXTEMP, TEMPUR, CONVEC, RADIATION and "
            "THERMBILAN are all called from the EXPLICIT integration loop in "
            "resol.F and none is reached from imp_solv (grep ITHERM over "
            "engine/source/implicit returns nothing). The thermal expansion "
            "will therefore not act. Run the thermal-expansion phase "
            "explicitly.")
