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
map, and coordinate-bearing keywords other than *NODE inside a transformed
include.  The common TRANSL/ROTATE/SCALE/MIRROR + id-offset path is applied
faithfully and silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .parser import (Block, PARSER_WARNINGS, parse_fixed, parse_free,
                     to_float, to_int)
from .transform import (Affine, TransformRow, affine_apply, compose_rows,
                        is_identity, linear_is_identity)

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

def _rewrite_line(line: str, mods: List[Tuple[int, str]],
                  offsets: Dict[str, int], w: int = 10) -> Optional[str]:
    """Offset the id fields listed in *mods* on one card. Returns the new
    line, or None when nothing changed. Only ids > 0 are touched (0/blank is
    a none/ground/self sentinel everywhere; negative values are special
    encodings the OpenRadioss reader does not offset either)."""
    comma = "," in line
    ws_free = False
    if comma:
        fields = parse_free(line)
    else:
        n_all = max(8, (len(line) + w - 1) // w)
        fields = parse_fixed(line, n_all, w)
        if any(" " in x.strip() for x in fields):
            ws_free = True
            fields = line.split()
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
    fields = [x.strip() for x in fields]
    while fields and fields[-1] == "":
        fields.pop()
    if comma or any(len(x) > w for x in fields):
        return ",".join(fields)
    if ws_free:
        return " ".join(fields)
    return "".join(f"{x:>{w}}" for x in fields).rstrip()


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
    """Return (nid, x, y, z, tail) for one *NODE card, or None. Mirrors
    handlers.handle_node: free split with a fixed I8+3×E16 fallback for glued
    negative coordinates; *tail* preserves the TC/RC columns verbatim."""
    f = parse_free(line)
    if len(f) < 4 or any(len(t) > 16 for t in f[1:4]):
        nid = to_int(line[0:8])
        if nid <= 0:
            return None
        return (nid, to_float(line[8:24]), to_float(line[24:40]),
                to_float(line[40:56]), line[56:])
    nid = to_int(f[0])
    if nid <= 0:
        return None
    tail = "".join(f"{t:>8}" for t in f[4:6]) if len(f) > 4 else ""
    return (nid, to_float(f[1]), to_float(f[2]), to_float(f[3]), tail)


def _emit_node_line(nid: int, x: float, y: float, z: float, tail: str) -> str:
    if len(str(nid)) <= 8:
        return f"{nid:>8}{x:16.9G}{y:16.9G}{z:16.9G}{tail}".rstrip()
    core = f"{nid},{x:.9G},{y:.9G},{z:.9G}"
    extra = tail.strip().split()
    return ",".join([core] + extra) if extra else core


def _rewrite_node_blocks(blocks: List[Block], nodeoff: int = 0,
                         aff: Optional[Affine] = None,
                         only_ids: Optional[Set[int]] = None) -> Dict[int, Vec3]:
    """Apply an id offset and/or an affine to every *NODE line of *blocks*.
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
            nid, x, y, z, tail = parsed
            if only_ids is not None and nid not in only_ids:
                continue
            if aff is not None:
                x, y, z = affine_apply(aff, (x, y, z))
            nid2 = nid + nodeoff if nodeoff else nid
            b.raw[k] = _emit_node_line(nid2, x, y, z, tail)
            changed[nid2] = (x, y, z)
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
                table[parsed[0]] = (parsed[1], parsed[2], parsed[3])
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
        verb = (parse_free(line)[0] if "," in line else line[:10]).strip().upper()
        fields = node_fields.get(verb)
        if not fields:
            continue
        if "," in line:
            new = _rewrite_line(line, [(i, "n") for i in fields], offsets)
            if new is not None:
                b.raw[k] = new
            continue
        a = parse_fixed(line[10:], 7, 10)
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

_OFFSET_SPECS: Dict[str, object] = {
    # Mesh
    "NODE": _off_node,
    "ELEMENT_SHELL": {"data": (0, _ELEM_SHELL_MODS), "w": 8},
    "ELEMENT_SOLID": _off_element_solid,
    "ELEMENT_BEAM": {"data": (0, [(0, "e"), (1, "p"), (2, "n"), (3, "n"),
                                  (4, "n")]), "w": 8},
    "ELEMENT_DISCRETE": _off_element_discrete,
    "ELEMENT_MASS": _off_element_mass,
    "ELEMENT_MASS_NODE_SET": _off_element_mass_node_set,
    "ELEMENT_MASS_PART": {"data": (0, [(0, "p"), (3, "f")]), "idhdr": "r"},
    "ELEMENT_MASS_PART_SET": {"data": (0, [(0, "s"), (3, "f")]), "idhdr": "r"},
    "PART": _off_part,
    "HOURGLASS": {"cards": {0: [(0, "r")]}},

    # Sections
    "SECTION_SHELL": {"cards": {0: [(0, "r")]}},
    "SECTION_SOLID": {"cards": {0: [(0, "r")]}},
    "SECTION_BEAM": {"cards": {0: [(0, "r")]}},
    "SECTION_DISCRETE": {"cards": {0: [(0, "r")]}},

    # Sets
    "SET_NODE_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "n")])},
    "SET_NODE": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "n")])},
    "SET_PART_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "p")])},
    "SET_PART": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "p")])},
    "SET_SHELL_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SHELL": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SOLID_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SOLID": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_BEAM_LIST": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_BEAM": {"cards": {0: [(0, "s")]}, "data": (1, [(ALL, "e")])},
    "SET_SEGMENT": {"cards": {0: [(0, "s")]},
                    "data": (1, [(0, "n"), (1, "n"), (2, "n"), (3, "n")])},

    # Curves / tables
    "DEFINE_CURVE": {"cards": {0: [(0, "f")]}},
    "DEFINE_CURVE_FUNCTION": {"cards": {0: [(0, "f")]}},
    "DEFINE_TABLE": {"cards": {0: [(0, "f")]}, "data": (1, [(1, "f")])},
    "DEFINE_TABLE_2D": {"cards": {0: [(0, "f")]}, "data": (1, [(1, "f")])},

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
    "MAT_ANISOTROPIC_VISCOPLASTIC": {"cards": {0: [(0, "m"), (6, "f")]}},
    "MAT_103": {"cards": {0: [(0, "m"), (6, "f")]}},
    "MAT_RIGID": _mat(),
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
    "MAT_SPRING_ELASTIC": _mat(),
    "MAT_S01": _mat(),
    "MAT_SPRING_NONLINEAR_ELASTIC": {"cards": {0: [(0, "m"), (1, "f"),
                                                   (2, "f")]}},
    "MAT_S04": {"cards": {0: [(0, "m"), (1, "f"), (2, "f")]}},
    "MAT_DAMPER_VISCOUS": _mat(),
    "MAT_D01": _mat(),
    "MAT_SPOTWELD": _mat(),
    "MAT_100": _mat(),
    "MAT_187": {"cards": {0: [(0, "m")],
                          1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"),
                              (5, "f")]}},
    "MAT_SAMP-1": {"cards": {0: [(0, "m")],
                             1: [(0, "f"), (1, "f"), (2, "f"), (3, "f"),
                                 (5, "f")]}},
    "MAT_SIMPLIFIED_JOHNSON_COOK": _mat(),
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
    "BOUNDARY_PRESCRIBED_MOTION_RIGID": {"data": (0, [(0, "p"), (3, "f"),
                                                      (5, "d")]), "idhdr": "r"},
    "BOUNDARY_PRESCRIBED_MOTION_SET": {"data": (0, [(0, "s"), (3, "f"),
                                                    (5, "d")]), "idhdr": "r"},
    "BOUNDARY_PRESCRIBED_MOTION_NODE": {"data": (0, [(0, "n"), (3, "f"),
                                                     (5, "d")]), "idhdr": "r"},
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
    "CONSTRAINED_NODAL_RIGID_BODY_SPC": {"cards": {0: [(0, "p"), (1, "d"),
                                                       (2, "s"), (3, "n")],
                                                   1: [(3, "n")]}},
    "CONSTRAINED_EXTRA_NODES_NODE": {"data": (0, [(0, "p"), (1, "n")])},
    "CONSTRAINED_EXTRA_NODES_SET": {"data": (0, [(0, "p"), (1, "s")])},
    "CONSTRAINED_RIGID_BODIES": {"data": (0, [(0, "p"), (1, "p")])},
    "CONSTRAINED_SPOTWELD": {"data": (0, [(0, "n"), (1, "n")])},
    "CONSTRAINED_SPOTWELD_FILTERED_FORCE": {"data": (0, [(0, "n"), (1, "n")]),
                                            "stride": 2},
    "CONSTRAINED_GENERALIZED_WELD_SPOT": {"cards": {0: [(0, "s"), (1, "d")]}},
    "CONSTRAINED_NODE_SET": {"cards": {0: [(0, "s")]}},
    "CONSTRAINED_LAGRANGE_IN_SOLID": _off_constrained_lagrange_in_solid,

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
    "LOAD_SEGMENT": {"data": (0, [(0, "f"), (3, "n"), (4, "n"), (5, "n"),
                                  (6, "n"), (7, "n")]), "idhdr": "r"},
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
        for idx in range(toff + start, len(raw), stride):
            if raw[idx].strip():
                new = _rewrite_line(raw[idx], mods, offsets, w)
                if new is not None:
                    raw[idx] = new


def _apply_offsets(p: PendingInclude, warn) -> None:
    unmapped: Set[str] = set()
    for b in p.sub_blocks:
        kw = b.keyword
        spec = _OFFSET_SPECS.get(kw)
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


def _warn_coordinate_bearing(p: PendingInclude, aff: Affine, warn) -> None:
    seen: Set[str] = set()
    rotates = not linear_is_identity(aff)
    for b in p.sub_blocks:
        kw = b.keyword
        if kw in seen:
            continue
        if kw in _POINT_BEARING or (rotates and kw in _DIRECTION_BEARING):
            seen.add(kw)
            warn(f"*INCLUDE_TRANSFORM {p.filename}: the TRANID transform is "
                 f"applied to *NODE coordinates only — *{kw} in this include "
                 "carries literal geometry (points/directions/tensors) that "
                 "was NOT transformed; move or re-orient it manually if it is "
                 "load-bearing. (Node-defined variants follow their nodes "
                 "automatically.)")


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

def finalize(blocks: List[Block]) -> None:
    has_nt = any(b.keyword == "NODE_TRANSFORM" for b in blocks)
    if not PENDING_INCLUDES and not has_nt:
        return
    warn = _warn

    # 1. Bind each pending TRANID to its *DEFINE_TRANSFORMATION Block BEFORE
    #    any id offsetting: the TRANID on the *INCLUDE_TRANSFORM card is in
    #    the INCLUDING file's namespace, i.e. pre-offset ids. Parent scope
    #    is searched first so a nested include resolves its own definition.
    for p in PENDING_INCLUDES:
        if p.tranid > 0:
            p.transform_block = (_find_transform_block(p.parent_blocks, p.tranid)
                                 or _find_transform_block(blocks, p.tranid))
            if p.transform_block is None:
                warn(f"*INCLUDE_TRANSFORM {p.filename}: TRANID={p.tranid} "
                     "matches no *DEFINE_TRANSFORMATION anywhere in the deck "
                     "— the include is NOT transformed; the geometry is wrong "
                     "if the transform is load-bearing.")

    # 2. Id offsets, registration order (= innermost first; nested offsets
    #    accumulate additively because the outer entry's sub_blocks contain
    #    the inner include's blocks).
    for p in PENDING_INCLUDES:
        _warn_units_and_decoration(p, warn)
        if any(p.offsets.values()):
            _apply_offsets(p, warn)

    # 3. Node table: parse-time coordinates, post-offset ids — what the
    #    starter sees when LECTRANSSUB resolves /TRANSFORM node references.
    table = _collect_node_coords(blocks)

    # 4. Geometric transforms, innermost first (LECSUBMOD level walk): the
    #    outer entry re-reads the raw lines its inner include already moved,
    #    composing outer∘inner on the coordinates. The reference table stays
    #    at parse-time coordinates on purpose.
    for p in PENDING_INCLUDES:
        aff = _resolve_pending_affine(p, table, warn)
        if aff is None:
            continue
        _rewrite_node_blocks(p.sub_blocks, aff=aff)
        _warn_coordinate_bearing(p, aff, warn)

    # 5. *NODE_TRANSFORM acts on already-transformed geometry, deck order
    #    (LECTRANS runs after the submodel pass; references read CURRENT
    #    coordinates).
    _apply_node_transforms(blocks, warn)
