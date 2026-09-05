"""Starter SPH particles: ``*ELEMENT_SPH`` → ``/SPHCEL`` and ``*SECTION_SPH``
→ ``/PROP/SPH`` (TYPE34), plus ``*CONTROL_SPH`` → ``/SPHGLO``.

======================================  ======================================
LS-DYNA                                 Radioss
======================================  ======================================
``*ELEMENT_SPH`` (+ ``_VOLUME``)        ``/SPHCEL/<part_ID>``, one row per cell
``*SECTION_SPH`` (+ 4 option spellings) ``/PROP/SPH`` (= ``/PROP/TYPE34``)
``*CONTROL_SPH`` NMNEIGH                ``/SPHGLO`` Lneigh / Nneigh
``*DATABASE_HISTORY_SPH[_SET]``         ``/TH/SPHCEL`` (writer/output.py)
======================================  ======================================

An SPH particle has NO CONNECTIVITY: the LS-DYNA card is ``NID PID MASS`` and
the particle IS its supporting node. Radioss states the same identity twice
over (``hm_read_sphcel.F:243-250``: the single id column is read as the NODE
user id, then "same identifier as the node" sets the cell id to it), so nothing
here renumbers a cell independently of a node — and the ``*INCLUDE_TRANSFORM``
offset spec gives field 0 the NODE bucket for the same reason.

**Mass is the correctness criterion of this batch**, and Radioss offers exactly
two places to put it, which are mutually exclusive because the one that carries
the mass also decides the smoothing length (``spinih.F:85-109``,
``spinit3.F:139-153``):

* per-cell — every ``/SPHCEL`` row states its own Flag+MASS. Mass exact per
  particle, whatever the deck says; ``h`` is then OVERWRITTEN per particle with
  ``(sqrt(2)*m_p/rho)^(1/3)`` and the deck's own ``SPHINI``/``CSLH`` cannot be
  honoured at all.
* per-property — the MASS column is left blank ("type 0"), every particle takes
  ``Mp`` from ``/PROP/SPH``, and the property's ``h`` is used verbatim. Total
  mass is ``N * Mp``, which is exact whenever the deck's particles all carry the
  IDENTICAL mass — and then ``h`` is exact too.

``_resolve_sph`` picks the second route when it is provably safe and the first
otherwise, reporting either way. That ordering is the fidelity ordering measured
at ``/BEGIN 2022``, and it is the one place this module deliberately outranks
dyna2rad's "copy the cell mass and move on".

Seven deliberate divergences from dyna2rad, every one of them a measured defect
on its side:

1. **``Mp`` is always written positive.** dyna2rad never sets the field, so
   ``hm_read_prop34.F:235-239`` raises WARNING 138 on EVERY converted SPH deck
   and forces ``MP = 1`` in the deck's mass unit. Harmless while the cells carry
   mass; catastrophic without — measured, four blank-mass particles gave
   ``TOTAL MASS = 4.000000000000``.
2. **The LS-DYNA card defaults are applied by the parser**: ``CSLH = 1.2``,
   ``HMIN = 0.2``, ``HMAX = 2.0``, ``DEATH = 1e20``. The CFG declares them and
   the SDI read path does not apply them, so dyna2rad sees a blank ``CSLH`` as 0
   and takes the ``else`` of ``lsdCSLH > 0`` — turning the commonest deck there
   is (blank CSLH = "use 1.2") into a CONSTANT smoothing length with ``SPHINI``
   discarded. Verified on probe decks h and i.
3. **``h_1D = 3`` and the ``hmin``/``hmax``/``hcst`` cells are NEVER emitted.**
   They live on a ``radioss2026``-only third card. At ``/BEGIN 2022`` a reader
   discards them SILENTLY — measured ``hmin=0.37 hmax=3.77 hcst=1.77`` echoed as
   ``0.2 / 2.0 / 1.2``, ``0 ERROR(S)``, only advisory ``WARNING 100213`` — while
   ``h_1D = 3`` on card 1 IS accepted, so the deck would run the bounded
   dilatation algorithm with bounds nobody chose. dyna2rad writes exactly that
   combination on its ``CSLH <= 0`` branch (and targets ``"hcst"``, which is not
   an attribute of the property at all — the real name is ``h_scal``, so the
   value is silently discarded even at 2026).
4. **``ORDER`` stays 0.** dyna2rad maps ``SPHKERN == 2 → ORDER = 2``. Radioss's
   ``Order`` is the renormalisation CORRECTION order, not a kernel-polynomial
   order, and 2 is out of range: ``spcompl.F:107-118`` dispatches only on
   -1/0/1, so such a particle gets no kernel correction at all, and
   ``spgrhead.F:180-185`` packs the value into two bits of the group-sort key.
   (Unreachable on its side anyway — the R11.1 IMPORT card reads seven fields,
   so ``SPHKERN`` is never populated. Verified: ``FORMULATION CORRECTION
   ORDER = 0``.)
5. **``*HOURGLASS`` / ``*CONTROL_HOURGLASS`` never reach ``h``.** dyna2rad
   copies ``QM``/``QH`` into the ``/PROP/SPH`` field named ``"h"`` — a
   dimensionless hourglass viscosity into a LENGTH. SPH has no hourglass modes
   and the property has no hourglass field; it is a straight name collision.
   Measured: a part ``*HOURGLASS QM=0.13`` with ``SPHINI=0.5`` echoed
   ``SMOOTHING LENGTH = 0.13``, and a global ``*CONTROL_HOURGLASS QH=0.07``
   ZEROED the smoothing length outright (its attribute is ``LSD_QH``, which the
   identifier ``"QH"`` does not resolve, so an empty value is written).
6. **``MASS < 0`` is a VOLUME and the ``_VOLUME`` suffix means the same thing**
   — both become ``/SPHCEL`` Type 2. dyna2rad honours neither: measured,
   ``MASS = -2e-6`` gave ``TOTAL MASS = 8.0 kg`` instead of ``0.016`` (the
   starter discards the negative and the fabricated ``Mp = 1`` takes over), and
   an ``*ELEMENT_SPH_VOLUME`` block came out wrong by exactly rho.
7. **``NEND`` is expanded** into one particle per id in the range. Neither
   dyna2rad nor OpenRadioss's own native ``.k`` reader does it — measured,
   ``NUMSPH = 1`` where the card asks for a cloud.

One MATERIAL is re-routed rather than only reported. ``*MAT_PLASTIC_KINEMATIC``
lands on ``/MAT/LAW44``, which ``hm_read_mat44.F`` does not declare for SPH — so
a particle on it is **ERROR 3046** and the deck is refused, as two r14 decks
LS-DYNA runs were. ``/MAT/LAW2`` IS declared and describes the identical curve
whenever there is no Cowper-Symonds rate term and no EFFECTIVE kinematic
hardening; ``_resolve_sph_materials`` moves the particle parts onto it, cloning
the ``/MAT`` when shells or solids share the material. Anything not expressible
keeps LAW44 and keeps the loud report: a different constitutive law is never
substituted silently.

What is dropped, and said so: the anisotropic ``_ELLIPSE`` smoothing lengths,
``DEATH``/``START`` (no per-property activation window in Radioss),
``SPHKERN != 0``, ``HMIN``/``HMAX`` other than the exact ``1/1`` constant-h
case, and every ``*CONTROL_SPH`` column but ``NMNEIGH`` — each named
individually by ``_warn_control_sph``.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Set, Tuple

from ..state import ConversionState, SectionSph, SphCell, SphProp
from .common import HDR, _f, _i

__all__ = [
    "_resolve_sph",
    "_sph_part_ids",
    "_make_sph_properties",
    "_emit_sphcel_block",
    "_make_sphglo",
    "auto_section_sph",
]


# ─────────────────────────────────────────────────────────────────────────────
# Material-law compatibility — the /PROP/SPH analogue of tshell's
# _SOLID_MAT_CLASS table
# ─────────────────────────────────────────────────────────────────────────────
#
# Radioss gates SPH on a per-law SELF-DECLARATION rather than on a class number:
# a law reaches ``MATPARAM%PROP_SPH = 1`` only by calling
# ``INIT_MAT_KEYWORD(..., "SPH")`` (``init_mat_keyword.F:272-273``, "Compatibility
# with /PROP/TYPE 34"). ``check_mat_elem_prop_compatibility.F`` then refuses
# anything else twice over — ``CASE (51)`` (the SPH element type) raises
# **ERROR 3046** when ``PROP_SPH == 0``, and ``CASE (34)`` (the SPH property)
# raises **ERROR 3047**.
#
# PROVENANCE: extracted 2026-08-20 from the OpenRadioss 2026-05-20 starter tree
# by ``grep -rin 'init_mat_keyword(.*"SPH"' starter/source/materials/mat/``,
# which is the complete and only way a law joins the set.
#
# This IS the hand-maintained table that ``_mat_density`` two functions below
# refuses to write, and the divergence is deliberate: the two tables fail in
# opposite directions. A density read from a stale list is a WRONG NUMBER in
# the deck; a law missing from a stale list is one spurious warning about a
# starter error that then does not happen — cheap, visible, and self-correcting
# the moment anyone runs the deck. Re-run the grep above after any material
# batch that adds laws (the next one is queued in ROADMAP.md).
#
# dyna2rad imposes NO law filter of its own — its ``GetComponentType`` does
# classify SPH parts, but the only two call sites are a MAT_100 spotweld test
# and a computed-then-unused local — so an SPH part there is converted exactly
# as if it sat on a solid and the starter is the first to object.
_SPH_COMPATIBLE_LAWS = frozenset({
    0, 1, 2, 3, 4, 5, 6, 10, 12, 13, 14, 21, 22, 23, 24, 28, 33, 34,
    35, 36, 38, 40, 41, 42, 49, 66, 70, 72, 75, 79, 81, 93, 97, 102, 103, 105,
    106, 109, 121, 126, 128, 129, 131, 133, 163,
} | {
    # /MAT/USER1..3. No ``mat029``/``mat030``/``mat031`` directory exists, so
    # there is no INIT_MAT_KEYWORD call to read and no way to know what a user
    # law declares. Deliberately PERMISSIVE — all three, not a subset — because
    # the alternative is warning about a starter error k2rad cannot predict.
    29, 30, 31,
})

#: ``spinih.F:85-95`` — Radioss derives a mass-carrying particle's smoothing
#: length as ``h = (sqrt(2) * m_p / rho)^(1/3)``. The sqrt(2) is exactly the FCC
#: packing factor, i.e. Radioss's h equals the nearest-neighbour distance of an
#: ideal close-packed fill. Numerically confirmed against a live starter: with
#: m = 0.002, rho = 1000 the ratio of two runs' time steps
#: (3.5700719306875E-06 / 3.1050391479609E-06 = 1.149769) matched the h ratio
#: 0.0141421 / 0.0123 exactly, ruling out the ``(m/2rho)^(1/3)`` reading that
#: some renderings of the Altair help card show.
_SQRT2 = math.sqrt(2.0)


def _f_mass(v: float, w: int = 20) -> str:
    """A particle MASS field, written so it reads back as the number it is.

    ``common._f`` renders anything below 1e-4 with ``%.6E`` — seven significant
    digits — and in Mg-mm-s EVERY SPH particle mass is below 1e-4. Measured: a
    deck stating ``m = 1.234567891E-09`` on 1000 particles came back from the
    starter as ``TOTAL MASS = 1.2345680000000E-06`` against the exact
    1.234567891E-06, a +8.8e-06 % deviation — small in engineering terms, but
    mass is this batch's stated correctness criterion and the warnings call the
    Route-A total "exact". The field is twenty characters wide and ``%.6E``
    fills twelve, so the digits were lost to the FORMATTER, not to the column.

    ``common._f`` itself is left alone: it formats every float in every deck
    the converter writes, and widening it there would rewrite the whole corpus
    to buy precision that only the two SPH mass columns need.

    The shortest decimal that round-trips is preferred (so ``9.683426e-05``
    stays ``9.683426E-05`` rather than growing a tail of zeros), with ``%.13E``
    — 14 significant digits, and at most 20 characters for a positive value —
    as the fallback. Both mass columns are positive by construction.
    """
    if v == 0.0:
        return _f(0.0, w)
    s = repr(float(v)).upper()
    if len(s) > w:
        s = f"{v:.13E}"
    if len(s) > w:
        return _f(v, w)
    return s.rjust(w)


def _radioss_h(mass: float, rho: float) -> float:
    """``h = (sqrt(2) * m_p / rho)^(1/3)`` — what Radioss uses for any particle
    that carries its own mass, whatever the property says."""
    if mass <= 0.0 or rho <= 0.0:
        return 0.0
    return (_SQRT2 * mass / rho) ** (1.0 / 3.0)


def _sph_part_ids(state: ConversionState) -> Set[int]:
    """*PART ids that own at least one SPH particle."""
    return {c.pid for c in state.sph_elems}


def _part_secid(state: ConversionState, pid: int) -> int:
    part = state.parts.get(pid)
    if part is None:
        return pid
    return part.secid if part.secid > 0 else pid


def auto_section_sph(secid: int) -> SectionSph:
    """The default *SECTION_SPH k2rad synthesizes when an SPH *PART's SECID has
    no card — LS-DYNA's own defaults throughout (CSLH 1.2, HMIN 0.2, HMAX 2.0,
    DEATH 1e20), which is what the manual says a blank card means."""
    return SectionSph(secid, f"AutoPropSph_{secid}", cslh_blank=True)


def _mat_density(state: ConversionState, mid: int) -> float:
    """The density of LS-DYNA material *mid*, or 0.0 when it is not known.

    Scans every ``mat_*`` container generically rather than listing them: the
    density is wanted only for REPORTING (the h ratio below) and for the
    volume→mass conversion of a Type-2 cell, and a hand-written list of ~60
    material dicts is exactly the kind of table that falls behind the next
    material batch. Both ``rho`` and ``ro`` spellings occur in the state
    dataclasses.

    A material whose density was SUBSTITUTED by the zero-density floor
    (``state.zero_density_floored``) reports 0.0 here, deliberately: that
    material states no usable density, and letting the particle-mass
    fabrication compute ``rho x V`` from ``1e-24`` would replace a LOUD
    "MASS INVENTED ... a bare unit mass" warning with a silent 1e-21 that
    looks measured. The floor exists to clear starter ERROR 683 on the /MAT
    card, not to answer this question.
    """
    if mid in state.zero_density_floored:
        return 0.0
    for name, container in vars(state).items():
        if not name.startswith("mat_") or not isinstance(container, dict):
            continue
        mat = container.get(mid)
        if mat is None:
            continue
        for attr in ("rho", "ro"):
            v = getattr(mat, attr, None)
            if isinstance(v, (int, float)) and v > 0.0:
                return float(v)
    return 0.0


def _section_parts(state: ConversionState, secid: int) -> List[int]:
    """Every *PART that REFERENCES this section, meshed or not.

    Not just the SPH ones: an element-free *PART still gets a /PART card
    pointing at the SECID, and a property has to exist there or the deck is
    starter ERROR 178."""
    return sorted(pid for pid in state.parts
                  if _part_secid(state, pid) == secid)


# ─────────────────────────────────────────────────────────────────────────────
# Prepass
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_sph(state: ConversionState) -> None:
    """build_starter prepass: screen the particles, split a shared SECID, and
    decide each section's mass/smoothing-length route.

    Runs BEFORE ``_make_parts_and_elements`` (which emits the /SPHCEL rows and
    repoints the /PART) and before ``_make_properties`` (which emits the
    /PROP/SPH), and AFTER ``_screen_provisional_elements`` so the census sees the
    final particle list.
    """
    # *CONTROL_SPH is reported unconditionally. Its columns are dropped whether
    # or not the particles reached the state, and IDIM — the one column
    # _warn_control_sph itself calls answer-changing rather than accuracy-
    # changing — is exactly the thing a user needs told when an *INCLUDE did
    # not resolve and the cloud is missing.
    _warn_control_sph(state)
    if not state.sph_elems and not state.sec_sph:
        return
    _screen_sph_cells(state)
    _autocreate_sph_sections(state)
    _split_mixed_family_sections(state)
    _resolve_sph_materials(state)
    _resolve_sph_props(state)


def _screen_sph_cells(state: ConversionState) -> None:
    """Drop the particles Radioss would refuse, and say how many.

    Two hard starter refusals, both measured:

    * a ``/SPHCEL`` id with no ``/NODE`` is **ERROR 78** ``UNDEFINED NODE NUMBER
      / IN SPH CONNECTIVITIES DEFINITION``;
    * the same id twice is **ERROR 79** ``DUPLICATE ID / IN SPH CONNECTIVITIES
      DEFINITION`` (``hm_read_sphcel.F:444``, ``UDOUBLE``).

    Both are refusals of the WHOLE DECK, so screening here trades a named,
    counted loss for a run that does not start at all. The NEND-generated ids
    are counted separately: a generated range routinely overshoots the node
    cloud by design, so those are expected and are reported as such rather than
    as a defect in the deck.
    """
    if not state.sph_elems:
        return
    nodes = state.nodes
    kept: List[SphCell] = []
    seen: Set[int] = set()
    no_node_written: List[int] = []
    no_node_generated = 0
    duplicates: List[int] = []
    for c in state.sph_elems:
        if c.nid not in nodes:
            if c.generated:
                no_node_generated += 1
            else:
                no_node_written.append(c.nid)
            continue
        if c.nid in seen:
            duplicates.append(c.nid)
            continue
        seen.add(c.nid)
        kept.append(c)
    state.sph_elems = kept
    if no_node_written:
        shown = ", ".join(str(n) for n in no_node_written[:12])
        if len(no_node_written) > 12:
            shown += f", ... ({len(no_node_written)} particles)"
        state.warn(
            f"MESH LOSS: {len(no_node_written)} *ELEMENT_SPH particle(s) name a "
            f"NID that no *NODE card defines — {shown}. A /SPHCEL id IS its "
            "supporting node id, so listing one Radioss cannot resolve is "
            "starter ERROR 78 (UNDEFINED NODE NUMBER IN SPH CONNECTIVITIES "
            "DEFINITION) and the deck is refused outright; they are DROPPED "
            "instead, so the run starts with that much less mass. Check for a "
            "missing *NODE block or an *INCLUDE that did not resolve.")
    if no_node_generated:
        state.warn(
            f"*ELEMENT_SPH: {no_node_generated} particle(s) generated by a NEND "
            "range have no *NODE and were dropped. A generated range names "
            "every id between NID and NEND whether or not the node cloud is "
            "contiguous, so some overshoot is normal — but if the number is "
            "large, check that NEND really is the last node of the fill.")
    if duplicates:
        shown = ", ".join(str(n) for n in sorted(set(duplicates))[:12])
        state.warn(
            f"*ELEMENT_SPH: {len(duplicates)} particle(s) repeat a NID already "
            f"used by another particle — {shown}. Radioss indexes an SPH cell "
            "BY its node, so two cells on one node is starter ERROR 79 "
            "(DUPLICATE ID IN SPH CONNECTIVITIES DEFINITION) and the deck is "
            "refused; the FIRST card of each id is kept and the rest are "
            "DROPPED. In LS-DYNA the later card would simply have overwritten "
            "the earlier one, so check which mass was meant.")


def _autocreate_sph_sections(state: ConversionState) -> None:
    """A *PART that owns particles but names no *SECTION_SPH gets a placeholder.

    Without one the /PART would point at a property id nothing defines —
    starter ERROR 178 — or fall through to the element-free placeholder
    /PROP/SHELL, which is starter ERROR 226 under a /SPHCEL.
    """
    missing: Set[int] = set()
    for pid in sorted(_sph_part_ids(state)):
        # Only a REAL *PART: an orphaned particle (no *PART card) is reported by
        # _warn_orphan_elements and emitted nowhere, so synthesizing a section
        # for it would leave a /PROP/SPH nothing references.
        if pid not in state.parts:
            continue
        secid = _part_secid(state, pid)
        if secid and secid not in state.sec_sph:
            missing.add(secid)
    if not missing:
        return
    for secid in sorted(missing):
        state.sec_sph[secid] = auto_section_sph(secid)
    state.warn(
        "*ELEMENT_SPH particle(s) reference section id(s) "
        + ", ".join(str(s) for s in sorted(missing))
        + " that no *SECTION_SPH card defines, so a PLACEHOLDER SPH property "
        "was created for each, carrying LS-DYNA's own defaults (CSLH 1.2, "
        "HMIN 0.2, HMAX 2.0). Without it the /PART would reference a property "
        "that does not exist (starter ERROR 178) or inherit the element-free "
        "placeholder /PROP/SHELL, which a /SPHCEL cannot run on. Add the "
        "*SECTION_SPH if the smoothing length matters.")


def _split_mixed_family_sections(state: ConversionState) -> None:
    """A *SECTION_SPH shared by SPH parts AND by shell/solid/thick-shell/beam
    parts gets its SPH property moved to a SYNTHESIZED id, with those parts
    repointed at it.

    Two /PROP cards cannot share one id — starter ``ERROR ID : 79 DUPLICATE ID
    / IN PID DEFINITION``. This is the thick-shell batch's ``#120`` review-round
    lesson applied to a fifth SECID-keyed property namespace; the SPH case is
    if anything more likely, because ``*SECTION_SPH`` SECIDs in the corpus are
    small round numbers (2, 101) that a *SECTION_SHELL happily reuses.

    Two ways the id can already be taken, and BOTH move the SPH property:

    * another family's MESHED *PART sits on the same SECID, so that family
      auto-creates its own section under the id;
    * another family's ``*SECTION_*`` CARD already claims the id, whether or
      not any part references it. An unreferenced or element-free
      ``*SECTION_SHELL`` still reaches ``_make_properties`` and still emits
      ``/PROP/SHELL/<secid>`` — measured on all four other meshed families,
      ``['/PROP/SHELL/5', '/PROP/SPH/5']`` with no diagnostic at all. That
      second test is what the thick-shell batch's own split does not make, so
      the same hole exists there (``*SECTION_SOLID 2`` + an unreferenced
      ``*SECTION_SHELL 2``); the deck-wide scan in
      ``assembly._warn_duplicate_prop_ids`` is the net under all of them.

    Runs in the prepass because ``_make_parts_and_elements`` reads
    ``sph_prop_ids`` to repoint the /PART, long before the card is written.
    """
    sph_pids = _sph_part_ids(state)
    if not sph_pids:
        return
    other_meshed = ({e.pid for e in state.shell_elems}
                    | {e.pid for e in state.solid_elems}
                    | {e.pid for e in state.tshell_elems}
                    | {e.pid for e in state.beam_elems})
    other_secids = (set(state.sec_shells) | set(state.sec_solids)
                    | set(state.sec_tshells) | set(state.sec_beams))
    for secid in sorted(state.sec_sph):
        ref_pids = _section_parts(state, secid)
        here = sorted(p for p in ref_pids if p in sph_pids)
        others = sorted(p for p in ref_pids
                        if p in other_meshed and p not in sph_pids)
        card = secid in other_secids
        if not here or not (others or card):
            continue
        prop_id = state.next_prop_id()
        state.sph_section_prop_ids[secid] = prop_id
        for p in here:
            state.sph_prop_ids[p] = prop_id
        claim = (f"part(s) {others} that carry shells, solids, thick shells or "
                 "beams" if others else
                 "a *SECTION_SHELL / _SOLID / _TSHELL / _BEAM card of the same "
                 "id, which emits its own /PROP whether or not a *PART "
                 "references it")
        state.warn(
            f"*SECTION_SPH {secid} is shared by SPH part(s) {here} AND by "
            f"{claim}. Both families need a /PROP and only one can own the "
            f"SECID, so the SPH property is emitted as /PROP id {prop_id} and "
            f"part(s) {here} are repointed at it. Writing both under {secid} "
            "would be starter ERROR 79 (DUPLICATE ID IN PID DEFINITION). Give "
            "the particles their own *SECTION_SPH to control the id.")


def _resolve_sph_materials(state: ConversionState) -> None:
    """Give an SPH part an SPH-CAPABLE material where the deck's own choice is
    not one and the difference is expressible.

    Exactly one case today: ``*MAT_PLASTIC_KINEMATIC`` → ``/MAT/LAW44``, which
    ``hm_read_mat44.F`` does not declare for SPH. The starter answers a particle
    on it with **ERROR 3046** and refuses the whole deck — measured on
    ``sph/bar-i/bar1.k`` and ``sph/bar-ii/bar2.k``, two r14 decks LS-DYNA runs.

    ``/MAT/LAW2`` is SPH-declared and, whenever the material carries no
    Cowper-Symonds rate term and no EFFECTIVE kinematic hardening, describes
    the identical curve (``a = SIGY``, ``b = E*ETAN/(E-ETAN)``, ``n = 1``). So:

    * every part on the material is SPH → it is simply written as LAW2;
    * some parts carry shells or solids, which still need LAW44 → a CLONE is
      allocated and only the SPH parts are repointed at it. Both corpus decks
      are this shape (MID 1 serves solid parts 1, 2 AND particle parts 101,
      102), which is why an "SPH-only material" rule alone would not have
      helped either of them.

    A material that is NOT expressible keeps LAW44 and keeps
    :func:`_warn_mat_compat`'s ERROR-3046 report: a loud refusal is the right
    answer when the alternative is a different constitutive law.
    """
    if not state.mat_plas_kin:
        return
    from .materials import _plas_kin_law2_expressible, _sph_only_mid
    sph_pids = _sph_part_ids(state)
    if not sph_pids:
        return
    for mid in sorted(state.mat_plas_kin):
        mat = state.mat_plas_kin[mid]
        here = sorted(pid for pid in sph_pids
                      if (p := state.parts.get(pid)) is not None
                      and p.mid == mid)
        if not here or _sph_only_mid(state, mid):
            continue                    # nothing to clone; the emitter decides
        if not _plas_kin_law2_expressible(mat):
            continue                    # keeps LAW44 + the ERROR-3046 warning
        # next_mat_id() draws from the MONOTONIC next_id() counter and skips
        # every user MID, so the clone can collide with neither a converted
        # *MAT nor a later synthesized one. It is deliberately NOT added to
        # all_mat_ids(): that set answers "is this LS-DYNA MID emitted as a
        # /MAT?" for ply references, and a ply can never name a clone.
        clone_id = state.next_mat_id()
        state.sph_mat_clones[mid] = clone_id
        for pid in here:
            state.sph_mat_ids[pid] = clone_id


# ─────────────────────────────────────────────────────────────────────────────
# The mass / smoothing-length decision
# ─────────────────────────────────────────────────────────────────────────────

#: Above this many particles on one part the interparticle-distance search
#: SUBSAMPLES its queries (against the full point cloud, so each query's answer
#: is still exact). ``d_ref`` is a max over per-particle minima and every
#: particle of a regular fill returns the same minimum, so the subsampled answer
#: is exact on a lattice and a lower bound on a graded one. Chosen so the
#: largest SPH deck in the corpus (683,394 particles) stays well under a second.
_DREF_MAX_QUERIES = 20000

#: Hard ceiling on how far one query's ring search widens. The loop normally
#: stops far earlier — either because a candidate satisfies the ``dmin <= r *
#: cell`` exactness test (r = 1..2 on any regular fill) or because the ring
#: already spans the whole grid, which makes the answer exact by covering every
#: particle. This ceiling exists only so a pathological cloud cannot turn one
#: query into a full O(n) scan; past it the query's minimum can be an
#: OVER-estimate (see :func:`_interparticle_distance`).
_DREF_MAX_RINGS = 32

#: Two parts on one section may not disagree about their interparticle distance
#: by more than this and still share one property ``h``. A relative tolerance,
#: because ``d_ref`` is a measured geometric quantity, not a stated one.
_DREF_AGREE_TOL = 1.0e-6


def _interparticle_distance(pts: Sequence[Tuple[float, float, float]]) -> float:
    """LS-DYNA's ``d_ref`` — "the maximum of the minimum distance between every
    particle" (Vol I R16 *SECTION_SPH Remark 1), 0.0 when it cannot be measured.

    A uniform grid keyed on an estimate of the mean spacing, then a widening
    shell search around each query cell. The ``dmin <= r * cell`` test is what
    keeps the answer exact rather than "the closest point in the 3x3x3 block":
    a candidate farther than the ring's guaranteed-covered radius may still be
    beaten by a point one ring out, so the ring widens until it cannot be.

    Two bounded approximations, and they err in OPPOSITE directions — both are
    stated here rather than left to be discovered:

    * the query set is SUBSAMPLED above ``_DREF_MAX_QUERIES`` particles. Every
      query's own answer is still against the full cloud, and ``d_ref`` is a
      max over per-particle minima, so subsampling can only UNDER-estimate it
      (exactly, on a lattice, where every particle returns the same minimum).
    * the ring widens only until it covers the cloud or the visit budget runs
      out. A query whose nearest neighbour lies beyond that is left holding the
      best candidate INSIDE the searched block, which OVER-estimates that
      particle's minimum and so can over-estimate ``d_ref``. The budget is
      generous enough that a regular fill breaks out at r = 1..2 and a
      cloud-spanning search terminates exactly; it bites only on a cloud with
      an isolated particle far outside the fill.
    """
    n = len(pts)
    if n < 2:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    ext = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    nonzero = [e for e in ext if e > 0.0]
    if not nonzero:
        return 0.0                      # every particle at one point
    vol = 1.0
    for e in nonzero:
        vol *= e
    cell = (vol / n) ** (1.0 / len(nonzero))
    if not (cell > 0.0) or math.isinf(cell):
        return 0.0
    grid: Dict[Tuple[int, int, int], List[int]] = {}
    keys: List[Tuple[int, int, int]] = []
    for i, (x, y, z) in enumerate(pts):
        key = (int(math.floor(x / cell)), int(math.floor(y / cell)),
               int(math.floor(z / cell)))
        keys.append(key)
        grid.setdefault(key, []).append(i)
    step = max(1, -(-n // _DREF_MAX_QUERIES))
    # The ring that already spans the whole grid: once it is reached the block
    # holds every particle, so the answer for that query is exact whether or
    # not the radius test fired.
    span = max(1, max(max(k[i] for k in keys) - min(k[i] for k in keys)
                      for i in range(3)) + 1)
    r_max = min(span, _DREF_MAX_RINGS)
    best = 0.0
    for qi in range(0, n, step):
        qx, qy, qz = pts[qi]
        cx, cy, cz = keys[qi]
        d2 = None
        for r in range(1, r_max + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        if r > 1 and max(abs(dx), abs(dy), abs(dz)) != r:
                            continue      # already searched by a smaller ring
                        for j in grid.get((cx + dx, cy + dy, cz + dz), ()):
                            if j == qi:
                                continue
                            ox, oy, oz = pts[j]
                            v = ((ox - qx) ** 2 + (oy - qy) ** 2
                                 + (oz - qz) ** 2)
                            if d2 is None or v < d2:
                                d2 = v
            if d2 is not None and math.sqrt(d2) <= r * cell:
                break
        if d2 is not None:
            d = math.sqrt(d2)
            if d > best:
                best = d
    return best


def _part_dref(state: ConversionState, pid: int,
               cells: Sequence[SphCell]) -> float:
    pts = []
    for c in cells:
        nd = state.nodes.get(c.nid)
        if nd is not None:
            pts.append((nd.x, nd.y, nd.z))
    return _interparticle_distance(pts)


def _resolve_sph_props(state: ConversionState) -> None:
    """One :class:`SphProp` per *SECTION_SPH — the single place that decides
    where each particle's mass comes from and what ``h`` the property states."""
    cells_by_pid: Dict[int, List[SphCell]] = {}
    for c in state.sph_elems:
        cells_by_pid.setdefault(c.pid, []).append(c)
    sph_pids = _sph_part_ids(state)
    other_meshed = ({e.pid for e in state.shell_elems}
                    | {e.pid for e in state.solid_elems}
                    | {e.pid for e in state.tshell_elems}
                    | {e.pid for e in state.beam_elems})
    unreferenced: List[int] = []
    wrong_family: List[int] = []
    for secid in sorted(state.sec_sph):
        sec = state.sec_sph[secid]
        ref_pids = _section_parts(state, secid)
        if not ref_pids:
            unreferenced.append(secid)
            continue
        if not any(p in sph_pids for p in ref_pids) \
                and any(p in other_meshed for p in ref_pids):
            # NO part on this section owns a particle, but at least one carries
            # shells, solids, thick shells or beams. That part's own family
            # auto-creates a section under the SAME id, and emitting the SPH
            # property too puts two /PROP cards on one id — starter ERROR 79,
            # silently, because nothing else in the converter compares emitted
            # property ids. The element family wins; this section is reported
            # and NOT emitted. (The MIXED case — some parts SPH, some not — is
            # resolved a step earlier by _split_mixed_family_sections, which
            # moves the SPH property onto a synthesized id instead of dropping
            # it.) This is the same guard writer/tshell.py makes.
            wrong_family.append(secid)
            continue
        prop_id = state.sph_section_prop_ids.get(secid, secid)
        title = sec.title or f"PROP_SPH_{secid}"
        pids = [p for p in ref_pids if p in cells_by_pid]
        cells = [c for p in pids for c in cells_by_pid[p]]
        _warn_dropped_fields(state, sec)
        _warn_mat_compat(state, sec, ref_pids)
        prop = SphProp(secid=secid, prop_id=prop_id, title=title)
        state.sph_props[secid] = prop
        if not cells:
            # An element-free *PART on an SPH section. There is no particle to
            # take a mass from and *SECTION_SPH has no mass field, so Mp is the
            # one value that cannot be derived — 1.0 keeps the property legal
            # (a non-positive Mp is WARNING 138 plus that same fabricated 1.0)
            # and nothing references it anyway.
            prop.mp = 1.0
            prop.h = sec.sphini if sec.sphini > 0.0 else 0.0
            prop.h_source = "SPHINI" if sec.sphini > 0.0 else ""
            prop.h_1d = _h_1d(sec)
            continue
        _decide_mass_route(state, sec, prop, pids, cells, cells_by_pid)
    if unreferenced:
        state.note_recognized_not_emitted(
            "SECTION_SPH",
            "section(s) " + ", ".join(str(s) for s in unreferenced)
            + " are referenced by no *PART, so no /PROP/SPH is written for "
            "them. Nothing in the deck can point at them, so nothing is lost.")
    if wrong_family:
        state.warn(
            "*SECTION_SPH " + ", ".join(str(s) for s in wrong_family)
            + " is referenced by *PART(s) whose elements are SHELLS, SOLIDS, "
            "THICK SHELLS or BEAMS — no particle sits on it at all. Those "
            "parts get the property their own element family needs, under the "
            "same id, so the SPH property is NOT emitted: writing both would "
            "be two /PROP cards on one id (starter ERROR 79, DUPLICATE ID IN "
            "PID DEFINITION) and the deck would be refused. Check the *PART's "
            "SECID if the elements were meant to be *ELEMENT_SPH.")


def _h_1d(sec: SectionSph) -> int:
    """``/PROP/SPH h_1D`` — the dilatation rule.

    ``HMIN == HMAX == 1.0`` is LS-DYNA's own spelling of a constant smoothing
    length ("Defining a value of 1 for HMIN and 1 for HMAX will result in a
    constant smoothing length in time and space") and maps EXACTLY onto
    ``h_1D = 2`` (``H_DILAT_COEFF = ZERO``, ``hm_read_prop34.F:203-211``). Every
    other HMIN/HMAX pair asks for BOUNDED dilatation, which needs ``h_1D = 3``
    and the radioss2026-only bounds card — unusable at /BEGIN 2022 — so it falls
    back to the unbounded 3D dilatation ``h_1D = 0`` and is warned about.
    """
    if sec.hmin == 1.0 and sec.hmax == 1.0:
        return 2
    return 0


def _decide_mass_route(state: ConversionState, sec: SectionSph, prop: SphProp,
                       pids: List[int], cells: List[SphCell],
                       cells_by_pid: Dict[int, List[SphCell]]) -> None:
    """Choose between the per-cell and the per-property mass, and report."""
    prop.h_1d = _h_1d(sec)
    masses = {(c.flag, c.mass) for c in cells}
    uniform = (len(masses) == 1
               and next(iter(masses))[0] == 1
               and next(iter(masses))[1] > 0.0)
    live = [c.mass for c in cells if c.flag == 1 and c.mass > 0.0]
    vols = [c.mass for c in cells if c.flag == 2 and c.mass > 0.0]
    rho = _section_density(state, pids)
    dref, dref_split = _section_dref(state, pids, cells_by_pid)
    if live:
        prop.mp = sum(live) / len(live)
    elif vols and rho > 0.0:
        prop.mp = rho * sum(vols) / len(vols)
    else:
        # NOT ONE particle of this section states a mass or a volume. Radioss
        # has nowhere to read a mass from, and writing Mp <= 0 hands the
        # fabrication to hm_read_prop34.F:235-239, which invents 1.0 mass unit
        # per particle behind a single WARNING 138 (measured: four blank-mass
        # particles gave TOTAL MASS = 4.000000000000). So a mass is derived from
        # the FILL — rho x d_ref**3, the mass of the cube each particle
        # occupies — when the density and the spacing are both known, and only
        # falls back to the bare 1.0 when neither is. Both cases are stated
        # outright by _warn_fabricated_mp: the number is not in the source deck.
        prop.mp = rho * dref ** 3 if (rho > 0.0 and dref > 0.0) else 1.0
        prop.mp_source = ("geometry" if (rho > 0.0 and dref > 0.0)
                          else "fabricated")

    # The smoothing length the LS-DYNA deck asks for, if it can be stated.
    h0, h_source = _lsdyna_h0(sec, dref, dref_split)

    if prop.mp_source != "deck":
        # Every cell is written Flag 0 / MASS 0 (they have no mass to write),
        # so they all read the property's Mp — and a type-0 particle leaves the
        # property's own h alone (spinih.F:85-109), so the deck's smoothing
        # length still survives. per_cell stays True only so the "all the same
        # mass, stated once" header comment — which would be false here — is
        # not written into the /SPHCEL block.
        prop.per_cell = True
        prop.h = h0
        prop.h_source = h_source
        _warn_fabricated_mp(state, sec, prop, pids, cells, rho, dref, h0,
                            h_source)
        if dref_split:
            _warn_dref_split(state, sec, dref_split)
        return

    if uniform and h0 > 0.0:
        # Route A: the mass lives on the PROPERTY, so the property's h survives.
        prop.per_cell = False
        prop.mp = next(iter(masses))[1]
        prop.h = h0
        prop.h_source = h_source
        state.warn(
            f"*SECTION_SPH {sec.secid} → /PROP/SPH/{prop.prop_id}: every one of "
            f"the {len(cells)} particle(s) on part(s) {pids} carries the SAME "
            f"mass {prop.mp:g}, so it is stated ONCE as the property's Mp and "
            "the per-particle /SPHCEL MASS column is left blank. Total mass is "
            f"{len(cells)} x {prop.mp:g} = {len(cells) * prop.mp:g}, exact — and "
            "because no particle carries a mass of its own, Radioss uses the "
            f"property's smoothing length h = {h0:g} ({h_source}) instead of "
            "deriving one. Writing the mass per cell would be equally exact for "
            "the mass but would OVERWRITE h with (sqrt(2)*m/rho)^(1/3) "
            "(spinih.F:90-95) and lose the deck's own smoothing length. "
            "(dyna2rad always writes the cell mass and never writes Mp at all.)")
        return

    # Route B: the mass lives on each cell. Exact whatever the deck says, but
    # Radioss then derives h itself and the deck's own h cannot be honoured.
    prop.per_cell = True
    prop.h = 0.0
    prop.h_source = ""
    if h0 > 0.0:
        state.warn(
            f"*SECTION_SPH {sec.secid} → /PROP/SPH/{prop.prop_id}: the deck "
            f"states a smoothing length h = {h0:g} ({h_source}), but "
            f"{_route_b_why(masses, uniform, live)}, so each particle has to "
            "carry its own mass on its /SPHCEL row — and a mass-carrying "
            "particle makes Radioss DERIVE h from that mass and IGNORE the "
            "property's (spinih.F:85-95)."
            + _derived_h_detail(cells, rho, h0)
            + " The MASS is exact either way; only the smoothing length "
            "differs. Give the particles one uniform mass, or accept the "
            "derived h.")
    if dref_split:
        _warn_dref_split(state, sec, dref_split)
    n_zero = sum(1 for c in cells if c.mass <= 0.0)
    if n_zero:
        how = ("the mean of the particles that DO state one" if live else
               "rho x the mean of the VOLUMES the other particles state")
        state.warn(
            f"*SECTION_SPH {sec.secid} → /PROP/SPH/{prop.prop_id}: "
            f"{n_zero} particle(s) on part(s) {pids} state no mass of their "
            f"own, so they take the property's Mp = {prop.mp:g} ({how}). Their "
            "/SPHCEL Flag is written 0, never 1: a Flag=1 row with a blank MASS "
            "is a SILENT ZERO-MASS particle — measured, TOTAL MASS = "
            "0.000000000000 with no diagnostic at all.")


def _route_b_why(masses: Set[Tuple[int, float]], uniform: bool,
                 live: List[float]) -> str:
    """Why the property route was not available — the ACTUAL reason.

    Three distinct cases hide behind ``not uniform``, and quoting the wrong one
    sends the reader looking for a mass spread that is not there:

    * genuinely different masses;
    * every cell states the SAME VOLUME (Flag 2). ``/PROP/SPH`` has no
      volume field at all, so only a ``/SPHCEL`` row can carry it — nothing to
      do with a spread;
    * the masses agree but the section's parts disagree about ``d_ref``, so no
      single property ``h`` can serve them (``uniform`` is True there and
      ``h0`` is 0, which is what put us on this route).
    """
    if uniform:
        return "the section's parts disagree about it"
    if len(masses) == 1 and not live:
        return ("the particles state a VOLUME, which only a /SPHCEL row can "
                "carry — /PROP/SPH has no volume field")
    return "the particles carry DIFFERENT masses"


def _derived_h_detail(cells: List[SphCell], rho: float, h0: float) -> str:
    """The h Radioss will actually derive on the per-cell route, as a RANGE.

    A single value computed from the MEAN particle mass is a value no particle
    has, and on a two-population cloud its DIRECTION is wrong for half of them.
    Measured on 500 particles at 8e-9 plus 500 at 1.6e-8: the mean-mass reading
    said "7.07 % larger", while ``spinih.F`` gives 2.2449 for the light half
    (6.5 % SMALLER) and 2.8284 for the heavy half — and the starter's governing
    time step matched the SMALLEST h, i.e. exactly the population the mean-mass
    reading mis-described. So the min and the max are both reported, and the
    smallest is named as the one that sets the time step.
    """
    if rho <= 0.0 or h0 <= 0.0:
        return ""
    ms = sorted(c.mass for c in cells if c.mass > 0.0)
    hs = [h for h in (_radioss_h(m, rho) for m in ms) if h > 0.0]
    if not hs:
        return ""
    lo, hi = min(hs), max(hs)
    if lo == hi:
        return (f" Radioss will use h = (sqrt(2)*{ms[0]:g}"
                f"/{rho:g})^(1/3) = {lo:g} against the deck's {h0:g} — a ratio "
                f"of {lo / h0:.4f}, i.e. {abs(1.0 - lo / h0) * 100:.3g} % "
                + ("smaller" if lo < h0 else "larger")
                + f" support radius and {abs(1.0 - (lo / h0) ** 3) * 100:.3g} % "
                + ("fewer" if lo < h0 else "more")
                + " neighbours per particle.")
    return (f" Radioss will derive h = (sqrt(2)*m_p/{rho:g})^(1/3) PER "
            f"PARTICLE, which over this section's masses spans {lo:g} to "
            f"{hi:g} against the deck's single {h0:g} — ratios "
            f"{lo / h0:.4f} to {hi / h0:.4f}. The SMALLEST h sets the SPH time "
            "step (mdtsph.F:132, dt = h/(c*(qb+sqrt(qb^2+1)))), so "
            f"{lo / h0:.4f} is the ratio that governs the run.")


def _section_density(state: ConversionState, pids: List[int]) -> float:
    """The density shared by the section's SPH parts, 0.0 when they disagree or
    it is not known. Used only for reporting and for the volume→mass mean."""
    rhos = set()
    for pid in pids:
        part = state.parts.get(pid)
        if part is None:
            continue
        rho = _mat_density(state, part.mid)
        if rho > 0.0:
            rhos.add(rho)
    return rhos.pop() if len(rhos) == 1 else 0.0


def _section_dref(state: ConversionState, pids: List[int],
                  cells_by_pid: Dict[int, List[SphCell]]):
    """``(d_ref, per_part_dref)`` for one section's SPH parts.

    ``d_ref`` is the value the whole section agrees on, or 0.0 when its parts
    disagree; ``per_part_dref`` is non-empty ONLY in that disagreeing case — it
    is what the report names.

    Measured once per section and then reused, because two callers want it: the
    LS-DYNA ``h0 = CSLH x d_ref`` rule, and the geometric ``Mp = rho x d_ref^3``
    fallback for a section whose particles state no mass at all. The
    nearest-neighbour search is the expensive part of this module (a grid build
    plus up to ``_DREF_MAX_QUERIES`` ring queries; 683,394 particles in ~9 s),
    and it is DELIBERATELY run even on the per-cell route, where its only
    consumer is the warning text — the number it produces is the one thing that
    tells the user how far the emitted smoothing length has moved, which is the
    whole point of that warning.
    """
    drefs: List[Tuple[int, float]] = []
    for pid in pids:
        d = _part_dref(state, pid, cells_by_pid.get(pid, []))
        if d > 0.0:
            drefs.append((pid, d))
    if not drefs:
        return 0.0, []
    lo = min(d for _p, d in drefs)
    hi = max(d for _p, d in drefs)
    if hi - lo > _DREF_AGREE_TOL * hi:
        return 0.0, drefs
    return hi, []


def _lsdyna_h0(sec: SectionSph, dref: float, dref_split):
    """``(h0, source)`` — the smoothing length the LS-DYNA deck asks for.

    ``SPHINI`` wins outright ("Optional initial smoothing length (overrides true
    smoothing length). With this option LS-DYNA will not calculate the smoothing
    length during initialization, and the field CSLH is ignored"). Otherwise the
    default rule applies: "LS-DYNA computes the initial smoothing length, h0,
    for each SPH part by taking the maximum of the minimum distance between
    every particle and then scaling this value by CSLH."

    A section whose parts DISAGREE about ``d_ref`` (``dref_split`` non-empty)
    has no single h0 the CSLH rule can express, so it returns 0.0 and lets
    :func:`_warn_dref_split` say why.
    """
    if sec.sphini > 0.0:
        return sec.sphini, "SPHINI"
    if not (sec.cslh > 0.0) or dref_split or dref <= 0.0:
        return 0.0, ""
    src = (f"CSLH {sec.cslh:g} x the measured interparticle distance {dref:g}"
           + (" — CSLH left blank, so the manual's default 1.2"
              if sec.cslh_blank else ""))
    return sec.cslh * dref, src


def _warn_dref_split(state: ConversionState, sec: SectionSph,
                     dref_split: List[Tuple[int, float]]) -> None:
    state.warn(
        f"*SECTION_SPH {sec.secid} is shared by parts whose particle "
        "spacings differ — "
        + ", ".join(f"part {p}: d_ref {d:g}" for p, d in dref_split)
        + ". LS-DYNA computes h0 = CSLH x d_ref PER PART, and one "
        "/PROP/SPH holds one h, so no single value can serve them. The "
        "particles keep their own masses instead and Radioss derives a "
        "smoothing length per particle. Give each part its own "
        "*SECTION_SPH to state a separate h.")


def _warn_fabricated_mp(state: ConversionState, sec: SectionSph, prop: SphProp,
                        pids: List[int], cells: List[SphCell], rho: float,
                        dref: float, h0: float, h_source: str) -> None:
    """The ONE report for a section whose particles state no mass at all.

    This is the case the batch's other diagnostics used to describe wrongly —
    they said the fabrication "cannot happen here", quoted a mean "of the
    particles that DO state one" when none does, blamed a mass spread among
    identical blanks, and printed an h ratio computed from the invented number.
    All of that is replaced by a single statement of what is now in the deck and
    where it came from.
    """
    n = len(cells)
    if prop.mp_source == "geometry":
        how = (f"rho x d_ref^3 = {rho:g} x {dref:g}^3 = {prop.mp:g} — the mass "
               "of the cube each particle occupies in the fill this deck "
               "actually contains")
    else:
        how = (f"{prop.mp:g}, a bare unit mass, because the part has neither a "
               "usable density nor a measurable particle spacing to derive one "
               "from")
    state.warn(
        f"MASS INVENTED: *SECTION_SPH {sec.secid} → /PROP/SPH/{prop.prop_id}: "
        f"NOT ONE of the {n} particle(s) on part(s) {pids} states a mass or a "
        "volume — every *ELEMENT_SPH MASS cell in the section is blank or "
        f"zero. The deck therefore carries a mass the SOURCE NEVER STATED: "
        f"Mp = {how}, giving a section total of {n} x {prop.mp:g} = "
        f"{n * prop.mp:g}. Writing Mp = 0 instead is not an option — "
        "hm_read_prop34.F:235-239 answers a non-positive Mp by inventing 1.0 "
        "mass unit per particle behind a single WARNING 138, which is the same "
        "fabrication with no number you chose and no line in this log. "
        + (f"The deck's own smoothing length h = {h0:g} ({h_source}) DOES "
           "survive, because a particle that carries no mass of its own leaves "
           "the property's h alone (spinih.F:85-109). "
           if h0 > 0.0 else "")
        + "State the particle masses on the *ELEMENT_SPH cards.")


# ─────────────────────────────────────────────────────────────────────────────
# Dropped-field reports
# ─────────────────────────────────────────────────────────────────────────────

def _warn_dropped_fields(state: ConversionState, sec: SectionSph) -> None:
    """The *SECTION_SPH cells with no /BEGIN 2022 Radioss home. dyna2rad drops
    every one of them without a message (and mis-handles two more)."""
    notes: List[str] = []
    # HMIN = HMAX = 1.0 maps exactly (h_1D = 2, handled in _h_1d); HMIN = HMAX =
    # 0.0 asks for no bound at all, which is what Radioss does anyway. Every
    # other pair — INCLUDING the manual's own 0.2 / 2.0 default, which a blank
    # card means — is a real bound that a /BEGIN 2022 deck cannot carry, and it
    # is the bound that keeps a collapsing smoothing length off engine ERROR 174.
    if not (sec.hmin == 1.0 and sec.hmax == 1.0) \
            and (sec.hmin > 0.0 or sec.hmax > 0.0):
        notes.append(
            f"HMIN={sec.hmin:g} / HMAX={sec.hmax:g} (the smoothing length is to "
            "stay between HMIN*h0 and HMAX*h0) — the bounded dilatation that "
            "needs is /PROP/SPH h_1D=3 plus hmin/hmax/hcst, and those three "
            "cells live on a radioss2026-only THIRD card that a /BEGIN 2022 "
            "reader discards SILENTLY while still accepting h_1D=3 (measured: "
            "0.37/3.77/1.77 echoed as the hard-coded 0.2/2.0/1.2, 0 ERRORS). "
            "Emitting them would run the bounded algorithm with bounds nobody "
            "chose, so the smoothing length dilates UNBOUNDED instead — which "
            "is what the LOWER bound exists to prevent (engine spadah.F:96-99 "
            "stops the run with ERROR 174 once h falls below 1e-20). "
            "HMIN=HMAX=1.0 is the one pair that maps exactly, to a constant h"
            + (" (0.2 / 2.0 is the manual's own default for a blank cell, so "
               "this fires on a deck that never named them)"
               if (sec.hmin, sec.hmax) == (0.2, 2.0) else ""))
    if sec.death and sec.death < 1.0e19:
        notes.append(
            f"DEATH={sec.death:g} (the time the SPH approximation stops) — "
            "Radioss has no per-property activation window; /PROP/SPH carries "
            "no time field at all, so the particles stay active for the whole "
            "run")
    if sec.start:
        notes.append(
            f"START={sec.start:g} (the time the SPH approximation begins) — "
            "same reason; the particles are active from t=0")
    if sec.sphkern:
        notes.append(
            f"SPHKERN={sec.sphkern} (0 cubic / 1 quintic / 2 quadratic / "
            "3 quartic B-spline) — Radioss's SPH kernel is the cubic B-spline "
            "with support 2h and no alternative (engine weight.F), so a "
            "higher-order kernel becomes the cubic one. NOTE the /PROP/SPH "
            "'Order' column is NOT a kernel order — it is the renormalisation "
            "correction order, valid only in -1/0/1 — so it is left at 0 "
            "(dyna2rad maps SPHKERN=2 onto it, which the engine's own dispatch "
            "in spcompl.F:107-118 then matches none of)")
    if notes:
        state.warn(f"*SECTION_SPH {sec.secid} → /PROP/SPH. Dropped: "
                   + "; ".join(notes) + ".")


def _warn_mat_compat(state: ConversionState, sec: SectionSph,
                     pids: List[int]) -> None:
    """The pre-starter ERROR 3046 / 3047 report for one SPH property."""
    from .mesh import _target_mat_law
    bad: Dict[int, List[int]] = {}
    nomat: List[int] = []
    for pid in pids:
        part = state.parts.get(pid)
        if part is None:
            continue
        if pid in state.sph_mat_ids:
            # Repointed at a /MAT/LAW2 clone by _resolve_sph_materials, which
            # is exactly the remedy this report would otherwise recommend.
            continue
        law = _target_mat_law(state, part.mid)
        if law is None:
            nomat.append(pid)
            continue
        if law not in _SPH_COMPATIBLE_LAWS:
            bad.setdefault(law, []).append(pid)
    for law, plist in sorted(bad.items()):
        state.warn(
            f"*SECTION_SPH {sec.secid} → /PROP/SPH: part(s) {plist} pair it "
            f"with /MAT/LAW{law}, which does NOT declare SPH compatibility "
            "(only a law that calls INIT_MAT_KEYWORD(...,'SPH') sets "
            "MATPARAM%PROP_SPH, init_mat_keyword.F:272-273). The starter "
            "refuses that with ERROR 3046 'ELEMENTS OF TYPE SPH ARE NOT "
            "COMPATIBLE WITH MATERIAL ID ...' — or ERROR 3047 on the property "
            "— so the deck will not start until the part gets an SPH-capable "
            "material. (dyna2rad imposes no law filter at all and lets the "
            "starter be the first to object.)")
    if nomat:
        state.warn(
            f"*SECTION_SPH {sec.secid} → /PROP/SPH: part(s) {nomat} have no "
            "/MAT in the converted deck, so their particles carry no density "
            "and no constitutive law. Radioss derives an SPH particle's VOLUME "
            "from its mass and the material density (spinit3.F:139-145), so "
            "without a material the part contributes nothing but mass.")


def _warn_control_sph(state: ConversionState) -> None:
    """Every *CONTROL_SPH column, by name, and where it went.

    dyna2rad drops the whole keyword silently — ``CONTROL_SPH`` does not occur
    anywhere under ``reader/source/dyna2rad/``.
    """
    c = state.control_sph
    if c is None:
        return
    dropped: List[str] = []
    if c.ncbs not in (0, 1):
        dropped.append(
            f"NCBS={c.ncbs} (time steps between particle sorts) — Radioss "
            "re-sorts on its own criterion, /SPHGLO Alpha_sort, which is a "
            "geometric tolerance rather than a cycle count")
    if c.boxid:
        dropped.append(
            f"BOXID={c.boxid} (particles leaving the box are deactivated) — "
            "Radioss has no box-scoped particle deactivation, so no particle "
            "is ever deactivated by leaving a region")
    if c.dt and c.dt < 1.0e19:
        dropped.append(f"DT={c.dt:g} (SPH death time) — the particles stay "
                       "active for the whole run")
    if c.idim not in (0, 3):
        dropped.append(
            f"IDIM={c.idim} ({'2D plane strain' if c.idim == 2 else '2D axisymmetric' if c.idim == -2 else 'an unknown dimension'}) "
            "— OpenRadioss SPH is 3D ONLY. This is the one column whose loss "
            "changes the ANSWER rather than the accuracy: the particles are "
            "solved in 3D whatever the deck asked for. Re-state the model in "
            "3D, or do not expect the 2D result")
    if c.form:
        dropped.append(
            f"FORM={c.form} (particle approximation theory) — Radioss's "
            "/PROP/SPH Order covers the renormalisation orders 0 and 1 only "
            "and nothing else in the FORM list has a counterpart; the standard "
            "formulation is used")
    if c.start:
        dropped.append(f"START={c.start:g} (particle-approximation start time) "
                       "— the particles are active from t=0")
    if c.maxv and c.maxv < 1.0e14:
        dropped.append(
            f"MAXV={c.maxv:g} (particles faster than this are deactivated) — "
            "Radioss has no velocity-based particle deactivation, so a "
            "particle that runs away keeps its neighbours' time step down "
            "instead of dropping out")
    for name, val, what in (
            ("CONT", c.cont, "inter-part approximation switch"),
            ("DERIV", c.deriv, "smoothing-length time-integration type"),
            ("INI", c.ini, "smoothing-length initialization algorithm"),
            ("ISHOW", c.ishow, "display of deactivated particles"),
            ("IEROD", c.ierod, "eroded-particle treatment"),
            ("ICONT", c.icont, "contact of deactivated particles"),
            ("IAVIS", c.iavis, "artificial-viscosity formulation"),
            ("ITHK", c.ithk, "contact thickness from particle volume"),
            ("ISTAB", c.istab, "FORM=12 stabilization type"),
            ("SPHSORT", c.sphsort, "implicit SPH node reordering"),
            ("ISHIFT", c.ishift, "particle-shifting algorithm")):
        if val:
            dropped.append(f"{name}={val} ({what})")
    if c.ql:
        dropped.append(f"QL={c.ql:g} (FORM=12 quasi-linear coefficient)")
    if c.isymp not in (0, 100):
        dropped.append(
            f"ISYMP={c.isymp} (ghost-node memory for symmetry planes) — "
            "*BOUNDARY_SPH_SYMMETRY_PLANE is outside this batch, so no ghost "
            "nodes are generated and the sizing hint has nothing to size")
    if dropped:
        state.warn("*CONTROL_SPH. Dropped: " + "; ".join(dropped)
                   + ". (dyna2rad drops the whole keyword with no message.)")


# ─────────────────────────────────────────────────────────────────────────────
# Card emitters
# ─────────────────────────────────────────────────────────────────────────────

#: ``radioss2019/PROP/prop_p34_sph.cfg FORMAT(radioss2019)``, the newest block a
#: ``/BEGIN 2022`` deck reads: a mandatory 80a title then TWO data cards,
#: ``%20lg%20lg%20lg%20lg%10d%10d`` and ``%10d%20lg%20lg``. The radioss2026
#: block adds ten dead columns and two more cells to card 2 plus a third card;
#: emitting that shape at 2022 costs the hmin/hmax/hcst values silently (see the
#: module docstring, divergence 3).
_PROP_CARD1_HDR = ("#                 Mp                  qa                  "
                   "qb            Alpha_cs   skew_ID      h_1D")
_PROP_CARD2_HDR = ("#    Order                   h             Xi_Stab")

#: ``/PROP/SPH`` qa (quadratic) and qb (linear) bulk viscosity. The reader
#: self-defaults a zero to exactly these (``hm_read_prop34.F:169-170``), so
#: writing them changes nothing — they are written so the emitted card states
#: what the run uses. LS-DYNA's *CONTROL_BULK_VISCOSITY Q1/Q2 (1.5/0.06) is NOT
#: propagated: k2rad does not parse that keyword, and dyna2rad does not
#: propagate it either.
_QA_DEFAULT, _QB_DEFAULT = 2.0, 1.0

#: ``/SPHCEL`` correction order. Valid values are -1, 0 and 1 ONLY —
#: ``spcompl.F:107-118`` dispatches on nothing else — and 0 is Radioss's own
#: default renormalisation.
_ORDER = 0


def _make_sph_properties(state: ConversionState) -> List[str]:
    """Every /PROP/SPH the deck needs, one per referenced *SECTION_SPH."""
    lines: List[str] = []
    for secid in sorted(state.sph_props):
        prop = state.sph_props[secid]
        lines += [
            f"/PROP/SPH/{prop.prop_id}",
            prop.title[:80],
            _PROP_CARD1_HDR,
            (f"{_f_mass(prop.mp)}{_f(_QA_DEFAULT)}{_f(_QB_DEFAULT)}{_f(0.0)}"
             f"{_i(0)}{_i(prop.h_1d)}"),
            _PROP_CARD2_HDR,
            f"{_i(_ORDER)}{_f(prop.h)}{_f(0.0)}",
            HDR,
        ]
    return lines


def _emit_sphcel_block(state: ConversionState, pid: int,
                       cells: List[SphCell]) -> List[str]:
    """The ``/SPHCEL/<part_ID>`` block for one part.

    ``id`` cols 1-10, ``Flag`` 11-20, ``MASS`` 21-40 —
    ``radioss41/ELEM/sphcel.cfg FORMAT(radioss110)``, the ONLY format block
    that file has, so 2022 and 2026 are byte-identical here.

    A zero-mass particle is written with ``Flag = 0``, never 1. That is not
    cosmetic: an explicit ``Flag = 1`` with a blank MASS keeps ``TYPE = 1``, and
    ``spinit3.F:142`` then computes ``VOL = 0/rho`` — measured, ``TOTAL MASS =
    0.000000000000`` with no diagnostic at all. ``Flag = 0`` routes the particle
    to the property's ``Mp`` instead, which this converter always writes
    positive.
    """
    prop = state.sph_props.get(_part_secid(state, pid))
    per_cell = prop.per_cell if prop is not None else True
    lines: List[str] = []
    if prop is not None and not per_cell:
        # Said in the deck, not only in the conversion log: a reader who sees a
        # column of zeros where the LS-DYNA card had masses must be able to
        # find out where they went without leaving the file.
        lines += [
            "#-  The Flag and MASS columns below are ZERO on purpose: every "
            "particle of this",
            f"#-  part carries the SAME mass, so it is stated ONCE as "
            f"/PROP/SPH/{prop.prop_id} Mp = {prop.mp:g}",
            "#-  (Type 0, spinit3.F:147). Stating it per cell would be equally "
            "exact for the mass",
            "#-  but would make Radioss DERIVE the smoothing length from it and "
            "ignore the",
            f"#-  property's h = {prop.h:g}.",
        ]
    lines += [f"/SPHCEL/{pid}", "#      id      Flag                MASS"]
    for c in cells:
        if per_cell and c.mass > 0.0:
            lines.append(f"{_i(c.nid)}{_i(c.flag)}{_f_mass(c.mass)}")
        else:
            lines.append(f"{_i(c.nid)}{_i(0)}{_f(0.0)}")
        # The #106 register: the /TH/SPHCEL writer lists ONLY ids that reach
        # this line, because naming one that does not is starter ERROR 69 and
        # the whole deck is refused.
        state.sph_cell_ids.add(c.nid)
    lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# /SPHGLO
# ─────────────────────────────────────────────────────────────────────────────
#
# ``radioss2017/CARDS/sphglo.cfg FORMAT(radioss2017)``, the newest block at or
# below 2022 (and 2026 — no newer file exists):
#     Alpha_sort(20) Maxsph(10) Lneigh(10) Nneigh(10) Isol2sph(10)
# No title line, and only the FIRST /SPHGLO is read.
#
# **An "empty" /SPHGLO is not a no-op.** Measured: with no card at all the
# starter echoes ALPHA SORT 0.25 / LNEIGH 120 / NNEIGH 240, and with a card
# whose every field is 0 it echoes 0.25 / 120 / *120* — the stored-neighbour cap
# HALVED, because ``hm_read_sphglo.F`` reads a blank Nneigh as 0, floors it at
# 120 and then never reaches the 240 default. So this card is emitted only when
# there is something to say, and then it says every field explicitly.
_SPHGLO_ALPHA_SORT = 0.25       # the reader's own default (SPASORT = FOURTH)
_SPHGLO_ISOL2SPH = 1            # the reader's own default (by part)
_SPHGLO_NNEIGH_DEFAULT = 240    # KVOISPH when no card is present


def _make_sphglo(state: ConversionState) -> List[str]:
    """*CONTROL_SPH NMNEIGH → /SPHGLO Lneigh / Nneigh, when it asks for MORE
    than Radioss's own default.

    ``NMNEIGH`` "defines the initial number of neighbors per particle"
    (default 150; a negative value makes ``|NMNEIGH|`` a static hard maximum).
    Radioss's two neighbour caps are ``Lneigh`` (max COMPUTED, default 120) and
    ``Nneigh`` (max STORED, default 240). Those defaults already exceed
    LS-DYNA's own 150, so a card is written only when the deck asks for more —
    never to REDUCE a Radioss default, which is how an under-sized neighbour
    table becomes a wrong answer rather than a slow one.
    """
    c = state.control_sph
    if c is None or not state.sph_elems:
        return []
    want = abs(c.nmneigh)
    if want <= _SPHGLO_NNEIGH_DEFAULT:
        if want:
            state.warn(
                f"*CONTROL_SPH: NMNEIGH={c.nmneigh} asks for {want} neighbour "
                "slots per particle. Radioss's own defaults are already larger "
                f"({_SPHGLO_NNEIGH_DEFAULT} stored / 120 computed), so NO "
                "/SPHGLO is written — emitting one would REDUCE the caps, and "
                "an all-blank /SPHGLO is worse still (measured: it halves the "
                "stored cap from 240 to 120). Nothing is lost.")
        return []
    state.warn(
        f"*CONTROL_SPH: NMNEIGH={c.nmneigh} → /SPHGLO Lneigh = Nneigh = {want}. "
        "Radioss splits the neighbour budget into a COMPUTED cap (Lneigh, "
        f"default 120) and a STORED cap (Nneigh, default {_SPHGLO_NNEIGH_DEFAULT}); "
        "LS-DYNA states one number, so both are set to it. Alpha_sort and "
        "Isol2sph are written at their Radioss defaults EXPLICITLY, because a "
        "blank /SPHGLO field is not neutral — an all-zero card halves the "
        "stored cap to 120 (measured). NCBS has no counterpart: Radioss "
        "re-sorts on the geometric Alpha_sort criterion, not on a cycle count.")
    return [
        "#-  GLOBAL SPH CONTROL (*CONTROL_SPH):", HDR,
        "/SPHGLO",
        "#        Alpha_sort    Maxsph    Lneigh    Nneigh  Isol2sph",
        f"{_f(_SPHGLO_ALPHA_SORT)}{_i(0)}{_i(want)}{_i(want)}"
        f"{_i(_SPHGLO_ISOL2SPH)}",
        HDR,
    ]
