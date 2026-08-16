"""Tests for the ERODING / node-to-surface contact + *DEFINE_FRICTION batch:

  *CONTACT_ERODING_SINGLE_SURFACE                 -> /INTER/TYPE25 ILEV=1
  *CONTACT_ERODING_SURFACE_TO_SURFACE             -> /INTER/TYPE25 ILEV=2
  *CONTACT_ERODING_NODES_TO_SURFACE               -> /INTER/TYPE25 ILEV=3 (one-way)
  *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE           -> /INTER/TYPE25 ILEV=3 (one-way)
  *DEFINE_FRICTION                                -> /FRICTION (Ifric=2 Darmstad)

Before this batch all five landed in ``skipped_keywords``: the exact-match
dispatch has no CONTACT_ prefix fallback, and a *CONTACT that misses it does not
merely lose an output card — the two surfaces stop interacting and the run
produces a plausible-looking answer with no load path. They were the ONLY
unhandled *CONTACT spellings left in the reference corpus (30 x
ERODING_NODES_TO_SURFACE in the three W11 bird-strike decks, 7 x
ERODING_SURFACE_TO_SURFACE in the W9 missile decks).

The batch's defining decision is the /SURF flavour, and it is the thing these
tests exist to pin: an eroding contact on SOLID parts is emitted over
``/SURF/PART/ALL`` (interior faces included) rather than the ``/SURF/PART/EXT``
every other k2rad contact uses, because only then can the engine re-expose a
face when the brick behind it dies (starter i25sti3.F:950-951 marks interior
segments with a negative stiffness, engine check_surface_state.F:174-203 flips
one active when NB_CONNECTED_ELM drops to 1). With /EXT the machinery still
arms and there is simply nothing to wake — a SILENT loss, which is why the
default is /ALL and the opt-out (--eroding-surf-ext) is loud.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import HANDLERS, dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState
from k2rad.writer.contacts import (
    _bind_friction_table,
    _contact_friction,
    _emit_inter_type7,
    _emit_inter_type25,
    _emit_inter_type25_self,
    _type25_istf_iedge,
)
from k2rad.writer.frictions import _friction_coeffs


def _convert(deck: str, **opts):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **opts)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


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


def _block(starter: str, header: str):
    """The lines of one /KEYWORD/id block, header line first."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln == header:
            out = [ln]
            for nxt in lines[i + 1:]:
                if nxt.startswith("#---1"):
                    break
                out.append(nxt)
            return out
    raise AssertionError(f"{header!r} not found in starter")


def _cards(block):
    """The non-comment data lines of a block, title line dropped."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


# ── Deck pieces ─────────────────────────────────────────────────────────────
# Part 1 = a 2-brick solid column (the eroding target, nodes 1-12),
# part 2 = a single shell (the projectile, nodes 13-16).

_MESH = """*KEYWORD
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             0.0             0.0             1.0
       6             1.0             0.0             1.0
       7             1.0             1.0             1.0
       8             0.0             1.0             1.0
       9             0.0             0.0             2.0
      10             1.0             0.0             2.0
      11             1.0             1.0             2.0
      12             0.0             1.0             2.0
      13             0.0             0.0             5.0
      14             1.0             0.0             5.0
      15             1.0             1.0             5.0
      16             0.0             1.0             5.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
       2       1       5       6       7       8       9      10      11      12
*ELEMENT_SHELL
      11       2      13      14      15      16
*PART
target
         1         1         1
*PART
projectile
         2         2         1
*SECTION_SOLID
         1         1
*SECTION_SHELL
         2        16
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1     7.85E-9  210000.0       0.3
*SET_NODE_LIST
       500
        13        14        15        16
"""

_TERM = "*CONTROL_TERMINATION\n       1.0\n*END\n"


def _card2(fs="       0.0", fd="       0.0", dc="       0.0",
           vdc="       0.0", bt="       0.0", dt="1.00000E20") -> str:
    return f"{fs}{fd}{dc}       0.0{vdc}         0{bt}{dt}\n"


_CARD3 = "       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0\n"


def _eroding(kw: str, ssid: int, msid: int, sstyp: int, mstyp: int,
             card2: str = None, card4: str = "         0         1         1\n",
             optional_a: str = "") -> str:
    return (f"*{kw}\n"
            f"{ssid:10d}{msid:10d}{sstyp:10d}{mstyp:10d}         0         0         0         0\n"
            + (card2 if card2 is not None else _card2())
            + _CARD3 + card4 + optional_a)


def _n2s(kw: str, ssid: int, msid: int, sstyp: int, mstyp: int,
         card2: str = None, optional_a: str = "") -> str:
    return (f"*{kw}\n"
            f"{ssid:10d}{msid:10d}{sstyp:10d}{mstyp:10d}         0         0         0         0\n"
            + (card2 if card2 is not None else _card2())
            + _CARD3 + optional_a)


#: One friction table: default FS=0.4 FD=0.2 DC=1.5, one part pair 1-2.
FRICTION_7 = ("*DEFINE_FRICTION\n"
              "         7       0.4       0.2       1.5       0.0         0\n"
              "         1         2       0.5       0.3       2.0       0.0\n")


# ═══════════════════════════════════════════════════════════════════════════
# Dispatch: every spelling must reach a handler
# ═══════════════════════════════════════════════════════════════════════════

class DispatchTests(unittest.TestCase):
    BASES = ("CONTACT_ERODING_SINGLE_SURFACE",
             "CONTACT_ERODING_SURFACE_TO_SURFACE",
             "CONTACT_ERODING_NODES_TO_SURFACE",
             "CONTACT_NODES_TO_SURFACE",
             "CONTACT_AUTOMATIC_NODES_TO_SURFACE")

    def test_every_base_and_mpp_spelling_is_registered(self):
        for base in self.BASES:
            for kw in (base, base + "_MPP"):
                self.assertIn(kw, HANDLERS, f"*{kw} would land in skipped_keywords")

    def test_define_friction_is_registered(self):
        self.assertIn("DEFINE_FRICTION", HANDLERS)

    def test_id_and_title_suffixes_reach_the_handler(self):
        """_ID / _TITLE are stripped by the parser, so no extra key is needed —
        but the header card they add MUST be consumed, or Card 1 is read off
        the heading line and every side id comes back 0. Both spellings read the
        SAME ``CARD("%10d%-70s", _ID_, TITLE)`` (contact_spotweld.cfg is the
        only CONTACT cfg that defines _TITLE, and it aliases the _ID card) —
        see _parse_contact_header."""
        for suffix in ("_ID", "_TITLE"):
            deck = (_MESH + "*CONTACT_ERODING_SURFACE_TO_SURFACE" + suffix + "\n"
                    + "        42 eroding title\n"
                    + "         2         1         3         3         0         0         0         0\n"
                    + _card2() + _CARD3 + "         0         1         1\n" + _TERM)
            st = _dispatch(deck)
            self.assertEqual(len(st.contacts_type25), 1, suffix)
            c = st.contacts_type25[0]
            self.assertEqual((c.ssid, c.msid, c.sstyp, c.mstyp), (2, 1, 3, 3), suffix)
            self.assertEqual(c.title, "eroding title", suffix)
            self.assertEqual(c.inter_id, 42, suffix)

    def test_variant_and_eroding_flag_per_keyword(self):
        want = {
            "CONTACT_ERODING_SINGLE_SURFACE":     ("SINGLE_SURFACE", True),
            "CONTACT_ERODING_SURFACE_TO_SURFACE": ("SURFACE_TO_SURFACE", True),
            "CONTACT_ERODING_NODES_TO_SURFACE":   ("NODES_TO_SURFACE", True),
            "CONTACT_NODES_TO_SURFACE":           ("NODES_TO_SURFACE", False),
            "CONTACT_AUTOMATIC_NODES_TO_SURFACE": ("NODES_TO_SURFACE", False),
        }
        for kw, (variant, eroding) in want.items():
            body = (_eroding(kw, 500, 1, 4, 3) if eroding
                    else _n2s(kw, 500, 1, 4, 3))
            st = _dispatch(_MESH + body + _TERM)
            c = st.contacts_type25[0]
            self.assertEqual((c.variant, c.eroding), (variant, eroding), kw)

    def test_multi_contact_deck_keeps_every_interface(self):
        deck = (_MESH
                + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3)
                + _eroding("CONTACT_ERODING_NODES_TO_SURFACE", 500, 1, 4, 3)
                + _n2s("CONTACT_AUTOMATIC_NODES_TO_SURFACE", 500, 1, 4, 3)
                + _TERM)
        result, starter = _convert(deck)
        self.assertEqual(result.skipped_keywords, [])
        self.assertEqual(starter.count("/INTER/TYPE25/"), 3)
        ids = [ln.split("/")[-1] for ln in starter.splitlines()
               if ln.startswith("/INTER/TYPE25/")]
        self.assertEqual(len(set(ids)), 3, "auto-assigned interface ids collided")


# ═══════════════════════════════════════════════════════════════════════════
# The ERODING Card 4 shifts the optional-card stack
# ═══════════════════════════════════════════════════════════════════════════

class ErodingCardOffsetTests(unittest.TestCase):
    """ISYM/EROSOP/IADJ sits between Card 3 and optional Card A, so SOFT and
    IGNORE are one line further down than on any other *CONTACT. Reading them
    blind takes ISYM for SOFT and Card B's THKOPT for IGNORE."""

    #: Card A (SOFT=2 ...), Card B (PENMAX THKOPT=1 ...), Card C (IGAP IGNORE=1)
    OPT_ABC = ("         2       0.1         0     1.025         2         2\n"
               "       0.0         1         0         0         0         0\n"
               "         1         1       0.0       0.0\n")

    def test_card4_fields_are_parsed(self):
        st = _dispatch(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
            card4="         1         1         1\n") + _TERM)
        c = st.contacts_type25[0]
        self.assertEqual((c.isym, c.erosop, c.iadj), (1, 1, 1))

    def test_soft_and_ignore_read_past_card4(self):
        st = _dispatch(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
            card4="         0         1         0\n",
            optional_a=self.OPT_ABC) + _TERM)
        c = st.contacts_type25[0]
        self.assertEqual(c.soft, 2, "SOFT read from ISYM instead of Card A")
        self.assertEqual(c.ignore, 1, "IGNORE read from Card B THKOPT")

    def test_non_eroding_n2s_reads_card_a_one_line_earlier(self):
        st = _dispatch(_MESH + _n2s(
            "CONTACT_AUTOMATIC_NODES_TO_SURFACE", 500, 1, 4, 3,
            optional_a=self.OPT_ABC) + _TERM)
        c = st.contacts_type25[0]
        self.assertEqual((c.soft, c.ignore), (2, 1))

    def test_isym_erosop_iadj_are_reported_not_dropped(self):
        result, _ = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
            card4="         1         0         0\n") + _TERM)
        joined = " ".join(result.warnings)
        self.assertIn("ISYM=1", joined)
        self.assertIn("EROSOP=0", joined)
        self.assertIn("IADJ=0/blank", joined)


# ═══════════════════════════════════════════════════════════════════════════
# /INTER/TYPE25 card geometry
# ═══════════════════════════════════════════════════════════════════════════

class Type25CardTests(unittest.TestCase):
    """Column-exact card lines, hand-built against
    radioss2022/INTER/inter_type25.cfg FORMAT(radioss2022)."""

    def test_card_widths_match_the_cfg_format(self):
        widths = [90, 100, 80, 100, 100, 100]
        data = [ln for ln in _emit_inter_type25(1, "T", 11, 22, grnod_id=33)
                if not ln.startswith(("#", "/"))][1:]
        self.assertEqual([len(ln) for ln in data], widths)

    def test_surface_to_surface_card1_and_card2(self):
        _, starter = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3) + _TERM)
        blk = _block(starter, "/INTER/TYPE25/90001")
        cards = _cards(blk)
        # surf_ID1 = the shell (secondary) surface, surf_ID2 = the solid one.
        surf1, surf2 = int(cards[0][0:10]), int(cards[0][10:20])
        self.assertIn(f"/SURF/GRSHEL/{surf1}", starter)
        self.assertIn(f"/SURF/PART/ALL/{surf2}", starter)
        # Istf=2 (SOFT=0), Ithe=0, Igap=2, Irem_i2=0, blank, Idel=2, Iedge=1000
        self.assertEqual(cards[0][20:90],
                         "         2         0         2         0"
                         "                   2      1000")
        self.assertEqual(cards[1][0:10], "         0", "grnd_IDs must be 0 on ILEV=2")

    def test_nodes_to_surface_is_one_way_ilev3(self):
        """surf_ID1 = 0, surf_ID2 = main surface, grnd_IDs = secondary nodes.
        That is starter ILEV=3 (hm_read_inter_type25.F:399-434) — a genuine
        one-way contact, which is what dyna2rad produces for this family too."""
        _, starter = _convert(_MESH + _eroding(
            "CONTACT_ERODING_NODES_TO_SURFACE", 500, 1, 4, 3) + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[0][0:10], "         0", "surf_ID1 must be 0")
        surf2 = int(cards[0][10:20])
        grnod = int(cards[1][0:10])
        self.assertIn(f"/SURF/PART/ALL/{surf2}", starter)
        self.assertIn(f"/GRNOD/NODE/{grnod}", starter)
        # the four *SET_NODE_LIST nodes, and nothing from the main side
        grp = _block(starter, f"/GRNOD/NODE/{grnod}")
        self.assertEqual(grp[2], "        13        14        15        16")

    def test_single_surface_is_self_impact(self):
        _, starter = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SINGLE_SURFACE", 1, 0, 3, 0) + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        surf1 = int(cards[0][0:10])
        self.assertIn(f"/SURF/PART/ALL/{surf1}", starter)
        self.assertEqual(cards[0][10:20], "         0", "surf_ID2 must be 0")

    def test_idel_is_2_any_quorum(self):
        """Idel=2 removes the segment as soon as ONE attached element dies —
        LS-DYNA's own per-element face removal, and the engine's own split
        (check_surface_state.F:155-171). dyna2rad copies its non-eroding
        default of 1 (ALL-quorum) instead."""
        _, starter = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3) + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[0][70:80], "         2")

    def test_birth_and_death_times_are_carried(self):
        deck = _MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
            card2=_card2(bt="     0.001", dt="      0.05")) + _TERM
        _, starter = _convert(deck)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[3][60:80], f"{0.001:>20.10G}")
        self.assertEqual(cards[3][80:100], f"{0.05:>20.10G}")

    def test_blank_death_time_becomes_zero_not_1e20(self):
        """A blank DT parses as 1e20; TYPE25 turns a Tstop of 0 back into EP30
        (hm_read_inter_type25.F:579), so 0 is the honest 'no death time'."""
        _, starter = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3) + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[3][80:100], "                   0")

    def test_vdc_maps_to_viss_else_the_radioss_default(self):
        _, plain = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3) + _TERM)
        self.assertEqual(_cards(_block(plain, "/INTER/TYPE25/90001"))[4][40:60],
                         f"{0.05:>20.10G}")
        _, damped = _convert(_MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
            card2=_card2(vdc="      20.0")) + _TERM)
        self.assertEqual(_cards(_block(damped, "/INTER/TYPE25/90001"))[4][40:60],
                         f"{0.2:>20.10G}")

    def test_stfac_is_min_sfs_sfm(self):
        """dyna2rad convertcontacts.cxx:459-464 — Stfac = min(SFS, SFM) after
        blank/0 has been reset to 1.0 (:410-414)."""
        card3 = ("       0.3       0.7       0.0       0.0"
                 "       1.0       1.0       1.0       1.0\n")
        deck = (_MESH + "*CONTACT_ERODING_SURFACE_TO_SURFACE\n"
                "         2         1         3         3         0         0         0         0\n"
                + _card2() + card3 + "         0         1         1\n" + _TERM)
        _, starter = _convert(deck)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[3][0:20], f"{0.3:>20.10G}")

    def test_sst_mst_is_reported_as_inexpressible(self):
        card3 = ("       1.0       1.0       0.5       0.5"
                 "       1.0       1.0       1.0       1.0\n")
        deck = (_MESH + "*CONTACT_ERODING_SURFACE_TO_SURFACE\n"
                "         2         1         3         3         0         0         0         0\n"
                + _card2() + card3 + "         0         1         1\n" + _TERM)
        result, _ = _convert(deck)
        self.assertTrue(any("no Gapmin column" in w for w in result.warnings))


class Type25IstfTests(unittest.TestCase):
    """dyna2rad splits the families across two SOFT branches
    (convertcontacts.cxx:583-613 vs :614-628); the asymmetry at SOFT=2 is
    undocumented but it IS the reference behaviour."""

    class _C:
        def __init__(self, keyword, soft):
            self.keyword, self.soft, self.inter_id = keyword, soft, 1

    def _istf(self, keyword, soft):
        return _type25_istf_iedge(ConversionState(), self._C(keyword, soft))

    def test_full_soft_rule_families(self):
        for kw in ("CONTACT_ERODING_SURFACE_TO_SURFACE",
                   "CONTACT_AUTOMATIC_NODES_TO_SURFACE"):
            self.assertEqual(self._istf(kw, 0), (2, 1000), kw)
            self.assertEqual(self._istf(kw, 1), (4, 1000), kw)
            self.assertEqual(self._istf(kw, 2), (2, 22), kw)

    def test_coarse_soft_rule_families(self):
        for kw in ("CONTACT_ERODING_SINGLE_SURFACE",
                   "CONTACT_ERODING_NODES_TO_SURFACE",
                   "CONTACT_NODES_TO_SURFACE"):
            self.assertEqual(self._istf(kw, 0), (2, 1000), kw)
            self.assertEqual(self._istf(kw, 1), (4, 1000), kw)
            self.assertEqual(self._istf(kw, 2), (4, 1000), kw)

    def test_mpp_spelling_takes_the_same_branch(self):
        self.assertEqual(
            self._istf("CONTACT_ERODING_SURFACE_TO_SURFACE_MPP", 2), (2, 22))


# ═══════════════════════════════════════════════════════════════════════════
# The /SURF flavour — the batch's defining decision
# ═══════════════════════════════════════════════════════════════════════════

class ErodingSurfaceTests(unittest.TestCase):
    S2S = _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3)

    def test_eroding_solid_side_uses_surf_part_all(self):
        _, starter = _convert(_MESH + self.S2S + _TERM)
        self.assertIn("/SURF/PART/ALL/", starter)
        self.assertNotIn("/SURF/PART/EXT/", starter)

    def test_non_eroding_n2s_keeps_surf_part_ext(self):
        _, starter = _convert(
            _MESH + _n2s("CONTACT_AUTOMATIC_NODES_TO_SURFACE", 500, 1, 4, 3)
            + _TERM)
        self.assertIn("/SURF/PART/EXT/", starter)
        self.assertNotIn("/SURF/PART/ALL/", starter)

    def test_opt_out_falls_back_to_ext_and_says_what_it_costs(self):
        result, starter = _convert(_MESH + self.S2S + _TERM,
                                   eroding_surf_ext=True)
        self.assertNotIn("/SURF/PART/ALL/", starter)
        self.assertIn("/SURF/PART/EXT/", starter)
        self.assertTrue(any("--eroding-surf-ext" in w and "CANNOT re-expose" in w
                            for w in result.warnings))

    def test_quadratic_solids_fall_back_to_ext_with_a_warning(self):
        """2022 Reference Guide p.372: with quadratic solids /SURF/PART/EXT is
        recommended, because only then do the mid-side nodes take part in the
        contact treatment."""
        tet10 = _MESH.replace(
            "*ELEMENT_SOLID\n"
            "       1       1       1       2       3       4       5       6       7       8\n"
            "       2       1       5       6       7       8       9      10      11      12\n",
            "*ELEMENT_SOLID\n"
            "       1       1\n"
            "       1       2       3       5       6       7       8       9      10      11\n")
        result, starter = _convert(tet10 + self.S2S + _TERM)
        self.assertNotIn("/SURF/PART/ALL/", starter)
        self.assertTrue(any("QUADRATIC" in w for w in result.warnings))

    def test_surf_part_all_body_lists_the_solid_parts(self):
        _, starter = _convert(_MESH + self.S2S + _TERM)
        header = next(ln for ln in starter.splitlines()
                      if ln.startswith("/SURF/PART/ALL/"))
        blk = _block(starter, header)
        self.assertEqual(blk[2], "         1")

    def test_shell_only_side_is_unaffected_by_the_all_choice(self):
        """Shells go through /GRSHEL/SHEL either way — /ALL vs /EXT is a
        solid-face concept (ssurftag.F:122 masks shared SOLID faces)."""
        _, starter = _convert(_MESH + self.S2S + _TERM)
        self.assertIn("/SURF/GRSHEL/", starter)


# ═══════════════════════════════════════════════════════════════════════════
# *DEFINE_FRICTION -> /FRICTION
# ═══════════════════════════════════════════════════════════════════════════

class DefineFrictionParseTests(unittest.TestCase):
    def test_card1_and_pair_rows(self):
        st = _dispatch(_MESH + FRICTION_7 + _TERM)
        f = st.define_frictions[7]
        self.assertEqual((f.fs, f.fd, f.dc, f.vc, f.icnep),
                         (0.4, 0.2, 1.5, 0.0, 0))
        self.assertEqual(len(f.pairs), 1)
        p = f.pairs[0]
        self.assertEqual((p.pid_i, p.pid_j, p.fs, p.fd, p.dc), (1, 2, 0.5, 0.3, 2.0))
        self.assertFalse(p.pset_i or p.pset_j)

    def test_ptype_pset_column(self):
        st = _dispatch(
            _MESH
            + "*DEFINE_FRICTION\n"
              "         7       0.4       0.2       0.0       0.0\n"
              "       800       900       0.5       0.3       0.0       0.0      PSET      PSET\n"
            + _TERM)
        p = st.define_frictions[7].pairs[0]
        self.assertTrue(p.pset_i and p.pset_j)

    def test_title_spelling(self):
        st = _dispatch(
            _MESH
            + "*DEFINE_FRICTION_TITLE\nsteel on steel\n"
              "         7       0.4       0.2       0.0       0.0\n"
            + _TERM)
        self.assertEqual(st.define_frictions[7].title, "steel on steel")
        self.assertEqual(st.define_frictions[7].fs, 0.4)


class FrictionCoefficientTests(unittest.TestCase):
    """LS-DYNA mu = FD + (FS-FD)*exp(-DC*|v|)  ==  Radioss Ifric=2 (Darmstad)
    Fric + C5*exp(C6*v) with C1..C4 = 0 — engine i7for3.F:1911-1914."""

    def test_mapping_is_exact(self):
        self.assertEqual(_friction_coeffs(0.4, 0.2, 1.5), (0.2, 0.2, -1.5))

    def test_zero_decay_leaves_c6_at_zero(self):
        """With C6=0 the decay term is the constant C5, so mu = FD + (FS-FD)
        = FS at every speed — exactly what the LS-DYNA law degenerates to."""
        self.assertEqual(_friction_coeffs(0.4, 0.2, 0.0), (0.2, 0.2, 0.0))

    def test_static_equals_dynamic_collapses_to_coulomb(self):
        self.assertEqual(_friction_coeffs(0.3, 0.3, 5.0), (0.3, 0.0, -5.0))


class FrictionCardTests(unittest.TestCase):
    DECK = (_MESH + FRICTION_7
            + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
                       card2=_card2(fs="      -2.0", fd="       7.0"))
            + _TERM)

    def test_card_lines_are_column_exact(self):
        _, starter = _convert(self.DECK)
        cards = _cards(_block(starter, "/FRICTION/7"))
        # Ifric=2 (Darmstad), Ifiltr=0, Xfreq=0, Iform=2
        self.assertEqual(cards[0],
                         "         2         0                   0         2")
        # C1..C5: only C5 = FS_D - FD_D = 0.2
        self.assertEqual(cards[1], "                   0" * 4 + f"{0.2:>20.10G}")
        # C6 = -DC_D = -1.5, FRIC = FD_D = 0.2, VIS_f = VC_D = 0
        self.assertEqual(cards[2],
                         f"{-1.5:>20.10G}{0.2:>20.10G}" + "                   0")
        # pair row: grpart1 grpart2 part1 part2 <10 blanks> Idir
        self.assertEqual(cards[3],
                         "         0         0         1         2"
                         "                    0")
        self.assertEqual(cards[4], "                   0" * 4 + f"{0.2:>20.10G}")
        self.assertEqual(cards[5],
                         f"{-2.0:>20.10G}{0.3:>20.10G}" + "                   0")

    def test_friction_id_is_preserved(self):
        _, starter = _convert(self.DECK)
        self.assertIn("/FRICTION/7\n", starter)

    def test_pset_row_gets_a_grpart(self):
        deck = (_MESH
                + "*SET_PART_LIST\n       800\n         1         2\n"
                + "*DEFINE_FRICTION\n"
                  "         7       0.4       0.2       0.0       0.0\n"
                  "       800       800       0.5       0.3       0.0       0.0      PSET      PSET\n"
                + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
                           card2=_card2(fs="      -2.0", fd="       7.0"))
                + _TERM)
        _, starter = _convert(deck)
        header = next(ln for ln in starter.splitlines()
                      if ln.startswith("/GRPART/PART/"))
        gid = int(header.rsplit("/", 1)[1])
        self.assertEqual(_block(starter, header)[2], "         1         2")
        row = _cards(_block(starter, "/FRICTION/7"))[3]
        self.assertEqual(row[0:20], f"{gid:>10d}{gid:>10d}")
        self.assertEqual(row[20:40], "         0         0")

    def test_unknown_part_row_is_dropped_with_a_warning(self):
        deck = (_MESH
                + "*DEFINE_FRICTION\n"
                  "         7       0.4       0.2       0.0       0.0\n"
                  "         1       999       0.5       0.3       0.0       0.0\n"
                + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
                           card2=_card2(fs="      -2.0", fd="       7.0"))
                + _TERM)
        result, starter = _convert(deck)
        self.assertEqual(len(_cards(_block(starter, "/FRICTION/7"))), 3)
        self.assertTrue(any("part 999, which does not exist" in w
                            for w in result.warnings))

    def test_vc_column_is_flagged_as_a_different_quantity(self):
        deck = (_MESH
                + "*DEFINE_FRICTION\n"
                  "         7       0.4       0.2       0.0     150.0\n"
                + _TERM)
        result, _ = _convert(deck)
        self.assertTrue(any("STRESS CAP" in w for w in result.warnings))


class FrictionBindingTests(unittest.TestCase):
    """*CONTACT Card-2 FS = -2 -> fric_ID on the interface, cols 91-100 of
    card 6 (radioss2020 TYPE7 / radioss2022 TYPE25)."""

    def _s2s_fs(self, fs, fd="       0.0"):
        return _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
                        card2=_card2(fs=fs, fd=fd))

    def test_single_table_binds_regardless_of_fd(self):
        result, starter = _convert(_MESH + FRICTION_7
                                   + self._s2s_fs("      -2.0", "       0.0")
                                   + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[5][90:100], "         7")
        self.assertEqual(cards[3][20:40], "                   0",
                         "Fric must be 0 while fric_ID is set")
        self.assertTrue(any("exactly one *DEFINE_FRICTION" in w
                            for w in result.warnings))

    def test_two_tables_bind_by_the_fd_column(self):
        second = ("*DEFINE_FRICTION\n"
                  "         9       0.1       0.1       0.0       0.0\n")
        _, starter = _convert(_MESH + FRICTION_7 + second
                              + self._s2s_fs("      -2.0", "       9.0") + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[5][90:100], "         9")

    def test_two_tables_no_match_zeroes_friction_and_warns(self):
        second = ("*DEFINE_FRICTION\n"
                  "         9       0.1       0.1       0.0       0.0\n")
        result, starter = _convert(_MESH + FRICTION_7 + second
                                   + self._s2s_fs("      -2.0", "      77.0")
                                   + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[5][90:100], "         0")
        self.assertTrue(any("matches none of the" in w for w in result.warnings))

    def test_no_table_at_all_warns(self):
        result, starter = _convert(_MESH + self._s2s_fs("      -2.0") + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE25/90001"))
        self.assertEqual(cards[5][90:100], "         0")
        self.assertTrue(any("the deck defines NONE" in w for w in result.warnings))

    def test_type7_contact_binds_too(self):
        """The FS=-2 binding is not TYPE25-only: an ordinary
        *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE converts to /INTER/TYPE7, whose
        radioss2020 card 6 carries fric_ID in the same cols 91-100."""
        s2s = ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
               "         2         1         3         3\n"
               + _card2(fs="      -2.0", fd="       7.0") + _CARD3)
        _, starter = _convert(_MESH + FRICTION_7 + s2s + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE7/90001"))
        self.assertEqual(cards[5][90:100], "         7")

    def test_tied_contact_says_it_cannot_hold_the_binding(self):
        """/INTER/TYPE2 has no friction model, and neither TYPE11's nor
        TYPE19's newest FORMAT at 2022 reaches a fric_ID column."""
        tied = ("*CONTACT_TIED_NODES_TO_SURFACE\n"
                "       500         1         4         3\n"
                + _card2(fs="      -2.0") + _CARD3)
        result, _ = _convert(_MESH + FRICTION_7 + tied + _TERM)
        self.assertTrue(any("NO fric_ID column" in w and "TYPE2" in w
                            for w in result.warnings))

    def test_bind_helper_rejects_unsupported_targets(self):
        st = ConversionState()
        for target in ("TYPE2", "TYPE10", "TYPE11", "TYPE19"):
            self.assertEqual(_bind_friction_table(st, 0.0, 1, "CONTACT", target), 0)


class FsSentinelTests(unittest.TestCase):
    def test_fs_minus_one_no_longer_writes_a_negative_coefficient(self):
        """FS=-1 means 'use the *PART_CONTACT coefficients'. It used to flow
        through literally as Fric=-1 — a negative Coulomb coefficient."""
        s2s = ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
               "         2         1         3         3\n"
               + _card2(fs="      -1.0", fd="       0.3") + _CARD3)
        result, starter = _convert(_MESH + s2s + _TERM)
        cards = _cards(_block(starter, "/INTER/TYPE7/90001"))
        self.assertEqual(cards[3][20:40], "                   0")
        self.assertNotIn("                  -1", cards[3])
        self.assertTrue(any("*PART_CONTACT" in w for w in result.warnings))

    def test_ordinary_fs_is_untouched(self):
        fric, fric_id = _contact_friction(ConversionState(), 0.3, 0.1, 1,
                                          "CONTACT", "TYPE7")
        self.assertEqual((fric, fric_id), (0.3, 0))

    def test_fs_two_only_warns_when_a_matching_define_table_exists(self):
        st = ConversionState()
        self.assertEqual(_contact_friction(st, 2.0, 5.0, 1, "C", "TYPE7"), (2.0, 0))
        self.assertEqual(st.warnings, [])
        st.define_tables[5] = object()
        self.assertEqual(_contact_friction(st, 2.0, 5.0, 1, "C", "TYPE7"), (2.0, 0))
        self.assertTrue(any("*DEFINE_TABLE" in w for w in st.warnings))

    def test_fsf_scales_the_coulomb_coefficient(self):
        fric, _ = _contact_friction(ConversionState(), 0.4, 0.0, 1, "C",
                                    "TYPE25", fsf=0.5)
        self.assertAlmostEqual(fric, 0.2)

    def test_dc_without_a_table_is_reported(self):
        deck = _MESH + _eroding(
            "CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3,
            card2=_card2(fs="       0.4", fd="       0.2", dc="       1.5")) + _TERM
        result, _ = _convert(deck)
        self.assertTrue(any("exponential static" in w for w in result.warnings))


# ═══════════════════════════════════════════════════════════════════════════
# Integration: drops, /TH/INTER, parent selection
# ═══════════════════════════════════════════════════════════════════════════

class IntegrationTests(unittest.TestCase):
    def test_unresolvable_side_is_dropped_loudly_and_accounted(self):
        result, starter = _convert(
            _MESH + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 999, 3, 3)
            + _TERM)
        self.assertNotIn("/INTER/TYPE25/", starter)
        self.assertTrue(any("NO /INTER was emitted" in w for w in result.warnings))
        self.assertTrue(any(kw.startswith("CONTACT_ERODING")
                            for kw, _ in result.recognized_not_emitted))

    def test_th_inter_lists_the_new_interfaces(self):
        deck = (_MESH + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 1, 3, 3)
                + "*DATABASE_RCFORC\n     0.001\n" + _TERM)
        _, starter = _convert(deck)
        header = next(ln for ln in starter.splitlines()
                      if ln.startswith("/TH/INTER/"))
        self.assertIn("     90001", _block(starter, header))

    def test_th_inter_omits_a_dropped_new_interface(self):
        deck = (_MESH + _eroding("CONTACT_ERODING_SURFACE_TO_SURFACE", 2, 999, 3, 3)
                + "*DATABASE_RCFORC\n     0.001\n" + _TERM)
        _, starter = _convert(deck)
        self.assertNotIn("/TH/INTER", starter)

    def test_force_transducer_never_parents_on_a_dropped_interface(self):
        """_select_parent_interface / _match_parent_interface must filter
        state.dropped_inter_ids: /INTER/SUB pointing at an interface that was
        never written is starter ERROR 581."""
        deck = (_MESH
                # dropped: the secondary side is a part that does not exist
                + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
                  "       777         1         3         3\n"
                + _card2() + _CARD3
                # emitted
                + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
                  "         2         1         3         3\n"
                + _card2() + _CARD3
                + "*CONTACT_FORCE_TRANSDUCER_PENALTY\n"
                  "         2         1         3         3\n"
                + _TERM)
        _, starter = _convert(deck)
        emitted = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                   if ln.startswith("/INTER/TYPE7/")}
        sub = _cards(_block(starter, "/INTER/SUB/90003"))[0]
        self.assertIn(int(sub[0:10]), emitted)


class ByteIdentityTests(unittest.TestCase):
    """A deck with none of the batch's keywords must convert exactly as before
    — the whole corpus sweep rests on that."""

    PLAIN = (_MESH
             + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
               "         2         1         3         3\n"
             + _card2(fs="       0.2", fd="       0.1") + _CARD3
             + _TERM)

    def test_plain_contact_deck_has_no_new_output(self):
        result, starter = _convert(self.PLAIN)
        for absent in ("/INTER/TYPE25/", "/FRICTION/", "/SURF/PART/ALL/",
                       "/GRPART/PART/", "ERODING / NODE-TO-SURFACE"):
            self.assertNotIn(absent, starter)
        for needle in ("fric_ID", "eroding", "EROSOP", "IADJ"):
            self.assertFalse(any(needle in w for w in result.warnings),
                             f"unexpected {needle!r} warning on a plain deck")

    def test_type7_card6_is_unchanged_without_a_friction_table(self):
        """The three trailing columns (fct_IDF / AscaleF / fric_ID) are only
        written when a table is actually bound, so every pre-existing deck's
        /INTER/TYPE7 stays byte-identical."""
        _, starter = _convert(self.PLAIN)
        blk = _block(starter, "/INTER/TYPE7/90001")
        self.assertIn("#    Ifric    Ifiltr               Xfreq     Iform   sens_ID",
                      blk)
        self.assertIn("         0         0                   0         2         0", blk)

    def test_emitters_are_byte_identical_at_fric_id_zero(self):
        self.assertEqual(_emit_inter_type7(1, "T", 2, 3, 0.2),
                         _emit_inter_type7(1, "T", 2, 3, 0.2, fric_id=0))
        self.assertEqual(_emit_inter_type25_self(1, "T", 5, 0.2)[-2],
                         "         0         0                   0"
                         "                   0                   0"
                         "                   0")

    def test_self_contact_path_still_emits_type25_self(self):
        deck = (_MESH + "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                "         0         0         0         0\n"
                + _card2(fs="       0.2") + _CARD3 + _TERM)
        _, starter = _convert(deck)
        self.assertIn("/INTER/TYPE25/90001", starter)
        self.assertIn("/SURF/PART/EXT/", starter)
        self.assertNotIn("/SURF/PART/ALL/", starter)


if __name__ == "__main__":
    unittest.main()
