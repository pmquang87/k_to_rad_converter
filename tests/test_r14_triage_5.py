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
        """Subtracting there would leave MS = 0 and the engine divides by it
        (``rcheckmass.F:126-135`` -> ERROR 1870)."""
        result, starter, _e = _convert(_weld_deck(meshed=False))
        self.assertNotIn("/ADMAS", starter)
        self.assertTrue(_has(result.warnings,
                             "carry NO element mass of their own",
                             "ERROR 1870", "[1, 11]"))

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

    _FLAGS = {
        "--shell-to-solid-rbody": "shell_to_solid_rbody",
        "--generalized-weld-butt": "generalized_weld_butt",
    }

    def test_every_round_5_flag_reaches_the_README(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        for flag in self._FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts, f"{flag} is not a parser option")
                neg = "--no-" + flag[2:]
                self.assertIn(neg, opts, f"{neg} is not a parser option")
                self.assertIn(neg, readme, f"{neg} is not in README.md")

    def test_the_help_renders_and_carries_the_measured_numbers(self):
        """A bare %% in a help string kills --help at a green suite."""
        from k2rad import cli
        text = cli.build_parser().format_help()
        for flag in self._FLAGS:
            self.assertIn("--no-" + flag[2:], text)
        self.assertIn("48190 cycles", text)
        self.assertIn("2082 cycles", text)

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


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
