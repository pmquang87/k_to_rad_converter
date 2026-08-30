"""Starter header/title/analysis cards, time-history outputs, /EIG, notes and skipped-keyword comment."""

from __future__ import annotations

from typing import Callable, Dict, List, NamedTuple, Optional, Set
from ..state import ConversionState
from .common import (
    HDR, _f, _i, _spotweld_beam_pids,
)
from .contacts import _select_parent_interface
# The _LOCAL route synthesizes a frozen /SKEW/FIX from a co-rotating
# *DEFINE_COORDINATE_NODES, using the very axes builder /SKEW emission uses, so
# the two can never disagree about what "the system at t=0" means.
from .mesh import _emit_skew_fix, _skew_axes_from_nodes

__all__ = [
    "_make_header",
    "_make_title",
    "_make_analysis_defaults",
    "_make_ams",
    "_make_starter_th",
    "_make_freq_domain_notes",
    "_make_skipped_comment",
    "_make_eig",
    "_make_starter_th_inter",
    "_make_starter_th_node_reac",
    "_make_starter_th_surf",
    "_spc_constrains_rotations",
    "_make_starter_th_node_spc",
    "_spotweld_solid_pids",
    "_make_starter_th_swforc",
    "_make_starter_th_discrete_connectors",
    "_emit_frame_mov",
    "_make_starter_th_nodal_force_group",
    "_make_starter_th_rbody",
    "_make_starter_th_bndout",
    "_make_engine_parith",
]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: header & defaults
# ─────────────────────────────────────────────────────────────────────────────

def _make_header(state: ConversionState) -> List[str]:
    # /BEGIN block embeds the unit system (Reference Guide).
    # Format:
    #   /BEGIN
    #   <title (80 chars)>
    #   <version>  <flag>
    #   <input mass>  <input length>  <input time>     ← .k file units
    #   <work mass>   <work length>   <work time>      ← internal units
    # LS-DYNA default unit system is ton (Mg) mm s N MPa.
    # Mg = megagram = 1000 kg = 1 tonne. Default is Mg/mm/s to match the .k file;
    # callers may override via convert(units=...) / the CLI --units flag.
    title = state.model_title[:80].ljust(80)
    mass, length, time = state.units
    unit_line = f"{mass.rjust(20)}{length.rjust(20)}{time.rjust(20)}"
    return [
        "#RADIOSS STARTER",
        HDR,
        "/BEGIN",
        title,
        "      2022         0",
        unit_line,
        unit_line,
        HDR,
    ]


def _make_title(state: ConversionState) -> List[str]:
    return ["/TITLE", state.model_title, HDR]


def _make_analysis_defaults(state: ConversionState) -> List[str]:
    cs = state.ctrl_shell
    ithick = 0
    if cs and cs.istupd:
        ithick = 2 if cs.istupd >= 2 else 1

    lines = [
        "/ANALY",
        "         0",
        HDR,
        "/DEF_SHELL",
    ]
    if ithick > 0:
        lines.append(f"         0         0{_i(ithick)}")
    else:
        lines.append("         0")
    lines += [HDR, "/DEF_SOLID", "         0", HDR]
    lines += ["/IOFLAG", "         0", HDR]
    return lines


def _make_ams(state: ConversionState) -> List[str]:
    """Opt-in Advanced Mass Scaling starter card (--ams), paired with the engine
    /DT/AMS (see _make_engine_timestep). grpart_ID = 0 → AMS applies to all
    parts; the solver auto-skips rigid bodies ("NO AMS EXPANSION OVERALL THE
    RBODY"). Only for a mass-scaled explicit deck (*CONTROL_TIMESTEP DT2MS<0);
    implicit/modal decks have no CFL step to scale. --ams forces element-free
    rigid masters (see convert()) so this never trips AMS ERROR 1066."""
    ts = state.ctrl_timestep
    if (not state.options.ams or ts is None or ts.dt2ms >= 0.0
            or state.is_implicit or state.is_modal):
        return []
    return ["/AMS", "#grpart_ID", _i(0), HDR]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: time history outputs
# ─────────────────────────────────────────────────────────────────────────────

# ── /TH card geometry ────────────────────────────────────────────────────────
#
# Pinned against live starter runs at /BEGIN 2022 AND at the newest /BEGIN 2612
# (identical parse at both, so nothing here is version-gated):
#
#   /TH/<TYPE>/<id>            <- id from ONE GLOBAL pool across every /TH type
#   <title>                    <- CARD("%-100s"), MANDATORY even when blank:
#                                 the reader takes the next line as the title
#                                 unconditionally, so omitting it feeds "DEF"
#                                 to the title and then dies with ERROR 260 +
#                                 ERROR 1109 ("no variable in the group")
#   <var cells>                <- 10-char cells, ten per line, 100 per line
#   <id cards>                 <- per type, below
#
# /TH/NODE            "%10d%10d%-80s"  = id, skew_ID, name   (th_node.cfg)
# /TH/BEAM,SPRING,
#     SHEL,SH3N,BRIC  "%10d          %-80s" = id, TEN BLANK COLUMNS, name
# /TH/RBODY,PART      FREE_CELL_LIST(idsmax,"%10d",ids,100) = TEN IDS PER LINE,
#                     no name column and no skew column at all
#
# Two measured traps this encodes:
#   * putting anything in columns 11-20 of a /TH/BEAM or /TH/SPRING id card is
#     WARNING 100214 ("unsupported field exists") and the value is SILENTLY
#     dropped — the skew column exists only on /TH/NODE (and, since
#     radioss140, /TH/SHEL and /TH/SH3N);
#   * packing several ids onto one card of a per-line type is read as ONE id
#     plus trailing junk: seven ids in columns 11+ gave 0 errors, only the
#     advisory WARNING 100214, and the channels vanished without even reaching
#     the existence check.

#: /TH types whose id card is a ten-per-line cell list rather than one id per
#: line. A leading 0 in a /TH/RBODY list means "ALL rigid bodies"
#: (hm_read_thgrki_rbody.F:123-125), so a 0 is never written into one.
#: MONV joins them from ``radioss2021/OUTPUTBLOCK/th_monv.cfg``, whose id card
#: is the same ``FREE_CELL_LIST(idsmax,"%10d",ids,100)`` declaration.
#: SLIPRING, RETRACTOR and ACCEL join them with the seatbelt batch, from the
#: same ``FREE_CELL_LIST(idsmax,"%10d",ids,100)`` declaration in
#: ``th_slipring.cfg`` / ``th_retractor.cfg`` / ``th_accel.cfg``.
_TH_CELL_LIST_TYPES = frozenset({"RBODY", "PART", "MONV",
                                 "SLIPRING", "RETRACTOR", "ACCEL"})

#: /TH types whose id card HAS a skew_ID column in columns 11-20.
_TH_SKEW_COLUMN_TYPES = frozenset({"NODE", "SHEL", "SH3N"})


def _th_var_lines(th_vars) -> List[str]:
    """The variable cards of a /TH group: 10-char cells, at most ten per line.

    LEFT-justified, because that is what every /TH cfg declares —
    ``FREE_CELL_LIST(Number_Of_Variables,"%-10s",VAR,100)`` in th_node.cfg,
    th_rbody.cfg, th_beam.cfg, th_spring.cfg, th_shel.cfg, th_bric.cfg and
    th_sphcel.cfg alike — and what every hand-written var line in this module
    already emits (``"DEF       "``). A right-justified cell happens to parse
    too, but only because the reader trims it.

    ``FREE_CELL_LIST`` caps a line at 100 characters, so the cells are chunked
    ten per line. No caller reaches eleven today (the longest list is the seven
    of ``_NODFOR_VARS``); the chunking is here so that adding one later cannot
    silently emit an over-long card.
    """
    return ["".join(v.ljust(10) for v in th_vars[k:k + 10])
            for k in range(0, len(th_vars), 10)]


def _th_var_header(th_vars) -> str:
    """The ``#var1     var2 ...`` ruler above a variable card.

    One label per 10-char cell, left-aligned on the cell it names — the first
    one is a character short because column 1 belongs to the ``#``.
    """
    labels = [f"var{k + 1}" for k in range(len(th_vars))]
    return ("#" + labels[0].ljust(9)
            + "".join(v.ljust(10) for v in labels[1:])).rstrip()


def _th_id_lines(rad_type: str, ids: List[int],
                 skews: Optional[List[int]] = None,
                 names: Optional[List[str]] = None) -> List[str]:
    """The id cards of a /TH group, in that type's own layout (see above)."""
    if rad_type in _TH_CELL_LIST_TYPES:
        return ["".join(_i(v) for v in ids[k:k + 10])
                for k in range(0, len(ids), 10)]
    out: List[str] = []
    for k, eid in enumerate(ids):
        skew = skews[k] if skews and k < len(skews) else 0
        # The reader keeps 40 characters of NAME_ARRAY
        # (hm_read_thgrne.F:169 HM_GET_STRING_INDEX(...,40,...)) even though the
        # cfg field is %-80s, so there is nothing to gain past 40.
        name = (names[k][:40].rstrip() if names and k < len(names) else "")
        if skew and rad_type not in _TH_SKEW_COLUMN_TYPES:
            skew = 0            # columns 11-20 are dead here — never write one
        if not skew and not name:
            out.append(_i(eid))
        elif rad_type in _TH_SKEW_COLUMN_TYPES:
            out.append(_i(eid) + _i(skew) + name)
        else:
            out.append(_i(eid) + " " * 10 + name)
    return out


# ── *DATABASE_HISTORY_<FAMILY>[_SET][_LOCAL][_ID] ────────────────────────────

#: db_type → the /TH sub-keyword its ids land on. SHELL is split further by
#: element topology (SHEL vs SH3N) and BEAM per element (BEAM vs SPRING).
_TH_HISTORY_RAD = {
    "SHELL": "SHEL", "SHELL_SET": "SHEL",
    "SOLID": "BRIC", "SOLID_SET": "BRIC",
    "TSHELL": "BRIC", "TSHELL_SET": "BRIC",
    "NODE": "NODE", "NODE_SET": "NODE",
    "NODE_LOCAL": "NODE", "NODE_SET_LOCAL": "NODE",
    "SPH": "SPHCEL", "SPH_SET": "SPHCEL",
    "BEAM": "BEAM", "BEAM_SET": "BEAM",
    "DISCRETE": "SPRING", "DISCRETE_SET": "SPRING",
    # SEATBELT is split PER ELEMENT into /TH/SPRING (1D belt) and
    # /TH/SHEL + /TH/SH3N (2D belt) — see _th_seatbelt_split.
    "SEATBELT": "SPRING",
}

#: /TH type → the variables a *DATABASE_HISTORY_* group requests for it,
#: dyna2rad's ``outVars`` verbatim (converttimehistory.cxx:238-296: the list
#: starts as ``{"DEF"}`` and the SHELL, SOLID and NODE branches push onto it).
#:
#: ``DEF`` alone is NOT the whole card. On a node it expands to six channels,
#: DX DY DZ VX VY VZ (hm_read_thgrou.F IVARNG row 1) — so a plain ``DEF``
#: group drops the accelerations and the rotational velocity/acceleration that
#: LS-DYNA's own nodout carries, and an element group drops the strain tensor.
#: All four names are legal at /BEGIN 2022: ``A``/``VR``/``AR`` are rows 4-6 of
#: VARNG (hm_read_thgrou.F:1272-1274), ``STRAIN`` is in VARCG1 (:1371, the
#: table /TH/SHEL and /TH/SH3N both read) and in VARSG1 (:1321, /TH/BRIC).
#:
#: MEASURED against the plain-DEF baseline on a shell+solid bending probe
#: (500 states, same run): /TH/NODE goes 6 -> 15 channels, /TH/SHEL 11 -> 19,
#: /TH/BRIC 11 -> 17, starter 0 ERROR(S), and every added channel carries real
#: time-varying data. The one structural zero is VR*/AR* on a node that belongs
#: only to solids — a solid node genuinely has no rotational dof, which is a
#: true answer rather than the un-computed zero *DATABASE_TPRINT would have
#: produced (see handle_database_tprint for that contrast).
_TH_HISTORY_VARS = {
    "NODE": ("DEF", "A", "AR", "VR"),
    "SHEL": ("DEF", "STRAIN"),
    "SH3N": ("DEF", "STRAIN"),
    "BRIC": ("DEF", "STRAIN"),
    # BEAM, SPRING and SPHCEL take DEF alone — dyna2rad pushes nothing extra
    # onto their branches either (its SPH "ALL" push is commented out at :296).
}


class _ThSetSource(NamedTuple):
    """How one ``*DATABASE_HISTORY_<FAMILY>_SET`` id is resolved.

    The cfgs accept TWO id pools per family — e.g.
    ``database_history_beam_set.cfg:25`` declares
    ``SUBTYPES = (/SETS/SET_COMPONENT_IDPOOL, /SETS/SET_BEAM_IDPOOL)`` — so a
    listed id may be an ELEMENT set or a PART set, and a part set expands to
    every element of that family in the named parts. Real accessors rather than
    ``getattr(state, "...")`` strings, the same reason
    :class:`_DiscreteDatabase` gives.
    """
    sets: Callable[[ConversionState], Dict[int, tuple]]
    set_kw: str                                   # the *SET_ keyword that fills it
    #: elements of this family belonging to the given part ids, or None when
    #: the family takes no part set (NODE: "IDn ... refers to node set ID n
    #: defined using the *SET_NODE_{OPTION}", Vol I R16 p.16-111).
    part_elems: Optional[Callable[[ConversionState, set], List[int]]]


def _elems_of_parts(elems, pids: set) -> List[int]:
    return [e.eid for e in elems if e.pid in pids]


_TH_SET_SOURCES = {
    "NODE_SET":       _ThSetSource(lambda s: s.node_sets, "*SET_NODE", None),
    "NODE_SET_LOCAL": _ThSetSource(lambda s: s.node_sets, "*SET_NODE", None),
    "SPH_SET":        _ThSetSource(lambda s: s.node_sets, "*SET_NODE", None),
    "BEAM_SET":       _ThSetSource(
        lambda s: s.beam_sets, "*SET_BEAM",
        lambda s, pids: _elems_of_parts(s.beam_elems, pids)),
    "DISCRETE_SET":   _ThSetSource(
        lambda s: s.discrete_sets, "*SET_DISCRETE",
        lambda s, pids: _elems_of_parts(s.discrete_elems, pids)),
    "SHELL_SET":      _ThSetSource(
        lambda s: s.shell_sets, "*SET_SHELL",
        lambda s, pids: _elems_of_parts(s.shell_elems, pids)),
    "SOLID_SET":      _ThSetSource(
        lambda s: s.solid_sets, "*SET_SOLID",
        lambda s, pids: _elems_of_parts(s.solid_elems, pids)),
    # *SET_TSHELL is not converted, so only the part-set pool resolves here.
    "TSHELL_SET":     _ThSetSource(
        lambda s: {}, "*SET_TSHELL",
        lambda s, pids: _elems_of_parts(s.tshell_elems, pids)),
}


def _th_history_kw(dbh) -> str:
    return "*DATABASE_HISTORY_" + dbh.db_type


def _th_history_entities(state: ConversionState, dbh):
    """(ids, cids, refs, names) one *DATABASE_HISTORY_* card requests.

    A ``_SET`` card is expanded here; the per-card ``CID``/``REF`` of a
    ``_SET_LOCAL`` row is broadcast to the nodes THAT set expands to.

    That last point is a deliberate deviation from dyna2rad, which compares the
    CID-column length against the EXPANDED entity count and, on the inevitable
    mismatch, broadcasts ``DH_cid[0]`` to every entity of every set and then
    discards the REF column entirely (converttimehistory.cxx:382-391). On the
    only ``_SET_LOCAL`` deck in the corpus that would put the second set's
    nodes in the first set's coordinate system. One card LINE names one set and
    carries that set's own CID and REF, so that is what is applied.
    """
    src = _TH_SET_SOURCES.get(dbh.db_type)
    if src is None:                       # not a _SET spelling: already entities
        return (list(dbh.ids), list(dbh.cids), list(dbh.refs), list(dbh.names))
    kw = _th_history_kw(dbh)
    elem_sets = src.sets(state)
    ids: List[int] = []
    cids: List[int] = []
    refs: List[int] = []
    unresolved: List[int] = []
    for k, sid in enumerate(dbh.ids):
        cid = dbh.cids[k] if k < len(dbh.cids) else 0
        ref = dbh.refs[k] if k < len(dbh.refs) else 0
        entry = elem_sets.get(sid)
        if entry is not None:
            members = list(entry[1])
        elif src.part_elems is not None and sid in state.part_sets:
            members = src.part_elems(state, set(state.part_sets[sid][1]))
        else:
            unresolved.append(sid)
            continue
        for m in members:
            ids.append(m)
            cids.append(cid)
            refs.append(ref)
    if unresolved:
        pools = src.set_kw + (" (or *SET_PART)" if src.part_elems else "")
        state.warn(
            f"{kw}: set id(s) {unresolved} resolve to no converted {pools}, so "
            "the entities they name get NO /TH channel. They are NOT written "
            "through as if they were entity ids — that is what dyna2rad's "
            "*SET_PART_LIST branch does (converttimehistory.cxx:184-211 keys "
            "on the literal string \"*SET_PART_LIST_TITLE\", so a plain "
            "*SET_PART_LIST falls through and its PART ids are pushed as "
            "ELEMENT ids) and it turns a lost channel into a starter refusal. "
            "The *SET_..._ADD unions ARE expanded (one shared resolver, "
            "recursive); the spellings still unconverted are the generated "
            "ones (_GENERAL / _COLUMN / _GENERATE / _INTERSECT) and "
            "*SET_TSHELL.")
    # dyna2rad sorts and uniques the _SET path and leaves the plain path in
    # deck order (converttimehistory.cxx:213-214); matched here, with the
    # CID/REF columns carried along so they stay aligned with their entity.
    order = sorted(range(len(ids)), key=lambda k: ids[k])
    ids = [ids[k] for k in order]
    cids = [cids[k] for k in order]
    refs = [refs[k] for k in order]
    return ids, cids, refs, []


def _th_dedup(ids, cids, refs, names):
    """Order-preserving de-duplication of an entity list and its aligned
    columns. The FIRST occurrence wins, so a node named by two sets keeps the
    first set's CID/REF."""
    seen: Set[int] = set()
    keep = []
    for k, v in enumerate(ids):
        if v in seen:
            continue
        seen.add(v)
        keep.append(k)
    return ([ids[k] for k in keep], _th_pick(cids, keep, len(ids)),
            _th_pick(refs, keep, len(ids)), _th_pick(names, keep, len(ids)))


def _th_pick(col, keep, n):
    """Sub-select an aligned column. A column is either FULL-LENGTH or absent
    (an entity list has a CID for every entity or for none), so a short one is
    dropped whole rather than partially indexed — filtering out-of-range
    indices instead would silently shift every surviving entry onto the wrong
    entity."""
    return [col[k] for k in keep] if len(col) >= n else []


def _th_screen(state: ConversionState, kw: str, what: str, err: str,
               exists, ids, cids, refs, names):
    """Drop requested ids that name no emitted entity — the #106 rule.

    A /TH group naming something the deck does not define is not a lost
    channel: it is a starter ERROR that refuses the WHOLE deck (ERROR 69 "TH
    ELEMENT SELECTION ID=n DOES NOT EXIST", hm_read_thgrne.F:187-193, for the
    element types; ERROR 78 "UNDEFINED NODE NUMBER IN TH GROUP" via
    ``USR2SYS`` for nodes). Losing the channel is strictly better than losing
    the run, so the ids come out and the loss is named.
    """
    keep = [k for k, v in enumerate(ids) if v in exists]
    if len(keep) == len(ids):
        return ids, cids, refs, names
    lost = sorted({v for v in ids if v not in exists})
    shown = ", ".join(str(v) for v in lost[:10])
    if len(lost) > 10:
        shown += f", ... ({len(lost)} ids)"
    state.warn(
        f"{kw}: {len(lost)} requested id(s) are not {what} in the converted "
        f"deck — {shown}. They are LEFT OUT of the /TH group on purpose: "
        f"naming one is starter {err} and the run would not start at all, "
        "which is strictly worse than losing those channels. Check the "
        "warnings above for the part or element that was not converted.")
    return ([ids[k] for k in keep], _th_pick(cids, keep, len(ids)),
            _th_pick(refs, keep, len(ids)), _th_pick(names, keep, len(ids)))


def _drop_muscle_springs(state: ConversionState, kw: str, ids, cids, refs,
                         names, muscle_eids: Set[int]):
    """Take *MAT_MUSCLE / *MAT_SPRING_MUSCLE elements OUT of a /TH group.

    ``/TH/SPRING`` on a ``/PROP/TYPE46`` is legal, accepted at 0 starter errors
    — and writes **15 channels of exact zero**, the OFF flag included, because
    ``ruser46.F`` fills none of the standard spring buffers. Measured by adding
    a muscle spring to a group that also held an ordinary ``/PROP/TYPE4``
    spring: the TYPE4 reported correctly (OFF = 1, length 10) beside 15 zeros.

    ``*DATABASE_DEFORC`` already excludes them (``state.discrete_spring_eids``
    is deliberately not filled for muscles); this closes the OTHER door, a
    ``*DATABASE_HISTORY_BEAM``/``_DISCRETE`` card that names the element
    directly or through a ``*SET_``. Shipping the group anyway would be the
    #122 defect — a channel that is legal, accepted and constant.

    *muscle_eids* is the set for the CALLER'S OWN LS-DYNA id namespace, never
    the union: ``*DATABASE_HISTORY_BEAM`` names *ELEMENT_BEAM ids and
    ``_DISCRETE`` names *ELEMENT_DISCRETE ids, which are separate id spaces, so
    a beam whose eid happens to equal a *MAT_SPRING_MUSCLE discrete's would
    otherwise be dropped from a group it belongs in. There is no
    ``_SEATBELT`` arm for the same reason — no *ELEMENT_SEATBELT can be a
    muscle spring, so any match there would be a namespace collision.
    """
    drop = [v for v in ids if v in muscle_eids]
    if not drop:
        return ids, cids, refs, names
    keep = [k for k, v in enumerate(ids) if v not in muscle_eids]
    n = len(ids)
    state.warn(
        f"{kw}: element(s) {sorted(drop)} are *MAT_MUSCLE / "
        "*MAT_SPRING_MUSCLE springs (/PROP/TYPE46), which write 15 channels "
        "of EXACT ZERO to /TH/SPRING — ruser46.F fills none of the standard "
        "spring buffers and the starter accepts the group at 0 errors "
        "(measured beside an ordinary /PROP/TYPE4 spring in the SAME group, "
        "which reported correctly). They are left OUT rather than shipped as "
        "a flat-zero channel. Read the muscle force from /TH/NODE REACX on an "
        "anchor node (an accumulated impulse — differentiate it) or from the "
        "global SPRING ENERGY channel.")
    return ([ids[k] for k in keep], _th_pick(cids, keep, n),
            _th_pick(refs, keep, n), _th_pick(names, keep, n))


def _th_beam_split(state: ConversionState, ids, cids, refs, names):
    """Split a *DATABASE_HISTORY_BEAM id list into (/BEAM ids, /SPRING ids).

    dyna2rad decides this PER ELEMENT through ``FindRadElement``'s fallback
    chain — /BEAM, then /SPRING, then /TRUSS, with the keyword re-initialised
    INSIDE the loop (converttimehistory.cxx:246, convertutils.cxx:298-312) — so
    one card can produce up to three groups. k2rad needs two of the three for
    its own reason: an *ELEMENT_BEAM on a *MAT_SPOTWELD part becomes a
    /PROP/TYPE13 /SPRING and one on a *SECTION_BEAM ELFORM=6 part becomes a
    /PROP/TYPE8|13 /SPRING, neither of which is a /BEAM. (k2rad emits no
    /TRUSS at all, so the third link of the chain has no target here.)
    """
    beam, spring = [], []
    n = len(ids)
    for k, eid in enumerate(ids):
        (beam if eid in state.beam_elem_ids else spring).append(k)
    return (([ids[k] for k in beam], _th_pick(cids, beam, n),
             _th_pick(refs, beam, n), _th_pick(names, beam, n)),
            ([ids[k] for k in spring], _th_pick(cids, spring, n),
             _th_pick(refs, spring, n), _th_pick(names, spring, n)))


def _make_starter_th(state: ConversionState) -> List[str]:
    """*DATABASE_HISTORY_<FAMILY>[_SET][_LOCAL][_ID] → /TH/<type>.

    Family → group:

      ``NODE`` / ``NODE_SET`` / ``NODE_LOCAL`` / ``NODE_SET_LOCAL`` → /TH/NODE
      ``SHELL`` / ``SHELL_SET``   → /TH/SHEL + /TH/SH3N, split by topology
      ``SOLID`` / ``TSHELL`` (+``_SET``) → /TH/BRIC
      ``SPH`` / ``SPH_SET``       → /TH/SPHCEL
      ``BEAM`` / ``BEAM_SET``     → /TH/BEAM + /TH/SPRING, split per element
      ``DISCRETE`` (+``_SET``)    → /TH/SPRING
      ``SEATBELT``                → /TH/SPRING + /TH/SHEL + /TH/SH3N, split
                                    PER ELEMENT

    A *DATABASE_HISTORY_SHELL request has to be split by element topology:
    since d1ade12 a 3-corner shell is emitted as /SH3N, and /TH/SHEL resolves
    only 4-node /SHELL ids, so a triangle named there is silently absent from
    the T01 instead of being recorded. Those ids go to /TH/SH3N.

    *DATABASE_HISTORY_TSHELL joins the SOLID block: a thick shell IS a /BRICK
    in the emitted deck, so /TH/BRIC resolves its ids exactly as it does an
    ordinary hex's.

    **EVERY family is SCREENED against the emitted entities** (the #106 rule —
    a dangling id is starter ERROR 69/78 and the whole deck is refused, which
    is strictly worse than losing the channel):

      NODE     ``state.nodes`` (which IS the emitted /NODE block: _make_nodes
               writes ``sorted(state.nodes.items())``)
      SPH      ``state.sph_cell_ids``
      BEAM     ``state.beam_elem_ids`` ∪ ``state.spring_elem_ids``
      DISCRETE ``state.spring_elem_ids``
      SEATBELT ``state.spring_elem_ids`` ∪ ``shell_elem_ids`` ∪ ``sh3n_elem_ids``
      SHELL    ``state.shell_elem_ids`` ∪ ``state.sh3n_elem_ids``
      SOLID    ``state.solid_elem_ids``
      TSHELL   ``state.solid_elem_ids`` (a thick shell IS a /BRICK)

    The last three are new. They close a hole that was live on BOTH spellings:
    a ``*ELEMENT_SHELL`` whose PID has no ``*PART`` record is parsed into
    ``state.shell_elems`` and warned about ("MESH LOSS") but never written, and
    both ``*DATABASE_HISTORY_SHELL`` and the ``_SET`` route synthesized their
    id list from that parsed container. MEASURED before the fix on a two-shell
    deck with one such element: ``/TH/SHEL/1`` and ``/TH/SHEL/2`` both listed
    it and the starter answered ``ERROR ID : 69 ... TH ELEMENT SELECTION
    ID=999 DOES NOT EXIST`` twice, refusing the deck. ``shell_elem_ids`` /
    ``sh3n_elem_ids`` / ``solid_elem_ids`` are filled at the six lines in
    ``_make_parts_and_elements`` that write an element row, never derived from
    ``state.shell_elems``/``solid_elems``, for exactly that reason — and the
    SHEL/SH3N split then reads the two registries directly instead of
    re-deciding the topology, so the writer and the /TH group cannot drift.

    An empty group is not a starter ERROR — ``hm_read_thgrne.F:123`` raises
    1109 only for ``NVAR == 0`` (no VARIABLE), and a group with a title, a
    ``DEF`` line and no id card is accepted, runs to NORMAL TERMINATION and
    writes a T01 group holding zero entities. That is WORSE than a refusal, not
    milder: the channels are lost in silence. So a request that resolves to
    nothing writes no block at all, and the loss is warned about instead. That
    guard used to exist only on the SHELL and SPH branches: a
    ``*DATABASE_HISTORY_NODE_ID`` card (whose fused ``%10d%-70s`` layout the
    handler mis-read, dropping every id) therefore emitted ``/TH/NODE/1`` with
    no entity — 94 silently absent channels on the Toyota Yaris and Camry
    decks. Both halves are fixed.

    Group ids stay on this function's OWN 1..N counter rather than
    ``state.next_id()``. The two streams cannot collide — ``_auto_id`` starts at
    90001, four orders of magnitude above anything this counter reaches — and
    moving them would rewrite the starter of every deck in the corpus that
    carries a *DATABASE_HISTORY_* card for no behavioural gain. The collision
    that cost PR #83 an ERROR 79 was a HARD-CODED ``/TH/INTER/1``, not this
    counter, and ``assembly._warn_duplicate_th_group_ids`` scans the emitted
    deck for the next one.
    """
    if not state.db_histories:
        return []
    lines = ["#-  TIME HISTORY OUTPUTS:", HDR]
    counter = 1
    frames: List[str] = []
    #: (CID, REF) -> the /SKEW or /FRAME id the _LOCAL route resolved it to,
    #: shared across the cards of this build. See _th_node_skews.
    local_frames: Dict[tuple, int] = {}

    def _emit_block(rad_type: str, ids: List[int], n: int,
                    skews=None, names=None, th_vars=None) -> List[str]:
        if th_vars is None:
            th_vars = _TH_HISTORY_VARS.get(rad_type, ("DEF",))
        block = [
            f"/TH/{rad_type}/{n}",
            f"TH_{rad_type}_{n}",
            _th_var_header(th_vars),
        ]
        block += _th_var_lines(th_vars)
        block += _th_id_lines(rad_type, ids, skews, names)
        return block

    for dbh in state.db_histories:
        kw = _th_history_kw(dbh)
        rad_type = _TH_HISTORY_RAD.get(dbh.db_type, dbh.db_type)
        ids, cids, refs, names = _th_history_entities(state, dbh)
        ids, cids, refs, names = _th_dedup(ids, cids, refs, names)
        skews: Optional[List[int]] = None
        if dbh.db_type in ("SPH", "SPH_SET"):
            # Through _th_screen like every other family, so the NAME column is
            # filtered with the ids instead of keeping its pre-screen length:
            # _th_id_lines pairs names[k] with ids[k] positionally, so dropping
            # a particle from the middle of an _SPH_ID list used to slide every
            # later heading onto the wrong particle (measured: 501 "alpha",
            # 9999 "ghost", 502 "beta" on a deck holding only 501/502 emitted
            # 501 "alpha" and 502 "GHOST"). _sph_th_ids keeps only its own
            # SPH-specific warning text.
            wanted = len(ids)
            ids, cids, refs, names = _th_screen(
                state, kw, "an emitted /SPHCEL",
                "ERROR 69 (TH ELEMENT SELECTION ID=n DOES NOT EXIST)",
                state.sph_cell_ids, ids, cids, refs, names)
            _warn_sph_th_loss(state, dbh, wanted, len(ids))
        elif rad_type == "NODE":
            ids, cids, refs, names = _th_screen(
                state, kw, "a node",
                "ERROR 78 (UNDEFINED NODE NUMBER ... IN TH GROUP)",
                state.nodes, ids, cids, refs, names)
            if dbh.db_type.endswith("_LOCAL"):
                skews, frame_lines = _th_node_skews(state, kw, ids, cids,
                                                    refs, local_frames)
                frames += frame_lines
        elif dbh.db_type in ("BEAM", "BEAM_SET"):
            ids, cids, refs, names = _th_screen(
                state, kw, "an emitted /BEAM or /SPRING",
                "ERROR 69 (TH ELEMENT SELECTION ID=n DOES NOT EXIST)",
                state.beam_elem_ids | state.spring_elem_ids,
                ids, cids, refs, names)
            ids, cids, refs, names = _drop_muscle_springs(
                state, kw, ids, cids, refs, names,
                state.muscle_beam_spring_eids)
        elif dbh.db_type in ("DISCRETE", "DISCRETE_SET"):
            ids, cids, refs, names = _th_screen(
                state, kw, "an emitted /SPRING",
                "ERROR 69 (TH ELEMENT SELECTION ID=n DOES NOT EXIST)",
                state.spring_elem_ids, ids, cids, refs, names)
            ids, cids, refs, names = _drop_muscle_springs(
                state, kw, ids, cids, refs, names,
                state.muscle_discrete_spring_eids)
        elif dbh.db_type == "SEATBELT":
            ids, cids, refs, names = _th_screen(
                state, kw, "an emitted belt /SPRING, /SHELL or /SH3N",
                "ERROR 69 (TH ELEMENT SELECTION ID=n DOES NOT EXIST)",
                state.spring_elem_ids | state.shell_elem_ids
                | state.sh3n_elem_ids, ids, cids, refs, names)
            # No muscle screen here: *DATABASE_HISTORY_SEATBELT names
            # *ELEMENT_SEATBELT ids, a namespace no muscle spring can be in.
        elif dbh.db_type in ("SHELL", "SHELL_SET"):
            ids, cids, refs, names = _th_screen(
                state, kw, "an emitted /SHELL or /SH3N",
                "ERROR 69 (TH ELEMENT SELECTION ID=n DOES NOT EXIST)",
                state.shell_elem_ids | state.sh3n_elem_ids,
                ids, cids, refs, names)
        elif dbh.db_type in ("SOLID", "SOLID_SET", "TSHELL", "TSHELL_SET"):
            ids, cids, refs, names = _th_screen(
                state, kw, "an emitted /BRICK, /TETRA4 or /TETRA10",
                "ERROR 69 (TH ELEMENT SELECTION ID=n DOES NOT EXIST)",
                state.solid_elem_ids, ids, cids, refs, names)
        if dbh.db_type in ("SHELL", "SHELL_SET"):
            # Split by the registries the writer filled, not by re-deciding the
            # topology from state.shell_elems: after the screen above every id
            # is in exactly one of the two sets, so the group and the emitted
            # element block cannot disagree about which is a quad.
            quad_ids = [v for v in ids if v in state.shell_elem_ids]
            tri_ids = [v for v in ids if v in state.sh3n_elem_ids]
            name_of = ({v: names[k] for k, v in enumerate(ids)}
                       if len(names) >= len(ids) else {})
            for sub, sub_ids in (("SHEL", quad_ids), ("SH3N", tri_ids)):
                if not sub_ids:
                    continue
                lines += _emit_block(
                    sub, sub_ids, counter, None,
                    [name_of[v] for v in sub_ids] if name_of else None)
                counter += 1
            continue
        if dbh.db_type == "SEATBELT":
            name_of = ({v: names[k] for k, v in enumerate(ids)}
                       if len(names) >= len(ids) else {})
            for sub, sub_ids in _th_seatbelt_split(state, ids):
                if not sub_ids:
                    continue
                lines += _emit_block(
                    sub, sub_ids, counter, None,
                    [name_of[v] for v in sub_ids] if name_of else None,
                    # DEF ALONE on the 2D-belt groups, unlike an ordinary
                    # *DATABASE_HISTORY_SHELL request. A /MAT/LAW119 shell does
                    # not stay a shell: starter0.F:782-803 hands it to
                    # hm_convert_2d_elements_seatbelt.F, which rewrites the
                    # part into 1D /SPRINGs AND rewrites every /TH/SHEL that
                    # named those shells into a /TH/SPRING (:135-141,
                    # GlobalModelSdi.cpp:2489-2554). STRAIN is a /TH/SHEL
                    # variable and not a /TH/SPRING one, so it would survive
                    # into a group that cannot serve it — ERROR 260 TH VARIABLE
                    # STRAIN IS NOT AVAILABLE. dyna2rad pushes nothing onto the
                    # SEATBELT branch either (converttimehistory.cxx:238 —
                    # outVars stays {"DEF"}; the STRAIN push at :298 belongs to
                    # the SHELL entityType).
                    th_vars=("DEF",))
                counter += 1
            continue
        if dbh.db_type in ("BEAM", "BEAM_SET"):
            (b_ids, _bc, _br, b_names), (s_ids, _sc, _sr, s_names) = \
                _th_beam_split(state, ids, cids, refs, names)
            for sub, sub_ids, sub_names in (("BEAM", b_ids, b_names),
                                            ("SPRING", s_ids, s_names)):
                if not sub_ids:
                    continue
                lines += _emit_block(sub, sub_ids, counter, None,
                                     sub_names or None)
                counter += 1
            continue
        if not ids:
            # Nothing resolved. Writing the header anyway is accepted by the
            # starter and produces a 0-entity T01 group, i.e. a lost channel
            # dressed as data — see the note on _make_starter_th.
            continue
        lines += _emit_block(rad_type, ids, counter, skews, names or None)
        counter += 1
    if len(lines) == 2:
        # Not one group survived; any /SKEW//FRAME the _LOCAL route synthesized
        # for it would be orphaned, so nothing is written at all.
        return []
    if frames:
        # After the section banner, before the groups that reference them.
        lines = lines[:2] + frames + lines[2:]
    lines.append(HDR)
    return lines


def _th_seatbelt_split(state: ConversionState, ids: List[int]):
    """Split a *DATABASE_HISTORY_SEATBELT id list PER ELEMENT.

    A belt element is a ``/SPRING`` when its part carries a
    ``*SECTION_SEATBELT`` (1D) and a ``/SHELL`` or ``/SH3N`` when it carries a
    ``*SECTION_SHELL`` (2D), so one card can produce three groups — the same
    shape ``_th_beam_split`` has, and for the same reason.

    dyna2rad decides this from the FIRST LISTED ELEMENT ONLY: it looks up
    ``elemidList[0]``, walks that element's PID → SECID, and routes the WHOLE
    list to ``/TH/SPRING`` or ``/TH/SHEL`` on that one answer
    (``converttimehistory.cxx:312-340``). A card that mixes a 1D shoulder belt
    with a 2D lap belt therefore sends every id to one keyword, and the ids of
    the other kind become ERROR 69 — or, worse, resolve to an unrelated element
    that happens to share the number. It also indexes ``elemidList[0]`` with no
    empty check.

    Reading the WRITER's own registries instead of the element's section is
    what makes the split exact: after the screen above, every surviving id is
    in exactly one of the three sets, because those sets are filled at the
    lines that write the rows.
    """
    springs = [v for v in ids if v in state.spring_elem_ids]
    quads = [v for v in ids if v in state.shell_elem_ids]
    tris = [v for v in ids if v in state.sh3n_elem_ids]
    return (("SPRING", springs), ("SHEL", quads), ("SH3N", tris))


def _warn_sph_th_loss(state: ConversionState, dbh, wanted: int, kept: int
                      ) -> None:
    """The SPH-specific half of the *DATABASE_HISTORY_SPH[_SET] screen.

    ``_th_screen`` does the filtering and names the lost ids generically; this
    adds the two things only the SPH route can say — WHY a particle id may be
    absent, and that dyna2rad does not check at all.

    ``_SPH`` lists particle ids directly; ``_SPH_SET`` lists *SET_NODE ids
    ("IDn for NODE_SET, SPH_SET, and DES_SET refers to node set ID n defined
    using the *SET_NODE_{OPTION}", Vol I R16), expanded by
    ``_th_history_entities`` before the screen runs.
    """
    kw = _th_history_kw(dbh)
    if wanted and not kept:
        state.warn(
            f"{kw}: none of the requested ids resolves to an emitted /SPHCEL, "
            "so NO /TH/SPHCEL group is written. Those channels are lost. "
            "Either the id is not an *ELEMENT_SPH particle, or its particle "
            "was dropped (no *NODE, duplicated id) — see the SPH warnings "
            "above. (dyna2rad copies the raw id list through with no check: "
            "its SPH branch is the only element branch in "
            "converttimehistory.cxx without a FindRadElement filter, so such "
            "a deck converts 'successfully' and then refuses to run with "
            "ERROR 69.)")


# ── the _LOCAL route: CID + REF -> the per-node skew_ID column ───────────────

def _emit_frame_mov(frame_id: int, title: str, n1: int, n2: int, n3: int,
                    dir_: str = "X") -> List[str]:
    """Emit /FRAME/MOV — a MOVING reference frame, N1 its origin node.

    Same (N1, N2, N3, Dir) convention as /SKEW/MOV, and the same card shape,
    but a different entity: a /SKEW only ROTATES the reported components into
    local axes, while a /FRAME reports the motion RELATIVE to the frame — the
    origin's translation and the frame's rotation are subtracted. That is
    exactly the difference between LS-DYNA's REF=1 ("projection of the node's
    absolute motion onto the local system") and REF=2 ("the motion of the node,
    expressed in the local system attached to node N1 of CID"), Vol I R16
    p.16-113.

    The Dir column (cols 31-40, ``%10s``) is a FORMAT(radioss2019) addition, so
    it is legal at /BEGIN 2022; the older radioss51 block stops at N3.
    /SKEW and /FRAME share ONE starter id namespace, which is why the id comes
    from ``state.reserve_skew_id``.
    """
    return [
        f"/FRAME/MOV/{frame_id}",
        title,
        "#  node_ID1  node_ID2  node_ID3       Dir",
        f"{_i(n1)}{_i(n2)}{_i(n3)}{dir_.rjust(10)}",
        HDR,
    ]


def _th_node_skews(state: ConversionState, kw: str, ids: List[int],
                   cids: List[int], refs: List[int],
                   cache: Optional[Dict[tuple, int]] = None):
    """(per-node skew_ID column, extra /FRAME/MOV lines) for a _LOCAL request.

    ``/TH/NODE`` is the only group in this batch whose id card carries a skew
    column, and it is PER ENTITY, not per group: ``hm_read_thgrne.F:167-171``
    fetches ``SKEW_ARRAY`` with the same index ``K`` as the id inside the id
    loop, and there is no group-level skew field anywhere in the /TH cards. The
    column accepts a ``/SKEW`` id OR a ``/FRAME`` id — ``hm_read_thgrou.F:
    2560-2588`` scans the skew table first and then falls through to the frame
    table, raising ERROR 434 only when neither matches; the starter echoes the
    column as ``SKEW(OR FRAME)``. Verified on a live starter run at /BEGIN 2022
    and 2612 with a /SKEW/FIX, a /FRAME/MOV and a 0 in one group.

    REF decides which of the two a CID becomes (Vol I R16 p.16-113):

      ``REF=0``  "output is in the local system FIXED for all time from the
                 beginning of the calculation" → a /SKEW/FIX. A CID that k2rad
                 emitted as a co-rotating /SKEW/MOV is frozen into a new
                 /SKEW/FIX built from the t=0 node positions. (The deck is
                 self-inconsistent in that case — LS-DYNA requires FLAG=0 on
                 the *DEFINE_COORDINATE_NODES for REF=0 — so it is warned.)
      ``REF=1``  "the projection of the node's absolute translational motion
                 onto the local system", which may co-rotate → the CID's own
                 /SKEW, whichever kind it is.
      ``REF=2``  "the motion of the node, expressed in the local system
                 ATTACHED TO NODE N1 of CID" — relative motion → /FRAME/MOV.

    dyna2rad's REF=0 branch builds the frozen /SKEW/FIX and then never writes
    its id back into the TH entry (converttimehistory.cxx:468-507 has no
    ``skewIdList[i] = ...``, unlike :424 and :461), so the new card is orphaned
    and the group keeps pointing at the moving skew. Fixed here.
    """
    skews: List[int] = [0] * len(ids)
    lines: List[str] = []
    unresolved: List[int] = []
    ref2_no_nodes: List[int] = []
    frozen: List[int] = []
    #: (CID, REF) -> the id written into the column, so N nodes sharing a CID
    #: synthesize ONE frame/skew (writing the id twice is starter ERROR 79 over
    #: the merged /SKEW + /FRAME table). Owned by _make_starter_th and shared
    #: across the cards of ONE build, so two *DATABASE_HISTORY_NODE[_SET]_LOCAL
    #: cards naming the same CID reference one card instead of each minting an
    #: identical twin — and a SECOND build_starter on the same state starts
    #: with a fresh dict, so it re-emits every card it references rather than
    #: pointing at a frame the new deck does not contain.
    resolved = cache if cache is not None else {}
    for k in range(len(ids)):
        cid = cids[k] if k < len(cids) else 0
        ref = refs[k] if k < len(refs) else 0
        if cid <= 0:
            continue                    # blank CID = the global system
        key = (cid, ref)
        if key in resolved:
            skews[k] = resolved[key]
            continue
        cn = state.coord_nodes.get(cid)
        known = (cid in state.coord_sys or cid in state.coord_vectors
                 or cn is not None)
        if not known:
            unresolved.append(cid)
            resolved[key] = 0
            continue
        out = cid
        if ref == 2:
            if cn is not None:
                fid = state.reserve_skew_id(state.next_id())
                lines += _emit_frame_mov(
                    fid, f"FRAME_MOV_TH_NODE_CID{cid}",
                    cn.n1, cn.n2, cn.n3, cn.dir or "X")
                out = fid
            else:
                ref2_no_nodes.append(cid)
        elif ref == 0 and cn is not None and cn.flag == 1:
            axes = _skew_axes_from_nodes(state, cn)
            if axes is not None:
                origin, xax, yax = axes
                zax = (xax[1] * yax[2] - xax[2] * yax[1],
                       xax[2] * yax[0] - xax[0] * yax[2],
                       xax[0] * yax[1] - xax[1] * yax[0])
                sid = state.reserve_skew_id(state.next_id())
                lines += _emit_skew_fix(
                    sid, f"SKEW_FIX_TH_NODE_CID{cid}", origin, yax, zax)
                out = sid
                frozen.append(cid)
        resolved[key] = out
        skews[k] = out
    if unresolved:
        state.warn(
            f"{kw}: CID {sorted(set(unresolved))} names no converted "
            "*DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR, so those nodes are "
            "recorded in the GLOBAL system (skew_ID 0) instead of the local "
            "one. Writing the raw CID through — what dyna2rad does when the "
            "lookup fails (converttimehistory.cxx:400) — would dangle into "
            "starter ERROR 434 (WRONG SKEW SYSTEM OR REFERENCE FRAME ID) and "
            "refuse the whole deck. QUANTITATIVELY: the T01 columns are then "
            "the global DX/DY/DZ components, i.e. rotated by the full "
            "orientation of the intended local system, so an intrusion "
            "measured along a local axis reads as its global projection.")
    if ref2_no_nodes:
        state.warn(
            f"{kw}: REF=2 asks for the motion RELATIVE to the system attached "
            f"to node N1 of CID {sorted(set(ref2_no_nodes))}, but that CID is a "
            "*DEFINE_COORDINATE_SYSTEM/_VECTOR — it has no nodes, so no moving "
            "/FRAME/MOV can be built from it. The nodes keep the CID's fixed "
            "/SKEW, which gives the REF=1 answer instead: the components are "
            "rotated into the local axes but the frame's own translation and "
            "rotation are NOT subtracted, so the channel is absolute motion in "
            "local axes rather than relative motion. Define the system with "
            "*DEFINE_COORDINATE_NODES to get the relative channel.")
    if frozen:
        state.warn(
            f"{kw}: REF=0 (\"the local system fixed for all time\") on CID "
            f"{sorted(set(frozen))}, whose *DEFINE_COORDINATE_NODES carries "
            "FLAG=1 (co-rotating). LS-DYNA states that combination is invalid "
            "(\"If CID is nonzero, FLAG in the corresponding "
            "*DEFINE_COORDINATE_NODES command must be set to 0\", Vol I R16 "
            "p.16-113). REF wins: a /SKEW/FIX frozen from the t=0 node "
            "positions is synthesized and the /TH group points at IT, not at "
            "the moving skew. (dyna2rad builds the same frozen skew and then "
            "never writes its id back — converttimehistory.cxx:468-507 — so "
            "its group silently keeps the CO-ROTATING system.)")
    return skews, lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: offline frequency-domain post-processing notes
# ─────────────────────────────────────────────────────────────────────────────

def _make_freq_domain_notes(state: ConversionState) -> List[str]:
    """*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG + *MAT_ADD_FATIGUE.

    OpenRadioss has no frequency-domain binary databases and no S-N fatigue
    material add-on; instead of listing these as bare "skipped" keywords, note
    where the results come from: the offline modal post-processing chain
    (tools/modal_solve.py → tools/modal_shapes_export.py mode shapes;
    tools/modal_random_response.py PSD/RMS/Dirlik fatigue honouring the deck's
    D3PSD band, PSD curve and *MAT_ADD_FATIGUE S-N data).
    """
    kinds = sorted(state.db_freq_binary)
    if not kinds and not state.mat_add_fatigue:
        return []
    what = [f"*DATABASE_FREQUENCY_BINARY_{k}" for k in kinds]
    if state.mat_add_fatigue:
        mids = ", ".join(str(m) for m in sorted(state.mat_add_fatigue))
        what.append(f"*MAT_ADD_FATIGUE (mid {mids})")
    listing = ", ".join(what)
    if state.is_modal:
        state.warn(
            f"NOTE: {listing}: no OpenRadioss equivalent - these results are "
            "produced OFFLINE from the modal solution: run tools/"
            "modal_solve.py (eigenmodes), then tools/modal_shapes_export.py "
            "(mode-shape d3plot + VTK) and tools/modal_random_response.py "
            "(response PSD / RMS / Dirlik fatigue per the deck's D3PSD band, "
            "PSD curve and S-N data). See the README modal section.")
    else:
        state.warn(
            f"NOTE: {listing}: no OpenRadioss equivalent, and the deck is not "
            "a modal (*CONTROL_IMPLICIT_EIGENVALUE) deck - the offline "
            "random-vibration post-processing (tools/modal_random_response.py)"
            " needs the modal solution, so these requests produce no output "
            "here.")
    lines = [
        "#-  FREQUENCY-DOMAIN REQUESTS (no OpenRadioss equivalent - handled OFFLINE):",
    ]
    for w in what:
        lines.append(f"#-    {w}")
    lines += [
        "#-  Results come from the offline modal chain: tools/modal_solve.py ->",
        "#-  tools/modal_shapes_export.py (mode shapes for LS-PrePost/ParaView) ->",
        "#-  tools/modal_random_response.py (PSD / RMS / Dirlik fatigue).",
        HDR,
    ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: skipped keyword comment block
# ─────────────────────────────────────────────────────────────────────────────

def _make_skipped_comment(state: ConversionState) -> List[str]:
    if not state.skipped_keywords:
        return []
    unique = sorted(set(state.skipped_keywords))
    lines = ["#", "# -- SKIPPED (unsupported) keywords --"]
    for kw in unique:
        lines.append(f"#-- SKIPPED: *{kw}")
    lines.append("#")
    return lines


def _make_eig(state: ConversionState) -> List[str]:
    """*CONTROL_IMPLICIT_EIGENVALUE → /EIG (normal-modes request) — opt-in.

    Emitted only with ``--eig`` (options.emit_eig): the open-source OpenRadioss
    engine cannot solve /EIG (the eigensolver kernel is not in the source
    release — the engine segfaults at init the moment NEIG>0), so /EIG output is
    reserved for commercial Altair Radioss users. The default modal conversion
    uses the stiffness-export recipe instead (see _make_engine_modal).

    grnd_ID=0 → modes of the whole structure AS constrained by the model's /BCS;
    grnd_bc=0 → ITYP=1 free eigenmodes (no extra interface static modes). The
    actual eigensolve is driven by /IMPL/LINEAR in the engine. Cutfreq/Freqmin
    stay 0 (engine default shift / no upper cutoff) unless the deck gave a finite
    frequency window.
    """
    eig = state.ctrl_implicit_eig
    if not state.is_modal or eig is None or not state.options.emit_eig:
        return []
    nmod = eig.neig or 100
    eig_id = state.next_id()
    return [
        HDR,
        "#-  EIGENVALUE / MODAL REQUEST (*CONTROL_IMPLICIT_EIGENVALUE):",
        f"/EIG/{eig_id}",
        "modal_eigenvalue_analysis",
        "#  grnd_ID   grnd_bc    Trarot     Ifile",
        "         0         0   000 000         0",
        "#     Nmod     Inorm             Cutfreq             Freqmin",
        f"{_i(nmod)}{_i(0)}{_f(eig.cutfreq)}{_f(eig.freqmin)}",
        "#    Nbloc      Incv     Niter      Ipri                 Tol",
        f"{_i(0)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# /TH/NODE REAC* is an accumulated impulse — shared warning text
# ─────────────────────────────────────────────────────────────────────────────
#
# Two independent conversion paths emit REACX/Y/Z channels and both have to
# say that those channels are integrated, not instantaneous:
#   * *DATABASE_SPCFORC          → _make_starter_th_node_spc  (the SPC reaction
#                                  readout that stands in for LS-DYNA's spcforc)
#   * *BOUNDARY_PRESCRIBED_MOTION_RIGID
#                                → _make_starter_th_node_reac (the imposed-motion
#                                  reaction readout, TH_reaction)
# Sources for the claim (verified, PR #93): engine/source/output/
# reaction_forces_th.F:60-62 accumulates ``FTHREAC = FTHREAC + IFLAG*MS*A*DT12``,
# the only ``FTHREAC = ZERO`` in the engine is engine/source/engine/resol.F:1901
# which runs BEFORE the explicit iteration-loop head at :2612 (back edge
# ``GOTO 100`` at :9294), and engine/source/output/th/thnod.F:178-208 writes the
# accumulator out undivided.
_REAC_IMPULSE_PHYSICS = (
    "the OpenRadioss REAC* channels are a time-ACCUMULATED reaction impulse "
    "(force x time), not an instantaneous force — the engine adds m*a*dt every "
    "cycle (reaction_forces_th.F:60-62) and zeroes the accumulator only once, "
    "before the iteration loop (resol.F:1901, loop head :2612)."
)
# Shown instead of the full derivation when this deck already carried it, so a
# deck that triggers BOTH paths does not repeat three identical sentences.
_REAC_IMPULSE_BACKREF = (
    "the REAC* channels are a time-ACCUMULATED reaction impulse (force x time), "
    "not an instantaneous force — same reaction_forces_th.F accumulation as the "
    "other REAC* warning on this deck."
)


def _warn_reac_impulse(state: ConversionState, lead: str, action: str) -> None:
    """Warn that a just-emitted REAC* block carries an impulse, not a force.

    ``lead`` names the conversion path, ``action`` is what the user must
    actually do with the column — that sentence differs between the two callers
    (compare against an LS-DYNA spcforc file vs. build a force-vs-displacement
    curve) and is therefore ALWAYS emitted in full. Only the shared
    engine-source derivation is deduplicated: the first caller on a deck writes
    it out, a second caller gets a back-reference to it. Both variants still
    contain the words "impulse", "d(REAC)/dt" and "reaction_forces_th.F", so a
    grep-style check on either warning behaves the same whichever fired first.
    """
    if state.reac_impulse_warned:
        physics = _REAC_IMPULSE_BACKREF
    else:
        physics = _REAC_IMPULSE_PHYSICS
        state.reac_impulse_warned = True
    state.warn(f"{lead}: {physics} {action}")


def _make_starter_th_inter(state: ConversionState) -> List[str]:
    """Emit /TH/INTER so contact-interface forces reach the T01 time-history file.

    Two requesters share the block:
      * *CONTACT_FORCE_TRANSDUCER → /INTER/SUB: a sub-interface's force is
        written as a channel of its parent interface, so the parent interface
        must be requested in a /TH/INTER block.
      * *DATABASE_NCFORC (nodal contact forces): OpenRadioss has no per-node
        contact-force time history (no /TH/NODE contact variable exists), so
        the request maps to the per-interface force resultants of EVERY
        converted contact interface here (T01, /TFILE frequency); the
        nodal-resolution view is the contact-force/pressure animation vectors
        /ANIM/VECT/CONT + /ANIM/VECT/PCONT the engine deck already carries.
      * *DATABASE_RCFORC (contact resultant forces): the closest equivalent of
        a /TH/INTER channel — LS-DYNA's rcforc is the per-contact force
        resultant, so every converted interface is listed here too.
    Only emitted when a transducer, *DATABASE_NCFORC or *DATABASE_RCFORC
    exists, so other decks are unchanged.

    **The DEF channels FNX/Y/Z and FTX/Y/Z are a time-ACCUMULATED contact
    IMPULSE, not a force** — the same defect class as /TH/NODE REAC*
    (_make_starter_th_node_spc below), and it is why an rcforc comparison needs
    differentiating first. The engine says so itself:
    engine/source/interfaces/int07/i7for3.F:1443 heads the block
    ``SAUVEGARDE DE L'IMPULSION NORMALE`` ("save the normal impulse") and
    :1459-1476 accumulates ``IMPX = F*DT12`` into FSAV(1..3), with the
    tangential half at :3055-3079; /INTER/SUB channels take the same path
    (:1559-1561). engine/source/output/th/thkin.F:56 copies FSAV into the T01
    buffer with no division by time.

    Nothing resets it on the rank that writes: hist2.F:616-622 zeroes FSAV only
    ``IF (ISPMD/=0)`` — i.e. on the non-master ranks after their contribution
    has been summed into the master — and sortie_main.F:1945, under its own
    heading ``TRAITEMENT SUR FSAV NON CUMULE`` ("handling of the NON-cumulated
    FSAV"), resets only the monvol block, FSAV(26) (contact elastic energy) and
    FSAV(29) (CAREA). The force columns are absent from that list precisely
    because they ARE cumulated. So on np=1 the channel is integral(F dt) since
    t=0 and carries force x time units.

    The instantaneous force is d(FNX)/dt — tools/th_to_csv.py writes that
    column. This supersedes the older "multiply by 2" folklore recorded on the
    force-transducer path (writer/contacts.py): the factor between the raw
    channel and the force is the elapsed accumulation time, not a constant.
    """
    # Parsed contacts MINUS the ones the writers refused to emit. A contact
    # whose side resolves to nothing is dropped with a loud warning, but its
    # record stays in state — listing it here is starter WARNING 257
    # "NONEXISTENT INTER <id>" on a deck that otherwise converts clean, and the
    # channel does not exist either way. All four contact writers run before
    # this section, so state.dropped_inter_ids is complete.
    all_inter_ids = [c.inter_id for c in (
        list(state.contacts_single) + list(state.contacts_surf2surf)
        + list(state.contacts_general) + list(state.contacts_type25)
        + list(state.contacts_tied) + list(state.contacts_spotweld)
        + list(state.contacts_tiebreak))
        if c.inter_id not in state.dropped_inter_ids]
    # Companion interfaces k2rad MINTED itself (the post-failure /INTER/TYPE25
    # behind a rupturing tiebreak tie) have no *CONTACT record, so they are not
    # in any of the containers above. They are real interfaces in the deck and
    # carry the whole post-failure load path — omitting them here would make
    # *DATABASE_RCFORC silently miss it. _tiebreak_companion_contact appends
    # only ids it actually emitted, so no dropped-id filter is needed.
    all_inter_ids += [i for i in state.companion_inter_ids
                      if i not in all_inter_ids]
    want_ncforc = bool(state.db_ncforc_dt) and bool(all_inter_ids)
    want_rcforc = bool(state.db_rcforc_dt) and bool(all_inter_ids)
    if state.db_ncforc_dt and not all_inter_ids:
        state.warn(
            "*DATABASE_NCFORC requested but no *CONTACT was converted — "
            "there is no interface to output (no /TH/INTER emitted).")
    if state.db_rcforc_dt and not all_inter_ids:
        state.warn(
            "*DATABASE_RCFORC requested but no *CONTACT was converted — "
            "there is no interface to output (no /TH/INTER emitted).")
    if not state.th_sub_ids and not want_ncforc and not want_rcforc:
        return []
    # List the parent interface (total contact force) and each force-transducer
    # sub-interface id — a sub-interface is written to the T01 only when its own
    # id is requested here (listing just the parent leaves OUTPUT TO TH = 0).
    ids: List[int] = []
    if state.th_sub_ids:
        parent_id = _select_parent_interface(state)
        if parent_id is not None:
            ids.append(parent_id)
        ids += [sid for sid, _ in state.th_sub_ids]
    if want_ncforc:
        state.warn(
            "*DATABASE_NCFORC (nodal contact forces): OpenRadioss has no "
            "per-node contact-force time history — mapped to /TH/INTER force "
            "resultants for every converted contact interface (T01 file, "
            "/TFILE frequency). The per-node field is in the animation "
            "vectors /ANIM/VECT/CONT + /ANIM/VECT/PCONT (at the /ANIM/DT "
            "frequency), which the engine deck emits by default.")
        ids += [i for i in all_inter_ids if i not in ids]
    if want_rcforc:
        state.warn(
            "*DATABASE_RCFORC (contact interface resultant forces): mapped to "
            "/TH/INTER resultants for every converted contact interface "
            "(T01 file, /TFILE frequency). LS-DYNA's rcforc reports the "
            "master/slave force resultant per contact; the /TH/INTER channel "
            "is the same quantity integrated over time — see the impulse "
            "warning below.")
        ids += [i for i in all_inter_ids if i not in ids]
    if not ids:
        return []
    # The units differ from LS-DYNA's, so say so on every deck that gets the
    # block. Same failure mode as the /TH/NODE REAC* channels: plotting the raw
    # column against an rcforc curve compares an impulse with a force, and
    # nothing anywhere reports an error.
    state.warn(
        "/TH/INTER FNX/Y/Z + FTX/Y/Z (contact interface forces): these "
        "channels are a time-ACCUMULATED contact IMPULSE (force x time), not "
        "an instantaneous force — the engine adds F*dt every cycle "
        "(i7for3.F:1459-1476, under its own comment 'SAUVEGARDE DE "
        "L'IMPULSION NORMALE') and never resets the accumulator on the rank "
        "that writes the T01 (hist2.F:616-622 zeroes FSAV only for ISPMD/=0; "
        "sortie_main.F:1945 resets only monvol, FSAV(26) and FSAV(29)). "
        "Differentiate with respect to time (F = d(FNX)/dt, e.g. "
        "numpy.gradient, or tools/th_to_csv.py which writes the differentiated "
        "column) before comparing against an LS-DYNA rcforc/ncforc file.")
    if any(c.variant == "SINGLE_SURFACE"
           for c in getattr(state, "contacts_type25", [])
           if c.inter_id not in state.dropped_inter_ids):
        state.warn(
            "/TH/INTER on a SELF-IMPACT interface (a *CONTACT_ERODING_SINGLE_"
            "SURFACE converts to /INTER/TYPE25 with surf_ID2=0, so both sides "
            "of the contact are the SAME surface): the FN/FT resultants are a "
            "SIGNED SUM over both sides and largely cancel. Measured on a "
            "converted punch/plate deck, the self-impact interface reported an "
            "impulse of -0.0668 against a true m*dv of +0.1833 (-63.6%) while "
            "the identical two-surface run gave +0.1913 (+4.4%). Do NOT use a "
            "self-impact interface's channels for a momentum balance — split "
            "the contact into a two-surface (ERODING_SURFACE_TO_SURFACE) "
            "interface, or take the impacting body's rigid-body deceleration "
            "instead.")
    # The TH group id namespace is GLOBAL across /TH types, not per type: the
    # starter rejects a deck carrying both /TH/NODE/1 and /TH/INTER/1 with
    # "ERROR ID : 79 / DUPLICATE ID / IN TH GROUP DEFINITION / ID=1 is
    # DUPLICATED" and writes NO RESTART FILE, so the engine cannot run at all.
    # This id used to be the literal 1, which collides with the first block
    # _make_starter_th numbers off its own 1..N counter (:111) — so any deck
    # asking for both a *DATABASE_HISTORY_* and a *DATABASE_RCFORC /
    # *DATABASE_NCFORC / *CONTACT_FORCE_TRANSDUCER died at the starter while
    # the conversion itself reported success. Every other /TH emitter already
    # draws from next_id() (_make_starter_th_node_reac, _make_starter_th_surf,
    # _make_starter_th_node_spc below; inistate._make_starter_th_sectio;
    # the /TH/RWALL in loads) — this was the one hard-coded id.
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (interface / force-transducer):", HDR,
        f"/TH/INTER/{th_id}",
        "TH_interface_forces",
        "#  DEF = FNX/Y/Z + FTX/Y/Z: contact IMPULSE (force x time), not force",
        "#  FSAV accumulates F*dt every cycle: contact force = d(FNX)/dt",
        "#     var1",
        "DEF",
    ]
    lines += [_i(i) for i in ids]
    lines.append(HDR)
    return lines


def _make_starter_th_node_reac(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Emit /TH/NODE writing reaction + displacement on the master node of each
    displacement-/velocity-controlled rigid body.

    Under displacement control the reaction at the imposed-motion node IS the
    load being 'measured' (the force the structure pushes back with). For a rigid
    body that reaction is assembled at the /RBODY master node, so REACX/Y/Z there
    is the readout of the applied load vs. the imposed DX/Y/Z. This complements
    the /INTER/SUB force transducer as an independent reaction readout. Only
    emitted when a *BOUNDARY_PRESCRIBED_MOTION_RIGID exists, so other decks are
    unchanged.

    **REACX/Y/Z is a time-accumulated reaction IMPULSE, not the instantaneous
    force** — see _make_starter_th_node_spc below for the engine source lines.
    The applied force is the time derivative of the plotted channel,
    F(t) = d(REAC)/dt; the DX/Y/Z channels alongside it are ordinary
    displacements and need no such treatment. So a force-vs-displacement curve
    has to be built from numpy.gradient(reac, t) against DX, not from REAC
    against DX. This path raises its own warning (_warn_reac_impulse): the
    *DATABASE_SPCFORC one does not cover it — a deck can have imposed motion
    and no *DATABASE_SPCFORC at all, and this block is the one that puts a
    reaction channel and a displacement channel side by side, which is the
    shape that invites the wrong plot.
    """
    if not state.prescribed_motions:
        return []
    nodes: List[int] = []
    seen: Set[int] = set()
    for pm in state.prescribed_motions:
        info = rbody_info.get(pm.pid)
        if not info:
            continue
        nd = info["ind_node"]
        if nd not in seen:
            seen.add(nd)
            nodes.append(nd)
    if not nodes:
        return []
    # This block pairs REACX/Y/Z with DX/Y/Z on the same node, which is exactly
    # the shape of a force-vs-displacement extraction — and exactly the plot
    # that silently goes wrong if REAC is used raw. The deck comment says so,
    # but a comment inside a .rad file is only read by someone who opens the
    # .rad file; the conversion log is what the engineer actually reads.
    _warn_reac_impulse(
        state,
        "*BOUNDARY_PRESCRIBED_MOTION_RIGID -> /TH/NODE TH_reaction "
        "(REACX/Y/Z next to DX/Y/Z on the rigid-body master node)",
        "Build the force-vs-displacement curve from numpy.gradient(reac, t) "
        "(F = d(REAC)/dt) against DX/Y/Z, not from REAC against DX/Y/Z — "
        "tools/th_to_csv.py writes that differentiated column for you. The raw "
        "channel rises monotonically under a steady load, so an untreated "
        "REAC-vs-DX curve has a meaningless slope and a meaningless enclosed "
        "area (it is not the work done). The DX/Y/Z channels alongside it are "
        "ordinary displacements and need no such treatment.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (imposed-motion reaction impulse on rigid-body master):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_reaction",
        "#  reaction IMPULSE (REACX/Y/Z) + displacement (DX/Y/Z) of the master node",
        "#  REAC* accumulates m*a*dt over the run: reaction force = d(REAC*)/dt",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in ("DX", "DY", "DZ", "REACX", "REACY", "REACZ")),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines


def _make_starter_th_surf(state: ConversionState) -> List[str]:
    """*DATABASE_BINARY_BLSTFOR → /TH/SURF (P, A) on each blast-loaded surface.

    LS-DYNA's blstfor binary database records the blast pressure applied to
    the *LOAD_BLAST_SEGMENT[_SET] segments over time. OpenRadioss has no
    per-segment binary equivalent, but /LOAD/PBLAST feeds three outputs that
    together carry the same information (engine pblast_1.F):
      * /TH/SURF on the loaded /SURF/SEG — P is the blast pressure and A the
        loaded area, written to the T01 at the /TFILE frequency (but read the
        caveat below before doing arithmetic with them);
      * /ANIM/NODA/PEXT — the nodal blast-pressure fringe (the spatial
        pressure field the blstfor file is fringed for in LS-PrePost);
      * /ANIM/VECT/FEXT — the external (blast) nodal force vectors.
    The two /ANIM options are added engine-side at the /ANIM/DT frequency.
    Emitted only when the deck requests *DATABASE_BINARY_BLSTFOR, so other
    decks are unchanged.

    **P and A are per-/TFILE-interval aggregates, and P*A is NOT the blast
    force.** Both are accumulated per cycle and reset at every TH write, so
    neither is a snapshot:

      * pblast_1.F:418-419 (and :468-469 / :506-507 for the other two blast
        models) adds ``AREA*P`` into channel 4 and ``AREA`` into channel 5 on
        every cycle — these are ``th_surf%channels``, which resol.F:3447 passes
        as the ``FSAVSURF`` dummy argument, so the two names are one array;
      * hist2.F:688 then divides channel 4 by channel 5 right before the write
        ("The pressure in an average pressure");
      * sortie_main.F:1976-1982 zeroes channels 1-5 after every TH write.

    So **P** is the area-weighted MEAN pressure over the /TFILE interval — not
    the instantaneous value, and a peak that falls between two TH writes is
    averaged away. **A** is the loaded area multiplied by the NUMBER OF CYCLES
    in the interval, so it only equals the loaded area when the T01 is written
    every cycle; ``P*A`` is inflated by that same cycle count. Use /TFILE close
    to the timestep if the peak matters, and take the total blast force from
    /ANIM/VECT/FEXT rather than from P*A.

    Because these are interval aggregates rather than a running integral,
    differentiating them (the fix for the REAC* and /TH/INTER channels) is
    meaningless — tools/th_to_csv.py deliberately leaves /TH/SURF alone and
    prints this caveat instead.

    **Multiple ids in ONE block are legal and correct** (starter
    hm_read_thgrsurf.F flags each id; engine thsurf.F writes one P/A pair per
    listed surface) — but on an SPMD (MPI) run the engine only reduces the
    first 5*NSURF of the 6*NSURF /TH/SURF channel elements across domains
    (hist2.F:679), which silently zeroes the highest-indexed surfaces. The
    deck-shape fix lives in assembly._pad_surfaces_for_spmd_th_surf, which
    runs after all sections are assembled and appends inert padding /SURF
    cards so every surface listed here stays inside the reduced prefix.
    """
    if not state.db_blstfor_dt:
        return []
    if not state.blast_surf_ids:
        state.warn(
            "*DATABASE_BINARY_BLSTFOR requested but no blast-loaded surface "
            "was emitted (no /LOAD/PBLAST) — there is no blast pressure to "
            "output (no /TH/SURF emitted).")
        return []
    state.warn(
        "*DATABASE_BINARY_BLSTFOR: no binary blast database exists in "
        "OpenRadioss — mapped to /TH/SURF (P, A; T01 at the /TFILE frequency) "
        "on the /LOAD/PBLAST surface plus /ANIM/NODA/PEXT (nodal pressure "
        "fringe) and /ANIM/VECT/FEXT (external force vectors) at the /ANIM/DT "
        "frequency.")
    state.warn(
        "/TH/SURF P and A are per-/TFILE-interval AGGREGATES, not snapshots: "
        "the engine adds AREA*P and AREA every cycle (pblast_1.F:418-419), "
        "divides P by A just before writing (hist2.F:688) and zeroes both "
        "after every TH write (sortie_main.F:1976-1982). So P is the MEAN "
        "pressure over the output interval — a peak falling between two writes "
        "is averaged away — and A is the loaded area times the NUMBER OF "
        "CYCLES in that interval, so P*A is NOT the blast force. Put /TFILE "
        "near the timestep if the peak matters, and take the total blast force "
        "from /ANIM/VECT/FEXT.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_BINARY_BLSTFOR -> blast surface pressure):", HDR,
        f"/TH/SURF/{th_id}",
        "TH_blast_surf",
        "#  P = MEAN pressure over the /TFILE interval; A = loaded area x cycles",
        "#  both are reset at every TH write: P*A is NOT the blast force",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "#     var1      var2",
        "".join(v.rjust(10) for v in ("P", "A")),
    ]
    lines += [_i(sid) for sid, _title in state.blast_surf_ids]
    lines.append(HDR)
    return lines


def _spc_constrains_rotations(state: ConversionState) -> bool:
    """True when any SPC constrains a rotational DOF — gates the REACXX/YY/ZZ
    /TH channels and the /ANIM/VECT/MREAC moment vectors.

    Both /BCS sources count: *BOUNDARY_SPC_* (state.bcs_spcs) and the
    *CONSTRAINED_NODAL_RIGID_BODY_SPC option (state.cnrb_spc_bcs), whose
    rotational mask is the emitted "111"-style rot field."""
    if any(bc.dofrx or bc.dofry or bc.dofrz for bc in state.bcs_spcs):
        return True
    return any(bc.rot != "000" for bc in state.cnrb_spc_bcs)


def _make_starter_th_node_spc(state: ConversionState, rbody_info: Dict) -> List[str]:
    """*DATABASE_SPCFORC → /TH/NODE with REACX/Y/Z (+REACXX/YY/ZZ) on every
    /BCS-constrained node.

    LS-DYNA's spcforc file lists the SPC reaction force (and, for rotational
    constraints, moment) per constrained node. OpenRadioss computes exactly
    that constraint reaction when reaction output is requested: /TH/NODE REAC*
    (or /ANIM/VECT/FREAC) switches the engine's constraint-reaction assembly on
    (engine reactions.F), and it is assembled on the /BCS nodes — so REACX/Y/Z
    on the /BCS node groups is the right channel on the right nodes, written to
    the T01 at the /TFILE frequency. Rigid-body member nodes are mapped to the
    /RBODY master node — the /BCS acts there and the reaction is assembled
    there. Emitted only when the deck requests *DATABASE_SPCFORC, so other
    decks are unchanged.

    **The REAC* channel is a time-accumulated reaction IMPULSE, not an
    instantaneous force — it is NOT numerically interchangeable with an
    LS-DYNA spcforc column.** engine/source/output/reaction_forces_th.F does

        FTHREAC(k,NODREAC(N)) = FTHREAC(k,NODREAC(N))
                              + IFLAG * MS(N)*A(k,N)*DT12

    i.e. it adds mass x acceleration x timestep, not mass x acceleration. It is
    called twice per cycle, IFLAG=-1 before the kinematic conditions are applied
    and IFLAG=+1 after (resol.F:7304 / :7386), so the per-cycle increment is the
    reaction m*(A - A~) times dt. Nothing ever resets it: the only
    ``FTHREAC = ZERO`` in the whole engine is resol.F:1901, which runs *before*
    the explicit iteration loop head at resol.F:2612 (back edge ``GOTO 100`` at
    :9294). thnod.F:178-208 then writes FTHREAC straight into TH channels
    620-625 with no division by time. The channel therefore rises monotonically
    under a steady load and carries force x time units (N*s in SI, mN*ms in the
    ton/mm/s system).

    reaction_forces_th.F is not the only accumulation site, and the /BCS one
    matters most here because these channels sit on /BCS nodes. The SPC path
    engine/source/output/th/bcs1th.F (called from thbcs.F) does the same thing
    for the constrained DOFs:

        FTHREAC(1..3,NODREAC(L)) += FTHREAC0(1..3) * MS(L) * DT12   (:143-148)
        FTHREAC(4..6,NODREAC(L)) += FTHREAC0(4..6) * IN(L) * DT12   (:150-155)

    so REACXX/YY/ZZ are ANGULAR impulses (moment x time, nodal inertia IN in
    place of the mass), not moments. The /ANIM counterpart in the same file
    accumulates the identical algebra with NO dt factor —
    ``FANREAC(1..6,L) += FANREAC0(1..6) * MS(L)/IN(L)`` (bcs1th.F:281-287) —
    which is the /BCS-path twin of the reactions.F:328 contrast below. On the
    IMPLICIT path the integration is trapezoidal rather than rectangular,
    ``FTHREAC -= (A + A_prev)*DT3/2`` (bcs1th_imp.F:46-56), but it is still an
    integral over time: no solver path writes an instantaneous /TH reaction.

    **How to read it:** the spcforc-equivalent force is the time derivative of
    the plotted channel, F(t) = d(REAC)/dt — ``numpy.gradient(reac, t)`` on the
    T01 column, or a least-squares slope over a window where the reaction is
    steady. Measured on a settled column+block deck of total weight
    3.850425 N: REACY ramps linearly (0.0735 N*s at t=0.03 to 1.1178 N*s at
    t=0.30) and the least-squares slope over t >= 0.15 is 3.8504181 N, which is
    -0.0002% off the analytic weight. A raw REAC* value on its own is
    meaningless as a force and grows without bound as the run gets longer.

    The instantaneous force is available as a nodal *field* instead: the
    engine-side /ANIM/VECT/FREAC (+MREAC) this writer also emits really is a
    force — reactions.F:328 finalizes ``FREAC = MS*A - FREAC`` every cycle, with
    no DT12 factor and no accumulation across cycles. FREAC and FTHREAC are
    separate arrays with deliberately different semantics; only the /TH one is
    integrated.
    """
    if not state.db_spcforc_dt:
        return []
    if not state.bcs_spcs and not state.cnrb_spc_bcs:
        state.warn(
            "*DATABASE_SPCFORC requested but the deck SPC-constrains no node "
            "(no *BOUNDARY_SPC_* and no *CONSTRAINED_NODAL_RIGID_BODY_SPC) — "
            "there is no reaction to output (no /TH/NODE emitted).")
        return []
    node_to_ind = {}
    for pid, info in rbody_info.items():
        for node in info["nodes"]:
            node_to_ind[node] = info["ind_node"]
    mapped: Set[int] = set()
    for bc in state.bcs_spcs:
        for n in state.node_sets.get(bc.nsid, ("", []))[1]:
            mapped.add(node_to_ind.get(n, n))
    # *CONSTRAINED_NODAL_RIGID_BODY_SPC: the /BCS acts directly on the /RBODY
    # master node, which is where the engine assembles the reaction — so the
    # master node IS the spcforc node, no set expansion needed.
    for cbc in state.cnrb_spc_bcs:
        mapped.add(cbc.ind_node)
    nodes = sorted(mapped)
    if not nodes:
        state.warn(
            "*DATABASE_SPCFORC: every *BOUNDARY_SPC node set is empty — "
            "no /TH/NODE reaction output emitted.")
        return []
    # The units differ from LS-DYNA's, so say so on every converted deck: an
    # engineer who plots the T01 REAC* column against an spcforc curve gets a
    # monotonically rising line instead of a force, with no error anywhere.
    _warn_reac_impulse(
        state,
        "*DATABASE_SPCFORC -> /TH/NODE REACX/Y/Z",
        "Differentiate the T01 columns with respect to time "
        "(F = d(REAC)/dt, e.g. numpy.gradient(reac, t), or tools/th_to_csv.py "
        "which writes the differentiated column for you) before comparing them "
        "against an LS-DYNA spcforc file. The instantaneous force is available "
        "as the nodal field /ANIM/VECT/FREAC, which is also emitted.")
    if len(nodes) > 1000:
        state.warn(
            f"*DATABASE_SPCFORC: {len(nodes)} SPC-constrained nodes get REAC* "
            "/TH channels (matching LS-DYNA's per-node spcforc output) — the "
            "T01 file will be correspondingly large. Trim the /TH/NODE block "
            "by hand if you only need a subset.")
    th_vars = ["REACX", "REACY", "REACZ"]
    if _spc_constrains_rotations(state):
        th_vars += ["REACXX", "REACYY", "REACZZ"]
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_SPCFORC -> SPC reaction impulse per /BCS node):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_spc_reactions",
        "#  reaction IMPULSE (REACX/Y/Z) [+ angular impulse (REACXX/YY/ZZ)] per constrained node",
        "#  REAC* accumulates m*a*dt over the run: spcforc force = d(REAC*)/dt",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in th_vars),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines


def _spotweld_solid_pids(state: ConversionState) -> Set[int]:
    """*MAT_SPOTWELD (MAT_100) parts that carry SOLID elements — the hex/nugget
    welds. Complement of _spotweld_beam_pids, which claims the beam-only MAT_100
    parts for the /PROP/TYPE13 spring path; a MAT_100 solid part falls back to
    /MAT/ELAST and its weld behaviour comes from a /CLUSTER instead."""
    if not state.mat_spotweld:
        return set()
    solid_pids = {e.pid for e in state.solid_elems}
    return {pid for pid, p in state.parts.items()
            if p.mid in state.mat_spotweld and pid in solid_pids}


def _make_starter_th_swforc(state: ConversionState) -> List[str]:
    """*DATABASE_SWFORC → /TH/SPRING (beam welds) + /TH/BRIC (solid welds).

    swforc is LS-DYNA's spot-weld force database. dyna2rad answers it with two
    blocks, both keyed on parts whose material is a *MAT_SPOTWELD
    (dyna2rad.cxx:613-695 — "SWFORC" appears TWICE in ``dbCardList``):

      * i=3: *ELEMENT_DISCRETE / *ELEMENT_BEAM  → /TH/SPRING
      * i=4: *ELEMENT_SOLID                     → /TH/BRIC

    k2rad's MAT_100 beam welds are /SPRING elements that keep their LS-DYNA
    *ELEMENT_BEAM ids VERBATIM (writer/loads.py _make_spotweld_beam_connectors
    writes ``sprg_ID = e.eid`` under a ``/SPRING/<original PID>``), so the ids
    listed here are exactly the ones the deck used and a channel maps 1:1 onto
    an LS-DYNA swforc row. Solid weld ids are likewise verbatim.

    The third block, /TH/CLUSTER over the *DEFINE_HEX_SPOTWELD_ASSEMBLY welds,
    is emitted next to the clusters themselves (writer/loads.py
    _make_hex_spotweld_clusters), the way dyna2rad emits it from its hex-weld
    converter rather than from the database card.

    Variables: ``DEF FAIL`` for the springs. ``DEF`` alone is what dyna2rad
    asks for, and hm_read_thgrou.F:1518-1520 expands it to indices 1-14 + 65 =
    OFF FX FY FZ MX MY MZ LX LY LZ RX RY RZ IE LENGTH — index 66, ``FAIL``, is
    NOT in the group. On a weld that is the one channel the user came for (it
    is *the* thing swforc reports), so it is requested explicitly. /TH/BRIC has
    no FAIL variable at all, so it takes ``DEF``.

    Element ids go ONE PER LINE for both types: /TH/SPRING and /TH/BRIC are
    read by hm_read_thgrne.F (``elem_ID`` cols 1-10, optional name in 21-100),
    not by the ten-per-line hm_read_thgrki.F that /TH/CLUSTER uses.
    """
    if not state.db_swforc_dt:
        return []
    weld_pids = _spotweld_beam_pids(state)
    # Only the springs the connector writer ACTUALLY emitted. It `continue`s
    # over a whole MAT_100 part whose welds are zero-length, carry no
    # *SECTION_BEAM, or size to no cross-section area — emitting neither
    # /PROP/TYPE13 nor /SPRING while the beams stay in state.beam_elems. A
    # /TH/SPRING naming one of those ids is not a lost channel, it is starter
    # ERROR 69 ("TH ELEMENT SELECTION ID=n DOES NOT EXIST", hm_read_thgrne.F:189
    # MSGTYPE=MSGERROR) and the whole deck is refused — strictly worse than the
    # degraded-but-running deck the "welds NOT converted" warning describes.
    # state.spotweld_spring_eids is filled by _make_spotweld_beam_connectors,
    # which the section registry runs first (same ordering the /CLUSTER +
    # cluster_ids pair relies on).
    parsed_eids = sorted(b.eid for b in state.beam_elems if b.pid in weld_pids)
    spring_eids = [e for e in parsed_eids if e in state.spotweld_spring_eids]
    if len(spring_eids) != len(parsed_eids):
        lost = [e for e in parsed_eids if e not in state.spotweld_spring_eids]
        state.warn(
            f"*DATABASE_SWFORC: {len(lost)} *MAT_SPOTWELD beam weld(s) "
            f"(element id(s) {lost[:10]}{' ...' if len(lost) > 10 else ''}) "
            "have no /SPRING in the converted deck — their part was skipped by "
            "the connector writer (see its own warning for the cause: "
            "zero-length welds, a missing *SECTION_BEAM, or no cross-section "
            "area). Those swforc channels are LOST. They are left out of the "
            "/TH/SPRING on purpose: listing an element the deck never defines "
            "is starter ERROR 69 and the run would not start at all.")
    solid_pids = _spotweld_solid_pids(state)
    # EVERY solid on a MAT_100 part, with no topology screening. /TH/BRIC is
    # read over the whole solid array (hm_read_thgrou.F ITYP=1, NUMELS), so a
    # /TETRA4 or /TETRA10 id resolves there exactly like a /BRICK — verified on
    # a live starter run, 0 ERROR(S) with a TET4 in the list. (The /CLUSTER path
    # DOES screen tets, for a different reason: it reads the hex node ordering
    # to build the weld frame. Screening them here would silently drop a
    # requested channel.) A weld already covered by a /CLUSTER is still listed:
    # /TH/BRIC reports stress and internal energy, which the cluster's force
    # resultants do not.
    brick_eids = sorted(e.eid for e in state.solid_elems if e.pid in solid_pids)
    if not spring_eids and not brick_eids:
        if not state.cluster_ids:
            state.warn(
                "*DATABASE_SWFORC requested but this deck has no spot weld "
                "k2rad could output: no *MAT_SPOTWELD (MAT_100) beam or solid "
                "part was converted and there is no "
                "*DEFINE_HEX_SPOTWELD_ASSEMBLY. No /TH block is "
                "emitted (a /TH group listing nothing is a starter error). The "
                "dt is still honoured as the /TFILE frequency. If the welds in "
                "this deck are *CONSTRAINED_SPOTWELD ties, their springs are "
                "synthesized with generated ids and are not covered here — "
                "request them with *DATABASE_HISTORY_* instead.")
        return []
    lines = [
        "#-  TIME HISTORY (*DATABASE_SWFORC -> spot-weld forces, "
        f"dt={state.db_swforc_dt:g}):", HDR,
    ]
    if spring_eids:
        th_id = state.next_id()
        lines += [
            f"/TH/SPRING/{th_id}",
            f"TH_SPOTWELD_SPRINGS_{th_id}",
            "#     var1      var2",
            "DEF       FAIL      ",
        ]
        lines += [_i(e) for e in spring_eids]
        lines.append(HDR)
        state.warn(
            f"*DATABASE_SWFORC -> /TH/SPRING/{th_id} over {len(spring_eids)} "
            "*MAT_SPOTWELD beam weld(s), listed by their ORIGINAL LS-DYNA "
            "element id (the /PROP/TYPE13 connectors keep it), so a T01 "
            "channel maps 1:1 onto an swforc row. Variables DEF + FAIL: FAIL "
            "is the weld rupture flag and is NOT part of DEF "
            "(hm_read_thgrou.F:1519). Unlike the /TH/INTER and /TH/NODE REAC* "
            "channels these are INSTANTANEOUS forces (thres.F writes GBUF%FOR "
            "and GBUF%MOM with no dt) — no differentiation needed. READ THE "
            "WELD FORCE FROM THE T01, NOT FROM THE ANIMATION: measured on a "
            "live run, /ANIM/SPRING/FORC writes 0.00 N for /PROP/TYPE13 "
            "connectors that the T01 shows carrying 13.4 kN, so the A-files "
            "are not a usable weld-force source. Note also that a weld whose "
            "*ELEMENT_BEAM card gives no third node (N3=0, the usual case) has "
            "no transverse frame of its own: the starter says WARNING 327 and "
            "resolves DOFs 2/3/5/6 against global X. That is harmless while "
            "the weld is loaded along its axis and while NRS==NRT and "
            "MSS==MTT, but on a lap-shear weld with unequal transverse limits "
            "the failure directions are not the ones the deck named — give the "
            "beam an N3 if that matters.")
    if brick_eids:
        th_id = state.next_id()
        lines += [
            f"/TH/BRIC/{th_id}",
            f"TH_SPOTWELD_SOLIDS_{th_id}",
            "#     var1      var2",
            "DEF       ",
        ]
        lines += [_i(e) for e in brick_eids]
        lines.append(HDR)
        state.warn(
            f"*DATABASE_SWFORC -> /TH/BRIC/{th_id} over {len(brick_eids)} "
            "*MAT_SPOTWELD solid weld element(s) (dyna2rad's second SWFORC "
            "pass, dyna2rad.cxx:685-689). DEF gives OFF/SX..SXZ/IE/DENS/PLAS/"
            "TEMP — element STRESS, not the weld force resultant LS-DYNA's "
            "swforc prints. The resultant needs a /CLUSTER: add a "
            "*DEFINE_HEX_SPOTWELD_ASSEMBLY over the nugget and k2rad emits "
            "/CLUSTER/BRICK + /TH/CLUSTER with FX..MZ and FS/FN/MS/MN.")
    return lines


class _DiscreteDatabase(NamedTuple):
    """One LS-DYNA discrete-connector ASCII database and how k2rad answers it.

    Real accessors rather than getattr(state, "...") strings: the fields below
    are followed by a type checker and moved by an IDE rename, which a
    stringly-typed table is not.
    """
    card: str                                   # the *DATABASE_ keyword
    dt: Callable[[ConversionState], float]      # its requested output interval
    eids: Callable[[ConversionState], Set[int]]  # ids a /SPRING was written for
    #: ids the DECK excluded from this database (deforc's PF=1); the /SPRING
    #: still exists, it is only left out of the /TH group.
    excluded: Callable[[ConversionState], Set[int]]
    stem: str                                   # /TH group title stem
    covers: str                                 # what LS-DYNA says it reports
    source: str                                 # the k2rad source of the ids


# Vol I R16 p.1944-1945 keeps DEFORC and DISBOUT apart and so does this, so
# every T01 channel is attributable to the database card the deck actually
# wrote.
_TH_DISCRETE_DATABASES = (
    _DiscreteDatabase(
        card="*DATABASE_DEFORC",
        dt=lambda s: s.db_deforc_dt,
        eids=lambda s: s.discrete_spring_eids,
        excluded=lambda s: s.deforc_suppressed_eids,
        stem="TH_DISCRETE_SPRINGS",
        covers="discrete spring and discrete damper (*ELEMENT_DISCRETE) data",
        source="*ELEMENT_DISCRETE"),
    _DiscreteDatabase(
        card="*DATABASE_DISBOUT",
        dt=lambda s: s.db_disbout_dt,
        eids=lambda s: s.dbeam_spring_eids,
        # *ELEMENT_BEAM has no PF field — disbout has no per-element print flag
        # to honour, so nothing is ever excluded here.
        excluded=lambda s: frozenset(),
        stem="TH_DISCRETE_BEAMS",
        covers="discrete beam element, type 6, relative displacements, "
               "rotations and forces",
        source="*ELEMENT_BEAM on a *SECTION_BEAM ELFORM=6 part"),
)


def _history_discrete_used(state: ConversionState) -> bool:
    """True when the deck carries a *DATABASE_HISTORY_DISCRETE[_SET][_ID] card.

    It used to be read out of ``skipped_keywords``, because k2rad had no
    handler for the card. It has one now, so the card never reaches that list
    and the parsed requests are the source instead — the qualifier below would
    otherwise have gone silently dead the moment the keyword became supported.

    The qualifier itself still stands: LS-DYNA narrows the deforc SELECTION
    with this card, while the /TH/SPRING that answers *DATABASE_DEFORC lists
    every converted *ELEMENT_DISCRETE connector. Both groups are written (they
    answer different LS-DYNA files), so the deforc one is a superset.
    """
    return any(dbh.db_type in ("DISCRETE", "DISCRETE_SET")
               for dbh in state.db_histories)


def _make_starter_th_discrete_connectors(state: ConversionState) -> List[str]:
    """*DATABASE_DEFORC / *DATABASE_DISBOUT → /TH/SPRING over the connectors.

    Both LS-DYNA databases report a family that k2rad converts to /SPRING
    elements, so both answer with /TH/SPRING — one group per card. Element ids
    are kept VERBATIM from the source deck by both writers (``sprg_ID =
    e.eid``), so a T01 channel lines up with a deforc / disbout row by id.

    That correspondence is 1:1 only as far as k2rad honours the deck's ELEMENT
    SELECTION. LS-DYNA offers two ways to narrow deforc (Manual p. 1944):
    ``PF = 1`` on *ELEMENT_DISCRETE, which IS honoured here (see
    ``state.deforc_suppressed_eids``), and *DATABASE_HISTORY_DISCRETE_OPTION,
    for which k2rad has no handler at all — a deck using it gets a /TH/SPRING
    listing EVERY converted connector while its own deforc file holds only the
    selected ones. Over-reporting, never under-reporting, but the group is then
    a superset and the emitted warning says so.

    Format, pinned against a live starter run (hm_read_thgrne.F, th_spring.cfg
    ``FORMAT(radioss51)``):

      * the TITLE line after ``/TH/SPRING/<id>`` is MANDATORY — the reader takes
        the first line after the header as the title unconditionally, so
        omitting it feeds ``DEF`` to the title and then dies with ERROR 260 +
        ERROR 1109 ("no variable in the group");
      * element ids go ONE PER LINE (``%10d`` + optional name from column 21).
        This is hm_read_thgrne.F, not the ten-per-line hm_read_thgrki.F that
        /TH/CLUSTER uses — measured, two ids on one line is WARNING 100214 and
        the second id is SILENTLY DROPPED, exit 0. Data loss with no error.

    ``DEF`` expands to 15 variables (hm_read_thgrou.F:1518-1520 → indices
    1-14 + 65): OFF FX FY FZ MX MY MZ LX LY LZ RX RY RZ IE LENGTH — the spring
    force resultants and deflections deforc/disbout report. (``ALL_42`` is NOT
    a superset: it stops at index 16, gaining F1/F2 but losing LENGTH.)

    Group ids come from ``state.next_id()``, never a literal: /TH ids are ONE
    namespace across every /TH type and a hard-coded one already cost this
    converter an ERROR 79 with no restart file (PR #83).
    """
    lines: List[str] = []
    for db in _TH_DISCRETE_DATABASES:
        card, stem, covers, source = db.card, db.stem, db.covers, db.source
        dt = db.dt(state)
        # DT == 0 is "no output is printed" (Manual p. 16-7), so nothing to do.
        # DT < 0 is NOT nothing: it means "output every -DT time steps". Radioss
        # has no cycle-based /TH frequency, so the group is still written and
        # only its INTERVAL is lost — writer/assembly.py reports that where it
        # picks /TFILE.
        if dt == 0.0:
            continue
        # ONLY the ids a /SPRING line was actually written for. Both writers
        # have live `continue` paths (an *ELEMENT_DISCRETE part with no *PART
        # record or no *SECTION_DISCRETE, a grounded element whose anchor node
        # has no coordinates, a discrete-beam part with no usable beams), and a
        # /TH/SPRING naming an element the deck never defines is starter
        # ERROR 69 ("TH ELEMENT SELECTION ID=n DOES NOT EXIST",
        # hm_read_thgrne.F:189, MSGTYPE=MSGERROR) — the deck is REFUSED, not
        # degraded. The sets are filled by the writers that run earlier in the
        # section registry, the same ordering the SWFORC block relies on.
        # ...minus the ones the DECK itself excluded from this database (PF=1).
        excluded = db.excluded(state) & db.eids(state)
        eids = sorted(db.eids(state) - excluded)
        if not eids:
            state.warn(
                f"{card} requested but this deck has no converted {source} "
                "connector to report on, so NO /TH block is emitted: a group "
                "with no entity is not refused by the starter, it is accepted "
                "and written to the T01 holding zero entities, so it would "
                "only look like data. If the connectors are there "
                "but were skipped, their own warning names the cause; joint "
                "forces belong to *DATABASE_JNTFORC and spot-weld forces to "
                "*DATABASE_SWFORC, which have their own /TH blocks."
                + (f" ({len(excluded)} connector(s) ARE converted but carry "
                   "PF=1, which turns their deforc output off.)"
                   if excluded else ""))
            continue
        th_id = state.next_id()
        lines += [
            f"#-  TIME HISTORY ({card} -> {covers}, dt={dt:g}):", HDR,
            f"/TH/SPRING/{th_id}",
            f"{stem}_{th_id}",
            "#     var1",
            "DEF       ",
        ]
        lines += [_i(e) for e in eids]
        lines.append(HDR)
        row = card.split('_')[-1].lower()
        state.warn(
            f"{card} -> /TH/SPRING/{th_id} over {len(eids)} {source} "
            "connector(s), listed by their ORIGINAL LS-DYNA element id, so a "
            f"T01 channel maps 1:1 onto a {row} row"
            + (f" ({len(excluded)} more connector(s) carry PF=1 and are left "
               "out, matching LS-DYNA)" if excluded else "")
            + ". Variables DEF = OFF FX FY FZ "
            "MX MY MZ LX LY LZ RX RY RZ IE LENGTH. These are INSTANTANEOUS "
            "forces and deflections (thres.F writes GBUF%FOR / GBUF%MOM with "
            "no dt factor), unlike the /TH/INTER and /TH/NODE REAC* channels "
            "which accumulate an impulse — no differentiation needed. The "
            "values are in the DECK'S OWN UNITS: k2rad never rescales, so a "
            "ton-mm-s deck reports newtons and millimetres exactly as written."
            + (" NOTE: this deck also carries *DATABASE_HISTORY_DISCRETE, "
               "which LS-DYNA uses to NARROW this database to the elements it "
               f"names, so the group above is a SUPERSET of what {row} "
               "actually holds. k2rad converts that card too, into its own "
               "narrowed /TH/SPRING group — both are in the starter deck, so "
               "read the narrowed one when you want the LS-DYNA selection."
               if _history_discrete_used(state) else ""))
    return lines


def _warn_db_card_without_dt(state: ConversionState, card: str,
                             would_be: str) -> None:
    """A presence-only *DATABASE_ card whose DT field is blank, 0 or missing.

    The REFERENCE trigger for *DATABASE_RBDOUT and *DATABASE_BNDOUT is presence
    alone — ``convertrigids.cxx:767`` uses ``selDatabaseRbdout.Count()`` and
    ``dyna2rad.cxx:461`` ``selDbCard.Count()``, neither reads DT. k2rad gates on
    the interval instead, which is right for the two ways DT can be non-positive
    and wrong to do silently:

      * ``DT == 0`` — "if DT is zero, no output is printed" (Vol I R16 p. 16-7).
        There is genuinely nothing to write;
      * ``DT`` BLANK with LCDT set — the interval comes from a curve, which
        Radioss's /TFILE (a single time interval) cannot express at all.

    Either way no group is emitted, but the user asked for one, so say so: a
    mistyped DT otherwise produces an empty T01 selection with no diagnostic
    anywhere in the log.
    """
    state.warn(
        f"{card} is present but its DT field is blank or non-positive, so no "
        f"output interval is stated and NO {would_be} is emitted. DT=0 means "
        "\"no output is printed\" (Vol I R16 p. 16-7); a BLANK DT means the "
        "interval comes from the LCDT curve in field 3, which Radioss's "
        "/TFILE cannot express (it takes one time interval, not a curve). Give "
        "the card a positive DT to get the channels. (dyna2rad triggers on the "
        "card's mere presence and ignores DT entirely.)")


# ─────────────────────────────────────────────────────────────────────────────
# *DATABASE_NODAL_FORCE_GROUP -> /TH/NODE
# ─────────────────────────────────────────────────────────────────────────────

#: The seven variables dyna2rad writes for a nodal force group, verbatim
#: (convertcards.cxx:1042-1045, Number_Of_Variables hard-coded to 7). All seven
#: are legal /TH/NODE names (th_node.cfg:117, :134-139); ``DEF`` itself expands
#: to DX DY DZ VX VY VZ (hm_read_thgrou.F IVARNG row 1).
_NODFOR_VARS = ("DEF", "REACX", "REACY", "REACZ", "REACXX", "REACYY", "REACZZ")


def _make_starter_th_nodal_force_group(state: ConversionState) -> List[str]:
    """*DATABASE_NODAL_FORCE_GROUP[_TITLE] -> one /TH/NODE per card.

    LS-DYNA writes the resultant force acting on a node GROUP to its ``nodfor``
    file; dyna2rad answers with one /TH/NODE per card over the expanded node
    set, ``skew_ID`` = the card's CID on every node, and the seven variables
    above (convertcards.cxx:993-1052). Same here, with three deliberate
    differences, each because the dyna2rad behaviour is a defect rather than a
    convention:

      * the node set is looked up through k2rad's own ``state.node_sets``.
        dyna2rad looks the RADIOSS ``/SET/GENERAL`` up by the raw LS-DYNA NSID
        (convertcards.cxx:1023) instead of going through its own
        ``GetRadiossSetIdFromLsdSet`` mapping, so on a deck where a *SET_NODE
        id collides with another set family it silently finds the WRONG set;
      * an unresolved NSID and an empty set are WARNED, not dropped in silence
        (convertcards.cxx:1017 / :1037);
      * nodes are screened against the converted mesh — a /TH/NODE naming an
        undefined node is starter ERROR 78, not a lost channel.

    **What the channel actually is.** LS-DYNA's nodfor is a free-body cut: the
    force the rest of the model exerts on the group. Radioss REAC* is the
    KINEMATIC CONSTRAINT reaction, which is identically zero on an
    unconstrained node — and it is a time-ACCUMULATED impulse on top of that.
    Both are said in the warning; the free-body equivalent is /SECT
    (*DATABASE_CROSS_SECTION), which k2rad also converts.
    """
    if not state.db_nodal_force_groups:
        if state.db_nodfor_dt:
            # Decided HERE, not in the *DATABASE_NODFOR handler: the two
            # keywords may appear in either order (every r14 deck writes the
            # frequency block first), so a handler-side test would report a
            # deck that DOES carry a group card as having none.
            state.note_recognized_not_emitted(
                "DATABASE_NODFOR",
                "it is the output INTERVAL of the nodfor database, not a "
                "channel selection - the nodes come from "
                "*DATABASE_NODAL_FORCE_GROUP, which this deck does not carry. "
                "The dt IS honoured, as one term of the /TFILE minimum. Add "
                "*DATABASE_NODAL_FORCE_GROUP with a *SET_NODE to get the "
                "reaction channels.")
        return []
    lines: List[str] = []
    for grp in state.db_nodal_force_groups:
        entry = state.node_sets.get(grp.nsid)
        if entry is None:
            state.warn(
                f"*DATABASE_NODAL_FORCE_GROUP NSID={grp.nsid}: no converted "
                "*SET_NODE with that id (or a set spelling k2rad does not "
                "expand, e.g. *SET_NODE_GENERAL), so NO /TH/NODE group is "
                "written "
                "and those nodfor channels are lost. Listing the set id as if "
                "it were a node id would be starter ERROR 78.")
            continue
        wanted: List[int] = []
        seen: Set[int] = set()
        for nid in entry[1]:
            if nid not in seen:
                seen.add(nid)
                wanted.append(nid)
        nodes = [n for n in wanted if n in state.nodes]
        lost = sorted(set(wanted) - set(nodes))
        if lost:
            shown = ", ".join(str(n) for n in lost[:10])
            if len(lost) > 10:
                shown += f", ... ({len(lost)} ids)"
            state.warn(
                f"*DATABASE_NODAL_FORCE_GROUP NSID={grp.nsid}: {len(lost)} "
                "member(s) of the set are not a node of the converted mesh — "
                f"{shown}. Left out: a /TH/NODE naming an undefined node is "
                "starter ERROR 78 (UNDEFINED NODE NUMBER IN TH GROUP) and the "
                "whole deck is refused.")
        if not nodes:
            state.warn(
                f"*DATABASE_NODAL_FORCE_GROUP NSID={grp.nsid}: the node set is "
                "empty, so NO /TH/NODE group is written — a group with no "
                "entity is accepted by the starter and written to the T01 "
                "holding zero entities, which only looks like data. Those "
                "channels are lost. dyna2rad drops this case silently.")
            continue
        skew = 0
        if grp.cid:
            if (grp.cid in state.coord_sys or grp.cid in state.coord_nodes
                    or grp.cid in state.coord_vectors):
                skew = grp.cid
            else:
                state.warn(
                    f"*DATABASE_NODAL_FORCE_GROUP NSID={grp.nsid}: CID="
                    f"{grp.cid} names no converted *DEFINE_COORDINATE_"
                    "SYSTEM/_NODES/_VECTOR, so the reactions are reported in "
                    "the GLOBAL system (skew_ID 0). A dangling skew id in that "
                    "column would be starter ERROR 434 (WRONG SKEW SYSTEM OR "
                    "REFERENCE FRAME ID) and no deck at all.")
        th_id = state.next_id()
        title = grp.title.strip() or f"DATABASE NODAL FORCE GROUP NSET {grp.nsid}"
        if not lines:
            # ONE section banner for the whole block, like every other /TH
            # section. Emitted here rather than at the top of the loop so a
            # deck whose groups ALL warn-and-drop writes no banner over an
            # empty section; the per-card nsid detail goes on the group's own
            # comment line below.
            lines += ["#-  TIME HISTORY (*DATABASE_NODAL_FORCE_GROUP -> nodal "
                      "reaction impulse):", HDR]
        lines += [
            f"/TH/NODE/{th_id}",
            title[:100],
            f"#  nsid={grp.nsid}: DEF (DX/Y/Z + VX/Y/Z) + reaction IMPULSE "
            "REACX/Y/Z + REACXX/YY/ZZ",
            f"#  skew_ID {skew} per node (CID={grp.cid}); REAC* force = d(REAC*)/dt",
            _th_var_header(_NODFOR_VARS),
        ]
        lines += _th_var_lines(_NODFOR_VARS)
        lines += _th_id_lines("NODE", nodes, [skew] * len(nodes))
        lines.append(HDR)
        _warn_reac_impulse(
            state,
            f"*DATABASE_NODAL_FORCE_GROUP NSID={grp.nsid} -> /TH/NODE/{th_id} "
            f"REACX/Y/Z + REACXX/YY/ZZ over {len(nodes)} node(s)",
            "Differentiate before comparing against an LS-DYNA nodfor file "
            "(F = d(REAC)/dt, e.g. numpy.gradient, or tools/th_to_csv.py which "
            "writes the differentiated column). AND NOTE THE CHANGE OF "
            "MEANING: LS-DYNA's nodfor is a FREE-BODY CUT — the force the rest "
            "of the model exerts on the group, nonzero anywhere in the mesh — "
            "while the Radioss REAC* channel is the KINEMATIC CONSTRAINT "
            "reaction and is identically zero on a node that carries no /BCS, "
            "/RBODY or imposed motion. dyna2rad maps the two onto each other "
            "anyway (convertcards.cxx:1045). For a real free-body section "
            "force use *DATABASE_CROSS_SECTION_PLANE/_SET, which k2rad turns "
            "into /SECT + /TH/SECTIO.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# *DATABASE_RBDOUT -> /TH/RBODY
# ─────────────────────────────────────────────────────────────────────────────

def _make_starter_th_rbody(state: ConversionState) -> List[str]:
    """*DATABASE_RBDOUT -> /TH/RBODY over EVERY /RBODY the conversion wrote.

    A presence-only trigger with no id list, answered by collecting every
    converted rigid body — the same shape /TH/RWALL, /TH/SECTIO and /TH/INTER
    use (convertrigids.cxx:766-772).

    ``state.rbody_ids`` is the set the THREE Radioss-side /RBODY emission sites
    register into at the line that writes the card — writer/rbody.py:645
    *MAT_RIGID parts (which is also where *PART_INERTIA, element-free CoG
    masters and *CONSTRAINED_RIGID_BODIES merge masters come out, so four
    LS-DYNA sources funnel through it), :1004 *CONSTRAINED_NODAL_RIGID_BODY and
    :1086 the implicit no-rigid-body probe.
    ``rbody_info`` cannot stand in for it: the probe body is not in that dict at
    all (so a deck whose ONLY rigid body is the probe would get no group), a
    CNRB/part id collision drops one record from it, and a
    *CONSTRAINED_RIGID_BODIES merge aliases several keys onto one master node.

    Two /TH/RBODY-only card rules, both measured:

      * the id list is a TEN-PER-LINE cell list with no name and no skew column
        (th_rbody.cfg ``FREE_CELL_LIST(idsmax,"%10d",ids,100)``), not the
        one-id-per-line layout every element group uses;
      * a leading id of 0 selects ALL rigid bodies
        (hm_read_thgrki_rbody.F:123-125), so a placeholder zero is never
        written. (A STALE id here is only ``WARNING 257 NONEXISTENT RBODY``,
        not the hard ERROR 69 the element groups give — the list is still
        built from the emitted set, so the group count is right.)

    ``DEF`` expands to nine channels, ``FX FY FZ MX MY MZ RX RY RZ``
    (hm_read_thgrou.F IVARRBG row 1). The first six are TIME-ACCUMULATED
    impulses — ``rgbodfp.F:261-266`` does ``FS(1)=FS(1)+AFM1*DT1*WEIGHT(M)`` —
    while ``RX/RY/RZ`` integrate the angular VELOCITY
    (``rgbodv.F:91-93 FS(7)=FS(7)+VR(1,M)*DT2*WEIGHT(M)``) and are therefore a
    genuine rotation ANGLE, needing no differentiation. Said in the warning,
    because LS-DYNA's rbdout is a MOTION file and half of this is not motion.
    """
    if not state.db_rbdout_dt:
        # DT == 0 is "no output is printed" (Manual p. 16-7) and a BLANK DT
        # means the interval comes from LCDT, which Radioss's /TFILE cannot
        # express. Either way there is no interval to honour, so no group —
        # but say so when the CARD IS THERE, because a mistyped DT otherwise
        # produces a silently empty T01 selection.
        if state.db_rbdout_seen:
            _warn_db_card_without_dt(state, "*DATABASE_RBDOUT",
                                     "/TH/RBODY over every converted rigid "
                                     "body")
        return []
    ids = sorted(state.rbody_ids)
    if not ids:
        state.warn(
            "*DATABASE_RBDOUT requested but this deck has no /RBODY — no "
            "*MAT_RIGID part, no *CONSTRAINED_NODAL_RIGID_BODY and no implicit "
            "probe body. NO /TH/RBODY is emitted: a group with no entity is "
            "not refused by the starter, it is accepted and written to the T01 "
            "holding zero entities, so it would only look like data. Those "
            "channels do not exist in this deck.")
        return []
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_RBDOUT -> rigid-body forces and rotation, "
        f"dt={state.db_rbdout_dt:g}):", HDR,
        f"/TH/RBODY/{th_id}",
        f"TH_RBODY_{th_id}",
        "#  DEF = FX FY FZ MX MY MZ (accumulated IMPULSE) + RX RY RZ (rotation angle)",
        "#  /RBODY ids are TEN PER LINE here, and a leading 0 would mean ALL",
        _th_var_header(("DEF",)),
    ]
    lines += _th_var_lines(("DEF",))
    lines += _th_id_lines("RBODY", ids)
    lines.append(HDR)
    state.warn(
        f"*DATABASE_RBDOUT -> /TH/RBODY/{th_id} over all {len(ids)} converted "
        "rigid body(ies), listed by their /RBODY id (which k2rad sets to the "
        "body's main node). Variables DEF = FX FY FZ MX MY MZ RX RY RZ. "
        "READ THE TWO HALVES DIFFERENTLY: FX..MZ are a time-ACCUMULATED "
        "force/moment IMPULSE, not a force — the engine adds a*dt every cycle "
        "(rgbodfp.F:261-266, FS(1)=FS(1)+AFM1*DT1*WEIGHT(M)) — so the force is "
        "d(FX)/dt, the same treatment /TH/INTER and /TH/NODE REAC* need. "
        "RX/RY/RZ integrate the angular VELOCITY instead (rgbodv.F:91-93) and "
        "ARE the body's rotation angle, so they need no differentiation. "
        "LS-DYNA's rbdout is a MOTION file (global and local displacement, "
        "velocity and acceleration of each body); only the rotation half of "
        "that is in this group. For rigid-body translation add a "
        "*DATABASE_HISTORY_NODE on the body's main node, which gives DX/DY/DZ "
        "and VX/VY/VZ directly.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# *DATABASE_BNDOUT -> /TH/NODE on the prescribed-motion nodes
# ─────────────────────────────────────────────────────────────────────────────

def _make_starter_th_bndout(state: ConversionState) -> List[str]:
    """*DATABASE_BNDOUT -> /TH/NODE REAC* over the imposed-motion nodes.

    "Boundary condition forces and energy" (Vol I R16 p.16-4). dyna2rad reads
    the card's mere presence and collects the node groups of every converted
    ``/IMPDISP``, ``/IMPVEL`` and ``/IMPACC`` — in that order, with the
    ``Gnod_id`` vs ``grnod_ID`` attribute switch at dyna2rad.cxx:466 — sorts
    and uniques them, and writes ONE group named ``TH_NODE_BNDOUT`` with SIX
    variables and no ``DEF`` (dyna2rad.cxx:449-495). Reproduced, with the node
    scope taken from ``state.imp_motion_nodes``: the set the two
    *BOUNDARY_PRESCRIBED_MOTION writers filled AT the point of emission, so a
    row they warned about and dropped (an unsupported DOF, a missing /RBODY, an
    empty box intersection) contributes no node and cannot dangle into starter
    ERROR 78.

    **The scope is *BOUNDARY_PRESCRIBED_MOTION, not "every /IMP* card".** k2rad
    has a third /IMP* producer — ``_make_geometric_rwall_motion`` drives a
    *RIGIDWALL_GEOMETRIC_*_MOTION wall with an /IMPVEL or /IMPDISP over its
    carrier nodes — and it is deliberately OUT of scope, unlike dyna2rad, whose
    re-walk of the OUTPUT model (``SelectionRead(p_radiossModel, "/IMPVEL")``)
    cannot tell the two apart and sweeps the wall in. Three reasons, in order
    of weight:

      * LS-DYNA does not put a rigid wall in bndout. Wall reactions are the
        ``rwforc`` file, which is *DATABASE_RWFORC -> /TH/RWALL here;
      * those carrier nodes are SYNTHESIZED by the converter (loads.py:4980,
        one per distinct face base point). They carry ids that appear in no
        LS-DYNA deck, so a channel labelled "bndout" keyed on them names
        something the deck author never wrote;
      * they are free nodes with zero mass and no element, so their REAC* is
        identically zero — a flat channel that reads as data, which is exactly
        what the *DATABASE_TPRINT decision refused to emit.

    Zero-scale *BOUNDARY_PRESCRIBED_MOTION_SET rows are deliberately absent for
    a different reason: ``sf == 0`` means "fix this DOF" and k2rad folds those
    into a /BCS rather than an /IMP* (writer/loads.py), which is exactly
    dyna2rad's SPCFORC scope, not its BNDOUT scope. *DATABASE_SPCFORC already
    covers them.

    REACXX/YY/ZZ are added only when a prescribed motion drives a ROTATIONAL
    dof, the same gate ``_spc_constrains_rotations`` puts on the SPC block.
    """
    if not state.db_bndout_dt:
        # See the matching note on _make_starter_th_rbody: DT == 0 prints
        # nothing (Manual p. 16-7) and a blank DT defers to LCDT.
        if state.db_bndout_seen:
            _warn_db_card_without_dt(
                state, "*DATABASE_BNDOUT",
                "/TH/NODE 'TH_NODE_BNDOUT' over the prescribed-motion nodes")
        return []
    if not state.imp_motion_nodes:
        state.warn(
            "*DATABASE_BNDOUT requested but this deck drives no node with a "
            "*BOUNDARY_PRESCRIBED_MOTION — there is no boundary-condition "
            "force to output, so NO /TH/NODE is emitted. (A "
            "*RIGIDWALL_GEOMETRIC_*_MOTION wall does not count: LS-DYNA "
            "reports a wall reaction in rwforc, so it belongs to "
            "*DATABASE_RWFORC -> /TH/RWALL, and its k2rad carrier nodes are "
            "synthesized massless free nodes whose reaction is identically "
            "zero.) SPC reaction forces are a different card again: "
            "*DATABASE_SPCFORC.")
        return []
    nodes = sorted(state.imp_motion_nodes)
    th_vars = ["REACX", "REACY", "REACZ"]
    if state.imp_motion_rot:
        th_vars += ["REACXX", "REACYY", "REACZZ"]
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_BNDOUT -> prescribed-motion reaction "
        f"impulse, dt={state.db_bndout_dt:g}):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_NODE_BNDOUT",
        "#  reaction IMPULSE (REACX/Y/Z)[ + angular impulse (REACXX/YY/ZZ)] per driven node",
        "#  REAC* accumulates m*a*dt over the run: bndout force = d(REAC*)/dt",
        _th_var_header(th_vars),
    ]
    lines += _th_var_lines(th_vars)
    lines += _th_id_lines("NODE", nodes)
    lines.append(HDR)
    _warn_reac_impulse(
        state,
        f"*DATABASE_BNDOUT -> /TH/NODE/{th_id} 'TH_NODE_BNDOUT' over "
        f"{len(nodes)} node(s) driven by a *BOUNDARY_PRESCRIBED_MOTION",
        "Differentiate the T01 columns with respect to time (F = d(REAC)/dt, "
        "e.g. numpy.gradient(reac, t), or tools/th_to_csv.py which writes the "
        "differentiated column) before comparing them against an LS-DYNA "
        "bndout file. The ENERGY half of bndout (the work done by the boundary "
        "condition) has no /TH channel at all; take it from the global energy "
        "balance in the .out / T01, where the external work appears."
        + ("" if state.imp_motion_rot else
           " Only the three translational REAC* are requested: no prescribed "
           "motion in this deck drives a rotational dof, and the rotational "
           "channels would read zero."))
    return lines


# ── *DATABASE_ABSTAT -> /TH/MONV ─────────────────────────────────────────────

#: /MONVOL model -> the /TH/MONV variables that model actually FILLS.
#:
#: The whole 19-name vocabulary of ``radioss2021/OUTPUTBLOCK/th_monv.cfg`` is
#: legal on every monitored volume — a probe requested all sixteen of the
#: non-vent names on a PRES bag and the starter took them without complaint —
#: but most of them come back identically zero, because the ENGINE only fills
#: the ``FSAV`` slots its own pressure law computes. Requesting the rest would
#: write flat channels that read as data, which is the trap the
#: *DATABASE_TPRINT decision already refused to walk into. So the list is per
#: MODEL, and every entry below is backed by an FSAV assignment:
#:
#:   PRES     ``volpfv.F`` / ``volpres.F`` fill FSAV 2/3/4 only, and set
#:            FSAV(1) = 0 — a PRES bag has no gas, so MASS is a literal zero.
#:   GAS      ``volpvg.F:172-181``: 2=VOL 3=PRES 4=AREA 12=GAMA. FSAV(1)=AMTOT
#:            and FSAV(5)=TEMPERATURE are ALSO written, but both are
#:            structurally zero on the card this converter emits: AMTOT comes
#:            from ``RVOLU(20) = MI``, which ``hm_read_monvol_type3.F:300-315``
#:            only derives when ``I_equi > 0``, and TEMPERATURE is assigned
#:            only inside ``IF (IEQUI > 0)`` at ``:159-161``. ``_emit_monvol_gas``
#:            hard-writes ``I_equi = 0`` and ``Mini = 0``, so MASS and T are
#:            requested only if that ever becomes settable. MEASURED over 505
#:            samples / 675 cycles of the adiabatic box: both min = max = 0
#:            while VOL/P/A/GAMA carry real data.
#:   AIRBAG1  ``airbagb1.F:655-679`` fills 1-12 and 15-18: the mixture CP/CV,
#:            the injected mass and enthalpy, the internal energy and the work
#:            on the structure (RVOLU(32)). **Not 13** — DTBAG. The bag's own
#:            time step goes to DT2/ITYPTS=9 and never to FSAV; index 13 is
#:            written only by the FVMBAG routines (``fvbag1.F:1808,1832``,
#:            ``fv_up_switch.F:1614,1638``), so it belongs to the batch that
#:            adds /MONVOL/FVMBAG1. MEASURED flat zero on a rigid sealed bag
#:            (1336 cycles), both vented bags and a deformable mini-bag.
#:   LFLUID   ``volp_lfluid.F``: 1=GMASS 2=VOL 3=PRES 4=AREA, plus RVOLU(54)
#:            = the cumulative mass in, which is the MASS-IN channel.
#:   COMMU1   AIRBAG1's list plus **AC** and **UC**, the communication area
#:            and the mean velocity through it. ``monvol0.F`` sends
#:            ``ITYP==7 .OR. ITYP==9`` to the same ``AIRBAGA1``/``AIRBAGB1``
#:            pair, so every AIRBAG1 channel is filled identically; AC and UC
#:            are the ``DO I=1,NAV`` communication loop's own sums, which only
#:            a COMMU1 has. A COMMU1 only ever exists here because an
#:            *AIRBAG_INTERACTION gave it a communicating row, so the two are
#:            never structurally zero on the cards this converter writes.
#:            **Not 13/14** — DTBAG and NFV are FVMBAG-only, as on AIRBAG1.
#:   FVMBAG2  ``fvbag1.F`` fills the finite-volume set: 1-7 and 10-12 as
#:            usual (FSAV(3) and FSAV(5) are the MASS-AVERAGED pressure and
#:            temperature over the FVs), plus the three this batch adds back —
#:            **13 DTBAG** (``fvbag1.F:1832``, ``FSAV(13)=DTX``, the bag's own
#:            CFL step, the thing ``/DT/FVMBAG`` overrides), **14 NFV**
#:            (``:1801``, ``FSAV(14)=NPOLH``, how many finite volumes are
#:            left after merging) and **19 UPCRIT** (``FSAV(19)=PDISP``, the
#:            pressure standard-deviation/mean ratio the uniform-pressure
#:            switch tests). This is the #123 handoff: DTBAG and NFV were
#:            dropped from AIRBAG1 as measured flat zeros and named as
#:            belonging "to the batch that adds /MONVOL/FVMBAG1" — this is
#:            that batch. **AC/UC are excluded** (no communication loop) and
#:            so is **18 WORK**, which the FV path never assigns.
#:
#: **Order matters and is not free.** The starter sorts the requested names
#: into its OWN ``VARMV`` table order (``hm_read_thgrou.F:1181-1186``:
#: MASS VOL P A T AO UO AC UC CP CV GAMA DTBAG NFV MASS-IN ENTHA-IN ENER-INT
#: WORK UPCRIT) and the T01 columns come back in that order, not in card
#: order. Writing the names already sorted makes the card describe the file it
#: produces — MEASURED, a group written MASS VOL P A T CP CV GAMA MASS-IN …
#: DTBAG AO UO AC UC came back with AO/UO/AC/UC in columns 6-9, mis-labelling
#: 9 of 17 channels for anyone reading th_to_csv positionally.
_TH_MONV_VARS = {
    "PRES":    ("VOL", "P", "A"),
    "GAS":     ("VOL", "P", "A", "GAMA"),
    "AIRBAG1": ("MASS", "VOL", "P", "A", "T", "CP", "CV", "GAMA",
                "MASS-IN", "ENTHA-IN", "ENER-INT", "WORK"),
    "LFLUID":  ("MASS", "VOL", "P", "A", "MASS-IN"),
    "COMMU1":  ("MASS", "VOL", "P", "A", "T", "AC", "UC", "CP", "CV", "GAMA",
                "MASS-IN", "ENTHA-IN", "ENER-INT", "WORK"),
    "FVMBAG2": ("MASS", "VOL", "P", "A", "T", "CP", "CV", "GAMA",
                "DTBAG", "NFV", "MASS-IN", "ENTHA-IN", "ENER-INT", "UPCRIT"),
}

#: Per model, the channels that exist only when the bag HAS a vent hole, and
#: where they belong in VARMV order (right after T). AIRBAG1 carries AC/UC
#: here because on a non-communicating volume they can only ever be a vent's;
#: COMMU1 does not, because its communication loop fills them whether or not
#: there is a vent, so they live in its base list instead.
_TH_MONV_VENT_VARS = {
    "AIRBAG1": ("AO", "UO", "AC", "UC"),
    "COMMU1":  ("AO", "UO"),
    "FVMBAG2": ("AO", "UO"),
}
_TH_MONV_VENT_AFTER = "T"


def _th_monv_groups(rad: str, ids: List[int], vented: set):
    """``[(variables, ids), ...]`` for one /MONVOL model.

    One group for a model with no vent channels, and otherwise one group per
    VENT state: the vent channels are inserted in VARMV order (right after T)
    for the bags that have a hole and left out for the ones that do not, so no
    bag loses a real channel to a sealed neighbour and none gains a flat zero.
    """
    base = list(_TH_MONV_VARS[rad])
    vent_vars = _TH_MONV_VENT_VARS.get(rad)
    if not vent_vars:
        return [(base, ids)]
    at = base.index(_TH_MONV_VENT_AFTER) + 1
    with_vent = base[:at] + list(vent_vars) + base[at:]
    groups = []
    for vars_, group_ids in ((with_vent, [i for i in ids if i in vented]),
                             (base, [i for i in ids if i not in vented])):
        if group_ids:
            groups.append((vars_, group_ids))
    return groups


def _make_starter_th_monv(state: ConversionState) -> List[str]:
    """*DATABASE_ABSTAT -> /TH/MONV over every emitted /MONVOL.

    "Airbag statistics. See *AIRBAG_OPTION" (Vol I R16 p.16-7), whose
    components are volume, internal energy and pressure (p.16-13). A
    presence-plus-DT trigger with no id list, answered by collecting every
    monitored volume the conversion actually wrote — the same shape
    /TH/RWALL, /TH/SECTIO, /TH/INTER and /TH/RBODY use.

    ``state.monvol_ids`` is filled AT THE LINE that writes each /MONVOL card
    (writer/monvol.py::_make_monvols), never derived from ``state.airbags``:
    a bag whose surface resolves to no shell element is dropped, and the #106
    rule is that a /TH group naming an entity the deck does not define is a
    starter ERROR that refuses the WHOLE run — strictly worse than losing the
    channel.

    One group PER MODEL, not one group for all of them, because the variable
    set is per model (see ``_TH_MONV_VARS``): a PRES bag's MASS, T and GAMA
    channels are structural zeros, and a group that mixes the four models
    would have to request the union and write those zeros for every PRES bag
    in the deck.

    Per-VENT-HOLE channels (``AOUT1``..``HOUT10``) are NOT requestable here —
    probe: ``ERROR ID : 260 ... TH VARIABLE AOUT1 IS NOT AVAILABLE``. They live
    in a second, AUTO-GENERATED group the starter creates after every /TH/MONV
    (``hm_read_thgrou.F:2745-2762``, titled ``"VENT " // <title>``), so the
    converter neither needs nor may emit one.
    """
    if not state.db_abstat_dt:
        # DT == 0 prints nothing (Vol I R16 p.16-7) and a blank DT defers to
        # LCDT, which /TFILE cannot express — the same two cases
        # _make_starter_th_rbody / _bndout gate on.
        if state.db_abstat_seen:
            _warn_db_card_without_dt(
                state, "*DATABASE_ABSTAT",
                "/TH/MONV over every converted monitored volume")
        return []
    if not state.monvol_ids:
        # An ABSTAT on a deck with NO *AIRBAG_* at all is inert in LS-DYNA too
        # — the abstat file would be empty there as well — and it is common
        # boilerplate: MEASURED, 73 of the 827 corpus decks carry one without a
        # single airbag keyword. That is a note, not a warning. An ABSTAT whose
        # airbags were DROPPED is a real loss and says so.
        if state.airbags:
            state.warn(
                "*DATABASE_ABSTAT requested and this deck DOES have "
                f"{len(state.airbags)} *AIRBAG_* card(s), but none of them "
                "converted to a /MONVOL — see the warnings above for why each "
                "was dropped. NO /TH/MONV is emitted: a group with no entity "
                "is not refused by the starter, it is accepted and written to "
                "the T01 holding zero entities, so it would only look like "
                "data.")
        else:
            state.note_recognized_not_emitted(
                "DATABASE_ABSTAT",
                "airbag statistics over the monitored volumes — this deck "
                "defines no *AIRBAG_*, so there is nothing to record and no "
                "/TH/MONV is emitted (LS-DYNA's abstat file would be empty "
                "too). The dt is honoured as one term of the /TFILE minimum "
                "only when a bag really converts.")
        return []
    by_model: Dict[str, List[int]] = {}
    vented: set = set()
    for ab in state.airbags:
        if ab.dropped or not ab.monvol_id:
            continue
        # ``radioss_type`` and NOT ``model``: which card a bag ends up on is a
        # resolver decision, not a keyword one — a *AIRBAG_HYBRID becomes a
        # COMMU1 the moment an *AIRBAG_INTERACTION names it, and a
        # *AIRBAG_PARTICLE becomes an AIRBAG1 under
        # --airbag-particle-uniform. Keying off the keyword would then request
        # channels the emitted card does not fill.
        rad = ab.radioss_type
        if rad not in _TH_MONV_VARS:                     # pragma: no cover
            continue
        by_model.setdefault(rad, []).append(ab.monvol_id)
        if ab.vents or ab.avent > 0.0 or ab.vent_fct_p:
            vented.add(ab.monvol_id)
    emitted = {mid for mid, _t in state.monvol_ids}
    lines = [
        "#-  TIME HISTORY (*DATABASE_ABSTAT -> monitored-volume statistics, "
        f"dt={state.db_abstat_dt:g}):", HDR,
    ]
    wrote = False
    for rad in ("PRES", "GAS", "AIRBAG1", "LFLUID", "COMMU1", "FVMBAG2"):
        ids = sorted(i for i in by_model.get(rad, []) if i in emitted)
        if not ids:
            continue
        # AIRBAG1 splits by VENT, not all-or-nothing. The four vent channels
        # are structural zeros on a bag with Nvent=0, but withholding them
        # from the whole group because ONE bag is unvented threw away real
        # data for every vented bag beside it. The group is already per model;
        # one more split costs one more group.
        for vars_, group_ids in _th_monv_groups(rad, ids, vented):
            th_id = state.next_id()
            lines += [
                f"/TH/MONV/{th_id}",
                f"TH_MONV_ABSTAT_{rad}",
                _th_var_header(vars_),
            ]
            lines += _th_var_lines(vars_)
            lines += _th_id_lines("MONV", group_ids)
            lines.append(HDR)
        wrote = True
    return lines if wrote else []


# ─────────────────────────────────────────────────────────────────────────────
# *CONTROL_PARALLEL -> engine /PARITH
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine_parith(state: ConversionState) -> List[str]:
    """*CONTROL_PARALLEL -> ``/PARITH/ON`` or ``/PARITH/OFF`` (engine card).

    ``CONST=1`` ("consistency: on") requires "that all contributions to global
    vectors be summed in a precise order independently of the number of
    processors used" (Vol I R16 p.12-449), which is precisely /PARITH/ON: the
    engine writes each element's contribution into a fixed per-node slot of the
    skyline ``FSKY`` array and gathers them in a deterministic walk
    (engine/source/assembly/asspar4.F), so the sum order is invariant in both
    the OpenMP thread count and the MPI domain count. MEASURED on a 576-brick
    LAW2 model, T01 decoded to full precision: /PARITH/ON gives a BITWISE
    identical T01 at nt=1 and nt=4, /PARITH/OFF differs in the 7th digit (row
    183 KE 3.495637e-02 vs 3.495636e-02). Cost on that model was 1.65x at
    nt=4; treat 15-25 % as the realistic figure on a real mesh, and re-measure.

    The card is header-only — ``FORMAT(radioss51) HEADER("/PARITH/%s",
    KEYWORD2)``, no data card — and the engine reader matches on a 5-character
    truncated key (``freform.F:560-571``, ``KEY0(34)='PARIT'``), so both
    ``/PARIT/ON`` and ``/PARITH/ON`` are accepted. An optional trailing integer
    is clamped away by ``rdresa.F:309``, so the bare form is what is written.

    **THE CARD IS EMITTED ONLY WHEN THE DECK CARRIES *CONTROL_PARALLEL.**
    dyna2rad creates /PARITH unconditionally and defaults it to OFF
    (convertcards.cxx:973-974) — before it has even looked for the LS-DYNA
    card. That is not neutral: OpenRadioss's own default is ON
    (starter/source/starter/contrl.F:400 sets ``IPARI0 = 1`` before
    HM_READ_ANALY), so dyna2rad silently FLIPS the solver default on every deck
    it converts, including decks that say nothing about parallelism. k2rad does
    not change a solver default from a card the deck does not carry; when the
    card IS there, both of its answers are honoured, OFF included.

    NCPU / NUMRHS / PARA have no Radioss counterpart and are named as dropped.
    """
    cards = state.ctrl_parallels
    if not cards:
        return []
    const_on = any(c.const == 1 for c in cards)
    dropped = sorted({name for c in cards
                      for name, v in (("NCPU", c.ncpu), ("NUMRHS", c.numrhs),
                                      ("PARA", c.para)) if v})
    if const_on:
        state.warn(
            "*CONTROL_PARALLEL CONST=1 (consistency on) -> engine /PARITH/ON: "
            "OpenRadioss then assembles nodal forces through the fixed-slot "
            "skyline array (asspar4.F) so the result is bit-reproducible "
            "independently of -nt and of the MPI domain count, the same "
            "guarantee LS-DYNA's CONST=1 gives. It costs run time (LS-DYNA "
            "quotes at least 15 % for PARA=0; measured 1.65x at nt=4 on a "
            "small brick model). VERIFY IT WAS CONSUMED by running the deck "
            "twice at different -Nt and diffing the decoded T01 - identical "
            "means the card took effect. Two things silently veto it and both "
            "leave a line in the _0001.out: an implicit run (PARITH/ON IS NOT "
            "COMPATIBLE WITH IMPLICIT OPTION ... RESETTING: PARITH/OFF, "
            "lectur.F:681) and /ANALY Iparith=2, which k2rad never writes."
            + (" NOTE: this deck is IMPLICIT or MODAL, so the engine WILL "
               "reset it to OFF." if (state.is_implicit or state.is_modal)
               else ""))
    else:
        state.warn(
            "*CONTROL_PARALLEL CONST="
            + ", ".join(str(c.const) for c in cards)
            + " (consistency off, LS-DYNA's own default) -> engine "
            "/PARITH/OFF. This is NOT a no-op: OpenRadioss's default is "
            "/PARITH/ON (contrl.F:400 sets IPARI0=1), so the card is written "
            "to hold the deck at the LS-DYNA behaviour - a faster run whose "
            "results shift in the last digits when the thread or domain count "
            "changes. Drop the card, or set CONST=1, if bit-reproducibility "
            "matters more than speed.")
    if dropped:
        state.warn(
            "*CONTROL_PARALLEL: " + ", ".join(dropped)
            + " - no OpenRadioss counterpart, DROPPED. NCPU is an SMP thread "
            "count, which "
            "OpenRadioss takes as the runtime -nt argument rather than a deck "
            "card (LS-DYNA itself disabled the field in 971 R5); NUMRHS and "
            "PARA are storage and assembly details of LS-DYNA's own SMP force "
            "accumulation, and /PARITH has no sub-option for either. dyna2rad "
            "drops all three silently.")
    return [f"/PARITH/{'ON' if const_on else 'OFF'}", "#"]


# ── Seatbelts: *DATABASE_SBTOUT -> /TH/SLIPRING + /TH/RETRACTOR ──────────────

#: /TH/SLIPRING and /TH/RETRACTOR channel names, from the READER's own tables
#: rather than from the cfg GUI lists, which are wrong for both cards:
#: ``th_slipring.cfg`` and ``th_retractor.cfg`` advertise a ``FORCE`` variable
#: that ``hm_read_thgrou.F`` does not know at all.
#:
#:   ``:1258  DATA VARSLIP/'RINGSLIP','FN','F1','F2','THETA','GAMMA'/``
#:   ``:1261  DATA VARRET /'SLIP','FN','LOCK'/``
#:
#: ``DEF`` expands to the whole row in both cases, so ``DEF`` is what is
#: written — naming the six (resp. three) individually would only risk
#: ``ERROR 260 TH VARIABLE <x> IS NOT AVAILABLE`` for no gain.
#:
#: Worth knowing when the T01 is read: ``RINGSLIP`` and ``SLIP`` are RUNNING
#: TOTALS — ``material_flow.F:284`` accumulates ``%RINGSLIP = %RINGSLIP -
#: DELTA_LO`` — so they are lengths already, not rates, and unlike the
#: /TH/INTER "force" channels they need no differentiation. ``THETA`` and
#: ``GAMMA`` are RADIANS. ``LOCK`` is 1.0 locked / 0.0 unlocked.
_TH_SEATBELT_VARS = ("DEF",)


def _make_starter_th_seatbelt(state: ConversionState) -> List[str]:
    """*DATABASE_SBTOUT -> /TH/SLIPRING + /TH/RETRACTOR.

    LS-DYNA writes ONE ``sbtout`` file for the whole restraint system; Radioss
    splits the same data across two group types, because the ring and the reel
    are separate entity families with separate channel sets. Both are emitted,
    with DIFFERENT group ids — sharing one is ``ERROR 79 DUPLICATE ID / IN TH
    GROUP DEFINITION``.

    This whole function is k2rad exceeding the reference converter. dyna2rad
    creates ``/TH/SLIPRING`` UNCONDITIONALLY from the model rather than from
    any ``*DATABASE_`` card (``convertelements.cxx:667-722``), over
    ``/SLIPRING/SPRING`` only (so a shell slipring never appears in it) and
    with the variable list hard-coded to ``{"DEF"}``; and it never emits
    ``/TH/RETRACTOR`` at all — ``grep -rn "TH/RETRACTOR"`` over its whole tree
    returns zero hits, so a retractor's force, pull-out and lock state are
    simply unavailable after a dyna2rad conversion. Its
    ``*DATABASE_SBTOUT`` handling is a bare ``dbCardList`` membership whose only
    effect is the /TFILE interval (``convertcards.cxx:94``).

    Gated on the CARD, not on the model, for the #122 reason every group in
    this file is: a /TH group is an OUTPUT REQUEST, and emitting one the deck
    did not ask for thickens the T01 with channels nobody reads. Screened
    against ``state.slipring_ids`` / ``state.retractor_ids``, which the writer
    fills AT the line that writes each card, for the #106 reason: several
    device cards are dropped (a shell slipring, a retractor whose mouth element
    did not convert), and a /TH naming one of those is a starter error that
    refuses the whole run.
    """
    if not state.db_sbtout_dt:
        if state.db_sbtout_seen:
            _warn_db_card_without_dt(
                state, "*DATABASE_SBTOUT",
                "/TH/SLIPRING and /TH/RETRACTOR over the converted seatbelt "
                "devices")
        return []
    have = bool(state.slipring_ids or state.retractor_ids)
    if not have:
        asked = (len(state.seatbelt_sliprings)
                 + len(state.seatbelt_retractors))
        if asked:
            state.warn(
                "*DATABASE_SBTOUT requested and this deck DOES have "
                f"{asked} slipring/retractor card(s), but none of them "
                "converted to a /SLIPRING or /RETRACTOR — see the warnings "
                "above for why each was dropped. NO /TH group is emitted: one "
                "with no entity is not refused by the starter, it is accepted "
                "and written to the T01 holding zero entities, so it would "
                "only look like data.")
        else:
            state.note_recognized_not_emitted(
                "DATABASE_SBTOUT",
                "seat-belt output over the sliprings and retractors — this "
                "deck defines none, so there is nothing to record and no "
                "/TH/SLIPRING or /TH/RETRACTOR is emitted (LS-DYNA's sbtout "
                "file would be empty too). The belt ELEMENT forces are a "
                "different request: they come from *DATABASE_HISTORY_SEATBELT, "
                "which builds /TH/SPRING groups. The dt is honoured as one "
                "term of the /TFILE minimum only when a device really "
                "converts.")
        return []
    lines: List[str] = [
        "#-  SEATBELT OUTPUT (*DATABASE_SBTOUT -> slipring + retractor "
        f"channels, dt={state.db_sbtout_dt:g}):", HDR]
    for kw, entries in (("SLIPRING", state.slipring_ids),
                        ("RETRACTOR", state.retractor_ids)):
        if not entries:
            continue
        ids = [i for i, _t in sorted(entries)]
        # state.next_id(), not a local 1..N counter: the /TH group id namespace
        # is GLOBAL ACROSS TYPES (assembly._warn_duplicate_th_group_ids, and
        # starter ERROR 79 IN TH GROUP DEFINITION), so a /TH/SLIPRING/1 beside
        # the /TH/SHEL/1 that _make_starter_th's own counter writes would
        # refuse the deck. Every group in this file below _make_starter_th
        # draws from the auto-id stream for exactly that reason.
        th_id = state.next_id()
        lines += [
            f"/TH/{kw}/{th_id}",
            f"TH_{kw}_SBTOUT",
            _th_var_header(_TH_SEATBELT_VARS),
        ]
        lines += _th_var_lines(_TH_SEATBELT_VARS)
        lines += _th_id_lines(kw, ids)
        lines.append(HDR)
    state.warn(
        "*DATABASE_SBTOUT -> "
        + " + ".join(
            f"/TH/{kw} over {len(e)} {kw.lower()}(s)"
            for kw, e in (("SLIPRING", state.slipring_ids),
                          ("RETRACTOR", state.retractor_ids)) if e)
        + ". DEF gives RINGSLIP FN F1 F2 THETA GAMMA on a slipring and SLIP FN "
        "LOCK on a retractor (hm_read_thgrou.F:1258,1261 — the cfg's "
        "advertised FORCE variable does not exist). RINGSLIP and SLIP are "
        "RUNNING TOTALS of belt length through the device, already lengths, so "
        "unlike the /TH/INTER force channels they need no differentiation; "
        "THETA and GAMMA are RADIANS; LOCK is 1.0 locked / 0.0 unlocked. "
        "dyna2rad emits no /TH/RETRACTOR at all.")
    return lines


def _make_starter_th_accel(state: ConversionState) -> List[str]:
    """*ELEMENT_SEATBELT_ACCELEROMETER -> /TH/ACCEL.

    An /ACCEL on its own writes NOTHING: it defines a measurement point, and
    the T01 carries it only through a /TH/ACCEL group. So the group is emitted
    whenever an accelerometer converted — a presence trigger on the
    ACCELEROMETER, not on a ``*DATABASE_`` card, which is the one place in this
    file where that is right. The keyword IS the output request: an
    ``*ELEMENT_SEATBELT_ACCELEROMETER`` exists for no other purpose than to
    record, and LS-DYNA reports it through ``nodout``, whose ``*DATABASE_``
    card is about the whole node set rather than about this instrument.
    dyna2rad builds the same group the same way (``convertelements.cxx:
    402-457``, ``var = {"DEF"}``).

    ``state.th_accel_ids`` is a SUBSET of ``state.accel_ids``: the /ACCEL a
    SBSTYP=1 ``*ELEMENT_SEATBELT_SENSOR`` needs exists only to satisfy
    ``sensor_acce.cfg``'s mandatory ``accel_ID``, and recording it would add a
    channel the deck never asked for. dyna2rad excludes those too, but by
    accident of ordering — ``p_CreateThAccel`` runs at ``:39``, BEFORE
    ``ConvertSeatbeltSensor`` at ``:41``, so they do not exist yet.
    """
    if not state.th_accel_ids:
        return []
    ids = [i for i, _t in sorted(state.th_accel_ids)]
    th_id = state.next_id()
    lines = ["#-  ACCELEROMETER OUTPUT (*ELEMENT_SEATBELT_ACCELEROMETER):",
             HDR,
             f"/TH/ACCEL/{th_id}", "TH_ACCEL",
             _th_var_header(("DEF",))]
    lines += _th_var_lines(("DEF",))
    lines += _th_id_lines("ACCEL", ids)
    lines.append(HDR)
    return lines
