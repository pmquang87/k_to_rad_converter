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


def _group_by_title(starter: str, prefix: str, title: str):
    """The one ``prefix``-headed block whose TITLE line is ``title``. Several
    /GRNOD/NODE blocks coexist in any real deck (rigid-body groups, contact
    groups, ...), so a block has to be picked by what it IS, not by position."""
    found = [b for b in _blocks(starter, prefix) if b[1].strip() == title]
    assert len(found) == 1, f"expected one {title!r} block, got {len(found)}"
    return found[0]


def _group_nids(block):
    return sorted(int(t) for ln in _cards(block) for t in ln.split())


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


# ─────────────────────────────────────────────────────────────────────────────
# (C) /DAMP on a model with no shells and no solids
# ─────────────────────────────────────────────────────────────────────────────

_C_DECK = "\n".join([
    "*KEYWORD", "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 100.0, 0.0, 0.0),
    _node16(3, 200.0, 0.0, 0.0), _node16(4, 300.0, 0.0, 0.0),
    _node16(5, 400.0, 0.0, 0.0),
    "*ELEMENT_BEAM", _i8(10, 1, 1, 2, 0), _i8(11, 1, 2, 3, 0),
    "*ELEMENT_DISCRETE", _i8(20, 2, 3, 4, 0),
    "*ELEMENT_MASS", f"{30:>8}{5:>8}" + f"{'1.0E-6':>16}",
    "*SECTION_BEAM", _row(1, 2, "1.0"),
    _row("100.0", "833.33", "833.33", "1406.0"),
    "*SECTION_DISCRETE", _row(2, 0), _row("0.0", "1.0", "0.0", "0.0"),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*MAT_SPRING_ELASTIC", _row(2, "100.0"),
    "*PART", "beams", _row(1, 1, 1),
    "*PART", "spring", _row(2, 2, 2),
    "*BOUNDARY_SPC_NODE", _row(1, 0, 1, 1, 1, 1, 1, 1),
    "*DAMPING_GLOBAL", _row(0, "10.0"),
    "*CONTROL_TERMINATION", _row("0.001"),
    "*END", ""])


class TestDampingReachesEveryElementFamily(unittest.TestCase):
    """(C) ``*DAMPING_GLOBAL`` emitted NO ``/DAMP`` at all on a model built
    from beams, springs and a lumped mass.

    Both target-node arms of ``_make_damping`` walked four registries —
    ``shell_elems | solid_elems | tshell_elems | sph_elems`` — so on this deck
    both were empty and the writer took its
    ``"no target deformable nodes found - /DAMP not emitted"`` exit. MEASURED
    at master 0c8968e on this exact deck: that warning, and ``grep -c '^/DAMP'``
    = 0. The model ran completely undamped with VALDMP = 10.0 in the deck.

    The scope was never a property of ``/DAMP``: ``hm_read_damp.F:415-429``
    validates only the group ID, ``hm_lecgrn.F:538-550`` collects beam, truss
    and spring nodes into a ``/GRNOD/PART``, and ``damping.F:148-150`` walks
    ``IGRNOD(IGR)%ENTITY`` with the sole exclusion ``TAGSLV_RBY(I)==0``.
    Measured on a spring-only oscillator: alpha recovered as 600.000132 from an
    input of 600.

    The emitted deck was run: starter 0 ERROR / 0 WARNING, engine NORMAL
    TERMINATION, 59 cycles.
    """

    def setUp(self):
        self.res, self.starter = _convert(_C_DECK)

    def test_a_DAMP_card_is_emitted(self):
        self.assertEqual(len(_headers(self.starter, "/DAMP/")), 1)
        self.assertEqual(_warns(self.res, "no target deformable nodes"), [])

    def test_the_group_holds_the_beam_spring_and_mass_nodes(self):
        """Nodes 1-3 from the two beams, 3-4 from the discrete spring, 5 from
        *ELEMENT_MASS. All five, none missing, nothing invented."""
        grp = _group_by_title(self.starter, "/GRNOD/NODE/",
                              "damping_target_all_deformable")
        self.assertEqual(_group_nids(grp), [1, 2, 3, 4, 5])

    def test_the_card_columns_are_exact(self):
        """/DAMP card 1 is ``Alpha(20) Beta(20) grnod_ID(10) skew_ID(10)
        Tstart(20) Tstop(20)`` — Damp.cfg:131. Beta must be written
        EXPLICITLY as 0: there is no alpha-only layout, and an omitted Beta
        puts the grnod_ID digits in cols 21-40."""
        card = _cards(_block(self.starter, "/DAMP/"))[0]
        grp = _group_by_title(self.starter, "/GRNOD/NODE/",
                              "damping_target_all_deformable")
        grp_id = int(grp[0].rsplit("/", 1)[1])
        self.assertEqual(_col_f(card, 1, 20), 10.0)        # Alpha = VALDMP 1:1
        self.assertEqual(_col_f(card, 21, 40), 0.0)        # Beta
        self.assertEqual(_col_i(card, 41, 50), grp_id)     # grnod_ID
        self.assertEqual(_col_i(card, 51, 60), 0)          # skew_ID
        self.assertEqual(_col_f(card, 61, 80), 0.0)        # Tstart
        self.assertEqual(_col_f(card, 81, 100), 1.0E30)    # Tstop

    def test_grnod_id_is_never_zero(self):
        """``grnod_ID = 0`` is not "all nodes": it is starter
        ``ERROR ID : 171 ... RAYLEIGH DAMPING NONEXISTENT / NODE GROUP ID=0
        DOES NOT EXIST``."""
        card = _cards(_block(self.starter, "/DAMP/"))[0]
        self.assertNotEqual(_col_i(card, 41, 50), 0)


class TestDampingGlobalCardIsFixedFormat(unittest.TestCase):
    """(C) side defect on the same card: ``handle_damping_global`` split card 1
    free-format. ``*DAMPING_GLOBAL`` is fixed I10/E10 (Vol I R17 p.15-8) and a
    blank INTERIOR column is ordinary, so a free split shifted every later
    field one slot left."""

    def test_a_blank_interior_column_does_not_shift_the_scale_factors(self):
        # LCID VALDMP STX STY [STZ blank] SRX SRY SRZ — the free split reads
        # SRX as STZ and loses SRZ entirely.
        card = _row(0, "500", "1.0", "1.0", "", "2.0", "2.0", "2.0")
        st = _dispatch("*KEYWORD\n*DAMPING_GLOBAL\n" + card + "\n*END\n")
        d = st.damping_global
        self.assertEqual(d.valdmp, 500.0)
        self.assertEqual((d.stx, d.sty, d.stz), (1.0, 1.0, 0.0))
        self.assertEqual((d.srx, d.sry, d.srz), (2.0, 2.0, 2.0))

    def test_a_full_card_is_unchanged(self):
        """The regression fence: with no blank interior column the fixed and
        free splits agree, so no ordinary deck moves."""
        card = _row(0, "500", "1.0", "2.0", "3.0", "4.0", "5.0", "6.0")
        d = _dispatch("*KEYWORD\n*DAMPING_GLOBAL\n" + card
                      + "\n*END\n").damping_global
        self.assertEqual((d.stx, d.sty, d.stz, d.srx, d.sry, d.srz),
                         (1.0, 2.0, 3.0, 4.0, 5.0, 6.0))


class TestDampingRigidMassCentre(unittest.TestCase):
    """(C) ``*DAMPING_GLOBAL`` "applies globally to the nodes of deformable
    bodies AND TO THE MASS CENTER OF THE RIGID BODIES" (Vol I R17 p.15-8).

    k2rad excluded every rigid node, main included, so rigid-body motion went
    undamped where LS-DYNA damps it. Putting the MAIN node in the group is
    exactly right and needs no extra filtering: ``rbyonf.F:181-192`` fills
    ``TAGSLV_RBY`` from ``LPBY``, the SECONDARY list only, so ``damping.F:150``
    skips the secondaries by itself and leaves the main node damped.
    """

    DECK = "\n".join([
        "*KEYWORD", "*NODE",
        _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
        _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
        _node16(5, 20.0, 0.0, 0.0), _node16(6, 20.0, 10.0, 0.0),
        "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4), _i8(2, 2, 2, 5, 6, 3),
        "*SECTION_SHELL", _row(1, 2, "", 2),
        _row("1.0", "1.0", "1.0", "1.0"),
        "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
        "*MAT_RIGID", _row(2, "7.85E-9", "2.1E5", "0.3"),
        _row("0.0", 7, 7), _row("0.0", "0.0", "0.0"),
        "*PART", "deformable", _row(1, 1, 1),
        "*PART", "rigid", _row(2, 1, 2),
        "*DAMPING_GLOBAL", _row(0, "10.0"),
        "*END", ""])

    def test_the_rigid_main_node_is_in_the_group_and_its_secondaries_are_not(self):
        _res, starter = _convert(self.DECK)
        ids = set(_group_nids(_group_by_title(
            starter, "/GRNOD/NODE/", "damping_target_all_deformable")))
        # The /RBODY main node is the sole member of its own rb_indnode group.
        main_grp = _group_by_title(starter, "/GRNOD/NODE/", "rb_indnode_pid2")
        main = _group_nids(main_grp)[0]
        self.assertIn(main, ids)
        # It is a SYNTHESIZED element-free node, not one of the six mesh ones.
        self.assertNotIn(main, range(1, 7))
        # The rigid part's own mesh nodes (5, 6 and the shared 2, 3) are
        # SECONDARIES and stay out; the engine would skip them anyway.
        self.assertNotIn(5, ids)
        self.assertNotIn(6, ids)
        # ... while the purely deformable corners are in.
        self.assertIn(1, ids)
        self.assertIn(4, ids)


# ─────────────────────────────────────────────────────────────────────────────
# (D) /INISH3/STRS_F — initial stress on a 3-node shell
# ─────────────────────────────────────────────────────────────────────────────

def _d_deck(with_tri_stress: bool = True, with_quad_strain: bool = True):
    """A quad (eid 1) and a tri (eid 2) on one *SECTION_SHELL with NIP 3.

    Distinct values per slot and per element, so a column swap or an
    element mix-up is detectable.
    """
    stress = ["*INITIAL_STRESS_SHELL",
              _row(1, 1, 3, 0, 0, 0, 0, 0),
              _row("-1.0", "100.0", "50.0", "10.0", "7.0", "8.0", "9.0",
                   "0.001"),
              _row("0.0", "101.0", "51.0", "11.0", "7.1", "8.1", "9.1",
                   "0.002"),
              _row("1.0", "102.0", "52.0", "12.0", "7.2", "8.2", "9.2",
                   "0.003")]
    if with_tri_stress:
        stress += [
            _row(2, 1, 3, 0, 0, 0, 0, 0),
            _row("-1.0", "200.0", "60.0", "20.0", "17.0", "18.0", "19.0",
                 "0.004"),
            _row("0.0", "201.0", "61.0", "21.0", "17.1", "18.1", "19.1",
                 "0.005"),
            _row("1.0", "202.0", "62.0", "22.0", "17.2", "18.2", "19.2",
                 "0.006")]
    strain = ["*INITIAL_STRAIN_SHELL", _row(1, 1, 2),
              _row("0.0", 0, 0, 0, 0, 0, "-1.0"),
              _row("0.001", 0, 0, 0, 0, 0, "1.0")] if with_quad_strain else []
    return "\n".join([
        "*KEYWORD", "*NODE",
        _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
        _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
        _node16(5, 20.0, 5.0, 0.0),
        "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4), _i8(2, 1, 2, 5, 3, 3),
        "*SECTION_SHELL", _row(1, 2, "", 3),
        _row("2.0", "2.0", "2.0", "2.0"),
        "*MAT_PLASTIC_KINEMATIC",
        _row(1, "7.85E-9", "2.1E5", "0.3", "1.0E6", "0.0"),
        "*PART", "strip", _row(1, 1, 1),
    ] + stress + strain + ["*CONTROL_TERMINATION", _row("0.0001"),
                           "*END", ""])


class TestInish3StressEmission(unittest.TestCase):
    """(D) An ``*INITIAL_STRESS_SHELL`` record on a 3-node shell was DROPPED,
    under a warning whose cited fact was FALSE: it said ``/INISH3/STRS_F`` "is
    a different card layout this converter does not write yet", and the code
    comment beside it said "the card layout differs".

    ``diff`` of the extracted ``FORMAT(radioss2021)`` blocks of
    ``radioss2021/TABLE/inish3_strs_f_glob_sub.cfg`` and
    ``inishe_strs_f_glob_sub.cfg`` is EMPTY. The only substantive difference in
    the two FILES is the HyperMesh-only
    ``SUBTYPES = ( /ELEMS/SH3N )`` vs ``( /ELEMS/SHELL )``. Same columns, same
    order (the #131 "check a warning's CITED FACT" class).

    MEASURED end to end on a MIXED deck (quad stress + tri stress + quad
    strain, which is the #127 shape that used to raise ERROR 26 + ERROR 1904):
    starter 0 ERROR / 0 WARNING, engine NORMAL TERMINATION, 70 cycles. And
    CONSUMED, not merely accepted — with/without twin, identical decks apart
    from the /INISH3/STRS_F block::

        cycle 1        with /INISH3     control
        I-ENERGY         -11.75          -4.125
        K-ENERGY T         5.468          1.705
        K-ENERGY R         0.1782         0.06210
        TOTAL MASS       0.2355E-05     0.2355E-05   (identical)
    """

    def setUp(self):
        self.res, self.starter = _convert(_d_deck())

    def test_both_stress_blocks_are_emitted(self):
        self.assertEqual(_headers(self.starter, "/INISHE/STRS_F"),
                         ["/INISHE/STRS_F/GLOB"])
        self.assertEqual(_headers(self.starter, "/INISH3/STRS_F"),
                         ["/INISH3/STRS_F/GLOB"])

    def test_the_tri_card_1_columns_are_exact(self):
        """``shell_ID(10) nb_integr(10) npg(10) Thick(20)``. nb_integr must be
        the /PROP/SHELL N; ``npg`` must be 1, never 4."""
        cards = _cards(_block(self.starter, "/INISH3/STRS_F/GLOB"))
        self.assertEqual(_col_i(cards[0], 1, 10), 2)      # the TRI, not the quad
        self.assertEqual(_col_i(cards[0], 11, 20), 3)     # nb_integr = NIP
        self.assertEqual(_col_i(cards[0], 21, 30), 1)     # npg
        self.assertEqual(_col_f(cards[0], 31, 50), 0.0)   # Thick

    def test_npg_is_one_on_the_tri_and_four_on_the_quad(self):
        """The npg rules are OPPOSITE on the two paths and must not be shared.
        k2rad writes ``Ish3n = 0``, so a /SH3N is initialised through
        ``c3init3 -> CSIGINI``, whose check is ``NPGI > 1`` (csigini.F:143) —
        measured ERROR 26 for npg 3 and 4, clean for 0 and 1. The quad's
        ``npg = 4`` comes from ``scigini4.F:160`` on the batch-integrated
        ``cbainit3`` path and does not transfer."""
        tri = _cards(_block(self.starter, "/INISH3/STRS_F/GLOB"))
        quad = _cards(_block(self.starter, "/INISHE/STRS_F/GLOB"))
        self.assertEqual(_col_i(tri[0], 21, 30), 1)
        self.assertEqual(_col_i(quad[0], 21, 30), 4)

    def test_the_tri_payload_columns_are_exact_and_bottom_first(self):
        """Layer 1 is the LOWER surface (measured: a -100/0/+100 record reads
        back lower/membrane/upper on the ANIM). Every slot carries a distinct
        value, so a swap fails rather than coinciding."""
        pts = _cards(_block(self.starter, "/INISH3/STRS_F/GLOB"))[2:]
        # npg = 1, so exactly 2 rows per layer, 3 layers.
        self.assertEqual(len(pts), 6)
        self.assertEqual(_col_f(pts[0], 1, 20), 200.0)      # sigma_X
        self.assertEqual(_col_f(pts[0], 21, 40), 60.0)      # sigma_Y
        self.assertEqual(_col_f(pts[0], 41, 60), 20.0)      # sigma_Z
        self.assertEqual(_col_f(pts[1], 1, 20), 17.0)       # sigma_XY
        self.assertEqual(_col_f(pts[1], 21, 40), 18.0)      # sigma_YZ
        self.assertEqual(_col_f(pts[1], 41, 60), 19.0)      # sigma_ZX
        self.assertEqual(_col_f(pts[1], 61, 80), 0.004)     # eps_p
        self.assertEqual(_col_f(pts[1], 81, 100), -1.0)     # pos_nip, BOTTOM
        self.assertEqual(_col_f(pts[5], 81, 100), 1.0)      # ... TOP last

    def test_the_quad_block_holds_only_the_quad(self):
        """The split is by TOPOLOGY, and each reader resolves against its own
        table — ``UEL2SYS(..., KSYSUSR, NUMELC)`` for /INISHE,
        ``UEL2SYS(ID_ELEM, KSYSUSRTG, NUMELTG)`` at
        hm_read_inistate_d00.F:3285 for /INISH3. A tri id in the /INISHE block
        resolves to nothing."""
        quad = _cards(_block(self.starter, "/INISHE/STRS_F/GLOB"))
        heads = [_col_i(ln, 1, 10) for ln in quad if len(ln) == 50]
        self.assertEqual(heads, [1])

    def test_the_tri_gets_an_all_zero_STRAIN_companion(self):
        """The #127 cross-family rule, on the /INISH3 side. ITHKSHEL = 2 is set
        by ANY STRA_F block (hm_read_inistate_d00.F:2469, :3597) and is
        GLOBAL: the QUAD's strain block un-gates the check for the TRI's
        stress record, and csigini.F:190 then reads Z1 == Z2 == 0 and raises
        ERROR 1904 — whose own message names "/INISHE/STRA_F/GLOB OR
        /INISH3/STRA_F/GLOB"."""
        tri = _cards(_block(self.starter, "/INISH3/STRA_F/GLOB"))
        self.assertEqual([_col_i(tri[0], 1, 10), _col_i(tri[0], 11, 20),
                          _col_i(tri[0], 21, 30)], [2, 3, 1])
        self.assertTrue(all(_col_f(ln, 1, 20) == 0.0 for ln in tri[1:]))
        w = _warns(self.res, "an all-zero record was added")
        self.assertEqual(len(w), 1)
        # ... and the message names the card it actually went into (#131).
        self.assertIn("/INISH3/STRA_F/GLOB (element(s) 2)", w[0])

    def test_the_false_layout_claim_is_gone(self):
        for phrase in ("different card layout",
                       "model those elements as quads"):
            with self.subTest(phrase=phrase):
                self.assertFalse([w for w in self.res.warnings
                                  if phrase in w])

    def test_a_duplicate_record_keeps_the_first_and_warns(self):
        """``hm_yctrl.F:719-724`` allocates ONE slot per element, so the
        starter takes both records at 0 ERROR / 0 WARNING and the LAST one
        silently wins (measured: 100/50/25 then 10/20/30 gave F1=10 F2=20
        F12=30 at t=0). The converter keeps the FIRST and says so."""
        dup = _d_deck().replace(
            "*CONTROL_TERMINATION",
            "*INITIAL_STRESS_SHELL\n" + _row(2, 1, 3, 0, 0, 0, 0, 0) + "\n"
            + _row("-1.0", "999.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
            + "\n"
            + _row("0.0", "999.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
            + "\n"
            + _row("1.0", "999.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
            + "\n*CONTROL_TERMINATION")
        res, starter = _convert(dup)
        pts = _cards(_block(starter, "/INISH3/STRS_F/GLOB"))[2:]
        self.assertEqual(_col_f(pts[0], 1, 20), 200.0)   # the FIRST record
        self.assertNotIn("999", starter)
        w = _warns(res, "named by more than one record")
        self.assertTrue(w)
        self.assertIn("LAST one silently winning", w[0])


class TestInish3StressWithoutStrain(unittest.TestCase):
    """(D) The single-keyword shape — stress on both topologies, no strain
    block anywhere. ITHKSHEL stays 0, so no companion is needed and none is
    written. Measured clean (row 3 of the cross-check matrix)."""

    def test_no_companion_is_invented_when_no_strain_block_exists(self):
        res, starter = _convert(_d_deck(with_quad_strain=False))
        self.assertEqual(_headers(starter, "/INISHE/STRS_F"),
                         ["/INISHE/STRS_F/GLOB"])
        self.assertEqual(_headers(starter, "/INISH3/STRS_F"),
                         ["/INISH3/STRS_F/GLOB"])
        self.assertEqual(_headers(starter, "/INISH3/STRA_F"), [])
        self.assertEqual(_headers(starter, "/INISHE/STRA_F"), [])
        self.assertEqual(_warns(res, "an all-zero record was added"), [])


# ─────────────────────────────────────────────────────────────────────────────
# (E) the /SECT reporting frame   +   (F) the _plane_cut spring arm
# ─────────────────────────────────────────────────────────────────────────────

def _ef_deck(card2: str = None, extra_pre: str = "") -> str:
    """A shell strip along +X (0..40), a beam and a discrete spring that both
    span x = 20..30, and a cutting plane at x = 25 with normal +X.

    Every geometric quantity is chosen so the expected frame is exact and
    hand-checkable: N1 = (25,0,0), e1 = +Y (the card's edge vector L), e2 =
    n x e1 = +Z, hence e6 = (N2-N1) x (N3-N1) = +X.
    """
    if card2 is None:
        # XHEV YHEV ZHEV LENL LENM ID ITYPE — the edge vector head is
        # (25,1,0), so L = head - (XCT,YCT,ZCT) = (0,1,0) = +Y.
        card2 = _row("25.0", "1.0", "0.0", "0.0", "0.0", 0, 0)
    return "\n".join([
        "*KEYWORD", "*NODE",
        _node16(1, 0.0, 0.0, 0.0), _node16(2, 20.0, 0.0, 0.0),
        _node16(3, 20.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
        _node16(5, 30.0, 0.0, 0.0), _node16(6, 30.0, 10.0, 0.0),
        _node16(7, 40.0, 0.0, 0.0), _node16(8, 40.0, 10.0, 0.0),
        _node16(20, 20.0, -10.0, 0.0), _node16(21, 30.0, -10.0, 0.0),
        _node16(30, 20.0, -20.0, 0.0), _node16(31, 30.0, -20.0, 0.0),
        "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4), _i8(2, 1, 2, 5, 6, 3),
        _i8(3, 1, 5, 7, 8, 6),
        "*ELEMENT_BEAM", _i8(20, 2, 20, 21, 0),
        "*ELEMENT_DISCRETE", _i8(10, 3, 30, 31, 0),
        "*SECTION_SHELL", _row(1, 2, "", 2),
        _row("1.0", "1.0", "1.0", "1.0"),
        "*SECTION_BEAM", _row(2, 2, "1.0"),
        _row("100.0", "833.33", "833.33", "1406.0"),
        "*SECTION_DISCRETE", _row(3, 0), _row("0.0", "1.0", "0.0", "0.0"),
        "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
        "*MAT_SPRING_ELASTIC", _row(3, "100.0"),
        "*PART", "strip", _row(1, 1, 1),
        "*PART", "beam", _row(2, 2, 1),
        "*PART", "spring", _row(3, 3, 3),
        extra_pre,
        "*DATABASE_CROSS_SECTION_PLANE_ID", f"{11:>10}" + "cut at x=25",
        _row(0, "25.0", "0.0", "0.0", "26.0", "0.0", "0.0", "0.0"),
        card2,
        "*DATABASE_SECFORC", _row("1.0E-5"),
        "*CONTROL_TERMINATION", _row("0.0002"),
        "*END", ""])


def _sect_card(starter: str, sid: int):
    return _cards(_block(starter, f"/SECT/{sid}"))


def _node_xyz(starter: str, nid: int):
    """The coordinates of a /NODE row, from any /NODE block in the deck."""
    for blk in _blocks(starter, "/NODE"):
        for ln in blk:
            if ln.startswith("/NODE") or ln.startswith("#"):
                continue
            if _col_i(ln, 1, 10) == nid:
                return (_col_f(ln, 11, 30), _col_f(ln, 31, 50),
                        _col_f(ln, 51, 70))
    raise AssertionError(f"node {nid} not found")


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


class TestSectFrameIsBuiltFromTheCard(unittest.TestCase):
    """(E) The /SECT output frame was CONDITIONING-PICKED: N1 = the lowest node
    id of the cut, N2 = the farthest node, N3 = the node making the largest
    triangle. None of XCT/YCT/ZCT, XCH/YCH/ZCH or XHEV/YHEV/ZHEV was read.

    That frame is not decoration. ``section_skew.F:82-99`` makes
    ``e6 = (N2-N1) x (N3-N1)`` the section NORMAL and ``section_c.F:385-389``
    splits every nodal force with it (``FN = FSX*XXN + ...``,
    ``FST = FS - FN``), while ``:393-397`` takes the moments about the frame
    ORIGIN.

    MEASURED on this exact deck at master 0c8968e: the picked frame was nodes
    2 (20,0,0), 6 (30,10,0), 21 (30,-10,0), whose

        e6 = (0, 0, -1)      -- 90.00 degrees off the card's (1,0,0)
        C  = (20, 0, 0)      -- the plane is x = 25; the origin is not on it

    at 0 starter ERROR. On a cantilever probe the same defect cost 89.6 % of
    the true normal force, gave 1.34x the true tangential force, and moved
    every moment component.
    """

    def setUp(self):
        self.res, self.starter = _convert(_ef_deck())
        self.card = _sect_card(self.starter, 11)[0]
        self.n1 = _col_i(self.card, 1, 10)
        self.n2 = _col_i(self.card, 11, 20)
        self.n3 = _col_i(self.card, 21, 30)

    def test_N1_is_the_cutting_planes_own_origin(self):
        self.assertEqual(_node_xyz(self.starter, self.n1), (25.0, 0.0, 0.0))

    def test_the_cross_product_is_the_cards_normal_exactly(self):
        """``e6 = (N2-N1) x (N3-N1)``, normalised, must be the card's
        ``XCT->XCH`` direction — here (1,0,0)."""
        p1 = _node_xyz(self.starter, self.n1)
        p2 = _node_xyz(self.starter, self.n2)
        p3 = _node_xyz(self.starter, self.n3)
        c = _cross([p2[k] - p1[k] for k in range(3)],
                   [p3[k] - p1[k] for k in range(3)])
        n = sum(v * v for v in c) ** 0.5
        self.assertGreater(n, 0.0)
        for k, want in enumerate((1.0, 0.0, 0.0)):
            self.assertAlmostEqual(c[k] / n, want, places=12)

    def test_the_first_axis_is_the_cards_edge_vector_L(self):
        """``e4 = normalize(N2-N1)`` must be the card-2 edge vector L
        projected into the plane — here (0,1,0)."""
        p1 = _node_xyz(self.starter, self.n1)
        p2 = _node_xyz(self.starter, self.n2)
        v = [p2[k] - p1[k] for k in range(3)]
        n = sum(x * x for x in v) ** 0.5
        for k, want in enumerate((0.0, 1.0, 0.0)):
            self.assertAlmostEqual(v[k] / n, want, places=12)

    def test_the_Iframe0_origin_lands_on_N1(self):
        """``Iframe = 0`` puts the moment reference at
        ``C = N1 + ((N3-N1).e4)*e4`` (section_skew.F:147-150). Because e1 and
        e2 are ORTHOGONAL by construction that dot product is 0, so C = N1 =
        the plane origin — which is why Iframe stays 0 rather than moving to
        1/2 (the section-node centroid, a different point)."""
        p1 = _node_xyz(self.starter, self.n1)
        p2 = _node_xyz(self.starter, self.n2)
        p3 = _node_xyz(self.starter, self.n3)
        e4 = [(p2[k] - p1[k]) for k in range(3)]
        m = sum(x * x for x in e4) ** 0.5
        e4 = [x / m for x in e4]
        d = sum((p3[k] - p1[k]) * e4[k] for k in range(3))
        self.assertAlmostEqual(d, 0.0, places=12)
        self.assertEqual(_col_i(_sect_card(self.starter, 11)[2], 91, 100), 0)

    def test_the_frame_nodes_are_synthesized_not_mesh_nodes(self):
        """Element-free nodes, exactly as #127's preload /SECT does. They never
        move, so the reporting frame is fixed in space — LS-DYNA's own default
        when the card names no output frame."""
        for nid in (self.n1, self.n2, self.n3):
            with self.subTest(nid=nid):
                self.assertNotIn(nid, range(1, 32))
        w = _warns(self.res, "SYNTHESIZED element-free nodes")
        self.assertEqual(len(w), 1)
        for nid in (self.n1, self.n2, self.n3):
            self.assertIn(str(nid), w[0])

    def test_a_card_without_an_edge_vector_still_gets_the_right_normal(self):
        """XHEV/YHEV/ZHEV is optional; only the IN-PLANE axis is then
        synthesized. The NORMAL must still be exact."""
        _res, starter = _convert(_ef_deck(card2=_row("", "", "", "", "", 0, 0)))
        card = _sect_card(starter, 11)[0]
        p = [_node_xyz(starter, _col_i(card, a, b))
             for a, b in ((1, 10), (11, 20), (21, 30))]
        c = _cross([p[1][k] - p[0][k] for k in range(3)],
                   [p[2][k] - p[0][k] for k in range(3)])
        n = sum(v * v for v in c) ** 0.5
        for k, want in enumerate((1.0, 0.0, 0.0)):
            self.assertAlmostEqual(c[k] / n, want, places=12)
        self.assertEqual(p[0], (25.0, 0.0, 0.0))

    def test_no_frame_node_is_ever_zero(self):
        """``node_ID3 = 0`` is NOT diagnosed by the starter: hm_read_sect.F:597
        tests ``NSTRF(K0+3)`` three times instead of K0+3/4/5, so the block
        runs and reads ``X0(:,0)`` — out of bounds. MEASURED: accepted at
        0 ERROR, engine NORMAL TERMINATION, and the implied "normal" comes out
        purely IN-plane. The old picker could return (n1, n2, 0)."""
        for a, b in ((1, 10), (11, 20), (21, 30)):
            self.assertNotEqual(_col_i(self.card, a, b), 0)

    def test_th_sectio_asks_for_the_global_and_centre_channels(self):
        """CX/CY/CZ is an exact, unaccumulated read-back of the frame ORIGIN
        (section_c.F assigns it rather than accumulating), and it is the only
        way to audit the frame from the T01 — the starter never echoes
        node_ID1/2/3."""
        th = _block(self.starter, "/TH/SECTIO/")
        var = next(ln for ln in th[2:] if not ln.startswith("#"))
        self.assertEqual([var[k:k + 10].strip() for k in (0, 10, 20)],
                         ["DEF", "GLOBAL", "CENTER"])


class TestSectSpringArm(unittest.TestCase):
    """(F) ``_plane_cut`` walked shells, solids, thick shells and beams and had
    NO spring arm, so a section plane through a belt or a discrete spring found
    nothing — and ``grsprg_ID``, the card's own spring slot, stayed 0.

    MEASURED, starter echo on this exact deck, master vs branch::

        NUMBER OF NODES              3   ->   4
        NUMBER OF SHELL ELEMENTS     1        1
        NUMBER OF BEAM ELEMENTS      1        1
        NUMBER OF SPRING ELEMENTS    0   ->   1     (SPRING 10, N1=1 N2=0)

    both at 0 starter ERROR; the branch's engine run terminates normally in
    182 cycles. ``N1=1 N2=0`` is the pack code SEC_TRI builds
    (hm_read_sect.F:962-974) and is exactly right: with BOTH nodes in the
    group ``section_r.F:83-84`` sums both and the contributions cancel to
    exactly 0.0 with no diagnostic — the ``d <= 0`` tail-side filter is what
    prevents it.
    """

    def setUp(self):
        self.res, self.starter = _convert(_ef_deck())

    def test_the_grsprg_column_names_a_real_group(self):
        card3 = _sect_card(self.starter, 11)[2]
        grsprg = _col_i(card3, 51, 60)
        self.assertNotEqual(grsprg, 0)
        blk = _block(self.starter, f"/GRSPRI/SPRI/{grsprg}")
        self.assertEqual([int(t) for ln in _cards(blk) for t in ln.split()],
                         [10])

    def test_a_dangling_grsprg_id_is_impossible(self):
        """``elegror.F:92-94`` returns 0 for a group id that does not exist and
        says NOTHING — on a section that also carries shells, a dangling
        grsprg_ID under-reports in complete silence (WARNING 1813 needs the
        section to be empty altogether). So the group must be emitted whenever
        the column is non-zero."""
        card3 = _sect_card(self.starter, 11)[2]
        grsprg = _col_i(card3, 51, 60)
        self.assertIn(f"/GRSPRI/SPRI/{grsprg}", self.starter)

    def test_the_other_columns_are_unmoved(self):
        """Column-exact, so a shifted spring slot is detectable: grbric(1-10),
        blank QUAD slot(11-20), grshel(21-30), grtrus(31-40), grbeam(41-50),
        grsprg(51-60), grtria(61-70), Niter(71-80), blank(81-90),
        Iframe(91-100)."""
        card3 = _sect_card(self.starter, 11)[2]
        self.assertEqual(_col_i(card3, 1, 10), 0)         # no solids cut
        self.assertEqual(card3[10:20], " " * 10)          # the dead QUAD slot
        self.assertNotEqual(_col_i(card3, 21, 30), 0)     # grshel
        self.assertEqual(_col_i(card3, 31, 40), 0)        # grtrus, never used
        self.assertNotEqual(_col_i(card3, 41, 50), 0)     # grbeam
        self.assertEqual(_col_i(card3, 61, 70), 0)        # grtria (no /SH3N)
        self.assertEqual(_col_i(card3, 71, 80), 0)        # Niter

    def test_the_divergence_from_secforc_is_named(self):
        """Vol I R17 p.16-48, Figure 16-2's caption: LS-DYNA's AUTOMATIC plane
        definition "does not check for springs and dampers in the section". So
        including them is a deliberate SUPER-SET and the user has to be told —
        the #125 class demands the statement, not the removal, because a belt
        section reading zero is the worse answer."""
        w = _warns(self.res, "deliberate SUPER-SET of LS-DYNA")
        self.assertEqual(len(w), 1)
        self.assertIn("does not check for springs and dampers", w[0])
        self.assertIn("[10]", w[0])

    def test_the_arm_keys_on_the_source_registry_not_the_union(self):
        """#128: ``state.spring_elem_ids`` is an id-only union across nine
        producers in different LS-DYNA namespaces. A beam whose eid EQUALS a
        discrete spring's must keep its own /GRBEAM membership."""
        deck = _ef_deck().replace(_i8(20, 2, 20, 21, 0), _i8(10, 2, 20, 21, 0))
        _res, starter = _convert(deck)
        card3 = _sect_card(starter, 11)[2]
        grbeam = _col_i(card3, 41, 50)
        self.assertNotEqual(grbeam, 0)
        blk = _block(starter, f"/GRBEAM/BEAM/{grbeam}")
        self.assertEqual([int(t) for ln in _cards(blk) for t in ln.split()],
                         [10])


class TestSectSetTsidDsid(unittest.TestCase):
    """(F) ``TSID`` and ``DSID`` on the ``_SET`` spelling were dropped with the
    stated reason "no converter-side element type". FALSE on both counts (the
    #130 class): thick shells leave this converter as ``/BRICK``, which is the
    grbric_ID group the card already carries, and ``/GRSPRI/SPRI`` has been
    starter-validated here since the preload batch, which is grsprg_ID.

    Vol I R17 p.16-49 gives both as first-class slots: "TSID — Thick shell
    element set ID", "DSID — Discrete element set ID, see *SET_DISCRETE"."""

    DECK = "\n".join([
        "*KEYWORD", "*NODE",
        _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
        _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
        _node16(5, 20.0, 0.0, 0.0), _node16(6, 20.0, 10.0, 0.0),
        _node16(30, 0.0, -20.0, 0.0), _node16(31, 10.0, -20.0, 0.0),
        "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4), _i8(2, 1, 2, 5, 6, 3),
        "*ELEMENT_DISCRETE", _i8(10, 3, 30, 31, 0),
        "*SECTION_SHELL", _row(1, 2, "", 2),
        _row("1.0", "1.0", "1.0", "1.0"),
        "*SECTION_DISCRETE", _row(3, 0), _row("0.0", "1.0", "0.0", "0.0"),
        "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
        "*MAT_SPRING_ELASTIC", _row(3, "100.0"),
        "*PART", "strip", _row(1, 1, 1),
        "*PART", "spring", _row(3, 3, 3),
        "*SET_NODE_LIST", _row(100), _row(1, 2, 3),
        "*SET_SHELL_LIST", _row(200), _row(1),
        "*SET_DISCRETE_LIST", _row(300), _row(10),
        "*DATABASE_CROSS_SECTION_SET_ID", f"{12:>10}" + "set section",
        # NSID HSID BSID SSID TSID DSID ID ITYPE
        _row(100, 0, 0, 200, 0, 300, 0, 0),
        "*END", ""])

    def test_DSID_lands_in_the_grsprg_column(self):
        res, starter = _convert(self.DECK)
        card3 = _sect_card(starter, 12)[2]
        grsprg = _col_i(card3, 51, 60)
        self.assertNotEqual(grsprg, 0)
        blk = _block(starter, f"/GRSPRI/SPRI/{grsprg}")
        self.assertEqual([int(t) for ln in _cards(blk) for t in ln.split()],
                         [10])
        # ... and the false "not converted" reason is gone.
        self.assertEqual(_warns(res, "are not converted"), [])


# ─────────────────────────────────────────────────────────────────────────────
# (G) /DYNAIN under implicit
# ─────────────────────────────────────────────────────────────────────────────

_G_IMPL = "\n".join([
    "*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1"),
    "*CONTROL_IMPLICIT_SOLUTION", _row(1, 11, "0.01"),
    "*CONTROL_IMPLICIT_AUTO", _row(1, 0, "0.05", "1.0E-7", "0.1")])


def _g_deck(elform: int = 12, implicit: bool = True) -> str:
    nodes, ids, nid = [], {}, 0
    for j, y in enumerate((0.0, 10.0, 20.0)):
        for i, x in enumerate((0.0, 10.0, 20.0)):
            nid += 1
            ids[(i, j)] = nid
            nodes.append(_node16(nid, x, y, 0.0))
    els, eid = [], 10
    for j in range(2):
        for i in range(2):
            eid += 1
            els.append(_i8(eid, 1, ids[(i, j)], ids[(i + 1, j)],
                           ids[(i + 1, j + 1)], ids[(i, j + 1)]))
    return "\n".join(
        ["*KEYWORD", "*NODE"] + nodes + ["*ELEMENT_SHELL"] + els + [
            "*SECTION_SHELL", _row(1, elform, "", 5),
            _row("1.0", "1.0", "1.0", "1.0"),
            "*MAT_PIECEWISE_LINEAR_PLASTICITY",
            _row(1, "7.85E-9", "2.1E5", "0.3", "200.0", "400.0"),
            "*PART", "plate", _row(1, 1, 1),
            "*SET_PART_LIST", _row(10), _row(1),
            "*INTERFACE_SPRINGBACK_LSDYNA", _row(10),
            "*CONTROL_TERMINATION", _row("1.0" if implicit else "1.0E-3"),
        ] + ([_G_IMPL] if implicit else []) + ["*END", ""])


class TestDynainUnderImplicit(unittest.TestCase):
    """(G) ``/DYNAIN`` under implicit was UNMEASURED — #129 shipped it
    validated explicit-only.

    MEASURED on a converging implicit probe (3x3 plate, ``*CONTROL_IMPLICIT_
    GENERAL/SOLUTION/AUTO``, imposed 0.2 mm, ENDTIM 1.0): the engine reports
    ``QUASI-STATIC NON-LINEAR``, ``TOTAL NONLINEAR ITERATIONS: 97``, NORMAL
    TERMINATION in 20 cycles, and writes THREE ``.dynain`` files of 22 225
    bytes each, all four blocks present (``*NODE``,
    ``*ELEMENT_SHELL_THICKNESS``, ``*INITIAL_STRESS_SHELL``,
    ``*INITIAL_STRAIN_SHELL``), header ``11 4 5 ... 1`` = full
    per-integration-point records.

    Not a stub and not frozen (the #122 checks): distinct md5 per file, and the
    driven edge reads 20.1960 / 20.1980 / **20.2000** — the last being the full
    imposed displacement to the digit, i.e. the terminal state captured
    EXACTLY. ``imp_dt.F:53-56`` clamps the last quasi-static step onto TSTOP,
    so implicit is BETTER here than explicit, whose last cycle lands below it.

    Source agrees: ``resol.F`` has ONE time loop, ``:8233`` is the only
    ``SORTIE_MAIN`` call site and is not gated on ``IMPL_S`` (``:8225`` even
    prepares the implicit coordinate array for it), and ``sortie_main.F:945``
    is the only ``GENDYNAIN`` call site.

    **VERDICT: works — document it, add NO guard.** A warning saying /DYNAIN is
    not written under /IMPL, or that the file would be empty, would be false
    and would prescribe a change to a correct deck (#125).
    """

    def test_the_dynain_block_is_emitted_unchanged_under_implicit(self):
        _res, _s, engine = _convert_both(_g_deck(implicit=True))
        self.assertIn("/DYNAIN/DT", engine)
        self.assertIn("/DYNAIN/SHELL/STRES/FULL", engine)
        self.assertIn("/DYNAIN/SHELL/STRAIN/FULL", engine)
        self.assertIn("/IMPL/", engine)

    def test_explicit_and_implicit_emit_the_SAME_dynain_cards(self):
        """No implicit branch anywhere in _make_engine_dynain — the card set
        is identical, which is the property the measurement licenses."""
        _r1, _s1, exp = _convert_both(_g_deck(implicit=False))
        _r2, _s2, imp = _convert_both(_g_deck(implicit=True))
        self.assertEqual([ln for ln in exp.splitlines()
                          if ln.startswith("/DYNAIN")],
                         [ln for ln in imp.splitlines()
                          if ln.startswith("/DYNAIN")])

    def test_no_warning_claims_implicit_is_unsupported(self):
        res, _s, _e = _convert_both(_g_deck(implicit=True))
        for w in res.warnings:
            for claim in ("not written under", "implicit is not supported",
                          "run the springback explicitly"):
                self.assertNotIn(claim, w)

    def test_the_terminal_state_caveat_is_scoped_to_explicit(self):
        """The ILASTDYNAIN dead branch is real but EXPLICIT-only: under
        quasi-static implicit the run lands on TSTOP exactly (measured
        20.2000 vs the imposed 0.2). Stating it unqualified on an implicit
        deck would be a false caveat."""
        imp, _s, _e = _convert_both(_g_deck(implicit=True))
        exp, _s2, _e2 = _convert_both(_g_deck(implicit=False))
        wi = _warns(imp, "/DYNAIN/DT")[0]
        we = _warns(exp, "/DYNAIN/DT")[0]
        self.assertIn("IS the terminal state, exactly", wi)
        self.assertIn("imp_dt.F:53-56", wi)
        self.assertNotIn("ILASTDYNAIN", wi)
        # ... and the explicit arm keeps the caveat, now labelled.
        self.assertIn("ILASTDYNAIN", we)
        self.assertIn("EXPLICIT-ONLY", we)


class TestDynainStrainCardSpelling(unittest.TestCase):
    """(G) side defect, found while measuring the implicit case and NOT what
    the batch's research predicted.

    ``fredynain.F:140`` accepts the card on ``KEY3(1:5) == 'STRAI'``, so
    ``/DYNAIN/SHELL/STRAI/FULL`` and ``/DYNAIN/SHELL/STRAIN/FULL`` both parse.
    They are not equivalent. ``check_qeph_stra.F:64-76`` runs inside the
    STARTER, opens ``<root>_0001.rad`` and compares the first 25 characters of
    each line against the literal ``/DYNAIN/SHELL/STRAIN/FULL``; a match sets
    ``ISTR_24 = 1``, and ``elbuf_ini.F:1588`` then allocates
    ``GBUF%G_STRPG = 4*GBUF%G_STRA`` for QEPH shell groups — the ONLY thing
    that lets ``dynain_c_strag.F:151`` lift ``NPG`` to 4 and stops ``:152``
    from ``CYCLE``-ing the group.

    MEASURED, spelling twin: the same starter deck, the same engine deck apart
    from this one card, both NORMAL TERMINATION at 0 ERROR / 0 WARNING,
    20 cycles::

        /DYNAIN/SHELL/STRAIN/FULL  ->  22 225 B, 366 lines, STRAIN block
                                       present (164 records, eps_XX 4.674E-03)
        /DYNAIN/SHELL/STRAI/FULL   ->  12 422 B, 195 lines, NO strain block

    The research round attributed that 12 4xx-byte file to QEPH itself and
    proposed a warning naming every QEPH part. That warning would have been
    FALSE: this converter's own implicit decks are ALL QEPH
    (``_elform_to_ishell`` returns 24 unconditionally under implicit) and the
    measured implicit dynain above HAS its strain block. Firing on those decks
    would be the #125 class — prescribing a fix on a correct deck — so no
    warning ships. The constant is a regression FENCE instead.
    """

    def test_the_long_spelling_is_emitted_character_for_character(self):
        from k2rad.writer.rarecards import _DYNAIN_STRAIN_CARD
        self.assertEqual(_DYNAIN_STRAIN_CARD, "/DYNAIN/SHELL/STRAIN/FULL")
        # check_qeph_stra.F:68 compares KEYA(1:25) — the card must be exactly
        # 25 characters, or the starter's scan cannot match it.
        self.assertEqual(len(_DYNAIN_STRAIN_CARD), 25)
        _res, _s, engine = _convert_both(_g_deck())
        cards = [ln for ln in engine.splitlines() if ln.startswith("/DYNAIN")]
        self.assertIn("/DYNAIN/SHELL/STRAIN/FULL", cards)
        self.assertNotIn("/DYNAIN/SHELL/STRAI/FULL", cards)

    def test_the_implicit_deck_is_QEPH_and_still_gets_its_strains(self):
        """The control that refutes the QEPH theory. _elform_to_ishell returns
        24 under implicit whatever the ELFORM, so the measured implicit run
        WAS a QEPH deck — and it wrote 164 strain records."""
        from k2rad.writer.common import _elform_to_ishell
        for elform in (2, 12, 16):
            with self.subTest(elform=elform):
                self.assertEqual(
                    _elform_to_ishell(elform, True, 12), 24)
        _res, starter, _e = _convert_both(_g_deck(elform=12))
        prop = _cards(_block(starter, "/PROP/SHELL/1"))[0]
        self.assertEqual(_col_i(prop, 1, 10), 24)

    def test_no_warning_prescribes_a_shell_formulation_change(self):
        for elform in (12, 16):
            with self.subTest(elform=elform):
                res, _s, _e = _convert_both(_g_deck(elform=elform))
                self.assertEqual(_warns(res, "QEPH shell formulation"), [])
                self.assertEqual(
                    _warns(res, "--shell-formulation qbat"), [])


if __name__ == "__main__":            # pragma: no cover
    unittest.main()
