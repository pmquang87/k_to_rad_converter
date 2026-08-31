"""``*PARAMETER_EXPRESSION`` evaluation — a safe recursive-descent evaluator.

Vol I R17 §36 (pp.36-1 … 36-12) defines the grammar this implements. There is
NO ``eval()`` anywhere here, and there cannot be: three of the manual's rules
are LS-DYNA-specific and Python gets each of them wrong.

**1. Unary minus binds TIGHTER than exponentiation.** Remark 2(d), p.36-9:
*"the unary minus has higher precedence than exponentiation, that is, the
formula ``-3**2`` is interpreted as ``(-3)**2 = 9``."* Python (and Fortran)
give ``-9``. That is a sign error on any deck that writes one.

**2. The integer/real properties of constants AND parameters are honoured.**
Remark 2(a): *"So ``2/5`` becomes ``0``, but ``2.0/5`` becomes ``0.4``."* The
type travels with the value, so an ``I``-typed parameter divided by an integer
literal truncates. Python's ``/`` is always real and its ``//`` floors rather
than truncating (``-7//2`` is ``-4``, Fortran's ``-7/2`` is ``-3``).

**3. The intrinsics are Fortran's, not Python's.** ``sign(x, y)`` is
``|x|`` with the sign of ``y`` (``sign(-4, 8) = 4``, Remark 3), ``mod`` takes
INTEGERS only and rounds real arguments, ``int``/``aint`` truncate toward zero
while ``nint``/``anint`` round, and the two pairs differ only in the TYPE they
return — which feeds rule 2.

Everything the grammar does not cover is REFUSED BY NAME rather than guessed:
an unknown function, a ``C``-typed parameter used arithmetically, a forward
reference, a name that is not defined. Each refusal raises :class:`ExprError`,
whose message the caller turns into a warning naming the expression.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple, Union

__all__ = ["ExprError", "Value", "evaluate", "format_value", "is_expression"]


class ExprError(Exception):
    """A refusal: the expression states something this evaluator will not
    guess at. The message is written to be shown to the user verbatim."""


#: A value carries its LS-DYNA TYPE with it, because the type decides what
#: ``/`` does (Remark 2a). ``True`` = integer.
Value = Tuple[Union[int, float], bool]


def _real(v: Value) -> float:
    return float(v[0])


def _as_int(v: Value) -> int:
    """The value as an integer, ROUNDED if it is real — the rule ``mod``'s
    arguments follow (Remark 2b: "supports integers only ... real arguments
    are rounded")."""
    return int(v[0]) if v[1] else _nint(float(v[0]))


def _nint(x: float) -> int:
    """Fortran NINT: round half AWAY FROM ZERO. Python's round() is
    banker's rounding (round(0.5) == 0), which would be off by one on every
    exact half."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _trunc(x: float) -> int:
    """Fortran INT/AINT: truncate TOWARD ZERO (``int(-48.1) = -48``,
    ``int(0.9) = 0`` — Remark 3)."""
    return int(x)


# ── the intrinsics, Vol I R17 p.36-8 ────────────────────────────────────────
#
# Each entry is (arity, callable, returns_integer). ``returns_integer`` is
# None when the result keeps the argument's own type.
_FUNCS: Dict[str, Tuple[int, Callable, Optional[bool]]] = {
    "sin":   (1, lambda a: math.sin(_real(a)), False),
    "cos":   (1, lambda a: math.cos(_real(a)), False),
    "tan":   (1, lambda a: math.tan(_real(a)), False),
    "csc":   (1, lambda a: 1.0 / math.sin(_real(a)), False),
    "sec":   (1, lambda a: 1.0 / math.cos(_real(a)), False),
    "ctn":   (1, lambda a: 1.0 / math.tan(_real(a)), False),
    "asin":  (1, lambda a: math.asin(_real(a)), False),
    "acos":  (1, lambda a: math.acos(_real(a)), False),
    "atan":  (1, lambda a: math.atan(_real(a)), False),
    "atan2": (2, lambda a, b: math.atan2(_real(a), _real(b)), False),
    "sinh":  (1, lambda a: math.sinh(_real(a)), False),
    "cosh":  (1, lambda a: math.cosh(_real(a)), False),
    "tanh":  (1, lambda a: math.tanh(_real(a)), False),
    "asinh": (1, lambda a: math.asinh(_real(a)), False),
    "acosh": (1, lambda a: math.acosh(_real(a)), False),
    "atanh": (1, lambda a: math.atanh(_real(a)), False),
    "sqrt":  (1, lambda a: math.sqrt(_real(a)), False),
    "exp":   (1, lambda a: math.exp(_real(a)), False),
    "log":   (1, lambda a: math.log(_real(a)), False),
    "log10": (1, lambda a: math.log10(_real(a)), False),
    "abs":   (1, lambda a: abs(a[0]), None),
    "float": (1, lambda a: _real(a), False),
    # min/max keep the type only when BOTH arguments are integers.
    "min":   (2, lambda a, b: min(a[0], b[0]), None),
    "max":   (2, lambda a, b: max(a[0], b[0]), None),
    # Remark 3: sign(x, y) is |x| with the sign of y. sign(-4, 8) = 4.
    "sign":  (2, lambda a, b: (abs(a[0]) if _real(b) >= 0.0
                               else -abs(a[0])), None),
    # Remark 2b: "mod supports integers only ... real arguments are rounded".
    # Fortran MOD truncates toward zero: MOD(-7,2) = -1, not Python's +1.
    "mod":   (2, lambda a, b: math.fmod(_as_int(a), _as_int(b)), True),
    "int":   (1, lambda a: _trunc(_real(a)), True),
    "aint":  (1, lambda a: float(_trunc(_real(a))), False),
    "nint":  (1, lambda a: _nint(_real(a)), True),
    "anint": (1, lambda a: float(_nint(_real(a))), False),
}

#: Appendix U (pp.71-1/71-2) reserves these names as CONSTANTS.
_CONSTANTS: Dict[str, Value] = {
    "pi":   (math.pi, False),
    "dtor": (math.pi / 180.0, False),   # degrees -> radians
    "rtod": (180.0 / math.pi, False),   # radians -> degrees
}

#: Every character that can legally start a bare expression token. Used by
#: :func:`is_expression` to tell "this cell is arithmetic" from "this cell is
#: a plain number or a plain &name".
_OPS = set("+-*/()")


def is_expression(text: str) -> bool:
    """True when *text* is arithmetic rather than a bare number or ``&name``.

    A leading sign is NOT arithmetic (``-&thick`` is the manual's own sign-fold
    form, Remark 1), and neither is an exponent's sign inside a number
    (``1.0E-5``). What makes a cell an expression is an operator or a
    parenthesis that is not part of a numeric literal, or a function call.
    """
    t = text.strip()
    if not t:
        return False
    if t.startswith("<") and t.endswith(">"):
        return True
    body = t[1:] if t[:1] in "+-" else t
    prev = ""
    for k, ch in enumerate(body):
        if ch in _OPS:
            # An exponent sign: the '-' of "1.0E-5" / "1.0D+5".
            if ch in "+-" and prev in "eEdD" and k >= 2:
                prev = ch
                continue
            return True
        prev = ch
    return False


# ── tokenizer ───────────────────────────────────────────────────────────────

_NUM_START = set("0123456789.")
_NAME_START = set("abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ_&")
_NAME_BODY = _NAME_START | set("0123456789")


def _tokenize(src: str) -> List[Tuple[str, object]]:
    """``[(kind, value)]`` with kind in {"num", "name", "op"}."""
    out: List[Tuple[str, object]] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if ch in _NUM_START:
            j = i
            seen_dot = False
            while j < n and (src[j].isdigit() or (src[j] == "." and not seen_dot)):
                seen_dot = seen_dot or src[j] == "."
                j += 1
            # An exponent, in either Fortran spelling.
            if j < n and src[j] in "eEdD":
                k = j + 1
                if k < n and src[k] in "+-":
                    k += 1
                if k < n and src[k].isdigit():
                    while k < n and src[k].isdigit():
                        k += 1
                    j = k
                    seen_dot = True          # an exponent makes it REAL
            text = src[i:j]
            is_int = not seen_dot
            try:
                val = int(text) if is_int else float(text.replace("d", "e")
                                                     .replace("D", "E"))
            except ValueError:               # pragma: no cover - guarded above
                raise ExprError(f"'{text}' is not a number")
            out.append(("num", (val, is_int)))
            i = j
            continue
        if ch in _NAME_START:
            j = i + 1
            while j < n and src[j] in _NAME_BODY:
                j += 1
            out.append(("name", src[i:j]))
            i = j
            continue
        if ch == "*" and src[i:i + 2] == "**":
            out.append(("op", "**"))
            i += 2
            continue
        if ch in "+-*/(),":
            out.append(("op", ch))
            i += 1
            continue
        raise ExprError(
            f"the character '{ch}' has no meaning in a *PARAMETER_EXPRESSION "
            "(Vol I R17 p.36-8 allows + - * / ** , parentheses, numbers, "
            "parameter names and the listed intrinsic functions)")
    return out


# ── parser ──────────────────────────────────────────────────────────────────

#: Nesting cap for the recursive descent. Well below CPython's own recursion
#: limit (each level costs several frames), and far beyond anything a real
#: deck writes: the deepest expression in the whole corpus nests 3 levels.
#: Exceeding it is a NAMED refusal, not a RecursionError escaping into the
#: caller and killing the conversion.
_MAX_DEPTH = 60


class _Parser:
    """Recursive descent over the token list.

    Precedence, lowest first::

        expr    := term   (('+' | '-') term)*
        term    := power  (('*' | '/') power)*
        power   := signed ('**' power)?          <- right-associative
        signed  := ('+' | '-')* atom             <- INSIDE the power's base
        atom    := number | name | func '(' args ')' | '(' expr ')'

    ``signed`` being the BASE of ``power`` — rather than a level above it — is
    what makes ``-3**2`` evaluate as ``(-3)**2 = 9`` (Remark 2d, p.36-9)
    instead of Python's and Fortran's ``-(3**2) = -9``. Note the exponent is
    itself a ``power``, so ``2**-1`` still reads as ``2**(-1) = 0.5``.
    """

    def __init__(self, tokens, lookup):
        self.toks = tokens
        self.i = 0
        self.lookup = lookup
        self.depth = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _eat(self, value=None):
        kind, val = self._peek()
        if kind is None:
            raise ExprError("the expression ends in the middle of a term")
        self.i += 1
        return val

    def parse(self) -> Value:
        v = self.expr()
        if self.i != len(self.toks):
            kind, val = self._peek()
            raise ExprError(f"unexpected '{val}' after a complete expression")
        return v

    def _enter(self) -> None:
        """One level deeper into the recursive descent, or a NAMED refusal.

        *PARAMETER_EXPRESSION explicitly supports continuation lines (Vol I R17
        p.36-7), so an arbitrarily long — and arbitrarily nested — expression
        is legal input. Without this cap a deeply nested one raised
        ``RecursionError``, which neither ``except ExprError`` site in the
        parser catches, and the whole conversion died with a traceback instead
        of refusing one parameter by name.
        """
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise ExprError(
                f"the expression nests more than {_MAX_DEPTH} levels deep")

    def expr(self) -> Value:
        self._enter()
        try:
            return self._expr()
        finally:
            self.depth -= 1

    def _expr(self) -> Value:
        v = self.term()
        while self._peek() == ("op", "+") or self._peek() == ("op", "-"):
            op = self._eat()
            r = self.term()
            both_int = v[1] and r[1]
            res = (v[0] + r[0]) if op == "+" else (v[0] - r[0])
            v = (int(res) if both_int else float(res), both_int)
        return v

    def term(self) -> Value:
        v = self.power()
        while self._peek() == ("op", "*") or self._peek() == ("op", "/"):
            op = self._eat()
            r = self.power()
            both_int = v[1] and r[1]
            if op == "*":
                res = v[0] * r[0]
                v = (int(res) if both_int else float(res), both_int)
            else:
                if _real(r) == 0.0:
                    raise ExprError("division by zero")
                if both_int:
                    # Fortran integer division TRUNCATES toward zero. Remark
                    # 2a's own example: 2/5 -> 0. Python's // FLOORS, so
                    # -7 // 2 would give -4 where Fortran gives -3.
                    q = abs(v[0]) // abs(r[0])
                    v = (q if (v[0] >= 0) == (r[0] >= 0) else -q, True)
                else:
                    v = (_real(v) / _real(r), False)
        return v

    def signed(self) -> Value:
        """``('+' | '-')* atom`` — the unary sign, which binds TIGHTER than
        ``**`` because this is the exponentiation's BASE, not a level above
        it (Remark 2d: ``-3**2`` is ``(-3)**2 = 9``)."""
        self._enter()
        try:
            return self._signed()
        finally:
            self.depth -= 1

    def _signed(self) -> Value:
        if self._peek() == ("op", "-"):
            self._eat()
            v = self.signed()
            return (-v[0], v[1])
        if self._peek() == ("op", "+"):
            self._eat()
            return self.signed()
        return self.atom()

    def power(self) -> Value:
        base = self.signed()
        if self._peek() == ("op", "**"):
            self._eat()
            # Right-associative, and the exponent is itself a power, so its
            # own sign still applies to it (2**-1 = 0.5).
            e = self.power()
            both_int = base[1] and e[1]
            try:
                res = float(base[0]) ** float(e[0])
            except (OverflowError, ValueError) as exc:
                raise ExprError(f"{base[0]}**{e[0]} cannot be evaluated "
                                f"({exc})")
            if both_int and e[0] >= 0:
                return (int(round(res)), True)
            return (float(res), False)
        return base

    def atom(self) -> Value:
        kind, val = self._peek()
        if kind == "op" and val == "(":
            self._eat()
            v = self.expr()
            if self._peek() != ("op", ")"):
                raise ExprError("a '(' is never closed")
            self._eat()
            return v
        if kind == "num":
            self._eat()
            return val
        if kind == "name":
            self._eat()
            key = val.lstrip("&").lower()
            if self._peek() == ("op", "("):
                return self._call(key, val)
            if key in _CONSTANTS:
                return _CONSTANTS[key]
            got = self.lookup(key)
            if got is None:
                raise ExprError(
                    f"'{val}' is not defined at this point. LS-DYNA "
                    "expressions may reference PREVIOUSLY defined parameters "
                    "only (Vol I R17 p.36-7), so a forward reference is not a "
                    "valid deck either — check the definition order, or the "
                    "spelling")
            return got
        raise ExprError("the expression is empty or starts with an operator "
                        "that has nothing to act on")

    def _call(self, key: str, spelled: str) -> Value:
        self._eat()                                  # '('
        args: List[Value] = []
        if self._peek() != ("op", ")"):
            args.append(self.expr())
            while self._peek() == ("op", ","):
                self._eat()
                args.append(self.expr())
        if self._peek() != ("op", ")"):
            raise ExprError(f"the argument list of '{spelled}(' is never "
                            "closed")
        self._eat()
        if key == "pi" and not args:
            return _CONSTANTS["pi"]
        entry = _FUNCS.get(key)
        if entry is None:
            raise ExprError(
                f"'{spelled}' is not one of the intrinsic functions LS-DYNA "
                "defines for *PARAMETER_EXPRESSION (Vol I R17 p.36-8: "
                + ", ".join(sorted(_FUNCS)) + ", pi)")
        arity, fn, ret_int = entry
        if len(args) != arity:
            raise ExprError(
                f"'{spelled}' takes {arity} argument"
                + ("s" if arity > 1 else "")
                + f", not {len(args)} (Vol I R17 p.36-8 Remark 2b: sign, "
                  "atan2, min, max and mod take two, every other function "
                  "takes one)")
        try:
            res = fn(*args)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            raise ExprError(f"'{spelled}' cannot be evaluated here ({exc})")
        if ret_int is None:                     # keeps the arguments' type
            is_int = all(a[1] for a in args)
        else:
            is_int = ret_int
        return (int(res) if is_int else float(res), is_int)


def evaluate(expr: str, lookup) -> Value:
    """Evaluate *expr*, resolving names through ``lookup(name) -> Value|None``.

    Raises :class:`ExprError` with a user-facing message for anything the
    grammar does not cover.
    """
    text = expr.strip()
    if text.startswith("<") and text.endswith(">"):
        # Remark 1, p.36-8: an inline expression in a data field is written
        # between angle brackets, and inside them the parameter names appear
        # WITHOUT the leading '&'.
        text = text[1:-1]
    toks = _tokenize(text)
    if not toks:
        raise ExprError("the expression is empty")
    return _Parser(toks, lookup).parse()


def format_value(v: Value) -> str:
    """The value as the string ``to_float``/``to_int`` will re-read.

    An INTEGER is written without a decimal point so a downstream ``to_int``
    on an ``I``-typed parameter sees exactly what the deck meant; a REAL keeps
    full double precision (``repr``), because the value may be an id-free
    physical quantity whose last digits matter.
    """
    return str(int(v[0])) if v[1] else repr(float(v[0]))
