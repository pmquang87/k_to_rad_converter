"""
k2rad.handlers  –  Convert each LS-DYNA Block into ConversionState entries.

Each public function has signature:
    handle_<keyword>(block: Block, state: ConversionState) -> None
"""

from __future__ import annotations

import ast as _ast
import math as _math
from typing import List, Tuple

from .parser import (
    Block, _strip_inline_comment, parse_fixed, parse_free, to_float, to_int,
)
from .state import (
    ConversionState,
    NodeData, ShellElem, SolidElem, BeamElem,
    PartData, SectionShell, SectionSolid, SectionBeam,
    MatElastic, MatPlasTAB, MatPlasKin, MatRigid, MatNull, MatSAMP, FailGissmo,
    MatAddErosion, ConstrainedNodeSet,
    MatCrushableFoam, MatLowDensityFoam, MatFuChangFoam, MatHoneycomb,
    DiscreteElem, SectionDiscrete, MatSpringElastic, MatSpringNonlinearElastic,
    MatDamperViscous, MatSpotweld, ConstrainedSpotweld,
    Curve, DefineTable, CoordSys, CoordNodes, ConstrainedNodalRigidBody,
    BcsSpc, PrescribedMotionRigid, PrescribedMotionSet, LoadRigidBody,
    LoadNode, RigidWallPlanar,
    ContactAutoSingle, ContactAutoSurf2Surf, ContactForceTransducer, ContactTied,
    InitialVelocityNode, InitialVelocityRigidBody, MatPowerLaw, PressureLoad,
    SegmentSet, SegmentSetPressureLoad, LoadBlastEnhanced, LoadBlastSegmentSet,
    LoadBody,
    MatHighExplosiveBurn, EosJwl, EosCard, InitialDetonation,
    AleMultiMaterialGroup, ConstrainedLagrangeInSolid, InitialVolumeFraction,
    BoundaryNonReflecting, ControlAle,
    ControlAccuracy, ControlContact, ControlCpu, ControlEnergy,
    ControlHourglass, ControlImplicitAuto, ControlImplicitDynamics,
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

def handle_element_shell(block: Block, state: ConversionState) -> None:
    for line in block.raw:
        f = [x for x in _elem_fields(line, 10) if x]   # eid pid n1..n8
        # 5 fields = eid pid n1 n2 n3: a triangle whose blank trailing N4
        # column was dropped — legal fixed-format output, keep it.
        if len(f) < 5:
            continue
        eid = to_int(f[0])
        pid = to_int(f[1])
        nodes = [to_int(f[i]) for i in range(2, min(6, len(f)))]
        while len(nodes) < 4:
            nodes.append(0)
        while len(nodes) > 3 and nodes[-1] == 0:
            nodes.pop()
        state.shell_elems.append(ShellElem(eid, pid, nodes))


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


def handle_element_beam(block: Block, state: ConversionState) -> None:
    for line in block.raw:
        f = [x for x in _elem_fields(line, 5) if x]
        # The orientation node N3 is optional (truss/ELFORM-3 beams omit it),
        # so 4 fields (eid pid n1 n2) is a complete card.
        if len(f) < 4:
            continue
        eid, pid = to_int(f[0]), to_int(f[1])
        n1, n2 = to_int(f[2]), to_int(f[3])
        n3 = to_int(f[4]) if len(f) > 4 else 0
        state.beam_elems.append(BeamElem(eid, pid, n1, n2, n3))


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
        if pid <= 0:
            state.warn(f"*PART: data card with no part id – skipped (title='{title}')")
            continue
        state.parts[pid] = PartData(pid, title, secid, mid)


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
    # Card2: C P LCSS LCSR VP
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


def handle_contact_automatic_single_surface(block: Block, state: ConversionState) -> None:
    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    # Card1: ssid msid sstyp mstyp sboxid mboxid spr mpr
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
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
                          vdc=vdc, sst=sst, mst=mst, sfs=sfs)
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
                             vdc=vdc, sst=sst, mst=mst, sfs=sfs)
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
    Card3: sfs sfm sst mst — a NEGATIVE sst/mst is LS-DYNA's "absolute
           tie-criterion distance", kept as a floor for the TYPE2 dsearch.
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
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sst = to_float(f3[2]) if len(f3) > 2 else 0.0
    mst = to_float(f3[3]) if len(f3) > 3 else 0.0

    kw = block.keyword                       # e.g. CONTACT_TIED_NODES_TO_SURFACE_OFFSET
    if "SHELL_EDGE" in kw:
        variant = "SHELL_EDGE_TO_SURFACE"
    elif "NODES" in kw:
        variant = "NODES_TO_SURFACE"
    else:
        variant = "SURFACE_TO_SURFACE"
    state.contacts_tied.append(
        ContactTied(inter_id, title, ssid, sstyp, msid, mstyp, variant,
                    offset=kw.endswith("OFFSET"), sst=sst, mst=mst)
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
    f = _card(raw, 0, fixed=True, n=8, w=10)
    dt2ms = to_float(f[4]) if len(f) > 4 else 0.0
    state.ctrl_timestep = ControlTimestep(to_float(f[0]), to_float(f[1]), dt2ms)


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


def _handle_db_dt(block: Block) -> float:
    """Parse DT from the first field of a DATABASE_* card."""
    raw = block.raw
    if not raw:
        return 0.0
    f = parse_free(raw[0])
    if not f:
        f = parse_fixed(raw[0], n=4, w=10)
    return to_float(f[0]) if f else 0.0


def handle_database_abstat(block: Block, state: ConversionState) -> None:
    state.db_abstat_dt = _handle_db_dt(block)


def handle_database_binary_d3thdt(block: Block, state: ConversionState) -> None:
    state.db_d3thdt_dt = _handle_db_dt(block)


def handle_database_binary_intfor(block: Block, state: ConversionState) -> None:
    state.db_intfor_dt = _handle_db_dt(block)


def handle_database_deforc(block: Block, state: ConversionState) -> None:
    state.db_deforc_dt = _handle_db_dt(block)


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
    state.db_jntforc_dt = _handle_db_dt(block)


def handle_database_matsum(block: Block, state: ConversionState) -> None:
    state.db_matsum_dt = _handle_db_dt(block)


def handle_database_nodout(block: Block, state: ConversionState) -> None:
    state.db_nodout_dt = _handle_db_dt(block)


def handle_database_rcforc(block: Block, state: ConversionState) -> None:
    state.db_rcforc_dt = _handle_db_dt(block)


def handle_database_rwforc(block: Block, state: ConversionState) -> None:
    state.db_rwforc_dt = _handle_db_dt(block)


def handle_database_secforc(block: Block, state: ConversionState) -> None:
    state.db_secforc_dt = _handle_db_dt(block)


def handle_database_sleout(block: Block, state: ConversionState) -> None:
    state.db_sleout_dt = _handle_db_dt(block)


def handle_database_binary_blstfor(block: Block, state: ConversionState) -> None:
    """*DATABASE_BINARY_BLSTFOR (blast pressure database) → /TH/SURF with the
    P (average external pressure) and A (loaded area) channels on each
    blast-loaded surface, plus engine /ANIM/NODA/PEXT (nodal blast-pressure
    fringe) and /ANIM/VECT/FEXT (external force vectors). /LOAD/PBLAST feeds
    all three (engine pblast_1.F). Card 1 field 1 is DT, as for D3PLOT."""
    state.db_blstfor_dt = _handle_db_dt(block)


def handle_database_ncforc(block: Block, state: ConversionState) -> None:
    """*DATABASE_NCFORC (nodal contact forces) → /TH/INTER on every converted
    contact interface (T01 force resultants). The per-node view lives in the
    default animation vectors /ANIM/VECT/CONT + /ANIM/VECT/PCONT; OpenRadioss
    has no per-node contact-force time history."""
    state.db_ncforc_dt = _handle_db_dt(block)


def handle_database_spcforc(block: Block, state: ConversionState) -> None:
    """*DATABASE_SPCFORC (SPC reaction forces) → /TH/NODE with REACX/Y/Z
    (+REACXX/YY/ZZ) on the /BCS-constrained nodes + engine /ANIM/VECT/FREAC.
    The writer emits both; requesting either makes the OpenRadioss engine
    compute constraint reactions (engine reactions.F, COMPTREAC)."""
    state.db_spcforc_dt = _handle_db_dt(block)


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
    if boxid:
        state.warn(f"{label} id={rwid}: BOXID has no /RWALL "
                   "equivalent — the box limitation is ignored.")
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


def handle_mat_187(block: Block, state: ConversionState) -> None:
    """*MAT_187 / *MAT_SAMP-1 → /MAT/LAW76 (SAMP-1 polymer).

    Reads the classic SAMP-1 card layout (mid ro e nu numint / tab_idt tab_idc
    tab_ids nu_p fct_idpr / fct_id1 epfail deprpt lcid_tri lcid_lc / iconv /
    asrate) — the same field order Radioss LAW76 uses, so the map is 1:1. The
    three yield curves (tab_idt/c/s) must become /TABLE cards, so their ids are
    registered in state.law76_table_ids. Free-field parsing is used because these
    decks (often tool-generated to target LAW76) rarely honour strict columns.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw

    def field(idx, pos, conv, default):
        f = _card(raw, idx, fixed=False)
        return conv(f[pos]) if len(f) > pos else default

    # Card1: mid ro e nu numint
    f1 = _card(raw, offset, fixed=False)
    if not f1:
        state.warn("*MAT_187: empty material card – skipped")
        return
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    E   = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu  = to_float(f1[3]) if len(f1) > 3 else 0.0
    # Card2: tab_idt tab_idc tab_ids nu_p fct_idpr
    tab_idt  = field(offset + 1, 0, to_int,   0)
    tab_idc  = field(offset + 1, 1, to_int,   0)
    tab_ids  = field(offset + 1, 2, to_int,   0)
    nu_p     = field(offset + 1, 3, to_float, nu)
    fct_idpr = field(offset + 1, 4, to_int,   0)
    # Card3: fct_id1 epfail deprpt lcid_tri lcid_lc
    fct_id1  = field(offset + 2, 0, to_int,   0)
    epfail   = field(offset + 2, 1, to_float, 0.0)
    deprpt   = field(offset + 2, 2, to_float, 0.0)
    # Card4: iconv (single value) — parse_free directly (a lone value would be
    # mis-slotted by the fixed-width fallback)
    c4 = parse_free(raw[offset + 3]) if offset + 3 < len(raw) else []
    iconv = to_int(c4[-1]) if c4 else 1
    # Card5: asrate (single value, optional)
    c5 = parse_free(raw[offset + 4]) if offset + 4 < len(raw) else []
    asrate = to_float(c5[-1]) if c5 else 0.0

    state.mat_samp[mid] = MatSAMP(mid, title, rho, E, nu, tab_idt, tab_idc,
                                  tab_ids, nu_p, fct_idpr, fct_id1, epfail,
                                  deprpt, iconv, asrate)
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
    """*MAT_ADD_EROSION → an OpenRadioss /FAIL model (strain criteria only).
    Card layout from mat_add_erosion.cfg:
      Card1: MID EXCL MXPRES MNEPS EFFEPS VOLEPS NUMFIP NCS
      Card2: MNPRES SIGP1 SIGVM MXEPS EPSSH SIGTH IMPULSE FAILTM
      Card3 (optional): IDAM ... (GISSMO/DIEM — reported, not converted)"""
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0]:
        state.warn("*MAT_ADD_EROSION: empty card – skipped")
        return
    mid    = to_int(f1[0])
    mxpres = to_float(f1[2]) if len(f1) > 2 else 0.0
    mneps  = to_float(f1[3]) if len(f1) > 3 else 0.0
    effeps = to_float(f1[4]) if len(f1) > 4 else 0.0
    voleps = to_float(f1[5]) if len(f1) > 5 else 0.0
    numfip = to_float(f1[6]) if len(f1) > 6 else 1.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    mnpres = to_float(f2[0]) if f2        else 0.0
    sigp1  = to_float(f2[1]) if len(f2) > 1 else 0.0
    sigvm  = to_float(f2[2]) if len(f2) > 2 else 0.0
    mxeps  = to_float(f2[3]) if len(f2) > 3 else 0.0
    epssh  = to_float(f2[4]) if len(f2) > 4 else 0.0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    idam = to_int(f3[0]) if f3 and f3[0] else 0
    other = [n for n, v in (("MXPRES", mxpres), ("MNEPS", mneps),
                            ("VOLEPS", voleps), ("MNPRES", mnpres),
                            ("SIGP1", sigp1), ("SIGVM", sigvm), ("EPSSH", epssh))
             if v]
    state.mat_add_erosion[mid] = MatAddErosion(mid, effeps, mxeps, numfip,
                                               idam, other)


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

    Card: pid dof lc accel lcdr stga stgr — DOF 1/2/3 loads along -X/-Y/-Z.
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
    """*LOAD_BODY_{X,Y,Z} → whole-model base-acceleration body load → /GRAV.

    Card: lcid sf lciddr xc yc zc cid.  The load direction is the axis letter in
    the keyword suffix (X/Y/Z); the acceleration field is sf × lcid(t). Angular
    (_RX/_RY/_RZ) and generic (_VECTOR/_GENERALIZED) body loads have no /GRAV
    mapping and are skipped with a warning.
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
    lcid = to_int(f[0])
    sf   = to_float(f[1]) if len(f) > 1 else 1.0
    if sf == 0.0:
        sf = 1.0
    if lcid <= 0:
        state.warn(f"*{kw}: no acceleration curve (lcid={lcid}) — skipped.")
        return
    state.body_loads.append(LoadBody(dir=suffix, lcid=lcid, sf=sf))


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
    raw = block.raw
    f = _card(raw, 0, fixed=True, n=8, w=10) if raw else []
    dt    = to_float(f[0]) if f else 0.0
    npltc = to_int(f[3])   if len(f) > 3 else 0
    state.db_d3plot = DbD3Plot(dt, npltc)


def handle_database_elout(block: Block, state: ConversionState) -> None:
    raw = block.raw
    f = _card(raw, 0, fixed=True, n=4, w=10) if raw else []
    state.db_elout_dt = to_float(f[0]) if f else 0.0


def handle_database_glstat(block: Block, state: ConversionState) -> None:
    raw = block.raw
    f = _card(raw, 0, fixed=True, n=4, w=10) if raw else []
    state.db_glstat_dt = to_float(f[0]) if f else 0.0


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
    "ELEMENT_SHELL":                          handle_element_shell,
    "ELEMENT_SOLID":                          handle_element_solid,
    "ELEMENT_BEAM":                           handle_element_beam,
    "PART":                                   handle_part,

    # Sections
    "SECTION_SHELL":                          handle_section_shell,
    "SECTION_SOLID":                          handle_section_solid,
    "SECTION_BEAM":                           handle_section_beam,
    "SECTION_DISCRETE":                       handle_section_discrete,

    # Materials
    "MAT_ELASTIC":                            handle_mat_elastic,
    "MAT_PIECEWISE_LINEAR_PLASTICITY":        handle_mat_piecewise_linear_plasticity,
    "MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY": handle_mat_piecewise_linear_plasticity,
    "MAT_PLASTIC_KINEMATIC":                  handle_mat_plastic_kinematic,
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
    "DEFINE_COORDINATE_VECTOR":               handle_skip,

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
    "INITIAL_VELOCITY_NODE":                  handle_initial_velocity_node,
    "INITIAL_VELOCITY_RIGID_BODY":            handle_initial_velocity_rigid_body,
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
    "CONTACT_AUTOMATIC_GENERAL":              handle_contact_automatic_single_surface,
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


def dispatch(block: Block, state: ConversionState) -> None:
    """Look up and call the handler for *block.keyword*."""
    handler = HANDLERS.get(block.keyword)
    if handler is not None:
        handler(block, state)
    else:
        state.skipped_keywords.append(block.keyword)
