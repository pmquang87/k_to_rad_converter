"""/TH/SURF on an SPMD run: every blast-loaded surface must record, so the
deck gets inert padding /SURF cards.

The defect (observed 2026-08-03 on two independent OpenRadioss 2026 MPI runs,
E:/w13/stack4 12 domains and E:/w13/neuberger 6 domains): k2rad emits ONE
/TH/SURF block listing every *DATABASE_BINARY_BLSTFOR surface — which is
LEGAL, the starter flags each listed id (hm_read_thgrsurf.F:147-175) and the
engine writes one P/A pair per surface (thsurf.F:71-80) — yet in the T01 only
the LOWEST-indexed surfaces carried data; the rest were exactly 0.0 all run.

Root cause is an OpenRadioss engine bug, not the card grouping: the /TH/SURF
channel array is (TH_SURF_NUM_CHANNEL=6, NSURF) (th_surf_mod.F:96-100) but
the MPI reduction covers only its first 5*NSURF elements::

    engine/source/output/th/hist2.F:679
    IF(NSPMD > 1)CALL SPMD_GLOB_DSUM9(FSAVSURF,5*NSURF)

Column-major: surface I's channel c sits at flat position 6*(I-1)+c, so a
surface violating 6*(I-1)+5 <= 5*NSURF never gets its P (ch4) / loaded-area
(ch5) summed across domains — domain 0 writes its local zeros, and
hist2.F:687-691 zeroes P whenever the unreduced ch5 is 0. The internal index
is the surface's position among ALL /SURF options in deck order (planes
included); the /TH/SURF block layout is irrelevant, so splitting the block
per surface would fix nothing.

The k2rad fix (assembly._pad_surfaces_for_spmd_th_surf) appends
K = ceil((6*I_max - 1 - 5*NSURF)/5) inert /SURF/SEG cards AFTER the last real
surface, raising NSURF without moving the /TH/SURF surfaces, so every listed
surface satisfies the inequality. These tests pin that card shape.
"""

import os
import re
import tempfile
import unittest

from k2rad import convert
from k2rad.writer.assembly import _SURF_CARD_RE, _th_surf_listed_ids


def _convert(deck: str, **opts):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **opts)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _surf_table(starter: str):
    """[(position_1based, id)] for every /SURF option of any type, deck order —
    exactly the engine's internal surface numbering."""
    out = []
    for ln in starter.splitlines():
        m = _SURF_CARD_RE.match(ln)
        if m:
            out.append((len(out) + 1, int(m.group(1))))
    return out


def _th_surf_ids(starter: str):
    return _th_surf_listed_ids(starter.splitlines())


def _assert_spmd_reduction_covers_th(testcase, starter: str):
    """The invariant the padding exists for: every /TH/SURF-listed surface at
    internal index I satisfies 6*(I-1)+5 <= 5*NSURF (channels 1..5 inside the
    engine's SPMD-reduced prefix, hist2.F:679)."""
    table = _surf_table(starter)
    th_ids = set(_th_surf_ids(starter))
    n_surf = len(table)
    for pos, sid in table:
        if sid in th_ids:
            testcase.assertLessEqual(
                6 * (pos - 1) + 5, 5 * n_surf,
                f"/TH/SURF surface {sid} at internal index {pos} of {n_surf} "
                "is OUTSIDE the engine's 5*NSURF SPMD reduction — its P/A "
                "channels read 0.0 on any MPI run (hist2.F:679)")


# Two blast-loaded segment sets on one charge. blast=2 (spherical free air)
# emits NO ground plane, so the surface table is exactly the two blast
# /SURF/SEG — the tightest case: index 2 of 2 puts ch5 at flat position 11 of
# a 10-element reduced prefix (the E:/w13/neuberger shape, where surface
# 90003 recorded 0.0 for the whole run).
TWO_SURF_FREE_AIR_K = """\
*KEYWORD
*TITLE
Two blast surfaces, free air
*CONTROL_TERMINATION
     0.006
*NODE
       1       0.0       0.0       0.0
       2       1.0       0.0       0.0
       3       1.0       1.0       0.0
       4       0.0       1.0       0.0
       5       0.0       0.0       1.0
       6       1.0       0.0       1.0
       7       1.0       1.0       1.0
       8       0.0       1.0       1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       5       6       7       8
*PART
target plate
         1         1         1
*SECTION_SHELL
         1         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_PLASTIC_KINEMATIC
         1    7500.02.10000E11       0.31.200000E91.10000E10       0.0
       0.0       0.0    0.0015       0.0
*SET_SEGMENT
         1       0.0       0.0       0.0       0.0MECH               0
         1         2         3         4       0.0       0.0       0.0       0.0
*SET_SEGMENT
         2       0.0       0.0       0.0       0.0MECH               0
         5         6         7         8       0.0       0.0       0.0       0.0
*LOAD_BLAST_SEGMENT_SET
         1         1         0       0.0       1.0
*LOAD_BLAST_SEGMENT_SET
         1         2         0       0.0       1.0
*LOAD_BLAST_ENHANCED
         1      50.0       2.5       0.0       5.0       0.0         2         2
       0.0       0.0       0.0       0.0         01.00000E20         0
*DATABASE_BINARY_BLSTFOR
2.00000E-5         0         0         0         0
*END
"""

# Same model, blast=1 (hemispherical surface burst): each /LOAD/PBLAST
# synthesizes a /SURF/PLANE ground right after its /SURF/SEG, so the table is
# SEG,PLANE,SEG,PLANE — the blast surfaces sit at indices 1 and 3 of 4 and
# already satisfy the inequality (6*2+5=17 <= 20): no padding must appear.
TWO_SURF_GROUND_K = TWO_SURF_FREE_AIR_K.replace(
    "         1      50.0       2.5       0.0       5.0       0.0         2         2",
    "         1      50.0       2.5       0.0       5.0       0.0         2         1")

# Single free-air surface: index 1 of 1, ch5 at flat position 5 = 5*NSURF —
# exactly on the boundary, already safe: no padding.
ONE_SURF_FREE_AIR_K = TWO_SURF_FREE_AIR_K.replace(
    "*LOAD_BLAST_SEGMENT_SET\n"
    "         1         2         0       0.0       1.0\n", "")

# No *DATABASE_BINARY_BLSTFOR: no /TH/SURF is emitted, so no padding either.
NO_BLSTFOR_K = TWO_SURF_FREE_AIR_K.replace(
    "*DATABASE_BINARY_BLSTFOR\n"
    "2.00000E-5         0         0         0         0\n", "")

_PAD_TITLE_RE = re.compile(r"^TH_surf_spmd_pad_(\d+)\b")


class ThSurfSpmdPaddingTests(unittest.TestCase):
    """Pins the emitted card shape: one /TH/SURF block listing every blast
    surface (unchanged, and correct) plus the inert padding /SURF/SEG cards
    that keep all of them inside the engine's SPMD-reduced channel prefix."""

    def _pad_cards(self, starter: str):
        """[(surf_id, title, seg_line)] for every padding card, deck order."""
        lines = starter.splitlines()
        out = []
        for i, ln in enumerate(lines):
            m = _SURF_CARD_RE.match(ln)
            if m and _PAD_TITLE_RE.match(lines[i + 1]):
                self.assertTrue(ln.startswith("/SURF/SEG/"),
                                f"padding surface must be a /SURF/SEG: {ln}")
                # title, seg-header comment, one segment data line
                self.assertTrue(lines[i + 2].startswith("#"))
                out.append((int(m.group(1)), lines[i + 1], lines[i + 3]))
        return out

    # ── the failing shape: two free-air surfaces (neuberger) ────────────
    def test_th_surf_block_lists_every_blast_surface(self):
        _, starter = _convert(TWO_SURF_FREE_AIR_K)
        table = dict((sid, pos) for pos, sid in _surf_table(starter))
        th_ids = _th_surf_ids(starter)
        self.assertEqual(len(th_ids), 2)
        # both blast surfaces, in emission order, in ONE block
        self.assertEqual(sorted(th_ids), th_ids)
        self.assertEqual(starter.count("/TH/SURF/"), 1)
        for sid in th_ids:
            self.assertIn(sid, table)

    def test_padding_emitted_and_last(self):
        _, starter = _convert(TWO_SURF_FREE_AIR_K)
        pads = self._pad_cards(starter)
        # deficit = 6*(2-1)+5 - 5*2 = 1 -> exactly one padding card
        self.assertEqual(len(pads), 1)
        pad_id, title, seg_line = pads[0]
        self.assertEqual(title[:len("TH_surf_spmd_pad_1")],
                         "TH_surf_spmd_pad_1")
        table = _surf_table(starter)
        # padding is the LAST surface of the table and has the highest id,
        # so the /TH/SURF surfaces keep their internal index under both
        # deck-order and id-order numbering
        self.assertEqual(table[-1][1], pad_id)
        self.assertEqual(max(sid for _, sid in table), pad_id)
        # its single segment duplicates the FIRST blast segment (valid nodes)
        th_ids = _th_surf_ids(starter)
        first_surf = f"/SURF/SEG/{th_ids[0]}"
        lines = starter.splitlines()
        i = lines.index(first_surf)
        donor = next(ln for ln in lines[i + 2:]
                     if not ln.startswith("#") and ln.split()
                     and all(t.isdigit() for t in ln.split()))
        self.assertEqual(seg_line.split()[1:5], donor.split()[1:5])
        self.assertEqual(seg_line.split()[0], "1")
        # padding is inert: its id appears exactly once (its own header)
        self.assertEqual(starter.count(str(pad_id)), 1)

    def test_invariant_holds_after_padding(self):
        _, starter = _convert(TWO_SURF_FREE_AIR_K)
        _assert_spmd_reduction_covers_th(self, starter)

    def test_padding_warned_with_root_cause(self):
        result, _ = _convert(TWO_SURF_FREE_AIR_K)
        w = [x for x in result.warnings if "hist2.F:679" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("SPMD", w[0])
        self.assertIn("1 inert padding /SURF/SEG card(s)", w[0])

    # ── shapes that need NO padding ─────────────────────────────────────
    def test_no_padding_when_ground_planes_raise_nsurf(self):
        _, starter = _convert(TWO_SURF_GROUND_K)
        self.assertEqual(self._pad_cards(starter), [])
        self.assertNotIn("TH_surf_spmd_pad", starter)
        # ...because the invariant already holds: SEG,PLANE,SEG,PLANE
        self.assertEqual(len(_surf_table(starter)), 4)
        _assert_spmd_reduction_covers_th(self, starter)

    def test_no_padding_single_surface_boundary(self):
        _, starter = _convert(ONE_SURF_FREE_AIR_K)
        self.assertEqual(len(_surf_table(starter)), 1)
        self.assertNotIn("TH_surf_spmd_pad", starter)
        _assert_spmd_reduction_covers_th(self, starter)

    def test_no_padding_without_blstfor(self):
        result, starter = _convert(NO_BLSTFOR_K)
        self.assertNotIn("/TH/SURF/", starter)
        self.assertNotIn("TH_surf_spmd_pad", starter)
        self.assertFalse(any("hist2.F:679" in x for x in result.warnings))


if __name__ == "__main__":
    unittest.main()
