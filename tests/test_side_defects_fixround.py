"""Follow-up fix round of the SIDE-DEFECT batch (PR #132, post-review).

One blocker, one major and six minors found by re-verifying the review round's
own fixes against the LS-DYNA manual, the OpenRadioss starter/engine source
and twin measurements. Each test carries the measurement that settles it.

  * The batch's ``*PARAMETER_LOCAL`` scoping fix never reached
    ``assembly.finalize`` — which runs AFTER the LOCAL frames are popped — so
    a ``&localname`` in an ``*INCLUDE_TRANSFORM`` child was un-offset (an id)
    or overwritten with a literal 0 (a coordinate).
  * A ``*NODE`` id welded to a negative first coordinate was read as node 0,
    losing the node and minting a phantom — 58 303 rows across 188 corpus
    files, at zero warnings (pre-existing).
  * ``paramexpr.power()`` recursed without ``_enter()``, so the depth cap the
    batch added did not cover a ``**`` chain and a ``RecursionError`` still
    escaped.
  * ``*PARAMETER_DUPLICATION`` quoted p.36-6 Remark 2 and did not apply it.
  * ``*DAMPING_GLOBAL``'s STX..SRZ were dropped on both /DAMP branches.
  * p.16-50's RADIUS exemption covers five cells; three were exempted.
  * The bare-``*EOS_*`` refusals printed the RADIOSS spelling of the keyword.
  * 24 ``/GRNOD`` emitters still drew from the unguarded allocator.
  * ``*INITIAL_STRESS_SHELL`` records at different ``nb_integr`` in one deck
    are consumed against ONE global offset (named, not fixed — pre-existing).
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                            # noqa: E402
from k2rad import parser as _parser                  # noqa: E402
from k2rad import paramexpr as _paramexpr            # noqa: E402
from k2rad.parser import parse_k_file                # noqa: E402


# ── harness ──────────────────────────────────────────────────────────────────

def _row(*vals) -> str:
    out = "".join(f"{v:>10}" for v in vals)
    assert len(out) == 10 * len(vals), f"field overflow in {out!r}"
    return out


def _node16(nid: int, x: float, y: float, z: float) -> str:
    return f"{nid:>8}{x:>16.9G}{y:>16.9G}{z:>16.9G}"


def _node_param(nid: int, x: str, y: str, z: str) -> str:
    """A *NODE row whose coordinate cells hold ``&name`` references."""
    return f"{nid:>8}{x:>16}{y:>16}{z:>16}"


def _i8(*vals) -> str:
    return "".join(f"{v:>8}" for v in vals)


def _convert_files(files: dict, main: str = "main.k", **kw):
    tmp = tempfile.TemporaryDirectory()
    for name, text in files.items():
        with open(os.path.join(tmp.name, name), "w") as fh:
            fh.write(text)
    result = convert(os.path.join(tmp.name, main), write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _convert(deck: str, **kw):
    return _convert_files({"main.k": deck}, **kw)


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _node_xyz(starter: str, nid: int):
    """The (x, y, z) of *nid* as the emitted /NODE block states it."""
    lines = starter.splitlines()
    i = lines.index("/NODE")
    for ln in lines[i + 1:]:
        if ln.startswith("/"):
            break
        if ln.startswith("#") or not ln.strip():
            continue
        if int(ln[0:10]) == nid:
            return (float(ln[10:30]), float(ln[30:50]), float(ln[50:70]))
    return None


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER — the LOCAL scope has to reach the *INCLUDE_TRANSFORM walks
# ─────────────────────────────────────────────────────────────────────────────

_PARENT_MESH = "\n".join([
    "*PART", "parent plate", _row(7, 7, 7),
    "*SECTION_SHELL", _row(7, 2, "1.0"), _row("1.0", "1.0", "1.0", "1.0"),
    "*MAT_ELASTIC", _row(7, "7.8E-9", "210000.0", "0.3"),
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    "*ELEMENT_SHELL", _i8(1, 7, 1, 2, 3, 4), ""])


def _parent(child_name: str, tranid: int = 0) -> str:
    """A deck whose *INCLUDE_TRANSFORM offsets nodes/elements/parts/sections."""
    out = ["*KEYWORD", _PARENT_MESH.rstrip("\n")]
    if tranid:
        out += ["*DEFINE_TRANSFORMATION", _row(tranid),
                "TRANSL    " + _row("0.0", "0.0", "100.0")]
    out += ["*INCLUDE_TRANSFORM", child_name,
            # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF IDDOFF
            _row(6000, 7000, 8000, 0, 9000, 0, 0),
            _row(0),                                   # IDROFF
            _row("1.0", "1.0", "1.0", "1.0", 0),       # FCTMAS.. INCOUT1
            _row(tranid),                              # TRANID
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]
    return "\n".join(out)


def _child_ids(local: bool) -> str:
    kw = "*PARAMETER_LOCAL" if local else "*PARAMETER"
    return "\n".join([
        "*KEYWORD", kw, f"{'Ipid':<10}{7:>10}",
        "*PART", "child plate", _row("&pid", "&pid", 7),
        "*SECTION_SHELL", _row("&pid", 2, "2.5"),
        _row("2.5", "2.5", "2.5", "2.5"),
        "*NODE",
        _node16(1, 20.0, 0.0, 0.0), _node16(2, 30.0, 0.0, 0.0),
        _node16(3, 30.0, 10.0, 0.0), _node16(4, 20.0, 10.0, 0.0),
        "*ELEMENT_SHELL", _i8(1, "&pid", 1, 2, 3, 4), "*END", ""])


def _child_coords(local: bool) -> str:
    kw = "*PARAMETER_LOCAL" if local else "*PARAMETER"
    return "\n".join([
        "*KEYWORD", kw, f"{'Rxc':<10}{'25.0':>10}",
        "*PART", "child plate", _row(8, 8, 7),
        "*SECTION_SHELL", _row(8, 2, "2.5"),
        _row("2.5", "2.5", "2.5", "2.5"),
        "*NODE",
        _node_param(11, "&xc", "0.0", "0.0"), _node16(12, 35.0, 0.0, 0.0),
        _node16(13, 35.0, 10.0, 0.0), _node_param(14, "&xc", "10.0", "0.0"),
        "*ELEMENT_SHELL", _i8(11, 8, 11, 12, 13, 14), "*END", ""])


class TestParameterLocalReachesTheAssemblyWalks(unittest.TestCase):
    """``assembly.finalize`` re-reads every included Block's raw lines, and it
    runs from ``parse_k_file`` AFTER ``_pop_local_scope()`` — an inner
    include's frame is popped even earlier, by its own recursive parse. So the
    ``Block.scope`` machinery the batch installed in ``handlers.dispatch`` did
    not cover the ``*INCLUDE_TRANSFORM`` offset walk or the TRANID geometry
    rewrite, and ``to_int("&pid")`` returned 0 there.

    MEASURED on the id twin below, against master (which has no LOCAL scoping
    at all, so the binding was still in ``_PARAMS`` at finalize time):

        master   /PART/7 AND /PART/8007 + /SHELL/8007
        branch   /PART/7 only, titled "child plate" — the child's part
                 REPLACED the parent's, its element was dropped under
                 "MESH LOSS: ... PID 8007 (1 shell)", and the log carried a
                 FALSE "*PARAMETER reference '&pid' is undefined — field
                 treated as blank (0)".

    The coordinate twin is worse, because ``_rewrite_node_blocks`` REWRITES
    what it read: node 6011's X came out as a literal ``0`` instead of 25.

    Both twins use ``*PARAMETER`` as the control — the deck is otherwise
    byte-identical, so any difference is the LOCAL scope and nothing else.
    """

    def test_a_LOCAL_id_is_offset_like_a_global_one(self):
        res, starter = _convert_files({"main.k": _parent("child.k"),
                                       "child.k": _child_ids(local=True)})
        self.assertEqual(_headers(starter, "/PART/"), ["/PART/7", "/PART/8007"])
        self.assertIn("/SHELL/8007", _headers(starter, "/SHELL/"))
        self.assertEqual(_warns(res, "'&pid' is undefined"), [])
        self.assertEqual(_warns(res, "MESH LOSS"), [])

    def test_the_global_control_gives_the_same_deck(self):
        """The discriminator: only the keyword spelling differs, so the two
        emitted decks must agree on every id."""
        _res_l, loc = _convert_files({"main.k": _parent("child.k"),
                                      "child.k": _child_ids(local=True)})
        _res_g, glo = _convert_files({"main.k": _parent("child.k"),
                                      "child.k": _child_ids(local=False)})
        for prefix in ("/PART/", "/SHELL/", "/PROP/SHELL/"):
            self.assertEqual(_headers(loc, prefix), _headers(glo, prefix))

    def test_a_LOCAL_coordinate_survives_the_TRANID_rewrite(self):
        """``&xc = 25.0`` under a +100 Z translation: the node must land at
        (25, 0, 100), not at (0, 0, 100)."""
        _res, starter = _convert_files(
            {"main.k": _parent("child.k", tranid=5),
             "child.k": _child_coords(local=True)})
        self.assertEqual(_node_xyz(starter, 6011), (25.0, 0.0, 100.0))
        self.assertEqual(_node_xyz(starter, 6014), (25.0, 10.0, 100.0))

    def test_the_global_coordinate_control_matches(self):
        _res_l, loc = _convert_files(
            {"main.k": _parent("child.k", tranid=5),
             "child.k": _child_coords(local=True)})
        _res_g, glo = _convert_files(
            {"main.k": _parent("child.k", tranid=5),
             "child.k": _child_coords(local=False)})
        for nid in (6011, 6012, 6013, 6014):
            self.assertEqual(_node_xyz(loc, nid), _node_xyz(glo, nid))


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — the depth cap has to cover the ** chain too
# ─────────────────────────────────────────────────────────────────────────────

class TestParamExprPowerDepthCap(unittest.TestCase):
    """``_enter`` was called from ``expr`` and ``signed`` only. ``power`` is
    RIGHT-associative and recurses into ``self.power()`` for the exponent
    without entering, so ``self.depth`` returned to its entry value at every
    ``**`` and the counter stayed at ~1 no matter how long the chain got.

    MEASURED on the clean tree before the fix: ``evaluate("1" + "**1"*1000)``
    raised ``RecursionError``, not ``ExprError`` — the exact escape the cap
    exists to prevent, and one that kills the whole conversion rather than
    refusing one parameter by name.
    """

    def test_a_long_exponent_chain_is_a_named_refusal(self):
        with self.assertRaises(_paramexpr.ExprError) as cm:
            _paramexpr.evaluate("1" + "**1" * 2000, lambda n: None)
        self.assertIn("nests more than", str(cm.exception))

    def test_the_refusal_reaches_the_deck_instead_of_a_traceback(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "p.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*PARAMETER_EXPRESSION\n"
                     + f"{'Rdeep':<10}" + "1" + "**1" * 2000 + "\n*END\n")
        parse_k_file(path)
        warns = list(_parser.PARSER_WARNINGS)
        tmp.cleanup()
        self.assertTrue([w for w in warns if "nests more than" in w])

    def test_the_manuals_exponent_semantics_are_unchanged(self):
        """p.36-9 Remark 2d and the right-associativity the cap must not
        disturb."""
        lk = (lambda n: None)
        for src, want in (("2**3**2", (512, True)),      # right-associative
                          ("-3**2", (9, True)),          # Remark 2d verbatim
                          ("2**-1", (0.5, False)),       # signed exponent
                          ("-2**2**3", (256, True)),
                          ("1" + "**1" * 10, (1, True))):
            with self.subTest(src=src):
                self.assertEqual(_paramexpr.evaluate(src, lk), want)


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — *PARAMETER_DUPLICATION Remark 2 (only the FIRST card counts)
# ─────────────────────────────────────────────────────────────────────────────

class TestParameterDuplicationOnlyTheFirstCard(unittest.TestCase):
    r"""Vol I R17 p.36-6 Remark 2, verbatim: *"Multiple Cards. Only one
    \*PARAMETER_DUPLICATION card is allowed. If more than one is found, a
    warning is issued and any after the first are ignored."* The rule was
    quoted in ``_set_parameter_duplication``'s own docstring and the
    assignment below it was unconditional, so a SECOND card won.

    Vol I p.138's R17 release note is the independent corroboration: *"Also,
    only honor the first \*PARAMETER_DUPLICATION card."*

    MEASURED before the fix on the deck below: DFLAG ended at 2 and
    ``thk = 9.0``; LS-DYNA ignores the second card, keeps DFLAG 1 and
    ``thk = 1.0``. That is a parameter VALUE, so it reaches the emitted deck.
    """

    def _thick(self, dflags) -> float:
        cards = "".join(f"*PARAMETER_DUPLICATION\n{_row(d)}\n" for d in dflags)
        deck = "\n".join([
            "*KEYWORD", cards.rstrip("\n"),
            "*PARAMETER", f"{'Rthk':<10}{'1.0':>10}",
            "*PARAMETER", f"{'Rthk':<10}{'9.0':>10}",
            "*NODE",
            _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
            _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
            "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4),
            "*PART", "plate", _row(1, 1, 1),
            "*SECTION_SHELL", _row(1, 2),
            _row("&thk", "&thk", "&thk", "&thk"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        res, starter = _convert(deck)
        lines = starter.splitlines()
        i = lines.index("/PROP/SHELL/1")
        data = [ln for ln in lines[i + 1:i + 14] if not ln.startswith("#")]
        return res, float(data[3][20:40])

    def test_a_second_card_does_not_change_the_policy(self):
        res, thick = self._thick([1, 2])
        self.assertAlmostEqual(thick, 1.0, places=9)
        w = _warns(res, "only ONE such card")
        self.assertEqual(len(w), 1)
        self.assertIn("DFLAG = 2", w[0])
        self.assertIn("DFLAG = 1 stands", w[0])

    def test_the_first_card_still_decides(self):
        """DFLAG 2 first, 1 second: the deck asked for last-wins and gets it."""
        res, thick = self._thick([2, 1])
        self.assertAlmostEqual(thick, 9.0, places=9)
        self.assertTrue(_warns(res, "only ONE such card"))

    def test_a_single_card_is_silent(self):
        res, thick = self._thick([2])
        self.assertAlmostEqual(thick, 9.0, places=9)
        self.assertEqual(_warns(res, "only ONE such card"), [])

    def test_two_identical_cards_do_not_warn(self):
        """Nothing is lost when the repeat asks for what already stands."""
        res, thick = self._thick([2, 2])
        self.assertAlmostEqual(thick, 9.0, places=9)
        self.assertEqual(_warns(res, "only ONE such card"), [])


class TestParameterDuplicationDefaultIsFirstWins(unittest.TestCase):
    r"""The fence on the one decision in this batch where the manual argues
    with itself, so a later round does not re-litigate it blind.

    p.36-5 Remark 5's worked example says that after an include redefines a
    non-LOCAL ``VAL1``, main.k sees the NEW value. p.36-6 says the opposite
    for the same case: DFLAG's Default is 1, *"issue a warning and ignore the
    new definition"*, and Remark 1 scopes it explicitly — *"a non-LOCAL that
    masks a non-LOCAL will"* trigger those actions. k2rad follows p.36-6, on
    the reading that p.36-5 is illustrating LOCAL scoping rather than
    duplication policy, and because p.36-5 Remark 6 plus the R17 release note
    on Vol I p.138 both present MUTABLE as the opt-in escape from a default in
    which *"\*PARAMETER_DUPLICATION says redefinition is not allowed"* — an
    escape hatch that only makes sense if the default forbids.

    Master was LAST-wins here, so this is where the batch changed a resolved
    parameter value on real decks.
    """

    def _thk(self, extra_files=None, main_extra="", child=""):
        files = {"main.k": "\n".join([
            "*KEYWORD", "*PARAMETER", f"{'Rthk':<10}{'1.0':>10}",
            main_extra,
            "*NODE",
            _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
            _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
            "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4),
            "*PART", "plate", _row(1, 1, 1),
            "*SECTION_SHELL", _row(1, 2),
            _row("&thk", "&thk", "&thk", "&thk"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])}
        if child:
            files["inc.k"] = child
        res, starter = _convert_files(files)
        lines = starter.splitlines()
        i = lines.index("/PROP/SHELL/1")
        data = [ln for ln in lines[i + 1:i + 14] if not ln.startswith("#")]
        return res, float(data[3][20:40])

    def test_a_non_LOCAL_redefinition_inside_an_include_is_ignored(self):
        res, thick = self._thk(
            main_extra="*INCLUDE\ninc.k",
            child="*KEYWORD\n*PARAMETER\n" + f"{'Rthk':<10}{'9.0':>10}"
                  + "\n*END\n")
        self.assertAlmostEqual(thick, 1.0, places=9)
        self.assertTrue(_warns(res, "defined more than once"))

    def test_MUTABLE_is_the_documented_escape_from_first_wins(self):
        """p.36-5 Remark 6: *"Redefinition is allowed regardless of the
        setting of \\*PARAMETER_DUPLICATION. The MUTABLE qualifier must appear
        for the first definition of the parameter."* So a MUTABLE FIRST
        definition is the sanctioned way to get the later value, which is what
        makes first-wins a defensible default rather than a lossy one."""
        files = {"main.k": "\n".join([
            "*KEYWORD", "*PARAMETER_MUTABLE", f"{'Rthk':<10}{'1.0':>10}",
            "*PARAMETER", f"{'Rthk':<10}{'9.0':>10}",
            "*NODE",
            _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
            _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
            "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4),
            "*PART", "plate", _row(1, 1, 1),
            "*SECTION_SHELL", _row(1, 2),
            _row("&thk", "&thk", "&thk", "&thk"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])}
        res, starter = _convert_files(files)
        lines = starter.splitlines()
        i = lines.index("/PROP/SHELL/1")
        data = [ln for ln in lines[i + 1:i + 14] if not ln.startswith("#")]
        self.assertAlmostEqual(float(data[3][20:40]), 9.0, places=9)
        self.assertEqual(_warns(res, "defined more than once"), [])


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — *DAMPING_GLOBAL's per-DOF scale factors
# ─────────────────────────────────────────────────────────────────────────────

_DAMP_MESH = "\n".join([
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4),
    "*PART", "plate", _row(1, 1, 1),
    "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"), ""])


def _damp_deck(scales, beta=None) -> str:
    out = ["*KEYWORD", "*DAMPING_GLOBAL",
           _row(0, "10.0", *scales), _DAMP_MESH.rstrip("\n")]
    if beta is not None:
        out += ["*DAMPING_PART_STIFFNESS", _row(1, beta)]
    out += ["*CONTROL_TERMINATION", _row("1.0"), "*END", ""]
    return "\n".join(out)


def _damp_alphas(starter: str):
    """The per-DOF alphas of the emitted /DAMP — six on Format 2, one on
    Format 1. Card 1 is ``Alpha Beta grnod_ID skew_ID Tstart Tstop``; the
    optional rows 2-6 are ``Alpha_i Beta_i``."""
    lines = starter.splitlines()
    i = [k for k, ln in enumerate(lines) if ln.startswith("/DAMP/")][0]
    out = []
    for ln in lines[i + 2:]:                       # skip the title line
        if ln.startswith("/") or ln.startswith("#"):
            if out:
                break
            continue
        if not ln.strip():
            break
        out.append(float(ln[0:20]))
    return out


class TestDampingGlobalPerDofScaleFactors(unittest.TestCase):
    """Vol I R17 p.15-8 gives ``*DAMPING_GLOBAL`` six scale factors STX..SRZ
    ("Scale factor on global x translational damping forces" and so on), and
    p.15-9 Remark 2 is exact about when they mean "uniform": *"If STX = STY =
    STZ = SRX = SRY = SRZ = 0.0 in the input above, all six values are
    defaulted to unity."*

    Both /DAMP branches wrote the SAME uniform alpha on all six DOFs — the
    Format-1 branch with a warning, the Format-2 branch (reached only when a
    ``*DAMPING_PART_STIFFNESS`` supplied a beta) in complete silence. So a
    card with STX = 1 and the rest 0 removed energy from five DOFs the source
    deck leaves undamped, and on the Format-2 path nothing said so at all.

    The map is the one the ``*DAMPING_PART_MASS`` FLAG = 1 emitter already
    uses and that ``hm_read_damp.F:104-115`` reads as DAMPR(3/5/7/9/11/13):
    ``alpha_i = VALDMP * ST_i`` in the order x, y, z, xx, yy, zz. Beta is not
    scaled — it comes from ``*DAMPING_PART_STIFFNESS``, which has no per-DOF
    cells of its own.

    Corpus impact: NONE. Scanning both corpus roots (2404 files) found 53
    ``*DAMPING_GLOBAL`` cards and not one with a non-zero scale factor.
    """

    ZERO = ("0.0",) * 6

    def test_all_six_zero_is_the_unity_default(self):
        res, starter = _convert(_damp_deck(self.ZERO))
        self.assertEqual(_damp_alphas(starter), [10.0])   # Format 1
        self.assertEqual(_warns(res, "*DAMPING_GLOBAL: STX"), [])

    def test_x_only_damps_x_only(self):
        res, starter = _convert(
            _damp_deck(("1.0", "0.0", "0.0", "0.0", "0.0", "0.0")))
        self.assertEqual(_damp_alphas(starter),
                         [10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        w = _warns(res, "STY, STZ, SRX, SRY, SRZ = 0.0")
        self.assertEqual(len(w), 1)
        self.assertIn("Remark 2", w[0])

    def test_the_slot_order_is_x_y_z_xx_yy_zz(self):
        _res, starter = _convert(
            _damp_deck(("1.0", "2.0", "3.0", "4.0", "5.0", "6.0")))
        self.assertEqual(_damp_alphas(starter),
                         [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])

    def test_uniform_non_unity_factors_scale_every_row(self):
        _res, starter = _convert(_damp_deck(("0.5",) * 6))
        self.assertEqual(_damp_alphas(starter), [5.0] * 6)

    def test_the_Format_2_branch_scales_too_and_keeps_beta_uniform(self):
        """The half that used to be silent: with a beta the card is already
        Format 2, and it wrote the unscaled alpha on all six rows."""
        _res, starter = _convert(
            _damp_deck(("1.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
                       beta="0.05"))
        self.assertEqual(_damp_alphas(starter),
                         [10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        lines = starter.splitlines()
        i = [k for k, ln in enumerate(lines) if ln.startswith("/DAMP/")][0]
        data = [ln for ln in lines[i + 1:i + 10]
                if not ln.startswith("#") and ln.strip()]
        for ln in data[1:]:
            self.assertAlmostEqual(float(ln[20:40]), 0.05, places=9)


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — p.16-50's RADIUS exemption covers LENL/LENM too
# ─────────────────────────────────────────────────────────────────────────────

_XS_MESH = "\n".join([
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    _node16(5, 0.0, 0.0, 10.0), _node16(6, 10.0, 0.0, 10.0),
    _node16(7, 10.0, 10.0, 10.0), _node16(8, 0.0, 10.0, 10.0),
    "*ELEMENT_SOLID", _i8(1, 1), _i8(1, 2, 3, 4, 5, 6, 7, 8),
    "*SECTION_SOLID", _row(1, 1),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
    "*PART", "brick", _row(1, 1, 1), ""])


def _xsec_deck(radius: str, lenl="5.0", lenm="5.0", hev=("",) * 3) -> str:
    """*hev* defaults to BLANK cells: p.16-50 gives XHEV/YHEV/ZHEV a default
    of 0., and the handler treats a written cell as "the card states an edge
    vector" — so a card meaning "no edge vector" leaves them empty."""
    return "\n".join([
        "*KEYWORD", _XS_MESH.rstrip("\n"),
        "*DATABASE_CROSS_SECTION_PLANE",
        _row(0, "5.0", "5.0", "5.0", "15.0", "5.0", "5.0", radius),
        _row(hev[0], hev[1], hev[2], lenl, lenm, 0, 0),
        "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])


class TestCrossSectionRadiusExemptsFiveCells(unittest.TestCase):
    """Vol I R17 p.16-50, verbatim and covering FIVE cells in one sentence:
    *"If RADIUS != 0.0, the variables XHEV, YHEV, ZHEV, LENL, and LENM, which
    are specified on Card 1a.2, will be ignored."*

    The exemption was applied to XHEV/YHEV/ZHEV only, so a RADIUS-limited card
    with LENL/LENM still got *"finite parallelogram extent (LENL/LENM) cannot
    be carried into /SECT"* — a fidelity loss that does not exist, because
    LS-DYNA ignores those cells itself and k2rad's behaviour is then exactly
    LS-DYNA's. Same #125/#130 class the round audits, in its over-alarming
    direction.
    """

    def test_RADIUS_zero_still_reports_the_real_loss(self):
        res, _starter = _convert(_xsec_deck("0.0"))
        w = _warns(res, "finite parallelogram extent")
        self.assertEqual(len(w), 1)
        self.assertIn("infinite plane", w[0])

    def test_a_RADIUS_limited_card_loses_nothing(self):
        res, _starter = _convert(_xsec_deck("3.0"))
        self.assertEqual(_warns(res, "finite parallelogram extent"), [])
        w = _warns(res, "so LS-DYNA ignores")
        self.assertEqual(len(w), 1)
        self.assertIn("LENL/LENM", w[0])
        self.assertIn("nothing is lost here", w[0])

    def test_the_edge_vector_is_still_named_beside_them(self):
        res, _starter = _convert(
            _xsec_deck("3.0", hev=("5.0", "5.0", "15.0")))
        w = _warns(res, "so LS-DYNA ignores")
        self.assertEqual(len(w), 1)
        self.assertIn("XHEV/YHEV/ZHEV", w[0])
        self.assertIn("LENL/LENM", w[0])

    def test_a_RADIUS_card_with_neither_says_nothing(self):
        res, _starter = _convert(_xsec_deck("3.0", lenl="0.0", lenm="0.0"))
        self.assertEqual(_warns(res, "so LS-DYNA ignores"), [])
        self.assertEqual(_warns(res, "finite parallelogram extent"), [])


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — an *EOS_* refusal must name the DECK's spelling
# ─────────────────────────────────────────────────────────────────────────────

_EOS_DECK = "\n".join([
    "*KEYWORD",
    "*MAT_ELASTIC", _row(7, "7.85E-9", "2.1E5", "0.3"),
    "*EOS_LINEAR_POLYNOMIAL",
    _row(7, "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
    _row("0.0", "1.0"),
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    "*ELEMENT_SHELL", _i8(1, 7, 1, 2, 3, 4),
    "*PART", "plate", _row(7, 7, 7),
    "*SECTION_SHELL", _row(7, 2), _row("1.0", "1.0", "1.0", "1.0"),
    "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])


class TestEosRefusalNamesBothSpellings(unittest.TestCase):
    """``EosCard.kind`` is the RADIOSS keyword suffix, assigned in the handler
    ("POLYNOMIAL", "GRUNEISEN", "IDEAL-GAS"), so every message built as
    ``"*EOS_" + kind`` printed a keyword+id pair that exists in NEITHER file:
    grepping the deck for ``*EOS_POLYNOMIAL`` finds nothing (it spells the
    card ``*EOS_LINEAR_POLYNOMIAL``) and grepping the ``.rad`` finds
    ``/EOS/POLYNOMIAL/7``. ``*EOS_IDEAL-GAS`` was worse — that hyphen is not
    even legal LS-DYNA. The #131 label class.
    """

    def test_the_collision_refusal_carries_the_LS_DYNA_keyword(self):
        res, starter = _convert(_EOS_DECK)
        self.assertEqual(_headers(starter, "/EOS/"), [])
        w = _warns(res, "*EOS_LINEAR_POLYNOMIAL 7")
        self.assertEqual(len(w), 1)
        # ... and the Radioss card it would have been, so the reader can grep
        # from whichever side they have open.
        self.assertIn("(/EOS/POLYNOMIAL/7)", w[0])
        self.assertEqual(_warns(res, "*EOS_POLYNOMIAL 7:"), [])

    def test_the_hyphenated_radioss_spelling_never_appears(self):
        deck = _EOS_DECK.replace(
            "*EOS_LINEAR_POLYNOMIAL\n"
            + _row(7, "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
            + "\n" + _row("0.0", "1.0"),
            "*EOS_IDEAL_GAS\n"
            + _row(7, "700.0", "1000.0", "0.0", "0.0", "300.0", "1.0"))
        res, _starter = _convert(deck)
        self.assertTrue(_warns(res, "*EOS_IDEAL_GAS 7"))
        self.assertEqual(_warns(res, "*EOS_IDEAL-GAS"), [])


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — every synthesized /GRNOD id must dodge the user *SET_NODE namespace
# ─────────────────────────────────────────────────────────────────────────────

_MASS_MESH = "\n".join([
    "*NODE",
    _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
    _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
    _node16(5, 20.0, 10.0, 0.0),
    "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4),
    "*PART", "plate", _row(1, 1, 1),
    "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
    "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"), ""])


class TestEverySynthesizedGrnodDodgesUserSets(unittest.TestCase):
    """The ``/GRNOD`` half of the batch's group-allocator item, which the
    review round left open at 24 of 38 emission sites.

    ``_make_extra_groups`` re-emits every user ``*SET_NODE`` under its own SID,
    so a set numbered at or above the auto-id base collides with a synthesized
    group and the starter refuses the WHOLE deck:
    ``ERROR ID : 79 ** ERROR: DUPLICATE ID / IN NODE GROUP DEFINITION``.

    The probe below is aimed at the id the allocator ACTUALLY takes — it reads
    that id out of a first conversion instead of assuming 90001 — because the
    #131 lesson is that a collision probe planted at the base id can be eaten
    by an earlier allocation and leave the guard untested in both arms.

    STARTER-MEASURED on this deck shape: before the fix the emitted deck
    carried ``/GRNOD/NODE/90001`` twice and the starter stopped with ERROR 79
    ERROR TERMINATION (exit 2); after it, 0 ERRORS.
    """

    #: One carrier per emitter this round moved, because a probe that reaches
    #: only ONE of them proves nothing about the others: the three
    #: initial-velocity spellings alone land in three different functions
    #: (``*INITIAL_VELOCITY_NODE`` -> ``_make_inivel``, ``*INITIAL_VELOCITY``
    #: with an NSID -> ``_make_initial_velocity``, ``_GENERATION`` ->
    #: ``_make_initial_velocity_generation``). Found the hard way: the first
    #: draft of this test used ``*INITIAL_VELOCITY_NODE`` and a mutation of the
    #: ``_make_initial_velocity`` site left it green.
    CARRIERS = {
        "*ELEMENT_MASS": "*ELEMENT_MASS\n" + _i8(1, 5) + f"{'1.0E-06':>16}",
        "*INITIAL_VELOCITY_NODE":
            "*INITIAL_VELOCITY_NODE\n" + _row(1, "100.0", "0.0", "0.0"),
        "*INITIAL_VELOCITY":
            "*SET_NODE_LIST\n" + _row(11) + "\n" + _row(1, 2)
            + "\n*INITIAL_VELOCITY\n" + _row(11, 0, 0) + "\n"
            + _row("100.0", "0.0", "0.0"),
        "*INITIAL_VELOCITY_GENERATION":
            "*INITIAL_VELOCITY_GENERATION\n"
            + _row(1, 2, "0.0", "100.0", "0.0", "0.0") + "\n"
            + _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
        "*LOAD_NODE_POINT":
            "*DEFINE_CURVE\n" + _row(9) + "\n" + _row("0.0", "0.0") + "\n"
            + _row("1.0", "1.0") + "\n"
            + "*LOAD_NODE_POINT\n" + _row(5, 1, 9, "1.0"),
    }

    #: The auto-id base; a user set below it cannot collide by construction.
    AUTO_BASE = 90000

    def _emitted_grnod_ids(self, extra=""):
        deck = "\n".join([
            "*KEYWORD", _MASS_MESH.rstrip("\n"), extra,
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        res, starter = _convert(deck)
        ids = [int(ln.rsplit("/", 1)[1])
               for ln in starter.splitlines() if ln.startswith("/GRNOD/")]
        return res, ids

    def test_every_carrier_dodges_a_user_set_on_its_own_allocated_id(self):
        """Aimed at the id the allocator ACTUALLY takes: the order is read out
        of a first conversion instead of being assumed to start at 90001. On
        the `_GENERATION` carrier it does not — a /SKEW is minted first — and
        #131's collision test failed exactly that way."""
        for name, card in self.CARRIERS.items():
            with self.subTest(carrier=name):
                _res, ids = self._emitted_grnod_ids(card)
                auto = [i for i in ids if i >= self.AUTO_BASE]
                self.assertTrue(auto, f"{name} emitted no synthesized /GRNOD")
                for taken in auto:
                    res, ids2 = self._emitted_grnod_ids(
                        card + "\n*SET_NODE_LIST\n" + _row(taken) + "\n"
                        + _row(1, 2))
                    self.assertEqual(
                        len(ids2), len(set(ids2)),
                        f"{name}: duplicate /GRNOD id in {ids2} "
                        f"(planted a user set at {taken})")
                    self.assertIn(taken, ids2)
                    self.assertEqual(
                        _warns(res, "emitted by more than one /GRNOD"), [])

    def test_no_emitter_is_left_on_the_bare_allocator(self):
        """The audit itself, as a fence: every ``_emit_grnod_node`` call whose
        id is allocated in its own function must allocate it from
        ``next_grnod_id``. The three that do not allocate are the two that
        re-emit a user set under its OWN sid — reallocating those would break
        every reference to them — and the rigid-wall motion group, whose id
        its caller allocates."""
        import ast
        root = Path(__file__).resolve().parent.parent / "k2rad"
        bare = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                allocs: dict = {}
                for node in ast.walk(fn):
                    if isinstance(node, ast.Assign) and \
                            isinstance(node.value, ast.Call):
                        f2 = node.value.func
                        if isinstance(f2, ast.Attribute) and \
                                f2.attr.startswith("next_"):
                            for t in node.targets:
                                if isinstance(t, ast.Name):
                                    allocs.setdefault(t.id, []).append(
                                        (node.lineno, f2.attr))
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id == "_emit_grnod_node"
                            and node.args
                            and isinstance(node.args[0], ast.Name)):
                        seen = [x for x in allocs.get(node.args[0].id, [])
                                if x[0] <= node.lineno]
                        if seen and seen[-1][1] != "next_grnod_id":
                            bare.append(f"{path.name}:{node.lineno} "
                                        f"({fn.name}, {seen[-1][1]})")
        self.assertEqual(bare, [])


# ─────────────────────────────────────────────────────────────────────────────
# MINOR — one deck, two through-thickness point counts, one global offset
# ─────────────────────────────────────────────────────────────────────────────

def _stress_record(eid: int, nip: int) -> str:
    """``*INITIAL_STRESS_SHELL`` card 1 (EID NPLANE NTHICK ...) + one
    ``T sig_xx sig_yy sig_zz sig_xy sig_yz sig_zx eps_p`` card per station.
    T comes FIRST — putting sig_xx in column 1 writes the stress into the
    thickness coordinate and leaves the tensor identically zero."""
    out = ["*INITIAL_STRESS_SHELL", _row(eid, 1, nip)]
    for k in range(nip):
        t = round(-1.0 + 2.0 * k / (nip - 1), 6)
        out.append(_row(t, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    return "\n".join(out) + "\n"


class TestInitialStressShellMixedNbIntegr(unittest.TestCase):
    """``INISHVAR`` is a SINGLE GLOBAL, not a per-record value.

    The reader sets ``INISHVAR = 22 + NIP*6`` per RECORD
    (``hm_read_inistate_d00.F:2206/2389/3347/3516``) into the COM01 common
    (``share/includes/com01_c.inc:34``), and ``csigini.F:231/233`` plus
    ``scigini4.F:345/347/487/489`` read ``SIGSH(INISHVAR+IT)`` (sigma_zz) and
    ``SIGSH(INISHVAR+NPTI+IT)`` (pos_nip) at CONSUME time — with whatever the
    LAST record left there. Two shell parts at NIP 3 and NIP 5 are each read
    correctly and then consumed against one offset, so every element whose NIP
    differs from the last record's picks up its through-thickness stress and
    its station positions from the wrong slots, at 0 starter ERROR /
    0 WARNING.

    Each record passes the per-part NTHICK check on its own, so nothing else
    in the pass can see it. PRE-EXISTING — master emits the byte-identical
    block — but item (D) adds a second block kind to the same pass, so the
    deck is named rather than left silent. The #127 class one namespace over.
    """

    def _deck(self, nip_a: int, nip_b: int) -> str:
        return "\n".join([
            "*KEYWORD", "*NODE",
            _node16(1, 0.0, 0.0, 0.0), _node16(2, 10.0, 0.0, 0.0),
            _node16(3, 10.0, 10.0, 0.0), _node16(4, 0.0, 10.0, 0.0),
            _node16(5, 20.0, 0.0, 0.0), _node16(6, 20.0, 10.0, 0.0),
            "*ELEMENT_SHELL", _i8(1, 1, 1, 2, 3, 4), _i8(2, 2, 2, 5, 6, 3),
            "*PART", "part a", _row(1, 1, 1),
            "*PART", "part b", _row(2, 2, 1),
            "*SECTION_SHELL", _row(1, 2, "1.0", nip_a),
            _row("1.0", "1.0", "1.0", "1.0"),
            "*SECTION_SHELL", _row(2, 2, "1.0", nip_b),
            _row("1.0", "1.0", "1.0", "1.0"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            _stress_record(1, nip_a).rstrip("\n"),
            _stress_record(2, nip_b).rstrip("\n"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])

    def test_two_point_counts_in_one_pass_are_named(self):
        res, starter = _convert(self._deck(3, 5))
        self.assertTrue(_headers(starter, "/INISHE/STRS_F/GLOB"))
        w = _warns(res, "do NOT share one through-thickness point count")
        self.assertEqual(len(w), 1)
        self.assertIn("[3, 5]", w[0])
        self.assertIn("INISHVAR", w[0])
        # It is a starter limitation, not a conversion loss — the records are
        # still written, and the message has to say which it is.
        self.assertIn("not a conversion loss", w[0])

    def test_one_shared_point_count_is_silent(self):
        res, starter = _convert(self._deck(5, 5))
        self.assertTrue(_headers(starter, "/INISHE/STRS_F/GLOB"))
        self.assertEqual(
            _warns(res, "do NOT share one through-thickness point count"), [])


# ─────────────────────────────────────────────────────────────────────────────
# MAJOR (pre-existing) — a *NODE id welded to a negative first coordinate
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeIdWeldedToANegativeCoordinate(unittest.TestCase):
    """``handle_node``'s fixed-vs-free discrimination tested the WIDTH of
    fields 2-4 and never looked at field 1.

    LS-DYNA's standard ``*NODE`` is I8 + 3xE16, and a negative coordinate
    fills its 16-char field completely, gluing onto the field before it. When
    X and Y are negative and Z is not, the whitespace split produces four
    perfectly ordinary-looking tokens with the NODE ID welded to the front of
    the first::

        '       5-1.000000000E+01-1.000000000E+01 0.000000000E+00       7   0'
          -> ['5-1.000000000E+01-1.000000000E+01', '0.000000000E+00', '7', '0']

    so the row took the FREE branch, ``to_int`` of that merged token returned
    0, and the node was written to ``state.nodes[0]`` with junk coordinates.

    MEASURED on ``dynaexamples/sph/bar-iv/taylor1.k`` (the real corpus
    carrier), converting on master vs this branch:

        master   /NODE ids below 100 = [0, 1, 2, 3, 4, 6, 8]
                 nodes 5 and 7 GONE, a phantom node 0 in their place, the
                 deck's only /BRICK still referencing 5 and 7, ZERO warnings
                 -> starter: 2 x ERROR ID 78 UNDEFINED NODE NUMBER
                    ("NODE ID=5 DOES NOT EXIST", "NODE ID=7 DOES NOT EXIST")
        branch   [1, 2, 3, 4, 5, 6, 7, 8], no node 0, both ERROR 78 gone

    Corpus reach: **58 303 rows across 188 files** in the two corpus roots,
    all of them this one shape. The risk class the fix could have traded
    against — a free-format id longer than the fixed I8 column, or a comma
    row, or a ``&parameter`` id — is measured EMPTY, and ``_free_node_id``
    accepts ``&name`` anyway.
    """

    HEAD = "*KEYWORD\n"
    TAIL = ("*SECTION_SOLID\n" + _row(1, 1) + "\n"
            "*MAT_ELASTIC\n" + _row(1, "7.85E-9", "2.1E5", "0.3") + "\n"
            "*PART\nbrick\n" + _row(1, 1, 1) + "\n"
            "*CONTROL_TERMINATION\n" + _row("1.0") + "\n*END\n")

    #: The taylor1.k corner block verbatim in shape: X and Y negative, Z not,
    #: TC = 7 in the fixed column. Rows 5 and 7 are the ones that used to fall
    #: through; 1 and 3 already took the fixed branch and are the control.
    MESH = "*NODE\n" + "\n".join(
        f"{nid:>8}{x:>16.9E}{y:>16.9E}{z:>16.9E}{7:>8}{0:>8}"
        for nid, x, y, z in (
            (1, -10.0, -10.0, -7.0), (2, 10.0, -10.0, -7.0),
            (3, -10.0, 10.0, -7.0), (4, 10.0, 10.0, -7.0),
            (5, -10.0, -10.0, 0.0), (6, 10.0, -10.0, 0.0),
            (7, -10.0, 10.0, 0.0), (8, 10.0, 10.0, 0.0))) + "\n"

    def _deck(self):
        return (self.HEAD + self.MESH
                + "*ELEMENT_SOLID\n" + _i8(1, 1) + "\n"
                + _i8(1, 2, 4, 3, 5, 6, 8, 7) + "\n" + self.TAIL)

    def test_the_welded_rows_are_read_from_their_fixed_columns(self):
        _res, starter = _convert(self._deck())
        ids = []
        lines = starter.splitlines()
        i = lines.index("/NODE")
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            ids.append(int(ln[0:10]))
        self.assertEqual(sorted(ids), [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertNotIn(0, ids)

    def test_the_coordinates_are_the_cards_own(self):
        _res, starter = _convert(self._deck())
        self.assertEqual(_node_xyz(starter, 5), (-10.0, -10.0, 0.0))
        self.assertEqual(_node_xyz(starter, 7), (-10.0, 10.0, 0.0))
        # The control rows, which already took the fixed branch.
        self.assertEqual(_node_xyz(starter, 1), (-10.0, -10.0, -7.0))
        self.assertEqual(_node_xyz(starter, 3), (-10.0, 10.0, -7.0))

    def test_the_element_no_longer_references_dead_ids(self):
        res, starter = _convert(self._deck())
        self.assertTrue(_headers(starter, "/BRICK/"))
        self.assertEqual(_warns(res, "MESH LOSS"), [])

    def test_the_TC_RC_count_matches_an_independent_scan(self):
        """The batch's new *NODE TC/RC note counted 6 on taylor1.k where an
        independent scan of the same file found 8 — the two lost rows carry
        TC = 7 as well. The counter was right; the reader under it was not."""
        res, _starter = _convert(self._deck())
        w = _warns(res, "TC/RC cells")
        self.assertEqual(len(w), 1)
        self.assertIn("8 node(s)", w[0])

    def test_a_genuine_free_format_row_still_takes_the_free_branch(self):
        """The discriminator: the same mesh written free-format, where field 1
        IS an integer token and the fixed columns hold nothing."""
        free = "*NODE\n" + "\n".join(
            f"{nid}, {x}, {y}, {z}"
            for nid, x, y, z in ((1, -10.0, -10.0, -7.0), (2, 10.0, -10.0, -7.0),
                                 (3, -10.0, 10.0, -7.0), (4, 10.0, 10.0, -7.0),
                                 (5, -10.0, -10.0, 0.0), (6, 10.0, -10.0, 0.0),
                                 (7, -10.0, 10.0, 0.0), (8, 10.0, 10.0, 0.0)))
        deck = (self.HEAD + free + "\n*ELEMENT_SOLID\n" + _i8(1, 1) + "\n"
                + _i8(1, 2, 4, 3, 5, 6, 8, 7) + "\n" + self.TAIL)
        _res, starter = _convert(deck)
        self.assertEqual(_node_xyz(starter, 5), (-10.0, -10.0, 0.0))
        self.assertEqual(_node_xyz(starter, 8), (10.0, 10.0, 0.0))

    def test_a_parameter_node_id_is_still_free_format(self):
        """``&name`` in field 1 resolves through ``to_int``; the guard must
        not push it into the fixed branch, where the ``&`` would be sliced."""
        deck = ("*KEYWORD\n*PARAMETER\n" + f"{'Ibase':<10}{5:>10}\n"
                + "*NODE\n"
                + "&base, -10.0, -10.0, 0.0\n"
                + "*CONTROL_TERMINATION\n" + _row("1.0") + "\n*END\n")
        _res, starter = _convert(deck)
        self.assertEqual(_node_xyz(starter, 5), (-10.0, -10.0, 0.0))


if __name__ == "__main__":
    unittest.main()
