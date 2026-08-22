"""The SPH batch:

  *ELEMENT_SPH (+ _VOLUME / unknown)   -> /SPHCEL/<part_ID>, one row per cell
  *SECTION_SPH (+ 4 option spellings)  -> /PROP/SPH (= /PROP/TYPE34)
  *CONTROL_SPH NMNEIGH                 -> /SPHGLO Lneigh / Nneigh
  *DATABASE_HISTORY_SPH[_SET]          -> /TH/SPHCEL

MASS is the correctness criterion of this batch, so it is asserted numerically
in every route, from hand-computed totals, rather than by substring. The
conventions that carry the most risk, and why each is pinned:

* **The particle IS its node.** The /SPHCEL id column is read as the NODE user
  id and the cell id is then forced equal to it (``hm_read_sphcel.F:243-250``),
  so an SPH cell cannot be renumbered independently of a node — which is why
  the *INCLUDE_TRANSFORM spec gives field 0 the NODE bucket, not the element
  one, and why every id here is asserted against IDNOFF.
* **Radioss has TWO places to state a mass and they are mutually exclusive.**
  A cell that carries its own mass makes the solver DERIVE the smoothing length
  from it and IGNORE the property's (``spinih.F:85-95``); a cell that does not
  takes ``Mp`` from the property and keeps the property's ``h``. Both routes are
  exercised, and both are asserted to give the exact total mass — the whole
  point of the split is that fidelity is never traded, only the smoothing
  length is.
* **``h_1D = 3`` and hmin/hmax/hcst must NEVER be emitted at /BEGIN 2022.** The
  bounds live on a radioss2026-only third card that a 2022 reader discards
  silently while still accepting ``h_1D = 3`` on card 1 — bounded dilatation
  with bounds nobody chose. So the card count is asserted, not just the values.
* **A zero-mass cell must be written Flag 0, never Flag 1.** An explicit Flag 1
  with a blank MASS is a SILENT zero-mass particle (measured: TOTAL MASS =
  0.000000000000, no diagnostic).
* **A /TH/SPHCEL id that is not an emitted /SPHCEL is starter ERROR 69**, not a
  lost channel — the #106 rule, and the SPH branch is the only element branch in
  dyna2rad's own TH converter with no such filter.
* **The mesh survives every spelling.** Measured on master, converting
  W11_SETUP_SPH_BirdStrike.k left ELEMENT_SPH in ``skipped_keywords`` and lost
  all 18,795 particles — 1.8199 kg, 100 % of the projectile — with NO MESH LOSS
  warning, while the two eroding contacts that scope those particle nodes
  converted and reported themselves healthy.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                              # noqa: E402
from k2rad.assembly import _OFFSET_SPECS, _offset_block  # noqa: E402
from k2rad.handlers import HANDLERS, dispatch          # noqa: E402
from k2rad.parser import parse_k_file                  # noqa: E402
from k2rad.state import ConversionState                # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

def _convert(deck_text: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck_text)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _dispatch(deck_text: str) -> ConversionState:
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck_text)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


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


def _rows(block):
    """A block's DATA lines: comments removed."""
    return [ln for ln in block[1:] if not ln.startswith("#")]


def _cards(block):
    """A property block's DATA lines: after the title, comments removed."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(result, needle: str):
    return [w for w in result.warnings if needle in w]


def _row(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def _cell(nid, pid, mass="", nend=""):
    """One *ELEMENT_SPH card in the manual's own layout: NID(I8) PID(I8)
    MASS(F16) NEND(I8)."""
    return f"{nid:>8}{pid:>8}{mass:>16}{nend:>8}".rstrip() + "\n"


def _total_mass(starter: str, part_ids=(1,)) -> float:
    """The mass the emitted deck states, summed the way Radioss would: a cell
    with a positive MASS states it, a cell with a blank one takes the property's
    Mp (spinit3.F:139-153)."""
    props = {}
    for blk in _blocks(starter, "/PROP/SPH/"):
        props[int(blk[0].rsplit("/", 1)[1])] = _col_f(_cards(blk)[0], 1, 20)
    total = 0.0
    for pid in part_ids:
        part = _block(starter, f"/PART/{pid}")
        prop_id = _col_i(_rows(part)[1], 1, 10)
        for ln in _rows(_block(starter, f"/SPHCEL/{pid}")):
            flag = _col_i(ln, 11, 20)
            mass = _col_f(ln, 21, 40)
            total += mass if (flag == 1 and mass > 0.0) else props[prop_id]
    return total


# ── Decks ────────────────────────────────────────────────────────────────────
#
# A 2x2x2 simple-cubic lattice of spacing 10, so LS-DYNA's d_ref ("the maximum
# of the minimum distance between every particle") is EXACTLY 10 for every
# particle: each corner's three face neighbours are 10 away and its three other
# neighbours 14.14 / 17.32. h0 = CSLH * d_ref is therefore hand-computable.
LATTICE = [(1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
           (3, 0.0, 10.0, 0.0), (4, 10.0, 10.0, 0.0),
           (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
           (7, 0.0, 10.0, 10.0), (8, 10.0, 10.0, 10.0)]
NODES = "*NODE\n" + "".join(
    f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in LATTICE)
D_REF = 10.0

MASS = 2.0e-3
SPH8 = "*ELEMENT_SPH\n" + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE)

PART = "*PART\nsph part\n" + _row(1, 1, 1) + "\n"

#: One quad on PART 2 (SECID 5), the structural partner for the mixed-family
#: deck. Written at the *ELEMENT_SHELL I8 ruler, not _row's I10.
SHELL2 = ("*ELEMENT_SHELL\n"
          + f"{1:>8}{2:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n"
          + "*PART\nshell part\n" + _row(2, 5, 1) + "\n")

RHO = 7.85e-6
MAT = "*MAT_ELASTIC\n" + _row(1, RHO, 210000.0, 0.3) + "\n"

TERM = "*CONTROL_TERMINATION\n" + _row(0.01) + "\n"


def sec(secid=1, cslh=1.2, hmin=0.2, hmax=2.0, sphini="", death="",
        start="", sphkern="", keyword="*SECTION_SPH", extra=""):
    """One *SECTION_SPH card set: SECID CSLH HMIN HMAX SPHINI DEATH START
    SPHKERN."""
    return (keyword + "\n"
            + _row(secid, cslh, hmin, hmax, sphini, death, start, sphkern)
            + "\n" + extra)


def deck(elem=SPH8, section=None, mat=MAT, part=PART, extra=""):
    return ("*KEYWORD\n" + NODES + elem + part
            + (sec() if section is None else section) + mat + TERM + extra
            + "*END\n")


# ═════════════════════════════════════════════════════════════════════════════
class SphCells(unittest.TestCase):
    """*ELEMENT_SPH -> /SPHCEL."""

    def test_the_cell_card_is_column_exact(self):
        """id 1-10, Flag 11-20, MASS 21-40 — radioss41/ELEM/sphcel.cfg
        FORMAT(radioss110), the ONLY format block that file has, so 2022 and
        2026 are byte-identical here."""
        # unequal masses -> the per-cell route, so the columns carry real data
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, MASS * (k + 1)) for k, (n, *_) in enumerate(LATTICE))
        _, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual(len(rows), 8)
        self.assertEqual(len(rows[0]), 40)
        self.assertEqual(_col_i(rows[0], 1, 10), 1)
        self.assertEqual(_col_i(rows[0], 11, 20), 1)
        self.assertAlmostEqual(_col_f(rows[0], 21, 40), MASS)
        self.assertAlmostEqual(_col_f(rows[7], 21, 40), MASS * 8)

    def test_unequal_masses_transfer_one_to_one_and_the_total_is_exact(self):
        """The primary criterion. Masses 1..8 x 2e-3 sum to 0.072 exactly, and
        every one of them has to survive as its own /SPHCEL row — a per-cell
        MASS is what Radioss reads FIRST (spinit3.F:141-143)."""
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, MASS * (k + 1)) for k, (n, *_) in enumerate(LATTICE))
        _, starter = _convert(deck(elem=elems))
        self.assertAlmostEqual(_total_mass(starter),
                               MASS * (1 + 2 + 3 + 4 + 5 + 6 + 7 + 8))

    def test_uniform_masses_move_onto_the_property_and_the_total_is_exact(self):
        """8 x 2e-3 = 0.016 either way. Stating it once as Mp is what lets the
        deck's own smoothing length survive — a cell that carries a mass makes
        Radioss overwrite h with (sqrt(2)*m/rho)^(1/3) (spinih.F:90-95)."""
        result, starter = _convert(deck())
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual([_col_i(r, 11, 20) for r in rows], [0] * 8)
        self.assertEqual([_col_f(r, 21, 40) for r in rows], [0.0] * 8)
        card1 = _cards(_block(starter, "/PROP/SPH/1"))[0]
        self.assertAlmostEqual(_col_f(card1, 1, 20), MASS)
        self.assertAlmostEqual(_total_mass(starter), 8 * MASS)
        self.assertTrue(_warns(result, "carries the SAME mass"),
                        result.warnings)

    def test_a_negative_mass_is_a_volume(self):
        """"LT.0.0: Volume. The absolute value will be used as volume … SPH
        element mass is calculated by |MASS| x rho". dyna2rad copies the sign
        through and the starter then DISCARDS the value — measured 8.0 kg where
        the deck states 0.016."""
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, -2.0e-6) for n, *_ in LATTICE)
        result, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual([_col_i(r, 11, 20) for r in rows], [2] * 8)
        self.assertAlmostEqual(_col_f(rows[0], 21, 40), 2.0e-6)
        self.assertTrue(_warns(result, "NEGATIVE mass"), result.warnings)

    def test_the_volume_suffix_is_the_same_convention_with_a_positive_number(self):
        """"It has the same effect as giving a negative number in the MASS
        field." dyna2rad's CFG declares no option here and reads the volumes as
        masses — measured, wrong by exactly rho."""
        elems = "*ELEMENT_SPH_VOLUME\n" + "".join(
            _cell(n, 1, 2.0e-6) for n, *_ in LATTICE)
        result, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual([_col_i(r, 11, 20) for r in rows], [2] * 8)
        self.assertAlmostEqual(_col_f(rows[0], 21, 40), 2.0e-6)
        self.assertTrue(_warns(result, "_VOLUME suffix"), result.warnings)

    def test_a_blank_mass_is_flag_zero_never_flag_one(self):
        """A Flag=1 row with a blank MASS is a SILENT zero-mass particle:
        spinit3.F:142 computes VOL = 0/rho and the starter reports TOTAL MASS =
        0.000000000000 with no diagnostic at all."""
        elems = ("*ELEMENT_SPH\n"
                 + _cell(1, 1, MASS) + _cell(2, 1) + _cell(3, 1, MASS * 2)
                 + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE[3:]))
        result, starter = _convert(deck(elem=elems))
        rows = {_col_i(r, 1, 10): r for r in _rows(_block(starter, "/SPHCEL/1"))}
        self.assertEqual(_col_i(rows[2], 11, 20), 0)
        self.assertEqual(_col_f(rows[2], 21, 40), 0.0)
        self.assertEqual(_col_i(rows[1], 11, 20), 1)
        self.assertTrue(_warns(result, "state no mass of their"),
                        result.warnings)
        # ... and it takes the property's Mp, which is always positive
        mp = _col_f(_cards(_block(starter, "/PROP/SPH/1"))[0], 1, 20)
        self.assertGreater(mp, 0.0)

    def test_the_property_mass_is_never_left_at_zero(self):
        """dyna2rad never sets Mp, so hm_read_prop34.F:235-239 raises WARNING
        138 on EVERY converted SPH deck and forces Mp = 1 in the deck's mass
        unit — measured, four blank-mass particles gave TOTAL MASS = 4.0."""
        elems = "*ELEMENT_SPH\n" + "".join(_cell(n, 1) for n, *_ in LATTICE)
        _, starter = _convert(deck(elem=elems))
        self.assertGreater(
            _col_f(_cards(_block(starter, "/PROP/SPH/1"))[0], 1, 20), 0.0)

    def test_nend_generates_the_range(self):
        """"GT.0: *ELEMENT_SPH cards are generated between NID to NEND using
        current PID and MASS data." Neither dyna2rad nor OpenRadioss's own
        native .k reader expands it — measured NUMSPH = 1."""
        elems = "*ELEMENT_SPH\n" + _cell(1, 1, MASS, 8)
        result, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual([_col_i(r, 1, 10) for r in rows], list(range(1, 9)))
        self.assertAlmostEqual(_total_mass(starter), 8 * MASS)
        self.assertTrue(_warns(result, "NEND range generator"), result.warnings)

    def test_generated_ids_with_no_node_are_dropped_and_counted(self):
        """A generated range names every id between NID and NEND whether or not
        the node cloud is contiguous. A /SPHCEL id with no /NODE is starter
        ERROR 78 and the whole deck is refused, so they go — but they go with a
        count."""
        elems = "*ELEMENT_SPH\n" + _cell(1, 1, MASS, 20)
        result, starter = _convert(deck(elem=elems))
        self.assertEqual(len(_rows(_block(starter, "/SPHCEL/1"))), 8)
        self.assertTrue(_warns(result, "generated by a NEND range have no"),
                        result.warnings)

    def test_a_particle_on_an_undefined_node_is_dropped_as_mesh_loss(self):
        elems = SPH8 + _cell(999, 1, MASS)
        result, starter = _convert(deck(elem=elems))
        self.assertEqual(len(_rows(_block(starter, "/SPHCEL/1"))), 8)
        hits = _warns(result, "MESH LOSS")
        self.assertTrue(hits, result.warnings)
        self.assertIn("999", hits[0])
        self.assertIn("ERROR 78", hits[0])

    def test_a_duplicated_particle_id_is_dropped(self):
        """Radioss indexes a cell BY its node, so two cells on one node is
        starter ERROR 79 (hm_read_sphcel.F:444 UDOUBLE) and the deck is
        refused."""
        elems = SPH8 + _cell(3, 1, MASS * 5)
        result, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual(len(rows), 8)
        self.assertTrue(_warns(result, "ERROR 79"), result.warnings)

    def test_the_r14_card_layout_with_nend_parses(self):
        """The layout LS-PrePost actually writes: mass in cols 17-32, NEND
        right-justified across 33-42 rather than the manual's 33-40."""
        state = _dispatch(
            "*KEYWORD\n*ELEMENT_SPH\n"
            "$#   nid     pid            mass      nend\n"
            " 1000001     101  2.264088E-07           0\n*END\n")
        self.assertEqual(len(state.sph_elems), 1)
        c = state.sph_elems[0]
        self.assertEqual((c.nid, c.pid, c.flag), (1000001, 101, 1))
        self.assertAlmostEqual(c.mass, 2.264088e-07)

    def test_a_free_format_card_parses(self):
        state = _dispatch("*KEYWORD\n*ELEMENT_SPH\n"
                          "150061, 2, 9.683426e-05\n*END\n")
        self.assertEqual(len(state.sph_elems), 1)
        self.assertAlmostEqual(state.sph_elems[0].mass, 9.683426e-05)

    def test_ids_that_fill_all_eight_columns_still_split(self):
        """A whitespace split glues NID and PID whenever the left one fills the
        field, so the fixed slice is the fallback — the _elem_fields lesson."""
        state = _dispatch("*KEYWORD\n*ELEMENT_SPH\n"
                          "1000000110000002        2.0E-03\n*END\n")
        self.assertEqual(len(state.sph_elems), 1)
        c = state.sph_elems[0]
        self.assertEqual((c.nid, c.pid), (10000001, 10000002))
        self.assertAlmostEqual(c.mass, 2.0e-3)

    def test_every_option_spelling_is_dispatched(self):
        for kw in ("ELEMENT_SPH", "ELEMENT_SPH_VOLUME"):
            self.assertIn(kw, HANDLERS, kw)
        for kw in ("SECTION_SPH", "SECTION_SPH_ELLIPSE", "SECTION_SPH_TENSOR",
                   "SECTION_SPH_INTERACTION", "SECTION_SPH_USER",
                   "CONTROL_SPH", "DATABASE_HISTORY_SPH",
                   "DATABASE_HISTORY_SPH_SET", "DATABASE_SPHOUT"):
            self.assertIn(kw, HANDLERS, kw)

    def test_element_sph_is_not_matched_by_the_element_shell_prefix(self):
        """The prefix fallback matches on a TOKEN boundary, so ELEMENT_SPH is
        not an ELEMENT_SHELL spelling and needs its own row — without it every
        particle lands in skipped_keywords, which is what master did."""
        from k2rad.handlers import _PREFIX_HANDLERS, handle_element_sph
        rows = dict(_PREFIX_HANDLERS)
        self.assertIs(rows["ELEMENT_SPH"], handle_element_sph)
        self.assertLess(list(rows).index("ELEMENT_SPH"),
                        list(rows).index("ELEMENT_SHELL"))

    def test_an_unknown_suffix_keeps_the_particles(self):
        state = _dispatch("*KEYWORD\n*ELEMENT_SPH_FANCY_OPTION\n"
                          + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE)
                          + "*END\n")
        self.assertEqual(len(state.sph_elems), 8)
        self.assertTrue(all(c.provisional for c in state.sph_elems))
        self.assertEqual(state.skipped_keywords, [])

    def test_provisional_particles_are_screened_against_the_node_table(self):
        """The content test an unknown suffix falls back on cannot tell an
        option card from a particle card, so an invented cell sits on an id the
        deck never defines — starter ERROR 78."""
        elems = ("*ELEMENT_SPH_FANCY\n"
                 + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE)
                 + _cell(4242, 1, 1.0))
        result, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual(len(rows), 8)
        hits = _warns(result, "is not implemented")
        self.assertTrue(hits, result.warnings)
        # the screen has to ACCOUNT for the invented cell, not merely let the
        # later _resolve_sph node check quietly drop it
        self.assertIn("named node ids the deck does not define", hits[0])
        self.assertIn("/SPHCEL (SPH particle)", hits[0])

    def test_a_non_particle_line_is_reported_not_silently_dropped(self):
        result, _ = _convert(deck(elem=SPH8 + "  not a card at all\n"))
        self.assertTrue(_warns(result, "not a particle card"), result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class SectionSphCards(unittest.TestCase):
    """*SECTION_SPH card-set walking and the LS-DYNA defaults."""

    def test_card1_fields(self):
        state = _dispatch("*KEYWORD\n"
                          + sec(secid=7, cslh=1.05, hmin=0.5, hmax=3.0,
                                sphini=0.25, death=1.5, start=0.5, sphkern=2)
                          + "*END\n")
        s = state.sec_sph[7]
        self.assertEqual(
            (s.cslh, s.hmin, s.hmax, s.sphini, s.death, s.start, s.sphkern),
            (1.05, 0.5, 3.0, 0.25, 1.5, 0.5, 2))

    def test_a_blank_cslh_is_the_manuals_default_1p2(self):
        """The CFG declares DEFAULTS(COMMON){LSD_CSLH = 1.2} and the SDI read
        path does NOT apply them, so dyna2rad sees 0 and takes the `else` of
        `lsdCSLH > 0` — turning a deck that left the cell blank into a CONSTANT
        smoothing length with SPHINI discarded (probe decks h and i)."""
        state = _dispatch("*KEYWORD\n*SECTION_SPH\n" + _row(1) + "\n*END\n")
        self.assertEqual(state.sec_sph[1].cslh, 1.2)
        self.assertTrue(state.sec_sph[1].cslh_blank)

    def test_blank_hmin_hmax_and_death_take_their_manual_defaults(self):
        state = _dispatch("*KEYWORD\n*SECTION_SPH\n" + _row(1) + "\n*END\n")
        s = state.sec_sph[1]
        self.assertEqual((s.hmin, s.hmax, s.death), (0.2, 2.0, 1.0e20))

    def test_every_card_set_under_one_header_is_read(self):
        state = _dispatch("*KEYWORD\n*SECTION_SPH\n"
                          + _row(1, 1.2) + "\n" + _row(2, 1.1) + "\n"
                          + _row(3, 1.05) + "\n*END\n")
        self.assertEqual(sorted(state.sec_sph), [1, 2, 3])
        self.assertAlmostEqual(state.sec_sph[3].cslh, 1.05)

    def test_title_option_reads_one_title_per_set(self):
        state = _dispatch("*KEYWORD\n*SECTION_SPH_TITLE\nbird\n"
                          + _row(1, 1.2) + "\nwater\n" + _row(2, 1.1)
                          + "\n*END\n")
        self.assertEqual(state.sec_sph[1].title, "bird")
        self.assertEqual(state.sec_sph[2].title, "water")

    def test_the_ellipse_card_is_stridden_by_raw_contiguity(self):
        """Card 2 carries no id but IS a card. Skipping it as whitespace would
        read the NEXT set's card 1 as anisotropic h values and lose that whole
        section (the #119 rule)."""
        state = _dispatch(
            "*KEYWORD\n*SECTION_SPH_ELLIPSE\n"
            + _row(1, 1.2, 0.2, 2.0) + "\n"
            + _row(1.0, 1.0, 2.0, 0.0, 0.0, 0.0) + "\n"
            + _row(2, 1.1, 0.2, 2.0) + "\n"
            + _row(1.0, 1.0, 1.0, 0.0, 0.0, 0.0) + "\n*END\n")
        self.assertEqual(sorted(state.sec_sph), [1, 2])
        self.assertAlmostEqual(state.sec_sph[2].cslh, 1.1)

    def test_the_anisotropic_smoothing_lengths_are_named_as_dropped(self):
        state = _dispatch(
            "*KEYWORD\n*SECTION_SPH_ELLIPSE\n"
            + _row(1, 1.2, 0.2, 2.0) + "\n"
            + _row(1.0, 1.0, 2.0, 0.0, 0.0, 0.0) + "\n*END\n")
        self.assertTrue([w for w in state.warnings
                         if "ANISOTROPIC smoothing length" in w],
                        state.warnings)

    def test_the_interaction_and_user_options_are_named(self):
        for opt in ("INTERACTION", "USER"):
            state = _dispatch("*KEYWORD\n*SECTION_SPH_" + opt + "\n"
                              + _row(1, 1.2) + "\n*END\n")
            self.assertTrue([w for w in state.warnings if f"_{opt}" in w],
                            (opt, state.warnings))
            self.assertIn(1, state.sec_sph)     # the card is still read

    def test_the_walk_stops_loudly_on_a_card_it_cannot_stride(self):
        state = _dispatch("*KEYWORD\n*SECTION_SPH\n" + _row(1, 1.2) + "\n"
                          + _row(0, 1.2) + "\n" + _row(3, 1.2) + "\n*END\n")
        self.assertEqual(sorted(state.sec_sph), [1])
        self.assertTrue([w for w in state.warnings if "walk\nSTOPPED" in w
                         or "STOPPED" in w], state.warnings)

    def test_duplicate_secid_warns(self):
        state = _dispatch("*KEYWORD\n*SECTION_SPH\n" + _row(1, 1.2) + "\n"
                          + _row(1, 1.05) + "\n*END\n")
        self.assertTrue([w for w in state.warnings
                         if "defined more than once" in w], state.warnings)
        self.assertAlmostEqual(state.sec_sph[1].cslh, 1.05)


# ═════════════════════════════════════════════════════════════════════════════
class PropSph(unittest.TestCase):
    """/PROP/SPH (= /PROP/TYPE34), radioss2019 layout."""

    def test_the_card_layout_is_column_exact(self):
        """radioss2019/PROP/prop_p34_sph.cfg FORMAT(radioss2019): a mandatory
        80a title then TWO data cards, %20lg%20lg%20lg%20lg%10d%10d and
        %10d%20lg%20lg."""
        _, starter = _convert(deck())
        blk = _block(starter, "/PROP/SPH/1")
        cards = _cards(blk)
        self.assertEqual(len(cards), 2)
        self.assertEqual(len(cards[0]), 100)
        self.assertEqual(len(cards[1]), 50)
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), MASS)     # Mp
        self.assertAlmostEqual(_col_f(cards[0], 21, 40), 2.0)     # qa
        self.assertAlmostEqual(_col_f(cards[0], 41, 60), 1.0)     # qb
        self.assertAlmostEqual(_col_f(cards[0], 61, 80), 0.0)     # Alpha_cs
        self.assertEqual(_col_i(cards[0], 81, 90), 0)             # skew_ID
        self.assertEqual(_col_i(cards[0], 91, 100), 0)            # h_1D
        self.assertEqual(_col_i(cards[1], 1, 10), 0)              # Order
        self.assertAlmostEqual(_col_f(cards[1], 31, 50), 0.0)     # Xi_Stab

    def test_never_a_third_card_and_never_h_1d_equal_three(self):
        """hmin/hmax/hcst are radioss2026-only and a /BEGIN 2022 reader
        DISCARDS them silently (measured: 0.37/3.77/1.77 echoed as the
        hard-coded 0.2/2.0/1.2, 0 ERRORS, advisory WARNING 100213) while still
        ACCEPTING h_1D=3 on card 1 — bounded dilatation with bounds nobody
        chose. dyna2rad emits exactly that combination."""
        for hmin, hmax in ((0.2, 2.0), (0.37, 3.77), (0.0, 0.0), (1.0, 4.0)):
            _, starter = _convert(deck(section=sec(hmin=hmin, hmax=hmax)))
            cards = _cards(_block(starter, "/PROP/SPH/1"))
            self.assertEqual(len(cards), 2, (hmin, hmax))
            self.assertNotEqual(_col_i(cards[0], 91, 100), 3, (hmin, hmax))

    def test_hmin_equals_hmax_equals_one_is_the_exact_constant_h_case(self):
        """"Defining a value of 1 for HMIN and 1 for HMAX will result in a
        constant smoothing length in time and space" — h_1D = 2, the one
        HMIN/HMAX pair that maps exactly (hm_read_prop34.F:203-211)."""
        _, starter = _convert(deck(section=sec(hmin=1.0, hmax=1.0)))
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertEqual(_col_i(cards[0], 91, 100), 2)

    def test_order_stays_zero_even_for_sphkern_two(self):
        """dyna2rad maps SPHKERN==2 -> ORDER=2. Radioss's Order is the
        RENORMALISATION correction order, valid in -1/0/1 only: spcompl.F:107-118
        dispatches on nothing else, so an Order=2 particle gets no kernel
        correction at all."""
        result, starter = _convert(deck(section=sec(sphkern=2)))
        self.assertEqual(_col_i(_cards(_block(starter, "/PROP/SPH/1"))[1],
                                1, 10), 0)
        self.assertTrue(_warns(result, "SPHKERN=2"), result.warnings)

    def test_sphini_becomes_the_property_smoothing_length(self):
        """"Optional initial smoothing length (overrides true smoothing
        length) … the field CSLH is ignored"."""
        _, starter = _convert(deck(section=sec(sphini=3.5)))
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertAlmostEqual(_col_f(cards[1], 11, 30), 3.5)

    def test_cslh_times_the_measured_spacing_becomes_h(self):
        """"LS-DYNA computes the initial smoothing length, h0, for each SPH
        part by taking the maximum of the minimum distance between every
        particle and then scaling this value by CSLH." On the 2x2x2 lattice
        d_ref is exactly 10, so h0 = 1.2 * 10 = 12."""
        result, starter = _convert(deck())
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertAlmostEqual(_col_f(cards[1], 11, 30), 1.2 * D_REF, places=9)
        self.assertTrue(_warns(result, "measured interparticle distance"),
                        result.warnings)

    def test_a_blank_cslh_still_scales_by_the_default_1p2(self):
        _, starter = _convert(deck(
            section="*SECTION_SPH\n" + _row(1) + "\n"))
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertAlmostEqual(_col_f(cards[1], 11, 30), 1.2 * D_REF, places=9)

    def test_unequal_masses_lose_h_and_the_mismatch_is_quantified(self):
        """A cell that carries a mass makes Radioss derive h from it and IGNORE
        the property's (spinih.F:90-95). The mass stays exact; the report has to
        state the smoothing-length ratios it costs.

        The ratios have to be the REAL ones — a single value derived from the
        MEAN particle mass is a value no particle has, and on a spread cloud
        its direction is wrong for the population that governs the time step.
        """
        import math
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, MASS * (k + 1)) for k, (n, *_) in enumerate(LATTICE))
        result, starter = _convert(deck(elem=elems))
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertEqual(_col_f(cards[1], 11, 30), 0.0)   # h auto-computed
        hits = _warns(result, "PER PARTICLE")
        self.assertTrue(hits, result.warnings)
        n = len(LATTICE)
        h_lo = (math.sqrt(2.0) * MASS * 1 / RHO) ** (1.0 / 3.0)
        h_hi = (math.sqrt(2.0) * MASS * n / RHO) ** (1.0 / 3.0)
        h0 = 1.2 * D_REF
        # both ends of the real span, not the mean-mass value in between
        self.assertIn(f"spans {h_lo:g} to {h_hi:g}", hits[0])
        self.assertIn(f"ratios {h_lo / h0:.4f} to {h_hi / h0:.4f}", hits[0])
        # the SMALLEST h sets the time step, and the message has to say so
        self.assertIn(f"{h_lo / h0:.4f} is the ratio that governs", hits[0])
        # the mean-mass reading is NOT what is reported
        mp = _col_f(cards[0], 1, 20)
        h_mean = (math.sqrt(2.0) * mp / RHO) ** (1.0 / 3.0)
        self.assertNotIn(f"a ratio of {h_mean / h0:.4f}", hits[0])

    def test_sphini_with_unequal_masses_is_named_as_dropped(self):
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, MASS * (k + 1)) for k, (n, *_) in enumerate(LATTICE))
        result, _ = _convert(deck(elem=elems, section=sec(sphini=3.5)))
        self.assertTrue(_warns(result, "h = 3.5 (SPHINI)"),
                        result.warnings)

    def test_hourglass_never_reaches_the_smoothing_length(self):
        """dyna2rad copies *HOURGLASS QM (and *CONTROL_HOURGLASS QH) into the
        /PROP/SPH field named "h" — a dimensionless viscosity coefficient into a
        LENGTH. Measured: QM=0.13 with SPHINI=0.5 echoed SMOOTHING LENGTH =
        0.13, and a global QH ZEROED it outright."""
        hg = ("*CONTROL_HOURGLASS\n" + _row(4, 0.07) + "\n"
              "*HOURGLASS\n" + _row(9, 4, 0.13) + "\n")
        result, starter = _convert(deck(section=sec(sphini=0.5), extra=hg))
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertAlmostEqual(_col_f(cards[1], 11, 30), 0.5)
        self.assertNotIn("/PROP/SPH/9", starter)
        del result

    def test_death_and_start_are_named_as_dropped(self):
        result, _ = _convert(deck(section=sec(death=1.0e-3, start=1.0e-4)))
        self.assertTrue(_warns(result, "DEATH=0.001"), result.warnings)
        self.assertTrue(_warns(result, "START=0.0001"), result.warnings)

    def test_the_dropped_hmin_hmax_bound_is_named_even_at_its_default(self):
        """0.2 / 2.0 is what a BLANK card means, and it is still a real bound —
        the one that keeps a collapsing smoothing length off engine ERROR 174.
        Reporting only the non-default pairs would leave the commonest deck
        there is unwarned."""
        result, _ = _convert(deck(section=sec(hmin=0.2, hmax=2.0)))
        hits = _warns(result, "HMIN=0.2 / HMAX=2")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 174", hits[0])
        self.assertIn("manual's own default", hits[0])

    def test_no_bound_at_all_is_not_reported(self):
        """HMIN = HMAX = 0 asks for no bound, which is what Radioss does
        anyway — nothing is lost, so nothing is said."""
        result, _ = _convert(deck(section=sec(hmin=0.0, hmax=0.0)))
        self.assertEqual(_warns(result, "HMIN="), [])

    def test_the_exact_constant_h_pair_is_not_reported_as_a_loss(self):
        result, _ = _convert(deck(section=sec(hmin=1.0, hmax=1.0)))
        self.assertEqual(_warns(result, "HMIN="), [])

    def test_the_property_sits_under_the_secid_so_the_part_is_not_repointed(self):
        _, starter = _convert(deck(
            part="*PART\nsph part\n" + _row(1, 5, 1) + "\n",
            section=sec(secid=5)))
        self.assertIn("/PROP/SPH/5", starter)
        self.assertEqual(_col_i(_rows(_block(starter, "/PART/1"))[1], 1, 10), 5)

    def test_a_mixed_family_secid_never_carries_two_props(self):
        """Two /PROP cards on one id is starter ERROR 79 (DUPLICATE ID IN PID
        DEFINITION). The SPH property moves to a synthesized id and its parts
        are repointed."""
        mixed = ("*KEYWORD\n" + NODES + SPH8 + SHELL2
                 + "*PART\nsph part\n" + _row(1, 5, 1) + "\n"
                 + sec(secid=5)
                 + "*SECTION_SHELL\n" + _row(5, 2, "", 3, "", "", "", "")
                 + "\n" + _row(1.0, 1.0, 1.0, 1.0) + "\n"
                 + MAT + TERM + "*END\n")
        result, starter = _convert(mixed)
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/5")), 1)
        self.assertEqual(_blocks(starter, "/PROP/SPH/5"), [])
        sph_props = _blocks(starter, "/PROP/SPH/")
        self.assertEqual(len(sph_props), 1)
        moved = int(sph_props[0][0].rsplit("/", 1)[1])
        self.assertNotEqual(moved, 5)
        self.assertEqual(_col_i(_rows(_block(starter, "/PART/1"))[1], 1, 10),
                         moved)
        self.assertTrue(_warns(result, "is shared by SPH part(s)"),
                        result.warnings)

    def test_a_sectionless_particle_part_gets_a_placeholder(self):
        """Without one the /PART would point at a property nothing defines
        (ERROR 178) or inherit the element-free placeholder /PROP/SHELL, which
        a /SPHCEL cannot run on."""
        result, starter = _convert(
            "*KEYWORD\n" + NODES + SPH8 + PART + MAT + TERM + "*END\n")
        self.assertIn("/PROP/SPH/1", starter)
        self.assertNotIn("/PROP/SHELL/1", starter)
        self.assertTrue(_warns(result, "PLACEHOLDER SPH property"),
                        result.warnings)

    def test_an_element_free_part_still_gets_its_sph_property(self):
        """An element-free *PART is idiomatic, not a mistake — and a /PART
        pointing at an undefined property is starter ERROR 178."""
        d = ("*KEYWORD\n" + NODES + SPH8 + PART
             + "*PART\nempty\n" + _row(2, 9, 1) + "\n"
             + sec() + sec(secid=9) + MAT + TERM + "*END\n")
        _, starter = _convert(d)
        self.assertIn("/PROP/SPH/9", starter)

    def test_an_unreferenced_section_emits_nothing(self):
        result, starter = _convert(deck(section=sec() + sec(secid=77)))
        self.assertEqual(_blocks(starter, "/PROP/SPH/77"), [])
        self.assertTrue(any(kw == "SECTION_SPH"
                            for kw, _ in result.recognized_not_emitted))

    def test_next_prop_id_skips_an_sph_secid(self):
        """/PROP/SPH sits under the SECID verbatim, so it is a FIFTH SECID-keyed
        /PROP namespace: a *SECTION_SPH at or above the auto-id base would
        otherwise collide with a synthesized property."""
        state = ConversionState()
        state.sec_sph[90001] = object()
        self.assertNotEqual(state.next_prop_id(), 90001)

    def test_a_law_outside_the_sph_whitelist_is_reported(self):
        """Only a law that calls INIT_MAT_KEYWORD(...,'SPH') sets
        MATPARAM%PROP_SPH (init_mat_keyword.F:272-273); anything else is starter
        ERROR 3046/3047. dyna2rad imposes no law filter at all."""
        # *MAT_COHESIVE_MIXED_MODE -> /MAT/LAW138, not on the SPH whitelist.
        mat = ("*MAT_COHESIVE_MIXED_MODE\n"
               + _row(1, RHO, 1.0, 100.0, 100.0, 0.1, 0.1, 1.0) + "\n"
               + _row(1.0, 1.0) + "\n")
        result, _ = _convert(deck(mat=mat))
        self.assertTrue(_warns(result, "does NOT declare SPH compatibility"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class ControlSphAndSphglo(unittest.TestCase):
    """*CONTROL_SPH -> /SPHGLO, and every column that does not map."""

    @staticmethod
    def _ctrl(*cards):
        return "*CONTROL_SPH\n" + "".join(c + "\n" for c in cards)

    def test_cards_two_and_three_are_claimed_by_raw_contiguity(self):
        """An all-blank card 2 IS a card. Taking "the next non-blank line"
        instead would read card 3's ITHK/ISTAB/QL as CONT/DERIV/INI — the #119
        rule."""
        state = _dispatch("*KEYWORD\n"
                          + self._ctrl(_row(1, 0, "", 3, 500),
                                       "",
                                       _row(1, 2, 0.05, "", 7, 9))
                          + "*END\n")
        c = state.control_sph
        self.assertEqual((c.cont, c.deriv, c.ini), (0, 0, 0))
        self.assertEqual((c.ithk, c.istab, c.sphsort, c.ishift), (1, 2, 7, 9))
        self.assertAlmostEqual(c.ql, 0.05)

    def test_nmneigh_above_the_radioss_default_writes_sphglo(self):
        """radioss2017/CARDS/sphglo.cfg: Alpha_sort(20) Maxsph(10) Lneigh(10)
        Nneigh(10) Isol2sph(10), no title."""
        result, starter = _convert(deck(
            extra=self._ctrl(_row(1, 0, "", 3, 1500))))
        blk = _block(starter, "/SPHGLO")
        card = _rows(blk)[0]
        self.assertEqual(len(card), 60)
        self.assertAlmostEqual(_col_f(card, 1, 20), 0.25)   # Alpha_sort
        self.assertEqual(_col_i(card, 21, 30), 0)           # Maxsph (dead)
        self.assertEqual(_col_i(card, 31, 40), 1500)        # Lneigh
        self.assertEqual(_col_i(card, 41, 50), 1500)        # Nneigh
        self.assertEqual(_col_i(card, 51, 60), 1)           # Isol2sph
        self.assertTrue(_warns(result, "/SPHGLO Lneigh = Nneigh = 1500"),
                        result.warnings)

    def test_nmneigh_at_or_below_the_default_writes_no_card(self):
        """An all-blank /SPHGLO is not a no-op: measured, it HALVES the stored
        neighbour cap from 240 to 120. And emitting 150/150 would reduce the
        caps below Radioss's own defaults for nothing."""
        result, starter = _convert(deck(
            extra=self._ctrl(_row(1, 0, "", 3, 150))))
        self.assertNotIn("/SPHGLO", starter)
        self.assertTrue(_warns(result, "Radioss's own defaults are already"),
                        result.warnings)

    def test_a_deck_with_no_particles_writes_no_sphglo(self):
        d = ("*KEYWORD\n" + NODES
             + "*ELEMENT_SOLID\n" + _row(1, 1, 1, 2, 4, 3, 5, 6, 8, 7) + "\n"
             + "*PART\nsolid\n" + _row(1, 1, 1) + "\n"
             + "*SECTION_SOLID\n" + _row(1, 1) + "\n" + MAT + TERM
             + self._ctrl(_row(1, 0, "", 3, 1500)) + "*END\n")
        _, starter = _convert(d)
        self.assertNotIn("/SPHGLO", starter)

    def test_idim_two_is_reported_as_an_answer_changing_loss(self):
        """OpenRadioss SPH is 3D only. This is the one *CONTROL_SPH column whose
        loss changes the ANSWER rather than the accuracy."""
        result, _ = _convert(deck(extra=self._ctrl(_row(1, 0, "", 2, 150))))
        hits = _warns(result, "IDIM=2")
        self.assertTrue(hits, result.warnings)
        self.assertIn("3D ONLY", hits[0])

    def test_every_dropped_column_is_named(self):
        result, _ = _convert(deck(extra=self._ctrl(
            _row(5, 11, 1.5e-3, 3, 150, 12, 2.0e-4, 1.0e3),
            _row(1, 1, 2, 1, 3, 1, 1, 50),
            _row(1, 2, 0.05, "", 7, 9))))
        for needle in ("NCBS=5", "BOXID=11", "DT=0.0015", "FORM=12",
                       "START=0.0002", "MAXV=1000", "CONT=1", "DERIV=1",
                       "INI=2", "ISHOW=1", "IEROD=3", "ICONT=1", "IAVIS=1",
                       "ISYMP=50", "ITHK=1", "ISTAB=2", "QL=0.05",
                       "SPHSORT=7", "ISHIFT=9"):
            self.assertTrue(_warns(result, needle), (needle, result.warnings))

    def test_database_sphout_dt_reaches_the_engine_tfile(self):
        d = deck(extra="*DATABASE_SPHOUT\n" + _row(2.5e-5) + "\n")
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(d)
        res = convert(path, write_log=False)
        engine = open(res.engine_path).read()
        tmp.cleanup()
        self.assertIn("/TFILE", engine)
        idx = engine.splitlines().index("/TFILE")
        self.assertAlmostEqual(float(engine.splitlines()[idx + 1]), 2.5e-5)


# ═════════════════════════════════════════════════════════════════════════════
class TimeHistory(unittest.TestCase):
    """*DATABASE_HISTORY_SPH[_SET] -> /TH/SPHCEL, screened the #106 way."""

    def test_the_group_lists_one_id_per_line(self):
        """LS-DYNA writes EIGHT ids per card; /TH/SPHCEL takes ONE. Packing
        them is worse than an error — measured, seven dangling ids in columns
        11+ gave 0 errors and only advisory WARNING 100214, so the channels
        vanished without even reaching the ERROR 69 check."""
        _, starter = _convert(deck(
            extra="*DATABASE_HISTORY_SPH\n" + _row(1, 2, 3, 4) + "\n"))
        blk = _block(starter, "/TH/SPHCEL/")
        ids = _rows(blk)[2:]
        self.assertEqual([_col_i(ln, 1, 10) for ln in ids], [1, 2, 3, 4])
        self.assertTrue(all(len(ln.strip()) <= 10 for ln in ids), ids)

    def test_a_dangling_id_is_screened_out(self):
        """Not a lost channel: starter ERROR 69 (TH ELEMENT SELECTION ID=n DOES
        NOT EXIST) refuses the whole deck. dyna2rad's SPH branch is the only
        element branch in converttimehistory.cxx with no such filter."""
        result, starter = _convert(deck(
            extra="*DATABASE_HISTORY_SPH\n" + _row(1, 2, 3, 99) + "\n"))
        blk = _block(starter, "/TH/SPHCEL/")
        ids = [_col_i(ln, 1, 10) for ln in _rows(blk)[2:]]
        self.assertEqual(ids, [1, 2, 3])
        hits = _warns(result, "not an emitted /SPHCEL")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 69", hits[0])

    def test_a_group_that_screens_to_nothing_is_not_written(self):
        """An empty TH group is a starter refusal in its own right
        (ERROR 1109)."""
        result, starter = _convert(deck(
            extra="*DATABASE_HISTORY_SPH\n" + _row(97, 98, 99) + "\n"))
        self.assertNotIn("/TH/SPHCEL", starter)
        self.assertTrue(_warns(result, "none of the requested ids"),
                        result.warnings)

    def test_the_set_form_expands_node_sets(self):
        """"IDn for NODE_SET, SPH_SET, and DES_SET refers to node set ID n
        defined using the *SET_NODE_{OPTION}" — set ids, not particle ids."""
        _, starter = _convert(deck(
            extra="*SET_NODE_LIST\n" + _row(20) + "\n" + _row(2, 5, 7) + "\n"
                  + "*DATABASE_HISTORY_SPH_SET\n" + _row(20) + "\n"))
        blk = _block(starter, "/TH/SPHCEL/")
        ids = [_col_i(ln, 1, 10) for ln in _rows(blk)[2:]]
        self.assertEqual(sorted(ids), [2, 5, 7])

    def test_an_undefined_node_set_is_named(self):
        """Wording generalized by the output-parity batch: _SPH_SET now shares
        ONE _SET expander with _NODE_SET / _BEAM_SET / _SHELL_SET / _SOLID_SET
        / _DISCRETE_SET, so the message names the pool the id failed to resolve
        in rather than hard-coding *SET_NODE into the SPH branch."""
        result, starter = _convert(deck(
            extra="*DATABASE_HISTORY_SPH_SET\n" + _row(20) + "\n"))
        self.assertNotIn("/TH/SPHCEL", starter)
        hits = _warns(result, "set id(s) [20] resolve to no converted "
                              "*SET_NODE")
        self.assertTrue(hits, result.warnings)
        self.assertIn("*DATABASE_HISTORY_SPH_SET", hits[0])

    def test_the_keyword_leaves_skipped_keywords(self):
        result, _ = _convert(deck(
            extra="*DATABASE_HISTORY_SPH\n" + _row(1) + "\n"))
        self.assertEqual([k for k in result.skipped_keywords if "SPH" in k], [])


# ═════════════════════════════════════════════════════════════════════════════
IMPLICIT = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
            + "*CONTROL_TERMINATION\n" + _row(1.0) + "\n")


class ElementRegistryArms(unittest.TestCase):
    """THE #120 AUDIT. SPH is a new element family, so every site that walks the
    element containers had to be re-decided. One test per REAL arm — each fails
    if the arm is removed — plus the two no-arm verdicts that are answered by a
    named warning instead."""

    def test_particles_are_not_clamped_by_the_free_node_guard(self):
        """THE #120 BUG CLASS. The implicit singularity guard fixes every node
        attached to no element in all six DOFs. An SPH particle carries mass and
        kernel stiffness, so without this arm the guard puts /BCS 111 111 on
        EVERY particle — which the starter accepts with 0 ERRORS and which
        freezes the whole cloud. Every corpus SPH deck is explicit and returns
        before the guard, so only a synthetic implicit deck reaches it."""
        result, starter = _convert(deck(extra=IMPLICIT))
        particles = {_col_i(ln, 1, 10)
                     for ln in _rows(_block(starter, "/SPHCEL/1"))}
        fixed = set()
        grab = False
        for ln in starter.splitlines():
            if ln.startswith("/GRNOD/NODE/"):
                grab = False
            if "free_reference_nodes" in ln:
                grab = True
                continue
            if grab:
                if ln.startswith("/") or ln.startswith("#"):
                    grab = ln.startswith("#")
                    continue
                fixed.update(int(t) for t in ln.split())
        self.assertEqual(len(particles), 8)
        self.assertEqual(sorted(particles & fixed), [])
        self.assertEqual([w for w in result.warnings
                          if "free node(s) attached to no element" in w], [])

    def test_a_modal_sph_deck_finds_a_node_for_its_dummy_load(self):
        """The implicit engine refuses to start with no loading data at all
        (MESSAGE ID 79), so a modal run gets a unit /CLOAD on a free structural
        node. Without the arm the candidate set is empty."""
        modal = ("*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(5) + "\n") + IMPLICIT
        result, starter = _convert(deck(extra=modal))
        self.assertEqual(
            [w for w in result.warnings if "no free node to put a dummy" in w],
            [])
        self.assertIn("/CLOAD", starter)

    def test_particle_nodes_are_dampable(self):
        """/DAMP is NODE-based Rayleigh damping with no element-type
        restriction, so a particle's node is damped exactly like a brick's."""
        d = deck(extra="*DAMPING_GLOBAL\n" + _row(0, 5.0) + "\n")
        _, starter = _convert(d)
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if "damping" in b[1]]
        self.assertTrue(grp)
        ids = {int(t) for ln in grp[0][2:] if not ln.startswith("#")
               for t in ln.split()}
        self.assertEqual(sorted(ids), [n for n, *_ in LATTICE])

    def test_a_part_scoped_damping_card_reaches_particles(self):
        d = deck(extra="*DAMPING_GLOBAL\n" + _row(0, 5.0) + "\n"
                       + "*DAMPING_PART_MASS\n" + _row(1, 0, 1.0) + "\n")
        result, _ = _convert(d)
        self.assertEqual([w for w in result.warnings
                          if "no deformable node" in w], [])
        self.assertEqual([w for w in result.warnings
                          if "holds no deformable" in w], [])

    def test_initial_velocity_generation_reaches_particles(self):
        """The highest-value row of the audit: driving an SPH body by
        *INITIAL_VELOCITY_GENERATION with STYP=2/3 is the idiomatic way to
        launch a bird. Without the arm the group is EMPTY and the projectile
        does not move."""
        gen = ("*INITIAL_VELOCITY_GENERATION\n"
               + _row(1, 2, 0.0, 0.0, 0.0, -100.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        _, starter = _convert(deck(extra=gen))
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if "InitVel" in b[1] or "inivel" in b[1].lower()]
        self.assertTrue(grp, starter)
        ids = {int(t) for ln in grp[0][2:] if not ln.startswith("#")
               for t in ln.split()}
        self.assertEqual(sorted(ids), [n for n, *_ in LATTICE])

    def test_a_particle_part_is_a_usable_contact_SECONDARY_side(self):
        """In Radioss an SPH<->structure contact is an /INTER with the PARTICLES
        as the secondary node group. Before the batch only the *SET_NODE
        spelling reached them, and then only by accident."""
        shell = ("*ELEMENT_SHELL\n"
                 + f"{1:>8}{2:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + shell + PART
             + "*PART\nshell part\n" + _row(2, 2, 1) + "\n"
             + sec()
             + "*SECTION_SHELL\n" + _row(2, 2, "", 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n" + MAT + TERM
             + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
             + _row(1, 2, 3, 3) + "\n" + _row(0.2, 0.2) + "\n" + "*END\n")
        _, starter = _convert(d)
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if "contact_slave" in b[1]]
        self.assertTrue(grp, starter)
        ids = {int(t) for b in grp for ln in b[2:]
               if not ln.startswith("#") for t in ln.split()}
        self.assertTrue({n for n, *_ in LATTICE} <= ids, sorted(ids))

    def test_a_particle_part_on_a_contact_MAIN_side_is_named(self):
        """NO-ARM VERDICT + WARNING. A particle has no face, so it contributes
        nothing to a main surface. With other parts in the scope the interface
        converts LOOKING HEALTHY while the SPH side is simply absent — a silence
        _drop_interface can never break, because the interface is not dropped."""
        shell = ("*ELEMENT_SHELL\n"
                 + f"{1:>8}{2:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + shell + PART
             + "*PART\nshell part\n" + _row(2, 2, 1) + "\n"
             + sec()
             + "*SECTION_SHELL\n" + _row(2, 2, "", 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n" + MAT + TERM
             + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
             + _row(2, 1, 3, 3) + "\n" + _row(0.2, 0.2) + "\n" + "*END\n")
        result, _ = _convert(d)
        hits = _warns(result, "hold SPH particles")
        self.assertTrue(hits, result.warnings)
        self.assertIn("NO FACE", hits[0])

    def test_a_rigid_particle_part_reaches_its_rbody(self):
        rigid = ("*MAT_RIGID\n" + _row(1, RHO, 210000.0, 0.3) + "\n"
                 + _row(0.0, 7, 7) + "\n" + _row(0.0, 0.0, 0.0) + "\n")
        _, starter = _convert(deck(mat=rigid))
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if b[1].startswith("rb_nodes")]
        self.assertTrue(grp, starter)
        ids = {int(t) for b in grp for ln in b[2:]
               if not ln.startswith("#") for t in ln.split()}
        self.assertTrue({n for n, *_ in LATTICE} <= ids, sorted(ids))

    def test_orphan_particles_are_reported_as_mesh_loss(self):
        """The orphan census is the ONE place that answers "did the conversion
        drop any of my mesh?"."""
        elems = SPH8 + _cell(99, 99, MASS)
        result, _ = _convert(deck(elem=elems))
        hits = _warns(result, "MESH LOSS")
        self.assertTrue(hits, result.warnings)
        self.assertIn("PID 99 (1 sph)", hits[0])

    def test_particle_nodes_count_as_referenced(self):
        """An SPH particle IS its node: a pruning pass that dropped that node as
        unreferenced would delete the particle with it."""
        from k2rad.writer.mesh import _referenced_node_ids
        state = _dispatch("*KEYWORD\n" + NODES + SPH8 + "*END\n")
        self.assertTrue({n for n, *_ in LATTICE}
                        <= _referenced_node_ids(state))

    def test_a_particle_part_is_meshed_not_element_free(self):
        """Without this arm an SPH part got the element-free placeholder
        /PROP/SHELL — the bare "/PART on a shell property and nothing else"
        shape the thick-shell batch found, and a /SPHCEL cannot run on it."""
        from k2rad.writer.mesh import _element_free_part_ids
        state = _dispatch("*KEYWORD\n" + NODES + SPH8 + PART + "*END\n")
        self.assertEqual(_element_free_part_ids(state, {1: 1}), set())

    def test_optt_on_a_particle_only_part_is_reported_as_inert(self):
        """There is no NUMSPH loop in i7sti3.F either, so an SPH part's OPTT is
        written into the /PART Thick column and never read."""
        pc = ("*PART_CONTACT\nsph part\n" + _row(1, 1, 1) + "\n"
              + _row(0.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0) + "\n")
        result, _ = _convert(
            "*KEYWORD\n" + NODES + SPH8 + pc + sec() + MAT + TERM + "*END\n")
        hits = _warns(result, "SOLID or SPH elements")
        self.assertTrue(hits, result.warnings)
        self.assertIn("1 (OPTT=5)", hits[0])

    def test_gapmin_measures_clearance_from_particle_nodes(self):
        """--auto-gapmin's node-side clearance is exactly what a particle CAN
        answer; the surface faceting is exactly what it cannot. The asymmetry is
        deliberate."""
        from k2rad.gapmin import _part_nodes_map, _surface_triangles
        state = _dispatch("*KEYWORD\n" + NODES + SPH8 + PART + "*END\n")
        self.assertEqual(sorted(_part_nodes_map(state)[1]),
                         [n for n, *_ in LATTICE])
        verts, faces = _surface_triangles(state, [1])
        self.assertEqual(faces, [])

    def test_a_cross_section_plane_names_the_particles_it_cannot_cut(self):
        """NO-ARM VERDICT + WARNING. A /SECT sums the force the cut ELEMENTS
        transmit and its card carries brick/shell/truss/beam/spring/tria groups
        only — there is no SPH group at any version."""
        cs = ("*DATABASE_CROSS_SECTION_PLANE\n"
              + _row(0, 5.0, 5.0, 5.0, 5.0, 5.0, 15.0, 0.0) + "\n"
              + _row(0.0, 0.0, 0.0, 0, 0, 0) + "\n")
        result, _ = _convert(deck(extra=cs))
        hits = _warns(result, "CANNOT be cut")
        self.assertTrue(hits, result.warnings)
        self.assertIn("UNDER-REPORTS", hits[0])

    def test_reference_geometry_on_a_particle_part_is_named(self):
        """NO-ARM VERDICT + WARNING. /XREF is reference geometry for SOLID
        elements (8/4-node only, ERROR 2013); Radioss has no stress-free
        reference state for a particle at all."""
        ref = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
               + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n"
                         for n, x, y, z in LATTICE))
        result, starter = _convert(deck(extra=ref))
        self.assertNotIn("/XREF", starter)
        self.assertTrue(_warns(result, "hold SPH particles whose nodes"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class IncludeTransformOffsets(unittest.TestCase):
    """*INCLUDE_TRANSFORM id offsetting must mirror the handler's own walks.

    k2rad bakes the offsets into the deck text; dyna2rad emits a //SUBMODEL and
    lets Radioss apply them — which CANNOT work for SPH, because the /SPHCEL id
    column is a plain INT with no entity type and the submodel machinery leaves
    it alone while /NODE moves. Measured on probe decks j and k: IDNOFF=1000
    (with or without a matching IDEOFF) gave four ERROR 78 and TOTAL MASS = 0.
    """

    OFF = {"n": 1000, "e": 2000, "p": 30, "r": 40, "m": 50}

    def _off(self, keyword: str, body: str):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n" + keyword + "\n" + body + "*END\n")
        blocks = [b for b in parse_k_file(path) if b.keyword == keyword[1:]]
        assert len(blocks) == 1
        _offset_block(blocks[0], _OFFSET_SPECS[keyword[1:]], self.OFF,
                      lambda m: None)
        tmp.cleanup()
        return blocks[0].raw

    def test_the_particle_id_takes_the_NODE_offset_not_the_element_one(self):
        """Unique in the *ELEMENT_ family: the particle IS its node, so IDNOFF
        is the only offset that can apply to field 0 — IDEOFF there would break
        the cell<->node identity Radioss enforces."""
        raw = self._off("*ELEMENT_SPH", _cell(1, 1, 2.0e-3))
        self.assertEqual(_col_i(raw[0], 1, 8), 1001)     # NID + IDNOFF
        self.assertEqual(_col_i(raw[0], 9, 16), 31)      # PID + IDPOFF
        self.assertAlmostEqual(_col_f(raw[0], 17, 32), 2.0e-3)

    def test_the_sixteen_wide_mass_column_survives_the_rewrite(self):
        """A uniform 10-wide re-slice cuts a right-justified F16 mass in half —
        the *ELEMENT_MASS defect this mirrors."""
        raw = self._off("*ELEMENT_SPH", _cell(1, 1, 9.683426e-05))
        self.assertAlmostEqual(_col_f(raw[0], 17, 32), 9.683426e-05)

    def test_nend_moves_with_the_nodes(self):
        raw = self._off("*ELEMENT_SPH", _cell(1, 1, 2.0e-3, 8))
        self.assertEqual(_col_i(raw[0], 1, 8), 1001)
        self.assertEqual(int(raw[0][32:].strip()), 1008)

    def test_the_volume_spelling_is_registered(self):
        raw = self._off("*ELEMENT_SPH_VOLUME", _cell(1, 1, 2.0e-6))
        self.assertEqual(_col_i(raw[0], 1, 8), 1001)

    def test_section_sph_offsets_every_set_secid(self):
        raw = self._off("*SECTION_SPH",
                        _row(1, 1.2) + "\n" + _row(2, 1.1) + "\n")
        self.assertEqual(_col_i(raw[0], 1, 10), 41)
        self.assertEqual(_col_i(raw[1], 1, 10), 42)

    def test_section_sph_ellipse_strides_its_second_card(self):
        """Same RAW-contiguity rule as the handler: card 2 carries no id but IS
        a card, and rewriting the next set's SECID out of a column of h values
        is what a "next non-blank line" walk would do."""
        raw = self._off("*SECTION_SPH_ELLIPSE",
                        _row(1, 1.2, 0.2, 2.0) + "\n"
                        + _row(1.0, 1.0, 2.0) + "\n"
                        + _row(2, 1.1, 0.2, 2.0) + "\n"
                        + _row(1.0, 1.0, 1.0) + "\n")
        self.assertEqual(_col_i(raw[0], 1, 10), 41)
        self.assertEqual(raw[1], _row(1.0, 1.0, 2.0))
        self.assertEqual(_col_i(raw[2], 1, 10), 42)

    def test_an_offset_include_keeps_the_particles_and_their_mass(self):
        """End to end: the ids that reach the /SPHCEL block are the OFFSET ones,
        and every particle still resolves to a /NODE."""
        tmp = tempfile.TemporaryDirectory()
        inc = os.path.join(tmp.name, "inc.k")
        with open(inc, "w") as fh:
            fh.write("*KEYWORD\n" + NODES + SPH8 + PART + sec() + MAT
                     + "*END\n")
        main = os.path.join(tmp.name, "main.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\ninc.k\n"
                     + _row(1000, 2000, 30, 50, 40) + "\n"
                     + _row(0, 0, 0, 0, 0) + "\n"
                     + _row(0) + "\n" + TERM + "*END\n")
        res = convert(main, write_log=False)
        starter = open(res.starter_path).read()
        tmp.cleanup()
        ids = [_col_i(ln, 1, 10)
               for ln in _rows(_block(starter, "/SPHCEL/31"))]
        self.assertEqual(ids, [n + 1000 for n, *_ in LATTICE])
        nodes = {_col_i(ln, 1, 10)
                 for ln in _rows(_block(starter, "/NODE"))}
        self.assertTrue(set(ids) <= nodes)


# ═════════════════════════════════════════════════════════════════════════════
class NoRegressionWithoutTheKeyword(unittest.TestCase):
    """A deck with no SPH must come out BYTE-IDENTICAL: the batch adds a
    container, a prepass, an emit block and a global card, every one of them
    gated."""

    DECK = ("*KEYWORD\n" + NODES
            + "*ELEMENT_SOLID\n" + _row(1, 1, 1, 2, 4, 3, 5, 6, 8, 7) + "\n"
            + "*PART\nsolid part\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + MAT + TERM + "*END\n")

    def test_a_solid_deck_is_untouched(self):
        result, starter = _convert(self.DECK)
        self.assertIn("/PROP/SOLID/1", starter)
        self.assertEqual(_blocks(starter, "/PROP/SPH"), [])
        self.assertEqual(_blocks(starter, "/SPHCEL"), [])
        self.assertNotIn("/SPHGLO", starter)
        self.assertEqual([w for w in result.warnings if "SPH" in w], [])

    def test_the_checked_in_golden_fixtures_are_byte_identical(self):
        """The strongest available statement that nothing moved: the goldens are
        whole-file captures of the emitted decks, and none of the five fixtures
        contains a particle."""
        root = Path(__file__).resolve().parent / "fixtures"
        for src in sorted(root.glob("*.k")):
            with self.subTest(fixture=src.name):
                tmp = tempfile.TemporaryDirectory()
                res = convert(str(src), os.path.join(tmp.name, src.stem),
                              write_log=False)
                for path, tag in ((res.starter_path, "0000"),
                                  (res.engine_path, "0001")):
                    got = open(path).read().replace("\r\n", "\n")
                    want = (root / "expected"
                            / f"{src.stem}_{tag}.rad").read_text().replace(
                                "\r\n", "\n")
                    self.assertEqual(got, want, f"{src.name} {tag}")
                tmp.cleanup()


# ═════════════════════════════════════════════════════════════════════════════
# REVIEW ROUND
# ═════════════════════════════════════════════════════════════════════════════

class OffsetReadsTheCardLikeTheHandler(unittest.TestCase):
    """``*INCLUDE_TRANSFORM`` rewriter vs ``handlers._parse_sph_cell``.

    The rewriter used to slice a FIXED 8/8/16/8 card while the handler that
    reads the same card prefers a WHITESPACE split, so the two silently
    disagreed on every layout whose columns are not exactly 8/8/16. The
    invariant is one line long and is asserted directly:

        parse(offset(line)) == parse(line) + offsets
    """

    OFF = {"n": 1000, "p": 30}

    LAYOUTS = {
        "I8 canonical":     "       1       2  9.6834260e-05",
        "I8 + NEND":        "       1       2  9.6834260e-05       8",
        "I10 ids":          "       101         2   9.6834260e-05",
        "I10 wide ids":     "    100001         2   9.6834260e-05",
        "comma free":       "1,2,9.6834260e-05",
        "mixed fixed/free": "  150061 2 9.683426e-05",
        "8-wide mass":      "       1       2 9.68e-05       8",
        "ids fill 8 cols":  "1234567812345678  9.6834260e-05",
        "trailing comment": "       1       2  9.6834260e-05  $ a note",
    }

    def _rewrite(self, line: str) -> str:
        from k2rad.assembly import _off_element_sph

        class _B:
            def __init__(self, raw):
                self.raw = list(raw)
                self.keyword = "ELEMENT_SPH"

        b = _B([line])
        _off_element_sph(b, dict(self.OFF), lambda *a, **k: None)
        return b.raw[0]

    def test_every_layout_reads_back_as_the_source_plus_the_offsets(self):
        from k2rad.handlers import _parse_sph_cell
        for name, line in self.LAYOUTS.items():
            with self.subTest(layout=name):
                src = _parse_sph_cell(line)
                self.assertIsNotNone(src, line)
                want = (src[0] + self.OFF["n"], src[1] + self.OFF["p"],
                        src[2], src[3] + self.OFF["n"] if src[3] else 0)
                self.assertEqual(_parse_sph_cell(self._rewrite(line)), want)

    def test_the_I10_layout_used_to_corrupt_all_three_id_cells(self):
        """The measured regression, pinned by its numbers: the I8 slice read
        NID 1001 / PID 31 / MASS 2.0 out of a card stating 101 / 2 / 9.68e-05 —
        a mass 20000x out and a part id nothing in the deck defines."""
        from k2rad.handlers import _parse_sph_cell
        got = _parse_sph_cell(self._rewrite(self.LAYOUTS["I10 ids"]))
        self.assertEqual(got, (1101, 32, 9.683426e-05, 0))

    def test_a_canonical_I8_card_keeps_its_columns(self):
        """The fallback must not be reached on the layout the corpus uses: a
        reflowed card would still READ back, but every downstream column
        assertion in this file — and any human reading the include — depends on
        the ruler surviving."""
        out = self._rewrite(self.LAYOUTS["I8 canonical"])
        self.assertEqual(_col_i(out, 1, 8), 1001)
        self.assertEqual(_col_i(out, 9, 16), 32)
        self.assertAlmostEqual(_col_f(out, 17, 32), 9.683426e-05)

    def test_a_trailing_comment_survives(self):
        self.assertTrue(self._rewrite(self.LAYOUTS["trailing comment"])
                        .endswith("$ a note"))


class DatabaseHistorySphOffsets(unittest.TestCase):
    """``*DATABASE_HISTORY_SPH[_SET]`` had no offset spec while every sibling
    (NODE / SHELL / SOLID / TSHELL) has one, so under ``*INCLUDE_TRANSFORM`` the
    requested ids stayed put while the particles they name moved — channels
    silently attached to the PARENT deck's bodies, which the ERROR-69 screen
    cannot catch because those ids do exist as /SPHCEL."""

    def test_the_particle_ids_take_IDNOFF(self):
        spec = _OFFSET_SPECS["DATABASE_HISTORY_SPH"]
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*DATABASE_HISTORY_SPH\n"
                     + _row(1, 2, 3, 4) + "\n*END\n")
        blk = [b for b in parse_k_file(path)
               if b.keyword == "DATABASE_HISTORY_SPH"][0]
        _offset_block(blk, spec, {"n": 1000, "e": 2000, "s": 7}, lambda m: None)
        tmp.cleanup()
        self.assertEqual([int(t) for t in blk.raw[0].split()],
                         [1001, 1002, 1003, 1004])

    def test_the_set_spelling_takes_IDSOFF(self):
        spec = _OFFSET_SPECS["DATABASE_HISTORY_SPH_SET"]
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*DATABASE_HISTORY_SPH_SET\n"
                     + _row(7, 8) + "\n*END\n")
        blk = [b for b in parse_k_file(path)
               if b.keyword == "DATABASE_HISTORY_SPH_SET"][0]
        _offset_block(blk, spec, {"n": 1000, "s": 500}, lambda m: None)
        tmp.cleanup()
        self.assertEqual([int(t) for t in blk.raw[0].split()], [507, 508])

    def test_an_include_attaches_the_channels_to_its_OWN_particles(self):
        """End to end. Both decks number their particles 1-4; the include is
        offset to 1001-1004 and asks for 1-4, which means ITS OWN."""
        tmp = tempfile.TemporaryDirectory()
        sub_nodes = "*NODE\n" + "".join(
            f"{n:>8}{x + 50.0:>16}{y:>16}{z:>16}\n"
            for n, x, y, z in LATTICE[:4])
        sub = ("*KEYWORD\n" + sub_nodes
               + "*ELEMENT_SPH\n"
               + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE[:4])
               + "*PART\nsub\n" + _row(1, 1, 1) + "\n"
               + "*DATABASE_HISTORY_SPH\n" + _row(1, 2, 3, 4) + "\n*END\n")
        parent = ("*KEYWORD\n" + NODES + SPH8 + PART + sec() + MAT + TERM
                  + "*INCLUDE_TRANSFORM\nsub.k\n"
                  + _row(1000, 1000, 30, 30, 30, 30, 30) + "\n"
                  + _row(30) + "\n*END\n")
        with open(os.path.join(tmp.name, "sub.k"), "w") as fh:
            fh.write(sub)
        main = os.path.join(tmp.name, "deck.k")
        with open(main, "w") as fh:
            fh.write(parent)
        result = convert(main, write_log=False)
        starter = open(result.starter_path).read()
        tmp.cleanup()
        th = _blocks(starter, "/TH/SPHCEL/")
        self.assertEqual(len(th), 1, starter)
        ids = sorted(int(ln) for ln in th[0][3:] if ln.strip()
                     and not ln.startswith("#") and ln.strip().isdigit())
        self.assertEqual(ids, [1001, 1002, 1003, 1004])
        # ... and the generic "no offset map" complaint is gone
        self.assertEqual(
            [w for w in result.warnings
             if "no offset map" in w and "DATABASE_HISTORY_SPH" in w], [])


class MassIsNeverSilentlyInvented(unittest.TestCase):
    """A section whose particles state NO mass at all. The old code fell to a
    hard-coded ``Mp = 1.0`` and then described it with four separate falsehoods:
    that the fabrication "cannot happen here", that Mp was "the mean of the
    particles that DO state one" when none does, that the particles "carry
    DIFFERENT masses" when all were identically blank, and an h ratio computed
    entirely from the invented number."""

    BLANK = "*ELEMENT_SPH\n" + "".join(_cell(n, 1) for n, *_ in LATTICE)

    def test_the_mass_is_derived_from_the_fill_not_set_to_one(self):
        result, starter = _convert(deck(elem=self.BLANK))
        mp = _col_f(_cards(_block(starter, "/PROP/SPH/1"))[0], 1, 20)
        self.assertAlmostEqual(mp, RHO * D_REF ** 3, places=12)
        self.assertNotAlmostEqual(mp, 1.0)
        self.assertAlmostEqual(_total_mass(starter), 8 * RHO * D_REF ** 3,
                               places=12)
        self.assertTrue(_warns(result, "MASS INVENTED"), result.warnings)

    def test_the_report_says_the_source_stated_none(self):
        result, _ = _convert(deck(elem=self.BLANK))
        hit = _warns(result, "MASS INVENTED")[0]
        self.assertIn("NOT ONE of the 8 particle(s)", hit)
        self.assertIn("SOURCE NEVER STATED", hit)
        self.assertIn("rho x d_ref^3", hit)

    def test_none_of_the_four_false_claims_is_made(self):
        result, _ = _convert(deck(elem=self.BLANK))
        joined = " ".join(result.warnings)
        self.assertNotIn("the fabrication cannot happen here", joined)
        self.assertNotIn("the mean of the particles that DO state one", joined)
        self.assertNotIn("the particles carry DIFFERENT masses", joined)
        self.assertNotIn("a ratio of", joined)

    def test_the_decks_own_smoothing_length_still_survives(self):
        """Every cell is Flag 0, so the property's h is NOT overwritten
        (spinih.F:85-109) — the one piece of good news in this case."""
        _, starter = _convert(deck(elem=self.BLANK))
        cards = _cards(_block(starter, "/PROP/SPH/1"))
        self.assertAlmostEqual(_col_f(cards[1], 11, 30), 1.2 * D_REF, places=9)

    def test_without_a_density_it_falls_back_and_says_so(self):
        nomat = "*MAT_ELASTIC\n" + _row(1, 0.0, 210000.0, 0.3) + "\n"
        result, starter = _convert(deck(elem=self.BLANK, mat=nomat))
        mp = _col_f(_cards(_block(starter, "/PROP/SPH/1"))[0], 1, 20)
        self.assertEqual(mp, 1.0)
        self.assertIn("a bare unit mass", _warns(result, "MASS INVENTED")[0])

    def test_a_partly_blank_section_still_uses_the_stated_mean(self):
        """The MIXED case is unchanged and its report is the accurate one: with
        seven stated masses and one blank, Mp IS the mean of the seven."""
        elems = ("*ELEMENT_SPH\n"
                 + "".join(_cell(n, 1, MASS * (k + 1))
                           for k, (n, *_) in enumerate(LATTICE[:7]))
                 + _cell(LATTICE[7][0], 1))
        result, starter = _convert(deck(elem=elems))
        mean = MASS * (1 + 2 + 3 + 4 + 5 + 6 + 7) / 7.0
        mp = _col_f(_cards(_block(starter, "/PROP/SPH/1"))[0], 1, 20)
        self.assertAlmostEqual(mp, mean, places=12)
        # the blank particle takes Mp, the seven keep their own
        self.assertAlmostEqual(_total_mass(starter),
                               MASS * (1 + 2 + 3 + 4 + 5 + 6 + 7) + mean,
                               places=12)
        self.assertEqual(_warns(result, "MASS INVENTED"), [])
        self.assertTrue(_warns(result, "state no mass of their own"))

    def test_an_all_volume_section_multiplies_by_the_density(self):
        """Mp on the volume route is rho x V, not V. Dropping the rho factor is
        a factor of 1/rho = 127389x on this deck and nothing else catches it."""
        vol = 2.0e-6
        elems = ("*ELEMENT_SPH_VOLUME\n"
                 + "".join(_cell(n, 1, vol) for n, *_ in LATTICE))
        _, starter = _convert(deck(elem=elems))
        mp = _col_f(_cards(_block(starter, "/PROP/SPH/1"))[0], 1, 20)
        self.assertAlmostEqual(mp, RHO * vol, places=15)
        self.assertNotAlmostEqual(mp, vol, places=15)

    def test_a_uniform_volume_section_is_not_blamed_on_a_mass_spread(self):
        """C6. Every cell states the SAME volume, so "the particles carry
        DIFFERENT masses" is false — /PROP/SPH simply has no volume field."""
        elems = ("*ELEMENT_SPH_VOLUME\n"
                 + "".join(_cell(n, 1, 2.0e-6) for n, *_ in LATTICE))
        result, _ = _convert(deck(elem=elems))
        hits = _warns(result, "only a /SPHCEL row can carry")
        self.assertTrue(hits, result.warnings)
        self.assertNotIn("carry DIFFERENT masses", hits[0])


class InterparticleDistance(unittest.TestCase):
    """``d_ref`` = "the maximum of the minimum distance between every particle"
    (Vol I R16 *SECTION_SPH Remark 1), and ``h0 = CSLH x d_ref``. The search
    used to stop at four grid rings, so a query whose nearest neighbour lay
    farther kept the best candidate INSIDE the searched block — an OVER-estimate
    of that particle's minimum, and therefore of a max OVER minima."""

    @staticmethod
    def _brute(pts):
        best = 0.0
        for i, p in enumerate(pts):
            d2 = min(((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                      + (p[2] - q[2]) ** 2)
                     for j, q in enumerate(pts) if j != i)
            best = max(best, d2 ** 0.5)
        return best

    LATTICE10 = [(i * 0.01, j * 0.01, k * 0.01)
                 for i in range(10) for j in range(10) for k in range(10)]

    def test_a_regular_fill_is_exact(self):
        from k2rad.writer.sph import _interparticle_distance
        self.assertAlmostEqual(_interparticle_distance(self.LATTICE10), 0.01,
                               places=12)

    def test_a_far_outlier_is_found_not_clipped_at_four_rings(self):
        """One particle at (5,5,5) beside a 0.09-wide lattice: its nearest
        neighbour is 8.504 away, ~850 grid rings out. The four-ring loop
        returned 0.01 — the lattice spacing — and h0 with it."""
        from k2rad.writer.sph import _interparticle_distance
        pts = self.LATTICE10 + [(5.0, 5.0, 5.0)]
        self.assertAlmostEqual(_interparticle_distance(pts), self._brute(pts),
                               places=9)

    def test_random_uniform_and_clustered_clouds_are_exact(self):
        import random
        from k2rad.writer.sph import _interparticle_distance
        random.seed(11)
        for trial in range(6):
            with self.subTest(trial=trial):
                n = random.randint(30, 200)
                pts = [(random.uniform(0, 10), random.uniform(0, 10),
                        random.uniform(0, 10)) for _ in range(n)]
                pts += [(random.gauss(0, 0.05), random.gauss(0, 0.05),
                         random.gauss(0, 0.05)) for _ in range(n // 3)]
                self.assertAlmostEqual(_interparticle_distance(pts),
                                       self._brute(pts), places=9)


class MassPrecision(unittest.TestCase):
    """``common._f`` renders anything below 1e-4 with ``%.6E``, and in Mg-mm-s
    every particle mass is below 1e-4 — measured, a stated 1.234567891E-09 came
    back from the starter as 1.2345680000000E-06 over 1000 particles. The two
    mass columns use a formatter that round-trips instead."""

    M = 1.234567891e-09

    #: Eight distinct nine-significant-digit masses. Each is written verbatim
    #: into the card's 16-wide MASS cell, so what the source states and what the
    #: emitted deck must state are the SAME decimal string — no rounding hides
    #: in the fixture.
    SPREAD = ["1.234567891e-09", "2.345678912e-09", "3.456789123e-09",
              "4.567891234e-09", "5.678912345e-09", "6.789123456e-09",
              "7.891234567e-09", "8.912345678e-09"]

    def test_the_property_mass_reads_back_exactly(self):
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, repr(self.M)) for n, *_ in LATTICE)
        _, starter = _convert(deck(elem=elems))
        cell = _cards(_block(starter, "/PROP/SPH/1"))[0][0:20]
        self.assertEqual(len(cell), 20)
        self.assertEqual(float(cell), self.M)

    def test_a_per_cell_mass_reads_back_exactly(self):
        elems = "*ELEMENT_SPH\n" + "".join(
            _cell(n, 1, m) for m, (n, *_) in zip(self.SPREAD, LATTICE))
        _, starter = _convert(deck(elem=elems))
        rows = _rows(_block(starter, "/SPHCEL/1"))
        self.assertEqual(len(rows), 8)
        for k, ln in enumerate(rows):
            with self.subTest(cell=k):
                self.assertEqual(len(ln), 40)
                self.assertEqual(_col_f(ln, 21, 40), float(self.SPREAD[k]))

    def test_the_common_case_is_not_made_noisier(self):
        """A value the shortest round-trip already covers must not grow a tail
        of zeros — the corpus's own 9.683426E-05 stays as it was."""
        from k2rad.writer.sph import _f_mass
        self.assertEqual(_f_mass(9.683426e-05).strip(), "9.683426E-05")


class PropertyIdNamespace(unittest.TestCase):
    """The /PROP id namespace is GLOBAL across property types while LS-DYNA's
    *SECTION_* namespaces are per family, so a *SECTION_SPH and a
    *SECTION_SHELL may legally share an id — and two /PROP cards on one id is
    starter ERROR 79, DUPLICATE ID IN PID DEFINITION."""

    NODES8 = NODES
    OTHER = {
        "SHELL": ("*SECTION_SHELL\n" + _row(5, 2, "", 3) + "\n"
                  + _row(1.0, 1.0, 1.0, 1.0) + "\n",
                  "*ELEMENT_SHELL\n"
                  + f"{1:>8}{9:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n"),
        "SOLID": ("*SECTION_SOLID\n" + _row(5, 1) + "\n",
                  "*ELEMENT_SOLID\n" + f"{1:>8}{9:>8}\n"
                  + "".join(f"{n:>8}" for n in (1, 2, 4, 3, 5, 6, 8, 7))
                  + "\n"),
        "TSHELL": ("*SECTION_TSHELL\n" + _row(5, 2) + "\n",
                   "*ELEMENT_TSHELL\n" + f"{1:>8}{9:>8}"
                   + "".join(f"{n:>8}" for n in (1, 2, 4, 3, 5, 6, 8, 7))
                   + "\n"),
    }

    def _prop_ids(self, starter):
        return [ln.strip() for ln in starter.splitlines()
                if ln.startswith("/PROP/")]

    def test_a_card_of_another_family_on_the_same_id_moves_the_sph_prop(self):
        """The other section need not be REFERENCED to collide: an unreferenced
        *SECTION_SHELL still reaches _make_properties and still emits
        /PROP/SHELL/<secid>."""
        for fam, (secblk, _elem) in self.OTHER.items():
            with self.subTest(family=fam):
                d = ("*KEYWORD\n" + NODES + SPH8
                     + "*PART\nsph\n" + _row(1, 5, 1) + "\n"
                     + sec(secid=5) + secblk + MAT + TERM + "*END\n")
                result, starter = _convert(d)
                ids = self._prop_ids(starter)
                nums = [x.rsplit("/", 1)[-1] for x in ids]
                self.assertEqual(len(nums), len(set(nums)), ids)
                self.assertTrue(_warns(result, "is shared by SPH part(s)"),
                                result.warnings)

    def test_a_section_no_particle_sits_on_is_not_emitted_at_all(self):
        """The wrong-family guard. The other family auto-creates its OWN
        property under the id, so emitting the SPH one too is ERROR 79."""
        for fam, (_secblk, elem) in self.OTHER.items():
            with self.subTest(family=fam):
                d = ("*KEYWORD\n" + NODES + SPH8
                     + "*PART\nsph\n" + _row(1, 1, 1) + "\n" + sec(secid=1)
                     + "*PART\nother\n" + _row(9, 5, 1) + "\n"
                     + sec(secid=5) + elem + MAT + TERM + "*END\n")
                result, starter = _convert(d)
                ids = self._prop_ids(starter)
                nums = [x.rsplit("/", 1)[-1] for x in ids]
                self.assertEqual(len(nums), len(set(nums)), ids)
                self.assertNotIn("/PROP/SPH/5", ids)
                self.assertTrue(
                    _warns(result, "no particle sits on it at all"),
                    result.warnings)

    def test_the_deck_wide_scan_names_a_collision_nothing_else_caught(self):
        """The net under every family's own guard: one pass over the assembled
        starter, so a duplicate no single writer can see is still named."""
        from k2rad.writer.assembly import _warn_duplicate_prop_ids
        state = ConversionState()
        _warn_duplicate_prop_ids(
            state, ["/PROP/SHELL/2", "/PROP/SPH/2", "/PROP/SOLID/9"])
        self.assertEqual(len(state.warnings), 1, state.warnings)
        self.assertIn("PROPERTY ID 2", state.warnings[0])
        self.assertIn("/PROP/SHELL/2", state.warnings[0])
        self.assertIn("/PROP/SPH/2", state.warnings[0])

    def test_the_scan_is_quiet_on_a_healthy_deck(self):
        from k2rad.writer.assembly import _warn_duplicate_prop_ids
        state = ConversionState()
        _warn_duplicate_prop_ids(
            state, ["/PROP/SHELL/2", "/PROP/SPH/3", "/PROP/TYPE20/4"])
        self.assertEqual(state.warnings, [])

    def test_the_scan_is_wired_into_the_assembled_starter(self):
        """The one collision class this branch does NOT close, so it is what
        proves the scan is CALLED: a *SECTION_SOLID and an UNREFERENCED
        *SECTION_SHELL sharing an id. Both properties are emitted — pre-existing
        behaviour, in no way SPH-specific — and before this scan nothing in the
        converter said so."""
        d = ("*KEYWORD\n" + NODES
             + "*ELEMENT_SOLID\n" + f"{1:>8}{9:>8}\n"
             + "".join(f"{n:>8}" for n in (1, 2, 4, 3, 5, 6, 8, 7)) + "\n"
             + "*PART\nsolid\n" + _row(9, 2, 1) + "\n"
             + "*SECTION_SOLID\n" + _row(2, 1) + "\n"
             + "*SECTION_SHELL\n" + _row(2, 2, "", 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n" + MAT + TERM + "*END\n")
        result, starter = _convert(d)
        props = [ln.strip() for ln in starter.splitlines()
                 if ln.startswith("/PROP/")]
        self.assertEqual(sorted(props), ["/PROP/SHELL/2", "/PROP/SOLID/2"],
                         props)
        hits = _warns(result, "PROPERTY ID 2")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 79", hits[0])

    def test_a_healthy_sph_deck_raises_no_duplicate_property_warning(self):
        result, _ = _convert(deck())
        self.assertEqual(_warns(result, "PROPERTY ID"), [])


class ProvisionalScreenIsPerFamily(unittest.TestCase):
    """The provisional-element screen keyed every family into ONE flat set of
    ids. SPH is keyed by its NODE id, and LS-DYNA element ids are per family, so
    any deck with two provisional blocks lost the intersection of their id
    ranges — valid particles deleted for no reason, with the per-block report
    then blaming the SPH block's own node screen, which had passed."""

    def test_a_shell_blocks_element_ids_do_not_delete_particles(self):
        shell = ("*ELEMENT_SHELL_MADEUP\n"
                 + "".join(f"{e:>8}{7:>8}{9001:>8}{9002:>8}{9003:>8}{9004:>8}\n"
                           for e in (1, 2, 3)))
        d = ("*KEYWORD\n" + NODES
             + "*ELEMENT_SPH_MADEUP\n"
             + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE)
             + shell + PART
             + "*PART\nshell\n" + _row(7, 8, 1) + "\n" + sec()
             + "*SECTION_SHELL\n" + _row(8, 2, "", 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n" + MAT + TERM + "*END\n")
        _, starter = _convert(d)
        ids = [_col_i(ln, 1, 10) for ln in _rows(_block(starter, "/SPHCEL/1"))]
        self.assertEqual(ids, [n for n, *_ in LATTICE])

    def test_a_genuinely_undefined_particle_is_still_dropped(self):
        """The control: namespacing must not disarm the screen it namespaces."""
        d = ("*KEYWORD\n" + NODES
             + "*ELEMENT_SPH_MADEUP\n"
             + "".join(_cell(n, 1, MASS) for n, *_ in LATTICE)
             + _cell(4242, 1, MASS)
             + PART + sec() + MAT + TERM + "*END\n")
        _, starter = _convert(d)
        ids = [_col_i(ln, 1, 10) for ln in _rows(_block(starter, "/SPHCEL/1"))]
        self.assertEqual(ids, [n for n, *_ in LATTICE])


class SphMaterialCompatibility(unittest.TestCase):
    """/MAT/LAW44 (COWPER) does NOT declare SPH (``hm_read_mat44.F``), so the
    starter refuses the whole deck with ERROR 3046 the moment a particle sits on
    a *MAT_PLASTIC_KINEMATIC — measured on r14 ``sph/bar-i/bar1.k`` and
    ``sph/bar-ii/bar2.k``, two decks LS-DYNA runs. /MAT/LAW2 IS declared
    (``mat002/hm_read_mat02_jc.F90:383``) and describes the identical curve
    whenever there is no Cowper-Symonds rate term and no EFFECTIVE kinematic
    hardening."""

    @staticmethod
    def _plaskin(mid=1, sigy=290.0, etan=0.0, beta=0.0, src=0.0, srp=0.0,
                 fs=0.0):
        return ("*MAT_PLASTIC_KINEMATIC\n"
                + _row(mid, RHO, 210000.0, 0.3, sigy, etan, beta) + "\n"
                + _row(src, srp, fs, 0.0) + "\n")

    SOLID9 = ("*ELEMENT_SOLID\n" + f"{1:>8}{9:>8}\n"
              + "".join(f"{n:>8}" for n in (1, 2, 4, 3, 5, 6, 8, 7)) + "\n"
              + "*PART\nsolid\n" + _row(9, 9, 1) + "\n"
              + "*SECTION_SOLID\n" + _row(9, 1) + "\n")

    def test_an_sph_only_material_simply_becomes_law2(self):
        result, starter = _convert(deck(mat=self._plaskin()))
        self.assertIn("/MAT/LAW2/1", starter)
        self.assertNotIn("/MAT/LAW44/1", starter)
        self.assertEqual(_warns(result, "ERROR 3046 'ELEMENTS OF TYPE SPH"),
                         [])
        self.assertTrue(_warns(result, "→ /MAT/LAW2 (PLAS_JOHNS) instead"))

    def test_the_bilinear_curve_carries_across_unchanged(self):
        """a = SIGY, b = E*ETAN/(E-ETAN), n = 1 — the same plastic branch LAW44
        would have been given, so the two cards are one material."""
        e, etan, sigy = 210000.0, 1000.0, 290.0
        _, starter = _convert(deck(mat=self._plaskin(sigy=sigy, etan=etan,
                                                     beta=1.0)))
        card = _cards(_block(starter, "/MAT/LAW2/1"))[2]
        self.assertAlmostEqual(_col_f(card, 1, 20), sigy)
        self.assertAlmostEqual(_col_f(card, 21, 40), e * etan / (e - etan),
                               places=6)
        self.assertAlmostEqual(_col_f(card, 41, 60), 1.0)

    def test_a_material_shared_with_a_solid_part_is_CLONED(self):
        """The shape both corpus decks have: MID 1 serves solid parts AND
        particle parts. One /MAT id cannot be two laws, so the SPH parts get a
        second card and are repointed at it — the solid keeps LAW44."""
        d = ("*KEYWORD\n" + NODES + SPH8 + PART + sec() + self.SOLID9
             + self._plaskin() + TERM + "*END\n")
        result, starter = _convert(d)
        self.assertIn("/MAT/LAW44/1", starter)
        clones = _blocks(starter, "/MAT/LAW2/")
        self.assertEqual(len(clones), 1, starter)
        clone_id = int(clones[0][0].rsplit("/", 1)[1])
        self.assertNotEqual(clone_id, 1)
        # the SPH /PART points at the clone, the solid /PART at the original
        self.assertEqual(_col_i(_rows(_block(starter, "/PART/1"))[1], 11, 20),
                         clone_id)
        self.assertEqual(_col_i(_rows(_block(starter, "/PART/9"))[1], 11, 20),
                         1)
        self.assertTrue(_warns(result, "a SECOND /MAT card is written"))
        self.assertEqual(_warns(result, "ERROR 3046 'ELEMENTS OF TYPE SPH"),
                         [])

    def test_a_cowper_symonds_rate_term_refuses_the_reroute(self):
        """LAW2's rate term is Johnson-Cook's LOGARITHMIC form, a different
        function — there is no faithful transcription, so the loud refusal is
        kept rather than a different material written silently."""
        result, starter = _convert(deck(mat=self._plaskin(src=40.0, srp=5.0)))
        self.assertIn("/MAT/LAW44/1", starter)
        self.assertEqual(_blocks(starter, "/MAT/LAW2/"), [])
        self.assertTrue(_warns(result, "ERROR 3046 'ELEMENTS OF TYPE SPH"))

    def test_real_kinematic_hardening_refuses_the_reroute(self):
        result, starter = _convert(deck(
            mat=self._plaskin(etan=1000.0, beta=0.0)))
        self.assertIn("/MAT/LAW44/1", starter)
        self.assertEqual(_blocks(starter, "/MAT/LAW2/"), [])
        self.assertTrue(_warns(result, "ERROR 3046 'ELEMENTS OF TYPE SPH"))

    def test_beta_is_inert_when_there_is_no_hardening_to_split(self):
        """bar1.k's exact shape: BETA=0 (pure kinematic) but ETAN=0, so the
        material is perfectly plastic and the split has nothing to divide."""
        result, starter = _convert(deck(mat=self._plaskin(etan=0.0, beta=0.0)))
        self.assertIn("/MAT/LAW2/1", starter)
        self.assertIn("inert here", _warns(result, "→ /MAT/LAW2")[0])

    def test_a_non_sph_deck_keeps_law44(self):
        """The re-route must be unreachable without particles."""
        d = ("*KEYWORD\n" + NODES + self.SOLID9 + self._plaskin() + TERM
             + "*END\n")
        _, starter = _convert(d)
        self.assertIn("/MAT/LAW44/1", starter)
        self.assertEqual(_blocks(starter, "/MAT/LAW2/"), [])

    def test_law_106_is_in_the_sph_whitelist(self):
        """``mat106/hm_read_mat106.F90:295`` calls INIT_MAT_KEYWORD(...,"SPH").
        It was missing, so a legal LAW106 particle part drew a warning about a
        starter refusal that does not happen."""
        from k2rad.writer.sph import _SPH_COMPATIBLE_LAWS
        self.assertIn(106, _SPH_COMPATIBLE_LAWS)

    def test_the_user_law_slots_are_all_three_or_none(self):
        """29/30/31 are /MAT/USER1..3 — no matNNN directory, so nothing to
        read. Permissive deliberately, and consistently."""
        from k2rad.writer.sph import _SPH_COMPATIBLE_LAWS
        self.assertEqual({29, 30, 31} & _SPH_COMPATIBLE_LAWS, {29, 30, 31})


class ReviewRoundReports(unittest.TestCase):
    """Reports that named the wrong thing."""

    def test_control_sph_losses_are_named_without_any_particles(self):
        """IDIM is the one column whose loss changes the ANSWER, and the deck
        that most needs to hear about it is the one whose *INCLUDE did not
        resolve — where there are no particles to gate the report on."""
        d = ("*KEYWORD\n" + NODES + MAT + TERM
             + "*CONTROL_SPH\n" + _row(1, 0, 1.0e20, 2) + "\n" + "*END\n")
        result, _ = _convert(d)
        hits = _warns(result, "*CONTROL_SPH. Dropped")
        self.assertTrue(hits, result.warnings)
        self.assertIn("IDIM=2", hits[0])
        self.assertIn("changes the ANSWER", hits[0])

    def test_an_explicit_zero_card_two_is_not_reported_as_anisotropic(self):
        """A *SECTION_SPH_ELLIPSE whose card 2 is written out as zeros is
        isotropic BY DEFINITION."""
        zeros = sec(keyword="*SECTION_SPH_ELLIPSE",
                    extra=_row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        result, _ = _convert(deck(section=zeros))
        self.assertEqual(_warns(result, "ANISOTROPIC"), result.warnings and [])

    def test_a_real_anisotropic_card_two_is_still_reported(self):
        real = sec(keyword="*SECTION_SPH_ELLIPSE",
                   extra=_row(1.0, 2.0, 0.5, 0.0, 0.0, 0.0) + "\n")
        result, _ = _convert(deck(section=real))
        self.assertTrue(_warns(result, "ANISOTROPIC"), result.warnings)

    def test_a_blank_mass_with_a_populated_nend_is_a_range_not_a_mass(self):
        """The one fixed-column shape the whitespace split cannot read: three
        tokens whose third is a valid float sitting in the NEND columns."""
        from k2rad.handlers import _parse_sph_cell
        self.assertEqual(_parse_sph_cell(_cell(1, 1, "", 8)), (1, 1, 0.0, 8))
        self.assertEqual(_parse_sph_cell(_cell(1, 1, "", 108)),
                         (1, 1, 0.0, 108))

    def test_a_stated_mass_is_still_a_mass(self):
        from k2rad.handlers import _parse_sph_cell
        self.assertEqual(_parse_sph_cell(_cell(1, 1, 2.0e-3, 8)),
                         (1, 1, 2.0e-3, 8))
        self.assertEqual(_parse_sph_cell("1 1 0.002"), (1, 1, 0.002, 0))


class MoreElementRegistryArms(unittest.TestCase):
    """Arms the first audit added but left untested — each of these fails if its
    arm is removed, which is what the ``ElementRegistryArms`` docstring claims
    for the whole set."""

    def _ids(self, starter, header, pred):
        out = set()
        for b in _blocks(starter, header):
            if not pred(b):
                continue
            for ln in b[2:]:
                if not ln.startswith("#"):
                    out.update(int(t) for t in ln.split())
        return out

    def test_a_part_inertia_covers_its_particles(self):
        """*PART_INERTIA states a CoG and an inertia tensor for a rigid part;
        the node set it is built over has to include the particles or the body
        is anchored to nothing."""
        rigid = ("*MAT_RIGID\n" + _row(1, RHO, 210000.0, 0.3) + "\n"
                 + _row(0.0, 7, 7) + "\n" + _row(0.0, 0.0, 0.0) + "\n")
        inertia = ("*PART_INERTIA\ninertia part\n"
                   + _row(1, 1, 1) + "\n"
                   + _row(5.0, 5.0, 5.0, 1.0) + "\n"
                   + _row(1.0, 0.0, 0.0, 1.0, 0.0, 1.0) + "\n"
                   + _row(0.0, 0.0, 0.0) + "\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + inertia + sec() + rigid + TERM
             + "*END\n")
        _, starter = _convert(d)
        ids = self._ids(starter, "/GRNOD/NODE/",
                        lambda b: b[1].startswith("rb_nodes"))
        self.assertTrue({n for n, *_ in LATTICE} <= ids, sorted(ids))

    def test_a_tied_contacts_secondary_side_reaches_particles(self):
        shell = ("*ELEMENT_SHELL\n"
                 + f"{1:>8}{2:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + shell + PART
             + "*PART\nshell\n" + _row(2, 2, 1) + "\n" + sec()
             + "*SECTION_SHELL\n" + _row(2, 2, "", 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n" + MAT + TERM
             + "*CONTACT_TIED_NODES_TO_SURFACE\n"
             + _row(1, 2, 3, 3) + "\n" + _row(0.0, 0.0) + "\n" + "*END\n")
        _, starter = _convert(d)
        ids = {int(t) for b in _blocks(starter, "/GRNOD/NODE/")
               for ln in b[2:] if not ln.startswith("#")
               for t in ln.split()}
        self.assertTrue({n for n, *_ in LATTICE} <= ids, sorted(ids))

    def test_a_force_transducer_over_a_particle_part_is_not_empty(self):
        """``_part_node_ids`` builds the /INTER/SUB secondary group of a
        *CONTACT_FORCE_TRANSDUCER. Without the arm the group is empty and the
        transducer is dropped for "no deformable nodes"."""
        shell = ("*ELEMENT_SHELL\n"
                 + f"{1:>8}{2:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + shell + PART
             + "*PART\nshell\n" + _row(2, 2, 1) + "\n" + sec()
             + "*SECTION_SHELL\n" + _row(2, 2, "", 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n" + MAT + TERM
             + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
             + _row(1, 2, 3, 3) + "\n" + _row(0.2, 0.2) + "\n"
             + "*CONTACT_FORCE_TRANSDUCER_PENALTY\n"
             + _row(1, 2, 3, 3) + "\n" + _row(0.0, 0.0) + "\n" + "*END\n")
        result, starter = _convert(d)
        self.assertEqual(
            [w for w in result.warnings
             if "secondary side has no" in w], [], result.warnings)
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if b[1].endswith("_secnd")]
        self.assertTrue(grp, starter)
        ids = {int(t) for b in grp for ln in b[2:]
               if not ln.startswith("#") for t in ln.split()}
        self.assertTrue({n for n, *_ in LATTICE} <= ids, sorted(ids))

    #: *MAT_ANISOTROPIC_VISCOPLASTIC (MAT_103) — the material whose parts
    #: _assign_ortho_props splits onto a synthesized /PROP/TYPE6 or TYPE9.
    MAT103 = (
        "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
        "         1   1.05E-9    1800.0       0.4      35.0       0.0"
        "       0.0       1.0\n"
        "      10.0      50.0       5.0     300.0       0.0       0.0"
        "       0.0       0.0\n"
        "       0.0       0.0      1.35       1.0      0.75       0.0"
        "       0.0       0.0\n"
        "       0.0       0.1\n")

    def test_an_orthotropic_material_does_not_claim_a_particle_part(self):
        """/MAT/LAW128 IS on the starter's SPH whitelist, so the pairing is
        legal — but the only property an SPH part may carry is /PROP/SPH
        (else `ERROR 3047`), so the ortho split must SKIP it. Without the skip
        the part falls through to the element-kind ladder and is told its
        particles are not a mesh."""
        result, starter = _convert(deck(mat=self.MAT103))
        props = [ln.strip() for ln in starter.splitlines()
                 if ln.startswith("/PROP/")]
        self.assertEqual(props, ["/PROP/SPH/1"], props)
        self.assertEqual(_col_i(_rows(_block(starter, "/PART/1"))[1], 1, 10), 1)
        self.assertEqual(
            [w for w in result.warnings if "no shell or solid elements" in w],
            [], result.warnings)

    def test_a_composite_material_does_not_claim_a_particle_part(self):
        """Same shape in `_assign_composite_props`. Without the skip the part
        reaches the element-kind ladder and is warned about a mesh that is
        perfectly fine — or, worse, gets a second orthotropic property."""
        comp = ("*MAT_ENHANCED_COMPOSITE_DAMAGE\n"
                + _row(1, RHO, 210000.0, 105000.0, 105000.0,
                       0.3, 0.3, 0.3) + "\n"
                + _row(80000.0, 80000.0, 80000.0, 0.0, 0.0, 0.0, 0.0, 2) + "\n"
                + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                + _row(1000.0, 1000.0, 1000.0, 1000.0, 100.0) + "\n"
                + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        result, starter = _convert(deck(mat=comp))
        props = [ln.strip() for ln in starter.splitlines()
                 if ln.startswith("/PROP/")]
        self.assertEqual(props, ["/PROP/SPH/1"], props)
        self.assertEqual(
            [w for w in result.warnings if "no shell or solid elements" in w],
            [], result.warnings)

    def test_a_composite_layup_does_not_fabricate_a_shell_section(self):
        """`_make_composite_fallback_sections` synthesizes a `SectionShell`
        under the part's SECID for a layup it cannot convert. On an SPH part
        that lands on the SAME id as the /PROP/SPH — two /PROP cards on one id,
        starter ERROR 79."""
        # _IGA_SHELL is a variant with nowhere to put a layup, so it takes the
        # fallback branch — the one that synthesizes a SectionShell.
        layup = ("*PART_COMPOSITE_IGA_SHELL\nsph composite\n"
                 + _row(1, 0, 0, 0, 0, 0) + "\n"
                 + _row(1, 1.0, 0.0, 1) + "\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + layup + sec() + MAT + TERM
             + "*END\n")
        _, starter = _convert(d)
        props = [ln.strip() for ln in starter.splitlines()
                 if ln.startswith("/PROP/")]
        nums = [p.rsplit("/", 1)[-1] for p in props]
        self.assertEqual(len(nums), len(set(nums)), props)
        self.assertIn("/PROP/SPH/1", props)

    def test_a_discrete_beam_section_id_does_not_swallow_a_particle_part(self):
        """_discrete_beam_pids excluded shells and solids but not particles, so
        an SPH part whose SECID matches an ELFORM=6 *SECTION_BEAM was claimed
        as a connector and skipped WHOLE — /PART, /SPHCEL block, `sph_cell_ids`
        registration and any /TH/SPHCEL naming those particles."""
        d = ("*KEYWORD\n" + NODES + SPH8
             + "*PART\nsph part\n" + _row(1, 99, 1) + "\n"
             + sec(secid=99)
             + "*SECTION_BEAM\n" + _row(99, 6) + "\n"
             + _row(0.0, 0.0, 0.0, 0.0) + "\n" + MAT + TERM
             + "*DATABASE_HISTORY_SPH\n" + _row(1, 2) + "\n" + "*END\n")
        _, starter = _convert(d)
        self.assertIn("/PART/1", starter)
        self.assertEqual(len(_rows(_block(starter, "/SPHCEL/1"))), 8)
        self.assertEqual(len(_blocks(starter, "/TH/SPHCEL/")), 1, starter)

    def test_an_inertia_card_never_reuses_a_particle_as_its_main_node(self):
        """`_inertia_element_nodes` is the "is this node element-free?" test for
        an `_INERTIA` main node. ICoG=4 still adds the main node's own nodal
        mass and rotary inertia (`inirby.F:146,166-169`), so reusing a particle
        would add mass `TM` never accounted for — and a main node on an element
        is WARNING 448, or ERROR 1066 under --ams."""
        rigid = ("*MAT_RIGID\n" + _row(1, RHO, 210000.0, 0.3) + "\n"
                 + _row(0.0, 7, 7) + "\n" + _row(0.0, 0.0, 0.0) + "\n")
        # card 3 is XC YC ZC TM IRCS NODEID — NODEID names particle 3
        inertia = ("*PART_INERTIA\ninertia part\n"
                   + _row(1, 1, 1) + "\n"
                   + _row(5.0, 5.0, 5.0, 1.0, 0, 3) + "\n"
                   + _row(1.0, 0.0, 0.0, 1.0, 0.0, 1.0) + "\n"
                   + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + inertia + sec() + rigid + TERM
             + "*END\n")
        result, starter = _convert(d)
        rb = _blocks(starter, "/RBODY/")
        self.assertTrue(rb, starter)
        main = _col_i(_cards(rb[0])[0], 1, 10)
        self.assertNotIn(main, [n for n, *_ in LATTICE], starter)
        self.assertTrue(_warns(result, "is attached to elements"),
                        result.warnings)

    def test_a_cnrb_never_reuses_a_particle_as_its_master(self):
        """Same test, other caller: a CNRB master is moved to the centre of
        gravity, and moving a node that belongs to elements INVERTS them."""
        d = ("*KEYWORD\n" + NODES + SPH8 + PART + sec() + MAT + TERM
             + "*SET_NODE_LIST\n" + _row(100) + "\n"
             + "".join(f"{n:>10}" for n, *_ in LATTICE) + "\n"
             + "*CONSTRAINED_NODAL_RIGID_BODY\n"
             + _row(10, 0, 100, 1) + "\n" + "*END\n")   # PNODE = particle 1
        _, starter = _convert(d)
        rb = _blocks(starter, "/RBODY/")
        self.assertTrue(rb, starter)
        master = _col_i(_cards(rb[0])[0], 1, 10)
        self.assertNotIn(master, [n for n, *_ in LATTICE], starter)

    def test_an_all_parts_self_contact_finds_the_particles(self):
        """`SSID = 0` is an ALL-PARTS self contact, and its secondary side is
        the deck-wide deformable-node set. Without the SPH arm a particle-only
        deck has none, and the whole interface is dropped."""
        d = deck(extra="*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                       + _row(0, 0, 0, 0) + "\n" + _row(0.2, 0.2) + "\n")
        result, starter = _convert(d)
        self.assertEqual(
            [w for w in result.warnings if "no deformable nodes left" in w],
            [], result.warnings)
        self.assertEqual(
            [w for w in result.warnings if "DROPPED" in w and "90001" in w],
            [], result.warnings)
        self.assertTrue(_blocks(starter, "/INTER/TYPE25/"), starter)

    def test_a_particle_part_paces_the_engine_time_step(self):
        """_warn_no_pacing_element reads _part_node_sets as "parts that have
        elements", and that inventory excludes particles for the /XREF callers'
        sake. A particle has a time step of its own (mdtsph.F:132), so a joint
        deck with a deformable cloud must NOT be told every element is rigid."""
        rigid = ("*MAT_RIGID\n" + _row(2, RHO, 210000.0, 0.3) + "\n"
                 + _row(0.0, 7, 7) + "\n" + _row(0.0, 0.0, 0.0) + "\n")
        d = ("*KEYWORD\n" + NODES + SPH8 + PART + sec() + MAT + rigid
             + "*ELEMENT_BEAM\n" + f"{1:>8}{4:>8}{1:>8}{2:>8}{3:>8}\n"
             + "*PART\nrigid\n" + _row(4, 4, 2) + "\n"
             + "*SECTION_BEAM\n" + _row(4, 1) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0, 1.0, 1.0) + "\n"
             + "*CONSTRAINED_JOINT_REVOLUTE\n"
             + _row(1, 2, 3, 4, 5, 6) + "\n" + TERM + "*END\n")
        result, _ = _convert(d)
        self.assertEqual(
            [w for w in result.warnings
             if "every element in this deck belongs to a rigid part" in w],
            [], result.warnings)


if __name__ == "__main__":
    unittest.main()
