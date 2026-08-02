"""Tests for the ``/PROP/BEAM`` (IGTYP 3) MATERIAL compatibility check
(``writer/mesh.py::_warn_beam_type3_material`` and ``_target_mat_law``).

``_make_properties`` writes a ``/PROP/BEAM`` for every ``*SECTION_BEAM``
whatever material the parts using it carry, and the OpenRadioss starter accepts
that for only five laws. The gate is on the MATERIAL: every law declares a
``PROP_BEAM`` class through ``INIT_MAT_KEYWORD`` — 1 BEAM_CLASSIC (TYPE3 only),
2 BEAM_INTEGRATED (TYPE18 only), 3 BEAM_ALL (``init_mat_keyword.F:251-258``) —
and IGTYP 3 requires 1 or 3 (``check_mat_elem_prop_compatibility.F:379-381``).
Grepping every ``INIT_MAT_KEYWORD`` call under ``starter/source/materials/``
gives 10 call sites and the complete list: LAW1 is BEAM_CLASSIC, LAW0/2/13/44
are BEAM_ALL, LAW34/36/71 are BEAM_INTEGRATED, everything else keeps the
``PROP_BEAM = 0`` default from ``ini_mat_elem.F:89``.

``*MAT_PIECEWISE_LINEAR_PLASTICITY`` — the most common LS-DYNA beam material —
converts to ``/MAT/LAW36``, so the likeliest beam deck of all was being turned
into an ERROR TERMINATION with no warning whatsoever.

Every claim below was MEASURED on ``starter_win64`` (nt=6) with the decks in
this module, one ``*SECTION_BEAM`` ELFORM=2 and two ``*ELEMENT_BEAM`` apiece:

  *MAT_ELASTIC (LAW1)             NORMAL TERMINATION, 0 ERROR(S) 0 WARNING(S)
  *MAT_JOHNSON_COOK (LAW2)        0 ERROR(S) (only unrelated warnings)
  *MAT_PLASTIC_KINEMATIC (LAW44)  NORMAL TERMINATION, 0 ERROR(S) 0 WARNING(S)
  *MAT_PIECEWISE_LIN… (LAW36)     3 ERROR(S): ERROR 3047 + one ERROR 745 per elem
  *MAT_BLATZ-KO_RUBBER (LAW42)    1 ERROR(S): ERROR 3046

so the two error ids the warning names are the ones the user really reads. They
are not interchangeable: a ``PROP_BEAM == 0`` law fails the ELEMENT test one
step earlier (3046, MATERIAL/ELEMENT — the property never enters it) while only
the BEAM_INTEGRATED laws reach the property test and raise 3047, joined by the
legacy per-element ERROR 745 from ``initia.F:2806-2817``.

The check is WARN-ONLY. Auto-promotion to ``/PROP/TYPE18`` is not
information-preserving (``*SECTION_BEAM`` ELFORM=2 states four independent
resultants while TYPE18 *defines* ``Ixx = Iyy + Izz``, so the deck's J would be
silently overwritten), it would rescue only the LAW34/36/71 third of the failing
cases, and the TYPE18 machinery is being built on ``feat/integration-beam``. See
the ``_warn_beam_type3_material`` docstring for the full argument.

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_element_free_parts.py, tests/test_composites.py and
tests/test_connectors.py).
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState
from k2rad.writer import build_starter
from k2rad.writer.mesh import _TYPE3_BEAM_LAWS, _target_mat_law


# The marker the check's warning carries.
MARKER = "/PROP/BEAM (TYPE3) material compatibility"


def _convert(deck: str):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _state_and_starter(deck: str):
    """Parse + dispatch + build_starter, returning the FINAL state (all writer
    prepasses run, so the conditional routings are resolved) and the text."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    starter = build_starter(state)
    tmp.cleanup()
    return state, starter


def _prop_block(starter: str, header: str):
    """The lines of the block starting with *header*, ruler line excluded."""
    out, cur = [], None
    for ln in starter.splitlines():
        if ln == header:
            cur = out
        elif cur is not None:
            if ln.startswith("#---1----"):
                break
            cur.append(ln)
    assert out, f"{header!r} not found"
    return [header] + out


def _hits(result):
    return [w for w in result.warnings if MARKER in w]


def _hit(result):
    """The single compatibility warning (fails the test if not unique)."""
    found = _hits(result)
    assert len(found) == 1, f"expected exactly one, got {len(found)}: {found}"
    return found[0]


# ── Deck pieces ──────────────────────────────────────────────────────────────
#
# Node 4 is the beam orientation node; part 2 owns beams 11 and 12 on
# *SECTION_BEAM 2 (ELFORM 2, A/Iss/Itt/J stated numerically).

NODES = (
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2            10.0             0.0             0.0\n"
    "       3            20.0             0.0             0.0\n"
    "       4             0.0            10.0             0.0\n"
    "       5             0.0             0.0            10.0\n"
    "       6            10.0             0.0            10.0\n"
    "       7            10.0            10.0            10.0\n"
    "       8             0.0            10.0            10.0\n")

BEAM_PART = ("*PART\nbar\n"
             "         2         2         1\n"
             "*SECTION_BEAM\n"
             "         2         2\n"
             "     100.0     833.0     833.0    1400.0\n")

BEAMS = ("*ELEMENT_BEAM\n"
         "      11       2       1       2       4\n"
         "      12       2       2       3       4\n")

END = "*CONTROL_TERMINATION\n      0.01\n*END\n"

# Materials, all under mid 1.
MAT_024 = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
           "         1  7.85E-9  210000.0       0.3     300.0\n"
           "       0.0       0.0\n")
MAT_003 = ("*MAT_PLASTIC_KINEMATIC\n"
           "         1  7.85E-9  210000.0       0.3     300.0    1000.0"
           "       1.0\n")
MAT_001 = "*MAT_ELASTIC\n         1  7.85E-9  210000.0       0.3\n"
MAT_015 = ("*MAT_JOHNSON_COOK\n"
           "         1  7.85E-9   80000.0  210000.0       0.3\n"
           "     300.0     500.0      0.26      0.01       1.0\n"
           "    1800.0       0.0       0.0       1.0\n"
           "       0.0       0.0       0.0       0.0       0.0\n")
MAT_009 = "*MAT_NULL\n         1  7.85E-9\n"
MAT_007 = "*MAT_BLATZ-KO_RUBBER\n         1  1.00E-9    1000.0\n"
MAT_018 = ("*MAT_POWER_LAW_PLASTICITY\n"
           "         1  7.85E-9  210000.0       0.3     600.0      0.25\n")


def _beam_deck(mat: str, extra: str = "") -> str:
    return "*KEYWORD\n" + NODES + BEAM_PART + mat + BEAMS + extra + END


# ─────────────────────────────────────────────────────────────────────────────
# A. The whitelist itself
# ─────────────────────────────────────────────────────────────────────────────

class WhitelistTests(unittest.TestCase):
    """``_TYPE3_BEAM_LAWS`` is a transcription of the Fortran, so pin it."""

    def test_whitelist_is_exactly_the_five_fortran_laws(self):
        # BEAM_CLASSIC (PROP_BEAM 1): LAW1. BEAM_ALL (PROP_BEAM 3): LAW0,
        # LAW2, LAW13, LAW44. Nothing else declares a beam keyword at all.
        self.assertEqual(_TYPE3_BEAM_LAWS, frozenset({0, 1, 2, 13, 44}))

    def test_the_integrated_beam_laws_are_not_on_it(self):
        # LAW34/36/71 are BEAM_INTEGRATED — /PROP/TYPE18 only.
        for law in (34, 36, 71):
            with self.subTest(law=law):
                self.assertNotIn(law, _TYPE3_BEAM_LAWS)


# ─────────────────────────────────────────────────────────────────────────────
# B. The warning fires, and names part / mid / law
# ─────────────────────────────────────────────────────────────────────────────

class MatPiecewiseLinearBeamTests(unittest.TestCase):
    """The headline case: *MAT_024 on a beam is starter ERROR 3047 + 745."""

    def test_mat024_beam_draws_a_warning_naming_part_mid_and_law(self):
        result, _ = _convert(_beam_deck(MAT_024))
        hit = _hit(result)
        self.assertIn("part 2", hit)
        self.assertIn("mid 1", hit)
        self.assertIn("/MAT/LAW36", hit)

    def test_it_names_the_error_ids_the_starter_really_raises(self):
        """Measured: ERROR 3047 once plus ERROR 745 per beam element."""
        hit = _hit(_convert(_beam_deck(MAT_024))[0])
        self.assertIn("BEAM_INTEGRATED", hit)
        self.assertIn("ERROR 3047", hit)
        self.assertIn("ERROR 745", hit)
        self.assertNotIn("ERROR 3046", hit)

    def test_the_prop_beam_is_still_emitted_unchanged(self):
        """Warn-only: the check adds no card, removes none and edits none. The
        rejected LAW36 deck and the starter-clean LAW44 one carry the SAME
        /PROP/BEAM, line for line — the diagnosis lives entirely in the
        warning list."""
        _, warned = _convert(_beam_deck(MAT_024))
        _, clean = _convert(_beam_deck(MAT_003))
        self.assertIn("/MAT/LAW36/1", warned)
        self.assertIn("/MAT/LAW44/1", clean)
        self.assertEqual(_prop_block(warned, "/PROP/BEAM/2"),
                         _prop_block(clean, "/PROP/BEAM/2"))
        self.assertEqual(_prop_block(warned, "/PROP/BEAM/2")[0],
                         "/PROP/BEAM/2")

    def test_power_law_plasticity_lands_on_the_same_law(self):
        """The gate follows k2rad's ROUTING, not the LS-DYNA material number:
        *MAT_018 is a different keyword that also becomes /MAT/LAW36."""
        hit = _hit(_convert(_beam_deck(MAT_018))[0])
        self.assertIn("/MAT/LAW36", hit)
        self.assertIn("ERROR 3047", hit)


class PropBeamZeroLawTests(unittest.TestCase):
    """A law with no beam keyword at all fails one step EARLIER, as 3046."""

    def test_rubber_beam_is_reported_under_error_3046(self):
        hit = _hit(_convert(_beam_deck(MAT_007))[0])
        self.assertIn("part 2", hit)
        self.assertIn("/MAT/LAW42", hit)
        self.assertIn("no beam keyword at all", hit)
        self.assertIn("ERROR 3046", hit)
        self.assertNotIn("ERROR 3047", hit)


# ─────────────────────────────────────────────────────────────────────────────
# C. Silence where the starter is happy
# ─────────────────────────────────────────────────────────────────────────────

class CompatibleMaterialTests(unittest.TestCase):
    """Each of these ran the starter to 0 ERROR(S); none may be warned about."""

    def test_law44_law1_law2_and_law0_beams_stay_silent(self):
        for name, mat in (("*MAT_PLASTIC_KINEMATIC → LAW44", MAT_003),
                          ("*MAT_ELASTIC → LAW1", MAT_001),
                          ("*MAT_JOHNSON_COOK → LAW2", MAT_015),
                          ("*MAT_NULL → /MAT/VOID LAW0", MAT_009)):
            with self.subTest(mat=name):
                result, _ = _convert(_beam_deck(mat))
                self.assertEqual(_hits(result), [])


class ScopeTests(unittest.TestCase):
    """What the check must NOT reach."""

    def test_a_shell_part_on_law36_is_not_warned(self):
        """LAW36 is a perfectly good shell material — only beams are gated."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART\nplate\n         3         3         1\n"
                  "*SECTION_SHELL\n         3         2\n"
                  "       1.0       1.0       1.0       1.0\n"
                + MAT_024
                + "*ELEMENT_SHELL\n"
                  "       1       3       5       6       7       8\n"
                + END)
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertEqual(_hits(result), [])

    def test_an_element_free_beam_part_is_not_warned(self):
        """The starter's compatibility loop runs per element GROUP, so a part
        with no elements is never tested — the same reason the composite
        element-free warning stopped predicting ERROR 3047."""
        deck = ("*KEYWORD\n" + NODES + BEAM_PART + MAT_024 + END)
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertEqual(_hits(result), [])

    def test_a_spotweld_beam_part_is_not_warned(self):
        """*MAT_SPOTWELD beams become /SPRING on a /PROP/TYPE13 connector, so
        no /PROP/BEAM exists for them to be incompatible with."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART\nweld\n         2         2         9\n"
                  "*SECTION_BEAM\n         2         9\n"
                  "       4.0       1.2\n"
                  "*MAT_SPOTWELD\n"
                  "         9    7.8E-9  210000.0       0.3     300.0\n"
                + BEAMS + END)
        result, starter = _convert(deck)
        self.assertIn("/PROP/TYPE13/", starter)
        self.assertNotIn("/PROP/BEAM/", starter)
        self.assertEqual(_hits(result), [])


# ─────────────────────────────────────────────────────────────────────────────
# D. Grouping and message shape
# ─────────────────────────────────────────────────────────────────────────────

class ReportShapeTests(unittest.TestCase):

    def test_parts_sharing_a_material_are_grouped_into_one_entry(self):
        deck = ("*KEYWORD\n" + NODES + BEAM_PART
                + "*PART\nbar2\n         3         2         1\n"
                + MAT_024
                + "*ELEMENT_BEAM\n"
                  "      11       2       1       2       4\n"
                  "      13       3       2       3       4\n"
                + END)
        hit = _hit(_convert(deck)[0])
        self.assertIn("parts 2, 3 on mid 1 (/MAT/LAW36", hit)

    def test_two_materials_give_two_entries_in_one_warning(self):
        deck = ("*KEYWORD\n" + NODES + BEAM_PART
                + "*PART\nrubberbar\n         3         2         4\n"
                + MAT_024
                + "*MAT_BLATZ-KO_RUBBER\n         4  1.00E-9    1000.0\n"
                + "*ELEMENT_BEAM\n"
                  "      11       2       1       2       4\n"
                  "      13       3       2       3       4\n"
                + END)
        hit = _hit(_convert(deck)[0])     # exactly ONE warning, two entries
        self.assertIn("part 2 on mid 1 (/MAT/LAW36", hit)
        self.assertIn("part 3 on mid 4 (/MAT/LAW42", hit)
        self.assertIn("; ", hit)

    def test_the_advice_names_both_remedies_and_cites_the_starter(self):
        hit = _hit(_convert(_beam_deck(MAT_024))[0])
        # (a) the integrated-beam route, worded so it stays true whether or not
        # this k2rad converts *INTEGRATION_BEAM into a /PROP/TYPE18.
        self.assertIn("*INTEGRATION_BEAM", hit)
        self.assertIn("/PROP/TYPE18", hit)
        self.assertIn("QR/IRID", hit)
        self.assertIn("NEGATIVE of the rule id", hit)
        self.assertIn("disappears by itself once the rule converts", hit)
        # (b) the material route.
        self.assertIn("*MAT_PLASTIC_KINEMATIC", hit)
        self.assertIn("/MAT/LAW44", hit)
        self.assertIn("*MAT_ELASTIC", hit)
        # The whitelist and its citation, so the claim is checkable.
        self.assertIn("PROP_BEAM 1 or 3", hit)
        self.assertIn("check_mat_elem_prop_compatibility.F:379-381", hit)
        # And the trap that makes this non-obvious.
        self.assertIn("*MAT_POWER_LAW_PLASTICITY both land on LAW36", hit)


# ─────────────────────────────────────────────────────────────────────────────
# E. _target_mat_law, checked against what the writer actually emits
# ─────────────────────────────────────────────────────────────────────────────

class TargetLawTests(unittest.TestCase):
    """The map is only worth anything if it agrees with the emitters, so every
    case is verified against the /MAT header in the produced deck rather than
    against a second copy of the table.

    ``/MAT/ELAST``, ``/MAT/VOID`` and ``/MAT/HYD_VISC`` are the three keyword
    aliases k2rad writes instead of the numeric form.
    """

    ALIAS = {1: "/MAT/ELAST", 0: "/MAT/VOID", 6: "/MAT/HYD_VISC"}

    CASES = [
        ("*MAT_ELASTIC", MAT_001, 1),
        ("*MAT_PIECEWISE_LINEAR_PLASTICITY", MAT_024, 36),
        ("*MAT_PLASTIC_KINEMATIC", MAT_003, 44),
        ("*MAT_JOHNSON_COOK (no EOS)", MAT_015, 2),
        ("*MAT_NULL (bare)", MAT_009, 0),
        ("*MAT_POWER_LAW_PLASTICITY", MAT_018, 36),
        ("*MAT_BLATZ-KO_RUBBER", MAT_007, 42),
        ("*MAT_ANISOTROPIC_VISCOPLASTIC",
         "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
         "         1  7.85E-9  210000.0       0.3     300.0\n"
         "       0.0       0.0       0.0       0.0\n"
         "       1.0       1.0       1.0       1.0       1.0       1.0\n", 128),
        ("*MAT_CRUSHABLE_FOAM",
         "*MAT_CRUSHABLE_FOAM\n"
         "         1  1.00E-9    1000.0       0.0        90\n", 50),
        ("*MAT_HONEYCOMB",
         "*MAT_HONEYCOMB\n"
         "         1  1.00E-9    1000.0       0.0      10.0       0.9\n"
         "        91        91        91        91        91        91\n", 28),
        ("*MAT_SAMP-1",
         "*MAT_SAMP-1\n"
         "         1  1.00E-9    1000.0       0.4\n"
         "         0        90         0         0\n", 76),
    ]

    def test_every_family_resolves_to_the_law_the_writer_emits(self):
        # One shared load curve so the tabulated foams have something to point
        # at; it is inert for the families that do not read it.
        curve = ("*DEFINE_CURVE\n"
                 "        90\n"
                 "                 0.0                 0.0\n"
                 "                 1.0              1000.0\n"
                 "*DEFINE_CURVE\n"
                 "        91\n"
                 "                 0.0                 0.0\n"
                 "                 1.0              1000.0\n")
        for name, mat, law in self.CASES:
            with self.subTest(mat=name):
                state, starter = _state_and_starter(
                    _beam_deck(mat, extra=curve))
                self.assertEqual(_target_mat_law(state, 1), law)
                self.assertIn(self.ALIAS.get(law, f"/MAT/LAW{law}") + "/1",
                              starter)

    def test_johnson_cook_switches_to_law4_when_an_eos_is_attached(self):
        """The one routing that depends on something outside the *MAT card."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART\nbrick\n         3         3         1         1\n"
                  "*SECTION_SOLID\n         3         1\n"
                + MAT_015
                + "*EOS_GRUNEISEN\n"
                  "         1    5000.0      1.49       0.0       0.0      2.0\n"
                + "*ELEMENT_SOLID\n"
                  "       1       3\n"
                  "       1       2       3       4       5       6       7"
                  "       8\n"
                + END)
        state, starter = _state_and_starter(deck)
        self.assertEqual(_target_mat_law(state, 1), 4)
        self.assertIn("/MAT/LAW4/1", starter)

    def test_an_unknown_material_id_maps_to_none(self):
        state, _ = _state_and_starter(_beam_deck(MAT_024))
        self.assertIsNone(_target_mat_law(state, 999))

    def test_a_part_on_an_unemitted_material_is_not_warned(self):
        """None means "k2rad writes no /MAT for this id" — a different, already
        reported problem. The gate must not invent a law for it."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART\nbar\n         2         2         7\n"
                  "*SECTION_BEAM\n         2         2\n"
                  "     100.0     833.0     833.0    1400.0\n"
                + BEAMS + END)
        result, _ = _convert(deck)
        self.assertEqual(_hits(result), [])


if __name__ == "__main__":
    unittest.main()
