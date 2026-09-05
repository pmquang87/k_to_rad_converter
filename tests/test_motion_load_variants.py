"""Tests for the prescribed-motion and body/pressure load VARIANTS:

  *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL -> /IMPVEL|/IMPACC|/IMPDISP + /SKEW/MOV
  *BOUNDARY_PRESCRIBED_MOTION_SET_BOX     -> the _SET path scoped by *DEFINE_BOX
  *LOAD_SHELL_ELEMENT / _SET              -> /SURF/SEG + /PLOAD (+ /SENSOR/TIME)
  *LOAD_BODY_VECTOR                       -> /GRAV + /SKEW/FIX
  *LOAD_BODY_RX/_RY/_RZ                   -> /LOAD/CENTRI (+ /FRAME/FIX)

Five things decide whether these convert correctly, and none of them is visible
by eye in the .rad:

* the PRESSURE SIGN. LS-DYNA's *LOAD_SHELL pressure is positive "in the negative
  t-direction" (Manual Vol I R16 p.3421 — t is the shell's right-hand-rule
  normal), while a Radioss /PLOAD with a positive ``Fscale_y`` pushes the surface
  along its POSITIVE segment normal ``n = N1N3 x N2N4`` (Altair help /PLOAD
  Comment 1; ``force.F90:451-465`` sums ``+P*A*n_hat`` over the segment's nodes).
  k2rad pastes the shell connectivity into /SURF/SEG, so n_hat = t_hat and
  exactly ONE flip is right. Doing both — flipping AND reversing the node order —
  cancels back to the wrong sign, which is the classic trap here.
* the CENTRIFUGAL CURVE SEMANTICS. *LOAD_BODY_R*'s LCID carries the ANGULAR
  VELOCITY omega(t), and the OpenRadioss engine squares it for itself
  (``cfield.F:121,128``: ``VROT = Fscaley*f(t*1/Ascalex)`` then
  ``VROT2 = VROT*VROT``, ``AREL = r_perp*VROT2``). LS-DYNA does the same
  internally (``b = rho*[omega x (omega x r)]``, Manual p.33-20 Remark 3). So the
  mapping is 1:1 and LINEAR — a squared or square-rooted Fscaley would be off by
  the value itself and there is nothing in the .rad to notice it by.
* the /LOAD/CENTRI ``Dir`` SPELLING. The starter accepts X/Y/Z and maps them to
  IDIR 1/2/3 (``hm_read_load_centri.F:206-211``), but the engine only branches on
  IDIR 4 and 5 — 1/2/3 all fall into the ``ELSE`` and rotate about the FRAME'S Z
  AXIS, with no error and no warning (measured). Only XX/YY/ZZ is safe. The
  Radioss dyna-reader writes X/Y/Z (``convertloads.cxx:271-288``) and is
  therefore wrong for RX and RY, right for RZ by accident.
* the *LOAD_BODY_VECTOR SIGN + SKEW PAIR. /GRAV adds ``+Fscale_Y*f(t)`` along the
  skew's DIR axis (``gravit.F:147``), and LS-DYNA's body force acts along -V
  (p.33-29: the manual's own example writes V = (-1,-1,-1) to get gravity along
  +(1,1,1)). So ``Fscale_Y = -SF`` AND the skew's local X' = +V. Reproducing one
  without the other flips the load, and both are invisible individually.
* the /SKEW/MOV BINDING for _RIGID_LOCAL. The moving system must go in the
  ``skew_ID`` column, never ``frame_ID``: measured under /BEGIN 2022 an /IMPDISP
  carrying ``frame_ID`` echoes ``FRAME 0`` and silently falls back to the global
  axis, because ``radioss120/LOADS/impdisp.cfg`` never populates the attribute
  ``read_impdisp.F:140-142`` reads (the fixing CARD_PREREAD arrived in FORMAT
  radioss2025). /IMPACC has no frame column at all.

The corpus has ZERO decks with any of these five keywords, so nothing here can
be validated by a sweep: the expectations are column-exact card lines built from
the CFG FORMAT blocks plus hand-computed values.

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_gravity.py and tests/test_rwall_variants.py).
"""

import math
import os
import re
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import HANDLERS, dispatch    # noqa: E402
from k2rad.state import ConversionState          # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Deck fragments
#
# Nodes 1-4  = shell 1 (part 1, deformable), in the z = 0 plane, CCW about +Z
# Nodes 5-8  = shell 2 (part 1), in the z = 10 plane
# Nodes 11-18 = the *MAT_RIGID brick (part 2), a 4x4x4 cube at x in [20, 24]
# ─────────────────────────────────────────────────────────────────────────────

HEAD = """\
*KEYWORD
*TITLE
motion / load variants test deck
*CONTROL_TERMINATION
      0.01
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             0.0             0.0            10.0
       6            10.0             0.0            10.0
       7            10.0            10.0            10.0
       8             0.0            10.0            10.0
      11            20.0             0.0             0.0
      12            24.0             0.0             0.0
      13            24.0             4.0             0.0
      14            20.0             4.0             0.0
      15            20.0             0.0             4.0
      16            24.0             0.0             4.0
      17            24.0             4.0             4.0
      18            20.0             4.0             4.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       5       6       7       8
*ELEMENT_SOLID
      11       2      11      12      13      14      15      16      17      18
*PART
shells
       1       1       1
*PART
rigid brick
       2       2       2
*SECTION_SHELL
       1       2
       1.0       1.0       1.0       1.0
*SECTION_SOLID
       2       1
*MAT_ELASTIC
       1   7.85E-9  210000.0       0.3
*MAT_RIGID
       2   7.85E-9  210000.0       0.3
       1.0       7.0       7.0
*DEFINE_CURVE
        10
       0.0       0.0
       1.0       1.0
*DEFINE_CURVE
        20
       0.0       0.0
       1.0       2.0
*SET_NODE_LIST
         1
         1         2         3         4
*SET_SHELL_LIST
        70
         1         2
"""

END = "*END\n"

#: A box that contains nodes 1 and 4 (x <= 5) but not 2 and 3 (x = 10).
BOX_HALF = """\
*DEFINE_BOX
         5      -1.0       5.0      -1.0      11.0      -1.0      11.0
"""

#: *DEFINE_VECTOR 30: tail (0,0,0) -> head (0,0,1), i.e. V = +Z.
VECTOR_Z = """\
*DEFINE_VECTOR
        30       0.0       0.0       0.0       0.0       0.0       1.0
"""

#: *DEFINE_COORDINATE_SYSTEM 40: origin (1,2,3), local x along global +Y,
#: in-plane point on global -X.  ex = (0,1,0), ey = (-1,0,0), ez = (0,0,1).
COORD_40 = """\
*DEFINE_COORDINATE_SYSTEM
        40       1.0       2.0       3.0       1.0       3.0       3.0
       0.0       2.0       3.0
"""


def _convert(deck, **kw):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path, encoding="utf-8") as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _parse(deck):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _deck(*frags):
    return HEAD + "".join(frags) + END


# ─────────────────────────────────────────────────────────────────────────────
# .rad readers
# ─────────────────────────────────────────────────────────────────────────────

def _block(starter, header):
    """The data lines of the /<header>/<id> block, comments stripped, plus the
    id. Returns (block_id, [data lines]) or (None, []) when absent."""
    lines = starter.splitlines()
    pat = re.compile(r"^" + re.escape(header) + r"/(\d+)\s*$")
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if not m:
            continue
        data = []
        for ln2 in lines[i + 2:]:            # skip the mandatory title line
            if ln2.startswith("/") or ln2.startswith("#-"):
                break
            if ln2.startswith("#"):
                continue
            data.append(ln2)
        return int(m.group(1)), data
    return None, []


def _blocks(starter, header):
    """Every /<header>/<id> block in the deck, as [(id, [data lines])]."""
    lines = starter.splitlines()
    pat = re.compile(r"^" + re.escape(header) + r"/(\d+)\s*$")
    out = []
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if not m:
            continue
        data = []
        for ln2 in lines[i + 2:]:
            if ln2.startswith("/") or ln2.startswith("#-"):
                break
            if ln2.startswith("#"):
                continue
            data.append(ln2)
        out.append((int(m.group(1)), data))
    return out


def _fields(line, w=10, n=None):
    """Slice a fixed-format .rad line into w-wide fields (stripped)."""
    out = [line[i:i + w].strip() for i in range(0, len(line), w)]
    if n is not None:
        out = (out + [""] * n)[:n]
    return out


def _pload_card(starter, pload_id):
    """(surf_ID, functIDT, sensor_ID, Ascale_x, Fscale_y) of one /PLOAD, read
    from the COLUMNS the radioss2021 FORMAT specifies rather than by splitting
    on whitespace: cols 1-10/11-20/21-30, 31-60 blank, 61-80, 81-100."""
    for pid, data in _blocks(starter, "/PLOAD"):
        if pid != pload_id:
            continue
        ln = data[0]
        assert len(ln) == 100, f"/PLOAD card is {len(ln)} cols, expected 100"
        assert ln[30:60].strip() == "", (
            "/PLOAD cols 31-60 must stay blank (col 51-60 is the 2023-only "
            f"Itypfun: WARNING 100214 under /BEGIN 2022) — got {ln[30:60]!r}")
        return (int(ln[0:10]), int(ln[10:20]), int(ln[20:30] or 0),
                float(ln[60:80]), float(ln[80:100]))
    raise AssertionError(f"/PLOAD/{pload_id} not in the deck")


def _centri_card(starter):
    """(id, fct, Dir, frame_ID, sens_ID, grnod_ID, Ivar, Ascalex, Fscaley) of
    the single /LOAD/CENTRI, read by column."""
    out = []
    for cid, data in _blocks(starter, "/LOAD/CENTRI"):
        ln = data[0]
        assert len(ln) == 100, f"/LOAD/CENTRI card is {len(ln)} cols"
        out.append((cid, int(ln[0:10]), ln[10:20].strip(), int(ln[20:30]),
                    int(ln[30:40]), int(ln[40:50]), int(ln[50:60]),
                    float(ln[60:80]), float(ln[80:100])))
    return out


def _grav_card(starter):
    """(id, fct, DIR, skew_ID, sens_ID, grnod_ID, Ascale_x, Fscale_Y) of every
    /GRAV, read by column (cols 51-60 are ten LITERAL blanks on /GRAV)."""
    out = []
    for gid, data in _blocks(starter, "/GRAV"):
        ln = data[0]
        assert len(ln) == 100, f"/GRAV card is {len(ln)} cols"
        assert ln[50:60].strip() == "", (
            "/GRAV cols 51-60 must be blank (that field does not exist on "
            f"/GRAV, unlike /LOAD/CENTRI's Ivar) — got {ln[50:60]!r}")
        out.append((gid, int(ln[0:10]), ln[10:20].strip(), int(ln[20:30]),
                    int(ln[30:40]), int(ln[40:50]),
                    float(ln[60:80]), float(ln[80:100])))
    return out


def _imp_cards(starter):
    """[(keyword, id, fct, Dir, skew_ID, sens_ID, grnod_ID, frame_ID, Icoor,
    Ascale_x, Fscale_Y, Tstart, Tstop)] for every /IMPVEL|/IMPACC|/IMPDISP."""
    out = []
    for kw in ("/IMPVEL", "/IMPACC", "/IMPDISP"):
        for mid, data in _blocks(starter, kw):
            c1, c2 = data[0], data[1]
            f1 = _fields(c1, 10, 7)
            f2 = _fields(c2, 20, 4)
            out.append((kw, mid, int(f1[0]), f1[1], int(f1[2] or 0),
                        int(f1[3] or 0), int(f1[4] or 0), int(f1[5] or 0),
                        int(f1[6] or 0), float(f2[0]), float(f2[1]),
                        float(f2[2]), float(f2[3])))
    return out


def _surf_segs(starter, surf_id):
    """[[n1, n2, n3, n4]] of one /SURF/SEG (n4 = 0 for a triangle). Read by
    column: seg_ID 1-10, n1..n4 at 11-20 / 21-30 / 31-40 / 41-50."""
    for sid, data in _blocks(starter, "/SURF/SEG"):
        if sid != surf_id:
            continue
        return [[int(x or 0) for x in _fields(ln, 10, 5)[1:5]] for ln in data]
    raise AssertionError(f"/SURF/SEG/{surf_id} not in the deck")


def _bcs_cards(starter):
    """[(Tra, Rot, skew_ID, grnod_ID)] of every /BCS. Its data card is
    ``   TTT RRR<skew:I10><grnod:I10>`` — three leading spaces and a space
    between the two 3-char masks, so it is NOT a plain 10-wide grid."""
    out = []
    for _bid, data in _blocks(starter, "/BCS"):
        ln = data[0]
        out.append((ln[3:6], ln[7:10], int(ln[10:20] or 0),
                    int(ln[20:30] or 0)))
    return out


def _grnod_nodes(starter, gid):
    for g, data in _blocks(starter, "/GRNOD/NODE"):
        if g == gid:
            out = []
            for ln in data:
                out += [int(x) for x in _fields(ln) if x]
            return out
    raise AssertionError(f"/GRNOD/NODE/{gid} not in the deck")


def _skew_axes(starter, header, skew_id):
    """(origin, Y', Z', X') of a /SKEW/FIX or /FRAME/FIX, with X' = Y' x Z' the
    way the starter rebuilds it (hm_read_skw.F:448-459)."""
    for sid, data in _blocks(starter, header):
        if sid != skew_id:
            continue
        rows = [tuple(float(x) for x in _fields(ln, 20, 3)) for ln in data[:3]]
        o, y, z = rows
        x = (y[1] * z[2] - y[2] * z[1],
             y[2] * z[0] - y[0] * z[2],
             y[0] * z[1] - y[1] * z[0])
        return o, y, z, x
    raise AssertionError(f"{header}/{skew_id} not in the deck")


def _has_warn(result, *needles):
    return any(all(n in w for n in needles) for w in result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# A) *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL
# ═════════════════════════════════════════════════════════════════════════════

_RIGID_LOCAL = """\
*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL
         2         1         0        10       2.5
"""


class TestRigidLocal(unittest.TestCase):
    def test_dispatch_and_local_flag(self):
        self.assertIn("BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL", HANDLERS)
        st = _parse(_deck(_RIGID_LOCAL))
        self.assertEqual(len(st.prescribed_motions), 1)
        pm = st.prescribed_motions[0]
        self.assertTrue(pm.local)
        self.assertEqual((pm.pid, pm.dof, pm.vad, pm.lcid, pm.sf),
                         (2, 1, 0, 10, 2.5))
        # plain _RIGID must NOT set the flag
        st2 = _parse(_deck(_RIGID_LOCAL.replace("_RIGID_LOCAL", "_RIGID")))
        self.assertFalse(st2.prescribed_motions[0].local)

    def test_id_suffix_needs_no_registry_key(self):
        """_LOCAL_ID is stripped to _LOCAL by parser._split_keyword, so it needs
        no key of its own — but _LOCAL itself does (like *DEFINE_BOX_LOCAL)."""
        self.assertNotIn("BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL_ID", HANDLERS)
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL_ID\n"
                     "         7local motion\n"
                     "         2         1         0        10       2.5\n")
        st = _parse(deck)
        self.assertEqual(len(st.prescribed_motions), 1)
        self.assertTrue(st.prescribed_motions[0].local)

    def test_emits_corotating_skew_mov_in_the_skew_column(self):
        result, starter = _convert(_deck(_RIGID_LOCAL))
        skews = _blocks(starter, "/SKEW/MOV")
        self.assertEqual(len(skews), 1, "one co-rotating /SKEW/MOV expected")
        skew_id, data = skews[0]
        n1, n2, n3, dir_ = _fields(data[0], 10, 4)
        self.assertEqual(dir_, "X", "N1->N2 must be the local X' axis")
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        kw, _mid, fct, d, skew_col, sens, _grnod, frame, icoor = imps[0][:9]
        self.assertEqual(kw, "/IMPVEL", "VAD=0 is a velocity")
        self.assertEqual(fct, 10)
        self.assertEqual(d, "X", "DOF=1 is the local x axis of that skew")
        self.assertEqual(skew_col, skew_id,
                         "the moving skew belongs in skew_ID (cols 21-30)")
        self.assertEqual((sens, frame, icoor), (0, 0, 0),
                         "frame_ID must stay 0: measured silent drop on "
                         "/IMPDISP under /BEGIN 2022")
        # Fscale_Y is SF verbatim — a prescribed motion is not negated.
        self.assertEqual(imps[0][10], 2.5)

    def test_skew_nodes_are_rigid_secondaries_and_element_free(self):
        result, starter = _convert(_deck(_RIGID_LOCAL))
        skew_id, data = _blocks(starter, "/SKEW/MOV")[0]
        helpers = [int(x) for x in _fields(data[0], 10, 4)[:3]]
        self.assertEqual(len(set(helpers)), 3, "N1/N2/N3 must be distinct")
        # every helper node exists in /NODE ...
        node_ids = set()
        for ln in starter.splitlines():
            m = re.match(r"^\s*(\d+)\s+-?[\d.eE+-]+\s+-?[\d.eE+-]+"
                         r"\s+-?[\d.eE+-]+\s*$", ln)
            if m:
                node_ids.add(int(m.group(1)))
        for h in helpers:
            self.assertIn(h, node_ids, f"helper node {h} is not in /NODE")
        # ... and every one is a secondary of the brick's /RBODY
        rb_group = None
        for gid, gdata in _blocks(starter, "/GRNOD/NODE"):
            flat = []
            for ln in gdata:
                flat += [int(x) for x in _fields(ln) if x]
            if {11, 12, 13, 14, 15, 16, 17, 18} <= set(flat):
                rb_group = set(flat)
        self.assertIsNotNone(rb_group, "the /RBODY secondary group is missing")
        for h in helpers:
            self.assertIn(h, rb_group,
                          f"helper node {h} must ride the rigid body")
        # they carry no element: no *ELEMENT references them
        for e in ("/SHELL", "/BRICK", "/SH3N", "/TETRA4"):
            for _eid, edata in _blocks(starter, e):
                for ln in edata:
                    self.assertFalse(set(int(x) for x in _fields(ln) if x)
                                     & set(helpers),
                                     f"helper node used by a {e} element")

    def test_helper_triad_is_orthogonal_and_mesh_scaled(self):
        """N1->N2 and N1->N3 must be non-collinear (collinear = starter WARNING
        163) and long enough to condition newskw.F's every-cycle rebuild."""
        _result, starter = _convert(_deck(_RIGID_LOCAL))
        _sid, data = _blocks(starter, "/SKEW/MOV")[0]
        h = [int(x) for x in _fields(data[0], 10, 4)[:3]]
        pos = {}
        for ln in starter.splitlines():
            m = re.match(r"^\s*(\d+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)"
                         r"\s+(-?[\d.eE+-]+)\s*$", ln)
            if m and int(m.group(1)) in h:
                pos[int(m.group(1))] = tuple(float(m.group(i))
                                             for i in (2, 3, 4))
        v12 = tuple(pos[h[1]][i] - pos[h[0]][i] for i in range(3))
        v13 = tuple(pos[h[2]][i] - pos[h[0]][i] for i in range(3))
        cross = (v12[1] * v13[2] - v12[2] * v13[1],
                 v12[2] * v13[0] - v12[0] * v13[2],
                 v12[0] * v13[1] - v12[1] * v13[0])
        self.assertGreater(math.sqrt(sum(c * c for c in cross)), 1e-9,
                           "N1->N2 and N1->N3 are collinear")
        # 10% of the brick's 4-unit span
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in v12)), 0.4,
                               places=9)
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in v13)), 0.4,
                               places=9)

    def test_warns_that_the_initial_orientation_is_global(self):
        result, _starter = _convert(_deck(_RIGID_LOCAL))
        self.assertTrue(_has_warn(result, "_RIGID_LOCAL", "CO-ROTATING",
                                  "INITIALISED TO THE GLOBAL AXES",
                                  "PRINCIPAL"),
                        "the approximation must be quantified, not silent")

    def test_two_cards_on_one_body_share_one_skew(self):
        deck = _deck(_RIGID_LOCAL, _RIGID_LOCAL.replace(
            "         2         1         0        10       2.5",
            "         2         3         0        10       1.0"))
        _result, starter = _convert(deck)
        self.assertEqual(len(_blocks(starter, "/SKEW/MOV")), 1)
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 2)
        self.assertEqual({i[3] for i in imps}, {"X", "Z"})
        self.assertEqual({i[4] for i in imps}, {_blocks(starter,
                                                        "/SKEW/MOV")[0][0]})

    def test_plain_rigid_emits_no_moving_skew(self):
        _result, starter = _convert(
            _deck(_RIGID_LOCAL.replace("_RIGID_LOCAL", "_RIGID")))
        self.assertEqual(_blocks(starter, "/SKEW/MOV"), [])
        self.assertEqual(_imp_cards(starter)[0][4], 0)

    def test_cnrb_target_also_gets_a_corotating_skew(self):
        """TYPEID may be a *CONSTRAINED_NODAL_RIGID_BODY PID, whose secondaries
        are ordinary nodes of DEFORMABLE parts — the helper nodes then have to
        join THAT node group, not a *MAT_RIGID part's."""
        deck = _deck(
            "*CONSTRAINED_NODAL_RIGID_BODY\n"
            "        50         0         1\n",
            "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
            "        50         1         0        10       2.5\n")
        _result, starter = _convert(deck)
        skews = _blocks(starter, "/SKEW/MOV")
        self.assertEqual(len(skews), 1)
        helpers = [int(x) for x in _fields(skews[0][1][0], 10, 4)[:3]]
        # the CNRB's secondary group must contain the node set AND the helpers
        found = False
        for _gid, gdata in _blocks(starter, "/GRNOD/NODE"):
            flat = []
            for ln in gdata:
                flat += [int(x) for x in _fields(ln) if x]
            if {1, 2, 3, 4} <= set(flat) and set(helpers) <= set(flat):
                found = True
        self.assertTrue(found, "the helper nodes did not join the CNRB group")
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual(imps[0][4], skews[0][0])

    def test_non_rigid_target_builds_no_triad(self):
        """A motion on a deformable part has no /RBODY to drive, so the writer
        drops it — and no helper nodes must be left attached to nothing."""
        result, starter = _convert(_deck(
            "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
            "         1         1         0        10       2.5\n"))
        self.assertEqual(_blocks(starter, "/SKEW/MOV"), [])
        self.assertEqual(_imp_cards(starter), [])
        self.assertTrue(_has_warn(result, "pid=1", "no RBODY found"))
        self.assertFalse(_has_warn(result, "CO-ROTATING"))


# ═════════════════════════════════════════════════════════════════════════════
# B) *BOUNDARY_PRESCRIBED_MOTION_SET_BOX
# ═════════════════════════════════════════════════════════════════════════════

def _set_box(nsid=1, dof=1, vad=2, lcid=10, sf=1.5, boxid=5, toffset=0,
             lcbchk=0, kw="*BOUNDARY_PRESCRIBED_MOTION_SET_BOX"):
    return (f"{kw}\n"
            f"{nsid:10d}{dof:10d}{vad:10d}{lcid:10d}{sf:10g}\n"
            f"{boxid:10d}{toffset:10d}{lcbchk:10d}\n")


class TestSetBox(unittest.TestCase):
    def test_dispatch_and_box_card(self):
        self.assertIn("BOUNDARY_PRESCRIBED_MOTION_SET_BOX", HANDLERS)
        st = _parse(_deck(BOX_HALF, _set_box(toffset=1, lcbchk=99)))
        self.assertEqual(len(st.prescribed_motion_sets), 1)
        pm = st.prescribed_motion_sets[0]
        self.assertEqual((pm.nsid, pm.dof, pm.vad, pm.lcid, pm.sf), (1, 1, 2, 10, 1.5))
        self.assertEqual((pm.boxid, pm.toffset, pm.lcbchk), (5, 1, 99))

    def test_membership_is_the_set_box_intersection(self):
        """Nodes 1 and 4 are inside the box (x <= 5); 2 and 3 are not."""
        result, starter = _convert(_deck(BOX_HALF, _set_box()))
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual(imps[0][0], "/IMPDISP")
        self.assertEqual(sorted(_grnod_nodes(starter, imps[0][6])), [1, 4])
        self.assertTrue(_has_warn(result, "_SET_BOX", "2 of 4",
                                  "t=0 SNAPSHOT"))

    def test_boxid_zero_falls_back_to_the_plain_set(self):
        result, starter = _convert(_deck(BOX_HALF, _set_box(boxid=0)))
        imps = _imp_cards(starter)
        self.assertEqual(sorted(_grnod_nodes(starter, imps[0][6])),
                         [1, 2, 3, 4])
        self.assertTrue(_has_warn(result, "no BOXID", "WHOLE node set"))

    def test_nsid_zero_uses_the_box_alone(self):
        result, starter = _convert(_deck(BOX_HALF, _set_box(nsid=0)))
        imps = _imp_cards(starter)
        driven = set(_grnod_nodes(starter, imps[0][6]))
        # every node with x <= 5: 1, 4, 5, 8 (the rigid brick sits at x >= 20)
        self.assertEqual(driven, {1, 4, 5, 8})
        self.assertTrue(_has_warn(result, "NSID is 0", "box alone"))

    def test_unknown_box_keeps_the_whole_set_and_warns(self):
        result, starter = _convert(_deck(_set_box(boxid=77)))
        imps = _imp_cards(starter)
        self.assertEqual(sorted(_grnod_nodes(starter, imps[0][6])),
                         [1, 2, 3, 4])
        self.assertTrue(_has_warn(result, "no *DEFINE_BOX 77"))

    def test_toffset_and_lcbchk_are_warned_not_silent(self):
        result, _starter = _convert(_deck(BOX_HALF,
                                          _set_box(toffset=1, lcbchk=99)))
        self.assertTrue(_has_warn(result, "TOFFSET", "DROPPED"))
        self.assertTrue(_has_warn(result, "LCBCHK", "DROPPED"))

    def test_empty_intersection_drops_the_motion(self):
        far = ("*DEFINE_BOX\n"
               "         5     100.0     200.0     100.0     200.0"
               "     100.0     200.0\n")
        result, starter = _convert(_deck(far, _set_box()))
        self.assertEqual(_imp_cards(starter), [])
        self.assertTrue(_has_warn(result, "no node of set 1 lies inside"))

    def test_sf_zero_box_row_becomes_a_scoped_bcs(self):
        """The SF=0 -> /BCS idiom must see the INTERSECTED node list too."""
        _result, starter = _convert(_deck(BOX_HALF, _set_box(sf=0.0)))
        target = [c for c in _bcs_cards(starter) if c[0] == "100"]
        self.assertEqual(len(target), 1, "no Tra=100 /BCS emitted")
        self.assertEqual(sorted(_grnod_nodes(starter, target[0][3])), [1, 4])

    def test_two_boxes_on_one_set_do_not_share_a_bcs(self):
        second = ("*DEFINE_BOX\n"
                  "         6      -1.0      11.0      -1.0       5.0"
                  "      -1.0      11.0\n")
        deck = _deck(BOX_HALF, second,
                     _set_box(dof=1, sf=0.0, boxid=5),
                     _set_box(dof=2, sf=0.0, boxid=6))
        _result, starter = _convert(deck)
        groups = [(c[0], sorted(_grnod_nodes(starter, c[3])))
                  for c in _bcs_cards(starter) if c[0] in ("100", "010")]
        self.assertIn(("100", [1, 4]), groups)      # box 5: x <= 5
        self.assertIn(("010", [1, 2]), groups)      # box 6: y <= 5

    def test_unmapped_spellings_stay_unregistered(self):
        """The IGA / line / segment forms are absent from the reader's own cfg
        tree (verified by grep over hm_cfg_files), so they must land in
        skipped_keywords, not be read as a near-alias of _SET."""
        for kw in ("BOUNDARY_PRESCRIBED_MOTION_SET_LINE",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_SEGMENT",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_POINT_UVW",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_EDGE_UVW",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_FACE_XYZ",
                   "BOUNDARY_PRESCRIBED_MOTION_NODE_LOCAL",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_LOCAL"):
            with self.subTest(kw=kw):
                self.assertNotIn(kw, HANDLERS)
                st = _parse(_deck(f"*{kw}\n"
                                  "         1         1         2        10\n"))
                self.assertIn(kw, st.skipped_keywords)
                self.assertEqual(st.prescribed_motion_sets, [])


# ═════════════════════════════════════════════════════════════════════════════
# The shared card walker: VAD gating and the continuation card
# ═════════════════════════════════════════════════════════════════════════════

class TestPrescribedMotionCardWalker(unittest.TestCase):
    def test_continuation_card_is_not_read_as_a_second_motion(self):
        """|DOF| in 9/10/11 takes an extra card OFFSET1 OFFSET2 LRB NODE1 NODE2.
        Read as a card 1, OFFSET1 becomes the node-set id and OFFSET2 the DOF —
        a PHANTOM motion on whatever set OFFSET1 happens to name."""
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1        11         2        10       1.0\n"
                     "       1.0       2.5         0         0         0\n")
        st = _parse(deck)
        self.assertEqual(len(st.prescribed_motion_sets), 1,
                         "the continuation card was parsed as a card 1")
        self.assertEqual(st.prescribed_motion_sets[0].dof, 11)

    def test_vad_4_continuation_card_is_consumed(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
                     "         2         1         4        10       1.0\n"
                     "       0.0       0.0         2        11        12\n")
        st = _parse(deck)
        self.assertEqual(st.prescribed_motions, [],
                         "VAD=4 is refused, and its extra card must not be "
                         "read as another motion")

    def test_box_card_and_continuation_card_together(self):
        deck = _deck(BOX_HALF,
                     "*BOUNDARY_PRESCRIBED_MOTION_SET_BOX\n"
                     "         1        11         2        10       1.0\n"
                     "         5         0         0\n"
                     "       1.0       2.5         0         0         0\n"
                     "         1         1         2        10       1.0\n"
                     "         5         0         0\n")
        st = _parse(deck)
        self.assertEqual(len(st.prescribed_motion_sets), 2)
        self.assertEqual([p.dof for p in st.prescribed_motion_sets], [11, 1])
        self.assertEqual([p.boxid for p in st.prescribed_motion_sets], [5, 5])

    def test_vad_3_and_4_are_refused_with_a_reason(self):
        for vad, needle in ((3, "velocity versus DISPLACEMENT"),
                            (4, "RELATIVE displacement")):
            with self.subTest(vad=vad):
                deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
                             f"         2         1{vad:10d}        10       1.0\n")
                result, starter = _convert(deck)
                self.assertEqual(_imp_cards(starter), [],
                                 f"VAD={vad} must not become an /IMPDISP")
                self.assertTrue(_has_warn(result, f"VAD={vad}", needle,
                                          "NOT converted"))

    def test_vid_binds_the_vector_skew_for_dof_4(self):
        """DOF 4 = translation ALONG *DEFINE_VECTOR VID. k2rad <= PR #116 wrote
        skew_ID = 0, silently turning it into global X."""
        deck = _deck(VECTOR_Z,
                     "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1         4         0        10       1.0"
                     "        30\n")
        _result, starter = _convert(deck)
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual(imps[0][3], "X")
        self.assertEqual(imps[0][4], 30,
                         "the *DEFINE_VECTOR skew must be in skew_ID")
        # and that skew's local X' really is +V = +Z
        _o, _y, _z, x = _skew_axes(starter, "/SKEW/FIX", 30)
        self.assertAlmostEqual(x[0], 0.0, places=12)
        self.assertAlmostEqual(x[1], 0.0, places=12)
        self.assertAlmostEqual(x[2], 1.0, places=12)

    def test_dof_8_binds_the_vector_skew_as_a_rotation(self):
        deck = _deck(VECTOR_Z,
                     "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1         8         0        10       1.0"
                     "        30\n")
        _result, starter = _convert(deck)
        imps = _imp_cards(starter)
        self.assertEqual((imps[0][3], imps[0][4]), ("XX", 30))

    def test_missing_vid_on_dof_4_is_warned(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1         4         0        10       1.0\n")
        result, starter = _convert(deck)
        self.assertEqual(_imp_cards(starter)[0][4], 0)
        self.assertTrue(_has_warn(result, "DOF=4", "VID is 0", "GLOBAL"))

    def test_negative_dof_4_locks_the_two_transverse_axes(self):
        """The lock must use a synthesized FLAT-ZERO /FUNCT at Fscale_Y = 1, not
        the real curve at Fscale_Y = 0: ``read_impvel.F:248`` replaces a zero
        ordinate scale with the unit-system factor, so the zero-scale form
        echoes FSCALE 1.0 on a live starter run and drives the transverse axes
        at FULL scale — the opposite of locking them."""
        deck = _deck(VECTOR_Z,
                     "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1        -4         0        10       2.0"
                     "        30\n")
        result, starter = _convert(deck)
        imps = sorted(_imp_cards(starter), key=lambda r: r[3])
        self.assertEqual([i[3] for i in imps], ["X", "Y", "Z"])
        by_dir = {i[3]: (i[2], i[10]) for i in imps}
        self.assertEqual(by_dir["X"], (10, 2.0), "the driven axis keeps SF")
        # both locked axes: a DIFFERENT curve, at a NON-zero scale
        zero_fcts = {by_dir["Y"][0], by_dir["Z"][0]}
        self.assertEqual(len(zero_fcts), 1, "one shared flat-zero curve")
        zero_fct = zero_fcts.pop()
        self.assertNotEqual(zero_fct, 10)
        self.assertEqual(by_dir["Y"][1], 1.0)
        self.assertEqual(by_dir["Z"][1], 1.0)
        # and that curve really is flat zero
        pts = []
        for _f, fdata in _blocks(starter, "/FUNCT"):
            if _f == zero_fct:
                pts = [tuple(float(x) for x in _fields(ln, 20, 2))
                       for ln in fdata]
        self.assertEqual(pts, [(0.0, 0.0), (1.0, 0.0)])
        self.assertEqual({i[4] for i in imps}, {30})
        self.assertTrue(_has_warn(result, "DOF=-4", "FORBIDS",
                                  "read_impvel.F:248"))

    def test_dof_12_emits_nothing(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1        12         2        10       1.0\n")
        result, starter = _convert(deck)
        self.assertEqual(_imp_cards(starter), [])
        self.assertTrue(_has_warn(result, "DOF=12", "no /IMP* Dir equivalent"))


# ═════════════════════════════════════════════════════════════════════════════
# C) *LOAD_SHELL_ELEMENT / _SET -> /PLOAD
# ═════════════════════════════════════════════════════════════════════════════

class TestLoadShell(unittest.TestCase):
    def test_dispatch(self):
        for kw in ("LOAD_SHELL_ELEMENT", "LOAD_SHELL_SET"):
            self.assertIn(kw, HANDLERS)
        st = _parse(_deck("*LOAD_SHELL_ELEMENT\n"
                          "         1        10       2.5     0.003\n"))
        self.assertEqual(len(st.shell_pressure_loads), 1)
        spl = st.shell_pressure_loads[0]
        self.assertEqual((spl.eids, spl.lcid, spl.sf, spl.at),
                         ([1], 10, 2.5, 0.003))

    def test_sf_defaults_to_one_when_blank(self):
        """load_shell.cfg gives ``magnitude`` no default, so a blank SF reads as
        0.0 — dyna2rad has no guard and would emit a zero load. LS-DYNA's
        default is 1.0."""
        st = _parse(_deck("*LOAD_SHELL_SET\n"
                          "        70        10\n"))
        self.assertEqual(st.shell_pressure_loads[0].sf, 1.0)

    def test_pressure_sign_is_exactly_one_flip(self):
        """Fscale_y = -SF, and the /SURF/SEG keeps the shell's node ORDER. Two
        flips would cancel back to the wrong direction."""
        _result, starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                          "         1        10       2.5\n"))
        surf, fct, sens, ascale, fscale = _pload_card(starter, 1)
        self.assertEqual(fct, 10)
        self.assertEqual(sens, 0, "AT = 0 needs no sensor")
        self.assertEqual(ascale, 1.0, "LS-DYNA never scales the time abscissa")
        self.assertEqual(fscale, -2.5, "Fscale_y must be -SF")
        # the segment is the shell connectivity, verbatim and UNREVERSED
        self.assertEqual(_surf_segs(starter, surf), [[1, 2, 3, 4]])

    def test_sign_flip_is_warned_with_its_authority(self):
        result, _starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                          "         1        10       2.5\n"))
        self.assertTrue(_has_warn(result, "Fscale_y = -SF",
                                  "negative t-direction", "force.F90"))

    def test_load_segment_sign_IS_flipped(self):
        """REPLACES ``test_load_segment_sign_is_NOT_flipped``, whose premise —
        "*LOAD_SEGMENT states an explicitly ORIENTED segment, so its scale and
        node order both pass through" — is contradicted by LS-DYNA's own
        manual.

        Vol I R17 p.33-107, Figure 33-12's caption: *"Positive pressure acts
        in the negative t-direction"*, with ``t`` the right-hand normal of the
        N1..N4 order. That is the SAME sentence the ``*LOAD_SHELL`` path has
        always quoted and inverted for. k2rad pastes the deck's node order
        into the ``/SURF/SEG`` verbatim, so ``n_hat = t_hat`` and exactly ONE
        flip is needed; ``/PLOAD`` with a positive ``Fscale_y`` pushes along
        the POSITIVE segment normal (``force.F90:451-465``).

        MEASURED on ``3.1_Elastic_Beams_etc`` against its own LS-DYNA
        ``nodout``, one converted deck run twice with only this cell patched:
        WITHOUT the flip its hex cantilever tip (node 21) reads +1.066000E-01
        against a reference -1.062870E-01 (-200.29 %), the tet tip -200.27 %,
        the mid-span node -199.96 % and the root DX -197.96 %; WITH it they
        are +0.29 %, +0.33 %, +0.03 % and -0.30 %. The same deck's
        ``*LOAD_NODE_POINT``-loaded shell tip is identical in both runs at
        +0.62 %, isolating the pressure path.
        """
        result, starter = _convert(_deck(
            "*LOAD_SEGMENT\n"
            "        10       2.5       0.0         1         2         3         4\n"))
        _surf, _fct, _sens, _ascale, fscale = _pload_card(starter, 1)
        self.assertEqual(fscale, -2.5)
        w = [x for x in result.warnings
             if x.startswith("*LOAD_SEGMENT[_SET] -> /PLOAD")]
        self.assertEqual(len(w), 1, result.warnings)
        for fact in ("Figure 33-12", "negative t-direction",
                     "force.F90:451-465", "3.1_Elastic_Beams_etc",
                     "-200.29 %", "+0.29 %"):
            self.assertIn(fact, w[0])

    def test_set_form_expands_the_shell_set(self):
        _result, starter = _convert(_deck("*LOAD_SHELL_SET\n"
                                          "        70        10       7.5\n"))
        surf, _fct, _sens, _ascale, fscale = _pload_card(starter, 1)
        self.assertEqual(fscale, -7.5)
        self.assertEqual(_surf_segs(starter, surf),
                         [[1, 2, 3, 4], [5, 6, 7, 8]])

    def test_multi_row_element_form_keeps_every_rows_own_load(self):
        """dyna2rad collapses a multi-row _ELEMENT block onto row 0's LCID/SF/AT
        (sdiIdentifier without a row index reads only the first sub-object).
        Every row must keep its own."""
        _result, starter = _convert(_deck(
            "*LOAD_SHELL_ELEMENT\n"
            "         1        10       2.5\n"
            "         2        20       3.0\n"))
        cards = {}
        for pid, _d in _blocks(starter, "/PLOAD"):
            surf, fct, _s, _a, fs = _pload_card(starter, pid)
            cards[fct] = (fs, _surf_segs(starter, surf))
        self.assertEqual(cards[10], (-2.5, [[1, 2, 3, 4]]))
        self.assertEqual(cards[20], (-3.0, [[5, 6, 7, 8]]))

    def test_rows_sharing_lcid_sf_at_are_merged(self):
        _result, starter = _convert(_deck(
            "*LOAD_SHELL_ELEMENT\n"
            "         1        10       2.5\n"
            "         2        10       2.5\n"))
        self.assertEqual(len(_blocks(starter, "/PLOAD")), 1)
        surf, _fct, _s, _a, _fs = _pload_card(starter, 1)
        self.assertEqual(_surf_segs(starter, surf),
                         [[1, 2, 3, 4], [5, 6, 7, 8]])

    def test_arrival_time_becomes_a_sensor_time(self):
        _result, starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                          "         1        10       2.5     0.003\n"))
        _surf, _fct, sens, _a, _fs = _pload_card(starter, 1)
        self.assertNotEqual(sens, 0, "AT > 0 needs a /SENSOR/TIME")
        sid, data = _block(starter, "/SENSOR/TIME")
        self.assertEqual(sid, sens)
        tdelay, tstop = (float(x) for x in _fields(data[0], 20, 2))
        self.assertEqual(tdelay, 0.003)
        self.assertEqual(tstop, 0.0, "Tstop = 0 means never deactivate")

    def test_arrival_time_shift_semantics_are_warned(self):
        result, _starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                          "         1        10       2.5     0.003\n"))
        self.assertTrue(_has_warn(result, "/SENSOR/TIME", "t - AT",
                                  "SHIFTED"))

    def test_load_segment_set_at_now_routes_to_a_sensor(self):
        """k2rad <= PR #116 dropped AT on *LOAD_SEGMENT_SET with a warning."""
        deck = _deck(
            "*SET_SEGMENT\n"
            "         8\n"
            "         1         2         3         4\n"
            "*LOAD_SEGMENT_SET\n"
            "         8        10       2.0     0.004\n")
        _result, starter = _convert(deck)
        _surf, _fct, sens, _a, fscale = _pload_card(starter, 1)
        # Fscale_y = -SF since this round: Vol I R17 p.33-107, Figure
        # 33-12's caption is "Positive pressure acts in the negative
        # t-direction", the SAME rule *LOAD_SHELL_* has always been
        # inverted for. MEASURED on 3.1_Elastic_Beams_etc against its own
        # LS-DYNA nodout: -200.29 % without the flip, +0.29 % with it.
        self.assertEqual(fscale, -2.0,
                         "*LOAD_SEGMENT_SET IS negated, exactly as "
                         "*LOAD_SEGMENT and *LOAD_SHELL_* are")
        sid, data = _block(starter, "/SENSOR/TIME")
        self.assertEqual(sid, sens)
        self.assertEqual(float(_fields(data[0], 20, 2)[0]), 0.004)

    def test_different_arrival_times_do_not_share_a_pload(self):
        _result, starter = _convert(_deck(
            "*LOAD_SHELL_ELEMENT\n"
            "         1        10       2.5       0.0\n"
            "         2        10       2.5     0.005\n"))
        self.assertEqual(len(_blocks(starter, "/PLOAD")), 2)
        self.assertEqual(len(_blocks(starter, "/SENSOR/TIME")), 1)

    def test_brode_and_conwep_lcids_are_refused(self):
        for lcid, name in ((-1, "Brode"), (-2, "ConWep")):
            with self.subTest(lcid=lcid):
                result, starter = _convert(_deck(
                    "*LOAD_SHELL_ELEMENT\n"
                    f"         1{lcid:10d}       2.5\n"))
                self.assertEqual(_blocks(starter, "/PLOAD"), [])
                self.assertTrue(_has_warn(result, f"LCID={lcid}", name,
                                          "/LOAD/PBLAST"))

    def test_unknown_element_is_warned(self):
        result, starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                         "       999        10       2.5\n"))
        self.assertEqual(_blocks(starter, "/PLOAD"), [])
        self.assertTrue(_has_warn(result, "999", "not in the deck"))

    def test_missing_shell_set_is_warned(self):
        result, starter = _convert(_deck("*LOAD_SHELL_SET\n"
                                         "        88        10       2.5\n"))
        self.assertEqual(_blocks(starter, "/PLOAD"), [])
        self.assertTrue(_has_warn(result, "*SET_SHELL 88", "not defined"))

    def test_id_suffix_needs_no_registry_key(self):
        for kw in ("LOAD_SHELL_ELEMENT_ID", "LOAD_SHELL_SET_ID"):
            self.assertNotIn(kw, HANDLERS)
        st = _parse(_deck("*LOAD_SHELL_ELEMENT_ID\n"
                          "         3shell pressure\n"
                          "         1        10       2.5\n"))
        self.assertEqual(len(st.shell_pressure_loads), 1)
        self.assertEqual(st.shell_pressure_loads[0].eids, [1])


# ═════════════════════════════════════════════════════════════════════════════
# D) *LOAD_BODY_VECTOR -> /GRAV + /SKEW/FIX
# ═════════════════════════════════════════════════════════════════════════════

def _body_vector(lcid=10, sf=2.0, lciddr=0, xc=0.0, yc=0.0, zc=0.0, cid=0,
                 v=(0.0, 0.0, -1.0)):
    return ("*LOAD_BODY_VECTOR\n"
            f"{lcid:10d}{sf:10g}{lciddr:10d}{xc:10g}{yc:10g}{zc:10g}{cid:10d}\n"
            f"{v[0]:10g}{v[1]:10g}{v[2]:10g}\n")


class TestLoadBodyVector(unittest.TestCase):
    def test_dispatch_and_card_2(self):
        self.assertIn("LOAD_BODY_VECTOR", HANDLERS)
        st = _parse(_deck(_body_vector(v=(1.0, 2.0, 3.0), xc=4.0, yc=5.0,
                                       zc=6.0, cid=40)))
        self.assertEqual(len(st.body_load_vectors), 1)
        bv = st.body_load_vectors[0]
        self.assertEqual((bv.lcid, bv.sf, bv.v, bv.cid), (10, 2.0,
                                                          (1.0, 2.0, 3.0), 40))
        self.assertEqual((bv.xc, bv.yc, bv.zc), (4.0, 5.0, 6.0))
        self.assertEqual(st.body_loads, [], "must not land on the X/Y/Z path")

    def test_one_grav_with_dir_x_and_a_skew_whose_x_is_plus_v(self):
        _result, starter = _convert(_deck(_body_vector(v=(0.0, 0.0, -1.0))))
        gravs = _grav_card(starter)
        self.assertEqual(len(gravs), 1, "one /GRAV, not a 3-card decomposition")
        gid, fct, d, skew_id, sens, _grnod, ascale, fscale = gravs[0]
        self.assertEqual((fct, d, sens, ascale), (10, "X", 0, 1.0))
        self.assertEqual(fscale, -2.0, "Fscale_Y = -SF")
        _o, _y, _z, x = _skew_axes(starter, "/SKEW/FIX", skew_id)
        for got, want in zip(x, (0.0, 0.0, -1.0)):
            self.assertAlmostEqual(got, want, places=12,
                                   msg="the skew's local X' must be +V")

    def test_the_resulting_acceleration_is_along_minus_v(self):
        """Hand-computed end-to-end: /GRAV adds +Fscale_Y*f(t) along the skew's
        DIR axis (gravit.F:147), so a = (-SF)*f(t) * X'_hat = -SF*f(t)*V_hat.
        LS-DYNA prescribes exactly that (p.33-29: V = (-1,-1,-1) gives gravity
        along +(1,1,1))."""
        v = (1.0, 1.0, 1.0)
        _result, starter = _convert(_deck(_body_vector(sf=3.0, v=v)))
        gid, _fct, _d, skew_id, _s, _g, _a, fscale = _grav_card(starter)[0]
        _o, _y, _z, x = _skew_axes(starter, "/SKEW/FIX", skew_id)
        n = math.sqrt(3.0)
        # a(t) at f(t) = 1
        a = tuple(fscale * xi for xi in x)
        for got, want in zip(a, (-3.0 / n, -3.0 / n, -3.0 / n)):
            # the skew axes are written at %.10G, so 10 significant digits
            self.assertAlmostEqual(got, want, places=8)

    def test_v_magnitude_is_irrelevant(self):
        """LS-DYNA and the starter both treat V as a direction only, so |V| must
        not scale the load."""
        out = []
        for scale in (1.0, 1000.0):
            _r, starter = _convert(_deck(_body_vector(
                v=(0.0, 3.0 * scale, 4.0 * scale))))
            _g, _f, _d, skew_id, _s, _gr, _a, fscale = _grav_card(starter)[0]
            _o, _y, _z, x = _skew_axes(starter, "/SKEW/FIX", skew_id)
            out.append((round(fscale, 12), tuple(round(c, 10) for c in x)))
        self.assertEqual(out[0], out[1])
        self.assertEqual(out[0][1], (0.0, 0.6, 0.8))

    def test_cid_maps_the_components_to_global(self):
        """V1/V2/V3 are components IN the CID basis. *DEFINE_COORDINATE_SYSTEM
        40 has ex=(0,1,0), ey=(-1,0,0), ez=(0,0,1), so V_local = (1,0,0) means
        V_global = +Y."""
        _result, starter = _convert(_deck(COORD_40,
                                          _body_vector(cid=40,
                                                       v=(1.0, 0.0, 0.0))))
        _g, _f, _d, skew_id, _s, _gr, _a, _fs = _grav_card(starter)[0]
        _o, _y, _z, x = _skew_axes(starter, "/SKEW/FIX", skew_id)
        for got, want in zip(x, (0.0, 1.0, 0.0)):
            self.assertAlmostEqual(got, want, places=12)

    def test_unknown_cid_is_warned(self):
        result, _starter = _convert(_deck(_body_vector(cid=77)))
        self.assertTrue(_has_warn(result, "CID=77", "not found",
                                  "DIRECTION IS WRONG"))

    def test_xc_yc_zc_become_the_skew_origin(self):
        _result, starter = _convert(_deck(_body_vector(xc=1.0, yc=2.0, zc=3.0)))
        _g, _f, _d, skew_id, _s, _gr, _a, _fs = _grav_card(starter)[0]
        o, _y, _z, _x = _skew_axes(starter, "/SKEW/FIX", skew_id)
        self.assertEqual(o, (1.0, 2.0, 3.0))

    def test_zero_vector_is_refused(self):
        """dyna2rad silently turns V=0 into a global -X body load
        (convertloads.cxx:588-594) — a load nobody asked for."""
        result, starter = _convert(_deck(_body_vector(v=(0.0, 0.0, 0.0))))
        self.assertEqual(_grav_card(starter), [])
        self.assertTrue(_has_warn(result, "direction vector V1 V2 V3 is zero"))

    def test_lciddr_is_warned(self):
        result, _starter = _convert(_deck(_body_vector(lciddr=99)))
        self.assertTrue(_has_warn(result, "LCIDDR=99"))

    def test_parts_scoping_is_shared_with_the_xyz_forms(self):
        deck = _deck("*SET_PART_LIST\n         9\n         1\n",
                     "*LOAD_BODY_PARTS\n         9\n",
                     _body_vector(),
                     "*LOAD_BODY_Z\n        10       1.0\n")
        _result, starter = _convert(deck)
        gravs = _grav_card(starter)
        self.assertEqual(len(gravs), 2)
        self.assertEqual(len({g[5] for g in gravs}), 1,
                         "both /GRAV cards must share the one scoped /GRNOD")

    def test_sign_and_skew_pairing_is_warned_together(self):
        result, _starter = _convert(_deck(_body_vector()))
        self.assertTrue(_has_warn(result, "Fscale_Y = -SF", "local X' is +V",
                                  "flips the load"))


# ═════════════════════════════════════════════════════════════════════════════
# E) *LOAD_BODY_RX/_RY/_RZ -> /LOAD/CENTRI (+ /FRAME/FIX)
# ═════════════════════════════════════════════════════════════════════════════

def _body_rot(axis="Z", lcid=10, sf=4.0, lciddr=0, xc=0.0, yc=0.0, zc=0.0,
              cid=0):
    return (f"*LOAD_BODY_R{axis}\n"
            f"{lcid:10d}{sf:10g}{lciddr:10d}{xc:10g}{yc:10g}{zc:10g}{cid:10d}\n")


class TestLoadBodyRotational(unittest.TestCase):
    def test_dispatch(self):
        for kw in ("LOAD_BODY_RX", "LOAD_BODY_RY", "LOAD_BODY_RZ"):
            self.assertIn(kw, HANDLERS)
        st = _parse(_deck(_body_rot("Y", xc=1.0, yc=2.0, zc=3.0, cid=40)))
        self.assertEqual(len(st.body_load_rots), 1)
        br = st.body_load_rots[0]
        self.assertEqual((br.dir, br.lcid, br.sf, br.cid), ("Y", 10, 4.0, 40))
        self.assertEqual((br.xc, br.yc, br.zc), (1.0, 2.0, 3.0))
        self.assertEqual(st.body_loads, [])

    def test_dir_is_the_double_letter_spelling(self):
        """X/Y/Z reach IDIR 1/2/3, which the engine's cfield.F does not branch
        on: they all fall into the ELSE and rotate about the FRAME'S Z AXIS,
        silently. Only XX/YY/ZZ is safe."""
        for axis, want in (("X", "XX"), ("Y", "YY"), ("Z", "ZZ")):
            with self.subTest(axis=axis):
                _result, starter = _convert(_deck(_body_rot(axis)))
                cards = _centri_card(starter)
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0][2], want)

    def test_omega_is_linear_not_squared(self):
        """The engine squares Fscaley for itself (cfield.F: VROT = Fscaley*f(t),
        VROT2 = VROT*VROT, AREL = r_perp*VROT2). Hand-computed check with
        SF = 4.0, f(t)=1: the emitted Fscaley must be 4.0 exactly — NOT 16.0
        (pre-squared) and NOT 2.0 (square-rooted), and the acceleration the
        engine then applies at r_perp = 3.0 is 4^2 * 3 = 48.0."""
        _result, starter = _convert(_deck(_body_rot("Z", sf=4.0)))
        cards = _centri_card(starter)
        fscaley = cards[0][8]
        self.assertEqual(fscaley, 4.0)
        self.assertNotEqual(fscaley, 16.0)
        self.assertNotEqual(fscaley, 2.0)
        r_perp = 3.0
        self.assertAlmostEqual((fscaley * 1.0) ** 2 * r_perp, 48.0, places=12)

    def test_omega_has_no_sign_flip(self):
        """Both codes push radially OUTWARD (LS-DYNA Remark 2; cfield.F:232-237
        AREL = DIST*VROT2 with DIST the axis-perpendicular radius), so Fscaley
        keeps SF's sign. Copying /GRAV's -SF here would be cargo-culting: it is
        squared away for Ivar=1 but would matter the moment Ivar=2."""
        _result, starter = _convert(_deck(_body_rot("Z", sf=4.0)))
        self.assertGreater(_centri_card(starter)[0][8], 0.0)

    def test_ivar_and_ascalex_are_written_in_the_right_columns(self):
        """/LOAD/CENTRI cols 51-60 are Ivar; /GRAV's are ten LITERAL blanks.
        The two cards must not share a formatter — _grav_card/_centri_card
        assert both grids."""
        _result, starter = _convert(_deck(_body_rot("Z"),
                                          "*LOAD_BODY_Z\n        10       1.0\n"))
        centri = _centri_card(starter)[0]
        self.assertEqual(centri[6], 1, "Ivar = 1 omits the dOmega/dt term, "
                                       "which is what LS-DYNA does too")
        self.assertEqual(centri[7], 1.0, "Ascalex is an abscissa DIVISOR")
        self.assertEqual(_grav_card(starter)[0][6], 1.0)

    def test_no_centre_and_no_cid_uses_frame_zero(self):
        """frame_ID = 0 is the global axes through the global origin
        (XFRAME(:,1) is initialised to the identity, hm_read_frm.F:133-135), so
        no /FRAME card is needed at all."""
        _result, starter = _convert(_deck(_body_rot("X")))
        self.assertEqual(_centri_card(starter)[0][3], 0)
        self.assertEqual(_blocks(starter, "/FRAME/FIX"), [])

    def test_centre_of_rotation_becomes_a_frame_fix_origin(self):
        _result, starter = _convert(_deck(_body_rot("Z", xc=1.0, yc=2.0,
                                                    zc=3.0)))
        frame_id = _centri_card(starter)[0][3]
        self.assertNotEqual(frame_id, 0)
        o, y, z, x = _skew_axes(starter, "/FRAME/FIX", frame_id)
        self.assertEqual(o, (1.0, 2.0, 3.0))
        self.assertEqual((y, z), ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertEqual(tuple(round(c, 12) for c in x), (1.0, 0.0, 0.0))

    def test_cid_wins_over_the_centre_fields(self):
        """CID takes the frame origin and XC/YC/ZC are dropped — the dyna2rad
        _SYSTEM behaviour (convertloads.cxx:325-385).

        *LOAD_BODY does NOT document the interaction (p.33-27 describes CID as
        the acceleration's system and says nothing about the centre of rotation)
        and *LOAD_BODY_GENERALIZED documents the OPPOSITE for its own card
        (p.33-32), so the warning must present this as k2rad's choice with both
        readings named, not as an LS-DYNA rule.
        """
        result, starter = _convert(_deck(COORD_40,
                                         _body_rot("Z", xc=9.0, yc=9.0,
                                                   zc=9.0, cid=40)))
        frame_id = _centri_card(starter)[0][3]
        o, y, z, _x = _skew_axes(starter, "/FRAME/FIX", frame_id)
        self.assertEqual(o, (1.0, 2.0, 3.0), "the CID origin, not XC/YC/ZC")
        self.assertEqual(tuple(round(c, 12) for c in y), (-1.0, 0.0, 0.0))
        self.assertEqual(tuple(round(c, 12) for c in z), (0.0, 0.0, 1.0))
        self.assertTrue(_has_warn(result, "k2rad lets CID win",
                                  "XC/YC/ZC are IGNORED",
                                  "does NOT document how the two interact",
                                  "LOAD_BODY_GENERALIZED documents the opposite"))

    def test_unknown_cid_is_warned(self):
        result, _starter = _convert(_deck(_body_rot("Z", cid=77)))
        self.assertTrue(_has_warn(result, "CID=77", "not found",
                                  "AXIS IS WRONG"))

    def test_two_cards_get_distinct_frame_ids(self):
        """dyna2rad calls GetDynaMaxEntityID inside the loop, which returns the
        SAME id every time: two *LOAD_BODY_R* cards then produce two /FRAMEs
        with one id (starter ERROR 79)."""
        deck = _deck(_body_rot("X", xc=1.0), _body_rot("Y", yc=2.0))
        _result, starter = _convert(deck)
        frames = [c[3] for c in _centri_card(starter)]
        self.assertEqual(len(frames), 2)
        self.assertEqual(len(set(frames)), 2, "duplicate /FRAME id")
        self.assertEqual(len(_blocks(starter, "/FRAME/FIX")), 2)

    def test_frame_ids_do_not_collide_with_converted_skews(self):
        """/FRAME and /SKEW share ONE starter table."""
        deck = _deck(COORD_40, VECTOR_Z, _body_rot("Z", xc=1.0))
        _result, starter = _convert(deck)
        frames = {c[3] for c in _centri_card(starter)}
        skews = {s for s, _d in _blocks(starter, "/SKEW/FIX")}
        skews |= {s for s, _d in _blocks(starter, "/SKEW/MOV")}
        self.assertEqual(frames & skews, set())

    def test_missing_curve_is_refused(self):
        """fct_IDT is mandatory: a missing function is starter ERROR 883."""
        result, starter = _convert(_deck(_body_rot("Z", lcid=999)))
        self.assertEqual(_centri_card(starter), [])
        self.assertTrue(_has_warn(result, "curve 999", "not found"))

    def test_lciddr_is_warned(self):
        result, _starter = _convert(_deck(_body_rot("Z", lciddr=99)))
        self.assertTrue(_has_warn(result, "LCIDDR=99"))

    def test_grnod_is_shared_with_the_grav_paths(self):
        deck = _deck("*LOAD_BODY_Z\n        10       1.0\n", _body_rot("Z"))
        _result, starter = _convert(deck)
        self.assertEqual(_grav_card(starter)[0][5],
                         _centri_card(starter)[0][5])

    def test_curve_and_dir_semantics_are_warned(self):
        result, _starter = _convert(_deck(_body_rot("Z")))
        self.assertTrue(_has_warn(result, "ANGULAR VELOCITY", "LINEARLY",
                                  "Do NOT pre-square"))
        self.assertTrue(_has_warn(result, "XX/YY/ZZ", "cfield.F",
                                  "convertloads.cxx:271-288"))

    def test_modal_decks_emit_nothing(self):
        deck = _deck("*CONTROL_IMPLICIT_GENERAL\n         1       0.1\n"
                     "*CONTROL_IMPLICIT_EIGENVALUE\n         5\n",
                     _body_rot("Z"))
        _result, starter = _convert(deck)
        self.assertEqual(_centri_card(starter), [])

    def test_generalized_is_registered_and_warn_skipped(self):
        """The handler docstring used to claim rotational/generalized forms are
        "skipped with a warning" while they were not registered at all, so they
        arrived as a mute skipped_keywords entry."""
        self.assertIn("LOAD_BODY_GENERALIZED", HANDLERS)
        result, _starter = _convert(_deck("*LOAD_BODY_GENERALIZED\n"
                                          "        10       1.0\n"))
        self.assertIn("LOAD_BODY_GENERALIZED", result.skipped_keywords)
        self.assertTrue(_has_warn(result, "*LOAD_BODY_GENERALIZED",
                                  "no OpenRadioss equivalent"))


# ═════════════════════════════════════════════════════════════════════════════
# Multi-variant deck + no-regression guards
# ═════════════════════════════════════════════════════════════════════════════

class TestMultiVariantDeck(unittest.TestCase):
    """One deck carrying all five new keywords at once."""

    def setUp(self):
        deck = _deck(
            BOX_HALF, VECTOR_Z, COORD_40,
            _RIGID_LOCAL,
            _set_box(dof=2, vad=2, sf=1.5),
            "*LOAD_SHELL_ELEMENT\n"
            "         1        10       2.5\n"
            "         2        20       3.0     0.003\n",
            _body_vector(v=(0.0, 0.0, -1.0)),
            _body_rot("Z", xc=1.0, yc=2.0, zc=3.0),
        )
        self.result, self.starter = _convert(deck)

    def test_nothing_is_skipped(self):
        self.assertEqual(self.result.skipped_keywords, [])

    def test_every_target_card_is_present_exactly_once(self):
        self.assertEqual(len(_blocks(self.starter, "/SKEW/MOV")), 1)
        self.assertEqual(len(_blocks(self.starter, "/LOAD/CENTRI")), 1)
        self.assertEqual(len(_blocks(self.starter, "/FRAME/FIX")), 1)
        self.assertEqual(len(_blocks(self.starter, "/SENSOR/TIME")), 1)
        self.assertEqual(len(_blocks(self.starter, "/PLOAD")), 2)
        self.assertEqual(len(_grav_card(self.starter)), 1)
        self.assertEqual(len(_imp_cards(self.starter)), 2)

    def test_all_ids_are_unique_within_each_namespace(self):
        for header in ("/PLOAD", "/SURF/SEG", "/SENSOR/TIME", "/GRAV",
                       "/LOAD/CENTRI", "/IMPVEL", "/IMPDISP", "/GRNOD/NODE"):
            ids = [i for i, _d in _blocks(self.starter, header)]
            self.assertEqual(len(ids), len(set(ids)), f"duplicate {header} id")
        # /SKEW and /FRAME share ONE starter table
        shared = ([i for i, _d in _blocks(self.starter, "/SKEW/FIX")]
                  + [i for i, _d in _blocks(self.starter, "/SKEW/MOV")]
                  + [i for i, _d in _blocks(self.starter, "/FRAME/FIX")])
        self.assertEqual(len(shared), len(set(shared)),
                         "/SKEW and /FRAME ids collide (starter ERROR 79)")

    def test_every_referenced_group_and_system_really_exists(self):
        surfs = {i for i, _d in _blocks(self.starter, "/SURF/SEG")}
        sensors = {i for i, _d in _blocks(self.starter, "/SENSOR/TIME")}
        grnods = {i for i, _d in _blocks(self.starter, "/GRNOD/NODE")}
        grnods |= {i for i, _d in _blocks(self.starter, "/GRNOD/PART")}
        grnods |= {i for i, _d in _blocks(self.starter, "/GRNOD/GRNOD")}
        skews = {i for i, _d in _blocks(self.starter, "/SKEW/FIX")}
        skews |= {i for i, _d in _blocks(self.starter, "/SKEW/MOV")}
        frames = {i for i, _d in _blocks(self.starter, "/FRAME/FIX")}
        for pid, _d in _blocks(self.starter, "/PLOAD"):
            surf, _f, sens, _a, _fs = _pload_card(self.starter, pid)
            self.assertIn(surf, surfs)
            if sens:
                self.assertIn(sens, sensors)
        for c in _centri_card(self.starter):
            if c[3]:
                self.assertIn(c[3], frames)
            self.assertIn(c[5], grnods)
        for g in _grav_card(self.starter):
            if g[3]:
                self.assertIn(g[3], skews)
            self.assertIn(g[5], grnods)
        for imp in _imp_cards(self.starter):
            if imp[4]:
                self.assertIn(imp[4], skews)
            self.assertIn(imp[6], grnods)

    def test_every_card_line_is_the_right_width(self):
        """A short card silently shifts the reader onto the next keyword
        (WARNING 100217) and a long one runs into the next field."""
        for header, width in (("/PLOAD", 100), ("/GRAV", 100),
                              ("/LOAD/CENTRI", 100)):
            for _i, data in _blocks(self.starter, header):
                self.assertEqual(len(data[0]), width,
                                 f"{header} data card is {len(data[0])} cols")


class TestNoRegressionWithoutTheNewKeywords(unittest.TestCase):
    """A deck with none of the new keywords must convert exactly as before."""

    def test_plain_motion_and_body_load_deck_is_unchanged(self):
        deck = _deck(
            "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
            "         2         3         2        10       1.0\n"
            "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
            "         1         1         2        10       2.0\n"
            "*LOAD_BODY_Z\n        10       1.0\n"
            "*LOAD_SEGMENT\n"
            "        10       2.5       0.0         1         2         3         4\n")
        result, starter = _convert(deck)
        self.assertEqual(result.skipped_keywords, [])
        # the /IMPDISP from the rigid path keeps its literal counter id
        rigid = [i for i in _imp_cards(starter) if i[1] == 1]
        self.assertEqual(len(rigid), 1)
        self.assertEqual(rigid[0][:4], ("/IMPDISP", 1, 10, "Z"))
        self.assertEqual(rigid[0][4], 0, "no skew on a plain _RIGID card")
        # no new card type appears
        for header in ("/SKEW/MOV", "/SENSOR/TIME", "/LOAD/CENTRI",
                       "/FRAME/FIX"):
            self.assertEqual(_blocks(starter, header), [],
                             f"{header} must not appear")
        # /PLOAD carries the NEGATED *LOAD_SEGMENT scale.
        # Fscale_y = -SF since this round: Vol I R17 p.33-107, Figure
        # 33-12's caption is "Positive pressure acts in the negative
        # t-direction", the SAME rule *LOAD_SHELL_* has always been
        # inverted for. MEASURED on 3.1_Elastic_Beams_etc against its own
        # LS-DYNA nodout: -200.29 % without the flip, +0.29 % with it.
        self.assertEqual(_pload_card(starter, 1)[4], -2.5)


class TestIncludeTransformTables(unittest.TestCase):
    def test_offset_specs_cover_every_new_spelling(self):
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_BOX",
                   "LOAD_SHELL_ELEMENT", "LOAD_SHELL_SET",
                   "LOAD_BODY_RX", "LOAD_BODY_RY", "LOAD_BODY_RZ",
                   "LOAD_BODY_VECTOR", "LOAD_BODY_PARTS"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_direction_bearing_covers_the_new_spellings(self):
        from k2rad.assembly import _DIRECTION_BEARING
        for kw in ("BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL",
                   "BOUNDARY_PRESCRIBED_MOTION_SET_BOX",
                   "LOAD_BODY_RX", "LOAD_BODY_RY", "LOAD_BODY_RZ",
                   "LOAD_BODY_VECTOR"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _DIRECTION_BEARING)

    def test_box_card_ids_move_with_iddoff_not_the_set_offset(self):
        """The _BOX card's BOXID is a *DEFINE_BOX (IDDOFF), and it must not be
        rewritten with the card-1 spec (which would move it with IDSOFF and put
        the set offset on TOFFSET)."""
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.parser import Block
        b = Block(keyword="BOUNDARY_PRESCRIBED_MOTION_SET_BOX", options=[],
                  raw=["         1         1         2        10       1.0",
                       "         5         1        99"])
        _OFFSET_SPECS["BOUNDARY_PRESCRIBED_MOTION_SET_BOX"](
            b, {"s": 1000, "d": 2000, "f": 300, "n": 0, "p": 0, "e": 0,
                "m": 0, "r": 0}, lambda m: None)
        c1 = _fields(b.raw[0], 10, 5)
        c2 = _fields(b.raw[1], 10, 3)
        self.assertEqual(int(c1[0]), 1001, "NSID moves with IDSOFF")
        self.assertEqual(int(c1[3]), 310, "LCID moves with IDFOFF")
        self.assertEqual(int(c2[0]), 2005, "BOXID moves with IDDOFF")
        self.assertEqual(int(c2[1]), 1, "TOFFSET is a flag, not an id")
        self.assertEqual(int(c2[2]), 399, "LCBCHK moves with IDFOFF")

    def test_load_body_rot_centre_is_reported_as_literal_geometry(self):
        from k2rad.assembly import _carries_literal_axis_point
        from k2rad.parser import Block
        with_centre = Block(
            keyword="LOAD_BODY_RZ", options=[],
            raw=["        10       1.0         0       1.0       2.0"
                 "       3.0         0"])
        without = Block(keyword="LOAD_BODY_RZ", options=[],
                        raw=["        10       1.0"])
        self.assertTrue(_carries_literal_axis_point(with_centre))
        self.assertFalse(_carries_literal_axis_point(without))

    def test_axis_point_scan_threads_is_box(self):
        """_carries_literal_axis_point walks the same two-card grammar. Without
        is_box the _SET_BOX card 2 is read as a card 1 and its TOFFSET tested
        against (9, 10, 11) — and when a real card 1 does carry |DOF| 9/10/11 the
        pending continuation slot then swallows the BOX card instead."""
        from k2rad.assembly import _bpm_cards
        from k2rad.parser import Block
        b = Block(keyword="BOUNDARY_PRESCRIBED_MOTION_SET_BOX", options=[],
                  raw=["         1        11         2        10       1.0",
                       "         5         0         0",
                       "       1.0       2.5         0         0         0",
                       "         1         1         2        10       1.0",
                       "         5         0         0"])
        self.assertEqual(list(_bpm_cards(b, is_box=True)),
                         [(0, ""), (1, "box"), (2, "cont"), (3, ""),
                          (4, "box")])

    def test_blank_continuation_card_does_not_shift_the_id_specs(self):
        """Card 3 is all-defaults-able (p.753), so a blank one is legal. Skipping
        blanks to find it left the pending 'cont' slot to swallow entity 2's card
        1, which then got the CONTINUATION spec: NSID un-offset, VAD+IDPOFF,
        LCID+IDNOFF and the float SF turned into an id."""
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.parser import Block
        b = Block(keyword="BOUNDARY_PRESCRIBED_MOTION_SET", options=[],
                  raw=["         1        11         2        10       1.0",
                       "",
                       "         2         1         2        10       2.0"])
        _OFFSET_SPECS["BOUNDARY_PRESCRIBED_MOTION_SET"](
            b, {"s": 1000, "d": 2000, "f": 300, "n": 7000, "p": 8000, "e": 0,
                "m": 0, "r": 0}, lambda m: None)
        self.assertEqual(b.raw[1], "", "the blank card 3 stays blank")
        c1 = _fields(b.raw[2], 10, 5)
        self.assertEqual(int(c1[0]), 1002, "entity 2's NSID moves with IDSOFF")
        self.assertEqual(int(c1[1]), 1, "DOF is not an id")
        self.assertEqual(int(c1[2]), 2, "VAD is not an id")
        self.assertEqual(int(c1[3]), 310, "LCID moves with IDFOFF")
        self.assertEqual(float(c1[4]), 2.0, "SF is a float, not an id")

    def test_blank_box_card_does_not_shift_the_id_specs(self):
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.parser import Block
        b = Block(keyword="BOUNDARY_PRESCRIBED_MOTION_SET_BOX", options=[],
                  raw=["         1         1         2        10       1.0",
                       "",
                       "         2         3         2        10       2.0",
                       "         5         0         0"])
        _OFFSET_SPECS["BOUNDARY_PRESCRIBED_MOTION_SET_BOX"](
            b, {"s": 1000, "d": 2000, "f": 300, "n": 0, "p": 0, "e": 0,
                "m": 0, "r": 0}, lambda m: None)
        c1 = _fields(b.raw[2], 10, 5)
        self.assertEqual(int(c1[0]), 1002, "entity 2's NSID moves with IDSOFF")
        self.assertEqual(int(c1[3]), 310, "LCID moves with IDFOFF")
        self.assertEqual(int(_fields(b.raw[3], 10, 3)[0]), 2005,
                         "entity 2's BOXID moves with IDDOFF")


# ═════════════════════════════════════════════════════════════════════════════
# G) Review-round fixes: card-walk positioning, VAD totality, zero scales,
#    box membership, the body-local frame, and the /RBODY master coordinate.
# ═════════════════════════════════════════════════════════════════════════════

class TestVadGuardIsTotal(unittest.TestCase):
    """PM_VAD_KEYWORD is the single source of truth for which VADs convert.

    The guard used to enumerate only the KNOWN-bad values (3 and 4), so every
    other value passed it and hit the writer's bare ``PM_VAD_KEYWORD[pm.vad]``:
    KeyError, traceback, no deck at all — strictly worse than master's
    ``.get(vad, "IMPDISP")``.
    """

    def test_out_of_range_vad_on_rigid_is_refused_not_a_crash(self):
        for vad in (5, 7, 9, -1):
            with self.subTest(vad=vad):
                deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
                             f"         2         1{vad:10d}        10       1.0\n")
                result, starter = _convert(deck)
                self.assertEqual(_imp_cards(starter), [])
                self.assertTrue(_has_warn(result, f"VAD={vad}",
                                          "not a *BOUNDARY_PRESCRIBED_MOTION",
                                          "defines 0-4 only"))

    def test_out_of_range_vad_on_set_is_refused_not_a_crash(self):
        for vad in (5, 9):
            with self.subTest(vad=vad):
                deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                             f"         1         2{vad:10d}        10       2.0\n")
                result, starter = _convert(deck)
                self.assertEqual(_imp_cards(starter), [])
                self.assertTrue(_has_warn(result, f"VAD={vad}"))

    def test_the_guard_and_the_writer_read_one_dict(self):
        from k2rad.handlers import _pm_vad_supported
        from k2rad.state import PM_VAD_KEYWORD
        self.assertEqual(set(PM_VAD_KEYWORD), {0, 1, 2})
        st = ConversionState()
        for vad in range(-2, 13):
            with self.subTest(vad=vad):
                self.assertEqual(
                    _pm_vad_supported(st, "KW", "ref", vad),
                    vad in PM_VAD_KEYWORD,
                    "the guard must accept exactly the writer's keys")


class TestBlankContinuationCard(unittest.TestCase):
    """Cards 2 and 3 are POSITIONAL. Every field of card 3 defaults (OFFSET1 0.,
    OFFSET2 0., LRB 0, NODE1 0, NODE2 0 — p.753), so an all-blank continuation
    card is legal input; hunting for the next NON-blank line ate the FOLLOWING
    entity's card 1 and lost that motion with no diagnostic at all.
    """

    def test_blank_card_3_keeps_the_next_entity(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1        11         0        10       1.0\n"
                     "\n"
                     "         1         2         2        10       2.0\n")
        st = _parse(deck)
        self.assertEqual([(p.dof, p.vad, p.sf)
                          for p in st.prescribed_motion_sets],
                         [(11, 0, 1.0), (2, 2, 2.0)])
        _result, starter = _convert(deck)
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1, "DOF=11 is refused, DOF=2 is not")
        self.assertEqual(imps[0][0], "/IMPDISP")
        self.assertEqual((imps[0][2], imps[0][3], imps[0][10]), (10, "Y", 2.0))

    def test_blank_vad4_card_3_keeps_the_next_entity(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
                     "         2         1         4        10       1.0\n"
                     "\n"
                     "         2         3         0        10       3.0\n")
        st = _parse(deck)
        self.assertEqual([(p.dof, p.vad) for p in st.prescribed_motions],
                         [(3, 0)], "VAD=4 refused, the DOF=3 row kept")
        _result, starter = _convert(deck)
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual((imps[0][0], imps[0][3], imps[0][10]),
                         ("/IMPVEL", "Z", 3.0))

    def test_blank_box_card_2_keeps_the_next_entity(self):
        deck = _deck(BOX_HALF,
                     "*BOUNDARY_PRESCRIBED_MOTION_SET_BOX\n"
                     "         1         1         2        10       1.0\n"
                     "\n"
                     "         1         3         2        10       2.0\n"
                     "         5         0         0\n")
        st = _parse(deck)
        self.assertEqual([(p.dof, p.boxid)
                          for p in st.prescribed_motion_sets],
                         [(1, 0), (3, 5)],
                         "the blank card 2 is BOXID 0, and entity 2 survives")

    def test_a_real_continuation_card_is_still_consumed(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1        11         2        10       1.0\n"
                     "       1.0       2.5         0         0         0\n"
                     "         1         2         2        10       2.0\n")
        st = _parse(deck)
        self.assertEqual([(p.dof, p.sf) for p in st.prescribed_motion_sets],
                         [(11, 1.0), (2, 2.0)])


class TestPressureZeroScale(unittest.TestCase):
    """A /PLOAD written with ``Fscale_y = 0`` is NOT a zero load.

    ``hm_read_pload.F:167`` is ``IF (FCY == ZERO) FCY = FAC_FCY``, so the starter
    substitutes the unit-system factor and the curve runs at FULL amplitude —
    with the sign inverted on the *LOAD_SHELL path, which negates SF. Measured:
    an ``SF = 0.0`` shell row echoed ``SCALE-Y 1.000000000000`` while its
    blank-SF sibling echoed -1.0. Every card documents ``SF ... Default 1.`` and
    LS-DYNA applies its defaults on a ZERO test (the same keyword family spells
    that out for DEATH, "EQ.0.0: default set to 1e28"), so 0.0 reads as 1.0 —
    warned, because a zeroed SF is also a common way of switching a load off.
    """

    def test_load_shell_zero_sf_reads_as_the_default(self):
        result, starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                         "         1        10       0.0\n"))
        self.assertEqual(_pload_card(starter, 1)[4], -1.0)
        self.assertTrue(_has_warn(result, "SF = 0.0 on element 1",
                                  "documented default 1.0",
                                  "hm_read_pload.F:167"))

    def test_load_segment_zero_sf_reads_as_the_default(self):
        result, starter = _convert(_deck(
            "*LOAD_SEGMENT\n"
            "        10       0.0       0.0         1         2         3"
            "         4\n"))
        # Fscale_y = -SF since this round: Vol I R17 p.33-107, Figure
        # 33-12's caption is "Positive pressure acts in the negative
        # t-direction", the SAME rule *LOAD_SHELL_* has always been
        # inverted for. MEASURED on 3.1_Elastic_Beams_etc against its own
        # LS-DYNA nodout: -200.29 % without the flip, +0.29 % with it.
        self.assertEqual(_pload_card(starter, 1)[4], -1.0,
                         "a defaulted SF = 1 reaches the card as -1")
        self.assertTrue(_has_warn(result, "SF = 0.0", "hm_read_pload.F:167"))

    def test_load_segment_set_zero_sf_reads_as_the_default(self):
        result, starter = _convert(_deck(
            "*SET_SEGMENT\n"
            "        80\n"
            "         1         2         3         4\n"
            "*LOAD_SEGMENT_SET\n"
            "        80        10       0.0\n"))
        # Fscale_y = -SF since this round: Vol I R17 p.33-107, Figure
        # 33-12's caption is "Positive pressure acts in the negative
        # t-direction", the SAME rule *LOAD_SHELL_* has always been
        # inverted for. MEASURED on 3.1_Elastic_Beams_etc against its own
        # LS-DYNA nodout: -200.29 % without the flip, +0.29 % with it.
        self.assertEqual(_pload_card(starter, 1)[4], -1.0)
        self.assertTrue(_has_warn(result, "SF = 0.0 on segment set 80"))

    def test_no_pload_ever_carries_a_literal_zero_scale(self):
        """Belt and braces: whatever the handlers do, the emitter refuses a zero
        ordinate scale rather than letting the starter turn it into 1.0."""
        from k2rad.state import PressureLoad
        from k2rad.writer.loads import _make_pressure_loads
        st = ConversionState()
        st.pressure_loads.append(PressureLoad(10, 0.0, [1, 2, 3, 4]))
        lines = _make_pressure_loads(st)
        self.assertFalse([ln for ln in lines if ln.startswith("/PLOAD")])
        self.assertTrue(any("Fscale_y = 0" in w and "DROPPED" in w
                            for w in st.warnings))

    def test_zero_eid_row_is_warned_not_silently_dropped(self):
        result, starter = _convert(_deck("*LOAD_SHELL_ELEMENT\n"
                                         "                  10       2.0\n"))
        self.assertEqual(_blocks(starter, "/PLOAD"), [])
        self.assertTrue(_has_warn(result, "*LOAD_SHELL_ELEMENT",
                                  "blank or non-positive"))


class TestLoadSegmentArrivalTime(unittest.TestCase):
    """AT on the PLAIN *LOAD_SEGMENT reached nothing: field 2 was never read.

    Its own comment listed the field, its _SET sibling routes AT to a
    /SENSOR/TIME, and the summary warning claimed AT was now covered — but a
    ``*LOAD_SEGMENT 10 2.0 0.004 1 2 3 4`` produced ``sensor_ID = 0`` and ZERO
    warnings, i.e. a pressure starting at t = 0 instead of t = 0.004.
    """

    _SEG_AT = ("*LOAD_SEGMENT\n"
               "        10       2.0     0.004         1         2         3"
               "         4\n")

    def test_at_is_parsed(self):
        st = _parse(_deck(self._SEG_AT))
        self.assertEqual(len(st.pressure_loads), 1)
        self.assertEqual(st.pressure_loads[0].at, 0.004)

    def test_at_becomes_a_sensor_time_in_the_pload(self):
        result, starter = _convert(_deck(self._SEG_AT))
        _surf, fct, sens, ascale, fscale = _pload_card(starter, 1)
        # Fscale_y = -SF since this round: Vol I R17 p.33-107, Figure
        # 33-12's caption is "Positive pressure acts in the negative
        # t-direction", the SAME rule *LOAD_SHELL_* has always been
        # inverted for. MEASURED on 3.1_Elastic_Beams_etc against its own
        # LS-DYNA nodout: -200.29 % without the flip, +0.29 % with it.
        self.assertEqual((fct, ascale, fscale), (10, 1.0, -2.0))
        self.assertNotEqual(sens, 0, "AT > 0 needs a /SENSOR/TIME")
        sensors = _blocks(starter, "/SENSOR/TIME")
        self.assertEqual([s[0] for s in sensors], [sens])
        self.assertEqual(float(sensors[0][1][0][0:20]), 0.004)
        self.assertTrue(_has_warn(result, "arrival time AT > 0",
                                  "/SENSOR/TIME"))

    def test_rows_with_different_at_do_not_share_a_pload(self):
        deck = _deck(self._SEG_AT,
                     "*LOAD_SEGMENT\n"
                     "        10       2.0       0.0         5         6"
                     "         7         8\n")
        _result, starter = _convert(deck)
        cards = [_pload_card(starter, i) for i in (1, 2)]
        # Fscale_y = -SF since this round: Vol I R17 p.33-107, Figure
        # 33-12's caption is "Positive pressure acts in the negative
        # t-direction", the SAME rule *LOAD_SHELL_* has always been
        # inverted for. MEASURED on 3.1_Elastic_Beams_etc against its own
        # LS-DYNA nodout: -200.29 % without the flip, +0.29 % with it.
        self.assertEqual({c[4] for c in cards}, {-2.0})
        self.assertEqual(len([c for c in cards if c[2] == 0]), 1,
                         "exactly one row keeps sensor_ID = 0")

    def test_at_zero_emits_no_sensor(self):
        _result, starter = _convert(_deck(
            "*LOAD_SEGMENT\n"
            "        10       2.0       0.0         1         2         3"
            "         4\n"))
        self.assertEqual(_blocks(starter, "/SENSOR/TIME"), [])
        self.assertEqual(_pload_card(starter, 1)[2], 0)

    def test_negative_at_is_warned_and_clamped(self):
        result, starter = _convert(_deck(
            "*LOAD_SEGMENT\n"
            "        10       2.0    -0.001         1         2         3"
            "         4\n"))
        self.assertEqual(_blocks(starter, "/SENSOR/TIME"), [])
        self.assertEqual(_pload_card(starter, 1)[2], 0)
        self.assertTrue(_has_warn(result, "negative arrival time",
                                  "Tdelay cannot be negative"))


#: A rigid brick (part 2, nodes 11-18, x in [20, 24]) plus a box round it.
BOX_ROUND_BRICK = """\
*DEFINE_BOX
         8      19.0      25.0      -1.0       5.0      -1.0       5.0
"""


class TestBoxMembershipIgnoresSynthesizedNodes(unittest.TestCase):
    """A *DEFINE_BOX names a region of the USER's model.

    By write time ``state.nodes`` also holds the /RBODY CoG masters, the
    /SKEW/MOV third nodes, the _LOCAL triads and the rigid-wall carriers.
    Measured before the fix: a box-only ``_SET_BOX`` round the rigid brick
    emitted ``/GRNOD/NODE ... 11 ... 18 19`` where 19 is the brick's synthesized
    /RBODY MASTER, so the /IMPVEL drove the whole body — starter WARNING 312,
    0 errors, restart written, i.e. the wrong model runs. The ``if not
    box_nodes`` guard cannot catch it: the box DOES contain nodes.
    """

    def test_box_only_group_holds_only_source_nodes(self):
        result, starter = _convert(_deck(
            BOX_ROUND_BRICK,
            _set_box(nsid=0, dof=3, vad=0, lcid=10, sf=2.0, boxid=8)))
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual(sorted(_grnod_nodes(starter, imps[0][6])),
                         [11, 12, 13, 14, 15, 16, 17, 18])
        self.assertTrue(_has_warn(result, "NSID is 0", "all 8 node(s)"))

    def test_the_rbody_master_is_in_the_deck_but_not_in_the_box_group(self):
        """Proves the exclusion is real: the master node exists, sits inside the
        box geometrically, and is still absent from the driven group."""
        _result, starter = _convert(_deck(
            BOX_ROUND_BRICK,
            _set_box(nsid=0, dof=3, vad=0, lcid=10, sf=2.0, boxid=8)))
        master = None
        for _gid, gdata in _blocks(starter, "/GRNOD/NODE"):
            flat = []
            for ln in gdata:
                flat += [int(x) for x in _fields(ln) if x]
            if len(flat) == 1:                    # rb_indnode_pid2
                master = flat[0]
        self.assertIsNotNone(master, "no /RBODY master group found")
        coords = {}
        for ln in starter.splitlines():
            m = re.match(r"^\s*(\d+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)"
                         r"\s+(-?[\d.eE+-]+)\s*$", ln)
            if m:
                coords[int(m.group(1))] = tuple(float(m.group(i))
                                                for i in (2, 3, 4))
        self.assertIn(master, coords)
        x, y, z = coords[master]
        self.assertTrue(19.0 <= x <= 25.0 and -1.0 <= y <= 5.0
                        and -1.0 <= z <= 5.0,
                        "the master must lie INSIDE the box for this to prove "
                        f"anything — got {coords[master]}")
        imps = _imp_cards(starter)
        self.assertNotIn(master, _grnod_nodes(starter, imps[0][6]))

    def _build(self, deck):
        from k2rad.parser import parse_k_file
        from k2rad.writer.assembly import build_starter
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck)
        st = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, st)
        deck_nodes = set(st.nodes)
        build_starter(st)
        tmp.cleanup()
        return st, deck_nodes

    def test_source_snapshot_is_taken_before_any_synthesis(self):
        st, deck_nodes = self._build(_deck(BOX_ROUND_BRICK))
        self.assertEqual(st.source_node_ids, deck_nodes)
        self.assertTrue(set(st.nodes) - st.source_node_ids,
                        "this deck must synthesize at least one node for the "
                        "test to mean anything")

    def test_no_snapshot_without_a_box(self):
        """A set of ints per node is a real cost on the 100-200 MB mesh decks in
        the reference corpora, and nothing reads it unless a *DEFINE_BOX exists —
        which is exactly the precondition for _box_node_ids being reachable."""
        st, _deck_nodes = self._build(_deck())
        self.assertEqual(st.source_node_ids, set())
        self.assertTrue(st.nodes, "the deck does have nodes")

    def test_one_warning_per_missing_box_not_one_per_row(self):
        deck = _deck(_set_box(nsid=1, dof=1, boxid=99),
                     _set_box(nsid=1, dof=2, boxid=99),
                     _set_box(nsid=1, dof=3, boxid=99))
        result, _starter = _convert(deck)
        hits = [w for w in result.warnings if "no *DEFINE_BOX 99" in w]
        self.assertEqual(len(hits), 1, f"one warning expected, got {len(hits)}")


#: *MAT_RIGID for part 2 whose card 3 names LCO = 40 (local x = global +Y).
MAT_RIGID_LCO_40 = """\
*MAT_RIGID
       2   7.85E-9  210000.0       0.3
       1.0       7.0       7.0
      40.0
"""

#: *MAT_RIGID for part 2 whose card 3 gives the A1-V3 vector pair:
#: a = +Y, v = +Z  ->  c = a x v = +X, b = c x a = +Z.
MAT_RIGID_A_V = """\
*MAT_RIGID
       2   7.85E-9  210000.0       0.3
       1.0       7.0       7.0
       0.0       1.0       0.0       0.0       0.0       1.0
"""


def _triad(starter):
    """(N1, X'-direction, Y'-direction) of the single /SKEW/MOV, from the helper
    nodes' coordinates."""
    _sid, data = _blocks(starter, "/SKEW/MOV")[0]
    h = [int(x) for x in _fields(data[0], 10, 4)[:3]]
    pos = {}
    for ln in starter.splitlines():
        m = re.match(r"^\s*(\d+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)"
                     r"\s+(-?[\d.eE+-]+)\s*$", ln)
        if m and int(m.group(1)) in h:
            pos[int(m.group(1))] = tuple(float(m.group(i)) for i in (2, 3, 4))

    def _unit(a, b):
        v = tuple(pos[b][i] - pos[a][i] for i in range(3))
        n = math.sqrt(sum(c * c for c in v))
        return tuple(round(c / n, 12) for c in v)
    return pos[h[0]], _unit(h[0], h[1]), _unit(h[0], h[2])


class TestLocalFrameFromTheDeck(unittest.TestCase):
    """_RIGID_LOCAL's triad is the body's OWN local system when the deck names it.

    LS-DYNA: "the local coordinate system is specified with LCO and CID in
    *MAT_RIGID and *CONSTRAINED_NODAL_RIGID_BODY, respectively. If LCO/CID is 0,
    the local coordinate system defaults to the principal inertia directions"
    (Manual Vol I R16 p.756-757 Remark 7). k2rad already parsed the CNRB's CID
    (zero consumers) and now parses *MAT_RIGID card 3 as well, so both named
    forms are EXACT and only the principal-inertia default is approximated.
    """

    def test_mat_rigid_card_3_lco_is_parsed(self):
        st = _parse(HEAD.replace(
            "*MAT_RIGID\n       2   7.85E-9  210000.0       0.3\n"
            "       1.0       7.0       7.0\n", MAT_RIGID_LCO_40) + END)
        self.assertEqual(st.mat_rigid[2].lco, 40)
        self.assertIsNone(st.mat_rigid[2].a_vec)

    def test_mat_rigid_card_3_vector_pair_is_parsed(self):
        st = _parse(HEAD.replace(
            "*MAT_RIGID\n       2   7.85E-9  210000.0       0.3\n"
            "       1.0       7.0       7.0\n", MAT_RIGID_A_V) + END)
        self.assertEqual(st.mat_rigid[2].lco, 0)
        self.assertEqual(st.mat_rigid[2].a_vec, (0.0, 1.0, 0.0))
        self.assertEqual(st.mat_rigid[2].v_vec, (0.0, 0.0, 1.0))

    def test_a_deck_without_card_3_keeps_lco_zero(self):
        st = _parse(_deck())
        self.assertEqual((st.mat_rigid[2].lco, st.mat_rigid[2].a_vec,
                          st.mat_rigid[2].v_vec), (0, None, None))

    def test_card_3_is_found_past_interleaved_comment_lines(self):
        """The manual's own worked example (Vol I R16 p.11-150) writes a `$`
        header above every card, and that is how LS-PrePost writes *MAT_RIGID —
        so card 3 must be located by CARD index, not by line index."""
        st = _parse("*KEYWORD\n"
                    "*MAT_RIGID\n"
                    "$      MID        RO         E        PR\n"
                    "         9   7.85E-9  210000.0       0.3\n"
                    "$      CMO      CON1      CON2\n"
                    "        -1        40    110111\n"
                    "$LCO or A1        A2        A3        V1        V2"
                    "        V3\n"
                    "        40\n"
                    "*END\n")
        m = st.mat_rigid[9]
        self.assertEqual((m.cmo, m.con1, m.con2), (-1.0, 40, 110111))
        self.assertEqual((m.lco, m.a_vec, m.v_vec), (40, None, None))

    def test_a_partial_card_3_is_read_as_neither_form(self):
        """Field 1 is LCO **or** A1 and the card does not disambiguate. A non-zero
        V1/V2/V3 picks the vector form; a lone non-zero field 1 is LCO. Anything
        else (A2/A3 set with V zero — no valid c = a x v) is neither, and the
        writer's global-axes fallback reports it."""
        for card3, want in (("      40.0", (40, None, None)),
                            ("       0.0       1.0       0.0       0.0"
                             "       0.0       1.0",
                             (0, (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))),
                            ("       1.0       2.0       3.0", (0, None, None)),
                            ("", (0, None, None))):
            with self.subTest(card3=card3):
                st = _parse("*KEYWORD\n*MAT_RIGID\n"
                            "         9   7.85E-9  210000.0       0.3\n"
                            "       0.0       0.0       0.0\n"
                            + (card3 + "\n" if card3 else "")
                            + "*END\n")
                m = st.mat_rigid[9]
                self.assertEqual((m.lco, m.a_vec, m.v_vec), want)

    def _lco_deck(self, *frags):
        return HEAD.replace(
            "*MAT_RIGID\n       2   7.85E-9  210000.0       0.3\n"
            "       1.0       7.0       7.0\n",
            MAT_RIGID_LCO_40) + COORD_40 + "".join(frags) + END

    def test_triad_follows_mat_rigid_lco(self):
        """COORD_40's local x is global +Y and its local y is global -X, so
        N1->N2 must be +Y and N1->N3 must be -X — NOT the global axes."""
        result, starter = _convert(self._lco_deck(_RIGID_LOCAL))
        _n1, xdir, ydir = _triad(starter)
        self.assertEqual(xdir, (0.0, 1.0, 0.0))
        self.assertEqual(ydir, (-1.0, 0.0, 0.0))
        self.assertTrue(_has_warn(result, "axes are taken from LCO=40",
                                  "reproduced EXACTLY"))
        self.assertFalse(_has_warn(result, "INITIALISED TO THE GLOBAL AXES"))

    def test_triad_follows_the_a_v_vector_pair(self):
        """a = +Y, v = +Z  ->  c = a x v = +X, b = c x a = +Z, and the emitted
        triad is (a, b, c) = (X', Y', Z')."""
        deck = HEAD.replace(
            "*MAT_RIGID\n       2   7.85E-9  210000.0       0.3\n"
            "       1.0       7.0       7.0\n",
            MAT_RIGID_A_V) + _RIGID_LOCAL + END
        result, starter = _convert(deck)
        _n1, xdir, ydir = _triad(starter)
        self.assertEqual(xdir, (0.0, 1.0, 0.0))
        self.assertEqual(ydir, (0.0, 0.0, 1.0))
        self.assertTrue(_has_warn(result, "the A1-V3 vector pair",
                                  "reproduced EXACTLY"))

    def test_triad_follows_the_cnrb_cid(self):
        """The CNRB's CID was already parsed and had ZERO consumers, so the triad
        was global-aligned while /SKEW/FIX/40 with exactly the right axes sat in
        the same .rad — and the warning claimed k2rad read neither field."""
        deck = _deck(COORD_40,
                     "*CONSTRAINED_NODAL_RIGID_BODY\n"
                     "        50        40         1\n",
                     "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
                     "        50         1         0        10       2.5\n")
        result, starter = _convert(deck)
        _n1, xdir, ydir = _triad(starter)
        self.assertEqual(xdir, (0.0, 1.0, 0.0))
        self.assertEqual(ydir, (-1.0, 0.0, 0.0))
        self.assertTrue(_has_warn(
            result, "axes are taken from CID=40 on "
            "*CONSTRAINED_NODAL_RIGID_BODY 50", "reproduced EXACTLY"))

    def test_cnrb_without_a_cid_falls_back_and_says_why(self):
        deck = _deck("*CONSTRAINED_NODAL_RIGID_BODY\n"
                     "        50         0         1\n",
                     "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
                     "        50         1         0        10       2.5\n")
        result, starter = _convert(deck)
        _n1, xdir, ydir = _triad(starter)
        self.assertEqual((xdir, ydir), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        self.assertTrue(_has_warn(result, "INITIALISED TO THE GLOBAL AXES",
                                  "*CONSTRAINED_NODAL_RIGID_BODY CID is 0",
                                  "PRINCIPAL INERTIA"))

    def test_mat_rigid_without_card_3_falls_back_and_says_why(self):
        result, starter = _convert(_deck(_RIGID_LOCAL))
        _n1, xdir, ydir = _triad(starter)
        self.assertEqual((xdir, ydir), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        self.assertTrue(_has_warn(result, "INITIALISED TO THE GLOBAL AXES",
                                  "LCO on *MAT_RIGID 2 card 3 is 0",
                                  "PRINCIPAL INERTIA"))

    def test_an_lco_that_is_not_in_the_deck_falls_back_and_says_so(self):
        deck = HEAD.replace(
            "*MAT_RIGID\n       2   7.85E-9  210000.0       0.3\n"
            "       1.0       7.0       7.0\n",
            MAT_RIGID_LCO_40.replace("      40.0", "      77.0")) \
            + _RIGID_LOCAL + END
        result, starter = _convert(deck)
        _n1, xdir, _ydir = _triad(starter)
        self.assertEqual(xdir, (1.0, 0.0, 0.0))
        self.assertTrue(_has_warn(result, "LCO=77", "is not a "
                                  "*DEFINE_COORDINATE_* system in the deck"))

    def test_a_named_frame_does_not_change_the_binding_or_the_scale(self):
        """Only the ORIENTATION changes: the skew still goes in skew_ID, the
        triad legs stay 10% of the body span, and Fscale_Y is still SF."""
        _result, starter = _convert(self._lco_deck(_RIGID_LOCAL))
        skew_id, _data = _blocks(starter, "/SKEW/MOV")[0]
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual((imps[0][4], imps[0][7], imps[0][10]),
                         (skew_id, 0, 2.5))
        n1, xdir, ydir = _triad(starter)
        _sid, data = _blocks(starter, "/SKEW/MOV")[0]
        h = [int(x) for x in _fields(data[0], 10, 4)[:3]]
        pos = {}
        for ln in starter.splitlines():
            m = re.match(r"^\s*(\d+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)"
                         r"\s+(-?[\d.eE+-]+)\s*$", ln)
            if m and int(m.group(1)) in h:
                pos[int(m.group(1))] = tuple(float(m.group(i))
                                             for i in (2, 3, 4))
        for other in (h[1], h[2]):
            leg = math.sqrt(sum((pos[other][i] - n1[i]) ** 2
                                for i in range(3)))
            self.assertAlmostEqual(leg, 0.4, places=9)
        self.assertNotEqual(xdir, ydir)


class TestRbodyMasterCoordinate(unittest.TestCase):
    """The _LOCAL helper triad must not move the written /RBODY master node.

    ``_make_rbodies`` folds the helpers into ``nodes_by_pid[pid]`` (they have to
    be rigid secondaries to co-rotate) and used the SAME list for the centroid,
    so the master landed 0.9% of the body span off the mesh centre — measured
    (22.036364, 2.036364, 2) instead of (22, 2, 2). Inert at runtime (ICoG
    relocates the master to the true CoM and the helpers are massless) but a
    silently wrong pre-run coordinate.
    """

    @staticmethod
    def _master_coord(starter, mesh_nodes):
        rb_master = None
        for _gid, gdata in _blocks(starter, "/GRNOD/NODE"):
            flat = []
            for ln in gdata:
                flat += [int(x) for x in _fields(ln) if x]
            if len(flat) == 1 and flat[0] not in mesh_nodes:
                rb_master = flat[0]
        assert rb_master is not None, "no /RBODY master group"
        for ln in starter.splitlines():
            m = re.match(r"^\s*(\d+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)"
                         r"\s+(-?[\d.eE+-]+)\s*$", ln)
            if m and int(m.group(1)) == rb_master:
                return tuple(float(m.group(i)) for i in (2, 3, 4))
        raise AssertionError("master node not in /NODE")

    def test_mat_rigid_master_is_the_mesh_centroid(self):
        brick = set(range(11, 19))
        _r1, without = _convert(_deck())
        _r2, with_local = _convert(_deck(_RIGID_LOCAL))
        self.assertEqual(self._master_coord(without, brick), (22.0, 2.0, 2.0))
        self.assertEqual(self._master_coord(with_local, brick),
                         (22.0, 2.0, 2.0),
                         "a _LOCAL card must not shift the master")

    def test_cnrb_master_is_the_node_set_centroid(self):
        cnrb = ("*CONSTRAINED_NODAL_RIGID_BODY\n"
                "        50         0         1\n")
        shell = {1, 2, 3, 4}
        _r1, without = _convert(_deck(cnrb))
        _r2, with_local = _convert(_deck(
            cnrb,
            "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
            "        50         1         0        10       2.5\n"))
        # set 1 = nodes 1-4, a 10x10 square in z = 0 -> centroid (5, 5, 0)
        base = self._master_coord(without, shell | set(range(11, 19)))
        self.assertEqual(base, (5.0, 5.0, 0.0))
        self.assertEqual(self._master_coord(with_local,
                                            shell | set(range(11, 19))),
                         base, "a _LOCAL card must not shift the CNRB master")


class TestLocalTriadLifecycle(unittest.TestCase):
    """No triad without a motion, and no motion-less triad without its skew."""

    def test_no_triad_for_a_dof_with_no_dir(self):
        """|DOF| 9/10/11/12 have no /IMP* Dir letter, so the writer refuses the
        card — building a triad for it left three unexplained element-free nodes
        in /NODE and in the /RBODY group, plus a warning promising a co-rotating
        skew the .rad does not contain."""
        for dof in (9, 10, 11, 12):
            with self.subTest(dof=dof):
                result, starter = _convert(_deck(
                    "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
                    f"         2{dof:10d}         0        10       2.5\n"))
                self.assertEqual(_blocks(starter, "/SKEW/MOV"), [])
                self.assertEqual(_imp_cards(starter), [])
                self.assertFalse(_has_warn(result, "CO-ROTATING"))
                self.assertTrue(_has_warn(result, f"DOF={dof}",
                                          "no /IMP* Dir"))
                brick = set(range(11, 19))
                self.assertEqual(
                    TestRbodyMasterCoordinate._master_coord(starter, brick),
                    (22.0, 2.0, 2.0))

    def test_a_dropped_motion_still_gets_its_skew_mov(self):
        """An ELEMENT-FREE *MAT_RIGID part gets no /RBODY, so rbody_info has no
        entry and the motion is dropped — but the prepass has already put three
        helper nodes in /NODE, so the /SKEW/MOV that explains them has to be
        written rather than leaving them unaccounted for and the prepass warning
        describing a skew the .rad does not contain. An unreferenced /SKEW is
        inert."""
        deck = _deck(
            "*PART\nrigid, no elements\n"
            "       3       2       2\n",
            "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL\n"
            "         3         1         0        10       2.5\n")
        result, starter = _convert(deck)
        self.assertTrue(_has_warn(result, "pid=3", "no RBODY found"))
        self.assertEqual(_imp_cards(starter), [],
                         "the motion itself must be dropped")
        skews = _blocks(starter, "/SKEW/MOV")
        self.assertEqual(len(skews), 1,
                         "the triad's own /SKEW/MOV must be in the deck")
        helpers = [int(x) for x in _fields(skews[0][1][0], 10, 4)[:3]]
        node_ids = set()
        for ln in starter.splitlines():
            m = re.match(r"^\s*(\d+)\s+-?[\d.eE+-]+\s+-?[\d.eE+-]+"
                         r"\s+-?[\d.eE+-]+\s*$", ln)
            if m:
                node_ids.add(int(m.group(1)))
        for h in helpers:
            self.assertIn(h, node_ids,
                          f"helper node {h} is not explained by anything")


class TestBodyLoadSummaryWarningsAreGatedOnEmission(unittest.TestCase):
    """A summary paragraph must describe what the .rad CONTAINS.

    Both new ones fired on ``if state.<container>:`` — the presence of a PARSED
    card — so a *LOAD_BODY_VECTOR with a missing LCID warned "load curve 999 not
    found — skipped" and then asserted the /GRAV + /SKEW/FIX mapping anyway. The
    *LOAD_BODY_{X,Y,Z} paragraph next to them was already gated on emission.
    """

    def test_vector_summary_is_silent_when_the_curve_is_missing(self):
        result, starter = _convert(_deck(_body_vector(lcid=999)))
        self.assertEqual(_grav_card(starter), [])
        self.assertTrue(_has_warn(result, "*LOAD_BODY_VECTOR",
                                  "load curve 999 not found"))
        self.assertFalse(_has_warn(result, "ONE /GRAV with DIR=X"))

    def test_rotational_summary_and_header_are_silent_when_nothing_emitted(self):
        result, starter = _convert(_deck(_body_rot("Z", lcid=999)))
        self.assertEqual(_centri_card(starter), [])
        self.assertTrue(_has_warn(result, "*LOAD_BODY_RZ",
                                  "curve 999 not found"))
        self.assertFalse(_has_warn(result, "/LOAD/CENTRI with fct_IDT"))
        self.assertFalse(_has_warn(result, "Dir is written as XX/YY/ZZ"))
        self.assertNotIn("ROTATIONAL BODY LOADS", starter,
                         "no dangling section header")

    def test_the_summaries_still_fire_when_a_card_is_emitted(self):
        result, starter = _convert(_deck(_body_vector(), _body_rot("Z")))
        self.assertEqual(len(_grav_card(starter)), 1)
        self.assertEqual(len(_centri_card(starter)), 1)
        self.assertTrue(_has_warn(result, "ONE /GRAV with DIR=X"))
        self.assertTrue(_has_warn(result, "/LOAD/CENTRI with fct_IDT"))
        self.assertIn("ROTATIONAL BODY LOADS", starter)

    def test_a_missing_rotational_curve_next_to_a_good_one_keeps_the_header(self):
        result, starter = _convert(_deck(_body_rot("Z"),
                                         _body_rot("X", lcid=999)))
        self.assertEqual(len(_centri_card(starter)), 1)
        self.assertIn("ROTATIONAL BODY LOADS", starter)
        self.assertTrue(_has_warn(result, "*LOAD_BODY_RX",
                                  "curve 999 not found"))


class TestGrnodIdAllocation(unittest.TestCase):
    """Both branches of _make_imposed_motions_set draw from next_grnod_id().

    k2rad re-emits every user *SET_NODE under its own SID, so a set at or above
    the auto-id base (90001) collides with a synthesized /GRNOD id — starter
    ERROR 79 DUPLICATE ID / IN NODE GROUP DEFINITION and no restart file. The
    motion branch was fixed; the zero-scale /BCS branch four lines away still
    used the unguarded next_id().
    """

    @staticmethod
    def _run(sf):
        """_make_imposed_motions_set on a state whose ONLY node sets sit exactly
        on the auto-id base, so an unguarded next_id() lands on one of them.
        Driven directly: on a full deck the /RBODY groups (still next_id(), the
        pre-existing hazard the docstring names) consume the low auto ids first
        and hide which branch allocated what."""
        from k2rad.state import NodeData, PrescribedMotionSet
        from k2rad.writer.loads import _make_imposed_motions_set
        st = ConversionState()
        st.nodes = {1: NodeData(0.0, 0.0, 0.0), 2: NodeData(1.0, 0.0, 0.0)}
        st.node_sets[90001] = ("high_a", [1, 2])
        st.node_sets[90002] = ("high_b", [1, 2])
        st.node_sets[90003] = ("high_c", [1, 2])
        st.prescribed_motion_sets.append(
            PrescribedMotionSet(90001, 1, 2, 10, sf, 1e28, 0.0))
        lines = _make_imposed_motions_set(st)
        ids = [int(ln.split("/")[-1]) for ln in lines
               if ln.startswith("/GRNOD/NODE/")]
        return st, ids

    def test_bcs_grnod_dodges_a_high_user_set_id(self):
        st, ids = self._run(0.0)
        self.assertEqual(len(ids), 1)
        self.assertNotIn(ids[0], st.node_sets,
                         f"/GRNOD/{ids[0]} collides with a user *SET_NODE — "
                         "starter ERROR 79 DUPLICATE ID")

    def test_motion_grnod_dodges_a_high_user_set_id(self):
        st, ids = self._run(1.0)
        self.assertEqual(len(ids), 1)
        self.assertNotIn(ids[0], st.node_sets)


class TestVidRegistries(unittest.TestCase):
    def test_vid_may_name_a_define_coordinate_nodes_system(self):
        """*DEFINE_COORDINATE_NODES emits its /SKEW under `cid` too
        (_emit_skew_from_nodes), so a |DOF| 4/8 card naming one resolves. Leaving
        coord_nodes out of the fallback sent it down the "no /SKEW exists — THE
        DIRECTION IS WRONG" exit while the skew sat in the same .rad."""
        deck = _deck("*DEFINE_COORDINATE_NODES\n"
                     "        45         1         2         4         X\n",
                     "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1         4         0        10       1.0"
                     "        45\n")
        result, starter = _convert(deck)
        imps = _imp_cards(starter)
        self.assertEqual(len(imps), 1)
        self.assertEqual(imps[0][4], 45,
                         "the *DEFINE_COORDINATE_NODES skew must bind")
        self.assertFalse(_has_warn(result, "THE DIRECTION IS WRONG"))

    def test_an_unknown_vid_still_warns(self):
        deck = _deck("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                     "         1         4         0        10       1.0"
                     "        66\n")
        result, _starter = _convert(deck)
        self.assertTrue(_has_warn(result, "*DEFINE_VECTOR 66",
                                  "THE DIRECTION IS WRONG"))


class TestNegativeDofLockPrecondition(unittest.TestCase):
    def test_lock_warning_names_the_cmo_precondition(self):
        """DOF -4/-8 "only applies to rigid bodies if |CMO| = 2 on *MAT_RIGID or
        *CONSTRAINED_NODAL_RIGID_BODY" (p.750). k2rad emits the lock either way
        (the manual does not say what LS-DYNA does instead), so the warning has
        to name the precondition."""
        deck = _deck(VECTOR_Z,
                     "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
                     "         2        -4         0        10       1.0"
                     "        30\n")
        result, starter = _convert(deck)
        self.assertEqual(len(_imp_cards(starter)), 3, "1 driven + 2 locked")
        self.assertTrue(_has_warn(result, "DOF=-4", "|CMO| = 2",
                                  "OVER-CONSTRAINT"))


class TestLoadBodyGeneralizedSpellings(unittest.TestCase):
    def test_all_three_option_spellings_are_registered(self):
        """The manual's name is *LOAD_BODY_GENERALIZED_OPTION with OPTION in
        {SET_NODE, SET_PART} (p.33-31), and only the bare form was registered —
        so the two spellings a real deck actually uses still arrived as mute
        skipped_keywords entries, which is exactly what the registration exists
        to prevent."""
        for kw in ("LOAD_BODY_GENERALIZED",
                   "LOAD_BODY_GENERALIZED_SET_NODE",
                   "LOAD_BODY_GENERALIZED_SET_PART"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_each_spelling_is_skipped_with_a_reason(self):
        for kw in ("LOAD_BODY_GENERALIZED",
                   "LOAD_BODY_GENERALIZED_SET_NODE",
                   "LOAD_BODY_GENERALIZED_SET_PART"):
            with self.subTest(kw=kw):
                result, starter = _convert(_deck(
                    f"*{kw}\n"
                    "         1         0        10         0       0.0"
                    "       0.0       0.0\n"
                    "       0.0       0.0    -9810.0       0.0       0.0"
                    "       0.0         0\n"))
                self.assertEqual(_grav_card(starter), [])
                self.assertEqual(_centri_card(starter), [])
                self.assertTrue(_has_warn(result, f"*{kw}",
                                          "no OpenRadioss equivalent"))
                self.assertIn(kw, result.skipped_keywords)


if __name__ == "__main__":
    unittest.main()
