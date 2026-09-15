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
import re
import sys
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import HANDLERS, dispatch
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


# ── A1: the spring token-mass compensation ───────────────────────────────────

_TOKEN = 1.0e-4
_SHARE = _TOKEN / 2.0


def _plate(nid0=1, z0=0.0, eid=1, pid=1):
    """Four nodes + one shell, so their nodes carry element mass of their own."""
    pts = [(0.0, 0.0, z0), (10.0, 0.0, z0), (10.0, 10.0, z0), (0.0, 10.0, z0)]
    nodes = "".join(f"{nid0 + i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
                    for i, (x, y, z) in enumerate(pts))
    elem = _row(eid, pid, nid0, nid0 + 1, nid0 + 2, nid0 + 3) + "\n"
    return nodes, elem


def _weld_deck(sn=1.0e4, ss=5.0e4, meshed=True, admas=0.0, pairs=None,
               rho=7.85e-9):
    """Two shell plates 1 mm apart + *CONSTRAINED_SPOTWELD pair(s) WITH failure.

    Node ``n`` of the lower plate welds to node ``n + 10`` of the upper one, so
    every pair has a finite length (a coincident pair is refused outright).
    ``meshed`` False drops both plates, so the weld nodes carry no element mass
    of their own and the guard must refuse the compensation.
    """
    n1, e1 = _plate(1, 0.0, 1, 1)
    n2, e2 = _plate(11, 1.0, 2, 2)
    if not meshed:
        nodes = "*NODE\n" + n1 + n2
        elems = ""
        parts = ""
    else:
        nodes = "*NODE\n" + n1 + n2
        elems = "*ELEMENT_SHELL\n" + e1 + e2
        parts = ("*PART\n" "plate1\n" + _row(1, 1, 1) + "\n"
                 "*PART\n" "plate2\n" + _row(2, 1, 1) + "\n")
    welds = ""
    for a, b in (pairs or [(1, 11)]):
        welds += "*CONSTRAINED_SPOTWELD\n" + _row(a, b, sn, ss) + "\n"
    mass = ""
    if admas:
        mass = ("*ELEMENT_MASS\n"
                + "".join(f"{900 + i:>8}{n:>8}{admas:>16.8G}\n"
                          for i, n in enumerate((1, 11))))
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + nodes + elems + parts
            + "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
              "*MAT_ELASTIC\n" + _row(1, rho, 210000.0, 0.3) + "\n"
            + welds + mass + "*END\n")


def _admas_cards(starter: str):
    """{mass value: [node ids]} over every emitted /ADMAS/0."""
    out = {}
    lines = starter.splitlines()
    grnods = {}
    for i, ln in enumerate(lines):
        if ln.startswith("/GRNOD/NODE/"):
            gid = int(ln.rsplit("/", 1)[1])
            nids = []
            j = i + 2
            while j < len(lines) and not lines[j].startswith(("/", "#")):
                nids += [int(v) for v in lines[j].split()]
                j += 1
            grnods[gid] = nids
    for i, ln in enumerate(lines):
        if ln.startswith("/ADMAS/0/"):
            mass, gid = lines[i + 3].split()
            out.setdefault(float(mass), []).extend(grnods[int(gid)])
    return out


class SpringTokenNegativeAdmas(unittest.TestCase):
    """A1 — the classes that carry no ``/ADMAS`` to subtract from.

    The shipped rule only SUBTRACTED, so those classes got nothing. On
    ``intro-by-k.-weimar/spotweld/spotweld-ii/plates.nrbc.k`` that is the whole
    defect: one ``(stiff weld tie)`` token of 1e-4 against an LS-DYNA model
    mass of 1.0048e-4, i.e. the starter's ``TOTAL MASS`` read **2.0048E-04,
    +99.52 %**.  ``hm_read_admas.F:161-171`` accepts a NEGATIVE added mass
    (``ANCMSG(MSGID=476, MSGTYPE=MSGWARNING)`` only, no sign check, no floor)
    and adds it algebraically at ``:247-248``.
    """

    def test_one_weld_with_no_admas_gets_a_negative_card_of_half_the_token(self):
        """Hand: one element, 0.5 x 1e-4 = 5e-05 on EACH of its two ends."""
        _r, starter, _e = _convert(_weld_deck())
        cards = _admas_cards(starter)
        self.assertEqual(sorted(cards), [-_SHARE], cards)
        self.assertEqual(sorted(cards[-_SHARE]), [1, 11])
        self.assertIn("       -5.000000E-05", starter)

    def test_k_welds_on_one_node_scale_the_share(self):
        """Hand: node 1 sits on three welds -> 3 x 5e-05 = 1.5e-04."""
        deck = _weld_deck(pairs=[(1, 11), (1, 12), (1, 13)])
        _r, starter, _e = _convert(deck)
        cards = {round(m, 12): v for m, v in _admas_cards(starter).items()}
        self.assertEqual(sorted(cards), [-1.5e-4, -_SHARE], cards)
        self.assertEqual(cards[-1.5e-4], [1])
        self.assertEqual(sorted(cards[-_SHARE]), [11, 12, 13])

    def test_the_opt_out_writes_no_negative_admas_at_all(self):
        """--no-spring-token-mass-compensation reproduces the master output."""
        deck = _weld_deck()
        _r, on, _e = _convert(deck)
        _r2, off, _e2 = _convert(deck, spring_token_mass_compensation=False)
        self.assertIn("/ADMAS", on)
        self.assertNotIn("/ADMAS", off)
        self.assertNotIn("spring_token_compensation", off)
        # and the opt-out arm is the pre-round-5 file, not a renumbered one
        self.assertNotIn("-5.000000E-05", off)

    def test_a_degenerate_admas_is_kept_and_the_share_removed_separately(self):
        """``gnonspring.k``'s shape, but on MESHED nodes so the guard passes.

        The deck's own /ADMAS stays exactly as stated (an /ADMAS must be
        positive) and the FULL share comes off on a card of its own, so the
        sum is m_own + m_admas + token - token.
        """
        _r, starter, _e = _convert(_weld_deck(admas=1.0e-6))
        cards = _admas_cards(starter)
        self.assertEqual(sorted(cards), [-_SHARE, 1.0e-6], cards)
        self.assertEqual(sorted(cards[1.0e-6]), [1, 11])
        self.assertEqual(sorted(cards[-_SHARE]), [1, 11])
        self.assertTrue(_has(_r.warnings, "LESS /ADMAS",
                             "The full share was taken off 2 of them"))

    def test_an_element_free_weld_node_is_guarded_and_named(self):
        """Subtracting there would leave MS = 0 and the engine divides by it.

        The check that REACHES a TYPE4/8/13 spring is ``chkmsin.F:52-59``
        (``NEGATIVE MASS ON NODE ID=``) with ``resol.F:5460``'s
        ``CALL ARRET(2)``. ``rcheckmass.F``'s ERROR 1870 is NOT it: that whole
        branch is gated on ``IGTYP==23`` (``:112``) with ``MTN==108``
        (``:123``). The assertion below names the DISCRIMINATING substrings,
        so the retracted wording cannot come back through it.
        """
        result, starter, _e = _convert(_weld_deck(meshed=False))
        self.assertNotIn("/ADMAS", starter)
        self.assertTrue(_has(result.warnings,
                             "carry NO element mass of their own",
                             "chkmsin.F:52-59", "resol.F:5460",
                             "ERROR 1870 is NOT it", "[1, 11]"))

    def test_a_zero_density_part_does_not_satisfy_the_guard(self):
        """The screen is incidence AND rho > 0 — a node whose only element
        sits on a zero-density part would otherwise pass it and still land
        near zero mass."""
        result, starter, _e = _convert(_weld_deck(rho=0.0),
                                       zero_density_floor=True)
        self.assertNotIn("spring_token_compensation", starter)
        self.assertTrue(_has(result.warnings,
                             "carry NO element mass of their own"))

    def test_a_synthesized_ground_node_is_neither_compensated_nor_named(self):
        """``_emit_spring_part`` mints a grounded element's second node fully
        ``/BCS 111 111``-fixed, so a mass on it cannot move anything — and it
        is not a user node the guard sentence may name either."""
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n*NODE\n"
                + "".join(f"{i:>8}{x:>16.4f}{y:>16.4f}{0.0:>16.4f}\n"
                          for i, (x, y) in enumerate(
                              [(0, 0), (10, 0), (10, 10), (0, 10)], 1))
                + "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
                  "*ELEMENT_DISCRETE\n"
                + f"{1:>8}{2:>8}{1:>8}{0:>8}{0:>8}{1.0:>16.8G}"
                  f"{0:>8}{0.0:>16.8G}\n"
                + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
                + "*PART\nspring\n" + _row(2, 2, 2) + "\n"
                + "*SECTION_SHELL\n" + _row(1, 2) + "\n"
                + _row(1.0, 1.0, 1.0, 1.0) + "\n"
                  "*SECTION_DISCRETE\n" + _row(2, 0) + "\n"
                + _row(0.0, 1.0, 0.0, 0.0) + "\n"
                  "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                  "*MAT_SPRING_ELASTIC\n" + _row(2, 100.0) + "\n*END\n")
        result, starter, _e = _convert(deck)
        cards = _admas_cards(starter)
        self.assertEqual(sorted(cards), [-_SHARE], cards)
        self.assertEqual(cards[-_SHARE], [1],
                         "only the REAL end node may be compensated")
        self.assertFalse(_has(result.warnings,
                              "carry NO element mass of their own"),
                         "the synthesized ground node must not be named")

    def test_a_rigid_body_secondary_node_gets_no_negative_admas(self):
        """MEASURED inert on the roster's only carrier: with ``ICoG = 4``
        ``inirby.F:265-266`` discards the secondaries' mass, so the token AND
        any compensation of it do nothing. Compensating anyway would write a
        card that cannot act."""
        deck = _weld_deck().replace(
            "*SECTION_SHELL",
            "*SET_NODE_LIST\n" + _row(77) + "\n" + _row(1, 11, 2) + "\n"
            "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(88, 0, 77) + "\n"
            "*SECTION_SHELL")
        result, starter, _e = _convert(deck)
        self.assertIn("/RBODY/", starter)
        self.assertNotIn("spring_token_compensation", starter)
        self.assertTrue(_has(result.warnings,
                             "are SECONDARY nodes of a rigid body",
                             "inirby.F:265-266"))

    def test_the_retracted_rigid_sentence_is_gone_from_every_shipped_text(self):
        """The old RIGID sentence stated a fact that is FALSE on the only
        carrier: *"It is added to the body's total mass"*. With ICoG = 4
        ``inirby.F:265-266`` discards the secondaries' mass entirely."""
        import re as _re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        retracted = [
            "It is added to the body's total mass",
            "rides along there UNCOMPENSATED",
            "a rigid body's own dynamics are paced by that total",
        ]
        pats = [_re.compile(r"\s+".join(_re.escape(w) for w in r.split()))
                for r in retracted]
        # CHANGELOG.md is deliberately NOT scanned — the same scope
        # tests/test_r14_triage_4.py::_STATING_DOCS uses. A changelog RECORDS
        # a retraction and has to be able to quote the sentence it retracts;
        # every text that STATES the fact to a user is below.
        texts = {}
        for rel in ("README.md", "ROADMAP.md",
                    "k2rad_gui.py", os.path.join("k2rad", "cli.py"),
                    os.path.join("k2rad", "state.py"),
                    os.path.join("k2rad", "__init__.py"),
                    os.path.join("k2rad", "writer", "loads.py")):
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                # adjacent string literals joined, whitespace collapsed
                texts[rel] = " ".join(
                    fh.read().replace('"\n', "").replace("'\n", "").split())
        for rel, txt in texts.items():
            for pat, raw in zip(pats, retracted):
                self.assertIsNone(pat.search(txt), f"{rel}: {raw!r}")
        # the companion: the guard MUST match each retracted spelling
        for pat, raw in zip(pats, retracted):
            self.assertIsNotNone(pat.search(" ".join(raw.split())), raw)
            self.assertIsNotNone(
                pat.search("x " + raw.replace(" ", "\n   ") + " y"), raw)


_SPOTWELD_BEAM_DECK = (
    "*KEYWORD\n"
    "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
    "*NODE\n"
    + "".join(f"{i:>8}{x:>16.4f}{0.0:>16.4f}{0.0:>16.4f}\n"
              for i, x in ((1, 0.0), (2, 2.0), (3, 0.0)))
    + "*ELEMENT_BEAM\n" + _row(1, 7, 1, 2, 3) + "\n"
      "*PART\n" "weld\n" + _row(7, 7, 7) + "\n"
      "*SECTION_BEAM\n" + _row(7, 9) + "\n" + _row(0.0, 3.0, 3.0) + "\n"
      "*MAT_SPOTWELD\n" + _row(7, "%RO%", 210000.0, 0.3, 300.0) + "\n"
    + _row(0, 0, 0, 1000.0, 500.0, 500.0) + "\n"
      "*END\n"
)


_CABLE_DECK = (
    "*KEYWORD\n"
    "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             0.0             0.0            10.0\n"
    "       3             1.0             0.0             0.0\n"
    "       4             5.0             0.0            10.0\n"
    "       5             5.0             0.0             0.0\n"
    "*ELEMENT_BEAM\n" + _row(1, 7, 1, 2, 3) + "\n"
    "*ELEMENT_SHELL\n" + _row(2, 1, 1, 5, 4, 2) + "\n"
    "*PART\n" "cable\n" + _row(7, 3, 9) + "\n"
    "*PART\n" "plate\n" + _row(1, 1, 1) + "\n"
    "*SECTION_BEAM\n" + _row(3, 6) + "\n"
    "     100.0       5.0         0      12.0\n"
    "*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0, 1.0, 1.0, 1.0) + "\n"
    "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
    "*MAT_CABLE_DISCRETE_BEAM\n"
    "         9   %RO%  210000.0\n"
    "*END\n"
)


class DiscreteBeamTokenIsLengthScaled(unittest.TestCase):
    """A1 — the discrete-beam fallback, and the ``Ileng = 1`` length factor.

    ``*MAT_CABLE_DISCRETE_BEAM`` forces ``Ileng = 1``, and on such a property
    ``rinit3.F``'s ``UMASS`` is ``Mass x L_element``, so the share an element
    really puts on its two ends scales with its OWN length. The cable here is
    10 long, so the token's half-share is ``0.5 x 1e-4 x 10 = 5e-04``, not
    ``5e-05``.
    """

    def test_a_real_RO_VOL_cable_mass_is_never_compensated(self):
        _r, starter, _e = _convert(_CABLE_DECK.replace("%RO%", "  7.8E-09"))
        self.assertNotIn("spring_token_compensation", starter)

    def test_the_fallback_token_is_scaled_by_the_element_length(self):
        r, starter, _e = _convert(
            _CABLE_DECK.replace("%RO%", "      0.0"),
            zero_density_floor=False)
        self.assertTrue(_has(r.warnings, "non-positive connector mass"))
        cards = {round(m, 12): v for m, v in _admas_cards(starter).items()}
        self.assertEqual(sorted(cards), [-5.0e-4], cards)
        self.assertEqual(sorted(cards[-5.0e-4]), [1, 2])


class SpringTokenIsRegisteredOnlyWhereItIsInvented(unittest.TestCase):
    """A1 — LS-DYNA's OWN mass is never compensated.

    ``_make_spotweld_beam_connectors`` writes ``RO*A*L`` when the material
    states a density and falls back to the token only when that is
    non-positive. Compensating the first would be a NEW defect — it is the
    mass ``*MAT_SPOTWELD`` states.
    """

    def _state_shares(self, deck, **kw):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck)
        res = convert(path, output_stem=os.path.join(tmp.name, "o"),
                      write_log=False, **kw)
        with open(res.starter_path) as fh:
            starter = fh.read()
        tmp.cleanup()
        return res, starter

    def test_a_real_RO_A_L_weld_mass_is_never_compensated(self):
        res, starter = self._state_shares(
            _SPOTWELD_BEAM_DECK.replace("%RO%", "7.85E-09"))
        self.assertNotIn("spring_token_compensation", starter)
        self.assertNotIn("non-positive weld mass", "\n".join(res.warnings))

    def test_a_non_positive_weld_mass_registers_the_token_it_invents(self):
        # zero_density_floor OFF: with it on, the floor substitutes a POSITIVE
        # rho = 1e-24 before the writer runs, so RO*A*L never reaches the
        # fallback at all and there is no invented mass to register.
        res, starter = self._state_shares(
            _SPOTWELD_BEAM_DECK.replace("%RO%", "0.0"),
            zero_density_floor=False)
        self.assertTrue(_has(res.warnings, "non-positive weld mass",
                             "negative /ADMAS"))
        # The beam's own nodes carry no OTHER element, so the guard refuses
        # the card and names them — which is what proves the token reached
        # the registry at all.
        self.assertTrue(_has(res.warnings,
                             "carry NO element mass of their own", "[1, 2]"))
        self.assertNotIn("spring_token_compensation", starter)

    def test_the_third_node_of_a_weld_spring_gets_no_share(self):
        """``rinit3.F:1937-1939`` writes ``MSR`` onto ``IXR(2,I)``/``IXR(3,I)``
        only — node_ID3 is the orientation node and carries nothing."""
        res, _s = self._state_shares(
            _SPOTWELD_BEAM_DECK.replace("%RO%", "0.0"),
            zero_density_floor=False)
        joined = "\n".join(res.warnings)
        self.assertIn("[1, 2]", joined)
        self.assertNotIn("[1, 2, 3]", joined)


# ── A2 / A3: the two new /RBODY producers ────────────────────────────────────

_SHELL_MAT_SEC = (
    "*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0, 1.0, 1.0, 1.0) + "\n"
    "*SECTION_SOLID\n" + _row(2, 1) + "\n"
    "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
)


def _shell_to_solid_deck(nid=5, nsid=9, fibre=(1, 2, 3), tc=0, extra=""):
    """One brick + a shell strip + one *CONSTRAINED_SHELL_TO_SOLID card.

    Nodes 1-4 are the brick's lower face, 11-14 its upper one; node 5 is the
    shell node on the fibre; ``fibre`` names the set members.
    """
    pts = {1: (0, 0, 0), 2: (10, 0, 0), 3: (10, 10, 0), 4: (0, 10, 0),
           11: (0, 0, 10), 12: (10, 0, 10), 13: (10, 10, 10), 14: (0, 10, 10),
           5: (0, 0, 20), 6: (10, 0, 20), 7: (10, 10, 20)}
    nodes = "*NODE\n" + "".join(
        f"{i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}"
        + (f"{tc:>8}{0:>8}" if tc and i in (1, 5) else "") + "\n"
        for i, (x, y, z) in sorted(pts.items()))
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + nodes
            + "*ELEMENT_SOLID\n"
            + _row(1, 2, 1, 2, 3, 4, 11, 12, 13, 14) + "\n"
              "*ELEMENT_SHELL\n" + _row(2, 1, 5, 6, 7, 7) + "\n"
              "*PART\n" "shell\n" + _row(1, 1, 1) + "\n"
              "*PART\n" "brick\n" + _row(2, 2, 1) + "\n"
            + _SHELL_MAT_SEC
            + "*SET_NODE_LIST\n" + _row(nsid) + "\n" + _row(*fibre) + "\n"
            + f"*CONSTRAINED_SHELL_TO_SOLID\n{_row(nid, nsid)}\n"
            + extra
            + "*END\n")


class ShellToSolidRbody(unittest.TestCase):
    """A2 — one ``/RBODY`` per ``*CONSTRAINED_SHELL_TO_SOLID`` card."""

    def test_the_card_is_registered_and_no_longer_skipped(self):
        st = _dispatch(_shell_to_solid_deck())
        self.assertNotIn("CONSTRAINED_SHELL_TO_SOLID", st.skipped_keywords)
        self.assertEqual(len(st.shell_to_solids), 1)
        self.assertEqual((st.shell_to_solids[0].nid,
                          st.shell_to_solids[0].nsid), (5, 9))

    def test_the_emitted_body_is_the_shell_node_over_the_fibre_set(self):
        _r, starter, _e = _convert(_shell_to_solid_deck())
        blk = _block_after(starter, "/RBODY/5", 9)
        self.assertEqual(blk[0], "/RBODY/5")
        self.assertEqual(blk[2], rbody_writer._RBODY_CARD1_HDR)
        cells = blk[3].split()
        self.assertEqual(len(cells), 9, blk[3])
        # node_ID sens skew Ispher Mass grnd Ikrem ICoG surf
        self.assertEqual(cells[0], "5")
        self.assertEqual(cells[4], "0", "Mass must be 0 — Radioss lumps it")
        self.assertEqual(cells[7], "3", "ICoG 3 keeps a MESHED master in place")
        self.assertEqual(blk[5].split(), ["0", "0", "0"])   # Jxx Jyy Jzz
        self.assertEqual(blk[7].split(), ["0", "0", "0"])   # Jxy Jyz Jxz
        self.assertEqual(blk[8], rbody_writer._RBODY_IOPTOFF_HDR)
        grnod = cells[5]
        gblk = _block_after(starter, f"/GRNOD/NODE/{grnod}", 3)
        self.assertEqual(gblk[2].split(), ["1", "2", "3"])

    def test_the_opt_out_is_byte_identical_to_dropping_the_keyword(self):
        deck = _shell_to_solid_deck()
        r_on, on, _e = _convert(deck)
        r_off, off, _e2 = _convert(deck, shell_to_solid_rbody=False)
        self.assertIn("/RBODY/5", on)
        self.assertNotIn("/RBODY/5", off)
        self.assertNotIn("shell_to_solid", off)
        self.assertTrue(_has(r_off.warnings, "were NOT converted",
                             "--no-shell-to-solid-rbody"))
        self.assertIn("CONSTRAINED_SHELL_TO_SOLID",
                      [k for k, _r in r_off.recognized_not_emitted])

    def test_a_missing_node_set_is_refused_by_name(self):
        r, starter, _e = _convert(_shell_to_solid_deck(nsid=9).replace(
            "*SET_NODE_LIST\n" + _row(9) + "\n" + _row(1, 2, 3) + "\n", ""))
        self.assertNotIn("/RBODY/5", starter)
        self.assertTrue(_has(r.warnings, "node set 9 not found",
                             "tie NOT converted"))

    def test_a_shell_node_with_no_coordinates_is_refused_by_name(self):
        r, starter, _e = _convert(_shell_to_solid_deck(nid=999))
        self.assertNotIn("/RBODY/999", starter)
        self.assertTrue(_has(r.warnings, "the shell node has no coordinates",
                             "tie NOT converted"))

    def test_the_main_node_is_removed_from_its_own_secondary_group(self):
        r, starter, _e = _convert(_shell_to_solid_deck(fibre=(1, 2, 5)))
        blk = _block_after(starter, "/RBODY/5", 4)
        grnod = blk[3].split()[5]
        gblk = _block_after(starter, f"/GRNOD/NODE/{grnod}", 3)
        self.assertEqual(gblk[2].split(), ["1", "2"])
        self.assertTrue(_has(r.warnings, "ALSO a member of the solid node set"))

    def test_a_BCS_on_a_tied_node_predicts_starter_WARNING_312(self):
        r, _s, _e = _convert(_shell_to_solid_deck(tc=7))
        self.assertTrue(_has(r.warnings, "WARNING ID 312",
                             "INCOMPATIBLE KINEMATIC CONDITIONS"))

    def test_the_tied_nodes_keep_their_own_NODE_TC_RC_constraint(self):
        """Registering them in ``rigid_nodes`` DROPPED the deck's own stated
        constraints — measured, 12 of 132 on the dome. They must survive."""
        _r, starter, _e = _convert(_shell_to_solid_deck(tc=7))
        self.assertIn("/BCS/", starter)
        self.assertIn("node_tc_rc_111_000", starter)
        tail = starter.split("node_tc_rc_111_000")[-1]
        self.assertEqual(tail.splitlines()[1].split(), ["1", "5"],
                         "both tied nodes must keep their own TC/RC")

    def test_a_duplicate_RBODY_id_takes_a_fresh_auto_id(self):
        """``/RBODY`` has no allocator — its id IS the main node id, and a
        duplicate is starter ERROR 79."""
        deck = _shell_to_solid_deck(nid=5) + ""
        deck = deck.replace(
            "*CONSTRAINED_SHELL_TO_SOLID\n" + _row(5, 9) + "\n",
            "*CONSTRAINED_SHELL_TO_SOLID\n" + _row(5, 9) + "\n"
            + "*CONSTRAINED_SHELL_TO_SOLID\n" + _row(5, 9) + "\n")
        _r, starter, _e = _convert(deck)
        ids = [ln.split("/")[-1] for ln in starter.splitlines()
               if ln.startswith("/RBODY/")]
        self.assertEqual(len(ids), 2, ids)
        self.assertEqual(len(set(ids)), 2, f"duplicate /RBODY id: {ids}")
        self.assertIn("5", ids)


def _butt_deck(sigy=250.0, length=10.0, depth=2.0, beta=0.9, nsid=21,
               pair=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), members=(21, 33),
               tfail=1e17, epsf=0.3, cid=0):
    pts = {21: pair[0], 33: pair[1],
           1: (10.0, 0.0, 0.0), 2: (10.0, 10.0, 0.0), 3: (0.0, 10.0, 0.0),
           4: (20.0, 0.0, 0.0), 5: (20.0, 10.0, 0.0)}
    nodes = "*NODE\n" + "".join(
        f"{i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
        for i, (x, y, z) in sorted(pts.items()))
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + nodes
            + "*ELEMENT_SHELL\n" + _row(1, 1, 21, 1, 2, 3) + "\n"
            + _row(2, 1, 33, 4, 5, 5) + "\n"
              "*PART\n" "plate\n" + _row(1, 1, 1) + "\n"
              "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
              "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
              "*SET_NODE_LIST\n" + _row(nsid) + "\n" + _row(*members) + "\n"
              "*CONSTRAINED_GENERALIZED_WELD_BUTT\n"
            + _row(nsid, cid, 0, 0, 0, 0) + "\n"
            + _row(tfail, epsf, sigy, beta, length, depth) + "\n"
              "*END\n")


class GeneralizedWeldButtRbody(unittest.TestCase):
    """A3 — one ``/RBODY`` with ``Ifail = 1`` per butt-weld card."""

    def test_the_card_is_registered_with_both_of_its_cards(self):
        st = _dispatch(_butt_deck())
        self.assertNotIn("CONSTRAINED_GENERALIZED_WELD_BUTT",
                         st.skipped_keywords)
        self.assertEqual(len(st.generalized_weld_butts), 1)
        c = st.generalized_weld_butts[0]
        self.assertEqual((c.nsid, c.sigy, c.beta, c.length, c.depth),
                         (21, 250.0, 0.9, 10.0, 2.0))

    def test_FN_equals_FT_equals_SIGY_L_D_over_BETA(self):
        """Hand: 250 x 10 x 2 / 0.9 = 5555.555555... -> _f prints 5555.555556,
        and the starter echoes NORMAL/SHEAR FORCE AT FAILURE 5556."""
        _r, starter, _e = _convert(_butt_deck())
        blk = _block_after(starter, "/RBODY/21", 11)
        self.assertEqual(blk[8], rbody_writer._RBODY_IOPTOFF_HDR)
        self.assertEqual(blk[9].split(), ["0", "0", "1"],
                         "Ifail is the THIRD value of the Ioptoff card")
        self.assertIn("FN", blk[10])
        fn, ft, en, et = starter.splitlines()[
            starter.splitlines().index(blk[10]) + 1].split()
        self.assertEqual(fn, "5555.555556")
        self.assertEqual(ft, fn, "FT = FNmax, not FNmax/sqrt(3)")
        self.assertEqual((en, et), ("2", "2"))

    def test_a_blank_BETA_takes_the_cards_own_default_of_one(self):
        """Hand: 250 x 10 x 2 / 1.0 = 5000."""
        _r, starter, _e = _convert(_butt_deck(beta=0.0))
        blk = _block_after(starter, "/RBODY/21", 12)
        self.assertEqual(blk[11].split(), ["5000", "5000", "2", "2"])

    def test_a_non_coincident_pair_is_refused_by_name(self):
        r, starter, _e = _convert(
            _butt_deck(pair=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))))
        self.assertNotIn("/RBODY/21", starter)
        self.assertTrue(_has(r.warnings, "is NOT coincident",
                             "weld NOT converted", "rgbodv.F:249-256"))

    def test_a_set_that_is_not_a_pair_is_refused_by_name(self):
        for members in ((21,), (21, 33, 1)):
            with self.subTest(members=members):
                r, starter, _e = _convert(_butt_deck(members=members))
                self.assertNotIn("/RBODY/21", starter)
                self.assertTrue(_has(r.warnings, "node(s), and a BUTT weld is "
                                                 "exactly ONE nodal pair"))

    def test_a_weld_with_no_failure_force_becomes_an_unbreakable_tie(self):
        r, starter, _e = _convert(_butt_deck(sigy=0.0))
        blk = _block_after(starter, "/RBODY/21", 10)
        self.assertEqual(blk[9].split(), ["0", "0", "0"])
        self.assertNotIn("expN", "\n".join(blk))
        self.assertTrue(_has(r.warnings, "UNBREAKABLE tie (Ifail 0)"))

    def test_EPSF_TFAIL_and_CID_are_dropped_and_named(self):
        r, _s, _e = _convert(_butt_deck(cid=3))
        self.assertTrue(_has(r.warnings, "EPSF, TFAIL, CID",
                             "have no /RBODY slot and were DROPPED"))

    def test_the_opt_out_is_byte_identical_to_dropping_the_keyword(self):
        deck = _butt_deck()
        _r, on, _e = _convert(deck)
        r_off, off, _e2 = _convert(deck, generalized_weld_butt=False)
        self.assertIn("/RBODY/21", on)
        self.assertNotIn("/RBODY/21", off)
        self.assertNotIn("gen_weld_butt", off)
        self.assertTrue(_has(r_off.warnings, "were NOT converted",
                             "--no-generalized-weld-butt"))


class Round5FlagWiring(unittest.TestCase):
    """Every new lever reaches the parser, the API, the GUI and the README."""

    #: default-ON opt-outs: the spelling the README and the GUI summary carry
    #: is the ``--no-`` one.
    _FLAGS = {
        "--shell-to-solid-rbody": "shell_to_solid_rbody",
        "--generalized-weld-butt": "generalized_weld_butt",
    }
    #: part B's default-OFF levers: ``(option, attribute, the GUI value that
    #: turns it on)``. Every one of the five is checked at the same five
    #: sites; a lever wired everywhere but the summary ships silently.
    _OPT_IN_FLAGS = (
        ("--implicit-rigid-secondary-swap",
         "implicit_rigid_secondary_swap", True),
        ("--mass-weighted-inivel", "mass_weighted_inivel", True),
        ("--assumed-strain-isolid", "assumed_strain_isolid", "24"),
    )

    def _readme(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_every_round_5_flag_reaches_the_README(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        readme = self._readme()
        for flag in self._FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts, f"{flag} is not a parser option")
                neg = "--no-" + flag[2:]
                self.assertIn(neg, opts, f"{neg} is not a parser option")
                self.assertIn(neg, readme, f"{neg} is not in README.md")
        for flag, _attr, _on in self._OPT_IN_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts, f"{flag} is not a parser option")
                self.assertIn(flag, readme, f"{flag} is not in README.md")

    def test_every_round_5_flag_has_its_OWN_README_SECTION(self):
        """``assertIn(flag, readme)`` is presence-only, and a flag's whole
        ``### `--flag``` section can be renamed away while the table-of-contents
        link still carries the string — a mutation that renamed the
        ``--mass-weighted-inivel`` heading left the suite green.

        So assert the HEADING, and that the TOC anchor still resolves to a
        heading that exists.
        """
        readme = self._readme()
        headings = re.findall(r"^#{2,4}\s+(.*)$", readme, re.M)
        anchors = set()
        for h in headings:
            slug = re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
            anchors.add(slug)

        # The three OPT-IN levers each own a `###` section a user tunes from.
        for flag, _attr, _on in self._OPT_IN_FLAGS:
            with self.subTest(flag=flag, kind="heading"):
                self.assertTrue(
                    any(flag in h for h in headings),
                    f"{flag} has no `### `{flag}`` section of its own in "
                    f"README.md (presence in a TOC link is not a section)")

        # The default-ON opt-outs are documented as bullets in the keyword
        # coverage list, so what has to hold for them is weaker but still real:
        # the flag must appear on a line that is NOT just a table-of-contents
        # link. That is the mutation this test exists for — renaming a section
        # away while the TOC entry keeps the string alive.
        body = [ln for ln in readme.splitlines()
                if not re.match(r"^\s*[-*]?\s*\[.*\]\(#.*\)\s*$", ln)]
        for flag in [("--no-" + f[2:]) for f in self._FLAGS]:
            with self.subTest(flag=flag, kind="body"):
                self.assertTrue(
                    any(flag in ln for ln in body),
                    f"{flag} appears in README.md only inside a "
                    f"table-of-contents link, not in any prose")

        # every in-page TOC link must point at a heading that exists
        for target in re.findall(r"\]\(#([a-z0-9-]+)\)", readme):
            with self.subTest(anchor=target):
                self.assertIn(target, anchors,
                              f"README.md links to #{target}, which is no "
                              f"heading in the file")

    def test_the_help_renders_and_carries_the_measured_numbers(self):
        """A bare %% in a help string kills --help at a green suite."""
        from k2rad import cli
        text = cli.build_parser().format_help()
        for flag in self._FLAGS:
            self.assertIn("--no-" + flag[2:], text)
        for flag, _attr, _on in self._OPT_IN_FLAGS:
            self.assertIn(flag, text)
        # argparse WRAPS a help string, so the figures are matched against the
        # whitespace-collapsed render — the sentence the user reads.
        flat = _collapse(text)
        for figure in ("48190 cycles", "2082 cycles", "131 cycles",
                       "6.934e5", "220.58", "189.962", "-5.87 %",
                       "22 deck keys on 18 emitted models"):
            with self.subTest(figure=figure):
                self.assertIn(figure, flat)

    def test_the_gui_wires_both_levers_end_to_end(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for name in self._FLAGS.values():
            with self.subTest(name=name):
                kw = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="",
                    **{name: False})
                self.assertIs(kw[name], False)
                captured = []
                app = k2rad_gui.ConverterGUI.__new__(
                    k2rad_gui.ConverterGUI)   # no Tk root needed
                app._append = captured.append
                k2rad_gui.ConverterGUI._describe_options(app, kw)
                self.assertIn("--no-" + name.replace("_", "-"),
                              "".join(captured))
        tmp.cleanup()

    def test_the_gui_wires_the_three_opt_in_levers_end_to_end(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for flag, name, on in self._OPT_IN_FLAGS:
            with self.subTest(name=name):
                kw = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="",
                    **{name: on})
                self.assertEqual(kw[name], on)
                captured = []
                app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
                app._append = captured.append
                k2rad_gui.ConverterGUI._describe_options(app, kw)
                self.assertIn(flag, "".join(captured))
                # ... and the default arm says NOTHING about it
                kw_off = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="")
                captured_off = []
                app._append = captured_off.append
                k2rad_gui.ConverterGUI._describe_options(app, kw_off)
                self.assertNotIn(flag, "".join(captured_off))
        tmp.cleanup()

    def test_the_gui_refuses_an_unknown_assumed_strain_value(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        with self.assertRaises(ValueError):
            k2rad_gui.build_convert_kwargs(
                path, "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="", soften_stfac_text="",
                assumed_strain_isolid="18")
        tmp.cleanup()

    def test_every_new_lever_reaches_convert_and_ConvertOptions(self):
        """The 13-site checklist's API half: a flag the parser owns but
        ``convert()`` does not is a flag that silently does nothing."""
        from k2rad import convert
        from k2rad.state import ConvertOptions
        sig = inspect.signature(convert).parameters
        fields = {f for f in ConvertOptions.__dataclass_fields__}
        names = ([n for n in self._FLAGS.values()]
                 + [n for _f, n, _o in self._OPT_IN_FLAGS])
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, sig)
                self.assertIn(name, fields)

    def test_both_keywords_carry_an_include_transform_offset_spec(self):
        """Both cards hold node/set ids, so an *INCLUDE_TRANSFORM renumber
        must reach them."""
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("CONSTRAINED_SHELL_TO_SOLID",
                   "CONSTRAINED_GENERALIZED_WELD_BUTT"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)
                self.assertIn(kw, HANDLERS)


# ── A5: *CONSTRAINED_JOINT_SCREW is NOT implemented this round ───────────────

class JointScrewIsStillRefused(unittest.TestCase):
    """A5 — the ``/GJOINT/RACK`` arm missed both acceptance gates (energy
    error ≤ 5 %: best −25.6 %; nut travel within 2 % of LS-DYNA's +183.72 mm:
    best −324.4 mm), so the keyword is NOT converted this round and the
    numbers are recorded in ROADMAP.md. What is pinned here is that it is
    still REFUSED rather than silently read as some other joint.
    """

    def test_the_keyword_is_not_registered(self):
        self.assertNotIn("CONSTRAINED_JOINT_SCREW", HANDLERS)

    def test_it_lands_in_skipped_keywords_rather_than_another_joint(self):
        deck = ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{float(i):>16.4f}{0.0:>16.4f}{0.0:>16.4f}\n"
                          for i in (1, 2, 3, 4))
                + "*CONSTRAINED_JOINT_SCREW\n"
                + _row(1, 2, 3, 4, 0, 0) + "\n"
                + _row(25.0) + "\n"
                  "*END\n")
        st = _dispatch(deck)
        self.assertIn("CONSTRAINED_JOINT_SCREW", st.skipped_keywords)
        self.assertEqual(st.constrained_joints, [])


# ═════════════════════════════════════════════════════════════════════════════
# PART B — opt-in levers, hygiene, docs
# ═════════════════════════════════════════════════════════════════════════════

# ── the shipped-text guard, shared by every retracted-figure test below ──────

def _collapse(text: str) -> str:
    """One space per whitespace run — so a sentence split across source lines
    reads as the one sentence a user sees."""
    return re.sub(r"\s+", " ", text)


def _SHIPPED_TEXTS():
    """``(relative path, normalized text)`` for every text a figure can ship in.

    Round 4's own convention (``test_r14_triage_4._STATING_DOCS`` plus the
    whole package and the GUI): the two DOCS a user reads, every module of the
    package — a default-ON runtime warning is shipped text too — and the GUI.
    ``CHANGELOG.md`` is excluded on purpose: it is the historical record of
    what each round shipped, not a claim about the current code.

    Adjacent string literals are JOINED before the whitespace collapses, so a
    figure split across two literals is one string here, exactly as it is in
    the message the user sees.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rels = ["README.md", "ROADMAP.md", "k2rad_gui.py"]
    for dirpath, _dirs, files in os.walk(os.path.join(root, "k2rad")):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                rels.append(os.path.relpath(
                    os.path.join(dirpath, name), root))
    out = []
    for rel in rels:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):        # a measurement, not an assumption
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        out.append((rel, _collapse(re.sub(r'"\s*\n\s*"', "", text))))
    assert len(out) >= 10, out
    return out


#: B3's three corrected claims, in every spelling they were ever written in.
_RETRACTED_B3 = (
    "-5.75 / -5.18 / -6.27",
    "−5.75 / −5.18 / −6.27",
    "-5.75/-5.18/-6.27",
    "Refine through the thickness",
    "refine through the thickness",
)

# ── B4: a solid stored with six node ids ─────────────────────────────────────

def _solid_row(*vals) -> str:
    """One ``*ELEMENT_SOLID`` card row (eight-column fields)."""
    return "".join(f"{v:>8}" for v in vals)


def _solid_deck(*rows: str, elform: int = 1) -> str:
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n"
            + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                      for i, (x, y, z) in enumerate(
                          [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                           (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10),
                           (5, 5, 20)], start=1))
            + "*ELEMENT_SOLID\n" + "".join(r + "\n" for r in rows)
            + "*PART\n"
              "block\n" + _row(1, 1, 1) + "\n"
              "*SECTION_SOLID\n" + _row(1, elform) + "\n"
              "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
              "*END\n")


class ShortCardSolidIsNotPaddedWithItsLastNode(unittest.TestCase):
    """B4 — a solid the deck stored with SIX node ids used to be padded with
    its last node, which the reader takes as a HEXAHEDRON over the wrong
    bottom face.

    MEASURED on ``tests/fixtures/wedge_short_card.k`` with OpenRadioss
    20260520 at nt 4 (a 10 x 10 x 10 mm block as two wedges, rho 7.85e-9, so
    the exact mass is 7.85e-6): the padded rows read starter ``TOTAL MASS``
    **3.9250E-06** — half the block — with the mass centre at (5, 6.25, 6.25),
    at 0 ERROR and 0 WARNING. The collapsed spelling this now emits reads
    **7.8500E-06** and (5, 6.25, 5), 0 ERROR / 0 WARNING / NORMAL TERMINATION,
    and is byte-identical to what the eight-column twin
    ``wedge_collapsed_card.k`` produces.

    The reader's OWN six-cell ``/PENTA6`` form is not used: it is accepted
    only on a property at ``Isolid = 24`` (starter ``ERROR ID : 3107`` on this
    coupon's ``Isolid`` 1; the same file with the cell hand-set to 24 runs and
    lumps the mass centre to an exact (5, 5, 5)).

    REACH: 0 roster decks — a six-field ``*ELEMENT_SOLID`` card is not an
    LS-DYNA spelling (Vol I R17 p.19-124) and the corpus has none.
    """

    def _bricks(self, *rows, **kw):
        _, starter, _ = _convert(_solid_deck(*rows, **kw))
        head = starter.index("/BRICK/1")
        block = starter[head:].split("#---", 1)[0].splitlines()
        return [ln for ln in block[1:] if ln.strip()]

    def test_a_six_id_solid_becomes_the_collapsed_pentahedron(self):
        rows = self._bricks(_solid_row(1, 1, 1, 2, 3, 5, 6, 7))
        self.assertEqual(len(rows), 1)
        self.assertEqual([int(rows[0][i:i + 10]) for i in range(10, 90, 10)],
                         [1, 2, 3, 3, 5, 6, 7, 7])

    def test_it_is_NOT_padded_with_the_last_node(self):
        """The shipped defect, pinned as its own assertion."""
        rows = self._bricks(_solid_row(1, 1, 1, 2, 3, 5, 6, 7))
        self.assertNotEqual([int(rows[0][i:i + 10]) for i in range(10, 90, 10)],
                            [1, 2, 3, 5, 6, 7, 7, 7])

    def test_cells_7_and_8_are_never_left_blank(self):
        """A native /PENTA6 needs Isolid 24 (ERROR 3107), which this part is
        not at — so the row must stay eight cells wide."""
        rows = self._bricks(_solid_row(1, 1, 1, 2, 3, 5, 6, 7))
        self.assertEqual(len(rows[0].rstrip()), 90)

    def test_the_two_spellings_produce_the_same_row(self):
        short = self._bricks(_solid_row(1, 1, 1, 2, 3, 5, 6, 7))
        full = self._bricks(_solid_row(1, 1, 1, 2, 3, 3, 5, 6, 7, 7))
        self.assertEqual(short, full)

    def test_a_five_id_pyramid_keeps_the_padded_form(self):
        """A pyramid has no ISOLNOD of its own; padding with the apex IS the
        degenerate-hex spelling for one."""
        rows = self._bricks(_solid_row(1, 1, 1, 2, 3, 4, 9))
        self.assertEqual([int(rows[0][i:i + 10]) for i in range(10, 90, 10)],
                         [1, 2, 3, 4, 9, 9, 9, 9])

    def test_a_seven_id_solid_keeps_the_padded_form(self):
        rows = self._bricks(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7))
        self.assertEqual([int(rows[0][i:i + 10]) for i in range(10, 90, 10)],
                         [1, 2, 3, 4, 5, 6, 7, 7])

    def test_a_six_id_solid_with_a_repeated_id_keeps_the_padded_form(self):
        """Already degenerate: the intended shape cannot be read off the row."""
        rows = self._bricks(_solid_row(1, 1, 1, 2, 3, 5, 6, 6))
        self.assertEqual([int(rows[0][i:i + 10]) for i in range(10, 90, 10)],
                         [1, 2, 3, 5, 6, 6, 6, 6])

    def test_a_four_id_solid_never_reaches_the_brick_emitter(self):
        _, starter, _ = _convert(_solid_deck(_solid_row(1, 1, 1, 2, 3, 5)))
        self.assertIn("/TETRA4/1", starter)
        self.assertNotIn("/BRICK/1", starter)

    def test_the_element_is_still_registered_for_TH_BRIC(self):
        deck = _solid_deck(_solid_row(1, 1, 1, 2, 3, 5, 6, 7))
        st = _dispatch(deck)
        self.assertEqual([len(e.nodes) for e in st.solid_elems], [6])
        _, starter, _ = _convert(deck)
        self.assertIn("/BRICK/1", starter)

    def test_one_warning_per_part_naming_the_measured_mass(self):
        res, _, _ = _convert(_solid_deck(_solid_row(1, 1, 1, 2, 3, 5, 6, 7),
                                         _solid_row(2, 1, 1, 3, 4, 5, 7, 8)))
        hits = [w for w in res.warnings if "SIX node ids" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("2 solid element(s)", hits[0])
        self.assertIn("3.9250E-06", hits[0])
        self.assertIn("7.8500E-06", hits[0])
        self.assertIn("ERROR 3107", hits[0])

    def test_a_full_eight_id_hex_warns_about_nothing(self):
        res, _, _ = _convert(_solid_deck(
            _solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8)))
        self.assertFalse([w for w in res.warnings if "SIX node ids" in w])

    def test_the_thick_shell_branch_still_writes_its_collapsed_eight(self):
        """*ELEMENT_TSHELL keeps the verbatim eight-cell row — written with
        trailing zeros it would be classified ISOLNOD=6 and refused on any
        thick-shell property with Isolid != 15 (ERROR 639)."""
        deck = ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                          for i, (x, y, z) in enumerate(
                              [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                               (0, 0, 1), (10, 0, 1), (10, 10, 1), (0, 10, 1)],
                              start=1))
                + "*ELEMENT_TSHELL\n"
                + _solid_row(1, 1, 1, 2, 3, 3, 5, 6, 7, 7) + "\n"
                  "*PART\n"
                  "tsh\n" + _row(1, 1, 1) + "\n"
                  "*SECTION_TSHELL\n" + _row(1, 2) + "\n"
                  "*MAT_ELASTIC\n"
                + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                  "*END\n")
        _, starter, _ = _convert(deck)
        row = _block_after(starter, "/BRICK/1", 2)[1]
        self.assertEqual([int(row[i:i + 10]) for i in range(10, 90, 10)],
                         [1, 2, 3, 3, 5, 6, 7, 7])


# ── B3: --assumed-strain-isolid {24,none} ────────────────────────────────────

def _isolid_of(starter: str, index: int = 0) -> int:
    lines = starter.splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.startswith("/PROP/SOLID/")]
    return int(lines[hits[index] + 3].split()[0])


def _h_cell_of(starter: str, index: int = 0) -> str:
    lines = starter.splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.startswith("/PROP/SOLID/")]
    return lines[hits[index] + 5][40:60].strip()


class AssumedStrainIsolidFlag(unittest.TestCase):
    """B3 — ``--assumed-strain-isolid 24`` puts LS-DYNA's assumed-strain
    ELFORM -1/-2 on Isolid 24 (HEPH) instead of the locking Isolid 17.

    MEASURED at this branch's head on
    ``ex_03_solid_elform_-1_4x6x4_mesh`` (nt 4, reproduced identically at
    nt 2) against its own LS-DYNA reference 174114: Isolid 17 → 136300
    (−21.72 %), **24 → 163900 (−5.87 %)**, 18 → 165000 (−5.23 %), 14 →
    163100 (−6.33 %). The starter echoes ``SOLID FORMULATION FLAG. = 24``.

    Reach 22 deck keys on 18 emitted models; the flag moves 20 on 17,
    because ``ex_12_solid_elform_{-1,-2}`` already reaches 24 through its own
    ``*HOURGLASS`` IHQ 6 overlay — verified byte-identical with and without
    the flag on the real deck.
    """

    def test_minus_1_and_minus_2_move_to_24(self):
        for elform in (-1, -2):
            with self.subTest(elform=elform):
                _, off, _ = _convert(_solid_deck(
                    _solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8), elform=elform))
                _, on, _ = _convert(
                    _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8),
                                elform=elform),
                    assumed_strain_isolid="24")
                self.assertEqual(_isolid_of(off), 17)
                self.assertEqual(_isolid_of(on), 24)

    def test_elform_2_and_3_are_NOT_touched(self):
        """2 is the fully-integrated element 17 reproduces; 3 is the quadratic
        hex, for which no Radioss Isolid exists."""
        for elform in (2, 3):
            with self.subTest(elform=elform):
                _, on, _ = _convert(
                    _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8),
                                elform=elform),
                    assumed_strain_isolid="24")
                self.assertEqual(_isolid_of(on), 17)

    def test_the_h_cell_carries_LS_DYNAs_own_default_QH(self):
        _, on, _ = _convert(
            _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8), elform=-1),
            assumed_strain_isolid="24")
        self.assertEqual(_h_cell_of(on), "0.1")

    def test_a_stated_hourglass_coefficient_still_wins(self):
        deck = _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8),
                           elform=-1).replace(
            "*PART\n", "*CONTROL_HOURGLASS\n" + _row(6, 0.07) + "\n*PART\n")
        _, on, _ = _convert(deck, assumed_strain_isolid="24")
        self.assertEqual(_isolid_of(on), 24)
        self.assertEqual(_h_cell_of(on), "0.07")

    def test_the_flag_off_arm_is_byte_identical(self):
        deck = _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8), elform=-1)
        _, a, ea = _convert(deck)
        _, b, eb = _convert(deck, assumed_strain_isolid="none")
        self.assertEqual(a, b)
        self.assertEqual(ea, eb)

    def test_the_PER_PART_hourglass_split_property_honours_it(self):
        """ex_27_solid_elform_-2_rigidwall's own shape: the split
        /PROP/SOLID is the ONLY solid property in the file."""
        deck = _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8),
                           elform=-2).replace(
            "*PART\nblock\n" + _row(1, 1, 1) + "\n",
            "*HOURGLASS\n" + _row(7, 0, 0.0) + "\n"
            "*PART\nblock\n" + _row(1, 1, 1, 0, 7) + "\n")
        _, off, _ = _convert(deck)
        _, on, _ = _convert(deck, assumed_strain_isolid="24")
        self.assertIn("HG_PROP_", off)
        self.assertEqual(_isolid_of(off), 17)
        self.assertEqual(_isolid_of(on), 24)

    def test_the_effective_isolid_predicate_reports_24(self):
        """The predicate /INIBRI and /FAIL/TAB1 read must not disagree with
        the property that was written."""
        from k2rad.writer.mesh import _effective_solid_isolid
        deck = _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8), elform=-1)
        for value, want in (("none", 17), ("24", 24)):
            with self.subTest(value=value):
                st = _dispatch(deck)
                st.options.assumed_strain_isolid = value
                sec = st.sec_solids[1]
                self.assertEqual(_effective_solid_isolid(st, 1, sec), want)

    def _tab1_deck(self, elform: int) -> str:
        """A ``*MAT_TABULATED_JOHNSON_COOK`` (224) → ``/FAIL/TAB1`` deck with
        ``NUMINT = 8``, the shape ``tests/test_tabulated_jc.py`` uses for the
        8-of-8 rule. The probe has to REACH that branch, so it is built from
        the keyword that really carries ``NUMINT`` into ``/FAIL/TAB1``."""
        nodes = "".join(
            f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
            for i, (x, y, z) in enumerate(
                [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                 (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)], start=1))
        return ("*KEYWORD\n*NODE\n" + nodes
                + "*ELEMENT_SOLID\n" + _row(1, 7) + "\n"
                + _row(*range(1, 9)) + "\n"
                + "*PART\njc part\n" + _row(7, 7, 7) + "\n"
                + "*SECTION_SOLID\n" + _row(7, elform) + "\n"
                + "*MAT_TABULATED_JOHNSON_COOK\n"
                + _row(7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 8) + "\n"
                + _row(110, 0, 300, 0, 0, 0) + "\n"
                + "*DEFINE_CURVE\n" + _row(110) + "\n"
                + f"{0.0:>20}{350.0:>20}\n{0.5:>20}{500.0:>20}\n"
                + "*DEFINE_CURVE\n" + _row(300) + "\n"
                + f"{-0.667:>20}{1.2:>20}\n{0.333:>20}{0.3:>20}\n"
                + "*END\n")

    def test_a_FAIL_TAB1_deck_loses_its_exact_8_of_8_rule_and_says_so(self):
        """The second, non-obvious effect: ``_exact_all_ip`` gates
        ``Ifail_so = 2`` (delete when ALL integration points fail) on the
        element really having 8 of them, so moving an ELFORM -1 part to the
        ONE-point Isolid 24 takes that exactness away — and the deck erodes
        on the FIRST failed point instead."""
        deck = self._tab1_deck(-1)
        res_off, off, _ = _convert(deck)
        res_on, on, _ = _convert(deck, assumed_strain_isolid="24")
        # the probe REACHES the branch: the 8-of-8 rule really is in effect
        self.assertTrue(any("exactly LS-DYNA's 8-of-8 rule" in w
                            for w in res_off.warnings), res_off.warnings)
        self.assertIn("/FAIL/TAB1/7", off)
        tab1_off = [ln for ln in off.split("/FAIL/TAB1/7")[1].splitlines()
                    if ln and not ln.startswith("#")]
        tab1_on = [ln for ln in on.split("/FAIL/TAB1/7")[1].splitlines()
                   if ln and not ln.startswith("#")]
        self.assertEqual(int(tab1_off[0][10:20]), 2)     # Ifail_so = 2
        self.assertEqual(int(tab1_on[0][10:20]), 1)      # ... and now 1
        self.assertFalse(any("exactly LS-DYNA's 8-of-8 rule" in w
                             for w in res_on.warnings), res_on.warnings)
        self.assertTrue(any("erode EARLIER" in w for w in res_on.warnings))
        self.assertTrue(any("--assumed-strain-isolid 24" in w
                            for w in res_on.warnings), res_on.warnings)

    def test_an_ELFORM_2_FAIL_TAB1_deck_keeps_its_8_of_8_rule(self):
        """The control: the flag must not reach ELFORM 2."""
        deck = self._tab1_deck(2)
        res_on, _s, _e = _convert(deck, assumed_strain_isolid="24")
        self.assertTrue(any("exactly LS-DYNA's 8-of-8 rule" in w
                            for w in res_on.warnings), res_on.warnings)
        self.assertFalse(any("--assumed-strain-isolid" in w
                             for w in res_on.warnings), res_on.warnings)

    def test_an_unknown_value_is_refused_rather_than_written(self):
        from k2rad.state import ConvertOptions
        for bad in ("18", "14", "17", "", "true", "yes", "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ConvertOptions(assumed_strain_isolid=bad)
        self.assertEqual(
            ConvertOptions(assumed_strain_isolid="none")
            .assumed_strain_isolid_value, 0)
        self.assertEqual(
            ConvertOptions(assumed_strain_isolid="24")
            .assumed_strain_isolid_value, 24)
        # whitespace is tolerated by BOTH the check and the reader, so a
        # padded value can never be accepted by one and ignored by the other
        self.assertEqual(
            ConvertOptions(assumed_strain_isolid=" 24 ")
            .assumed_strain_isolid_value, 24)

    def test_the_24_arm_gets_its_own_warning_naming_the_flag(self):
        res, _s, _e = _convert(
            _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8), elform=-1),
            assumed_strain_isolid="24")
        hits = [w for w in res.warnings if "ASSUMED-STRAIN" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("--assumed-strain-isolid 24 was passed", hits[0])
        self.assertIn("SMALLEST", hits[0])
        self.assertIn("-2.9 %", hits[0])

    def test_the_17_warning_carries_the_re_measured_figures(self):
        res, _s, _e = _convert(
            _solid_deck(_solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8), elform=-1))
        hit = next(w for w in res.warnings if "ASSUMED-STRAIN" in w)
        for figure in ("-5.87 / -5.23 / -6.33 %", "163900 / 165000 / 163100",
                       "174114", "22 deck keys on 18 emitted models",
                       "19 of them on 16 models",
                       "convertprops.cxx:398-402",
                       "REFINE ALONG THE BEAM",
                       "+19.7 % -> -28.8 %"):
            with self.subTest(figure=figure):
                self.assertIn(figure, hit)

    def test_the_retracted_figures_are_gone_from_every_shipped_text(self):
        """A rename is a prefix: the guard matches the JOINED, whitespace-
        collapsed text of every shipped file, so a string split across two
        adjacent literals cannot hide.

        ``CHANGELOG.md`` is deliberately NOT scanned — round 4's own
        ``_STATING_DOCS`` convention. It is a historical record of what each
        round shipped, and deleting a figure from a past entry would rewrite
        that history; the round-4 entry instead carries an in-place
        ``re-measured in round 5`` note beside its own number, and
        :meth:`test_the_changelog_records_the_re_measurement` pins it.
        """
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_B3:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle), joined)

    def test_each_retracted_spelling_is_one_the_guard_can_see(self):
        """The companion the #137 rule asks for: feed the guard each retracted
        string on its own, in the shape a source file would carry it — split
        across two adjacent literals, with the space kept INSIDE the first one
        — and prove the guard FIRES. A guard that silently matches nothing
        cannot pass for a clean one."""
        for needle in _RETRACTED_B3:
            with self.subTest(needle=needle):
                fake = ('some shipped sentence '
                        + needle.replace(" ", ' "\n            "')
                        + ' and the rest')
                self.assertIn(_collapse(needle), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)))

    def test_the_changelog_records_the_re_measurement(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("re-measured in round 5", text)
        self.assertIn("−5.87 / −5.23 / −6.33", text)


# ── B1: --implicit-rigid-secondary-swap ──────────────────────────────────────

def _implicit_rigid_ssid_deck(main_solid: bool = True) -> str:
    """An IMPLICIT deck whose *CONTACT SSID side is a wholly RIGID part and
    whose MSID side is deformable — ``bumper``'s shape, in miniature.

    *main_solid* False makes the side that BECOMES the main surface a SHELL
    part, so no Gapmin can be derived for it: the refusal arm.
    """
    nodes = "".join(
        f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
        for i, (x, y, z) in enumerate(
            [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
             (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10),
             (0, 0, 20), (10, 0, 20), (10, 10, 20), (0, 10, 20),
             (0, 0, 30), (10, 0, 30), (10, 10, 30), (0, 10, 30)], start=1))
    rigid = ("*ELEMENT_SOLID\n" + _solid_row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8)
             + "\n" if main_solid else
             "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n")
    rigid_sec = ("*SECTION_SOLID\n" + _row(1, 1) + "\n" if main_solid else
                 "*SECTION_SHELL\n" + _row(1, 2) + "\n"
                 + _row(1.0, 1.0, 1.0, 1.0) + "\n")
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(0.05) + "\n"
            "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
            "*NODE\n" + nodes
            + rigid
            + "*ELEMENT_SOLID\n"
            + _solid_row(2, 2, 9, 10, 11, 12, 13, 14, 15, 16) + "\n"
            + "*PART\nrigid platen\n" + _row(1, 1, 1) + "\n"
            + "deformable block\n" + _row(2, 2, 2) + "\n"
            + rigid_sec
            + "*SECTION_SOLID\n" + _row(2, 1) + "\n"
            + "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            + _row(0, 7, 7) + "\n" + _row(0, 0, 0) + "\n"
            + "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
            + "*CONTACT_SURFACE_TO_SURFACE\n"
            + _row(1, 2, 3, 3) + "\n" + _row(0.2, 0.2) + "\n"
            + "*END\n")


class ImplicitRigidSecondarySwap(unittest.TestCase):
    """B1 — on an IMPLICIT deck an all-rigid SSID contact is DROPPED;
    ``--implicit-rigid-secondary-swap`` swaps it instead, with the derived
    Gapmin the swap needs.

    MEASURED on ``implicit/basic-examples/contact-i/bumper.k`` at nt 4 AND
    nt 2 (identical on both), against the LS-DYNA reference IE 1.23131e7:

    ==========================================  =========================
    arm                                         result
    ==========================================  =========================
    shipped drop                                NORMAL 502 cycles, IE 0
    bare swap (Gapmin hand-set back to 0)       ERROR at t = 3.0e-4
    swap + derived Gapmin 0.1499, Inacti 0      NORMAL 131 cycles,
                                                IE 6.934e5 (−94.4 %)
    the same with /IMPL/QSTAT/DTSCAL 1          IE 1.473e6 (−88.0 %)
    the recipe's DTSCAL 0.05, hand-set          IE −7.418e5, NEGATIVE
    ==========================================  =========================

    Starter: 0 ERROR on both arms (1 → 2 WARNING, both ID 1084, the deck's
    own). The campaign VERDICT cannot move — bumper's LS-DYNA KE is exactly 0,
    a structural zero the benchmark short-circuits on.
    """

    def test_the_default_is_still_the_drop(self):
        res, starter, _e = _convert(_implicit_rigid_ssid_deck())
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertTrue(_has(res.warnings, "NO /INTER was emitted"),
                        res.warnings)

    def test_the_flag_emits_the_swapped_interface_with_a_derived_gapmin(self):
        res, starter, _e = _convert(_implicit_rigid_ssid_deck(),
                                    implicit_rigid_secondary_swap=True)
        self.assertIn("/INTER/TYPE7/", starter)
        self.assertTrue(_has(res.warnings, "the roles are SWAPPED instead"),
                        res.warnings)
        self.assertTrue(
            _has(res.warnings, "IMPLIED the derived Gapmin"), res.warnings)
        block = _block_after(starter, "/INTER/TYPE7/", 40)
        i = next(j for j, ln in enumerate(block) if "Gapmin" in ln)
        self.assertGreater(float(block[i + 1][40:60]), 0.0)

    def test_the_flag_is_a_no_op_with_the_explicit_swap_turned_off(self):
        """``--no-rigid-secondary-swap`` disarms it: it is the same exchange."""
        _r, a, _e = _convert(_implicit_rigid_ssid_deck(),
                             implicit_rigid_secondary_swap=True,
                             rigid_secondary_swap=False)
        self.assertNotIn("/INTER/TYPE7/", a)

    def test_an_EXPLICIT_deck_is_untouched_by_the_flag(self):
        deck = _implicit_rigid_ssid_deck().replace(
            "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n", "")
        _r, off, _e = _convert(deck)
        _r2, on, _e2 = _convert(deck, implicit_rigid_secondary_swap=True)
        self.assertIn("/INTER/TYPE7/", off)      # the explicit swap already
        self.assertEqual(off, on)

    def test_the_swap_is_REFUSED_when_no_gapmin_can_be_derived(self):
        """The flag implies the derived Gapmin and refuses to swap without
        one — the bare swap is measured to ERROR."""
        res, starter, _e = _convert(_implicit_rigid_ssid_deck(main_solid=False),
                                    implicit_rigid_secondary_swap=True)
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertTrue(_has(res.warnings, "the swap was REFUSED"),
                        res.warnings)
        self.assertTrue(_has(res.warnings, "t = 3.0e-4"), res.warnings)

    def test_the_flag_off_arm_is_byte_identical(self):
        deck = _implicit_rigid_ssid_deck()
        _r, a, ea = _convert(deck)
        _r2, b, eb = _convert(deck, implicit_rigid_secondary_swap=False)
        self.assertEqual(a, b)
        self.assertEqual(ea, eb)

    def test_the_deformable_contact_recipe_is_NOT_widened(self):
        """``_recipe_active`` and the recipe's interface set must not change
        with the flag — its DTSCAL 0.05 drives this class NEGATIVE."""
        from k2rad.writer.contacts import (_recipe_active,
                                           deformable_deformable_inter_ids)
        deck = _implicit_rigid_ssid_deck()
        for flag in (False, True):
            with self.subTest(flag=flag):
                st = _dispatch(deck)
                st.options.implicit_rigid_secondary_swap = flag
                st.options.deformable_contact_recipe = True
                # the interface is rigid-vs-deformable, so it is not in the
                # recipe's set and the recipe does not arm -- with the flag
                # ON as well as off. That IS the claim: the flag creates a
                # contact the recipe still does not reach.
                self.assertEqual(sorted(deformable_deformable_inter_ids(st)),
                                 [])
                self.assertFalse(_recipe_active(st))

    def test_only_the_TYPE7_route_can_take_the_flag(self):
        """The `gapmin_route` gate, probed on the plan function itself.

        The swap is inseparable from the derived Gapmin, and the two routes
        that have no Gapmin cell — the `SOFT=-7` sentinel (`Igap 2`, an
        element-derived gap) and `/INTER/TYPE25` — must keep the drop however
        the flag is set. Their measured reach for an all-rigid secondary on
        every corpus here is 0 interfaces, so this is the probe that reaches
        the branch: the same state, the same sides, one argument apart.
        """
        from k2rad.writer.contacts import (_RS_IMPLICIT, _RS_IMPLICIT_SWAP,
                                           _rigid_secondary_plan)
        from k2rad.writer.common import rigid_part_ids
        st = _dispatch(_implicit_rigid_ssid_deck())
        st.options.implicit_rigid_secondary_swap = True
        rigid_parts = rigid_part_ids(st)
        rigid_nodes = {n for e in st.solid_elems if e.pid in rigid_parts
                       for n in e.nodes if n > 0}
        c = st.contacts_surf2surf[0]
        plan7, _s, _m = _rigid_secondary_plan(
            st, rigid_nodes, c.ssid, c.sstyp, c.msid, c.mstyp,
            gapmin_route=True)
        plan_other, _s2, _m2 = _rigid_secondary_plan(
            st, rigid_nodes, c.ssid, c.sstyp, c.msid, c.mstyp)
        self.assertEqual(plan7, _RS_IMPLICIT_SWAP)
        self.assertEqual(plan_other, _RS_IMPLICIT)

    def test_exactly_one_call_site_passes_the_gapmin_route(self):
        """...and it is the plain /INTER/TYPE7 one. A second site quietly
        opting in would give a route with no Gapmin cell a swap that is
        measured to ERROR without one."""
        import k2rad.writer.contacts as cw
        src = inspect.getsource(cw)
        self.assertEqual(src.count("gapmin_route=True"), 1)
        self.assertEqual(src.count("_rigid_secondary_plan("), 4)

    def test_the_drop_message_names_the_flag_only_where_it_can_reach(self):
        """A named control must reach the branch it controls: the TYPE25 and
        SOFT=-7 routes have no Gapmin cell, so neither is told to pass a flag
        that would do nothing for them."""
        from k2rad.writer.contacts import _implicit_rigid_secondary_note
        st = _dispatch("*KEYWORD\n*END\n")
        self.assertIn("Pass --implicit-rigid-secondary-swap",
                      _implicit_rigid_secondary_note(st))
        other = _implicit_rigid_secondary_note(st, gapmin_route=False)
        self.assertIn("does NOT reach this interface", other)
        self.assertNotIn("Pass --implicit-rigid-secondary-swap", other)

    def test_the_retracted_every_arm_diverges_claim_is_gone(self):
        retracted = ("every restoration arm measured on implicit",
                     "EVERY arm that restores the load path diverges",
                     "with an explicit Gapmin of 0.14986 it reaches")
        for rel, joined in _SHIPPED_TEXTS():
            for needle in retracted:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle), joined)


# ── B2: --mass-weighted-inivel ───────────────────────────────────────────────

class MomentumAverageArithmetic(unittest.TestCase):
    """B2's arithmetic, on its own: ``lumping.rigid_body_momentum_velocity``.

    Vol I R17 p.28-129 Remark 3 computes the body's momentum from the
    PRESCRIBED nodal velocities over the WHOLE body's mass, which is what
    makes the average smaller than the card's own velocity.
    """

    def _f(self):
        from k2rad.lumping import rigid_body_momentum_velocity
        return rigid_body_momentum_velocity

    def test_the_analytic_four_node_plate(self):
        """Four equal corner masses on a 2 x 2 plate, the two at x = 2
        carrying v = (0, 0, 10). By hand: v_cm = v/2 = (0, 0, 5);
        ``L = m(d3 + d4) x v = (0, -20, 0)``; ``Iyy = 4 m (L/2)^2 = 4`` so
        ``omega = (0, -5, 0)``; KE = 1/2 M v_cm^2 + 1/2 omega.I.omega =
        50 + 50 = 100. ``max|hand - code| = 0.0``."""
        v_cm, omega, cog, refusal = self._f()(
            [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)],
            [1.0, 1.0, 1.0, 1.0],
            [None, (0.0, 0.0, 10.0), (0.0, 0.0, 10.0), None],
            model_mass=4.0)
        self.assertEqual(refusal, "")
        self.assertEqual(v_cm, (0.0, 0.0, 5.0))
        self.assertEqual(cog, (1.0, 1.0, 0.0))
        for got, want in zip(omega, (0.0, -5.0, 0.0)):
            self.assertAlmostEqual(got, want, places=12)
        ke = 0.5 * 4.0 * 25.0 + 0.5 * 4.0 * omega[1] ** 2
        self.assertAlmostEqual(ke, 100.0, places=10)

    def test_the_X_and_Z_components_of_L_carry_their_own_sign(self):
        """Every other probe in this file puts the angular momentum on Y, so a
        sign error in ``lx`` or ``lz`` shipped invisibly: a whole-suite mutation
        pass flipping ``lx +=`` to ``-=`` (and the same on ``lz``) left
        5370 passed / 4124 subtests GREEN, while the ``ly`` twin was caught.

        A flipped component is a rigid body spinning the WRONG WAY with
        ``v_cm`` unchanged, so no energy or mass check notices it either.

        Both cases are the same square in the z = 0 plane with unit corner
        masses; only which pair is prescribed, and in which direction, changes.

          * prescribed pair on ``y = +1`` moving in ``+z``  -> spin about +X
            L_x = sum m (d_y v_z - d_z v_y) = 2 x 1 x (1 x 10) = 20,
            I_xx = 4 m d_y^2 = 4  ->  omega = (+5, 0, 0)
          * prescribed pair on ``x = +1`` moving in ``+y``  -> spin about +Z
            L_z = sum m (d_x v_y - d_y v_x) = 2 x 1 x (1 x 10) = 20,
            I_zz = 4 m (d_x^2 + d_y^2) / ... = 8  ->  omega = (0, 0, 2.5)
        """
        square = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0),
                  (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]
        masses = [1.0, 1.0, 1.0, 1.0]

        # ---- X: the two nodes at y = +1 move in +z ------------------------
        v_cm, omega, _cog, refusal = self._f()(
            square, masses,
            [None, None, (0.0, 0.0, 10.0), (0.0, 0.0, 10.0)],
            model_mass=4.0)
        self.assertEqual(refusal, "")
        self.assertAlmostEqual(v_cm[2], 5.0, places=12)
        for got, want in zip(omega, (5.0, 0.0, 0.0)):
            self.assertAlmostEqual(got, want, places=12)
        # the sign is the assertion: a flipped lx gives (-5, 0, 0)
        self.assertGreater(omega[0], 0.0)

        # ---- Z: the two nodes at x = +1 move in +y ------------------------
        v_cm, omega, _cog, refusal = self._f()(
            square, masses,
            [None, (0.0, 10.0, 0.0), (0.0, 10.0, 0.0), None],
            model_mass=4.0)
        self.assertEqual(refusal, "")
        self.assertAlmostEqual(v_cm[1], 5.0, places=12)
        for got, want in zip(omega, (0.0, 0.0, 2.5)):
            self.assertAlmostEqual(got, want, places=12)
        self.assertGreater(omega[2], 0.0)

    def test_a_fully_covered_body_returns_the_cards_own_velocity(self):
        """The degenerate arm, and the reason no deck of that class moves a
        byte: with every node prescribed the momentum average IS the card's
        velocity and omega is exactly zero."""
        v = (2286.0, 0.0, 7620.0)
        v_cm, omega, _cog, refusal = self._f()(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
            [0.25, 0.25, 0.25, 0.25], [v, v, v, v], model_mass=1.0)
        self.assertEqual(refusal, "")
        for got, want in zip(v_cm, v):
            self.assertAlmostEqual(got, want, places=9)
        self.assertEqual(omega, (0.0, 0.0, 0.0))

    def test_a_collinear_two_node_body_gets_no_axial_spin(self):
        """A line of point masses has NO moment of inertia about its own
        axis, and its angular momentum is perpendicular to that axis — so the
        pseudo-inverse is EXACT here, not an approximation.

        The separation is the real one from the Yaris suspension deck's 2-node
        CNRB ``nsid 2202010`` (9.784467 mm, ``det`` 8.75e-12, condition number
        1.34e16, where a ``solve()`` returns an angular velocity two orders of
        magnitude wrong with no diagnostic). The two node positions here are
        placed along that measured separation rather than lifted from the
        deck, so what is pinned is the GUARD, not the Yaris numbers.
        """
        import math as _m
        d = 9.784467
        axis = (1.0 / _m.sqrt(3.0),) * 3
        p0 = (0.0, 0.0, 0.0)
        p1 = tuple(d * a for a in axis)
        v_cm, omega, _cog, refusal = self._f()(
            [p0, p1], [1.0e-6, 1.0e-6], [None, (0.0, 100.0, 0.0)],
            model_mass=1.0e-3)
        self.assertEqual(refusal, "")
        self.assertAlmostEqual(v_cm[1], 50.0, places=9)
        axial = sum(o * a for o, a in zip(omega, axis))
        self.assertAlmostEqual(axial, 0.0, places=9)
        # ... and the answer is FINITE and of the right order: |omega| is
        # about |v|/2 divided by the half-separation.
        self.assertLess(max(abs(o) for o in omega), 50.0 / (d / 2.0) * 1.01)
        self.assertGreater(max(abs(o) for o in omega), 1.0)

    def test_a_NEARLY_collinear_body_does_not_explode_at_EITHER_scale(self):
        """The one the rank test is actually for, and why it is SCALE-FREE.

        A TWO-node body is exactly collinear whatever its coordinates — two
        points always are — so its axial inertia is exactly 0 and any guard
        catches it. It takes THREE nearly-collinear masses to make an
        eigenvalue that is tiny but NOT zero, which is the case a
        ``solve()`` answers by orders of magnitude (the real 2-node CNRB of
        the Yaris suspension deck reads ``det`` 8.75e-12 / condition 1.34e16).

        Both bodies below are the same shape — three masses on a 10-long line
        with a small transverse kink — and both must give the same answer:
        ``omega = (0, -10, 0)``, the transverse spin
        ``|v|/2 ÷ half the span``. They differ only in UNITS, and that is the
        point: the light one's small eigenvalue is ~6.7e-19 and the heavy
        one's is ~1.0e-6, so a fixed ABSOLUTE tolerance can only be right for
        one of them, while ``1e-10 × M × R²max`` is right for both.
        """
        for mass, kink, small in ((1.0e-6, 1.0e-6, 6.7e-19),
                                  (1.0e+3, 3.9e-5, 1.0e-06)):
            with self.subTest(mass=mass):
                v_cm, omega, _cog, refusal = self._f()(
                    [(0.0, 0.0, 0.0), (5.0, kink, 0.0), (10.0, 0.0, 0.0)],
                    [mass, mass, mass],
                    [None, None, (0.0, 0.0, 100.0)], model_mass=mass * 3)
                self.assertEqual(refusal, "")
                self.assertAlmostEqual(v_cm[2], 100.0 / 3.0, places=9)
                # the spin it CAN carry, and nothing about its own axis
                self.assertAlmostEqual(omega[1], -10.0, delta=0.2)
                self.assertAlmostEqual(omega[0], 0.0, places=6)
                self.assertLess(max(abs(o) for o in omega), 20.0,
                                f"the {small:g} eigenvalue was inverted")

    def test_a_single_node_body_translates_and_does_not_spin(self):
        v_cm, omega, _c, refusal = self._f()(
            [(1.0, 2.0, 3.0)], [2.0], [(1.0, 0.0, 0.0)], model_mass=2.0)
        self.assertEqual(refusal, "")
        self.assertEqual(v_cm, (1.0, 0.0, 0.0))
        self.assertEqual(omega, (0.0, 0.0, 0.0))

    def test_coincident_nodes_do_not_produce_a_spin(self):
        v_cm, omega, _c, refusal = self._f()(
            [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], [1.0, 1.0],
            [(10.0, 0.0, 0.0), None], model_mass=2.0)
        self.assertEqual(refusal, "")
        self.assertEqual(v_cm, (5.0, 0.0, 0.0))
        self.assertEqual(omega, (0.0, 0.0, 0.0))

    def test_a_relatively_massless_body_is_REFUSED_by_name(self):
        """A 37-node CNRB on this corpus lumps to 4.55e-24 in a model whose
        own lumped mass is ~1e-4: an absolute ``M <= 0`` test misses it and an
        absolute 1e-30 test accepts it."""
        v_cm, omega, cog, refusal = self._f()(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [2.275e-24, 2.275e-24],
            [(1.0, 0.0, 0.0), None], model_mass=1.0048e-4)
        self.assertIsNone(v_cm)
        self.assertIsNone(omega)
        self.assertIsNone(cog)
        self.assertIn("lumped mass", refusal)
        self.assertIn("ANCMSG 679", refusal)

    def test_the_same_body_is_ACCEPTED_when_the_model_is_that_light(self):
        """The refusal is RELATIVE: the same masses in a model whose own mass
        is of that order carry real momentum."""
        v_cm, _o, _c, refusal = self._f()(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [2.275e-24, 2.275e-24],
            [(1.0, 0.0, 0.0), None], model_mass=1.0e-20)
        self.assertEqual(refusal, "")
        self.assertAlmostEqual(v_cm[0], 0.5, places=12)

    def test_the_eigen_solver_matches_a_hand_diagonalisation(self):
        from k2rad.lumping import _sym3_eigen
        a = ((4.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 0.0, 9.0))
        vals, vecs = _sym3_eigen(a)
        self.assertEqual(sorted(round(v, 9) for v in vals), [3.0, 5.0, 9.0])
        for lam, vec in zip(vals, vecs):
            av = tuple(sum(a[i][j] * vec[j] for j in range(3))
                       for i in range(3))
            for got, want in zip(av, tuple(lam * c for c in vec)):
                self.assertAlmostEqual(got, want, places=9)


def _mixed_inivel_deck(all_rigid: bool = True, rot: bool = False) -> str:
    """``translat``'s shape: a 4-node shell on a *MAT_RIGID part, of which an
    ``*INITIAL_VELOCITY_NODE`` names TWO nodes. *all_rigid* False adds a
    deformable node to the card, making it the MIXED arm."""
    nodes = "".join(
        f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
        for i, (x, y, z) in enumerate(
            [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0),
             (0, 0, 10), (2, 0, 10), (2, 2, 10), (0, 2, 10)], start=1))
    card = "".join(
        _row(n, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0 if rot else 0.0) + "\n"
        for n in ([2, 3] + ([] if all_rigid else [5])))
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n" + nodes
            + "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
            + _row(2, 2, 5, 6, 7, 8) + "\n"
            + "*PART\nrigid plate\n" + _row(1, 1, 1) + "\n"
            + "deformable plate\n" + _row(2, 1, 2) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            + _row(0, 0, 0) + "\n" + _row(0, 0, 0) + "\n"
            + "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
            + "*INITIAL_VELOCITY_NODE\n" + card
            + "*END\n")


class MassWeightedInivel(unittest.TestCase):
    """B2 — a rigid body an initial-velocity card covers only PARTLY.

    MEASURED on ``intro-by-j.-day/joint/joint-ii/translat.k`` at nt 4 (2 of
    rigid part 1's 4 element nodes carry ``v = (2286, 0, 7620)``; LS-DYNA's own
    glstat cycle-0 K-ENERGY is 189.962): the shipped full-velocity re-point
    reads 387.9 (+104.20 %), this rule emits ``v_cm = (1143, 0, 3810)`` and
    ``omega = (300, 0, -45)`` — the hand values the round-3 docstring recorded,
    to every digit — for **220.58** (+16.12 %), and the final ``ke_dev`` goes
    +194.03 % → **+47.82 %**. Both arms NORMAL TERMINATION, 0 ERROR / 1
    WARNING; the starter echoes ``NEW X,Y,Z 12.70000 12.70000 4.14e-15``, i.e.
    ``ICoG`` really did move the main node to the centre of mass.
    """

    def test_the_default_writes_the_cards_full_velocity(self):
        _r, starter, _e = _convert(_mixed_inivel_deck())
        block = _block_after(starter, "/INIVEL/TRA/", 4)
        self.assertEqual([float(x) for x in block[3].split()[:3]],
                         [0.0, 0.0, 10.0])
        self.assertNotIn("/INIVEL/ROT/", starter)

    def test_the_flag_writes_the_momentum_average_on_the_main_node(self):
        res, starter, _e = _convert(_mixed_inivel_deck(),
                                    mass_weighted_inivel=True)
        tra = _block_after(starter, "/INIVEL/TRA/", 4)
        self.assertEqual([float(x) for x in tra[3].split()[:3]],
                         [0.0, 0.0, 5.0])
        rot = _block_after(starter, "/INIVEL/ROT/", 4)
        # ALL THREE cells, not just the one this deck happens to load: reading
        # only index 1 is what let a flipped lx/lz ship (see
        # MomentumAverageArithmetic.test_the_X_and_Z_components_of_L_carry...).
        cells = [float(x) for x in rot[3].split()[:3]]
        for got, want in zip(cells, (0.0, -5.0, 0.0)):
            self.assertAlmostEqual(got, want, places=9)
        self.assertTrue(_has(res.warnings, "MOMENTUM AVERAGE"), res.warnings)

    def test_the_MIXED_card_keeps_its_deformable_half(self):
        """The mixed arm is where the body was REFUSED before: its deformable
        nodes must keep working either way."""
        res, starter, _e = _convert(_mixed_inivel_deck(all_rigid=False),
                                    mass_weighted_inivel=True)
        self.assertTrue(_has(res.warnings, "MOMENTUM AVERAGE"), res.warnings)
        grp = [ln for ln in starter.splitlines() if ln.startswith("         5")]
        self.assertTrue(grp, "the deformable node left the group")

    def test_a_card_with_NODAL_ROTATIONS_is_refused_out_loud(self):
        """The average is formed from TRANSLATIONAL momentum only; a card that
        also prescribes nodal spin is out of scope and says so rather than
        silently doing nothing."""
        res, starter, _e = _convert(_mixed_inivel_deck(rot=True),
                                    mass_weighted_inivel=True)
        self.assertTrue(_has(res.warnings, "did NOT touch",
                             "NODAL ROTATIONAL"), res.warnings)
        self.assertFalse(_has(res.warnings, "MOMENTUM AVERAGE"))

    def test_the_flag_off_arm_is_byte_identical(self):
        deck = _mixed_inivel_deck()
        _r, a, ea = _convert(deck)
        _r2, b, eb = _convert(deck, mass_weighted_inivel=False)
        self.assertEqual(a, b)
        self.assertEqual(ea, eb)

    def test_a_FULLY_covered_body_is_untouched_by_the_flag(self):
        """The 20 class-C keys: their card names every node of the body, so
        the momentum average IS the card's velocity and the existing re-point
        already writes it. Byte-identical with and without the flag."""
        deck = _mixed_inivel_deck().replace(
            "*INITIAL_VELOCITY_NODE\n",
            "*INITIAL_VELOCITY_NODE\n"
            + "".join(_row(n, 0.0, 0.0, 10.0) + "\n" for n in (1, 4)))
        _r, off, _e = _convert(deck)
        _r2, on, _e2 = _convert(deck, mass_weighted_inivel=True)
        self.assertEqual(off, on)
        self.assertNotIn("/INIVEL/ROT/", on)

    def test_every_call_site_takes_the_two_value_return(self):
        """The #132 rule: the same keyword family lands in THREE writer
        functions, and a change to one leaves the other two silent."""
        import k2rad.writer.loads as lw
        src = inspect.getsource(lw)
        self.assertEqual(src.count("_warn_inivel_on_rigid_members("), 4)
        self.assertEqual(src.count("nids, mw_bodies = "), 3)
        self.assertEqual(src.count("_emit_mass_weighted_bodies(state, mw_bodies"),
                         3)

    def test_the_lumper_moved_into_the_package_and_tools_imports_it_back(self):
        import k2rad.lumping as pkg
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools"))
        import modal_solve
        self.assertIs(modal_solve._tet_volume, pkg._tet_volume)
        self.assertIs(modal_solve._HEXA_TETS, pkg._HEXA_TETS)
        self.assertIs(modal_solve._beam_section_area, pkg._beam_section_area)
        # the WRAPPER is the tool's own (it passes print); the arithmetic is
        # the package's
        self.assertIsNot(modal_solve.nodal_masses_from_state,
                         pkg.nodal_masses_from_state)
        deck = _mixed_inivel_deck()
        st = _dispatch(deck)
        self.assertEqual(modal_solve.nodal_masses_from_state(st),
                         pkg.nodal_masses_from_state(st))

    def test_the_package_never_imports_numpy(self):
        """``k2rad`` must run without numpy/scipy; the momentum average is
        pure standard library."""
        import k2rad.lumping as pkg
        src = inspect.getsource(pkg)
        self.assertNotIn("import numpy", src)
        self.assertNotIn("import scipy", src)

    def test_the_retracted_no_nodal_masses_claims_are_gone(self):
        retracted = ("this writer computes no nodal masses and will not "
                     "invent one",
                     "a mass-weighted average this WRITER does not form",
                     "The mass-weighted arm is a round-4 item")
        for rel, joined in _SHIPPED_TEXTS():
            for needle in retracted:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle), joined)


# ── the verification round's own guards ──────────────────────────────────────

class RbodyProducerCountIsStatedOnce(unittest.TestCase):
    """Round 5 added /RBODY producers 4 and 5 and four shipped texts still
    said THREE — the #138 rule ("grep every consumer of a state flag you add a
    producer for") applied to ``state.rbody_ids``.

    No test pinned the count, so the whole-suite mutation pass could not see
    it. This one DERIVES the number from the source and makes every text that
    states it agree, so the next producer cannot be added silently either.
    """

    def _root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _rbody_src(self):
        with open(os.path.join(self._root(), "k2rad", "writer", "rbody.py"),
                  encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _add_lines(src: str):
        """The lines that REGISTER, 1-based. A mention in a comment or a
        docstring must not vote: the #139 review found the substring count one
        comment away from being wrong."""
        return [i + 1 for i, ln in enumerate(src.splitlines())
                if ln.strip().startswith("state.rbody_ids.add")]

    def test_the_number_of_producers_is_what_the_module_actually_has(self):
        adds = self._add_lines(self._rbody_src())
        self.assertEqual(len(adds), 5, f"rbody_ids.add sites: {adds}")

    def test_a_comment_mentioning_the_call_does_not_inflate_the_count(self):
        """The substring form this test used to have counted any line that
        merely NAMED ``rbody_ids.add``."""
        src = self._rbody_src() + "\n# state.rbody_ids.add is called 5 times\n"
        self.assertEqual(len(self._add_lines(src)), 5)
        self.assertEqual(
            len([i for i, ln in enumerate(src.splitlines())
                 if "rbody_ids.add" in ln]), 6,
            "the substring form must still see six, or this probe is moot")

    def test_every_producer_comment_numbers_itself_out_of_that_total(self):
        src = self._rbody_src()
        # a producer may name itself more than once (docstring + the line that
        # registers), so the assertion is on the SET of ordinals
        seen = {int(n) for n, tot in
                re.findall(r"[Pp]roducer (\d) of (\d)", src) if int(tot) == 5}
        self.assertEqual(seen, {1, 2, 3, 4, 5},
                         "each /RBODY producer must number itself 'N of 5'")
        self.assertEqual(re.findall(r"[Pp]roducer \d of [1-46-9]", src), [],
                         "a producer comment still counts out of the old total")

    def test_no_shipped_text_still_says_there_are_three(self):
        """The four consumer texts that named the count."""
        stale = ("THREE Radioss-side", "three /RBODY producers",
                 "all THREE Radioss-side", "funnelling through three writers")
        for rel, joined in _SHIPPED_TEXTS():
            for needle in stale:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle), joined)

    def test_the_cited_registration_lines_are_the_real_ones(self):
        """A line citation is a measurement too. Each number the consumer texts
        quote must really be a ``rbody_ids.add`` line."""
        adds = set(self._add_lines(self._rbody_src()))
        root = self._root()
        # CHANGELOG.md is deliberately NOT in this list: it is history and
        # carries line citations that were right at the commit they were
        # written for (``writer/rbody.py:969``, a 2026-07 entry about the
        # master node's added mass), the same reason the retracted-spelling
        # guard excludes it.
        for rel in ("k2rad/writer/output.py", "k2rad/state.py",
                    "k2rad/handlers.py"):
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      encoding="utf-8") as fh:
                text = _collapse(fh.read())
            # A citation RUN is ``writer/rbody.py:791`` followed by bare
            # ``:NNN`` continuations. The round-5 form read only the first,
            # fully prefixed number and swept the rest into a regex applied to
            # the EMPTY STRING, so four of the five were never checked -- and
            # three of them were stale at that very commit (#139).
            cited = set()
            for m in re.finditer(
                    r"writer/rbody\.py:(\d+)((?:[^A-Za-z0-9]{0,16}:\d+)*)",
                    text):
                cited.add(int(m.group(1)))
                cited |= {int(x) for x in re.findall(r":(\d+)", m.group(2))}
            self.assertTrue(cited, f"{rel} cites no writer/rbody.py line")
            for line in sorted(cited):
                with self.subTest(file=rel, line=line):
                    self.assertIn(line, adds,
                                  f"{rel} cites writer/rbody.py:{line}, which "
                                  f"is not a rbody_ids.add line (they are "
                                  f"{sorted(adds)})")


class ImplicitProbeRbodyReadsBothRegistries(unittest.TestCase):
    """``_make_probe_rbody`` guarded on ``rbody_info`` alone, which producers 4
    and 5 deliberately do NOT populate — they have no LS-DYNA PART id to key it
    by. An IMPLICIT deck whose only rigid body is a shell-to-solid tie or a butt
    weld would therefore have been given the inert probe, its three synthesized
    nodes and its ``/BCS`` on top of a body it already has, under a warning
    claiming it has none.

    Reach is 0 on every corpus here (both carriers are explicit decks), which is
    exactly why nothing caught it: reverting the guard to ``rbody_info`` alone
    left the whole suite GREEN (5380 passed) in this round's own mutation pass.
    A guard with no probe is not a guard, so here is the probe.
    """

    def _implicit(self, deck: str) -> str:
        return deck.replace(
            "*CONTROL_TERMINATION\n",
            "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
            "*CONTROL_TERMINATION\n", 1)

    def test_a_tie_is_a_rigid_body_so_the_probe_stays_away(self):
        deck = self._implicit(_shell_to_solid_deck())
        _r, starter, _e = _convert(deck)
        self.assertIn("/RBODY/5", starter, "the tie body was not emitted")
        self.assertNotIn("INERT PROBE RIGID BODY", starter)

    def test_the_same_deck_WITHOUT_the_tie_still_gets_the_probe(self):
        """The control arm the #138 rule asks for: the guard must not have
        turned the probe off for everyone. With the tie opted out there is no
        rigid body left, and the probe has to come back."""
        deck = self._implicit(_shell_to_solid_deck())
        _r, starter, _e = _convert(deck, shell_to_solid_rbody=False)
        self.assertNotIn("/RBODY/5", starter)
        self.assertIn("INERT PROBE RIGID BODY", starter)

    def test_a_butt_weld_counts_as_a_rigid_body_too(self):
        deck = self._implicit(_butt_deck())
        _r, starter, _e = _convert(deck)
        self.assertIn("/RBODY/", starter)
        self.assertNotIn("INERT PROBE RIGID BODY", starter)


class ImplicitNogapRemedyPointsSomewhereReal(unittest.TestCase):
    """The ``_RS_IMPLICIT_NOGAP`` remedy told the user to state a gap with
    ``--inter-gapmin <id>=VAL``. ``_rigid_secondary_plan`` decides the swap
    purely from ``_derived_gapmin_value``; it never reads
    ``state.options.inter_gapmin``, ``_gapmin_override`` or
    ``_sst_mst_to_gapmin``, all of which are evaluated later in
    ``_make_interfaces`` — on an interface this refusal prevents from existing.

    The branch is NOT hypothetical: it is what
    ``implicit/Yaris%20Dynamic%20Roof%20Crush`` fires (measured — with the flag
    on, that deck's drop prints this remedy and both its .rad files stay
    byte-identical).
    """

    def test_the_plan_reads_no_user_stated_gap(self):
        import inspect
        from k2rad.writer import contacts
        src = inspect.getsource(contacts._rigid_secondary_plan)
        for name in ("inter_gapmin", "_gapmin_override", "_sst_mst_to_gapmin"):
            with self.subTest(name=name):
                self.assertNotIn(name, src)

    def test_the_remedy_no_longer_promises_a_flag_it_cannot_use(self):
        from k2rad.writer import contacts
        text = contacts._RIGID_SECONDARY_REMEDY_IMPLICIT_NOGAP
        self.assertNotIn("State the gap yourself with --inter-gapmin", text)
        self.assertIn("do NOT rescue this", text)
        self.assertIn("Swap the sides in the .k", text)


class DropInterfaceKeepsItsSentenceWhole(unittest.TestCase):
    """The implicit note used to be concatenated onto the drop's CAUSE, which
    is a clause followed by ", so NO /INTER was emitted" — so the note was
    spliced into the middle of its own sentence and the seam read
    ``... is the usual cause This is an IMPLICIT deck ... answer., so NO``.
    """

    def test_the_note_lands_after_the_clause_closes(self):
        from k2rad.state import ConversionState
        from k2rad.writer import contacts
        st = ConversionState()
        dropped: dict = {}
        contacts._drop_interface(st, dropped, "CONTACT", 7,
                                 "the SECONDARY side resolved to no nodes",
                                 "REMEDY: do the thing.",
                                 note="This is an IMPLICIT deck. It matters.")
        msg = st.warnings[-1]
        self.assertIn("no nodes, so NO /INTER was emitted for this contact. "
                      "This is an IMPLICIT deck.", msg)
        self.assertNotIn(".,", msg)
        self.assertNotIn("cause This is", msg)

    def test_a_drop_without_a_note_is_unchanged(self):
        from k2rad.state import ConversionState
        from k2rad.writer import contacts
        st = ConversionState()
        contacts._drop_interface(st, {}, "CONTACT", 7, "a cause", "REMEDY: x.")
        msg = st.warnings[-1]
        self.assertTrue(msg.startswith(
            "*CONTACT 7: a cause, so NO /INTER was emitted for this contact."))
        self.assertNotIn("  ", msg)


# ── B6: the corrected statements ─────────────────────────────────────────────

#: Every claim round 5 measured to be WRONG, in every spelling it was ever
#: shipped in. The guard below runs each one against every shipped text; the
#: companion feeds each one to the guard's own matcher and proves it fires.
_RETRACTED_ROUND_5 = (
    # the derived-Gapmin class had 2 measured arms; it has 7
    "13 of the class's 15",
    "the only OTHER carrier with a measured arm",
    "the only other carrier with a measured arm",
    "the measured arms disagree",
    "THIRTEEN have none",
    "13 have none at all",
    # the ELFORM 5/6/7 gate never fires on this route
    "9 starter errors on taylor_B",
    "4 on advection_B",
    # /IMPFLUX HAS a volumetric form and HAS a time window
    "no volume source",
    "neither the motion nor the depth distribution can be expressed",
    # the implicit all-rigid-SSID swap: one arm does NOT diverge
    "every restoration arm measured on implicit",
    "EVERY arm that restores the load path diverges",
    "with an explicit Gapmin of 0.14986 it reaches",
    # the writer DOES compute nodal masses now
    "this writer computes no nodal masses and will not invent one",
    "a mass-weighted average this WRITER does not form",
    "The mass-weighted arm is a round-4 item",
    # the assumed-strain figures and remedy
    "-5.75 / -5.18 / -6.27",
    "−5.75 / −5.18 / −6.27",
    "Refine through the thickness",
    # ── the verification round's own five corrections ────────────────────────
    # WARNING 476 is raised ONCE: the check is inside hm_read_admas.F:160's
    # IF (FLAG == 0), so the FLAGG=1 pass of lectur.F:7967-7979 never sees it.
    # The doubling on plates.nrbc is its SECOND domain decomposition, which
    # reprints every warning -- the deck's own WARNING 1084 doubles on the
    # master arm too, and the dome (no second decomposition) prints all nine
    # of its warnings once.
    "because the reader runs both FLAG passes",
    "raised TWICE per card",
    "raised twice per card",
    "twice per card, because the reader runs both",
    "raised once per FLAG pass",
    # rcheckmass.F's ERROR 1870 is gated on IGTYP==23 (:112) and MTN==108
    # (:123) -- a /PROP/TYPE23 on /MAT/LAW108 -- so it never inspects the
    # TYPE4/TYPE8/TYPE13 springs this compensation registers. The check that
    # does reach them is chkmsin.F:52-59 + resol.F:5460.
    "rcheckmass.F:126-135",
    "MS = 0 is ERROR 1870",
    # every one of the corpus's 7417 pentahedra collapses the OTHER cell pair
    "the spelling every one of the R14 corpus's 7417 pentahedra uses",
    "the one all 7417 R14-corpus",
    # the flag is byte-inert on the Yaris giant (measured, both .rad files)
    "plus the Yaris Dynamic Roof Crush giant, convert-only",
    # --inter-gapmin is evaluated long after the plan that refuses the swap
    "State the gap yourself with --inter-gapmin",
    # the assumed-strain flag moves 19 keys on 16 models, not 20 on 17
    "moves 20 keys / 17 models",
    "20 deck keys on 17 emitted models",
    "20 keys on 17 models",
    # ── the #139 verification round's own corrections ────────────────────────
    # An independently rebuilt coupon: at nz = 1 and TSSFAC 0.9 BOTH
    # formulations blow up and both print NORMAL TERMINATION; at TSSFAC 0.3
    # both converge. The "24 alone diverges, 17 is stable at 0.238246" half
    # also contradicted the same warning's own 0.24820 for that point.
    "is stable at 0.238246",
    "the 24 arm DIVERGES",
    # base-paired, twice, nt 4: 51762 cycles on BOTH arms, and the flag arm is
    # the FASTER one in wall time (93.2/94.6 s against 106.2/107.2 s)
    "at 5x the wall time",
    "5x the wall",
    # the engine prints 0.1017E-16 and 0.1353E+13, i.e. 1.017e-17 and 1.353e12
    "1.017e-16",
    "1.353e13",
    # the converted cylinder_impact_B's ALE bricks are /MAT/VOID rho 1e-12, so
    # the starter's own Iauto=2 answer is 3.528 -- measured, 0 ERROR
    "four orders above the 1.0 emitted here",
    # WHICH condition wins WAS measured after all, and the /BCS is LOST
    "Radioss applies the rigid body first",
    # mat_spring.belted-dummy states no *ELEMENT_MASS at all and emits no
    # /ADMAS; its 15 token nodes are all rigid-body secondaries
    "its spring end nodes already carry",
    "spring end nodes already carry an",
    # hm_read_admas.F has no sign check: keeping the deck's own /ADMAS
    # positive is a k2rad policy, not a solver rule
    "an /ADMAS must stay positive",
    # taking the token off a degenerate node leaves m_own + m_admas > 0
    "so removing it would drive the nodal mass negative",
    # only the warnings raised inside lectur.F:5691-9094 are reprinted
    "so prints every warning twice",
    # 3 of the 6 are identical arm for arm; the OTHER four is the
    # SINGLE_SURFACE count
    "changes NOTHING on 4 of the 6 carriers",
    # a paraphrase in quotation marks is not a quote
    "the same material as the material that is being voided",
)


class Round5RetractedStatements(unittest.TestCase):
    """Every statement rounds 5 and #139 measured to be wrong, guarded
    as one family.

    The matcher is the one the round-4 figure guard established: adjacent
    string literals JOINED and every whitespace run collapsed, over every
    shipped text (both docs, the whole package, the GUI). ``CHANGELOG.md`` is
    the historical record and is deliberately not scanned — a past entry says
    what that round shipped, and the round-4 entry carries an in-place
    ``re-measured in round 5`` note beside its own figure.
    """

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_5:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle), joined)

    def test_the_guard_fires_on_each_retracted_spelling(self):
        """A guard that matches nothing passes for a clean one. Each needle is
        fed back in the shape a source file would carry it — split across two
        adjacent literals — and must be FOUND."""
        for needle in _RETRACTED_ROUND_5:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "') + ' y')
                self.assertIn(_collapse(needle), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)))

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        """A rename is a prefix, not a removal."""
        for needle in _RETRACTED_ROUND_5:
            with self.subTest(needle=needle):
                self.assertIn(_collapse(needle[:max(8, len(needle) // 2)]),
                              _collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        """The other half: the corrected statement has to BE somewhere, or the
        retraction is just a deletion."""
        texts = dict(_SHIPPED_TEXTS())
        pairs = (
            ("k2rad\\writer\\contacts.py", "7 now have a measured arm and 8 are still UNJUDGEABLE"),
            ("k2rad\\handlers.py", "0 ERROR / 0 WARNING with Iale 1 AND with Iale 2"),
            ("k2rad\\handlers.py", "/IMPFLUX DOES have a volumetric form"),
            ("k2rad\\writer\\contacts.py", "the swap WITH the derived Gapmin"),
            ("k2rad\\writer\\loads.py",
             "``--mass-weighted-inivel`` forms exactly that average"),
            ("k2rad\\writer\\mesh.py", "REFINE ALONG THE BEAM"),
            ("ROADMAP.md", "What round 5 deliberately does NOT close"),
            ("README.md", "--assumed-strain-isolid"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts if k.replace("/", "\\") == rel),
                           None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])

    def test_the_roadmap_carries_a_round_5_column(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ROADMAP.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(
            "| # | class | decks | closed by round 1 | round 2 | round 3 | "
            "round 4 | round 5 |", text)
        self.assertIn(
            "| family | decks | death | verdict after round 3 | round 4 | "
            "round 5 |", text)
        # the constant-step NO-GO, with the measurement that decided it
        self.assertIn("152 811", text)
        self.assertIn("1 888", text)


class EveryParserOptionIsInTheREADME(unittest.TestCase):
    """The half of the #139 flag-wiring finding that was not applied.

    ``Round5FlagWiring`` asserts membership only for the flags already in its
    own literal, so a FUTURE flag added to the parser with no README row and no
    tuple entry ships green. This derives the list from the parser instead. A
    ``--no-X`` pair counts as documented when EITHER spelling is in the README,
    because the README names the one a user would type.
    """

    #: Known gaps, documented rather than hidden. Every one predates round 5.
    _UNDOCUMENTED = {
        "--help",
        "--gapmin-factor", "--ground-spring-k", "--ground-springs",
        "--soften-stfac", "--tet10-to-tet4",
    }

    def test_every_option_the_parser_knows_is_named_in_the_README(self):
        from k2rad import cli
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings if s.startswith("--")}
        self.assertGreater(len(opts), 40, "the parser lost its options")

        def documented(opt: str) -> bool:
            twin = ("--" + opt[5:]) if opt.startswith("--no-") \
                else ("--no-" + opt[2:])
            return opt in readme or twin in readme

        missing = sorted(o for o in opts
                         if o not in self._UNDOCUMENTED and not documented(o))
        self.assertEqual(missing, [],
                         "parser options with no README row: " + repr(missing))

    def test_the_allow_list_has_no_stale_entry(self):
        """An allow-list that outlives its gap is a lie of its own."""
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings if s.startswith("--")}
        self.assertEqual(sorted(self._UNDOCUMENTED - opts), [],
                         "the allow-list names an option the parser lost")


# ── #139 verification round: four branches that had no probe ────────────────

class SpringTokenExactZeroBoundary(unittest.TestCase):
    """A1 — the ``mass - share > 0.0`` boundary the writer's own docstring
    names.

    ``_make_added_masses`` subtracts only while the remainder stays strictly
    positive; at ``mass == share`` the node is DEGENERATE, keeps the deck's own
    ``/ADMAS`` and takes the full share off on a negative card of its own. The
    existing degenerate probe uses an ``/ADMAS`` fifty times BELOW the share,
    so it pinned only the ``<`` side: relaxing the comparison to ``>=`` left
    the whole suite green (5383 passed) in the #139 mutation pass, while the
    mutant emitted a single ``/ADMAS`` of literally ``0.0`` and dropped the
    compensation block altogether.
    """

    def test_an_admas_exactly_equal_to_the_share_is_degenerate(self):
        _r, starter, _e = _convert(_weld_deck(admas=_SHARE))
        self.assertEqual(_admas_cards(starter),
                         {_SHARE: [1, 11], -_SHARE: [1, 11]})

    def test_just_above_the_share_is_subtracted_instead(self):
        """The other side of the same boundary, so the probe pins a POINT."""
        _r, starter, _e = _convert(_weld_deck(admas=_SHARE * 1.02))
        cards = {round(m, 12): v for m, v in _admas_cards(starter).items()}
        self.assertEqual(sorted(cards), [round(_SHARE * 0.02, 12)], cards)


class SpringTokenOrphanBranchIsProbed(unittest.TestCase):
    """A1 — the fifth list of ``_warn_spring_token_mass``.

    Since round 5 a spring node with no ``/ADMAS`` gets a NEGATIVE one, so
    "nothing to subtract from" stopped being a terminal class: the only way
    into ``orphan`` left is a node registered for the token that is not in
    ``state.nodes`` at all. No deck reaches that — every producer registers at
    the line that WRITES the ``/SPRING`` row and ``_register_spring_token_mass``
    refuses a share ``<= 0`` — so the probe calls the writer directly, which is
    what a defensive branch can be probed with.
    """

    def test_a_registered_node_outside_state_nodes_is_named_as_internal(self):
        from k2rad.writer import loads as loads_writer
        state = ConversionState()
        state.spring_token_mass_by_node[4242] = _SHARE
        loads_writer._warn_spring_token_mass(state, set(), [], [])
        self.assertTrue(_has(state.warnings, "[4242]",
                             "NOT in the converted model's node set",
                             "k2rad-internal inconsistency"), state.warnings)

    def test_a_node_the_model_does_have_never_reaches_that_branch(self):
        """The control arm: the same share on a node that DOES exist is a
        rigid-body case, never the internal one."""
        from k2rad.writer import loads as loads_writer
        state = ConversionState()
        state.nodes[7] = (0.0, 0.0, 0.0)
        state.spring_token_mass_by_node[7] = _SHARE
        loads_writer._warn_spring_token_mass(state, {7}, [], [])
        self.assertFalse(_has(state.warnings, "k2rad-internal inconsistency"),
                         state.warnings)
        self.assertTrue(_has(state.warnings,
                             "SECONDARY nodes of a rigid body"),
                        state.warnings)


class ImplicitSwapNeedsADeformableMainSide(unittest.TestCase):
    """B1 — the third precondition of the swap gate, which had no probe.

    ``_rigid_secondary_plan`` needs an implicit deck, a wholly rigid SSID
    **and a MSID side that still has a deformable node to swap onto**. Dropping
    that last clause (``and main and (main - rigid_nodes)`` -> ``and main``)
    left the whole suite green in the #139 mutation pass, while the mutant
    built a rigid-vs-rigid swapped ``/INTER/TYPE7``.
    """

    def _both_rigid(self) -> str:
        """The same implicit deck with the MSID side made rigid too."""
        deck = _implicit_rigid_ssid_deck()
        old = "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
        new = ("*MAT_RIGID\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
               + _row(0, 7, 7) + "\n" + _row(0, 0, 0) + "\n")
        assert deck.count(old) == 1, "the fixture moved"
        return deck.replace(old, new, 1)

    def test_the_plan_refuses_the_swap_when_the_main_side_is_rigid_too(self):
        """Straight at the gate: both sides rigid, both flags on."""
        from k2rad.writer import contacts as contacts_writer
        state = ConversionState()
        state.is_implicit = True
        state.options.implicit_rigid_secondary_swap = True
        state.nodes.update({i: (float(i), 0.0, 0.0) for i in range(1, 5)})
        state.node_sets[1] = ("ssid", [1, 2])
        state.node_sets[2] = ("msid", [3, 4])
        plan, _s, _m = contacts_writer._rigid_secondary_plan(
            state, {1, 2, 3, 4}, 1, 4, 2, 4, gapmin_route=True)
        self.assertEqual(plan, contacts_writer._RS_IMPLICIT)
        plan2, _s2, _m2 = contacts_writer._rigid_secondary_plan(
            state, {1, 2}, 1, 4, 2, 4, gapmin_route=True)
        self.assertNotEqual(
            plan2, contacts_writer._RS_IMPLICIT,
            "the control arm: a DEFORMABLE main side must not be refused")

    def test_the_conversion_drops_it_even_with_the_flag(self):
        res, starter, _e = _convert(self._both_rigid(),
                                    implicit_rigid_secondary_swap=True)
        self.assertNotIn("/INTER/TYPE7", starter)

    def test_the_deformable_arm_still_takes_the_swap(self):
        """The control: with a DEFORMABLE main side the same flag swaps."""
        _r, starter, _e = _convert(_implicit_rigid_ssid_deck(),
                                   implicit_rigid_secondary_swap=True)
        self.assertIn("/INTER/TYPE7", starter)


class MassWeightedInivelWritesNoEmptyGroup(unittest.TestCase):
    """B2 — commit 870c2c5's own guard, which had no probe.

    When every node of an ``*INITIAL_VELOCITY*`` card went to a momentum-
    averaged body there is nothing left to put in a ``/GRNOD``. Disarming the
    guard (``if not nids: continue`` -> ``if False:``) left the whole suite
    green in the #139 mutation pass, while the mutant emitted a fourth
    ``/GRNOD/NODE`` with no members and wrote an ``/INIVEL`` on it.
    """

    @staticmethod
    def _grnod_blocks(starter: str):
        """{id: [member ids]} over every emitted /GRNOD/NODE."""
        out = {}
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/GRNOD/NODE/"):
                gid = int(ln.rsplit("/", 1)[1])
                nids, j = [], i + 2
                while j < len(lines) and not lines[j].startswith(("/", "#")):
                    nids += [int(v) for v in lines[j].split()]
                    j += 1
                out[gid] = nids
        return out

    def test_the_fully_covered_card_writes_no_empty_group(self):
        _r, starter, _e = _convert(_mixed_inivel_deck(),
                                   mass_weighted_inivel=True)
        blocks = self._grnod_blocks(starter)
        self.assertTrue(blocks, "no /GRNOD at all - the probe is moot")
        for gid, nids in sorted(blocks.items()):
            self.assertTrue(nids, f"/GRNOD/NODE/{gid} was emitted EMPTY")

    def test_the_mixed_card_still_writes_the_group_it_needs(self):
        """The control arm: a card with a leftover deformable node must keep
        its /GRNOD, or the guard could equally have suppressed every group."""
        _r, starter, _e = _convert(_mixed_inivel_deck(all_rigid=False),
                                   mass_weighted_inivel=True)
        blocks = self._grnod_blocks(starter)
        for gid, nids in sorted(blocks.items()):
            self.assertTrue(nids, f"/GRNOD/NODE/{gid} was emitted EMPTY")
        self.assertTrue(any(nids == [5] for nids in blocks.values()),
                        "the leftover deformable node lost its group: "
                        + repr(blocks))


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
