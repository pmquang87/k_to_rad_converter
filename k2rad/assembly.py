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

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .handlers import _SPOTWELD_CONTACT_KEYWORDS
from .parser import (Block, PARSER_WARNINGS, parse_fixed, parse_free,
                     to_float, to_int)
from .transform import (Affine, TransformRow, affine_apply, compose_rows,
                        is_identity, linear_is_identity, mat_apply)

Vec3 = Tuple[float, float, float]

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
    *tail* preserves the TC/RC columns verbatim."""
    f = parse_free(line)
    if len(f) < 4 or any(len(t) > 16 for t in f[1:4]):
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


def _off_part(b: Block, offsets: Dict[str, int], warn) -> None:
    # (title, data) pairs, possibly repeated: pid secid mid eosid hgid _ _ tmid
    mods = [(0, "p"), (1, "r"), (2, "m"), (3, "m"), (4, "r"), (7, "m")]
    for i in range(0, len(b.raw) - 1, 2):
        new = _rewrite_line(b.raw[i + 1], mods, offsets)
        if new is not None:
            b.raw[i + 1] = new


# *ELEMENT_SHELL / *ELEMENT_BEAM option grammar — mirrors handlers.py
# (_SHELL_SUFFIX_TOKENS / _BEAM_SUFFIX_TOKENS) without importing it, the same
# way _title_offset mirrors handlers._title_offset.
_SHELL_OPT_TOKENS = frozenset({"THICKNESS", "BETA", "MCID", "OFFSET", "DOF"})
_BEAM_OPT_TOKENS = frozenset({"ORIENTATION", "OFFSET"})


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


def _off_cnrb_spc(b: Block, offsets: Dict[str, int], warn) -> None:
    """*CONSTRAINED_NODAL_RIGID_BODY_SPC. Card 1: pid cid nsid pnode …;
    SPC card: CMO CON1 CON2 SPCNID — with CMO<0 CON1 is a local
    *DEFINE_COORDINATE_* system id (IDDOFF namespace), not a DOF code."""
    toff = _title_offset(b)
    if toff < len(b.raw) and b.raw[toff].strip():
        new = _rewrite_line(b.raw[toff], [(0, "p"), (1, "d"), (2, "s"),
                                          (3, "n")], offsets)
        if new is not None:
            b.raw[toff] = new
    i2 = toff + 1
    if i2 < len(b.raw) and b.raw[i2].strip():
        f = _fields(b.raw[i2])
        cmo = to_float(f[0]) if f and str(f[0]).strip() else 0.0
        mods: List[Tuple[int, str]] = [(3, "n")]          # SPCNID
        if cmo < 0.0:
            mods.append((1, "d"))                         # CON1 = system id
        new = _rewrite_line(b.raw[i2], mods, offsets)
        if new is not None:
            b.raw[i2] = new


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
    so needs the sign-preserving rewriter."""
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
        idx += 2
        if _geti(f1, 6) == 1:                   # ICOMP: ceil(NIP/8) angle cards
            idx += ((nip if nip > 0 else 2) + 7) // 8
        if opt_card:                            # card 4a-4d
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


def _bpm_cards(b: Block):
    """Yield (line_index, is_continuation) over a *BOUNDARY_PRESCRIBED_MOTION
    block: the official reader takes ONE extra card (OFFSET1 OFFSET2 MRB
    NODE1 NODE2) after a card 1 with |DOF| in 9/10/11 or VAD=4
    (boundary_prescribed_motion*.cfg)."""
    expect2 = False
    for k in range(_title_offset(b), len(b.raw)):
        if not b.raw[k].strip():
            continue
        if expect2:
            yield k, True
            expect2 = False
            continue
        f = _fields(b.raw[k])
        expect2 = abs(_geti(f, 1)) in (9, 10, 11) or _geti(f, 2) == 4
        yield k, False


def _off_bpm(id_bucket: str):
    """*BOUNDARY_PRESCRIBED_MOTION_{RIGID,SET,NODE}: repeated card-1 entries
    (typeid dof vad lcid sf vid death birth) with a conditional continuation
    card that must NOT receive the card-1 mods — its OFFSET1/OFFSET2 are
    literal coordinates; MRB is a rigid-body part, NODE1/NODE2 nodes."""
    c1 = [(0, id_bucket), (3, "f"), (5, "d")]
    c2 = [(2, "p"), (3, "n"), (4, "n")]

    def _fn(b: Block, offsets: Dict[str, int], warn) -> None:
        raw = b.raw
        if _title_offset(b) and "ID" in b.options and raw:
            new = _rewrite_id_header(raw[0], offsets.get("r", 0))
            if new is not None:
                raw[0] = new
        for k, cont in _bpm_cards(b):
            new = _rewrite_line(raw[k], c2 if cont else c1, offsets)
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

_OFFSET_SPECS: Dict[str, object] = {
    # Mesh
    "NODE": _off_node,
    # The _THICKNESS/_BETA/_MCID/_OFFSET/_DOF and _ORIENTATION spellings are
    # registered from the same grammar handlers.py uses, just below this dict;
    # _apply_offsets additionally falls back on the family prefix, so an
    # unlisted spelling is offset rather than warned about.
    "ELEMENT_SHELL": _off_element_shell,
    "ELEMENT_SOLID": _off_element_solid,
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
    # *SET_PART_ADD data ids are part-SET ids (one nesting level), bucket "s".
    "SET_PART_ADD": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "s")])},
    # *CONTACT_INTERIOR is a bare free list of part-set ids (no header card).
    "CONTACT_INTERIOR": {"data": (0, [(ALL, "s")])},
    "SET_SHELL_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SHELL": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SOLID_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SOLID": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_BEAM_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_BEAM": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
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
    "NODE_TRANSFORM": {"data": (0, [(0, "d"), (1, "s")])},

    # Materials (mid + the curve/table reference fields k2rad models)
    "MAT_ELASTIC": _mat(),
    # Impact / blast batch. Every field of *MAT_110, *MAT_111 and the
    # *MAT_ELASTIC _FLUID card is a physical constant — no curve, table or set
    # id anywhere on the three cards — so MID is the only cell to offset.
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
    "MAT_HILL_FOAM": _mat({0: [(5, "f"), (7, "f")]}),
    "MAT_177": _mat({0: [(5, "f"), (7, "f")]}),
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
    "BOUNDARY_PRESCRIBED_MOTION_SET": _off_bpm("s"),
    "BOUNDARY_PRESCRIBED_MOTION_NODE": _off_bpm("n"),
    "INITIAL_VELOCITY": {"cards": {0: [(0, "s"), (1, "s"), (2, "d"),
                                       (4, "d")]}, "idhdr": "r"},
    "INITIAL_VELOCITY_NODE": {"data": (0, [(0, "n")]), "idhdr": "r"},
    "INITIAL_VELOCITY_RIGID_BODY": {"data": (0, [(0, "p")]), "idhdr": "r"},
    "INITIAL_VELOCITY_GENERATION": _off_inivel_generation,
    "INITIAL_DETONATION": {"data": (0, [(0, "p")])},
    "BOUNDARY_NON_REFLECTING": {"data": (0, [(0, "s")])},

    # Constraints
    "CONSTRAINED_NODAL_RIGID_BODY": {"cards": {0: [(0, "p"), (1, "d"),
                                                   (2, "s"), (3, "n")]}},
    "CONSTRAINED_NODAL_RIGID_BODY_SPC": _off_cnrb_spc,
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
    "LOAD_BODY_X": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_Y": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BODY_Z": {"cards": {0: [(0, "f"), (2, "f"), (6, "d")]}, "idhdr": "r"},
    "LOAD_BLAST_ENHANCED": {"cards": {0: [(0, "r")], 1: [(4, "n")]}},
    "LOAD_BLAST": {"cards": {1: [(4, "n")]}},
    "LOAD_BLAST_SEGMENT_SET": {"data": (0, [(0, "r"), (1, "s"), (2, "p")])},
    "LOAD_BLAST_SEGMENT": {"data": (0, [(0, "r"), (1, "n"), (2, "n"), (3, "n"),
                                        (4, "n")])},

    # ALE
    "ALE_MULTI-MATERIAL_GROUP": _off_ale_multi_material_group,

    # Database / output requests
    "DATABASE_HISTORY_NODE": {"data": (0, [(ALL, "n")])},
    "DATABASE_HISTORY_SHELL": {"data": (0, [(ALL, "e")])},
    "DATABASE_HISTORY_SOLID": {"data": (0, [(ALL, "e")])},
    "DATABASE_CROSS_SECTION_PLANE": {"cards": {0: [(0, "s")]}, "idhdr": "p"},
    "DATABASE_CROSS_SECTION_SET": {"cards": {0: [(i, "s") for i in range(6)]},
                                   "idhdr": "p"},
    "DATABASE_BINARY_D3PLOT": {"cards": {0: [(1, "f"), (4, "s")]}},

    # Damping / control cards that carry ids
    "DAMPING_GLOBAL": {"cards": {0: [(0, "f")]}},
    "DAMPING_PART_STIFFNESS": {"data": (0, [(0, "p")])},
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
del _o1, _o2, _o3, _o4

#: Family prefix → rewriter for the *ELEMENT_ spellings the table does not list
#: (mirrors handlers._ELEMENT_PREFIX_HANDLERS). Without it every unrecognized
#: *ELEMENT_SHELL_<option> in an *INCLUDE_TRANSFORM would keep its original
#: node/part ids while the rest of the include was offset — dangling
#: connectivity, which is worse than the warning it would have produced.
_ELEMENT_PREFIX_SPECS = (
    ("ELEMENT_SHELL", _off_element_shell),
    ("ELEMENT_BEAM", _off_element_beam),
    ("ELEMENT_PLOTEL", _OFFSET_SPECS["ELEMENT_PLOTEL"]),
)

# All *RIGIDWALL_PLANAR variants share Card 1 (nsid nsidex boxid ...).
for _kw in ("RIGIDWALL_PLANAR_FORCES", "RIGIDWALL_PLANAR_MOVING",
            "RIGIDWALL_PLANAR_MOVING_FORCES", "RIGIDWALL_PLANAR_FINITE",
            "RIGIDWALL_PLANAR_FINITE_FORCES", "RIGIDWALL_PLANAR_FINITE_MOVING",
            "RIGIDWALL_PLANAR_FINITE_MOVING_FORCES", "RIGIDWALL_PLANAR_ORTHO",
            "RIGIDWALL_PLANAR_ORTHO_FORCES", "RIGIDWALL_PLANAR_ORTHO_FINITE",
            "RIGIDWALL_PLANAR_ORTHO_MOVING",
            "RIGIDWALL_PLANAR_ORTHO_FINITE_MOVING"):
    _OFFSET_SPECS[_kw] = _OFFSET_SPECS["RIGIDWALL_PLANAR"]

# All CONTACT_* handled by k2rad share the Card-1 (ssid msid sstyp mstyp
# sboxid mboxid) layout; unlisted CONTACT_ variants fall to the unmapped warn.
for _kw in (
    "CONTACT_AUTOMATIC_SINGLE_SURFACE", "CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR",
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK",
    "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK",
    "CONTACT_TIEBREAK_SURFACE_TO_SURFACE", "CONTACT_TIEBREAK_NODES_TO_SURFACE",
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
    "DATABASE_EXTENT_BINARY", "DATABASE_JNTFORC", "DATABASE_MATSUM",
    "DATABASE_NODOUT", "DATABASE_RCFORC", "DATABASE_RWFORC",
    "DATABASE_SECFORC", "DATABASE_SLEOUT", "DATABASE_SPCFORC",
    "DATABASE_NCFORC", "DATABASE_RBDOUT", "DATABASE_BINARY_D3DRLF",
    "DATABASE_BINARY_D3DUMP", "DATABASE_BINARY_BLSTFOR",
    "DATABASE_BINARY_RUNRSF",
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
})
#: Direction/tensor-bearing keywords: valid under pure translation, wrong
#: under rotation/mirror/scale — warned only when the linear part is not I.
_DIRECTION_BEARING = frozenset({
    "DEFINE_COORDINATE_VECTOR", "DEFINE_SD_ORIENTATION", "INITIAL_VELOCITY",
    "INITIAL_VELOCITY_NODE", "INITIAL_VELOCITY_RIGID_BODY",
    "INITIAL_VELOCITY_GENERATION", "BOUNDARY_PRESCRIBED_MOTION_RIGID",
    "BOUNDARY_PRESCRIBED_MOTION_SET", "BOUNDARY_PRESCRIBED_MOTION_NODE",
    "LOAD_NODE_POINT", "LOAD_NODE_SET", "LOAD_BODY_X", "LOAD_BODY_Y",
    "LOAD_BODY_Z", "INITIAL_STRESS_SHELL", "INITIAL_STRESS_SOLID",
    "BOUNDARY_SPC_SET", "BOUNDARY_SPC_NODE", "BOUNDARY_SPC",
})


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
            for _prefix, _spec in _ELEMENT_PREFIX_SPECS:
                if kw.startswith(_prefix):
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
        _offset_block(b, spec, p.offsets, warn)


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_TRANSFORMATION lookup / row parsing
# ─────────────────────────────────────────────────────────────────────────────

def _transform_block_id(b: Block) -> int:
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


def _rewrite_direction_fields(line: str, aff: Affine, n: int) -> Optional[str]:
    """Apply only the LINEAR part of *aff* to the leading (0,1,2) triplet of a
    fixed-width card, keeping every other field verbatim.

    A DIRECTION has no origin, so the translation must not be applied — the
    *ELEMENT_BEAM_ORIENTATION vector is "relative to node N1" and the third node
    it defines is placed at ``pos(N1) + V``, which already carries the include's
    translation through N1. Returns None when the card is too short."""
    toks = [t.strip() for t in _fields(line, n, 10)]
    while toks and toks[-1] == "":
        toks.pop()
    if not toks:
        return None
    while len(toks) < 3:
        toks.append("0.0")           # a blank VY/VZ column is 0.0, not absent
    v = mat_apply(aff[0], (to_float(toks[0]), to_float(toks[1]),
                           to_float(toks[2])))
    for j in range(3):
        toks[j] = _fmt_coord(v[j])
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
        while i < len(b.raw):
            f = [x for x in _fields(b.raw[i], 10, 8) if x]
            if len(f) < 4:
                i += 1
                continue
            vi = i + vec_off
            # A blank card is the zero vector: no third node, nothing to rotate.
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
    """Move *RIGIDWALL_PLANAR* literal wall geometry with the include, the way
    the OpenRadioss starter replays a submodel transform on both wall points
    (hm_read_rwall_plane.F: SUBROTPOINT on XT/YT/ZT and XH/YH/ZH): Card 2's
    base and head points, plus the _FINITE card's in-plane edge head
    (XHEV/YHEV/ZHEV) — a plain point, so any affine maps it consistently with
    the wall plane. LENL/LENM are lengths: exact under translation/rotation/
    mirror; warned (not rescaled) under scale/shear."""
    for b in p.sub_blocks:
        if not b.keyword.startswith("RIGIDWALL_PLANAR"):
            continue
        label = f"*INCLUDE_TRANSFORM {p.filename}: *{b.keyword}"
        gi = _title_offset(b) + 1
        new = (_rewrite_point_fields(b.raw[gi], aff, [0, 3])
               if gi < len(b.raw) and b.raw[gi].strip() else None)
        if new is None:
            warn(f"{label}: geometry card missing or incomplete — the wall "
                 "was NOT transformed; verify its position manually.")
            continue
        b.raw[gi] = new
        if "_ORTHO" in b.keyword:
            # Friction-direction cards sit between the geometry and _FINITE
            # cards; the ORTHO wall is warn-skipped by the handler anyway
            # (no /RWALL equivalent), so only the plane points are moved.
            continue
        if "_FINITE" in b.keyword:
            fi = gi + 1
            if fi < len(b.raw) and b.raw[fi].strip():
                newf = _rewrite_point_fields(b.raw[fi], aff, [0])
                if newf is not None:
                    b.raw[fi] = newf
            if not _linear_preserves_lengths(aff):
                warn(f"{label}: the TRANID transform scales or shears — the "
                     "finite-wall extents LENL/LENM are NOT rescaled; verify "
                     "the wall coverage.")


def _carries_literal_axis_point(b: Block) -> bool:
    """True for DIRECTION-bearing blocks whose cards also carry a literal
    axis POINT that even a pure translation must move:
    *INITIAL_VELOCITY_GENERATION with OMEGA != 0 (axis through XC/YC/ZC,
    unless node-defined via NX=-999) and *BOUNDARY_PRESCRIBED_MOTION_* with
    |DOF| in 9/10/11 (axis through OFFSET1/OFFSET2)."""
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
    if kw.startswith("BOUNDARY_PRESCRIBED_MOTION"):
        return any(not cont and abs(_geti(_fields(b.raw[k]), 1)) in (9, 10, 11)
                   for k, cont in _bpm_cards(b))
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


def _warn_coordinate_bearing(p: PendingInclude, aff: Affine, warn) -> None:
    seen: Set[str] = set()
    rotates = not linear_is_identity(aff)
    for b in p.sub_blocks:
        kw = b.keyword
        if kw in seen:
            continue
        if kw in _POINT_BEARING or (kw in _DIRECTION_BEARING and (
                rotates or _carries_literal_axis_point(b))) \
                or (rotates and _is_untransformed_beam_orientation(b)):
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
