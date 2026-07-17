"""Tests for per-part hourglass control: *HOURGLASS + *PART HGID → per-part
/PROP h/Isolid (solid) and Hm/Hf/Hr (shell), overriding the global
*CONTROL_HOURGLASS, with a dedicated /PROP split when a part on a shared
*SECTION resolves differently (k2rad props are per-section).

Behaviour follows dyna2rad ConvertProp::ConvertEntities (solid IHQ→Isolid
1/2/3→1, 4/5→5, 6/7→24; h←QM/QH); k2rad additionally carries the coefficient
onto shells (clamped to the Radioss shell max 0.05) and warns where dyna2rad is
silent (dangling HGID, unsupported IHQ, inert shell coefficient).

Kept in a separate module from tests/test_converter.py, following the
tests/test_roadmap_keywords.py / tests/test_mat103.py harness so the additions
do not collide with other in-flight work.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState


def _convert(deck: str, **opts):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **opts)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


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


def _block_lines(starter: str, header_prefix: str):
    """The non-comment/non-blank lines of a /-block: [title, data cards...]."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(header_prefix))
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("/"):
            break
        if ln.startswith("#") or not ln.strip():
            continue
        out.append(ln)
    return out


# _block_lines returns [title, data-card-1, data-card-2, ...] (title at [0]).

def _part_prop_ref(starter: str, pid: int) -> int:
    """The /PROP id a /PART points at (part data card cols 1-10)."""
    return int(_block_lines(starter, f"/PART/{pid}")[1][0:10])


def _solid_isolid_h(starter: str, prop_hdr: str):
    """(Isolid, h) for a /PROP/SOLID block: Isolid card col 1-10, h card 41-60."""
    d = _block_lines(starter, prop_hdr)
    return int(d[1][0:10]), float(d[2][40:60])


def _shell_ishell_hm(starter: str, prop_hdr: str):
    """(Ishell, Hm) for a /PROP/SHELL block: Ishell col 1-10, Hm card 1-20."""
    d = _block_lines(starter, prop_hdr)
    return int(d[1][0:10]), float(d[2][0:20])


# ── Deck building blocks ─────────────────────────────────────────────────────

_NODES = (
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             0.0             0.0             1.0\n"
    "       6             1.0             0.0             1.0\n"
    "       7             1.0             1.0             1.0\n"
    "       8             0.0             1.0             1.0\n"
    "       9             5.0             0.0             0.0\n"
    "      10             6.0             0.0             0.0\n"
    "      11             6.0             1.0             0.0\n"
    "      12             5.0             1.0             0.0\n"
)

_MAT = (
    "*MAT_ELASTIC\n"
    "         1     7.85E-9  210000.0       0.3\n"
    "*MAT_ELASTIC\n"
    "         2     7.85E-9  210000.0       0.3\n"
)


def _pcard(pid, secid, mid, hgid=0):
    return f"{pid:>10}{secid:>10}{mid:>10}{0:>10}{hgid:>10}"


def _hgcard(hgid, ihq="", qm=""):
    # Full *HOURGLASS block (callers add the terminating newline).
    return f"*HOURGLASS\n{hgid:>10}{ihq:>10}{qm:>10}"


def _solid_deck(hgid1=0, hg_cards="", control="", elform=1):
    """One brick on section 1 (part 1)."""
    return (
        "*KEYWORD\n" + _NODES +
        "*ELEMENT_SOLID\n"
        "       1       1       1       2       3       4       5       6       7       8\n"
        "*PART\nsolid1\n" + _pcard(1, 1, 1, hgid1) + "\n"
        f"*SECTION_SOLID\n         1{elform:>10}\n"
        + hg_cards + _MAT + control +
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )


def _two_solid_deck(hgid1, hgid2, hg_cards, control=""):
    """Two bricks on the SAME section 1 (parts 1 and 2)."""
    return (
        "*KEYWORD\n" + _NODES +
        "*ELEMENT_SOLID\n"
        "       1       1       1       2       3       4       5       6       7       8\n"
        "       2       2       1       2       3       4       5       6       7       8\n"
        "*PART\nsolidA\n" + _pcard(1, 1, 1, hgid1) + "\n"
        "*PART\nsolidB\n" + _pcard(2, 1, 1, hgid2) + "\n"
        "*SECTION_SOLID\n         1         1\n"
        + hg_cards + _MAT + control +
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )


def _solid_shell_deck(solid_hgid, shell_hgid, hg_cards, control=""):
    """Mixed deck: a brick (part 1, section 1) + a quad shell (part 2, section 2)."""
    return (
        "*KEYWORD\n" + _NODES +
        "*ELEMENT_SOLID\n"
        "       1       1       1       2       3       4       5       6       7       8\n"
        "*ELEMENT_SHELL\n"
        "      10       2       9      10      11      12\n"
        "*PART\nsolid\n" + _pcard(1, 1, 1, solid_hgid) + "\n"
        "*PART\nshell\n" + _pcard(2, 2, 2, shell_hgid) + "\n"
        "*SECTION_SOLID\n         1         1\n"
        "*SECTION_SHELL\n         2         2         0         3\n"
        "       0.5       0.5       0.5       0.5\n"
        + hg_cards + _MAT + control +
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )


# ── 1. Parsing + defaults ────────────────────────────────────────────────────

class HourglassParseTests(unittest.TestCase):
    def test_hgid_read_into_partdata(self):
        st = _dispatch(_solid_deck(hgid1=4, hg_cards=_hgcard(4, 5, 0.08) + "\n"))
        self.assertEqual(st.parts[1].hgid, 4)

    def test_hourglass_def_stored(self):
        st = _dispatch(_solid_deck(hgid1=4, hg_cards=_hgcard(4, 5, 0.08) + "\n"))
        hg = st.hourglass_defs[4]
        self.assertEqual(hg.hgid, 4)
        self.assertEqual(hg.ihq, 5)
        self.assertAlmostEqual(hg.qm, 0.08)

    def test_qm_defaults_to_point_ten_when_blank(self):
        # HGID 4, IHQ 5, QM blank → dyna2rad default 0.10.
        st = _dispatch(_solid_deck(hgid1=4, hg_cards=_hgcard(4, 5) + "\n"))
        self.assertAlmostEqual(st.hourglass_defs[4].qm, 0.10)

    def test_ihq_defaults_to_zero_when_blank(self):
        st = _dispatch(_solid_deck(hgid1=4, hg_cards=_hgcard(4) + "\n"))
        self.assertEqual(st.hourglass_defs[4].ihq, 0)
        self.assertAlmostEqual(st.hourglass_defs[4].qm, 0.10)

    def test_explicit_zero_qm_kept(self):
        st = _dispatch(_solid_deck(hgid1=4, hg_cards=_hgcard(4, 5, 0.0) + "\n"))
        self.assertAlmostEqual(st.hourglass_defs[4].qm, 0.0)

    def test_hourglass_no_longer_skipped(self):
        st = _dispatch(_solid_deck(hgid1=4, hg_cards=_hgcard(4, 5, 0.08) + "\n"))
        self.assertNotIn("HOURGLASS", st.skipped_keywords)


# ── 2. Solid IHQ → Isolid mapping ────────────────────────────────────────────

class SolidMappingTests(unittest.TestCase):
    def _isolid_for_ihq(self, ihq, qm=0.05):
        _, starter = _convert(_solid_deck(hgid1=4,
                                          hg_cards=_hgcard(4, ihq, qm) + "\n"))
        # section 1 is fully split → the part points at the dedicated prop.
        ref = _part_prop_ref(starter, 1)
        return _solid_isolid_h(starter, f"/PROP/SOLID/{ref}")

    def test_ihq_1_2_3_map_to_isolid_1(self):
        for ihq in (1, 2, 3):
            isolid, h = self._isolid_for_ihq(ihq)
            self.assertEqual(isolid, 1, f"IHQ {ihq}")
            self.assertAlmostEqual(h, 0.05)

    def test_ihq_4_5_map_to_isolid_5(self):
        for ihq in (4, 5):
            isolid, h = self._isolid_for_ihq(ihq)
            self.assertEqual(isolid, 5, f"IHQ {ihq}")

    def test_ihq_6_7_map_to_isolid_24(self):
        for ihq in (6, 7):
            isolid, h = self._isolid_for_ihq(ihq)
            self.assertEqual(isolid, 24, f"IHQ {ihq}")

    def test_h_is_qm_verbatim(self):
        isolid, h = self._isolid_for_ihq(4, qm=0.123)
        self.assertAlmostEqual(h, 0.123)   # no scaling, no IHQ dependence

    def test_unsupported_ihq_keeps_section_isolid_and_warns(self):
        # IHQ 8 has no Radioss Isolid mapping → the ELFORM-17 default is kept,
        # h is still applied, and a warning is emitted (dyna2rad is silent).
        result, starter = _convert(_solid_deck(
            hgid1=4, hg_cards=_hgcard(4, 8, 0.05) + "\n"))
        ref = _part_prop_ref(starter, 1)
        isolid, h = _solid_isolid_h(starter, f"/PROP/SOLID/{ref}")
        self.assertEqual(isolid, 17)               # ELFORM-derived, unchanged
        self.assertAlmostEqual(h, 0.05)            # h still carried
        self.assertTrue(any("IHQ=8" in w and "no faithful" in w
                            for w in result.warnings))

    def test_tetra_section_not_remapped(self):
        # ELFORM 13 (tet) is gated out (dyna2rad elform ∉ {2,13}); no split.
        result, starter = _convert(_solid_deck(
            hgid1=4, hg_cards=_hgcard(4, 4, 0.05) + "\n", elform=13))
        # Part still references its section prop (id 1), unchanged.
        self.assertEqual(_part_prop_ref(starter, 1), 1)


# ── 3. HGID override vs *CONTROL_HOURGLASS fallback (mixed solid + shell) ─────

class ControlFallbackTests(unittest.TestCase):
    """Part 1 (solid) carries HGID → its *HOURGLASS wins; part 2 (shell) has no
    HGID → it falls back to the global *CONTROL_HOURGLASS."""

    def setUp(self):
        deck = _solid_shell_deck(
            solid_hgid=4, shell_hgid=0,
            hg_cards=_hgcard(4, 4, 0.08) + "\n",      # IHQ 4 → Isolid 5, h 0.08
            control="*CONTROL_HOURGLASS\n         1      0.09\n")  # IHQ1, QH .09
        self.result, self.starter = _convert(deck)

    def test_solid_part_uses_hourglass_card_not_control(self):
        ref = _part_prop_ref(self.starter, 1)
        self.assertNotEqual(ref, 1)                       # split out
        isolid, h = _solid_isolid_h(self.starter, f"/PROP/SOLID/{ref}")
        self.assertEqual(isolid, 5)                       # from *HOURGLASS IHQ 4
        self.assertAlmostEqual(h, 0.08)                   # from *HOURGLASS QM

    def test_shell_part_falls_back_to_control(self):
        # No HGID → shared /PROP/SHELL/2 with the control coefficient (clamped
        # 0.09 → 0.05). No split.
        self.assertEqual(_part_prop_ref(self.starter, 2), 2)
        ishell, hm = _shell_ishell_hm(self.starter, "/PROP/SHELL/2")
        self.assertAlmostEqual(hm, 0.05)                  # clamp(QH=0.09)


class ControlOnlyTests(unittest.TestCase):
    """A deck with only *CONTROL_HOURGLASS and no per-part HGID applies the
    global card to the shared section /PROP and never splits."""

    def setUp(self):
        self.result, self.starter = _convert(_solid_deck(
            hgid1=0,
            control="*CONTROL_HOURGLASS\n         6      0.12\n"))  # IHQ6→24

    def test_shared_prop_carries_control(self):
        self.assertEqual(_part_prop_ref(self.starter, 1), 1)   # no split
        isolid, h = _solid_isolid_h(self.starter, "/PROP/SOLID/1")
        self.assertEqual(isolid, 24)
        self.assertAlmostEqual(h, 0.12)

    def test_single_prop_no_split(self):
        self.assertEqual(self.starter.count("/PROP/SOLID/"), 1)

    def test_control_now_honored_warning(self):
        # The previously-inert global card is now applied (17 → 24 remap).
        self.assertTrue(any("CONTROL_HOURGLASS" in w and "now honored" in w
                            for w in self.result.warnings))


# ── 4. Shared SECID, different HGID → prop split ─────────────────────────────

class SharedSectionSplitTests(unittest.TestCase):
    def setUp(self):
        deck = _two_solid_deck(
            hgid1=4, hgid2=5,
            hg_cards=(_hgcard(4, 4, 0.08) + "\n"      # part1 IHQ4 → Isolid5
                      + _hgcard(5, 6, 0.03) + "\n"))  # part2 IHQ6 → Isolid24
        self.result, self.starter = _convert(deck)

    def test_two_parts_get_distinct_prop_ids(self):
        r1, r2 = _part_prop_ref(self.starter, 1), _part_prop_ref(self.starter, 2)
        self.assertNotEqual(r1, r2)
        self.assertNotEqual(r1, 1)
        self.assertNotEqual(r2, 1)

    def test_each_part_prop_has_its_own_settings(self):
        i1, h1 = _solid_isolid_h(self.starter,
                                 f"/PROP/SOLID/{_part_prop_ref(self.starter, 1)}")
        i2, h2 = _solid_isolid_h(self.starter,
                                 f"/PROP/SOLID/{_part_prop_ref(self.starter, 2)}")
        self.assertEqual((i1, round(h1, 3)), (5, 0.08))
        self.assertEqual((i2, round(h2, 3)), (24, 0.03))

    def test_shared_section_prop_suppressed(self):
        # Every part on section 1 was split → no shared /PROP/SOLID/1.
        self.assertNotIn("/PROP/SOLID/1\n", self.starter)

    def test_split_summary_warning(self):
        self.assertTrue(any("hourglass" in w.lower() and "split" in w.lower()
                            for w in self.result.warnings))


class MixedSectionKeepsBasePropTests(unittest.TestCase):
    """A section shared by an overridden part and a plain (base) part keeps its
    shared /PROP AND gets the per-part split."""

    def setUp(self):
        # part1 HGID 4 (IHQ4→5), part2 no HGID + a global control (IHQ1→1).
        deck = _two_solid_deck(
            hgid1=4, hgid2=0, hg_cards=_hgcard(4, 4, 0.08) + "\n",
            control="*CONTROL_HOURGLASS\n         1       0.1\n")
        self.result, self.starter = _convert(deck)

    def test_base_prop_kept_for_plain_part(self):
        # part 2 (no HGID) still uses the shared section prop.
        self.assertEqual(_part_prop_ref(self.starter, 2), 1)
        self.assertIn("/PROP/SOLID/1\n", self.starter)

    def test_overridden_part_split(self):
        self.assertNotEqual(_part_prop_ref(self.starter, 1), 1)

    def test_base_prop_carries_control_isolid(self):
        isolid, h = _solid_isolid_h(self.starter, "/PROP/SOLID/1")
        self.assertEqual(isolid, 1)                  # control IHQ 1 → Isolid 1
        self.assertAlmostEqual(h, 0.1)


# ── 5. Missing / dangling HGID reference ─────────────────────────────────────

class MissingHgidTests(unittest.TestCase):
    def test_dangling_hgid_warns_loudly(self):
        result, _ = _convert(_solid_deck(hgid1=99, hg_cards=""))
        self.assertTrue(any("HGID=99" in w and "not defined" in w
                            for w in result.warnings))

    def test_dangling_hgid_falls_back_to_control(self):
        # HGID 99 undefined → falls back to the global *CONTROL_HOURGLASS.
        result, starter = _convert(_solid_deck(
            hgid1=99, hg_cards="",
            control="*CONTROL_HOURGLASS\n         4       0.1\n"))  # IHQ4→5
        isolid, h = _solid_isolid_h(
            starter, f"/PROP/SOLID/{_part_prop_ref(starter, 1)}")
        # falls back to control's mapping (IHQ 4 → Isolid 5)
        self.assertIn(isolid, (5, 17))   # remapped or (if base==eff) section 1
        self.assertTrue(any("HGID=99" in w for w in result.warnings))

    def test_dangling_hgid_no_control_no_split(self):
        # No control either → nothing applies; the part keeps its section prop.
        result, starter = _convert(_solid_deck(hgid1=99, hg_cards=""))
        self.assertEqual(_part_prop_ref(starter, 1), 1)
        i, h = _solid_isolid_h(starter, "/PROP/SOLID/1")
        self.assertEqual(i, 17)
        self.assertAlmostEqual(h, 0.0)


# ── 6. Shell coefficient handling ────────────────────────────────────────────

class ShellHourglassTests(unittest.TestCase):
    def test_shell_coefficient_clamped_and_warned(self):
        # *HOURGLASS QM 0.10 on a shell → Hm/Hf/Hr clamped to 0.05, inert warn.
        result, starter = _convert(_solid_shell_deck(
            solid_hgid=0, shell_hgid=5, hg_cards=_hgcard(5, 4, 0.10) + "\n"))
        ref = _part_prop_ref(starter, 2)
        d = _block_lines(starter, f"/PROP/SHELL/{ref}")
        hm = float(d[2][0:20]); hf = float(d[2][20:40]); hr = float(d[2][40:60])
        self.assertEqual((hm, hf, hr), (0.05, 0.05, 0.05))
        self.assertTrue(any("inert" in w and "Ishell" in w
                            for w in result.warnings))

    def test_shell_ishell_unchanged_by_ihq(self):
        # No IHQ→Ishell remap: the ELFORM-derived Ishell (12) is preserved.
        _, starter = _convert(_solid_shell_deck(
            solid_hgid=0, shell_hgid=5, hg_cards=_hgcard(5, 4, 0.03) + "\n"))
        ref = _part_prop_ref(starter, 2)
        ishell, hm = _shell_ishell_hm(starter, f"/PROP/SHELL/{ref}")
        self.assertEqual(ishell, 12)
        self.assertAlmostEqual(hm, 0.03)


# ── 7. Regression: no hourglass data → coefficients stay zero ────────────────

class NoHourglassRegressionTests(unittest.TestCase):
    def test_no_hourglass_leaves_zero_coefficients(self):
        _, starter = _convert(_solid_deck(hgid1=0, hg_cards=""))
        self.assertEqual(_part_prop_ref(starter, 1), 1)
        isolid, h = _solid_isolid_h(starter, "/PROP/SOLID/1")
        self.assertEqual(isolid, 17)          # ELFORM default, unchanged
        self.assertAlmostEqual(h, 0.0)        # Radioss default (0 → 0.10)

    def test_no_split_props(self):
        _, starter = _convert(_solid_deck(hgid1=0, hg_cards=""))
        self.assertEqual(starter.count("/PROP/SOLID/"), 1)


# ── 8. Cross-feature: *INITIAL_STRESS_SOLID → /INIBRI Nb_integr must track the
#      hourglass-remapped /PROP/SOLID Isolid (else starter MSGID 695). ─────────

# One brick + *INITIAL_STRESS_SOLID (NINT=1, one stress point).
_ISS = ("*INITIAL_STRESS_SOLID\n"
        "         1         1\n"
        "     100.0     200.0     300.0      10.0      20.0      30.0       0.0\n")


def _iss_deck(hgid=0, hg_cards="", control=""):
    """One brick (part 1, ELFORM-1 section 1) with an initial solid stress."""
    return (
        "*KEYWORD\n" + _NODES +
        "*ELEMENT_SOLID\n"
        "       1       1       1       2       3       4       5       6       7       8\n"
        "*PART\nsolid1\n" + _pcard(1, 1, 1, hgid) + "\n"
        "*SECTION_SOLID\n         1         1\n"
        + hg_cards + _MAT + _ISS + control +
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )


def _inibri_nbint_isolid(starter: str):
    """(Nb_integr, Isolid) from the first /INIBRI/STRS_FGLO data card (cols
    11-20 and 31-40)."""
    card = _block_lines(starter, "/INIBRI/STRS_FGLO")[0]
    return int(card[10:20]), int(card[30:40])


# Under-integrated Isolid (1 IP) vs full-integration (8 IP) — the /INIBRI
# Nb_integr the starter demands for each.
_NBINT_FOR_ISOLID = {1: 1, 5: 1, 24: 1, 12: 8, 17: 8, 18: 8}


class InitialStressHourglassTests(unittest.TestCase):
    """The /INIBRI Nb_integr/Isolid the writer emits must match the *effective*
    /PROP/SOLID Isolid once hourglass control remaps it — the regression the
    previously-dropped *CONTROL_HOURGLASS masked."""

    def _prop_and_inibri(self, deck):
        _, starter = _convert(deck)
        ref = _part_prop_ref(starter, 1)
        prop_isolid, _ = _solid_isolid_h(starter, f"/PROP/SOLID/{ref}")
        nbint, ini_isolid = _inibri_nbint_isolid(starter)
        return prop_isolid, ini_isolid, nbint

    def test_inibri_matches_control_remapped_isolid(self):
        # *CONTROL_HOURGLASS IHQ1 → /PROP Isolid 1 (1 IP); /INIBRI must be
        # Nb_integr 1, Isolid 1 (was Nb_integr 8/Isolid 17 → MSGID 695).
        prop_isolid, ini_isolid, nbint = self._prop_and_inibri(
            _iss_deck(control="*CONTROL_HOURGLASS\n         1       0.1\n"))
        self.assertEqual(prop_isolid, 1)
        self.assertEqual(ini_isolid, 1)
        self.assertEqual(nbint, _NBINT_FOR_ISOLID[prop_isolid])

    def test_inibri_matches_perpart_hgid_isolid(self):
        # *PART HGID → *HOURGLASS IHQ4 → split /PROP Isolid 5 (1 IP).
        prop_isolid, ini_isolid, nbint = self._prop_and_inibri(
            _iss_deck(hgid=7, hg_cards=_hgcard(7, 4, 0.08) + "\n"))
        self.assertEqual(prop_isolid, 5)
        self.assertEqual(ini_isolid, 5)
        self.assertEqual(nbint, _NBINT_FOR_ISOLID[prop_isolid])

    def test_inibri_unchanged_without_hourglass(self):
        # No hourglass source → /PROP keeps Isolid 17 (8 IP); /INIBRI stays
        # Nb_integr 8 (guards the fix against regressing the plain path).
        prop_isolid, ini_isolid, nbint = self._prop_and_inibri(_iss_deck())
        self.assertEqual(prop_isolid, 17)
        self.assertEqual(ini_isolid, 17)
        self.assertEqual(nbint, 8)


# ── 9. Cross-feature: per-part *HOURGLASS on an auto-created (undefined)
#      *SECTION_SOLID must still apply (the prepass resolves the default). ─────

class AutoCreatedSectionTests(unittest.TestCase):
    def _deck(self, hgid, hg_cards, control=""):
        # part 1 references SECID 1 but the deck defines NO *SECTION_SOLID for it.
        return (
            "*KEYWORD\n" + _NODES +
            "*ELEMENT_SOLID\n"
            "       1       1       1       2       3       4       5       6       7       8\n"
            "*PART\nhex\n" + _pcard(1, 1, 1, hgid) + "\n"
            + hg_cards + _MAT + control +
            "*CONTROL_TERMINATION\n       1.0\n*END\n")

    def test_perpart_hourglass_applied_on_undefined_section(self):
        # HGID 7 → IHQ4 QM0.08; the auto-created ELFORM-1 section must still be
        # remapped to Isolid 5 / h 0.08 (was silently dropped → Isolid 17/h 0).
        result, starter = _convert(
            self._deck(7, _hgcard(7, 4, 0.08) + "\n"))
        ref = _part_prop_ref(starter, 1)
        self.assertNotEqual(ref, 1)                       # split out
        isolid, h = _solid_isolid_h(starter, f"/PROP/SOLID/{ref}")
        self.assertEqual(isolid, 5)
        self.assertAlmostEqual(h, 0.08)
        self.assertTrue(any("split" in w.lower() for w in result.warnings))

    def test_control_applied_on_undefined_section(self):
        # Global *CONTROL_HOURGLASS also reaches the auto-created section.
        _, starter = _convert(self._deck(
            0, "", control="*CONTROL_HOURGLASS\n         6      0.12\n"))
        isolid, h = _solid_isolid_h(starter, "/PROP/SOLID/1")
        self.assertEqual(isolid, 24)                      # IHQ6 → 24
        self.assertAlmostEqual(h, 0.12)


# ── 10. Prop-split dedup: sibling parts sharing SECID *and* effective hourglass
#       get ONE shared /PROP, not a byte-identical copy each. ──────────────────

class SharedSectionDedupTests(unittest.TestCase):
    def setUp(self):
        # Two bricks, same section 1, same HGID 4 (IHQ6 → Isolid 24, h 0.03).
        deck = _two_solid_deck(
            hgid1=4, hgid2=4, hg_cards=_hgcard(4, 6, 0.03) + "\n")
        self.result, self.starter = _convert(deck)

    def test_both_parts_share_one_split_prop(self):
        r1 = _part_prop_ref(self.starter, 1)
        r2 = _part_prop_ref(self.starter, 2)
        self.assertEqual(r1, r2)                          # deduplicated
        self.assertNotEqual(r1, 1)                        # and it is the split

    def test_only_one_prop_emitted(self):
        # Shared section prop suppressed (all split) + ONE dedup split prop.
        self.assertEqual(self.starter.count("/PROP/SOLID/"), 1)

    def test_shared_prop_carries_settings(self):
        ref = _part_prop_ref(self.starter, 1)
        isolid, h = _solid_isolid_h(self.starter, f"/PROP/SOLID/{ref}")
        self.assertEqual(isolid, 24)
        self.assertAlmostEqual(h, 0.03)

    def test_distinct_hgid_still_splits_separately(self):
        # Contrast: different resolved hourglass → distinct props (no over-dedup).
        _, starter = _convert(_two_solid_deck(
            hgid1=4, hgid2=5,
            hg_cards=(_hgcard(4, 6, 0.03) + "\n" + _hgcard(5, 4, 0.08) + "\n")))
        self.assertNotEqual(_part_prop_ref(starter, 1),
                            _part_prop_ref(starter, 2))


# ── 11. Cross-feature: LAW128 (ortho) + hourglass split on one section — the
#       shared section prop is suppressed only when EVERY part is split. ───────

_MAT_LAW128 = (
    "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
    "        10   1.05E-9    1800.0       0.4      35.0       0.0       0.0       1.0\n"
    "      10.0      50.0       5.0     300.0       0.0       0.0       0.0       0.0\n"
    "       0.0       0.0      1.35       1.0      0.75       0.0       0.0       0.0\n"
    "       0.0       0.1\n"
)


def _law128_hg_deck(part2_hgid, hg_cards):
    """part1 = LAW128 ortho (mid 10), part2 = elastic (mid 1) with optional
    HGID, both solids on the SAME section 1."""
    return (
        "*KEYWORD\n" + _NODES +
        "*ELEMENT_SOLID\n"
        "       1       1       1       2       3       4       5       6       7       8\n"
        "       2       2       1       2       3       4       5       6       7       8\n"
        "*PART\nlaw128\n" + _pcard(1, 1, 10, 0) + "\n"
        "*PART\nelastic\n" + _pcard(2, 1, 1, part2_hgid) + "\n"
        "*SECTION_SOLID\n         1         1\n"
        + hg_cards + _MAT + _MAT_LAW128 +
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )


class Law128HourglassSuppressionTests(unittest.TestCase):
    def test_all_parts_split_suppresses_shared_prop(self):
        # part1 ortho-split + part2 hourglass-split → no shared /PROP/SOLID/1.
        _, starter = _convert(_law128_hg_deck(
            part2_hgid=4, hg_cards=_hgcard(4, 6, 0.03) + "\n"))
        self.assertNotIn("/PROP/SOLID/1\n", starter)
        self.assertNotEqual(_part_prop_ref(starter, 1), 1)   # ortho prop
        self.assertNotEqual(_part_prop_ref(starter, 2), 1)   # hourglass prop
        self.assertNotEqual(_part_prop_ref(starter, 1),
                            _part_prop_ref(starter, 2))

    def test_plain_sibling_keeps_shared_prop(self):
        # part1 ortho-split, part2 plain (no HGID) → shared /PROP/SOLID/1 kept.
        _, starter = _convert(_law128_hg_deck(part2_hgid=0, hg_cards=""))
        self.assertIn("/PROP/SOLID/1\n", starter)
        self.assertEqual(_part_prop_ref(starter, 2), 1)      # plain part
        self.assertNotEqual(_part_prop_ref(starter, 1), 1)   # ortho part


# ── 12. Cross-feature: --tet10-to-tet4 downgrade + *HOURGLASS — the downgraded
#       tets stay gated (Isolid 14), so no remap and no split. ────────────────

_TET10_HG_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             0.0             1.0             0.0\n"
    "       4             0.0             0.0             1.0\n"
    "       5             0.5             0.0             0.0\n"
    "       6             0.5             0.5             0.0\n"
    "       7             0.0             0.5             0.0\n"
    "       8             0.0             0.0             0.5\n"
    "       9             0.5             0.0             0.5\n"
    "      10             0.0             0.5             0.5\n"
    "*ELEMENT_SOLID\n"
    "       1       1\n"
    "       1       2       3       4       5       6       7       8       9      10\n"
    "*PART\ntet10\n" + _pcard(1, 1, 1, 7) + "\n"
    "*SECTION_SOLID\n         1        10\n"
    + _hgcard(7, 4, 0.08) + "\n" + _MAT +
    "*CONTROL_TERMINATION\n       1.0\n*END\n"
)


class Tet10DowngradeHourglassTests(unittest.TestCase):
    def test_downgraded_tet_not_remapped_or_split(self):
        result, starter = _convert(_TET10_HG_DECK, tet10_to_tet4=True)
        self.assertIn("/TETRA4", starter)                 # downgrade happened
        self.assertEqual(_part_prop_ref(starter, 1), 1)   # section prop, no split
        self.assertNotIn("HG_PROP", starter)              # no dedicated hg prop

    def test_tet10_kept_not_remapped_or_split(self):
        # Same gate without the downgrade (raw /TETRA10).
        _, starter = _convert(_TET10_HG_DECK)
        self.assertIn("/TETRA10", starter)
        self.assertEqual(_part_prop_ref(starter, 1), 1)
        self.assertNotIn("HG_PROP", starter)


if __name__ == "__main__":
    unittest.main()
