"""
k2rad.assembly  –  parse-time application of the LS-DYNA assembly keywords:
*INCLUDE_TRANSFORM (id offsets + TRANID transform), *DEFINE_TRANSFORMATION
and *NODE_TRANSFORM.

Architecture (mirrors LS-DYNA's own order: id offset at read → geometric
transform → node-set transform):

  * The parser registers one PendingInclude per *INCLUDE_TRANSFORM while
    streaming (holding REFERENCES to the included file's Block objects — the
    same objects that get merged into the parent block list), then calls
    :func:`finalize` once at the end of the top-level parse.  Deferred
    resolution is required because the TRANID's *DEFINE_TRANSFORMATION may
    appear before OR after the include, or in a different include.
  * Everything is applied by mutating ``Block.raw`` in place BEFORE dispatch:
    nothing downstream (handlers/state/writer) reads raw afterwards, so the
    rest of the converter sees already-offset ids and already-transformed
    coordinates and needs no changes.  This is exactly LS-DYNA's semantics —
    offsets apply to every id INSIDE the included file (definitions and
    references alike), the parent references the post-offset ids.
  * Registration order is naturally innermost-first (a nested
    *INCLUDE_TRANSFORM registers during the child's recursion, before the
    parent's own entry covering the child blocks), so id offsets accumulate
    additively down the include chain and geometric transforms compose
    innermost-first — the LECSUBMOD level-walk semantics — for free.
  * Node-referenced transform rows resolve against parse-time (original)
    coordinates (the starter parses /TRANSFORM references in LECTRANSSUB
    before LECSUBMOD moves anything); *NODE_TRANSFORM rows resolve against
    CURRENT coordinates (LECTRANS applies in deck order after the submodel
    pass).  See k2rad.transform for the row math.

Only genuinely unsupported content warns: unknown transform verbs, unit
factors (FCTMAS/FCTTIM/FCTLEN/FCTTEM — a whole-deck unit rescale is the
kunit tool's domain), PREFIX/SUFFIX title decoration, keywords with no id
map, and coordinate-bearing keywords other than *NODE / *RIGIDWALL_PLANAR
(whose literal geometry IS transformed) inside a transformed include.  The
common TRANSL/ROTATE/SCALE/MIRROR + id-offset path is applied faithfully and
silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import permutations as _permutations, product as _product
from typing import Dict, List, Optional, Set, Tuple

from .handlers import (_AIRBAG_LEGACY_SUFFIXES, _AIRBAG_MODELS,
                       _AIRBAG_OPTION_STACKS,
                       INITIAL_STATE_PRELOAD_KEYWORDS,
                       RARE_CARD_KEYWORDS,
                       RARE_MATERIAL_KEYWORDS,
                       _SEATBELT_MAT_KEYWORDS,
                       _SEATBELT_SUBKEYWORDS,
                       final_geometry_node_row,
                       initial_strain_shell_records,
                       initial_stress_shell_records,
                       initial_stress_solid_records,
                       perturbation_node_records,
                       springback_records,
                       _SPOTWELD_CONTACT_KEYWORDS, _TYPE25_CONTACT_BASES,
                       TIEBREAK_CONTACT_KEYWORDS,
                       _cnrb_option_keywords, _cnrb_options,
                       _free_node_id,
                       _is_float_token, _is_int_token, _parse_sph_cell,
                       _seatbelt_rows,
                       _part_option_keywords,
                       _part_options, _rwall_geometric_keywords,
                       _rwall_planar_keywords)
from .parser import (Block, PARSER_WARNINGS, parse_fixed, parse_free,
                     set_active_scope, to_float, to_int)
from .state import FABRIC_CURVE_FORMS, SET_ADD_FAMILIES
from .transform import (Affine, TransformRow, affine_apply, compose_rows,
                        is_identity, linear_is_identity, mat_apply)

Vec3 = Tuple[float, float, float]


class _scoped_block:
    """Resolve ``&name`` against the *PARAMETER_LOCAL bindings of ONE block.

    ``finalize`` runs from ``parse_k_file`` AFTER ``_pop_local_scope()``, so by
    the time this module re-reads a Block's raw lines every LOCAL frame is gone
    from the parser's global tables — and an inner include's frame was popped
    even earlier, by its own recursive parse.  ``handlers.dispatch`` installs
    ``Block.scope`` around each handler call for exactly this reason; every walk
    in this module that feeds a raw cell to ``to_int``/``to_float`` needs the
    same install, because ``_rewrite_line`` decides "this cell is an id" from
    whether it parses as an integer and ``_rewrite_node_blocks`` REWRITES the
    coordinate it read.

    Without it a ``*PARAMETER_LOCAL``-supplied cell fails BOTH ways at once: an
    id cell reads 0, so it keeps its pre-offset value and the block collides
    with the parent deck's entity of the same number (measured: a child
    ``*PART &pid`` replaced the parent's part outright and its element was
    dropped as mesh loss), while a transformed coordinate is re-emitted as a
    literal 0.  A false "*PARAMETER reference '&pid' is undefined" warning is
    printed for a parameter that is perfectly well defined.

    The install is a two-element list write; ``Block.scope`` is ``None`` on every
    deck that uses no ``*PARAMETER_LOCAL``, which makes it a no-op there.
    """

    __slots__ = ("_prev", "_scope")

    def __init__(self, b: Block):
        self._scope = b.scope

    def __enter__(self):
        self._prev = set_active_scope(self._scope)
        return self

    def __exit__(self, *exc):
        set_active_scope(self._prev)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Offset buckets (the *INCLUDE_TRANSFORM card-2/3 fields)
# ─────────────────────────────────────────────────────────────────────────────
# n=IDNOFF nodes | e=IDEOFF elements | p=IDPOFF parts/CNRBs/rigidwalls/
# cross-sections | m=IDMOFF materials+EOS | s=IDSOFF sets | f=IDFOFF curves/
# tables/functions | d=IDDOFF other *DEFINE ids (coord systems, vectors, SD
# orientations, boxes, transformations) | r=IDROFF everything else (sections,
# hourglass, contacts, loads, ...)

_BUCKET_NAMES = {"n": "IDNOFF", "e": "IDEOFF", "p": "IDPOFF", "m": "IDMOFF",
                 "s": "IDSOFF", "f": "IDFOFF", "d": "IDDOFF", "r": "IDROFF"}

ALL = -1          # sentinel field index: every field on the line


@dataclass
class PendingInclude:
    """One *INCLUDE_TRANSFORM awaiting the deferred resolution pass."""
    filename: str
    sub_blocks: List[Block]           # the included file's blocks (shared refs)
    parent_blocks: List[Block]        # the INCLUDING file's block list
    offsets: Dict[str, int]
    tranid: int
    fctmas: float = 0.0
    fcttim: float = 0.0
    fctlen: float = 0.0
    fcttem: str = ""
    incout1: str = ""
    fctchg: str = ""
    prefix: str = ""
    suffix: str = ""
    transform_block: Optional[Block] = field(default=None, repr=False)


PENDING_INCLUDES: List[PendingInclude] = []


def reset() -> None:
    """Clear registration state (called at the start of a top-level parse)."""
    PENDING_INCLUDES.clear()


def _warn(msg: str) -> None:
    if msg not in PARSER_WARNINGS:
        PARSER_WARNINGS.append(msg)


# ─────────────────────────────────────────────────────────────────────────────
# Field helpers (free/fixed detection mirroring handlers._card)
# ─────────────────────────────────────────────────────────────────────────────

def _fields(line: str, n: int = 8, w: int = 10) -> List[str]:
    if "," in line:
        toks = parse_free(line)
        return toks + [""] * max(0, n - len(toks))
    f = parse_fixed(line, n, w)
    if any(" " in x.strip() for x in f):
        toks = parse_free(line)
        return toks + [""] * max(0, n - len(toks))
    return f


def _geti(f: List[str], i: int) -> int:
    return to_int(f[i]) if len(f) > i and str(f[i]).strip() else 0


def _title_offset(block: Block) -> int:
    """Raw lines consumed by a _TITLE/_SUBTITLE/_ID header (mirrors
    handlers._title_offset without importing handlers)."""
    if "ID" in block.options:
        return 1
    if "TITLE" in block.options or "SUBTITLE" in block.options:
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Registration (called from parser._flush)
# ─────────────────────────────────────────────────────────────────────────────

def register_include_transform(filename: str, raw: List[str],
                               sub_blocks: List[Block],
                               parent_blocks: List[Block]) -> None:
    """Parse cards 2-5 of an *INCLUDE_TRANSFORM POSITIONALLY from *raw*
    (blank placeholders intact — a deck that leaves card 2 blank but supplies
    TRANID on card 5 must not shift) and register the pending entry."""
    # Card 1 is the filename; locate it so stray leading blanks don't shift
    # the numbered cards.
    base = 0
    for k, ln in enumerate(raw):
        if ln.strip():
            base = k
            break
    c2 = _fields(raw[base + 1]) if len(raw) > base + 1 else []
    c3 = _fields(raw[base + 2]) if len(raw) > base + 2 else []
    c4 = _fields(raw[base + 3]) if len(raw) > base + 3 else []
    c5 = _fields(raw[base + 4]) if len(raw) > base + 4 else []
    offsets = {"n": _geti(c2, 0), "e": _geti(c2, 1), "p": _geti(c2, 2),
               "m": _geti(c2, 3), "s": _geti(c2, 4), "f": _geti(c2, 5),
               "d": _geti(c2, 6), "r": _geti(c3, 0)}
    gets = lambda f, i: f[i].strip() if len(f) > i and str(f[i]).strip() else ""
    getf = lambda f, i: to_float(f[i]) if len(f) > i and str(f[i]).strip() else 0.0
    PENDING_INCLUDES.append(PendingInclude(
        filename=filename, sub_blocks=sub_blocks, parent_blocks=parent_blocks,
        offsets=offsets, tranid=_geti(c5, 0),
        fctmas=getf(c4, 0), fcttim=getf(c4, 1), fctlen=getf(c4, 2),
        fcttem=gets(c4, 3), incout1=gets(c4, 4), fctchg=gets(c4, 5),
        prefix=gets(c3, 2), suffix=gets(c3, 3)))


# ─────────────────────────────────────────────────────────────────────────────
# Line rewriting
# ─────────────────────────────────────────────────────────────────────────────

def _split_card(line: str, w: int):
    """Split one card into fields, remembering how to reassemble it.

    Returns ``(fields, comma, ws_free)``. Shared by every card rewriter below so
    they can never disagree about a card's format."""
    if "," in line:
        return parse_free(line), True, False
    n_all = max(8, (len(line) + w - 1) // w)
    fields = parse_fixed(line, n_all, w)
    if any(" " in x.strip() for x in fields):
        return line.split(), False, True
    return fields, False, False


def _join_card(fields: List[str], comma: bool, ws_free: bool, w: int) -> str:
    """Reassemble a card split by :func:`_split_card`, in its own format."""
    fields = [x.strip() for x in fields]
    while fields and fields[-1] == "":
        fields.pop()
    if comma or any(len(x) > w for x in fields):
        return ",".join(fields)
    if ws_free:
        return " ".join(fields)
    return "".join(f"{x:>{w}}" for x in fields).rstrip()


def _rewrite_line(line: str, mods: List[Tuple[int, str]],
                  offsets: Dict[str, int], w: int = 10) -> Optional[str]:
    """Offset the id fields listed in *mods* on one card. Returns the new
    line, or None when nothing changed. Only ids > 0 are touched (0/blank is
    a none/ground/self sentinel everywhere; negative values are special
    encodings the OpenRadioss reader does not offset either)."""
    fields, comma, ws_free = _split_card(line, w)
    changed = False
    targets: List[Tuple[int, str]] = []
    for i, b in mods:
        if i == ALL:
            targets.extend((j, b) for j in range(len(fields)))
        elif i < len(fields):
            targets.append((i, b))
    for i, b in targets:
        off = offsets.get(b, 0)
        tok = fields[i].strip() if fields[i] else ""
        if not off or not tok:
            continue
        v = to_int(tok)
        if v > 0:
            fields[i] = str(v + off)
            changed = True
    if not changed:
        return None
    return _join_card(fields, comma, ws_free, w)


def _rewrite_neg_ref(line: str, i: int, off: int,
                     w: int = 10) -> Optional[str]:
    """Offset a NEGATIVE back-reference cell in place, keeping its sign.

    :func:`_rewrite_line` deliberately touches only values > 0 — everywhere else
    in LS-DYNA a negative id cell is a flag encoding, and adding an offset to it
    would move it towards zero. ``*SECTION_SHELL`` card-1 field 6 is the one
    exception this converter meets: ``QR/IRID``'s SIGN is the selector and its
    MAGNITUDE is an ``*INTEGRATION_SHELL`` id, so under ``*INCLUDE_TRANSFORM``
    it has to move with ``IDROFF`` like every other rule reference — otherwise
    the rule's own IRID is offset, the section's reference to it is not, and the
    pair dangles into a silent even-thickness split.
    """
    if not off:
        return None
    fields, comma, ws_free = _split_card(line, w)
    if i >= len(fields):
        return None
    tok = fields[i].strip() if fields[i] else ""
    if not tok:
        return None
    v = to_float(tok)
    if v >= 0.0:
        return None
    fields[i] = str(-(int(abs(v)) + off))
    return _join_card(fields, comma, ws_free, w)


def _rewrite_id_header(line: str, off: int) -> Optional[str]:
    """Offset the leading id of a '%10d%-70s' _ID heading card."""
    if not off:
        return None
    if "," in line:
        toks = line.split(",", 1)
        v = to_int(toks[0])
        if v > 0:
            return f"{v + off}," + (toks[1] if len(toks) > 1 else "")
        return None
    head, rest = line[:10], line[10:]
    if head.strip() and " " not in head.strip():
        v = to_int(head)
        if v > 0:
            return f"{v + off:>10}" + rest
        return None
    # free-format "id title..." heading
    toks = line.split(None, 1)
    if toks:
        v = to_int(toks[0])
        if v > 0:
            return f"{v + off:>10} " + (toks[1] if len(toks) > 1 else "")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# *NODE rewriting (id offset and/or coordinate transform in one pass)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_node_line(line: str):
    """Return (nid, [xt, yt, zt], tail) for one *NODE card — the coordinates
    as their RAW text tokens — or None. Mirrors handlers.handle_node: free
    split with a fixed I8+3×E16 fallback for glued negative coordinates;
    *tail* preserves the TC/RC columns verbatim.

    "Mirrors handlers.handle_node" is a CONTRACT, and it broke the moment that
    function grew its field-1 test: this one kept the width-only test, so an
    I8+3xE16 row with X and Y negative, Z not, and TC/RC present split into
    four ordinary-looking tokens with the id welded to the first, took the free
    branch, and returned None (``to_int`` of the merged token is 0). MEASURED
    on an *INCLUDE_TRANSFORM twin with such a child, AFTER handle_node was
    fixed and before this was: node ids came out
    ``[5, 7, 6001, 6002, 6003, 6004, 6006, 6008]`` — the two welded rows kept
    their PRE-offset ids (colliding with whatever the parent numbers 5 and 7)
    and were never transformed, while 6005 and 6007 simply did not exist and
    the /BRICK referencing them was broken. Not corpus-reachable: none of the
    10 ``*INCLUDE_TRANSFORM`` cards in either corpus root names a child with a
    welded row (checked by resolving each card's card-1 filename), which is
    why nothing measured it. See ``handlers.handle_node`` for the rest.
    """
    f = parse_free(line)
    if len(f) < 4 or any(len(t) > 16 for t in f[1:4]) \
            or not _free_node_id(f[0]):
        nid = to_int(line[0:8])
        if nid <= 0:
            return None
        return nid, [line[8:24], line[24:40], line[40:56]], line[56:]
    nid = to_int(f[0])
    if nid <= 0:
        return None
    tail = "".join(f"{t:>8}" for t in f[4:6]) if len(f) > 4 else ""
    return nid, [f[1], f[2], f[3]], tail


def _fmt_coord(v: float) -> str:
    """Transformed-coordinate text at the writer's precision (%.10G, so the
    final /NODE output equals what a lossless internal path would emit),
    widened to %.17G when a huge exponent overflows the 16-char fixed field —
    the emitter then switches the whole line to comma format."""
    s = f"{v:.10G}"
    return s if len(s) <= 16 else f"{v:.17G}"


def _emit_node_line(nid: int, toks: List[str], tail: str) -> str:
    """Re-emit one *NODE card from the (possibly rewritten) id and coordinate
    tokens. Falls back to comma free format when a token cannot fit its
    fixed-width field."""
    toks = [t.strip() for t in toks]
    if len(str(nid)) <= 8 and all(len(t) <= 16 for t in toks):
        return (f"{nid:>8}" + "".join(f"{t:>16}" for t in toks) + tail).rstrip()
    core = ",".join([str(nid)] + toks)
    extra = tail.strip().split()
    return ",".join([core] + extra) if extra else core


def _rewrite_node_blocks(blocks: List[Block], nodeoff: int = 0,
                         aff: Optional[Affine] = None,
                         only_ids: Optional[Set[int]] = None) -> Dict[int, Vec3]:
    """Apply an id offset and/or an affine to every *NODE line of *blocks*.
    Offset-only rewrites keep the original coordinate text verbatim (zero
    precision loss); transformed coordinates are re-emitted via _fmt_coord.
    Returns {final_nid: new_coords} for the rewritten nodes."""
    changed: Dict[int, Vec3] = {}
    if not nodeoff and aff is None:
        return changed
    for b in blocks:
        if b.keyword != "NODE":
            continue
        with _scoped_block(b):
            for k, line in enumerate(b.raw):
                if not line.strip():
                    continue
                parsed = _parse_node_line(line)
                if parsed is None:
                    continue
                nid, toks, tail = parsed
                if only_ids is not None and nid not in only_ids:
                    continue
                xyz = (to_float(toks[0]), to_float(toks[1]), to_float(toks[2]))
                if aff is not None:
                    xyz = affine_apply(aff, xyz)
                    toks = [_fmt_coord(v) for v in xyz]
                nid2 = nid + nodeoff if nodeoff else nid
                b.raw[k] = _emit_node_line(nid2, toks, tail)
                changed[nid2] = xyz
    return changed


def _collect_node_coords(blocks: List[Block]) -> Dict[int, Vec3]:
    table: Dict[int, Vec3] = {}
    for b in blocks:
        if b.keyword != "NODE":
            continue
        with _scoped_block(b):
            for line in b.raw:
                if not line.strip():
                    continue
                parsed = _parse_node_line(line)
                if parsed is not None:
                    toks = parsed[1]
                    table[parsed[0]] = (to_float(toks[0]), to_float(toks[1]),
                                        to_float(toks[2]))
    return table


def _node_ids_in(blocks: List[Block]) -> Set[int]:
    ids: Set[int] = set()
    for b in blocks:
        if b.keyword != "NODE":
            continue
        with _scoped_block(b):
            for line in b.raw:
                if line.strip():
                    parsed = _parse_node_line(line)
                    if parsed is not None:
                        ids.add(parsed[0])
    return ids


# ─────────────────────────────────────────────────────────────────────────────
# Custom per-keyword offset rewriters (layouts a flat card map cannot express)
# ─────────────────────────────────────────────────────────────────────────────

def _off_node(b: Block, offsets: Dict[str, int], warn) -> None:
    _rewrite_node_blocks([b], nodeoff=offsets.get("n", 0))


#: `*PART` option cards that carry an id, by option token: {card offset within the
#: option's cards: [(field index, bucket)]}. In CARD-SUMMARY order, mirroring
#: handlers._PART_OPTION_CARDS.
#:
#: Card 7 (_REPOSITION: CMSN MDEP MOVOPT) is deliberately left UNOFFSET. k2rad
#: warn-drops the card, so nothing downstream reads those ids, and guessing at
#: which of them are node/part references would rewrite numbers on the strength of
#: a guess. Card 8 (_CONTACT) and card 9 (_PRINT) hold no ids at all; card 11
#: (_FIELD FIDBO) names a *DEFINE_FIELD, which this converter does not read.
_PART_OPTION_ID_CARDS = {
    "REPOSITION": (1, {}),
    "CONTACT": (1, {}),
    "PRINT": (1, {}),
    "ATTACHMENT_NODES": (1, {0: [(0, "s")]}),   # ANSID = a *SET_NODE id
    "AVERAGED": (0, {}),
    "FIELD": (1, {}),
}


def _off_part(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every `*PART` spelling: the data card's ids, plus the option cards' ids.

    The walk mirrors ``handlers.handle_part`` exactly (the way ``_off_section_shell``
    mirrors its handler) rather than importing it. It has to: the old flat
    stride-of-2 loop would, on a `*PART_INERTIA` inside an `*INCLUDE_TRANSFORM`,
    rewrite the ``IXX IXY IXZ IYY IYZ IZZ`` card as if it were the next part's data
    card — corrupting the inertia numbers with a part/material/section offset.
    """
    # (title, data) pairs, possibly repeated: pid secid mid eosid hgid _ _ tmid
    mods = [(0, "p"), (1, "r"), (2, "m"), (3, "m"), (4, "r"), (7, "m")]
    opts, _unknown = _part_options(b.keyword)
    i = 0
    while i + 1 < len(b.raw):
        new = _rewrite_line(b.raw[i + 1], mods, offsets)
        if new is not None:
            b.raw[i + 1] = new
        i += 2
        if "INERTIA" in opts:
            # Card 3 XC YC ZC TM IRCS NODEID — NODEID is a node id; cards 4-5 are
            # pure floats; card 6's CID is a *DEFINE_COORDINATE_* id (IDDOFF), and
            # it exists only when card 3's IRCS reads 1.
            ircs = 0
            if i < len(b.raw):
                ircs = _geti(_fields(b.raw[i]), 4)
                new = _rewrite_line(b.raw[i], [(5, "n")], offsets)
                if new is not None:
                    b.raw[i] = new
            i += 3
            if ircs == 1:
                if i < len(b.raw):
                    new = _rewrite_line(b.raw[i], [(6, "d")], offsets)
                    if new is not None:
                        b.raw[i] = new
                i += 1
        for tok, (n_cards, id_fields) in _PART_OPTION_ID_CARDS.items():
            if tok not in opts:
                continue
            for k, cell_mods in id_fields.items():
                if i + k < len(b.raw):
                    new = _rewrite_line(b.raw[i + k], cell_mods, offsets)
                    if new is not None:
                        b.raw[i + k] = new
            i += n_cards


# *ELEMENT_SHELL / *ELEMENT_BEAM option grammar — mirrors handlers.py
# (_SHELL_SUFFIX_TOKENS / _BEAM_SUFFIX_TOKENS) without importing it, the same
# way _title_offset mirrors handlers._title_offset.
_SHELL_OPT_TOKENS = frozenset({"THICKNESS", "BETA", "MCID", "OFFSET", "DOF"})
_BEAM_OPT_TOKENS = frozenset({"ORIENTATION", "OFFSET"})
_TSHELL_OPT_TOKENS = frozenset({"BETA", "COMPOSITE"})


def _elem_opts(keyword: str, base: str, known: frozenset):
    tokens = [t for t in keyword[len(base):].split("_") if t]
    return ({t for t in tokens if t in known},
            [t for t in tokens if t not in known])


def _is_elem_conn_card(line: str, n_min: int) -> bool:
    """Content test for a connectivity card (see handlers._is_connectivity_card):
    every field is a plain positive integer. Used only on the UNKNOWN-suffix
    path, where the number of optional cards per element cannot be known."""
    f = [x for x in _fields(line, 10, 8) if x]
    if len(f) < n_min:
        return False
    return all(t.isdigit() and int(t) > 0 for t in f[:n_min])


def _off_element_shell(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *ELEMENT_SHELL spelling. Only the BASE card carries ids; the
    optional cards (THIC1..4+BETA/MCID, THIC5..8, OFFSET, NS1..NS4) must be
    stepped over — a generic w=8 reslice would cut their F16 floats in half and
    a blind id offset would corrupt them. The card count per element follows the
    option grammar exactly, so an integer-valued thickness card is skipped by
    POSITION, not by guessing at its content."""
    opts, unknown = _elem_opts(b.keyword, "ELEMENT_SHELL", _SHELL_OPT_TOKENS)
    if unknown:
        for k, line in enumerate(b.raw):
            if _is_elem_conn_card(line, 5):
                new = _rewrite_line(line, _ELEM_SHELL_MODS, offsets, w=8)
                if new is not None:
                    b.raw[k] = new
        return
    want_thic = bool(opts & {"THICKNESS", "BETA", "MCID"})
    i = 0
    while i < len(b.raw):
        f = [x for x in _fields(b.raw[i], 10, 8) if x]
        if len(f) < 5:
            i += 1
            continue
        midside = any(_geti(f, j) for j in range(6, min(10, len(f))))
        new = _rewrite_line(b.raw[i], _ELEM_SHELL_MODS, offsets, w=8)
        if new is not None:
            b.raw[i] = new
        i += 1 + int(want_thic) \
            + int("THICKNESS" in opts and midside) \
            + int("OFFSET" in opts) + int("DOF" in opts)


def _off_element_beam(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *ELEMENT_BEAM spelling — same shape as _off_element_shell. The
    _OFFSET (WX1..WZ2) and _ORIENTATION (VX VY VZ) cards hold no ids."""
    mods = [(0, "e"), (1, "p"), (2, "n"), (3, "n"), (4, "n")]
    opts, unknown = _elem_opts(b.keyword, "ELEMENT_BEAM", _BEAM_OPT_TOKENS)
    if unknown:
        for k, line in enumerate(b.raw):
            if _is_elem_conn_card(line, 4):
                new = _rewrite_line(line, mods, offsets, w=8)
                if new is not None:
                    b.raw[k] = new
        return
    step = 1 + int("OFFSET" in opts) + int("ORIENTATION" in opts)
    i = 0
    while i < len(b.raw):
        f = [x for x in _fields(b.raw[i], 10, 8) if x]
        if len(f) < 4:
            i += 1
            continue
        new = _rewrite_line(b.raw[i], mods, offsets, w=8)
        if new is not None:
            b.raw[i] = new
        i += step


def _off_tshell_ply_card(line: str) -> Optional[List[Tuple[int, str]]]:
    """The MID field indices of an *ELEMENT_TSHELL_COMPOSITE card 2b, or None
    when *line* is not one. Mirrors ``handlers._tshell_ply_card`` — including
    its FREE-FORMAT branch, where the gap columns 4 and 8 are simply not
    written and the second MID therefore sits at token 3 rather than 4.

    Its MID columns hold MATERIAL ids, which *INCLUDE_TRANSFORM offsets with
    IDMOFF — a bucket ``_rewrite_line`` would never apply from the connectivity
    mods — so the card is both strided over AND rewritten below, and the mods
    have to name the slots the ids are actually IN. The free branch is taken on
    the SAME test ``_fields`` uses to fall back, not on the token count: a
    fixed card with blank gap columns whitespace-splits to six tokens too."""
    fixed = parse_fixed(line, 8, 10)
    if "," in line or any(" " in x.strip() for x in fixed):
        toks = parse_free(line)
        if len(toks) in (3, 6):
            mids = [(0, "m")] + ([(3, "m")] if len(toks) == 6 else [])
            f = ([toks[0], toks[1], toks[2], ""]
                 + ([toks[3], toks[4], toks[5], ""] if len(toks) == 6
                    else ["", "", "", ""]))
        else:
            mids = [(0, "m"), (4, "m")]
            f = toks + [""] * max(0, 8 - len(toks))
    else:
        mids = [(0, "m"), (4, "m")]
        f = fixed
    if not f or not str(f[0]).strip():
        return None
    for gap in (3, 7):
        cell = str(f[gap]).strip() if len(f) > gap else ""
        if cell and to_float(cell, float("nan")) != 0.0:
            return None
    return mids


def _off_element_tshell(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *ELEMENT_TSHELL spelling — the same shape as _off_element_shell.

    Card 1 is ``EID PID N1..N8`` at I8. The _BETA card 2a holds no id (five F16
    cells, only BETA defined) but must be STRIDDEN; the _COMPOSITE card 2b holds
    two MATERIAL ids (IDMOFF) in fields 1 and 5, so it is rewritten at w=10 —
    the only *ELEMENT_ card in the converter that carries a *MAT reference.

    Mirrors handlers.handle_element_tshell's own walk rather than importing it,
    the way _SHELL_OPT_TOKENS mirrors the element-option grammar."""
    mods = [(0, "e"), (1, "p")] + [(i, "n") for i in range(2, 10)]
    opts, unknown = _elem_opts(b.keyword, "ELEMENT_TSHELL", _TSHELL_OPT_TOKENS)
    if unknown:
        for k, line in enumerate(b.raw):
            if _is_elem_conn_card(line, 6):
                new = _rewrite_line(line, mods, offsets, w=8)
                if new is not None:
                    b.raw[k] = new
        return
    i = 0
    while i < len(b.raw):
        f = [x for x in _fields(b.raw[i], 10, 8) if x]
        if len(f) < 6:
            i += 1
            continue
        new = _rewrite_line(b.raw[i], mods, offsets, w=8)
        if new is not None:
            b.raw[i] = new
        i += 1
        if "BETA" in opts and i < len(b.raw):
            i += 1                      # card 2a: no ids, but it IS a card
        if "COMPOSITE" in opts:
            while i < len(b.raw):
                mids = _off_tshell_ply_card(b.raw[i])
                if mids is None:
                    break
                new = _rewrite_line(b.raw[i], mids, offsets)
                if new is not None:
                    b.raw[i] = new
                i += 1


def _off_element_sph(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *ELEMENT_SPH spelling: ``NID(I8) PID(I8) MASS(F16) NEND(I8)``.

    Two things make this card unlike every other ``*ELEMENT_`` row in the table.

    **Field 0 takes the NODE offset, not the element offset.** An SPH particle
    IS its supporting node — the starter reads the single id column as the node
    user id and then forces the cell id equal to it
    (``hm_read_sphcel.F:243-250``) — so ``IDNOFF`` is the only offset that can
    apply, and applying ``IDEOFF`` there would break the cell↔node identity that
    Radioss enforces. ``NEND`` is a node id for the same reason and moves with
    it.

    This is precisely where dyna2rad cannot follow: it does not bake offsets in
    at all, it emits a ``//SUBMODEL`` and lets Radioss apply them — and the
    ``/SPHCEL`` id column is a PLAIN INT with no entity type, so the submodel
    machinery leaves it alone while ``/NODE`` moves. Measured on probe decks j
    and k, an ``*INCLUDE_TRANSFORM`` with ``IDNOFF=1000`` (with or without a
    matching ``IDEOFF``) gave four ``ERROR ID : 78 … NODE ID=1 DOES NOT EXIST``
    and ``TOTAL MASS = 0``. Baking the offset into the deck, as every k2rad
    ``_off_*`` does, is immune to that by construction.

    **The MASS column is SIXTEEN wide.** Rewriting the card on a uniform
    10-wide slice cuts a right-justified F16 mass in half — the
    ``*ELEMENT_MASS`` defect this mirrors — so the columns are preserved
    literally and only the id cells are re-rendered.

    **The card is read the way its HANDLER reads it, never on a fixed slice
    alone.** ``handlers._parse_sph_cell`` tries a whitespace split first and
    prefers it whenever it yields a complete card, precisely because the two
    column-layout variants in the wild (I10 ids, and an 8-wide MASS with NEND
    at 25-32) do not survive an I8/I8/F16 slice. A rewriter that slices where
    the handler splits is a SILENT DESYNC between two readers of one card:
    measured with ``IDNOFF=1000 IDPOFF=30``, the I10 card
    ``"       101         2   9.6834260e-05"`` came out as
    ``"    1001      31   2   9.6834260e-05"``, which the handler then read as
    ``(1001, 31, 2.0)`` — wrong node, wrong part, and a mass 20000x out — and
    an end-to-end I10 include lost 100 % of its particles to MESH LOSS while
    blaming ids that were never in the deck. So :func:`_sph_cell_split` makes
    the same free-vs-fixed decision the handler makes, and the free branch
    rewrites each id token IN PLACE, leaving the mass text byte-identical.
    """
    noff, poff = offsets.get("n", 0), offsets.get("p", 0)
    if not noff and not poff:
        return
    for k in range(len(b.raw)):
        line = b.raw[k]
        if not line.strip() or line.lstrip().startswith("$"):
            continue
        if "," in line:
            new = _rewrite_line(line, [(0, "n"), (1, "p"), (3, "n")],
                                offsets, w=8)
            if new is not None:
                b.raw[k] = new
            continue
        new = _off_sph_cell_line(line, noff, poff)
        if new is not None:
            b.raw[k] = new


#: ``NID``/``PID``/``MASS``/``NEND`` → the offset bucket each takes. Field 0 and
#: field 3 are both NODE ids (see :func:`_off_element_sph`); the MASS cell is
#: never an id and is never touched.
_SPH_CELL_BUCKETS = {0: "n", 1: "p", 3: "n"}

_NONBLANK_RE = re.compile(r"\S+")


def _sph_cell_split(data: str):
    """``(spans, fixed)`` for one *ELEMENT_SPH card — the SAME free-vs-fixed
    decision ``handlers._parse_sph_cell`` makes, expressed as character spans so
    the caller can rewrite an id without re-rendering the rest of the line.

    ``spans`` is a list of ``(start, end)`` into *data*, one per field in card
    order. ``fixed`` says which branch produced them, only so the caller can
    keep the fixed branch's 16-wide MASS cell intact.
    """
    toks = [(m.start(), m.end()) for m in _NONBLANK_RE.finditer(data)]
    words = [data[s:e] for s, e in toks]
    if len(words) >= 2 and _is_int_token(words[0]) and _is_int_token(words[1]) \
            and (len(words) == 2 or _is_float_token(words[2])):
        return toks, False
    # The one case the split cannot handle: ids wide enough to fill all eight
    # columns, which glues NID and PID into a single token.
    return [(0, 8), (8, 16), (16, 32), (32, len(data))], True


def _off_sph_cell_line(line: str, noff: int, poff: int):
    """Offset NID/PID/NEND on one *ELEMENT_SPH card, or None when nothing moved.

    Only the id CELLS are re-rendered; the mass text and any trailing ``$``
    comment survive byte-for-byte, and each id stays right-justified in its own
    column while it still fits — so an I8 deck comes out of the rewriter in the
    same columns it went in.

    The result is then CHECKED against the handler rather than assumed: the
    card is re-parsed with ``_parse_sph_cell`` and must read back as the source
    card plus the offsets. That is the invariant the whole function exists to
    hold, and it is cheap to assert. A layout that cannot keep its columns and
    still read back (an id that outgrows its cell and would touch its
    neighbour) falls back to a plain space-separated card, which always does.
    """
    src = _parse_sph_cell(line)
    if src is None:
        return None                     # not a particle card at all
    cut = line.find("$")
    data, tail = (line[:cut], line[cut:]) if cut >= 0 else (line, "")
    spans, _fixed = _sph_cell_split(data)
    cells: List[Tuple[int, int, str, Optional[str]]] = []
    want = list(src)
    changed = False
    for i, (s, e) in enumerate(spans):
        if s >= len(data):
            break
        tok = data[s:e]
        off = {"n": noff, "p": poff}.get(_SPH_CELL_BUCKETS.get(i, ""), 0)
        new = None
        if off and tok.strip() and _is_int_token(tok) and to_int(tok) > 0:
            new = str(to_int(tok) + off)
            want[i] = src[i] + off
            changed = True
        cells.append((s, e, tok, new))
    if not changed:
        return None
    out: List[str] = []
    prev = 0
    for s, e, tok, new in cells:
        gap = data[prev:s]
        if new is None:
            out.append(gap + tok)
        else:
            width = len(gap) + len(tok)
            out.append(new.rjust(width) if len(new) <= width else gap + new)
        prev = max(prev, e)
    cand = ("".join(out) + data[prev:]).rstrip()
    if _parse_sph_cell(cand) != tuple(want):
        # Re-render as a plain space-separated card. The handler prefers the
        # whitespace split whenever it yields a complete card, so this reading
        # is stable by construction.
        toks = [(new if new is not None else tok).strip()
                for _s, _e, tok, new in cells]
        while toks and not toks[-1]:
            toks.pop()
        cand = " ".join(toks)
    return (cand + tail).rstrip()


def _off_section_sph(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_SPH card set: SECID (IDROFF).

    A card-SET walker rather than a declarative spec, for the reason every
    *SECTION_* keyword here is one — a declarative spec addresses only the first
    set, and every later section in the block would keep its original SECID
    while the *PARTs that name it moved. The ``_ELLIPSE``/``_TENSOR`` card 2 is
    strided BY POSITION (the #119 rule) and must stay in lockstep with
    ``handlers.handle_section_sph``, which claims it the same way: it carries no
    id, but it IS a card, and skipping it as whitespace would rewrite the NEXT
    set's SECID out of a column of anisotropic h values.
    """
    per_set_title = _title_offset(b)
    raw = b.raw
    has_card2 = ("ELLIPSE" in b.keyword) or ("TENSOR" in b.keyword)
    idx = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:                       # one 80a title card per set
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)      # SECID
        if new is not None:
            raw[idx] = new
        idx += 1 + (1 if has_card2 else 0)


def _off_element_solid(b: Block, offsets: Dict[str, int], warn) -> None:
    """Both *ELEMENT_SOLID layouts (mirrors handle_element_solid detection):
    ten-node = (eid pid) / (n1..n10) line pairs, else eid pid n1..n8 per line."""
    idxs = [k for k, ln in enumerate(b.raw) if ln.strip()]
    if not idxs:
        return
    first = [x for x in _fields(b.raw[idxs[0]], 10, 8) if x]
    if len(first) == 2 and len(idxs) > 1:
        second = [x for x in _fields(b.raw[idxs[1]], 10, 8) if x]
        ten_node = len(second) >= 4
    else:
        ten_node = len(first) < 6
    if ten_node:
        for j in range(0, len(idxs) - 1, 2):
            new = _rewrite_line(b.raw[idxs[j]], [(0, "e"), (1, "p")], offsets, w=8)
            if new is not None:
                b.raw[idxs[j]] = new
            new = _rewrite_line(b.raw[idxs[j + 1]], [(ALL, "n")], offsets, w=8)
            if new is not None:
                b.raw[idxs[j + 1]] = new
    else:
        mods = [(0, "e"), (1, "p")] + [(i, "n") for i in range(2, 10)]
        for k in idxs:
            new = _rewrite_line(b.raw[k], mods, offsets, w=8)
            if new is not None:
                b.raw[k] = new


def _off_element_discrete(b: Block, offsets: Dict[str, int], warn) -> None:
    """EID PID N1 N2 VID (I8×5) S(E16) PF(I8) OFFSET(E16): the E16 fields make
    a generic w=8 reslice unsafe (an E16 float spans two 8-char slices), so on
    dense fixed lines only the five leading I8 slots are rewritten and
    everything from column 40 on is kept verbatim."""
    mods = [(0, "e"), (1, "p"), (2, "n"), (3, "n"), (4, "d")]
    for k, line in enumerate(b.raw):
        if not line.strip():
            continue
        f = parse_free(line)
        if "," in line:
            new = _rewrite_line(line, mods, offsets, w=8)
            if new is not None:
                b.raw[k] = new
            continue
        if len(f) >= 3 and not any(len(t) > 8 for t in f[:5]):
            # Clean whitespace tokens: token order == field order (the same
            # free-first rule handle_element_discrete uses). Re-join as tokens
            # so the E16 S/OFFSET floats are never resliced at w=8.
            toks = list(f)
            changed = False
            for i, bucket in mods:
                off = offsets.get(bucket, 0)
                if off and i < len(toks) and toks[i].strip():
                    v = to_int(toks[i])
                    if v > 0:
                        toks[i] = str(v + off)
                        changed = True
            if changed:
                b.raw[k] = " ".join(t for t in toks if t != "")
            continue
        head = parse_fixed(line, 5, 8)
        tail = line[40:]
        changed = False
        for i, bucket in mods:
            off = offsets.get(bucket, 0)
            tok = head[i].strip()
            if off and tok:
                v = to_int(tok)
                if v > 0:
                    head[i] = str(v + off)
                    changed = True
        if changed:
            b.raw[k] = ("".join(f"{x:>8}" for x in head) + tail).rstrip()


def _off_element_mass(b: Block, offsets: Dict[str, int], warn,
                      id_bucket: str = "n") -> None:
    """eid(I8) id(I8) mass(F16) pid(I8) — *ELEMENT_MASS (id = node) and
    *ELEMENT_MASS_NODE_SET (id = node set)."""
    start = 1 if "ID" in b.options else 0
    for k in range(start, len(b.raw)):
        line = b.raw[k]
        if not line.strip():
            continue
        if "," in line:
            new = _rewrite_line(line, [(0, "e"), (1, id_bucket), (3, "p")],
                                offsets, w=8)
            if new is not None:
                b.raw[k] = new
            continue
        eid, nid = line[0:8], line[8:16]
        mass, pid = line[16:32], line[32:40]
        changed = False
        for tok, bucket in ((eid, "e"), (nid, id_bucket), (pid, "p")):
            if offsets.get(bucket, 0) and tok.strip() and to_int(tok) > 0:
                changed = True
        if not changed:
            continue
        def _sh(tok: str, bucket: str, width: int) -> str:
            off = offsets.get(bucket, 0)
            if off and tok.strip():
                v = to_int(tok)
                if v > 0:
                    return f"{v + off:>{width}}"
            return tok.ljust(width) if tok else ""
        b.raw[k] = (_sh(eid, "e", 8) + _sh(nid, id_bucket, 8)
                    + mass.ljust(16) + _sh(pid, "p", 8)).rstrip()


def _off_element_mass_node_set(b: Block, offsets: Dict[str, int], warn) -> None:
    _off_element_mass(b, offsets, warn, id_bucket="s")


def _contact_side_bucket(styp: int) -> Optional[str]:
    """SSTYP/MSTYP → id namespace: 3 = part id, 5/6-all = no id, else set id
    (0 segment set, 1 shell set, 2 part set, 4 node set, 6 exempted part set)."""
    if styp == 3:
        return "p"
    if styp == 5:
        return None
    return "s"


def _off_contact(b: Block, offsets: Dict[str, int], warn) -> None:
    start = 0
    if "ID" in b.options and b.raw:
        new = _rewrite_id_header(b.raw[0], offsets.get("r", 0))
        if new is not None:
            b.raw[0] = new
        start = 1
    if start >= len(b.raw) or not b.raw[start].strip():
        return
    f = _fields(b.raw[start])
    sstyp, mstyp = _geti(f, 2), _geti(f, 3)
    mods: List[Tuple[int, str]] = [(4, "d"), (5, "d")]     # SBOXID/MBOXID
    sb = _contact_side_bucket(sstyp)
    mb = _contact_side_bucket(mstyp)
    if sb:
        mods.append((0, sb))
    if mb:
        mods.append((1, mb))
    new = _rewrite_line(b.raw[start], mods, offsets)
    if new is not None:
        b.raw[start] = new


def _off_define_friction(b: Block, offsets: Dict[str, int], warn) -> None:
    """*DEFINE_FRICTION: the table ID → IDDOFF, every Card-2 part pair → IDPOFF
    or IDSOFF depending on that row's own PTYPEi/PTYPEj.

    IDDOFF, not IDROFF: LS-DYNA Vol I p.27-5 defines it as "Offset to any ID
    defined through *DEFINE, except the FUNCTION, TABLE, and CURVE options",
    which is where every other *DEFINE_* entry in this table sends its id
    (bucket "d"), while *DEFINE_CURVE / *DEFINE_TABLE use IDFOFF ("f").

    A walker rather than a declarative spec because the bucket is PER ROW AND
    PER COLUMN: PTYPEi/j (fields 6/7) is the literal string ``PSET`` when the
    id in field 0/1 names a *SET_PART, and blank/anything else when it names a
    part. The two columns are independent — a row may mix a part with a part
    set. Getting this wrong is not cosmetic: an un-offset part id inside an
    *INCLUDE_TRANSFORM matches nothing, and writer/frictions.py then drops the
    whole pair row back to the table's default coefficients.
    """
    toff = _title_offset(b)
    if toff < len(b.raw) and b.raw[toff].strip():
        new = _rewrite_line(b.raw[toff], [(0, "d")], offsets)
        if new is not None:
            b.raw[toff] = new
    if not offsets.get("p", 0) and not offsets.get("s", 0):
        return

    def bucket(f: List[str], i: int) -> str:
        """PTYPEi/PTYPEj sits 6 fields to the right of the id it types."""
        ptype = f[i + 6].strip().upper() if len(f) > i + 6 else ""
        return "s" if ptype == "PSET" else "p"

    for k in range(toff + 1, len(b.raw)):
        line = b.raw[k]
        if not line.strip():
            continue
        f = _fields(line)
        new = _rewrite_line(line, [(0, bucket(f, 0)), (1, bucket(f, 1))],
                            offsets)
        if new is not None:
            b.raw[k] = new


def _off_define_transformation(b: Block, offsets: Dict[str, int], warn) -> None:
    """TRANID → IDDOFF; node-referencing option rows → IDNOFF (POINT ids are
    local to the definition and never offset)."""
    toff = _title_offset(b)
    if toff < len(b.raw) and b.raw[toff].strip():
        new = _rewrite_line(b.raw[toff], [(0, "d")], offsets)
        if new is not None:
            b.raw[toff] = new
    node_fields = {"TRANSL2ND": [1, 2], "ROTATE3NA": [1, 2, 3],
                   "POS6N": [1, 2, 3, 4, 5, 6]}
    if not offsets.get("n", 0):
        return
    for k in range(toff + 1, len(b.raw)):
        line = b.raw[k]
        if not line.strip():
            continue
        if "," in line:
            verb = parse_free(line)[0].strip().upper()
            fields = node_fields.get(verb)
            if fields:
                new = _rewrite_line(line, [(i, "n") for i in fields], offsets)
                if new is not None:
                    b.raw[k] = new
            continue
        verb = line[:10].strip().upper()
        a = parse_fixed(line[10:], 7, 10)
        if " " in verb or any(" " in x.strip() for x in a):
            # Whitespace free format (mirrors _parse_transformation_rows'
            # detection so a row the geometry pass can resolve is never left
            # with un-offset node references).
            toks = line.split()
            verb = toks[0].strip().upper()
            fields = node_fields.get(verb)
            if not fields:
                continue
            changed = False
            for i in fields:
                if i < len(toks):
                    v = to_int(toks[i])
                    if v > 0:
                        toks[i] = str(v + offsets["n"])
                        changed = True
            if changed:
                b.raw[k] = " ".join(toks)
            continue
        fields = node_fields.get(verb)
        if not fields:
            continue
        changed = False
        for i in fields:
            tok = a[i - 1].strip()
            if tok:
                v = to_int(tok)
                if v > 0:
                    a[i - 1] = str(v + offsets["n"])
                    changed = True
        if changed:
            b.raw[k] = f"{verb:<10}" + "".join(f"{x:>10}" for x in a).rstrip()


def _off_cnrb(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every `*CONSTRAINED_NODAL_RIGID_BODY` spelling.

    Card 1: ``pid cid nsid pnode ...``. Then, in CARD-SUMMARY order (which is fixed
    even though the keyword's option order is not — mirrors
    ``handlers.handle_constrained_nodal_rigid_body``):

      * ``_SPC`` card 2 ``CMO CON1 CON2 SPCNID`` — with ``CMO < 0`` ``CON1`` is a
        local *DEFINE_COORDINATE_* system id (IDDOFF), not a DOF code;
      * ``_INERTIA`` cards 3-5, of which only card 3's ``NODEID`` is an id, plus
        card 6's ``CID2`` (IDDOFF) when card 3's ``IRCS`` reads 1;
      * ``_OVERRIDE`` card 7 and ``_THERMAL`` card 8 hold flags only.

    Every option card must be STEPPED OVER even when it carries no id: without the
    stride, an ``_INERTIA`` block's card 6 ``CID2`` would never be offset while the
    coordinate system it names would be, leaving the reference dangling.

    ``_TITLE`` costs a card too, from either place it can end up in: the parser
    moves a TRAILING one into ``block.options`` (``_title_offset`` sees it), a
    MID-position one stays spelled out in the keyword. Missing the second kind
    would rewrite the 80a title line as if it were card 1.
    """
    opts, kw_title = _cnrb_options(b.keyword)
    toff = _title_offset(b) or (1 if kw_title else 0)
    if toff < len(b.raw) and b.raw[toff].strip():
        new = _rewrite_line(b.raw[toff], [(0, "p"), (1, "d"), (2, "s"),
                                          (3, "n")], offsets)
        if new is not None:
            b.raw[toff] = new
    i = toff + 1
    if "SPC" in opts:
        if i < len(b.raw) and b.raw[i].strip():
            f = _fields(b.raw[i])
            cmo = to_float(f[0]) if f and str(f[0]).strip() else 0.0
            mods: List[Tuple[int, str]] = [(3, "n")]       # SPCNID
            if cmo < 0.0:
                mods.append((1, "d"))                     # CON1 = system id
            new = _rewrite_line(b.raw[i], mods, offsets)
            if new is not None:
                b.raw[i] = new
        i += 1
    if "INERTIA" in opts:
        ircs = 0
        if i < len(b.raw):
            ircs = _geti(_fields(b.raw[i]), 4)
            new = _rewrite_line(b.raw[i], [(5, "n")], offsets)   # NODEID
            if new is not None:
                b.raw[i] = new
        i += 3
        if ircs == 1:
            if i < len(b.raw):
                new = _rewrite_line(b.raw[i], [(6, "d")], offsets)   # CID2
                if new is not None:
                    b.raw[i] = new
            i += 1
    if "OVERRIDE" in opts:
        i += 1
    if "THERMAL" in opts:
        i += 1


def _off_constrained_interpolation(b: Block, offsets: Dict[str, int],
                                   warn) -> None:
    """`*CONSTRAINED_INTERPOLATION[_LOCAL]`.

    Card 1: ``ICID DNID DDOF CIDD ITYP IDNSW FGM`` — the constraint id goes to
    IDROFF, ``DNID`` to IDNOFF and ``CIDD`` to IDDOFF. ``DDOF`` is a DOF digit
    string, not an id, and must never be offset.

    Card 2, repeated to the end of the block: ``INID`` is a NODE id when ``ITYP``
    is 0 and a *SET_NODE id when it is 1 — the bucket depends on a card-1 value.
    With ``_LOCAL`` each card 2 is followed by its own ``CIDI`` card (IDDOFF),
    which has to be stepped over per pair or the pairing slips by one line.
    """
    is_local = b.keyword.endswith("_LOCAL")
    toff = _title_offset(b)
    if toff >= len(b.raw):
        return
    ityp = 0
    if b.raw[toff].strip():
        ityp = _geti(_fields(b.raw[toff]), 4)
        new = _rewrite_line(b.raw[toff], [(0, "r"), (1, "n"), (3, "d")], offsets)
        if new is not None:
            b.raw[toff] = new
    ind_bucket = "s" if ityp else "n"
    # Last non-blank line located once — a re-sliced ``b.raw[i:]`` blank-tail probe
    # per iteration is quadratic on a thousand-node spider (mirrors the same fix in
    # handlers.handle_constrained_interpolation).
    last_data = -1
    for j in range(len(b.raw) - 1, toff, -1):
        if b.raw[j].strip():
            last_data = j
            break
    i = toff + 1
    while i <= last_data:
        new = _rewrite_line(b.raw[i], [(0, ind_bucket)], offsets)
        if new is not None:
            b.raw[i] = new
        i += 1
        if is_local:
            if i < len(b.raw):
                new = _rewrite_line(b.raw[i], [(0, "d")], offsets)
                if new is not None:
                    b.raw[i] = new
            i += 1


# *SECTION_SHELL / *INTEGRATION_SHELL card-set walks. Both keywords let a deck
# stack several SETS under one header, and a declarative spec can only address
# one set: the flat form offset the FIRST section's SECID and then treated every
# later line as data. That leaves set 2's SECID behind (so a *PART in the same
# include dangles into a zero-thickness placeholder) and, on the rule keyword,
# offsets a stacked rule's ESOP column with IDPOFF as if card 1 were a point
# card — which the reader then reports as "ESOP=<offset> is neither 0 nor 1".
# Both walks mirror handlers.py's own, the way _SHELL_OPT_TOKENS above mirrors
# the element-option grammar, rather than importing it.
_SECTION_SHELL_OPTION_CARDS = ("EFG", "THERMAL", "XFEM", "MISC")
_USER_SHELL_ELFORMS = frozenset({101, 102, 103, 104, 105})


def _off_section_shell(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_SHELL card set: SECID (IDROFF) plus the card-1 field-6
    QR/IRID back-reference to an *INTEGRATION_SHELL rule, which is NEGATED and
    so needs the sign-preserving rewriter, plus the card-2 field-7 EDGSET.

    EDGSET is the ONE id on card 2 — the rest of the card is thicknesses,
    NLOC, MAREA and the IDOF flag. It names a ``*SET_NODE`` and so belongs to
    IDSOFF, not to card 1's IDROFF; ``handle_section_shell`` reads it into
    ``SectionShell.nsid`` and the 2D-seatbelt writer quotes it back at the
    user, so an un-offset cell would name a set that exists in neither the
    child deck nor the converted model."""
    per_set_title = _title_offset(b)
    opt_card = any(b.keyword.endswith("_" + o)
                   for o in _SECTION_SHELL_OPTION_CARDS)
    raw = b.raw
    idx = 0
    roff = offsets.get("r", 0)
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:                       # one 80a title card per set
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)      # SECID
        if new is not None:
            raw[idx] = new
        new = _rewrite_neg_ref(raw[idx], 5, roff)               # -QR/IRID
        if new is not None:
            raw[idx] = new
        nip = abs(_geti(f1, 3))
        if idx + 1 < len(raw):                  # card 2 field 7 = EDGSET
            new = _rewrite_line(raw[idx + 1], [(7, "s")], offsets)
            if new is not None:
                raw[idx + 1] = new
        idx += 2
        if _geti(f1, 6) == 1:                   # ICOMP: ceil(NIP/8) angle cards
            idx += ((nip if nip > 0 else 2) + 7) // 8
        if opt_card:                            # card 4a-4d
            # None of the four option cards carries an ID. _THERMAL's single
            # cell is ITHELFM — "Thermal shell formulation" (Keyword971_R10.1/
            # PROPERTY/SectShll.cfg:53; the GUI radio reads "1: Thick thermal
            # shell / 2: Thin thermal shell"), a formulation FLAG, not the
            # *MAT_THERMAL_* id that *PART's TMID names. The corpus carrier
            # 07_metalstrip.k writes 1 and 2 there while both its parts state
            # TMID 1. So the card is only STRIDDEN, like EFG / XFEM / MISC.
            idx += 1
        if _geti(f1, 1) in _USER_SHELL_ELFORMS:  # cards 5 / 5.1 / 5.2
            f5 = _fields(raw[idx], 8, 10) if idx < len(raw) else []
            if not f5:
                break
            idx += 1 + max(_geti(f5, 0), 0) + (max(_geti(f5, 5), 0) + 7) // 8


def _off_integration_shell(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *INTEGRATION_SHELL rule under the header: card 1's IRID shares the
    *SECTION id space (IDROFF), and only a real S/WF/PID point card carries a
    *PART reference (IDPOFF) in field 3."""
    raw = b.raw
    idx = 0
    while idx < len(raw):
        if not raw[idx].strip():
            idx += 1
            continue
        f1 = _fields(raw[idx], 4, 10)
        if _geti(f1, 0) <= 0:
            return
        nip, esop = _geti(f1, 1), _geti(f1, 2)
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)
        if new is not None:
            raw[idx] = new
        idx += 1
        if esop != 0 or nip <= 0:               # ESOP=1: no point cards at all
            continue
        for _ in range(nip):
            while idx < len(raw) and not raw[idx].strip():
                idx += 1
            if idx >= len(raw):
                return
            new = _rewrite_line(raw[idx], [(2, "p")], offsets)
            if new is not None:
                raw[idx] = new
            idx += 1


# *SECTION_SOLID / *SECTION_BEAM / *SECTION_DISCRETE / *INTEGRATION_BEAM card-set
# walks. Same reason as the shell pair above: every one of these keywords lets a
# deck stack several SETS under one header, and the flat declarative form offset
# only the FIRST set's SECID — leaving every later section behind, so a *PART in
# the same include dangled onto an auto-generated placeholder property. The beam
# keyword additionally carries the NEGATED card-1 field-4 QR/IRID back-reference,
# which _rewrite_line cannot touch. All four mirror handlers.py's own walks
# rather than importing them.
_SECTION_SOLID_OPTION_CARDS = {"EFG": 2, "SPG": 2, "MISC": 1}
_USER_SOLID_ELFORMS = frozenset({101, 102, 103, 104, 105})


def _beam_card2_kind(elform: int, first_field: str) -> str:
    """Which *SECTION_BEAM card-2 dialect a set takes (mirrors
    handlers._beam_card2_kind); "" when ELFORM defines none."""
    named = str(first_field).strip().upper().startswith("SECTION")
    if elform in (0, 1, 11):
        return "2a"
    if elform in (2, 3, 12) and named:
        return "2b"
    if elform in (2, 12, 13):
        return "2c"
    if elform == 3:
        return "2d"
    if elform in (4, 5):
        return "2e"
    if elform == 6:
        return "2f"
    if elform in (7, 8):
        return "2h"
    if elform == 9:
        return "2i"
    if elform == 14:
        return "2j"
    return ""


def _off_section_solid(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_SOLID card set: SECID (IDROFF). The option cards and the
    ELFORM 101-105 cards carry no id but must still be strided over."""
    per_set_title = _title_offset(b)
    opt_cards = sum(n for o, n in _SECTION_SOLID_OPTION_CARDS.items()
                    if b.keyword.endswith("_" + o)
                    or ("_" + o + "_") in b.keyword)
    raw = b.raw
    idx = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:                       # one 80a title card per set
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)
        if new is not None:
            raw[idx] = new
        idx += 1 + opt_cards
        if _geti(f1, 1) in _USER_SOLID_ELFORMS:  # cards 3 / 4 / 5
            f3 = _fields(raw[idx], 8, 10) if idx < len(raw) else []
            if not f3:
                break
            idx += 1 + max(_geti(f3, 0), 0) + (max(_geti(f3, 4), 0) + 7) // 8


def _off_section_tshell(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_TSHELL card set: SECID (IDROFF).

    The ICOMP=1 angle block is card **2** here, not card 3 — this keyword has no
    thickness card — so the stride is ``1 + ceil(NIP/8)``, and the angle cards
    are consumed BY COUNT (an all-zero angle card is written blank, and skipping
    it as whitespace would offset the NEXT set's card 1 as if it were data).
    Card 1 field 6 (QR) can hold a NEGATED *INTEGRATION_SHELL reference exactly
    as *SECTION_SHELL's does, so it takes the sign-preserving rewriter too."""
    per_set_title = _title_offset(b)
    raw = b.raw
    idx = 0
    roff = offsets.get("r", 0)
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:                       # one 80a title card per set
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)      # SECID
        if new is not None:
            raw[idx] = new
        new = _rewrite_neg_ref(raw[idx], 5, roff)               # -QR/IRID
        if new is not None:
            raw[idx] = new
        nip = abs(_geti(f1, 3))
        idx += 1
        if _geti(f1, 6) == 1:                   # ICOMP: ceil(NIP/8) angle cards
            idx += ((nip if nip > 0 else 2) + 7) // 8


def _off_section_beam(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_BEAM card set: SECID (IDROFF) plus the card-1 field-4
    QR/IRID back-reference to an *INTEGRATION_BEAM rule, which is NEGATED and so
    needs the sign-preserving rewriter.

    Card 2 carries an id in exactly one dialect: the ELFORM=6 discrete beam's
    card 2f field 3, ``CID``, a *DEFINE_COORDINATE_* reference (IDDOFF). Every
    other card-2 dialect is pure geometry."""
    per_set_title = _title_offset(b)
    raw = b.raw
    idx = 0
    roff = offsets.get("r", 0)
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)      # SECID
        if new is not None:
            raw[idx] = new
        new = _rewrite_neg_ref(raw[idx], 3, roff)               # -QR/IRID
        if new is not None:
            raw[idx] = new
        elform = _geti(f1, 1)
        f2 = _fields(raw[idx + 1], 8, 10) if idx + 1 < len(raw) else []
        kind = _beam_card2_kind(elform, f2[0] if f2 else "")
        if kind == "2f" and idx + 1 < len(raw):
            new = _rewrite_line(raw[idx + 1], [(2, "d")], offsets)   # CID
            if new is not None:
                raw[idx + 1] = new
        idx += 2
        if kind == "2b" and elform == 2:        # card 2b.1 OPTCARD
            nxt = _fields(raw[idx], 2, 10) if idx < len(raw) else []
            if nxt and str(nxt[0]).strip().upper().startswith("OPTCARD"):
                idx += 1
        elif kind == "2c" and elform == 12:     # card 2c.1
            idx += 1
        elif not kind:                          # unknown stride — stop
            break


def _off_section_discrete(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_DISCRETE card set: SECID (IDROFF). The stride is a fixed
    pair of cards per set (Vol I R17 p.41-32)."""
    per_set_title = _title_offset(b)
    raw = b.raw
    idx = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 6, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)
        if new is not None:
            raw[idx] = new
        idx += 2


def _off_integration_beam(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *INTEGRATION_BEAM rule under the header: card 1's IRID shares the
    *SECTION id space (IDROFF), the ICST>0 dimension card carries no id at all,
    and only a real S/T/WF/PID point card carries a *PART reference (IDPOFF) —
    in field 4, not field 3 as on the shell rule."""
    raw = b.raw
    idx = 0
    while idx < len(raw):
        if not raw[idx].strip():
            idx += 1
            continue
        f1 = _fields(raw[idx], 5, 10)
        if _geti(f1, 0) <= 0:
            return
        nip, icst = _geti(f1, 1), _geti(f1, 3)
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)
        if new is not None:
            raw[idx] = new
        idx += 1
        if icst > 0:                    # D1 D2 D3 D4 SREF TREF D5 D6
            idx += 1
        # The two blocks are ADDITIVE: NIP point cards follow whether or not a
        # dimension card did. Skipping them when ICST>0 would read the next
        # rule's card 1 out of the middle of this one.
        for _ in range(max(nip, 0)):
            while idx < len(raw) and not raw[idx].strip():
                idx += 1
            if idx >= len(raw):
                return
            new = _rewrite_line(raw[idx], [(3, "p")], offsets)
            if new is not None:
                raw[idx] = new
            idx += 1


def _off_mat_rigid(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_RIGID: mid → IDMOFF; card-2 CON1 is a *DEFINE_COORDINATE_* system
    id (IDDOFF namespace) when CMO<0 (local constraint frame)."""
    toff = _title_offset(b)
    if toff < len(b.raw) and b.raw[toff].strip():
        new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
        if new is not None:
            b.raw[toff] = new
    i2 = toff + 1
    if i2 < len(b.raw) and b.raw[i2].strip():
        f = _fields(b.raw[i2])
        cmo = to_float(f[0]) if f and str(f[0]).strip() else 0.0
        if cmo < 0.0:
            new = _rewrite_line(b.raw[i2], [(1, "d")], offsets)
            if new is not None:
                b.raw[i2] = new


def _bpm_cards(b: Block, is_box: bool = False):
    """Yield ``(line_index, kind)`` over a *BOUNDARY_PRESCRIBED_MOTION block,
    where *kind* is ``""`` for a card 1, ``"box"`` for the _SET_BOX card and
    ``"cont"`` for the continuation card.

    Per entity the official reader takes card 1 (typeid dof vad lcid sf vid
    death birth), then — only on the _BOX option — ``BOXID TOFFSET LCBCHK``,
    then — only when |DOF| is 9/10/11 or VAD=4 — ``OFFSET1 OFFSET2 LRB NODE1
    NODE2`` (boundary_prescribed_motion*.cfg).

    The empty string for a card 1 keeps ``not kind`` true for it, so callers
    that only care "is this a card 1" read unchanged.

    Cards 2 and 3 are consumed POSITIONALLY: every one of their fields defaults
    (``BOXID`` aside, p.752-753), so an all-blank continuation card is legal
    input, and skipping blanks while looking for it consumed the FOLLOWING
    entity's card 1 instead — which then got the continuation card's id spec
    (NSID un-offset, VAD+IDPOFF, LCID+IDNOFF, the float SF turned into an id).
    A blank card 2/3 carries no id to rewrite, so it is simply not yielded.
    Blank lines are still skipped while hunting for a card 1: an all-default
    card 1 has TYPEID 0 and is not an entity at all.
    """
    raw = b.raw
    i = _title_offset(b)
    n = len(raw)
    while i < n:
        if not raw[i].strip():
            i += 1
            continue
        f = _fields(raw[i])
        has_cont = abs(_geti(f, 1)) in (9, 10, 11) or _geti(f, 2) == 4
        yield i, ""
        i += 1
        if is_box:
            if i < n and raw[i].strip():
                yield i, "box"
            i += 1
        if has_cont:
            if i < n and raw[i].strip():
                yield i, "cont"
            i += 1


def _off_bpm(id_bucket: str, is_box: bool = False):
    """*BOUNDARY_PRESCRIBED_MOTION_{RIGID,RIGID_LOCAL,SET,SET_BOX,NODE}:
    repeated card-1 entries (typeid dof vad lcid sf vid death birth) with two
    conditional extra cards that must NOT receive the card-1 mods.

    * the _BOX card is ``BOXID TOFFSET LCBCHK`` — BOXID is a *DEFINE_BOX
      (IDDOFF, the bucket every other *DEFINE id uses) and LCBCHK a curve;
    * the continuation card's OFFSET1/OFFSET2 are literal coordinates, LRB is a
      rigid-body part and NODE1/NODE2 are nodes.
    """
    c1 = [(0, id_bucket), (3, "f"), (5, "d")]
    cards = {"": c1, "box": [(0, "d"), (2, "f")],
             "cont": [(2, "p"), (3, "n"), (4, "n")]}

    def _fn(b: Block, offsets: Dict[str, int], warn) -> None:
        raw = b.raw
        if _title_offset(b) and "ID" in b.options and raw:
            new = _rewrite_id_header(raw[0], offsets.get("r", 0))
            if new is not None:
                raw[0] = new
        for k, kind in _bpm_cards(b, is_box=is_box):
            new = _rewrite_line(raw[k], cards[kind], offsets)
            if new is not None:
                raw[k] = new
    return _fn


def _off_load_segment(b: Block, offsets: Dict[str, int], warn) -> None:
    """*LOAD_SEGMENT: card 1 = lcid sf at n1..n5; the official reader takes
    the NEXT card as N6 N7 N8 if and only if N5 is set (load_segment.cfg) —
    node fields, not another card 1."""
    raw = b.raw
    start = _title_offset(b)
    if start and "ID" in b.options and raw:
        new = _rewrite_id_header(raw[0], offsets.get("r", 0))
        if new is not None:
            raw[0] = new
    c1 = [(0, "f")] + [(i, "n") for i in range(3, 8)]
    c2 = [(0, "n"), (1, "n"), (2, "n")]
    expect2 = False
    for k in range(start, len(raw)):
        if not raw[k].strip():
            continue
        cont = expect2
        expect2 = False if cont else (_geti(_fields(raw[k]), 7) != 0)
        new = _rewrite_line(raw[k], c2 if cont else c1, offsets)
        if new is not None:
            raw[k] = new


def _off_rigidwall_geometric(b: Block, offsets: Dict[str, int], warn) -> None:
    """*RIGIDWALL_GEOMETRIC_<shape>[_MOTION][_DISPLAY][_ID].

    Card 1 carries NSID/NSIDEX (IDSOFF) and BOXID (IDDOFF), Card 2 is pure
    geometry, and the shape card is geometry too — but the optional _MOTION
    card's LCID is a curve id (IDFOFF) whose CARD INDEX depends on the shape
    and, for a cylinder, on NSEGS (each of the NSEGS "VL HEIGHT" sub-cards sits
    between the shape card and the MOTION card). A fixed ``cards`` map cannot
    express that, so the position is walked here. The _DISPLAY card's PID is a
    *PART id, offset with IDPOFF.
    """
    raw = b.raw
    # "The order of the OPTIONS is arbitrary" (Manual p. 40-4), so _ID may sit
    # in a non-final position, where the keyword parser leaves it in the
    # keyword instead of in block.options (mirrors handlers._rwall_has_id).
    has_id = "ID" in b.options or "_ID_" in f"_{b.keyword}_"
    start = 1 if has_id else _title_offset(b)
    if has_id and raw:
        new = _rewrite_id_header(raw[0], offsets.get("p", 0))
        if new is not None:
            raw[0] = new
    if start < len(raw):
        new = _rewrite_line(raw[start], [(0, "s"), (1, "s"), (2, "d")], offsets)
        if new is not None:
            raw[start] = new
    # start+1 = geometry card, start+2 = shape card (+ NSEGS sub-cards)
    idx = start + 3
    if "_CYLINDER" in b.keyword and start + 2 < len(raw):
        f3 = [x.strip() for x in _fields(raw[start + 2], 8, 10)]
        idx += to_int(f3[2]) if len(f3) > 2 and f3[2] else 0
    if "_MOTION" in b.keyword:
        if idx < len(raw):
            new = _rewrite_line(raw[idx], [(0, "f")], offsets)
            if new is not None:
                raw[idx] = new
        idx += 1
    if "_DISPLAY" in b.keyword and idx < len(raw):
        new = _rewrite_line(raw[idx], [(0, "p")], offsets)
        if new is not None:
            raw[idx] = new


def _off_hex_spotweld_assembly(b: Block, offsets: Dict[str, int], warn) -> None:
    """*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N][_TITLE]: an optional title/heading
    card, then ID_SW on its OWN card, then EID1..EIDn.

    ID_SW lives in its own weld-id namespace with no *INCLUDE_TRANSFORM bucket,
    so it is left alone; every field after it is an *ELEMENT_SOLID id and moves
    with IDEOFF. Getting this wrong is not a dangling reference in the .rad —
    the writer finds no matching solid, drops the whole cluster, and the hex
    weld silently loses its failure criterion for the rest of the run (see
    _make_hex_spotweld_clusters' "none of its element id(s) resolved" warning).
    """
    start = _title_offset(b) + 1          # title (if any) + the ID_SW card
    for k in range(start, len(b.raw)):
        if not b.raw[k].strip():
            continue
        new = _rewrite_line(b.raw[k], [(ALL, "e")], offsets)
        if new is not None:
            b.raw[k] = new


def _off_ale_multi_material_group(b: Block, offsets: Dict[str, int], warn) -> None:
    for k, line in enumerate(b.raw):
        if not line.strip():
            continue
        f = _fields(line)
        idtype = _geti(f, 1)                 # 0 = part set, 1 = part
        new = _rewrite_line(line, [(0, "p" if idtype == 1 else "s")], offsets)
        if new is not None:
            b.raw[k] = new


def _off_constrained_lagrange_in_solid(b: Block, offsets: Dict[str, int],
                                       warn) -> None:
    if not b.raw or not b.raw[0].strip():
        return
    f = _fields(b.raw[0])
    sstyp, mstyp = _geti(f, 2), _geti(f, 3)
    # CTYPE-side STYPEs: 0 = part set, 1 = part, 2 = node set
    def bucket(t: int) -> str:
        return "p" if t == 1 else "s"
    new = _rewrite_line(b.raw[0], [(0, bucket(sstyp)), (1, bucket(mstyp))],
                        offsets)
    if new is not None:
        b.raw[0] = new


def _off_inivel_generation(b: Block, offsets: Dict[str, int], warn) -> None:
    start = 1 if "ID" in b.options else 0
    if start and b.raw:
        new = _rewrite_id_header(b.raw[0], offsets.get("r", 0))
        if new is not None:
            b.raw[0] = new
    if start >= len(b.raw):
        return
    f = _fields(b.raw[start])
    styp = _geti(f, 1)                       # 1 part set, 2 part, 3 node set
    mods: List[Tuple[int, str]] = [(7, "d")]
    if styp == 2:
        mods.append((0, "p"))
    elif styp in (1, 3):
        mods.append((0, "s"))
    new = _rewrite_line(b.raw[start], mods, offsets)
    if new is not None:
        b.raw[start] = new
    if start + 1 < len(b.raw) and b.raw[start + 1].strip():
        f2 = _fields(b.raw[start + 1])
        if len(f2) > 3 and -999.5 < to_float(f2[3], 0.0) < -998.5:
            new = _rewrite_line(b.raw[start + 1], [(4, "n"), (5, "n")], offsets)
            if new is not None:
                b.raw[start + 1] = new


def _off_joint_stiffness(b: Block, offsets: Dict[str, int], warn) -> None:
    """*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED / _TRANSLATIONAL.

    Card 1  JSID PIDA PIDB CIDA CIDB JID [RPS]  — parts, coordinate systems and
            the joint id it points at.
    Card 2  six load-curve ids.
    Card 3  ES/FM pairs — NOT rewritten. The ES fields are float stiffnesses, so
            a static ("f") field map would run to_int over ESPH=1000.0 and turn
            it into 1000+IDFOFF, silently changing the physics. The FM/FF fields
            are ids only when NEGATIVE (-FM is the yield-moment curve id), an
            encoding _rewrite_line deliberately leaves alone. A negative one is
            therefore warned about rather than guessed at.
    Card 4  stop angles / displacements: pure floats, never offset.
    """
    toff = _title_offset(b)
    if toff and "ID" in b.options and b.raw:
        new = _rewrite_id_header(b.raw[0], offsets.get("r", 0))
        if new is not None:
            b.raw[0] = new
    for ci, mods in ((0, [(0, "r"), (1, "p"), (2, "p"), (3, "d"), (4, "d"),
                          (5, "r")]),
                     (1, [(i, "f") for i in range(6)])):
        idx = toff + ci
        if idx < len(b.raw) and b.raw[idx].strip():
            new = _rewrite_line(b.raw[idx], mods, offsets)
            if new is not None:
                b.raw[idx] = new
    idx = toff + 2
    if offsets.get("f", 0) and idx < len(b.raw) and b.raw[idx].strip():
        f = _fields(b.raw[idx])
        neg = [f[i] for i in (1, 3, 5)
               if len(f) > i and to_float(f[i], 0.0) < 0.0]
        if neg:
            warn(f"*INCLUDE_TRANSFORM: *{b.keyword} has a negative FM/FF field "
                 f"({', '.join(neg)}), which LS-DYNA reads as a load-curve id, "
                 "but IDFOFF is NOT applied to it (the field is a float "
                 "elsewhere on the same card). Check that the curve id still "
                 "resolves in the transformed include.")


def _off_mat_077(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_OGDEN_RUBBER / *MAT_HYPERELASTIC_RUBBER (077_O/077_H): MID →
    IDMOFF; card 2 is conditional on card-1 N — it carries the LCID1/LCID2
    curve ids (fields 4/6) only when N>0. With N=0 the same card positions
    hold MU4/MU6 (077_O) or C20/C30 (077_H) float constants, which a static
    curve-field spec would corrupt."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    f = _fields(b.raw[toff])
    n = int(to_float(f[3], 0.0)) if len(f) > 3 and str(f[3]).strip() else 0
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    i2 = toff + 1
    if n > 0 and i2 < len(b.raw) and b.raw[i2].strip():
        new = _rewrite_line(b.raw[i2], [(3, "f"), (5, "f")], offsets)
        if new is not None:
            b.raw[i2] = new


def _off_mat_006(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_VISCOELASTIC (006): MID → IDMOFF, and each of BULK/G0/GI/BETA
    (card 1 fields 3-6) is a SCALAR_OR_OBJECT whose NEGATIVE form is the
    negated id of a temperature curve — those move with IDFOFF like any other
    curve reference, which _rewrite_line alone would not do (it deliberately
    touches only positive cells)."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    foff = offsets.get("f", 0)
    for i in (2, 3, 4, 5):
        new = _rewrite_neg_ref(b.raw[toff], i, foff)
        if new is not None:
            b.raw[toff] = new


def _off_mat_181(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_SIMPLIFIED_RUBBER/FOAM (181): MID → IDMOFF, LC/TBID (card 2
    field 4) → IDFOFF, and LCUNLD → IDFOFF on the OPTIONAL unloading card,
    whose index depends on the keyword: the _WITH_FAILURE option inserts a
    whole K/GAMA1/GAMA2/EH card between card 2 and it. A static spec would
    rewrite that failure card's K value as a curve id."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    i2 = toff + 1
    if i2 < len(b.raw):
        new = _rewrite_line(b.raw[i2], [(3, "f")], offsets)
        if new is not None:
            b.raw[i2] = new
    iu = toff + (3 if "_WITH_FAILURE" in b.keyword else 2)
    if iu < len(b.raw) and b.raw[iu].strip():
        new = _rewrite_line(b.raw[iu], [(0, "f")], offsets)
        if new is not None:
            b.raw[iu] = new


#: ``*AIRBAG_<MODEL>`` → the card-3 (and card-4) cells that are CURVE ids, by
#: model. Card 1 is shared and handled separately; the two card-3 cells that
#: hold a curve id only when NEGATIVE (SPV's CN, SIMPLE_AIRBAG_MODEL's MU and
#: AREA) are listed apart, because ``_rewrite_line`` only touches positive
#: cells and a sign-preserving rewriter is needed for them.
_AIRBAG_CURVE_CELLS = {
    "AIRBAG_SIMPLE_PRESSURE_VOLUME": ([(2, "f"), (3, "f")], [0], []),
    "AIRBAG_SIMPLE_AIRBAG_MODEL":    ([(3, "f")], [4, 5], [(0, "f")]),
    "AIRBAG_ADIABATIC_GAS_MODEL":    ([(1, "f")], [], []),
    "AIRBAG_LOAD_CURVE":             ([(1, "f")], [], []),
    "AIRBAG_LINEAR_FLUID":           ([(i, "f") for i in range(2, 8)], [],
                                      [(1, "f")]),
    # HYBRID's card 3 is the ambient state and holds no id at all; its card 4
    # (LCC23/LCA23/LCP23/LCAP23) and card 5 (LCEFR/LCIDM0) and its NGAS gas
    # pairs are walked by _off_airbag_hybrid, because their INDEX moves with
    # NGAS and their count is not knowable from a static cell list.
    "AIRBAG_HYBRID":                 ([], [], []),
    # PARTICLE shares nothing with the other six — different card 1, no RBID
    # walk — so it has its own spec entirely.
    "AIRBAG_PARTICLE":               ([], [], []),
}


def _off_airbag(b: Block, offsets: Dict[str, int], warn) -> None:
    """``*AIRBAG_<MODEL>``: SID → IDSOFF, RBID → IDPOFF, every curve slot →
    IDFOFF, and the ``_ID`` header's ABID → IDROFF.

    Card 3's INDEX moves with RBID — ``> 0`` inserts an ``N`` card plus
    ``ceil(N/5)`` constant cards, ``< 0`` inserts three sensor cards (Vol I R16
    p.3-4) — so a declarative spec would rewrite a sensor's acceleration
    magnitude as a curve id on any RBID != 0 deck. Same walk the handler uses,
    imported from it so the two cannot drift.

    **Card-1 SID is mapped to IDSOFF unconditionally**, because that is what
    SIDTYP says it is — a *SET_SEGMENT or a *SET_PART id, both of them SET
    ids. ``writer/monvol.py::_airbag_surface_eids`` additionally accepts a bare
    *PART id there as a fallback, and such a reference moves to the wrong id
    under an *INCLUDE_TRANSFORM whose IDSOFF and IDPOFF differ. It is
    diagnosed rather than silent — the writer then reports "names a *SET_PART
    that this deck does not define" — and offsetting by IDPOFF instead would
    break the documented case, so the fallback is left un-offset.
    """
    from .handlers import (_AIRBAG_MODELS, _airbag_base_keyword,
                           _airbag_prelude)
    raw = b.raw
    base = _airbag_base_keyword(b.keyword)
    if base == "AIRBAG_PARTICLE":
        _off_airbag_particle(b, offsets, warn)
        return
    toff = _title_offset(b)
    if toff and "ID" in b.options and raw:
        new = _rewrite_id_header(raw[0], offsets.get("r", 0))
        if new is not None:
            raw[0] = new
    if toff >= len(raw) or not raw[toff].strip():
        return
    new = _rewrite_line(raw[toff], [(0, "s"), (2, "p")], offsets)
    if new is not None:
        raw[toff] = new
    # The legacy trailing "_<digits>" spelling is the base model's card stack
    # (handlers._airbag_base_keyword), so it keys the same cell map.
    model = _AIRBAG_MODELS.get(base)
    if model is None:
        return
    _f1, i3 = _airbag_prelude(raw, toff)
    if base == "AIRBAG_HYBRID":
        _off_airbag_hybrid(b, raw, i3, offsets)
        return
    cells, neg_cells, card4 = _AIRBAG_CURVE_CELLS[base]
    foff = offsets.get("f", 0)
    if i3 < len(raw) and raw[i3].strip():
        if cells:
            new = _rewrite_line(raw[i3], cells, offsets)
            if new is not None:
                raw[i3] = new
        for i in neg_cells:
            new = _rewrite_neg_ref(raw[i3], i, foff)
            if new is not None:
                raw[i3] = new
    if card4 and i3 + 1 < len(raw) and raw[i3 + 1].strip():
        new = _rewrite_line(raw[i3 + 1], card4, offsets)
        if new is not None:
            raw[i3 + 1] = new


def _off_airbag_hybrid(b: Block, raw, i3: int, offsets: Dict[str, int]) -> None:
    """``*AIRBAG_HYBRID`` cards 4, 5 and the NGAS gas pairs.

    Card 3 (ATMOST ATMOSP ATMOSD GC CC HCONV) holds no id — a NEGATIVE HCONV
    is ``|HCONV|`` as a curve id, but the converter drops it rather than
    referencing it, so rewriting it would move an id nothing points at.

    Card 4  ``C23 LCC23 A23 LCA23 CP23 LCP23 AP23 LCAP23`` — four curve cells,
            and ``A23`` is the sign-overloaded one: a NEGATIVE A23 is a *PART
            id when ``LCA23 != -1`` and a *SET_PART id when it is ``-1``. Two
            different buckets on one cell, decided by a neighbouring cell —
            which is why it is walked rather than declared.
    Card 5  ``OPT PVENT NGAS LCEFR LCIDM0 VNTOPT`` — two curve cells, and NGAS
            is the count that positions everything below.
    Card 5.1 (x NGAS) ``LCIDM LCIDT <blank> MW INITM A B C`` — two curve cells
            per gas, at a card index that moves with the stride
            ``_hybrid_gas_stride`` decides. Both are sign-overloaded: a
            negative id means cubic-spline interpolation of ``|id|``.

    The jetting cards below carry ``PSID`` (a *SET_PART) and NODE1/2/3, which
    move with IDSOFF and IDNOFF — and both of those are among the offsets
    ``*INCLUDE_TRANSFORM`` does NOT propagate to Radioss at all
    (``convertincludes.cxx:121-124`` leaves IDSOFF/IDFOFF/IDDOFF commented
    out), so they are rewritten here for the same reason every other set and
    curve cell is: k2rad applies the offsets in the .k, before conversion.
    """
    from .handlers import _card, _hybrid_gas_stride
    foff = offsets.get("f", 0)
    if i3 + 1 < len(raw) and raw[i3 + 1].strip():
        new = _rewrite_line(raw[i3 + 1],
                            [(1, "f"), (3, "f"), (5, "f"), (7, "f")], offsets)
        if new is not None:
            raw[i3 + 1] = new
        # A23 < 0 names a *PART (LCA23 != -1) or a *SET_PART (LCA23 == -1).
        lca23 = to_int(_card(raw, i3 + 1, fixed=True, n=8, w=10)[3])
        _rewrite_neg_cell(raw, i3 + 1, 2,
                          offsets.get("s" if lca23 == -1 else "p", 0))
    ngas = 0
    if i3 + 2 < len(raw) and raw[i3 + 2].strip():
        f5 = _card(raw, i3 + 2, fixed=True, n=8, w=10)
        ngas = to_int(f5[2]) if len(f5) > 2 else 0
        new = _rewrite_line(raw[i3 + 2], [(3, "f"), (4, "f")], offsets)
        if new is not None:
            raw[i3 + 2] = new
    i = i3 + 3
    stride = _hybrid_gas_stride(raw, i, ngas)
    for _k in range(max(0, ngas)):
        if i < len(raw) and raw[i].strip():
            new = _rewrite_line(raw[i], [(0, "f"), (1, "f")], offsets)
            if new is not None:
                raw[i] = new
            for cell in (0, 1):
                _rewrite_neg_cell(raw, i, cell, foff)
        i += stride
    if "_JETTING" in b.keyword and i + 1 < len(raw) and raw[i + 1].strip():
        # Card 7: XSJFP YSJFP ZSJFP PSID IDUM NODE1 NODE2 NODE3 — read by the
        # MANUAL, not by the reader cfg, which omits IDUM (see the handler).
        new = _rewrite_line(raw[i + 1],
                            [(3, "s"), (5, "n"), (6, "n"), (7, "n")], offsets)
        if new is not None:
            raw[i + 1] = new


def _off_airbag_particle(b: Block, offsets: Dict[str, int], warn) -> None:
    """``*AIRBAG_PARTICLE``: SD1/SD2 → IDSOFF or IDPOFF by their own type
    flags, the NVENT vent rows' SID3 the same way, every inflator curve →
    IDFOFF, and the NORIF nozzles' NIDi → IDEOFF or IDNOFF by VDi.

    Every one of those buckets is chosen by a NEIGHBOURING cell, which is what
    makes this a walk and not a table:

      ``SD1``  is a *PART when ``STYPE1 == 0`` and a *SET_PART otherwise —
               the opposite convention from the ``SIDTYP`` on card 1 of the
               other six models, where 0 is a *SET_SEGMENT.
      ``SID3`` on each vent row, the same way, off ``STYPE3``.
      ``NIDi`` is a SHELL ELEMENT id when ``VDi`` is -1/-2/-3/-4 and a NODE id
               otherwise — the one cell in the whole airbag family whose
               ENTITY TYPE, not just its namespace, depends on another cell.

    The card walk itself is the handler's, imported so the two cannot drift.
    """
    from .handlers import (_card, _airbag_particle_id_row,
                           _read_airbag_particle_indices)
    raw = b.raw
    # On an _MPP deck the SX/SY/SZ card comes FIRST and the _ID card second
    # (Vol I R17 p.3-94 Card Summary), so the header is not always raw[0].
    hdr = _airbag_particle_id_row(b)
    if "ID" in b.options and len(raw) > hdr:
        new = _rewrite_id_header(raw[hdr], offsets.get("r", 0))
        if new is not None:
            raw[hdr] = new
    i1, vent_rows, gas_rows, orif_rows, partial = \
        _read_airbag_particle_indices(b, raw)
    if partial:
        warn(f"*{b.keyword}: the card stack could not be walked past card 1 "
             "(a STYPE2 = 2 block repeats once per part of the SD2 set, a "
             "count that only exists after the *SET_PART is resolved). Card "
             "1's SID1/SID2 ARE offset; the vent, gas and orifice rows below "
             "it are NOT — check their set, curve and element ids by hand "
             "against this *INCLUDE_TRANSFORM's IDSOFF / IDFOFF / IDEOFF.")
    if i1 < len(raw) and raw[i1].strip():
        f1 = _card(raw, i1, fixed=True, n=8, w=10)
        stype1 = to_int(f1[1]) if len(f1) > 1 else 0
        stype2 = to_int(f1[3]) if len(f1) > 3 else 0
        new = _rewrite_line(
            raw[i1],
            [(0, "s" if stype1 else "p"), (2, "s" if stype2 else "p")],
            offsets)
        if new is not None:
            raw[i1] = new
    for r in vent_rows:
        if r < len(raw) and raw[r].strip():
            fv = _card(raw, r, fixed=True, n=8, w=10)
            stype3 = to_int(fv[1]) if len(fv) > 1 else 0
            new = _rewrite_line(
                raw[r], [(0, "s" if stype3 else "p"), (3, "f"), (4, "f")],
                offsets)
            if new is not None:
                raw[r] = new
    for r in gas_rows:
        if r < len(raw) and raw[r].strip():
            new = _rewrite_line(raw[r], [(0, "f"), (1, "f")], offsets)
            if new is not None:
                raw[r] = new
    for r in orif_rows:
        if r < len(raw) and raw[r].strip():
            fo = _card(raw, r, fixed=True, n=8, w=10)
            vdi = to_float(fo[2]) if len(fo) > 2 else 0.0
            # VDi -1/-2/-3/-4 -> NIDi is a SHELL ELEMENT; otherwise a NODE.
            new = _rewrite_line(
                raw[r], [(0, "e" if vdi < 0.0 else "n")], offsets)
            if new is not None:
                raw[r] = new


def _off_airbag_interaction(b: Block, offsets: Dict[str, int], warn) -> None:
    """``*AIRBAG_INTERACTION``: ``AB1``/``AB2`` → IDROFF (they are *AIRBAG
    ids, the same bucket the ``_ID`` header's ABID takes), ``PID`` → IDPOFF
    and ``LCID`` → IDFOFF.

    ``AREA`` and ``SF`` are sign-overloaded — a negative one is ``|value|`` as
    a curve id — so both get the sign-preserving rewriter as well.
    """
    raw = b.raw
    off = _title_offset(b)
    if "ID" in b.options and raw:
        new = _rewrite_id_header(raw[0], offsets.get("r", 0))
        if new is not None:
            raw[0] = new
    if off >= len(raw) or not raw[off].strip():
        return
    new = _rewrite_line(raw[off],
                        [(0, "r"), (1, "r"), (4, "p"), (5, "f")], offsets)
    if new is not None:
        raw[off] = new
    foff = offsets.get("f", 0)
    for cell in (2, 3):                       # AREA < 0, SF < 0 are curve ids
        _rewrite_neg_cell(raw, off, cell, foff)


def _rewrite_neg_cell(raw, idx: int, cell: int, off: int) -> None:
    """``_rewrite_neg_ref`` applied in place, for the cells whose NEGATIVE
    value is an id in some other namespace."""
    if not off or idx >= len(raw):
        return
    new = _rewrite_neg_ref(raw[idx], cell, off)
    if new is not None:
        raw[idx] = new


def _off_airbag_ref_geometry(b: Block, offsets: Dict[str, int], warn) -> None:
    """``*AIRBAG_REFERENCE_GEOMETRY[...]``: the node ids of the coordinate rows
    → IDNOFF, and the ``_ID`` card's NIDO with them.

    The rows are ``NID(I10) X(E20) Y(E20) Z(E20)`` — TWENTY-column coordinates,
    not the sixteen of *NODE — so ``data_w`` cannot be the header's 10 and the
    walk is written out rather than declared. The card index of the first row
    moves with the options (``_ID`` adds one card, ``_BIRTH`` another), the
    same shift the handler walks.

    The COORDINATES themselves are literal geometry a TRANID would have to
    move, which this converter does not do — hence the entry in
    ``_POINT_BEARING`` beside *INITIAL_FOAM_REFERENCE_GEOMETRY.
    """
    kw = b.keyword
    raw = b.raw
    i = 0
    if "_ID" in kw or "ID" in b.options:
        if i < len(raw):
            new = _rewrite_line(raw[i], [(4, "n")], offsets)
            if new is not None:
                raw[i] = new
        i += 1
    if "_BIRTH" in kw:
        i += 1
    noff = offsets.get("n", 0)
    if not noff:
        return
    for idx in range(i, len(raw)):
        line = raw[idx]
        if not line.strip():
            continue
        nid = to_int(line[0:10])
        if nid > 0:
            raw[idx] = f"{nid + noff:>10}" + line[10:]


def _off_airbag_shell_ref_geometry(b: Block, offsets: Dict[str, int],
                                   warn) -> None:
    """``*AIRBAG_SHELL_REFERENCE_GEOMETRY[...]``: ``EID PID N1 N2 N3 N4``, all
    I10 — element, part and four nodes, each to its own bucket."""
    raw = b.raw
    i = 1 if ("_ID" in b.keyword or "ID" in b.options) else 0
    if i and raw:
        new = _rewrite_line(raw[0], [(4, "n")], offsets)
        if new is not None:
            raw[0] = new
    mods = [(0, "e"), (1, "p")] + [(k, "n") for k in range(2, 6)]
    for idx in range(i, len(raw)):
        if raw[idx].strip():
            new = _rewrite_line(raw[idx], mods, offsets)
            if new is not None:
                raw[idx] = new


def _off_mat_fabric(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_FABRIC (034): MID → IDMOFF, and the six card-7 stress/strain curve
    ids (LCA LCB LCAB LCUA LCUB LCUAB) → IDFOFF.

    Card 7's INDEX is conditional twice over: it exists only when
    ``FORM in {4, 14, -14, 24}`` (card-3 field 5) and it sits one line lower
    when the FVOPT<0 leakage card 4 is present (card-3 field 6). A static spec
    would rewrite card 5's A0REF/A1/A2/A3 as curve ids on a FORM=0 deck and
    move a leakage constant on an FVOPT<0 one — the ``_WITH_FAILURE`` hazard
    ``_off_mat_181`` records, twice.

    Card 3 is read with ``_fields`` and NOT with the bare ``parse_fixed``
    slicer (#119). On a comma-separated or narrow *MAT_FABRIC the 10-char
    slicer reads FORM out of the wrong columns, ``form`` comes back 0 and the
    six card-7 curve ids are silently left UN-offset — while the MID on the
    same block IS offset (``_rewrite_line`` goes through ``_split_card``,
    which handles commas) and so are the ``*DEFINE_CURVE`` ids in the same
    include, leaving the material pointing at the parent deck's curve numbers.

    The FORM set comes from ``state.FABRIC_CURVE_FORMS``, the one the parser
    and ``writer.fabric._fabric_law`` both use, so the two cannot drift (#116).
    """
    toff = _title_offset(b)
    raw = b.raw
    if toff >= len(raw) or not raw[toff].strip():
        return
    new = _rewrite_line(raw[toff], [(0, "m")], offsets)
    if new is not None:
        raw[toff] = new
    i3 = toff + 2
    if i3 >= len(raw):
        return
    f3 = _fields(raw[i3], 8, 10)
    form = int(round(to_float(f3[5]))) if len(f3) > 5 else 0
    if form not in FABRIC_CURVE_FORMS:
        return
    fvopt = to_float(f3[6]) if len(f3) > 6 else 0.0
    i7 = i3 + (4 if fvopt < 0.0 else 3)
    if i7 < len(raw) and raw[i7].strip():
        new = _rewrite_line(raw[i7], [(i, "f") for i in range(6)], offsets)
        if new is not None:
            raw[i7] = new


def _off_mat_138(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_COHESIVE_MIXED_MODE (138): MID → IDMOFF; GIC/GIIC (card 1 fields
    7/8) and T/S (card 2 fields 2/3) are floats whose NEGATIVE form is the
    negated id of an element-size curve — moved with IDFOFF via the
    sign-preserving rewriter (positive values are physics, never touched)."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    foff = offsets.get("f", 0)
    for i in (6, 7):
        new = _rewrite_neg_ref(b.raw[toff], i, foff)
        if new is not None:
            b.raw[toff] = new
    i2 = toff + 1
    if i2 < len(b.raw) and b.raw[i2].strip():
        for i in (1, 2):
            new = _rewrite_neg_ref(b.raw[i2], i, foff)
            if new is not None:
                b.raw[i2] = new


def _off_mat_shape_memory(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_SHAPE_MEMORY (*MAT_030): MID → IDMOFF; every curve reference the
    card can carry → IDFOFF (``VALUE(FUNCT)`` in mat_030.cfg, so IDFOFF per
    ``include_transform.cfg:64-78``).

    Two sign conventions on one keyword:
      * card 1 fields 5/6 (``LCSS``/``LCSSC``) are ordinary positive ids — but
        LCSS may be NEGATIVE to say "the SIG_* cells are plastic-strain
        curves", so both signs are walked;
      * card 2 fields 1-4 (``SIG_ASS``/``SIG_ASF``/``SIG_SAS``/``SIG_SAF``) are
        ``SCALAR_OR_OBJECT``: a POSITIVE value is a stress (physics — never
        touch it) and a NEGATIVE one is a curve id. Only the negative form is
        rewritten, sign preserved — the *SECTION_SHELL QR/IRID pattern.

    Card 3 is the R7.1 ``FREE_CARD(optionalCards, "%10d%10d", LCID_AS,
    LCID_SA)``. It is claimed by RAW ROW INDEX like the handler does, never by
    "the next non-blank row": an all-blank optional card is legal LS-DYNA, and a
    content scan would walk past it into the following keyword (the #109/#117/
    #119 trap) — here that would offset another entity's card-1 ids as if they
    were curve references.
    """
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m"), (4, "f"), (5, "f")], offsets)
    if new is not None:
        b.raw[toff] = new
    foff = offsets.get("f", 0)
    for i in (4, 5):                        # LCSS / LCSSC stated negative
        new = _rewrite_neg_ref(b.raw[toff], i, foff)
        if new is not None:
            b.raw[toff] = new
    i2 = toff + 1
    if i2 < len(b.raw) and b.raw[i2].strip():
        for i in (0, 1, 2, 3):              # SIG_ASS/ASF/SAS/SAF, curve form
            new = _rewrite_neg_ref(b.raw[i2], i, foff)
            if new is not None:
                b.raw[i2] = new
    i3 = toff + 2
    if i3 < len(b.raw) and b.raw[i3].strip():
        new = _rewrite_line(b.raw[i3], [(0, "f"), (1, "f")], offsets)
        if new is not None:
            b.raw[i3] = new


def _off_mat_add_thermal_expansion(b: Block, offsets: Dict[str, int],
                                   warn) -> None:
    """*MAT_ADD_THERMAL_EXPANSION, one card per record, repeating.

    Field 0 lives in TWO id namespaces by SIGN (Vol II R17 p.2-146): ``GT.0``
    is a PART id → IDPOFF, ``LT.0`` makes ``|PID|`` a MATERIAL id → IDMOFF.
    ``_rewrite_line`` never touches a negative cell, so the LT.0 form needs the
    ``_rewrite_neg_ref`` treatment — without it the include's materials all move
    by IDMOFF while this reference stays on the parent deck's numbering and the
    writer drops the card as "names a material no *PART uses".
    ``LCID``/``LCIDY``/``LCIDZ`` (fields 1/3/5) are curves → IDFOFF.
    """
    poff, moff = offsets.get("p", 0), offsets.get("m", 0)
    for i in range(_title_offset(b), len(b.raw)):
        line = b.raw[i]
        if not line.strip():
            continue
        new = _rewrite_line(line, [(0, "p"), (1, "f"), (3, "f"), (5, "f")],
                            offsets) if poff or offsets.get("f", 0) else None
        if new is not None:
            b.raw[i] = new
        new = _rewrite_neg_ref(b.raw[i], 0, moff)
        if new is not None:
            b.raw[i] = new


def _off_load_thermal_sets(b: Block, offsets: Dict[str, int], warn) -> None:
    """*LOAD_THERMAL_{CONSTANT,VARIABLE}: repeating TWO-CARD sets.

    *"Card Sets. Include as many sets consisting of the following two cards as
    desired"* (Vol I R17 pp.33-166/33-179). Walked in RAW PAIRS for the same
    reason the handler is: card 1 may be entirely blank (NSID defaults to all
    nodes), so a per-record "next non-blank row" walk would offset the wrong
    cells from the second set on.

    Card 1 ``NSID NSIDEX BOXID`` → IDSOFF, IDSOFF, IDDOFF.
    Card 2 of _VARIABLE ``TS TB LCID TSE TBE LCIDE LCIDR LCIDEDR``: the four
    curve cells → IDFOFF. _CONSTANT's card 2 (``T TE``) carries no id.
    """
    variable = "VARIABLE" in b.keyword
    i = _title_offset(b)
    while i + 1 < len(b.raw):
        if not b.raw[i].strip() and not b.raw[i + 1].strip():
            break
        new = _rewrite_line(b.raw[i], [(0, "s"), (1, "s"), (2, "d")], offsets)
        if new is not None:
            b.raw[i] = new
        if variable:
            new = _rewrite_line(b.raw[i + 1],
                                [(2, "f"), (5, "f"), (6, "f"), (7, "f")],
                                offsets)
            if new is not None:
                b.raw[i + 1] = new
        i += 2


def _off_boundary_thermal_bc(b: Block, offsets: Dict[str, int], warn) -> None:
    """*BOUNDARY_{FLUX,CONVECTION,RADIATION}_{SEGMENT,SET}: repeating TWO-CARD
    sets, walked in RAW PAIRS exactly as the handler walks them.

    Card 1 of a ``_SET``   : ``SSID`` → IDSOFF, and the PART-SET ``PSEROD`` →
                             IDSOFF too. RADIATION puts ``PSEROD`` in field 7
                             (``SSID TYPE _ _ _ _ PSEROD``, Vol I R17 p.5-122)
                             where the other two put it in field 2.
    Card 1 of a ``_SEGMENT``: ``N1..N4`` → IDNOFF. (RADIATION's field 5 is
                             ``TYPE``, a flag, and is left alone.)
    Card 2                 : the curve cells → IDFOFF, SIGN-PRESERVING — all
                             three keywords give the first cell an ``LT.0``
                             meaning (``|LCID|`` is a curve of TEMPERATURE
                             rather than of time), so ``_rewrite_line``, which
                             never touches a negative cell, is not enough on
                             its own.
                             FLUX: ``LCID`` (field 0).
                             CONVECTION: ``HLCID`` (0), ``TLCID`` (2).
                             RADIATION: ``FLCID`` (0), ``TLCID`` (2).

    ``*BOUNDARY_FLUX``'s optional card 3 stack (``ceil(NHISV/8)`` rows of
    history-variable INITIAL VALUES) carries no id and is strided over, not
    rewritten — the same raw-contiguity stride the handler uses, so a deck with
    history variables does not shift the walk.
    """
    kw = b.keyword
    is_set = kw.endswith("_SET")
    is_flux = "FLUX" in kw
    is_radiation = "RADIATION" in kw
    foff = offsets.get("f", 0)
    if is_set:
        c1 = [(0, "s"), (6, "s")] if is_radiation else [(0, "s"), (1, "s")]
    else:
        c1 = [(0, "n"), (1, "n"), (2, "n"), (3, "n")]
    c2 = [(0, "f")] if is_flux else [(0, "f"), (2, "f")]
    i = _title_offset(b)
    while i + 1 < len(b.raw):
        if not b.raw[i].strip() and not b.raw[i + 1].strip():
            break
        new = _rewrite_line(b.raw[i], c1, offsets)
        if new is not None:
            b.raw[i] = new
        new = _rewrite_line(b.raw[i + 1], c2, offsets)
        if new is not None:
            b.raw[i + 1] = new
        for cell, _bucket in c2:
            new = _rewrite_neg_ref(b.raw[i + 1], cell, foff)
            if new is not None:
                b.raw[i + 1] = new
        step = 2
        if is_flux:
            step += _nhisv_rows(_geti(_fields(b.raw[i + 1]), 6))
        i += step


def _nhisv_rows(nhisv: int) -> int:
    """``ceil(NHISV/8)`` extra card-3 rows, 0 when the card states none."""
    return (nhisv + 7) // 8 if nhisv > 0 else 0


def _off_mat_thermal_td(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_THERMAL_ISOTROPIC_TD / _TD_LC: ``TMID`` → IDMOFF and the curve
    cells → IDFOFF, sign-preserving.

    Card 1 is ``TMID TRO TGRLC TGMULT TLAT HLAT`` on both spellings.
    ``TGRLC`` lives in two id namespaces by SIGN (``GT.0`` a curve of TIME,
    ``LT.0`` a curve of TEMPERATURE — Vol II R17 p.3-7), so it needs the
    ``_rewrite_neg_ref`` treatment as well as the plain rewrite.

    ``_TD_LC``'s card 2 is ``HCLC TCLC HCHSV TCHSV TGHSV``: the first two are
    curve (or, with a non-zero ``*HSV``, table) ids → IDFOFF; the three
    ``*HSV`` cells select a mechanical HISTORY VARIABLE by index and are not
    ids of any class. ``_TD``'s cards 2-4 are pure data (T1..T8, C1..C8,
    K1..K8) and are left alone.
    """
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m"), (2, "f")], offsets)
    if new is not None:
        b.raw[toff] = new
    new = _rewrite_neg_ref(b.raw[toff], 2, offsets.get("f", 0))
    if new is not None:
        b.raw[toff] = new
    if "_TD_LC" in b.keyword or b.keyword.endswith("MAT_T10"):
        i2 = toff + 1
        if i2 < len(b.raw) and b.raw[i2].strip():
            new = _rewrite_line(b.raw[i2], [(0, "f"), (1, "f")], offsets)
            if new is not None:
                b.raw[i2] = new


def _off_mat_thermal_ortho(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_THERMAL_ORTHOTROPIC: ``TMID`` → IDMOFF, ``TGRLC`` → IDFOFF
    (sign-preserving).

    Card 1 is ``TMID TRO TGRLC TGMULT AOPT TLAT HLAT`` — note ``AOPT`` sits in
    field 5 where the isotropic card has ``TLAT``, and it is a FLAG, not an id.
    Cards 2-4 (``HC K1 K2 K3`` / ``XP YP ZP A1 A2 A3`` / ``D1 D2 D3``) are pure
    geometry and material data.
    """
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m"), (2, "f")], offsets)
    if new is not None:
        b.raw[toff] = new
    new = _rewrite_neg_ref(b.raw[toff], 2, offsets.get("f", 0))
    if new is not None:
        b.raw[toff] = new


def _off_mat_muscle(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_MUSCLE (*MAT_156): MID → IDMOFF; ``ALM SFR SVS SVR SSP`` (card 2
    fields 1-5) are ``SCALAR_OR_FUNCTION`` — a NEGATIVE value is a curve (or,
    for SSP, a table) id, a positive one is physics. Only the negative form is
    rewritten, sign preserved."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    i2 = toff + 1
    if i2 >= len(b.raw) or not b.raw[i2].strip():
        return
    foff = offsets.get("f", 0)
    for i in (0, 1, 2, 3, 4):
        new = _rewrite_neg_ref(b.raw[i2], i, foff)
        if new is not None:
            b.raw[i2] = new


def _off_mat_spring_muscle(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_SPRING_MUSCLE (*MAT_S15): MID → IDMOFF; ``SV A TL TV`` (card 1
    fields 4/5/7/8) and ``FPE`` (card 2 field 1) are ``SCALAR_OR_OBJECT``
    ``VALUE(CURVE)`` cells — negative = curve id → IDFOFF, sign preserved."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    foff = offsets.get("f", 0)
    for i in (3, 4, 6, 7):
        new = _rewrite_neg_ref(b.raw[toff], i, foff)
        if new is not None:
            b.raw[toff] = new
    i2 = toff + 1
    if i2 < len(b.raw) and b.raw[i2].strip():
        new = _rewrite_neg_ref(b.raw[i2], 0, foff)
        if new is not None:
            b.raw[i2] = new


def _off_mat_169(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_ARUP_ADHESIVE (169): MID → IDMOFF; TENMAX/GCTEN/SHRMAX/GCSHR
    (card 1 fields 5-8), SHRP (card 2 field 3) and SDFAC/SGFAC (card 5 fields
    1/2) all accept a NEGATIVE value = function id (R9.0+). Card 5's INDEX is
    conditional — it exists only when EDOT2 != 0 and shifts down 2 when the
    EXTRA edge cards (EXTRA 1|3) are present — so a static spec cannot hold
    it."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    foff = offsets.get("f", 0)
    for i in (4, 5, 6, 7):
        new = _rewrite_neg_ref(b.raw[toff], i, foff)
        if new is not None:
            b.raw[toff] = new
    i2 = toff + 1
    if i2 >= len(b.raw) or not b.raw[i2].strip():
        return
    new = _rewrite_neg_ref(b.raw[i2], 2, foff)
    if new is not None:
        b.raw[i2] = new
    f2 = _fields(b.raw[i2])
    extra = int(to_float(f2[7], 0.0)) if len(f2) > 7 and str(f2[7]).strip() \
        else 0
    edot2 = to_float(f2[5], 0.0) if len(f2) > 5 and str(f2[5]).strip() else 0.0
    if edot2 == 0.0:
        return
    i5 = i2 + 1 + (2 if extra in (1, 3) else 0)
    if i5 < len(b.raw) and b.raw[i5].strip():
        for i in (0, 1):
            new = _rewrite_neg_ref(b.raw[i5], i, foff)
            if new is not None:
                b.raw[i5] = new


def _off_mat_add_damage_diem(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_ADD_DAMAGE_DIEM: MID → IDMOFF; per criterion i (NDIEMC pairs) the
    initiation curve P1 (card 2 field 2) and the regularization curve P5
    (field 6) are positive ids → IDFOFF, Q1 (card 3 field 3) is a table id
    only when NEGATIVE, and Q4 (field 6) is |id| under either sign (its sign
    selects the table's second input, not id-ness)."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff], [(0, "m")], offsets)
    if new is not None:
        b.raw[toff] = new
    f1 = _fields(b.raw[toff])
    ndiemc = int(to_float(f1[1], 0.0)) if len(f1) > 1 and str(f1[1]).strip() \
        else 0
    foff = offsets.get("f", 0)
    for i in range(max(ndiemc, 0)):
        i2 = toff + 1 + 2 * i
        i3 = toff + 2 + 2 * i
        if i2 < len(b.raw) and b.raw[i2].strip():
            new = _rewrite_line(b.raw[i2], [(1, "f"), (5, "f")], offsets)
            if new is not None:
                b.raw[i2] = new
        if i3 < len(b.raw) and b.raw[i3].strip():
            new = _rewrite_line(b.raw[i3], [(5, "f")], offsets)
            if new is not None:
                b.raw[i3] = new
            for j in (2, 5):
                new = _rewrite_neg_ref(b.raw[i3], j, foff)
                if new is not None:
                    b.raw[i3] = new


def _off_foam_ref_geometry(b: Block, offsets: Dict[str, int], warn) -> None:
    """*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP]: node ids in the *NODE-format
    table → IDNOFF. The _RAMP variant's first card is NDTRRG (a step count,
    not an id) and must not be rewritten."""
    nodeoff = offsets.get("n", 0)
    if not nodeoff:
        return
    start = 0
    if b.keyword.endswith("_RAMP"):
        for k, line in enumerate(b.raw):
            if line.strip():
                start = k + 1
                break
    for k in range(start, len(b.raw)):
        line = b.raw[k]
        if not line.strip():
            continue
        parsed = _parse_node_line(line)
        if parsed is None:
            continue
        nid, toks, tail = parsed
        b.raw[k] = _emit_node_line(nid + nodeoff, toks, tail)


# ─────────────────────────────────────────────────────────────────────────────
# The declarative offset map
# ─────────────────────────────────────────────────────────────────────────────
# spec = {"cards": {card_index_after_title: [(field, bucket), ...]},
#         "data": (start_card_after_title, [(field, bucket), ...]),  # repeated
#         "stride": int, "w": field width, "idhdr": bucket of the _ID heading}
# or a callable(block, offsets, warn).  Field index ALL = every field.

def _mat(extra: Optional[Dict[int, List[Tuple[int, str]]]] = None) -> dict:
    """Material spec: MID on card 1 field 1, plus any extra (card, field)
    curve/table reference fields."""
    cards: Dict[int, List[Tuple[int, str]]] = {0: [(0, "m")]}
    for ci, mods in (extra or {}).items():
        cards[ci] = cards.get(ci, []) + mods
    return {"cards": cards}


# ─────────────────────────────────────────────────────────────────────────────
# Seatbelts / restraints
# ─────────────────────────────────────────────────────────────────────────────
#
# Bucket assignments, from ``hcioi_utils.cpp:769-846`` and the cfg's own HCDI
# types (``include_transform.cfg:65-78`` names only NODE/ELEMENT/COMPONENT/
# MATERIAL/FUNCT/SETS/BLOCK-family offsets; ``hcioi_utils.cpp:564-579`` falls
# every other cfg type back to ``_DEFAULT_IDOFFSET`` = IDROFF):
#
#   belt element id                          ELEMS      -> IDEOFF ("e")
#   its N1..N4                               NODES      -> IDNOFF ("n")
#   its PID                                  COMPS      -> IDPOFF ("p")
#   its SBRID (VALUE(RETRACTOR))             RETRACTORS -> IDROFF ("r")
#   *SECTION_SEATBELT SECID                  PROPS      -> IDROFF ("r")
#   *MAT_SEATBELT MID                        MATS       -> IDMOFF ("m")
#   slipring / retractor / pretensioner /
#     sensor / accelerometer own ids         (no drawable) -> IDROFF ("r")
#   SBID / SBID1 / SBID2 (VALUE(ELEMS))      ELEMS      -> IDEOFF ("e")
#   SBRNID / ONID / NID / NID1..3            NODES      -> IDNOFF ("n")
#   SID1..4, SBSID1..4 (VALUE(SENSOR))       SENSORS    -> IDROFF ("r")
#   LLCID ULCID PTLCID FUNCID LCNFFD LCNFFS  CURVES     -> IDFOFF ("f")
#   the SHELL-belt flavours (SBID1_SHELL,
#     SBRNID_NODES)                          SETS       -> IDSOFF ("s")
#
# There is NO _PROPERTY_IDOFFSET and NO _SENSOR_IDOFFSET on *INCLUDE_TRANSFORM,
# which is why a *SECTION_SEATBELT and a *ELEMENT_SEATBELT_SENSOR both move
# with IDROFF rather than with something of their own.

#: The 8/8/8/8/8/16/8/8 column grid of an ``*ELEMENT_SEATBELT`` card. SLEN is
#: SIXTEEN wide, so a uniform 8-wide re-render would move N3 and N4 into the
#: right half of it — the ``*ELEMENT_SPH`` MASS trap on a card where the damage
#: is worse, because N3 and N4 both non-zero is what turns a 1D belt into a 2D
#: one.
_SEATBELT_ELEM_WIDTHS = (8, 8, 8, 8, 8, 16, 8, 8)
_SEATBELT_ELEM_BUCKETS = ("e", "p", "n", "n", "r", "", "n", "n")


def _off_element_seatbelt(b: Block, offsets: Dict[str, int], warn) -> None:
    """*ELEMENT_SEATBELT: ``EID(I8) PID(I8) N1..N2(I8) SBRID(I8) SLEN(F16)
    N3(I8) N4(I8)``.

    The card is READ the way its HANDLER reads it, never on a slice of its own:
    ``handlers._seatbelt_elem_card`` is imported and called here, so the two
    readers cannot desync. A rewriter that slices where the handler splits is a
    SILENT corruption of every value on the card — the lesson
    ``_off_element_sph`` records, and this card carries the same 16-wide cell
    that causes it.

    The SLEN text is preserved verbatim: only the seven id cells are
    re-rendered, each right-justified in its own column, so an I8 deck comes
    out of the rewriter in the columns it went in.
    """
    from .handlers import _seatbelt_elem_card
    for k, line in enumerate(b.raw):
        if not line.strip() or line.lstrip().startswith("$"):
            continue
        cut = line.find("$")
        data, tail = (line[:cut], line[cut:]) if cut > 0 else (line, "")
        fields = _seatbelt_elem_card(data)
        if to_int(fields[0]) <= 0 or to_int(fields[1]) <= 0:
            continue
        changed = False
        out = list(fields)
        for i, bucket in enumerate(_SEATBELT_ELEM_BUCKETS):
            off = offsets.get(bucket, 0) if bucket else 0
            tok = out[i].strip()
            if not off or not tok:
                continue
            v = to_int(tok)
            if v > 0:
                out[i] = str(v + off)
                changed = True
        if not changed:
            continue
        if "," in data:
            b.raw[k] = ",".join(x.strip() for x in out).rstrip(",") + tail
            continue
        while out and not out[-1].strip():
            out.pop()
        if any(len(x.strip()) > w
               for x, w in zip(out, _SEATBELT_ELEM_WIDTHS)):
            # An id outgrew its cell; a fixed re-render would run it into its
            # neighbour, so fall back to a free card. It has to be the COMMA
            # form, not a space-joined one: a BLANK interior cell — SLEN on a
            # 2D belt, SBRID on most — joins to nothing between two spaces, and
            # `parse_free` collapses run-on whitespace, so the card reads back
            # one slot out of phase. MEASURED, the very shift this card's
            # slicer exists to prevent: with e=n=1e8,
            # "66000004660000026600000266000172       0                6600005766000058"
            # (I8, SLEN blank) space-joined to
            # "166000004 66000002 166000002 166000172 0  166000057 166000058"
            # reads back SLEN=166000057, N3=166000058, N4 empty — the 2D shell
            # belt becomes a 1D /SPRING with 166,000,057 units of invented
            # slack. Commas hold an empty field in its position ("two
            # consecutive commas hold an EMPTY field", `parse_free`), so the
            # comma form round-trips through `_seatbelt_elem_card` unchanged
            # and nothing has to be invented to fill the gap.
            b.raw[k] = ",".join(x.strip() for x in out).rstrip(",") + tail
            continue
        b.raw[k] = "".join(
            x.strip().rjust(w)
            for x, w in zip(out, _SEATBELT_ELEM_WIDTHS)).rstrip() + tail


def _off_seatbelt_accelerometer(b: Block, offsets: Dict[str, int],
                                warn) -> None:
    """*ELEMENT_SEATBELT_ACCELEROMETER: ``SBACID NID1 NID2 NID3 IGRAV INTOPT
    MASS``, one card each. IGRAV above 1 is a CURVE id (Vol I: "GT.1: the flag
    is given by load curve IGRAV"), so it moves with IDFOFF — but only then,
    which a flat spec cannot express."""
    for k, line in enumerate(b.raw):
        if not line.strip() or line.lstrip().startswith("$"):
            continue
        f = _fields(line, 7, 10)
        if _geti(f, 0) <= 0:
            continue
        mods = [(0, "r"), (1, "n"), (2, "n"), (3, "n")]
        if _geti(f, 4) > 1:
            mods.append((4, "f"))
        new = _rewrite_line(line, mods, offsets)
        if new is not None:
            b.raw[k] = new


def _off_seatbelt_slipring(b: Block, offsets: Dict[str, int], warn) -> None:
    """*ELEMENT_SEATBELT_SLIPRING, both cards.

    Two cells change BUCKET with the sign of another cell, which is why this is
    a walker and not a declarative spec:

    * ``SBRNID < 0`` makes the ring a SHELL-belt ring, and then ``SBID1`` /
      ``SBID2`` are ``*SET_SHELL_LIST`` ids (IDSOFF) rather than element ids
      (IDEOFF), and ``|SBRNID|`` is a ``*SET_NODE`` (IDSOFF) rather than a node
      (IDNOFF);
    * ``FC < 0`` and ``FCS < 0`` are ``*DEFINE_CURVE`` ids carrying their sign,
      so they move with IDFOFF and have to keep the minus — which is exactly
      what ``_rewrite_neg_ref`` exists for (``_rewrite_line`` deliberately
      touches only values > 0, because everywhere else a negative cell is a
      flag).

    Card 2 is claimed the same way ``handlers._slipring_card2_follows`` claims
    it — the #119 rule that the two walks must agree on which line is a card,
    or the offsetter and the handler address different rows.
    """
    from .handlers import _slipring_card2_follows
    rows = _seatbelt_rows(b)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _fields(b.raw[i], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        k += 1
        onid = _geti(f1, 7)
        shell = to_float(f1[4]) < 0.0 if len(f1) > 4 and f1[4].strip() else False
        el_bucket = "s" if shell else "e"
        node_bucket = "s" if shell else "n"
        mods = [(0, "r"), (1, el_bucket), (2, el_bucket), (7, "n")]
        if not shell:
            mods.append((4, node_bucket))
        new = _rewrite_line(b.raw[i], mods, offsets)
        if new is not None:
            b.raw[i] = new
        foff = offsets.get("f", 0)
        soff = offsets.get("s", 0)
        for idx, off in ((3, foff), (6, foff),
                         (4, soff if shell else 0)):
            if not off:
                continue
            g = _fields(b.raw[i], 8, 10)
            if len(g) > idx and g[idx].strip() and to_float(g[idx]) < 0.0:
                upd = _rewrite_neg_ref(b.raw[i], idx, off)
                if upd is not None:
                    b.raw[i] = upd
        if _slipring_card2_follows(b, rows, k, i, onid):
            # K FUNCID DIRECT DC <blank> LCNFFD LCNFFS — columns 41-50 are ten
            # literal blanks in the cfg's CARD string, so the two normal-force
            # curves are fields 5 and 6, not 4 and 5.
            new = _rewrite_line(b.raw[rows[k]],
                                [(1, "f"), (5, "f"), (6, "f")], offsets)
            if new is not None:
                b.raw[rows[k]] = new
            k += 1


def _off_seatbelt_retractor(b: Block, offsets: Dict[str, int], warn) -> None:
    """*ELEMENT_SEATBELT_RETRACTOR, both cards.

    Card 1 ``SBRID SBRNID SBID SID1..SID4 DSID``, card 2
    ``TDEL PULL LLCID ULCID LFED LCFL FLOPT``. ``SBRNID < 0`` makes it a
    SHELL-belt retractor: ``|SBRNID|`` is a ``*SET_NODE`` and ``SBID`` a
    ``*SET_SHELL_LIST``, both IDSOFF.

    Card 2 is claimed by RAW CONTIGUITY, the same test the handler uses: an
    all-blank card 2 is legal (every field on it has a default), and treating
    it as absent would offset the NEXT retractor's card 1 as a card 2 and then
    run one card out of phase for the rest of the block.
    """
    rows = _seatbelt_rows(b)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _fields(b.raw[i], 8, 10)
        if _geti(f1, 0) <= 0:
            break
        k += 1
        shell = _geti(f1, 1) < 0
        mods = [(0, "r"), (2, "s" if shell else "e"),
                (3, "r"), (4, "r"), (5, "r"), (6, "r"), (7, "r")]
        if not shell:
            mods.append((1, "n"))
        new = _rewrite_line(b.raw[i], mods, offsets)
        if new is not None:
            b.raw[i] = new
        if shell and offsets.get("s", 0):
            upd = _rewrite_neg_ref(b.raw[i], 1, offsets["s"])
            if upd is not None:
                b.raw[i] = upd
        if k < len(rows) and rows[k] == i + 1:
            # TDEL PULL LLCID ULCID LFED LCFL FLOPT — THREE *DEFINE_CURVE
            # references, not two: LCFL (field 5) is the adaptive multi-level
            # load limiter, "a curve representing an adaptive multi-level load
            # limiter ... the abscissa is the ID of a *SENSOR_SWITCH" (Vol I
            # *ELEMENT_SEATBELT_RETRACTOR), so the CELL is a curve id like any
            # other even though its POINTS are switch ids. k2rad warn-drops
            # LCFL, so no EMITTED card dangles either way, but the rewritten .k
            # is what a second consumer reads and what the warning quotes.
            # (The switch ids INSIDE that curve are a *SENSOR_SWITCH namespace
            # k2rad does not convert and cannot offset from here.)
            new = _rewrite_line(b.raw[rows[k]],
                                [(2, "f"), (3, "f"), (5, "f")], offsets)
            if new is not None:
                b.raw[rows[k]] = new
            k += 1


def _off_seatbelt_pretensioner(b: Block, offsets: Dict[str, int],
                               warn) -> None:
    """*ELEMENT_SEATBELT_PRETENSIONER, both cards.

    Card 1 ``SBPRID SBPRTY SBSID1..SBSID4`` (the four sensor ids move with
    IDROFF), card 2 ``SBRID TIME PTLCID LMTFRC LMTPIN`` (PTLCID a curve,
    IDFOFF).

    ``SBRID`` sits in TWO id namespaces and card ONE says which: "Retractor
    number (SBPRTY = 1, 4, 5, 6, 7 or 8) or SPRING ELEMENT number
    (SBPRTY = 2, 3 or 9)" (Vol I *ELEMENT_SEATBELT_PRETENSIONER). Offsetting it
    as a retractor on a SBPRTY 2/3/9 card moves a belt element id by IDROFF and
    dangles it — which is why this is a walker and not a flat spec.

    Card 2 is claimed by RAW CONTIGUITY, and here the reason is sharper than
    on the retractor: on SBPRTY 7/8/9 the legacy ``Keyword971`` cfg writes card
    2 with field 0 LITERALLY BLANK, so a walk keyed on a populated leading cell
    would take the next pretensioner's card 1 as this one's SBRID and offset it
    twice.
    """
    rows = _seatbelt_rows(b)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _fields(b.raw[i], 6, 10)
        if _geti(f1, 0) <= 0:
            break
        k += 1
        new = _rewrite_line(
            b.raw[i], [(0, "r"), (2, "r"), (3, "r"), (4, "r"), (5, "r")],
            offsets)
        if new is not None:
            b.raw[i] = new
        if k < len(rows) and rows[k] == i + 1:
            sbrid_bucket = "e" if _geti(f1, 1) in (2, 3, 9) else "r"
            new = _rewrite_line(b.raw[rows[k]],
                                [(0, sbrid_bucket), (2, "f")], offsets)
            if new is not None:
                b.raw[rows[k]] = new
            k += 1


def _off_seatbelt_sensor(b: Block, offsets: Dict[str, int], warn) -> None:
    """*ELEMENT_SEATBELT_SENSOR: card 1 ``SBSID SBSTYP SBSFL``, then ONE type
    card whose ID CELLS depend on SBSTYP — the #119 walk, on the offsetter side
    this time:

      1  ``NID DOF ACC ATIME``     field 0 is a NODE
      2  ``SBRID PULRAT PULTIM``   field 0 is a RETRACTOR
      3  ``TIME``                  no ids at all
      4  ``NID1 NID2 DMX DMN``     fields 0 and 1 are NODES
      5  ``SBRID PULMX PULMN``     field 0 is a RETRACTOR

    Offsetting field 0 as a node on a SBSTYP=2 card would move a retractor id
    by IDNOFF and dangle it; reading the card as having no ids on a SBSTYP=1
    deck would leave the watched node behind while the mesh moved.
    """
    _card2 = {1: [(0, "n")], 2: [(0, "r")], 3: [], 4: [(0, "n"), (1, "n")],
              5: [(0, "r")]}
    rows = _seatbelt_rows(b)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _fields(b.raw[i], 3, 10)
        if _geti(f1, 0) <= 0:
            break
        k += 1
        new = _rewrite_line(b.raw[i], [(0, "r")], offsets)
        if new is not None:
            b.raw[i] = new
        mods = _card2.get(_geti(f1, 1), [])
        if k < len(rows) and rows[k] == i + 1:
            if mods:
                new = _rewrite_line(b.raw[rows[k]], mods, offsets)
                if new is not None:
                    b.raw[rows[k]] = new
            k += 1


def _off_section_seatbelt(b: Block, offsets: Dict[str, int], warn) -> None:
    """Every *SECTION_SEATBELT card set: SECID (IDROFF). A card-SET walker for
    the reason every ``*SECTION_*`` here is one — a declarative spec addresses
    only the first set, and every later section would keep its original SECID
    while the *PARTs that name it moved."""
    per_set_title = _title_offset(b)
    raw = b.raw
    idx = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        if per_set_title:
            idx += 1
            if idx >= len(raw):
                break
        f1 = _fields(raw[idx], 3, 10)
        if _geti(f1, 0) <= 0:
            break
        new = _rewrite_line(raw[idx], [(0, "r")], offsets)
        if new is not None:
            raw[idx] = new
        idx += 1


_ELEM_SHELL_MODS = [(0, "e"), (1, "p")] + [(i, "n") for i in range(2, 10)]

# A discrete-beam LCID run: six consecutive *DEFINE_CURVE references (IDFOFF).
_SIX_CURVE_FIELDS = [(i, "f") for i in range(6)]
# MAT_067: card 1 fields 3-8 (LCIDTR…LCIDRT, after MID+RO) and the whole of
# card 2 (LCIDTDR…LCIDRDT).
_DBEAM_CURVE_CARDS_67 = {0: [(i, "f") for i in range(2, 8)],
                         1: _SIX_CURVE_FIELDS}
# MAT_119: cards 2-5 are the loading / unloading / damping / elastic LCID runs.
_DBEAM_CURVE_CARDS_119 = {i: _SIX_CURVE_FIELDS for i in (1, 2, 3, 4)}


def _off_mat_196(b: Block, offsets: Dict[str, int], warn) -> None:
    """*MAT_GENERAL_SPRING_DISCRETE_BEAM: MID on card 1, then repeating card
    PAIRS (``DOF TYPE K D CDF TDF`` / ``FLCID HLCID C1 C2 DLE GLCID``) — the
    curve references sit on the SECOND card of every pair, so the stride has to
    be walked; a flat ``data`` spec would offset the DOF/TYPE integers too."""
    toff = _title_offset(b)
    raw = b.raw
    new = _rewrite_line(raw[toff], [(0, "m")], offsets) if toff < len(raw) else None
    if new is not None:
        raw[toff] = new
    idx = toff + 1
    pairs = 0
    while idx + 1 < len(raw) and pairs < 6:
        fa = _fields(raw[idx], 8, 10)
        dof = _geti(fa, 0)
        if dof < 1 or dof > 6:
            break
        new = _rewrite_line(raw[idx + 1], [(0, "f"), (1, "f"), (5, "f")],
                            offsets)
        if new is not None:
            raw[idx + 1] = new
        idx += 2
        pairs += 1


def _off_damping_part_mass_common(b: Block, offsets: Dict[str, int],
                                  pid_bucket: str) -> None:
    """*DAMPING_PART_MASS[_SET]: offset PID/PSID and LCID on every card 1, and
    STEP OVER the FLAG=1 Scale Factor Card.

    A flat ``data`` spec cannot be used here. ``_rewrite_line`` decides what is
    an id with ``to_int(tok) > 0``, and ``to_int`` goes through ``float`` — so a
    scale factor of ``1.5`` reads back as the id ``1`` and would be rewritten to
    ``1 + IDPOFF``, silently turning a damping scale factor into a part number.
    The FLAG column makes the optional card unambiguous, so the walk skips it.

    The row filter mirrors ``handlers._damping_data_rows`` (blank placeholder
    cards and ``$`` comments are not card 1s), and — critically — so does the
    RAW-CONTIGUITY test on the Scale Factor Card: an all-blank card 2 is a legal
    "every scale factor defaults to 0.0" card that the filter drops, so skipping
    ``rows[k]`` unconditionally on FLAG=1 would step over the FOLLOWING card 1
    and leave its PID/LCID un-offset. The two walks must agree on which line is
    a card 1 or *INCLUDE_TRANSFORM silently desyncs from the handler.
    """
    toff = _title_offset(b)
    raw = b.raw
    rows = [i for i in range(toff, len(raw))
            if raw[i].strip() and not raw[i].lstrip().startswith("$")]
    k = 0
    while k < len(rows):
        idx = rows[k]
        k += 1
        flag = _geti(_fields(raw[idx], 4, 10), 3)
        new = _rewrite_line(raw[idx], [(0, pid_bucket), (1, "f")], offsets)
        if new is not None:
            raw[idx] = new
        if flag == 1 and k < len(rows) and rows[k] == idx + 1:
            k += 1                      # the Scale Factor Card holds no ids


def _off_damping_first_data_card(mods):
    """Offset *mods* on the first REAL data card, blank placeholders skipped.

    A flat ``{"cards": {0: ...}}`` spec addresses ``raw[_title_offset + 0]``,
    but ``handlers._damping_data_rows`` skips blank placeholder cards — so a
    single blank line after the keyword makes the offsetter rewrite the
    placeholder while the handler happily reads the real card one line down,
    and its ids come through un-offset with no "offsets are NOT applied"
    warning. Both walks have to use the same rule for finding card 1.
    """
    def _off(b: Block, offsets: Dict[str, int], warn) -> None:
        raw = b.raw
        for i in range(_title_offset(b), len(raw)):
            if raw[i].strip() and not raw[i].lstrip().startswith("$"):
                new = _rewrite_line(raw[i], mods, offsets)
                if new is not None:
                    raw[i] = new
                return
    return _off


def _off_db_history(bucket: str, local: bool = False):
    """Offset spec for *DATABASE_HISTORY_<FAMILY>[_SET][_LOCAL][_ID].

    A callable rather than a flat ``{"data": ...}`` spec, for two reasons that
    are both the #119 rule — the offset walk and the handler MUST agree on
    which raw line is a card, or the ids move in one and not the other:

      * ``_offset_block`` starts its ``data`` walk at ``_title_offset(b)``,
        which is 1 whenever the ``_ID`` option is present. On this family
        ``_ID`` is a PER-ENTITY 70-char HEADING beside every id, NOT a
        card-level "id + title" header, so the flat spec silently skipped the
        FIRST requested entity while ``handlers._handle_db_history`` read it.
        (The desync was invisible only because the handler's own free split
        could not read an ``_ID`` card either — both halves are fixed here.)
      * the ``_ID`` card FUSES ``%10d`` and ``%-70s``, which ``_rewrite_line``
        cannot touch: ``_split_card`` sees the space inside the heading, falls
        back to a whitespace split, and field 0 becomes ``5000390Left``.
        ``_rewrite_id_header`` rewrites columns 1-10 only and leaves the rest
        of the line byte-identical.

    ``local`` adds the ``_LOCAL`` card's CID column (field 1) in the IDDOFF
    bucket — a *DEFINE_COORDINATE id. REF (field 2) and HFO (field 3) are
    plain flags and must NOT be offset, which is the other thing a
    ``(ALL, ...)`` spec would get wrong.
    """
    def _off(b: Block, offsets: Dict[str, int], warn) -> None:
        raw = b.raw
        rows = [i for i in range(len(raw))
                if raw[i].strip() and not raw[i].lstrip().startswith("$")]
        is_id = "ID" in b.options
        if local:
            k = 0
            while k < len(rows):
                idx = rows[k]
                k += 1
                new = _rewrite_line(raw[idx], [(0, bucket), (1, "d")], offsets)
                if new is not None:
                    raw[idx] = new
                # RAW contiguity, the same test the handler uses: a blank
                # HEADING card is legal and drops out of `rows`, so "the next
                # row" would step onto the FOLLOWING entity card and offset it
                # twice while treating its id as a heading.
                if is_id and k < len(rows) and rows[k] == idx + 1:
                    k += 1                    # the heading card holds no ids
            return
        off = offsets.get(bucket, 0)
        for idx in rows:
            if is_id:
                new = _rewrite_id_header(raw[idx], off)
            else:
                new = _rewrite_line(raw[idx], [(ALL, bucket)], offsets)
            if new is not None:
                raw[idx] = new
    return _off


def _off_initial_strain_shell_common(b: Block, offsets: Dict[str, int],
                                     is_set: bool) -> None:
    """*INITIAL_STRAIN_SHELL[_SET]: offset the EID (or SET id) on every card 1.

    Driven by ``handlers.initial_strain_shell_records`` — the SAME walker the
    handler parses with (#116), so the two can never disagree about which raw
    row is a card 1. A flat ``data`` spec cannot be used: the strain cards hold
    only floats, and ``_rewrite_line`` decides what is an id with
    ``to_int(tok) > 0``, so a strain of ``0.011`` would read back as the id
    ``0``… and one of ``1.5`` as the id ``1``, rewritten to ``1 + IDEOFF``.
    Raw contiguity is what the walker enforces (#119): an all-blank strain card
    is legal and must not be mistaken for the next record's card 1.

    Bucket: the plain spelling's cell 1 is an ELEMENT id (IDEOFF); the ``_SET``
    spelling's is a ``*SET_SHELL`` id (IDSOFF) — Vol I R17 p.3120, "shell
    element set ID when the SET option is used".
    """
    raw = b.raw
    bucket = "s" if is_set else "e"
    toff = _title_offset(b)
    body = raw[toff:]
    for card1, _fields, _pt_rows in initial_strain_shell_records(body, is_set):
        idx = toff + card1
        new = _rewrite_line(raw[idx], [(0, bucket)], offsets)
        if new is not None:
            raw[idx] = new


def _off_initial_stress_shell(b: Block, offsets: Dict[str, int], warn) -> None:
    """*INITIAL_STRESS_SHELL: offset the EID on every card 1 — IDEOFF.

    Driven by ``handlers.initial_stress_shell_records``, the SAME walker the
    handler parses with, for the same reason ``_off_initial_strain_shell``
    needs one (#116/#119): the stress cards are ALL floats, and
    ``_rewrite_line`` decides what is an id with ``to_int(tok) > 0``, so a
    declarative ``{"data": ...}`` spec would rewrite a stress of ``1.5`` as
    the element id ``1``. And an all-blank stress card is legal LS-DYNA (every
    component defaults to 0.0), so the record boundaries can only be found by
    RAW CONTIGUITY from the card-1 row, which is what the walker enforces.

    Bucket: cell 1 is ``EID/SID``, and for the PLAIN spelling that is an
    ELEMENT id — Vol I R17 p.28-95, "Element ID or element set ID (see
    *SET_SHELL)" — so IDEOFF ("e"). The ``_SET`` spelling would be IDSOFF; it
    is not registered in ``INITIAL_STATE_PRELOAD_KEYWORDS``, so it lands in
    ``skipped_keywords`` and never reaches this table (``_split_keyword``
    keeps ``_SET`` in the base name — verified — so it is NOT silently
    misparsed as the plain form).

    Nothing else on the card is an id: NPLANE/NTHICK/NHISV/NTENSR/LARGE/
    NTHINT/NTHHSV are counts and flags, and the stress records are pure
    floats.
    """
    raw = b.raw
    for card1, _fields, _pt_rows, _trunc in initial_stress_shell_records(raw):
        new = _rewrite_line(raw[card1], [(0, "e")], offsets)
        if new is not None:
            raw[card1] = new


def _off_initial_stress_solid(b: Block, offsets: Dict[str, int], warn) -> None:
    """*INITIAL_STRESS_SOLID: offset the EID on every card 1 — IDEOFF.

    The solid twin of :func:`_off_initial_stress_shell`, driven by
    ``handlers.initial_stress_solid_records`` and needing a walker for the
    identical reason (float-only stress cards, legal all-blank cards).

    Card 1 is ``EID/SID NINT NHISV LARGE IVEFLG IALEGP NTHINT NTHHSV`` (Vol I
    R17 p.28-103); cell 1 is an ELEMENT id on the plain spelling -> "e".

    ``IALEGP`` (cell 6) is an ALE multi-material GROUP number, not an id in any
    of the seven *INCLUDE_TRANSFORM buckets (Vol I R17 p.27-5 offers IDNOFF /
    IDEOFF / IDPOFF / IDMOFF / IDSOFF / IDFOFF / IDDOFF and no ALE-group one),
    so it is deliberately left alone — and the handler does not read it
    either, so nothing downstream can dangle on it.
    """
    raw = b.raw
    for card1, _fields, _pt_rows, _trunc in initial_stress_solid_records(raw):
        new = _rewrite_line(raw[card1], [(0, "e")], offsets)
        if new is not None:
            raw[card1] = new


def _off_initial_volume_fraction_geometry(b: Block, offsets: Dict[str, int],
                                          warn) -> None:
    """*INITIAL_VOLUME_FRACTION_GEOMETRY: header FMSID, bucketed by FMIDTYP.

    Card 1 is ``FMSID FMIDTYP BAMMG NTRACE``, and FMSID lives in TWO id
    namespaces selected by the cell beside it — the #125 class: FMIDTYP 0
    makes it a ``*SET_PART`` id (IDSOFF) and FMIDTYP 1 a ``*PART`` id
    (IDPOFF). Offsetting it with one fixed bucket would move it into the wrong
    namespace on half the decks, which is why this is a callable and not a
    ``{"cards": {0: [(0, "p")]}}`` row.

    The container cards that follow (``CONTTYP FILLOPT FAMMG`` plus the
    geometry) are NOT rewritten. This converter reads only CONTTYP/FILLOPT/
    FAMMG from them — all three are enumerations or ALE group numbers, none is
    an id in any bucket — and the geometry cells it does not read are
    coordinates for the container types it supports. If a container type whose
    geometry is stated by NODE ids is ever read, this spec needs an arm for it
    (the audit belongs with that change, not to a guess here).
    """
    raw = b.raw
    toff = _title_offset(b)
    if toff >= len(raw):
        return
    # _split_card is the shared reader every rewriter in this file uses, so the
    # FMIDTYP this reads is the same cell _rewrite_line would edit.
    cells, _comma, _wsf = _split_card(raw[toff], 10)
    fmidtyp = to_int(cells[1]) if len(cells) > 1 else 0
    new = _rewrite_line(raw[toff], [(0, "p" if fmidtyp == 1 else "s")],
                        offsets)
    if new is not None:
        raw[toff] = new


def _off_database_cross_section_plane(b: Block, offsets: Dict[str, int],
                                      warn) -> None:
    """*DATABASE_CROSS_SECTION_PLANE: PSID -> IDSOFF, and XCT/XCH -> IDNOFF
    **when RADIUS is negative**.

    Two id namespaces in one cell again (the #125 class): Vol I R17 p.16-50
    says *"If RADIUS is negative ... XCT and XCH will be node IDs"*, so cells 1
    and 4 of card 1 are COORDINATES when RADIUS >= 0 and NODE IDS when it is
    negative. A flat ``{"cards": {0: [(0, "s")]}}`` row leaves them alone in
    both cases, which is right for the coordinates and wrong for the ids:
    MEASURED on a child include offset by IDNOFF 6000 whose section names its
    own nodes 2 and 5, the card kept asking for 2 and 5 — which the parent
    deck may well own, so the plane silently moves to the WRONG mesh, and when
    it does not the section is refused as "node 5 is missing" on a deck that
    states it perfectly.

    The RADIUS sign is read with ``_split_card``, the same reader
    ``_rewrite_line`` edits with, so the two cannot disagree about which cell
    is which. YCT/ZCT/YCH/ZCH stay untouched: the manual says they "are
    ignored" in this form.

    A callable spec bypasses ``_offset_block``'s own ``idhdr`` step, so the
    ``_ID`` header's CSID is rewritten here with the same bucket the flat row
    used ("p") — dropping it would silently stop offsetting the section id.
    """
    raw = b.raw
    toff = _title_offset(b)
    if toff and "ID" in b.options and raw:
        new = _rewrite_id_header(raw[0], offsets.get("p", 0))
        if new is not None:
            raw[0] = new
    if toff >= len(raw):
        return
    cells, _comma, _wsf = _split_card(raw[toff], 10)
    radius = to_float(cells[7]) if len(cells) > 7 else 0.0
    mods = [(0, "s")] + ([(1, "n"), (4, "n")] if radius < 0.0 else [])
    new = _rewrite_line(raw[toff], mods, offsets)
    if new is not None:
        raw[toff] = new


def _off_initial_strain_shell(b: Block, offsets: Dict[str, int], warn) -> None:
    _off_initial_strain_shell_common(b, offsets, False)


def _off_initial_strain_shell_set(b: Block, offsets: Dict[str, int], warn) -> None:
    _off_initial_strain_shell_common(b, offsets, True)


def _off_perturbation_node(b: Block, offsets: Dict[str, int], warn) -> None:
    """*PERTURBATION_NODE: NSID -> IDSOFF and CID -> IDDOFF, on CARD 1 ONLY.

    Driven by ``handlers.perturbation_node_records`` — the SAME walker the
    handler parses with (#116). A flat ``data`` spec cannot be used and neither
    can a ``{"cards": {0: ...}}`` one that ignores the rest: every card-2
    variant is float-bearing (AMPL/XWL/XOFF/... on 2a, FADE on 2b, ELLIP1/2 on
    2d, AMPL/DTYPE on 2e) and ``_rewrite_line`` decides what is an id with
    ``to_int(tok) > 0`` — a wavelength of ``1.5`` would read back as the id
    ``1`` and be rewritten to ``1 + IDSOFF``. Card 2c is a FILE NAME, which a
    positional rewrite would corrupt outright.

    ``NSID = 0`` means "perturb all the nodes in the model" (Vol I R17 p.38-4),
    not "node set 0", and must NOT be offset — ``_rewrite_line`` already leaves
    every zero alone.
    """
    toff = _title_offset(b)
    body = b.raw[toff:]
    for card1, _rows in perturbation_node_records(body):
        idx = toff + card1
        new = _rewrite_line(b.raw[idx], [(1, "s"), (5, "d")], offsets)
        if new is not None:
            b.raw[idx] = new


def _off_boundary_prescribed_final_geometry(b: Block, offsets: Dict[str, int],
                                            warn) -> None:
    """*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY.

    Card 1: ``BPFGID`` -> IDROFF ("ID for this set of imposed boundary
    conditions" is in none of the seven named classes), ``LCIDF`` -> IDFOFF.

    Node rows: hand-sliced in the manual's own column layout (I8 + 3xE16 + I8 +
    E16, or I8 + 3xE16 + I8 + E8 + E8 when IBRTH = 1) through the SAME slicer
    the handler reads with, ``handlers.final_geometry_node_row``. A uniform
    10-wide ``data`` spec would start ``Y`` inside ``X`` (the ``*ELEMENT_MASS``
    failure), and a positional ``_rewrite_line`` would additionally read the
    float coordinates as ids.

    ``NID`` is ONE CELL IN TWO ID NAMESPACES BY SIGN (the #125 trap): "GT.0:
    Node ID ... LT.0: |NID| is a node set ID" (Vol I R17 p.5-74). A positive
    NID takes IDNOFF, a negative one takes IDSOFF on its magnitude with the
    sign preserved — a walker that keys the cell on "node" alone corrupts every
    set-form row.
    """
    toff = _title_offset(b)
    if toff < len(b.raw) and b.raw[toff].strip():
        new = _rewrite_line(b.raw[toff], [(0, "r"), (1, "f")], offsets)
        if new is not None:
            b.raw[toff] = new
    f1 = _fields(b.raw[toff]) if toff < len(b.raw) else []
    ibrth = _geti(f1, 3)
    n_off, s_off, f_off = (offsets.get("n", 0), offsets.get("s", 0),
                           offsets.get("f", 0))
    if not (n_off or s_off or f_off):
        return
    widths = ((8, 16, 16, 16, 8, 8, 8) if ibrth == 1
              else (8, 16, 16, 16, 8, 16, 0))
    for k in range(toff + 1, len(b.raw)):
        line = b.raw[k]
        if not line.strip():
            continue
        cells = final_geometry_node_row(line, ibrth)
        if not cells or not cells[0].strip():
            continue
        nid = to_int(cells[0])
        if nid == 0:
            continue
        new_nid = cells[0]
        if nid > 0 and n_off:
            new_nid = str(nid + n_off)
        elif nid < 0 and s_off:
            new_nid = str(-(abs(nid) + s_off))
        new_lcid = cells[4]
        if f_off and new_lcid.strip() and to_int(new_lcid) > 0:
            new_lcid = str(to_int(new_lcid) + f_off)
        if new_nid == cells[0] and new_lcid == cells[4]:
            continue
        out = list(cells)
        out[0], out[4] = new_nid, new_lcid
        cols = [(tok, w) for tok, w in zip(out, widths) if w]
        # No inline-comment handling needed on either side: parse_k_file runs
        # _strip_inline_comment on EVERY line it puts into Block.raw, so a
        # "$..." tail is already gone before any walker — read or offset — sees
        # the card, and the offset pass mutates Block.raw, never the include
        # file on disk.
        #
        # An offset id that outgrows its column would shift every later cell —
        # the #125 free-format trap. _join_card's comma form keeps an empty
        # field between commas, so it is the safe fallback here too.
        if "," in line or any(len(tok) > w for tok, w in cols):
            b.raw[k] = _join_card(out[:6] if ibrth != 1 else out,
                                  True, False, 8)
            continue
        b.raw[k] = "".join(f"{tok:>{w}}" for tok, w in cols).rstrip()


def _off_interface_springback(b: Block, offsets: Dict[str, int], warn) -> None:
    """*INTERFACE_SPRINGBACK_LSDYNA: PSID -> IDSOFF, Card-4 NID -> IDNOFF.

    Driven by ``handlers.springback_records`` — the SAME walker the handler
    parses with (#116), so the two can never disagree about which rows are
    ``OPTCARD`` optional cards and which are node cards. The OPTCARD rows carry
    no id at all (SLDO/NCYC/FSPLIT/NDFLAG/CFLAG/HFLAG are flags and counts) and
    are left untouched; a ``data`` spec would rewrite ``NCYC`` as though it were
    an id.
    """
    toff = _title_offset(b)
    body = b.raw[toff:]
    for card1, _opt, nodes in springback_records(body):
        idx = toff + card1
        new = _rewrite_line(b.raw[idx], [(0, "s")], offsets)
        if new is not None:
            b.raw[idx] = new
        for k in nodes:
            new = _rewrite_line(b.raw[toff + k], [(0, "n")], offsets)
            if new is not None:
                b.raw[toff + k] = new


def _off_damping_part_mass(b: Block, offsets: Dict[str, int], warn) -> None:
    _off_damping_part_mass_common(b, offsets, "p")


def _off_damping_part_mass_set(b: Block, offsets: Dict[str, int], warn) -> None:
    _off_damping_part_mass_common(b, offsets, "s")


_OFFSET_SPECS: Dict[str, object] = {
    # Mesh
    "NODE": _off_node,
    # The _THICKNESS/_BETA/_MCID/_OFFSET/_DOF and _ORIENTATION spellings are
    # registered from the same grammar handlers.py uses, just below this dict;
    # _apply_offsets additionally falls back on the family prefix, so an
    # unlisted spelling is offset rather than warned about.
    "ELEMENT_SHELL": _off_element_shell,
    "ELEMENT_SOLID": _off_element_solid,
    # *ELEMENT_TSHELL — the _BETA/_COMPOSITE spellings come from the same
    # grammar handlers.py uses, just below this dict, and the family prefix
    # catches anything outside it.
    "ELEMENT_TSHELL": _off_element_tshell,
    # *ELEMENT_SPH — the _VOLUME spelling comes from the same grammar
    # handlers.py uses, just below this dict; field 0 is a NODE, not an element
    # (see _off_element_sph).
    "ELEMENT_SPH": _off_element_sph,
    "ELEMENT_BEAM": _off_element_beam,
    # *ELEMENT_PLOTEL: EID N1 N2 (I8) — no PID column.
    "ELEMENT_PLOTEL": {"data": (0, [(0, "e"), (1, "n"), (2, "n")]), "w": 8},
    "ELEMENT_DISCRETE": _off_element_discrete,
    "ELEMENT_MASS": _off_element_mass,
    "ELEMENT_MASS_NODE_SET": _off_element_mass_node_set,
    "ELEMENT_MASS_PART": {"data": (0, [(0, "p"), (3, "f")]), "idhdr": "r"},
    "ELEMENT_MASS_PART_SET": {"data": (0, [(0, "s"), (3, "f")]), "idhdr": "r"},
    "PART": _off_part,
    "HOURGLASS": {"cards": {0: [(0, "r")]}},

    # Sections. *SECTION_SHELL and *INTEGRATION_SHELL are card-SET keywords —
    # a walker, not a declarative spec, because a declarative one addresses only
    # the first set (see the note above _off_section_shell). The walker also
    # carries the NEGATED card-1 field-6 QR/IRID back-reference across with
    # IDROFF, which the declarative form could not: _rewrite_line only touches
    # positive cells, so the rule id moved and the reference to it did not.
    "SECTION_SHELL": _off_section_shell,
    # *INTEGRATION_SHELL: IRID shares the *SECTION id space (IDROFF, bucket
    # "r"), and each S/WF/PID point card's third field is a *PART reference.
    "INTEGRATION_SHELL": _off_integration_shell,
    # The other three *SECTION_* keywords are card-SET keywords too — same
    # walker-not-spec reasoning (see the note above _off_section_solid), and
    # *SECTION_BEAM carries the second NEGATED back-reference this converter
    # meets: card-1 field 4, QR/IRID.
    "SECTION_SOLID": _off_section_solid,
    # *SECTION_TSHELL is a card-SET keyword too, and its ICOMP=1 angle block
    # sits one card EARLIER than *SECTION_SHELL's (no thickness card).
    "SECTION_TSHELL": _off_section_tshell,
    # *SECTION_SPH is a card-SET keyword too; its _ELLIPSE/_TENSOR spellings add
    # one card that carries no id but must be strided. Registered from the same
    # option list handlers.py uses, just below this dict.
    "SECTION_SPH": _off_section_sph,
    "SECTION_BEAM": _off_section_beam,
    "SECTION_DISCRETE": _off_section_discrete,
    # *INTEGRATION_BEAM: IRID shares the *SECTION id space (IDROFF, bucket "r"),
    # and each S/T/WF/PID point card's FOURTH field is a *PART reference.
    "INTEGRATION_BEAM": _off_integration_beam,

    # Sets
    "SET_NODE_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "n")])},
    "SET_NODE": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "n")])},
    "SET_PART_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "p")])},
    "SET_PART": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "p")])},
    # The *SET_<FAMILY>_ADD rows are generated below from state's family table.
    # *CONTACT_INTERIOR is a bare free list of part-set ids (no header card).
    "CONTACT_INTERIOR": {"data": (0, [(ALL, "s")])},
    "SET_SHELL_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SHELL": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SOLID_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SOLID": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_BEAM_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_BEAM": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    # Same shape as its three siblings above. Inert until the output-parity
    # batch gave the set a consumer: *DATABASE_HISTORY_DISCRETE_SET offsets its
    # set-id reference through _off_db_history("s"), so without these two rows
    # an *INCLUDE_TRANSFORM moved the REFERENCE and left the *SET_DISCRETE
    # behind — the history card resolved to nothing and the /TH/SPRING was
    # dropped, or (set inside, reference outside) the set resolved but listed
    # un-offset member ids pointing at the PARENT deck's springs.
    "SET_DISCRETE_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_DISCRETE": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SEGMENT": {"cards": {0: [(0, "s")]},
                    "data": (1, [(0, "n"), (1, "n"), (2, "n"), (3, "n")])},

    # Curves / tables. The table point cards are 2E20.0 ("VALUE LCID"; the
    # legacy *DEFINE_TABLE form has bare-VALUE rows, whose absent field 1 is
    # simply untouched) while the header card is I10 — hence "data_w": 20;
    # without it the offset lands inside the VALUE (chars 11-20) and the real
    # curve/table reference in chars 21-40 dangles after the id shift.
    "DEFINE_CURVE": {"cards": {0: [(0, "f")]}},
    "DEFINE_CURVE_FUNCTION": {"cards": {0: [(0, "f")]}},
    "DEFINE_TABLE": {"cards": {0: [(0, "f")]}, "data": (1, [(1, "f")]),
                     "data_w": 20},
    "DEFINE_TABLE_2D": {"cards": {0: [(0, "f")]}, "data": (1, [(1, "f")]),
                        "data_w": 20},

    # *DEFINE geometry entities
    "DEFINE_COORDINATE_SYSTEM": {"cards": {0: [(0, "d"), (7, "d")]}},
    "DEFINE_COORDINATE_NODES": {"cards": {0: [(0, "d"), (1, "n"), (2, "n"),
                                              (3, "n")]}},
    "DEFINE_COORDINATE_VECTOR": {"cards": {0: [(0, "d"), (7, "n")]}},
    "DEFINE_VECTOR": {"cards": {0: [(0, "d"), (7, "d")]}},
    "DEFINE_VECTOR_NODES": {"cards": {0: [(0, "d"), (1, "n"), (2, "n")]}},
    "DEFINE_SD_ORIENTATION": {"cards": {0: [(0, "d"), (5, "n"), (6, "n")]}},
    "DEFINE_BOX": {"cards": {0: [(0, "d")]}},
    "DEFINE_BOX_LOCAL": {"cards": {0: [(0, "d")]}},
    "DEFINE_TRANSFORMATION": _off_define_transformation,
    # *DEFINE_FRICTION: table id on IDDOFF (Vol I p.27-5, "any ID defined
    # through *DEFINE" other than CURVE/TABLE/FUNCTION), Card-2 part pairs on
    # IDPOFF/IDSOFF per row. See _off_define_friction for why it is a walker.
    "DEFINE_FRICTION": _off_define_friction,
    "NODE_TRANSFORM": {"data": (0, [(0, "d"), (1, "s")])},

    # Materials (mid + the curve/table reference fields k2rad models)
    "MAT_ELASTIC": _mat(),
    # Impact / blast batch. Every field of *MAT_110, *MAT_111 and the
    # *MAT_ELASTIC _FLUID card is a physical constant — no curve, table or set
    # id anywhere on the three cards — so MID is the only cell to offset.
    # *MAT_COMPOSITE_DAMAGE (022): MID on card 1 field 1, and nothing else on
    # the card is an id — AOPT < 0 is a *DEFINE_COORDINATE reference, but it is
    # a NEGATIVE cell and _rewrite_line deliberately leaves those alone (a
    # negative id is a flag encoding everywhere else in LS-DYNA), the same
    # treatment MAT_002/MAT_054 get. NOTE that neither of those two has an
    # offset row at all today, so an *INCLUDE_TRANSFORM leaves their MID
    # behind while *PART's IDMOFF moves the reference — a pre-existing gap
    # this batch names rather than changes, because fixing it would move
    # output on decks that have nothing to do with MAT_022.
    "MAT_COMPOSITE_DAMAGE": _mat(),
    "MAT_022": _mat(),
    "MAT_22": _mat(),
    "MAT_JOHNSON_HOLMQUIST_CERAMICS": _mat(),
    "MAT_110": _mat(),
    "MAT_JOHNSON_HOLMQUIST_CONCRETE": _mat(),
    "MAT_111": _mat(),
    "MAT_ELASTIC_FLUID": _mat(),
    "MAT_001_FLUID": _mat(),
    "MAT_1_FLUID": _mat(),
    "MAT_001": _mat(),
    "MAT_1": _mat(),
    "MAT_PIECEWISE_LINEAR_PLASTICITY": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_024": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_24": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION":
        _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION_2D":
        _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_PIECEWISE_LINEAR_PLASTICITY_2D": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_123": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_PLASTIC_KINEMATIC": _mat(),
    # Metal plasticity batch 2. MAT_081/082 card 2 carries LCSS/LCSR (fields
    # 3/4) and LCDM (field 7); MAT_105 card 2 carries LCSS/LCSR only; MAT_019
    # card 2 is LC1 ETAN LC2 LC3 LC4 (fields 1/3/4/5); MAT_124 card 2 is
    # LCIDC LCIDT LCSRC LCSRT _ LCFAIL; MAT_120 card 6 is LCSS LCFF _ LCF0
    # LCFC LCFN; MAT_122 card 2 field 4 is LCID.
    "MAT_PLASTICITY_WITH_DAMAGE": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_PLASTICITY_WITH_DAMAGE_ORTHO": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_PLASTICITY_WITH_DAMAGE_ORTHO_RCDC":
        _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_PLASTICITY_WITH_DAMAGE_ORTHO_RCDC1980":
        _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_PLASTICITY_WITH_DAMAGE_STOCHASTIC":
        _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_081": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_81": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_081_STOCHASTIC": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_082": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_82": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_082_RCDC": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_082_RCDC1980": _mat({1: [(2, "f"), (3, "f"), (6, "f")]}),
    "MAT_DAMAGE_2": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_105": _mat({1: [(2, "f"), (3, "f")]}),
    "MAT_STRAIN_RATE_DEPENDENT_PLASTICITY":
        _mat({1: [(0, "f"), (2, "f"), (3, "f"), (4, "f")]}),
    "MAT_019": _mat({1: [(0, "f"), (2, "f"), (3, "f"), (4, "f")]}),
    "MAT_19": _mat({1: [(0, "f"), (2, "f"), (3, "f"), (4, "f")]}),
    "MAT_PLASTICITY_COMPRESSION_TENSION":
        _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"), (5, "f")]}),
    "MAT_124": _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"), (5, "f")]}),
    "MAT_GURSON": _mat({5: [(0, "f"), (1, "f"), (3, "f"), (4, "f"), (5, "f")]}),
    "MAT_120": _mat({5: [(0, "f"), (1, "f"), (3, "f"), (4, "f"), (5, "f")]}),
    # The _JC card 5 holds LCDAM (field 1) and LCJC (field 8); card 6 is the
    # base one. _RCDC / _BFRAC card 5 is not modelled — MID only, so their
    # curve ids are left alone rather than offset at a guessed position.
    "MAT_GURSON_JC": _mat({4: [(0, "f"), (7, "f")],
                           5: [(0, "f"), (1, "f"), (3, "f"), (4, "f"),
                               (5, "f")]}),
    "MAT_120_JC": _mat({4: [(0, "f"), (7, "f")],
                        5: [(0, "f"), (1, "f"), (3, "f"), (4, "f"), (5, "f")]}),
    "MAT_GURSON_RCDC": _mat(),
    "MAT_120_RCDC": _mat(),
    "MAT_GURSON_BFRAC": _mat(),
    "MAT_120_BFRAC": _mat(),
    "MAT_ISOTROPIC_ELASTIC_PLASTIC": _mat(),
    "MAT_012": _mat(),
    "MAT_12": _mat(),
    "MAT_HILL_3R": _mat({1: [(3, "f")]}),
    "MAT_122": _mat({1: [(3, "f")]}),
    "MAT_ANISOTROPIC_VISCOPLASTIC": {"cards": {0: [(0, "m"), (6, "f")]}},
    "MAT_103": {"cards": {0: [(0, "m"), (6, "f")]}},
    "MAT_RIGID": _off_mat_rigid,
    "MAT_NULL": _mat(),
    "MAT_POWER_LAW_PLASTICITY": _mat(),
    "MAT_CRUSHABLE_FOAM": {"cards": {0: [(0, "m"), (4, "f")]}},
    "MAT_63": {"cards": {0: [(0, "m"), (4, "f")]}},
    "MAT_063": {"cards": {0: [(0, "m"), (4, "f")]}},
    "MAT_LOW_DENSITY_FOAM": {"cards": {0: [(0, "m"), (3, "f")]}},
    "MAT_57": {"cards": {0: [(0, "m"), (3, "f")]}},
    "MAT_057": {"cards": {0: [(0, "m"), (3, "f")]}},
    "MAT_FU_CHANG_FOAM": {"cards": {0: [(0, "m"), (7, "f")], 1: [(4, "f")]}},
    "MAT_83": {"cards": {0: [(0, "m"), (7, "f")], 1: [(4, "f")]}},
    "MAT_083": {"cards": {0: [(0, "m"), (7, "f")], 1: [(4, "f")]}},
    "MAT_HONEYCOMB": {"cards": {0: [(0, "m")],
                                1: [(i, "f") for i in range(8)]}},
    "MAT_26": {"cards": {0: [(0, "m")], 1: [(i, "f") for i in range(8)]}},
    "MAT_026": {"cards": {0: [(0, "m")], 1: [(i, "f") for i in range(8)]}},
    # Foam batch. MAT_005 card 2 field 3 is LCID. MAT_073 card 1 field 4 is
    # LCID, card 2 field 5 is LCID2 (a curve id only when > 0; the -1
    # frequency-data flag is negative and _rewrite_line leaves negative cells
    # alone) — its conditional card-3 forms are NOT modelled, so an LCID2=-1
    # deck's LCID3/LCID4 keep their original ids (same policy as the
    # MAT_GURSON_RCDC card-5 note above). MAT_126 card 2 is the 7-curve+LCSR
    # row exactly like MAT_026 (negative flag cells untouched); its
    # conditional cards 6-8 hold no ids. MAT_154 has no curve references.
    # MAT_177 card 1 fields 6/8 are LCID/LCSR.
    "MAT_SOIL_AND_FOAM": _mat({1: [(2, "f")]}),
    "MAT_5": _mat({1: [(2, "f")]}),
    "MAT_005": _mat({1: [(2, "f")]}),
    "MAT_LOW_DENSITY_VISCOUS_FOAM": _mat({0: [(3, "f")], 1: [(4, "f")]}),
    "MAT_73": _mat({0: [(3, "f")], 1: [(4, "f")]}),
    "MAT_073": _mat({0: [(3, "f")], 1: [(4, "f")]}),
    "MAT_MODIFIED_HONEYCOMB": {"cards": {0: [(0, "m")],
                                         1: [(i, "f") for i in range(8)]}},
    "MAT_126": {"cards": {0: [(0, "m")], 1: [(i, "f") for i in range(8)]}},
    "MAT_DESHPANDE_FLECK_FOAM": _mat(),
    "MAT_154": _mat(),
    # Airbag fabric. MID → IDMOFF plus the six card-7 stress/strain curves →
    # IDFOFF, on a card whose index moves with FORM and FVOPT — a callable.
    "MAT_FABRIC": _off_mat_fabric,
    "MAT_034": _off_mat_fabric,
    "MAT_34": _off_mat_fabric,
    "MAT_HILL_FOAM": _mat({0: [(5, "f"), (7, "f")]}),
    "MAT_177": _mat({0: [(5, "f"), (7, "f")]}),
    # The RARE MATERIALS batch is registered from _RARE_MATERIAL_OFFSETS below
    # this dict, keyed off handlers.RARE_MATERIAL_KEYWORDS — ONE source.
    # Hyperelastic rubber batch. MAT_027 card 2 field 4 is the LCID test curve
    # (blank in the constants path → no-op). MAT_077_O/_H card 2 is CONDITIONAL:
    # LCID1/LCID2 only exist when N>0 (with N=0 the same card holds MU4/MU6 or
    # C20/C30 float constants), so a plain static spec would corrupt them —
    # handled by the _off_mat_077 callable.
    "MAT_BLATZ-KO_RUBBER": _mat(),
    "MAT_BLATZ_KO_RUBBER": _mat(),
    "MAT_007": _mat(),
    "MAT_7": _mat(),
    "MAT_MOONEY-RIVLIN_RUBBER": _mat({1: [(3, "f")]}),
    "MAT_MOONEY_RIVLIN_RUBBER": _mat({1: [(3, "f")]}),
    "MAT_027": _mat({1: [(3, "f")]}),
    "MAT_27": _mat({1: [(3, "f")]}),
    "MAT_OGDEN_RUBBER": _off_mat_077,
    "MAT_077_O": _off_mat_077,
    "MAT_77_O": _off_mat_077,
    "MAT_HYPERELASTIC_RUBBER": _off_mat_077,
    "MAT_077_H": _off_mat_077,
    "MAT_77_H": _off_mat_077,
    # Viscoelastic batch. MAT_006's negative temperature-curve cells and
    # MAT_181's option-dependent unloading-card index both need a callable.
    # MAT_076 card 2 (LCID field 1, LCIDK field 5) is MANDATORY in the cfg even
    # when the deck uses the Prony rows below it, so a static spec is safe.
    # MAT_061 and MAT_091/092 carry no curve references at all.
    "MAT_VISCOELASTIC": _off_mat_006,
    "MAT_006": _off_mat_006,
    "MAT_6": _off_mat_006,
    "MAT_KELVIN-MAXWELL_VISCOELASTIC": _mat(),
    "MAT_KELVIN_MAXWELL_VISCOELASTIC": _mat(),
    "MAT_061": _mat(),
    "MAT_61": _mat(),
    "MAT_GENERAL_VISCOELASTIC": _mat({1: [(0, "f"), (4, "f")]}),
    "MAT_GENERAL_VISCOELASTIC_MOISTURE": _mat({1: [(0, "f"), (4, "f")]}),
    "MAT_076": _mat({1: [(0, "f"), (4, "f")]}),
    "MAT_76": _mat({1: [(0, "f"), (4, "f")]}),
    "MAT_SOFT_TISSUE": _mat(),
    "MAT_091": _mat(),
    "MAT_91": _mat(),
    "MAT_SOFT_TISSUE_VISCO": _mat(),
    "MAT_092": _mat(),
    "MAT_92": _mat(),
    # Adhesives / cohesive batch. MAT_138's and MAT_169's curve references are
    # NEGATIVE-encoded floats (and MAT_169's SDFAC card index is conditional),
    # so both need callables; MAT_240's LCG1C/LCG2C sit at fixed cells, but the
    # _THERMAL/_FUNCTIONS spellings turn eight more cells into curve ids — a
    # static spec PER SPELLING stays exact (the base spelling must not offset
    # those cells: there they are float physics). MAT_ADD_DAMAGE_DIEM repeats
    # its curve cells NDIEMC times → callable. (The MAT_240 variant specs are
    # filled in by the grammar loop below the dict, mirroring HANDLERS.)
    "MAT_COHESIVE_MIXED_MODE": _off_mat_138,
    "MAT_138": _off_mat_138,
    "MAT_ARUP_ADHESIVE": _off_mat_169,
    "MAT_169": _off_mat_169,
    "MAT_TOUGHENED_ADHESIVE_POLYMER": _mat({1: [(0, "f")]}),
    "MAT_252": _mat({1: [(0, "f")]}),
    "MAT_ADD_DAMAGE_DIEM": _off_mat_add_damage_diem,
    # Tabulated Johnson-Cook batch. Card 2 is all curve/table ids
    # (LCK1 LCKT LCF LCG LCH LCI; BFLG field 7 is a flag) and card 3 field 5
    # is LCPS (a table id; FAILOPT/NUMAVG/NCYFAIL/ERODE are counts/flags).
    # The E<0 / BETA<0 encodings (|value| is a curve id inside a FLOAT cell)
    # are NOT offset — the machinery shifts integer id cells only; a
    # transformed deck using them draws the dangling-reference warning
    # instead of a silent wrong-curve remap. The _GYS/_ORTHO_PLASTICITY
    # variants are parse-time warn-skips but still get MID offset so the
    # dropped material's id story stays consistent.
    "MAT_TABULATED_JOHNSON_COOK":
        _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"), (4, "f"),
                  (5, "f")], 2: [(4, "f")]}),
    "MAT_TABULATED_JOHNSON_COOK_LOG_INTERPOLATION":
        _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"), (4, "f"),
                  (5, "f")], 2: [(4, "f")]}),
    "MAT_224":
        _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"), (4, "f"),
                  (5, "f")], 2: [(4, "f")]}),
    "MAT_TABULATED_JOHNSON_COOK_GYS": _mat(),
    "MAT_224_GYS": _mat(),
    "MAT_TABULATED_JOHNSON_COOK_ORTHO_PLASTICITY": _mat(),
    "MAT_264": _mat(),
    # Same 2E20.0 point-card layout as *DEFINE_TABLE above (Vol I R17 p.2571:
    # VALUE chars 1-20, TABLEID chars 21-40) — "data_w": 20 or the offset
    # corrupts the VALUE and leaves the inner-table reference dangling.
    "DEFINE_TABLE_3D": {"cards": {0: [(0, "f")]}, "data": (1, [(1, "f")]),
                        "data_w": 20},
    "SECTION_SOLID_MISC": _off_section_solid,
    # Node table in the *NODE I8/E16 format → IDNOFF (base variant has no
    # header card; _RAMP prepends the NDTRRG card, which carries no ids).
    "INITIAL_FOAM_REFERENCE_GEOMETRY": _off_foam_ref_geometry,
    "INITIAL_FOAM_REFERENCE_GEOMETRY_RAMP": _off_foam_ref_geometry,
    "MAT_SPRING_ELASTIC": _mat(),
    "MAT_S01": _mat(),
    "MAT_SPRING_NONLINEAR_ELASTIC": {"cards": {0: [(0, "m"), (1, "f"),
                                                   (2, "f")]}},
    "MAT_S04": {"cards": {0: [(0, "m"), (1, "f"), (2, "f")]}},
    "MAT_DAMPER_VISCOUS": _mat(),
    "MAT_D01": _mat(),
    # S03 K/KT/FY are scalars; S05/S06/S08 carry *DEFINE_CURVE references
    # (IDFOFF) on card 1.
    "MAT_SPRING_ELASTOPLASTIC": _mat(),
    "MAT_S03": _mat(),
    "MAT_DAMPER_NONLINEAR_VISCOUS": _mat({0: [(1, "f")]}),
    "MAT_S05": _mat({0: [(1, "f")]}),
    "MAT_D02": _mat({0: [(1, "f")]}),
    "MAT_SPRING_GENERAL_NONLINEAR": _mat({0: [(1, "f"), (2, "f")]}),
    "MAT_S06": _mat({0: [(1, "f"), (2, "f")]}),
    "MAT_SPRING_INELASTIC": _mat({0: [(1, "f")]}),
    "MAT_S08": _mat({0: [(1, "f")]}),
    # Discrete-beam materials. MID on card 1 field 1 everywhere; the LCID runs
    # are IDFOFF. MAT_066's cards carry only stiffness/damping/preload scalars.
    "MAT_LINEAR_ELASTIC_DISCRETE_BEAM": _mat(),
    "MAT_066": _mat(),
    "MAT_66": _mat(),
    "MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM": _mat(_DBEAM_CURVE_CARDS_67),
    "MAT_067": _mat(_DBEAM_CURVE_CARDS_67),
    "MAT_67": _mat(_DBEAM_CURVE_CARDS_67),
    "MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM": _mat({2: _SIX_CURVE_FIELDS}),
    "MAT_068": _mat({2: _SIX_CURVE_FIELDS}),
    "MAT_68": _mat({2: _SIX_CURVE_FIELDS}),
    "MAT_CABLE_DISCRETE_BEAM": _mat({0: [(3, "f")]}),
    "MAT_071": _mat({0: [(3, "f")]}),
    "MAT_71": _mat({0: [(3, "f")]}),
    # MAT_074 card 2: FLCID HLCID C1 C2 DLE GLCID — fields 0, 1 and 5 are curves.
    "MAT_ELASTIC_SPRING_DISCRETE_BEAM": _mat({1: [(0, "f"), (1, "f"), (5, "f")]}),
    "MAT_074": _mat({1: [(0, "f"), (1, "f"), (5, "f")]}),
    "MAT_74": _mat({1: [(0, "f"), (1, "f"), (5, "f")]}),
    "MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM": _mat(_DBEAM_CURVE_CARDS_119),
    "MAT_119": _mat(_DBEAM_CURVE_CARDS_119),
    "MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM":
        _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f")]}),
    "MAT_121": _mat({1: [(0, "f"), (1, "f"), (2, "f"), (3, "f")]}),
    "MAT_GENERAL_SPRING_DISCRETE_BEAM": _off_mat_196,
    "MAT_196": _off_mat_196,
    # The ELFORM=6 materials with no Radioss spring law: k2rad reads only their
    # MID, but the id STILL has to move under IDMOFF or the *PART reference
    # would dangle and the warn-drop would name the wrong material.
    "MAT_SID_DAMPER_DISCRETE_BEAM": _mat(),
    "MAT_069": _mat(),
    "MAT_69": _mat(),
    "MAT_HYDRAULIC_GAS_DAMPER_DISCRETE_BEAM": _mat(),
    "MAT_070": _mat(),
    "MAT_70": _mat(),
    "MAT_ELASTIC_6DOF_SPRING_DISCRETE_BEAM": _mat(),
    "MAT_093": _mat(),
    "MAT_93": _mat(),
    "MAT_INELASTIC_SPRING_DISCRETE_BEAM": _mat(),
    "MAT_094": _mat(),
    "MAT_94": _mat(),
    "MAT_INELASTIC_6DOF_SPRING_DISCRETE_BEAM": _mat(),
    "MAT_095": _mat(),
    "MAT_95": _mat(),
    "MAT_GENERAL_JOINT_DISCRETE_BEAM": _mat(),
    "MAT_097": _mat(),
    "MAT_97": _mat(),
    "MAT_1DOF_GENERALIZED_SPRING": _mat(),
    "MAT_146": _mat(),
    "MAT_SPOTWELD": _mat(),
    "MAT_100": _mat(),
    "MAT_187": {"cards": {0: [(0, "m")],
                          1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"),
                              (5, "f")]}},
    "MAT_SAMP-1": {"cards": {0: [(0, "m")],
                             1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"),
                                 (5, "f")]}},
    "MAT_SIMPLIFIED_JOHNSON_COOK": _mat(),
    "MAT_098": _mat(),
    "MAT_98": _mat(),
    "MAT_JOHNSON_COOK": _mat(),
    "MAT_015": _mat(),
    "MAT_15": _mat(),
    # MAT_099 card 1 field 7 (LCDM) is a load-curve reference
    "MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE": _mat({0: [(6, "f")]}),
    "MAT_099": _mat({0: [(6, "f")]}),
    "MAT_99": _mat({0: [(6, "f")]}),
    "MAT_HIGH_EXPLOSIVE_BURN": _mat(),
    "MAT_ADD_DAMAGE_GISSMO": {"cards": {0: [(0, "m")],
                                        1: [(0, "f"), (5, "f")],
                                        2: [(0, "f")]}},
    "MAT_ADD_EROSION": _mat(),
    "MAT_ADD_FATIGUE": {"cards": {0: [(0, "m"), (1, "f")]}},
    "EOS_JWL": _mat(),
    "EOS_LINEAR_POLYNOMIAL": _mat(),
    "EOS_GRUNEISEN": _mat(),
    "EOS_IDEAL_GAS": _mat(),

    # Boundary conditions / motions / velocities
    "BOUNDARY_SPC_SET": {"data": (0, [(0, "s"), (1, "d")]), "idhdr": "r"},
    "BOUNDARY_SPC_NODE": {"data": (0, [(0, "n"), (1, "d")]), "idhdr": "r"},
    "BOUNDARY_SPC": {"data": (0, [(0, "n"), (1, "d")]), "idhdr": "r"},
    "BOUNDARY_PRESCRIBED_MOTION_RIGID": _off_bpm("p"),
    "BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL": _off_bpm("p"),
    "BOUNDARY_PRESCRIBED_MOTION_SET": _off_bpm("s"),
    "BOUNDARY_PRESCRIBED_MOTION_SET_BOX": _off_bpm("s", is_box=True),
    "BOUNDARY_PRESCRIBED_MOTION_NODE": _off_bpm("n"),
    "INITIAL_VELOCITY": {"cards": {0: [(0, "s"), (1, "s"), (2, "d"),
                                       (4, "d")]}, "idhdr": "r"},
    "INITIAL_VELOCITY_NODE": {"data": (0, [(0, "n")]), "idhdr": "r"},
    "INITIAL_VELOCITY_RIGID_BODY": {"data": (0, [(0, "p")]), "idhdr": "r"},
    "INITIAL_VELOCITY_GENERATION": _off_inivel_generation,
    "INITIAL_DETONATION": {"data": (0, [(0, "p")])},
    # Found by the SIDE-DEFECT batch's audit of every INITIAL_* handler:
    # readable and un-offsettable, like the two *INITIAL_STRESS_* keywords.
    "INITIAL_VOLUME_FRACTION_GEOMETRY": _off_initial_volume_fraction_geometry,
    "BOUNDARY_NON_REFLECTING": {"data": (0, [(0, "s")])},

    # Constraints. The *CONSTRAINED_NODAL_RIGID_BODY option spellings (65 of them)
    # and *CONSTRAINED_INTERPOLATION are registered below from the same generators
    # handlers.py uses, so the two tables cannot drift apart.
    "CONSTRAINED_NODAL_RIGID_BODY": _off_cnrb,
    "CONSTRAINED_NODAL_RIGID_BODY_SPC": _off_cnrb,
    "CONSTRAINED_EXTRA_NODES_NODE": {"data": (0, [(0, "p"), (1, "n")])},
    "CONSTRAINED_EXTRA_NODES_SET": {"data": (0, [(0, "p"), (1, "s")])},
    "CONSTRAINED_RIGID_BODIES": {"data": (0, [(0, "p"), (1, "p")])},
    "CONSTRAINED_SPOTWELD": {"data": (0, [(0, "n"), (1, "n")])},
    "CONSTRAINED_SPOTWELD_FILTERED_FORCE": {"data": (0, [(0, "n"), (1, "n")]),
                                            "stride": 2},
    "CONSTRAINED_GENERALIZED_WELD_SPOT": {"cards": {0: [(0, "s"), (1, "d")]}},
    "CONSTRAINED_NODE_SET": {"cards": {0: [(0, "s")]}},
    "CONSTRAINED_LAGRANGE_IN_SOLID": _off_constrained_lagrange_in_solid,
    # Joints. Card 1 is N1..N6 + RPS/DAMP for every kind and every option
    # combination (the _LOCAL and _FAILURE cards follow it), so one spec covers
    # all 28 registered keywords. The _ID heading's JID goes to IDROFF, the same
    # bucket *CONSTRAINED_JOINT_STIFFNESS's JID field uses, so the reference
    # between them survives the include.
    **{f"CONSTRAINED_JOINT_{_k}{_o}":
       {"cards": {0: [(_i, "n") for _i in range(6)]}, "idhdr": "r"}
       for _k in ("SPHERICAL", "REVOLUTE", "CYLINDRICAL", "PLANAR",
                  "UNIVERSAL", "TRANSLATIONAL", "LOCKING")
       for _o in ("", "_LOCAL", "_FAILURE", "_LOCAL_FAILURE")},
    "CONSTRAINED_JOINT_STIFFNESS_GENERALIZED": _off_joint_stiffness,
    "CONSTRAINED_JOINT_STIFFNESS_TRANSLATIONAL": _off_joint_stiffness,
    "CONSTRAINED_JOINT_STIFFNESS_FLEXION-TORSION": _off_joint_stiffness,
    "CONSTRAINED_JOINT_STIFFNESS_CYLINDRICAL": _off_joint_stiffness,

    # Rigid walls (id → IDPOFF per the R16 manual bucket list)
    "RIGIDWALL_PLANAR": {"cards": {0: [(0, "s"), (1, "s"), (2, "d")]},
                         "idhdr": "p"},
    # *RIGIDWALL_GEOMETRIC Card 1 is the same NSID/NSIDEX/BOXID triple, plus a
    # _MOTION curve id and a _DISPLAY part id at shape-dependent card indices.
    "RIGIDWALL_GEOMETRIC": _off_rigidwall_geometric,

    # Loads
    "LOAD_NODE_POINT": {"data": (0, [(0, "n"), (2, "f"), (4, "d"), (5, "n"),
                                     (6, "n"), (7, "n")]), "idhdr": "r"},
    "LOAD_NODE_SET": {"data": (0, [(0, "s"), (2, "f"), (4, "d"), (5, "n"),
                                   (6, "n"), (7, "n")]), "idhdr": "r"},
    "LOAD_RIGID_BODY": {"data": (0, [(0, "p"), (2, "f"), (4, "d"), (5, "n"),
                                     (6, "n"), (7, "n")]), "idhdr": "r"},
    "LOAD_SEGMENT": _off_load_segment,
    "LOAD_SEGMENT_SET": {"data": (0, [(0, "s"), (1, "f")]), "idhdr": "r"},
    "LOAD_GRAVITY_PART": {"data": (0, [(0, "p"), (2, "f"), (4, "f")])},
    "LOAD_GRAVITY_PART_SET": {"data": (0, [(0, "s"), (2, "f"), (4, "f")])},
    # All of X/Y/Z/RX/RY/RZ/VECTOR share card 1a.1's grid: LCID and LCIDDR are
    # curves, CID a *DEFINE_COORDINATE. _VECTOR's card 1a.2 (V1 V2 V3) and
    # _R*'s XC/YC/ZC carry no ids, so no card-2 spec is needed — the geometry
    # they DO carry is reported via _DIRECTION_BEARING /
    # _carries_literal_axis_point instead.
    "LOAD_BODY_X": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_Y": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_Z": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_RX": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_RY": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_RZ": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_VECTOR": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]},
                         "idhdr": "r"},
    "LOAD_BODY_PARTS": {"data": (0, [(0, "s")]), "idhdr": "r"},
    # *LOAD_SHELL_{ELEMENT,SET}: repeated "eid|esid lcid sf at" rows.
    "LOAD_SHELL_ELEMENT": {"data": (0, [(0, "e"), (1, "f")]), "idhdr": "r"},
    "LOAD_SHELL_SET": {"data": (0, [(0, "s"), (1, "f")]), "idhdr": "r"},
    "LOAD_BLAST_ENHANCED": {"cards": {0: [(0, "r")], 1: [(4, "n")]}},
    "LOAD_BLAST": {"cards": {1: [(4, "n")]}},
    "LOAD_BLAST_SEGMENT_SET": {"data": (0, [(0, "r"), (1, "s"), (2, "p")])},
    "LOAD_BLAST_SEGMENT": {"data": (0, [(0, "r"), (1, "n"), (2, "n"), (3, "n"),
                                        (4, "n")])},

    # ALE
    "ALE_MULTI-MATERIAL_GROUP": _off_ale_multi_material_group,

    # Database / output requests
    #
    # EVERY spelling of the *DATABASE_HISTORY_* family needs its own row:
    # parser._split_keyword strips only a trailing _ID, so _SET and _LOCAL are
    # part of the base keyword. The callable is what keeps the offset walk and
    # handlers._handle_db_history reading the SAME raw lines under the _ID and
    # _LOCAL layouts — see _off_db_history.
    "DATABASE_HISTORY_NODE": _off_db_history("n"),
    "DATABASE_HISTORY_NODE_SET": _off_db_history("s"),
    "DATABASE_HISTORY_NODE_LOCAL": _off_db_history("n", local=True),
    "DATABASE_HISTORY_NODE_SET_LOCAL": _off_db_history("s", local=True),
    "DATABASE_HISTORY_SHELL": _off_db_history("e"),
    "DATABASE_HISTORY_SHELL_SET": _off_db_history("s"),
    "DATABASE_HISTORY_SOLID": _off_db_history("e"),
    "DATABASE_HISTORY_SOLID_SET": _off_db_history("s"),
    "DATABASE_HISTORY_TSHELL": _off_db_history("e"),
    "DATABASE_HISTORY_TSHELL_SET": _off_db_history("s"),
    "DATABASE_HISTORY_BEAM": _off_db_history("e"),
    "DATABASE_HISTORY_BEAM_SET": _off_db_history("s"),
    "DATABASE_HISTORY_DISCRETE": _off_db_history("e"),
    "DATABASE_HISTORY_DISCRETE_SET": _off_db_history("s"),
    # *ELEMENT_SEATBELT ids take IDEOFF like any other element even though
    # k2rad emits no channel for them: the request must still point at the
    # renumbered elements when the seatbelt batch lands.
    "DATABASE_HISTORY_SEATBELT": _off_db_history("e"),
    # *DATABASE_NODAL_FORCE_GROUP[_TITLE]: NSID is a *SET_NODE (IDSOFF) and CID
    # a *DEFINE_COORDINATE (IDDOFF); the _TITLE line is consumed by
    # _title_offset, so the flat "cards" spec is correct here (unlike the
    # HISTORY family, whose _ID is per entity).
    "DATABASE_NODAL_FORCE_GROUP": {"cards": {0: [(0, "s"), (1, "d")]}},
    # *DATABASE_HISTORY_SPH lists PARTICLE ids, and an SPH particle IS its
    # supporting node (hm_read_sphcel.F:243-250) — so these take IDNOFF, the
    # same bucket _off_element_sph gives the card's field 0, NOT IDEOFF. Without
    # the row the requested ids stay put while the particles they name move:
    # measured, an include offset to 1001-1004 asked for 1-4 and got the
    # PARENT deck's particles, which the ERROR-69 screen cannot catch because
    # those ids do exist as /SPHCEL. The _SET spelling lists *SET_NODE ids
    # (IDSOFF) for the same reason.
    "DATABASE_HISTORY_SPH": _off_db_history("n"),
    "DATABASE_HISTORY_SPH_SET": _off_db_history("s"),
    # A callable, not a flat row: XCT/XCH are COORDINATES at RADIUS >= 0 and
    # NODE IDS at RADIUS < 0 (Vol I R17 p.16-50) — see the walker.
    "DATABASE_CROSS_SECTION_PLANE": _off_database_cross_section_plane,
    "DATABASE_CROSS_SECTION_SET": {"cards": {0: [(i, "s") for i in range(6)]},
                                   "idhdr": "p"},
    "DATABASE_BINARY_D3PLOT": {"cards": {0: [(1, "f"), (4, "s")]}},

    # Damping / control cards that carry ids
    "DAMPING_GLOBAL": {"cards": {0: [(0, "f")]}},
    "DAMPING_PART_STIFFNESS": {"data": (0, [(0, "p")])},
    # *DAMPING_PART_MASS: PID(p)/PSID(s) + LCID(f), repeated card SETS whose
    # optional second card must be SKIPPED, not offset — hence a callable
    # rather than a flat "data" spec (the _off_mat_196 situation).
    "DAMPING_PART_MASS": _off_damping_part_mass,
    "DAMPING_PART_MASS_SET": _off_damping_part_mass_set,
    # *DAMPING_FREQUENCY_RANGE: PSID(s) at field 3, PIDREL(p) at field 5.
    # Every option spelling needs its own row (see the HANDLERS comment).
    # Callables, not flat "cards" specs, so the offset walk skips the same blank
    # placeholder cards handlers._damping_data_rows does.
    "DAMPING_FREQUENCY_RANGE":
        _off_damping_first_data_card([(3, "s"), (5, "p")]),
    "DAMPING_FREQUENCY_RANGE_DEFORM":
        _off_damping_first_data_card([(3, "s")]),
    # _DEFORM_DMIG: PSID is a SUPERELEMENT id (*ELEMENT_DIRECT_MATRIX_INPUT
    # EID), not a *SET_PART id — Manual Vol I R16 p.15-3 — so the SET bucket
    # would be the wrong offset. k2rad converts no superelement keyword and the
    # writer drops the card whole, so nothing is offset here at all.
    "DAMPING_FREQUENCY_RANGE_DEFORM_DMIG": _off_damping_first_data_card([]),
    # *DAMPING_RELATIVE: PIDRB(p) field 2, PSID(s) field 3, LCID(f) field 5.
    "DAMPING_RELATIVE":
        _off_damping_first_data_card([(2, "p"), (3, "s"), (5, "f")]),
    "CONTROL_TIMESTEP": {"cards": {0: [(5, "f")]}},
}

# *ELEMENT_SHELL_{THICKNESS}_{BETA|MCID}_{OFFSET}_{DOF} and
# *ELEMENT_BEAM_{OFFSET}_{ORIENTATION} — the same generated grammar handlers.py
# registers, so the two tables cannot drift apart.
for _o1 in ("", "_THICKNESS"):
    for _o2 in ("", "_BETA", "_MCID"):
        for _o3 in ("", "_OFFSET"):
            for _o4 in ("", "_DOF"):
                _OFFSET_SPECS[f"ELEMENT_SHELL{_o1}{_o2}{_o3}{_o4}"] = \
                    _off_element_shell
for _o1 in ("", "_OFFSET"):
    for _o2 in ("", "_ORIENTATION"):
        _OFFSET_SPECS[f"ELEMENT_BEAM{_o1}{_o2}"] = _off_element_beam
for _o1 in ("", "_BETA", "_COMPOSITE"):
    _OFFSET_SPECS[f"ELEMENT_TSHELL{_o1}"] = _off_element_tshell
# *ELEMENT_SPH_{VOLUME} and *SECTION_SPH_{ELLIPSE|TENSOR|INTERACTION|USER} —
# the same spellings handlers.py registers, so the two tables cannot drift.
for _o1 in ("", "_VOLUME"):
    _OFFSET_SPECS[f"ELEMENT_SPH{_o1}"] = _off_element_sph
for _o1 in ("", "_ELLIPSE", "_TENSOR", "_INTERACTION", "_USER"):
    _OFFSET_SPECS[f"SECTION_SPH{_o1}"] = _off_section_sph
del _o1, _o2, _o3, _o4

# *PART_{OPTION1..6} (3588 spellings) and *CONSTRAINED_NODAL_RIGID_BODY_{SPC,
# INERTIA,OVERRIDE,THERMAL,TITLE} (326) — generated from the SAME functions
# handlers.py registers its dispatch keys from, so a spelling can never reach one
# table and miss the other. That pairing is the #116 lesson: the rigid-wall list
# used to be a literal here and had already fallen three spellings behind the
# registry.
for _kw in _part_option_keywords():
    _OFFSET_SPECS[_kw] = _off_part
for _kw, _cnrb_opts in _cnrb_option_keywords():
    _OFFSET_SPECS[_kw] = _off_cnrb
del _kw, _cnrb_opts

for _kw in ("CONSTRAINED_INTERPOLATION", "CONSTRAINED_INTERPOLATION_LOCAL"):
    _OFFSET_SPECS[_kw] = _off_constrained_interpolation
del _kw

#: Family prefix → rewriter for the *ELEMENT_ spellings the table does not list
#: (mirrors the *ELEMENT_ rows of handlers._PREFIX_HANDLERS). Without it every
#: unrecognized *ELEMENT_SHELL_<option> in an *INCLUDE_TRANSFORM would keep its
#: original node/part ids while the rest of the include was offset — dangling
#: connectivity, which is worse than the warning it would have produced.
#: *PART deliberately gets NO prefix row, unlike handlers._PREFIX_HANDLERS. Every
#: one of the 3588 legal spellings is registered above by name, so a keyword that
#: reaches this fallback is NOT a *PART option stacking — it is *PART_SENSOR,
#: *PART_ADD, *PART_MODES or an unlisted *PART_COMPOSITE ordering, none of which
#: has *PART's (HEADING, data) card layout. Walking those with _off_part would
#: rewrite a composite PLY card as if it were a part data card. Letting them fall
#: through to the "keyword has no offset map" warning is right: the handler side
#: warn-skips them too, so no id of theirs is read anywhere.
#: ELEMENT_TSHELL comes FIRST for the same reason it does in
#: handlers._PREFIX_HANDLERS — the match is on a token boundary, so it is not an
#: ELEMENT_SHELL spelling and needs its own row (its base card is 10 fields, not
#: 5, and its option cards are laid out differently).
#: ELEMENT_SPH likewise: its base card is four fields with a SIXTEEN-wide mass
#: cell and a NODE id in field 0, none of which the shell rewriter would get
#: right.
_ELEMENT_PREFIX_SPECS = (
    ("ELEMENT_TSHELL", _off_element_tshell),
    ("ELEMENT_SPH", _off_element_sph),
    ("ELEMENT_SHELL", _off_element_shell),
    ("ELEMENT_BEAM", _off_element_beam),
    ("ELEMENT_PLOTEL", _OFFSET_SPECS["ELEMENT_PLOTEL"]),
)

# All *RIGIDWALL_PLANAR variants share Card 1 (nsid nsidex boxid ...), and
# every spelling handlers.py registers is generated from the same source, so the
# two tables cannot drift apart — an unmapped keyword would keep its original
# NSID/BOXID while the rest of the *INCLUDE_TRANSFORM was offset. The list used
# to be a literal and had already fallen 3 spellings behind the registry.
for _kw, _ in _rwall_planar_keywords():
    _OFFSET_SPECS[_kw] = _OFFSET_SPECS["RIGIDWALL_PLANAR"]
del _kw

# *SET_<FAMILY>_ADD — Card 1 SID and EVERY member cell take IDSOFF (bucket
# "s"), because an _ADD set's members are SET ids of the same family, never
# entity ids. That is the one place an _ADD spec differs from its base
# keyword's (*SET_NODE_LIST members are NODES, "n"; *SET_SHELL members are
# ELEMENTS, "e"), and getting it wrong is invisible on any deck without an
# *INCLUDE_TRANSFORM. LS-DYNA has exactly ONE set bucket — Vol I R17
# *INCLUDE_{OPTION} Card 2b.1/2b.2 (p.27-5/27-6) gives "IDSOFF: Offset to set
# ID" and no per-family split — so every family shares this shape.
#
# Generated from state.SET_ADD_FAMILIES, the same source handlers.py registers
# the parser keys from, so the two tables cannot drift apart: a spelling that
# dispatches but has no offset spec keeps its un-offset member ids under an
# *INCLUDE_TRANSFORM while the member SETS move, and the union resolves to
# nothing.
for _family, _kw, _n, _adds, _target in SET_ADD_FAMILIES:
    _OFFSET_SPECS[_kw] = {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "s")])}
del _family, _kw, _n, _adds, _target


def _off_set_part_add(b: Block, offsets: Dict[str, int], warn) -> None:
    """*SET_PART_ADD, whose member cells can be SIGNED.

    Same shape as the generated spec above (header SID and every member cell in
    the ``IDSOFF`` bucket), plus the one thing ``_rewrite_line`` cannot do: a
    NEGATIVE cell here is not a flag encoding, it is the upper end of the
    inclusive range ``PSID[N-1] .. -PSID[N]`` (Vol I R17 p.43-57). Its
    MAGNITUDE is a part-set id and has to move with ``IDSOFF`` exactly like the
    positive start of the range — otherwise the include's sets shift and the
    range endpoint stays behind, silently selecting a different slice (or
    none). The ``*SECTION_SHELL`` QR/IRID cell is the same situation and uses
    the same sign-preserving rewriter.
    """
    soff = offsets.get("s", 0)
    raw = b.raw
    toff = _title_offset(b)               # the 80a title card carries no id
    if toff < len(raw):
        new = _rewrite_line(raw[toff], [(0, "s")], offsets)     # SID
        if new is not None:
            raw[toff] = new
    for i in range(toff + 1, len(raw)):
        if not raw[i].strip():
            continue
        new = _rewrite_line(raw[i], [(ALL, "s")], offsets)
        if new is not None:
            raw[i] = new
        for cell in range(len(_fields(raw[i], 8, 10))):
            new = _rewrite_neg_ref(raw[i], cell, soff)
            if new is not None:
                raw[i] = new


_OFFSET_SPECS["SET_PART_ADD"] = _off_set_part_add

# *SET_NODE_ADD_ADVANCED card 2b is NOT a uniform id list: it is four
# (SID, TYPE) PAIRS (Vol I R17 p.43-46), so only the EVEN cells are set ids.
# An (ALL, "s") data spec would offset every TYPE enumeration as well and turn
# a "node set" member into a "TYPE 10000002" one.
_OFFSET_SPECS["SET_NODE_ADD_ADVANCED"] = {
    "cards": {0: [(0, "s")]},
    "data": (1, [(0, "s"), (2, "s"), (4, "s"), (6, "s")]),
}

# Every *RIGIDWALL_GEOMETRIC spelling handlers.py registers — generated from
# the same source so the two tables cannot drift apart (an unmapped keyword
# would keep its original NSID/BOXID/LCID while the rest of the include is
# offset, i.e. dangling or colliding references).
for _kw, _ in _rwall_geometric_keywords():
    _OFFSET_SPECS[_kw] = _off_rigidwall_geometric
del _kw

# The PRELOAD / INITIAL-STATE batch. Keyed off the SAME dict handlers.py
# registers from, and asserted equal by tests/test_preload_inistate.py, so a
# spelling cannot be readable and un-offsettable at the same time (#116).
#
# Buckets, from Vol I R17 pp.2979-2980 (*INCLUDE_TRANSFORM Card 2b.1):
#   ISSID   the card's own id, in no named list          -> IDROFF  "r"
#   CSID    "...and CROSS SECTION ID (see *DATABASE_CROSS_SECTION)" named
#           under IDPOFF                                  -> IDPOFF  "p"
#   LCID    "Offset to function ID, table ID, curve ID"   -> IDFOFF  "f"
#   PSID    *SET_PART / BSID *SET_BEAM                    -> IDSOFF  "s"
#   VID     "any ID defined through *DEFINE, except the FUNCTION, TABLE and
#           CURVE options"                                -> IDDOFF  "d"
#   ISTIFF  a curve id in BOTH spellings (Vol I R17 p.3144): "GT.0: Load curve
#           ID defining stiffness fraction as a function of time" and "LT.0:
#           |ISTIFF| is the load curve ID for the stiffness fraction as a
#           function of time" — the sign selects only whether the preload
#           stress is auto-adjusted +/-10%, not what the number means. So the
#           field is a SIGNED curve id like *SECTION_SHELL QR/IRID -> IDFOFF "f"
#           _rewrite_line touches only v > 0, so the POSITIVE spelling is
#           offset (correct) and the NEGATIVE one is left as written (which
#           would be wrong if the cell were emitted). It is deliberately not
#           routed through _rewrite_neg_ref because the writer DROPS ISTIFF
#           entirely (no /PRELOAD slot at any Radioss version), so neither
#           spelling reaches the emitted deck — the value only appears in the
#           warning that names it, which says for LT.0 that the id is quoted
#           un-offset.
#   IZSHEAR / KBEND / SCALE   not ids, absent from the mods lists
#   EID (*INITIAL_STRAIN_SHELL) element                   -> IDEOFF  "e"
#   SID (*INITIAL_STRAIN_SHELL_SET) *SET_SHELL            -> IDSOFF  "s"
#
# *INITIAL_AXIAL_FORCE_BEAM takes a "data" walk, not a single card: LS-DYNA
# allows the card to repeat under one keyword and the handler reads every
# non-blank row, so a {"cards": {0: ...}} spec would offset the first bolt and
# leave the rest pointing at the parent deck's sets.
_INITIAL_STATE_PRELOAD_OFFSETS = {
    "INITIAL_STRESS_SECTION": {
        "cards": {0: [(0, "r"), (1, "p"), (2, "f"), (3, "s"), (4, "d"),
                      (6, "f")]}},
    "INITIAL_AXIAL_FORCE_BEAM": {"data": (0, [(0, "s"), (1, "f")])},
    "INITIAL_STRAIN_SHELL": _off_initial_strain_shell,
    "INITIAL_STRAIN_SHELL_SET": _off_initial_strain_shell_set,
    "INITIAL_STRESS_SHELL": _off_initial_stress_shell,
    "INITIAL_STRESS_SOLID": _off_initial_stress_solid,
}
# Keyed off the handler registry, so adding a spelling there without an offset
# spec here is an ImportError, not a silent un-offset include.
for _kw in INITIAL_STATE_PRELOAD_KEYWORDS:
    _OFFSET_SPECS[_kw] = _INITIAL_STATE_PRELOAD_OFFSETS[_kw]
del _kw

# The RARE MATERIALS batch. Keyed off the SAME dict handlers.py registers from,
# and asserted equal by tests/test_rare_materials.py, so a spelling cannot be
# readable and un-offsettable at the same time (#116).
#
# Buckets, from Vol I R17 pp.2979-2980 (*INCLUDE_TRANSFORM Card 2b.1) and the
# cfg's own HCDI types (include_transform.cfg:64-78):
#   *MAT_030 / *MAT_156 / *MAT_S15 MID   MATS   -> IDMOFF "m"
#   *MAT_030 SIG_* (negative), LCSS,
#     LCSSC, LCID_AS, LCID_SA            FUNCT  -> IDFOFF "f"
#   *MAT_156 ALM SFR SVS SVR SSP (neg)   FUNCT  -> IDFOFF "f"
#   *MAT_S15 SV A TL TV FPE (negative)   CURVE  -> IDFOFF "f" (same HCDI type
#                                        HCDI_OBJ_TYPE_CURVES, mv_type.cpp:93)
#   *MAT_ADD_THERMAL_EXPANSION field 1 (PID)  COMPONENT -> IDPOFF "p" when
#                                        GT.0; its LT.0 form makes |PID| a
#                                        MATERIAL id -> IDMOFF, sign preserved
#                                        (_rewrite_neg_ref)
#   its LCID / LCIDY / LCIDZ             FUNCT  -> IDFOFF "f"
#   *MAT_THERMAL_ISOTROPIC TMID          "material ID"           -> IDMOFF "m"
#   *PART TMID                           idem (already in _off_part)
#   *SECTION_SHELL_THERMAL option-card TMID                      -> IDMOFF "m"
#   *INITIAL_TEMPERATURE_SET NSID,
#     *BOUNDARY_TEMPERATURE_SET NSID,
#     *LOAD_THERMAL_{CONSTANT,VARIABLE} NSID / NSIDEX   SETS     -> IDSOFF "s"
#   the _NODE spellings' NID                          NODES      -> IDNOFF "n"
#   *BOUNDARY_TEMPERATURE TLCID, *LOAD_THERMAL_* LCID / LCIDDR / LCIDE /
#     LCIDR / LCIDEDR, *MAT_THERMAL_ISOTROPIC TGRLC   CURVES     -> IDFOFF "f"
#   *LOAD_THERMAL_{CONSTANT,VARIABLE} BOXID (*DEFINE_BOX)        -> IDDOFF "d"
_RARE_MATERIAL_OFFSETS = {
    "MAT_SHAPE_MEMORY":  _off_mat_shape_memory,
    "MAT_030":           _off_mat_shape_memory,
    "MAT_30":            _off_mat_shape_memory,
    "MAT_MUSCLE":        _off_mat_muscle,
    "MAT_156":           _off_mat_muscle,
    "MAT_SPRING_MUSCLE": _off_mat_spring_muscle,
    "MAT_S15":           _off_mat_spring_muscle,
    # The card repeats under one keyword, and its field 0 lives in two id
    # namespaces by SIGN — hence a callable, not a "data" walk.
    "MAT_ADD_THERMAL_EXPANSION": _off_mat_add_thermal_expansion,
    "MAT_THERMAL_ISOTROPIC": {"cards": {0: [(0, "m"), (2, "f")]}},
    "SECTION_SHELL_THERMAL": _off_section_shell,
    # Every *LOAD_THERMAL_* spelling REPEATS ("Include as many cards/sets ...
    # as desired"), so all five take a repeating walk. A {"cards": {0: ...}}
    # spec would offset the FIRST row only and leave every later NID / LCID
    # pointing at the parent deck (the same hole the handler had).
    "INITIAL_TEMPERATURE_SET":   {"data": (0, [(0, "s")])},
    "INITIAL_TEMPERATURE_NODE":  {"data": (0, [(0, "n")])},
    "BOUNDARY_TEMPERATURE_SET":  {"data": (0, [(0, "s"), (1, "f")])},
    "BOUNDARY_TEMPERATURE_NODE": {"data": (0, [(0, "n"), (1, "f")])},
    "LOAD_THERMAL_CONSTANT":      _off_load_thermal_sets,
    "LOAD_THERMAL_CONSTANT_NODE": {"data": (0, [(0, "n")])},
    "LOAD_THERMAL_LOAD_CURVE":    {"data": (0, [(0, "f"), (1, "f")])},
    "LOAD_THERMAL_VARIABLE":      _off_load_thermal_sets,
    "LOAD_THERMAL_VARIABLE_NODE": {"data": (0, [(0, "n"), (3, "f")])},
    # ── THERMAL SOLVER batch ───────────────────────────────────────────────
    #   *BOUNDARY_{FLUX,CONVECTION,RADIATION}_SET SSID and PSEROD (a PART SET,
    #     Vol I R17 p.5-47/5-31/5-122)                             -> IDSOFF "s"
    #   the _SEGMENT spellings' N1..N4                             -> IDNOFF "n"
    #   their card-2 curve cells (LCID / HLCID+TLCID / FLCID+TLCID), each with
    #     an LT.0 = "a curve of TEMPERATURE" form, sign preserved  -> IDFOFF "f"
    #   *MAT_THERMAL_{ORTHOTROPIC,ISOTROPIC_TD,ISOTROPIC_TD_LC} TMID -> IDMOFF
    #     ("thermal material identification ... see *PART" — it is defined on a
    #     *MAT_ card, so IDMOFF is the only consistent bucket, and *PART's TMID
    #     and *SECTION_SHELL_THERMAL's TMID already move with it)
    #   their TGRLC (sign preserving) and _TD_LC's HCLC/TCLC      -> IDFOFF "f"
    #     (the three *HSV cells select a mechanical history variable BY INDEX
    #     and are not ids of any class — deliberately not offset)
    #   *LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_<F> EID          -> IDEOFF "e"
    #   *LOAD_THERMAL_VARIABLE_ELEMENT_<F> LCID                    -> IDFOFF "f"
    **{kw: _off_boundary_thermal_bc for kw in (
        "BOUNDARY_FLUX", "BOUNDARY_FLUX_SET", "BOUNDARY_FLUX_SEGMENT",
        "BOUNDARY_CONVECTION", "BOUNDARY_CONVECTION_SET",
        "BOUNDARY_CONVECTION_SEGMENT",
        "BOUNDARY_RADIATION", "BOUNDARY_RADIATION_SET",
        "BOUNDARY_RADIATION_SEGMENT")},
    "MAT_THERMAL_ORTHOTROPIC":     _off_mat_thermal_ortho,
    "MAT_T02":                     _off_mat_thermal_ortho,
    "MAT_THERMAL_ISOTROPIC_TD":    _off_mat_thermal_td,
    "MAT_T03":                     _off_mat_thermal_td,
    "MAT_THERMAL_ISOTROPIC_TD_LC": _off_mat_thermal_td,
    "MAT_T10":                     _off_mat_thermal_td,
    "MAT_T01":                     {"cards": {0: [(0, "m"), (2, "f")]}},
    # Both element-temperature families REPEAT ("Include as many cards in this
    # format as desired", Vol I R17 pp.33-168/33-184), so a {"cards": {0: ...}}
    # spec would offset the FIRST row only.
    **{kw: {"data": (0, [(0, "e")])} for kw in (
        "LOAD_THERMAL_CONSTANT_ELEMENT",
        "LOAD_THERMAL_CONSTANT_ELEMENT_BEAM",
        "LOAD_THERMAL_CONSTANT_ELEMENT_SHELL",
        "LOAD_THERMAL_CONSTANT_ELEMENT_SOLID",
        "LOAD_THERMAL_CONSTANT_ELEMENT_TSHELL")},
    **{kw: {"data": (0, [(0, "e"), (3, "f")])} for kw in (
        "LOAD_THERMAL_VARIABLE_ELEMENT",
        "LOAD_THERMAL_VARIABLE_ELEMENT_BEAM",
        "LOAD_THERMAL_VARIABLE_ELEMENT_SHELL",
        "LOAD_THERMAL_VARIABLE_ELEMENT_SOLID",
        "LOAD_THERMAL_VARIABLE_ELEMENT_TSHELL")},
    # Recognized + warn-dropped keywords get NO offset spec, deliberately: an
    # unmodelled card stack must not have its cells rewritten by position (the
    # *AIRBAG warn-drop rule). That covers every *BOUNDARY_RADIATION_*VF*
    # spelling, *BOUNDARY_FLUX_TRAJECTORY, *MAT_THERMAL_CWM, the four
    # *LOAD_THERMAL_VARIABLE_{BEAM,SHELL}[_SET] gradient cards and
    # *CONTROL_THERMAL_{FORMING,EIGENVALUE}.
    #
    # *CONTROL_THERMAL_{SOLVER,TIMESTEP,NONLINEAR} and *CONTROL_SOLUTION are
    # PARSED but carry no offset spec either, and that is a verdict, not a gap:
    # *INCLUDE_TRANSFORM offsets ENTITY ids, and a *CONTROL_ card's cells are
    # solver settings. The two curve-bearing cases — *CONTROL_THERMAL_SOLVER's
    # LT.0 EQHEAT/TSF and *CONTROL_THERMAL_TIMESTEP's LT.0 TMIN/TMAX/DTEMP plus
    # LCTS — are all cells k2rad DROPS by name, so rewriting them would move an
    # id nothing reads while making the include's own copy of the card differ
    # from the deck's. (If either ever converts, its row belongs here.)
}
_RARE_MATERIAL_OFFSETS.update(
    {kw: None for kw in RARE_MATERIAL_KEYWORDS
     if kw not in _RARE_MATERIAL_OFFSETS})
for _kw in RARE_MATERIAL_KEYWORDS:
    _spec = _RARE_MATERIAL_OFFSETS[_kw]     # KeyError = a spelling with no
    if _spec is not None:                   # verdict, never a silent gap
        _OFFSET_SPECS[_kw] = _spec
del _kw, _spec

# The RARE CARDS batch. Keyed off the SAME dict handlers.py registers from, and
# asserted equal by tests/test_rare_cards.py, so a spelling cannot be readable
# and un-offsettable at the same time (#116).
#
# Buckets, from Vol I R17 pp.2979-2980 (*INCLUDE_TRANSFORM Card 2b.1) — quoted
# verbatim where the assignment is not obvious:
#   *DEFINE_ELEMENT_DEATH_<F>      EID    "Offset to element ID"   -> IDEOFF "e"
#   *DEFINE_ELEMENT_DEATH_<F>_SET  SID    "Offset to set ID"       -> IDSOFF "s"
#     BOXID (*DEFINE_BOX) and CID (*DEFINE_COORDINATE_*): "any ID defined
#     through *DEFINE, except the FUNCTION, TABLE, and CURVE options"
#                                                                  -> IDDOFF "d"
#     IDGRP is a bare GROUPING TAG, not an entity id of any listed class, and
#     grouping is by EQUALITY: "There is no requirement that each
#     *DEFINE_ELEMENT_DEATH command have a unique IDGRP ... elements in a
#     single group can come from multiple *DEFINE_ELEMENT_DEATH commands"
#     (p.17-252). Offsetting it and not offsetting it are equally consistent
#     WITHIN one include; leaving it alone is what keeps an include's group
#     tags matching each other, which is the only relation the field has.
#     It is deliberately absent from the mods list — and it reaches no emitted
#     card either, being warn-dropped by writer/rarecards.py.
#   *DEFINE_CURVE_SMOOTH LCID     "Offset to function ID, table ID, and curve
#     ID" — IDFOFF even though the keyword is a *DEFINE_, because IDDOFF
#     explicitly EXCLUDES "the FUNCTION, TABLE, and CURVE options"
#                                                                  -> IDFOFF "f"
#     SIDR is a flag, not an id.
#   *PERTURBATION_NODE NSID (a *SET_NODE)                          -> IDSOFF "s"
#     CID (*DEFINE_COORDINATE_NODES)                               -> IDDOFF "d"
#     RND on the TYPE=4 card is a random SEED, not an id.
#   *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY BPFGID ("ID for this set of imposed
#     boundary conditions" — in none of the seven named classes, so the
#     catch-all)                                                   -> IDROFF "r"
#     LCIDF and the per-row LCID                                   -> IDFOFF "f"
#     row NID > 0                                                  -> IDNOFF "n"
#     row NID < 0 (|NID| is a *SET_NODE, sign preserved)           -> IDSOFF "s"
#   *INTERFACE_SPRINGBACK_* PSID (a *SET_PART)                     -> IDSOFF "s"
#     Card-4 NID                                                   -> IDNOFF "n"
#
# All five take a callable rather than a declarative spec, for four different
# reasons — see each walker's docstring: the death cards are the only ones a
# flat "cards" spec would fit, and they use one so the _SET/plain bucket split
# stays beside the family table it belongs to.
def _off_element_death(b: Block, offsets: Dict[str, int], warn,
                       is_set: bool = False) -> None:
    """*DEFINE_ELEMENT_DEATH_<FAMILY>[_SET] card 1, the only card there is."""
    toff = _title_offset(b)
    if toff >= len(b.raw) or not b.raw[toff].strip():
        return
    new = _rewrite_line(b.raw[toff],
                        [(0, "s" if is_set else "e"), (2, "d"), (5, "d")],
                        offsets)
    if new is not None:
        b.raw[toff] = new


def _off_element_death_set(b: Block, offsets: Dict[str, int], warn) -> None:
    _off_element_death(b, offsets, warn, is_set=True)


_RARE_CARD_OFFSETS = {
    **{f"DEFINE_ELEMENT_DEATH_{_o}":
       (_off_element_death_set if _o.endswith("_SET") else _off_element_death)
       for _o in ("SOLID", "SOLID_SET", "BEAM", "BEAM_SET", "SHELL",
                  "SHELL_SET", "THICK_SHELL", "THICK_SHELL_SET")},
    "DEFINE_CURVE_SMOOTH": {"cards": {0: [(0, "f")]}},
    "PERTURBATION_NODE": _off_perturbation_node,
    "BOUNDARY_PRESCRIBED_FINAL_GEOMETRY":
        _off_boundary_prescribed_final_geometry,
    "INTERFACE_SPRINGBACK_LSDYNA": _off_interface_springback,
    "INTERFACE_SPRINGBACK_LSDYNA_NOTHICKNESS": _off_interface_springback,
    # Recognized + warn-dropped keywords get NO offset spec, deliberately: an
    # unmodelled card stack must not have its cells rewritten by position (the
    # *AIRBAG warn-drop rule).
}
_RARE_CARD_OFFSETS.update(
    {kw: None for kw in RARE_CARD_KEYWORDS
     if kw not in _RARE_CARD_OFFSETS})
for _kw in RARE_CARD_KEYWORDS:
    _spec = _RARE_CARD_OFFSETS[_kw]         # KeyError = a spelling with no
    if _spec is not None:                   # verdict, never a silent gap
        _OFFSET_SPECS[_kw] = _spec
del _kw, _spec

# All CONTACT_* handled by k2rad share the Card-1 (ssid msid sstyp mstyp
# sboxid mboxid) layout; unlisted CONTACT_ variants fall to the unmapped warn.
for _kw in (
    "CONTACT_AUTOMATIC_SINGLE_SURFACE", "CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR",
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
    "CONTACT_AUTOMATIC_GENERAL", "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE",
    "CONTACT_FORCE_TRANSDUCER_PENALTY", "CONTACT_FORCE_TRANSDUCER",
    "CONTACT_TIED_NODES_TO_SURFACE", "CONTACT_TIED_NODES_TO_SURFACE_OFFSET",
    "CONTACT_TIED_NODES_TO_SURFACE_CONSTRAINED_OFFSET",
    "CONTACT_TIED_SURFACE_TO_SURFACE", "CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET",
    "CONTACT_TIED_SURFACE_TO_SURFACE_CONSTRAINED_OFFSET",
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE",
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE_OFFSET",
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE_BEAM_OFFSET",
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE_CONSTRAINED_OFFSET",
    # *CONTACT_AIRBAG_SINGLE_SURFACE writes SSID in the same cols 1-10 and
    # SBOX in the same cols 41-50 — its card is the two-sided grid with the
    # B-side cells left blank, which is exactly why it can share the handler
    # (see handle_contact_airbag_single_surface). _off_contact only touches
    # the id cells, and a blank one is left alone, so the interleaved blanks
    # are harmless. The _MPP spelling is excluded for the reason the spotweld
    # and eroding ones are: the MPP card pushes card 1 down a line.
    "CONTACT_AIRBAG_SINGLE_SURFACE",
):
    _OFFSET_SPECS[_kw] = _off_contact

# *CONTACT_SPOTWELD{...} shares that Card-1 layout too — but only when the _MPP
# card is absent, because _MPP pushes Card 1 down by one (or two) lines and
# _off_contact rewrites b.raw[start] blind. The spellings are taken from the
# handler's own generated grammar so the two lists cannot drift apart; the _MPP
# ones are deliberately left out and fall to the unmapped warn rather than
# silently offsetting the MPP bucket parameters as if they were SSID/MSID.
for _kw in _SPOTWELD_CONTACT_KEYWORDS:
    if "_MPP" not in _kw:
        _OFFSET_SPECS[_kw] = _off_contact

# *CONTACT_ERODING_* and *CONTACT_{,AUTOMATIC_}NODES_TO_SURFACE share the same
# Card-1 layout. Their mandatory ERODING Card 4 (ISYM/EROSOP/IADJ) sits AFTER
# Card 1, so _off_contact — which only rewrites b.raw[start] — is unaffected by
# it. The _MPP spellings are excluded for the same reason the spotweld ones are:
# the MPP card(s) push Card 1 down and _off_contact rewrites that line blind.
for _kw in _TYPE25_CONTACT_BASES:
    _OFFSET_SPECS[_kw] = _off_contact

# *CONTACT_..._TIEBREAK — from the SAME generator the dispatch table uses
# (handlers.TIEBREAK_CONTACT_KEYWORDS), so the two tables cover exactly the same
# set and a test can assert it. The mandatory Card 4 sits AFTER Card 1, so
# _off_contact — which rewrites b.raw[start] only — is unaffected by it.
#
# The _MPP spellings are excluded for the reason the spotweld and eroding ones
# are: the MPP card pushes Card 1 down a line and _off_contact rewrites that
# line blind.
#
# NOTE on Card-4 curve ids: OPTION 5 makes SFLS a *DEFINE_CURVE id, OPTION
# +-9/+-11 make a NEGATIVE NFLS/SFLS one, OPTION 13/14 carry LCG1C/LCG2C and
# the TIEBREAK_SURFACE family carries TBLCID — all IDFOFF ("f") cells that
# _off_contact does not touch. Every one of those OPTION classes is a named
# warn-drop in the writer (no rupture card is built from them), so no converted
# output depends on those ids today; honouring one would need a Card-4 walker,
# not this flat Card-1 rewriter.
for _kw in TIEBREAK_CONTACT_KEYWORDS:
    if "_MPP" not in _kw:
        _OFFSET_SPECS[_kw] = _off_contact

# *DEFINE_HEX_SPOTWELD_ASSEMBLY{_N} — the _TITLE spelling parses to the bare
# keyword with TITLE in options, so the base entry covers it.
# *MAT_SIMPLIFIED_RUBBER/FOAM{_WITH_FAILURE}{_LOG_LOG_INTERPOLATION} and
# *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE{_LOG_LOG_INTERPOLATION} — the same
# generated grammar handlers.py registers, so the two tables cannot drift.
# 181 needs the callable (the unloading card's index moves with _WITH_FAILURE);
# 183's three cards are fixed, so LC (card 2 field 4) and LCUNLD (card 3 field
# 1) take a static spec.
for _base in ("MAT_SIMPLIFIED_RUBBER/FOAM", "MAT_SIMPLIFIED_RUBBER",
              "MAT_SIMPLIFIED_RUBBER_FOAM", "MAT_181"):
    for _o1 in ("", "_WITH_FAILURE"):
        for _o2 in ("", "_LOG_LOG_INTERPOLATION"):
            _OFFSET_SPECS[f"{_base}{_o1}{_o2}"] = _off_mat_181
for _base in ("MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE", "MAT_183"):
    for _o2 in ("", "_LOG_LOG_INTERPOLATION"):
        _OFFSET_SPECS[f"{_base}{_o2}"] = _mat({1: [(3, "f")], 2: [(0, "f")]})
del _base, _o1, _o2

# *MAT_240{_THERMAL|_3MODES|_FUNCTIONS|_THERMAL_3MODES|_FUNCTIONS_3MODES} —
# the same generated grammar handlers.py registers. Cells are curve ids per
# SPELLING: the base card only carries LCG1C/LCG2C (cards 2/3 field 8);
# _THERMAL/_FUNCTIONS additionally turn EMOD/GMOD (card 1 fields 5/6) and
# G*C_0/T0|S0/FG* (cards 2/3 fields 1/4/7) into function ids; _3MODES adds a
# mode-III card with the same shape (its LCG3C — and under THERMAL its
# G3C_0/R0/FG3 — plus the GMOD3 card). The handler warn-skips the variants,
# but the include-transform rewrite must still move their ids so the warning
# and any hand-recovery see the post-offset deck consistently.
_MAT240_CURVE_CELLS = {
    "":                  {1: [(7, "f")], 2: [(7, "f")]},
    "_3MODES":           {1: [(7, "f")], 2: [(7, "f")], 3: [(7, "f")]},
    "_THERMAL":          {0: [(4, "f"), (5, "f")],
                          1: [(0, "f"), (3, "f"), (6, "f"), (7, "f")],
                          2: [(0, "f"), (3, "f"), (6, "f"), (7, "f")]},
    "_THERMAL_3MODES":   {0: [(4, "f"), (5, "f")],
                          1: [(0, "f"), (3, "f"), (6, "f"), (7, "f")],
                          2: [(0, "f"), (3, "f"), (6, "f"), (7, "f")],
                          3: [(0, "f"), (3, "f"), (6, "f"), (7, "f")],
                          4: [(0, "f")]},
}
_MAT240_CURVE_CELLS["_FUNCTIONS"] = _MAT240_CURVE_CELLS["_THERMAL"]
_MAT240_CURVE_CELLS["_FUNCTIONS_3MODES"] = _MAT240_CURVE_CELLS["_THERMAL_3MODES"]
for _base in ("MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE", "MAT_240"):
    for _opt, _cells in _MAT240_CURVE_CELLS.items():
        _OFFSET_SPECS[f"{_base}{_opt}"] = _mat(_cells)
del _base, _opt, _cells

# *AIRBAG_* — generated from the same dicts handlers.py dispatches on, so a
# model cannot be readable and un-offsettable. The UNCONVERTED models are
# deliberately left out: their card stacks are not modelled, so a blind rewrite
# of "card 1 field 0" could land on something else entirely, and an unmapped
# keyword warns rather than corrupting ids. The batch-2 OPTION stacks are
# generated from _AIRBAG_OPTION_STACKS, the same product the dispatch table
# uses, so every readable spelling is also offsettable.
for _kw in _AIRBAG_MODELS:
    for _sfx in _AIRBAG_LEGACY_SUFFIXES:
        _OFFSET_SPECS[_kw + _sfx] = _off_airbag
for _kw, _stack in _AIRBAG_OPTION_STACKS.items():
    for _combo in _product(*_stack):
        for _sfx in _AIRBAG_LEGACY_SUFFIXES:
            _OFFSET_SPECS[_kw + "".join(_combo) + _sfx] = _off_airbag
for _sfx in _AIRBAG_LEGACY_SUFFIXES:
    _OFFSET_SPECS["AIRBAG_INTERACTION" + _sfx] = _off_airbag_interaction

# ── Seatbelts / restraints ─────────────────────────────────────────────────
#
# Generated from the SAME dict handlers.py dispatches on (#116), so a spelling
# cannot be readable by the handler and invisible to this table. An unmapped
# seatbelt keyword inside an *INCLUDE_TRANSFORM keeps its original element,
# node, part, sensor and curve ids while everything around it moves — the belt
# then hangs off nodes that are no longer there, or, worse, off the wrong ones.
# MEASURED on master before this batch: every one of the eleven seatbelt
# keywords hit the "keyword has no offset map" fallback while the *PART beside
# them WAS offset (/PART/3900 -> mat 4900 on IDPOFF 3000 / IDMOFF 4000), so the
# SECID would have needed +IDROFF and the belt eids +IDEOFF and neither moved.
_SEATBELT_OFFSET_WALKERS = {
    "": _off_element_seatbelt,
    "_ACCELEROMETER": _off_seatbelt_accelerometer,
    "_SLIPRING": _off_seatbelt_slipring,
    "_RETRACTOR": _off_seatbelt_retractor,
    "_PRETENSIONER": _off_seatbelt_pretensioner,
    "_SENSOR": _off_seatbelt_sensor,
}
assert set(_SEATBELT_OFFSET_WALKERS) == set(_SEATBELT_SUBKEYWORDS), (
    "handlers._SEATBELT_SUBKEYWORDS and assembly._SEATBELT_OFFSET_WALKERS "
    "must cover the SAME spellings")
for _sfx, _walk in _SEATBELT_OFFSET_WALKERS.items():
    _OFFSET_SPECS["ELEMENT_SEATBELT" + _sfx] = _walk
_OFFSET_SPECS["SECTION_SEATBELT"] = _off_section_seatbelt
for _kw in _SEATBELT_MAT_KEYWORDS:
    # MID on card 1 field 0, LLCID on field 2 and ULCID on field 3 (curves).
    # Cards 2-4 carry no ids at all — A/I/J/AS/F/M/R and the _2D coating and
    # weft data are every one of them a plain value.
    _OFFSET_SPECS[_kw] = _mat({0: [(2, "f"), (3, "f")]})
del _sfx, _walk, _stack, _combo
for _r in range(4):
    for _combo in _permutations(("_BIRTH", "_RDT", "_ID"), _r):
        if _combo and _combo[-1] == "_ID":
            continue
        _OFFSET_SPECS["AIRBAG_REFERENCE_GEOMETRY" + "".join(_combo)] = \
            _off_airbag_ref_geometry
for _r in range(3):
    for _combo in _permutations(("_RDT", "_ID"), _r):
        if _combo and _combo[-1] == "_ID":
            continue
        _OFFSET_SPECS["AIRBAG_SHELL_REFERENCE_GEOMETRY" + "".join(_combo)] = \
            _off_airbag_shell_ref_geometry
del _kw, _r, _combo

_OFFSET_SPECS["DEFINE_HEX_SPOTWELD_ASSEMBLY"] = _off_hex_spotweld_assembly
for _n in range(1, 17):
    _OFFSET_SPECS[f"DEFINE_HEX_SPOTWELD_ASSEMBLY_{_n}"] = _off_hex_spotweld_assembly
del _n

#: Keywords that genuinely carry no offsetable ids — silently left alone.
_NO_ID_KEYWORDS = frozenset({
    "KEYWORD", "TITLE", "END", "COMMENT",
    "CONTROL_TERMINATION", "CONTROL_ACCURACY", "CONTROL_CONTACT",
    "CONTROL_CPU", "CONTROL_ENERGY", "CONTROL_HOURGLASS", "CONTROL_OUTPUT",
    "CONTROL_SHELL", "CONTROL_SOLID", "CONTROL_ALE", "CONTROL_ADAPTIVE",
    "CONTROL_BULK_VISCOSITY", "CONTROL_DYNAMIC_RELAXATION",
    "CONTROL_MPP_DECOMPOSITION", "CONTROL_UNITS", "CONTROL_IMPLICIT_GENERAL",
    "CONTROL_IMPLICIT_SOLUTION", "CONTROL_IMPLICIT_AUTO",
    "CONTROL_IMPLICIT_DYNAMICS", "CONTROL_IMPLICIT_EIGENVALUE",
    "DATABASE_ELOUT", "DATABASE_GLSTAT", "DATABASE_ABSTAT",
    "DATABASE_BINARY_D3THDT", "DATABASE_BINARY_INTFOR", "DATABASE_DEFORC",
    "DATABASE_DISBOUT",
    "DATABASE_EXTENT_BINARY", "DATABASE_JNTFORC", "DATABASE_MATSUM",
    "DATABASE_NODOUT", "DATABASE_RCFORC", "DATABASE_RWFORC",
    "DATABASE_SECFORC", "DATABASE_SLEOUT", "DATABASE_SPCFORC",
    "DATABASE_NCFORC", "DATABASE_RBDOUT", "DATABASE_BINARY_D3DRLF",
    "DATABASE_BINARY_D3DUMP", "DATABASE_BINARY_BLSTFOR",
    "DATABASE_BINARY_RUNRSF",
    # The output-parity batch. *DATABASE_BNDOUT / _NODFOR / _TPRINT carry only
    # DT / BINARY / LCUR / IOOPT — the OPTION1..4 columns of the *DATABASE_
    # card apply to bndout/nodout/elout as PRINT flags, not as ids (Vol I R16
    # p.16-7). *CONTROL_PARALLEL is NCPU / NUMRHS / CONST / PARA, all counts
    # and flags. Nothing on any of the four is offsetable.
    "DATABASE_BNDOUT", "DATABASE_NODFOR", "DATABASE_TPRINT",
    "CONTROL_PARALLEL",
    # *DATABASE_SBTOUT is the standard *DATABASE_OPTION card - DT, BINARY,
    # LCUR, IOOPT - and carries no id at all. (LCUR is an OUTPUT-INTERVAL curve
    # k2rad does not read on any *DATABASE_ card, so it is not offset here
    # either; every one of the cards above is in this set for the same reason.)
    "DATABASE_SBTOUT",
})

#: Coordinate/point-bearing keywords other than *NODE: literal geometry that a
#: TRANID transform SHOULD move but k2rad does not (phase-1 scope) — loud warn.
_POINT_BEARING = frozenset({
    "DEFINE_COORDINATE_SYSTEM", "DEFINE_VECTOR", "DEFINE_BOX",
    "DEFINE_BOX_LOCAL", "INITIAL_DETONATION", "LOAD_BLAST_ENHANCED",
    "LOAD_BLAST", "DATABASE_CROSS_SECTION_PLANE", "DEFINE_TRANSFORMATION",
    "INITIAL_VOLUME_FRACTION_GEOMETRY",
    # Stress-free reference coordinates (→ /XREF): literal geometry that the
    # include affine does not rewrite (only the node IDS are offset).
    "INITIAL_FOAM_REFERENCE_GEOMETRY", "INITIAL_FOAM_REFERENCE_GEOMETRY_RAMP",
    # The airbag twin: *AIRBAG_REFERENCE_GEOMETRY rows are node id +
    # reference X/Y/Z, literal geometry the include affine does not
    # rewrite (only the node IDS are offset). Every option permutation is
    # listed, generated below this frozenset. *AIRBAG_SHELL_REFERENCE_
    # GEOMETRY is NOT point-bearing: its rows are ids only, and the ghost
    # nodes it names carry their coordinates in *NODE, which IS moved.
})
#: Direction/tensor-bearing keywords: valid under pure translation, wrong
#: under rotation/mirror/scale — warned only when the linear part is not I.
_DIRECTION_BEARING = frozenset({
    "DEFINE_COORDINATE_VECTOR", "DEFINE_SD_ORIENTATION", "INITIAL_VELOCITY",
    "INITIAL_VELOCITY_NODE", "INITIAL_VELOCITY_RIGID_BODY",
    "INITIAL_VELOCITY_GENERATION", "BOUNDARY_PRESCRIBED_MOTION_RIGID",
    "BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL",
    "BOUNDARY_PRESCRIBED_MOTION_SET", "BOUNDARY_PRESCRIBED_MOTION_SET_BOX",
    "BOUNDARY_PRESCRIBED_MOTION_NODE",
    "LOAD_NODE_POINT", "LOAD_NODE_SET", "LOAD_BODY_X", "LOAD_BODY_Y",
    "LOAD_BODY_Z", "INITIAL_STRESS_SHELL", "INITIAL_STRESS_SOLID",
    # The strain twin: EPSxx..EPSzx is a GLOBAL cartesian TENSOR (Vol I R17
    # p.3121), so a rotating TRANID makes every component wrong while the
    # element ids it names move correctly.
    "INITIAL_STRAIN_SHELL", "INITIAL_STRAIN_SHELL_SET",
    "BOUNDARY_SPC_SET", "BOUNDARY_SPC_NODE", "BOUNDARY_SPC",
    # *LOAD_BODY_RX/RY/RZ carry BOTH a direction (the rotation axis, which the
    # include's linear part must rotate) and a literal axis POINT (XC/YC/ZC,
    # which even a pure translation must move) — the second half is reported by
    # _carries_literal_axis_point below. *LOAD_BODY_VECTOR carries V1/V2/V3 on
    # its second card.
    "LOAD_BODY_RX", "LOAD_BODY_RY", "LOAD_BODY_RZ", "LOAD_BODY_VECTOR",
})

# Every *AIRBAG_REFERENCE_GEOMETRY option permutation is point-bearing — the
# option order in the keyword is arbitrary, so the set is generated from the
# same grammar handlers.py and _OFFSET_SPECS use.
_POINT_BEARING = _POINT_BEARING | frozenset(
    "AIRBAG_REFERENCE_GEOMETRY" + "".join(combo)
    for r in range(4)
    for combo in _permutations(("_BIRTH", "_RDT", "_ID"), r)
    if not (combo and combo[-1] == "_ID"))


# ─────────────────────────────────────────────────────────────────────────────
# Offset application
# ─────────────────────────────────────────────────────────────────────────────

def _offset_block(b: Block, spec, offsets: Dict[str, int], warn) -> None:
    if callable(spec):
        spec(b, offsets, warn)
        return
    w = spec.get("w", 10)
    toff = _title_offset(b)
    raw = b.raw
    if toff and "ID" in b.options and spec.get("idhdr") and raw:
        new = _rewrite_id_header(raw[0], offsets.get(spec["idhdr"], 0))
        if new is not None:
            raw[0] = new
    for ci, mods in spec.get("cards", {}).items():
        idx = toff + ci
        if idx < len(raw) and raw[idx].strip():
            new = _rewrite_line(raw[idx], mods, offsets, w)
            if new is not None:
                raw[idx] = new
    data = spec.get("data")
    if data:
        start, mods = data
        stride = spec.get("stride", 1)
        # "data_w": field width of the DATA cards when it differs from the
        # header cards' (the *DEFINE_TABLE family: I10 header, but E20.0
        # point cards — slicing those at w=10 would land field 1 INSIDE the
        # VALUE and corrupt it while leaving the real id untouched).
        wd = spec.get("data_w", w)
        for idx in range(toff + start, len(raw), stride):
            if raw[idx].strip():
                new = _rewrite_line(raw[idx], mods, offsets, wd)
                if new is not None:
                    raw[idx] = new


def _apply_offsets(p: PendingInclude, warn) -> None:
    unmapped: Set[str] = set()
    for b in p.sub_blocks:
        kw = b.keyword
        spec = _OFFSET_SPECS.get(kw)
        if spec is None:
            # Token boundary, not a bare character prefix — see handlers.dispatch.
            for _prefix, _spec in _ELEMENT_PREFIX_SPECS:
                if kw == _prefix or kw.startswith(_prefix + "_"):
                    spec = _spec
                    break
        if spec is None:
            if (kw in _NO_ID_KEYWORDS or kw.startswith("PARAMETER")
                    or kw in unmapped):
                continue
            unmapped.add(kw)
            warn(f"*INCLUDE_TRANSFORM {p.filename}: id offsets are NOT applied "
                 f"to *{kw} (keyword has no offset map) — its ids/references "
                 "keep their original values; verify they neither collide with "
                 "the parent deck nor dangle.")
            continue
        with _scoped_block(b):
            _offset_block(b, spec, p.offsets, warn)


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_TRANSFORMATION lookup / row parsing
# ─────────────────────────────────────────────────────────────────────────────

def _transform_block_id(b: Block) -> int:
    with _scoped_block(b):
        toff = _title_offset(b)
        if toff >= len(b.raw) or not b.raw[toff].strip():
            return 0
        return _geti(_fields(b.raw[toff]), 0)


def _find_transform_block(blocks: List[Block], tranid: int) -> Optional[Block]:
    for b in blocks:
        if b.keyword == "DEFINE_TRANSFORMATION" and \
                _transform_block_id(b) == tranid:
            return b
    return None


def _parse_transformation_rows(b: Block, warn) -> List[TransformRow]:
    with _scoped_block(b):
        toff = _title_offset(b)
        rows: List[TransformRow] = []
        k = toff + 1
        raw = b.raw
        while k < len(raw):
            line = raw[k]
            k += 1
            if not line.strip():
                continue
            if "," in line:
                toks = parse_free(line)
                verb = toks[0].strip().upper()
                atoks = toks[1:8]
            else:
                verb = line[:10].strip().upper()
                if " " in verb:                     # whitespace free format
                    toks = line.split()
                    verb = toks[0].strip().upper()
                    atoks = toks[1:8]
                else:
                    atoks = parse_fixed(line[10:], 7, 10)
                    if any(" " in t.strip() for t in atoks):
                        # Whitespace free format with a verb ≥ 9 chars filling
                        # the whole first slice (e.g. "TRANSL2ND 1 2 5.0").
                        toks = line.split()
                        verb = toks[0].strip().upper()
                        atoks = toks[1:8]
            a = tuple(to_float(t) for t in atoks) + (0.0,) * (7 - len(atoks))
            matrix = None
            if verb == "MATRIX":
                vals: List[float] = []
                while k < len(raw) and len(vals) < 16:
                    if raw[k].strip():
                        vals.extend(to_float(t) for t in _fields(raw[k]))
                    k += 1
                matrix = tuple(vals[:16]) if len(vals) >= 16 else None
            rows.append(TransformRow(verb, a[:7], matrix))
        return rows


def _resolve_pending_affine(p: PendingInclude, table: Dict[int, Vec3],
                            warn) -> Optional[Affine]:
    if p.transform_block is None:
        return None
    scope = _node_ids_in(p.sub_blocks)
    rows = _parse_transformation_rows(p.transform_block, warn)
    label = f"*INCLUDE_TRANSFORM {p.filename} (TRANID={p.tranid})"
    aff = compose_rows(rows, table.get, scope.__contains__, warn, label)
    return None if is_identity(aff) else aff


def _linear_preserves_lengths(aff: Affine, tol: float = 1e-9) -> bool:
    """True when the linear part is orthonormal (rotation and/or mirror):
    lengths and angles survive the map, so extent/length fields stay valid."""
    m = aff[0]
    rows = ((m[0], m[1], m[2]), (m[3], m[4], m[5]), (m[6], m[7], m[8]))
    for i in range(3):
        for j in range(i, 3):
            dot = sum(rows[i][t] * rows[j][t] for t in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > tol:
                return False
    return True


def _rewrite_point_fields(line: str, aff: Affine,
                          triplets: List[int]) -> Optional[str]:
    """Apply *aff* to the (i, i+1, i+2) coordinate triplets of one 10-wide
    card, keeping every other field's text verbatim. Returns None when the
    line is too short to carry all requested triplets."""
    toks = [t.strip() for t in _fields(line)]
    while toks and toks[-1] == "":
        toks.pop()
    for i in triplets:
        if len(toks) < i + 3:
            return None
    for i in triplets:
        p = (to_float(toks[i]), to_float(toks[i + 1]), to_float(toks[i + 2]))
        q = affine_apply(aff, p)
        for j in range(3):
            toks[i + j] = _fmt_coord(q[j])
    if "," in line or any(len(t) > 10 for t in toks):
        return ",".join(toks)
    return "".join(f"{t:>10}" for t in toks).rstrip()


def _rewrite_direction_fields(line: str, aff: Affine, n: int,
                              start: int = 0) -> Optional[str]:
    """Apply only the LINEAR part of *aff* to the (start, +1, +2) triplet of a
    fixed-width card, keeping every other field verbatim.

    A DIRECTION has no origin, so the translation must not be applied — the
    *ELEMENT_BEAM_ORIENTATION vector is "relative to node N1" and the third node
    it defines is placed at ``pos(N1) + V``, which already carries the include's
    translation through N1. Returns None when the card is too short."""
    toks = [t.strip() for t in _fields(line, n, 10)]
    while toks and toks[-1] == "":
        toks.pop()
    if not toks or len(toks) <= start:
        return None
    while len(toks) < start + 3:
        toks.append("0.0")           # a blank VY/VZ column is 0.0, not absent
    v = mat_apply(aff[0], (to_float(toks[start]), to_float(toks[start + 1]),
                           to_float(toks[start + 2])))
    for j in range(3):
        toks[start + j] = _fmt_coord(v[j])
    if "," in line or any(len(t) > 10 for t in toks):
        return ",".join(toks)
    return "".join(f"{t:>10}" for t in toks).rstrip()


def _transform_beam_orientation(p: PendingInclude, aff: Affine, warn) -> None:
    """Rotate the *ELEMENT_BEAM_ORIENTATION vectors with their include.

    VX/VY/VZ is literal GEOMETRY, not an id: under a rotating or mirroring
    TRANID the nodes move but an untouched vector leaves the beam's local Y-Z
    frame behind, so Iyy/Izz act on the wrong axes — and at 90 deg the vector
    can end up collinear with the rotated beam axis, which is a degenerate frame
    (starter WARNING 3051, N3 := N2). Nothing else in the deck records the
    error, so this is silent-wrong-answer territory rather than a missing
    warning; applying the affine's linear part is the fix, and it composes for
    nested includes the same way the *NODE rewrite does (the outer entry re-reads
    the lines the inner one already rewrote).

    The cards are located by stepping the same option grammar
    ``_off_element_beam`` uses — the vector card is card 8, after the optional
    _OFFSET card 7 — so an integer-valued vector is never mistaken for a base
    card. Under an unmodelled suffix the step is unknown, so those blocks fall
    back to the coordinate-bearing warning in ``_warn_coordinate_bearing``.
    """
    if linear_is_identity(aff):
        return
    for b in p.sub_blocks:
        kw = b.keyword
        if not (kw.startswith("ELEMENT_BEAM") and "ORIENTATION" in kw):
            continue
        opts, unknown = _elem_opts(kw, "ELEMENT_BEAM", _BEAM_OPT_TOKENS)
        if unknown:
            continue                     # warned by _warn_coordinate_bearing
        vec_off = 1 + int("OFFSET" in opts)
        i = 0
        n_short = 0
        with _scoped_block(b):
            while i < len(b.raw):
                f = [x for x in _fields(b.raw[i], 10, 8) if x]
                if len(f) < 4:
                    i += 1
                    continue
                vi = i + vec_off
                # A blank card is the zero vector: no third node, nothing to
                # rotate.
                if vi < len(b.raw) and b.raw[vi].strip():
                    new = _rewrite_direction_fields(b.raw[vi], aff, 8)
                    if new is None:
                        n_short += 1
                    else:
                        b.raw[vi] = new
                i = vi + 1
        if n_short:
            warn(f"*INCLUDE_TRANSFORM {p.filename}: {n_short} *{kw} orientation "
                 "card(s) are too short to hold VX/VY/VZ — those vectors were "
                 "NOT rotated with the include; check the beams' local axes.")


def _transform_rigidwalls(p: PendingInclude, aff: Affine, warn) -> None:
    """Move *RIGIDWALL_* literal wall geometry with the include, the way the
    OpenRadioss starter replays a submodel transform on both wall points
    (hm_read_rwall_plane.F: SUBROTPOINT on XT/YT/ZT and XH/YH/ZH): Card 2's
    base and head points, plus the _FINITE/_FLAT/_PRISM card's in-plane edge
    head (XHEV/YHEV/ZHEV) — a plain point, so any affine maps it consistently
    with the wall plane. LENL/LENM/LENP are lengths and RADCYL/RADSPH are
    radii: exact under translation/rotation/mirror; warned (not rescaled)
    under scale/shear. A _MOTION card's VX/VY/VZ are direction cosines, so
    only the linear part of the affine applies to them."""
    for b in p.sub_blocks:
        planar = b.keyword.startswith("RIGIDWALL_PLANAR")
        geom = b.keyword.startswith("RIGIDWALL_GEOMETRIC")
        if not (planar or geom):
            continue
        with _scoped_block(b):
            label = f"*INCLUDE_TRANSFORM {p.filename}: *{b.keyword}"
            gi = (1 if "_ID_" in f"_{b.keyword}_" else _title_offset(b)) + 1
            new = (_rewrite_point_fields(b.raw[gi], aff, [0, 3])
                   if gi < len(b.raw) and b.raw[gi].strip() else None)
            if new is None:
                warn(f"{label}: geometry card missing or incomplete — the wall "
                     "was NOT transformed; verify its position manually.")
                continue
            b.raw[gi] = new
            if planar and "_ORTHO" in b.keyword:
                # Friction-direction cards sit between the geometry and _FINITE
                # cards; the ORTHO wall is warn-skipped by the handler anyway
                # (no /RWALL equivalent), so only the plane points are moved.
                continue
            if planar and "_FINITE" in b.keyword:
                fi = gi + 1
                if fi < len(b.raw) and b.raw[fi].strip():
                    newf = _rewrite_point_fields(b.raw[fi], aff, [0])
                    if newf is not None:
                        b.raw[fi] = newf
                if not _linear_preserves_lengths(aff):
                    warn(f"{label}: the TRANID transform scales or shears — the "
                         "finite-wall extents LENL/LENM are NOT rescaled; verify "
                         "the wall coverage.")
            elif geom:
                # Card 3 is shape-specific: FLAT/PRISM lead with the edge-vector
                # head, a POINT; CYLINDER/SPHERE carry only radii and lengths.
                si = gi + 1
                flat = "_FLAT" in b.keyword or "_PRISM" in b.keyword
                if flat and si < len(b.raw) and b.raw[si].strip():
                    news = _rewrite_point_fields(b.raw[si], aff, [0])
                    if news is not None:
                        b.raw[si] = news
                if not _linear_preserves_lengths(aff):
                    warn(f"{label}: the TRANID transform scales or shears — the "
                         "wall dimensions (LENL/LENM/LENP, RADCYL/LENCYL, RADSPH) "
                         "are NOT rescaled; verify the wall size.")
                if "_MOTION" not in b.keyword:
                    continue
                # Card 3c of a CYLINDER carries NSEGS sub-cards before the MOTION
                # card; without NSEGS the MOTION card is the one right after.
                mi = si + 1
                if "_CYLINDER" in b.keyword and si < len(b.raw):
                    f3 = [x.strip() for x in _fields(b.raw[si], 8, 10)]
                    mi += to_int(f3[2]) if len(f3) > 2 and f3[2] else 0
                if mi < len(b.raw) and b.raw[mi].strip():
                    newm = _rewrite_direction_fields(b.raw[mi], aff, 8, start=2)
                    if newm is None:
                        warn(f"{label}: the MOTION card is too short to hold "
                             "VX/VY/VZ — the motion direction was NOT rotated "
                             "with the include.")
                    else:
                        b.raw[mi] = newm


def _carries_literal_axis_point(b: Block) -> bool:
    """True for DIRECTION-bearing blocks whose cards also carry a literal
    axis POINT that even a pure translation must move:
    *INITIAL_VELOCITY_GENERATION with OMEGA != 0 (axis through XC/YC/ZC,
    unless node-defined via NX=-999), *BOUNDARY_PRESCRIBED_MOTION_* with
    |DOF| in 9/10/11 (axis through OFFSET1/OFFSET2), and *LOAD_BODY_RX/RY/RZ
    with a non-zero centre of rotation (XC/YC/ZC)."""
    kw = b.keyword
    if kw == "INITIAL_VELOCITY_GENERATION":
        start = _title_offset(b)
        f1 = _fields(b.raw[start]) if start < len(b.raw) else []
        omega = to_float(f1[2]) if len(f1) > 2 and str(f1[2]).strip() else 0.0
        if omega == 0.0:
            return False
        f2 = _fields(b.raw[start + 1]) if start + 1 < len(b.raw) else []
        nx = to_float(f2[3]) if len(f2) > 3 and str(f2[3]).strip() else 0.0
        return not (-999.5 < nx < -998.5)
    if kw in ("LOAD_BODY_RX", "LOAD_BODY_RY", "LOAD_BODY_RZ"):
        start = _title_offset(b)
        f1 = _fields(b.raw[start]) if start < len(b.raw) else []
        return any(to_float(f1[i]) != 0.0
                   for i in (3, 4, 5)
                   if len(f1) > i and str(f1[i]).strip())
    if kw.startswith("BOUNDARY_PRESCRIBED_MOTION"):
        # is_box has to be threaded through here too, or the _SET_BOX card 2 is
        # walked as a card 1 and its TOFFSET tested against (9, 10, 11) — the one
        # call site the two-card walk was not wired into (_off_bpm already
        # passes it).
        return any(not cont and abs(_geti(_fields(b.raw[k]), 1)) in (9, 10, 11)
                   for k, cont in _bpm_cards(b, is_box=kw.endswith("_BOX")))
    return False


def _is_untransformed_beam_orientation(b: Block) -> bool:
    """True for an *ELEMENT_BEAM*ORIENTATION block ``_transform_beam_orientation``
    could NOT rotate — i.e. one whose option suffix is not in the grammar, so the
    per-element card count (and with it the position of the vector card) is
    unknown. The modelled spellings ARE rotated and must not be warned about."""
    kw = b.keyword
    if not (kw.startswith("ELEMENT_BEAM") and "ORIENTATION" in kw):
        return False
    return bool(_elem_opts(kw, "ELEMENT_BEAM", _BEAM_OPT_TOKENS)[1])


def _cross_section_plane_is_node_defined(b: Block) -> bool:
    """True when this ``*DATABASE_CROSS_SECTION_PLANE`` states its plane with
    NODE IDS rather than coordinates.

    Vol I R17 p.16-50: *"If RADIUS is negative ... XCT and XCH will be node
    IDs"*. Such a card carries no literal geometry at all — it follows its
    nodes, which the TRANID affine DOES move — so the point-bearing warning
    would be prescribing a manual re-orientation on a correct deck (#125), and
    the warning's own parenthetical already promises that node-defined variants
    follow their nodes.
    """
    toff = _title_offset(b)
    if toff >= len(b.raw):
        return False
    cells, _comma, _wsf = _split_card(b.raw[toff], 10)
    return len(cells) > 7 and to_float(cells[7]) < 0.0


def _warn_coordinate_bearing(p: PendingInclude, aff: Affine, warn) -> None:
    seen: Set[str] = set()
    rotates = not linear_is_identity(aff)
    for b in p.sub_blocks:
        kw = b.keyword
        if kw in seen:
            continue
        bearing = False
        with _scoped_block(b):
            if (kw == "DATABASE_CROSS_SECTION_PLANE"
                    and _cross_section_plane_is_node_defined(b)):
                # Not added to `seen`: a SECOND, coordinate-defined card of the
                # same keyword in this include still has to be reported.
                continue
            bearing = kw in _POINT_BEARING or (
                kw in _DIRECTION_BEARING
                and (rotates or _carries_literal_axis_point(b))) \
                or (rotates and _is_untransformed_beam_orientation(b))
        if bearing:
            seen.add(kw)
            warn(f"*INCLUDE_TRANSFORM {p.filename}: the TRANID transform is "
                 "applied to *NODE coordinates and *RIGIDWALL_PLANAR geometry "
                 f"only — *{kw} in this include carries literal geometry "
                 "(points/directions/tensors) that was NOT transformed; move "
                 "or re-orient it manually if it is load-bearing. "
                 "(Node-defined variants follow their nodes automatically.)")


def _warn_units_and_decoration(p: PendingInclude, warn) -> None:
    fct = [("FCTMAS", p.fctmas), ("FCTTIM", p.fcttim), ("FCTLEN", p.fctlen)]
    nonunity = [f"{n}={v:g}" for n, v in fct if v not in (0.0, 1.0)]
    if p.fcttem:
        nonunity.append(f"FCTTEM={p.fcttem}")
    if p.fctchg and to_float(p.fctchg) not in (0.0, 1.0):
        nonunity.append(f"FCTCHG={p.fctchg}")
    if nonunity:
        warn(f"*INCLUDE_TRANSFORM {p.filename}: unit transform factors "
             f"({', '.join(nonunity)}) are NOT applied — a consistent rescale "
             "must touch every dimensioned value (coordinates, thicknesses, "
             "densities, moduli, curves), which is the kunit converter's "
             "domain. Convert the include to the parent's unit system first "
             "(e.g. with kunit), then drop the FCT* factors.")
    if p.prefix or p.suffix:
        warn(f"*INCLUDE_TRANSFORM {p.filename}: PREFIX/SUFFIX title decoration "
             "is not applied (titles are cosmetic; ids are already offset).")


# ─────────────────────────────────────────────────────────────────────────────
# *NODE_TRANSFORM
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_node_set(blocks: List[Block], nsid: int) -> Optional[List[int]]:
    for b in blocks:
        if b.keyword not in ("SET_NODE_LIST", "SET_NODE"):
            continue
        with _scoped_block(b):
            toff = _title_offset(b)
            if toff >= len(b.raw):
                continue
            if _geti(_fields(b.raw[toff]), 0) != nsid:
                continue
            nids: List[int] = []
            for line in b.raw[toff + 1:]:
                for tok in parse_free(line):
                    v = to_int(tok)
                    if v > 0:
                        nids.append(v)
            return nids
    return None


def _apply_node_transforms(blocks: List[Block], warn) -> None:
    nts = [b for b in blocks if b.keyword == "NODE_TRANSFORM"]
    if not nts:
        return
    table = _collect_node_coords(blocks)     # CURRENT (post-include) coords
    for b in nts:
        with _scoped_block(b):
            for line in b.raw:
                if not line.strip():
                    continue
                f = _fields(line, 3)
                trsid, nsid, immed = _geti(f, 0), _geti(f, 1), _geti(f, 2)
                if trsid <= 0 or nsid <= 0:
                    warn(f"*NODE_TRANSFORM: incomplete card (TRSID={trsid}, "
                         f"NSID={nsid}) — NOT applied.")
                    continue
                if immed:
                    warn(f"*NODE_TRANSFORM TRSID={trsid}: IMMED=1 (apply while "
                         "reading) is treated as the default deferred application "
                         "— identical unless the transformed nodes feed a later "
                         "node-referenced definition.")
                tb = _find_transform_block(blocks, trsid)
                if tb is None:
                    warn(f"*NODE_TRANSFORM TRSID={trsid}: no "
                         "*DEFINE_TRANSFORMATION with this id — NOT applied; the "
                         "node set keeps its original position.")
                    continue
                nids = _resolve_node_set(blocks, nsid)
                if nids is None:
                    warn(f"*NODE_TRANSFORM TRSID={trsid}: node set {nsid} not "
                         "found (only *SET_NODE_LIST is resolvable here) — NOT "
                         "applied.")
                    continue
                scope = set(nids)
                rows = _parse_transformation_rows(tb, warn)
                aff = compose_rows(rows, table.get, scope.__contains__, warn,
                                   f"*NODE_TRANSFORM TRSID={trsid}")
                if is_identity(aff):
                    continue
                changed = _rewrite_node_blocks(blocks, aff=aff, only_ids=scope)
                table.update(changed)
                if not changed:
                    warn(f"*NODE_TRANSFORM TRSID={trsid}: node set {nsid} matched "
                         "no *NODE in the deck — nothing transformed.")


# ─────────────────────────────────────────────────────────────────────────────
# The deferred resolution pass (called by parser at the end of a depth-0 parse)
# ─────────────────────────────────────────────────────────────────────────────

def _cum_parent_iddoff(p: PendingInclude,
                       owner: Dict[int, PendingInclude]) -> int:
    """Cumulative IDDOFF applied to the FILE containing p's include card. The
    card's TRANID reference lives in that file's namespace, and every
    enclosing *INCLUDE_TRANSFORM offsets that namespace's *DEFINE ids —
    *owner* maps id(sub_blocks list) → the pending that included it."""
    total = 0
    q = owner.get(id(p.parent_blocks))
    while q is not None:
        total += q.offsets.get("d", 0)
        q = owner.get(id(q.parent_blocks))
    return total


def finalize(blocks: List[Block]) -> None:
    has_nt = any(b.keyword == "NODE_TRANSFORM" for b in blocks)
    if not PENDING_INCLUDES and not has_nt:
        return
    warn = _warn

    # 1. Id offsets, registration order (= innermost first; nested offsets
    #    accumulate additively because the outer entry's sub_blocks contain
    #    the inner include's blocks).
    for p in PENDING_INCLUDES:
        _warn_units_and_decoration(p, warn)
        if any(p.offsets.values()):
            _apply_offsets(p, warn)

    # 2. Bind each pending TRANID to its *DEFINE_TRANSFORMATION AFTER the
    #    offset pass — dyna2rad applies IDDOFF at read and resolves TRANID
    #    against the offset ids, so a definition inside an offset include is
    #    referenced by its POST-offset id, and a same-numbered child
    #    definition never shadows the parent's. The TRANID reference itself
    #    is shifted by the cumulative IDDOFF of the file CONTAINING the
    #    include card (zero for the main deck), like every other *DEFINE
    #    reference in that file. Parent scope is searched first so a nested
    #    include prefers its own file's definition on a (user-made) id clash.
    owner = {id(q.sub_blocks): q for q in PENDING_INCLUDES}
    for p in PENDING_INCLUDES:
        if p.tranid > 0:
            tid = p.tranid + _cum_parent_iddoff(p, owner)
            p.transform_block = (_find_transform_block(p.parent_blocks, tid)
                                 or _find_transform_block(blocks, tid))
            if p.transform_block is None:
                extra = (f" (id {tid} after the enclosing includes' IDDOFF)"
                         if tid != p.tranid else "")
                warn(f"*INCLUDE_TRANSFORM {p.filename}: TRANID={p.tranid}"
                     f"{extra} matches no *DEFINE_TRANSFORMATION anywhere in "
                     "the deck — the include is NOT transformed; the geometry "
                     "is wrong if the transform is load-bearing.")

    # 3. Node table: parse-time coordinates, post-offset ids — what the
    #    starter sees when LECTRANSSUB resolves /TRANSFORM node references.
    table = _collect_node_coords(blocks)

    # 4. Geometric transforms, innermost first (LECSUBMOD level walk): the
    #    outer entry re-reads the raw lines its inner include already moved,
    #    composing outer∘inner on the coordinates. The reference table stays
    #    at parse-time coordinates on purpose. Rigid-wall literal geometry
    #    moves with its include (the starter's SUBROTPOINT semantics).
    for p in PENDING_INCLUDES:
        aff = _resolve_pending_affine(p, table, warn)
        if aff is None:
            continue
        _rewrite_node_blocks(p.sub_blocks, aff=aff)
        _transform_rigidwalls(p, aff, warn)
        _transform_beam_orientation(p, aff, warn)
        _warn_coordinate_bearing(p, aff, warn)

    # 5. *NODE_TRANSFORM acts on already-transformed geometry, deck order
    #    (LECTRANS runs after the submodel pass; references read CURRENT
    #    coordinates).
    _apply_node_transforms(blocks, warn)
