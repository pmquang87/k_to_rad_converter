"""Tests for the INITIAL-STATE and CROSS-SECTION conversions:

  *INITIAL_STRESS_SHELL          → /INISHE/STRS_F/GLOB (ILOC=0) / /INISHE/STRS_F
  *INITIAL_STRESS_SOLID          → /INIBRI/STRS_FGLO
  *DATABASE_CROSS_SECTION_SET    → /SECT (direct set mapping) + /TH/SECTIO
  *DATABASE_CROSS_SECTION_PLANE  → /SECT (geometric plane-cut resolver)
  *DATABASE_SECFORC              → /TH/SECTIO pairing

Kept in its own module (modelled on tests/test_roadmap_keywords.py) so the
additions do not collide with other in-flight work on the big test files.
"""

import os
import re
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState
from k2rad.writer import _f, _i


def _convert(deck: str):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


def _dispatch(deck: str) -> ConversionState:
    """Parse + dispatch a deck string into a fresh ConversionState."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _block_ids(starter: str, header_prefix: str):
    """Return the integer ids listed in the first starter block whose header
    line starts with *header_prefix* (e.g. '/GRNOD/NODE/', '/GRSHEL/SHEL/')."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(header_prefix):
            ids = []
            for data in lines[i + 2:]:          # skip the title line
                if data.startswith("/"):
                    break
                if data.startswith("#"):        # comment / HDR rulers
                    continue
                ids.extend(int(t) for t in data.split() if t.lstrip("-").isdigit())
            return ids
    return None


# ── Shared deck fragments ────────────────────────────────────────────────────

SHELL_STRIP = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             2.0             0.0             0.0\n"
    "       6             2.0             1.0             0.0\n"
    "*PART\n"
    "strip\n"
    "         1         1         1\n"
    # secid=1 elform=2 shrf=(blank) nip=2
    "*SECTION_SHELL\n"
    "         1         2                   2\n"
    "       1.0\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       1       2       5       6       3\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

# eid=1, NPLANE=1, NTHICK=2 → two per-layer stress cards
# (T SIGXX SIGYY SIGZZ SIGXY SIGYZ SIGZX EPS)
INI_STRESS_SHELL = (
    "*INITIAL_STRESS_SHELL\n"
    "         1         1         2\n"
    "      -0.5     100.0     200.0      50.0      10.0      20.0      30.0      0.01\n"
    "       0.5     110.0     210.0      55.0      11.0      21.0      31.0      0.02\n"
)

SOLID_CUBE = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             0.0             0.0             1.0\n"
    "       6             1.0             0.0             1.0\n"
    "       7             1.0             1.0             1.0\n"
    "       8             0.0             1.0             1.0\n"
    "*PART\n"
    "cube\n"
    "         1         1         1\n"
    "*SECTION_SOLID\n"
    "         1         1\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9  210000.0       0.3\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


# ═════════════════════════════════════════════════════════════════════════════
# *INITIAL_STRESS_SHELL → /INISHE
# ═════════════════════════════════════════════════════════════════════════════

class InitialStressShellTests(unittest.TestCase):
    def test_emits_glob_flavour_with_matching_layers(self):
        deck = SHELL_STRIP.replace("{EXTRA}", INI_STRESS_SHELL)
        _, starter, _ = _convert(deck)
        self.assertIn("/INISHE/STRS_F/GLOB", starter)
        # Card 1: shell_ID=1, nb_integr=NTHICK=2, npg=4 (Ishell 12/24), Thick=0
        self.assertIn(f"{_i(1)}{_i(2)}{_i(4)}{_f(0.0)}", starter)
        # Tensor columns per the radioss2021 glob cfg:
        #   (sigma_X sigma_Y sigma_Z) then (sigma_XY sigma_YZ sigma_ZX eps_p pos_nip)
        lay1_a = f"{_f(100.0)}{_f(200.0)}{_f(50.0)}"
        lay1_b = f"{_f(10.0)}{_f(20.0)}{_f(30.0)}{_f(0.01)}{_f(-0.5)}"
        lay2_a = f"{_f(110.0)}{_f(210.0)}{_f(55.0)}"
        lay2_b = f"{_f(11.0)}{_f(21.0)}{_f(31.0)}{_f(0.02)}{_f(0.5)}"
        # Each layer record is replicated across the npg=4 in-plane Gauss points
        self.assertEqual(starter.count(lay1_a), 4)
        self.assertEqual(starter.count(lay1_b), 4)
        self.assertEqual(starter.count(lay2_a), 4)
        self.assertEqual(starter.count(lay2_b), 4)

    def test_handler_collects_layers(self):
        deck = SHELL_STRIP.replace("{EXTRA}", INI_STRESS_SHELL)
        state = _dispatch(deck)
        self.assertEqual(len(state.ini_stress_shells), 1)
        iss = state.ini_stress_shells[0]
        self.assertEqual(iss.eid, 1)
        self.assertEqual(iss.nthick, 2)
        self.assertEqual(iss.iloc, 0)
        self.assertEqual(len(iss.layers), 2)
        self.assertEqual(iss.layers[0], (-0.5, 100.0, 200.0, 50.0, 10.0, 20.0, 30.0, 0.01))

    def test_nthick_mismatch_warns_and_skips(self):
        # /PROP/SHELL N = max(2, NIP=3) = 3 but the element supplies NTHICK=2.
        deck = SHELL_STRIP.replace(
            "         1         2                   2\n",
            "         1         2                   3\n",
        ).replace("{EXTRA}", INI_STRESS_SHELL)
        result, starter, _ = _convert(deck)
        self.assertNotIn("/INISHE", starter)
        self.assertTrue(any("NTHICK" in w and "skip" in w.lower()
                            for w in result.warnings))

    def test_nplane_average_warns(self):
        # NPLANE=2, NTHICK=1 → the two in-plane points are averaged into one layer.
        ini = (
            "*INITIAL_STRESS_SHELL\n"
            "         1         2         1\n"
            "       0.0     100.0     200.0       0.0       0.0       0.0       0.0       0.0\n"
            "       0.0     300.0     400.0       0.0       0.0       0.0       0.0       0.0\n"
        )
        # NIP=1 → property N = max(2, 1) = 2 would mismatch; use NTHICK=1... the
        # writer must skip it, but the handler-side averaging is what we assert.
        state = _dispatch(SHELL_STRIP.replace("{EXTRA}", ini))
        iss = state.ini_stress_shells[0]
        self.assertEqual(len(iss.layers), 1)
        self.assertEqual(iss.layers[0][1], 200.0)   # (100+300)/2
        self.assertEqual(iss.layers[0][2], 300.0)   # (200+400)/2
        self.assertTrue(any("AVERAGED" in w for w in state.warnings))

    def test_nhisv_dropped_with_warning(self):
        ini = (
            "*INITIAL_STRESS_SHELL\n"
            "         1         1         2         2\n"
            "      -0.5     100.0     200.0      50.0      10.0      20.0      30.0      0.01\n"
            "       1.0       2.0\n"
            "       0.5     110.0     210.0      55.0      11.0      21.0      31.0      0.02\n"
            "       3.0       4.0\n"
        )
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", ini))
        # history cards consumed (both layers parsed), warned dropped
        self.assertIn("/INISHE/STRS_F/GLOB", starter)
        self.assertIn(f"{_f(110.0)}{_f(210.0)}{_f(55.0)}", starter)
        self.assertTrue(any("NHISV" in w and "dropped" in w for w in result.warnings))

    def test_iloc_local_flavour_drops_szz_with_warning(self):
        ini = (
            "*INITIAL_STRESS_SHELL\n"
            "         1         1         2         0         0         0         0         0         1\n"
            "      -0.5     100.0     200.0      50.0      10.0      20.0      30.0      0.01\n"
            "       0.5     110.0     210.0      55.0      11.0      21.0      31.0      0.02\n"
        )
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", ini))
        self.assertIn("/INISHE/STRS_F\n", starter)
        self.assertNotIn("/INISHE/STRS_F/GLOB", starter)
        # local layout: (sigma_1 sigma_2 sigma_12) / (sigma_23 sigma_31 eps_p)
        self.assertEqual(starter.count(f"{_f(100.0)}{_f(200.0)}{_f(10.0)}"), 4)
        self.assertEqual(starter.count(f"{_f(20.0)}{_f(30.0)}{_f(0.01)}"), 4)
        self.assertTrue(any("sigma_zz" in w.lower() or "SIGZZ" in w
                            for w in result.warnings))


# ═════════════════════════════════════════════════════════════════════════════
# *INITIAL_STRESS_SOLID → /INIBRI
# ═════════════════════════════════════════════════════════════════════════════

class InitialStressSolidTests(unittest.TestCase):
    INI = (
        "*INITIAL_STRESS_SOLID\n"
        "         1         1\n"
        "     100.0     200.0     300.0      10.0      20.0      30.0      0.05\n"
    )

    def test_emits_inibri_glob(self):
        result, starter, _ = _convert(SOLID_CUBE.replace("{EXTRA}", self.INI))
        self.assertIn("/INIBRI/STRS_FGLO", starter)
        # Card 1: brick_ID=1, Nb_integr=8 (Isolid 17 = 8 points), Isolnod=8,
        # Isolid=17, nptr=npts=nptt=2, nlay=1, grbric=0
        self.assertIn(f"{_i(1)}{_i(8)}{_i(8)}{_i(17)}{_i(2)}{_i(2)}{_i(2)}{_i(1)}{_i(0)}",
                      starter)
        # NINT=1 replicated onto the 8-point formulation; component order per
        # the radioss2021 cfg: (SIGMA1 SIGMA2 SIGMA3) / (SIGMA12 SIGMA23 SIGMA31)
        self.assertEqual(starter.count(f"{_f(100.0)}{_f(200.0)}{_f(300.0)}"), 8)
        self.assertEqual(starter.count(f"{_f(10.0)}{_f(20.0)}{_f(30.0)}"), 8)
        # layout A: EPS on its own Epsilon_p card
        self.assertEqual(starter.count(f"\n{_f(0.05)}\n"), 8)

    def test_handler_collects_points(self):
        state = _dispatch(SOLID_CUBE.replace("{EXTRA}", self.INI))
        self.assertEqual(len(state.ini_stress_solids), 1)
        iss = state.ini_stress_solids[0]
        self.assertEqual(iss.eid, 1)
        self.assertEqual(iss.points[0], (100.0, 200.0, 300.0, 10.0, 20.0, 30.0, 0.05))

    def test_unknown_element_warns(self):
        ini = self.INI.replace("         1         1\n", "        99         1\n")
        result, starter, _ = _convert(SOLID_CUBE.replace("{EXTRA}", ini))
        self.assertNotIn("/INIBRI", starter)
        self.assertTrue(any("INITIAL_STRESS_SOLID" in w and "not found" in w
                            for w in result.warnings))


# ═════════════════════════════════════════════════════════════════════════════
# *DATABASE_CROSS_SECTION_SET → /SECT + /TH/SECTIO
# ═════════════════════════════════════════════════════════════════════════════

CROSS_SET = (
    "*SET_NODE_LIST\n"
    "        10\n"
    "         1         4\n"
    "*SET_SHELL_LIST\n"
    "        20\n"
    "         1\n"
    "*DATABASE_CROSS_SECTION_SET_ID\n"
    "         5cut section\n"
    "        10" + " " * 20 + "        20\n"
)


class CrossSectionSetTests(unittest.TestCase):
    def test_set_emits_sect_referencing_the_sets(self):
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", CROSS_SET))
        self.assertIn("/SECT/5", starter)
        # the node set became the /SECT grnod
        self.assertEqual(_block_ids(starter, "/GRNOD/NODE/"), [1, 4])
        # the shell set became the /SECT grshel
        self.assertEqual(_block_ids(starter, "/GRSHEL/SHEL/"), [1])
        # /SECT main card references the section's own grnod (emitted with a
        # "<title>_nodes" title, distinct from the raw *SET_NODE_LIST group)
        m = re.search(r"/GRNOD/NODE/(\d+)\ncut section_nodes", starter)
        grnod_id = int(m.group(1))
        sect_card = re.search(
            r"/SECT/5\ncut section\n#[^\n]*\n([^\n]*)\n", starter).group(1)
        self.assertIn(_i(grnod_id), sect_card)
        # grshel id sits on the element-group card
        gshel = int(re.search(r"/GRSHEL/SHEL/(\d+)", starter).group(1))
        self.assertIn(_i(gshel), starter.split("/SECT/5", 1)[1][:600])

    def test_th_sectio_lists_the_section(self):
        _, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", CROSS_SET))
        self.assertIn("/TH/SECTIO/", starter)
        self.assertEqual(_block_ids(starter, "/TH/SECTIO/"), [5])

    def test_handler_records_set_ids(self):
        state = _dispatch(SHELL_STRIP.replace("{EXTRA}", CROSS_SET))
        self.assertEqual(len(state.cross_sections), 1)
        cs = state.cross_sections[0]
        self.assertEqual((cs.csid, cs.kind, cs.nsid, cs.ssid), (5, "SET", 10, 20))
        self.assertEqual(state.shell_sets[20], ("", [1]))

    def test_missing_node_set_warns_and_skips(self):
        bad = CROSS_SET.replace("        10\n         1         4\n*SET_SHELL",
                                "        99\n         1         4\n*SET_SHELL")
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", bad))
        self.assertNotIn("/SECT/", starter)
        self.assertTrue(any("node set 10 not found" in w for w in result.warnings))


# ═════════════════════════════════════════════════════════════════════════════
# *DATABASE_CROSS_SECTION_PLANE → geometric resolver
# ═════════════════════════════════════════════════════════════════════════════

CROSS_PLANE = (
    "*DATABASE_CROSS_SECTION_PLANE\n"
    "         0       0.5       0.0       0.0       1.5       0.0       0.0\n"
)


class CrossSectionPlaneTests(unittest.TestCase):
    def test_plane_picks_the_straddling_element(self):
        # 2-quad strip: element 1 spans x∈[0,1], element 2 spans x∈[1,2].
        # Plane through x=0.5 with normal +X cuts element 1 only; the section
        # node group is the cut element's nodes on the tail side (x=0 → 1, 4).
        _, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", CROSS_PLANE))
        self.assertIn("/SECT/", starter)
        self.assertEqual(_block_ids(starter, "/GRSHEL/SHEL/"), [1])
        self.assertEqual(_block_ids(starter, "/GRNOD/NODE/"), [1, 4])

    def test_plane_between_far_elements_cuts_second(self):
        # tail x=1.5, head x=2.5 → cuts element 2; tail-side nodes are the
        # shared edge at x=1 (nodes 2, 3).
        plane = (
            "*DATABASE_CROSS_SECTION_PLANE\n"
            "         0       1.5       0.0       0.0       2.5       0.0       0.0\n"
        )
        _, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", plane))
        self.assertEqual(_block_ids(starter, "/GRSHEL/SHEL/"), [2])
        self.assertEqual(_block_ids(starter, "/GRNOD/NODE/"), [2, 3])

    def test_no_cut_warns_and_skips(self):
        plane = (
            "*DATABASE_CROSS_SECTION_PLANE\n"
            "         0       9.0       0.0       0.0      10.0       0.0       0.0\n"
        )
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", plane))
        self.assertNotIn("/SECT/", starter)
        self.assertTrue(any("cuts no element" in w for w in result.warnings))

    def test_radius_restricts_cut(self):
        # Same cutting plane but a tiny RADIUS centred far off the strip in Y:
        # element centroid (0.5, 0.5) is outside the r=0.1 circle around y=5.
        plane = (
            "*DATABASE_CROSS_SECTION_PLANE\n"
            "         0       0.5       5.0       0.0       1.5       5.0       0.0       0.1\n"
        )
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", plane))
        self.assertNotIn("/SECT/", starter)

    def test_finite_parallelogram_warns(self):
        plane = (
            "*DATABASE_CROSS_SECTION_PLANE\n"
            "         0       0.5       0.0       0.0       1.5       0.0       0.0\n"
            "       0.0       1.0       0.0       2.0       2.0\n"
        )
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", plane))
        self.assertTrue(any("parallelogram" in w for w in result.warnings))
        self.assertIn("/SECT/", starter)   # still resolved as an infinite plane


# ═════════════════════════════════════════════════════════════════════════════
# *DATABASE_SECFORC ↔ /TH/SECTIO pairing
# ═════════════════════════════════════════════════════════════════════════════

class SecforcTests(unittest.TestCase):
    def test_secforc_sets_tfile_dt_and_pairs_th(self):
        deck = SHELL_STRIP.replace(
            "{EXTRA}", CROSS_SET + "*DATABASE_SECFORC\n      0.01\n")
        result, starter, engine = _convert(deck)
        self.assertIn("/TH/SECTIO/", starter)
        self.assertIn("/TFILE\n0.01", engine)
        # a requested SECFORC must not trigger the "emitted anyway" note
        self.assertFalse(any("without *DATABASE_SECFORC" in w
                             for w in result.warnings))

    def test_sections_without_secforc_still_get_th_with_note(self):
        result, starter, _ = _convert(SHELL_STRIP.replace("{EXTRA}", CROSS_SET))
        self.assertIn("/TH/SECTIO/", starter)
        self.assertTrue(any("without *DATABASE_SECFORC" in w
                            for w in result.warnings))

    def test_secforc_alone_emits_no_th(self):
        deck = SHELL_STRIP.replace("{EXTRA}", "*DATABASE_SECFORC\n      0.01\n")
        _, starter, _ = _convert(deck)
        self.assertNotIn("/TH/SECTIO/", starter)


if __name__ == "__main__":
    unittest.main()
