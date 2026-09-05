"""
k2rad.handlers  –  Convert each LS-DYNA Block into ConversionState entries.

Each public function has signature:
    handle_<keyword>(block: Block, state: ConversionState) -> None
"""

from __future__ import annotations

import ast as _ast
import math as _math
from itertools import permutations as _permutations, product as _product
from typing import Any, Dict, List, Optional, Tuple, cast

#: Fixed arities the *INITIAL_STRESS_/_STRAIN_ producers below guarantee via
#: _fixed_float_card's zero-padding (`vals += [0.0] * (n - len(vals))`), and
#: that writer/inistate.py unpacks positionally — an 8-way `for (t, sxx, syy,
#: szz, sxy, syz, szx, eps) in iss.layers` there. Widening the dataclass field
#: to Tuple[float, ...] would throw away a guarantee its consumer relies on.
_Layer8 = Tuple[float, float, float, float, float, float, float, float]
_Layer7 = Tuple[float, float, float, float, float, float, float]

from .parser import (
    Block, _strip_inline_comment, parse_fixed, parse_free, set_active_scope,
    to_float, to_int,
)
from .state import (
    ConversionState,
    SET_ADD_FAMILIES,
    NodeData, ShellElem, SolidElem, BeamElem, PlotelElem, ProvisionalElemBlock,
    TshellElem, SphCell,
    PartData, SectionShell, SectionSolid, SectionTshell, SectionBeam,
    SectionSph, ControlSph,
    IntegrationShell, IntegrationPoint,
    IntegrationBeam, IntegrationBeamPoint,
    MatElastic, MatPlasTAB, MatPlasKin, MatRigid, MatNull, MatSAMP, FailGissmo,
    MatAnisoViscoplastic, MatJohnsonCook,
    MatOrthotropicElastic, MatEnhancedCompositeDamage, MatCompositeDamage,
    MatTransverselyAnisotropic, MatLaminatedGlass,
    MatFabric, FABRIC_CURVE_FORMS,
    Airbag, AirbagRefGeometry, AirbagShellRefGeometry,
    AirbagInteraction, GasSpecies,
    CompositePly, PartComposite,
    MatAddErosion, ConstrainedNodeSet,
    MatCrushableFoam, MatLowDensityFoam, MatFuChangFoam, MatHoneycomb,
    MatSoilAndFoam, MatLowDensityViscousFoam, MatModifiedHoneycomb,
    MatDeshpandeFleckFoam, MatHillFoam,
    MatBlatzKo, MatMooneyRivlin, MatOgdenRubber, MatHyperelasticRubber,
    MatIsoElasPlas, MatStrainRatePlas, MatGurson, MatHill3R, MatPlasCompTens,
    MatViscoelastic, MatKelvinMaxwell, MatGeneralViscoelastic,
    MatSimplifiedRubber, MatSoftTissue,
    MatCohesiveMixedMode, MatArupAdhesive, MatCohesiveMMEPR,
    MatToughenedAdhesive, FailDiem, FailDiemCriterion,
    MatTabulatedJC, DefineTable3D,
    MatJHCeramics, MatJHConcrete, MatElasticFluid,
    FoamRefGeometry,
    DiscreteElem, SectionDiscrete, MatSpringElastic, MatSpringNonlinearElastic,
    MatDamperViscous, MatSpotweld, ConstrainedSpotweld,
    MatSpringElastoplastic, MatDamperNonlinearViscous,
    MatSpringGeneralNonlinear, MatSpringInelastic,
    MatDiscreteBeamLinear, MatDiscreteBeamNonlinearElastic,
    MatDiscreteBeamNonlinearPlastic, MatCableDiscreteBeam,
    MatElasticSpringDiscreteBeam, MatGeneralNonlinear6dof,
    MatGeneralNonlinear1dof, MatGeneralSpringDiscreteBeam,
    ConstrainedJoint, JointStiffness, JOINT_TYPE45,
    Curve, DefineTable, CoordSys, CoordNodes, CoordVector, DefineVector,
    SdOrientation, DefineBox, ConstrainedNodalRigidBody,
    RigidInertia, PartContact,
    ConstrainedInterpolation, InterpolationIndep,
    BcsSpc, PM_VAD_KEYWORD, PrescribedMotionRigid, PrescribedMotionSet,
    LoadRigidBody,
    LoadNode, RigidWallPlanar, RigidWallGeometric,
    ContactAutoSingle, ContactAutoSurf2Surf, ContactAutoGeneral,
    ContactForceTransducer, ContactTied, ContactSpotweld, ContactType25,
    ContactTiebreak,
    DefineFriction, FrictionPair, HexSpotweldAssembly,
    InitialVelocityNode, InitialVelocityRigidBody,
    InitialVelocity, InitialVelocityGeneration, MatPowerLaw, PressureLoad,
    SegmentSet, SegmentSetPressureLoad, LoadBlastEnhanced, LoadBlastSegmentSet,
    LoadBody, LoadBodyVector, LoadBodyRot, ShellPressureLoad,
    MatHighExplosiveBurn, EosJwl, EosCard, InitialDetonation,
    AleMultiMaterialGroup, ConstrainedLagrangeInSolid, InitialVolumeFraction,
    BoundaryNonReflecting, ControlAle,
    ControlAccuracy, ControlContact, ControlCpu, ControlEnergy,
    ControlHourglass, HourglassDef, ControlImplicitAuto, ControlImplicitDynamics,
    ControlOutput, ControlParallel, ControlShell, ControlSolid,
    ControlImplicitGeneral, ControlImplicitSolution, ControlImplicitEigenvalue,
    ControlTermination, ControlTimestep,
    DampingGlobal, DampingPartStiffness, DampingPartMass,
    DampingFrequencyRange, DampingRelative,
    DbD3Plot, DbHistory, DbExtentBinary, DbNodalForceGroup,
    GravityLoadPart, MatAddFatigue, DbFreqBinary,
    InitialStressShell, InitialStressSolid, CrossSection,
    InitialStrainShell, InitialStressSection, InitialAxialForceBeam,
    SeatbeltElem, SectionSeatbelt, MatSeatbelt, SeatbeltSlipring,
    SeatbeltRetractor, SeatbeltPretensioner, SeatbeltSensor,
    SeatbeltAccelerometer,
    MatShapeMemory, MatMuscle, MatSpringMuscle,
    MatElasticPlasticThermal, MatCWM, MatElasticPlasticHydro, MatVacuum,
    MatAddThermalExpansion, MatThermalIsotropic,
    MatThermalIsotropicTD, MatThermalOrthotropic,
    ControlThermalSolver, ThermalBoundary, LoadThermalElement,
    InitialTemperature, ImposedTemperature,
    ElementDeath, PerturbationNode, FinalGeometryNode,
    BoundaryPrescribedFinalGeometry, InterfaceSpringback,
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

def _note_node_constraint(state: ConversionState, nid: int, tc: str,
                          rc: str) -> None:
    """Record a ``*NODE`` card that states a constraint in TC or RC.

    Vol I R17's ``*NODE`` Card 1 is ``NID X Y Z TC RC``, and TC/RC are
    constraint CODES (0 none, 1 x, 2 y, 3 z, 4 xy, 5 yz, 6 zx, 7 xyz) in the
    GLOBAL system. k2rad reads only NID/X/Y/Z, so a deck that states its
    constraints there converts into a model with those degrees of freedom
    FREE — at 0 conversion warnings and 0 starter errors. Measured on a
    spring-mass coupon: the anchor node carried tc=7/rc=7, no /BCS was
    emitted, and the whole oscillator drifted at the centre-of-mass velocity
    (6.68 mm against an intended 0.317 mm amplitude) while the run reported
    NORMAL TERMINATION. 721 of 2346 corpus decks write a non-zero cell here.

    Only the LOSS is recorded; ``writer/assembly._warn_node_tc_rc`` names it
    once per deck and carries the full reasoning for why the conversion is
    deferred rather than done here.
    """
    for cell in (tc, rc):
        if not cell:
            continue
        try:
            if int(float(cell)) == 0:
                continue
        except ValueError:
            continue
        state.node_tc_rc_count += 1
        # Five, matching what _warn_node_tc_rc prints — collecting ten left
        # half the list dead.
        if len(state.node_tc_rc) < 5:
            state.node_tc_rc.append(nid)
        return


def _free_node_id(tok: str) -> bool:
    """True when *tok* can be a free-format *NODE row's field 1.

    That field is the node id (type I), so an integer token — or a ``&name``
    parameter reference, which ``to_int`` resolves — is the whole legal set.
    Anything else means the whitespace split welded the id onto a negative
    first coordinate and the row has to be read from its fixed columns
    instead. See :func:`handle_node`.

    Measured across both corpus roots: of the 58 303 *NODE rows whose field 1
    is not an integer token, ALL 58 303 are the welded kind — there is no
    ``&``-id, comma-format or blank-id row anywhere to trade against.
    """
    t = (tok or "").strip()
    return t.startswith("&") or _is_int_token(t)


def handle_node(block: Block, state: ConversionState) -> None:
    """*NODE — ``NID X Y Z TC RC`` (Vol I R17 p.35-3), I8 + 3xE16 + 2xI8.

    The fixed-vs-free discrimination is the whole difficulty. A negative
    coordinate fills its 16-char field completely and glues onto the field
    BEFORE it ("... 0.000000000e+00-1.250000000e+00"), so a whitespace split
    of a fixed-format row can under-count, leave an over-long merged token —
    or, when exactly the right cells are negative, produce four perfectly
    ordinary-looking tokens with the NODE ID welded to the front of the first
    one.

    That last case is why ``f[0]`` is now tested too, and it is not academic:
    the width test alone missed **58 303 rows across 188 corpus files**. Take
    ``dynaexamples/sph/bar-iv/taylor1.k``, where X and Y are negative and Z is
    not::

        '       5-1.000000000E+01-1.000000000E+01 0.000000000E+00       7   0'
          -> ['5-1.000000000E+01-1.000000000E+01', '0.000000000E+00', '7', '0']

    Four tokens, none longer than 16, so it took the FREE branch,
    ``to_int('5-1.000000000E+01-1.000000000E+01')`` returned 0, and the row
    was written to ``state.nodes[0]`` with the wrong coordinates — nodes 5 and
    7 GONE, a phantom node 0 in their place, and the deck's only /BRICK left
    referencing two ids that no longer exist, at ZERO warnings. (It is also
    why this deck's *NODE TC/RC count disagreed with an independent scan of
    the same file by exactly the number of lost rows.)

    An ``f[0]`` that is not an integer token can only mean the split merged
    the id with a coordinate: in genuine free format field 1 IS the node id.
    Testing the token's TYPE rather than its width also keeps the guard safe
    for a free-format id longer than eight digits, which no fixed-format row
    can carry — measured: 0 such rows in the corpus, but the type test costs
    nothing to be right about.
    """
    for line in block.raw:
        f = parse_free(line)
        if len(f) < 4 or any(len(t) > 16 for t in f[1:4]) \
                or not _free_node_id(f[0]):
            nid = to_int(line[0:8])
            if nid <= 0:
                continue
            state.nodes[nid] = NodeData(to_float(line[8:24]), to_float(line[24:40]),
                                        to_float(line[40:56]))
            # TC/RC live in cols 57-64 and 65-72. The length test keeps the
            # cost off every ordinary node line, which ends at column 56.
            if len(line) > 56:
                _note_node_constraint(state, nid, line[56:64].strip(),
                                      line[64:72].strip())
            continue
        nid = to_int(f[0])
        if nid <= 0:
            # Unreachable while the branch test above is right; kept so that a
            # future miss DROPS the row instead of minting node 0 and letting
            # every later row overwrite it (which is exactly how the defect
            # above stayed silent).
            state.warn(f"*NODE: the row {line.strip()[:40]!r} has no usable "
                       "node id — it was dropped rather than written to node "
                       "0; check the card's column layout.")
            continue
        state.nodes[nid] = NodeData(to_float(f[1]), to_float(f[2]), to_float(f[3]))
        if len(f) > 4:
            _note_node_constraint(state, nid, f[4].strip(),
                                  f[5].strip() if len(f) > 5 else "")


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
# *ELEMENT_TSHELL_{BETA|COMPOSITE} (Vol I R16 pp.2703-2707). Neither option has
# a CFG entry at all — Keyword971/ELEMENTS/tshell.cfg declares ONLY the bare
# ``EID PID N1..N8`` card — so dyna2rad cannot even read the header and drops
# the whole block, mesh included. k2rad walks both card layouts.
_TSHELL_SUFFIX_TOKENS = frozenset({"BETA", "COMPOSITE"})
# *ELEMENT_SPH_{VOLUME} (Vol I R16/R17). One option slot, and it changes what
# the MASS column MEANS: "If the VOLUME option is used, the field for MASS is
# treated as particle volume. It has the same effect as giving a negative
# number in the MASS field." dyna2rad's CFG (Keyword971/ELEMENTS/sphcel.cfg)
# declares no option at all, so it reads a _VOLUME block's volumes as masses —
# measured, wrong by exactly rho (1.6e-05 kg where the deck states 1.6e-02).
_SPH_SUFFIX_TOKENS = frozenset({"VOLUME"})

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


def _parse_tshell_base(line: str):
    """One *ELEMENT_TSHELL connectivity card → (eid, pid, nodes, n_given) or
    None. *nodes* is always eight ids; *n_given* is how many the card actually
    named, so the caller can report a short card.

    Card 1 is ``EID PID N1..N8``, ten I8 fields
    (``Keyword971/ELEMENTS/tshell.cfg:73``). A thick shell is ALWAYS eight-slot
    in LS-DYNA: the 6-node pentahedron is entered by REPEATING ids rather than
    blanking slots — "For a pentahedron, nodes n1, n2, n3 form the lower
    triangular surface and the eight variables N1 to N8 should be defined using
    nodes n1, n2, n3, n3, n4, n5, n6, n6, respectively. Note that node n3 and
    node n6 are each repeated" (Vol I R14 p.19-139 Remark 1). A conforming deck
    therefore never reaches the padding below.

    A SHORT card (six ids given, or two trailing zeros) is not a form LS-DYNA
    defines, but it has one obvious reading — the pentahedron's own six nodes —
    so it is expanded into exactly the manual's 8-slot spelling
    ``n1 n2 n3 n3 n4 n5 n6 n6``. Padding by repeating the LAST id instead was a
    silent 50 % volume error: it produces ``n1 n2 n3 n4 n5 n6 n6 n6``, whose
    upper face has collapsed to a point, and the starter accepts it with 0
    ERRORS (measured 1.950E-10 against the correct 3.900E-10 for one prism,
    with the CoG shifted 0.05 → 0.0625) — the /TETRA10 under-volume failure
    mode again. Trailing zeros are examined BEFORE they are stripped so a card
    written ``n1..n6 0 0`` takes the same route as a six-field one.

    Seven ids is a genuine degenerate hex (a pyramid); repeating n7 there
    changes nothing, so it is kept. Four or five ids cannot be a thick shell at
    all and are still padded — the mesh is never dropped — but the caller says
    so loudly.
    """
    f = [x for x in _elem_fields(line, 10) if x]
    if len(f) < 6:                        # eid pid + at least one face
        return None
    eid, pid = to_int(f[0]), to_int(f[1])
    nodes = [to_int(f[i]) for i in range(2, min(10, len(f)))]
    while nodes and nodes[-1] == 0:
        nodes.pop()
    # An INTERIOR zero (or a non-integer that read as 0) is not connectivity —
    # a thick shell fills every slot it uses. The test also keeps a malformed
    # block from turning an *ELEMENT_TSHELL_COMPOSITE ply card into an element:
    # ``1 0.6 0.0 - 2 0.4 90.0`` free-splits to six fields and would otherwise
    # pass the length test with node ids 0, 2, 0, 90.
    if not nodes or eid <= 0 or any(n <= 0 for n in nodes):
        return None
    n_given = len(nodes)
    if n_given == 6:
        n1, n2, n3, n4, n5, n6 = nodes
        nodes = [n1, n2, n3, n3, n4, n5, n6, n6]
    else:
        while len(nodes) < 8:
            nodes.append(nodes[-1])
    return eid, pid, nodes, n_given


def _tshell_ply_card(raw: List[str], idx: int):
    """One *ELEMENT_TSHELL_COMPOSITE card 2b → its (mid, thick, beta) points,
    or ``None`` when the line at *idx* is not a card 2b.

    Layout is ``MID1 THICK1 B1 - MID2 THICK2 B2 -``, eight 10-char fields with
    two integration points per card and "the fourth field must be zero or blank
    to be interpreted as a Card 2b" (Vol I R16 p.2705) — verified by an
    LS-PrePost round trip, whose ruler reads
    ``$#    mid1    thick1        b1         -      mid2    thick2        b2``.

    That blank-4th-field rule is also what ENDS the variable-length ply block:
    the number of integration points is stated nowhere, only by "the number of
    entries on these cards", so the walk has to recognise the next element's own
    connectivity card. It cannot do that by content — guessing "all fields are
    integers" is exactly the trap ``_screen_provisional_elements`` exists to
    catch — so it counts CELLS. A connectivity card names at least six ids; a
    ply card names three or six values with the gap columns 4 and 8 blank or
    zero. Those two shapes never collide.

    FREE-FORMAT card 2b needs its own branch, because ``_card`` falls back to a
    whitespace split whenever a fixed slice contains internal whitespace: the
    card ``1 0.6 0.0  2 0.4 90.0`` then arrives as six tokens whose FOURTH is
    the second MID, and a purely positional 8-slot reading rejects the line —
    measured as a whole layup vanishing with no message, and on the
    *INCLUDE_TRANSFORM side as node offsets being added to ``2`` and ``90.0``.
    The branch is taken on the SAME test ``_card`` uses to fall back, never on
    the token count alone: a properly fixed card with blank gap columns
    whitespace-splits to six tokens too, and remapping THAT would move MID2 out
    of its column.
    """
    if idx >= len(raw):
        return None
    line = raw[idx]
    fixed = parse_fixed(line, 8, 10)
    if any(" " in x.strip() or "," in x for x in fixed):
        tokens = parse_free(line)
        if len(tokens) in (3, 6):
            # Gap columns omitted: MID THICK B [MID THICK B].
            f = ([tokens[0], tokens[1], tokens[2], ""]
                 + ([tokens[3], tokens[4], tokens[5], ""] if len(tokens) == 6
                    else ["", "", "", ""]))
        else:
            f = tokens + [""] * max(0, 8 - len(tokens))
    else:
        f = fixed
    if not f or not f[0].strip():
        return None
    for gap in (3, 7):
        cell = f[gap].strip() if len(f) > gap else ""
        if cell and to_float(cell, float("nan")) != 0.0:
            return None
    pts = []
    for im, it, ib in ((0, 1, 2), (4, 5, 6)):
        if len(f) <= im or not f[im].strip():
            continue
        mid = to_int(f[im], -10 ** 9)
        if mid == -10 ** 9:               # not a number → not a ply card
            return None
        pts.append((mid,
                    to_float(f[it]) if len(f) > it else 0.0,
                    to_float(f[ib]) if len(f) > ib else 0.0))
    return pts or None


def handle_element_tshell(block: Block, state: ConversionState) -> None:
    """*ELEMENT_TSHELL and its _BETA / _COMPOSITE spellings → /BRICK.

    dyna2rad converts the bare keyword only, and even there the CFG declares no
    BETA attribute and no option at all (``Keyword971/ELEMENTS/tshell.cfg`` is
    one ``CARD`` line), so ``*ELEMENT_TSHELL_BETA`` and
    ``*ELEMENT_TSHELL_COMPOSITE`` are unmatched headers whose WHOLE BLOCK it
    drops — elements included. Here every spelling keeps its mesh:

    * ``_BETA`` card 2a is five F16 fields with BETA in cols 65-80 (the manual's
      10-column table is wrong; confirmed by an LS-PrePost round trip, which
      re-emits the ruler ``$# - - - - beta``). The angle rides on the element
      and the writer folds it into the property, because /BRICK has no
      per-element angle column.
    * ``_COMPOSITE`` card 2b is the variable-length ply block (see
      ``_tshell_ply_card``). Radioss has no per-element layup either, so the
      writer promotes it to a /PROP/TYPE22 only when every thick shell on the
      part declares the same stack, and warn-drops it otherwise.
    * an UNRECOGNIZED suffix takes the provisional path: keep every line that
      can only be connectivity, mark it, and let
      ``_screen_provisional_elements`` check it against the node table.
    """
    opts, unknown = _elem_options(block.keyword, "ELEMENT_TSHELL",
                                  _TSHELL_SUFFIX_TOKENS)
    raw = block.raw
    if unknown and _elem_block_is_not_a_mesh(block, state, unknown):
        return

    if unknown:
        # See handle_element_shell: kept by CONTENT, marked provisional, and
        # screened against the node table before it reaches the deck.
        rec = ProvisionalElemBlock(block.keyword, "tshell",
                                   "_" + "_".join(unknown))
        seen_eids: set = set()
        for line in raw:
            if not _is_connectivity_card(line, 6):
                if line.strip():
                    rec.n_unparsed += 1
                continue
            parsed = _parse_tshell_base(line)
            if parsed is None:
                rec.n_unparsed += 1
                continue
            eid, pid, nodes, _n_given = parsed
            if eid in seen_eids:
                rec.n_unparsed += 1
                continue
            seen_eids.add(eid)
            state.tshell_elems.append(
                TshellElem(eid, pid, nodes, provisional=True))
            rec.eids.append(eid)
        state.provisional_elem_blocks.append(rec)
        return

    n_penta = 0
    n_odd = 0
    n_rejected = 0
    n_plied = 0
    n_ply_cards = 0
    n_beta_offcol = 0
    i = 0
    while i < len(raw):
        parsed = _parse_tshell_base(raw[i])
        if parsed is None:
            # A line the connectivity reader refuses — an interior zero, a
            # non-integer id, a truncated card. Counted so the loss is never
            # silent: the orphan census cannot see it (no element was ever
            # created) and the deck would simply be short a mesh line.
            if raw[i].strip() and not raw[i].lstrip().startswith("$"):
                n_rejected += 1
            i += 1
            continue
        eid, pid, nodes, n_given = parsed
        if n_given == 6:
            n_penta += 1
        elif n_given < 8:
            n_odd += 1
        i += 1
        beta = 0.0
        if "BETA" in opts and i < len(raw):
            # Card 2a: five F16 cells, only the fifth (cols 65-80) defined.
            # Consumed BY COUNT — the card is mandatory under the option and a
            # blank one is a card, not padding (the #117 rule).
            fb = _card(raw, i, fixed=True, n=5, w=16)
            if len(fb) > 4 and fb[4].strip():
                beta = to_float(fb[4])
            else:
                # The manual's own table shows BETA in field 5 of a TEN-column
                # card (Vol I R14 p.19-137), i.e. cols 41-50, while LS-PrePost
                # writes the five-F16 ruler this reader is pinned to. A card in
                # the other spelling has its angle OUTSIDE cols 65-80, and
                # reading it as 0.0 would silently zero a real material
                # rotation — the worst available failure mode on the one layout
                # claim here that rests on a round trip rather than the manual.
                # So take it, and say where it came from.
                alt = _card(raw, i, fixed=True, n=10, w=10)
                cells = [c.strip() for c in (alt or []) if c.strip()]
                _NOT_A_NUMBER = -1.0e300
                if len(cells) == 1 and \
                        to_float(cells[0], _NOT_A_NUMBER) != _NOT_A_NUMBER:
                    beta = to_float(cells[0])
                    if beta:
                        n_beta_offcol += 1
            i += 1
        plies: List[CompositePly] = []
        if "COMPOSITE" in opts:
            while i < len(raw):
                pts = _tshell_ply_card(raw, i)
                if pts is None:
                    break
                plies += [CompositePly(mid=m, thick=t, beta=b)
                          for (m, t, b) in pts]
                n_ply_cards += 1
                i += 1
            if plies:
                n_plied += 1
                state.tshell_elem_plies[eid] = plies
        state.tshell_elems.append(TshellElem(eid, pid, nodes, beta))

    if n_penta:
        state.warn(
            f"*{block.keyword}: {n_penta} card(s) name six nodes (or two "
            "trailing zeros) instead of eight. LS-DYNA has no six-field form — "
            "a thick shell is always eight-SLOT and the pentahedron is written "
            "n1 n2 n3 n3 n4 n5 n6 n6, repeating ids rather than blanking slots "
            "(Vol I R14 p.19-139 Remark 1) — so the six ids were read as that "
            "pentahedron's own n1..n6 and expanded to the manual's 8-slot "
            "spelling. Volume, shape and thickness direction are preserved; "
            "write the cards in the 8-slot form to state it unambiguously.")
    if n_odd:
        state.warn(
            f"*{block.keyword}: {n_odd} card(s) name four, five or seven nodes. "
            "A thick shell has eight slots and no LS-DYNA form is that short, "
            "so the missing ones were filled by repeating the last id — which "
            "IS a valid degenerate hex for seven ids (a pyramid) but collapses "
            "a whole face for four or five, so the ELEMENT VOLUME is very "
            "likely wrong. The mesh is kept; fix the source cards.")
    if n_rejected:
        state.warn(
            f"*{block.keyword}: {n_rejected} non-blank line(s) in the block "
            "are neither a connectivity card nor an option card and were "
            "SKIPPED — an interior zero node, a non-numeric id or a truncated "
            "line. Each one is a thick shell that is NOT in the converted "
            "deck, and the orphan census cannot report it because no element "
            "was ever created from it. Check the block for a stray or "
            "misaligned line.")
    if n_beta_offcol:
        state.warn(
            f"*{block.keyword}: {n_beta_offcol} BETA card(s) carry the angle "
            "OUTSIDE columns 65-80. k2rad's card-2a reader is pinned to the "
            "five-F16 ruler LS-PrePost writes ($# - - - - beta); the manual's "
            "own table instead shows BETA in field 5 of a TEN-column card. The "
            "value was read from the column it was found in rather than "
            "treated as blank — verify the angle in the converted /PROP.")
    if n_plied:
        state.warn(
            f"*{block.keyword}: {n_plied} element(s) carry a per-element ply "
            f"stack ({n_ply_cards} card(s) of MID/THICK/B). Radioss has no "
            "per-element layup — /BRICK carries connectivity only — so the "
            "stack can survive only as a per-PART /PROP/TYPE22, which needs "
            "every thick shell on the part to declare the SAME stack. The "
            "writer reports per part whether that held. (dyna2rad cannot read "
            "this keyword at all and drops the whole block, elements "
            "included.)")


#: The largest ``NEND`` span one *ELEMENT_SPH card may generate. LS-DYNA's
#: generator writes one card per id from NID to NEND, so a typo'd NEND (or a
#: NEND that is really a second particle's id) would otherwise fabricate
#: millions of particles on nodes that do not exist. Every real generated block
#: in the corpus is far below this; anything above it is reported and the single
#: written card is kept.
_SPH_NEND_MAX_SPAN = 1_000_000


def _parse_sph_cell(line: str):
    """One *ELEMENT_SPH card → ``(nid, pid, mass, nend)`` or ``None``.

    Card 1 is ``NID(I8) PID(I8) MASS(F16) NEND(I8)`` — the layout the R16/R17
    manual's column table gives and an LS-PrePost round trip confirms
    (``$#   nid     pid            mass      nend``; note LS-PrePost right-justifies
    NEND across cols 33-42 rather than 33-40, which is why the tail is read
    whole rather than sliced at 40).

    A WHITESPACE split is tried first and preferred whenever it yields a
    complete card, because that is the reading that survives both of the
    column-layout variants in the wild: a deck writing MASS in EIGHT columns
    with NEND at 25-32 fuses those two cells under a 16-wide slice (measured on
    the native reader: ``0.002`` and ``108`` became ``0.002108``), and a deck
    written with I10 ids cuts every field short under an I8 slice. The fixed
    slice is the fallback for the one case the split cannot handle — ids wide
    enough to fill all eight columns, which glues NID and PID into one token.

    One shape the split alone cannot read: a BLANK MASS with a populated NEND.
    ``"       1       1                       8"`` splits to three tokens and
    the third IS a valid float, so the free reading makes the range generator
    into an 8-mass-unit particle and loses the whole cloud. The columns
    disambiguate it exactly — the MASS cell is blank and the NEND cell is not —
    so a three-token card is cross-checked against the fixed slice before the
    split is believed.

    ``mass`` is returned SIGNED; the caller folds the sign (and the ``_VOLUME``
    suffix) into the Flag column.
    """
    data = _strip_inline_comment(line)
    if not data.strip():
        return None
    toks = parse_free(data)
    f = None
    if len(toks) >= 2 and _is_int_token(toks[0]) and _is_int_token(toks[1]):
        if len(toks) == 2 or _is_float_token(toks[2]):
            f = toks + [""] * max(0, 4 - len(toks))
    if f is not None and len(toks) == 3 and _is_int_token(toks[2]) \
            and not data[16:32].strip() and data[32:].strip():
        # Third token is an integer sitting in the NEND columns while the MASS
        # columns are empty: a generated range, not a mass.
        f = [data[0:8], data[8:16], "", data[32:]]
    if f is None:
        f = [data[0:8], data[8:16], data[16:32], data[32:]]
        if not (_is_int_token(f[0]) and _is_int_token(f[1])):
            return None
    nid, pid = to_int(f[0]), to_int(f[1])
    if nid <= 0:
        return None
    mass = to_float(f[2]) if len(f) > 2 and f[2].strip() else 0.0
    nend = to_int(f[3]) if len(f) > 3 and f[3].strip() else 0
    return nid, pid, mass, nend


def _is_int_token(tok: str) -> bool:
    t = (tok or "").strip()
    return bool(t) and (t[1:] if t[0] in "+-" else t).isdigit()


def _is_float_token(tok: str) -> bool:
    t = (tok or "").strip()
    if not t:
        return False
    try:
        float(t.replace("D", "E").replace("d", "e"))
    except ValueError:
        return False
    return True


def handle_element_sph(block: Block, state: ConversionState) -> None:
    """*ELEMENT_SPH and its _VOLUME spelling → /SPHCEL.

    An SPH particle has no connectivity — it IS a node with a mass — so this
    handler's whole job is the MASS column, and three of its conventions are
    ones neither dyna2rad nor OpenRadioss's own native .k reader implements:

    * ``MASS < 0`` is a VOLUME ("The absolute value will be used as volume …
      SPH element mass is calculated by |MASS| x rho"). Passed through as a
      negative mass the starter discards it and falls back to the fabricated
      ``Mp = 1`` — measured, ``TOTAL MASS = 8.0`` instead of ``1.6E-02``.
    * the ``_VOLUME`` suffix means the same thing with a positive number.
      Measured through the native reader, a ``_VOLUME`` block came out wrong by
      exactly rho (``1.6E-05`` instead of ``1.6E-02``).
    * ``NEND > 0`` GENERATES the cards from NID to NEND with this card's PID and
      MASS. Neither reader expands it (measured ``NUMSPH = 1``), which is a
      whole particle cloud silently missing.

    A blank or zero MASS is kept as Flag 0 and reported by the writer, not
    silently defaulted: Radioss answers a type-0 particle with the property's
    ``Mp``, and if that is also unset it invents 1.0 mass unit per particle with
    only WARNING 138 to say so.
    """
    opts, unknown = _elem_options(block.keyword, "ELEMENT_SPH",
                                  _SPH_SUFFIX_TOKENS)
    raw = block.raw
    if unknown and _elem_block_is_not_a_mesh(block, state, unknown):
        return
    is_volume = "VOLUME" in opts

    if unknown:
        # See handle_element_shell: kept by CONTENT, marked provisional, and
        # screened against the node table before it reaches the deck. The
        # content test is SPH-specific — a particle card's third cell is a
        # float, so the all-integers test the other families use would reject
        # every real card here.
        rec = ProvisionalElemBlock(block.keyword, "sph",
                                   "_" + "_".join(unknown))
        seen: set = set()
        for line in raw:
            parsed = _parse_sph_cell(line)
            if parsed is None or parsed[1] <= 0:
                if line.strip():
                    rec.n_unparsed += 1
                continue
            nid, pid, mass, _nend = parsed
            if nid in seen:
                rec.n_unparsed += 1
                continue
            seen.add(nid)
            flag, mag = _sph_flag_and_mass(mass, is_volume)
            state.sph_elems.append(
                SphCell(nid, pid, mag, flag, provisional=True))
            rec.eids.append(nid)
        state.provisional_elem_blocks.append(rec)
        return

    n_rejected = 0
    n_negative = 0
    n_zero = 0
    n_generated = 0
    n_gen_cards = 0
    n_gen_refused = 0
    for line in raw:
        parsed = _parse_sph_cell(line)
        if parsed is None:
            # A line the particle reader refuses. Counted so the loss is never
            # silent: no cell was created, so the orphan census cannot see it.
            if line.strip() and not line.lstrip().startswith("$"):
                n_rejected += 1
            continue
        nid, pid, mass, nend = parsed
        flag, mag = _sph_flag_and_mass(mass, is_volume)
        if mass < 0.0:
            n_negative += 1
        elif mag == 0.0:
            n_zero += 1
        ids = [nid]
        if nend > nid:
            if nend - nid > _SPH_NEND_MAX_SPAN:
                n_gen_refused += 1
            else:
                ids = list(range(nid, nend + 1))
                n_gen_cards += 1
                n_generated += len(ids) - 1
        for k, gid in enumerate(ids):
            state.sph_elems.append(
                SphCell(gid, pid, mag, flag, generated=(k > 0)))

    if n_rejected:
        state.warn(
            f"*{block.keyword}: {n_rejected} non-blank line(s) in the block are "
            "not a particle card and were SKIPPED — a non-numeric NID or PID, "
            "or a truncated line. Each one is an SPH particle that is NOT in "
            "the converted deck, and the orphan census cannot report it because "
            "no cell was ever created from it. Check the block for a stray or "
            "misaligned line.")
    if n_negative:
        state.warn(
            f"*{block.keyword}: {n_negative} card(s) state a NEGATIVE mass, "
            "which LS-DYNA reads as a VOLUME (\"the absolute value will be used "
            "as volume … SPH element mass is calculated by |MASS| x rho\"). "
            "They are emitted as /SPHCEL Type 2 with |MASS| in the value column, "
            "so the particle mass is rho x |MASS| exactly as the deck asks. "
            "(dyna2rad copies the sign through and the starter then DISCARDS the "
            "value and falls back to the property's fabricated Mp = 1 — measured "
            "8.0 kg where the deck states 0.016 kg.)")
    if is_volume:
        state.warn(
            f"*{block.keyword}: the _VOLUME suffix makes the MASS column a "
            "particle VOLUME, so every cell is emitted as /SPHCEL Type 2 and "
            "Radioss multiplies by the part's density itself "
            "(spinit3.F:143-145). (dyna2rad's CFG declares no option on this "
            "keyword and reads the volumes as masses — wrong by exactly rho.)")
    if n_zero:
        state.warn(
            f"*{block.keyword}: {n_zero} card(s) leave the MASS column blank or "
            "zero. Those particles carry NO mass of their own and fall back on "
            "the /PROP/SPH particle mass Mp, so the mass they get is the "
            "section's, NOT one the deck stated per particle. k2rad always "
            "writes a POSITIVE Mp, which keeps the starter's own fabrication "
            "out of it (hm_read_prop34.F:235-239 answers a non-positive Mp by "
            "inventing 1.0 IN THE DECK'S MASS UNIT behind a single WARNING 138 "
            "— measured, four blank-mass particles gave TOTAL MASS = 4.0). But "
            "if NO particle of the section states a mass, that positive Mp is "
            "one k2rad had to derive rather than read, and the writer's own "
            "report for that section names it and states the number it wrote.")
    if n_generated:
        state.warn(
            f"*{block.keyword}: {n_gen_cards} card(s) use the NEND range "
            f"generator and were EXPANDED into {n_generated} additional "
            "particle(s) (\"*ELEMENT_SPH cards are generated between NID to "
            "NEND using current PID and MASS data\"). Generated ids whose "
            "*NODE does not exist are dropped by the writer with their own "
            "count — a /SPHCEL id with no node is starter ERROR 78. (Neither "
            "dyna2rad nor OpenRadioss's native .k reader expands NEND at all: "
            "measured, a card with NEND=108 produced NUMSPH = 1.)")
    if n_gen_refused:
        state.warn(
            f"*{block.keyword}: {n_gen_refused} card(s) name a NEND more than "
            f"{_SPH_NEND_MAX_SPAN} ids above their NID. That is far outside any "
            "real generated block, so the range was NOT expanded and only the "
            "written card became a particle — check whether the column really "
            "holds NEND. Fix the card if the range was meant.")


def _sph_flag_and_mass(mass: float, is_volume: bool):
    """(/SPHCEL Type, magnitude) for one LS-DYNA MASS cell.

    Type 1 = the value is a mass, Type 2 = the value is a volume
    (``hm_read_sphcel.F:221-223`` / ``spinit3.F:139-153``). A blank cell keeps
    Type 1 with a zero magnitude, which the emitter turns into a blank column so
    the starter's own "type 0" fallback applies.
    """
    if is_volume or mass < 0.0:
        return 2, abs(mass)
    return 1, mass


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
    """One *ELEMENT_BEAM connectivity card → (eid, pid, n1, n2, n3, rt1, rt2)
    or None.

    Field order is EID PID N1 N2 N3 RT1 RR1 RT2 RR2 LOCAL (Vol I R17 p.19-5).
    Only the TRANSLATIONAL releases RT1 (field 6) and RT2 (field 8) are kept —
    see BeamElem for why the rotational pair and LOCAL are not.
    """
    f = _positional_elem_fields(line, 10)
    # The orientation node N3 is optional (truss/ELFORM-3 beams omit it),
    # so 4 fields (eid pid n1 n2) is a complete card.
    if len(f) < 4 or not f[3]:
        return None
    eid, pid = to_int(f[0]), to_int(f[1])
    n1, n2 = to_int(f[2]), to_int(f[3])
    n3 = to_int(f[4]) if len(f) > 4 else 0
    rt1 = to_int(f[5]) if len(f) > 5 else 0
    rt2 = to_int(f[7]) if len(f) > 7 else 0
    return eid, pid, n1, n2, n3, rt1, rt2


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
            eid, pid, n1, n2, n3, rt1, rt2 = parsed
            if eid in seen_eids:
                rec.n_unparsed += 1
                continue
            seen_eids.add(eid)
            state.beam_elems.append(
                BeamElem(eid, pid, n1, n2, n3, provisional=True,
                         rt1=rt1, rt2=rt2))
            rec.eids.append(eid)
        state.provisional_elem_blocks.append(rec)
        return

    i = 0
    while i < len(raw):
        parsed = _parse_beam_base(raw[i])
        if parsed is None:
            i += 1
            continue
        eid, pid, n1, n2, n3, rt1, rt2 = parsed
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
        state.beam_elems.append(BeamElem(eid, pid, n1, n2, n3, vx, vy, vz,
                                         rt1=rt1, rt2=rt2))

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

    PF is the deforc PRINT flag, not a solution parameter (Manual p. 19-32:
    "EQ.0: forces are printed in DEFORC file, EQ.1: forces are not printed
    DEFORC file"), so PF=1 leaves the /SPRING alone and only drops the element
    from the *DATABASE_DEFORC selection — see state.deforc_suppressed_eids.
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
        if len(f) > 6 and to_int(f[6]) == 1:
            state.deforc_suppressed_eids.add(eid)
        offset = to_float(f[7]) if len(f) > 7 else 0.0
        state.discrete_elems.append(DiscreteElem(eid, pid, n1, n2, vid, s, offset))


# ─────────────────────────────────────────────────────────────────────────────
# Shared _INERTIA card walker (*PART_INERTIA and *CONSTRAINED_NODAL_RIGID_BODY_
# INERTIA carry the SAME data — Vol I R17 Appendix X p.75-16)
# ─────────────────────────────────────────────────────────────────────────────

def _read_rigid_inertia(raw: List[str], idx: int):
    """Read the `_INERTIA` cards starting at ``raw[idx]``.

    Returns ``(RigidInertia, n_cards_consumed)``. Three cards are consumed
    unconditionally and a fourth only when the card-3 ``IRCS`` field reads 1.

    **Blank cards are CARDS, not whitespace.** LS-PrePost writes an all-default
    card as a line of blanks (and writes every one of the eight columns even when
    unused), so a blank card 5 with `VTX..VRZ` all zero is normal output. The
    parser preserves such a line as ``""`` precisely so its card POSITION holds
    (``parser.py``: "an all-blank fixed-format card means all defaults"), and the
    walk must therefore consume by COUNT and never skip a blank line. Skipping
    one shifts everything below it up by a card — and because card 6 is
    conditional on a value read from card 3, a skipped blank card 3 makes ``IRCS``
    read 0, card 6 is not consumed, and on ``*PART`` the next part's HEADING gets
    eaten as a data card. That is the exact PR #117 positional-consumption
    failure mode.
    """
    inr = RigidInertia()
    # Card 3: XC YC ZC TM IRCS NODEID
    f3 = _card(raw, idx, fixed=True, n=8, w=10)
    if f3:
        inr.xc = to_float(f3[0])
        inr.yc = to_float(f3[1]) if len(f3) > 1 else 0.0
        inr.zc = to_float(f3[2]) if len(f3) > 2 else 0.0
        inr.tm = to_float(f3[3]) if len(f3) > 3 else 0.0
        inr.ircs = to_int(f3[4]) if len(f3) > 4 else 0
        inr.nodeid = to_int(f3[5]) if len(f3) > 5 else 0
    # Card 4: IXX IXY IXZ IYY IYZ IZZ  (note the LS-DYNA order — the Radioss
    # cards are Jxx Jyy Jzz / Jxy Jyz Jxz, a pure permutation, see RigidInertia)
    f4 = _card(raw, idx + 1, fixed=True, n=8, w=10)
    if f4:
        inr.ixx = to_float(f4[0])
        inr.ixy = to_float(f4[1]) if len(f4) > 1 else 0.0
        inr.ixz = to_float(f4[2]) if len(f4) > 2 else 0.0
        inr.iyy = to_float(f4[3]) if len(f4) > 3 else 0.0
        inr.iyz = to_float(f4[4]) if len(f4) > 4 else 0.0
        inr.izz = to_float(f4[5]) if len(f4) > 5 else 0.0
    # Card 5: VTX VTY VTZ VRX VRY VRZ
    f5 = _card(raw, idx + 2, fixed=True, n=8, w=10)
    if f5:
        inr.vtx = to_float(f5[0])
        inr.vty = to_float(f5[1]) if len(f5) > 1 else 0.0
        inr.vtz = to_float(f5[2]) if len(f5) > 2 else 0.0
        inr.vrx = to_float(f5[3]) if len(f5) > 3 else 0.0
        inr.vry = to_float(f5[4]) if len(f5) > 4 else 0.0
        inr.vrz = to_float(f5[5]) if len(f5) > 5 else 0.0
    used = 3
    # Card 6 — "optional unless IRCS = 1" (Card Summary, Vol I R17 p.37-4). The
    # condition is a VALUE just parsed, not an option name.
    if inr.ircs == 1:
        f6 = _card(raw, idx + 3, fixed=True, n=8, w=10)
        if f6:
            inr.xl = to_float(f6[0])
            inr.yl = to_float(f6[1]) if len(f6) > 1 else 0.0
            inr.zl = to_float(f6[2]) if len(f6) > 2 else 0.0
            inr.xlip = to_float(f6[3]) if len(f6) > 3 else 0.0
            inr.ylip = to_float(f6[4]) if len(f6) > 4 else 0.0
            inr.zlip = to_float(f6[5]) if len(f6) > 5 else 0.0
            inr.cid = to_int(f6[6]) if len(f6) > 6 else 0
        # Records whether the card was THERE (``_card`` returns [] past the end of
        # the block), not just whether IRCS asked for it. The writer needs the two
        # apart: "IRCS=1 and the block ended" and "card 6 present but its vectors
        # are degenerate" are different source-deck defects with different fixes.
        inr.has_local_card = bool(f6)
        # The card is still STRIDDEN over unconditionally — the card count follows
        # IRCS, and a *PART block whose next set exists must not have its HEADING
        # eaten. Past the end of the block the extra step is harmless.
        used = 4
    return inr, used


# ─────────────────────────────────────────────────────────────────────────────
# Parts
# ─────────────────────────────────────────────────────────────────────────────

#: The six `*PART` OPTION slots and the tokens each accepts (Vol I R17 p.37-2).
#: "For OPTION1 ... <BLANK> / INERTIA / REPOSITION.  For OPTION2 ... <BLANK> /
#: CONTACT.  For OPTION3 ... <BLANK> / PRINT.  For OPTION4 ... <BLANK> /
#: ATTACHMENT_NODES.  For OPTION5 ... <BLANK> / AVERAGED.  For OPTION6 ...
#: <BLANK> / FIELD.  **Options 1, 2, 3, 4, 5, and 6 may be specified in any order
#: on the *PART card.**"
#:
#: Slot order here is the OPTION-NUMBER order, which is NOT the card order — see
#: _PART_OPTION_CARDS.
_PART_OPTION_SLOTS = (
    ("INERTIA", "REPOSITION"),
    ("CONTACT",),
    ("PRINT",),
    ("ATTACHMENT_NODES",),
    ("AVERAGED",),
    ("FIELD",),
)

#: Every `*PART` option token, for suffix tokenisation. ATTACHMENT_NODES is the
#: one token that itself contains an underscore, so the suffix cannot simply be
#: split on "_" — _part_options matches longest-first instead.
_PART_OPTION_TOKENS = tuple(sorted(
    (t for slot in _PART_OPTION_SLOTS for t in slot),
    key=len, reverse=True))

#: (option token, number of data cards it adds) in **CARD-SUMMARY order** (Vol I
#: R17 p.37-4/37-5), which is fixed and independent of the spelling order:
#: INERTIA cards 3/4/5(/6) -> REPOSITION card 7 -> CONTACT card 8 -> PRINT card 9
#: -> ATTACHMENT_NODES card 10 -> FIELD card 11. AVERAGED adds no card.
#: INERTIA is handled separately because its card count depends on IRCS.
_PART_OPTION_CARDS = (
    ("REPOSITION", 1),          # CMSN MDEP MOVOPT
    ("CONTACT", 1),             # FS FD DC VC OPTT SFT SSF CPARM8
    ("PRINT", 1),               # PRBF
    ("ATTACHMENT_NODES", 1),    # ANSID
    ("AVERAGED", 0),
    ("FIELD", 1),               # FIDBO
)


def _part_options(keyword: str):
    """Split a `*PART...` keyword into ``(option set, unknown tokens)``.

    Tokenises the suffix into an order-INDEPENDENT set rather than matching the
    whole suffix against a closed list of canonical spellings. Altair's own
    LS-DYNA reader does the latter (``Keyword971_R8.0/COMPONENT/part.cfg`` tests
    ``_opt`` against ``""``, ``"_INERTIA"``, ``"_INERTIA_CONTACT"``, ... and
    ``_CONTACT_INERTIA`` falls into the final ``else``), which silently
    mis-parses a legal spelling the manual explicitly permits.
    """
    rest = keyword[len("PART"):]
    opts: set = set()
    unknown: List[str] = []
    while rest:
        if not rest.startswith("_"):
            unknown.append(rest)
            break
        rest = rest[1:]
        for tok in _PART_OPTION_TOKENS:
            if rest == tok or rest.startswith(tok + "_"):
                opts.add(tok)
                rest = rest[len(tok):]
                break
        else:
            # Not a *PART option: take the whole remainder as one unknown token
            # so the caller can name it in a warning.
            unknown.append(rest)
            break
    return opts, unknown


def _part_option_keywords():
    """Every legal `*PART` spelling, generated rather than hand-listed.

    The six OPTION slots "may be specified in any order" (Vol I R17 p.37-2), so
    every permutation of the chosen tokens is a legal keyword and ``dispatch()``
    — an exact dict lookup — needs a key for each: 3588 in total. Hand-listing
    the canonical orderings is what the native reader does, and 3576 of those
    spellings then fall through it.

    This matters more here than for any other family: without a `*PART` key the
    block lands in ``skipped_keywords``, the PART is never registered, and
    ``_make_parts_and_elements`` (which emits elements inside the
    ``state.parts`` loop) drops EVERY ELEMENT on it. The mesh is gone, not just
    the option's data — the same failure the #116 rigid-wall generator and the
    #91 element-suffix fallback were written to close. ``_OFFSET_SPECS`` in
    ``assembly.py`` is generated from this same function so the two cannot
    drift apart.

    Yields keyword strings, including the bare ``"PART"``.
    """
    # A choice per slot: nothing, or one of that slot's tokens.
    choices = [(None,) + slot for slot in _PART_OPTION_SLOTS]
    seen: set = set()

    def _walk(i: int, picked: List[str]):
        if i == len(choices):
            for combo in _permutations(picked, len(picked)):
                kw = "PART" + "".join("_" + t for t in combo)
                if kw not in seen:
                    seen.add(kw)
                    yield kw
            return
        for tok in choices[i]:
            yield from _walk(i + 1, picked if tok is None else picked + [tok])

    yield from _walk(0, [])


def handle_part(block: Block, state: ConversionState) -> None:
    """`*PART` and EVERY legal option stacking (`_INERTIA`, `_CONTACT`,
    `_REPOSITION`, `_PRINT`, `_ATTACHMENT_NODES`, `_AVERAGED`, `_FIELD`, in any
    order).

    "Card Sets.  Repeat as many sets of data cards as desired (Cards 1 through
    10, depending on the keyword options).  This input ends at the next keyword
    ("*") card." (Vol I R17 p.37-4) — so a set is ``HEADING`` + the data card +
    whatever cards this block's OPTION SET demands, and the set repeats. Every
    part under one keyword gets the same option cards.

    The card walk is driven by the option set at the CARD-SUMMARY order, never by
    a fixed stride and never by guessing at a card's content: with the option set
    known there is no reason to guess, and the extra cards are floats where cards
    1-2 are integers, so a content test would look convincing right up to a
    `*PART_INERTIA` whose ``IXX`` happens to be integral. Aliasing this handler
    onto `*PART_INERTIA` with the OLD stride-of-2 loop was measured to register a
    phantom ``/PART/4321`` (from the ``IXX=4321.0`` card) with ``secid=0``,
    ``mid=0`` and a coordinate card as its title, silently.
    """
    opts, unknown = _part_options(block.keyword)
    raw = block.raw
    if len(raw) < 2:
        title = raw[0].strip() if raw else ""
        state.warn(f"*PART missing data card – skipped (title='{title}')")
        return
    n_reposition = n_print = n_attach = n_field = n_averaged = 0
    truncated = False
    i = 0
    # A set needs at least the HEADING + the data card. The guard is exactly the
    # old ``range(0, len(raw) - 1, 2)`` bound, so a plain *PART block walks
    # byte-identically (an odd trailing line is ignored, a trailing pair of blank
    # lines still reports "data card with no part id" as it always has).
    while i + 1 < len(raw):
        title = raw[i].strip()
        # Data card: pid secid mid eosid hgid grav adpopt tmid
        f = _card(raw, i + 1, fixed=True, n=8, w=10)
        i += 2
        pid   = to_int(f[0])
        secid = to_int(f[1])
        mid   = to_int(f[2])
        # EOSID (field 4, cols 31-40) → the *EOS_* bound to this part's material
        # (routes *MAT_JOHNSON_COOK to /MAT/LAW4 + /EOS).
        eosid = to_int(f[3]) if len(f) > 3 else 0
        # HGID (field 5, cols 41-50) → the *HOURGLASS card overriding
        # *CONTROL_HOURGLASS for this part (0 = global card / defaults).
        hgid  = to_int(f[4]) if len(f) > 4 else 0
        # TMID (field 8, cols 71-80) → the *MAT_THERMAL_* card bound to this
        # part. A SEPARATE id namespace from MID (Vol II R17, *MAT_THERMAL
        # header: "This number is independent of the material ID number"), and
        # the only place a deck states which thermal properties a part has —
        # it supplies the /HEAT/MAT RHO0_CP and AS. Fields 6 (GRAV) and 7
        # (ADPOPT) are read into f and deliberately unused: Radioss takes
        # gravity from /GRAV over a node group, and there is no adaptivity.
        tmid  = to_int(f[7]) if len(f) > 7 else 0

        # ── Option cards, in Card-Summary order ──────────────────────────────
        inertia = None
        if "INERTIA" in opts:
            inertia, used = _read_rigid_inertia(raw, i)
            i += used
        for tok, n_cards in _PART_OPTION_CARDS:
            if tok not in opts:
                continue
            if tok == "AVERAGED":
                n_averaged += 1
                continue
            fo = _card(raw, i, fixed=True, n=8, w=10)
            i += n_cards
            if tok == "CONTACT":
                if pid > 0:
                    state.part_contacts[pid] = PartContact(
                        pid,
                        fs=to_float(fo[0]) if fo else 0.0,
                        fd=to_float(fo[1]) if len(fo) > 1 else 0.0,
                        dc=to_float(fo[2]) if len(fo) > 2 else 0.0,
                        vc=to_float(fo[3]) if len(fo) > 3 else 0.0,
                        optt=to_float(fo[4]) if len(fo) > 4 else 0.0,
                        sft=to_float(fo[5]) if len(fo) > 5 else 0.0,
                        ssf=to_float(fo[6]) if len(fo) > 6 else 0.0,
                        cparm8=to_float(fo[7]) if len(fo) > 7 else 0.0)
            elif tok == "REPOSITION":
                if any(x.strip() for x in fo):
                    n_reposition += 1
            elif tok == "PRINT":
                if fo and to_int(fo[0]):
                    n_print += 1
            elif tok == "ATTACHMENT_NODES":
                if fo and to_int(fo[0]):
                    n_attach += 1
            elif tok == "FIELD":
                if fo and to_int(fo[0]):
                    n_field += 1

        # A set whose option cards ran off the end of the block: the values above
        # came from empty _card() reads, so say so instead of trusting them.
        if i > len(raw) and opts:
            truncated = True
        if pid <= 0:
            state.warn(f"*PART: data card with no part id – skipped (title='{title}')")
            if truncated:
                break
            continue
        state.parts[pid] = PartData(pid, title, secid, mid, hgid, eosid,
                                    tmid)
        if inertia is not None:
            if inertia.has_mass_data() or inertia.has_velocity():
                state.part_inertias[pid] = inertia
            else:
                # LS-PrePost writes an all-blank card set when the option is
                # present but unused. Remark 3 forbids DERIVING the values, so
                # "all blank" can only mean "no override" — emitting Mass = 0 and
                # Jxx = 0 with ICoG = 4 would instead throw the mesh's own mass
                # away (starter ERROR 679 "total mass <= 1e-30" / ERROR 274 "min
                # principal inertia <= 0").
                state.warn(
                    f"*{block.keyword} {pid}: the _INERTIA cards are entirely "
                    "blank (no TM, no inertia tensor, no initial velocity). "
                    "*PART Remark 3 says 'all mass and inertia properties of the "
                    "body must be specified.  There are no default values', so "
                    "there is nothing to transfer — the rigid body keeps its "
                    "MESH-derived mass and inertia. Fill in TM and IXX..IZZ if "
                    "the body was meant to carry defined properties.")
        if truncated:
            state.warn(
                f"*{block.keyword}: the block ends part-way through the option "
                f"cards of part {pid} — the {'/'.join(sorted(opts))} card(s) are "
                "INCOMPLETE and any part defined below this point in the same "
                "block is UNREAD. Split the block so every card set is whole.")
            break

    if n_reposition:
        state.warn(
            f"*{block.keyword}: {n_reposition} part(s) carry _REPOSITION data "
            "(CMSN/MDEP/MOVOPT) — DROPPED. It repositions a rigid body onto a "
            "deformable master at t=0, which has no OpenRadioss counterpart; the "
            "part stays at its meshed coordinates. Pre-position the mesh instead.")
    if n_print:
        state.warn(
            f"*{block.keyword}: {n_print} part(s) carry _PRINT PRBF — DROPPED. It "
            "selects LS-DYNA rigid-body force printing (rbdout); use "
            "*DATABASE_RBDOUT, which k2rad maps to /TH/RBODY.")
    if n_attach:
        state.warn(
            f"*{block.keyword}: {n_attach} part(s) carry _ATTACHMENT_NODES ANSID "
            "— DROPPED (the node set is not attached to anything). Altair's own "
            "LS-DYNA reader does not implement this card either. Use "
            "*CONSTRAINED_EXTRA_NODES_SET, which k2rad folds into the part's "
            "/RBODY secondary-node group.")
    if n_field:
        state.warn(
            f"*{block.keyword}: {n_field} part(s) carry _FIELD FIDBO — DROPPED "
            "(no OpenRadioss counterpart for a *DEFINE_FIELD boundary).")
    if n_averaged:
        state.note_recognized_not_emitted(
            block.keyword,
            "the _AVERAGED option adds no data card and no Radioss field")
    if unknown:
        state.warn(
            f"*{block.keyword}: the option token(s) "
            f"{', '.join('_' + u for u in unknown)} are not part of the *PART "
            "grammar (INERTIA/REPOSITION, CONTACT, PRINT, ATTACHMENT_NODES, "
            "AVERAGED, FIELD). Cards 1-2 were read, so the parts and their "
            "elements are in the deck, but any extra card the unknown option "
            "adds was read as if it were the next part's HEADING — check the "
            "converted /PART list against the source deck.")


#: `*PART_`-prefixed keywords that are a DIFFERENT LS-DYNA keyword family, not a
#: `*PART` option stacking: their cards have nothing to do with ``HEADING`` +
#: ``PID SECID MID ...``, so parsing them as a `*PART` would invent phantom parts
#: with a coordinate or flag card for a title (exactly the phantom-/PART/4321
#: failure the option-driven walk in handle_part exists to prevent).
_PART_NOT_A_PART_FAMILIES = (
    "PART_ADAPTIVE_FAILURE", "PART_ADD", "PART_ANNEAL", "PART_DUPLICATE",
    "PART_MODES", "PART_MOVE", "PART_SENSOR", "PART_STACKED_ELEMENTS",
)


def handle_part_unknown_option(block: Block, state: ConversionState) -> None:
    """Prefix-fallback for a `*PART...` spelling the exact lookup missed.

    Belt to _part_option_keywords' braces: a spelling whose suffix decomposes
    into `*PART` option tokens is walked by ``handle_part`` (mesh AND options
    survive), and anything else is warn-skipped by NAME. The distinction is
    load-bearing — `*PART_SENSOR`, `*PART_ADD`, `*PART_MODES` and friends are
    separate keywords whose first card is not a heading, so running the `*PART`
    walk on them would register parts that do not exist.
    """
    if block.keyword in _PART_NOT_A_PART_FAMILIES or any(
            block.keyword.startswith(f + "_") for f in _PART_NOT_A_PART_FAMILIES):
        state.skipped_keywords.append(block.keyword)
        state.warn(
            f"*{block.keyword} is a separate LS-DYNA keyword, not a *PART option "
            "stacking — its cards do not start with a HEADING line, so it is "
            "skipped WHOLE rather than parsed as a part (which would invent "
            "phantom /PART entries from its data cards). Nothing it defines is "
            "in the converted deck.")
        return
    _opts, unknown = _part_options(block.keyword)
    if unknown:
        state.skipped_keywords.append(block.keyword)
        state.warn(
            f"*{block.keyword}: the suffix does not decompose into *PART option "
            f"tokens ({', '.join('_' + u for u in unknown)} is not one of "
            "INERTIA/REPOSITION, CONTACT, PRINT, ATTACHMENT_NODES, AVERAGED, "
            "FIELD), so the block is skipped rather than guessed at. If it "
            "defines parts, EVERY ELEMENT on them is missing from the converted "
            "deck — check the orphan-element warning below.")
        return
    handle_part(block, state)


# ─────────────────────────────────────────────────────────────────────────────
# Sections → Properties
# ─────────────────────────────────────────────────────────────────────────────

# *SECTION_SHELL keyword-option suffixes that add exactly ONE extra card per
# card set — card 4a EFG, 4b THERMAL, 4c XFEM, 4d MISC (Manual Vol I R17
# p.41-62/63). None of them reaches this handler today: the dispatcher is
# exact-key on block.keyword and only "SECTION_SHELL" is registered, so
# *SECTION_SHELL_EFG lands in the unrecognized-keyword report instead. The walk
# accounts for them anyway so that registering one later cannot silently make
# every following set mis-stride.
_SECTION_SHELL_OPTION_CARDS = ("EFG", "THERMAL", "XFEM", "MISC")

# ELFORM values that add the user-defined-shell cards 5 / 5.1 / 5.2
# (Manual Vol I R17 p.41-63): "EQ.101..105: User defined shell".
_USER_SHELL_ELFORMS = frozenset({101, 102, 103, 104, 105})


def handle_section_shell(block: Block, state: ConversionState) -> None:
    """*SECTION_SHELL (+ _TITLE/_ID) — every card SET under the header.

    "Card Sets.  For each shell section, of a type matching the keyword's
    options, include one set of data cards.  This input ends at the next keyword
    ("*") card." (Manual Vol I R17 p.41-62). Under the _TITLE option "an
    addition line is read for each section in 80a format" (p.41-1), so the title
    line repeats PER SET, not once for the block.

    A set spans ``1 (title) + 2 (cards 1-2) + ceil(NIP/8) (card 3, ICOMP=1 only)
    + 1 (card 4, keyword option) + 1 + NIPP + ceil(LMC/8) (cards 5/5.1/5.2,
    ELFORM 101-105)`` lines, every term read from that set's OWN fields, so the
    cursor is advanced by what each set actually consumed rather than by a fixed
    stride. Reading only the first set — which is what this handler used to do —
    dropped every later section silently, and a *PART pointing at one of them
    fell through to ``_auto_section_shell``'s ZERO-thickness placeholder, which
    the starter rejects.

    The title card is consumed UNCONDITIONALLY under the _TITLE option, blank or
    not: the manual reads one 80a line per set with no "if non-empty" proviso,
    and the parser deliberately preserves a blank line as a card placeholder
    (``parser.py``: "an all-blank fixed-format card means all defaults"). Eating
    a blank title as padding instead shifts the whole set up by one line and
    registers a phantom section under ``int(T1)``, which then OVERWRITES a real
    one. Only trailing padding — a tail with no non-blank line left in it — ends
    the walk.
    """
    per_set_title = _title_offset(block)
    opt_card = any(block.keyword.endswith("_" + o)
                   for o in _SECTION_SHELL_OPTION_CARDS)
    raw = block.raw
    idx = 0
    n_sets = 0
    while idx < len(raw):
        # Trailing blank padding is not a card set. Anything else — including a
        # blank line that IS this set's 80a title card — is walked, not skipped.
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        # Card 1: secid elform shrf nip propt qr/irid icomp setyp
        f1 = _card(raw, idx, fixed=True, n=8, w=10)
        # Card 2: t1 t2 t3 t4 nloc marea idof edgset
        f2 = _card(raw, idx + 1, fixed=True, n=8, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            state.warn(
                "*SECTION_SHELL: "
                + (f"after {n_sets} complete card set(s) the next card"
                   if n_sets else "the first card of the block")
                + f" ('{raw[idx][:40].strip()}') carries no positive SECID, so "
                "the walk STOPPED there and the remaining lines of the block "
                "are UNREAD — any *PART pointing at a section defined below it "
                "falls back to a zero-thickness placeholder. Split the sets "
                "k2rad cannot stride over into their own *SECTION_SHELL blocks.")
            break
        elform = to_int(f1[1]) if f1[1] else 2
        nip = to_int(f1[3]) if len(f1) > 3 else 3
        if nip < 0:
            # LS-DYNA's NIP is a COUNT; only field 6 (QR/IRID) uses a negative
            # value as a rule reference. A negative NIP used to clamp silently
            # to 2 AND mis-trim the ICOMP angle block to 2 of the deck's angles
            # with no warning at all, so a [0/45/-45/90] layup became [0, 45].
            state.warn(
                f"*SECTION_SHELL {secid}: NIP={nip} is negative. NIP is an "
                "integration-point COUNT — it is the QR/IRID field (card 1 "
                f"field 6, cols 51-60) that takes a negative value to reference "
                f"an *INTEGRATION_SHELL rule. |NIP| = {abs(nip)} is used; if the "
                "deck meant a user rule, move the negative value to field 6.")
            nip = abs(nip)
        t1 = to_float(f2[0]) if f2 else 0.0
        sec = SectionShell(secid, title, elform, nip, t1)
        # Card 2 field 8 (cols 71-80): EDGSET, the 2D-seatbelt flow-direction
        # node set. Only writer/seatbelts.py reads it, to report it as dropped.
        sec.nsid = to_int(f2[7]) if len(f2) > 7 else 0
        # QR/IRID (field 6, cols 51-60): a NEGATIVE value makes |QR| the id of a
        # user *INTEGRATION_SHELL rule (Manual Vol I R17 p.29-1). A positive or
        # zero value is the built-in quadrature rule and carries no reference.
        qr_irid = to_float(f1[5]) if len(f1) > 5 else 0.0
        if qr_irid < 0.0:
            sec.irid = int(abs(qr_irid))
        idx += 2
        # ICOMP (field 7) = 1 → a layered composite section: card 3 carries one
        # material angle B_i per through-thickness integration point.
        if len(f1) > 6 and to_int(f1[6]) == 1:
            sec.icomp = 1
            sec.betas = _read_icomp_angles(raw, idx, nip, secid, state)
            idx += ((nip if nip > 0 else 2) + 7) // 8
        # Card 4a-4d: the single card the EFG/THERMAL/XFEM/MISC option adds.
        if opt_card:
            idx += 1
        # Cards 5 / 5.1 / 5.2, ELFORM 101-105 only. Nothing on them is modelled,
        # but the CURSOR has to clear them: card 5 begins with NIPP, a POSITIVE
        # integer, so the "no positive SECID" stop above never trips on it and
        # the next set would otherwise be read out of the middle of this one.
        if elform in _USER_SHELL_ELFORMS:
            f5 = _card(raw, idx, fixed=True, n=8, w=10)
            nipp = to_int(f5[0]) if f5 else 0
            lmc = to_int(f5[5]) if len(f5) > 5 else 0
            state.warn(
                f"*SECTION_SHELL {secid}: ELFORM={elform} is a USER-DEFINED "
                "shell (*USER_INTERFACE routine), which has no Radioss "
                "counterpart — the section is converted as an ordinary "
                "/PROP/SHELL and the user routine's own integration points, "
                "extra DOFs and LMC constants (cards 5/5.1/5.2) are DROPPED. "
                "The element behaves as a standard Radioss shell, not as the "
                "deck's user element.")
            if not f5:
                state.warn(
                    f"*SECTION_SHELL {secid}: ELFORM={elform} needs card 5 "
                    "(NIPP NXDOF IUNF IHGF ITAJ LMC NHSV ILOC) but the block "
                    "ends first, so the walk STOPPED here.")
                break
            idx += 1 + max(nipp, 0) + (max(lmc, 0) + 7) // 8
        if secid in state.sec_shells:
            state.warn(
                f"*SECTION_SHELL {secid} is defined more than once — the LAST "
                "definition wins, as in LS-DYNA, so the earlier section's "
                "thickness/NIP/ELFORM are discarded and every *PART on that "
                "SECID silently takes this one's. Delete the duplicate if the "
                "two sections differ.")
        state.sec_shells[secid] = sec
        n_sets += 1


def handle_integration_shell(block: Block, state: ConversionState) -> None:
    """*INTEGRATION_SHELL — user through-thickness integration rules.

    Card 1  ``IRID NIP ESOP FAILOPT``                       (4 x I10)
    Card 2  ``S WF PID``, ONE point per card, NIP cards,    (F10 F10 I10)
            present only when ``ESOP == 0`` and ``NIP > 0``
            (``CARD_LIST(NIP)`` under ``if(ESOP == 0 && NIP > 0)``,
            INTEGRATION_RULES/integration_shell.cfg:79-86).

    The keyword has no documented "Card Sets" summary, but the general LS-DYNA
    block rule (a block ends at the next ``*``) still lets a deck stack several
    rules under one header, so the reader loops. That is strictly more
    permissive than a single-rule reader and cannot break a single-rule deck.

    ``S`` is NOT range-checked here: the CFG's ``CHECK(COMMON){ S >= -1; S <= 1; }``
    is a GUI constraint that the importer does not enforce, and an out-of-range
    S is reported by the writer (which is where the consequence lives) rather
    than being clipped away at parse time.
    """
    raw = block.raw
    idx = 0
    while idx < len(raw):
        if not raw[idx].strip():
            idx += 1
            continue
        f1 = _card(raw, idx, fixed=True, n=4, w=10)
        irid = to_int(f1[0]) if f1 else 0
        if irid <= 0:
            state.warn(
                "*INTEGRATION_SHELL: a card set with no positive IRID "
                f"('{raw[idx][:40].strip()}') cannot be referenced by any "
                "*SECTION_SHELL QR/IRID field — the rule and every card after "
                "it in this block are SKIPPED.")
            return
        rule = IntegrationShell(
            irid,
            nip=to_int(f1[1]) if len(f1) > 1 else 0,
            esop=to_int(f1[2]) if len(f1) > 2 else 0,
            failopt=to_int(f1[3]) if len(f1) > 3 else 0)
        idx += 1
        if rule.esop == 0 and rule.nip > 0:
            for _ in range(rule.nip):
                # Blank placeholders hold a card position but carry no point.
                while idx < len(raw) and not raw[idx].strip():
                    idx += 1
                if idx >= len(raw):
                    break
                p = _card(raw, idx, fixed=True, n=3, w=10)
                rule.points.append(IntegrationPoint(
                    s=to_float(p[0]) if p else 0.0,
                    wf=to_float(p[1]) if len(p) > 1 else 0.0,
                    pid=to_int(p[2]) if len(p) > 2 else 0))
                idx += 1
            if len(rule.points) < rule.nip:
                state.warn(
                    f"*INTEGRATION_SHELL {rule.irid}: ESOP=0 with NIP="
                    f"{rule.nip} needs {rule.nip} S/WF/PID card(s) but only "
                    f"{len(rule.points)} follow(s) card 1. The rule is used "
                    f"with its {len(rule.points)} defined point(s) — the shell "
                    "loses the remaining layer(s), so its through-thickness "
                    "stiffness and its layer materials are BOTH wrong until the "
                    "missing cards are supplied.")
        if rule.irid in state.integration_shells:
            state.warn(
                f"*INTEGRATION_SHELL {rule.irid} is defined more than once — "
                "the LAST definition wins, as in LS-DYNA. Delete the duplicate "
                "if the two rules differ.")
        state.integration_shells[rule.irid] = rule


def handle_integration_beam(block: Block, state: ConversionState) -> None:
    """*INTEGRATION_BEAM — user cross-section integration rules.

    Card 1        ``IRID NIP RA ICST K``               (I10 I10 F10 I10 I10)
    Card 2 (ICST>0, exactly ONE card)
                  ``D1 D2 D3 D4 SREF TREF D5 D6``      (8 x F10)
    Card 3 (NIP != 0, NIP cards, one point each)
                  ``S T WF PID``                       (F10 F10 F10 I10)

    The two blocks are ADDITIVE, not exclusive. The manual prints them under two
    independent headings ("Additional card for ICST > 0" / "Include NIP
    additional cards below for NIP != 0", Vol I R17 p.29-2/3) and the reader
    honours both: a rule with ``ICST=5, NIP=2`` consumes 1 + 2 lines, and one
    that supplies only 1 of them swallows the NEXT rule's header as the missing
    point card. Only the HyperMesh CFG gates the list on ``ICST == 0``. When
    ICST > 0 the point data is IGNORED (LS-PrePost re-exports the dimension card
    alone) but the lines are still consumed, so they are read and reported
    rather than skipped.

    Like *INTEGRATION_SHELL the keyword has no documented "Card Sets" summary,
    but a deck may stack several rules under one header (verified: two rules
    under one ``*INTEGRATION_BEAM`` round-trip as two), so the reader loops. It
    has NO ``_TITLE`` variant — the p.41-1 "_TITLE may be appended to all the
    *SECTION keywords" sentence covers *SECTION_* only.

    Field ranges are NOT enforced here: the CFG's ``CHECK`` block (``K >= 0``,
    ``-1 <= SREF <= 1``, ``-1 <= TREF <= 1``) is a GUI constraint the importer
    does not apply, and the consequence of an out-of-range value lives in the
    writer, which reports it there.
    """
    raw = block.raw
    idx = 0
    while idx < len(raw):
        if not raw[idx].strip():
            idx += 1
            continue
        f1 = _card(raw, idx, fixed=True, n=5, w=10)
        irid = to_int(f1[0]) if f1 else 0
        if irid <= 0:
            state.warn(
                "*INTEGRATION_BEAM: a card set with no positive IRID "
                f"('{raw[idx][:40].strip()}') cannot be referenced by any "
                "*SECTION_BEAM QR/IRID field — the rule and every card after "
                "it in this block are SKIPPED.")
            return
        rule = IntegrationBeam(
            irid,
            nip=to_int(f1[1]) if len(f1) > 1 else 0,
            ra=to_float(f1[2]) if len(f1) > 2 else 0.0,
            icst=to_int(f1[3]) if len(f1) > 3 else 0,
            k=to_int(f1[4]) if len(f1) > 4 else 0)
        idx += 1
        if rule.icst > 0:
            # D1 D2 D3 D4 SREF TREF D5 D6 — SREF/TREF sit BETWEEN D4 and D5, so
            # D5/D6 are fields 7/8 and NOT fields 5/6.
            d = _card(raw, idx, fixed=True, n=8, w=10)
            if not d:
                state.warn(
                    f"*INTEGRATION_BEAM {rule.irid}: ICST={rule.icst} needs a "
                    "D1..D6/SREF/TREF dimension card but the block ends first, "
                    "so the walk STOPPED here and any later rule in this block "
                    "is UNREAD.")
                return
            rule.dims = [to_float(d[i]) if len(d) > i else 0.0
                         for i in (0, 1, 2, 3, 6, 7)]
            rule.sref = to_float(d[4]) if len(d) > 4 else 0.0
            rule.tref = to_float(d[5]) if len(d) > 5 else 0.0
            idx += 1
        if rule.nip < 0:
            state.warn(
                f"*INTEGRATION_BEAM {rule.irid}: NIP={rule.nip} is negative. "
                "NIP is an integration-point COUNT — it is *SECTION_BEAM's "
                "QR/IRID field (card 1 field 4, cols 31-40) that takes a "
                "negative value to reference a rule. No S/T/WF/PID card is "
                "read for this rule, so if point cards do follow they are "
                "mis-read as the next rule's card 1.")
        for _ in range(max(rule.nip, 0)):
            # Blank placeholders hold a card position but carry no point.
            while idx < len(raw) and not raw[idx].strip():
                idx += 1
            if idx >= len(raw):
                break
            p = _card(raw, idx, fixed=True, n=4, w=10)
            rule.points.append(IntegrationBeamPoint(
                s=to_float(p[0]) if p else 0.0,
                t=to_float(p[1]) if len(p) > 1 else 0.0,
                wf=to_float(p[2]) if len(p) > 2 else 0.0,
                pid=to_int(p[3]) if len(p) > 3 else 0))
            idx += 1
        if 0 < len(rule.points) < rule.nip:
            state.warn(
                f"*INTEGRATION_BEAM {rule.irid}: NIP={rule.nip} needs "
                f"{rule.nip} S/T/WF/PID card(s) but only {len(rule.points)} "
                f"follow(s). The rule is used with its {len(rule.points)} "
                "defined point(s), so the section loses the remaining cell(s) "
                "and both its area and its bending inertia come out too small "
                "until the missing cards are supplied.")
        if rule.icst > 0 and rule.points:
            state.warn(
                f"*INTEGRATION_BEAM {rule.irid}: ICST={rule.icst} selects a "
                f"STANDARD cross-section, so the {len(rule.points)} S/T/WF/PID "
                "card(s) that follow are read to keep the card count right but "
                "their data is IGNORED — the manual asks for NIP and RA to be "
                "zero whenever ICST is non-zero, and LS-DYNA drops the points "
                "the same way. Delete them, or set ICST=0 to use them.")
        if rule.irid in state.integration_beams:
            state.warn(
                f"*INTEGRATION_BEAM {rule.irid} is defined more than once — "
                "the LAST definition wins, as in LS-DYNA. Delete the duplicate "
                "if the two rules differ.")
        state.integration_beams[rule.irid] = rule


def _read_icomp_angles(raw: List[str], idx: int, nip: int, secid: int,
                       state: ConversionState,
                       keyword: str = "*SECTION_SHELL") -> List[float]:
    """*SECTION_SHELL card 3 / *SECTION_TSHELL card 2 (ICOMP=1): the B_i
    material angles, eight per card over ``ceil(NIP/8)`` cards (Manual Vol I R17
    p.41-70). Returns exactly NIP values, bottom layer first.

    A blank NIP defaults to LS-DYNA's 2.0, so an ICOMP section that omits it
    still reads its one angle card rather than none. (The thick-shell CFG agrees
    on the card COUNT by a different route — ``if(LSD_NIP == 0 && LSD_ICOMP ==
    1) BLANK;``, SectTShl.cfg:143 — one card either way.)

    Cards are taken BY RAW INDEX, so an all-zero angle card, which is written
    blank, is consumed as the CARD it is instead of being skipped as whitespace
    (the #117 rule). ``_card`` returns eight empty strings for a blank line in
    range and ``[]`` only past the end of the block, which is what separates
    "this layer's angle is 0" from "the angle block is truncated".

    *keyword* names the caller in the truncation warning; the two card layouts
    are identical, only their card NUMBER differs (*SECTION_TSHELL has no
    thickness card 2, because a thick shell's thickness is its mesh).
    """
    n = nip if nip > 0 else 2
    n_cards = (n + 7) // 8
    vals: List[float] = []
    read = 0
    for k in range(n_cards):
        row = _card(raw, idx + k, fixed=True, n=8, w=10)
        if not row:
            break
        vals += [to_float(x) for x in row]
        read += 1
    if read < n_cards:
        state.warn(
            f"{keyword} {secid}: ICOMP=1 with NIP={nip} needs {n_cards} "
            f"angle card(s) (8 values each) but only {read} follow(s) card 2 — "
            "the missing layer angles default to 0 degrees. Check the deck: a "
            "truncated angle block silently turns a balanced layup into a "
            "unidirectional one.")
    return (vals + [0.0] * n)[:n]


# *SECTION_SOLID keyword options that add card sets of their own (Manual Vol I
# R17 p.41-88). Like the shell option cards none of them reaches this handler
# today (the dispatcher is exact-key and only "SECTION_SOLID" is registered), but
# the walk accounts for them so registering one later cannot silently make every
# following set mis-stride.
_SECTION_SOLID_OPTION_CARDS = {"EFG": 2, "SPG": 2, "MISC": 1}

# ELFORM values that add the user-defined-solid cards 3 / 4 / 5 (p.41-90):
# "EQ.101..105: user defined solid".
_USER_SOLID_ELFORMS = frozenset({101, 102, 103, 104, 105})


def _section_set_stop(keyword: str, n_sets: int, line: str) -> str:
    """The message every card-set walk uses when it cannot stride past a set."""
    return (
        f"{keyword}: "
        + (f"after {n_sets} complete card set(s) the next card"
           if n_sets else "the first card of the block")
        + f" ('{line[:40].strip()}') carries no positive SECID, so the walk "
        "STOPPED there and the remaining lines of the block are UNREAD — any "
        "*PART pointing at a section defined below it falls back to an "
        "auto-generated placeholder. Split the sets k2rad cannot stride over "
        f"into their own {keyword} blocks.")


def _dup_secid(keyword: str, secid: int, seen, state: ConversionState) -> None:
    """Report a SECID defined twice under the same *SECTION_* keyword.

    Scoped to *seen* (that keyword's own dict) rather than to the whole
    *SECTION id space on purpose: cross-keyword reuse is a different defect
    with a different consequence (two /PROP cards of the same id) and would
    fire on decks this walk is not otherwise changing.
    """
    if secid in seen:
        state.warn(
            f"{keyword} {secid} is defined more than once — the LAST "
            "definition wins, as in LS-DYNA, so the earlier section's fields "
            "are discarded and every *PART on that SECID silently takes this "
            "one's. Delete the duplicate if the two sections differ.")


def handle_section_solid(block: Block, state: ConversionState) -> None:
    """*SECTION_SOLID (+ _EFG/_SPG/_MISC/_TITLE) — every card SET under the
    header.

    "Card Sets.  For each unique solid section, include one set of data cards.
    ...  This input ends at the following keyword ("*") card." (Vol I R17
    p.41-88). Under _TITLE one 80a line is read per SECTION (p.41-1), so the
    title card repeats per set.

    A set spans ``1 (title) + 1 (card 1) + <option cards> + 1 + NIP +
    ceil(LMC/8) (cards 3/4/5, ELFORM 101-105)`` lines. Reading only the first
    set — which is what this handler used to do — dropped every later section
    silently, and a *PART pointing at one of them fell through to
    ``_auto_section_solid``'s placeholder.

    The _EFG/_SPG "optional" second option card is consumed UNCONDITIONALLY:
    it is not positionally detectable, and LS-PrePost eats it whether or not it
    is there (a multi-set _EFG block that omits it reads the next set's card 1
    as the optional card and produces a garbage section). Neither spelling is
    dispatched today, so this only matters if one is registered later. The
    _MISC card 2c IS positionally detectable (only field 1 defined) and is
    consumed per-set only when present — see the walk.
    """
    per_set_title = _title_offset(block)
    opt_cards = sum(n for o, n in _SECTION_SOLID_OPTION_CARDS.items()
                    if block.keyword.endswith("_" + o)
                    or ("_" + o + "_") in block.keyword)
    raw = block.raw
    idx = 0
    n_sets = 0
    while idx < len(raw):
        # Trailing blank padding is not a card set. Anything else — including a
        # blank line that IS this set's 80a title card — is walked, not skipped.
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        f1 = _card(raw, idx, fixed=True, n=8, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            state.warn(_section_set_stop("*SECTION_SOLID", n_sets, raw[idx]))
            break
        elform = to_int(f1[1]) if len(f1) > 1 else 1
        # ELFORM 11 (1-pt ALE multi-material) / 12 (1-pt ALE single material)
        # mark the property as ALE → /PROP/SOLID Iale=1.
        iale = 1 if elform in (11, 12) else 0
        if iale:
            state.warn(f"*SECTION_SOLID {secid}: ELFORM={elform} (ALE) -> "
                       "/PROP/SOLID Iale=1. If the mesh is fixed (Eulerian), "
                       "switch Iale to 2 (Euler) for a cheaper run.")
        # Cohesive sections (ELFORM ±19/20/±21/22 → /PROP/TYPE43): card-1
        # fields 7/8 are COHOFF and GASKETT (Vol I R16 p.41-88). COHOFF only
        # matters for the shell-offset forms 20/22 (it places the cohesive
        # layer between shells of unequal thickness) and TYPE43 has no slot
        # for it; GASKETT turns the section into a *MAT_COHESIVE_GASKET
        # element, which is not an adhesive path at all.
        cohoff  = to_float(f1[6]) if len(f1) > 6 else 0.0
        gaskett = to_float(f1[7]) if len(f1) > 7 else 0.0
        if cohoff != 0.0:
            state.warn(
                f"*SECTION_SOLID {secid}: COHOFF={cohoff:g} places the "
                "cohesive layer off-center between shells of different "
                "thickness (ELFORM 20/22) — /PROP/TYPE43 has no offset field, "
                "so the layer acts at the nodal mid-plane. DROPPED.")
        if gaskett != 0.0:
            state.warn(
                f"*SECTION_SOLID {secid}: GASKETT={gaskett:g} converts the "
                "cohesive ELFORM into a *MAT_COHESIVE_GASKET gasket element — "
                "no Radioss counterpart; the flag is DROPPED and the section "
                "is emitted as a plain cohesive /PROP/TYPE43.")
        # _MISC option card 2c: COHTHK (field 1) supersedes *MAT_240 THICK —
        # exactly what /PROP/TYPE43 True_thickness does, so it maps 1:1. The
        # card position is idx+1 (option cards follow card 1) — but unlike
        # _EFG/_SPG the card is BOTH optional ("It is optional", Vol I R16
        # p.41-83) and positionally detectable: it holds ONLY COHTHK, fields
        # 2..8 are undefined/blank. Consuming it unconditionally would eat
        # the next set's card 1 in a multi-set block that omits it
        # (True_thickness = that set's SECID and the set vanishes), so it is
        # consumed only when the next line looks like a MISC card: fields
        # 2..8 blank and field 1 blank or numeric (a short non-numeric lone
        # field is the next set's title in the _TITLE spellings).
        cohthk = 0.0
        set_opt_cards = opt_cards
        if (block.keyword.endswith("_MISC") or "_MISC_" in block.keyword):
            fm = _card(raw, idx + 1, fixed=True, n=8, w=10)
            misc_present = bool(fm) and not any(x.strip() for x in fm[1:])
            if misc_present and fm[0].strip():
                v = to_float(fm[0], float("nan"))
                if v != v:                       # NaN — not a number
                    misc_present = False
                else:
                    cohthk = v
            set_opt_cards = opt_cards - 1 + (1 if misc_present else 0)
        idx += 1 + set_opt_cards
        # Cards 3 / 4 / 5, ELFORM 101-105 only. Nothing on them is modelled, but
        # the CURSOR has to clear them: card 3 begins with NIP, a positive
        # integer, so the "no positive SECID" stop above never trips on it and
        # the next set would otherwise be read out of the middle of this one.
        if elform in _USER_SOLID_ELFORMS:
            f3 = _card(raw, idx, fixed=True, n=8, w=10)
            state.warn(
                f"*SECTION_SOLID {secid}: ELFORM={elform} is a USER-DEFINED "
                "solid (*USER_INTERFACE routine), which has no Radioss "
                "counterpart — the section is converted as an ordinary "
                "/PROP/SOLID and the user routine's own integration points, "
                "extra DOFs and LMC constants (cards 3/4/5) are DROPPED.")
            if not f3:
                state.warn(
                    f"*SECTION_SOLID {secid}: ELFORM={elform} needs card 3 "
                    "(NIP NXDOF IHGF ITAJ LMC NHSV XNOD) but the block ends "
                    "first, so the walk STOPPED here.")
                break
            nip = to_int(f3[0]) if f3 else 0
            lmc = to_int(f3[4]) if len(f3) > 4 else 0
            idx += 1 + max(nip, 0) + (max(lmc, 0) + 7) // 8
        _dup_secid("*SECTION_SOLID", secid, state.sec_solids, state)
        state.sec_solids[secid] = SectionSolid(secid, title, elform, iale,
                                               cohthk=cohthk)
        n_sets += 1


#: *SECTION_TSHELL ELFORM values the manual defines (Vol I R16 p.3717, and the
#: CFG enum SectTShl.cfg:84-92). Note 4 is NOT one of them — the thick-shell set
#: is 1/2/3/5/6/7. Anything outside it is warned about and mapped like the
#: non-default forms.
_TSHELL_ELFORMS = frozenset({1, 2, 3, 5, 6, 7})

#: The thick-shell ELFORMs that are EXTRUDED THIN SHELLS: they use thin-shell
#: (plane-stress) material models and have an uncoupled stiffness in the
#: thickness direction (Vol I R16 p.3717 Remark 1). Every Radioss thick shell is
#: a 3D-stress element, so this distinction cannot be carried across.
_TSHELL_PLANE_STRESS_ELFORMS = frozenset({1, 2, 6})

#: The thick-shell ELFORMs whose integration is REDUCED. dyna2rad maps only
#: ELFORM 1 to the under-integrated Isolid=15 and sends 5 and 6 to the
#: full-integration HA8 (Isolid=14) along with 2/3/7, so those two lose their
#: reduced integration; warned rather than silently remapped, because Isolid=15
#: would also change their assumed-strain treatment.
_TSHELL_REDUCED_ELFORMS = frozenset({1, 5, 6})


def handle_section_tshell(block: Block, state: ConversionState) -> None:
    """*SECTION_TSHELL (+ _TITLE/_ID) — every card SET under the header.

    Card 1  ``SECID ELFORM SHRF NIP PROPT QR ICOMP TSHEAR``   (8 x I10)
    Card 2  ``B1..B8``, ``ceil(NIP/8)`` cards, ICOMP=1 ONLY   (8 x F10)

    (``Keyword971/PROPERTY/SectTShl.cfg:141-146``.) The angle block is card
    **2**, not card 3 as on *SECTION_SHELL: this keyword has no thickness card
    at all, because a thick shell's thickness is the distance between its two
    faces in *NODE. Getting that wrong by one card would read the first angle
    card as the next set's card 1.

    A set therefore spans ``1 (title) + 1 (card 1) + ceil(NIP/8) (ICOMP=1)``
    lines, every term read from that set's OWN fields — the same
    walk-by-what-was-consumed discipline as *SECTION_SHELL / *SECTION_SOLID, and
    for the same reason: reading only the first set drops every later section
    silently and its *PARTs fall through to an auto-generated placeholder.
    """
    per_set_title = _title_offset(block)
    raw = block.raw
    idx = 0
    n_sets = 0
    while idx < len(raw):
        # Trailing blank padding is not a card set. Anything else — including a
        # blank line that IS this set's 80a title card — is walked, not skipped.
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        f1 = _card(raw, idx, fixed=True, n=8, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            state.warn(_section_set_stop("*SECTION_TSHELL", n_sets, raw[idx]))
            break
        # A BLANK ELFORM is LS-DYNA's default 1 (one-point reduced integration),
        # NOT 0. dyna2rad reads the blank as 0, which falls into the `else` of
        # its `elform == 1 ? 15 : 14` test and hands the deck the FULL
        # integration HA8 — the opposite element class from the one the deck
        # asked for by leaving the field empty. Deliberate divergence.
        elform_blank = not (len(f1) > 1 and f1[1].strip())
        elform = 1 if elform_blank else to_int(f1[1])
        shrf = to_float(f1[2]) if len(f1) > 2 else 0.0
        # NIP: "EQ.0: set to 2 integration points" (Vol I R16 p.3717). dyna2rad
        # keeps the raw 0 (measured: a blank-NIP section echoed NIP = 0), which
        # on the composite branch writes ZERO ply cards against a property that
        # expects one — starter ERROR 675. Deliberate divergence.
        nip = to_int(f1[3]) if len(f1) > 3 and f1[3].strip() else 0
        if nip < 0:
            state.warn(
                f"*SECTION_TSHELL {secid}: NIP={nip} is negative. NIP is an "
                "integration-point COUNT — it is the QR field (card 1 field 6, "
                f"cols 51-60) that takes a negative value to reference an "
                f"*INTEGRATION_SHELL rule. |NIP| = {abs(nip)} is used.")
            nip = abs(nip)
        if nip == 0:
            nip = 2
        propt = to_float(f1[4]) if len(f1) > 4 else 0.0
        qr = to_float(f1[5]) if len(f1) > 5 else 0.0
        icomp = to_int(f1[6]) if len(f1) > 6 else 0
        tshear = to_int(f1[7]) if len(f1) > 7 else 0
        sec = SectionTshell(secid, title, elform, shrf, nip, propt, qr,
                            icomp, tshear, elform_blank=elform_blank)
        if qr < 0.0:
            sec.irid = int(abs(qr))
        idx += 1
        if icomp == 1:
            sec.betas = _read_icomp_angles(raw, idx, nip, secid, state,
                                           "*SECTION_TSHELL")
            idx += (nip + 7) // 8
        _dup_secid("*SECTION_TSHELL", secid, state.sec_tshells, state)
        state.sec_tshells[secid] = sec
        n_sets += 1


#: *SECTION_SPH_{OPTION}. ELLIPSE (called TENSOR before R8) is the only one
#: that adds a CARD — six anisotropic h cells HXCSLH..HZINI — so it is the only
#: one the card walk has to stride over. INTERACTION and USER change the
#: SEMANTICS of card 1 without adding one. dyna2rad's CFG makes all four
#: USER_NAMES of one entity and reads card 2 for ``sphOption == 2`` only, so
#: the anisotropic cells are silently lost there; here they are named.
_SPH_SECTION_OPTIONS = ("ELLIPSE", "TENSOR", "INTERACTION", "USER")


def handle_section_sph(block: Block, state: ConversionState) -> None:
    """*SECTION_SPH (+ _TITLE/_ID/_ELLIPSE/_TENSOR/_INTERACTION/_USER) → the
    per-set *SECTION_SPH records the /PROP/SPH writer consumes.

    Card 1  ``SECID CSLH HMIN HMAX SPHINI DEATH START SPHKERN``  (8 x I10)
    Card 2  ``HXCSLH HYCSLH HZCSLH HXINI HYINI HZINI``  (_ELLIPSE/_TENSOR only)

    Two things this walk does that dyna2rad does not:

    * **it applies the manual's own defaults**, ``CSLH = 1.2``, ``HMIN = 0.2``,
      ``HMAX = 2.0``, ``DEATH = 1e20``. The CFG declares them but the SDI read
      path does not apply them, so on the far side a blank CSLH is 0 and the
      section takes the CONSTANT-h branch — the wrong one for the commonest
      deck there is (see SectionSph).
    * **the _ELLIPSE card 2 is claimed by RAW CONTIGUITY** (the #119 rule).
      The card is mandatory under that option and an all-blank one is still a
      card, so it is strided by position; taking "the next non-blank row"
      instead would consume the FOLLOWING set's card 1 as anisotropic h values
      and lose that whole section.
    """
    per_set_title = _title_offset(block)
    raw = block.raw
    option = next((o for o in _SPH_SECTION_OPTIONS
                   if f"_{o}" in f"_{block.keyword}"), "")
    has_card2 = option in ("ELLIPSE", "TENSOR")
    idx = 0
    n_sets = 0
    n_aniso = 0
    while idx < len(raw):
        # Trailing blank padding is not a card set. Anything else — including a
        # blank line that IS this set's 80a title card — is walked, not skipped.
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        f1 = _card(raw, idx, fixed=True, n=8, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            state.warn(_section_set_stop("*SECTION_SPH", n_sets, raw[idx]))
            break
        cslh_blank = not (len(f1) > 1 and f1[1].strip())
        sec = SectionSph(
            secid, title,
            cslh=1.2 if cslh_blank else to_float(f1[1]),
            hmin=_ffield(f1, 2, 0.2),
            hmax=_ffield(f1, 3, 2.0),
            sphini=to_float(f1[4]) if len(f1) > 4 else 0.0,
            death=_ffield(f1, 5, 1.0e20),
            start=to_float(f1[6]) if len(f1) > 6 else 0.0,
            sphkern=to_int(f1[7]) if len(f1) > 7 else 0,
            cslh_blank=cslh_blank,
            option=option)
        idx += 1
        if has_card2:
            # A NON-ZERO cell, not merely a non-blank one. A card 2 written out
            # as explicit zeros is isotropic BY DEFINITION, and reporting it as
            # "you lost your anisotropy" costs the reader a chase through a
            # deck that never asked for any. (The card is still consumed
            # positionally either way — the #119 rule.)
            if idx < len(raw) and any(
                    c.strip() and to_float(c) != 0.0
                    for c in _card(raw, idx, fixed=True, n=6, w=10)):
                n_aniso += 1
            idx += 1
        _dup_secid("*SECTION_SPH", secid, state.sec_sph, state)
        state.sec_sph[secid] = sec
        n_sets += 1
    if n_aniso:
        state.warn(
            f"*{block.keyword}: {n_aniso} section(s) state an ANISOTROPIC "
            "smoothing length (HXCSLH/HYCSLH/HZCSLH and/or HXINI/HYINI/HZINI on "
            "card 2) — DROPPED. Radioss's /PROP/SPH carries ONE scalar h and "
            "one scalar dilatation rule; there is no per-direction smoothing "
            "length anywhere in the SPH property, so a deliberately flattened "
            "or stretched kernel becomes an isotropic one and the particle's "
            "neighbour set changes shape. Re-state the model with an isotropic "
            "kernel, or accept the difference. (dyna2rad reads card 2 for this "
            "option too and then writes none of its six cells, so it degrades "
            "to isotropic with no message at all.)")
    if option in ("INTERACTION", "USER"):
        state.warn(
            f"*{block.keyword}: the _{option} option is not carried. "
            + ("_INTERACTION restricts the particle approximation to the parts "
               "that name it (*CONTROL_SPH CONT=1); Radioss has no per-section "
               "interaction switch, so every SPH part in the converted deck "
               "interacts with every other one."
               if option == "INTERACTION" else
               "_USER hands the smoothing-length computation to a user "
               "subroutine, which has no OpenRadioss counterpart at all.")
            + " The section's ordinary CSLH/HMIN/HMAX/SPHINI cells ARE read and "
            "converted, so the part keeps a usable /PROP/SPH.")


# *SECTION_BEAM card 2 (Manual Vol I R17 pp.41-4..41-14). WHICH card 2 a set
# takes is decided by ELFORM and, for ELFORM 2/3/12, by a look-ahead on that
# card's own first 10 columns — "the first 7 characters of the card spell out
# 'SECTION'" selects the NAMED standard-section dialect over the numeric one
# (the CFG does it literally: CARD_PREREAD("%10s", SectType) then
# ASSIGN(ifSect, _FIND(SectType, "SECTION"), IMPORT), sect_beam.cfg:611-612).
_BEAM_CARD2 = {
    "2a": "TS1 TS2 TT1 TT2 NSLOC NTLOC ITORM",
    "2b": "STYPE D1..D6 ITORM",
    "2c": "A ISS ITT J SAS IST ITORM SAT",
    "2d": "A RAMPT STRESS",
    "2e": "TS1 TS2 TT1 TT2",
    "2f": "VOL INER CID CA OFFSET RRCON SRCON TRCON",
    "2h": "TS1 TS2",
    "2i": "TS1 TS2 TT1 TT2 PRINT - ITOFF",
    "2j": "PR IOVPR IPRSTR",
}


def _beam_card2_kind(elform: int, first_field: str) -> str:
    """Which *SECTION_BEAM card-2 dialect this set takes, "" if ELFORM has none.

    ELFORM 0 is the CFG's accepted alias of 1 (``if(LSD_ELFORM == 0 || 1 ||
    11)``, sect_beam.cfg:625). ELFORM 10 is not defined by the manual, so it
    returns "" and the caller stops the walk rather than guessing a stride.
    """
    named = first_field.strip().upper().startswith("SECTION")
    if elform in (0, 1, 11):
        return "2a"
    if elform in (2, 3, 12) and named:
        return "2b"
    if elform in (2, 12, 13):
        return "2c"
    if elform == 3:
        return "2d"
    if elform in (4, 5):
        return "2e"
    if elform == 6:
        return "2f"
    if elform in (7, 8):
        return "2h"
    if elform == 9:
        return "2i"
    if elform == 14:
        return "2j"
    return ""


def handle_section_beam(block: Block, state: ConversionState) -> None:
    """*SECTION_BEAM (+ _TITLE) — every card SET under the header.

    "Card Sets.  For each BEAM section in the model, add one set of Cards 1 and
    2 (maybe additionally Card 3 for ELFORM = 12) cards.  This input ends at the
    next keyword ("*") card." (Vol I R17 p.41-3). Under _TITLE one 80a line is
    read per SECTION, so the title card repeats per set.

    A set spans ``1 (title) + 1 (card 1) + 1 (card 2a..2j) + 1 (OPTCARD, only
    ELFORM 2 on the named-section card 2b when the next line starts with
    OPTCARD) + 1 (card 2c.1, only ELFORM 12 whose card 2 was the NUMERIC 2c)``
    lines. The two riders are what makes a fixed stride impossible: an ELFORM 12
    set with a ``SECTION_09`` card 2 takes NO card 2c.1 — "Include this card if
    ELFORM equals 12 and the preceding card is Card 2c" is exact, and the reader
    honours it.

    Card 1 is ``SECID ELFORM SHRF QR/IRID CST SCOOR NSM NAUPD``; field 4 is the
    QR/IRID cell whose negative value binds an *INTEGRATION_BEAM rule.
    """
    per_set_title = _title_offset(block)
    raw = block.raw
    idx = 0
    n_sets = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        f1 = _card(raw, idx, fixed=True, n=8, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            state.warn(_section_set_stop("*SECTION_BEAM", n_sets, raw[idx]))
            break
        elform = to_int(f1[1]) if len(f1) > 1 else 2
        sec = SectionBeam(secid, title, elform)
        # QR/IRID (field 4, cols 31-40): the field is a FLOAT and a NEGATIVE
        # value makes |QR| the id of a user *INTEGRATION_BEAM rule (p.41-4).
        # Both "-77" and "-77.0" occur in real decks. On that branch the
        # quadrature scalar is DEAD — leaving sec.qr at its 0.0 default rather
        # than storing the negative value is what stops a later reader from
        # seeing "QR = 0" and silently picking the 2-point rectangular rule.
        qr_irid = to_float(f1[3]) if len(f1) > 3 else 0.0
        if qr_irid < 0.0:
            sec.irid = int(abs(qr_irid))
        else:
            sec.qr = qr_irid
        sec.cst = to_int(f1[4]) if len(f1) > 4 else 0
        # SCOOR (cols 51-60) is a FLOAT and only meaningful for ELFORM=6; it is
        # the discrete beam's triad-rotation rule and |SCOOR|=2 is what selects
        # the node-oriented (n1->n2 r-axis) spring property.
        sec.scoor = to_float(f1[5]) if len(f1) > 5 else 0.0
        f2 = _card(raw, idx + 1, fixed=True, n=8, w=10)
        kind = _beam_card2_kind(elform, f2[0] if f2 else "")
        if kind in ("2a", "2e", "2h", "2i"):
            # TS1 TS2 [TT1 TT2] — thicknesses, NOT section constants.
            sec.ts1 = to_float(f2[0]) if f2 else 0.0
            sec.ts2 = to_float(f2[1]) if len(f2) > 1 else 0.0
            if kind != "2h":
                sec.tt1 = to_float(f2[2]) if len(f2) > 2 else 0.0
                sec.tt2 = to_float(f2[3]) if len(f2) > 3 else 0.0
            if kind == "2a":
                sec.nsloc = to_float(f2[4]) if len(f2) > 4 else 0.0
                sec.ntloc = to_float(f2[5]) if len(f2) > 5 else 0.0
            if kind == "2i":
                # ELFORM 9 spot weld, card 2i (Manual Vol I R17 p.41-22):
                # TS1 TS2 TT1 TT2 PRINT - ITOFF -. TS/TT (parsed above via the
                # shared thickness branch) are the outer/inner nugget diameters
                # at each node; the /PROP/TYPE13 connector path derives the
                # cross-section from them (pi*(do^2-di^2)/4 at the mean of the
                # end diameters). There is no VOL and no CA on this card — that
                # is card 2f, the ELFORM=6 discrete beam. PRINT (field 5) only
                # steers swforc output.
                sec.itoff = to_int(f2[6]) if len(f2) > 6 else 0
        elif kind == "2c":
            # ELFORM 2/12/13 resultant: A ISS ITT J
            sec.area = to_float(f2[0]) if f2 else 0.0
            sec.iyy = to_float(f2[1]) if len(f2) > 1 else 0.0
            sec.izz = to_float(f2[2]) if len(f2) > 2 else 0.0
            sec.ixx = to_float(f2[3]) if len(f2) > 3 else 0.0
        elif kind == "2d":
            # ELFORM 3 truss: A RAMPT STRESS. Only the AREA has a /PROP meaning
            # — reading fields 2/3 as Iyy/Izz (which this handler used to do,
            # via the catch-all resultant branch) put a ramp TIME and an initial
            # STRESS into two bending inertias. RAMPT/STRESS are kept on the
            # record and SCREENED by the truss writer (writer/truss.py), which
            # is the only place that knows whether the deck has a
            # dynamic-relaxation phase for them to act in. No warning here: the
            # section now converts to /PROP/TYPE2 (TRUSS) and its elements to
            # /TRUSS, so the old "no k2rad path yet" text was the statement of
            # a gap this batch closes.
            sec.area = to_float(f2[0]) if f2 else 0.0
            sec.rampt = to_float(f2[1]) if len(f2) > 1 else 0.0
            sec.prestress = to_float(f2[2]) if len(f2) > 2 else 0.0
        elif kind == "2b":
            # Card 2b reaches ELFORM 2, 3 AND 12 (p.41-9), so an ELFORM=3
            # section can state its geometry here instead of as card 2d's
            # `A RAMPT STRESS` — and then Area stays 0. writer/truss.py's
            # _truss_section_is_emittable REFUSES such a section rather than
            # writing a /PROP/TYPE2 with AREA 0 (ERROR 497), which is why this
            # message names both destinations.
            state.warn(
                f"*SECTION_BEAM {secid}: card 2 is the NAMED standard section "
                f"'{(f2[0] if f2 else '').strip()}', whose D1..D6 dimensions "
                "k2rad has no path for — the section's Area/Iyy/Izz/Ixx stay "
                "ZERO and the beam carries no stiffness"
                + (" (on ELFORM=3 that is a TRUSS with no cross-section area, "
                   "so its /PROP/TYPE2 is refused outright rather than emitted "
                   "as starter ERROR 497)" if elform == 3 else "")
                + ". State the section "
                "numerically (ELFORM=2 with A/ISS/ITT/J, ELFORM=3 with A) or, "
                "for an integrated beam, as an *INTEGRATION_BEAM rule "
                "referenced from a negative QR/IRID.")
        elif kind == "2f":
            # ELFORM=6 DISCRETE beam, card 2f: VOL INER CID CA OFFSET RRCON
            # SRCON TRCON (Manual Vol I R17 p.41-20). There is no cross-section
            # here at all — VOL is a lumped VOLUME (mass = RO·VOL) and INER a
            # lumped rotary inertia, so the set never becomes a /PROP/BEAM: the
            # discrete-beam connector path turns it into a 6-DOF spring
            # property instead (/PROP/TYPE8 or /PROP/TYPE13).
            sec.vol = to_float(f2[0]) if f2 else 0.0
            sec.iner = to_float(f2[1]) if len(f2) > 1 else 0.0
            sec.cid = to_int(f2[2]) if len(f2) > 2 else 0
            sec.ca = to_float(f2[3]) if len(f2) > 3 else 0.0
            sec.cable_offset = to_float(f2[4]) if len(f2) > 4 else 0.0
            sec.rrcon = to_float(f2[5]) if len(f2) > 5 else 0.0
            sec.srcon = to_float(f2[6]) if len(f2) > 6 else 0.0
            sec.trcon = to_float(f2[7]) if len(f2) > 7 else 0.0
        elif kind == "2j":
            # ELFORM 14 is the ELBOW integrated tubular beam: "A user-defined
            # integration rule with a tubular cross section (9) must be used"
            # (Vol I R17 p.41-11). It is not a shear panel and it is not
            # un-integrated — it is the one formulation that MANDATES a rule.
            state.warn(
                f"*SECTION_BEAM {secid}: ELFORM=14 is the ELBOW integrated "
                "tubular beam, which Radioss has no counterpart for. Its card "
                f"2 is '{_BEAM_CARD2[kind]}' and states no cross-section at "
                "all — the section comes from the *INTEGRATION_BEAM rule that "
                "this formulation REQUIRES (a tubular one, ICST=9, referenced "
                "from a negative QR/IRID) — so /PROP/BEAM is written with "
                "Area=Iyy=Izz=Ixx=0 and the starter refuses it (ERROR "
                "314-317). Model the bend as ordinary integrated beams "
                "(ELFORM 1) if the pipe-ovalization response is not what the "
                "deck is about.")
        elif not kind:
            state.warn(
                f"*SECTION_BEAM {secid}: ELFORM={elform} is not a defined beam "
                "formulation (the manual lists 1-9 and 11-14), so k2rad cannot "
                "tell how many cards this set spans. The section is registered "
                "with no card-2 data and the walk STOPPED here — the remaining "
                "lines of the block are UNREAD.")
        idx += 2
        # Card 2b.1: only ELFORM 2, only after a NAMED card 2b, and only when
        # the line really is one (its field 1 is the literal string OPTCARD).
        if kind == "2b" and elform == 2:
            nxt = _card(raw, idx, fixed=True, n=2, w=10)
            if nxt and nxt[0].strip().upper().startswith("OPTCARD"):
                idx += 1
        # Card 2c.1: only ELFORM 12, and only when card 2 was the NUMERIC 2c.
        elif kind == "2c" and elform == 12:
            idx += 1
        _dup_secid("*SECTION_BEAM", secid, state.sec_beams, state)
        state.sec_beams[secid] = sec
        n_sets += 1
        if not kind:
            break


def handle_section_discrete(block: Block, state: ConversionState) -> None:
    """*SECTION_DISCRETE (+ _TITLE) → /PROP/TYPE4 (SPRING) flags — every card
    SET under the header.

    "Card Sets.  For each DISCRETE section include a pair of Cards 1 and 2.
    This input ends at the next keyword ("*") card." (Vol I R17 p.41-32). The
    pair is unconditional — the manual's own example shows a section with a
    blank card 2 — so the stride is a fixed ``1 (title) + 2``.

    Card 1: ``SECID DRO KD V0 CL FD``
    Card 2: ``CDL TDL`` (compression/tension deflection limits → deletion).

    Card 2 is read as CDL then TDL per the manual, its example and the
    LS-PrePost echo; ``Keyword971_R6.1/PROPERTY/sect_disc.cfg:127`` binds them
    the other way round and is wrong.
    """
    per_set_title = _title_offset(block)
    raw = block.raw
    idx = 0
    n_sets = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        f1 = _card(raw, idx, fixed=True, n=6, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            if not n_sets:
                state.warn("*SECTION_DISCRETE: empty card - skipped")
            else:
                state.warn(_section_set_stop("*SECTION_DISCRETE", n_sets,
                                             raw[idx]))
            break
        dro = to_int(f1[1]) if len(f1) > 1 else 0
        kd  = to_float(f1[2]) if len(f1) > 2 else 0.0
        v0  = to_float(f1[3]) if len(f1) > 3 else 0.0
        cl  = to_float(f1[4]) if len(f1) > 4 else 0.0
        fd  = to_float(f1[5]) if len(f1) > 5 else 0.0
        # A missing card 2 at the very END of the block is tolerated (LS-PrePost
        # defaults CDL/TDL to 0 there); anywhere else _card returns the next
        # set's card 1, which the stride below then skips as this set's card 2.
        # That silently swallows a whole section, so say it happened: a line in
        # the card-2 slot whose first field is a positive integer AND which is
        # followed by more of the block is a card 1 wearing a card 2's clothes.
        f2 = _card(raw, idx + 1, fixed=True, n=2, w=10)
        if (f2 and to_int(f2[0]) > 0
                and any(line.strip() for line in raw[idx + 2:])):
            state.warn(
                f"*SECTION_DISCRETE {secid}: the line read as its card 2 "
                f"(CDL TDL) is '{raw[idx + 1].strip()}', whose first field is "
                "the positive integer "
                f"{to_int(f2[0])} — that looks like the NEXT set's card 1, so "
                "this set is probably missing its card 2. The pair is "
                "UNCONDITIONAL (Vol I R17 p.41-32: 'For each DISCRETE section "
                "include a pair of Cards 1 and 2'), so k2rad strides two lines "
                "regardless: the section that line belongs to is LOST and "
                "every set after it in this block is read one line out of "
                "phase, which usually ends the walk early. Add the blank card "
                "2 the manual's own example shows.")
        cdl = to_float(f2[0]) if f2 else 0.0
        tdl = to_float(f2[1]) if len(f2) > 1 else 0.0
        idx += 2
        _dup_secid("*SECTION_DISCRETE", secid, state.sec_discrete, state)
        state.sec_discrete[secid] = SectionDiscrete(secid, title, dro, kd, v0,
                                                    cl, fd, cdl, tdl)
        n_sets += 1


# ─────────────────────────────────────────────────────────────────────────────
# Materials
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_elastic(block: Block, state: ConversionState) -> None:
    """*MAT_ELASTIC (001) → /MAT/ELAST, plus its _FLUID option variant →
    /MAT/LAW6 (HYD_VISC) + /EOS/POLYNOMIAL.

    The option is a SUBSTRING test on the keyword, exactly as dyna2rad does it
    (CM:216-222 ``sourceCard.find("FLUID")``) and as the LS-DYNA reader defines
    it (mat_001.cfg ``ASSIGN(MAT_OPTION,_FIND(TYPE,"_FLUID"),IMPORT)``);
    ``_split_keyword`` has already stripped _TITLE/_ID, so
    ``*MAT_ELASTIC_FLUID_TITLE`` arrives here as ``MAT_ELASTIC_FLUID``. Same
    shape as MAT_224's _LOG_INTERPOLATION branch — one handler, one flag, base
    path untouched.

    K (bulk modulus) is card-1 field 7 on BOTH spellings — blank and unused for
    plain *MAT_ELASTIC. Only the FLUID option adds card 2 (VC, CP); DA/DB are
    beam-only damping and are dropped by both converters.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Card1: mid rho E PR DA DB K
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    # The file's standard guard, placed BEFORE the option split so it covers
    # every spelling: a block with no data card, or one whose MID cell is
    # blank, would otherwise raise IndexError / emit a /MAT of id 0.
    if not f1 or not f1[0].strip():
        state.warn(f"*{block.keyword}: empty material card — skipped")
        return
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    E   = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu  = to_float(f1[3]) if len(f1) > 3 else 0.0
    if "FLUID" not in block.keyword:
        state.mat_elastic[mid] = MatElastic(mid, title, rho, E, nu)
        return
    # Card2 (FLUID only): VC CP. LS-DYNA's documented CP default is 1e20
    # (mat_001.cfg:52 DEFAULTS), i.e. "no cavitation limit" — a blank cell must
    # NOT read as an explicit 0.0 cavitation pressure, so cp_given records
    # whether the cell was actually written.
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    state.mat_elastic_fluid[mid] = MatElasticFluid(
        mid, title, rho,
        e=E, pr=nu,
        da=to_float(f1[4]) if len(f1) > 4 else 0.0,
        db=to_float(f1[5]) if len(f1) > 5 else 0.0,
        k=to_float(f1[6]) if len(f1) > 6 else 0.0,
        vc=to_float(f2[0]) if f2 else 0.0,
        cp=_ffield(f2, 1, 1.0e20),
        cp_given=bool(len(f2) > 1 and f2[1].strip()))


def handle_mat_jh_ceramics(block: Block, state: ConversionState) -> None:
    """*MAT_JOHNSON_HOLMQUIST_CERAMICS (110) → /MAT/LAW79.

    THREE cards (Vol II R16 p.2-761; mat_110.cfg:170-182), 8 x 10 chars:
      Card1: MID RO G A B C M N
      Card2: EPS0 T SFMAX HEL PHEL BETA
      Card3: D1 D2 K1 K2 K3 FS
    mat_110.cfg declares NO defaults block, so every blank cell is a real 0.0
    on both sides — parsed with plain to_float, no _ffield substitution. The
    one field that cannot survive a 0 (EPS0 with C != 0, starter ERROR 910) is
    repaired in the writer prepass, where the substitution can be warned about.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset,     fixed=True, n=8, w=10)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)

    if not f1 or not f1[0].strip():
        state.warn("*MAT_JOHNSON_HOLMQUIST_CERAMICS: empty material card — "
                   "skipped")
        return

    def _v(f, i):
        return to_float(f[i]) if len(f) > i else 0.0

    mid = to_int(f1[0])
    state.mat_jh_ceramics[mid] = MatJHCeramics(
        mid, title, _v(f1, 1),
        g=_v(f1, 2), a=_v(f1, 3), b=_v(f1, 4), c=_v(f1, 5),
        m=_v(f1, 6), n=_v(f1, 7),
        eps0=_v(f2, 0), t=_v(f2, 1), sfmax=_v(f2, 2),
        hel=_v(f2, 3), phel=_v(f2, 4), beta=_v(f2, 5),
        d1=_v(f3, 0), d2=_v(f3, 1),
        k1=_v(f3, 2), k2=_v(f3, 3), k3=_v(f3, 4), fs=_v(f3, 5))


def handle_mat_jh_concrete(block: Block, state: ConversionState) -> None:
    """*MAT_JOHNSON_HOLMQUIST_CONCRETE (111) → /MAT/LAW126.

    THREE cards (Vol II R16 p.2-765; mat_111.cfg), 8 x 10 chars:
      Card1: MID RO G A B C N FC
      Card2: T EPS0 EFMIN SFMAX PC UC PL UL
      Card3: D1 D2 K1 K2 K3 FS
    Card 1 is NOT the *MAT_110 layout: field 7 is N and field 8 is FC, where
    110 has M then N. There is no M, no HEL, no PHEL and no BETA on this card,
    and card 2 holds eight fields instead of six. mat_111.cfg declares no
    defaults, so blanks are 0.0.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset,     fixed=True, n=8, w=10)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)

    if not f1 or not f1[0].strip():
        state.warn("*MAT_JOHNSON_HOLMQUIST_CONCRETE: empty material card — "
                   "skipped")
        return

    def _v(f, i):
        return to_float(f[i]) if len(f) > i else 0.0

    mid = to_int(f1[0])
    state.mat_jh_concrete[mid] = MatJHConcrete(
        mid, title, _v(f1, 1),
        g=_v(f1, 2), a=_v(f1, 3), b=_v(f1, 4), c=_v(f1, 5),
        n=_v(f1, 6), fc=_v(f1, 7),
        t=_v(f2, 0), eps0=_v(f2, 1), efmin=_v(f2, 2), sfmax=_v(f2, 3),
        pc=_v(f2, 4), uc=_v(f2, 5), pl=_v(f2, 6), ul=_v(f2, 7),
        d1=_v(f3, 0), d2=_v(f3, 1),
        k1=_v(f3, 2), k2=_v(f3, 3), k3=_v(f3, 4), fs=_v(f3, 5))


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
    mat.family = "123" if _is_mat123(block) else "024"
    state.mat_plas_tab[mid] = mat


# *MAT_PLASTICITY_WITH_DAMAGE keyword options (Vol II R17 p.2-601). ORTHO turns
# 081 into 082 (directional damage); RCDC / RCDC1980 add the Wilkins card 5;
# STOCHASTIC scatters the failure strain via *DEFINE_STOCHASTIC_VARIATION.
_MAT081_RCDC_OPTIONS = ("ORTHO_RCDC1980", "ORTHO_RCDC", "RCDC1980", "RCDC")


def handle_mat_plasticity_with_damage(block: Block, state: ConversionState) -> None:
    """*MAT_PLASTICITY_WITH_DAMAGE / *MAT_081 / *MAT_082 (+ _ORTHO, _RCDC,
    _RCDC1980, _STOCHASTIC) → the MAT_024 /MAT/LAW36 path + /FAIL/TAB1.

    Card layout (Vol II R17 pp.2-602/603):
      Card1: MID RO E PR SIGY ETAN EPPF TDEL
      Card2: C P LCSS LCSR EPPFR VP LCDM NUMINT
      Card3: EPS1-EPS8
      Card4: ES1-ES8
      Card5: ALPHA BETA GAMMA D0 B LAMBDA DS L   — _RCDC/_RCDC1980 ONLY

    The elasto-plastic half is card-for-card *MAT_024 apart from the two
    damage strains, so the record rides ``state.mat_plas_tab`` and reuses the
    whole LCSS/table/EPS-ES/bilinear resolution ladder. Only the card-1 field 7
    and card-2 field 6 differ in MEANING from MAT_024 (EPPF where MAT_024 has
    FAIL, VP one slot further right), which is exactly why this cannot share
    the MAT_024 handler.

    ``fail`` is deliberately left 0: MAT_081 has no FAIL field, and its
    plastic-strain failure is the EPPF/EPPFR pair on /FAIL/TAB1 instead of a
    /FAIL/JOHNSON, so a single criterion is never counted twice.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    kw = block.keyword
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    f3 = _card(raw, offset + 2, fixed=False)
    f4 = _card(raw, offset + 3, fixed=False)

    # *MAT_082 spells the ORTHO option in the number; the named keyword spells
    # it as a suffix. RCDC/RCDC1980 imply ORTHO too (they are 082 variants).
    ortho = ("ORTHO" in kw or "RCDC" in kw
             or kw.startswith("MAT_082") or kw.startswith("MAT_82"))
    mat = MatPlasTAB(
        mid, title, rho=g1(1), E=g1(2), nu=g1(3), sigy=g1(4), etan=g1(5),
        fail=0.0, lcss=to_int(f2[2]) if len(f2) > 2 else 0,
        C=g2(0), P=g2(1),
        eps_pts=[to_float(v) for v in f3], es_pts=[to_float(v) for v in f4])
    mat.eppf = g1(6)
    mat.tdel = g1(7)
    mat.lcsr = to_int(f2[3]) if len(f2) > 3 else 0
    mat.eppfr = g2(4)
    mat.vp = int(g2(5))
    mat.lcdm = to_int(f2[6]) if len(f2) > 6 else 0
    mat.numint = g2(7)
    mat.ortho_damage = ortho
    mat.family = "082" if ortho else "081"
    state.mat_plas_tab[mid] = mat

    if ortho:
        state.warn(
            f"*MAT_082 {mid}: the _ORTHO option makes the damage evolution "
            "DIRECTIONAL (damage tracked separately in the two in-plane "
            "principal directions, element deleted when either reaches the "
            "rupture strain). /MAT/LAW36 + /FAIL/TAB1 is ISOTROPIC, so the "
            "base plasticity and the EPPF/EPPFR damage strains convert but "
            "the directionality does NOT — expect somewhat later failure "
            "under non-proportional loading. (dyna2rad drops *MAT_082 "
            "entirely and silently, leaving the part with no material.)")
    if any(opt in kw for opt in _MAT081_RCDC_OPTIONS):
        state.warn(
            f"*MAT_082 {mid}: the _RCDC/_RCDC1980 option adds the Wilkins "
            "Rc-Dc damage card (ALPHA BETA GAMMA D0 B LAMBDA DS L), which has "
            "no OpenRadioss counterpart — that card is NOT read and the "
            "material converts with the plain EPPF/EPPFR damage of the base "
            "law. Use *MAT_ADD_DAMAGE_GISSMO (→ /FAIL/TAB2) if a "
            "triaxiality-driven damage law is the point.")
    if "STOCHASTIC" in kw:
        state.warn(
            f"*MAT_081 {mid}: the _STOCHASTIC option scatters the failure "
            "strain per element via *DEFINE_STOCHASTIC_VARIATION. Radioss has "
            "no per-element material scatter, so every element gets the same "
            "EPPF/EPPFR — the deterministic mean behaviour.")


def handle_mat_damage_2(block: Block, state: ConversionState) -> None:
    """*MAT_DAMAGE_2 / *MAT_105 → /MAT/LAW36 + /FAIL/LEMAITRE (+ /FAIL/JOHNSON).

    Card layout (Vol II R17 pp.2-752/753):
      Card1: MID RO E PR SIGY ETAN FAIL TDEL
      Card2: C P LCSS LCSR
      Card3: EPSD S DC
      Card4: EPS1-EPS8
      Card5: ES1-ES8

    Cards 1/2 are *MAT_024's (MAT_105 has no VP column — the formulation is
    always fully viscoplastic), so the record rides ``state.mat_plas_tab``;
    the EPS/ES pair sits one card lower because of the Lemaitre card 3.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    g3 = lambda i: to_float(f3[i]) if len(f3) > i else 0.0     # noqa: E731
    f4 = _card(raw, offset + 3, fixed=False)
    f5 = _card(raw, offset + 4, fixed=False)
    mat = MatPlasTAB(
        mid, title, rho=g1(1), E=g1(2), nu=g1(3), sigy=g1(4), etan=g1(5),
        fail=g1(6), lcss=to_int(f2[2]) if len(f2) > 2 else 0,
        C=g2(0), P=g2(1),
        eps_pts=[to_float(v) for v in f4], es_pts=[to_float(v) for v in f5])
    mat.tdel = g1(7)
    mat.lcsr = to_int(f2[3]) if len(f2) > 3 else 0
    mat.epsd = g3(0)
    mat.damage_s = g3(1)
    mat.dc = g3(2)
    mat.family = "105"
    state.mat_plas_tab[mid] = mat


def handle_mat_strain_rate_dependent_plasticity(block: Block,
                                                state: ConversionState) -> None:
    """*MAT_STRAIN_RATE_DEPENDENT_PLASTICITY / *MAT_019 → /MAT/LAW121.

    Card layout (Vol II R17 pp.2-238/239):
      Card1: MID RO E PR VP
      Card2: LC1 ETAN LC2 LC3 LC4 TDEL RDEF

    A pure 1:1 pass-through — no curve is sampled or synthesized. LAW121's
    kernel is literally MAT_019's law: ``sigma_y = sigma_0(eps_dot) +
    E*Et/(E-Et)*eps_p`` with Et clamped to 0.99E (mat121c_newton.F), so ETAN
    goes into the TANG slot verbatim and Radioss does the Ep conversion itself.

    Every curve field is typed F in the manual but only ever holds an integer
    id, so they are read through ``to_int``.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    gi2 = lambda i: to_int(f2[i]) if len(f2) > i else 0        # noqa: E731
    state.mat_strain_rate_plas[mid] = MatStrainRatePlas(
        mid=mid, title=title, rho=g1(1), E=g1(2), nu=g1(3), vp=int(g1(4)),
        lc1=gi2(0),
        etan=to_float(f2[1]) if len(f2) > 1 else 0.0,
        lc2=gi2(2), lc3=gi2(3), lc4=gi2(4),
        tdel=to_float(f2[5]) if len(f2) > 5 else 0.0,
        rdef=gi2(6))


def handle_mat_plasticity_compression_tension(block: Block,
                                              state: ConversionState) -> None:
    """*MAT_PLASTICITY_COMPRESSION_TENSION / *MAT_124 → /MAT/LAW66.

    Card layout (Vol II R17 pp.2-873..2-877):
      Card1: MID RO E PR C P FAIL TDEL
      Card2: LCIDC LCIDT LCSRC LCSRT SRFLAG LCFAIL EC RPCT
      Card3: PC PT PCUTC PCUTT PCUTF - - SRFILT
      Card4: K                                   — always present (may be blank)
      Card5: Gi BETAi                            — up to 6, to the next "*" card

    Card 4 is REQUIRED even when blank ("Card 4. This card is required."), so
    the Prony pairs always start at card 5; reading them from the first
    non-blank line after card 3 would swallow a blank K card's successor.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    gi2 = lambda i: to_int(f2[i]) if len(f2) > i else 0        # noqa: E731
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    g3 = lambda i: to_float(f3[i]) if len(f3) > i else 0.0     # noqa: E731
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    gis: List[float] = []
    betais: List[float] = []
    for idx in range(offset + 4, len(raw)):
        if not raw[idx].strip():
            continue
        fc = _card(raw, idx, fixed=True, n=8, w=10)
        if not fc or not fc[0].strip():
            continue
        gis.append(to_float(fc[0]))
        betais.append(to_float(fc[1]) if len(fc) > 1 else 0.0)
        if len(gis) >= 6:
            break
    state.mat_plas_comp_tens[mid] = MatPlasCompTens(
        mid=mid, title=title, rho=g1(1), E=g1(2), nu=g1(3),
        c=g1(4), p=g1(5), fail=g1(6), tdel=g1(7),
        lcidc=gi2(0), lcidt=gi2(1), lcsrc=gi2(2), lcsrt=gi2(3),
        srflag=g2(4), lcfail=gi2(5), ec=g2(6), rpct=g2(7),
        pc=g3(0), pt=g3(1), pcutc=g3(2), pcutt=g3(3), pcutf=g3(4),
        srfilt=g3(7),
        k=to_float(f4[0]) if f4 and f4[0].strip() else 0.0,
        gi=gis, betai=betais)


def handle_mat_gurson(block: Block, state: ConversionState) -> None:
    """*MAT_GURSON / *MAT_120 (+ _JC / _RCDC / _BFRAC) → /MAT/LAW52.

    Card layout (Vol II R17 pp.2-826..2-830):
      Card1: MID RO E PR SIGY N Q1 Q2
      Card2: FC F0 EN SN FN ETAN ATYP FF0
      Card3: EPS1-EPS8
      Card4: ES1-ES8
      Card5: L1 L2 L3 L4 FF1 FF2 FF3 FF4
      Card6: LCSS LCFF NUMINT LCF0 LCFC LCFN VGTYP DEXP

    The *_JC* variant replaces card 5 with ``LCDAM L1 L2 D1 D2 D3 D4 LCJC`` and
    keeps card 6 (Vol II R17 pp.2-837+); its D1-D4 are Johnson-Cook damage
    parameters and become a /FAIL/JOHNSON alongside the Gurson law.

    *_RCDC* / *_BFRAC* replace card 5 with a layout this converter does not
    model. Their card 6 is NOT read rather than read at a guessed stride: a
    mis-strided card 6 would silently produce a wrong LCSS/LCFF/LCF0 set, which
    is far worse than a named drop.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    kw = block.keyword
    if "_JC" in kw:
        variant = "JC"
    elif "_RCDC" in kw:
        variant = "RCDC"
    elif "_BFRAC" in kw:
        variant = "BFRAC"
    else:
        variant = ""
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    f5 = _card(raw, offset + 4, fixed=True, n=8, w=10)
    g5 = lambda i: to_float(f5[i]) if len(f5) > i else 0.0     # noqa: E731
    mat = MatGurson(
        mid=mid, title=title, rho=g1(1), E=g1(2), nu=g1(3), sigy=g1(4),
        n=g1(5), q1=g1(6), q2=g1(7),
        fc=g2(0), f0=g2(1), en=g2(2), sn=g2(3), fn=g2(4), etan=g2(5),
        atyp=int(g2(6)), ff0=g2(7),
        eps_pts=[to_float(v) for v in f3], es_pts=[to_float(v) for v in f4],
        variant=variant)
    if variant == "":
        mat.lengths = [g5(i) for i in range(4)]
        mat.ffs = [g5(i) for i in range(4, 8)]
    elif variant == "JC":
        mat.jc_lcdam = to_int(f5[0]) if f5 else 0
        mat.jc_l1, mat.jc_l2 = g5(1), g5(2)
        mat.jc_d = [g5(i) for i in range(3, 7)]
        mat.jc_lcjc = to_int(f5[7]) if len(f5) > 7 else 0
    if variant in ("", "JC"):
        f6 = _card(raw, offset + 5, fixed=True, n=8, w=10)
        gi6 = lambda i: to_int(f6[i]) if len(f6) > i else 0    # noqa: E731
        g6 = lambda i: to_float(f6[i]) if len(f6) > i else 0.0  # noqa: E731
        mat.lcss, mat.lcff = gi6(0), gi6(1)
        mat.numint = g6(2)
        mat.lcf0, mat.lcfc, mat.lcfn = gi6(3), gi6(4), gi6(5)
        mat.vgtyp, mat.dexp = g6(6), g6(7)
    state.mat_gurson[mid] = mat

    if variant == "JC":
        state.warn(
            f"*MAT_GURSON_JC {mid}: the _JC variant adds a Johnson-Cook "
            "failure strain on top of the Gurson porosity. The Gurson law "
            "converts to /MAT/LAW52 and D1-D4 become a companion "
            f"/FAIL/JOHNSON/{mid}, but LS-DYNA applies the two criteria "
            "TOGETHER inside one material while Radioss evaluates the /FAIL "
            "card independently of the LAW52 f_F coalescence — the coupling "
            "(LCDAM element-length scaling and the L1/L2 triaxiality bounds) "
            "is NOT reproduced. (dyna2rad drops the whole keyword silently: "
            "*MAT_GURSON_JC is not in its material map.)")
    elif variant in ("RCDC", "BFRAC"):
        state.warn(
            f"*MAT_GURSON_{variant} {mid}: this variant's card 5 is not the "
            "(L1..L4, FF1..FF4) element-length table of the base keyword and "
            "k2rad does not model it, so cards 5 AND 6 are left UNREAD — LCSS, "
            "LCFF, NUMINT, LCF0, LCFC, LCFN, VGTYP and DEXP are all DROPPED "
            "and the material converts as the plain Gurson law of cards 1-4 "
            "(hardening from ATYP, failure void fraction from FF0). Reading "
            "card 6 at a guessed stride would silently invent those ids. "
            "Restate the material as plain *MAT_GURSON if those fields "
            "matter. (dyna2rad drops the whole keyword silently.)")


def handle_mat_isotropic_elastic_plastic(block: Block,
                                         state: ConversionState) -> None:
    """*MAT_ISOTROPIC_ELASTIC_PLASTIC / *MAT_012 → /MAT/LAW2 (PLAS_JOHNS).

    Card layout (Vol II R17 p.2-206), ONE card only:
      Card1: MID RO G SIGY ETAN BULK

    The only LS-DYNA plasticity card stated in SHEAR + BULK modulus; E and nu
    are derived in the writer prepass. ETAN is the manual's "Plastic hardening
    modulus" (p.2-206), i.e. dSIGMA/dEPS_PLASTIC — NOT the total-curve tangent
    modulus *MAT_003 spells with the same name — so it needs no E*ET/(E-ET)
    rescale on the way to LAW2's ``b``.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    state.mat_iso_elas_plas[mid] = MatIsoElasPlas(
        mid=mid, title=title, rho=g1(1), g=g1(2), sigy=g1(3), etan=g1(4),
        bulk=g1(5))


def handle_mat_hill_3r(block: Block, state: ConversionState) -> None:
    """*MAT_HILL_3R / *MAT_122 → /MAT/LAW43 (HILL_TAB) or /MAT/LAW32 (HILL).

    Card layout (Vol II R17 pp.2-851..2-854), FIVE required cards:
      Card1: MID RO E PR HR P1 P2
      Card2: R00 R45 R90 LCID E0
      Card3: AOPT
      Card4: (3 blank) A1 A2 A3
      Card5: V1 V2 V3 D1 D2 D3 BETA

    HR selects the hardening rule and therefore the target law: 1 (linear) and
    3 (load curve) are tabular → LAW43; 2 (exponential, sigma = k*(E0+eps_p)^n)
    is analytic and matches /MAT/LAW32's Swift form exactly, so it is routed
    there instead of being dropped.

    Note P1/P2 for HR=1: P1 is the TANGENT modulus and P2 the YIELD STRESS
    (p.2-852) — the opposite of dyna2rad's ``{(0, P1), (1, P1+P2)}`` curve.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    g1 = lambda i: to_float(f1[i]) if len(f1) > i else 0.0     # noqa: E731
    mid = to_int(f1[0]) if f1 else 0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g2 = lambda i: to_float(f2[i]) if len(f2) > i else 0.0     # noqa: E731
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    g4 = lambda i: to_float(f4[i]) if len(f4) > i else 0.0     # noqa: E731
    f5 = _card(raw, offset + 4, fixed=True, n=8, w=10)
    g5 = lambda i: to_float(f5[i]) if len(f5) > i else 0.0     # noqa: E731
    # HR blank defaults to 1.0 (linear) — to_float("") would make it 0 and pick
    # no hardening rule at all.
    state.mat_hill_3r[mid] = MatHill3R(
        mid=mid, title=title, rho=g1(1), E=g1(2), nu=g1(3),
        hr=_ffield(f1, 4, 1.0) or 1.0, p1=g1(5), p2=g1(6),
        r00=g2(0), r45=g2(1), r90=g2(2),
        lcid=to_int(f2[3]) if len(f2) > 3 else 0, e0=g2(4),
        aopt=to_float(f3[0]) if f3 else 0.0,
        a1=g4(3), a2=g4(4), a3=g4(5),
        v1=g5(0), v2=g5(1), v3=g5(2),
        d1=g5(3), d2=g5(4), d3=g5(5), beta=g5(6))


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
        vp=vp, rate_curves=rate_curves, family="098")


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


def handle_mat_composite_damage(block: Block, state: ConversionState) -> None:
    """*MAT_COMPOSITE_DAMAGE (MAT_022) → /MAT/LAW25 (COMPSH) + /FAIL/CHANG on
    shells, /MAT/LAW127 on solids (writer/composites._mat022_law routes).

    Card layout (LS-DYNA Manual Vol II R17 p.2-257/2-258; matches
    ``hm_cfg_files/.../Keyword971_R9.0/MAT/mat_022.cfg`` FORMAT(Keyword971)):
      Card1: MID RO EA EB EC PRBA PRCA PRCB
      Card2: GAB GBC GCA KFAIL AOPT MACF ATRACK
      Card3: XP YP ZP A1 A2 A3
      Card4: V1 V2 V3 D1 D2 D3 BETA
      Card5: SC XT YT YC ALPH SN SYZ SZX

    Cards 3 and 4 are the same axis pair MAT_002 and MAT_054 carry, so they
    are read through the shared ``_read_axis_cards``: field 7 of card 3 is
    unused here (MAT_002 spells it MACF, MAT_054 MANGLE; MAT_022 puts MACF on
    card 2 instead) and field 7 of card 4 is BETA.

    All five cards are read at FIXED columns, the convention every AOPT-card
    material in this file uses — a slot the active AOPT does not need is blank,
    not absent, so there is no conditional card shape to track.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw

    def cf(idx, i, default=0.0):
        f = _card(raw, offset + idx, fixed=True, n=8, w=10)
        return to_float(f[i]) if len(f) > i and f[i].strip() else default

    def ci(idx, i, default=0):
        f = _card(raw, offset + idx, fixed=True, n=8, w=10)
        return to_int(f[i]) if len(f) > i and f[i].strip() else default

    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    mid = to_int(f1[0]) if f1 else 0
    (xp, yp, zp, a1, a2, a3, _f7,
     v1, v2, v3, d1, d2, d3, beta) = _read_axis_cards(raw, offset + 2,
                                                      offset + 3)
    ncards = 0
    for k in range(len(raw) - offset):
        if raw[offset + k].strip():
            ncards = k + 1
    if ncards > 5:
        state.warn(
            f"*MAT_COMPOSITE_DAMAGE mid={mid}: {ncards} data cards were read "
            "where the keyword defines exactly 5 — the extra line(s) are "
            "IGNORED. This is the fingerprint of a fixed-format card shift (a "
            "missing or duplicated blank card), which silently moves every "
            "following field into the wrong slot; check the card order "
            "against MID/RO/EA.. | GAB/GBC/GCA/KFAIL/AOPT/MACF/ATRACK | "
            "XP/YP/ZP/A1/A2/A3 | V1/V2/V3/D1/D2/D3/BETA | "
            "SC/XT/YT/YC/ALPH/SN/SYZ/SZX.")
    state.mat_composite_damage[mid] = MatCompositeDamage(
        mid=mid, title=title, rho=cf(0, 1),
        ea=cf(0, 2), eb=cf(0, 3), ec=cf(0, 4),
        prba=cf(0, 5), prca=cf(0, 6), prcb=cf(0, 7),
        gab=cf(1, 0), gbc=cf(1, 1), gca=cf(1, 2), kfail=cf(1, 3),
        aopt=cf(1, 4), macf=ci(1, 5), atrack=ci(1, 6),
        xp=xp, yp=yp, zp=zp, a1=a1, a2=a2, a3=a3,
        v1=v1, v2=v2, v3=v3, d1=d1, d2=d2, d3=d3, beta=beta,
        sc=cf(4, 0), xt=cf(4, 1), yt=cf(4, 2), yc=cf(4, 3),
        alph=cf(4, 4), sn=cf(4, 5), syz=cf(4, 6), szx=cf(4, 7))


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


def handle_mat_fabric(block: Block, state: ConversionState) -> None:
    """*MAT_FABRIC / *MAT_034 → /MAT/LAW19 (FABRI) or /MAT/LAW58 (FABR_A).

    A RAW-CONTIGUITY card walk (#119): cards 4, 7 and 8 are CONDITIONAL and
    every card after them shifts, so the index is advanced explicitly rather
    than assumed. Reading card 5 at a fixed ``offset + 4`` on an FVOPT<0 deck
    would take the L/R/C1/C2/C3 leakage card as RGBRTH/A0REF/A1..A3, silently
    turning a leakage constant into a reference-geometry birth time.

    The gates, from the Vol II R16 card summary (p.2-313) and the data-card
    headings (pp.2-325…2-330):

      card 4  present when ``FVOPT < 0``
      card 7  present when ``FORM in {4, 14, -14, 24}``
      card 8  present when ``FORM == -14``

    ``FORM``, ``FVOPT`` and ``LNRC`` are declared **F**, not I, on the LS-DYNA
    card — real decks write ``0`` and ``0.0`` interchangeably in those columns
    — so FORM is read as a float and rounded, and the sign is kept (FORM = -14
    is a distinct model from +14).

    Card-1 fields 4 and 7 and card-6 fields 3-5 are blank in the R8.0+ layout
    (they were EC / PRCA-PRCB and D1-D3 in R6.1) and are not read. Card-2
    fields 1-2 ARE read: they were GBC and GCA and, where an old deck fills
    them, they are the only transverse-shear moduli it states.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw

    def card(i):
        return _card(raw, i, fixed=True, n=8, w=10)

    def flt(f, i):
        return to_float(f[i]) if len(f) > i else 0.0

    def integer(f, i):
        return to_int(f[i]) if len(f) > i else 0

    i = offset
    f1 = card(i); i += 1
    f2 = card(i); i += 1
    f3 = card(i); i += 1
    mid = to_int(f1[0]) if f1 else 0
    fvopt = flt(f3, 6)
    # Card 4 (L R C1 C2 C3) exists only for FVOPT < 0. Its five values have no
    # Radioss counterpart (they parameterise LS-DYNA's own porous-flow fit), so
    # the card is SKIPPED rather than stored — but it must be skipped, not
    # ignored, or cards 5 and 6 are read one line early.
    if fvopt < 0.0:
        i += 1
    f5 = card(i); i += 1
    f6 = card(i); i += 1
    form = int(round(flt(f3, 5)))
    f7 = card(i) if form in FABRIC_CURVE_FORMS else []
    if form in FABRIC_CURVE_FORMS:
        i += 1
    f8 = card(i) if form == -14 else []

    state.mat_fabric[mid] = MatFabric(
        mid=mid, title=title,
        rho=flt(f1, 1), ea=flt(f1, 2), eb=flt(f1, 3),
        prba=flt(f1, 5), prab=flt(f1, 6),
        gab=flt(f2, 0), gbc=flt(f2, 1), gca=flt(f2, 2), cse=flt(f2, 3),
        el=flt(f2, 4), prl=flt(f2, 5), lratio=flt(f2, 6), damp=flt(f2, 7),
        aopt=flt(f3, 0), flc=flt(f3, 1), fac=flt(f3, 2), ela=flt(f3, 3),
        lnrc=flt(f3, 4), form=form, fvopt=fvopt, tsrfac=flt(f3, 7),
        rgbrth=flt(f5, 1), a0ref=flt(f5, 2),
        a1=flt(f5, 3), a2=flt(f5, 4), a3=flt(f5, 5),
        x0=flt(f5, 6), x1=flt(f5, 7),
        v1=flt(f6, 0), v2=flt(f6, 1), v3=flt(f6, 2),
        beta=flt(f6, 6), isrefg=integer(f6, 7),
        lca=integer(f7, 0), lcb=integer(f7, 1), lcab=integer(f7, 2),
        lcua=integer(f7, 3), lcub=integer(f7, 4), lcuab=integer(f7, 5),
        rl=flt(f7, 6),
        lcaa=integer(f8, 0), lcbb=integer(f8, 1), hyst=flt(f8, 2),
        dt_avg=flt(f8, 3), ecoat=flt(f8, 5), scoat=flt(f8, 6),
        tcoat=flt(f8, 7),
    )


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
    # Card 3b field 8 is TSHEAR where card 3a has THSHEL — the SAME column with
    # a different meaning, so it is read on the _TSHELL variant only. Radioss
    # thick shells have no constant-shear option, so the writer warn-drops it;
    # reading it is what lets it be NAMED rather than lost silently, the way the
    # *SECTION_TSHELL path names its own TSHEAR.
    tshear = to_int(fd[7]) if len(fd) > 7 and fd[7].strip() \
        and variant == "TSHELL" else 0
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
        tshear=tshear, long_form=long_form, irpl=irpl, optt=optt)
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
    """*MAT_RIGID (MAT_020) → /MAT/ELAST + a deferred /RBODY.

    Card 3 (``LCO or A1  A2  A3  V1  V2  V3``, Vol II R16 p.2-233) is read for
    the body's own LOCAL system, which is what
    *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL drives in: "LCO also specifies the
    coordinate system used for *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL. Defaults
    to the principal coordinate system of the rigid body."

    Field 1 is EITHER ``LCO`` (a *DEFINE_COORDINATE_* id) or ``A1`` (the first
    component of vector **a**), which the card itself does not disambiguate. The
    vector form needs BOTH **a** and **v** to be real vectors — the triad is
    ``c = a x v``, ``b = c x a`` — so a non-zero V1/V2/V3 selects it and a lone
    non-zero field 1 is LCO. The manual's own worked example
    (Vol I R16 p.11-150) writes card 3 as a single ``&flg5cid`` next to a
    *BOUNDARY_PRESCRIBED_MOTION_RIGID_local, which is exactly that shape.
    """
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
    # Card3: LCO or A1 | A2 A3 | V1 V2 V3 — "must be included but may be blank".
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    v3 = [to_float(f3[j]) if len(f3) > j and f3[j].strip() else 0.0
          for j in range(6)]
    lco, a_vec, v_vec = 0, None, None
    if any(v3[3:]) and any(v3[:3]):
        a_vec, v_vec = (v3[0], v3[1], v3[2]), (v3[3], v3[4], v3[5])
    elif v3[0] and not (v3[1] or v3[2]):
        lco = int(v3[0])
    state.mat_rigid[mid] = MatRigid(mid, title, rho, E, nu, cmo, con1, con2,
                                    lco=lco, a_vec=a_vec, v_vec=v_vec)


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
        # K is the UNREACTED bulk modulus and maps 1:1 onto /MAT/LAW5's
        # Bunreacted cell (Vol II R17 p.2-188 `p = K(1/V - 1)` against
        # jwl51.F:197 `Psol = C01 + C11*MU1`); G and SIGY have no LAW5 slot.
        # All three used to be unread, which is why the cell went out as 0 and
        # a LAW51 Iform=12 deck met ERROR 99 (fill_buffer_51.F:496).
        k=to_float(f[5])    if len(f) > 5 else 0.0,
        g=to_float(f[6])    if len(f) > 6 else 0.0,
        sigy=to_float(f[7]) if len(f) > 7 else 0.0,
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
        eosid=eosid, kind="POLYNOMIAL", keyword=block.keyword,
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
        eosid=eosid, kind="GRUNEISEN", keyword=block.keyword,
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
        eosid=eosid, kind="IDEAL-GAS", keyword=block.keyword,
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

def _clear_smooth_flag_on_redefinition(state: ConversionState, lcid: int,
                                       keyword: str) -> None:
    """Drop the ``/FUNCT_SMOOTH`` flag when a PLAIN curve producer overwrites
    ``state.curves[lcid]``, and name the duplicate.

    Every producer that stores piecewise-linear points under a USER lcid has to
    call this, not just the one the first reviewer looked at: the emitted CARD
    KIND must match the points that survive, or a sampled/plain curve goes out
    as ``/FUNCT_SMOOTH`` and ``fixfingeo.F:194-200`` / ``fixvel.F:314-316``
    read it quintic-blended. Gating the guard on ONE keyword spelling while a
    sibling with the same risk stays uncovered is the #124 class — which is
    exactly what happened here: the guard shipped on ``*DEFINE_CURVE`` and was
    dead on ``*DEFINE_CURVE_FUNCTION``.
    """
    if lcid not in state.funct_smooth_ids:
        return
    state.funct_smooth_ids.discard(lcid)
    state.warn(
        f"{keyword} LCID {lcid}: a *DEFINE_CURVE_SMOOTH already "
        "defined this id. LS-DYNA shares one load-curve id namespace "
        "between the two keywords (Vol I R17 p.17-153: the "
        "*DEFINE_CURVE_SMOOTH LCID 'must be unique'), so one of them is a "
        f"mistake. The {keyword} points below were kept and the curve "
        "is emitted as an ordinary /FUNCT; renumber one of the two cards.")


def handle_define_curve(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    # Header card: lcid sidr sfa sfo offa offo dattyp lcint
    f1   = _card(raw, offset, fixed=True, n=8, w=10)
    lcid = to_int(f1[0])
    sidr = to_int(f1[1]) if len(f1) > 1 else 0
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
    # A *DEFINE_CURVE_SMOOTH may have claimed this id first. LS-DYNA's curve
    # ids are unique across both keywords, so such a deck is malformed — but
    # the emitted CARD KIND must still match the points that survive.
    _clear_smooth_flag_on_redefinition(state, lcid, "*DEFINE_CURVE")
    state.curves[lcid] = Curve(lcid, title, sfa, sfo, offa, offo, pts,
                               sidr=sidr)
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


def handle_define_table_3d(block: Block, state: ConversionState) -> None:
    """*DEFINE_TABLE_3D → /TABLE/1 (Ndim=3) — a table of *DEFINE_TABLE[_2D]s.

    Header card (Keyword971_R13.0 define_table_3D.cfg): TBID SFA OFFA — same
    as the 2-D form. Point cards (Vol I R17 p.2571): VALUE (chars 1-20) and
    TABLEID (chars 21-40), a *DEFINE_TABLE/_2D id — ALWAYS explicit, there is
    no legacy positional form for the 3-D keyword. V = SFA·(VALUE+OFFA), the
    *DEFINE_CURVE abscissa convention. Validation against the referenced 2-D
    tables and the flat Ndim=3 /TABLE/1 emission (starter grid rules, ERROR
    3089) live in the writer post-pass _resolve_define_tables_3d.

    *DEFINE_TABLE_4D..9D stay unregistered on purpose: Radioss /TABLE caps at
    Ndim=4 and no supported consumer reads one — they fall into
    skipped_keywords and any material referencing them warns as dangling.
    """
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
    rows: List = []          # (V, 2-D table id)
    bad = 0
    for line in raw[offset + 1:]:
        f = parse_free(line)
        if not f:
            continue
        val = (to_float(f[0]) + offa) * sfa
        tid = to_int(f[1]) if len(f) > 1 else 0
        if tid > 0:
            rows.append((val, tid))
        else:
            bad += 1
    if bad:
        state.warn(
            f"*DEFINE_TABLE_3D tbid={tbid}: {bad} row(s) without the required "
            "TABLEID field — those rows are dropped (the 3-D form has no "
            "positional curve pairing).")
    if not rows:
        state.warn(f"*DEFINE_TABLE_3D tbid={tbid}: no usable rows — skipped.")
        state.skipped_keywords.append(block.keyword)
        return
    state.define_tables_3d[tbid] = DefineTable3D(
        tbid=tbid, title=title, sfa=sfa, offa=offa, rows=rows)


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
    env: Dict[str, Any] = {"__builtins__": {}}
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
    # Same guard as handle_define_curve: these points are SAMPLED
    # piecewise-linear, so a *DEFINE_CURVE_SMOOTH that claimed this id first
    # must lose its flag or the sampled ramp is emitted as /FUNCT_SMOOTH.
    _clear_smooth_flag_on_redefinition(state, lcid, "*DEFINE_CURVE_FUNCTION")
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
    # DA1..DA4 are the NODAL ATTRIBUTES (Vol I R17 p.43-43 Remark 1): for
    # *CONTACT_TIEBREAK_NODES_TO_SURFACE they override NFLF/NSFL/NNEN/NMES for
    # this set. Recorded so the tiebreak writer can tell a deck that states one
    # from a deck whose four cells are the 0.0 LS-PrePost writes by default.
    def _da(i: int) -> float:
        return to_float(f1[i]) if len(f1) > i else 0.0
    da = (_da(1), _da(2), _da(3), _da(4))
    if any(da):
        state.node_set_attrs[nsid] = da


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


def handle_set_discrete_list(block: Block, state: ConversionState) -> None:
    """*SET_DISCRETE[_LIST] — the *ELEMENT_DISCRETE twin of the three sets
    above. Its only consumer is *DATABASE_HISTORY_DISCRETE_SET, whose cfg takes
    a ``SET_DISCRETE_IDPOOL`` id (database_history_discrete_set.cfg:25)."""
    _handle_set_elem_list(block, state, state.discrete_sets)


def _record_part_set_attrs(state: ConversionState, psid: int,
                           f1: List[str]) -> None:
    """Record the *SET_PART header's DA1..DA4 attributes when any is set.
    *CONTACT_INTERIOR reads them as per-set defaults (PSF / Fa / ED / TYPE,
    Manual Vol I R17 p.11-178); no other consumer uses them yet."""
    def _da(i: int) -> float:
        return to_float(f1[i]) if len(f1) > i and f1[i].strip() else 0.0
    da = (_da(1), _da(2), _da(3), _da(4))
    if any(da):
        state.part_set_attrs[psid] = da


def handle_set_part_list(block: Block, state: ConversionState) -> None:
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    psid = to_int(f1[0])
    _record_part_set_attrs(state, psid, f1)
    pids: List[int] = []
    for line in raw[offset + 1:]:
        for tok in parse_free(line):
            v = to_int(tok)
            if v > 0:
                pids.append(v)
    state.part_sets[psid] = (title, pids)


def _set_add_keywords():
    """Every ``*SET_<FAMILY>_ADD`` spelling, from the ONE family table in
    state.py. ``_TITLE`` needs no entry of its own: ``parser._split_keyword``
    strips it into ``block.options`` (Vol I R17 p.43-2 — "an additional
    keyword option TITLE may be appended to all the *SET keywords", exactly one
    80a line between the header and card 1).

    ``assembly._OFFSET_SPECS`` is generated from this same source, so the
    parser table and the ``*INCLUDE_TRANSFORM`` offset table cannot drift
    apart — an unmapped spelling would keep its original member set ids while
    the rest of the include was offset."""
    return tuple(row[1] for row in SET_ADD_FAMILIES)


def _handle_set_add(block: Block, state: ConversionState, family: str,
                    ncells: int, adds_name: str) -> None:
    """Shared parser for the whole ``*SET_<FAMILY>_ADD`` union family.

    An ``_ADD`` set's data ids are **SET** ids of its own family, never entity
    ids, so the block cannot land in the family's ordinary container at PARSE
    TIME (a child set may not be read yet, and every consumer reads the members
    as entity ids). It is stored per family here; the post-parse
    ``_flatten_set_adds`` prepass (writer/mesh.py) expands the union — with
    recursion, a cycle guard and a depth cap — into a plain set entry, so
    EVERY consumer resolves it without knowing the variant.

    *ncells* is that spelling's own card-1 cell WIDTH (see SET_ADD_FAMILIES),
    which is what ``_card`` has to slice to reach the attribute columns: PART
    is the one family whose DA1..DA4 are read (``_record_part_set_attrs``,
    for *CONTACT_INTERIOR), and it needs six. The other rows carry their card's
    documented width for the record; nothing reads past cell 1 on them.

    Member rows are claimed by RAW contiguity after the header card. Exact
    ZEROS are dropped: trailing zero padding is the LS-PrePost house style and
    is NOT a member — measured in two corpus carriers, e.g.
    ``show-cases/contact-overview/main.k:172`` = ``100200301 100200302 0 0 0 0
    0 0``. The manual's "tightly packed data" remark scopes INTERIOR zeros
    only (identical text on every ``_ADD`` page).

    NEGATIVE cells are KEPT and passed on: on *SET_PART_ADD* a negative
    ``PSID[N]`` is the inclusive RANGE ``PSID[N-1] .. -PSID[N]`` (Vol I R17
    p.43-57), which can only be resolved once every child set is parsed —
    ``writer/mesh._expanded_member_ids`` does it, and warns by name on the six
    families whose page gives a negative cell no meaning at all.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=max(1, ncells), w=10)
    if not f1 or not f1[0].strip():
        return
    sid = to_int(f1[0])
    if family == "PART":
        # The PART header's DA1..DA4 are *CONTACT_INTERIOR's per-set defaults.
        _record_part_set_attrs(state, sid, f1)
    elif family == "NODE":
        # *SET_NODE_ADD's DA1..DA4 are the nodal attributes NFLF/NSFL/NNEN/NMES
        # (Vol I R17 p.43-43 Remark 1) — the per-set override of
        # *CONTACT_TIEBREAK_NODES_TO_SURFACE's Card 4. Recorded since #131
        # converts that keyword: the writer names the override as a loss only
        # when the deck actually states one.
        def _da(i: int) -> float:
            return to_float(f1[i]) if len(f1) > i else 0.0
        da = (_da(1), _da(2), _da(3), _da(4))
        if any(da):
            state.node_set_attrs[sid] = da
    ids: List[int] = []
    for line in raw[offset + 1:]:
        for tok in parse_free(line):
            v = to_int(tok)
            if v != 0:
                ids.append(v)
    getattr(state, adds_name)[sid] = (title, ids)


def handle_set_node_add_advanced(block: Block, state: ConversionState) -> None:
    """``*SET_NODE_ADD_ADVANCED`` — a node union across the SEVEN set families.

    Card 2b is ``SID1 TYPE1 SID2 TYPE2 SID3 TYPE3 SID4 TYPE4`` — four
    (id, family) PAIRS per card, not eight ids (Vol I R17 p.43-46). There is no
    operator column and no boolean-op table anywhere on the page: the purpose
    line is still "define a node set by combining NODE, SHELL, SOLID, BEAM,
    SEGMENT, DISCRETE, and TSHELL sets", i.e. a UNION whose non-node members
    contribute the nodes of their entities.

    dyna2rad reads this card as a plain id list (``convertsets.cxx:103``
    matches the substring "ADD" and never dispatches on TYPE), so the TYPE
    column is fed to ``GetValue("ids")`` as if it were another set id — a
    silently WRONG union. Reading the pairs is the whole difference.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        return
    nsid = to_int(f1[0])
    pairs: List[Tuple[int, int]] = []
    for k in range(offset + 1, len(raw)):
        if not raw[k].strip():
            continue
        f = _card(raw, k, fixed=True, n=8, w=10)
        for j in range(0, 8, 2):
            sid = to_int(f[j]) if len(f) > j else 0
            typ = to_int(f[j + 1]) if len(f) > j + 1 else 0
            # Only an exact ZERO is card padding. A NEGATIVE SID has no meaning
            # on this page — Vol I R17 p.43-46 gives card 2b's SID[N] no
            # GT.0/LT.0 block, unlike *SET_PART_ADD's PSID — so it is dropped;
            # but it is dropped BY NAME in writer/mesh._advanced_members, the
            # same rule the plain _ADD families got in the review round. A
            # silent drop here was the one spelling that still lost a member
            # without saying so.
            if sid != 0:
                pairs.append((sid, typ))
    state.node_set_add_advanced[nsid] = (title, pairs)


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


#: LS-DYNA *BOUNDARY_PRESCRIBED_MOTION VAD codes that k2rad cannot express.
#: 3 = velocity-versus-DISPLACEMENT and 4 = relative displacement (both rigid
#: bodies only, Manual Vol I R16 p.749): /IMPVEL, /IMPACC and /IMPDISP all take
#: a function of TIME, so the curve would silently be re-read against the wrong
#: abscissa. dyna2rad emits /IMPVEL anyway (warning 200002 for VAD=3 on _RIGID,
#: and a SILENT ``continue`` for VAD=4 and for VAD=3 on the non-rigid forms,
#: ``convertbcs.cxx:312-338``) — k2rad refuses instead, because a curve read
#: against time when it means displacement is a wrong answer, not a missing one.
_PM_VAD_UNSUPPORTED = {
    3: ("velocity versus DISPLACEMENT", "the curve abscissa is a displacement, "
        "but /IMPVEL evaluates its function against TIME"),
    4: ("RELATIVE displacement", "the motion is relative to a lead rigid body "
        "(LRB) and its two orientation nodes, which has no Radioss equivalent"),
}


def _bpm_walk(block: Block, is_box: bool = False):
    """Walk a *BOUNDARY_PRESCRIBED_MOTION block, yielding one ``(card1_fields,
    box_fields)`` tuple per ENTITY.

    The keyword's cards are not all card 1s. Per entity the official reader
    takes, in order (``boundary_prescribed_motion_{rigid,set,node}.cfg``;
    Manual Vol I R16 p.747-752):

      * card 1  ``TYPEID DOF VAD LCID SF VID DEATH BIRTH``            (always)
      * card 2  ``BOXID TOFFSET LCBCHK``                        (_SET_BOX only)
      * card 3  ``OFFSET1 OFFSET2 LRB NODE1 NODE2``   (|DOF| in 9/10/11, VAD=4)

    k2rad <= PR #116 looped over every non-blank line and read each as a card 1,
    so a |DOF|=11 or VAD=4 card's continuation was parsed as a second motion:
    ``OFFSET1`` became the node-set/part id and ``OFFSET2`` the DOF. That is a
    PHANTOM motion on whatever set id ``OFFSET1`` happens to name — silent
    whenever that set exists. ``assembly._bpm_cards`` already implemented the
    correct rule for the *INCLUDE_TRANSFORM offsets; this is the parser half.

    **Cards 2 and 3 are consumed POSITIONALLY — blank lines included.** Every
    field of card 3 defaults (``OFFSET1 0., OFFSET2 0., LRB 0, NODE1 0, NODE2
    0``, p.753) and TOFFSET/LCBCHK default to 0 (p.752), so an all-blank
    continuation card is legal input. Hunting for the next NON-blank line
    instead ate the FOLLOWING entity's card 1 and lost that motion silently.
    Only the card-1 hunt skips blanks (an all-default card 1 has TYPEID 0 and is
    not a motion at all).
    """
    raw = block.raw
    i = _title_offset(block)
    while i < len(raw):
        if not raw[i].strip():            # blank card placeholder → skip
            i += 1
            continue
        f1 = _card(raw, i, fixed=True, n=8, w=10)
        i += 1
        box: List[str] = []
        if is_box:
            box = _card(raw, i, fixed=True, n=8, w=10)   # blank => all defaults
            i += 1
        # Card 3 is consumed and discarded: OFFSET1/OFFSET2 place a rotation
        # axis (|DOF| 9/10/11) and LRB/NODE1/NODE2 drive VAD=4, none of which
        # k2rad converts. Skipping it here is what stops it being misread.
        if abs(to_int(f1[1]) if len(f1) > 1 else 0) in (9, 10, 11) \
                or (to_int(f1[2]) if len(f1) > 2 else 0) == 4:
            i += 1
        yield f1, box


def _pm_vad_supported(state: ConversionState, keyword: str, ref: str,
                      vad: int) -> bool:
    """False (with a warning) for a VAD k2rad will not convert.

    The test is TOTAL: anything outside ``PM_VAD_KEYWORD`` is refused, whether or
    not ``_PM_VAD_UNSUPPORTED`` has an explanation for it. Enumerating only the
    known-bad values (3 and 4) left every OTHER value — a typo, a negative, a
    future LS-DYNA code — passing the guard and reaching the writer's bare
    ``PM_VAD_KEYWORD[pm.vad]``, which raised KeyError and aborted the whole
    conversion with a traceback (measured: VAD=7 on _RIGID, VAD=9 on _SET).
    Before the guard existed at all, ``.get(vad, "IMPDISP")`` turned VAD 3 and 4
    into an /IMPDISP with no diagnostic.
    """
    if vad in PM_VAD_KEYWORD:
        return True
    info = _PM_VAD_UNSUPPORTED.get(vad)
    if info is None:
        state.warn(
            f"*{keyword} {ref}: VAD={vad} is not a *BOUNDARY_PRESCRIBED_MOTION "
            "velocity/acceleration/displacement flag — the keyword defines 0-4 "
            "only (Manual Vol I R16 p.751). Nothing is emitted for this card; "
            "the DOF is left free. VAD 0 = velocity, 1 = acceleration, "
            "2 = displacement.")
        return False
    kind, why = info
    state.warn(
        f"*{keyword} {ref}: VAD={vad} ({kind}) is NOT converted — {why}. "
        "Nothing is emitted for this card; the DOF is left free. Re-express the "
        "motion as a function of time (VAD=0/1/2) if you need it.")
    return False


def handle_boundary_prescribed_motion_rigid(block: Block, state: ConversionState) -> None:
    """*BOUNDARY_PRESCRIBED_MOTION_RIGID[_LOCAL] → /IMPVEL | /IMPACC | /IMPDISP
    on the rigid body's /RBODY main node.

    TYPEID is a *PART id (or a *CONSTRAINED_NODAL_RIGID_BODY PID). The _LOCAL
    option expresses DOF in the body's own, co-rotating system (Manual Vol I R16
    p.756-757 Remark 7) and is honoured with a /SKEW/MOV — see
    ``_synthesize_local_motion_frames``. ``_ID`` needs no key of its own
    (``parser._split_keyword`` strips it).
    """
    keyword = block.keyword
    local = keyword.endswith("_LOCAL")
    for f, _box in _bpm_walk(block):
        if len(f) < 4:
            continue
        pid   = to_int(f[0])
        dof   = to_int(f[1])
        vad   = to_int(f[2])
        lcid  = to_int(f[3])
        sf    = _ffield(f, 4, 1.0)
        vid   = to_int(f[5]) if len(f) > 5 else 0
        death = _ffield(f, 6, 1e28)
        birth = to_float(f[7]) if len(f) > 7 else 0.0
        if not _pm_vad_supported(state, keyword, f"pid={pid}", vad):
            continue
        state.prescribed_motions.append(
            PrescribedMotionRigid(pid, dof, vad, lcid, sf, death, birth,
                                  vid=vid, local=local)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Constraints
# ─────────────────────────────────────────────────────────────────────────────

#: The `*CONSTRAINED_NODAL_RIGID_BODY` option tokens, in the order their DATA
#: CARDS appear (Card Summary, Vol I R17 p.10-147): the `_SPC` constraint card is
#: card 2, `_INERTIA` cards 3-6, `_OVERRIDE` card 7, `_THERMAL` card 8. The NAME
#: order is arbitrary — "The order of the options in the keyword name is
#: arbitrary" (p.10-146) — so the spellings are generated (see
#: _cnrb_option_keywords) while the card walk always follows this order.
_CNRB_OPTIONS = ("SPC", "INERTIA", "OVERRIDE", "THERMAL")

#: `_TITLE` is an option of this keyword too, and the manual's arbitrary-order
#: sentence covers it: the documented list is "<BLANK> INERTIA OVERRIDE SPC
#: THERMAL TITLE" (p.10-146). It gets its own tuple because it adds a card but no
#: DATA — one 80a line ahead of card 1 — and because ``parser._split_keyword``
#: already moves a TRAILING `_TITLE` into ``block.options``. Only a MID-position
#: one (``*..._TITLE_INERTIA``) reaches the dispatcher spelled out, and without a
#: key for it the whole rigid body vanishes with no diagnostic at all.
_CNRB_TITLE_OPTIONS = ("TITLE", "SUBTITLE")


def _cnrb_options(keyword: str):
    """`(option set, has_title)` for a `*CONSTRAINED_NODAL_RIGID_BODY` spelling.

    Tokenises the suffix on ``_`` — safe here, unlike `*PART`, because none of the
    five option tokens contains an underscore. ``has_title`` is True when a
    `_TITLE`/`_SUBTITLE` survives IN THE KEYWORD, i.e. when it is not the trailing
    token the parser already stripped into ``block.options``.
    """
    opts: set = set()
    has_title = False
    for tok in keyword[len("CONSTRAINED_NODAL_RIGID_BODY"):].split("_"):
        if tok in _CNRB_OPTIONS:
            opts.add(tok)
        elif tok in _CNRB_TITLE_OPTIONS:
            has_title = True
    return opts, has_title


def _cnrb_option_keywords():
    """Every legal `*CONSTRAINED_NODAL_RIGID_BODY` spelling, generated.

    Same reasoning as _part_option_keywords and the #116 rigid-wall generator:
    the option order is free, ``dispatch()`` is an exact lookup, and an unlisted
    spelling means the rigid body silently vanishes from the model (here without
    even the orphan-element warning, because a CNRB owns no elements).

    ``TITLE`` is permuted in with the four data options, which takes the count
    from 65 to 326 — "The order of the options in the keyword name is arbitrary"
    (p.10-146) applies to the whole documented list, TITLE included. Leaving it
    out covered only the 130 spellings with `_TITLE` last (which the parser strips
    for us) and dropped the other 196 on the floor: measured, an otherwise
    identical deck gave `/RBODY/205` with Mass 7.25 for
    `*CONSTRAINED_NODAL_RIGID_BODY_INERTIA_TITLE` and
    ``SKIPPED: ['CONSTRAINED_NODAL_RIGID_BODY_TITLE_INERTIA']`` — no rigid body at
    all — for the same options written the other way round.

    The trailing-`_TITLE` keys are unreachable through ``dispatch`` today, since
    ``parser._split_keyword`` never leaves one on ``block.keyword``. They are
    generated anyway: a superset costs a dict entry, and it makes "every legal
    spelling has a key" true of the table itself rather than of the table plus an
    assumption about the parser.

    Yields (keyword, frozenset(data options)) — the title carries no data, so it
    is not in the returned set.
    """
    tokens = _CNRB_OPTIONS + ("TITLE",)
    for r in range(len(tokens) + 1):
        for combo in _permutations(tokens, r):
            yield ("_".join(("CONSTRAINED_NODAL_RIGID_BODY",) + combo),
                   frozenset(t for t in combo if t in _CNRB_OPTIONS))


def handle_constrained_nodal_rigid_body(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_NODAL_RIGID_BODY[_SPC][_INERTIA][_OVERRIDE][_THERMAL][_TITLE]
    → /RBODY (+ /BCS for _SPC, + Mass/Jxx..Jxz and /INIVEL for _INERTIA).

    LS-DYNA R17 Vol I (p.10-146..152), CARD-SUMMARY order — which is fixed even
    though the keyword's option order is not:
      Card 1: PID CID NSID PNODE IPRT DRFLAG RRFLAG
      Card 2 (_SPC):      CMO CON1 CON2 SPCNID XSPC YSPC ZSPC
        CMO>0 → CON1/CON2 are global translation/rotation codes (0-7);
        CMO<0 → CON1 is the local coordinate-system ID, CON2 a 6-digit local
        DOF code. Card-1 CID is the rigid body's (output/release) local system.
      Cards 3-5 (_INERTIA):  XC YC ZC TM IRCS NODEID / IXX..IZZ / VTX..VRZ
      Card 6 (IRCS=1):       XL YL ZL XLIP YLIP ZLIP CID2
      Card 7 (_OVERRIDE):    ICNT IBAG IPSM
      Card 8 (_THERMAL):     IDTHRM

    Two positional traps this walk exists to avoid. First, the cards are consumed
    by COUNT in the order above, never by option-name order and never with blank
    lines skipped — LS-PrePost writes an all-default card as blanks and the
    parser keeps it as a card placeholder, so `if not line.strip(): continue`
    would put every following card one slot out of phase (the PR #117 lesson).
    Second, card 6 is conditional on the ``IRCS`` VALUE read from card 3, not on
    an option name, so mis-reading card 3 also mis-strides card 6.

    Without `_INERTIA` the mass comes from `*ELEMENT_MASS_*` on the part/master
    node (see writer) — which matches LS-DYNA, where a CNRB without the option
    has "LS-DYNA compute the inertia tensor from the nodal masses".
    """
    raw = block.raw
    # The `_TITLE` line, from whichever place the option ended up: the parser
    # moves a TRAILING _TITLE into block.options, a mid-position one stays spelled
    # out in the keyword. Exactly one card either way — never two.
    opts, kw_title = _cnrb_options(block.keyword)
    offset = _title_offset(block) or (1 if kw_title else 0)
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
    title = ""
    if offset and raw:
        # _read_title only fires off block.options; a keyword-spelled _TITLE has
        # its 80a line at raw[0] just the same.
        title = (_read_title(block) if (_has_title(block) or _has_id(block))
                 else raw[0].strip())
    cnrb = ConstrainedNodalRigidBody(
        pid=pid, nsid=nsid, pnode=pnode, cid=cid, title=title,
    )
    idx = offset + 1
    if "SPC" in opts:
        # Card 2: CMO CON1 CON2 SPCNID XSPC YSPC ZSPC. Altair's own CNRB cfg
        # writes only the first three columns; the current manual has seven, and
        # this reads all of them.
        f2 = _card(raw, idx, fixed=True, n=8, w=10)
        idx += 1
        if f2:
            cnrb.has_spc = True
            cnrb.cmo    = to_float(f2[0]) if len(f2) > 0 else 0.0
            cnrb.con1   = to_int(f2[1])   if len(f2) > 1 else 0
            cnrb.con2   = to_int(f2[2])   if len(f2) > 2 else 0
            cnrb.spcnid = to_int(f2[3])   if len(f2) > 3 else 0
    if "INERTIA" in opts:
        inertia, used = _read_rigid_inertia(raw, idx)
        idx += used
        if inertia.has_mass_data() or inertia.has_velocity():
            cnrb.inertia = inertia
        else:
            state.warn(
                f"*{block.keyword} pid={pid}: the _INERTIA cards are entirely "
                "blank (no TM, no inertia tensor, no initial velocity), so there "
                "is nothing to transfer — the /RBODY keeps its MESH-derived mass "
                "and inertia (LS-DYNA does the same without the option). Card 4's "
                "own Default row marks IXX and IYY as required.")
        if idx > len(raw):
            state.warn(
                f"*{block.keyword} pid={pid}: the block ends part-way through the "
                "_INERTIA cards, so the mass properties read as zeros and were "
                "not transferred. Cards 3-5 are mandatory with the option (plus "
                "card 6 when IRCS=1).")
    if "OVERRIDE" in opts:
        f7 = _card(raw, idx, fixed=True, n=8, w=10)
        idx += 1
        if any(to_int(x) for x in f7[:3]):
            state.warn(
                f"*{block.keyword} pid={pid}: the _OVERRIDE card (ICNT/IBAG/IPSM) "
                "is DROPPED — it overrides LS-DYNA's automatic contact/airbag "
                "treatment of the rigid body's nodes, which has no /RBODY "
                "counterpart. Scope the contact interfaces explicitly instead.")
    if "THERMAL" in opts:
        f8 = _card(raw, idx, fixed=True, n=8, w=10)
        idx += 1
        state.warn(
            f"*{block.keyword} pid={pid}: the _THERMAL card (IDTHRM="
            f"{to_int(f8[0]) if f8 else 0}) is DROPPED — k2rad emits no thermal "
            "solver, so a rigid body's thermal-conduction flag has no target.")
    state.cnrbs.append(cnrb)


# ─────────────────────────────────────────────────────────────────────────────
# *CONSTRAINED_INTERPOLATION → /RBE3
#
# The DDOF/IDOF digit-string decoder that turns these cards into the /RBE3
# ``Trarot`` sub-columns lives next to the card layout it feeds,
# ``writer/rbe3.py::dof_digits_to_flags`` — no handler needs it, and no writer
# module imports handlers.
# ─────────────────────────────────────────────────────────────────────────────

def handle_constrained_interpolation(block: Block, state: ConversionState) -> None:
    """*CONSTRAINED_INTERPOLATION[_LOCAL] → /RBE3 (+ one /GRNOD/NODE per set).

    Card 1: ICID DNID DDOF CIDD ITYP IDNSW FGM.
    Card 2, repeated: INID IDOF TWGHTX TWGHTY TWGHTZ RWGHTX RWGHTY RWGHTZ.
    Card 3, only with _LOCAL and PAIRED with each card 2: CIDI.

    "One *CONSTRAINED_INTERPOLATION card is required for each constraint
    definition.  The input list of independent nodes is terminated when the next
    keyword ("*") card is found." (Vol I R17 p.10-41.) There is NO count field —
    unlike Radioss /RBE3, whose ``N_set`` is authoritative — so the pair list runs
    to the end of the block and the walk must consume it positionally.

    A blank line inside the list is a card of all-defaults, not padding: with
    ``_LOCAL`` a blank ``CIDI`` card is the NORMAL spelling for "global", and
    skipping it would pull the NEXT pair card into the CIDI slot and lose an
    independent node per pair. Only a wholly blank TAIL (no non-blank line left)
    ends the walk.
    """
    raw = block.raw
    is_local = block.keyword.endswith("_LOCAL")
    offset = _title_offset(block)
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if len(f1) < 2 or to_int(f1[0]) <= 0:
        state.warn("*CONSTRAINED_INTERPOLATION: incomplete Card 1 (no ICID) – "
                   "skipped; the interpolation constraint is NOT in the deck.")
        return
    icid = to_int(f1[0])
    dnid = to_int(f1[1])
    # DDOF default 123456 ("The default is 123456", p.10-42) — a real non-zero
    # default, so it must come from content, not from to_int("") == 0.
    ddof = to_int(f1[2]) if len(f1) > 2 and f1[2].strip() else 123456
    if ddof == 0:
        ddof = 123456
    cidd = to_int(f1[3]) if len(f1) > 3 else 0
    ityp = to_int(f1[4]) if len(f1) > 4 else 0
    idnsw = to_int(f1[5]) if len(f1) > 5 and f1[5].strip() else 1
    fgm = to_int(f1[6]) if len(f1) > 6 else 0
    rec = ConstrainedInterpolation(icid=icid, dnid=dnid, ddof=ddof, cidd=cidd,
                                  ityp=ityp, idnsw=idnsw, fgm=fgm,
                                  local=is_local)
    # A wholly blank TAIL is padding, not a pair card; anything before the last
    # non-blank line — blank or not — is one card of the pair list. Located once
    # rather than by re-slicing ``raw[i:]`` per iteration: an RBE3 spider runs to
    # thousands of independent nodes and the slice copies N-i references each time.
    last_data = -1
    for j in range(len(raw) - 1, offset, -1):
        if raw[j].strip():
            last_data = j
            break
    i = offset + 1
    while i <= last_data:
        f2 = _card(raw, i, fixed=True, n=8, w=10)
        i += 1
        cidi = 0
        if is_local:
            f3 = _card(raw, i, fixed=True, n=8, w=10)
            i += 1
            cidi = to_int(f3[0]) if f3 else 0
        inid = to_int(f2[0]) if f2 else 0
        if inid <= 0:
            continue
        # IDOF default 123456; the five trailing weights default to TWGHTX ("the
        # other factors are set equal to this input value as the default",
        # p.10-43), and TWGHTX itself to 1.0.
        idof = to_int(f2[1]) if len(f2) > 1 and f2[1].strip() else 123456
        if idof == 0:
            idof = 123456
        wx = _ffield(f2, 2, 1.0)
        rec.indeps.append(InterpolationIndep(
            inid=inid, idof=idof, twghtx=wx,
            twghty=_ffield(f2, 3, wx), twghtz=_ffield(f2, 4, wx),
            rwghtx=_ffield(f2, 5, wx), rwghty=_ffield(f2, 6, wx),
            rwghtz=_ffield(f2, 7, wx), cidi=cidi))
    if idnsw not in (0, 1):
        state.warn(
            f"*{block.keyword} {icid}: IDNSW={idnsw} (continue the analysis with "
            "the constraints unchanged after a node is deleted) is DROPPED — "
            "/RBE3 has no deleted-node policy field. The default behaviour is "
            "kept.")
    if fgm:
        state.warn(
            f"*{block.keyword} {icid}: FGM={fgm} (special implicit constraint "
            "processing for a dependent node not attached to the mesh) is "
            "DROPPED — it selects an LS-DYNA implicit assembly path with no "
            "/RBE3 counterpart.")
    if is_local and cidd:
        state.warn(
            f"*{block.keyword} {icid}: the _LOCAL dependent system CIDD={cidd} is "
            "DROPPED. The /RBE3 dependent-node card is Node_IDr / Trarot_ref / "
            "N_set / I_modif — there is no skew column on it at /BEGIN 2022 (only "
            "the per-set skew_IDi, which carries CIDI). LS-DYNA keeps DDOF global "
            "either way ('DDOF are in the global coordinate system regardless of "
            "whether the LOCAL option is used or not'), so the dependent DOF "
            "selection is unaffected; a genuinely rotated dependent frame is not "
            "representable.")
    state.interpolations.append(rec)


# ─────────────────────────────────────────────────────────────────────────────
# Contacts
# ─────────────────────────────────────────────────────────────────────────────

def _parse_contact_header(block: Block):
    """Parse the optional *_ID / _TITLE header line, return
    (inter_id, title, data_offset).

    ``_TITLE`` consumes a header card exactly like ``_ID``: contact_spotweld.cfg
    is explicit about it on import (:1720-1725) — when ``_FIND(_opt,"_ID")``
    misses it retries ``_FIND(_opt,"_TITLE")`` and reads the SAME
    ``CARD("%10d%-70s", _ID_, TITLE)``. It is an Altair CFG extension (no
    *CONTACT_..._TITLE appears in the LSTC manual, and contact_spotweld.cfg is
    the only CONTACT cfg that defines it), but treating it as a plain option
    with no header card reads Card 1 off the heading line: SSID/SSTYP/MSID/
    MSTYP all come back 0 and the interface is silently dropped for "resolved
    to no nodes". Wrong in every reading, so both spellings consume the card.

    The card is FIXED format ``%10d%-70s`` (the CFG line quoted above), and
    LS-PrePost writes the title BUTTED against the id. A free split of
    ``"        10Kurbel self tiebreak contact"`` yields the single token
    ``10Kurbel``, which reads back as id 0 — so the deck's own id was silently
    replaced by an auto-id (breaking ``--inter-gapmin ID=…``, the /TH/INTER
    keying and every log line that names the interface) and the first word of
    the title was eaten. The fixed read is therefore tried FIRST; the free
    split stays as the fallback for a comma- or space-separated header, which
    is legal LS-DYNA too.
    """
    raw = block.raw
    if (_has_id(block) or "TITLE" in block.options) and raw:
        head = raw[0]
        col = head[:10]
        if col.strip() and "," not in col:
            try:
                fixed_id = int(col.strip())
            except ValueError:
                fixed_id = 0
            if fixed_id > 0:
                return fixed_id, head[10:80].strip(), 1
        f = parse_free(head)
        inter_id = to_int(f[0]) if f else 0
        title = " ".join(f[1:]) if len(f) > 1 else ""
        return inter_id, title, 1
    # No _ID header: return 0 so the caller assigns state.next_id(). (An older
    # fallback derived the id from the block's line count — every contact of the
    # same card shape got the same id, and multi-contact decks died with starter
    # ERROR 117 "INTERFACE ID USED TWICE OR MORE".)
    return 0, "", 0


def _read_contact_ignore(raw: List[str], offset: int, extra: int = 0) -> int:
    """Read LS-DYNA optional Card C (the 6th card): igap ignore dprfac dtstif ...

    ``extra`` is the number of MANDATORY cards that sit between Card 3 and
    optional Card A for this keyword flavour — 1 for *CONTACT_ERODING_* (its
    ISYM/EROSOP/IADJ Card 4), 0 otherwise. Reading IGNORE one line too early on
    an eroding deck lands on optional Card B (PENMAX/THKOPT/SHLTHK/SNLOG...),
    whose field 2 is THKOPT, and silently produces the wrong Inacti.
    """
    f = _card(raw, offset + 5 + extra, fixed=True, n=8, w=10)
    return to_int(f[1]) if len(f) > 1 else 0


def _read_contact_soft(raw: List[str], offset: int, extra: int = 0) -> int:
    """Read LS-DYNA optional Card A field 1 = SOFT (soft-constraint formulation).

    Card A sits immediately after Card 3 (offset+3), consistent with
    _read_contact_ignore's assumption that Cards A/B/C are all present (it reads
    IGNORE from Card C at offset+5). dyna2rad routes *CONTACT_AUTOMATIC_GENERAL
    on this field: SOFT -7/-11/-19 are hand-entered sentinels selecting
    /INTER/TYPE7/TYPE11/TYPE19; any ordinary value (0/1/2/blank, or Card A
    absent) leaves SOFT=0 → the default single-surface routing.

    ``extra`` shifts past a keyword-specific mandatory card between Card 3 and
    Card A — see _read_contact_ignore.
    """
    f = _card(raw, offset + 3 + extra, fixed=True, n=8, w=10)
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


def handle_contact_automatic_single_surface(block: Block, state: ConversionState,
                                            extra: int = 0,
                                            card1: Optional[int] = None,
                                            inter_id: Optional[int] = None) -> None:
    """``card1``/``inter_id``: a caller that has ALREADY resolved the block's
    first mandatory card index and its interface id passes them in. Both exist
    for the ``*CONTACT_..._TIEBREAK`` delegation, which needs them for two
    different reasons: an ``_MPP`` spelling puts its own card BEFORE Card 1, so
    re-deriving the offset from ``_parse_contact_header`` here reads SSID off
    the MPP IGNORE flag; and the caller has already resolved the id in order to
    name it in its warnings, so allocating a second one would make the log and
    the card disagree. Both default to the old behaviour."""
    hdr_id, title, offset = _parse_contact_header(block)
    if card1 is not None:
        offset = card1
    if inter_id is None:
        inter_id = hdr_id
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
    ignore = _read_contact_ignore(raw, offset, extra)
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


def handle_contact_automatic_surface_to_surface(block: Block, state: ConversionState,
                                                extra: int = 0,
                                                card1: Optional[int] = None,
                                                inter_id: Optional[int] = None) -> None:
    """``card1``/``inter_id`` — see
    :func:`handle_contact_automatic_single_surface`. Both default to the old
    behaviour; only the ``*CONTACT_..._TIEBREAK`` OPTION-4 delegation passes
    them."""
    hdr_id, title, offset = _parse_contact_header(block)
    if card1 is not None:
        offset = card1
    if inter_id is None:
        inter_id = hdr_id
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
    ignore = _read_contact_ignore(raw, offset, extra)
    state.contacts_surf2surf.append(
        ContactAutoSurf2Surf(inter_id, title, ssid, sstyp, msid, mstyp, fs, fd, bt, dt, ignore,
                             vdc=vdc, sst=sst, mst=mst, sfs=sfs,
                             keyword=block.keyword)
    )


def handle_contact_airbag_single_surface(block: Block,
                                         state: ConversionState) -> None:
    """``*CONTACT_AIRBAG_SINGLE_SURFACE`` (contact type a13) — a near-alias of
    the single-surface path, with the dyna2rad ``SOFT = -19`` sentinel routing
    to ``/INTER/TYPE19``.

    **The card grid is column-compatible with the general contact card**, which
    is what makes this an alias rather than a new parser.
    ``contact_airbag_single_surface.cfg:556-563`` writes card 1 as
    ``%10d          %10d          %10d          %10d%10d`` — SSID, then TEN
    BLANK columns where SURFB would be, then SSTYP, blanks, SBOX, blanks,
    SPR, IFLAG — so every field lands on the SAME 10-char grid index the
    two-sided card uses: SSID -> 0, SSTYP -> 2, SBOX -> 4, SPR -> 6. Card 3 is
    the same shape: SFS -> 0, SST -> 2, MST -> 3 (blank, so 0), SFST -> 4.

    The ONE genuinely new field is ``IFLAG`` in card-1 slot 7, where MPR sits
    on a two-sided contact. dyna2rad reads it and then branches on SOFT
    instead — its two ``if (IFLAG == …)`` lines are commented out
    (``convertcontacts.cxx:167-181``) — so the live routing is the same
    hand-entered ``SOFT = -19`` sentinel *CONTACT_AUTOMATIC_GENERAL and
    *CONTACT_ERODING_SINGLE_SURFACE already use here (#114). IFLAG is reported
    rather than acted on, because acting on a field dyna2rad demonstrably does
    not act on would silently split the two converters' output.

    Default (any other SOFT, or no card A) -> the validated single-surface
    routing, byte-for-byte unchanged: /INTER/TYPE25 explicit, /INTER/TYPE7
    implicit.
    """
    raw = block.raw
    inter_id, title, offset = _parse_contact_header(block)
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    iflag = to_int(f1[7]) if len(f1) > 7 else 0
    if iflag:
        state.warn(
            f"*{block.keyword}: IFLAG={iflag} is read and DROPPED. dyna2rad "
            "reads it too and then ignores it — the two IFLAG branches in "
            "convertcontacts.cxx:170/176 are commented out and the live test "
            "is on SOFT — so acting on it here would make the two converters "
            "disagree with no way to tell which is right. Use the SOFT = -19 "
            "sentinel on optional Card A to request /INTER/TYPE19 (combined "
            "surface + edge contact); anything else gives the ordinary "
            "single-surface interface.")
    soft = _read_contact_soft(raw, offset)
    if soft != -19:
        handle_contact_automatic_single_surface(block, state)
        return

    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    ssid = to_int(f1[0]) if f1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    _warn_contact_box(state, block.keyword, inter_id, f1)
    # Card2: fs fd dc vc vdc penchk bt dt
    f3 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs = to_float(f3[0]) if f3 else 0.0
    fd = to_float(f3[1]) if len(f3) > 1 else 0.0
    vdc = to_float(f3[4]) if len(f3) > 4 else 0.0
    bt = to_float(f3[6]) if len(f3) > 6 else 0.0
    dt = to_float(f3[7]) if len(f3) > 7 else 1e28
    # Card3: SFS <blank> SST <blank> SFST <blank> FSF VSF
    f4 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sfs = to_float(f4[0]) if f4 else 0.0
    sst = to_float(f4[2]) if len(f4) > 2 else 0.0
    sfst = to_float(f4[4]) if len(f4) > 4 else 0.0
    ignore = _read_contact_ignore(raw, offset)
    state.contacts_general.append(
        # SINGLE surface: the card genuinely has no SURFB, so the main side is
        # the secondary side mirrored. dyna2rad omits that mirror on this
        # keyword alone (the AUTOMATIC_GENERAL branch has it,
        # convertcontacts.cxx:139-163) and leaves surf_IDm at 0, which is an
        # interface against nothing.
        ContactAutoGeneral(inter_id, title, ssid, sstyp, ssid, sstyp, soft,
                           fs, fd, bt, dt, ignore, vdc=vdc, sst=sst, mst=0.0,
                           sfs=sfs, sfst=sfst, airbag=True,
                           keyword=block.keyword))


# ─────────────────────────────────────────────────────────────────────────────
# *CONTACT_..._TIEBREAK  —  the cohesive family
# ─────────────────────────────────────────────────────────────────────────────

#: The complete tiebreak family, from ONE source (#116): the dispatch table,
#: assembly._OFFSET_SPECS and the tests all read this dict, so a spelling
#: cannot exist in one and be missing from another. Vol I R17 p.11-14 lists
#: eleven spellings under "The following contacts are tiebreak contacts" and
#: p.11-14/15 adds the two Mortar ones.
#:
#: value = (Card-4 family, ``_ONLY``, one-way, self-tie)
_TIEBREAK_BASES: Dict[str, Tuple[str, bool, bool, bool]] = {
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK":
        ("AUTOMATIC", False, False, False),
    "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK":
        ("AUTOMATIC", False, True, False),
    "CONTACT_AUTOMATIC_SINGLE_SURFACE_TIEBREAK":
        ("AUTOMATIC", False, False, True),
    "CONTACT_AUTOMATIC_GENERAL_TIEBREAK":
        ("AUTOMATIC", False, False, True),
    "CONTACT_TIEBREAK_SURFACE_TO_SURFACE":
        ("SURFACE", False, False, False),
    "CONTACT_TIEBREAK_SURFACE_TO_SURFACE_ONLY":
        ("SURFACE", True, False, False),
    "CONTACT_TIEBREAK_NODES_TO_SURFACE":
        ("NODES", False, True, False),
    "CONTACT_TIEBREAK_NODES_ONLY":
        ("NODES", True, True, False),
}

#: Suffixes that name a DIFFERENT LS-DYNA keyword of the same family, per base.
#: ``parser._split_keyword`` strips only trailing ``_ID``/``_TITLE``/
#: ``_SUBTITLE`` (parser.py:41), so ``_USER``/``_MORTAR``/``_DAMPING`` reach the
#: dispatch table verbatim and need their own keys — without them they land in
#: ``skipped_keywords``, and a skipped *CONTACT is a missing LOAD PATH, not a
#: missing output card.
_TIEBREAK_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    # p.11-14: AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK{,_USER}; p.11-15 adds
    # _MORTAR and _USER_MORTAR. p.11-35: "The DAMPING option cannot be
    # combined with the MORTAR option."
    "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK":
        ("", "_USER", "_MORTAR", "_USER_MORTAR"),
    "CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_TIEBREAK":
        ("", "_DAMPING", "_USER"),
}

#: OPTION4 (the OFFSET options, Vol I R17 p.11-8) per base. p.11-16 scopes
#: ``BEAM_OFFSET`` on this family to exactly two spellings: *"BEAM_OFFSET is
#: also available when OPTION1 is: AUTOMATIC_SINGLE_SURFACE_TIEBREAK /
#: AUTOMATIC_GENERAL_TIEBREAK, but moments are transferred only when the
#: variable FTORQ is invoked (see Optional Card E)."* ``OFFSET`` and
#: ``CONSTRAINED_OFFSET`` are NOT offered for any tiebreak (p.11-16 lists them
#: for the three ``TIED_*`` types only), so they stay out.
#:
#: The option adds no MANDATORY card — FTORQ lives on optional Card E — so the
#: card stack, and with it every offset in ``assembly._OFFSET_SPECS``, is the
#: same as the base spelling's.
_TIEBREAK_OFFSETS: Dict[str, Tuple[str, ...]] = {
    "CONTACT_AUTOMATIC_SINGLE_SURFACE_TIEBREAK": ("", "_BEAM_OFFSET"),
    "CONTACT_AUTOMATIC_GENERAL_TIEBREAK":        ("", "_BEAM_OFFSET"),
}

#: Every spelling the dispatch table registers, ``_MPP`` included.
TIEBREAK_CONTACT_KEYWORDS: List[str] = [
    f"{_base}{_suf}{_off}{_mpp}"
    for _base in _TIEBREAK_BASES
    for _suf in _TIEBREAK_SUFFIXES.get(_base, ("",))
    for _off in _TIEBREAK_OFFSETS.get(_base, ("",))
    for _mpp in ("", "_MPP")
]

#: Card-4 ``OPTION`` → (bond class, what LS-DYNA does). Vol I R17 p.11-36 to
#: p.11-38 for the semantics, p.11-39/40 Remark 3 for the criteria.
#:
#: The bond classes, and why they are the partition that matters:
#:
#:   ``NOFAIL``   the tie NEVER breaks in LS-DYNA either — nothing is lost by
#:                emitting a permanent tie.
#:   ``CCRIT``    ``PARAM`` is a RELEASE DISTANCE. This is the ONLY class that
#:                states the one quantity ``/INTER/TYPE2``'s rupture needs
#:                (``Max_N_Dist``), so it is the only class whose failure the
#:                converter can reproduce without inventing a number.
#:   ``STRESS``   a stress criterion and NO length anywhere on the card.
#:   ``CURVE``    OPTION 5: ``SFLS`` is a *DEFINE_CURVE id, sigma_n(gap).
#:   ``SLIDE``    OPTION 4: tangential sliding is PERMITTED, so the LS-DYNA
#:                pre-failure state is not a tie at all.
#:   ``DYCOSS`` / ``COHESIVE`` / ``MAT240`` / ``USER`` — no counterpart of any
#:                kind in this OpenRadioss build.
_TIEBREAK_OPTION_CLASS: Dict[int, Tuple[str, str]] = {
    1: ("NOFAIL",
        "tracked nodes in contact and those that come into contact "
        "permanently stick, tangential motion inhibited — there is NO failure "
        "criterion (p.11-36), and NFLS/SFLS are not in this OPTION's field "
        "list (p.11-38) so LS-DYNA ignores them too"),
    -1: ("NOFAIL",
         "as OPTION 1 (permanent stick, no failure) with MOMENTS transferred"),
    2: ("STRESS",
        "tied for nodes INITIALLY in contact; failure at "
        "(|sn|/NFLS)^2 + (|ss|/SFLS)^2 >= 1 with compressive sn taken as zero, "
        "then a surface-to-surface contact with thickness offsets"),
    -2: ("STRESS", "as OPTION 2 with MOMENTS transferred"),
    3: ("STRESS",
        "as OPTION 1 (permanent stick, growing tie set) but WITH failure, at "
        "the same quadratic criterion as OPTION 2"),
    -3: ("STRESS", "as OPTION 3 with MOMENTS transferred"),
    4: ("SLIDE",
        "tied NORMALLY but tangential motion with frictional SLIDING is "
        "permitted; failure on the normal stress alone, |sn|/NFLS >= 1"),
    5: ("CURVE",
        "elastoplastic 'deformable glue bond': NFLS is a plastic yield stress "
        "and SFLS is a *DEFINE_CURVE id giving normal stress as a function of "
        "the crack opening"),
    6: ("CCRIT",
        "solids and thick shells: after the quadratic failure stress is "
        "reached, damage is a LINEAR function of the distance between the "
        "points initially in contact and interface failure occurs when that "
        "distance equals PARAM (CCRIT)"),
    7: ("DYCOSS",
        "Dycoss Discrete Crack Model — PARAM is a friction angle and the "
        "shear envelope is pressure-dependent, "
        "[max(sn,0)/NFLS]^2 + [ss/(SFLS - sin(PARAM)*min(0,sn))]^2 = 1"),
    8: ("CCRIT", "as OPTION 6 but for OFFSET SHELL elements"),
    9: ("COHESIVE",
        "Discrete Crack Model with power-law / Benzeggagh-Kenane mixed-mode "
        "damage (the *MAT_COHESIVE_MIXED_MODE fracture model); PARAM is the "
        "damage exponent and ERATEN/ERATES the energy release rates"),
    -9: ("COHESIVE",
         "as OPTION 9 with NFLS/SFLS/ERATEN/ERATES as functions of "
         "TEMPERATURE (MORTAR only)"),
    10: ("DYCOSS", "as OPTION 7 but for OFFSET SHELL elements"),
    11: ("COHESIVE", "as OPTION 9 but for OFFSET SHELL elements"),
    -11: ("COHESIVE", "as OPTION -9 but for OFFSET SHELL elements"),
    13: ("MAT240",
         "elastoplastic rate-dependent damage per *MAT_240, driven by cards "
         "4.1b/4.2b (G1C_0..LCG2C); NFLS, SFLS, ERATEN and ERATES are NOT "
         "used (p.11-42 Remark 7)"),
    14: ("MAT240", "as OPTION 13 but for OFFSET SHELL elements"),
}

#: OPTION 101..105 = the ``_USER`` subroutines ``utb101``..``utb105`` in
#: ``dyn21cnt.f`` (p.11-43).
_TIEBREAK_USER_OPTIONS = (101, 102, 103, 104, 105)


def _tiebreak_spelling(keyword: str):
    """Split a generated tiebreak spelling into
    ``(base, mortar, user, damping, beam_offset, mpp)``.

    Longest base first, so ``CONTACT_TIEBREAK_SURFACE_TO_SURFACE_ONLY`` is not
    swallowed by ``CONTACT_TIEBREAK_SURFACE_TO_SURFACE``.
    """
    for base in sorted(_TIEBREAK_BASES, key=len, reverse=True):
        if keyword == base or keyword.startswith(base + "_"):
            tail = keyword[len(base):]
            return (base, "_MORTAR" in tail, "_USER" in tail,
                    "_DAMPING" in tail, "_BEAM_OFFSET" in tail,
                    tail.endswith("_MPP"))
    return keyword, False, False, False, False, False


def _tiebreak_card4_extra(family: str, option: int, damping: bool,
                          user: bool = False) -> int:
    """Number of MANDATORY cards a tiebreak inserts between Card 3 and optional
    Card A — the ``extra`` every optional-card read has to be shifted by.

    Card 4 is MANDATORY for the whole family (Vol I R17 p.11-6 lists
    ``AUTOMATIC_..._TIEBREAK``, ``AUTOMATIC_..._TIEBREAK_USER``,
    ``TIEBREAK_NODES_...`` and ``TIEBREAK_SURFACE_...`` among the keywords that
    take one, and p.11-7 adds "the format of Card 4 (which can include multiple
    cards) is different for each option listed"), and the optional cards A-G
    follow AFTER it. Reading them at the un-shifted offset lands IGNORE on
    Card B's THKOPT — measured on a with/without twin, a deck with IGNORE=2
    reported ``ignore=0`` and a deck with THKOPT=3 reported ``ignore=3``.

    The ``_USER`` flavour replaces Card 4 with THREE cards of its own —
    p.11-43: *"These cards, 4.1, 4.2, and 4.3, are mandatory for:
    \\*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_USER …"* — Card 4.1
    (``OPTION NHV CT2CN CN OFFSET NHMAT NHWLD``) plus 4.2/4.3 (``UP1..UP16``).
    Counting one card there would land every optional-card read three rows
    early, and reading NFLS/SFLS/PARAM off Card 4.1 would report NHV/CT2CN/CN
    under three names the card does not have.

    Two further OPTIONs add mandatory cards after Card 4:
      * Card 4.1a (DMP_1 DMP_2 DMP_3) — p.11-35: "If the response parameter,
        OPTION, below is set to 9 or 11, three damping constants can be
        defined ... set the keyword option to DAMPING". Both conditions.
      * Cards 4.1b + 4.2b (G1C_0..LCG1C / G2C_0..LCG2C) — OPTION 13/14.
    """
    if user:
        return 3
    extra = 1
    if family == "AUTOMATIC":
        if damping and option in (9, 11):
            extra += 1
        elif option in (13, 14):
            extra += 2
    return extra


def handle_contact_tiebreak(block: Block, state: ConversionState) -> None:
    """``*CONTACT_..._TIEBREAK`` — the cohesive family, routed by Card 4.

    LS-DYNA Vol I R17 p.11-9 defines the family: *"TIEBREAK is a special case
    of a tied contact allowing failure in which the contact usually becomes a
    regular one-way, two-way, or single surface version after failure."* So the
    PRE-failure state is a TIE, and that is what this handler preserves — a
    plain ``/INTER/TYPE7`` (what k2rad emitted before) has no bond at all and
    loses the joint's load path from t = 0, not only after failure.

    Card 4 decides the route:

    * the bond classes whose pre-failure state is a tie (every OPTION except 4,
      and both ``TIEBREAK_SURFACE`` / ``TIEBREAK_NODES`` spellings) become a
      :class:`~k2rad.state.ContactTiebreak` record, which the writer turns into
      ``/INTER/TYPE2`` — with the rupture cards when the OPTION states a
      release distance, as a permanent tie otherwise;
    * ``OPTION = 4`` permits tangential sliding, so LS-DYNA's own pre-failure
      state is NOT a tie — it keeps the existing penalty-contact route and the
      bond is a named warn-drop;
    * ``*CONTACT_AUTOMATIC_{SINGLE_SURFACE,GENERAL}_TIEBREAK`` tie a surface to
      ITSELF, which ``/INTER/TYPE2`` has no shape for — the same node list
      would be both the secondary /GRNOD and the main /SURF — so they keep the
      self-contact route with a named warn-drop.
    """
    kw = block.keyword
    base, mortar, user, damping, beam_offset, mpp = _tiebreak_spelling(kw)
    family, only, one_way, self_tie = _TIEBREAK_BASES[base]

    raw = block.raw
    inter_id, title, hdr = _parse_contact_header(block)
    offset = _contact_mpp_card_offset(raw, hdr, mpp)
    # Resolve the id HERE, before the first warning is built: the fixup below
    # used to run only on the tie route, so on a deck whose CID sits outside
    # (0, 90000] every warning named the deck's id while the emitted /INTER
    # carried an auto one. The two delegated routes are handed this id
    # (``inter_id=``) instead of allocating their own, so the id STREAM is
    # unchanged — same number of next_id() calls, in the same order.
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    tag = f"*{kw} {inter_id}"

    # ── Card 4 ───────────────────────────────────────────────────────────
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)

    def _g(i: int) -> float:
        return to_float(f4[i]) if len(f4) > i else 0.0

    option = 0
    nfls = sfls = param = eraten = erates = ct2cn = cn = 0.0
    nflf = sflf = nen = mes = 0.0
    tblcid = thkoff = 0
    nhv = user_offset = nhmat = nhwld = 0
    if user:
        # Card 4.1 is a DIFFERENT card: OPTION NHV CT2CN CN OFFSET NHMAT NHWLD
        # (Vol I R17 p.11-43). NFLS/SFLS/PARAM/ERATEN/ERATES do not exist on
        # it — reading them off columns 2-6 would report NHV as a failure
        # stress and CT2CN as a shear one.
        option = to_int(f4[0]) if f4 else 0
        nhv = to_int(f4[1]) if len(f4) > 1 else 0
        ct2cn, cn = _g(2), _g(3)
        user_offset = to_int(f4[4]) if len(f4) > 4 else 0
        nhmat = to_int(f4[5]) if len(f4) > 5 else 0
        nhwld = to_int(f4[6]) if len(f4) > 6 else 0
    elif family == "AUTOMATIC":
        option = to_int(f4[0]) if f4 else 0
        nfls, sfls, param = _g(1), _g(2), _g(3)
        eraten, erates, ct2cn, cn = _g(4), _g(5), _g(6), _g(7)
    elif family == "SURFACE":
        nfls, sfls = _g(0), _g(1)
        tblcid = to_int(f4[2]) if len(f4) > 2 else 0
        thkoff = to_int(f4[3]) if len(f4) > 3 else 0
        # LS-DYNA's own documented rewrite of this spelling onto the AUTOMATIC
        # enumeration (p.11-72, THKOFF): "It works by substituting with
        # *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK (OPTION = 2 if TBLCID
        # is not specified; OPTION = 5 if TBLCID is specified)." The criterion
        # is the same quadratic either way (p.11-73 Remark 2), so the mapping
        # holds with or without THKOFF and one classification table serves.
        option = 5 if tblcid else 2
    else:                                   # NODES — a FORCE criterion
        nflf, sflf = _g(0), _g(1)
        # Vol I R17 p.11-70 gives NEN and MES the DEFAULT 2 (the Card-4 table's
        # "Default" row reads "required required 2. 2."). A blank cell read as
        # 0.0 would make the reported criterion (|fn|/NFLF)^0 + (|fs|/SFLF)^0
        # identically 2 >= 1 — a criterion the deck does not contain. Applied
        # at parse time so every consumer sees the value LS-DYNA uses.
        nen = _g(2) or 2.0
        mes = _g(3) or 2.0

    extra = _tiebreak_card4_extra(family, option, damping, user)

    # ── the named drops that belong to the KEYWORD, not the OPTION ────────
    if mpp:
        state.warn(
            f"{tag}: the _MPP card (IGNORE/BCKT/LCBCKT/NS2TRK/"
            "INITITR/PARMAX/CPARM8) is read past but NOT converted — it tunes "
            "LS-DYNA's MPP decomposition, which has no OpenRadioss "
            "counterpart. Note PARMAX is hard-coded to 1.1 for every "
            "*CONTACT_TIEBREAK_* anyway (Vol I R17 p.11-20). The tiebreak "
            "itself is unaffected.")
    if user:
        state.warn(
            f"{tag}: the _USER flavour puts the failure law in the "
            f"LS-DYNA user subroutine utb{option if option in _TIEBREAK_USER_OPTIONS else '<OPTION>'}"
            " in dyn21cnt.f (Vol I R17 p.11-43) together with its "
            f"NHV={nhv} history variables, NHMAT={nhmat}/NHWLD={nhwld} and the "
            "UP1..UP16 parameters on Cards 4.2/4.3 "
            f"{'(OFFSET=%d) ' % user_offset if user_offset else ''}"
            "— all read past and DROPPED. That subroutine is not part of the "
            "deck, so NOTHING of the user failure law can be converted. Note "
            "Card 4.1 REPLACES the ordinary Card 4 (OPTION NHV CT2CN CN OFFSET "
            "NHMAT NHWLD), so this spelling states no NFLS/SFLS/PARAM at all. "
            "REMEDY: restate the law with a built-in OPTION (6 or 8 carry over "
            "completely — see the per-interface note below), or model the "
            "joint with a failing connector.")
    if mortar:
        state.warn(
            f"{tag}: the _MORTAR flavour is LS-DYNA's "
            "segment-to-segment mortar treatment (a different contact "
            "discretisation, not a different bond). OpenRadioss has no mortar "
            "interface, so the contact is converted with the ordinary "
            "node-to-segment discretisation; the CN normal-stiffness field, "
            "which is read only for the MORTAR option on OPTIONs 2/4/6/7/8 "
            "(Vol I R17 p.11-39), is dropped with it.")
    if damping:
        state.warn(
            f"{tag}: the _DAMPING flavour adds Card 4.1a "
            "(DMP_1/DMP_2/DMP_3, three damping constants for OPTION 9/11 "
            "only — Vol I R17 p.11-35). It is read past to keep the optional "
            "card stack aligned, and DROPPED: /INTER/TYPE2's rupture has no "
            "damping input at all (the tie is a kinematic constraint, not a "
            "spring, until it partially ruptures).")
    if beam_offset:
        state.warn(
            f"{tag}: the _BEAM_OFFSET flavour replaces the constraint "
            "formulation with beam-like springs between the tracked nodes and "
            "the reference segments, and those springs transfer MOMENTS as "
            "well as forces when Optional Card E's FTORQ is set (Vol I R17 "
            "p.11-16). Neither half converts: the interface keeps the "
            "penalty/self-contact route this spelling already takes, so the "
            "offset springs and any FTORQ moment transfer are DROPPED. Without "
            "this entry the whole keyword landed in skipped_keywords, i.e. no "
            "interface at all — a missing LOAD PATH rather than a missing "
            "option.")

    if (family == "AUTOMATIC" and option not in _TIEBREAK_OPTION_CLASS
            and option not in _TIEBREAK_USER_OPTIONS):
        state.warn(
            f"{tag}: Card 4 field 1 (OPTION) reads {option}, which is not one "
            "of the values Vol I R17 p.11-36..11-38 defines "
            "(-11, -9, -3..-1, 1..11, 13, 14, or 101..105 with _USER) — the "
            "card is required for this keyword (p.11-6), so a 0 usually means "
            "Card 4 is MISSING or a column is shifted. The contact is still "
            "converted as a tie (the pre-failure state of every tiebreak), but "
            "no failure criterion can be read from it. REMEDY: check the deck "
            "against the Card-4 layout OPTION NFLS SFLS PARAM ERATEN ERATES "
            "CT2CN CN.")

    # ── Cards 1-3, read once for EVERY route ─────────────────────────────
    # (The record is built before the two delegating exits so they can run the
    # Card-4 inventory too: a refusal that skips the dropped-field accounting
    # loses it on exactly the cards a reader most needs it.)
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid = to_int(f1[0]) if f1 else 0
    msid = to_int(f1[1]) if len(f1) > 1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    mstyp = to_int(f1[3]) if len(f1) > 3 else 0
    # Card2: fs fd dc vc vdc penchk bt dt — friction and birth/death act only
    # AFTER failure, and neither /INTER/TYPE2 nor its rupture block has a
    # column for them; FS/FD are kept only so the writer can name them.
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs = to_float(f2[0]) if f2 else 0.0
    fd = to_float(f2[1]) if len(f2) > 1 else 0.0
    # Card3: sfsa sfsb sast sbst sfsat sfsbt fsf vsf — a NEGATIVE SAST/SBST is
    # LS-DYNA's "absolute tie-criterion distance", the tied path's dsearch floor.
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sst = to_float(f3[2]) if len(f3) > 2 else 0.0
    mst = to_float(f3[3]) if len(f3) > 3 else 0.0

    rec = ContactTiebreak(inter_id, title, ssid, sstyp, msid, mstyp, family,
                          keyword=kw, only=only, one_way=one_way, option=option,
                          nfls=nfls, sfls=sfls, param=param, eraten=eraten,
                          erates=erates, ct2cn=ct2cn, cn=cn, tblcid=tblcid,
                          thkoff=thkoff, nflf=nflf, sflf=sflf, nen=nen, mes=mes,
                          fs=fs, fd=fd, sst=sst, mst=mst,
                          mortar=mortar, user=user, damping=damping, mpp=mpp)

    # ── OPTION 4: LS-DYNA itself does not tie tangentially ───────────────
    if family == "AUTOMATIC" and option == 4:
        state.warn(
            f"{tag}: OPTION 4 — "
            f"{_TIEBREAK_OPTION_CLASS[4][1]}. Because tangential SLIDING is "
            "permitted before failure, the LS-DYNA pre-failure state is NOT a "
            "tie, and /INTER/TYPE2 (which always inhibits tangential motion) "
            "would OVER-constrain it. The interface is therefore converted as "
            "the post-failure penalty contact and the NORMAL bond "
            f"(NFLS={nfls:g}) is DROPPED — the surfaces contact but carry no "
            "tension. REMEDY: if the normal bond is load-bearing, restate it "
            "as OPTION 6 (solids/thick shells) or 8 (offset shells) with "
            "PARAM = the crack-opening distance at full damage, which "
            "converts to a real /INTER/TYPE2 rupture tie.")
        _report_tiebreak_dropped_cells(state, rec)
        handle_contact_automatic_surface_to_surface(
            block, state, extra=extra, card1=offset, inter_id=inter_id)
        return

    # ── the self-tie spellings: /INTER/TYPE2 has no shape for a self-tie ──
    if self_tie:
        state.warn(
            f"{tag}: a SELF-tiebreak (one surface tied to itself — Vol I R17 "
            "p.11-9 names AUTOMATIC_SINGLE_SURFACE_TIEBREAK and "
            "AUTOMATIC_GENERAL_TIEBREAK as two of the three single-surface "
            "tied contacts). /INTER/TYPE2 has no shape for it: it takes a "
            "secondary /GRNOD and a SEPARATE main /SURF, and here the two "
            "would be the same node list. The rupture Spotflags cannot be used "
            "at all — chktyp2.F:82 tags a TYPE2's secondary nodes whenever "
            "Spotflag is outside {25,26,27,28} and :97-98 raises the hard "
            "ERROR 556 for every MAIN node carrying that tag, which for a "
            "self-tie is every node of the surface. The auto-penalty Spotflag "
            "27 would be accepted, but i2trivox.F90:234 only excludes the "
            "segment a node is a CORNER of, so each node would be tied to "
            "whatever neighbouring segment of its OWN surface lies within "
            "dsearch — welding the part to itself instead of reproducing "
            "LS-DYNA's 'nodes in contact stick'. The interface is therefore "
            "converted as the post-failure self-contact and the BOND is "
            "DROPPED. Note LS-DYNA restricts this spelling to OPTIONs 1-5 and "
            "to MPP only (Vol I R17 p.11-40 Remark 2). REMEDY: split the "
            "self-contact into two explicit surfaces and use "
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK, which does "
            "convert to a tie.")
        _report_tiebreak_dropped_cells(state, rec)
        handle_contact_automatic_single_surface(
            block, state, extra=extra, card1=offset, inter_id=inter_id)
        return

    # ── everything else: the pre-failure state is a TIE ──────────────────
    _warn_contact_box(state, kw, inter_id, f1)
    state.contacts_tiebreak.append(rec)


def _report_tiebreak_dropped_cells(state: ConversionState, rec) -> None:
    """Run the writer's Card-4 inventory for a record that never reaches it.

    The OPTION-4 and self-tie routes hand the block to a penalty-contact
    handler and RETURN, so their ``ContactTiebreak`` never enters
    ``state.contacts_tiebreak`` and the writer's per-record accounting never
    runs for them. Without this they lose the whole Card-4 inventory on exactly
    the two routes that drop the most: OPTION 4's ``SFLS`` is a real Coulomb
    cap when ``PARAM = 1`` (*"For OPTION = 4, SFLS is a frictional stress limit
    if PARAM = 1. This frictional stress limit is independent of the normal
    force at the tie"*, Vol I R17 p.11-38), and the self-tie routes drop the
    bond outright.
    """
    from .writer.contacts import _tiebreak_report_dropped_cells
    # spotflag=None on purpose: BOTH routes that reach this keep their
    # penalty-contact spelling and emit no /INTER/TYPE2 at all, so the
    # CT2CN/CN sentence must not talk about a tie's Stfac card.
    _tiebreak_report_dropped_cells(state, rec, ruptured=False, spotflag=None)


#: The LS-DYNA keyword bases dyna2rad routes to /INTER/TYPE25, and the
#: ``ContactType25.variant`` each maps to. ``eroding`` marks the families whose
#: mandatory Card 4 (ISYM/EROSOP/IADJ) shifts the optional-card stack.
_TYPE25_CONTACT_BASES = {
    "CONTACT_ERODING_SINGLE_SURFACE":       ("SINGLE_SURFACE", True),
    "CONTACT_ERODING_SURFACE_TO_SURFACE":   ("SURFACE_TO_SURFACE", True),
    "CONTACT_ERODING_NODES_TO_SURFACE":     ("NODES_TO_SURFACE", True),
    "CONTACT_NODES_TO_SURFACE":             ("NODES_TO_SURFACE", False),
    "CONTACT_AUTOMATIC_NODES_TO_SURFACE":   ("NODES_TO_SURFACE", False),
}


def handle_contact_type25(block: Block, state: ConversionState) -> None:
    """*CONTACT_ERODING_* and *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE →
    /INTER/TYPE25 (see :class:`~k2rad.state.ContactType25`).

    Card stack (LS-DYNA Vol I p.11-6, "cards must appear in the exact order
    listed"), with the ERODING Card 4 present only for the ERODING spellings::

        [MPP 1[, MPP 2]]                      _MPP option
        Card 1  ssid msid sstyp mstyp sboxid mboxid spr mpr
        Card 2  fs fd dc vc vdc penchk bt dt
        Card 3  sfs sfm sst mst sfst sfmt fsf vsf
        Card 4  isym erosop iadj                    ERODING only
        Card A  soft sofscl lcidab maxpar sbopt depth bsort frcfrq
        Card B  penmax thkopt shlthk snlog isym i2d3d sldthk sldstf
        Card C  igap ignore dprfac dtstif edgek <blank> flangl cid_rcf

    The ERODING Card 4 is what makes an eroding contact impossible to alias onto
    the existing automatic handlers: it pushes Card A and Card C down one line,
    so the SOFT and IGNORE reads would land on ISYM and Card B respectively.

    The dyna2rad SOFT sentinels (-7/-11/-19) are honoured for
    ERODING_SINGLE_SURFACE, exactly as ``convertcontacts.cxx:133-165`` does
    (that branch is gated on ``ERODING_SINGLE_SURFACE`` or ``AUTOMATIC_GENERAL``
    — ERODING_SURFACE_TO_SURFACE has no such escape). A sentinel-routed contact
    goes to the existing /INTER/TYPE7|11|19 path and LOSES the eroding
    re-exposure, which is warned about: only TYPE25 implements the dormant
    interior-segment mechanism (``check_surface_state.F:174`` is gated on
    ``ITY==25``).
    """
    base = block.keyword
    if base.endswith("_MPP"):
        base = base[:-4]
    variant, eroding = _TYPE25_CONTACT_BASES[base]

    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    if block.keyword.endswith("_MPP"):
        new_offset = _contact_mpp_card_offset(raw, offset, True)
        state.warn(
            f"*{block.keyword} {inter_id}: the _MPP option card(s) "
            f"({new_offset - offset} line(s): bucket-sort and MPP-decomposition "
            "tuning) are skipped — they carry no field OpenRadioss has an "
            "equivalent for. The contact itself converts normally.")
        offset = new_offset

    # Card 1: ssid msid sstyp mstyp sboxid mboxid spr mpr
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    msid  = to_int(f1[1]) if len(f1) > 1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    mstyp = to_int(f1[3]) if len(f1) > 3 else 0
    _warn_contact_box(state, block.keyword, inter_id, f1)
    # Card 2: fs fd dc vc vdc penchk bt dt
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs  = to_float(f2[0]) if f2 else 0.0
    fd  = to_float(f2[1]) if len(f2) > 1 else 0.0
    dc  = to_float(f2[2]) if len(f2) > 2 else 0.0
    vdc = to_float(f2[4]) if len(f2) > 4 else 0.0
    bt  = to_float(f2[6]) if len(f2) > 6 else 0.0
    dt  = to_float(f2[7]) if len(f2) > 7 else 1e28
    # Card 3: sfs sfm sst mst sfst sfmt fsf vsf
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    sfs = to_float(f3[0]) if f3 else 0.0
    sfm = to_float(f3[1]) if len(f3) > 1 else 0.0
    sst = to_float(f3[2]) if len(f3) > 2 else 0.0
    mst = to_float(f3[3]) if len(f3) > 3 else 0.0
    fsf = to_float(f3[6]) if len(f3) > 6 else 0.0
    fsf = fsf if fsf != 0.0 else 1.0        # LS-DYNA blank/0 → 1.0
    # Card 4 (ERODING only): isym erosop iadj
    isym = erosop = iadj = 0
    if eroding:
        f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
        isym   = to_int(f4[0]) if f4 else 0
        erosop = to_int(f4[1]) if len(f4) > 1 else 1
        iadj   = to_int(f4[2]) if len(f4) > 2 else 0
    extra = 1 if eroding else 0
    soft = _read_contact_soft(raw, offset, extra=extra)
    ignore = _read_contact_ignore(raw, offset, extra=extra)

    # dyna2rad's SOFT escape hatch, ERODING_SINGLE_SURFACE only (cc:133-165).
    if variant == "SINGLE_SURFACE" and soft in (-7, -11, -19):
        target = {-7: "TYPE7", -11: "TYPE11", -19: "TYPE19"}[soft]
        state.warn(
            f"*{block.keyword} {inter_id}: optional-Card-A SOFT={soft} is the "
            f"dyna2rad sentinel that forces /INTER/{target} instead of the "
            "default /INTER/TYPE25 (convertcontacts.cxx:133-165). Honoured — "
            "but the EROSION half of this contact is then LOST: only "
            "/INTER/TYPE25 keeps interior solid faces as dormant "
            "negative-stiffness segments, and only TYPE25 wakes them "
            "(engine check_surface_state.F:174 is gated on ITY==25). Segments "
            "whose element dies are still removed, but no NEW surface is ever "
            "exposed, so the contact goes under-stiff as the crater grows. "
            "Remove the SOFT sentinel to keep the eroding behaviour.")
        if msid == 0:
            msid, mstyp = ssid, sstyp
        state.contacts_general.append(
            ContactAutoGeneral(inter_id, title, ssid, sstyp, msid, mstyp, soft,
                               fs, fd, bt, dt, ignore, vdc=vdc, sst=sst,
                               mst=mst, sfs=sfs))
        return

    state.contacts_type25.append(
        ContactType25(inter_id, title, ssid, sstyp, msid, mstyp, variant,
                      eroding=eroding, fs=fs, fd=fd, dc=dc, bt=bt, dt=dt,
                      vdc=vdc, sfs=sfs, sfm=sfm, sst=sst, mst=mst, fsf=fsf,
                      isym=isym, erosop=erosop, iadj=iadj, soft=soft,
                      ignore=ignore, keyword=block.keyword))


def handle_define_friction(block: Block, state: ConversionState) -> None:
    """*DEFINE_FRICTION → /FRICTION (id preserved; see
    :class:`~k2rad.state.DefineFriction`).

    Card 1: ``ID FS_D FD_D DC_D VC_D [ICNEP]`` — the default coefficients, which
    become the /FRICTION header row (the fallback for every part pair not
    listed).

    Card 2 (repeated to the end of the block): ``PIDi PIDj FSij FDij DCij VCij
    PTYPEi PTYPEj`` — one part pair each. ``PTYPEi/j`` is the literal string
    ``PSET`` when the id names a *SET_PART; blank means a part id. Rows are kept
    in deck order, un-expanded and un-deduplicated, exactly as dyna2rad does
    (``convertfrictions.cxx:107-184``).
    """
    toff = _title_offset(block)
    raw = block.raw[toff:]
    if not raw:
        return
    f1 = _card(raw, 0, fixed=True, n=6, w=10)
    fric_id = to_int(f1[0]) if f1 else 0
    if fric_id <= 0:
        state.warn(
            "*DEFINE_FRICTION with no (or a non-positive) ID on Card 1 — the "
            "table cannot be referenced by a *CONTACT FS=-2 and is DROPPED. "
            "Give the friction definition a positive ID.")
        state.note_recognized_not_emitted(
            "DEFINE_FRICTION",
            "a friction table had no usable ID on Card 1, so no /FRICTION was "
            "written; contacts that meant to use it fall back to their own "
            "FS/FD.")
        return
    fric = DefineFriction(
        fric_id=fric_id,
        title=_read_title(block, f"FRICTION_{fric_id}"),
        fs=to_float(f1[1]) if len(f1) > 1 else 0.0,
        fd=to_float(f1[2]) if len(f1) > 2 else 0.0,
        dc=to_float(f1[3]) if len(f1) > 3 else 0.0,
        vc=to_float(f1[4]) if len(f1) > 4 else 0.0,
        icnep=to_int(f1[5]) if len(f1) > 5 else 0,
    )
    for ln in raw[1:]:
        if not ln.strip():
            continue
        f = _card([ln], 0, fixed=True, n=8, w=10)
        pid_i = to_int(f[0]) if f else 0
        pid_j = to_int(f[1]) if len(f) > 1 else 0
        if pid_i <= 0 or pid_j <= 0:
            # Do NOT drop this silently: a fixed-format row written one column
            # short, or one whose second id field was left blank, otherwise
            # loses that part pair without a word and it falls back to the
            # table's default coefficients. The two other drop paths (part /
            # *SET_PART does not exist, writer/frictions.py) both warn.
            state.warn(
                f"*DEFINE_FRICTION {fric_id}: a part-pair row has a blank or "
                f"non-positive part id (PID_i={pid_i}, PID_j={pid_j}) and is "
                f"DROPPED — that pair falls back to the table's default "
                f"FS/FD/DC. Row as read: {ln.rstrip()!r}. Check the row's "
                "column alignment (both ids are 10-wide fields) if this pair "
                "was meant to have its own coefficients.")
            continue
        fric.pairs.append(FrictionPair(
            pid_i=pid_i, pid_j=pid_j,
            fs=to_float(f[2]) if len(f) > 2 else 0.0,
            fd=to_float(f[3]) if len(f) > 3 else 0.0,
            dc=to_float(f[4]) if len(f) > 4 else 0.0,
            vc=to_float(f[5]) if len(f) > 5 else 0.0,
            pset_i=(f[6].strip().upper() == "PSET") if len(f) > 6 else False,
            pset_j=(f[7].strip().upper() == "PSET") if len(f) > 7 else False,
        ))
    if fric_id in state.define_frictions:
        state.warn(
            f"*DEFINE_FRICTION {fric_id} is defined more than once — the LAST "
            "definition wins (/FRICTION ids are unique). Renumber one of them "
            "if both tables are meant to be used.")
    state.define_frictions[fric_id] = fric


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
    # Card2: fs fd dc vc vdc penchk bt dt — only FS is kept (see ContactTied.fs)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    fs_tied = to_float(f2[0]) if f2 else 0.0
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
                    sfs=sfs, sfm=sfm, sfst=sfst, sfmt=sfmt, fs=fs_tied)
    )


#: *CONTACT_SPOTWELD keyword flavour → what the LS-DYNA option does that
#: /INTER/TYPE2 cannot, said plainly. dyna2rad parses the same flag into
#: ``ContactOption`` (contact_spotweld.cfg:842-852) and then never reads it, so
#: all five spellings convert byte-identically there — silently. These are the
#: texts that make the loss visible instead.
_SPOTWELD_VARIANT_LOSS = {
    "WITH_TORSION": (
        "the _WITH_TORSION flavour makes the LS-DYNA tie transmit TORSION about "
        "the weld axis with its own failure moment; /INTER/TYPE2 has no "
        "torsional-release field, so the tie carries the full moment and the "
        "torsional failure is NOT modelled by the interface"),
    "BEAM_OFFSET": (
        "the _BEAM_OFFSET flavour keeps the weld beam PHYSICALLY offset from the "
        "sheet mid-surface and ties it with a penalty beam; /INTER/TYPE2 "
        "projects the secondary node onto its main segment instead, so the "
        "offset lever arm is not preserved"),
    "CONSTRAINED_OFFSET": (
        "the _CONSTRAINED_OFFSET flavour keeps the weld offset with a "
        "CONSTRAINT equation rather than a penalty; /INTER/TYPE2 projects the "
        "secondary node onto its main segment, so the offset lever arm is not "
        "preserved"),
}


def _contact_mpp_card_offset(raw: List[str], offset: int, mpp: bool) -> int:
    """First index of a *CONTACT's mandatory Card 1, past any ``_MPP`` cards.

    ``_MPP`` inserts its own card BEFORE Card 1 (IGNORE BCKT LCBCKT NS2TRK
    INITITR PARMAX <blank> CPARM8), optionally followed by a second MPP card
    recognised by a literal ``&`` in COLUMN 1 (``CARD_PREREAD("%-1s")``). Miss
    either and every field of the real card is read one line too early — SSID
    would come back as the MPP IGNORE flag.

    The rule is identical in every *CONTACT CFG that offers the option —
    ``contact_spotweld.cfg`` and ``contact_option_nodes_to_surface.cfg:2414-2434``
    carry the same two-card block verbatim — so the spotweld and eroding /
    node-to-surface handlers share this one implementation rather than each
    guessing at the card count.
    """
    if not mpp:
        return offset
    idx = offset + 1
    if idx < len(raw) and raw[idx][:1] == "&":
        idx += 1
    return idx


def handle_contact_spotweld(block: Block, state: ConversionState) -> None:
    """*CONTACT_SPOTWELD[_WITH_TORSION|_BEAM_OFFSET|_CONSTRAINED_OFFSET]
    [_PENALTY][_MPP][_ID] → /INTER/TYPE2 (Spotflag=28, Ignore=2, Idel2=1).

    Card1: ssid msid sstyp mstyp sboxid mboxid spr mpr — SSID names the WELD
           side (commonly SSTYP=3, the MAT_100 beam part), MSID the sheets
           being joined (commonly MSTYP=2, a *SET_PART_LIST).
    Card2: fs fd dc vc vdc penchk bt dt — friction and birth/death are
           meaningless on a tie and have no /INTER/TYPE2 field; dropped exactly
           as dyna2rad drops them (they are not even read on its TYPE2 path,
           convertcontacts.cxx:319 ``continue`` precedes the read at :321).
    Card3: sfs sfm sst mst sfst sfmt fsf vsf — SST/MST are the only Card-3
           fields with a TYPE2 home: they size the tie search distance
           (see _spotweld_dsearch in the writer).
    """
    kw = block.keyword
    variant = ""
    for flavour in ("WITH_TORSION", "BEAM_OFFSET", "CONSTRAINED_OFFSET"):
        if flavour in kw:
            variant = flavour
            break
    penalty = kw.endswith("_PENALTY") or "_PENALTY_" in kw
    mpp = kw.endswith("_MPP") or "_MPP_" in kw

    inter_id, title, offset = _parse_contact_header(block)
    if inter_id <= 0 or inter_id > 90000:
        inter_id = state.next_id()
    raw = block.raw
    c1 = _contact_mpp_card_offset(raw, offset, mpp)
    f1 = _card(raw, c1, fixed=True, n=8, w=10)
    ssid  = to_int(f1[0]) if f1 else 0
    msid  = to_int(f1[1]) if len(f1) > 1 else 0
    sstyp = to_int(f1[2]) if len(f1) > 2 else 0
    mstyp = to_int(f1[3]) if len(f1) > 3 else 0
    _warn_contact_box(state, kw, inter_id, f1)
    # Card3: sfs sfm sst mst sfst sfmt fsf vsf
    f3 = _card(raw, c1 + 2, fixed=True, n=8, w=10)
    sst = to_float(f3[2]) if len(f3) > 2 else 0.0
    mst = to_float(f3[3]) if len(f3) > 3 else 0.0

    if variant:
        state.warn(
            f"*CONTACT_SPOTWELD_{variant} {inter_id} -> /INTER/TYPE2 with the "
            f"PLAIN spotweld tie: {_SPOTWELD_VARIANT_LOSS[variant]}. dyna2rad "
            "converts all five *CONTACT_SPOTWELD spellings to the same card "
            "and reports nothing (contact_spotweld.cfg parses ContactOption "
            "2/3/4 and dyna2rad never reads it). REMEDY: if the dropped "
            "behaviour is load-bearing, model the weld explicitly with a "
            "/PROP/TYPE13 spring (its Ifail2 failure surface does carry "
            "torsion) instead of relying on the tie.")
    if mpp:
        state.warn(
            f"*CONTACT_SPOTWELD {inter_id}: the _MPP card (BCKT/LCBCKT/NS2TRK/"
            "INITITR/PARMAX/CPARM8 bucket-sort and tracking controls) is read "
            "past but NOT converted — it tunes LS-DYNA's MPP decomposition, "
            "which has no OpenRadioss counterpart (the starter builds its own "
            "domain decomposition). The tie itself is unaffected.")
    state.contacts_spotweld.append(
        ContactSpotweld(inter_id, title, ssid, sstyp, msid, mstyp, variant,
                        penalty=penalty, mpp=mpp, sst=sst, mst=mst)
    )


def handle_define_hex_spotweld_assembly(block: Block, state: ConversionState) -> None:
    """*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N][_TITLE] → /CLUSTER/BRICK.

    Card 1: ID_SW (the weld id, on its OWN card — not on the keyword line).
    Card 2: EID1..EID8, 10-char fields.
    Card 3: EID9..EID16 — read only when the ``_N`` suffix says N > 8.

    The ``_N`` suffix is the TOTAL number of solid elements in the assembly
    (LS-DYNA Vol I R16 p.17-300), 1..16, not a card count; the bare keyword
    free-reads the list. ``_TITLE`` is an Altair CFG extension (the LSTC manual
    documents only <BLANK> and N) — parsed if present, never emitted.
    """
    raw = block.raw
    if not raw:
        return
    idx = 0
    title = ""
    if _has_title(block) or _has_id(block):
        title = raw[0].strip()
        idx = 1
    if idx >= len(raw):
        return
    id_card = _card(raw, idx, fixed=True, n=1, w=10)
    sw_id = to_int(id_card[0]) if id_card else 0
    # The _N suffix caps the list; without it every remaining card is read.
    suffix = block.keyword[len("DEFINE_HEX_SPOTWELD_ASSEMBLY"):].lstrip("_")
    declared = int(suffix) if suffix.isdigit() else 0
    eids: List[int] = []
    for i in range(idx + 1, len(raw)):
        # _card, not a bare parse_fixed: a comma/free-format element card
        # written narrower than 10 columns ("101,102,103") slices to
        # ['101,102,10', '3', ...], so to_int silently drops 101/102/103 and
        # ADDS element 3 to the weld cluster. _card detects that and re-splits.
        # (The ID_SW card above already goes through it.)
        for tok in _card(raw, i, fixed=True, n=8, w=10):
            v = to_int(tok)
            if v > 0:
                eids.append(v)
        if declared and len(eids) >= declared:
            break
    if declared:
        if len(eids) > declared:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY_{declared} id={sw_id}: the "
                f"cards carry {len(eids)} element ids but the _N suffix "
                f"declares {declared} — only the first {declared} are used "
                "(LS-DYNA reads exactly N).")
            eids = eids[:declared]
        elif len(eids) < declared:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY_{declared} id={sw_id}: the _N "
                f"suffix declares {declared} element(s) but only {len(eids)} "
                "id(s) are on the cards — the weld cluster is built from the "
                "ids that are actually there.")
    if len(eids) > 16:
        state.warn(
            f"*DEFINE_HEX_SPOTWELD_ASSEMBLY id={sw_id}: {len(eids)} element "
            "ids were read, but LS-DYNA caps an assembly at 16 hexes "
            "(definehexspotweld.cfg CHECK idsmax < 17). All of them are kept "
            "in the /CLUSTER (its own limit is 500) — check the deck if that "
            "is not what you meant.")
    if not eids:
        state.warn(
            f"*DEFINE_HEX_SPOTWELD_ASSEMBLY id={sw_id}: no solid element ids "
            "on the card — no /CLUSTER/BRICK is emitted for this weld, and "
            "the hexes it names (if any) behave as ordinary solids with no "
            "weld failure.")
        return
    state.hex_spotweld_assemblies.append(HexSpotweldAssembly(sw_id, title, eids))


def handle_database_swforc(block: Block, state: ConversionState) -> None:
    """*DATABASE_SWFORC → /TH/SPRING (MAT_100 beam welds) + /TH/BRIC (MAT_100
    solid welds) + /TH/CLUSTER (*DEFINE_HEX_SPOTWELD_ASSEMBLY welds).

    LS-DYNA's swforc is the spot-weld force database. dyna2rad splits the same
    request in two (dyna2rad.cxx:613-695: ``SWFORC`` appears TWICE in
    ``dbCardList``, i=3 filtering *ELEMENT_DISCRETE/*ELEMENT_BEAM on a MAT_100
    part to /TH/SPRING, i=4 filtering *ELEMENT_SOLID to /TH/BRIC); the
    /TH/CLUSTER half comes from the hex-assembly converter
    (convertdefinehexspotweldassembly.cxx:315). k2rad emits all three.
    """
    state.db_swforc_dt = _handle_db_dt(block, state, "*DATABASE_SWFORC")


def handle_database_bndout(block: Block, state: ConversionState) -> None:
    """*DATABASE_BNDOUT ("Boundary condition forces and energy") → /TH/NODE
    REAC* over every node an /IMPDISP, /IMPVEL or /IMPACC drives.

    dyna2rad names exactly those three converted cards as the node source
    (``dyna2rad.cxx:456`` ``{"/IMPDISP","/IMPVEL","/IMPACC"}``, with the
    ``Gnod_id`` vs ``grnod_ID`` attribute switch at :466), collects their node
    groups, sorts and uniques them, and writes ONE group named
    ``TH_NODE_BNDOUT`` with the six REAC* variables and no ``DEF``. k2rad
    builds the node scope from what its two imposed-motion writers ACTUALLY
    emitted (``state.imp_motion_nodes``) rather than from the parsed cards, so
    a row that was warned-and-dropped contributes no node — a /TH/NODE naming
    an undefined node is starter ERROR 78, not a lost channel.
    """
    state.db_bndout_seen = True
    state.db_bndout_dt = _handle_db_dt(block, state, "*DATABASE_BNDOUT")


def handle_database_rbdout(block: Block, state: ConversionState) -> None:
    """*DATABASE_RBDOUT ("Motion of rigid bodies") → /TH/RBODY over EVERY
    emitted /RBODY.

    A presence-only trigger: the card carries no id list, and dyna2rad answers
    it by collecting every ``/RBODY`` in the converted model
    (``convertrigids.cxx:766-772`` — ``selDatabaseRbdout.Count()``, then a full
    ``SelectionRead(p_radiossModel, "/RBODY")`` walk), the same "collect every
    converted entity" shape /TH/RWALL, /TH/SECTIO and /TH/INTER use. k2rad
    lists ``state.rbody_ids``, which all THREE Radioss-side /RBODY emission
    sites register into at the line that writes the card (writer/rbody.py:645,
    :1004, :1086 — four LS-DYNA sources, since *MAT_RIGID parts, *PART_INERTIA,
    element-free CoG masters and *CONSTRAINED_RIGID_BODIES merge masters all
    come out of the first one).
    """
    state.db_rbdout_seen = True
    state.db_rbdout_dt = _handle_db_dt(block, state, "*DATABASE_RBDOUT")


def handle_database_nodfor(block: Block, state: ConversionState) -> None:
    """*DATABASE_NODFOR — the nodal-force-group ASCII database.

    It selects nothing on its own: "The output interval must be specified using
    *DATABASE_NODFOR" is what *DATABASE_NODAL_FORCE_GROUP says about it (Vol I
    R16 p.16-121), so its DT is the frequency of the /TH/NODE groups that card
    builds. Same treatment as *DATABASE_SPHOUT: the dt joins the /TFILE
    minimum, the channels come from the other keyword. dyna2rad likewise has
    ``*DATABASE_NODFOR`` only in its ``dbCardList`` (convertcards.cxx:89).

    Whether the deck ALSO carries a group card cannot be decided here: the two
    keywords may appear in either order (every r14 deck writes the frequency
    block first), so the "interval only, no channel" note is raised by the
    writer once the whole deck has been read.
    """
    state.db_nodfor_dt = _handle_db_dt(block, state, "*DATABASE_NODFOR")


def handle_database_tprint(block: Block, state: ConversionState) -> None:
    """*DATABASE_TPRINT — the THERMAL ASCII database. Recognized, not emitted.

    dyna2rad answers it by switching on ``/ANIM/NODA TEMP`` + ``/ANIM/ELEM
    TEMP`` and appending the ``TEMP`` variable to every existing /TH/NODE and
    /TH/BRIC group (dyna2rad.cxx:497-551), with no check that a thermal
    solution was ever requested. k2rad deliberately does NOT copy that, and the
    reason is specific to this converter rather than a matter of taste:

      * Whether the CONVERTED deck has a thermal solve at all is not known at
        parse time — it depends on whether some material ends up with a
        /HEAT/MAT (the only thing that arms MAT_PARAM%ITHERM,
        hm_read_therm.F:253) and whether a temperature driver was converted.
        The answer is therefore given by writer/thermal.py::_note_tprint,
        which runs after that is decided, and the channels are emitted
        exactly when both halves exist.
      * What it would carry instead was measured on a 576-brick deck: with
        /MAT/ELAST the Nodal_Temperature and 3DELEM_Temperature fields come out
        ALL ZERO; with /MAT/PLAS_JOHNS (which allocates ``GBUF%TEMP`` but never
        integrates it) they come out a constant 300. The scalar is ALWAYS
        created in the A-file (``genani.F:1905``, ``:4547``) — it is never
        omitted — so the result is a flat fringe that looks like data.
      * The starter says the same thing on the /TH side and nowhere else:
        ``WARNING 1087 OUTPUT TEMP WHILE TEMPERATURE IS NOT COMPUTED (NO
        HEAT/MAT)`` fires for ``ITHBUF==19 .AND. ITHERM_FE==0``
        (hm_read_thgrne.F:228-236). There is NO equivalent warning on the ANIM
        side, so an emitted /ANIM/*/TEMP is silently uninformative.
      * Its dt stays OUT of the /TFILE minimum for the documented membership
        rule (writer/assembly.py): a card with no /TH consumer would only
        thicken the T01 for channels that are not in it.
    """
    state.db_tprint_dt = _handle_db_dt(block, state, "*DATABASE_TPRINT")


def handle_control_parallel(block: Block, state: ConversionState) -> None:
    """*CONTROL_PARALLEL → engine /PARITH (only when the card is present).

    Card 1 (control_parallel.cfg:74-75, Vol I R16 p.12-448):
    ``NCPU NUMRHS CONST PARA``, all %10d.

    CONST is the consistency flag: "EQ.1 or n < 0: On (recommended). EQ.2 or
    n > 0: Off, for a faster solution (default)." CONST=1 requires "that all
    contributions to global vectors be summed in a precise order independently
    of the number of processors used", which is exactly what OpenRadioss's
    /PARITH/ON does (the skyline FSKY array with fixed per-node slots gathered
    in a deterministic walk, engine/source/assembly/asspar4.F). Measured on a
    576-brick LAW2 model: with /PARITH/ON the T01 is BITWISE identical between
    nt=1 and nt=4; with /PARITH/OFF row 183's kinetic energy differs in the
    7th digit.

    NCPU, NUMRHS and PARA have no Radioss counterpart — NCPU is an SMP thread
    count, which OpenRadioss takes as the runtime ``-nt`` argument rather than
    a deck card (and LS-DYNA itself disabled the field in 971 R5), while
    NUMRHS and PARA are storage/assembly details of LS-DYNA's own SMP force
    accumulation with no /PARITH sub-option. Reported as dropped by the writer.
    """
    f = _card(block.raw, _title_offset(block), fixed=True, n=4, w=10)
    state.ctrl_parallels.append(ControlParallel(
        ncpu=to_int(f[0]) if len(f) > 0 else 0,
        numrhs=to_int(f[1]) if len(f) > 1 else 0,
        const=to_int(f[2]) if len(f) > 2 else 0,
        para=to_int(f[3]) if len(f) > 3 else 0))


def handle_database_nodal_force_group(block: Block,
                                      state: ConversionState) -> None:
    """*DATABASE_NODAL_FORCE_GROUP[_TITLE] → one /TH/NODE per card.

    Card 1 (NodalForceGrp.cfg:110-116, Vol I R16 p.16-121): an optional 80-char
    TITLE line for the ``_TITLE`` spelling, then ``NSID CID`` as ``%10d%10d``.
    NSID is restricted to the *SET_NODE id pool; CID is a *DEFINE_COORDINATE
    "for output of data in local system".

    ``NSID == 0`` drops the whole card — dyna2rad does the same silently
    (convertcards.cxx:1017 ``if (NSID)``); here it is warned, because a card
    that asks for output and produces none should not be invisible.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f = _card(block.raw, offset, fixed=True, n=2, w=10)
    nsid = to_int(f[0]) if f else 0
    cid = to_int(f[1]) if len(f) > 1 else 0
    if nsid <= 0:
        state.warn(
            "*DATABASE_NODAL_FORCE_GROUP: NSID is blank or 0, so the card "
            "names no node set and NO /TH/NODE group is written. LS-DYNA "
            "needs a *SET_NODE here (Vol I R16 p.16-121); dyna2rad drops such "
            "a card silently.")
        return
    state.db_nodal_force_groups.append(DbNodalForceGroup(nsid, cid, title))


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


def handle_boundary_prescribed_motion_set_box(block: Block,
                                              state: ConversionState) -> None:
    """*BOUNDARY_PRESCRIBED_MOTION_SET_BOX — the _SET card plus one extra card
    ``BOXID TOFFSET LCBCHK``, restricting the motion to the node-set members
    that lie inside a *DEFINE_BOX.

    The membership is the INTERSECTION ``nodes(NSID) AND nodes-inside(BOXID)``,
    which is what the Radioss dyna-reader builds too (a /SET/GENERAL with a
    ``SET`` clause and a ``SET_I`` clause, ``convertbcs.cxx:493-520``); with
    NSID = 0 the box alone is the group (``:522-535``), and with BOXID = 0 the
    card degenerates to a plain _SET (``:476-479``).

    ``LCBCHK`` is R7.1+ (``boundary_prescribed_motion_set.cfg:319-324``); the
    R6.1 form of the card has only ``BOXID TOFFSET``, so a two-field card parses
    identically.
    """
    _handle_boundary_prescribed_motion(block, state, is_node=False, is_box=True)


def handle_boundary_prescribed_motion_node(block: Block, state: ConversionState) -> None:
    """*BOUNDARY_PRESCRIBED_MOTION_NODE — same card as _SET with a node id in
    field 1; wrapped in an auto-created single-node set and sent down the _SET
    path (→ /IMPDISP//IMPVEL//IMPACC, or /BCS when SF=0)."""
    _handle_boundary_prescribed_motion(block, state, is_node=True)


def _handle_boundary_prescribed_motion(block: Block, state: ConversionState,
                                       is_node: bool,
                                       is_box: bool = False) -> None:
    keyword = block.keyword
    for f, boxf in _bpm_walk(block, is_box=is_box):
        if len(f) < 4:
            continue
        nsid  = to_int(f[0])
        dof   = to_int(f[1])
        vad   = to_int(f[2])
        lcid  = to_int(f[3])
        sf    = _ffield(f, 4, 1.0)
        vid   = to_int(f[5]) if len(f) > 5 else 0
        death = _ffield(f, 6, 1e28)
        birth = to_float(f[7]) if len(f) > 7 else 0.0
        boxid   = to_int(boxf[0]) if boxf else 0
        toffset = to_int(boxf[1]) if len(boxf) > 1 else 0
        lcbchk  = to_int(boxf[2]) if len(boxf) > 2 else 0
        ref = f"nid={nsid}" if is_node else f"nsid={nsid}"
        if not _pm_vad_supported(state, keyword, ref, vad):
            continue
        if is_box and not boxid:
            state.warn(
                f"*{keyword} nsid={nsid}: the _BOX card carries no BOXID — the "
                "motion is applied to the WHOLE node set (which is what the "
                "Radioss dyna-reader does too, convertbcs.cxx:476-479).")
        # NSID = 0 with a BOXID is legal: the box alone is the group. It is left
        # at 0 here and resolved to "every node inside the box" by the writer
        # (the same shape convertbcs.cxx:522-535 emits).
        if is_node:
            nid = nsid
            nsid = state.next_id()
            state.node_sets[nsid] = (f"PM_node_{nid}", [nid])
        state.prescribed_motion_sets.append(
            PrescribedMotionSet(nsid, dof, vad, lcid, sf, death, birth,
                                vid=vid, boxid=boxid, toffset=toffset,
                                lcbchk=lcbchk)
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


def handle_control_sph(block: Block, state: ConversionState) -> None:
    """*CONTROL_SPH — one to three cards, only NMNEIGH of which has a home.

    Card 1  ``NCBS BOXID DT IDIM NMNEIGH FORM START MAXV``
    Card 2  ``CONT DERIV INI ISHOW IEROD ICONT IAVIS ISYMP``   (optional)
    Card 3  ``ITHK ISTAB QL - SPHSORT ISHIFT``                 (optional)

    Cards 2 and 3 are claimed by RAW CONTIGUITY (the #119 rule): card 2 is the
    line IMMEDIATELY after card 1 whether or not it is blank, and an all-blank
    one IS a card ("every field defaults"). Skipping blanks and taking "the next
    non-blank line" would read a following keyword's data as card 2 the moment
    the deck writes an empty optional card — the corpus spans all three lengths
    (hvi.k writes 1 card, W11 writes 2, model5.k writes 3).

    The column-by-column fates are reported by ``writer/sph.py``, which is where
    the one mapping that exists (``NMNEIGH`` → /SPHGLO) is decided. dyna2rad
    drops the whole keyword without a message.
    """
    off = _title_offset(block)
    raw = [ln for ln in block.raw]
    while raw and not raw[-1].strip():
        raw.pop()
    if len(raw) <= off:
        state.warn("*CONTROL_SPH: no data card found — skipped.")
        return
    f1 = _card(raw, off, fixed=True, n=8, w=10)
    c = ControlSph(
        ncbs=to_int(f1[0]) if f1 else 0,
        boxid=to_int(f1[1]) if len(f1) > 1 else 0,
        dt=_ffield(f1, 2, 1.0e20),
        idim=to_int(f1[3]) if len(f1) > 3 and f1[3].strip() else 3,
        nmneigh=to_int(f1[4]) if len(f1) > 4 else 0,
        form=to_int(f1[5]) if len(f1) > 5 else 0,
        start=to_float(f1[6]) if len(f1) > 6 else 0.0,
        maxv=to_float(f1[7]) if len(f1) > 7 else 0.0,
        n_cards=min(3, len(raw) - off))
    if c.n_cards >= 2:
        f2 = _card(raw, off + 1, fixed=True, n=8, w=10)
        c.cont = to_int(f2[0]) if f2 else 0
        c.deriv = to_int(f2[1]) if len(f2) > 1 else 0
        c.ini = to_int(f2[2]) if len(f2) > 2 else 0
        c.ishow = to_int(f2[3]) if len(f2) > 3 else 0
        c.ierod = to_int(f2[4]) if len(f2) > 4 else 0
        c.icont = to_int(f2[5]) if len(f2) > 5 else 0
        c.iavis = to_int(f2[6]) if len(f2) > 6 else 0
        c.isymp = to_int(f2[7]) if len(f2) > 7 else 0
    if c.n_cards >= 3:
        f3 = _card(raw, off + 2, fixed=True, n=8, w=10)
        c.ithk = to_int(f3[0]) if f3 else 0
        c.istab = to_int(f3[1]) if len(f3) > 1 else 0
        c.ql = to_float(f3[2]) if len(f3) > 2 else 0.0
        c.sphsort = to_int(f3[4]) if len(f3) > 4 else 0
        c.ishift = to_int(f3[5]) if len(f3) > 5 else 0
    if len(raw) - off > 3:
        state.warn(
            "*CONTROL_SPH: the keyword defines at most THREE cards (Vol I R16), "
            f"so the {len(raw) - off - 3} line(s) after card 3 are UNREAD. "
            "Split them into their own keyword block if they were meant as "
            "data.")
    state.control_sph = c


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
    """*DATABASE_ABSTAT -> /TH/MONV over every converted /MONVOL.

    "Airbag statistics. See *AIRBAG_OPTION" (Vol I R16 p.16-7); its
    components are volume, internal energy and pressure (p.16-13). Until
    the airbag batch this card contributed nothing but a parsed DT that
    was then deliberately left OUT of the /TFILE minimum, because it had
    no /TH consumer at all. It has one now, so both halves are live —
    see writer/output.py::_make_starter_th_monv and the /TFILE chain in
    writer/assembly.py, which gates the dt on state.monvol_ids.
    """
    state.db_abstat_seen = True
    state.db_abstat_dt = _handle_db_dt(block, state, "*DATABASE_ABSTAT")


def handle_database_sphout(block: Block, state: ConversionState) -> None:
    """*DATABASE_SPHOUT — the SPH particle ASCII database.

    Radioss has no ``sphout`` file; the particle channels come out of the
    /TH/SPHCEL groups *DATABASE_HISTORY_SPH builds. What this card contributes
    is its DT, which joins the /TFILE minimum scan so those channels are sampled
    at the frequency the deck asked for (dyna2rad does exactly the same — the
    keyword appears only in its ``dbCardList``, never in a TH converter).
    """
    state.db_sphout_dt = _handle_db_dt(block, state, "*DATABASE_SPHOUT")
    state.note_recognized_not_emitted(
        "DATABASE_SPHOUT",
        "OpenRadioss has no 'sphout' database — the per-particle channels come "
        "from the /TH/SPHCEL groups *DATABASE_HISTORY_SPH builds instead. The "
        "dt IS honoured, as one term of the /TFILE minimum, so the particle "
        "channels a deck also requests with *DATABASE_HISTORY_SPH are sampled "
        "as often as this card asked for.")


def handle_database_binary_d3thdt(block: Block, state: ConversionState) -> None:
    state.db_d3thdt_dt = _handle_db_dt(block, state, "*DATABASE_BINARY_D3THDT")


def handle_database_binary_intfor(block: Block, state: ConversionState) -> None:
    state.db_intfor_dt = _handle_db_dt(block, state, "*DATABASE_BINARY_INTFOR")


def handle_database_deforc(block: Block, state: ConversionState) -> None:
    state.db_deforc_dt = _handle_db_dt(block, state, "*DATABASE_DEFORC")


def handle_database_disbout(block: Block, state: ConversionState) -> None:
    """*DATABASE_DISBOUT: "Discrete beam element, type 6, relative
    displacements, rotations, and forces" (Vol I R16 p.1945) — the sibling of
    DEFORC, which covers *ELEMENT_DISCRETE only. k2rad turns both families into
    /SPRING elements, so both land in a /TH/SPRING; keeping the two cards apart
    keeps each T01 channel attributed to the database LS-DYNA attributes it to.
    """
    state.db_disbout_dt = _handle_db_dt(block, state, "*DATABASE_DISBOUT")


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


# ── *INITIAL_STRESS_SHELL / *INITIAL_STRESS_SOLID ───────────────────────────
#
# ONE record walker per keyword, shared by the handler and by the
# *INCLUDE_TRANSFORM offsetter (assembly._off_initial_stress_shell /
# _off_initial_stress_solid), exactly as initial_strain_shell_records already
# is. The two walks MUST agree on which raw row is a card 1, because these
# cards are almost entirely floats and ``_rewrite_line`` decides "this token is
# an id" with ``to_int(tok) > 0``: a desynced offsetter would read a stress of
# 1.5 as the element id 1 and rewrite it to ``1 + IDEOFF`` (#116 / #119).
#
# Neither walker applies ``_title_offset``: Vol I R17 p.28-95 / p.28-103 give
# these keywords the options ``<BLANK>`` and ``SET`` only — no ``_TITLE``, no
# ``_ID`` — so the handlers walk ``block.raw`` from row 0 and the offsetters
# must start on the same row.

def initial_stress_shell_records(raw: List[str]):
    """Yield ``(card1_idx, fields, pt_row_indices, truncated)`` per element.

    Card 1 (Vol I R17 p.28-95, EIGHT fields, cols 1-80)::

        EID NPLANE NTHICK NHISV NTENSR LARGE NTHINT NTHHSV

    read with ``n=9`` so a stray NINTH cell can be NAMED (it is never used as
    data — this keyword has no ILOCAL; see the handler). Then
    ``NPLANE*NTHICK`` stress records, each 1 row (LARGE=0, 8x10) or 2 rows
    (LARGE=1, 5x16 + 3x16), each trailed by ``ceil(NHISV/8|5)`` history rows
    and ``ceil(NTENSR/6|5)`` tensor rows, and finally
    ``NTHINT*ceil(NTHHSV/8|5)`` thermal rows.

    RAW CONTIGUITY (#119): every one of those rows is claimed by ROW INDEX
    from the card-1 row, never by "the next non-blank row" — an all-blank
    stress card is legal LS-DYNA (every component defaults to 0.0) and a
    non-blank walk would step over it and eat the next element's card 1.

    ``truncated`` is True when the block ends mid-record; the generator then
    stops, mirroring the handler's ``break``.
    """
    i = 0
    n = len(raw)
    while i < n:
        if not raw[i].strip():
            i += 1
            continue
        f = _card(raw, i, fixed=True, n=9, w=10)
        eid = to_int(f[0]) if f else 0
        if eid <= 0:
            i += 1
            continue
        nplane = max(1, to_int(f[1]))
        nthick = max(1, to_int(f[2]))
        nhisv = to_int(f[3]) if len(f) > 3 else 0
        ntensr = to_int(f[4]) if len(f) > 4 else 0
        large = to_int(f[5]) if len(f) > 5 else 0
        nthint = to_int(f[6]) if len(f) > 6 else 0
        nthhsv = to_int(f[7]) if len(f) > 7 else 0
        ninth = to_int(f[8]) if len(f) > 8 else 0
        card1 = i
        i += 1
        pt_rows: List[int] = []
        truncated = False
        for _ in range(nplane * nthick):
            if i >= n:
                truncated = True
                break
            pt_rows.append(i)
            i += 2 if large else 1
            if nhisv > 0:
                i += _ceil_div(nhisv, 5 if large else 8)
            if ntensr > 0:
                i += _ceil_div(ntensr, 5 if large else 6)
        if nthint > 0 and nthhsv > 0:
            i += nthint * _ceil_div(nthhsv, 5 if large else 8)
        yield (card1, (eid, nplane, nthick, nhisv, ntensr, large, nthint,
                       nthhsv, ninth), pt_rows, truncated)
        if truncated:
            return


def initial_stress_solid_records(raw: List[str]):
    """Yield ``(card1_idx, fields, pt_row_indices, truncated)`` per element.

    Card 1 (Vol I R17 p.28-103)::

        EID NINT NHISV LARGE IVEFLG IALEGP NTHINT NTHHSV

    then ``NINT`` stress records of 1 row (LARGE=0, 7x10) or 2 rows (LARGE=1,
    5x16 + 5x16, the first 3 history values riding row 2), each trailed by the
    remaining ``NHISV+IVEFLG`` history rows, then the thermal rows. Same raw
    contiguity rule as the shell walker.
    """
    i = 0
    n = len(raw)
    while i < n:
        if not raw[i].strip():
            i += 1
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        eid = to_int(f[0]) if f else 0
        if eid <= 0:
            i += 1
            continue
        nint = max(1, to_int(f[1]))
        nhisv = to_int(f[2]) if len(f) > 2 else 0
        large = to_int(f[3]) if len(f) > 3 else 0
        iveflg = to_int(f[4]) if len(f) > 4 else 0
        ialegp = to_int(f[5]) if len(f) > 5 else 0
        nthint = to_int(f[6]) if len(f) > 6 else 0
        nthhsv = to_int(f[7]) if len(f) > 7 else 0
        card1 = i
        i += 1
        nh = nhisv + iveflg   # IVEFLG appends extra value(s) to the history list
        pt_rows: List[int] = []
        truncated = False
        for _ in range(nint):
            if i >= n:
                truncated = True
                break
            pt_rows.append(i)
            if large:
                i += 2
                if nh > 3:                    # 3 history values ride card 2
                    i += _ceil_div(nh - 3, 5)
            else:
                i += 1
                if nh > 0:
                    i += _ceil_div(nh, 8)
        if nthint > 0 and nthhsv > 0:
            i += nthint * _ceil_div(nthhsv, 5 if large else 8)
        yield (card1, (eid, nint, nhisv, large, iveflg, ialegp, nthint,
                       nthhsv, nh), pt_rows, truncated)
        if truncated:
            return


def handle_initial_stress_shell(block: Block, state: ConversionState) -> None:
    """*INITIAL_STRESS_SHELL → /INISHE/STRS_F/GLOB.

    Card 1 (Keyword971 initial_stress_shell_subobj.cfg, Vol I R17 p.28-95) —
    EIGHT fields, cols 1-80, and nothing after them:
        EID NPLANE NTHICK NHISV NTENSR LARGE NTHINT NTHHSV
    then NPLANE×NTHICK stress cards:
        small (LARGE=0): T SIGXX SIGYY SIGZZ SIGXY SIGYZ SIGZX EPS   (8×10)
        large (LARGE=1): T..SIGXY / SIGYZ SIGZX EPS                  (5+3×16)
    each followed by the NHISV history cards (8/card small, 5/card large) and
    NTENSR tensor cards (6/card small, 5/card large); NTHINT×NTHHSV thermal
    history cards close the element record (large format).

    The stress components are ALWAYS global cartesian — "SIGij  Define the ij
    stress component.  The stresses are defined in the GLOBAL cartesian system"
    (p.28-98) — so the writer always emits /INISHE/STRS_F/GLOB, which carries
    the full tensor (incl. σzz), the plastic strain eps_p AND the thickness
    position pos_nip 1:1. There is NO ILOCAL field on this keyword (that is
    *INITIAL_STRAIN_SHELL card 1 field 8, p.28-67); a value in cols 81-90 is
    past the card's last field, is not read by LS-DYNA, and is reported +
    ignored here rather than switched on. NHISV/NTENSR/thermal data have no
    /INISHE slot → dropped with one aggregated warning per block. NPLANE>1
    in-plane points are averaged per through-thickness layer (the /INISHE
    per-layer format is replicated across the shell's in-plane Gauss points by
    the writer).
    """
    raw = block.raw
    n_hisv_dropped = 0
    n_tensr_dropped = 0
    n_thermal_dropped = 0
    n_plane_averaged = 0
    n_read = 0
    ninth_cell: List[int] = []
    for _c1, (eid, nplane, nthick, nhisv, ntensr, large, nthint, nthhsv,
              ninth), pt_rows, truncated in initial_stress_shell_records(raw):
        if ninth != 0:
            ninth_cell.append(eid)
        pts = []
        for r in pt_rows:
            if large:
                a = _fixed_float_card(raw, r, 5, 16)
                b = (_fixed_float_card(raw, r + 1, 3, 16)
                     if r + 1 < len(raw) else [0.0] * 3)
                pts.append(tuple(a + b))
            else:
                pts.append(tuple(_fixed_float_card(raw, r, 8, 10)))
        if nthint > 0 and nthhsv > 0:
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
                               layers=cast(List[_Layer8], layers)))
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
    if ninth_cell:
        named = ", ".join(str(e) for e in ninth_cell[:25])
        if len(ninth_cell) > 25:
            named += f", ... (+{len(ninth_cell) - 25} more)"
        state.warn("*INITIAL_STRESS_SHELL: element(s) "
                   f"{named} carry a NINTH value on card 1 "
                   "(cols 81-90). This keyword's card 1 ends at NTHHSV, field 8 "
                   "(Vol I R17 p.28-95), so LS-DYNA does not read that cell — "
                   "it was IGNORED here too. In particular it is not an ILOCAL "
                   "flag: that field belongs to *INITIAL_STRAIN_SHELL, and this "
                   "card's own text states the frame outright ('the stresses "
                   "are defined in the GLOBAL cartesian system', p.28-98), so "
                   "the components were written to /INISHE/STRS_F/GLOB.")


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
    n_hisv_dropped = 0
    n_thermal_dropped = 0
    for _c1, (eid, nint, nhisv, large, iveflg, _ialegp, nthint, nthhsv,
              nh), pt_rows, truncated in initial_stress_solid_records(raw):
        pts = []
        for r in pt_rows:
            if large:
                a = _fixed_float_card(raw, r, 5, 16)
                b = (_fixed_float_card(raw, r + 1, 2, 16)
                     if r + 1 < len(raw) else [0.0] * 2)
                pts.append(tuple(a + b))
            else:
                pts.append(tuple(_fixed_float_card(raw, r, 7, 10)))
        if nthint > 0 and nthhsv > 0:
            n_thermal_dropped += 1
        if truncated:
            state.warn(f"*INITIAL_STRESS_SOLID eid={eid}: block ends before all "
                       f"{nint} integration-point cards — element skipped.")
            break
        if nh > 0:
            n_hisv_dropped += 1
        state.ini_stress_solids.append(
            InitialStressSolid(eid=eid, nint=nint,
                               points=cast(List[_Layer7], pts)))

    if n_hisv_dropped:
        state.warn(f"*INITIAL_STRESS_SOLID: NHISV/IVEFLG history values on "
                   f"{n_hisv_dropped} element(s) have no /INIBRI slot — dropped "
                   "(plastic strain EPS itself IS mapped via Epsilon_p).")
    if n_thermal_dropped:
        state.warn(f"*INITIAL_STRESS_SOLID: thermal history (NTHINT/NTHHSV) on "
                   f"{n_thermal_dropped} element(s) has no /INIBRI slot — dropped.")


# ── *INITIAL_STRAIN_SHELL[_SET] ──────────────────────────────────────────────
#
# ONE record walker, shared by the handler below and by the
# *INCLUDE_TRANSFORM offsetter (assembly._off_initial_strain_shell). The two
# walks must agree on which raw row is a card 1 or the offsetter desyncs and
# rewrites a STRAIN COMPONENT as an element id (#116 / #119).

def initial_strain_shell_records(raw: List[str], is_set: bool):
    """Yield ``(card1_idx, fields, point_card_indices)`` per element record.

    Card 1 — Keyword971_R13.0/TABLE/initial_strain_shell_subobj.cfg:110::

        COMMENT("$      EID    NPLANE    NTHICK     LARGE                                  ILOCAL");
        CARD("%10d%10d%10d%10d%10s%10s%10s%10d", eid, ngaussianpoints,
             nintegrationpoints, large, _BLANK_, _BLANK_, _BLANK_, ilocal);

    so LARGE is cell 4 (index 3) and ILOCAL cell 8 (index 7, cols 71-80) —
    NOT the *INITIAL_STRESS_SHELL positions (LARGE index 5, ILOC index 8),
    and there are no NHISV/NTENSR/thermal cards on this keyword at all.

    Strain-card count (cfg :113-121)::

        if(nintegrationpoints>0 && ngaussianpoints>0)  tot = NPLANE*NTHICK
        else                                           tot = 1*2

    with the ``_SET`` spelling forced to the 2-card inner/outer form: Vol I R17
    p.3120 states NPLANE/NTHICK are "not read when the SET option is used" and
    "When NPLANE and NTHICK are not defined **or when the SET option is
    used**, define two cards below, one for the inner integration point and
    the other for the outer".

    Each strain record is one card of 7x10 (``EPSxx EPSyy EPSzz EPSxy EPSyz
    EPSzx T``) when LARGE=0, or two cards of 5x16 + 2x16 when LARGE=1.

    RAW CONTIGUITY (#119): strain cards are claimed by ROW INDEX from the
    card-1 row. An all-blank strain card is legal LS-DYNA (every component
    defaults to 0.0); a "next non-blank row" walk would step over it and eat
    the following element's card 1.
    """
    i = 0
    n = len(raw)
    while i < n:
        if not raw[i].strip():
            i += 1
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        eid = to_int(f[0]) if f else 0
        if eid <= 0:
            i += 1
            continue
        nplane = to_int(f[1]) if len(f) > 1 else 0
        nthick = to_int(f[2]) if len(f) > 2 else 0
        large = to_int(f[3]) if len(f) > 3 else 0
        ilocal = to_int(f[7]) if len(f) > 7 else 0
        npts = (nplane * nthick) if (nplane > 0 and nthick > 0) else 2
        if is_set:
            npts = 2
        rows_per_pt = 2 if large else 1
        card1 = i
        i += 1
        pt_rows: List[int] = []
        for _ in range(npts):
            if i >= n:
                break
            pt_rows.append(i)
            i += rows_per_pt
        yield (card1, (eid, nplane, nthick, large, ilocal, npts), pt_rows)


def handle_initial_strain_shell(block: Block, state: ConversionState) -> None:
    """*INITIAL_STRAIN_SHELL[_SET] → /INISHE/STRA_F/GLOB + /INISH3/STRA_F/GLOB.

    The strains are a GLOBAL cartesian tensor "used for post-processing only"
    in LS-DYNA (Vol I R17 p.3119); in Radioss they land in ``GBUF%STRA``
    (csigini.F:165-215), which feeds the /TH E1..K12 channels AND the
    total-strain failure models — measured: a /FAIL/TENSSTRAIN shell with an
    initialised eps_XX above its threshold is deleted at cycle 1.
    """
    is_set = block.keyword.endswith("_SET")
    n_plane_avg = 0
    set_dims_ignored = False
    truncated: List[int] = []
    # No cfg FORMAT block declares a _TITLE or _ID option for this keyword, so
    # _title_offset is 0 on every legal deck. It is applied anyway because
    # assembly._off_initial_strain_shell_common applies it: the two walks must
    # start on the same raw row, or the offsetter rewrites a strain value as an
    # element id on a deck that carries a nonstandard header line.
    body = block.raw[_title_offset(block):]
    for _c1, (eid, nplane, nthick, large, ilocal, npts), pt_rows in \
            initial_strain_shell_records(body, is_set):
        if len(pt_rows) < npts:
            truncated.append(eid)
            break
        pts: List[Tuple[float, ...]] = []
        for r in pt_rows:
            if large:
                exx, eyy, ezz, exy, eyz = _fixed_float_card(body, r, 5, 16)
                ezx, t = (_fixed_float_card(body, r + 1, 2, 16)
                          if r + 1 < len(body) else [0.0, 0.0])
            else:
                exx, eyy, ezz, exy, eyz, ezx, t = \
                    _fixed_float_card(body, r, 7, 10)
            pts.append((t, exx, eyy, ezz, exy, eyz, ezx))
        # NPLANE in-plane points collapse to one value per through-thickness
        # station. Points of one station share their T, so group by T (robust
        # to either loop order) and fall back to consecutive-NPLANE chunking
        # when the distinct-T count does not match NTHICK (an all-zero T
        # column). Same rule as handle_initial_stress_shell.
        eff_plane = nplane if (nplane > 0 and nthick > 0 and not is_set) else 1
        eff_thick = nthick if (nplane > 0 and nthick > 0 and not is_set) else 2
        if eff_plane > 1 and len(pts) == eff_plane * eff_thick:
            n_plane_avg += 1
            order: List[float] = []
            groups: dict = {}
            for p in pts:
                groups.setdefault(p[0], []).append(p)
                if len(groups[p[0]]) == 1:
                    order.append(p[0])
            if len(order) == eff_thick:
                layers = [_avg_tuples(groups[t]) for t in order]
            else:
                layers = [_avg_tuples(pts[k * eff_plane:(k + 1) * eff_plane])
                          for k in range(eff_thick)]
        else:
            layers = pts
        if is_set and (nplane or nthick):
            set_dims_ignored = True
        state.ini_strain_shells.append(InitialStrainShell(
            eid=eid, nplane=nplane, nthick=nthick, ilocal=ilocal,
            is_set=is_set, layers=cast(List[_Layer7], layers)))
    if truncated:
        state.warn(f"*{block.keyword}: the block ends before all strain cards "
                   f"of record {truncated[0]} — that record and any after it "
                   "were skipped.")
    if n_plane_avg:
        state.warn(f"*{block.keyword}: NPLANE>1 in-plane integration points on "
                   f"{n_plane_avg} element(s) were AVERAGED per through-"
                   "thickness station — one value per station, replicated "
                   "across whatever in-plane Gauss points the emitted "
                   "/INISHE|/INISH3 /STRA_F/GLOB record carries. (The card's "
                   "npg is the writer's decision, not the handler's: it depends "
                   "on the shell formulation and on whether the deck also "
                   "carries an initial-STRESS block — see _stra_f_npg in "
                   "k2rad/writer/inistate.py.)")
    if set_dims_ignored:
        state.warn("*INITIAL_STRAIN_SHELL_SET: NPLANE/NTHICK are IGNORED for "
                   "the _SET spelling (Vol I R17 p.3120, 'not read when the "
                   "SET option is used') — exactly two strain cards were read "
                   "per record, inner then outer, whatever those two columns "
                   "say.")


def handle_initial_stress_section(block: Block, state: ConversionState) -> None:
    """*INITIAL_STRESS_SECTION[_TITLE] → /PRELOAD (bolt pre-tension).

    Card — Keyword971_R14.1/TABLE/initial_stress_section.cfg:111-112::

        COMMENT("$    ISSID      CSID      LCID      PSID       VID   IZSHEAR    ISTIFF");
        CARD("%10d%10d%10d%10d%10d%10d%10d", _ID_, csid, lcid, psid, vid,
             izshear, SCALAR_OR_OBJECT(opt_istiff_funct, istiff, istiff_funct));

    ISSID is the card's FIRST CELL, not an ``_ID`` header card, so the only
    header this keyword can carry is the ``_TITLE`` option's 80-char title
    line (cfg :106-109) — ``_title_offset``, never ``_has_id``.
    """
    raw = block.raw
    off = _title_offset(block)
    f = _card(raw, off, fixed=True, n=7, w=10)
    if not f or all(not x.strip() for x in f):
        state.warn("*INITIAL_STRESS_SECTION: missing data card — skipped.")
        return

    def g(k: int) -> int:
        return to_int(f[k]) if len(f) > k and f[k].strip() else 0

    state.ini_stress_sections.append(InitialStressSection(
        issid=g(0), title=_read_title(block, ""), csid=g(1), lcid=g(2),
        psid=g(3), vid=g(4), izshear=g(5), istiff=g(6)))


def handle_initial_axial_force_beam(block: Block, state: ConversionState) -> None:
    """*INITIAL_AXIAL_FORCE_BEAM → /PRELOAD/AXIAL (1D bolt pre-tension).

    Card — Keyword971_R9.3/LOADCOL/initial_axial_force_beam.cfg:83-84::

        COMMENT("$     BSID      LCID     SCALE     KBEND");
        CARD("%10d%10d%10lg%10d", LSD_SID, LSD_LCID, LSD_AXIAL_SCALE, LSD_KBEND);

    The R6.1 format is the same card without KBEND, and neither format block
    declares a ``_TITLE`` or ``_ID`` option (both ``HEADER`` lines are the bare
    keyword), so there is no header card to skip.

    SCALE is dimensionless and defaults to 1.0 (cfg DEFAULTS). A literal 0.0 is
    also taken as 1.0: ``hm_read_preload_axial.F90:257`` does
    ``if (loadval==zero) loadval = one``, so writing the 0 through would only
    hide what the starter is going to do anyway.
    """
    raw = block.raw
    off = _title_offset(block)
    for i in range(off, len(raw)):
        if not raw[i].strip():
            continue
        f = _card(raw, i, fixed=True, n=4, w=10)
        bsid = to_int(f[0]) if f else 0
        if bsid <= 0:
            continue
        scale = _ffield(f, 2, 1.0) or 1.0
        state.ini_axial_force_beams.append(InitialAxialForceBeam(
            bsid=bsid,
            lcid=to_int(f[1]) if len(f) > 1 else 0,
            scale=scale,
            kbend=to_int(f[3]) if len(f) > 3 else 0))


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
    tag = f"*DATABASE_CROSS_SECTION_PLANE{f' id={csid}' if csid else ''}"
    radius = g(7)
    xct, yct, zct = g(1), g(2), g(3)
    xch, ych, zch = g(4), g(5), g(6)
    radius_is_nodes = radius < 0.0
    xct_nid = xch_nid = 0
    if radius_is_nodes:
        # Vol I R17 p.16-49/50: "If RADIUS is negative, the radius will be the
        # absolute value of RADIUS and XCT and XCH will be node IDs ... YCT,
        # ZCT, YCH, and ZCH are ignored." The ids are only RECORDED here; the
        # lookup happens in the writer (inistate.resolve_cross_section_
        # endpoints), because handlers run in deck-block order and state.nodes
        # is filled by handle_node in the SAME pass — a card written before
        # *NODE (the standard layout, *CONTROL_/*DATABASE_ at the head of the
        # deck) saw an empty table and the section was dropped with the untrue
        # message "they are not nodes of this deck". Measured on twin probes
        # differing only in card order.
        radius = -radius
        xct_nid, xch_nid = to_int(f1[1]), to_int(f1[4])
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    xhev = yhev = zhev = 0.0
    has_hev = False
    loc_id = itype = 0
    if f2:
        xhev = to_float(f2[0]) if len(f2) > 0 else 0.0
        yhev = to_float(f2[1]) if len(f2) > 1 else 0.0
        zhev = to_float(f2[2]) if len(f2) > 2 else 0.0
        has_hev = any(x.strip() for x in f2[:3])
        lenl = to_float(f2[3]) if len(f2) > 3 else 0.0
        lenm = to_float(f2[4]) if len(f2) > 4 else 0.0
        loc_id = to_int(f2[5]) if len(f2) > 5 else 0
        itype = to_int(f2[6]) if len(f2) > 6 else 0
        # p.16-50 covers FIVE cells in one sentence: "If RADIUS != 0.0, the
        # variables XHEV, YHEV, ZHEV, LENL, and LENM, which are specified on
        # Card 1a.2, will be ignored." The exemption used to be applied to
        # XHEV/YHEV/ZHEV only, so a RADIUS-limited card with LENL/LENM still
        # got the fidelity-loss warning below — reporting a loss that does not
        # exist, because LS-DYNA ignores those cells itself and k2rad's
        # behaviour is then exactly LS-DYNA's (#125/#130, over-alarming
        # direction). RADIUS is already the absolute value here, so the gate
        # covers the RADIUS < 0 node-id spelling too.
        if radius != 0.0 and (has_hev or lenl or lenm):
            ignored = ", ".join(
                w for w, on in (("the edge vector (XHEV/YHEV/ZHEV)", has_hev),
                                ("LENL/LENM", lenl or lenm)) if on)
            state.warn(f"{tag}: RADIUS is non-zero, so LS-DYNA ignores "
                       f"{ignored} on card 2 (Vol I R17 p.16-50) — nothing is "
                       "lost here; the /SECT cut is limited to RADIUS and its "
                       "output frame's in-plane axis is synthesized, exactly "
                       "as LS-DYNA would.")
            has_hev = False
        elif lenl or lenm:
            state.warn(f"{tag}: finite parallelogram extent (LENL/LENM) cannot "
                       "be carried into /SECT — treated as an infinite plane.")
        if loc_id:
            what = {0: "a rigid body (*PART)",
                    1: "an accelerometer (*ELEMENT_SEATBELT_ACCELEROMETER)",
                    2: "a *DEFINE_COORDINATE_* system"}.get(
                        itype, f"an unknown ITYPE={itype} entity")
            state.warn(
                f"{tag}: the output-frame request ID={loc_id} / ITYPE={itype} "
                f"names {what}, and LS-DYNA would report the force resultants "
                "in that system as it UPDATES (Vol I R17 p.16-50). That is not "
                "converted: the /SECT frame is built from the card's own "
                "cutting plane — origin (XCT,YCT,ZCT), normal XCT->XCH, "
                "in-plane axis from the edge vector — and is FIXED in space, "
                "so on a rotating body the reported components drift from what "
                "secforc would print. The resultant itself is unaffected.")
    state.cross_sections.append(CrossSection(
        csid=csid, title=title, kind="PLANE",
        psid=to_int(f1[0]),
        xct=xct, yct=yct, zct=zct,
        xch=xch, ych=ych, zch=zch,
        radius=radius, radius_is_nodes=radius_is_nodes,
        xct_nid=xct_nid, xch_nid=xch_nid,
        xhev=xhev, yhev=yhev, zhev=zhev, has_hev=has_hev,
        loc_id=loc_id, itype=itype))


def handle_database_cross_section_set(block: Block, state: ConversionState) -> None:
    """*DATABASE_CROSS_SECTION_SET[_ID] → /SECT (direct set mapping).

    Card: NSID HSID BSID SSID TSID DSID ID ITYPE — node set → the /SECT node
    group, solid/beam/shell element sets → its grbric/grbeam/grshel groups.
    DSID (*SET_DISCRETE) goes to the card's grsprg_ID column as a
    /GRSPRI/SPRI group. TSID names a *SET_TSHELL, an id namespace this
    converter does not read: the writer tries the *SET_SOLID registry (a thick
    shell IS a /BRICK here) and otherwise names the loss — never *SET_SHELL,
    which is a third namespace holding ordinary shells.
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
    itype = to_int(f1[7]) if len(f1) > 7 else 0
    # TSID and DSID used to be dropped here with the stated reason "no
    # converter-side element type". That was FALSE on BOTH counts (#130 — an
    # exclusion's stated reason needs the same audit as a warning's): k2rad
    # writes thick shells as /BRICK, which is the grbric_ID group the card
    # already carries, and it has emitted starter-validated /GRSPRI/SPRI
    # groups since the preload batch, which is the grsprg_ID column
    # (sect.cfg:37 declares it SUBTYPES = (/SETS/GRSPRI), hm_read_sect.F:301
    # reads it, :548 resolves it with ELEGROR(...,'SPRI')). Both are converted
    # now; the writer says which group each one went into.
    tag = f"*DATABASE_CROSS_SECTION_SET{f' id={csid}' if csid else ''}"
    if loc_id:
        what = {0: "a rigid body (*PART)",
                1: "an accelerometer (*ELEMENT_SEATBELT_ACCELEROMETER)",
                2: "a *DEFINE_COORDINATE_* system"}.get(
                    itype, f"an unknown ITYPE={itype} entity")
        state.warn(
            f"{tag}: the output-frame request ID={loc_id} / ITYPE={itype} "
            f"names {what}, and LS-DYNA would report the force resultants in "
            "that system as it UPDATES (Vol I R17 p.16-50). That is not "
            "converted: this card states no cutting plane at all, so the "
            "/SECT frame is FITTED to the section nodes and is fixed in "
            "space. The resultant itself is unaffected.")
    state.cross_sections.append(CrossSection(
        csid=csid, title=title, kind="SET",
        nsid=to_int(f1[0]),
        hsid=to_int(f1[1]) if len(f1) > 1 else 0,
        bsid=to_int(f1[2]) if len(f1) > 2 else 0,
        ssid=to_int(f1[3]) if len(f1) > 3 else 0,
        tsid=tsid, dsid=dsid, loc_id=loc_id, itype=itype))


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


def _warn_extra_rwall_card_sets(state: ConversionState, label: str, kw: str,
                                rwid: int, raw, idx: int, family: str) -> None:
    """One guard for both rigid-wall families.

    "Card Sets. For each rigid wall include ONE SET of the following data
    cards. This input ends at the next keyword card" (Manual p. 40-5) — a
    single *RIGIDWALL_ keyword may therefore carry several walls, and k2rad
    converts the first set only. Never let the rest vanish silently.

    ``family`` is the keyword stem named in the advice ("*RIGIDWALL_PLANAR" /
    "*RIGIDWALL_GEOMETRIC_"); everything else in the message is identical, and
    tests/test_rwall_geometric.py and tests/test_rwall_variants.py both assert
    on that wording.

    On the planar family this can only be trusted now that the FORCES card is
    consumed: without it, ``idx`` stopped one line short on every
    *RIGIDWALL_PLANAR_*FORCES deck and the wall's own last card was reported as
    a second, phantom card set.
    """
    if not any(ln.strip() for ln in raw[idx:]):
        return
    state.warn(
        f"{label} id={rwid}: {len(raw) - idx} further card line(s) follow "
        "the first wall's card set. LS-DYNA reads one set per wall and "
        "keeps going to the next keyword (Manual p. 40-5), but k2rad "
        "converts the FIRST set only — split the extra wall(s) into their "
        f"own {family} blocks.")
    state.note_recognized_not_emitted(
        kw, "only the first of several card sets under the keyword was "
            "converted")


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
      _FORCES: soft ssid n1 n2 n3 n4 — ONE card, always the LAST of the set
        (Card Summary, Manual p. 40-17: ID -> 1 -> 2 -> [ORTHO 3,4] ->
        [FINITE 5] -> [MOVING 6] -> [FORCES 7], whatever order the options are
        spelled in the keyword name). It is mostly output plumbing that
        /TH/RWALL already covers, but SOFT is a solver knob, so the card is
        READ rather than assumed absent — leaving it unconsumed made every
        following line shift by one and, worse, made the multi-card-set guard
        below unusable on the planar family.
    _ORTHO (orthotropic friction) has no /RWALL equivalent and is warn-skipped
    by handle_rigidwall_ortho.
    """
    kw = block.keyword
    label = f"*{kw}"
    is_finite = "_FINITE" in kw
    is_moving = "_MOVING" in kw
    raw = block.raw
    offset = _rwall_title_offset(block)
    rwid, title = _rwall_id_and_title(block)
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

    if "_FORCES" in kw:
        # Card 7: SOFT SSID N1 N2 N3 N4 (Manual p. 40-23). Consumed leniently,
        # the same way handle_rigidwall_geometric treats the DISPLAY card: it is
        # the LAST card of the set, so a deck that stops after MOVING is legal
        # LS-DYNA and must not be warned at.
        if idx < len(raw) and raw[idx].strip():
            ff = _card(raw, idx, fixed=True, n=8, w=10)
            idx += 1
            soft = to_int(ff[0]) if ff else 0
            ssid = to_int(ff[1]) if len(ff) > 1 else 0
            # N1..N4 are "Optional node for visualization" (Manual p. 40-23) —
            # they change nothing about the wall and are dropped in silence.
            if soft:
                state.warn(
                    f"{label} id={rwid}: FORCES SOFT={soft} (ramp the relative "
                    "velocity to zero over that many cycles to soften the "
                    "initial contact-force spike) has no /RWALL equivalent — "
                    "dropped. The wall engages at full stiffness from the "
                    "first contact cycle, so expect a sharper force peak at "
                    "t=0 than LS-DYNA reports. Soften it by ramping the "
                    "approach velocity, or replace the wall with an /INTER "
                    "interface, whose penalty stiffness IS tunable.")
            if ssid:
                state.warn(
                    f"{label} id={rwid}: FORCES SSID={ssid} splits the wall "
                    "force over the segments of that *SET_SEGMENT for "
                    "per-area output in rwforc — dropped. /RWALL reports ONE "
                    "resultant for the whole wall (/TH/RWALL), so the "
                    "distribution over sub-areas is not available; split the "
                    "wall into several *RIGIDWALL_PLANAR blocks if you need "
                    "the force per region.")

    _warn_extra_rwall_card_sets(state, label, kw, rwid, raw, idx,
                                "*RIGIDWALL_PLANAR")

    state.rigid_walls.append(RigidWallPlanar(
        rwid=rwid, title=title, nsid=nsid, nsidex=nsidex,
        xt=g(0), yt=g(1), zt=g(2), xh=g(3), yh=g(4), zh=g(5),
        fric=fric, birth=birth, death=death, offset=woff,
        boxid=boxid,
        moving=is_moving, mass=mass, v0=v0,
        finite=is_finite, xhev=xhev, yhev=yhev, zhev=zhev,
        lenl=lenl, lenm=lenm))


def _rwall_has_id(block: Block) -> bool:
    """True when a *RIGIDWALL_* block carries the ``_ID`` header card.

    "The order of the OPTIONS is arbitrary" (Manual p. 40-4) and the cfg
    locates the option with an unanchored ``_FIND(_opt, "_ID")``, so ``_ID``
    is legal in a non-final position too — ``*RIGIDWALL_GEOMETRIC_SPHERE_ID_-
    MOTION``. The keyword parser only strips a TRAILING _ID/_TITLE, so for the
    non-final spelling the option never reaches ``block.options`` and the RWID
    card would be misread as Card 1 (losing the wall's id, its heading and
    every card index after it).
    """
    return _has_id(block) or "_ID_" in f"_{block.keyword}_"


def _rwall_title_offset(block: Block) -> int:
    return 1 if _rwall_has_id(block) else _title_offset(block)


def _rwall_id_and_title(block: Block) -> Tuple[int, str]:
    """(RWID, HEADING) from a *RIGIDWALL_* ``_ID`` header card, else (0, "").

    Both rigidwall cfgs write the header as ``CARD("%10d%-70s", _ID_, TITLE)``
    (rigidwall_geometric.cfg:469, rigidwall_planar.cfg), so an unpadded title
    is FUSED to the id — "       777my wall" free-splits to the token
    "777my", which is not an integer and would silently cost the wall both its
    user id and its name. Slice the I10 field first and fall back to the free
    split only when that field is not a bare integer (a comma-separated or
    narrower hand-written card).
    """
    if not (_rwall_has_id(block) and block.raw):
        return 0, ""
    line = block.raw[0]
    head = line[:10].strip()
    if head.isdigit() or (head.startswith("-") and head[1:].isdigit()):
        return to_int(head), line[10:].strip()
    tokens = parse_free(line)
    if not tokens:
        return 0, ""
    return to_int(tokens[0]), " ".join(tokens[1:])


#: *RIGIDWALL_GEOMETRIC shape suffix → the LS-DYNA card-3 flavour.
_RWALL_GEOM_SHAPES = ("FLAT", "PRISM", "CYLINDER", "SPHERE")


def handle_rigidwall_geometric(block: Block, state: ConversionState) -> None:
    """*RIGIDWALL_GEOMETRIC_<shape>[_MOTION][_DISPLAY][_ID] → /RWALL/*.

    Card 1: nsid nsidex boxid birth death
    Card 2: xt yt zt xh yh zh fric
    Card 3 (shape, LS-DYNA's strict card order — the option NAMES may be in
    any order, the CARDS may not, Manual p. 3659):
      _FLAT      xhev yhev zhev lenl lenm
      _PRISM     xhev yhev zhev lenl lenm lenp
      _CYLINDER  radcyl lencyl nsegs, then NSEGS "vl height" sub-cards
      _SPHERE    radsph
    Card 4 (_MOTION):  lcid opt vx vy vz   — always BEFORE card 5
    Card 5 (_DISPLAY): pid ro e pr

    The geometry is resolved to Radioss walls by the writer prepass
    ``_resolve_geometric_rigid_walls`` (it also synthesizes the _MOTION
    carrier nodes, which must exist before the /NODE section is built).
    """
    kw = block.keyword
    shape = next(s for s in _RWALL_GEOM_SHAPES if f"_{s}" in kw)
    label = f"*{kw}"
    raw = block.raw
    offset = _rwall_title_offset(block)
    rwid, title = _rwall_id_and_title(block)
    if rwid <= 0:
        rwid = state.next_id()

    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1:
        state.warn(f"{label}: missing data card — skipped.")
        state.note_recognized_not_emitted(
            kw, "the wall's Card 1 (NSID/NSIDEX/BOXID) is missing")
        return
    nsid   = to_int(f1[0])
    nsidex = to_int(f1[1]) if len(f1) > 1 else 0
    boxid  = to_int(f1[2]) if len(f1) > 2 else 0
    birth  = to_float(f1[3]) if len(f1) > 3 else 0.0
    death  = _ffield(f1, 4, 0.0)

    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if len(f2) < 6:
        state.warn(f"{label} id={rwid}: missing geometry card — skipped.")
        state.note_recognized_not_emitted(
            kw, "the wall's Card 2 (XT..ZH/FRIC) is missing or too short")
        return
    g = lambda i: to_float(f2[i]) if len(f2) > i else 0.0
    fric = g(6)
    if birth > 0.0 or (0.0 < death < 1e20):
        state.warn(f"{label} id={rwid}: BIRTH/DEATH have no /RWALL "
                   "equivalent — the wall is active for the whole run.")

    rw = RigidWallGeometric(
        rwid=rwid, title=title, shape=shape,
        nsid=nsid, nsidex=nsidex, boxid=boxid, birth=birth, death=death,
        xt=g(0), yt=g(1), zt=g(2), xh=g(3), yh=g(4), zh=g(5), fric=fric)

    idx = offset + 2
    f3 = _card(raw, idx, fixed=True, n=8, w=10)
    idx += 1
    if not f3:
        state.warn(f"{label} id={rwid}: missing the {shape} shape card — "
                   "the wall dimensions are unknown, so it was skipped.")
        state.note_recognized_not_emitted(
            kw, f"the {shape} shape card (Card 3) is missing")
        return
    h = lambda i: to_float(f3[i]) if len(f3) > i else 0.0
    if shape in ("FLAT", "PRISM"):
        rw.xhev, rw.yhev, rw.zhev = h(0), h(1), h(2)
        rw.lenl, rw.lenm = h(3), h(4)
        if shape == "PRISM":
            rw.lenp = h(5)
    elif shape == "CYLINDER":
        rw.radcyl, rw.lencyl = h(0), h(1)
        rw.nsegs = to_int(f3[2]) if len(f3) > 2 else 0
        if rw.nsegs > 0:
            # Card 3c.1 repeats NSEGS times (VL HEIGHT) — force-output
            # subdivisions with no /RWALL counterpart, but they DO shift the
            # _MOTION / _DISPLAY cards, so the cursor has to skip them.
            idx += rw.nsegs
            state.warn(
                f"{label} id={rwid}: NSEGS={rw.nsegs} subdivides the cylinder "
                "for per-segment force output; /RWALL/CYL is one wall with one "
                "resultant, so the VL/HEIGHT sub-cards were dropped and "
                "/TH/RWALL reports the whole-cylinder resultant only.")
    else:                       # SPHERE
        rw.radsph = h(0)

    if "_MOTION" in kw:
        fm = _card(raw, idx, fixed=True, n=8, w=10)
        idx += 1
        if len(fm) < 2:
            state.warn(f"{label} id={rwid}: missing the MOTION card — the "
                       "wall is emitted as a FIXED wall.")
        else:
            rw.motion = True
            rw.lcid = to_int(fm[0])
            rw.opt = to_int(fm[1])
            rw.vx = to_float(fm[2]) if len(fm) > 2 else 0.0
            rw.vy = to_float(fm[3]) if len(fm) > 3 else 0.0
            rw.vz = to_float(fm[4]) if len(fm) > 4 else 0.0
    if "_DISPLAY" in kw:
        # PID/RO/E/PR describe a visualization mesh only and have no effect on
        # the solution (Manual p. 40-13) — dyna2rad never reads them either.
        # The card is optional on the LAST card set, so only step over it when
        # something is actually there.
        if idx < len(raw) and raw[idx].strip():
            idx += 1
        state.warn(f"{label} id={rwid}: the DISPLAY card (PID/RO/E/PR) defines "
                   "a visualization mesh only and has no solution effect — "
                   "dropped.")

    _warn_extra_rwall_card_sets(state, label, kw, rwid, raw, idx,
                                "*RIGIDWALL_GEOMETRIC_")

    state.rigid_walls_geometric.append(rw)


def handle_rigidwall_geometric_unsupported(block: Block,
                                           state: ConversionState) -> None:
    """Reached by the keyword-PREFIX fallback: a spelling k2rad cannot read.

    ``dispatch`` only tries this after the exact-match lookup misses, so every
    generated FLAT/PRISM/CYLINDER/SPHERE spelling is already handled and what
    lands here is either a missing shape option or an option whose extra cards
    would shift the card indices — today that is _DEFORM, whose Cards 3c.2/3c.3
    sit between the cylinder card and the MOTION card (Manual p. 40-6).
    Reading such a block as a plain cylinder would take LCID/OPT/VX/VY/VZ off
    the wrong line, so warn-skip instead. dyna2rad drops an unknown shape
    silently (convertrwalls.cxx:214, ``if (GeomType)``).
    """
    kw = block.keyword
    known = {"RIGIDWALL", "GEOMETRIC", "MOTION", "DISPLAY", "INTERIOR",
             "ID", "TITLE", *_RWALL_GEOM_SHAPES}
    extra = [p for p in kw.split("_") if p not in known]
    if not any(f"_{s}" in kw for s in _RWALL_GEOM_SHAPES):
        state.warn(f"*{kw}: no FLAT/PRISM/CYLINDER/SPHERE shape option — "
                   "the wall geometry is undefined, so it was skipped.")
    elif extra:
        state.warn(
            f"*{kw}: the option(s) {', '.join(extra)} add or move data cards "
            "that k2rad does not parse, so every card index after them would "
            "be wrong — the rigid wall was skipped rather than misread.")
    else:
        # Every token is a known option, so the COMBINATION is what LS-DYNA
        # does not offer — e.g. _INTERIOR on a FLAT or PRISM wall, which only
        # the CYLINDER and SPHERE shapes accept (Manual p. 40-4).
        state.warn(
            f"*{kw}: this combination of options is not a legal "
            "*RIGIDWALL_GEOMETRIC spelling (_INTERIOR exists for CYLINDER and "
            "SPHERE only), so the rigid wall was skipped rather than guessed "
            "at.")
    state.skipped_keywords.append(kw)


def handle_rigidwall_geometric_interior(block: Block,
                                        state: ConversionState) -> None:
    """*RIGIDWALL_GEOMETRIC_{CYLINDER,SPHERE}_INTERIOR*: nodes confined INSIDE.

    Radioss /RWALL/CYL and /RWALL/SPHER are unconditionally exterior obstacles
    — the engine tests ``DP <= RA2`` and pushes the node radially OUT
    (rgwalc.F:132-133, rgwals.F:126-127) — and there is no inversion flag on
    any /RWALL card. Converting an _INTERIOR wall would therefore INVERT the
    physics, so warn-skip it instead (dyna2rad parses the option and then
    ignores it, silently producing that inverted wall).
    """
    state.warn(
        f"*{block.keyword}: the INTERIOR option confines nodes INSIDE the "
        "cylinder/sphere, but /RWALL/CYL and /RWALL/SPHER always push nodes "
        "OUTWARD and have no inversion flag — converting it would invert the "
        "wall physics, so this rigid wall was skipped.")
    state.skipped_keywords.append(block.keyword)


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
# Foam batch (MAT_005 / MAT_073 / MAT_126 / MAT_154 / MAT_177 + *CONTACT_INTERIOR)
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_soil_and_foam(block: Block, state: ConversionState) -> None:
    """*MAT_SOIL_AND_FOAM (MAT_005) → /MAT/LAW21.

    LS-DYNA cards (mat_005.cfg Keyword971_R6.1):
      Card1: MID RO G KUN A0 A1 A2 PC
      Card2: VCR REF LCID   (pre-R6.1 decks have no LCID cell; a blank reads 0)
      Card3-4: EPS1..EPS10  Card5-6: P1..P10
    Every sign encoding is kept raw here — EPS = ln(V/V0), NEGATIVE in
    compression, and PC < 0 — and decoded by the emitter's P(mu) transform,
    which is where the semantic warnings live.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_SOIL_AND_FOAM: empty material card — skipped")
        return
    mid = to_int(f1[0])
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    g   = to_float(f1[2]) if len(f1) > 2 else 0.0
    kun = to_float(f1[3]) if len(f1) > 3 else 0.0
    a0  = to_float(f1[4]) if len(f1) > 4 else 0.0
    a1  = to_float(f1[5]) if len(f1) > 5 else 0.0
    a2  = to_float(f1[6]) if len(f1) > 6 else 0.0
    pc  = to_float(f1[7]) if len(f1) > 7 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=3, w=10)
    vcr  = to_float(f2[0]) if f2 else 0.0
    ref  = to_float(f2[1]) if len(f2) > 1 else 0.0
    lcid = to_int(f2[2])   if len(f2) > 2 else 0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    f5 = _card(raw, offset + 4, fixed=True, n=8, w=10)
    f6 = _card(raw, offset + 5, fixed=True, n=8, w=10)
    eps = ([to_float(f3[i]) if len(f3) > i else 0.0 for i in range(8)]
           + [to_float(f4[i]) if len(f4) > i else 0.0 for i in range(2)])
    p = ([to_float(f5[i]) if len(f5) > i else 0.0 for i in range(8)]
         + [to_float(f6[i]) if len(f6) > i else 0.0 for i in range(2)])
    state.mat_soil_and_foam[mid] = MatSoilAndFoam(
        mid, title, rho, g, kun, a0, a1, a2, pc, vcr, ref, lcid, eps, p,
        # *MAT_SOIL_AND_FOAM_FAILURE (MAT_014) has the SAME input as MAT_005 —
        # Vol II R17 p.2-209 verbatim: *"The input for this model is the same
        # as for *MATERIAL_SOIL_AND_FOAM (Type 5); however, when the pressure
        # reaches the tensile failure pressure, the element loses its ability
        # to carry tension."* So one handler reads both spellings and the
        # spelling itself is the flag; the writer adds the /FAIL/SPALLING
        # latch. (_FAILURE is not a trailing _ID/_TITLE, so
        # parser._split_keyword leaves it IN block.keyword.)
        latched_tension_failure="FAILURE" in (block.keyword or "").upper())


def handle_mat_low_density_viscous_foam(block: Block,
                                        state: ConversionState) -> None:
    """*MAT_LOW_DENSITY_VISCOUS_FOAM (MAT_073) → /MAT/LAW90 [+ /VISC/PRONY].

    LS-DYNA cards (mat_073.cfg Keyword971_R6.1):
      Card1: MID RO E LCID TC HU BETA DAMP
      Card2: SHAPE FAIL BVFLAG KCON LCID2 BSTART TRAMP NV
      Card3a (iff LCID2 == 0, repeated up to 6x): Gi BETAi REF
      Card3b (iff LCID2 == -1): LCID3 LCID4 SCALEW SCALEA
      (LCID2 > 0: NO card 3 — the Gi/BETAi come from LS-DYNA's internal
       least-squares fit of the LCID2 relaxation curve.)
    The walk must branch on LCID2 exactly like the cfg's CARD_PREREAD — the
    Gi list and the LCID3/LCID4 card are mutually exclusive, and misreading
    one as the other turns curve ids into moduli. Blank-vs-zero defaults that
    carry semantics (HU=1.0, SHAPE=1.0) go through _ffield.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_LOW_DENSITY_VISCOUS_FOAM: empty material card — "
                   "skipped")
        return
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    E    = to_float(f1[2]) if len(f1) > 2 else 0.0
    lcid = to_int(f1[3])   if len(f1) > 3 else 0
    tc   = to_float(f1[4]) if len(f1) > 4 else 0.0    # 0/blank = 1e20 (no cutoff)
    hu   = _ffield(f1, 5, 1.0)
    beta = to_float(f1[6]) if len(f1) > 6 else 0.0
    damp = _ffield(f1, 7, 0.05)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    shape  = _ffield(f2, 0, 1.0)
    fail   = to_float(f2[1]) if len(f2) > 1 else 0.0
    bvflag = to_float(f2[2]) if len(f2) > 2 else 0.0
    kcon   = to_float(f2[3]) if len(f2) > 3 else 0.0
    lcid2  = to_int(f2[4])   if len(f2) > 4 else 0
    bstart = to_float(f2[5]) if len(f2) > 5 else 0.0
    tramp  = to_float(f2[6]) if len(f2) > 6 else 0.0
    nv     = to_int(f2[7]) if len(f2) > 7 and f2[7].strip() else 6
    prony: List[Tuple[float, float, float]] = []
    lcid3 = lcid4 = 0
    if lcid2 == 0:
        for k in range(offset + 2, min(offset + 8, len(raw))):
            f = _card(raw, k, fixed=True, n=3, w=10)
            if not f or not any(x.strip() for x in f):
                break
            prony.append((to_float(f[0]),
                          to_float(f[1]) if len(f) > 1 else 0.0,
                          to_float(f[2]) if len(f) > 2 else 0.0))
    elif lcid2 == -1:
        f = _card(raw, offset + 2, fixed=True, n=4, w=10)
        lcid3 = to_int(f[0]) if f else 0
        lcid4 = to_int(f[1]) if len(f) > 1 else 0
    ref = 1.0 if any(t[2] != 0.0 for t in prony) else 0.0
    state.mat_low_density_viscous_foam[mid] = MatLowDensityViscousFoam(
        mid, title, rho, E, lcid, tc, hu, beta, damp, shape, fail, bvflag,
        kcon, lcid2, bstart, tramp, nv, prony, lcid3, lcid4, ref)


def handle_mat_modified_honeycomb(block: Block,
                                  state: ConversionState) -> None:
    """*MAT_MODIFIED_HONEYCOMB (MAT_126) → /MAT/LAW50 + /PROP/TYPE6.

    LS-DYNA cards (Manual Vol II R17 p.2-886 — the shipped Keyword971 cfg is
    behind the manual, so the manual layout is authoritative):
      Card1: MID RO E PR SIGY VF MU BULK
      Card2: LCA LCB LCC LCS LCAB LCBC LCCA LCSR
      Card3: EAAU EBBU ECCU GABU GBCU GCAU AOPT MACF
      Card4: XP YP ZP A1 A2 A3 RFAC PRU
      Card5: D1 D2 D3 TSEF SSEF VREF TREF SHDFLG
      Card6 (iff AOPT == 3 or 4): V1 V2 V3
      Card7 (iff LCSR == -1): LCSRA LCSRB LCSRC LCSRAB LCSRBC LCSRCA
      Card8 (iff PRU == 2): PRUAB PRUAC PRUBC PRUBA PRUCA PRUCB
    The walk must clear every conditional card that is present — otherwise a
    following keyword's parse position would be wrong. Sign flags (LCA < 0,
    ECCU < 0, TSEF/SSEF < 0) are kept raw; the writer prepass decodes them.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_MODIFIED_HONEYCOMB: empty material card — skipped")
        return
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    E    = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu   = to_float(f1[3]) if len(f1) > 3 else 0.0
    sigy = to_float(f1[4]) if len(f1) > 4 else 0.0
    vf   = to_float(f1[5]) if len(f1) > 5 else 0.0
    mu   = _ffield(f1, 6, 0.05)
    bulk = to_float(f1[7]) if len(f1) > 7 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    lca  = to_int(f2[0]) if f2        else 0
    lcb  = to_int(f2[1]) if len(f2) > 1 else 0
    lcc  = to_int(f2[2]) if len(f2) > 2 else 0
    lcs  = to_int(f2[3]) if len(f2) > 3 else 0
    lcab = to_int(f2[4]) if len(f2) > 4 else 0
    lcbc = to_int(f2[5]) if len(f2) > 5 else 0
    lcca = to_int(f2[6]) if len(f2) > 6 else 0
    lcsr = to_float(f2[7]) if len(f2) > 7 else 0.0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    eaau = to_float(f3[0]) if f3        else 0.0
    ebbu = to_float(f3[1]) if len(f3) > 1 else 0.0
    eccu = to_float(f3[2]) if len(f3) > 2 else 0.0
    gabu = to_float(f3[3]) if len(f3) > 3 else 0.0
    gbcu = to_float(f3[4]) if len(f3) > 4 else 0.0
    gcau = to_float(f3[5]) if len(f3) > 5 else 0.0
    aopt = to_float(f3[6]) if len(f3) > 6 else 0.0
    macf = to_int(f3[7])   if len(f3) > 7 else 0
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    xp = to_float(f4[0]) if f4        else 0.0
    yp = to_float(f4[1]) if len(f4) > 1 else 0.0
    zp = to_float(f4[2]) if len(f4) > 2 else 0.0
    a1 = to_float(f4[3]) if len(f4) > 3 else 0.0
    a2 = to_float(f4[4]) if len(f4) > 4 else 0.0
    a3 = to_float(f4[5]) if len(f4) > 5 else 0.0
    rfac = to_float(f4[6]) if len(f4) > 6 else 0.0
    pru  = to_float(f4[7]) if len(f4) > 7 else 0.0
    f5 = _card(raw, offset + 4, fixed=True, n=8, w=10)
    d1 = to_float(f5[0]) if f5        else 0.0
    d2 = to_float(f5[1]) if len(f5) > 1 else 0.0
    d3 = to_float(f5[2]) if len(f5) > 2 else 0.0
    tsef = to_float(f5[3]) if len(f5) > 3 else 0.0
    ssef = to_float(f5[4]) if len(f5) > 4 else 0.0
    vref = to_float(f5[5]) if len(f5) > 5 else 0.0
    tref = to_float(f5[6]) if len(f5) > 6 else 0.0
    shdflg = to_float(f5[7]) if len(f5) > 7 else 0.0
    k = offset + 5
    v1 = v2 = v3 = 0.0
    if int(round(aopt)) in (3, 4):
        fv = _card(raw, k, fixed=True, n=3, w=10)
        v1 = to_float(fv[0]) if fv        else 0.0
        v2 = to_float(fv[1]) if len(fv) > 1 else 0.0
        v3 = to_float(fv[2]) if len(fv) > 2 else 0.0
        k += 1
    lcsr_dirs: List[float] = []
    if lcsr == -1.0:
        fr = _card(raw, k, fixed=True, n=6, w=10)
        lcsr_dirs = [to_float(fr[i]) if len(fr) > i else 0.0
                     for i in range(6)]
        k += 1
    pru_ratios: List[float] = []
    if pru == 2.0:
        fp = _card(raw, k, fixed=True, n=6, w=10)
        pru_ratios = [to_float(fp[i]) if len(fp) > i else 0.0
                      for i in range(6)]
        k += 1
    state.mat_modified_honeycomb[mid] = MatModifiedHoneycomb(
        mid, title, rho, E, nu, sigy, vf, mu, bulk,
        lca, lcb, lcc, lcs, lcab, lcbc, lcca, lcsr,
        eaau, ebbu, eccu, gabu, gbcu, gcau, aopt, macf,
        xp, yp, zp, a1, a2, a3, rfac, pru,
        d1, d2, d3, tsef, ssef, vref, tref, shdflg,
        v1, v2, v3, lcsr_dirs, pru_ratios)


def handle_mat_deshpande_fleck_foam(block: Block,
                                    state: ConversionState) -> None:
    """*MAT_DESHPANDE_FLECK_FOAM (MAT_154) → /MAT/LAW115.

    LS-DYNA cards (mat_154.cfg Keyword971_R6.1):
      Card1: MID RHO E PR ALPHA GAMMA
      Card2: EPSD ALPHA2 BETA SIGP DERFI CFAIL PFAIL NUM
    (The pre-R6.1 card 2 stops after CFAIL; blank PFAIL/NUM read 0/1000.)
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_DESHPANDE_FLECK_FOAM: empty material card — skipped")
        return
    mid   = to_int(f1[0])
    rho   = to_float(f1[1]) if len(f1) > 1 else 0.0
    E     = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu    = to_float(f1[3]) if len(f1) > 3 else 0.0
    alpha = to_float(f1[4]) if len(f1) > 4 else 0.0
    gamma = to_float(f1[5]) if len(f1) > 5 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    epsd   = to_float(f2[0]) if f2        else 0.0
    alpha2 = to_float(f2[1]) if len(f2) > 1 else 0.0
    beta   = to_float(f2[2]) if len(f2) > 2 else 0.0
    sigp   = to_float(f2[3]) if len(f2) > 3 else 0.0
    derfi  = to_float(f2[4]) if len(f2) > 4 else 0.0
    cfail  = to_float(f2[5]) if len(f2) > 5 else 0.0
    pfail  = to_float(f2[6]) if len(f2) > 6 else 0.0
    num    = to_int(f2[7]) if len(f2) > 7 and f2[7].strip() else 1000
    state.mat_deshpande_fleck[mid] = MatDeshpandeFleckFoam(
        mid, title, rho, E, nu, alpha, gamma, epsd, alpha2, beta, sigp,
        derfi, cfail, pfail, num)


def handle_mat_hill_foam(block: Block, state: ConversionState) -> None:
    """*MAT_HILL_FOAM (MAT_177) → /MAT/LAW62 — constants branch (LCID = 0).

    LS-DYNA cards (Manual Vol II R17 p.2-1216; the shipped Keyword971
    mat_177.cfg CARD(...,LSDYNA_K,LSDYNA_N,LSD_MU,...) states the SAME
    order — field 4 is N, field 5 is MU):
      Card1: MID RO K N MU LCID FITTYPE LCSR
      Card2 (iff LCID == 0): C1..C8    Card3 (iff LCID == 0): B1..B8
      Card4 (optional, both branches): R M
    LCID > 0 selects the curve-fit branch (FITTYPE test data), for which
    /MAT/LAW62 has NO counterpart — LAW62 takes only constants (no Itab/fit
    path, hm_read_mat62.F reads no function id at all). dyna2rad produces
    NOTHING for that variant and wires the part's mat_ID to 0 silently
    (CM:9746-9750 + 140-143); k2rad skips it too but says so LOUDLY. The
    branch changes the CARD LAYOUT (no C/B cards), so the skip lives here at
    parse — the same policy as the MAT_240 option variants.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_HILL_FOAM: empty material card — skipped")
        return
    mid     = to_int(f1[0])
    rho     = to_float(f1[1]) if len(f1) > 1 else 0.0
    kbulk   = to_float(f1[2]) if len(f1) > 2 else 0.0
    n       = to_float(f1[3]) if len(f1) > 3 else 0.0
    mu      = to_float(f1[4]) if len(f1) > 4 else 0.0
    lcid    = to_int(f1[5])   if len(f1) > 5 else 0
    fittype = to_int(f1[6])   if len(f1) > 6 else 0
    lcsr    = to_int(f1[7])   if len(f1) > 7 else 0
    if lcid > 0:
        state.warn(
            f"*MAT_HILL_FOAM mid={mid}: LCID={lcid} selects the curve-fit "
            f"branch (FITTYPE={fittype} test data), and /MAT/LAW62 has NO "
            "curve-fit path — unlike LAW42/LAW69 there is no Itab or function "
            "field anywhere on the card (hm_read_mat62.F reads constants "
            "only), so the Hill-series fit LS-DYNA performs internally cannot "
            "be delegated to the Radioss starter. dyna2rad emits NOTHING for "
            "this variant and silently wires the part's mat_ID to 0 "
            "(CM:9746-9750); k2rad also skips the material — every /PART "
            "referencing it has no /MAT and the starter will reject the deck. "
            "Run the fit in LS-DYNA once (the fitted C_i/B_i are echoed in "
            "d3hsp), then re-state the card with LCID=0 and the constants.")
        return
    c: List[float] = []
    b: List[float] = []
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    c = [to_float(f2[i]) if len(f2) > i else 0.0 for i in range(8)]
    b = [to_float(f3[i]) if len(f3) > i else 0.0 for i in range(8)]
    f4 = _card(raw, offset + 3, fixed=True, n=2, w=10)
    r = to_float(f4[0]) if f4        else 0.0
    m = to_float(f4[1]) if len(f4) > 1 else 0.0
    state.mat_hill_foam[mid] = MatHillFoam(
        mid, title, rho, kbulk, mu, n, lcid, fittype, lcsr, c, b, r, m)


def handle_mat_shape_memory(block: Block, state: ConversionState) -> None:
    """*MAT_SHAPE_MEMORY (*MAT_030) → /MAT/LAW71 (superelastic SMA).

    Cards (Vol II R17 pp.2-303..2-309; Keyword971_R7.1/MAT/mat_030.cfg):
      Card1: MID RO E PR [LCSS LCSSC IDPP]
      Card2: SIG_ASS SIG_ASF SIG_SAS SIG_SAF EPSL ALPHA YMRT
      Card3 (optional R7.1 FREE_CARD): LCID_AS LCID_SA

    Fixed-width w=10, like every other *MAT here: RO regularly fills its whole
    field and fuses with MID ("  301.05000E-9"), and a free split then shifts
    every value (the *MAT_187 trap).

    The four SIG_* cells are ``SCALAR_OR_OBJECT``: a NEGATIVE value is a curve
    id, not a stress. /MAT/LAW71 has one scalar per threshold, so the curve form
    cannot be carried; dyna2rad copies each cell only when ``> 0``
    (convertmats.cxx:1907-1926) and leaves the rest at 0, which the starter then
    turns into ``sig_* = 1e-20`` (hm_read_mat71.F:163-166) and immediately
    refuses with ERROR 1122 + ERROR 1123 (measured, once per material). Emitting
    that is strictly worse than not emitting it, so a curve form warn-skips the
    whole material here — the /PART then reports a dangling material id, which
    names the deck's real problem.

    Card 3 is claimed by RAW CONTIGUITY (row index offset+2), not by "the next
    non-blank line": an all-blank card 3 is a legal FREE_CARD and a scan for
    content would walk past it (the #109/#117/#119 trap).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_SHAPE_MEMORY: empty material card — skipped")
        return
    mid = to_int(f1[0])
    if mid <= 0:
        state.warn(f"*MAT_SHAPE_MEMORY '{title}': MID parsed as {mid} — "
                   "unreadable (shifted or fused fields?); material skipped.")
        return
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    e   = to_float(f1[2]) if len(f1) > 2 else 0.0
    nu  = to_float(f1[3]) if len(f1) > 3 else 0.0
    lcss  = to_int(f1[4]) if len(f1) > 4 else 0
    lcssc = to_int(f1[5]) if len(f1) > 5 else 0
    idpp  = to_int(f1[6]) if len(f1) > 6 else 0

    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    sig = [to_float(f2[i]) if len(f2) > i else 0.0 for i in range(4)]
    epsl  = to_float(f2[4]) if len(f2) > 4 else 0.0
    alpha = to_float(f2[5]) if len(f2) > 5 else 0.0
    ymrt  = to_float(f2[6]) if len(f2) > 6 else 0.0

    # Card 3: the R7.1 FREE_CARD, claimed by row index.
    lcid_as = lcid_sa = 0
    if len(raw) > offset + 2 and raw[offset + 2].strip():
        f3 = _card(raw, offset + 2, fixed=True, n=2, w=10)
        lcid_as = to_int(f3[0]) if f3 else 0
        lcid_sa = to_int(f3[1]) if len(f3) > 1 else 0

    names = ("SIG_ASS", "SIG_ASF", "SIG_SAS", "SIG_SAF")
    curve_form = [f"{n}={v:g} (curve {abs(int(v))})"
                  for n, v in zip(names, sig) if v < 0.0]
    if curve_form:
        state.warn(
            f"*MAT_SHAPE_MEMORY mid={mid}: " + ", ".join(curve_form) +
            " — a NEGATIVE transformation stress is a LOAD CURVE ID in "
            "LS-DYNA (temperature-dependent, or effective-plastic-strain "
            "dependent when LCSS is negative too; Vol II R17 p.2-305/306), and "
            "/MAT/LAW71 has ONE SCALAR slot per threshold (matl71_71.cfg: "
            "sig_sas sig_fas sig_ssa sig_fsa) with no function field anywhere "
            "on the card. The material is SKIPPED. dyna2rad copies only the "
            "positive cells (convertmats.cxx:1907-1926) and leaves the rest at "
            "0, which hm_read_mat71.F:163-166 turns into 1e-20 and then "
            "refuses with ERROR 1122 + ERROR 1123 — an unstartable deck either "
            "way, so nothing is emitted. Re-state the card with the four "
            "transformation stresses as constants for the operating "
            "temperature.")
        return

    dropped = []
    if lcss:
        dropped.append(f"LCSS={lcss} (stress-strain curve/table)")
    if lcssc:
        dropped.append(f"LCSSC={lcssc} (compression curve/table)")
    if idpp:
        dropped.append(f"IDPP={idpp} (Drucker-Prager yield flag)")
    if lcid_as:
        dropped.append(f"LCID_AS={lcid_as} (stress vs martensite fraction, "
                       "loading — it OVERWRITES SIG_ASS/SIG_ASF in LS-DYNA)")
    if lcid_sa:
        dropped.append(f"LCID_SA={lcid_sa} (stress vs martensite fraction, "
                       "unloading)")
    if dropped:
        state.warn(
            f"*MAT_SHAPE_MEMORY mid={mid} → /MAT/LAW71: dropped "
            + "; ".join(dropped) +
            ". /MAT/LAW71 is the plain Auricchio superelastic model — its card "
            "carries no function id at all (matl71_71.cfg), so a tabulated "
            "transformation law and the Drucker-Prager yield option have no "
            "slot. The four constant transformation stresses are used instead"
            + (" — where LCID_AS is present those constants are the ones "
               "LS-DYNA would have OVERWRITTEN, so the emitted plateau is the "
               "card-1 value, not the curve's." if lcid_as else "") + ".")

    state.mat_shape_memory[mid] = MatShapeMemory(
        mid, title, rho, e, nu, sig[0], sig[1], sig[2], sig[3],
        epsl, alpha, ymrt, lcss, lcssc, idpp, lcid_as, lcid_sa)


def _mat004_live_points(t: List[float]) -> int:
    """How many of ``*MAT_004``'s eight temperature slots are LIVE.

    The card is a fixed eight-slot table and states no count. Vol II R17
    p.2-177 Remark 2 requires at least two temperatures and the analysis
    terminates outside the stated range, so the temperatures are ordered; an
    unused slot is written ``0.0``, which is ALSO a legal temperature and is
    what three corpus decks put in ``T1``. The longest STRICTLY INCREASING
    prefix is therefore the only reading that separates a real point from
    padding, and it reproduces every corpus carrier: ``tempcyl.vari``
    (−1000, 0, 1000, 0, …) → 3, ``thermal-stress`` (0 … 50, 0, 0) → 6,
    ``main_steel_frame``/``ex_24`` (0, 400|1000, 0, …) → 2, the four welding
    decks (273, 493, 1273, 10000, 0, …) → 4.

    **The cfg reads it differently, and this rule is deliberately not that
    reading.** ``Keyword971/MAT/mat_004.cfg:176-207`` counts with a
    ``CARD_PREREAD``/``ArrayCount`` ladder whose tests are ``LOCAL_Tn != ""``,
    i.e. the last NON-BLANK column — a purely textual test. Every corpus
    carrier pads its unused slots with an explicit ``0.0`` rather than leaving
    them blank (``tempcyl.vari``'s ``T`` row is
    ``-1000.0  0.0  1000.0  0.0  0.0  0.0  0.0  0.0``), so that ladder would
    return **8** where this rule returns 3, and ``/FUNCT`` would get a
    non-monotonic table with five spurious points at ``T = 0``. The cfg is a
    HyperMesh import descriptor, not solver semantics (#115); the
    increasing-prefix reading is what separates padding from a stated point,
    and it can only ever DROP a slot.
    """
    n = 1
    while n < len(t) and t[n] > t[n - 1]:
        n += 1
    return n


def handle_mat_elastic_plastic_thermal(block: Block,
                                       state: ConversionState) -> None:
    """*MAT_ELASTIC_PLASTIC_THERMAL (*MAT_004) → /MAT/LAW106 +
    /THERM_STRESS/MAT.

    Cards (Vol II R17 pp.2-177..2-179; ``Keyword971/MAT/mat_004.cfg``
    resolved through the cfg overlay — the ``Keyword971_R14.1/MAT`` dir
    holds only ``M054_55.cfg``):
      Card1: MID RO
      Cards 2-7: T1..T8 / E1..E8 / PR1..PR8 / ALPHA1..ALPHA8 / SIGY1..SIGY8 /
                 ETAN1..ETAN8

    Fixed-width w=10 throughout, like every other ``*MAT`` here: ``RO``
    regularly fills its whole field and fuses with ``MID``
    (``main_steel_frame.k`` writes ``         17.85000E-9``), and a free split
    would then shift every value — the ``*MAT_187`` trap.

    The temperature-dependence tables are carried to ``/MAT/LAW106`` by
    ``writer/materials.py::_resolve_mat_law106``; this handler only reads the
    card. dyna2rad has no ``case 4:`` at all — ``convertmats.cxx:527``'s
    ``default:`` calls ``Convert1To1(..., matLawNum, ...)``, which emits
    ``/MAT/LAW4`` (HYD_JCOOK, an EOS-driven hydrodynamic law with no E(T)
    slot). It is not a usable reference for this keyword.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_ELASTIC_PLASTIC_THERMAL: empty material card — "
                   "skipped")
        return
    mid = to_int(f1[0])
    if mid <= 0:
        state.warn(f"*MAT_ELASTIC_PLASTIC_THERMAL '{title}': MID parsed as "
                   f"{mid} — unreadable (shifted or fused fields?); material "
                   "skipped.")
        return
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    rows: List[List[float]] = []
    for k in range(1, 7):
        fk = _card(raw, offset + k, fixed=True, n=8, w=10)
        rows.append([to_float(fk[i]) if len(fk) > i else 0.0
                     for i in range(8)])
    state.mat_ep_thermal[mid] = MatElasticPlasticThermal(
        mid=mid, title=title, rho=rho, t=rows[0], e=rows[1], pr=rows[2],
        alpha=rows[3], sigy=rows[4], etan=rows[5])


def handle_mat_cwm(block: Block, state: ConversionState) -> None:
    """*MAT_CWM (*MAT_270) → /MAT/LAW106 + /THERM_STRESS/MAT.

    Cards (Vol II R17 pp.2-1835..2-1840;
    ``Keyword971_R7.1/MAT/mat_270.cfg``, the newest dir that holds it):
      Card1: MID RO LCEM LCPR LCSY LCHR LCAT BETA
      Card2: TASTART TAEND TLSTART TLEND EGHOST PGHOST AGHOST EPSINI
      Card3 (optional): T2PHASE T1PHASE ANOPT POSTV DTEMP DOSPOT

    Card 3 is claimed by RAW CONTIGUITY (row index ``offset + 2``), never by
    "the next non-blank line": an all-blank optional card is legal LS-DYNA and
    a content scan walks past it into the following keyword (#109/#117/#119).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_CWM: empty material card — skipped")
        return
    mid = to_int(f1[0])
    if mid <= 0:
        state.warn(f"*MAT_CWM '{title}': MID parsed as {mid} — unreadable "
                   "(shifted or fused fields?); material skipped.")
        return

    def _g(f: List[str], i: int) -> float:
        return to_float(f[i]) if len(f) > i else 0.0

    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    rec = MatCWM(
        mid=mid, title=title, rho=_g(f1, 1),
        lcem=to_int(f1[2]) if len(f1) > 2 else 0,
        lcpr=to_int(f1[3]) if len(f1) > 3 else 0,
        lcsy=to_int(f1[4]) if len(f1) > 4 else 0,
        lchr=to_int(f1[5]) if len(f1) > 5 else 0,
        lcat=to_int(f1[6]) if len(f1) > 6 else 0,
        beta=_g(f1, 7),
        tastart=_g(f2, 0), taend=_g(f2, 1), tlstart=_g(f2, 2),
        tlend=_g(f2, 3), eghost=_g(f2, 4), pghost=_g(f2, 5),
        aghost=_g(f2, 6), epsini=_g(f2, 7))
    if len(raw) > offset + 2 and raw[offset + 2].strip():
        f3 = _card(raw, offset + 2, fixed=True, n=6, w=10)
        rec.has_card3 = True
        rec.t2phase = _g(f3, 0)
        rec.t1phase = _g(f3, 1)
        rec.anopt = _g(f3, 2)
        rec.postv = to_int(f3[3]) if len(f3) > 3 else 0
        rec.dtemp = _g(f3, 4)
        rec.dospot = to_int(f3[5]) if len(f3) > 5 else 0
    state.mat_cwm[mid] = rec


def handle_mat_vacuum(block: Block, state: ConversionState) -> None:
    """*MAT_VACUUM (*MAT_140) → /MAT/VOID (LAW0).

    Card: MID RHO. Two separate questions this answers separately.

    **The PART needs a material.** A vacuum *PART with no /MAT is starter
    ERROR 179, which is what four corpus ALE decks used to get on top of their
    LAW51 error. /MAT/VOID is a region that carries no stress at all — the same
    target a bare *MAT_NULL already takes in this converter — so the part
    resolves and contributes nothing, which is what a vacuum does.

    **The LAW51 PHASE does NOT need one.** LAW0 is not on
    ``fill_buffer_51.F:210``'s allowed list and cannot be declared as a phase
    at all (``hm_read_mat51.F:608-627``: a ``tMID <= 0`` inside the MIP rows is
    fatal, and there is no vacuum law to name instead). It does not need to be:
    ``:639-646`` checks only that the volume fractions SUM ABOVE 1, so a sum
    below one is legal and the UNDECLARED BALANCE is exactly how Radioss
    represents void. ``_resolve_ale_submaterials`` drops the entry and reduces
    MIP.

    RHO is written verbatim, 0.0 included — ``hm_read_mat.F90:1575-1583``
    exempts law 0 from ERROR 683.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_VACUUM: empty material card — skipped")
        return
    mid = to_int(f[0])
    if mid <= 0:
        state.warn(f"*MAT_VACUUM '{title}': MID parsed as {mid} — unreadable; "
                   "material skipped.")
        return
    rho = to_float(f[1]) if len(f) > 1 else 0.0
    state.mat_vacuum[mid] = MatVacuum(mid=mid, title=title, rho=rho)
    state.warn(
        f"*MAT_VACUUM {mid} -> /MAT/VOID/{mid} (LAW0, RHO_I = {rho:g}). "
        "Radioss has no vacuum MATERIAL — the word appears nowhere in the 2022 "
        "Reference or User Guide — but /MAT/VOID is a region that carries no "
        "stress at all, which is what the LS-DYNA card means, and it is the "
        "same target a bare *MAT_NULL takes here. It exists so the vacuum "
        "*PART resolves (a /PART naming no /MAT is ERROR 179). It is NOT "
        "written into the /MAT/LAW51 phase list: LAW0 is not on "
        "fill_buffer_51.F:210's allowed list, and it does not need to be — "
        "hm_read_mat51.F:639-646 checks only that the volume fractions SUM "
        "ABOVE 1, so the undeclared balance IS Radioss's void. WHAT IS LOST: "
        "in LS-DYNA the vacuum is an AMMG PHASE that the other materials "
        "advect into as they expand; here it is a separate single-material ALE "
        "region on its own mesh, so nothing flows into it. See the "
        "*ALE_MULTI-MATERIAL_GROUP warning for the whole-deck statement.")


def handle_mat_elastic_plastic_hydro(block: Block,
                                     state: ConversionState) -> None:
    """*MAT_ELASTIC_PLASTIC_HYDRO[_SPALL] (*MAT_010) → /MAT/LAW3 + its same-id
    /EOS.

    Cards (Vol II R17 pp.2-191..2-195;
    ``Keyword971/MAT/mat_010.cfg``, the newest dir that holds it):
      Card1: MID RO G SIG0 EH PC FS CHARL
      Card1a (``_SPALL`` option ONLY): A1 A2 SPALL
      Cards 2-3: EPS1..EPS16
      Cards 4-5: ES1..ES16

    The ``_SPALL`` option inserts its card BETWEEN card 1 and the EPS table, so
    the table's row index depends on the option — claimed by RAW CONTIGUITY
    from the option flag, never by scanning for the next non-blank row
    (#109/#117/#119: an all-zero EPS row is legal and a content scan walks past
    it into the following keyword).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_ELASTIC_PLASTIC_HYDRO: empty material card — skipped")
        return
    mid = to_int(f1[0])
    if mid <= 0:
        state.warn(f"*MAT_ELASTIC_PLASTIC_HYDRO '{title}': MID parsed as "
                   f"{mid} — unreadable (shifted or fused fields?); material "
                   "skipped.")
        return

    def _g(f: List[str], i: int) -> float:
        return to_float(f[i]) if len(f) > i else 0.0

    # ``_SPALL`` is NOT a trailing _ID/_TITLE/_SUBTITLE, so parser.
    # _split_keyword leaves it IN the keyword rather than moving it into
    # block.options — the spelling itself is the flag.
    spall_option = "SPALL" in block.keyword.upper()
    row = offset + 1
    a1 = a2 = spall = 0.0
    if spall_option:
        fs_card = _card(raw, row, fixed=True, n=3, w=10)
        a1, a2, spall = _g(fs_card, 0), _g(fs_card, 1), _g(fs_card, 2)
        row += 1
    eps: List[float] = []
    es: List[float] = []
    for k in range(2):
        fk = _card(raw, row + k, fixed=True, n=8, w=10)
        eps += [_g(fk, i) for i in range(8)]
    for k in range(2):
        fk = _card(raw, row + 2 + k, fixed=True, n=8, w=10)
        es += [_g(fk, i) for i in range(8)]
    state.mat_ep_hydro[mid] = MatElasticPlasticHydro(
        mid=mid, title=title, rho=_g(f1, 1), g=_g(f1, 2), sig0=_g(f1, 3),
        eh=_g(f1, 4), pc=_g(f1, 5), fs=_g(f1, 6), charl=_g(f1, 7),
        eps=eps, es=es, spall_option=spall_option, a1=a1, a2=a2, spall=spall)


def _material_refused(keyword: str, what: str, why: str):
    """Build a handler that RECOGNIZES a material, records its MID and refuses
    it by name.

    A refused material is not the same thing as an unread one. Leaving the
    keyword in ``skipped_keywords`` says only "k2rad does not know this card";
    recording it here says WHICH law it is, WHY no Radioss counterpart exists,
    and — through ``writer/materials.py::_warn_refused_materials``, which runs
    once the mesh is parsed — exactly which ``/PART``s and how many elements
    are left without a material by the refusal. That is the actionable half:
    the starter's own answer is ``ERROR 179`` naming one part at a time.

    The MID is read with the same fixed-width w=10 card-1 slice every ``*MAT``
    handler uses, so a fused ``MID``+``RO`` field cannot shift it.
    """
    def _h(block: Block, state: ConversionState) -> None:
        seen = block.keyword or keyword
        offset = _title_offset(block)
        f1 = _card(block.raw, offset, fixed=True, n=8, w=10)
        mid = to_int(f1[0]) if f1 and f1[0].strip() else 0
        if mid > 0:
            state.refused_materials[mid] = (seen, what, why)
        state.note_recognized_not_emitted(
            seen,
            f"{what} — no /MAT written. {why}. The *PART(s) on this material "
            "therefore have none, which the starter answers with ERROR 179 "
            "(MATERIAL ID DOES NOT EXIST); the parts and element counts are "
            "named in the conversion warnings.")
    return _h


#: The three ``*MAT`` families of the R14 ERROR-179 census that have NO
#: expressible Radioss counterpart at ``/BEGIN 2022``. Each row is
#: (what the law is, why nothing can carry it) — refused BY NAME rather than
#: left in the unrecognized-keyword list, and never fitted into a nearby law:
#: a fit is an invented value (#124), and a converted deck that terminates
#: normally on the wrong constitutive law is worse than a deck that refuses
#: (#122).
_REFUSED_MATERIALS = {
    ("MAT_INV_HYPERBOLIC_SIN", "MAT_102"): (
        "the inverse-hyperbolic-sine hot-forming flow law (*MAT_102)",
        "Vol II R17 p.2-729 Remark 1 gives the flow stress as "
        "sigma = (1/alpha)*arcsinh[(Z/A)^(1/N)] with the Zener-Hollomon "
        "parameter Z = max(eps_dot, EPS0)*exp(Q/(G*T)). No Radioss law at "
        "/BEGIN 2022 has that form: the sinh rate law exists only inside "
        "/MAT/LAW100 (viscsinh.F:63, (sinh(B0*tau))^EXPN — the parallel "
        "rheological framework's hyperelastic-network polymer law, with no "
        "exp(Q/GT) cell) and /MAT/LAW101 (sigeps101.F:836, the Bouvard "
        "semi-crystalline POLYMER model), and the Garofalo/Norton creep law "
        "that carries it properly is /MAT/LAW129 crp_law = 2, first available "
        "in radioss2025. /MAT/LAW103 (Hensel-Spittel, radioss2020, SOLID+SPH) "
        "is the closest 2022 hot-forming law but is a FIT, not a mapping: "
        "fitting A0, m1..m5, m7 to the arcsinh curve would invent every "
        "coefficient, so it is named here as the manual escape route and NOT "
        "done automatically"),
    ("MAT_ACOUSTIC", "MAT_090"): (
        "the acoustic pressure-formulation element material (*MAT_090)",
        "it exists for *FREQUENCY_DOMAIN_ACOUSTIC_BEM / _FEM and "
        "*FREQUENCY_DOMAIN_SSD, and OpenRadioss has neither an acoustic "
        "pressure element nor a frequency-domain solver — the whole analysis, "
        "not just the material, has no counterpart, and its engine "
        "eigensolver is a compiled-out stub on this build. Converting the "
        "material alone would leave a deck with nothing to solve"),
    ("MAT_GAS_MIXTURE", "MAT_148"): (
        "the multi-species ALE gas mixture (*MAT_148)",
        "its whole mechanism is *SECTION_POINT_SOURCE_MIXTURE + "
        "*INITIAL_GAS_MIXTURE — an airbag-inflator point-source injection into "
        "an ALE mesh — and OpenRadioss has none of the three. /MAT/GAS "
        "(mat_gas.cfg, radioss120) is a /MONVOL gas definition, not an ALE "
        "material. A single perfect gas as a LAW51 phase WOULD be expressible "
        "as /MAT/LAW6 + /EOS/POLYNOMIAL with C4 = C5 = gamma-1 (Radioss "
        "RefGuide p.1112, 'Modeling Technique with Polynomial EOS'), but "
        "converting the material alone would leave the deck with no injection "
        "source and no way to reach the LS-DYNA result, so the whole family "
        "is refused rather than half of it"),
    ("MAT_FRAZER_NASH_RUBBER_MODEL", "MAT_031"): (
        "the Frazer-Nash hyperelastic rubber model (*MAT_031)",
        "the card states no constants to map when a least-squares fit is "
        "requested: Vol II R17 p.2-312 says the energy terms to include are "
        "'flagged by setting their corresponding coefficients to unity', so "
        "C100/C110/C010/C020 = 1.0 beside SGL/SW/ST and an LCID are INCLUSION "
        "FLAGS plus a request for LS-DYNA's own internal fit of "
        "U = C100*I1 + C200*I1^2 + ... + f(J) to a uniaxial force-vs-gauge-"
        "length curve — there is no value to carry, and reimplementing that "
        "fit is not a conversion. Even a direct-constants card is not a "
        "1:1 map: Frazer-Nash's I1, I2 are invariants of the GREEN-ST-VENANT "
        "strain while Radioss's polynomial hyperelastic (/MAT/LAW100 "
        "PPOLYNOMIAL, available at 2022) uses the REDUCED Cauchy-Green "
        "invariants — the algebraic bridge I1^E = (I1^C-3)/2, "
        "I2^E = (I2^C-2*I1^C+3)/4 is exact but the J^(-2/3) reduction breaks "
        "it for compressible response, and the I1^4 term needs an order-4 "
        "polynomial"),
}


def _scalar_or_curve(f: List[str], i: int, default: float,
                     state: Optional[ConversionState] = None,
                     field: str = "", fixed_positive: bool = False,
                     where: str = ""):
    """Read an LS-DYNA ``SCALAR_OR_FUNCTION`` / ``SCALAR_OR_OBJECT`` cell.

    ``cfgio/MODEL_IO/meci_data_reader.cpp:6845-6848`` states the rule verbatim:
    *"this is Dyna specific: if the value is negative, its abs value is the ID
    of an object"*. Returns ``(scalar, curve_id)`` — exactly one of the two is
    meaningful, and a BLANK cell takes *default* rather than 0 (blank is not
    always "no factor": SFR/SVS/SVR/SV/TL/TV default to 1.0).

    *fixed_positive* is the muscle family's second rule, and it is NOT the same
    as a blank default: for ``SFR``/``SVS``/``SVR`` (Vol II R17 p.2-1072) and
    ``SV``/``TL``/``TV`` (p.2-2096) the manual reads *"LT.0.0: Absolute value
    gives load curve ID. **GE.0.0: Constant value of 1.0 is used**"* — LS-DYNA
    DISCARDS whatever positive number the deck writes and uses 1.0. Reading the
    cell as a coefficient makes a deck stating ``SFR = 2`` run at twice the rate
    normalisation it means. ``ALM``/``A`` are the contrast in the same family
    (*"GE.0.0: Constant value of ALM is used"*), so they keep their scalar.
    """
    if len(f) <= i or not f[i].strip():
        return default, 0
    v = to_float(f[i])
    if v < 0.0:
        return default, int(abs(v))
    if fixed_positive:
        if state is not None and v not in (0.0, 1.0):
            # `where` carries the deck-specific prefix ("*MAT_MUSCLE mid=1: ")
            # and `field` is the BARE cell name, so the quoted manual sentence
            # stays a manual sentence instead of repeating the prefix inside
            # its own quotation marks.
            state.warn(
                f"{where}{field}={v:g} states a positive constant, and LS-DYNA "
                f"DISCARDS it: '{field} ... GE.0.0: Constant value of 1.0 is "
                "used' (Vol II R17 p.2-1072 for the *MAT_156 cells, p.2-2096 "
                "for the *MAT_S15 ones). Only a NEGATIVE value is meaningful "
                "there — it names a load curve. 1.0 is used, as LS-DYNA does; "
                "write the value as a negative curve id if a real factor was "
                "meant.")
        return default, 0
    return v, 0


def handle_mat_muscle(block: Block, state: ConversionState) -> None:
    """*MAT_MUSCLE (*MAT_156) → /PROP/TYPE46 (SPR_MUSCLE) + /SPRING.

    Cards (Vol II R17 pp.2-1071..2-1074; Keyword971_R6.1/MAT/mat_156.cfg:
    ``MID RO SNO SRM PIS SSM CER DMP`` / ``ALM SFR SVS SVR SSP``, the last five
    all ``SCALAR_OR_FUNCTION``):

      sigma = PIS*a(t)*f(l/l_orig)*g(eps_bar_dot) + PIS*h(l/l_orig)
              + DMP*(l/l_orig)*eps_dot
      a = ALM, f = SVS, g = SVR, h = SSP,
      l_orig = l0/SNO, eps_bar_dot = (l/l_orig)*eps_dot/(SFR*SRM)

    *"This is Material Type 156 for truss elements"* (p.2-1071), i.e. a
    *SECTION_BEAM with ELFORM 3. No /MAT is written at all — the whole law
    lives in the /PROP/TYPE46 of the part, exactly like the *MAT_Sxx spring
    family, so which parts it claims is decided by the PROPERTY those parts
    carry (writer/common.py::_muscle_beam_pids).

    Fixed-width w=10: RO fills its whole field and fuses with MID.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_MUSCLE: empty material card — skipped")
        return
    mid = to_int(f1[0])
    if mid <= 0:
        state.warn(f"*MAT_MUSCLE '{title}': MID parsed as {mid} — unreadable "
                   "(shifted or fused fields?); material skipped.")
        return
    rho = to_float(f1[1]) if len(f1) > 1 else 0.0
    # SNO is the INITIAL STRETCH RATIO l0/l_orig (cfg: "Initial stretch
    # ratio"); a blank one is 1.0, not 0 — a zero would divide by zero in
    # l_orig = l0/SNO.
    sno = _ffield(f1, 2, 1.0) or 1.0
    srm = to_float(f1[3]) if len(f1) > 3 else 0.0
    pis = to_float(f1[4]) if len(f1) > 4 else 0.0
    ssm = to_float(f1[5]) if len(f1) > 5 else 0.0
    cer = to_float(f1[6]) if len(f1) > 6 else 0.0
    dmp = to_float(f1[7]) if len(f1) > 7 else 0.0

    f2 = _card(raw, offset + 1, fixed=True, n=5, w=10)
    alm, alm_l = _scalar_or_curve(f2, 0, 0.0)
    # SFR/SVS/SVR: "GE.0.0: Constant value of 1.0 is used" (Vol II R17
    # p.2-1072) — the SCALAR ITSELF is discarded, so the constant branch is
    # always 1.0 whatever number the deck writes. SSP is the odd one out
    # ("EQ.0.0: Exponential function is used. GT.0.0: Constant value of 0.0"),
    # so its scalar must survive to tell 0 from positive.
    where = f"*MAT_MUSCLE mid={mid}: "
    sfr, sfr_l = _scalar_or_curve(f2, 1, 1.0, state,
                                    "SFR", True, where)
    svs, svs_l = _scalar_or_curve(f2, 2, 1.0, state,
                                    "SVS", True, where)
    svr, svr_l = _scalar_or_curve(f2, 3, 1.0, state,
                                    "SVR", True, where)
    ssp, ssp_l = _scalar_or_curve(f2, 4, 0.0)
    state.mat_muscle[mid] = MatMuscle(
        mid, title, rho, sno, srm, pis, ssm, cer, dmp,
        alm, alm_l, sfr, sfr_l, svs, svs_l, svr, svr_l, ssp, ssp_l)


def handle_mat_spring_muscle(block: Block, state: ConversionState) -> None:
    """*MAT_SPRING_MUSCLE (*MAT_S15) → /PROP/TYPE46 (SPR_MUSCLE) + /SPRING.

    Cards (Vol II R17 pp.2-2095..2-2099; Keyword971_R13.0/MAT/SDMAT15.cfg:
    ``MID L0 VMAX SV A FMAX TL TV`` / ``FPE LMAX KSH``, with SV/A/TL/TV/FPE all
    ``SCALAR_OR_OBJECT``):

      F_M = F_PE + a(t)*F_max*f_TL(L)*f_TV(V),
      L = L_M/L0,  V = V_M/(V_max*S_v)

    A *SECTION_DISCRETE material, so it lands on the discrete-spring side of
    the same /PROP/TYPE46 writer. No /MAT is written.

    Blank defaults are NOT zero (p.2-2096): L0 1.0, SV 1.0, TL 1.0, TV 1.0,
    FPE 0.0 — reading them as 0 would give a zero-length reference, a zero
    velocity scale and a muscle that produces nothing.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_SPRING_MUSCLE: empty material card — skipped")
        return
    mid = to_int(f1[0])
    if mid <= 0:
        state.warn(f"*MAT_SPRING_MUSCLE '{title}': MID parsed as {mid} — "
                   "unreadable (shifted or fused fields?); material skipped.")
        return
    l0 = _ffield(f1, 1, 1.0) or 1.0
    vmax = to_float(f1[2]) if len(f1) > 2 else 0.0
    # SV/TL/TV: "GE.0.0: Constant value of 1.0 is used" (Vol II R17 p.2-2096),
    # i.e. the positive scalar is DISCARDED. A is the contrast on the same
    # card — "GE.0.0: Constant value of A is used" — so it keeps its value.
    where = f"*MAT_SPRING_MUSCLE mid={mid}: "
    sv, sv_l = _scalar_or_curve(f1, 3, 1.0, state,
                                  "SV", True, where)
    a, a_l = _scalar_or_curve(f1, 4, 0.0)
    fmax = to_float(f1[5]) if len(f1) > 5 else 0.0
    tl, tl_l = _scalar_or_curve(f1, 6, 1.0, state,
                                  "TL", True, where)
    tv, tv_l = _scalar_or_curve(f1, 7, 1.0, state,
                                  "TV", True, where)

    f2 = _card(raw, offset + 1, fixed=True, n=3, w=10)
    fpe, fpe_l = _scalar_or_curve(f2, 0, 0.0)
    lmax = to_float(f2[1]) if len(f2) > 1 else 0.0
    ksh = to_float(f2[2]) if len(f2) > 2 else 0.0
    state.mat_spring_muscle[mid] = MatSpringMuscle(
        mid, title, l0, vmax, sv, sv_l, a, a_l, fmax,
        tl, tl_l, tv, tv_l, fpe, fpe_l, lmax, ksh)


def handle_mat_add_thermal_expansion(block: Block,
                                     state: ConversionState) -> None:
    """*MAT_ADD_THERMAL_EXPANSION → /THERM_STRESS/MAT (+ /HEAT/MAT).

    One card (Vol II R17 pp.2-146..2-148), 7 or 8 fields:
      PID LCID MULT LCIDY MULTY LCIDZ MULTZ [TREF]

    The shipped Keyword971 ADD_THERMAL_EXPANSION.cfg declares only SEVEN cells
    (``PID LCID MULT LCIDY MULTY LCIDZ MULTZ``) while the r14 verification decks
    write eight — so the count is read from the CARD, not assumed: an 8-field
    layout carries TREF (the secant-approach switch) and a 7-field one does not.
    Both spellings occur in the corpus, and a handler that assumed either would
    mis-read the other (the #127 "parse only the fields the keyword defines"
    rule, run the other way round).

    ``PID`` GT.0 is a part id; LT.0 makes ``|PID|`` a MATERIAL id — a form the
    dyna2rad reader cannot even parse (its cfg types the cell
    ``VALUE(COMPONENT)`` and the whole deck dies with ERROR 109999). k2rad reads
    it and stores it as a material reference.

    Nothing is decided here: which materials end up with a /THERM_STRESS/MAT,
    whether one has to be split off a shared MID, and what the coefficient
    function looks like are all resolved in writer/thermal.py, which is the one
    place that can see the whole deck.
    """
    offset = _title_offset(block)
    raw = block.raw
    idx = offset
    while idx < len(raw):
        line = raw[idx]
        idx += 1
        if not line.strip():
            continue
        f = _card(raw, idx - 1, fixed=True, n=8, w=10)
        pid = to_int(f[0])
        if pid == 0:
            state.warn("*MAT_ADD_THERMAL_EXPANSION: card with no PID — "
                       "skipped.")
            continue
        # The 8th cell exists only in the r14+ layout. Presence is decided on
        # the CARD, never on the value: a blank TREF and an absent TREF are
        # different statements about the card's release. The fixed-width test
        # is the raw line reaching into columns 71-80; a comma- or free-format
        # card is far shorter than that, so an eighth TOKEN counts too — the
        # flag only ever gates the secant-approach warning, and losing it on a
        # free-format deck would convert a secant card as incremental silently.
        data = _strip_inline_comment(line)
        has_tref = len(data.rstrip()) > 70 or len(f) > 7 and f[7].strip() != ""
        state.mat_add_thermal_expansion.append(MatAddThermalExpansion(
            pid=pid,
            lcid=to_int(f[1]) if len(f) > 1 else 0,
            mult=to_float(f[2]) if len(f) > 2 else 0.0,
            lcidy=to_int(f[3]) if len(f) > 3 else 0,
            multy=to_float(f[4]) if len(f) > 4 else 0.0,
            lcidz=to_int(f[5]) if len(f) > 5 else 0,
            multz=to_float(f[6]) if len(f) > 6 else 0.0,
            tref=to_float(f[7]) if len(f) > 7 else 0.0,
            has_tref=has_tref))


def handle_mat_thermal_isotropic(block: Block, state: ConversionState) -> None:
    """*MAT_THERMAL_ISOTROPIC (T01) → the /HEAT/MAT values of every part whose
    *PART TMID names it.

    Cards (Vol II R17 p.3-2):
      Card1: TMID TRO TGRLC TGMULT TLAT HLAT
      Card2: HC TC

    ``TRO`` EQ.0 → the structural density. ``HC`` is the specific heat per unit
    MASS and ``TC`` the thermal conductivity, so Radioss's VOLUMETRIC
    ``RHO0_CP`` is ``(TRO or RO)·HC`` and ``AS`` is ``TC``. Units pass straight
    through — k2rad never rescales (``--units`` only labels the /BEGIN card), so
    a consistent LS-DYNA deck stays consistent.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_THERMAL_ISOTROPIC: empty card — skipped")
        return
    tmid = to_int(f1[0])
    if tmid <= 0:
        state.warn(f"*MAT_THERMAL_ISOTROPIC '{title}': TMID parsed as {tmid} — "
                   "unreadable; card skipped.")
        return
    f2 = _card(raw, offset + 1, fixed=True, n=2, w=10)
    state.mat_thermal_isotropic[tmid] = MatThermalIsotropic(
        tmid=tmid, title=title,
        tro=to_float(f1[1]) if len(f1) > 1 else 0.0,
        tgrlc=to_int(f1[2]) if len(f1) > 2 else 0,
        tgmult=to_float(f1[3]) if len(f1) > 3 else 0.0,
        tlat=to_float(f1[4]) if len(f1) > 4 else 0.0,
        hlat=to_float(f1[5]) if len(f1) > 5 else 0.0,
        hc=to_float(f2[0]) if f2 else 0.0,
        tc=to_float(f2[1]) if len(f2) > 1 else 0.0)


def handle_mat_thermal_orthotropic(block: Block,
                                   state: ConversionState) -> None:
    """*MAT_THERMAL_ORTHOTROPIC (T02) → /HEAT/MAT when K1 == K2 == K3.

    Cards (Vol II R17 p.3-4):
      Card1: TMID TRO TGRLC TGMULT AOPT TLAT HLAT
      Card2: HC K1 K2 K3
      Card3: XP YP ZP A1 A2 A3
      Card4: D1 D2 D3

    Note ``AOPT`` sits in field 5 here, where the isotropic card has ``TLAT``:
    the two layouts are NOT the same card with an extra column, so the fields
    are read positionally against this page and not against T01's.

    Cards 3 and 4 (the AOPT geometry) are read only far enough to be reported
    as dropped — /HEAT/MAT has no material-axis concept at all.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_THERMAL_ORTHOTROPIC: empty card — skipped")
        return
    tmid = to_int(f1[0])
    if tmid <= 0:
        state.warn(f"*MAT_THERMAL_ORTHOTROPIC '{title}': TMID parsed as {tmid} "
                   "— unreadable; card skipped.")
        return
    f2 = _card(raw, offset + 1, fixed=True, n=4, w=10)
    state.mat_thermal_ortho[tmid] = MatThermalOrthotropic(
        tmid=tmid, title=title,
        tro=to_float(f1[1]) if len(f1) > 1 else 0.0,
        tgrlc=to_int(f1[2]) if len(f1) > 2 else 0,
        tgmult=to_float(f1[3]) if len(f1) > 3 else 0.0,
        aopt=to_float(f1[4]) if len(f1) > 4 else 0.0,
        tlat=to_float(f1[5]) if len(f1) > 5 else 0.0,
        hlat=to_float(f1[6]) if len(f1) > 6 else 0.0,
        hc=to_float(f2[0]) if f2 else 0.0,
        k1=to_float(f2[1]) if len(f2) > 1 else 0.0,
        k2=to_float(f2[2]) if len(f2) > 2 else 0.0,
        k3=to_float(f2[3]) if len(f2) > 3 else 0.0)


def handle_mat_thermal_isotropic_td(block: Block,
                                    state: ConversionState) -> None:
    """*MAT_THERMAL_ISOTROPIC_TD (T03) and _TD_LC (T10) → /HEAT/MAT by FIT.

    ``_TD`` cards (Vol II R17 p.3-7), *"a minimum of two and a maximum of eight
    data points"*:
      Card1: TMID TRO TGRLC TGMULT TLAT HLAT
      Card2: T1..T8      Card3: C1..C8 (specific heat)   Card4: K1..K8

    ``_TD_LC`` (p.3-37) replaces cards 2-4 with
      Card2: HCLC TCLC HCHSV TCHSV TGHSV
    where ``HCLC``/``TCLC`` are curve ids. Only the IDS are read here; the
    curves are SAMPLED in the writer prepass (``_sample_td_lc_curves``),
    because a ``*DEFINE_CURVE`` may sit anywhere in the deck — including AFTER
    this card, which dispatch has not reached yet. Sampling at parse time made
    a deck whose curves follow the material come out with no conductivity at
    all.

    **Why a fit is expressible at all.** ``/HEAT/MAT``'s conduction really is
    the linear ``AS + BS*T_element`` and nothing more — ``stherm.F:82/104``,
    ``s4therm.F:67/84``, ``s10therm.F:61/81``, ``cbatherm.F:61/67``,
    ``pforc3.F:382`` all read ``PM(75)``/``PM(76)`` alone. (The two-segment
    ``below/above T1`` form in ``dttherm.F90:102-106`` and
    ``mqviscb.F:653-657`` is the thermal TIME-STEP routine, gated on
    ``IDT_THERM == 1``; it never touches the heat flow.) So a tabulated
    ``k(T)`` is carried by a least-squares LINE whose worst deviation the
    writer states, and the capacity ``RHO0_CP`` is one constant with no
    temperature dependence at all — that is the loss this card takes.

    A non-zero ``HCHSV``/``TCHSV``/``TGHSV`` makes the property a function of a
    MECHANICAL history variable (stress component, plastic strain, a law's own
    history slot). Nothing in Radioss can express that, so the record is stored
    with empty tables and ``lc_hsv`` set, and the writer drops it by name.
    """
    kw = block.keyword
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn(f"*{kw}: empty card — skipped")
        return
    tmid = to_int(f1[0])
    if tmid <= 0:
        state.warn(f"*{kw} '{title}': TMID parsed as {tmid} — unreadable; "
                   "card skipped.")
        return
    rec = MatThermalIsotropicTD(
        tmid=tmid, title=title,
        tro=to_float(f1[1]) if len(f1) > 1 else 0.0,
        tgrlc=to_int(f1[2]) if len(f1) > 2 else 0,
        tgmult=to_float(f1[3]) if len(f1) > 3 else 0.0,
        tlat=to_float(f1[4]) if len(f1) > 4 else 0.0,
        hlat=to_float(f1[5]) if len(f1) > 5 else 0.0,
        spelling=f"*{kw}",
        # *MAT_T10 IS *MAT_THERMAL_ISOTROPIC_TD_LC — Vol II R17 p.2-9's alias
        # table, and p.3-37 heads the card with BOTH names. A plain
        # `endswith("_TD_LC")` read it with the _TD layout instead: card 2's
        # `HCLC TCLC HCHSV TCHSV TGHSV` became the T1..T8 temperature row and
        # cards 3-4 (which do not exist) the C/K rows, so the whole thermal
        # material was silently lost. assembly.py's offset walker has always
        # keyed MAT_T10 on the _TD_LC layout, so the two readers disagreed.
        is_lc=kw.endswith("_TD_LC") or kw.endswith("MAT_T10"))
    if rec.is_lc:
        f2 = _card(raw, offset + 1, fixed=True, n=5, w=10)
        rec.hclc = to_int(f2[0]) if f2 else 0
        rec.tclc = to_int(f2[1]) if len(f2) > 1 else 0
        for name, idx in (("HCHSV", 2), ("TCHSV", 3), ("TGHSV", 4)):
            v = to_int(f2[idx]) if len(f2) > idx else 0
            if v:
                rec.lc_hsv = (name, v)
                break
    else:
        rows = []
        for r in range(3):
            rows.append(_card(raw, offset + 1 + r, fixed=True, n=8, w=10))
        n = 0
        for j in range(8):
            if len(rows[0]) > j and rows[0][j].strip():
                n = j + 1
        rec.temps = [to_float(rows[0][j]) for j in range(n)]
        rec.cps = [to_float(rows[1][j]) if len(rows[1]) > j else 0.0
                   for j in range(n)]
        rec.ks = [to_float(rows[2][j]) if len(rows[2]) > j else 0.0
                  for j in range(n)]
    state.mat_thermal_iso_td[tmid] = rec


def handle_control_thermal_solver(block: Block,
                                  state: ConversionState) -> None:
    """*CONTROL_THERMAL_SOLVER — two cells map, the rest are named drops.

    Card 1 is ``ATYPE PTYPE SOLVER <cgtol> GPT EQHEAT FWORK SBC`` (Vol I R17
    p.12-573). Field 4 is the OBSOLETE ``CGTOL`` column — Remark 11 removed it
    at R12 but the column stays, so it is skipped rather than read: the
    hot-stamping example on p.12-567 prints the header
    ``atype ptype solver cgtol gpt eqheat fwork sbc`` with that cell blank.

    Card 2 is read only when it exists, and its layout depends on SOLVER
    (2a for != 17, 2b for == 17). Card 3 is ``MXDMP DTVF VARDEN - NCYCL``.

    Only ``FWORK`` and ``TSF`` reach a card; ``SBC`` becomes a CROSS-CHECK
    against the Stefan-Boltzmann constant the /RADIATION reader derives from
    the emitted ``/BEGIN`` unit line (``hm_read_radiation.F:140-142``:
    ``SIGMA = STEFBOLTZ*FAC_T**3/FAC_M``). The per-field verdicts are written
    by the writer, which is the only place that knows whether a thermal solve
    is armed at all.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    rec = ControlThermalSolver(
        atype=to_int(f1[0]) if f1 else 0,
        ptype=to_int(f1[1]) if len(f1) > 1 else 0,
        solver=to_int(f1[2]) if len(f1) > 2 else 0,
        gpt=to_int(f1[4]) if len(f1) > 4 else 0,
        eqheat=_ffield(f1, 5, 1.0),
        fwork=_ffield(f1, 6, 1.0),
        sbc=to_float(f1[7]) if len(f1) > 7 else 0.0,
        # Recorded for the message only: a BLANK FWORK means 1.0 (p.12-573's
        # Card 1 Default row prints `1.` under it), so the physics does NOT
        # branch on whether the cell was typed — see writer/thermal._efrac.
        has_fwork=bool(len(f1) > 6 and f1[6].strip()))
    # Cards 2 and 3 are OPTIONAL and claimed by RAW CONTIGUITY (row index), not
    # by "the next non-blank row": an all-blank card 2 is legal (every cell
    # defaults) and a "next non-blank" walk would read card 3's cells into card
    # 2's slots — the #109/#117/#119 rule.
    i2 = offset + 1
    if i2 < len(raw):
        rec.has_card2 = True
        f2 = _card(raw, i2, fixed=True, n=8, w=10)
        rec.msglvl = to_int(f2[0]) if f2 else 0
        rec.abstol = to_float(f2[2]) if len(f2) > 2 else 0.0
        rec.reltol = to_float(f2[3]) if len(f2) > 3 else 0.0
        if rec.solver == 17:
            rec.ninner = to_int(f2[1]) if len(f2) > 1 else 0
            rec.nouter = to_int(f2[4]) if len(f2) > 4 else 0
        else:
            rec.maxitr = to_int(f2[1]) if len(f2) > 1 else 0
            rec.omega = to_float(f2[4]) if len(f2) > 4 else 0.0
            rec.tsf = to_float(f2[7]) if len(f2) > 7 else 0.0
    i3 = offset + 2
    if i3 < len(raw):
        rec.has_card3 = True
        f3 = _card(raw, i3, fixed=True, n=5, w=10)
        rec.mxdmp = to_int(f3[0]) if f3 else 0
        rec.dtvf = to_float(f3[1]) if len(f3) > 1 else 0.0
        rec.varden = to_int(f3[2]) if len(f3) > 2 else 0
        rec.ncycl = to_int(f3[4]) if len(f3) > 4 else 0
    state.ctrl_thermal_solver = rec


def handle_control_thermal_timestep(block: Block,
                                    state: ConversionState) -> None:
    """*CONTROL_THERMAL_TIMESTEP — every field is a named drop.

    Card 1 ``TS TIP ITS TMIN TMAX DTEMP TSCP LCTS`` (Vol I R17 p.12-580).

    **Why none of the eight maps.** They are the controls of an IMPLICIT
    thermal integration with an adaptive step: ``TIP`` picks Crank-Nicolson vs
    fully implicit, ``ITS``/``TMIN``/``TMAX`` bracket the step, and
    ``DTEMP``/``TSCP`` cut it when a temperature change is too large. Radioss
    integrates the heat equation EXPLICITLY on a lumped capacity
    (``tempur.F:51``: ``TEMP(N) = TEMP(N) + FTHE(N)/MCP(N)``); its thermal step
    is the conduction STABILITY limit ``DTFACTHERM · ½·Lc²·ρCp / max(k,1e-20)``
    (``dttherm.F90:116``, ``mqviscb.F:666``), and the only user cell is the
    dimensionless factor — which the engine reads from ``/DT/THERM``, and only
    in thermal-ONLY mode. There is no step to set, no minimum, no maximum and
    no adaptivity to configure, so mapping any of these onto ``DTFACTHERM``
    would put a physical time into a dimensionless scale factor.

    The card is not silently dropped: the writer names all eight, and the three
    ``LT.0`` cells plus ``LCTS`` are curve references that the
    *INCLUDE_TRANSFORM walker must still offset even though nothing is emitted
    — which is exactly why this handler parses them at all.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    named = []
    for i, name in enumerate(("TS", "TIP", "ITS", "TMIN", "TMAX", "DTEMP",
                              "TSCP", "LCTS")):
        if len(f) > i and f[i].strip():
            named.append(f"{name}={f[i].strip()}")
    detail = ", ".join(named) if named else "all cells blank (defaults)"
    state.note_recognized_not_emitted(
        "CONTROL_THERMAL_TIMESTEP",
        f"the thermal time-step controls ({detail}) — no card written, and "
        "NOT ONE of the eight fields has a counterpart. They configure an "
        "IMPLICIT thermal integration with an adaptive step (TIP = "
        "Crank-Nicolson vs fully implicit; ITS/TMIN/TMAX bracket the step; "
        "DTEMP/TSCP cut it when a step's temperature change is too large; "
        "LCTS steps to stated breakpoints). Radioss integrates the heat "
        "equation EXPLICITLY on a lumped capacity (tempur.F:51, "
        "TEMP += FTHE/MCP) and has no thermal matrix, no nonlinear iteration "
        "and no adaptive step: its thermal dt is the conduction STABILITY "
        "limit DTFACTHERM*0.5*Lc^2*rhoCp/max(k,1e-20) (dttherm.F90:116, "
        "mqviscb.F:666), whose only user cell is the dimensionless factor of "
        "the ENGINE card /DT/THERM — and even that is computed ONLY in "
        "thermal-only mode (both routines are gated on IDT_THERM == 1). In a "
        "COUPLED run Radioss therefore integrates the temperature at the "
        "MECHANICAL time step with no thermal stability check at all; that is "
        "the honest difference from LS-DYNA, and it is not something these "
        "cells could fix. (The registry used to name /DTTHERM as the "
        "counterpart: no such engine keyword exists — dttherm.F90 is a "
        "SUBROUTINE, and the engine keyword table at freform.F:213-232 has "
        "only 'DT' and 'THERM'.)")


def handle_control_thermal_nonlinear(block: Block,
                                     state: ConversionState) -> None:
    """*CONTROL_THERMAL_NONLINEAR — a named drop over all SEVEN fields.

    Card 1 ``REFMAX TOL DCP LUMPBC THLSTL NLTHPR PHCHPN`` (Vol I R17 p.12-571).
    The registry entry this replaces named only the first three.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=7, w=10)
    named = []
    for i, name in enumerate(("REFMAX", "TOL", "DCP", "LUMPBC", "THLSTL",
                              "NLTHPR", "PHCHPN")):
        if len(f) > i and f[i].strip():
            named.append(f"{name}={f[i].strip()}")
    detail = ", ".join(named) if named else "all cells blank (defaults)"
    state.note_recognized_not_emitted(
        "CONTROL_THERMAL_NONLINEAR",
        f"the nonlinear thermal solve's controls ({detail}) — no card "
        "written. All seven configure Newton iterations on a thermal stiffness "
        "matrix: REFMAX matrix reformations per step, TOL the temperature "
        "convergence tolerance, DCP the divergence cut factor, LUMPBC the "
        "boundary-condition lumping damper, THLSTL the line-search tolerance, "
        "NLTHPR the print level and PHCHPN the phase-change penalty. Radioss "
        "assembles NO thermal matrix and performs NO nonlinear iteration — "
        "tempur.F:48-55 is the whole integrator (TEMP += FTHE/MCP, then FTHE "
        "is zeroed) — so there is nothing for any of them to control. (The "
        "registry used to name 'the /THERM nonlinear controls': /THERM exists "
        "but carries exactly ONE cell, THEACCFACT, frethermal.F:64-70. There "
        "is no nonlinear-control family.)")


def _radiation_type_ok(state: ConversionState, kw: str, rtype: int,
                       where: str, page: str) -> bool:
    """Screen ``*BOUNDARY_RADIATION_{SET,SEGMENT}``'s TYPE cell.

    Vol I R17 p.5-117 (``_SEGMENT``: ``N1 N2 N3 N4 TYPE``) and p.5-122
    (``_SET``: ``SSID TYPE _ _ _ _ PSEROD``) both print TYPE with **Default 1**
    and list exactly one value, *"EQ.1: Radiation to environment"*. ``TYPE = 2``
    (*"Radiation within an enclosure"*) and page 5-126 belong to the SEPARATE
    ``_VF`` / ``_ENCLOSURE`` keywords, which k2rad refuses under their own
    names — so on these two spellings enclosure radiation is not even
    expressible.

    A typed ``0`` therefore takes the Default row, exactly the way ``_efrac``
    applies p.12-575's ``EQ.0.0`` rule to FWORK: a defaulted fixed-width
    integer column is ordinarily written as ``0``, and reading that as an
    unknown radiation type lost a fully convertible environment-radiation
    boundary while the log asserted a value the deck never wrote (the #130
    class — an exclusion's cited fact is itself a claim).

    Anything else quotes the value the deck ACTUALLY stated and cites the
    card's OWN page. The refusal is a ``state.warn`` rather than a
    keyword-scoped ``recognized_not_emitted`` entry: it is per RECORD, and on a
    mixed deck the keyword-scoped form listed ``BOUNDARY_RADIATION_SET`` under
    "Recognized but not emitted" while a ``/RADIATION`` built from its sibling
    record WAS in the emitted deck (measured).
    """
    if rtype in (0, 1):
        return True
    state.warn(
        f"*{kw}: TYPE={rtype} on {where} is not a value this card defines. "
        f"Vol I R17 {page} prints TYPE with Default 1 and lists exactly one "
        "value, 'EQ.1: Radiation to environment'. TYPE=2 ('Radiation within "
        "an enclosure', p.5-126) belongs to the SEPARATE "
        "*BOUNDARY_RADIATION_*_VF / _ENCLOSURE keywords, which exchange heat "
        "between segments through VIEW FACTORS and which k2rad refuses under "
        "their own names. Radioss's /RADIATION is radiation to an ENVIRONMENT "
        "temperature only (radiation.F:155: FLUX = AREA*EMISIG*(T_INF**4 - "
        "TE**4)) and there is no surface-to-surface exchange anywhere in "
        "engine/source/constraints/thermic — the record is DROPPED rather "
        "than converted into a different physical model. (A stated TYPE=0 is "
        "NOT refused: it takes the card's own Default row of 1.)")
    return False


def _boundary_segment_source(state: ConversionState, kw: str, is_set: bool,
                             f1: List[str]) -> Optional[ThermalBoundary]:
    """Card 1 of a *BOUNDARY_{FLUX,CONVECTION,RADIATION} record.

    ``_SET``      → ``SSID PSEROD``  (and ``SSID TYPE _ _ _ _ PSEROD`` for
                     RADIATION, whose PSEROD is field 7, Vol I R17 p.5-122)
    ``_SEGMENT``  → ``N1 N2 N3 N4``  (RADIATION adds ``TYPE`` in field 5)
    """
    kind = ("FLUX" if "FLUX" in kw else
            "CONVECTION" if "CONVECTION" in kw else "RADIATION")
    rec = ThermalBoundary(
        kind={"FLUX": "FLUX", "CONVECTION": "CONVEC",
              "RADIATION": "RADIATION"}[kind],
        source=f"*{kw}")
    if is_set:
        rec.ssid = to_int(f1[0]) if f1 else 0
        if kind == "RADIATION":
            rtype = to_int(f1[1]) if len(f1) > 1 and f1[1].strip() else 1
            rec.pserod = to_int(f1[6]) if len(f1) > 6 else 0
            if not _radiation_type_ok(state, kw, rtype,
                                      f"segment set {rec.ssid}", "p.5-122"):
                return None
        else:
            rec.pserod = to_int(f1[1]) if len(f1) > 1 else 0
    else:
        # POSITIONAL: a blank N3 beside a stated N4 must leave a hole, not
        # shift N4 into N3's slot. The trailing-blank / N4 = N3 triangle
        # spellings are collapsed by the writer, exactly as handle_set_segment
        # collapses them.
        rec.nodes = [to_int(f1[j]) if len(f1) > j else 0 for j in range(4)]
        if kind == "RADIATION":
            rtype = to_int(f1[4]) if len(f1) > 4 and f1[4].strip() else 1
            if not _radiation_type_ok(state, kw, rtype, "an explicit segment",
                                      "p.5-117"):
                return None
    return rec


def handle_boundary_thermal_bc(block: Block, state: ConversionState) -> None:
    """*BOUNDARY_{FLUX,CONVECTION,RADIATION}_{SEGMENT,SET} → /IMPFLUX, /CONVEC,
    /RADIATION.

    All three LS-DYNA keywords are two-card records with the same shape
    (Vol I R17 pp.5-46, 5-30, 5-117/5-122):

      card 1a (_SET)      FLUX/CONVECTION: ``SSID PSEROD``
                          RADIATION:       ``SSID TYPE _ _ _ _ PSEROD``
      card 1b (_SEGMENT)  FLUX/CONVECTION: ``N1 N2 N3 N4``
                          RADIATION:       ``N1 N2 N3 N4 TYPE``
      card 2   FLUX:       ``LCID MLC1 MLC2 MLC3 MLC4 LOC NHISV``
               CONVECTION: ``HLCID HMULT TLCID TMULT LOC``
               RADIATION:  ``FLCID FMULT TLCID TMULT LOC``
      card 3   FLUX only, ``ceil(NHISV/8)`` rows of ``HISV1..HISV8``

    **Walked in RAW PAIRS.** The manual prints one card set per keyword
    (*"Two cards are defined for each option"*), but an LS-DYNA keyword block's
    data cards repeat until the next ``*``, and this repo already reads
    ``*BOUNDARY_TEMPERATURE`` — a card with the same silence about repetition —
    one record per row. The pair is FIXED-SIZE, so a raw-contiguity walk is
    unambiguous and cannot eat a following entity: a blank card 1 (legal — the
    cells default) is claimed by row index, never by "the next non-blank row"
    (the #109/#117/#119 rule).

    The per-field verdicts (the FLUX sign flip, the h-curve refusal, the
    emissivity de-scaling) all live in the writer, which is where the unit
    system and the resolved curves are known.
    """
    kw = block.keyword
    is_set = kw.endswith("_SET")
    is_flux = "FLUX" in kw
    if not (is_set or kw.endswith("_SEGMENT")):
        # The manual heads all three keywords with a MANDATORY option
        # (*BOUNDARY_FLUX_OPTION p.5-46, *BOUNDARY_CONVECTION_OPTION p.5-30,
        # *BOUNDARY_RADIATION_OPTION1_... p.5-109), so a bare spelling is not
        # a card LS-DYNA defines. It is read as the _SEGMENT layout — which is
        # SAFE either way: a deck that meant _SET puts an SSID in the N1 cell,
        # the remaining node cells come out blank, and the writer drops the
        # record by name rather than building a one-node surface.
        state.warn(
            f"*{kw}: this keyword's OPTION suffix is MANDATORY — Vol I R17 "
            "heads the card *BOUNDARY_FLUX_OPTION / _CONVECTION_OPTION / "
            "_RADIATION_OPTION1_{OPTION2}_{OPTION3} with SEGMENT and SET as "
            "the choices — so the bare spelling is not a card the manual "
            "defines and its card 1 is ambiguous. It is read as the _SEGMENT "
            "layout (N1 N2 N3 N4); if the deck meant a segment SET, the record "
            "will be dropped by name for want of a resolvable segment. Write "
            f"*{kw}_SET or *{kw}_SEGMENT.")
    offset = _title_offset(block)
    raw = block.raw
    i = offset
    while i < len(raw):
        if not raw[i].strip() and not (i + 1 < len(raw)
                                       and raw[i + 1].strip()):
            break
        if i + 1 >= len(raw):
            state.warn(
                f"*{kw}: the last card set has a card 1 but no card 2 (the "
                "value row) — the set is incomplete and is dropped. Each set "
                "is exactly two cards (Vol I R17 pp.5-30/5-46/5-117).")
            break
        f1 = _card(raw, i, fixed=True, n=8, w=10)
        rec = _boundary_segment_source(state, kw, is_set, f1)
        f2 = _card(raw, i + 1, fixed=True, n=8, w=10)
        step = 2
        if is_flux:
            nhisv = to_int(f2[6]) if len(f2) > 6 else 0
            step += (nhisv + 7) // 8 if nhisv > 0 else 0
            if rec is not None:
                rec.lcid = to_int(f2[0]) if f2 else 0
                mlc = [to_float(f2[j]) if len(f2) > j else 0.0
                       for j in range(1, 5)]
                # /IMPFLUX splits ONE Fscale_y evenly over the segment's nodes
                # (fixflux.F:167 FLUX = FOURTH*FLUX). Per-node weights are only
                # expressible when they agree — but MLCk is "the curve
                # multiplier at node Nk" (Vol I R17 p.5-48), so which cells may
                # be compared depends on how many nodes the segments HAVE, and
                # that is only known once the writer has resolved them. The
                # whole list is carried through; the writer does the comparing.
                rec.mult = mlc[0]
                rec.mlcs = mlc
                rec.loc = to_int(f2[5]) if len(f2) > 5 else 0
                if nhisv > 0:
                    state.note_recognized_not_emitted(
                        kw,
                        f"NHISV={nhisv} makes LS-DYNA call the user "
                        "subroutine usrflux() to compute the flux (Vol I R17 "
                        "p.5-49 Remark 3). Radioss's /IMPFLUX evaluates a "
                        "/FUNCT of time and nothing else (fixflux.F:140), so "
                        "the record is DROPPED rather than converted into the "
                        "history variables' initial values alone.")
                    rec = None
        elif rec is not None:
            # HMULT -> H for /CONVEC, FMULT -> the f the writer de-scales into
            # /RADIATION's emissivity cell.
            rec.coef = to_float(f2[1]) if len(f2) > 1 else 0.0
            # field 0 is HLCID/FLCID: the h (or f) CURVE, which Radioss has no
            # slot for at all — recorded so the writer can refuse BY NAME
            # rather than silently using the constant beside it.
            rec.coef_lcid = to_int(f2[0]) if f2 else 0
            rec.lcid = to_int(f2[2]) if len(f2) > 2 else 0          # TLCID
            rec.fscale = to_float(f2[3]) if len(f2) > 3 else 0.0    # TMULT
            rec.loc = to_int(f2[4]) if len(f2) > 4 else 0
        if rec is not None:
            state.thermal_boundaries.append(rec)
        i += step


def handle_load_thermal_element(block: Block,
                                state: ConversionState) -> None:
    """*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_{BEAM,SHELL,SOLID,TSHELL}.

    ``_CONSTANT_ELEMENT_<F>``: ``EID T``          (Vol I R17 p.33-168)
    ``_VARIABLE_ELEMENT_<F>``: ``EID TS TB LCID`` (p.33-184)

    *"Element Cards. Include as many cards in this format as desired"* on both
    pages, so every row is a record.

    The OPTION suffix is MANDATORY on both keywords — p.33-162 lists
    ``CONSTANT_ELEMENT_OPTION`` and ``VARIABLE_ELEMENT_OPTION`` with
    ``BEAM/SHELL/SOLID/TSHELL`` — which is why the bare spellings the registry
    carried were eight dead entries: a real deck writes
    ``*LOAD_THERMAL_CONSTANT_ELEMENT_SHELL`` and that spelling was not
    registered at all.
    """
    kw = block.keyword
    variable = "VARIABLE" in kw
    family = kw.rsplit("_", 1)[-1]
    if family not in ("BEAM", "SHELL", "SOLID", "TSHELL"):
        # The BARE spelling. It is kept registered so it is recognised rather
        # than skipped, but it is not a card LS-DYNA defines, and falling
        # through to an empty-family lookup would blame the deck for something
        # else entirely ("the converted deck has no element elements at all",
        # printed on a deck full of elements — the #125 class).
        state.warn(
            f"*{kw}: the _OPTION suffix is MANDATORY on this keyword. Vol I "
            "R17 p.33-162 lists it as "
            + ("VARIABLE_ELEMENT_OPTION" if variable
               else "CONSTANT_ELEMENT_OPTION")
            + " with the four choices BEAM, SHELL, SOLID and TSHELL, and the "
            "card gives no other way to say which element table its EIDs are "
            "in (element ids are per-family namespaces, so an *ELEMENT_BEAM 50 "
            "and an *ELEMENT_SHELL 50 can both exist). The card is DROPPED — "
            f"write *{kw}_SOLID (or _SHELL / _BEAM / _TSHELL).")
        return
    offset = _title_offset(block)
    for i in range(offset, len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=4 if variable else 2, w=10)
        eid = to_int(f[0]) if f else 0
        if eid <= 0:
            state.warn(f"*{kw}: a card states EID={eid} — there is no element "
                       "to give a temperature to; row dropped.")
            continue
        if variable:
            state.load_thermal_elements.append(LoadThermalElement(
                source=f"*{kw}", family=family, eid=eid,
                scale=to_float(f[1]) if len(f) > 1 else 0.0,
                offset=to_float(f[2]) if len(f) > 2 else 0.0,
                lcid=to_int(f[3]) if len(f) > 3 else 0))
        else:
            state.load_thermal_elements.append(LoadThermalElement(
                source=f"*{kw}", family=family, eid=eid,
                temp=to_float(f[1]) if len(f) > 1 else 0.0))


def handle_initial_temperature(block: Block, state: ConversionState) -> None:
    """*INITIAL_TEMPERATURE_{SET|NODE} → /INITEMP on a /GRNOD.

    Card: ``NSID/NID TEMP LOC``. ``NSID = 0`` on the _SET spelling means EVERY
    node in the model. ``LOC`` picks a thick-thermal-shell surface (-1 lower,
    0 middle, +1 upper) and has no Radioss counterpart — /INITEMP sets one
    nodal temperature.
    """
    is_node = "NODE" in block.keyword.split("_")[-1:]
    offset = _title_offset(block)
    for i in range(offset, len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=3, w=10)
        sid = to_int(f[0]) if f else 0
        temp = to_float(f[1]) if len(f) > 1 else 0.0
        loc = to_int(f[2]) if len(f) > 2 else 0
        state.initial_temperatures.append(
            InitialTemperature(sid=sid, temp=temp, loc=loc, is_node=is_node))


def handle_boundary_temperature(block: Block, state: ConversionState) -> None:
    """*BOUNDARY_TEMPERATURE_{SET|NODE} → /IMPTEMP on the set.

    Card: ``NID/NSID TLCID TMULT LOC TDEATH TBIRTH`` with defaults
    ``none / 0 / 0. / 0 / 1e20 / 0.``.

    ``TLCID GT.0`` makes T a curve of time scaled by ``TMULT``; ``TLCID EQ.0``
    makes T the constant ``TMULT``. That is an OVERRIDE convention on the
    LS-DYNA side and a PRODUCT on the Radioss side (/IMPTEMP is
    ``Fscale_y · f(t)``, fixtemp.F:180-200), which is exactly the
    *AIRBAG_HYBRID A23/LCA23 class — so the constant form gets a synthesized
    two-point function rather than being paired with a zero id, which
    hm_read_imptemp.F refuses outright (ERROR 120, once per node).

    ``TMULT``'s printed default is ``0.`` and every corpus deck that names a
    curve writes ``1.0`` explicitly, so a blank TMULT BESIDE a curve is a card
    the manual does not resolve. It is resolved HERE rather than left to the
    reader: ``hm_read_imptemp.F:139`` turns a zero ``Fscale_y`` into 1.0, so
    emitting the literal zero would write a cell that means the opposite of
    what it does. 1.0 is written and the ambiguity is named.
    """
    is_node = "NODE" in block.keyword.split("_")[-1:]
    offset = _title_offset(block)
    for i in range(offset, len(block.raw)):
        if not block.raw[i].strip():
            continue
        f = _card(block.raw, i, fixed=True, n=6, w=10)
        sid = to_int(f[0]) if f else 0
        lcid = to_int(f[1]) if len(f) > 1 else 0
        tmult = to_float(f[2]) if len(f) > 2 else 0.0
        loc = to_int(f[3]) if len(f) > 3 else 0
        tdeath = _ffield(f, 4, 1.0e20)
        tbirth = to_float(f[5]) if len(f) > 5 else 0.0
        if loc:
            state.warn(
                f"*BOUNDARY_TEMPERATURE: LOC={loc} on set/node {sid} selects a "
                "thick-thermal-shell SURFACE (-1 lower, +1 upper). Radioss's "
                "/IMPTEMP imposes ONE temperature per node (fixtemp.F:180-200 "
                "writes TEMP(node)), so the through-thickness distinction is "
                "dropped — the value is imposed on the node itself.")
        scale = 1.0
        if lcid:
            if tmult:
                scale = tmult
            else:
                state.warn(
                    f"*BOUNDARY_TEMPERATURE: set/node {sid} names curve "
                    f"{lcid} but leaves TMULT blank/zero. TMULT is the "
                    "'temperature curve multiplier' with a printed default of "
                    "0. (Vol I R17 p.5-150), which literally read would impose "
                    "T = 0 everywhere — every corpus deck that uses a curve "
                    "writes 1.0 explicitly, so the card is ambiguous. It is "
                    "resolved to Fscale_y = 1.0 HERE: writing the literal zero "
                    "would rely on hm_read_imptemp.F:139 ('IF (FACY == ZERO) "
                    "FACY = FACY_DIM') turning it into 1.0 anyway, i.e. a cell "
                    "meaning the opposite of what it does. State TMULT on the "
                    ".k card if a different scale was meant.")
        state.imposed_temperatures.append(ImposedTemperature(
            source="*BOUNDARY_TEMPERATURE", sid=sid, is_node=is_node,
            lcid=lcid, scale=scale,
            const=tmult if not lcid else 0.0,
            tbirth=tbirth, tdeath=tdeath))


def _exempt_driver(state: ConversionState, kw: str, nsid: int, nsidex: int,
                   boxid: int, tse: float, tbe: float, lcide: int,
                   stated: bool) -> None:
    """The SECOND temperature a ``*LOAD_THERMAL_{CONSTANT,VARIABLE}`` card set
    states: the one the NSIDEX nodes are held at.

    The ``_E`` columns are the EXEMPTED nodes' own temperature, not an
    expansion-only field. Vol I R17 p.33-167 reads *"TE — Temperature of
    exempted nodes (optional)"* and p.33-180 *"TSE — Scaled temperature of the
    exempted nodes (optional). TBE — Base temperature of the exempted nodes
    (optional). LCIDE — Load curve ID that multiplies the scaled temperature of
    the exempted nodes (optional)"*, with the same ``T = TB + TS x f(t)``
    law (Remark 1). So the card partitions its node set in two, and Radioss can
    say exactly that: a second /IMPTEMP over the NSIDEX subset.

    Emitted only where the card states the second temperature WITHOUT a guess:

    * ``LCIDE`` given and resolvable -> ``TBE + TSE*f_LCIDE(t)``;
    * ``LCIDE`` blank and ``TSE = 0`` -> the constant ``TBE`` (the curve
      multiplies a zero scale, so which curve it would have been cannot
      matter);
    * ``LCIDE`` blank with a non-zero ``TSE`` -> NOT emitted. The manual prints
      only a down-arrow in that Default cell and never says which curve is
      meant, and inventing one would fabricate the whole exempted-node history
      (the #124 "never fabricate an unstated quantity" rule).
    """
    if not stated:
        return
    label = f"{kw}: TE/TSE/TBE/LCIDE"
    if not nsidex:
        state.warn(
            f"{label} state the temperature OF THE EXEMPTED NODES (Vol I R17 "
            "pp.33-167/33-180), but NSIDEX is blank on card 1, so this set "
            "exempts no node at all. The values have no target and are "
            "dropped.")
        return
    if lcide:
        curve = state.curves.get(lcide)
        if curve is None or len(curve.pts) < 2:
            state.warn(
                f"{label}: LCIDE={lcide} multiplies the exempted nodes' scaled "
                "temperature, but the deck defines no such *DEFINE_CURVE (or "
                "one with fewer than two points). The exempted nodes get NO "
                "driver of their own — they are left out of the imposed "
                "temperature (as the card asks) and then simply conduct, "
                "where LS-DYNA would hold them at TBE + TSE*f(t).")
            return
    elif tse:
        state.warn(
            f"{label}: TSE={tse:g} scales a curve for the exempted nodes but "
            "LCIDE is blank, and the manual states no curve for that case "
            "(the Default cell is only a down-arrow, Vol I R17 p.33-179). "
            "Guessing one would fabricate the whole exempted-node history, so "
            "no second /IMPTEMP is emitted: the exempted nodes are left out of "
            "the imposed temperature and then conduct. State LCIDE explicitly "
            "if they are meant to follow a curve.")
        return
    if lcide:
        # T_e = TBE + TSE*f_LCIDE(t) — the writer bakes the offset into a
        # synthesized copy of the curve, exactly as it does for TS/TB.
        rec = ImposedTemperature(
            source=f"{kw} (NSIDEX exempted nodes)", sid=nsid, nsidex=nsidex,
            boxid=boxid, drive_exempt=True, lcid=lcide, scale=tse, offset=tbe)
    else:
        # A pure constant: const alone carries it (the writer's constant
        # branch computes const + offset, so the offset must stay 0).
        rec = ImposedTemperature(
            source=f"{kw} (NSIDEX exempted nodes)", sid=nsid, nsidex=nsidex,
            boxid=boxid, drive_exempt=True, const=tbe, initial_temp=tbe)
    state.imposed_temperatures.append(rec)
    detail = (f"TBE={tbe:g} + TSE={tse:g} x curve {lcide}" if lcide
              else f"the constant TBE={tbe:g}")
    state.warn(
        f"{label}: the exempted nodes (*SET_NODE {nsidex}) are held at "
        f"{detail} — these columns are the EXEMPTED NODES' OWN temperature "
        "(Vol I R17 pp.33-167/33-180), not an expansion-only field. A SECOND "
        "/IMPTEMP is emitted over exactly that subset, so the card's two "
        "temperatures partition the node set the way LS-DYNA states them.")


def handle_load_thermal(block: Block, state: ConversionState) -> None:
    """*LOAD_THERMAL_{CONSTANT|LOAD_CURVE|VARIABLE}[_NODE] → /IMPTEMP (+ the
    companion /INITEMP for the temperature at t = 0).

    These are the STRUCTURAL-ONLY thermal loads: *"In a structural-only
    analysis, use *LOAD_THERMAL_OPTION to define temperatures"*
    (*BOUNDARY_TEMPERATURE, Purpose). Layouts:

      _CONSTANT           C1: NSID NSIDEX BOXID   C2: T TE
      _CONSTANT_NODE      C1: NID T
      _LOAD_CURVE         C1: LCID LCIDDR
      _VARIABLE           C1: NSID NSIDEX BOXID
                          C2: TS TB LCID TSE TBE LCIDE LCIDR LCIDEDR
      _VARIABLE_NODE      C1: NID TS TB LCID

    ``*LOAD_THERMAL_VARIABLE``'s law is ``T = TB + TS·f(t)`` (Remark 1), an
    OFFSET plus a scale. /IMPTEMP offers only ``Fscale_y·f(x)``
    (fixtemp.F:180-200), so the offset cannot be carried by a scale factor and
    the writer synthesizes ``TB + TS·f(t)`` point by point instead.

    **All four spellings REPEAT.** The manual says so for each one — *"Card
    Sets. Include as many sets consisting of the following two cards as
    desired"* (_CONSTANT p.33-166, _VARIABLE p.33-179), *"Node Cards. Include
    as many cards in this format as desired"* (_CONSTANT_NODE p.33-169,
    _VARIABLE_NODE p.33-185), *"Thermal Load Curve Cards. Include as many cards
    in this format as desired"* (_LOAD_CURVE p.33-171) — so every record is
    read, not just the first. The two CARD-SET spellings are walked by RAW
    CONTIGUITY (row index), never by "the next non-blank row": an all-blank
    card 1 is legal there (NSID defaults to *all nodes*) and skipping it would
    eat the next set's card 1 (the #109/#117/#119 rule).
    """
    kw = block.keyword
    offset = _title_offset(block)
    raw = block.raw
    is_node = kw.endswith("_NODE")

    if "LOAD_CURVE" in kw:
        for i in range(offset, len(raw)):
            if not raw[i].strip():
                continue
            f = _card(raw, i, fixed=True, n=2, w=10)
            lcid = to_int(f[0]) if f else 0
            lciddr = to_int(f[1]) if len(f) > 1 else 0
            if lciddr:
                state.warn(
                    f"*LOAD_THERMAL_LOAD_CURVE: LCIDDR={lciddr} (the DYNAMIC "
                    "RELAXATION temperature curve) is dropped — k2rad converts "
                    "no dynamic-relaxation phase, so there is no preload stage "
                    "for it to drive.")
            if lcid <= 0:
                state.warn("*LOAD_THERMAL_LOAD_CURVE: LCID is 0 — no "
                           "temperature history to impose; card dropped.")
                continue
            state.imposed_temperatures.append(ImposedTemperature(
                source="*LOAD_THERMAL_LOAD_CURVE", sid=0, lcid=lcid))
        return

    if is_node:
        # _CONSTANT_NODE "NID T" / _VARIABLE_NODE "NID TS TB LCID", one node
        # per card, as many cards as desired.
        variable = "VARIABLE" in kw
        for i in range(offset, len(raw)):
            if not raw[i].strip():
                continue
            f = _card(raw, i, fixed=True, n=4 if variable else 2, w=10)
            nid = to_int(f[0]) if f else 0
            if nid <= 0:
                state.warn(f"{kw}: a node card states NID={nid} — there is no "
                           "node to impose a temperature on; row dropped.")
                continue
            if variable:
                state.imposed_temperatures.append(ImposedTemperature(
                    source="*LOAD_THERMAL_VARIABLE_NODE", sid=nid,
                    is_node=True, lcid=to_int(f[3]) if len(f) > 3 else 0,
                    scale=to_float(f[1]) if len(f) > 1 else 0.0,
                    offset=to_float(f[2]) if len(f) > 2 else 0.0))
            else:
                t = to_float(f[1]) if len(f) > 1 else 0.0
                state.imposed_temperatures.append(ImposedTemperature(
                    source="*LOAD_THERMAL_CONSTANT_NODE", sid=nid,
                    is_node=True, const=t, initial_temp=t))
        return

    # The two CARD-SET spellings: card 1 "NSID NSIDEX BOXID", card 2 the
    # temperature. Walked in RAW PAIRS — card 1 may be entirely blank (NSID
    # defaults to all nodes), so a "next non-blank row" walk would eat the
    # following set's card 1. A pair in which BOTH rows are blank states
    # nothing at all and ends the list: that is a trailing blank line, not a
    # deck asking for T = 0 on every node.
    variable = "VARIABLE" in kw
    i = offset
    while i < len(raw):
        if not raw[i].strip() and not (i + 1 < len(raw)
                                       and raw[i + 1].strip()):
            break
        if i + 1 >= len(raw):
            state.warn(
                f"{kw}: the last card set has a card 1 but no card 2 (the "
                "temperature row) — the set is incomplete and is dropped. "
                "Each set is exactly two cards (Vol I R17 pp.33-166/33-179).")
            break
        f1 = _card(raw, i, fixed=True, n=3, w=10)
        nsid = to_int(f1[0]) if f1 else 0
        nsidex = to_int(f1[1]) if len(f1) > 1 else 0
        boxid = to_int(f1[2]) if len(f1) > 2 else 0
        if variable:
            f2 = _card(raw, i + 1, fixed=True, n=8, w=10)
            ts = to_float(f2[0]) if f2 else 0.0
            tb = to_float(f2[1]) if len(f2) > 1 else 0.0
            lcid = to_int(f2[2]) if len(f2) > 2 else 0
            tse = to_float(f2[3]) if len(f2) > 3 else 0.0
            tbe = to_float(f2[4]) if len(f2) > 4 else 0.0
            lcide = to_int(f2[5]) if len(f2) > 5 else 0
            dr = [(n, v) for n, v in
                  (("LCIDR", to_int(f2[6]) if len(f2) > 6 else 0),
                   ("LCIDEDR", to_int(f2[7]) if len(f2) > 7 else 0)) if v]
            if dr:
                state.warn(
                    "*LOAD_THERMAL_VARIABLE: "
                    + ", ".join(f"{n}={v:g}" for n, v in dr)
                    + " dropped — the _DR columns drive the DYNAMIC-RELAXATION "
                    "phase, which k2rad does not convert, so they have no "
                    "target in the emitted deck.")
            state.imposed_temperatures.append(ImposedTemperature(
                source="*LOAD_THERMAL_VARIABLE", sid=nsid, nsidex=nsidex,
                boxid=boxid, lcid=lcid, scale=ts, offset=tb))
            _exempt_driver(state, "*LOAD_THERMAL_VARIABLE", nsid, nsidex,
                           boxid, tse, tbe, lcide,
                           stated=any(len(f2) > k and f2[k].strip()
                                      for k in (3, 4, 5)))
        else:
            f2 = _card(raw, i + 1, fixed=True, n=2, w=10)
            t = to_float(f2[0]) if f2 else 0.0
            te = to_float(f2[1]) if len(f2) > 1 else 0.0
            state.imposed_temperatures.append(ImposedTemperature(
                source="*LOAD_THERMAL_CONSTANT", sid=nsid, nsidex=nsidex,
                boxid=boxid, const=t, initial_temp=t))
            _exempt_driver(state, "*LOAD_THERMAL_CONSTANT", nsid, nsidex,
                           boxid, 0.0, te, 0,
                           stated=bool(len(f2) > 1 and f2[1].strip()))
        i += 2


def handle_control_solution(block: Block, state: ConversionState) -> None:
    """*CONTROL_SOLUTION: SOLN selects the analysis type (0 structural only,
    1 thermal only, 2 coupled — Vol I R17 p.12-532).

    **SOLN = 1 IS expressible, and the old warning saying otherwise was
    wrong.** The engine card is ``/DT/THERM``:

      * ``freform.F:950-951`` sets ``GLOB_THERM%IDT_THERM = 1``;
      * ``resol.F:1738`` then calls ``BCSDTTH_COPY(..., 1)``, which writes
        ``ICODT(N) = 7`` AND ``ICODR(N) = 7`` on EVERY node — the whole mesh's
        translations and rotations are frozen for the run and restored at
        ``resol.F:9167``;
      * ``resol.F:5807-5809`` replaces the mechanical step with
        ``DT2 = GLOB_THERM%DT_THERM``, the conduction stability step;
      * ``lectur.F:696-698`` prints ``THERMAL ANALYSIS ONLY``.

    That is a thermal-only run mode, term for term. The writer emits the card
    (``_make_engine_thermal``) and states the two traps it carries — the AMS
    conflict (``freform.F:1327-1330``, a hard ``ANCMSG(301)`` + ``ARRET``) and
    the silent divergence when the thermal step is too large for a stiff
    convection boundary, since the criterion is CONDUCTION-only.

    SOLN is recorded rather than acted on here because the decision needs the
    emitted deck: a ``/DT/THERM`` on a deck with no ``/HEAT/MAT`` integrates
    nothing while freezing every DOF.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    soln = to_int(f[0]) if f else 0
    state.ctrl_solution_soln = soln
    state.ctrl_solution_present = True
    dropped = []
    # Vol I R17 p.12-532's Card 1 Default row: SOLN 0, NLQ 0, ISNAN 0,
    # LCINT 100, LCACC 0, NCDCF 1, NOCOPY 0, CRVP 0. A cell holding its OWN
    # documented default states nothing, so naming it asks the reader of a
    # plain structural deck to go and look at a cell that carries no
    # information — three corpus decks moved for exactly that (LCINT=100 and
    # NCDCF=1, both written out explicitly). Only a value that DIFFERS from
    # the manual's default is a real dropped input.
    # LCINT also absorbs a stated 0 (and anything below 100) because the same
    # page says "A minimum number of 100 is always used, that is, only larger
    # input values are possible"; NCDCF absorbs 0 and 1 alike.
    inert = {"LCINT": lambda v: v <= 100,
             "NCDCF": lambda v: v in (0, 1)}
    for i, name in enumerate(("NLQ", "ISNAN", "LCINT", "LCACC", "NCDCF",
                              "NOCOPY", "CRVP"), start=1):
        if not (len(f) > i and f[i].strip()):
            continue
        v = to_int(f[i])
        if inert.get(name, lambda x: x == 0)(v):
            continue
        dropped.append(f"{name}={f[i].strip()}")
    if dropped:
        state.warn(
            "*CONTROL_SOLUTION: " + ", ".join(dropped) + " dropped. They are "
            "vectorisation and curve-plumbing controls (vector length, NaN "
            "checking, curve rediscretization, load-curve accuracy) with no "
            "Radioss counterpart; only SOLN reaches the converted deck. "
            "(Cells stating their own documented default — Vol I R17 p.12-532 "
            "gives LCINT 100 and NCDCF 1, the rest 0 — are not listed: they "
            "state nothing to lose.)")
    if soln == 1:
        # The engine card and the warning are written by the writer, which
        # knows whether a /HEAT/MAT exists to make the run integrate anything.
        return
    if soln == 2:
        state.note_recognized_not_emitted(
            "CONTROL_SOLUTION",
            "SOLN=2 (coupled structural/thermal). Radioss has no analysis-type "
            "switch for the COUPLED case: the FE thermal solve is armed per "
            "MATERIAL by /HEAT/MAT (hm_read_therm.F:253 sets "
            "MAT_PARAM%ITHERM = 1, and hm_read_part.F:366 -> "
            "ale_euler_init.F:193-201 turns that into GLOB_THERM%ITHERM_FE for "
            "every PART on the material), which k2rad emits for the parts "
            "whose *MAT_ADD_THERMAL_EXPANSION or *PART TMID asks for it. One "
            "honest difference: with no /DT/THERM the thermal stability step "
            "is NEVER COMPUTED (dttherm.F90 and mqviscb.F:644 are both gated "
            "on IDT_THERM == 1), so a coupled run integrates the temperature "
            "at the MECHANICAL step with no thermal stability check — safe in "
            "practice only because the mechanical step is normally far "
            "smaller.")
        return
    state.note_recognized_not_emitted(
        "CONTROL_SOLUTION",
        f"SOLN={soln} (structural only) is Radioss's default behaviour — "
        "nothing to emit.")


def _thermal_deferred(keyword: str, what: str, target: str):
    """Build a handler that names an INEXPRESSIBLE thermal keyword and drops it.

    The text used to promise that the drop was temporary — *"which belongs to
    the full thermal-solver conversion; this batch ships the thermal-EXPANSION
    path plus the minimal temperature drivers only"*. That clause is false now
    that /IMPFLUX, /CONVEC, /RADIATION and the engine thermal controls are
    converted, so every keyword still routed here is one with no counterpart at
    all, and the message says exactly that instead.

    The entry is keyed on the SPELLING THE DECK USED, not on *keyword*: the
    same handler serves a canonical ``*MAT_THERMAL_*`` name and its
    ``*MAT_T##`` alias (Vol II R17 p.2-9), and a log that answered
    ``*MAT_THERMAL_CWM`` to a deck writing ``*MAT_T07`` would name a card the
    deck does not contain. When the two differ the message says so.
    """
    def _h(block: Block, state: ConversionState) -> None:
        seen = block.keyword or keyword
        alias = ("" if seen == keyword else
                 f" (*{seen} is Vol II R17 p.2-9's numeric alias for "
                 f"*{keyword})")
        state.note_recognized_not_emitted(
            seen,
            f"{what}{alias} — no card written. {target}. Registering the "
            "keyword is what lets this log say WHICH thermal input the deck "
            "loses instead of leaving it in the unrecognized-keyword list.")
    return _h


def handle_mat_tabulated_johnson_cook(block: Block,
                                      state: ConversionState) -> None:
    """*MAT_TABULATED_JOHNSON_COOK (224) → /MAT/LAW109 [+ /FAIL/TAB1].

    R16/R17 cards (Vol II R17 p.1591-1597; the shipped Keyword971_R7.1
    mat_224.cfg is STALE — it lacks BFLG/ERODE/LCPS and types card 3 as
    floats, so the layout is stated from the manual):
      Card1: MID RO E PR CP TR BETA NUMINT
      Card2: LCK1 LCKT LCF LCG LCH LCI BFLG
      Card3 (optional): FAILOPT NUMAVG NCYFAIL ERODE LCPS

    Blank/0.0 BETA and NUMINT take the manual's defaults (both 1.0, "EQ.0.0:
    Defaults to 1.0"). CP is the specific heat per unit MASS on BOTH sides —
    LAW109's C_p divides by RHO itself (sigeps109.F:419) — so it is stored
    RAW, deliberately unlike the MAT_015 → LAW2/LAW4 rho-premultiplied
    rhoC_p convention. The _LOG_INTERPOLATION spelling (log interpolation of
    the LCK1 rate axis) sets I_smooth=2, dyna2rad's choice (CM:11131-11132;
    Ismooth 2 and 3 are numerically identical weights in
    table2d_vinterp_log.F:210/241). Every curve/table routing decision lives
    in the writer prepass _resolve_mat_tabulated_jc.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_TABULATED_JOHNSON_COOK: empty material card — skipped")
        return
    mid  = to_int(f1[0])
    rho  = to_float(f1[1]) if len(f1) > 1 else 0.0
    e    = to_float(f1[2]) if len(f1) > 2 else 0.0
    pr   = to_float(f1[3]) if len(f1) > 3 else 0.0
    cp   = to_float(f1[4]) if len(f1) > 4 else 0.0
    tr   = to_float(f1[5]) if len(f1) > 5 else 0.0
    beta = _ffield(f1, 6, 1.0)
    if beta == 0.0:
        beta = 1.0
    numint = _ffield(f1, 7, 1.0)
    if numint == 0.0:
        numint = 1.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    lck1 = to_int(f2[0]) if f2         else 0
    lckt = to_int(f2[1]) if len(f2) > 1 else 0
    lcf  = to_int(f2[2]) if len(f2) > 2 else 0
    lcg  = to_int(f2[3]) if len(f2) > 3 else 0
    lch  = to_int(f2[4]) if len(f2) > 4 else 0
    lci  = to_int(f2[5]) if len(f2) > 5 else 0
    bflg = to_int(f2[6]) if len(f2) > 6 else 0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    failopt = to_int(f3[0]) if f3         else 0
    numavg  = to_int(f3[1]) if len(f3) > 1 and f3[1].strip() else 1
    ncyfail = to_int(f3[2]) if len(f3) > 2 and f3[2].strip() else 1
    erode   = to_int(f3[3]) if len(f3) > 3 else 0
    lcps    = to_int(f3[4]) if len(f3) > 4 else 0
    state.mat_tabulated_jc[mid] = MatTabulatedJC(
        mid, title, rho, e, pr, cp, tr, beta, numint,
        lck1, lckt, lcf, lcg, lch, lci, bflg,
        failopt, numavg, ncyfail, erode, lcps,
        log_interpolation="LOG_INTERPOLATION" in block.keyword)


def handle_mat_tabulated_jc_variant(block: Block,
                                    state: ConversionState) -> None:
    """*MAT_TABULATED_JOHNSON_COOK_GYS (224_GYS) and
    *MAT_TABULATED_JOHNSON_COOK_ORTHO_PLASTICITY (264) — warn-skip.

    dyna2rad's verdict for BOTH is a silent drop: _GYS is absent from its
    keyword map (operator[] default-inserts law 0) and _ORTHO_PLASTICITY maps
    to 264 which has no case in the dispatch switch, so both fall into the
    Convert1To1 fallback whose error message is commented out and whose
    LsDynaToRad.cfg lookup has no MAT_224/264 rule — no /MAT is created, no
    message is shown, and the part is wired to mat_ID=0 (CM:140-143,
    196-201, 527-554). k2rad matches the DROP (their yield surfaces are
    genuinely inexpressible in the isotropic von-Mises /MAT/LAW109) but says
    so loudly, naming what is lost.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=2, w=10)
    mid = to_int(f1[0]) if f1 and f1[0].strip() else 0
    if "ORTHO" in block.keyword or block.keyword in ("MAT_264",):
        lost = ("orthotropic plasticity (per-direction tabulated yield "
                "surfaces + anisotropy angles)")
        name = "*MAT_TABULATED_JOHNSON_COOK_ORTHO_PLASTICITY (264)"
    else:
        lost = ("the GYS tension/compression/shear-asymmetric yield surface "
                "(separate LCK-style tables per stress state)")
        name = "*MAT_TABULATED_JOHNSON_COOK_GYS (224_GYS)"
    state.warn(
        f"{name} mid={mid}: DROPPED — /MAT/LAW109 is an isotropic von-Mises "
        f"tabulated law and cannot express {lost}. dyna2rad drops this "
        "variant too, but SILENTLY (no /MAT, no message, part wired to "
        "mat_ID=0). Every /PART referencing this MID has no /MAT in the "
        "converted deck and the starter will reject it; restate the material "
        "as plain *MAT_TABULATED_JOHNSON_COOK to convert it.")
    state.skipped_keywords.append(block.keyword)


def handle_contact_interior(block: Block, state: ConversionState) -> None:
    """*CONTACT_INTERIOR — a FREE_CELL_LIST of part-set ids, 8 per card,
    ending at the next keyword; the keyword may appear more than once and the
    ids accumulate. Resolution and the version-gated Icontrol mapping live in
    writer/mesh.py::_resolve_contact_interior (*SET_PART_ADD ids arrive
    pre-expanded by _flatten_part_set_adds)."""
    offset = _title_offset(block)
    for line in block.raw[offset:]:
        for tok in parse_free(line):
            v = to_int(tok)
            if v > 0:
                state.contact_interior_psids.append(v)


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


# ─────────────────────────────────────────────────────────────────────────────
# Viscoelastic batch (MAT_006 / MAT_061 / MAT_076 / MAT_181 / MAT_183 /
#                     MAT_091 / MAT_092)
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_viscoelastic(block: Block, state: ConversionState) -> None:
    """*MAT_VISCOELASTIC (MAT_006) → /MAT/LAW34 (BOLTZMAN).

    ONE card (mat_006.cfg): MID RHO BULK G0 GI BETA. The mapping is exact —
    LS-DYNA's G(t) = GI + (G0-GI)e^(-BETA t) is literally LAW34's kernel, and
    BETA is a decay rate in both codes. From R6.1 on each of BULK/G0/GI/BETA
    may be NEGATIVE, meaning "-LCID of a temperature-dependent curve"; the
    negative value is stored as-is here and collapsed by the writer resolve
    pass, which needs the parsed *DEFINE_CURVEs.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f1 = _card(block.raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_VISCOELASTIC: empty material card — skipped")
        return
    mid = to_int(f1[0])
    state.mat_viscoelastic[mid] = MatViscoelastic(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        bulk=to_float(f1[2]) if len(f1) > 2 else 0.0,
        g0=to_float(f1[3]) if len(f1) > 3 else 0.0,
        gi=to_float(f1[4]) if len(f1) > 4 else 0.0,
        beta=to_float(f1[5]) if len(f1) > 5 else 0.0)


def handle_mat_kelvin_maxwell(block: Block, state: ConversionState) -> None:
    """*MAT_KELVIN-MAXWELL_VISCOELASTIC (MAT_061) → /MAT/LAW40 (KELVINMAX).

    ONE card (mat_061.cfg): MID RHO BULK G0 GI DC FO SO. dyna2rad
    p_ConvertMatL61 maps G_inf = GI, G1 = G0-GI, BETA1 = DC and zeroes the
    other four Maxwell branches plus the Stassi/von-Mises coefficients. FO
    (0 = Maxwell / 1 = Kelvin) and SO (a d3plot output selector) are dropped by
    dyna2rad without a word — both are warned in the writer resolve pass, FO
    loudly because a Kelvin-form DC is a RETARDATION constant and converting it
    as a Maxwell decay rate is silently wrong.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f1 = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_KELVIN-MAXWELL_VISCOELASTIC: empty material card — skipped")
        return
    mid = to_int(f1[0])
    state.mat_kelvin_maxwell[mid] = MatKelvinMaxwell(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        bulk=to_float(f1[2]) if len(f1) > 2 else 0.0,
        g0=to_float(f1[3]) if len(f1) > 3 else 0.0,
        gi=to_float(f1[4]) if len(f1) > 4 else 0.0,
        dc=to_float(f1[5]) if len(f1) > 5 else 0.0,
        fo=to_float(f1[6]) if len(f1) > 6 else 0.0,
        so=to_float(f1[7]) if len(f1) > 7 else 0.0)


def handle_mat_general_viscoelastic(block: Block,
                                    state: ConversionState) -> None:
    """*MAT_GENERAL_VISCOELASTIC (MAT_076, + _MOISTURE) → /MAT/LAW42 +
    /VISC/PRONY.

    Cards (mat_076.cfg): MID RO BULK PCF EF TREF A B / LCID NT BSTART TRAMP
    LCIDK NTK BSTARTK TRAMPK / [MO ALPHA BETA GAMMA MST, _MOISTURE only] /
    then the FREE_CARD_LIST of GI BETAI KI BETAKI Prony rows.

    Card 2 is MANDATORY in the cfg — a deck that uses the Prony rows leaves it
    BLANK rather than omitting it, and both the parse below and the
    *INCLUDE_TRANSFORM offset spec depend on that. A deck that really omitted
    it would read its first Prony row as LCID/NT, which surfaces as the
    "LCID has no parsed *DEFINE_CURVE" warning from the resolver.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_GENERAL_VISCOELASTIC: empty material card — skipped")
        return
    mid = to_int(f1[0])
    moisture = block.keyword.endswith("_MOISTURE")
    mat = MatGeneralViscoelastic(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        bulk=to_float(f1[2]) if len(f1) > 2 else 0.0,
        pcf=to_float(f1[3]) if len(f1) > 3 else 0.0,
        ef=to_float(f1[4]) if len(f1) > 4 else 0.0,
        tref=to_float(f1[5]) if len(f1) > 5 else 0.0,
        a=to_float(f1[6]) if len(f1) > 6 else 0.0,
        b=to_float(f1[7]) if len(f1) > 7 else 0.0,
        moisture=moisture)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if f2:
        mat.lcid    = to_int(f2[0])
        mat.nt      = int(to_float(f2[1])) if len(f2) > 1 else 0
        mat.bstart  = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.tramp   = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.lcidk   = to_int(f2[4]) if len(f2) > 4 else 0
        mat.ntk     = int(to_float(f2[5])) if len(f2) > 5 else 0
        mat.bstartk = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.trampk  = to_float(f2[7]) if len(f2) > 7 else 0.0
    prony_start = offset + 3 if moisture else offset + 2
    for gi, betai, ki, betaki in _prony_rows(raw, prony_start, 4):
        mat.gi.append(gi)
        mat.betai.append(betai)
        mat.ki.append(ki)
        mat.betaki.append(betaki)
    state.mat_general_visco[mid] = mat


def handle_mat_simplified_rubber(block: Block, state: ConversionState) -> None:
    """*MAT_SIMPLIFIED_RUBBER/FOAM (181) and *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE
    (183) → /MAT/LAW88.

    181 (mat_181.cfg): MID RHO KM MU G SIGF REF PRTEN / SGL SW ST LC/TBID
    TENSION RTYPE AVGOPT PR / [K GAMA1 GAMA2 EH — _WITH_FAILURE only] /
    [LCUNLD HU SHAPE STOL VISCO HISOUT — optional] / [Gi BETAi VFLAG free list].
    183 (mat_183.cfg): MID RHO K MU G SIGF / SGL SW ST LC TENSION RTYPE AVGOPT
    / LCUNLD REF STOL — card 3 MANDATORY, no PR, no REF/PRTEN on card 1, no
    HU/SHAPE/VISCO and no Prony cards at all.

    HU defaults to 1.0 (no dissipation) per the cfg DEFAULTS, so a BLANK HU on
    a present card 4 is 1.0, not 0. The optional card 4 counts as present only
    when it carries a non-blank field — a trailing blank line in the block is
    not a card, and a genuinely blank card 4 gives the same result either way
    (every field falls back to its default and _prony_rows skips blanks).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    kw = block.keyword
    is_183 = "WITH_DAMAGE" in kw or kw.startswith("MAT_183")
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn(f"*{kw}: empty material card — skipped")
        return
    mid = to_int(f1[0])
    mat = MatSimplifiedRubber(
        mid=mid, title=title, family="183" if is_183 else "181",
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        k=to_float(f1[2]) if len(f1) > 2 else 0.0,
        mu=to_float(f1[3]) if len(f1) > 3 else 0.0,
        g=to_float(f1[4]) if len(f1) > 4 else 0.0,
        sigf=to_float(f1[5]) if len(f1) > 5 else 0.0,
        log_log=kw.endswith("_LOG_LOG_INTERPOLATION"))
    if not is_183:
        mat.ref   = to_float(f1[6]) if len(f1) > 6 else 0.0
        mat.prten = to_float(f1[7]) if len(f1) > 7 else 0.0
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if f2:
        mat.sgl     = to_float(f2[0])
        mat.sw      = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.st      = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.lc_tbid = to_int(f2[3]) if len(f2) > 3 else 0
        mat.tension = int(to_float(f2[4])) if len(f2) > 4 else 0
        mat.rtype   = int(to_float(f2[5])) if len(f2) > 5 else 0
        mat.avgopt  = to_float(f2[6]) if len(f2) > 6 else 0.0
        if not is_183:
            mat.pr = to_float(f2[7]) if len(f2) > 7 else 0.0
    if is_183:
        f3 = _card(raw, offset + 2, fixed=True, n=3, w=10)
        if f3:
            mat.lcunld = to_int(f3[0])
            mat.ref    = to_float(f3[1]) if len(f3) > 1 else 0.0
            mat.stol   = to_float(f3[2]) if len(f3) > 2 else 0.0
        state.mat_simplified_rubber[mid] = mat
        return
    nxt = offset + 2
    if "_WITH_FAILURE" in kw:
        mat.with_failure = True
        f3 = _card(raw, nxt, fixed=True, n=4, w=10)
        if f3:
            mat.kfail = to_float(f3[0])
            mat.gama1 = to_float(f3[1]) if len(f3) > 1 else 0.0
            mat.gama2 = to_float(f3[2]) if len(f3) > 2 else 0.0
            mat.eh    = to_float(f3[3]) if len(f3) > 3 else 0.0
        nxt += 1
    f4 = _card(raw, nxt, fixed=True, n=6, w=10)
    if f4 and any(x.strip() for x in f4):
        mat.has_unload_card = True
        mat.lcunld = to_int(f4[0])
        mat.hu     = _ffield(f4, 1, 1.0)
        mat.shape  = to_float(f4[2]) if len(f4) > 2 else 0.0
        mat.stol   = to_float(f4[3]) if len(f4) > 3 else 0.0
        mat.visco  = int(to_float(f4[4])) if len(f4) > 4 else 0
        mat.hisout = int(to_float(f4[5])) if len(f4) > 5 else 0
        nxt += 1
    rows = _prony_rows(raw, nxt, 3)
    if rows:
        mat.vflag = int(rows[0][2])
    for gi, betai, _vf in rows:
        mat.gi.append(gi)
        mat.betai.append(betai)
    state.mat_simplified_rubber[mid] = mat


def handle_mat_soft_tissue(block: Block, state: ConversionState) -> None:
    """*MAT_SOFT_TISSUE (091) / *MAT_SOFT_TISSUE_VISCO (092) → /MAT/LAW42.

    FOUR mandatory cards (Vol II R17 p.2-669) — MID RO C1..C5 REF / XK XLAM
    FANG XLAM0 FAILSF FAILSM FAILSHR / AOPT AX AY AZ BX BY BZ / LA1 LA2 LA3
    MACF — plus S1..S6 and T1..T6 for the _VISCO (MAT_092) spelling. Cards 3
    and 4 are required even for the non-VISCO variant; this material carries
    its a/b fibre vectors inline on card 3 rather than through the generic
    AOPT card expansion, so the S/T cards are always at a fixed offset.

    dyna2rad keeps only the isotropic Mooney-Rivlin ground substance; the
    dropped fields are enumerated by the writer resolve pass.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn(f"*{block.keyword}: empty material card — skipped")
        return
    mid = to_int(f1[0])
    visco = block.keyword.endswith("_VISCO") or block.keyword in ("MAT_092",
                                                                  "MAT_92")
    mat = MatSoftTissue(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        c1=to_float(f1[2]) if len(f1) > 2 else 0.0,
        c2=to_float(f1[3]) if len(f1) > 3 else 0.0,
        c3=to_float(f1[4]) if len(f1) > 4 else 0.0,
        c4=to_float(f1[5]) if len(f1) > 5 else 0.0,
        c5=to_float(f1[6]) if len(f1) > 6 else 0.0,
        ref=to_float(f1[7]) if len(f1) > 7 else 0.0,
        visco=visco)
    f2 = _card(raw, offset + 1, fixed=True, n=7, w=10)
    if f2:
        mat.xk      = to_float(f2[0])
        mat.xlam    = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.fang    = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.xlam0   = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.failsf  = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.failsm  = to_float(f2[5]) if len(f2) > 5 else 0.0
        mat.failshr = to_float(f2[6]) if len(f2) > 6 else 0.0
    f3 = _card(raw, offset + 2, fixed=True, n=7, w=10)
    if f3:
        mat.aopt = to_float(f3[0])
    f4 = _card(raw, offset + 3, fixed=True, n=4, w=10)
    if f4 and len(f4) > 3:
        mat.macf = to_float(f4[3])
    if visco:
        f5 = _card(raw, offset + 4, fixed=True, n=6, w=10)
        f6 = _card(raw, offset + 5, fixed=True, n=6, w=10)
        mat.s = [to_float(f5[i]) if len(f5) > i else 0.0 for i in range(6)]
        mat.t = [to_float(f6[i]) if len(f6) > i else 0.0 for i in range(6)]
    state.mat_soft_tissue[mid] = mat


# ─────────────────────────────────────────────────────────────────────────────
# Adhesives / cohesive batch (MAT_138 / MAT_169 / MAT_240 / MAT_252 /
#                             MAT_ADD_DAMAGE_DIEM)
# ─────────────────────────────────────────────────────────────────────────────

def handle_mat_cohesive_mixed_mode(block: Block,
                                   state: ConversionState) -> None:
    """*MAT_COHESIVE_MIXED_MODE (MAT_138) → /MAT/LAW117.

    TWO cards (mat_138.cfg R13.0): MID RO ROFLG INTFAIL EN ET GIC GIIC /
    XMU T S UND UTD GAMMA. Every sign encoding is kept raw here (XMU's sign is
    the power-law/B-K switch, negative T/S/GIC/GIIC are curve ids) and decoded
    by the emitter, which is where the semantic warnings live.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_COHESIVE_MIXED_MODE: empty material card — skipped")
        return
    mid = to_int(f1[0])
    mat = MatCohesiveMixedMode(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        roflg=int(to_float(f1[2])) if len(f1) > 2 else 0,
        intfail=to_float(f1[3]) if len(f1) > 3 else 0.0,
        en=to_float(f1[4]) if len(f1) > 4 else 0.0,
        et=to_float(f1[5]) if len(f1) > 5 else 0.0,
        gic=to_float(f1[6]) if len(f1) > 6 else 0.0,
        giic=to_float(f1[7]) if len(f1) > 7 else 0.0)
    f2 = _card(raw, offset + 1, fixed=True, n=6, w=10)
    if f2:
        mat.xmu   = to_float(f2[0])
        mat.t     = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.s     = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.und   = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.utd   = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.gamma = _ffield(f2, 5, 1.0)
    state.mat_cohesive_mixed_mode[mid] = mat


def handle_mat_arup_adhesive(block: Block, state: ConversionState) -> None:
    """*MAT_ARUP_ADHESIVE (MAT_169) → /MAT/LAW169.

    Cards 1/2 always; card 3+4 iff EXTRA in (1,3); card 5 iff EDOT2 != 0;
    card 6 iff EXTRA in (2,3) — IN THAT ORDER (the EDOT2 card sits BETWEEN the
    edge cards and the bond-thickness card, mat_169.cfg R11.1 == R16 manual).
    The walk must clear the conditional cards even though everything on them
    is dropped, otherwise a following keyword's parse position would be wrong
    for multi-material files read through *INCLUDE assembly.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_ARUP_ADHESIVE: empty material card — skipped")
        return
    mid = to_int(f1[0])
    mat = MatArupAdhesive(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        e=to_float(f1[2]) if len(f1) > 2 else 0.0,
        pr=to_float(f1[3]) if len(f1) > 3 else 0.0,
        tenmax=to_float(f1[4]) if len(f1) > 4 else 0.0,
        gcten=to_float(f1[5]) if len(f1) > 5 else 0.0,
        shrmax=to_float(f1[6]) if len(f1) > 6 else 0.0,
        gcshr=to_float(f1[7]) if len(f1) > 7 else 0.0)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if f2:
        mat.pwrt   = _ffield(f2, 0, 2.0)
        mat.pwrs   = _ffield(f2, 1, 2.0)
        mat.shrp   = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.sht_sl = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.edot0  = _ffield(f2, 4, 1.0)
        mat.edot2  = to_float(f2[5]) if len(f2) > 5 else 0.0
        mat.thkdir = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.extra  = int(to_float(f2[7])) if len(f2) > 7 else 0
    nxt = offset + 2
    if mat.extra in (1, 3):
        nxt += 2                        # cards 3 + 4: edge data (dropped)
    if mat.edot2 != 0.0:
        nxt += 1                        # card 5: SDFAC..SGEFAC (dropped)
    if mat.extra in (2, 3):
        f6 = _card(raw, nxt, fixed=True, n=5, w=10)
        if f6:
            mat.bthk = to_float(f6[0])
    state.mat_arup_adhesive[mid] = mat


# *MAT_240 keyword options that change the CARD CONTENT itself: _THERMAL (and
# _FUNCTIONS, R16) turn EMOD/GMOD/G*C_0/T0/S0/FG* into curve ids, _3MODES adds
# the mode-III cards. /MAT/LAW116 holds none of that, and dyna2rad's own gate
# is `if (lsdThermal == 0 && lsd3Modes == 0)` — with the variants falling
# through to NO material and NO message (convertmats.cxx:6664). k2rad registers
# the variant spellings so they warn-skip loudly instead of parsing garbage.
_MAT240_UNSUPPORTED_OPTIONS = ("_THERMAL", "_3MODES", "_FUNCTIONS")


def handle_mat_cohesive_mm_epr(block: Block, state: ConversionState) -> None:
    """*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE (MAT_240) → /MAT/LAW116.

    THREE cards (mat_240.cfg R11.1) plus the optional R16 Card 6 (the
    manual's cards 4/5 are the _3MODES mode-III cards, absent from the
    option-free spelling, so Card 6 sits at position offset+3 here):
    MID RO ROFLG INTFAIL EMOD GMOD THICK INICRT / G1C_0 G1C_INF EDOT_G1 T0 T1
    EDOT_T FG1 LCG1C / G2C_0 G2C_INF EDOT_G2 S0 S1 EDOT_S FG2 LCG2C /
    [RFILTF COMPY SMOLIM XMU]. Sign encodings stay raw for the emitter.

    The _THERMAL / _3MODES / _FUNCTIONS variants are warn-skipped HERE (their
    cards hold curve ids / mode-III data with no LAW116 slot); dyna2rad drops
    them with no message and the part ends with mat_ID=0.
    """
    kw = block.keyword
    unsupported = [o for o in _MAT240_UNSUPPORTED_OPTIONS if o in kw]
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn(f"*{kw}: empty material card — skipped")
        return
    mid = to_int(f1[0])
    if unsupported:
        state.warn(
            f"*{kw} mid={mid}: the {'/'.join(o.lstrip('_') for o in unsupported)} "
            "option has no /MAT/LAW116 counterpart — _THERMAL/_FUNCTIONS turn "
            "EMOD/GMOD/G1C_0/G2C_0/T0/S0/FG1/FG2 into curve ids and _3MODES "
            "adds mode-III cards, none of which LAW116 can hold. The material "
            "is SKIPPED (no /MAT emitted), so any part referencing MID "
            f"{mid} will fail the starter with a dangling mat_ID. Re-state the "
            "material as the option-free *MAT_240 card (evaluate the curves at "
            "the working temperature/rate) to convert it. dyna2rad drops these "
            "variants silently (convertmats.cxx:6664).")
        state.note_recognized_not_emitted(
            kw, f"MAT_240 option variant not convertible to LAW116 (mid {mid})")
        return
    mat = MatCohesiveMMEPR(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        roflg=int(to_float(f1[2])) if len(f1) > 2 else 0,
        intfail=_ffield(f1, 3, 1.0),
        emod=to_float(f1[4]) if len(f1) > 4 else 0.0,
        gmod=to_float(f1[5]) if len(f1) > 5 else 0.0,
        thick=to_float(f1[6]) if len(f1) > 6 else 0.0,
        inicrt=to_float(f1[7]) if len(f1) > 7 else 0.0)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if f2:
        mat.g1c_0   = to_float(f2[0])
        mat.g1c_inf = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.edot_g1 = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.t0      = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.t1      = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.edot_t  = to_float(f2[5]) if len(f2) > 5 else 0.0
        mat.fg1     = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.lcg1c   = to_int(f2[7]) if len(f2) > 7 else 0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    if f3:
        mat.g2c_0   = to_float(f3[0])
        mat.g2c_inf = to_float(f3[1]) if len(f3) > 1 else 0.0
        mat.edot_g2 = to_float(f3[2]) if len(f3) > 2 else 0.0
        mat.s0      = to_float(f3[3]) if len(f3) > 3 else 0.0
        mat.s1      = to_float(f3[4]) if len(f3) > 4 else 0.0
        mat.edot_s  = to_float(f3[5]) if len(f3) > 5 else 0.0
        mat.fg2     = to_float(f3[6]) if len(f3) > 6 else 0.0
        mat.lcg2c   = to_int(f3[7]) if len(f3) > 7 else 0
    f4 = _card(raw, offset + 3, fixed=True, n=4, w=10)
    if f4 and any(x.strip() for x in f4):
        mat.rfiltf = to_float(f4[0])
        mat.compy  = to_float(f4[1]) if len(f4) > 1 else 0.0
        mat.smolim = to_float(f4[2]) if len(f4) > 2 else 0.0
        mat.xmu    = to_float(f4[3]) if len(f4) > 3 else 0.0
    state.mat_cohesive_mm_epr[mid] = mat


def handle_mat_toughened_adhesive(block: Block,
                                  state: ConversionState) -> None:
    """*MAT_TOUGHENED_ADHESIVE_POLYMER (MAT_252) → /MAT/LAW120 (TAPO).

    FOUR cards, parsed to the R16 manual layout — NOT the local R7.1 cfg,
    which blanks card-3 field 8 (SRFILT) and card-4 field 1 (IHIS) and would
    silently drop both: MID RO E PR FLG JCFL DOPT / LCSS TAU0 Q B H C GAM0
    GAMM / A10 A20 A1H A2H A2S POW - SRFILT / IHIS - D1 D2 D3 D4 D1C D2C.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=7, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_TOUGHENED_ADHESIVE_POLYMER: empty material card — "
                   "skipped")
        return
    mid = to_int(f1[0])
    mat = MatToughenedAdhesive(
        mid=mid, title=title,
        rho=to_float(f1[1]) if len(f1) > 1 else 0.0,
        e=to_float(f1[2]) if len(f1) > 2 else 0.0,
        pr=to_float(f1[3]) if len(f1) > 3 else 0.0,
        flg=int(to_float(f1[4])) if len(f1) > 4 else 0,
        jcfl=int(to_float(f1[5])) if len(f1) > 5 else 0,
        dopt=int(to_float(f1[6])) if len(f1) > 6 else 0)
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    if f2:
        mat.lcss = to_int(f2[0])
        mat.tau0 = to_float(f2[1]) if len(f2) > 1 else 0.0
        mat.q    = to_float(f2[2]) if len(f2) > 2 else 0.0
        mat.b    = to_float(f2[3]) if len(f2) > 3 else 0.0
        mat.h    = to_float(f2[4]) if len(f2) > 4 else 0.0
        mat.c    = to_float(f2[5]) if len(f2) > 5 else 0.0
        mat.gam0 = to_float(f2[6]) if len(f2) > 6 else 0.0
        mat.gamm = to_float(f2[7]) if len(f2) > 7 else 0.0
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    if f3:
        mat.a10    = to_float(f3[0])
        mat.a20    = to_float(f3[1]) if len(f3) > 1 else 0.0
        mat.a1h    = to_float(f3[2]) if len(f3) > 2 else 0.0
        mat.a2h    = to_float(f3[3]) if len(f3) > 3 else 0.0
        mat.a2s    = to_float(f3[4]) if len(f3) > 4 else 0.0
        mat.pow    = to_float(f3[5]) if len(f3) > 5 else 0.0
        mat.srfilt = to_float(f3[7]) if len(f3) > 7 else 0.0
    f4 = _card(raw, offset + 3, fixed=True, n=8, w=10)
    if f4:
        mat.ihis = to_float(f4[0])
        mat.d1   = to_float(f4[2]) if len(f4) > 2 else 0.0
        mat.d2   = to_float(f4[3]) if len(f4) > 3 else 0.0
        mat.d3   = to_float(f4[4]) if len(f4) > 4 else 0.0
        mat.d4   = to_float(f4[5]) if len(f4) > 5 else 0.0
        mat.d1c  = to_float(f4[6]) if len(f4) > 6 else 0.0
        mat.d2c  = to_float(f4[7]) if len(f4) > 7 else 0.0
    state.mat_toughened_adhesive[mid] = mat


def handle_mat_add_damage_diem(block: Block, state: ConversionState) -> None:
    """*MAT_ADD_DAMAGE_DIEM → /FAIL/INIEVO (rider keyed by the parent MID).

    Card 1: MID NDIEMC DINIT DEPS NUMFIP [VOLFRAC], then NDIEMC contiguous
    pairs of criterion cards (max 5, mat_add_damage_diem.cfg R13.0 +
    VOLFRAC/Q4 from R16):
      Card 2: DITYP P1 P2 P3 P4 P5
      Card 3: DETYP DCTYP Q1 Q2 Q3 Q4
    Column positions are fixed regardless of DITYP/DETYP (the cfg pads unused
    slots with _BLANK_), so a plain fixed read per card is exact.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=6, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_ADD_DAMAGE_DIEM: empty card – skipped")
        return
    mid = to_int(f1[0])
    diem = FailDiem(
        mid=mid,
        ndiemc=int(to_float(f1[1])) if len(f1) > 1 else 0,
        dinit=to_float(f1[2]) if len(f1) > 2 else 0.0,
        deps=to_float(f1[3]) if len(f1) > 3 else 0.0,
        numfip=_ffield(f1, 4, 1.0),
        volfrac=to_float(f1[5]) if len(f1) > 5 else 0.0)
    for i in range(max(diem.ndiemc, 0)):
        c2 = _card(raw, offset + 1 + 2 * i, fixed=True, n=6, w=10)
        c3 = _card(raw, offset + 2 + 2 * i, fixed=True, n=6, w=10)
        if not c2:
            state.warn(
                f"*MAT_ADD_DAMAGE_DIEM mid={mid}: NDIEMC={diem.ndiemc} but "
                f"only {i} criterion card pair(s) follow — the missing "
                "criteria are dropped and NINIEVO is reduced to match.")
            diem.ndiemc = i
            break
        crit = FailDiemCriterion(
            dityp=int(to_float(c2[0])),
            p1=to_int(c2[1]) if len(c2) > 1 else 0,
            p2=to_float(c2[2]) if len(c2) > 2 else 0.0,
            p3=to_float(c2[3]) if len(c2) > 3 else 0.0,
            p4=to_float(c2[4]) if len(c2) > 4 else 0.0,
            p5=to_int(c2[5]) if len(c2) > 5 else 0)
        if c3:
            crit.detyp = int(to_float(c3[0]))
            crit.dctyp = int(to_float(c3[1])) if len(c3) > 1 else 0
            crit.q1    = to_float(c3[2]) if len(c3) > 2 else 0.0
            crit.q2    = to_float(c3[3]) if len(c3) > 3 else 0.0
            crit.q3    = to_float(c3[4]) if len(c3) > 4 else 0.0
            crit.q4    = to_float(c3[5]) if len(c3) > 5 else 0.0
        diem.criteria.append(crit)
    if mid in state.fail_diem:
        state.warn(f"*MAT_ADD_DAMAGE_DIEM: a second card for MID {mid} "
                   "overwrites the first — k2rad emits one /FAIL/INIEVO per "
                   "material (put all criteria on one keyword, NDIEMC up to "
                   "5). The earlier card's criteria are dropped.")
    state.fail_diem[mid] = diem


# ─────────────────────────────────────────────────────────────────────────────
# *AIRBAG_* → /MONVOL  (monitored volumes)
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA keyword base → the ``Airbag.model`` tag the writer routes on. ONE
#: source for the dispatch keys, the model tag and the per-model card readers
#: (#116) — ``parser._split_keyword`` strips a trailing ``_ID``/``_TITLE``, so
#: those two spellings need no key of their own, but nothing else falls back:
#: ``dispatch()`` is an exact dict lookup with no ``AIRBAG_`` prefix rule, and
#: an unregistered spelling lands in ``skipped_keywords`` with no warning at
#: all (the #117 ``*LOAD_BODY_R*`` defect).
_AIRBAG_MODELS = {
    "AIRBAG_SIMPLE_PRESSURE_VOLUME": "SIMPLE_PRESSURE_VOLUME",
    "AIRBAG_SIMPLE_AIRBAG_MODEL":    "SIMPLE_AIRBAG_MODEL",
    "AIRBAG_ADIABATIC_GAS_MODEL":    "ADIABATIC_GAS_MODEL",
    "AIRBAG_LOAD_CURVE":             "LOAD_CURVE",
    "AIRBAG_LINEAR_FLUID":           "LINEAR_FLUID",
    # ── batch 2 ─────────────────────────────────────────────────────────
    "AIRBAG_HYBRID":                 "HYBRID",
    "AIRBAG_PARTICLE":               "PARTICLE",
}

#: The OPTION suffixes each batch-2 model accepts, as a product generated onto
#: the dispatch table (#116). Order inside a tuple is the order LS-DYNA
#: documents; the generator below emits every combination, because
#: ``dispatch()`` is an exact lookup and an unregistered spelling is a bag that
#: never inflates on a run that terminates normally.
#:
#: ``*AIRBAG_HYBRID``'s documented option list is exactly ``{ }``, ``_ID``,
#: ``_TITLE``, ``_JETTING``, ``_JETTING_CM`` (Vol I R17 pp.3-44…3-52; ``_ID``
#: and ``_TITLE`` are stripped by ``parser._split_keyword``).
#:
#: ``_CHEMKIN`` is deliberately NOT here. ``*AIRBAG_HYBRID_CHEMKIN`` is a
#: MODEL of its own with its own card stack, not a HYBRID with extra cards:
#: Vol I R17 p.3-54 gives it card 3 ``LCIDM LCIDT NGAS DATA ATMT ATMP RG``,
#: card 4 ``HCONV``, card 5 ``C23 A23``, and then a control card plus several
#: thermodynamic-property cards PER SPECIES. Routing it to the HYBRID reader
#: reads its curve ids as ATMOST/ATMOSP and its DATA as GC, then walks a gas
#: block that is not there. It is registered on ``handle_airbag_unsupported``
#: instead — a named warn-drop, which is what master did before batch 2.
#:
#: ``_CHAMBER`` is not here either: it is not a documented *AIRBAG option at
#: all (the chamber concept belongs to CPM — ``*DEFINE_CPM_CHAMBER`` plus
#: ``*AIRBAG_PARTICLE``'s ``CHM``/``CHM_ID``), so its card stack is unknown
#: and guessing it is worse than the ``("AIRBAG", ...)`` prefix net's
#: warn-and-drop, which still names the keyword.
#:
#: ``*AIRBAG_PARTICLE``'s six option slots ARE all here, because every one of
#: them is a documented option of the same model: ``_MPP`` and ``_TIME`` add a
#: prelude card, ``_SEGMENT`` adds card 2, ``_JET`` adds card 4, and
#: ``_DECOMPOSITION``/``_MOLEFRACTION``/``_INFLATION`` add none — see
#: ``_warn_particle_option`` for what each unmodelled one costs.
_AIRBAG_OPTION_STACKS = {
    "AIRBAG_HYBRID":   (("", "_JETTING"), ("", "_CM")),
    "AIRBAG_PARTICLE": (("", "_MPP"), ("", "_DECOMPOSITION"),
                        ("", "_MOLEFRACTION", "_INFLATION", "_JET"),
                        ("", "_SEGMENT"), ("", "_TIME")),
}

#: ``*AIRBAG_<OPTION>`` models this batch does NOT convert, with what each one
#: would need. Registered anyway — a keyword with a handler that warns by name
#: is strictly better than one that disappears into ``skipped_keywords``,
#: because an unconverted airbag is not a missing output card: the bag never
#: inflates and the deck runs to termination looking healthy.
_AIRBAG_UNSUPPORTED = {
    "AIRBAG_HYBRID_CHEMKIN":
        "the CHEMKIN hybrid inflator — a MODEL of its own, not an option of "
        "*AIRBAG_HYBRID: Vol I R17 p.3-54 gives it card 3 'LCIDM LCIDT NGAS "
        "DATA ATMT ATMP RG', card 4 'HCONV' and card 5 'C23 A23', then a "
        "control card and several thermodynamic-property cards per species. "
        "Reading it as a plain *AIRBAG_HYBRID would take its curve ids for "
        "ATMOST/ATMOSP, so it is dropped whole rather than mis-read. The "
        "Radioss target would be /MONVOL/AIRBAG1 with Iform 2 (Chemkin) on "
        "the vent holes and one /MAT/GAS per species",
    "AIRBAG_WANG_NEFSKE":
        "the Wang-Nefske inflator with its full orifice/temperature model — "
        "the closest Radioss target is /MONVOL/AIRBAG1 with a /PROP/INJECT1 "
        "per inflator gas and one vent-hole block per orifice",
    "AIRBAG_ALE":
        "the ALE-coupled bag — needs an ALE mesh and /INTER/TYPE18 coupling, "
        "not a monitored volume",
    "AIRBAG_ADVANCED_ALE":
        "the advanced ALE bag — same as *AIRBAG_ALE",
    "AIRBAG_FLUID_AND_GAS":
        "the mixed fluid/gas bag — Radioss has no single-card equivalent",
}


def _airbag_prelude(raw: List[str], offset: int):
    """``(card-1 fields, index of card 3)`` for any ``*AIRBAG_<MODEL>``.

    Card 1 is shared by every model, and the cards BETWEEN it and card 3 are
    conditional on RBID (Vol I R16 p.3-4):

      * ``RBID > 0`` — a user activation subroutine: card 2a is ``N`` (the
        number of constants, <= 25) and card 2a.1 carries C1..C5, five per
        card, ``ceil(N/5)`` cards of them.
      * ``RBID < 0`` — the built-in sensor: THREE cards (AX/AY/AZ/AMAG/TDUR,
        DVX/DVY/DVZ/DVMAG, UX/UY/UZ/UMAG).
      * ``RBID == 0`` — nothing; card 3 follows card 1 directly.

    A fixed ``offset + 1`` would therefore read the sensor's acceleration
    magnitudes as the model's thermodynamic constants on any RBID != 0 deck —
    the #119 offset-walk rule, on a keyword where the shift is up to six cards.
    """
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    rbid = to_int(f1[2]) if len(f1) > 2 else 0
    i = offset + 1
    if rbid > 0:
        n = to_int(_card(raw, i, fixed=True, n=1, w=10)[0]) if i < len(raw) else 0
        i += 1 + max(0, (n + 4) // 5)
    elif rbid < 0:
        i += 3
    return f1, i


def _airbag_base_keyword(kw: str) -> str:
    """``AIRBAG_SIMPLE_AIRBAG_MODEL_1`` → ``AIRBAG_SIMPLE_AIRBAG_MODEL``.

    The trailing ``_<digits>`` is a legacy *AIRBAG spelling that LS-DYNA reads
    as the base model, and its card stack is byte-for-byte the documented one —
    the corpus decks even carry the base model's own field-name comments above
    each card (``tire-compression.k:74`` ``*AIRBAG_SIMPLE_AIRBAG_MODEL_1`` over
    ``$#  sid sidtyp rbid vsca psca vini mwd spsf``).

    It matters because ``dispatch()`` is an exact dict lookup: MEASURED over
    the r14 dynaexamples corpus, **16 of the 28** ``*AIRBAG_*`` occurrences use
    it (12 ``_SIMPLE_PRESSURE_VOLUME_1``, 4 ``_SIMPLE_AIRBAG_MODEL_1``) and
    every one of them landed in ``skipped_keywords`` with NO warning — three
    whole decks (``airfilled.sphere.k`` and both ``tire-compression.k``) lost
    their only pressure source while the run terminated normally. Exactly the
    hazard the registration block's own comment names.
    """
    base, _sep, tail = kw.rpartition("_")
    if base.startswith("AIRBAG_") and tail.isdigit():
        kw = base
    if kw in _AIRBAG_MODELS:
        return kw
    # An UNSUPPORTED model is a model, not an option of the model whose name
    # it extends: *AIRBAG_HYBRID_CHEMKIN has its own card stack (Vol I R17
    # p.3-54) and must not resolve to AIRBAG_HYBRID through the prefix walk
    # below, or a future caller would read it with the HYBRID reader.
    if kw in _AIRBAG_UNSUPPORTED:
        return kw
    # The batch-2 OPTION stacks: *AIRBAG_HYBRID_JETTING_CM and
    # *AIRBAG_PARTICLE_MOLEFRACTION are the HYBRID and PARTICLE card stacks
    # with extra cards, not models of their own, so they key the same reader
    # and the same offset spec. Only the two keywords that HAVE options are
    # walked, so no other model can be swallowed by a prefix match.
    for cand in sorted(_AIRBAG_OPTION_STACKS, key=len, reverse=True):
        if kw == cand or kw.startswith(cand + "_"):
            return cand
    return kw


def _populated_cell_slots(raw: List[str], idx: int, n: int = 8,
                          w: int = 10) -> List[int]:
    """WHICH of a fixed card's ``n`` cells carry anything, by 0-based slot.

    The count alone answers "is this card there"; the slots answer "which
    card is it", because two optional cards of the same family can carry the
    same NUMBER of cells in different COLUMNS.
    """
    if idx >= len(raw) or not raw[idx].strip():
        return []
    return [k for k, c in enumerate(_card(raw, idx, fixed=True, n=n, w=w))
            if c.strip()]


def _populated_cells(raw: List[str], idx: int, n: int = 8,
                     w: int = 10) -> int:
    """How many of a fixed card's ``n`` cells carry anything.

    The discriminator for the OPTIONAL cards that decide a count-driven walk's
    stride (#119). A card that is absent or blank counts 0 — which is a
    different answer from "one populated cell", and both are load-bearing.
    """
    return len(_populated_cell_slots(raw, idx, n=n, w=w))


def _hybrid_gas_stride(raw: List[str], first: int, ngas: int) -> int:
    """``1`` or ``2`` — cards per gas in a ``*AIRBAG_HYBRID`` NGAS loop.

    LS-DYNA R17 defines TWO cards per gas (Vol I p.3-49/3-50): card 5.1
    ``LCIDM LCIDT <blank> MW INITM A B C`` and card 5.2 ``FMASS`` alone. The
    second is a later addition and real decks written against the older card
    set simply do not carry it, so the stride cannot be assumed — and getting
    it wrong reads gas 2's mass-flow curve id as gas 1's aspiration fraction
    and then walks the jetting cards off the end of the block.

    It is decided by CONTENT, once: card 5.2 has at most ONE populated cell, so
    a card with two or more at that position is the next gas's card 5.1 (or,
    at NGAS = 1, the jetting card 6, which has eight).

    **A BLANK card is not the end of the block.** ``FMASS``'s default is
    "none" (Vol I R17 p.3-49), so writing it as an all-spaces line is legal
    and is how a preprocessor states FMASS = 0 — and that card has ZERO
    populated cells, the same count an absent one has. Deciding on the blank
    card alone collapsed the stride to 1 and read every gas after the first
    off a blank line: MEASURED with NGAS = 2 and a blank card 5.2, gas 2 came
    back MW = 0, no ``/MAT/GAS`` was emitted for it, the injector lost its row
    and the mixture was built from gas 1 alone (MW 0.03544303797 instead of
    0.02875481386) — on a deck the starter accepts and runs. So a blank card
    is disambiguated by looking ONE FURTHER: if what follows it is itself a
    populated card, the blank line was card 5.2 and the stride is 2. Only a
    blank card with nothing (or nothing populated) behind it is the genuine
    end of the block.

    The residual ambiguity is at NGAS = 1 with ``_JETTING``, where an ABSENT
    card 5.2 in front of a blank jetting card 6 looks exactly like a blank
    card 5.2 in front of a populated card 6. An entirely blank card 6 IS a
    legal jet: NODE1/NODE2 on card 7 override XJFP/XJVH (Vol I R17 p.3-51)
    and CA/BETA are optional, so a jet stated purely by nodes writes card 6
    blank. The look-ahead is therefore decided on the COLUMNS, not on the
    count: card 7 in that node form populates only ``NODE1``/``NODE2``/
    ``NODE3``, slots 5-7 (columns 51-80), while a gas card 5.1 must populate
    ``MW`` in slot 3 (columns 31-40) — a species with MW = 0 is starter
    ERROR 710 — and card 6 in coordinate form populates slots 0-5. So a card
    whose populated cells are ALL in slots >= 5 is a jetting card 7, and the
    blank line in front of it was card 6, not card 5.2.
    """
    if ngas <= 0:
        return 1
    cells = _populated_cells(raw, first + 1)
    if cells == 0:
        nxt = _populated_cell_slots(raw, first + 2)
        return 2 if len(nxt) >= 2 and not all(k >= 5 for k in nxt) else 1
    return 1 if cells >= 2 else 2


def _read_airbag_hybrid(ab: "Airbag", block: Block, raw: List[str], i3: int,
                        state: ConversionState) -> None:
    """``*AIRBAG_HYBRID{_JETTING}{_CM}`` cards 3, 4, 5, the NGAS gas pairs and
    the jetting block.

    Card 3   ``ATMOST ATMOSP ATMOSD GC CC HCONV``
    Card 4   ``C23 LCC23 A23 LCA23 CP23 LCP23 AP23 LCAP23``
    Card 5   ``OPT PVENT NGAS LCEFR LCIDM0 VNTOPT``
    Card 5.1 ``LCIDM LCIDT <blank> MW INITM A B C``   (x NGAS)
    Card 5.2 ``FMASS``                                (x NGAS, optional)
    Card 6   ``XJFP YJFP ZJFP XJVH YJVH ZJVH CA BETA``      (_JETTING)
    Card 7   ``XSJFP YSJFP ZSJFP PSID IDUM NODE1 NODE2 NODE3`` (_JETTING)
    Card 8   ``NREACT``                                     (_JETTING_CM)

    **Card 7 is read by the MANUAL, not by the reader cfg.**
    ``Keyword971_R14.1/CONTROL_VOLUME/subobj_airbag_hybrid.cfg`` writes it as
    seven fields with ``IDUM`` omitted::

        CARD("%10lf%10lf%10lf%10d%10d%10d%10d", LSD_XSJFP, LSD_YSJFP,
             LSD_ZSJFP, LSD_PSID, LSD_NODE1, LSD_NODE2, LSD_NODE3);

    so a reader following it puts NODE1 in the ``IDUM`` slot (columns 41-50)
    and drops NODE3 entirely. Vol I R17 p.3-51 is explicit that field 5 is
    ``IDUM``, "Dummy field (variable not used)". Following the cfg would
    silently move the jet axis node into the focal-point slot.
    """
    f3 = _card(raw, i3, fixed=True, n=8, w=10)
    ab.atmost = _ffield(f3, 0, 0.0)
    ab.atmosp = _ffield(f3, 1, 0.0)
    ab.atmosd = _ffield(f3, 2, 0.0)
    ab.gc = _ffield(f3, 3, 0.0)
    # "Conversion constant, CC. EQ.0.0: set to 1.0" (Vol I R17 p.3-47).
    ab.cc = _ffield(f3, 4, 1.0) or 1.0
    ab.hconv = _ffield(f3, 5, 0.0)
    # T0/Pext live on card 3 for this model; mirror them onto the shared slots
    # so the batch-1 surface/vent machinery keeps one name for one quantity.
    ab.t_ext = ab.atmost
    ab.pe = ab.atmosp

    f4 = _card(raw, i3 + 1, fixed=True, n=8, w=10)
    ab.c23 = _ffield(f4, 0, 0.0)
    ab.lcc23 = to_int(f4[1]) if len(f4) > 1 else 0
    ab.a23 = _ffield(f4, 2, 0.0)
    ab.lca23 = to_int(f4[3]) if len(f4) > 3 else 0
    ab.cp23 = _ffield(f4, 4, 0.0)
    ab.lcp23 = to_int(f4[5]) if len(f4) > 5 else 0
    ab.ap23 = _ffield(f4, 6, 0.0)
    ab.lcap23 = to_int(f4[7]) if len(f4) > 7 else 0

    f5 = _card(raw, i3 + 2, fixed=True, n=8, w=10)
    ab.opt = to_int(f5[0]) if f5 else 0
    ab.pvent = _ffield(f5, 1, 0.0)
    ab.ngas = to_int(f5[2]) if len(f5) > 2 else 0
    ab.lcefr = to_int(f5[3]) if len(f5) > 3 else 0
    ab.lcidm0 = to_int(f5[4]) if len(f5) > 4 else 0
    ab.vntopt = to_int(f5[5]) if len(f5) > 5 else 0

    i = i3 + 3
    stride = _hybrid_gas_stride(raw, i, ab.ngas)
    if ab.ngas <= 0:
        state.warn(
            f"*{block.keyword}: NGAS={ab.ngas} on card 5, so this inflator "
            "declares NO gas species at all. No /MAT/GAS and no /PROP/INJECT1 "
            "row can be built and the bag receives nothing — it stays at its "
            "ambient state. NGAS counts the initial air too (Vol I R17 "
            "p.3-48), so even a pure-air bag states 1.")
    for k in range(max(0, ab.ngas)):
        g = _card(raw, i, fixed=True, n=8, w=10)
        sp = GasSpecies(
            index=k + 1,
            lcid_m=to_int(g[0]) if g else 0,
            lcid_t=to_int(g[1]) if len(g) > 1 else 0,
            # cell 2 is a documented BLANK — MW is at columns 31-40.
            mw=_ffield(g, 3, 0.0),
            initm=_ffield(g, 4, 0.0),
            hc_a=_ffield(g, 5, 0.0),
            hc_b=_ffield(g, 6, 0.0),
            hc_c=_ffield(g, 7, 0.0),
        )
        if stride == 2:
            sp.fmass = _ffield(_card(raw, i + 1, fixed=True, n=8, w=10), 0, 0.0)
        ab.species.append(sp)
        i += stride

    if "_JETTING" in block.keyword:
        ab.jetting = True
        f6 = _card(raw, i, fixed=True, n=8, w=10)
        ab.jet_fp = (_ffield(f6, 0, 0.0), _ffield(f6, 1, 0.0),
                     _ffield(f6, 2, 0.0))
        ab.jet_vh = (_ffield(f6, 3, 0.0), _ffield(f6, 4, 0.0),
                     _ffield(f6, 5, 0.0))
        ab.jet_ca = _ffield(f6, 6, 0.0)
        ab.jet_beta = _ffield(f6, 7, 0.0)
        f7 = _card(raw, i + 1, fixed=True, n=8, w=10)
        ab.jet_sfp = (_ffield(f7, 0, 0.0), _ffield(f7, 1, 0.0),
                      _ffield(f7, 2, 0.0))
        ab.jet_psid = to_int(f7[3]) if len(f7) > 3 else 0
        # f7[4] is IDUM — read by the MANUAL, not by the cfg (see the
        # docstring). NODE1/2/3 are fields 6, 7 and 8.
        ab.jet_n1 = to_int(f7[5]) if len(f7) > 5 else 0
        ab.jet_n2 = to_int(f7[6]) if len(f7) > 6 else 0
        ab.jet_n3 = to_int(f7[7]) if len(f7) > 7 else 0
        if "_CM" in block.keyword:
            f8 = _card(raw, i + 2, fixed=True, n=8, w=10)
            ab.jet_nreact = to_int(f8[0]) if f8 else 0


def _airbag_particle_id_row(block: Block) -> int:
    """Index of the ``_ID``/``_TITLE`` card in an ``*AIRBAG_PARTICLE`` block.

    **1 on an ``_MPP`` deck, 0 otherwise.** The Card Summary of Vol I R17
    p.3-94 lists *"Card MPP. Include this card if using the MPP keyword
    option"* BEFORE *"Card ID. Include this card if ... the ID or TITLE
    keyword options"*, so on ``*AIRBAG_PARTICLE_MPP_ID`` the ``SX SY SZ`` line
    is ``raw[0]`` and ``ABID``/``HEADING`` is ``raw[1]``.

    Only the card COUNT is unaffected by that order (``_title_offset`` plus
    one for ``_MPP`` reaches card 1 either way); the IDENTITY of ``raw[0]`` is
    not. Reading the ABID off the MPP card gives the bag ``SY`` as its id and
    ``SZ`` as its title, which then makes every ``*AIRBAG_INTERACTION`` naming
    the real ABID report it as undefined — and lets ``_rewrite_id_header``
    add an ``*INCLUDE_TRANSFORM`` offset to ``SX``.
    """
    return 1 if "_MPP" in block.keyword and _has_id_or_title(block) else 0


def _has_id_or_title(block: Block) -> bool:
    return _has_id(block) or _has_title(block)


def _airbag_particle_cards(block: Block, raw: List[str]):
    """``{name: index}`` of every ``*AIRBAG_PARTICLE`` card.

    THE one source for the layout: the handler reads its values at these
    indices and ``assembly._off_airbag_particle`` rewrites its ids at the same
    ones, so a card-order change cannot leave the two disagreeing.

    For the ``STYPE2 == 2`` case — whose SIDUP block repeats once per part of
    the SD2 set, a count that only exists after the *SET_PART is resolved,
    i.e. after parsing — the walk stops and returns a PARTIAL result:
    ``{"partial": True, "card1": <index>}`` with every other key empty. Card 1
    is above the block that cannot be walked, so its index is known and is
    handed back rather than thrown away; recomputing it as
    ``_title_offset(block)`` would miss the ``_MPP`` and ``_TIME`` prelude
    cards and read card 1 off ``SX SY SZ``.

    Keys: ``partial``, ``card1``, ``card3``, ``card7``, and — each -1 when
    the option that carries it is absent — ``seg``, ``jnode``, ``air``,
    ``lcmass``; plus the lists ``vents``, ``gases``, ``orifices``.
    """
    kw = block.keyword
    i = _title_offset(block)
    if "_MPP" in kw:
        i += 1
    if "_TIME" in kw:
        i += 1
    i1 = i
    f1 = _card(raw, i, fixed=True, n=8, w=10)
    i += 1
    stype2 = to_int(f1[3]) if len(f1) > 3 else 0
    npdata = to_int(f1[5]) if len(f1) > 5 else 0
    seg = -1
    if "_SEGMENT" in kw:
        seg = i
        i += 1
    i3 = i
    f3 = _card(raw, i, fixed=True, n=8, w=10)
    i += 1
    unit = to_int(f3[1]) if len(f3) > 1 else 0
    nvent = to_int(f3[5]) if len(f3) > 5 else 0
    jnode = -1
    if "_JET" in kw and "_JETTING" not in kw:
        jnode = i
        i += 1
    # The two optional continuation cards are self-identifying: LS-DYNA reads
    # them only when the line STARTS with '+'. Skipping by content rather than
    # by option keeps the walk right for a deck that writes one and not the
    # other.
    while i < len(raw) and raw[i].lstrip().startswith("+"):
        i += 1
    if unit == 3:
        i += 1
    i7 = i
    f7 = _card(raw, i, fixed=True, n=8, w=10)
    i += 1
    iair = to_int(f7[0]) if f7 else 0
    ngas = to_int(f7[1]) if len(f7) > 1 else 0
    norif = to_int(f7[2]) if len(f7) > 2 else 0
    if stype2 == 2:
        return {"partial": True, "card1": i1, "card3": -1, "card7": -1,
                "seg": seg, "jnode": jnode, "air": -1, "lcmass": -1,
                "vents": [], "gases": [], "orifices": []}
    i += max(0, npdata)
    vents = list(range(i, i + max(0, nvent)))
    i += max(0, nvent)
    air = -1
    if iair != 0:
        air = i
        i += 1
    lcmass = -1
    if "_MOLEFRACTION" in kw:
        lcmass = i
        i += 1
    gases = list(range(i, i + max(0, ngas)))
    i += max(0, ngas)
    orifices: List[int] = []
    for _k in range(max(0, norif)):
        orifices.append(i)
        o = _card(raw, i, fixed=True, n=8, w=10)
        i += 1
        # Card 14.1 exists only for the two shell-normal-WITH-OFFSET forms.
        if _ffield(o, 2, 0.0) in (-3.0, -4.0):
            i += 1
    return {"partial": False, "card1": i1, "card3": i3, "card7": i7,
            "seg": seg, "jnode": jnode, "air": air, "lcmass": lcmass,
            "vents": vents, "gases": gases, "orifices": orifices}


def _read_airbag_particle_indices(block: Block, raw: List[str]):
    """``(card1, vent rows, gas rows, orifice rows, partial)`` — the id-bearing
    cards of a ``*AIRBAG_PARTICLE``, for the ``*INCLUDE_TRANSFORM`` rewriter.

    ``partial`` is True for the ``STYPE2 == 2`` stack, where only ``card1`` is
    known. Card 1 still carries ``SID1`` and ``SID2``, so it is offset; the
    rows below it are not, and the caller says so."""
    idx = _airbag_particle_cards(block, raw)
    return (idx["card1"], idx["vents"], idx["gases"], idx["orifices"],
            idx["partial"])


def _read_airbag_particle(ab: "Airbag", block: Block, raw: List[str],
                          state: ConversionState) -> None:
    """``*AIRBAG_PARTICLE{_MPP}{_DECOMPOSITION}{_MOLEFRACTION}{_SEGMENT}
    {_TIME}`` — a card stack that shares NOTHING with the other six models.

    Card 1 is ``SD1 STYPE1 SD2 STYPE2 BLOCK NPDATA FRIC IRPD``, **not** the
    ``SID SIDTYP RBID VSCA PSCA VINI MWD SPSF`` every other ``*AIRBAG_`` model
    carries, so there is no RBID walk above card 3 and ``_airbag_prelude`` must
    not be used here. Reading it as the shared card 1 would take STYPE1 for a
    SIDTYP, SD2 for an RBID and then walk three sensor cards that do not exist.

    The walk, in order (Vol I R17 pp.3-97…3-110)::

        [_MPP]           SX SY SZ
        [_ID/_TITLE]     BAGID + HEADING          (consumed by _title_offset)
        [_TIME]          BIRTH DEATH
        card 1           SD1 STYPE1 SD2 STYPE2 BLOCK NPDATA FRIC IRPD
        [_SEGMENT]       SEGSID
        card 3           NP UNIT VISFLG TATM PATM NVENT TEND TSW
        [_JET]           JNODE
        ['+' cards]      the two optional continuation cards
        [UNIT == 3]      MASS TIME LENGTH
        card 7           IAIR NGAS NORIF NID1 NID2 NID3 CHM CD_EXT
        [STYPE2 == 2]    SIDUP STYUP PFRAC LINKING   (x |SD2|)
        card 9           SIDH STYPEH HCONV ...       (x NPDATA)
        card 10          SID3 STYPE3 C23 LCTC23 LCPC23 ENH_V PPOP  (x NVENT)
        [IAIR != 0]      PAIR TAIR XMAIR AAIR BAIR CAIR NPAIR NPRLX
        [_MOLEFRACTION]  LCMASS
        card 13          LCMi LCTi XMi Ai Bi Ci INFGi              (x NGAS)
        card 14          NIDi ANi VDi CAi INFOi IMOM IANG CHM_ID   (x NORIF)
        [VDi in -3/-4]   XOFF

    Three of those counts come off cards this walk has already read (NVENT,
    NGAS, NORIF) and one — the ``STYPE2 == 2`` block — is ``|SD2|`` rows, a
    count that only exists once the *SET_PART is resolved, which is after
    parsing. That case therefore ABANDONS the rest of the walk with a warning
    rather than guessing: everything past it would be read one card out of
    place, and a mis-parsed gas card is a wrong inflator on a run that
    terminates normally.

    The walk itself lives in :func:`_airbag_particle_cards`, which the
    ``*INCLUDE_TRANSFORM`` id rewriter uses as well — one source for the card
    order, so the reader and the offsetter cannot drift.

    ``_MPP``'s ``SX SY SZ`` card is listed BEFORE the ``_ID``/``_TITLE`` card
    (Vol I R17 p.3-94 Card Summary), and the two are interchangeable ONLY for
    the card COUNT — ``_title_offset`` plus one for ``_MPP`` reaches card 1
    from either order. Which line is which still matters, because ``raw[0]``
    is also what the ABID/HEADING reader and the ``*INCLUDE_TRANSFORM``
    header rewriter take: see :func:`_airbag_particle_id_row`, which both of
    them use instead of assuming ``raw[0]``. ``SX``/``SY``/``SZ`` themselves
    are the MPP decomposition-reference point and are dropped.
    """
    kw = block.keyword
    idx = _airbag_particle_cards(block, raw)
    f1 = _card(raw, idx["card1"], fixed=True, n=8, w=10)
    ab.sd1 = to_int(f1[0]) if f1 else 0
    ab.stype1 = to_int(f1[1]) if len(f1) > 1 else 0
    ab.sd2 = to_int(f1[2]) if len(f1) > 2 else 0
    ab.stype2 = to_int(f1[3]) if len(f1) > 3 else 0
    ab.block = to_int(f1[4]) if len(f1) > 4 else 0
    ab.npdata = to_int(f1[5]) if len(f1) > 5 else 0
    ab.fric = _ffield(f1, 6, 0.0)
    ab.irpd = to_int(f1[7]) if len(f1) > 7 else 0
    # The bag scope, in the shared slots the surface machinery reads. STYPE1
    # is NOT LS-DYNA's SIDTYP: 0 is a PART here (and a *SET_SEGMENT there), so
    # sidtyp is pinned to the PART family and the bare-*PART fallback in
    # _airbag_surface_eids covers STYPE1 = 0.
    ab.sid = ab.sd1
    ab.sidtyp = 1
    # SEGSID and JNODE sit ABOVE the SIDUP block, so both are reliably located
    # even when the walk is abandoned below. Read here so they are named by
    # value either way.
    if idx["seg"] >= 0:
        ab.segsid = to_int(_card(raw, idx["seg"], fixed=True, n=8, w=10)[0])
    if idx["jnode"] >= 0:
        ab.jnode = to_int(_card(raw, idx["jnode"], fixed=True, n=8, w=10)[0])
    if idx["partial"]:
        state.warn(
            f"*{kw}: STYPE2=2 selects the SIDUP/STYUP/PFRAC/LINKING card "
            "block, which repeats once per PART in the SD2 set — a count that "
            "only exists after the *SET_PART is resolved, i.e. after parsing. "
            "The card walk is ABANDONED here: the vent, gas and orifice cards "
            "below it would every one be read out of place, and a mis-parsed "
            "inflator is a wrong bag on a run that terminates normally. "
            "Nothing past card 1 is read, so the bag converts with no gas and "
            "no vents. Restate SD2 with STYPE2 = 0 or 1 to convert it.")
        return

    f3 = _card(raw, idx["card3"], fixed=True, n=8, w=10)
    ab.np = to_int(f3[0]) if f3 else 0
    ab.unit = to_int(f3[1]) if len(f3) > 1 else 0
    ab.visflg = to_int(f3[2]) if len(f3) > 2 else 0
    ab.tatm = _ffield(f3, 3, 293.0)
    ab.patm = _ffield(f3, 4, 0.0)
    ab.nvent = to_int(f3[5]) if len(f3) > 5 else 0
    ab.tend = _ffield(f3, 6, 0.0)
    ab.tsw = _ffield(f3, 7, 0.0)

    f7 = _card(raw, idx["card7"], fixed=True, n=8, w=10)
    ab.iair = to_int(f7[0]) if f7 else 0
    ab.ngas = to_int(f7[1]) if len(f7) > 1 else 0
    ab.norif = to_int(f7[2]) if len(f7) > 2 else 0
    ab.nid1 = to_int(f7[3]) if len(f7) > 3 else 0
    ab.nid2 = to_int(f7[4]) if len(f7) > 4 else 0
    ab.nid3 = to_int(f7[5]) if len(f7) > 5 else 0
    ab.chm = to_int(f7[6]) if len(f7) > 6 else 0
    ab.cd_ext = _ffield(f7, 7, 0.0)

    if ab.npdata > 0:
        # The per-part HCONV/PFRIC/SDFBLK/KP/INIP/CP rows. Counted and
        # SKIPPED, which is strictly better than dyna2rad: its reader cfg has
        # the whole block commented out (airbag_Particle.cfg:1068-1086), so a
        # deck with NPDATA > 0 has these rows consumed as VENT cards.
        state.warn(
            f"*{kw}: NPDATA={ab.npdata} defines per-part heat-transfer and "
            "particle-friction data (HCONV PFRIC SDFBLK KP INIP CP). Those "
            f"{ab.npdata} card(s) are counted and SKIPPED — the finite-volume "
            "bag has no per-part particle friction and its single Hconv is a "
            "whole-bag column. The rest of the card stack is read at the right "
            "offset, which dyna2rad's own reader is not: its NPDATA block is "
            "commented out, so those rows are consumed as vent cards there.")

    for r in idx["vents"]:
        v = _card(raw, r, fixed=True, n=8, w=10)
        ab.vent_rows.append((
            to_int(v[0]) if v else 0,                      # SID3
            to_int(v[1]) if len(v) > 1 else 0,             # STYPE3
            _ffield(v, 2, 1.0),                            # C23, default 1.0
            to_int(v[3]) if len(v) > 3 else 0,             # LCTC23
            to_int(v[4]) if len(v) > 4 else 0,             # LCPC23
            to_int(v[5]) if len(v) > 5 else 0,             # ENH_V
            _ffield(v, 6, 0.0),                            # PPOP
        ))

    if idx["air"] >= 0:
        fa = _card(raw, idx["air"], fixed=True, n=8, w=10)
        ab.pair = _ffield(fa, 0, 0.0)
        ab.tair = _ffield(fa, 1, 0.0)
        ab.xmair = _ffield(fa, 2, 0.0)
        ab.aair = _ffield(fa, 3, 0.0)
        ab.bair = _ffield(fa, 4, 0.0)
        ab.cair = _ffield(fa, 5, 0.0)
        ab.npair = to_int(fa[6]) if len(fa) > 6 else 0
        ab.nprlx = to_int(fa[7]) if len(fa) > 7 else 0

    if idx["lcmass"] >= 0:
        ab.mole_fraction = True
        fm = _card(raw, idx["lcmass"], fixed=True, n=8, w=10)
        ab.lcmass = to_int(fm[0]) if fm else 0
    ab.decomposition = "_DECOMPOSITION" in kw
    ab.inflation = "_INFLATION" in kw

    for k, r in enumerate(idx["gases"]):
        g = _card(raw, r, fixed=True, n=8, w=10)
        ab.species.append(GasSpecies(
            index=k + 1,
            lcid_m=to_int(g[0]) if g else 0,
            lcid_t=to_int(g[1]) if len(g) > 1 else 0,
            mw=_ffield(g, 2, 0.0),
            hc_a=_ffield(g, 3, 0.0),
            hc_b=_ffield(g, 4, 0.0),
            hc_c=_ffield(g, 5, 0.0),
            infg=to_int(g[6]) if len(g) > 6 else 1,
        ))

    for r in idx["orifices"]:
        o = _card(raw, r, fixed=True, n=8, w=10)
        vdi = _ffield(o, 2, 0.0)
        ab.orifices.append((
            to_int(o[0]) if o else 0,                      # NIDi
            _ffield(o, 1, 0.0),                            # ANi
            vdi,                                           # VDi
            _ffield(o, 3, 30.0),                           # CAi, default 30 deg
            to_int(o[4]) if len(o) > 4 else 1,             # INFOi, default 1
            to_int(o[5]) if len(o) > 5 else 0,             # IMOM
            to_int(o[6]) if len(o) > 6 else 0,             # IANG
            to_int(o[7]) if len(o) > 7 else 0,             # CHM_ID
        ))


def handle_airbag_interaction(block: Block, state: ConversionState) -> None:
    """``*AIRBAG_INTERACTION[_ID][_TITLE]`` → one ``Nbag`` row in EACH of the
    two ``/MONVOL/COMMU1`` its partners are promoted to.

    ONE card::

        AB1(1-10) AB2(11-20) AREA(21-30) SF(31-40) PID(41-50) LCID(51-60)
        IFLOW(61-70) EXCP(71-80)

    **``EXCP`` is read by the MANUAL, not by the reader cfg.**
    ``Keyword971/CONTROL_VOLUME/airbag_interaction.cfg`` ``FORMAT(Keyword971)``
    writes only seven fields::

        CARD("%10d%10d%10lg%10lg%10d%10d%10d", ... LSD_IFLOW);

    so the eighth column is dropped there. Vol I R17 documents it.

    dyna2rad does not convert this keyword at all — ``grep`` over the whole
    ``reader/source/dyna2rad`` tree returns zero hits for
    ``AIRBAG_INTERACTION`` — so everything below is k2rad exceeding the
    reference converter rather than following it.
    """
    raw = block.raw
    offset = _title_offset(block)
    title = _read_title(block, default="AIRBAG_INTERACTION")
    if _has_id(block) and raw:
        _iid, id_title = _id_heading_card(raw[0])
        title = id_title or title
    f = _card(raw, offset, fixed=True, n=8, w=10)
    it = AirbagInteraction(
        ab1=to_int(f[0]) if f else 0,
        ab2=to_int(f[1]) if len(f) > 1 else 0,
        area=_ffield(f, 2, 0.0),
        sf=_ffield(f, 3, 0.0),
        pid=to_int(f[4]) if len(f) > 4 else 0,
        lcid=to_int(f[5]) if len(f) > 5 else 0,
        iflow=to_int(f[6]) if len(f) > 6 else 0,
        excp=to_int(f[7]) if len(f) > 7 else 0,
        keyword=block.keyword, title=title,
    )
    state.airbag_interactions.append(it)


def handle_airbag(block: Block, state: ConversionState) -> None:
    """``*AIRBAG_<MODEL>[_ID][_TITLE]`` → one ``/MONVOL``.

    Five models, one handler, because card 1 (SID SIDTYP RBID VSCA PSCA VINI
    MWD SPSF) and the RBID card walk above it are identical on all of them and
    the per-model card 3 is disjoint. The Radioss target per model:

      SIMPLE_PRESSURE_VOLUME  → /MONVOL/PRES
      SIMPLE_AIRBAG_MODEL     → /MONVOL/AIRBAG1 + /MAT/GAS + /PROP/INJECT1
      ADIABATIC_GAS_MODEL     → /MONVOL/GAS
      LOAD_CURVE              → /MONVOL/PRES (pressure vs TIME)
      LINEAR_FLUID            → /MONVOL/LFLUID

    ``SIDTYP`` is inverted relative to intuition: **0 = *SET_SEGMENT**,
    non-zero = *SET_PART. Both are resolved to the OWNING SHELL ELEMENTS by
    ``writer/monvol.py`` — a /SURF/SEG external surface is starter ERROR 18 and
    the run aborts (``check_surf.F:55-62``).
    """
    raw = block.raw
    offset = _title_offset(block)
    model = _AIRBAG_MODELS[_airbag_base_keyword(block.keyword)]
    title = _read_title(block, default=f"AIRBAG_{model}")
    airbag_id = 0
    if model == "PARTICLE":
        # PARTICLE's card 1 is SD1 STYPE1 SD2 STYPE2 ..., not the shared
        # SID SIDTYP RBID ..., so it neither takes the RBID walk nor the
        # shared card-1 reader. Its whole stack is read in one place.
        #
        # Its header card is not always raw[0] either: _MPP's SX/SY/SZ card is
        # listed BEFORE the _ID/_TITLE card (Vol I R17 p.3-94 Card Summary),
        # so _airbag_particle_id_row says which line carries ABID/HEADING.
        hdr = _airbag_particle_id_row(block)
        if hdr and len(raw) > hdr:
            title = (" ".join(parse_free(raw[hdr])[1:]) if _has_id(block)
                     else raw[hdr].strip()) or f"AIRBAG_{model}"
        ab = Airbag(airbag_id=0, model=model, title=title,
                    keyword=block.keyword)
        if _has_id(block) and len(raw) > hdr:
            ab.airbag_id, id_title = _id_heading_card(raw[hdr])
            ab.title = id_title or f"AIRBAG_{model}"
        _read_airbag_particle(ab, block, raw, state)
        state.airbags.append(ab)
        return
    if _has_id(block) and raw:
        # ABID(I10) + HEADING(A70): a real deck writes the heading at column 11
        # with no separating space, and a free whitespace split then fuses the
        # two ("        42Driver airbag" -> ['42Driver', 'airbag'], ABID = 0).
        # _id_heading_card is the repo's column-first reader for exactly that
        # card shape, free-format fallback included.
        airbag_id, id_title = _id_heading_card(raw[0])
        title = id_title or f"AIRBAG_{model}"

    f1, i3 = _airbag_prelude(raw, offset)

    def flt(f, k, dflt=0.0):
        return _ffield(f, k, dflt)

    def integer(f, k):
        return to_int(f[k]) if len(f) > k else 0

    ab = Airbag(
        airbag_id=airbag_id, model=model, title=title, keyword=block.keyword,
        sid=integer(f1, 0), sidtyp=integer(f1, 1), rbid=integer(f1, 2),
        # VSCA/PSCA default to 1.0 on a BLANK cell; an explicit 0.0 is also
        # LS-DYNA's 1.0 ("Volume scale factor (default = 1.0)" — a zero volume
        # scale is not a thing), and real decks write both (airfilled.sphere.k
        # states 0.0, airbag.deploy.k states 1.0).
        vsca=flt(f1, 3, 1.0) or 1.0, psca=flt(f1, 4, 1.0) or 1.0,
        vini=flt(f1, 5), mwd=flt(f1, 6), spsf=flt(f1, 7),
    )

    if model == "HYBRID":
        _read_airbag_hybrid(ab, block, raw, i3, state)
        state.airbags.append(ab)
        return

    f3 = _card(raw, i3, fixed=True, n=8, w=10)
    if model == "SIMPLE_PRESSURE_VOLUME":
        ab.cn = flt(f3, 0)
        ab.beta = flt(f3, 1)
        ab.lcid = integer(f3, 2)
        ab.lciddr = integer(f3, 3)
    elif model == "SIMPLE_AIRBAG_MODEL":
        ab.cv = flt(f3, 0)
        ab.cp = flt(f3, 1)
        ab.t = flt(f3, 2)
        ab.lcid = integer(f3, 3)
        ab.mu = flt(f3, 4)
        ab.area = flt(f3, 5)
        ab.pe = flt(f3, 6)
        ab.ro = flt(f3, 7)
        # Card 4 has TWO layouts, chosen by CV: 4a (CV == 0) is
        # "LOU T_EXT A B MW GASC" and 4b (CV != 0) is LOU alone. Both are ONE
        # card, so nothing after it shifts — but reading 4a's columns under
        # CV != 0 would invent an ambient temperature and a molar Cp the deck
        # never stated.
        f4 = _card(raw, i3 + 1, fixed=True, n=8, w=10)
        ab.lou = integer(f4, 0)
        if ab.cv == 0.0:
            ab.t_ext = flt(f4, 1)
            ab.hc_a = flt(f4, 2)
            ab.hc_b = flt(f4, 3)
            ab.mw = flt(f4, 4)
            ab.gasc = flt(f4, 5)
        elif any(flt(f4, k) != 0.0 for k in range(1, 6)):
            state.warn(
                f"*{block.keyword}: CV={ab.cv:g} is non-zero, so LS-DYNA reads "
                "card 4 in its 4b layout — LOU alone — but the card carries "
                "non-zero values in the T_EXT/A/B/MW/GASC columns of the 4a "
                "layout. Those columns are IGNORED (LS-DYNA ignores them too). "
                "The gas is built from CV and CP directly; set CV=0 if the "
                "molar A/B/MW form was meant.")
    elif model == "ADIABATIC_GAS_MODEL":
        ab.psf = flt(f3, 0)
        ab.lcid = integer(f3, 1)
        ab.gamma = flt(f3, 2)
        ab.p0 = flt(f3, 3)
        ab.pe = flt(f3, 4)
        ab.ro = flt(f3, 5)
    elif model == "LOAD_CURVE":
        ab.stime = flt(f3, 0)
        ab.lcid = integer(f3, 1)
        ab.ro = flt(f3, 2)
        ab.pe = flt(f3, 3)
        ab.p0 = flt(f3, 4)
        ab.t = flt(f3, 5)
        ab.t0 = flt(f3, 6)
    else:                                    # LINEAR_FLUID
        ab.bulk = flt(f3, 0)
        ab.ro = flt(f3, 1)
        ab.lcint = integer(f3, 2)
        ab.lcoutt = integer(f3, 3)
        ab.lcoutp = integer(f3, 4)
        ab.lcfit = integer(f3, 5)
        ab.lcbulk = integer(f3, 6)
        ab.lcid = integer(f3, 7)
        f4 = _card(raw, i3 + 1, fixed=True, n=8, w=10)
        ab.p_limit = flt(f4, 0)
        ab.p_limlc = integer(f4, 1)
        ab.nonull = integer(f4, 2)

    state.airbags.append(ab)


def handle_airbag_unsupported(block: Block, state: ConversionState) -> None:
    """An ``*AIRBAG_<MODEL>`` this batch does not convert — named, not skipped.

    An airbag that vanishes into ``skipped_keywords`` is not a missing output
    card: the bag never inflates, and the deck runs to NORMAL TERMINATION with
    the fabric flapping loose. Every unmodelled model therefore gets a handler
    that says which one it is and what the Radioss counterpart would be.
    """
    base = block.keyword
    reason = _AIRBAG_UNSUPPORTED.get(base)
    if reason is None:
        for kw, why in _AIRBAG_UNSUPPORTED.items():
            if base.startswith(kw):
                reason = why
                break
    if reason is None:
        reason = "no Radioss counterpart is emitted by this batch"
    state.warn(
        f"*{base} is NOT converted: {reason}. NOTHING is emitted for it — the "
        "monitored volume is absent, so the bag never inflates and the run "
        "terminates normally with an empty bag. The mesh, materials and "
        "contacts of the deck are unaffected.")
    state.note_recognized_not_emitted(
        base, "airbag model outside batch 1 (PRES / AIRBAG1 / GAS / LFLUID) — "
              "no /MONVOL is emitted and the bag does not inflate")


#: The ``*DEFINE_CPM_*`` family (Vol I R17 §17): the EXTENDED inputs of the
#: Corpuscular Particle Method bag, each one a side card of
#: ``*AIRBAG_PARTICLE`` rather than a model of its own. None of it is
#: convertible — Radioss's ``/MONVOL/FVMBAG*`` is a finite-volume bag, not a
#: particle one, and it has no per-vent, per-chamber or per-species extension
#: slots to receive them — but a CPM side card that disappears into the
#: generic ``skipped_keywords`` list is a vent, a chamber or a gas property
#: that silently stops applying while the bag still converts. Named here so
#: the log says WHICH one and WHAT it cost. Purposes are the manual's own.
_DEFINE_CPM_UNSUPPORTED = {
    "DEFINE_CPM_BAG_INTERACTION":
        "energy flow from a source particle bag to a sink control-volume bag "
        "through their common vent parts (p.17-88). The two bags stay "
        "thermodynamically independent — use *AIRBAG_INTERACTION, which this "
        "converter does read, if the coupling matters",
    "DEFINE_CPM_CHAMBER":
        "the airbag CHAMBERS for particle initialization and chamber "
        "interaction (p.17-90). The bag is emitted as ONE volume, so a "
        "multi-chamber bag loses its internal partitions and fills uniformly",
    "DEFINE_CPM_GAS_PROPERTIES":
        "extended gas thermodynamic properties for CPM bags (p.17-93). The "
        "gas keeps the A/B/C polynomial stated on the *AIRBAG_PARTICLE card "
        "itself",
    "DEFINE_CPM_NPDATA":
        "the extended per-part NPDATA parameters — heat transfer and particle "
        "friction (p.17-96). *AIRBAG_PARTICLE's own NPDATA count is already "
        "warned about and skipped by the same reasoning",
    "DEFINE_CPM_SWITCH_REGION":
        "regions where particle-to-particle collision is switched off over "
        "stated intervals (p.17-98). It has no meaning without particles",
    "DEFINE_CPM_VENT":
        "the extended vent-hole options (p.17-99). A negative C23 on an "
        "*AIRBAG_PARTICLE vent row NAMES one of these, and that row is warned "
        "about separately — its vent coefficient falls back to 1, so the hole "
        "opens over the whole of its named surface",
}


def handle_define_cpm_unsupported(block: Block,
                                  state: ConversionState) -> None:
    """A ``*DEFINE_CPM_*`` side card — named, not silently skipped.

    Registered rather than left to the generic unsupported-keyword list for
    the same reason the unmodelled ``*AIRBAG_*`` models are: the deck still
    converts and still runs, so the only sign that a chamber, a vent option or
    a gas property has stopped applying is the log line that says so.
    """
    kw = block.keyword
    reason = _DEFINE_CPM_UNSUPPORTED.get(
        kw, "an extended input of the Corpuscular Particle Method bag")
    state.warn(
        f"*{kw} is NOT converted: it states {reason}. NOTHING is emitted for "
        "it. The *AIRBAG_PARTICLE bag it belongs to still converts (to "
        "/MONVOL/FVMBAG2, or to /MONVOL/AIRBAG1 under "
        "--airbag-particle-uniform), so the run terminates normally with this "
        "input simply absent.")
    state.note_recognized_not_emitted(
        kw, "a *DEFINE_CPM_* extended input of the particle bag — Radioss's "
            "finite-volume /MONVOL has no slot for it and nothing is emitted")


def handle_airbag_reference_geometry(block: Block,
                                     state: ConversionState) -> None:
    """``*AIRBAG_REFERENCE_GEOMETRY[_ID][_BIRTH][_RDT]`` → /XREF per part.

    Card order is FIXED even though the option order in the keyword is not
    (Vol I R16): the ``_ID`` card (ID SX SY SZ NIDO IOUT) comes first, then the
    ``_BIRTH`` card (BIRTH), then the node rows.

    The node rows are **NID(I10) X(E20) Y(E20) Z(E20)** — twenty-column
    coordinates, not the sixteen of *NODE. Slicing them at 16 would read each
    coordinate four columns short and silently move every reference node.
    """
    kw = block.keyword
    ref = AirbagRefGeometry(keyword=kw,
                            has_id="_ID" in kw or _has_id(block),
                            has_rdt="_RDT" in kw)
    raw = block.raw
    i = 0
    if ref.has_id:
        f = _card(raw, i, fixed=True, n=6, w=10)
        i += 1
        ref.sx = _ffield(f, 1, 1.0) or 1.0
        ref.sy = _ffield(f, 2, 1.0) or 1.0
        ref.sz = _ffield(f, 3, 1.0) or 1.0
        ref.nid0 = to_int(f[4]) if len(f) > 4 else 0
    if "_BIRTH" in kw:
        f = _card(raw, i, fixed=True, n=1, w=10)
        i += 1
        ref.birth = to_float(f[0]) if f else 0.0
    for line in raw[i:]:
        if not line.strip():
            continue
        nid = to_int(line[0:10])
        if nid <= 0:
            continue
        ref.nodes[nid] = (to_float(line[10:30]), to_float(line[30:50]),
                          to_float(line[50:70]))
    if ref.nodes:
        state.airbag_ref_geoms.append(ref)
    else:
        state.warn(
            f"*{kw}: no node rows parsed — no /XREF is emitted for this block, "
            "so the airbag starts stress-free at its MODELLED coordinates "
            "instead of at the reference ones.")


def handle_airbag_shell_reference_geometry(block: Block,
                                           state: ConversionState) -> None:
    """``*AIRBAG_SHELL_REFERENCE_GEOMETRY[_ID][_RDT]`` → /EREF/SHELL + /SH3N.

    Element rows are ``EID PID N1 N2 N3 N4``, all I10. PID is read and then
    DISCARDED — "the part ID is not used in this section" (Vol I R16) — because
    Radioss takes the part from the ``/EREF`` header, and the owning part is
    the one the ELEMENT really belongs to.
    """
    kw = block.keyword
    ref = AirbagShellRefGeometry(keyword=kw,
                                 has_id="_ID" in kw or _has_id(block),
                                 has_rdt="_RDT" in kw)
    raw = block.raw
    i = 0
    if ref.has_id:
        f = _card(raw, i, fixed=True, n=6, w=10)
        i += 1
        ref.sx = _ffield(f, 1, 1.0) or 1.0
        ref.sy = _ffield(f, 2, 1.0) or 1.0
        ref.sz = _ffield(f, 3, 1.0) or 1.0
        ref.nid0 = to_int(f[4]) if len(f) > 4 else 0
    for idx in range(i, len(raw)):
        if not raw[idx].strip():
            continue
        f = _card(raw, idx, fixed=True, n=6, w=10)
        eid = to_int(f[0]) if f else 0
        if eid <= 0:
            continue
        nodes = [to_int(f[k]) for k in range(2, 6) if len(f) > k]
        ref.elems.append((eid, [n for n in nodes if n > 0]))
    if ref.elems:
        state.airbag_shell_ref_geoms.append(ref)
    else:
        state.warn(
            f"*{kw}: no element rows parsed — no /EREF is emitted for this "
            "block.")


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
        # Same glued-negative-coordinate hazard as *NODE, and the same three
        # tests: re-slice the fixed columns when the whitespace split
        # under-counts, leaves an over-long merged token, or welds the node id
        # onto the first coordinate (four ordinary-looking tokens whose FIRST
        # one is not an integer). Here the `nid > 0` guard below turned that
        # third case into a silent DROP rather than a phantom node 0 —
        # different symptom, same cause. See handle_node.
        if len(f) < 4 or any(len(t) > 16 for t in f[1:4]) \
                or not _free_node_id(f[0]):
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
    """*MAT_DAMPER_VISCOUS (MAT_S02): MID DC → /PROP/TYPE4 damping C."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=2, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_DAMPER_VISCOUS: empty card – skipped")
        return
    mid = to_int(f[0])
    dc = to_float(f[1]) if len(f) > 1 else 0.0
    state.mat_damper_viscous[mid] = MatDamperViscous(mid, dc)


def handle_mat_spring_elastoplastic(block: Block, state: ConversionState) -> None:
    """*MAT_SPRING_ELASTOPLASTIC (MAT_S03): MID K KT FY → /PROP/TYPE4 K1 = K,
    H1 = 1 and a synthesized 5-point elastic-plastic force function."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=4, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_SPRING_ELASTOPLASTIC: empty card – skipped")
        return
    mid = to_int(f[0])
    g = lambda i: to_float(f[i]) if len(f) > i else 0.0
    state.mat_spring_elastoplastic[mid] = MatSpringElastoplastic(
        mid, g(1), g(2), g(3))


def handle_mat_damper_nonlinear_viscous(block: Block,
                                        state: ConversionState) -> None:
    """*MAT_DAMPER_NONLINEAR_VISCOUS (MAT_S05): MID LCDR → /PROP/TYPE4
    fct_ID41 (the h(rate) damping-force function)."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=2, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_DAMPER_NONLINEAR_VISCOUS: empty card – skipped")
        return
    mid = to_int(f[0])
    state.mat_damper_nl_viscous[mid] = MatDamperNonlinearViscous(
        mid, to_int(f[1]) if len(f) > 1 else 0)


def handle_mat_spring_general_nonlinear(block: Block,
                                        state: ConversionState) -> None:
    """*MAT_SPRING_GENERAL_NONLINEAR (MAT_S06): MID LCDL LCDU BETA TYI CYI →
    /PROP/TYPE4 fct_ID11 = LCDL, fct_ID31 = LCDU, H1 = 6."""
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=6, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_SPRING_GENERAL_NONLINEAR: empty card – skipped")
        return
    mid = to_int(f[0])
    gi = lambda i: to_int(f[i]) if len(f) > i else 0
    gf = lambda i: to_float(f[i]) if len(f) > i else 0.0
    state.mat_spring_general_nl[mid] = MatSpringGeneralNonlinear(
        mid, gi(1), gi(2), gf(3), gf(4), gf(5))


def handle_mat_spring_inelastic(block: Block, state: ConversionState) -> None:
    """*MAT_SPRING_INELASTIC (MAT_S08): MID LCFD KU CTF → /PROP/TYPE4 K1 = KU
    plus the one-sided LCFD mirrored into the opposite quadrant.

    CTF's LS-DYNA default is +1.0 (compression only); a blank column therefore
    means compression-only, not "unset". Only CTF < 0 selects tension-only,
    which is also the test dyna2rad makes (``if (lsdCTF == -1)``).
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=4, w=10)
    if not f or not f[0].strip():
        state.warn("*MAT_SPRING_INELASTIC: empty card – skipped")
        return
    mid = to_int(f[0])
    state.mat_spring_inelastic[mid] = MatSpringInelastic(
        mid,
        to_int(f[1]) if len(f) > 1 else 0,
        to_float(f[2]) if len(f) > 2 else 0.0,
        _ffield(f, 3, 1.0))


# ── *SECTION_BEAM ELFORM=6 discrete-beam materials ───────────────────────────
#
# Every one of these is a 6-DOF (or 1-DOF) SPRING, not a beam: the LS-DYNA card
# carries stiffnesses / load curves per local DOF and the *SECTION_BEAM card 2f
# carries only a lumped VOL and INER. They convert to /PROP/TYPE8 (SPR_GENE,
# skew oriented — the /MAT/LAW108 card body with an absolute Mass instead of
# RHO×Volume) or /PROP/TYPE13 (SPR_BEAM, node oriented — likewise for LAW113).

def _six(f: List[str], start: int = 0, n: int = 6) -> List[float]:
    """*n* consecutive float fields from *start*, zero-filled — every discrete
    beam card is a plain run of six local-DOF cells (r,s,t then Rr,Rs,Rt)."""
    return [to_float(f[start + i]) if len(f) > start + i else 0.0
            for i in range(n)]


def _six_i(f: List[str], start: int = 0, n: int = 6) -> List[int]:
    """The integer form of _six — the LCID runs. The manual types the discrete
    beam curve columns ``F`` on some cards (LS-DYNA reads them as reals and
    rounds), so parse as a number and use as an id."""
    return [to_int(f[start + i]) if len(f) > start + i else 0
            for i in range(n)]


def handle_mat_linear_elastic_discrete_beam(block: Block,
                                            state: ConversionState) -> None:
    """*MAT_LINEAR_ELASTIC_DISCRETE_BEAM (MAT_066) → a 6-DOF spring property.

    Card1: MID RO TKR TKS TKT RKR RKS RKT
    Card2: TDR TDS TDT RDR RDS RDT
    Card3: FOR FOS FOT MOR MOS MOT
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_LINEAR_ELASTIC_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    state.mat_dbeam_linear[mid] = MatDiscreteBeamLinear(
        mid,
        to_float(f1[1]) if len(f1) > 1 else 0.0,
        _six(f1, 2),
        _six(_card(raw, offset + 1, fixed=True, n=8, w=10)),
        _six(_card(raw, offset + 2, fixed=True, n=8, w=10)))


def handle_mat_nonlinear_elastic_discrete_beam(block: Block,
                                               state: ConversionState) -> None:
    """*MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM (MAT_067) → a 6-DOF spring property.

    Card1: MID RO LCIDTR LCIDTS LCIDTT LCIDRR LCIDRS LCIDRT
    Card2: LCIDTDR LCIDTDS LCIDTDT LCIDRDR LCIDRDS LCIDRDT
    Card3: FOR FOS FOT MOR MOS MOT
    Card4: FFAILR FFAILS FFAILT MFAILR MFAILS MFAILT
    Card5: UFAILR UFAILS UFAILT TFAILR TFAILS TFAILT

    Manual R17 marks cards 3-5 as required; the shipped cfg models them as
    optional FREE_CARDs, so they are read POSITIONALLY here (a missing card
    just yields zeros).
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    c = lambda i: _card(raw, offset + i, fixed=True, n=8, w=10)
    state.mat_dbeam_nl_elastic[mid] = MatDiscreteBeamNonlinearElastic(
        mid,
        to_float(f1[1]) if len(f1) > 1 else 0.0,
        _six_i(f1, 2), _six_i(c(1)), _six(c(2)), _six(c(3)), _six(c(4)))


def handle_mat_nonlinear_plastic_discrete_beam(block: Block,
                                               state: ConversionState) -> None:
    """*MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM (MAT_068) → a 6-DOF spring property.

    Card1: MID RO TKR TKS TKT RKR RKS RKT
    Card2: TDR TDS TDT RDR RDS RDT RYLD
    Card3: LCPDR LCPDS LCPDT LCPMR LCPMS LCPMT
    Card4: FFAILR … MFAILT   Card5: UFAILR … TFAILT   Card6: FOR … MOT

    ``RYLD`` (card 2 cols 61-70) exists only from Keyword971_R12.0 on; the base
    cfg stops at RDT. Reading the column unconditionally is safe — an older
    deck leaves it blank.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    c = lambda i: _card(raw, offset + i, fixed=True, n=8, w=10)
    c2 = c(1)
    state.mat_dbeam_nl_plastic[mid] = MatDiscreteBeamNonlinearPlastic(
        mid,
        to_float(f1[1]) if len(f1) > 1 else 0.0,
        _six(f1, 2), _six(c2),
        to_float(c2[6]) if len(c2) > 6 else 0.0,
        _six_i(c(2)), _six(c(3)), _six(c(4)), _six(c(5)))


def handle_mat_cable_discrete_beam(block: Block, state: ConversionState) -> None:
    """*MAT_CABLE_DISCRETE_BEAM (MAT_071) → a tension-only 1-DOF spring.

    Card1: MID RO E LCID F0 TMAXF0 TRAMP IREAD
    Card2 (only when IREAD > 0): OUTPUT [TSTART [FRACL0 MXEPS MXFRC]] — output
    control and strain/force limits with no Radioss slot; warn-dropped.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_CABLE_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    g = lambda i: to_float(f1[i]) if len(f1) > i else 0.0
    m = MatCableDiscreteBeam(
        mid, g(1), g(2), to_int(f1[3]) if len(f1) > 3 else 0, g(4), g(5), g(6),
        to_int(f1[7]) if len(f1) > 7 else 0)
    state.mat_cable_dbeam[mid] = m
    if m.iread > 0:
        state.warn(f"*MAT_CABLE_DISCRETE_BEAM mid={mid}: IREAD={m.iread} card 2 "
                   "(OUTPUT/TSTART/FRACL0/MXEPS/MXFRC) has no /PROP/TYPE13 "
                   "slot — cable output control and the strain/force limits "
                   "are DROPPED (the cable keeps the CDF/TDF-free 'never "
                   "fails' behaviour).")


def handle_mat_elastic_spring_discrete_beam(block: Block,
                                            state: ConversionState) -> None:
    """*MAT_ELASTIC_SPRING_DISCRETE_BEAM (MAT_074) → a 1-DOF spring.

    Card1: MID RO K F0 D CDF TDF
    Card2: FLCID HLCID C1 C2 DLE GLCID
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_ELASTIC_SPRING_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    g = lambda f, i: to_float(f[i]) if len(f) > i else 0.0
    gi = lambda f, i: to_int(f[i]) if len(f) > i else 0
    state.mat_elastic_spring_dbeam[mid] = MatElasticSpringDiscreteBeam(
        mid, g(f1, 1), g(f1, 2), g(f1, 3), g(f1, 4), g(f1, 5), g(f1, 6),
        gi(f2, 0), gi(f2, 1), g(f2, 2), g(f2, 3), g(f2, 4), gi(f2, 5))


def handle_mat_general_nonlinear_6dof(block: Block,
                                      state: ConversionState) -> None:
    """*MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM (MAT_119) → a 6-DOF spring.

    Cards 1-8 (Manual Vol I R17):
      1: MID RO KT KR IUNLD OFFSET DAMPF IFLAG
      2: LCIDTR LCIDTS LCIDTT LCIDRR LCIDRS LCIDRT      (loading)
      3: LCIDTUR … LCIDRUT                               (unloading)
      4: LCIDTDR … LCIDRDT                               (damping)
      5: LCIDTER … LCIDRET                               (elastic/scale)
      6: UTFAILR … WTFAILT FCRIT
      7: UCFAILR … WCFAILT
      8: IUR IUS IUT IWR IWS IWT
    Cards 9-15 exist only for IFLAG=2 (crushable-frame buckling) or IUNLD=2 and
    are NOT in the shipped Keyword971 cfg — they are counted (so the block is
    fully consumed) and reported, never converted.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    # c(n) is the n-th card AFTER card 1, so the manual's card 6 (UTFAIL* +
    # FCRIT) is c(5) and card 7 (UCFAIL*) is c(6).
    c = lambda i: _card(raw, offset + i, fixed=True, n=8, w=10)
    g = lambda f, i: to_float(f[i]) if len(f) > i else 0.0
    c6 = c(5)
    m = MatGeneralNonlinear6dof(
        mid, g(f1, 1), g(f1, 2), g(f1, 3),
        to_int(f1[4]) if len(f1) > 4 else 0,
        g(f1, 5), g(f1, 6),
        to_int(f1[7]) if len(f1) > 7 else 0,
        _six_i(c(1)), _six_i(c(2)), _six_i(c(3)), _six_i(c(4)),
        _six(c6), _six(c(6)),
        to_float(c6[6]) if len(c6) > 6 else 0.0)
    state.mat_gnl_6dof[mid] = m
    if m.iflag == 2:
        state.warn(f"*MAT_119 mid={mid}: IFLAG=2 (crushable-frame buckling "
                   "formulation) needs cards 9-15 (LM*/LUM*/KUM*/E1*/E2* "
                   "moment-interaction tables) that no Radioss spring law can "
                   "express — the material is converted as the ordinary 6-DOF "
                   "spring (IFLAG=0) and the buckling interaction is LOST.")
    elif m.iunld == 2:
        state.warn(f"*MAT_119 mid={mid}: IUNLD=2 additionally reads card 15 "
                   "(KTS KTT KRS KRT, the unloading stiffnesses); those four "
                   "values have no per-DOF unloading-stiffness slot on the "
                   "Radioss spring card and are DROPPED — unloading follows "
                   "the H=7 elastic-hysteresis rule with K1..K6 instead.")


def handle_mat_general_nonlinear_1dof(block: Block,
                                      state: ConversionState) -> None:
    """*MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM (MAT_121) → a 1-DOF spring.

    Card1: MID RO K IUNLD OFFSET DAMPF
    Card2: LCIDT LCIDTU LCIDTD LCIDTE
    Card3: UTFAIL UCFAIL IU
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
    f3 = _card(raw, offset + 2, fixed=True, n=8, w=10)
    g = lambda f, i: to_float(f[i]) if len(f) > i else 0.0
    gi = lambda f, i: to_int(f[i]) if len(f) > i else 0
    state.mat_gnl_1dof[mid] = MatGeneralNonlinear1dof(
        mid, g(f1, 1), g(f1, 2), gi(f1, 3), g(f1, 4), g(f1, 5),
        gi(f2, 0), gi(f2, 1), gi(f2, 2), gi(f2, 3), g(f3, 0), g(f3, 1))


def handle_mat_general_spring_discrete_beam(block: Block,
                                            state: ConversionState) -> None:
    """*MAT_GENERAL_SPRING_DISCRETE_BEAM (MAT_196) → a 6-DOF spring.

    Card1:  MID RO … MDFAIL(61-70) DOSPOT(71-80)
    Card2i: DOF TYPE K D CDF TDF
    Card3i: FLCID HLCID C1 C2 DLE GLCID

    Cards 2 and 3 form a repeating PAIR, one per active DOF, up to six pairs.
    The shipped ``Keyword971/MAT/mat_196.cfg`` card 1 reads only MID and RO —
    MDFAIL and DOSPOT are read here from the manual's columns.
    """
    offset = _title_offset(block)
    raw = block.raw
    f1 = _card(raw, offset, fixed=True, n=8, w=10)
    if not f1 or not f1[0].strip():
        state.warn("*MAT_GENERAL_SPRING_DISCRETE_BEAM: empty card – skipped")
        return
    mid = to_int(f1[0])
    m = MatGeneralSpringDiscreteBeam(
        mid,
        to_float(f1[1]) if len(f1) > 1 else 0.0,
        to_int(f1[6]) if len(f1) > 6 else 0,
        to_int(f1[7]) if len(f1) > 7 else 0)
    idx = offset + 1
    seen: set = set()
    while idx < len(raw) and len(m.dofs) < 6:
        fa = _card(raw, idx, fixed=True, n=8, w=10)
        if not fa or not fa[0].strip():
            break
        dof = to_int(fa[0])
        if dof < 1 or dof > 6:
            state.warn(f"*MAT_196 mid={mid}: the line '{raw[idx].strip()}' read "
                       f"as a DOF card names DOF={dof}, which is outside 1-6 — "
                       "the per-DOF walk STOPPED there and every later card "
                       "PAIR in this block is UNREAD.")
            break
        if dof in seen:
            state.warn(f"*MAT_196 mid={mid}: DOF {dof} is defined more than "
                       "once — the LAST pair wins (LS-DYNA allows each DOF at "
                       "most once).")
        seen.add(dof)
        fb = _card(raw, idx + 1, fixed=True, n=8, w=10)
        g = lambda f, i: to_float(f[i]) if len(f) > i else 0.0
        gi = lambda f, i: to_int(f[i]) if len(f) > i else 0
        m.dofs.append((dof, gi(fa, 1), g(fa, 2), g(fa, 3), g(fa, 4), g(fa, 5),
                       gi(fb, 0), gi(fb, 1), g(fb, 2), g(fb, 3), g(fb, 4),
                       gi(fb, 5)))
        idx += 2
    state.mat_general_spring_dbeam[mid] = m


#: *SECTION_BEAM ELFORM=6 materials that OpenRadioss has no spring law for.
#: Recorded (not converted) so the connector writer can name the physics the
#: deck loses; dyna2rad routes all of them to its ``default:`` branch, which
#: produces no usable /MAT and says nothing (convertmats.cxx:527-554, with the
#: unsupported-material error at :530 commented out).
_UNSUPPORTED_DBEAM_KEYWORDS = {
    "MAT_SID_DAMPER_DISCRETE_BEAM": "MAT_069",
    "MAT_069": "MAT_069", "MAT_69": "MAT_069",
    "MAT_HYDRAULIC_GAS_DAMPER_DISCRETE_BEAM": "MAT_070",
    "MAT_070": "MAT_070", "MAT_70": "MAT_070",
    "MAT_ELASTIC_6DOF_SPRING_DISCRETE_BEAM": "MAT_093",
    "MAT_093": "MAT_093", "MAT_93": "MAT_093",
    "MAT_INELASTIC_SPRING_DISCRETE_BEAM": "MAT_094",
    "MAT_094": "MAT_094", "MAT_94": "MAT_094",
    "MAT_INELASTIC_6DOF_SPRING_DISCRETE_BEAM": "MAT_095",
    "MAT_095": "MAT_095", "MAT_95": "MAT_095",
    "MAT_GENERAL_JOINT_DISCRETE_BEAM": "MAT_097",
    "MAT_097": "MAT_097", "MAT_97": "MAT_097",
    "MAT_1DOF_GENERALIZED_SPRING": "MAT_146",
    "MAT_146": "MAT_146",
}


def handle_mat_unsupported_discrete_beam(block: Block,
                                         state: ConversionState) -> None:
    """A discrete-beam material with NO OpenRadioss spring counterpart.

    Only MID and RO are read — every one of these cards puts them in the first
    two columns. Registering the keyword (instead of letting it fall into
    ``skipped_keywords``) is what lets the ELFORM=6 connector writer say WHICH
    device the deck loses and emit an inert spring in its place — a *PART left
    with no material and a /PROP/BEAM built from a section that states no
    cross-section is starter ERROR 314-317, i.e. no run at all.
    """
    offset = _title_offset(block)
    f = _card(block.raw, offset, fixed=True, n=2, w=10)
    if not f or not f[0].strip():
        state.warn(f"*{block.keyword}: empty material card – skipped")
        return
    state.mat_unsupported_dbeam[to_int(f[0])] = (
        _UNSUPPORTED_DBEAM_KEYWORDS.get(block.keyword, block.keyword),
        to_float(f[1]) if len(f) > 1 else 0.0)


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
    in state.table_1d_ids.
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
            state.table_1d_ids.add(tid)


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


def _pload_sf_default(state: ConversionState, kw: str, ref: str,
                      warned: bool) -> bool:
    """Report SF = 0.0 being read as the documented default 1.0, once per block.

    Every *LOAD_SEGMENT/_SET/*LOAD_SHELL card documents ``SF ... Default 1.``
    (Manual Vol I R16 p.33-99 / p.33-115 / p.3421) and LS-DYNA applies its card
    defaults on a ZERO test, not a blank test — the same keyword family spells
    that out for DEATH ("EQ.0.0: default set to 1e28", p.752). So an explicit
    0.0 is the default, and blank/0.0 cannot be told apart downstream.

    It is warned rather than silently substituted because a zeroed SF is also a
    common way of switching a load off by hand, and /PLOAD cannot express either
    reading of a zero: ``hm_read_pload.F:167`` is ``IF (FCY == ZERO) FCY =
    FAC_FCY``, so a card written with ``Fscale_y = 0`` runs the curve at FULL
    unit-system amplitude — and for *LOAD_SHELL, whose sign is flipped, with the
    pressure pointing the wrong way as well.
    """
    if warned:
        return True
    state.warn(
        f"*{kw}: SF = 0.0 on {ref} is read as the card's documented default "
        "1.0 (LS-DYNA applies its defaults on a zero test — the same keyword "
        "family says so explicitly for DEATH, \"EQ.0.0: default set to 1e28\"). "
        "If the zero was meant to switch the load OFF, delete the row instead: "
        "/PLOAD cannot carry a zero scale either, because hm_read_pload.F:167 "
        "replaces a zero ordinate scale with the unit-system factor and the "
        "load would run at FULL amplitude.")
    return True


def handle_load_segment(block: Block, state: ConversionState) -> None:
    """*LOAD_SEGMENT[_ID] → /PLOAD on the segment's own node order.

    Card 2: ``LCID SF AT N1 N2 N3 N4 N5`` (Manual Vol I R16 p.33-99, defaults
    ``none 1. 0.``). ``AT`` is the arrival time and SHIFTS the curve — "the
    function value of the load curves will be evaluated at the offset time given
    by the difference of the solution time and AT" (Remark 3) — so it becomes a
    /SENSOR/TIME in the /PLOAD ``sens_ID`` slot, exactly as on the _SET sibling.
    k2rad <= PR #116 never read the field: the pressure started at t = 0 with no
    diagnostic at all.
    """
    raw = block.raw
    # _ID variant: first line is "id  title", data starts at index 1
    data = raw[1:] if _has_id(block) else raw
    warned_sf = False
    warned_at = False
    # One card per loaded segment; the card may REPEAT inside one keyword.
    for i in range(len(data)):
        if not data[i].strip():       # blank card placeholder → skip
            continue
        # Card: lcid sf at n1 n2 n3 n4 n5  (n5 ignored)
        f1   = _card(data, i, fixed=True, n=8, w=10)
        lcid = to_int(f1[0])   if f1 else 0
        sf   = _ffield(f1, 1, 1.0)
        at   = to_float(f1[2]) if len(f1) > 2 else 0.0
        nodes = [to_int(f1[j]) for j in range(3, min(7, len(f1)))]
        while nodes and nodes[-1] == 0:
            nodes.pop()
        if len(nodes) >= 3 and lcid > 0:
            if sf == 0.0:
                warned_sf = _pload_sf_default(
                    state, block.keyword, f"the segment on curve {lcid}",
                    warned_sf)
                sf = 1.0
            if at < 0.0 and not warned_at:
                state.warn(
                    f"*{block.keyword}: negative arrival time AT={at:g} on the "
                    f"segment on curve {lcid} — ignored (the load applies from "
                    "t=0). /SENSOR/TIME's Tdelay cannot be negative.")
                warned_at = True
            state.pressure_loads.append(
                PressureLoad(lcid, sf, nodes, at=max(at, 0.0)))


def handle_load_segment_set(block: Block, state: ConversionState) -> None:
    """*LOAD_SEGMENT_SET[_ID] → /PLOAD on the referenced *SET_SEGMENT surface.

    Card: ssid lcid sf at  (one card per loaded segment set; may repeat).
      ssid = *SET_SEGMENT id (the loaded surface)
      lcid = load curve (pressure vs time)
      sf   = curve scale factor (default 1.0)
      at   = arrival/activation time → a /SENSOR/TIME with Tdelay = at in the
             /PLOAD sens_ID slot (the load is zero for t < at and the curve is
             then read at t - at; see ShellPressureLoad). k2rad <= PR #116
             dropped it with a warning, having no /SENSOR emitter at all. The
             shift itself is the manual's own reading of an arrival time
             (*LOAD_SEGMENT Remark 3, p.33-101: "evaluated at the offset time
             given by the difference of the solution time and AT").
    The segments are resolved from state.segment_sets at write time, so the
    *SET_SEGMENT may appear anywhere in the deck.
    """
    raw = block.raw
    data = raw[1:] if _has_id(block) else raw
    warned_at = False
    warned_sf = False
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
        if sf == 0.0:
            warned_sf = _pload_sf_default(state, block.keyword,
                                          f"segment set {ssid}", warned_sf)
            sf = 1.0
        if at < 0.0 and not warned_at:
            state.warn(f"*{block.keyword}: negative arrival time AT={at:g} on "
                       f"segment set {ssid} — ignored (the load applies from "
                       "t=0). /SENSOR/TIME's Tdelay cannot be negative.")
            warned_at = True
        state.segment_set_pressure_loads.append(
            SegmentSetPressureLoad(ssid, lcid, sf, max(at, 0.0)))


def handle_load_shell(block: Block, state: ConversionState) -> None:
    """*LOAD_SHELL_ELEMENT / *LOAD_SHELL_SET[_ID] → /SURF/SEG + /PLOAD.

    Card: ``EID|ESID  LCID  SF  AT`` (4 x I10/F10, Manual Vol I R16 p.3421,
    defaults ``none none 1. 0.``). The _ELEMENT form repeats the card once per
    loaded shell, each with its OWN LCID/SF/AT; the _SET form takes a *SET_SHELL
    id.

    Two dyna2rad defects are deliberately NOT reproduced:

      * ``ConvertLoadShell`` writes the magnitude under the solver name
        ``Fscale_Y``, but that is only the COMMENT label on the /PLOAD card —
        the cfg attribute is ``magnitude`` (``radioss2021/LOADS/pload.cfg:25``,
        ``DEFAULTS { magnitude = 1.; }``). The solver-name map is case-sensitive
        (``mv_descriptor.cpp:93``), so the value is parked in a stray sub-object
        and never reaches the card: the /PLOAD keeps the cfg default of ``1.``
        — SF is lost AND the sign inverts.
      * multi-row _ELEMENT blocks are collapsed onto row 0's LCID/SF/AT
        (``sdiIdentifier("SF")`` without a row index reads only the first
        sub-object, ``sdiModelViewPO.h:3015-3021``), silently applying one
        curve to every listed element. k2rad groups by ``(lcid, sf, at)``
        instead, so every row keeps its own load.

    ``LCID = -1`` selects the Brode function and ``-2`` ConWep
    (*LOAD_BRODE / *LOAD_BLAST): those are blast sources for /LOAD/PBLAST, not
    a /PLOAD pressure curve, so they are refused rather than written as
    ``functIDT = -1``.
    """
    kw = block.keyword
    is_set = kw.endswith("_SET")
    raw = block.raw
    warned_sf = False
    warned_at = False
    for i in range(_title_offset(block), len(raw)):
        if not raw[i].strip():            # blank card placeholder → skip
            continue
        f = _card(raw, i, fixed=True, n=8, w=10)
        if not f:
            continue
        ref  = to_int(f[0])
        lcid = to_int(f[1]) if len(f) > 1 else 0
        sf   = _ffield(f, 2, 1.0)
        at   = to_float(f[3]) if len(f) > 3 else 0.0
        if ref <= 0:
            state.warn(
                f"*{kw}: a row names {'shell set' if is_set else 'shell'} id "
                f"{ref} (blank or non-positive), which cannot be resolved — the "
                "row carries no /PLOAD. EID/ESID has no default (Manual Vol I "
                "R16 p.3421).")
            continue
        if lcid in (-1, -2):
            state.warn(
                f"*{kw}: LCID={lcid} selects the "
                + ("Brode" if lcid == -1 else "ConWep")
                + " air-blast function, not a *DEFINE_CURVE (Manual Vol I R16 "
                "p.3421). That is a /LOAD/PBLAST source, not a /PLOAD pressure "
                f"curve — the load on {'set' if is_set else 'element'} {ref} is "
                "NOT converted. Use *LOAD_BLAST_ENHANCED + "
                "*LOAD_BLAST_SEGMENT_SET, which k2rad maps to /LOAD/PBLAST.")
            continue
        if lcid <= 0:
            state.warn(f"*{kw}: no pressure curve (LCID={lcid}) on "
                       f"{'set' if is_set else 'element'} {ref} — skipped "
                       "(/PLOAD has no constant-pressure form: fct_IDT is "
                       "mandatory, hm_read_pload.F).")
            continue
        if sf == 0.0:
            warned_sf = _pload_sf_default(
                state, kw, f"{'set' if is_set else 'element'} {ref}", warned_sf)
            sf = 1.0
        if at < 0.0 and not warned_at:
            state.warn(
                f"*{kw}: negative arrival time AT={at:g} on "
                f"{'set' if is_set else 'element'} {ref} — ignored (the load "
                "applies from t=0). /SENSOR/TIME's Tdelay cannot be negative.")
            warned_at = True
        at = max(at, 0.0)
        # The *SET_SHELL may legitimately appear after the load in the deck, so
        # the set is recorded and resolved at write time (the same deferral
        # *LOAD_SEGMENT_SET uses for *SET_SEGMENT).
        state.shell_pressure_loads.append(
            ShellPressureLoad([] if is_set else [ref], lcid, sf, at,
                              ssid=ref if is_set else 0, source=f"*{kw}"))


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
    like LCDR on *LOAD_GRAVITY_PART).

    The sibling forms share this handler because card 1a.1 has the SAME seven-
    field column grid for all of X/Y/Z/RX/RY/RZ/VECTOR (the CFG writes X/Y/Z
    with cols 31-60 blank, but the grid is identical):

      * ``_RX/_RY/_RZ`` -> /LOAD/CENTRI + /FRAME/FIX (see LoadBodyRot);
      * ``_VECTOR``     -> /GRAV + /SKEW/FIX, and reads card 1a.2 V1 V2 V3;
      * ``_GENERALIZED`` has a different card set (per-part scaling) and no
        Radioss equivalent -> explicit warn-skip.
    """
    kw = block.keyword                       # e.g. "LOAD_BODY_Y"
    suffix = kw.rsplit("_", 1)[-1] if "_" in kw else ""
    if suffix not in ("X", "Y", "Z", "RX", "RY", "RZ", "VECTOR"):
        state.warn(
            f"*{kw}: no OpenRadioss equivalent — skipped. /GRAV takes a "
            "uniform base acceleration along one axis and /LOAD/CENTRI a single "
            "angular velocity about one frame axis; *LOAD_BODY_GENERALIZED's "
            "per-part scaling (Manual Vol I R16 p.33-25: use it for per-part "
            "body loads) cannot be expressed as either. Split it into one "
            "*LOAD_GRAVITY_PART per part, which k2rad does convert.")
        state.skipped_keywords.append(kw)
        return
    raw = block.raw
    offset = _title_offset(block)
    f = _card(raw, offset, fixed=True, n=8, w=10)
    if not f:
        return
    lcid   = to_int(f[0])
    sf     = to_float(f[1]) if len(f) > 1 else 1.0
    lciddr = to_int(f[2]) if len(f) > 2 else 0
    xc     = to_float(f[3]) if len(f) > 3 else 0.0
    yc     = to_float(f[4]) if len(f) > 4 else 0.0
    zc     = to_float(f[5]) if len(f) > 5 else 0.0
    cid    = to_int(f[6]) if len(f) > 6 else 0
    if sf == 0.0:
        sf = 1.0
    if lcid <= 0:
        label = ("angular-velocity" if suffix in ("RX", "RY", "RZ")
                 else "acceleration")
        state.warn(f"*{kw}: no {label} curve (lcid={lcid}) — skipped.")
        return
    if lciddr:
        state.warn(f"*{kw}: dynamic-relaxation curve LCIDDR={lciddr} has no "
                   "OpenRadioss mapping - ignored (only the transient body "
                   "load is converted).")
    if suffix in ("RX", "RY", "RZ"):
        state.body_load_rots.append(
            LoadBodyRot(dir=suffix[1], lcid=lcid, sf=sf, cid=cid,
                        xc=xc, yc=yc, zc=zc))
        return
    if suffix == "VECTOR":
        # Card 1a.2: V1 V2 V3 — a DIRECTION, magnitude irrelevant.
        f2 = _card(raw, offset + 1, fixed=True, n=8, w=10)
        v = (to_float(f2[0]) if len(f2) > 0 else 0.0,
             to_float(f2[1]) if len(f2) > 1 else 0.0,
             to_float(f2[2]) if len(f2) > 2 else 0.0)
        if v == (0.0, 0.0, 0.0):
            state.warn(
                f"*{kw}: the direction vector V1 V2 V3 is zero (or its card is "
                "missing) — skipped. The Radioss dyna-reader silently turns a "
                "zero V into a global -X body load (convertloads.cxx:588-594), "
                "which is a load nobody asked for.")
            return
        state.body_load_vectors.append(
            LoadBodyVector(lcid=lcid, sf=sf, v=v, cid=cid,
                           xc=xc, yc=yc, zc=zc))
        return
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
                  ignored). Node order fixes the segment normal.

    **A triangle has TWO legal spellings and they are stored as ONE.** Vol I
    R17 *SET_SEGMENT p.43-63 verbatim: *"N4 - Nodal point n4. To define a
    triangular segment, set N4 = N3."*, and a trailing blank/zero is the other
    house style. Both collapse to a 3-node list here, so every consumer sees
    one spelling: ``_emit_surf_seg`` then writes ``n1 n2 n3 0`` and
    ``hm_read_surf.F:318-321`` (``IF(N4/=0) ... ELSE N4 = N3``) restores the
    degenerate corner inside the starter. Without the collapse the two
    spellings are two different segments to any set operation — a
    *SET_SEGMENT_ADD union over both keeps BOTH rows and applies the /PLOAD
    pressure on that face TWICE (measured against a one-row twin on a free
    plate, both 0 ERROR / NORMAL TERMINATION / 67 cycles: EXT-WORK 18.35 ->
    73.39 and K-ENERGY 17.68 -> 70.73, a factor of 4.0005, i.e. impulse
    x2.0001). It is also the same normalisation ``_shell_load_segments``
    (``writer/loads.py:4415``) already does on the *LOAD_SHELL path, where the
    collapse is spelled ``if len(nodes) >= 4 and nodes[3] == nodes[2]``.

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
        while len(nodes) > 3 and (nodes[-1] == 0 or nodes[-1] == nodes[-2]):
            nodes.pop()
        if len(nodes) >= 3 and all(n > 0 for n in nodes):
            segments.append(nodes)
            # A1/A2 are the PER-SEGMENT override of a
            # *CONTACT_TIEBREAK_SURFACE_TO_SURFACE's NFLS/SFLS (Vol I R17
            # p.11-72 Remark 1: "The failure fields, NFLS and SFLS, can be
            # overridden segment by segment on the *SET_SEGMENT or *SET_SHELL
            # data cards for the SURFA surface with A1 and A2"). Only the FACT
            # that the set states one is recorded — the tiebreak writer needs
            # it to decide whether the override is a loss to name, and no
            # converted card can hold a per-segment strength.
            #
            # The *SET_SHELL half of that sentence is a KNOWN UNNAMED loss, and
            # it is unreachable rather than merely unimplemented: `_tied_slave_
            # nids` has no shell-element-set arm at all (SSTYP 0/1 fall back to
            # segment set -> part -> part set -> node set), so a tiebreak whose
            # SURFA is a *SET_SHELL resolves to no nodes and is dropped OUTRIGHT
            # by `_make_tiebreak_interfaces` with its own message. Recording
            # *SET_SHELL DA1/DA2 here would be dead code until that resolver
            # grows the arm; when it does, this is the second half to add.
            if any(to_float(f[j]) for j in (4, 5) if len(f) > j):
                state.segment_set_attr_sids.add(sid)
    state.segment_sets[sid] = SegmentSet(sid, title, segments)


# ─────────────────────────────────────────────────────────────────────────────
# Blast loads
# ─────────────────────────────────────────────────────────────────────────────

#: *LOAD_BLAST_ENHANCED UNIT flag → the (mass, length, time) label triple for
#: /BEGIN, or None where the system has no clean OpenRadioss label.
#:
#: Transcribed from the pinned manual, Vol I R16 p.33-17 (identical in R17
#: p.33-17) — the FULL eight-row table, not the five-row LSTC note the earlier
#: version of this code carried:
#:
#:   EQ.1: pound-mass, foot, second, psi                     imperial
#:   EQ.2: kilogram, meter, second, Pascal (default)         -> kg  m   s
#:   EQ.3: dozen slugs (lbf-s2/in), inch, second, psi        imperial
#:   EQ.4: centimeters, grams, microseconds, Megabars        -> g   cm  mus
#:   EQ.5: user conversions will be supplied (see Card 2)    CFM/CFL/CFT/CFP
#:   EQ.6: kilogram, millimeter, millisecond, GPa            -> kg  mm  ms
#:   EQ.7: metric ton, millimeter, second, MPa               -> Mg  mm  s
#:   EQ.8: gram, millimeter, millisecond, MPa                -> g   mm  ms
#:
#: 6/7/8 are as physically consistent as 2 and 4 and every label they need is
#: already in the starter's grammar, so they map automatically too:
#:   6: kg*mm/ms^2 = kN, kN/mm^2 = GPa                       matches the manual
#:   7: Mg*mm/s^2  = N,  N/mm^2  = MPa                       matches the manual
#:   8: g*mm/ms^2  = N,  N/mm^2  = MPa                       matches the manual
#: 1 and 3 stay unmapped because an imperial base has no legal '*g'/'*m'/'*s'
#: label at all (see the grammar note in _blast_unit_system); 5 stays unmapped
#: because the deck's units live in the CFM/CFL/CFT/CFP factors on Card 2 and
#: nothing names them.
_BLAST_UNIT_SYSTEMS = {
    1: None,
    2: ("kg", "m", "s"),
    3: None,
    4: ("g", "cm", "mus"),
    5: None,
    6: ("kg", "mm", "ms"),
    7: ("Mg", "mm", "s"),
    8: ("g", "mm", "ms"),
}

#: The LEGACY *LOAD_BLAST card's IUNIT stops at 5 (Vol I R16 p.33-11/33-12:
#: the list ends "EQ.5: user conversions will be supplied" and runs straight
#: into ISURF). 6/7/8 exist on *LOAD_BLAST_ENHANCED only, so a legacy deck
#: carrying one is malformed and must warn rather than have a unit system
#: invented for it that LS-DYNA itself would not apply.
_LEGACY_BLAST_MAX_UNIT = 5


def _blast_unit_mapping_note() -> str:
    """The auto-mapped flags, rendered from the table so the user-facing
    warnings cannot drift away from what the code actually does."""
    return ", ".join(
        f"UNIT={flag} {'/'.join(labels)}"
        for flag, labels in sorted(_BLAST_UNIT_SYSTEMS.items())
        if labels is not None)


def _blast_unit_system(unit: int, legacy: bool = False):
    """Map a *LOAD_BLAST_ENHANCED UNIT flag to an OpenRadioss (mass, length,
    time) label triple for /BEGIN, or None when it has no clean mapping.

    The flag table itself is _BLAST_UNIT_SYSTEMS above. ``legacy=True`` is the
    older *LOAD_BLAST card, whose IUNIT is documented only up to 5.

    The TM5-1300 empirical formula is unit-dependent, so /LOAD/PBLAST reads the
    /BEGIN unit labels to convert its internal {cm, g, µs} data to model units —
    those labels must therefore match the deck's real units. Only the physically
    consistent flags get an automatic mapping.

    Every label here must be one the STARTER can parse, not merely one a human
    can read. unit_code.F:70-98 splits the %20s field into an SI prefix + a base
    letter and accepts a token of ONE, TWO or THREE characters only; anything
    longer takes the ELSE branch at :92-98, which blanks CUNIT and sets IERR1=0,
    and the test at :151-158 (last character must be 'g'/'m'/'s' per
    MASS/LENGTH/TIME, or IERR1==0) then raises ERROR 573 INVALID UNIT CODE.
    Microseconds are therefore ``mus`` (the label begin.cfg:127 itself lists),
    never ``micros``: measured on starter_win64, ``micros`` gives
      ERROR ID : 573 ** INVALID UNIT CODE / UNIT: micros - CODE: TIME
    on BOTH /BEGIN unit lines — the "2 GLOBAL UNITS ERROR(S)" that stops the run
    — and the factor it reports is 1.0E+00, i.e. it would silently have read
    seconds and been wrong by 1e6 had the run continued.
    Legal token = (prefix in {'', y z a f p n mu u m c d da h k K M G T P E Z Y})
    + (base in {g, m, s}); the same grammar the writer's _time_unit_in_seconds
    transcribes for the *CONTROL_UNITS side. (The two tables are deliberately
    NOT shared: handlers.py imports only .parser/.state, and reaching into
    k2rad.writer from a handler would invert the layer direction. Unifying them
    belongs in a units module of its own.)
    """
    if legacy and unit > _LEGACY_BLAST_MAX_UNIT:
        return None
    return _BLAST_UNIT_SYSTEMS.get(unit)


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
            f"OpenRadioss unit mapping (auto-mapped are "
            f"{_blast_unit_mapping_note()}; the imperial UNIT=1/3 have no legal "
            "Radioss unit label, and UNIT=5 states its units only as the "
            "CFM/CFL/CFT/CFP factors on Card 2). The TM5-1300 blast formula is "
            "unit-dependent, so set /BEGIN to the deck's real mass/length/time "
            "via convert(units=...) or /LOAD/PBLAST will compute wrong "
            "pressures.")


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
    # legacy=True: this card's IUNIT is documented 1..5 only, so the
    # *LOAD_BLAST_ENHANCED-only 6/7/8 must NOT be applied here.
    us = _blast_unit_system(iunit, legacy=True)
    if us is not None:
        state.blast_unit_system = us
    else:
        state.warn(
            f"*LOAD_BLAST: IUNIT={iunit} has no automatic OpenRadioss unit "
            "mapping (auto-mapped on this legacy card are IUNIT=2 kg/m/s and "
            "IUNIT=4 g/cm/mus; its IUNIT is documented 1..5 only — 6/7/8 are "
            "*LOAD_BLAST_ENHANCED extensions and are not applied here); set "
            "/BEGIN via convert(units=...) or /LOAD/PBLAST pressures will be "
            "wrong.")
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
        # Both triangle spellings collapse to one — see handle_set_segment.
        while len(nodes) > 3 and (nodes[-1] == 0 or nodes[-1] == nodes[-2]):
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


def _db_history_rows(block: Block) -> List[int]:
    """RAW indices of a *DATABASE_HISTORY_* block's data cards.

    Deliberately NOT ``_title_offset``: on this family ``_ID`` is a PER-ENTITY
    70-char HEADING beside every id (Vol I R16 p.16-112 Card 1b), not the
    card-level "id + title" header ``_title_offset`` assumes. Skipping raw[0]
    on an ``_ID`` card would drop the deck's FIRST requested channel — which is
    exactly what ``assembly._offset_block`` does today for the same reason, and
    why the *INCLUDE_TRANSFORM walk for this family is a callable that reuses
    this function (the #119 rule: both walks must agree on which line is a
    card, or the offsetter and the handler silently address different rows).

    Blank cards are dropped. That is what makes the ``_LOCAL_ID`` pairing below
    safe: an all-blank HEADING card is legal and disappears from this list, so
    the pairing claims its heading by RAW CONTIGUITY (``rows[k] == i + 1``)
    instead of "the next row", which would swallow the following entity card.
    """
    return [i for i, ln in enumerate(block.raw)
            if ln.strip() and not ln.lstrip().startswith("$")]


def _handle_db_history(block: Block, state: ConversionState, db_type: str) -> None:
    """Read one *DATABASE_HISTORY_<FAMILY>[_SET][_LOCAL][_ID] block.

    Four card layouts, all from ``Keyword971_R6.1/OUTPUTBLOCK/
    database_history_*.cfg`` and Vol I R16 p.16-110..16-115:

      plain / ``_SET``  free list, EIGHT ids per line, ``%10d``
      ``_ID``           one card per entity: ``%10d`` id + ``%-70s`` HEADING
      ``_LOCAL``        one card per entity: ``%10d%10d%10d%10d``
                        = ID, CID, REF, HFO
      ``_LOCAL_ID``     the same 4-field card, then a ``%-70s`` heading card

    The ``_ID`` card FUSES its two columns — ``   5000390Left Rear Seat`` is the
    literal layout in the Toyota Yaris deck — so the free split this function
    used for every spelling read ``5000390Left``, ``to_int`` returned 0, and
    EVERY requested channel was silently dropped; the writer then emitted an
    empty ``/TH/NODE`` group, which the starter ACCEPTS (1109 fires only for
    ``NVAR == 0``, hm_read_thgrne.F:123) and writes to the T01 holding zero
    entities — 94 lost channels on the Yaris deck, with no diagnostic at all.
    ``_id_heading_card``
    reads columns 1-10 as the id, with the free-format fallback for decks that
    write ``id  title``.

    HFO ("also write nodouthf") is read by the cfg and has no Radioss
    counterpart at all, so it is not stored.
    """
    ids: List[int] = []
    cids: List[int] = []
    refs: List[int] = []
    names: List[str] = []
    rows = _db_history_rows(block)
    is_id = "ID" in block.options
    is_local = db_type.endswith("_LOCAL")
    if is_local:
        k = 0
        while k < len(rows):
            i = rows[k]
            k += 1
            f = _card(block.raw, i, fixed=True, n=4, w=10)
            v = to_int(f[0]) if f else 0
            # Claim the HEADING card BEFORE the v <= 0 guard, exactly where
            # assembly._off_db_history(local=True) claims it — the #119 rule
            # again. Skipping the guard first left the heading in the walk, and
            # a heading whose columns 1-10 happen to parse ("9000      Beam A"
            # after a card with id 0) was then read as an entity id while the
            # offsetter had already consumed it. MEASURED on exactly that deck:
            # the handler invented entity 9000, swallowed the REAL next entity
            # card as that entity's heading, and the card lost BOTH channels.
            # RAW contiguity, never "the next row" — see _db_history_rows.
            claimed = is_id and k < len(rows) and rows[k] == i + 1
            if claimed:
                k += 1
            if v <= 0:
                continue
            ids.append(v)
            cids.append(to_int(f[1]) if len(f) > 1 else 0)
            refs.append(to_int(f[2]) if len(f) > 2 else 0)
            if is_id:
                names.append(block.raw[i + 1][:70].strip() if claimed else "")
    elif is_id:
        for i in rows:
            v, heading = _id_heading_card(block.raw[i])
            if v > 0:
                ids.append(v)
                names.append(heading[:70])
    else:
        for i in rows:
            for tok in parse_free(block.raw[i]):
                v = to_int(tok)
                if v > 0:
                    ids.append(v)
    state.db_histories.append(DbHistory(db_type, ids, cids, refs, names))


def handle_database_history_shell(block: Block, state: ConversionState) -> None:
    _handle_db_history(block, state, "SHELL")


def handle_database_history_solid(block: Block, state: ConversionState) -> None:
    _handle_db_history(block, state, "SOLID")


def handle_database_history_tshell(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_TSHELL → /TH/BRIC, the same block *_SOLID takes.

    A thick shell IS a /BRICK in the emitted deck (writer/tshell.py), and
    /TH/BRIC resolves brick ids, so the requested channels land exactly where
    the deck asked for them. Before the thick-shell batch this keyword was
    unroutable — the elements it names did not exist in the conversion at all —
    and it stayed in ``skipped_keywords`` on all nine r14 decks."""
    _handle_db_history(block, state, "TSHELL")


def handle_database_history_sph(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_SPH → /TH/SPHCEL.

    The ids are SPH element ids, which LS-DYNA and Radioss both force equal to
    the supporting NODE id, so no translation is needed — but every one of them
    must resolve to a /SPHCEL this conversion actually emitted. A dangling id is
    not a lost channel, it is starter ERROR 69 ("TH ELEMENT SELECTION ID=n DOES
    NOT EXIST", hm_read_thgrne.F:189) and the whole deck is refused; the writer
    intersects against ``state.sph_cell_ids`` for exactly that reason (the #106
    rule). dyna2rad copies the raw id list through with no check at all — its
    SPH branch is the only element branch in ``converttimehistory.cxx`` with no
    ``FindRadElement`` filter.

    Before this batch the keyword was unroutable (the elements it names did not
    exist in the conversion) and stayed in ``skipped_keywords``.
    """
    _handle_db_history(block, state, "SPH")


def handle_database_history_sph_set(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_SPH_SET → /TH/SPHCEL over the named *SET_NODEs.

    "IDn for NODE_SET, SPH_SET, and DES_SET refers to node set ID n defined
    using the *SET_NODE_{OPTION}" (Vol I R16), so these are SET ids, not
    particle ids — resolving them as particle ids would list a handful of set
    numbers as if they were cells and refuse the deck with ERROR 69. The writer
    expands them through ``state.node_sets`` and then applies the same
    emitted-cell screen.
    """
    _handle_db_history(block, state, "SPH_SET")


def handle_database_history_node(block: Block, state: ConversionState) -> None:
    _handle_db_history(block, state, "NODE")


def handle_database_history_beam(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_BEAM[_ID] → /TH/BEAM, or /TH/SPRING per element.

    The target group is decided PER ELEMENT, exactly as dyna2rad's
    ``FindRadElement`` fallback chain does (convertutils.cxx:286-338 tries
    /BEAM, then /SPRING, then /TRUSS, re-initialising the keyword INSIDE the
    loop at converttimehistory.cxx:246). k2rad needs all three links for its own
    reason: an *ELEMENT_BEAM on a *MAT_SPOTWELD part or on a *SECTION_BEAM
    ELFORM=6 part is emitted as a /SPRING, not a /BEAM, and one on a
    *SECTION_BEAM ELFORM=3 part is emitted as a /TRUSS, so one card can produce
    all three groups. ``writer/output.py::_th_beam_split`` does the split, on
    the producer registries filled at the write lines.
    """
    _handle_db_history(block, state, "BEAM")


def handle_database_history_beam_set(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_BEAM_SET → /TH/BEAM (+/TH/SPRING, +/TH/TRUSS) over the
    named sets.

    ``database_history_beam_set.cfg:25`` declares
    ``SUBTYPES = (/SETS/SET_COMPONENT_IDPOOL, /SETS/SET_BEAM_IDPOOL)``: the ids
    may be *SET_BEAM sets OR *SET_PART sets, and a part set expands to every
    beam of every named part — a ``*SECTION_BEAM`` ELFORM=3 part's elements
    included, because they stay in ``state.beam_elems`` and only the WRITE side
    splits them off into ``/TRUSS`` (see ``writer/common._truss_secids``)."""
    _handle_db_history(block, state, "BEAM_SET")


def handle_database_history_discrete(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_DISCRETE[_ID] → /TH/SPRING.

    dyna2rad copies the raw id list into the group with NO existence check at
    all (converttimehistory.cxx:256-261 assigns ``containKeywordVsElemIds
    ["/SPRING"] = elemidList`` without going through ``FindRadElement``, unlike
    its BEAM and SHELL branches). k2rad screens against the /SPRING ids it
    actually wrote: a /TH/SPRING naming an element the deck does not define is
    starter ERROR 69 and the whole run is refused, which is strictly worse than
    losing the channel.
    """
    _handle_db_history(block, state, "DISCRETE")


def handle_database_history_discrete_set(block: Block,
                                         state: ConversionState) -> None:
    """*DATABASE_HISTORY_DISCRETE_SET → /TH/SPRING over the named sets
    (``SET_COMPONENT_IDPOOL`` part sets or ``SET_DISCRETE_IDPOOL`` element
    sets, database_history_discrete_set.cfg:25)."""
    _handle_db_history(block, state, "DISCRETE_SET")


def handle_database_history_seatbelt(block: Block, state: ConversionState) -> None:
    """*DATABASE_HISTORY_SEATBELT[_ID] -> /TH/SPRING (1D) + /TH/SHEL + /TH/SH3N.

    LIVE since the seatbelt batch. Before it, k2rad converted neither
    ``*ELEMENT_SEATBELT`` nor ``*SECTION_SEATBELT``, so both branches were
    unreachable and naming the ids would have been starter ERROR 69 — a deck
    that "converts" and then refuses to run, which is the worst of the three
    outcomes; the request was recorded as recognized-but-not-emitted instead.

    dyna2rad probes the FIRST listed element's ``*ELEMENT_SEATBELT`` -> PID ->
    SECID and routes the WHOLE list on that one answer
    (``converttimehistory.cxx:303-341``). k2rad splits PER ELEMENT against the
    registries the writer filled — see ``writer/output.py::_th_seatbelt_split``
    — so a card mixing a 1D shoulder belt with a 2D lap belt gets both groups
    instead of one wrong one.
    """
    _handle_db_history(block, state, "SEATBELT")


def handle_database_history_node_set(block: Block,
                                     state: ConversionState) -> None:
    """*DATABASE_HISTORY_NODE_SET → /TH/NODE over the named *SET_NODEs."""
    _handle_db_history(block, state, "NODE_SET")


def handle_database_history_node_local(block: Block,
                                       state: ConversionState) -> None:
    """*DATABASE_HISTORY_NODE_LOCAL[_ID] → /TH/NODE with a PER-NODE skew.

    NODE (and NODE_SET) are the ONLY families with a ``_LOCAL`` option — a
    full-text scan of the R16 and R17 manuals finds no BEAM_LOCAL,
    DISCRETE_LOCAL or SEATBELT_LOCAL — and ``/TH/NODE`` is correspondingly the
    only group in this batch whose id card carries a ``skew_ID`` column
    (``th_node.cfg`` ``CARD("%10d%10d%-80s")``, cols 11-20; /TH/BEAM and
    /TH/SPRING have ten BLANK columns there and answer a skew with
    ``WARNING 100214`` plus a silent drop). See writer/output.py for how CID
    and REF become that column."""
    _handle_db_history(block, state, "NODE_LOCAL")


def handle_database_history_node_set_local(block: Block,
                                           state: ConversionState) -> None:
    """*DATABASE_HISTORY_NODE_SET_LOCAL → /TH/NODE, per-node skew, sets."""
    _handle_db_history(block, state, "NODE_SET_LOCAL")


def handle_database_history_shell_set(block: Block,
                                      state: ConversionState) -> None:
    """*DATABASE_HISTORY_SHELL_SET → /TH/SHEL + /TH/SH3N over the named sets."""
    _handle_db_history(block, state, "SHELL_SET")


def handle_database_history_solid_set(block: Block,
                                      state: ConversionState) -> None:
    """*DATABASE_HISTORY_SOLID_SET → /TH/BRIC over the named sets."""
    _handle_db_history(block, state, "SOLID_SET")


def handle_database_history_tshell_set(block: Block,
                                       state: ConversionState) -> None:
    """*DATABASE_HISTORY_TSHELL_SET → /TH/BRIC (a thick shell IS a /BRICK)."""
    _handle_db_history(block, state, "TSHELL_SET")


def handle_damping_global(block: Block, state: ConversionState) -> None:
    """*DAMPING_GLOBAL: mass-proportional Rayleigh damping (LS-DYNA Manual Vol I).

    Card: lcid valdmp stx sty stz srx sry srz — EIGHT fixed I10/E10 cells
    (Vol I R17 p.15-8). Only one *DAMPING_GLOBAL active at a time per LS-DYNA;
    last one wins.

    ``fixed=True``: this is a fixed-format card, and a blank INTERIOR column is
    ordinary on it (STZ omitted while SRX..SRZ are stated, say). A free split
    then drops the blank and shifts every later field one slot left —
    MEASURED::

        raw    '         0       500       1.0       1.0                 2.0       2.0       2.0'
        fixed  ['0','500','1.0','1.0','',   '2.0','2.0','2.0']    <- truth
        free   ['0','500','1.0','1.0','2.0','2.0','2.0']          <- SRX read
                                                                     as STZ,
                                                                     SRZ lost

    which silently rotates the per-DOF scale factors onto the wrong degrees of
    freedom.
    """
    raw = block.raw
    offset = _title_offset(block)
    f = _card(raw, offset, fixed=True, n=8, w=10)
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


def _damping_data_rows(block: Block) -> List[int]:
    """Indices of the real data lines of a *DAMPING_* block.

    The parser keeps blank cards as ``""`` placeholders so multi-card keywords
    hold their column positions (parser.py:299-308). Every *DAMPING_* card 1
    starts with an id or a coefficient, so a placeholder is never one of them
    and can be skipped here — the same walk ``handle_damping_part_stiffness``
    uses.

    A caller that also reads an OPTIONAL SECOND card must NOT simply take the
    next entry of this list: *DAMPING_PART_MASS's Scale Factor Card may itself
    be blank (all six scale factors default to 0.0, Manual Vol I R16 p.15-10),
    and that blank card is filtered out here, so the next entry would be the
    FOLLOWING card 1. ``handle_damping_part_mass`` therefore requires the card-2
    row to be RAW-CONTIGUOUS with its card 1; see the comment there.

    (The ``$`` guard is defensive only — ``parse_k_file`` drops column-1 ``$``
    lines outright and ``_strip_inline_comment`` reduces an indented one to
    ``""`` — but it is what ``handle_damping_part_stiffness`` writes, so the two
    walks stay textually identical.)
    """
    return [i for i in range(_title_offset(block), len(block.raw))
            if block.raw[i].strip() and not block.raw[i].lstrip().startswith("$")]


def _warn_extra_damping_rows(block: Block, state: ConversionState,
                             rows: List[int], n_expected: int) -> None:
    """Report the data lines a one-entity-per-block *DAMPING_* handler ignores.

    *DAMPING_FREQUENCY_RANGE and *DAMPING_RELATIVE are modelled as one entity
    per keyword block — that is how both HyperMesh cfgs read them
    (``Keyword971_R7.1/DAMPING/DampFrequencyRange.cfg``,
    ``Keyword971_R9.3/DAMPING/DampRelative.cfg``: a flat card each, no
    CARD_LIST), and the R16 manual shows a single card set for both. Whether
    LS-DYNA would go on to read a stacked second set is not settled here, so
    the rows are NOT interpreted — but they are named rather than dropped in
    silence, which is the whole point of this batch.

    (*DAMPING_PART_MASS is different and really does loop: its manual entry
    says the command "may appear multiple times", and the FLAG column makes the
    optional second card unambiguous to consume.)
    """
    if len(rows) <= n_expected:
        return
    ignored = [block.raw[i].rstrip() for i in rows[n_expected:]]
    state.warn(
        f"*{block.keyword}: {len(ignored)} extra data line(s) after the "
        f"{'card set' if n_expected == 1 else f'{n_expected} expected cards'} "
        f"— k2rad reads ONE {block.keyword} entity per keyword block (as both "
        "HyperMesh cfgs and the R16 manual describe it), so the following "
        f"line(s) are IGNORED: {ignored}. Split them into separate "
        f"*{block.keyword} blocks if they were meant as additional cards.")


def handle_damping_part_mass(block: Block, state: ConversionState) -> None:
    """*DAMPING_PART_MASS / _SET: mass-proportional damping scoped to parts.

    Card 1: ``PID|PSID  LCID  SF  FLAG``  (SF default 1.0, everything else 0)
    Card 2: ``STX STY STZ SRX SRY SRZ``   — present only when ``FLAG == 1``

    Repeated card sets are supported: LS-DYNA lets one keyword block define as
    many parts as wanted, and the FLAG column makes the optional second card
    unambiguous to consume.
    """
    is_set = "_SET" in block.keyword
    rows = _damping_data_rows(block)
    raw = block.raw
    k = 0
    n_before = len(state.damping_part_mass)
    while k < len(rows):
        c1 = rows[k]
        f = _card(raw, c1, fixed=True, n=4, w=10)
        k += 1
        if not f:
            continue
        pid = to_int(f[0])
        lcid = to_int(f[1]) if len(f) > 1 else 0
        # SF is one of the rare LS-DYNA fields with a NON-ZERO default, so a
        # blank column must fall back to 1.0 rather than to to_float("") == 0.0.
        sf = _ffield(f, 2, 1.0)
        flag = to_int(f[3]) if len(f) > 3 else 0
        st = [0.0] * 6
        # The Scale Factor Card is positional: LS-DYNA reads the line
        # IMMEDIATELY after card 1, and an all-blank one is the legal "every
        # scale factor defaults to 0.0" card. So the card-2 slot is claimed by
        # RAW index, not by "the next non-blank row" — a blank card 2 is dropped
        # from `rows`, and taking rows[k] there would consume the FOLLOWING
        # card 1 as scale factors (its PID/LCID landing in STX/STY) and lose
        # that part entirely. Non-blank card 2 <=> rows[k] is raw-contiguous.
        if flag == 1 and k < len(rows) and rows[k] == c1 + 1:
            f2 = _card(raw, rows[k], fixed=True, n=6, w=10)
            k += 1
            for j in range(6):
                st[j] = to_float(f2[j]) if len(f2) > j else 0.0
        if pid <= 0:
            state.warn(
                f"*{block.keyword}: card {c1 - _title_offset(block) + 1} has "
                f"{'PSID' if is_set else 'PID'}={pid} (0 or blank names no "
                "part) — that card is DROPPED.")
            continue
        state.damping_part_mass.append(DampingPartMass(
            pid=pid, is_set=is_set, lcid=lcid, sf=sf, flag=flag,
            stx=st[0], sty=st[1], stz=st[2], srx=st[3], sry=st[4], srz=st[5]))
    if len(state.damping_part_mass) == n_before:
        state.warn(f"*{block.keyword}: no usable data card found — skipped")


def handle_damping_frequency_range(block: Block, state: ConversionState) -> None:
    """*DAMPING_FREQUENCY_RANGE[_DEFORM[_DMIG]]: banded frequency damping.

    Card 1: ``CDAMP FLOW FHIGH PSID <blank> PIDREL IFLG ICARD2``
    Card 2: ``CDAMPV IPWP`` — only when ``ICARD2 == 1`` and the DEFORM option.

    The two option spellings share ONE card layout: the ``_DEFORM`` variant
    simply leaves the PIDREL slot (cols 51-60) blank, because the manual states
    PIDREL "does not apply to the DEFORM keyword option". IFLG stays at cols
    61-70 either way, so a single 8-field read serves both.

    Unlike dyna2rad — which folds ``_DEFORM`` into the base subtype through a
    cfg ``USER_NAMES`` alias and never calls ``GetKeyword()`` in
    ``ConvertDampingFrequencyRange`` (convertdampings.cxx:321), so the two forms
    are indistinguishable to it — k2rad keeps the distinction, because the two
    have genuinely different Radioss fidelity (see
    :func:`k2rad.writer.loads._make_damping_frequency_range`).
    """
    kw = block.keyword
    deform = "_DEFORM" in kw
    dmig = "_DMIG" in kw
    rows = _damping_data_rows(block)
    if not rows:
        state.warn(f"*{kw}: no data card found — skipped")
        return
    f = _card(block.raw, rows[0], fixed=True, n=8, w=10)
    cdamp = to_float(f[0]) if len(f) > 0 else 0.0
    flow = to_float(f[1]) if len(f) > 1 else 0.0
    fhigh = to_float(f[2]) if len(f) > 2 else 0.0
    psid = to_int(f[3]) if len(f) > 3 else 0
    pidrel = to_int(f[5]) if len(f) > 5 else 0
    iflg = to_int(f[6]) if len(f) > 6 else 0
    icard2 = to_int(f[7]) if len(f) > 7 else 0
    # CDAMPV defaults to CDAMP and IPWP to 1 — both NON-ZERO defaults, so they
    # are seeded before the read: an all-blank Card 2 (a legal "all defaults"
    # card, which the row filter drops along with the other blank placeholders)
    # must still land on those values, not on 0. Card 2 is positional, exactly
    # like *DAMPING_PART_MASS's Scale Factor Card, so it is claimed by RAW
    # contiguity rather than as "the next non-blank row" — otherwise a blank
    # card 2 followed by a stray line would read that line as CDAMPV/IPWP.
    cdampv, ipwp = (cdamp, 1) if (icard2 == 1 and deform) else (0.0, 1)
    n_consumed = 1
    if (icard2 == 1 and deform and len(rows) > 1
            and rows[1] == rows[0] + 1):
        f2 = _card(block.raw, rows[1], fixed=True, n=2, w=10)
        cdampv = _ffield(f2, 0, cdamp)
        ipwp = to_int(f2[1]) if len(f2) > 1 and f2[1].strip() else 1
        n_consumed = 2
    _warn_extra_damping_rows(block, state, rows, n_consumed)
    state.damping_frequency_range.append(DampingFrequencyRange(
        cdamp=cdamp, flow=flow, fhigh=fhigh, psid=psid, pidrel=pidrel,
        iflg=iflg, icard2=icard2, cdampv=cdampv, ipwp=ipwp,
        deform=deform, dmig=dmig))


def handle_damping_relative(block: Block, state: ConversionState) -> None:
    """*DAMPING_RELATIVE: damping of motion relative to a rigid body.

    Card: ``CDAMP FREQ PIDRB PSID DV2 LCID``.

    ``DV2`` (cols 41-50) and ``LCID`` (cols 51-60) only exist from the R7.1 /
    R9.3 profiles on; older decks simply leave those columns blank, which the
    fixed-width read turns into 0 — the same value their absence means.
    """
    rows = _damping_data_rows(block)
    if not rows:
        state.warn(f"*{block.keyword}: no data card found — skipped")
        return
    _warn_extra_damping_rows(block, state, rows, 1)
    f = _card(block.raw, rows[0], fixed=True, n=6, w=10)
    state.damping_relative.append(DampingRelative(
        cdamp=to_float(f[0]) if len(f) > 0 else 0.0,
        freq=to_float(f[1]) if len(f) > 1 else 0.0,
        pidrb=to_int(f[2]) if len(f) > 2 else 0,
        psid=to_int(f[3]) if len(f) > 3 else 0,
        dv2=to_float(f[4]) if len(f) > 4 else 0.0,
        lcid=to_int(f[5]) if len(f) > 5 else 0,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Seatbelts / restraints — *ELEMENT_SEATBELT[_<DEVICE>], *SECTION_SEATBELT,
# *MAT_SEATBELT / *MAT_B01 (+ _2D), *DATABASE_SBTOUT
# ─────────────────────────────────────────────────────────────────────────────

def _seatbelt_rows(block: Block) -> List[int]:
    """RAW indices of a seatbelt block's data cards (blanks and ``$`` out).

    IMPORTED and called by every device walk below AND by all four
    ``assembly._off_seatbelt_*`` offsetters, so the handler and the
    ``*INCLUDE_TRANSFORM`` offsetter cannot disagree about which line is a
    card — the #119 rule. (It used to be re-implemented inline on the assembly
    side, which made the invariant a coincidence rather than a fact; the
    offsetters now call this function, the way they already call
    ``_seatbelt_elem_card`` and ``_slipring_card2_follows``.) A blank card
    DROPS OUT of this list,
    which is exactly why the two-card devices claim their card 2 by RAW
    CONTIGUITY (``rows[k] == i + 1``) rather than "the next row".
    """
    return [i for i, ln in enumerate(block.raw)
            if ln.strip() and not ln.lstrip().startswith("$")]


def _seatbelt_elem_card(line: str) -> List[str]:
    """Slice one ``*ELEMENT_SEATBELT`` card.

    ``EID(I8) PID(I8) N1(I8) N2(I8) SBRID(I8) SLEN(F16) N3(I8) N4(I8)`` —
    ``Keyword971/ELEMENTS/seatbelt.cfg:64``,
    ``CARD("%8d%8d%8d%8d%8d%16lg%8d%8d", ...)``, which is also what LS-PrePost
    4.13.5 writes.

    EIGHT variables spanning TEN cells' worth of card, because SLEN alone is
    SIXTEEN wide. A uniform 8-wide slice reads the right half of SLEN as N3 and
    the left half of N3 as N4 — the same class of defect ``_element_mass_card``
    and ``_parse_sph_cell`` were written for, except here it silently turns a
    1D belt into a 2D one (N3 and N4 both non-zero is what makes the element a
    shell, ``convertelements.cxx:86-95``) and hands that /SHELL two nodes that
    do not exist.

    The card is SLICED FIRST and the free split is the fallback — the rule
    ``_card(fixed=True)`` already uses, and the only one that survives a BLANK
    interior cell. Trying the free split first and accepting it whenever it
    yields five short tokens reads a column-correct card with a blank cell one
    slot out of phase, and every field after the blank is then wrong:
    MEASURED, ``"       1      10       1       2       0                       7       8"``
    (I8 columns, SLEN blank, N3=7 N4=8) free-splits to
    ``['1','10','1','2','0','7','8']`` — SLEN=7, N3=8, N4=0 — so a 2D shell
    belt silently becomes a 1D /SPRING with 7 mm of invented slack, and the
    part is then claimed by BOTH routes (starter ERROR 79 + 1715 + 78 + 760).

    A genuinely fixed-format cell never contains whitespace or a comma INSIDE
    it, so a slice that produces one means the card was written free-format,
    narrower than the columns — the fallback's exact trigger.
    """
    data = _strip_inline_comment(line)
    if "," in data:
        toks = parse_free(data)
        return toks + [""] * max(0, 8 - len(toks))
    cells = [data[0:8], data[8:16], data[16:24], data[24:32], data[32:40],
             data[40:56], data[56:64], data[64:72]]
    sliced = [c.strip() for c in cells]
    if any(ch.isspace() for c in sliced for ch in c):
        toks = parse_free(data)
        if toks:
            return toks + [""] * max(0, 8 - len(toks))
    return sliced


def handle_element_seatbelt(block: Block, state: ConversionState) -> None:
    """*ELEMENT_SEATBELT → a 1D belt /SPRING, or a 2D belt /SHELL.

    ``N3``/``N4`` both non-zero makes the element a four-node SHELL belt whose
    thickness comes from ``*SECTION_SHELL``; otherwise it is a two-node
    ``/SPRING`` on ``/PROP/TYPE23`` + ``/MAT/LAW114``. dyna2rad decides exactly
    this way (``convertelements.cxx:86-95``) and preserves the element id
    (``:281``).

    ``SBRID`` — the retractor the element STARTS INSIDE — is read and kept even
    though the Radioss link runs the other way (``/RETRACTOR/SPRING``'s
    ``EL_ID`` names the mouth element): the writer uses it to catch a belt that
    declares a retractor which does not name it back. dyna2rad cannot see that
    at all, because it never reads the field — ``grep '"SBRID"'`` over its tree
    matches only the *pretensioner's* homonym.

    ``SLEN`` — the initial SLACK length — is read for the same reason: Radioss
    has no slot for it anywhere in ``/SPRING`` + ``/PROP/TYPE23`` +
    ``/MAT/LAW114`` (``grep '"SLEN"'`` over the whole dyna2rad tree returns
    zero hits), so the writer names the loss instead of dropping it in silence.
    """
    for i in _seatbelt_rows(block):
        f = _seatbelt_elem_card(block.raw[i])
        eid = to_int(f[0])
        pid = to_int(f[1])
        if eid <= 0 or pid <= 0:
            continue
        state.seatbelt_elems.append(SeatbeltElem(
            eid=eid, pid=pid, n1=to_int(f[2]), n2=to_int(f[3]),
            sbrid=to_int(f[4]), slen=to_float(f[5]),
            n3=to_int(f[6]), n4=to_int(f[7])))


def handle_element_seatbelt_accelerometer(block: Block,
                                          state: ConversionState) -> None:
    """*ELEMENT_SEATBELT_ACCELEROMETER → /ACCEL + /SKEW/MOV + /ADMAS.

    ``SBACID NID1 NID2 NID3 IGRAV INTOPT MASS`` in 10-char cells, one card per
    accelerometer, repeated to the next keyword.

    The two Toyota production decks are the only carriers in the corpus and
    they disagree about the header comment (the Camry writes a ``mass`` column
    label, the Yaris does not) while leaving IGRAV/INTOPT/MASS blank in every
    row — so a short or blank tail has to read as "absent", which is what
    ``_card``'s fixed slice already gives.
    """
    for i in _seatbelt_rows(block):
        f = _card(block.raw, i, fixed=True, n=7, w=10)
        sbacid = to_int(f[0]) if f else 0
        if sbacid <= 0:
            continue
        state.seatbelt_accels.append(SeatbeltAccelerometer(
            sbacid=sbacid,
            nid1=to_int(f[1]) if len(f) > 1 else 0,
            nid2=to_int(f[2]) if len(f) > 2 else 0,
            nid3=to_int(f[3]) if len(f) > 3 else 0,
            igrav=to_int(f[4]) if len(f) > 4 else 0,
            intopt=to_int(f[5]) if len(f) > 5 else 0,
            mass=to_float(f[6]) if len(f) > 6 else 0.0))


def _slipring_card2_follows(block: Block, rows: List[int], k: int, i: int,
                            onid: int) -> bool:
    """Is ``rows[k]`` the optional card 2 of the slipring whose card 1 is *i*?

    The cfg's own rule is ``if (ONID != NONE)``
    (``Keyword971_R13.0/ELEMENTS/element_seatbelt_slipring.cfg:17``) and the
    manual's is "Optional Card ... required when ONID is nonzero", so ONID is
    the primary vote — and ``ONID != 0`` claims the card even when every cell
    on it is BLANK, which is the #119 rule: a blank card is not an absent one.
    (A blank card 2 drops out of ``_seatbelt_rows`` entirely, so the contiguity
    test below then declines it and the following card 1 is still read as a
    card 1 — the safe direction.)

    The second vote exists because a deck CAN write card 2 with ONID blank:
    ``LCNFFD``/``LCNFFS`` need no orientation node. Without it that card would
    be read as the next slipring's card 1, ``to_int`` would return 0 for its
    ``K`` cell ("0.12" parses to 0) and the walk would ``break`` — losing every
    remaining ring in the block, silently. The discriminator is card 2's own
    geometry: its columns 41-50 are TEN LITERAL BLANKS in the cfg's CARD string
    (``"%10lg%10d%10d%10lg          %10d%10d"``), while card 1's field 4 is
    SBRNID, the anchorage node, without which the ring cannot exist at all
    (starter ERROR 2004). So "field 4 populated" means card 1, and nothing else
    does.
    """
    if k >= len(rows) or rows[k] != i + 1:
        return False                      # RAW contiguity, never "next row"
    cand = _card(block.raw, rows[k], fixed=True, n=8, w=10)
    looks_like_card1 = len(cand) > 4 and bool(cand[4].strip())
    if looks_like_card1:
        return False
    return onid != 0 or _populated_cells(block.raw, rows[k]) > 0


def handle_element_seatbelt_slipring(block: Block,
                                     state: ConversionState) -> None:
    """*ELEMENT_SEATBELT_SLIPRING → /SLIPRING/SPRING or /SLIPRING/SHELL.

    Card 1 ``SBSRID SBID1 SBID2 FC SBRNID LTIME FCS ONID``. The field ORDER is
    the trap: ``FC`` sits BETWEEN the two element ids and the anchorage node
    (``Keyword971_R13.0/ELEMENTS/element_seatbelt_slipring.cfg:11``, and
    LS-PrePost writes those columns), not after ``LTIME`` where the manual's
    variable list reads as though it were. A converter that assumes the list
    order gives the ring a friction coefficient of ``SBRNID`` (a node id) and
    an anchorage node of ``FC`` (0).

    Card 2 ``K FUNCID DIRECT DC <blank> LCNFFD LCNFFS`` — see
    :func:`_slipring_card2_follows` for the #119 walk that claims it.

    A NEGATIVE ``SBRNID`` makes this a SHELL-belt ring: ``|SBRNID|`` is a
    ``*SET_NODE`` and ``SBID1``/``SBID2`` are ``*SET_SHELL_LIST`` ids, which is
    the ``/SLIPRING/SHELL`` card rather than ``/SLIPRING/SPRING``.
    """
    rows = _seatbelt_rows(block)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _card(block.raw, i, fixed=True, n=8, w=10)
        sbsrid = to_int(f1[0]) if f1 else 0
        if sbsrid <= 0:
            break
        k += 1
        onid = to_int(f1[7]) if len(f1) > 7 else 0
        fc_raw = to_float(f1[3]) if len(f1) > 3 else 0.0
        fcs_raw = to_float(f1[6]) if len(f1) > 6 else 0.0
        sl = SeatbeltSlipring(
            sbsrid=sbsrid,
            sbid1=to_int(f1[1]) if len(f1) > 1 else 0,
            sbid2=to_int(f1[2]) if len(f1) > 2 else 0,
            # A NEGATIVE FC / FCS is a *DEFINE_CURVE id (friction vs TIME), not
            # a coefficient: the cfg declares both cells SCALAR_OR_OBJECT and
            # meci_data_reader.cpp:6846 spells the convention out — "this is
            # Dyna specific: if the value is negative, its abs value is the ID
            # of an object". Reading it as a coefficient would hand the ring a
            # friction of -0.15 and Radioss a Fricd it can only clamp.
            fc=fc_raw if fc_raw >= 0.0 else 0.0,
            fc_func=int(round(-fc_raw)) if fc_raw < 0.0 else 0,
            sbrnid=to_int(f1[4]) if len(f1) > 4 else 0,
            ltime=_ffield(f1, 5, 1.0e20),
            fcs=fcs_raw if fcs_raw >= 0.0 else 0.0,
            fcs_func=int(round(-fcs_raw)) if fcs_raw < 0.0 else 0,
            onid=onid)
        if _slipring_card2_follows(block, rows, k, i, onid):
            f2 = _card(block.raw, rows[k], fixed=True, n=8, w=10)
            sl.has_card2 = True
            sl.k = to_float(f2[0]) if f2 else 0.0
            sl.funcid = to_int(f2[1]) if len(f2) > 1 else 0
            sl.direct = to_int(f2[2]) if len(f2) > 2 else 0
            sl.dc = to_float(f2[3]) if len(f2) > 3 else 0.0
            # Columns 41-50 are ten literal BLANKS in the cfg's own CARD
            # string, so LCNFFD is field 5 and LCNFFS field 6. Reading them as
            # 4 and 5 takes the blank for the dynamic normal-force curve and
            # the dynamic curve for the static one.
            sl.lcnffd = to_int(f2[5]) if len(f2) > 5 else 0
            sl.lcnffs = to_int(f2[6]) if len(f2) > 6 else 0
            k += 1
        state.seatbelt_sliprings.append(sl)


def handle_element_seatbelt_retractor(block: Block,
                                      state: ConversionState) -> None:
    """*ELEMENT_SEATBELT_RETRACTOR → /RETRACTOR/SPRING.

    A FIXED two-card stack, repeated to the next keyword:

      Card 1 ``SBRID SBRNID SBID SID1 SID2 SID3 SID4 DSID``
      Card 2 ``TDEL PULL LLCID ULCID LFED LCFL FLOPT``

    The ``Keyword971_R13.0`` cfg stops at ``SID4`` and ``LFED``; ``DSID``,
    ``LCFL`` and ``FLOPT`` are in the R17 manual and LS-PrePost 4.13.5 writes
    them, so all three are read here (and warn-dropped by name — none has a
    Radioss slot).

    Card 2 is claimed by RAW CONTIGUITY, not by "the next populated row". An
    all-blank card 2 is legal — every field on it has a documented default, and
    a retractor with no delay, no pull-out threshold and no feed length is a
    perfectly ordinary free reel — and dropping it from the walk would read the
    NEXT retractor's card 1 as this one's ``TDEL PULL LLCID``, then run one
    card out of phase for the rest of the block (#119).
    """
    rows = _seatbelt_rows(block)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _card(block.raw, i, fixed=True, n=8, w=10)
        sbrid = to_int(f1[0]) if f1 else 0
        if sbrid <= 0:
            break
        k += 1
        f2: List[str] = []
        if k < len(rows) and rows[k] == i + 1:
            f2 = _card(block.raw, rows[k], fixed=True, n=7, w=10)
            k += 1
        state.seatbelt_retractors.append(SeatbeltRetractor(
            sbrid=sbrid,
            sbrnid=to_int(f1[1]) if len(f1) > 1 else 0,
            sbid=to_int(f1[2]) if len(f1) > 2 else 0,
            sid1=to_int(f1[3]) if len(f1) > 3 else 0,
            sid2=to_int(f1[4]) if len(f1) > 4 else 0,
            sid3=to_int(f1[5]) if len(f1) > 5 else 0,
            sid4=to_int(f1[6]) if len(f1) > 6 else 0,
            dsid=to_int(f1[7]) if len(f1) > 7 else 0,
            tdel=to_float(f2[0]) if f2 else 0.0,
            pull=to_float(f2[1]) if len(f2) > 1 else 0.0,
            llcid=to_int(f2[2]) if len(f2) > 2 else 0,
            ulcid=to_int(f2[3]) if len(f2) > 3 else 0,
            lfed=to_float(f2[4]) if len(f2) > 4 else 0.0,
            lcfl=to_int(f2[5]) if len(f2) > 5 else 0,
            flopt=to_int(f2[6]) if len(f2) > 6 else 0))


def handle_element_seatbelt_pretensioner(block: Block,
                                         state: ConversionState) -> None:
    """*ELEMENT_SEATBELT_PRETENSIONER — folded onto its retractor's card 3.

      Card 1 ``SBPRID SBPRTY SBSID1 SBSID2 SBSID3 SBSID4``
      Card 2 ``SBRID TIME PTLCID LMTFRC LMTPIN``

    Card 2 is claimed by RAW CONTIGUITY for a sharper reason than the
    retractor's: on SBPRTY 7/8/9 the legacy ``Keyword971`` cfg writes card 2
    with field 0 LITERALLY BLANK (``CARD("          %10lg          %10lg",
    TIME, LMTFRC)``), so a walk that looked for a populated leading cell would
    take the NEXT pretensioner's card 1 as this one's ``SBRID`` and pretension
    the wrong retractor.

    Every cfg from ``Keyword971_R7.1`` on — and LS-PrePost 4.13.5 — writes the
    UNIFORM card 2 read here. The legacy type-dependent layout differs only in
    field 0, for SBPRTY 2/3 (a sensor id) and 7/9 (blank); all four of those
    types have no Radioss ``Tens_typ`` at all and are warn-dropped whole by the
    writer, so the ambiguity never reaches a Radioss card.
    """
    rows = _seatbelt_rows(block)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _card(block.raw, i, fixed=True, n=6, w=10)
        sbprid = to_int(f1[0]) if f1 else 0
        if sbprid <= 0:
            break
        k += 1
        f2: List[str] = []
        if k < len(rows) and rows[k] == i + 1:
            f2 = _card(block.raw, rows[k], fixed=True, n=5, w=10)
            k += 1
        state.seatbelt_pretensioners.append(SeatbeltPretensioner(
            sbprid=sbprid,
            sbprty=to_int(f1[1]) if len(f1) > 1 else 0,
            sbsid1=to_int(f1[2]) if len(f1) > 2 else 0,
            sbsid2=to_int(f1[3]) if len(f1) > 3 else 0,
            sbsid3=to_int(f1[4]) if len(f1) > 4 else 0,
            sbsid4=to_int(f1[5]) if len(f1) > 5 else 0,
            sbrid=to_int(f2[0]) if f2 else 0,
            time=to_float(f2[1]) if len(f2) > 1 else 0.0,
            ptlcid=to_int(f2[2]) if len(f2) > 2 else 0,
            lmtfrc=to_float(f2[3]) if len(f2) > 3 else 0.0,
            lmtpin=to_float(f2[4]) if len(f2) > 4 else 0.0))


#: SBSTYP → how many cells that type's card 2 carries. Card 2 EXISTS for every
#: documented SBSTYP (1..5) and for none other, so the STRIDE is a fixed
#: ``1 + 1`` and the #119 walk is only about WHICH fields are read off it. An
#: unknown SBSTYP still consumes its card (four cells read and discarded):
#: consuming it keeps the block in phase, which is the whole point.
_SEATBELT_SENSOR_CARD2 = {1: 4, 2: 3, 3: 1, 4: 4, 5: 3}


def handle_element_seatbelt_sensor(block: Block,
                                   state: ConversionState) -> None:
    """*ELEMENT_SEATBELT_SENSOR → /SENSOR/ACCE | /SENSOR/TIME | /SENSOR/DIST.

    Card 1 ``SBSID SBSTYP SBSFL``, then ONE type card selected by SBSTYP
    (``Keyword971_R12.0/SENSOR/element_seatbelt_sensor_no_sub.cfg``):

      1  ``NID DOF ACC ATIME``       node acceleration
      2  ``SBRID PULRAT PULTIM``     retractor pull-out RATE
      3  ``TIME``                    time
      4  ``NID1 NID2 DMX DMN``       node distance — MAXIMUM first
      5  ``SBRID PULMX PULMN``       retractor pull-out

    Card 2 is claimed by RAW CONTIGUITY, never "the next populated row": a
    SBSTYP=3 card carrying ``TIME = 0`` (fire immediately — the LS-DYNA default
    and a perfectly ordinary pretensioner trigger) is entirely blank, and
    skipping it would read the next sensor's card 1 as this one's TIME and then
    walk every remaining sensor one card out of phase, with no line that ever
    re-syncs (#119).
    """
    rows = _seatbelt_rows(block)
    k = 0
    while k < len(rows):
        i = rows[k]
        f1 = _card(block.raw, i, fixed=True, n=3, w=10)
        sbsid = to_int(f1[0]) if f1 else 0
        if sbsid <= 0:
            break
        k += 1
        sbstyp = to_int(f1[1]) if len(f1) > 1 else 0
        sens = SeatbeltSensor(sbsid=sbsid, sbstyp=sbstyp,
                              sbsfl=to_int(f1[2]) if len(f1) > 2 else 0)
        f2: List[str] = []
        if k < len(rows) and rows[k] == i + 1:
            f2 = _card(block.raw, rows[k],
                       fixed=True, n=_SEATBELT_SENSOR_CARD2.get(sbstyp, 4),
                       w=10)
            k += 1

        def _g(idx: int, default: float = 0.0) -> float:
            return to_float(f2[idx]) if len(f2) > idx else default

        def _gi(idx: int) -> int:
            return to_int(f2[idx]) if len(f2) > idx else 0

        if sbstyp == 1:
            sens.nid, sens.dof = _gi(0), _gi(1)
            sens.acc, sens.atime = _g(2), _g(3)
        elif sbstyp == 2:
            sens.sbrid, sens.pulrat, sens.pultim = _gi(0), _g(1), _g(2)
        elif sbstyp == 3:
            sens.time = _g(0)
        elif sbstyp == 4:
            # DMX is field 2 and DMN field 3 — the LS-DYNA card lists the
            # MAXIMUM first while the Radioss /SENSOR/DIST card lists Dmin
            # first. Copying position-for-position swaps the two bounds, and
            # with Dmin > Dmax the sensor can never fire at all.
            sens.nid1, sens.nid2 = _gi(0), _gi(1)
            sens.dmx, sens.dmn = _g(2), _g(3)
        elif sbstyp == 5:
            sens.sbrid = _gi(0)
            sens.pulmx = _ffield(f2, 1, 1.0e16)
            sens.pulmn = _ffield(f2, 2, -1.0e16)
        state.seatbelt_sensors[sbsid] = sens


def handle_section_seatbelt(block: Block, state: ConversionState) -> None:
    """*SECTION_SEATBELT (+ _TITLE) → /PROP/TYPE23 (SPR_MAT) — every card SET.

    ``SECID AREA THICK`` (``Keyword971_R8.0/PROPERTY/sect_seatbelt.cfg``; the
    older ``Keyword971`` block has only ``SECID AREA``, so THICK reads as
    absent on an R7.1 deck, which is correct).

    Both AREA and THICK are LS-DYNA CONTACT numbers and neither becomes the
    Radioss property area — see :class:`SectionSeatbelt` and the writer, which
    names the drop.
    """
    per_set_title = _title_offset(block)
    raw = block.raw
    idx = 0
    n_sets = 0
    while idx < len(raw):
        if not any(line.strip() for line in raw[idx:]):
            break
        title = ""
        if per_set_title:
            title = _read_title(block) if n_sets == 0 else raw[idx].strip()
            idx += 1
            if idx >= len(raw):
                break
        f1 = _card(raw, idx, fixed=True, n=3, w=10)
        secid = to_int(f1[0]) if f1 else 0
        if secid <= 0:
            if not n_sets:
                state.warn("*SECTION_SEATBELT: empty card - skipped")
            else:
                state.warn(_section_set_stop("*SECTION_SEATBELT", n_sets,
                                             raw[idx]))
            break
        state.sec_seatbelts[secid] = SectionSeatbelt(
            secid=secid, title=title or f"SECTION_SEATBELT_{secid}",
            # AREA defaults to 0.01 in LS-DYNA. Stored as STATED-vs-blank (0.0)
            # deliberately: it never reaches a Radioss card, and the writer's
            # note reads better naming the number the deck actually wrote.
            area=to_float(f1[1]) if len(f1) > 1 else 0.0,
            thick=to_float(f1[2]) if len(f1) > 2 else 0.0)
        idx += 1
        n_sets += 1


def handle_mat_seatbelt(block: Block, state: ConversionState) -> None:
    """*MAT_SEATBELT / *MAT_B01 (+ ``_2D``) → /MAT/LAW114 or /MAT/LAW119.

    Card 1  ``MID MPUL LLCID ULCID LMIN CSE DAMP E``
    Card 2  ``A I J AS F M R``           — read ONLY when ``E > 0``
    Card 3  ``P1DOFF FORM ECOAT TCOAT SCOAT EB PRBA PRAB``   — ``_2D`` only
    Card 4  ``GAB``                                          — ``_2D`` only

    Card 2's presence is a #119 walk on a card-1 VALUE: the manual makes it
    "required if and only if E > 0". Reading it unconditionally on an ordinary
    belt (E blank — the overwhelmingly common case) takes the NEXT material's
    MID as this one's cross-sectional area, and ``A`` is exactly the number the
    /PROP/TYPE23 area comes from, so the belt would be sized by an id.

    The LS-DYNA card-2/3 DEFAULTS are applied here rather than left at zero,
    because each is real physics a blank cell STATES rather than omits:
    ``J = 2I``, ``AS = A``, ``F = M = 1e20`` (no limit), ``R = 0.05``,
    ``EB = -0.1`` (10 % of the curve-derived modulus, negative meaning a
    RATIO), ``PRBA = 0.3``, ``PRAB = PRBA``. dyna2rad copies the raw cells
    instead — ``CopyValue`` is a plain get/set with no defaulting at all
    (``convertutilsbase.cxx:101-137``) — so a blank ``F`` reaches LAW114 as
    ``FMAX = 0``, a belt clamped to ZERO compression force on a deck that
    explicitly asked for the bending model.
    """
    kw = block.keyword
    is_2d = kw.endswith("_2D")
    raw = block.raw
    idx = _title_offset(block)
    f1 = _card(raw, idx, fixed=True, n=8, w=10)
    mid = to_int(f1[0]) if f1 else 0
    if mid <= 0:
        state.warn(f"*{kw}: empty or unreadable card 1 - material skipped.")
        return
    m = MatSeatbelt(
        mid=mid,
        mpul=to_float(f1[1]) if len(f1) > 1 else 0.0,
        llcid=to_int(f1[2]) if len(f1) > 2 else 0,
        ulcid=to_int(f1[3]) if len(f1) > 3 else 0,
        lmin=to_float(f1[4]) if len(f1) > 4 else 0.0,
        cse=to_float(f1[5]) if len(f1) > 5 else 0.0,
        damp=_ffield(f1, 6, 0.1),
        e=to_float(f1[7]) if len(f1) > 7 else 0.0,
        is_2d=is_2d)
    idx += 1
    if m.e > 0.0:
        f2 = _card(raw, idx, fixed=True, n=7, w=10)
        m.has_card2 = True
        m.a = to_float(f2[0]) if f2 else 0.0
        m.i = to_float(f2[1]) if len(f2) > 1 else 0.0
        m.j = _ffield(f2, 2, 2.0 * m.i)
        m.as_ = _ffield(f2, 3, m.a)
        m.f = _ffield(f2, 4, 1.0e20)
        m.m = _ffield(f2, 5, 1.0e20)
        m.r = _ffield(f2, 6, 0.05)
        idx += 1
    if is_2d and idx < len(raw):
        if raw[idx].strip():
            f3 = _card(raw, idx, fixed=True, n=8, w=10)
            m.has_card3 = True
            m.p1doff = to_float(f3[0]) if f3 else 0.0
            m.form = to_int(f3[1]) if len(f3) > 1 else 0
            m.ecoat = to_float(f3[2]) if len(f3) > 2 else 0.0
            m.tcoat = to_float(f3[3]) if len(f3) > 3 else 0.0
            m.scoat = to_float(f3[4]) if len(f3) > 4 else 0.0
            m.eb = _ffield(f3, 5, -0.1)
            m.prba = _ffield(f3, 6, 0.3)
            m.prab = _ffield(f3, 7, m.prba)
        # A BLANK card 3 is still a CARD: the manual makes it required for the
        # _2D option ("2D Card. Additional 1st card for the 2D keyword
        # option"), so every cell on it is asking for its default and the
        # OPTIONAL card 4 sits after it. Not advancing past a blank one read
        # the GAB card as card 3 — P1DOFF = GAB — and lost the shear modulus
        # in silence, under a warning that said GAB was never stated.
        idx += 1
        if idx < len(raw) and raw[idx].strip():
            f4 = _card(raw, idx, fixed=True, n=1, w=10)
            m.has_card4 = True
            m.gab = to_float(f4[0]) if f4 else 0.0
    state.mat_seatbelt[mid] = m


def handle_database_sbtout(block: Block, state: ConversionState) -> None:
    """*DATABASE_SBTOUT → /TH/SLIPRING + /TH/RETRACTOR.

    "Seat belts" — LS-DYNA ASCII database 52 (Vol I R16 p.16-7). ONE file
    there; TWO group types in Radioss, because the ring and the reel are
    separate entity families with separate channel sets
    (``hm_read_thgrou.F:1258`` ``VARSLIP = RINGSLIP FN F1 F2 THETA GAMMA``,
    ``:1261`` ``VARRET = SLIP FN LOCK``), so both are emitted.

    This is k2rad exceeding the reference converter outright: dyna2rad handles
    *DATABASE_SBTOUT only as a member of the generic ``dbCardList``
    (``convertcards.cxx:94``), where its ONLY effect is contributing its DT to
    the global /TFILE minimum — and ``grep -rn "TH/RETRACTOR"`` over its whole
    ``reader/source`` tree returns zero hits, so a retractor's force, pull-out
    and lock state are simply unavailable after a dyna2rad conversion.
    """
    state.db_sbtout_seen = True
    state.db_sbtout_dt = _handle_db_dt(block, state, "*DATABASE_SBTOUT")


#: Every ``*ELEMENT_SEATBELT`` spelling this batch reads, as
#: ``suffix -> handler``. ONE source: ``HANDLERS`` and
#: ``assembly._OFFSET_SPECS`` are both generated from it (#116), so a spelling
#: cannot be dispatchable and un-offsettable, or the other way round.
#:
#: A DISJOINT-SUFFIX family, not an option stack: ``_SLIPRING`` and
#: ``_RETRACTOR`` are different KEYWORDS with different card stacks, so this
#: mirrors ``_AIRBAG_MODELS`` (one handler per member, exact keys) rather than
#: ``_AIRBAG_OPTION_STACKS`` (the cartesian product of option slots over one
#: card stack). Nothing here may be reached by a prefix walk either: a bare
#: ``startswith("ELEMENT_SEATBELT")`` would route ``_SLIPRING`` into the belt
#: element reader and turn a friction coefficient into a node id.
#:
#: ``_ID`` / ``_TITLE`` need no key — ``parser._split_keyword`` strips a
#: trailing one into ``block.options`` before ``dispatch`` sees the keyword.
_SEATBELT_SUBKEYWORDS = {
    "": handle_element_seatbelt,
    "_ACCELEROMETER": handle_element_seatbelt_accelerometer,
    "_SLIPRING": handle_element_seatbelt_slipring,
    "_RETRACTOR": handle_element_seatbelt_retractor,
    "_PRETENSIONER": handle_element_seatbelt_pretensioner,
    "_SENSOR": handle_element_seatbelt_sensor,
}

#: Every ``*MAT_`` spelling of the seatbelt material. ``*MAT_B01`` is the
#: numbered alias of ``*MAT_SEATBELT`` and ``_2D`` is a distinct material, NOT
#: an option of the base one — dyna2rad maps all four to its internal law 801
#: (``dynamatlawkeywordmap.h:306-307,371-372``) but routes them through
#: different property converters. Registered EXACTLY, never by prefix, so
#: ``*MAT_SEATBELT_2D`` can never be swallowed by a walk from
#: ``MAT_SEATBELT``.
_SEATBELT_MAT_KEYWORDS = ("MAT_SEATBELT", "MAT_SEATBELT_2D",
                          "MAT_B01", "MAT_B01_2D")


# ─────────────────────────────────────────────────────────────────────────────
# Rare cards batch
# ─────────────────────────────────────────────────────────────────────────────

#: ``*DEFINE_ELEMENT_DEATH_<OPTION>``: the eight OPTIONs of Vol I R17 p.17-251,
#: mapped to ``(family, is_set)``. There is NO ``_TITLE`` option on this
#: keyword — neither the manual's option list nor
#: ``Keyword971_R11.1/PROPERTY/define_elem_death.cfg:74-81`` admits one — but a
#: deck that writes one anyway still dispatches, because
#: ``parser._split_keyword`` strips a trailing ``_TITLE`` into
#: ``block.options`` before ``dispatch`` sees the keyword.
#:
#: ``_SET`` is part of the BASE keyword, not an option: the same cell is an
#: element id in one spelling and a ``*SET_<FAMILY>`` id in the other, i.e. two
#: different ``*INCLUDE_TRANSFORM`` buckets, so both spellings are listed in
#: full (the ``*INITIAL_STRAIN_SHELL[_SET]`` precedent).
_ELEMENT_DEATH_OPTIONS = {
    "SOLID":            ("SOLID", False),
    "SOLID_SET":        ("SOLID", True),
    "BEAM":             ("BEAM", False),
    "BEAM_SET":         ("BEAM", True),
    "SHELL":            ("SHELL", False),
    "SHELL_SET":        ("SHELL", True),
    "THICK_SHELL":      ("THICK_SHELL", False),
    "THICK_SHELL_SET":  ("THICK_SHELL", True),
}


def handle_define_element_death(block: Block, state: ConversionState) -> None:
    """``*DEFINE_ELEMENT_DEATH_<FAMILY>[_SET]`` → ``/ACTIV`` (writer side).

    Card 1, ONE card per keyword instance (Vol I R17 p.17-251/252, and
    ``define_elem_death.cfg:429/497`` ``%10d%10lg%10d%10d%10d%10d%10lg``)::

        EID/SID   TIME   BOXID   INOUT   IDGRP   CID   PERCENT

    Older layouts are SHORTER, not different: ``FORMAT(Keyword971_R6.1)`` has 4
    fields (:159), ``Keyword971_R8.0`` 6 (:294), ``R11.1`` 7 (:429). Reading by
    COLUMN with ``fixed=True, n=8, w=10`` therefore covers all three — a short
    card simply leaves the trailing cells blank.

    Everything but ``EID/SID`` and ``TIME`` is carried into the record only so
    the writer can name what it drops; see writer/rarecards.py for the
    verdicts. dyna2rad never even reads them
    (``convertdefineelementdeath.cxx`` has ``GetValue``s for ``SID`` and
    ``EID`` only).
    """
    opt = block.keyword[len("DEFINE_ELEMENT_DEATH_"):]
    family, is_set = _ELEMENT_DEATH_OPTIONS[opt]
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or not f[0].strip():
        return
    eid = to_int(f[0])
    if eid <= 0:
        state.warn(
            f"*DEFINE_ELEMENT_DEATH_{opt}: field 1 is "
            f"{f[0].strip()!r}, not a positive element"
            f"{' set' if is_set else ''} id — card dropped.")
        return
    state.element_deaths.append(ElementDeath(
        family=family, is_set=is_set, eid=eid,
        time=to_float(f[1]) if len(f) > 1 else 0.0,
        boxid=to_int(f[2]) if len(f) > 2 else 0,
        inout=to_int(f[3]) if len(f) > 3 else 0,
        idgrp=to_int(f[4]) if len(f) > 4 else 0,
        cid=to_int(f[5]) if len(f) > 5 else 0,
        percent=to_float(f[6]) if len(f) > 6 else 0.0,
        title=title))


def smooth_curve_points(dist: float, tstart: float, tend: float,
                        trise: float, vmax: float):
    """The four trapezoid vertices of a ``*DEFINE_CURVE_SMOOTH``.

    Returns ``(points, vmax, tend, note)`` — ``note`` is ``""`` when nothing
    had to be repaired.

    Vol I R17 p.17-154 makes ``TEND`` and ``VMAX`` mutually exclusive
    ("**Input either TEND or VMAX**"), each back-solved from ``DIST``, "Total
    distance tool will travel (area under curve)". The trapezoid with vertices
    ``(TSTART,0) (TSTART+TRISE,VMAX) (TEND-TRISE,VMAX) (TEND,0)`` has area

        A = VMAX * [(TEND-TSTART) + (TEND-TRISE-TSTART-TRISE)] / 2
          = VMAX * (TEND - TSTART - TRISE)

    so ``VMAX = DIST/(TEND-TSTART-TRISE)`` and ``TEND = DIST/VMAX + TSTART +
    TRISE`` are the two exact inverses of one identity. **No conversion factor
    is involved** — the same closed form on both sides (the #128 rule). This
    stays true for the ``/FUNCT_SMOOTH`` quintic blend as well: the smoothstep
    ``S(u) = u^3 (10 - 15u + 6u^2)`` integrates to exactly ``1/2`` over
    ``[0,1]`` (``finter_smooth.F:92-101``), so each blended ramp contributes
    the same ``VMAX*TRISE/2`` a straight ramp does.

    Two guards dyna2rad does not have:

    * ``convertcurves.cxx:325`` fires only when ``TEND-TSTART-TRISE != 0``, so
      the case ``VMAX = 0``, ``TEND != 0``, ``TEND == TSTART+TRISE`` falls
      through EVERY branch and d2r emits a flat all-zero 4-point curve with no
      diagnostic. Here it is a named refusal — and so are the same two
      degeneracies on the OTHER arm, where the identity ``TEND-TSTART-TRISE =
      DIST/VMAX`` makes ``DIST = 0`` (zero-width window) and a ``DIST`` whose
      sign contradicts ``VMAX``'s (negative window) exactly the same shape.
    * ``TRISE = 0`` (or a ``TRISE`` that would consume the whole window)
      collapses the trapezoid onto duplicate abscissae, which is starter
      ``ERROR 156`` (``hm_read_funct.F:240-243`` refuses a non-increasing
      abscissa). The vertices are nudged apart on the CARD value, so the
      emitted function keeps ``DIST`` exactly and still returns to zero at
      ``TEND`` — the ``TRISE -> 0`` limit rather than a rejected deck.
    """
    note = ""
    if vmax == 0.0 and tend == 0.0:
        return None, vmax, tend, ("neither TEND nor VMAX is stated, so the "
                                  "travel distance DIST determines nothing")
    if vmax == 0.0:
        span = tend - tstart - trise
        # A span that is only float noise (0.03 - 0.01 - 0.02 = -3.5e-18) is a
        # zero, not a divisor: taking it at face value gives VMAX ~ 1e18.
        # dyna2rad's test is a bare ``!= 0.0`` (convertcurves.cxx:325).
        scale = max(abs(tend), abs(tstart), abs(trise))
        if scale > 0.0 and abs(span) <= 1.0e-9 * scale:
            span = 0.0
        if span == 0.0:
            return None, vmax, tend, (
                f"VMAX is blank and TEND-TSTART-TRISE = {tend:g}-{tstart:g}-"
                f"{trise:g} = 0 to card precision, so the back-solve "
                "VMAX = DIST/(TEND-TSTART-TRISE) divides by zero")
        if span < 0.0:
            return None, vmax, tend, (
                f"VMAX is blank and TEND-TSTART-TRISE = {tend:g}-{tstart:g}-"
                f"{trise:g} = {span:g} is NEGATIVE — the rise time alone "
                "exceeds the window, so the trapezoid has no plateau and the "
                "back-solve VMAX = DIST/(TEND-TSTART-TRISE) would come out "
                "with the wrong sign")
        vmax = dist / span
        note = (f"VMAX was blank and back-solved from DIST/(TEND-TSTART-TRISE) "
                f"= {dist:g}/{span:g} = {vmax:g}")
    else:
        # The SAME span the VMAX-blank arm computes, reached from the other
        # side: TEND-TSTART-TRISE == DIST/VMAX. Its two degeneracies (a zero
        # and a negative window) have to be refused here too, or the asymmetry
        # emits what the sibling arm refuses — the third, both cells blank, is
        # already handled above. DIST = 0 in particular does NOT give an
        # identically-zero curve on this arm — it collapses TEND onto
        # TSTART+TRISE and
        # _strictly_increasing then nudges the duplicated abscissae apart into
        # a VMAX-height spike one card digit wide (MEASURED: DIST blank,
        # TRISE 1e-3, VMAX 100 -> (0,0) (1e-3,100) (1.00001e-3,100)
        # (1.00002e-3,0)), i.e. a stated velocity written over a window the
        # deck never asked for.
        window = dist / vmax
        if window == 0.0:
            return None, vmax, tend, (
                f"VMAX = {vmax:g} is stated and DIST = 0, so the back-solve "
                f"TEND = DIST/VMAX + TSTART + TRISE = {tstart + trise:g} "
                "collapses the window onto TSTART+TRISE: the trapezoid's third "
                "vertex (TEND-TRISE) lands ON its first and the plateau has "
                "zero width. That is the degeneracy the VMAX-blank arm refuses "
                "as TEND-TSTART-TRISE = 0, reached from the other side — and "
                "every field on this card has default 'none' (Vol I R17 "
                "p.17-153), so a blank DIST is a missing input rather than a "
                "stated zero")
        if window < 0.0:
            return None, vmax, tend, (
                f"VMAX = {vmax:g} is stated and DIST/VMAX = {window:g} is "
                f"NEGATIVE, so the back-solve TEND = DIST/VMAX + TSTART + "
                f"TRISE = {window + tstart + trise:g} puts TEND BEFORE "
                "TSTART+TRISE and the trapezoid runs backwards. DIST is 'Total "
                "distance tool will travel (area under curve)' (Vol I R17 "
                "p.17-154), so its sign has to match VMAX's")
        new_tend = window + tstart + trise
        if tend and abs(new_tend - tend) > 1.0e-12 * max(1.0, abs(tend)):
            note = (f"both TEND ({tend:g}) and VMAX ({vmax:g}) are stated, "
                    "which Vol I R17 p.17-154 forbids ('Input either TEND or "
                    f"VMAX'); VMAX was honoured and TEND recomputed as "
                    f"DIST/VMAX + TSTART + TRISE = {new_tend:g}")
        elif not tend:
            note = (f"TEND was blank and back-solved from DIST/VMAX + TSTART "
                    f"+ TRISE = {new_tend:g}")
        tend = new_tend
    pts = [(tstart, 0.0), (tstart + trise, vmax),
           (tend - trise, vmax), (tend, 0.0)]
    return _strictly_increasing(pts), vmax, tend, note


def _card_abscissa(v: float) -> float:
    """The abscissa the starter reads back from a ``_f`` field (%.10G, or
    %.6E outside 1e-4..1e15) — the value ``hm_read_funct.F:240`` compares.

    A tie-break finer than the printed field survives in memory and vanishes on
    the card (#113), so monotonicity has to be enforced on THIS number.
    """
    if v == 0.0:
        s = "0"
    elif abs(v) >= 1e15 or (0.0 < abs(v) < 1e-4):
        s = f"{v:.6E}"
    else:
        s = f"{v:.10G}"
    return float(s)


def _strictly_increasing(pts):
    """Force a point list to grow strictly AS PRINTED (see _card_abscissa).

    The TIE-ONLY half of ``writer/loads._monotonic_abscissae``, DELIBERATELY
    kept separate rather than routed through it. That function grew a REVERSAL
    arm — a stated ``x[k] < x[k-1]`` is re-anchored onto the segment LS-DYNA's
    own ``LCINT`` rediscretization jumps to — and that rule was derived from a
    user-typed reversed pair in a real deck. A ``*DEFINE_CURVE_SMOOTH``
    trapezoid is SYNTHESIZED here from TSTART/TRISE/TEND, so a crossing means
    the four vertices were computed in a degenerate order, not that the deck
    stated a reversal; re-anchoring one would move a vertex the deck never
    typed. The tie repair (nudge the abscissa, keep the ordinate) is the right
    answer for that, and it runs at PARSE time because the smooth curve is
    stored straight into ``state.curves``. Points already strictly increasing
    are returned unchanged, so a well-formed curve is byte-identical either
    way.
    """
    out = []
    for a, o in pts:
        x = float(a)
        if out:
            prev = _card_abscissa(out[-1][0])
            step = max(abs(prev), 1.0) * 1.0e-8
            for _ in range(64):
                if _card_abscissa(x) > prev:
                    break
                x = prev + step
                step *= 2.0
        out.append((x, float(o)))
    return out


def handle_define_curve_smooth(block: Block, state: ConversionState) -> None:
    """``*DEFINE_CURVE_SMOOTH[_TITLE]`` → ``/FUNCT_SMOOTH``.

    Card 1 (Vol I R17 p.17-153/154, ``Keyword971_R13.0/CURVE/
    define_curve_smooth.cfg:87-88`` ``%10d%10d%10lg%10lg%10lg%10lg%10lg``)::

        LCID   SIDR   DIST   TSTART   TEND   TRISE   VMAX

    There is no eighth cell: ``LSD_LCINT`` exists in the cfg ATTRIBUTES but is
    not on the R13.0 FORMAT card and not in the manual, so it is not parsed
    (the #127 "parse only the fields the keyword defines" rule).

    The curve is registered in ``state.curves`` like an ordinary
    ``*DEFINE_CURVE`` and merely FLAGGED in ``state.funct_smooth_ids``, because
    ``/FUNCT_SMOOTH`` shares ONE starter id namespace with ``/FUNCT`` and
    ``/TABLE``: ``hm_read_funct.F`` reads both keywords (``HM_OPTION_COUNT
    ('/FUNCT')`` :103 and ``('/FUNCT_SMOOTH')`` :104) into the same
    ``NPC/PLD/NOM_OPT`` arrays under one running index, differing only by
    ``NPC(2*NFUNCT+L+1) = ISMOOTH``. MEASURED: ``/FUNCT/8002`` beside
    ``/FUNCT_SMOOTH/8002`` is ``ERROR ID : 79 ** ERROR: DUPLICATE ID / IN
    FUNCTION & TABLE DEFINITION``. Storing it in ``state.curves`` makes
    ``next_curve_id`` dodge it and makes all 97 existing "is this LCID
    defined?" membership tests resolve it, with no new registry for a future
    allocator to forget (the #111 lesson).

    ``SIDR`` (0 transient / 1 dynamic-relaxation only / 2 both) has no Radioss
    counterpart and is warn-dropped BY NAME; ``SIDR = 1`` additionally means
    the curve must not drive the transient run at all.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    f = _card(block.raw, offset, fixed=True, n=8, w=10)
    if not f or not f[0].strip():
        return
    lcid = to_int(f[0])
    if lcid <= 0:
        state.warn("*DEFINE_CURVE_SMOOTH: LCID "
                   f"{f[0].strip()!r} is not a positive id — card dropped.")
        return
    sidr = to_int(f[1]) if len(f) > 1 else 0
    dist = to_float(f[2]) if len(f) > 2 else 0.0
    tstart = to_float(f[3]) if len(f) > 3 else 0.0
    tend = to_float(f[4]) if len(f) > 4 else 0.0
    trise = to_float(f[5]) if len(f) > 5 else 0.0
    vmax = to_float(f[6]) if len(f) > 6 else 0.0
    label = f"*DEFINE_CURVE_SMOOTH LCID {lcid}"
    # A cell that is a *PARAMETER reference the parser could not resolve reads
    # back as 0.0 and would silently change the ramp; say which cell it was.
    unresolved = [name for name, cell in
                  (("DIST", 2), ("TSTART", 3), ("TEND", 4), ("TRISE", 5),
                   ("VMAX", 6))
                  if len(f) > cell and f[cell].strip().startswith(("&", "-&"))
                  and to_float(f[cell]) == 0.0]
    if unresolved:
        state.warn(
            f"{label}: the cell(s) {', '.join(unresolved)} hold a *PARAMETER "
            "reference the parser could not resolve, and were read as 0. The "
            "curve below is the one that reading implies, not the deck's "
            "intent. The parser evaluates a bare '&name', a sign-folded "
            "'-&name', inline arithmetic in the cell ('&tend/6.0') and the "
            "bracketed '<expr>' form, and it evaluates *PARAMETER_EXPRESSION "
            "definitions — so a cell that still reads 0 names something that "
            "is genuinely undefined at this point in the deck, or that the "
            "expression grammar refuses. Look for the parser's own message "
            "about that name: it says which.")
    pts, vmax, tend, note = smooth_curve_points(dist, tstart, tend, trise, vmax)
    if pts is None:
        state.warn(
            f"{label}: {note} — no /FUNCT_SMOOTH emitted. dyna2rad raises the "
            "same refusal for the blank/blank case only (reader message "
            "200039, 'At least one of the input parameters must be non zero: "
            "VMAX, TEND'), and silently emits an all-zero flat curve for the "
            "others.")
        return
    if note:
        state.warn(f"{label}: {note}.")
    if unresolved:
        # The consequence in numbers, not just in principle: a reader has to be
        # able to see the plateau velocity the zero-read implies and compare it
        # against the deck's intent without redoing the back-solve by hand.
        state.warn(
            f"{label}: reading {', '.join(unresolved)} as 0 makes the emitted "
            f"curve DIST = {dist:g} over TSTART = {tstart:g} .. TEND = "
            f"{tend:g} with TRISE = {trise:g}, i.e. a plateau of VMAX = "
            f"{vmax:g}. Check that number against the deck before running: "
            "the area under the curve (the tool's total travel) is right by "
            "construction, but the plateau value and the ramp shape are not.")
    if trise > 0.0 and 2.0 * trise > (tend - tstart) * (1.0 + 1.0e-9):
        state.warn(
            f"{label}: TRISE = {trise:g} is more than half the window "
            f"TEND-TSTART = {tend - tstart:g}, so the rise and the fall "
            "overlap and the trapezoid's third vertex (TEND-TRISE) falls "
            "BEFORE its second (TSTART+TRISE). The vertices were reordered "
            "into a strictly increasing abscissa list — starter ERROR 156 "
            "otherwise — but the emitted ramp is no longer the shape of "
            "Figure 17-25.")
    if trise <= 0.0:
        state.warn(
            f"{label}: TRISE = {trise:g} makes the trapezoid's rise and fall "
            "instantaneous, i.e. the four vertices collapse onto two "
            "abscissae. A /FUNCT whose abscissa does not grow is starter "
            "ERROR 156 (hm_read_funct.F:240-243), so the two duplicated "
            "abscissae were nudged apart by one card digit. The emitted "
            f"function still holds VMAX = {vmax:g} over TSTART..TEND and its "
            f"area is DIST = {dist:g}; only the ramp SHAPE is lost.")
    if sidr:
        state.warn(
            f"{label}: SIDR = {sidr} has no /FUNCT_SMOOTH slot and was "
            "dropped (dyna2rad drops it too). SIDR scopes the curve to "
            "LS-DYNA's dynamic-relaxation stress-initialization phase"
            + (" — SIDR=1 means the curve is used for initialization ONLY and "
               "NOT in the transient analysis, so driving the transient run "
               "with it, as this conversion now does, is not what the deck "
               "asks for." if sidr == 1 else
               " (SIDR=2 = both phases; OpenRadioss has no separate "
               "relaxation phase, so the transient use is all that survives)."))
    if dist == 0.0:
        # Reachable only on the VMAX-BLANK arm: with VMAX stated, DIST = 0 is a
        # zero-width window and smooth_curve_points refuses the card above, so
        # `pts` would be None and this line unreachable. Scoped that way the
        # claim below is exact — VMAX really did back-solve to 0 and the four
        # ordinates really are 0. Every field on this card has default "none"
        # (Vol I R17 p.17-153), so a blank DIST is a missing input, not a
        # stated zero, and DIST is the ONLY thing that sets the curve's height
        # ("Total distance tool will travel (area under curve)", p.17-154): a
        # legal, accepted card that moves nothing, the #122 class.
        state.warn(
            f"{label}: DIST = 0 with VMAX blank, so the whole curve is "
            "identically zero — VMAX = DIST/(TEND-TSTART-TRISE) = 0 and a "
            "consumer driven by it does not move at all. DIST is 'Total "
            "distance tool will travel (area under curve)' and has no default "
            "(Vol I R17 p.17-153/154), so a blank cell here is a missing input "
            "rather than a stated zero. The curve was emitted as written; "
            "state DIST if the tool is meant to move. (With VMAX STATED the "
            "same DIST = 0 is refused instead: there it collapses TEND onto "
            "TSTART+TRISE and would emit a VMAX-height spike, not a zero.)")
    if lcid in state.curves or lcid in state.define_tables:
        state.warn(
            f"{label}: this id is already defined by a "
            + ("*DEFINE_TABLE" if lcid in state.define_tables
               else "*DEFINE_CURVE" if lcid not in state.funct_smooth_ids
               else "*DEFINE_CURVE_SMOOTH")
            + " in the same deck. Vol I R17 p.17-153 requires the "
            "*DEFINE_CURVE_SMOOTH LCID to be unique, and LS-DYNA shares one "
            "load-curve id namespace across *DEFINE_CURVE / "
            "*DEFINE_CURVE_SMOOTH (tables share it too, p.17-445: 'Tables and "
            "Load curves may not share common IDs'). The smooth curve below "
            "replaces the earlier definition; renumber one of the cards.")
    state.curves[lcid] = Curve(lcid, title, 1.0, 1.0, 0.0, 0.0, pts)
    # NOT appended to state.curve_order. That list is the *DEFINE_CURVE
    # ORDERING used to resolve the legacy positional *DEFINE_TABLE form, and
    # the manual scopes it to that keyword by name: the curves "must be defined
    # as lists of (x, y) pairs in a collection of *DEFINE_CURVE sections that
    # directly follow the *DEFINE_TABLE section", with input "terminated when a
    # '*DEFINE_CURVE' keyword card is found" (Vol I R17 p.17-444). A smooth
    # curve after a legacy table is not one of its rows.
    state.funct_smooth_ids.add(lcid)


def perturbation_node_records(raw: List[str]):
    """Yield ``(card1_idx, card2_indices)`` per ``*PERTURBATION_NODE`` record.

    One ``*PERTURBATION_NODE`` keyword carries exactly ONE card 1 and then the
    card-2 stack its ``TYPE`` selects (Vol I R17 p.38-4..38-10):

    ======  ==========================================================
    TYPE    card 2
    ======  ==========================================================
    1       ``AMPL XWL XOFF YWL YOFF ZWL ZOFF``, REPEATED to the next ``*``
    2       ``FADE``
    3       ``FNAME`` (a free string)
    4       ``CSTYPE ELLIP1 ELLIP2 RND`` + 1..3 ``CFTYPE CFC1 CFC2 CFC3``
    8       ``AMPL DTYPE``
    ======  ==========================================================

    RAW CONTIGUITY (#119): card 2 is claimed by ROW INDEX from card 1. An
    all-blank card 2 is legal (every field of 2a/2b/2d/2e defaults), and a
    "next non-blank row" walk would step past the placeholder.
    """
    i = 0
    n = len(raw)
    while i < n and not raw[i].strip():
        i += 1
    if i >= n:
        return
    card1 = i
    f = _card(raw, card1, fixed=True, n=8, w=10)
    ptype = to_int(f[0]) if f and f[0].strip() else 1
    i += 1
    if ptype == 4:
        # card 2d + 1..3 card-2d.1 rows, the count keyed on CSTYPE
        cstype = 0
        if i < n:
            g = _card(raw, i, fixed=True, n=8, w=10)
            cstype = to_int(g[0]) if g and g[0].strip() else 0
        extra = {1: 1, 2: 3}.get(cstype, 2) if cstype else 1
        rows = [k for k in range(i, min(n, i + 1 + extra))]
    elif ptype == 1:
        rows = list(range(i, n))
    else:
        rows = [i] if i < n else []
    yield (card1, rows)


def handle_perturbation_node(block: Block, state: ConversionState) -> None:
    """``*PERTURBATION_NODE`` → ``/RANDOM`` or ``/RANDOM/GRNOD``.

    Card 1b (Vol I R17 p.38-4): ``TYPE NSID SCL CMP ICOORD CID``, defaults
    ``TYPE = 1``, ``NSID = {all}``, ``SCL = 1.0``, ``CMP = 7``, ``ICOORD = 0``,
    ``CID = 0``. The type-dependent card 2 is claimed by raw row index.

    ``/RANDOM`` is the only Radioss card that touches nodal COORDINATES —
    ``hm_read_rand.F:161-163`` adds ``XALEA*ALEAT()`` to ``X(1..3,I)`` at
    STARTER time, which is exactly "modifies the three-dimensional coordinates
    for the whole model or a node set" (p.38-2). The ``/PERTURB/*`` family in
    the same starter directory is a different feature: ``/PERTURB/PART/SHELL``
    accepts only ``chvar = "thick"`` (``hm_read_perturb_part_shell.F:142``) and
    ``/PERTURB/PART/SOLID`` only ``chvar = "dens"`` (:139) — those are the
    counterparts of ``*PERTURBATION_SHELL_THICKNESS`` and
    ``*PERTURBATION_MAT``, not of ``_NODE``.

    Only the TYPE it can express is stored; the writer decides scope and warns.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    body = block.raw[offset:]
    for card1, rows in perturbation_node_records(body):
        f = _card(body, card1, fixed=True, n=8, w=10)
        if not f:
            return
        rec = PerturbationNode(
            ptype=to_int(f[0]) if f[0].strip() else 1,
            nsid=to_int(f[1]) if len(f) > 1 else 0,
            scl=_ffield(f, 2, 1.0),
            cmp=to_int(f[3]) if len(f) > 3 and f[3].strip() else 7,
            icoord=to_int(f[4]) if len(f) > 4 else 0,
            cid=to_int(f[5]) if len(f) > 5 else 0,
            title=title)
        if rec.ptype == 8 and rows:
            g = _card(body, rows[0], fixed=True, n=8, w=10)
            rec.ampl = _ffield(g, 0, 1.0)
            rec.dtype = to_float(g[1]) if len(g) > 1 else 0.0
        state.perturbation_nodes.append(rec)


def final_geometry_node_row(line: str, ibrth: int) -> List[str]:
    """Slice one ``*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY`` node card.

    NOT the uniform 8x10 grid. Vol I R17 p.5-74 lays both card formats out over
    ten 8-char columns, with the three coordinates on DOUBLED columns
    (recovered from the manual's own column ruler):

    * card 2a (``IBRTH = 0``): ``NID`` I8, ``X``/``Y``/``Z`` E16 each,
      ``LCID`` I8, ``DEATH`` E16 — the same
      ``%8d%16lg%16lg%16lg%8d%16lg`` the R14.1 cfg states (:124);
    * card 2b (``IBRTH = 1``): the same first five, then ``DEATH`` E8 and
      ``BIRTH`` E8, so the seventh variable still fits inside eighty columns.

    Slicing this card 10-wide is the ``*ELEMENT_MASS`` failure (:157-166): the
    read would start ``Y`` in the middle of ``X``. A comma/space free-format
    row is split as written, the convention every other card in this converter
    follows.
    """
    data = _strip_inline_comment(line)
    if "," in data:
        toks = parse_free(data)
        return toks + [""] * max(0, 7 - len(toks))
    if ibrth == 1:
        cuts = ((0, 8), (8, 24), (24, 40), (40, 56), (56, 64), (64, 72),
                (72, 80))
    else:
        cuts = ((0, 8), (8, 24), (24, 40), (40, 56), (56, 64), (64, 80),
                (80, 80))
    out = [data[a:b].strip() for a, b in cuts]
    if any(" " in x for x in out):
        toks = parse_free(data)
        return toks + [""] * max(0, 7 - len(toks))
    return out


def handle_boundary_prescribed_final_geometry(block: Block,
                                              state: ConversionState) -> None:
    """``*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY`` → ``/IMPDISP/FGEO``.

    Card 1 (Vol I R17 p.5-73): ``BPFGID LCIDF DEATHD IBRTH``. The node rows
    repeat to the next ``*`` and are claimed by RAW CONTIGUITY from card 1
    (#119) — a blank row inside the list is skipped, never treated as a new
    card 1.
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    raw = block.raw
    f = _card(raw, offset, fixed=True, n=8, w=10)
    if not f:
        return
    rec = BoundaryPrescribedFinalGeometry(
        bpfgid=to_int(f[0]) if f[0].strip() else 0,
        lcidf=to_int(f[1]) if len(f) > 1 else 0,
        deathd=to_float(f[2]) if len(f) > 2 else 0.0,
        ibrth=to_int(f[3]) if len(f) > 3 else 0,
        title=title)
    for k in range(offset + 1, len(raw)):
        line = raw[k]
        if not line.strip():
            continue
        g = final_geometry_node_row(line, rec.ibrth)
        if not g or not g[0].strip():
            continue
        nid = to_int(g[0])
        if nid == 0:
            continue
        rec.nodes.append(FinalGeometryNode(
            nid=nid,
            x=to_float(g[1]) if len(g) > 1 else 0.0,
            y=to_float(g[2]) if len(g) > 2 else 0.0,
            z=to_float(g[3]) if len(g) > 3 else 0.0,
            lcid=to_int(g[4]) if len(g) > 4 else 0,
            death=to_float(g[5]) if len(g) > 5 else 0.0,
            birth=to_float(g[6]) if len(g) > 6 and rec.ibrth == 1 else 0.0))
    state.final_geometries.append(rec)


#: The literal string that promotes the card after card 1 from a node card to
#: an optional card: "For LS-DYNA to interpret the card as this card, include
#: the string 'OPTCARD' in the first column. Otherwise, the input reader
#: assumes the second card is Card 4." (Vol I R17 p.30-80). This is the one
#: legitimate CONTENT test in an optional-card walk — the manual mandates it —
#: and it is applied only at the fixed row positions 1/2/3 after card 1, never
#: as a "find the next OPTCARD" scan.
_SPRINGBACK_OPTCARD = "OPTCARD"


def springback_records(raw: List[str]):
    """Yield ``(card1_idx, optcard_indices, node_row_indices)``.

    RAW CONTIGUITY (#119) with the manual's own ``OPTCARD`` promotion rule: the
    rows immediately after card 1 are optional cards 2, 3.1 and 3.2 for as long
    as each begins with ``OPTCARD``; the first row that does not is the first
    card-4 ``NID TC RC`` node row, and every remaining row is another one.
    """
    i = 0
    n = len(raw)
    while i < n and not raw[i].strip():
        i += 1
    if i >= n:
        return
    card1 = i
    i += 1
    opt: List[int] = []
    while i < n and len(opt) < 3:
        line = raw[i]
        if line.strip().upper().startswith(_SPRINGBACK_OPTCARD):
            opt.append(i)
            i += 1
            continue
        break
    nodes = [k for k in range(i, n) if raw[k].strip()]
    yield (card1, opt, nodes)


def handle_interface_springback(block: Block, state: ConversionState) -> None:
    """``*INTERFACE_SPRINGBACK_LSDYNA`` → the engine ``/DYNAIN`` block.

    Card 1 (Vol I R17 p.30-81, ``Keyword971_R14.1/CONTROL_CARDS/
    interface_springback.cfg:305`` ``%10d%10d%10d%10s%10d%10d%10d%10d``)::

        PSID   NHSV   FTYPE   <blank>   FTENSR   NTHHSV   RFLAG   INTSTRN

    Column FOUR is blank — every corpus carrier's own comment line spells it
    ``$#    psid      nshv     ftype         -    ftensr    nthhsv     rflag
    intstrn`` — so ``FTENSR`` is cell index 4, not 3.

    Optional cards 2 / 3.1 / 3.2 are claimed by the ``OPTCARD`` rule; the rest
    are card-4 ``NID TC RC`` rows (``%10d%10lf%10lf``, cfg :327).
    """
    offset = _title_offset(block)
    title = _read_title(block) if offset else ""
    body = block.raw[offset:]
    for card1, opt, nodes in springback_records(body):
        f = _card(body, card1, fixed=True, n=8, w=10)
        if not f:
            return
        rec = InterfaceSpringback(
            psid=to_int(f[0]) if f[0].strip() else 0,
            nhsv=to_int(f[1]) if len(f) > 1 else 0,
            ftype=to_int(f[2]) if len(f) > 2 else 0,
            ftensr=to_int(f[4]) if len(f) > 4 else 0,
            nthhsv=to_int(f[5]) if len(f) > 5 else 0,
            rflag=to_int(f[6]) if len(f) > 6 else 0,
            intstrn=to_int(f[7]) if len(f) > 7 else 0,
            keyword=block.keyword, title=title)
        if opt:
            rec.has_optcard = True
            g = _card(body, opt[0], fixed=True, n=8, w=10)
            rec.sldo = to_int(g[1]) if len(g) > 1 else 0
            rec.ncyc = to_int(g[2]) if len(g) > 2 else 0
            rec.fsplit = to_int(g[3]) if len(g) > 3 else 0
            rec.ndflag = to_int(g[4]) if len(g) > 4 else 0
            rec.cflag = to_int(g[5]) if len(g) > 5 else 0
            rec.hflag = to_int(g[6]) if len(g) > 6 else 0
        if len(opt) > 1:
            g = _card(body, opt[1], fixed=True, n=8, w=10)
            rec.dtwrt = to_float(g[1]) if len(g) > 1 else 0.0
        if len(opt) > 2:
            g = _card(body, opt[2], fixed=True, n=8, w=10)
            rec.nmwrt = to_int(g[1]) if len(g) > 1 else 0
            rec.ivflg = to_int(g[2]) if len(g) > 2 else 0
        for k in nodes:
            g = _card(body, k, fixed=True, n=8, w=10)
            nid = to_int(g[0]) if g and g[0].strip() else 0
            if nid <= 0:
                continue
            rec.constraints.append(
                (nid, to_int(g[1]) if len(g) > 1 else 0,
                 to_int(g[2]) if len(g) > 2 else 0))
        state.interface_springbacks.append(rec)


def _springback_sibling(keyword: str, what: str):
    """A recognized + NAMED warn-drop for an ``*INTERFACE_SPRINGBACK`` option
    this converter does not convert.

    dyna2rad reads ``*INTERFACE_SPRINGBACK_LSDYNA`` and nothing else (one
    ``SelectionRead`` at ``convertcards.cxx:1071``), so ``_NASTRAN``,
    ``_SEAMLESS`` and ``_EXCLUDE`` vanish there without a word. Named here
    instead: each writes a DIFFERENT artifact, and a deck whose whole purpose
    is that artifact should not read "skipped: 1 unsupported keyword".
    """
    def _handler(block: Block, state: ConversionState) -> None:
        state.note_recognized_not_emitted(keyword, what)
    _handler.__name__ = f"handle_{keyword.lower()}"
    return _handler


def _perturbation_sibling(keyword: str, what: str):
    """The same named warn-drop for the two ``*PERTURBATION`` options that
    perturb something other than the nodal coordinates."""
    def _handler(block: Block, state: ConversionState) -> None:
        state.note_recognized_not_emitted(keyword, what)
    _handler.__name__ = f"handle_{keyword.lower()}"
    return _handler


#: ``*INTERFACE_SPRINGBACK_OPTION1_{OPTION2}`` (Vol I R17 p.30-80): OPTION1 is
#: one of LSDYNA / NASTRAN / SEAMLESS / EXCLUDE and OPTION2 is blank or
#: NOTHICKNESS, so there are exactly EIGHT legal spellings. ``None`` = this
#: converter converts the card; a string = the named warn-drop reason.
#:
#: Kept as OPTION1 x OPTION2 rather than as eight literals because a
#: hand-written variant table drifts: the ``EXCLUDE_NOTHICKNESS`` corner was
#: missing from exactly such a list and fell through to "skipped: 1 unsupported
#: keyword" (the #116 lesson — generate every spelling from one source).
_SPRINGBACK_OPTION1 = {
    "LSDYNA": None,
    "NASTRAN":
        "a NASTRAN-format springback deck (a bulk-data file, not a dynain). "
        "OpenRadioss writes /DYNAIN in LS-DYNA keyword format and /STATE in "
        "Radioss format; neither is NASTRAN bulk data, so nothing was emitted",
    "SEAMLESS":
        "SEAMLESS springback, which makes LS-DYNA run the implicit springback "
        "analysis ITSELF after the forming run terminates (p.30-80). "
        "OpenRadioss has no second-stage handoff of that kind: the /DYNAIN "
        "file must be read back into a NEW deck by hand. Nothing was "
        "emitted — emitting the /DYNAIN half alone would look like the "
        "springback had been set up",
    "EXCLUDE":
        "a list of parts to EXCLUDE from the springback output (p.30-80 "
        "Remark 9). /DYNAIN/DT selects parts positively and has no exclusion "
        "form, so the exclusion was dropped; if a "
        "*INTERFACE_SPRINGBACK_LSDYNA is present its own PSID still decides "
        "the scope",
}

#: OPTION2 = NOTHICKNESS (Vol I R17 p.30-80 Remark 1) suppresses the
#: ``*ELEMENT_SHELL_THICKNESS`` block of the dynain. The Radioss /DYNAIN writer
#: emits it unconditionally (``dynain_shel_mp.F:256``, no content sub-key to
#: switch it off), so the option cannot be honoured — but for OPTION1 = LSDYNA
#: the rest of the card can be, so it routes to the same handler and the writer
#: names the difference.
_SPRINGBACK_OPTION2 = ("", "_NOTHICKNESS")


def _springback_keyword_handlers():
    """The eight ``*INTERFACE_SPRINGBACK`` spellings and their handlers."""
    out = {}
    for _o1, _what in _SPRINGBACK_OPTION1.items():
        for _o2 in _SPRINGBACK_OPTION2:
            kw = f"INTERFACE_SPRINGBACK_{_o1}{_o2}"
            if _what is None:
                out[kw] = handle_interface_springback
            else:
                out[kw] = _springback_sibling(
                    kw, _what + (" (the NOTHICKNESS option is moot here: "
                                 "nothing is written at all)" if _o2 else ""))
    return out


#: The RARE CARDS batch, as ONE source for HANDLERS and for
#: assembly._OFFSET_SPECS (#116: a spelling the handler reads and the
#: *INCLUDE_TRANSFORM offsetter does not know keeps its original ids while the
#: rest of the include moves — a dangling EID/NID/LCID at 0 diagnostics).
RARE_CARD_KEYWORDS = {
    **{f"DEFINE_ELEMENT_DEATH_{_o}": handle_define_element_death
       for _o in _ELEMENT_DEATH_OPTIONS},
    "DEFINE_CURVE_SMOOTH": handle_define_curve_smooth,
    "PERTURBATION_NODE": handle_perturbation_node,
    "BOUNDARY_PRESCRIBED_FINAL_GEOMETRY":
        handle_boundary_prescribed_final_geometry,
    **_springback_keyword_handlers(),
    # ── Recognized + named warn-drop ──────────────────────────────────────
    "PERTURBATION_MAT": _perturbation_sibling(
        "PERTURBATION_MAT",
        "a perturbed MATERIAL parameter, which LS-DYNA supports for *MAT_238 "
        "and solid elements only (p.38-12 Remark 10). The Radioss analogue is "
        "/PERTURB/PART/SOLID (density) or /PERTURB/FAIL, neither of which "
        "reaches a *MAT_238 parameter, so nothing was emitted"),
    "PERTURBATION_SHELL_THICKNESS": _perturbation_sibling(
        "PERTURBATION_SHELL_THICKNESS",
        "a perturbed SHELL THICKNESS field. /PERTURB/PART/SHELL with "
        "chvar='thick' (hm_read_perturb_part_shell.F:142) is the Radioss "
        "counterpart and is not implemented yet, so nothing was emitted"),
}


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
    # *ELEMENT_TSHELL — an 8-node THICK shell → /BRICK on a /PROP/TYPE20|21|22.
    # The _BETA / _COMPOSITE spellings are registered from the grammar below,
    # and dispatch() routes any other one to the same handler's provisional
    # path. dyna2rad's CFG has neither option, so it drops those blocks whole.
    "ELEMENT_TSHELL":                         handle_element_tshell,
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
    # _MISC adds one option card whose field 1 (COHTHK) is the section-wise
    # cohesive-thickness override → /PROP/TYPE43 True_thickness. The handler's
    # card-set walk already strides the option card (_SECTION_SOLID_OPTION_
    # CARDS), so registering the spelling is what turns it from a
    # skipped_keywords entry (part loses its whole property) into a parse.
    "SECTION_SOLID_MISC":                     handle_section_solid,
    # *SECTION_TSHELL takes no option suffix of its own (only the universal
    # _TITLE / _ID, which the parser strips), so one exact key covers it.
    "SECTION_TSHELL":                         handle_section_tshell,
    # *SECTION_SPH's four option spellings are registered from a loop below (an
    # unregistered one would land in skipped_keywords and its parts would lose
    # the whole /PROP/SPH, i.e. the particle mass AND the smoothing length).
    "SECTION_SPH":                            handle_section_sph,
    "SECTION_BEAM":                           handle_section_beam,
    "SECTION_DISCRETE":                       handle_section_discrete,

    # Integration rules. Neither keyword takes an LS-DYNA option suffix (they
    # have no _TITLE variant either), so a single exact key is enough for each —
    # no grammar loop and no prefix entry. *SECTION_BEAM's QR/IRID field carries
    # the identical EQ.-n semantics as *SECTION_SHELL's.
    "INTEGRATION_SHELL":                      handle_integration_shell,
    "INTEGRATION_BEAM":                       handle_integration_beam,

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
    # ── Metal plasticity batch 2 ───────────────────────────────────────────
    # MAT_081/082 (+ _ORTHO / _RCDC / _RCDC1980 / _STOCHASTIC) ride the MAT_024
    # /MAT/LAW36 machinery and add /FAIL/TAB1 from EPPF/EPPFR. Every option
    # spelling gets its own key: the dispatcher is an exact dict match after
    # only _ID/_TITLE/_SUBTITLE are stripped.
    "MAT_PLASTICITY_WITH_DAMAGE":             handle_mat_plasticity_with_damage,
    "MAT_PLASTICITY_WITH_DAMAGE_ORTHO":       handle_mat_plasticity_with_damage,
    "MAT_PLASTICITY_WITH_DAMAGE_ORTHO_RCDC":  handle_mat_plasticity_with_damage,
    "MAT_PLASTICITY_WITH_DAMAGE_ORTHO_RCDC1980":
        handle_mat_plasticity_with_damage,
    "MAT_PLASTICITY_WITH_DAMAGE_STOCHASTIC":  handle_mat_plasticity_with_damage,
    "MAT_081":                                handle_mat_plasticity_with_damage,
    "MAT_81":                                 handle_mat_plasticity_with_damage,
    "MAT_081_STOCHASTIC":                     handle_mat_plasticity_with_damage,
    "MAT_082":                                handle_mat_plasticity_with_damage,
    "MAT_82":                                 handle_mat_plasticity_with_damage,
    "MAT_082_RCDC":                           handle_mat_plasticity_with_damage,
    "MAT_082_RCDC1980":                       handle_mat_plasticity_with_damage,
    # MAT_105 → the same LAW36 path + /FAIL/LEMAITRE from its card-3 triple
    "MAT_DAMAGE_2":                           handle_mat_damage_2,
    "MAT_105":                                handle_mat_damage_2,
    # MAT_019 → /MAT/LAW121 (PLAS_RATE), a 1:1 curve-for-curve target
    "MAT_STRAIN_RATE_DEPENDENT_PLASTICITY":
        handle_mat_strain_rate_dependent_plasticity,
    "MAT_019":                                handle_mat_strain_rate_dependent_plasticity,
    "MAT_19":                                 handle_mat_strain_rate_dependent_plasticity,
    # MAT_124 → /MAT/LAW66 (+ /VISC/PRONY, + a failure card). The _EOS variant
    # is a different keyword (LS-DYNA 155) with a different card set and is
    # deliberately NOT registered.
    "MAT_PLASTICITY_COMPRESSION_TENSION":
        handle_mat_plasticity_compression_tension,
    "MAT_124":                                handle_mat_plasticity_compression_tension,
    # MAT_120 → /MAT/LAW52 (GURSON); the _JC variant adds /FAIL/JOHNSON
    "MAT_GURSON":                             handle_mat_gurson,
    "MAT_120":                                handle_mat_gurson,
    "MAT_GURSON_JC":                          handle_mat_gurson,
    "MAT_120_JC":                             handle_mat_gurson,
    "MAT_GURSON_RCDC":                        handle_mat_gurson,
    "MAT_120_RCDC":                           handle_mat_gurson,
    "MAT_GURSON_BFRAC":                       handle_mat_gurson,
    "MAT_120_BFRAC":                          handle_mat_gurson,
    # MAT_012 → /MAT/LAW2, with G/K derived to E/nu in the writer prepass
    "MAT_ISOTROPIC_ELASTIC_PLASTIC":          handle_mat_isotropic_elastic_plastic,
    "MAT_012":                                handle_mat_isotropic_elastic_plastic,
    "MAT_12":                                 handle_mat_isotropic_elastic_plastic,
    # MAT_122 → /MAT/LAW43 (HR=1/3) or /MAT/LAW32 (HR=2). *MAT_122_3D and
    # *MAT_122_TABULATED are separate keywords with different card sets.
    "MAT_HILL_3R":                            handle_mat_hill_3r,
    "MAT_122":                                handle_mat_hill_3r,
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
    # *MAT_ANISOTROPIC_VISCOPLASTIC (103) → /MAT/LAW128 (HILL_VISC_PLAST), the
    # near 1:1 counterpart: Hill surface, Voce hardening and the viscous term
    # all carried over. (It is NOT the LAW36 isotropic reduction an older
    # comment here claimed — that was replaced by LAW128 in PRs #60-#64.)
    # Kinematic hardening folds into the isotropic Voce fit and the overstress
    # becomes multiplicative — both warned, see the handler.
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
    # MAT_022 → /MAT/LAW25 (COMPSH) + /FAIL/CHANG on a shell-only material,
    # /MAT/LAW127 when a part holds solids or thick shells. Not MAT_054 with
    # fewer fields: MAT_022 is orthotropic ELASTIC with BRITTLE Chang-Chang
    # failure — no XC, no EFS, no TFAIL, no element deletion at all.
    "MAT_COMPOSITE_DAMAGE":                   handle_mat_composite_damage,
    "MAT_022":                                handle_mat_composite_damage,
    "MAT_22":                                 handle_mat_composite_damage,
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
    # MAT_034 → /MAT/LAW19 (FABRI) + /PROP/TYPE9, or /MAT/LAW58 (FABR_A) +
    # /PROP/TYPE16 when the card-7 curves are there (writer/fabric.py).
    "MAT_FABRIC":                             handle_mat_fabric,
    "MAT_034":                                handle_mat_fabric,
    "MAT_34":                                 handle_mat_fabric,
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
    # Foam batch: MAT_005 → LAW21 (P(mu) transform); MAT_073 → LAW90
    # [+ /VISC/PRONY]; MAT_126 → LAW50 (+ /PROP/TYPE6); MAT_154 → LAW115;
    # MAT_177 → LAW62 (LCID=0 constants branch; LCID>0 warn-skips at parse).
    #
    # *MAT_SOIL_AND_FOAM_FAILURE (MAT_014) used to be excluded here on the
    # ground that "dyna2rad maps it to law 14, which has no case in its
    # dispatch switch and falls into the generic 1:1 dump". That is a fact
    # about d2r, not a reason for k2rad, which has its own MAT_005 -> LAW21
    # route — the #130 exclusion-list audit. Vol II R17 p.2-209 states the
    # keyword in one sentence: *"The input for this model is the same as for
    # *MATERIAL_SOIL_AND_FOAM (Type 5); however, when the pressure reaches the
    # tensile failure pressure, the element loses its ability to carry
    # tension."* /FAIL/SPALLING with Ifail_so = 1 is that latch exactly
    # (fail_spalling_s.F90:241-268), so the same handler reads both spellings
    # and the writer adds the rider.
    "MAT_SOIL_AND_FOAM":                      handle_mat_soil_and_foam,
    "MAT_5":                                  handle_mat_soil_and_foam,
    "MAT_005":                                handle_mat_soil_and_foam,
    "MAT_SOIL_AND_FOAM_FAILURE":              handle_mat_soil_and_foam,
    "MAT_14":                                 handle_mat_soil_and_foam,
    "MAT_014":                                handle_mat_soil_and_foam,
    "MAT_LOW_DENSITY_VISCOUS_FOAM":           handle_mat_low_density_viscous_foam,
    "MAT_73":                                 handle_mat_low_density_viscous_foam,
    "MAT_073":                                handle_mat_low_density_viscous_foam,
    "MAT_MODIFIED_HONEYCOMB":                 handle_mat_modified_honeycomb,
    "MAT_126":                                handle_mat_modified_honeycomb,
    "MAT_DESHPANDE_FLECK_FOAM":               handle_mat_deshpande_fleck_foam,
    "MAT_154":                                handle_mat_deshpande_fleck_foam,
    "MAT_HILL_FOAM":                          handle_mat_hill_foam,
    "MAT_177":                                handle_mat_hill_foam,
    # The RARE MATERIALS batch (*MAT_030, *MAT_156, *MAT_S15, the thermal
    # cards) is registered from RARE_MATERIAL_KEYWORDS below this dict — ONE
    # source shared with assembly._OFFSET_SPECS.
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
    # Viscoelastic batch: MAT_006 → LAW34; MAT_061 → LAW40; MAT_076 → LAW42 +
    # /VISC/PRONY; MAT_181/183 → LAW88 [+ /VISC/PRONY]; MAT_091/092 → LAW42.
    # The dispatcher is an exact dict match after only _ID/_TITLE/_SUBTITLE are
    # stripped, so the hyphen AND underscore spellings of the hyphenated names,
    # the literal "/" of *MAT_SIMPLIFIED_RUBBER/FOAM, and every option suffix
    # that changes the CARD LAYOUT each need a key of their own. The numeric
    # aliases *MAT_076 and *MAT_183 are missing from dyna2rad's own keyword
    # table (they fall into its raw 1:1 dump); k2rad registers them.
    "MAT_VISCOELASTIC":                       handle_mat_viscoelastic,
    "MAT_006":                                handle_mat_viscoelastic,
    "MAT_6":                                  handle_mat_viscoelastic,
    "MAT_KELVIN-MAXWELL_VISCOELASTIC":        handle_mat_kelvin_maxwell,
    "MAT_KELVIN_MAXWELL_VISCOELASTIC":        handle_mat_kelvin_maxwell,
    "MAT_061":                                handle_mat_kelvin_maxwell,
    "MAT_61":                                 handle_mat_kelvin_maxwell,
    "MAT_GENERAL_VISCOELASTIC":               handle_mat_general_viscoelastic,
    "MAT_GENERAL_VISCOELASTIC_MOISTURE":      handle_mat_general_viscoelastic,
    "MAT_076":                                handle_mat_general_viscoelastic,
    "MAT_76":                                 handle_mat_general_viscoelastic,
    # (*MAT_SIMPLIFIED_RUBBER/FOAM 181 and *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE
    #  183 are registered below — their _WITH_FAILURE/_LOG_LOG_INTERPOLATION
    #  grammar is generated rather than hand-listed.)
    "MAT_SOFT_TISSUE":                        handle_mat_soft_tissue,
    "MAT_091":                                handle_mat_soft_tissue,
    "MAT_91":                                 handle_mat_soft_tissue,
    "MAT_SOFT_TISSUE_VISCO":                  handle_mat_soft_tissue,
    "MAT_092":                                handle_mat_soft_tissue,
    "MAT_92":                                 handle_mat_soft_tissue,
    # Adhesives / cohesive batch: MAT_138 → LAW117; MAT_169 → LAW169;
    # MAT_240 → LAW116 (option variants warn-skip, registered below with the
    # generated grammars); MAT_252 → LAW120; MAT_ADD_DAMAGE_DIEM →
    # /FAIL/INIEVO. The numeric aliases *MAT_138 and *MAT_252 are missing from
    # dyna2rad's own keyword table (they fall into its broken Convert1To1
    # fallback — no /MAT, no message); k2rad registers them.
    "MAT_COHESIVE_MIXED_MODE":                handle_mat_cohesive_mixed_mode,
    "MAT_138":                                handle_mat_cohesive_mixed_mode,
    "MAT_ARUP_ADHESIVE":                      handle_mat_arup_adhesive,
    "MAT_169":                                handle_mat_arup_adhesive,
    "MAT_TOUGHENED_ADHESIVE_POLYMER":         handle_mat_toughened_adhesive,
    "MAT_252":                                handle_mat_toughened_adhesive,
    "MAT_ADD_DAMAGE_DIEM":                    handle_mat_add_damage_diem,
    # ── Tabulated Johnson-Cook batch ───────────────────────────────────────
    # MAT_224 → /MAT/LAW109 [+ /FAIL/TAB1]. _LOG_INTERPOLATION is the only
    # convertible option spelling (same handler, I_smooth=2 — the MAT_024
    # _LOG_INTERPOLATION precedent); LS-DYNA accepts no options on the
    # numeric *MAT_224 alias. _GYS and _ORTHO_PLASTICITY (264) change the
    # yield-surface model AND the card set, so they get the loud warn-skip
    # handler — dyna2rad drops both silently (no /MAT, part wired to 0).
    "MAT_TABULATED_JOHNSON_COOK":             handle_mat_tabulated_johnson_cook,
    "MAT_TABULATED_JOHNSON_COOK_LOG_INTERPOLATION":
        handle_mat_tabulated_johnson_cook,
    "MAT_224":                                handle_mat_tabulated_johnson_cook,
    "MAT_TABULATED_JOHNSON_COOK_GYS":         handle_mat_tabulated_jc_variant,
    "MAT_224_GYS":                            handle_mat_tabulated_jc_variant,
    "MAT_TABULATED_JOHNSON_COOK_ORTHO_PLASTICITY":
        handle_mat_tabulated_jc_variant,
    "MAT_264":                                handle_mat_tabulated_jc_variant,
    # ── Impact / blast materials batch ─────────────────────────────────────
    # MAT_110 → /MAT/LAW79, MAT_111 → /MAT/LAW126 (dyna2rad p_ConvertMatL110
    # CM:12491-12506 / p_ConvertMatL111 CM:5639-5674), and *MAT_ELASTIC's
    # _FLUID option → /MAT/LAW6 + /EOS/POLYNOMIAL (p_ConvertMatL1_FLUID
    # CM:12093-12136), which shares handle_mat_elastic above.
    #
    # Three alias registrations dyna2rad LACKS. (a) *MAT_001_FLUID: its
    # dynamatlawkeywordmap.h has *MAT_ELASTIC_FLUID but not the numeric
    # spelling, so the keyword misses the map, falls into the broken
    # Convert1To1 fallback and produces NO /MAT at all — the part is wired to
    # mat_ID 0 and the starter dies with ERROR 3046 (its own convertprops.cxx
    # :331 does test both spellings, so the omission is an inconsistency, not
    # intent). The LS-DYNA reader accepts it: mat_001.cfg matches the option
    # by _FIND(TYPE,"_FLUID"), and data_hierarchy.cfg:467 lists MAT_001_FLUID
    # in USER_NAMES. (b) the bare *MAT_001 / *MAT_1 numerics, which k2rad
    # previously dropped into skipped_keywords, leaving every referencing
    # /PART without a material.
    "MAT_JOHNSON_HOLMQUIST_CERAMICS":         handle_mat_jh_ceramics,
    "MAT_110":                                handle_mat_jh_ceramics,
    "MAT_JOHNSON_HOLMQUIST_CONCRETE":         handle_mat_jh_concrete,
    "MAT_111":                                handle_mat_jh_concrete,
    "MAT_ELASTIC_FLUID":                      handle_mat_elastic,
    "MAT_001_FLUID":                          handle_mat_elastic,
    "MAT_1_FLUID":                            handle_mat_elastic,
    "MAT_001":                                handle_mat_elastic,
    "MAT_1":                                  handle_mat_elastic,
    "INITIAL_FOAM_REFERENCE_GEOMETRY":        handle_initial_foam_reference_geometry,
    "INITIAL_FOAM_REFERENCE_GEOMETRY_RAMP":   handle_initial_foam_reference_geometry,
    # Discrete-element (spring/damper) materials + spotwelds → /SPRING connectors
    "MAT_SPRING_ELASTIC":                     handle_mat_spring_elastic,
    "MAT_S01":                                handle_mat_spring_elastic,
    "MAT_SPRING_NONLINEAR_ELASTIC":           handle_mat_spring_nonlinear_elastic,
    "MAT_S04":                                handle_mat_spring_nonlinear_elastic,
    "MAT_DAMPER_VISCOUS":                     handle_mat_damper_viscous,
    # *MAT_DAMPER_VISCOUS's own numeric alias is *MAT_S02 (Manual Vol II R17
    # p.2-2083 headers the card "*MAT_DAMPER_VISCOUS / *MAT_S02", and that is
    # what dyna2rad's keyword map carries). "MAT_D01"/"MAT_D02" are k2rad
    # legacy spellings that appear nowhere in the manual — kept so old decks
    # written against them still dispatch, but S02 is the one LS-DYNA writes.
    "MAT_S02":                                handle_mat_damper_viscous,
    "MAT_D01":                                handle_mat_damper_viscous,
    "MAT_SPRING_ELASTOPLASTIC":               handle_mat_spring_elastoplastic,
    "MAT_S03":                                handle_mat_spring_elastoplastic,
    "MAT_DAMPER_NONLINEAR_VISCOUS":           handle_mat_damper_nonlinear_viscous,
    "MAT_S05":                                handle_mat_damper_nonlinear_viscous,
    "MAT_D02":                                handle_mat_damper_nonlinear_viscous,
    "MAT_SPRING_GENERAL_NONLINEAR":           handle_mat_spring_general_nonlinear,
    "MAT_S06":                                handle_mat_spring_general_nonlinear,
    "MAT_SPRING_INELASTIC":                   handle_mat_spring_inelastic,
    "MAT_S08":                                handle_mat_spring_inelastic,
    # *SECTION_BEAM ELFORM=6 discrete beams → 6-DOF /PROP/TYPE8 / TYPE13 springs
    "MAT_LINEAR_ELASTIC_DISCRETE_BEAM":       handle_mat_linear_elastic_discrete_beam,
    "MAT_066":                                handle_mat_linear_elastic_discrete_beam,
    "MAT_66":                                 handle_mat_linear_elastic_discrete_beam,
    "MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM":    handle_mat_nonlinear_elastic_discrete_beam,
    "MAT_067":                                handle_mat_nonlinear_elastic_discrete_beam,
    "MAT_67":                                 handle_mat_nonlinear_elastic_discrete_beam,
    "MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM":    handle_mat_nonlinear_plastic_discrete_beam,
    "MAT_068":                                handle_mat_nonlinear_plastic_discrete_beam,
    "MAT_68":                                 handle_mat_nonlinear_plastic_discrete_beam,
    "MAT_CABLE_DISCRETE_BEAM":                handle_mat_cable_discrete_beam,
    "MAT_071":                                handle_mat_cable_discrete_beam,
    "MAT_71":                                 handle_mat_cable_discrete_beam,
    "MAT_ELASTIC_SPRING_DISCRETE_BEAM":       handle_mat_elastic_spring_discrete_beam,
    "MAT_074":                                handle_mat_elastic_spring_discrete_beam,
    "MAT_74":                                 handle_mat_elastic_spring_discrete_beam,
    "MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM": handle_mat_general_nonlinear_6dof,
    "MAT_119":                                handle_mat_general_nonlinear_6dof,
    "MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM": handle_mat_general_nonlinear_1dof,
    "MAT_121":                                handle_mat_general_nonlinear_1dof,
    "MAT_GENERAL_SPRING_DISCRETE_BEAM":       handle_mat_general_spring_discrete_beam,
    "MAT_196":                                handle_mat_general_spring_discrete_beam,
    # (the seven ELFORM=6 materials with no Radioss spring law are registered
    # from _UNSUPPORTED_DBEAM_KEYWORDS just below this dict)
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
    "DEFINE_TABLE_3D":                        handle_define_table_3d,
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
    # The *SET_<FAMILY>_ADD unions are registered below, generated from
    # state.SET_ADD_FAMILIES (the same source assembly._OFFSET_SPECS reads).
    "SET_NODE_ADD_ADVANCED":                  handle_set_node_add_advanced,
    "SET_SHELL_LIST":                         handle_set_shell_list,
    "SET_SHELL":                              handle_set_shell_list,
    "SET_SOLID_LIST":                         handle_set_solid_list,
    "SET_SOLID":                              handle_set_solid_list,
    "SET_BEAM_LIST":                          handle_set_beam_list,
    "SET_BEAM":                               handle_set_beam_list,
    "SET_DISCRETE_LIST":                      handle_set_discrete_list,
    "SET_DISCRETE":                           handle_set_discrete_list,

    # Boundary conditions
    "BOUNDARY_SPC_SET":                       handle_boundary_spc_set,
    "BOUNDARY_SPC_NODE":                      handle_boundary_spc_node,
    "BOUNDARY_SPC":                           handle_boundary_spc_node,
    # *BOUNDARY_PRESCRIBED_MOTION_{NODE|SET|SET_BOX|RIGID|RIGID_LOCAL}. The _ID
    # option needs no key of its own (parser._split_keyword strips it), but
    # _BOX and _LOCAL stay in the base name and do need one — the *DEFINE_BOX /
    # *DEFINE_BOX_LOCAL rule. Deliberately absent, so they land in
    # skipped_keywords rather than being silently read as a near-alias: the IGA
    # forms (_SET_POINT_UVW / _SET_EDGE_UVW / _SET_FACE_XYZ), _SET_LINE and
    # _SET_SEGMENT. None of them exists in the Radioss dyna-reader's cfg tree
    # either (verified by grep over hm_cfg_files), so its reader rejects them at
    # parse time as well; _SET_SEGMENT in particular carries DOF=12 (translation
    # along the segment normals), which no /IMPVEL Dir can express.
    "BOUNDARY_PRESCRIBED_MOTION_RIGID":       handle_boundary_prescribed_motion_rigid,
    "BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL": handle_boundary_prescribed_motion_rigid,
    "BOUNDARY_PRESCRIBED_MOTION_SET":         handle_boundary_prescribed_motion_set,
    "BOUNDARY_PRESCRIBED_MOTION_SET_BOX":     handle_boundary_prescribed_motion_set_box,
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

    # Constraints. The *CONSTRAINED_NODAL_RIGID_BODY option spellings are
    # GENERATED below (_cnrb_option_keywords) — the two literal keys are kept
    # here only so the family is visible in this table.
    "CONSTRAINED_NODAL_RIGID_BODY":           handle_constrained_nodal_rigid_body,
    "CONSTRAINED_NODAL_RIGID_BODY_SPC":       handle_constrained_nodal_rigid_body,
    "CONSTRAINED_INTERPOLATION":              handle_constrained_interpolation,
    "CONSTRAINED_INTERPOLATION_LOCAL":        handle_constrained_interpolation,
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

    # Rigid walls: *RIGIDWALL_PLANAR is generated below, not listed here (the
    # option order is free, so a literal list always misses spellings).

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
    # The *CONTACT_..._TIEBREAK family is generated below from
    # TIEBREAK_CONTACT_KEYWORDS — all 13 LS-DYNA spellings plus their _MPP
    # forms — so the dispatch table and assembly._OFFSET_SPECS read ONE source.
    "CONTACT_AUTOMATIC_GENERAL":              handle_contact_automatic_general,
    # *CONTACT_AIRBAG_SINGLE_SURFACE (type a13) — a near-alias of the
    # single-surface path (its card grid is column-compatible; see the
    # handler), with the SOFT = -19 sentinel routing to /INTER/TYPE19. The
    # _MPP spelling is generated below with the other contact grammars.
    "CONTACT_AIRBAG_SINGLE_SURFACE":          handle_contact_airbag_single_surface,
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
    # Spot welds → /INTER/TYPE2 Spotflag=28 (the *_SPOTWELD_* spellings are
    # generated below — see _SPOTWELD_CONTACT_KEYWORDS)
    # Eroding + node-to-surface contacts → /INTER/TYPE25 (the *_MPP spellings
    # are generated below — see _TYPE25_CONTACT_KEYWORDS)
    # Interior (foam self-) contact → Icontrol on the solid /PROP, which the
    # /BEGIN 2022 property format cannot carry (radioss2025-only column);
    # parsed and resolved so the affected parts are NAMED in the warning.
    "CONTACT_INTERIOR":                       handle_contact_interior,

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
    "CONTROL_SPH":                            handle_control_sph,
    "CONTROL_ADAPTIVE":                       handle_skip,
    "CONTROL_BULK_VISCOSITY":                 handle_skip,
    "CONTROL_DYNAMIC_RELAXATION":             handle_skip,
    "CONTROL_MPP_DECOMPOSITION":              handle_skip,
    "CONTROL_UNITS":                          handle_skip,

    # Damping
    "DAMPING_GLOBAL":                         handle_damping_global,
    "DAMPING_PART_STIFFNESS":                 handle_damping_part_stiffness,
    "DAMPING_PART_MASS":                      handle_damping_part_mass,
    "DAMPING_PART_MASS_SET":                  handle_damping_part_mass,
    "DAMPING_RELATIVE":                       handle_damping_relative,
    # *DAMPING_FREQUENCY_RANGE_{OPTION1}_{OPTION2}. parser._split_keyword only
    # strips a trailing _ID/_TITLE, so _DEFORM does NOT fall back to the base
    # key — every spelling needs its own row or it lands in skipped_keywords
    # with no warning at all (the #117 *LOAD_BODY_R* defect).
    # These THREE rows are the complete legal set: Manual Vol I R16 p.15-2
    # states "OPTION2 is available only when OPTION1 is DEFORM", so the bare
    # *DAMPING_FREQUENCY_RANGE_DMIG spelling (OPTION2 without OPTION1) does not
    # exist and is deliberately absent — a deck carrying it is malformed, and
    # skipped_keywords is the right place for it.
    "DAMPING_FREQUENCY_RANGE":                handle_damping_frequency_range,
    "DAMPING_FREQUENCY_RANGE_DEFORM":         handle_damping_frequency_range,
    "DAMPING_FREQUENCY_RANGE_DEFORM_DMIG":    handle_damping_frequency_range,

    # Database / output
    "DATABASE_BINARY_D3PLOT":                 handle_database_binary_d3plot,
    "DATABASE_ELOUT":                         handle_database_elout,
    "DATABASE_GLSTAT":                        handle_database_glstat,
    "DATABASE_HISTORY_SHELL":                 handle_database_history_shell,
    "DATABASE_HISTORY_SOLID":                 handle_database_history_solid,
    "DATABASE_HISTORY_TSHELL":                handle_database_history_tshell,
    # *DATABASE_HISTORY_SPH lists PARTICLE (= node) ids; _SPH_SET lists
    # *SET_NODE ids. Both land on /TH/SPHCEL, and both are screened against the
    # emitted /SPHCEL set before a single id is written (ERROR 69).
    "DATABASE_HISTORY_SPH":                   handle_database_history_sph,
    "DATABASE_HISTORY_SPH_SET":               handle_database_history_sph_set,
    "DATABASE_HISTORY_NODE":                  handle_database_history_node,
    # The *DATABASE_HISTORY_* family, completed. parser._split_keyword strips
    # only a trailing _ID/_TITLE, so _SET and _LOCAL are part of the BASE
    # keyword and every spelling needs its own row or it lands in
    # skipped_keywords with no warning at all (the #117 *LOAD_BODY_R* defect).
    # There is no _TITLE anywhere in this family and no _SET_ID: the R14.1/R15
    # dictionaries list exactly BEAM / BEAM_ID / BEAM_SET, DISCRETE /
    # DISCRETE_ID / DISCRETE_SET, SEATBELT / SEATBELT_ID, NODE / NODE_ID /
    # NODE_LOCAL / NODE_LOCAL_ID / NODE_SET / NODE_SET_LOCAL, and the
    # SHELL/SOLID/TSHELL/SPH triples.
    "DATABASE_HISTORY_BEAM":                  handle_database_history_beam,
    "DATABASE_HISTORY_BEAM_SET":              handle_database_history_beam_set,
    "DATABASE_HISTORY_DISCRETE":              handle_database_history_discrete,
    "DATABASE_HISTORY_DISCRETE_SET":          handle_database_history_discrete_set,
    "DATABASE_HISTORY_SEATBELT":              handle_database_history_seatbelt,
    "DATABASE_HISTORY_NODE_SET":              handle_database_history_node_set,
    "DATABASE_HISTORY_NODE_LOCAL":            handle_database_history_node_local,
    "DATABASE_HISTORY_NODE_SET_LOCAL":        handle_database_history_node_set_local,
    "DATABASE_HISTORY_SHELL_SET":             handle_database_history_shell_set,
    "DATABASE_HISTORY_SOLID_SET":             handle_database_history_solid_set,
    "DATABASE_HISTORY_TSHELL_SET":            handle_database_history_tshell_set,
    "DATABASE_ABSTAT":                        handle_database_abstat,
    "DATABASE_BINARY_D3THDT":                 handle_database_binary_d3thdt,
    "DATABASE_BINARY_INTFOR":                 handle_database_binary_intfor,
    "DATABASE_DEFORC":                        handle_database_deforc,
    "DATABASE_DISBOUT":                       handle_database_disbout,
    "DATABASE_EXTENT_BINARY":                 handle_database_extent_binary,
    "DATABASE_JNTFORC":                       handle_database_jntforc,
    "DATABASE_MATSUM":                        handle_database_matsum,
    "DATABASE_NODOUT":                        handle_database_nodout,
    "DATABASE_RCFORC":                        handle_database_rcforc,
    "DATABASE_RWFORC":                        handle_database_rwforc,
    "DATABASE_SECFORC":                       handle_database_secforc,
    "DATABASE_SLEOUT":                        handle_database_sleout,
    "DATABASE_SPHOUT":                        handle_database_sphout,
    "DATABASE_SPCFORC":                       handle_database_spcforc,
    "DATABASE_SWFORC":                        handle_database_swforc,
    "DATABASE_NCFORC":                        handle_database_ncforc,
    # *DATABASE_RBDOUT was an explicit handle_skip row while handlers.py:1568
    # already told users it "maps to /TH/RBODY". The claim is now true.
    "DATABASE_RBDOUT":                        handle_database_rbdout,
    "DATABASE_BNDOUT":                        handle_database_bndout,
    "DATABASE_NODFOR":                        handle_database_nodfor,
    "DATABASE_TPRINT":                        handle_database_tprint,
    "DATABASE_NODAL_FORCE_GROUP":             handle_database_nodal_force_group,
    "CONTROL_PARALLEL":                       handle_control_parallel,
    "DATABASE_BINARY_D3DRLF":                handle_skip,
    "DATABASE_BINARY_D3DUMP":                 handle_skip,
    "DATABASE_BINARY_BLSTFOR":                handle_database_binary_blstfor,
    "DATABASE_CROSS_SECTION_PLANE":           handle_database_cross_section_plane,
    "DATABASE_CROSS_SECTION_SET":             handle_database_cross_section_set,
    "DATABASE_BINARY_RUNRSF":                 handle_skip,
    "DATABASE_FREQUENCY_BINARY_D3PSD":        handle_database_frequency_binary_d3psd,
    "DATABASE_FREQUENCY_BINARY_D3RMS":        handle_database_frequency_binary_d3rms,
    "DATABASE_FREQUENCY_BINARY_D3FTG":        handle_database_frequency_binary_d3ftg,
    "LOAD_GRAVITY_PART":                      handle_load_gravity_part,
    "LOAD_GRAVITY_PART_SET":                  handle_load_gravity_part,
    "LOAD_RIGID_BODY":                        handle_load_rigid_body,
    "LOAD_SEGMENT":                           handle_load_segment,
    "LOAD_SEGMENT_ID":                        handle_load_segment,
    "LOAD_SEGMENT_SET":                       handle_load_segment_set,
    "LOAD_SEGMENT_SET_ID":                    handle_load_segment_set,
    "LOAD_NODE_POINT":                        handle_load_node,
    "LOAD_NODE_SET":                          handle_load_node,
    "LOAD_SHELL_ELEMENT":                     handle_load_shell,
    "LOAD_SHELL_SET":                         handle_load_shell,
    # *LOAD_BODY_{X,Y,Z} -> /GRAV, _VECTOR -> /GRAV + /SKEW/FIX,
    # _RX/_RY/_RZ -> /LOAD/CENTRI + /FRAME/FIX, _GENERALIZED -> explicit
    # warn-skip. They share one handler because card 1a.1 has the same column
    # grid; _GENERALIZED is registered ON PURPOSE so the skip is reported with
    # its reason instead of arriving as a mute skipped_keywords entry (the
    # handler's docstring used to claim that and was not true). The manual's
    # spelling is *LOAD_BODY_GENERALIZED_OPTION with OPTION in {SET_NODE,
    # SET_PART} (p.33-31 + the keyword index on p.33-1), so all THREE forms are
    # registered — a real deck names one of the two option forms, and those were
    # the spellings still arriving mute.
    "LOAD_BODY_X":                            handle_load_body,
    "LOAD_BODY_Y":                            handle_load_body,
    "LOAD_BODY_Z":                            handle_load_body,
    "LOAD_BODY_RX":                           handle_load_body,
    "LOAD_BODY_RY":                           handle_load_body,
    "LOAD_BODY_RZ":                           handle_load_body,
    "LOAD_BODY_VECTOR":                       handle_load_body,
    "LOAD_BODY_GENERALIZED":                  handle_load_body,
    "LOAD_BODY_GENERALIZED_SET_NODE":         handle_load_body,
    "LOAD_BODY_GENERALIZED_SET_PART":         handle_load_body,
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


# *PART_{OPTION1..6} — 3588 legal spellings, since "Options 1, 2, 3, 4, 5, and 6
# may be specified in any order on the *PART card" (Vol I R17 p.37-2). Registered
# from the generator so a legal ordering can never miss the exact-match lookup:
# without a key the whole block lands in skipped_keywords, the part is never
# registered, and _make_parts_and_elements — which emits elements INSIDE the
# state.parts loop — drops every element on it. Measured on a one-solid
# *PART_INERTIA deck before this batch: "SKIPPED: ['PART_INERTIA']" plus a MESH
# LOSS warning for the orphaned brick, and no /PART/1 in the starter at all.
for _kw in _part_option_keywords():
    HANDLERS[_kw] = handle_part
del _kw

# *SET_<FAMILY>_ADD — one dispatch key per family, GENERATED from
# state.SET_ADD_FAMILIES so the parser table, the writer's resolver and
# assembly._OFFSET_SPECS all read the same source. Each family closes over its
# OWN card-1 cell count and its OWN container; a hand-written per-family copy
# is exactly how a guard goes dead on a sibling spelling.
for _family, _kw, _ncells, _adds, _target in SET_ADD_FAMILIES:
    HANDLERS[_kw] = (lambda fam, nc, ad:
                     lambda b, s: _handle_set_add(b, s, fam, nc, ad))(
        _family, _ncells, _adds)
del _family, _kw, _ncells, _adds, _target

# *CONSTRAINED_NODAL_RIGID_BODY_{SPC,INERTIA,OVERRIDE,THERMAL,TITLE} in any order
# — 326 spellings ("The order of the options in the keyword name is arbitrary",
# p.10-146, of a list that includes TITLE). A missing key here is worse than for
# *PART: a CNRB owns no elements, so nothing downstream notices the loss and the
# rigid body simply is not in the model. Measured before TITLE joined the
# permutation: *..._INERTIA_TITLE gave /RBODY Mass 7.25, *..._TITLE_INERTIA gave
# SKIPPED and no rigid body.
for _kw, _cnrb_opts in _cnrb_option_keywords():
    HANDLERS[_kw] = handle_constrained_nodal_rigid_body
del _kw, _cnrb_opts


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

# *ELEMENT_TSHELL_{OPTION} with OPTION in {<blank>, BETA, COMPOSITE} — the
# manual defines ONE option slot, not a stacking (Vol I R16 p.2703), so three
# spellings. Generated for the same reason as the shell/beam grammars above,
# and the prefix fallback in dispatch() covers anything outside it.
for _o1 in ("", "_BETA", "_COMPOSITE"):
    HANDLERS[f"ELEMENT_TSHELL{_o1}"] = handle_element_tshell
del _o1

# *ELEMENT_SPH_{OPTION} with OPTION in {<blank>, VOLUME} — one option slot, two
# spellings, and the option is not cosmetic: it makes the MASS column a VOLUME.
# *SECTION_SPH_{OPTION} with OPTION in {<blank>, ELLIPSE, TENSOR, INTERACTION,
# USER} — the pre-R8 name TENSOR is kept alongside ELLIPSE because old decks
# still spell it that way and it selects the same anisotropic card 2.
for _o1 in ("", "_VOLUME"):
    HANDLERS[f"ELEMENT_SPH{_o1}"] = handle_element_sph
for _o1 in ("",) + tuple(f"_{o}" for o in _SPH_SECTION_OPTIONS):
    HANDLERS[f"SECTION_SPH{_o1}"] = handle_section_sph
del _o1


# *CONTACT_SPOTWELD{_WITH_TORSION|_BEAM_OFFSET|_CONSTRAINED_OFFSET}{_PENALTY}
# {_MPP}{_ID} — the suffixes appear in that fixed order (contact_spotweld.cfg
# HEADER("*CONTACT_SPOTWELD%40s") + the _FIND() tests at :827-856; _ID and
# _TITLE are stripped by the parser, so they need no key). Sixteen spellings.
#
# Hand-listing the five USER_NAMES the CFG advertises would leave a
# *CONTACT_SPOTWELD_MPP in skipped_keywords, and a skipped spotweld contact is
# the whole point of this batch: the weld elements then reach the solver joined
# to nothing and carry zero force. Generating the grammar makes that
# impossible, and the handler warns on every flavour it cannot honour.
_SPOTWELD_CONTACT_KEYWORDS = [
    f"CONTACT_SPOTWELD{_o1}{_o2}{_o3}"
    for _o1 in ("", "_WITH_TORSION", "_BEAM_OFFSET", "_CONSTRAINED_OFFSET")
    for _o2 in ("", "_PENALTY")
    for _o3 in ("", "_MPP")
]
for _kw in _SPOTWELD_CONTACT_KEYWORDS:
    HANDLERS[_kw] = handle_contact_spotweld
del _kw

# *CONTACT_ERODING_{SINGLE_SURFACE|SURFACE_TO_SURFACE|NODES_TO_SURFACE}{_MPP}
# and *CONTACT_{<blank>|AUTOMATIC_}NODES_TO_SURFACE{_MPP} — ten spellings
# (_ID/_TITLE are stripped by the parser, so they need no key of their own).
#
# Generated rather than hand-listed for the reason the spotweld grammar is:
# dispatch() is an exact dict lookup with no CONTACT_ prefix fallback, so a
# missing spelling lands in skipped_keywords — and a skipped *CONTACT is not a
# missing output card, it is a missing LOAD PATH. The _MPP flavours matter here
# in particular because the two eroding families in the reference corpus (W9
# missile, W11 bird strike) are impact decks, which is exactly where an MPP
# deck is likely to come from.
_TYPE25_CONTACT_KEYWORDS = [
    f"{_base}{_mpp}"
    for _base in _TYPE25_CONTACT_BASES
    for _mpp in ("", "_MPP")
]
for _kw in _TYPE25_CONTACT_KEYWORDS:
    HANDLERS[_kw] = handle_contact_type25
del _kw

# *CONTACT_..._TIEBREAK — the whole family from TIEBREAK_CONTACT_KEYWORDS
# (_TIEBREAK_BASES x _TIEBREAK_SUFFIXES x {"", "_MPP"}), 26 spellings against
# the four the pre-#131 table listed by hand. The missing ones were not
# academic: *CONTACT_TIEBREAK_NODES_ONLY is in the reference corpus
# (dynaexamples_r14 intro-by-k.-weimar/spotweld/spotweld-iv/plates.tied.k) and
# landed in skipped_keywords with NO warning at all — the only joint between
# the two plates vanished silently.
for _kw in TIEBREAK_CONTACT_KEYWORDS:
    HANDLERS[_kw] = handle_contact_tiebreak
del _kw

HANDLERS["CONTACT_AIRBAG_SINGLE_SURFACE_MPP"] = (
    handle_contact_airbag_single_surface)

HANDLERS["DEFINE_FRICTION"] = handle_define_friction

# ── *AIRBAG_* → /MONVOL ──────────────────────────────────────────────────────
#
# Generated from the SAME dicts the handler routes on (#116), so a model
# cannot be readable by the writer and unreachable by the dispatcher. _ID and
# _TITLE are stripped by parser._split_keyword and need no key; the WANG_NEFSKE
# family's _POP / _JETTING suffixes DO need one each, because dispatch() is an
# exact lookup — an unregistered spelling lands in skipped_keywords with no
# warning, and a skipped airbag is a bag that never inflates while the run
# terminates normally.
#: The LEGACY numeric suffix, generated onto every airbag spelling for the same
#: reason the _MPP contact flavours are: MEASURED over the r14 dynaexamples
#: corpus, 16 of the 28 *AIRBAG_* occurrences are spelled
#: ``*AIRBAG_SIMPLE_PRESSURE_VOLUME_1`` / ``*AIRBAG_SIMPLE_AIRBAG_MODEL_1``, and
#: without a key each of them is a bag that never inflates on a run that
#: terminates normally. ``_airbag_base_keyword`` strips it back off inside the
#: handler, so the card stack is read as the base model's — which it is.
_AIRBAG_LEGACY_SUFFIXES = ("", "_1", "_2", "_3", "_4")
for _kw in _AIRBAG_MODELS:
    for _sfx in _AIRBAG_LEGACY_SUFFIXES:
        HANDLERS[_kw + _sfx] = handle_airbag
for _kw in _AIRBAG_UNSUPPORTED:
    for _sfx in _AIRBAG_LEGACY_SUFFIXES:
        HANDLERS[_kw + _sfx] = handle_airbag_unsupported
for _o1 in ("", "_JETTING", "_MULTIPLE_JETTING"):
    for _o2 in ("", "_POP"):
        for _sfx in _AIRBAG_LEGACY_SUFFIXES:
            HANDLERS[f"AIRBAG_WANG_NEFSKE{_o1}{_o2}{_sfx}"] = \
                handle_airbag_unsupported
# The batch-2 OPTION stacks, from the SAME dict `_airbag_base_keyword` resolves
# them with, so a spelling cannot be dispatchable and unreadable (or the other
# way round). One product per model, every combination, every legacy suffix.
for _kw, _stack in _AIRBAG_OPTION_STACKS.items():
    for _combo in _product(*_stack):
        for _sfx in _AIRBAG_LEGACY_SUFFIXES:
            HANDLERS[_kw + "".join(_combo) + _sfx] = handle_airbag
HANDLERS["AIRBAG_INTERACTION"] = handle_airbag_interaction
for _sfx in _AIRBAG_LEGACY_SUFFIXES:
    HANDLERS["AIRBAG_INTERACTION" + _sfx] = handle_airbag_interaction
del _kw, _o1, _o2, _sfx, _stack, _combo

# The *DEFINE_CPM_* side cards of *AIRBAG_PARTICLE. Registered on a warn-drop
# for the same reason as the unmodelled *AIRBAG_* models above: an extended
# CPM input that lands in the generic skipped-keyword list is a vent option, a
# chamber or a gas property that quietly stops applying on a deck that still
# converts and still terminates normally. NOT in `_OFFSET_SPECS` — an
# unmodelled card stack must not have its cells rewritten by position, the
# same rule *AIRBAG_HYBRID_CHEMKIN follows. `parser._split_keyword` strips a
# trailing _ID/_TITLE, so those spellings reach the same six keys.
for _kw in _DEFINE_CPM_UNSUPPORTED:
    HANDLERS[_kw] = handle_define_cpm_unsupported
del _kw

# ── Seatbelts / restraints ───────────────────────────────────────────────────
#
# Generated from the SAME dicts assembly._OFFSET_SPECS is generated from (#116),
# so a spelling cannot be readable by the handler and invisible to the
# *INCLUDE_TRANSFORM offsetter. Registered EXACTLY, with no prefix row in
# _PREFIX_HANDLERS: a bare startswith("ELEMENT_SEATBELT") would route
# *ELEMENT_SEATBELT_SLIPRING into the belt-element reader, whose field 3 is a
# node and whose field 3 there is a friction coefficient.
#
# A skipped seatbelt keyword is the worst of the three loss channels: it is not
# a missing output card, it is a missing RESTRAINT — the occupant is unbelted
# and the run terminates normally, looking healthy.
for _sfx, _h in _SEATBELT_SUBKEYWORDS.items():
    HANDLERS["ELEMENT_SEATBELT" + _sfx] = _h
for _kw in _SEATBELT_MAT_KEYWORDS:
    HANDLERS[_kw] = handle_mat_seatbelt
HANDLERS["SECTION_SEATBELT"] = handle_section_seatbelt
HANDLERS["DATABASE_SBTOUT"] = handle_database_sbtout
del _sfx, _h, _kw

# *AIRBAG_REFERENCE_GEOMETRY{_BIRTH}{_RDT}{_ID} and
# *AIRBAG_SHELL_REFERENCE_GEOMETRY{_RDT}{_ID}. "The order of the options in
# the keyword name is arbitrary" for this family too, so every permutation is
# generated rather than the documented order alone — and a TRAILING _ID is
# skipped, because parser._split_keyword already moves it into block.options
# (where _has_id finds it and the ID card is still read).
for _r in range(4):
    for _combo in _permutations(("_BIRTH", "_RDT", "_ID"), _r):
        if _combo and _combo[-1] == "_ID":
            continue
        HANDLERS["AIRBAG_REFERENCE_GEOMETRY" + "".join(_combo)] = \
            handle_airbag_reference_geometry
for _r in range(3):
    for _combo in _permutations(("_RDT", "_ID"), _r):
        if _combo and _combo[-1] == "_ID":
            continue
        HANDLERS["AIRBAG_SHELL_REFERENCE_GEOMETRY" + "".join(_combo)] = \
            handle_airbag_shell_reference_geometry
del _r, _combo

# *MAT_SIMPLIFIED_RUBBER/FOAM{_WITH_FAILURE}{_LOG_LOG_INTERPOLATION} and
# *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE{_LOG_LOG_INTERPOLATION}, over every base
# spelling LS-DYNA and dyna2rad accept for each (the literal "/" survives
# _split_keyword, which only splits on "_"). _WITH_FAILURE is not cosmetic — it
# inserts a whole card between card 2 and the optional unloading card, so a
# missing key would not just skip the material, it would shift the parse of
# every deck that uses it. Generated rather than hand-listed: 3 base spellings
# x 2 x 2 + 2 x 2 = 16 keys.
for _base in ("MAT_SIMPLIFIED_RUBBER/FOAM", "MAT_SIMPLIFIED_RUBBER",
              "MAT_SIMPLIFIED_RUBBER_FOAM", "MAT_181"):
    for _o1 in ("", "_WITH_FAILURE"):
        for _o2 in ("", "_LOG_LOG_INTERPOLATION"):
            HANDLERS[f"{_base}{_o1}{_o2}"] = handle_mat_simplified_rubber
for _base in ("MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE", "MAT_183"):
    for _o2 in ("", "_LOG_LOG_INTERPOLATION"):
        HANDLERS[f"{_base}{_o2}"] = handle_mat_simplified_rubber
del _base, _o1, _o2

# *MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_{OPTION} — the legal option
# spellings are <blank>, THERMAL, 3MODES, FUNCTIONS, THERMAL_3MODES and
# FUNCTIONS_3MODES (R16 Vol II; THERMAL_FUNCTIONS is NOT a legal combination).
# All land on the same handler, which converts the option-free card and
# warn-skips the variants (their fields are curve ids / mode-III data with no
# /MAT/LAW116 slot). Registering the variant spellings matters beyond the
# message: an unregistered one would fall into skipped_keywords and the part
# would silently lose its material with only the generic skip note.
for _base in ("MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE", "MAT_240"):
    for _opt in ("", "_THERMAL", "_3MODES", "_FUNCTIONS", "_THERMAL_3MODES",
                 "_FUNCTIONS_3MODES"):
        HANDLERS[f"{_base}{_opt}"] = handle_mat_cohesive_mm_epr
del _base, _opt

#: The PRELOAD / INITIAL-STATE batch, as ONE source for HANDLERS and for
#: assembly._OFFSET_SPECS (#116: a spelling readable by the handler and
#: invisible to the *INCLUDE_TRANSFORM offsetter keeps its original ids while
#: the rest of the include moves — a dangling CSID/LCID/BSID at 0 diagnostics).
#: Trailing ``_TITLE`` is NOT listed: parser._split_keyword moves it into
#: block.options, where _title_offset finds it. ``_SET`` is a real base
#: keyword (its EID cell is a *SET_SHELL id, i.e. a different offset bucket),
#: so it is listed in full.
INITIAL_STATE_PRELOAD_KEYWORDS = {
    "INITIAL_STRESS_SECTION":   handle_initial_stress_section,
    "INITIAL_AXIAL_FORCE_BEAM": handle_initial_axial_force_beam,
    "INITIAL_STRAIN_SHELL":     handle_initial_strain_shell,
    "INITIAL_STRAIN_SHELL_SET": handle_initial_strain_shell,
    # Moved here from the bare HANDLERS table by the SIDE-DEFECT batch. They
    # were readable and un-offsettable: registered directly, so
    # ``_OFFSET_SPECS.get("INITIAL_STRESS_SHELL")`` was None and an
    # *INCLUDE_TRANSFORM left their EIDs at the child deck's original numbers
    # while the mesh around them moved by IDEOFF. MEASURED on a parent/child
    # pair (IDEOFF 6000, IDPOFF 7000): one stress record landed on the PARENT
    # deck's shell 1 — a different part, a different thickness, a different
    # place — and the other two dangled, under the generic "keyword has no
    # offset map" warning. Registering them HERE is what makes that
    # impossible: the loop in assembly.py keys the offset table off this dict,
    # so a spelling added without a spec is an ImportError, not a silent
    # un-offset include (#116).
    "INITIAL_STRESS_SHELL":     handle_initial_stress_shell,
    "INITIAL_STRESS_SOLID":     handle_initial_stress_solid,
}
for _kw, _h in INITIAL_STATE_PRELOAD_KEYWORDS.items():
    HANDLERS[_kw] = _h
del _kw, _h

#: The RARE MATERIALS batch, as ONE source for HANDLERS and for
#: assembly._OFFSET_SPECS (#116: a spelling the handler reads and the
#: *INCLUDE_TRANSFORM offsetter does not know keeps its original ids while the
#: rest of the include moves — a dangling MID/LCID at 0 diagnostics).
#: Trailing ``_TITLE`` / ``_ID`` are NOT listed: parser._split_keyword moves
#: them into block.options, where _title_offset finds them. Every numbered
#: material carries both the zero-padded and the unpadded alias, the convention
#: the rest of this table follows.
RARE_MATERIAL_KEYWORDS = {
    "MAT_SHAPE_MEMORY":   handle_mat_shape_memory,
    "MAT_030":            handle_mat_shape_memory,
    "MAT_30":             handle_mat_shape_memory,
    # ── R14 triage batch, round 1 ──────────────────────────────────────────
    # The two temperature-dependent elasto-plastic laws behind 13 of the 29
    # ERROR-179 decks. Both land on /MAT/LAW106, the only law available at
    # /BEGIN 2022 that carries E(T) and nu(T) as plain functions of
    # temperature (LAW129, the exact target, first appears in radioss2025).
    "MAT_ELASTIC_PLASTIC_THERMAL": handle_mat_elastic_plastic_thermal,
    "MAT_004":                     handle_mat_elastic_plastic_thermal,
    "MAT_4":                       handle_mat_elastic_plastic_thermal,
    "MAT_CWM":                     handle_mat_cwm,
    "MAT_270":                     handle_mat_cwm,
    # *MAT_010 -> /MAT/LAW3 (HYDPLA) + the same-id /EOS. The _SPALL option is
    # NOT a trailing _ID/_TITLE, so parser._split_keyword leaves it in the
    # keyword: the spelling is its own row, and the handler reads the flag off
    # block.keyword (its card 1a shifts the EPS/ES table by one row).
    # Refused BY NAME (recognized, no /MAT): three families of the R14
    # ERROR-179 census whose law has no Radioss counterpart at /BEGIN 2022.
    # Generated from ONE table so the canonical name and its numeric alias can
    # never be diagnosed differently (the _MAT_THERMAL_ALIASES rule).
    **{kw: _material_refused(names[0], what, why)
       for names, (what, why) in _REFUSED_MATERIALS.items() for kw in names},
    # *MAT_140 -> /MAT/VOID so the vacuum *PART resolves; the /MAT/LAW51
    # phase list drops it (LAW0 is not on fill_buffer_51.F:210's list, and
    # Radioss's void is the UNDECLARED BALANCE of the volume fractions).
    "MAT_VACUUM":                      handle_mat_vacuum,
    "MAT_140":                         handle_mat_vacuum,
    "MAT_ELASTIC_PLASTIC_HYDRO":       handle_mat_elastic_plastic_hydro,
    "MAT_ELASTIC_PLASTIC_HYDRO_SPALL": handle_mat_elastic_plastic_hydro,
    "MAT_010":                         handle_mat_elastic_plastic_hydro,
    "MAT_10":                          handle_mat_elastic_plastic_hydro,
    "MAT_010_SPALL":                   handle_mat_elastic_plastic_hydro,
    "MAT_10_SPALL":                    handle_mat_elastic_plastic_hydro,
    "MAT_MUSCLE":         handle_mat_muscle,
    "MAT_156":            handle_mat_muscle,
    # *MAT_SPRING_MUSCLE's numeric alias is *MAT_S15 (Vol II R17 p.2-2095
    # headers the card "*MAT_SPRING_MUSCLE / *MAT_S15"); the Sxx spelling is
    # the only numeric one the manual gives for the discrete-spring family,
    # like the *MAT_S01..S08 rows above.
    "MAT_SPRING_MUSCLE":  handle_mat_spring_muscle,
    "MAT_S15":            handle_mat_spring_muscle,
    # ── Thermal expansion + the minimal temperature-driver foothold ────────
    # *MAT_ADD_THERMAL_EXPANSION has no _SET spelling in any Keyword971* cfg
    # folder and none in the manual — the card's own field 1 carries the
    # part-vs-material selection through its SIGN.
    "MAT_ADD_THERMAL_EXPANSION": handle_mat_add_thermal_expansion,
    "MAT_THERMAL_ISOTROPIC":     handle_mat_thermal_isotropic,
    "INITIAL_TEMPERATURE_SET":   handle_initial_temperature,
    "INITIAL_TEMPERATURE_NODE":  handle_initial_temperature,
    "BOUNDARY_TEMPERATURE_SET":  handle_boundary_temperature,
    "BOUNDARY_TEMPERATURE_NODE": handle_boundary_temperature,
    "LOAD_THERMAL_CONSTANT":      handle_load_thermal,
    "LOAD_THERMAL_CONSTANT_NODE": handle_load_thermal,
    "LOAD_THERMAL_LOAD_CURVE":    handle_load_thermal,
    "LOAD_THERMAL_VARIABLE":      handle_load_thermal,
    "LOAD_THERMAL_VARIABLE_NODE": handle_load_thermal,
    "CONTROL_SOLUTION":           handle_control_solution,
    # ── THERMAL SOLVER batch ───────────────────────────────────────────────
    # The three heat-source boundary conditions. OPTION is MANDATORY on all
    # three (Vol I R17 pp.5-46/5-30/5-109 head them
    # *BOUNDARY_FLUX_OPTION / *BOUNDARY_CONVECTION_OPTION /
    # *BOUNDARY_RADIATION_OPTION1_{OPTION2}_{OPTION3}), so _SEGMENT is as real
    # a spelling as _SET — and it was the one MISSING: a probe deck carrying
    # *BOUNDARY_FLUX_SEGMENT came out as "Skipped (unsupported) keywords" on
    # master. The bare spellings are kept because they cost nothing and the
    # registry already carried them.
    "BOUNDARY_FLUX_SEGMENT":       handle_boundary_thermal_bc,
    "BOUNDARY_FLUX_SET":           handle_boundary_thermal_bc,
    "BOUNDARY_FLUX":               handle_boundary_thermal_bc,
    "BOUNDARY_CONVECTION_SEGMENT": handle_boundary_thermal_bc,
    "BOUNDARY_CONVECTION_SET":     handle_boundary_thermal_bc,
    "BOUNDARY_CONVECTION":         handle_boundary_thermal_bc,
    "BOUNDARY_RADIATION_SEGMENT":  handle_boundary_thermal_bc,
    "BOUNDARY_RADIATION_SET":      handle_boundary_thermal_bc,
    "BOUNDARY_RADIATION":          handle_boundary_thermal_bc,
    "CONTROL_THERMAL_SOLVER":      handle_control_thermal_solver,
    "CONTROL_THERMAL_TIMESTEP":    handle_control_thermal_timestep,
    "CONTROL_THERMAL_NONLINEAR":   handle_control_thermal_nonlinear,
    "MAT_THERMAL_ORTHOTROPIC":     handle_mat_thermal_orthotropic,
    "MAT_THERMAL_ISOTROPIC_TD":    handle_mat_thermal_isotropic_td,
    "MAT_THERMAL_ISOTROPIC_TD_LC": handle_mat_thermal_isotropic_td,
    # The *MAT_T## numeric aliases are NOT written out here: they are generated
    # from _MAT_THERMAL_ALIASES below, one row per canonical name, so an alias
    # can never end up less well diagnosed than the name it aliases (the
    # MISTAKES.md "suffix/option-order combinatorics ... hand-kept lookup
    # tables drift" rule). Hand-listing them had already gone wrong: *MAT_T07
    # landed in the generic "Skipped (unsupported) keywords" list while its
    # exact synonym *MAT_THERMAL_CWM, registered two screens away, got a named
    # drop.
    # The FOUR mandatory _OPTION suffixes of each element-temperature keyword
    # (Vol I R17 p.33-162 lists CONSTANT_ELEMENT_OPTION and
    # VARIABLE_ELEMENT_OPTION; p.33-168 / p.33-184 give OPTION = BEAM, SHELL,
    # SOLID, TSHELL). These were EIGHT dead spellings: the registry carried the
    # bare forms only, and a real deck never writes those.
    "LOAD_THERMAL_CONSTANT_ELEMENT":        handle_load_thermal_element,
    "LOAD_THERMAL_CONSTANT_ELEMENT_BEAM":   handle_load_thermal_element,
    "LOAD_THERMAL_CONSTANT_ELEMENT_SHELL":  handle_load_thermal_element,
    "LOAD_THERMAL_CONSTANT_ELEMENT_SOLID":  handle_load_thermal_element,
    "LOAD_THERMAL_CONSTANT_ELEMENT_TSHELL": handle_load_thermal_element,
    "LOAD_THERMAL_VARIABLE_ELEMENT":        handle_load_thermal_element,
    "LOAD_THERMAL_VARIABLE_ELEMENT_BEAM":   handle_load_thermal_element,
    "LOAD_THERMAL_VARIABLE_ELEMENT_SHELL":  handle_load_thermal_element,
    "LOAD_THERMAL_VARIABLE_ELEMENT_SOLID":  handle_load_thermal_element,
    "LOAD_THERMAL_VARIABLE_ELEMENT_TSHELL": handle_load_thermal_element,
    # *SECTION_SHELL_THERMAL: the option adds exactly ONE extra card per card
    # set (Vol I R17 p.41-62/63) carrying the section's own TMID, and
    # handle_section_shell's card-set walk ALREADY strides it
    # (_SECTION_SHELL_OPTION_CARDS). Registering the spelling is all that turns
    # it from a skipped keyword — which loses the whole /PROP/SHELL, i.e. the
    # thickness, and earns one ERROR 495 "SHELL HAS A NULL THICKNESS" per
    # element — into a parse.
    "SECTION_SHELL_THERMAL":      handle_section_shell,
    # ── Recognized + named warn-drop: NO Radioss counterpart exists ─────────
    # *CONTROL_THERMAL_FORMING is a SHORTHAND for the four cards above plus a
    # block of contact thermal properties (Vol I R17 p.12-567 prints the
    # equivalence explicitly), so a deck can configure the thermal solver
    # through it WITHOUT a *CONTROL_THERMAL_SOLVER. The two cells that would
    # map (TSF, FWORK) are on its card 1, but the keyword also carries the
    # per-contact-pair thermal cards 2.1/2.2 that k2rad has no target for at
    # all, and reading half a card set would make the log claim a conversion it
    # did not do. Named, whole.
    "CONTROL_THERMAL_FORMING": _thermal_deferred(
        "CONTROL_THERMAL_FORMING",
        "the hot-stamping thermal shorthand (ITS, PTYPE, TSF, THSHEL, ITHOFF, "
        "SOLVER, FWORK plus a default set of per-contact-pair thermal and "
        "friction properties, Vol I R17 pp.12-561..570)",
        "Radioss has no thermal CONTACT conductance model at all — the "
        "/INTER/TYPE7 family carries no interface conductivity, gap-dependent "
        "h or contact heat-generation cells — so the keyword's own point (one "
        "card configuring every die/blank pair) has no target. State "
        "*CONTROL_THERMAL_SOLVER instead if only its TSF/FWORK cells are "
        "wanted: k2rad converts those two"),
    "CONTROL_THERMAL_EIGENVALUE": _thermal_deferred(
        "CONTROL_THERMAL_EIGENVALUE",
        "a thermal EIGENVALUE analysis (the decay modes of the conduction "
        "operator)",
        "no Radioss counterpart: there is no thermal stiffness matrix to "
        "extract eigenvalues from — tempur.F:48-55 integrates the temperature "
        "explicitly on a lumped capacity, and the engine's own structural "
        "eigensolver is a compiled-out stub on this build"),
    "MAT_THERMAL_CWM": _thermal_deferred(
        "MAT_THERMAL_CWM",
        "a computational-welding-mechanics thermal material: quiet/dead/live "
        "property pairs interpolated by a phase fraction gamma(T_max) with an "
        "element BIRTH time (Vol II R17 pp.3-25..3-27)",
        "no Radioss counterpart at all — /HEAT/MAT holds ONE (T0, RHO0_CP, "
        "AS, BS, T1, AL, BL) set with no birth, no ghost properties and no "
        "history of the peak temperature (re-verified against "
        "hm_read_therm.F:157-166, which reads exactly those nine cells)"),
    "LOAD_THERMAL_D3PLOT": _thermal_deferred(
        "LOAD_THERMAL_D3PLOT",
        "nodal temperatures read from an external d3plot file, named by "
        "T = tpf on the execution line (Vol I R17 p.33-170)",
        "no Radioss counterpart: /IMPTEMP and /INITEMP take a /FUNCT and a "
        "/GRNOD, and no Radioss card reads a result database as a load"),
    # The remaining REAL *LOAD_THERMAL_* spellings of Vol I R17 p.33-162, which
    # lists BINOUT, CONSTANT, CONSTANT_ELEMENT_OPTION, CONSTANT_NODE, D3PLOT,
    # LOAD_CURVE, RSW, TOPAZ, VARIABLE, VARIABLE_ELEMENT_OPTION, VARIABLE_NODE
    # and VARIABLE_SHELL_OPTION — there is no *LOAD_THERMAL_DYNAIN. Note the
    # page's list is itself incomplete: *LOAD_THERMAL_VARIABLE_BEAM has its own
    # section at p.33-181 and appears in neither that OPTION list nor the
    # load-type table, a manual self-contradiction. Both it and
    # *LOAD_THERMAL_VARIABLE_SHELL take a {<BLANK>|SET} suffix.
    "LOAD_THERMAL_RSW": _thermal_deferred(
        "LOAD_THERMAL_RSW",
        "a resistance-spot-weld nugget temperature history, positioned by an "
        "orientation vector and grown over an ellipsoidal region",
        "no Radioss counterpart — /IMPTEMP drives a node GROUP with no "
        "geometric nugget model"),
    "LOAD_THERMAL_TOPAZ": _thermal_deferred(
        "LOAD_THERMAL_TOPAZ",
        "nodal temperatures read in from the TOPAZ3D database (Vol I R17 "
        "p.33-178)",
        "no Radioss counterpart: no Radioss card reads an external thermal "
        "database as a nodal load"),
    "LOAD_THERMAL_VARIABLE_BEAM": _thermal_deferred(
        "LOAD_THERMAL_VARIABLE_BEAM",
        "a temperature history stated per CROSS-SECTION POINT of a "
        "Hughes-Liu beam — card 1 'ID EID/SID IPOLAR' then a list of "
        "'TBASE TSCALE TCURVE TCURDR SCOOR TCOOR' rows at normalised section "
        "coordinates, interpolated to the integration points (Vol I R17 "
        "pp.33-181..183)",
        "no Radioss counterpart: the whole point of the card is the "
        "cross-section GRADIENT, and /IMPTEMP writes ONE temperature per node "
        "(fixtemp.F:196-205) — there is no per-integration-point temperature "
        "anywhere in Radioss. Converting the section MEAN would silently "
        "discard the gradient that is the card's only content"),
    "LOAD_THERMAL_VARIABLE_BEAM_SET": _thermal_deferred(
        "LOAD_THERMAL_VARIABLE_BEAM_SET",
        "the beam-SET spelling of the per-cross-section-point temperature "
        "history (card 1 field 2 is a *SET_BEAM id, Vol I R17 p.33-181)",
        "no Radioss counterpart, for the same reason as the bare spelling: "
        "/IMPTEMP carries no cross-section gradient"),
    "LOAD_THERMAL_VARIABLE_SHELL": _thermal_deferred(
        "LOAD_THERMAL_VARIABLE_SHELL",
        "a temperature history stated per THROUGH-THICKNESS point of a shell "
        "— card 1 'ID EID/SID' then a list of "
        "'TBASE TSCALE TCURVE TCURDR ZCO' rows at ZCO in [-1, +1], linearly "
        "interpolated between them (Vol I R17 pp.33-186/187)",
        "no Radioss counterpart: /IMPTEMP writes ONE temperature per node and "
        "carries no through-thickness gradient, and Radioss has no per-layer "
        "temperature field to write one into"),
    "LOAD_THERMAL_VARIABLE_SHELL_SET": _thermal_deferred(
        "LOAD_THERMAL_VARIABLE_SHELL_SET",
        "the shell-SET spelling of the per-through-thickness-point "
        "temperature history (card 1 field 2 is a *SET_SHELL id, Vol I R17 "
        "p.33-186)",
        "no Radioss counterpart, for the same reason as the bare spelling: "
        "/IMPTEMP carries no through-thickness gradient"),
    "LOAD_THERMAL_BINOUT": _thermal_deferred(
        "LOAD_THERMAL_BINOUT",
        "nodal temperatures read back from a previous run's binout (DEFTEMP "
        "plus a list of FILENAME / 'STARTT TSF TMPOFF NIDOFF' rows naming the "
        "LSDA TPRINT sections, Vol I R17 pp.33-164/165)",
        "no Radioss counterpart: no Radioss card reads a result database as a "
        "nodal load"),
    # ── *BOUNDARY_RADIATION view-factor spellings ───────────────────────────
    # OPTION1 x OPTION2 x OPTION3 (Vol I R17 p.5-110 lists the seven concrete
    # spellings). Every one that is not the bare environment form exchanges
    # heat between SURFACES through view factors, which nothing in
    # engine/source/constraints/thermic can express.
    **{
        _kw: _thermal_deferred(
            _kw,
            "a VIEW-FACTOR radiation surface (TYPE=2, "
            + ("read from the 'viewfl' file" if "READ" in _kw else
               "with the view factors computed by LS-DYNA" if "CALCULATE"
               in _kw else "an MPP-only radiation enclosure")
            + ("; the _RESTART suffix resumes an interrupted view-factor "
               "calculation" if _kw.endswith("_RESTART") else ""),
            "no Radioss counterpart: /RADIATION is radiation to an "
            "ENVIRONMENT temperature only (radiation.F:155 computes "
            "AREA*EMISIG*(T_INF**4 - TE**4) from ONE segment's own nodes), "
            "and there is no surface-to-surface exchange, no enclosure and no "
            "view-factor machinery anywhere in "
            "engine/source/constraints/thermic")
        for _kw in (
            "BOUNDARY_RADIATION_ENCLOSURE",
            "BOUNDARY_RADIATION_SET_VF_READ",
            "BOUNDARY_RADIATION_SET_VF_CALCULATE",
            "BOUNDARY_RADIATION_SET_VF_READ_RESTART",
            "BOUNDARY_RADIATION_SET_VF_CALCULATE_RESTART",
            "BOUNDARY_RADIATION_SEGMENT_VF_READ",
            "BOUNDARY_RADIATION_SEGMENT_VF_CALCULATE",
            "BOUNDARY_RADIATION_SEGMENT_VF_READ_RESTART",
            "BOUNDARY_RADIATION_SEGMENT_VF_CALCULATE_RESTART",
        )
    },
    "BOUNDARY_FLUX_TRAJECTORY": _thermal_deferred(
        "BOUNDARY_FLUX_TRAJECTORY",
        "a MOVING heat-flux source (a laser or torch) that travels along a "
        "nodal path with its own beam profile (Vol I R17 p.5-50)",
        "no Radioss counterpart: /IMPFLUX applies a flux density to a FIXED "
        "/SURF (fixflux.F:149-203) with no position argument, so the "
        "trajectory — the whole content of the card — cannot be expressed"),
    # ── The remaining *MAT_THERMAL_* families of Vol II R17 p.2-9 ───────────
    # Registering them is what turns a silent line in "Skipped (unsupported)
    # keywords" into a statement of WHICH thermal material the deck loses. The
    # numeric *MAT_T## aliases are attached below, from ONE table.
    "MAT_THERMAL_ORTHOTROPIC_TD": _thermal_deferred(
        "MAT_THERMAL_ORTHOTROPIC_TD",
        "a TABULATED orthotropic thermal material — three direction-dependent "
        "conductivities, each stated as a (temperature, value) table, plus a "
        "material axis definition (Vol II R17 pp.3-13..3-18)",
        "/HEAT/MAT is ISOTROPIC and takes no function ids at any cfg version "
        "(hm_read_therm.F:157-166 reads nine scalars), so neither the "
        "anisotropy nor the tabulation has a target. State "
        "*MAT_THERMAL_ISOTROPIC_TD if the three directions are equal in fact: "
        "k2rad fits that onto AS + BS*T"),
    "MAT_THERMAL_ORTHOTROPIC_TD_LC": _thermal_deferred(
        "MAT_THERMAL_ORTHOTROPIC_TD_LC",
        "the load-curve spelling of the tabulated orthotropic thermal "
        "material — the same three direction-dependent conductivities, given "
        "as *DEFINE_CURVE ids instead of in-card tables",
        "/HEAT/MAT is ISOTROPIC and holds one (AS, BS) pair, so the "
        "anisotropy has no target; see *MAT_THERMAL_ORTHOTROPIC_TD"),
    "MAT_THERMAL_DISCRETE_BEAM": _thermal_deferred(
        "MAT_THERMAL_DISCRETE_BEAM",
        "a thermal property set for DISCRETE beam elements (Vol II R17 "
        "p.3-19)",
        "no Radioss counterpart: /HEAT/MAT is keyed on a structural material "
        "id and Radioss's discrete elements (/PROP/TYPE4 springs) carry no "
        "conduction path at all — pforc3.F's conduction is the HUGHES-LIU "
        "beam's"),
    "MAT_THERMAL_CHEMICAL_REACTION": _thermal_deferred(
        "MAT_THERMAL_CHEMICAL_REACTION",
        "a thermal material with up to three Arrhenius decomposition "
        "reactions, each adding its own heat of reaction to the energy "
        "balance (Vol II R17 pp.3-21..3-24)",
        "no Radioss counterpart: /HEAT/MAT has no reaction, no species and no "
        "heat-of-reaction cell, and there is no chemical-kinetics source term "
        "anywhere in engine/source/constraints/thermic"),
    "MAT_THERMAL_CHEMICAL_REACTION_ORTHOTROPIC": _thermal_deferred(
        "MAT_THERMAL_CHEMICAL_REACTION_ORTHOTROPIC",
        "the orthotropic spelling of the Arrhenius decomposition thermal "
        "material",
        "no Radioss counterpart, twice over: /HEAT/MAT is isotropic and has "
        "no reaction terms"),
    "MAT_THERMAL_ISOTROPIC_PHASE_CHANGE": _thermal_deferred(
        "MAT_THERMAL_ISOTROPIC_PHASE_CHANGE",
        "a thermal material carrying a solid/liquid PHASE CHANGE — a latent "
        "heat released over a solidus/liquidus interval",
        "/HEAT/MAT's T1/AL/BL cells do split conductivity at a melting "
        "temperature, but there is no LATENT HEAT cell anywhere on the card "
        "(hm_read_therm.F:157-166) and RHO0_CP is one constant, so the "
        "enthalpy of the transformation — the point of the keyword — cannot "
        "be carried"),
    "MAT_THERMAL_ISPG": _thermal_deferred(
        "MAT_THERMAL_ISPG",
        "the thermal material of the ISPG (incompressible smoothed particle "
        "Galerkin) solver",
        "no Radioss counterpart: there is no ISPG solver in OpenRadioss"),
    "MAT_THERMAL_USER_DEFINED": _thermal_deferred(
        "MAT_THERMAL_USER_DEFINED",
        "a USER SUBROUTINE thermal material (*MAT_T11..T15), whose "
        "conductivity and capacity are computed by compiled-in code",
        "no Radioss counterpart: /HEAT/MAT is a fixed nine-scalar card and "
        "Radioss's user-material hooks (/MAT/USERn) are STRUCTURAL laws with "
        "no thermal-property entry point"),
    # ── The thermal *BOUNDARY_ families with no counterpart ─────────────────
    "BOUNDARY_TEMPERATURE_PERIODIC_SET": _thermal_deferred(
        "BOUNDARY_TEMPERATURE_PERIODIC_SET",
        "a PERIODIC temperature boundary condition tying two segment sets "
        "(SSID1/SSID2, with a translation or a rotation about AXE/NID by "
        "ANGLE, Vol I R17 p.5-152)",
        "no Radioss counterpart: /IMPTEMP prescribes an absolute temperature "
        "on a /GRNOD from a /FUNCT of time (fixtemp.F:180-199) and there is "
        "no constraint anywhere in Radioss that ties one node's temperature "
        "to another's"),
    "BOUNDARY_TEMPERATURE_RSW": _thermal_deferred(
        "BOUNDARY_TEMPERATURE_RSW",
        "a resistance-spot-weld nugget: temperatures prescribed to whatever "
        "nodes fall inside a growing ELLIPSOIDAL region (Vol I R17 p.5-154)",
        "no Radioss counterpart: /IMPTEMP drives a node group fixed at "
        "conversion time, with no geometric region and no membership that "
        "changes during the run"),
    "BOUNDARY_TEMPERATURE_TRAJECTORY": _thermal_deferred(
        "BOUNDARY_TEMPERATURE_TRAJECTORY",
        "a temperature boundary condition applied to whatever nodes lie "
        "inside a cylinder or prism that MOVES along a nodal path at a "
        "prescribed speed (Vol I R17 p.5-159)",
        "no Radioss counterpart: /IMPTEMP's /GRNOD is resolved once in the "
        "starter and cannot follow a trajectory"),
    "BOUNDARY_THERMAL_BULKFLOW": _thermal_deferred(
        "BOUNDARY_THERMAL_BULKFLOW",
        "bulk FLUID-FLOW elements carrying a mass flow rate MDOT along beam "
        "elements, optionally with the fluid upwind algorithm "
        "(*BOUNDARY_THERMAL_BULKFLOW_OPTION1_{OPTION2}, OPTION1 = ELEMENT or "
        "SET, OPTION2 = UPWIND, Vol I R17 p.5-164)",
        "no Radioss counterpart: there is no advective transport term in the "
        "Lagrangian thermal solver — tempur.F:48-55 is the whole integrator "
        "and every source adds heat to a node, never to a flowing stream"),
    "BOUNDARY_THERMAL_BULKNODE": _thermal_deferred(
        "BOUNDARY_THERMAL_BULKNODE",
        "a thermal BULK NODE: a lumped-capacity reservoir of volume VOL "
        "exchanging heat with NBNSEG structural segments through its own h "
        "(Vol I R17 p.5-165)",
        "no Radioss counterpart: /CONVEC exchanges with an ENVIRONMENT "
        "temperature read from a /FUNCT of time (convec.F:152), never with a "
        "second body whose own temperature the exchange updates"),
    "BOUNDARY_THERMAL_WELD": _thermal_deferred(
        "BOUNDARY_THERMAL_WELD",
        "a MOVING welding heat source with a double-ellipsoid (Goldak) "
        "distribution — semi-axes a/b/cf/cr, power Q and the front/rear "
        "fractions Ff/Fr (Vol I R17 p.5-167)",
        "no Radioss counterpart: /IMPFLUX applies a flux density to a FIXED "
        "/SURF (fixflux.F:149-203) with no position argument and no volume "
        "source, so neither the motion nor the depth distribution can be "
        "expressed"),
    "BOUNDARY_THERMAL_WELD_TRAJECTORY": _thermal_deferred(
        "BOUNDARY_THERMAL_WELD_TRAJECTORY",
        "the nodal-path spelling of the moving welding heat source, with a "
        "prescribed velocity along the path (Vol I R17 p.5-171)",
        "no Radioss counterpart, for the same reason as *BOUNDARY_THERMAL_"
        "WELD: /IMPFLUX has no position argument"),
}

#: Vol II R17 p.2-9, verbatim: the ``*MAT_T##`` numeric aliases of the thermal
#: material families. ONE table, so an alias can never be registered (or
#: diagnosed) differently from the name it aliases. Note the gaps are the
#: MANUAL's: T11-T15 are five aliases of one card, there is no T16, and T17/T18
#: exist. Every canonical name below must already be a key of
#: RARE_MATERIAL_KEYWORDS — the loop asserts it.
_MAT_THERMAL_ALIASES = {
    "MAT_THERMAL_ISOTROPIC":                     ("MAT_T01",),
    "MAT_THERMAL_ORTHOTROPIC":                   ("MAT_T02",),
    "MAT_THERMAL_ISOTROPIC_TD":                  ("MAT_T03",),
    "MAT_THERMAL_ORTHOTROPIC_TD":                ("MAT_T04",),
    "MAT_THERMAL_DISCRETE_BEAM":                 ("MAT_T05",),
    "MAT_THERMAL_CHEMICAL_REACTION":             ("MAT_T06",),
    "MAT_THERMAL_CWM":                           ("MAT_T07",),
    "MAT_THERMAL_ORTHOTROPIC_TD_LC":             ("MAT_T08",),
    "MAT_THERMAL_ISOTROPIC_PHASE_CHANGE":        ("MAT_T09",),
    "MAT_THERMAL_ISOTROPIC_TD_LC":               ("MAT_T10",),
    "MAT_THERMAL_USER_DEFINED":                  ("MAT_T11", "MAT_T12",
                                                 "MAT_T13", "MAT_T14",
                                                 "MAT_T15"),
    "MAT_THERMAL_CHEMICAL_REACTION_ORTHOTROPIC": ("MAT_T17",),
    "MAT_THERMAL_ISPG":                          ("MAT_T18",),
}

for _name, _aliases in _MAT_THERMAL_ALIASES.items():
    _canon = RARE_MATERIAL_KEYWORDS[_name]
    for _alias in _aliases:
        RARE_MATERIAL_KEYWORDS[_alias] = _canon
del _name, _aliases, _canon, _alias
for _kw, _h in RARE_MATERIAL_KEYWORDS.items():
    HANDLERS[_kw] = _h
del _kw, _h

for _kw, _h in RARE_CARD_KEYWORDS.items():
    HANDLERS[_kw] = _h
del _kw, _h

# *DEFINE_HEX_SPOTWELD_ASSEMBLY{_N}, N = 1..16 (definehexspotweld.cfg
# APPEND_OPTIONS + CHECK idsmax<17). The bare keyword free-reads the list.
HANDLERS["DEFINE_HEX_SPOTWELD_ASSEMBLY"] = handle_define_hex_spotweld_assembly
for _n in range(1, 17):
    HANDLERS[f"DEFINE_HEX_SPOTWELD_ASSEMBLY_{_n}"] = handle_define_hex_spotweld_assembly
del _n

# The ELFORM=6 discrete-beam materials OpenRadioss has no spring law for. They
# are parsed for their MID only — see handle_mat_unsupported_discrete_beam.
for _kw in _UNSUPPORTED_DBEAM_KEYWORDS:
    HANDLERS[_kw] = handle_mat_unsupported_discrete_beam
del _kw


def _rwall_geometric_keywords():
    """Every *RIGIDWALL_GEOMETRIC spelling, generated rather than hand-listed.

    "The order of the OPTIONS is arbitrary" (Manual p. 40-4) — only the DATA
    CARDS have a fixed order — so every permutation of the optional suffixes
    is a legal spelling and each needs its own dispatch key (k2rad registers
    exact keywords; a substring rule would misclassify neighbouring
    families). _INTERIOR exists for CYLINDER/SPHERE only (R10.1+ cfg).

    _ID is generated too, but only in the NON-final positions: a trailing _ID
    is stripped by the keyword parser into ``block.options`` and the base
    spelling already covers it, while a mid-keyword _ID stays in the keyword
    and needs its own key (``_rwall_has_id`` then still finds it, so the RWID
    header card is read either way). _DEFORM is deliberately NOT generated —
    its two extra cards shift every card index after the cylinder card, so it
    must warn-skip rather than convert as a plain cylinder.

    Yields (keyword, has_interior) pairs.
    """
    for _shape in _RWALL_GEOM_SHAPES:
        opts = ["_MOTION", "_DISPLAY", "_ID"]
        if _shape in ("CYLINDER", "SPHERE"):
            opts.append("_INTERIOR")
        for _r in range(len(opts) + 1):
            for _combo in _permutations(opts, _r):
                if _combo and _combo[-1] == "_ID":
                    continue            # trailing _ID: parser strips it
                yield (f"RIGIDWALL_GEOMETRIC_{_shape}" + "".join(_combo),
                       "_INTERIOR" in _combo)


for _kw, _interior in _rwall_geometric_keywords():
    HANDLERS[_kw] = (handle_rigidwall_geometric_interior if _interior
                     else handle_rigidwall_geometric)
del _kw, _interior


#: The four *RIGIDWALL_PLANAR keyword options, in the order their DATA CARDS
#: appear (Card Summary, Manual p. 40-17). The card order is fixed; the NAME
#: order is not — see _rwall_planar_keywords.
_RWALL_PLANAR_OPTIONS = ("ORTHO", "FINITE", "MOVING", "FORCES")


def _rwall_planar_keywords():
    """Every *RIGIDWALL_PLANAR spelling, generated rather than hand-listed.

    "The ordering of the input below as specified in the Card Summary must be
    observed, but the ordering of the options in the keyword name is
    unimportant. For example, both *RIGIDWALL_PLANAR_ORTHO_FINITE and
    *RIGIDWALL_PLANAR_FINITE_ORTHO are valid and have the same effect."
    (Manual p. 40-16.) k2rad dispatches on exact keywords, so each ordering
    needs its own key.

    Hand-listing only the canonical orderings left 8 of the 16 legal non-ORTHO
    spellings — _FORCES_MOVING, _MOVING_FINITE, _FINITE_ORTHO and friends —
    missing the exact-match lookup, and with no RIGIDWALL_PLANAR row in
    _PREFIX_HANDLERS they fell into the generic skipped_keywords list: the wall
    silently vanished from the model and the user was told only that some
    keyword was skipped, never that a rigid wall was lost. Generating the
    permutations closes that by construction, and _OFFSET_SPECS in assembly.py
    is generated from this same source so the two cannot drift apart.

    _ID is not generated: the parser strips a TRAILING _ID into block.options
    (parser._TRAILING) and that is where p. 40-16 puts it — "an ID number may
    be assigned ... using the following option: ID", listed apart from the
    {OPTION} slots, unlike the geometric family where it sits in the
    arbitrary-order list. _DISPLAY is not generated either: it is legal on this
    family too and needs NO extra card (the Card Summary stops at Card 7), but
    registering it would start CONVERTING walls that are skipped today, which
    is a feature and not this batch's business — it stays a known gap.

    Yields (keyword, is_ortho) pairs; ORTHO has no /RWALL equivalent and routes
    to the warn-skip handler.
    """
    for _r in range(len(_RWALL_PLANAR_OPTIONS) + 1):
        for _combo in _permutations(_RWALL_PLANAR_OPTIONS, _r):
            yield ("_".join(("RIGIDWALL_PLANAR",) + _combo),
                   "ORTHO" in _combo)


for _kw, _is_ortho in _rwall_planar_keywords():
    HANDLERS[_kw] = (handle_rigidwall_ortho if _is_ortho
                     else handle_rigidwall_planar)
del _kw, _is_ortho


#: Keyword PREFIX → handler, tried when the exact-match lookup misses. Mostly
#: the element families whose handler can keep the connectivity of an option it
#: does not understand (see the UNKNOWN-suffix branch in each handler).
#:
#: Without this, an unlisted spelling would land in skipped_keywords, and for
#: elements that is not a soft failure: _make_parts_and_elements emits elements
#: inside the state.parts loop, so a *ELEMENT_SHELL_MCID block leaves its /PART
#: in the deck with NO /SHELL block under it — the elements are gone, the part
#: is silently empty, and result.warnings says nothing. That is exactly what
#: dyna2rad does (its CFG table matches USER_NAMES exactly), and it is the
#: single biggest parity win in this family.
#:
#: *RIGIDWALL_GEOMETRIC is here for the opposite reason: its handler must NOT
#: see an option it cannot parse, so the prefix routes every unregistered
#: spelling to an explicit warn-skip instead of the generic skipped-keyword
#: note (which says nothing about WHY the wall is gone).
#: *PART is here for BOTH reasons at once. A spelling whose suffix decomposes
#: into *PART option tokens is walked (mesh AND options survive) — belt to the
#: generated keys above; a *PART_SENSOR / _ADD / _MODES / _MOVE / _DUPLICATE /
#: _ANNEAL / _STACKED_ELEMENTS is a DIFFERENT keyword whose first card is not a
#: HEADING, so it is warn-skipped by name rather than parsed into phantom parts.
#: PART_COMPOSITE MUST precede it — the loop breaks on the first prefix match, and
#: a composite ordering the twelve generated keys miss belongs on the composite
#: walk (its ply cards are nothing like *PART's), not on the plain one.
#: ELEMENT_TSHELL is listed on its own row rather than under ELEMENT_SHELL:
#: the match is on a TOKEN boundary, so "ELEMENT_TSHELL" is not an
#: "ELEMENT_SHELL" spelling at all and would otherwise fall through to
#: skipped_keywords — which for a thick shell means every element of the part
#: silently missing from the deck (measured on master: the nine r14 thick-shell
#: decks each emitted a bare /PART on a placeholder /PROP/SHELL and nothing
#: else, with no MESH LOSS warning, because no element was ever parsed).
#: ELEMENT_SPH needs its own row for the same token-boundary reason, and the
#: stakes are the same: measured on master, converting
#: W11_SETUP_SPH_BirdStrike.k left ELEMENT_SPH in skipped_keywords and lost all
#: 18,795 particles — 1.8199 kg, 100 % of the projectile — with NO MESH LOSS
#: warning, while the two eroding contacts that scope those particle nodes
#: converted and reported themselves healthy.
_PREFIX_HANDLERS = (
    # *AIRBAG_* is the family where a silent skip costs the most: the mesh,
    # materials, contacts and time history all convert, the run reaches NORMAL
    # TERMINATION, and the bag simply never inflates. Every documented spelling
    # has an exact key (models, unsupported models, both reference geometries,
    # each with the legacy _<digits> suffix); this catches the UNDOCUMENTED
    # one, which would otherwise land in skipped_keywords unnamed. It emits
    # nothing and says so — a warn-only handler, never a card.
    ("AIRBAG", handle_airbag_unsupported),
    ("ELEMENT_TSHELL", handle_element_tshell),
    ("ELEMENT_SPH", handle_element_sph),
    ("ELEMENT_SHELL", handle_element_shell),
    ("ELEMENT_BEAM", handle_element_beam),
    ("ELEMENT_PLOTEL", handle_element_plotel),
    ("RIGIDWALL_GEOMETRIC", handle_rigidwall_geometric_unsupported),
    ("PART_COMPOSITE", handle_part_composite),
    ("PART", handle_part_unknown_option),
)


def dispatch(block: Block, state: ConversionState) -> None:
    """Look up and call the handler for *block.keyword*.

    The prefix fallback matches on a TOKEN boundary — ``kw == prefix`` or
    ``kw.startswith(prefix + "_")`` — not on a bare character prefix.
    ``*PARTICLE_BLAST`` is not a `*PART` spelling, and a bare
    ``startswith("PART")`` routed it into the *PART fallback, which then told the
    user that "_ICLE_BLAST is not one of INERTIA/REPOSITION, CONTACT, ..." and
    that its parts might have lost every element. The emitted deck was the same
    either way (both land in skipped_keywords), but the diagnostic named the wrong
    keyword family.
    """
    handler = HANDLERS.get(block.keyword)
    if handler is None:
        for _prefix, _handler in _PREFIX_HANDLERS:
            if (block.keyword == _prefix
                    or block.keyword.startswith(_prefix + "_")):
                handler = _handler
                break
    if handler is not None:
        # Install this block's *PARAMETER_LOCAL scope for the duration of the
        # handler. Parameter scoping is a PARSE-TIME concept in LS-DYNA while
        # k2rad resolves "&name" here, lazily — long after the file that
        # declared a LOCAL name was closed and its binding removed from the
        # global table. Without this a *PARAMETER_LOCAL resolved as 0 on a
        # perfectly valid deck (measured: /PROP/SHELL Thick 0, starter ERROR
        # 495), and a LOCAL masking an outer parameter silently produced the
        # OUTER value. try/finally, so a handler that raises cannot leak a
        # scope onto the next block.
        prev = set_active_scope(block.scope)
        try:
            handler(block, state)
        finally:
            set_active_scope(prev)
    else:
        state.skipped_keywords.append(block.keyword)
