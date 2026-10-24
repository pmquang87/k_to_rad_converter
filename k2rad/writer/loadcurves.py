"""R14 triage round 9, B5: an applied-load /FUNCT is ZERO off its abscissa
range, as LS-DYNA's load curves are (default ON,
``--no-load-curve-offscale-zero``).

LS-DYNA (Vol I R17 *DEFINE_CURVE): Remark 4a adds the two points (0, 0) and
(0.999 OFFA, 0) to a DATTYP-0 curve with OFFA > 0, and Remark 5 says load
curves are not extrapolated - "Function values are set to zero if the time
goes off scale". OpenRadioss extends a /FUNCT's first / last segment instead
(``finter.F:235-273``), so a curve shifted after t 0 by OFFA (Remark 4a; the
aniso cup-draw: the punch started BACKWARD at +219.29 mm/s) or ending before
t_end (Remark 5; thick.k: the punch ran on past LS-DYNA's stop) drives the
model where LS-DYNA does not. The HEAD is padded only under Remark 4a (OFFA >
0, SFA 0 / 1): a curve whose first abscissa is merely > 0 keeps its head (the
post-review round, C7 / F8: the texts said 'off the abscissa range').

The rule acts at EMISSION (decision B5-a): a mechanical applied-load consumer
(/IMPVEL, /IMPDISP, /IMPACC - their rigid-body, node / set and rigid-wall forms
- /CLOAD, /PLOAD, /GRAV) whose curve OpenRadioss would extrapolate NONZERO
inside the consumer's active window is pointed at a COPY with the zero points;
``state.curves`` and the deck's own /FUNCT stay as stated, so material,
preload and thermal curves never change. Sensor-gated consumers (B5-b) and
/FUNCT_SMOOTH curves (B5-c) are excluded.
"""

from __future__ import annotations

from typing import List, Tuple

from ..state import ConversionState
from .common import HDR, _f

__all__ = ["load_funct_id", "make_offscale_functs"]

#: an /IMPVEL Tstop at or above this is "no stop" (the reader's 1e30 default)
_NO_STOP = 1.0e20


def _endtim(state: ConversionState) -> float:
    return state.ctrl_termination.endtim if state.ctrl_termination else 1.0


def load_funct_id(state: ConversionState, lcid: int, consumer: str,
                  tstart: float = 0.0, tstop: float = 0.0,
                  sensor_id: int = 0, ascale_x: float = 1.0) -> int:
    """The /FUNCT id a mechanical applied-load *consumer* card should name:
    *lcid* itself, or the id of a copy that is zero off the curve's range
    where OpenRadioss would extrapolate it nonzero inside the active window
    [max(0, Tstart), min(ENDTIM, Tstop)] (mapped by FACX = 1 / Ascale_x)."""
    if (not state.options.load_curve_offscale_zero or sensor_id
            or lcid <= 0 or lcid not in state.curves
            or lcid in state.funct_smooth_ids or lcid in state.table_1d_ids):
        return lcid
    c = state.curves[lcid]
    if getattr(c, "dattyp", 0) not in (0, None) or len(c.pts) < 2:
        return lcid
    from .loads import _monotonic_abscissae
    pts = [(float(a), float(o)) for a, o in _monotonic_abscissae(c.pts)]
    endtim = _endtim(state)
    facx = 1.0 / (ascale_x or 1.0)
    xa = max(0.0, tstart) * facx
    tb = tstop if 0.0 < tstop < _NO_STOP else endtim
    xb = min(endtim, tb) * facx
    head: List[Tuple[float, float]] = []
    tail: List[Tuple[float, float]] = []
    # Remark 4a: DATTYP 0 with OFFA > 0 (stated for an unscaled abscissa)
    if (c.offa > 0.0 and c.sfa in (0.0, 1.0) and pts[0][0] > xa
            and not (pts[0][1] == 0.0 and pts[1][1] == 0.0)):
        head = [(0.0, 0.0)]
        if 0.999 * c.offa < pts[0][0]:
            head.append((0.999 * c.offa, 0.0))
    # Remark 5: zero after the last abscissa
    if (endtim > 0.0 and pts[-1][0] < xb
            and not (pts[-2][1] == 0.0 and pts[-1][1] == 0.0)):
        xn = pts[-1][0]
        x1 = 1.0001 * xn if xn > 0.0 else xn + 1.0e-4 * xb
        far = max(2.0 * endtim * facx, 2.0 * xn)
        if far <= x1:                       # only a curve ending at x <= 0
            far = x1 + xb
        # two points: one would leave a steep last segment OpenRadioss
        # extrapolates again
        tail = [(x1, 0.0), (far, 0.0)]
    if not head and not tail:
        return lcid
    key = (lcid, tuple(head), tuple(tail))
    rec = state.offscale_functs.get(key)
    if rec is None:
        fid = state.next_curve_id()
        rec = (fid, head + pts + tail)
        state.offscale_functs[key] = rec
    state.offscale_uses.append((lcid, consumer, rec[0], head, tail))
    return rec[0]


def _pt(p: Tuple[float, float]) -> str:
    return f"({p[0]:g}, {p[1]:g})"


def make_offscale_functs(state: ConversionState) -> List[str]:
    """The copies' /FUNCT blocks (after every consumer) + ONE sentence per
    deck naming every padded curve."""
    if not state.offscale_functs:
        return []
    from .loads import _monotonic_abscissae
    lines: List[str] = ["#-  FUNCTIONS (zero off scale, *DEFINE_CURVE "
                        "Remarks 4a / 5):", HDR]
    per: List[str] = []
    sides = set()
    for (lcid, head, tail), (fid, pts) in sorted(
            state.offscale_functs.items(), key=lambda kv: kv[1][0]):
        lines += [f"/FUNCT/{fid}", f"FUNCT_{lcid}_offscale_zero",
                  "#                  X                   Y"]
        for a, o in _monotonic_abscissae(pts):
            lines.append(f"{_f(a)}{_f(o)}")
        lines.append(HDR)
        bits = []
        if head:
            sides.add("before")
            bits.append(" and ".join(_pt(p) for p in head)
                        + f" before {pts[len(head)][0]:g}")
        if tail:
            sides.add("after")
            bits.append(" and ".join(_pt(p) for p in tail)
                        + f" after {pts[-len(tail) - 1][0]:g}")
        per.append(f"/FUNCT/{lcid} -> /FUNCT/{fid} ({'; '.join(bits)})")
    where = ("at both ends" if sides == {"before", "after"} else
             "before the first abscissa" if sides == {"before"} else
             "after the last abscissa")
    consumers = sorted({u[1] for u in state.offscale_uses})
    lcids = sorted({k[0] for k in state.offscale_functs})
    state.warn(
        f"*DEFINE_CURVE {lcids}: an applied-load curve is zero off its "
        "abscissa range in LS-DYNA (Vol I R17 *DEFINE_CURVE Remark 5 'Function "
        "values are set to zero if the time goes off scale'; Remark 4a adds "
        "(0, 0) and (0.999 OFFA, 0) for DATTYP 0 with OFFA > 0), while "
        "OpenRadioss extends the first / last segment (finter.F:235-273). So "
        f"the {', '.join('/' + c for c in consumers)} consumer(s) read a copy "
        f"with zero points written {where}: " + "; ".join(per) + ". The deck's "
        "own /FUNCT stays as stated for every other consumer, and material, "
        "preload and thermal curves are never changed. MEASURED: "
        "mat_transversely_anisotropic.cup-draw (nt 4) - the punch no longer "
        "starts BACKWARD (DZ at 2.1 ms +0.2187 -> -0.00055 mm; punch work at "
        "the fifths within 0.1-7.8 % of LS-DYNA's bndout, every fifth "
        "below it), but the deck IE is WORSE on both counts - END +6.09 -> "
        "+13.10 % and RMS 2.89 -> 5.57 % of the LS peak (150 LS times to t "
        "0.015) - and KE END -40.31 -> -42.14 %: the backward start hid an IE "
        "excess; "
        "thick.k (nt 4) - the punch stops at -10.0003 mm as LS-DYNA's does (it "
        "ran on to -11.99 mm), KE END +91.96 -> +23.42 %, KE RMS 21.01 -> "
        "8.79 % (1000 LS times to t 0.0012), IE unchanged. A prescribed "
        "DISPLACEMENT whose curve ends before t_end returns to 0 after its "
        "last abscissa by the manual's wording; no LS-DYNA carrier measures "
        "that side. --no-load-curve-offscale-zero writes the curves as "
        "stated.")
    return lines
