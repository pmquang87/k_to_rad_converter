"""Tests for the rigid-body inertia + load-distribution batch:

  *PART_INERTIA (+ every option stacking)   -> /RBODY Mass/Jxx..Jxz, ICoG=4,
                                               main node at the stated CoM,
                                               /INIVEL/TRA + /INIVEL/ROT
  *CONSTRAINED_NODAL_RIGID_BODY_INERTIA     -> the same transfer on the CNRB path
  *PART_CONTACT                             -> OPTT into the /PART Thick column
  *CONSTRAINED_INTERPOLATION[_LOCAL]        -> /RBE3 + one /GRNOD/NODE per set

Seven conventions decide whether these convert correctly and NOT ONE of them is
visible by eye in the .rad:

* the PRODUCT-OF-INERTIA SIGN. Both sides define the off-diagonals as the inertia
  TENSOR component, i.e. minus the product of inertia, so the transfer is
  verbatim. *PART Remark 4 (Vol I R17 p.37-14): "Note that the off-diagonal terms
  of the inertia tensor are opposite in sign from the products of inertia."
  Radioss matches — ``inirby.F:154-160`` inserts ``Jxy`` into tensor slot (1,2)
  with a PLUS sign while ``:331-339`` accumulates the mesh contribution into the
  same slot as ``RBY(2)=RBY(2)-XY*XMG``, and two quantities summed into one entry
  must share one convention. Negating would be silently wrong in a way only a
  starter WARNING 542 ("NONPHYSICAL INERTIA") ever hints at.
* the FIELD ORDER. LS-DYNA card 4 is ``IXX IXY IXZ IYY IYZ IZZ`` on one line;
  Radioss is ``Jxx Jyy Jzz`` then ``Jxy Jyz Jxz`` on two. The second Radioss line
  is NOT ``Jxy Jxz Jyz``. Pinned empirically: a body fed ``Jxx=100 Jyy=200 Jzz=250
  / Jxy=10 Jyz=0 Jxz=0`` echoed ``ADDED INERTIA 100.0 200.0 250.0 10.00 0.000
  0.000``, printed in reader-storage order Mass/Jxx/Jyy/Jzz/Jxy/Jyz/Jxz
  (``hm_read_rbody.F:553``).
* ICoG = 4, and only 4. It is the sole value that means "defined rather than
  calculated from the finite element mesh": ``inirby.F:266-282`` pins the COG at
  the main node and sets ``MASRB=MS(M)`` alone, and the gate ``IF(ICDG<=3)`` at
  ``:322`` skips every secondary contribution and all parallel-axis transport.
  Measured on five identical bodies (main node at x=n*100, secondaries 20 further
  out, user Mass 1e-6, mesh mass 7.86e-7): ICoG 1 -> COG 108.80 / mass 1.786e-6,
  2 -> 220.0, 3 -> 300.0 / 1.786e-6, 4 -> 400.0 / 1.000e-6, blank -> = 1. Any
  value but 4 double-counts the mesh; 1 and 2 also MOVE the COG off XC/YC/ZC.
* IRCS=1 goes through /RBODY ``Skew_ID`` and nowhere else. ``inirby.F:161-164``
  calls ``CHBAS(SKEW(1,NOSKEW), RBY(1,NRB))``, and ``chbas.F`` computes
  ``M_out = A*M_in*A^T`` with ``A`` filled column-major from ``SKEW``, i.e.
  ``A = [X'|Y'|Z']`` = R (local->global) -> ``J_global = R*J_local*R^T``, which is
  LS-DYNA's IRCS=1 definition exactly. Validated end-to-end: a deck stating
  ``J_local = diag(20,25,30)`` in a frame with X'=Z, Y'=X, Z'=Y came back from the
  starter as ``NEW INERTIA xx yy zz 25.0 30.0 20.0`` — the hand-computed
  ``R J R^T`` — with NORMAL TERMINATION, 0 ERROR, 0 WARNING.
  Its companion trap: /SKEW/FIX's two vector cards are the local Y' and Z', NOT
  X' and Y', and the card has THREE data lines because the origin line comes
  first (omitting it is WARNING 100217 and silently shifts Y' into the origin).
* the /RBE3 ``Trarot`` SUB-COLUMNS. ``CARD("%10d   %1d%1d%1d %1d%1d%1d...")``
  packs six booleans inside a 10-wide field at FIXED offsets: three blanks, TxTyTz,
  one blank, RxRyRz. ``%1d`` reads exactly one character at a fixed position, so a
  right-aligned ``      111111`` instead of ``   111 111`` drops the three
  translations — measured, and the run still TERMINATED NORMALLY with only
  WARNING 100213/100214/100217 and ``REFERENCE DOF(Trarot) 000 111``. A physically
  wrong constraint delivered with zero errors.
* the /RBE3 SET SPLIT. LS-DYNA gives every independent node its own IDOF mask and
  weight; Radioss gives every SET one scalar WTi and one Trarot_Mi. Collapsing them
  into one set (all dyna2rad can do) throws the weights away — its echo reads
  ``1.0 1.0 1.0 0.0 0.0 0.0`` for every node whatever the deck said. k2rad groups
  on (IDOF, weight, CIDI); validated against the starter at IPRI=5, which echoed
  2.0/2.0/2.0/0/0/0, 3.0x4, 4.0x5 and ``0 0 5.0 0 0 0`` for IDOF 123 / 1234 /
  12345 / 3 with weights 2/3/4/5 — exactly the deck.
* POSITIONAL CONSUMPTION (the PR #117 lesson). A blank line inside a `*PART` or
  CNRB option block is a card of all-DEFAULTS, not whitespace: LS-PrePost writes
  an all-default card as blanks and the parser preserves it as a card placeholder.
  Skipping one shifts every card below it up by one — and because `_INERTIA` card 6
  is conditional on the ``IRCS`` VALUE read from card 3, a skipped blank card 3
  makes IRCS read 0, card 6 is not consumed, and on `*PART` the NEXT part's HEADING
  is eaten as a data card. Measured before the fix, aliasing the old stride-of-2
  loop onto `*PART_INERTIA` registered a phantom ``/PART/4321`` from the
  ``IXX=4321.0`` card, with secid=0, mid=0 and a coordinate card for a title.

The corpus has ZERO decks with any of these four keywords (two independent passes
over 618 files across the repo, E:\\openradioss_run and E:\\foxcore_data, plus a
sniff of 6804 extensionless files), so nothing here can be validated by a sweep:
the expectations are column-exact card lines built from the CFG FORMAT blocks plus
hand-computed values.

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_motion_load_variants.py and tests/test_rwall_variants.py).
"""

import os
import re
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                                    # noqa: E402
from k2rad.assembly import _OFFSET_SPECS                     # noqa: E402
from k2rad.handlers import (HANDLERS, dispatch,              # noqa: E402
                            dof_digits_to_flags,
                            _cnrb_option_keywords,
                            _part_option_keywords, _part_options)
from k2rad.parser import parse_k_file                        # noqa: E402
from k2rad.state import ConversionState                      # noqa: E402
from k2rad.writer.rbe3 import _trarot                        # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Deck fragments
#
# Nodes 1-4   = shell 1 (part 1, deformable *MAT_ELASTIC), z = 0 plane
# Nodes 11-18 = the *MAT_RIGID brick (part 2), a 4x4x4 cube at x in [20, 24]
# Node 200    = a free node, used as the /RBE3 dependent node
# ─────────────────────────────────────────────────────────────────────────────

HEAD = """\
*KEYWORD
*TITLE
rigid inertia / rbe3 test deck
*CONTROL_TERMINATION
      0.01
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
      11            20.0             0.0             0.0
      12            24.0             0.0             0.0
      13            24.0             4.0             0.0
      14            20.0             4.0             0.0
      15            20.0             0.0             4.0
      16            24.0             0.0             4.0
      17            24.0             4.0             4.0
      18            20.0             4.0             4.0
      99            30.0            30.0            30.0
     200            50.0            50.0            50.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*ELEMENT_SOLID
      11       2      11      12      13      14      15      16      17      18
*SECTION_SHELL
       1       2
       1.0       1.0       1.0       1.0
*SECTION_SOLID
       2       1
*MAT_ELASTIC
       1   7.85E-9  210000.0       0.3
*MAT_RIGID
       2   7.85E-9  210000.0       0.3
       1.0       0.0       0.0
"""

END = "*END\n"

#: The deformable shell part.
PART_SHELL = """\
*PART
shells
       1       1       1
"""

#: The plain rigid brick part (no options).
PART_RIGID = """\
*PART
rigid brick
       2       2       2
"""

#: *PART_INERTIA on the rigid brick.
#: Card 3  XC=22.05  YC=2.125  ZC=0.75  TM=7.25  IRCS=0  NODEID=0
#: Card 4  IXX=20  IXY=1  IXZ=3  IYY=25  IYZ=2  IZZ=30   <- LS-DYNA field order
#: Card 5  VTX=1.5  VTY=0  VTZ=0  VRX=0  VRY=0  VRZ=2.5
PART_INERTIA = """\
*PART_INERTIA
rigid brick
       2       2       2
     22.05      2.125       0.75      7.25         0         0
      20.0       1.0       3.0      25.0       2.0      30.0
       1.5       0.0       0.0       0.0       0.0       2.5
"""

#: *DEFINE_COORDINATE_SYSTEM 7: origin at the global origin, local x along +Y,
#: in-plane point on -X.  ex=(0,1,0)  ey=(-1,0,0)  ez=(0,0,1)  (+90 deg about Z).
COORD_7 = """\
*DEFINE_COORDINATE_SYSTEM
         7       0.0       0.0       0.0       0.0       1.0       0.0
      -1.0       0.0       0.0
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
# .rad readers — every one reads by COLUMN, not by whitespace split, because a
# mis-positioned sub-field is the failure mode these tests exist to catch.
# ─────────────────────────────────────────────────────────────────────────────

def _blocks(starter, header):
    """Every /<header>/<id> block as [(id, [data lines])], comments stripped."""
    lines = starter.splitlines()
    pat = re.compile(r"^" + re.escape(header) + r"/(\d+)\s*$")
    out = []
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
        out.append((int(m.group(1)), data))
    return out


def _rbody_cards(starter):
    """[(id, dict)] for every /RBODY, read by column.

    Card 1 is ``node_ID(I10) sens_ID(I10) Skew_ID(I10) Ispher(I10) Mass(F20)
    grnd_ID(I10) Ikrem(I10) ICoG(I10) surf_ID(I10)`` = 100 cols; the CNRB path
    adds a 10th ``Ifail`` column. Then ``Jxx Jyy Jzz`` / ``Jxy Jyz Jxz`` (3 x F20
    each) and ``Ioptoff Iexpams [Ifail]``.
    """
    out = []
    for rid, data in _blocks(starter, "/RBODY"):
        c1, j1, j2, flags = data[0], data[1], data[2], data[3]
        assert len(c1) in (100, 110), f"/RBODY card 1 is {len(c1)} cols"
        out.append((rid, {
            "node_ID": int(c1[0:10]), "sens_ID": int(c1[10:20]),
            "Skew_ID": int(c1[20:30]), "Ispher": int(c1[30:40]),
            "Mass": float(c1[40:60]), "grnd_ID": int(c1[60:70]),
            "Ikrem": int(c1[70:80]), "ICoG": int(c1[80:90]),
            "surf_ID": int(c1[90:100]),
            "Jxx": float(j1[0:20]), "Jyy": float(j1[20:40]),
            "Jzz": float(j1[40:60]),
            "Jxy": float(j2[0:20]), "Jyz": float(j2[20:40]),
            "Jxz": float(j2[40:60]),
            "Ioptoff": int(flags[0:10]), "Iexpams": int(flags[10:20]),
        }))
    return out


def _part_cards(starter):
    """{pid: (prop_ID, mat_ID, subset_ID, Thick, raw_line)} for every /PART.

    ``Thick`` is cols 31-50 (F20) per radioss51/PART/part.cfg; ``None`` when the
    line stops at 30 cols, which is what "no OPTT" must produce byte for byte.
    """
    out = {}
    for pid, data in _blocks(starter, "/PART"):
        ln = data[0]
        thick = float(ln[30:50]) if len(ln) > 30 else None
        out[pid] = (int(ln[0:10]), int(ln[10:20]), int(ln[20:30]), thick, ln)
    return out


def _rbe3_cards(starter):
    """[(id, dep dict, [set dicts])] for every /RBE3, read by column.

    Dependent card: ``Node_IDr(1-10) Trarot_ref(11-20) N_set(21-30)
    I_modif(31-40)``. Per-set card: ``WTi(1-20) Trarot_Mi(21-30) skew_IDi(31-40)
    grnod_IDi(41-50)``. The ``Trarot`` fields are returned RAW so a test can
    assert the exact sub-column pattern.
    """
    out = []
    for rid, data in _blocks(starter, "/RBE3"):
        d = data[0]
        assert len(d) == 40, f"/RBE3 dependent card is {len(d)} cols, expected 40"
        dep = {"Node_IDr": int(d[0:10]), "Trarot_ref": d[10:20],
               "N_set": int(d[20:30]), "I_modif": int(d[30:40])}
        sets = []
        for ln in data[1:]:
            assert len(ln) == 50, f"/RBE3 set card is {len(ln)} cols, expected 50"
            sets.append({"WTi": float(ln[0:20]), "Trarot_Mi": ln[20:30],
                         "skew_IDi": int(ln[30:40]),
                         "grnod_IDi": int(ln[40:50])})
        out.append((rid, dep, sets))
    return out


def _grnod_nodes(starter, gid):
    """The node id list of one /GRNOD/NODE, read as 10-wide columns."""
    for g, data in _blocks(starter, "/GRNOD/NODE"):
        if g != gid:
            continue
        nids = []
        for ln in data:
            nids += [int(ln[i:i + 10]) for i in range(0, len(ln), 10)
                     if ln[i:i + 10].strip()]
        return nids
    raise AssertionError(f"/GRNOD/NODE/{gid} not in the deck")


def _inivel_cards(starter):
    """[(kind, id, (Vx,Vy,Vz), Gnod_id, Skew_id)] for every /INIVEL/TRA|ROT."""
    out = []
    for kind in ("TRA", "ROT"):
        for iid, data in _blocks(starter, f"/INIVEL/{kind}"):
            ln = data[0]
            out.append((kind, iid,
                        (float(ln[0:20]), float(ln[20:40]), float(ln[40:60])),
                        int(ln[60:70]), int(ln[70:80] or 0)))
    return out


def _skew_fix(starter, skew_id):
    """(origin, y_axis, z_axis) of one /SKEW/FIX — three data lines, in that
    order. The FIRST is the ORIGIN; forgetting it is WARNING 100217."""
    for sid, data in _blocks(starter, "/SKEW/FIX"):
        if sid != skew_id:
            continue
        assert len(data) == 3, (
            f"/SKEW/FIX/{sid} has {len(data)} data lines, expected 3 "
            "(origin, Y', Z')")
        return tuple(tuple(float(ln[i:i + 20]) for i in (0, 20, 40))
                     for ln in data)
    raise AssertionError(f"/SKEW/FIX/{skew_id} not in the deck")


def _node_coords(starter, nid):
    """(x, y, z) of one /NODE row (I10 + 3 x F20)."""
    for ln in starter.splitlines():
        if len(ln) >= 70 and ln[0:10].strip().isdigit() \
                and int(ln[0:10]) == nid:
            try:
                return (float(ln[10:30]), float(ln[30:50]), float(ln[50:70]))
            except ValueError:
                continue
    raise AssertionError(f"/NODE {nid} not in the deck")


def _warned(result, *needles):
    return any(all(n in w for n in needles) for w in result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# A) *PART_INERTIA
# ═════════════════════════════════════════════════════════════════════════════

class PartInertiaTests(unittest.TestCase):

    def test_mesh_survives_and_inertia_lands(self):
        """The whole point: the part card is parsed, so the MESH survives, and the
        inertia cards reach the /RBODY.

        Before this batch ``*PART_INERTIA`` was not a dispatch key at all: the
        block went to skipped_keywords, the part was never registered, and because
        ``_make_parts_and_elements`` emits elements inside the ``state.parts``
        loop, every element on it was dropped (measured: "SKIPPED:
        ['PART_INERTIA']" plus a MESH LOSS warning, and no /PART/2 in the starter).
        """
        res, st = _convert(_deck(PART_SHELL, PART_INERTIA))
        self.assertEqual(res.skipped_keywords, [])
        parts = _part_cards(st)
        self.assertIn(2, parts, "the *PART_INERTIA part is missing from the deck")
        self.assertIn("/BRICK/2", st, "the part's solid element was dropped")
        self.assertFalse(_warned(res, "MESH LOSS"))

    def test_inertia_tensor_field_order_and_sign(self):
        """``Jxx Jyy Jzz`` / ``Jxy Jyz Jxz`` from ``IXX IXY IXZ IYY IYZ IZZ``.

        A pure permutation with NO sign change — both sides hold the inertia
        TENSOR component (*PART Remark 4; ``inirby.F:154-160`` vs ``:331-339``).
        The deck's card 4 is ``20 1 3 25 2 30``, so a negating or mis-ordered
        writer produces a different set of six numbers here and nothing else in
        the .rad reveals it.
        """
        _res, st = _convert(_deck(PART_SHELL, PART_INERTIA))
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["Jxx"], 20.0)     # IXX
        self.assertEqual(rb["Jyy"], 25.0)     # IYY, card-4 field 4
        self.assertEqual(rb["Jzz"], 30.0)     # IZZ, card-4 field 6
        self.assertEqual(rb["Jxy"], 1.0)      # IXY, verbatim — NOT -1.0
        self.assertEqual(rb["Jyz"], 2.0)      # IYZ, card-4 field 5
        self.assertEqual(rb["Jxz"], 3.0)      # IXZ, card-4 field 3
        self.assertEqual(rb["Mass"], 7.25)    # TM

    def test_icog_is_4_and_main_node_is_the_stated_com(self):
        """ICoG=4, and the main node sits exactly on XC/YC/ZC.

        4 is the only flag that ignores the mesh contribution and leaves the main
        node where the card put it (``inirby.F:266-282`` + the ``IF(ICDG<=3)``
        gate at ``:322``). Confirmed end-to-end: the starter echoed ``CENTER OF
        MASS FLAG 4``, ``NEW X,Y,Z 22.05 2.125 0.75`` and ``NEW MASS 7.250000`` —
        the mesh's own mass absent from the total.
        """
        _res, st = _convert(_deck(PART_SHELL, PART_INERTIA))
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["ICoG"], 4)
        self.assertEqual(rb["Skew_ID"], 0)          # IRCS = 0 binds nothing
        self.assertEqual(_node_coords(st, rb["node_ID"]),
                         (22.05, 2.125, 0.75))
        # The main node must be element-free (ICoG=4 still adds ITS OWN nodal mass
        # and rotary inertia, inirby.F:146,166-169; and a meshed main node is
        # WARNING 448 / ERROR 1066 under AMS).
        self.assertNotIn(rb["node_ID"], range(11, 19))
        self.assertNotIn(rb["node_ID"], _grnod_nodes(st, rb["grnd_ID"]))

    def test_nodeid_beats_xc_yc_zc_and_is_reused_when_free(self):
        """"If nodal point NODEID is defined, XC, YC, and ZC are ignored, and the
        coordinates of NODEID are taken as the center of mass" (p.37-7).

        Node 99 is element-free, so it is reused as the main node directly.
        dyna2rad loses this outright: with NODEID != 0 the starter reports the
        primary node at (0,0,0) and BOTH NODEID's coordinates and XC/YC/ZC are
        discarded (reproduced on three separate decks).
        """
        deck = _deck(PART_SHELL, PART_INERTIA.replace(
            "     22.05      2.125       0.75      7.25         0         0",
            "     22.05      2.125       0.75      7.25         0        99"))
        _res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["node_ID"], 99)
        self.assertEqual(_node_coords(st, 99), (30.0, 30.0, 30.0))

    def test_meshed_nodeid_is_copied_to_a_free_node(self):
        """A NODEID that carries elements is copied, not reused.

        Node 11 is a corner of the brick. ICoG=4 always adds the main node's own
        ``MS(M)``/``IN(M)`` on top of the user's Mass, so reusing a mesh node
        would make the body heavier than TM — and a main node on an element is
        WARNING 448, or the fatal ERROR 1066 with --ams.
        """
        deck = _deck(PART_SHELL, PART_INERTIA.replace(
            "     22.05      2.125       0.75      7.25         0         0",
            "     22.05      2.125       0.75      7.25         0        11"))
        res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertNotEqual(rb["node_ID"], 11)
        self.assertEqual(_node_coords(st, rb["node_ID"]), (20.0, 0.0, 0.0))
        self.assertTrue(_warned(res, "NODEID=11", "attached to elements"))

    def test_card5_velocity_becomes_inivel_on_the_main_node_only(self):
        """``VTX..VTZ`` -> /INIVEL/TRA and ``VRX..VRZ`` -> /INIVEL/ROT, both on a
        group holding ONLY the /RBODY main node.

        /INIVEL/ROT has no axis and no origin — it writes straight into the nodal
        ``VR`` (``hm_read_inivel.F:535-541``) — and ``inirby.F`` then propagates
        the main node's V/VR to the secondaries as ``V(:,N) = V(:,M) + w x (X_N -
        X_M)``. With ICoG=4 that origin IS the stated centre of mass, so the
        one-node group reproduces "velocity about the COG" exactly, with no
        correction term and without /INIVEL/AXIS (which needs a /FRAME and may not
        share a node with /TRA or /ROT).
        """
        _res, st = _convert(_deck(PART_SHELL, PART_INERTIA))
        (_rid, rb), = _rbody_cards(st)
        cards = _inivel_cards(st)
        self.assertEqual(len(cards), 2, cards)
        tra = [c for c in cards if c[0] == "TRA"][0]
        rot = [c for c in cards if c[0] == "ROT"][0]
        self.assertEqual(tra[2], (1.5, 0.0, 0.0))
        self.assertEqual(rot[2], (0.0, 0.0, 2.5))
        self.assertEqual(tra[3], rot[3], "TRA and ROT must share one group")
        self.assertEqual(_grnod_nodes(st, tra[3]), [rb["node_ID"]])

    def test_zero_velocity_vector_emits_no_card(self):
        deck = _deck(PART_SHELL, PART_INERTIA.replace(
            "       1.5       0.0       0.0       0.0       0.0       2.5",
            "       0.0       0.0       0.0       0.0       0.0       2.5"))
        _res, st = _convert(deck)
        kinds = sorted(c[0] for c in _inivel_cards(st))
        self.assertEqual(kinds, ["ROT"], "a zero 3-vector must emit nothing")

    def test_initial_velocity_rigid_body_wins_over_card5(self):
        """*PART Remark 5: "The *INITIAL_VELOCITY card may overwrite the initial
        velocity of the rigid body."

        Radioss /INIVEL ASSIGNS rather than accumulates, so emitting both would
        leave the result decided by card order. The card-5 values are dropped with
        a warning instead of being written to be silently overwritten.
        """
        deck = _deck(PART_SHELL, PART_INERTIA,
                     "*INITIAL_VELOCITY_RIGID_BODY\n"
                     "         2       9.0       0.0       0.0\n")
        res, st = _convert(deck)
        vs = [c[2] for c in _inivel_cards(st)]
        self.assertIn((9.0, 0.0, 0.0), vs)
        self.assertNotIn((1.5, 0.0, 0.0), vs)
        self.assertTrue(_warned(res, "*INITIAL_VELOCITY_RIGID_BODY also drives"))

    def test_incomplete_inertia_drops_the_override_loudly(self):
        """A blank ``TM`` or a zero inertia diagonal is a source-deck defect —
        *PART Remark 3: "all mass and inertia properties of the body must be
        specified.  There are no default values."

        ICoG=4 throws the mesh contribution away, so writing the card as-is would
        be starter ERROR 679 (total mass <= 1e-30) or ERROR 274 (min principal
        inertia <= 0). The override is dropped and the mesh-derived body kept —
        which is what LS-DYNA does WITHOUT the option.
        """
        for bad, needle in (
            ("     22.05      2.125       0.75       0.0         0         0",
             "ERROR 679"),
        ):
            with self.subTest(needle=needle):
                deck = _deck(PART_SHELL, PART_INERTIA.replace(
                    "     22.05      2.125       0.75      7.25"
                    "         0         0", bad))
                res, st = _convert(deck)
                (_rid, rb), = _rbody_cards(st)
                self.assertEqual(rb["ICoG"], 0, "override must be refused")
                self.assertEqual(rb["Jxx"], 0.0)
                self.assertTrue(_warned(res, "INCOMPLETE", needle))
        # zero inertia tensor, TM fine
        deck = _deck(PART_SHELL, PART_INERTIA.replace(
            "      20.0       1.0       3.0      25.0       2.0      30.0",
            "       0.0       1.0       3.0       0.0       2.0       0.0"))
        res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["ICoG"], 0)
        self.assertTrue(_warned(res, "INCOMPLETE", "ERROR 274"))

    def test_all_blank_inertia_cards_are_no_override(self):
        """LS-PrePost writes an all-blank card set for an option that is present
        but unused. Remark 3 forbids DERIVING values, so "all blank" can only mean
        "no override" — never Mass = 0 with ICoG = 4."""
        res, st = _convert(_deck(PART_SHELL, """\
*PART_INERTIA
rigid brick
       2       2       2

""" + "\n\n"))
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["ICoG"], 0)
        self.assertEqual(rb["Mass"], 0.0)
        self.assertTrue(_warned(res, "entirely blank"))

    def test_non_rigid_part_inertia_is_warned_and_the_mesh_survives(self):
        """"This applies to rigid bodies (see *MAT_RIGID) only" (p.37-2).

        dyna2rad drops a deformable `*PART_INERTIA` SILENTLY — its part selection
        filters on ``MID in *MAT_RIGID/020/009`` — so the deck quietly loses TM.
        Here the mesh still converts and the loss is named with the number.
        """
        res, st = _convert(_deck(PART_RIGID, """\
*PART_INERTIA
shells
       1       1       1
      5.0       5.0       0.0      3.25         0         0
      10.0       0.0       0.0      11.0       0.0      12.0
       0.0       0.0       0.0       0.0       0.0       0.0
"""))
        self.assertIn(1, _part_cards(st))
        self.assertIn("/SHELL/1", st)
        self.assertTrue(_warned(res, "*PART_INERTIA 1", "not a *MAT_RIGID",
                                "TM=3.25"))

    def test_part_inertia_without_any_mat_rigid_still_warns(self):
        """The early return of _make_rbodies must not swallow the report."""
        deck = HEAD.replace("""*MAT_RIGID
       2   7.85E-9  210000.0       0.3
       1.0       0.0       0.0
""", "*MAT_ELASTIC\n       2   7.85E-9  210000.0       0.3\n")
        res, _st = _convert(deck + PART_SHELL + PART_INERTIA + END)
        self.assertTrue(_warned(res, "*PART_INERTIA 2", "DROPPED"))


# ═════════════════════════════════════════════════════════════════════════════
# IRCS: the local inertia frame
# ═════════════════════════════════════════════════════════════════════════════

class InertiaLocalFrameTests(unittest.TestCase):

    #: IRCS = 1 with card 6 giving two vectors: local x along +Z, in-plane vector
    #: +X.  ex = (0,0,1); ez = norm(XL x XLIP) = (0,1,0); ey = ez x ex = (1,0,0).
    #: So X'=Z, Y'=X, Z'=Y.
    IRCS_VECTORS = """\
*PART_INERTIA
rigid brick
       2       2       2
      22.0       2.00       2.00      7.25         1         0
      20.0       0.0       0.0      25.0       0.0      30.0
       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       1.0       1.0       0.0       0.0
"""

    def test_ircs1_vectors_build_a_three_line_skew_fix(self):
        """/SKEW/FIX carries the local Y' and Z' — NOT X' and Y' — and has THREE
        data lines because the ORIGIN comes first.

        The origin is (0,0,0) by *PART Remark 4 ("The reference coordinate system
        defines the orientation of the axes, not the origin"), and /RBODY never
        reads ``SKEW(10:12)`` anyway.

        End-to-end proof that the whole route is right: this deck states
        ``J_local = diag(20,25,30)`` and the starter echoed ``NEW INERTIA xx yy
        zz 25.0 30.0 20.0`` = the hand-computed ``R J_local R^T`` for X'=Z, Y'=X,
        Z'=Y, with NORMAL TERMINATION, 0 ERROR, 0 WARNING.
        """
        _res, st = _convert(_deck(PART_SHELL, self.IRCS_VECTORS))
        (_rid, rb), = _rbody_cards(st)
        self.assertNotEqual(rb["Skew_ID"], 0)
        origin, yax, zax = _skew_fix(st, rb["Skew_ID"])
        self.assertEqual(origin, (0.0, 0.0, 0.0))
        self.assertEqual(yax, (1.0, 0.0, 0.0))       # Y' = global X
        self.assertEqual(zax, (0.0, 1.0, 0.0))       # Z' = global Y
        # The tensor itself is written unrotated — the STARTER rotates it.
        self.assertEqual((rb["Jxx"], rb["Jyy"], rb["Jzz"]), (20.0, 25.0, 30.0))

    def test_ircs1_with_cid_binds_that_skew_1_to_1(self):
        deck = _deck(PART_SHELL, COORD_7, self.IRCS_VECTORS.replace(
            "       0.0       0.0       1.0       1.0       0.0       0.0",
            "       0.0       0.0       0.0       0.0       0.0       0.0"
            "         7"))
        _res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["Skew_ID"], 7)

    def test_ircs1_with_dangling_cid_warns_and_stays_global(self):
        """A dangling ``Skew_ID`` is starter ERROR 137 (WRONG SKEW SYSTEM), a hard
        stop — so the reference is checked here and dropped, loudly."""
        deck = _deck(PART_SHELL, self.IRCS_VECTORS.replace(
            "       0.0       0.0       1.0       1.0       0.0       0.0",
            "       0.0       0.0       0.0       0.0       0.0       0.0"
            "        77"))
        res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["Skew_ID"], 0)
        self.assertTrue(_warned(res, "CID=77", "ERROR 137"))

    def test_ircs1_degenerate_vectors_warn_and_stay_global(self):
        deck = _deck(PART_SHELL, self.IRCS_VECTORS.replace(
            "       0.0       0.0       1.0       1.0       0.0       0.0",
            "       0.0       0.0       1.0       0.0       0.0       2.0"))
        res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["Skew_ID"], 0)
        self.assertTrue(_warned(res, "degenerate"))

    def test_ircs0_never_binds_a_skew(self):
        """With IRCS=0 the tensor is GLOBAL, so nothing may be bound.

        This is a deliberate divergence from dyna2rad, whose CNRB path binds
        card-1 ``CID`` as ``Skew_ID`` whenever ``IRCS == 0``
        (``convertrigids.cxx:126-127``) and so rotates a global tensor —
        measured: ``4.11 5.22 6.33`` came out as ``5.22 6.33 4.11``.
        """
        deck = _deck(PART_SHELL, COORD_7, PART_INERTIA)
        _res, st = _convert(deck)
        (_rid, rb), = _rbody_cards(st)
        self.assertEqual(rb["Skew_ID"], 0)

    def test_card6_is_consumed_only_when_ircs_is_1(self):
        """The conditional card is gated on a VALUE, not on an option name.

        With IRCS=0 there is no card 6, so a following part's HEADING sits where
        card 6 would be. Mis-striding here eats it — the classic PR #117 failure.
        """
        deck = _deck(PART_SHELL, PART_INERTIA + """\
*PART
second brick
       3       2       2
""")
        _res, st = _convert(deck)
        parts = _part_cards(st)
        self.assertIn(3, parts)
        self.assertIn(2, parts)


# ═════════════════════════════════════════════════════════════════════════════
# B) *CONSTRAINED_NODAL_RIGID_BODY_INERTIA
# ═════════════════════════════════════════════════════════════════════════════

CNRB_SET = """\
*SET_NODE_LIST
       300
         1         2         3         4
"""

#: Card 1 then cards 3-5. Card 5 is ALL BLANK on purpose — LS-PrePost emits it
#: that way, and it must be consumed as a card of all-defaults.
CNRB_INERTIA = """\
*CONSTRAINED_NODAL_RIGID_BODY_INERTIA
       400         0       300         0         0         0         0
      0.25       0.35       0.45      3.75         0         0
      31.0       1.0       3.0      35.0       2.0      40.0

"""


class CnrbInertiaTests(unittest.TestCase):

    def test_inertia_lands_on_the_cnrb_rbody(self):
        """Same transfer as `*PART_INERTIA`, on the CNRB path.

        Validated against the starter: ``PRIMARY NODE`` at (0.25, 0.35, 0.45),
        ``CENTER OF MASS FLAG 4``, ``ADDED MASS 3.750``, ``ADDED INERTIA 31.0 35.0
        40.0 1.0 2.0 3.0``. dyna2rad cannot even get here — an `_INERTIA` CNRB
        hard-crashes the hm LS-DYNA reader (starter exit 3, no listing at all,
        reproduced on four decks).
        """
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, CNRB_SET,
                                  CNRB_INERTIA))
        rbs = {rb["Mass"]: rb for _rid, rb in _rbody_cards(st)}
        self.assertIn(3.75, rbs)
        rb = rbs[3.75]
        self.assertEqual(rb["ICoG"], 4)
        self.assertEqual((rb["Jxx"], rb["Jyy"], rb["Jzz"]), (31.0, 35.0, 40.0))
        self.assertEqual((rb["Jxy"], rb["Jyz"], rb["Jxz"]), (1.0, 2.0, 3.0))
        self.assertEqual(_node_coords(st, rb["node_ID"]), (0.25, 0.35, 0.45))

    def test_blank_card5_does_not_eat_the_next_block(self):
        """The all-blank card 5 above is a CARD. If it were skipped as whitespace
        the walk would fall a card short and the *following* keyword's first line
        would be consumed as card 5 — the PR #117 positional-consumption bug."""
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, CNRB_SET, CNRB_INERTIA,
                                 "*CONSTRAINED_NODAL_RIGID_BODY\n"
                                 "       401         0       300\n"))
        self.assertEqual(res.skipped_keywords, [])
        masses = sorted(rb["Mass"] for _rid, rb in _rbody_cards(st))
        self.assertIn(3.75, masses)
        self.assertEqual(len([m for m in masses if m == 0.0]), 2,
                         "the plain CNRB and the rigid part must both survive")

    def test_pnode_is_not_the_main_node_with_inertia(self):
        """LS-DYNA relocates PNODE to the centre of mass itself, so it is a
        readout node, not the datum. With `_INERTIA` the main node must be the
        stated COM (ICoG=4 does not move it)."""
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, CNRB_SET,
                                 CNRB_INERTIA.replace(
                                     "       400         0       300"
                                     "         0         0         0         0",
                                     "       400         0       300"
                                     "        99         0         0         0")))
        rbs = {rb["Mass"]: rb for _rid, rb in _rbody_cards(st)}
        self.assertNotEqual(rbs[3.75]["node_ID"], 99)
        self.assertTrue(_warned(res, "PNODE 99", "NOT used"))

    def test_cid2_binds_the_skew_when_ircs_is_1(self):
        deck = _deck(PART_SHELL, PART_RIGID, COORD_7, CNRB_SET,
                     CNRB_INERTIA.replace(
                         "      0.25       0.35       0.45      3.75"
                         "         0         0",
                         "      0.25       0.35       0.45      3.75"
                         "         1         0")
                     + "       0.0       0.0       0.0       0.0       0.0"
                       "       0.0         7\n")
        _res, st = _convert(deck)
        rbs = {rb["Mass"]: rb for _rid, rb in _rbody_cards(st)}
        self.assertEqual(rbs[3.75]["Skew_ID"], 7)

    def test_drflag_rrflag_are_warn_dropped(self):
        """DOF releases have no /RBODY counterpart (the M2 backlog item). dyna2rad
        drops them without a word — ``grep -rn DRFLAG dyna2rad/`` is 0 hits, and a
        deck with ``DRFLAG=-3 RRFLAG=5`` converts byte-identically to one without.
        """
        res, _st = _convert(_deck(PART_SHELL, PART_RIGID, CNRB_SET,
                                  CNRB_INERTIA.replace(
                                      "       400         0       300"
                                      "         0         0         0         0",
                                      "       400         0       300"
                                      "         0         0        -3         5")))
        self.assertTrue(_warned(res, "DRFLAG=-3", "RRFLAG=5"))

    def test_override_and_thermal_cards_are_consumed_and_warned(self):
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, CNRB_SET,
                                 """\
*CONSTRAINED_NODAL_RIGID_BODY_INERTIA_OVERRIDE_THERMAL
       400         0       300         0         0         0         0
      0.25       0.35       0.45      3.75         0         0
      31.0       1.0       3.0      35.0       2.0      40.0

         1         0         0
         2
""", "*PART\nthird\n       3       1       1\n"))
        self.assertEqual(res.skipped_keywords, [])
        self.assertTrue(_warned(res, "_OVERRIDE card"))
        self.assertTrue(_warned(res, "_THERMAL card", "IDTHRM=2"))
        self.assertIn(3, _part_cards(st), "the next block must not be eaten")


# ═════════════════════════════════════════════════════════════════════════════
# C) *PART_CONTACT
# ═════════════════════════════════════════════════════════════════════════════

class PartContactTests(unittest.TestCase):

    def test_optt_lands_in_the_part_thick_column(self):
        """OPTT -> /PART field 4, cols 31-50 (F20).

        Reference Guide 2022 p.194: "(Optional) Virtual thickness for shells ...
        only used to calculate gap in interfaces", and it feeds the gap in
        /INTER/TYPE7, 11, 18, 19, 20, 21, 24 and 25 — every interface type k2rad
        emits. Confirmed by the starter's own read-back: ``VIRT. THICKN:
        0.5000000000000`` for the part carrying OPTT.
        """
        _res, st = _convert(_deck(PART_RIGID, """\
*PART_CONTACT
shells
       1       1       1
       0.0       0.0       0.0       0.0       0.5       0.0       0.0
"""))
        prop, mat, subset, thick, ln = _part_cards(st)[1]
        self.assertEqual((prop, mat, subset), (1, 1, 0))
        self.assertEqual(thick, 0.5)
        self.assertEqual(len(ln), 50, f"/PART line is {len(ln)} cols, expected 50")

    def test_blank_optt_keeps_the_three_field_line(self):
        """A written ``0.0`` is INDISTINGUISHABLE from blank — the starter's gate
        is ``IF (THK_PART(IP) /= ZERO ...)`` (``i7sti3.F:226``), so a literal zero
        contact thickness is not expressible through /PART at all. Suppressing the
        field also keeps every deck without the option byte-identical."""
        _res, st = _convert(_deck(PART_RIGID, """\
*PART_CONTACT
shells
       1       1       1
       0.3       0.2       0.0       0.0       0.0       0.0       0.0
"""))
        _p, _m, _s, thick, ln = _part_cards(st)[1]
        self.assertIsNone(thick)
        self.assertEqual(len(ln), 30, f"/PART line is {len(ln)} cols, expected 30")

    def test_other_card8_fields_are_warn_dropped(self):
        res, _st = _convert(_deck(PART_RIGID, """\
*PART_CONTACT
shells
       1       1       1
      0.31      0.22       1.5       2.5     0.007       1.3       1.7       2.0
"""))
        self.assertTrue(_warned(res, "friction coefficients", "FS=0.31",
                                "FD=0.22"))
        self.assertTrue(_warned(res, "thickness SCALE", "SFT=1.3"))
        self.assertTrue(_warned(res, "penalty-stiffness scale", "SSF=1.7"))
        self.assertTrue(_warned(res, "CPARM8"))

    def test_element_thickness_clash_is_reported(self):
        """/PART Comment 3: the part ``Thick`` supersedes the PROPERTY thickness
        only when the /SHELL or /SH3N ``Thick`` is 0 — so a non-zero per-element
        thickness WINS and the OPTT the deck just asked for does nothing."""
        deck = _deck(PART_RIGID, """\
*PART_CONTACT
shells
       1       1       1
       0.0       0.0       0.0       0.0       0.5       0.0       0.0
""").replace("""*ELEMENT_SHELL
       1       1       1       2       3       4
""", """*ELEMENT_SHELL_THICKNESS
       1       1       1       2       3       4
             2.0             2.0             2.0             2.0
""")
        res, _st = _convert(deck)
        self.assertTrue(_warned(res, "BOTH", "OPTT", "*ELEMENT_SHELL_THICKNESS"))

    def test_stacked_spellings_read_inertia_first_then_contact(self):
        """"Options 1, 2, 3, 4, 5, and 6 may be specified in any order on the
        *PART card" (p.37-2), but the CARD order is fixed by the Card Summary:
        INERTIA cards 3-6 come BEFORE the CONTACT card 8, whichever way the
        keyword is spelled. Both spellings must therefore produce the same result.
        """
        body = """\
rigid brick
       2       2       2
     22.05      2.125       0.75      7.25         0         0
      20.0       1.0       3.0      25.0       2.0      30.0
       1.5       0.0       0.0       0.0       0.0       2.5
       0.0       0.0       0.0       0.0     0.007       0.0       0.0
"""
        seen = []
        for kw in ("*PART_INERTIA_CONTACT", "*PART_CONTACT_INERTIA"):
            with self.subTest(kw=kw):
                res, st = _convert(_deck(PART_SHELL, kw + "\n" + body))
                self.assertEqual(res.skipped_keywords, [])
                (_rid, rb), = _rbody_cards(st)
                self.assertEqual(rb["Mass"], 7.25)
                self.assertEqual(rb["Jxx"], 20.0)
                self.assertEqual(_part_cards(st)[2][3], 0.007)
                seen.append(_part_cards(st)[2][4])
        self.assertEqual(seen[0], seen[1], "spelling order must not matter")


# ═════════════════════════════════════════════════════════════════════════════
# *PART option grammar / dispatch coverage / mesh survival
# ═════════════════════════════════════════════════════════════════════════════

class PartOptionGrammarTests(unittest.TestCase):

    def test_every_legal_spelling_is_registered_in_both_tables(self):
        """3588 `*PART` spellings and 65 CNRB ones, generated from ONE source and
        mirrored into ``_OFFSET_SPECS`` — the #116 lesson. A spelling that reaches
        only one table either loses the mesh (no handler) or keeps un-offset ids
        inside an `*INCLUDE_TRANSFORM` (no offset spec)."""
        part_kws = list(_part_option_keywords())
        self.assertEqual(len(part_kws), 3588)
        self.assertEqual(len(set(part_kws)), 3588)
        cnrb_kws = [k for k, _ in _cnrb_option_keywords()]
        self.assertEqual(len(cnrb_kws), 65)
        for kw in part_kws + cnrb_kws:
            self.assertIn(kw, HANDLERS, f"*{kw} has no handler")
            self.assertIn(kw, _OFFSET_SPECS, f"*{kw} has no offset spec")
        for kw in ("CONSTRAINED_INTERPOLATION",
                   "CONSTRAINED_INTERPOLATION_LOCAL"):
            self.assertIn(kw, HANDLERS)
            self.assertIn(kw, _OFFSET_SPECS)

    def test_option_suffix_tokenises_order_independently(self):
        """ATTACHMENT_NODES itself contains an underscore, so the suffix cannot be
        split on "_" — the matcher goes longest-token-first."""
        self.assertEqual(_part_options("PART_INERTIA_CONTACT"),
                         ({"INERTIA", "CONTACT"}, []))
        self.assertEqual(_part_options("PART_CONTACT_INERTIA"),
                         ({"INERTIA", "CONTACT"}, []))
        self.assertEqual(_part_options("PART_ATTACHMENT_NODES_PRINT"),
                         ({"ATTACHMENT_NODES", "PRINT"}, []))
        self.assertEqual(_part_options("PART"), (set(), []))
        self.assertEqual(_part_options("PART_SENSOR"), (set(), ["SENSOR"]))

    def test_unmodelled_option_stack_keeps_the_mesh(self):
        """The CRITICAL requirement: an option stack k2rad cannot model must still
        parse the part card, so the part and its elements reach the deck. Only the
        option's DATA is lost, and each loss is named."""
        res, st = _convert(_deck(PART_SHELL, """\
*PART_REPOSITION_PRINT_FIELD
rigid brick
       2       2       2
         1         2         3
         7
        11
"""))
        self.assertEqual(res.skipped_keywords, [])
        self.assertIn(2, _part_cards(st))
        self.assertIn("/BRICK/2", st)
        self.assertFalse(_warned(res, "MESH LOSS"))
        self.assertTrue(_warned(res, "_REPOSITION"))
        self.assertTrue(_warned(res, "_PRINT PRBF"))
        self.assertTrue(_warned(res, "_FIELD FIDBO"))

    def test_attachment_nodes_card_is_consumed(self):
        res, st = _convert(_deck(PART_SHELL, """\
*PART_ATTACHMENT_NODES
rigid brick
       2       2       2
       300
""", CNRB_SET, "*PART\nthird\n       3       1       1\n"))
        self.assertEqual(res.skipped_keywords, [])
        self.assertTrue(_warned(res, "_ATTACHMENT_NODES ANSID"))
        self.assertIn(3, _part_cards(st))

    def test_part_sensor_is_warn_skipped_not_parsed_as_a_part(self):
        """`*PART_SENSOR` and friends are SEPARATE keywords whose first card is
        not a HEADING. Running the `*PART` walk on them would register phantom
        parts from their data cards — the same class of bug as the measured
        phantom ``/PART/4321``."""
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*PART_SENSOR
         2         1         1
"""))
        self.assertIn("PART_SENSOR", res.skipped_keywords)
        self.assertTrue(_warned(res, "*PART_SENSOR is a separate LS-DYNA keyword"))
        self.assertEqual(sorted(_part_cards(st)), [1, 2],
                         "no phantom part may be invented")

    def test_plain_part_deck_line_is_unchanged(self):
        """Byte-identity guard for every deck without the new keywords: the /PART
        data line must stay exactly three 10-wide fields."""
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID))
        for pid, (_p, _m, _s, thick, ln) in _part_cards(st).items():
            self.assertIsNone(thick, f"/PART/{pid} grew a Thick field")
            self.assertEqual(len(ln), 30)


# ═════════════════════════════════════════════════════════════════════════════
# D) *CONSTRAINED_INTERPOLATION -> /RBE3
# ═════════════════════════════════════════════════════════════════════════════

#: Four independent nodes with four different (IDOF, weight) pairs, so the split
#: into per-set groups is exercised end to end.
INTERP = """\
*CONSTRAINED_INTERPOLATION
       500       200    123456
         1       123       2.0
         2      1234       3.0
         3     12345       4.0
         4         3       5.0
"""


class Rbe3Tests(unittest.TestCase):

    def test_dependent_card_columns(self):
        """``Node_IDr(1-10) Trarot_ref(11-20) N_set(21-30) I_modif(31-40)`` = 40
        cols, and ``Iform`` (cols 41-50) is NOT emitted at /BEGIN 2022.

        Omitting Iform is right, not merely safe: the reader gets 0 from the 2022
        cfg and ``SELECT CASE(IFORM) CASE(0,1)`` maps 0 to 1, the
        kinematic-with-auto-penalty-fallback that IS the 2022 behaviour. Writing
        it would be WARNING 100211 "Unsupported option in format".
        """
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, INTERP))
        self.assertEqual(res.skipped_keywords, [])
        (rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(rid, 500)              # /RBE3 id = ICID, 1:1
        self.assertEqual(dep["Node_IDr"], 200)
        self.assertEqual(dep["N_set"], 4)
        self.assertEqual(dep["I_modif"], 2)

    def test_trarot_subcolumn_pattern_is_exact(self):
        """Three blanks, TxTyTz, one blank, RxRyRz — inside the 10-wide field.

        Measured negative control: right-aligning the six digits as
        ``      111111`` produced ``REFERENCE DOF(Trarot) 000 111`` (the three
        translations silently lost) and the run still TERMINATED NORMALLY.
        """
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, INTERP))
        (_rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(dep["Trarot_ref"], "   111 111")
        self.assertEqual([s["Trarot_Mi"] for s in sets],
                         ["   111 000",     # IDOF 123    -> Tx Ty Tz
                          "   111 100",     # IDOF 1234   -> + Rx
                          "   111 110",     # IDOF 12345  -> + Ry
                          "   001 000"])    # IDOF 3      -> Tz alone
        for s in sets:
            self.assertEqual(s["Trarot_Mi"][:3], "   ")
            self.assertEqual(s["Trarot_Mi"][6], " ")

    def test_one_set_and_one_grnod_per_weight_dof_group(self):
        """Radioss has ONE scalar WTi per set, so the rows are grouped on
        (IDOF, weight, CIDI) and each group gets its own /GRNOD/NODE.

        Validated against the starter at IPRI=5, which echoed exactly these
        weights per node: ``2.0 2.0 2.0 0 0 0`` / ``3.0`` x4 / ``4.0`` x5 /
        ``0 0 5.0 0 0 0``. dyna2rad collapses all four into one set and its echo
        reads ``1.0 1.0 1.0 0.0 0.0 0.0`` for every node.
        """
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, INTERP))
        (_rid, _dep, sets), = _rbe3_cards(st)
        self.assertEqual([s["WTi"] for s in sets], [2.0, 3.0, 4.0, 5.0])
        self.assertEqual([_grnod_nodes(st, s["grnod_IDi"]) for s in sets],
                         [[1], [2], [3], [4]])
        self.assertEqual(len({s["grnod_IDi"] for s in sets}), 4)

    def test_equal_weight_and_dof_rows_share_one_set(self):
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500       200    123456
         1       123       2.0
         2       123       2.0
         3       123       7.0
"""))
        (_rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(dep["N_set"], 2)
        self.assertEqual(_grnod_nodes(st, sets[0]["grnod_IDi"]), [1, 2])
        self.assertEqual(_grnod_nodes(st, sets[1]["grnod_IDi"]), [3])

    def test_ddof_and_idof_defaults(self):
        """Blank DDOF/IDOF -> 123456 ("The default is 123456", p.10-42).

        That is NOT the Radioss default for the same field: a blank
        ``Trarot_Mi`` gives Tx/Ty/Tz only (``hm_read_rbe3.F:244-248``),
        contradicting the Reference Guide's own "set on all DOF" — empirically
        confirmed. k2rad writes all six digits explicitly and leans on neither
        default.
        """
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500       200
         1
"""))
        (_rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(dep["Trarot_ref"], "   111 111")
        self.assertEqual(sets[0]["Trarot_Mi"], "   111 111")
        self.assertEqual(sets[0]["WTi"], 1.0)     # TWGHTX default 1.0

    def test_trailing_weights_default_to_twghtx(self):
        """"the other factors are set equal to this input value as the default"
        (p.10-43) — so a row with only TWGHTX is UNIFORM and must not warn."""
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500       200    123456
         1       123       6.0
"""))
        (_rid, _dep, sets), = _rbe3_cards(st)
        self.assertEqual(sets[0]["WTi"], 6.0)
        self.assertFalse(_warned(res, "per-component weights"))

    def test_non_uniform_weights_warn_and_use_twghtx(self):
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500       200    123456
         1       123       2.0       9.0       9.0       9.0       9.0       9.0
"""))
        (_rid, _dep, sets), = _rbe3_cards(st)
        self.assertEqual(sets[0]["WTi"], 2.0)
        self.assertTrue(_warned(res, "per-component weights"))

    def test_local_cidi_becomes_the_per_set_skew_and_cidd_is_warned(self):
        """With `_LOCAL` each card 2 is PAIRED with its own ``CIDI`` card, and the
        pairing is positional — a blank CIDI card (the normal spelling for
        "global") must be consumed, not skipped, or the next pair slides into it.

        ``CIDD`` has no destination: the 2022 dependent card has no skew column at
        all, only the per-set ``skew_IDi``.
        """
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, COORD_7, """\
*CONSTRAINED_INTERPOLATION_LOCAL
       500       200    123456         7
         1       123       2.0
         7
         2       123       2.0

"""))
        self.assertEqual(res.skipped_keywords, [])
        (_rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(dep["N_set"], 2, "the blank CIDI card must be consumed")
        self.assertEqual(sets[0]["skew_IDi"], 7)
        self.assertEqual(sets[1]["skew_IDi"], 0)
        self.assertTrue(_warned(res, "CIDD=7", "DROPPED"))

    def test_dangling_cidi_warns_and_stays_global(self):
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION_LOCAL
       500       200    123456
         1       123       2.0
        77
"""))
        (_rid, _dep, sets), = _rbe3_cards(st)
        self.assertEqual(sets[0]["skew_IDi"], 0)
        self.assertTrue(_warned(res, "CIDI=77", "ERROR 184"))

    def test_ityp1_resolves_a_node_set(self):
        """"EQ.1: INID is a node set ID" (p.10-43). dyna2rad keeps only the FIRST
        such set and drops every further one."""
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, CNRB_SET, """\
*CONSTRAINED_INTERPOLATION
       500       200    123456         0         1
       300       123       2.0
"""))
        (_rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(dep["N_set"], 1)
        self.assertEqual(_grnod_nodes(st, sets[0]["grnod_IDi"]), [1, 2, 3, 4])

    def test_missing_dependent_node_skips_the_whole_constraint(self):
        """``Node_IDr = 0`` is starter ERROR 78 followed by ERROR 760 — the deck
        does not convert into a runnable model. That is exactly what dyna2rad
        emits (its DNID handle never resolves), so the constraint is skipped here
        with the reason said out loud instead."""
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500      9999    123456
         1       123       2.0
"""))
        self.assertEqual(_rbe3_cards(st), [])
        self.assertTrue(_warned(res, "DNID=9999", "ERROR 78"))

    def test_dependent_node_in_its_own_independent_list_warns(self):
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500         1    123456
         1       123       2.0
         2       123       2.0
"""))
        self.assertEqual(len(_rbe3_cards(st)), 1)
        self.assertTrue(_warned(res, "ALSO in its own independent list"))

    def test_dependent_node_on_an_rbody_main_warns(self):
        """Hierarchy rule RBODY > RBE3 > RBE2 > INTERFACE TYPE2 (Reference Guide
        p.1959 comment 6): this is starter ERROR 810, or WARNING 3104 with a
        silent switch to the penalty formulation."""
        _res, st = _convert(_deck(PART_SHELL, PART_RIGID, INTERP))
        (_rid, rb), = _rbody_cards(st)
        res2, _st2 = _convert(_deck(PART_SHELL, PART_RIGID, INTERP.replace(
            "       500       200    123456",
            f"       500{rb['node_ID']:>10}    123456")))
        self.assertTrue(_warned(res2, "ERROR 810"))

    def test_repeated_node_with_different_weights_is_deduplicated(self):
        """A node in two sets with different weights is starter ERROR 705
        ("DIFFERENT WEIGHTS FOR INDEPENDENT NODE NUMBER") — a first-write-wins
        check in the reader, so the first row is what k2rad keeps."""
        res, st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500       200    123456
         1       123       2.0
         1       123       9.0
         2       123       2.0
"""))
        (_rid, dep, sets), = _rbe3_cards(st)
        self.assertEqual(dep["N_set"], 1)
        self.assertEqual(sets[0]["WTi"], 2.0)
        self.assertEqual(_grnod_nodes(st, sets[0]["grnod_IDi"]), [1, 2])
        self.assertTrue(_warned(res, "ERROR 705"))

    def test_idnsw_and_fgm_are_warn_dropped(self):
        res, _st = _convert(_deck(PART_SHELL, PART_RIGID, """\
*CONSTRAINED_INTERPOLATION
       500       200    123456         0         0         2         1
         1       123       2.0
"""))
        self.assertTrue(_warned(res, "IDNSW=2"))
        self.assertTrue(_warned(res, "FGM=1"))

    def test_rbe3_nodes_are_not_fixed_by_the_implicit_free_node_guard(self):
        """A /BCS 111 111 on an /RBE3 DEPENDENT node fights the constraint —
        starter WARNING 3115 switches the whole element to the penalty
        formulation.

        Differential, so it cannot pass vacuously: node 200 is attached to nothing
        but the /RBE3, so WITHOUT the interpolation card the implicit free-node
        guard grabs it, and WITH it the node must be left free.
        """
        IMPL = "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n"

        def _fixed_nodes(starter):
            out = set()
            for _bid, data in _blocks(starter, "/BCS"):
                ln = data[0]
                if ln[3:6] == "111" and ln[7:10] == "111":
                    gid = int(ln[20:30] or 0)
                    if gid:
                        out.update(_grnod_nodes(starter, gid))
            return out

        _r0, st0 = _convert(_deck(PART_SHELL, PART_RIGID, IMPL))
        self.assertIn(200, _fixed_nodes(st0),
                      "the free-node guard should grab the lone node 200 here — "
                      "if it does not, this test proves nothing")
        _r1, st1 = _convert(_deck(PART_SHELL, PART_RIGID, INTERP, IMPL))
        self.assertNotIn(200, _fixed_nodes(st1))


class DofDigitDecoderTests(unittest.TestCase):

    def test_digit_set_membership(self):
        """A DOF code is a DIGIT STRING, not a bitfield: ``1356`` means DOFs
        {1,3,5,6} (Vol I R17 p.10-42)."""
        self.assertEqual(dof_digits_to_flags(123), [1, 1, 1, 0, 0, 0])
        self.assertEqual(dof_digits_to_flags(123456), [1, 1, 1, 1, 1, 1])
        self.assertEqual(dof_digits_to_flags(1356), [1, 0, 1, 0, 1, 1])
        self.assertEqual(dof_digits_to_flags(3), [0, 0, 1, 0, 0, 0])
        self.assertEqual(dof_digits_to_flags(0), [0, 0, 0, 0, 0, 0])

    def test_zero_and_out_of_range_digits_are_ignored(self):
        """dyna2rad's decoder tests ``d <= 6``, which a ``0`` digit passes, and
        then writes ``flags[-1]`` — an out-of-bounds stack write on any code
        containing a zero (``DDOF = 10``, ``IDOF = 120``)."""
        self.assertEqual(dof_digits_to_flags(10), [1, 0, 0, 0, 0, 0])
        self.assertEqual(dof_digits_to_flags(120), [1, 1, 0, 0, 0, 0])
        self.assertEqual(dof_digits_to_flags(789), [0, 0, 0, 0, 0, 0])

    def test_trarot_formatting(self):
        self.assertEqual(_trarot([1, 1, 1, 0, 0, 0]), "   111 000")
        self.assertEqual(_trarot([0, 0, 0, 0, 0, 1]), "   000 001")
        self.assertEqual(len(_trarot([1] * 6)), 10)


# ═════════════════════════════════════════════════════════════════════════════
# *INCLUDE_TRANSFORM id offsets for the new card layouts
# ═════════════════════════════════════════════════════════════════════════════

#: An *INCLUDE_TRANSFORM header with a DISTINCT value per bucket, so a test that
#: asserts the wrong bucket cannot pass by coincidence. Card 2 is
#: ``IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF IDDOFF`` and card 3 opens with
#: ``IDROFF`` ("everything else": sections, constraint ids, ...).
OFF_C2 = ("      1000      2000      3000      4000"
          "      5000      6000      7000")
OFF_C3 = "      8000"
IDNOFF, IDPOFF, IDMOFF, IDSOFF, IDDOFF, IDROFF = (
    1000, 3000, 4000, 5000, 7000, 8000)


class IncludeTransformOffsetTests(unittest.TestCase):
    """A stale `_off_part` would rewrite the ``IXX IXY IXZ IYY IYZ IZZ`` card as
    if it were the next part's data card, corrupting the inertia NUMBERS with a
    part/material/section offset. So the offset walker mirrors the handler's, and
    is generated from the same two keyword functions."""

    def _run(self, child):
        tmp = tempfile.TemporaryDirectory()
        d = tmp.name
        with open(os.path.join(d, "child.k"), "w") as fh:
            fh.write(child)
        main = os.path.join(d, "main.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     + OFF_C2 + "\n" + OFF_C3 + "\n\n\n*END\n")
        state = ConversionState()
        for block in parse_k_file(main):
            dispatch(block, state)
        tmp.cleanup()
        return state

    def test_part_inertia_ids_offset_and_floats_untouched(self):
        st = self._run("""\
*KEYWORD
*PART_INERTIA
brick
       2       2       2
     22.05      2.125       0.75      7.25         0        11
      20.0       1.0       3.0      25.0       2.0      30.0
       1.5       0.0       0.0       0.0       0.0       2.5
*END
""")
        pid = IDPOFF + 2
        self.assertIn(pid, st.parts)
        self.assertEqual(st.parts[pid].mid, IDMOFF + 2)
        self.assertEqual(st.parts[pid].secid, IDROFF + 2)
        inr = st.part_inertias[pid]
        self.assertEqual(inr.nodeid, IDNOFF + 11)
        # Every float must be untouched — this is what a flat stride-of-2 walk
        # would corrupt.
        self.assertEqual((inr.tm, inr.ixx, inr.ixy, inr.ixz, inr.iyy, inr.iyz,
                          inr.izz, inr.vtx, inr.vrz),
                         (7.25, 20.0, 1.0, 3.0, 25.0, 2.0, 30.0, 1.5, 2.5))
        self.assertEqual((inr.xc, inr.yc, inr.zc), (22.05, 2.125, 0.75))

    def test_ircs1_card6_cid_moves_with_iddoff(self):
        st = self._run("""\
*KEYWORD
*PART_INERTIA
brick
       2       2       2
      22.0       2.0       2.0      7.25         1         0
      20.0       0.0       0.0      25.0       0.0      30.0
       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0         7
*END
""")
        inr = st.part_inertias[IDPOFF + 2]
        self.assertEqual(inr.cid, IDDOFF + 7)

    def test_part_contact_card_is_stepped_over_not_rewritten(self):
        """`*PART_CONTACT` card 8 is eight FLOATS. Offsetting anything on it would
        turn OPTT into a part id; not striding past it would leave the NEXT part's
        heading treated as a data card."""
        st = self._run("""\
*KEYWORD
*PART_INERTIA_CONTACT
brick
       2       2       2
     22.05      2.125       0.75      7.25         0         0
      20.0       1.0       3.0      25.0       2.0      30.0
       0.0       0.0       0.0       0.0       0.0       0.0
      0.31      0.22       1.5       2.5     0.007       1.3       1.7
shell
       1       1       1
     10.05      1.125       0.25      1.25         0         0
       1.0       0.0       0.0       2.0       0.0       3.0
       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0     0.009       0.0       0.0
*END
""")
        self.assertEqual(sorted(st.parts), [IDPOFF + 1, IDPOFF + 2])
        self.assertEqual(st.part_contacts[IDPOFF + 2].optt, 0.007)
        self.assertEqual(st.part_contacts[IDPOFF + 1].optt, 0.009)
        self.assertEqual(st.part_inertias[IDPOFF + 1].tm, 1.25)

    def test_cnrb_inertia_nodeid_moves_with_idnoff(self):
        st = self._run("""\
*KEYWORD
*CONSTRAINED_NODAL_RIGID_BODY_SPC_INERTIA
       400         0       300         0         0         0         0
       1.0         7         3
      0.25       0.35       0.45      3.75         0        11
      31.0       1.0       3.0      35.0       2.0      40.0
       0.0       0.0       0.0       0.0       0.0       0.0
*END
""")
        (cnrb,) = st.cnrbs
        self.assertEqual(cnrb.pid, IDPOFF + 400)
        self.assertEqual(cnrb.nsid, IDSOFF + 300)
        self.assertEqual(cnrb.inertia.nodeid, IDNOFF + 11)
        self.assertEqual(cnrb.inertia.tm, 3.75)
        self.assertEqual(cnrb.con1, 7)           # CMO > 0 -> a DOF code, not an id

    def test_interpolation_ids_offset(self):
        st = self._run("""\
*KEYWORD
*CONSTRAINED_INTERPOLATION_LOCAL
       500       200    123456         7         0
         1       123       2.0
         9
*END
""")
        (rec,) = st.interpolations
        self.assertEqual(rec.icid, IDROFF + 500)
        self.assertEqual(rec.dnid, IDNOFF + 200)
        self.assertEqual(rec.cidd, IDDOFF + 7)
        self.assertEqual(rec.ddof, 123456)       # a DOF code — never offset
        self.assertEqual(rec.indeps[0].inid, IDNOFF + 1)
        self.assertEqual(rec.indeps[0].cidi, IDDOFF + 9)
        self.assertEqual(rec.indeps[0].idof, 123)
        self.assertEqual(rec.indeps[0].twghtx, 2.0)

    def test_interpolation_ityp1_inid_moves_with_idsoff(self):
        st = self._run("""\
*KEYWORD
*CONSTRAINED_INTERPOLATION
       500       200    123456         0         1
       300       123       2.0
*END
""")
        (rec,) = st.interpolations
        self.assertEqual(rec.indeps[0].inid, IDSOFF + 300)   # not IDNOFF


if __name__ == "__main__":
    unittest.main()
