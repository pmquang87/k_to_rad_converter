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

from . import paramexpr as _paramexpr


# ─────────────────────────────────────────────────────────────────────────────
# Block
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Block:
    """One LS-DYNA keyword section."""
    keyword: str          # e.g. "CONTROL_IMPLICIT_GENERAL"
    options: List[str]    # e.g. ["TITLE"] or []
    raw: List[str] = field(default_factory=list)  # stripped data lines
    #: The ``*PARAMETER_LOCAL`` bindings that were in scope where this block
    #: was READ, or None when the deck defines none. LS-DYNA parameter scoping
    #: is a PARSE-TIME concept while k2rad resolves ``&name`` LAZILY (handlers
    #: call ``to_float`` during dispatch, long after the file that owns a LOCAL
    #: name has been closed), so the scope has to travel with the block.
    #: ``dispatch`` installs it for the duration of the handler; see
    #: :func:`_current_local_scope`.
    scope: dict | None = None


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

#: name -> True when the parameter was declared ``I`` (integer). The TYPE has
#: to travel with the value, because ``*PARAMETER_EXPRESSION`` honours it:
#: Vol I R17 p.36-9 Remark 2a, *"the integer and real properties of constants
#: and parameters are honored ... So 2/5 becomes 0, but 2.0/5 becomes 0.4."*
_PARAM_IS_INT: dict = {}

#: name -> the raw string of a ``C``-typed parameter. Kept apart from _PARAMS
#: so a character parameter can be REFUSED BY NAME when a field asks for it as
#: a number, instead of silently reading as 0.
_PARAM_TEXT: dict = {}

#: Names declared ``MUTABLE`` on their FIRST definition (Vol I R17 p.36-5
#: Remark 6: the qualifier "must appear on the first definition" and is
#: ignored for character parameters).
_PARAM_MUTABLE: set = set()

#: ``*PARAMETER_DUPLICATION`` DFLAG, p.36-6. **1 is the default and means
#: "warn and IGNORE the new definition"** — first wins. This parser used to
#: overwrite unconditionally, i.e. LAST wins, the exact opposite of LS-DYNA's
#: default.
#:
#: The second cell is the Remark-2 latch: *"Only one \*PARAMETER_DUPLICATION
#: card is allowed. If more than one is found, a warning is issued and any
#: after the first are ignored."* The card is itself first-wins, and it is the
#: card that DECIDES first-wins for everything else — reading a second one
#: would let the deck's LAST duplication policy govern its FIRST parameter
#: definitions, which is neither LS-DYNA's behaviour nor internally coherent.
_PARAM_DUPLICATION = [1, False]

#: LS-DYNA disallows this name outright (p.36-3), case-insensitively.
_PARAM_RESERVED_NAMES = frozenset({"time"})

#: One frame per *INCLUDE level: ``name -> the (value, is_int, text) this
#: level's LOCAL definition MASKED``, or ``None`` when it masked nothing.
#: Vol I R17 p.36-4 Remark 5: a LOCAL parameter "disappears when the input
#: parser finishes reading the file in which it appears" and may temporarily
#: MASK a non-LOCAL one of the same name. The frame is popped on the way out
#: of parse_k_file and the masked value restored.
_PARAM_LOCAL_STACK: List[dict] = [{}]

#: The scope snapshot handed to the Block being flushed, rebuilt only when a
#: LOCAL frame changed. ``None`` = no LOCAL name is in scope, which is every
#: deck that does not use *PARAMETER_LOCAL — those pay nothing.
_LOCAL_SNAPSHOT: List = [None, True]     # [snapshot, dirty]

#: The scope of the block currently being dispatched, installed by
#: ``handlers.dispatch``. Consulted BEFORE the global table, so a ``&name``
#: inside the file that declared it LOCAL still resolves after that file has
#: been closed and its binding removed from _PARAMS.
_ACTIVE_SCOPE: List = [None]


def _current_local_scope():
    """The LOCAL bindings visible right now, as ``name -> (val, is_int, text)``.

    ``None`` when no LOCAL name is in scope. The dict is SHARED by every block
    flushed between two changes of the local frames, so a 100k-block deck pays
    one small dict, not 100k.
    """
    if _LOCAL_SNAPSHOT[1]:
        names: set = set()
        for frame in _PARAM_LOCAL_STACK[1:]:
            names |= set(frame)
        _LOCAL_SNAPSHOT[0] = ({
            n: (_PARAMS.get(n), _PARAM_IS_INT.get(n, False), _PARAM_TEXT.get(n))
            for n in names} if names else None)
        _LOCAL_SNAPSHOT[1] = False
    return _LOCAL_SNAPSHOT[0]


def set_active_scope(scope):
    """Install *scope* (a Block's) as the one ``&name`` resolves against.

    Returns the previous value so the caller can restore it — ``dispatch``
    does this around every handler call.
    """
    prev = _ACTIVE_SCOPE[0]
    _ACTIVE_SCOPE[0] = scope
    return prev


def _scoped(name: str):
    """``(value, is_int, text)`` for *name* from the active block scope, or
    None when the active block's file declared no such LOCAL parameter."""
    scope = _ACTIVE_SCOPE[0]
    return scope.get(name) if scope else None


def _param_lookup(name: str):
    """``(value, is_int)`` for the evaluator, or None when undefined.

    A ``C``-typed parameter is a REFUSAL, not an undefined name: it exists,
    but Vol I R17 p.36-7 says a character expression is *"not evaluated in any
    sense, just stored as a string"*, so using one arithmetically is a deck
    error worth naming.
    """
    key = name.lstrip("&").strip().lower()
    local = _scoped(key)
    if local is not None:
        val, is_int, text = local
    else:
        val, is_int, text = (_PARAMS.get(key), _PARAM_IS_INT.get(key, False),
                             _PARAM_TEXT.get(key))
    if text is not None:
        raise _paramexpr.ExprError(
            f"'&{key}' is a CHARACTER parameter (type C). Vol I R17 p.36-7: "
            "for type C the expression is 'not evaluated in any sense, just "
            "stored as a string', so it has no numeric value to compute with")
    if val is None:
        return None
    try:
        return (int(val), True) if is_int else (float(val), False)
    except ValueError:
        try:
            return (float(val), False)
        except ValueError:
            raise _paramexpr.ExprError(
                f"'&{key}' holds '{val}', which is not a number")


def _warn_once(msg: str) -> None:
    if msg not in PARSER_WARNINGS:
        PARSER_WARNINGS.append(msg)


def _resolve_param(token: str):
    """Resolve a parameter reference in one data field against _PARAMS.

    Handles three forms:

    * ``&name`` and ``-&name`` — the bare reference, with Remark 1's sign fold
      (*"If a minus sign is placed directly before &, with no space, the sign
      of the numerical value will be switched"*, p.36-3).
    * ``&name<arith>`` — inline arithmetic in a fixed-width field, e.g.
      ``&tend/6.0``. The manual documents only the bracketed form for data
      fields (Remark 1, p.36-8, comma-delimited lines), but LSTC's own example
      ``efg/metal-cutting/main.k`` writes ``&dtimpl/6.`` and ``&tend/6.0``
      into plain 10-char columns and LS-DYNA accepts them — so both are read.
      MEASURED loss before this: that deck's TRISE came out 0 instead of
      0.005, and the back-solved VMAX 300 mm/s instead of 360.
    * ``<expr>`` — Remark 1's bracketed form, where the names appear WITHOUT
      the leading ``&``.

    Returns the value string, or None if *token* is not a parameter reference
    at all / the reference cannot be resolved (a warning is recorded).
    """
    t = token.strip()
    if not t:
        return None
    bracketed = t.startswith("<") and t.endswith(">")
    if not bracketed and "&" not in t:
        return None
    if bracketed or _paramexpr.is_expression(t):
        try:
            return _paramexpr.format_value(
                _paramexpr.evaluate(t, _param_lookup))
        except _paramexpr.ExprError as exc:
            _warn_once(
                f"*PARAMETER expression '{t}' in a data field could not be "
                f"evaluated: {exc}. The field was read as blank (0).")
            return None
    sign = ""
    if t[:1] in "+-" and t[1:2] == "&":
        sign = "-" if t[0] == "-" else ""
        t = t[1:]
    if not t.startswith("&"):
        return None
    name = t[1:].strip().lower()
    local = _scoped(name)
    val, text = ((local[0], local[2]) if local is not None
                 else (_PARAMS.get(name), _PARAM_TEXT.get(name)))
    if text is not None:
        _warn_once(
            f"*PARAMETER reference '&{name}' names a CHARACTER parameter "
            f"(type C, value '{text}') where a number is "
            "expected — field treated as blank (0). Vol I R17 p.36-3 Remark 2 "
            "gives C parameters a STRING substitution role (&NAME^ inside a "
            "larger string, e.g. a filename), which this converter does not "
            "perform.")
        return None
    if val is None:
        _warn_once(f"*PARAMETER reference '&{name}' is undefined — "
                   "field treated as blank (0)")
        return None
    if sign == "-":
        v = val.strip()
        return v[1:] if v.startswith("-") else "-" + v
    return val


def _store_parameter(name: str, val: str, type_char: str, kw: str) -> None:
    """Apply one (name, value) definition under the manual's own rules.

    Redefinition follows ``*PARAMETER_DUPLICATION`` DFLAG (Vol I R17 p.36-6),
    whose DEFAULT is 1 = "warn and IGNORE the new definition" — **first wins**.
    This parser used to overwrite unconditionally, i.e. last wins, the exact
    opposite. ``MUTABLE`` (Remark 6, p.36-5) allows redefinition regardless of
    DFLAG, and must appear on the FIRST definition to count.
    """
    name = name.strip().lower()
    if not name:
        return
    if name in _PARAM_RESERVED_NAMES:
        _warn_once(f"*PARAMETER: '{name}' is a name LS-DYNA disallows "
                   "(Vol I R17 p.36-3) — the definition was ignored.")
        return
    if name[:1].isdigit():
        _warn_once(f"*PARAMETER: '{name}' starts with a digit, which Vol I "
                   "R17 p.36-3 forbids — the definition was ignored.")
        return
    is_c = type_char.upper() == "C"
    known = name in _PARAMS or name in _PARAM_TEXT
    is_local = "LOCAL" in kw.split("_")
    # Is the definition this one would hide itself LOCAL? Vol I R17 p.36-6
    # Remark 1 scopes the duplication exemption precisely: "A LOCAL variable
    # appearing in a file, which masks a non-LOCAL parameter, won't trigger
    # these actions; however, a LOCAL that masks another LOCAL or a non-LOCAL
    # that masks a non-LOCAL will." So only LOCAL-over-NON-LOCAL is exempt.
    masks_a_local = any(name in frame for frame in _PARAM_LOCAL_STACK[1:])
    if known and is_local and name not in _PARAM_LOCAL_STACK[-1]:
        # A LOCAL definition MASKS whatever is in scope rather than replacing
        # it. Remember the hidden value IN THIS FRAME so _pop_local_scope can
        # restore it at the end of this file — per-frame, because two include
        # levels may mask the same name and the inner pop must restore the
        # OUTER one, not the outermost. Recorded even when the duplication
        # actions do apply, so a DFLAG that ACCEPTS the redefinition still
        # unwinds correctly.
        _PARAM_LOCAL_STACK[-1].setdefault(
            name, (_PARAMS.get(name), _PARAM_IS_INT.get(name, False),
                   _PARAM_TEXT.get(name)))
        if not masks_a_local:
            known = False
    if known:
        dflag = _PARAM_DUPLICATION[0]
        mutable = name in _PARAM_MUTABLE
        # "MUTABLE" also does not apply to character parameters (Remark 6).
        if not mutable or is_c:
            if dflag in (1, 3):
                if dflag != 5:
                    _warn_once(
                        f"*PARAMETER '{name}' is defined more than once. "
                        f"*PARAMETER_DUPLICATION DFLAG = {dflag}, so LS-DYNA "
                        "keeps the FIRST definition and ignores the later "
                        "one(s) — which is what this converter does"
                        + (" (DFLAG 3 also terminates at the end of input, so "
                           "the deck would not run as written)"
                           if dflag == 3 else "")
                        + ". Add the MUTABLE option to the FIRST definition, "
                        "or *PARAMETER_DUPLICATION with DFLAG 2 or 4, to let "
                        "the later value win.")
                return
            if dflag == 5:
                return
            if dflag == 2:
                _warn_once(
                    f"*PARAMETER '{name}' is defined more than once and "
                    "*PARAMETER_DUPLICATION DFLAG = 2, so the LATER "
                    "definition wins (LS-DYNA warns here too).")
    elif "MUTABLE" in kw:
        _PARAM_MUTABLE.add(name)
    if is_c:
        _PARAM_TEXT[name] = val.strip()
        _PARAMS.pop(name, None)
        _PARAM_IS_INT.pop(name, None)
    else:
        _PARAMS[name] = val.strip()
        _PARAM_IS_INT[name] = type_char.upper() == "I"
        _PARAM_TEXT.pop(name, None)
    if is_local:
        # None = "this LOCAL masked nothing", so the pop removes it outright.
        _PARAM_LOCAL_STACK[-1].setdefault(name, None)
    if is_local or name in _PARAM_LOCAL_STACK[-1]:
        _LOCAL_SNAPSHOT[1] = True


def _collect_parameters(kw: str, raw: List[str]) -> None:
    """Store the name→value pairs of a *PARAMETER block in _PARAMS.

    Card format (Vol I R17 p.36-2): up to 4 (PRMR, VAL) pairs of 10-char
    fields per card; PRMR's first character is the type (R real, I integer,
    C character). Free (comma/space) format is accepted too.

    ``*PARAMETER_EXPRESSION`` (p.36-7) is a DIFFERENT card: ONE 10-char PRMR
    followed by the expression as free text to the end of the line, which may
    continue onto further lines "simply by leaving the first 10 characters of
    the continuation line blank". It is evaluated here, at parse time, so
    every downstream ``&name`` consumer is untouched — see
    :mod:`k2rad.paramexpr` for the grammar and for the three rules that make
    an ``eval()`` wrong.

    ``*PARAMETER_TYPE`` (p.36-11) IS a definition: *"*PARAMETER_TYPE is a
    variation on the *PARAMETER keyword command.  In addition to its basic
    function of associating a parameter name (PRMR) with a numerical value
    (VAL), the *PARAMETER_TYPE command also includes information (PRTYP) about
    how the parameter is used by LS-DYNA"* — Card 1 is ``PRMR VAL PRTYP`` with
    PRMR an ``I``-typed name (p.36-12). Only PRTYP is the LS-PrePost id-offset
    hint, and it is a type NAME, never a value; the ordinary pair scan below
    drops it on its own because "PART"/"SET_NODE"/... does not start with R, I
    or C followed by a number.
    """
    if "TYPE" in kw.split("_"):
        _warn_once(
            "*PARAMETER_TYPE: the name and VALUE are read exactly like a "
            "*PARAMETER definition (Vol I R17 p.36-11: 'a variation on the "
            "*PARAMETER keyword command ... its basic function of associating "
            "a parameter name (PRMR) with a numerical value (VAL)'). Only the "
            "third cell PRTYP is dropped: it tells LS-PrePost which id offset "
            "to apply when decks are merged, and has no solver effect.")

    def _is_number(tok: str) -> bool:
        return to_float(tok, float("nan")) == to_float(tok, float("nan"))

    if "EXPRESSION" in kw:
        _collect_parameter_expressions(kw, raw)
        return

    for line in raw:
        if not line.strip():
            continue
        pairs: List[tuple] = []
        if "," not in line:
            # Fixed format (the standard): (A10, A10) pairs — PRMR is the type
            # char (R/I/C) followed by the name, VAL the value. Keep only pairs
            # whose value field really is a number (guards against a free-format
            # line that happens to slice weirdly), EXCEPT for type C, whose
            # value is a string by definition.
            fields = parse_fixed(line, n=8, w=10)
            for i in range(0, 8, 2):
                prmr, val = fields[i], fields[i + 1]
                if (prmr and val and prmr[:1] in _PARAM_TYPE_CHARS
                        and (_is_number(val) or prmr[:1] in "Cc")):
                    pairs.append((prmr[1:], val, prmr[:1]))
        if not pairs:
            # Free (comma/space) format: either "R name value ..." with the
            # type char as its own token, or glued "Rname value ...".
            toks = [t for t in parse_free(line) if t]
            i = 0
            while i < len(toks) - 1:
                if (len(toks[i]) == 1 and toks[i] in _PARAM_TYPE_CHARS
                        and i + 2 < len(toks)
                        and (_is_number(toks[i + 2]) or toks[i] in "Cc")):
                    pairs.append((toks[i + 1], toks[i + 2], toks[i]))
                    i += 3
                elif (len(toks[i]) > 1 and toks[i][:1] in _PARAM_TYPE_CHARS
                        and (_is_number(toks[i + 1]) or toks[i][:1] in "Cc")):
                    pairs.append((toks[i][1:], toks[i + 1], toks[i][:1]))
                    i += 2
                else:
                    i += 1
        for name, val, tch in pairs:
            _store_parameter(name, val, tch, kw)


def _collect_parameter_expressions(kw: str, raw: List[str]) -> None:
    """``*PARAMETER_EXPRESSION``: ``PRMR1`` in cols 1-10, the expression after.

    Continuation (p.36-7): *"The expression can be continued on multiple lines
    simply by leaving the first 10 characters of the continuation line
    blank."* So a record is claimed by RAW CONTIGUITY from its PRMR row, the
    same rule the offset walkers use (#119) — a "next non-blank" walk would
    misread a continuation as a new parameter.

    **The comma form splits at the COMMA, not at column 10.** p.36-8 Remark
    1's own worked example is comma-delimited::

        *parameter
        rterm, 0.2, istates,  80
        *parameter_expression
        rplot,term/(states-30)

    and states it is equivalent to ``<term/(states-30)>``, i.e. 0.004.
    Slicing ``line[10:]`` unconditionally cut that expression to
    ``/(states-30)`` — the leading ``term`` eaten by the 10-column field —
    and lost a whole record whenever the value fits inside ten columns
    (``rxmin, -96`` is exactly ten characters, so the expression came out
    EMPTY). Real carrier: dynaexamples
    ``IGA_tensile_test_input/tensile_test_iga.k`` writes four such base
    parameters and eight box parameters referencing them. The comma rule is
    applied only when the comma falls inside the PRMR field (index <= 10);
    beyond that the comma belongs to the expression itself (``max(1,2)``).
    """
    records: List[List[str]] = []
    for line in raw:
        if not line.strip():
            continue
        head = line[:10]
        if head.strip():
            comma = line.find(",")
            if 0 <= comma <= 10:
                records.append([line[:comma], line[comma + 1:]])
            else:
                records.append([head, line[10:]])
        elif records:
            records[-1][1] += " " + line[10:]
        else:
            _warn_once(
                "*PARAMETER_EXPRESSION: a line leaves the first 10 columns "
                "blank with no parameter above it to continue (Vol I R17 "
                "p.36-7 makes a blank PRMR field a CONTINUATION) — ignored.")
    for prmr, expr in records:
        prmr = prmr.strip()
        if not prmr or prmr[:1] not in _PARAM_TYPE_CHARS:
            _warn_once(
                f"*PARAMETER_EXPRESSION: '{prmr}' does not start with a type "
                "character (R, I or C — Vol I R17 p.36-7), so the definition "
                "was ignored and every field referencing it reads as 0.")
            continue
        tch, name = prmr[:1], prmr[1:].strip()
        if tch.upper() == "C":
            # p.36-7: "For type C parameters, the expression is not evaluated
            # in any sense, just stored as a string."
            _store_parameter(name, expr.strip(), tch, kw)
            continue
        try:
            value = _paramexpr.evaluate(expr, _param_lookup)
        except _paramexpr.ExprError as exc:
            _warn_once(
                f"*PARAMETER_EXPRESSION '{name} = {expr.strip()}' could not "
                f"be evaluated: {exc}. The parameter stays UNDEFINED and every "
                "field referencing it reads as 0.")
            continue
        if tch.upper() == "I" and not value[1]:
            # An I-typed parameter takes the integer part of a real result,
            # which is what makes the type declaration meaningful downstream
            # (2/5 vs 2.0/5, Remark 2a).
            value = (int(value[0]), True)
        _store_parameter(name, _paramexpr.format_value(value), tch, kw)


def _pop_local_scope() -> None:
    r"""Discard this file's LOCAL parameters and restore anything they masked.

    Vol I R17 p.36-4/5 Remark 5's worked example, on the three cells this
    function is responsible for: ``VAL2 = 20.0`` inside the include and
    ``2.0`` again after it returns, ``VAL3 = 3.0`` throughout, and ``VAL4``
    gone. So a LOCAL definition is a MASK, not an overwrite: what it hid comes
    back.

    **The example's fourth cell is one the two manual pages disagree about,
    and k2rad follows p.36-6.** ``file1`` also carries a plain, non-LOCAL
    ``R VAL1 10.0``, and p.36-5 says main.k then sees ``VAL1 = 10.0``. But
    that is a duplicate definition of a non-LOCAL parameter, which p.36-6
    governs: DFLAG's Default is 1, *"issue a warning and ignore the new
    definition"*, and Remark 1 says explicitly that *"a non-LOCAL that masks a
    non-LOCAL will"* trigger those actions. k2rad therefore keeps
    ``VAL1 = 1.0`` in both places and warns — p.36-5's example is illustrating
    LOCAL scoping, not duplication policy, and predates the MUTABLE work.
    Two independent things back the p.36-6 reading over the example:
    p.36-5 Remark 6 introduces MUTABLE as the way to redefine *"regardless of
    the setting of \*PARAMETER_DUPLICATION"*, and the R17 release notes on
    Vol I p.138 spell the premise out — *"to indicate that it is OK to redefine
    a specific parameter even if \*PARAMETER_DUPLICATION says redefinition is
    not allowed"*. An opt-in escape hatch only makes sense if the default
    state is "not allowed", i.e. first-wins. (Master was last-wins, so this is
    the one place the batch changed a resolved parameter VALUE on decks that
    redefine a global parameter inside an include; see
    ``TestParameterDuplicationFirstWins`` for the fence.)

    **This affects the GLOBAL table only.** Every Block read while the frame
    was live carries the frame's bindings in ``Block.scope``, so the cards of
    the file that declared the LOCAL still resolve it during dispatch.
    Popping without that snapshot is what turned a runnable deck into
    ``Thick 0`` and a starter ERROR 495: k2rad resolves ``&name`` lazily,
    long after the file has been closed. The same lateness is why
    ``assembly._scoped_block`` re-installs ``Block.scope`` around the
    *INCLUDE_TRANSFORM offset and geometry walks, which run after this pop.
    """
    if len(_PARAM_LOCAL_STACK) <= 1:
        return
    frame = _PARAM_LOCAL_STACK.pop()
    _LOCAL_SNAPSHOT[1] = True
    for name, saved in frame.items():
        _PARAMS.pop(name, None)
        _PARAM_IS_INT.pop(name, None)
        _PARAM_TEXT.pop(name, None)
        _PARAM_MUTABLE.discard(name)
        if saved is not None:
            val, is_int, text = saved
            if text is not None:
                _PARAM_TEXT[name] = text
            elif val is not None:
                _PARAMS[name] = val
                _PARAM_IS_INT[name] = is_int


def _set_parameter_duplication(raw: List[str]) -> None:
    r"""``*PARAMETER_DUPLICATION`` — one card, one cell, Vol I R17 p.36-6.

    DFLAG 1 warn + ignore the new definition (DEFAULT), 2 warn + accept,
    3 error + ignore (terminates at the end of input), 4 accept silently,
    5 ignore silently.

    Remark 2 is verbatim: *"Multiple Cards. Only one \*PARAMETER_DUPLICATION
    card is allowed. If more than one is found, a warning is issued and any
    after the first are ignored."* The rule was quoted here and NOT
    implemented — the assignment below used to be unconditional, so a second
    card won. MEASURED on the twin ``DFLAG 1`` then ``DFLAG 2`` then
    ``R thk 1.0`` then ``R thk 9.0``: k2rad ended with DFLAG 2 and
    ``thk = 9.0``; LS-DYNA ignores the second card, keeps DFLAG 1 and
    ``thk = 1.0``. That is a parameter VALUE, so it reaches the emitted deck.
    """
    for line in raw:
        if not line.strip():
            continue
        toks = parse_free(line) if "," in line else [line[:10].strip()]
        try:
            dflag = int(float(toks[0]))
        except (ValueError, IndexError):
            _warn_once("*PARAMETER_DUPLICATION: DFLAG is not a number — the "
                       "default 1 (warn, keep the FIRST definition) is used.")
            return
        if dflag not in (1, 2, 3, 4, 5):
            _warn_once(f"*PARAMETER_DUPLICATION: DFLAG = {dflag} is not one "
                       "of 1..5 (Vol I R17 p.36-6) — the default 1 (warn, "
                       "keep the FIRST definition) is used.")
            return
        if _PARAM_DUPLICATION[1]:
            if dflag != _PARAM_DUPLICATION[0]:
                _warn_once(
                    f"*PARAMETER_DUPLICATION: a second card asks for "
                    f"DFLAG = {dflag}, but Vol I R17 p.36-6 Remark 2 allows "
                    "only ONE such card and ignores every one after the "
                    f"first — DFLAG = {_PARAM_DUPLICATION[0]} stands. Delete "
                    "the duplicate card if the later value is the intended "
                    "one.")
            return
        _PARAM_DUPLICATION[0] = dflag
        _PARAM_DUPLICATION[1] = True
        return


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
        _PARAM_IS_INT.clear()
        _PARAM_TEXT.clear()
        _PARAM_MUTABLE.clear()
        _PARAM_DUPLICATION[0], _PARAM_DUPLICATION[1] = 1, False
        del _PARAM_LOCAL_STACK[1:]
        _PARAM_LOCAL_STACK[0].clear()
        _LOCAL_SNAPSHOT[0], _LOCAL_SNAPSHOT[1] = None, True
        _ACTIVE_SCOPE[0] = None
        PARSER_WARNINGS.clear()
        _assembly.reset()

    # Vol I R17 p.36-4 Remark 5: a LOCAL parameter lives only for the file it
    # is defined in, and may MASK a non-LOCAL one of the same name while it
    # does. One stack frame per file; _pop_local_scope pops it. Every Block
    # flushed while the frame is live captures its bindings in Block.scope,
    # because resolution happens later (see _current_local_scope).
    _PARAM_LOCAL_STACK.append({})
    _LOCAL_SNAPSHOT[1] = True

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
            # *PARAMETER / *PARAMETER_LOCAL / *PARAMETER_EXPRESSION[_LOCAL] /
            # *PARAMETER_MUTABLE / *PARAMETER_DUPLICATION / *PARAMETER_TYPE.
            # Collected here, in a streaming pass, because LS-DYNA parameters
            # are DEFINE-BEFORE-USE (p.36-7: an expression "can reference
            # previously defined parameters"), so the order of the file is the
            # order of definition.
            if kw == "PARAMETER_DUPLICATION" or "DUPLICATION" in kw.split("_"):
                _set_parameter_duplication(raw)
            else:
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
            blocks.append(Block(kw, opts, raw,
                                scope=_current_local_scope()))

        kw, opts, raw = None, [], []

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
    _pop_local_scope()
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
    # *PARAMETER reference. The test used to be ``"&" in t[:2]`` — only a
    # token that STARTS with the sigil — which meant ``2.0*&thick`` and
    # ``(&thick)`` fell straight through to the caller's default with NO
    # diagnostic at all: _resolve_param returned None before it could warn.
    # Any token carrying an ``&``, or the bracketed ``<expr>`` form, is
    # offered to the resolver now; it decides whether it is a bare reference,
    # an inline expression, or neither.
    if "&" in t or (t.startswith("<") and t.endswith(">")):
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
