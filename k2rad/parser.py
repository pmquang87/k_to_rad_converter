"""
k2rad.parser  –  LS-DYNA .k file parser.

Produces a list of Block objects; each Block holds:
  keyword  – normalised base keyword name (e.g. "CONTROL_IMPLICIT_GENERAL")
  options  – trailing suffix tokens stripped from the keyword (["TITLE"], ["ID"] …)
  raw      – non-comment, non-keyword data lines (stripped of $ comments)

*INCLUDE directives are resolved relative to the directory of the including
file and the blocks from the included file are merged inline.
*INCLUDE_TRANSFORM additionally applies its id offsets and TRANID transform
numerically to the included blocks (see k2rad.assembly) in a deferred
resolution pass at the end of the top-level parse.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import List


# ─────────────────────────────────────────────────────────────────────────────
# Block
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Block:
    """One LS-DYNA keyword section."""
    keyword: str          # e.g. "CONTROL_IMPLICIT_GENERAL"
    options: List[str]    # e.g. ["TITLE"] or []
    raw: List[str] = field(default_factory=list)  # stripped data lines


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

_TRAILING = frozenset({"ID", "TITLE", "SUBTITLE"})


def _split_keyword(token: str):
    """Split *KEYWORD_OPTION token into (base, options).

    Strips trailing _ID / _TITLE / _SUBTITLE while keeping the rest intact.
    Examples:
      CONTROL_IMPLICIT_GENERAL       → ("CONTROL_IMPLICIT_GENERAL", [])
      MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE → ("MAT_PIECEWISE_LINEAR_PLASTICITY", ["TITLE"])
      CONTACT_AUTOMATIC_SINGLE_SURFACE_ID   → ("CONTACT_AUTOMATIC_SINGLE_SURFACE", ["ID"])
      BOUNDARY_PRESCRIBED_MOTION_RIGID      → ("BOUNDARY_PRESCRIBED_MOTION_RIGID", [])
      SET_NODE_LIST_TITLE                   → ("SET_NODE_LIST", ["TITLE"])
    """
    parts = token.upper().split("_")
    options: List[str] = []
    while parts and parts[-1] in _TRAILING:
        options.insert(0, parts.pop())
    base = "_".join(parts)
    # Guard: if stripping left an empty base, the whole token is the keyword
    if not base:
        base = token.upper()
        options = []
    return base, options


def _strip_inline_comment(line: str) -> str:
    """Remove everything from the first $ onward."""
    idx = line.find("$")
    return line[:idx].rstrip() if idx >= 0 else line.rstrip()


# ─────────────────────────────────────────────────────────────────────────────
# *PARAMETER support
# ─────────────────────────────────────────────────────────────────────────────
# LS-DYNA parameters are define-before-use, so parse_k_file collects them in a
# streaming pass (shared across *INCLUDE recursion) and to_float/to_int resolve
# "&name" field references at conversion time. Names are case-insensitive.
# Module-level tables: reset at the start of each top-level parse_k_file call;
# they must SURVIVE the parse (handlers call to_float on the stored field
# strings during dispatch, after parsing has finished).
_PARAMS: dict = {}
PARSER_WARNINGS: List[str] = []
_PARAM_TYPE_CHARS = frozenset("RICric")


def _resolve_param(token: str):
    """Resolve a ``&name`` (or ``-&name``) field reference against _PARAMS.

    Returns the parameter's value string (sign-folded), or None if *token* is
    not a parameter reference / the name is unknown (a warning is recorded for
    unknown names).
    """
    t = token.strip()
    sign = ""
    if t[:1] in "+-" and t[1:2] == "&":
        sign = "-" if t[0] == "-" else ""
        t = t[1:]
    if not t.startswith("&"):
        return None
    name = t[1:].strip().lower()
    val = _PARAMS.get(name)
    if val is None:
        msg = (f"*PARAMETER reference '&{name}' is undefined — "
               "field treated as blank (0)")
        if msg not in PARSER_WARNINGS:
            PARSER_WARNINGS.append(msg)
        return None
    if sign == "-":
        v = val.strip()
        return v[1:] if v.startswith("-") else "-" + v
    return val


def _collect_parameters(kw: str, raw: List[str]) -> None:
    """Store the name→value pairs of a *PARAMETER block in _PARAMS.

    Card format (R16 Vol I): up to 4 (PRMR, VAL) pairs of 10-char fields per
    card; PRMR's first character is the type (R real, I integer, C character).
    Free (comma/space) format is accepted too. *PARAMETER_EXPRESSION is not
    evaluated — a warning is recorded instead.
    """
    if "EXPRESSION" in kw:
        PARSER_WARNINGS.append(
            "*PARAMETER_EXPRESSION is not evaluated — its parameters stay "
            "undefined; fields referencing them parse as 0")
        return

    def _is_number(tok: str) -> bool:
        return to_float(tok, float("nan")) == to_float(tok, float("nan"))

    for line in raw:
        if not line.strip():
            continue
        pairs: List[tuple] = []
        if "," not in line:
            # Fixed format (the standard): (A10, A10) pairs — PRMR is the type
            # char (R/I/C) followed by the name, VAL the value. Keep only pairs
            # whose value field really is a number (guards against a free-format
            # line that happens to slice weirdly).
            fields = parse_fixed(line, n=8, w=10)
            for i in range(0, 8, 2):
                prmr, val = fields[i], fields[i + 1]
                if prmr and val and prmr[:1] in _PARAM_TYPE_CHARS and _is_number(val):
                    pairs.append((prmr[1:], val))
        if not pairs:
            # Free (comma/space) format: either "R name value ..." with the
            # type char as its own token, or glued "Rname value ...".
            toks = [t for t in parse_free(line) if t]
            i = 0
            while i < len(toks) - 1:
                if (len(toks[i]) == 1 and toks[i] in _PARAM_TYPE_CHARS
                        and i + 2 < len(toks) and _is_number(toks[i + 2])):
                    pairs.append((toks[i + 1], toks[i + 2]))
                    i += 3
                elif (len(toks[i]) > 1 and toks[i][:1] in _PARAM_TYPE_CHARS
                        and _is_number(toks[i + 1])):
                    pairs.append((toks[i][1:], toks[i + 1]))
                    i += 2
                else:
                    i += 1
        for name, val in pairs:
            name = name.strip().lower()
            if name:
                _PARAMS[name] = val.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_k_file(path: str, _depth: int = 0,
                 _include_path: str = "") -> List[Block]:
    """Parse *path* and return a list of Block objects.

    *INCLUDE directives are resolved relative to the directory of *path* (or
    the current *INCLUDE_PATH prefix when one is active), then merged inline.
    *_depth* guards against circular includes (limit: 50 levels).
    """
    # Imported lazily to avoid a module-level import cycle (assembly uses the
    # parser's field helpers; by the first parse call this module is complete).
    from . import assembly as _assembly

    if _depth > 50:
        return []

    if _depth == 0:
        # Fresh top-level parse: reset the *PARAMETER table, the warning list
        # and the pending *INCLUDE_TRANSFORM registrations. The first two
        # persist after the parse — handlers resolve "&name" fields via
        # to_float/to_int during dispatch, and convert() collects the warnings.
        _PARAMS.clear()
        PARSER_WARNINGS.clear()
        _assembly.reset()

    base_dir = os.path.dirname(os.path.abspath(path))
    blocks: List[Block] = []
    kw: str | None = None
    opts: List[str] = []
    raw: List[str] = []
    include_path = _include_path   # current *INCLUDE_PATH prefix

    def _resolve(filename: str) -> str:
        filename = filename.strip()
        if os.path.isabs(filename):
            return filename
        # Try INCLUDE_PATH prefix first, then the including file's directory
        if include_path:
            candidate = os.path.join(include_path, filename)
            if os.path.isfile(candidate):
                return candidate
        return os.path.join(base_dir, filename)

    def _flush() -> None:
        nonlocal kw, opts, raw, include_path
        if kw is None:
            return

        # raw may now contain leading "" placeholders for blank data cards, so
        # use the first non-blank entry as the filename/path argument.
        nonblank = [r for r in raw if r.strip()]

        if kw == "INCLUDE":
            # One filename per card; a single *INCLUDE may list several files.
            for fname in nonblank:
                inc_path = _resolve(fname)
                if os.path.isfile(inc_path):
                    blocks.extend(parse_k_file(inc_path, _depth + 1, include_path))
                else:
                    print(f"  [INCLUDE] WARNING: file not found: {inc_path}", file=sys.stderr)
                    PARSER_WARNINGS.append(f"*INCLUDE file not found: {inc_path}")

        elif kw == "INCLUDE_TRANSFORM":
            # Card 1 = filename; card 2 = IDNOFF..IDDOFF; card 3 = IDROFF /
            # PREFIX / SUFFIX; card 4 = FCTMAS FCTTIM FCTLEN FCTTEM INCOUT1
            # [FCTCHG]; card 5 = TRANID. The cards are read POSITIONALLY from
            # raw (blank placeholders intact) by assembly.register_...; the id
            # offsets and the TRANID transform are applied numerically to the
            # captured sub-blocks in the deferred resolution pass at the end
            # of the top-level parse (assembly.finalize) — the referenced
            # *DEFINE_TRANSFORMATION may appear before OR after this keyword,
            # even in a different include.
            if nonblank:
                fname = nonblank[0]
                inc_path = _resolve(fname)
                if os.path.isfile(inc_path):
                    sub = parse_k_file(inc_path, _depth + 1, include_path)
                    _assembly.register_include_transform(fname, raw, sub, blocks)
                    blocks.extend(sub)
                else:
                    print(f"  [INCLUDE] WARNING: file not found: {inc_path}", file=sys.stderr)
                    PARSER_WARNINGS.append(f"*INCLUDE_TRANSFORM file not found: {inc_path}")

        elif kw.startswith("PARAMETER"):
            # *PARAMETER / *PARAMETER_LOCAL / *PARAMETER_EXPRESSION — collect
            # name→value pairs for "&name" field resolution (define-before-use).
            _collect_parameters(kw, raw)

        elif kw == "INCLUDE_PATH":
            if nonblank:
                candidate = nonblank[0].strip()
                if not os.path.isabs(candidate):
                    candidate = os.path.join(base_dir, candidate)
                include_path = candidate

        elif kw == "INCLUDE_PATH_RELATIVE":
            if nonblank:
                candidate = nonblank[0].strip()
                include_path = os.path.join(base_dir, candidate)

        else:
            blocks.append(Block(kw, opts, raw))

        kw, opts, raw = None, [], []   # type: ignore[assignment]

    # Read the deck as UTF-8 (matching the UTF-8 the writer emits) so the
    # conversion is byte-for-byte identical regardless of the host locale — the
    # default encoding is cp1252 on Windows, which silently mangles any non-ASCII
    # title/comment. errors="replace" keeps a genuinely non-UTF-8 deck from
    # crashing the parse.
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n\r")

            # Column-1 comment lines never carry data; skip them everywhere so
            # they don't consume a fixed-format card slot inside a block.
            if line.startswith("$") or line.startswith("//"):
                continue

            if line.startswith("*"):
                _flush()
                token_match = re.match(r"\*(\S+)", line)
                if token_match:
                    kw, opts = _split_keyword(token_match.group(1))
                else:
                    kw, opts = "UNKNOWN", []
                raw = []
            elif kw is not None:
                # Inside a block: keep EVERY data line, including an intentionally
                # blank card (an all-blank fixed-format card means "all defaults").
                # Dropping blank cards shifts every following card up by one and
                # misaligns the columns of multi-card keywords (e.g. an empty
                # *CONTROL_IMPLICIT_SOLUTION card-1 would push card-2's value into
                # the dctol slot). Inline $ comments are still stripped; a line
                # that is blank (or becomes blank after stripping) is preserved as
                # "" so it holds its card position. Handlers that build lists from
                # raw skip these "" placeholders (see handlers.py).
                raw.append(_strip_inline_comment(line))
            # else: blank or data line outside any block → ignore

    _flush()
    if _depth == 0:
        # Deferred assembly-transform resolution: apply *INCLUDE_TRANSFORM id
        # offsets + TRANID transforms and *NODE_TRANSFORM node-set transforms
        # by mutating Block.raw in place (handlers re-parse raw during
        # dispatch, so the whole pipeline downstream sees final ids/coords).
        _assembly.finalize(blocks)
    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# Field-level helpers (used by handlers)
# ─────────────────────────────────────────────────────────────────────────────

def parse_fixed(line: str, n: int = 8, w: int = 10) -> List[str]:
    """Extract *n* fixed-width fields of width *w* from *line*."""
    return [
        (line[i * w: (i + 1) * w] if i * w < len(line) else "").strip()
        for i in range(n)
    ]


def parse_free(line: str) -> List[str]:
    """Split a free-format card into fields, stripping inline $ comments first.

    LS-DYNA free format delimits fields with commas and/or whitespace; two
    consecutive commas hold an EMPTY field in its position (meaning "use the
    default"), so comma-split segments are preserved even when blank, while
    whitespace inside a segment splits further without empties.
    """
    data = _strip_inline_comment(line)
    if "," not in data:
        return data.split()
    tokens: List[str] = []
    for part in data.split(","):
        sub = part.split()
        tokens.extend(sub if sub else [""])
    return tokens


# Fortran/LS-DYNA fixed-format numbers often drop the 'E' from the exponent so
# the value fits a 10-column field: "7.85000-9" means 7.85000E-9, "1.5+10" means
# 1.5E+10. Match a +/- sign that directly follows a digit (the dropped-E exponent
# sign) — a leading mantissa sign sits at index 0 and is never preceded by a digit.
_FORTRAN_EXP = re.compile(r"(?<=\d)([+-]\d)")


def to_float(s: str, default: float = 0.0) -> float:
    """Safe float conversion.

    Also accepts the Fortran fixed-format exponent spellings LS-DYNA writes but
    Python's ``float()`` rejects: an E-less exponent (``7.85000-9`` → 7.85e-9)
    and the ``D`` double-precision marker (``7.85D-9`` → 7.85e-9). The repair is
    a fallback tried only when the plain conversion fails, so well-formed numbers
    are unaffected.
    """
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    if not isinstance(s, str):
        return default
    t = s.strip()
    if not t:
        return default
    # *PARAMETER reference: &name (or -&name) → the parameter's value
    if "&" in t[:2]:
        resolved = _resolve_param(t)
        if resolved is None:
            return default
        t = resolved
        try:
            return float(t)
        except (ValueError, TypeError):
            pass
    # Fortran double-precision exponent marker: 1.5D-9 → 1.5E-9
    t = t.replace("D", "E").replace("d", "e")
    # Restore the dropped 'E' on E-less exponents: 7.85000-9 → 7.85000E-9
    t = _FORTRAN_EXP.sub(r"E\1", t)
    try:
        return float(t)
    except (ValueError, TypeError):
        return default


def to_int(s: str, default: int = 0) -> int:
    """Safe int-from-float-string conversion (Fortran exponents allowed; see
    :func:`to_float`)."""
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return int(to_float(s, float(default)))
