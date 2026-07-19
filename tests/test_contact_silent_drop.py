"""Tests for contacts that were accepted and then silently deleted.

The defect: a contact whose SECONDARY (LS-DYNA "slave") side consists entirely
of rigid-body nodes resolves to an empty /GRNOD, and the whole /INTER was
dropped by a bare ``if slav_grnod and mast_surf:`` with no ``else`` --
``k2rad/writer/contacts.py`` at the pre-fix lines 91-93 and 404/416.  No
warning, no entry in any tally, and the conversion log still reported
``skipped : 0 unsupported keyword(s)``.

This is the *DATABASE_* family of PR #80 (accepted, produced nothing, reported
success) but strictly worse: a missing /INTER changes the PHYSICS rather than
the instrumentation.  It was found on a unit-cell crush model that put a rigid
loading platen on the contact secondary side::

    *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE
            92         1         3         3

Five *CONTACT keywords in, three /INTER out.  The platen never touched the
model: force appeared only once the platen mid-surface reached the plate
mid-surface (7.25 mm of dead travel), the reaction was bit-identical across 30+
output states while internal energy climbed 0.66 -> 8682 mJ, and the implicit
solve diverged at 27-41 % of stroke.

The chosen behaviour is WARN AND DROP, plus accounting:
  * k2rad does not silently rewrite the user's contact definition by swapping
    the sides for them (that would convert a different model from the one they
    wrote, which is the same sin in the opposite direction);
  * but the drop is never silent again: an actionable warning naming the
    interface, the side, the cause and the remedy, AND an entry in
    ``recognized_not_emitted`` so the log's summary counts the loss.

Also covered: the same shape on the MAIN side, on the all-parts self-contact
path, and on *CONTACT_TIED_*, plus the previously-unreported *partial* rigid
thinning of a mixed secondary side.
"""

import os
import tempfile
import unittest

from k2rad import convert


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


# ── Deck pieces ─────────────────────────────────────────────────────────────
# Part 1 = deformable plate (nodes 1-4), part 2 = rigid platen (nodes 5-8).

_MESH = """*KEYWORD
*NODE
         1             0.0             0.0             0.0
         2            10.0             0.0             0.0
         3            10.0            10.0             0.0
         4             0.0            10.0             0.0
         5             0.0             0.0             1.0
         6            10.0             0.0             1.0
         7            10.0            10.0             1.0
         8             0.0            10.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
plate
         1         1         1
*PART
platen
         2         2         2
*SECTION_SHELL
         1        16
       1.0       1.0       1.0       1.0
*SECTION_SHELL
         2        16
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1     7.85E-9  210000.0       0.3
*MAT_RIGID
         2   7.86e-9    210000.0      0.3
"""

_TERM = """*CONTROL_TERMINATION
       1.0
*END
"""


def _s2s(ssid: int, msid: int, sstyp: int = 3, mstyp: int = 3) -> str:
    return (
        "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
        f"{ssid:10d}{msid:10d}{sstyp:10d}{mstyp:10d}\n"
        "       0.2       0.1\n"
    )


#: The reported defect: rigid platen (part 2) on the SECONDARY side.
DECK_RIGID_SECONDARY = _MESH + _s2s(2, 1) + _TERM

#: The same physics written the way OpenRadioss wants it: deformable secondary.
DECK_DEFORMABLE_SECONDARY = _MESH + _s2s(1, 2) + _TERM

#: A mixed secondary side (part set {1, 2}): the interface survives, but the
#: rigid half of it is quietly deleted -- previously with no warning either.
DECK_MIXED_SECONDARY = (
    _MESH
    + "*SET_PART_LIST\n       200\n         1         2\n"
    + _s2s(200, 1, sstyp=2)
    + _TERM
)

#: MAIN side names a part id that does not exist in the deck.
DECK_MISSING_MAIN = _MESH + _s2s(1, 77) + _TERM

#: A tied contact with the rigid platen on the secondary side.
DECK_TIED_RIGID_SECONDARY = (
    _MESH
    + "*CONTACT_TIED_NODES_TO_SURFACE\n"
      "         2         1         3         3\n"
      "       0.0       0.0\n"
    + _TERM
)


class RigidSecondaryContactDropped(unittest.TestCase):
    """The reported defect: SSID = a rigid part, and the /INTER vanishes."""

    def setUp(self):
        self.result, self.starter = _convert(DECK_RIGID_SECONDARY)

    def _drop_warnings(self):
        return [w for w in self.result.warnings if "NO /INTER was emitted" in w]

    def test_no_interface_is_emitted(self):
        # The behaviour itself is unchanged -- k2rad still declines to emit an
        # interface whose secondary node group would be empty. What changed is
        # that it now says so.
        self.assertNotIn("/INTER/TYPE7/", self.starter)

    def test_the_drop_warns_at_all(self):
        """The floor: a dropped interface is never silent again."""
        self.assertEqual(len(self._drop_warnings()), 1,
                         "expected exactly one drop warning, got: "
                         + repr(self.result.warnings))

    def test_the_warning_is_actionable(self):
        w = self._drop_warnings()[0]
        # Names the keyword and the interface id...
        self.assertIn("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", w)
        # ...which side was emptied, and that it was all rigid nodes...
        self.assertIn("SECONDARY", w)
        self.assertIn("ssid=2", w)
        self.assertIn("rigid body", w)
        # ...what it costs the user physically...
        self.assertIn("PHYSICAL CONSEQUENCE", w)
        self.assertIn("will NOT interact", w)
        # ...and the concrete remedy: put the deformable side secondary.
        self.assertIn("REMEDY", w)
        self.assertIn("DEFORMABLE", w)
        self.assertIn("SECONDARY (SSID)", w)

    def test_k2rad_does_not_silently_swap_the_sides(self):
        """Option (b) rejected: emitting the contact with the sides reversed
        would convert a model the user did not write. The warning says so."""
        self.assertIn("does NOT swap them", self._drop_warnings()[0])

    def test_the_loss_reaches_the_log_accounting(self):
        """`skipped : 0 unsupported keyword(s)` can no longer coexist with a
        missing /INTER: the drop is reported through the same
        recognized-but-not-emitted channel PR #80 introduced."""
        entries = dict(self.result.recognized_not_emitted)
        self.assertIn("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", entries)
        reason = entries["CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"]
        self.assertIn("no /INTER", reason)
        self.assertIn("[90001]", reason)      # the auto-assigned interface id

    def test_accounting_names_every_lost_interface(self):
        """Two dropped contacts of the same keyword are one log entry naming
        both ids -- note_recognized_not_emitted deduplicates on the keyword."""
        deck = _MESH + _s2s(2, 1) + _s2s(2, 1) + _TERM
        result, starter = _convert(deck)
        self.assertNotIn("/INTER/TYPE7/", starter)
        reason = dict(result.recognized_not_emitted)[
            "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"]
        self.assertIn("2 contact(s)", reason)
        self.assertIn("[90001, 90002]", reason)


class CorrectlyOrderedContactIsUntouched(unittest.TestCase):
    """The fix must not perturb the deck that was already right."""

    def test_deformable_secondary_still_emits_quietly(self):
        result, starter = _convert(DECK_DEFORMABLE_SECONDARY)
        self.assertIn("/INTER/TYPE7/", starter)
        self.assertEqual(
            [w for w in result.warnings if "NO /INTER was emitted" in w], [])
        self.assertEqual(
            [kw for kw, _ in result.recognized_not_emitted
             if kw.startswith("CONTACT")], [])


class PartialRigidSecondaryIsReported(unittest.TestCase):
    """A mixed secondary side keeps its interface but loses the rigid nodes.

    That is the same silent physics edit in partial form: it was never warned
    about either. The output is deliberately unchanged -- only the reporting."""

    def test_interface_survives_and_the_thinning_is_warned(self):
        result, starter = _convert(DECK_MIXED_SECONDARY)
        self.assertIn("/INTER/TYPE7/", starter)
        hits = [w for w in result.warnings
                if "removed from the secondary node group" in w]
        self.assertEqual(len(hits), 1, repr(result.warnings))
        self.assertIn("belong to a rigid body", hits[0])
        self.assertIn("MAIN (MSID) side of its own contact", hits[0])

    def test_a_kept_interface_is_not_counted_as_a_loss(self):
        result, _ = _convert(DECK_MIXED_SECONDARY)
        self.assertEqual(
            [kw for kw, _ in result.recognized_not_emitted
             if kw.startswith("CONTACT")], [])


class MainSideDropIsAlsoReported(unittest.TestCase):
    """The same shape on the MAIN side: msid names nothing that exists."""

    def test_missing_main_surface_warns_and_is_accounted(self):
        result, starter = _convert(DECK_MISSING_MAIN)
        self.assertNotIn("/INTER/TYPE7/", starter)
        hits = [w for w in result.warnings if "NO /INTER was emitted" in w]
        self.assertEqual(len(hits), 1, repr(result.warnings))
        self.assertIn("MAIN (MSID) side msid=77", hits[0])
        self.assertIn("PHYSICAL CONSEQUENCE", hits[0])
        self.assertIn("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
                      dict(result.recognized_not_emitted))


class TiedContactDropIsAccounted(unittest.TestCase):
    """*CONTACT_TIED_* already warned, but the loss never reached the tally."""

    def test_all_rigid_tied_secondary(self):
        result, starter = _convert(DECK_TIED_RIGID_SECONDARY)
        self.assertNotIn("/INTER/TYPE2/", starter)
        hits = [w for w in result.warnings if "NO /INTER was emitted" in w]
        self.assertEqual(len(hits), 1, repr(result.warnings))
        self.assertIn("kinematic tie", hits[0])
        # The tie-specific remedy: TYPE10 accepts rigid-body secondary nodes.
        self.assertIn("/INTER/TYPE10", hits[0])
        self.assertIn("CONTACT_TIED_NODES_TO_SURFACE",
                      dict(result.recognized_not_emitted))


if __name__ == "__main__":
    unittest.main()
