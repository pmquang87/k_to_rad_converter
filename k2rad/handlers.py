"""
k2rad.handlers  –  Convert each LS-DYNA Block into ConversionState entries.

Each public function has signature:
    handle_<keyword>(block: Block, state: ConversionState) -> None
"""

from __future__ import annotations

import ast as _ast
import math as _math
from typing import List, Optional, Tuple

from .parser import (
    Block, _strip_inline_comment, parse_fixed, parse_free, to_float, to_int,
)
from .state import (
    ConversionState,
    NodeData, ShellElem, SolidElem, BeamElem, PlotelElem, ProvisionalElemBlock,
    PartData, SectionShell, SectionSolid, SectionBeam,
    MatElastic, MatPlasTAB, MatPlasKin, MatRigid, MatNull, MatSAMP, FailGissmo,
    MatAnisoViscoplastic, MatJohnsonCook,
    MatOrthotropicElastic, MatEnhancedCompositeDamage,
    MatTransverselyAnisotropic, MatLaminatedGlass,
    CompositePly, PartComposite,
    MatAddErosion, ConstrainedNodeSet,
    MatCrushableFoam, MatLowDensityFoam, MatFuChangFoam, MatHoneycomb,
    MatBlatzKo, MatMooneyRivlin, MatOgdenRubber, MatHyperelasticRubber,
    FoamRefGeometry,
    DiscreteElem, SectionDiscrete, MatSpringElastic, MatSpringNonlinearElastic,
    MatDamperViscous, MatSpotweld, ConstrainedSpotweld,
    ConstrainedJoint, JointStiffness, JOINT_TYPE45,
    Curve, DefineTable, CoordSys, CoordNodes, CoordVector, DefineVector,
    SdOrientation, DefineBox, ConstrainedNodalRigidBody,
    BcsSpc, PrescribedMotionRigid, PrescribedMotionSet, LoadRigidBody,
    LoadNode, RigidWallPlanar,
    ContactAutoSingle, ContactAutoSurf2Surf, ContactAutoGeneral,
    ContactForceTransducer, ContactTied,
    InitialVelocityNode, InitialVelocityRigidBody,
    InitialVelocity, InitialVelocityGeneration, MatPowerLaw, PressureLoad,
    SegmentSet, SegmentSetPressureLoad, LoadBlastEnhanced, LoadBlastSegmentSet,
    LoadBody,
    MatHighExplosiveBurn, EosJwl, EosCard, InitialDetonation,
    AleMultiMaterialGroup, ConstrainedLagrangeInSolid, InitialVolumeFraction,
    BoundaryNonReflecting, ControlAle,
    ControlAccuracy, ControlContact, ControlCpu, ControlEnergy,
    ControlHourglass, HourglassDef, ControlImplicitAuto, ControlImplicitDynamics,
    ControlOutput, ControlShell, ControlSolid,
    ControlImplicitGeneral, ControlImplicitSolution, ControlImplicitEigenvalue,
    ControlTermination, ControlTimestep,
    DampingGlobal, DampingPartStiffness,
    DbD3Plot, DbHistory, DbExtentBinary,
    GravityLoadPart, MatAddFatigue, DbFreqBinary,
    InitialStressShell, InitialStressSolid, CrossSection,
)


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _elem_fields(line: str, n: int) -> List[str]:
    """Parse an element connectivity line into *n* fields.

    Tries whitespace-split first.  In the fixed I8 format two consecutive
    fields glue together whenever the left one's value fills all 8 columns
    (any id >= 10,000,000, e.g. LS-PrePost output): the split then under-counts
    — "90000001      9190000001…" (eid pid n1…) is just two tokens.  A single
    I8 field never exceeds 8 characters, so any longer token marks a possible
    glue; re-slice the whole line at w=8 and prefer that result when it
    separates more fields and every one is a plain unsigned integer.  Genuine
    free-format lines with ids wider than 8 digits fail that check (their
    re-slice cuts numbers mid-token, leaving fields with embedded spaces) and
    keep the whitespace split.
    """
    f = parse_free(line)
    if f and any(len(tok) > 8 for tok in f):
        data = _strip_inline_comment(line)
        # Slice the full line, not just n fields: a glue past field n (e.g. in
        # a beam's optional trailing fields) must still count as fixed format,
        # otherwise the mis-split leading tokens would be taken at face value.
        n_all = max(n, (len(data) + 7) // 8)
        fixed = parse_fixed(data, n=n_all, w=8)
        nonempty = [x for x in fixed if x]
        if len(nonempty) > len(f) and all(x.isdigit() for x in nonempty):
            return fixed[:n]
    return f


def _card(raw: List[str], idx: int, fixed: bool = False, n: int = 8, w: int = 10) -> List[str]:
    """Return fields from raw[idx], or empty list if out of range."""
    if idx >= len(raw):
        return []
    line = raw[idx]
    if fixed:
        fields = parse_fixed(line, n, w)
        # A genuinely fixed-format field never has whitespace or a comma INSIDE
        # it — if one does (e.g. the free-format cards "1 1 1" or "1,2,3"
        # slicing to ["1 1 1", ...] / ["1,2,3", ...]), the card is free-format
        # written narrower than the field width, and slicing it silently
        # corrupts every value. Fall back to a free split.
        if any(" " in x.strip() or "," in x for x in fields):
            tokens = parse_free(line)
            if tokens:
                return tokens + [""] * max(0, n - len(tokens))
        return fields
    tokens = parse_free(line)
    # Fall back to fixed-width if whitespace-split yields too few tokens
    if len(tokens) < max(2, n // 2):
        return parse_fixed(line, n, w)
    return tokens


def _ffield(f: List[str], i: int, default: float) -> float:
    """Float field with an LS-DYNA non-zero default: fixed-format cards always
    slice to n fields, so a BLANK field must fall back to *default* by content
    (``to_float("")`` would silently turn e.g. a default SF=1.0 into 0.0)."""
    return to_float(f[i]) if len(f) > i and f[i].strip() else default


def _element_mass_card(line: str) -> List[str]:
    """Slice an *ELEMENT_MASS-family card: eid(I8) nid/id(I8) mass(F16.0) pid(I8).

    The mass column is 16 wide, so uniform 10-wide slicing must not be used
    here: it reads line chars 20-30 and cuts the last characters off a
    right-justified F16 mass ("            0.05" → "0." → 0.0), silently
    zeroing every non-integer mass value.
    """
    return [line[0:8].strip(), line[8:16].strip(),
            line[16:32].strip(), line[32:40].strip()]


def _has_title(block: Block) -> bool:
    return "TITLE" in block.options or "SUBTITLE" in block.options


def _has_id(block: Block) -> bool:
    return "ID" in block.options


def _title_offset(block: Block) -> int:
    """Number of raw lines consumed by title/id header."""
    offset = 0
    if _has_id(block):
        offset += 1  # id + title line
    elif _has_title(block):
        offset += 1  # title line only
    return offset


def _read_title(block: Block, default: str = "") -> str:
    """Return the title string if _TITLE or _ID option present."""
    if (_has_title(block) or _has_id(block)) and block.raw:
        # For _ID option the first card is "id   title"; title is the rest
        if _has_id(block):
            tokens = parse_free(block.raw[0])
            return " ".join(tokens[1:]) if len(tokens) > 1 else default
        return block.raw[0].strip()
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Header / control
# ─────────────────────────────────────────────────────────────────────────────

def handle_keyword(block: Block, state: ConversionState) -> None:
    pass  # nothing to emit


def handle_title(block: Block, state: ConversionState) -> None:
    if block.raw:
        state.model_title = block.raw[0].strip()


def handle_end(block: Block, state: ConversionState) -> None:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────

def handle_node(block: Block, state: ConversionState) -> None:
    for line in block.raw:
        f = parse_free(line)
        # LS-DYNA standard *NODE is fixed I8 + 3×E16: a negative coordinate
        # fills its 16-char field completely and glues onto the previous field
        # ("… 0.000000000e+00-1.250000000e+00"), so a whitespace split either
        # under-counts or leaves an over-long merged token. Re-slice the fixed
        # columns in that case — otherwise every node with a glued negative
        # coordinate is silently dropped (e.g. an entire plate at z < 0).
        if len(f) < 4 or any(len(t) > 16 for t in f[1:4]):
            nid = to_int(line[0:8])
            if nid <= 0:
                continue
            state.nodes[nid] = NodeData(to_float(line[8:24]), to_float(line[24:40]),
                                        to_float(line[40:56]))
            continue
        nid = to_int(f[0])
        state.nodes[nid] = NodeData(to_float(f[1]), to_float(f[2]), to_float(f[3]))


# ─────────────────────────────────────────────────────────────────────────────
# Elements
# ─────────────────────────────────────────────────────────────────────────────

# ── *ELEMENT_SHELL / *ELEMENT_BEAM option grammar ────────────────────────────
#
# LS-DYNA Vol I R17: *ELEMENT_SHELL_{THICKNESS}_{BETA|MCID}_{OFFSET}_{DOF}.
# The BASE connectivity card is always 10 x I8 (EID PID N1..N8); the suffix only
# decides which EXTRA cards follow it, per element:
#   card 2  THIC1..THIC4 + (BETA|MCID)  5 x F16  present for THICKNESS, BETA and
#                                                MCID alike — ONE shared card;
#                                                the option name says which
#                                                datum is meant, not which
#                                                columns exist
#   card 3  THIC5..THIC8                4 x F16  THICKNESS only, and only when
#                                                the mid-side nodes N5..N8 are
#                                                defined
#   card 4  OFFSET                      1 x F16  OFFSET only
#   card 5  blank(16) + NS1..NS4        4 x I8   DOF only
#
# *ELEMENT_BEAM_{OFFSET}_{ORIENTATION} adds, in that order, WX1..WZ2 (6 x F10)
# and VX VY VZ (3 x F10) — note the beam's extra cards are 10 chars wide while
# its base card is 8, and the shell's extra cards are 16.
#
# WHY THIS MATTERS: dyna2rad's CFG keyword table is an exact-match lookup
# (reader/source/cfgio/MODEL_IO/mv_solver_input_infos.cpp:497, myUserNameExactMatch)
# listing only ELEMENT_SHELL, ELEMENT_SHELL_THICKNESS, ELEMENT_SHELL_BETA and
# ELEMENT_BEAM_ORIENTATION. Every other spelling — _MCID, _OFFSET, _DOF,
# _COMPOSITE, and EVERY combined form — is an unmatched header, so the whole
# block is skipped and THE MESH IS LOST, not merely the extra data. k2rad keeps
# the mesh for every spelling, known or unknown (see dispatch()).
_SHELL_SUFFIX_TOKENS = frozenset({"THICKNESS", "BETA", "MCID", "OFFSET", "DOF"})
_BEAM_SUFFIX_TOKENS = frozenset({"ORIENTATION", "OFFSET"})

#: Option tokens whose block is not a list of finite elements at all, so the
#: "keep whatever parses as connectivity" fallback must NOT run on it.
#: *ELEMENT_SHELL_NURBS_PATCH card 1 is NPEID PID NPR PR NPS PS — six positive
#: integers that pass every connectivity test while meaning polynomial orders
#: and control-point counts, not nodes. Inventing an element from it would turn
#: a keyword k2rad merely skipped into starter ERROR 78 (undefined node).
_ELEM_NOT_A_MESH_TOKENS = frozenset({"NURBS", "PATCH"})


def _elem_options(keyword: str, base: str, known: frozenset):
    """Split ``*ELEMENT_<base><suffix>`` into (known option set, unknown tokens)."""
    tokens = [t for t in keyword[len(base):].split("_") if t]
    return ({t for t in tokens if t in known},
            [t for t in tokens if t not in known])


def _elem_block_is_not_a_mesh(block: Block, state: ConversionState,
                              unknown: List[str]) -> bool:
    """Route an isogeometric-patch block to skipped_keywords, as before."""
    if not any(t in _ELEM_NOT_A_MESH_TOKENS for t in unknown):
        return False
    state.skipped_keywords.append(block.keyword)
    state.warn(
        f"*{block.keyword} is an ISOGEOMETRIC patch definition, not a finite "
        "element mesh — its card holds polynomial orders and control-point "
        "counts where an element card holds node ids. OpenRadioss has no /IGA "
        "counterpart k2rad can target, so the block is skipped whole. The "
        "geometry it describes is NOT in the converted deck.")
    return True


def _parse_shell_base(line: str):
    """One *ELEMENT_SHELL connectivity card → (eid, pid, nodes, midside) or None.

    ``nodes`` is the 3 or 4 corner ids with trailing zeros stripped (a triangle
    may be written either as 3 ids with a blank N4 or as a collapsed quad);
    ``midside`` is the N5..N8 slots, which Radioss's 4-node /SHELL cannot carry.
    """
    f = [x for x in _elem_fields(line, 10) if x]   # eid pid n1..n8
    # 5 fields = eid pid n1 n2 n3: a triangle whose blank trailing N4
    # column was dropped — legal fixed-format output, keep it.
    if len(f) < 5:
        return None
    eid = to_int(f[0])
    pid = to_int(f[1])
    nodes = [to_int(f[i]) for i in range(2, min(6, len(f)))]
    while len(nodes) < 4:
        nodes.append(0)
    while len(nodes) > 3 and nodes[-1] == 0:
        nodes.pop()
    midside = [to_int(f[i]) for i in range(6, min(10, len(f)))]
    return eid, pid, nodes, midside


def _is_connectivity_card(line: str, n_min: int) -> bool:
    """True when *line* CAN be an element connectivity card.

    Used on the UNKNOWN-suffix path, where the number and layout of the extra
    cards is by definition not known: every field of a connectivity card is a
    plain unsigned integer and the id/node slots are non-zero, which no float
    card (thicknesses, offsets, ply thickness/angle pairs) can imitate.

    This test is NECESSARY BUT NOT SUFFICIENT and must never be the last word.
    An option card whose values happen to be integers passes it — an
    *ELEMENT_BEAM_THICKNESS section written ``10 10 10 10``, an
    *ELEMENT_SHELL_COMPOSITE ply card ``mid thick beta tmid …`` — and an element
    invented from one sits on node ids that do not exist: starter ERROR 78
    (UNDEFINED NODE) / ERROR 222 (N1=N2), a HARD failure where the old behaviour
    was a silent skip. Everything this accepts is therefore marked
    ``provisional`` and re-checked against the node table by
    ``writer/mesh.py::_screen_provisional_elements`` before it is emitted.
    """
    f = [x for x in _elem_fields(line, 10) if x]
    if len(f) < n_min:
        return False
    return all(t.isdigit() and int(t) > 0 for t in f[:n_min])


def handle_element_shell(block: Block, state: ConversionState) -> None:
    """*ELEMENT_SHELL and EVERY _THICKNESS/_BETA/_MCID/_OFFSET/_DOF spelling.

    Per-node thicknesses land on the element's own ``Thick`` field and BETA on
    its ``Phi`` field (both are real /SHELL // SH3N columns — no property split,
    no skew); MCID, OFFSET and DOF have no /SHELL destination and are dropped
    with a counted warning. An unrecognized suffix still keeps every element.
    """
    opts, unknown = _elem_options(block.keyword, "ELEMENT_SHELL",
                                  _SHELL_SUFFIX_TOKENS)
    raw = block.raw
    n_mcid = n_offset = n_dof = n_midside = 0
    seen_eids: set = set()

    if unknown and _elem_block_is_not_a_mesh(block, state, unknown):
        return

    if unknown:
        # Unrecognized option: the extra cards' layout is unknown, so consume
        # nothing positionally and keep every line that can only be a base
        # connectivity card. The mesh survives; the option's data does not.
        # Everything taken here is PROVISIONAL — the content test cannot tell an
        # all-integer option card from a real element, so the candidates are
        # screened against the node table before they reach the deck
        # (_screen_provisional_elements), which is also where this block's
        # summary warning is emitted with the surviving count.
        rec = ProvisionalElemBlock(block.keyword, "shell",
                                   "_" + "_".join(unknown))
        for line in raw:
            if not _is_connectivity_card(line, 5):
                if line.strip():
                    rec.n_unparsed += 1
                continue
            parsed = _parse_shell_base(line)
            if parsed is None:
                continue
            eid, pid, nodes, midside = parsed
            if eid in seen_eids:
                # A repeated id inside one block is a data card that happens to
                # be all-integer, not a second element.
                rec.n_unparsed += 1
                continue
            seen_eids.add(eid)
            if any(midside):
                n_midside += 1
            state.shell_elems.append(
                ShellElem(eid, pid, nodes, provisional=True))
            rec.eids.append(eid)
        state.provisional_elem_blocks.append(rec)
    else:
        want_thic = bool(opts & {"THICKNESS", "BETA", "MCID"})
        i = 0
        while i < len(raw):
            parsed = _parse_shell_base(raw[i])
            if parsed is None:
                i += 1
                continue
            eid, pid, nodes, midside = parsed
            i += 1
            thick_nodes: List[float] = []
            beta = 0.0
            if want_thic and i < len(raw):
                f = _card(raw, i, fixed=True, n=5, w=16)
                i += 1
                # A BLANK THIC cell is not "unspecified" — Card 2 gives it the
                # default 0., and Remark 1 makes 0. mean "take the *SECTION_
                # SHELL thickness for THIS node". So blank and 0.0 collapse to
                # the same stored value and the writer resolves both.
                thick_nodes = [to_float(f[k]) if len(f) > k else 0.0
                               for k in range(4)]
                fifth = f[4] if len(f) > 4 else ""
                if "MCID" in opts:
                    if fifth.strip() and to_int(fifth) != 0:
                        n_mcid += 1
                elif fifth.strip():
                    beta = to_float(fifth)
            if "THICKNESS" in opts and any(midside) and i < len(raw):
                i += 1                       # THIC5..THIC8, no /SHELL home
            if "OFFSET" in opts and i < len(raw):
                f = _card(raw, i, fixed=True, n=1, w=16)
                i += 1
                if f and f[0].strip() and to_float(f[0]) != 0.0:
                    n_offset += 1
            if "DOF" in opts and i < len(raw):
                # Card 5 is 10 x I8 with NS1..NS4 in fields 3-6 (the first two
                # columns are blank — Altair's shell.cfg writes it %16s + 4xI8).
                # Read it through _card so a comma/space-delimited spelling is
                # split free-format instead of being sliced at column 16, where
                # the scalar nodes would vanish and never be reported. The
                # values have no Radioss destination, so ANY non-zero field is
                # enough to raise the "dropped" warning — no field alignment to
                # get wrong.
                f = _card(raw, i, fixed=True, n=6, w=8)
                i += 1
                if any(to_int(x) for x in f):
                    n_dof += 1
            if any(midside):
                n_midside += 1
            state.shell_elems.append(
                ShellElem(eid, pid, nodes, thick_nodes, beta))

    if n_mcid:
        state.warn(
            f"*{block.keyword}: {n_mcid} element(s) carry a material "
            "coordinate-system id MCID — DROPPED. MCID names a "
            "*DEFINE_COORDINATE_SYSTEM, it is not the BETA angle, and Radioss "
            "/SHELL has no per-element material system: writing the id into the "
            "element's Phi column would silently rotate the material axes by "
            "<cid> DEGREES. If the layup orientation matters, give the part an "
            "orthotropic property (/PROP/TYPE9 or TYPE51) whose reference "
            "direction carries the same system.")
    if n_offset:
        state.warn(
            f"*{block.keyword}: {n_offset} element(s) carry a non-zero "
            "*ELEMENT_SHELL_OFFSET mid-surface offset — DROPPED. Radioss "
            "/SHELL has no per-element offset field, so every shell sits on the "
            "surface its nodes define; a model that relied on the offset to "
            "close a gap now has that gap (contact clearance, section modulus). "
            "Move the nodes, or split the parts, to model the offset.")
    if n_dof:
        state.warn(
            f"*{block.keyword}: {n_dof} element(s) carry *ELEMENT_SHELL_DOF "
            "scalar-node references NS1..NS4 — DROPPED (Radioss has no scalar "
            "nodal degrees of freedom). The shells themselves are unaffected.")
    if n_midside:
        state.warn(
            f"*{block.keyword}: {n_midside} element(s) define mid-side nodes "
            "N5..N8. Radioss /SHELL is 4-node only, so each is emitted as the "
            "LINEAR quad on N1..N4 and the mid-side nodes are dropped — the "
            "element loses its quadratic edges (coarser bending response, and "
            "the dropped nodes become unreferenced). Re-mesh with linear shells "
            "if this matters.")


def handle_element_plotel(block: Block, state: ConversionState) -> None:
    """*ELEMENT_PLOTEL → an inert /SPRING (see writer/loads.py).

    Card (Vol I R17): EID(I8) N1(I8) N2(I8). There is NO PID column — LS-DYNA
    assigns part id 10000000 implicitly, so the converter has to fabricate the
    part (and the property) itself.
    """
    for line in block.raw:
        f = [x for x in _elem_fields(line, 3) if x]
        if len(f) < 3:
            continue
        eid, n1, n2 = to_int(f[0]), to_int(f[1]), to_int(f[2])
        if eid <= 0 or n1 <= 0 or n2 <= 0:
            continue
        state.plotel_elems.append(PlotelElem(eid, n1, n2))


def handle_element_solid(block: Block, state: ConversionState) -> None:
    # Drop blank "" placeholders so format detection (which keys off raw[0]/raw[1])
    # and the ten-node line-pairing are never thrown off by an embedded/trailing
    # blank line. Element connectivity never uses all-defaults blank cards.
    raw = [ln for ln in block.raw if ln.strip()]
    if not raw:
        return

    # Detect format.  Use _elem_fields so both space-separated and dense 8-char fixed-width
    # are handled.  Ten-node format: first line has exactly 2 non-empty fields (eid+pid);
    # standard format: first line has >= 6 non-empty fields (eid+pid+n1..n4+).
    first_nonempty = [x for x in _elem_fields(raw[0], 10) if x]
    if len(first_nonempty) == 2 and len(raw) > 1:
        second_nonempty = [x for x in _elem_fields(raw[1], 10) if x]
        ten_node_fmt = len(second_nonempty) >= 4
    else:
        ten_node_fmt = len(first_nonempty) < 6  # treat very short lines as ten-node header too

    if ten_node_fmt:
        i = 0
        while i + 1 < len(raw):
            f1 = [x for x in _elem_fields(raw[i], 2) if x]
            f2 = [x for x in _elem_fields(raw[i + 1], 10) if x]
            if len(f1) < 2 or len(f2) < 4:
                i += 1
                continue
            eid = to_int(f1[0])
            pid = to_int(f1[1])
            all_nodes = [to_int(f2[j]) for j in range(min(10, len(f2)))]
            n9  = all_nodes[8] if len(all_nodes) > 8 else 0
            n10 = all_nodes[9] if len(all_nodes) > 9 else 0
            if n9 != 0 or n10 != 0:
                # True 10-node quadratic tetra (n1-n4 corners, n5-n10 mid-edge):
                # keep ALL 10 nodes. The writer emits these as /TETRA10. Storing
                # only the 4 corners would orphan every mid-edge node (no element
                # references it) → zero-stiffness DOFs → a singular implicit matrix.
                nodes = all_nodes[:10]
            else:
                # Pseudo-hex8 or tet4 in ten-node format (n9=n10=0): keep n1-n8.
                nodes = all_nodes[:8]
            state.solid_elems.append(SolidElem(eid, pid, nodes))
            i += 2
    else:
        for line in raw:
            f = [x for x in _elem_fields(line, 10) if x]
            if len(f) < 6:
                continue
            eid = to_int(f[0])
            pid = to_int(f[1])
            nodes = [to_int(f[i]) for i in range(2, min(10, len(f)))]
            state.solid_elems.append(SolidElem(eid, pid, nodes))


def _positional_elem_fields(line: str, n: int):
    """*ELEMENT_ card fields by COLUMN when a fixed I8 reading is consistent.

    ``_elem_fields`` drops empty fields, which is right for connectivity (a
    blank N4 is simply absent) but wrong for a card with INTERIOR blanks. The
    *ELEMENT_BEAM base card is exactly that shape: EID PID N1 N2 N3 RT1 RR1 RT2
    RR2 LOCAL, and the manual says that under _ORIENTATION "the field N3 should
    be left undefined" — so a beam that also sets LOCAL leaves fields 5-9 blank
    and the whitespace split reads the LOCAL flag as N3 (a silently wrong local
    frame, or an id that does not exist).

    The fixed slice is used only when it is CONSISTENT with the whitespace
    split — same values, same order — AND the four mandatory leading columns are
    filled. That is exactly the fixed-format-with-interior-gaps case. A genuine
    free-format line ("1,2,3,4,5") slices into fields with embedded separators
    and fails the comparison; a sloppily aligned one ("       1        2 …",
    where a value straddles a column boundary) fails the leading-column test.
    Both keep the whitespace reading, so no card that parsed before stops
    parsing now.
    """
    free = [x for x in _elem_fields(line, n) if x]
    if len(free) < 4:
        return free
    fixed = parse_fixed(_strip_inline_comment(line), n=n, w=8)
    if all(fixed[k] for k in range(4)) and [x for x in fixed if x] == free:
        return fixed
    return free


def _parse_beam_base(line: str):
    """One *ELEMENT_BEAM connectivity card → (eid, pid, n1, n2, n3) or None."""
    f = _positional_elem_fields(line, 10)
    # The orientation node N3 is optional (truss/ELFORM-3 beams omit it),
    # so 4 fields (eid pid n1 n2) is a complete card.
    if len(f) < 4 or not f[3]:
        return None
    eid, pid = to_int(f[0]), to_int(f[1])
    n1, n2 = to_int(f[2]), to_int(f[3])
    n3 = to_int(f[4]) if len(f) > 4 else 0
    return eid, pid, n1, n2, n3


def handle_element_beam(block: Block, state: ConversionState) -> None:
    """*ELEMENT_BEAM and its _ORIENTATION / _OFFSET spellings.

    _ORIENTATION's VX/VY/VZ is stored on the element; the writer prepass
    _synthesize_beam_orientation_nodes turns it into a real third node at
    ``pos(N1) + V`` (the dyna2rad mapping). _OFFSET has no /BEAM destination and
    is dropped with a counted warning; an unrecognized suffix still keeps every
    element.
    """
    opts, unknown = _elem_options(block.keyword, "ELEMENT_BEAM",
                                  _BEAM_SUFFIX_TOKENS)
    raw = block.raw
    n_offset = 0
    n_zerovec = 0

    if unknown and _elem_block_is_not_a_mesh(block, state, unknown):
        return

    if unknown:
        # See handle_element_shell: kept by CONTENT, marked provisional, and
        # screened against the node table before it reaches the deck.
        rec = ProvisionalElemBlock(block.keyword, "beam",
                                   "_" + "_".join(unknown))
        seen_eids: set = set()
        for line in raw:
            if not _is_connectivity_card(line, 4):
                if line.strip():
                    rec.n_unparsed += 1
                continue
            parsed = _parse_beam_base(line)
            if parsed is None:
                continue
            eid, pid, n1, n2, n3 = parsed
            if eid in seen_eids:
                rec.n_unparsed += 1
                continue
            seen_eids.add(eid)
            state.beam_elems.append(
                BeamElem(eid, pid, n1, n2, n3, provisional=True))
            rec.eids.append(eid)
        state.provisional_elem_blocks.append(rec)
        return

    i = 0
    while i < len(raw):
        parsed = _parse_beam_base(raw[i])
        if parsed is None:
            i += 1
            continue
        eid, pid, n1, n2, n3 = parsed
        i += 1
        vx = vy = vz = 0.0
        # Card order follows the manual's card numbering: _OFFSET (card 7)
        # before _ORIENTATION (card 8).
        if "OFFSET" in opts and i < len(raw):
            f = _card(raw, i, fixed=True, n=6, w=10)
            i += 1
            if any(to_float(x) for x in f):
                n_offset += 1
        if "ORIENTATION" in opts and i < len(raw):
            # 3 x F10 — NOT the F16 the shell's optional card uses.
            f = _card(raw, i, fixed=True, n=3, w=10)
            i += 1
            vx, vy, vz = (to_float(f[0]) if len(f) > 0 else 0.0,
                          to_float(f[1]) if len(f) > 1 else 0.0,
                          to_float(f[2]) if len(f) > 2 else 0.0)
            if vx == 0.0 and vy == 0.0 and vz == 0.0:
                n_zerovec += 1
        state.beam_elems.append(BeamElem(eid, pid, n1, n2, n3, vx, vy, vz))

    if n_offset:
        state.warn(
            f"*{block.keyword}: {n_offset} element(s) carry non-zero "
            "*ELEMENT_BEAM_OFFSET end offsets WX1..WZ2 — DROPPED. Radioss "
            "/BEAM has no per-element end-offset field, so each beam runs "
            "straight between its two nodes; a model that used the offsets to "
            "represent an eccentric connection now has that eccentricity (and "
            "its bending moment) missing. Add rigid links or move the nodes if "
            "the eccentricity matters.")
    if n_zerovec:
        state.warn(
            f"*{block.keyword}: {n_zerovec} element(s) give a ZERO orientation "
            "vector (VX=VY=VZ=0), so no third node can be synthesized. The "
            "beams keep whatever N3 their base card carries; the manual says "
            "that column should be left undefined under _ORIENTATION, and when "
            "it is, the OpenRadioss starter reports INFO 2093 and falls back to "
            "N3:=N2 — a degenerate local frame whose Iyy/Izz axes are "
            "solver-chosen. CHECK the emitted /BEAM node_ID3 column for these "
            "elements, then give them a real orientation vector (dyna2rad has "
            "the same behaviour, silently).")


def handle_element_discrete(block: Block, state: ConversionState) -> None:
    """*ELEMENT_DISCRETE → /SPRING (2-node spring/damper connector).

    Fixed card (Keyword971 ELEMENTS/discrete.cfg):
        EID(I8) PID(I8) N1(I8) N2(I8) VID(I8) S(E16) PF(I8) OFFSET(E16)
    Free-format lines carry the same field order. N2=0 = grounded element.
    """
    for line in block.raw:
        if not line.strip():
            continue
        f = parse_free(line)
        # Fixed I8 columns glue when an id fills all 8 chars — re-slice then
        # (S is E16 wide, so only the first five I8 fields can glue).
        if len(f) < 3 or any(len(t) > 8 for t in f[:5]):
            data = _strip_inline_comment(line)
            f = [data[0:8], data[8:16], data[16:24], data[24:32], data[32:40],
                 data[40:56], data[56:64], data[64:80]]
            f = [x.strip() for x in f]
        eid = to_int(f[0]) if f else 0
        pid = to_int(f[1]) if len(f) > 1 else 0
        if eid <= 0 or pid <= 0:
            continue
        n1 = to_int(f[2]) if len(f) > 2 else 0
        n2 = to_int(f[3]) if len(f) > 3 else 0
        vid = to_int(f[4]) if len(f) > 4 else 0
        s = _ffield(f, 5, 1.0)
        offset = to_float(f[7]) if len(f) > 7 else 0.0
        state.discrete_elems.append(DiscreteElem(eid, pid, n1, n2, vid, s, offset))


# ─────────────────────────────────────────────────────────────────────────────
# Parts
# ─────────────────────────────────────────────────────────────────────────────

def handle_part(block: Block, state: ConversionState) -> None:
    """*PART: (title card, data card) pairs — the pair may REPEAT inside one
    keyword block, so parse every pair, not just the first."""
    raw = block.raw
    if len(raw) < 2:
        title = raw[0].strip() if raw else ""
        state.warn(f"*PART missing data card – skipped (title='{title}')")
        return
    for i in range(0, len(raw) - 1, 2):
        title = raw[i].strip()
        # Data card: pid secid mid eosid hgid grav adpopt tmid
        f = _card(raw, i + 1, fixed=True, n=8, w=10)
        pid   = to_int(f[0])
        secid = to_int(f[1])
        mid   = to_int(f[2])
        # EOSID (field 4, cols 31-40) → the *EOS_* bound to this part's material
        # (routes *MAT_JOHNSON_COOK to /MAT/LAW4 + /EOS).
        eosid = to_int(f[3]) if len(f) > 3 else 0
        # HGID (field 5, cols 41-50) → the *HOURGLASS card overriding
        # *CONTROL_HOURGLASS for this part (0 = global card / defaults).
        hgid  = to_int(f[4]) if len(f) > 4 else 0
        if pid <= 0:
            state.warn(f"*PART: data card with no part id – skipped (title='{title}')")
            continue
        state.parts[pid] = PartData(pid, title, secid, mid, hgid, eosid)


# ─────────────────────────────────────────────────────────────────────────────
# Sections → Properties
# ─────────────────────────────────────────────────────────────────────────────

def handle_section_shell(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card 1: secid elform shrf nip propt qr/irid icomp setyp
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    # Card 2: t1 t2 t3 t4 nloc marea idof edgset
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    secid  = to_int(f1[0])
    elform = to_int(f1[1]) if f1[1] else 2
    nip    = to_int(f1[3]) if len(f1) > 3 else 3
    t1     = to_float(f2[0]) if f2 else 0.0
    state.sec_shells[secid] = SectionShell(secid, title, elform, nip, t1)


def handle_section_solid(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    secid  = to_int(f1[0]) if f1 else 0
    elform = to_int(f1[1]) if len(f1) > 1 else 1
    # ELFORM 11 (1-pt ALE multi-material) / 12 (1-pt ALE single material) mark the
    # property as ALE → /PROP/SOLID Iale=1.
    iale = 1 if elform in (11, 12) else 0
    if iale:
        state.warn(f"*SECTION_SOLID {secid}: ELFORM={elform} (ALE) -> /PROP/SOLID "
                   "Iale=1. If the mesh is fixed (Eulerian), switch Iale to 2 "
                   "(Euler) for a cheaper run.")
    state.sec_solids[secid] = SectionSolid(secid, title, elform, iale)


def handle_section_beam(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    secid  = to_int(f1[0]) if f1 else 0
    elform = to_int(f1[1]) if len(f1) > 1 else 2
    sec = SectionBeam(secid, title, elform)

    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if elform == 1:
        sec.ts1 = to_float(f2[0]) if f2 else 0.0
    elif elform == 9:
        # elform=9 spotweld beam: VOL INER CID CA OFFSET RRCON SRCON TRCON —
        # card 2 carries a nugget volume and cross-section area, NOT A/Iyy/Izz.
        sec.vol = to_float(f2[0]) if f2 else 0.0
        sec.ca  = to_float(f2[3]) if len(f2) > 3 else 0.0
        sec.area = sec.ca
    else:
        # elform=2 resultant: A IYY IZZ IXX
        sec.area = to_float(f2[0]) if f2 else 0.0
        sec.iyy  = to_float(f2[1]) if len(f2) > 1 else 0.0
        sec.izz  = to_float(f2[2]) if len(f2) > 2 else 0.0
        sec.ixx  = to_float(f2[3]) if len(f2) > 3 else 0.0
    state.sec_beams[secid] = sec


def handle_section_discrete(block: Block, state: ConversionState) -> None:
    """*SECTION_DISCRETE → /PROP/TYPE4 (SPRING) flags.

    Card1 (Keyword971 PROPERTY/SectDisc.cfg): SECID DRO KD V0 CL FD
    Card2: CDL TDL (compression/tension deflection limits, element deletion).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*SECTION_DISCRETE: empty card – skipped")
        return
    secid = to_int(f1[0])
    dro = to_int(f1[1]) if len(f1) > 1 else 0
    kd  = to_float(f1[2]) if len(f1) > 2 else 0.0
    v0  = to_float(f1[3]) if len(f1) > 3 else 0.0
    cl  = to_float(f1[4]) if len(f1) > 4 else 0.0
    fd  = to_float(f1[5]) if len(f1) > 5 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=2, w=10)
    cdl = to_float(f2[0]) if f2 else 0.0
    tdl = to_float(f2[1]) if len(f2) > 1 else 0.0
    state.sec_discrete[secid] = SectionDiscrete(secid, title, dro, kd, v0, cl,
                                                fd, cdl, tdl)


# ─────────────────────────────────────────────────────────────────────────────
# Materials
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_elastic(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: mid rho E PR DA DB K
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0])
    rho = to_float(f1[1])
    E   = to_float(f1[2])
    nu  = to_float(f1[3])
    state.mat_elastic[mid] = MatElastic(mid, title, rho, E, nu)


def _is_mat123(block: Block) -> bool:
    """*MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY (MAT_123) vs plain MAT_024.
    _split_keyword has already stripped _TITLE/_ID, so a bare keyword compare
    is enough to know whether card-2 slots 6/7/8 carry EPSTHIN/EPSMAJ/NUMINT."""
    return block.keyword in ("MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY",
                             "MAT_123")


def handle_mat_piecewise_linear_plasticity(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: mid rho E PR SIGY ETAN FAIL TDEL
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1])
    E    = to_float(f1[2])
    nu   = to_float(f1[3])
    sigy = to_float(f1[4])
    etan = to_float(f1[5])
    fail = to_float(f1[6]) if len(f1) > 6 else 0.0
    # Card2: C P LCSS LCSR VP  (+ EPSTHIN EPSMAJ NUMINT for MAT_123)
    f2   = _card(raw, offset + 1, fixed=True, n=8, w=10)
    C    = to_float(f2[0]) if f2 else 0.0
    P    = to_float(f2[1]) if len(f2) > 1 else 0.0
    lcss = to_int(f2[2])   if len(f2) > 2 else 0
    vp   = to_int(f2[4])   if len(f2) > 4 else 0
    # Card3: EPS1-EPS8
    f3   = _card(raw, offset + 2, fixed=False)
    eps_pts = [to_float(v) for v in f3]
    # Card4: ES1-ES8
    f4   = _card(raw, offset + 3, fixed=False)
    es_pts = [to_float(v) for v in f4]

    mat = MatPlasTAB(mid, title, rho, E, nu, sigy, etan, fail, lcss, C, P,
                     eps_pts, es_pts, vp=vp)
    # *MAT_123 carries three extra failure inputs in card-2 slots 6/7/8 (EPSTHIN
    # EPSMAJ NUMINT) that plain MAT_024 leaves blank; only read them for 123 so
    # a MAT_024 whose slots happen to be non-blank is not mis-parsed.
    if _is_mat123(block):
        mat.lcsr    = to_int(f2[3])   if len(f2) > 3 else 0
        mat.epsthin = to_float(f2[5]) if len(f2) > 5 else 0.0
        mat.epsmaj  = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.numint  = to_float(f2[7]) if len(f2) > 7 else 0.0
    # _LOG_INTERPOLATION (a MAT_024 keyword option; combines with _2D) selects
    # logarithmic strain-rate interpolation → LAW36 F_smooth=2 in the writer.
    mat.log_interp = "LOG_INTERPOLATION" in block.keyword
    state.mat_plas_tab[mid] = mat


def handle_mat_simplified_johnson_cook(block: Block, state: ConversionState) -> None:
    """*MAT_SIMPLIFIED_JOHNSON_COOK (MAT_098) → /MAT/LAW36 with a sampled
    hardening curve (or a family of rate-scaled curves when C != 0).

    Card 1: mid ro e pr vp epsf itype
    Card 2: a b n c psfail sigmax sigsat epso
    Yield stress σ(εp) = A + B·εpⁿ (capped at SIGMAX when given) is sampled
    into an auto-generated LAW36 yield table — the card layout shares NOTHING
    with MAT_024, so it must not go through that handler. When C is nonzero
    the strain-rate term (1 + C·ln(ε̇/EPSO)) is converted into a LAW36
    rate-function family: one sampled curve per reference rate ε̇_i, each the
    quasi-static curve scaled by max(1, 1 + C·ln(ε̇_i/EPSO)). VP (card 1)
    carries through to the LAW36 VP flag.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0])
    rho = to_float(f1[1])
    E   = to_float(f1[2])
    nu  = to_float(f1[3])
    vp  = to_int(f1[4]) if len(f1) > 4 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    a      = to_float(f2[0]) if f2 else 0.0
    b      = to_float(f2[1]) if len(f2) > 1 else 0.0
    n_exp  = to_float(f2[2]) if len(f2) > 2 else 0.0
    c      = to_float(f2[3]) if len(f2) > 3 else 0.0
    psfail = _ffield(f2, 4, 1e17)      # blank = no failure (LS-DYNA 1e17)
    sigmax = to_float(f2[5]) if len(f2) > 5 else 0.0
    epso   = _ffield(f2, 7, 1.0)       # reference rate; blank/0 → LS-DYNA 1.0
    if epso <= 0.0:
        epso = 1.0

    eps_samples = [0.0, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05,
                   0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0]
    eps_pts: List[float] = []
    es_pts: List[float] = []
    for e in eps_samples:
        s = a + (b * (e ** n_exp) if b != 0.0 and e > 0.0 else 0.0)
        if sigmax > 0.0:
            s = min(s, sigmax)
        eps_pts.append(e)
        es_pts.append(s)
    rate_curves: List = []
    if c != 0.0:
        # Reference rates: EPSO itself (scale factor exactly 1 — the JC term's
        # ln vanishes), then decades 1/10/100/1000/10000 above EPSO. The
        # scale factor is floored at 1 so a negative C (or a rate below EPSO,
        # excluded anyway) can never soften below the quasi-static curve.
        rates = [epso] + [r for r in (1.0, 10.0, 100.0, 1000.0, 10000.0)
                          if r > epso]
        for rate in rates:
            fac = max(1.0, 1.0 + c * _math.log(rate / epso))
            rate_curves.append(
                (rate, [(e, s * fac) for e, s in zip(eps_pts, es_pts)]))
        state.warn(
            f"*MAT_SIMPLIFIED_JOHNSON_COOK mid={mid}: strain-rate term "
            f"(1 + {c:g}·ln(ε̇/{epso:g})) converted to a /MAT/LAW36 "
            f"rate-function family of {len(rates)} sampled curves at "
            f"ε̇ = {', '.join(f'{r:g}' for r in rates)} "
            "(scale factor floored at 1).")
    fail = psfail if psfail < 1e16 else 0.0
    state.mat_plas_tab[mid] = MatPlasTAB(
        mid, title, rho, E, nu, a, 0.0, fail, 0, 0.0, 0.0, eps_pts, es_pts,
        vp=vp, rate_curves=rate_curves)


def handle_mat_johnson_cook(block: Block, state: ConversionState) -> None:
    """*MAT_JOHNSON_COOK (MAT_015) → /MAT/LAW2 (PLAS_JOHNS), or /MAT/LAW4
    (HYD_JCOOK) + a bound /EOS when the part attaches an equation of state.

    R16 card layout:
      Card 1: mid ro g e pr dtf vp rateop
      Card 2: a b n c m tm tr eps0
      Card 3: cp pc spall it d1 d2 d3 d4
      Card 4: d5 c2/p erod efmin numint   (R7 decks: d5 c2 <blank> efmin)

    The a/b/n/c/EPS0 flow-stress and m/TM/TR thermal terms map 1:1 onto LAW2
    (dyna2rad's attribMap); E falls back to 2G(1+ν) when only G is given, and
    CP (per MASS in LS-DYNA) is premultiplied by RHO because Radioss rhoC_p is
    per VOLUME. Blank EPS0 takes the LS-DYNA default 1.0 (dyna2rad copies the
    0 and trips starter ERROR 298 whenever C>0 — deliberately not replicated).
    The LAW2/LAW4 routing and the failure cards (DTF → /FAIL/GENE1 dtmin,
    D1-D5 → /FAIL/JOHNSON) are resolved in the writer, which needs the *PART
    EOSID binding (writer.materials._resolve_mat_johnson_cook).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    g   = to_float(f1[2]) if len(f1) > 2 else 0.0
    e   = to_float(f1[3]) if len(f1) > 3 else 0.0
    nu  = to_float(f1[4]) if len(f1) > 4 else 0.0
    dtf = to_float(f1[5]) if len(f1) > 5 else 0.0
    vp  = to_int(f1[6]) if len(f1) > 6 else 0
    rateop = to_float(f1[7]) if len(f1) > 7 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    a     = to_float(f2[0]) if f2 else 0.0
    b     = to_float(f2[1]) if len(f2) > 1 else 0.0
    n_exp = to_float(f2[2]) if len(f2) > 2 else 0.0
    c     = to_float(f2[3]) if len(f2) > 3 else 0.0
    m_exp = to_float(f2[4]) if len(f2) > 4 else 0.0
    tm    = to_float(f2[5]) if len(f2) > 5 else 0.0
    tr    = to_float(f2[6]) if len(f2) > 6 else 0.0
    epso  = _ffield(f2, 7, 1.0)     # blank → LS-DYNA default 1.0 (unit: 1/time)
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    cp    = to_float(f3[0]) if f3 else 0.0
    pc    = to_float(f3[1]) if len(f3) > 1 else 0.0
    spall = _ffield(f3, 2, 2.0)     # blank → LS-DYNA default spall model 2
    it    = to_float(f3[3]) if len(f3) > 3 else 0.0
    d1    = to_float(f3[4]) if len(f3) > 4 else 0.0
    d2    = to_float(f3[5]) if len(f3) > 5 else 0.0
    d3    = to_float(f3[6]) if len(f3) > 6 else 0.0
    d4    = to_float(f3[7]) if len(f3) > 7 else 0.0
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    d5     = to_float(f4[0]) if f4 else 0.0
    c2     = to_float(f4[1]) if len(f4) > 1 else 0.0
    erod   = to_float(f4[2]) if len(f4) > 2 else 0.0
    efmin  = to_float(f4[3]) if len(f4) > 3 else 0.0
    numint = to_float(f4[4]) if len(f4) > 4 else 0.0

    if e == 0.0 and g != 0.0:
        e = 2.0 * g * (1.0 + nu)    # dyna2rad's shear-modulus fallback
    if epso <= 0.0:
        epso = 1.0
        if c != 0.0:
            state.warn(f"*MAT_JOHNSON_COOK mid={mid}: EPS0 <= 0 with a nonzero "
                       "rate coefficient C — reset to the LS-DYNA default 1.0 "
                       "(in the deck's time unit) so the rate term stays "
                       "defined (OpenRadioss rejects EPS_DOT_0=0, ERROR 298).")
    if vp:
        # RATEOP only acts when VP=1 (LS-DYNA ignores it for VP=0), so it is
        # named in this warning rather than warned on its own.
        state.warn(f"*MAT_JOHNSON_COOK mid={mid}: VP={vp:g} (viscoplastic rate "
                   "formulation"
                   + (f", RATEOP={rateop:g}" if rateop else "")
                   + ") has no slot in the radioss140-format /MAT/LAW2 card a "
                   "/BEGIN 2022 deck reads — the total-strain-rate formulation "
                   "applies.")
    if spall not in (0.0, 2.0):
        state.warn(f"*MAT_JOHNSON_COOK mid={mid}: SPALL={spall:g} (non-default "
                   "spall model) has no LAW2/LAW4 equivalent — dropped; only "
                   "the PC pressure cutoff carries over (LAW4 Pmin).")
    if it:
        state.warn(f"*MAT_JOHNSON_COOK mid={mid}: IT={it:g} (plastic-strain "
                   "iteration accuracy flag) has no Radioss equivalent — "
                   "dropped (integration accuracy is solver-controlled).")
    if c2:
        state.warn(f"*MAT_JOHNSON_COOK mid={mid}: C2/P={c2:g} (second rate "
                   "parameter of the RATEOP forms) has no LAW2/LAW4 slot — "
                   "dropped; the classic log-linear JC rate term (C, EPS0) is "
                   "emitted.")
    if numint:
        state.warn(f"*MAT_JOHNSON_COOK mid={mid}: NUMINT={numint:g} "
                   "(integration points that must fail before deletion) is "
                   "approximated by the /FAIL/JOHNSON Ifail_sh=2 all-points "
                   "rule; the exact IP-count threshold is not reproduced.")
    state.mat_johnson_cook[mid] = MatJohnsonCook(
        mid=mid, title=title, rho=rho, e=e, nu=nu,
        a=a, b=b, n=n_exp, c=c, epso=epso,
        m=m_exp, tmelt=tm, tref=tr, rhocp=rho * cp, pc=pc,
        dtf=dtf, d1=d1, d2=d2, d3=d3, d4=d4, d5=d5,
        efmin=efmin, erod=erod)


def handle_mat_simplified_johnson_cook_ortho(block: Block,
                                             state: ConversionState) -> None:
    """*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE (MAT_099) →
    /MAT/LAW2 (PLAS_JOHNS) + an optional flat /FAIL/FLD (dyna2rad
    p_ConvertMatL99).

    R16 card layout:
      Card 1: mid ro e pr vp eppfr lcdm numint
      Card 2: a b n c psfail sigmax sigsat eps0

    The isotropic reduction follows dyna2rad: a/b/n/c → LAW2,
    EPPFR → EPS_p_max (deletion strain), SIG_max0 = min(SIGSAT, SIGMAX),
    Fsmooth=1, and PSFAIL>0 → a /FAIL/FLD whose flat limit curve sits at
    PSFAIL + A/E over minor strain -1..1. Deliberate deviations from dyna2rad:
    blank/zero EPS0 takes the LS-DYNA default 1.0 (not the 1e-20 rescue, which
    amplifies the ln(ε̇/ε̇₀) rate term ~46x), and SIGMAX/SIGSAT blanks take
    their LS-DYNA 1e28 defaults so min() cannot discard the one real cap
    (both-blank still means no cap). The LCDM orthotropic damage curve has no
    isotropic-LAW2 counterpart and is dropped with a warning.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    e   = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu  = to_float(f1[3]) if len(f1) > 3 else 0.0
    vp  = to_int(f1[4]) if len(f1) > 4 else 0
    eppfr  = to_float(f1[5]) if len(f1) > 5 else 0.0
    lcdm   = to_int(f1[6]) if len(f1) > 6 else 0
    numint = to_float(f1[7]) if len(f1) > 7 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    a      = to_float(f2[0]) if f2 else 0.0
    b      = to_float(f2[1]) if len(f2) > 1 else 0.0
    n_exp  = to_float(f2[2]) if len(f2) > 2 else 0.0
    c      = to_float(f2[3]) if len(f2) > 3 else 0.0
    psfail = to_float(f2[4]) if len(f2) > 4 else 0.0
    sigmax = _ffield(f2, 5, 1e28)   # blank → LS-DYNA default (no cap)
    sigsat = _ffield(f2, 6, 1e28)
    epso   = _ffield(f2, 7, 1.0)
    if epso <= 0.0:
        epso = 1.0                  # LS-DYNA default; see docstring
    sig_max0 = min(sigsat, sigmax)
    if sig_max0 >= 1e19:
        sig_max0 = 0.0              # no cap → LAW2 blank (starter 1e30)
    eps_p_max = eppfr if 0.0 < eppfr < 1e15 else 0.0
    if vp:
        state.warn(f"*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE mid={mid}: "
                   f"VP={vp:g} has no slot in the radioss140-format /MAT/LAW2 "
                   "card — the total-strain-rate formulation applies.")
    if lcdm:
        state.warn(f"*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE mid={mid}: "
                   f"LCDM={lcdm} (nonlinear orthotropic damage curve) has no "
                   "isotropic /MAT/LAW2 counterpart — the material converts as "
                   "isotropic Johnson-Cook (dyna2rad drops it too); the damage "
                   "evolution is NOT reproduced.")
    if numint:
        state.warn(f"*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE mid={mid}: "
                   f"NUMINT={numint:g} is approximated by the /FAIL/FLD "
                   "Ifail_sh=2 all-points rule; the exact IP-count threshold "
                   "is not reproduced.")
    state.mat_johnson_cook[mid] = MatJohnsonCook(
        mid=mid, title=title, rho=rho, e=e, nu=nu,
        a=a, b=b, n=n_exp, c=c, epso=epso,
        eps_p_max=eps_p_max, sig_max0=sig_max0, fsmooth=1,
        ortho=True, psfail=psfail if 0.0 < psfail < 1e16 else 0.0)


def handle_mat_anisotropic_viscoplastic(block: Block, state: ConversionState) -> None:
    """*MAT_ANISOTROPIC_VISCOPLASTIC (MAT_103) → /MAT/LAW128 (HILL_VISC_PLAST).

    LAW128 is the near 1:1 OpenRadioss counterpart of MAT_103: it carries the
    same two-term Voce isotropic hardening (QR/CR), two-term kinematic
    back-stress (QX/CX), a Cowper-Symonds rate term, and the Hill'48 surface from
    either the shell Lankford ratios R00/R45/R90 or the brick coefficients
    F/G/H/L/M/N. The full parameter set is stored on ``state.mat_aniso_visco``;
    the writer (_emit_mat_law128) does the field mapping and warns about the two
    approximations (VK/VM additive overstress → Cowper-Symonds; the iso/kin split
    CHARD). Because every Radioss Hill law is orthotropic-only, the writer also
    synthesizes a companion orthotropic property (/PROP/TYPE9 shell / TYPE6
    solid) for each part that uses this material — see
    writer.mesh._assign_ortho_props.

    Card layout (LS-DYNA hm_cfg_files mat_103.cfg):
      Card1: MID RHO E PR SIGY FLAG LCSS ALPHA
      Card2: QR1 CR1 QR2 CR2 QX1 CX1 QX2 CX2
      Card3: VK VM R00_F R45_G R90_H L M N
      Card4: AOPT FAIL NUMINT MACF   (axis cards 5-6 are not needed for LAW128)
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: MID RHO E PR SIGY FLAG LCSS ALPHA
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1])
    E    = to_float(f1[2])
    nu   = to_float(f1[3])
    sigy = to_float(f1[4]) if len(f1) > 4 else 0.0
    flag = to_int(f1[5])   if len(f1) > 5 else 0
    lcss = to_int(f1[6])   if len(f1) > 6 else 0
    alpha = to_float(f1[7]) if len(f1) > 7 else 0.0
    # Card2: QR1 CR1 QR2 CR2 QX1 CX1 QX2 CX2
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0
    qr1, cr1, qr2, cr2 = g2(0), g2(1), g2(2), g2(3)
    qx1, cx1, qx2, cx2 = g2(4), g2(5), g2(6), g2(7)
    # Card3: VK VM R00_F R45_G R90_H L M N
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    g3 = lambda i: to_float(f3[i]) if len(f3) > i else 0.0
    vk, vm = g3(0), g3(1)
    r00, r45, r90 = g3(2), g3(3), g3(4)
    hl, hm, hn = g3(5), g3(6), g3(7)          # brick Hill L, M, N
    # Card4: AOPT FAIL NUMINT MACF
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    aopt   = to_float(f4[0]) if len(f4) > 0 else 0.0
    fail   = to_float(f4[1]) if len(f4) > 1 else 0.0
    numint = to_float(f4[2]) if len(f4) > 2 else 0.0
    # Card5: XP YP ZP A1 A2 A3   Card6: V1 V2 V3 D1 D2 D3 BETA. Each field sits in
    # a fixed slot (blank where the current AOPT does not use it), so read every
    # slot unconditionally — the meaningful ones are non-blank for that AOPT.
    f5 = _card(raw, offset + 4, fixed=True, n=8, w=10)
    g5 = lambda i: to_float(f5[i]) if len(f5) > i else 0.0
    xp, yp, zp = g5(0), g5(1), g5(2)
    a1, a2, a3 = g5(3), g5(4), g5(5)
    f6 = _card(raw, offset + 5, fixed=True, n=8, w=10)
    g6 = lambda i: to_float(f6[i]) if len(f6) > i else 0.0
    v1, v2, v3 = g6(0), g6(1), g6(2)
    beta = g6(6)

    # Shift guard. MAT_103 is fixed-format positional: card 2 (QR/CR/QX/CX) is
    # MANDATORY as a physical line even though FLAG=1/2 makes its VALUES ignored
    # (the yield then comes from LCSS). A deck that OMITS the blank card-2 line —
    # a common hand-editing error when FLAG>=1 — shifts every following card up
    # by one, so the Hill card (VK VM F G H L M N) is read as card 2 and its
    # F/G/H/L/M/N leak into the hardening slots. The fingerprint: FLAG=1/2 with
    # nonzero QR/CR/QX/CX AND all-zero L/M/N (the true L/M/N shifted out onto the
    # AOPT card, which has no slots 6-8). Warn loudly — a silent shift produces a
    # wrong material with no error.
    if (flag in (1, 2)
            and any(v != 0.0 for v in (qr1, cr1, qr2, cr2, qx1, cx1, qx2, cx2))
            and hl == 0.0 and hm == 0.0 and hn == 0.0):
        state.warn(
            f"*MAT_ANISOTROPIC_VISCOPLASTIC mid={mid}: FLAG={flag} drives the "
            f"yield from LCSS={lcss}, so the card-2 hardening line (QR/CR/QX/CX) "
            "is ignored and should be blank — but NONZERO values were read there "
            "while the Hill L/M/N came out zero. This is the signature of a "
            "MISSING card-2 line (a common fixed-format error when FLAG>=1): every "
            "card then shifts up one and the Hill F/G/H/L/M/N leak into the "
            "QR/CR/QX/CX slots, silently corrupting the material. Insert a blank "
            "card-2 line (eight zeros) between the card-1 line and the "
            "'vk vm f g h l m n' line, then re-convert. If the QR/CR/QX/CX values "
            "are intentional, note they are IGNORED under FLAG=1/2.")

    state.mat_aniso_visco[mid] = MatAnisoViscoplastic(
        mid=mid, title=title, rho=rho, E=E, nu=nu, sigy=sigy,
        flag=flag, lcss=lcss, alpha=alpha,
        qr1=qr1, cr1=cr1, qr2=qr2, cr2=cr2,
        qx1=qx1, cx1=cx1, qx2=qx2, cx2=cx2,
        vk=vk, vm=vm, r00=r00, r45=r45, r90=r90, hl=hl, hm=hm, hn=hn,
        fail=fail, numint=numint, aopt=aopt,
        a1=a1, a2=a2, a3=a3, v1=v1, v2=v2, v3=v3, xp=xp, yp=yp, zp=zp, beta=beta)


# ─────────────────────────────────────────────────────────────────────────────
# Composites
# ─────────────────────────────────────────────────────────────────────────────
# All four composite/orthotropic material families share the LS-DYNA material-
# axis cards, and follow the MAT_103 convention established above: each AOPT
# slot sits at a FIXED position and is blank where the active AOPT does not use
# it, so the handler reads every slot unconditionally and ALL AOPT branching
# lives in the writer (writer/composites.py::_composite_ref_axis).

def _read_axis_cards(raw: List[str], i_point: int, i_vect: int):
    """Read the two shared material-axis cards of MAT_002 / MAT_054.

    ``i_point`` is the index of the ``XP YP ZP A1 A2 A3 [MACF/MANGLE] [IHIS]``
    card and ``i_vect`` that of the ``V1 V2 V3 D1 D2 D3 [BETA] [REF]`` card.
    Returns ``(xp, yp, zp, a1, a2, a3, f7, v1, v2, v3, d1, d2, d3, beta)`` where
    ``f7`` is field 7 of the point card (MACF for MAT_002, MANGLE for MAT_054).
    """
    fp = _card(raw, i_point, fixed=True, n=8, w=10)
    gp = lambda i: to_float(fp[i]) if len(fp) > i else 0.0     # noqa: E731
    fv = _card(raw, i_vect, fixed=True, n=8, w=10)
    gv = lambda i: to_float(fv[i]) if len(fv) > i else 0.0     # noqa: E731
    return (gp(0), gp(1), gp(2), gp(3), gp(4), gp(5), gp(6),
            gv(0), gv(1), gv(2), gv(3), gv(4), gv(5), gv(6))


def handle_mat_orthotropic_elastic(block: Block, state: ConversionState) -> None:
    """*MAT_ORTHOTROPIC_ELASTIC (MAT_002) → /MAT/LAW93 (ORTH_HILL).

    Card layout (LS-DYNA Manual Vol II R16 p.2-155, ORTHO variant):
      Card1a.1: MID RO EA EB EC PRBA PRCA PRCB
      Card1a.2: GAB GBC GCA AOPT G SIGF
      Card2:    XP YP ZP A1 A2 A3 MACF IHIS
      Card3:    V1 V2 V3 D1 D2 D3 BETA REF

    The Poisson conversion (``NU12 = PRBA·EA/EB``) and the GBC/GCA→G23/G13 swap
    are done in the writer; this handler only stores the raw LS-DYNA fields.
    ``G``/``SIGF`` (fields 5-6 of card 1a.2) and ``REF`` are read by the cfg but
    have no LAW93 counterpart — dropped, as in dyna2rad.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    (xp, yp, zp, a1, a2, a3, macf,
     v1, v2, v3, d1, d2, d3, beta) = _read_axis_cards(raw, offset + 2, offset + 3)
    state.mat_orthotropic[mid] = MatOrthotropicElastic(
        mid=mid, title=title, rho=g1(1),
        ea=g1(2), eb=g1(3), ec=g1(4),
        prba=g1(5), prca=g1(6), prcb=g1(7),
        gab=g2(0), gbc=g2(1), gca=g2(2), aopt=g2(3),
        xp=xp, yp=yp, zp=zp, a1=a1, a2=a2, a3=a3,
        v1=v1, v2=v2, v3=v3, d1=d1, d2=d2, d3=d3,
        beta=beta, macf=int(macf))


def handle_mat_anisotropic_elastic(block: Block, state: ConversionState) -> None:
    """*MAT_ANISOTROPIC_ELASTIC / *MAT_002_ANIS — recognized, NOT converted.

    The ANISOTROPIC dialect replaces cards 1a.1/1a.2 with the 21 constants of
    the full 6×6 constitutive matrix (C11…C66) and leaves EA…GCA empty:

      Card1b.1: MID RO C11 C12 C22 C13 C23 C33
      Card1b.2: C14 C24 C34 C44 C15 C25 C35 C45
      Card1b.3: C55 C16 C26 C36 C46 C56 C66 AOPT

    /MAT/LAW93 has slots for nine ENGINEERING constants only (E11…NU23) — there
    is no home for the 12 anisotropic coupling terms. dyna2rad's ``p_ConvertMatL2``
    never checks the dialect and emits a /MAT/LAW93 with ALL MODULI ZERO, with no
    warning (a silently massless, stiffness-free material). k2rad refuses to
    write that: the material is skipped with a loud warning instead, so the
    failure is impossible to miss rather than impossible to see.

    Inverting C to engineering constants is deliberately NOT attempted — it is
    only well-defined when every coupling term vanishes (i.e. the material is
    really orthotropic), and guessing the Voigt shear-index convention would
    risk a silently wrong material, which is exactly the failure mode being
    avoided here. Rewrite such a material as *MAT_ORTHOTROPIC_ELASTIC.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0]) if f1 else 0
    pids = sorted(p.pid for p in state.parts.values() if p.mid == mid)
    state.warn(
        f"*MAT_ANISOTROPIC_ELASTIC (MAT_002 ANIS dialect) mid={mid}: the full "
        "6x6 constitutive matrix (C11...C66) has NO /MAT/LAW93 counterpart — "
        "LAW93 carries nine engineering constants (E11/E22/E33, G12/G13/G23, "
        "NU12/NU13/NU23) and cannot hold the 12 anisotropic coupling terms. "
        "The material is NOT emitted. (dyna2rad converts this dialect to a "
        "/MAT/LAW93 with all moduli ZERO and no warning — a silently "
        "stiffness-free material; k2rad refuses to write that.) Re-state the "
        "material as *MAT_ORTHOTROPIC_ELASTIC with EA/EB/EC, GAB/GBC/GCA and "
        "PRBA/PRCA/PRCB to convert it"
        + (f"; part(s) {pids} reference it and will have no /MAT."
           if pids else "."))
    state.note_recognized_not_emitted(
        block.keyword,
        "MAT_002 ANISOTROPIC dialect: the 6x6 C-matrix has no /MAT/LAW93 "
        "counterpart (see the warning); no /MAT emitted")


def handle_mat_enhanced_composite_damage(block: Block, state: ConversionState) -> None:
    """*MAT_ENHANCED_COMPOSITE_DAMAGE (MAT_054 / MAT_055) → /MAT/LAW127.

    Card layout (LS-DYNA Manual Vol II R16; card order cross-checked against
    ``hm_cfg_files/.../M054_55.cfg FORMAT(Keyword971_R14.1)``):
      Card1: MID RO EA EB EC PRBA PRCA PRCB
      Card2: GAB GBC GCA (KF) AOPT 2WAY TI
      Card3: XP YP ZP A1 A2 A3 MANGLE
      Card4: V1 V2 V3 D1 D2 D3 [DFAILM DFAILS]
      Card5: TFAIL ALPH SOFT FBRT [YCFAC DFAILT DFAILC EFS]
      Card6: XC XT YC YT SC CRIT BETA
      Card7: PFL EPSF EPSR TSMD SOFT2                        (optional)
      Card8: SLIMT1 SLIMC1 SLIMT2 SLIMC2 SLIMS NCYRED SOFTG  (only if 7)
      Card9: LCXC LCXT LCYC LCYT LCSC DT                     (only if 7 and 8)

    Two parsing rules the manual states only circularly:

    * **Card 4 is always exactly one physical line.** The manual says "include
      card 4a if DFAILT != 0", but DFAILT lives on card 5 — so cols 1-60 are read
      unconditionally and cols 61-80 are read as DFAILM/DFAILS and discarded when
      DFAILT <= 0 (which is what the cfg's CARD_PREREAD on card 5 decides for the
      export side).
    * **Cards 7/8/9 are strictly cascading FREE_CARDs**: 8 is only read if 7 was,
      9 only if 7 and 8 were. Presence is positional, so it is taken from the
      block's line count.

    MAT_055 shares the layout; its card 5 simply leaves fields 5-8 blank and it
    carries no cards 7/8/9, so reading every slot unconditionally is correct for
    both spellings. The 54-vs-55 criterion itself lives in CRIT (card 6 field 6),
    which overrides the keyword spelling.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    kw = block.keyword
    is55 = ("055" in kw) or kw.endswith("_55") or ("_55_" in kw)

    def cf(idx, i, default=0.0):
        f = _card(raw, offset + idx, fixed=True, n=8, w=10)
        return to_float(f[i]) if len(f) > i and f[i].strip() else default

    def ci(idx, i, default=0):
        f = _card(raw, offset + idx, fixed=True, n=8, w=10)
        return to_int(f[i]) if len(f) > i and f[i].strip() else default

    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0]) if f1 else 0
    # Cards 3/4 = the shared axis pair (field 7 of card 3 is MANGLE here).
    (xp, yp, zp, a1, a2, a3, mangle,
     v1, v2, v3, d1, d2, d3, _b) = _read_axis_cards(raw, offset + 2, offset + 3)
    dfailt = cf(4, 5)
    # Card-4 cols 61-80 only carry DFAILM/DFAILS when DFAILT > 0 (see docstring).
    dfailm = cf(3, 6) if dfailt > 0.0 else 0.0
    dfails = cf(3, 7) if dfailt > 0.0 else 0.0

    # Cascading optional cards: count the DATA lines this block actually has.
    ncards = 0
    for k in range(len(raw) - offset):
        if raw[offset + k].strip():
            ncards = k + 1
    has7 = ncards >= 7
    has8 = has7 and ncards >= 8
    has9 = has8 and ncards >= 9

    mat = MatEnhancedCompositeDamage(
        mid=mid, title=title, rho=cf(0, 1),
        ea=cf(0, 2), eb=cf(0, 3), ec=cf(0, 4),
        prba=cf(0, 5), prca=cf(0, 6), prcb=cf(0, 7),
        gab=cf(1, 0), gbc=cf(1, 1), gca=cf(1, 2), kf=cf(1, 3),
        aopt=cf(1, 4), two_way=cf(1, 5), ti=cf(1, 6),
        xp=xp, yp=yp, zp=zp, a1=a1, a2=a2, a3=a3, mangle=mangle,
        v1=v1, v2=v2, v3=v3, d1=d1, d2=d2, d3=d3,
        dfailm=dfailm, dfails=dfails,
        tfail=cf(4, 0), alph=cf(4, 1), soft=cf(4, 2, 1.0), fbrt=cf(4, 3),
        ycfac=cf(4, 4, 2.0), dfailt=dfailt, dfailc=cf(4, 6), efs=cf(4, 7),
        xc=cf(5, 0), xt=cf(5, 1), yc=cf(5, 2), yt=cf(5, 3), sc=cf(5, 4),
        crit=cf(5, 5), beta=cf(5, 6),
        pfl=cf(6, 0) if has7 else 0.0,
        epsf=cf(6, 1) if has7 else 0.0,
        epsr=cf(6, 2) if has7 else 0.0,
        tsmd=cf(6, 3, 0.9) if has7 else 0.9,
        soft2=cf(6, 4, 1.0) if has7 else 1.0,
        slimt1=cf(7, 0, 1.0) if has8 else 1.0,
        slimc1=cf(7, 1, 1.0) if has8 else 1.0,
        slimt2=cf(7, 2, 1.0) if has8 else 1.0,
        slimc2=cf(7, 3, 1.0) if has8 else 1.0,
        slims=cf(7, 4, 1.0) if has8 else 1.0,
        ncyred=cf(7, 5) if has8 else 0.0,
        softg=cf(7, 6, 1.0) if has8 else 1.0,
        lcxc=ci(8, 0) if has9 else 0,
        lcxt=ci(8, 1) if has9 else 0,
        lcyc=ci(8, 2) if has9 else 0,
        lcyt=ci(8, 3) if has9 else 0,
        lcsc=ci(8, 4) if has9 else 0,
        dt=cf(8, 5) if has9 else 0.0,
        keyword_is_55=is55)
    if ncards > 9:
        state.warn(
            f"*MAT_ENHANCED_COMPOSITE_DAMAGE mid={mid}: {ncards} data cards were "
            "read where the keyword defines at most 9 — the extra line(s) are "
            "IGNORED. This is the fingerprint of a fixed-format card shift (a "
            "missing or duplicated blank card), which silently moves every "
            "following field into the wrong slot; check the card order against "
            "MID/RO/EA.. | GAB/GBC/GCA/KF/AOPT.. | XP.. | V1.. | TFAIL.. | "
            "XC/XT/YC/YT/SC/CRIT/BETA | PFL.. | SLIMT1.. | LCXC..")
    state.mat_enhanced_composite[mid] = mat


def handle_mat_transversely_anisotropic(block: Block, state: ConversionState) -> None:
    """*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC (MAT_037) → /MAT/LAW43.

    Card layout:
      Card1: MID RO E PR SIGY ETAN R HLCID
      Card2: IDSCALE EA COE ICFLD _ STRAINLT      (option-dependent slots)

    Card 2 exists in three option-specific shapes (_ECHANGE fills fields 1-3,
    _NLP_FAILURE fields 4 and 6, _NLP2 field 4, _ECHANGE_NLP_FAILURE all of
    them), each field at a FIXED column — so every slot is read unconditionally,
    the same convention as the MAT_103/MAT_002 axis cards.

    ``R < 0`` selects a stabilized algorithm, not a negative ratio: the writer
    takes |R|.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    kw = block.keyword
    if "ECHANGE" in kw and "NLP" in kw:
        opt = 5
    elif "NLP2" in kw:
        opt = 4
    elif "NLP_FAILURE" in kw:
        opt = 3
    elif "ECHANGE" in kw:
        opt = 2
    else:
        opt = 1
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    state.mat_transverse_aniso[mid] = MatTransverselyAnisotropic(
        mid=mid, title=title, rho=g1(1), E=g1(2), nu=g1(3),
        sigy=g1(4), etan=g1(5), r=g1(6),
        hlcid=to_int(f1[7]) if len(f1) > 7 else 0,
        idscale=to_int(f2[0]) if len(f2) > 0 and f2[0].strip() else 0,
        ea=g2(1), coe=g2(2),
        icfld=to_int(f2[3]) if len(f2) > 3 and f2[3].strip() else 0,
        strainlt=g2(5), echange_option=opt)


def handle_mat_laminated_glass(block: Block, state: ConversionState) -> None:
    """*MAT_LAMINATED_GLASS (MAT_032) → a /MAT/PLAS_BRIT (LAW27) glass+polymer pair.

    Card layout:
      Card1: MID RO EG PRG SYG ETG EFG EP
      Card2: PRP SYP ETP
      Card3+: F1..F8, repeating up to 4 lines (max 32 integration points)

    ``F_i = 0.0`` marks integration point *i* as GLASS, ``1.0`` as POLYMER
    (LS-DYNA Manual Vol II, *MAT_032). The F array runs to the end of the block.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    fvals: List[float] = []
    for idx in range(offset + 2, len(raw)):
        if not raw[idx].strip():
            continue
        fc = _card(raw, idx, fixed=True, n=8, w=10)
        for tok in fc:
            if tok.strip():
                fvals.append(to_float(tok))
    state.mat_laminated_glass[mid] = MatLaminatedGlass(
        mid=mid, title=title, rho=g1(1),
        eg=g1(2), prg=g1(3), syg=g1(4), etg=g1(5), efg=g1(6), ep=g1(7),
        prp=g2(0), syp=g2(1), etp=g2(2), f=fvals[:32])


def handle_part_composite(block: Block, state: ConversionState) -> None:
    """*PART_COMPOSITE (+ _TITLE / _LONG / _CONTACT / _TSHELL / _IGA_SHELL).

    A *PART that carries its own per-ply layup instead of a *SECTION reference →
    /PROP/TYPE51 (stack) + one /PROP/TYPE19 (PLY) per layer.

    Card layout:
      Card1: HEADING (the whole line)                       — ALWAYS present
      Card2: "OPTCARD" IRPL                                 — only if cols 1-7
             spell OPTCARD
      Card3a: PID ELFORM SHRF NLOC MAREA HGID ADPOPT THSHEL  (thin shell)
      Card3b: PID ELFORM SHRF _ _ HGID _ TSHEAR              (_TSHELL)
      Card3c: PID ELFORM SHRF NLOC _ IRL                     (_IGA_SHELL)
      Card4: FS FD DC VC OPTT SFT SSF                        — only _CONTACT
      Card5a: MID1 THICK1 B1 TMID1 MID2 THICK2 B2 TMID2      (2 layers/line)
      Card5b: MID1 THICK1 B1 TMID1 PLYID1 SHRFAC1            (_LONG, 1/line)

    A *PART record is ALWAYS registered, for every variant — including ones the
    property converter cannot handle. k2rad emits elements inside the
    ``state.parts`` loop, so a part with no PartData silently takes its whole
    mesh with it; an unsupported layup must degrade to a plain shell property,
    never to a lost part.

    Field 4 of card 5a is TMID (thermal material id), NOT MID2: the pairing is
    ``(MID, THICK, B, TMID) | (MID, THICK, B, TMID)``. The sibling keyword
    *ELEMENT_SHELL_COMPOSITE uses the same 8-column line with fields 4 and 8
    blank, so the two line parsers must not be shared blindly.
    """
    raw = block.raw
    kw = block.keyword
    if not raw:
        state.warn("*PART_COMPOSITE: empty block – skipped")
        return
    # Card 1 is the heading card in EVERY variant (the _TITLE option adds no
    # second line — *PART_COMPOSITE always heads its data with a title card).
    title = raw[0].strip()
    idx = 1
    irpl = 0
    if idx < len(raw) and raw[idx][:7].upper() == "OPTCARD":
        fo = _card(raw, idx, fixed=True, n=8, w=10)
        irpl = to_int(fo[1]) if len(fo) > 1 else 0
        idx += 1
    fd = _card(raw, idx, fixed=True, n=8, w=10)
    if not fd or not fd[0].strip():
        state.warn(f"*PART_COMPOSITE '{title}': no data card (PID) – skipped")
        return
    pid = to_int(fd[0])
    if pid <= 0:
        state.warn(f"*PART_COMPOSITE '{title}': data card with no part id – skipped")
        return
    variant = ""
    if "TSHELL" in kw:
        variant = "TSHELL"
    elif "IGA_SHELL" in kw or "IGA" in kw:
        variant = "IGA_SHELL"
    elform = to_int(fd[1]) if len(fd) > 1 and fd[1].strip() else 0
    # A BLANK SHRF is recorded as 0.0 = "not given" rather than as LS-DYNA's
    # own 1.0 default, so the writer can leave Radioss's 5/6 Ashear in place.
    shrf = to_float(fd[2]) if len(fd) > 2 and fd[2].strip() else 0.0
    nloc = to_float(fd[3]) if len(fd) > 3 and fd[3].strip() and variant != "TSHELL" else 0.0
    marea = to_float(fd[4]) if len(fd) > 4 and fd[4].strip() and variant == "" else 0.0
    hgid = to_int(fd[5]) if len(fd) > 5 and fd[5].strip() else 0
    adpopt = to_int(fd[6]) if len(fd) > 6 and fd[6].strip() and variant == "" else 0
    thshel = to_int(fd[7]) if len(fd) > 7 and fd[7].strip() and variant == "" else 0
    idx += 1
    optt = 0.0
    if "CONTACT" in kw:
        fc = _card(raw, idx, fixed=True, n=8, w=10)
        optt = to_float(fc[4]) if len(fc) > 4 and fc[4].strip() else 0.0
        idx += 1
    long_form = "LONG" in kw
    plies: List[CompositePly] = []
    for j in range(idx, len(raw)):
        line = raw[j]
        if not line.strip():
            continue
        fl = _card(raw, j, fixed=True, n=8, w=10)
        if long_form:
            groups = [(0, 1, 2, 3)]
        else:
            groups = [(0, 1, 2, 3), (4, 5, 6, 7)]
        for gi, (im, it, ib, ix) in enumerate(groups):
            if len(fl) <= im or not fl[im].strip():
                continue
            lmid = to_int(fl[im])
            lthk = to_float(fl[it]) if len(fl) > it else 0.0
            lbet = to_float(fl[ib]) if len(fl) > ib else 0.0
            if long_form:
                plies.append(CompositePly(
                    mid=lmid, thick=lthk, beta=lbet,
                    tmid=to_int(fl[ix]) if len(fl) > ix else 0,
                    plyid=to_int(fl[4]) if len(fl) > 4 and fl[4].strip() else 0,
                    shrfac=to_float(fl[5]) if len(fl) > 5 else 0.0))
            else:
                plies.append(CompositePly(
                    mid=lmid, thick=lthk, beta=lbet,
                    tmid=to_int(fl[ix]) if len(fl) > ix else 0))
    state.part_composites[pid] = PartComposite(
        pid=pid, title=title, elform=elform, shrf=shrf, nloc=nloc, marea=marea,
        hgid=hgid, adpopt=adpopt, thshel=thshel, plies=plies, variant=variant,
        long_form=long_form, irpl=irpl, optt=optt)
    # ALWAYS register the *PART itself (SECID 0 → the writer auto-creates a
    # *SECTION_SHELL under the part id if the layup cannot be converted), so the
    # part's elements are emitted whatever happens to the property.
    #
    # The fallback mat_ID must come from the first REAL ply, mirroring the
    # writer's _valid_plies filter: LS-DYNA's "missing ply" padding is
    # MID = -1 with THICK = 0, and a layup that leads with it would otherwise
    # put a negative material id on the /PART, which references no material and
    # is rejected by the starter — defeating the whole point of the
    # mesh-preserving fallback.
    if pid not in state.parts:
        fallback_mid = next((p.mid for p in plies if p.mid > 0 and p.thick > 0.0),
                            0)
        if plies and fallback_mid == 0:
            state.warn(
                f"*PART_COMPOSITE {pid}: every layer is 'missing ply' padding "
                "(MID <= 0 or zero thickness), so the fallback *PART carries no "
                "material. The part and its elements are still emitted, but the "
                "starter will reject the /PART until a real ply material is "
                "given.")
        state.parts[pid] = PartData(pid, title, 0, fallback_mid, hgid, 0)


def handle_mat_plastic_kinematic(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: mid rho E PR SIGY ETAN BETA
    f1  = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1])
    E    = to_float(f1[2])
    nu   = to_float(f1[3])
    sigy = to_float(f1[4])
    etan = to_float(f1[5])
    beta = to_float(f1[6]) if len(f1) > 6 else 0.0
    # Card2: SRC SRP FS VP  (Cowper-Symonds strain-rate params, failure strain)
    f2  = _card(raw, offset + 1, fixed=True, n=4, w=10)
    src = to_float(f2[0]) if f2 else 0.0
    srp = to_float(f2[1]) if len(f2) > 1 else 0.0
    fs  = to_float(f2[2]) if len(f2) > 2 else 0.0
    vp  = to_int(f2[3])   if len(f2) > 3 else 0
    state.mat_plas_kin[mid] = MatPlasKin(mid, title, rho, E, nu, sigy, etan, beta,
                                         src, srp, fs, vp)


def handle_mat_rigid(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: mid rho E PR N COUPLE M ALIAS
    f1  = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0])
    rho = to_float(f1[1])
    E   = to_float(f1[2])
    nu  = to_float(f1[3])
    # Card2: CMO CON1 CON2
    f2  = _card(raw, offset + 1, fixed=True, n=4, w=10)
    cmo = to_float(f2[0]) if f2 else 0.0
    con1 = to_int(f2[1]) if len(f2) > 1 else 0
    con2 = to_int(f2[2]) if len(f2) > 2 else 0
    state.mat_rigid[mid] = MatRigid(mid, title, rho, E, nu, cmo, con1, con2)


def handle_mat_null(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card: mid ro pc mu terod cerod ym pr — the Young's modulus / Poisson ratio
    # used for the (shell) contact stiffness sit in fields 7-8, NOT 3-4 (those
    # are the pressure cutoff and viscosity).
    f1  = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0])
    rho = to_float(f1[1])
    E   = to_float(f1[6]) if len(f1) > 6 else 0.0
    nu  = to_float(f1[7]) if len(f1) > 7 else 0.0
    state.mat_null[mid] = MatNull(mid, title, rho, E, nu)


# ─────────────────────────────────────────────────────────────────────────────
# High explosive + equations of state (coupled ALE / JWL detonation)
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_high_explosive_burn(block: Block, state: ConversionState) -> None:
    """*MAT_HIGH_EXPLOSIVE_BURN (MAT_008) → half of /MAT/LAW5 (JWL).

    Card: mid ro d pcj beta k g sigy.  Merged at write time with the *EOS_JWL of
    the same id (which supplies A,B,R1,R2,omega,E0) into one /MAT/LAW5.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        return
    mid = to_int(f[0])
    state.mat_high_explosive[mid] = MatHighExplosiveBurn(
        mid=mid, title=title,
        rho=to_float(f[1]) if len(f) > 1 else 0.0,
        d=to_float(f[2])   if len(f) > 2 else 0.0,
        pcj=to_float(f[3]) if len(f) > 3 else 0.0,
        beta=to_float(f[4]) if len(f) > 4 else 0.0,
    )


def handle_eos_jwl(block: Block, state: ConversionState) -> None:
    """*EOS_JWL (EOS_002) → the JWL parameters of /MAT/LAW5.

    Card 1: eosid a b r1 r2 omeg e0 vo.  Stored by eosid; folded into the LAW5
    of the same id (its companion *MAT_HIGH_EXPLOSIVE_BURN).
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        return
    eosid = to_int(f[0])
    state.eos_jwl[eosid] = EosJwl(
        eosid=eosid,
        a=to_float(f[1])     if len(f) > 1 else 0.0,
        b=to_float(f[2])     if len(f) > 2 else 0.0,
        r1=to_float(f[3])    if len(f) > 3 else 0.0,
        r2=to_float(f[4])    if len(f) > 4 else 0.0,
        omega=to_float(f[5]) if len(f) > 5 else 0.0,
        e0=to_float(f[6])    if len(f) > 6 else 0.0,
        vo=to_float(f[7], 1.0) if len(f) > 7 else 1.0,
    )


def handle_eos_linear_polynomial(block: Block, state: ConversionState) -> None:
    """*EOS_LINEAR_POLYNOMIAL (EOS_001) → /EOS/POLYNOMIAL.

    Card 1: eosid c0 c1 c2 c3 c4 c5 c6
    Card 2: e0 v0        (c6 has no Radioss term and is dropped)
    """
    offset = _title_offset(block)
    raw = block.raw
    f = _card(raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        return
    eosid = to_int(f[0])
    g = lambda i: to_float(f[i]) if len(f) > i else 0.0
    c6 = g(7)
    if c6 != 0.0:
        state.warn(f"*EOS_LINEAR_POLYNOMIAL {eosid}: C6={c6:g} (the C6·μ²·E "
                   "term) has no /EOS/POLYNOMIAL equivalent — Radioss's "
                   "polynomial energy coefficients stop at C5·μ·E — so C6 is "
                   "dropped.")
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    e0 = to_float(f2[0]) if f2 else 0.0
    v0 = to_float(f2[1], 1.0) if len(f2) > 1 else 1.0
    if v0 not in (0.0, 1.0):
        state.warn(f"*EOS_LINEAR_POLYNOMIAL {eosid}: V0={v0} (initial relative "
                   "volume) has no /EOS/POLYNOMIAL field — Radioss references E0 "
                   "to the initial volume; verify the initial state.")
    state.eos_cards[eosid] = EosCard(
        eosid=eosid, kind="POLYNOMIAL",
        params={"c0": g(1), "c1": g(2), "c2": g(3), "c3": g(4),
                "c4": g(5), "c5": g(6), "e0": e0, "psh": 0.0, "rho0": 0.0})


def handle_eos_gruneisen(block: Block, state: ConversionState) -> None:
    """*EOS_GRUNEISEN (EOS_004) → /EOS/GRUNEISEN.

    Card 1: eosid c s1 s2 s3 gamao a e0   (LS-DYNA GAMAO -> Radioss Y0).
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        return
    eosid = to_int(f[0])
    g = lambda i: to_float(f[i]) if len(f) > i else 0.0
    state.eos_cards[eosid] = EosCard(
        eosid=eosid, kind="GRUNEISEN",
        params={"c": g(1), "s1": g(2), "s2": g(3), "s3": g(4),
                "y0": g(5), "a": g(6), "e0": g(7), "rho0": 0.0})


def handle_eos_ideal_gas(block: Block, state: ConversionState) -> None:
    """*EOS_IDEAL_GAS → /EOS/IDEAL-GAS.

    LS-DYNA parameterises the ideal gas by specific heats (Card 1:
    eosid cv0 cp0 c1 c2 t0 v0); Radioss wants the ratio gamma = Cp/Cv. The
    conversion is the one genuine EOS unit-aware map, so it is warned.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        return
    eosid = to_int(f[0])
    cv0 = to_float(f[1]) if len(f) > 1 else 0.0
    cp0 = to_float(f[2]) if len(f) > 2 else 0.0
    t0  = to_float(f[5]) if len(f) > 5 else 0.0
    if cv0 > 0.0 and cp0 > 0.0:
        gamma = cp0 / cv0
    else:
        gamma = 1.4
        state.warn(f"*EOS_IDEAL_GAS {eosid}: Cv/Cp not both given — defaulted "
                   "gamma=1.4 for /EOS/IDEAL-GAS; set the heat-capacity ratio "
                   "explicitly if the gas is not diatomic.")
    state.eos_cards[eosid] = EosCard(
        eosid=eosid, kind="IDEAL-GAS",
        # cv/cp/t0 are kept so the writer can compute the initial pressure
        # P0 = rho*(cp-cv)*t0 (Radioss requires P0 > 0) once the carrier
        # material's density is known.
        params={"gamma": gamma, "p0": 0.0, "psh": 0.0, "t0": t0, "rho0": 0.0,
                "cv": cv0, "cp": cp0},
        note="gamma = Cp/Cv")


def handle_initial_detonation(block: Block, state: ConversionState) -> None:
    """*INITIAL_DETONATION → /DFS/DETPOINT (JWL lighting point/time).

    Card: pid x y z lt.  pid = explosive part (0 = all); the writer resolves
    part -> LAW5 material id.
    """
    offset = _title_offset(block)
    for i in range(offset, len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=8, w=10)
        if not f:
            continue
        state.detonations.append(InitialDetonation(
            pid=to_int(f[0]),
            x=to_float(f[1]) if len(f) > 1 else 0.0,
            y=to_float(f[2]) if len(f) > 2 else 0.0,
            z=to_float(f[3]) if len(f) > 3 else 0.0,
            lt=to_float(f[4]) if len(f) > 4 else 0.0,
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Coupled ALE mechanics / fluid-structure coupling / boundaries
# ─────────────────────────────────────────────────────────────────────────────

def handle_ale_multi_material_group(block: Block, state: ConversionState) -> None:
    """*ALE_MULTI-MATERIAL_GROUP → the submaterial order of a /MAT/LAW51.

    Each data card is `sid idtype` (idtype 0 = part-set, 1 = part). The card
    order is the AMMG/phase index. Collected into one AleMultiMaterialGroup.
    """
    offset = _title_offset(block)
    mmg = AleMultiMaterialGroup()
    for i in range(offset, len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=8, w=10)
        if not f or f[0].strip() == "":
            continue
        sid = to_int(f[0])
        idtype = to_int(f[1]) if len(f) > 1 else 1
        if sid > 0:
            mmg.entries.append((sid, idtype))
    if mmg.entries:
        state.ale_mmgs.append(mmg)


def handle_constrained_lagrange_in_solid(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_LAGRANGE_IN_SOLID → /INTER/TYPE18 (fluid-structure coupling).

    Card 1: slave master sstyp mstyp nquad ctype direc mcoup
    Card 2: start end pfac fric ...   (penalty stiffness scale, times)
    slave = Lagrangian structure set, master = ALE fluid set.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if len(f1) < 2:
        return
    ctype = to_int(f1[5]) if len(f1) > 5 else 4
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    start = to_float(f2[0]) if f2 else 0.0
    end   = to_float(f2[1]) if len(f2) > 1 else 0.0
    pfac  = to_float(f2[2]) if len(f2) > 2 else 0.1
    state.lagrange_in_solid.append(ConstrainedLagrangeInSolid(
        slave=to_int(f1[0]), master=to_int(f1[1]),
        sstyp=to_int(f1[2]) if len(f1) > 2 else 0,
        mstyp=to_int(f1[3]) if len(f1) > 3 else 0,
        ctype=ctype, pfac=pfac if pfac > 0 else 0.1, start=start, end=end))


def handle_initial_volume_fraction_geometry(block: Block, state: ConversionState) -> None:
    """*INITIAL_VOLUME_FRACTION_GEOMETRY → /INIVOL initial ALE fill.

    Header card: fmsid fmidtyp bammg ntrace
    Container cards: conttyp fillopt fammg ...  (geometry follows)
    Only the ALE part (fmsid) and the fill phase/opt are captured — the geometric
    container is emitted as a /SURF/PLANE where possible (writer), otherwise
    warned. A first-pass, plane-container mapping.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or f1[0].strip() == "":
        return
    part = to_int(f1[0])
    vf = InitialVolumeFraction(part=part)
    # Each subsequent non-blank card starts a container: conttyp fillopt fammg
    for i in range(offset + 1, len(raw)):
        if not raw[i].strip():
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 3:
            continue
        fillopt = to_int(f[1])
        fammg   = to_int(f[2])
        vf.fills.append((0, fammg, fillopt))     # surf_ID resolved/synth at write
    if vf.fills:
        state.volume_fractions.append(vf)


def handle_boundary_non_reflecting(block: Block, state: ConversionState) -> None:
    """*BOUNDARY_NON_REFLECTING → /EBCS/NRF on the named segment set.

    Card: nsid ad as.  nsid = the *SET_SEGMENT acting as a silent frontier.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        return
    state.non_reflecting.append(BoundaryNonReflecting(nsid=to_int(f[0])))


def handle_control_ale(block: Block, state: ConversionState) -> None:
    """*CONTROL_ALE → ALE advection hints (mostly informational).

    Card 1: dct nadv meth afac bfac cfac dfac efac.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f:
        return
    state.control_ale = ControlAle(
        meth=to_int(f[2]) if len(f) > 2 else 1,
        afac=to_float(f[3]) if len(f) > 3 else 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Definitions
# ─────────────────────────────────────────────────────────────────────────────

def handle_define_curve(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Header card: lcid sidr sfa sfo offa offo dattyp lcint
    f1   = _card(raw, offset, fixed=True, n=8, w=10)
    lcid = to_int(f1[0])
    sfa  = to_float(f1[2]) if len(f1) > 2 else 1.0
    sfo  = to_float(f1[3]) if len(f1) > 3 else 1.0
    offa = to_float(f1[4]) if len(f1) > 4 else 0.0
    offo = to_float(f1[5]) if len(f1) > 5 else 0.0
    pts: list = []
    # LS-DYNA R16: "Abscissa value = SFA·(Defined value + OFFA)" — the offset is
    # applied BEFORE the scale factor (same for SFO/OFFO on the ordinate).
    for line in raw[offset + 1:]:
        f = parse_free(line)
        if len(f) >= 2:
            pts.append(((to_float(f[0]) + offa) * (sfa or 1.0),
                        (to_float(f[1]) + offo) * (sfo or 1.0)))
    state.curves[lcid] = Curve(lcid, title, sfa, sfo, offa, offo, pts)
    state.curve_order.append(lcid)


def _handle_define_table_common(block: Block, state: ConversionState,
                                is_2d: bool) -> None:
    """Shared parser for *DEFINE_TABLE / *DEFINE_TABLE_2D → /TABLE/1 (Ndim=2).

    Header card (Keyword971_R6.1 define_table[_2D].cfg): TBID SFA OFFA — the
    table header has NO ordinate scale/offset (SFO/OFFO exist only on
    *DEFINE_CURVE). Rows: VALUE LCID (the _2D form, 20-char fields) or bare
    VALUE (legacy form; the curves are the *DEFINE_CURVE blocks immediately
    following the table, resolved positionally by the writer post-pass).
    A = SFA·(VALUE + OFFA), the same convention as *DEFINE_CURVE abscissas.
    """
    kw = "*DEFINE_TABLE_2D" if is_2d else "*DEFINE_TABLE"
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        return
    tbid = to_int(f1[0])
    sfa  = _ffield(f1, 1, 1.0)
    if sfa == 0.0:
        sfa = 1.0
    offa = to_float(f1[2]) if len(f1) > 2 else 0.0
    rows: List = []          # (A, lcid) — explicit-LCID rows
    pending: List = []       # bare VALUE rows (legacy positional form)
    for line in raw[offset + 1:]:
        f = parse_free(line)
        if not f:
            continue
        val = (to_float(f[0]) + offa) * sfa
        lcid = to_int(f[1]) if len(f) > 1 else 0
        if lcid > 0:
            rows.append((val, lcid))
        else:
            pending.append(val)
    if rows and pending:
        state.warn(
            f"{kw} tbid={tbid}: mixes rows with and without an explicit LCID "
            "— skipped (cannot pair the bare values with curves).")
        state.skipped_keywords.append(block.keyword)
        return
    if is_2d and pending:
        state.warn(
            f"{kw} tbid={tbid}: {len(pending)} row(s) without the required "
            "LCID field — skipped.")
        state.skipped_keywords.append(block.keyword)
        return
    if not rows and not pending:
        state.warn(f"{kw} tbid={tbid}: no data rows — skipped.")
        state.skipped_keywords.append(block.keyword)
        return
    state.define_tables[tbid] = DefineTable(
        tbid=tbid, title=title, sfa=sfa, offa=offa,
        rows=rows, pending_values=pending,
        curve_seq=len(state.curve_order), resolved=bool(rows))


def handle_define_table(block: Block, state: ConversionState) -> None:
    _handle_define_table_common(block, state, is_2d=False)


def handle_define_table_2d(block: Block, state: ConversionState) -> None:
    _handle_define_table_common(block, state, is_2d=True)


# Whitelisted names for the *DEFINE_CURVE_FUNCTION expression sampler. Only a
# pure single-variable arithmetic/trig expression can be sampled into a /FUNCT;
# anything referencing parameters, other curves (LC(...)), or runtime state is
# left to the warn-and-skip path.
_FUNC_EXPR_FUNCS = {
    "sin": _math.sin, "cos": _math.cos, "tan": _math.tan,
    "asin": _math.asin, "acos": _math.acos, "atan": _math.atan,
    "sinh": _math.sinh, "cosh": _math.cosh, "tanh": _math.tanh,
    "exp": _math.exp, "log": _math.log, "log10": _math.log10,
    "sqrt": _math.sqrt, "abs": abs, "min": min, "max": max, "pow": pow,
    "atan2": _math.atan2, "floor": _math.floor, "ceil": _math.ceil,
}
_FUNC_EXPR_CONSTS = {"pi": _math.pi, "PI": _math.pi, "e": _math.e}
_FUNC_EXPR_VARS = {"x", "X", "t", "T", "time", "TIME"}
_FUNC_EXPR_OK_NODES = (
    _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Call, _ast.Name, _ast.Load,
    _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.Pow, _ast.Mod, _ast.USub,
    _ast.UAdd, _ast.Constant,
)


def _sample_curve_function(expr: str, tmax: float, npts: int = 101):
    """Sample a pure single-variable expression into [(x, f(x))] points over
    [0, tmax], or return None if the expression is not a safe single-variable
    arithmetic/trig function (references parameters, curves, or other state)."""
    try:
        tree = _ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    varname = None
    for node in _ast.walk(tree):
        if not isinstance(node, _FUNC_EXPR_OK_NODES):
            return None
        if isinstance(node, _ast.Call):
            if not (isinstance(node.func, _ast.Name)
                    and node.func.id in _FUNC_EXPR_FUNCS):
                return None
        if isinstance(node, _ast.Name):
            nm = node.id
            if nm in _FUNC_EXPR_FUNCS or nm in _FUNC_EXPR_CONSTS:
                continue
            if nm in _FUNC_EXPR_VARS:
                if varname is not None and nm != varname:
                    return None            # more than one distinct variable
                varname = nm
            else:
                return None                # unknown identifier (param/curve/…)
    if varname is None:
        return None                        # constant expression — not a curve
    code = compile(tree, "<curve_function>", "eval")
    env = {"__builtins__": {}}
    env.update(_FUNC_EXPR_FUNCS)
    env.update(_FUNC_EXPR_CONSTS)
    tmax = tmax if tmax and tmax > 0.0 else 1.0
    pts = []
    for i in range(npts):
        xv = tmax * i / (npts - 1)
        env[varname] = xv
        try:
            yv = float(eval(code, env))    # noqa: S307 — AST-whitelisted above
        except (ValueError, ZeroDivisionError, OverflowError):
            yv = 0.0
        pts.append((xv, yv))
    return pts


def handle_define_curve_function(block: Block, state: ConversionState) -> None:
    """*DEFINE_CURVE_FUNCTION → /FUNCT (sampled).

    Header card: lcid sidr sfa sfo offa offo dattyp lcint (same as *DEFINE_CURVE).
    The following card(s) hold an analytic expression string. OpenRadioss /FUNCT
    has no analytic form, so a pure single-variable expression (of x / time) is
    SAMPLED into an X-Y /FUNCT over [0, termination time]. Expressions that
    reference parameters, other curves (LC(id,x)), sensors, or runtime state
    cannot be sampled and are warned + skipped.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1:
        return
    lcid = to_int(f1[0])
    sfa  = to_float(f1[2]) if len(f1) > 2 else 1.0
    sfo  = to_float(f1[3]) if len(f1) > 3 else 1.0
    offa = to_float(f1[4]) if len(f1) > 4 else 0.0
    offo = to_float(f1[5]) if len(f1) > 5 else 0.0
    expr = " ".join(line.strip() for line in raw[offset + 1:] if line.strip())
    if not expr:
        state.warn(f"*DEFINE_CURVE_FUNCTION lcid={lcid}: empty expression — skipped.")
        state.skipped_keywords.append(block.keyword)
        return
    tmax = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    pts = _sample_curve_function(expr, tmax)
    if pts is None:
        state.warn(
            f"*DEFINE_CURVE_FUNCTION lcid={lcid}: expression {expr!r} is not a "
            "pure single-variable (x/time) arithmetic function — it references "
            "parameters, other curves, or runtime state that cannot be sampled "
            "into a /FUNCT — skipped. Replace it with an explicit *DEFINE_CURVE.")
        state.skipped_keywords.append(block.keyword)
        return
    pts = [((a + offa) * (sfa or 1.0), (o + offo) * (sfo or 1.0)) for a, o in pts]
    state.curves[lcid] = Curve(lcid, title, sfa, sfo, offa, offo, pts)
    state.warn(
        f"*DEFINE_CURVE_FUNCTION lcid={lcid}: analytic expression sampled into "
        f"a {len(pts)}-point /FUNCT over [0,{tmax:g}] — verify the range/"
        "resolution covers the intended use.")


def handle_define_coordinate_system(block: Block, state: ConversionState) -> None:
    raw = block.raw
    # Skip comment-only lines already stripped; data lines:
    # Card1: cid xo yo zo xl yl zl cidl
    # Card2: xp yp zp
    data = [line for line in raw if parse_free(line)]
    if not data:
        return
    f1 = parse_free(data[0])
    if not f1:
        return
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0
    cid = to_int(f1[0])
    xo, yo, zo = g1(1), g1(2), g1(3)
    xl, yl, zl = g1(4), g1(5), g1(6)
    xp = yp = zp = 0.0
    if len(data) > 1:
        f2 = parse_free(data[1])
        xp = to_float(f2[0]) if f2 else 0.0
        yp = to_float(f2[1]) if len(f2) > 1 else 0.0
        zp = to_float(f2[2]) if len(f2) > 2 else 0.0
    state.coord_sys[cid] = CoordSys(cid, xo, yo, zo, xl, yl, zl, xp, yp, zp)


def handle_define_coordinate_nodes(block: Block, state: ConversionState) -> None:
    """*DEFINE_COORDINATE_NODES → local system from three nodes.

    LS-DYNA card (R16 Vol I p.17-67):  cid n1 n2 n3 flag dir
      n1->n2 is the `dir` axis (default X); n3 fixes the in-plane direction;
      flag=1 updates the system every step (moving), flag=0 (default) is fixed.
    DIR is the only alphabetic field, so detect it wherever it lands. LS-PrePost
    writes FLAG and DIR in adjacent columns so they collapse into a single token
    when whitespace-split (e.g. "0X" = flag 0, dir X; "1Y" = flag 1, dir Y), so a
    trailing X/Y/Z letter on an otherwise-numeric token is peeled off as DIR.
    """
    data = [line for line in block.raw if parse_free(line)]
    if not data:
        return
    toks = parse_free(data[0])
    dir_ = "X"
    nums: List[str] = []
    for tok in toks:
        u = tok.strip().upper()
        if u in ("X", "Y", "Z"):
            dir_ = u
        elif len(u) >= 2 and u[-1] in ("X", "Y", "Z") and u[:-1].lstrip("+-").isdigit():
            nums.append(u[:-1])   # the FLAG value
            dir_ = u[-1]
        else:
            nums.append(tok)
    if len(nums) < 4:
        state.warn("*DEFINE_COORDINATE_NODES: incomplete card – skipped")
        return
    cid  = to_int(nums[0])
    n1   = to_int(nums[1])
    n2   = to_int(nums[2])
    n3   = to_int(nums[3])
    flag = to_int(nums[4]) if len(nums) > 4 else 0
    state.coord_nodes[cid] = CoordNodes(cid, n1, n2, n3, flag, dir_)


def handle_define_coordinate_vector(block: Block, state: ConversionState) -> None:
    """*DEFINE_COORDINATE_VECTOR → /SKEW/FIX (id = CID).

    Card (R16 Vol I p.17-74): CID XX YX ZX XV YV ZV NID
      (XX,YX,ZX) = a vector on the local x-axis; (XV,YV,ZV) = a vector in the
      local x-y plane; the starter forms z = X × V, y = z × X. NID (field 8) is
      an optional co-rotation node — dyna2rad ignores it (emits a fixed skew),
      so it is stored and warned in the writer.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*DEFINE_COORDINATE_VECTOR: empty card — skipped")
        return
    g = lambda i: to_float(f1[i]) if len(f1) > i and f1[i].strip() else 0.0
    cid = to_int(f1[0])
    xx, yx, zx = g(1), g(2), g(3)
    xv, yv, zv = g(4), g(5), g(6)
    nid = to_int(f1[7]) if len(f1) > 7 else 0
    state.coord_vectors[cid] = CoordVector(cid, xx, yx, zx, xv, yv, zv, nid, title)


def handle_define_vector(block: Block, state: ConversionState) -> None:
    """*DEFINE_VECTOR (value form) → /SKEW/FIX, *DEFINE_VECTOR_NODES → /SKEW/MOV.

    Value form card: VID XT YT ZT XH YH ZH CID (tail → head).
    _NODES card:     VID NODET NODEH (tail node → head node).
    The writer builds a skew whose local X' follows the tail→head direction.
    """
    is_nodes = "_NODES" in block.keyword
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn(f"*{block.keyword}: empty card — skipped")
        return
    vid = to_int(f1[0])
    if is_nodes:
        nodet = to_int(f1[1]) if len(f1) > 1 else 0
        nodeh = to_int(f1[2]) if len(f1) > 2 else 0
        state.define_vectors[vid] = DefineVector(
            vid, title, is_nodes=True, nodet=nodet, nodeh=nodeh)
    else:
        g = lambda i: to_float(f1[i]) if len(f1) > i and f1[i].strip() else 0.0
        xt, yt, zt = g(1), g(2), g(3)
        xh, yh, zh = g(4), g(5), g(6)
        cid = to_int(f1[7]) if len(f1) > 7 else 0
        state.define_vectors[vid] = DefineVector(
            vid, title, is_nodes=False, xt=xt, yt=yt, zt=zt,
            xh=xh, yh=yh, zh=zh, cid=cid)


def handle_define_sd_orientation(block: Block, state: ConversionState) -> None:
    """*DEFINE_SD_ORIENTATION → the orientation /SKEW of an oriented
    *ELEMENT_DISCRETE (its VID).

    Card (R16 Vol I p.17-372): VID IOP XT YT ZT NID1 NID2
      IOP=0: fixed direction (XT,YT,ZT) → /SKEW/FIX
      IOP=2: along NID1→NID2 (co-rotating) → /SKEW/MOV
      IOP=1/3: the spring's own node axis projected ⟂ to the vector/node pair —
        no OpenRadioss skew equivalent (unhandled by dyna2rad too), warned in
        the writer.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*DEFINE_SD_ORIENTATION: empty card — skipped")
        return
    vid = to_int(f1[0])
    iop = to_int(f1[1]) if len(f1) > 1 else -1
    xt = to_float(f1[2]) if len(f1) > 2 and f1[2].strip() else 0.0
    yt = to_float(f1[3]) if len(f1) > 3 and f1[3].strip() else 0.0
    zt = to_float(f1[4]) if len(f1) > 4 and f1[4].strip() else 0.0
    nid1 = to_int(f1[5]) if len(f1) > 5 else 0
    nid2 = to_int(f1[6]) if len(f1) > 6 else 0
    state.sd_orientations[vid] = SdOrientation(
        vid, iop, xt, yt, zt, nid1, nid2, title)


def handle_define_box(block: Block, state: ConversionState) -> None:
    """*DEFINE_BOX / *DEFINE_BOX_LOCAL → numeric node-membership scoping.

    Card 1 (both): BOXID XMN XMX YMN YMX ZMN ZMX.
    _LOCAL extra cards: (XX YX ZX XV YV ZV) local-x and in-plane vectors, then
    (CX CY CZ) the local-system origin — the extents on Card 1 are then in that
    local frame. (The _ADAPTIVE/_COARSEN/_DRAWBEAD/_SPH variants have their own
    normalized keywords and fall through to skipped_keywords, matching
    dyna2rad's silent drop.)
    """
    is_local = "_LOCAL" in block.keyword
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn(f"*{block.keyword}: empty card — skipped")
        return
    g = lambda f, i: to_float(f[i]) if len(f) > i and f[i].strip() else 0.0
    box_id = to_int(f1[0])
    box = DefineBox(box_id, title,
                    xmn=g(f1, 1), xmx=g(f1, 2),
                    ymn=g(f1, 3), ymx=g(f1, 4),
                    zmn=g(f1, 5), zmx=g(f1, 6),
                    local=is_local)
    if is_local:
        f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
        f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
        box.xx, box.yx, box.zx = g(f2, 0), g(f2, 1), g(f2, 2)
        box.xv, box.yv, box.zv = g(f2, 3), g(f2, 4), g(f2, 5)
        box.cx, box.cy, box.cz = g(f3, 0), g(f3, 1), g(f3, 2)
    state.boxes[box_id] = box


# ─────────────────────────────────────────────────────────────────────────────
# Sets
# ─────────────────────────────────────────────────────────────────────────────

def handle_set_node_list(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card: sid da1 da2 da3 da4 solver
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    nsid = to_int(f1[0])
    nids: List[int] = []
    for line in raw[offset + 1:]:
        for tok in parse_free(line):
            v = to_int(tok)
            if v > 0:
                nids.append(v)
    state.node_sets[nsid] = (title, nids)


def _handle_set_elem_list(block: Block, state: ConversionState, target: dict) -> None:
    """Shared parser for *SET_SHELL/_SOLID/_BEAM[_LIST]: header card ``sid da1..``
    then element ids 8 per card. Stored as sid → (title, [eids]); referenced by
    *DATABASE_CROSS_SECTION_SET (the /SECT element groups)."""
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        return
    sid = to_int(f1[0])
    eids: List[int] = []
    for line in raw[offset + 1:]:
        for tok in parse_free(line):
            v = to_int(tok)
            if v > 0:
                eids.append(v)
    target[sid] = (title, eids)


def handle_set_shell_list(block: Block, state: ConversionState) -> None:
    _handle_set_elem_list(block, state, state.shell_sets)


def handle_set_solid_list(block: Block, state: ConversionState) -> None:
    _handle_set_elem_list(block, state, state.solid_sets)


def handle_set_beam_list(block: Block, state: ConversionState) -> None:
    _handle_set_elem_list(block, state, state.beam_sets)


def handle_set_part_list(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    psid = to_int(f1[0])
    pids: List[int] = []
    for line in raw[offset + 1:]:
        for tok in parse_free(line):
            v = to_int(tok)
            if v > 0:
                pids.append(v)
    state.part_sets[psid] = (title, pids)


# ─────────────────────────────────────────────────────────────────────────────
# Boundary Conditions
# ─────────────────────────────────────────────────────────────────────────────

def _handle_boundary_spc(block: Block, state: ConversionState, use_nsid: bool) -> None:
    """Shared logic for *BOUNDARY_SPC_SET and *BOUNDARY_SPC_NODE."""
    raw = block.raw
    # For _ID variant, first line has numeric id (ignored; we derive from nsid)
    offset = 1 if _has_id(block) else 0
    i = offset
    bc_counter = len(state.bcs_spcs) + 1

    while i < len(raw):
        if not raw[i].strip():        # blank card placeholder → skip (no id-0 BC)
            i += 1
            continue
        # Card: nsid/nid cid dofx dofy dofz dofrx dofry dofrz
        f = _card(raw, i, fixed=True, n=8, w=10)
        nsid_or_nid = to_int(f[0])
        cid  = to_int(f[1])
        dofx = to_int(f[2])
        dofy = to_int(f[3])
        dofz = to_int(f[4])
        dofrx = to_int(f[5])
        dofry = to_int(f[6])
        dofrz = to_int(f[7])

        if use_nsid:
            nsid = nsid_or_nid
            # Next card is a SET_NODE_LIST title+data if embedded, but in
            # LS-DYNA the *SET_NODE_LIST_TITLE block is separate; here nsid
            # references an existing set from state.node_sets.
        else:
            # NODE variant: auto-create a single-node set
            nsid = state.next_id()
            state.node_sets[nsid] = ("", [nsid_or_nid])

        bc_id = bc_counter
        bc_counter += 1
        state.bcs_spcs.append(BcsSpc(bc_id, nsid, cid,
                                     dofx, dofy, dofz,
                                     dofrx, dofry, dofrz))
        i += 1


def handle_boundary_spc_set(block: Block, state: ConversionState) -> None:
    _handle_boundary_spc(block, state, use_nsid=True)


def handle_boundary_spc_node(block: Block, state: ConversionState) -> None:
    _handle_boundary_spc(block, state, use_nsid=False)


def handle_boundary_prescribed_motion_rigid(block: Block, state: ConversionState) -> None:
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 4:
            continue
        pid   = to_int(f[0])
        dof   = to_int(f[1])
        vad   = to_int(f[2])
        lcid  = to_int(f[3])
        sf    = _ffield(f, 4, 1.0)
        death = _ffield(f, 6, 1e28)
        birth = to_float(f[7]) if len(f) > 7 else 0.0
        state.prescribed_motions.append(
            PrescribedMotionRigid(pid, dof, vad, lcid, sf, death, birth)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Constraints
# ─────────────────────────────────────────────────────────────────────────────

def handle_constrained_nodal_rigid_body(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_NODAL_RIGID_BODY[_SPC] → /RBODY (+ /BCS for _SPC).

    LS-DYNA R16 Vol I (p.10-146..151):
      Card 1: PID CID NSID PNODE IPRT DRFLAG RRFLAG
      _SPC card (only with the _SPC option):
        CMO CON1 CON2 SPCNID XSPC YSPC ZSPC
        CMO>0 → CON1/CON2 are global translation/rotation codes (0-7);
        CMO<0 → CON1 is the local coordinate-system ID, CON2 a 6-digit local
        DOF code. Card-1 CID is the rigid body's (output/release) local system.

    The _INERTIA option (extra mass/inertia cards) is not parsed here; mass is
    instead taken from *ELEMENT_MASS_* on the part/master node (see writer).
    """
    raw = block.raw
    offset = _title_offset(block)          # title line for the _TITLE option
    is_spc = block.keyword.endswith("_SPC")
    # Card 1
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if len(f1) < 3:
        state.warn("*CONSTRAINED_NODAL_RIGID_BODY: incomplete Card 1 – skipped")
        return
    pid   = to_int(f1[0])
    cid   = to_int(f1[1])
    nsid  = to_int(f1[2])
    pnode = to_int(f1[3]) if len(f1) > 3 else 0
    drflag = to_int(f1[5]) if len(f1) > 5 else 0
    rrflag = to_int(f1[6]) if len(f1) > 6 else 0
    if nsid == 0:                          # NSID=0 → node set ID equals PID
        nsid = pid
    if drflag or rrflag:
        state.warn(
            f"*CONSTRAINED_NODAL_RIGID_BODY pid={pid}: DRFLAG={drflag}/RRFLAG="
            f"{rrflag} (per-node DOF releases) are not converted — the /RBODY ties "
            "all secondary-node DOFs. Model these releases manually if required."
        )
    title = _read_title(block) if offset else ""
    cnrb = ConstrainedNodalRigidBody(
        pid=pid, nsid=nsid, pnode=pnode, cid=cid, title=title,
    )
    if is_spc:
        # SPC card: CMO CON1 CON2 SPCNID XSPC YSPC ZSPC
        f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
        if f2:
            cnrb.has_spc = True
            cnrb.cmo    = to_float(f2[0]) if len(f2) > 0 else 0.0
            cnrb.con1   = to_int(f2[1])   if len(f2) > 1 else 0
            cnrb.con2   = to_int(f2[2])   if len(f2) > 2 else 0
            cnrb.spcnid = to_int(f2[3])   if len(f2) > 3 else 0
    state.cnrbs.append(cnrb)


# ─────────────────────────────────────────────────────────────────────────────
# Contacts
# ─────────────────────────────────────────────────────────────────────────────

def _parse_contact_header(block: Block):
    """Parse the optional *_ID header line, return (inter_id, title, data_offset)."""
    raw = block.raw
    if _has_id(block) and raw:
        f = parse_free(raw[0])
        inter_id = to_int(f[0]) if f else 0
        title = " ".join(f[1:]) if len(f) > 1 else ""
        return inter_id, title, 1
    # No _ID header: return 0 so the caller assigns state.next_id(). (An older
    # fallback derived the id from the block's line count — every contact of the
    # same card shape got the same id, and multi-contact decks died with starter
    # ERROR 117 "INTERFACE ID USED TWICE OR MORE".)
    return 0, "", 0


def _read_contact_ignore(raw: List[str], offset: int) -> int:
    """Read LS-DYNA optional Card E (Card 6): igap ignore dprfac dtstif ..."""
    f = _card(raw, offset + 5, fixed=True, n=8, w=10)
    return to_int(f[1]) if len(f) > 1 else 0


def _read_contact_soft(raw: List[str], offset: int) -> int:
    """Read LS-DYNA optional Card A field 1 = SOFT (soft-constraint formulation).

    Card A sits immediately after Card 3 (offset+3), consistent with
    _read_contact_ignore's assumption that Cards A/B/C are all present (it reads
    IGNORE from Card C at offset+5). dyna2rad routes *CONTACT_AUTOMATIC_GENERAL
    on this field: SOFT -7/-11/-19 are hand-entered sentinels selecting
    /INTER/TYPE7/TYPE11/TYPE19; any ordinary value (0/1/2/blank, or Card A
    absent) leaves SOFT=0 → the default single-surface routing.
    """
    f = _card(raw, offset + 3, fixed=True, n=8, w=10)
    return to_int(f[0]) if f and f[0].strip() else 0


def _warn_contact_box(state: ConversionState, keyword: str, inter_id: int,
                      f1: List[str]) -> None:
    """Warn (loudly) when a contact Card 1 carries SBOXID/MBOXID (fields 5/6).

    dyna2rad only maps box-restricted contact scoping for
    *CONTACT_FORCE_TRANSDUCER_PENALTY (via a Boolean-intersection /SET/GENERAL
    → /INTER/SUB); the general TYPE7/TYPE25 contact converters ignore it. k2rad
    resolves box membership only at the node level (initial velocities, rigid
    walls), which does not map cleanly onto a contact's slave/master *surface*,
    so the box is dropped and the contact uses the full surface — flagged here
    so the user can restrict the *SET manually if the scoping is load-bearing.
    """
    sboxid = to_int(f1[4]) if len(f1) > 4 else 0
    mboxid = to_int(f1[5]) if len(f1) > 5 else 0
    if sboxid or mboxid:
        state.warn(
            f"*{keyword} id={inter_id}: SBOXID/MBOXID box-restricted contact "
            f"scoping (sbox={sboxid}, mbox={mboxid}) is NOT converted — the "
            "contact uses the full slave/master surface. dyna2rad only maps box "
            "scoping for *CONTACT_FORCE_TRANSDUCER_PENALTY, and a box does not "
            "map cleanly onto a contact surface here; restrict the referenced "
            "*SET manually if the box scoping matters.")


def handle_contact_automatic_single_surface(block: Block, state: ConversionState) -> None:
    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    # Card1: ssid msid sstyp mstyp sboxid mboxid spr mpr
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    _warn_contact_box(state, block.keyword, inter_id, f1)
    # Card2: fs fd dc vc vdc penchk bt dt  (immediately after Card1)
    f3 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs = to_float(f3[0]) if f3 else 0.0
    fd = to_float(f3[1]) if len(f3) > 1 else 0.0
    bt = to_float(f3[6]) if len(f3) > 6 else 0.0
    dt = to_float(f3[7]) if len(f3) > 7 else 1e28
    vdc = to_float(f3[4]) if len(f3) > 4 else 0.0
    # Card3: sfs sfm sst mst sfst sfmt fsf vsf — sfs (slave penalty stiffness
    # scale) → /INTER/TYPE7 Stfac; sst/mst (optional contact thickness per side,
    # SAST/SBST in newer manuals) → /INTER/TYPE7 Gapmin.
    f4 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sfs = to_float(f4[0]) if f4 else 0.0
    sst = to_float(f4[2]) if len(f4) > 2 else 0.0
    mst = to_float(f4[3]) if len(f4) > 3 else 0.0
    ignore = _read_contact_ignore(raw, offset)
    state.contacts_single.append(
        ContactAutoSingle(inter_id, title, ssid, sstyp, fs, fd, bt, dt, ignore,
                          vdc=vdc, sst=sst, mst=mst, sfs=sfs,
                          keyword=block.keyword)
    )


def handle_contact_automatic_general(block: Block, state: ConversionState) -> None:
    """*CONTACT_AUTOMATIC_GENERAL — dyna2rad SOFT-sentinel routing.

    The optional-Card-A SOFT field selects the OpenRadioss interface
    (``convertcontacts.cxx`` cc:133-164):

      * SOFT == -7  → /INTER/TYPE7  (penalty node→surface self-contact)
      * SOFT == -11 → /INTER/TYPE11 (edge-to-edge / line self-contact)
      * SOFT == -19 → /INTER/TYPE19 (combined surface + edge self-contact)
      * any other value (0/1/2/blank, or Card A absent) → the ordinary
        single-surface path (unchanged: /INTER/TYPE25 explicit, /INTER/TYPE7
        implicit). These -7/-11/-19 values are a dyna2rad-only sentinel
        convention (nothing in LS-DYNA writes them) — the user hand-enters SOFT
        to request the edge/line interface, exactly as dyna2rad expects.

    For a sentinel-routed contact with MSID==0 the interface is self-contact and
    the writer mirrors SSID onto the main side (dyna2rad cc:139-163).
    """
    inter_id, title, offset = _parse_contact_header(block)
    raw = block.raw
    soft = _read_contact_soft(raw, offset)
    if soft not in (-7, -11, -19):
        # Ordinary AUTOMATIC_GENERAL → the validated single-surface routing,
        # byte-for-byte unchanged (no regression on the default case).
        handle_contact_automatic_single_surface(block, state)
        return

    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    # Card1: ssid msid sstyp mstyp sboxid mboxid spr mpr
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    msid  = to_int(f1[1]) if len(f1) > 1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    mstyp = to_int(f1[3]) if len(f1) > 3 else 0
    _warn_contact_box(state, block.keyword, inter_id, f1)
    # Card2: fs fd dc vc vdc penchk bt dt
    f3 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs = to_float(f3[0]) if f3 else 0.0
    fd = to_float(f3[1]) if len(f3) > 1 else 0.0
    bt = to_float(f3[6]) if len(f3) > 6 else 0.0
    dt = to_float(f3[7]) if len(f3) > 7 else 1e28
    vdc = to_float(f3[4]) if len(f3) > 4 else 0.0
    # Card3: sfs sfm sst mst sfst sfmt fsf vsf
    f4 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sfs = to_float(f4[0]) if f4 else 0.0
    sst = to_float(f4[2]) if len(f4) > 2 else 0.0
    mst = to_float(f4[3]) if len(f4) > 3 else 0.0
    ignore = _read_contact_ignore(raw, offset)
    # Self-contact mirror: MSID==0 → main side = secondary side (dyna2rad cc:139-163).
    if msid == 0:
        msid, mstyp = ssid, sstyp
    state.contacts_general.append(
        ContactAutoGeneral(inter_id, title, ssid, sstyp, msid, mstyp, soft,
                           fs, fd, bt, dt, ignore, vdc=vdc, sst=sst, mst=mst, sfs=sfs)
    )


def handle_contact_automatic_surface_to_surface(block: Block, state: ConversionState) -> None:
    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    msid  = to_int(f1[1]) if len(f1) > 1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    mstyp = to_int(f1[3]) if len(f1) > 3 else 0
    _warn_contact_box(state, block.keyword, inter_id, f1)
    # Card2: fs fd dc vc vdc penchk bt dt
    f3 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs = to_float(f3[0]) if f3 else 0.0
    fd = to_float(f3[1]) if len(f3) > 1 else 0.0
    bt = to_float(f3[6]) if len(f3) > 6 else 0.0
    dt = to_float(f3[7]) if len(f3) > 7 else 1e28
    vdc = to_float(f3[4]) if len(f3) > 4 else 0.0
    # Card3: sfs sfm sst mst sfst sfmt fsf vsf — sfs (slave penalty stiffness
    # scale) → /INTER/TYPE7 Stfac; sst/mst → /INTER/TYPE7 Gapmin.
    f4 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sfs = to_float(f4[0]) if f4 else 0.0
    sst = to_float(f4[2]) if len(f4) > 2 else 0.0
    mst = to_float(f4[3]) if len(f4) > 3 else 0.0
    ignore = _read_contact_ignore(raw, offset)
    state.contacts_surf2surf.append(
        ContactAutoSurf2Surf(inter_id, title, ssid, sstyp, msid, mstyp, fs, fd, bt, dt, ignore,
                             vdc=vdc, sst=sst, mst=mst, sfs=sfs,
                             keyword=block.keyword)
    )


def handle_contact_tiebreak(block: Block, state: ConversionState) -> None:
    """*CONTACT_..._TIEBREAK (SURFACE_TO_SURFACE / ONE_WAY_...) → /INTER/TYPE7.

    The base contact cards (Card1/2/3) are identical to a plain automatic
    surface-to-surface contact, so the post-failure sliding/friction behaviour
    converts faithfully via the /INTER/TYPE7 path. But the *tiebreak* itself —
    the pre-failure cohesive BOND and its stress-based release (OPTION, NFLS
    normal / SFLS shear failure stress, ERATEN/ERATES energy release) — has no
    equivalent in an open-source OpenRadioss /INTER/TYPE7, so it is NOT
    represented: the parts will contact but not pre-bond. Warned explicitly.
    """
    state.warn(
        f"*{block.keyword}: converted to /INTER/TYPE7 (post-failure contact "
        "only). The cohesive TIEBREAK bond (NFLS/SFLS stress failure) has no "
        "open-source OpenRadioss equivalent and is DROPPED — the interface "
        "contacts but does not pre-bond. Model a bonded joint with a tied "
        "interface or a failing spring/connector if the pre-bond is required.")
    handle_contact_automatic_surface_to_surface(block, state)


def handle_contact_tied(block: Block, state: ConversionState) -> None:
    """*CONTACT_TIED_{NODES,SURFACE,SHELL_EDGE}_TO_SURFACE[_OFFSET…] →
    /INTER/TYPE2 (tied kinematic interface).

    Card1: ssid msid sstyp mstyp …  (slave commonly a *SET_NODE_LIST, sstyp=4;
           master commonly a *SET_SEGMENT, mstyp=0)
    Card2: fs fd dc vc vdc penchk bt dt — friction is meaningless on a tie and
           is not carried over.
    Card3: sfs sfm sst mst sfst sfmt — a NEGATIVE sst/mst is LS-DYNA's "absolute
           tie-criterion distance", kept as a floor for the TYPE2 dsearch. The
           dyna2rad discriminator (SFST*SST + SFMT*MST)/2 < 0 routes the contact
           to the penalty tie /INTER/TYPE10 instead of the kinematic /INTER/TYPE2
           (decided in the writer); sfs/sfm size the TYPE10 GAP.
    """
    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    msid  = to_int(f1[1]) if len(f1) > 1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    mstyp = to_int(f1[3]) if len(f1) > 3 else 0
    # Card3: sfs sfm sst mst sfst sfmt fsf vsf
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sfs  = to_float(f3[0]) if len(f3) > 0 else 0.0
    sfm  = to_float(f3[1]) if len(f3) > 1 else 0.0
    sst  = to_float(f3[2]) if len(f3) > 2 else 0.0
    mst  = to_float(f3[3]) if len(f3) > 3 else 0.0
    sfst = to_float(f3[4]) if len(f3) > 4 else 0.0
    sfmt = to_float(f3[5]) if len(f3) > 5 else 0.0

    kw = block.keyword                       # e.g. CONTACT_TIED_NODES_TO_SURFACE_OFFSET
    if "SHELL_EDGE" in kw:
        variant = "SHELL_EDGE_TO_SURFACE"
    elif "NODES" in kw:
        variant = "NODES_TO_SURFACE"
    else:
        variant = "SURFACE_TO_SURFACE"
    state.contacts_tied.append(
        ContactTied(inter_id, title, ssid, sstyp, msid, mstyp, variant,
                    offset=kw.endswith("OFFSET"), sst=sst, mst=mst,
                    sfs=sfs, sfm=sfm, sfst=sfst, sfmt=sfmt)
    )


def handle_contact_force_transducer(block: Block, state: ConversionState) -> None:
    """*CONTACT_FORCE_TRANSDUCER[_PENALTY] — measurement-only contact.

    Card1: surfa surfb surfatyp surfbtyp saboxid sbboxid sapr sbpr
    Mapped (in the writer) to a /INTER/SUB sub-interface so OpenRadioss reports
    the contact force already acting between these surfaces — it adds no stiffness.
    """
    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    surfa = to_int(f1[0]) if f1 else 0
    surfb = to_int(f1[1]) if len(f1) > 1 else 0
    satyp = to_int(f1[2]) if len(f1) > 2 else 0
    sbtyp = to_int(f1[3]) if len(f1) > 3 else 0
    # SABOXID/SBBOXID (fields 5/6) restrict the measured region to a *DEFINE_BOX.
    # dyna2rad DOES honour the box here (uniquely among contacts, via a Boolean
    # /SET/GENERAL → /INTER/SUB), but k2rad's node-level box membership does not
    # map onto a contact surface, so the box is dropped — warned loudly so the
    # reported force scope is not silently the full surface.
    saboxid = to_int(f1[4]) if len(f1) > 4 else 0
    sbboxid = to_int(f1[5]) if len(f1) > 5 else 0
    if saboxid or sbboxid:
        state.warn(
            f"*CONTACT_FORCE_TRANSDUCER id={inter_id}: SABOXID/SBBOXID box-"
            f"restricted measurement scope (sabox={saboxid}, sbbox={sbboxid}) is "
            "NOT converted — the /INTER/SUB reports the force over the FULL "
            "surface intersection, not the box-restricted region. dyna2rad maps "
            "this box (Boolean /SET/GENERAL); restrict the referenced *SET/*SURF "
            "manually if the box scope is load-bearing.")
    state.force_transducers.append(
        ContactForceTransducer(inter_id, title, surfa, surfb, satyp, sbtyp)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Control – Implicit
# ─────────────────────────────────────────────────────────────────────────────

def handle_control_implicit_general(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    # imflag dt0 imform nsbs igs cnstn form zero_v
    f = _card(raw, 0, fixed=True, n=8, w=10)
    imflag = to_int(f[0])
    dt0    = to_float(f[1])
    imform = to_int(f[2])
    nsbs   = to_int(f[3])
    if imflag != 0:
        state.is_implicit = True
    state.ctrl_implicit_gen = ControlImplicitGeneral(imflag, dt0, imform, nsbs)


def handle_control_implicit_solution(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    # nsolvr ilimit maxref dctol ectol rctol lstol abstol
    f = _card(raw, 0, fixed=True, n=8, w=10)
    nsolvr  = to_int(f[0])
    ilimit  = to_int(f[1])
    maxref  = to_int(f[2])
    dctol   = to_float(f[3])
    ectol   = to_float(f[4])
    rctol   = to_float(f[5]) if len(f) > 5 else 0.0
    # Card2: dnorm diverg istif nlprint nlnorm d3itctl cpchk
    f2 = _card(raw, 1, fixed=True, n=8, w=10)
    nlprint = to_int(f2[3]) if len(f2) > 3 else 0
    state.ctrl_implicit_sol = ControlImplicitSolution(
        nsolvr, ilimit, maxref, dctol, ectol, nlprint, rctol
    )


def handle_control_termination(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=6, w=10)
    state.ctrl_termination = ControlTermination(to_float(f[0]))


def handle_control_timestep(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    # Card: dtinit tssfac isdo tslimt dt2ms lctm erode ms1st
    #        f[0]   f[1]   f[2] f[3]   f[4]  f[5] f[6]  f[7]
    # TSLIMT (3) and ERODE (6) used to be sliced into f and then dropped on
    # the floor: a user who wrote ERODE=1 got a converted deck with no
    # deletion behaviour and no warning that the request had gone missing.
    f = _card(raw, 0, fixed=True, n=8, w=10)
    dt2ms = to_float(f[4]) if len(f) > 4 else 0.0
    tslimt = to_float(f[3]) if len(f) > 3 else 0.0
    erode = to_int(f[6]) if len(f) > 6 else 0
    state.ctrl_timestep = ControlTimestep(to_float(f[0]), to_float(f[1]),
                                          dt2ms, tslimt, erode)


def handle_boundary_prescribed_motion_set(block: Block, state: ConversionState) -> None:
    _handle_boundary_prescribed_motion(block, state, is_node=False)


def handle_boundary_prescribed_motion_node(block: Block, state: ConversionState) -> None:
    """*BOUNDARY_PRESCRIBED_MOTION_NODE — same card as _SET with a node id in
    field 1; wrapped in an auto-created single-node set and sent down the _SET
    path (→ /IMPDISP//IMPVEL//IMPACC, or /BCS when SF=0)."""
    _handle_boundary_prescribed_motion(block, state, is_node=True)


def _handle_boundary_prescribed_motion(block: Block, state: ConversionState,
                                       is_node: bool) -> None:
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 4:
            continue
        nsid  = to_int(f[0])
        dof   = to_int(f[1])
        vad   = to_int(f[2])
        lcid  = to_int(f[3])
        sf    = _ffield(f, 4, 1.0)
        death = _ffield(f, 6, 1e28)
        birth = to_float(f[7]) if len(f) > 7 else 0.0
        if is_node:
            nid = nsid
            nsid = state.next_id()
            state.node_sets[nsid] = (f"PM_node_{nid}", [nid])
        state.prescribed_motion_sets.append(
            PrescribedMotionSet(nsid, dof, vad, lcid, sf, death, birth)
        )


def handle_control_accuracy(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=4, w=10)
    osu  = to_int(f[0])
    inn  = to_int(f[1]) if len(f) > 1 else 0
    iacc = to_int(f[3]) if len(f) > 3 else 0
    state.ctrl_accuracy = ControlAccuracy(osu, inn, iacc)


def handle_control_contact(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    slsfac = to_float(f[0]) if f else 0.1
    rwpnal = to_float(f[1]) if len(f) > 1 else 0.0
    islchk = to_int(f[2])   if len(f) > 2 else 1
    shlthk = to_int(f[3])   if len(f) > 3 else 0
    penopt = to_int(f[4])   if len(f) > 4 else 1
    thkchk = to_int(f[5])   if len(f) > 5 else 0
    state.ctrl_contact = ControlContact(slsfac, rwpnal, islchk, shlthk, penopt, thkchk)


def handle_control_cpu(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=4, w=10)
    cputim = to_float(f[0]) if f else 0.0
    if cputim > 0.0:
        state.ctrl_cpu = ControlCpu(cputim)


def handle_control_energy(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=4, w=10)
    hgen   = to_int(f[0]) if f else 1
    rwen   = to_int(f[1]) if len(f) > 1 else 1
    slnten = to_int(f[2]) if len(f) > 2 else 0
    rylen  = to_int(f[3]) if len(f) > 3 else 0
    state.ctrl_energy = ControlEnergy(hgen, rwen, slnten, rylen)


def handle_control_hourglass(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=2, w=10)
    ihq = to_int(f[0])   if f else 1
    qh  = to_float(f[1]) if len(f) > 1 else 0.1
    state.ctrl_hourglass = ControlHourglass(ihq, qh)


def handle_hourglass(block: Block, state: ConversionState) -> None:
    """*HOURGLASS: HGID IHQ QM [IBQ Q1 Q2 QB|VDC QW]. Only HGID/IHQ/QM are
    consumed (dyna2rad reads exactly these; the bulk-viscosity and shell
    coefficients are dropped). QM defaults to 0.10 when blank; IHQ to 0 (the
    cfg default — the unmapped formulations 0/8/9/10 keep the section's
    ELFORM-derived Isolid, warned at property-emit time)."""
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    hgid = to_int(f[0]) if f else 0
    if hgid <= 0:
        state.warn("*HOURGLASS: card with no HGID – skipped")
        return
    ihq = to_int(f[1]) if len(f) > 1 else 0
    # A genuinely blank QM field means "LS-DYNA default 0.10"; an explicit 0.0
    # is kept as 0.0 (Radioss then applies its own h default for Isolid 1/2).
    qm = to_float(f[2]) if (len(f) > 2 and f[2].strip()) else 0.10
    state.hourglass_defs[hgid] = HourglassDef(hgid, ihq, qm)


def handle_control_implicit_auto(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    iauto  = to_int(f[0])   if f else 0
    iteopt = to_int(f[1])   if len(f) > 1 else 11
    itewin = to_int(f[2])   if len(f) > 2 else 5
    dtmin  = to_float(f[3]) if len(f) > 3 else 0.0
    dtmax  = to_float(f[4]) if len(f) > 4 else 0.0
    kfail  = to_int(f[6])   if len(f) > 6 else 0
    state.ctrl_implicit_auto = ControlImplicitAuto(iauto, iteopt, itewin, dtmin, dtmax, kfail)


def handle_control_implicit_eigenvalue(block: Block, state: ConversionState) -> None:
    """*CONTROL_IMPLICIT_EIGENVALUE → /EIG normal-modes (modal) analysis.

    Card-1: neig center lflag lftend rflag rhtend eigmth shfscl
      neig   = number of eigenmodes (→ /EIG Nmod). Negative neig (shift-based
               count) is taken as |neig|.
      lflag/lftend, rflag/rhtend = lower/upper eigenvalue-window bounds. LS-DYNA
               uses ±1e29 sentinels for "no bound"; only a flagged, finite,
               positive bound is forwarded to /EIG Freqmin/Cutfreq.
    Sets state.is_modal (engine switches to /IMPL/LINEAR) and is_implicit (modal
    IS an implicit analysis — keeps the implicit element formulations).
    """
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    neig   = to_int(f[0])   if f else 0
    lflag  = to_int(f[2])   if len(f) > 2 else 0
    lftend = to_float(f[3]) if len(f) > 3 else 0.0
    rflag  = to_int(f[4])   if len(f) > 4 else 0
    rhtend = to_float(f[5]) if len(f) > 5 else 0.0
    freqmin = lftend if (lflag != 0 and 0.0 < lftend < 1e28) else 0.0
    cutfreq = rhtend if (rflag != 0 and 0.0 < rhtend < 1e28) else 0.0
    state.ctrl_implicit_eig = ControlImplicitEigenvalue(
        neig=abs(neig), freqmin=freqmin, cutfreq=cutfreq
    )
    state.is_modal = True
    state.is_implicit = True


def handle_control_implicit_dynamics(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=6, w=10)
    imass = to_int(f[0])   if f else 0
    gamma = to_float(f[1]) if len(f) > 1 else 0.5
    beta  = to_float(f[2]) if len(f) > 2 else 0.25
    alpha = to_float(f[4]) if len(f) > 4 else 0.0
    state.ctrl_implicit_dyn = ControlImplicitDynamics(imass, gamma, beta, alpha)


def handle_control_output(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    npopt  = to_int(f[0]) if f else 0
    neecho = to_int(f[1]) if len(f) > 1 else 0
    state.ctrl_output = ControlOutput(npopt, neecho)


def handle_control_shell(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    wrpang = to_float(f[0]) if f else 20.0
    esort  = to_int(f[1])   if len(f) > 1 else 0
    irnxx  = to_int(f[2])   if len(f) > 2 else -1
    istupd = to_int(f[3])   if len(f) > 3 else 0
    theory = to_int(f[4])   if len(f) > 4 else 2
    bwc    = to_int(f[5])   if len(f) > 5 else 2
    intgrd = to_int(f[7])   if len(f) > 7 else 0
    state.ctrl_shell = ControlShell(wrpang, esort, irnxx, istupd, theory, bwc, intgrd)


def handle_control_solid(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f = _card(raw, 0, fixed=True, n=8, w=10)
    esort   = to_int(f[0]) if f else 0
    fmatrix = to_int(f[1]) if len(f) > 1 else 0
    niptets = to_int(f[2]) if len(f) > 2 else 4
    state.ctrl_solid = ControlSolid(esort, fmatrix, niptets)


_DT_PARSE_SENTINEL = -1.2345678e-300


def _numeric_or_none(tok: str) -> Optional[float]:
    """``to_float`` that can tell "not a number" from "the number 0".

    ``to_float`` folds both onto its default, which is exactly what let an
    unreadable DT field become a silent 0.0 — indistinguishable from "this
    output was never requested".
    """
    if tok is None or not str(tok).strip():
        return None
    v = to_float(tok, default=_DT_PARSE_SENTINEL)
    return None if v == _DT_PARSE_SENTINEL else v


def _db_fields(line: str, n: int = 4) -> List[str]:
    """Field list for a ``*DATABASE_*`` card line, under the family's ONE rule.

    Shared by every ``*DATABASE_*`` handler so that DT and its neighbours
    (``NPLTC`` on ``*DATABASE_BINARY_D3PLOT``, for one) are always read out of
    the SAME reading of the line. Reading DT free-format and NPLTC fixed-width
    off one card is how two fields of the same line end up disagreeing about
    where the line's columns are.

    See :func:`_handle_db_dt` for why the rule is what it is.
    """
    if "," in line:                       # LS-DYNA: a comma means free format
        return parse_free(line)
    fields = parse_fixed(line, n=n, w=10)
    head = fields[0] if fields else ""
    if head.strip() and _numeric_or_none(head) is None:
        # not column-aligned after all — e.g. an 11+ column first field
        free = parse_free(line)
        if free and _numeric_or_none(free[0]) is not None:
            return free
    return fields


def _handle_db_dt(block: Block, state: "ConversionState | None" = None,
                  keyword: str = "*DATABASE_*") -> float:
    """Parse DT from the first field of a ``*DATABASE_*`` card.

    ONE policy for the whole family. The family used to disagree with itself:
    most handlers split free-format first, while ``*DATABASE_ELOUT``,
    ``*DATABASE_GLSTAT`` and ``*DATABASE_BINARY_D3PLOT`` sliced strict
    fixed-width ``w=10``. On the same deck the two readings return different
    numbers, and both failure modes are SILENT — the output is requested in
    the .k and then never written, or written at the wrong frequency.

    Neither reading is right on its own, which is why this is a rule and not a
    choice between them::

        line                    fixed w=10      free      correct
        '1.000000E-05'               0.0       1e-05      1e-05   <- 12 chars
        '     1.0E-05'               0.0       1e-05      1e-05   <- straddles
        '   1.0E-05'                1e-05      1e-05      1e-05
        '1.0E-05,0,0'                0.0       1e-05      1e-05
        '          1.0E-05'          0.0       1e-05        0.0   <- DT blank

    ``1.000000E-05`` is simply how 1e-5 is normally written and it does not
    fit a 10-column field, so fixed slicing truncates it to ``'1.000000E-'``
    and ``to_float`` defaults that to 0.0. The last row is the opposite trap:
    DT is genuinely BLANK there (output driven by LCDT in field 2), and a
    free-format split cheerfully returns field 2's value as if it were DT.

    So: a comma means free format outright; otherwise read fixed columns and
    fall back to a free split ONLY when field 1 is non-empty but does not
    parse as a number — the signature of a line that is not really
    column-aligned. A blank field 1 stays 0.0, because that is what the deck
    says.

    Anything still unreadable is WARNED about rather than quietly defaulted,
    so a requested output can no longer vanish without trace.
    """
    raw = block.raw
    if not raw:
        return 0.0
    line = raw[0]
    fields = _db_fields(line)
    if not fields:
        return 0.0
    tok = fields[0]
    if not str(tok).strip():              # DT genuinely omitted
        return 0.0
    val = _numeric_or_none(tok)
    if val is None:
        if state is not None:
            state.warn(
                f"{keyword}: could not read the output interval DT from "
                f"{tok!r} (card line {line!r}). It is NOT being silently "
                "defaulted to 0.0 — the failure is reported so the missing "
                "output is visible; fix the field or the output will not be "
                "written at the interval the deck asks for."
            )
        return 0.0
    return val


def handle_database_abstat(block: Block, state: ConversionState) -> None:
    state.db_abstat_dt = _handle_db_dt(block, state, "*DATABASE_ABSTAT")


def handle_database_binary_d3thdt(block: Block, state: ConversionState) -> None:
    state.db_d3thdt_dt = _handle_db_dt(block, state, "*DATABASE_BINARY_D3THDT")


def handle_database_binary_intfor(block: Block, state: ConversionState) -> None:
    state.db_intfor_dt = _handle_db_dt(block, state, "*DATABASE_BINARY_INTFOR")


def handle_database_deforc(block: Block, state: ConversionState) -> None:
    state.db_deforc_dt = _handle_db_dt(block, state, "*DATABASE_DEFORC")


def handle_database_extent_binary(block: Block, state: ConversionState) -> None:
    raw = block.raw
    if not raw:
        return
    f1 = _card(raw, 0, fixed=True, n=8, w=10)
    strflg = to_int(f1[3]) if len(f1) > 3 else 0
    sigflg = to_int(f1[4]) if len(f1) > 4 else 1
    epsflg = to_int(f1[5]) if len(f1) > 5 else 1
    rltflg = to_int(f1[6]) if len(f1) > 6 else 1
    engflg = to_int(f1[7]) if len(f1) > 7 else 1
    # Card 2: cmpflg ieverp beamip dcomp shge stssz n3thdt
    f2   = _card(raw, 1, fixed=True, n=8, w=10)
    shge = to_int(f2[4]) if len(f2) > 4 else 0
    state.db_extent_binary = DbExtentBinary(strflg, sigflg, epsflg, rltflg, engflg, shge)


def handle_database_jntforc(block: Block, state: ConversionState) -> None:
    state.db_jntforc_dt = _handle_db_dt(block, state, "*DATABASE_JNTFORC")


def handle_database_matsum(block: Block, state: ConversionState) -> None:
    state.db_matsum_dt = _handle_db_dt(block, state, "*DATABASE_MATSUM")
    if state.db_matsum_dt:
        state.note_recognized_not_emitted(
            "DATABASE_MATSUM",
            "per-part energy/mass time history needs /TH/PART, which k2rad "
            "does not emit yet. The dt is honoured as the /TFILE frequency, "
            "but no per-part channel is written — global energy is still in "
            "the .out/T01, and per-part energy is unavailable.")


def handle_database_nodout(block: Block, state: ConversionState) -> None:
    state.db_nodout_dt = _handle_db_dt(block, state, "*DATABASE_NODOUT")
    if state.db_nodout_dt:
        state.note_recognized_not_emitted(
            "DATABASE_NODOUT",
            "no /TH/NODE block is emitted for it — k2rad writes /TH/NODE only "
            "for nodes a *DATABASE_HISTORY_NODE[_SET] names (or a reaction "
            "request). The dt is honoured as the /TFILE frequency. Add "
            "*DATABASE_HISTORY_NODE to choose the nodes to record.")


def handle_database_rcforc(block: Block, state: ConversionState) -> None:
    state.db_rcforc_dt = _handle_db_dt(block, state, "*DATABASE_RCFORC")


def handle_database_rwforc(block: Block, state: ConversionState) -> None:
    state.db_rwforc_dt = _handle_db_dt(block, state, "*DATABASE_RWFORC")


def handle_database_secforc(block: Block, state: ConversionState) -> None:
    state.db_secforc_dt = _handle_db_dt(block, state, "*DATABASE_SECFORC")


def handle_database_sleout(block: Block, state: ConversionState) -> None:
    state.db_sleout_dt = _handle_db_dt(block, state, "*DATABASE_SLEOUT")


def handle_database_binary_blstfor(block: Block, state: ConversionState) -> None:
    """*DATABASE_BINARY_BLSTFOR (blast pressure database) → /TH/SURF with the
    P (average external pressure) and A (loaded area) channels on each
    blast-loaded surface, plus engine /ANIM/NODA/PEXT (nodal blast-pressure
    fringe) and /ANIM/VECT/FEXT (external force vectors). /LOAD/PBLAST feeds
    all three (engine pblast_1.F). Card 1 field 1 is DT, as for D3PLOT."""
    state.db_blstfor_dt = _handle_db_dt(
        block, state, "*DATABASE_BINARY_BLSTFOR")


def handle_database_ncforc(block: Block, state: ConversionState) -> None:
    """*DATABASE_NCFORC (nodal contact forces) → /TH/INTER on every converted
    contact interface (T01 force resultants). The per-node view lives in the
    default animation vectors /ANIM/VECT/CONT + /ANIM/VECT/PCONT; OpenRadioss
    has no per-node contact-force time history."""
    state.db_ncforc_dt = _handle_db_dt(block, state, "*DATABASE_NCFORC")


def handle_database_spcforc(block: Block, state: ConversionState) -> None:
    """*DATABASE_SPCFORC (SPC reaction forces) → /TH/NODE with REACX/Y/Z
    (+REACXX/YY/ZZ) on the /BCS-constrained nodes + engine /ANIM/VECT/FREAC.
    The writer emits both; requesting either makes the OpenRadioss engine
    compute constraint reactions (engine reactions.F, COMPTREAC).

    The two carry different quantities: /ANIM/VECT/FREAC is the instantaneous
    reaction force, while the /TH/NODE REAC* channels are the time-accumulated
    reaction impulse (m*a*dt summed over the run) — the writer warns about it
    and writer/output.py:_make_starter_th_node_spc has the engine source
    lines."""
    state.db_spcforc_dt = _handle_db_dt(block, state, "*DATABASE_SPCFORC")


# ─────────────────────────────────────────────────────────────────────────────
# Initial stresses (*INITIAL_STRESS_SHELL / _SOLID) and cross sections
# ─────────────────────────────────────────────────────────────────────────────

def _ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def _fixed_float_card(raw: List[str], idx: int, n: int, w: int) -> List[float]:
    """Read one fixed-format card of *n* float fields of width *w* (with the
    usual free-format fallback via _card)."""
    f = _card(raw, idx, fixed=True, n=n, w=w)
    vals = [to_float(x) for x in f[:n]]
    vals += [0.0] * (n - len(vals))
    return vals


def _avg_tuples(pts: list) -> tuple:
    n = len(pts)
    return tuple(sum(p[k] for p in pts) / n for k in range(len(pts[0])))


def handle_initial_stress_shell(block: Block, state: ConversionState) -> None:
    """*INITIAL_STRESS_SHELL → /INISHE/STRS_F/GLOB (or /INISHE/STRS_F).

    Card 1 (Keyword971 initial_stress_shell_subobj.cfg):
        EID NPLANE NTHICK NHISV NTENSR LARGE NTHINT NTHHSV [ILOC]
    then NPLANE×NTHICK stress cards:
        small (LARGE=0): T SIGXX SIGYY SIGZZ SIGXY SIGYZ SIGZX EPS   (8×10)
        large (LARGE=1): T..SIGXY / SIGYZ SIGZX EPS                  (5+3×16)
    each followed by the NHISV history cards (8/card small, 5/card large) and
    NTENSR tensor cards (6/card small, 5/card large); NTHINT×NTHHSV thermal
    history cards close the element record (large format).

    The stress components are GLOBAL cartesian by default (ILOC=0) → the
    /INISHE/STRS_F/GLOB flavour, which carries the full tensor (incl. σzz), the
    plastic strain eps_p AND the thickness position pos_nip 1:1. ILOC=1 (local)
    → the local /INISHE/STRS_F flavour (σzz and T have no slot there; the
    writer warns). NHISV/NTENSR/thermal data have no /INISHE slot → dropped
    with one aggregated warning per block. NPLANE>1 in-plane points are
    averaged per through-thickness layer (the /INISHE per-layer format is
    replicated across the shell's in-plane Gauss points by the writer).
    """
    raw = block.raw
    i = 0
    n_hisv_dropped = 0
    n_tensr_dropped = 0
    n_thermal_dropped = 0
    n_plane_averaged = 0
    n_read = 0
    while i < len(raw):
        if not raw[i].strip():
            i += 1
            continue
        f = _card(raw, i, fixed=True, n=9, w=10)
        eid = to_int(f[0])
        if eid <= 0:
            i += 1
            continue
        nplane = max(1, to_int(f[1]))
        nthick = max(1, to_int(f[2]))
        nhisv  = to_int(f[3]) if len(f) > 3 else 0
        ntensr = to_int(f[4]) if len(f) > 4 else 0
        large  = to_int(f[5]) if len(f) > 5 else 0
        nthint = to_int(f[6]) if len(f) > 6 else 0
        nthhsv = to_int(f[7]) if len(f) > 7 else 0
        iloc   = to_int(f[8]) if len(f) > 8 else 0
        i += 1

        pts = []
        truncated = False
        for _ in range(nplane * nthick):
            if i >= len(raw):
                truncated = True
                break
            if large:
                a = _fixed_float_card(raw, i, 5, 16)
                b = _fixed_float_card(raw, i + 1, 3, 16) if i + 1 < len(raw) else [0.0] * 3
                i += 2
                pts.append(tuple(a + b))
            else:
                pts.append(tuple(_fixed_float_card(raw, i, 8, 10)))
                i += 1
            if nhisv > 0:
                i += _ceil_div(nhisv, 5 if large else 8)
            if ntensr > 0:
                i += _ceil_div(ntensr, 5 if large else 6)
        if nthint > 0 and nthhsv > 0:
            i += nthint * _ceil_div(nthhsv, 5 if large else 8)
            n_thermal_dropped += 1
        if truncated:
            state.warn(f"*INITIAL_STRESS_SHELL eid={eid}: block ends before all "
                       f"{nplane * nthick} integration-point cards — element skipped.")
            break
        if nhisv > 0:
            n_hisv_dropped += 1
        if ntensr > 0:
            n_tensr_dropped += 1

        # Collapse the NPLANE in-plane points into per-layer averages. Points
        # of one layer share the same T coordinate, so group by T (robust to
        # either loop order); fall back to consecutive-NPLANE chunking when the
        # distinct-T count does not match NTHICK (e.g. all-zero T columns).
        if nplane == 1:
            layers = pts
        else:
            n_plane_averaged += 1
            order: List[float] = []
            groups: dict = {}
            for p in pts:
                groups.setdefault(p[0], []).append(p)
                if len(groups[p[0]]) == 1:
                    order.append(p[0])
            if len(order) == nthick:
                layers = [_avg_tuples(groups[t]) for t in order]
            else:
                layers = [_avg_tuples(pts[k * nplane:(k + 1) * nplane])
                          for k in range(nthick)]
        state.ini_stress_shells.append(
            InitialStressShell(eid=eid, nplane=nplane, nthick=nthick,
                               iloc=iloc, layers=layers))
        n_read += 1

    if n_hisv_dropped:
        state.warn(f"*INITIAL_STRESS_SHELL: NHISV material history variables on "
                   f"{n_hisv_dropped} element(s) have no /INISHE slot — dropped "
                   "(plastic strain EPS itself IS mapped via eps_p).")
    if n_tensr_dropped:
        state.warn(f"*INITIAL_STRESS_SHELL: NTENSR tensor data on "
                   f"{n_tensr_dropped} element(s) has no /INISHE slot — dropped.")
    if n_thermal_dropped:
        state.warn(f"*INITIAL_STRESS_SHELL: thermal history (NTHINT/NTHHSV) on "
                   f"{n_thermal_dropped} element(s) has no /INISHE slot — dropped.")
    if n_plane_averaged:
        state.warn(f"*INITIAL_STRESS_SHELL: NPLANE>1 in-plane integration points "
                   f"on {n_plane_averaged} element(s) were AVERAGED per "
                   "through-thickness layer (the layer value is replicated "
                   "across the /INISHE in-plane Gauss points).")


def handle_initial_stress_solid(block: Block, state: ConversionState) -> None:
    """*INITIAL_STRESS_SOLID → /INIBRI/STRS_FGLO.

    Card 1 (Keyword971_R13.0 initial_stress_solid_subobj.cfg):
        EID NINT NHISV LARGE IVEFLG IALEGP NTHINT NTHHSV
    then NINT stress cards:
        small (LARGE=0): SIGXX SIGYY SIGZZ SIGXY SIGYZ SIGZX EPS  (7×10)
        large (LARGE=1): SIGXX..SIGYZ / SIGZX EPS HISV1-3         (5+5×16)
    NHISV(+IVEFLG) history values follow each stress card (8/card small; the
    first 3 ride the large card 2, then 5/card). LS-DYNA defines the solid
    stress components in the GLOBAL system → the global /INIBRI/STRS_FGLO
    flavour is emitted. History/thermal variables are dropped with one
    aggregated warning; EPS maps to /INIBRI's Epsilon_p.
    """
    raw = block.raw
    i = 0
    n_hisv_dropped = 0
    n_thermal_dropped = 0
    while i < len(raw):
        if not raw[i].strip():
            i += 1
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        eid = to_int(f[0])
        if eid <= 0:
            i += 1
            continue
        nint   = max(1, to_int(f[1]))
        nhisv  = to_int(f[2]) if len(f) > 2 else 0
        large  = to_int(f[3]) if len(f) > 3 else 0
        iveflg = to_int(f[4]) if len(f) > 4 else 0
        nthint = to_int(f[6]) if len(f) > 6 else 0
        nthhsv = to_int(f[7]) if len(f) > 7 else 0
        i += 1
        nh = nhisv + iveflg   # IVEFLG appends extra value(s) to the history list

        pts = []
        truncated = False
        for _ in range(nint):
            if i >= len(raw):
                truncated = True
                break
            if large:
                a = _fixed_float_card(raw, i, 5, 16)
                b = _fixed_float_card(raw, i + 1, 2, 16) if i + 1 < len(raw) else [0.0] * 2
                i += 2
                pts.append(tuple(a + b))
                if nh > 3:                    # 3 history values ride card 2
                    i += _ceil_div(nh - 3, 5)
            else:
                pts.append(tuple(_fixed_float_card(raw, i, 7, 10)))
                i += 1
                if nh > 0:
                    i += _ceil_div(nh, 8)
        if nthint > 0 and nthhsv > 0:
            i += nthint * _ceil_div(nthhsv, 5 if large else 8)
            n_thermal_dropped += 1
        if truncated:
            state.warn(f"*INITIAL_STRESS_SOLID eid={eid}: block ends before all "
                       f"{nint} integration-point cards — element skipped.")
            break
        if nh > 0:
            n_hisv_dropped += 1
        state.ini_stress_solids.append(
            InitialStressSolid(eid=eid, nint=nint, points=pts))

    if n_hisv_dropped:
        state.warn(f"*INITIAL_STRESS_SOLID: NHISV/IVEFLG history values on "
                   f"{n_hisv_dropped} element(s) have no /INIBRI slot — dropped "
                   "(plastic strain EPS itself IS mapped via Epsilon_p).")
    if n_thermal_dropped:
        state.warn(f"*INITIAL_STRESS_SOLID: thermal history (NTHINT/NTHHSV) on "
                   f"{n_thermal_dropped} element(s) has no /INIBRI slot — dropped.")


def _id_heading_card(line: str) -> Tuple[int, str]:
    """Parse a *DATABASE_..._ID header card: fixed '%10d%-70s' (the heading
    starts at column 11 and may glue onto the id), with a free-format
    fallback for 'id  title' decks."""
    head = line[:10].strip()
    if head and head.lstrip("+-").isdigit():
        return to_int(head), line[10:].strip()
    toks = parse_free(line)
    if not toks:
        return 0, ""
    return to_int(toks[0]), " ".join(toks[1:])


def handle_database_cross_section_plane(block: Block, state: ConversionState) -> None:
    """*DATABASE_CROSS_SECTION_PLANE[_ID] → /SECT (resolved geometrically).

    Card (Keyword971_R6.1 database_cross_section.cfg):
        PSID XCT YCT ZCT XCH YCH ZCH RADIUS
        [XHEV YHEV ZHEV LENL LENM ID ITYPE]
    The infinite plane through (XCT,YCT,ZCT) with normal towards (XCH,YCH,ZCH)
    is stored; the writer finds the cut elements/nodes. A finite parallelogram
    (LENL/LENM) cannot be carried into /SECT — approximated by the infinite
    plane (within RADIUS when given) with a warning.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    csid = 0
    title = ""
    if offset and raw:
        csid, title = _id_heading_card(raw[0])
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or all(not x.strip() for x in f1):
        state.warn("*DATABASE_CROSS_SECTION_PLANE: missing data card — skipped.")
        return
    g = lambda k: to_float(f1[k]) if len(f1) > k else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if f2:
        lenl = to_float(f2[3]) if len(f2) > 3 else 0.0
        lenm = to_float(f2[4]) if len(f2) > 4 else 0.0
        loc_id = to_int(f2[5]) if len(f2) > 5 else 0
        if lenl or lenm:
            state.warn(f"*DATABASE_CROSS_SECTION_PLANE{f' id={csid}' if csid else ''}: "
                       "finite parallelogram extent (LENL/LENM) cannot be carried "
                       "into /SECT — treated as an infinite plane"
                       + (" limited to RADIUS" if g(7) > 0 else "") + ".")
        if loc_id:
            state.warn(f"*DATABASE_CROSS_SECTION_PLANE{f' id={csid}' if csid else ''}: "
                       "local coordinate system ID for output has no /SECT "
                       "mapping here — forces are reported in the section frame "
                       "built from three section nodes.")
    state.cross_sections.append(CrossSection(
        csid=csid, title=title, kind="PLANE",
        psid=to_int(f1[0]),
        xct=g(1), yct=g(2), zct=g(3),
        xch=g(4), ych=g(5), zch=g(6),
        radius=g(7)))


def handle_database_cross_section_set(block: Block, state: ConversionState) -> None:
    """*DATABASE_CROSS_SECTION_SET[_ID] → /SECT (direct set mapping).

    Card: NSID HSID BSID SSID TSID DSID ID ITYPE — node set → the /SECT node
    group, solid/beam/shell element sets → its grbric/grbeam/grshel groups.
    Thick-shell (TSID) and discrete (DSID) sets have no converter-side element
    type — warned and dropped.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    csid = 0
    title = ""
    if offset and raw:
        csid, title = _id_heading_card(raw[0])
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or all(not x.strip() for x in f1):
        state.warn("*DATABASE_CROSS_SECTION_SET: missing data card — skipped.")
        return
    tsid = to_int(f1[4]) if len(f1) > 4 else 0
    dsid = to_int(f1[5]) if len(f1) > 5 else 0
    loc_id = to_int(f1[6]) if len(f1) > 6 else 0
    if tsid or dsid:
        state.warn(f"*DATABASE_CROSS_SECTION_SET{f' id={csid}' if csid else ''}: "
                   "TSID (thick shell) / DSID (discrete) element sets are not "
                   "converted — dropped from the /SECT.")
    if loc_id:
        state.warn(f"*DATABASE_CROSS_SECTION_SET{f' id={csid}' if csid else ''}: "
                   "local coordinate system ID for output has no /SECT mapping "
                   "here — forces are reported in the section frame built from "
                   "three section nodes.")
    state.cross_sections.append(CrossSection(
        csid=csid, title=title, kind="SET",
        nsid=to_int(f1[0]),
        hsid=to_int(f1[1]) if len(f1) > 1 else 0,
        bsid=to_int(f1[2]) if len(f1) > 2 else 0,
        ssid=to_int(f1[3]) if len(f1) > 3 else 0))


def handle_load_rigid_body(block: Block, state: ConversionState) -> None:
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 3:
            continue
        pid  = to_int(f[0])
        dof  = to_int(f[1])
        lcid = to_int(f[2])
        sf   = _ffield(f, 3, 1.0)
        cid  = to_int(f[4])   if len(f) > 4 else 0
        state.load_rigid_bodies.append(LoadRigidBody(pid, dof, lcid, sf, cid))


def handle_load_node(block: Block, state: ConversionState) -> None:
    """*LOAD_NODE_POINT / *LOAD_NODE_SET → /CLOAD (concentrated nodal load).

    Card: nid/nsid dof lcid sf cid m1 m2 m3.  DOF 1/2/3 = force along global
    x/y/z, 5/6/7 = moment about x/y/z; DOF 4/8 are follower loads with no
    /CLOAD equivalent (warned). CID references a *DEFINE_COORDINATE_* local
    system → /CLOAD skew.
    """
    is_set = block.keyword.endswith("_SET")
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 3:
            continue
        ref  = to_int(f[0])
        dof  = to_int(f[1])
        lcid = to_int(f[2])
        sf   = _ffield(f, 3, 1.0)
        cid  = to_int(f[4]) if len(f) > 4 else 0
        if ref <= 0 or lcid <= 0:
            continue
        if dof not in (1, 2, 3, 5, 6, 7):
            state.warn(
                f"*LOAD_NODE_{'SET' if is_set else 'POINT'} dof={dof}: only "
                "global forces (1-3) and moments (5-7) map to /CLOAD — "
                "follower loads (4/8) do not; this row was skipped.")
            continue
        if is_set:
            nsid = ref
        else:
            nsid = state.next_id()
            state.node_sets[nsid] = (f"CLOAD_node_{ref}", [ref])
        state.load_nodes.append(LoadNode(nsid, dof, lcid, sf, cid))


def handle_constrained_extra_nodes(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_EXTRA_NODES_NODE/_SET — extra nodes rigidly attached to a
    *MAT_RIGID part; merged into that part's /RBODY secondary-node group.

    Card: pid nid/nsid iflag  (iflag only matters for deformable-to-rigid
    switching, which the converter does not model).
    """
    is_set = block.keyword.endswith("_SET")
    for i in range(len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=3, w=10)
        pid = to_int(f[0])
        ref = to_int(f[1]) if len(f) > 1 else 0
        if pid <= 0 or ref <= 0:
            continue
        if is_set:
            nids = list(state.node_sets.get(ref, ("", []))[1])
            if not nids:
                state.warn(
                    f"*CONSTRAINED_EXTRA_NODES_SET pid={pid}: node set {ref} "
                    "not found (or empty) — no extra nodes attached.")
                continue
        else:
            nids = [ref]
        state.extra_rigid_nodes.setdefault(pid, []).extend(nids)


def handle_constrained_rigid_bodies(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_RIGID_BODIES — merge two rigid parts into one rigid body.

    Card: PIDM PIDS IFLAG  (one per merge; may repeat)
      PIDM = master rigid part id (survives as the single /RBODY)
      PIDS = slave rigid part id (its nodes fold into the master's rigid body)
      IFLAG = optional (deformable<->rigid switching / inertia option; not modelled)
    Both parts must be *MAT_RIGID. The writer (_make_rbodies) folds the slave's
    nodes into the master's secondary-node group, resolves chains transitively,
    and repoints the slave pid's rigid-body info at the master's master node so
    loads/motions/readouts keyed on either pid still resolve.
    """
    for i in range(len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=3, w=10)
        pidm = to_int(f[0]) if f else 0
        pids = to_int(f[1]) if len(f) > 1 else 0
        if pidm <= 0 or pids <= 0 or pidm == pids:
            continue
        state.rigid_body_merges.append((pidm, pids))


# ── *CONSTRAINED_JOINT ───────────────────────────────────────────────────────

#: Option suffixes LS-DYNA allows on a *CONSTRAINED_JOINT_<KIND> keyword after
#: parser._split_keyword has already stripped _ID/_TITLE/_SUBTITLE.
_JOINT_OPTIONS = frozenset({"LOCAL", "FAILURE"})


def handle_constrained_joint(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_JOINT_SPHERICAL / _REVOLUTE / _CYLINDRICAL / _PLANAR /
    _UNIVERSAL / _TRANSLATIONAL / _LOCKING (+ _LOCAL / _FAILURE / _ID / _TITLE)
    → a /PROP/TYPE45 (KJOINT2) joint spring built by the writer.

    Card 1: ``N1 N2 N3 N4 N5 N6 RPS DAMP`` — eight 10-wide fields. RPS and DAMP
    both default to 1.0 in LS-DYNA, so a BLANK field must not read as 0.0
    (_ffield). The optional _LOCAL (RAID/LST) and _FAILURE (CID/TFAIL/COUPL +
    N**/M**) cards follow card 1 and are only flagged here — see the writer for
    why neither maps onto /PROP/TYPE45.

    Dispatch is exact-match, so *CONSTRAINED_JOINT_TRANSLATIONAL_MOTOR (and the
    other motor/gear/pulley/screw joints) can never reach this handler and be
    misread as a plain TRANSLATIONAL — the substring test dyna2rad uses
    (keyWord.find("TRANS")) does exactly that. The kind is re-checked below
    anyway so a future registration cannot re-open the hole.
    """
    rest = block.keyword[len("CONSTRAINED_JOINT_"):]
    parts = rest.split("_")
    kind = parts[0]
    opts = parts[1:]
    if kind not in JOINT_TYPE45 or any(o not in _JOINT_OPTIONS for o in opts):
        state.warn(
            f"*{block.keyword}: not one of the seven joint kinds k2rad converts "
            f"({', '.join(sorted(JOINT_TYPE45))}) — no /PROP/TYPE45 emitted. "
            "The motor / gears / rack-and-pinion / pulley / screw / "
            "constant-velocity joints have no OpenRadioss counterpart.")
        return

    off = _title_offset(block)
    if off >= len(block.raw):
        return
    # _ID heading card is "%10d%-70s": the JID is what *CONSTRAINED_JOINT_
    # STIFFNESS's JID field points at, so a joint without _ID is unreferenceable.
    jid, title = 0, _read_title(block, f"CONSTRAINED_JOINT_{kind}")
    if _has_id(block) and block.raw:
        head = block.raw[0][:10].strip()
        if head and " " not in head and "," not in head:
            # Canonical "%10d%-70s": take the HEADING columns verbatim rather
            # than the shared free-split, which glues "        77hinge" into one
            # token and eats the first word of the title.
            #
            # A comma disqualifies the fixed reading even without a space: the
            # free-format heading "77,hinge" fits inside the first 10 columns,
            # and to_int("77,hinge") is 0 — which silently unbinds every
            # *CONSTRAINED_JOINT_STIFFNESS JID pointing at this joint.
            jid = to_int(head)
            title = block.raw[0][10:].strip() or title
        else:
            toks = parse_free(block.raw[0])
            jid = to_int(toks[0]) if toks else 0     # free "77, my joint"
    f = _card(block.raw, off, fixed=True, n=8, w=10)
    jnt = ConstrainedJoint(
        kind=kind,
        keyword=block.keyword,
        jid=jid,
        title=title,
        n1=to_int(f[0]) if len(f) > 0 else 0,
        n2=to_int(f[1]) if len(f) > 1 else 0,
        n3=to_int(f[2]) if len(f) > 2 else 0,
        n4=to_int(f[3]) if len(f) > 3 else 0,
        n5=to_int(f[4]) if len(f) > 4 else 0,
        n6=to_int(f[5]) if len(f) > 5 else 0,
        rps=_ffield(f, 6, 1.0),
        damp=_ffield(f, 7, 1.0),
        has_local="LOCAL" in opts,
        has_failure="FAILURE" in opts,
    )
    state.constrained_joints.append(jnt)


def handle_constrained_joint_stiffness(block: Block,
                                       state: ConversionState) -> None:
    """*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED / _TRANSLATIONAL → the DOF
    blocks of the matched joint's /PROP/TYPE45.

    Card 1 : JSID PIDA PIDB CIDA CIDB JID [RPS]
    Card 2 : LCIDPH LCIDT LCIDPS DLCIDPH DLCIDT DLCIDPS   (GENERALIZED)
             LCIDX  LCIDY LCIDZ  DLCIDX  DLCIDY DLCIDZ    (TRANSLATIONAL)
    Card 3 : ESPH FMPH EST FMT ESPS FMPS   /   ESX FFX ESY FFY ESZ FFZ
    Card 4 : NSAPH PSAPH NSAT PSAT NSAPS PSAPS  (DEGREES)
             NSDX  PSDX  NSDY PSDY NSDZ  PSDZ   (displacements) [+ FS FD]

    CIDB defaults to CIDA when blank (LS-DYNA R16 p.965). The FS/FD static /
    dynamic friction coefficients on TRANSLATIONAL card 4 fields 7-8 are a later
    addition to the card and are parsed as optional.

    The two unregistered options (_FLEXION-TORSION, _CYLINDRICAL) route here too
    so they surface as an explicit not-emitted note rather than a bare
    "unsupported keyword" — dyna2rad's reader profile does not even parse them
    (data_hierarchy.cfg:4414-4417 comments _FLEXION-TORSION out).
    """
    option = block.keyword[len("CONSTRAINED_JOINT_STIFFNESS_"):]
    if option not in ("GENERALIZED", "TRANSLATIONAL"):
        state.note_recognized_not_emitted(
            block.keyword,
            f"*CONSTRAINED_JOINT_STIFFNESS_{option} has no /PROP/TYPE45 field "
            "map. FLEXION-TORSION is a spherical-joint cone/torsion pair and "
            "CYLINDRICAL mixes a radial curve with axial ones; neither lines up "
            "with the Rx/Ry/Rz + Tx/Ty/Tz DOF blocks. dyna2rad does not register "
            "either keyword. The joint itself still converts — only its "
            "stiffness/damping/stop data is dropped.")
        state.warn(
            f"*{block.keyword}: joint stiffness NOT converted (no /PROP/TYPE45 "
            "field map for this option; the joint is still emitted as a "
            "kinematic joint with solver-computed blocking stiffness).")
        return

    off = _title_offset(block)
    c1 = _card(block.raw, off, fixed=True, n=8, w=10)
    c2 = _card(block.raw, off + 1, fixed=True, n=8, w=10)
    c3 = _card(block.raw, off + 2, fixed=True, n=8, w=10)
    c4 = _card(block.raw, off + 3, fixed=True, n=8, w=10)
    if not c1:
        return

    def _i3(f: List[str], a: int, b: int, c: int) -> Tuple[int, int, int]:
        g = (lambda i: to_int(f[i]) if len(f) > i else 0)
        return (g(a), g(b), g(c))

    def _f3(f: List[str], a: int, b: int, c: int) -> Tuple[float, float, float]:
        g = (lambda i: to_float(f[i]) if len(f) > i else 0.0)
        return (g(a), g(b), g(c))

    cida = to_int(c1[3]) if len(c1) > 3 else 0
    cidb = to_int(c1[4]) if len(c1) > 4 else 0
    state.joint_stiffnesses.append(JointStiffness(
        option=option,
        jsid=to_int(c1[0]),
        pida=to_int(c1[1]) if len(c1) > 1 else 0,
        pidb=to_int(c1[2]) if len(c1) > 2 else 0,
        cida=cida,
        cidb=cidb or cida,          # blank CIDB defaults to CIDA
        jid=to_int(c1[5]) if len(c1) > 5 else 0,
        rps=to_float(c1[6]) if len(c1) > 6 else 0.0,
        title=_read_title(block, f"CONSTRAINED_JOINT_STIFFNESS_{to_int(c1[0])}"),
        lcid=_i3(c2, 0, 1, 2),
        dlcid=_i3(c2, 3, 4, 5),
        es=_f3(c3, 0, 2, 4),
        fm=_f3(c3, 1, 3, 5),
        nstop=_f3(c4, 0, 2, 4),
        pstop=_f3(c4, 1, 3, 5),
        fs=to_float(c4[6]) if len(c4) > 6 else 0.0,
        fd=to_float(c4[7]) if len(c4) > 7 else 0.0,
    ))


def _record_spotweld_pair(state: ConversionState, kw: str, title: str,
                          n1: int, n2: int, nsid: int,
                          sn: float, ss: float, n_exp: float, m_exp: float,
                          tf: float, ep: float) -> None:
    """Route one weld: no failure → 2-node nodal rigid body (LS-DYNA's own
    interpretation of a spotweld without failure, reusing the validated CNRB
    machinery); with failure → a stiff /PROP/TYPE13 spring emitted by the
    writer with Ifail2=2 force criteria."""
    if tf and 0.0 < tf < 1e19:
        state.warn(f"*{kw}: failure time TF={tf:g} has no /SPRING equivalent — "
                   "dropped (weld active for the whole run).")
    if sn > 0.0 or ss > 0.0:
        if ep and 0.0 < ep < 1e19:
            state.warn(f"*{kw}: plastic failure strain EP={ep:g} dropped (the "
                       "converted weld is elastic with a force-failure surface).")
        state.constrained_spotwelds.append(ConstrainedSpotweld(
            n1=n1, n2=n2, nsid=nsid, sn=sn, ss=ss, n=n_exp, m=m_exp,
            tf=tf, ep=ep, title=title))
        return
    # No failure: rigidly tie the nodes (2-node nodal rigid body).
    if nsid > 0:
        set_id = nsid           # resolve the referenced node set at write time
    else:
        set_id = state.next_id()
        state.node_sets[set_id] = (title or "CONSTRAINED_SPOTWELD", [n1, n2])
        title = title or f"spotweld_{n1}_{n2}"
    state.cnrbs.append(ConstrainedNodalRigidBody(
        pid=state.next_id(), nsid=set_id, title=title))
    state.warn(f"*{kw}: no failure force given — converted to a 2-node nodal "
               "rigid body (/RBODY) tie, LS-DYNA's own model of an unbreakable "
               "spotweld.")


def handle_constrained_spotweld(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_SPOTWELD[_ID][_FILTERED_FORCE] — a node-pair weld.

    Card (Keyword971_R6.1 constrained_spotweld.cfg): N1 N2 SN SS N M TF EP.
    The _FILTERED_FORCE flavour appends one 'NF TW' card (force filtering has
    no /SPRING equivalent — dropped with a warning).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    filtered = "FILTERED_FORCE" in block.keyword
    step = 2 if filtered else 1
    found = False
    for i in range(offset, len(raw), step):
        if not raw[i].strip():
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        n1 = to_int(f[0]) if f else 0
        n2 = to_int(f[1]) if len(f) > 1 else 0
        if n1 <= 0 or n2 <= 0:
            continue
        found = True
        g = lambda j: to_float(f[j]) if len(f) > j else 0.0
        sn, ss = g(2), g(3)
        n_exp = _ffield(f, 4, 2.0)
        m_exp = _ffield(f, 5, 2.0)
        tf, ep = g(6), g(7)
        if filtered:
            state.warn("*CONSTRAINED_SPOTWELD_FILTERED_FORCE: the NF/TW force "
                       "filtering card has no OpenRadioss equivalent — the "
                       "failure forces act on the raw (unfiltered) force.")
        _record_spotweld_pair(state, block.keyword, title, n1, n2, 0,
                              sn, ss, n_exp, m_exp, tf, ep)
    if not found:
        state.warn("*CONSTRAINED_SPOTWELD: no valid node pair found — skipped.")


def handle_constrained_generalized_weld_spot(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_GENERALIZED_WELD_SPOT — an NSID-based weld.

    Card1: NSID CID; Card2 (subobj_constrained_generalized_weld_spot.cfg):
    TFAIL EPSF SN SS N M. The welded node set is resolved at write time.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=2, w=10)
    nsid = to_int(f1[0]) if f1 else 0
    cid = to_int(f1[1]) if len(f1) > 1 else 0
    if nsid <= 0:
        state.warn("*CONSTRAINED_GENERALIZED_WELD_SPOT: no node set id — skipped.")
        return
    if cid:
        state.warn(f"*CONSTRAINED_GENERALIZED_WELD_SPOT nsid={nsid}: CID (local "
                   "output system) is ignored.")
    f2 = _card(raw, offset + 1, fixed=True, n=6, w=10)
    g = lambda j: to_float(f2[j]) if len(f2) > j else 0.0
    tfail, epsf, sn, ss = g(0), g(1), g(2), g(3)
    n_exp = _ffield(f2, 4, 2.0)
    m_exp = _ffield(f2, 5, 2.0)
    _record_spotweld_pair(state, block.keyword,
                          title or f"GEN_WELD_SPOT_{nsid}",
                          0, 0, nsid, sn, ss, n_exp, m_exp, tfail, epsf)


def handle_rigidwall_planar(block: Block, state: ConversionState) -> None:
    """*RIGIDWALL_PLANAR[_ID] (+_FORCES/_FINITE/_MOVING combos) → /RWALL.

    Card 1: nsid nsidex boxid offset birth death rwksf
    Card 2: xt yt zt xh yh zh fric wvel
    Option cards then follow in LS-DYNA's fixed keyword-name order (FINITE
    before MOVING, matching *RIGIDWALL_PLANAR_{ORTHO}_{FINITE}_{MOVING}_
    {FORCES}):
      _FINITE: xhev yhev zhev lenl lenm — head of the l-edge vector (its
        in-plane projection is the l direction) + extents along l and
        m = n × l → /RWALL/PARAL (finite parallelogram wall).
      _MOVING: mass v0 — wall mass and initial speed along the outward
        normal (free-flying finite-mass wall) → the /RWALL moving form
        (node_ID > 0 carrier node + "Mass VX0 VY0 VZ0" card).
    _FORCES only appends force-output cards, which /TH/RWALL replaces, so it
    needs no extra parsing. _ORTHO (orthotropic friction) has no /RWALL
    equivalent and is warn-skipped by handle_rigidwall_ortho.
    """
    kw = block.keyword
    label = f"*{kw}"
    is_finite = "_FINITE" in kw
    is_moving = "_MOVING" in kw
    raw = block.raw
    offset = _title_offset(block)
    if offset and _has_id(block):
        rwid = to_int(parse_free(raw[0])[0]) if parse_free(raw[0]) else 0
        title = _read_title(block)
    else:
        rwid, title = 0, ""
    if rwid <= 0:
        rwid = state.next_id()
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1:
        state.warn(f"{label}: missing data card — skipped.")
        return
    nsid   = to_int(f1[0])
    nsidex = to_int(f1[1]) if len(f1) > 1 else 0
    boxid  = to_int(f1[2]) if len(f1) > 2 else 0
    woff   = to_float(f1[3]) if len(f1) > 3 else 0.0
    birth  = to_float(f1[4]) if len(f1) > 4 else 0.0
    death  = _ffield(f1, 5, 0.0)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if len(f2) < 6:
        state.warn(f"{label} id={rwid}: missing geometry card — skipped.")
        return
    g = lambda i: to_float(f2[i]) if len(f2) > i else 0.0
    fric = g(6)
    if woff:
        state.warn(f"{label} id={rwid}: OFFSET has no /RWALL "
                   "equivalent — ignored.")
    if birth > 0.0 or (0.0 < death < 1e20):
        state.warn(f"{label} id={rwid}: BIRTH/DEATH have no /RWALL "
                   "equivalent — the wall is active for the whole run.")

    # Optional cards, in LS-DYNA's fixed order: FINITE, then MOVING.
    idx = offset + 2
    xhev = yhev = zhev = lenl = lenm = 0.0
    if is_finite:
        ff = _card(raw, idx, fixed=True, n=8, w=10)
        idx += 1
        if len(ff) >= 5:
            xhev, yhev, zhev = to_float(ff[0]), to_float(ff[1]), to_float(ff[2])
            lenl, lenm = to_float(ff[3]), to_float(ff[4])
        else:
            state.warn(f"{label} id={rwid}: missing FINITE card — the wall "
                       "is emitted as an infinite plane.")
            is_finite = False
    mass = v0 = 0.0
    if is_moving:
        fm = _card(raw, idx, fixed=True, n=8, w=10)
        idx += 1
        if fm:
            mass = to_float(fm[0])
            v0 = to_float(fm[1]) if len(fm) > 1 else 0.0
        if mass <= 0.0:
            state.warn(f"{label} id={rwid}: MOVING wall mass is missing or "
                       "non-positive — the wall is emitted as a fixed wall.")
            is_moving = False
            mass = v0 = 0.0
        elif fric > 0.0:
            state.warn(
                f"{label} id={rwid}: LS-DYNA constrains a MOVING wall to "
                "translate along its normal; the OpenRadioss moving /RWALL "
                "is carried by a free node, which frictionless contact only "
                "loads along the normal — but with FRIC>0 tangential contact "
                "forces may also drift the wall laterally.")

    state.rigid_walls.append(RigidWallPlanar(
        rwid=rwid, title=title, nsid=nsid, nsidex=nsidex,
        xt=g(0), yt=g(1), zt=g(2), xh=g(3), yh=g(4), zh=g(5),
        fric=fric, birth=birth, death=death, offset=woff,
        boxid=boxid,
        moving=is_moving, mass=mass, v0=v0,
        finite=is_finite, xhev=xhev, yhev=yhev, zhev=zhev,
        lenl=lenl, lenm=lenm))


def handle_rigidwall_ortho(block: Block, state: ConversionState) -> None:
    """*RIGIDWALL_PLANAR_ORTHO*: orthotropic (direction-dependent) friction.

    /RWALL supports only a single isotropic Coulomb coefficient, so the ORTHO
    wall physics cannot be represented — warn-skip with the specific reason.
    """
    state.warn(
        f"*{block.keyword}: orthotropic friction (ORTHO) has no /RWALL "
        "equivalent — this rigid wall was skipped.")
    state.skipped_keywords.append(block.keyword)


def handle_element_mass(block: Block, state: ConversionState) -> None:
    """*ELEMENT_MASS: add a lumped mass at a node.

    LS-DYNA format (one card per added mass):
        eid(I8)  nid(I8)  mass(F16.0)  pid(I8)
    Accumulates into state.added_node_masses[nid].
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _element_mass_card(raw[i])
        eid  = to_int(f[0])
        nid  = to_int(f[1])
        mass = to_float(f[2])
        if nid <= 0 or mass <= 0:
            state.warn(
                f"*ELEMENT_MASS card {raw[i]!r}: parsed eid={eid} nid={nid} "
                f"mass={mass:g} — lumped mass dropped."
            )
            continue
        state.added_node_masses[nid] = (
            state.added_node_masses.get(nid, 0.0) + mass
        )


def handle_element_mass_part(block: Block, state: ConversionState) -> None:
    """*ELEMENT_MASS_PART: add non-structural mass to all nodes of a part.

    Per LS-DYNA R16 Manual Vol I, p.19-67:
      Card: ID  ADDMASS  FINMASS  LCID  MWD
      - ID: part ID (or part-set ID if _SET option active)
      - ADDMASS: extra mass distributed to part nodes by area/volume weighting
      - FINMASS: target total mass (computes ADDMASS = FINMASS − existing mass)
      - LCID: optional load curve to scale at t=0 (deformable only)
      - MWD: mass-weighted distribution flag (SET only)

    Accepts both LS-DYNA I10 long format AND free format (comma- or
    whitespace-separated) for user-friendliness.

    For rigid-body parts, the resulting mass goes directly into the /RBODY
    Mass field. For deformable parts, mass is distributed to part nodes.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        # fixed=False enables free-format with fixed-width fallback
        f = _card(raw, i, fixed=False, n=5, w=10)
        if len(f) < 2:
            continue
        try:
            pid     = to_int(f[0])
            addmass = to_float(f[1])
            finmass = to_float(f[2]) if len(f) > 2 else 0.0
        except (ValueError, IndexError):
            continue
        if pid <= 0:
            continue
        if addmass > 0 and finmass > 0:
            state.warn(
                f"*ELEMENT_MASS_PART pid={pid}: both ADDMASS and FINMASS "
                f"specified — using ADDMASS (LS-DYNA spec: one must be zero)."
            )
            finmass = 0.0
        if addmass <= 0 and finmass <= 0:
            continue
        # Accumulate (multiple invocations sum per LS-DYNA spec for _SET option)
        prev_add, prev_fin = state.element_mass_parts.get(pid, (0.0, 0.0))
        state.element_mass_parts[pid] = (prev_add + addmass, finmass or prev_fin)


def handle_element_mass_part_set(block: Block, state: ConversionState) -> None:
    """*ELEMENT_MASS_PART_SET: same as *ELEMENT_MASS_PART but ID is a part-set ID.

    Per LS-DYNA R16 Manual: when SET option is active, mass applies to every
    part in the part-set. Multiple SET applications sum.

    Accepts both LS-DYNA I10 long format AND free format.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        f = _card(raw, i, fixed=False, n=5, w=10)
        if len(f) < 2:
            continue
        try:
            psid    = to_int(f[0])
            addmass = to_float(f[1])
            finmass = to_float(f[2]) if len(f) > 2 else 0.0
        except (ValueError, IndexError):
            continue
        if psid <= 0:
            continue
        part_set = state.part_sets.get(psid)
        if not part_set:
            state.warn(f"*ELEMENT_MASS_PART_SET psid={psid}: part set not found")
            continue
        _title, pids = part_set
        if not pids:
            continue
        if addmass > 0 and finmass > 0:
            state.warn(
                f"*ELEMENT_MASS_PART_SET psid={psid}: both ADDMASS and FINMASS "
                f"specified — using ADDMASS."
            )
            finmass = 0.0
        if addmass <= 0 and finmass <= 0:
            continue
        # Distribute across parts: each part in the set gets the SAME addmass
        # (per LS-DYNA semantics — ADDMASS is per-part, sums across SET calls)
        for pid in pids:
            prev_add, prev_fin = state.element_mass_parts.get(pid, (0.0, 0.0))
            state.element_mass_parts[pid] = (prev_add + addmass, finmass or prev_fin)


def handle_element_mass_node_set(block: Block, state: ConversionState) -> None:
    """*ELEMENT_MASS_NODE_SET: lumped mass equally distributed over node set.

    Per LS-DYNA R16 Manual Vol I, p.19-64:
      "When the NODE_SET option is active, the mass is equally distributed
       to all nodes in a node set."

    Card format:  EID  ID(=nsid)  MASS  PID
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _element_mass_card(raw[i])
        nsid = to_int(f[1])
        total_mass = to_float(f[2])
        if nsid <= 0 or total_mass <= 0:
            state.warn(
                f"*ELEMENT_MASS_NODE_SET card {raw[i]!r}: parsed nsid={nsid} "
                f"mass={total_mass:g} — lumped mass dropped."
            )
            continue
        node_set = state.node_sets.get(nsid)
        if not node_set:
            state.warn(f"*ELEMENT_MASS_NODE_SET nsid={nsid}: node set not found")
            continue
        _title, nids = node_set
        if not nids:
            continue
        # Equal distribution per LS-DYNA spec
        per_node_mass = total_mass / len(nids)
        for nid in nids:
            state.added_node_masses[nid] = (
                state.added_node_masses.get(nid, 0.0) + per_node_mass
            )


def handle_initial_velocity_node(block: Block, state: ConversionState) -> None:
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 4:
            continue
        nid = to_int(f[0])
        vx  = to_float(f[1]); vy = to_float(f[2]); vz = to_float(f[3])
        vxr = to_float(f[4]) if len(f) > 4 else 0.0
        vyr = to_float(f[5]) if len(f) > 5 else 0.0
        vzr = to_float(f[6]) if len(f) > 6 else 0.0
        if nid > 0:
            state.inivel_nodes.append(InitialVelocityNode(nid, vx, vy, vz, vxr, vyr, vzr))


def handle_initial_velocity_rigid_body(block: Block, state: ConversionState) -> None:
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():        # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 4:
            continue
        pid = to_int(f[0])
        vx  = to_float(f[1]); vy = to_float(f[2]); vz = to_float(f[3])
        vxr = to_float(f[4]) if len(f) > 4 else 0.0
        vyr = to_float(f[5]) if len(f) > 5 else 0.0
        vzr = to_float(f[6]) if len(f) > 6 else 0.0
        state.inivel_rbodies.append(InitialVelocityRigidBody(pid, vx, vy, vz, vxr, vyr, vzr))


def handle_initial_velocity(block: Block, state: ConversionState) -> None:
    """*INITIAL_VELOCITY (base set form).

    Card 1: NSID NSIDEX BOXID IRIGID ICID   Card 2: VX VY VZ VXR VYR VZR
    (Card 3 = per-exempt-node velocities when NSIDEX>0 — read but discarded;
    NSIDEX is treated as pure exclusion, matching the native reader.) A blank
    Card 1 leaves every field 0 → whole-model velocity. Lossy fields (BOXID,
    IRIGID, unresolved ICID) are warned in the writer, where the sets and the
    converted /SKEW ids are all resolvable regardless of deck order.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    nsid   = to_int(f1[0]) if len(f1) > 0 else 0
    nsidex = to_int(f1[1]) if len(f1) > 1 else 0
    boxid  = to_int(f1[2]) if len(f1) > 2 else 0
    irigid = to_int(f1[3]) if len(f1) > 3 else 0
    icid   = to_int(f1[4]) if len(f1) > 4 else 0
    vx  = to_float(f2[0]) if len(f2) > 0 else 0.0
    vy  = to_float(f2[1]) if len(f2) > 1 else 0.0
    vz  = to_float(f2[2]) if len(f2) > 2 else 0.0
    vxr = to_float(f2[3]) if len(f2) > 3 else 0.0
    vyr = to_float(f2[4]) if len(f2) > 4 else 0.0
    vzr = to_float(f2[5]) if len(f2) > 5 else 0.0
    state.inivel_general.append(
        InitialVelocity(nsid, nsidex, boxid, irigid, icid,
                        vx, vy, vz, vxr, vyr, vzr))


def handle_initial_velocity_generation(block: Block, state: ConversionState) -> None:
    """*INITIAL_VELOCITY_GENERATION → /INIVEL/AXIS + companion /FRAME/FIX.

    Card 1: ID STYP OMEGA VX VY VZ IVATN ICID
    Card 2: XC YC ZC NX NY NZ PHASE IRIGID
    When NX == -999 the axis is node-defined: the NY/NZ columns hold node ids
    (origin = node1, direction = node2 − node1). A nonzero ICID rotates the
    velocity/axis to global in the writer; IVATN/PHASE/IRIGID are lossy and
    warned there.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    sid   = to_int(f1[0]) if len(f1) > 0 else 0
    styp  = to_int(f1[1]) if len(f1) > 1 else 0
    omega = to_float(f1[2]) if len(f1) > 2 else 0.0
    vx    = to_float(f1[3]) if len(f1) > 3 else 0.0
    vy    = to_float(f1[4]) if len(f1) > 4 else 0.0
    vz    = to_float(f1[5]) if len(f1) > 5 else 0.0
    ivatn = to_int(f1[6]) if len(f1) > 6 else 0
    icid  = to_int(f1[7]) if len(f1) > 7 else 0
    xc = to_float(f2[0]) if len(f2) > 0 else 0.0
    yc = to_float(f2[1]) if len(f2) > 1 else 0.0
    zc = to_float(f2[2]) if len(f2) > 2 else 0.0
    nx = to_float(f2[3]) if len(f2) > 3 else 0.0
    ny = nz = 0.0
    node1 = node2 = 0
    if -999.5 < nx < -998.5:   # NX == -999.0 sentinel → node-defined axis
        node1 = to_int(f2[4]) if len(f2) > 4 else 0
        node2 = to_int(f2[5]) if len(f2) > 5 else 0
    else:
        ny = to_float(f2[4]) if len(f2) > 4 else 0.0
        nz = to_float(f2[5]) if len(f2) > 5 else 0.0
    phase  = to_int(f2[6]) if len(f2) > 6 else 0
    irigid = to_int(f2[7]) if len(f2) > 7 else 0
    state.inivel_generations.append(
        InitialVelocityGeneration(sid, styp, omega, vx, vy, vz, ivatn, icid,
                                  xc, yc, zc, nx, ny, nz, node1, node2,
                                  phase, irigid))


def handle_mat_power_law_plasticity(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: mid rho E PR K N SRC SRP
    f1   = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1])
    E    = to_float(f1[2])
    nu   = to_float(f1[3])
    k    = to_float(f1[4]) if len(f1) > 4 else 1.0
    n    = to_float(f1[5]) if len(f1) > 5 else 0.2
    src  = to_float(f1[6]) if len(f1) > 6 else 0.0
    srp  = to_float(f1[7]) if len(f1) > 7 else 0.0
    # Card2: SIGY VP EPSF
    f2   = _card(raw, offset + 1, fixed=True, n=4, w=10)
    sigy = to_float(f2[0]) if f2        else 0.0
    vp   = to_int(f2[1])   if len(f2) > 1 else 0
    epsf = to_float(f2[2]) if len(f2) > 2 else 0.0
    state.mat_power_law[mid] = MatPowerLaw(mid, title, rho, E, nu, k, n, src, srp, sigy, vp, epsf)


def handle_mat_crushable_foam(block: Block, state: ConversionState) -> None:
    """*MAT_CRUSHABLE_FOAM (MAT_063) → /MAT/LAW50.

    LS-DYNA card (mat_063.cfg Keyword971): MID RHO E PR LCID TSC DAMP.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    E    = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu   = to_float(f1[3]) if len(f1) > 3 else 0.0
    lcid = to_int(f1[4])   if len(f1) > 4 else 0
    tsc  = to_float(f1[5]) if len(f1) > 5 else 0.0
    damp = to_float(f1[6]) if len(f1) > 6 else 0.0
    state.mat_crushable_foam[mid] = MatCrushableFoam(
        mid, title, rho, E, nu, lcid, tsc, damp)


def handle_mat_low_density_foam(block: Block, state: ConversionState) -> None:
    """*MAT_LOW_DENSITY_FOAM (MAT_057) → /MAT/LAW38.

    LS-DYNA cards (mat_057.cfg Keyword971):
      Card1: MID RHO E LCID TC HU BETA DAMP
      Card2: SHAPE FAIL BVFLAG ED BETA1 KCON REF
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    E    = to_float(f1[2]) if len(f1) > 2 else 0.0
    lcid = to_int(f1[3])   if len(f1) > 3 else 0
    tc   = to_float(f1[4]) if len(f1) > 4 else 0.0
    hu   = to_float(f1[5]) if len(f1) > 5 else 0.0
    beta = to_float(f1[6]) if len(f1) > 6 else 0.0
    damp = to_float(f1[7]) if len(f1) > 7 else 0.0
    # Card2 (optional): SHAPE is the first field
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    shape = to_float(f2[0]) if f2 else 0.0
    state.mat_low_density_foam[mid] = MatLowDensityFoam(
        mid, title, rho, E, lcid, tc, hu, beta, damp, shape)


def handle_mat_fu_chang_foam(block: Block, state: ConversionState) -> None:
    """*MAT_FU_CHANG_FOAM (MAT_083) → /MAT/LAW70 (APPROXIMATE).

    LS-DYNA cards (mat_083.cfg Keyword971_R11.1):
      Card1: MID RHO E ED TC FAIL DAMP TBID
      Card2: BVFLAG SFLAG RFLAG TFLAG PVID SRAF REF HU
      Card3: (analytic form) C3 C4 C5 AIJ SIJ MINR MAXR SHAPE
    TBID is the strain-rate load-curve family; HU (card2 field 8) and SHAPE
    (card3 field 8, analytic form) map to LAW70 Hys / Shape.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    E    = to_float(f1[2]) if len(f1) > 2 else 0.0
    tc   = to_float(f1[4]) if len(f1) > 4 else 0.0
    damp = to_float(f1[6]) if len(f1) > 6 else 0.0
    tbid = to_int(f1[7])   if len(f1) > 7 else 0
    # Card2: HU is the 8th field (hysteretic unloading factor)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    hu = to_float(f2[7]) if len(f2) > 7 else 0.0
    # Card3 (analytic constitutive form): SHAPE is the 8th field of the second
    # constitutive card. Only present when the Fu-Chang analytic constants are
    # given; guarded so the tabulated (TBID-only) form parses cleanly.
    f3 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    shape = to_float(f3[7]) if len(f3) > 7 else 0.0
    state.mat_fu_chang_foam[mid] = MatFuChangFoam(
        mid, title, rho, E, tc, damp, tbid, hu, shape)


def handle_mat_honeycomb(block: Block, state: ConversionState) -> None:
    """*MAT_HONEYCOMB (MAT_026) → /MAT/LAW28.

    LS-DYNA cards (mat_026.cfg Keyword971):
      Card1: MID RO E PR SIGY VF MU BULK
      Card2: LCA LCB LCC LCS LCAB LCBC LCCA LCSR
      Card3: EAAU EBBU ECCU GABU GBCU GCAU AOPT MACF
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    E    = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu   = to_float(f1[3]) if len(f1) > 3 else 0.0
    sigy = to_float(f1[4]) if len(f1) > 4 else 0.0
    vf   = to_float(f1[5]) if len(f1) > 5 else 0.0
    mu   = to_float(f1[6]) if len(f1) > 6 else 0.0
    bulk = to_float(f1[7]) if len(f1) > 7 else 0.0
    # Card2: the seven crush curves + strain-rate curve
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    lca  = to_int(f2[0]) if f2        else 0
    lcb  = to_int(f2[1]) if len(f2) > 1 else 0
    lcc  = to_int(f2[2]) if len(f2) > 2 else 0
    lcs  = to_int(f2[3]) if len(f2) > 3 else 0
    lcab = to_int(f2[4]) if len(f2) > 4 else 0
    lcbc = to_int(f2[5]) if len(f2) > 5 else 0
    lcca = to_int(f2[6]) if len(f2) > 6 else 0
    lcsr = to_int(f2[7]) if len(f2) > 7 else 0
    # Card3: the uncompressed moduli
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    eaau = to_float(f3[0]) if f3        else 0.0
    ebbu = to_float(f3[1]) if len(f3) > 1 else 0.0
    eccu = to_float(f3[2]) if len(f3) > 2 else 0.0
    gabu = to_float(f3[3]) if len(f3) > 3 else 0.0
    gbcu = to_float(f3[4]) if len(f3) > 4 else 0.0
    gcau = to_float(f3[5]) if len(f3) > 5 else 0.0
    state.mat_honeycomb[mid] = MatHoneycomb(
        mid, title, rho, E, nu, sigy, vf, mu, bulk,
        eaau, ebbu, eccu, gabu, gbcu, gcau,
        lca, lcb, lcc, lcs, lcab, lcbc, lcca, lcsr)


# ─────────────────────────────────────────────────────────────────────────────
# Hyperelastic rubber batch (MAT_007 / MAT_027 / MAT_077_O / MAT_077_H)
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_blatz_ko(block: Block, state: ConversionState) -> None:
    """*MAT_BLATZ-KO_RUBBER (MAT_007) → /MAT/LAW42 fixed form.

    Card 1: MID RHO G REF (mat_007.cfg). dyna2rad case 7 maps Mu_1 = G,
    alpha_1 = 2, Nu = 0.463 (the Poisson value the LS-DYNA Blatz-Ko
    implementation hard-codes). REF=1 relies on *INITIAL_FOAM_REFERENCE_GEOMETRY
    for the actual /XREF node table — dyna2rad additionally emits a nodeless
    /XREF stub (Nitrs=100, no coordinates), which is deliberately NOT
    replicated: without the keyword there are no reference coordinates to
    initialize from (warned in the writer resolve pass instead).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f1 = _card(block.raw, offset, fixed=True, n=4, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_BLATZ-KO_RUBBER: empty material card — skipped")
        return
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    g   = to_float(f1[2]) if len(f1) > 2 else 0.0
    ref = to_float(f1[3]) if len(f1) > 3 else 0.0
    state.mat_blatz_ko[mid] = MatBlatzKo(mid, title, rho, g, ref)


def handle_mat_mooney_rivlin(block: Block, state: ConversionState) -> None:
    """*MAT_MOONEY-RIVLIN_RUBBER (MAT_027) → /MAT/LAW42 or /MAT/LAW69.

    Cards (mat_027.cfg): MID RHO PR A B REF / SGL SW ST LCID.
    dyna2rad p_ConvertMatL27 routes on the LCID handle: no parsed curve →
    LAW42 with the Ogden equivalents Mu_1 = 2A, Mu_2 = -2B, alpha_1 = 2,
    alpha_2 = -2, Nu = PR VERBATIM (no abs/clamp; 0 → the starter's 0.495)
    plus a 500-point funIDbulk curve; parsed curve → LAW69 LAW_ID=2 with the
    curve id unmodified (the starter runs the Mooney-Rivlin fit). SGL/SW/ST
    and REF are never read by dyna2rad in either branch (warned here when they
    would matter). Routing + curve synthesis happen in the writer resolve pass
    (_resolve_mat_hyper_rubber), which needs the parsed *DEFINE_CURVEs.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_MOONEY-RIVLIN_RUBBER: empty material card — skipped")
        return
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    pr  = to_float(f1[2]) if len(f1) > 2 else 0.0
    a   = to_float(f1[3]) if len(f1) > 3 else 0.0
    b   = to_float(f1[4]) if len(f1) > 4 else 0.0
    ref = to_float(f1[5]) if len(f1) > 5 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=4, w=10)
    sgl  = to_float(f2[0]) if f2 else 0.0
    sw   = to_float(f2[1]) if len(f2) > 1 else 0.0
    st   = to_float(f2[2]) if len(f2) > 2 else 0.0
    lcid = to_int(f2[3]) if len(f2) > 3 else 0
    state.mat_mooney_rivlin[mid] = MatMooneyRivlin(
        mid=mid, title=title, rho=rho, pr=pr, a=a, b=b, ref=ref,
        sgl=sgl, sw=sw, st=st, lcid=lcid)


def _prony_rows(raw: List[str], start: int, ncols: int) -> List[List[float]]:
    """The free viscoelastic-constant card list at the tail of a *MAT_077_O/_H
    block (FREE_CARD_LIST in the cfg: one term per card until the block ends).
    Returns one [col0..col(ncols-1)] float row per non-blank card."""
    rows: List[List[float]] = []
    for idx in range(start, len(raw)):
        if not raw[idx].strip():
            continue
        f = _card(raw, idx, fixed=True, n=ncols, w=10)
        vals = [to_float(f[i]) if len(f) > i else 0.0 for i in range(ncols)]
        if any(v != 0.0 for v in vals):
            rows.append(vals)
    return rows


def handle_mat_ogden_rubber(block: Block, state: ConversionState) -> None:
    """*MAT_OGDEN_RUBBER (MAT_077_O) → /MAT/LAW42 (N=0) or /MAT/LAW69 (N>0).

    Cards (mat_077_O.cfg): MID RO PR N NV G SIGF REF; N=0 → MU1..MU8 /
    ALPHA1..ALPHA8; N>0 → SGL SW ST LCID1 DATA LCID2 BSTART TRAMP; then the
    free GI/BETAI Prony list. dyna2rad p_ConvertMatL77: N=0 keeps the pairs
    1:1 (Nu = |PR|, Mullins PR<0 warned) with the BETAI>0 Prony terms embedded
    on the LAW42 card (Tau_i = 1/BETAI, Gamma_i = GI, I_form=2); N>0 →
    LAW69 with LAW_ID = int(DATA), N_PAIR = N and the LCID1 curve rescaled by
    1/SGL (abscissa) and 1/(SW*ST) (ordinate) into a *_Duplicate function.
    NV/LCID2/BSTART/TRAMP are never read (warned); G>0 & SIGF>0 would become
    /VISC/PLAS, whose card only exists from the radioss2025 input format on —
    unreadable in the /BEGIN 2022 decks k2rad emits, so it is warn-dropped.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_OGDEN_RUBBER: empty material card — skipped")
        return
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    pr   = to_float(f1[2]) if len(f1) > 2 else 0.0
    n    = int(to_float(f1[3])) if len(f1) > 3 else 0
    nv   = int(to_float(f1[4])) if len(f1) > 4 else 0
    g    = to_float(f1[5]) if len(f1) > 5 else 0.0
    sigf = to_float(f1[6]) if len(f1) > 6 else 0.0
    ref  = to_float(f1[7]) if len(f1) > 7 else 0.0
    mat = MatOgdenRubber(mid=mid, title=title, rho=rho, pr=pr, n=n, nv=nv,
                         g=g, sigf=sigf, ref=ref)
    if n < 0:
        state.warn(f"*MAT_OGDEN_RUBBER mid={mid}: N={n} is not a valid fit "
                   "order — treated as N=0 (direct mu/alpha constants); "
                   "dyna2rad would silently convert nothing.")
        mat.n = n = 0
    if n == 0:
        f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
        f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
        mat.mu    = [to_float(f2[i]) if len(f2) > i else 0.0 for i in range(8)]
        mat.alpha = [to_float(f3[i]) if len(f3) > i else 0.0 for i in range(8)]
        prony_start = offset + 3
    else:
        f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
        mat.sgl    = to_float(f2[0]) if f2 else 0.0
        mat.sw     = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.st     = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.lcid1  = to_int(f2[3]) if len(f2) > 3 else 0
        mat.data   = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.lcid2  = to_int(f2[5]) if len(f2) > 5 else 0
        mat.bstart = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.tramp  = to_float(f2[7]) if len(f2) > 7 else 0.0
        prony_start = offset + 2
    for gi, betai in _prony_rows(raw, prony_start, 2):
        mat.gi.append(gi)
        mat.betai.append(betai)
    state.mat_ogden[mid] = mat


def handle_mat_hyperelastic_rubber(block: Block, state: ConversionState) -> None:
    """*MAT_HYPERELASTIC_RUBBER (MAT_077_H) → /MAT/LAW95 (N=0) or /MAT/LAW69
    (N>0), + /VISC/PRONY from the Gi/BETAi list (both branches).

    Cards (mat_077_H.cfg): MID RHO PR N NV G SIGF REF; N=0 → C10 C01 C11 C20
    C02 C30; N>0 → SGL SW ST LCID1 DATA LCID2 BSTART TRAMP; then the free
    Gi/BETAi/Gj/SIGFj list. dyna2rad p_ConvertMatL77H: N=0 copies the
    polynomial coefficients 1:1 into LAW95 and encodes the compressibility as
    D1 = |2/K| with K = 2G(1+PR)/3/(1-2PR), G = 2(C10+C01) (PR<0 → Mullins
    warning, D1 left 0 → starter defaults nu to 0.495); N>0 is byte-for-byte
    the 077_O LAW69 branch. The Gi/BETAi terms go to a /VISC/PRONY of the
    material's id (Beta_i used directly — NO 1/BETA inversion here, and no
    BETAI>0 filtering, both unlike the 077_O embedded-Prony path). The header
    G/SIGF and the per-term Gj/SIGFj damping columns are never read (warned).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_HYPERELASTIC_RUBBER: empty material card — skipped")
        return
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    pr   = to_float(f1[2]) if len(f1) > 2 else 0.0
    n    = int(to_float(f1[3])) if len(f1) > 3 else 0
    nv   = int(to_float(f1[4])) if len(f1) > 4 else 0
    g    = to_float(f1[5]) if len(f1) > 5 else 0.0
    sigf = to_float(f1[6]) if len(f1) > 6 else 0.0
    ref  = to_float(f1[7]) if len(f1) > 7 else 0.0
    mat = MatHyperelasticRubber(mid=mid, title=title, rho=rho, pr=pr, n=n,
                                nv=nv, g=g, sigf=sigf, ref=ref)
    if n < 0:
        state.warn(f"*MAT_HYPERELASTIC_RUBBER mid={mid}: N={n} is not a valid "
                   "fit order — treated as N=0 (direct C10..C30 constants); "
                   "dyna2rad would silently convert nothing.")
        mat.n = n = 0
    if n == 0:
        f2 = _card(raw, offset + 1, fixed=True, n=6, w=10)
        mat.c10 = to_float(f2[0]) if f2 else 0.0
        mat.c01 = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.c11 = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.c20 = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.c02 = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.c30 = to_float(f2[5]) if len(f2) > 5 else 0.0
        prony_start = offset + 2
    else:
        f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
        mat.sgl    = to_float(f2[0]) if f2 else 0.0
        mat.sw     = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.st     = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.lcid1  = to_int(f2[3]) if len(f2) > 3 else 0
        mat.data   = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.lcid2  = to_int(f2[5]) if len(f2) > 5 else 0
        mat.bstart = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.tramp  = to_float(f2[7]) if len(f2) > 7 else 0.0
        prony_start = offset + 2
    for gi, betai, gj, sigfj in _prony_rows(raw, prony_start, 4):
        mat.gi.append(gi)
        mat.betai.append(betai)
        mat.gj.append(gj)
        mat.sigfj.append(sigfj)
    state.mat_hyper_rubber[mid] = mat


def handle_initial_foam_reference_geometry(block: Block,
                                           state: ConversionState) -> None:
    """*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] → /XREF per intersecting part.

    Node table rows are *NODE-format (NID I8, X/Y/Z E16 —
    initial_foam_reference_geometry.cfg); the _RAMP variant prepends one card
    with NDTRRG (ramp steps → /XREF Nitrs when > 0). Stored per keyword
    instance; the /XREF blocks themselves are built by writer.inistate
    _make_xref (dyna2rad converts the keyword unconditionally — the material
    REF flags never gate it).
    """
    ref = FoamRefGeometry()
    raw = block.raw
    start = 0
    if block.keyword.endswith("_RAMP"):
        for idx, line in enumerate(raw):
            if line.strip():
                f = _card(raw, idx, fixed=True, n=1, w=10)
                ref.ndtrrg = to_int(f[0]) if f else 0
                start = idx + 1
                break
    for line in raw[start:]:
        f = parse_free(line)
        # Same glued-negative-coordinate hazard as *NODE: re-slice fixed
        # columns when the whitespace split under-counts or merges fields.
        if len(f) < 4 or any(len(t) > 16 for t in f[1:4]):
            nid = to_int(line[0:8])
            if nid <= 0:
                continue
            ref.nodes[nid] = (to_float(line[8:24]), to_float(line[24:40]),
                              to_float(line[40:56]))
            continue
        nid = to_int(f[0])
        if nid > 0:
            ref.nodes[nid] = (to_float(f[1]), to_float(f[2]), to_float(f[3]))
    if ref.nodes:
        state.foam_ref_geoms.append(ref)
    else:
        state.warn("*INITIAL_FOAM_REFERENCE_GEOMETRY: no node rows parsed — "
                   "no /XREF emitted for this block.")


def handle_mat_spring_elastic(block: Block, state: ConversionState) -> None:
    """*MAT_SPRING_ELASTIC (MAT_S01): MID K → /PROP/TYPE4 stiffness K."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=2, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_SPRING_ELASTIC: empty card – skipped")
        return
    mid = to_int(f[0])
    k = to_float(f[1]) if len(f) > 1 else 0.0
    state.mat_spring_elastic[mid] = MatSpringElastic(mid, k)


def handle_mat_spring_nonlinear_elastic(block: Block, state: ConversionState) -> None:
    """*MAT_SPRING_NONLINEAR_ELASTIC (MAT_S04): MID LCD LCR → /PROP/TYPE4
    fct_ID1 = LCD (force vs displacement). LCR (force scale vs rate) has no
    /PROP/TYPE4 slot the cfg confirms, so it is dropped with a warning."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=3, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_SPRING_NONLINEAR_ELASTIC: empty card – skipped")
        return
    mid = to_int(f[0])
    lcd = to_int(f[1]) if len(f) > 1 else 0
    lcr = to_int(f[2]) if len(f) > 2 else 0
    state.mat_spring_nonlinear[mid] = MatSpringNonlinearElastic(mid, lcd, lcr)


def handle_mat_damper_viscous(block: Block, state: ConversionState) -> None:
    """*MAT_DAMPER_VISCOUS (MAT_D01): MID DC → /PROP/TYPE4 damping C."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=2, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_DAMPER_VISCOUS: empty card – skipped")
        return
    mid = to_int(f[0])
    dc = to_float(f[1]) if len(f) > 1 else 0.0
    state.mat_damper_viscous[mid] = MatDamperViscous(mid, dc)


def handle_mat_spotweld(block: Block, state: ConversionState) -> None:
    """*MAT_SPOTWELD (MAT_100) → /PROP/TYPE13 (SPR_BEAM) spring connectors.

    Card1 (Keyword971 mat_100.cfg): MID RO E PR SIGY EH DT TFAIL
    Card2: EFAIL NRR NRS NRT MRR MSS MTT NF
    Negative SIGY / failure-force values mean 'curve id' in the DAMAGE-FAILURE
    option; only positive scalars are converted.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_SPOTWELD: empty material card – skipped")
        return
    mid   = to_int(f1[0])
    rho   = to_float(f1[1]) if len(f1) > 1 else 0.0
    E     = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu    = to_float(f1[3]) if len(f1) > 3 else 0.0
    sigy  = to_float(f1[4]) if len(f1) > 4 else 0.0
    et    = to_float(f1[5]) if len(f1) > 5 else 0.0
    dt    = to_float(f1[6]) if len(f1) > 6 else 0.0
    tfail = to_float(f1[7]) if len(f1) > 7 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g = lambda i: to_float(f2[i]) if len(f2) > i else 0.0
    efail, nrr, nrs, nrt = g(0), g(1), g(2), g(3)
    mrr, mss, mtt, nf = g(4), g(5), g(6), g(7)
    if sigy < 0.0:
        state.warn(f"*MAT_SPOTWELD mid={mid}: SIGY<0 (yield stress from a curve) "
                   "is not supported — yield dropped (elastic weld until failure).")
        sigy = 0.0
    neg = [name for name, v in (("NRR", nrr), ("NRS", nrs), ("NRT", nrt),
                                ("MRR", mrr), ("MSS", mss), ("MTT", mtt)) if v < 0.0]
    if neg:
        state.warn(f"*MAT_SPOTWELD mid={mid}: {', '.join(neg)} < 0 (curve-driven "
                   "failure resultants) not supported — treated as no failure in "
                   "those components.")
        nrr, nrs, nrt = max(nrr, 0.0), max(nrs, 0.0), max(nrt, 0.0)
        mrr, mss, mtt = max(mrr, 0.0), max(mss, 0.0), max(mtt, 0.0)
    state.mat_spotweld[mid] = MatSpotweld(mid, title, rho, E, nu, sigy, et, dt,
                                          tfail, efail, nrr, nrs, nrt,
                                          mrr, mss, mtt, nf)


def _num_ok(s: str) -> bool:
    """True if *s* parses as a number (Fortran exponent spellings included)."""
    v = to_float(s, default=float("nan"))
    return v == v


def _samp_card(raw: List[str], idx: int) -> List[str]:
    """Fixed-width card read hardened against free-format lines that slice
    cleanly: a wide-spaced free card can straddle the 10-char boundaries
    ("1.0500E-9" → slices "1.0500" + "E-9") without tripping _card's
    internal-whitespace fallback, silently corrupting every value (a 1e9×
    density error that passes every downstream guard). Non-numeric junk in a
    slice is the tell — retry a free split when every free token is numeric.
    Also rescues tab-delimited cards (_card's fallback tests literal spaces)."""
    f = _card(raw, idx, fixed=True)
    if f and any(x and not _num_ok(x) for x in f):
        tokens = parse_free(raw[idx]) if idx < len(raw) else []
        if tokens and all(t == "" or _num_ok(t) for t in tokens):
            return tokens + [""] * max(0, 8 - len(tokens))
    return f


def handle_mat_187(block: Block, state: ConversionState) -> None:
    """*MAT_187 / *MAT_SAMP-1 → /MAT/LAW76 (SAMP-1 polymer).

    Official manual card layout (what LS-PrePost exports):
      Card1: MID RO BULK GMOD EMOD NUE RBCFAC NUMINT
      Card2: LCID-T LCID-C LCID-S LCID-B NUEP LCID-P - INCDAM
      Card3: LCID-D EPFAIL DEPRPT LCID-TRI LCID-LC
      Card4: MITER MIPS - INCFAIL ICONV ASAF - NHSV
      Card5: LCEMOD BETA FILT
    LAW76 wants E/ν directly: EMOD/NUE when given, else derived from BULK+GMOD
    (E = 9KG/(3K+G), ν = (3K−2G)/(6K+2G)); MAT_187 Remark 6 then lowers the
    effective elastic ν to min(NUE, NUEP). Cards are parsed fixed-width because
    RO regularly fills its whole 10-char field and fuses with MID
    ("1871.05000E-9") — a free split shifts every value and emits
    /MAT/LAW76/0 with zero density (starter ERROR 683). LCID-D is SAMP's damage
    -vs-plastic-strain curve = LAW76 fct_ID1; LCID-P is its plastic-Poisson
    -ratio-vs-plastic-strain curve = LAW76 fct_IDpr (both stay /FUNCT).
    DEPRPT is the plastic-strain INCREMENT from failure to rupture, while
    LAW76's Epsilon_r_p is ABSOLUTE — the sum is emitted. The three yield
    curves (LCID-T/C/S) must become /TABLE cards, so their ids are registered
    in state.law76_table_ids.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw

    # Card1: MID RO BULK GMOD EMOD NUE RBCFAC NUMINT
    f1 = _samp_card(raw, offset)
    if not f1 or not f1[0]:
        state.warn("*MAT_187: empty material card – skipped")
        return
    mid    = to_int(f1[0])
    rho    = to_float(f1[1]) if len(f1) > 1 else 0.0
    bulk   = to_float(f1[2]) if len(f1) > 2 else 0.0
    gmod   = to_float(f1[3]) if len(f1) > 3 else 0.0
    emod   = to_float(f1[4]) if len(f1) > 4 else 0.0
    nue    = to_float(f1[5]) if len(f1) > 5 else 0.0
    rbcfac = to_float(f1[6]) if len(f1) > 6 else 0.0
    if mid <= 0:
        state.warn(f"*MAT_187 '{title}': MID parsed as {mid} — unreadable "
                   "(shifted or fused fields?); material skipped. A /MAT id "
                   "of 0 would fail the starter (ERROR 683).")
        return
    # Card2: LCID-T LCID-C LCID-S LCID-B NUEP LCID-P - INCDAM
    f2 = _samp_card(raw, offset + 1)
    tab_idt = to_int(f2[0]) if f2 else 0
    tab_idc = to_int(f2[1]) if len(f2) > 1 else 0
    tab_ids = to_int(f2[2]) if len(f2) > 2 else 0
    lcid_b  = to_int(f2[3]) if len(f2) > 3 else 0
    if len(f2) > 4 and f2[4]:
        nu_p = to_float(f2[4])
    else:
        # DYNA reads a blank NUEP as 0.0 = strongly dilatant plastic flow
        # (there is no documented default); substituting anything else would
        # silently change the volumetric plastic response.
        nu_p = 0.0
        state.warn(f"*MAT_187 {mid}: NUEP blank — LS-DYNA treats it as 0.0 "
                   "(strongly dilatant plastic flow); Nu_p=0 emitted. Set "
                   "NUEP explicitly if that is not intended.")
    fct_idpr = to_int(f2[5]) if len(f2) > 5 else 0
    incdam   = to_int(f2[7]) if len(f2) > 7 else 0
    # Card3: LCID-D EPFAIL DEPRPT LCID-TRI LCID-LC
    f3 = _samp_card(raw, offset + 2)
    fct_id1  = to_int(f3[0])   if f3 else 0
    epfail   = to_float(f3[1]) if len(f3) > 1 else 0.0
    deprpt   = to_float(f3[2]) if len(f3) > 2 else 0.0
    lcid_tri = to_int(f3[3])   if len(f3) > 3 else 0
    lcid_lc  = to_int(f3[4])   if len(f3) > 4 else 0
    # Negative LCID-D/EPFAIL/DEPRPT are LS-DYNA curve-reference/ASSR
    # conventions (EPFAIL vs strain rate, DEPRPT vs triaxiality, ASSR
    # recalibration). None is representable in LAW76, and a literal negative
    # Epsilon would make the engine's DMG=(PLA-EPSF)/(EPSR-EPSF) negative —
    # post-failure stress AMPLIFICATION instead of fade-out.
    if fct_id1 < 0 or epfail < 0.0 or deprpt < 0.0:
        state.warn(f"*MAT_187 {mid}: negative LCID-D/EPFAIL/DEPRPT are "
                   "LS-DYNA curve/ASSR conventions with no /MAT/LAW76 "
                   "counterpart — dropped (no damage/failure from these "
                   "fields).")
        fct_id1 = max(fct_id1, 0)
        epfail  = max(epfail, 0.0)
        deprpt  = max(deprpt, 0.0)
    # Card4: MITER MIPS - INCFAIL ICONV ASAF - NHSV (solver numerics; only
    # ICONV has a LAW76 counterpart — blank keeps LAW76's convexity default 1)
    f4 = _samp_card(raw, offset + 3)
    incfail = to_int(f4[3]) if len(f4) > 3 else 0
    iconv   = to_int(f4[4]) if len(f4) > 4 and f4[4] else 1
    if incfail == -1 and (epfail > 0.0 or deprpt > 0.0):
        state.warn(f"*MAT_187 {mid}: INCFAIL=-1 deactivates the failure "
                   "model in LS-DYNA — EPFAIL/DEPRPT dropped so the converted "
                   "material does not erode either.")
        epfail, deprpt = 0.0, 0.0
    # Card5: LCEMOD BETA FILT — damage-coupled unloading modulus and strain-
    # rate filtering; no LAW76 counterpart (Fsmooth/Fcut keep their defaults)
    f5 = _samp_card(raw, offset + 4)
    lcemod = to_int(f5[0])   if f5 else 0
    beta   = to_float(f5[1]) if len(f5) > 1 else 0.0
    filt   = to_float(f5[2]) if len(f5) > 2 else 0.0

    # Elastic constants: EMOD/NUE when given, else derived from BULK+GMOD.
    if emod > 0.0:
        E, nu = emod, nue
    elif bulk > 0.0 and gmod > 0.0:
        E  = 9.0 * bulk * gmod / (3.0 * bulk + gmod)
        nu = (3.0 * bulk - 2.0 * gmod) / (6.0 * bulk + 2.0 * gmod)
        note = (" — ν≈0.5 is suspicious: a legacy condensed 'mid ro e nu' "
                "card read as the official layout lands E in BULK and ν in "
                "GMOD; check the card" if nu >= 0.49 else "")
        state.warn(f"*MAT_187 {mid}: EMOD blank — derived E={E:.6g} "
                   f"nu={nu:.6g} from BULK/GMOD for /MAT/LAW76{note}.")
    else:
        E, nu = 0.0, 0.0
        state.warn(f"*MAT_187 {mid}: no usable elastic modulus (EMOD and "
                   "BULK/GMOD all blank or 0) — /MAT/LAW76 gets E=0, a "
                   "zero-stiffness material the starter accepts silently.")
    # MAT_187 Remark 6: the effective elastic Poisson ratio is min(NUE, NUEP)
    # (not applied when a NUEP-vs-strain curve overrides the constant).
    if fct_idpr == 0 and nu_p < nu:
        state.warn(f"*MAT_187 {mid}: effective elastic nu lowered to "
                   f"min(NUE, NUEP)={nu_p:g} per LS-DYNA MAT_187 Remark 6.")
        nu = nu_p
    if rho <= 0.0:
        state.warn(f"*MAT_187 {mid}: density {rho:g} ≤ 0 — the starter will "
                   "reject this material (ERROR 683: DENSITY IS LESS THAN OR "
                   "EQUAL TO ZERO). Check the card for shifted/fused fields.")
    # DYNA's DEPRPT is the INCREMENT from failure to rupture; LAW76's
    # Epsilon_r_p is ABSOLUTE (engine: DMG=(PLA-EPSF)/(EPSR-EPSF), delete at
    # PLA>=EPSR) — emitting DEPRPT raw would put EPSR below EPSF. With DEPRPT
    # blank DYNA ruptures AT EPFAIL, so use a hair above it to keep the DMG
    # denominator finite.
    if epfail > 0.0:
        eps_rupt = epfail + deprpt if deprpt > 0.0 else epfail * 1.001
    else:
        eps_rupt = 0.0
    if fct_id1 and epfail > 0.0:
        state.warn(f"*MAT_187 {mid}: LAW76 uses the damage function and "
                   "Epsilon_f_p/Epsilon_r_p mutually exclusively (the "
                   "function wins; erosion only when damage reaches 1), while "
                   "LS-DYNA combines LCID-D with erosion at EPFAIL+DEPRPT — "
                   "check the damage curve reaches 1 or the part never "
                   "erodes.")

    unmapped = [name for name, val in (("RBCFAC", rbcfac),
                                       ("INCDAM", incdam),
                                       ("LCID-B", lcid_b),
                                       ("LCID-TRI", lcid_tri),
                                       ("LCID-LC", lcid_lc),
                                       ("INCFAIL", max(incfail, 0)),
                                       ("LCEMOD", lcemod),
                                       ("BETA", beta), ("FILT", filt)) if val]
    if unmapped:
        state.warn(f"*MAT_187 {mid}: no /MAT/LAW76 counterpart for non-zero "
                   f"field(s) {', '.join(unmapped)} — ignored.")

    state.mat_samp[mid] = MatSAMP(mid, title, rho, E, nu, tab_idt, tab_idc,
                                  tab_ids, nu_p, fct_idpr, fct_id1, epfail,
                                  eps_rupt, iconv, 0.0)
    for tid in (tab_idt, tab_idc, tab_ids):
        if tid:
            state.law76_table_ids.add(tid)


def handle_mat_add_damage_gissmo(block: Block, state: ConversionState) -> None:
    """*MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2 (GISSMO). Card layout from the reader
    cfg MATERIALBEHAVIOR/mat_add_damage_gissmo.cfg:
      Card1: MID <blank> DTYP REFSZ NUMFIP [VOLFRAC]
      Card2: LCSDG ECRIT DMGEXP DCRIT FADEXP LCREGD [INSTF]
      Card3: LCSRS SHRF BIAXF ...
    Only the fields with a /FAIL/TAB2 counterpart are captured."""
    offset = _title_offset(block)
    raw = block.raw
    # Card1 (fixed 10-wide; field 1 is intentionally blank)
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0]:
        state.warn("*MAT_ADD_DAMAGE_GISSMO: empty card – skipped")
        return
    mid    = to_int(f1[0])
    numfip = to_float(f1[4]) if len(f1) > 4 and f1[4] else 1.0
    # Card2
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    lcsdg  = to_int(f2[0])   if f2        else 0
    ecrit  = to_float(f2[1]) if len(f2) > 1 else 0.0
    dmgexp = to_float(f2[2]) if len(f2) > 2 else 1.0
    dcrit  = to_float(f2[3]) if len(f2) > 3 else 0.0
    fadexp = to_float(f2[4]) if len(f2) > 4 else 1.0
    lcregd = to_int(f2[5])   if len(f2) > 5 else 0
    # Card3 (optional)
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    lcsrs  = to_float(f3[0]) if f3 else 0.0

    state.fail_gissmo[mid] = FailGissmo(mid, numfip, lcsdg, ecrit, dmgexp,
                                        dcrit, fadexp, lcregd, lcsrs)
    if not lcsdg:
        state.warn(f"*MAT_ADD_DAMAGE_GISSMO {mid}: no LCSDG failure curve — "
                   "/FAIL/TAB2 needs EPSF_ID; damage will not accumulate.")


def handle_mat_add_erosion(block: Block, state: ConversionState) -> None:
    """*MAT_ADD_EROSION → an OpenRadioss /FAIL/GENE1 model.
    Card layout from mat_add_erosion.cfg:
      Card1: MID EXCL MXPRES MNEPS EFFEPS VOLEPS NUMFIP NCS
      Card2: MNPRES SIGP1 SIGVM MXEPS EPSSH SIGTH IMPULSE FAILTM
      Card3 (optional): IDAM ... (GISSMO/DIEM — reported, not converted)
      Card4/5 (optional): MXTMP DTMIN VOLFRAC MXPRES(solid) ... — only present
        alongside an IDAM card, which is not converted, so these are not parsed
        (MXTMP→Temp_max, DTMIN→dtmin would map if IDAM support were added).

    EXCL (default 0) is LS-DYNA's exclusion number: any card-1/card-2 field whose
    value equals EXCL is inactive. GENE1 uses the same 0→inactive convention, so
    with EXCL=0 (the common case) the values pass straight through; a non-zero
    EXCL is applied here (excluded fields zeroed) so the two conventions align."""
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0]:
        state.warn("*MAT_ADD_EROSION: empty card – skipped")
        return
    mid    = to_int(f1[0])
    excl   = to_float(f1[1]) if len(f1) > 1 else 0.0
    mxpres = to_float(f1[2]) if len(f1) > 2 else 0.0
    mneps  = to_float(f1[3]) if len(f1) > 3 else 0.0
    effeps = to_float(f1[4]) if len(f1) > 4 else 0.0
    voleps = to_float(f1[5]) if len(f1) > 5 else 0.0
    numfip = to_float(f1[6]) if len(f1) > 6 else 1.0
    ncs    = to_float(f1[7]) if len(f1) > 7 else 1.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    mnpres  = to_float(f2[0]) if f2         else 0.0
    sigp1   = to_float(f2[1]) if len(f2) > 1 else 0.0
    sigvm   = to_float(f2[2]) if len(f2) > 2 else 0.0
    mxeps   = to_float(f2[3]) if len(f2) > 3 else 0.0
    epssh   = to_float(f2[4]) if len(f2) > 4 else 0.0
    sigth   = to_float(f2[5]) if len(f2) > 5 else 0.0
    impulse = to_float(f2[6]) if len(f2) > 6 else 0.0
    failtm  = to_float(f2[7]) if len(f2) > 7 else 0.0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    idam = to_int(f3[0]) if f3 and f3[0] else 0

    # Apply the EXCL exclusion: a field == a non-zero EXCL is inactive → 0
    # (which GENE1 also reads as inactive). Leave the special four (MXPRES/MNEPS/
    # EFFEPS/VOLEPS) and everything else untouched when EXCL is the 0 default.
    def _ex(v: float) -> float:
        return 0.0 if (excl != 0.0 and v == excl) else v

    if mid in state.mat_add_erosion:
        state.warn(f"*MAT_ADD_EROSION: a second card for MID {mid} overwrites "
                   "the first — OpenRadioss keeps only one /FAIL/GENE1 per "
                   "material, so the earlier card's criteria are dropped. Merge "
                   "the criteria into a single *MAT_ADD_EROSION card.")
    state.mat_add_erosion[mid] = MatAddErosion(
        mid=mid, excl=excl,
        mxpres=_ex(mxpres), mneps=_ex(mneps), effeps=_ex(effeps),
        voleps=_ex(voleps), numfip=numfip, ncs=ncs,
        mnpres=_ex(mnpres), sigp1=_ex(sigp1), sigvm=_ex(sigvm),
        mxeps=_ex(mxeps), epssh=_ex(epssh), sigth=_ex(sigth),
        impulse=_ex(impulse), failtm=_ex(failtm), idam=idam)


def handle_constrained_node_set(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_NODE_SET → /RLINK. Card: NSID DOF TF."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=3, w=10)
    if not f or not f[0]:
        state.warn("*CONSTRAINED_NODE_SET: empty card – skipped")
        return
    nsid = to_int(f[0])
    dof  = to_int(f[1])   if len(f) > 1 else 0
    tf   = to_float(f[2]) if len(f) > 2 else 1e20
    state.constrained_node_sets.append(ConstrainedNodeSet(nsid, dof, tf))


def handle_load_segment(block: Block, state: ConversionState) -> None:
    raw = block.raw
    # _ID variant: first line is "id  title", data starts at index 1
    data = raw[1:] if _has_id(block) else raw
    # One card per loaded segment; the card may REPEAT inside one keyword.
    for i in range(len(data)):
        if not data[i].strip():       # blank card placeholder → skip
            continue
        # Card: lcid sf at n1 n2 n3 n4 n5  (n5 ignored)
        f1   = _card(data, i, fixed=True, n=8, w=10)
        lcid = to_int(f1[0])   if f1 else 0
        sf   = _ffield(f1, 1, 1.0)
        nodes = [to_int(f1[j]) for j in range(3, min(7, len(f1)))]
        while nodes and nodes[-1] == 0:
            nodes.pop()
        if len(nodes) >= 3 and lcid > 0:
            state.pressure_loads.append(PressureLoad(lcid, sf, nodes))


def handle_load_segment_set(block: Block, state: ConversionState) -> None:
    """*LOAD_SEGMENT_SET[_ID] → /PLOAD on the referenced *SET_SEGMENT surface.

    Card: ssid lcid sf at  (one card per loaded segment set; may repeat).
      ssid = *SET_SEGMENT id (the loaded surface)
      lcid = load curve (pressure vs time)
      sf   = curve scale factor (default 1.0)
      at   = arrival/activation time (no /PLOAD equivalent — dropped, warned)
    The segments are resolved from state.segment_sets at write time, so the
    *SET_SEGMENT may appear anywhere in the deck.
    """
    raw = block.raw
    data = raw[1:] if _has_id(block) else raw
    warned_at = False
    for i in range(len(data)):
        if not data[i].strip():           # blank card placeholder → skip
            continue
        f = _card(data, i, fixed=True, n=8, w=10)
        if not f:
            continue
        ssid = to_int(f[0])
        lcid = to_int(f[1]) if len(f) > 1 else 0
        sf   = _ffield(f, 2, 1.0)
        at   = to_float(f[3]) if len(f) > 3 else 0.0
        if ssid <= 0 or lcid <= 0:
            continue
        if at != 0.0 and not warned_at:
            state.warn(f"*{block.keyword}: arrival time AT={at:g} on segment set "
                       f"{ssid} has no /PLOAD equivalent — dropped (load applies "
                       "from t=0).")
            warned_at = True
        state.segment_set_pressure_loads.append(
            SegmentSetPressureLoad(ssid, lcid, sf))


def handle_load_gravity_part(block: Block, state: ConversionState) -> None:
    """*LOAD_GRAVITY_PART[_SET]: one data row per part (or part set).

    Card: pid dof lc accel lcdr stga stgr — DOF 1/2/3 names the X/Y/Z axis.
    The load is ACCEL × factor(t): LC is the "Load curve defining factor as a
    function of time", ACCEL is the "Acceleration (will be multiplied by factor
    from curve)", and "a constant factor of 1.0 is assumed if LC is not
    specified" (p.33-57 + Remark 1a) — so ACCEL is never dropped, whether or
    not a curve is given.

    The R16/R17 manual fixes NO sign for ACCEL anywhere in the keyword's
    section, so the direction convention is taken from the Radioss dyna-reader,
    which negates it exactly like *LOAD_BODY (``convertloads.cxx:859``:
    ``Fscale_Y = -lsdACCEL``; that file is not part of this repo, so the
    citation cannot be checked from here): a positive ACCEL loads the part
    along -X/-Y/-Z.
    _SET rows reference a *SET_PART; they are expanded to the set's parts.
    """
    is_set = "SET" in block.options or block.keyword.endswith("_SET")
    for i in range(len(block.raw)):
        if not block.raw[i].strip():      # blank card placeholder → skip
            continue
        f = _card(block.raw, i, fixed=True, n=8, w=10)
        if len(f) < 2:
            continue
        pid   = to_int(f[0])
        dof   = to_int(f[1])
        lc    = to_int(f[2])   if len(f) > 2 else 0
        accel = to_float(f[3]) if len(f) > 3 else 0.0
        lcdr  = to_int(f[4])   if len(f) > 4 else 0
        stga  = to_int(f[5])   if len(f) > 5 else 0
        stgr  = to_int(f[6])   if len(f) > 6 else 0
        if pid <= 0 or dof not in (1, 2, 3):
            continue
        pids = ([p for p in state.part_sets.get(pid, ("", []))[1]]
                if is_set else [pid])
        for p in pids:
            state.gravity_loads.append(
                GravityLoadPart(p, dof, lc, accel, lcdr, stga, stgr))


def handle_load_body(block: Block, state: ConversionState) -> None:
    """*LOAD_BODY_{X,Y,Z} → base-acceleration body load → /GRAV.

    Card: lcid sf lciddr xc yc zc cid.  The load axis is the letter in the
    keyword suffix (X/Y/Z) and the acceleration field is sf × lcid(t), acting
    along the NEGATIVE axis: a base acceleration accelerates the coordinate
    system, "and, thus, the inertial loads acting on the model are of opposite
    sign" (Manual Vol I R16 p.33-27), which the manual's own *LOAD_BODY_Z
    example annotates "Note: Positive body load acts in the negative
    direction." The writer therefore emits ``Fscale_Y = -sf``.

    Scope is the whole model unless a *LOAD_BODY_PARTS card names a part set
    (p.33-25) — see handle_load_body_parts.

    CID is a local system the acceleration is expressed in ("The accelerations
    (LCID) are with respect to CID", p.33-27) and maps to the /GRAV skew_ID;
    LCIDDR is the dynamic-relaxation curve and has no /GRAV equivalent (warned,
    like LCDR on *LOAD_GRAVITY_PART). Angular (_RX/_RY/_RZ) and generic
    (_VECTOR/_GENERALIZED) body loads have no /GRAV mapping and are skipped
    with a warning.
    """
    kw = block.keyword                       # e.g. "LOAD_BODY_Y"
    suffix = kw.rsplit("_", 1)[-1] if "_" in kw else ""
    if suffix not in ("X", "Y", "Z"):
        state.warn(f"*{kw}: only translational LOAD_BODY_X/Y/Z map to /GRAV "
                   "— skipped (rotational / generalized body loads have no "
                   "OpenRadioss /GRAV equivalent).")
        state.skipped_keywords.append(kw)
        return
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    f = _card(raw, offset, fixed=True, n=8, w=10)
    if not f:
        return
    lcid   = to_int(f[0])
    sf     = to_float(f[1]) if len(f) > 1 else 1.0
    lciddr = to_int(f[2]) if len(f) > 2 else 0
    cid    = to_int(f[6]) if len(f) > 6 else 0
    if sf == 0.0:
        sf = 1.0
    if lcid <= 0:
        state.warn(f"*{kw}: no acceleration curve (lcid={lcid}) — skipped.")
        return
    if lciddr:
        state.warn(f"*{kw}: dynamic-relaxation curve LCIDDR={lciddr} has no "
                   "OpenRadioss mapping - ignored (only the transient body "
                   "load is converted).")
    state.body_loads.append(LoadBody(dir=suffix, lcid=lcid, sf=sf, cid=cid))


def handle_load_body_parts(block: Block, state: ConversionState) -> None:
    """*LOAD_BODY_PARTS — restrict EVERY *LOAD_BODY_* row to one part set.

    Card 1b is a single field, PSID. The scoping is deck-global, not per
    *LOAD_BODY card: "This data applies to all nodes in the complete problem
    unless a part subset is specified via the *LOAD_BODY_PARTS keyword" and
    "Only one *LOAD_BODY_PARTS card is permitted per deck" (Manual Vol I R16
    p.33-25). The Radioss dyna-reader implements exactly that with a single
    ``int grnodid`` scanned in a first pass over all *LOAD_BODY cards
    (``convertloads.cxx:167-182``), so a second card overwrites the first —
    the last-wins rule kept here.

    Without this, a deck that scopes gravity to one part set used to get the
    body load on the WHOLE model, reported only as an unsupported keyword.
    """
    offset = 1 if _has_id(block) else 0
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f:
        return
    psid = to_int(f[0])
    if psid <= 0:
        state.warn("*LOAD_BODY_PARTS: no part-set id on the card — ignored "
                   "(the body load stays on the whole model).")
        return
    if state.body_load_psid and state.body_load_psid != psid:
        state.warn(
            f"*LOAD_BODY_PARTS: a second card (PSID {psid}) replaces the "
            f"earlier PSID {state.body_load_psid}. LS-DYNA permits only one "
            "such card per deck (Manual Vol I R16 p.33-25) and the Radioss "
            "dyna-reader also keeps the last one.")
    state.body_load_psid = psid


# ─────────────────────────────────────────────────────────────────────────────
# Segment sets  (used as /SURF/SEG by blast / pressure loads)
# ─────────────────────────────────────────────────────────────────────────────

def handle_set_segment(block: Block, state: ConversionState) -> None:
    """*SET_SEGMENT[_TITLE] → a set of 3/4-node surface segments → /SURF/SEG.

    Header card:  sid da1 da2 da3 da4 solver its
    Data cards :  n1 n2 n3 n4 a1 a2 a3 a4  (one segment per card; a* attributes
                  ignored). Node order fixes the segment normal (n4=0 → triangle).
    Stored on state.segment_sets for later /SURF/SEG emission.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1:
        return
    sid = to_int(f1[0])
    segments: List[List[int]] = []
    for line in raw[offset + 1:]:
        if not line.strip():
            continue
        # Node columns are fixed I10 in LS-PrePost output, but free-format
        # (space/comma) cards are equally legal — use the shared free-with-
        # fixed-fallback parse so both survive.
        f = _card([line], 0, fixed=True, n=8, w=10)
        nodes = [to_int(f[j]) for j in range(min(4, len(f)))]
        while len(nodes) > 3 and nodes[-1] == 0:
            nodes.pop()
        if len(nodes) >= 3 and all(n > 0 for n in nodes):
            segments.append(nodes)
    state.segment_sets[sid] = SegmentSet(sid, title, segments)


# ─────────────────────────────────────────────────────────────────────────────
# Blast loads
# ─────────────────────────────────────────────────────────────────────────────

def _blast_unit_system(unit: int):
    """Map a *LOAD_BLAST_ENHANCED UNIT flag to an OpenRadioss (mass, length,
    time) label triple for /BEGIN, or None when it has no clean mapping.

    UNIT table (LSTC — L. Slavik, "Blast Loading in LS-DYNA"):
      1 = the original CONWEP *inconsistent* system ("do not use for analysis")
      2 = kilogram, metre, second, Pascal
      3 = "dozen slugs", inch, second, psi           (English)
      4 = gram, centimetre, microsecond, megabar
      5 = user-defined (CFM/CFL/CFT/CFP conversion factors)
    The TM5-1300 empirical formula is unit-dependent, so /LOAD/PBLAST reads the
    /BEGIN unit labels to convert its internal {cm, g, µs} data to model units —
    those labels must therefore match the deck's real units. Only the physically
    consistent SI-family flags get an automatic mapping.
    """
    return {
        2: ("kg", "m", "s"),
        4: ("g", "cm", "micros"),
    }.get(unit)


def handle_load_blast_enhanced(block: Block, state: ConversionState) -> None:
    """*LOAD_BLAST_ENHANCED → a blast source for /LOAD/PBLAST.

    Card 1: bid m xbo ybo zbo tbo unit blast
    Card 2: cfm cfl cft cfp nidbo death negphs
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if len(f1) < 2:
        state.warn("*LOAD_BLAST_ENHANCED: incomplete Card 1 — skipped")
        return
    bid   = to_int(f1[0])
    m     = to_float(f1[1])
    xbo   = to_float(f1[2]) if len(f1) > 2 else 0.0
    ybo   = to_float(f1[3]) if len(f1) > 3 else 0.0
    zbo   = to_float(f1[4]) if len(f1) > 4 else 0.0
    tbo   = to_float(f1[5]) if len(f1) > 5 else 0.0
    unit  = to_int(f1[6])   if len(f1) > 6 else 2
    blast = to_int(f1[7])   if len(f1) > 7 else 1
    # Card 2: cfm cfl cft cfp nidbo death negphs
    f2     = _card(raw, offset + 1, fixed=True, n=8, w=10)
    death  = to_float(f2[5]) if len(f2) > 5 else 1e20
    negphs = to_int(f2[6])   if len(f2) > 6 else 0
    state.blast_sources[bid] = LoadBlastEnhanced(
        bid=bid, m=m, xbo=xbo, ybo=ybo, zbo=zbo, tbo=tbo,
        unit=unit, blast=blast, death=death, negphs=negphs,
    )
    us = _blast_unit_system(unit)
    if us is not None:
        state.blast_unit_system = us
    else:
        state.warn(
            f"*LOAD_BLAST_ENHANCED bid={bid}: UNIT={unit} has no automatic "
            "OpenRadioss unit mapping (only UNIT=2 kg/m/s and UNIT=4 g/cm/µs "
            "are auto-mapped). The TM5-1300 blast formula is unit-dependent, so "
            "set /BEGIN to the deck's real mass/length/time via convert("
            "units=...) or /LOAD/PBLAST will compute wrong pressures.")


def handle_load_blast_segment_set(block: Block, state: ConversionState) -> None:
    """*LOAD_BLAST_SEGMENT_SET → apply blast source `bid` to segment set `ssid`.

    Card: bid ssid alepid sfnrb scalep
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    for i in range(offset, len(raw)):
        if not raw[i].strip():
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 2:
            continue
        bid    = to_int(f[0])
        ssid   = to_int(f[1])
        alepid = to_int(f[2])   if len(f) > 2 else 0
        sfnrb  = to_float(f[3]) if len(f) > 3 else 0.0
        scalep = to_float(f[4]) if len(f) > 4 else 1.0
        state.blast_segment_loads.append(
            LoadBlastSegmentSet(bid, ssid, alepid, sfnrb, scalep))


def handle_load_blast(block: Block, state: ConversionState) -> None:
    """*LOAD_BLAST (legacy CONWEP) → a single blast source for /LOAD/PBLAST.

    Card 1: wgt xbo ybo zbo tbo iunit isurf
    Card 2: cfm cfl cft cfp nidbo death negphs   (optional)

    The original *LOAD_BLAST carries no BID (there is one implicit charge), so a
    synthetic bid is assigned and ``blast = isurf`` is stored, letting it flow
    through the shipped /LOAD/PBLAST writer exactly like *LOAD_BLAST_ENHANCED.
    The loaded segments come from a following *LOAD_BLAST_SEGMENT[_SET]. The
    legacy surface/air flag numbering differs from *LOAD_BLAST_ENHANCED, so the
    burst type is flagged for the user to verify.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    f = _card(raw, offset, fixed=True, n=8, w=10)
    if not f or f[0].strip() == "":
        state.warn("*LOAD_BLAST: incomplete Card 1 — skipped")
        return
    wgt   = to_float(f[0])
    xbo   = to_float(f[1]) if len(f) > 1 else 0.0
    ybo   = to_float(f[2]) if len(f) > 2 else 0.0
    zbo   = to_float(f[3]) if len(f) > 3 else 0.0
    tbo   = to_float(f[4]) if len(f) > 4 else 0.0
    iunit = to_int(f[5])   if len(f) > 5 else 2
    isurf = to_int(f[6])   if len(f) > 6 else 2
    f2     = _card(raw, offset + 1, fixed=True, n=8, w=10)
    death  = to_float(f2[5]) if len(f2) > 5 else 1e20
    negphs = to_int(f2[6])   if len(f2) > 6 else 0
    bid = state.next_id()
    state.blast_sources[bid] = LoadBlastEnhanced(
        bid=bid, m=wgt, xbo=xbo, ybo=ybo, zbo=zbo, tbo=tbo,
        unit=iunit, blast=isurf, death=death, negphs=negphs)
    us = _blast_unit_system(iunit)
    if us is not None:
        state.blast_unit_system = us
    else:
        state.warn(
            f"*LOAD_BLAST: IUNIT={iunit} has no automatic OpenRadioss unit "
            "mapping (only 2 kg/m/s and 4 g/cm/µs are auto-mapped); set /BEGIN "
            "via convert(units=...) or /LOAD/PBLAST pressures will be wrong.")
    state.warn(
        "*LOAD_BLAST (legacy) mapped to /LOAD/PBLAST with Exp_data from ISURF="
        f"{isurf} — the legacy surface/air-burst flag numbering differs from "
        "*LOAD_BLAST_ENHANCED; verify the burst type (surface vs free-air).")


def handle_load_blast_segment(block: Block, state: ConversionState) -> None:
    """*LOAD_BLAST_SEGMENT → apply a blast source to ad-hoc segments (N1..N4).

    Card (one per segment): bid n1 n2 n3 n4. Unlike *LOAD_BLAST_SEGMENT_SET
    (which names a *SET_SEGMENT), this lists the segment nodes inline. Segments
    are grouped by bid into a synthesized segment set so the shipped /SURF/SEG +
    /LOAD/PBLAST writer is reused. bid=0 / an unmatched bid falls back at write
    time to the sole blast source when there is exactly one.
    """
    raw = block.raw
    offset = 1 if _has_id(block) else 0
    by_bid: dict = {}
    for i in range(offset, len(raw)):
        if not raw[i].strip():
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if len(f) < 4:
            continue
        bid = to_int(f[0])
        nodes = [to_int(f[j]) for j in range(1, 5)]
        while len(nodes) > 3 and nodes[-1] == 0:
            nodes.pop()
        if len(nodes) >= 3 and all(n > 0 for n in nodes):
            by_bid.setdefault(bid, []).append(nodes)
    for bid, segs in by_bid.items():
        ssid = state.next_id()
        state.segment_sets[ssid] = SegmentSet(ssid, f"blast_seg_bid{bid}", segs)
        state.blast_segment_loads.append(LoadBlastSegmentSet(bid, ssid))


def handle_mat_add_fatigue(block: Block, state: ConversionState) -> None:
    """*MAT_ADD_FATIGUE: S-N data per material — offline post-processing only.

    Card: mid lcid ltype a b sthres snlimt sntype.  No OpenRadioss equivalent;
    tools/modal_random_response.py consumes it for Dirlik fatigue damage.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f:
        return
    mid = to_int(f[0])
    if mid == 0:
        return
    state.mat_add_fatigue[mid] = MatAddFatigue(
        mid=mid,
        lcid=to_int(f[1])     if len(f) > 1 else 0,
        ltype=to_int(f[2])    if len(f) > 2 else 0,
        a=to_float(f[3])      if len(f) > 3 else 0.0,
        b=to_float(f[4])      if len(f) > 4 else 0.0,
        sthres=to_float(f[5]) if len(f) > 5 else 0.0,
        snlimt=to_int(f[6])   if len(f) > 6 else 0,
        sntype=to_int(f[7])   if len(f) > 7 else 0,
    )


def _handle_db_freq_binary(block: Block, state: ConversionState, kind: str) -> None:
    """*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG.

    Card 1: binary … psetid.  D3PSD adds Card 2: fmin fmax nfreq fspace lcfreq
    (deck frequency units — cycles per time-unit).  Stored for the offline
    random-vibration post-processor; OpenRadioss has no equivalent database.
    """
    raw = block.raw
    f1 = _card(raw, 0, fixed=True, n=8, w=10) if raw else []
    req = DbFreqBinary(
        kind=kind,
        binary=to_int(f1[0], 1) if f1 else 1,
        psetid=to_int(f1[4])    if len(f1) > 4 else 0,
    )
    if kind == "D3PSD" and len(raw) > 1:
        f2 = _card(raw, 1, fixed=True, n=8, w=10)
        req.fmin   = to_float(f2[0]) if f2 else 0.0
        req.fmax   = to_float(f2[1]) if len(f2) > 1 else 0.0
        req.nfreq  = to_int(f2[2])   if len(f2) > 2 else 0
        req.fspace = to_int(f2[3])   if len(f2) > 3 else 0
        req.lcfreq = to_int(f2[4])   if len(f2) > 4 else 0
    state.db_freq_binary[kind] = req


def handle_database_frequency_binary_d3psd(block: Block, state: ConversionState) -> None:
    _handle_db_freq_binary(block, state, "D3PSD")


def handle_database_frequency_binary_d3rms(block: Block, state: ConversionState) -> None:
    _handle_db_freq_binary(block, state, "D3RMS")


def handle_database_frequency_binary_d3ftg(block: Block, state: ConversionState) -> None:
    _handle_db_freq_binary(block, state, "D3FTG")


def handle_define_transformation(block: Block, state: ConversionState) -> None:
    """*DEFINE_TRANSFORMATION is consumed at parse time (k2rad.assembly): its
    option rows are composed into the affine transform that is applied
    numerically to *INCLUDE_TRANSFORM / *NODE_TRANSFORM geometry before
    dispatch. Nothing to convert here — the handler exists so the keyword is
    not reported as skipped."""


def handle_node_transform(block: Block, state: ConversionState) -> None:
    """*NODE_TRANSFORM is applied numerically at parse time (k2rad.assembly):
    the referenced node set's coordinates are already transformed when this
    block reaches dispatch."""


def handle_skip(block: Block, state: ConversionState) -> None:
    state.skipped_keywords.append(block.keyword)


# ─────────────────────────────────────────────────────────────────────────────
# Database / output requests
# ─────────────────────────────────────────────────────────────────────────────

def handle_database_binary_d3plot(block: Block, state: ConversionState) -> None:
    # *DATABASE_BINARY_D3PLOT card 1 fields (LS-DYNA, 10-char each):
    #   f[0]=DT/CYCL  f[1]=LCDT/NR  f[2]=BEAM  f[3]=NPLTC  f[4]=PSETID
    # NPLTC (number of plot states) is the 4th field, index 3 — reading f[4]
    # picked up PSETID instead, leaving npltc=0 for NPLTC-driven decks so the
    # writer's /ANIM/DT wrongly fell back to endtim/40 instead of endtim/npltc.
    # DT and NPLTC are read from ONE reading of the line (_db_fields), on the
    # same rule as every other *DATABASE_* card. Slicing this card strict
    # fixed-width silently zeroed any DT wider than 10 columns — and
    # '1.000000E-05' is 12 — which set the animation interval to 0, i.e. the
    # writer fell back to endtim/40 instead of the interval the deck asked for.
    raw = block.raw
    f = _db_fields(raw[0], n=8) if raw else []
    dt    = _handle_db_dt(block, state, "*DATABASE_BINARY_D3PLOT")
    npltc = to_int(f[3])   if len(f) > 3 else 0
    state.db_d3plot = DbD3Plot(dt, npltc)


def handle_database_elout(block: Block, state: ConversionState) -> None:
    state.db_elout_dt = _handle_db_dt(block, state, "*DATABASE_ELOUT")
    if state.db_elout_dt:
        state.note_recognized_not_emitted(
            "DATABASE_ELOUT",
            "no per-element /TH block is emitted for it — k2rad writes "
            "/TH/SHEL, /TH/BRIC and /TH/BEAM only for elements a "
            "*DATABASE_HISTORY_{SHELL,SOLID,BEAM} names. The dt is honoured as "
            "the /TFILE frequency. Add *DATABASE_HISTORY_* to pick elements.")


def handle_database_glstat(block: Block, state: ConversionState) -> None:
    state.db_glstat_dt = _handle_db_dt(block, state, "*DATABASE_GLSTAT")
    if state.db_glstat_dt:
        state.note_recognized_not_emitted(
            "DATABASE_GLSTAT",
            "no dedicated card exists or is needed — OpenRadioss writes the "
            "global energy/statistics balance to the .out and T01 files "
            "automatically. The dt is honoured as the /TFILE frequency, so "
            "the data IS produced; it just is not driven by a converted card.")


def _handle_db_history(block: Block, state: ConversionState, db_type: str) -> None:
    ids: List[int] = []
    for line in block.raw:
        for tok in parse_free(line):
            v = to_int(tok)
            if v > 0:
                ids.append(v)
    state.db_histories.append(DbHistory(db_type, ids))


def handle_database_history_shell(block: Block, state: ConversionState) -> None:
    _handle_db_history(block, state, "SHELL")


def handle_database_history_solid(block: Block, state: ConversionState) -> None:
    _handle_db_history(block, state, "SOLID")


def handle_database_history_node(block: Block, state: ConversionState) -> None:
    _handle_db_history(block, state, "NODE")


def handle_damping_global(block: Block, state: ConversionState) -> None:
    """*DAMPING_GLOBAL: mass-proportional Rayleigh damping (LS-DYNA Manual Vol I).

    Card: lcid valdmp stx sty stz srx sry srz
    Only one *DAMPING_GLOBAL active at a time per LS-DYNA; last one wins.
    """
    raw = block.raw
    offset = _title_offset(block)
    f = _card(raw, offset, fixed=False, n=8, w=10)
    if not f:
        state.warn("*DAMPING_GLOBAL: no data card found — skipped")
        return
    lcid   = to_int(f[0]) if len(f) > 0 else 0
    valdmp = to_float(f[1]) if len(f) > 1 else 0.0
    stx = to_float(f[2]) if len(f) > 2 else 0.0
    sty = to_float(f[3]) if len(f) > 3 else 0.0
    stz = to_float(f[4]) if len(f) > 4 else 0.0
    srx = to_float(f[5]) if len(f) > 5 else 0.0
    sry = to_float(f[6]) if len(f) > 6 else 0.0
    srz = to_float(f[7]) if len(f) > 7 else 0.0
    if lcid > 0:
        state.warn(
            f"*DAMPING_GLOBAL: lcid={lcid} (time-varying damping) not supported; "
            f"using constant valdmp={valdmp}"
        )
    state.damping_global = DampingGlobal(
        valdmp=valdmp, lcid=lcid,
        stx=stx, sty=sty, stz=stz, srx=srx, sry=sry, srz=srz,
    )


def handle_damping_part_stiffness(block: Block, state: ConversionState) -> None:
    """*DAMPING_PART_STIFFNESS: stiffness-proportional damping per part.

    Card: pid coef
    Multiple parts allowed; each adds one entry.
    """
    raw = block.raw
    offset = _title_offset(block)
    # May have multiple data cards (one per part); read until blank/EOB
    for i in range(offset, len(raw)):
        line = raw[i].strip()
        if not line or line.startswith("$"):
            continue
        f = _card(raw, i, fixed=False, n=2, w=10)
        if not f or len(f) < 1:
            continue
        pid = to_int(f[0])
        coef = to_float(f[1]) if len(f) > 1 else 0.0
        if pid > 0:
            state.damping_part_stiffness.append(DampingPartStiffness(pid=pid, coef=coef))


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table
# ─────────────────────────────────────────────────────────────────────────────

HANDLERS = {
    "KEYWORD":                                handle_keyword,
    "TITLE":                                  handle_title,
    "END":                                    handle_end,

    # Mesh
    "NODE":                                   handle_node,
    # *ELEMENT_SHELL / *ELEMENT_BEAM: every legal option spelling is registered
    # from the grammar just below this dict, and dispatch() additionally routes
    # any UNLISTED *ELEMENT_SHELL*/_BEAM*/PLOTEL* spelling to the same handler,
    # so no suffix can ever take a block's elements with it.
    "ELEMENT_SHELL":                          handle_element_shell,
    "ELEMENT_SOLID":                          handle_element_solid,
    "ELEMENT_BEAM":                           handle_element_beam,
    # *ELEMENT_PLOTEL is a visualization-only line element with no PID column
    # → an inert /SPRING on a synthesized PLOTEL /PART + /PROP/TYPE4.
    "ELEMENT_PLOTEL":                         handle_element_plotel,
    "PART":                                   handle_part,
    # *PART_COMPOSITE carries its own per-ply layup instead of a *SECTION
    # reference → /PROP/TYPE51 + one /PROP/TYPE19 per ply. Every OPTION1/2/3
    # spelling needs its own key (dispatch is an exact dict lookup and only
    # _ID/_TITLE/_SUBTITLE are stripped); the handler reads block.keyword to
    # pick the card layout. All twelve are registered from the option grammar
    # just below this dict — including _TSHELL / _IGA_SHELL, so the *PART
    # record still lands and the part keeps its mesh (the property then falls
    # back to a plain shell — see the handler).
    "HOURGLASS":                              handle_hourglass,

    # Sections
    "SECTION_SHELL":                          handle_section_shell,
    "SECTION_SOLID":                          handle_section_solid,
    "SECTION_BEAM":                           handle_section_beam,
    "SECTION_DISCRETE":                       handle_section_discrete,

    # Materials
    "MAT_ELASTIC":                            handle_mat_elastic,
    "MAT_PIECEWISE_LINEAR_PLASTICITY":        handle_mat_piecewise_linear_plasticity,
    "MAT_024":                                handle_mat_piecewise_linear_plasticity,
    "MAT_24":                                 handle_mat_piecewise_linear_plasticity,
    # _LOG_INTERPOLATION and _2D are MAT_024 keyword options (combinable, any
    # order) that change only the strain-rate-table semantics → same handler,
    # F_smooth=2 for the log form. _split_keyword keeps these suffixes intact.
    "MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION":    handle_mat_piecewise_linear_plasticity,
    "MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION_2D": handle_mat_piecewise_linear_plasticity,
    "MAT_PIECEWISE_LINEAR_PLASTICITY_2D":     handle_mat_piecewise_linear_plasticity,
    "MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY": handle_mat_piecewise_linear_plasticity,
    "MAT_123":                                handle_mat_piecewise_linear_plasticity,
    "MAT_PLASTIC_KINEMATIC":                  handle_mat_plastic_kinematic,
    # Johnson-Cook family: MAT_015 → /MAT/LAW2 (or /MAT/LAW4 + /EOS when the
    # part attaches an EOS); MAT_099 → /MAT/LAW2 + /FAIL/FLD; MAT_098 keeps its
    # sampled /MAT/LAW36 path (registered further down with the numeric aliases
    # added here).
    "MAT_JOHNSON_COOK":                       handle_mat_johnson_cook,
    "MAT_015":                                handle_mat_johnson_cook,
    "MAT_15":                                 handle_mat_johnson_cook,
    "MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE":
        handle_mat_simplified_johnson_cook_ortho,
    "MAT_099":                                handle_mat_simplified_johnson_cook_ortho,
    "MAT_99":                                 handle_mat_simplified_johnson_cook_ortho,
    "MAT_098":                                handle_mat_simplified_johnson_cook,
    "MAT_98":                                 handle_mat_simplified_johnson_cook,
    # *MAT_ANISOTROPIC_VISCOPLASTIC (103) → /MAT/LAW36 (isotropic reduction;
    # Hill anisotropy + kinematic hardening dropped/folded — see the handler)
    "MAT_ANISOTROPIC_VISCOPLASTIC":           handle_mat_anisotropic_viscoplastic,
    "MAT_103":                                handle_mat_anisotropic_viscoplastic,

    # ── Composites ──────────────────────────────────────────────────────────
    # MAT_002 ORTHO dialect → /MAT/LAW93. The ANIS dialect is a DIFFERENT card
    # layout (the 6x6 C-matrix) with no LAW93 home — its own handler, which
    # warns and emits nothing rather than dyna2rad's silent zero-modulus law.
    "MAT_ORTHOTROPIC_ELASTIC":                handle_mat_orthotropic_elastic,
    "MAT_002":                                handle_mat_orthotropic_elastic,
    "MAT_2":                                  handle_mat_orthotropic_elastic,
    "MAT_ANISOTROPIC_ELASTIC":                handle_mat_anisotropic_elastic,
    "MAT_002_ANIS":                           handle_mat_anisotropic_elastic,
    "MAT_2_ANIS":                             handle_mat_anisotropic_elastic,
    # MAT_054/055 → /MAT/LAW127 (+ /FAIL/GENE1 when TFAIL is a dt criterion).
    # CRIT on card 6 selects Chang-Chang (54) vs Tsai-Wu (55) independently of
    # the keyword spelling, so both spellings share one handler.
    "MAT_ENHANCED_COMPOSITE_DAMAGE":          handle_mat_enhanced_composite_damage,
    "MAT_054":                                handle_mat_enhanced_composite_damage,
    "MAT_54":                                 handle_mat_enhanced_composite_damage,
    "MAT_055":                                handle_mat_enhanced_composite_damage,
    "MAT_55":                                 handle_mat_enhanced_composite_damage,
    # MAT_037 (+ the _ECHANGE / _NLP_FAILURE / _NLP2 option variants) → LAW43
    "MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC":
        handle_mat_transversely_anisotropic,
    "MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC_ECHANGE":
        handle_mat_transversely_anisotropic,
    "MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC_NLP_FAILURE":
        handle_mat_transversely_anisotropic,
    "MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC_NLP2":
        handle_mat_transversely_anisotropic,
    "MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC_ECHANGE_NLP_FAILURE":
        handle_mat_transversely_anisotropic,
    "MAT_037":                                handle_mat_transversely_anisotropic,
    "MAT_37":                                 handle_mat_transversely_anisotropic,
    # MAT_032 → a synthesized /MAT/PLAS_BRIT (LAW27) glass + polymer PAIR
    "MAT_LAMINATED_GLASS":                    handle_mat_laminated_glass,
    "MAT_032":                                handle_mat_laminated_glass,
    "MAT_32":                                 handle_mat_laminated_glass,
    "MAT_RIGID":                              handle_mat_rigid,
    "MAT_NULL":                               handle_mat_null,
    "MAT_POWER_LAW_PLASTICITY":               handle_mat_power_law_plasticity,
    # Foam / honeycomb families
    "MAT_CRUSHABLE_FOAM":                     handle_mat_crushable_foam,
    "MAT_63":                                 handle_mat_crushable_foam,
    "MAT_063":                                handle_mat_crushable_foam,
    "MAT_LOW_DENSITY_FOAM":                   handle_mat_low_density_foam,
    "MAT_57":                                 handle_mat_low_density_foam,
    "MAT_057":                                handle_mat_low_density_foam,
    "MAT_FU_CHANG_FOAM":                      handle_mat_fu_chang_foam,
    "MAT_83":                                 handle_mat_fu_chang_foam,
    "MAT_083":                                handle_mat_fu_chang_foam,
    "MAT_HONEYCOMB":                          handle_mat_honeycomb,
    "MAT_26":                                 handle_mat_honeycomb,
    "MAT_026":                                handle_mat_honeycomb,
    # Hyperelastic rubber batch: MAT_007 → LAW42 fixed form; MAT_027 → LAW42 or
    # LAW69 (LCID); MAT_077_O → LAW42 (embedded Prony) or LAW69; MAT_077_H →
    # LAW95 + /VISC/PRONY or LAW69. Underscore spellings of the hyphenated
    # names are accepted too (hand-edited decks).
    "MAT_BLATZ-KO_RUBBER":                    handle_mat_blatz_ko,
    "MAT_BLATZ_KO_RUBBER":                    handle_mat_blatz_ko,
    "MAT_007":                                handle_mat_blatz_ko,
    "MAT_7":                                  handle_mat_blatz_ko,
    "MAT_MOONEY-RIVLIN_RUBBER":               handle_mat_mooney_rivlin,
    "MAT_MOONEY_RIVLIN_RUBBER":               handle_mat_mooney_rivlin,
    "MAT_027":                                handle_mat_mooney_rivlin,
    "MAT_27":                                 handle_mat_mooney_rivlin,
    "MAT_OGDEN_RUBBER":                       handle_mat_ogden_rubber,
    "MAT_077_O":                              handle_mat_ogden_rubber,
    "MAT_77_O":                               handle_mat_ogden_rubber,
    "MAT_HYPERELASTIC_RUBBER":                handle_mat_hyperelastic_rubber,
    "MAT_077_H":                              handle_mat_hyperelastic_rubber,
    "MAT_77_H":                               handle_mat_hyperelastic_rubber,
    "INITIAL_FOAM_REFERENCE_GEOMETRY":        handle_initial_foam_reference_geometry,
    "INITIAL_FOAM_REFERENCE_GEOMETRY_RAMP":   handle_initial_foam_reference_geometry,
    # Discrete-element (spring/damper) materials + spotwelds → /SPRING connectors
    "MAT_SPRING_ELASTIC":                     handle_mat_spring_elastic,
    "MAT_S01":                                handle_mat_spring_elastic,
    "MAT_SPRING_NONLINEAR_ELASTIC":           handle_mat_spring_nonlinear_elastic,
    "MAT_S04":                                handle_mat_spring_nonlinear_elastic,
    "MAT_DAMPER_VISCOUS":                     handle_mat_damper_viscous,
    "MAT_D01":                                handle_mat_damper_viscous,
    "MAT_SPOTWELD":                           handle_mat_spotweld,
    "MAT_100":                                handle_mat_spotweld,
    "MAT_187":                                handle_mat_187,
    "MAT_SAMP-1":                             handle_mat_187,
    "MAT_ADD_DAMAGE_GISSMO":                  handle_mat_add_damage_gissmo,
    # High explosive + equations of state (coupled ALE / JWL detonation)
    "MAT_HIGH_EXPLOSIVE_BURN":                handle_mat_high_explosive_burn,
    "EOS_JWL":                                handle_eos_jwl,
    "EOS_LINEAR_POLYNOMIAL":                  handle_eos_linear_polynomial,
    "EOS_GRUNEISEN":                          handle_eos_gruneisen,
    "EOS_IDEAL_GAS":                          handle_eos_ideal_gas,

    # Definitions
    "DEFINE_CURVE":                           handle_define_curve,
    "DEFINE_CURVE_FUNCTION":                  handle_define_curve_function,
    "DEFINE_TABLE":                           handle_define_table,
    "DEFINE_TABLE_2D":                        handle_define_table_2d,
    "DEFINE_COORDINATE_SYSTEM":               handle_define_coordinate_system,
    "DEFINE_COORDINATE_NODES":                handle_define_coordinate_nodes,
    "DEFINE_COORDINATE_VECTOR":               handle_define_coordinate_vector,
    "DEFINE_VECTOR":                          handle_define_vector,
    "DEFINE_VECTOR_NODES":                    handle_define_vector,
    "DEFINE_SD_ORIENTATION":                  handle_define_sd_orientation,
    "DEFINE_BOX":                             handle_define_box,
    "DEFINE_BOX_LOCAL":                       handle_define_box,
    # Assembly transforms — consumed at parse time (k2rad.assembly); the
    # no-op handlers keep them out of skipped_keywords.
    "DEFINE_TRANSFORMATION":                  handle_define_transformation,
    "NODE_TRANSFORM":                         handle_node_transform,

    # Sets
    "SET_NODE_LIST":                          handle_set_node_list,
    "SET_NODE":                               handle_set_node_list,
    "SET_PART_LIST":                          handle_set_part_list,
    "SET_PART":                               handle_set_part_list,
    "SET_SHELL_LIST":                         handle_set_shell_list,
    "SET_SHELL":                              handle_set_shell_list,
    "SET_SOLID_LIST":                         handle_set_solid_list,
    "SET_SOLID":                              handle_set_solid_list,
    "SET_BEAM_LIST":                          handle_set_beam_list,
    "SET_BEAM":                               handle_set_beam_list,

    # Boundary conditions
    "BOUNDARY_SPC_SET":                       handle_boundary_spc_set,
    "BOUNDARY_SPC_NODE":                      handle_boundary_spc_node,
    "BOUNDARY_SPC":                           handle_boundary_spc_node,
    "BOUNDARY_PRESCRIBED_MOTION_RIGID":       handle_boundary_prescribed_motion_rigid,
    "BOUNDARY_PRESCRIBED_MOTION_SET":         handle_boundary_prescribed_motion_set,
    "BOUNDARY_PRESCRIBED_MOTION_NODE":        handle_boundary_prescribed_motion_node,
    "INITIAL_VELOCITY":                       handle_initial_velocity,
    "INITIAL_VELOCITY_NODE":                  handle_initial_velocity_node,
    "INITIAL_VELOCITY_RIGID_BODY":            handle_initial_velocity_rigid_body,
    "INITIAL_VELOCITY_GENERATION":            handle_initial_velocity_generation,
    "INITIAL_DETONATION":                     handle_initial_detonation,
    "INITIAL_VOLUME_FRACTION_GEOMETRY":       handle_initial_volume_fraction_geometry,
    # Coupled ALE / fluid-structure coupling / boundaries
    "ALE_MULTI-MATERIAL_GROUP":               handle_ale_multi_material_group,
    "CONSTRAINED_LAGRANGE_IN_SOLID":          handle_constrained_lagrange_in_solid,
    "BOUNDARY_NON_REFLECTING":                handle_boundary_non_reflecting,
    "CONTROL_ALE":                            handle_control_ale,

    # Constraints
    "CONSTRAINED_NODAL_RIGID_BODY":           handle_constrained_nodal_rigid_body,
    "CONSTRAINED_NODAL_RIGID_BODY_SPC":       handle_constrained_nodal_rigid_body,
    "CONSTRAINED_EXTRA_NODES_NODE":           handle_constrained_extra_nodes,
    "CONSTRAINED_EXTRA_NODES_SET":            handle_constrained_extra_nodes,
    "CONSTRAINED_RIGID_BODIES":               handle_constrained_rigid_bodies,
    "CONSTRAINED_SPOTWELD":                   handle_constrained_spotweld,
    "CONSTRAINED_SPOTWELD_FILTERED_FORCE":    handle_constrained_spotweld,
    "CONSTRAINED_GENERALIZED_WELD_SPOT":      handle_constrained_generalized_weld_spot,

    # Joints. _ID/_TITLE come free via parser._split_keyword; _LOCAL and
    # _FAILURE stay in the base name and need their own literal keys (the same
    # rule *DEFINE_BOX_LOCAL follows). Registering exact keywords is also the
    # guard against dyna2rad's substring misclassification: the motor / gears /
    # rack-and-pinion / pulley / screw / constant-velocity joints are absent
    # here, so *CONSTRAINED_JOINT_TRANSLATIONAL_MOTOR cannot be read as a plain
    # TRANSLATIONAL joint — it lands in skipped_keywords instead.
    "CONSTRAINED_JOINT_SPHERICAL":                 handle_constrained_joint,
    "CONSTRAINED_JOINT_SPHERICAL_LOCAL":           handle_constrained_joint,
    "CONSTRAINED_JOINT_SPHERICAL_FAILURE":         handle_constrained_joint,
    "CONSTRAINED_JOINT_SPHERICAL_LOCAL_FAILURE":   handle_constrained_joint,
    "CONSTRAINED_JOINT_REVOLUTE":                  handle_constrained_joint,
    "CONSTRAINED_JOINT_REVOLUTE_LOCAL":            handle_constrained_joint,
    "CONSTRAINED_JOINT_REVOLUTE_FAILURE":          handle_constrained_joint,
    "CONSTRAINED_JOINT_REVOLUTE_LOCAL_FAILURE":    handle_constrained_joint,
    "CONSTRAINED_JOINT_CYLINDRICAL":               handle_constrained_joint,
    "CONSTRAINED_JOINT_CYLINDRICAL_LOCAL":         handle_constrained_joint,
    "CONSTRAINED_JOINT_CYLINDRICAL_FAILURE":       handle_constrained_joint,
    "CONSTRAINED_JOINT_CYLINDRICAL_LOCAL_FAILURE": handle_constrained_joint,
    "CONSTRAINED_JOINT_PLANAR":                    handle_constrained_joint,
    "CONSTRAINED_JOINT_PLANAR_LOCAL":              handle_constrained_joint,
    "CONSTRAINED_JOINT_PLANAR_FAILURE":            handle_constrained_joint,
    "CONSTRAINED_JOINT_PLANAR_LOCAL_FAILURE":      handle_constrained_joint,
    "CONSTRAINED_JOINT_UNIVERSAL":                 handle_constrained_joint,
    "CONSTRAINED_JOINT_UNIVERSAL_LOCAL":           handle_constrained_joint,
    "CONSTRAINED_JOINT_UNIVERSAL_FAILURE":         handle_constrained_joint,
    "CONSTRAINED_JOINT_UNIVERSAL_LOCAL_FAILURE":   handle_constrained_joint,
    "CONSTRAINED_JOINT_TRANSLATIONAL":                 handle_constrained_joint,
    "CONSTRAINED_JOINT_TRANSLATIONAL_LOCAL":           handle_constrained_joint,
    "CONSTRAINED_JOINT_TRANSLATIONAL_FAILURE":         handle_constrained_joint,
    "CONSTRAINED_JOINT_TRANSLATIONAL_LOCAL_FAILURE":   handle_constrained_joint,
    "CONSTRAINED_JOINT_LOCKING":                   handle_constrained_joint,
    "CONSTRAINED_JOINT_LOCKING_LOCAL":             handle_constrained_joint,
    "CONSTRAINED_JOINT_LOCKING_FAILURE":           handle_constrained_joint,
    "CONSTRAINED_JOINT_LOCKING_LOCAL_FAILURE":     handle_constrained_joint,
    "CONSTRAINED_JOINT_STIFFNESS_GENERALIZED":     handle_constrained_joint_stiffness,
    "CONSTRAINED_JOINT_STIFFNESS_TRANSLATIONAL":   handle_constrained_joint_stiffness,
    "CONSTRAINED_JOINT_STIFFNESS_FLEXION-TORSION": handle_constrained_joint_stiffness,
    "CONSTRAINED_JOINT_STIFFNESS_CYLINDRICAL":     handle_constrained_joint_stiffness,

    # Rigid walls (LS-DYNA option order: _ORTHO _FINITE _MOVING _FORCES)
    "RIGIDWALL_PLANAR":                       handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_FORCES":                handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_MOVING":                handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_MOVING_FORCES":         handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_FINITE":                handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_FINITE_FORCES":         handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_FINITE_MOVING":         handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_FINITE_MOVING_FORCES":  handle_rigidwall_planar,
    "RIGIDWALL_PLANAR_ORTHO":                 handle_rigidwall_ortho,
    "RIGIDWALL_PLANAR_ORTHO_FORCES":          handle_rigidwall_ortho,
    "RIGIDWALL_PLANAR_ORTHO_FINITE":          handle_rigidwall_ortho,
    "RIGIDWALL_PLANAR_ORTHO_MOVING":          handle_rigidwall_ortho,
    "RIGIDWALL_PLANAR_ORTHO_FINITE_MOVING":   handle_rigidwall_ortho,

    # Discrete (spring/damper) elements
    "ELEMENT_DISCRETE":                       handle_element_discrete,

    # Mass / inertia additions
    "ELEMENT_MASS":                           handle_element_mass,
    "ELEMENT_MASS_NODE_SET":                  handle_element_mass_node_set,
    "ELEMENT_MASS_PART":                      handle_element_mass_part,
    "ELEMENT_MASS_PART_SET":                  handle_element_mass_part_set,

    # Contacts
    "CONTACT_AUTOMATIC_SINGLE_SURFACE":       handle_contact_automatic_single_surface,
    "CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR": handle_contact_automatic_single_surface,
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE":   handle_contact_automatic_surface_to_surface,
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK": handle_contact_tiebreak,
    "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK": handle_contact_tiebreak,
    "CONTACT_TIEBREAK_SURFACE_TO_SURFACE":    handle_contact_tiebreak,
    "CONTACT_TIEBREAK_NODES_TO_SURFACE":      handle_contact_tiebreak,
    "CONTACT_AUTOMATIC_GENERAL":              handle_contact_automatic_general,
    "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE": handle_contact_automatic_surface_to_surface,
    "CONTACT_FORCE_TRANSDUCER_PENALTY":        handle_contact_force_transducer,
    "CONTACT_FORCE_TRANSDUCER":                handle_contact_force_transducer,
    # Tied (glued) contacts → /INTER/TYPE2
    "CONTACT_TIED_NODES_TO_SURFACE":                    handle_contact_tied,
    "CONTACT_TIED_NODES_TO_SURFACE_OFFSET":             handle_contact_tied,
    "CONTACT_TIED_NODES_TO_SURFACE_CONSTRAINED_OFFSET": handle_contact_tied,
    "CONTACT_TIED_SURFACE_TO_SURFACE":                  handle_contact_tied,
    "CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET":           handle_contact_tied,
    "CONTACT_TIED_SURFACE_TO_SURFACE_CONSTRAINED_OFFSET": handle_contact_tied,
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE":               handle_contact_tied,
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE_OFFSET":        handle_contact_tied,
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE_BEAM_OFFSET":   handle_contact_tied,
    "CONTACT_TIED_SHELL_EDGE_TO_SURFACE_CONSTRAINED_OFFSET": handle_contact_tied,

    # Control
    "CONTROL_IMPLICIT_GENERAL":               handle_control_implicit_general,
    "CONTROL_IMPLICIT_SOLUTION":              handle_control_implicit_solution,
    "CONTROL_IMPLICIT_AUTO":                  handle_control_implicit_auto,
    "CONTROL_IMPLICIT_DYNAMICS":              handle_control_implicit_dynamics,
    "CONTROL_IMPLICIT_EIGENVALUE":            handle_control_implicit_eigenvalue,
    "CONTROL_TERMINATION":                    handle_control_termination,
    "CONTROL_TIMESTEP":                       handle_control_timestep,
    "CONTROL_ACCURACY":                       handle_control_accuracy,
    "CONTROL_CONTACT":                        handle_control_contact,
    "CONTROL_CPU":                            handle_control_cpu,
    "CONTROL_ENERGY":                         handle_control_energy,
    "CONTROL_HOURGLASS":                      handle_control_hourglass,
    "CONTROL_OUTPUT":                         handle_control_output,
    "CONTROL_SHELL":                          handle_control_shell,
    "CONTROL_SOLID":                          handle_control_solid,
    "CONTROL_ADAPTIVE":                       handle_skip,
    "CONTROL_BULK_VISCOSITY":                 handle_skip,
    "CONTROL_DYNAMIC_RELAXATION":             handle_skip,
    "CONTROL_MPP_DECOMPOSITION":              handle_skip,
    "CONTROL_UNITS":                          handle_skip,

    # Damping
    "DAMPING_GLOBAL":                         handle_damping_global,
    "DAMPING_PART_STIFFNESS":                 handle_damping_part_stiffness,

    # Database / output
    "DATABASE_BINARY_D3PLOT":                 handle_database_binary_d3plot,
    "DATABASE_ELOUT":                         handle_database_elout,
    "DATABASE_GLSTAT":                        handle_database_glstat,
    "DATABASE_HISTORY_SHELL":                 handle_database_history_shell,
    "DATABASE_HISTORY_SOLID":                 handle_database_history_solid,
    "DATABASE_HISTORY_NODE":                  handle_database_history_node,
    "DATABASE_ABSTAT":                        handle_database_abstat,
    "DATABASE_BINARY_D3THDT":                 handle_database_binary_d3thdt,
    "DATABASE_BINARY_INTFOR":                 handle_database_binary_intfor,
    "DATABASE_DEFORC":                        handle_database_deforc,
    "DATABASE_EXTENT_BINARY":                 handle_database_extent_binary,
    "DATABASE_JNTFORC":                       handle_database_jntforc,
    "DATABASE_MATSUM":                        handle_database_matsum,
    "DATABASE_NODOUT":                        handle_database_nodout,
    "DATABASE_RCFORC":                        handle_database_rcforc,
    "DATABASE_RWFORC":                        handle_database_rwforc,
    "DATABASE_SECFORC":                       handle_database_secforc,
    "DATABASE_SLEOUT":                        handle_database_sleout,
    "DATABASE_SPCFORC":                       handle_database_spcforc,
    "DATABASE_NCFORC":                        handle_database_ncforc,
    "DATABASE_RBDOUT":                        handle_skip,
    "DATABASE_BINARY_D3DRLF":                handle_skip,
    "DATABASE_BINARY_D3DUMP":                 handle_skip,
    "DATABASE_BINARY_BLSTFOR":                handle_database_binary_blstfor,
    "DATABASE_CROSS_SECTION_PLANE":           handle_database_cross_section_plane,
    "DATABASE_CROSS_SECTION_SET":             handle_database_cross_section_set,
    "DATABASE_BINARY_RUNRSF":                 handle_skip,
    "DATABASE_FREQUENCY_BINARY_D3PSD":        handle_database_frequency_binary_d3psd,
    "DATABASE_FREQUENCY_BINARY_D3RMS":        handle_database_frequency_binary_d3rms,
    "DATABASE_FREQUENCY_BINARY_D3FTG":        handle_database_frequency_binary_d3ftg,
    # INITIAL_STRESS_SECTION prescribes a section FORCE (a different beast from
    # the per-IP stress fields below) — kept warn+skipped.
    "INITIAL_STRESS_SECTION":                 handle_skip,
    "INITIAL_STRESS_SHELL":                   handle_initial_stress_shell,
    "INITIAL_STRESS_SOLID":                   handle_initial_stress_solid,
    "LOAD_GRAVITY_PART":                      handle_load_gravity_part,
    "LOAD_GRAVITY_PART_SET":                  handle_load_gravity_part,
    "LOAD_RIGID_BODY":                        handle_load_rigid_body,
    "LOAD_SEGMENT":                           handle_load_segment,
    "LOAD_SEGMENT_ID":                        handle_load_segment,
    "LOAD_SEGMENT_SET":                       handle_load_segment_set,
    "LOAD_SEGMENT_SET_ID":                    handle_load_segment_set,
    "LOAD_NODE_POINT":                        handle_load_node,
    "LOAD_NODE_SET":                          handle_load_node,
    "LOAD_BODY_X":                            handle_load_body,
    "LOAD_BODY_Y":                            handle_load_body,
    "LOAD_BODY_Z":                            handle_load_body,
    "LOAD_BODY_PARTS":                        handle_load_body_parts,
    "LOAD_BLAST_ENHANCED":                    handle_load_blast_enhanced,
    "LOAD_BLAST_SEGMENT_SET":                 handle_load_blast_segment_set,
    "LOAD_BLAST_SEGMENT":                     handle_load_blast_segment,
    "LOAD_BLAST":                             handle_load_blast,
    "MAT_ADD_EROSION":                        handle_mat_add_erosion,
    "CONSTRAINED_NODE_SET":                   handle_constrained_node_set,
    "MAT_ADD_FATIGUE":                        handle_mat_add_fatigue,
    "MAT_SIMPLIFIED_JOHNSON_COOK":            handle_mat_simplified_johnson_cook,
    "SET_SEGMENT":                            handle_set_segment,
}


# *PART_COMPOSITE_{OPTION1}_{OPTION2}_{OPTION3} — OPTION1 in {<blank>, TSHELL,
# IGA_SHELL}, OPTION2 in {<blank>, LONG}, OPTION3 in {<blank>, CONTACT}
# (LS-DYNA Vol I R17 p.37-18): TWELVE legal spellings. dispatch() is an exact
# dict lookup with no *PART_COMPOSITE prefix fallback, and a *PART_COMPOSITE
# that misses it does not merely get skipped — _make_parts_and_elements emits
# elements inside the state.parts loop, so the part AND every element on it
# vanish with no warning. Generating the grammar keeps that from depending on
# someone hand-enumerating all twelve.
for _o1 in ("", "_TSHELL", "_IGA_SHELL"):
    for _o2 in ("", "_LONG"):
        for _o3 in ("", "_CONTACT"):
            HANDLERS[f"PART_COMPOSITE{_o1}{_o2}{_o3}"] = handle_part_composite
del _o1, _o2, _o3


# *ELEMENT_SHELL_{THICKNESS}_{BETA|MCID}_{OFFSET}_{DOF} (Vol I R17): 24 legal
# spellings, and *ELEMENT_BEAM_{OFFSET}_{ORIENTATION}: 4. Generating the grammar
# beats hand-enumerating it — and unlike *PART_COMPOSITE (twelve spellings, all
# of them enumerable) the element families also have options k2rad does not
# model at all (_COMPOSITE, _SHL4_TO_SHL8, _SCALAR, ...), so the prefix fallback
# in dispatch() below is what actually guarantees no mesh is lost.
for _o1 in ("", "_THICKNESS"):
    for _o2 in ("", "_BETA", "_MCID"):
        for _o3 in ("", "_OFFSET"):
            for _o4 in ("", "_DOF"):
                HANDLERS[f"ELEMENT_SHELL{_o1}{_o2}{_o3}{_o4}"] = handle_element_shell
for _o1 in ("", "_OFFSET"):
    for _o2 in ("", "_ORIENTATION"):
        HANDLERS[f"ELEMENT_BEAM{_o1}{_o2}"] = handle_element_beam
del _o1, _o2, _o3, _o4


#: Keyword PREFIX → handler, tried when the exact-match lookup misses. Only the
#: element families whose handler can keep the connectivity of an option it does
#: not understand are listed (see the UNKNOWN-suffix branch in each handler).
#:
#: Without this, an unlisted spelling would land in skipped_keywords, and for
#: elements that is not a soft failure: _make_parts_and_elements emits elements
#: inside the state.parts loop, so a *ELEMENT_SHELL_MCID block leaves its /PART
#: in the deck with NO /SHELL block under it — the elements are gone, the part
#: is silently empty, and result.warnings says nothing. That is exactly what
#: dyna2rad does (its CFG table matches USER_NAMES exactly), and it is the
#: single biggest parity win in this family.
_ELEMENT_PREFIX_HANDLERS = (
    ("ELEMENT_SHELL", handle_element_shell),
    ("ELEMENT_BEAM", handle_element_beam),
    ("ELEMENT_PLOTEL", handle_element_plotel),
)


def dispatch(block: Block, state: ConversionState) -> None:
    """Look up and call the handler for *block.keyword*."""
    handler = HANDLERS.get(block.keyword)
    if handler is None:
        for _prefix, _handler in _ELEMENT_PREFIX_HANDLERS:
            if block.keyword.startswith(_prefix):
                handler = _handler
                break
    if handler is not None:
        handler(block, state)
    else:
        state.skipped_keywords.append(block.keyword)
