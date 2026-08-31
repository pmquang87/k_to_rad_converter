"""The RARE CARDS batch.

Five keywords whose Radioss targets share nothing but their rarity:

===========================================  ==============================
LS-DYNA                                      Radioss
===========================================  ==============================
``*DEFINE_ELEMENT_DEATH_<FAMILY>[_SET]``     ``/ACTIV`` + element groups
``*PERTURBATION_NODE``                       ``/RANDOM`` / ``/RANDOM/GRNOD``
``*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY``      ``/IMPDISP/FGEO``
``*INTERFACE_SPRINGBACK_LSDYNA``             the ENGINE ``/DYNAIN`` block
===========================================  ==============================

(``*DEFINE_CURVE_SMOOTH`` is the fifth; it needs no writer of its own — the
handler registers the trapezoid in ``state.curves`` and flags it in
``state.funct_smooth_ids``, and ``materials._make_functions`` writes
``/FUNCT_SMOOTH`` instead of ``/FUNCT`` for a flagged id.)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..state import ConversionState
from .common import (
    HDR,
    _emit_grsh3n,
    _emit_grshel,
    _emit_id_group,
    _f,
    _fmt_eid_list,
    _i,
)
from .loads import _emit_funct

__all__ = [
    "_make_element_death",
    "_make_random",
    "_make_impdisp_fgeo",
    "_make_engine_dynain",
]


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_ELEMENT_DEATH_* → /ACTIV
# ─────────────────────────────────────────────────────────────────────────────

#: The ``/ACTIV`` card-2 slot each Radioss element family occupies, in the
#: column order of ``radioss2019/LOADCOL/activ.cfg:142-157``::
#:
#:   #  sens_ID grbric_ID grquad_ID grshel_ID grtrus_ID grbeam_ID  grspr_ID grsh3n_ID               Iform
#:
#: ``radioss2019`` is the ONLY layout in that cfg (the file carries radioss51,
#: radioss2017 and radioss2019 blocks and nothing newer), so a ``/BEGIN 2022``
#: deck reads it. MEASURED with twin decks at ``/BEGIN 2019`` and ``/BEGIN
#: 2022``: byte-identical ``ELEMENT ACTIVATION-DEACTIVATION`` echo, no warning
#: on the card at either version — the ordinary "newest format is older than
#: the deck" case, class (a) of the #119 rule, so it is emitted as written.
_ACTIV_SLOTS = ("sens", "grbric", "grquad", "grshel", "grtrus", "grbeam",
                "grspr", "grsh3n")


def _activ_card(activ_id: int, title: str, slots: Dict[str, int],
                tstart: float, tstop: float) -> List[str]:
    """One ``/ACTIV`` block, always ``Iform = 2``.

    ``Iform`` is not a style choice. ``Iform = 1`` is the SENSOR form, and with
    ``sens_ID = 0`` it is a silent no-op — MEASURED: an ``Iform = 1``
    ``/ACTIV`` with no sensor produced zero activation/deactivation events over
    a whole run, at zero starter and engine diagnostics. LS-DYNA element death
    has no sensor, so ``Iform = 2`` (``hm_read_activ.F:137-139``, the
    ``Tstart``/``Tstop`` form) is the only expressible one — and it needs its
    card 3: the cfg emits ``CARD("%20lg%20lg", ACTIV_Tstart, ACTIV_Tstop)``
    only ``if(ACTIV_Iform == 2)``, so omitting it under ``Iform = 2`` is a
    misparse, not a default.
    """
    row = "".join(_i(slots.get(k, 0)) for k in _ACTIV_SLOTS)
    return [
        f"/ACTIV/{activ_id}",
        (title or f"ACTIV_{activ_id}")[:100],
        "#  sens_ID grbric_ID grquad_ID grshel_ID grtrus_ID grbeam_ID  "
        "grspr_ID grsh3n_ID               Iform",
        f"{row}{' ' * 10}{_i(2)}",
        "#             Tstart               Tstop",
        f"{_f(tstart)}{_f(tstop)}",
        HDR,
    ]


def _death_source_eids(state: ConversionState, rec) -> Optional[List[int]]:
    """The element ids one ``*DEFINE_ELEMENT_DEATH`` card names, or ``None``.

    ``None`` means the card was warned about and must be dropped; an empty list
    means the set resolved but held nothing.
    """
    label = _death_label(rec)
    if not rec.is_set:
        return [rec.eid]
    if rec.family == "SHELL":
        entry = state.shell_sets.get(rec.eid)
        setkw = "*SET_SHELL"
    elif rec.family == "BEAM":
        entry = state.beam_sets.get(rec.eid)
        setkw = "*SET_BEAM"
    elif rec.family == "SOLID":
        entry = state.solid_sets.get(rec.eid)
        setkw = "*SET_SOLID"
    else:
        # THICK_SHELL_SET names a *SET_TSHELL, which this converter does not
        # read. Only the *SET_SOLID registry is tried as a fallback: a thick
        # shell IS a /BRICK in the emitted deck and decks do sometimes restate
        # a tshell list as a *SET_SOLID. *SET_SHELL is deliberately NOT tried —
        # *SET_TSHELL, *SET_SOLID and *SET_SHELL are three separate LS-DYNA SID
        # namespaces, and a *SET_SHELL cannot hold a thick-shell id at all, so
        # adopting one on a bare SID match would deactivate whatever solids
        # happen to share an eid with those shells (LS-DYNA element ids are
        # per-family too) — the #125/#128 two-namespace trap.
        entry = state.solid_sets.get(rec.eid)
        setkw = "*SET_TSHELL"
    if entry is None:
        state.warn(
            f"{label}: element set {rec.eid} was not found — no /ACTIV "
            f"emitted. ({setkw} is the set keyword this card names"
            + ("; k2rad reads *SET_SHELL/_SOLID/_BEAM/_DISCRETE but not "
               "*SET_TSHELL, so a thick-shell set has to be restated as a "
               "*SET_SOLID." if setkw == "*SET_TSHELL" else ".") + ")")
        return None
    return list(entry[1])


def _death_label(rec) -> str:
    return (f"*DEFINE_ELEMENT_DEATH_{rec.family}"
            f"{'_SET' if rec.is_set else ''} "
            f"{'SID' if rec.is_set else 'EID'} {rec.eid}")


def _split_death_eids(state: ConversionState, rec, eids: List[int]):
    """``({slot: [eids]}, dangling)`` — the emitted family each id belongs to.

    The screening registries are the ones filled AT the line that writes each
    element row (``state.shell_elem_ids`` etc.), never the parsed containers:
    an element whose PID has no ``*PART`` record is parsed, warned about
    ("MESH LOSS") and never written, and naming it in a group is starter
    ``ERROR ID : 69`` — which refuses the whole deck, strictly worse than
    losing the card.

    Family routing:

    * ``SHELL`` splits by EMISSION, not by the deck's spelling: since d1ade12 a
      3-corner ``*ELEMENT_SHELL`` is written as ``/SH3N``, and ``/GRSHEL/SHEL``
      resolves only 4-node ``/SHELL`` ids, so a triangle put there is silently
      absent from the group (the #122 rule). Reading ``shell_elem_ids`` vs
      ``sh3n_elem_ids`` directly means the writer and the group can never drift.
      dyna2rad instead writes ONE ``/SET/GENERAL`` id into BOTH slots
      (``convertdefineelementdeath.cxx:156-157``), which works only because its
      set is a multi-clause ``/SET/GENERAL``; with the plain per-family groups
      k2rad emits it would resolve one family twice.
    * ``THICK_SHELL`` joins the solids: ``writer/tshell.py`` writes a thick
      shell as a ``/BRICK``, so its id lives in ``solid_elem_ids`` and
      ``/GRBRIC/BRIC`` resolves it (``lecggroup.F:83`` resolves ``/GRBRIC``
      against NUMELS, i.e. every solid family including ``/TETRA4/10``).
    * ``BEAM`` splits beam-vs-re-routed-spring on the THREE PRODUCER-SPECIFIC
      registries, never on ``state.spring_elem_ids``: that union also holds
      ``*ELEMENT_DISCRETE``, ``*ELEMENT_PLOTEL``, belt and joint spring ids,
      which live in their own LS-DYNA id namespaces — an ``*ELEMENT_BEAM 50``
      beside an ``*ELEMENT_DISCRETE 50`` would otherwise put the beam in the
      spring slot (the #128 regression, verbatim).
    """
    by_slot: Dict[str, List[int]] = {}
    dangling: List[int] = []
    rerouted = (state.dbeam_spring_eids | state.spotweld_spring_eids
                | state.muscle_beam_spring_eids)
    for eid in eids:
        if rec.family in ("SOLID", "THICK_SHELL"):
            slot = "grbric" if eid in state.solid_elem_ids else None
        elif rec.family == "SHELL":
            if eid in state.shell_elem_ids:
                slot = "grshel"
            elif eid in state.sh3n_elem_ids:
                slot = "grsh3n"
            else:
                slot = None
        else:                                            # BEAM
            if eid in state.beam_elem_ids:
                slot = "grbeam"
            elif eid in rerouted:
                slot = "grspr"
            else:
                slot = None
        if slot is None:
            dangling.append(eid)
        else:
            by_slot.setdefault(slot, []).append(eid)
    return by_slot, dangling


#: ``/ACTIV`` slot → (group keyword, group-title suffix).
_DEATH_GROUP_KEYWORD = {
    "grbric": ("GRBRIC/BRIC", "bricks"),
    "grbeam": ("GRBEAM/BEAM", "beams"),
    "grspr": ("GRSPRI/SPRI", "springs"),
}


def _make_element_death(state: ConversionState) -> List[str]:
    """``*DEFINE_ELEMENT_DEATH_*`` → ``/ACTIV`` with one group per family.

    **The death-time mapping is the decision this card turns on.** LS-DYNA
    ``TIME`` defaults to ``0.0`` and means "Deletion time for elimination of
    the element or element set" (Vol I R17 p.17-251) — i.e. a blank TIME (with
    ``BOXID = 0``) deletes the elements AT ``t = 0``. Radioss reads the same
    zero the other way round: ``hm_read_activ.F:139``

        ``IF (STOPT == ZERO) STOPT = INFINITY``

    MEASURED — a ``/ACTIV`` written with ``Tstop = 0.0`` echoes
    ``STOP-TIME 0.1000000020041E+21`` and the group is never deactivated.
    dyna2rad's ``CopyValue("TIME", "Tstop")``
    (``convertdefineelementdeath.cxx:76`` and on every one of its seven
    branches) therefore INVERTS the card on LS-DYNA's own default: "delete
    immediately" becomes "never delete". k2rad refuses instead — it neither
    emits ``Tstop = 0`` nor invents a small positive one, because there is no
    number on the card to derive it from and a one-cycle-alive element is not
    what LS-DYNA does either.
    """
    if not state.element_deaths:
        return []
    lines: List[str] = []
    for rec in state.element_deaths:
        label = _death_label(rec)
        if rec.time <= 0.0:
            if rec.boxid:
                state.warn(
                    f"{label}: BOXID = {rec.boxid} (INOUT = {rec.inout}, CID "
                    f"= {rec.cid}) with TIME = {rec.time:g} is a purely "
                    "SPATIAL death: 'An element is immediately deleted upon "
                    "meeting the condition of being inside the box (or "
                    "outside the box, depending on INOUT), without regard to "
                    "TIME, IDGRP, or PERCENT', and 'If BOXID is nonzero, a "
                    "TIME value of zero is reset to 1e16' (Vol I R17 "
                    "p.17-251) — so the time criterion is switched off on "
                    "this card and only the box is left. /ACTIV is time- or "
                    "sensor-driven (hm_read_activ.F) and has no geometric "
                    "form, so nothing is expressible — no card emitted. "
                    "dyna2rad never reads BOXID at all and converts such a "
                    "card to /ACTIV Tstop = 0, i.e. to nothing happening, "
                    "silently.")
            else:
                state.warn(
                    f"{label}: TIME = {rec.time:g} means 'delete at t = 0' in "
                    "LS-DYNA (Vol I R17 p.17-251: TIME is the deletion time "
                    "and its default is 0.0), but /ACTIV reads the same zero "
                    "as 'never' — hm_read_activ.F:139 turns Tstop = 0 into "
                    "INFINITY (measured: STOP-TIME 1e+21 in the starter "
                    "echo). Copying it through, as dyna2rad does, would "
                    "invert the card, and there is no number on the card to "
                    "derive a small positive Tstop from — no /ACTIV emitted. "
                    "State a positive TIME, or delete the elements from the "
                    "mesh.")
            continue
        eids = _death_source_eids(state, rec)
        if eids is None:
            continue
        if not eids:
            state.warn(f"{label}: the element set is empty — no /ACTIV "
                       "emitted.")
            continue
        by_slot, dangling = _split_death_eids(state, rec, eids)
        if dangling:
            state.warn(
                f"{label}: element(s) {_fmt_eid_list(dangling)} reached no "
                f"/{rec.family} element in the converted deck (their part or "
                "section was dropped upstream) and were left out of the "
                "deactivation group. Naming an element the deck does not "
                "define is starter ERROR 69 and would refuse the whole run; "
                "dyna2rad drops the entire card silently in the same "
                "situation (convertdefineelementdeath.cxx:96).")
        if not by_slot:
            state.warn(f"{label}: no element of this card survived into the "
                       "converted deck — no /ACTIV emitted.")
            continue
        slots: Dict[str, int] = {}
        for slot, slot_eids in sorted(by_slot.items()):
            gid = state.next_elem_group_id()
            title = (rec.title or f"ELEMENT_DEATH_{rec.family}_{rec.eid}")
            if slot == "grshel":
                lines += _emit_grshel(gid, f"{title}_quads"[:100], slot_eids)
            elif slot == "grsh3n":
                lines += _emit_grsh3n(gid, f"{title}_trias"[:100], slot_eids)
            else:
                keyword, suffix = _DEATH_GROUP_KEYWORD[slot]
                lines += _emit_id_group(keyword, gid,
                                        f"{title}_{suffix}"[:100], slot_eids)
            slots[slot] = gid
        activ_id = state.next_id()
        lines += _activ_card(
            activ_id, rec.title or f"ELEMENT_DEATH_{rec.family}_{rec.eid}",
            slots, 0.0, rec.time)
        state.warn(
            f"{label}: TIME = {rec.time:g} -> /ACTIV/{activ_id} Iform=2 "
            f"Tstart=0 Tstop={rec.time:g} on "
            + ", ".join(f"{slot}_ID {gid}" for slot, gid
                        in sorted(slots.items()))
            + ". The group is switched OFF at t=0 and back ON in the same "
            "call (desacti.F:140-170, Tstart=0), then OFF for good once "
            "TT > Tstop; deactivated elements keep their mass — Radioss zeroes "
            "OFFG, it does not remove the nodal mass, which is what LS-DYNA "
            "element death does too. WHEN READING /TH AFTERWARDS: a 4-node "
            "shell is the one family eloff.F does NOT zero — :479 writes "
            "OFFG = -ABS(OFFG) while :418 zeroes the solids (in the dedicated "
            "IGBR pre-loop, not the ITY dispatch), :522 the beams, :565 the "
            "/SH3N and :458 the 2-D quads k2rad never emits — and its /TH "
            "force and moment channels then FREEZE at the "
            "value they held when it died instead of dropping to 0 (measured "
            "on a twin-deck pair: F1 stuck at 0.1294952 and M1 at -50.23716 "
            "for every state after Tstop). The element carries no load — a "
            "node it alone connected becomes a free particle at a = F/m, "
            "measured — the CHANNEL is stale, not the physics. NOTE: the "
            "deactivated elements' contact segments "
            "are NOT removed, and that holds REGARDLESS of the interface's "
            "Idel (k2rad writes Idel=2 on both /INTER/TYPE7 and /INTER/TYPE25). "
            "The segment-removal pass at resol.F:5015-5153 runs only on "
            "IDEL7NG>=1 .AND. IDEL7NOK==1, and IDEL7NOK is armed exclusively "
            "by element FAILURE and geometry routines (sgeodel3.F, "
            "schkjab3.F, cdt3.F, c3dt3.F, main_beam18.F, sconnect_off.F, ...) "
            "— desacti.F and eloff.F, the two routines /ACTIV goes through, "
            "never touch it. So the dead elements go on carrying contact.")
        if rec.boxid:
            state.warn(
                f"{label}: BOXID = {rec.boxid} (INOUT = {rec.inout}, CID = "
                f"{rec.cid}) has no /ACTIV slot and was dropped. It is a "
                "SECOND, independent death criterion — 'An element is "
                "immediately deleted upon meeting the condition of being "
                "inside the box (or outside the box, depending on INOUT), "
                "without regard to TIME, IDGRP, or PERCENT' (Vol I R17 "
                "p.17-251), and TIME stays live beside it (the same page "
                "resets a ZERO time to 1e16 only when BOXID is nonzero, which "
                "is what would switch the time criterion off). LS-DYNA "
                f"therefore deletes at min(box crossing, TIME = {rec.time:g}) "
                "while the converted deck keeps only the TIME half: elements "
                "that would have entered or left the box earlier now survive "
                "until Tstop. /ACTIV is time- or sensor-driven only "
                "(hm_read_activ.F) and has no geometric form.")
        if rec.idgrp:
            state.warn(
                f"{label}: IDGRP = {rec.idgrp} / PERCENT = {rec.percent:g} "
                "has no /ACTIV slot and was dropped. It is a SECOND, "
                "independent death criterion — 'All elements in a group will "
                "be simultaneously deleted one cycle after a percentage of "
                "the elements (specified in PERCENT) fail' (Vol I R17 "
                "p.17-252) — so the converted deck keeps the TIME criterion "
                "above and loses the group-failure one. Radioss has no "
                "equivalent: /ACTIV is time- or sensor-driven only.")
        elif rec.percent:
            state.warn(
                f"{label}: PERCENT = {rec.percent:g} was dropped — it only "
                "acts through IDGRP, which is 0 on this card, so LS-DYNA "
                "ignores it too.")
    if not lines:
        return []
    return ["#-  ELEMENT DEACTIVATION (*DEFINE_ELEMENT_DEATH_* -> /ACTIV):",
            HDR] + lines


# ─────────────────────────────────────────────────────────────────────────────
# *PERTURBATION_NODE → /RANDOM
# ─────────────────────────────────────────────────────────────────────────────

#: The ``SEED`` written on every ``/RANDOM``. LS-DYNA states no seed for
#: ``TYPE = 8`` (``RND`` exists only on the ``TYPE = 4`` spectral card,
#: Vol I R17 p.38-9), so the number is not carried over from anything — it is
#: chosen, once, so that the perturbed mesh is REPRODUCIBLE: ``aleat.F:44-46``
#: seeds its LCG from ``I = SEED*32768 + 32768`` on the first call only, and
#: MEASURED, two runs of the same deck moved all 1000 probe nodes by
#: byte-identical amounts. 0.5 is the midpoint of the documented ``[0,1)``
#: range (Reference Guide p.122); it is a reproducibility knob, not a physical
#: quantity, which is why choosing it is not the "invented load" case.
_RANDOM_SEED = 0.5


def _perturbation_label(rec) -> str:
    return (f"*PERTURBATION_NODE TYPE={rec.ptype} "
            + (f"NSID={rec.nsid}" if rec.nsid else "NSID=0 (all nodes)"))


def _random_xalea(state: ConversionState, rec) -> Optional[float]:
    """``XALEA`` for one ``TYPE = 8`` record, or ``None`` to drop it.

    ``/RANDOM`` adds ``XALEA*ALEAT()`` to each of ``X(1..3,I)``, and
    ``aleat.F:48-49`` returns ``(I - 32768.)/32768.`` — uniform on ``(-1, +1)``
    and SYMMETRIC. MEASURED on a 1000-node block at ``XALEA = 0.5``: dX/dY/dZ
    spanned -0.4997..+0.4998 with std 0.293/0.288/0.294 against the theoretical
    ``XALEA/sqrt(3) = 0.2887``. (The Reference Guide's "random number is
    defined between 0 and 1", p.122 comment 1, is contradicted by the source
    and by that measurement — do not build a factor on it.)

    So ``DTYPE = 1.0`` ("Uniform distribution between SCL x [-AMPL, AMPL]",
    Vol I R17 p.38-10) is an exact match at ``XALEA = SCL*AMPL``, while
    ``DTYPE = 0.0`` — the DEFAULT — is the one-sided ``SCL x [0, AMPL]``:
    zero-mean noise of half-width ``SCL*AMPL/2`` plus a rigid shift of
    ``+SCL*AMPL/2`` on every axis. ``XALEA = SCL*AMPL/2`` reproduces the noise
    EXACTLY (matching both the half-width and the standard deviation) and drops
    only that rigid translation. dyna2rad ignores DTYPE altogether and writes
    ``SCL*AMPL`` for both, i.e. double the spread on the default form.
    """
    label = _perturbation_label(rec)
    amplitude = rec.scl * rec.ampl
    if amplitude == 0.0:
        state.warn(f"{label}: SCL*AMPL = 0, so the perturbation has zero "
                   "amplitude — no /RANDOM emitted (hm_read_rand.F:119 skips "
                   "a record with XALEA <= 0 anyway).")
        return None
    if amplitude < 0.0:
        state.warn(f"{label}: SCL*AMPL = {amplitude:g} is negative; XALEA is "
                   "a half-width and hm_read_rand.F:119 ignores a record with "
                   "XALEA <= 0 — no /RANDOM emitted.")
        return None
    if rec.dtype == 0.0:
        state.warn(
            f"{label}: DTYPE = 0 is the one-sided uniform distribution "
            f"SCL x [0, AMPL] = [0, {amplitude:g}] (Vol I R17 p.38-10), while "
            "Radioss's ALEAT() is symmetric on (-XALEA, +XALEA) "
            f"(aleat.F:48-49). XALEA = SCL*AMPL/2 = {amplitude / 2.0:g} was "
            "written, which reproduces the zero-mean noise exactly (same "
            "half-width, same standard deviation) and drops only the rigid "
            f"translation of +{amplitude / 2.0:g} per axis that the one-sided "
            "form also applies. dyna2rad drops DTYPE entirely and writes "
            "SCL*AMPL, i.e. twice the spread.")
        return amplitude / 2.0
    return amplitude


def _make_random(state: ConversionState) -> List[str]:
    """``*PERTURBATION_NODE`` → ``/RANDOM`` or ``/RANDOM/GRNOD``.

    Card body (``radioss110/CARDS/random.cfg:84-118``): no title, no block id,
    one ``%20lg%20lg`` card carrying ``XALEA`` and ``SEED``; the group form
    carries its ``grnod_ID`` in the HEADER, ``/RANDOM/GRNOD/<id>``.

    **The global and the grouped form cannot coexist.**
    ``hm_read_rand.F:152/156/175`` runs the all-nodes branch only when
    ``NRANDG == 0`` and the group branch only when ``IALL == 0``, so a deck
    holding one of each executes NEITHER — MEASURED: no ``RANDOM NOISE`` block
    in the ``.out`` at all, 0 ERROR, 0 WARNING, and not one node moved. One
    LS-DYNA deck may legitimately carry an ``NSID = 0`` card beside an
    ``NSID > 0`` one, so the conflict is resolved HERE rather than shipped.
    """
    if not state.perturbation_nodes:
        return []
    convertible = []
    for rec in state.perturbation_nodes:
        label = _perturbation_label(rec)
        if rec.ptype != 8:
            what = {
                1: ("a HARMONIC field — a deterministic, spatially correlated "
                    "sum of three sines (Vol I R17 p.38-10 Remark 3), i.e. a "
                    "shaped buckling trigger, not noise"),
                2: ("a FADE field, which does not perturb anything itself: it "
                    "scales the OTHER perturbations down with distance from "
                    "this node set (p.38-11 Remark 4)"),
                3: ("perturbations READ FROM A FILE (FNAME)"),
                4: ("a SPECTRAL field with a stated correlation structure "
                    "(CSTYPE/CFTYPE/ELLIPn), i.e. correlated random noise"),
            }.get(rec.ptype, "an unknown perturbation TYPE")
            extra = ""
            if rec.ptype in (1, 2, 4):
                extra = (" dyna2rad converts this TYPE to /RANDOM anyway, "
                         "replacing the field with white noise of amplitude "
                         + ("SCL*AMPL" if rec.ptype == 1 else "SCL") + ".")
            state.warn(
                f"{label}: TYPE = {rec.ptype} is {what}. Radioss /RANDOM is "
                "per-node UNIFORM noise on the three coordinates and can "
                "express none of it, so nothing was emitted — only TYPE = 8 "
                "('Random value from uniform distribution') converts." + extra)
            continue
        if rec.cmp != 7:
            state.warn(
                f"{label}: CMP = {rec.cmp} restricts the perturbation to "
                + {1: "x", 2: "y", 3: "z", 4: "x and y", 5: "y and z",
                   6: "z and x"}.get(rec.cmp, f"component {rec.cmp}")
                + ", but /RANDOM always moves ALL THREE coordinates "
                "(hm_read_rand.F:161-163 writes X(1..3,I) unconditionally). "
                "The perturbation below is 3-axis; the constrained directions "
                "gain noise the deck did not ask for.")
        if rec.icoord or rec.cid:
            state.warn(
                f"{label}: ICOORD = {rec.icoord} / CID = {rec.cid} states a "
                "cylindrical, spherical or user-Cartesian frame for the "
                "perturbation (Vol I R17 p.38-5). /RANDOM perturbs the GLOBAL "
                "cartesian coordinates only and has no frame column — the "
                "frame was dropped, so a radial perturbation becomes an "
                "isotropic one.")
        xalea = _random_xalea(state, rec)
        if xalea is None:
            continue
        if rec.nsid and rec.nsid not in state.node_sets:
            state.warn(
                f"{label}: *SET_NODE {rec.nsid} was not found — no /RANDOM "
                "emitted. A /RANDOM/GRNOD naming a group the deck does not "
                "define is starter ERROR 173 ('NODE GROUP ID=%d DOES NOT "
                "EXIST'), which refuses the whole run.")
            continue
        convertible.append((rec, xalea))
    if not convertible:
        return []
    globals_ = [(r, x) for r, x in convertible if not r.nsid]
    grouped = [(r, x) for r, x in convertible if r.nsid]
    if globals_ and grouped:
        state.warn(
            "*PERTURBATION_NODE: this deck states both an all-nodes card "
            "(NSID = 0) and "
            + (f"{len(grouped)} node-set card(s) "
               f"(NSID {', '.join(str(r.nsid) for r, _ in grouped)})")
            + ". A global /RANDOM and a /RANDOM/GRNOD cannot coexist: "
            "hm_read_rand.F:152/156/175 runs the all-nodes branch only when "
            "NRANDG == 0 and the group branch only when IALL == 0, so a deck "
            "carrying both perturbs NOTHING — measured, at 0 ERROR and 0 "
            "WARNING. The all-nodes card was kept (it already covers every "
            "node the sets name) and the per-set amplitudes were dropped; "
            "split them into separate runs if the amplitudes differ.")
        grouped = []
    if len(globals_) > 1:
        # hm_read_rand.F:135-136 OVERWRITES the module-level XALEA on every
        # all-nodes record (`IALL = IALL+1; XALEA = ALEA(I)`) and the
        # application loop at :156-163 then adds XALEA*ALEAT() ONCE per node —
        # so a second global card silently makes the first one inert. LS-DYNA
        # instead SUMS them ('Perturbations specified using separate
        # *PERTURBATION cards are created separately and then added together',
        # Vol I R17 p.38-10 Remark 2). (The grouped form is not affected: its
        # loop applies each group's own ALEA(I).)
        kept_i = max(range(len(globals_)), key=lambda i: globals_[i][1])
        dropped_x = [x for i, (_r, x) in enumerate(globals_) if i != kept_i]
        kept = globals_[kept_i]
        globals_ = [kept]
        state.warn(
            "*PERTURBATION_NODE: this deck states "
            f"{len(dropped_x) + 1} all-nodes cards (NSID = 0). LS-DYNA sums "
            "separate *PERTURBATION cards ('created separately and then added "
            "together', Vol I R17 p.38-10 Remark 2), but /RANDOM cannot: "
            "hm_read_rand.F:135-136 overwrites ONE module-level XALEA per "
            "all-nodes record and :156-163 applies it once, so the earlier "
            "cards would be silently inert. The largest amplitude "
            f"(XALEA = {kept[1]:g}) was kept and "
            + ", ".join(f"XALEA = {x:g}" for x in sorted(dropped_x))
            + " dropped. The sum of two independent uniform deviates is not "
            "uniform, so no single XALEA reproduces it; state one card, or "
            "run the perturbations as separate models.")
    lines: List[str] = []
    for rec, xalea in globals_ + grouped:
        label = _perturbation_label(rec)
        head = f"/RANDOM/GRNOD/{rec.nsid}" if rec.nsid else "/RANDOM"
        lines += [head,
                  "#              XALEA                SEED",
                  f"{_f(xalea)}{_f(_RANDOM_SEED)}",
                  HDR]
        state.warn(
            f"{label}: -> {head} XALEA={xalea:g} SEED={_RANDOM_SEED:g}. "
            "/RANDOM displaces the nodal coordinates at STARTER time "
            "(hm_read_rand.F:161-163 / :184-186 add XALEA*ALEAT() to "
            "X(1..3,I)), so the restart file already carries the perturbed "
            "mesh and there is no engine-side component — the same thing "
            "*PERTURBATION_NODE does ('modifies the three-dimensional "
            "coordinates', Vol I R17 p.38-2). LS-DYNA states no seed for "
            "TYPE 8, so SEED was chosen to make the mesh reproducible; note "
            "aleat.F's generator is seeded ONCE per run, so only the first "
            "/RANDOM card's SEED takes effect.")
    return ["#-  NODAL COORDINATE NOISE (*PERTURBATION_NODE -> /RANDOM):",
            HDR] + lines


# ─────────────────────────────────────────────────────────────────────────────
# *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY → /IMPDISP/FGEO
# ─────────────────────────────────────────────────────────────────────────────

def _fgeo_rows(state: ConversionState, rec):
    """Expand one card's node rows into ``[(nid, xf, yf, zf, lcid, death,
    birth)]``, resolving the negative-NID set form.

    ``NID < 0`` makes ``|NID|`` a ``*SET_NODE`` "for which the final projection
    plane normal to the global z-axis is defined. In this case, only the offset
    Z value is needed, and all the nodes in this node set are displaced from
    their initial positions to the projected points on the xy-plane with Z
    offset" (Vol I R17 p.5-74) — so each member keeps its OWN x and y and moves
    only in z. dyna2rad pushes the SAME ``(X, Y, Z)`` for every member
    (``convertbcs.cxx:741-746``), collapsing the whole set onto one point.

    The per-row ``LCID``/``DEATH`` override the header defaults when nonzero
    ("Load curve ID for NID. If zero, the default curve ID, LCIDF, is used",
    p.5-75); dyna2rad reads neither.
    """
    out = []
    for row in rec.nodes:
        lcid = row.lcid or rec.lcidf
        death = row.death or rec.deathd
        birth = row.birth
        if row.nid > 0:
            if row.nid not in state.nodes:
                state.warn(
                    f"{_fgeo_label(rec)}: node {row.nid} is not in the "
                    "converted deck — row dropped. A /IMPDISP/FGEO row naming "
                    "an unknown node is a starter USR2SYS failure, and the "
                    "manual requires it too ('Nodes defined in this section "
                    "must also appear under the *NODE input', Vol I R17 "
                    "p.5-74).")
                continue
            out.append((row.nid, row.x, row.y, row.z, lcid, death, birth))
            continue
        nsid = -row.nid
        entry = state.node_sets.get(nsid)
        if entry is None:
            state.warn(
                f"{_fgeo_label(rec)}: row NID = {row.nid} names *SET_NODE "
                f"{nsid} (a negative NID is a node SET id, Vol I R17 p.5-74) "
                "and that set was not found — row dropped.")
            continue
        missing = [n for n in entry[1] if n not in state.nodes]
        if missing:
            state.warn(
                f"{_fgeo_label(rec)}: *SET_NODE {nsid} lists node(s) "
                f"{_fmt_eid_list(missing)} the converted deck does not define "
                "— they were left out of the projection.")
        members = [n for n in entry[1] if n in state.nodes]
        if members:
            state.warn(
                f"{_fgeo_label(rec)}: row NID = {row.nid} projects the "
                f"{len(members)} node(s) of *SET_NODE {nsid} onto the plane "
                f"z = {row.z:g}, each KEEPING its own x and y (Vol I R17 "
                "p.5-74). dyna2rad instead writes the single triple "
                f"({row.x:g}, {row.y:g}, {row.z:g}) for every member "
                "(convertbcs.cxx:741-746), i.e. collapses the set onto one "
                "point.")
        for n in members:
            nd = state.nodes[n]
            out.append((n, nd.x, nd.y, row.z, lcid, death, birth))
    return out


def _fgeo_label(rec) -> str:
    return f"*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY BPFGID {rec.bpfgid}"


def _warn_fgeo_curve_range(state: ConversionState, label: str,
                           lcid: int) -> None:
    """Name a driver curve that is not the 0 → 1 scale factor the card needs.

    *"A load curve defines a scale factor as a function of time that is bounded
    between zero and unity corresponding to the initial and final geometry"*
    (Vol I R17 p.5-73), and the engine takes that literally:
    ``fixfingeo.F:243-256`` computes ``X(t) = X0 + f(t)·(Xf − X0)`` with NO
    clamp on ``f``, so an ordinate of 200 sends the node 200 × the stated offset
    and an ordinate that returns to 0 brings it back to where it started.

    NOR does the engine hold the last ordinate PAST the curve. The FGEO
    consumer's interpolators both extrapolate the last segment —
    ``FINTER2`` linearly, ``FINTER2_SMOOTH`` (``finter_smooth.F:116-152``) with
    the same quintic, neither with a clamp — so unless ``Tstop`` bounds the
    card (a ``DEATH`` of 0 becomes INFINITY, ``read_impdisp_fgeo.F:161``) the
    node does not stop at the last point, it keeps going. MEASURED past a
    smooth curve's last vertex: ``f`` = −0.0117 / −0.406 / −2.379 / −7.624 at
    ``t`` = 13.20 / 13.60 / 14.00 / 14.38 ms on a curve ending at 13 ms, the
    quintic ``1−S(u)`` to five digits, and the run died on the energy-error
    limit under a ``NORMAL TERMINATION`` banner.

    Reachable and silent until now. A ``*DEFINE_CURVE_SMOOTH`` in particular can
    NEVER satisfy the requirement: it is a velocity trapezoid whose plateau is
    ``VMAX`` and whose last vertex is ``(TEND, 0)`` by construction. MEASURED on
    a probe pairing the two: with ``VMAX = 200`` the driven tip reached 98 mm on
    a 1 mm offset by ``t = 2.5 ms`` and the run died on the energy-error limit —
    under a ``NORMAL TERMINATION`` banner.
    """
    curve = state.curves.get(lcid)
    if not curve or not curve.pts:
        return
    ords = [o for _a, o in curve.pts]
    end, top, bot = ords[-1], max(ords), min(ords)
    smooth = lcid in state.funct_smooth_ids
    if abs(end - 1.0) <= 1.0e-6 and top <= 1.0 + 1.0e-6 and bot >= -1.0e-6:
        return
    # Lead with the clause that is actually out of range. A curve whose
    # ordinates are already bounded by 1 trips the gate on its END VALUE alone,
    # and opening with "an ordinate of 1 sends the node 1 times the offset" —
    # the CORRECT behaviour — reads as a self-contradiction.
    over = top > 1.0 + 1.0e-6 or bot < -1.0e-6
    consequence = (
        f"an ordinate of {top:g} sends every listed node {top:g} times the "
        "stated offset"
        + (f" and an end value of {end:g} leaves it there" if end else
           " and an end value of 0 brings it back to where it started")
        if over else
        (f"an end value of {end:g} leaves every listed node at {end:g} times "
         "the stated offset" if end else
         "an end value of 0 brings every listed node back to where it started, "
         "not to the geometry the node rows name"))
    state.warn(
        f"{label}: load curve {lcid} is not the 0 -> 1 scale factor this card "
        f"needs — its ordinates run {bot:g} .. {top:g} and end at {end:g}. "
        "'A load curve defines a scale factor as a function of time that is "
        "bounded between zero and unity corresponding to the initial and final "
        "geometry' (Vol I R17 p.5-73), and fixfingeo.F:243-256 computes "
        "X(t) = X0 + f(t)*(Xf - X0) with NO clamp on f, so "
        + consequence
        + ". The curve is written through as stated — nothing on the card "
        "derives a rescaling, and inventing one would be a fabricated motion — "
        "but the resulting positions are not the ones the node rows name. "
        "PAST its last abscissa the curve is not held either: fixfingeo.F "
        "extrapolates the last segment (FINTER2 linearly, FINTER2_SMOOTH with "
        "the same quintic — finter_smooth.F:116-152 has no clamp), so unless "
        "DEATH bounds this card the node keeps moving. MEASURED on the smooth "
        "pairing: f reached -7.62 past a curve ending at 0 and the run died on "
        "the energy-error limit under a NORMAL TERMINATION banner."
        + (" NOTE: curve " + str(lcid) + " is a *DEFINE_CURVE_SMOOTH, which "
           "can never satisfy this: it is a VELOCITY trapezoid whose plateau "
           "is VMAX and whose last vertex is (TEND, 0) by construction. The "
           "two keywords do not pair." if smooth else ""))


def _make_impdisp_fgeo(state: ConversionState) -> List[str]:
    """``*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY`` → one ``/IMPDISP/FGEO`` per
    distinct ``(LCID, DEATH, BIRTH)`` triple.

    Card body (``radioss140/LOADS/impdisp_fgeo.cfg:118-145``, the only FORMAT
    in the file)::

        /IMPDISP/FGEO/<id>
        <title>
        #   fct_ID   part_ID             sens_ID
        #             Ascale                                  Tstart               Tstop
        # node_IDN                  Xn                  Yn                  Zn

    The engine realises exactly ``X(t) = X0 + f(Ascale*t) * (Xf - X0)``:
    ``read_impdisp_fgeo.F:175-207`` stores ``DIST = |Xf - X0|`` and the unit
    direction, and ``fixfingeo.F:243-256`` drives the node along it, overwriting
    the whole acceleration vector with the axial component. MEASURED to seven
    digits against a 0->1 ramp.

    Radioss carries ONE ``fct_ID``, ``Tstart`` and ``Tstop`` per card while
    LS-DYNA allows a per-node ``LCID``, ``DEATH`` and ``BIRTH``, so the rows are
    partitioned. dyna2rad reads only the header ``LCIDF``/``DEATHD``
    (``convertbcs.cxx:719-720``) and emits one card.

    ``Tstop = 0`` is written through UNCHANGED here, and that is CORRECT even
    though the identical idiom inverts ``/ACTIV``: ``read_impdisp_fgeo.F:161``
    turns ``Tstop = 0`` into INFINITY, and LS-DYNA's ``DEATHD`` default is
    "infinity" too (Vol I R17 p.5-73). Same starter idiom, opposite verdict —
    checked per card.
    """
    if not state.final_geometries:
        return []
    lines: List[str] = []
    # /IMPDISP and /IMPDISP/FGEO are ONE id namespace: hm_read_impvel.F:96-129
    # counts them together (NIMPDISP includes FGEOD) and runs ONE UDOUBLE scan
    # over the merged NOM_OPT slice, so a user BPFGID landing on a synthesized
    # /IMPDISP id is ERROR 79 over the whole table.
    #
    # The *BOUNDARY_PRESCRIBED_MOTION writers run BEFORE this section in
    # _starter_section_registry and record every id at the line that writes it
    # (_emit_imp_card), so those are screened HERE. The rigid-wall geometric
    # motion path (loads._emit_rwall_geom_motion) is the one /IMPDISP producer
    # whose section runs AFTER this one, so its ids cannot be seen from here —
    # it dodges the deck's BPFGIDs from its own side instead
    # (state.next_impdisp_id). Between the two directions the pair is covered,
    # and _warn_duplicate_impdisp_ids is the deck-wide backstop.
    used_ids: Set[int] = set(state.imp_card_ids.get("IMPDISP", set()))
    for rec in state.final_geometries:
        label = _fgeo_label(rec)
        # One range diagnostic per (DECK CARD, curve): a single card whose rows
        # split into several /IMPDISP/FGEO must not repeat it, but a SECOND
        # *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY driven by the same curve must
        # still be named — the warning quotes {label}, so hoisting this set out
        # of the loop silently dropped the diagnostic for every card after the
        # first (measured: BPFGID 800 named, BPFGID 801 emitted in silence).
        range_checked: Set[int] = set()
        rows = _fgeo_rows(state, rec)
        if not rows:
            state.warn(f"{label}: no usable node row — no /IMPDISP/FGEO "
                       "emitted.")
            continue
        groups: Dict[Tuple[int, float, float], List] = {}
        for nid, xf, yf, zf, lcid, death, birth in rows:
            groups.setdefault((lcid, death, birth), []).append(
                (nid, xf, yf, zf))
        if len(groups) > 1:
            state.warn(
                f"{label}: the node rows state {len(groups)} distinct "
                "(LCID, DEATH, BIRTH) combinations, so they were split into "
                f"{len(groups)} /IMPDISP/FGEO cards. Radioss carries one "
                "fct_ID and one Tstart/Tstop per card "
                "(impdisp_fgeo.cfg:118-145) while LS-DYNA lets every node "
                "state its own; a single card would have applied the header's "
                "LCIDF/DEATHD to all of them, which is what dyna2rad does "
                "(convertbcs.cxx:719-720 reads no per-row value at all).")
        for (lcid, death, birth), members in sorted(
                groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            if lcid <= 0 or lcid not in state.curves:
                state.warn(
                    f"{label}: load curve {lcid} is not defined in the "
                    f"converted deck — the {len(members)} node row(s) using "
                    "it were dropped. fct_ID is mandatory on /IMPDISP/FGEO "
                    "(impdisp_fgeo.cfg:118-145) and the engine multiplies it "
                    "straight into DIST (fixfingeo.F:243), so a zero or "
                    "dangling id is a wrong answer, not a missing one.")
                continue
            if lcid not in range_checked:
                range_checked.add(lcid)
                _warn_fgeo_curve_range(state, label, lcid)
            fct_id = lcid
            if birth:
                curve = state.curves[lcid]
                fct_id = state.next_curve_id()
                shifted = [(a + birth, o) for a, o in curve.pts]
                # The copy has to keep the SOURCE curve's card kind. A
                # *DEFINE_CURVE_SMOOTH re-emitted as a plain /FUNCT loses the
                # ISMOOTH flag (fixfingeo.F:194-195 reads it from
                # NPC(2*NFUNCT+L+1)), and :196-199 then picks FINTER2 instead
                # of FINTER2_SMOOTH: the quintic blend becomes piecewise-linear
                # — a DIFFERENT motion for the same four points (MEASURED: f =
                # 0.1036 vs 0.2503 at u = 0.25, 2.42x).
                #
                # NOT a clamp question. Neither branch clamps on this path:
                # FINTER2_SMOOTH (finter_smooth.F:116-152) walks IPOS to the
                # last segment and evaluates the quintic with u > 1, so the
                # SMOOTH copy actually runs FURTHER past the end of the curve
                # than the plain one, not less. The clamping routines are other
                # entry points with other callers — FINTER_SMOOTH
                # (finter_smooth.F:71/74, gravit.F/forcefingeo.F) and
                # VINTER_SMOOTH (vinter_smooth.F:68-71), which is what the
                # /IMPVEL path uses (fixvel.F:314/316).
                smooth = lcid in state.funct_smooth_ids
                kind = "/FUNCT_SMOOTH" if smooth else "/FUNCT"
                lines += _emit_funct(
                    fct_id, f"FGEO_{rec.bpfgid}_LCID_{lcid}_BIRTH_{birth:g}",
                    shifted, smooth=smooth)
                if smooth:
                    state.funct_smooth_ids.add(fct_id)
                state.warn(
                    f"{label}: BIRTH = {birth:g} was written as Tstart = "
                    f"{birth:g} AND as a copy of curve {lcid} with every "
                    f"abscissa shifted by +{birth:g} ({kind}/{fct_id}). "
                    "LS-DYNA's BIRTH does BOTH: 'The prescribed motion begins "
                    "acting at time = BIRTH, but with the motion from the "
                    "zero-abscissa value of the curve LCID. In other words, "
                    "the abscissa values are shifted by an amount BIRTH, such "
                    "that it has the same effect as setting OFFA = BIRTH' "
                    "(Vol I R17 p.5-75), while Radioss's Tstart is a PURE "
                    "GATE — fixfingeo.F:155 skips the node before Tstart and "
                    ":168 evaluates the curve at the raw TT, with no shift. "
                    "Emitting Tstart alone would run the tail of the curve; "
                    "shifting alone would move the node before BIRTH.")
            impdisp_id = rec.bpfgid if rec.bpfgid > 0 else 0
            if impdisp_id <= 0 or impdisp_id in used_ids:
                taken = impdisp_id
                impdisp_id = state.next_id()
                while impdisp_id in used_ids:
                    impdisp_id = state.next_id()
                if taken > 0:
                    state.warn(
                        f"{label}: BPFGID {taken} is already in use by another "
                        "/IMPDISP or /IMPDISP/FGEO card in the converted deck "
                        "(that can be a *BOUNDARY_PRESCRIBED_MOTION card, or "
                        "an earlier slice of THIS card when its node rows were "
                        "split by (LCID, DEATH, BIRTH)), so this block was "
                        f"renumbered to {impdisp_id}. /IMPDISP and "
                        "/IMPDISP/FGEO are ONE id namespace — "
                        "hm_read_impvel.F:96-129 counts them together and runs "
                        "one UDOUBLE duplicate scan over the merged table, so "
                        f"leaving both on {taken} would be ERROR 79.")
            used_ids.add(impdisp_id)
            # Recorded for the producers that run LATER (the rigid-wall
            # geometric motion path mints its /IMPDISP ids from
            # state.next_impdisp_id, which reads this).
            state.imp_card_ids.setdefault("IMPDISP", set()).add(impdisp_id)
            title = rec.title or f"FINAL_GEOMETRY_{rec.bpfgid}"
            lines += [
                f"/IMPDISP/FGEO/{impdisp_id}",
                title[:100],
                "#   fct_ID   part_ID             sens_ID",
                f"{_i(fct_id)}{_i(0)}{' ' * 10}{_i(0)}",
                "#             Ascale                                  "
                "Tstart               Tstop",
                f"{_f(1.0)}{' ' * 20}{_f(birth)}{_f(death)}",
                "# node_IDN                  Xn                  Yn"
                "                  Zn",
            ]
            for nid, xf, yf, zf in members:
                lines.append(f"{_i(nid)}{_f(xf)}{_f(yf)}{_f(zf)}")
            lines.append(HDR)
            state.warn(
                f"{label}: -> /IMPDISP/FGEO/{impdisp_id} fct_ID={fct_id} "
                f"Tstart={birth:g} Tstop={death:g} on {len(members)} node(s). "
                "The curve must range 0 -> 1 ('A load curve defines a scale "
                "factor as a function of time that is bounded between zero "
                "and unity corresponding to the initial and final geometry', "
                "Vol I R17 p.5-73): the engine computes "
                "X(t) = X0 + f(t)*(Xf - X0) and does NOT clamp f — measured, "
                "a plain /FUNCT that keeps rising carries the node straight "
                "past its final position. Tstop=0 is written through on "
                "purpose: read_impdisp_fgeo.F:161 turns it into INFINITY, "
                "which is exactly LS-DYNA's DEATHD default.")
    if not lines:
        return []
    return ["#-  PRESCRIBED FINAL GEOMETRY "
            "(*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY -> /IMPDISP/FGEO):",
            HDR] + lines


# ─────────────────────────────────────────────────────────────────────────────
# *INTERFACE_SPRINGBACK_LSDYNA → the engine /DYNAIN block
# ─────────────────────────────────────────────────────────────────────────────

#: ``fredynain.F:101-105`` reads the ``/DYNAIN/DT`` data line with
#: ``READ(IUSC2,*)`` into a fixed ``IV2(10)``, and ``:108-126`` reads the part
#: ids the same way — at most TEN ids per line before the array is overrun.
_DYNAIN_IDS_PER_LINE = 10

#: ``fredynain.F:140`` accepts the card on ``KEY3(1:5) == 'STRAI'``, so both
#: ``/DYNAIN/SHELL/STRAI/FULL`` and ``/DYNAIN/SHELL/STRAIN/FULL`` parse — but
#: they are NOT equivalent, and the difference is silent.
#:
#: ``check_qeph_stra.F:64-76`` runs inside the STARTER: it opens
#: ``<root>_0001.rad``, scans it for a line whose first 25 characters are
#: EXACTLY ``/DYNAIN/SHELL/STRAIN/FULL`` (or ``/STATE/SHELL/STRAIN/GLOBF``),
#: and sets ``ISTR_24 = 1``. ``elbuf_ini.F:1588`` then allocates
#: ``GBUF%G_STRPG = 4*GBUF%G_STRA`` for every QEPH shell group, and that is
#: the ONLY thing that makes ``dynain_c_strag.F:151`` lift ``NPG`` to 4 —
#: ``:152`` ``CYCLE``s the group when it did not, leaving ``LEN`` at 0 so the
#: ``:392`` write gate never opens.
#:
#: The SHORT spelling is 24 characters and does not match that comparison, so
#: on a QEPH deck it silently loses the whole strain block. MEASURED, spelling
#: twin — the same starter deck, the same engine deck apart from this one
#: card, both NORMAL TERMINATION at 0 ERROR / 0 WARNING, 20 cycles::
#:
#:     /DYNAIN/SHELL/STRAIN/FULL  ->  22 225 B, 366 lines: *NODE,
#:                                    *ELEMENT_SHELL_THICKNESS,
#:                                    *INITIAL_STRESS_SHELL AND
#:                                    *INITIAL_STRAIN_SHELL (164 records,
#:                                    eps_XX 4.674E-03 ...)
#:     /DYNAIN/SHELL/STRAI/FULL   ->  12 422 B, 195 lines: NO strain block
#:
#: The deck was implicit, where ``_elform_to_ishell`` always returns Ishell 24
#: — so EVERY implicit springback deck this converter writes is QEPH and rides
#: entirely on getting this one string right. No warning is emitted for it,
#: because k2rad always writes the long form and a warning would only fire on
#: correct decks; the constant makes it a REGRESSION FENCE instead, asserted
#: character for character by tests/test_side_defects.py.
_DYNAIN_STRAIN_CARD = "/DYNAIN/SHELL/STRAIN/FULL"

#: ``TDYNAIN0`` and ``DTDYNAIN0``, as fractions of ENDTIM: write from 90 % of
#: the run on, every 2 %, so at most six files (the triggers at 0.90, 0.92,
#: ..., 1.00 ENDTIM) and the last of them lands within one interval of
#: termination. It is a SCHEDULE, not a terminal-state capture: ``GENDYNAIN``
#: fires from ``sortie_main.F:922`` on ``TT >= TDYNAIN``, so the newest file
#: sits at the last trigger an output pass crossed — up to ``DTDYNAIN0``
#: before ENDTIM, and further back if the engine's own output cadence is
#: coarser than that.
#:
#: **Neither ``ENDTIM ENDTIM`` (dyna2rad's choice, convertcards.cxx:1242-1243)
#: nor a single near-terminal trigger can be relied on, and the reason is a
#: dead branch in the engine.** ``sortie_main.F:922`` fires ``GENDYNAIN`` on
#: ``TT >= TDYNAIN`` and ``SORTIE_MAIN`` is called once per cycle
#: (``resol.F:8233``, unconditional) — but an explicit run's last computed
#: cycle lands BELOW ``TSTOP`` and the overshoot ``TT > TSTOP`` happens in the
#: time-update block AFTER that call. The end-of-run rescue
#: (``resol.F:8358-8368``) does set ``ILASTDYNAIN = 1`` and pull ``TDYNAIN``
#: back to ``TT - 1e-10`` there — but ``ILASTDYNAIN`` is then never READ again:
#: the "run one more cycle" decision at ``resol.F:9265-9295`` is taken on
#: ``ILASTANIM`` and ``ILASTH3D`` only. So a terminal dynain is written only
#: when an ANIMATION or H3D extra cycle happens to be triggered as well, which
#: depends on where the animation schedule falls relative to the final cycles.
#:
#: MEASURED on one deck (ENDTIM = 1.0e-2, 3478 cycles, dt growing from 1.15e-6
#: to 5.5e-4 so that an animation was written on each of the last cycles):
#: ``/DYNAIN/DT 0.0098 1E+30`` wrote ZERO files at NORMAL TERMINATION, 0 ERROR,
#: 0 WARNING; ``/DYNAIN/DT 0.009 0.0002`` (this recipe) wrote two, the second at
#: the run's very last cycle. Both the per-part and the ``/ALL`` form behaved
#: identically.
_DYNAIN_TSTART_FRACTION = 0.9
_DYNAIN_INTERVAL_FRACTION = 0.02


def _springback_label(rec) -> str:
    return f"*{rec.keyword} PSID {rec.psid}"


def _warn_springback_dropped_fields(state: ConversionState, label: str,
                                    rec) -> None:
    """Name every *INTERFACE_SPRINGBACK cell that has no /DYNAIN slot.

    Called on EVERY card, including the three the writer refuses (no
    ENDTIM, deck-wide shell-free, part list with no shell): a refusal is a
    reason not to emit a block, not a reason to stop accounting for the
    fields the card states. README's "none has a /DYNAIN counterpart; each
    is named" is a promise about the CARD, not about the cards that happen
    to convert.
    """
    dropped = []
    if rec.nhsv:
        dropped.append(
            f"NHSV={rec.nhsv} (extra element history variables beyond the "
            "six stresses and the effective plastic strain; the Radioss "
            "dynain writes exactly stress + EPSP, dynain_c_strsg.F:1100)")
    if rec.ftype:
        dropped.append(
            f"FTYPE={rec.ftype} (file format: binary/LSDA/large; "
            "gendynain.F writes ASCII, optionally gzipped)")
    if rec.ftensr:
        dropped.append(
            f"FTENSR={rec.ftensr} (dump *MAT_190 history tensors in the "
            "global frame)")
    if rec.rflag:
        dropped.append(
            f"RFLAG={rec.rflag} (carry over reference coordinates and "
            "nodal masses)")
    if rec.intstrn:
        dropped.append(
            f"INTSTRN={rec.intstrn} (strains at ALL through-thickness "
            "integration points; /DYNAIN/SHELL/STRAIN/FULL writes what "
            "dynain_c_strag.F writes and has no such switch)")
    if rec.nthhsv:
        dropped.append(
            f"NTHHSV={rec.nthhsv} (thermal history variables; the "
            "/STATE/NODE/TEMP dyna2rad reaches for writes a Radioss .sta, "
            "not a dynain)")
    if rec.has_optcard:
        dropped.append(
            f"the OPTCARD card (SLDO={rec.sldo} NCYC={rec.ncyc} "
            f"FSPLIT={rec.fsplit} NDFLAG={rec.ndflag} CFLAG={rec.cflag} "
            f"HFLAG={rec.hflag}) — none of it has a /DYNAIN counterpart. "
            "NDFLAG in particular is a NODE-DUMP flag ('Flag to dump "
            "nodes into dynain file'), NOT a part-scope flag; dyna2rad "
            "maps NDFLAG>0 to /STATE/DT/ALL (convertcards.cxx:1097), "
            "which silently discards PSID and widens the output to the "
            "whole model")
    if rec.dtwrt or rec.nmwrt or rec.ivflg:
        dropped.append(
            f"the OPTCARD 3.1/3.2 cards (DTWRT={rec.dtwrt:g} "
            f"NMWRT={rec.nmwrt} IVFLG={rec.ivflg})")
    if rec.constraints:
        dropped.append(
            f"{len(rec.constraints)} Card-4 node constraint row(s) "
            "(NID/TC/RC) — springback constraints for the SEAMLESS "
            "option, which no engine keyword can carry into the dynain")
    if rec.keyword.endswith("_NOTHICKNESS"):
        dropped.append(
            "the NOTHICKNESS option — dynain_shel_mp.F:256 writes "
            "*ELEMENT_SHELL_THICKNESS unconditionally and /DYNAIN has no "
            "sub-key to suppress it, so the thickness block is present "
            "anyway")
    if dropped:
        state.warn(f"{label}: dropped, with no /DYNAIN slot — "
                   + "; ".join(dropped) + ". dyna2rad drops all of them "
                   "too, without a message.")


def _make_engine_dynain(state: ConversionState) -> List[str]:
    """``*INTERFACE_SPRINGBACK_LSDYNA`` → ``/DYNAIN/DT[/ALL]`` +
    ``/DYNAIN/SHELL/{STRES,STRAIN}/FULL`` in the ENGINE file.

    ``/DYNAIN`` is an ENGINE keyword, so the ENGINE SOURCE is the authority
    (engine keywords are not ``/BEGIN``-version gated). ``fredynain.F:99-151``
    accepts exactly three keys — ``/DYNAIN/DT[/ALL]``,
    ``/DYNAIN/SHELL/STRES/FULL`` and ``/DYNAIN/SHELL/STRAIN/FULL``; anything
    else under ``KEY2 == 'SHELL'`` is ``ANCMSG(73)`` + ``ARRET(0)``, an engine
    ERROR TERMINATION. (``radioss2026/CARDS/dynain_shell.cfg`` also offers
    ``/DYNAIN/SHELL/AUX/FULL``; there is no AUX branch in the reader and it was
    MEASURED to kill the engine — a cfg that lies, the #115 class.)

    The written file is ``<root>_NNNN.dynain`` (``gendynain.F:124``) in LS-DYNA
    keyword format: ``*ELEMENT_SHELL_THICKNESS``, ``*NODE``,
    ``*INITIAL_STRESS_SHELL``, ``*INITIAL_STRAIN_SHELL``, ``*END`` — the same
    blocks ``handlers.handle_initial_stress_shell`` /
    ``handle_initial_strain_shell`` read, so the forming -> springback handoff
    round-trips back through k2rad.

    Two starter-level traps this writer exists to avoid, both MEASURED:

    * ``check_dynain.F`` opens ``<root>_0001.rad`` FROM INSIDE THE STARTER and
      re-parses the ``/DYNAIN/DT`` block. A bare ``/DYNAIN/DT`` with no part
      line is starter ``ERROR 1909``, and a part id that names no ``/PART`` is
      ``ERROR 1908`` — both refuse the deck before the engine ever runs. Hence
      the ``/ALL`` fallback and the ``state.parts`` screening below.
    * that same reader's guard ``IF(CARTE(1:1)/='#'.OR.CARTE(1:1)/='$')``
      (:144) is always TRUE, so it feeds whatever follows the ``Tstart Tfreq``
      line into an ``(I10)`` internal READ. The two bad lines fail DIFFERENTLY,
      and both are fatal: a ``#`` or ``$`` COMMENT line passes the tautology,
      enters the ``DO WHILE`` at :145 (non-blank, not ``/``) and reaches the
      ``READ(CARTE(J:K-1),'(I10)')`` at :153 — ``forrtl: severe (64): input
      conversion error``, the starter dies with no ``.out`` at all. A BLANK
      line instead FAILS the ``DO WHILE``'s own ``LEN_TRIM(CARTE)/=0`` and
      exits at once, leaving ``NPRT = 0`` — starter ``ERROR 1909`` (:171-174).
      The part ids therefore follow that line IMMEDIATELY, with neither a
      ``#`` nor a blank between them.

    "Shells only" is enforced at BOTH scopes. The deck-wide guard refuses a
    model with no shell at all; the part-list screen against
    ``state.shell_part_ids`` drops the parts that own none. Without the second
    one a ``*SET_PART`` naming solid parts in a deck that has shells elsewhere
    passes the first guard and produces an ACCEPTED, EMPTY dynain — measured,
    118 bytes of ``*NODE`` + ``*END`` at 0 ERROR / 0 WARNING / NORMAL
    TERMINATION, i.e. exactly the #122 failure this writer exists to prevent.
    """
    if not state.interface_springbacks:
        return []
    endtim = (state.ctrl_termination.endtim
              if state.ctrl_termination else 0.0)
    lines: List[str] = []
    # ONE merged block for the whole deck, never one per card. /DYNAIN is a
    # GLOBAL engine output request and the reader resolves the two scopes with
    # an ELSEIF: read_dynain.F:80/93 takes the part list when NDYNAINPRT /= 0
    # and /ALL only otherwise, while fredynain.F:109-110 ZEROES NDYNAINPRT
    # inside the /ALL branch. Two blocks are therefore order-dependent — a
    # per-part block after an /ALL one silently NARROWS the request, before it
    # silently WIDENS it — and the second block's Tstart/Tfreq overwrite the
    # first's. Merged here instead, with the union named.
    merged_all = False
    merged_pids: List[int] = []
    contributors: List[str] = []
    for rec in state.interface_springbacks:
        label = _springback_label(rec)
        if endtim <= 0.0:
            state.warn(
                f"{label}: this deck states no *CONTROL_TERMINATION ENDTIM "
                "(or states zero), so there is no termination time to write "
                "the dynain at — no /DYNAIN block emitted. dyna2rad writes "
                "`/DYNAIN/DT 0. 0.` in this situation "
                "(convertcards.cxx:1085), which asks the engine for one "
                "dynain file PER CYCLE.")
            _warn_springback_dropped_fields(state, label, rec)
            continue
        if not state.shell_elem_ids and not state.sh3n_elem_ids:
            state.warn(
                f"{label}: this deck converts no shell element, and "
                "OpenRadioss's /DYNAIN writer is SHELLS ONLY "
                "(fredynain.F:132-166 accepts no BRICK/BEAM/NODE sub-key; "
                "dynain_shel_mp.F / dynain_c_strsg.F / dynain_c_strag.F are "
                "the only element writers) — no /DYNAIN block emitted. "
                "MEASURED on a solid-only model: a legal, accepted, four-line "
                "stub with 0 errors and 0 warnings, which is worse than "
                "saying so.")
            _warn_springback_dropped_fields(state, label, rec)
            continue
        pids: List[int] = []
        scope_all = False
        if rec.psid <= 0:
            scope_all = True
            state.warn(
                f"{label}: PSID = {rec.psid} names no *SET_PART, so the "
                "dynain covers ALL parts (/DYNAIN/DT/ALL). A bare "
                "/DYNAIN/DT with an empty part list is starter ERROR 1909 "
                "('LIST OF PART MUST BE PROVIDED'), measured — the escape "
                "hatch is /ALL, not an empty list.")
        else:
            entry = state.part_sets.get(rec.psid)
            if entry is None:
                scope_all = True
                state.warn(
                    f"{label}: *SET_PART {rec.psid} was not found — the "
                    "dynain was widened to ALL parts (/DYNAIN/DT/ALL) rather "
                    "than emitted with an empty part list, which is starter "
                    "ERROR 1909.")
            else:
                missing = [p for p in entry[1] if p not in state.parts]
                pids = [p for p in entry[1] if p in state.parts]
                if missing:
                    state.warn(
                        f"{label}: *SET_PART {rec.psid} lists part(s) "
                        f"{_fmt_eid_list(missing)} the converted deck does "
                        "not define — they were left out. A /DYNAIN/DT part "
                        "id that names no /PART is starter ERROR 1908 "
                        "('PART ID=%d DOES NOT EXIST'), measured, which "
                        "refuses the whole run.")
                if pids:
                    # /DYNAIN is shells-only PER PART, not only deck-wide: a
                    # part that owns no emitted /SHELL or /SH3N contributes
                    # nothing to the file, and a part list made entirely of
                    # such parts is ACCEPTED — 0 ERROR, 0 WARNING, NORMAL
                    # TERMINATION — and writes an empty stub (measured: 118
                    # bytes, *NODE + *END and nothing else). The #122 class,
                    # one scope narrower than the deck-wide guard above.
                    shell_less = [p for p in pids
                                  if p not in state.shell_part_ids]
                    if shell_less:
                        pids = [p for p in pids if p in state.shell_part_ids]
                        state.warn(
                            f"{label}: part(s) {_fmt_eid_list(shell_less)} of "
                            f"*SET_PART {rec.psid} carry no /SHELL or /SH3N "
                            "element and were left out of the /DYNAIN part "
                            "list. OpenRadioss's dynain writer is SHELLS ONLY "
                            "(fredynain.F:132-166 has no BRICK/BEAM/NODE "
                            "sub-key; dynain_shel_mp.F / dynain_c_strsg.F / "
                            "dynain_c_strag.F are its only element writers), "
                            "so naming them would have added nothing to the "
                            "file. The forming state of a solid, thick-shell "
                            "or beam part cannot be carried over this way — "
                            "/STATE is the Radioss keyword family for that, "
                            "and this converter does not emit it yet.")
                    if not pids:
                        state.warn(
                            f"{label}: no part of *SET_PART {rec.psid} "
                            "carries a shell in the converted deck, so there "
                            "is nothing a shells-only /DYNAIN could write — "
                            "no /DYNAIN block emitted. Widening to "
                            "/DYNAIN/DT/ALL would have dumped the WHOLE model "
                            "instead of the parts the deck named, and "
                            "emitting the stated list would have produced an "
                            "accepted, EMPTY dynain file at 0 ERROR and 0 "
                            "WARNING (measured).")
                        _warn_springback_dropped_fields(state, label, rec)
                        continue
                else:
                    scope_all = True
                    state.warn(
                        f"{label}: no part of *SET_PART {rec.psid} survived "
                        "into the converted deck — the dynain was widened to "
                        "ALL parts rather than emitted with an empty part "
                        "list (starter ERROR 1909).")
        tstart = _DYNAIN_TSTART_FRACTION * endtim
        interval = _DYNAIN_INTERVAL_FRACTION * endtim
        contributors.append(label)
        if scope_all:
            merged_all = True
        else:
            merged_pids += [p for p in pids if p not in merged_pids]
        state.warn(
            f"{label}: -> /DYNAIN/DT{'/ALL' if scope_all else ''} "
            f"{tstart:.6G} {interval:.6G} + /DYNAIN/SHELL/STRES/FULL + "
            "/DYNAIN/SHELL/STRAIN/FULL. The engine writes "
            "<root>_NNNN.dynain from "
            f"{_DYNAIN_TSTART_FRACTION:g}*ENDTIM = {tstart:.6G} on, every "
            f"{_DYNAIN_INTERVAL_FRACTION:g}*ENDTIM = {interval:.6G} (ENDTIM = "
            f"{endtim:g}) — at most "
            f"{round((1.0 - _DYNAIN_TSTART_FRACTION) / _DYNAIN_INTERVAL_FRACTION) + 1}"
            " files; TAKE THE HIGHEST-NUMBERED ONE. "
            + ("UNDER THIS DECK'S QUASI-STATIC IMPLICIT SOLVE the highest-"
               "numbered file IS the terminal state, exactly: imp_dt.F:53-56 "
               "clamps the last step onto TSTOP (DT_E = MIN(DT_IMP, TSTOP-TT) "
               "whenever IDYNA == 0), so the run lands ON ENDTIM and the "
               "ordinary TT >= TDYNAIN trigger fires there. MEASURED on a "
               "converging implicit twin (QUASI-STATIC NON-LINEAR, 97 total "
               "nonlinear iterations, NORMAL TERMINATION, 20 cycles): three "
               "files of 22 225 bytes, all four blocks present, and the driven "
               "edge reads 20.1960 / 20.1980 / 20.2000 — the last being the "
               "full imposed displacement to the digit. Expect FEWER files "
               "than the schedule asks for, though: sortie_main.F:952 advances "
               "TDYNAIN by ONE interval per write, so an implicit step that "
               "strides over several triggers yields one file per cycle, not "
               "one per trigger. /IMPL/DT/FIXPOINT, which this converter "
               "already emits, removes the intermediate overshoot. Note this "
               "is BETTER than the explicit case below, not worse — no guard "
               "is needed and none is applied."
               if state.is_implicit else
               f"It holds the last state written at or after {tstart:.6G}, "
               f"which can precede termination by up to {interval:.6G} (more "
               "if the engine's own output cadence is coarser than that): "
               "SORTIE_MAIN fires GENDYNAIN on TT >= TDYNAIN, so the capture "
               "is a SCHEDULE, not the terminal state. A single trigger at "
               "(or just below) ENDTIM is NOT usable either: an EXPLICIT "
               "run's last cycle lands below TSTOP and the engine's own "
               "end-of-run rescue sets ILASTDYNAIN (resol.F:8358-8368) but "
               "never reads it — the extra-cycle decision at "
               "resol.F:9265-9295 is taken on ILASTANIM/ILASTH3D alone. "
               "MEASURED: `/DYNAIN/DT 0.98*ENDTIM 1E+30` wrote zero files at "
               "NORMAL TERMINATION, 0 ERROR, 0 WARNING, while this schedule "
               "wrote a file on the run's last computed cycle. (This caveat "
               "is EXPLICIT-ONLY: a quasi-static implicit run lands exactly "
               "on TSTOP — imp_dt.F:53-56 — and captures the terminal state.) "
               )
            + "The file is LS-DYNA "
            "keyword format (*NODE, "
            "*ELEMENT_SHELL_THICKNESS, *INITIAL_STRESS_SHELL, "
            "*INITIAL_STRAIN_SHELL, *END) and can be read straight back into "
            "k2rad as the springback stage's initial state.")
        _warn_springback_dropped_fields(state, label, rec)
    if not contributors:
        return []
    if len(contributors) > 1:
        state.warn(
            f"*INTERFACE_SPRINGBACK: {len(contributors)} cards ("
            + "; ".join(contributors)
            + ") were merged into ONE /DYNAIN block covering "
            + ("ALL parts" if merged_all
               else f"{len(merged_pids)} part(s): "
                    f"{_fmt_eid_list(merged_pids)}")
            + ". /DYNAIN is a global engine output request, and what two "
            "blocks do depends on their scopes. Two PART-SCOPED blocks are "
            "additive by accident: fredynain.F initialises NDYNAINPRT once "
            "(:89) and zeroes it only in the /ALL branch (:109), while the "
            "part-list branch APPENDS every id (:123) and counts it (:124), so "
            "both lists reach read_dynain.F:81-91 and both are tagged — only "
            "the EARLIER block's Tstart/Tfreq is lost, because :103 overwrites "
            "TDYNAIN0/DTDYNAIN0 per block. Mixing an /ALL block with a "
            "part-scoped one is the ORDER-DEPENDENT case: read_dynain.F:80/93 "
            "resolves the scope with an ELSEIF (the part list wins whenever "
            "NDYNAINPRT is nonzero) and the /ALL branch zeroes NDYNAINPRT, so "
            "whichever card comes second decides and the other is silently "
            "ignored. The union with ONE schedule is written instead, which is "
            "what the engine would have done for the part-scoped case anyway"
            + (" — an all-parts card was among them, which widens the scope "
               "to the whole model." if merged_all and merged_pids else "."))
    tstart = _DYNAIN_TSTART_FRACTION * endtim
    interval = _DYNAIN_INTERVAL_FRACTION * endtim
    if merged_all:
        lines += ["/DYNAIN/DT/ALL", f"{tstart:.6G} {interval:.6G}"]
    else:
        lines += ["/DYNAIN/DT", f"{tstart:.6G} {interval:.6G}"]
        # No comment and no blank line here: check_dynain.F:144 feeds the
        # very next line into an (I10) READ and dies on anything else.
        for k in range(0, len(merged_pids), _DYNAIN_IDS_PER_LINE):
            lines.append("".join(
                _i(p) for p in merged_pids[k:k + _DYNAIN_IDS_PER_LINE]))
    # The STRAIN card must go out in the LONG spelling — see
    # _DYNAIN_STRAIN_CARD. The short 'STRAI' form parses identically and
    # silently loses every QEPH shell's strain block.
    lines += ["/DYNAIN/SHELL/STRES/FULL",
              _DYNAIN_STRAIN_CARD,
              "#"]
    return ["#-  SPRINGBACK STATE (*INTERFACE_SPRINGBACK_LSDYNA -> /DYNAIN):"
            ] + lines


