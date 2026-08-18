"""Starter thick shells: ``*ELEMENT_TSHELL`` → ``/BRICK`` and
``*SECTION_TSHELL`` / ``*PART_COMPOSITE_TSHELL`` → the three thick-shell
properties.

======================================  ======================================
LS-DYNA                                 Radioss
======================================  ======================================
``*ELEMENT_TSHELL`` (+ _BETA/_COMPOSITE) ``/BRICK``, connectivity VERBATIM
``*SECTION_TSHELL`` ICOMP=0, isotropic   ``/PROP/TYPE20`` (TSHELL)
``*SECTION_TSHELL`` ICOMP=0, orthotropic ``/PROP/TYPE21`` (TSH_ORTH)
``*SECTION_TSHELL`` ICOMP=1              ``/PROP/TYPE22`` (TSH_COMP)
``*PART_COMPOSITE_TSHELL``               ``/PROP/TYPE22``, REAL per-ply data
======================================  ======================================

The three-way split follows dyna2rad's own branch (``convertprops.cxx:
4279-4312``) exactly: ICOMP=1 always wins, and an ICOMP=0 section splits on
whether the PART's MATERIAL is orthotropic. Card layouts are pinned at the
FORMAT block a ``/BEGIN 2022`` deck actually reads — ``radioss2018`` for TYPE20
and TYPE21, ``radioss90`` for TYPE22 (there is no ``radioss2022`` file for any
of the three, and TYPE22 has no 2018 block either).

Six deliberate divergences from dyna2rad, every one of them a measured defect
on its side:

1. **``Icstr`` is written explicitly** (010, the thickness direction that maps
   LS-DYNA's n1-n4 → n5-n8 convention). dyna2rad leaves the column blank and
   relies on the starter's own ``IF (IHBE == 14 .AND. ICSTR == 0) ICSTR = 10``.
   That works for TYPE20/21 but DESYNCS TYPE22: the CFG counts the layer cards
   itself in a chain that matches only ``Icstr == 100/10/1``, so with the column
   blank ``N`` is never set and the reader consumes the wrong number of layer
   cards while the starter expects ``NPTS`` of them. Measured: ``WARNING ID :
   100213 ... unsupported field exists at the end of line`` followed by
   ``ERROR ID : 675`` with an EMPTY last layer.
2. **A blank ELFORM is LS-DYNA's default 1**, not 0. dyna2rad's ``elform == 1 ?
   15 : 14`` sends a blank straight to the full-integration HA8.
3. **A blank NIP is LS-DYNA's default 2**, not 0 (measured: dyna2rad echoed
   ``NIP = 0``). On the composite branch its 0 writes zero ply cards against a
   property that expects one — ERROR 675 again.
4. **``Inpts`` is clamped to 1..9 on Isolid=15 too.** dyna2rad clamps only on
   the Isolid=14 branch and passes a raw NIP > 9 through to starter ERROR 563.
5. **The orthotropy axes use the #90 ``_composite_ref_axis`` route** — all six
   AOPT modes, with a synthesized ``/SKEW/FIX`` where one is needed. dyna2rad
   copies ``A1/A2/A3`` for AOPT=2 and ``V1/V2/V3`` for AOPT=3 and writes NOTHING
   for AOPT 0/1/4/negative, leaving a zero reference vector that the starter
   rejects PER ELEMENT with ERROR 526 ("REFERENCE DIRECTION IS ALMOST NORMAL TO
   THICK SHELL MID-SURFACE").
6. **``*PART_COMPOSITE_TSHELL`` becomes a real TYPE22.** dyna2rad dispatches it
   on the substring ``COMPOSITE`` alone and emits the THIN-shell
   ``/PROP/TYPE51`` + ``/PROP/TYPE19`` sandwich, which its own starter then
   refuses on the bricks: ``ERROR ID : 60 ... INVALID PROPERTY ID=1 (TYPE = 51)
   FOR BRICK ELEMENT`` plus ``ERROR ID : 226 WRONG SOLID PROPERTY TYPE 51``.

What is dropped, and said so: ``PROPT`` (a printout option), ``TSHEAR``
(parabolic vs constant transverse shear — a real physics difference), ``QR < 0``
(a user ``*INTEGRATION_SHELL`` rule), and ``SHRF`` on TYPE20/TYPE21, which have
no transverse-shear column at all. On TYPE22 ``SHRF`` DOES map, to ``Ashear``;
dyna2rad drops it there as well (measured: ``SHRF = 0.7`` echoed
``SHEAR AREA REDUCTION FACTOR = 1.000``).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..state import (
    ConversionState,
    CompositePly,
    SectionTshell,
    TshellLayup,
)
from .common import HDR, _f, _i
from .composites import _RefAxis, _composite_ref_axis

__all__ = [
    "_resolve_tshells",
    "_tshell_part_ids",
    "_make_tshell_properties",
    "_emit_prop_type20",
    "_emit_prop_type21",
    "_emit_prop_type22",
]


# ─────────────────────────────────────────────────────────────────────────────
# Material-law compatibility — the /PROP/TYPE20|21|22 analogue of
# _warn_beam_type3_material
# ─────────────────────────────────────────────────────────────────────────────
#
# ``check_mat_elem_prop_compatibility.F:198-234`` gates each thick-shell
# property on the material's ``MATPARAM%PROP_SOLID`` class, which every law
# self-declares through ``INIT_MAT_KEYWORD`` (``init_mat_keyword.F:216-246``):
#
#     CASE (20)  PROP_SOLID must be 1, 5 or 6
#     CASE (21)  PROP_SOLID must be 1, 2 or 6
#     CASE (22)  PROP_SOLID must be 1, 2, 3 or 6
#
# Anything else is **ERROR 3047** ``PROPERTY ID %d OF TYPE %d IS NOT COMPATIBLE
# WITH MATERIAL ID %d OF TYPE %d``; a law that declares NO solid class at all
# (``PROP_SOLID == 0``) fails one step earlier with **ERROR 3046**
# ``ELEMENTS OF TYPE ... ARE NOT COMPATIBLE WITH MATERIAL ID ...``. Both were
# measured on ``starter_win64``: ``/MAT/LAW12`` on a TYPE20 gives
# ``ERROR ID : 3047 ... PROPERTY ID 1 OF TYPE 20 IS NOT COMPATIBLE WITH MATERIAL
# ID 9 OF TYPE 12``, and the same LAW12 on a TYPE21 is accepted with 0 errors.
#
# Classes, for the laws k2rad actually EMITS, read off the INIT_MAT_KEYWORD call
# sites in the 2026-05-20 starter tree:
#   1 SOLID_ISOTROPIC         2 SOLID_ORTHOTROPIC     4 SOLID_COHESIVE
#   5 SOLID_POROUS            6 SOLID_ALL             7 SOLID_BRICK_ISOTROPIC
# (class 3 SOLID_COMPOSITE is declared by NO law in the tree, so TYPE22's extra
# allowance for it is unreachable.)
_SOLID_MAT_CLASS: Dict[int, int] = {
    0: 1, 1: 1, 2: 1, 4: 1, 5: 1,
    6: 5,                      # LAW6 HYD_VISC — POROUS, so TYPE20 only
    21: 1, 28: 2,              # LAW28 HONEYCOMB is ORTHOTROPIC
    34: 1, 36: 1, 38: 1, 40: 1, 42: 1, 44: 1, 50: 1, 52: 1, 62: 1, 66: 1,
    69: 1, 70: 1, 76: 1, 79: 1,
    88: 7,                     # SOLID_BRICK_ISOTROPIC — no thick shell takes it
    90: 1, 93: 2, 95: 1, 109: 1, 115: 1,
    116: 4, 117: 4,            # cohesive — /PROP/TYPE43 only
    120: 6, 121: 1, 126: 1,
    127: 2, 128: 2,            # ENHANCED_COMPOSITE, HILL_VISC_PLAST
    169: 4,
}

#: Laws k2rad emits that declare NO solid class at all — a thick shell on one of
#: them is ERROR 3046, one step before any property is examined. All three are
#: shell-only laws (LAW27 PLAS_BRIT from *MAT_032, LAW32/LAW43 HILL from
#: *MAT_122/*MAT_037).
_NO_SOLID_CLASS_LAWS = frozenset({27, 32, 43})

_TSHELL_PROP_CLASSES: Dict[int, frozenset] = {
    20: frozenset({1, 5, 6}),
    21: frozenset({1, 2, 6}),
    22: frozenset({1, 2, 3, 6}),
}

#: The classes that make a *SECTION_TSHELL take TYPE21 rather than TYPE20.
#: dyna2rad splits on the MATERIAL CARD's ``axisOptFlag`` instead, which is
#: ``AOPT + 1`` after the CFG's enum remap — i.e. on whether the material has an
#: AOPT FIELD, not on what is in it (so even ``AOPT = 0`` routes to TYPE21).
#: Keying on the emitted law's own solid class lands on the same answer for
#: every real deck and states the actual constraint: class 2 is exactly what
#: TYPE20 rejects with ERROR 3047.
_ORTHO_SOLID_CLASS = 2

#: /MAT/LAW1 (ELAST) force-resets the through-thickness integration on TYPE20
#: and TYPE21 — ``sgrtails.F:694-704``: ``IF(MLN == 1 .AND. IGT /= 22)`` then
#: ``NPT = 2`` / ``NPT = 222`` and **WARNING 791**. TYPE22 is exempt.
_LAW1 = 1


def _tshell_part_ids(state: ConversionState) -> Set[int]:
    """*PART ids that own at least one thick shell."""
    return {e.pid for e in state.tshell_elems}


def _part_secid(state: ConversionState, pid: int) -> int:
    part = state.parts.get(pid)
    if part is None:
        return pid
    return part.secid if part.secid > 0 else pid


def auto_section_tshell(secid: int) -> SectionTshell:
    """The default *SECTION_TSHELL k2rad synthesizes when a thick-shell *PART's
    SECID has no card — ELFORM 1 (LS-DYNA's own default: one-point reduced
    integration) and NIP 2, i.e. the Isolid=15 / Inpts=2 property. Kept in sync
    with the auto-create in ``_make_properties``."""
    return SectionTshell(secid, f"AutoPropTshell_{secid}", 1, nip=2)


# ─────────────────────────────────────────────────────────────────────────────
# ELFORM / NIP → Isolid, Icstr, Inpts
# ─────────────────────────────────────────────────────────────────────────────

#: Radioss reads the thick-shell layer direction off ``Icstr``: "= 010
#: (Default) Reduced stress integration in s direction" (help.altair.com), and
#: ``scdtchk3.F`` builds the through-thickness node pairs there as (1-5) (2-6)
#: (3-7) (4-8) — exactly LS-DYNA's "n1 to n4 define the lower surface, n5 to n8
#: the upper" (Vol I R16 p.2703 Remark 1). So 010 is what makes a VERBATIM
#: connectivity copy preserve the thickness direction, and it is written
#: explicitly rather than left to the starter's own default (see the module
#: docstring, divergence 1).
ICSTR_S = 10


def _tshell_isolid(elform: int) -> int:
    """LS-DYNA *SECTION_TSHELL ELFORM → Radioss Isolid, dyna2rad's own total
    map (``convertprops.cxx:4324-4332``, byte-identical in all three writers):
    ``elform == 1`` → 15, everything else → 14.

    ==========  ======  ==========================================
    ELFORM      Isolid  what is lost
    ==========  ======  ==========================================
    1           15      nothing — HSEPH is the closest match
    2           14      plane stress (extruded thin shell)
    3           14      nothing structural (2x2 in-plane both sides)
    5           14      reduced integration
    6           14      reduced integration AND plane stress
    7           14      nothing structural
    ==========  ======  ==========================================

    5 and 6 are NOT re-routed to the under-integrated 15 even though their
    integration is reduced: Isolid 15 is HSEPH/PA6, whose physical stabilization
    is a different animal from LS-DYNA's assumed-strain enhancement, so the
    swap would trade one known difference for an unmeasured one. It is warned
    about instead.
    """
    return 15 if elform == 1 else 14


def _tshell_inpts(isolid: int, nip: int) -> Tuple[int, int]:
    """(NBP, layer count) for a thick-shell property.

    ``Isolid=14``: 2 x j x 2, packed as ``Inpts = 2*100 + j*10 + 2`` with
    ``j = clamp(NIP, 1, 9)``. Two in-plane Gauss points are forced in r and t
    because the packed field has no way to say "one"; with ``Icstr=010`` the
    LAYER count is that middle digit, so ``j`` is the deck's NIP.

    Two traps the value has to clear, both in the CFG rather than the starter:
    the unpack is gated on ``NBP > 200`` (``prop_p20_tshell.cfg`` /
    ``prop_p21_tsh_orth.cfg``), so a leading digit of 1 — or a bare ``200`` —
    is read as ``Inpts_S = NBP`` with zero points in r and t; and TYPE22's
    layer-card count comes off the same unpacked digits. Writing ``i = 2``
    always keeps ``NBP >= 212``, clear of both.

    ``Isolid=15``: ``Inpts = NIP`` plain, and the starter enforces 1..9
    (``hm_read_prop20.F``, MSGID 563). dyna2rad does not clamp here — see the
    module docstring, divergence 4.
    """
    j = max(1, min(nip, 9))
    if isolid == 14:
        return 2 * 100 + j * 10 + 2, j
    return j, j


# ─────────────────────────────────────────────────────────────────────────────
# Prepass
# ─────────────────────────────────────────────────────────────────────────────

def _tshell_layer_encoding(state: ConversionState, isolid: int, nply: int,
                           what: str) -> Tuple[int, int, int]:
    """(Isolid, Inpts, Iint) for a /PROP/TYPE22 holding *nply* layers.

    Radioss derives ``NLY`` from the property card, and which field it reads
    depends on the formulation and on the packed digits
    (``hm_read_prop22.F:228-293``, mirrored by the CFG's own layer-card count):

    * ``Isolid=15``  → ``NLY = Inpts``, which the reader caps at 9.
    * ``Isolid=14``  → ``NLY`` is the digit ``Icstr`` selects, here the middle
      one (``Icstr = 010`` → ``NPTS``), so also at most 9;
    * ``Isolid=14`` with that digit ZERO → ``NLY = Iint``, up to 200. This is
      the ONLY encoding Radioss has for a laminate of more than nine layers.

    So a >9-ply stack on the under-integrated Isolid=15 has to move to Isolid=14
    to be expressible at all. That is announced rather than done silently: it
    changes the element formulation, and the alternative — writing 12 layer
    cards under an ``Inpts`` that says 9 — is a reader desync, not a
    compromise.
    """
    if nply > 9:
        if isolid != 14:
            state.warn(
                f"{what}: {nply} layers exceed the 9 integration points "
                f"Isolid={isolid} allows (MSGID 563), so the property switches "
                "to the full-integration Isolid=14 with the layer count in "
                "Iint — the only encoding Radioss has for a thick shell of "
                "more than nine layers (hm_read_prop22.F:272-275 reads NLY "
                "from Iint exactly when the thickness digit of Inpts is 0). "
                "The element formulation changes with it.")
        return 14, 202, nply
    return isolid, _tshell_inpts(isolid, nply)[0], 0


def _plies_key(plies: List[CompositePly]):
    return tuple((p.mid, p.thick, p.beta) for p in plies)


def _fold_tshell_beta(state: ConversionState) -> None:
    """*ELEMENT_TSHELL_BETA → the PROPERTY angle, or a warning.

    Radioss ``/BRICK`` has no per-element angle column at all — the contrast
    with ``/SHELL``, which does have ``Phi``, is why this cannot follow
    ``_fold_element_beta``'s element-level route and why the #91 lesson (that
    even ``/SHELL``'s column is read for IGTYP 17/51/52 only) does not apply:
    there is no column to be ignored. The only angle channels on a thick shell
    are ``/PROP/TYPE21``'s ``MAT_BETA`` and ``/PROP/TYPE22``'s per-layer
    ``Prop_phi``, both PROPERTY-level.

    k2rad properties are per-SECTION, so the fold is only sound when every
    thick shell served by a section carries the SAME angle. When it does, the
    angle moves onto the property and the elements' own beta is zeroed, so the
    deck states it exactly once. When it does not, the angle is warn-dropped:
    splitting one property per distinct angle would be expressible, but a
    per-element angle field is what the deck actually asked for and any
    grouping would be a guess at which elements the user meant to share one.
    """
    by_secid: Dict[int, Set[float]] = {}
    for e in state.tshell_elems:
        by_secid.setdefault(_part_secid(state, e.pid), set()).add(e.beta)
    mixed: List[int] = []
    for secid, angles in sorted(by_secid.items()):
        nonzero = {a for a in angles if a}
        if not nonzero:
            continue
        if len(angles) > 1:
            mixed.append(secid)
            continue
        state.tshell_beta_fold[secid] = next(iter(nonzero))
    for e in state.tshell_elems:
        e.beta = 0.0
    if state.tshell_beta_fold:
        shown = ", ".join(f"{s} ({state.tshell_beta_fold[s]:g} deg)"
                          for s in sorted(state.tshell_beta_fold))
        state.warn(
            "*ELEMENT_TSHELL_BETA: Radioss /BRICK has NO per-element material "
            "angle column (unlike /SHELL), so the angle was FOLDED into the "
            f"thick-shell property of section(s) {shown} — every element there "
            "states the same one. It lands on /PROP/TYPE21's Phi or is added "
            "to each /PROP/TYPE22 layer angle; on an ISOTROPIC /PROP/TYPE20 "
            "there is no angle slot and the value is dropped, which costs "
            "nothing because an isotropic material has no material direction "
            "to rotate. (dyna2rad cannot read *ELEMENT_TSHELL_BETA at all — "
            "its CFG declares no BETA attribute — and drops the whole block, "
            "elements included.)")
    if mixed:
        state.warn(
            "*ELEMENT_TSHELL_BETA: thick shells on section(s) "
            + ", ".join(str(s) for s in mixed)
            + " carry DIFFERENT per-element angles, and Radioss has no "
            "per-element angle field on a thick shell — the angles are "
            "DROPPED and every element takes the property's own reference "
            "direction. Split the elements into parts (each with its own "
            "*SECTION_TSHELL) by angle to keep them, or state the layup as "
            "*SECTION_TSHELL ICOMP=1 / *PART_COMPOSITE_TSHELL, whose angles "
            "are per-LAYER and do convert.")


def _elem_composite_layups(state: ConversionState) -> None:
    """*ELEMENT_TSHELL_COMPOSITE → a per-PART layup, when the part agrees.

    LS-DYNA states the stack per ELEMENT; Radioss states it per PROPERTY. The
    promotion is therefore only valid when every thick shell on the part
    declares an identical (MID, THICK, B) sequence — and note that a part whose
    elements DISAGREE is not a broken deck, it is a legal LS-DYNA model that
    Radioss simply cannot express.
    """
    if not state.tshell_elem_plies:
        return
    by_pid: Dict[int, Set[tuple]] = {}
    plies_by_pid: Dict[int, List[CompositePly]] = {}
    for e in state.tshell_elems:
        plies = state.tshell_elem_plies.get(e.eid)
        key = _plies_key(plies) if plies else ()
        by_pid.setdefault(e.pid, set()).add(key)
        if plies and e.pid not in plies_by_pid:
            plies_by_pid[e.pid] = plies
    uniform: List[int] = []
    ragged: List[int] = []
    for pid, keys in sorted(by_pid.items()):
        if pid not in plies_by_pid:
            continue
        if len(keys) > 1:
            ragged.append(pid)
            continue
        plies = [p for p in plies_by_pid[pid] if p.mid > 0 and p.thick > 0.0]
        if not plies:
            ragged.append(pid)
            continue
        part = state.parts.get(pid)
        state.tshell_layups[pid] = TshellLayup(
            pid=pid,
            title=(part.title if part is not None else "") or f"PART_{pid}",
            source="*ELEMENT_TSHELL_COMPOSITE",
            plies=plies)
        uniform.append(pid)
    if uniform:
        state.warn(
            "*ELEMENT_TSHELL_COMPOSITE: part(s) "
            + ", ".join(str(p) for p in uniform)
            + " declare one identical ply stack on every thick shell, so it "
            "was promoted to a per-part /PROP/TYPE22 (Radioss states a layup "
            "on the PROPERTY, never on the element). Ply thicknesses become "
            "the relative ti/t the property wants — LS-DYNA scales THICKi to "
            "the element geometry on a thick shell too (Vol I R16 p.3529), so "
            "no absolute length is lost.")
    if ragged:
        state.warn(
            "*ELEMENT_TSHELL_COMPOSITE: thick shells on part(s) "
            + ", ".join(str(p) for p in ragged)
            + " declare DIFFERENT per-element ply stacks (or none that is "
            "usable). Radioss has no per-element layup and a /PROP is shared "
            "by the whole part, so the stacks are DROPPED and the part falls "
            "back on its *SECTION_TSHELL property — the MESH and the part's "
            "own material survive, the laminate does not. Split the part by "
            "layup, or state one layup per part with "
            "*PART_COMPOSITE_TSHELL.")


def _part_composite_tshell_layups(state: ConversionState) -> None:
    """*PART_COMPOSITE_TSHELL → a per-PART layup, when the part is thick-shell
    meshed.

    A ``*PART_COMPOSITE_TSHELL`` whose elements are NOT thick shells keeps the
    pre-existing warn-and-fall-back-to-a-plain-shell-property path: the layup
    would have nowhere to live, and the point of that path is that the part's
    mesh is never lost.
    """
    tshell_pids = _tshell_part_ids(state)
    for pid, pc in sorted(state.part_composites.items()):
        if pc.variant != "TSHELL" or pid not in tshell_pids:
            continue
        plies = [p for p in pc.plies if p.mid > 0 and p.thick > 0.0]
        if not plies:
            state.warn(
                f"*PART_COMPOSITE_TSHELL {pid}: no valid plies (every layer "
                "has MID<=0 or zero thickness), so no /PROP/TYPE22 is "
                "emitted. The part and its thick shells are still converted, "
                "on the section property — give at least one ply a positive "
                "MID and THICK.")
            continue
        state.tshell_layups[pid] = TshellLayup(
            pid=pid, title=pc.title or f"PART_{pid}",
            source="*PART_COMPOSITE_TSHELL", elform=pc.elform,
            shrf=pc.shrf, tshear=pc.tshear, plies=plies)
        if pc.tshear:
            state.warn(
                f"*PART_COMPOSITE_TSHELL {pid}: TSHEAR={pc.tshear} asks for a "
                "CONSTANT through-thickness transverse-shear distribution — "
                "DROPPED, because every Radioss thick shell uses the parabolic "
                "one. Stacked-element models come out slightly stiffer in shear "
                "than the deck asks for. (Card 3b puts TSHEAR in the column the "
                "thin-shell card 3a uses for THSHEL.)")
        if pc.irpl:
            state.warn(
                f"*PART_COMPOSITE_TSHELL {pid}: the OPTCARD IRPL={pc.irpl} "
                "through-thickness integration rule is DROPPED — a "
                "/PROP/TYPE22 layer carries ONE integration point at its own "
                "mid-plane (Ipos=0 auto-stacking), which is LS-DYNA's own "
                "default one-point trapezoidal rule but not IRPL=103's "
                "3-point Simpson.")
        if pc.optt:
            state.warn(
                f"*PART_COMPOSITE_TSHELL {pid}: the _CONTACT OPTT="
                f"{pc.optt:g} contact thickness is DROPPED (Radioss takes the "
                "contact gap from the /INTER card).")


def _resolve_tshells(state: ConversionState) -> None:
    """build_starter prepass: fold the per-element angles, resolve the per-part
    layups, and allocate their /PROP ids.

    Runs BEFORE ``_assign_composite_props`` (which must not also claim a
    thick-shell part), before ``_make_parts_and_elements`` (which repoints the
    /PART) and before ``_make_properties``.
    """
    if not state.tshell_elems and not state.sec_tshells:
        return
    _fold_tshell_beta(state)
    _elem_composite_layups(state)
    _part_composite_tshell_layups(state)
    for pid in sorted(state.tshell_layups):
        state.tshell_prop_ids[pid] = state.next_prop_id()


# ─────────────────────────────────────────────────────────────────────────────
# Property emitters
# ─────────────────────────────────────────────────────────────────────────────

_CARD3_HDR_IINT = ("#   Isolid    Ismstr                         Icstr     "
                   "Inpts      Iint                            Dn")
_CARD3_HDR_PLAIN = ("#   Isolid    Ismstr                         Icstr     "
                    "Inpts                                      Dn")
_QAQB_H_HDR = ("#                 qa                  qb"
               "                   h")
_QAQB_HDR = "#                 qa                  qb"
_B20, _B10 = " " * 20, " " * 10


def _card3(isolid: int, inpts: int, iint: Optional[int]) -> str:
    """Card 3 of all three properties, column-exact.

    ``prop_p20_tshell.cfg FORMAT(radioss2018)`` writes
    ``"%10d%10d                    %10d%10d%10d          %20lg"`` — Isolid
    1-10, Ismstr 11-20, TWENTY dead columns 21-40 (``Icpre`` lived there up to
    radioss140), Icstr 41-50, Inpts 51-60, Iint 61-70, ten blanks, Dn 81-100.
    TYPE21's card is the same minus the Iint slot, which it does not have at
    all (the starter hardcodes ``IINT = 1``).

    ``Ismstr`` is left 0 → the ``/DEF_SOLID`` chain → 4. It is emphatically NOT
    set to a total-strain 10/11/12: ``sgrtails.F:793`` refuses those on any
    thick shell, ``ERROR 3027 THICK-SHELL IS NOT COMPATIBLE WITH TOTAL STRAIN
    ISMSTR``. ``Dn`` is left 0 too — the starter zeroes it outright for
    Isolid=14 and defaults it to 0.1 for Isolid=15, so no value k2rad could
    write would survive either branch.
    """
    tail = f"{_i(iint)}{_B10}" if iint is not None else _B20
    return (f"{_i(isolid)}{_i(0)}{_B20}{_i(ICSTR_S)}{_i(inpts)}"
            f"{tail}{_f(0.0)}")


def _emit_prop_type20(prop_id: int, title: str, isolid: int, inpts: int,
                      istrain: int) -> List[str]:
    """/PROP/TYPE20 (TSHELL) — the ISOTROPIC thick shell.

    Layout from ``radioss2018/PROP/prop_p20_tshell.cfg FORMAT(radioss2018)``,
    which is what a ``/BEGIN 2022`` deck reads (the file's newer block is
    radioss2023, and there is no radioss2022 file at all). Confirmed against
    the starter by writing card 5 as ``20 blanks + "2"``: under the 2018 layout
    those columns are ``Istrain``, under 2023 they are ``vdef_min``, and the
    ``SOLID MINIMUM VOLUMETRIC STRAIN`` echo block the latter triggers did NOT
    print.

    ``Iint`` is written 0: it selects Gauss vs Lobatto for Isolid=16 only, and
    ``hm_read_prop20.F:195-197`` force-overwrites it to 1 for the 14 and 15 this
    converter emits. ``Istrain`` is equally inert here — ``hm_read_prop20.F:110``
    pins ``ISTRAIN = 1`` and the read at :126 is commented out — but it is
    carried anyway so the field says what the deck asked for, exactly as
    /PROP/SOLID does.
    """
    return [
        f"/PROP/TYPE20/{prop_id}",
        title,
        _CARD3_HDR_IINT,
        _card3(isolid, inpts, 0),
        _QAQB_H_HDR,
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#         DeltaT_min   Istrain",
        f"{_f(0.0)}{_i(istrain)}",
        HDR,
    ]


def _emit_prop_type21(prop_id: int, title: str, isolid: int, inpts: int,
                      axis: "_RefAxis", phi: float) -> List[str]:
    """/PROP/TYPE21 (TSH_ORTH) — the ORTHOTROPIC thick shell.

    Layout from ``radioss2018/PROP/prop_p21_tsh_orth.cfg
    FORMAT(radioss2018)``. Note three differences from TYPE20 that are easy to
    get wrong: there is no ``Iint`` column (cols 61-80 are dead), card 4 has no
    ``h`` column, and the deltaT_min card comes AFTER the ``Phi`` card rather
    than being the last field of it.

    ``Vx/Vy/Vz`` is a REFERENCE VECTOR, not a fibre direction: the starter
    projects it onto the element mid-plane and then rotates by ``Phi``
    (``scmorth3.F:185-199``). A vector that projects to nothing is refused PER
    ELEMENT — ``ERROR 526 REFERENCE DIRECTION IS ALMOST NORMAL TO THICK SHELL
    MID-SURFACE`` — and, unlike TYPE22, TYPE21 has NO zero-vector fallback
    (contrast ``hm_read_prop22.F:313-317``, which substitutes (1,0,0)). That is
    why the axis comes from ``_composite_ref_axis`` rather than dyna2rad's raw
    field copy, and why an ``Ip`` mode with no vector is written as a skew
    instead.

    ``Iorth`` stays 0: the angle is held constant with respect to the
    co-rotational frame, which is what an LS-DYNA material angle means.
    """
    return [
        f"/PROP/TYPE21/{prop_id}",
        title,
        _CARD3_HDR_PLAIN,
        _card3(isolid, inpts, None),
        _QAQB_HDR,
        f"{_f(0.0)}{_f(0.0)}",
        "#                 Vx                  Vy                  Vz"
        "   skew_ID     Iorth",
        f"{_f(axis.vec[0])}{_f(axis.vec[1])}{_f(axis.vec[2])}"
        f"{_i(axis.skew_id)}{_i(0)}",
        "#                Phi",
        _f(phi),
        "#         deltaT_min",
        _f(0.0),
        HDR,
    ]


def _emit_prop_type22(prop_id: int, title: str, isolid: int, inpts: int,
                      iint: int, axis: "_RefAxis",
                      layers: List[Tuple[float, float, int]],
                      ashear: float) -> List[str]:
    """/PROP/TYPE22 (TSH_COMP) — the LAYERED thick shell, one card per ply.

    Layout from ``radioss110/PROP/prop_p22_tsh_comp.cfg`` **FORMAT(radioss90)**
    — the newest block at or below 2022, since this file jumps straight from
    radioss90 to radioss2023. Getting that wrong matters: the 2023 block adds
    columns this reader would not expect.

    *layers* is ``(Phi, ti/t, mat_ID)`` bottom-first. Three constraints the
    caller must have satisfied, all hard-checked by the starter:

    * ``sum(ti/t)`` must land within 1% of 1.0 — ``hm_read_prop22.F:395-405``
      computes ``INT(sum*100)`` and raises **ERROR 675** unless it is 100 +/- 1.
    * ``1 <= NLY <= 200`` (**ERROR 27 / 28**), and ``NLY`` is derived from
      ``Icstr`` + the unpacked ``Inpts`` digits, or from ``Iint`` when the
      thickness digit is 0 — the >9-layer encoding.
    * every ``mat_IDi`` must resolve (**ERROR 676**).

    ``Zi`` is written 0 with ``Ipos = 0``, so the starter stacks the layers
    itself from the bottom: ``Z1 = -0.5 + t1/2`` and ``Zk = Z(k-1) + (tk +
    t(k-1))/2`` (``hm_read_prop22.F:429-433``). That is the #98 lesson applied
    to a thick shell — writing a quadrature SAMPLING coordinate into ``Zi``
    with ``Ipos = 1`` makes the starter derive the stack from the layer
    ENVELOPE and leaves gaps between the slabs.
    """
    lines = [
        f"/PROP/TYPE22/{prop_id}",
        title,
        _CARD3_HDR_IINT,
        _card3(isolid, inpts, iint),
        _QAQB_HDR,
        f"{_f(0.0)}{_f(0.0)}",
        "#                 Vx                  Vy                  Vz"
        "   skew_ID     Iorth      Ipos",
        f"{_f(axis.vec[0])}{_f(axis.vec[1])}{_f(axis.vec[2])}"
        f"{_i(axis.skew_id)}{_i(0)}{_i(0)}",
        "#             Ashear",
        _f(ashear),
        "#                Phi                ti/t                  Zi"
        "   mat_IDi",
    ]
    for (phi, frac, mat_id) in layers:
        lines.append(f"{_f(phi)}{_f(frac)}{_f(0.0)}{_i(mat_id)}")
    lines += ["#         DeltaT_min", _f(0.0), HDR]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Section → property
# ─────────────────────────────────────────────────────────────────────────────

def _section_parts(state: ConversionState, secid: int) -> List[int]:
    """Every *PART that REFERENCES this section, meshed or not.

    Not just the thick-shell ones: an element-free *PART still gets a /PART card
    pointing at the SECID, and a property has to exist there or the deck is
    starter ERROR 178 (``_element_free_part_ids`` counts a defined
    ``sec_tshells`` entry as resolved and hands out no placeholder)."""
    return sorted(pid for pid in state.parts
                  if _part_secid(state, pid) == secid)


def _warn_dropped_fields(state: ConversionState, sec: SectionTshell,
                         prop_type: int) -> None:
    """PROPT / QR / TSHEAR / SHRF — the *SECTION_TSHELL cells with no Radioss
    home. dyna2rad drops all four without a message."""
    notes = []
    if sec.shrf and prop_type != 22:
        notes.append(
            f"SHRF={sec.shrf:g} (transverse-shear scale) — /PROP/TYPE"
            f"{prop_type} has no shear column at all; only the composite "
            "TYPE22 does (Ashear), so the shear stiffness is Radioss's own")
    if sec.tshear:
        notes.append(
            f"TSHEAR={sec.tshear} (CONSTANT through-thickness transverse "
            "shear) — Radioss thick shells always use the parabolic "
            "distribution, so stacked-element models come out slightly "
            "stiffer in shear than the deck asks for")
    if sec.propt:
        notes.append(f"PROPT={sec.propt:g} (a printout option, no solver "
                     "meaning)")
    if sec.irid:
        notes.append(
            f"QR={sec.qr:g} references *INTEGRATION_SHELL rule {sec.irid} — a "
            "thick shell has no user quadrature rule in Radioss, so the layer "
            "positions and weights revert to the uniform Gauss stack; state "
            "the layup as ICOMP=1 or *PART_COMPOSITE_TSHELL to keep per-layer "
            "control")
    elif sec.qr == 1.0:
        notes.append("QR=1.0 (trapezoidal quadrature) — Radioss thick shells "
                     "integrate Gauss only")
    if notes:
        state.warn(f"*SECTION_TSHELL {sec.secid} → /PROP/TYPE{prop_type}. "
                   "Dropped: " + "; ".join(notes) + ".")


def _warn_elform(state: ConversionState, sec: SectionTshell,
                 isolid: int) -> None:
    from ..handlers import (_TSHELL_ELFORMS, _TSHELL_PLANE_STRESS_ELFORMS,
                            _TSHELL_REDUCED_ELFORMS)
    if sec.elform_blank:
        state.warn(
            f"*SECTION_TSHELL {sec.secid}: ELFORM is blank, which is LS-DYNA's "
            "default 1 (one-point reduced integration) → Isolid=15 (HSEPH). "
            "Note dyna2rad reads the blank as 0 and lands on the "
            "FULL-integration Isolid=14 instead, so a deck converted both ways "
            "will not match — this one follows the manual's default.")
    elif sec.elform not in _TSHELL_ELFORMS:
        state.warn(
            f"*SECTION_TSHELL {sec.secid}: ELFORM={sec.elform} is not a "
            "thick-shell formulation (the manual defines 1, 2, 3, 5, 6 and 7 — "
            f"there is no ELFORM 4). Converted as Isolid={isolid} like the "
            "non-default forms; check the deck, because an out-of-range ELFORM "
            "usually means the card was written for *SECTION_SOLID.")
    lost = []
    if sec.elform in _TSHELL_REDUCED_ELFORMS and isolid == 14:
        lost.append("its REDUCED integration (Isolid=14 is the "
                    "full-integration HA8; Radioss's under-integrated 15 is "
                    "HSEPH physical stabilization, not LS-DYNA's "
                    "assumed-strain enhancement, so it is not substituted)")
    if sec.elform in _TSHELL_PLANE_STRESS_ELFORMS:
        lost.append("its PLANE-STRESS treatment — ELFORM 1, 2 and 6 are "
                    "extruded thin shells with an uncoupled thickness-"
                    "direction stiffness (Vol I R16 p.3717 Remark 1), while "
                    "EVERY Radioss thick shell is a 3D-stress element, so the "
                    "part comes out stiffer through the thickness")
    if lost:
        state.warn(
            f"*SECTION_TSHELL {sec.secid}: ELFORM={sec.elform} loses "
            + "; and ".join(lost) + ".")


def _warn_mat_compat(state: ConversionState, secid: int, prop_type: int,
                     pids: List[int], nip: int, isolid: int) -> None:
    """The pre-starter ERROR 3046 / 3047 / WARNING 791 report for one
    thick-shell property, aggregated per (law, defect) rather than per part."""
    from .mesh import _target_mat_law
    accepted = _TSHELL_PROP_CLASSES[prop_type]
    noclass: Dict[int, List[int]] = {}
    wrongclass: Dict[int, List[int]] = {}
    law1_pids: List[int] = []
    for pid in pids:
        part = state.parts.get(pid)
        if part is None:
            continue
        law = _target_mat_law(state, part.mid)
        if law is None:
            continue        # no /MAT emitted at all — reported elsewhere
        if law == _LAW1:
            law1_pids.append(pid)
        if law in _NO_SOLID_CLASS_LAWS:
            noclass.setdefault(law, []).append(pid)
            continue
        cls = _SOLID_MAT_CLASS.get(law)
        if cls is not None and cls not in accepted:
            wrongclass.setdefault(law, []).append(pid)
    for law, plist in sorted(noclass.items()):
        state.warn(
            f"*SECTION_TSHELL {secid} → /PROP/TYPE{prop_type}: part(s) "
            f"{plist} carry /MAT/LAW{law}, which declares NO solid element "
            "class at all (it is a shell-only law). The starter refuses that "
            "one step before any property is looked at — ERROR 3046 "
            "'ELEMENTS OF TYPE ... ARE NOT COMPATIBLE WITH MATERIAL ID ...' "
            "(check_mat_elem_prop_compatibility.F) — so the deck will not "
            "start until the part gets a solid-capable material or is "
            "re-meshed as thin shells.")
    for law, plist in sorted(wrongclass.items()):
        cls = _SOLID_MAT_CLASS[law]
        state.warn(
            f"*SECTION_TSHELL {secid} → /PROP/TYPE{prop_type}: part(s) "
            f"{plist} pair it with /MAT/LAW{law}, whose PROP_SOLID class is "
            f"{cls}; TYPE{prop_type} accepts only "
            + "/".join(str(c) for c in sorted(accepted))
            + " (check_mat_elem_prop_compatibility.F:198-234), so the starter "
            "raises ERROR 3047 'PROPERTY ID ... IS NOT COMPATIBLE WITH "
            "MATERIAL ID ...'. "
            + ("Class 2 is SOLID_ORTHOTROPIC: give the material an AOPT so "
               "the section routes to the orthotropic /PROP/TYPE21 instead."
               if cls == 2 else
               "Class 5 is SOLID_POROUS, which only the isotropic TYPE20 "
               "takes — an ICOMP=1 or orthotropic-material thick shell cannot "
               "carry it."
               if cls == 5 else
               "Class 4 is SOLID_COHESIVE and class 7 SOLID_BRICK_ISOTROPIC; "
               "neither is legal on any thick shell."))
    if law1_pids and prop_type != 22 and nip != (2 if isolid == 15 else 222):
        state.warn(
            f"*SECTION_TSHELL {secid} → /PROP/TYPE{prop_type}: part(s) "
            f"{law1_pids} use /MAT/LAW1 (*MAT_ELASTIC), and the starter "
            "force-RESETS the through-thickness integration of a LAW1 thick "
            f"shell — sgrtails.F:694-704 sets Inpts to {'2' if isolid == 15 else '222'}"
            f" and raises WARNING 791, so the deck's NIP={nip // 10 % 10 if isolid == 14 else nip}"
            " is silently discarded (TYPE22 is exempt). Use a material with "
            "real through-thickness behaviour if the layer count matters.")


#: The #90 ``Ip`` modes a thick-shell property CAN express, and how.
#:
#: /PROP/TYPE21 and TYPE22 have no ``Ip`` column at all. Their whole orthotropy
#: input is ``Vx/Vy/Vz + skew_ID + Phi``, and ``scmorth3.F:126-134`` resolves it
#: to ONE vector::
#:
#:     IF (ISKV==0) THEN
#:       VX=GEO(7,IG) ; VY=GEO(8,IG) ; VZ=GEO(9,IG)     ! the Vx/Vy/Vz cells
#:     ELSE
#:       VX=SKEW(1,ISKV) ; VY=SKEW(2,ISKV) ; VZ=SKEW(3,ISKV)   ! the skew's X'
#:     ENDIF
#:
#: which is then PROJECTED onto the element mid-plane (``CASE (3)``, the branch
#: ``Icstr=010`` always selects) and rotated by ``Phi`` about the normal. So a
#: skew contributes exactly its first axis — the ``Ip=22`` semantic — and
#: ``skew_ID`` covers both the AOPT=2 and the AOPT<0 routes exactly.
_TSHELL_AXIS_SKEW_IPS = frozenset({0, 22})

#: LS-DYNA AOPT=3 defines material direction 1 as "the cross product of the
#: vector v with the element normal", rotated by BETA about that normal. For any
#: v, ``v x n`` equals ``proj(v)`` turned -90 degrees about n — the out-of-plane
#: part of v drops out of the cross product — so the exact thick-shell mapping
#: is ``V = v`` with ``Phi = BETA - 90``. (Orthotropy is symmetric under 180
#: degrees, so +90 would describe the same material axes; -90 is used because it
#: is the literal sign of the cross product.) dyna2rad copies v into Vx/Vy/Vz
#: and leaves Phi at 0, i.e. it converts an AOPT=3 material to axes rotated 90
#: degrees from the ones the deck states — directions 1 and 2 swapped.
_AOPT3_PHI_OFFSET = -90.0


def _tshell_axis(state: ConversionState, label: str, prop_id: int,
                 mids: List[int]):
    """The orthotropy reference system for a thick-shell property, from the
    FIRST orthotropic material among *mids*.

    Reuses the #90 ``_composite_ref_axis`` (``for_solid=True``, so the
    point-based AOPT 1 and 4 modes resolve rather than warn twice) and then
    TRANSLATES its ``Ip`` into what a thick-shell card can hold — see
    ``_TSHELL_AXIS_SKEW_IPS`` and ``_AOPT3_PHI_OFFSET``. Three modes have no
    thick-shell expression at all and fall back to global X with a warning:

    * ``Ip=20`` (AOPT=0, axes from element nodes 1/2/4). Radioss's own ``E1``
      IS that direction — ``scortho3.F:118-129`` builds it from the n1->n2 edge
      — but there is no way to SAY "use E1" on the card: the only input is a
      global vector, and a zero one is ERROR 526 per element.
    * ``Ip=21`` (AOPT=1, a reference point) and ``Ip=24`` (AOPT=4,
      cylindrical). Both are position-dependent; a thick shell takes one global
      direction.
    """
    for mid in mids:
        mat = (state.mat_orthotropic.get(mid)
               or state.mat_enhanced_composite.get(mid)
               or state.mat_aniso_visco.get(mid)
               or state.mat_honeycomb.get(mid))
        if mat is None:
            continue
        axis = _composite_ref_axis(mat, state, label, prop_id, for_solid=True)
        if axis.skew_id and axis.ip in _TSHELL_AXIS_SKEW_IPS:
            return _RefAxis(ip=axis.ip, vec=(0.0, 0.0, 0.0),
                            skew_id=axis.skew_id, phi=axis.phi,
                            lines=axis.lines,
                            note=(axis.note + " (on a thick shell the skew "
                                  "contributes its FIRST axis as the "
                                  "reference vector, scmorth3.F:131-133)")), mid
        if axis.ip == 23:
            return _RefAxis(ip=23, vec=axis.vec,
                            phi=axis.phi + _AOPT3_PHI_OFFSET, lines=axis.lines,
                            note=(axis.note + "; on a thick shell that cross "
                                  "product is expressed as the reference "
                                  "vector v with Phi shifted by "
                                  f"{_AOPT3_PHI_OFFSET:g} deg, because Radioss "
                                  "PROJECTS the vector onto the mid-plane "
                                  "instead of crossing it with the normal "
                                  "(dyna2rad copies v and leaves Phi at 0, so "
                                  "its axes come out 90 deg off)")), mid
        state.warn(
            f"{label}: the material's AOPT resolves to an element-local or "
            f"point-based system (#90 Ip={axis.ip}), which a thick-shell "
            "property cannot express — /PROP/TYPE21 and TYPE22 carry ONE "
            "global reference vector (projected onto the element mid-plane) "
            "plus an optional skew, and have no Ip column. The reference "
            "direction falls back to global X (1, 0, 0), so the fibre "
            "orientation is WRONG unless the mesh happens to align with it. "
            "State the material axes as AOPT=2 (vectors a/d), AOPT=3 (vector "
            "v) or a *DEFINE_COORDINATE system to carry them. (dyna2rad writes "
            "a ZERO vector for these modes, which the starter then refuses "
            "with ERROR 526 on EVERY element.)")
        return _RefAxis(ip=axis.ip, vec=(1.0, 0.0, 0.0), phi=axis.phi,
                        mapped=False, lines=axis.lines,
                        note=axis.note + " → global X fallback"), mid
    return None, 0


def _make_tshell_properties(state: ConversionState, istrain: int) -> List[str]:
    """Every /PROP/TYPE20|21|22 the deck needs, section props first.

    Section properties sit under the SECID VERBATIM — the /PROP/TYPE43 shape, so
    no /PART repoint is needed — while a per-part layup gets a synthesized id
    from ``state.tshell_prop_ids`` and the /PART is repointed at it.
    """
    from .mesh import _target_mat_law
    lines: List[str] = []
    tshell_pids = _tshell_part_ids(state)
    if not tshell_pids and not state.sec_tshells:
        return lines
    other_meshed = ({e.pid for e in state.shell_elems}
                    | {e.pid for e in state.solid_elems}
                    | {e.pid for e in state.beam_elems})
    unreferenced: List[int] = []
    wrong_family: List[int] = []
    for sec in sorted(state.sec_tshells.values(), key=lambda s: s.secid):
        ref_pids = _section_parts(state, sec.secid)
        here = [p for p in ref_pids if p in tshell_pids]
        if not ref_pids:
            # No *PART names it, so nothing would reference the property. Skip
            # it the way dyna2rad does (its converter is driven by the *PART
            # loop and never iterates sections at all): an ICOMP=1 section with
            # no part has no MATERIAL either, and a /PROP/TYPE22 whose mat_IDi
            # is 0 is starter ERROR 676.
            unreferenced.append(sec.secid)
            continue
        if not here and any(p in other_meshed for p in ref_pids):
            # A *PART on a *SECTION_TSHELL that carries SHELLS or ordinary
            # SOLIDS instead. That part's own family already auto-creates a
            # section under the SAME secid, and both properties would be
            # emitted under that id — starter ERROR 79, duplicate id. The
            # element family wins; this section is reported, not emitted.
            wrong_family.append(sec.secid)
            continue
        # A part with its own layup ignores the section property entirely; a
        # section ALL of whose thick-shell parts do would emit a property
        # nothing uses.
        pids = here or ref_pids
        live = [p for p in pids if p not in state.tshell_prop_ids]
        if not live:
            continue
        isolid = _tshell_isolid(sec.elform)
        _warn_elform(state, sec, isolid)
        inpts, _ = _tshell_inpts(isolid, sec.nip)
        if isolid == 15 and sec.nip > 9 and sec.icomp != 1:
            state.warn(
                f"*SECTION_TSHELL {sec.secid}: NIP={sec.nip} exceeds the 9 "
                "through-thickness points Radioss allows on the "
                "under-integrated Isolid=15 (hm_read_prop20.F, MSGID 563), so "
                "it is CLAMPED to 9. dyna2rad passes the raw value through and "
                "the starter refuses the deck.")
        mids = [state.parts[p].mid for p in (live or pids)
                if p in state.parts]
        laws = [ln for ln in (_target_mat_law(state, m) for m in mids)
                if ln is not None]
        ortho = any(_SOLID_MAT_CLASS.get(ln) == _ORTHO_SOLID_CLASS
                    for ln in laws)
        if sec.icomp == 1:
            prop_type = 22
        elif ortho:
            prop_type = 21
        else:
            prop_type = 20
        if ortho and prop_type == 21 and len(set(laws)) > 1:
            state.warn(
                f"*SECTION_TSHELL {sec.secid} is shared by parts with "
                "DIFFERENT materials, at least one of them orthotropic, so the "
                "whole section takes the orthotropic /PROP/TYPE21. That is the "
                "safe choice — TYPE21 also accepts isotropic laws (PROP_SOLID "
                "class 1) while TYPE20 REJECTS orthotropic ones (ERROR 3047) — "
                "but the reference direction comes from the first orthotropic "
                "material only. dyna2rad would emit a separate property per "
                "material; give each material its own *SECTION_TSHELL to get "
                "that here.")
        _warn_dropped_fields(state, sec, prop_type)
        _warn_mat_compat(state, sec.secid, prop_type, live or pids,
                         inpts, isolid)
        title = sec.title or f"PROP_{sec.secid}"
        fold = state.tshell_beta_fold.get(sec.secid, 0.0)
        if prop_type == 20:
            if fold:
                state.warn(
                    f"*SECTION_TSHELL {sec.secid}: the folded "
                    f"*ELEMENT_TSHELL_BETA angle {fold:g} deg is DROPPED — "
                    "the section's material is isotropic, so it converts to "
                    "the isotropic /PROP/TYPE20, which has no material "
                    "direction to rotate.")
            lines += _emit_prop_type20(sec.secid, title, isolid, inpts,
                                       istrain)
            continue
        label = f"/PROP/TYPE{prop_type} for *SECTION_TSHELL {sec.secid}"
        axis, src_mid = _tshell_axis(state, label, sec.secid, mids)
        if axis is None:
            axis = _RefAxis(ip=0, vec=(1.0, 0.0, 0.0),
                            note="no orthotropic material on the section")
        else:
            state.warn(
                f"*SECTION_TSHELL {sec.secid} → /PROP/TYPE{prop_type}: the "
                f"orthotropy reference direction is taken from material "
                f"{src_mid} — {axis.note}.")
        lines += list(axis.lines)
        if prop_type == 21:
            lines += _emit_prop_type21(sec.secid, title, isolid, inpts,
                                       axis, axis.phi + fold)
            continue
        # ICOMP=1: one layer per through-thickness integration point, angle
        # B_i, equal thickness. There is no per-layer MATERIAL on this card —
        # LS-DYNA's ICOMP states an ANGLE per point and nothing else — so every
        # layer carries the part's own MID, exactly as dyna2rad does.
        nply = max(1, min(sec.nip, 200))
        if sec.nip > 200:
            state.warn(
                f"*SECTION_TSHELL {sec.secid}: NIP={sec.nip} exceeds the 200 "
                "layers a /PROP/TYPE22 can hold (hm_read_prop22.F:120, "
                "ERROR 28), so the stack is TRUNCATED to the bottom 200 — the "
                "laminate is thinner than the deck's.")
        betas = (sec.betas + [0.0] * nply)[:nply]
        mat_id = mids[0] if mids else 0
        isolid, inpts, iint = _tshell_layer_encoding(
            state, isolid, nply, f"*SECTION_TSHELL {sec.secid} (ICOMP=1)")
        lines += _emit_prop_type22(
            sec.secid, title, isolid, inpts, iint, axis,
            [(betas[k] + axis.phi + fold, 1.0 / nply, mat_id)
             for k in range(nply)],
            sec.shrf if 0.0 < sec.shrf <= 1.0 else 0.0)
        state.warn(
            f"*SECTION_TSHELL {sec.secid}: ICOMP=1 → /PROP/TYPE22 with {nply} "
            f"layer(s) of equal thickness (ti/t = {1.0 / nply:g}), angles "
            + ", ".join(f"{betas[k] + axis.phi + fold:g}" for k in range(nply))
            + f" deg, all on material {mat_id}. LS-DYNA's ICOMP states one "
            "ANGLE per integration point and nothing else — no per-layer "
            "material and no per-layer thickness — so a genuinely "
            "heterogeneous laminate needs *PART_COMPOSITE_TSHELL instead.")
    if unreferenced:
        state.note_recognized_not_emitted(
            "SECTION_TSHELL",
            "section(s) " + ", ".join(str(s) for s in unreferenced)
            + " are referenced by no *PART, so no /PROP is written for them "
            "(dyna2rad never converts an unreferenced *SECTION either — its "
            "property converter is driven by the *PART loop). Nothing in the "
            "deck can point at them, so nothing is lost.")
    if wrong_family:
        state.warn(
            "*SECTION_TSHELL " + ", ".join(str(s) for s in wrong_family)
            + " is referenced by *PART(s) whose elements are SHELLS or "
            "ordinary SOLIDS, not thick shells. Those parts get the property "
            "their own element family needs, under the same id, so the "
            "thick-shell property is NOT emitted — writing both would be two "
            "/PROP cards on one id (starter ERROR 79). Check the *PART's SECID "
            "if the elements were meant to be *ELEMENT_TSHELL.")
    lines += _emit_tshell_layup_props(state)
    return lines


def _emit_tshell_layup_props(state: ConversionState) -> List[str]:
    """The per-part /PROP/TYPE22 of a *PART_COMPOSITE_TSHELL or a uniform
    *ELEMENT_TSHELL_COMPOSITE stack."""
    from .composites import _mid_is_known
    lines: List[str] = []
    for pid in sorted(state.tshell_layups):
        layup = state.tshell_layups[pid]
        prop_id = state.tshell_prop_ids[pid]
        secid = _part_secid(state, pid)
        sec = state.sec_tshells.get(secid) or auto_section_tshell(secid)
        # ELFORM comes from the layup's own card when it has one
        # (*PART_COMPOSITE_TSHELL card 3b), else from the section.
        elform = layup.elform if layup.elform > 0 else sec.elform
        isolid = _tshell_isolid(elform)
        nply = len(layup.plies)
        if nply > 200:
            state.warn(
                f"{layup.source} {pid}: {nply} layers exceed the 200 a "
                "/PROP/TYPE22 can hold (hm_read_prop22.F:120, ERROR 28), so "
                "the stack is TRUNCATED to the bottom 200 — the laminate is "
                "thinner than the deck's. Merge plies of the same material.")
            layup.plies = layup.plies[:200]
            nply = 200
        total = sum(p.thick for p in layup.plies)
        isolid, inpts, iint = _tshell_layer_encoding(
            state, isolid, nply, f"{layup.source} {pid} (ELFORM={elform})")
        label = f"/PROP/TYPE22 for {layup.source} {pid}"
        axis, src_mid = _tshell_axis(state, label, prop_id,
                                     [p.mid for p in layup.plies])
        if axis is None:
            axis = _RefAxis(ip=0, vec=(1.0, 0.0, 0.0),
                            note="no orthotropic ply material")
        lines += list(axis.lines)
        # ti/t is a FRACTION of the element's geometric thickness, and the
        # starter checks INT(sum*100) against 100 +/- 1 (ERROR 675). Normalising
        # by the real sum is what LS-DYNA does too on a thick shell ("the THICKi
        # are also scaled to conform to the geometry", Vol I R16 p.3529).
        #
        # A folded *ELEMENT_TSHELL_BETA rides on top of every layer angle, the
        # same composition the manual states for the layup case (Remark 4:
        # theta_i = beta + beta_i) and the same one the section path applies.
        fold = state.tshell_beta_fold.get(secid, 0.0)
        layers = [(p.beta + axis.phi + fold, p.thick / total, p.mid)
                  for p in layup.plies]
        lines += _emit_prop_type22(
            prop_id, (layup.title or f"TSHELL_LAYUP_{pid}")[:100],
            isolid, inpts, iint, axis, layers,
            layup.shrf if 0.0 < layup.shrf <= 1.0 else 0.0)
        state.warn(
            f"{layup.source} {pid}: per-ply layup → /PROP/TYPE22/{prop_id} "
            f"with {nply} layer(s) (Isolid={isolid}, ti/t from "
            f"THICKi/{total:g}"
            + (f", axes from ply material {src_mid}" if src_mid else "")
            + "). The part is repointed at it and its *SECTION_TSHELL "
            "property is no longer used."
            + (" dyna2rad routes *PART_COMPOSITE_TSHELL through its THIN-shell "
               "handler and emits /PROP/TYPE51 + /PROP/TYPE19, which its own "
               "starter then refuses on the bricks (ERROR 60 INVALID PROPERTY "
               "ID ... FOR BRICK ELEMENT, ERROR 226 WRONG SOLID PROPERTY TYPE "
               "51)." if layup.source == "*PART_COMPOSITE_TSHELL" else ""))
        for mid in sorted({p.mid for p in layup.plies}):
            if not _mid_is_known(state, mid):
                state.warn(
                    f"{layup.source} {pid}: ply material {mid} is NOT emitted "
                    "as a /MAT by this conversion — either the deck defines no "
                    "*MAT with that id, or its law is one k2rad does not "
                    "convert. The /PROP/TYPE22 mat_IDi will dangle and the "
                    "starter rejects the property (ERROR 676 WRONG MATERIAL "
                    "ID DEFINED).")
    return lines
