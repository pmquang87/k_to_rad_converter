#!/usr/bin/env python3
"""
th_to_csv.py - OpenRadioss binary time-history (T01) -> CSV, with the
time-derivative column that the accumulated channels actually need.

OpenRadioss writes several /TH channels as a running TIME INTEGRAL rather than
as the instantaneous quantity their name suggests.  A `/TH/NODE` `REACY` column
is not a reaction force, it is the reaction impulse integral(F dt) accumulated
since t = 0; the same is true of the `/TH/INTER`, `/TH/SECTIO`, `/TH/RWALL` and
`/TH/RBODY`
force channels.  Plotting one of those columns as a force gives a monotonically
rising line and no error anywhere.  The instantaneous quantity is the time
derivative of the column.

So this tool extracts the T01 and, next to every accumulated channel, writes a
differentiated sibling column named `<channel>_ddt`::

      time,   3_REACY,  3_REACY_ddt
    0.03000,  0.073500,    3.850418     <- N*s          <- N

`_ddt` is deliberately unit-neutral: d/dt of `REACX` is a force, of `REACXX` a
moment, of a `/TH/SECTIO` `M1` a moment as well, so no single word ("force")
fits every column it is applied to.

Which channels get the treatment, and why (engine sources verified against
``C:/OpenRadioss/source``; see the k2rad CHANGELOG for the full sweep):

* ``/TH/NODE`` ``REACX/Y/Z``, ``REACXX/YY/ZZ`` - ``reaction_forces_th.F:62``
  and ``bcs1th.F:143-155`` add ``m*a*dt`` (``I*ar*dt`` for the rotations) every
  cycle; the only reset is ``resol.F:1901``, before the iteration loop head at
  ``:2612``.  ``thnod.F:176-178`` writes the accumulator out undivided.
* ``/TH/INTER`` (and ``/INTER/SUB``) ``FNX/Y/Z``, ``FTX/Y/Z`` -
  ``i7for3.F:1459-1476`` accumulates ``F*DT12`` under the engine's own comment
  ``SAUVEGARDE DE L'IMPULSION NORMALE``; ``thkin.F:56`` copies it raw.  The
  master rank is never reset: ``hist2.F:616-622`` zeroes ``FSAV`` only on
  ``ISPMD/=0``, and ``sortie_main.F:1945`` ("TRAITEMENT SUR FSAV NON CUMULE")
  resets only the monvol block, ``FSAV(26)`` and ``FSAV(29)``.
* ``/TH/SECTIO`` ``FNX..FTZ``, ``M1/M2/M3`` - ``section_c.F:459-467`` and
  ``section_s.F:565-572`` accumulate ``DT12*FST``.
* ``/TH/RWALL`` ``FNX/Y/Z``, ``FTX/Y/Z`` - ``rgwal0.F:504-509`` accumulates the
  nodal impulse sums ``FXN..FZT``.  The engine computes the true wall force one
  line earlier (``*DIVDT12``, ``rgwal0.F:498-500``) but routes it only to
  ``FOPT`` (/ANIM) and the sensor buffer.
* ``/TH/RBODY`` ``FX/Y/Z``, ``MX/Y/Z`` - ``rgbodfp.F:261-266`` accumulates
  ``FS(1)=FS(1)+AFM1*DT1*WEIGHT(M)``.  This is the group *DATABASE_RBDOUT
  builds, so a converted deck reaches it routinely.

Channels NOT differentiated, because they are already instantaneous: `/TH/NODE`
`DX/VX/...` (`thnod.F:124-135`), `/TH/SHEL` + `/TH/SH3N` + `/TH/BRIC` element
state (`thcoq.F:305-315`, `thsol.F:329-336`), `/TH/SPRING` `FX..MZ`
(`thres.F:355-361`).  `/TH/RBODY` `RX/RY/RZ` are the odd ones out inside an
otherwise accumulated group: `rgbodv.F:91-93` integrates the angular VELOCITY,
so they ARE the rotation angle and differentiating them would give back a rate.
Energies (`IE`, `KE`) are cumulative by nature and are
left alone.  `/TH/SURF` is a special case and is flagged rather than
differentiated - see `--list` output and the note under "/TH/SURF" below.

Usage
-----
    python tools/th_to_csv.py <jobname>T01 [-o STEM]
        [--list] [--only TYPE ...] [--no-derivative] [--precision N]

    # what is in the file?
    python tools/th_to_csv.py runT01 --list

    # only the node groups, into ./run_th_NODE_<id>.csv
    python tools/th_to_csv.py runT01 --only NODE

Outputs (<stem> = the T01 path with a trailing `T01`/`T02`... stripped)
-----------------------------------------------------------------------
  <stem>_th_<TYPE>_<groupid>.csv   one file per /TH group, `time` + one column
                                   per (entity, variable) named `<id>_<VAR>`,
                                   each accumulated channel followed by its
                                   `_ddt` sibling
  <stem>_th_GLOBAL.csv             the global energy/momentum channels, if the
                                   file carries them

The differentiated columns are ON by default (`--no-derivative` opts out): the
raw column is the trap, and a flag you have to know about is exactly the
knowledge the user is missing.  Adding columns is non-destructive - every
original column keeps its name and position, so a downstream script that reads
this CSV by column name is unaffected.

/TH/SURF
--------
`/TH/SURF` is neither instantaneous nor a running integral: `P` and `A` are
accumulated per cycle and RESET at every TH write (`sortie_main.F:1976-1982`),
and `hist2.F:688` divides `P` by `A` before writing.  So `P` is the
area-weighted MEAN pressure over the /TFILE interval, and `A` is the loaded
area multiplied by the number of cycles in that interval - `P*A` is NOT the
total surface force.  Differentiating those columns would be meaningless, so
the tool leaves them alone and prints a warning instead.

Stdlib only - no numpy required (the derivative uses the same second-order
non-uniform-spacing formula as `numpy.gradient`, and the T01 reader is plain
`struct`).

T01 binary format
-----------------
The engine's default `/TH` output ("IEEE" format, `ITTYP=3`) is a stream of
Fortran-style records, each framed by a 4-byte BIG-ENDIAN byte count before and
after the payload (`engine/source/output/th/wrtdes.F`, `EOR_C(4*L)`; marker
written by `eor_c()` in `common_source/tools/input_output/write_routines.c`).
All integers are 4-byte big-endian, and all reals are 4-byte big-endian
IEEE-754 SINGLES even in a double-precision engine build - `wrtdes.F` narrows
`my_real` to `REAL*4` before writing (`engine/source/output/tools/ieee.cpp`
does the byte packing).  Header and per-state layout: see `hist1.F` and
`hist2.F`, and the record-by-record map in `read_th` below.

This reader was validated cell-by-cell against Altair's own
`th_to_csv_win64.exe` on four real T01 files (1.29 million values, 29 to 10000
states, node/part/interface groups): zero disagreements beyond the reference
CSV's 7-significant-digit print rounding.
"""

from __future__ import annotations

import argparse
import gzip
import os
import struct
import sys
from typing import Dict, List, Optional, Sequence, Tuple


class ThFormatError(Exception):
    """The file does not follow the expected T01 binary layout."""


# ─────────────────────────────────────────────────────────────────────────────
# Channels that carry a time integral rather than the instantaneous quantity
# ─────────────────────────────────────────────────────────────────────────────

# (group type -> channel names).  Verified against the engine sources cited in
# the module docstring; do not extend this without a file:line citation.
ACCUMULATED_CHANNELS: Dict[str, Tuple[str, ...]] = {
    "NODE": ("REACX", "REACY", "REACZ", "REACXX", "REACYY", "REACZZ"),
    "INTER": ("FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ"),
    "SECTIO": ("FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ", "M1", "M2", "M3"),
    "RWALL": ("FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ"),
    # Only the force/moment half.  rgbodfp.F:261-266 accumulates
    # FS(1)=FS(1)+AFM1*DT1*WEIGHT(M) into FX..MZ, so those six are an impulse
    # like every other row here -- but rgbodv.F:91-93 integrates the angular
    # VELOCITY into FS(7..9)=RX/RY/RZ, which makes them the body's rotation
    # ANGLE already.  Differentiating those would turn an angle back into a
    # rate; measured 0.998181 rad against an exact 0.998008 rad on a body spun
    # at a known 100 rad/s, so they are correct as written and stay out.
    # FXI..MZI (FS(10..15), the 'FI'/'MI' vars) are not listed either: k2rad
    # never requests them -- /TH/RBODY DEF stops at channel 9
    # (hm_read_thgrou.F IVARRBG row 1) -- and this table takes no entry without
    # a file:line citation for it.
    "RBODY": ("FX", "FY", "FZ", "MX", "MY", "MZ"),
}

# Suffix for the differentiated sibling column.  Unit-neutral on purpose: the
# derivative of REACX is a force, of REACXX and of a SECTIO M1 a moment.
DERIV_SUFFIX = "_ddt"

# Types whose channels are per-TH-interval aggregates: neither instantaneous
# nor a running integral, so a time derivative is meaningless.  Warned about.
INTERVAL_AGGREGATE_TYPES = ("SURF",)


def is_accumulated(group_type: str, var: str) -> bool:
    """True when this (/TH type, variable) pair carries a running time integral."""
    return var.upper() in ACCUMULATED_CHANNELS.get(group_type.upper(), ())


# ─────────────────────────────────────────────────────────────────────────────
# Time derivative
# ─────────────────────────────────────────────────────────────────────────────

def gradient(values: Sequence[float], times: Sequence[float]) -> List[float]:
    """d(values)/d(times), the same scheme as ``numpy.gradient(v, t)``.

    Second-order central differences on the interior with non-uniform spacing
    allowed, first-order one-sided at the two ends.  Exact for a linear ramp,
    which is what a steady reaction or contact force produces in an accumulated
    channel - so a settled load differentiates back to a flat, correct value.
    """
    n = len(values)
    if n != len(times):
        raise ValueError("values and times must have the same length")
    if n < 2:
        return [0.0] * n
    out = [0.0] * n
    for i in range(1, n - 1):
        # hb = backward step, hf = forward step. The interior estimate is the
        # slope at x_i of the parabola through the three surrounding samples:
        #   f'(x_i) = (hb^2*f[i+1] + (hf^2 - hb^2)*f[i] - hf^2*f[i-1])
        #             / (hb*hf*(hb + hf))
        # which collapses to the usual (f[i+1] - f[i-1]) / 2h when hb == hf.
        # Getting hb and hf the wrong way round still passes every
        # evenly-spaced test, so keep the non-uniform test that pins it.
        hb = times[i] - times[i - 1]
        hf = times[i + 1] - times[i]
        denom = hb * hf * (hb + hf)
        if denom == 0.0:
            # duplicated output times (restart overlap): fall back to a
            # one-sided difference over whatever interval is non-degenerate
            out[i] = _one_sided(values, times, i)
            continue
        out[i] = (hb * hb * values[i + 1]
                  + (hf * hf - hb * hb) * values[i]
                  - hf * hf * values[i - 1]) / denom
    out[0] = _one_sided(values, times, 0)
    out[n - 1] = _one_sided(values, times, n - 1)
    return out


def _one_sided(values: Sequence[float], times: Sequence[float], i: int) -> float:
    """First-order one-sided slope at index ``i`` (0.0 if the step is degenerate)."""
    j = i + 1 if i == 0 else i - 1
    dt = times[i] - times[j]
    if dt == 0.0:
        return 0.0
    return (values[i] - values[j]) / dt


# ─────────────────────────────────────────────────────────────────────────────
# T01 name tables
# ─────────────────────────────────────────────────────────────────────────────

# Global channel order: engine/source/output/th/hist2.F WA(1..22) assignments.
GLOBAL_VAR_NAMES = (
    "INTERNAL_ENERGY", "KINETIC_ENERGY", "X_MOMENTUM", "Y_MOMENTUM",
    "Z_MOMENTUM", "MASS", "TIME_STEP", "ROTATION_ENERGY", "EXTERNAL_WORK",
    "SPRING_ENERGY", "CONTACT_ENERGY", "HOURGLASS_ENERGY",
    "ELASTIC_CONTACT_ENERGY", "FRICTIONAL_CONTACT_ENERGY",
    "DAMPING_CONTACT_ENERGY", "PLASTIC_WORK", "ADDED_MASS",
    "PERCENT_ADDED_MASS", "INLET_MASS", "OUTLET_MASS",
    "INLET_ENERGY", "OUTLET_ENERGY",
)

# /TH group ityp -> type name (hist2.F dispatch ladder; NSTRAND=100 is
# re-tagged 6/SPRING in the header, hist1.F).
GROUP_TYPE_NAMES = {
    0: "NODE", 1: "BRICK", 2: "QUAD", 3: "SHELL", 4: "TRUSS", 5: "BEAM",
    6: "SPRING", 7: "SH3N", 50: "RNUR", 51: "SPHCEL", 100: "NSTRAND",
    101: "INTER", 102: "RWALL", 103: "RBODY", 104: "SECTIO",
    105: "CYL_JOINT", 106: "RBAG", 107: "MONVOL", 108: "ACCEL",
    109: "RIVET", 110: "FRAME", 111: "FXBODY", 113: "GAUGE",
    114: "CLUSTER", 115: "SPH_FLOW", 116: "SURF", 117: "TRIA",
    118: "SLIPRING", 119: "RETRACTOR", 120: "SENSOR", 121: "CHECKSUM",
}

# /TH/NODE variable codes: engine/source/output/th/thnod.F:124-291.
_NODE_VARS = {
    1: "DX", 2: "DY", 3: "DZ", 4: "VX", 5: "VY", 6: "VZ",
    7: "AX", 8: "AY", 9: "AZ", 10: "VRX", 11: "VRY", 12: "VRZ",
    13: "ARX", 14: "ARY", 15: "ARZ", 16: "X", 17: "Y", 18: "Z", 19: "TEMP",
    620: "REACX", 621: "REACY", 622: "REACZ",
    623: "REACXX", 624: "REACYY", 625: "REACZZ",
    626: "DRX", 627: "DRY", 628: "DRZ", 629: "PEXT",
}

# starter/source/output/th/hm_read_thgrou.F DATA VARIN / VARRW / VARRB /
# VARSE / VARR / VARSURF blocks (1-based variable codes).
_INTER_VARS = (
    "FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ", "SFW", "|FNX|", "|FNY|",
    "|FNZ|", "||FN||", "|FX|", "|FY|", "|FZ|", "||F||", "PVOL", "PSURF",
    "PMED", "DELTAP", "VOL", "SURF", "MX", "MY", "MZ", "QFRIC",
    "CE_ELAST", "CE_FRIC", "CE_DAMP", "CAREA",
)
_RWALL_VARS = ("FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ")
_RBODY_VARS = (
    "FX", "FY", "FZ", "MX", "MY", "MZ", "RX", "RY", "RZ",
    "FXI", "FYI", "FZI", "MXI", "MYI", "MZI",
)
_SECTIO_VARS = (
    "FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ", "M1", "M2", "M3", "WORK",
    "DFX", "DFY", "DFZ", "DF2", "WORKR", "DMX", "DMY", "DMZ", "DM2",
    "KIN", "KINR", "DMVX", "DMVY", "DMVZ", "DKIN", "DMVRX", "DMVRY",
    "DMVRZ", "DKINR", "TFEXT", "MX", "MY", "MZ", "F1", "F2", "F3",
    "CX", "CY", "CZ",
)
_SPRING_VARS = (
    "OFF", "FX", "FY", "FZ", "MX", "MY", "MZ", "LX", "LY", "LZ",
    "RX", "RY", "RZ", "IE",
)
_SURF_VARS = ("AREA", "MASSFLOW", "VELOCITY", "P", "A", "MASS")
_PART_VARS = {
    1: "IE", 2: "KE", 3: "XMOM", 4: "YMOM", 5: "ZMOM", 6: "MASS",
    7: "HE", 8: "ERODED", 9: "HEAT",
}

_TYPED_VAR_TABLES = {
    "INTER": _INTER_VARS,
    "RWALL": _RWALL_VARS,
    "RBODY": _RBODY_VARS,
    "SECTIO": _SECTIO_VARS,
    "SPRING": _SPRING_VARS,
    "SURF": _SURF_VARS,
}
# /TH/SPRING code 65 is LENGTH (hm_read_thgrou.F IVARRG last entry).
_SPRING_EXTRA = {65: "LENGTH", 66: "FAIL"}


def _var_name(group_type: str, code: int) -> str:
    """Best-effort variable name for a (/TH type, variable code) pair."""
    if group_type == "NODE":
        return _NODE_VARS.get(code, "var%d" % code)
    if group_type == "PART":
        return _PART_VARS.get(code, "var%d" % code)
    if group_type == "SPRING" and code in _SPRING_EXTRA:
        return _SPRING_EXTRA[code]
    table = _TYPED_VAR_TABLES.get(group_type)
    if table is not None and 1 <= code <= len(table):
        return table[code - 1]
    return "var%d" % code


# ─────────────────────────────────────────────────────────────────────────────
# T01 reader
# ─────────────────────────────────────────────────────────────────────────────

class _RecordStream:
    """Fortran-style records framed by big-endian 4-byte length markers."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def next_record(self) -> Optional[bytes]:
        """Next record payload, or None at a clean or truncated end of file."""
        data, pos = self._data, self._pos
        if pos + 8 > len(data):
            return None
        (n1,) = struct.unpack_from(">i", data, pos)
        end = pos + 4 + n1
        if n1 < 0 or end + 4 > len(data):
            return None
        (n2,) = struct.unpack_from(">i", data, end)
        if n1 != n2:
            raise ThFormatError(
                "record marker mismatch at byte %d (%d != %d)" % (pos, n1, n2))
        self._pos = end + 4
        return data[pos + 4:end]

    def expect(self, nbytes: int, what: str) -> bytes:
        rec = self.next_record()
        if rec is None:
            raise ThFormatError("unexpected end of file reading %s" % what)
        if len(rec) != nbytes:
            raise ThFormatError("bad %s record: %d bytes, expected %d"
                                % (what, len(rec), nbytes))
        return rec


def _ints(buf: bytes) -> List[int]:
    return list(struct.unpack(">%di" % (len(buf) // 4), buf))


def _floats(buf: bytes) -> List[float]:
    return list(struct.unpack(">%df" % (len(buf) // 4), buf))


def _text(buf: bytes) -> str:
    return buf.decode("latin-1").rstrip(" \x00")


def read_th(path: str) -> Tuple[List[float], List[Dict]]:
    """Read an OpenRadioss binary time-history file (``<root>T01``, ``.thy``).

    Returns ``(times, groups)``.  Each group dict carries:

    ``type``       "GLOBAL", "PART", "SUBSET" or the /TH group type
                   ("NODE", "INTER", "SECTIO", ...)
    ``id``         user id of the group / part / subset (0 for GLOBAL)
    ``title``      title string as stored in the file
    ``vars``       decoded variable names ("var<code>" when the code table for
                   that type is not known)
    ``var_codes``  the raw integer variable codes
    ``ids``        entity user ids; parts, subsets and GLOBAL have one
    ``data``       ``data[state][entity_index][var_index]``
    """
    with open(path, "rb") as fh:
        if fh.read(2) == b"\x1f\x8b":       # /TH format 4/5: gzip-wrapped
            fh.seek(0)
            with gzip.open(fh) as gz:
                raw = gz.read()
        else:
            fh.seek(0)
            raw = fh.read()

    if len(raw) < 12 or struct.unpack_from(">i", raw, 0)[0] != 84:
        raise ThFormatError(
            "%s is not an OpenRadioss IEEE-binary time-history file (expected a "
            "first record marker of 84). The ASCII and platform-native /TH "
            "output formats are not supported." % os.path.basename(path))

    st = _RecordStream(raw)

    rec = st.expect(84, "title")
    icode = _ints(rec[:4])[0]
    run_title = _text(rec[4:])
    if icode not in (3040, 3041, 3050, 4021):
        raise ThFormatError("unsupported TH format code %d" % icode)
    ltitl = {3040: 40, 3041: 80}.get(icode, 100)

    date_rec = st.next_record()
    if date_rec is None:
        raise ThFormatError("unexpected end of file reading the date record")

    if icode >= 3050:                        # TH_VERS >= 50 extra records
        nrecord = _ints(st.expect(4, "nrecord"))[0]
        for irec in range(nrecord):
            extra = st.next_record()
            if extra is None:
                raise ThFormatError("unexpected end of file in extra records")
            if irec == 0 and len(extra) == 4:
                ltitl = _ints(extra)[0]

    npart, nummat, numgeo, nsubs, nthgrp, nglob = _ints(st.expect(24, "hierarchy"))
    if nglob > 0:
        st.expect(4 * nglob, "global variable codes")

    groups: List[Dict] = []

    def _add(gtype, gid, title, codes, ids):
        groups.append({
            "type": gtype, "id": gid, "title": title,
            "vars": [_var_name(gtype, c) for c in codes],
            "var_codes": list(codes), "ids": list(ids), "data": [],
        })
        return len(groups) - 1

    if nglob > 0:
        idx = _add("GLOBAL", 0, "GLOBAL", range(1, nglob + 1), [0])
        groups[idx]["vars"] = [
            GLOBAL_VAR_NAMES[i] if i < len(GLOBAL_VAR_NAMES) else "GLOB%d" % (i + 1)
            for i in range(nglob)]

    part_slices: List[Tuple[int, int]] = []
    for _ in range(npart):
        rec = st.expect(20 + ltitl, "part descriptor")
        pid = _ints(rec[:4])[0]
        title = _text(rec[4:4 + ltitl])
        nvar = _ints(rec[4 + ltitl + 12:4 + ltitl + 16])[0]
        if nvar > 0:
            codes = _ints(st.expect(4 * nvar, "part variables"))
            part_slices.append((_add("PART", pid, title, codes, [pid]), nvar))

    for _ in range(nummat):
        st.expect(4 + ltitl, "material descriptor")
    for _ in range(numgeo):
        st.expect(4 + ltitl, "property descriptor")

    subs_slices: List[Tuple[int, int]] = []
    for _ in range(nsubs):
        rec = st.expect(20 + ltitl, "subset descriptor")
        sid, _parent, nchild, nprt, nvar = _ints(rec[:20])
        title = _text(rec[20:])
        if nchild > 0:
            st.expect(4 * nchild, "subset children")
        if nprt > 0:
            st.expect(4 * nprt, "subset parts")
        if nvar > 0:
            codes = _ints(st.expect(4 * nvar, "subset variables"))
            subs_slices.append((_add("SUBSET", sid, title, codes, [sid]), nvar))

    th_slices: List[Tuple[int, int, int]] = []
    for _ in range(nthgrp):
        rec = st.expect(20 + ltitl, "TH group descriptor")
        gid, ityp, _res, nn, nvar = _ints(rec[:20])
        title = _text(rec[20:])
        ids = []
        for _ in range(nn):
            erec = st.expect(4 + ltitl, "TH group entity")
            ids.append(_ints(erec[:4])[0])
        codes = _ints(st.expect(4 * nvar, "TH group variables")) if nvar > 0 else []
        gtype = GROUP_TYPE_NAMES.get(ityp, "TYPE%d" % ityp)
        th_slices.append((_add(gtype, gid, title, codes, ids), nn, nvar))

    # ── time states ──────────────────────────────────────────────────────────
    part_total = sum(n for _, n in part_slices)
    subs_total = sum(n for _, n in subs_slices)
    times: List[float] = []

    def _grab(nbytes):
        rec = st.next_record()
        if rec is None or len(rec) != nbytes:
            return None
        return _floats(rec)

    while True:
        rec = st.next_record()
        if rec is None:
            break
        if len(rec) != 4:
            raise ThFormatError("bad time record (%d bytes)" % len(rec))
        t = _floats(rec)[0]

        staged: List[Tuple[int, List[float], int]] = []   # (group, values, nvar)
        ok = True
        if nglob > 0:
            vals = _grab(4 * nglob)
            ok = vals is not None
            if ok:
                staged.append((0, vals, nglob))
        for total, slices in ((part_total, part_slices), (subs_total, subs_slices)):
            if not ok or total == 0:
                continue
            vals = _grab(4 * total)
            if vals is None:
                ok = False
                break
            off = 0
            for gidx, nvar in slices:
                staged.append((gidx, vals[off:off + nvar], nvar))
                off += nvar
        if ok:
            for gidx, nn, nvar in th_slices:
                if nn * nvar == 0:
                    continue
                vals = _grab(4 * nn * nvar)
                if vals is None:
                    ok = False
                    break
                staged.append((gidx, vals, nvar))
        if not ok:
            break                       # run killed mid-write: drop the state
        times.append(t)
        for gidx, vals, nvar in staged:
            rows = [vals[k:k + nvar] for k in range(0, len(vals), nvar)]
            groups[gidx]["data"].append(rows)

    meta = {"icode": icode, "title": run_title, "date": _text(date_rec)}
    for group in groups:
        group["file_meta"] = meta
    return times, groups


# ─────────────────────────────────────────────────────────────────────────────
# CSV assembly
# ─────────────────────────────────────────────────────────────────────────────

def build_table(group: Dict, times: Sequence[float],
                derivative: bool = True) -> Tuple[List[str], List[List[float]]]:
    """Turn one /TH group into (header, rows) with the `_ddt` siblings inserted.

    Column order is `time`, then each (entity, variable) in file order, with an
    accumulated channel immediately followed by its derivative.  Original
    columns keep their name and relative order, so adding the siblings cannot
    break a consumer that selects columns by name.
    """
    gtype = group["type"]
    single = gtype in ("GLOBAL", "PART", "SUBSET")
    header = ["time"]
    # (entity index, variable index, differentiate?)
    picks: List[Tuple[int, int, bool]] = []
    for ei, eid in enumerate(group["ids"]):
        for vi, var in enumerate(group["vars"]):
            name = var if single else "%d_%s" % (eid, var)
            header.append(name)
            picks.append((ei, vi, False))
            if derivative and is_accumulated(gtype, var):
                header.append(name + DERIV_SUFFIX)
                picks.append((ei, vi, True))

    states = group["data"]
    n = min(len(times), len(states))
    columns: List[List[float]] = []
    cache: Dict[Tuple[int, int], List[float]] = {}
    for ei, vi, diff in picks:
        raw = cache.get((ei, vi))
        if raw is None:
            raw = [states[s][ei][vi] for s in range(n)]
            cache[(ei, vi)] = raw
        columns.append(gradient(raw, times[:n]) if diff else raw)

    rows = [[times[s]] + [col[s] for col in columns] for s in range(n)]
    return header, rows


def write_csv(path: str, header: Sequence[str], rows, precision: int = 9) -> None:
    """Write a CSV with `%.<precision>G` numbers and Unix line endings."""
    fmt = "%." + str(precision) + "G"
    with open(path, "w", newline="\n") as fh:
        fh.write(",".join(header) + "\n")
        for row in rows:
            fh.write(",".join(fmt % v for v in row) + "\n")


def default_output_stem(th_path: str) -> str:
    """`.../runT01` -> `.../run`; `.../run_0001.thy` -> `.../run_0001`."""
    stem = th_path[:-4] if th_path.lower().endswith(".thy") else th_path
    if len(stem) > 3 and stem[-3] in "Tt" and stem[-2:].isdigit():
        stem = stem[:-3]
    return stem


def group_filename(stem: str, group: Dict) -> str:
    if group["type"] == "GLOBAL":
        return "%s_th_GLOBAL.csv" % stem
    return "%s_th_%s_%d.csv" % (stem, group["type"], group["id"])


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="th_to_csv",
        description="Extract an OpenRadioss T01 time-history file to CSV, "
                    "adding a differentiated sibling column next to every "
                    "channel the engine writes as a running time integral "
                    "(/TH/NODE REAC*, /TH/INTER, /TH/SECTIO, /TH/RWALL forces).")
    ap.add_argument("th_file", help="<jobname>T01 (or .thy) written by the engine")
    ap.add_argument("-o", "--output-stem", default=None, metavar="STEM",
                    help="output path stem (default: the T01 path with the "
                         "trailing T01/T02/... stripped)")
    ap.add_argument("--list", action="store_true", dest="list_only",
                    help="print the file inventory and exit; write nothing")
    ap.add_argument("--only", nargs="+", default=None, metavar="TYPE",
                    help="extract only these /TH types (NODE INTER SECTIO ...)")
    ap.add_argument("--no-derivative", action="store_false", dest="derivative",
                    help="do not add the _ddt columns (raw channels only)")
    ap.add_argument("--precision", type=int, default=9, metavar="N",
                    help="significant digits in the CSV (default 9)")
    args = ap.parse_args(argv)

    try:
        times, groups = read_th(args.th_file)
    except (OSError, ThFormatError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    print("Read %s: %d state(s), t = %g .. %g, %d group(s)"
          % (args.th_file, len(times), times[0] if times else 0.0,
             times[-1] if times else 0.0, len(groups)))
    if not times:
        print("  WARNING: no time state in the file - nothing to write.")
        return 1

    wanted = {t.upper() for t in args.only} if args.only else None
    selected = [g for g in groups if wanted is None or g["type"] in wanted]

    for g in groups:
        acc = [v for v in g["vars"] if is_accumulated(g["type"], v)]
        note = "  <- accumulated: %s" % ", ".join(acc) if acc else ""
        if g["type"] in INTERVAL_AGGREGATE_TYPES:
            note = "  <- per-/TFILE-interval aggregate, see --help"
        print("  %-8s id %-7s %-3d entity(ies)  vars: %s%s"
              % (g["type"], g["id"], len(g["ids"]), ", ".join(g["vars"]), note))

    if args.list_only:
        return 0

    surf = [g for g in selected if g["type"] in INTERVAL_AGGREGATE_TYPES]
    if surf:
        print("  WARNING: /TH/SURF P and A are reset at every TH write "
              "(sortie_main.F:1976-1982) and P is divided by A (hist2.F:688), so "
              "P is the MEAN pressure over the /TFILE interval and A is the "
              "loaded area times the number of cycles in it - P*A is not the "
              "surface force. No derivative is written for those columns.")

    stem = args.output_stem or default_output_stem(args.th_file)
    written = 0
    for g in selected:
        if not g["vars"] or not g["ids"] or not g["data"]:
            continue
        header, rows = build_table(g, times, derivative=args.derivative)
        path = group_filename(stem, g)
        write_csv(path, header, rows, precision=args.precision)
        ndiff = sum(1 for h in header if h.endswith(DERIV_SUFFIX))
        print("  wrote %s  (%d column(s), %d differentiated)"
              % (os.path.basename(path), len(header) - 1, ndiff))
        written += 1

    if not written:
        print("  nothing matched --only %s" % " ".join(args.only or []))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
