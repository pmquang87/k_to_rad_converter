"""Tests for the SIDE-DEFECT batch — ten defects found at the edges of cards
this converter already handles, each reachable but none of them the main line
of any single keyword.

  (A) the standalone *EOS_* /MAT/LAW6 carrier collided in the /MAT namespace
  (B) *INITIAL_STRESS_SHELL / _SOLID had no *INCLUDE_TRANSFORM offset row
  (C) *DAMPING_GLOBAL emitted no /DAMP on a beam/spring model
  (D) *INITIAL_STRESS_SHELL on a 3-node shell was dropped (no /INISH3/STRS_F)
  (E) the reporting /SECT frame was conditioning-picked, not read from the card
  (F) _plane_cut had no spring arm, so a *DATABASE_CROSS_SECTION_SET DSID and
      a section plane through a belt found nothing
  (G) /DYNAIN under implicit (measured: it works) and the QEPH strain dropout
  (H) the element-GROUP id namespaces had one guarded allocation site of 18
  (I) *PARAMETER_EXPRESSION was not evaluated
  (J) the tiebreak ``c.only`` rupture branch

Every numeric expectation is hand-computed in the test, and the per-slot
values are chosen DISTINCT so a column swap is detectable (a card written with
sigma_X and sigma_Y exchanged must fail, not coincide).

Where an assertion contradicts what master pinned, the docstring carries the
measurement that settles it — see
``tests/test_impact_mats.py::...test_an_unrelated_EOS_id_gets_no_carrier_either``
for the (A) precedent (the old expectation was a deck the starter refuses with
ERROR 683).
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402


# ── Harness (same shape as tests/test_impact_mats.py) ────────────────────────

def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _convert_both(deck: str, **kw):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    engine = ""
    if getattr(result, "engine_path", None) and os.path.exists(
            result.engine_path):
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


def _row(*vals) -> str:
    out = "".join(f"{v:>10}" for v in vals)
    assert len(out) == 10 * len(vals), f"field overflow in {out!r}"
    return out


def _blocks(starter: str, header: str):
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
    return out


def _block(starter: str, header: str):
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _cards(block):
    """A block's DATA lines (header + title skipped, comments skipped)."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


# ─────────────────────────────────────────────────────────────────────────────
# (A) The standalone *EOS_* carrier and the /MAT + /EOS id namespaces
# ─────────────────────────────────────────────────────────────────────────────

_A_NODES = "*NODE\n" + "".join(
    _row(n, x, y, z) + "\n" for n, x, y, z in (
        (1, "0.0", "0.0", "0.0"), (2, "1.0", "0.0", "0.0"),
        (3, "1.0", "1.0", "0.0"), (4, "0.0", "1.0", "0.0"),
        (5, "0.0", "0.0", "1.0"), (6, "1.0", "0.0", "1.0"),
        (7, "1.0", "1.0", "1.0"), (8, "0.0", "1.0", "1.0")))

_A_SOLID = "*ELEMENT_SOLID\n" + _row(1, 1) + "\n" + _row(*range(1, 9)) + "\n"
_A_SEC = "*SECTION_SOLID\n" + _row(1, 1) + "\n"


def _a_deck(mat_block: str, eosid: int, mid: int) -> str:
    """One brick on material ``mid``, plus a bare *EOS_LINEAR_POLYNOMIAL of id
    ``eosid`` that no *PART names."""
    return ("*KEYWORD\n" + _A_NODES + _A_SOLID + _A_SEC
            + "*PART\nbrick\n" + _row(1, 1, mid) + "\n"
            + mat_block
            + "*EOS_LINEAR_POLYNOMIAL\n"
            + _row(eosid, "0.0", "2.2E9", "0.0", "0.0", "0.0", "0.0", "0.0")
            + "\n" + _row("0.0", "1.0") + "\n"
            + "*END\n")


_A_MAT_ELASTIC_7 = ("*MAT_ELASTIC\n"
                    + _row(7, "7.85E-9", "2.1E5", "0.3") + "\n")


class TestEosCarrierIdCollision(unittest.TestCase):
    """(A) A bare ``*EOS_*`` (no same-id ``*MAT_NULL``, named by no ``*PART``
    EOSID) used to mint a ``/MAT/LAW6`` carrier under the EOS id.

    The guard on that was ``_impact_claimed_mids`` — a hand-kept list of THREE
    families — so an EOS id held by ANY other family went straight through.
    MEASURED on the corpus carrier
    ``dynaexamples_r14_ton-mm-s/ale-s-ale/s-ale/wavestructure/2Dlag.k``
    (``*MAT_JOHNSON_COOK 3`` + orphan ``*EOS_LINEAR_POLYNOMIAL 3``), converted
    at master 0c8968e and run through the starter::

        ERROR ID :   683  ... MATERIAL ID: 3  ... DENSITY <= ZERO
        ERROR ID :    79  ** ERROR: DUPLICATE ID
                          IN MATERIAL DEFINITION      ID=3 is DUPLICATED
        ERROR TERMINATION       3 ERROR(S)

    plus an UNDIAGNOSED second collision, ``/EOS/GRUNEISEN/3`` beside
    ``/EOS/POLYNOMIAL/3``: ``hm_read_eos.F`` contains no ``UDOUBLE`` at all, so
    two /EOS on one id are accepted at 0 ERROR / 0 WARNING and the last one
    silently replaces the material's pressure law (``:301-304`` writes
    ``IPM(4,IMAT) = IEOS``).
    """

    def test_a_bare_eos_on_a_free_id_is_dropped_and_named(self):
        """No family holds id 500 — and there is still no carrier, because no
        *EOS_* keyword carries a density and /MAT/LAW6 with RHO_I 0 is starter
        ERROR 683."""
        res, starter = _convert(_a_deck(_A_MAT_ELASTIC_7, eosid=500, mid=7))
        self.assertEqual(_headers(starter, "/MAT/"), ["/MAT/ELAST/7"])
        self.assertEqual(_headers(starter, "/EOS/"), [])
        w = _warns(res, "*EOS_POLYNOMIAL 500")
        self.assertEqual(len(w), 1)
        self.assertIn("ERROR 683", w[0])

    def test_a_bare_eos_colliding_with_MAT_ELASTIC_names_the_owner(self):
        """The generalised guard: ``*MAT_ELASTIC`` is in NONE of the three
        families ``_impact_claimed_mids`` knows, so master emitted
        ``/MAT/ELAST/7`` AND ``/MAT/HYD_VISC/7``."""
        res, starter = _convert(_a_deck(_A_MAT_ELASTIC_7, eosid=7, mid=7))
        self.assertEqual(_headers(starter, "/MAT/"), ["/MAT/ELAST/7"])
        self.assertEqual(_headers(starter, "/EOS/"), [])
        w = _warns(res, "*EOS_POLYNOMIAL 7")
        self.assertEqual(len(w), 1)
        self.assertIn("*MAT_ELASTIC -> /MAT/ELAST", w[0])
        self.assertIn("ERROR 79", w[0])
        # The /EOS half of the collision is the one the starter does NOT
        # diagnose, so the message has to say so.
        self.assertIn("SILENTLY REPLACES", w[0])

    def test_the_three_EOS_adjacent_families_keep_their_specific_reason(self):
        """``_impact_claimed_mids`` survives as a MESSAGE refinement: for a
        Johnson-Holmquist law or an elastic fluid the reader is told why that
        law neither needs nor accepts a companion /EOS, not just that the id
        is taken. Pinned so the generalisation cannot flatten it."""
        fluid = ("*MAT_ELASTIC_FLUID\n"
                 + _row(7, "7.85E-9", "2.1E5", "0.3", "0.0", "0.0") + "\n"
                 + _row("2.2E9", "0.0", "0.0", "-1E20") + "\n")
        res, _s = _convert(_a_deck(fluid, eosid=7, mid=7))
        w = _warns(res, "*EOS_POLYNOMIAL 7")
        self.assertEqual(len(w), 1)
        self.assertIn("already emits its OWN", w[0])
        self.assertIn("*MAT_ELASTIC_FLUID -> /MAT/LAW6", w[0])

    def test_no_id_is_emitted_twice_in_either_namespace(self):
        """The property the whole item is about, asserted on the deck shape
        that used to break it: one /MAT per id AND one /EOS per id."""
        for mid, eosid in ((7, 7), (7, 500), (7, 8)):
            with self.subTest(mid=mid, eosid=eosid):
                _r, starter = _convert(
                    _a_deck(_A_MAT_ELASTIC_7, eosid=eosid, mid=mid))
                for prefix in ("/MAT/", "/EOS/"):
                    ids = [ln.rsplit("/", 1)[-1]
                           for ln in _headers(starter, prefix)]
                    self.assertEqual(sorted(ids), sorted(set(ids)))

    def test_a_MAT_NULL_carrier_is_untouched(self):
        """The shared-id pairing that DOES work keeps working byte-for-byte:
        a *MAT_NULL of the EOS id supplies the density, so the carrier is
        legal and is still emitted."""
        null = "*MAT_NULL\n" + _row(7, 1.0e-9) + "\n"
        _r, starter = _convert(_a_deck(null, eosid=7, mid=7))
        self.assertEqual(_headers(starter, "/MAT/"), ["/MAT/HYD_VISC/7"])
        self.assertEqual(_headers(starter, "/EOS/"), ["/EOS/POLYNOMIAL/7"])
        rho = _cards(_block(starter, "/MAT/HYD_VISC/7"))[0]
        self.assertEqual(_col_f(rho, 1, 20), 1.0e-9)


class TestDuplicateEosScan(unittest.TestCase):
    """(A) The tenth deck-wide duplicate scan. Nine existed (/TH group, /PROP,
    /MAT, thermal, /PRELOAD, /SECT, /FUNCT, /IMPDISP, /INTER); /EOS had none,
    which is why only half of the 2Dlag double collision was reported."""

    def test_the_scan_fires_on_two_EOS_of_one_id(self):
        from k2rad.writer.assembly import _warn_duplicate_eos_ids
        st = ConversionState()
        _warn_duplicate_eos_ids(st, [
            "/MAT/LAW4/3", "/EOS/GRUNEISEN/3", "/MAT/HYD_VISC/3",
            "/EOS/POLYNOMIAL/3", "/MAT/ELAST/2", "/EOS/IDEAL-GAS/2",
        ])
        self.assertEqual(len(st.warnings), 1)
        w = st.warnings[0]
        self.assertIn("MATERIAL ID 3", w)
        self.assertIn("/EOS/GRUNEISEN/3", w)
        self.assertIn("/EOS/POLYNOMIAL/3", w)
        # The starter's own behaviour is the load-bearing fact: it does NOT
        # error, and the LAST block wins.
        self.assertIn("does NOT diagnose", w)
        self.assertIn("/EOS/POLYNOMIAL/3", w.split("LAST one wins")[0])

    def test_the_scan_is_silent_on_one_EOS_per_id(self):
        from k2rad.writer.assembly import _warn_duplicate_eos_ids
        st = ConversionState()
        _warn_duplicate_eos_ids(st, [
            "/MAT/LAW4/3", "/EOS/GRUNEISEN/3",
            "/MAT/HYD_VISC/4", "/EOS/POLYNOMIAL/4",
            "/MAT/LAW6/5", "/EOS/IDEAL-GAS/5",
        ])
        self.assertEqual(st.warnings, [])

    def test_the_regex_matches_the_hyphenated_spelling(self):
        """``/EOS/IDEAL-GAS`` is a real keyword; a ``[A-Z0-9_]`` class without
        ``-`` would silently never see it."""
        from k2rad.writer.assembly import _EOS_CARD_KIND_ID_RE
        m = _EOS_CARD_KIND_ID_RE.match("/EOS/IDEAL-GAS/9001")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "IDEAL-GAS")
        self.assertEqual(m.group(2), "9001")


# ─────────────────────────────────────────────────────────────────────────────
# (B) *INITIAL_STRESS_SHELL / _SOLID under *INCLUDE_TRANSFORM
# ─────────────────────────────────────────────────────────────────────────────

def _i8(*vals) -> str:
    """An I8 card — the width *ELEMENT_SHELL / _SOLID actually use. Writing
    them at I10 makes the offset walker read every cell one slot over, which
    is a deck bug, not a converter one; the reproducer must not have it."""
    out = "".join(f"{v:>8}" for v in vals)
    assert len(out) == 8 * len(vals), f"field overflow in {out!r}"
    return out


def _node16(nid, x, y, z) -> str:
    return f"{nid:>8}" + "".join(f"{c:>16.6f}" for c in (x, y, z))


_B_CHILD = "\n".join([
    "*KEYWORD", "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    _node16(5, 20.0, 0.0, 0.0), _node16(6, 20.0, 10.0, 0.0),
    _node16(7, 0.0, 0.0, 10.0), _node16(8, 10.0, 0.0, 10.0),
    _node16(9, 10.0, 10.0, 10.0), _node16(10, 0.0, 10.0, 10.0),
    "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4), _i8(2, 1, 2, 5, 6, 3),
    "*ELEMENT_SOLID", _i8(1, 2), _i8(1, 2, 3, 4, 7, 8, 9, 10),
    "*SECTION_SHELL", _row(1, 2, "", 2), _row("2.0", "2.0", "2.0", "2.0"),
    "*SECTION_SOLID", _row(2, 1),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "child shell", _row(1, 1, 1),
    "*PART", "child solid", _row(2, 2, 1),
    # Distinct values per slot so a column swap is detectable.
    "*INITIAL_STRESS_SHELL",
    _row(1, 1, 2, 0, 0, 0, 0, 0),
    _row("-1.0", "100.0", "50.0", "10.0", "7.0", "8.0", "9.0", "0.001"),
    _row("1.0", "110.0", "55.0", "11.0", "17.0", "18.0", "19.0", "0.002"),
    _row(2, 1, 2, 0, 0, 0, 0, 0),
    _row("-1.0", "200.0", "60.0", "20.0", "27.0", "28.0", "29.0", "0.003"),
    _row("1.0", "210.0", "65.0", "21.0", "37.0", "38.0", "39.0", "0.004"),
    "*INITIAL_STRESS_SOLID",
    _row(1, 1, 0, 0, 0, 0, 0, 0),
    _row("300.0", "70.0", "30.0", "4.0", "5.0", "6.0", "0.005"),
    "*END", ""])

_B_PARENT = "\n".join([
    "*KEYWORD", "*NODE",
    _node16(1001, 0.0, -100.0, 0.0), _node16(1002, 10.0, -100.0, 0.0),
    _node16(1003, 10.0, -90.0, 0.0), _node16(1004, 0.0, -90.0, 0.0),
    "*ELEMENT_SHELL", _i8(1, 101, 1001, 1002, 1003, 1004),
    "*SECTION_SHELL", _row(101, 2, "", 2),
    _row("1.0", "1.0", "1.0", "1.0"),
    "*MAT_ELASTIC", _row(101, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "parent shell", _row(101, 101, 101),
    "*INCLUDE_TRANSFORM", "childB.k",
    # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF IDDOFF — all distinct, so a
    # wrong bucket lands on a recognisably wrong number.
    _row(5000, 6000, 7000, 8000, 9000, 11000, 12000),
    "*END", ""])


def _convert_include_pair(parent: str, child: str):
    tmp = tempfile.TemporaryDirectory()
    with open(os.path.join(tmp.name, "childB.k"), "w") as fh:
        fh.write(child)
    path = os.path.join(tmp.name, "parentB.k")
    with open(path, "w") as fh:
        fh.write(parent)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


class TestInitialStressOffsetSpecs(unittest.TestCase):
    """(B) ``*INITIAL_STRESS_SHELL`` and ``_SOLID`` were registered directly in
    ``HANDLERS``, not through ``INITIAL_STATE_PRELOAD_KEYWORDS``, so
    ``_OFFSET_SPECS.get("INITIAL_STRESS_SHELL")`` was ``None`` and an
    ``*INCLUDE_TRANSFORM`` left their EIDs at the child deck's numbers while
    the mesh around them moved by IDEOFF.

    MEASURED on this exact pair at master 0c8968e: two "keyword has no offset
    map" warnings, then

        /INISHE/STRS_F/GLOB   shell_ID = 1     <- the PARENT deck's shell
        *INITIAL_STRESS_SHELL: element(s) 2 not found in the shell mesh
        *INITIAL_STRESS_SOLID: element(s) 1 not found in the solid mesh

    — one record on the wrong element (different part, different thickness,
    different place) and two dangling, with no /INIBRI block at all.
    """

    def setUp(self):
        self.res, self.starter = _convert_include_pair(_B_PARENT, _B_CHILD)

    def test_the_generic_no_offset_map_warning_is_gone(self):
        self.assertEqual(_warns(self.res, "has no offset map"), [])

    def test_no_stress_record_dangles(self):
        self.assertEqual(_warns(self.res, "not found in the shell mesh"), [])
        self.assertEqual(_warns(self.res, "not found in the solid mesh"), [])

    def test_the_shell_record_lands_on_the_offset_child_element(self):
        """EID 1 + IDEOFF 6000 = 6001, and 6001 is a row of /SHELL/7001 (the
        child's part, PID 1 + IDPOFF 7000) — NOT the parent's shell 1."""
        card1 = _cards(_block(self.starter, "/INISHE/STRS_F/GLOB"))[0]
        self.assertEqual(_col_i(card1, 1, 10), 6001)
        self.assertIn("      6001      5001      5002      5003      5004",
                      self.starter)

    def test_the_solid_record_lands_on_the_offset_child_element(self):
        card1 = _cards(_block(self.starter, "/INIBRI/STRS_FGLO"))[0]
        self.assertEqual(_col_i(card1, 1, 10), 6001)

    def test_the_stress_VALUES_are_untouched_by_the_offset(self):
        """The offsetter must rewrite card 1 ONLY. Every stress component is a
        float, and ``_rewrite_line`` calls a token an id when
        ``to_int(tok) > 0`` — a ``{"data": ...}`` spec would have turned the
        10.0 shear into ``10 + 6000``."""
        pts = _cards(_block(self.starter, "/INISHE/STRS_F/GLOB"))[2:]
        # layer 1: sigma_X sigma_Y sigma_Z on row 1; XY YZ ZX eps_p pos_nip
        # on row 2. Distinct per slot, so a swap fails.
        self.assertEqual(_col_f(pts[0], 1, 20), 100.0)     # sigma_X
        self.assertEqual(_col_f(pts[0], 21, 40), 50.0)     # sigma_Y
        self.assertEqual(_col_f(pts[0], 41, 60), 10.0)     # sigma_Z
        self.assertEqual(_col_f(pts[1], 1, 20), 7.0)       # sigma_XY
        self.assertEqual(_col_f(pts[1], 21, 40), 8.0)      # sigma_YZ
        self.assertEqual(_col_f(pts[1], 41, 60), 9.0)      # sigma_ZX
        self.assertEqual(_col_f(pts[1], 61, 80), 0.001)    # eps_p
        self.assertEqual(_col_f(pts[1], 81, 100), -1.0)    # pos_nip

    def test_every_INITIAL_keyword_has_an_offset_spec(self):
        """The #116 property, over the whole family rather than the four
        keywords ``INITIAL_STATE_PRELOAD_KEYWORDS`` used to hold. The audit
        that found (B) also found *INITIAL_VOLUME_FRACTION_GEOMETRY."""
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import HANDLERS
        missing = sorted(k for k in HANDLERS
                         if k.startswith("INITIAL") and k not in _OFFSET_SPECS)
        self.assertEqual(missing, [])

    def test_the_stress_keywords_are_registered_through_the_shared_dict(self):
        """Registered in ``INITIAL_STATE_PRELOAD_KEYWORDS``, which is the dict
        assembly.py keys the offset table off — so a future spelling cannot be
        readable and un-offsettable again."""
        from k2rad.handlers import INITIAL_STATE_PRELOAD_KEYWORDS
        for kw in ("INITIAL_STRESS_SHELL", "INITIAL_STRESS_SOLID"):
            with self.subTest(kw=kw):
                self.assertIn(kw, INITIAL_STATE_PRELOAD_KEYWORDS)


class TestInitialStressRecordWalkers(unittest.TestCase):
    """(B) The offsetter and the handler are driven by ONE walker each, so the
    two can never disagree about which raw row is a card 1 (#116/#119)."""

    def test_a_blank_stress_card_does_not_swallow_the_next_record(self):
        """An all-blank stress card is legal LS-DYNA (every component defaults
        to 0.0). A "next non-blank row" walk would step over it and read the
        FOLLOWING element's card 1 as this element's stress card, then read
        the next stress card as a card 1 — the #119 class."""
        from k2rad.handlers import initial_stress_shell_records
        raw = [
            _row(11, 1, 2, 0, 0, 0, 0, 0),
            "",                                   # layer 1: all defaults
            _row("1.0", "1.0", "2.0", "3.0", "0.0", "0.0", "0.0", "0.0"),
            _row(22, 1, 1, 0, 0, 0, 0, 0),
            _row("0.0", "9.0", "8.0", "7.0", "0.0", "0.0", "0.0", "0.0"),
        ]
        recs = list(initial_stress_shell_records(raw))
        self.assertEqual([r[1][0] for r in recs], [11, 22])
        self.assertEqual([r[0] for r in recs], [0, 3])
        self.assertEqual([r[2] for r in recs], [[1, 2], [4]])
        self.assertEqual([r[3] for r in recs], [False, False])

    def test_a_stress_value_that_looks_like_an_id_is_not_offset(self):
        """The reason a declarative ``data`` spec is unusable: a stress of 1.5
        reads back through ``to_int`` as the id 1."""
        child = _B_CHILD.replace(
            _row("-1.0", "100.0", "50.0", "10.0", "7.0", "8.0", "9.0",
                 "0.001"),
            _row("-1.0", "1.5", "2.5", "3.5", "7.0", "8.0", "9.0", "0.001"))
        _res, starter = _convert_include_pair(_B_PARENT, child)
        pts = _cards(_block(starter, "/INISHE/STRS_F/GLOB"))[2:]
        self.assertEqual(_col_f(pts[0], 1, 20), 1.5)
        self.assertEqual(_col_f(pts[0], 21, 40), 2.5)
        self.assertEqual(_col_f(pts[0], 41, 60), 3.5)

    def test_the_walkers_reproduce_the_handlers_skips(self):
        """Blank rows and ``EID <= 0`` rows are skipped by BOTH walks — the
        handler's own two ``continue``s."""
        from k2rad.handlers import (initial_stress_shell_records,
                                    initial_stress_solid_records)
        shell = ["", _row(0, 1, 1, 0, 0, 0, 0, 0),
                 _row(7, 1, 1, 0, 0, 0, 0, 0),
                 _row("0.0", "1.0", "2.0", "3.0", "0.0", "0.0", "0.0", "0.0")]
        self.assertEqual([r[1][0] for r in initial_stress_shell_records(shell)],
                         [7])
        solid = ["", _row(0, 1, 0, 0, 0, 0, 0, 0),
                 _row(9, 1, 0, 0, 0, 0, 0, 0),
                 _row("1.0", "2.0", "3.0", "0.0", "0.0", "0.0", "0.0")]
        self.assertEqual([r[1][0] for r in initial_stress_solid_records(solid)],
                         [9])

    def test_a_truncated_block_stops_the_walk(self):
        """Mirrors the handler's ``break``: the record is yielded with
        ``truncated`` set and nothing after it is read."""
        from k2rad.handlers import initial_stress_shell_records
        raw = [_row(11, 1, 3, 0, 0, 0, 0, 0),
               _row("0.0", "1.0", "2.0", "3.0", "0.0", "0.0", "0.0", "0.0")]
        recs = list(initial_stress_shell_records(raw))
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0][3])


class TestVolumeFractionGeometryOffsets(unittest.TestCase):
    """(B) bonus: *INITIAL_VOLUME_FRACTION_GEOMETRY's FMSID lives in TWO id
    namespaces selected by FMIDTYP beside it (0 = part set, 1 = part) — the
    #125 "one cell, two id namespaces" class."""

    def _off(self, fmidtyp: int):
        from k2rad.assembly import _off_initial_volume_fraction_geometry
        from k2rad.parser import Block
        b = Block(keyword="INITIAL_VOLUME_FRACTION_GEOMETRY", options=[],
                  raw=[_row(4, fmidtyp, 1, 0), _row(1, 1, 2)])
        _off_initial_volume_fraction_geometry(
            b, {"p": 7000, "s": 9000, "e": 6000, "n": 5000}, lambda *_a: None)
        return b.raw

    def test_FMIDTYP_1_is_a_PART_id(self):
        raw = self._off(1)
        self.assertEqual(_col_i(raw[0], 1, 10), 7004)      # 4 + IDPOFF

    def test_FMIDTYP_0_is_a_PART_SET_id(self):
        raw = self._off(0)
        self.assertEqual(_col_i(raw[0], 1, 10), 9004)      # 4 + IDSOFF

    def test_the_container_cards_are_left_alone(self):
        """CONTTYP/FILLOPT/FAMMG are enumerations and an ALE group number, in
        none of the seven buckets — and this converter reads nothing else off
        those rows, so no dangling reference can result."""
        for fmidtyp in (0, 1):
            with self.subTest(fmidtyp=fmidtyp):
                self.assertEqual(self._off(fmidtyp)[1], _row(1, 1, 2))


if __name__ == "__main__":            # pragma: no cover
    unittest.main()
