"""Integrated beams: ``*INTEGRATION_BEAM`` -> ``/PROP/TYPE18`` (INT_BEAM).

A ``*SECTION_BEAM`` whose card-1 QR/IRID field is negative hands its quadrature
to a user ``*INTEGRATION_BEAM`` rule. The rule comes in two flavours, and this
module turns each into the Radioss property that can carry it:

  ``ICST = 0``  the rule IS the section: NIP cells of ``S T WF PID``, which
                become /PROP/TYPE18 ``Isect=0`` plus one ``Yi Zi AREA`` card per
                cell, denormalized with the section's own ``TS1``/``TT1``
                thicknesses and the rule's relative area ``RA``.
  ``ICST > 0``  one of LS-DYNA's 22 standard shapes, which lines up 1:1 with
                Radioss's own predefined sections at ``Isect = ICST + 9`` — but
                only the shapes needing at most TWO dimensions can be emitted at
                the ``/BEGIN 2022`` this converter writes (see
                ``_ICST_TO_ISECT`` below). The rest are reported and fall back.

Neither path exists in dyna2rad: ``INTEGRATION_BEAM`` is commented out of the
R14.1 data hierarchy so the native reader drops the card without a message
(``data_hierarchy.cfg:4244-4253``), and the ``*SECTION_BEAM`` branch that would
consume a rule is an empty stub awaiting "RD-6730"
(``convertprops.cxx:1343-1347``). Everything here is net-new capability, and the
one piece of dyna2rad arithmetic worth mirroring — its ``*INTEGRATION_SHELL``
``S``/``WF`` -> position/weight-share math (``convertprops.cxx:2015-2016``) — is
mirrored with the point-count guard Altair's shell code lacks.

Kept out of ``writer/composites.py`` (whose scope is the orthotropic/composite
laws and the per-ply shell layup) and out of ``writer/mesh.py`` (already the
largest writer module) for the same reason ``joints.py`` is its own module.
"""

from __future__ import annotations

import math
from typing import Dict, List, Set, Tuple

from ..state import (
    ConversionState,
    IntBeamProp,
    IntegrationBeam,
    SectionBeam,
)
from .common import HDR, _f, _i, _spotweld_beam_pids

__all__ = [
    "_resolve_integration_beams",
    "_emit_prop_int_beam",
    "_constants_from_thicknesses",
]


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# /PROP/TYPE18 hard limits, both CHECK-block constraints on the Radioss side
# (prop_p18_int_beam.cfg:85-91) and both enforced by the starter:
# hm_read_prop18.F:257 raises ERROR 977 above 100 points, and :169 ERROR 314 on
# a non-positive sub-area.
_MAX_IP = 100

# *SECTION_BEAM ELFORM values whose card 2 is a pair of s/t THICKNESSES and
# which therefore integrate a real cross-section — the only ones a
# *INTEGRATION_BEAM rule can drive. dyna2rad reaches a rule-aware path for 1 and
# 4 only (convertprops.cxx:1250) and drops 5 and 11 with no message at all
# (they have no switch case and there is no `default:`), even though both are
# rule-bearing in LS-DYNA. ELFORM 0 is the CFG's accepted alias of 1.
_INTEGRATED_ELFORMS = frozenset({0, 1, 4, 5, 11})

# LS-DYNA *INTEGRATION_BEAM ICST -> (Radioss Isect, number of dimensions the
# shape needs, the shape's own max NITRS). The map is exact and 1:1 with a
# constant offset of 9: ICST 1..22 (Vol I R17 p.29-2) against Isect 10..31
# (starter defbeam_sect_new.F90, whose `case` blocks name each shape and set
# nb_dim / intr_max). The dimension counts agree with LS-DYNA's OWN
# *SECTION_BEAM `SECTION_nn` card-2b field counts on every row, which is an
# independent cross-check of the alignment.
_ICST_TO_ISECT: Dict[int, Tuple[int, int, int]] = {
    1:  (10, 4, 15),   # I-shape
    2:  (11, 4, 30),   # channel
    3:  (12, 4, 47),   # L-shape
    4:  (13, 4, 22),   # T-shape
    5:  (14, 4, 23),   # tubular box
    6:  (15, 4, 30),   # Z-shape
    7:  (16, 3, 7),    # trapezoidal
    8:  (17, 1, 2),    # circular      (solid, L1 = radius)
    9:  (18, 2, 2),    # tubular       (L1 = outer radius, L2 = inner)
    10: (19, 6, 15),   # I-shape 2
    11: (20, 2, 7),    # solid box     (L1 x L2)
    12: (21, 4, 8),    # cross
    13: (22, 4, 14),   # H-shape
    14: (23, 4, 8),    # T-shape 2
    15: (24, 4, 10),   # I-shape 3
    16: (25, 4, 22),   # channel 2
    17: (26, 4, 15),   # channel 3
    18: (27, 4, 11),   # T-shape 3
    19: (28, 6, 23),   # box-shape 2
    20: (29, 3, 4),    # hexagon
    21: (30, 4, 8),    # hat
    22: (31, 6, 5),    # hat 2
}

# How many predefined-section sizes a /BEGIN 2022 deck can actually carry.
# k2rad writes /BEGIN 2022, and the CFG that supplies the TYPE18 card layout is
# resolved DOWNWARD from the requested version (cfg_kernel.cpp:266,
# GetVerDirForGvnVersion does `vers.substr(found)`), so the radioss2024 copy is
# invisible and the first hit is radioss120 — which declares L1 and L2 and
# NOTHING else (prop_p18_int_beam.cfg:33-34). Writing L3..L6 there earns
# WARNING 100213 "unsupported field exists at the end of line" and then ERROR
# 3059 MISSING DIMENSIONS FOR PREDEFINED SECTION, because the starter still
# checks all nb_dim of them (hm_read_prop18.F:224-232). Verified against the
# real starter with two decks differing only in /BEGIN: 2022 fails, 2026 reads
# L3/L4 and generates the section. So a shape is emitted only when it fits in
# two dimensions; the rest are reported and fall back.
_MAX_PREDEFINED_DIMS = 2


# ─────────────────────────────────────────────────────────────────────────────
# The material gate
# ─────────────────────────────────────────────────────────────────────────────

def _type18_material(state: ConversionState, mid: int) -> bool:
    """Does the /MAT law this *MAT id converts to accept a /PROP/TYPE18?

    The gate is on the material, not the property: ``PROP_BEAM`` is 1
    BEAM_CLASSIC (TYPE3 only), 2 BEAM_INTEGRATED (TYPE18 only) or 3 BEAM_ALL,
    and ``check_mat_elem_prop_compatibility.F:239-241`` rejects TYPE18 for
    anything that is not 2 or 3 with ERROR 3047 followed by ERROR 745. Grepping
    ``INIT_MAT_KEYWORD`` gives the whole list: LAW0/2/13/44 are BEAM_ALL,
    LAW34/36/71 are BEAM_INTEGRATED, LAW1 (``/MAT/ELAST``) is BEAM_CLASSIC, and
    every other law declares nothing at all and so fails BOTH beam properties.

    This is a WHITELIST of the k2rad material families whose law is known to be
    on that list. An unrecognized material keeps today's /PROP/BEAM rather than
    being promoted into a starter error.
    """
    if mid in state.mat_plas_tab:            # LAW36  PLAS_TAB
        return True
    if mid in state.mat_power_law:           # LAW36  PLAS_TAB (power-law fit)
        return True
    if mid in state.mat_plas_kin:            # LAW44  COWPER
        return True
    if mid in state.mat_johnson_cook:
        # /MAT/LAW2 (PLAS_JOHNS) is BEAM_ALL; the EOS-attached /MAT/LAW4
        # (HYD_JCOOK) route declares no beam keyword at all.
        return not state.mat_johnson_cook[mid].use_law4
    # /MAT/VOID (LAW0) is BEAM_ALL too, but *MAT_NULL only reaches it when it
    # carries no *EOS_* — with one it becomes the hydrodynamic /MAT/LAW6, which
    # declares nothing. A null BEAM is a contact/visualization stub either way,
    # so it is left off the whitelist rather than routed on that condition.
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Section-constant derivation (the /PROP/BEAM fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _constants_from_points(points: List[Tuple[float, float, float]]):
    """(Area, Iyy, Izz, Ixx) of a cross-section given as (y, z, area) cells.

    ``Iyy`` IS THE Z-BASED SUM. Radioss's /PROP/BEAM Iyy is the second moment
    ABOUT the local y-axis, i.e. ``INT z^2 dA`` — the standard sense — and the
    ENGINE is the ground truth for it, not the starter's listing::

        TYPE3   m1lawp.F:108        MOM(2) = KYY * YM * B1,  B1 = GEO(2) = Iyy
        TYPE18  mulaw_ib.F:139      DEPSXX = EXX - YPT*KZZ + ZPT*KYY
                main_beam18.F:253   MOM(2) = SUM(DFXX*ZPT)

    A curvature KYY on an integrated beam therefore develops
    ``MOM(2) = E*KYY*SUM(A_i*z_i^2)``, and on the resultant beam it develops
    ``MOM(2) = E*KYY*Iyy``. Equating the same moment slot pins
    ``Iyy = SUM(A_i*z_i^2)`` and ``Izz = SUM(A_i*y_i^2)``.

    DO NOT "FIX" THIS BACK. The starter's own listing block
    (``hm_read_prop18.F:289-301``) prints ``TIYY_I = SUM(INI + ARI*RYI*RYI)``,
    i.e. it labels the Y-based sum "Iyy". That label is inverted relative to the
    field it shares a name with, and it is print-only — ``TIYY_I`` is never
    stored into GEO and never reaches the engine. Two further in-repo
    cross-checks agree with the engine and not with the listing:
    ``_constants_from_shape``'s ICST=11 box returns ``iyy = D1*D2^3/12`` with D1
    along y (``defbeam_sect_new.F90`` case(20): ``dy1 = l(1)*fac``), and
    ``handle_section_beam``'s ELFORM=2 branch maps ``iyy <- ISS``, LS-DYNA's
    "area moment of inertia about local s-axis" = ``INT t^2 dA`` = ``INT z^2 dA``
    (Vol I R17 p.41-15).

    ``INI = A_i^2/12`` is the starter's per-cell self-inertia, which models each
    cell as a SQUARE patch of area A_i. That is exact only for square cells — a
    4x4 grid of 0.5 x 2.0 cells on a 2 x 8 box wants 0.5*2^3/12 = 0.333 each and
    gets 1/12 — but a rule states no cell SHAPE, only a position and an area, so
    no better term is recoverable. It is kept because it is the same term the
    starter prints, and dropping it would be further from the continuum section,
    not closer.

    ``Ixx = Iyy + Izz`` is the POLAR moment, which equals the torsion constant
    only for a circular section — the same approximation dyna2rad makes when
    *SECTION_BEAM leaves ``J`` at zero (``convertprops.cxx:1400-1402``).
    """
    area = iyy = izz = 0.0
    for y, z, a in points:
        ini = a * a / 12.0
        area += a
        iyy += ini + a * z * z
        izz += ini + a * y * y
    return area, iyy, izz, iyy + izz


def _constants_from_shape(icst: int, dims: List[float]):
    """(Area, Iyy, Izz, Ixx) of the three standard shapes with a closed form
    both codes agree on, or None.

    ICST 8 (circular) and 11 (solid box) are the two dyna2rad hard-codes on its
    *SECTION_BEAM standard-section path (``convertprops.cxx:1372-1375`` and
    ``:1390-1393``); ICST 9 (tubular) is the same circle minus its bore, with
    ``D1``/``D2`` as outer/inner RADIUS exactly as Radioss's own Isect 18 reads
    them (``area = pi*(l(1)**2-l(2)**2)``, ``defbeam_sect_new.F90:380``). Note
    that these are radii — *SECTION_BEAM's own CST=1 tubular spelling uses
    DIAMETERS on TS1/TT1 instead (see ``_constants_from_thicknesses``), so the
    two must not be conflated.

    For the box, D1 runs along local y and D2 along local z: the starter builds
    its point cloud with ``dy1 = l(1)*fac`` / ``dz1 = l(2)*fac``
    (``defbeam_sect_new.F90`` case(20)). ``iyy = D1*D2^3/12`` is therefore
    ``INT z^2 dA``, which is what the engine's Iyy slot means — see the
    convention proof in ``_constants_from_points``. The asymmetric box is
    pinned by a test precisely because the circle and tube are symmetric and
    would hide a swap.
    """
    d = list(dims) + [0.0] * 6
    if icst == 8:                                        # solid circle, r = D1
        r = d[0]
        i = math.pi * r ** 4 / 4.0
        return math.pi * r * r, i, i, 2.0 * i
    if icst == 9:                                        # tube, ro=D1, ri=D2
        ro, ri = d[0], d[1]
        i = math.pi * (ro ** 4 - ri ** 4) / 4.0
        return math.pi * (ro * ro - ri * ri), i, i, 2.0 * i
    if icst == 11:                                       # solid box D1 x D2
        b, h = d[0], d[1]                                # b along y, h along z
        iyy = b * h ** 3 / 12.0                          # = INT z^2 dA
        izz = h * b ** 3 / 12.0                          # = INT y^2 dA
        return b * h, iyy, izz, iyy + izz
    return None


def _constants_from_thicknesses(cst: int, ts: float, tt: float):
    """(Area, Iyy, Izz, Ixx) of a *SECTION_BEAM stated only as card-2
    thicknesses (ELFORM 0/1/4/5/11, cards 2a and 2e), or None.

    These formulations carry no A/Iyy/Izz/Ixx at all — their card 2 is
    ``TS1 TS2 TT1 TT2 ...`` — so without this the /PROP/BEAM they fall back to
    is written all-zero, which is not a soft beam but a REFUSED deck:
    ``hm_read_prop03.F:151-182`` raises ERROR 314/315/316/317 on each
    non-positive value. The section shape is fully determined by CST
    (Vol I R17 p.41-12/41-13):

      CST 0 / 2   rectangular, TS1 x TT1, TS1 along local s -> y
      CST 1       tubular, TS1 the OUTER and TT1 the INNER **diameter**

    Node-1 values only: /PROP/BEAM is prismatic and TS2/TT2 taper has nowhere
    to go (the caller warns when they differ).
    """
    if ts <= 0.0:
        return None
    if cst == 1:                                  # tube, ro=TS1/2, ri=TT1/2
        ro, ri = ts / 2.0, max(tt, 0.0) / 2.0
        if ri >= ro:
            return None
        i = math.pi * (ro ** 4 - ri ** 4) / 4.0
        return math.pi * (ro * ro - ri * ri), i, i, 2.0 * i
    if tt <= 0.0:
        return None
    iyy = ts * tt ** 3 / 12.0                     # = INT z^2 dA
    izz = tt * ts ** 3 / 12.0                     # = INT y^2 dA
    return ts * tt, iyy, izz, iyy + izz


# ─────────────────────────────────────────────────────────────────────────────
# The build_starter prepass
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_integration_beams(state: ConversionState) -> None:
    """build_starter prepass: bind every ``*SECTION_BEAM`` QR/IRID reference to
    its ``*INTEGRATION_BEAM`` rule, turn the rule into a /PROP/TYPE18 payload
    where Radioss can take one, derive the section constants where it cannot,
    and report every route the rule does not reach.

    Runs AFTER ``_screen_provisional_elements`` (so ``state.beam_elems`` is
    final and a phantom element cannot claim a section) and AFTER
    ``_resolve_mat_johnson_cook`` (the LAW2-vs-LAW4 routing decides the material
    gate), and BEFORE ``_make_parts_and_elements`` / ``_make_properties``, which
    emit the /PART and the /PROP this pass chooses between.

    The chosen property is keyed on the SECID and nothing else: an integration
    rule hangs off the SECTION in LS-DYNA, so every *PART on that section gets
    the same integrated beam and no per-part /PROP split (the ``ortho_prop_ids``
    / ``composite_prop_ids`` mechanism the shell side needs) is required.
    """
    if not state.integration_beams and not any(
            s.irid for s in state.sec_beams.values()):
        return

    referenced: Set[int] = set()
    beam_pids = {e.pid for e in state.beam_elems}
    spotweld_pids = _spotweld_beam_pids(state)
    # secid -> the *PARTs whose beams use it (LS-DYNA lets SECID default to PID)
    sec_parts: Dict[int, List[int]] = {}
    for pid in sorted(beam_pids):
        part = state.parts.get(pid)
        secid = part.secid if part is not None and part.secid > 0 else pid
        sec_parts.setdefault(secid, []).append(pid)

    for sec in sorted(state.sec_beams.values(), key=lambda s: s.secid):
        if sec.irid <= 0:
            continue
        label = f"*SECTION_BEAM {sec.secid}"
        rule = state.integration_beams.get(sec.irid)
        if rule is None:
            state.warn(
                f"{label}: card-1 field 4 (QR/IRID) is -{sec.irid}, which "
                f"references an *INTEGRATION_BEAM rule {sec.irid} that the "
                "deck does NOT define. The section falls back to its own "
                "card-2 data, so the cross-section the rule described is LOST "
                "and the beam keeps whatever Area/Iyy/Izz/Ixx that card gave "
                "(zero, for an ELFORM 1/4/5/11 thickness card). dyna2rad never "
                "reads the field on a beam at all, so it cannot even report "
                "the dangling reference.")
            continue
        referenced.add(rule.irid)
        if sec.elform == 14:
            # ELFORM 14 is the one formulation that MANDATES a rule: "Elbow
            # integrated tubular beam element. A user-defined integration rule
            # with a tubular cross section (9) must be used" (Vol I R17
            # p.41-11). The rule is understood perfectly well here; what is
            # missing is the element.
            state.warn(
                f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED because "
                "ELFORM=14 is the ELBOW element, which Radioss has no "
                "counterpart for — not because the rule is wrong. ELFORM 14 is "
                "in fact the one formulation that REQUIRES a user rule, and a "
                "tubular one (ICST=9) at that. Its card 2 is 'PR IOVPR IPRSTR' "
                "and carries no section at all, so the /PROP/BEAM left behind "
                "has Area=Iyy=Izz=Ixx=0 and the starter refuses it (ERROR "
                "314-317). Model the elbow as ordinary integrated beams "
                "(ELFORM 1) over the bend if the pipe-ovalization response is "
                "not what the deck is about.")
            continue
        if sec.elform not in _INTEGRATED_ELFORMS:
            state.warn(
                f"{label}: ELFORM={sec.elform} does not integrate a "
                f"cross-section, so *INTEGRATION_BEAM {rule.irid} is DROPPED — "
                "a user cross-section rule has meaning only for the "
                "formulations that integrate one, and of those Radioss can "
                "carry ELFORM 1, 4, 5 and 11 (ELFORM 0 is an alias of 1; "
                "ELFORM 14 integrates one too but is the elbow element and is "
                "reported separately). The section keeps its own card-2 data. "
                "Change ELFORM if the rule is meant to define the section.")
            continue
        if rule.sref or rule.tref:
            state.warn(
                f"*INTEGRATION_BEAM {rule.irid}: SREF={rule.sref:g} / "
                f"TREF={rule.tref:g} are DROPPED — they move the beam's "
                "reference axis inside the section (and override "
                "*SECTION_BEAM's NSLOC/NTLOC 'even if SREF = 0', Vol I R17 "
                "p.29-2), but /PROP/TYPE18 has no offset column: its section "
                "centre is either the point barycentre (Iref=0) or Y0/Z0 "
                "(Iref=1), both measured from the beam's node line. Offset the "
                "S/T coordinates of the rule instead if the eccentricity "
                "carries load.")
        pids = sec_parts.get(sec.secid, [])
        if not pids:
            state.warn(
                f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — no "
                "*ELEMENT_BEAM uses this section, so there is no beam for the "
                "cross-section to act on.")
            continue
        if all(p in spotweld_pids for p in pids):
            state.warn(
                f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — every "
                "part on this section is a *MAT_SPOTWELD beam, which k2rad "
                "converts to a /SPRING with a /PROP/TYPE13 (SPR_BEAM) nugget "
                "and never to a beam property at all.")
            continue

        geo = _rule_geometry(state, sec, rule, label)
        if geo is None:
            continue
        isect, nitrs, l1, l2, points = geo

        # Material gate BEFORE the property type is chosen, not after: a
        # /PROP/TYPE18 on an incompatible law is starter ERROR 3047 + ERROR 745,
        # which kills the run outright.
        bad = sorted(p for p in pids if p not in spotweld_pids
                     and not _type18_material(
                         state, state.parts[p].mid if p in state.parts else 0))
        if bad:
            derived = (_constants_from_points(points) if isect == 0
                       else _constants_from_shape(rule.icst, rule.dims))
            # Belt and braces: unreachable today, because _predefined_geometry
            # has already rejected every shape needing more than two
            # dimensions and ICST 8/9/11 — the whole nb_dim <= 2 set — are
            # exactly the three _constants_from_shape covers. It stays so that
            # widening _MAX_PREDEFINED_DIMS cannot silently start emitting
            # zero-stiffness properties.
            got_constants = derived is not None
            if got_constants:
                sec.area, sec.iyy, sec.izz, sec.ixx = derived
            # The gate is per SECTION, so ONE incompatible part moves every
            # part on it. Parts whose own law would have taken the integrated
            # property are named, because they are the ones that lose
            # through-section plasticity to a neighbour's material choice —
            # and, once on /PROP/BEAM, a BEAM_INTEGRATED law (LAW34/36/71)
            # among them is itself an ERROR 3047, which the TYPE3 material
            # gate in writer/mesh.py then reports by name.
            ok = sorted(p for p in pids if p not in spotweld_pids
                        and p not in bad)
            state.warn(
                f"{label}: *INTEGRATION_BEAM {rule.irid} cannot become a "
                f"/PROP/TYPE18 — part(s) {bad} carry a material whose Radioss "
                "law is not BEAM_INTEGRATED or BEAM_ALL (only LAW0/2/13/44 and "
                "LAW34/36/71 are; /MAT/ELAST LAW1 in particular is TYPE3-only, "
                "check_mat_elem_prop_compatibility.F:239-241, ERROR 3047 + "
                "ERROR 745). The section stays on /PROP/BEAM (TYPE3) "
                + ("with the Area/Iyy/Izz/Ixx DERIVED from the rule, so the "
                   "stiffness is right but the through-section stress "
                   "distribution and any plasticity front are lost. "
                   if got_constants else
                   "and the rule's geometry is LOST, because no closed-form "
                   "section constant exists for this shape. ")
                + (f"The gate is per SECTION, so part(s) {ok} are moved with "
                   "them even though their own law would have taken the "
                   "integrated beam — and if any of those is LAW34/36/71 the "
                   "/PROP/BEAM it lands on rejects it in turn. Put them on "
                   "their own *SECTION_BEAM to keep the rule. " if ok else "")
                + "Give the beam parts an elasto-plastic law "
                "(*MAT_PIECEWISE_LINEAR_PLASTICITY -> LAW36, or "
                "*MAT_PLASTIC_KINEMATIC -> LAW44) to keep the integrated beam.")
            continue

        state.int_beam_props[sec.secid] = IntBeamProp(
            secid=sec.secid, isect=isect, nitrs=nitrs, l1=l1, l2=l2,
            points=points)

    orphans = sorted(set(state.integration_beams) - referenced)
    if orphans:
        state.note_recognized_not_emitted(
            "*INTEGRATION_BEAM",
            "rule(s) " + ", ".join(str(r) for r in orphans)
            + " are defined but no *SECTION_BEAM references them (card-1 field "
            "4, QR/IRID, must be the NEGATIVE of the rule id) — an integration "
            "rule has no standalone Radioss counterpart, so nothing is emitted "
            "for them")


def _rule_geometry(state: ConversionState, sec: SectionBeam,
                   rule: IntegrationBeam, label: str):
    """(Isect, NITRS, L1, L2, points) for one bound rule, or None when the rule
    cannot describe a section at all. Warns once per rejected route."""
    if rule.icst == 0:
        return _arbitrary_geometry(state, sec, rule, label)
    return _predefined_geometry(state, rule, label)


def _arbitrary_geometry(state: ConversionState, sec: SectionBeam,
                        rule: IntegrationBeam, label: str):
    """ICST = 0: the S/T/WF point cloud, denormalized onto the real section.

    LS-DYNA states a cell as (S, T) in [-1, 1] and a weight ``WF = A_i/A``;
    Radioss wants ABSOLUTE local coordinates and an ABSOLUTE area
    (prop_p18_int_beam.cfg:29-31). The +/-1 square is *SECTION_BEAM card 2a's
    ``TS1`` x ``TT1`` rectangle and the gross area is ``RA * TS1 * TT1``, so::

        Y_i = (S_i - NSLOC) * TS1/2    Z_i = (T_i - NTLOC) * TT1/2
        A_i = WF_i/SUM(WF) * A

    ``NSLOC``/``NTLOC`` (card 2a fields 5/6) are what put the section where
    LS-DYNA puts it. They give the "location of the reference surface" — the
    beam's node line — inside the same +/-1 square: ``EQ.1.0: Side at s = 1.0``,
    ``EQ.0.0: Center``, ``EQ.-1.0: Side at s = -1.0`` (Vol I R17 p.41-13/41-14).
    Subtracting them re-expresses each cell RELATIVE TO THE NODES, which is the
    frame /PROP/TYPE18's Yi/Zi are measured in. A beam hung off a shell surface
    with NSLOC=1 would otherwise be silently re-centred on its nodes, losing
    exactly the eccentricity that couples axial force to bending. The rule's
    own SREF/TREF override NSLOC/NTLOC "even if SREF = 0" (p.29-3) but exist
    only on the ICST > 0 dimension card, which never reaches this function, so
    the two cannot collide here.

    Normalizing by ``SUM(WF)`` is a no-op on the usual deck (the WFs sum to 1)
    and is what dyna2rad's shell rule does with the same field
    (convertprops.cxx:1991-1996); it keeps the total area equal to ``A`` when a
    deck's weights do not add up. LS-DYNA itself applies WF literally, so the
    rescale is reported whenever it actually moves the area.
    """
    if not rule.points:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} has ICST=0 and NIP="
            f"{rule.nip}, so it defines no integration cell at all and is "
            "DROPPED. An arbitrary section needs one S/T/WF/PID card per cell.")
        return None
    sum_wf = sum(p.wf for p in rule.points)
    if sum_wf <= 0.0:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — its "
            "weighting factors sum to 0, so no cell area can be derived. WF is "
            "the area FRACTION A_i/A of each cell and must be positive.")
        return None
    if sec.cst == 1:
        # CST=1 makes TS1/TT1 an OUTER and an INNER DIAMETER, not an s- and a
        # t-extent (Vol I R17 p.41-13). The +/-1 square the rule's S/T live in
        # is then not a TS1 x TT1 rectangle at all, and denormalizing them as
        # one would state an annulus as a solid box — pi/4*(TS1^2-TT1^2) of
        # real area emitted as TS1*TT1, with no diagnostic. LS-DYNA's own
        # spelling for "the rule IS the section" is CST=2 (Arbitrary).
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — card 1 field "
            "5 (CST) is 1 = TUBULAR, which redefines card 2 as TS1 = the OUTER "
            f"and TT1 = the INNER DIAMETER ({sec.ts1:g} and {sec.tt1:g} here), "
            "not the s- and t-direction thicknesses. The rule's S/T are "
            "normalized to a RECTANGLE and k2rad will not place them on an "
            "annulus, because doing so silently would emit TS1 x TT1 of area "
            "where the section really has pi/4*(TS1^2 - TT1^2). Set CST=2 "
            "(Arbitrary, the value the manual pairs with a user rule) and "
            "state TS1/TT1 as the bounding-box thicknesses, or drop the rule "
            "and let the tubular section stand on its own card 2.")
        return None
    ts, tt = sec.ts1, sec.tt1
    if ts <= 0.0 or tt <= 0.0:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — the rule's S "
            "and T are NORMALIZED to +/-1 and can only be placed once the "
            "section's own thicknesses are known, but card 2 gives "
            f"TS1={ts:g} and TT1={tt:g}. Fill the s-direction and t-direction "
            "thickness at node 1 (card 2 fields 1 and 3).")
        return None
    if (sec.ts2 and sec.ts2 != ts) or (sec.tt2 and sec.tt2 != tt):
        state.warn(
            f"{label}: the section is TAPERED (TS1={ts:g} TS2={sec.ts2:g}, "
            f"TT1={tt:g} TT2={sec.tt2:g}) but /PROP/TYPE18 has no taper column "
            "— its Yi/Zi/AREA cloud is one prismatic cross-section for the "
            "whole element. The NODE-1 section is emitted and the node-2 end "
            "is DROPPED, so the beam is stiffer and heavier than the deck says "
            "wherever it narrows. Split the beam into several *PARTs with "
            "stepped sections if the taper carries load.")
    ra = rule.ra
    if ra <= 0.0:
        state.warn(
            f"*INTEGRATION_BEAM {rule.irid} (referenced by {label}): RA="
            f"{rule.ra:g} is not positive. RA is the RELATIVE area "
            "A/(TS1*TT1) and its card default is 0.0, which would make every "
            "integration cell zero-area (starter ERROR 314, "
            "hm_read_prop18.F:169) — k2rad uses RA=1.0, i.e. the full "
            f"TS1 x TT1 = {ts * tt:g} rectangle, so the deck still runs. Write "
            "the real relative area if the section does not fill its bounding "
            "box.")
        ra = 1.0
    area = ra * ts * tt
    if abs(sum_wf - 1.0) > 1.0e-6:
        state.warn(
            f"*INTEGRATION_BEAM {rule.irid} (referenced by {label}): its "
            f"weighting factors sum to {sum_wf:g}, not 1. WF is the area "
            "FRACTION A_i/A (Vol I R17 p.29-3) and LS-DYNA applies it "
            f"LITERALLY, so this section really carries {sum_wf:g} x its gross "
            "area. k2rad RENORMALIZES by the sum — the same thing dyna2rad's "
            "shell rule does with the same field (convertprops.cxx:1991-1996) "
            f"— so every cell is scaled by {1.0 / sum_wf:g} and the emitted "
            f"section area is the full RA*TS1*TT1 = {area:g}. Make the weights "
            "add up to 1, or fold the shortfall into RA, if the deck meant the "
            "smaller area.")
    # NSLOC/NTLOC move the NODE LINE inside the +/-1 square, so the cells are
    # offset the other way to land in the nodes' frame (see the docstring).
    pts = [((p.s - sec.nsloc) * ts / 2.0, (p.t - sec.ntloc) * tt / 2.0,
            p.wf / sum_wf * area) for p in rule.points]
    bad_area = [i + 1 for i, (_, _, a) in enumerate(pts) if a <= 0.0]
    if bad_area:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — cell(s) "
            f"{bad_area} come out with a non-positive area (a WF <= 0), which "
            "the starter rejects with ERROR 314 'AREA OF THE SUBSECTION MUST "
            "BE POSITIVE' (hm_read_prop18.F:169). Every WF is an area fraction "
            "and must be > 0.")
        return None
    off = [p for p in rule.points if p.pid > 0]
    if off:
        state.warn(
            f"*INTEGRATION_BEAM {rule.irid} (referenced by {label}): the "
            f"per-cell PID of {len(off)} integration point(s) is DROPPED — "
            "/PROP/TYPE18 has one material for the whole cross-section "
            "(prop_p18_int_beam.cfg has no per-point material column), so a "
            "beam made of two materials cannot be expressed. Every cell takes "
            "the *PART's own *MAT. Split the beam into two parts if the second "
            "material carries load.")
    if len(pts) > _MAX_IP:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} defines {len(pts)} "
            f"integration cells but /PROP/TYPE18 carries at most {_MAX_IP} "
            "('NIP <= 100', prop_p18_int_beam.cfg:90, starter ERROR 977 in "
            f"hm_read_prop18.F:257) — the first {_MAX_IP} are kept and the "
            "rest DROPPED, so the section loses area and inertia. Coarsen the "
            "rule.")
        pts = pts[:_MAX_IP]
    return 0, 0, 0.0, 0.0, pts


def _predefined_geometry(state: ConversionState, rule: IntegrationBeam,
                         label: str):
    """ICST > 0: one of LS-DYNA's 22 standard shapes -> Isect = ICST + 9."""
    entry = _ICST_TO_ISECT.get(rule.icst)
    if entry is None:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — ICST="
            f"{rule.icst} is not one of the 22 standard cross-section types "
            "(Vol I R17 p.29-2 lists EQ.01 through EQ.22; EQ.0 means the "
            "arbitrary S/T/WF form).")
        return None
    isect, nb_dim, intr_max = entry
    if nb_dim > _MAX_PREDEFINED_DIMS:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — ICST="
            f"{rule.icst} maps to Radioss Isect={isect}, which needs "
            f"{nb_dim} dimensions (L1..L{nb_dim}), but the /PROP/TYPE18 card "
            "layout a /BEGIN 2022 deck reads declares only L1 and L2 "
            "(radioss120/PROP/prop_p18_int_beam.cfg). Writing the rest earns "
            "WARNING 100213 'unsupported field exists at the end of line' and "
            "then ERROR 3059 MISSING DIMENSIONS FOR PREDEFINED SECTION. "
            "Restate the shape as an ICST=0 rule with explicit S/T/WF cells — "
            "that form has no version gate — or state the section's "
            "A/ISS/ITT/J numerically on an ELFORM=2 *SECTION_BEAM.")
        return None
    dims = list(rule.dims) + [0.0] * nb_dim
    missing = [i + 1 for i in range(nb_dim) if dims[i] <= 0.0]
    if missing:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} is DROPPED — ICST="
            f"{rule.icst} needs {nb_dim} positive dimension(s) but D"
            + ", D".join(str(m) for m in missing)
            + " is zero or negative on the standard-section card. Radioss "
            "rejects the same gap with ERROR 3059 ('DIMENSION L<i> IS "
            "MISSING', hm_read_prop18.F:224-232) and its CHECK block requires "
            "L1..L6 > 0.")
        return None
    nitrs = max(rule.k, 0)
    if nitrs > intr_max:
        state.warn(
            f"{label}: *INTEGRATION_BEAM {rule.irid} has K={rule.k}, which is "
            f"carried to /PROP/TYPE18's NITRS but CLAMPED to {intr_max} — that "
            f"is the refinement ceiling Radioss sets for Isect={isect} "
            "(defbeam_sect_new.F90), and exceeding it is ERROR 3060 "
            "(hm_read_prop18.F:212). The section is integrated more coarsely "
            "than the deck asked; the two codes count refinement differently "
            "anyway, so K and NITRS are not the same number of points.")
        nitrs = intr_max
    return isect, nitrs, dims[0], dims[1] if nb_dim > 1 else 0.0, []


# ─────────────────────────────────────────────────────────────────────────────
# Emission
# ─────────────────────────────────────────────────────────────────────────────

def _emit_prop_int_beam(sec: SectionBeam, prop: IntBeamProp) -> List[str]:
    """/PROP/TYPE18 (INT_BEAM) card block.

    Layout audited against ``hm_cfg_files`` ``radioss120/PROP/
    prop_p18_int_beam.cfg`` FORMAT(radioss120):199-235, the block a /BEGIN 2022
    deck resolves to (radioss2024's, which adds an ``L5 L6`` card in place of
    the trailing BLANK, is invisible below /BEGIN 2024)::

        CARD("%-100s", TITLE);
        CARD("%10d%10d", ISFLAG, Ismstr);
        CARD("%20lg%20lg", Dm, df);
        CARD("%10d%10d%20lg%20lg", NIP, Iref, Y0, Z0);
        if(NIP>0)      CARD_LIST(NIP) { CARD("%20lg%20lg%20lg", Y_IP,Z_IP,AREA_IP); }
        if(ISFLAG!=0){ CARD("%10d          %20lg%20lg", NITRS, L1, L2); BLANK; }
        CARD("   %1d%1d%1d %1d%1d%1d", Wx1,Wy1,Wz1,Wx2,Wy2,Wz2);

    ``Ismstr=4`` (full geometric nonlinearities) matches what dyna2rad writes on
    its own TYPE18 path (``convertprops.cxx:1282``) and what the CFG defaults
    to. ``Dm``/``df`` are written as explicit zeros exactly as /PROP/BEAM does;
    the starter turns a zero flexural damping into its 1e-2 default anyway
    (``hm_read_prop18.F:156``).

    ``Iref=1`` with ``Y0=Z0=0`` — NOT the ``Iref=0`` barycentre — is what keeps
    the beam's reference axis where LS-DYNA put it. The rule's S/T are measured
    from the beam's node line, and ``Iref=0`` would re-centre the section on the
    area centroid of the cells (``hm_read_prop18.F:267-276`` computes Y0/Z0 as
    the area-weighted mean and then shifts every point by it), silently moving
    the neutral axis of any deliberately eccentric section.
    """
    isect = prop.isect
    lines = [
        f"/PROP/TYPE18/{sec.secid}",
        sec.title or f"PROP_{sec.secid}",
        "#    Isect    Ismstr",
        f"{_i(isect)}{_i(4)}",
        "#                 Dm                  Df",
        "                   0                   0",
        "#      NIP      Iref                  Y0                  Z0",
    ]
    if isect == 0:
        lines.append(f"{_i(len(prop.points))}{_i(1)}{_f(0.0)}{_f(0.0)}")
        lines.append("#                 Yi                  Zi"
                     "                AREA")
        for y, z, a in prop.points:
            lines.append(f"{_f(y)}{_f(z)}{_f(a)}")
    else:
        # The CFG force-zeroes NIP/Iref/Y0/Z0 on export whenever Isect != 0
        # (prop_p18_int_beam.cfg:206-212): the starter generates the point cloud
        # for a predefined shape itself.
        lines.append(f"{_i(0)}{_i(0)}{_f(0.0)}{_f(0.0)}")
        lines.append("#    NITRS                            L1"
                     "                  L2")
        lines.append(f"{_i(prop.nitrs)}{'':>10}{_f(prop.l1)}{_f(prop.l2)}")
        lines.append("")
    lines += ["#    W_DOF", "   000 000", HDR]
    return lines
