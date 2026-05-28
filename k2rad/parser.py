"""
k2rad.parser  –  LS-DYNA .k file parser.

Produces a list of Block objects; each Block holds:
  keyword  – normalised base keyword name (e.g. "CONTROL_IMPLICIT_GENERAL")
  options  – trailing suffix tokens stripped from the keyword (["TITLE"], ["ID"] …)
  raw      – non-comment, non-keyword data lines (stripped of $ comments)

*INCLUDE directives are resolved relative to the directory of the including
file and the blocks from the included file are merged inline.
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
# Main parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_k_file(path: str, _depth: int = 0,
                 _include_path: str = "") -> List[Block]:
    """Parse *path* and return a list of Block objects.

    *INCLUDE directives are resolved relative to the directory of *path* (or
    the current *INCLUDE_PATH prefix when one is active), then merged inline.
    *_depth* guards against circular includes (limit: 50 levels).
    """
    if _depth > 50:
        return []

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

        if kw in ("INCLUDE", "INCLUDE_TRANSFORM"):
            if raw:
                inc_path = _resolve(raw[0])
                if os.path.isfile(inc_path):
                    blocks.extend(parse_k_file(inc_path, _depth + 1, include_path))
                else:
                    print(f"  [INCLUDE] WARNING: file not found: {inc_path}", file=sys.stderr)

        elif kw == "INCLUDE_PATH":
            if raw:
                candidate = raw[0].strip()
                if not os.path.isabs(candidate):
                    candidate = os.path.join(base_dir, candidate)
                include_path = candidate

        elif kw == "INCLUDE_PATH_RELATIVE":
            if raw:
                candidate = raw[0].strip()
                include_path = os.path.join(base_dir, candidate)

        else:
            blocks.append(Block(kw, opts, raw))

        kw, opts, raw = None, [], []   # type: ignore[assignment]

    with open(path, "r", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n\r")

            if not line or line.startswith("$") or line.startswith("//"):
                continue

            if line.startswith("*"):
                _flush()
                token_match = re.match(r"\*(\S+)", line)
                if token_match:
                    kw, opts = _split_keyword(token_match.group(1))
                else:
                    kw, opts = "UNKNOWN", []
                raw = []
            else:
                if kw is not None:
                    stripped = _strip_inline_comment(line)
                    if stripped:
                        raw.append(stripped)

    _flush()
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
    """Whitespace-split, stripping inline $ comments first."""
    return _strip_inline_comment(line).split()


def to_float(s: str, default: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def to_int(s: str, default: int = 0) -> int:
    """Safe int-from-float-string conversion."""
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default
