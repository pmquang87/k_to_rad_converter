"""The damping batch: *DAMPING_PART_MASS, *DAMPING_FREQUENCY_RANGE[_DEFORM],
*DAMPING_RELATIVE.

Every convention these three conversions rest on is invisible in the .rad, so
each gets pinned here:

* **Two different version-gate answers, both MEASURED on starter_win64
  (2026-05-20) with twin decks differing only in /BEGIN.**
  ``/DAMP/FREQUENCY_RANGE`` is a radioss2025 keyword: at /BEGIN 2022 the starter
  draws ``WARNING 100211`` and then reads every field correctly (echo identical
  to the 2025 run), so k2rad EMITS it and restates the warning.
  ``/DAMP/VREL`` is a radioss2024 keyword: at /BEGIN 2022 the starter falls back
  to the reduced radioss2023 layout, swallows the ``Freq RbodyID FuncID Xscale``
  card as the ``Alpha_y`` row (echo ``Y 12.5`` for a card that said 0.03) and
  leaves ``Freq`` at 0, which switches the engine to the
  ``alpha = Cdamp/dt_initial`` branch. So k2rad resolves it and WARNS without
  emitting — the ``_resolve_contact_interior`` precedent.
* **The dyna2rad FuncID defect is deliberately NOT reproduced.**
  ``convertdampings.cxx:305`` routes *DAMPING_RELATIVE's curve id through
  ``GetRadiossSetIdFromLsdSet(lcid, "*SET_PART")`` — the part-SET map, with the
  SET entity type — a copy-paste of the ``PSID`` line above it. Both failure
  shapes are pinned below: a curve id that matches no set, and one that
  numerically collides with a part-set id.
* ``/DAMP/FREQUENCY_RANGE`` card 1 carries **two dead 10-column slots** between
  ``Cdamp`` and ``grpart_ID`` and **one more** after it. Column positions are
  asserted, not just field values.
* LS-DYNA ``PSID = 0`` on *DAMPING_FREQUENCY_RANGE means "all parts EXCEPT
  those claimed by other cards" — the OPPOSITE of Radioss ``grpart_ID = 0``,
  which grabs every part and silently re-tags the ones an earlier card took
  (``hm_read_damp.F:299-307`` overwrites). The complement is therefore made
  explicit whenever another card claims anything.
* ``SF`` on *DAMPING_PART_MASS is one of the rare LS-DYNA fields whose default
  is NOT zero (1.0), and the card has no constant-value column at all — the
  damping constant lives entirely on the curve.
* dyna2rad has **no converter for *DAMPING_PART_MASS**; k2rad's is a deliberate
  super-set, not a parity item.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS, _offset_block
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState, Curve, DampingRelative
from k2rad.writer.common import _f, _i
from k2rad.writer.loads import _resolve_damping_relative


def _convert(deck: str):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _dispatch(deck: str) -> ConversionState:
    """Parse + dispatch a deck string into a fresh ConversionState."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _blocks(deck: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    out = list(parse_k_file(path))
    tmp.cleanup()
    return out


def _warns(result, needle: str):
    return [w for w in result.warnings if needle in w]


# Two quad-shell parts (1 and 2), part 1 on nodes 1-4, part 2 on nodes 2,5,6,3
# and 5,7,8,6 — so part 2 owns nodes 2,3,5,6,7,8 and shares 2,3 with part 1.
_MESH = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2            10.0             0.0             0.0\n"
    "       3            10.0            10.0             0.0\n"
    "       4             0.0            10.0             0.0\n"
    "       5            20.0             0.0             0.0\n"
    "       6            20.0            10.0             0.0\n"
    "       7            30.0             0.0             0.0\n"
    "       8            30.0            10.0             0.0\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       2       2       5       6       3\n"
    "       3       2       5       7       8       6\n"
    "*PART\n"
    "damped plate\n"
    "         1         1         1\n"
    "*PART\n"
    "second plate\n"
    "         2         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2       1.0\n"
    "       1.0       1.0       1.0       1.0\n"
    "*MAT_ELASTIC\n"
    "         1 7.860E-09  210000.0       0.3\n"
)

#: A FLAT curve: SF*y is then exact and no "time-varying" warning is due.
_CURVE_FLAT = (
    "*DEFINE_CURVE\n"
    "       201         0     1.000     1.000     0.000     0.000\n"
    "               0.000             200.000\n"
    "        1.000000e-02             200.000\n"
)

#: A RAMPED curve: the constant reduction is lossy and must say so.
_CURVE_RAMP = (
    "*DEFINE_CURVE\n"
    "       202         0     1.000     1.000     0.000     0.000\n"
    "               0.000              50.000\n"
    "        1.000000e-02             150.000\n"
)

#: The same two parts, but NOT conformal — part 1 on nodes 1-4, part 2 on
#: 5-8, no shared node anywhere. The control for the node-overlap warning.
_DISJOINT_MESH = _MESH.replace(
    "       2       2       2       5       6       3\n"
    "       3       2       5       7       8       6\n",
    "       2       2       5       7       8       6\n")

_END = "*CONTROL_TERMINATION\n       0.1\n*END\n"


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / parsing
# ═════════════════════════════════════════════════════════════════════════════

class DampingDispatchTests(unittest.TestCase):
    """None of the three may reach state.skipped_keywords, and every option
    spelling needs its own dispatch key: parser._split_keyword strips only a
    trailing _ID/_TITLE, so *DAMPING_FREQUENCY_RANGE_DEFORM does NOT fall back
    to the base keyword (the #117 *LOAD_BODY_R* defect)."""

    def test_all_three_keywords_are_recognized(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n         1       201       1.0\n"
                + "*DAMPING_FREQUENCY_RANGE\n"
                  "      0.01      30.0     300.0         0\n"
                + "*DAMPING_RELATIVE\n"
                  "      0.03      12.5         1         0       0.0       201\n"
                + _END)
        result, _ = _convert(deck)
        for kw in ("*DAMPING_PART_MASS", "*DAMPING_FREQUENCY_RANGE",
                   "*DAMPING_RELATIVE"):
            self.assertNotIn(kw.lstrip("*"), result.skipped_keywords)
        self.assertEqual([], [k for k in result.skipped_keywords
                              if "DAMPING" in k])

    def test_every_option_spelling_dispatches(self):
        for kw, attr in (
            ("DAMPING_PART_MASS", "damping_part_mass"),
            ("DAMPING_PART_MASS_SET", "damping_part_mass"),
            ("DAMPING_FREQUENCY_RANGE", "damping_frequency_range"),
            ("DAMPING_FREQUENCY_RANGE_DEFORM", "damping_frequency_range"),
            ("DAMPING_FREQUENCY_RANGE_DEFORM_DMIG", "damping_frequency_range"),
            ("DAMPING_RELATIVE", "damping_relative"),
        ):
            with self.subTest(keyword=kw):
                card = ("         1       201       1.0"
                        if "PART_MASS" in kw else
                        "      0.01      30.0     300.0         0"
                        if "FREQUENCY" in kw else
                        "      0.03      12.5         1         0")
                st = _dispatch(f"*KEYWORD\n*{kw}\n{card}\n*END\n")
                self.assertEqual(1, len(getattr(st, attr)), kw)
                self.assertEqual([], st.skipped_keywords, kw)

    def test_title_and_id_suffixes_skip_the_heading_line(self):
        """_TITLE consumes one heading line, _ID consumes the id+title line —
        _title_offset must skip it or field 0 is read out of the title text."""
        for suffix, head in (("_TITLE", "my damping card\n"),
                             ("_ID", "        77 my damping card\n")):
            with self.subTest(suffix=suffix):
                st = _dispatch("*KEYWORD\n"
                               f"*DAMPING_PART_MASS{suffix}\n{head}"
                               "         1       201       1.0\n*END\n")
                self.assertEqual(1, len(st.damping_part_mass))
                self.assertEqual(1, st.damping_part_mass[0].pid)
                self.assertEqual(201, st.damping_part_mass[0].lcid)

                st = _dispatch("*KEYWORD\n"
                               f"*DAMPING_FREQUENCY_RANGE{suffix}\n{head}"
                               "      0.01      30.0     300.0         4\n*END\n")
                self.assertEqual(1, len(st.damping_frequency_range))
                self.assertEqual(4, st.damping_frequency_range[0].psid)


class DampingPartMassParseTests(unittest.TestCase):

    def test_card1_fields(self):
        st = _dispatch("*KEYWORD\n*DAMPING_PART_MASS\n"
                       "         7       201       2.5         0\n*END\n")
        dm = st.damping_part_mass[0]
        self.assertEqual((7, False, 201, 2.5, 0),
                         (dm.pid, dm.is_set, dm.lcid, dm.sf, dm.flag))

    def test_set_spelling_marks_the_id_as_a_part_set(self):
        st = _dispatch("*KEYWORD\n*DAMPING_PART_MASS_SET\n"
                       "         3       201       1.0\n*END\n")
        self.assertTrue(st.damping_part_mass[0].is_set)
        self.assertEqual(3, st.damping_part_mass[0].pid)

    def test_blank_sf_defaults_to_one_not_zero(self):
        """SF's LS-DYNA default is 1.0. to_float("") would give 0.0 and silently
        zero the damping, so the read must go through _ffield."""
        st = _dispatch("*KEYWORD\n*DAMPING_PART_MASS\n"
                       "         1       201\n*END\n")
        self.assertEqual(1.0, st.damping_part_mass[0].sf)

    def test_flag1_consumes_the_scale_factor_card(self):
        st = _dispatch("*KEYWORD\n*DAMPING_PART_MASS\n"
                       "         1       201       1.0         1\n"
                       "       1.0       2.0       3.0       0.5       0.6       0.7\n"
                       "*END\n")
        self.assertEqual(1, len(st.damping_part_mass))
        dm = st.damping_part_mass[0]
        self.assertEqual((1.0, 2.0, 3.0, 0.5, 0.6, 0.7),
                         (dm.stx, dm.sty, dm.stz, dm.srx, dm.sry, dm.srz))

    def test_repeated_card_sets_with_and_without_the_scale_card(self):
        """The FLAG column is what makes the optional second card unambiguous,
        so a mixed run must not desynchronise."""
        st = _dispatch("*KEYWORD\n*DAMPING_PART_MASS\n"
                       "         1       201       1.0         1\n"
                       "       1.0       1.0       1.0       0.0       0.0       0.0\n"
                       "         2       202       3.0         0\n"
                       "         5       203       4.0\n*END\n")
        self.assertEqual([(1, 201, 1.0, 1), (2, 202, 3.0, 0), (5, 203, 4.0, 0)],
                         [(d.pid, d.lcid, d.sf, d.flag)
                          for d in st.damping_part_mass])

    def test_fused_fixed_width_columns_are_sliced_not_split(self):
        """A deck written hard against the column edges free-splits into ONE
        token; the fixed-width fallback has to recover PID and LCID."""
        st = _dispatch("*KEYWORD\n*DAMPING_PART_MASS\n"
                       "  60000000       201\n*END\n")
        self.assertEqual(60000000, st.damping_part_mass[0].pid)
        self.assertEqual(201, st.damping_part_mass[0].lcid)


class DampingFrequencyRangeParseTests(unittest.TestCase):

    def test_all_eight_columns(self):
        # cdamp flow fhigh psid <blank> pidrel iflg icard2
        st = _dispatch("*KEYWORD\n*DAMPING_FREQUENCY_RANGE\n"
                       "      0.01      30.0     300.0         4"
                       "                   9         1         0\n*END\n")
        d = st.damping_frequency_range[0]
        self.assertEqual((0.01, 30.0, 300.0, 4, 9, 1, 0),
                         (d.cdamp, d.flow, d.fhigh, d.psid, d.pidrel,
                          d.iflg, d.icard2))
        self.assertFalse(d.deform)
        self.assertFalse(d.dmig)

    def test_deform_and_dmig_options_are_distinguished(self):
        """dyna2rad cannot tell these apart — data_hierarchy.cfg folds _DEFORM
        into the base subtype as a USER_NAMES alias and
        ConvertDampingFrequencyRange never calls GetKeyword()."""
        card = "      0.01      30.0     300.0         0\n"
        st = _dispatch(f"*KEYWORD\n*DAMPING_FREQUENCY_RANGE_DEFORM\n{card}*END\n")
        self.assertTrue(st.damping_frequency_range[0].deform)
        self.assertFalse(st.damping_frequency_range[0].dmig)
        st = _dispatch("*KEYWORD\n*DAMPING_FREQUENCY_RANGE_DEFORM_DMIG\n"
                       f"{card}*END\n")
        self.assertTrue(st.damping_frequency_range[0].dmig)

    def test_card2_only_read_for_icard2_and_deform(self):
        two = ("      0.05         2\n")
        st = _dispatch("*KEYWORD\n*DAMPING_FREQUENCY_RANGE_DEFORM\n"
                       "      0.01      30.0     300.0         0"
                       "                   0         0         1\n" + two + "*END\n")
        d = st.damping_frequency_range[0]
        self.assertEqual((1, 0.05, 2), (d.icard2, d.cdampv, d.ipwp))

    def test_card2_cdampv_defaults_to_cdamp_and_ipwp_to_one(self):
        st = _dispatch("*KEYWORD\n*DAMPING_FREQUENCY_RANGE_DEFORM\n"
                       "      0.01      30.0     300.0         0"
                       "                   0         0         1\n"
                       "\n*END\n")
        d = st.damping_frequency_range[0]
        self.assertEqual((0.01, 1), (d.cdampv, d.ipwp))

    def test_corpus_card_layout(self):
        """The exact card all three dynaexamples NVH decks carry."""
        st = _dispatch(
            "*KEYWORD\n*DAMPING_FREQUENCY_RANGE\n"
            "$#   cdamp      flow     fhigh      psid         -    pidrel"
            "      iflg    icard2\n"
            "      0.01      30.0     300.0         0"
            "                   0         0         0\n*END\n")
        d = st.damping_frequency_range[0]
        self.assertEqual((0.01, 30.0, 300.0, 0, 0, 0, 0),
                         (d.cdamp, d.flow, d.fhigh, d.psid, d.pidrel,
                          d.iflg, d.icard2))


class DampingRelativeParseTests(unittest.TestCase):

    def test_all_six_columns(self):
        st = _dispatch("*KEYWORD\n*DAMPING_RELATIVE\n"
                       "      0.03      12.5         7         3      0.25"
                       "       201\n*END\n")
        d = st.damping_relative[0]
        self.assertEqual((0.03, 12.5, 7, 3, 0.25, 201),
                         (d.cdamp, d.freq, d.pidrb, d.psid, d.dv2, d.lcid))

    def test_pre_r71_card_without_dv2_and_lcid(self):
        """Keyword971 has only four columns; the missing DV2/LCID read as 0,
        which is what their absence means."""
        st = _dispatch("*KEYWORD\n*DAMPING_RELATIVE\n"
                       "      0.03      12.5         7         3\n*END\n")
        d = st.damping_relative[0]
        self.assertEqual((0.0, 0), (d.dv2, d.lcid))


# ═════════════════════════════════════════════════════════════════════════════
# *DAMPING_PART_MASS -> /DAMP
# ═════════════════════════════════════════════════════════════════════════════

class DampingPartMassEmissionTests(unittest.TestCase):

    def test_format1_card_is_column_exact(self):
        """alpha = SF * curve = 1.0 * 200.0. Beta must be written explicitly as
        0 or the grnod_ID digits land in the Beta field (cols 21-40)."""
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/DAMP/"))
        self.assertEqual("Mass damping *DAMPING_PART_MASS lcid=201 (alpha=200)",
                         lines[i + 1])
        self.assertEqual(
            "#               alpha                beta   grnod_ID   skew_ID"
            "              Tstart               Tstop", lines[i + 2])
        grnod_id = int(lines[i - 4].rsplit("/", 1)[1])
        self.assertEqual(
            f"{_f(200.0)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
            lines[i + 3])
        # column check, radioss110/DAMP/Damp.cfg %20lg%20lg%10d%10d%20lg%20lg
        card = lines[i + 3]
        self.assertEqual("200", card[0:20].strip())
        self.assertEqual("0", card[20:40].strip())
        self.assertEqual(str(grnod_id), card[40:50].strip())
        self.assertEqual("0", card[50:60].strip())
        self.assertEqual("0", card[60:80].strip())
        self.assertEqual("1.000000E+30", card[80:100].strip())
        # Format 1: exactly one value card, then the separator
        self.assertTrue(lines[i + 4].startswith("#---"))

    def test_grnod_holds_only_the_named_parts_nodes(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        g = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/NODE/")
                 and "damping_part_mass" in lines[k + 1])
        self.assertEqual("damping_part_mass_pid_1", lines[g + 1])
        self.assertEqual([1, 2, 3, 4], [int(t) for t in lines[g + 2].split()])

    def test_sf_scales_the_curve_ordinate(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n         1       201       2.5\n" + _END)
        _, starter = _convert(deck)
        # 2.5 * 200.0 = 500.0
        self.assertIn("(alpha=500)", starter)
        self.assertIn(f"{_f(500.0)}{_f(0.0)}", starter)

    def test_format2_per_dof_alphas_are_hand_computed(self):
        """FLAG=1: alpha_i = SF*curve*ST_i = 2.0*200.0*ST_i."""
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n"
                  "         1       201       2.0         1\n"
                  "       1.0       0.5       0.0       0.25      0.1       2.0\n"
                + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/DAMP/"))
        base = 2.0 * 200.0
        expect = [base * s for s in (1.0, 0.5, 0.0, 0.25, 0.1, 2.0)]
        self.assertEqual([400.0, 200.0, 0.0, 100.0, 40.0, 800.0], expect)
        grnod_id = int(lines[i - 4].rsplit("/", 1)[1])
        self.assertEqual(
            f"{_f(400.0)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
            lines[i + 3])
        # Format 2 = five further (Alpha_dir, Beta_dir) cards; their PRESENCE is
        # what sets Mass_Damp_Factor_Option, there is no switch column.
        for k, val in enumerate(expect[1:], start=4):
            self.assertEqual(f"{_f(val)}{_f(0.0)}", lines[i + k])
        self.assertTrue(lines[i + 9].startswith("#---"))

    def test_flag1_with_all_zero_scales_falls_back_to_uniform(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n"
                  "         1       201       1.0         1\n"
                  "       0.0       0.0       0.0       0.0       0.0       0.0\n"
                + _END)
        result, starter = _convert(deck)
        self.assertTrue(_warns(result, "STX..SRZ are all 0.0"))
        # uniform => Format 1, a single value card
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/DAMP/"))
        self.assertIn(_f(200.0), lines[i + 3])
        self.assertTrue(lines[i + 4].startswith("#---"))

    def test_set_scope_resolves_through_part_sets(self):
        deck = (_MESH + _CURVE_FLAT
                + "*SET_PART_LIST\n         3\n         2\n"
                + "*DAMPING_PART_MASS_SET\n         3       201       1.0\n"
                + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        g = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/NODE/")
                 and "damping_part_mass" in lines[k + 1])
        self.assertEqual("damping_part_mass_pset_3", lines[g + 1])
        self.assertEqual([2, 3, 5, 6, 7, 8],
                         [int(t) for t in lines[g + 2].split()])

    def test_set_part_add_is_resolved_too(self):
        """*SET_PART_ADD is flattened into part_sets by the writer pass, which
        is why the PSID must be resolved in the writer and not in the handler."""
        deck = (_MESH + _CURVE_FLAT
                + "*SET_PART_LIST\n         4\n         1\n"
                + "*SET_PART_LIST\n         5\n         2\n"
                + "*SET_PART_ADD\n         6\n         4         5\n"
                + "*DAMPING_PART_MASS_SET\n         6       201       1.0\n"
                + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        g = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/NODE/")
                 and "damping_part_mass" in lines[k + 1])
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8],
                         [int(t) for t in lines[g + 2].split()])

    def test_lcid_zero_is_dropped_with_the_reason(self):
        """The card has NO constant-value column — unlike *DAMPING_GLOBAL's
        VALDMP — so LCID=0 leaves nothing to apply."""
        deck = (_MESH + "*DAMPING_PART_MASS\n         1         0       1.0\n"
                + _END)
        result, starter = _convert(deck)
        self.assertNotIn("PART MASS DAMPING", starter)
        self.assertTrue(_warns(result, "NO constant-value column"))

    def test_missing_curve_is_dropped_not_dangled(self):
        deck = (_MESH + "*DAMPING_PART_MASS\n         1       999       1.0\n"
                + _END)
        result, starter = _convert(deck)
        self.assertNotIn("PART MASS DAMPING", starter)
        self.assertTrue(_warns(result, "load curve 999 is not defined"))

    def test_flat_curve_reduces_without_a_loss_warning(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, _ = _convert(deck)
        self.assertEqual([], _warns(result, "time-VARYING"))

    def test_ramped_curve_warns_and_uses_the_first_ordinate(self):
        deck = (_MESH + _CURVE_RAMP
                + "*DAMPING_PART_MASS\n         1       202       1.0\n" + _END)
        result, starter = _convert(deck)
        w = _warns(result, "time-VARYING")
        self.assertEqual(1, len(w))
        self.assertIn("ordinates 50..150", w[0])
        self.assertIn("(50)", w[0])
        self.assertIn("(alpha=50)", starter)

    def test_curve_scale_factors_are_already_baked_into_the_ordinate(self):
        """*DEFINE_CURVE SFO/OFFO are applied at parse time, so the writer must
        NOT re-apply them: ordinate = (200 + 0)*2 = 400, alpha = 1.5*400."""
        curve = ("*DEFINE_CURVE\n"
                 "       203         0     1.000     2.000     0.000     0.000\n"
                 "               0.000             200.000\n"
                 "        1.000000e-02             200.000\n")
        deck = (_MESH + curve
                + "*DAMPING_PART_MASS\n         1       203       1.5\n" + _END)
        _, starter = _convert(deck)
        self.assertIn("(alpha=600)", starter)

    def test_zero_alpha_emits_nothing(self):
        for sf, lcid, curve, label in (
                ("       0.0", "       201", _CURVE_FLAT, "SF=0"),
                ("       1.0", "       205",
                 "*DEFINE_CURVE\n"
                 "       205         0     1.000     1.000     0.000     0.000\n"
                 "               0.000               0.000\n"
                 "        1.000000e-02             100.000\n", "curve starts 0")):
            with self.subTest(case=label):
                deck = (_MESH + curve + "*DAMPING_PART_MASS\n"
                        f"         1{lcid}{sf}\n" + _END)
                result, starter = _convert(deck)
                self.assertNotIn("PART MASS DAMPING", starter)
                self.assertTrue(_warns(result, "damps nothing"))

    def test_part_without_shell_or_solid_nodes_warns(self):
        deck = (_MESH + _CURVE_FLAT
                + "*PART\nempty\n         9         1         1\n"
                + "*DAMPING_PART_MASS\n         9       201       1.0\n" + _END)
        result, starter = _convert(deck)
        self.assertNotIn("PART MASS DAMPING", starter)
        self.assertTrue(_warns(result, "no deformable shell or solid nodes"))

    def test_unknown_part_is_dropped(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_MASS\n        77       201       1.0\n" + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "part 77 has no *PART card"))

    def test_combination_with_damping_global_is_flagged(self):
        """LS-DYNA forbids it; Radioss would apply both additively."""
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_GLOBAL\n         0       5.0\n"
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "LS-DYNA forbids combining"))

    def test_overlap_with_part_stiffness_warns_about_the_history_buffer(self):
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_STIFFNESS\n         1    1.0E-7\n"
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "ONE per-node damping history buffer"))

    def test_conformal_neighbour_parts_still_overlap_at_the_nodes(self):
        """Part 1 (nodes 1-4) and part 2 (nodes 2,3,5,6,7,8) are DISJOINT as
        part lists but share nodes 2 and 3 along their common edge — which is
        exactly the case a part-id intersection would miss."""
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_STIFFNESS\n         2    1.0E-7\n"
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, _ = _convert(deck)
        w = _warns(result, "ONE per-node damping history buffer")
        self.assertEqual(1, len(w))
        self.assertIn("2 node(s)", w[0])
        self.assertIn("[2, 3]", w[0])

    def test_no_overlap_warning_when_the_meshes_really_are_disjoint(self):
        deck = (_DISJOINT_MESH + _CURVE_FLAT
                + "*DAMPING_PART_STIFFNESS\n         2    1.0E-7\n"
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, _ = _convert(deck)
        self.assertEqual([], _warns(result, "ONE per-node damping history buffer"))

    def test_zero_coef_stiffness_does_not_trigger_the_overlap_warning(self):
        """Only a Beta-bearing /DAMP can corrupt the buffer; alpha-only cards
        overlap harmlessly."""
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_PART_STIFFNESS\n         1       0.0\n"
                + "*DAMPING_PART_MASS\n         1       201       1.0\n" + _END)
        result, _ = _convert(deck)
        self.assertEqual([], _warns(result, "ONE per-node damping history buffer"))


# ═════════════════════════════════════════════════════════════════════════════
# *DAMPING_FREQUENCY_RANGE -> /DAMP/FREQUENCY_RANGE
# ═════════════════════════════════════════════════════════════════════════════

def _freq_card(cdamp="      0.02", flow="      10.0", fhigh="     200.0",
               psid="         0", pidrel="         0", iflg="         0",
               icard2="         0", suffix=""):
    return (f"*DAMPING_FREQUENCY_RANGE{suffix}\n"
            f"{cdamp}{flow}{fhigh}{psid}          {pidrel}{iflg}{icard2}\n")


class DampingFrequencyRangeEmissionTests(unittest.TestCase):

    def test_card_is_column_exact_including_the_dead_slots(self):
        """radioss2025/DAMP/Damp_freq_range.cfg:
        CARD("%20lg%10s%10s%10d%10s%20lg%20lg", Cdamp,_,_,grpart_id,_,Tstart,Tstop)
        — cols 21-40 and 51-60 are dead and MUST be blank."""
        deck = (_MESH + "*SET_PART_LIST\n         3\n         1\n"
                + _freq_card(psid="         3") + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/DAMP/FREQUENCY_RANGE/"))
        grpart_id = int(lines[i - 4].rsplit("/", 1)[1])
        self.assertEqual(
            "Frequency-range damping 0.02 over 10-200 Hz (pset 3)", lines[i + 1])
        self.assertEqual(
            "#              Cdamp                     grpart_ID"
            "                        Tstart               Tstop", lines[i + 2])
        card = lines[i + 3]
        self.assertEqual(
            f"{_f(0.02)}{' ' * 20}{_i(grpart_id)}{' ' * 10}{_f(0.0)}{_f(1.0E30)}",
            card)
        self.assertEqual("0.02", card[0:20].strip())
        self.assertEqual(" " * 20, card[20:40])           # two dead %10s
        self.assertEqual(str(grpart_id), card[40:50].strip())
        self.assertEqual(" " * 10, card[50:60])           # one more dead %10s
        self.assertEqual("0", card[60:80].strip())        # Tstart
        self.assertEqual("1.000000E+30", card[80:100].strip())   # Tstop
        self.assertEqual(100, len(card))
        self.assertEqual("#           Freq_low           Freq_high", lines[i + 4])
        self.assertEqual(f"{_f(10.0)}{_f(200.0)}", lines[i + 5])
        self.assertEqual("10", lines[i + 5][0:20].strip())
        self.assertEqual("200", lines[i + 5][20:40].strip())

    def test_column_header_lines_up_with_the_card(self):
        """The COMMENT string is a contract with the reader's eye, not
        decoration: each label must END on its field's last column."""
        hdr = ("#              Cdamp                     grpart_ID"
               "                        Tstart               Tstop")
        self.assertEqual(100, len(hdr))
        self.assertTrue(hdr[:20].endswith("Cdamp"))
        self.assertTrue(hdr[40:50].endswith("grpart_ID"))
        self.assertTrue(hdr[60:80].endswith("Tstart"))
        self.assertTrue(hdr[80:100].endswith("Tstop"))

    def test_psid_becomes_an_explicit_grpart_part_group(self):
        deck = (_MESH + "*SET_PART_LIST\n         3\n         2\n"
                + _freq_card(psid="         3") + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        g = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRPART/PART/"))
        self.assertEqual("damping_freq_range_pset_3", lines[g + 1])
        self.assertEqual([2], [int(t) for t in lines[g + 2].split()])

    def test_lone_psid_zero_maps_to_grpart_zero(self):
        """With nothing to exclude, Radioss grpart_ID=0 (= all parts,
        hm_read_damp.F:305-307) is the faithful 1:1 — no group needed."""
        deck = _MESH + _freq_card(psid="         0") + _END
        _, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/DAMP/FREQUENCY_RANGE/"))
        self.assertEqual("0", lines[i + 3][40:50].strip())
        self.assertIn("(all parts)", lines[i + 1])
        self.assertNotIn("damping_freq_range_all_other_parts", starter)

    def test_psid_zero_becomes_the_explicit_complement_of_the_other_cards(self):
        """LS-DYNA PSID=0 = "all parts EXCEPT those referred to by other
        *DAMPING_FREQUENCY_RANGE cards" — the OPPOSITE of Radioss grpart_ID=0,
        which would re-tag every part and silently override the other card."""
        deck = (_MESH + "*SET_PART_LIST\n         3\n         1\n"
                + _freq_card(psid="         0")
                + _freq_card(cdamp="      0.05", psid="         3") + _END)
        _, starter = _convert(deck)
        lines = starter.splitlines()
        g = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRPART/PART/")
                 and lines[k + 1] == "damping_freq_range_all_other_parts")
        self.assertEqual([2], [int(t) for t in lines[g + 2].split()])
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/DAMP/FREQUENCY_RANGE/"))
        self.assertIn("(all other parts)", lines[i + 1])
        self.assertNotEqual("0", lines[i + 3][40:50].strip())

    def test_psid_zero_with_everything_claimed_is_dropped(self):
        deck = (_MESH + "*SET_PART_LIST\n         3\n         1         2\n"
                + _freq_card(psid="         0")
                + _freq_card(cdamp="      0.05", psid="         3") + _END)
        result, starter = _convert(deck)
        self.assertTrue(_warns(result, "nothing left to damp"))
        self.assertEqual(1, starter.count("/DAMP/FREQUENCY_RANGE/"))

    def test_two_psid_zero_cards_warn_about_last_one_wins(self):
        deck = (_MESH + _freq_card(psid="         0")
                + _freq_card(cdamp="      0.05", psid="         0") + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "a SECOND *DAMPING_FREQUENCY_RANGE card "
                                       "also has PSID=0"))

    def test_overlapping_part_scopes_warn_about_last_one_wins(self):
        deck = (_MESH
                + "*SET_PART_LIST\n         3\n         1\n"
                + "*SET_PART_LIST\n         4\n         1         2\n"
                + _freq_card(psid="         3")
                + _freq_card(cdamp="      0.05", psid="         4") + _END)
        result, _ = _convert(deck)
        w = _warns(result, "already damped by")
        self.assertEqual(1, len(w))
        self.assertIn("part(s) [1]", w[0])

    def test_flow_and_fhigh_are_validated(self):
        """The starter's FREQ branch checks neither bound; FLOW=0 makes
        f_mid = sqrt(FLOW*FHIGH) = 0 and the 3x3 collocation matrix singular."""
        for flow, fhigh, label in (("       0.0", "     200.0", "FLOW=0"),
                                   ("      -1.0", "     200.0", "FLOW<0"),
                                   ("     200.0", "     200.0", "FHIGH==FLOW"),
                                   ("     200.0", "      10.0", "FHIGH<FLOW")):
            with self.subTest(case=label):
                deck = _MESH + _freq_card(flow=flow, fhigh=fhigh) + _END
                result, starter = _convert(deck)
                self.assertNotIn("/DAMP/FREQUENCY_RANGE/", starter)
                self.assertTrue(_warns(result, "needs 0 < FLOW < FHIGH"))

    def test_zero_cdamp_is_dropped(self):
        deck = _MESH + _freq_card(cdamp="       0.0") + _END
        result, starter = _convert(deck)
        self.assertNotIn("/DAMP/FREQUENCY_RANGE/", starter)
        self.assertTrue(_warns(result, "CDAMP <= 0 damps nothing"))

    def test_version_gate_warning_is_emitted_once(self):
        deck = (_MESH + "*SET_PART_LIST\n         3\n         1\n"
                + "*SET_PART_LIST\n         4\n         2\n"
                + _freq_card(psid="         3")
                + _freq_card(cdamp="      0.05", psid="         4") + _END)
        result, starter = _convert(deck)
        self.assertEqual(2, starter.count("/DAMP/FREQUENCY_RANGE/"))
        w = _warns(result, "WARNING ID : 100211")
        self.assertEqual(1, len(w))
        self.assertIn("in format < 2025", w[0])

    def test_blank_option_warns_about_the_nodal_vs_element_mismatch(self):
        deck = _MESH + _freq_card() + _END
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "this is the BLANK option"))

    def test_deform_option_is_a_clean_match_and_does_not_warn(self):
        """The single Radioss card IS the DEFORM behaviour — damping is applied
        as a Prony viscous stress inside the material law."""
        deck = _MESH + _freq_card(suffix="_DEFORM") + _END
        result, starter = _convert(deck)
        self.assertIn("/DAMP/FREQUENCY_RANGE/", starter)
        self.assertEqual([], _warns(result, "this is the BLANK option"))

    def test_dmig_option_is_dropped(self):
        deck = _MESH + _freq_card(suffix="_DEFORM_DMIG") + _END
        result, starter = _convert(deck)
        self.assertNotIn("/DAMP/FREQUENCY_RANGE/", starter)
        self.assertTrue(_warns(result, "damps a SUPERELEMENT"))

    def test_dmig_psid_is_not_resolved_as_a_part_set(self):
        """On the _DMIG variant PSID is a SUPERELEMENT id, so resolving it
        against *SET_PART would draw a misleading "set is not defined"."""
        deck = _MESH + _freq_card(psid="        42",
                                  suffix="_DEFORM_DMIG") + _END
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "damps a SUPERELEMENT"))
        self.assertEqual([], _warns(result, "*SET_PART 42"))

    def test_a_dropped_card_does_not_shrink_the_psid_zero_complement(self):
        """Validation runs in pass 1, before the union a PSID=0 card subtracts:
        a card that is about to be dropped must not reserve its parts."""
        deck = (_MESH + "*SET_PART_LIST\n         3\n         1\n"
                # this one is dropped (FLOW = 0), so part 1 stays available
                + _freq_card(flow="       0.0", psid="         3")
                + _freq_card(psid="         0") + _END)
        result, starter = _convert(deck)
        self.assertTrue(_warns(result, "needs 0 < FLOW < FHIGH"))
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/DAMP/FREQUENCY_RANGE/"))
        # nothing was validly claimed => plain grpart_ID = 0, not a complement
        self.assertEqual("0", lines[i + 3][40:50].strip())
        self.assertNotIn("damping_freq_range_all_other_parts", starter)

    def test_pidrel_is_dropped_with_a_warning(self):
        deck = _MESH + _freq_card(pidrel="         2") + _END
        result, starter = _convert(deck)
        self.assertIn("/DAMP/FREQUENCY_RANGE/", starter)
        self.assertTrue(_warns(result, "PIDREL=2"))

    def test_iflg_zero_warns_and_iflg_one_does_not(self):
        result, _ = _convert(_MESH + _freq_card(iflg="         0") + _END)
        self.assertTrue(_warns(result, "IFLG=0 selects LS-DYNA's ITERATIVE fit"))
        result, _ = _convert(_MESH + _freq_card(iflg="         1") + _END)
        self.assertEqual([], _warns(result, "IFLG=0 selects"))

    def test_icard2_fields_are_dropped_with_a_warning(self):
        deck = (_MESH
                + "*DAMPING_FREQUENCY_RANGE_DEFORM\n"
                  "      0.02      10.0     200.0         0"
                  "                   0         0         1\n"
                  "      0.05         2\n" + _END)
        result, starter = _convert(deck)
        self.assertIn("/DAMP/FREQUENCY_RANGE/", starter)
        self.assertTrue(_warns(result, "ICARD2=1 supplies CDAMPV=0.05"))

    def test_tstart_tstop_are_the_neutral_pair(self):
        """They are read and echoed but INERT for this damping type: both nodal
        kernels skip it (damping.F:120-127 / DAMPING44) and the material-law
        path has no time argument at all."""
        deck = _MESH + _freq_card() + _END
        _, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/DAMP/FREQUENCY_RANGE/"))
        self.assertEqual("0", lines[i + 3][60:80].strip())
        self.assertEqual("1.000000E+30", lines[i + 3][80:100].strip())


# ═════════════════════════════════════════════════════════════════════════════
# *DAMPING_RELATIVE — resolved, reported, not emitted
# ═════════════════════════════════════════════════════════════════════════════

_RIGID_MESH = _MESH.replace(
    "*MAT_ELASTIC\n         1 7.860E-09  210000.0       0.3\n",
    "*MAT_ELASTIC\n         1 7.860E-09  210000.0       0.3\n"
    "*PART\nrigid block\n         7         2         2\n"
    "*MAT_RIGID\n         2   7.86e-9  210000.0       0.3\n"
    "         0         7         7\n").replace(
    "       3       2       5       7       8       6\n",
    "       3       2       5       7       8       6\n"
    "       4       7       1       2       3       4\n")


class DampingRelativeResolutionTests(unittest.TestCase):

    def test_no_card_is_emitted_and_the_reason_is_logged(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         1         0\n" + _END)
        result, starter = _convert(deck)
        self.assertNotIn("/DAMP/VREL", starter)
        self.assertIn("*DAMPING_RELATIVE",
                      [kw for kw, _ in result.recognized_not_emitted])
        self.assertTrue(_warns(result, "NOT EMITTED"))

    def test_the_warning_states_the_measured_2022_misread(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         1         0\n" + _END)
        result, _ = _convert(deck)
        w = _warns(result, "NOT EMITTED")[0]
        self.assertIn("radioss2024", w)
        self.assertIn("Freq lost to 0", w)
        self.assertIn("Alpha_y", w)

    # ── the two dyna2rad FuncID-bug shapes ────────────────────────────────────

    def test_funcid_when_the_curve_id_matches_no_set(self):
        """Shape 1 of convertdampings.cxx:305. dyna2rad gets this one right by
        accident (setsMappingDetails[LCID] is empty, so the guard size()>1
        fails and the id passes through); k2rad must get it right on purpose."""
        deck = (_MESH + _CURVE_FLAT
                + "*SET_PART_LIST\n        11\n         1\n"
                + "*DAMPING_RELATIVE\n"
                  "      0.03      12.5         1        11       0.0"
                  "       201\n" + _END)
        result, _ = _convert(deck)
        w = _warns(result, "NOT EMITTED")[0]
        self.assertIn("FuncID=201 (from LCID=201", w)
        self.assertIn("*DEFINE_CURVE -> /FUNCT table", w)

    def test_funcid_when_the_curve_id_collides_with_a_part_set_id(self):
        """Shape 2, the one that actually bites dyna2rad: the curve id is ALSO
        a *SET_PART id. Routing it through the part-set map yields that set's
        (possibly renumbered) id in a /FUNCT slot — the wrong curve, or none at
        all and starter ERROR 3049. k2rad resolves LCID against state.curves
        only, so the two id spaces cannot cross."""
        curve = _CURVE_FLAT.replace("       201  ", "         3  ")
        self.assertIn("\n         3         0", curve)   # the renumber landed
        deck = (_MESH + curve
                # *SET_PART 3 has the SAME number as the curve
                + "*SET_PART_LIST\n         3\n         2\n"
                + "*DAMPING_RELATIVE\n"
                  "      0.03      12.5         1         3       0.0"
                  "         3\n" + _END)
        result, starter = _convert(deck)
        w = _warns(result, "NOT EMITTED")[0]
        # The curve, not the part set, and certainly not a renumbered set id.
        self.assertIn("FuncID=3 (from LCID=3", w)
        self.assertIn("*SET_PART 3 -> parts [2]", w)
        # and the curve really is emitted as /FUNCT/3, so the reference resolves
        self.assertIn("/FUNCT/3", starter)

    def test_curve_id_reaching_a_table_slot_is_refused(self):
        """A curve a material consumes through a TABLE slot is re-emitted as
        /TABLE/1/<id> instead of /FUNCT/<id> (state.table_1d_ids — the LAW52 /
        LAW76 mechanism), so a FuncID naming it would dangle: starter
        ERROR 3049. Driven directly, because which material routes a curve into
        a TABLE slot is a materials-side detail this guard must not depend on."""
        state = ConversionState()
        state.curves[204] = Curve(204, "", 1.0, 1.0, 0.0, 0.0,
                                  [(0.0, 250.0), (0.1, 300.0)])
        state.table_1d_ids.add(204)
        state.damping_relative.append(
            DampingRelative(cdamp=0.03, freq=12.5, pidrb=0, psid=0, lcid=204))
        self.assertEqual([], _resolve_damping_relative(state, {}))
        joined = "\n".join(state.warnings)
        self.assertIn("consumed by a material through a TABLE", joined)
        self.assertIn("/TABLE/1/204", joined)
        self.assertIn("FuncID=0 (from LCID=204",
                      [w for w in state.warnings if "NOT EMITTED" in w][0])

    def test_curve_not_in_a_table_slot_resolves_to_funct(self):
        """The control for the test above: same curve, not table-routed."""
        state = ConversionState()
        state.curves[204] = Curve(204, "", 1.0, 1.0, 0.0, 0.0,
                                  [(0.0, 250.0), (0.1, 300.0)])
        state.damping_relative.append(
            DampingRelative(cdamp=0.03, freq=12.5, pidrb=0, psid=0, lcid=204))
        _resolve_damping_relative(state, {})
        self.assertIn("FuncID=204 (from LCID=204",
                      [w for w in state.warnings if "NOT EMITTED" in w][0])

    def test_unknown_curve_is_refused_rather_than_dangled(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         1         0       0.0"
                        "       999\n" + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "has no *DEFINE_CURVE in this deck"))
        self.assertIn("FuncID=0 (from LCID=999", _warns(result, "NOT EMITTED")[0])

    # ── CDAMP vs LCID: Radioss MULTIPLIES where LS-DYNA REPLACES ──────────────

    def test_alpha_is_one_when_a_curve_is_present(self):
        """LS-DYNA: "CDAMP will be ignored if LCID is non-zero". Radioss:
        damp_a = fact*Alpha_x*4*pi*freq — the curve MULTIPLIES. Copying CDAMP
        into Alpha_x alongside a FuncID would double-count."""
        deck = (_MESH + _CURVE_FLAT
                + "*DAMPING_RELATIVE\n"
                  "      0.03      12.5         1         0       0.0"
                  "       201\n" + _END)
        result, _ = _convert(deck)
        self.assertIn("Alpha_x=Alpha_y=Alpha_z=1,",
                      _warns(result, "NOT EMITTED")[0])

    def test_alpha_is_cdamp_when_no_curve_is_given(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         1         0\n" + _END)
        result, _ = _convert(deck)
        self.assertIn("Alpha_x=Alpha_y=Alpha_z=0.03,",
                      _warns(result, "NOT EMITTED")[0])

    # ── PIDRB -> /RBODY ───────────────────────────────────────────────────────

    def test_pidrb_resolves_to_the_emitted_rbody_id(self):
        """The /RBODY id k2rad emits is the main NODE id (writer/rbody.py:624),
        which is what hm_read_damp.F:236-239 wants in RbodyID."""
        deck = (_RIGID_MESH + "*DAMPING_RELATIVE\n"
                              "      0.03      12.5         7         0\n" + _END)
        result, starter = _convert(deck)
        w = _warns(result, "NOT EMITTED")[0]
        rbody_ids = [int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                     if ln.startswith("/RBODY/")]
        self.assertEqual(1, len(rbody_ids))
        self.assertIn(f"RbodyID={rbody_ids[0]} (from PIDRB=7)", w)
        self.assertNotIn("RbodyID=0 ", w)

    def test_non_rigid_pidrb_is_named_loudly(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         2         0\n" + _END)
        result, _ = _convert(deck)
        w = _warns(result, "PIDRB=2 is not a rigid body")
        self.assertEqual(1, len(w))
        self.assertIn("no /RBODY for the relative-velocity reference", w[0])

    def test_pidrb_zero_is_named_loudly(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         0         0\n" + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "PIDRB is 0"))

    def test_dv2_without_a_rigid_body_is_zeroed_and_warned(self):
        """DAMPR(22:24) is read only by damping_vref_rby.F90, inside
        `if (id_rby > 0)` — the grnod path never touches it."""
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         0         0      0.25\n"
                + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "only applied by Radioss on the "
                                       "rigid-body path"))
        self.assertIn("Alpha2_x=0,", _warns(result, "NOT EMITTED")[0])

    def test_dv2_with_a_rigid_body_is_carried(self):
        deck = (_RIGID_MESH + "*DAMPING_RELATIVE\n"
                              "      0.03      12.5         7         0"
                              "      0.25\n" + _END)
        result, _ = _convert(deck)
        self.assertEqual([], _warns(result, "only applied by Radioss on the "
                                            "rigid-body path"))
        self.assertIn("Alpha2_x=0.25,", _warns(result, "NOT EMITTED")[0])

    def test_zero_freq_is_called_out(self):
        """Altair's card documents the Freq=0 branch as a multiplication by dt;
        the shipped engine divides by the INITIAL dt — ~1e12 apart."""
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03       0.0         1         0\n" + _END)
        result, _ = _convert(deck)
        self.assertTrue(_warns(result, "FREQ is 0"))

    def test_nonzero_freq_does_not_draw_that_warning(self):
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         1         0\n" + _END)
        result, _ = _convert(deck)
        self.assertEqual([], _warns(result, "FREQ is 0"))

    def test_xscale_is_called_out_as_dead(self):
        """The starter reads Xscale into DAMPR(27) and no engine file reads that
        slot back — abscissa scaling must be baked into the curve."""
        deck = (_MESH + "*DAMPING_RELATIVE\n"
                        "      0.03      12.5         1         0\n" + _END)
        result, _ = _convert(deck)
        self.assertIn("Xscale must stay 1.0", _warns(result, "NOT EMITTED")[0])


# ═════════════════════════════════════════════════════════════════════════════
# *INCLUDE_TRANSFORM id offsets
# ═════════════════════════════════════════════════════════════════════════════

class DampingOffsetSpecTests(unittest.TestCase):
    """A keyword missing from _OFFSET_SPECS is not silent-but-safe — it draws
    the "id offsets are NOT applied" warning and its references dangle."""

    OFFSETS = {"n": 0, "e": 0, "p": 1000, "m": 0, "s": 2000, "f": 3000,
               "d": 0, "r": 0}

    def _apply(self, deck_block: str):
        kw = deck_block.split("\n", 1)[0].lstrip("*")
        block = next(b for b in _blocks("*KEYWORD\n" + deck_block + "*END\n")
                     if b.keyword == kw)
        _offset_block(block, _OFFSET_SPECS[kw], self.OFFSETS, lambda m: None)
        return block.raw

    def test_every_new_keyword_has_a_spec(self):
        for kw in ("DAMPING_PART_MASS", "DAMPING_PART_MASS_SET",
                   "DAMPING_FREQUENCY_RANGE",
                   "DAMPING_FREQUENCY_RANGE_DEFORM",
                   "DAMPING_FREQUENCY_RANGE_DEFORM_DMIG",
                   "DAMPING_RELATIVE"):
            with self.subTest(keyword=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_part_mass_offsets_pid_and_lcid(self):
        raw = self._apply("*DAMPING_PART_MASS\n"
                          "         1       201       1.0\n")
        self.assertEqual([1001, 3201], [int(t) for t in raw[0].split()[:2]])

    def test_part_mass_set_offsets_the_psid_with_the_set_bucket(self):
        raw = self._apply("*DAMPING_PART_MASS_SET\n"
                          "         3       201       1.0\n")
        self.assertEqual([2003, 3201], [int(t) for t in raw[0].split()[:2]])

    def test_the_scale_factor_card_is_stepped_over(self):
        """to_int() goes through float, so a scale factor of 1.5 reads back as
        the id 1 and a flat "data" spec would rewrite it to 1 + IDPOFF."""
        raw = self._apply("*DAMPING_PART_MASS\n"
                          "         1       201       1.0         1\n"
                          "       1.5       2.0       0.0       0.0       0.0       0.0\n")
        self.assertEqual([1001, 3201], [int(t) for t in raw[0].split()[:2]])
        self.assertEqual([1.5, 2.0, 0.0, 0.0, 0.0, 0.0],
                         [float(t) for t in raw[1].split()])

    def test_repeated_part_mass_sets_all_get_offset(self):
        raw = self._apply("*DAMPING_PART_MASS\n"
                          "         1       201       1.0         1\n"
                          "       1.5       0.0       0.0       0.0       0.0       0.0\n"
                          "         2       202       1.0         0\n")
        self.assertEqual(1001, int(raw[0].split()[0]))
        self.assertEqual(1.5, float(raw[1].split()[0]))
        self.assertEqual([1002, 3202], [int(t) for t in raw[2].split()[:2]])

    def test_frequency_range_offsets_psid_and_pidrel(self):
        raw = self._apply("*DAMPING_FREQUENCY_RANGE\n"
                          "      0.01      30.0     300.0         4"
                          "                   9         0         0\n")
        f = raw[0].split()
        self.assertEqual(0.01, float(f[0]))
        self.assertEqual(2004, int(f[3]))     # PSID via IDSOFF
        self.assertEqual(1009, int(f[4]))     # PIDREL via IDPOFF

    def test_deform_spelling_offsets_the_psid(self):
        raw = self._apply("*DAMPING_FREQUENCY_RANGE_DEFORM\n"
                          "      0.01      30.0     300.0         4\n")
        self.assertEqual(2004, int(raw[0].split()[3]))

    def test_relative_offsets_pidrb_psid_and_lcid(self):
        raw = self._apply("*DAMPING_RELATIVE\n"
                          "      0.03      12.5         7         3       0.0"
                          "       201\n")
        f = raw[0].split()
        self.assertEqual(1007, int(f[2]))     # PIDRB via IDPOFF
        self.assertEqual(2003, int(f[3]))     # PSID  via IDSOFF
        self.assertEqual(3201, int(f[5]))     # LCID  via IDFOFF

    def test_offsets_land_end_to_end_through_a_real_include(self):
        """The unit tests above call _offset_block directly. This one drives the
        whole parse -> _apply_offsets -> dispatch path, so it also proves
        _OFFSET_SPECS is reached for each keyword and that no
        "id offsets are NOT applied" warning is drawn."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        with open(os.path.join(d, "child.k"), "w") as fh:
            fh.write("*KEYWORD\n"
                     "*DAMPING_PART_MASS\n"
                     "         1       201       1.0         1\n"
                     "       1.5       0.0       0.0       0.0       0.0"
                     "       0.0\n"
                     "*DAMPING_FREQUENCY_RANGE\n"
                     "      0.01      30.0     300.0         4"
                     "                   9         0         0\n"
                     "*DAMPING_RELATIVE\n"
                     "      0.03      12.5         7         3       0.0"
                     "       201\n"
                     "*END\n")
        main = os.path.join(d, "main.k")
        with open(main, "w") as fh:
            # card 2 = IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     "         0         0      1000         0      2000"
                     "      3000\n         0         0\n*END\n")
        state = ConversionState()
        for block in parse_k_file(main):
            dispatch(block, state)

        dm = state.damping_part_mass[0]
        self.assertEqual((1001, 3201), (dm.pid, dm.lcid))
        self.assertEqual(1.5, dm.stx)         # a scale factor, NOT an id
        dfr = state.damping_frequency_range[0]
        self.assertEqual((2004, 1009), (dfr.psid, dfr.pidrel))
        self.assertEqual((0.01, 30.0, 300.0), (dfr.cdamp, dfr.flow, dfr.fhigh))
        dr = state.damping_relative[0]
        self.assertEqual((1007, 2003, 3201), (dr.pidrb, dr.psid, dr.lcid))
        self.assertEqual([], [w for w in state.warnings
                              if "offsets are NOT applied" in w])


# ═════════════════════════════════════════════════════════════════════════════
# Non-regression
# ═════════════════════════════════════════════════════════════════════════════

class DampingBatchNonRegressionTests(unittest.TestCase):

    def test_deck_without_the_new_keywords_emits_nothing_new(self):
        result, starter = _convert(_MESH + _END)
        for marker in ("/DAMP", "PART MASS DAMPING", "FREQUENCY-RANGE DAMPING",
                       "/GRPART/PART/"):
            self.assertNotIn(marker, starter)
        self.assertEqual([], [w for w in result.warnings if "DAMPING" in w])

    def test_the_new_sections_draw_no_ids_when_idle(self):
        """The three builders must return [] BEFORE touching state.next_id(),
        or adding them would shift every auto id on every existing deck."""
        base = _MESH + "*DAMPING_GLOBAL\n         0       5.0\n" + _END
        _, starter = _convert(base)
        damp_ids = [ln for ln in starter.splitlines() if ln.startswith("/DAMP/")]
        self.assertEqual(1, len(damp_ids))
        # the /GRNOD + /DAMP pair takes the first two auto ids, exactly as
        # before this batch existed
        self.assertIn("/GRNOD/NODE/90001", starter)
        self.assertEqual("/DAMP/90002", damp_ids[0])

    def test_all_zero_part_stiffness_without_a_global_card_does_not_crash(self):
        """Pre-existing crash surfaced by this batch and fixed with it: a
        *DAMPING_PART_STIFFNESS whose every COEF is 0.0 clears _make_damping's
        early return but leaves beta at 0, so the Format-1 branch read
        state.damping_global.stx on a None — AttributeError, aborting the WHOLE
        conversion rather than just the card. Verified against master 62a53e8,
        where the same deck raises."""
        deck = (_MESH + "*DAMPING_PART_STIFFNESS\n         1       0.0\n"
                + _END)
        _, starter = _convert(deck)          # must not raise
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/DAMP/"))
        self.assertEqual("Rayleigh mass damping (alpha=0)", lines[i + 1])
        self.assertEqual(f"{_f(0.0)}{_f(0.0)}{_i(90001)}{_i(0)}"
                         f"{_f(0.0)}{_f(1.0E30)}", lines[i + 3])

    def test_existing_damping_global_path_is_untouched(self):
        deck = _MESH + "*DAMPING_GLOBAL\n         0     500.0\n" + _END
        _, starter = _convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/DAMP/"))
        self.assertEqual("Rayleigh mass damping (alpha=500)", lines[i + 1])
        self.assertEqual(f"{_f(500.0)}{_f(0.0)}{_i(90001)}{_i(0)}"
                         f"{_f(0.0)}{_f(1.0E30)}", lines[i + 3])


if __name__ == "__main__":
    unittest.main()
