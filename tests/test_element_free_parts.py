"""Tests for the element-free ``*PART`` placeholder property
(``writer/mesh.py::_element_free_part_ids``).

k2rad emits a ``/PART`` for every ``*PART`` record, and points it at
``composite/ortho/hourglass prop id`` or, failing those, at the part's SECID.
The auto-created "missing section" placeholders that back that last case are
derived from the ELEMENTS naming a secid, so a ``*PART`` that owns no elements
is never reached by any of them: its ``/PART`` card ends up referencing a
property id nothing emits, and the starter kills the run outright —

    ERROR ID :    178
    ** ERROR IN PART DEFINITION (PROPERTY)
       -- PART ID: 88
       PROPERTY ID=88 DOES NOT EXIST

An element-free part is not a pathology. ``*INTEGRATION_SHELL``'s ``PID_i``
"may reference a part with no elements" (Vol I R17 p.29-17) purely to carry a
layer MATERIAL, and an element-free ``*MAT_RIGID`` part with
``*CONSTRAINED_EXTRA_NODES`` forms a working ``/RBODY`` out of nodes it borrows
from other parts. So the part is kept and given a placeholder property rather
than dropped — dropping it only moves the breakage, because nothing in k2rad
filters set / group / surface members against the parts that were emitted
(``contacts.py`` builds an all-parts ``/SURF/PART/EXT`` from
``state.parts.keys()``, ``loads.py`` the same for a ``/GRNOD/PART`` gravity
scope). Hand-stripping the ``/PART`` from a converted ``*LOAD_BODY_PARTS`` deck
trades ERROR 178 for starter WARNING 194, "REFERENCE TO NONEXISTENT PART
ID=88" — quieter, still broken.

The native reader is no help here: dyna2rad writes the ``/PART`` with
``prop_ID = 0`` (``convertprops.cxx:110-150``) and its own starter then raises
the SAME ERROR 178, reporting ``PROPERTY ID=0`` (``hm_read_part.F:203-210``).

Assertions are COLUMN-EXACT against the emitted cards. The suite's closing
invariant is the one the starter actually enforces: every ``/PART``'s property
column must name a ``/PROP`` the deck emits.

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_orphan_elements.py, tests/test_composites.py and
tests/test_joints.py).
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                                    # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"

# The marker the element-free warning carries.
MARKER = "hold no elements and reference no *SECTION"


# ─────────────────────────────────────────────────────────────────────────────
# Deck fragments
#
# Part 7 is the one MESHED part (nodes 1-4, one shell, *SECTION_SHELL 7).
# Everything appended after it is some flavour of element-free part.
# ─────────────────────────────────────────────────────────────────────────────

HEAD = """\
*KEYWORD
*TITLE
element-free part test deck
*CONTROL_TERMINATION
      0.01
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
*ELEMENT_SHELL
       1       7       1       2       3       4
*PART
real plate
         7         7         1
*SECTION_SHELL
         7         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
"""

# The repro: SECID 0, no elements, no *SECTION anywhere.
FREE_PART = """\
*PART
material carrier, no elements
        88         0         1
"""

FREE_PART_99 = """\
*PART
second carrier
        99         0         1
"""

# Two element-free parts naming the SAME undefined section: one placeholder
# has to serve both, or the deck gains a duplicate property id.
TWO_FREE_PARTS_ONE_SECID = """\
*PART
carrier a
        88         5         1
*PART
carrier b
        99         5         1
"""

# Same part, but its SECID points at the MESHED part's section.
FREE_PART_SHARED_SECTION = """\
*PART
carrier on section 7
        88         7         1
"""

# Same part with a *SECTION_SHELL of its very own.
FREE_PART_OWN_SECTION = """\
*PART
carrier on section 8
        88         8         1
*SECTION_SHELL
         8         2       1.0         2
      0.10      0.10      0.10      0.10
"""

# ... and on a *SECTION_SOLID, to prove the shell placeholder is not blanket.
FREE_PART_SOLID_SECTION = """\
*PART
carrier on solid section 8
        88         8         1
*SECTION_SOLID
         8         1
"""

# A *SECTION_DISCRETE part with no elements: the connector path already claims
# it (_discrete_part_ids keys on the SECTION, not on the elements), so it is
# skipped by /PART emission entirely and must not be given a placeholder.
FREE_PART_DISCRETE = """\
*PART
discrete carrier
        88         8         1
*SECTION_DISCRETE
         8
"""

# The element-free part referenced by a *SET_PART that reaches the deck:
# *LOAD_BODY_PARTS turns the set into the /GRNOD/PART scope of every /GRAV.
SET_REFERENCE = """\
*SET_PART_LIST
        10
         7        88
*LOAD_BODY_Z
         5    9810.0
*LOAD_BODY_PARTS
        10
*DEFINE_CURVE
         5
                     0.0                     1.0
                     1.0                     1.0
"""

# An element-free *MAT_RIGID part doing real work: it owns no elements, but
# *CONSTRAINED_EXTRA_NODES gives it nodes and it becomes a /RBODY.
RIGID_FREE_PART = """\
*PART
element-free rigid carrier
        88         0         9
*MAT_RIGID
         9  7.85E-9  210000.0       0.3
       1.0       7.0       7.0
*CONSTRAINED_EXTRA_NODES_NODE
        88         2
*CONSTRAINED_EXTRA_NODES_NODE
        88         3
"""

# An element-free part on an ORTHOTROPIC material. The composite prepass
# declines to synthesize an orthotropic property for it (there is no element to
# put one on) and used to predict starter ERROR 3047 for the pairing that
# leaves behind; it does not happen — the MAT/PROP class check runs per element
# GROUP and this part contributes none. So the placeholder has to cover it, and
# the resulting deck is starter-clean.
ORTHO_FREE_PART = """\
*PART
orthotropic carrier, no elements
        88         0        12
*MAT_ORTHOTROPIC_ELASTIC
        12  1.55E-9  150000.0   10000.0   10000.0      0.02      0.02       0.4
    5000.0    3000.0    4000.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0         0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0
"""

# The *INTEGRATION_SHELL PID_i material carrier with NO hand-added
# *SECTION_SHELL — the idiom of Vol I R17 p.29-17, and the exact case that
# keyword's own pass used to ask the user to repair by hand. Its own head: the
# meshed part needs *MAT_024 (LAW1 is banned from every layered shell property,
# hm_read_part.F:289 ERROR 658) and its section needs QR/IRID = -2 in card-1
# field 6, cols 51-60.
RULE_CARRIER_DECK = """\
*KEYWORD
*TITLE
*INTEGRATION_SHELL PID_i carrier, no hand-added section
*CONTROL_TERMINATION
      0.01
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
*ELEMENT_SHELL
       1       7       1       2       3       4
*PART
real plate
         7         7         3
*SECTION_SHELL
         7         2       1.0         3         0        -2
       2.0       2.0       2.0       2.0
*INTEGRATION_SHELL
         2         3         0         0
      -1.0      0.25         0
       0.0       0.5        88
       1.0      0.25         0
*PART
material carrier, no elements
        88         0         4
*MAT_PIECEWISE_LINEAR_PLASTICITY
         3  7.85E-9  210000.0       0.3     300.0
*MAT_PIECEWISE_LINEAR_PLASTICITY
         4  1.0E-10       3.0      0.45       0.5
*END
"""

END = "*END\n"


# ── Harness ──────────────────────────────────────────────────────────────────

def _convert(deck):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path, encoding="utf-8") as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _free_warnings(result):
    return [w for w in result.warnings if MARKER in w]


def _block(starter, header):
    """The lines of the single block starting with *header* (header included,
    trailing HDR ruler excluded). Fails if the header is not unique."""
    out, cur = [], None
    for ln in starter.splitlines():
        if ln.startswith(header):
            cur = [ln]
            out.append(cur)
        elif cur is not None:
            if ln.startswith("#---1----"):
                cur = None
            else:
                cur.append(ln)
    assert len(out) == 1, f"expected exactly one {header!r}, got {len(out)}"
    return out[0]


def _prop_ids(starter):
    """Every emitted property id, whatever the /PROP subtype."""
    return {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
            if ln.startswith("/PROP/")}


def _part_prop_refs(starter):
    """{part id: property id} — the first 10-column field of each /PART card 1
    (``prop_ID mat_ID subset_ID``), which is what the starter resolves."""
    refs = {}
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/PART/"):
            refs[int(ln.rsplit("/", 1)[1])] = int(lines[i + 2][:10])
    return refs


# ─────────────────────────────────────────────────────────────────────────────


class ElementFreePartEmissionTests(unittest.TestCase):
    """The repro: one meshed part, one element-free part with SECID 0."""

    def test_placeholder_property_is_emitted_for_the_element_free_part(self):
        _, starter = _convert(HEAD + FREE_PART + END)
        self.assertIn("/PROP/SHELL/88", starter)

    def test_part_card_points_at_a_property_the_deck_emits(self):
        # The whole bug in one assertion: before the fix /PART/88 named
        # property 88 and no /PROP/88 existed -> starter ERROR 178.
        _, starter = _convert(HEAD + FREE_PART + END)
        self.assertEqual(88, _part_prop_refs(starter)[88])
        self.assertIn(88, _prop_ids(starter))

    def test_part_card_is_column_exact(self):
        # prop_ID mat_ID subset_ID, three 10-wide right-aligned fields. The
        # material and the title survive: that is what a carrier part is FOR.
        _, starter = _convert(HEAD + FREE_PART + END)
        self.assertEqual(
            ["/PART/88",
             "material carrier, no elements",
             "        88         1         0"],
            _block(starter, "/PART/88"))

    def test_placeholder_property_card_is_the_auto_shell_section(self):
        # Identical to what a sectionless MESHED shell part already gets from
        # _auto_section_shell: ELFORM 2 -> Ishell 12, NIP 3, zero thickness.
        _, starter = _convert(HEAD + FREE_PART + END)
        self.assertEqual(
            ["/PROP/SHELL/88",
             "AutoPropShell_88",
             "#   Ishell    Ismstr     Ish3n    Idrill",
             "        12         0         0         0",
             "#                 hm                  hf                  hr"
             "                  dm                  dn",
             "                   0                   0                   0"
             "                   0                   0",
             "#        N   Istrain               Thick              Ashear"
             "              Ithick     Iplas",
             "         3         0                   0                   0"
             "                   0         0"],
            _block(starter, "/PROP/SHELL/88"))

    def test_the_meshed_part_is_untouched(self):
        _, starter = _convert(HEAD + FREE_PART + END)
        self.assertEqual(7, _part_prop_refs(starter)[7])
        self.assertIn("/PROP/SHELL/7", starter)
        self.assertIn("/SHELL/7", starter)

    def test_every_element_free_part_gets_its_own_property(self):
        _, starter = _convert(HEAD + FREE_PART + FREE_PART_99 + END)
        self.assertIn("/PROP/SHELL/88", starter)
        self.assertIn("/PROP/SHELL/99", starter)
        self.assertEqual({7: 7, 88: 88, 99: 99}, _part_prop_refs(starter))

    def test_parts_sharing_one_undefined_secid_share_one_placeholder(self):
        # Both resolve to section 5, so section 5 gets ONE /PROP — emitting it
        # per part would collide on the property id.
        _, starter = _convert(HEAD + TWO_FREE_PARTS_ONE_SECID + END)
        self.assertEqual(1, starter.count("/PROP/SHELL/5\n"))
        self.assertEqual({7: 7, 88: 5, 99: 5}, _part_prop_refs(starter))

    def test_warning_names_the_parts_in_ascending_order(self):
        result, _ = _convert(HEAD + FREE_PART + FREE_PART_99 + END)
        hits = _free_warnings(result)
        self.assertEqual(1, len(hits), f"expected one warning, got {hits}")
        w = hits[0]
        self.assertIn("*PART record(s) 88, 99", w)
        self.assertLess(w.index("88"), w.index("99"))

    def test_warning_states_the_error_it_prevents_and_the_physics_it_keeps(self):
        result, _ = _convert(HEAD + FREE_PART + END)
        w = _free_warnings(result)[0]
        self.assertIn("ERROR 178", w)
        self.assertIn("PLACEHOLDER", w)
        self.assertIn("changes no physics", w)


class ReferencedElementFreePartTests(unittest.TestCase):
    """The part is element-free AND referenced by a *SET_PART that reaches the
    deck. Both the reference and the property must resolve."""

    def test_grnod_part_scope_lists_the_element_free_part(self):
        _, starter = _convert(HEAD + FREE_PART + SET_REFERENCE + END)
        grnod = _block(starter, "/GRNOD/PART/")
        self.assertEqual("         7        88", grnod[2])

    def test_the_referenced_part_is_still_emitted_with_a_property(self):
        # Dropping the /PART instead would leave this /GRNOD/PART naming a part
        # that does not exist — starter WARNING 194.
        _, starter = _convert(HEAD + FREE_PART + SET_REFERENCE + END)
        self.assertIn("/PART/88", starter)
        self.assertIn("/PROP/SHELL/88", starter)
        self.assertEqual(88, _part_prop_refs(starter)[88])

    def test_element_free_rigid_part_keeps_its_rbody_and_resolves(self):
        # *CONSTRAINED_EXTRA_NODES lets a part with no mesh of its own form a
        # /RBODY from borrowed nodes: an element-free part doing real work.
        _, starter = _convert(HEAD + RIGID_FREE_PART + END)
        self.assertIn("/RBODY/", starter)
        self.assertEqual(88, _part_prop_refs(starter)[88])
        self.assertIn(88, _prop_ids(starter))


class CarrierIdiomsResolveWithoutAHandEditTests(unittest.TestCase):
    """The two element-free shapes the composite writer used to send the user
    away to fix by hand. Both are covered by the placeholder, and both are
    starter-clean as converted — no *SECTION_SHELL to add, no mesh to supply.

    Starter-verified on starter_win64 (nt=6). RULE_CARRIER_DECK: `0 ERROR(S)
    0 WARNING(S)`, `NORMAL TERMINATION`, reading identically to a control deck
    where the carrier IS given a *SECTION_SHELL by hand. HEAD + ORTHO_FREE_PART:
    `0 ERROR(S)`, and its one warning (1084, LAW1 with N > 1) is on the MESHED
    part 7 / property 7 and appears unchanged with part 88 removed — the empty
    part itself is echoed as "ISOTROPIC SHELL PROPERTY SET NUMBER 88" and
    "Part id,name: 88 orthotropic carrier, Mat type: 93 Elm type: N/A", the
    PROP_SHELL=2 law on IGTYP 1 with no complaint. No ERROR 3047 anywhere.
    """

    def test_integration_shell_carrier_resolves_without_a_hand_added_section(self):
        result, starter = _convert(RULE_CARRIER_DECK)
        self.assertIn("/PART/88", starter)
        self.assertIn("/PROP/SHELL/88", starter)
        self.assertEqual(88, _part_prop_refs(starter)[88])
        # the carrier is still doing its job: its material reaches the layup
        self.assertIn("/PROP/TYPE51/", starter)
        # exactly one message about it, and it explains the synthesized /PROP
        self.assertEqual(1, len(_free_warnings(result)), result.warnings)
        self.assertIn("PLACEHOLDER", _free_warnings(result)[0])
        # ...and nothing tells the user to hand-add a section any more
        self.assertFalse([w for w in result.warnings
                          if "Give the carrier part a *SECTION_SHELL" in w],
                         result.warnings)

    def test_orthotropic_element_free_part_resolves_and_is_not_called_fatal(self):
        result, starter = _convert(HEAD + ORTHO_FREE_PART + END)
        self.assertIn("/PROP/SHELL/88", starter)
        self.assertEqual(88, _part_prop_refs(starter)[88])
        self.assertIn("/MAT/LAW93/12", starter)
        # the composite pass reports the empty mesh but predicts no failure
        composite = [w for w in result.warnings
                     if "no shell or solid elements" in w]
        self.assertEqual(1, len(composite), result.warnings)
        self.assertNotIn("3047", composite[0])


class NoPlaceholderWhenTheReferenceAlreadyResolvesTests(unittest.TestCase):
    """The placeholder is a last resort — anything that already emits a /PROP
    for the part's id must suppress it, or the deck gains a duplicate."""

    def test_section_shared_with_a_meshed_part_needs_no_placeholder(self):
        result, starter = _convert(HEAD + FREE_PART_SHARED_SECTION + END)
        self.assertEqual({7}, _prop_ids(starter))
        self.assertEqual(7, _part_prop_refs(starter)[88])
        self.assertEqual([], _free_warnings(result))

    def test_own_section_shell_needs_no_placeholder(self):
        result, starter = _convert(HEAD + FREE_PART_OWN_SECTION + END)
        self.assertEqual({7, 8}, _prop_ids(starter))
        self.assertEqual(8, _part_prop_refs(starter)[88])
        self.assertNotIn("/PROP/SHELL/88", starter)
        self.assertEqual([], _free_warnings(result))

    def test_section_solid_is_not_overwritten_by_a_shell_placeholder(self):
        result, starter = _convert(HEAD + FREE_PART_SOLID_SECTION + END)
        self.assertIn("/PROP/SOLID/8", starter)
        self.assertNotIn("/PROP/SHELL/8\n", starter)
        self.assertEqual(8, _part_prop_refs(starter)[88])
        self.assertEqual([], _free_warnings(result))

    def test_element_free_discrete_part_stays_a_connector(self):
        # _discrete_part_ids claims it off its *SECTION_DISCRETE, so /PART
        # emission skips it and there is no dangling reference to repair.
        result, starter = _convert(HEAD + FREE_PART_DISCRETE + END)
        self.assertNotIn("/PART/88", starter)
        self.assertNotIn("/PROP/SHELL/88", starter)
        self.assertEqual([], _free_warnings(result))


class NoFalsePositiveTests(unittest.TestCase):
    """A deck whose parts all carry elements must stay silent — and unchanged."""

    def test_clean_deck_does_not_warn(self):
        result, starter = _convert(HEAD + END)
        self.assertEqual([], _free_warnings(result))
        self.assertEqual({7}, _prop_ids(starter))

    def test_golden_fixture_output_is_byte_identical(self):
        # Every part in these fixtures has elements, so the pass must not
        # perturb a single byte of them.
        for stem in ("shell_explicit", "solid_plastic", "rigid_contact",
                     "tied_weld", "implicit_qstat"):
            with self.subTest(stem=stem), tempfile.TemporaryDirectory() as tmp:
                src = FIXTURES_DIR / f"{stem}.k"
                dst = os.path.join(tmp, f"{stem}.k")
                shutil.copy(src, dst)
                result = convert(dst, write_log=False)
                for suffix, path in (("0000", result.starter_path),
                                     ("0001", result.engine_path)):
                    produced = Path(path).read_text().replace("\r\n", "\n")
                    golden = (EXPECTED_DIR / f"{stem}_{suffix}.rad"
                              ).read_text().replace("\r\n", "\n")
                    self.assertEqual(golden, produced,
                                     f"{stem}_{suffix}.rad changed")
                self.assertEqual([], _free_warnings(result))


class PartPropertyResolutionInvariantTests(unittest.TestCase):
    """The contract the starter enforces (ERROR 178), asserted directly: every
    /PART must name a property the same deck emits."""

    DECKS = {
        "element-free part": HEAD + FREE_PART + END,
        "two element-free parts": HEAD + FREE_PART + FREE_PART_99 + END,
        "two on one undefined secid": HEAD + TWO_FREE_PARTS_ONE_SECID + END,
        "referenced by a *SET_PART": HEAD + FREE_PART + SET_REFERENCE + END,
        "element-free rigid part": HEAD + RIGID_FREE_PART + END,
        "shared section": HEAD + FREE_PART_SHARED_SECTION + END,
        "own section": HEAD + FREE_PART_OWN_SECTION + END,
        "solid section": HEAD + FREE_PART_SOLID_SECTION + END,
        "discrete carrier": HEAD + FREE_PART_DISCRETE + END,
        "orthotropic carrier": HEAD + ORTHO_FREE_PART + END,
        "*INTEGRATION_SHELL PID_i carrier": RULE_CARRIER_DECK,
        "all parts meshed": HEAD + END,
    }

    def test_no_part_references_a_property_that_does_not_exist(self):
        for name, deck in self.DECKS.items():
            with self.subTest(deck=name):
                _, starter = _convert(deck)
                emitted = _prop_ids(starter)
                dangling = {pid: prop
                            for pid, prop in _part_prop_refs(starter).items()
                            if prop not in emitted}
                self.assertEqual({}, dangling,
                                 f"{name}: /PART -> missing /PROP (ERROR 178)")


if __name__ == "__main__":
    unittest.main()
