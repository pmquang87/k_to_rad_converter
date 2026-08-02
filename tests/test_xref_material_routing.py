"""Which parts a ``*INITIAL_FOAM_REFERENCE_GEOMETRY`` really turns into a
``/XREF`` — the MATERIAL side of ``writer/inistate.py::_resolve_xref_parts``.

The starter accepts a solid-part ``/XREF`` only for laws 1/35/38/42/70/88/90
(``hm_read_xref.F:222-226``, else ERROR 2014), so k2rad resolves each part's
material to the law it will actually emit and drops the rest with a warning.
That resolution used to be a private 7-family table in ``inistate.py`` which
returned ``None`` — read as "some other law" — for the two families that reach
``/MAT/ELAST`` by a route other than ``*MAT_ELASTIC``:

  * ``*MAT_RIGID`` (the /RBODY's material), and
  * the ``*MAT_SPOTWELD`` fallback a MAT_100 part gets when it is not a
    pure-beam connector (a solid/hexa or shell spotweld).

Both are LAW1 and LAW1 IS on the whitelist, so both lost their ``/XREF`` under a
warning that named a law violation that does not exist. The table is gone: the
gate now reads ``mesh.py::_target_mat_law``, the one mid → law map in the
codebase, and the two families are decided on their own merits.

Measured on ``starter_win64`` (nt=6), one hexa on ``*SECTION_SOLID`` with a
4-node ``*INITIAL_FOAM_REFERENCE_GEOMETRY``:

  * ``*MAT_SPOTWELD`` solid part, ``/XREF`` emitted → NORMAL TERMINATION,
    ``0 ERROR(S) 0 WARNING(S)``. It is a deformable part with a real stress-free
    reference state, so it keeps the block.
  * ``*MAT_RIGID`` solid part, ``/XREF`` force-emitted for the probe → also
    NORMAL TERMINATION, ``0 ERROR(S) 0 WARNING(S)``. The starter does not mind;
    the block is simply inert, because the part converts to an /RBODY and every
    node it owns is kinematically slaved to the rigid master. k2rad still skips
    it — not to dodge an error, but because it changes no physics while forcing
    the part's ``*SECTION_SOLID`` to ``Ismstr=10`` (measured: the same deck
    emits ``Ismstr 0`` without the block and ``10`` with it), which the shared
    section rule then propagates to any deformable part using that section.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState
from k2rad.writer import inistate
from k2rad.writer import mesh


def _convert(deck: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _state(deck: str) -> ConversionState:
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _row(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def _raw_block(starter: str, header: str):
    """The block's lines exactly as emitted, ruler line excluded."""
    out, cur = [], None
    for ln in starter.splitlines():
        if ln == header:
            cur = out
        elif cur is not None:
            if ln.startswith("#---1----"):
                break
            cur.append(ln)
    assert out or cur is not None, f"{header!r} not found"
    return [header] + out


def _xref_rows(starter: str, pid: int):
    return [ln for ln in _raw_block(starter, f"/XREF/{pid}")[4:]
            if ln.strip() and not ln.startswith("#")]


NODES = ("*NODE\n"
         "       1             0.0             0.0             0.0\n"
         "       2             1.0             0.0             0.0\n"
         "       3             1.0             1.0             0.0\n"
         "       4             0.0             1.0             0.0\n"
         "       5             0.0             0.0             1.0\n"
         "       6             1.0             0.0             1.0\n"
         "       7             1.0             1.0             1.0\n"
         "       8             0.0             1.0             1.0\n")
BRICK = ("*ELEMENT_SOLID\n"
         "       1       1       1       2       3       4       5       6"
         "       7       8\n")
QUAD = "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
SOLID_PART = ("*PART\nblock\n" + _row(1, 1, 1) + "\n"
              "*SECTION_SOLID\n" + _row(1, 1) + "\n")
SHELL_PART = ("*PART\nplate\n" + _row(1, 1, 1) + "\n"
              "*SECTION_SHELL\n" + _row(1, 2, 1.0, 4) + "\n"
              + _row(1.2, 1.2, 1.2, 1.2) + "\n")
REF_GEOM = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
            "       1             0.0             0.0             0.0\n"
            "       2             1.1             0.0             0.0\n"
            "       3             1.1             1.1             0.0\n"
            "       4             0.0             1.1             0.0\n")
END = "*CONTROL_TERMINATION\n       1.0\n*END\n"

# MAT_100 card1 MID RO E PR SIGY, card2 EFAIL NRR NRS NRT.
MAT_SPOTWELD = ("*MAT_SPOTWELD\n"
                + _row(1, 7.85e-9, 210000.0, 0.3, 300.0) + "\n"
                + _row(0.0, 5000.0, 5000.0, 5000.0) + "\n")
MAT_RIGID = ("*MAT_RIGID\n"
             + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
             + _row(0, 0, 0) + "\n"
             + _row(0, 0, 0, 0, 0, 0) + "\n")
MAT_024 = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
           + _row(1, 7.85e-9, 210000.0, 0.3, 300.0) + "\n")

WHITELIST_MARK = "solid-/XREF whitelist"
RIGID_MARK = "*MAT_RIGID part"


def _solid_deck(mat: str, geom: str = REF_GEOM) -> str:
    return "*KEYWORD\n" + NODES + BRICK + SOLID_PART + mat + geom + END


def _shell_deck(mat: str, geom: str = REF_GEOM) -> str:
    return "*KEYWORD\n" + NODES + QUAD + SHELL_PART + mat + geom + END


def _ismstr(starter: str) -> int:
    """The Ismstr field of the single /PROP/SOLID (columns 11-20 of its data)."""
    data = [ln for ln in _raw_block(starter, "/PROP/SOLID/1")[2:]
            if not ln.startswith("#")]
    return int(data[0][10:20])


# ─────────────────────────────────────────────────────────────────────────────
# One routing map
# ─────────────────────────────────────────────────────────────────────────────

class SharedLawMapTests(unittest.TestCase):

    def test_the_xref_gate_reads_the_shared_mid_to_law_map(self):
        """The private 7-family copy is gone — one map, one place to extend."""
        self.assertIs(inistate._target_mat_law, mesh._target_mat_law)
        self.assertFalse(hasattr(inistate, "_xref_target_law"))

    def test_the_two_repaired_families_really_are_law1(self):
        """The premise of the whole fix: both resolve to LAW1, and LAW1 is on
        the starter's whitelist — so the old drop had no basis."""
        self.assertIn(1, inistate._XREF_SOLID_LAWS)
        rigid = _state(_solid_deck(MAT_RIGID))
        self.assertEqual(inistate._target_mat_law(rigid, 1), 1)
        weld = _state(_solid_deck(MAT_SPOTWELD))
        self.assertEqual(inistate._target_mat_law(weld, 1), 1)
        # ...and the pure-beam connector really does get no /MAT, which is why
        # only the FALLBACK (a solid/shell MAT_100 part) is in scope here.
        beam_weld = _state("*KEYWORD\n" + NODES
                           + "*PART\nweld\n" + _row(1, 1, 1) + "\n"
                           + "*SECTION_BEAM\n" + _row(1, 2) + "\n"
                           + _row(100.0, 833.0, 833.0, 1400.0) + "\n"
                           + "*ELEMENT_BEAM\n" + _row(11, 1, 1, 2, 5) + "\n"
                           + MAT_SPOTWELD + END)
        self.assertIsNone(inistate._target_mat_law(beam_weld, 1))


# ─────────────────────────────────────────────────────────────────────────────
# *MAT_SPOTWELD fallback: deformable, keeps its /XREF
# ─────────────────────────────────────────────────────────────────────────────

class SpotweldFallbackXrefTests(unittest.TestCase):
    """A MAT_100 part that is NOT a pure-beam connector falls back to
    /MAT/ELAST (LAW1) and is an ordinary deformable part — it gets the /XREF.
    Starter-measured on the emitted deck: 0 ERROR(S) 0 WARNING(S)."""

    def setUp(self):
        self.result, self.starter = _convert(_solid_deck(MAT_SPOTWELD))

    def test_the_xref_is_emitted(self):
        self.assertIn("/XREF/1", self.starter)
        self.assertFalse([w for w in self.result.warnings
                          if WHITELIST_MARK in w], self.result.warnings)

    def test_the_block_is_column_exact(self):
        raw = _raw_block(self.starter, "/XREF/1")
        self.assertEqual(raw[0], "/XREF/1")
        self.assertEqual(raw[1], "XREF_PART_1")
        self.assertEqual(raw[2], "#    Nitrs")
        self.assertEqual(raw[3], f"{0:>10}")                    # Nitrs, I10
        self.assertEqual(raw[4], "#  node_ID" + "".join(
            f"{c:>20}" for c in "XYZ"))
        rows = _xref_rows(self.starter, 1)
        self.assertEqual(len(rows), 4)                          # 4 covered nodes
        for r in rows:
            self.assertEqual(len(r), 70)                        # I10 + 3 x F20
        self.assertEqual([int(r[0:10]) for r in rows], [1, 2, 3, 4])
        self.assertEqual(rows[1], f"{2:>10}{'1.1':>20}{'0':>20}{'0':>20}")
        self.assertEqual([float(r[10:30]) for r in rows], [0.0, 1.1, 1.1, 0.0])
        self.assertEqual([float(r[30:50]) for r in rows], [0.0, 0.0, 1.1, 1.1])
        self.assertEqual([float(r[50:70]) for r in rows], [0.0, 0.0, 0.0, 0.0])

    def test_the_solid_section_is_promoted_to_ismstr_10(self):
        """/XREF on a solid needs Ismstr>=10 or the starter raises ERROR 2013,
        so keeping the block has to carry the formulation with it."""
        self.assertEqual(_ismstr(self.starter), 10)
        _, plain = _convert(_solid_deck(MAT_SPOTWELD, geom=""))
        self.assertEqual(_ismstr(plain), 0)

    def test_a_pure_beam_spotweld_part_is_untouched(self):
        """The connector case has no /MAT at all — and no solid elements, so it
        never reaches the gate; the reference geometry simply hits nothing."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART\nweld\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_BEAM\n" + _row(1, 2) + "\n"
                + _row(100.0, 833.0, 833.0, 1400.0) + "\n"
                + "*ELEMENT_BEAM\n" + _row(11, 1, 1, 2, 5) + "\n"
                + MAT_SPOTWELD + REF_GEOM + END)
        result, starter = _convert(deck)
        self.assertNotIn("/XREF/", starter)
        self.assertIn("/PROP/TYPE13", starter)
        self.assertFalse([w for w in result.warnings if WHITELIST_MARK in w],
                         result.warnings)


# ─────────────────────────────────────────────────────────────────────────────
# *MAT_RIGID: dropped, and for the RIGHT reason
# ─────────────────────────────────────────────────────────────────────────────

class RigidPartXrefTests(unittest.TestCase):
    """Pinned decision: a rigid part gets NO /XREF, and the warning says why —
    no strain state on an /RBODY — instead of claiming a law violation. The
    starter would take the block (measured 0 ERROR(S) 0 WARNING(S) with it
    force-emitted); the reason to skip is physics plus the Ismstr side effect."""

    def setUp(self):
        self.result, self.starter = _convert(_solid_deck(MAT_RIGID))

    def _rigid_warning(self):
        hits = [w for w in self.result.warnings if RIGID_MARK in w]
        self.assertEqual(len(hits), 1, self.result.warnings)
        return hits[0]

    def test_no_xref_for_a_rigid_solid_part(self):
        self.assertNotIn("/XREF/", self.starter)
        self.assertIn("/RBODY", self.starter)

    def test_the_warning_gives_the_rigid_reason_not_a_law_claim(self):
        w = self._rigid_warning()
        self.assertIn("/RBODY", w)
        self.assertIn("no strain state", w)
        self.assertIn("NOT a starter rejection", w)
        # The old text claimed the law was off the whitelist. It is ON it, and
        # the ERROR the old text threatened is not what happens here.
        self.assertNotIn("outside the starter's " + WHITELIST_MARK, w)
        self.assertNotIn("2014", w)
        self.assertIn("LAW1, which IS on the " + WHITELIST_MARK, w)
        # the measured cost of emitting it anyway
        self.assertIn("Ismstr=10", w)

    def test_the_section_keeps_its_default_formulation(self):
        """The concrete cost of emitting it: Ismstr 0 -> 10 on the section,
        which any deformable part sharing the section is dragged into."""
        self.assertEqual(_ismstr(self.starter), 0)

    def test_a_rigid_shell_part_is_skipped_by_the_same_rule(self):
        """The shell branch has no law gate at all, so a rigid shell part used
        to keep a /XREF that is just as meaningless. One rule, one reason."""
        result, starter = _convert(_shell_deck(MAT_RIGID))
        self.assertNotIn("/XREF/", starter)
        self.assertTrue([w for w in result.warnings if RIGID_MARK in w],
                        result.warnings)

    def test_a_deformable_part_on_the_same_deck_still_gets_its_xref(self):
        """The skip is per-part, not a global switch. Part 1 is rigid and
        part 2 is a LAW38 foam; both own the same 8 nodes, so the reference
        geometry reaches both."""
        hexa = "       1       2       3       4       5       6       7       8\n"
        deck = ("*KEYWORD\n" + NODES
                + "*ELEMENT_SOLID\n"
                + "       1       1" + hexa
                + "       2       2" + hexa
                + "*PART\nrigid\n" + _row(1, 1, 1) + "\n"
                + "*PART\nfoam\n" + _row(2, 1, 2) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + MAT_RIGID
                + "*MAT_LOW_DENSITY_FOAM\n"
                + _row(2, 1.0e-10, 5.0, 900) + "\n"
                + "*DEFINE_CURVE\n" + _row(900) + "\n"
                + "                 0.0                 0.0\n"
                + "                 1.0                10.0\n"
                + REF_GEOM + END)
        result, starter = _convert(deck)
        self.assertNotIn("/XREF/1", starter)
        self.assertIn("/XREF/2", starter)
        self.assertTrue([w for w in result.warnings if RIGID_MARK in w],
                        result.warnings)


# ─────────────────────────────────────────────────────────────────────────────
# The off-whitelist warning now names the law
# ─────────────────────────────────────────────────────────────────────────────

class OffWhitelistWarningTests(unittest.TestCase):

    def test_it_names_the_actual_law_instead_of_the_word_law(self):
        """*MAT_024 -> /MAT/LAW36, which is off the whitelist. The wider map
        resolves it, so the message can print the number the user will look
        for; the old table returned None here and printed "a law"."""
        result, starter = _convert(_solid_deck(MAT_024))
        self.assertNotIn("/XREF/", starter)
        hits = [w for w in result.warnings if WHITELIST_MARK in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("/MAT/LAW36, which is", hits[0])
        self.assertIn("ERROR 2014", hits[0])

    def test_a_material_with_no_mat_at_all_says_so(self):
        """`_target_mat_law` returns None only when k2rad emits no /MAT for the
        id — an undefined MID here. The message must not call that "a law"."""
        deck = ("*KEYWORD\n" + NODES + BRICK
                + "*PART\nblock\n" + _row(1, 1, 77) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + REF_GEOM + END)
        result, starter = _convert(deck)
        self.assertNotIn("/XREF/", starter)
        hits = [w for w in result.warnings if WHITELIST_MARK in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("no /MAT at all", hits[0])


if __name__ == "__main__":
    unittest.main()
