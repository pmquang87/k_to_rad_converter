"""``*DATABASE_*`` DT: one parsing policy for the whole family.

The family used to disagree with itself about how wide its own first field
is. Most handlers split free-format first; ``*DATABASE_ELOUT``,
``*DATABASE_GLSTAT`` and ``*DATABASE_BINARY_D3PLOT`` sliced strict
fixed-width ``w=10``. On the same deck the two readings return different
numbers.

Both failure modes are SILENT, which is what makes this worth a test file of
its own rather than a line in the converter tests:

* fixed-width truncates any value wider than 10 columns and ``to_float``
  defaults the wreckage to 0.0 — and ``1.000000E-05`` is 12 characters, i.e.
  simply how a 1e-5 is normally written. The output is requested in the .k
  and then never written, with nothing in the log to say so;
* free-format returns field 2's value when field 1 is legitimately BLANK
  (output driven by LCDT), i.e. it invents an interval the deck never asked
  for.

So neither reading is correct on its own and the fix is a rule, not a
preference. See ``handlers._handle_db_dt``.
"""
import unittest

from k2rad.handlers import _db_fields, _handle_db_dt, _numeric_or_none
from k2rad.parser import Block


class _FakeState:
    """Just enough ConversionState to capture warnings."""

    def __init__(self):
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)


def _block(*lines):
    b = Block.__new__(Block)
    b.raw = list(lines)
    return b


class TestNumericOrNone(unittest.TestCase):
    """The primitive that lets 'unreadable' be told from 'zero'."""

    def test_a_real_zero_is_a_number(self):
        self.assertEqual(_numeric_or_none("0.0"), 0.0)

    def test_an_unreadable_token_is_none_not_zero(self):
        self.assertIsNone(_numeric_or_none("1.000000E-"))

    def test_blank_is_none(self):
        self.assertIsNone(_numeric_or_none("   "))

    def test_fortran_exponent_still_parses(self):
        self.assertAlmostEqual(_numeric_or_none("7.85000-9"), 7.85e-9)


class TestDtParsingRule(unittest.TestCase):
    """The table from the _handle_db_dt docstring, as executable cases."""

    def test_twelve_character_value_is_not_truncated_to_zero(self):
        """THE BUG. '1.000000E-05' is 12 chars; fixed w=10 leaves
        '1.000000E-', which to_float defaults to 0.0 -- so the deck requests
        an output every 10 us and the converter records 'not requested'."""
        self.assertAlmostEqual(_handle_db_dt(_block("1.000000E-05")), 1e-5)

    def test_value_straddling_the_column_boundary(self):
        self.assertAlmostEqual(_handle_db_dt(_block("     1.0E-05")), 1e-5)

    def test_value_inside_ten_columns_is_unchanged(self):
        self.assertAlmostEqual(_handle_db_dt(_block("   1.0E-05")), 1e-5)

    def test_comma_means_free_format(self):
        self.assertAlmostEqual(_handle_db_dt(_block("1.0E-05,0,0")), 1e-5)

    def test_a_blank_dt_stays_zero_and_does_not_borrow_field_two(self):
        """The opposite trap, and the reason 'just use free format' is not
        the fix: DT is genuinely omitted here and LCDT drives the output, so
        the answer is 0.0. A free-format split returns 1e-05."""
        self.assertEqual(_handle_db_dt(_block(" " * 10 + "1.0E-05")), 0.0)

    def test_empty_card_is_zero(self):
        self.assertEqual(_handle_db_dt(_block()), 0.0)

    def test_a_genuine_zero_is_still_zero(self):
        self.assertEqual(_handle_db_dt(_block("       0.0")), 0.0)


class TestUnreadableDtIsWarnedNotSwallowed(unittest.TestCase):
    """'never degrade to a silent zero'."""

    def test_unreadable_dt_warns(self):
        st = _FakeState()
        v = _handle_db_dt(_block("    NOTANUM"), st, "*DATABASE_GLSTAT")
        self.assertEqual(v, 0.0)
        self.assertTrue(st.warnings, "an unreadable DT must be reported")
        self.assertIn("*DATABASE_GLSTAT", st.warnings[0])

    def test_a_readable_dt_does_not_warn(self):
        st = _FakeState()
        _handle_db_dt(_block("1.000000E-05"), st, "*DATABASE_GLSTAT")
        self.assertEqual(st.warnings, [])

    def test_an_omitted_dt_does_not_warn(self):
        """Blank is a legitimate deck statement, not a parse failure."""
        st = _FakeState()
        _handle_db_dt(_block(" " * 10 + "1.0E-05"), st, "*DATABASE_GLSTAT")
        self.assertEqual(st.warnings, [])


class TestFieldsAreReadFromOneReadingOfTheLine(unittest.TestCase):
    """*DATABASE_BINARY_D3PLOT takes DT and NPLTC off the SAME card.

    Reading DT free-format and NPLTC fixed-width off one line is how two
    fields of the same card end up disagreeing about where its columns are.
    """

    def test_d3plot_dt_and_npltc_come_from_the_same_split(self):
        line = "1.000000E-05,0,0,25,0"
        f = _db_fields(line, n=8)
        self.assertAlmostEqual(float(f[0]), 1e-5)
        self.assertEqual(int(f[3]), 25)

    def test_fixed_card_still_reads_positionally(self):
        #        DT        LCDT      BEAM      NPLTC
        line = "     1e-05         0         0        25"
        f = _db_fields(line, n=8)
        self.assertAlmostEqual(float(f[0]), 1e-5)
        self.assertEqual(int(f[3]), 25)


class TestTheWholeFamilyAgrees(unittest.TestCase):
    """The point of the change: no *DATABASE_* handler is an outlier.

    ELOUT/GLSTAT/D3PLOT used to slice fixed-width while the other fourteen
    split free-format. Whatever the rule is, it has to be the same rule --
    two handlers reading the same line differently is the defect.
    """

    LINES = ["1.000000E-05", "     1.0E-05", "   1.0E-05",
             "1.0E-05,0,0", " " * 10 + "1.0E-05", "       0.0"]

    def test_every_dt_site_reads_a_given_line_identically(self):
        from k2rad import handlers as H
        state_free = _FakeState()
        for line in self.LINES:
            want = _handle_db_dt(_block(line), state_free)
            for kw in ("*DATABASE_ELOUT", "*DATABASE_GLSTAT",
                       "*DATABASE_BINARY_D3PLOT", "*DATABASE_MATSUM"):
                got = H._handle_db_dt(_block(line), _FakeState(), kw)
                self.assertEqual(
                    got, want,
                    f"{kw} disagrees with the family on {line!r}: "
                    f"{got} != {want}")


if __name__ == "__main__":
    unittest.main()
