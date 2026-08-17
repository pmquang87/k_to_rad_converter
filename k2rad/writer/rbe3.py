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

__all__ = ["_make_rbe3", "_trarot", "I_MODIF_NO_MODIFICATION"]


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
    from ..handlers import dof_digits_to_flags

    lines: List[str] = []
    # /RBODY main nodes, and every node any /RBODY governs — the hierarchy rule is
    # RBODY > RBE3 > RBE2 > INTERFACE TYPE2 (Reference Guide 2022 p.1959 comment 6).
    rbody_mains = {info["ind_node"] for info in rbody_info.values()}

    for rec in state.interpolations:
        label = f"*CONSTRAINED_INTERPOLATION{'_LOCAL' if rec.local else ''} {rec.icid}"
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
