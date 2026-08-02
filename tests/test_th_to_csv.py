"""Tests for ``tools/th_to_csv.py`` — T01 -> CSV with the differentiated
sibling column next to every accumulated /TH channel::

    python -m unittest tests.test_th_to_csv -v

The fixtures are **synthetic T01 files** built by ``_write_synthetic_t01``
below, which writes the engine's own IEEE-binary layout: records framed by a
big-endian 4-byte length marker on both sides (``engine/source/output/th/
wrtdes.F``), big-endian ``int32`` / ``float32`` payloads
(``engine/source/output/tools/ieee.cpp``), the ``hist1.F`` header sequence and
the ``hist2.F`` per-state sequence. Writing the fixture rather than checking in
a binary keeps the format assumption visible and reviewable in the test itself:
if the reader and the writer here ever drift apart from the engine, they drift
together and the docstring above each is the thing to check.

The load-bearing test is ``test_linear_ramp_differentiates_to_a_constant``: a
``REACY`` channel that ramps linearly at a known rate must come back out of the
``REACY_ddt`` column as that constant, because a settled reaction is exactly
what produces a linear ramp in an accumulated channel.

Stdlib only, like the tool.
"""

import gzip
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

# The offline tools live outside tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import th_to_csv                                   # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic T01 writer (the engine's IEEE-binary /TH layout, minimal instance)
# ─────────────────────────────────────────────────────────────────────────────

def _rec(payload: bytes) -> bytes:
    """One Fortran-style record: big-endian byte count, payload, byte count."""
    marker = struct.pack(">i", len(payload))
    return marker + payload + marker


def _title(text: str, ltitl: int = 40) -> bytes:
    return text.ljust(ltitl)[:ltitl].encode("ascii")


def _write_synthetic_t01(path, times, entity_ids, var_codes, values,
                         ityp=0, group_id=7001, gz=False):
    """Write a minimal spec-conforming T01: one /TH group, no parts/subsets.

    ``values[state][entity][var]``. ``ityp`` is the /TH group type code
    (0 = NODE, 101 = INTER, 104 = SECTIO, 102 = RWALL, 6 = SPRING, 116 = SURF).
    ``nglob`` is 0, which is what the engine writes for the auxiliary
    ``/TH1``..``/TH9`` files, so the state record is just time + the group.
    """
    blob = bytearray()
    blob += _rec(struct.pack(">i", 3040) + _title("synthetic T01 fixture", 80))
    blob += _rec(_title("date and version stamp", 80))
    # npart, nummat, numgeo, nsubs, nthgrp, nglob
    blob += _rec(struct.pack(">6i", 0, 0, 0, 0, 1, 0))
    # group descriptor: id, ityp, reserved, n_entities, n_vars, title
    blob += _rec(struct.pack(">5i", group_id, ityp, 0,
                             len(entity_ids), len(var_codes))
                 + _title("synthetic_group"))
    for eid in entity_ids:
        blob += _rec(struct.pack(">i", eid) + _title("entity_%d" % eid))
    blob += _rec(struct.pack(">%di" % len(var_codes), *var_codes))
    for state, t in enumerate(times):
        blob += _rec(struct.pack(">f", t))
        flat = [v for row in values[state] for v in row]
        blob += _rec(struct.pack(">%df" % len(flat), *flat))

    opener = gzip.open if gz else open
    with opener(path, "wb") as fh:
        fh.write(bytes(blob))
    return path


# Codes used below: 620/621 = REACX/REACY, 1 = DX, 4 = VX (thnod.F:124-291).
_REACX, _REACY, _DX, _VX = 620, 621, 1, 4


class _T01Case(unittest.TestCase):
    """Shared temp-dir + fixture helpers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def ramp_t01(self, slope=2.5, nstates=9, dt=0.25, gz=False,
                 var_codes=(_REACY, _DX), ityp=0, name="rampT01"):
        """A T01 whose first channel ramps linearly at ``slope`` per unit time.

        All times and values are exact in binary32 (the file stores singles),
        so the test tolerance measures the derivative scheme, not the format.
        """
        times = [i * dt for i in range(nstates)]
        values = [[[slope * t] + [1.0] * (len(var_codes) - 1)] for t in times]
        path = os.path.join(self.tmp, name)
        return _write_synthetic_t01(path, times, [3], list(var_codes), values,
                                    ityp=ityp, gz=gz), times, slope

    @staticmethod
    def read_csv(path):
        lines = Path(path).read_text().splitlines()
        header = [h.strip() for h in lines[0].split(",")]
        rows = [[float(x) for x in ln.split(",")] for ln in lines[1:]]
        return header, rows


class ThReaderTests(_T01Case):
    """The T01 binary reader round-trips the engine layout."""

    def test_reads_times_ids_and_decoded_variable_names(self):
        path, times, _ = self.ramp_t01()
        got_times, groups = th_to_csv.read_th(path)
        self.assertEqual(len(got_times), len(times))
        for a, b in zip(got_times, times):
            self.assertAlmostEqual(a, b, places=6)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g["type"], "NODE")
        self.assertEqual(g["id"], 7001)
        self.assertEqual(g["ids"], [3])
        # variable CODES are what the file stores; the names are decoded
        self.assertEqual(g["var_codes"], [_REACY, _DX])
        self.assertEqual(g["vars"], ["REACY", "DX"])

    def test_values_survive_the_round_trip(self):
        path, times, slope = self.ramp_t01()
        _t, groups = th_to_csv.read_th(path)
        col = [state[0][0] for state in groups[0]["data"]]
        for t, v in zip(times, col):
            self.assertAlmostEqual(v, slope * t, places=5)

    def test_gzipped_th_file_reads_identically(self):
        plain, _t, _s = self.ramp_t01(name="plainT01")
        packed, _t2, _s2 = self.ramp_t01(gz=True, name="gzT01")
        self.assertEqual(th_to_csv.read_th(plain), th_to_csv.read_th(packed))

    def test_a_truncated_final_state_is_dropped_not_guessed(self):
        path, times, _ = self.ramp_t01()
        raw = Path(path).read_bytes()
        Path(path).write_bytes(raw[:-6])          # chop the last data record
        got_times, groups = th_to_csv.read_th(path)
        self.assertEqual(len(got_times), len(times) - 1)
        self.assertEqual(len(groups[0]["data"]), len(times) - 1)

    def test_a_non_th_file_is_rejected_loudly(self):
        path = os.path.join(self.tmp, "notaT01")
        Path(path).write_bytes(b"this is not a time history file at all")
        with self.assertRaises(th_to_csv.ThFormatError) as cm:
            th_to_csv.read_th(path)
        self.assertIn("time-history", str(cm.exception))


class GradientTests(unittest.TestCase):
    """The derivative kernel, independent of any file."""

    def test_linear_ramp_gives_the_exact_slope_everywhere(self):
        t = [0.0, 0.1, 0.2, 0.3, 0.4]
        v = [3.85 * x for x in t]
        for g in th_to_csv.gradient(v, t):
            self.assertAlmostEqual(g, 3.85, places=9)

    def test_non_uniform_spacing_is_still_exact_on_a_ramp(self):
        # T01 output times are not always evenly spaced (restart, /TFILE change)
        t = [0.0, 0.05, 0.2, 0.21, 0.9]
        v = [-1.25 * x + 7.0 for x in t]
        for g in th_to_csv.gradient(v, t):
            self.assertAlmostEqual(g, -1.25, places=9)

    def test_quadratic_recovers_the_analytic_derivative_on_the_interior(self):
        t = [i * 0.1 for i in range(6)]
        v = [x * x for x in t]
        got = th_to_csv.gradient(v, t)
        for i in range(1, len(t) - 1):
            self.assertAlmostEqual(got[i], 2 * t[i], places=9)

    def test_quadratic_is_exact_on_the_interior_with_uneven_steps_too(self):
        # The three-point interior estimate is the slope of the parabola
        # through the samples, so it is exact for a quadratic at ANY spacing.
        # This is the test that distinguishes the correct formula from the one
        # with the forward and backward steps swapped — every evenly-spaced
        # test passes either way.
        t = [0.0, 0.05, 0.2, 0.21, 0.9, 1.4]
        v = [2.0 * x * x - 0.5 * x + 3.0 for x in t]
        got = th_to_csv.gradient(v, t)
        for i in range(1, len(t) - 1):
            self.assertAlmostEqual(got[i], 4.0 * t[i] - 0.5, places=9)

    def test_degenerate_inputs_do_not_raise(self):
        self.assertEqual(th_to_csv.gradient([], []), [])
        self.assertEqual(th_to_csv.gradient([5.0], [0.0]), [0.0])
        # duplicated output times (restart overlap) must not divide by zero
        self.assertEqual(len(th_to_csv.gradient([1.0, 1.0, 1.0],
                                                [0.0, 0.0, 0.0])), 3)

    def test_length_mismatch_is_an_error(self):
        with self.assertRaises(ValueError):
            th_to_csv.gradient([1.0, 2.0], [0.0])


class AccumulatedChannelTests(unittest.TestCase):
    """Which channels get a derivative, and which must not."""

    def test_reac_channels_are_accumulated(self):
        for var in ("REACX", "REACY", "REACZ", "REACXX", "REACYY", "REACZZ"):
            self.assertTrue(th_to_csv.is_accumulated("NODE", var), var)

    def test_ordinary_node_channels_are_not(self):
        for var in ("DX", "DY", "DZ", "VX", "VY", "VZ", "AX"):
            self.assertFalse(th_to_csv.is_accumulated("NODE", var), var)

    def test_inter_sectio_rwall_force_channels_are_accumulated(self):
        # i7for3.F:1459-1476 (+F*DT12), section_c.F:459-467 (+DT12*FST),
        # rgwal0.F:504-509 (+ nodal impulse sums)
        for var in ("FNX", "FNY", "FNZ", "FTX", "FTY", "FTZ"):
            for gtype in ("INTER", "SECTIO", "RWALL"):
                self.assertTrue(th_to_csv.is_accumulated(gtype, var),
                                "%s %s" % (gtype, var))
        for var in ("M1", "M2", "M3"):
            self.assertTrue(th_to_csv.is_accumulated("SECTIO", var), var)

    def test_spring_and_element_channels_are_instantaneous(self):
        # thres.F:355-361 writes GBUF%FOR/MOM straight out — a real force.
        for var in ("FX", "FY", "FZ", "MX", "MY", "MZ"):
            self.assertFalse(th_to_csv.is_accumulated("SPRING", var), var)
        for var in ("F1", "F2", "F12", "M1", "M2", "M12"):
            self.assertFalse(th_to_csv.is_accumulated("SHELL", var), var)
        for var in ("SX", "SY", "SZ", "IE"):
            self.assertFalse(th_to_csv.is_accumulated("BRICK", var), var)

    def test_surf_channels_are_flagged_but_never_differentiated(self):
        # P is a /TFILE-interval MEAN and A is the loaded area times the cycle
        # count (pblast_1.F:418-419, hist2.F:688, sortie_main.F:1976-1982),
        # so a time derivative of either is meaningless.
        self.assertIn("SURF", th_to_csv.INTERVAL_AGGREGATE_TYPES)
        for var in ("P", "A", "AREA"):
            self.assertFalse(th_to_csv.is_accumulated("SURF", var), var)


class DerivativeColumnTests(_T01Case):
    """The differentiated sibling column, end to end through build_table."""

    def test_linear_ramp_differentiates_to_a_constant(self):
        """The load-bearing test: a steady reaction ramps the accumulated
        channel linearly, so REACY_ddt must come back as the constant force."""
        path, times, slope = self.ramp_t01(slope=3.85, nstates=13, dt=0.02)
        got_times, groups = th_to_csv.read_th(path)
        header, rows = th_to_csv.build_table(groups[0], got_times)
        self.assertIn("3_REACY_ddt", header)
        col = header.index("3_REACY_ddt")
        for row in rows:
            self.assertAlmostEqual(row[col], slope, places=4)

    def test_the_sibling_sits_next_to_its_source_and_nothing_moves(self):
        path, _t, _s = self.ramp_t01(var_codes=(_REACX, _DX, _REACY))
        times, groups = th_to_csv.read_th(path)
        header, _rows = th_to_csv.build_table(groups[0], times)
        self.assertEqual(header, ["time", "3_REACX", "3_REACX_ddt",
                                  "3_DX", "3_REACY", "3_REACY_ddt"])

    def test_raw_columns_are_untouched_by_the_addition(self):
        path, times, slope = self.ramp_t01(slope=2.5)
        got_times, groups = th_to_csv.read_th(path)
        plain, plain_rows = th_to_csv.build_table(groups[0], got_times,
                                                  derivative=False)
        rich, rich_rows = th_to_csv.build_table(groups[0], got_times)
        self.assertEqual(plain, ["time", "3_REACY", "3_DX"])
        for pr, rr in zip(plain_rows, rich_rows):
            for name, value in zip(plain, pr):
                self.assertEqual(value, rr[rich.index(name)])

    def test_no_derivative_for_an_instantaneous_only_group(self):
        path, _t, _s = self.ramp_t01(var_codes=(_DX, _VX))
        times, groups = th_to_csv.read_th(path)
        header, _rows = th_to_csv.build_table(groups[0], times)
        self.assertEqual(header, ["time", "3_DX", "3_VX"])

    def test_inter_group_gets_the_derivative_too(self):
        # /TH/INTER DEF = codes 1..6 = FNX FNY FNZ FTX FTY FTZ
        path, _t, slope = self.ramp_t01(var_codes=(1, 2), ityp=101)
        times, groups = th_to_csv.read_th(path)
        self.assertEqual(groups[0]["type"], "INTER")
        header, rows = th_to_csv.build_table(groups[0], times)
        self.assertIn("3_FNX_ddt", header)
        col = header.index("3_FNX_ddt")
        for row in rows:
            self.assertAlmostEqual(row[col], slope, places=4)


class CliTests(_T01Case):
    """The command line: what it writes and what it refuses to do."""

    def test_main_writes_a_csv_with_the_derivative_column(self):
        path, _t, slope = self.ramp_t01(slope=3.85, nstates=11, dt=0.02)
        stem = os.path.join(self.tmp, "out")
        self.assertEqual(th_to_csv.main([path, "-o", stem]), 0)
        csv_path = stem + "_th_NODE_7001.csv"
        self.assertTrue(os.path.exists(csv_path))
        header, rows = self.read_csv(csv_path)
        self.assertEqual(header, ["time", "3_REACY", "3_REACY_ddt", "3_DX"])
        col = header.index("3_REACY_ddt")
        for row in rows:
            self.assertAlmostEqual(row[col], slope, places=3)

    def test_no_derivative_flag_writes_the_raw_channels_only(self):
        path, _t, _s = self.ramp_t01()
        stem = os.path.join(self.tmp, "raw")
        self.assertEqual(th_to_csv.main([path, "-o", stem, "--no-derivative"]), 0)
        header, _rows = self.read_csv(stem + "_th_NODE_7001.csv")
        self.assertEqual(header, ["time", "3_REACY", "3_DX"])

    def test_list_only_writes_nothing(self):
        path, _t, _s = self.ramp_t01()
        stem = os.path.join(self.tmp, "listed")
        self.assertEqual(th_to_csv.main([path, "-o", stem, "--list"]), 0)
        self.assertFalse(os.path.exists(stem + "_th_NODE_7001.csv"))

    def test_only_filter_selects_by_type(self):
        path, _t, _s = self.ramp_t01()
        stem = os.path.join(self.tmp, "filt")
        self.assertEqual(th_to_csv.main([path, "-o", stem, "--only", "INTER"]), 1)
        self.assertFalse(os.path.exists(stem + "_th_NODE_7001.csv"))
        self.assertEqual(th_to_csv.main([path, "-o", stem, "--only", "node"]), 0)
        self.assertTrue(os.path.exists(stem + "_th_NODE_7001.csv"))

    def test_a_bad_file_returns_nonzero_instead_of_a_traceback(self):
        path = os.path.join(self.tmp, "junkT01")
        Path(path).write_bytes(b"\x00" * 64)
        self.assertEqual(th_to_csv.main([path, "-o", os.path.join(self.tmp, "x")]), 1)

    def test_default_output_stem_strips_the_run_number(self):
        self.assertEqual(th_to_csv.default_output_stem("/a/b/runT01"), "/a/b/run")
        self.assertEqual(th_to_csv.default_output_stem("/a/b/runT12"), "/a/b/run")
        self.assertEqual(th_to_csv.default_output_stem("/a/b/run_0001.thy"),
                         "/a/b/run_0001")


if __name__ == "__main__":
    unittest.main()
