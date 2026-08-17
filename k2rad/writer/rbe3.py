"""Starter interpolation constraints: `*CONSTRAINED_INTERPOLATION` → `/RBE3`.

Its own module because the card has a sub-column layout no other keyword in this
converter uses: the six ``Trarot`` booleans are packed inside a 10-character
field at FIXED character offsets, and getting them one column wrong is a
physically wrong constraint delivered with zero errors.

**k2rad writes this card itself rather than mirroring dyna2rad.** dyna2rad's
`/RBE3` output is non-functional in the shipped build, verified by running the
starter on a minimal four-independent-node deck:

    IN INTERPOLATION CONSTRAINT BODY NUMBER: 300
    NODE ID=0 DOES NOT EXIST                      <-- ERROR ID : 78
      DEPENDENT NODE . . . . . . . . .         0
    ...
    -> ERROR ID : 760, RADIOSS STOP DUE TO INPUT ERROR

Three independent defects produce that. ``Node_IDr`` comes out 0 because
``GetEntityHandle(sdiIdentifier("DNID"), ...)`` resolves the node type by the cfg
object name ``NODE`` while the LS-DYNA view keys nodes as ``*NODE``, so the handle
is always invalid; the per-set weights and the independent ``Trarot_Mi`` are
written as SCALARS into attributes the cfg declares ``ARRAY[nset]`` (and the
weight list is declared ``sdiIntList`` against a ``FLOAT`` array, so it comes back
empty and the ``SetValue`` never runs); and every independent node is forced into
ONE set, so differing per-node weights and DOF masks collapse. The starter then
substitutes its own defaults and the echo reads ``1.0 1.0 1.0 0.0 0.0 0.0`` for
every node whatever the deck said.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from ..state import ConversionState
from .common import HDR, _emit_grnod_node, _f, _i

__all__ = ["_make_rbe3", "_trarot", "dof_digits_to_flags",
           "I_MODIF_NO_MODIFICATION"]


#: /RBE3 ``I_modif`` — forbid Radioss from modifying the weights.
#:
#: The three legal values (Reference Guide 2022 p.1957): 1 = automatic weight
#: modification, 2 = modification forbidden, 3 = every weight forced to 1.0. 2 is
#: the only one that keeps what the deck says, and *CONSTRAINED_INTERPOLATION's
#: weights are exact user data — "There is no requirement on the values that are
#: chosen as the weighting factors, that is, that they sum to unity" (Vol I R17
#: p.10-43). It is also the value the starter leaves alone: ``hm_read_rbe3.F:322``
#: is ``IF (IMODIF/=2) IRBE3(8,I)=4``, and the floor-raising pass at ``:516``
#: (WARNING 757) is likewise gated on ``I_modif /= 2``. So with 2 a
#: nearly-unconstrained arrangement surfaces as WARNING 749 instead of silent
#: weight surgery. dyna2rad hard-codes 2 as well.
I_MODIF_NO_MODIFICATION = 2


def dof_digits_to_flags(code: int) -> List[int]:
    """A LS-DYNA DOF DIGIT-STRING (``DDOF``/``IDOF``) → six 0/1 flags.

    "The list of dependent degrees-of-freedom consists of a number with up to six
    digits, with each digit representing a degree of freedom.  For example, the
    value 1356 indicates that degrees of freedom 1, 3, 5, and 6 are controlled by
    the constraint" (Vol I R17 p.10-42), where 1/2/3 are x/y/z translation and
    4/5/6 the rotations about x/y/z. So it is digit-SET membership, not a bitfield
    and not a positional row: ``123`` is Tx/Ty/Tz, ``3`` is Tz alone.

    Digits outside 1..6 are ignored. That guard is not theoretical — dyna2rad's
    own decoder (``convertconstrainedinterpolations.cxx:67``) tests ``d <= 6``,
    which a ``0`` digit passes, and then writes ``flags[-1]``: an out-of-bounds
    stack write on any code containing a zero, e.g. ``DDOF = 10``.

    An all-zero result is not the same thing as "no DOFs": the starter's own
    default fills in the three translations (``hm_read_rbe3.F:244-247``, ``IF
    ((J6(1)+...+J6(6))==0) J6(1:3)=1``), which is why ``_rbe3_check`` substitutes
    Tx/Ty/Tz for an all-zero mask when it sums the axis weights.
    """
    flags = [0, 0, 0, 0, 0, 0]
    v = abs(int(code))
    while v:
        d = v % 10
        if 1 <= d <= 6:
            flags[d - 1] = 1
        v //= 10
    return flags


def _trarot(flags) -> str:
    """Six 0/1 DOF flags → the 10-character ``Trarot`` field.

    The layout is rigid and positional — ``CARD("%10d   %1d%1d%1d %1d%1d%1d...")``
    in ``radioss110/RBODY/rbe3.cfg``, i.e. inside the 10-wide field:

        col :  1  2  3  4  5  6  7  8  9 10
        val : ' '' '' ' Tx Ty Tz ' ' Rx Ry Rz

    three literal blanks, the three translations, one literal blank, the three
    rotations. Corroborated independently by the Reference Guide 2022 p.1957
    sub-column table, whose TX/TY/TZ glyphs sit in grid cells 4/5/6 and whose
    theta glyphs sit in cells 8/9/10 with cell 7 empty.

    Because ``%1d`` reads exactly ONE character at a FIXED offset, any other
    spelling silently loses DOFs. Measured negative control: writing the six
    digits right-aligned as ``      111111`` instead of ``   111 111`` produced
    WARNING 100213/100214/100217 and ``REFERENCE DOF(Trarot) 000 111`` — the three
    translations dropped — and the run still TERMINATED NORMALLY. So never
    right-align it, never write ``111111``, and never let it become an integer.
    """
    t = "".join("1" if f else "0" for f in flags)
    return f"   {t[0]}{t[1]}{t[2]} {t[3]}{t[4]}{t[5]}"


def _rbe3_check(state: ConversionState, label: str,
                groups: Dict[Tuple[int, float, int], List[int]]) -> None:
    """Warn for the arrangements ``RBE3CHK`` turns into starter ERROR 706.

    ``hm_read_rbe3.F`` runs a Nastran-style RBE3 check over every constraint after
    reading it, and ``IERR1 > 0`` becomes ``ANCMSG(MSGID=706)`` — a hard stop
    ("HAS UNCONSTRAINED DEGREES OF FREEDOM FOR THE DEPENDENT NODE", :499-505). Two
    of its four failure codes are decidable from the deck alone, and both come
    from input LS-DYNA itself accepts, so without this the conversion is clean and
    the starter is not:

      * ``IERR = 322`` (:637) — ``IF (NG == 2 .AND. IROT == 0)``: exactly two
        independent NODES and no rotational DOF anywhere on the independent side.
        The element cannot carry a moment about its own axis. ``NG`` counts NODES,
        not sets: three nodes whose rows collapse to two groups is fine, two nodes
        in two groups is not.
      * ``IERR = 326/327/328`` (:685-695) — ``ABS(DENFX/DENFY/DENFZ) <= EM20``,
        where ``DENFx`` is the sum over independent nodes of that axis's weight
        (:675-677). A deck whose every ``IDOF`` omits an axis (say ``IDOF = 3``,
        z only) leaves that denominator at zero.

    Two starter behaviours the sums have to mirror. A weight of exactly 0 is
    promoted before it is stored — ``IF (W==ZERO.OR.IMODIF==3) W=ONE`` (:227) — so
    a zero weight does NOT zero a denominator. An all-zero ``Trarot_Mi`` is
    likewise refilled with the three translations (:244-247), which is why
    ``dof_digits_to_flags`` returning all zeros counts as Tx/Ty/Tz here.

    A per-set skew makes the axes mix — with ``IELSUB > 0`` the starter accumulates
    ``TW(I,K)*EL(I,axis,K)**2`` over all three components (:669-673) — so the
    axis-sum test is skipped entirely when any set carries one, rather than
    guessing at the rotation. The ``NG == 2`` test is unaffected: it runs before
    the skews are even resolved.
    """
    n_indep = sum(len(nids) for nids in groups.values())
    irot = False
    denom = [0.0, 0.0, 0.0]
    skewed = False
    for (idof, wt, _cidi), nids in groups.items():
        flags = dof_digits_to_flags(idof)
        if not any(flags):
            flags = [1, 1, 1, 0, 0, 0]      # the starter's own blank default
        if any(flags[3:]):
            irot = True
        if _cidi:
            skewed = True
        w = 1.0 if wt == 0.0 else wt        # hm_read_rbe3.F:227
        for a in range(3):
            if flags[a]:
                denom[a] += w * len(nids)
    if n_indep == 2 and not irot:
        state.warn(
            f"{label}: exactly TWO independent nodes and no rotational DOF on the "
            "independent side (every IDOF is translations only). That is starter "
            "ERROR 706 — rbe3chk IERR=322, 'RBE3 ELEMENT HAS TWO INDEPENDENT NODES "
            "WITH NO ROTATIONAL WEIGHTS SET', because the constraint cannot carry "
            "a moment about its own axis. LS-DYNA accepts it; OpenRadioss will not "
            "start. Add a third independent node, or give one of them a rotational "
            "IDOF digit (4/5/6).")
    if skewed:
        return
    axes = [n for n, d in zip("XYZ", denom) if abs(d) <= 1e-20]
    if axes:
        state.warn(
            f"{label}: no independent node carries a T{'/T'.join(axes)} weight "
            f"(the IDOF digits never name {', '.join(str('XYZ'.index(a) + 1) for a in axes)}), "
            f"so the /RBE3 force denominator DENF{'/DENF'.join(axes)} is zero. That "
            "is starter ERROR 706 — rbe3chk IERR="
            f"{'/'.join(str(326 + 'XYZ'.index(a)) for a in axes)} — and the run "
            "stops before the first cycle. Radioss needs a non-zero weight sum on "
            "EACH of Tx/Ty/Tz even when the DEPENDENT DDOF asks for only one of "
            "them; widen the independent IDOF to 123 (the LS-DYNA default).")


def _make_rbe3(state: ConversionState, rbody_info: Dict,
               rigid_nodes: Set[int]) -> List[str]:
    """`*CONSTRAINED_INTERPOLATION[_LOCAL]` → `/RBE3` + one `/GRNOD/NODE` per set.

    **The set split is the whole conversion.** LS-DYNA gives every independent
    node its own ``IDOF`` mask and its own weight; Radioss gives every SET one
    scalar ``WTi``, one ``Trarot_Mi`` and one ``skew_IDi``. So the rows are grouped
    on ``(idof, weight, cidi)`` and each distinct combination becomes its own
    ``/GRNOD/NODE`` and its own per-set card, with ``N_set`` = the number of
    groups. Collapsing them into one set — which is all dyna2rad can do — throws
    the per-node weights away.

    Grouping also has to be a partition: a node that lands in two sets with
    different weights on the same DOF is starter ``ERROR 705``, "DIFFERENT WEIGHTS
    FOR INDEPENDENT NODE NUMBER %d" (``hm_read_rbe3.F:277``, a first-write-wins
    check). Repeated ``INID`` rows are therefore de-duplicated here, first row
    winning, with a warning.

    Card layout (``radioss110/RBODY/rbe3.cfg``, ``FORMAT(radioss100)`` — the
    effective definition at ``/BEGIN 2022``)::

        /RBE3/<id>
        <title>
        Node_IDr(I10) Trarot_ref(11-20) N_set(21-30) I_modif(31-40)
        WTi(F20)      Trarot_Mi(21-30)  skew_IDi(31-40) grnod_IDi(41-50)   x N_set

    ``Iform`` (cols 41-50 of the dependent card) is radioss2026-only and is NOT
    emitted: at 2022 the reader gets 0 from the cfg and ``SELECT CASE(IFORM)``
    maps ``0`` to ``1``, the kinematic-with-auto-penalty-fallback that IS the 2022
    behaviour. Writing it would be WARNING 100211 "Unsupported option in format".

    ``/GRNOD/NODE`` rather than ``/SET/GENERAL`` for the groups: the cfg declares
    ``grnod_IDi`` as ``SETS`` restricted to ``SUBTYPES = (/SETS/GRNOD)``, and
    /GRNOD/NODE is version-stable back to radioss41 and needs no clause
    vocabulary. (A ``/SET/GENERAL`` id does resolve too — ``lectur.F:7176-7178``
    hashes every ``IGRNOD`` entry and ``hm_set.F`` turns /SET into IGRNOD entries
    — but there is no reason to need the clause algebra here.)
    """
    # Rebuilt from scratch each call, like state.cnrb_spc_bcs: the set mirrors the
    # cards this function emits, so a second call must not accumulate stale ids.
    state.rbe3_nodes = set()
    if not state.interpolations:
        return []

    lines: List[str] = []
    seen_icids: Set[int] = set()
    # /RBODY main nodes, and every node any /RBODY governs — the hierarchy rule is
    # RBODY > RBE3 > RBE2 > INTERFACE TYPE2 (Reference Guide 2022 p.1959 comment 6).
    rbody_mains = {info["ind_node"] for info in rbody_info.values()}

    for rec in state.interpolations:
        label = f"*CONSTRAINED_INTERPOLATION{'_LOCAL' if rec.local else ''} {rec.icid}"
        if rec.icid in seen_icids:
            # LS-DYNA requires ICID unique, and hm_read_rbe3.F has no UDOUBLE pass
            # to catch a repeat, so the deck simply carries two /RBE3 blocks under
            # one id. Reported like every other id collision the converter can see
            # (_warn_spring_eid_collisions, _warn_duplicate_th_group_ids).
            state.warn(
                f"{label}: a second *CONSTRAINED_INTERPOLATION reuses ICID "
                f"{rec.icid}. Both are emitted, so the deck holds two /RBE3 blocks "
                "with the SAME id — LS-DYNA requires the id to be unique and the "
                "starter's /RBE3 reader has no duplicate-id check, so which one "
                "wins downstream (readouts, /TH) is undefined. Renumber one.")
        seen_icids.add(rec.icid)
        if rec.dnid <= 0 or rec.dnid not in state.nodes:
            state.warn(
                f"{label}: the dependent node DNID={rec.dnid} is not a *NODE in "
                "the deck. /RBE3 with Node_IDr=0 is starter ERROR 78 (NODE DOES "
                "NOT EXIST) followed by ERROR 760, so the whole constraint is "
                "SKIPPED — the dependent node is free in the converted model.")
            continue
        # ── resolve the independent rows into groups ─────────────────────────
        # key = (idof, weight, cidi) -> [node ids]; insertion-ordered so the emitted
        # set order follows the deck.
        groups: Dict[Tuple[int, float, int], List[int]] = {}
        seen: Dict[int, Tuple[int, float, int]] = {}
        dup: List[int] = []
        nonuniform: List[int] = []
        missing: List[int] = []
        for ind in rec.indeps:
            if rec.ityp:
                # ITYP=1: INID is a *SET_NODE id ("EQ.1: INID is a node set ID").
                ns = state.node_sets.get(ind.inid)
                if ns is None:
                    state.warn(
                        f"{label}: ITYP=1 makes INID={ind.inid} a *SET_NODE id, "
                        "but no such node set is in the deck (an unsupported "
                        "*SET_NODE variant?) — that whole independent set is "
                        "DROPPED from the constraint.")
                    continue
                nids = [n for n in ns[1] if n > 0]
            else:
                nids = [ind.inid]
            # Six LS-DYNA weights vs one Radioss WTi. TWGHTX is the one the manual
            # tells users to fill ("It is normally sufficient to define only
            # TWGHTX"), so it is the one that survives.
            if not (ind.twghtx == ind.twghty == ind.twghtz == ind.rwghtx
                    == ind.rwghty == ind.rwghtz):
                nonuniform.append(ind.inid)
            key = (ind.idof, ind.twghtx, ind.cidi)
            for n in nids:
                if n not in state.nodes:
                    missing.append(n)
                    continue
                if n in seen:
                    if seen[n] != key:
                        dup.append(n)
                    continue
                seen[n] = key
                groups.setdefault(key, []).append(n)
        if not groups:
            state.warn(
                f"{label}: no independent node resolved (the card-2 list is empty "
                "or every INID is undefined) — the constraint is SKIPPED and the "
                "dependent node is free in the converted model.")
            continue
        if missing:
            shown = ", ".join(str(n) for n in sorted(set(missing))[:10])
            state.warn(
                f"{label}: {len(set(missing))} independent node(s) are not *NODEs "
                f"in the deck ({shown}) and were left out of the /RBE3 groups — a "
                "dangling grnod_IDi member is only starter WARNING 174, so the set "
                "would silently come up short instead.")
        if dup:
            shown = ", ".join(str(n) for n in sorted(set(dup))[:10])
            state.warn(
                f"{label}: node(s) {shown} appear in more than one card-2 row with "
                "DIFFERENT weight/IDOF/CIDI. Radioss allows a node in only one "
                "/RBE3 set — a second one is starter ERROR 705 'DIFFERENT WEIGHTS "
                "FOR INDEPENDENT NODE NUMBER' — so the FIRST row wins and the "
                "later ones are dropped.")
        if nonuniform:
            shown = ", ".join(str(n) for n in sorted(set(nonuniform))[:10])
            state.warn(
                f"{label}: row(s) for INID {shown} give per-component weights "
                "(TWGHTX..RWGHTZ are not all equal). /RBE3 carries ONE scalar WTi "
                "per set, so TWGHTX is used for all six DOFs — the manual's own "
                "advice is that 'it is normally sufficient to define only TWGHTX' "
                "because the others default to it, so a deck that sets them apart "
                "is asking for something not representable here.")
        if rec.dnid in seen:
            state.warn(
                f"{label}: the dependent node {rec.dnid} is ALSO in its own "
                "independent list. That gives it a zero lever arm in its own "
                "interpolation, which is never what the source deck meant and can "
                "leave the dependent rotations undeterminable (starter ERROR 3098 "
                "for a collinear arrangement, ERROR 706 otherwise). Emitted as "
                "written — remove the node from the independent list.")
        if rec.dnid in rbody_mains:
            state.warn(
                f"{label}: the dependent node {rec.dnid} is also an /RBODY MAIN "
                "node. The Radioss hierarchy is RBODY > RBE3, so this is starter "
                "ERROR 810 ('NODE DEFINED AS MAIN OF RIGID BODY AND ALSO DEPENDENT "
                "NODE OF RBE3') with a kinematic-only formulation, or WARNING 3104 "
                "and a silent switch to the PENALTY formulation on the auto path — "
                "either way the rigid body wins and the interpolation does not "
                "drive the node. Pick a different dependent node.")
        elif rec.dnid in rigid_nodes:
            state.warn(
                f"{label}: the dependent node {rec.dnid} is also a SECONDARY node "
                "of an /RBODY. The rigid body's kinematics govern it (RBODY > RBE3), "
                "so the interpolation constraint is redundant at best and "
                "over-constrains the node at worst. LS-DYNA says the same for "
                "explicit runs: 'the independent and dependent nodes cannot be "
                "dependent nodes in other constraints such as nodal rigid bodies'.")
        overlap = sorted(n for n in seen if n in rigid_nodes)
        if overlap:
            shown = ", ".join(str(n) for n in overlap[:10])
            state.warn(
                f"{label}: {len(overlap)} INDEPENDENT node(s) ({shown}) also belong "
                "to an /RBODY. Their motion is dictated by the rigid body, so the "
                "interpolation reads a prescribed displacement rather than a free "
                "one — legal, but usually a sign the constraint was meant to hang "
                "off the deformable mesh.")
        # WTi has no domain check on the card, and the starter quietly substitutes
        # for one of the two illegal values.
        zero_w = sorted({n for (_d, w, _c), nn in groups.items() if w == 0.0
                         for n in nn})
        neg_w = sorted({n for (_d, w, _c), nn in groups.items() if w < 0.0
                        for n in nn})
        if zero_w:
            shown = ", ".join(str(n) for n in zero_w[:10])
            state.warn(
                f"{label}: {len(zero_w)} independent node(s) ({shown}) carry "
                "TWGHTX = 0. The card is written as WTi=0, but the starter REWRITES "
                "it to 1.0 — `IF (W==ZERO.OR.IMODIF==3) W=ONE`, hm_read_rbe3.F:227 "
                "— so those nodes run at FULL weight, not at none. A zero weight is "
                "not a way to exclude a node from an /RBE3; delete its card-2 row "
                "instead.")
        if neg_w:
            shown = ", ".join(str(n) for n in neg_w[:10])
            state.warn(
                f"{label}: {len(neg_w)} independent node(s) ({shown}) carry a "
                "NEGATIVE TWGHTX. It is passed through to WTi verbatim and the "
                "starter does not reject it, but a negative interpolation factor "
                "makes the force denominators (hm_read_rbe3.F:675-677) subtract "
                "rather than add — the split is not a weighted average any more, "
                "and a denominator that cancels to zero is ERROR 706. Check the "
                "sign in the source deck.")
        _rbe3_check(state, label, groups)

        # ── emit ────────────────────────────────────────────────────────────
        set_cards: List[str] = []
        group_lines: List[str] = []
        for (idof, wt, cidi), nids in groups.items():
            skew_id = 0
            if cidi:
                if (cidi in state.coord_sys or cidi in state.coord_nodes
                        or cidi in state.coord_vectors):
                    skew_id = cidi
                else:
                    state.warn(
                        f"{label}: the _LOCAL card-3 CIDI={cidi} names no "
                        "*DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR in the deck. "
                        "Writing it as /RBE3 skew_IDi would be starter ERROR 184 "
                        "(WRONG SKEW SYSTEM), so that set's DOFs are taken in the "
                        "GLOBAL frame instead.")
            grnod_id = state.next_grnod_id()
            group_lines += _emit_grnod_node(
                grnod_id, f"rbe3_{rec.icid}_set{len(set_cards) + 1}", sorted(nids))
            # WTi(F20) then Trarot_Mi packed at cols 21-30, skew_IDi, grnod_IDi.
            set_cards.append(
                f"{_f(wt)}{_trarot(dof_digits_to_flags(idof))}"
                f"{_i(skew_id)}{_i(grnod_id)}")
        lines += group_lines
        lines += [
            f"/RBE3/{rec.icid}",
            f"RBE3_{rec.icid}",
            "# Node_IDr    Trarot     N_set   I_modif",
            f"{_i(rec.dnid)}{_trarot(dof_digits_to_flags(rec.ddof))}"
            f"{_i(len(set_cards))}{_i(I_MODIF_NO_MODIFICATION)}",
            "#                WTi    Trarot  skew_IDi grnod_IDi",
        ]
        lines += set_cards
        lines.append(HDR)
        state.rbe3_nodes.add(rec.dnid)
        state.rbe3_nodes.update(seen)

    if lines:
        lines = ["#-  INTERPOLATION CONSTRAINTS (/RBE3):", HDR] + lines
    return lines
