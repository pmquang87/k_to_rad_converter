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


if __name__ == "__main__":            # pragma: no cover
    unittest.main()
