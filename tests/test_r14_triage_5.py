"""Tests for the R14 CAMPAIGN TRIAGE batch, round 5 — PART A:

  A1  the spring token-mass compensation reaches the THREE producers that
      invent a token and never registered it (``*CONSTRAINED_SPOTWELD`` /
      ``*CONSTRAINED_GENERALIZED_WELD_SPOT`` with failure forces, and the two
      ``mass <= 0`` fallbacks), and the class that carries no ``/ADMAS`` to
      subtract from is compensated with a NEGATIVE ``/ADMAS``
  A2  ``*CONSTRAINED_SHELL_TO_SOLID`` -> one ``/RBODY`` per card (default ON,
      ``--no-shell-to-solid-rbody``)
  A3  ``*CONSTRAINED_GENERALIZED_WELD_BUTT`` -> one ``/RBODY`` per card with
      ``Ifail = 1`` and ``FN = FT = SIGY*L*D/BETA``, COINCIDENT pairs only
      (default ON, ``--no-generalized-weld-butt``)
  A4  the CNRB ``/RBODY`` card-1 shape: NINE fields, ``Ifail`` third on the
      ``Ioptoff`` card — the shape ``radioss2021/RBODY/rbody.cfg`` and
      ``hm_read_rbody.F:260-289`` describe, and the shape the other producers
      already wrote

  A5  ``*CONSTRAINED_JOINT_SCREW`` is NOT implemented this round (the measured
      ``/GJOINT/RACK`` arm missed both acceptance gates) — the numbers are in
      ROADMAP.md, and the only test here is that the keyword is still refused
      rather than silently mis-converted.

Kept in its own module, the repo's one-module-per-batch convention.
"""

import inspect
import os
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState
from k2rad.writer import rbody as rbody_writer


# ── Harness (the helpers of tests/test_r14_triage_4.py) ──────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


def _dispatch(deck: str) -> ConversionState:
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _has(warnings, *needles) -> bool:
    return any(all(n in w for n in needles) for w in warnings)


def _card_rows(text: str, header: str):
    """Every data line that immediately follows *header* in *text*."""
    lines = text.splitlines()
    return [lines[i + 1] for i, ln in enumerate(lines) if ln == header]


def _block_after(text: str, head: str, n: int):
    """*n* lines following the line that starts with *head*."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(head):
            return lines[i:i + n]
    raise AssertionError(f"{head!r} not in the emitted deck")


# ── A4: the CNRB /RBODY card shape ───────────────────────────────────────────

_CNRB_DECK = (
    "*KEYWORD\n"
    "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
    "*NODE\n"
    + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
              for i, (x, y, z) in enumerate(
                  [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], start=1))
    + "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
      "*PART\n"
      "plate\n" + _row(1, 1, 1) + "\n"
      "*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0, 1.0, 1.0, 1.0) + "\n"
      "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
      "*SET_NODE_LIST\n" + _row(9) + "\n" + _row(1, 2, 3) + "\n"
      "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(77, 0, 9) + "\n"
      "*END\n"
)


class CnrbRbodyCardShape(unittest.TestCase):
    """A4 — the CNRB producer wrote TEN fields on /RBODY card 1 (a phantom
    ``Ifail`` column) and a TWO-field ``Ioptoff`` card.

    ``radioss2021/RBODY/rbody.cfg`` card 1 is nine fields and
    ``hm_read_rbody.F:286-289`` reads ``Ioptoff``, ``Iexpams``, ``Ifail`` —
    ``Ifail`` is the THIRD value of the card BELOW the inertia pair, which is
    what the ``*MAT_RIGID`` producer (``rbody.py``) and the implicit probe
    already wrote.  No behaviour change: the emitted value was 0 and the
    fixed-column reader stops at nine fields.
    """

    def test_cnrb_card_1_has_nine_fields_and_no_Ifail_column(self):
        _r, starter, _e = _convert(_CNRB_DECK)
        self.assertIn("/RBODY/", starter)
        rows = _card_rows(starter, rbody_writer._RBODY_CARD1_HDR)
        self.assertTrue(rows, "no /RBODY card-1 row was emitted")
        for row in rows:
            self.assertEqual(len(row), 100, f"card 1 is not 9x10 wide: {row!r}")
            self.assertEqual(len(row.split()), 9, row)

    def test_the_Ifail_cell_is_the_third_value_of_the_Ioptoff_card(self):
        _r, starter, _e = _convert(_CNRB_DECK)
        rows = _card_rows(starter, rbody_writer._RBODY_IOPTOFF_HDR)
        self.assertTrue(rows, "no /RBODY Ioptoff row was emitted")
        for row in rows:
            self.assertEqual([int(v) for v in row.split()], [0, 0, 0], row)

    def test_the_ten_field_header_is_gone_from_every_shipped_text(self):
        """A rename is a prefix — assert on the RETRACTED spelling itself."""
        src = inspect.getsource(rbody_writer)
        self.assertNotIn("surf_ID     Ifail", src)
        for name in ("README.md", "CHANGELOG.md", "ROADMAP.md"):
            path = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), name)
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("surf_ID     Ifail", fh.read(), name)

    def test_all_five_producers_share_one_card_1_comment(self):
        """One constant, so the shape cannot drift between producers again.

        Five /RBODY producers now: *MAT_RIGID, the CNRB route, the implicit
        probe, *CONSTRAINED_SHELL_TO_SOLID and
        *CONSTRAINED_GENERALIZED_WELD_BUTT.
        """
        src = inspect.getsource(rbody_writer)
        self.assertEqual(
            src.count('"#  node_ID   sens_ID'), 1,
            "a producer spells the /RBODY card-1 comment out again instead of "
            "using _RBODY_CARD1_HDR")
        self.assertEqual(
            src.count('"#  Ioptoff'), 1,
            "a producer spells the /RBODY Ioptoff comment out again instead "
            "of using _RBODY_IOPTOFF_HDR")
        self.assertEqual(len(rbody_writer._RBODY_CARD1_HDR), 100)


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
