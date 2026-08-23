"""
k2rad.state  –  ConversionState: all data collected from the .k file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class NodeData:
    x: float
    y: float
    z: float


@dataclass
class ShellElem:
    """*ELEMENT_SHELL (+ the _THICKNESS / _BETA / _MCID / _OFFSET / … variants).

    ``thick_nodes`` holds the optional card's nodal thicknesses THIC1..THIC4 in
    SLOT order (slot i = the id in ``nodes[i]``), empty when the element carried
    no thickness card at all. A blank cell is stored as ``0.0`` because that is
    what LS-DYNA does with it — Vol I R17 *ELEMENT_SHELL Card 2 gives THIC1..4
    the default ``0.``, and Remark 1 then reads "default values in place of ZERO
    shell thicknesses are taken from the cross-section property definition of
    the PID". So blank and an explicit 0.0 are the SAME input, and the fallback
    is per VALUE, not per element (writer/mesh.py _shell_element_thickness).

    ``beta`` is the *ELEMENT_SHELL_BETA / _THICKNESS material angle in DEGREES →
    the /SHELL / /SH3N ``Phi`` column (the solver converts to radians itself,
    hm_read_shell.F:170). NOTE that OpenRadioss only READS that column for
    IGTYP 17/51/52; on an IGTYP 9/10/11/16 part the angle has to be folded into
    the property instead — see writer/composites.py _fold_element_beta.
    """
    eid: int
    pid: int
    nodes: List[int]   # 3 or 4 node IDs (trailing zeros stripped)
    thick_nodes: List[float] = field(default_factory=list)
    beta: float = 0.0
    #: True for an element recovered from an *ELEMENT_SHELL/_BEAM block whose
    #: option suffix k2rad does not model, where the connectivity was
    #: identified by CONTENT rather than by position. Such a candidate is
    #: re-checked against the node table before it is emitted
    #: (writer/mesh.py _screen_provisional_elements).
    provisional: bool = False


@dataclass
class SolidElem:
    eid: int
    pid: int
    nodes: List[int]   # 4 or 8 node IDs


@dataclass
class TshellElem:
    """*ELEMENT_TSHELL — an 8-node THICK SHELL, emitted as a Radioss /BRICK.

    Kept in a container of its own rather than on ``solid_elems``, for two
    independent reasons. The /BRICK writer splits a solid part by DISTINCT-node
    count (4 → /TETRA4, 10 → /TETRA10, else /BRICK), which would turn a
    degenerate 6-node thick shell — written ``n1 n2 n3 n3 n5 n6 n7 n7`` — into
    something it is not; and the property a thick shell needs is
    /PROP/TYPE20|21|22, never /PROP/SOLID (starter ERROR 3047 the moment the
    material is orthotropic, and no through-thickness layers either way).

    ``nodes`` is the LS-DYNA n1..n8 order VERBATIM. LS-DYNA's convention is
    "nodes n1 to n4 define the lower surface, and nodes n5 to n8 define the
    upper surface" (Vol I R16 p.2703 Remark 1), and with ``Icstr=010`` Radioss
    reads the through-thickness pairs as (1-5) (2-6) (3-7) (4-8)
    (``starter/source/elements/thickshell/solidec/scdtchk3.F:84-246``, and
    ``scortho3.F`` builds the same S axis from the connectivity) — so the two
    conventions coincide and NO permutation is needed. dyna2rad copies the
    connectivity verbatim as well (``convertelements.cxx:146-149``).

    ``beta`` is the *ELEMENT_TSHELL_BETA orthotropy offset angle in DEGREES.
    /BRICK has NO per-element angle column at all (contrast /SHELL's Phi), so
    the writer folds a value shared by a whole section into that property's
    angle slot (TYPE21 ``MAT_BETA`` / TYPE22 ``Prop_phi``) and warn-drops a
    non-uniform one — see writer/tshell.py ``_fold_tshell_beta``.
    """
    eid: int
    pid: int
    nodes: List[int]   # 8 node IDs, LS-DYNA order, bottom face first
    beta: float = 0.0
    #: See ShellElem.provisional — set for an element recovered by CONTENT from
    #: an *ELEMENT_TSHELL block whose option suffix k2rad does not model.
    provisional: bool = False


@dataclass
class TshellLayup:
    """A per-PART thick-shell layup → one /PROP/TYPE22 (TSH_COMP).

    Two sources, both of which state a REAL per-ply material and thickness (so
    neither is the ``*SECTION_TSHELL`` ICOMP path, whose only per-layer datum is
    the angle):

    * ``*PART_COMPOSITE_TSHELL`` card 5a/5b — ``MID THICK B TMID`` per layer.
    * ``*ELEMENT_TSHELL_COMPOSITE`` card 2b — ``MID THICK B`` per integration
      point, per ELEMENT. Radioss has no per-element layup, so this is only
      promoted when every thick shell on the part declares the SAME stack;
      otherwise the writer warn-drops it and the part keeps its section
      property.

    LS-DYNA scales the THICK values to the element geometry in both cases ("For
    thick shells, the total thickness is obtained from the positions of the
    nodes on the top and bottom surfaces. In this case, the THICKi are also
    scaled to conform to the geometry", Vol I R16 p.3529), which is exactly
    /PROP/TYPE22's relative ``ti/t`` semantic — so the mapping is
    ``ti/t = THICKi / sum(THICKj)`` with no unit conversion.
    """
    pid: int
    title: str = ""
    source: str = ""            # the keyword the layup came from
    elform: int = 0
    shrf: float = 0.0
    tshear: int = 0
    plies: List["CompositePly"] = field(default_factory=list)


@dataclass
class SphCell:
    """*ELEMENT_SPH — one SMOOTHED-PARTICLE cell, emitted as a Radioss /SPHCEL.

    An SPH particle has NO CONNECTIVITY: the card is ``NID PID MASS [NEND]`` and
    the particle IS its supporting node. Radioss states the same thing twice
    over — ``hm_read_sphcel.F:243-250`` reads the single id column into
    ``KXSP(3,*)`` as the NODE user id and then sets the cell id to it
    ("same identifier as the node"), and the Altair help card says "The
    particles will have the same identifier as their supporting node". So there
    is no separate element id to keep: ``nid`` is both.

    ``nodes`` is a one-element list, so the ~40 ``ref.update(e.nodes)`` /
    ``nids.update(e.nodes)`` element-registry walks take an SPH particle with no
    shape change at all. ``eid`` is an alias of ``nid`` for the same reason (the
    orphan census and the /TH screen address elements by ``eid``).

    ``flag`` is the Radioss ``/SPHCEL`` Type column, and it decides what ``mass``
    MEANS (``spinit3.F:139-153``):

    ==========  =========================  ==============================
    ``flag``    ``mass`` holds             particle mass
    ==========  =========================  ==============================
    1           a MASS                     ``mass``
    2           a VOLUME                   ``rho * mass``
    0           nothing (blank column)     ``/PROP/SPH`` Mp
    ==========  =========================  ==============================

    The LS-DYNA side states the same three cases in one signed cell: "GT.0.0:
    Mass value. LT.0.0: Volume. The absolute value will be used as volume …
    SPH element mass is calculated by |MASS| x rho" (Vol I R16/R17
    *ELEMENT_SPH), plus the ``_VOLUME`` keyword suffix, which "has the same
    effect as giving a negative number in the MASS field". So the sign and the
    suffix are folded into ``flag`` at parse time and ``mass`` is always the
    NON-NEGATIVE magnitude. dyna2rad copies the signed cell verbatim and honours
    neither convention — measured, a MASS of -2e-6 gave ``TOTAL MASS = 8.0 kg``
    instead of 0.016 kg (the negative value is discarded by the starter and the
    fabricated ``Mp = 1`` fallback takes over), and ``*ELEMENT_SPH_VOLUME`` came
    out wrong by exactly rho.

    ``generated`` marks a particle expanded from the ``NEND`` range generator
    ("*ELEMENT_SPH cards are generated between NID to NEND using current PID and
    MASS data") rather than written out card by card. Neither dyna2rad nor
    OpenRadioss's native reader performs that expansion — measured, a card with
    NEND gave ``NUMSPH = 1``.
    """
    nid: int
    pid: int
    mass: float = 0.0
    flag: int = 1
    generated: bool = False
    #: See ShellElem.provisional — set for a particle recovered by CONTENT from
    #: an *ELEMENT_SPH block whose option suffix k2rad does not model.
    provisional: bool = False

    @property
    def nodes(self) -> List[int]:
        """The one node this particle sits on, as a list, so every element
        registry walk that says ``update(e.nodes)`` works unchanged."""
        return [self.nid]

    @property
    def eid(self) -> int:
        """The cell id, which Radioss forces equal to the node id."""
        return self.nid


@dataclass
class BeamElem:
    """*ELEMENT_BEAM (+ _ORIENTATION).

    ``vx/vy/vz`` is the *ELEMENT_BEAM_ORIENTATION vector, expressed relative to
    N1 ("the orientation vector points to a virtual third node", Vol I R17).
    The writer prepass _synthesize_beam_orientation_nodes turns a non-zero
    vector into a real /NODE at ``pos(N1) + V`` and puts its id in ``n3``.
    """
    eid: int
    pid: int
    n1: int
    n2: int
    n3: int            # orientation node
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    #: See ShellElem.provisional.
    provisional: bool = False


@dataclass
class ProvisionalElemBlock:
    """Bookkeeping for one *ELEMENT_SHELL/_BEAM block with an UNMODELLED option.

    The option's card layout is by definition unknown there, so the handler
    cannot step over the extra cards positionally: it keeps every line that can
    only be a connectivity card (all fields plain positive integers) and marks
    the elements ``provisional``. That content test is necessary but NOT
    sufficient — an option card made of integers (an *ELEMENT_BEAM_THICKNESS
    section written as ``10 10 10 10``, an *ELEMENT_SHELL_COMPOSITE ply card
    ``mid thick beta tmid …``) passes it and would become an element on node ids
    that do not exist, which is starter ERROR 78 / 222 and a HARD failure where
    the old behaviour was a silent skip. ``_screen_provisional_elements`` runs
    after parsing (so *NODE may follow *ELEMENT, and includes are merged) and
    drops the candidates the node table does not back.
    """
    keyword: str
    kind: str                       # "shell" | "beam" | "tshell"
    option: str                     # the unmodelled suffix, e.g. "_COMPOSITE"
    eids: List[int] = field(default_factory=list)
    n_unparsed: int = 0


@dataclass
class PlotelElem:
    """*ELEMENT_PLOTEL — a 2-node VISUALIZATION-ONLY line element.

    Card (Vol I R17): EID(I8) N1(I8) N2(I8); there is NO PID field — LS-DYNA
    assigns part id 10000000 implicitly. Converted to an inert /SPRING on a
    dedicated /PART + /PROP/TYPE4 with K=C=0 (no stiffness, no mass, no time
    step) — see writer/loads.py _make_plotel_elements.
    """
    eid: int
    n1: int
    n2: int


@dataclass
class DiscreteElem:
    """*ELEMENT_DISCRETE — a 2-node spring/damper element → /SPRING.

    LS-DYNA card (Keyword971 ELEMENTS/discrete.cfg):
        EID(I8) PID(I8) N1(I8) N2(I8) VID(I8) S(E16) PF(I8) OFFSET(E16)
      vid    = *DEFINE_SD_ORIENTATION id (0 = act along the N1-N2 axis)
      s      = scale factor on the element force (default 1.0)
      offset = initial offset (preload displacement)
    N2 = 0 means the element is attached to ground.
    """
    eid: int
    pid: int
    n1: int
    n2: int
    vid: int = 0
    s: float = 1.0
    offset: float = 0.0


@dataclass
class SectionDiscrete:
    """*SECTION_DISCRETE → /PROP/TYPE4 (SPRING) flags.

    Card1: SECID DRO KD V0 CL FD;  Card2: CDL TDL.
      dro = 0 translational, 1 torsional (torsional has no /PROP/TYPE4 map)
      kd/v0/cl = dynamic magnification factor / test velocity / clearance
      fd  = failure deflection (positive tension, negative compression)
      cdl/tdl = deflection limits in compression/tension (element deletion)
    """
    secid: int
    title: str
    dro: int = 0
    kd: float = 0.0
    v0: float = 0.0
    cl: float = 0.0
    fd: float = 0.0
    cdl: float = 0.0
    tdl: float = 0.0


@dataclass
class MatSpringElastic:
    """*MAT_SPRING_ELASTIC (MAT_S01): F = K·dl → /PROP/TYPE4 K."""
    mid: int
    k: float


@dataclass
class MatSpringNonlinearElastic:
    """*MAT_SPRING_NONLINEAR_ELASTIC (MAT_S04): F = LCD(dl), optionally scaled
    by rate curve LCR → /PROP/TYPE4 fct_ID1 (LCR has no confident TYPE4 slot)."""
    mid: int
    lcd: int
    lcr: int = 0


@dataclass
class MatDamperViscous:
    """*MAT_DAMPER_VISCOUS (MAT_D01): F = DC·(dl/dt) → /PROP/TYPE4 C."""
    mid: int
    dc: float


@dataclass
class MatSpringElastoplastic:
    """*MAT_SPRING_ELASTOPLASTIC (MAT_S03): K KT FY → /PROP/TYPE4 K1 + a
    synthesized 5-point elastic-plastic force function on fct_ID11 with H1=1
    (isotropic hardening, unloading along K).

    Card (Keyword971 MAT/SDMAT3.cfg): MID(I10) K(E10) KT(E10) FY(E10).
      k  = elastic stiffness, kt = tangent (plastic) stiffness,
      fy = yield force (or moment on a DRO=1 section).
    """
    mid: int
    k: float = 0.0
    kt: float = 0.0
    fy: float = 0.0


@dataclass
class MatDamperNonlinearViscous:
    """*MAT_DAMPER_NONLINEAR_VISCOUS (MAT_S05): LCDR = force vs rate-of-
    displacement → /PROP/TYPE4 fct_ID41 (the h(δ̇) damping-force function),
    Hscale1 = 1.

    Card (Keyword971 MAT/SDMAT5.cfg): MID(I10) LCDR(I10).
    """
    mid: int
    lcdr: int = 0


@dataclass
class MatSpringGeneralNonlinear:
    """*MAT_SPRING_GENERAL_NONLINEAR (MAT_S06) → /PROP/TYPE4 fct_ID11 = LCDL
    (loading), fct_ID31 = LCDU (unloading), H1 = 6 (isotropic hardening with
    nonlinear unloading).

    Card (Keyword971 MAT/SDMAT6.cfg):
        MID(I10) LCDL(I10) LCDU(I10) BETA(E10) TYI(E10) CYI(E10)
      beta = 0 tension+compression yield with softening, != 0 kinematic
             hardening, 1 isotropic hardening
      tyi/cyi = initial yield force in tension / compression
    """
    mid: int
    lcdl: int = 0
    lcdu: int = 0
    beta: float = 0.0
    tyi: float = 0.0
    cyi: float = 0.0


@dataclass
class MatSpringInelastic:
    """*MAT_SPRING_INELASTIC (MAT_S08) → /PROP/TYPE4 K1 = KU + a mirrored
    LCFD force function on fct_ID11.

    Card (Keyword971 MAT/SDMAT8.cfg): MID(I10) LCFD(I10) KU(E10) CTF(E10).
      lcfd = force/torque vs displacement/rotation, defined in the POSITIVE
             quadrant only whatever the tension/compression sense
      ku   = unloading stiffness (max(KU, max loading stiffness) is used)
      ctf  = -1 tension only, +1 compression only (default)
    """
    mid: int
    lcfd: int = 0
    ku: float = 0.0
    ctf: float = 1.0


# ── *SECTION_BEAM ELFORM=6 discrete-beam materials → 6-DOF spring properties ──

@dataclass
class MatDiscreteBeamLinear:
    """*MAT_LINEAR_ELASTIC_DISCRETE_BEAM (MAT_066) → a 6-DOF spring property
    (/PROP/TYPE8 or TYPE13) with K1..K6 = TKR TKS TKT RKR RKS RKT and
    C1..C6 = TDR TDS TDT RDR RDS RDT.

    Card1: MID RO TKR TKS TKT RKR RKS RKT
    Card2: TDR TDS TDT RDR RDS RDT
    Card3: FOR FOS FOT MOR MOS MOT   (preloads → 2-point stiffness functions)
    """
    mid: int
    rho: float = 0.0
    k: List[float] = field(default_factory=lambda: [0.0] * 6)
    c: List[float] = field(default_factory=lambda: [0.0] * 6)
    preload: List[float] = field(default_factory=lambda: [0.0] * 6)


@dataclass
class MatDiscreteBeamNonlinearElastic:
    """*MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM (MAT_067) → a 6-DOF spring
    property: fct_ID1i = LCIDTR..LCIDRT (loading f(δ)), fct_ID4i =
    LCIDTDR..LCIDRDT (damping h(δ̇)) with Hscale_i = 1.

    Card1: MID RO LCIDTR LCIDTS LCIDTT LCIDRR LCIDRS LCIDRT
    Card2: LCIDTDR LCIDTDS LCIDTDT LCIDRDR LCIDRDS LCIDRDT
    Card3: FOR FOS FOT MOR MOS MOT
    Card4: FFAILR FFAILS FFAILT MFAILR MFAILS MFAILT
    Card5: UFAILR UFAILS UFAILT TFAILR TFAILS TFAILT
    """
    mid: int
    rho: float = 0.0
    lcid: List[int] = field(default_factory=lambda: [0] * 6)
    lcid_damp: List[int] = field(default_factory=lambda: [0] * 6)
    preload: List[float] = field(default_factory=lambda: [0.0] * 6)
    ffail: List[float] = field(default_factory=lambda: [0.0] * 6)
    ufail: List[float] = field(default_factory=lambda: [0.0] * 6)


@dataclass
class MatDiscreteBeamNonlinearPlastic:
    """*MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM (MAT_068) → a 6-DOF spring
    property: K/C as MAT_066, plus the LCPD*/LCPM* yield curves on fct_ID1i
    with H_i = 1 (their abscissa is PLASTIC displacement and is converted to
    the TOTAL displacement Radioss wants).

    Card1: MID RO TKR TKS TKT RKR RKS RKT
    Card2: TDR TDS TDT RDR RDS RDT RYLD     (RYLD only from Keyword971_R12.0)
    Card3: LCPDR LCPDS LCPDT LCPMR LCPMS LCPMT
    Card4: FFAILR FFAILS FFAILT MFAILR MFAILS MFAILT
    Card5: UFAILR UFAILS UFAILT TFAILR TFAILS TFAILT
    Card6: FOR FOS FOT MOR MOS MOT
    """
    mid: int
    rho: float = 0.0
    k: List[float] = field(default_factory=lambda: [0.0] * 6)
    c: List[float] = field(default_factory=lambda: [0.0] * 6)
    ryld: float = 0.0
    lcp: List[int] = field(default_factory=lambda: [0] * 6)
    ffail: List[float] = field(default_factory=lambda: [0.0] * 6)
    ufail: List[float] = field(default_factory=lambda: [0.0] * 6)
    preload: List[float] = field(default_factory=lambda: [0.0] * 6)


@dataclass
class MatCableDiscreteBeam:
    """*MAT_CABLE_DISCRETE_BEAM (MAT_071) → a tension-only 1-DOF spring
    (/PROP/TYPE13, Ileng=1): K1 = |E| when E < 0, else E·CA from the
    *SECTION_BEAM card 2f, and a 3-point (-1,0)(0,0)(1,K) force function
    carrying the initial tension F0 as its y offset.

    ``LCID`` is a STRESS-vs-engineering-strain curve, not a force curve
    ("The points on the load curve are defined as engineering stress versus
    engineering strain", Manual Vol II R17 p.2-530), so its ordinates are
    multiplied by CA on the way to the /FUNCT; ``F0`` is a FORCE and is added
    after that. Both ends are then clamped at zero force — the whole point of
    the material is that "no force will develop in compression" (p.2-529).

    Card1: MID RO E LCID F0 TMAXF0 TRAMP IREAD
    Card2 (IREAD > 0): OUTPUT [TSTART [FRACL0 MXEPS MXFRC]] — never converted.
    """
    mid: int
    rho: float = 0.0
    e: float = 0.0
    lcid: int = 0
    f0: float = 0.0
    tmaxf0: float = 0.0
    tramp: float = 0.0
    iread: int = 0


@dataclass
class MatElasticSpringDiscreteBeam:
    """*MAT_ELASTIC_SPRING_DISCRETE_BEAM (MAT_074) → a 1-DOF spring
    (/PROP/TYPE13): K→K1, D→C1, -CDF→DeltaMin1, TDF→DeltaMax1,
    FLCID→fct_ID11, HLCID→fct_ID21, DLE→D1, C2→B1, C1→E1.

    Card1: MID RO K F0 D CDF TDF
    Card2: FLCID HLCID C1 C2 DLE GLCID
    """
    mid: int
    rho: float = 0.0
    k: float = 0.0
    f0: float = 0.0
    d: float = 0.0
    cdf: float = 0.0
    tdf: float = 0.0
    flcid: int = 0
    hlcid: int = 0
    c1: float = 0.0
    c2: float = 0.0
    dle: float = 0.0
    glcid: int = 0


@dataclass
class MatGeneralNonlinear6dof:
    """*MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM (MAT_119) → a 6-DOF spring
    property: fct_ID1i loading, fct_ID3i unloading, fct_ID4i damping;
    K1..3 = KT, K4..6 = KR; +UTFAIL*/WTFAIL* and -UCFAIL*/-WCFAIL* limits;
    H_i from IUNLD.

    Card1: MID RO KT KR IUNLD OFFSET DAMPF IFLAG
    Card2: LCIDTR LCIDTS LCIDTT LCIDRR LCIDRS LCIDRT   (loading)
    Card3: LCIDTUR … LCIDRUT                            (unloading)
    Card4: LCIDTDR … LCIDRDT                            (damping)
    Card5: LCIDTER … LCIDRET                            (elastic/scale)
    Card6: UTFAILR … WTFAILT FCRIT
    Card7: UCFAILR … WCFAILT
    Card8: IUR IUS IUT IWR IWS IWT
    Cards 9-15 exist only for IFLAG=2 / IUNLD=2 and are not modelled by the
    shipped Keyword971 cfg — parsed positionally per Manual R17.
    """
    mid: int
    rho: float = 0.0
    kt: float = 0.0
    kr: float = 0.0
    iunld: int = 0
    offset: float = 0.0
    dampf: float = 0.0
    iflag: int = 0
    lcid: List[int] = field(default_factory=lambda: [0] * 6)
    lcid_unld: List[int] = field(default_factory=lambda: [0] * 6)
    lcid_damp: List[int] = field(default_factory=lambda: [0] * 6)
    lcid_elast: List[int] = field(default_factory=lambda: [0] * 6)
    utfail: List[float] = field(default_factory=lambda: [0.0] * 6)
    ucfail: List[float] = field(default_factory=lambda: [0.0] * 6)
    fcrit: float = 0.0


@dataclass
class MatGeneralNonlinear1dof:
    """*MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM (MAT_121) → a 1-DOF spring:
    K→K1, LCIDT→fct_ID11, LCIDTU→fct_ID31, LCIDTD→fct_ID41,
    UTFAIL→DeltaMax1, -UCFAIL→DeltaMin1, H1 from IUNLD.

    Card1: MID RO K IUNLD OFFSET DAMPF
    Card2: LCIDT LCIDTU LCIDTD LCIDTE
    Card3: UTFAIL UCFAIL IU
    """
    mid: int
    rho: float = 0.0
    k: float = 0.0
    iunld: int = 0
    offset: float = 0.0
    dampf: float = 0.0
    lcidt: int = 0
    lcidtu: int = 0
    lcidtd: int = 0
    lcidte: int = 0
    utfail: float = 0.0
    ucfail: float = 0.0


@dataclass
class MatGeneralSpringDiscreteBeam:
    """*MAT_GENERAL_SPRING_DISCRETE_BEAM (MAT_196) → a 6-DOF spring property
    built from the per-DOF card PAIRS: each pair names its own DOF (1..6) and
    fills that slot's K / C / B / D / DeltaMin / DeltaMax / E and functions.

    Card1: MID RO … MDFAIL DOSPOT  (the shipped cfg stops after RO)
    Card2i: DOF TYPE K D CDF TDF
    Card3i: FLCID HLCID C1 C2 DLE GLCID
    ``dofs`` is a list of (dof, type, k, d, cdf, tdf, flcid, hlcid, c1, c2,
    dle, glcid) in deck order.
    """
    mid: int
    rho: float = 0.0
    mdfail: int = 0
    dospot: int = 0
    dofs: List[tuple] = field(default_factory=list)


@dataclass
class MatSpotweld:
    """*MAT_SPOTWELD (MAT_100) on beam elements → /PROP/TYPE13 (SPR_BEAM)
    2-node /SPRING connectors (per-DOF stiffness from E,G + the beam section,
    Ifail=1/Ifail2=2 quadratic force/moment failure surface from card 2).

    Card1: MID RO E PR SIGY EH DT TFAIL;  Card2: EFAIL NRR NRS NRT MRR MSS MTT NF.
    /MAT/LAW59 (CONNECT) was considered and rejected: it binds to /PROP/TYPE43
    8-node connection solids, not to 2-node spring elements.
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    sigy: float
    et: float           # EH: plastic hardening modulus
    dt: float           # time step for mass scaling (dropped, warned)
    tfail: float        # failure time (dropped, warned)
    efail: float        # effective plastic strain at failure (dropped, warned)
    nrr: float          # axial (tension) failure force  → DeltaMax1
    nrs: float          # shear failure force (s)        → ±Delta2
    nrt: float          # shear failure force (t)        → ±Delta3
    mrr: float          # torsion failure moment         → ±Delta4
    mss: float          # bending failure moment (s)     → ±Delta5
    mtt: float          # bending failure moment (t)     → ±Delta6
    nf: float = 0.0     # force-filter count (dropped, warned)


@dataclass
class ConstrainedSpotweld:
    """A *CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT WITH failure
    forces → a stiff /PROP/TYPE13 /SPRING with Ifail2=2 force criteria.
    (The no-failure flavour is turned into a 2-node CNRB at parse time and never
    lands here.)  Node-pair welds set n1/n2; NSID-based welds set nsid and are
    resolved to a pair at write time.

    Card (Keyword971_R6.1 constrained_spotweld.cfg):
        N1 N2 SN SS N M TF EP
      sn/ss = normal/shear failure force, n/m = failure exponents,
      tf = failure time (dropped), ep = plastic failure strain (dropped).
    """
    n1: int = 0
    n2: int = 0
    nsid: int = 0
    sn: float = 0.0
    ss: float = 0.0
    n: float = 2.0
    m: float = 2.0
    tf: float = 0.0
    ep: float = 0.0
    title: str = ""


#: LS-DYNA *CONSTRAINED_JOINT_<KIND> → the /PROP/TYPE45 ``Type`` integer.
#: Verified against prop_p45_kjoint2.cfg lines 261-272 (1 Spherical, 2 Revolute,
#: 3 Cylindrical, 4 Planar, 5 Universal, 6 Translational, 7 Oldham, 8 Fixed,
#: 9 Free) and against dyna2rad's own dispatch (convertconstrainedjoints.cxx
#: 1613/1640/1666/1692/1718/1744/1770). LOCKING → 8 (rigid), NOT 7 (Oldham):
#: Oldham is a planar joint without rotation and has no LS-DYNA counterpart.
JOINT_TYPE45 = {
    "SPHERICAL": 1,
    "REVOLUTE": 2,
    "CYLINDRICAL": 3,
    "PLANAR": 4,
    "UNIVERSAL": 5,
    "TRANSLATIONAL": 6,
    "LOCKING": 8,
}

#: Which LS-DYNA card-1 node slots become the /SPRING node list, per joint kind
#: (1-based LS-DYNA slot numbers). The solver builds the joint frame from these
#: (rini45.F GET_SKEW45), so the order is load-bearing:
#:   3 nodes  → local x = spring node 3 − node 1
#:   4 nodes, Type≠5 → x = n3−n1, ȳ = n4−n1
#:   4 nodes, Type=5 → y = n3−n1, z = n4−n1, x = y×z
#: LOCKING forwards N5 (body A's second auxiliary node) into slot 4 — N4/N6
#: (body B) are dropped, exactly as dyna2rad does (joints.cxx 1630-1631).
JOINT_SPRING_SLOTS = {
    "SPHERICAL": (1, 2),
    "REVOLUTE": (1, 2, 3),
    "CYLINDRICAL": (1, 2, 3),
    "PLANAR": (1, 2, 3),
    "UNIVERSAL": (1, 2, 3, 4),
    "TRANSLATIONAL": (1, 2, 3),
    "LOCKING": (1, 2, 3, 5),
}

#: Minimum node count the starter requires per /PROP/TYPE45 Type — rini45.F:391
#: ``NNOD_REQ = [2, 3, 3, 3, 4, 3, 3, 2, 4]`` for Types 1..9. Falling below it
#: with Skew_ID1 = 0 is starter ERROR 936.
JOINT_NNOD_REQ = {1: 2, 2: 3, 3: 3, 4: 3, 5: 4, 6: 3, 7: 3, 8: 2, 9: 4}

#: Free DOFs per /PROP/TYPE45 Type, in the exact order the reader expects the
#: 3-card DOF blocks (prop_p45_kjoint2.cfg FORMAT(radioss2019) lines 925-1224 /
#: hm_read_prop45.F LEC_DOF_JNT call order). The blocks are all-or-nothing: a
#: partial set is starter ERROR 973 (ONLY %d DOF DEFINED %d REQUIRED).
JOINT_TYPE45_DOFS = {
    1: ("Rx", "Ry", "Rz"),
    2: ("Rx",),
    3: ("Tx", "Rx"),
    4: ("Ty", "Tz", "Rx"),
    5: ("Ry", "Rz"),
    6: ("Tx",),
    7: ("Ty", "Tz"),
    8: (),
    9: ("Tx", "Ty", "Tz", "Rx", "Ry", "Rz"),
}


@dataclass
class ConstrainedJoint:
    """*CONSTRAINED_JOINT_<KIND>[_LOCAL][_FAILURE][_ID|_TITLE] → one synthesized
    /PART + /PROP/TYPE45 (KJOINT2) + one 2..4-node /SPRING per joint.

    Card 1 (all fields 10 wide): ``N1 N2 N3 N4 N5 N6 RPS DAMP``.
    N1/N3/N5 belong to rigid body A, N2/N4/N6 to body B; the pairs (1,2), (3,4),
    (5,6) are coincident by design — except UNIVERSAL, where (3,4) are not and
    lines (1,3) ⟂ (2,4). Coincidence is never checked or enforced (dyna2rad does
    not either: there is no GetPosition() comparison anywhere on that path).

    /PROP/TYPE13 (SPR_BEAM) was considered and rejected: it is a 6-DOF penalty
    spring with no kinematic DOF selector and no joint frame, so a revolute
    joint would need a stiff/soft split per DOF that still would not track the
    axis as the bodies rotate. /PROP/TYPE45 IS the joint property — it blocks
    the constrained DOFs with a solver-computed stiffness (Kn=0 → auto from the
    time step) and leaves exactly the joint's free DOFs.
    """
    kind: str                   # SPHERICAL | REVOLUTE | ... (option suffixes stripped)
    keyword: str = ""           # the full LS-DYNA keyword, for messages
    jid: int = 0                # _ID / _TITLE id; 0 when the card carries none
    title: str = ""
    n1: int = 0
    n2: int = 0
    n3: int = 0
    n4: int = 0
    n5: int = 0
    n6: int = 0
    rps: float = 1.0            # relative penalty stiffness → /PROP/TYPE45 ScF
    damp: float = 1.0           # damping scale (no Radioss counterpart, warned)
    has_local: bool = False     # _LOCAL: RAID/LST output frame (dropped, warned)
    has_failure: bool = False   # _FAILURE: CID/TFAIL/COUPL + N**/M** (dropped)

    def uses_n4_as_axis(self) -> bool:
        """True when N3 is blank and N4 stands in for it as the axis node.

        ``*CONSTRAINED_JOINT_CYLINDRICAL`` with N3 = 0 is a DOCUMENTED
        configuration — R16 Vol I p.10-62: "For cylindrical joints, by setting
        node 3 to zero, it is possible to use a cylindrical joint to join a node
        that is not on a rigid body (node 1) to a rigid body (nodes 2 and 4)."
        Since the nodal pair (3, 4) coincides in the initial configuration for
        every kind except UNIVERSAL, N4 gives exactly the axis N3 would have,
        and using it turns a guaranteed starter ERROR 936 (2-node spring on a
        Type that needs 3) into the intended joint."""
        return (JOINT_SPRING_SLOTS.get(self.kind, (1, 2)) == (1, 2, 3)
                and self.n3 <= 0 < self.n4)

    def spring_nodes(self) -> List[int]:
        """The /SPRING node list for this joint kind, gaps compacted away.

        GET_SKEW45 compacts non-zero IXR/IXR_KJ slots before building the frame,
        so a hole would silently shift NN(3)/NN(4) — the list must be written
        contiguously (card-format spec §2, trap 2)."""
        slots = JOINT_SPRING_SLOTS.get(self.kind, (1, 2))
        if self.uses_n4_as_axis():
            slots = (1, 2, 4)
        vals = (0, self.n1, self.n2, self.n3, self.n4, self.n5, self.n6)
        return [vals[s] for s in slots if vals[s] > 0]


@dataclass
class JointStiffness:
    """*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED / _TRANSLATIONAL → the DOF
    stiffness / damping / friction / stop blocks of a joint's /PROP/TYPE45.

    Card 1: ``JSID PIDA PIDB CIDA CIDB JID [RPS]`` (RPS is a later addition —
    the bundled Keyword971 cfg writes only six fields, so it is optional).
    The three option cards carry one triple per channel:
      GENERALIZED   φ/θ/ψ  — LCIDPH/LCIDT/LCIDPS, DLCID*, ESPH/EST/ESPS,
                             FMPH/FMT/FMPS, NSA*/PSA* stop ANGLES in DEGREES
      TRANSLATIONAL x/y/z  — LCIDX/Y/Z, DLCID*, ESX/ESY/ESZ, FFX/FFY/FFZ,
                             NSD*/PSD* stop DISPLACEMENTS
    A negative FM*/FF* means ``-FM*`` is a curve id for the yield moment/force;
    in Radioss that is the separate fct_fm*/fct_ff* field.
    """
    option: str                 # GENERALIZED | TRANSLATIONAL
    jsid: int = 0
    pida: int = 0
    pidb: int = 0
    cida: int = 0
    cidb: int = 0
    jid: int = 0
    rps: float = 0.0
    title: str = ""
    # Per-channel triples, index 0/1/2 = φ,θ,ψ (GENERALIZED) or x,y,z (TRANS).
    lcid: Tuple[int, int, int] = (0, 0, 0)      # stiffness curve
    dlcid: Tuple[int, int, int] = (0, 0, 0)     # damping curve
    es: Tuple[float, float, float] = (0.0, 0.0, 0.0)    # elastic stop stiffness
    fm: Tuple[float, float, float] = (0.0, 0.0, 0.0)    # friction limit (<0 = curve)
    nstop: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # negative stop
    pstop: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # positive stop
    # TRANSLATIONAL card 2c.3 fields 7-8: static / dynamic friction COEFFICIENTS
    # (dimensionless). /PROP/TYPE45 expresses friction only as an absolute
    # force/moment limit, so these cannot be carried across — warned, not
    # silently dropped.
    fs: float = 0.0
    fd: float = 0.0


@dataclass
class PartData:
    pid: int
    title: str
    secid: int
    mid: int
    # *PART field 5 (HGID) → the *HOURGLASS card that overrides
    # *CONTROL_HOURGLASS for this part. 0 = use the global card / defaults.
    hgid: int = 0
    # *PART field 4 (EOSID) → the *EOS_* card bound to this part's material.
    # 0 = none. Drives the *MAT_JOHNSON_COOK LAW2-vs-LAW4 routing (dyna2rad's
    # law choice is triggered solely by a nonzero part EOSID) and the
    # *MAT_NULL /MAT/LAW6-carrier pairing for an EOS of a different id.
    eosid: int = 0


@dataclass
class SectionShell:
    secid: int
    title: str
    elform: int
    nip: int
    t1: float
    # *SECTION_SHELL card 1 field 7 (cols 61-70). ICOMP=1 declares a LAYERED
    # orthotropic/anisotropic composite section: "A material angle in degrees is
    # defined for each through-thickness integration point. Thus, each layer has
    # one integration point" (Manual Vol I R17 p.41-67). The angles ride on the
    # card-3 angle cards below.
    icomp: int = 0
    # The B_i material angles in DEGREES, bottom layer first, one per
    # through-thickness integration point — *SECTION_SHELL card 3, eight values
    # per card, ceil(NIP/8) cards (Manual Vol I R17 p.41-70). Empty unless
    # ICOMP=1. They are measured FROM the material's own AOPT/BETA reference
    # direction, so they add to it rather than replacing it — the same
    # convention *PART_COMPOSITE's per-ply B_i uses.
    betas: List[float] = field(default_factory=list)
    # *SECTION_SHELL card 1 field 6 (cols 51-60), the shared QR/IRID cell. The
    # field is a FLOAT and its SIGN is the selector: >= 0.0 is the built-in
    # quadrature rule QR (0 = Gauss/Lobatto, 1 = trapezoidal), < 0.0 makes |QR|
    # the id of a user *INTEGRATION_SHELL rule — "Quadrature rules in the
    # *SECTION_SHELL and *SECTION_BEAM cards need to be specified as a negative
    # number.  The absolute value of the negative number refers to user defined
    # integration rule number" (Manual Vol I R17 p.29-1). 0 = no rule.
    #
    # NOTE this is field 6, NOT the NIP field 4: dyna2rad encodes the same cell
    # as SCALAR_OR_OBJECT(Sect_Option, LSD_QR, LSD_IRID) (SectShll.cfg:699) and
    # picks the object branch on the sign alone (meci_data_reader.cpp:6847).
    irid: int = 0


@dataclass
class IntegrationPoint:
    """One *INTEGRATION_SHELL card-2 point: S WF PID (Vol I R17 p.29-16).

    ``s``   through-thickness coordinate, -1 (bottom) .. +1 (top), 0 = the
            mid-surface. A quadrature SAMPLING coordinate, not a slab edge.
    ``wf``  weighting factor, i.e. the thickness fraction Delta_t_i / t this
            point accounts for (p.29-17). LS-DYNA's convention is that the WF
            sum to 1, but nothing enforces it, so k2rad normalizes by the sum
            exactly as dyna2rad does (convertprops.cxx:1993-1996).
    ``pid`` optional *PART id supplying this layer's MATERIAL (and density)
            only; 0/blank = the element's own part material. The referenced
            part's own section, thickness and orientation are NOT consulted.
    """
    s: float = 0.0
    wf: float = 0.0
    pid: int = 0


@dataclass
class IntegrationShell:
    """*INTEGRATION_SHELL — a user through-thickness integration rule, bound
    from a *SECTION_SHELL whose card-1 field 6 (QR/IRID) is negative.

    Card 1 is ``IRID NIP ESOP FAILOPT``; card 2 repeats ``S WF PID`` NIP times
    and exists only when ``ESOP == 0`` (Vol I R17 p.29-16, and the CFG guard
    ``if(ESOP == 0 && NIP > 0)`` in INTEGRATION_RULES/integration_shell.cfg).

    ``nip`` defaults to 0 — the CFG's ``DEFAULTS(COMMON){ NIP = 0; }`` and NOT
    *SECTION_SHELL's 2.0; the manual prints no Default row for this card at all.
    A rule with NIP = 0 defines nothing and is warn-dropped.

    ``esop`` = 1 means NIP layers of EQUAL thickness with no point cards.

    ``failopt`` has no Radioss counterpart (TYPE11 carries one global
    P_Thick_Fail, not a per-layer failure policy) and is warn-dropped; dyna2rad
    never reads the field at all.
    """
    irid: int
    nip: int = 0
    esop: int = 0
    failopt: int = 0
    points: List[IntegrationPoint] = field(default_factory=list)


@dataclass
class SectionTshell:
    """*SECTION_TSHELL → /PROP/TYPE20 (TSHELL) | TYPE21 (TSH_ORTH) | TYPE22
    (TSH_COMP).

    Card 1 is ``SECID ELFORM SHRF NIP PROPT QR ICOMP TSHEAR`` (8 x I10,
    ``Keyword971/PROPERTY/SectTShl.cfg:141``); card 2 is the ICOMP=1 angle
    block, eight ``B_i`` per card over ``ceil(NIP/8)`` cards. There is NO
    thickness field anywhere on this keyword — a thick shell's thickness is the
    distance between its n1-n4 and n5-n8 faces, i.e. pure mesh.

    ``elform`` defaults to LS-DYNA's own 1 for a blank field, NOT to 0. That is
    a deliberate divergence from dyna2rad, which reads a blank as 0 and lands on
    the ``else`` of its ``elform == 1 ? 15 : 14`` test — giving a deck that
    asked for the DEFAULT one-point form the FULL-integration HA8 instead.

    ``nip`` likewise defaults to 2 ("EQ.0: set to 2 integration points", Vol I
    R16 p.3717) rather than dyna2rad's 0, which produces ``Inpts_S`` clamped to
    1 against a ply list of length 0 → starter ERROR 675.

    ``irid`` is ``|QR|`` when the QR cell is negative (an *INTEGRATION_SHELL
    reference, Vol I R16 p.29-1). Radioss thick shells take no user quadrature
    rule, so it is warn-dropped — but recorded, so the warning can name it.
    """
    secid: int
    title: str = ""
    elform: int = 1
    shrf: float = 0.0
    nip: int = 2
    propt: float = 0.0
    qr: float = 0.0
    icomp: int = 0
    tshear: int = 0
    #: The card-2 B_i material angles in DEGREES, bottom layer first, one per
    #: through-thickness integration point. Empty unless ICOMP=1.
    betas: List[float] = field(default_factory=list)
    irid: int = 0
    #: True when the deck left ELFORM blank (so the divergence note above can
    #: be reported per section rather than guessed at from the value 1).
    elform_blank: bool = False


@dataclass
class SectionSph:
    """*SECTION_SPH (+ _ELLIPSE / _TENSOR / _INTERACTION / _USER) → /PROP/SPH
    (= /PROP/TYPE34).

    Card 1 is ``SECID CSLH HMIN HMAX SPHINI DEATH START SPHKERN`` (8 x I10,
    ``Keyword971_R11.1/PROPERTY/SectSPH.cfg`` FORMAT(Keyword971_R11.1)).

    **Every non-zero default below is applied HERE, by the parser, not left to
    the reader.** That is a deliberate divergence from dyna2rad, and the biggest
    single behavioural finding of this batch: the CFG declares
    ``DEFAULTS(COMMON){ LSD_CSLH = 1.2; LSD_HMIN = 0.2; LSD_HMAX = 2.0;
    LSD_TDEATH = 1.0e20; }`` but the SDI read path does NOT apply them, so a
    blank ``CSLH`` reaches ``p_ConvertSectionSph`` as 0 and takes the
    ``lsdCSLH > 0`` branch's ``else`` — i.e. a deck that left CSLH blank to get
    the manual's 1.2 is converted to a CONSTANT smoothing length with SPHINI
    discarded (measured on probe decks h/i: ``CONSTANT SMOOTHING LENGTH`` and
    ``SMOOTHING LENGTH AUTOMATICALLY COMPUTED``).

    ``cslh_blank`` records that the deck left the cell empty, so the report can
    say which value it is talking about rather than guessing from 1.2.

    ``sphkern`` is READ but never mapped. dyna2rad turns ``SPHKERN == 2`` into
    ``/PROP/SPH ORDER = 2``, which is wrong twice over: Radioss's ``Order`` is
    the renormalisation CORRECTION order, not a kernel-polynomial order, and 2
    is out of range — ``spcompl.F:107-118`` dispatches only on -1/0/1, so an
    Order=2 particle silently gets no kernel correction at all, and
    ``spgrhead.F:180-185`` packs the value into two bits of the group-sort key.
    (dyna2rad's map is unreachable anyway: the R11.1 IMPORT card reads seven
    fields, so SPHKERN is never populated on its read path — verified, a
    ``SPHKERN=2`` deck echoed ``FORMULATION CORRECTION ORDER = 0``.)
    """
    secid: int
    title: str = ""
    #: Scale on the initial smoothing length, LS-DYNA default 1.2 (Vol I R16:
    #: "Values between 1.05 and 1.3 are acceptable. Taking a value less than 1
    #: is inadmissible").
    cslh: float = 1.2
    hmin: float = 0.2          # scale factor for the MINIMUM smoothing length
    hmax: float = 2.0          # scale factor for the MAXIMUM smoothing length
    #: "Optional initial smoothing length (overrides true smoothing length).
    #: With this option LS-DYNA will not calculate the smoothing length during
    #: initialization, and the field CSLH is ignored." 0 = not given.
    sphini: float = 0.0
    death: float = 1.0e20      # time the SPH approximation is STOPPED
    start: float = 0.0         # time the SPH approximation is ACTIVATED
    sphkern: int = 0           # 0 cubic / 1 quintic / 2 quadratic / 3 quartic
    #: True when the deck left CSLH empty (so the divergence above can be
    #: reported per section rather than inferred from the value 1.2).
    cslh_blank: bool = False
    #: The keyword suffix this section came from ("", "ELLIPSE", "TENSOR",
    #: "INTERACTION", "USER") — every one of them but the bare spelling loses
    #: data, and the report names which.
    option: str = ""


@dataclass
class SphProp:
    """The resolved /PROP/SPH payload for one *SECTION_SPH, decided ONCE in the
    ``_resolve_sph`` prepass and read by both emitters.

    Radioss can express a particle's mass in exactly two places and they are
    MUTUALLY EXCLUSIVE by construction, because the one that carries the mass
    also decides the smoothing length (``spinih.F:85-109``):

    * ``per_cell = True``  — every ``/SPHCEL`` row carries its own Flag+MASS.
      The mass is exact per particle whatever the deck says, and Radioss
      OVERWRITES the property's ``h`` with ``(sqrt(2)*m_p/rho)^(1/3)``. The
      deck's own ``SPHINI`` / ``CSLH*d_ref`` cannot be honoured.
    * ``per_cell = False`` — the ``/SPHCEL`` MASS column is left blank (Flag 0,
      "type 0"), every particle takes ``mass = Mp`` from the property, and the
      property's ``h`` is used verbatim. Only usable when the section's
      particles all carry the IDENTICAL mass, and then the total is exact too
      (``N * Mp``) while ``h`` matches LS-DYNA's own.

    ``mp`` is ALWAYS positive on both routes: ``hm_read_prop34.F:235-239``
    raises WARNING 138 and forces ``MP = 1`` in the deck's mass unit for any
    ``Mp <= 0``, which on the per-cell route is merely noisy but on a TYPE-0
    particle fabricates a whole mass unit per particle (measured: four blank-mass
    particles gave ``TOTAL MASS = 4.0``). dyna2rad never writes the field at all.
    """
    secid: int
    prop_id: int
    title: str = ""
    #: /PROP/SPH Mp — the property-level particle mass. Always > 0.
    mp: float = 1.0
    #: /PROP/SPH h — the smoothing length, 0 = "compute automatically".
    h: float = 0.0
    #: /PROP/SPH h_1D — 0 (3D dilatation), 1 (1D), 2 (constant h). NEVER 3 at
    #: /BEGIN 2022: the hmin/hmax/hcst bounds that branch needs live on a
    #: radioss2026-only third card, which a 2022 reader discards SILENTLY
    #: (measured: hmin 0.37 / hmax 3.77 / hcst 1.77 echoed as 0.2 / 2.0 / 1.2,
    #: 0 ERRORS, only advisory WARNING 100213), leaving the bounded-dilatation
    #: algorithm running with bounds nobody chose.
    h_1d: int = 0
    #: True when each /SPHCEL row states its own mass (see above).
    per_cell: bool = True
    #: Where ``h`` came from, for the report ("" when h is left automatic).
    h_source: str = ""
    #: Where ``mp`` came from. ``"deck"`` = a mass (or a volume x rho) the
    #: *ELEMENT_SPH cards actually state; ``"geometry"`` = rho x d_ref**3,
    #: derived because NO particle of the section states a mass at all;
    #: ``"fabricated"`` = neither was available and 1.0 had to be written to
    #: keep the property legal. The last two are the cases where the emitted
    #: deck holds a mass the SOURCE never stated, so every report keyed on this
    #: says so instead of quoting derived numbers as if they were the deck's.
    mp_source: str = "deck"


@dataclass
class ControlSph:
    """*CONTROL_SPH — the global SPH controls.

    Card 1 ``NCBS BOXID DT IDIM NMNEIGH FORM START MAXV`` (8 x I10; older decks
    and LS-PrePost label column 5 ``memory``), card 2 ``CONT DERIV INI ISHOW
    IEROD ICONT IAVIS ISYMP``, card 3 ``ITHK ISTAB QL - SPHSORT ISHIFT``. Cards
    2 and 3 are OPTIONAL and are claimed by RAW CONTIGUITY (the #119 rule), not
    by "the next non-blank row": an all-blank card 2 is a legal card and taking
    the following non-blank line instead would read the NEXT keyword's data.

    Exactly one column has a Radioss home: ``nmneigh`` → ``/SPHGLO``
    ``Lneigh``/``Nneigh``. Everything else is dropped, and
    ``writer/sph.py::_warn_control_sph`` names every one of them. dyna2rad
    drops the whole keyword silently — the string ``CONTROL_SPH`` does not
    occur anywhere under ``reader/source/dyna2rad/``.
    """
    ncbs: int = 1              # time steps between particle sorting
    boxid: int = 0             # *DEFINE_BOX outside which particles deactivate
    dt: float = 1.0e20         # death time for the SPH calculation
    idim: int = 3              # 3 = 3D, 2 = 2D plane strain, -2 = axisymmetric
    nmneigh: int = 0           # initial neighbours per particle (LS-DYNA 150)
    form: int = 0              # particle approximation theory
    start: float = 0.0         # start time for particle approximation
    maxv: float = 0.0          # velocity magnitude above which a particle dies
    # Card 2
    cont: int = 0
    deriv: int = 0
    ini: int = 0               # 0 bucket sort / 1 global / 2 from particle MASS
    ishow: int = 0
    ierod: int = 0
    icont: int = 0
    iavis: int = 0
    isymp: int = 0
    # Card 3
    ithk: int = 0
    istab: int = 0
    ql: float = 0.0
    sphsort: int = 0
    ishift: int = 0
    #: How many of the three cards the deck actually wrote.
    n_cards: int = 1


@dataclass
class SectionSolid:
    secid: int
    title: str
    elform: int
    # ALE/Euler flag for /PROP/SOLID field 3 (Iale): 0 Lagrange, 1 ALE, 2 Euler.
    # LS-DYNA *SECTION_SOLID ELFORM 11 (1-pt ALE multi-material) / 12 (1-pt ALE
    # single material) set this to 1.
    iale: int = 0
    # *SECTION_SOLID_MISC card 2c COHTHK: a section-wise cohesive-thickness
    # override (supersedes *MAT_240 THICK in LS-DYNA) → /PROP/TYPE43
    # True_thickness, its exact Radioss analogue. 0 = element geometric height.
    cohthk: float = 0.0


@dataclass
class SectionBeam:
    secid: int
    title: str
    elform: int
    area: float = 0.0
    iyy: float = 0.0
    izz: float = 0.0
    ixx: float = 0.0
    ts1: float = 0.0   # integrated beam thickness (elform=1)
    # *SECTION_BEAM card 2a/2e/2h (ELFORM 0/1/4/5/7/8/9/11) — the cross-section
    # thicknesses at node 1 and node 2, in the beam's local s and t directions
    # (Manual Vol I R17 p.41-11). ``ts1``/``ts2`` are the s-direction thickness
    # at node 1 / node 2 and ``tt1``/``tt2`` the t-direction pair, so the
    # PRISMATIC section of an integrated beam is ts1 x tt1 — NOT ts1 x ts2,
    # which is dyna2rad's L1<-TS1 / L2<-TS2 map (convertprops.cxx:1274-1275)
    # and reads a taper as a depth.
    #
    # On ELFORM=9 (spot weld) the same four cells are card 2i, Manual Vol I R17
    # p.41-22/23: TS1 TS2 TT1 TT2 PRINT - ITOFF -, where TS is the beam
    # thickness (CST=0/2) or OUTER diameter (CST=1) and TT the thickness or
    # INNER diameter at node n1 / n2. There is no volume and no area on that
    # card — VOL/INER/CID/CA is card 2f, which belongs to the ELFORM=6
    # DISCRETE beam.
    ts2: float = 0.0
    tt1: float = 0.0
    tt2: float = 0.0
    # Card 2i field 7 (ELFORM=9 only): 1 = torsional stiffness of the spot
    # weld is zero.
    itoff: int = 0
    # Card 2a fields 5/6: where the beam's reference axis (the node line) sits
    # inside the +/-1 s-t square. Both default to 0 = the section centre.
    nsloc: float = 0.0
    ntloc: float = 0.0
    # *SECTION_BEAM card 1 field 4 (cols 31-40), the shared QR/IRID cell — the
    # exact analogue of *SECTION_SHELL's field 6 (see SectionShell.irid). The
    # field is a FLOAT and its SIGN is the selector: >= 0.0 is a built-in
    # quadrature rule QR, < 0.0 makes |QR| the id of a user *INTEGRATION_BEAM
    # rule — "EQ.-n: |n| is the number of the user defined rule" (Vol I R17
    # p.41-4). 0 = no rule.
    #
    # ``qr`` keeps the built-in rule ONLY on the scalar branch: once QR is
    # negative the quadrature field is dead (dyna2rad's SCALAR_OR_OBJECT cell
    # force-zeroes the scalar on the object branch, meci_data_reader.cpp:7003),
    # so a converter that read it without checking the sign would see "QR = 0"
    # and silently pick the 2-point rectangular rule.
    irid: int = 0
    qr: float = 0.0
    # Card 1 field 5 (cols 41-50): cross-section type, 0 = rectangular,
    # 1 = tubular, 2 = arbitrary (defined by the *INTEGRATION_BEAM rule).
    cst: int = 0
    # Card 1 field 6 (cols 51-60), FLOAT: which node's angular velocity rotates
    # the DISCRETE-beam (ELFORM=6) triad. |SCOOR| = 2 additionally realigns the
    # local r-axis along n1→n2 — exactly Radioss's /PROP/TYPE13 (SPR_BEAM,
    # r4buf3.F) frame, and the same value dyna2rad tests to pick /MAT/LAW113
    # over /MAT/LAW108 (convertmats.cxx:3374). 0 = centred (default).
    scoor: float = 0.0
    # *SECTION_BEAM card 2f (ELFORM=6 DISCRETE beam), Manual Vol I R17 p.41-20:
    #   VOL INER CID CA OFFSET RRCON SRCON TRCON
    # SectBeam.cfg's COMMENT mislabels fields 4/5 as DOFN1/DOFN2 (that is card
    # 2g, the *MAT_146 dialect); its CARD spec binds LSD_CA / LSD_OFFSET, which
    # is what the manual says and what k2rad reads.
    vol: float = 0.0        # → spring Mass = RO·VOL (Imass=2 equivalent)
    iner: float = 0.0       # → spring Inertia; -1 = solid sphere of VOL, -2 = auto
    cid: int = 0            # *DEFINE_COORDINATE_* id → /SKEW (orientation)
    ca: float = 0.0         # cable area (MAT_071) → Mass = RO·CA·L
    cable_offset: float = 0.0   # cable offset (MAT_071) — no Radioss slot
    rrcon: float = 0.0      # rotational constraint about local r/s/t
    srcon: float = 0.0
    trcon: float = 0.0


@dataclass
class IntegrationBeamPoint:
    """One *INTEGRATION_BEAM quadrature card: S T WF PID (Vol I R17 p.29-2).

    ``s``/``t`` the NORMALIZED cross-section coordinates of the integration
            point, -1 .. +1 in each direction, measured in the beam's local s-t
            frame from the reference axis. They are quadrature SAMPLING
            coordinates, not sub-area corners, so the +/-1 square they span is
            the ``TS1`` x ``TT1`` rectangle of *SECTION_BEAM card 2a.
    ``wf``  weighting factor, i.e. the area fraction ``Ar_i = A_i / A`` this
            point accounts for (p.29-3). LS-DYNA's convention is that the WF
            sum to 1, but nothing enforces it, so k2rad normalizes by the sum
            exactly as dyna2rad's shell rule does (convertprops.cxx:1993-1996).
    ``pid`` optional *PART id whose material this cell uses; 0/blank = the
            *ELEMENT_BEAM's own part. /PROP/TYPE18 has ONE material for the
            whole section (prop_p18_int_beam.cfg has no per-point mat column),
            so a non-zero PID is warn-dropped.
    """
    s: float = 0.0
    t: float = 0.0
    wf: float = 0.0
    pid: int = 0


@dataclass
class IntegrationBeam:
    """*INTEGRATION_BEAM — a user cross-section integration rule, bound from a
    *SECTION_BEAM whose card-1 field 4 (QR/IRID) is negative.

    Card 1 is ``IRID NIP RA ICST K``. The two blocks that may follow are
    ADDITIVE, not exclusive: the reader takes one ``D1 D2 D3 D4 SREF TREF D5
    D6`` dimension card whenever ``ICST > 0`` and ``NIP`` ``S T WF PID`` cards
    whenever ``NIP != 0``, exactly as the manual's two independent card
    headings say (Vol I R17 p.29-2/3). The HyperMesh CFG gates the quadrature
    list on ``if(LSD_ICST == 0 && LSD_NIP > 0)`` and is WRONG about it — a rule
    with ICST>0 and NIP=2 that only supplies one trailing line makes the real
    reader swallow the next rule's header as the missing point card.

    ``ra`` relative area, ``A / (TS1 * TT1)``. Default 0.0, which makes every
    derived sub-area zero; there is no "1.0 means unscaled" default in the
    card, so a rule that omits it is reported rather than silently scaled.

    ``icst`` 0 = arbitrary (the point cards define the section), 1..22 = one of
    LS-DYNA's standard shapes, whose ``D1..D6`` ride on the dimension card.

    ``k`` integration refinement parameter (>= 0), meaningful for ICST > 0.

    ``sref``/``tref`` reference-axis offsets that OVERRIDE *SECTION_BEAM's
    NSLOC/NTLOC "even if SREF = 0" (p.29-2). Radioss has no equivalent column
    on /PROP/TYPE18, so a non-zero value is warn-dropped.

    dyna2rad converts NONE of this: the keyword is commented out of the R14.1
    data hierarchy (data_hierarchy.cfg:4244-4253) so the native reader drops the
    card silently, and the *SECTION_BEAM branch that would consume a rule is an
    empty stub awaiting "RD-6730" (convertprops.cxx:1343-1347). Everything here
    is net-new capability, not parity.
    """
    irid: int
    nip: int = 0
    ra: float = 0.0
    icst: int = 0
    k: int = 0
    # D1..D6 of the ICST > 0 dimension card, in card order. NOTE the card reads
    # D1 D2 D3 D4 SREF TREF D5 D6 — SREF/TREF sit BETWEEN D4 and D5.
    dims: List[float] = field(default_factory=list)
    sref: float = 0.0
    tref: float = 0.0
    points: List[IntegrationBeamPoint] = field(default_factory=list)


@dataclass
class IntBeamProp:
    """The resolved /PROP/TYPE18 payload for one *SECTION_BEAM + rule pair,
    produced by ``writer.beams._resolve_integration_beams`` and consumed by
    ``_emit_prop_int_beam``. Keyed by SECID: an integration rule hangs off the
    SECTION in LS-DYNA, so every *PART on that section gets the same integrated
    beam and no per-part /PROP split is needed.

    ``isect`` 0 = the user point cloud in ``points``; >= 10 = one of Radioss's
    predefined shapes, whose sizes are in ``l1``/``l2`` and whose point cloud
    the starter generates itself.
    """
    secid: int
    isect: int = 0
    nitrs: int = 0
    l1: float = 0.0
    l2: float = 0.0
    # (Y_IP, Z_IP, AREA_IP) per integration point, in ABSOLUTE local
    # coordinates and absolute area — Radioss does not take LS-DYNA's
    # normalized S/T or fractional WF.
    points: List[Tuple[float, float, float]] = field(default_factory=list)


@dataclass
class MatElastic:
    mid: int
    title: str
    rho: float
    E: float
    nu: float


@dataclass
class MatPlasTAB:
    """*MAT_PIECEWISE_LINEAR_PLASTICITY → /MAT/LAW36 (PLAS_TAB)."""
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    sigy: float
    etan: float
    fail: float
    lcss: int           # curve ID (0 = none)
    C: float            # Cowper-Symonds
    P: float
    eps_pts: List[float] = field(default_factory=list)
    es_pts: List[float] = field(default_factory=list)
    # resolved function ID (set by handlers during post-processing)
    funct_id: int = 0
    # LS-DYNA VP viscoplastic-formulation flag → LAW36 VP (radioss2017 cfg
    # N_funct card, cols 91-100). Only emitted when nonzero.
    vp: int = 0
    # Strain-rate function family → LAW36 N_funct>1: (fct_ID, Fscale, Eps_dot)
    # triples, ascending Eps_dot. Populated by the writer post-pass from either
    # an LCSS *DEFINE_TABLE or sampled rate curves; empty = single static curve.
    rate_fcts: List[Tuple[int, float, float]] = field(default_factory=list)
    # Pre-sampled hardening curves per strain rate, (eps_dot, [(eps_p, sigma)]),
    # filled by handle_mat_simplified_johnson_cook when C != 0. The writer
    # allocates /FUNCT ids for them and moves them into rate_fcts.
    rate_curves: List[Tuple[float, List[Tuple[float, float]]]] = \
        field(default_factory=list)
    # *MAT_123 (*MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY) card-2 extras. Stay
    # 0 for plain MAT_024, so the writer's /FAIL/TAB1+/FAIL/FLD trailers only
    # fire for MAT_123 and the base LAW36 emission is unchanged.
    epsthin: float = 0.0   # thinning strain at failure  → /FAIL/TAB1 P_THICKFAIL
    epsmaj: float = 0.0    # major in-plane strain at failure → /FAIL/FLD curve
    numint: float = 0.0    # IPs that must fail before deletion (0 = ALL)
    lcsr: int = 0          # LCSR strain-rate curve (no LAW36 slot; reported)
    # _LOG_INTERPOLATION keyword option → LAW36 F_smooth=2 (logarithmic rather
    # than linear interpolation between the strain-rate yield curves).
    log_interp: bool = False
    # Which LS-DYNA keyword family filled this record. The base LAW36 card is
    # identical for all of them — only the FAILURE trailer and the LCSR
    # handling differ, so the writer dispatches on this instead of sniffing
    # fields. "024" also covers *MAT_POWER_LAW-style callers that leave every
    # extra field at 0, so nothing about the MAT_024/098/123 output moves.
    family: str = "024"    # "024" | "123" | "098" | "081" | "082" | "105"
    # *MAT_PLASTICITY_WITH_DAMAGE (081/082) card fields. EPPF/EPPFR are the
    # softening-onset and rupture plastic strains → the /FAIL/TAB1 TABLE2/TABLE1
    # pair; LCDM (nonlinear damage curve) and TDEL have no Radioss slot.
    eppf: float = 0.0
    eppfr: float = 0.0
    lcdm: int = 0
    tdel: float = 0.0
    # True for *MAT_082 / the _ORTHO option: the damage evolution is directional.
    # LAW36 + /FAIL/TAB1 is isotropic, so the base material still converts and
    # only the directionality is reported as dropped.
    ortho_damage: bool = False
    # *MAT_DAMAGE_2 (105) card 3 — the Lemaitre continuum-damage constants,
    # a 1:1 /FAIL/LEMAITRE triple (EPSD → EPS_D, S → S_D, DC → DC).
    epsd: float = 0.0
    damage_s: float = 0.0
    dc: float = 0.0


@dataclass
class MatPlasCompTens:
    """*MAT_PLASTICITY_COMPRESSION_TENSION (124) → /MAT/LAW66.

    Separate yield curves in tension and compression (``lcidt``/``lcidc``)
    blended over the mean-stress band ``PT``..``PC``, Cowper-Symonds or
    per-branch rate-scaling curves, an optional 6-term Prony viscoelastic
    branch and a plastic-strain / rate-curve failure criterion.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    E: float = 0.0
    nu: float = 0.0
    c: float = 0.0        # Cowper-Symonds C → LAW66 Epsilon_0 (reference rate)
    p: float = 0.0        # Cowper-Symonds P → LAW66 c (the 1/p exponent)
    fail: float = 0.0     # >0 plastic strain to failure, <0 user subroutine
    tdel: float = 0.0
    lcidc: int = 0        # compression yield curve → funct_IDc
    lcidt: int = 0        # tension yield curve     → funct_IDt
    lcsrc: int = 0        # compression rate-scaling curve → fnYrt_IDc
    lcsrt: int = 0        # tension rate-scaling curve     → fnYrt_IDt
    srflag: float = 0.0   # 0 total / 1 deviatoric / 2 plastic rate → VP
    lcfail: int = 0       # failure plastic strain vs strain rate
    ec: float = 0.0       # Young's modulus in compression → EC
    rpct: float = 0.0     # E→EC blend fraction of PT/PC   → RPCT
    pc: float = 0.0       # compressive mean stress of LCIDC → P_c
    pt: float = 0.0       # tensile mean stress of LCIDT     → P_t
    pcutc: float = 0.0    # pressure cut-offs (3D stress update only) — no slot
    pcutt: float = 0.0
    pcutf: float = 0.0
    srfilt: float = 0.0   # strain-rate EMA filter — no slot
    k: float = 0.0        # viscoelastic bulk modulus → /VISC/PRONY K_v
    gi: List[float] = field(default_factory=list)
    betai: List[float] = field(default_factory=list)


@dataclass
class MatStrainRatePlas:
    """*MAT_STRAIN_RATE_DEPENDENT_PLASTICITY (019) → /MAT/LAW121 (PLAS_RATE).

    A 1:1 target: LAW121's engine kernel is literally LS-DYNA MAT_019's
    ``sigma_y = sigma_0(eps_dot) + E*Et/(E-Et) * eps_p``, so every curve slot
    transfers without resampling.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    E: float = 0.0
    nu: float = 0.0
    vp: int = 0           # 0 scale yield stress / 1 viscoplastic → Ivisc
    lc1: int = 0          # yield strength vs strain rate  → Fct_SIG0
    etan: float = 0.0     # tangent modulus Et             → TANG
    lc2: int = 0          # Young's modulus vs strain rate → Fct_YOUN
    lc3: int = 0          # tangent modulus vs strain rate → Fct_TANG
    lc4: int = 0          # failure stress vs strain rate  → Fct_FAIL
    tdel: float = 0.0     # min timestep element deletion  → DTMIN
    rdef: int = 0         # failure-curve redefinition     → Ifail (value-for-value)


@dataclass
class MatGurson:
    """*MAT_GURSON (120, + the _JC / _RCDC / _BFRAC variants) → /MAT/LAW52.

    The porosity set (f0/fc/fN/fF, the nucleation pair eps_N/s_N and the flow
    parameters q1/q2) maps one-for-one; the hardening comes from ATYP (ideal /
    power law / linear / 8-point curve) or from LCSS, which wins over all of
    them.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    E: float = 0.0
    nu: float = 0.0
    sigy: float = 0.0     # → LAW52 A
    n: float = 0.0        # power-law exponent (ATYP=1 only)
    q1: float = 0.0       # → alpha_1
    q2: float = 0.0       # → alpha_2
    fc: float = 0.0       # critical void volume fraction → Fc
    f0: float = 0.0       # initial void volume fraction  → Fi
    en: float = 0.0       # mean nucleation strain        → EpsN (<0 = curve id)
    sn: float = 0.0       # nucleation std deviation      → SN   (<0 = curve id)
    fn: float = 0.0       # nucleating void fraction      → FN
    etan: float = 0.0     # linear-hardening tangent modulus (ATYP=2 only)
    atyp: int = 0         # 0 ideal / 1 power law / 2 linear / 3 8-point curve
    ff0: float = 0.0      # failure void volume fraction  → FF
    eps_pts: List[float] = field(default_factory=list)   # EPS1..EPS8
    es_pts: List[float] = field(default_factory=list)    # ES1..ES8
    lengths: List[float] = field(default_factory=list)   # L1..L4
    ffs: List[float] = field(default_factory=list)       # FF1..FF4
    lcss: int = 0         # yield curve / table → Tab_ID (wins over ATYP)
    lcff: int = 0         # fF vs element length
    numint: float = 0.0   # failed IPs before deletion — no LAW52 slot
    lcf0: int = 0         # f0 vs element length
    lcfc: int = 0         # fc vs element length
    lcfn: int = 0         # fN vs element length
    vgtyp: float = 0.0    # void-growth type — no LAW52 slot
    dexp: float = 0.0     # damage history-variable exponent — no LAW52 slot
    # "" = *MAT_GURSON; "JC" / "RCDC" / "BFRAC" = the option variants, whose
    # card 5 is NOT the (L1..L4, FF1..FF4) element-length table.
    variant: str = ""
    jc_d: List[float] = field(default_factory=list)   # _JC card 5 D1..D4
    jc_lcdam: int = 0
    jc_lcjc: int = 0
    jc_l1: float = 0.0
    jc_l2: float = 0.0
    # writer-resolved (see _resolve_mat_gurson)
    tab_id: int = 0       # → LAW52 Tab_ID
    iyield: int = 0       # → LAW52 Iyield (1 when Tab_ID is used)
    hard_b: float = 0.0   # → LAW52 B
    hard_n: float = 0.0   # → LAW52 N
    ff: float = 0.0       # → LAW52 FF, after the LCFF / (L,FF) / FF0 ladder


@dataclass
class MatIsoElasPlas:
    """*MAT_ISOTROPIC_ELASTIC_PLASTIC (012) → /MAT/LAW2 (PLAS_JOHNS).

    The one LS-DYNA plasticity card written in SHEAR + BULK modulus rather than
    E/nu, so the writer derives ``E = 9KG/(3K+G)`` and ``nu = (3K-2G)/(2(3K+G))``
    before anything else. ``etan`` is documented as the PLASTIC hardening
    modulus (Vol II R17 p.2-206), so it lands on LAW2's ``b`` verbatim.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    g: float = 0.0        # shear modulus
    sigy: float = 0.0     # → LAW2 a
    etan: float = 0.0     # plastic hardening modulus → LAW2 b
    bulk: float = 0.0     # bulk modulus K
    # writer-resolved
    E: float = 0.0
    nu: float = 0.0


@dataclass
class MatHill3R:
    """*MAT_HILL_3R (122) → /MAT/LAW43 (HILL_TAB) or /MAT/LAW32 (HILL).

    Hill 1948 planar anisotropy with THREE independent Lankford values. The
    hardening rule picks the target law: HR=1/3 are tabular (LAW43), HR=2 is
    the analytic Swift power law, for which /MAT/LAW32's
    ``sigma = A*(eps_0 + eps_p)^n`` is an exact match.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    E: float = 0.0
    nu: float = 0.0
    hr: float = 1.0       # 1 linear / 2 exponential / 3 load curve
    p1: float = 0.0       # HR=1 tangent modulus; HR=2 k (strength coefficient)
    p2: float = 0.0       # HR=1 yield stress;    HR=2 n (exponent)
    r00: float = 0.0
    r45: float = 0.0
    r90: float = 0.0
    lcid: int = 0         # HR=3 hardening curve
    e0: float = 0.0       # HR=2 eps_0 offset
    # Material-axis card set (AOPT / A1-A3 / V1-V3 D1-D3 BETA), read by
    # _emit_hill_3r_prop, which hand-rolls the mapping onto /PROP/TYPE9's
    # single Vx/Vy/Vz + Phi rather than going through _composite_ref_axis (that
    # mapper serves the LAW93/LAW127 layup path and its /PROP/TYPE11-TYPE51
    # cards, which this material never reaches).
    aopt: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    a3: float = 0.0
    # V1-V3 only gate the "something was stated that has no home" warning:
    # AOPT=3 rotates within the element plane, which TYPE9 cannot express.
    v1: float = 0.0
    v2: float = 0.0
    v3: float = 0.0
    # D1-D3 are parsed for completeness and intentionally UNUSED: they belong
    # to the AOPT modes (the in-plane second vector) that have no TYPE9 column.
    d1: float = 0.0
    d2: float = 0.0
    d3: float = 0.0
    beta: float = 0.0
    # writer-resolved
    hard_func_id: int = 0   # LAW43 func_IDi (HR=1 synthesized, HR=3 = LCID)
    use_law32: bool = False # HR=2 → the analytic /MAT/LAW32 instead


@dataclass
class MatSAMP:
    """*MAT_187 / *MAT_SAMP-1 → /MAT/LAW76 (SAMP-1 semi-analytical polymer).

    Fields are already resolved to their LAW76 meaning by the handler, which
    reads the official manual card layout (MID RO BULK GMOD EMOD NUE RBCFAC
    NUMINT / LCID-T LCID-C LCID-S LCID-B NUEP LCID-P - INCDAM / LCID-D EPFAIL
    DEPRPT LCID-TRI LCID-LC / MITER MIPS - INCFAIL ICONV ASAF - NHSV /
    LCEMOD BETA FILT): E/ν come from EMOD/NUE or are derived from BULK+GMOD.
    The three yield tables (tension/compression/shear) become /TABLE/1 cards.
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    tab_idt: int          # tension yield table   → /TABLE  (LCID-T)
    tab_idc: int          # compression yield table         (LCID-C)
    tab_ids: int          # shear yield table               (LCID-S)
    nu_p: float           # plastic Poisson ratio (Nu_p ← NUEP, blank → 0.0)
    fct_idpr: int         # plastic-ν vs plastic-strain function (fct_IDpr ← LCID-P)
    fct_id1: int          # damage vs plastic-strain function (fct_ID1 ← LCID-D)
    epfail: float         # plastic failure strain (EPS_f_p)
    eps_rupt: float       # ABSOLUTE rupture plastic strain (EPFAIL+DEPRPT → EPS_r_p)
    iconv: int            # convexity flag (ICONV)
    asrate: float         # strain-rate smoothing cutoff (→ Fcut; no SAMP source, 0)


@dataclass
class FailGissmo:
    """*MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2 (GISSMO tabulated damage model).

    Fields keep LS-DYNA meaning; the writer maps them onto /FAIL/TAB2. ECRIT,
    FADEXP and LCSRS follow the LS-DYNA sign convention (a negative value is a
    curve/table id, a positive value a scalar).
    """
    mid: int
    numfip: float       # >0 = # failed IPs (solids); <0 = % thru-thickness (shells)
    lcsdg: int          # failure plastic strain vs triaxiality curve → EPSF_ID
    ecrit: float        # instability: curve id if <0, fixed value if >0
    dmgexp: float       # damage accumulation exponent → N
    dcrit: float        # critical accumulated damage → DCRIT
    fadexp: float       # fading exponent: curve id if <0, value if >0 → EXP/FCT_EXP
    lcregd: int         # element-size regularization curve → TAB_EL
    lcsrs: float        # strain-rate scaling of LCSDG (curve id if <0) → FCT_SR


@dataclass
class ConstrainedNodeSet:
    """*CONSTRAINED_NODE_SET → /RLINK (nodes share the same velocity along the
    coded direction). DOF 1/2/3 = x/y/z translation, 4 = all translations,
    5/6/7 = rotation about x/y/z."""
    nsid: int
    dof: int
    tf: float          # failure time (LS-DYNA); /RLINK has none, so dropped


@dataclass
class MatAddErosion:
    """*MAT_ADD_EROSION → an OpenRadioss /FAIL/GENE1 model.

    The whole card-1/card-2 scalar-criteria set maps onto /FAIL/GENE1 (which
    subsumes what earlier went to /FAIL/TENSSTRAIN + /FAIL/JOHNSON): MXPRES→Pmax,
    MNPRES→Pmin, SIGP1→SigP1_max, SIGVM→Sig_max/fct_IDsm, MXEPS→Eps_max/fct_IDps,
    EFFEPS→Eps_eff, MNEPS→Eps_min, VOLEPS→Eps_vol, EPSSH→Eps_s, SIGTH→Sigr,
    IMPULSE→K, FAILTM→Time_max, NUMFIP→Pthickfail, NCS→NCS. Values are stored
    post-EXCL (a field equal to a non-zero EXCL has already been zeroed = made
    inactive, matching GENE1's own 0→±INFINITY inactive sentinel). IDAM≥1
    (GISSMO/DIEM embedded in the erosion card) is reported, not converted."""
    mid: int
    # Card 1
    excl: float        # exclusion number (kept only for the writer's warning)
    mxpres: float      # max pressure          → Pmax   (+ABS)
    mneps: float       # min principal strain  → Eps_min (-ABS)
    effeps: float      # max effective strain  → Eps_eff (ABS)
    voleps: float      # max volumetric strain → Eps_vol
    numfip: float      # failed-IP rule        → Pthickfail
    ncs: float         # conditions to delete  → NCS
    # Card 2
    mnpres: float      # min pressure          → Pmin   (-ABS)
    sigp1: float       # max principal stress  → SigP1_max
    sigvm: float       # max eq. stress        → Sig_max (>0) / fct_IDsm (<0=curve)
    mxeps: float       # max principal strain  → Eps_max (>0) / fct_IDps (<0=curve)
    epssh: float       # tensorial shear strain→ Eps_s
    sigth: float       # Tuler-Butcher stress  → Sigr
    impulse: float     # Tuler-Butcher integral→ K
    failtm: float      # failure time          → Time_max
    # Card 3
    idam: int          # >=1 GISSMO / <0 DIEM embedded damage model (not converted)
    # Not an *MAT_ADD_EROSION field: *MAT_JOHNSON_COOK DTF>0 (minimum shell
    # timestep deletion) is folded into this material's /FAIL/GENE1 dtmin slot
    # by the writer resolve pass (dyna2rad routes DTF to GENE1 the same way).
    dtmin: float = 0.0


@dataclass
class MatJohnsonCook:
    """*MAT_JOHNSON_COOK (MAT_015) / *MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_
    DAMAGE (MAT_099) → /MAT/LAW2 (PLAS_JOHNS), or /MAT/LAW4 (HYD_JCOOK) + a
    bound /EOS when the part attaches an equation of state (MAT_015 only —
    dyna2rad's law-choice rule).

    Fields are stored with their LAW2/LAW4 meaning (the handler resolves the
    LS-DYNA card: E falls back to 2G(1+ν), CP is premultiplied by RHO into the
    per-volume rhocp, blank EPS0 takes the LS-DYNA default 1.0). Failure inputs
    (DTF / D1-D5 / EFMIN / EROD, MAT_099 PSFAIL) ride along; the writer routes
    them to /FAIL/GENE1 (dtmin), /FAIL/JOHNSON or /FAIL/FLD."""
    mid: int
    title: str
    rho: float
    e: float            # resolved Young's modulus (E, or 2G(1+nu) when E blank)
    nu: float
    a: float            # JC yield A → a
    b: float            # JC hardening B → b
    n: float            # JC exponent N → n (blank → 0; starter default 1)
    c: float            # JC rate coefficient C → c
    epso: float         # EPS0 reference strain rate → EPS_DOT_0 (blank → 1.0)
    m: float = 0.0      # thermal-softening exponent M (blank → 0; starter 1)
    tmelt: float = 0.0  # TM melt temperature (blank → 0; starter 1e20 = off)
    tref: float = 0.0   # TR room temperature → LAW2 T_r / LAW4 T0
    rhocp: float = 0.0  # RHO*CP: LS-DYNA CP is per MASS, Radioss per VOLUME
    pc: float = 0.0     # PC pressure cutoff → LAW4 Pmin (LAW2 has no slot: warned)
    # MAT_099 extras (stay 0 for MAT_015, so the LAW2 card is unchanged)
    eps_p_max: float = 0.0   # MAT_099 EPPFR deletion strain → EPS_p_max
    sig_max0: float = 0.0    # MAT_099 min(SIGSAT, SIGMAX) → SIG_max0
    fsmooth: int = 0         # MAT_099 → 1 (dyna2rad sets rate smoothing)
    ortho: bool = False      # True = MAT_099 (always LAW2 + optional /FAIL/FLD)
    psfail: float = 0.0      # MAT_099 principal failure strain → /FAIL/FLD
    # MAT_015 failure card inputs
    dtf: float = 0.0    # timestep deletion → /FAIL/GENE1 dtmin (suppresses D1-D5)
    d1: float = 0.0     # JC damage D1..D5 → /FAIL/JOHNSON (D3 emitted as -|D3|)
    d2: float = 0.0
    d3: float = 0.0
    d4: float = 0.0
    d5: float = 0.0
    efmin: float = 0.0  # EFMIN: no EPSF_MIN slot in the radioss2017 /FAIL/JOHNSON
    erod: float = 0.0   # EROD != 0 (no erosion) → Ifail_so=2, else 1
    # Writer-resolved routing (set by _resolve_mat_johnson_cook)
    use_law4: bool = False   # True → /MAT/LAW4 + /EOS bound by the mat id
    eos_id: int = 0          # source *EOS_* id consumed by the LAW4 route


@dataclass
class MatPlasKin:
    """*MAT_PLASTIC_KINEMATIC → /MAT/LAW44 (COWPER)."""
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    sigy: float
    etan: float
    beta: float         # kinematic/isotropic split (0=kin, 1=iso) → Chard
    src: float = 0.0   # Cowper-Symonds C
    srp: float = 0.0   # Cowper-Symonds P
    fs: float = 0.0    # failure strain → εpmax (0 = unlimited)
    vp: int = 0        # viscoplastic formulation flag → VP


@dataclass
class MatAnisoViscoplastic:
    """*MAT_ANISOTROPIC_VISCOPLASTIC (MAT_103) → /MAT/LAW128 (HILL_VISC_PLAST).

    Hill-anisotropic elasto-viscoplastic metal model — LAW128 is the near 1:1
    OpenRadioss counterpart (same QR/CR Voce + QX/CX kinematic parameters, a
    Cowper-Symonds rate term, and the Hill surface from R00/R45/R90 or
    F/G/H/L/M/N). Uniaxial flow stress (LS-DYNA Manual Vol II, *MAT_103):

        σ(εp, ε̇p) = SIGY + Σ_i QRi·(1 − e^(−CRi·εp))     # isotropic (Voce)
                         + Σ_i QXi·(1 − e^(−CXi·εp))      # kinematic back-stress
                         + VK·ε̇p^VM                        # viscous overstress

    Card-3 slots ``r00/r45/r90`` double as the Hill F/G/H for brick elements
    (MAT_103's own shell-Lankford / brick-Hill duality); ``hl/hm/hn`` are the
    brick Hill L/M/N. LAW128 is orthotropic-only, so a converted part also needs
    an orthotropic property (/PROP/TYPE9 shell, /PROP/TYPE6 solid) — see
    ``ConversionState.ortho_prop_ids``.
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    sigy: float
    flag: int            # 0 = analytic params; 1 = fit QR/CR to LCSS; 2 = use LCSS
    lcss: int            # yield curve / strain-rate table id (FLAG 1/2)
    alpha: float         # iso/kin split for the FLAG=1 fit (1=iso, 0=kin)
    qr1: float           # isotropic (Voce) hardening
    cr1: float
    qr2: float
    cr2: float
    qx1: float           # kinematic back-stress hardening
    cx1: float
    qx2: float
    cx2: float
    vk: float            # viscous overstress coefficient (σ_v = VK·ε̇^VM)
    vm: float            # viscous overstress exponent
    r00: float           # shell Lankford R00/R45/R90 (or brick Hill F/G/H)
    r45: float
    r90: float
    hl: float            # brick Hill L/M/N (unused for shells)
    hm: float
    hn: float
    fail: float = 0.0    # failure plastic strain (0 = none)
    numint: float = 0.0  # failed integration points before element deletion
    # Material-axis option + the axis-definition cards (5-6). AOPT selects which
    # of these is meaningful; the writer maps them onto the /PROP reference
    # direction (Vx/Vy/Vz + Phi): AOPT=2 → the global vector a, AOPT=3 → vector v
    # rotated by BETA. AOPT=0 (element nodes) / 1 / 4 (point / cylindrical) have
    # no single global vector and fall back to the default axis + a warning.
    aopt: float = 0.0
    a1: float = 0.0      # AOPT=2 global material-1 (a) vector
    a2: float = 0.0
    a3: float = 0.0
    v1: float = 0.0      # AOPT=3/4 reference vector v
    v2: float = 0.0
    v3: float = 0.0
    xp: float = 0.0      # AOPT=1/4 reference point P
    yp: float = 0.0
    zp: float = 0.0
    beta: float = 0.0    # AOPT=3 rotation angle (degrees)


# ── Composites ───────────────────────────────────────────────────────────────
# The four composite/orthotropic material families and the *PART_COMPOSITE
# per-ply layup. Every one of these laws is orthotropic- or composite-class in
# the starter (PROP_SHELL=2), so a converted part that HOLDS ELEMENTS can never
# sit on the isotropic /PROP/SHELL (ERROR 3047) — each gets a synthesized
# orthotropic property, see ``ConversionState.composite_prop_ids``. The check is
# per element GROUP, so an element-free part is never tested and needs none.
#
# AOPT convention (shared by MAT_002 and MAT_054/055, and identical to the
# MAT_103 one above): the axis cards carry fixed slots that are blank where the
# active AOPT does not use them, so the handler reads EVERY slot unconditionally
# and all AOPT interpretation lives in the writer.

@dataclass
class MatOrthotropicElastic:
    """*MAT_ORTHOTROPIC_ELASTIC (MAT_002) → /MAT/LAW93 (ORTH_HILL).

    Linear orthotropic elasticity. LAW93 is an orthotropic *Hill-plasticity* law,
    so the elastic-only MAT_002 is emitted with ``sigma_y = 1e30`` (yield never
    reached) and all Hill r-ratios at 1.0 — matching dyna2rad's
    ``p_ConvertMatL2``, which writes only the moduli and lets the cfg defaults
    supply the rest.

    POISSON CONVENTION — the one real numeric trap. LS-DYNA ``PRBA`` is ν_ba
    (Manual Vol II R16 p.2-157: "PRBA is the minor Poisson's ratio if EA > EB"),
    while Radioss ``NU12`` is the MAJOR ratio tied to E11 (``hm_read_mat93.F``
    computes ``NU21 = NU12*E22/E11``). Reciprocity ν_ab/E_a = ν_ba/E_b therefore
    makes the conversion ``NU12 = PRBA·EA/EB`` — NOT a 1:1 copy. Note this is the
    OPPOSITE of LAW127 (*MAT_054), which takes PRBA verbatim; the two must never
    share a conversion helper.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    ea: float = 0.0
    eb: float = 0.0
    ec: float = 0.0
    prba: float = 0.0    # ν_ba  → LAW93 NU12 = PRBA·EA/EB
    prca: float = 0.0    # ν_ca  → LAW93 NU13 = PRCA·EA/EC
    prcb: float = 0.0    # ν_cb  → LAW93 NU23 = PRCB·EB/EC
    gab: float = 0.0     # → G12
    gbc: float = 0.0     # → G23   (note the GBC/GCA swap vs the card order)
    gca: float = 0.0     # → G13
    # Material-axis option + every axis slot (see the module note above).
    aopt: float = 0.0
    xp: float = 0.0      # AOPT=1/4 reference point P
    yp: float = 0.0
    zp: float = 0.0
    a1: float = 0.0      # AOPT=2 global material-1 vector a
    a2: float = 0.0
    a3: float = 0.0
    v1: float = 0.0      # AOPT=3/4 reference vector v
    v2: float = 0.0
    v3: float = 0.0
    d1: float = 0.0      # AOPT=2 in-plane vector d
    d2: float = 0.0
    d3: float = 0.0
    beta: float = 0.0    # rotation about the shell normal / material axis (deg)
    macf: int = 0        # axis-swap flag — no Radioss counterpart, warn-dropped


@dataclass
class MatEnhancedCompositeDamage:
    """*MAT_ENHANCED_COMPOSITE_DAMAGE (MAT_054 / MAT_055) → /MAT/LAW127.

    LAW127 (/MAT/ENHANCED_COMPOSITE) is a direct MAT_054 clone: the strengths
    (XT/XC/YT/YC/SC), the SLIM* stress-limit factors, the DFAIL* strains-to-
    failure and the rate curves all have 1:1 slots.

    POISSON CONVENTION: LAW127 takes the LS-DYNA MINOR ratios VERBATIM
    (``hm_read_mat127.F90`` reads PRBA→nu21, PRCB→nu32, PRCA→nu31 and derives
    ``nu12 = nu21*e1/e2`` itself). Do NOT apply the LAW93 ``E·ν/E`` rescale here
    — it would double-apply.

    LAW127 is Chang-Chang only: ``CRIT=55`` (Tsai-Wu) has no switch and is
    warn-dropped, as are SOFT/SOFT2/SOFTG, KF and DT (no columns exist).
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    ea: float = 0.0
    eb: float = 0.0
    ec: float = 0.0
    prba: float = 0.0    # → LAW127 Nu21 (RAW — no rescale)
    prca: float = 0.0    # → LAW127 Nu31 (RAW)
    prcb: float = 0.0    # → LAW127 Nu32 (RAW)
    gab: float = 0.0     # → G12
    gbc: float = 0.0     # → G23
    gca: float = 0.0     # → G13
    kf: float = 0.0      # bulk modulus of failed material — no LAW127 slot
    aopt: float = 0.0
    two_way: float = 0.0
    ti: float = 0.0
    xp: float = 0.0
    yp: float = 0.0
    zp: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    a3: float = 0.0
    mangle: float = 0.0  # material-angle offset — dyna2rad never reads it
    v1: float = 0.0
    v2: float = 0.0
    v3: float = 0.0
    d1: float = 0.0
    d2: float = 0.0
    d3: float = 0.0
    dfailm: float = 0.0  # matrix strain to failure
    dfails: float = 0.0  # shear strain to failure
    tfail: float = 0.0   # time-step failure criterion
    alph: float = 0.0    # shear-nonlinearity weighting
    soft: float = 0.0    # crashfront softening — no LAW127 slot
    fbrt: float = 0.0
    ycfac: float = 2.0
    dfailt: float = 0.0  # fiber tensile strain to failure
    dfailc: float = 0.0  # fiber compressive strain to failure (negative)
    efs: float = 0.0     # effective failure strain
    xc: float = 0.0
    xt: float = 0.0
    yc: float = 0.0
    yt: float = 0.0
    sc: float = 0.0
    crit: float = 0.0    # 54 = Chang-Chang, 55 = Tsai-Wu (LAW127 = 54 only)
    beta: float = 0.0
    pfl: float = 0.0     # % layers that must fail → LAW127 RATIO = |PFL|
    epsf: float = 0.0
    epsr: float = 0.0
    tsmd: float = 0.9
    soft2: float = 0.0   # no LAW127 slot
    slimt1: float = 1.0
    slimc1: float = 1.0
    slimt2: float = 1.0
    slimc2: float = 1.0
    slims: float = 1.0   # → SLIMSC
    ncyred: float = 0.0
    softg: float = 0.0   # no LAW127 slot
    lcxc: int = 0        # strain-rate curves → LAW127 LCXC/LCXT/LCYC/LCYT/LCSC
    lcxt: int = 0
    lcyc: int = 0
    lcyt: int = 0
    lcsc: int = 0
    dt: float = 0.0      # strain-rate averaging window — no LAW127 slot
    # True when the deck spelled the keyword *MAT_055 / *MAT_LAMINATED_...
    # (the Tsai-Wu default); CRIT on card 6 still overrides it.
    keyword_is_55: bool = False


@dataclass
class MatTransverselyAnisotropic:
    """*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC (MAT_037) → /MAT/LAW43.

    Transversely-isotropic sheet plasticity driven by a single Lankford r-bar.
    LAW43 (/MAT/HILL_TAB) is TABULAR-only — there is no SIGY/ETAN slot — so a
    deck with ``HLCID = 0`` needs a synthesized bilinear hardening /FUNCT
    (``hard_func_id``, allocated by the writer prepass).
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    E: float = 0.0
    nu: float = 0.0
    sigy: float = 0.0
    etan: float = 0.0
    r: float = 0.0       # Lankford r-bar → r00 = r45 = r90 = |R|
    hlcid: int = 0       # hardening curve (σ vs plastic strain)
    idscale: int = 0     # → LAW43 FUNCT_IDE
    ea: float = 0.0      # _ECHANGE saturated Young's modulus → EINF
    coe: float = 0.0     # _ECHANGE decay coefficient → CE
    icfld: int = 0       # _NLP_FAILURE forming-limit curve → /FAIL/FLD fct_ID
    strainlt: float = 0.0
    # 1 = plain, 2 = _ECHANGE, 3 = _NLP_FAILURE, 4 = _NLP2,
    # 5 = _ECHANGE_NLP_FAILURE (the cfg's ECHANGE_OPTION enum)
    echange_option: int = 1
    # writer-resolved: the synthesized bilinear hardening curve id (HLCID = 0)
    hard_func_id: int = 0


@dataclass
class MatLaminatedGlass:
    """*MAT_LAMINATED_GLASS (MAT_032) → a /MAT/PLAS_BRIT (LAW27) PAIR.

    MAT_032 is a single LS-DYNA card describing TWO phases — brittle glass and a
    ductile polymer interlayer — with a per-integration-point ``F_i`` array
    selecting which phase each layer is. Radioss has no such law, so the
    converter synthesizes two /MAT/LAW27 materials and a layered /PROP/TYPE11
    whose per-layer ``m_i`` picks between them (dyna2rad's
    ``p_ConvertMatL32`` + ``ConvertSecShellsRelatedMatLaminate``).

    ID convention, matching dyna2rad: the POLYMER inherits the LS-DYNA MID (so
    every existing reference resolves) and the GLASS gets a fresh synthesized id
    (``glass_mid``), which is also what the converted /PART points at.
    """
    mid: int             # = the polymer /MAT id
    title: str = ""
    rho: float = 0.0
    eg: float = 0.0      # glass Young's modulus
    prg: float = 0.0
    syg: float = 0.0     # glass yield
    etg: float = 0.0     # glass tangent modulus
    efg: float = 0.0     # glass failure strain (only the glass can fail)
    ep: float = 0.0      # polymer Young's modulus
    prp: float = 0.0
    syp: float = 0.0
    etp: float = 0.0
    # F_i, one per integration point: 0.0 = glass, 1.0 = polymer (LS-DYNA)
    f: List[float] = field(default_factory=list)
    # writer-resolved: the synthesized glass /MAT id
    glass_mid: int = 0


#: *MAT_FABRIC FORM values whose card 7 (LCA…LCUAB) exists at all — the only
#: forms that can carry the tabulated warp/weft/shear curves /MAT/LAW58 needs
#: (Vol II R16 p.2-313 card summary "if FORM = 4, 14, or -14"; the data-card
#: heading on p.2-329 widens it to "4, 14, -14, or 24" — the wider set is used,
#: because reading card 7 on a FORM=24 deck can only ADD curves that are there).
FABRIC_CURVE_FORMS = frozenset({4, 14, -14, 24})

#: *MAT_FABRIC FORM values that ARE the plain orthotropic elastic fabric
#: /MAT/LAW19 models faithfully. Everything outside this set and
#: FABRIC_CURVE_FORMS still converts (to the closest of the two laws) but has
#: its FORM specialisation named as dropped — see writer/fabric.py.
FABRIC_ELASTIC_FORMS = frozenset({0, 1, 2, 12})


@dataclass
class MatFabric:
    """*MAT_FABRIC (*MAT_034) → /MAT/LAW19 (FABRI) or /MAT/LAW58 (FABR_A).

    The airbag fabric law: "a variation on the layered orthotropic composite
    model of material 22 and is valid for 3 and 4 node membrane elements only"
    (Vol II R16 p.2-312).

    **The law is chosen by FORM plus the presence of card-7 curves**, and the
    PROPERTY follows the law with no freedom at all — the starter enforces the
    pairing through the material's declared shell class:

      * ``/MAT/LAW19`` declares ``SHELL_ORTHOTROPIC`` (``hm_read_mat19.F:236``
        → ``MATPARAM%PROP_SHELL = 2``) and ``check_mat_elem_prop_compatibility
        .F:174-179`` accepts that on ``/PROP/TYPE9`` — **not** on TYPE16.
      * ``/MAT/LAW58`` declares ``SHELL_ANISOTROPIC`` (``hm_read_mat58.F:334``
        → ``PROP_SHELL = 4``) and ``:194-197`` accepts that on
        ``/PROP/TYPE16`` — **not** on TYPE9.

    Crossing them is starter ``ERROR 3047`` (PROPERTY … IS NOT COMPATIBLE WITH
    MATERIAL …), so the fabric part is repointed at a synthesized property of
    the matching type (``state.fabric_prop_ids``), exactly as the honeycomb
    (#110) and cohesive (#109) batches repoint theirs.

    Card layout (Vol II R16 pp.2-312…2-330, all 10-char fields). Cards 4, 7 and
    8 are CONDITIONAL and shift everything after them, so the walk is driven by
    FVOPT and FORM rather than by a fixed card count:

      1  MID RO EA EB (blank) PRBA PRAB (blank)
      2  GAB (2 blanks) CSE EL PRL LRATIO DAMP
      3  AOPT FLC/X2 FAC/X3 ELA LNRC FORM FVOPT TSRFAC
      4  L R C1 C2 C3                          — only when FVOPT < 0
      5  (blank) RGBRTH A0REF A1 A2 A3 X0 X1
      6  V1 V2 V3 (3 blanks) BETA ISREFG
      7  LCA LCB LCAB LCUA LCUB LCUAB RL       — only when FORM in {4,14,-14,24}
      8  LCAA LCBB H DT (blank) ECOAT SCOAT TCOAT  — only when FORM = -14

    Card-2 fields 2 and 3 are GBC and GCA in the R6.1 layout and blank from
    R8.0 on; they are read (blank → 0) so an old deck's transverse shear moduli
    are not lost, and they only ever act as a fallback for G23/G31.
    """
    mid: int
    title: str = ""
    rho: float = 0.0
    ea: float = 0.0          # warp (a-axis) Young's modulus  → E11 / E1
    eb: float = 0.0          # weft (b-axis)                  → E22 / E2
    prba: float = 0.0        # nu_ba (minor)
    prab: float = 0.0        # nu_ab (major)  → NU12 (see _fabric_nu12)
    gab: float = 0.0         # in-plane shear → G12 / G0
    gbc: float = 0.0         # R6.1-only, blank from R8.0     → G23 fallback
    gca: float = 0.0         # R6.1-only                      → G31 fallback
    cse: float = 0.0         # 0 = keep compressive stress, 1 = eliminate
    el: float = 0.0          # liner Young's modulus
    prl: float = 0.0         # liner Poisson
    lratio: float = 0.0      # liner thickness ratio (non-zero activates it)
    damp: float = 0.0        # Rayleigh damping → the property's Dm
    aopt: float = 0.0
    flc: float = 0.0         # porosity / leakage coefficient (or X2)
    fac: float = 0.0         # fabric area coefficient (or X3)
    ela: float = 0.0
    lnrc: float = 0.0
    form: int = 0
    fvopt: float = 0.0
    tsrfac: float = 0.0      # → ZEROSTRESS / ZERO_STRESS (closest, not equal)
    rgbrth: float = 0.0      # material-dependent reference-geometry birth time
    a0ref: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    a3: float = 0.0
    x0: float = 0.0
    x1: float = 0.0
    v1: float = 0.0
    v2: float = 0.0
    v3: float = 0.0
    beta: float = 0.0        # material angle (deg) for AOPT 0 and 3
    isrefg: int = 0
    # Card 7 (FORM 4/14/-14/24)
    lca: int = 0             # sigma(eps) warp   → LAW58 FCT_ID1
    lcb: int = 0             # weft              → FCT_ID2
    lcab: int = 0            # shear             → FCT_ID3
    lcua: int = 0            # unload warp       → FCT_ID4
    lcub: int = 0            # unload weft       → FCT_ID5
    lcuab: int = 0           # unload shear      → FCT_ID6
    rl: float = 0.0          # reloading parameter (FORM 14/24)
    # Card 8 (FORM = -14)
    lcaa: int = 0
    lcbb: int = 0
    hyst: float = 0.0
    dt_avg: float = 0.0
    ecoat: float = 0.0
    scoat: float = 0.0
    tcoat: float = 0.0
    # ── resolved by writer/fabric.py::_resolve_mat_fabric ─────────────────
    use_law58: bool = False  # False → /MAT/LAW19 + /PROP/TYPE9
    nu12: float = 0.0        # the Poisson's ratio actually written
    g12: float = 0.0
    g23: float = 0.0
    g31: float = 0.0
    e22: float = 0.0         # EB with the EA fallback already applied
    r_e: float = 1.0         # LAW19 compression reduction factor (CSE)
    # 0 = apply the reference-state pre-stress in full (LS-DYNA TSRFAC = 0);
    # non-zero CANCELS it and relaxes it away. See writer/fabric.py.
    zerostress: float = 0.0
    sensor_id: int = 0       # /SENSOR/TIME id (0 = none)
    # Tdelay of that sensor: RGBRTH (card 5) or, when the deck states none, the
    # BIRTH of an *AIRBAG_REFERENCE_GEOMETRY_BIRTH covering the material's
    # parts. Both mean "the reference geometry activates at this time"; the
    # MATERIAL-level RGBRTH wins, because LS-DYNA documents it as the
    # per-material override of the card-level BIRTH.
    sensor_tdelay: float = 0.0
    #: The six function ids actually written into LAW58's FCT_ID1..6. Four of
    #: them are the deck's own curve ids; the two SHEAR slots (3 and 6) are
    #: SYNTHESIZED copies, because Radioss evaluates the shear function at an
    #: ANGLE IN DEGREES and needs it defined on both sides of zero — see
    #: writer/fabric.py::_law58_shear_curve.
    fct_ids: List[int] = field(default_factory=lambda: [0] * 6)

    def curve_ids(self) -> List[int]:
        """The six card-7 stress/strain curve ids, zeros included."""
        return [self.lca, self.lcb, self.lcab, self.lcua, self.lcub, self.lcuab]

    def has_curves(self) -> bool:
        return any(self.curve_ids())


@dataclass
class CompositePly:
    """One layer of a *PART_COMPOSITE layup (card 5a/5b), bottom → top."""
    mid: int             # layer material id
    thick: float         # layer thickness
    beta: float          # layer material angle (deg) → Radioss Phi_i/delta_phi
    tmid: int = 0        # thermal material id — no Radioss counterpart
    plyid: int = 0       # _LONG only
    shrfac: float = 0.0  # _LONG only


@dataclass
class PartComposite:
    """*PART_COMPOSITE (+ _TITLE / _LONG / _CONTACT / _TSHELL / _IGA_SHELL).

    A *PART that carries its own per-ply layup instead of pointing at a
    *SECTION_SHELL — converted to /PROP/TYPE51 (stack) plus one /PROP/TYPE19
    (PLY) per layer. ``variant`` is "" for the thin-shell (supported) form;
    TSHELL / IGA_SHELL warn and fall back to a plain shell property so the
    part's MESH is never lost.
    """
    pid: int
    title: str = ""
    elform: int = 0
    # LS-DYNA's own SHRF default is 1.0, but a BLANK field is recorded as 0.0
    # ("not given") so the writer can fall back to Radioss's 5/6 instead of
    # silently making the part 20% stiffer in transverse shear than the same
    # deck converted by dyna2rad, which never touches Ashear on this path.
    shrf: float = 0.0    # → /PROP/TYPE51 Ashear, only when explicitly given
    nloc: float = 0.0    # 1 = top, 0 = mid, -1 = bottom → Ipos 3 / 0 / 4
    marea: float = 0.0   # non-structural mass per area
    hgid: int = 0
    adpopt: int = 0
    thshel: int = 0
    plies: List[CompositePly] = field(default_factory=list)
    variant: str = ""    # "", "TSHELL", "IGA_SHELL"
    # Card 3b field 8, _TSHELL variant ONLY (the thin-shell card 3a has THSHEL
    # there instead): 0 parabolic / 1 constant transverse-shear distribution.
    # Radioss thick shells are always parabolic, so it is warn-dropped — but it
    # is READ, because the *SECTION_TSHELL path reports the same field and
    # dropping it silently on one route while naming it on the other is worse
    # than either.
    tshear: int = 0
    long_form: bool = False
    irpl: int = 0        # optional OPTCARD: 103 = 3-point Simpson per layer
    optt: float = 0.0    # _CONTACT contact thickness


@dataclass
class MatRigid:
    """*MAT_RIGID → /MAT/ELAST + /RBODY (deferred).

    Card 3 ("must be included but may be left blank", Vol II R16 p.2-233) is
    ``LCO or A1 | A2 | A3 | V1 | V2 | V3`` and carries the body's own LOCAL
    system: ``LCO`` is a *DEFINE_COORDINATE_* id, or ``a``/``v`` are two
    body-fixed vectors whose triad is ``(a, b, c)`` with ``c = a x v`` and
    ``b = c x a``. Either form "specifies the coordinate system used for
    *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL", defaulting to the body's
    principal inertia directions when both are absent — which is the one case
    k2rad cannot recover (it computes no inertia tensor).
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    cmo: float
    con1: int
    con2: int
    lco: int = 0
    a_vec: Optional[Tuple[float, float, float]] = None
    v_vec: Optional[Tuple[float, float, float]] = None


@dataclass
class MatNull:
    mid: int
    title: str
    rho: float
    E: float
    nu: float


@dataclass
class MatHighExplosiveBurn:
    """*MAT_HIGH_EXPLOSIVE_BURN (MAT_008) — a programmed-burn high explosive.

    Card: mid ro d pcj beta k g sigy
      ro   = density, d = detonation velocity, pcj = Chapman-Jouguet pressure.
    Paired (shared mid) with an *EOS_JWL that supplies the JWL A,B,R1,R2,omega,E0.
    The two together map to one OpenRadioss /MAT/LAW5 (JWL). beta/k/g/sigy have
    no LAW5 counterpart (LAW5 is a pure detonation-product EOS) and are dropped.
    """
    mid: int
    title: str
    rho: float
    d: float
    pcj: float
    beta: float = 0.0


@dataclass
class EosJwl:
    """*EOS_JWL (EOS_002) — the JWL pressure law for detonation products.

    Card 1: eosid a b r1 r2 omeg e0 vo.  Folded into the /MAT/LAW5 of the same id
    (its companion *MAT_HIGH_EXPLOSIVE_BURN); vo != 1 is warned.
    """
    eosid: int
    a: float
    b: float
    r1: float
    r2: float
    omega: float
    e0: float
    vo: float = 1.0


@dataclass
class EosCard:
    """An *EOS_* that maps to a standalone OpenRadioss /EOS/<kind> block.

    ``kind`` is the Radioss keyword suffix ("POLYNOMIAL" | "GRUNEISEN" |
    "IDEAL-GAS"); ``params`` holds the Radioss field values keyed by name (the
    LS-DYNA->Radioss field mapping is done in the handler). ``rho0`` is the
    reference density used as a fallback for the /MAT/LAW6 carrier when no
    companion *MAT_NULL supplies one. The /EOS block binds to the material of the
    SAME id (eosid == mid), an OpenRadioss requirement.
    """
    eosid: int
    kind: str
    params: Dict[str, float] = field(default_factory=dict)
    rho0: float = 0.0
    note: str = ""


@dataclass
class AleMultiMaterialGroup:
    """*ALE_MULTI-MATERIAL_GROUP — the ordered list of ALE material groups.

    Each entry is a (sid, idtype) reference (idtype 0 = part-set, 1 = part). The
    order is the AMMG/phase index used by *INITIAL_VOLUME_FRACTION and the ALE
    advection. Maps to the ordered submaterial list of one /MAT/LAW51 (MULTIMAT).
    """
    entries: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class ConstrainedLagrangeInSolid:
    """*CONSTRAINED_LAGRANGE_IN_SOLID — fluid-structure coupling → /INTER/TYPE18.

    Card 1: slave master sstyp mstyp nquad ctype direc mcoup.  slave = the
    Lagrangian structure set, master = the ALE fluid set. Card 2 carries the
    penalty stiffness scale (pfac) and start/end. Mapped to a penalty ALE/
    Lagrange /INTER/TYPE18 (surf_ID = structure, grbric_ID = fluid bricks).
    """
    slave: int
    master: int
    sstyp: int = 0
    mstyp: int = 0
    ctype: int = 4
    pfac: float = 0.1
    start: float = 0.0
    end: float = 0.0


@dataclass
class InitialVolumeFraction:
    """*INITIAL_VOLUME_FRACTION_GEOMETRY — initial ALE fill → /INIVOL.

    ``part`` is the ALE part being filled; ``fills`` is a list of
    (surf_ID, ale_phase, fill_opt) container rows. Only a plane container
    (reusing /SURF/PLANE) is supported; other container shapes are warned.
    """
    part: int
    fills: List[Tuple[int, int, int]] = field(default_factory=list)


@dataclass
class BoundaryNonReflecting:
    """*BOUNDARY_NON_REFLECTING — a silent far-field boundary → /EBCS/NRF.

    ``nsid`` is the segment set acting as the non-reflecting frontier.
    """
    nsid: int


@dataclass
class ControlAle:
    """*CONTROL_ALE — ALE advection/mesh controls.

    Card 1: dct nadv meth afac bfac cfac dfac efac.  ``meth`` is the advection
    method (1 donor-cell, 2 Van-Leer, 3 HIS). Only informational / advection-
    hint mapping to /ALE options; mesh smoothing has no clean equivalent.
    """
    meth: int = 1
    afac: float = 0.0


@dataclass
class InitialDetonation:
    """*INITIAL_DETONATION — a JWL lighting point/time → /DFS/DETPOINT.

    Card: pid x y z lt.  ``pid`` is the explosive part (0 = all); the writer
    resolves part -> LAW5 material id for the /DFS/DETPOINT mat_ID field.
    """
    pid: int
    x: float
    y: float
    z: float
    lt: float = 0.0


@dataclass
class InitialStressShell:
    """*INITIAL_STRESS_SHELL (one element's record) → /INISHE/STRS_F[/GLOB].

    ``layers`` holds one tuple per through-thickness integration point:
    (t, sxx, syy, szz, sxy, syz, szx, eps) — t is the normalized [-1,1]
    thickness coordinate, the stress components are in the system selected by
    ``iloc`` (LS-DYNA default 0 = GLOBAL cartesian; 1 = element-local).
    NPLANE in-plane points have already been averaged per layer by the handler
    (warned there). ``nthick`` is kept for the writer's /PROP/SHELL-N
    consistency check (the OpenRadioss starter ERRORs on a mismatch, so the
    writer warns + skips mismatched elements instead of emitting a bad card).
    """
    eid: int
    nplane: int
    nthick: int
    iloc: int
    layers: List[Tuple[float, float, float, float, float, float, float, float]] \
        = field(default_factory=list)


@dataclass
class InitialStressSolid:
    """*INITIAL_STRESS_SOLID (one element's record) → /INIBRI/STRS_FGLO.

    ``points`` holds one tuple per integration point:
    (sxx, syy, szz, sxy, syz, szx, eps) in the GLOBAL cartesian system
    (LS-DYNA defines *INITIAL_STRESS_SOLID components globally, hence the
    global /INIBRI flavour). ``nint`` is the LS-DYNA integration point count;
    the writer adapts it to the point count of the emitted /PROP/SOLID
    formulation (replicate 1→8, average n→1, warn + skip otherwise).
    """
    eid: int
    nint: int
    points: List[Tuple[float, float, float, float, float, float, float]] \
        = field(default_factory=list)


@dataclass
class CrossSection:
    """*DATABASE_CROSS_SECTION_PLANE/_SET → /SECT (+ /TH/SECTIO).

    kind "SET": nsid = *SET_NODE (the section's node group); hsid/bsid/ssid =
    *SET_SOLID / *SET_BEAM / *SET_SHELL element sets → the /SECT grbric/grbeam/
    grshel groups (direct mapping).

    kind "PLANE": an infinite cutting plane through tail (xct,yct,zct) with
    normal towards head (xch,ych,zch), optionally limited to a circle of
    ``radius`` around the tail point and to the parts of part-set ``psid``
    (0 = all). The writer resolves the cut geometrically: elements whose nodes
    straddle the plane are the section elements, and their nodes on the TAIL
    side of the plane form the node group (the standard /SECT construction).
    """
    csid: int           # user id from the _ID variant (0 = auto-assign)
    title: str
    kind: str           # "PLANE" | "SET"
    # _SET fields
    nsid: int = 0
    hsid: int = 0       # solid element set
    bsid: int = 0       # beam element set
    ssid: int = 0       # shell element set
    # _PLANE fields
    psid: int = 0       # part set restriction (0 = all parts)
    xct: float = 0.0; yct: float = 0.0; zct: float = 0.0
    xch: float = 0.0; ych: float = 0.0; zch: float = 0.0
    radius: float = 0.0


@dataclass
class Curve:
    lcid: int
    title: str
    sfa: float          # abscissa scale
    sfo: float          # ordinate scale
    offa: float
    offo: float
    pts: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class DefineTable:
    """*DEFINE_TABLE / *DEFINE_TABLE_2D → /TABLE/1 with Ndim=2.

    Header card (Keyword971_R6.1 define_table[_2D].cfg): TBID SFA OFFA.
    Each row pairs a 2nd-dimension abscissa VALUE (e.g. a strain rate, stored
    already scaled: A = SFA·(VALUE+OFFA)) with a *DEFINE_CURVE id. The _2D
    variant carries the LCID explicitly on each row; the legacy *DEFINE_TABLE
    lists bare VALUEs whose curves are the *DEFINE_CURVE blocks immediately
    FOLLOWING the table in the deck — those live in ``pending_values`` until
    the writer post-pass pairs them positionally (``curve_seq`` = how many
    curves had been parsed when the table was read).
    """
    tbid: int
    title: str
    sfa: float
    offa: float
    rows: List[Tuple[float, int]] = field(default_factory=list)   # (A, lcid)
    pending_values: List[float] = field(default_factory=list)     # legacy form
    curve_seq: int = 0      # len(state.curve_order) at parse time
    resolved: bool = False  # rows are final (post-pass ran / _2D form)


@dataclass
class DefineTable3D:
    """*DEFINE_TABLE_3D → /TABLE/1 with Ndim=3 (a table of 2-D tables).

    Header card (Keyword971_R13.0 define_table_3D.cfg): TBID SFA OFFA — same
    shape as the 2-D form. Each row pairs a 3rd-dimension abscissa VALUE
    (stored already scaled: V = SFA·(VALUE+OFFA)) with a *DEFINE_TABLE[_2D]
    id, so the full nesting is TABLE_3D(V) → TABLE(A) → CURVE(x): dim 1 = the
    leaf curves' own abscissa, dim 2 = the inner tables' VALUEs, dim 3 = this
    card's VALUEs. There is NO legacy positional form — the manual's point
    card is always "VALUE TABLEID" (20-char fields).

    Validation + the flat Ndim=3 /TABLE/1 emission (grid-completeness checked
    against starter ERROR 3089) happen in the writer post-pass
    ``_resolve_define_tables_3d``; *MAT_224's LCK1 additionally SLICES the
    nesting (a 2-D plane for tab_ID_h, the per-plane quasi-static curves for
    tab_ID_t) instead of referencing the 3-D card.
    """
    tbid: int
    title: str
    sfa: float
    offa: float
    rows: List[Tuple[float, int]] = field(default_factory=list)   # (V, 2-D tbid)
    resolved: bool = False  # post-pass validated; emitted as Ndim=3 /TABLE/1


@dataclass
class AutoTable:
    """A synthesized multi-dimensional /TABLE/1 (Ndim 2 or 3), built by a
    writer prepass with EXPLICIT rows — unlike ``DefineTable`` (whose rows are
    the parsed LS-DYNA table) these carry per-row Scale_y and, for Ndim=3, a
    (A, B) coordinate pair per row. Emitted by ``_make_functions`` after the
    *DEFINE_TABLE loop, layout from CURVE/table_1.cfg FORMAT(radioss110):
    row = fct_ID(10) blank(10) A(20) [B(20)] blank(40|20) Scale_y(20).

    Rows must already satisfy the starter's grid rules for Ndim=3 (complete
    rectangular secondary grid, no duplicate (A,B) with different fct/scale —
    hm_read_table2_1.F:197-303, ERRORs 3087/3088/3089); the builders construct
    them as full tensor grids so this holds by construction.
    """
    tid: int
    title: str
    ndim: int
    # (fct_id, (A,) or (A, B), Scale_y)
    rows: List[Tuple[int, Tuple[float, ...], float]] = field(default_factory=list)


@dataclass
class CoordSys:
    cid: int
    xo: float; yo: float; zo: float
    xl: float; yl: float; zl: float
    xp: float; yp: float; zp: float


@dataclass
class CoordNodes:
    """*DEFINE_COORDINATE_NODES — a local system defined by three nodes.

    LS-DYNA card: cid n1 n2 n3 flag dir
      n1     = origin node
      n1->n2 = the local axis named by `dir` (default X)
      n3     = together with n1 defines the in-plane (next cyclic) direction
      flag   = 0: orientation evaluated once at t=0 (fixed);
               1: updated every step (the system co-rotates with the nodes)
      dir    = 'X' | 'Y' | 'Z' — which local axis the n1->n2 vector defines

    OpenRadioss /SKEW/MOV uses the IDENTICAL (N1, N2, N3, Dir) convention, so
    flag=1 maps 1:1 to a moving skew; flag=0 maps to a /SKEW/FIX whose axes are
    computed from the node coordinates at t=0 (Reference Guide p.2217-2221).
    """
    cid: int
    n1: int
    n2: int
    n3: int
    flag: int = 0
    dir: str = "X"


@dataclass
class CoordVector:
    """*DEFINE_COORDINATE_VECTOR → /SKEW/FIX at the global origin.

    (xx,yx,zx) = a vector on the local x-axis; (xv,yv,zv) = a vector in the
    local x-y plane. The starter forms local Z = X × V, local Y = Z × X. The
    /SKEW id is the LS-DYNA CID (coordinate-system id space). ``nid`` is the R16
    co-rotation node (field 8); dyna2rad ignores it and emits a fixed skew, so
    a nonzero nid is warned and dropped.
    """
    cid: int
    xx: float; yx: float; zx: float
    xv: float; yv: float; zv: float
    nid: int = 0
    title: str = ""


@dataclass
class DefineVector:
    """*DEFINE_VECTOR (value form) → /SKEW/FIX, or *DEFINE_VECTOR_NODES →
    /SKEW/MOV.

    Value form (is_nodes=False): tail (xt,yt,zt) → head (xh,yh,zh), optional
    ``cid``. Nodes form (is_nodes=True): tail node ``nodet`` → head node
    ``nodeh``. Either way the /SKEW's local X' follows the tail→head direction.
    ``skew_id`` and ``n3`` (a synthesized third node for the moving /SKEW/MOV of
    the _NODES form) are filled in by the _synthesize_vector_skews writer
    prepass. The VID lives in the LS-DYNA vector-id space; the writer maps it to
    a converted /SKEW id via state.vector_skew_ids.
    """
    vid: int
    title: str = ""
    is_nodes: bool = False
    xt: float = 0.0; yt: float = 0.0; zt: float = 0.0
    xh: float = 0.0; yh: float = 0.0; zh: float = 0.0
    cid: int = 0
    nodet: int = 0
    nodeh: int = 0
    skew_id: int = 0
    n3: int = 0


@dataclass
class SdOrientation:
    """*DEFINE_SD_ORIENTATION → a /SKEW referenced by an oriented
    *ELEMENT_DISCRETE (its VID).

    IOP=0: fixed direction (xt,yt,zt) → /SKEW/FIX (local X' aligned with that
    vector). IOP=2: moving, along nid1→nid2 → /SKEW/MOV. IOP=1/3 (the spring's
    own node axis projected ⟂ to a vector/node pair) have no OpenRadioss skew
    equivalent and are unhandled — exactly as in dyna2rad. ``skew_id`` and
    ``n3`` (synthesized third node for the IOP=2 /SKEW/MOV) are filled in by the
    writer prepass; the writer maps the VID to its skew via
    state.sdorient_skew_ids.
    """
    vid: int
    iop: int
    xt: float = 0.0; yt: float = 0.0; zt: float = 0.0
    nid1: int = 0
    nid2: int = 0
    title: str = ""
    skew_id: int = 0
    n3: int = 0


@dataclass
class DefineBox:
    """*DEFINE_BOX / *DEFINE_BOX_LOCAL → numeric node-membership scoping.

    Extents (xmn,xmx,ymn,ymx,zmn,zmx) span the box between two diagonal corners.
    Plain box: the extents are global, axis-aligned. _LOCAL box: the extents are
    in the box's local frame, whose origin is (cx,cy,cz) and whose axes come
    from the local-X vector (xx,yx,zx) and an in-plane vector (xv,yv,zv) — the
    same construction as *DEFINE_COORDINATE_VECTOR (local Z = X × V, local Y =
    Z × X). Box membership is resolved against the node coordinates at
    conversion time (no /BOX entity is emitted): every consumer intersects its
    node group with the box's contained nodes, mirroring the NSIDEX set-
    difference the initial-velocity path already uses.
    """
    box_id: int
    title: str = ""
    xmn: float = 0.0; xmx: float = 0.0
    ymn: float = 0.0; ymx: float = 0.0
    zmn: float = 0.0; zmx: float = 0.0
    local: bool = False
    cx: float = 0.0; cy: float = 0.0; cz: float = 0.0
    xx: float = 0.0; yx: float = 0.0; zx: float = 0.0
    xv: float = 0.0; yv: float = 0.0; zv: float = 0.0


@dataclass
class RigidInertia:
    """The `_INERTIA` mass-property card set, shared by `*PART_INERTIA` and
    `*CONSTRAINED_NODAL_RIGID_BODY_INERTIA`.

    The two keywords carry IDENTICAL data — LS-DYNA Vol I R17 Appendix X p.75-16
    says so in as many words: "The same method must be used for
    *CONSTRAINED_NODAL_RIGID_BODY_INERTIA which has the same keyword data (except
    the coordinate system in input in field CID2)". So one dataclass and one card
    walker (``handlers._read_rigid_inertia``) serve both, and ``cid`` holds
    *PART's card-6 ``CID`` or the CNRB's card-6 ``CID2`` indifferently.

    Cards (each 8 x I10/E10.0, Vol I R17 p.37-4 / p.10-147):
      3: XC YC ZC TM IRCS NODEID
      4: IXX IXY IXZ IYY IYZ IZZ
      5: VTX VTY VTZ VRX VRY VRZ
      6: XL YL ZL XLIP YLIP ZLIP CID   — present ONLY when IRCS = 1

    **The off-diagonal SIGN is not a product of inertia.** *PART Remark 4 (Vol I
    R17 p.37-14) is explicit: "Note that the off-diagonal terms of the inertia
    tensor are opposite in sign from the products of inertia." So LS-DYNA's
    ``IXY`` is the tensor component ``-integral(xy dm)``. Radioss uses the SAME
    convention — ``inirby.F:154-160`` inserts ``Jxy`` into slot (1,2) with a plus
    sign while ``:331-339`` accumulates the mesh contribution into that same slot
    as ``RBY(2)=RBY(2)-XY*XMG``, and two quantities summed into one tensor entry
    must share one convention. Hence ``Jxy=IXY, Jyz=IYZ, Jxz=IXZ`` VERBATIM: the
    only transformation is the field ORDER (LS-DYNA writes IXX IXY IXZ IYY IYZ
    IZZ on one card, Radioss writes Jxx Jyy Jzz then Jxy Jyz Jxz on two).

    **There are no defaults.** *PART Remark 3: "If the INERTIA keyword option is
    used, all mass and inertia properties of the body must be specified. There
    are no default values." A blank ``TM`` or a blank inertia tensor is therefore
    a source-deck DEFECT, not a request to derive anything — the writer warns
    rather than emitting ``Mass = 0``.
    """
    xc: float = 0.0
    yc: float = 0.0
    zc: float = 0.0
    tm: float = 0.0
    #: 0 = the tensor is in the GLOBAL frame, 1 = in the card-6 local system.
    ircs: int = 0
    #: Node whose coordinates ARE the centre of mass; beats XC/YC/ZC ("If nodal
    #: point NODEID is defined, XC, YC, and ZC are ignored", p.37-7).
    nodeid: int = 0
    ixx: float = 0.0
    ixy: float = 0.0
    ixz: float = 0.0
    iyy: float = 0.0
    iyz: float = 0.0
    izz: float = 0.0
    vtx: float = 0.0
    vty: float = 0.0
    vtz: float = 0.0
    vrx: float = 0.0
    vry: float = 0.0
    vrz: float = 0.0
    # Card 6 — the local system the tensor is expressed in when IRCS = 1. Either
    # two vectors (local x-axis XL,YL,ZL plus an in-plane vector XLIP,YLIP,ZLIP,
    # "The origin lies at (0,0,0)") or a *DEFINE_COORDINATE_* id in ``cid``
    # ("With this option, leave fields 1 - 6 blank").
    xl: float = 0.0
    yl: float = 0.0
    zl: float = 0.0
    xlip: float = 0.0
    ylip: float = 0.0
    zlip: float = 0.0
    cid: int = 0
    #: True when card 6 was actually PRESENT in the deck, not merely promised by
    #: ``IRCS = 1``. ``writer/rbody.py::_inertia_frame`` splits its "the local
    #: system is unusable" diagnostic on it: a missing card 6 (the block ended)
    #: and a card 6 stating two zero/parallel vectors are different defects.
    has_local_card: bool = False

    def has_mass_data(self) -> bool:
        """True when the card set carries ANY mass/inertia value.

        An all-blank card set is what LS-PrePost writes for an ``_INERTIA``
        option that is present but unused, and Remark 3 forbids deriving values,
        so the writer treats it as "no override" instead of "zero mass"."""
        return bool(self.tm or self.ixx or self.iyy or self.izz
                    or self.ixy or self.iyz or self.ixz)

    def has_velocity(self) -> bool:
        return bool(self.vtx or self.vty or self.vtz
                    or self.vrx or self.vry or self.vrz)


@dataclass
class PartContact:
    """`*PART_CONTACT` card 8: FS FD DC VC OPTT SFT SSF CPARM8 (all 8 x E10.0).

    Only ``OPTT`` has a Radioss home — the ``/PART`` card's 4th field ``Thick``
    (cols 31-50), "Virtual thickness for shells ... only used to calculate gap in
    interfaces" (Reference Guide 2022 p.194). Everything else is warn-dropped:
    ``FS``/``FD``/``DC``/``VC`` are per-part friction coefficients that Radioss
    expresses only per INTERFACE, ``SFT`` is a thickness SCALE (not multiplied
    into ``Thick`` — that would silently double-apply once the property thickness
    is also scaled), ``SSF`` is a per-part penalty-stiffness scale whose only
    Radioss route is the radioss2026 ``Igap=5`` + ``THICK_S``/``THICK_M`` pair,
    and ``CPARM8`` does not exist below FORMAT(Keyword971_R8.0)."""
    pid: int
    fs: float = 0.0
    fd: float = 0.0
    dc: float = 0.0
    vc: float = 0.0
    optt: float = 0.0
    sft: float = 0.0
    ssf: float = 0.0
    cparm8: float = 0.0


@dataclass
class InterpolationIndep:
    """One `*CONSTRAINED_INTERPOLATION` card-2 row (+ its `_LOCAL` card 3).

    ``inid`` is a NODE id when the card's ``ITYP`` is 0 and a `*SET_NODE` id when
    it is 1. ``idof`` is a DIGIT-STRING, not a bitfield: "The list of dependent
    degrees-of-freedom consists of a number with up to six digits, with each
    digit representing a degree of freedom. For example, the value 1356 indicates
    that degrees of freedom 1, 3, 5, and 6 are controlled" (Vol I R17 p.10-42).

    LS-DYNA gives SIX weights per row and defaults the last five to ``twghtx``
    ("the other factors are set equal to this input value as the default",
    p.10-43); Radioss `/RBE3` has ONE scalar ``WTi`` per set, so a row whose six
    weights are not all equal is not representable and is warned."""
    inid: int
    idof: int = 123456
    twghtx: float = 1.0
    twghty: float = 1.0
    twghtz: float = 1.0
    rwghtx: float = 1.0
    rwghty: float = 1.0
    rwghtz: float = 1.0
    #: `_LOCAL` card 3 — the local system this independent node's DOFs are in.
    cidi: int = 0


@dataclass
class ConstrainedInterpolation:
    """`*CONSTRAINED_INTERPOLATION[_LOCAL]` → `/RBE3` (+ one `/GRNOD/NODE` per set).

    Card 1: ICID DNID DDOF CIDD ITYP IDNSW FGM.

    ``ddof`` defaults to 123456 ("The default is 123456", Vol I R17 p.10-42) —
    which is NOT the Radioss default for the same field: a blank Radioss
    ``Trarot_Mi`` gives Tx/Ty/Tz only (``hm_read_rbe3.F:244-248`` sets
    ``J6(1)=J6(2)=J6(3)=1``), contradicting the Reference Guide's own "set on all
    DOF". k2rad therefore always writes the six digits explicitly and never
    leans on either default.

    ``cidd`` has no `/RBE3` destination at all: the 2022 dependent-node card is
    ``Node_IDr Trarot_ref N_set I_modif`` with no skew column (only the per-set
    ``skew_IDi`` exists), and DDOF is global regardless — "DDOF are in the global
    coordinate system regardless of whether the LOCAL option is used or not".
    """
    icid: int
    dnid: int
    ddof: int = 123456
    cidd: int = 0
    ityp: int = 0
    idnsw: int = 1
    fgm: int = 0
    local: bool = False
    indeps: List[InterpolationIndep] = field(default_factory=list)


@dataclass
class ConstrainedNodalRigidBody:
    """*CONSTRAINED_NODAL_RIGID_BODY[_SPC] — a rigid body tied from a node set.

    Card 1: pid cid nsid pnode iprt drflag rrflag
      pid    = part ID of the nodal rigid body — referenced by *LOAD_RIGID_BODY,
               *BOUNDARY_PRESCRIBED_MOTION_RIGID, *INITIAL_VELOCITY_RIGID_BODY
      cid    = coordinate system for the inertia/output (informational here)
      nsid   = node-set ID; these nodes become the rigid body's secondary nodes
      pnode  = primary/master node (0 = pick the first node of the set; the
               master location does not change a rigid body's physics, only
               where loads/reactions are applied/reported)

    _SPC option adds a constraint card (R16 Vol I p.10-149):
        cmo con1 con2 spcnid xspc yspc zspc
      cmo > 0 : constraints in the GLOBAL system; con1 = translation code (0-7),
                con2 = rotation code (0-7) — same convention as *MAT_RIGID.
      cmo < 0 : constraints in a LOCAL system; con1 = the local coordinate-system
                ID (a *DEFINE_COORDINATE_* cid, fixed in time), con2 = a 6-digit
                local DOF code (Tx Ty Tz Rx Ry Rz, e.g. 010000 = local-y trans).
    Maps to an OpenRadioss /BCS on the rigid body's master node.
    """
    pid: int
    nsid: int
    pnode: int = 0
    cid: int = 0
    title: str = ""
    has_spc: bool = False
    cmo: float = 0.0
    con1: int = 0
    con2: int = 0
    spcnid: int = 0
    #: The `_INERTIA` option's cards 3-6 (``CID2`` lands in ``inertia.cid``).
    #: None when the option is absent — then LS-DYNA "computes the inertia tensor
    #: from the nodal masses", which is exactly Radioss's own ICoG=1 default.
    inertia: Optional[RigidInertia] = None


@dataclass
class BcsSpc:
    bc_id: int
    nsid: int           # node set ID
    cid: int            # coordinate system (0 = global)
    dofx: int; dofy: int; dofz: int
    dofrx: int; dofry: int; dofrz: int


@dataclass
class CnrbSpcBc:
    """A /BCS emitted by the *CONSTRAINED_NODAL_RIGID_BODY_SPC path.

    *BOUNDARY_SPC_* records land in ``bcs_spcs`` and are turned into /BCS by
    ``_make_bcs``. The CNRB ``_SPC`` option is a *second, independent* source of
    /BCS: ``_make_cnrb_rbodies`` writes those cards inline on the rigid body's
    master node, so they must NOT go into ``bcs_spcs`` (that would emit the card
    twice). They are recorded here instead, so the reaction-output consumers —
    /TH/NODE REAC* and /ANIM/VECT/FREAC for *DATABASE_SPCFORC — can see that the
    deck really does SPC-constrain nodes.
    """
    bc_id: int
    ind_node: int       # /RBODY master node the /BCS acts on
    tra: str            # "111"-style translational mask, as emitted
    rot: str            # "111"-style rotational mask, as emitted


#: *BOUNDARY_PRESCRIBED_MOTION VAD -> the OpenRadioss keyword that carries it.
#: THE ONLY definition of which VADs k2rad converts: ``handlers._pm_vad_supported``
#: refuses everything this dict does not hold, and the writer indexes it directly.
#: Keeping one dict is the point — a guard that enumerated the unsupported values
#: instead let an out-of-range VAD (typo, negative, a future LS-DYNA code) reach
#: the writer's bare lookup and abort the whole conversion with a KeyError.
PM_VAD_KEYWORD = {0: "IMPVEL", 1: "IMPACC", 2: "IMPDISP"}


@dataclass
class PrescribedMotionRigid:
    """*BOUNDARY_PRESCRIBED_MOTION_RIGID[_LOCAL] — motion of a rigid part.

    ``local`` is the _LOCAL option: LS-DYNA then expresses DOF in the rigid
    body's OWN system, which rotates with the body (Manual Vol I R16 p.756-757
    Remark 7). k2rad honours that with a co-rotating /SKEW/MOV built on three
    synthesized nodes rigidly attached to the body — see
    ``_synthesize_local_motion_frames``; ``skew_id`` / ``mov_nodes`` are filled
    in by that prepass. The Radioss dyna-reader instead drops the flag
    entirely (``convertbcs.cxx`` never reads ``localOption``), which freezes
    the axes at t = 0.
    """
    pid: int            # rigid part ID
    dof: int            # 1=X,2=Y,3=Z,5=RX,6=RY,7=RZ; ±4/±8 = along/about VID
    vad: int            # 0=vel,1=acc,2=disp,3=vel-vs-disp,4=relative disp
    lcid: int
    sf: float
    death: float
    birth: float
    vid: int = 0                # *DEFINE_VECTOR id, only meaningful for |DOF| 4/8
    local: bool = False         # the _LOCAL option
    skew_id: int = 0            # co-rotating /SKEW/MOV id (_LOCAL prepass)
    mov_nodes: Tuple[int, int, int] = (0, 0, 0)   # its N1/N2/N3


@dataclass
class PrescribedMotionSet:
    """*BOUNDARY_PRESCRIBED_MOTION_SET[_BOX] / *_NODE — applies to a node set.

    DOF follows LS-DYNA: 1/2/3 = Tx/Ty/Tz, 5/6/7 = Rx/Ry/Rz, ±4/±8 =
    translation along / rotation about the *DEFINE_VECTOR ``vid``.

    ``boxid`` is the _BOX option's *DEFINE_BOX: the motion then applies to
    ``nodes(NSID) INTERSECT nodes-inside(BOXID)`` (dyna2rad builds exactly that
    as a /SET/GENERAL with a ``SET`` + ``SET_I`` clause pair,
    ``convertbcs.cxx:493-520``). ``toffset`` / ``lcbchk`` are read so they can
    be reported: neither has an OpenRadioss equivalent.
    """
    nsid: int           # node set ID (0 = "every node in the box" for _BOX)
    dof: int            # 1=X,2=Y,3=Z,5=RX,6=RY,7=RZ; ±4/±8 = along/about VID
    vad: int            # 0=vel,1=acc,2=disp,3=vel-vs-disp,4=relative disp
    lcid: int
    sf: float           # scale factor (0 → zero displacement → /BCS)
    death: float
    birth: float
    vid: int = 0                # *DEFINE_VECTOR id, only meaningful for |DOF| 4/8
    boxid: int = 0              # _BOX option: *DEFINE_BOX scoping the node set
    toffset: int = 0            # _BOX card 2: per-node curve time shift (dropped)
    lcbchk: int = 0             # _BOX card 2: box-check curve (dropped)


@dataclass
class LoadNode:
    """*LOAD_NODE_POINT / *LOAD_NODE_SET — concentrated nodal force/moment
    → /CLOAD. DOF 1/2/3 = force along x/y/z, 5/6/7 = moment about x/y/z
    (4/8 are follower loads, which have no /CLOAD equivalent)."""
    nsid: int           # node-set id (a _POINT card gets an auto single-node set)
    dof: int
    lcid: int
    sf: float
    cid: int            # local system (0 = global) → /CLOAD skew


@dataclass
class RigidWallPlanar:
    """*RIGIDWALL_PLANAR[_ID] (+_MOVING/_FINITE combos) → /RWALL/PLANE|PARAL.

    Card 1: nsid nsidex boxid offset birth death rwksf
      nsid   = tracked ("slave") node set (0 = all nodes)
      nsidex = excluded node set
    Card 2: xt yt zt xh yh zh fric wvel
      (xt,yt,zt) = tail point M on the wall; (xh,yh,zh) = head point M1 —
      the outward normal points from tail to head, exactly /RWALL's M→M1.
      fric: 0 = frictionless sliding, 0<fric<1 = Coulomb friction,
      fric ≥ 1 = no sliding (LS-DYNA "stick") → Slide 0 / 2 / 1.

    _FINITE extra card: xhev yhev zhev lenl lenm — (xhev,yhev,zhev) is the
    head of the edge vector whose in-plane projection gives the l-edge
    direction; lenl/lenm are the wall extents along l and m = n × l. Mapped
    to /RWALL/PARAL corner points M1 = M + lenl·l̂ and M2 = M + lenm·m̂
    (the /RWALL/PARAL normal is (M1−M)×(M2−M), which equals the wall normal).

    _MOVING extra card: mass v0 — total wall mass and initial speed along
    the outward normal (a free-flying finite-mass wall). Mapped to the
    /RWALL moving form: node_ID = a synthesized carrier node at the tail
    point (node_id, assigned by the writer prepass) and the cfg's
    "Mass VX0 VY0 VZ0" card in place of the "XM YM ZM" card.
    """
    rwid: int
    title: str
    nsid: int
    nsidex: int
    xt: float; yt: float; zt: float
    xh: float; yh: float; zh: float
    fric: float = 0.0
    birth: float = 0.0
    death: float = 0.0
    offset: float = 0.0
    # *DEFINE_BOX id scoping the tracked ("slave") node group. Resolved to a
    # /GRNOD of the in-box nodes by the writer; dropped (with a warning) when
    # NSID is also given, matching dyna2rad (NSID wins).
    boxid: int = 0
    # _MOVING option
    moving: bool = False
    mass: float = 0.0
    v0: float = 0.0
    node_id: int = 0            # synthesized carrier node (writer prepass)
    # _FINITE option
    finite: bool = False
    xhev: float = 0.0; yhev: float = 0.0; zhev: float = 0.0
    lenl: float = 0.0
    lenm: float = 0.0


@dataclass
class RigidWallGeomFace:
    """One emitted Radioss wall of a *RIGIDWALL_GEOMETRIC conversion.

    A CYLINDER/SPHERE/FLAT wall resolves to exactly one face; a PRISM (a box,
    which Radioss has no single card for) resolves to six ``/RWALL/PARAL``
    faces with outward normals. Filled in by the writer prepass
    ``_resolve_geometric_rigid_walls`` so the geometry warnings are raised
    once and the carrier nodes exist before the /NODE section is built.

    ``form`` is the Radioss keyword tail (PLANE / PARAL / CYL / SPHER); ``m``
    is the base point (unused when ``node_id`` > 0 — the carrier node's
    coordinates ARE M then); ``m1``/``m2`` are the absolute card-4/card-5
    points (``m2`` only for PARAL, ``m1`` None for SPHER).

    Also the emission record for a *RIGIDWALL_PLANAR wall, so both families
    go through one card writer (``_emit_rwall_geom_face``): ``mass``/``v0``
    fill the moving form's "Mass VX0 VY0 VZ0" card, which a _MOVING planar
    wall uses and a geometric _MOTION wall leaves at zero.
    """
    rwid: int
    title: str
    form: str
    m: Tuple[float, float, float]
    m1: Optional[Tuple[float, float, float]] = None
    m2: Optional[Tuple[float, float, float]] = None
    diameter: float = 0.0
    node_id: int = 0            # synthesized carrier node (_MOTION walls)
    mass: float = 0.0                                   # moving form only
    v0: Tuple[float, float, float] = (0.0, 0.0, 0.0)    # moving form only


@dataclass
class RigidWallGeometric:
    """*RIGIDWALL_GEOMETRIC_{FLAT|PRISM|CYLINDER|SPHERE}[_MOTION][_DISPLAY].

    Card 1: nsid nsidex boxid birth death
    Card 2: xt yt zt xh yh zh fric   — (xt,yt,zt) is the tail T, the wall's
      anchor point; n̂ = normalize(head − tail) is the outward normal /
      cylinder axis.
    Card 3 (shape-specific):
      _FLAT     xhev yhev zhev lenl lenm
      _PRISM    xhev yhev zhev lenl lenm lenp
      _CYLINDER radcyl lencyl nsegs   (+ nsegs "vl height" sub-cards)
      _SPHERE   radsph
    Card 4 (_MOTION):  lcid opt vx vy vz — opt 0 = velocity, else displacement;
      (vx,vy,vz) are DIRECTION COSINES, the curve carries the amplitude.
    Card 5 (_DISPLAY): pid ro e pr — visualization mesh only, no solution
      effect (Manual p. 3669), so it is parsed away and dropped.

    RADCYL/RADSPH are RADII while the Radioss card field is a DIAMETER
    (starter hm_read_rwall_cyl.F:272 / hm_read_rwall_spher.F:243 both halve
    it), so Phi = 2 x RAD. The resolved Radioss walls live in ``faces``.
    """
    rwid: int
    title: str
    shape: str                  # FLAT | PRISM | CYLINDER | SPHERE
    nsid: int = 0
    nsidex: int = 0
    boxid: int = 0
    birth: float = 0.0
    death: float = 0.0
    xt: float = 0.0; yt: float = 0.0; zt: float = 0.0
    xh: float = 0.0; yh: float = 0.0; zh: float = 0.0
    fric: float = 0.0
    # FLAT / PRISM card 3
    xhev: float = 0.0; yhev: float = 0.0; zhev: float = 0.0
    lenl: float = 0.0
    lenm: float = 0.0
    lenp: float = 0.0
    # CYLINDER card 3
    radcyl: float = 0.0
    lencyl: float = 0.0
    nsegs: int = 0
    # SPHERE card 3
    radsph: float = 0.0
    # _MOTION card
    motion: bool = False
    lcid: int = 0
    opt: int = 0
    vx: float = 0.0; vy: float = 0.0; vz: float = 0.0
    # writer prepass results
    faces: List["RigidWallGeomFace"] = field(default_factory=list)


@dataclass
class LoadRigidBody:
    """*LOAD_RIGID_BODY — force/moment applied to a rigid body part."""
    pid: int            # rigid body part ID
    dof: int            # 1=Fx,2=Fy,3=Fz,4=|F|,5=Mx,6=My,7=Mz
    lcid: int           # load curve
    sf: float           # scale factor
    cid: int            # coordinate system (0=global)


@dataclass
class ContactAutoSingle:
    inter_id: int
    title: str
    ssid: int           # slave set / part / 0=all
    sstyp: int          # 0=seg,2=partset,3=part,5=all
    fs: float           # static friction
    fd: float           # dynamic friction
    bt: float           # birth time
    dt: float           # death time
    ignore: int = 0     # LS-DYNA optional Card E: 0=push apart, 1=track, 2=accept gap
    vdc: float = 0.0    # LS-DYNA Card2 viscous damping coeff (% of critical) → VisS
    sst: float = 0.0    # LS-DYNA Card3 SST/SAST: contact thickness, secondary side → Gapmin
    mst: float = 0.0    # LS-DYNA Card3 MST/SBST: contact thickness, main side → Gapmin
    sfs: float = 0.0    # LS-DYNA Card3 SFS: slave penalty stiffness scale → Stfac (1.0/0/blank = default)
    # Source *CONTACT spelling, kept verbatim so the writer can name the exact
    # keyword when it has to report an interface it could not emit (the
    # conversion log's "Recognized but not emitted" tally). "" = synthesized by
    # k2rad itself (the implicit-stabilization self-contact), which has no
    # originating keyword to report.
    keyword: str = ""


@dataclass
class ContactAutoSurf2Surf:
    inter_id: int
    title: str
    ssid: int; sstyp: int
    msid: int; mstyp: int
    fs: float; fd: float
    bt: float; dt: float
    ignore: int = 0     # LS-DYNA optional Card E: 0=push apart, 1=track, 2=accept gap
    vdc: float = 0.0    # LS-DYNA Card2 viscous damping coeff (% of critical) → VisS
    sst: float = 0.0    # LS-DYNA Card3 SST: contact thickness, secondary side → Gapmin
    mst: float = 0.0    # LS-DYNA Card3 MST: contact thickness, main side → Gapmin
    sfs: float = 0.0    # LS-DYNA Card3 SFS: slave penalty stiffness scale → Stfac (1.0/0/blank = default)
    keyword: str = ""   # source *CONTACT spelling — see ContactAutoSingle.keyword


@dataclass
class ContactAutoGeneral:
    """*CONTACT_AUTOMATIC_GENERAL whose LS-DYNA optional-Card-A ``SOFT`` field
    carries a dyna2rad sentinel (-7 / -11 / -19) that routes it to a specific
    OpenRadioss interface, instead of the ordinary single-surface self-contact.

    dyna2rad (``convertcontacts.cxx`` cc:133-164) reads ``LSDYNA_SOFT`` and:
      * SOFT == -7  → /INTER/TYPE7  (node-group → surface penalty self-contact)
      * SOFT == -11 → /INTER/TYPE11 (edge-to-edge / line contact)
      * SOFT == -19 → /INTER/TYPE19 (combined surface + edge contact)
      * anything else (0/1/2/…) → the default (handled by ``ContactAutoSingle``
        → /INTER/TYPE25 explicit or /INTER/TYPE7 implicit, unchanged).

    Only the three sentinel-routed cases land here; the default case is appended
    to ``contacts_single`` so the validated single-surface path is byte-for-byte
    unchanged. When ``msid`` is 0 the contact is self-contact and the writer
    mirrors ``ssid`` onto the main side (dyna2rad cc:139-163).
    """
    inter_id: int
    title: str
    ssid: int; sstyp: int
    msid: int; mstyp: int
    soft: int               # -7 → TYPE7, -11 → TYPE11, -19 → TYPE19
    fs: float; fd: float    # static / dynamic friction (fs → scalar Fric)
    bt: float; dt: float    # birth / death time
    ignore: int = 0         # optional Card E IGNORE → Inacti (via _ignore_to_inacti)
    vdc: float = 0.0        # Card2 viscous damping (% critical) → VisS
    sst: float = 0.0        # Card3 SST contact thickness, secondary → Gapmin
    mst: float = 0.0        # Card3 MST contact thickness, main → Gapmin
    sfs: float = 0.0        # Card3 SFS slave penalty stiffness scale → Stfac
    sfst: float = 0.0       # Card3 SFST thickness scale (airbag route only)
    # *CONTACT_AIRBAG_SINGLE_SURFACE rather than *CONTACT_AUTOMATIC_GENERAL.
    # Same SOFT = -19 -> /INTER/TYPE19 routing (dyna2rad branches on the same
    # sentinel for both, convertcontacts.cxx:167-181), but the airbag flavour
    # carries four different interface settings — Istf=4, Idel=2, Ibag=1 and
    # a scale-weighted Gapmin — see writer/contacts.py.
    airbag: bool = False
    keyword: str = ""


@dataclass
class ContactTied:
    """*CONTACT_TIED_* — a tied (glued) contact → OpenRadioss /INTER/TYPE2.

    The tie is kinematic in both codes: each secondary (slave) node is rigidly
    stuck to its main (master) segment at initialization. ``variant`` keeps the
    LS-DYNA flavour so the writer can pick the /INTER/TYPE2 Spotflag:

      * NODES_TO_SURFACE / SHELL_EDGE_TO_SURFACE → Spotflag=1 (spotweld
        formulation: the node-to-projection offset is carried by a rigid link
        with constant stiffness — the laser-weld / rivet use case).
      * SURFACE_TO_SURFACE → Spotflag=5 (standard formulation — the
        mesh-transition glue it is used for in LS-DYNA).

    ``sst``/``mst`` are the Card-3 contact thicknesses: LS-DYNA gives a
    NEGATIVE value the special meaning "absolute tie-criterion distance", which
    the writer honours as a floor on the /INTER/TYPE2 dsearch.

    ``sfst``/``sfmt`` (Card-3 scale factors on SST/MST) drive the dyna2rad
    kinematic-vs-penalty discriminator (``convertcontacts.cxx`` cc:220):
    ``(SFST*SST + SFMT*MST)/2 < 0`` → penalty tie /INTER/TYPE10, otherwise the
    kinematic tie /INTER/TYPE2. A negative SST/MST with a nonzero SFST/SFMT is
    LS-DYNA's "maintain the physical offset" flag, which dyna2rad maps to the
    penalty TYPE10 (physical gap kept) rather than TYPE2 (secondary nodes
    projected onto the main segment). ``sfs``/``sfm`` (Card-3 penalty stiffness
    scales) size the TYPE10 GAP.
    """
    inter_id: int
    title: str
    ssid: int; sstyp: int   # slave side: 4=node set, 3=part, 2=part set, 0=segment set
    msid: int; mstyp: int   # master side: 0=segment set, 3=part, 2=part set
    variant: str            # "NODES_TO_SURFACE" | "SURFACE_TO_SURFACE" | "SHELL_EDGE_TO_SURFACE"
    offset: bool = False    # _OFFSET / _CONSTRAINED_OFFSET / _BEAM_OFFSET keyword flavour
    sst: float = 0.0        # Card3 SST (negative = absolute tie distance)
    mst: float = 0.0        # Card3 MST (negative = absolute tie distance)
    sfs: float = 0.0        # Card3 SFS (secondary penalty stiffness scale)
    sfm: float = 0.0        # Card3 SFM (main penalty stiffness scale)
    sfst: float = 0.0       # Card3 SFST (scale on SST) — TYPE10 discriminator term
    sfmt: float = 0.0       # Card3 SFMT (scale on MST) — TYPE10 discriminator term
    # Card2 FS. Friction is meaningless on a tie and is NOT carried over — this
    # is kept only so the writer can spot FS=-2 (*DEFINE_FRICTION reference) and
    # say out loud that neither /INTER/TYPE2 nor /INTER/TYPE10 has a fric_ID
    # column to bind the table to.
    fs: float = 0.0


@dataclass
class ContactSpotweld:
    """*CONTACT_SPOTWELD[_WITH_TORSION|_BEAM_OFFSET|_CONSTRAINED_OFFSET]
    [_PENALTY][_MPP][_ID] → OpenRadioss /INTER/TYPE2 with Spotflag=28.

    LS-DYNA's spotweld contact ties the nodes of the WELD elements (the MAT_100
    beam nuggets, SSTYP=3 naming their part) to the surface of the sheets they
    join (MSTYP=2, a *SET_PART_LIST). Without it the weld beams reach the
    solver attached to nothing but each other and carry zero force.

    Kept in its own dataclass rather than as a fourth ``ContactTied.variant``
    because three of its field values differ from every *CONTACT_TIED_*:

      * ``Idel2 = 1`` — dyna2rad's spotweld default (convertcontacts.cxx:49
        ``interTypeVsMapDefaultVals["TYPE2"] = {Ignore 2, Idel2 1, Spotflag 28}``),
        so the tie dies with the sheet segment it is welded to instead of
        holding a deleted element in place. The tied path emits Idel2=0.
      * the secondary side is resolved over BEAM elements too — a weld part is
        beams, and the tied resolver walks shells and solids only.
      * ``dsearch`` comes from the card (0.6*(SST+MST)), never from a measured
        node-to-segment distance: for a spotweld the secondary side IS the weld,
        so there is no tie surface to measure against.

    ``variant`` records the keyword flavour purely for reporting — dyna2rad
    parses ContactOption 2/3/4 (_WITH_TORSION / _BEAM_OFFSET /
    _CONSTRAINED_OFFSET) in the CFG and then never reads it, so all five
    spellings produce byte-identical output there. k2rad emits the same card
    and WARNS about the dropped flavour instead of dropping it silently.
    """
    inter_id: int
    title: str
    ssid: int; sstyp: int   # secondary: 3=part (the weld part), 2=part set, 4=node set
    msid: int; mstyp: int   # main: 2=part set (the joined sheets), 3=part, 0=segment set
    variant: str            # "" | "WITH_TORSION" | "BEAM_OFFSET" | "CONSTRAINED_OFFSET"
    penalty: bool = False   # _PENALTY keyword flavour
    mpp: bool = False       # _MPP keyword flavour (extra MPP card(s) before Card 1)
    sst: float = 0.0        # Card3 SST (negative = absolute tie-criterion distance)
    mst: float = 0.0        # Card3 MST (negative = absolute tie-criterion distance)


@dataclass
class ContactType25:
    """The *CONTACT families dyna2rad routes to **/INTER/TYPE25**:

      * ``*CONTACT_ERODING_SINGLE_SURFACE``     (``variant="SINGLE_SURFACE"``)
      * ``*CONTACT_ERODING_SURFACE_TO_SURFACE`` (``variant="SURFACE_TO_SURFACE"``)
      * ``*CONTACT_ERODING_NODES_TO_SURFACE``   (``variant="NODES_TO_SURFACE"``)
      * ``*CONTACT_NODES_TO_SURFACE`` and ``*CONTACT_AUTOMATIC_NODES_TO_SURFACE``
        (``variant="NODES_TO_SURFACE"``, ``eroding=False``)

    They share one dataclass because they share one target card and every field
    of it — ``eroding`` only gates (a) the mandatory ERODING Card 4
    (ISYM/EROSOP/IADJ), which shifts the optional-card stack down by one line,
    and (b) whether the solid side's /SURF is built with ``ALL`` (interior faces
    included) instead of ``EXT``.

    dyna2rad reaches TYPE25 for all of them through
    ``convertcontacts.cxx:117-131`` (ERODING_SINGLE/SURFACE_TO_SURFACE and
    AUTOMATIC_NODES_TO_SURFACE) and ``:212-216`` (the generic
    ``find("NODES_TO_SURFACE")`` branch, which is where plain NODES_TO_SURFACE
    and ERODING_NODES_TO_SURFACE land).

    Side topology follows the starter's ILEV classification
    (``hm_read_inter_type25.F:399-434``):

      * SINGLE_SURFACE     → ``surf_ID1`` = SSID surface, ``surf_ID2`` = 0
        (ILEV=1, self-impact of one surface).
      * SURFACE_TO_SURFACE → ``surf_ID1`` = SSID, ``surf_ID2`` = MSID (ILEV=2,
        symmetric).
      * NODES_TO_SURFACE   → ``surf_ID1`` = 0, ``surf_ID2`` = MSID surface,
        ``grnd_IDs`` = the SSID node group (ILEV=3) — a genuine ONE-WAY
        node-to-surface contact. dyna2rad does NOT symmetrize this family
        (``surfAttrNames[0] = "grnd_IDs"``), so neither does k2rad.

    ``isym``/``erosop``/``iadj`` are the ERODING Card-4 fields. dyna2rad parses
    them in the CFG and then discards all three with no message
    (``grep EROSOP|IADJ|ISYM`` over the whole dyna2rad tree: zero hits) — k2rad
    WARNS about all three (``_warn_eroding_card4``) but acts on none of them:
    the solid side is built with /SURF/PART/ALL whenever the contact is eroding
    (``writer/contacts.py`` ``_type25_surface``, ``if c.eroding and
    solid_pids``), i.e. IADJ is assumed to be 1 unconditionally, which is what
    MPP hardcodes. The only lever is the global ``--eroding-surf-ext``; a deck
    mixing an IADJ=0 and an IADJ=1 eroding contact cannot be expressed.
    """
    inter_id: int
    title: str
    ssid: int; sstyp: int
    msid: int; mstyp: int
    variant: str            # "SINGLE_SURFACE" | "SURFACE_TO_SURFACE" | "NODES_TO_SURFACE"
    eroding: bool = False   # *CONTACT_ERODING_* (mandatory Card 4 present)
    fs: float = 0.0         # Card2 FS: static friction, or -1/-2/2 sentinel
    fd: float = 0.0         # Card2 FD: dynamic friction, or a *DEFINE_FRICTION id when FS=-2
    dc: float = 0.0         # Card2 DC: exponential decay coefficient
    bt: float = 0.0         # Card2 BT: birth time  → Tstart
    dt: float = 0.0         # Card2 DT: death time  → Tstop
    vdc: float = 0.0        # Card2 VDC: viscous damping (% critical) → VISs
    sfs: float = 0.0        # Card3 SFS: secondary penalty stiffness scale → Stfac
    sfm: float = 0.0        # Card3 SFM: main penalty stiffness scale
    sst: float = 0.0        # Card3 SST: secondary contact thickness
    mst: float = 0.0        # Card3 MST: main contact thickness
    fsf: float = 1.0        # Card3 FSF: Coulomb friction scale (mu_sc = FSF * mu_c)
    isym: int = 0           # ERODING Card4 ISYM   (1 = drop symmetry-plane faces)
    erosop: int = 1         # ERODING Card4 EROSOP (hardcoded 1 in LS-DYNA)
    iadj: int = 0           # ERODING Card4 IADJ   (1 = material-subset boundary faces)
    soft: int = 0           # optional Card A SOFT (dyna2rad -7/-11/-19 sentinels)
    ignore: int = 0         # optional Card C IGNORE → Inacti
    keyword: str = ""       # source *CONTACT spelling — see ContactAutoSingle.keyword


@dataclass
class FrictionPair:
    """One ``*DEFINE_FRICTION`` Card-2 row → one /FRICTION part-pair block."""
    pid_i: int              # PIDi  (part id, or *SET_PART id when pset_i)
    pid_j: int              # PIDj
    fs: float = 0.0         # FSij static friction
    fd: float = 0.0         # FDij dynamic friction
    dc: float = 0.0         # DCij exponential decay coefficient
    vc: float = 0.0         # VCij viscous friction (shear-stress cap)
    pset_i: bool = False    # PTYPEi == "PSET"  → grpart_ID1 rather than part_ID1
    pset_j: bool = False    # PTYPEj == "PSET"


@dataclass
class DefineFriction:
    """*DEFINE_FRICTION → /FRICTION (id preserved 1:1, which is what makes the
    interfaces' ``fric_ID`` binding work — dyna2rad ``convertfrictions.cxx:57``
    creates the entity with ``selFriction->GetId()``).

    LS-DYNA's law is ``mu_c = FD + (FS - FD) * exp(-DC * |v_rel|)``
    (Vol I p.17-280). Radioss ``Ifric=2`` (Darmstad,
    ``engine/.../i7for3.F:1911-1914``) evaluates

        XMU = Fric + C1*e^(C2*v)*p^2 + C3*e^(C4*v)*p + C5*e^(C6*v)

    so with ``C1..C4 = 0`` and ``Fric = FD``, ``C5 = FS - FD``, ``C6 = -DC``
    the two are algebraically IDENTICAL. That is dyna2rad's mapping
    (``convertfrictions.cxx:94-97``) and it is also the only 2022-legal one:
    Radioss's own exponential-decay law ``Ifric=4`` would need one fewer sign
    flip but does not exist before radioss2023 (``radioss2020/FRICTION/
    friction.cfg:87-93`` offers 0-3; the 2022 Reference Guide p.223 likewise).

    The Card-1 defaults become the /FRICTION header row — the fallback friction
    for every part pair not listed (the engine seeds every contact pair from it,
    ``frictionparts_model.F:88-92``).
    """
    fric_id: int
    title: str
    fs: float = 0.0         # FS_D default static friction
    fd: float = 0.0         # FD_D default dynamic friction
    dc: float = 0.0         # DC_D default decay coefficient
    vc: float = 0.0         # VC_D default viscous friction
    icnep: int = 0          # 0 = a missing PID is an error, 1 = ignore that row
    pairs: List["FrictionPair"] = field(default_factory=list)


@dataclass
class HexSpotweldAssembly:
    """*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N] → /CLUSTER/BRICK + its /GRBRIC/BRIC.

    A group of up to 16 solid elements that together form ONE spot weld. In
    LS-DYNA the assembly is what *MAT_SPOTWELD's failure resultants act on (the
    forces are summed over the whole nugget, not per element); OpenRadioss
    spells the same construct /CLUSTER/BRICK — a force/moment monitor around a
    brick group that deletes every element of the group at once when its
    failure surface is reached.

    ``sw_id`` is LS-DYNA's ID_SW, reused verbatim as the /CLUSTER id.
    """
    sw_id: int
    title: str
    eids: List[int]         # the assembly's solid element ids, in card order


@dataclass
class ContactForceTransducer:
    """*CONTACT_FORCE_TRANSDUCER[_PENALTY] — a measurement-only "contact" that
    reports the contact force already acting on a surface/part from the model's
    *real* contacts. It adds NO stiffness. Maps to OpenRadioss /INTER/SUB, a
    sub-interface of an existing parent interface that outputs the forces applied
    by a secondary node group on a main surface (read out via /TH/SUBS)."""
    inter_id: int       # transducer id (used as the /INTER/SUB sub-interface id)
    title: str
    surfa: int          # SURFA (LS-DYNA secondary side id)
    surfb: int          # SURFB (LS-DYNA main side id)
    satyp: int          # SURFA type: 0=seg,2=partset,3=part,5=all
    sbtyp: int          # SURFB type


@dataclass
class InitialVelocityNode:
    nid: int
    vx: float; vy: float; vz: float
    vxr: float; vyr: float; vzr: float


@dataclass
class InitialVelocityRigidBody:
    pid: int
    vx: float; vy: float; vz: float
    vxr: float; vyr: float; vzr: float


@dataclass
class InitialVelocity:
    """*INITIAL_VELOCITY (base set form) → /INIVEL/TRA (+ /INIVEL/ROT).

    Raw ids only; the writer resolves nsid/nsidex against state.node_sets and
    icid against the converted /SKEW ids (set difference for NSIDEX)."""
    nsid: int; nsidex: int; boxid: int; irigid: int; icid: int
    vx: float; vy: float; vz: float
    vxr: float; vyr: float; vzr: float


@dataclass
class InitialVelocityGeneration:
    """*INITIAL_VELOCITY_GENERATION → /INIVEL/AXIS + companion /FRAME/FIX.

    sid/styp select the scoped group (0=all, 1=part set, 2=part, 3=node set).
    When nx == -999 the axis is node-defined: node1/node2 give origin/direction
    and nx/ny/nz are ignored."""
    sid: int; styp: int; omega: float
    vx: float; vy: float; vz: float
    ivatn: int; icid: int
    xc: float; yc: float; zc: float
    nx: float; ny: float; nz: float
    node1: int; node2: int
    phase: int; irigid: int


@dataclass
class MatPowerLaw:
    """*MAT_POWER_LAW_PLASTICITY → /MAT/LAW36 with auto-generated curve."""
    mid: int; title: str
    rho: float; E: float; nu: float
    k: float; n: float
    src: float; srp: float
    sigy: float; vp: int; epsf: float
    funct_id: int = 0


@dataclass
class MatCrushableFoam:
    """*MAT_CRUSHABLE_FOAM (MAT_063) → /MAT/LAW50 (VISC_HONEY, isotropic use).

    LS-DYNA card (Keyword971 mat_063.cfg): MID RHO E PR LCID TSC DAMP. LCID is the
    yield stress vs volumetric strain curve; the single curve drives all six
    LAW50 direction yield functions (σ11/σ22/σ33/σ12/σ23/σ31 identical → isotropic).
    LAW50's radioss90 FORMAT has no tensile-cutoff or rate-damping slot, so TSC and
    DAMP are reported and dropped by the writer.
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    lcid: int          # yield stress vs volumetric strain curve → all 6 fct_IDs
    tsc: float         # tensile stress cutoff (no LAW50 slot → warned)
    damp: float        # rate damping (no LAW50 slot → warned)


@dataclass
class MatLowDensityFoam:
    """*MAT_LOW_DENSITY_FOAM (MAT_057) → /MAT/LAW38 (VISC_TAB).

    LS-DYNA card (Keyword971 mat_057.cfg):
      Card1: MID RHO E LCID TC HU BETA DAMP
      Card2: SHAPE FAIL BVFLAG ED BETA1 KCON REF
    E → LAW38 E0; LCID → the (single) loading function; TC → LAW38 CUToff (tension
    cutoff stress). LAW38 has no direct hysteretic-unloading factor, unloading
    decay or shape factor, so HU / BETA / SHAPE / DAMP are approximate/dropped and
    warned by the writer.
    """
    mid: int
    title: str
    rho: float
    E: float
    lcid: int          # nominal stress vs strain loading curve → LAW38 loading fct
    tc: float          # tension cutoff → LAW38 CUToff
    hu: float          # hysteretic unloading factor (approximate in LAW38)
    beta: float        # unloading decay constant (no LAW38 slot → warned)
    damp: float        # viscous damping (no LAW38 slot → warned)
    shape: float       # unloading shape factor (no LAW38 slot → warned)


@dataclass
class MatFuChangFoam:
    """*MAT_FU_CHANG_FOAM (MAT_083) → /MAT/LAW70 (FOAM_TAB). APPROXIMATE.

    LS-DYNA card (Keyword971_R11.1 mat_083.cfg):
      Card1: MID RHO E ED TC FAIL DAMP TBID
      Card2: BVFLAG SFLAG RFLAG TFLAG PVID SRAF REF HU
      Card3: (analytic form) D0 N0 N1 N2 N3 C0 C1 C2 / C3 C4 C5 AIJ SIJ MINR MAXR SHAPE
    E → LAW70 E0; TBID → the load-curve family (a *DEFINE_TABLE of nominal
    stress-strain curves at several strain rates) mapped onto LAW70's per-rate
    loading functions; HU → LAW70 Hys; SHAPE → LAW70 Shape. Fu-Chang's analytic
    hysteresis/damping constants (D0..C5, DAMP) have no LAW70 equivalent → warned.
    """
    mid: int
    title: str
    rho: float
    E: float
    tc: float          # tension cutoff (no scalar LAW70 slot → warned)
    damp: float        # rate damping (no LAW70 slot → warned)
    tbid: int          # load-curve family (table/curve) → LAW70 loading function(s)
    hu: float          # hysteretic unloading factor → LAW70 Hys
    shape: float       # unloading shape factor → LAW70 Shape


@dataclass
class MatHoneycomb:
    """*MAT_HONEYCOMB (MAT_026) → /MAT/LAW28 (HONEYCOMB).

    LS-DYNA card (Keyword971 mat_026.cfg):
      Card1: MID RO E PR SIGY VF MU BULK
      Card2: LCA LCB LCC LCS LCAB LCBC LCCA LCSR
      Card3: EAAU EBBU ECCU GABU GBCU GCAU AOPT MACF
    Per-direction uncompressed moduli EAAU/EBBU/ECCU → LAW28 E_11/E_22/E_33 and
    GABU/GBCU/GCAU → G_12/G_23/G_31 (a/b/c ↔ 11/22/33). Normal yield functions
    LCA/LCB/LCC → fun_ID11/22/33; shear yield functions LCAB/LCBC/LCCA → fun_ID12/
    23/31 (with the LCS transverse-shear curve as the fallback for any missing
    shear component). LAW28 has no fully-compacted modulus / SIGY / VF / MU / BULK /
    LCSR slot, so E, SIGY, VF, MU, BULK and LCSR are reported and dropped.
    """
    mid: int
    title: str
    rho: float
    E: float           # fully-compacted Young's modulus (no LAW28 slot → warned)
    nu: float
    sigy: float        # compacted yield stress (no LAW28 slot → warned)
    vf: float          # relative volume at full compaction (no LAW28 slot → warned)
    mu: float          # viscosity coefficient (no LAW28 slot → warned)
    bulk: float        # bulk viscosity (no LAW28 slot → warned)
    eaau: float        # uncompressed Young's moduli
    ebbu: float
    eccu: float
    gabu: float        # uncompressed shear moduli
    gbcu: float
    gcau: float
    lca: int           # normal crush curves (aa/bb/cc)
    lcb: int
    lcc: int
    lcs: int           # transverse shear crush curve (fallback for LCAB/BC/CA)
    lcab: int          # shear crush curves (ab/bc/ca)
    lcbc: int
    lcca: int
    lcsr: int          # strain-rate scaling curve (no LAW28 slot → warned)


@dataclass
class MatSoilAndFoam:
    """*MAT_SOIL_AND_FOAM (MAT_005) → /MAT/LAW21 (DPRAG).

    LS-DYNA cards (mat_005.cfg Keyword971_R6.1):
      Card1: MID RO G KUN A0 A1 A2 PC
      Card2: VCR REF LCID
      Card3-4: EPS1..EPS10   Card5-6: P1..P10
    E and Nu are derived from G/KUN (dyna2rad CM:742-757); A0/A1/A2 transfer
    coefficient-for-coefficient (identical yield surface phi = J2 - (a0 + a1*p
    + a2*p^2)); PC → P_min verbatim (both are the negative tension cutoff).
    The pressure curve (LCID preferred, else the EPS/P pairs) needs the
    abscissa transform mu = exp(-EPS) - 1: LS-DYNA tabulates P against
    EPS = ln(V/V0) (negative in compression), the LAW21 engine evaluates the
    function at mu = rho/rho0 - 1 = V0/V - 1 (positive in compression,
    mmain.F90:686-692) — resolved by the writer prepass.
    """
    mid: int
    title: str
    rho: float
    g: float           # shear modulus → E/Nu via 9GK/(3K+G), (3K-2G)/(6K+2G)
    kun: float         # bulk unloading modulus → B and Kt (KUN/100 for VCR=1)
    a0: float          # yield coefficients, 1:1 → A0/A1/A2
    a1: float
    a2: float
    pc: float          # tension cutoff pressure (< 0) → P_min verbatim
    vcr: float         # 1.0 = no volumetric crushing → B = 0 (dyna2rad)
    ref: float         # 1.0 = init from *INITIAL_FOAM_REFERENCE_GEOMETRY
    lcid: int          # pressure vs volumetric strain curve (preferred source)
    eps: List[float] = field(default_factory=list)   # up to 10 ln(V/V0) values
    p: List[float] = field(default_factory=list)     # up to 10 pressures
    func_id: int = 0   # resolved /FUNCT id of the transformed P(mu) curve
    # Writer-resolved elastic constants (set by _resolve_mat_soil_and_foam so
    # the clamp warning and the emitted values cannot drift apart):
    e_res: float = 0.0     # E = 9GK/(3K+G)
    nu_res: float = 0.0    # (3K-2G)/(6K+2G) clamped to [0, 0.495]


@dataclass
class MatLowDensityViscousFoam:
    """*MAT_LOW_DENSITY_VISCOUS_FOAM (MAT_073) → /MAT/LAW90 [+ /VISC/PRONY].

    LS-DYNA cards (mat_073.cfg Keyword971_R6.1):
      Card1: MID RO E LCID TC HU BETA DAMP
      Card2: SHAPE FAIL BVFLAG KCON LCID2 BSTART TRAMP NV
      Card3a (iff LCID2 == 0, up to 6): Gi BETAi REF
      Card3b (iff LCID2 == -1): LCID3 LCID4 SCALEW SCALEA
      (LCID2 > 0: no card 3 at all — LS-DYNA least-squares fits Gi/BETAi
       from the LCID2 relaxation curve; neither dyna2rad nor k2rad fits.)
    E → E0, LCID → the single loading function, HU → Hys, SHAPE → Shape
    (dyna2rad CM:4275-4338); the explicit Gi/BETAi pairs with BETAi > 0
    become a /VISC/PRONY of the same id.
    """
    mid: int
    title: str
    rho: float
    E: float
    lcid: int          # nominal stress vs strain loading curve → fct_IDL row 1
    tc: float          # tension cutoff (LAW90 Tcut is radioss2026-only → warned)
    hu: float          # hysteretic unloading factor → LAW90 Hys
    beta: float        # HU decay constant (no LAW90 slot → warned)
    damp: float        # viscous damping (dyna2rad moves it onto the prop → warned)
    shape: float       # unloading shape factor → LAW90 Shape
    fail: float        # tension behaviour flag (LAW90 FAIL is 2026-only → warned)
    bvflag: float      # bulk-viscosity activation flag (dropped → warned)
    kcon: float        # contact stiffness modulus (LAW90 Kcont is 2026-only)
    lcid2: int         # 0 = explicit Gi/BETAi; >0 = fit branch; -1 = freq data
    bstart: float      # fit-branch parameters (unsupported branch)
    tramp: float
    nv: int
    prony: List[Tuple[float, float, float]] = field(default_factory=list)  # (Gi, BETAi, REF)
    lcid3: int = 0     # LCID2 == -1 frequency-data branch (unsupported)
    lcid4: int = 0
    ref: float = 0.0   # 1.0 when any Gi card's REF flag is on (registry hook)


@dataclass
class MatModifiedHoneycomb:
    """*MAT_MODIFIED_HONEYCOMB (MAT_126) → /MAT/LAW50 (VISC_HONEY) on a
    synthesized orthotropic /PROP/TYPE6 (SOL_ORTH).

    LS-DYNA cards (Manual Vol II R17 p.2-886; the Keyword971 cfg is behind it):
      Card1: MID RO E PR SIGY VF MU BULK
      Card2: LCA LCB LCC LCS LCAB LCBC LCCA LCSR
      Card3: EAAU EBBU ECCU GABU GBCU GCAU AOPT MACF
      Card4: XP YP ZP A1 A2 A3 RFAC PRU
      Card5: D1 D2 D3 TSEF SSEF VREF TREF SHDFLG
      Card6 (iff AOPT 3/4): V1 V2 V3
      Card7 (iff LCSR == -1): LCSRA LCSRB LCSRC LCSRAB LCSRBC LCSRCA
      Card8 (iff PRU == 2): PRUAB PRUAC PRUBC PRUBA PRUCA PRUCB
    Slot order and fallbacks follow dyna2rad (CM:1744-1815 + 8923-9213); the
    per-direction curve wiring, the V/V0-abscissa transform and the LCSR rate
    sampling are resolved by the writer prepass into fun_ids/rates/scales.
    """
    mid: int
    title: str
    rho: float
    E: float           # compacted modulus → LAW50 compaction card (2025-only → warned)
    nu: float
    sigy: float        # compacted yield (2025-only compaction card → warned)
    vf: float          # relative compaction volume (2025-only → warned)
    mu: float          # viscosity coefficient (no LAW50 slot → warned)
    bulk: float        # bulk viscosity flag (no LAW50 slot → warned)
    lca: int           # < 0 selects the transversely isotropic yield surface
    lcb: int
    lcc: int
    lcs: int
    lcab: int
    lcbc: int
    lcca: int
    lcsr: float        # > 0: rate-scale curve; -1: per-direction curve card
    eaau: float        # uncompressed moduli (0 → E / E/2(1+PR) fallbacks)
    ebbu: float
    eccu: float        # < 0 activates the third yield surface (unsupported)
    gabu: float
    gbcu: float
    gcau: float
    aopt: float
    macf: int
    xp: float = 0.0    # AOPT geometry (same field names _composite_ref_axis reads)
    yp: float = 0.0
    zp: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    a3: float = 0.0
    rfac: float = 0.0
    pru: float = 0.0
    d1: float = 0.0
    d2: float = 0.0
    d3: float = 0.0
    tsef: float = 0.0  # tensile failure strain → Eps_max11/22/33 (< 0 = curve id, warned)
    ssef: float = 0.0  # shear failure strain → Eps_max12/23/31 (< 0 = curve id, warned)
    vref: float = 0.0
    tref: float = 0.0
    shdflg: float = 0.0
    v1: float = 0.0
    v2: float = 0.0
    v3: float = 0.0
    lcsr_dirs: List[float] = field(default_factory=list)   # LCSR == -1 card (dropped)
    pru_ratios: List[float] = field(default_factory=list)  # PRU == 2 card (dropped)
    # Writer-resolved wiring: base /FUNCT per LAW50 slot 11/22/33/12/23/31,
    # the sampled (rate, scale) pairs, and the resolved moduli/flags.
    fun_ids: List[int] = field(default_factory=list)
    rates: List[float] = field(default_factory=list)
    scales: List[float] = field(default_factory=list)
    moduli: List[float] = field(default_factory=list)      # E11 E22 E33 G12 G23 G31
    iflag1: int = -1
    iflag2: int = -1


@dataclass
class MatDeshpandeFleckFoam:
    """*MAT_DESHPANDE_FLECK_FOAM (MAT_154) → /MAT/LAW115 (DESHFLECK, Istat=0).

    LS-DYNA cards (mat_154.cfg Keyword971_R6.1):
      Card1: MID RHO E PR ALPHA GAMMA
      Card2: EPSD ALPHA2 BETA SIGP DERFI CFAIL PFAIL NUM
    The direct 1:1 counterpart: same flow law sigma_y = SIGP + GAMMA*(e/EPSD)
    + ALPHA2*ln[1/(1-(e/EPSD)^BETA)], same parameter meanings. CFAIL →
    EPSVP_F, PFAIL → SIGP_F (dyna2rad's cfg never parses PFAIL, so its
    SIGP_F is silently always 0 — k2rad maps it). DERFI (0/1 numerical/
    analytical derivative) is NOT the LAW115 Ires enumeration and is dropped;
    NUM (sustained violation steps) has no counterpart (Radioss fails on the
    first violation).
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    alpha: float       # pressure-sensitivity shape parameter (0 <= a <= sqrt(4.5))
    gamma: float       # linear hardening modulus
    epsd: float        # densification strain
    alpha2: float      # nonlinear hardening modulus
    beta: float        # nonlinear hardening exponent
    sigp: float        # initial flow stress
    derfi: float       # derivative-evaluation flag (dropped → warned)
    cfail: float       # tensile volumetric strain at failure → EPSVP_F
    pfail: float       # max principal stress at failure → SIGP_F
    num: int           # sustained-timestep count for PFAIL (dropped → warned)


@dataclass
class MatHillFoam:
    """*MAT_HILL_FOAM (MAT_177) → /MAT/LAW62 (VISC_HYP), constants branch only.

    LS-DYNA cards (Manual Vol II R17 p.2-1216, and the shipped Keyword971
    mat_177.cfg agrees — field 4 is N, field 5 is MU):
      Card1: MID RO K N MU LCID FITTYPE LCSR
      Card2 (iff LCID == 0): C1..C8    Card3 (iff LCID == 0): B1..B8
      Card4 (optional, both branches): R M
    Hill → Ogden identity per pair: mu_i = Ci*Bi/2, alpha_i = Bi (index-
    aligned — dyna2rad compacts the C and B lists independently and misreads
    B out of range when a Ci is zero mid-list); Nu = N/(1+2N). LCID > 0 (the
    curve-fit branch) has no LAW62 counterpart (LAW62 has no Itab/fit path)
    and is warn-skipped at parse.
    """
    mid: int
    title: str
    rho: float
    k: float           # bulk modulus, card field 3 (LAW62 derives bulk from Nu)
    mu: float          # damping coefficient, card field 5 (no LAW62 slot)
    n: float           # Poisson-like exponent, card field 4 → Nu = N/(1+2N)
    lcid: int
    fittype: int
    lcsr: int          # transverse-stretch curve (no LAW62 slot → warned)
    c: List[float] = field(default_factory=list)   # C1..C8
    b: List[float] = field(default_factory=list)   # B1..B8
    r: float = 0.0     # Mullins-effect card (no LAW62 slot → warned)
    m: float = 0.0
    # Writer-resolved Ogden pairs (index-aligned over the nonzero-C slots):
    mu_i: List[float] = field(default_factory=list)      # C_i*B_i/2
    alpha_i: List[float] = field(default_factory=list)   # B_i


@dataclass
class MatBlatzKo:
    """*MAT_BLATZ-KO_RUBBER (MAT_007) → /MAT/LAW42 fixed form (dyna2rad case 7:
    Mu_1 = G, alpha_1 = 2, Nu = 0.463 — the Blatz-Ko Poisson value LS-DYNA
    hard-codes)."""
    mid: int
    title: str
    rho: float
    g: float             # shear modulus → LAW42 Mu_1
    ref: float = 0.0     # 1.0 = initialize from reference geometry (→ /XREF)


@dataclass
class MatMooneyRivlin:
    """*MAT_MOONEY-RIVLIN_RUBBER (MAT_027) → /MAT/LAW42 (A/B constants) or
    /MAT/LAW69 LAW_ID=2 (LCID least-squares path, fitted by the starter).

    LS-DYNA card (Keyword971 mat_027.cfg):
      Card1: MID RHO PR A B REF
      Card2: SGL SW ST LCID   (uniaxial test data: force vs Δgauge-length)
    """
    mid: int
    title: str
    rho: float
    pr: float            # Poisson's ratio → Nu VERBATIM (no abs, per dyna2rad)
    a: float             # = C10 → Mu_1 = 2A (alpha_1 = 2)
    b: float             # = C01 → Mu_2 = -2B (alpha_2 = -2)
    ref: float = 0.0
    sgl: float = 0.0     # specimen gauge length (never read by dyna2rad)
    sw: float = 0.0      # specimen width
    st: float = 0.0      # specimen thickness
    lcid: int = 0        # test curve: present+parsed → LAW69, else LAW42
    # writer-resolved routing (see _resolve_mat_hyper_rubber)
    use_law69: bool = False
    funidbulk: int = 0   # auto /FUNCT id of the 500-point bulk-scale curve


@dataclass
class MatOgdenRubber:
    """*MAT_OGDEN_RUBBER (MAT_077_O) → /MAT/LAW42 (N=0: direct mu/alpha pairs)
    or /MAT/LAW69 (N>0: the starter fits the pairs from the LCID1 test curve).

    LS-DYNA card (Keyword971 mat_077_O.cfg):
      Card1: MID RO PR N NV G SIGF REF
      N=0 → Card2: MU1..MU8 / Card3: ALPHA1..ALPHA8
      N>0 → Card2: SGL SW ST LCID1 DATA LCID2 BSTART TRAMP
      then free list: GI BETAI (one Prony term per card, until block end)
    """
    mid: int
    title: str
    rho: float
    pr: float                    # → Nu = |PR| (PR<0 = Mullins flag, warned)
    n: int                       # Ogden fit order; 0 = constants given
    nv: int = 0                  # LS-DYNA Prony fit order (informational)
    g: float = 0.0               # freq-independent damping shear modulus
    sigf: float = 0.0            # freq-independent damping limit stress
    ref: float = 0.0
    mu: List[float] = field(default_factory=list)      # MU1..MU8 (N=0)
    alpha: List[float] = field(default_factory=list)   # ALPHA1..ALPHA8 (N=0)
    sgl: float = 0.0
    sw: float = 0.0
    st: float = 0.0
    lcid1: int = 0               # engineering test curve (N>0)
    data: float = 0.0            # 1=Ogden / 2=Mooney fit → LAW69 LAW_ID
    lcid2: int = 0               # relaxation curve (dropped, warned)
    bstart: float = 0.0
    tramp: float = 0.0
    gi: List[float] = field(default_factory=list)      # Prony shear moduli
    betai: List[float] = field(default_factory=list)   # Prony decay constants
    # writer-resolved LAW69 curve id (after the 1/SGL / 1/(SW*ST) duplicate)
    fct_id1: int = 0


@dataclass
class MatHyperelasticRubber:
    """*MAT_HYPERELASTIC_RUBBER (MAT_077_H) → /MAT/LAW95 (N=0: C10..C30
    polynomial) or /MAT/LAW69 (N>0), + /VISC/PRONY from the Gi/BETAi terms.

    LS-DYNA card (Keyword971 mat_077_H.cfg):
      Card1: MID RHO PR N NV G SIGF REF
      N=0 → Card2: C10 C01 C11 C20 C02 C30
      N>0 → Card2: SGL SW ST LCID1 DATA LCID2 BSTART TRAMP
      then free list: Gi BETAi Gj SIGFj (one term per card, until block end)
    """
    mid: int
    title: str
    rho: float
    pr: float
    n: int
    nv: int = 0
    g: float = 0.0               # header damping terms — never read by dyna2rad
    sigf: float = 0.0
    ref: float = 0.0
    c10: float = 0.0
    c01: float = 0.0
    c11: float = 0.0
    c20: float = 0.0
    c02: float = 0.0
    c30: float = 0.0
    sgl: float = 0.0
    sw: float = 0.0
    st: float = 0.0
    lcid1: int = 0
    data: float = 0.0
    lcid2: int = 0
    bstart: float = 0.0
    tramp: float = 0.0
    gi: List[float] = field(default_factory=list)      # → /VISC/PRONY G_i
    betai: List[float] = field(default_factory=list)   # → /VISC/PRONY Beta_i
    gj: List[float] = field(default_factory=list)      # damping columns (dropped)
    sigfj: List[float] = field(default_factory=list)
    fct_id1: int = 0             # writer-resolved LAW69 curve id
    d1: float = 0.0              # writer-resolved LAW95 compressibility |2/K|


@dataclass
class MatViscoelastic:
    """*MAT_VISCOELASTIC (MAT_006) → /MAT/LAW34 (BOLTZMAN).

    LS-DYNA card (Keyword971_R6.1 mat_006.cfg), ONE card:
      MID RHO BULK G0 GI BETA

    G(t) = GI + (G0-GI)·exp(-BETA·t) is LAW34's kernel verbatim
    (sigeps34.F:88-101), so this is an exact 1:1 — BETA is a decay rate (1/time)
    in both codes and needs no conversion.

    From R6.1 on, each of BULK/G0/GI/BETA is a SCALAR_OR_OBJECT: a NEGATIVE
    entry is the negated id of a temperature-dependent *DEFINE_CURVE. LAW34 has
    no temperature slot, so the writer resolve pass collapses such a curve to
    its value at the LOWEST tabulated temperature (dyna2rad's own rule),
    OVERWRITING the negative entry in place — the curve id is not kept, because
    nothing downstream of the collapse can use it.
    """
    mid: int
    title: str
    rho: float
    bulk: float            # → LAW34 K
    g0: float              # → LAW34 G0 (short-time shear modulus)
    gi: float              # → LAW34 Gl (long-time shear modulus)
    beta: float            # → LAW34 Beta (decay constant, 1/time)


@dataclass
class MatKelvinMaxwell:
    """*MAT_KELVIN-MAXWELL_VISCOELASTIC (MAT_061) → /MAT/LAW40 (KELVINMAX).

    LS-DYNA card (Keyword971 mat_061.cfg), ONE card:
      MID RHO BULK G0 GI DC FO SO

    LAW40 is a generalised Maxwell chain, so the single LS-DYNA branch becomes
    G_inf = GI, G1 = G0 - GI, BETA1 = DC and G2..G5 / BETA2..BETA5 = 0.
    Astass/Bstass/Kvm are written 0, which the starter turns into INFINITY,
    i.e. the Stassi/von-Mises yield surface is disabled (hm_read_mat40.F:122).
    """
    mid: int
    title: str
    rho: float
    bulk: float            # → LAW40 K
    g0: float              # instantaneous shear modulus; LAW40 G1 = G0 - GI
    gi: float              # → LAW40 G_inf
    dc: float              # → LAW40 BETA1
    fo: float = 0.0        # 0 = Maxwell (exact map), 1 = Kelvin (no counterpart)
    so: float = 0.0        # d3plot strain-output selector — output-only


@dataclass
class MatGeneralViscoelastic:
    """*MAT_GENERAL_VISCOELASTIC (MAT_076, + _MOISTURE) → /MAT/LAW42 (OGDEN)
    carrier + /VISC/PRONY.

    LS-DYNA cards (Keyword971_R7.1 mat_076.cfg):
      Card1: MID RO BULK PCF EF TREF A B
      Card2: LCID NT BSTART TRAMP LCIDK NTK BSTARTK TRAMPK
             (mandatory in the cfg — blank when the Prony rows below are used)
      Card3: MO ALPHA BETA GAMMA MST          (_MOISTURE only)
      Card4+: GI BETAI KI BETAKI              (FREE_CARD_LIST, up to 18)

    LAW42 has no bulk-modulus field of its own (the starter derives one from
    Nu), so the elastic carrier is dyna2rad's fixed 2-term Ogden ground state
    Mu_1 = +0.01·BULK / Mu_2 = -0.01·BULK / alpha = ±2 / Nu = 0.495. The whole
    Prony series — including the BULK terms dyna2rad drops — rides the separate
    /VISC/PRONY block, which is the only Radioss card carrying all four columns.
    """
    mid: int
    title: str
    rho: float
    bulk: float                  # → the LAW42 Mu_1/Mu_2 ground state
    pcf: float = 0.0             # tensile-pressure cut-off FLAG (no LAW42 slot)
    ef: float = 0.0              # 1 = elastic layer
    tref: float = 0.0            # WLF / Arrhenius shift function — no slot
    a: float = 0.0
    b: float = 0.0
    lcid: int = 0                # G(t) curve  → /VISC/PRONY Itab=1 Ifunc_G
    nt: int = 0                  # shear fit order (blank → 6, max 18)
    bstart: float = 0.0
    tramp: float = 0.0
    lcidk: int = 0               # K(t) curve  → /VISC/PRONY Itab=1 Ifunc_K
    ntk: int = 0
    bstartk: float = 0.0
    trampk: float = 0.0
    moisture: bool = False       # the _MOISTURE card is present (dropped)
    gi: List[float] = field(default_factory=list)      # → /VISC/PRONY G_i
    betai: List[float] = field(default_factory=list)   # → /VISC/PRONY Beta_i
    ki: List[float] = field(default_factory=list)      # → /VISC/PRONY Ki
    betaki: List[float] = field(default_factory=list)  # → /VISC/PRONY Beta_ki
    # writer-resolved /VISC/PRONY shape (0 = no /VISC/PRONY at all)
    prony_m: int = 0
    prony_itab: int = 0


@dataclass
class MatSimplifiedRubber:
    """*MAT_SIMPLIFIED_RUBBER/FOAM (181) and *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE
    (183) → /MAT/LAW88 (TABULATED_HYPERELASTIC) [+ /VISC/PRONY for 181].

    LS-DYNA cards — 181 (Keyword971_R11.1 mat_181.cfg):
      Card1: MID RHO KM MU G SIGF REF PRTEN
      Card2: SGL SW ST LC/TBID TENSION RTYPE AVGOPT PR
      Card3: K GAMA1 GAMA2 EH            (_WITH_FAILURE only)
      Card4: LCUNLD HU SHAPE STOL VISCO HISOUT      (optional)
      Card5+: Gi BETAi VFLAG             (optional free list, up to 12)
    ... and 183 (Keyword971_R8.0 mat_183.cfg), where card 3 is MANDATORY and
    holds something else entirely, and there are no HU/SHAPE/VISCO/Prony cards:
      Card1: MID RHO K MU G SIGF
      Card2: SGL SW ST LC TENSION RTYPE AVGOPT
      Card3: LCUNLD REF STOL

    One container for both because the LAW88 target and the whole curve/
    unloading wiring are shared; ``family`` carries the discriminator (the same
    pattern MatPlasTAB.family uses for MAT_024/081/082/105).
    """
    mid: int
    title: str
    family: str                  # "181" | "183"
    rho: float
    k: float                     # KM (181) / K (183) → LAW88 K
    mu: float = 0.0              # damping coefficient — a /PROP field, dropped
    g: float = 0.0               # frequency-independent damping shear modulus
    sigf: float = 0.0            # frequency-independent damping limit stress
    ref: float = 0.0
    prten: float = 0.0
    sgl: float = 0.0             # specimen gauge length  → curve abscissa /SGL
    sw: float = 0.0              # specimen width         → curve ordinate
    st: float = 0.0              # specimen thickness     →   /(SW*ST)
    lc_tbid: int = 0             # *DEFINE_CURVE or *DEFINE_TABLE of the loading
    tension: int = 0             # -1/0/+1 → LAW88 TENSION 1:1
    rtype: int = 0               # 0 true / 1 engineering strain rate
    avgopt: float = 0.0          # rate averaging — no /BEGIN 2022 LAW88 slot
    pr: float = 0.0              # → LAW88 NU verbatim (<=0 → the beta=|NU| rule)
    with_failure: bool = False   # the _WITH_FAILURE card 3 is present
    kfail: float = 0.0           # Feng-Hallquist damage — LAW88 2026 card only
    gama1: float = 0.0
    gama2: float = 0.0
    eh: float = 0.0
    lcunld: int = 0              # unloading curve → LAW88 FCT_ID_UN
    hu: float = 1.0              # hysteretic unloading factor → LAW88 HYS
    shape: float = 0.0           # → LAW88 SHAPE
    stol: float = 0.0
    visco: int = 0               # 1 = the Gi/BETAi branch is live (solids only)
    hisout: int = 0
    has_unload_card: bool = False
    log_log: bool = False        # the _LOG_LOG_INTERPOLATION spelling
    gi: List[float] = field(default_factory=list)      # → /VISC/PRONY G_i
    betai: List[float] = field(default_factory=list)   # → /VISC/PRONY Beta_i
    vflag: int = 0               # per-term formulation flag — no counterpart
    # writer-resolved LAW88 curve wiring (_resolve_mat_viscoelastic)
    fct_load: List[int] = field(default_factory=list)    # FCT_ID_LI, len = NL
    rates: List[float] = field(default_factory=list)     # EPSI_LI, len = NL
    fct_unload: int = 0                                  # FCT_ID_UN
    hys: float = 0.0                                     # HYS
    shape_out: float = 0.0                               # SHAPE


@dataclass
class MatSoftTissue:
    """*MAT_SOFT_TISSUE (091) / *MAT_SOFT_TISSUE_VISCO (092) → /MAT/LAW42.

    LS-DYNA cards (Vol II R17 p.2-669), FOUR always + two for _VISCO:
      Card1: MID RO C1 C2 C3 C4 C5 REF
      Card2: XK XLAM FANG XLAM0 FAILSF FAILSM FAILSHR
      Card3: AOPT AX AY AZ BX BY BZ
      Card4: LA1 LA2 LA3 MACF          (may be blank, but the card is there)
      Card5: S1..S6                    (_VISCO)
      Card6: T1..T6                    (_VISCO)

    Only the isotropic Mooney-Rivlin ground substance survives: Mu_1 = 2·C1,
    Mu_2 = -2·C2, alpha = ±2, Nu = 0.495. The transversely-isotropic collagen
    fibre term (C3/C4/C5, XLAM, XLAM0, FANG), the bulk modulus XK, all three
    FAILS* modes and the whole fibre orientation are DROPPED — loudly warned,
    unlike dyna2rad which converts silently.
    """
    mid: int
    title: str
    rho: float
    c1: float = 0.0              # → LAW42 Mu_1 = 2·C1 (alpha_1 = 2)
    c2: float = 0.0              # → LAW42 Mu_2 = -2·C2 (alpha_2 = -2)
    c3: float = 0.0              # collagen fibre term — DROPPED
    c4: float = 0.0
    c5: float = 0.0
    ref: float = 0.0
    xk: float = 0.0              # bulk modulus — DROPPED (LAW42 derives K from Nu)
    xlam: float = 0.0            # fibre straightening stretch — DROPPED
    fang: float = 0.0            # fibre angle about the c-axis — DROPPED
    xlam0: float = 0.0
    failsf: float = 0.0          # fibre / matrix / shear failure — all DROPPED
    failsm: float = 0.0
    failshr: float = 0.0
    aopt: float = 0.0            # fibre orientation — DROPPED entirely
    macf: float = 0.0
    visco: bool = False          # the _VISCO (MAT_092) spelling
    s: List[float] = field(default_factory=list)   # → LAW42 Gamma_arr (ratios)
    t: List[float] = field(default_factory=list)   # → LAW42 Tau_arr (TIMES)


@dataclass
class MatCohesiveMixedMode:
    """*MAT_COHESIVE_MIXED_MODE (138) → /MAT/LAW117.

    LS-DYNA cards (mat_138.cfg, R13.0):
      Card1: MID RO ROFLG INTFAIL EN ET GIC GIIC
      Card2: XMU T S UND UTD GAMMA

    Fields keep the LS-DYNA sign encodings raw; the emitter decodes them:
    XMU>0 = power law (Irupt=1, EXP_G), XMU<0 = Benzeggagh-Kenane (Irupt=2,
    EXP_BK=|XMU|); T/S<0 = |id| of a peak-traction-vs-element-size curve
    (→ Fct_TN/Fct_TT with TMAX=1.0); GIC/GIIC<0 = |id| of an
    energy-vs-element-size curve, which LAW117 cannot express (warned, zeroed).
    EN/ET are stiffness PER UNIT LENGTH on both sides — raw copy, no thickness
    rescale (LAW117 MAT_E_ELAS_N/S carry the same stress/length dimension).
    """
    mid: int
    title: str
    rho: float
    roflg: int = 0          # 0 = volume density → Imass=2; 1 = area → Imass=1
    intfail: float = 0.0    # IPs-to-fail; <0 Newton-Cotes, 0 = never delete
    en: float = 0.0         # → EN (stiffness / length)
    et: float = 0.0         # → ET (0 → starter defaults ET=EN)
    gic: float = 0.0        # → GIC (<0 = curve id, dropped with warning)
    giic: float = 0.0       # → GIIC
    xmu: float = 0.0        # sign = power-law / B-K switch
    t: float = 0.0          # peak traction (<0 = curve id → Fct_TN)
    s: float = 0.0          # peak shear traction (<0 = curve id → Fct_TT)
    und: float = 0.0        # ultimate normal displacement (T=0: TN = 2·GIC/UND)
    utd: float = 0.0        # ultimate shear displacement (S=0: TT = 2·GIIC/UTD)
    gamma: float = 0.0      # B-K gamma → GAMMA (0 → starter default 1.0)


@dataclass
class MatArupAdhesive:
    """*MAT_ARUP_ADHESIVE (169) → /MAT/LAW169 (ARUP_ADHESIVE, radioss2025).

    LS-DYNA cards (mat_169.cfg R11.1; card order 3,4,5,6 with card 5 BETWEEN
    the edge cards and the bond-thickness card):
      Card1: MID RO E PR TENMAX GCTEN SHRMAX GCSHR
      Card2: PWRT PWRS SHRP SHT_SL EDOT0 EDOT2 THKDIR EXTRA
      Card3 (EXTRA 1|3): TMAXE GCTE SMAXE GCSE PWRTE PWRSE
      Card4 (EXTRA 1|3): FACET FACCT FACES FACCS SOFTT SOFTS
      Card5 (EDOT2≠0):   SDFAC SGFAC SDEFAC SGEFAC
      Card6 (EXTRA 2|3): BTHK OUTFAIL FSIP FBR713 [ELF2NS]

    Radioss LAW169 implements card 1 plus PWRT/PWRS/SHRP/SHT_SL only; the rate
    scaling (EDOT0/EDOT2 + card 5), the edge data (cards 3/4), THKDIR and
    card 6 are all dropped by the emitter with warnings. Strengths/energies
    accept a NEGATIVE value = function id in LS-DYNA — LAW169 has no curve
    inputs, so those are warned and left at the 1e20 no-failure default.
    """
    mid: int
    title: str
    rho: float
    e: float = 0.0
    pr: float = 0.0
    tenmax: float = 0.0     # 0 → LAW169 default 1e20 (no tension failure)
    gcten: float = 0.0
    shrmax: float = 0.0
    gcshr: float = 0.0
    pwrt: float = 2.0       # float in LS-DYNA, INT in LAW169 (rounded, warned)
    pwrs: float = 2.0
    shrp: float = 0.0       # shear plateau ratio (<0 = curve id — dropped)
    sht_sl: float = 0.0     # slope of shear/tension interaction
    edot0: float = 0.0      # rate scaling — DROPPED
    edot2: float = 0.0      # ≠0 gates card 5 — DROPPED
    thkdir: float = 0.0     # thickness-direction flag — DROPPED
    extra: int = 0          # gates cards 3/4 (edge data) and 6 (BTHK...)
    bthk: float = 0.0       # bond thickness override (card 6) — DROPPED


@dataclass
class MatCohesiveMMEPR:
    """*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE (240) → /MAT/LAW116.

    Base cards (mat_240.cfg R11.1):
      Card1: MID RO ROFLG INTFAIL EMOD GMOD THICK INICRT
      Card2: G1C_0 G1C_INF EDOT_G1 T0 T1 EDOT_T FG1 LCG1C
      Card3: G2C_0 G2C_INF EDOT_G2 S0 S1 EDOT_S FG2 LCG2C
      Card 6 (optional, R16): RFILTF COMPY SMOLIM XMU — the manual's cards
      4/5 are the _3MODES mode-III cards, absent from the option-free
      spelling, so this card is parsed at position offset+3

    Only the option-free keyword converts (a _THERMAL/_3MODES/_FUNCTIONS
    variant turns these fields into curve ids / adds mode III, neither of
    which LAW116 can hold — the handler warn-skips those spellings and no
    entry lands here). EMOD/GMOD are TRUE moduli — LAW116 divides by Thick
    internally (UPARAM(1)=E/THICK), unlike LAW117's per-length EN/ET.
    Sign encodings stay raw for the emitter: G*C_0<0 activates rate-dependent
    toughness, T0<0 rate-dependent yield with T1's sign picking the
    quadratic/linear log form, FG1/FG2's sign picking the energy/displacement
    failure criterion.
    """
    mid: int
    title: str
    rho: float
    roflg: int = 0
    intfail: float = 1.0     # LS-DYNA default 1 (unlike MAT_138's 0)
    emod: float = 0.0        # true Young's modulus → E
    gmod: float = 0.0        # true shear modulus → G
    thick: float = 0.0       # 0 = LS-DYNA element thickness; LAW116 0→1·unit_L!
    inicrt: float = 0.0      # initiation criterion: 0 quad → Icrit 1, 1/2 max → 2
    g1c_0: float = 0.0
    g1c_inf: float = 0.0
    edot_g1: float = 0.0
    t0: float = 0.0
    t1: float = 0.0
    edot_t: float = 0.0
    fg1: float = 0.0
    lcg1c: int = 0           # GC-vs-thickness curve — DROPPED (warned)
    g2c_0: float = 0.0
    g2c_inf: float = 0.0
    edot_g2: float = 0.0
    s0: float = 0.0
    s1: float = 0.0
    edot_s: float = 0.0
    fg2: float = 0.0
    lcg2c: int = 0
    rfiltf: float = 0.0      # optional R16 card — all four DROPPED (warned)
    compy: float = 0.0
    smolim: float = 0.0
    xmu: float = 0.0


@dataclass
class MatToughenedAdhesive:
    """*MAT_TOUGHENED_ADHESIVE_POLYMER (252) → /MAT/LAW120 (TAPO).

    R16 cards (the local R7.1 cfg is outdated — it lacks SRFILT and IHIS):
      Card1: MID RO E PR FLG JCFL DOPT
      Card2: LCSS TAU0 Q B H C GAM0 GAMM
      Card3: A10 A20 A1H A2H A2S POW — SRFILT
      Card4: IHIS — D1 D2 D3 D4 D1C D2C

    LAW120 is the same TAPO model, so the copy is near-1:1 (D1→D1F, D2→D2F,
    D3→Dtrx, D4→Djc per dyna2rad CM:6806-6809). Flags translate 1:1 against
    the engine kernels (sigeps120_*.F): FLG 0→Iform 1 (Drucker-Prager cap) /
    2→Iform 2 (von Mises); JCFL 0→Itrx 2 (triaxiality factor in tension only)
    / 1→Itrx 1 (all T); DOPT 0→Idam 2 (damage plastic strain, "with turning
    point") / 1→Idam 1 (plastic arc length). SRFILT/IHIS have no LAW120 slot.
    """
    mid: int
    title: str
    rho: float
    e: float = 0.0
    pr: float = 0.0
    flg: int = 0
    jcfl: int = 0
    dopt: int = 0
    lcss: int = 0            # τ_Y vs plastic strain curve/table → Table_Id
    tau0: float = 0.0
    q: float = 0.0
    b: float = 0.0
    h: float = 0.0
    c: float = 0.0
    gam0: float = 0.0
    gamm: float = 0.0
    a10: float = 0.0
    a20: float = 0.0
    a1h: float = 0.0
    a2h: float = 0.0
    a2s: float = 0.0
    pow: float = 0.0
    srfilt: float = 0.0      # strain-rate EMA filter — DROPPED (warned)
    ihis: float = 0.0        # history-output selector — DROPPED (warned)
    d1: float = 0.0          # → D1F
    d2: float = 0.0          # → D2F
    d3: float = 0.0          # → Dtrx
    d4: float = 0.0          # → Djc
    d1c: float = 0.0
    d2c: float = 0.0


@dataclass
class FailDiemCriterion:
    """One DIEM criterion — the card-2 + card-3 pair of *MAT_ADD_DAMAGE_DIEM."""
    dityp: int = 0           # 0..4 → INITYPE 1..5 (same order)
    p1: int = 0              # initiation curve/table id → TAB_ID (mandatory)
    p2: float = 0.0          # → PARAM for DITYP 1/4; layer flag for 2/3 (dropped)
    p3: float = 0.0          # → PARAM for DITYP 2/3; shell shear flag for 1 (dropped)
    p4: float = 0.0          # transverse-shear flag → ISHEAR inverted (global!)
    p5: int = 0              # element-size regularization curve/table → TAB_EL
    detyp: int = 0           # 0 displacement → EVOTYPE 1; 1 energy → EVOTYPE 2
    dctyp: int = 0           # 0 max → COMPTYP 1; 1 multiplicative → 2; -1 none
    q1: float = 0.0          # DISP or ENER; <0 with DETYP 0 = table id (collapsed)
    q2: float = 0.0          # d3hsp logging flag — output-only, ignored
    q3: float = 0.0          # >0 with scalar Q1 → ALPHA + EVOSHAP 2
    q4: float = 0.0          # regularization curve on Q1 — DROPPED (warned)


@dataclass
class FailDiem:
    """*MAT_ADD_DAMAGE_DIEM → /FAIL/INIEVO (multi-criteria initiation +
    evolution; one /FAIL/INIEVO per keyword, bound by the trailing mat id).

    Card1: MID NDIEMC DINIT DEPS NUMFIP [VOLFRAC], then NDIEMC pairs of
    criterion cards (max 5). DINIT/DEPS/VOLFRAC have no INIEVO slot.
    NUMFIP maps to FAILIP (solid parts, IP count) and/or PTHICKFAIL (shell
    parts, through the same NUMFIP→Pthickfail rule /FAIL/GENE1 uses) — k2rad
    resolves solid/shell per the parts that actually reference the MID,
    instead of dyna2rad's whole-model element-count heuristic.
    """
    mid: int
    ndiemc: int = 0
    dinit: float = 0.0
    deps: float = 0.0
    numfip: float = 0.0
    volfrac: float = 0.0
    criteria: List[FailDiemCriterion] = field(default_factory=list)


@dataclass
class MatTabulatedJC:
    """*MAT_TABULATED_JOHNSON_COOK (224) → /MAT/LAW109 [+ /FAIL/TAB1].

    R16/R17 cards (Vol II R17 p.1591-1597; the shipped Keyword971_R7.1
    mat_224.cfg is STALE — no BFLG/ERODE/LCPS and card 3 typed as floats):
      Card1: MID RO E PR CP TR BETA NUMINT
      Card2: LCK1 LCKT LCF LCG LCH LCI BFLG
      Card3 (optional): FAILOPT NUMAVG NCYFAIL ERODE LCPS
    Negative encodings: E<0 → -E is a curve E(T); BETA<0 → -BETA is a curve /
    table / TABLE_3D(4D) of the Taylor-Quinney factor; NUMINT<0 → |NUMINT| is
    a PERCENT of failed IPs/layers (-200 = erosion off); a table whose first
    VALUE is negative carries natural-log strain rates.

    All routing (tables, failure model, warnings) is resolved by the writer
    prepass ``_resolve_mat_tabulated_jc`` into the ``tab_*``/``fail_*``
    fields below; the emitters only format cards.
    """
    mid: int
    title: str
    rho: float
    e: float = 0.0           # E<0: -E is an E(T) curve — sampled at TR (warned)
    pr: float = 0.0
    cp: float = 0.0          # specific heat per MASS on BOTH sides → C_p 1:1
    tr: float = 0.0          # → T_ref (0 keeps the starter default 293)
    beta: float = 1.0        # ≥0 scalar → ETA; <0: -BETA → TAB_ETA
    numint: float = 1.0
    lck1: int = 0
    lckt: int = 0
    lcf: int = 0
    lcg: int = 0
    lch: int = 0
    lci: int = 0
    bflg: int = 0            # R16+: β(shear/rate/size) reinterpretation — DROPPED
    failopt: int = 0         # F2 = eps_p/eps_f criterion — DROPPED (warned)
    numavg: int = 1
    ncyfail: int = 1
    erode: int = 0           # R16+: no-erosion stress handling — DROPPED
    lcps: int = 0            # R16+: post-processing principal-stress limit — DROPPED
    log_interpolation: bool = False   # _LOG_INTERPOLATION spelling → I_smooth=2
    # ── resolved by _resolve_mat_tabulated_jc ──────────────────────────────
    e_eff: float = 0.0       # scalar E actually emitted
    eta: float = 1.0         # scalar ETA actually emitted
    ismooth: int = 1         # LAW109 I_smooth (1 linear / 2 log)
    tab_h: int = 0           # tab_ID_h (flow stress, Ndim ≤ 2)
    tab_t: int = 0           # tab_ID_t (quasi-static yield vs T)
    yscale_h: float = 0.0    # Yscale_h; 0 = default 1.0 (3-D-split T-plane fix)
    tab_eta: int = 0         # TAB_ETA (Taylor-Quinney scale)
    emit_fail: bool = False  # a usable LCF exists → write /FAIL/TAB1
    fail_table1: int = 0     # TAB1 table1_ID (function or Auto/DefineTable id)
    fct_idel: int = 0        # TAB1 fct_IDel (element-size function, EI_ref=1)
    ifail_sh: int = 1
    ifail_so: int = 1
    pthickfail: float = 0.0


@dataclass
class MatJHCeramics:
    """*MAT_JOHNSON_HOLMQUIST_CERAMICS (110, JH-2) → /MAT/LAW79 (JOHN_HOLM).

    Cards (Vol II R16 p.2-761; mat_110.cfg:170-182), 8 x 10 chars:
      Card1: MID RO G A B C M N
      Card2: EPS0 T SFMAX HEL PHEL BETA
      Card3: D1 D2 K1 K2 K3 FS

    **Nothing is normalized on conversion.** A/B/C/M/N/SFMAX are dimensionless
    in BOTH codes; HEL, PHEL and T are copied as PHYSICAL stresses. The Radioss
    starter re-derives the JH-2 normalizers itself with the identical
    definitions LS-DYNA uses — ``sigma_HEL = 1.5*(HEL-PHEL)`` and
    ``T* = T/PHEL`` (hm_read_mat79.F:211-213), ``P* = P/PHEL`` and
    ``sigma* = sigma_VM/sigma_HEL`` (sigeps79.F:153,190). Pre-dividing T by
    PHEL, or passing sigma_HEL in a stress slot, would double-apply the
    normalization. K1/K2/K3 are LAW79's OWN polynomial EOS
    (P = K1*mu + K2*mu^2 + K3*mu^3, sigeps79.F:143-147) — no /EOS is emitted.

    The ONE field that is not a straight copy is PHEL — a blank/0 PHEL is a
    documented LS-DYNA derivation request, not a defective card (see
    ``phel_eff``). All guards, the EPS0 substitution and every warning are
    resolved by the writer prepass ``_resolve_mat_impact``; the emitter only
    formats cards.
    """
    mid: int
    title: str
    rho: float
    g: float = 0.0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    m: float = 0.0           # FRACTURED pressure exponent (card1 field 7)
    n: float = 0.0           # INTACT pressure exponent (card1 field 8)
    eps0: float = 0.0        # EPS0/EPSI reference strain rate, 1/time
    t: float = 0.0           # max tensile hydrostatic pressure, PHYSICAL
    sfmax: float = 0.0       # max normalized fractured strength (0 → INFINITY)
    hel: float = 0.0
    phel: float = 0.0
    beta: float = 0.0        # bulking fraction, must be in [0, 1]
    d1: float = 0.0
    d2: float = 0.0
    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    fs: float = 0.0          # failure flag — NOT expressible at /BEGIN 2022
    # ── resolved by _resolve_mat_impact ───────────────────────────────────
    eps0_eff: float = 0.0    # EPS0 actually emitted (a deck-time-unit
                             # quasi-static rate substituted for the ERROR-910
                             # case C != 0 with EPS0 <= 0)
    phel_eff: float = 0.0    # PHEL actually emitted. A blank/0 PHEL is a
                             # documented LS-DYNA input mode ("calculated
                             # automatically by LS-DYNA if p_hel is zero on
                             # input", Vol II R16 p.2-764) that Radioss does
                             # NOT implement, so the converter reproduces the
                             # mu_hel iteration and emits the derived value.


@dataclass
class MatJHConcrete:
    """*MAT_JOHNSON_HOLMQUIST_CONCRETE (111, JHC) → /MAT/LAW126.

    Cards (Vol II R16 p.2-765; mat_111.cfg), 8 x 10 chars:
      Card1: MID RO G A B C N FC     <- note field 7 is N and field 8 is FC,
                                        NOT the M,N pair of *MAT_110
      Card2: T EPS0 EFMIN SFMAX PC UC PL UL
      Card3: D1 D2 K1 K2 K3 FS

    **Nothing is normalized on conversion.** A/B/N/SFMAX/EFMIN/D1/D2 and the
    volumetric strains UC/UL are dimensionless; FC, T, PC, PL, K1..K3 and G are
    stresses. The engine forms ``P* = P/FC``, ``sigma* = sigma_VM/FC`` and
    ``T* = T/FC`` itself (sigeps126.F90:264,305,338) and multiplies the yield
    back up by FC at :383 — so T must NOT be pre-divided by FC.

    All guards (the unguarded ``k0 = PC/UC`` and ``h = (PL-PC)/UL`` divisions),
    the EPS0 substitution and the FS → IDEL/EPS_MAX mapping are resolved by the
    writer prepass ``_resolve_mat_impact``; the emitter only formats cards.
    """
    mid: int
    title: str
    rho: float
    g: float = 0.0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    n: float = 0.0
    fc: float = 0.0          # quasi-static uniaxial compressive strength
    t: float = 0.0           # max tensile hydrostatic pressure, PHYSICAL
    eps0: float = 0.0
    efmin: float = 0.0       # damage-strain floor (0 → starter 1e-20)
    sfmax: float = 0.0       # 0 → starter INFINITY
    pc: float = 0.0          # crushing pressure
    uc: float = 0.0          # crushing volumetric strain → MUC
    pl: float = 0.0          # locking pressure
    ul: float = 0.0          # locking volumetric strain → MUL
    d1: float = 0.0
    d2: float = 0.0
    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    fs: float = 0.0
    # ── resolved by _resolve_mat_impact ───────────────────────────────────
    eps0_eff: float = 0.0
    idel: int = 1            # FS<0 → 3, FS=0 → 1, FS>0 → 2
    eps_max: float = 0.0     # = FS (copied verbatim, d2r CM:5654)


@dataclass
class MatElasticFluid:
    """*MAT_ELASTIC with the _FLUID option (001) → /MAT/LAW6 (HYD_VISC) +
    /EOS/POLYNOMIAL of the same id.

    Cards (Vol II R16 p.2-145..2-148; mat_001.cfg:191-201):
      Card1: MID RO E PR DA DB K      <- K is card-1 field 7, NOT a second card
      Card2: VC CP                    <- FLUID option only

    Manual Remark 5: under the FLUID option **K must be defined, E and PR are
    ignored, and the shear modulus is set to zero**. /MAT/LAW6 has no shear
    slot at all (the deviatoric response comes only from the viscosity), so
    G = 0 is structural rather than a conversion loss. E and PR survive here
    solely for the ``K == 0`` fallback ``B = E/(3(1-2*PR))``, which is the
    manual's own relation.

    Kept in its OWN container rather than as a flag on ``MatElastic`` so the
    plain *MAT_ELASTIC path — its /MAT/ELAST emitter, its ``_target_mat_law``
    LAW1 entry and therefore its place on the starter's solid-/XREF law
    whitelist — is byte-for-byte untouched by this family.

    ``bulk``/``nu_visc``/``pmin`` are resolved by ``_resolve_mat_impact``.
    """
    mid: int
    title: str
    rho: float
    e: float = 0.0           # ignored by LS-DYNA under FLUID; K==0 fallback only
    pr: float = 0.0          # idem
    da: float = 0.0          # beam-only axial damping — dropped
    db: float = 0.0          # beam-only bending damping — dropped
    k: float = 0.0           # bulk modulus → /EOS/POLYNOMIAL C1
    vc: float = 0.0          # DIMENSIONLESS tensor-viscosity coefficient
    cp: float = 0.0          # cavitation pressure, LS-DYNA default 1e20
    cp_given: bool = False   # card 2 present with a non-blank CP cell
    # ── resolved by _resolve_mat_impact ───────────────────────────────────
    bulk: float = 0.0        # /EOS/POLYNOMIAL C1
    nu_visc: float = 0.0     # /MAT/LAW6 Nu (kinematic viscosity, L^2/T)
    pmin: float = 0.0        # /MAT/LAW6 Pmin (0 → starter -INFINITY)


@dataclass
class FoamRefGeometry:
    """*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] → one /XREF per part whose nodes
    intersect the keyword's node table (dyna2rad ConvertInitialFoamReferenceGeometry;
    conversion is unconditional — the material REF flags are never consulted)."""
    ndtrrg: int = 0                        # _RAMP ramp steps → Nitrs (only if >0)
    nodes: Dict[int, Tuple[float, float, float]] = field(default_factory=dict)


@dataclass
class PressureLoad:
    """*LOAD_SEGMENT / *LOAD_SEGMENT_ID → /PLOAD.

    ``at`` is the arrival time (card 2 field 3, Manual Vol I R16 p.33-99). It has
    the same shift semantics as on *LOAD_SEGMENT_SET / *LOAD_SHELL — "the
    function value of the load curves will be evaluated at the offset time given
    by the difference of the solution time and AT" (Remark 3) — so it becomes a
    /SENSOR/TIME with ``Tdelay = at`` in the /PLOAD ``sens_ID`` slot. k2rad <=
    PR #116 never read the field at all: the pressure started at t = 0 with no
    diagnostic, while the identical AT on the _SET sibling was warned about.
    """
    lcid: int
    sf: float
    nodes: List[int]
    at: float = 0.0


@dataclass
class SegmentSetPressureLoad:
    """*LOAD_SEGMENT_SET — a pressure/traction on every segment of a *SET_SEGMENT.

    ``ssid`` references a *SET_SEGMENT (``state.segment_sets``); the segments are
    resolved at write time so the set may be defined anywhere in the deck. Each
    segment becomes one /PLOAD entry with function ``lcid`` scaled by ``sf``.

    ``at`` is the arrival time. /PLOAD has no Tstart column, so it becomes a
    /SENSOR/TIME with ``Tdelay = at`` in the ``sens_ID`` slot — the same
    mechanism, and the same shift semantics, as ShellPressureLoad.at. k2rad
    <= PR #116 dropped it with a warning.
    """
    ssid: int
    lcid: int
    sf: float
    at: float = 0.0


@dataclass
class SegmentSet:
    """*SET_SEGMENT — a set of 3- or 4-node surface segments.

    Each entry in ``segments`` is the corner-node list of one segment
    (``[n1, n2, n3, n4]``; a 3-node segment drops n4). Segment orientation
    (node order) fixes the outward normal, which a blast / pressure load uses
    as its application side. Maps to an OpenRadioss /SURF/SEG.
    """
    sid: int
    title: str
    segments: List[List[int]] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# *AIRBAG_* → /MONVOL (monitored volumes)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GasSpecies:
    """One gas species of a MULTI-GAS airbag (``*AIRBAG_HYBRID`` card 5.1,
    ``*AIRBAG_PARTICLE`` card 13) → one ``/MAT/GAS/MOLE`` + one
    ``/PROP/INJECT1`` row.

    **The heat-capacity coefficients are MOLAR on both sides, so the copy is
    1:1.** LS-DYNA states A/B/C as "Coefficient of MOLAR heat capacity of
    inflator gas at constant pressure, (e.g., Joules/mole/K, /K^2, /K^3)"
    (Vol I R17 p.3-50) and ``/MAT/GAS/MOLE`` is the variant whose reader
    DIVIDES them by MW — ``hm_read_matgas.F:295-302``::

        IF (IMOLE == 1) THEN
          CPA = CPA / MW * FAC
          CPB = CPB / MW * FAC
          CPC = CPC / MW * FAC

    so what the card carries is a molar Cp and what the solver stores is the
    mass-specific one. Cross-checked against the hard-coded PREDEF gases, which
    take the same ``IMOLE=1`` path with SI molar numbers (``:158-166``: N2 has
    ``MW = 0.02801`` kg/mol and ``CPA = 26.0920000`` J/(mol K), i.e.
    Cp/M = 931 J/(kg K), correct for nitrogen).

    That is why this batch emits ``/MAT/GAS/MOLE`` and NOT the
    ``/MAT/GAS/MASS`` batch 1 uses for ``*AIRBAG_SIMPLE_AIRBAG_MODEL``: there
    the card-4a A and B are molar but the target slot is mass-specific, so
    ``Cpa = A/MW`` is the converter's own division. Here the SOLVER does it,
    and dividing again would be a second division by MW.

    **The units still have to be the deck's.** ``MW`` must be in
    deck-mass/mole and ``Cp*`` in deck-energy/(mole K); no rescaling is applied
    on either side. MEASURED (card-format probe ``mole_0000.rad``, an Mg/mm/s
    deck): ``MW=2.896e-05`` with ``Cpa=26789.065`` reproduces
    ``/MAT/GAS/PREDEF AIR`` exactly, while the naive SI pair ``0.02896`` /
    ``26.789065`` is accepted silently and is wrong by 1e6.
    """
    #: molecular weight — LS-DYNA ``MW`` (HYBRID) / ``XMi`` (PARTICLE)
    mw: float = 0.0
    #: MOLAR Cp polynomial, ``Cp = a + b*T + c*T^2`` — A/B/C or Ai/Bi/Ci
    hc_a: float = 0.0
    hc_b: float = 0.0
    hc_c: float = 0.0
    #: HYBRID ``INITM`` — the initial mass FRACTION of this species in the bag
    #: at t=0 ("The sum of INITM of all gas components should be 1.0",
    #: Vol I R17 p.3-50). NOT an absolute mass.
    initm: float = 0.0
    #: HYBRID ``FMASS`` — fraction of additional aspirated mass. No Radioss
    #: counterpart; carried so the drop can be reported by value.
    fmass: float = 0.0
    #: inflator mass-FLOW-RATE curve — ``LCIDM`` / ``LCMi``
    lcid_m: int = 0
    #: inflator gas-temperature curve — ``LCIDT`` / ``LCTi``
    lcid_t: int = 0
    #: PARTICLE ``INFGi`` — the inflator this species belongs to
    infg: int = 0
    #: 1-based index on the LS-DYNA card, for warnings
    index: int = 0
    # ── resolved by writer/monvol.py ────────────────────────────────────
    mat_id: int = 0          # the /MAT/GAS/MOLE id
    fun_m: int = 0           # the /PROP/INJECT1 fun_ID_M
    fun_t: int = 0           # the /PROP/INJECT1 fun_ID_T
    injected: bool = False   # True → this species gets an injector row


@dataclass
class AirbagVent:
    """One VENT HOLE of a ``/MONVOL``.

    The four-card vent block is the one sub-block whose layout is pinned as
    IDENTICAL across the three monitored volumes this converter writes it on —
    ``radioss140/PROP/venthole1.cfg:17`` names itself *"SUBOBJECT of AIRBAG1,
    COMMU1 AND FVMBAG1"* — which is why every leak path in batch 2 is stated
    as a vent hole and ``Nporsurf`` stays 0. See ``_resolve_hybrid_vents`` for
    the fabric-porosity case that decision covers.

    ``surf_id == 0`` is the whole-bag mode: ``Avent`` is then an ABSOLUTE AREA
    and ``Bvent`` is forced to 0 by the reader. With a NAMED surface ``Avent``
    is a SCALE FACTOR on that surface's current area — the same column, two
    meanings, selected by whether a surface is named. ``hm_read_monvol_type9.F``
    (and its type-7/11 twins): *"if ``surf_IDv==0`` then ``Bvent→0`` and
    ``Avent`` is an absolute area (``Avent 0→1.0``)"*.

    The ``/TH`` per-hole channels ``AOUT1..HOUT10`` are addressed by the
    POSITIONAL slot of the hole, not by ``surf_IDv``, so this list's order is
    the order the T01 columns come back in.
    """
    title: str = "VENT"
    #: the named vent /SURF id, 0 = whole-bag
    surf_id: int = 0
    quad_eids: List[int] = field(default_factory=list)
    tri_eids: List[int] = field(default_factory=list)
    #: 1 isenthalpic, 2 Chemkin, 3 Graefe, 4 in-flow. Always 1: every LS-DYNA
    #: leak path this converter reads is the Wang-Nefske isentropic orifice,
    #: whose Radioss equivalent is Iform 1.
    iform: int = 1
    avent: float = 0.0
    fct_t: int = 0           # area scale vs TIME
    fct_p: int = 0           # area scale vs GAUGE pressure (P - Pext)
    tstart: float = 0.0
    dpdef: float = 0.0


@dataclass
class AirbagInteraction:
    """``*AIRBAG_INTERACTION`` — gas exchange BETWEEN two bags.

    Not an :class:`Airbag`: it owns no surface, no gas and no ``/MONVOL`` id of
    its own. It is a RELATION that promotes both of its partners from
    ``/MONVOL/AIRBAG1`` to ``/MONVOL/COMMU1`` and writes one row into each
    partner's ``Nbag`` block — the only Radioss card that expresses inter-bag
    flow at all.

    ``AREA < 0`` → ``|AREA|`` is a curve of orifice area vs ABSOLUTE pressure.
    ``SF < 0`` → ``|SF|`` is a curve of vent coefficient vs relative time.
    ``PID < 0`` → contact blockage of the orifice is considered.
    ``LCID`` → mass flow vs pressure difference; when set, LS-DYNA ignores
    AREA/SF/PID entirely.
    ``IFLOW`` < 0 one-way AB1→AB2, 0 two-way, > 0 one-way AB2→AB1.
    """
    ab1: int = 0
    ab2: int = 0
    area: float = 0.0
    sf: float = 0.0
    pid: int = 0
    lcid: int = 0
    iflow: int = 0
    excp: int = 0
    keyword: str = ""
    title: str = ""


@dataclass
class Airbag:
    """One ``*AIRBAG_<MODEL>`` card → one ``/MONVOL/<type>``.

    ONE dataclass for all five batch-1 models rather than five: every model
    shares the whole of card 1 (SID/SIDTYP/RBID/VSCA/PSCA/VINI/MWD/SPSF) and
    the surface machinery built on it, and the per-model card-3/4 fields are
    disjoint, so a union keeps the surface contract in one place. Batch 2 adds
    ``HYBRID`` and ``PARTICLE`` to the same union for the same reason — both
    carry that identical card 1 and the identical RBID walk above it, and their
    multi-gas / multi-vent data goes into LISTS (``species``, ``vents``,
    ``poros``) rather than into more scalar slots. ``model``
    names which of the seven was read and therefore which fields are live:

      ``SIMPLE_PRESSURE_VOLUME``  → /MONVOL/PRES   (cn, beta, lcid, lciddr)
      ``SIMPLE_AIRBAG_MODEL``     → /MONVOL/AIRBAG1 + /MAT/GAS + /PROP/INJECT1
                                    (cv, cp, t, lcid, mu, area, pe, ro,
                                     lou, t_ext, hc_a, hc_b, mw, gasc)
      ``ADIABATIC_GAS_MODEL``     → /MONVOL/GAS    (psf, lcid, gamma, p0, pe, ro)
      ``LOAD_CURVE``              → /MONVOL/PRES   (stime, lcid, …)
      ``LINEAR_FLUID``            → /MONVOL/LFLUID (bulk, ro, lcint, lcoutt,
                                     lcoutp, lcfit, lcbulk, lcid, p_limit,
                                     p_limlc, nonull)
      ``HYBRID``                  → /MONVOL/AIRBAG1 with N_gases > 1, or
                                    /MONVOL/COMMU1 when an *AIRBAG_INTERACTION
                                    joins it to another bag (atmost, atmosp,
                                    hconv, c23/a23/cp23/ap23 + their curves,
                                    opt, pvent, species, jet_*)
      ``PARTICLE``                → /MONVOL/FVMBAG2 (sd1, sd2, unit, tatm,
                                    patm, tsw, iair, pair/tair/xmair/aair/
                                    bair/cair, species, orifices, vent_rows)

    **SIDTYP is inverted relative to intuition**: ``0`` = *SET_SEGMENT,
    non-zero = *SET_PART (Vol I R16 p.3-4, "EQ.0: segment / NE.0: part set ID").

    **The scaling contract** (Vol I p.3-4, verbatim): ``V_cvolume = (VSCA ×
    V_femodel) − VINI`` and ``P_femodel = PSCA × P_cvolume``. So VSCA/PSCA are
    a UNIT BRIDGE and VINI is subtracted AFTER the volume scale — it is the
    Radioss ``Vinc`` (incompressible volume), not an "initial fill".
    """
    airbag_id: int
    model: str
    title: str = ""
    keyword: str = ""
    # ── card 1, shared by every model ────────────────────────────────────
    sid: int = 0
    sidtyp: int = 0
    rbid: int = 0
    vsca: float = 1.0
    psca: float = 1.0
    vini: float = 0.0
    mwd: float = 0.0
    spsf: float = 0.0
    # ── SIMPLE_PRESSURE_VOLUME ───────────────────────────────────────────
    cn: float = 0.0
    beta: float = 0.0
    lciddr: int = 0
    # ── SIMPLE_AIRBAG_MODEL ──────────────────────────────────────────────
    cv: float = 0.0
    cp: float = 0.0
    t: float = 0.0           # temperature of the INJECTED gas
    mu: float = 0.0          # vent shape factor (< 0 → |mu| is a curve id)
    area: float = 0.0        # vent exit area  (< 0 → |area| is a curve id)
    pe: float = 0.0          # ambient pressure
    ro: float = 0.0          # ambient density
    lou: int = 0             # mass-flow-out vs gauge-pressure curve
    t_ext: float = 0.0       # ambient temperature (card 4a, CV == 0 only)
    hc_a: float = 0.0        # molar heat-capacity coefficient A (card 4a)
    hc_b: float = 0.0        # molar heat-capacity coefficient B (card 4a)
    mw: float = 0.0          # molecular weight  (card 4a)
    gasc: float = 0.0        # universal gas constant (card 4a)
    # ── ADIABATIC_GAS_MODEL ──────────────────────────────────────────────
    psf: float = 0.0
    gamma: float = 0.0
    p0: float = 0.0          # initial GAUGE pressure
    # ── LOAD_CURVE ───────────────────────────────────────────────────────
    stime: float = 0.0
    t0: float = 0.0
    # ── LINEAR_FLUID ─────────────────────────────────────────────────────
    bulk: float = 0.0
    lcint: int = 0
    lcoutt: int = 0
    lcoutp: int = 0
    lcfit: int = 0
    lcbulk: int = 0
    p_limit: float = 0.0
    p_limlc: int = 0
    nonull: int = 0
    # ── HYBRID (batch 2) ─────────────────────────────────────────────────
    # card 3, the ambient state
    atmost: float = 0.0      # ambient temperature  -> T0
    atmosp: float = 0.0      # ambient pressure     -> Pext
    atmosd: float = 0.0      # ambient density      (dropped)
    gc: float = 0.0          # the deck's universal gas constant (dropped)
    cc: float = 0.0          # conversion constant  (dropped)
    hconv: float = 0.0       # convective heat-transfer coefficient -> Hconv
    # card 4, the vent / fabric-porosity orifices
    c23: float = 0.0         # vent orifice coefficient
    lcc23: int = 0           # > 0 vs TIME, < 0 vs relative pressure
    a23: float = 0.0         # vent area; < 0 -> |A23| is a PART or PART-SET id
    lca23: int = 0           # vent area vs ABSOLUTE pressure; -1 = A23 is a set
    cp23: float = 0.0        # fabric-porosity coefficient
    lcp23: int = 0           # porosity coefficient vs TIME
    ap23: float = 0.0        # fabric-porosity area
    lcap23: int = 0          # porosity area vs ABSOLUTE pressure
    # card 5
    opt: int = 0             # the venting FORMULA switch (1..8)
    pvent: float = 0.0       # gauge pressure at which venting begins
    ngas: int = 0
    lcefr: int = 0           # exit flow rate vs gauge pressure
    lcidm0: int = 0          # total inflator mass inflow -> /PROP/INJECT2
    vntopt: int = 0
    # _JETTING cards 6/7 and _CM card 8
    jetting: bool = False
    jet_ca: float = 0.0      # cone half-angle, RADIANS (< 0 -> |CA| is a curve)
    jet_beta: float = 0.0    # Bernoulli efficiency (< 0 -> curve)
    jet_psid: int = 0
    jet_n1: int = 0          # jet focal point node
    jet_n2: int = 0          # jet axis node
    jet_n3: int = 0          # secondary focal point (0 -> conical jet)
    jet_fp: tuple = (0.0, 0.0, 0.0)     # XJFP  YJFP  ZJFP
    jet_vh: tuple = (0.0, 0.0, 0.0)     # XJVH  YJVH  ZJVH
    jet_sfp: tuple = (0.0, 0.0, 0.0)    # XSJFP YSJFP ZSJFP
    jet_nreact: int = 0
    # ── PARTICLE (batch 2) ───────────────────────────────────────────────
    sd1: int = 0             # the bag part / part-set
    stype1: int = 0          # 0 PART, 1 PART SET
    sd2: int = 0             # the INTERNAL part / part-set
    stype2: int = 0
    block: int = 0
    npdata: int = 0
    fric: float = 0.0
    irpd: int = 0
    np: int = 0              # particle count (CPM-only)
    unit: int = 0            # 0 kg-mm-ms-K, 1 SI, 2 t-mm-s-K, 3 user
    visflg: int = 0
    tatm: float = 0.0
    patm: float = 0.0
    nvent: int = 0
    tend: float = 0.0
    tsw: float = 0.0         # -> Tswitch
    iair: int = 0
    norif: int = 0
    nid1: int = 0
    nid2: int = 0
    nid3: int = 0
    chm: int = 0
    cd_ext: float = 0.0
    pair: float = 0.0
    tair: float = 0.0
    xmair: float = 0.0
    aair: float = 0.0
    bair: float = 0.0
    cair: float = 0.0
    npair: int = 0
    nprlx: int = 0
    lcmass: int = 0          # _MOLEFRACTION: the total mass-flow curve
    segsid: int = 0          # _SEGMENT: the *SET_SEGMENT the volume is cut to
    jnode: int = 0           # _JET: the node the vent thrust reacts on
    #: raw ``(SID3, STYPE3, C23, LCTC23, LCPC23, ENH_V, PPOP)`` vent rows
    vent_rows: List[tuple] = field(default_factory=list)
    #: raw ``(NIDi, ANi, VDi, CAi, INFOi, IMOM, IANG, CHM_ID)`` orifice rows
    orifices: List[tuple] = field(default_factory=list)
    #: option flags that change the card walk or the physics
    mole_fraction: bool = False
    decomposition: bool = False
    inflation: bool = False
    # ── multi-gas / multi-vent, shared by HYBRID and PARTICLE ────────────
    species: List["GasSpecies"] = field(default_factory=list)
    # ── shared curve slot (SPV / SAM / AGM / LOAD_CURVE / LFLUID card 3) ─
    lcid: int = 0
    # ── resolved by writer/monvol.py::_resolve_airbags ───────────────────
    monvol_id: int = 0       # the emitted /MONVOL id
    surf_id: int = 0         # the emitted external /SURF id
    quad_eids: List[int] = field(default_factory=list)
    tri_eids: List[int] = field(default_factory=list)
    fct_id: int = 0          # PRES: the pressure function
    itypfun: int = 0         # PRES: 0 = f(V0/V), 1 = f(t), 2 = f(V/V0), 3 = t·V0/V
    fscale: float = 0.0      # PRES: 0 → starter default (1 × unit)
    gas_mat_id: int = 0      # AIRBAG1: the /MAT/GAS id
    gas_mat_kind: str = ""   # AIRBAG1: "CSTA" or "MASS"
    inject_prop_id: int = 0  # AIRBAG1: the /PROP/INJECT1 id
    inject_temp_fct: int = 0  # AIRBAG1: the constant-T /FUNCT
    avent: float = 0.0       # AIRBAG1: vent area (0 → no vent)
    vent_fct_p: int = 0      # AIRBAG1: porosity-vs-gauge-pressure /FUNCT
    pmax_fct: int = 0        # LFLUID: the flat P_LIMIT /FUNCT
    dropped: bool = False    # resolved to nothing — no /MONVOL is written
    # ── resolved, batch 2 ────────────────────────────────────────────────
    #: which /MONVOL card is written — "PRES" | "GAS" | "AIRBAG1" | "LFLUID"
    #: | "COMMU1" | "FVMBAG2". Set by the resolver, NOT by ``model``: a
    #: HYBRID bag is AIRBAG1 on its own and COMMU1 once an *AIRBAG_INTERACTION
    #: names it, and a PARTICLE bag falls back from FVMBAG2 to AIRBAG1 under
    #: ``--airbag-particle-uniform``.
    radioss_type: str = ""
    #: the ``Ittf`` column of /MONVOL/AIRBAG1, COMMU1 and FVMBAG2 — which
    #: sensor-relative shift the reader applies to the injector's own
    #: functions. Always ``ITTF_NO_SHIFT``; see ``writer/monvol.py``.
    ittf: int = 0
    vents: List["AirbagVent"] = field(default_factory=list)
    surf_in_id: int = 0      # FVMBAG2: the INTERNAL surface /SURF id
    surf_inj_id: int = 0     # FVMBAG2: the inflator-nozzle /SURF id
    in_quad_eids: List[int] = field(default_factory=list)
    in_tri_eids: List[int] = field(default_factory=list)
    inj_quad_eids: List[int] = field(default_factory=list)
    inj_tri_eids: List[int] = field(default_factory=list)
    #: FVMBAG2 numerics — see ``_FVMBAG2_*`` in writer/monvol.py
    cgmerg: float = 0.0
    dtsca: float = 0.0
    dtmin: float = 0.0
    tswitch: float = 0.0
    #: ``(partner /MONVOL id, surf_IDc, Acom, fct_IDCt, fct_IDCP)`` rows of the
    #: COMMU1 ``Nbag`` block, one per *AIRBAG_INTERACTION.
    commu_rows: List[tuple] = field(default_factory=list)
    #: The partition surfaces those rows name. Kept OUT of ``vents``: a
    #: communicating surface is not a vent hole — it moves gas to the partner
    #: volume, not to the outside — and putting it in the vent list would add a
    #: leak-path block to the card as well as the Nbag row.
    commu_surfs: List["AirbagVent"] = field(default_factory=list)


@dataclass
class AirbagRefGeometry:
    """``*AIRBAG_REFERENCE_GEOMETRY[_ID][_BIRTH][_RDT]`` → one ``/XREF`` per
    part whose element nodes the table names.

    Structurally the airbag twin of :class:`FoamRefGeometry` and it feeds the
    SAME writer prepass (``inistate._resolve_xref_parts``) and emitter
    (``inistate._make_xref``) — a shell part carrying it needs no law check at
    all (the starter's law whitelist in ``hm_read_xref.F:222-226`` is gated on
    ``ITYP == 2``, i.e. SOLID parts only), and ``cepsini.F``'s ``CMLAWI``
    dispatch covers ILAW 1, 19 and 58, so both fabric laws honour it.

    ``sx``/``sy``/``sz`` and ``nid0`` come from the ``_ID`` card and are applied
    AT CONVERSION TIME (Radioss ``/XREF`` has no scale or origin field): each
    listed coordinate is scaled about NID0's own reference position. ``birth``
    (the ``_BIRTH`` card) becomes a ``/SENSOR/TIME`` on the fabric material's
    ``SENS_ID``; ``_RDT`` has no Radioss counterpart at all and is warn-dropped.
    """
    nodes: Dict[int, Tuple[float, float, float]] = field(default_factory=dict)
    sx: float = 1.0
    sy: float = 1.0
    sz: float = 1.0
    nid0: int = 0
    birth: float = 0.0
    has_id: bool = False
    has_rdt: bool = False
    keyword: str = ""


@dataclass
class AirbagShellRefGeometry:
    """``*AIRBAG_SHELL_REFERENCE_GEOMETRY[_ID][_RDT]`` → ``/EREF/SHELL`` and/or
    ``/EREF/SH3N``, one per owning part.

    Each entry of ``elems`` is ``(EID, [N1, N2, N3, N4])`` — the LS-DYNA PID
    column is read but NOT used ("the part ID is not used in this section",
    Vol I R16), because Radioss takes the part from the ``/EREF`` header.

    The referenced node ids are GHOST nodes whose CURRENT ``/NODE`` coordinates
    become the reference geometry (``hm_read_eref.F``: ``XREFC(IN,1,IE) =
    X(1,NN)``), so they only carry a reference state when they are distinct
    from the element's structural nodes.
    """
    elems: List[Tuple[int, List[int]]] = field(default_factory=list)
    sx: float = 1.0
    sy: float = 1.0
    sz: float = 1.0
    nid0: int = 0
    has_id: bool = False
    has_rdt: bool = False
    keyword: str = ""


@dataclass
class LoadBlastEnhanced:
    """*LOAD_BLAST_ENHANCED — a ConWep / TM5-1300 empirical air-blast source.

    Card 1:  bid m xbo ybo zbo tbo unit blast
    Card 2:  cfm cfl cft cfp nidbo death negphs
      m          = equivalent TNT charge mass (in the UNIT system's mass unit)
      xbo/ybo/zbo= detonation-point coordinates
      tbo        = detonation time
      unit       = unit-system flag (2 = kg,m,s,Pa; see handlers._blast_unit_system)
      blast      = 1 hemispherical surface burst, 2 spherical free-air burst,
                   3 air burst with ground reflection (Mach stem)
      death      = load-removal time
      negphs     = 0 include the negative (suction) phase, 1 ignore it

    Maps to OpenRadioss /LOAD/PBLAST: Exp_data from ``blast``, WTNT from ``m``,
    Xdet/Ydet/Zdet from the origin, Tdet from ``tbo``, Tstop from ``death``.
    """
    bid: int
    m: float
    xbo: float
    ybo: float
    zbo: float
    tbo: float
    unit: int
    blast: int
    death: float = 1e20
    negphs: int = 0


@dataclass
class LoadBlastSegmentSet:
    """*LOAD_BLAST_SEGMENT_SET — applies a *LOAD_BLAST_ENHANCED source (``bid``)
    to a *SET_SEGMENT (``ssid``); ``scalep`` scales the resulting pressure."""
    bid: int
    ssid: int
    alepid: int = 0
    sfnrb: float = 0.0
    scalep: float = 1.0


@dataclass
class LoadBody:
    """*LOAD_BODY_{X,Y,Z} — a whole-model base-acceleration (body) load.

    Card: lcid sf lciddr xc yc zc cid
      dir  = axis letter from the keyword suffix ("X" | "Y" | "Z")
      lcid = acceleration-vs-time curve (magnitude)
      sf   = scale factor
      cid  = local system the acceleration is given in (0 = global)
    The applied acceleration field is ``sf × lcid(t)`` along the NEGATIVE
    ``dir`` axis — a base acceleration accelerates the coordinate system, so the
    inertial load on the model has the opposite sign (Manual Vol I R16
    p.33-27/33-28, "Note: Positive body load acts in the negative direction").
    Maps to an OpenRadioss /GRAV with ``Fscale_Y = -sf`` and ``skew_ID = cid``,
    over every part unless a *LOAD_BODY_PARTS card scopes it to a part set.
    """
    dir: str            # "X" | "Y" | "Z"
    lcid: int
    sf: float
    cid: int = 0        # *DEFINE_COORDINATE_* id → /GRAV skew_ID (0 = global)


@dataclass
class LoadBodyVector:
    """*LOAD_BODY_VECTOR — a base-acceleration body load along a free vector.

    Card 1a.1: lcid sf lciddr xc yc zc cid;  Card 1a.2: v1 v2 v3.
    ``(v1,v2,v3)`` is a DIRECTION only — its magnitude is irrelevant (both
    LS-DYNA and the Radioss dyna-reader use it unnormalised and let the frame
    construction normalise it). When ``cid`` is set the components are given in
    that system's basis and must be mapped to global first.

    The body force acts along **-V** (Manual Vol I R16 p.33-29: the manual's own
    validation example writes ``V = (-1,-1,-1)`` to obtain gravity along
    +(1,1,1)), which is the same opposite-sign rule the ``_X/_Y/_Z`` forms
    follow. Maps to ONE /GRAV with ``DIR = "X"``, ``Fscale_Y = -sf`` and a
    companion /SKEW/FIX whose local X' is +V_global — exactly what dyna2rad
    emits (``convertloads.cxx:550`` ``Fscale_Y = -lsdSF``, ``:595-606`` the
    X' = +V skew). Both halves must be reproduced together: either one alone
    flips the load.
    """
    lcid: int
    sf: float
    v: Tuple[float, float, float]
    cid: int = 0        # basis the components are given in (0 = global)
    xc: float = 0.0     # skew origin; inert for a uniform acceleration field
    yc: float = 0.0
    zc: float = 0.0


@dataclass
class LoadBodyRot:
    """*LOAD_BODY_RX/_RY/_RZ — an angular-velocity body load → /LOAD/CENTRI.

    Card: lcid sf lciddr xc yc zc cid.  ``lcid`` carries the ANGULAR VELOCITY
    omega(t), not omega^2 and not an acceleration: LS-DYNA forms
    ``b = rho*[omega x (omega x r)]`` internally (Manual Vol I R16 p.33-20
    Remark 3) and the OpenRadioss engine squares the curve for itself
    (``cfield.F:121,128``: ``VROT = FAC(1,NL)*FINTER(...)`` then
    ``VROT2 = VROT*VROT``). The mapping is therefore 1:1 and LINEAR in omega —
    squaring or square-rooting it here would be catastrophic.

    Both sides apply the acceleration radially OUTWARD from the axis
    (LS-DYNA Remark 2; ``cfield.F:232-237`` ``AREL = DIST*VROT2`` with ``DIST``
    the axis-perpendicular radius), so there is NO sign flip, unlike the
    translational forms.

    ``dir`` is the axis letter from the keyword suffix. The /LOAD/CENTRI ``Dir``
    field must be spelled **XX/YY/ZZ**: the starter maps X/Y/Z to IDIR 1/2/3
    (``hm_read_load_centri.F:206-211``) but the engine only branches on 4/5/6,
    so IDIR 1/2/3 all fall into the ``ELSE`` and rotate about the frame's Z
    axis instead (``cfield.F:132-144``) — silently, with no error. dyna2rad
    writes X/Y/Z (``convertloads.cxx:271-288``) and is wrong for RX and RY.

    The rotation axis passes through ``(xc,yc,zc)``, or through the ``cid``
    system's origin when ``cid`` is set (``cid`` supersedes the centre fields);
    that becomes a companion /FRAME/FIX.
    """
    dir: str            # "X" | "Y" | "Z" → /LOAD/CENTRI Dir "XX"/"YY"/"ZZ"
    lcid: int           # omega(t) curve
    sf: float           # scales omega (NOT omega^2)
    cid: int = 0        # *DEFINE_COORDINATE_* id; supersedes xc/yc/zc
    xc: float = 0.0     # centre of rotation (cid = 0)
    yc: float = 0.0
    zc: float = 0.0


@dataclass
class ShellPressureLoad:
    """*LOAD_SHELL_ELEMENT / *LOAD_SHELL_SET → /PLOAD on the shells' faces.

    Card: eid|esid lcid sf at.  ``eids`` holds the shell element ids the row
    applies to (one for _ELEMENT, the expanded *SET_SHELL for _SET).

    Sign: LS-DYNA's positive pressure acts along the shell's NEGATIVE normal
    (Manual Vol I R16 p.3421: connectivity follows the right-hand rule, with
    "positive pressure acting in the negative t-direction"), while a Radioss
    /PLOAD with a positive ``Fscale_y`` pushes the surface along its POSITIVE
    segment normal (``force.F90:451-465``: ``fx = Fscale_y*f(t)*nx/8`` summed
    over the four nodes gives ``+P*A*n_hat``). k2rad builds the /SURF/SEG by
    pasting the shell connectivity, so ``n_hat = t_hat`` and exactly ONE flip
    is needed: ``Fscale_y = -sf``.

    ``at`` is the arrival time. /PLOAD has no Tstart column, so it becomes a
    /SENSOR/TIME with ``Tdelay = at`` in the ``sens_ID`` slot: the load is zero
    for t < at and the curve is then evaluated at ``t - at``
    (``sensor_time.F:66-68`` sets ``TSTART = TDELAY``; ``force.F90:216-218``
    evaluates at ``ts = tt - TSTART``) — a shift, which is how LS-DYNA's
    arrival time reads.
    """
    eids: List[int]
    lcid: int
    sf: float
    at: float = 0.0
    ssid: int = 0       # _SET form: *SET_SHELL id, resolved at write time
    source: str = "*LOAD_SHELL_ELEMENT"


@dataclass
class GravityLoadPart:
    """*LOAD_GRAVITY_PART — gravity body load on one part → /GRAV.

    LS-DYNA card: pid dof lc accel lcdr stga stgr.  DOF 1/2/3 loads the part
    along X/Y/Z.  The load is ACCEL × factor(t): LC "defines factor as a
    function of time", ACCEL "will be multiplied by factor from curve", and
    "a constant factor of 1.0 is assumed if LC is not specified" (Manual Vol I
    R16 p.33-57 + Remark 1a).  The R16/R17 manual fixes NO sign for ACCEL, so
    the direction convention is taken from the Radioss dyna-reader, which
    negates it exactly like *LOAD_BODY (``convertloads.cxx:859``; that file is
    not part of this repo) — the writer emits Fscaley = -accel with fct_IDT =
    LC.  Gravity is irrelevant to a non-prestressed eigenproblem, so modal
    decks only get an informational note.
    """
    pid: int
    dof: int            # 1/2/3 = load along -X/-Y/-Z
    lc: int             # accel-vs-time curve (0 = constant ACCEL)
    accel: float        # constant gravity acceleration magnitude (lc = 0)
    lcdr: int = 0       # dynamic-relaxation curve (not converted)
    stga: int = 0       # staged-construction activation stage (not converted)
    stgr: int = 0       # staged-construction removal stage (not converted)


@dataclass
class MatAddFatigue:
    """*MAT_ADD_FATIGUE — S-N fatigue data for a material.

    No OpenRadioss equivalent exists; the data feeds the OFFLINE random-vibration
    post-processor (tools/modal_random_response.py), which computes Dirlik
    fatigue damage from the modal PSD response.  S-N definition: either a curve
    (lcid > 0: abscissa N, ordinate S) or the power law  N·S^b = a  (lcid = 0).
    """
    mid: int
    lcid: int           # S-N *DEFINE_CURVE (0 = use a/b power law)
    ltype: int          # curve interpolation: 0 = semi-log, 1 = log-log
    a: float            # N·S^b = a  power-law coefficient (lcid = 0)
    b: float            # power-law exponent
    sthres: float       # fatigue/endurance threshold stress (0 = none)
    snlimt: int         # behaviour below the last curve point
    sntype: int         # S meaning: 0 = stress RANGE (default), 1 = amplitude


@dataclass
class DbFreqBinary:
    """*DATABASE_FREQUENCY_BINARY_D3PSD / D3RMS / D3FTG output requests.

    OpenRadioss has no frequency-domain binary databases; the requests are kept
    so the offline post-processor (tools/modal_random_response.py) can honour
    the D3PSD output band.  fmin/fmax are in the deck's frequency unit
    (cycles per time-unit: a kg-mm-ms deck means kHz).
    """
    kind: str           # "D3PSD" | "D3RMS" | "D3FTG"
    binary: int = 1
    psetid: int = 0
    fmin: float = 0.0   # D3PSD only: output band lower bound
    fmax: float = 0.0   # D3PSD only: output band upper bound
    nfreq: int = 0      # D3PSD only: number of output frequencies
    fspace: int = 0     # D3PSD only: 0 = linear, 1 = log, 2 = biased
    lcfreq: int = 0     # D3PSD only: curve of explicit output frequencies


# ── Control blocks ─────────────────────────────────────────────────────────

@dataclass
class ControlAccuracy:
    osu: int            # angular momentum conservation flag
    inn: int            # invariant node numbering
    iacc: int           # improved accuracy for implicit (1=on)


@dataclass
class ControlContact:
    slsfac: float       # slave penalty scale factor
    rwpnal: float       # rigid wall penalty scale
    islchk: int         # initial penetration check
    shlthk: int         # shell thickness consideration
    penopt: int         # penalty option
    thkchk: int         # thickness change check


@dataclass
class DampingGlobal:
    """LS-DYNA *DAMPING_GLOBAL: mass-proportional Rayleigh damping (C = α·M).

    Maps to OpenRadioss /DAMP (starter block keyword, Reference Guide p.130).
    """
    valdmp: float       # α coefficient (LS-DYNA valdmp = mass-prop α)
    lcid: int = 0       # load curve for time-varying (0 = constant)
    # Per-DOF scale factors (LS-DYNA stx..srz; 0 = use valdmp uniformly)
    stx: float = 0.0
    sty: float = 0.0
    stz: float = 0.0
    srx: float = 0.0
    sry: float = 0.0
    srz: float = 0.0


@dataclass
class DampingPartStiffness:
    """LS-DYNA *DAMPING_PART_STIFFNESS: stiffness-proportional damping per part.

    In LS-DYNA: β_part = 2·coef/ω_max where ω_max is the highest part frequency
    (computed internally). For OpenRadioss /DAMP we pass `coef` directly as β
    since we can't estimate ω_max at conversion time — user may need to tune.
    """
    pid: int            # part ID
    coef: float         # LS-DYNA Rayleigh stiffness damping ratio (typ. 0.01-0.10)


@dataclass
class DampingPartMass:
    """LS-DYNA *DAMPING_PART_MASS / _SET: mass-proportional damping, part-scoped.

    Card 1 (10-wide fields, Manual Vol I R16 p.15-8): ``PID|PSID LCID SF FLAG``;
    the Scale Factor Card ``STX STY STZ SRX SRY SRZ`` follows only when
    ``FLAG == 1``.

    Unlike *DAMPING_GLOBAL this card carries **no constant-value field** — the
    damping constant comes entirely from ``LCID`` (``F_damp = D_s·m·v`` with
    ``D_s`` read off the curve), and ``SF`` only rescales it. Maps to plain
    /DAMP ``Alpha`` (both sides are ``F = -α·m·v``); see
    :func:`k2rad.writer.loads._make_damping_part_mass` for the constant-value
    reduction a /BEGIN 2022 deck forces.

    dyna2rad has **no converter for this keyword at all** (``convertdampings.
    cxx`` selects only GLOBAL/PART_STIFFNESS/RELATIVE/FREQUENCY_RANGE at lines
    51/167/247/321) — it parses the card and silently drops it. k2rad converts
    it deliberately, as a documented super-set of dyna2rad.
    """
    pid: int            # PID, or PSID when is_set
    is_set: bool        # True for the _SET spelling (pid is a *SET_PART id)
    lcid: int = 0       # damping constant vs time (0 = nothing to apply)
    sf: float = 1.0     # scale factor on the curve (LS-DYNA default 1.0)
    flag: int = 0       # 1 → the per-DOF Scale Factor Card follows
    stx: float = 0.0
    sty: float = 0.0
    stz: float = 0.0
    srx: float = 0.0
    sry: float = 0.0
    srz: float = 0.0


@dataclass
class DampingFrequencyRange:
    """LS-DYNA *DAMPING_FREQUENCY_RANGE[_DEFORM[_DMIG]] → /DAMP/FREQUENCY_RANGE.

    Card 1 (10-wide, Manual Vol I R16 p.15-11):
    ``CDAMP FLOW FHIGH PSID <blank> PIDREL IFLG ICARD2``.
    Card 2 (only when ``ICARD2 == 1`` **and** the DEFORM option): ``CDAMPV IPWP``.

    ``FLOW``/``FHIGH`` are mandatory and must satisfy ``0 < FLOW < FHIGH``: the
    Radioss starter fits three Maxwell branches at ``[FLOW, sqrt(FLOW·FHIGH),
    FHIGH]`` (``damping_range_compute_param.F90``) and ``FLOW = 0`` makes that
    3x3 system singular — NaN alpha/tau propagate silently into every element,
    because the ``KEY(1:4)=='FREQ'`` reader branch validates neither bound.
    """
    cdamp: float
    flow: float
    fhigh: float
    psid: int = 0       # *SET_PART id; 0 = "all parts EXCEPT other cards' parts"
    pidrel: int = 0     # optional rigid-body part; no Radioss equivalent
    iflg: int = 0       # 0 = iterative (LS-DYNA default), 1 = approximate
    icard2: int = 0     # 1 → Card 2 present (DEFORM only)
    cdampv: float = 0.0  # volumetric damping ratio (Card 2)
    ipwp: int = 1       # pore-pressure flag (Card 2)
    deform: bool = False  # the _DEFORM option
    dmig: bool = False    # the _DEFORM_DMIG option (superelements)


@dataclass
class DampingRelative:
    """LS-DYNA *DAMPING_RELATIVE → /DAMP/VREL (a radioss2024 card).

    Card 1 (10-wide, Manual Vol I R16 p.15-16):
    ``CDAMP FREQ PIDRB PSID DV2 LCID``. The manual's Type row prints ``PIDRB``
    as ``F``; that is a typo — it is a part id and is written right-justified
    as an integer.

    Damping force, Remark 3: ``F = -(D·m·v) - (DV2·m·v^2)`` with
    ``D = 4*pi*CDAMP*FREQ`` and ``v`` measured RELATIVE to the point of the
    rigid body ``PIDRB`` at the node's coordinates. That is byte-for-byte the
    Radioss ``damp_a = Alpha_x*4*pi*freq`` of
    ``engine/source/assembly/damping_vref_compute_dampa.F90``, so the card is a
    clean 1:1 — but only from /BEGIN 2024 up. See
    :func:`k2rad.writer.loads._resolve_damping_relative` for the measured
    version gate that keeps k2rad from emitting it.
    """
    cdamp: float
    freq: float
    pidrb: int = 0
    psid: int = 0
    dv2: float = 0.0    # quadratic velocity term; Radioss Alpha2_x
    lcid: int = 0       # fraction of critical damping vs time; REPLACES CDAMP


@dataclass
class ControlCpu:
    cputim: float       # max CPU time in seconds


@dataclass
class ControlEnergy:
    hgen: int           # hourglass energy (1=on, 2=on+contact)
    rwen: int           # rigid wall energy (1=on)
    slnten: int         # sliding interface energy (1=on)
    rylen: int          # rayleigh damping energy (1=on)


@dataclass
class ControlHourglass:
    ihq: int            # hourglass control type (1-6)
    qh: float           # hourglass viscosity coefficient


@dataclass
class HourglassDef:
    """A *HOURGLASS card, referenced per-part via the *PART HGID field. Only the
    two fields dyna2rad consumes are stored: IHQ (formulation → Radioss Isolid)
    and QM (the hourglass coefficient → /PROP h). The bulk-viscosity and shell
    coefficients IBQ/Q1/Q2/QB/VDC/QW are parsed-then-dropped, exactly as
    dyna2rad does (they have no k2rad /PROP mapping)."""
    hgid: int
    ihq: int
    qm: float


@dataclass
class ControlImplicitAuto:
    iauto: int          # auto timestep flag (0=off,1=on)
    iteopt: int         # optimal iterations per step
    itewin: int         # iteration window
    dtmin: float        # minimum timestep
    dtmax: float        # maximum timestep
    kfail: int          # max failures before cut


@dataclass
class ControlImplicitDynamics:
    imass: int          # 0=quasi-static,1=transient
    gamma: float        # Newmark gamma (0.5=no damp)
    beta: float         # Newmark beta (0.25=avg accel)
    alpha: float        # HHT alpha (0=pure Newmark)


@dataclass
class ControlOutput:
    npopt: int          # 0=print node/elem, 1=suppress
    neecho: int         # nodal echo flag


@dataclass
class ControlShell:
    wrpang: float       # warping angle threshold
    esort: int          # element sorting flag
    irnxx: int          # shell normal update
    istupd: int         # shell thickness update (0=off,1-4=on)
    theory: int         # default shell theory
    bwc: int            # warping stiffness
    intgrd: int         # integration rule


@dataclass
class ControlSolid:
    esort: int          # element sorting
    fmatrix: int        # deformation gradient type
    niptets: int        # integration points for tet


@dataclass
class ControlImplicitGeneral:
    imflag: int         # 0=explicit,4=implicit,5=implicit springback
    dt0: float          # initial time step
    imform: int
    nsbs: int           # subcycles


@dataclass
class ControlImplicitEigenvalue:
    """*CONTROL_IMPLICIT_EIGENVALUE → /EIG (normal-modes / modal analysis).

    Only ``neig`` (number of eigenmodes) maps cleanly to /EIG Nmod. LS-DYNA's
    frequency-window flags (lflag/lftend, rflag/rhtend) default to ±1e29
    sentinels meaning "no bound", so Cutfreq/Freqmin are left 0 (engine default
    shift, no upper cutoff) unless a finite, flagged bound is given.
    """
    neig: int                  # number of eigenmodes (Nmod); abs() of LS-DYNA neig
    freqmin: float = 0.0       # lower frequency bound (/EIG Freqmin); 0 = default
    cutfreq: float = 0.0       # upper frequency cutoff (/EIG Cutfreq); 0 = none


@dataclass
class ControlImplicitSolution:
    nsolvr: int         # solver (11=MUMPS,12=PARDISO)
    ilimit: int         # max stiffness reformations
    maxref: int         # max refinements
    dctol: float        # displacement convergence
    ectol: float        # energy convergence
    nlprint: int        # nonlinear print flag
    rctol: float = 0.0  # residual/force convergence (LS-DYNA rctol; 1e10 = off)


@dataclass
class ControlTermination:
    endtim: float


@dataclass
class ControlTimestep:
    dtinit: float
    tssfac: float
    # DT2MS: <0 = mass scaling to hold the explicit time step at |DT2MS|
    # (→ /DT/NODA/CST). 0 or >0 (init-only) = no mass scaling.
    dt2ms: float = 0.0
    # TSLIMT (card field 3): the shell time-step floor. In LS-DYNA this is the
    # step at which a shell is stiffness-reduced or, with ERODE=1, DELETED.
    # Carried to /DT/<elem>/DEL Tmin.
    tslimt: float = 0.0
    # ERODE (card field 6): 1 = delete elements whose step falls below the
    # floor, rather than merely limiting it. This is the user's explicit
    # consent to LOSE ELEMENTS, which is why k2rad emits no deletion floor
    # without it (or without the explicit --dt-del opt-in).
    erode: int = 0


# ── Database / output ──────────────────────────────────────────────────────

@dataclass
class DbD3Plot:
    dt: float
    npltc: int          # number of plots


@dataclass
class DbHistory:
    """One *DATABASE_HISTORY_<FAMILY>[_SET][_LOCAL][_ID] request.

    ``db_type`` is the keyword tail as the dispatcher resolved it — "SHELL",
    "SOLID", "TSHELL", "NODE", "SPH", "BEAM", "DISCRETE", "SEATBELT", the
    ``_SET`` spellings of each, and "NODE_LOCAL" / "NODE_SET_LOCAL". The three
    optional columns are populated only by the spellings that carry them:

      * ``cids`` / ``refs`` — the ``CID`` and ``REF`` columns of a ``_LOCAL``
        card (Vol I R16 p.16-113 Card 1c). One entry per entry in ``ids``, so
        the per-entity ``skew_ID`` column of ``/TH/NODE`` can be built from
        them. ``_LOCAL`` exists ONLY for NODE / NODE_SET (a full-text scan of
        the R16 and R17 manuals finds no BEAM_LOCAL, DISCRETE_LOCAL or
        SEATBELT_LOCAL), which lines up with Radioss: ``/TH/NODE`` is the only
        group type in this batch whose id card HAS a skew column.
      * ``names`` — the 70-char ``HEADING`` of an ``_ID`` card, written into the
        ``elem_name`` column of the emitted group so a T01 channel keeps the
        label the deck gave it.
    """
    db_type: str        # "SHELL", "SOLID", "NODE", "BEAM", "DISCRETE", ...
    ids: List[int] = field(default_factory=list)
    cids: List[int] = field(default_factory=list)
    refs: List[int] = field(default_factory=list)
    names: List[str] = field(default_factory=list)


@dataclass
class DbNodalForceGroup:
    """*DATABASE_NODAL_FORCE_GROUP[_TITLE] — one node set whose reaction is
    written to LS-DYNA's ``nodfor`` file, in the optional local system CID.
    The card carries no DT of its own: "The output interval must be specified
    using *DATABASE_NODFOR" (Vol I R16 p.16-121)."""
    nsid: int
    cid: int = 0
    title: str = ""


@dataclass
class ControlParallel:
    """*CONTROL_PARALLEL (Vol I R16 p.12-448). Only CONST reaches OpenRadioss:
    CONST=1 ("consistency on") is the engine's /PARITH/ON, i.e. force assembly
    in a thread-count-independent order. NCPU is an SMP thread count, which in
    OpenRadioss is the runtime ``-nt`` argument and not a deck card at all;
    NUMRHS and PARA have no /PARITH sub-option. All three are read so the
    converter can name them as dropped."""
    ncpu: int = 0
    numrhs: int = 0
    const: int = 0
    para: int = 0


@dataclass
class DbExtentBinary:
    """*DATABASE_EXTENT_BINARY — controls what goes into binary output files."""
    strflg: int = 0     # strain tensor output flag
    sigflg: int = 1     # stress tensor output flag
    epsflg: int = 1     # effective strain output flag
    rltflg: int = 1     # resultant stresses flag
    engflg: int = 1     # energy output flag
    shge: int = 0       # shell hourglass energy flag


# ── Seatbelts / restraints (*ELEMENT_SEATBELT* family) ───────────────────────


@dataclass
class SeatbeltElem:
    """*ELEMENT_SEATBELT — a 1D belt /SPRING, or a 2D belt /SHELL.

    LS-DYNA card (``Keyword971/ELEMENTS/seatbelt.cfg:64``)::

        CARD("%8d%8d%8d%8d%8d%16lg%8d%8d",
             id, collector, node1, node2, SBRID, SLEN, node3, node4)

    Eight fields in EIGHT-wide cells except SLEN, which is SIXTEEN wide and
    therefore spans two of them — the same trap ``*ELEMENT_MASS`` and
    ``*ELEMENT_SPH`` carry, and the reason ``handlers._seatbelt_elem_card``
    exists instead of a uniform slice.

    ``n3``/``n4`` both non-zero makes the element a 2D (shell) belt; otherwise
    it is a 1D belt spanning ``n1``-``n2`` (dyna2rad ``convertelements.cxx:
    86-95``).
    """
    eid: int
    pid: int
    n1: int
    n2: int
    sbrid: int = 0          # *ELEMENT_SEATBELT_RETRACTOR this element starts in
    slen: float = 0.0       # initial SLACK length — no Radioss slot, see writer
    n3: int = 0
    n4: int = 0

    @property
    def is_2d(self) -> bool:
        return self.n3 > 0 and self.n4 > 0


@dataclass
class SectionSeatbelt:
    """*SECTION_SEATBELT — ``SECID AREA THICK``.

    Both AREA and THICK are CONTACT numbers in LS-DYNA ("AREA — cross sectional
    area … used for the contact stiffness", default 0.01; "THICK — belt
    thickness … used for contact"), and neither has a Radioss slot: the
    /PROP/TYPE23 ``Area`` cell is a MASS and STIFFNESS area (``rinit3.F:474``
    ``MASS = GEO(1)*LENGTH*RHO``; ``r23l114def3.F:224`` ``XK_COMP = E*AREA``),
    which is a different quantity. dyna2rad ignores this card entirely and
    takes its property area from ``*MAT_SEATBELT``'s ``A`` instead
    (``convertprops.cxx:2538``); k2rad does the same and names the loss.
    """
    secid: int
    title: str = ""
    area: float = 0.0
    thick: float = 0.0


@dataclass
class MatSeatbelt:
    """*MAT_SEATBELT / *MAT_B01 (and their ``_2D`` spellings) → /MAT/LAW114
    (1D belt springs) or /MAT/LAW119 (2D belt shells).

    WHICH law is decided by the PROPERTY the part carries, not by the material
    keyword — dyna2rad ``convertmats.cxx:517-526`` branches on
    ``propKeyWord.find("SEATBELT")`` vs ``propKeyWord.find("SHELL")``, so a
    ``*MAT_SEATBELT`` on a ``*SECTION_SHELL`` is LAW119 and a
    ``*MAT_SEATBELT_2D`` on a ``*SECTION_SEATBELT`` is LAW114. ``is_2d`` records
    only which keyword was WRITTEN, so cards 3/4 (the ``_2D``-only coating and
    weft data) can be reported as present-but-unused on a 1D belt.

    Card 1  ``MID MPUL LLCID ULCID LMIN CSE DAMP E``
    Card 2  ``A I J AS F M R``                     — present only when ``E > 0``
    Card 3  ``P1DOFF FORM ECOAT TCOAT SCOAT EB PRBA PRAB``   — ``_2D`` only
    Card 4  ``GAB``                                          — ``_2D`` only
    """
    mid: int
    mpul: float = 0.0       # mass per unit length
    llcid: int = 0          # loading   force vs ENGINEERING STRAIN
    ulcid: int = 0          # unloading force vs ENGINEERING STRAIN
    lmin: float = 0.0
    cse: float = 0.0        # compressive-stress elimination (2D belts only)
    damp: float = 0.1       # Rayleigh damping fraction (shells only)
    e: float = 0.0          # Young's modulus for the optional bending model
    # card 2 — only meaningful when e > 0
    has_card2: bool = False
    a: float = 0.0          # cross-sectional area
    i: float = 0.0          # area moment for bending
    j: float = 0.0          # torsional constant  (default 2*I)
    as_: float = 0.0        # shear area          (default A)
    f: float = 0.0          # max shear/compression force (default 1e20)
    m: float = 0.0          # max torque                  (default 1e20)
    r: float = 0.0          # rotational inertia scale    (default 0.05)
    # card 3/4 — the *_2D option only
    is_2d: bool = False
    has_card3: bool = False
    p1doff: float = 0.0
    form: int = 0
    ecoat: float = 0.0
    tcoat: float = 0.0
    scoat: float = 0.0
    eb: float = -0.1        # transverse modulus; NEGATIVE = ratio of E11
    prba: float = 0.3       # minor in-plane Poisson ratio  -> /MAT/LAW119 NU12
    prab: float = 0.0       # major in-plane Poisson ratio  (default = PRBA)
    has_card4: bool = False
    gab: float = 0.0        # in-plane shear modulus -> /MAT/LAW119 G12


@dataclass
class SeatbeltSlipring:
    """*ELEMENT_SEATBELT_SLIPRING → /SLIPRING/SPRING or /SLIPRING/SHELL.

    Card 1 ``SBSRID SBID1 SBID2 FC SBRNID LTIME FCS ONID`` — note the order:
    ``FC`` sits BETWEEN the two element ids and the anchorage node, which is not
    where a reading of the manual's variable list alone would put it
    (``Keyword971_R13.0/ELEMENTS/element_seatbelt_slipring.cfg:11``).

    A NEGATIVE ``FC``/``FCS`` is a *DEFINE_CURVE id (friction vs time) rather
    than a coefficient — the cfg declares both cells ``SCALAR_OR_OBJECT`` — and
    a NEGATIVE ``SBRNID`` makes this a SHELL-belt slipring whose ``SBID1``/
    ``SBID2`` are ``*SET_SHELL_LIST`` ids and whose ``|SBRNID|`` is a
    ``*SET_NODE``.

    Card 2 ``K FUNCID DIRECT DC <blank> LCNFFD LCNFFS`` is read only when
    ``ONID != 0`` (the cfg's own condition).
    """
    sbsrid: int
    sbid1: int = 0
    sbid2: int = 0
    fc: float = 0.0
    fc_func: int = 0        # |FC| when FC < 0
    sbrnid: int = 0         # > 0 node, < 0 *SET_NODE (shell belt)
    ltime: float = 1.0e20
    fcs: float = 0.0
    fcs_func: int = 0       # |FCS| when FCS < 0
    onid: int = 0
    has_card2: bool = False
    k: float = 0.0
    funcid: int = 0
    direct: int = 0
    dc: float = 0.0
    lcnffd: int = 0
    lcnffs: int = 0

    @property
    def is_shell(self) -> bool:
        return self.sbrnid < 0


@dataclass
class SeatbeltRetractor:
    """*ELEMENT_SEATBELT_RETRACTOR → /RETRACTOR/SPRING.

    Card 1 ``SBRID SBRNID SBID SID1 SID2 SID3 SID4 DSID``
    Card 2 ``TDEL PULL LLCID ULCID LFED LCFL FLOPT``

    ``SBRNID < 0`` is a SHELL belt (``|SBRNID|`` a ``*SET_NODE``, ``SBID`` a
    ``*SET_SHELL_LIST``); Radioss has only ``/RETRACTOR/SPRING`` — there is no
    ``/RETRACTOR/SHELL`` card in ``hm_cfg_files/config/CFG/radioss2022/
    SEATBELTS/`` at all — so that flavour is warn-dropped whole.
    """
    sbrid: int
    sbrnid: int = 0
    sbid: int = 0
    sid1: int = 0
    sid2: int = 0
    sid3: int = 0
    sid4: int = 0
    dsid: int = 0           # deactivation sensor — no Radioss slot
    tdel: float = 0.0
    pull: float = 0.0
    llcid: int = 0
    ulcid: int = 0
    lfed: float = 0.0
    lcfl: int = 0           # no Radioss slot
    flopt: int = 0          # no Radioss slot

    @property
    def is_shell(self) -> bool:
        return self.sbrnid < 0

    def sensor_ids(self):
        return [s for s in (self.sid1, self.sid2, self.sid3, self.sid4) if s > 0]


@dataclass
class SeatbeltPretensioner:
    """*ELEMENT_SEATBELT_PRETENSIONER — folded onto its retractor's card 3.

    Card 1 ``SBPRID SBPRTY SBSID1 SBSID2 SBSID3 SBSID4``
    Card 2 ``SBRID TIME PTLCID LMTFRC LMTPIN``

    The ``Keyword971`` cfg gives card 2 a TYPE-DEPENDENT layout (``SBSID TIME
    <blank> LMTFRC`` for SBPRTY 2/3, ``<blank> TIME <blank> LMTFRC`` for the
    rest); every later cfg (``Keyword971_R7.1``, ``_R13.0``) and LS-PrePost
    4.13.5 write the uniform ``SBRID TIME PTLCID LMTFRC LMTPIN`` card, which is
    what is read here. The difference only ever touches field 0 of card 2 for
    SBPRTY 2/3/7/9 — the four types that have no ``Tens_typ`` at all and are
    warn-dropped whole — so the ambiguity never reaches a Radioss card.
    """
    sbprid: int
    sbprty: int = 0
    sbsid1: int = 0
    sbsid2: int = 0
    sbsid3: int = 0
    sbsid4: int = 0
    sbrid: int = 0          # the *ELEMENT_SEATBELT_RETRACTOR this pretensions
    time: float = 0.0
    ptlcid: int = 0
    lmtfrc: float = 0.0
    lmtpin: float = 0.0     # no Radioss slot

    def sensor_ids(self):
        return [s for s in (self.sbsid1, self.sbsid2, self.sbsid3,
                            self.sbsid4) if s > 0]


@dataclass
class SeatbeltSensor:
    """*ELEMENT_SEATBELT_SENSOR → /SENSOR/ACCE | /SENSOR/TIME | /SENSOR/DIST.

    Card 1 ``SBSID SBSTYP SBSFL``, then ONE type card whose layout is chosen by
    SBSTYP (``Keyword971_R12.0/SENSOR/element_seatbelt_sensor_no_sub.cfg``) —
    a #119 count-driven walk on a card-1 discriminator:

      1  ``NID DOF ACC ATIME``      node acceleration   → /SENSOR/ACCE + /ACCEL
      2  ``SBRID PULRAT PULTIM``    retractor pull-out RATE   → no target
      3  ``TIME``                   time                → /SENSOR/TIME
      4  ``NID1 NID2 DMX DMN``      node distance       → /SENSOR/DIST
      5  ``SBRID PULMX PULMN``      retractor pull-out  → no target
    """
    sbsid: int
    sbstyp: int = 0
    sbsfl: int = 0          # 1 = active during dynamic relaxation
    # type 1
    nid: int = 0
    dof: int = 0
    acc: float = 0.0
    atime: float = 0.0
    # type 2 / 5
    sbrid: int = 0
    pulrat: float = 0.0
    pultim: float = 0.0
    pulmx: float = 0.0
    pulmn: float = 0.0
    # type 3
    time: float = 0.0
    # type 4
    nid1: int = 0
    nid2: int = 0
    dmx: float = 0.0
    dmn: float = 0.0


@dataclass
class SeatbeltAccelerometer:
    """*ELEMENT_SEATBELT_ACCELEROMETER → /ACCEL (+ /SKEW/MOV, + /ADMAS).

    ``SBACID NID1 NID2 NID3 IGRAV INTOPT MASS``. Radioss ``/ACCEL`` is ONE node
    plus a skew, so the LS-DYNA triad becomes a ``/SKEW/MOV`` on (NID1, NID2,
    NID3) with ``/ACCEL`` pointing at NID1 — dyna2rad ``convertelements.cxx:
    448-462``. ``MASS`` is "distributed equally to the three nodes" in LS-DYNA.
    """
    sbacid: int
    nid1: int = 0
    nid2: int = 0
    nid3: int = 0
    igrav: int = 0
    intopt: int = 0
    mass: float = 0.0


# ── User conversion options (CLI flags) ──────────────────────────────────────

@dataclass
class ConvertOptions:
    """Opt-in conversion switches set from the CLI / convert() — NOT parsed from
    the .k file. All default to off so a default conversion is byte-identical.

    These productize the three proven manual deck-patches that make a
    force-control implicit deck (a *LOAD_RIGID_BODY pulling a clearance-fit pin
    held only by penalty contact) converge — see the writer for the physics:
      * ground_springs/ground_spring_k → soft /PROP/TYPE8 grounding springs on
        the loaded rigid body's free DOFs (bootstrap the singular t=0 tangent);
      * inter_gapmin → drop a pulled interface's Gapmin below its nodal clearance
        so it has 0 initial penetrations and engages cleanly (no contact limit
        cycle);
      * soften_stfac → reduce the TYPE7 penalty stiffness scale (chatter
        insurance).
    """
    ground_springs: bool = False
    ground_spring_k: float = 100.0                       # N/mm per loaded axis
    inter_gapmin: Dict[int, float] = field(default_factory=dict)  # inter_id → Gapmin
    soften_stfac: Optional[float] = None                 # None = engine auto (0)
    # Auto-Gapmin: derive each surface-to-surface interface's Gapmin from the
    # minimum node-to-node clearance between its two parts (Gapmin =
    # gapmin_factor × clearance), instead of hand-tuning Card-3 SST/SBST per
    # mesh. Explicit inter_gapmin entries still win. See k2rad.gapmin.
    auto_gapmin: bool = False
    gapmin_factor: float = 0.8                            # Gapmin = factor × clearance
    # Mesh transform: downgrade 10-node quadratic tets to 4-node linear tets
    # (keep the 4 corners, drop mid-edge nodes). Stiffer/less accurate but lets a
    # TET10-only source .k produce a TET4 run.
    tet10_to_tet4: bool = False
    # /IMPL/DT/FIXPOINT: number of evenly spaced times (k/N × endtim for
    # k = 1 … N) the implicit time-step controller is forced to land on, so a
    # clean animation / time-history state is produced at each milestone instead
    # of wherever the variable implicit step happens to fall. The OpenRadioss
    # engine caps the list at 100 (engine/source/input/freimpl.F); the writer
    # clamps to that 1…100 range and treats 0 as "off". Default 100 → a point
    # every 1% of the run. Implicit decks only (no effect on explicit output).
    fixpoint_count: int = 100
    # Modal (/EIG) emission for COMMERCIAL Altair Radioss (opt-in): the
    # open-source OpenRadioss engine ships the /EIG eigensolver only as a no-op
    # stub (the kernel is gated behind an undefined DNC build macro and the real
    # com/eig/*.F source is not in the release), so by default a
    # *CONTROL_IMPLICIT_EIGENVALUE deck is converted to the validated
    # stiffness-export recipe instead: one /IMPL/LINEAR step with
    # /IMPL/PRINT/STIF writes the assembled K to
    # 'local_stiffness_matrix_domain0', and tools/modal_solve.py solves the
    # eigenproblem offline (scipy). Set emit_eig to get the classic /EIG +
    # one-shot eigensolve engine instead — runnable only on commercial Radioss.
    emit_eig: bool = False
    # Deformable-deformable contact recipe (opt-in): the validated stabilization
    # for an implicit deck where two DEFORMABLE parts contact (e.g. force control
    # through a clearance-fit deformable pin). On a detected deformable-vs-
    # deformable /INTER/TYPE7 it sets Inacti=5 (mesh-scale engagement gap, no t=0
    # force spike); globally it sets /IMPL/DT/2 L_dtn=50 (iteration cap for the
    # slow LINEAR contact-force convergence) and /IMPL/QSTAT/DTSCAL=0.05 (anchors
    # the force-control soft-mode step-overshoot). Off by default — the converter
    # only WARNS that the recipe exists when it detects such contact (see
    # writer._warn_deformable_deformable_contact); turn this on to apply it.
    deformable_contact_recipe: bool = False
    # Blast ground plane for a surface-burst /LOAD/PBLAST (Exp_data=2). OpenRadioss
    # needs a reflecting ground; with no Ground_ID it assumes the plane is ⊥Z
    # through the detonation point and drops target segments on the far side —
    # wrong whenever the deck's vertical axis is not +Z. Values:
    #   "auto" (default) : infer the up-axis from geometry (the axis along which
    #                      the charge sits beyond the target) and synthesize a
    #                      flat /SURF/SEG ground plane through the charge whose
    #                      normal points at the target, used as Ground_ID;
    #   "none"           : emit no Ground_ID (OpenRadioss's ⊥Z default) + warn;
    #   "X"/"Y"/"Z"/"-X"/"-Y"/"-Z" : force the ground-normal (up) axis.
    # Free-air bursts (Exp_data=1) need no ground and ignore this.
    blast_ground: str = "auto"
    # Element-free CoG masters for *MAT_RIGID parts (ON by default). Each
    # *MAT_RIGID part gets a NEW synthesized node at its nodal centroid as the
    # /RBODY master (the same treatment CNRBs always get) — mesh nodes stay put
    # and starter WARNINGs 448 "MAIN NODE CONNECTED TO AN ELEMENT" + 1624 "MAIN
    # NODE REMOVED FROM SECONDARY NODE SET" disappear. It also makes the deck
    # AMS-compatible (a mesh-node master trips AMS ERROR 1066). Set False
    # (--no-rigid-cog-master) to instead reuse the part's lowest-id mesh node as
    # the master: that node is an element corner (WARNINGs 448/1624) and
    # OpenRadioss relocates it to the centre of mass at runtime (ICoG default),
    # so its coordinates appear to change in post-processing — but it keeps the
    # master-node id stable for scripts that address loads/readouts by it.
    rigid_cog_master: bool = True
    # Restart (.rst) files. OpenRadioss writes engine restart files by default;
    # they are only needed for /RERUN or crash recovery and add up to a lot of
    # disk on a large model. Off by default here → the engine deck gets
    # /RFILE/OFF. Set True to keep OpenRadioss's default restart writing.
    write_restart: bool = False
    # Advanced Mass Scaling (opt-in). By default a mass-scaled explicit deck
    # (*CONTROL_TIMESTEP DT2MS<0) gets /DT/NODA/CST, which holds the time step by
    # adding real (diagonal) nodal mass — fast, but on a fine mesh the added mass
    # can dwarf the physical mass and corrupt the dynamics (kinetic energy runs
    # away). With this flag the deck instead gets AMS: engine /DT/AMS + starter
    # /AMS (grpart_ID 0 = all parts; the solver auto-skips rigid bodies), which
    # holds the step with a COUPLED mass matrix that preserves the low-frequency
    # response. AMS solves a preconditioned conjugate gradient each cycle and can
    # DIVERGE ("AMS IS LIKELY DIVERGING") on stiff / high-stiffness-contrast /
    # contact-heavy models or at a large Tmin/element-dt ratio; if it does, drop
    # the flag (back to /DT/NODA/CST) or lower |DT2MS|. Forces element-free rigid
    # masters (implies rigid_cog_master) so no whole-part rigid body's master is
    # an element node (AMS ERROR 1066). Off by default.
    ams: bool = False

    # Which /PROP/SHELL Ishell an LS-DYNA shell ELFORM with no exact Radioss
    # counterpart maps to — "qbat" (12, fully integrated; what every
    # conversion to date produced) or "qeph" (24, reduced + physically
    # stabilised, far closer to ELFORM=2 Belytschko-Tsay). Defaults to "qbat"
    # so no existing deck changes underfoot. See
    # writer/common._elform_to_ishell for why this is a choice at all and why
    # under-integrated Ishell 1..4 is deliberately not offered.
    shell_formulation: str = "qbat"
    # *CONTACT_ERODING_* solid sides: emit /SURF/PART/EXT (external skin only)
    # instead of the default /SURF/PART/ALL.
    #
    # /ALL is what makes eroding contact WORK on solids. The starter puts every
    # interior (two-solid) face in the segment list with a NEGATIVE stiffness
    # (i25sti3.F:950-951 "Case of internal segment : put stiffness to
    # negative"), and the engine flips it active the moment one of the two
    # solids dies (check_surface_state.F:174-203, NB_CONNECTED_ELM==1 and
    # STFM<0 → ACTIVATION). With /EXT there are no interior segments, so the
    # machinery arms (IPARI(100)=1 needs only Idel>0 and a solid segment) and
    # then has nothing to wake up — the newly exposed crater face is
    # frictionless and stiffness-free, SILENTLY. dyna2rad has exactly this gap:
    # it builds contact surfaces from a bare PART clause with no opt_A
    # (convertcontacts.cxx:264-274).
    #
    # Set True to reproduce LS-DYNA SMP's literal IADJ=0 ("solid element faces
    # are included only for free boundaries") instead. Note LS-DYNA MPP
    # hardcodes IADJ=1, so a blank IADJ in an MPP-authored deck means /ALL.
    eroding_surf_ext: bool = False
    # *AIRBAG_PARTICLE: emit a uniform-pressure /MONVOL/AIRBAG1 instead of the
    # finite-volume /MONVOL/FVMBAG2 the CPM bag actually maps to.
    #
    # FVMBAG2 is the faithful target and the default, but it CANNOT RUN on an
    # open-source OpenRadioss build. hm_read_monvol_type11.F:299 hard-wires
    # KMESH = 14, init_monvol.F then dispatches CASE (12, 14) to
    # HYPERMESH_TETRA, and starter/stub/fvmbags_stub.F (guarded #ifndef DNC)
    # is the whole of it:
    #
    #     SUBROUTINE HYPERMESH_TETRA(...)
    #       WRITE(6,*) "FVMBAGS require a mesher"
    #       STOP
    #     END SUBROUTINE
    #
    # MEASURED on a probe deck: the reader echoes the whole /MONVOL cleanly,
    # then the starter prints that line and terminates before writing any
    # restart file. So the FVMBAG2 deck is CORRECT and UNRUNNABLE here, and
    # this flag trades the finite-volume pressure field for a bag that runs.
    airbag_particle_uniform: bool = False

    @property
    def shell_default_ishell(self) -> int:
        """The Ishell an unmapped ELFORM resolves to, per the user's choice."""
        from .writer.common import ISHELL_QBAT, SHELL_FORMULATIONS
        return SHELL_FORMULATIONS.get(self.shell_formulation, ISHELL_QBAT)
    # /DT/<elem>/DEL Tmin [s]: delete an element whose time step reaches
    # this. None = only what *CONTROL_TIMESTEP ERODE=1 + TSLIMT asks for.
    # Opt-in because the card DELETES ELEMENTS; see
    # writer/assembly._make_engine_dt_deletion.
    dt_del: "float | None" = None


# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConversionState:
    """Holds all data parsed from the .k file.  Written by handlers,
    read by the writer to produce .rad output.

    A dataclass so the field set is a typed, documented contract between the
    handlers and the writer (typo-safe access, free repr, mypy-checkable).
    Every field has a default, so ``ConversionState()`` stays a no-arg
    constructor; mutable collections use ``field(default_factory=...)``.
    """

    # ── Identity ───────────────────────────────────────────────
    model_title: str = "Model"
    is_implicit: bool = False
    # *CONTROL_IMPLICIT_EIGENVALUE present → normal-modes (/EIG) analysis.
    # Switches the engine to a one-shot /IMPL/LINEAR eigensolve and skips
    # the inert contact stub (the eigen path ignores contact, and the stub
    # crashes the implicit-eigen setup).
    is_modal: bool = False
    _auto_id: int = 90001               # counter for auto-generated IDs
    # Unit system written to the /BEGIN header (mass, length, time).
    # Defaults to the LS-DYNA ton-mm-s system; overridable via convert().
    units: Tuple[str, str, str] = ("Mg", "mm", "s")
    # Opt-in conversion switches (CLI flags); see ConvertOptions.
    options: ConvertOptions = field(default_factory=ConvertOptions)

    # ── Mesh ───────────────────────────────────────────────────
    nodes: Dict[int, NodeData] = field(default_factory=dict)
    shell_elems: List[ShellElem] = field(default_factory=list)
    solid_elems: List[SolidElem] = field(default_factory=list)
    # *ELEMENT_TSHELL → /BRICK on a /PROP/TYPE20|21|22. Its OWN container, not
    # solid_elems — see TshellElem.
    tshell_elems: List[TshellElem] = field(default_factory=list)
    # *ELEMENT_SPH → /SPHCEL on a /PROP/SPH (TYPE34). Its OWN container — an SPH
    # particle has no connectivity at all (it IS a node with a mass), so it
    # belongs on none of the other element lists; see SphCell.
    sph_elems: List[SphCell] = field(default_factory=list)
    beam_elems: List[BeamElem] = field(default_factory=list)
    # *ELEMENT_DISCRETE → /SPRING (on a /PROP/TYPE4 built by the writer)
    discrete_elems: List[DiscreteElem] = field(default_factory=list)
    # *ELEMENT_PLOTEL → an inert /SPRING on a synthesized PLOTEL /PART+/PROP
    plotel_elems: List[PlotelElem] = field(default_factory=list)
    # /NODE ids synthesized for *ELEMENT_BEAM_ORIENTATION third nodes. Radioss
    # tags a beam's third node CHECK_USED, not CHECK_BEAM (hm_read_beam.F:181):
    # it is a pure geometric reference that carries NO beam stiffness, so on an
    # implicit deck one of these is a zero row in the tangent exactly like an
    # unattached node — the free-node guard uses this set to see through the
    # /BEAM connectivity and fix them.
    beam_orient_nodes: Set[int] = field(default_factory=set)
    # One record per *ELEMENT_SHELL/_BEAM block with an option k2rad does not
    # model — see ProvisionalElemBlock and _screen_provisional_elements.
    provisional_elem_blocks: List[ProvisionalElemBlock] = field(
        default_factory=list)
    # Node ids handed out by next_node_id() but not yet written into
    # self.nodes — see that method.
    _reserved_node_ids: Set[int] = field(default_factory=set)
    # Idempotency guard for _normalize_tet10_ordering: the LS-DYNA→Radioss apex
    # permutation is a 3-cycle (not self-inverse), so a blind re-run corrupts the
    # connectivity. Set True the first time the pass runs (it may be invoked both
    # before --auto-gapmin analysis and inside build_starter).
    tet10_normalized: bool = False

    # ── Model entities ─────────────────────────────────────────
    parts: Dict[int, PartData] = field(default_factory=dict)
    sec_shells: Dict[int, SectionShell] = field(default_factory=dict)
    # *INTEGRATION_SHELL user integration rules, keyed by IRID. Bound from a
    # *SECTION_SHELL whose card-1 QR/IRID field is negative; the rule's NIP then
    # WINS over the section's (dyna2rad reads NIP off the rule and never off the
    # section, convertprops.cxx:1890-1892), and its per-point WF/PID become the
    # layer thicknesses and materials of a layered /PROP/TYPE11.
    integration_shells: Dict[int, IntegrationShell] = field(default_factory=dict)
    sec_solids: Dict[int, SectionSolid] = field(default_factory=dict)
    # *SECTION_TSHELL → /PROP/TYPE20|21|22, emitted under the SECID verbatim
    # (the /PROP/TYPE43 shape — no /PART repoint). A FOURTH SECID-keyed /PROP
    # namespace, so next_prop_id() guards against it too.
    sec_tshells: Dict[int, SectionTshell] = field(default_factory=dict)
    # *SECTION_SPH → /PROP/SPH, emitted under the SECID verbatim (the same shape
    # /PROP/TYPE20|21|22 uses — no /PART repoint). A FIFTH SECID-keyed /PROP
    # namespace, so next_prop_id() guards against it too.
    sec_sph: Dict[int, SectionSph] = field(default_factory=dict)
    sec_beams: Dict[int, SectionBeam] = field(default_factory=dict)
    # *INTEGRATION_BEAM user cross-section integration rules, keyed by IRID.
    # Bound from a *SECTION_BEAM whose card-1 field 4 (QR/IRID) is negative;
    # the rule then OWNS the quadrature (the section's own QR field is dead)
    # and its point cloud or standard shape becomes a /PROP/TYPE18.
    integration_beams: Dict[int, IntegrationBeam] = field(default_factory=dict)
    # secid → the resolved /PROP/TYPE18 payload for a *SECTION_BEAM that binds a
    # usable rule AND whose parts carry a TYPE18-compatible material. Filled by
    # the _resolve_integration_beams prepass; a section absent from this dict
    # keeps the ordinary /PROP/BEAM (TYPE3) path.
    int_beam_props: Dict[int, IntBeamProp] = field(default_factory=dict)
    # *SECTION_DISCRETE → /PROP/TYPE4 flags (spring/damper connectors)
    sec_discrete: Dict[int, SectionDiscrete] = field(default_factory=dict)
    # *SECTION_SEATBELT → /PROP/TYPE23 (SPR_MAT). A SIXTH SECID-keyed /PROP
    # namespace: the belt property is emitted under the SECID verbatim, so
    # next_prop_id() has to dodge it like the other five.
    sec_seatbelts: Dict[int, SectionSeatbelt] = field(default_factory=dict)
    # part_id → synthesized orthotropic property id for a *MAT_ANISOTROPIC_
    # VISCOPLASTIC (LAW128) part. LAW128 is orthotropic-only, so such a part
    # cannot use the isotropic /PROP/SHELL|SOLID — the writer emits a dedicated
    # /PROP/TYPE9 (shell) or /PROP/TYPE6 (solid) and points the /PART at it.
    ortho_prop_ids: Dict[int, int] = field(default_factory=dict)
    # part_id → synthesized COMPOSITE property id. Same split mechanism as
    # ortho_prop_ids (the /PART is repointed in _make_parts_and_elements and the
    # section's shared /PROP/SHELL is suppressed when every part left it), for
    # the four orthotropic/composite material families and *PART_COMPOSITE.
    # Claimed FIRST: _assign_ortho_props and _assign_hourglass_props both skip a
    # part that already has a composite property.
    composite_prop_ids: Dict[int, int] = field(default_factory=dict)
    # part_id → synthesized FABRIC property id (*MAT_FABRIC → /PROP/TYPE9 for
    # /MAT/LAW19, /PROP/TYPE16 for /MAT/LAW58). Same split mechanism as
    # composite_prop_ids, and claimed FIRST among the shell families:
    # _assign_composite_props / _assign_ortho_props / _assign_hourglass_props
    # all skip a part that already has one. The reason is the starter's
    # material/property CLASS check, not a duplicate id — LAW19 on a TYPE16
    # (or LAW58 on a TYPE9, or either on the isotropic /PROP/SHELL a
    # *SECTION_SHELL would give it) is ERROR 3047. See writer/fabric.py.
    fabric_prop_ids: Dict[int, int] = field(default_factory=dict)
    # *PART_COMPOSITE parts, keyed by PID — the per-ply layup that replaces the
    # section-derived property (→ /PROP/TYPE51 + one /PROP/TYPE19 per ply).
    part_composites: Dict[int, PartComposite] = field(default_factory=dict)
    # part_id → *ELEMENT_SHELL_BETA angle (degrees) FOLDED into the part's
    # synthesized orthotropic property, because the OpenRadioss starter reads
    # the per-element /SHELL Phi column only for IGTYP 17/51/52 and takes the
    # layer angle from the PROPERTY alone for IGTYP 9/10/11/16 (starter/source/
    # elements/shell/coque/corthini.F:202-217, :429-435). Filled by the
    # _fold_element_beta prepass, which also zeroes the elements' own beta so
    # the deck states the angle exactly once.
    part_beta_fold: Dict[int, float] = field(default_factory=dict)
    # ── Thick shells ───────────────────────────────────────────
    # eid → the *ELEMENT_TSHELL_COMPOSITE per-element ply stack (card 2b).
    # Read so the writer can see whether a part's thick shells agree on one
    # layup — the only shape a Radioss per-PART /PROP/TYPE22 can express.
    tshell_elem_plies: Dict[int, List["CompositePly"]] = field(
        default_factory=dict)
    # pid → the per-PART thick-shell layup that becomes a /PROP/TYPE22, from
    # *PART_COMPOSITE_TSHELL or a uniform *ELEMENT_TSHELL_COMPOSITE stack.
    # Filled by the _resolve_tshells prepass (writer/tshell.py).
    tshell_layups: Dict[int, TshellLayup] = field(default_factory=dict)
    # pid → the synthesized /PROP/TYPE22 id for such a layup. Same /PART-repoint
    # mechanism as composite_prop_ids, and claimed FIRST among the thick-shell
    # routes: a part in here ignores its *SECTION_TSHELL property entirely.
    tshell_prop_ids: Dict[int, int] = field(default_factory=dict)
    # secid → a SYNTHESIZED /PROP id for a *SECTION_TSHELL whose SECID is also
    # claimed by another element family (a shell or ordinary-solid *PART on the
    # same section). Two /PROP cards on one id is starter ERROR 79, so the
    # thick-shell property moves here and its parts are repointed through
    # tshell_prop_ids. Filled by _split_mixed_family_sections; empty on the
    # ordinary one-family deck, where the property IS the SECID.
    tshell_section_prop_ids: Dict[int, int] = field(default_factory=dict)
    # secid → the *ELEMENT_TSHELL_BETA angle (degrees) FOLDED into that
    # section's property angle slot, because /BRICK has no per-element angle
    # column. Only set when every thick shell on the section agrees; the
    # elements' own beta is zeroed so the deck states the angle exactly once.
    tshell_beta_fold: Dict[int, float] = field(default_factory=dict)

    # ── SPH particles ──────────────────────────────────────────
    # secid → a SYNTHESIZED /PROP id for a *SECTION_SPH whose SECID is also
    # claimed by another element family. Two /PROP cards on one id is starter
    # ERROR 79, so the SPH property moves here and its parts are repointed
    # through sph_prop_ids. Same mechanism as tshell_section_prop_ids; empty on
    # the ordinary one-family deck, where the property IS the SECID.
    sph_section_prop_ids: Dict[int, int] = field(default_factory=dict)
    # pid → the /PROP/SPH id the part's /PART card must point at, when that is
    # NOT its own SECID (the mixed-family split above).
    sph_prop_ids: Dict[int, int] = field(default_factory=dict)
    # The /MAT twin of the two maps above. A *MAT_PLASTIC_KINEMATIC lands on
    # /MAT/LAW44, which does NOT declare SPH compatibility — starter ERROR 3046
    # refuses the whole deck the moment a particle sits on it — while /MAT/LAW2
    # does and expresses the identical bilinear law whenever the material has
    # no Cowper-Symonds rate term and no effective kinematic hardening. When
    # such a material is SHARED between SPH and non-SPH parts, one /MAT id
    # cannot be both laws, so writer/sph.py::_resolve_sph_materials allocates a
    # clone: mid → the synthesized /MAT/LAW2 id, and pid → that id for the SPH
    # parts whose /PART is repointed at it. Both empty on every deck without
    # particles on a *MAT_PLASTIC_KINEMATIC.
    sph_mat_clones: Dict[int, int] = field(default_factory=dict)
    sph_mat_ids: Dict[int, int] = field(default_factory=dict)
    # secid → the resolved /PROP/SPH payload (Mp, h, and whether the per-cell
    # MASS column is written at all). Filled by the _resolve_sph prepass and
    # read by BOTH the /SPHCEL emitter and the /PROP/SPH emitter, so the two
    # cannot disagree about where each particle's mass comes from.
    sph_props: Dict[int, "SphProp"] = field(default_factory=dict)
    # The /SPHCEL ids this conversion ACTUALLY emitted. A /TH/SPHCEL naming
    # anything else is starter ERROR 69 and the whole deck is refused (the #106
    # rule), so the TH writer intersects against this set.
    sph_cell_ids: Set[int] = field(default_factory=set)
    # *CONTROL_SPH — the global SPH controls; only NMNEIGH reaches /SPHGLO.
    control_sph: Optional["ControlSph"] = None

    # *HOURGLASS cards, keyed by HGID (referenced from *PART HGID). See
    # HourglassDef; consumed by the per-part hourglass /PROP overlay.
    hourglass_defs: Dict[int, "HourglassDef"] = field(default_factory=dict)
    # part_id → dedicated per-part /PROP id when the part's effective hourglass
    # (from its *HOURGLASS or the global *CONTROL_HOURGLASS) differs from its
    # section's base. Props are per-SECTION, so a per-part hourglass difference
    # forces a /PROP split — same mechanism as ortho_prop_ids above.
    hourglass_prop_ids: Dict[int, int] = field(default_factory=dict)
    # part_id → the resolved (h/hm coefficient, Isolid/Ishell override) that the
    # split /PROP emits. Isolid/Ishell override is None → keep the section's
    # ELFORM-derived formulation. Populated by _assign_hourglass_props.
    hourglass_prop_vals: Dict[int, Tuple[Optional[float], Optional[int]]] = \
        field(default_factory=dict)

    mat_elastic: Dict[int, MatElastic] = field(default_factory=dict)
    mat_plas_tab: Dict[int, MatPlasTAB] = field(default_factory=dict)
    mat_plas_kin: Dict[int, MatPlasKin] = field(default_factory=dict)
    # *MAT_JOHNSON_COOK (015) / *MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE
    # (099) → /MAT/LAW2 (PLAS_JOHNS), or /MAT/LAW4 + /EOS when an EOS is
    # attached (015 only; see writer _resolve_mat_johnson_cook)
    mat_johnson_cook: Dict[int, MatJohnsonCook] = field(default_factory=dict)
    # *MAT_ANISOTROPIC_VISCOPLASTIC (103) → /MAT/LAW128 (HILL_VISC_PLAST) +
    # a synthesized orthotropic property (see ortho_prop_ids)
    mat_aniso_visco: Dict[int, MatAnisoViscoplastic] = field(default_factory=dict)
    # Composite / orthotropic material families:
    #   MAT_002     → /MAT/LAW93  (ORTH_HILL, elastic-only: sigma_y = 1e30)
    #   MAT_054/055 → /MAT/LAW127 (ENHANCED_COMPOSITE) [+ /FAIL/GENE1 on TFAIL]
    #   MAT_037     → /MAT/LAW43  (HILL_TAB) [+ /FAIL/FLD on ICFLD]
    #   MAT_032     → a /MAT/PLAS_BRIT (LAW27) glass+polymer PAIR
    mat_orthotropic: Dict[int, MatOrthotropicElastic] = field(default_factory=dict)
    mat_enhanced_composite: Dict[int, MatEnhancedCompositeDamage] = \
        field(default_factory=dict)
    mat_transverse_aniso: Dict[int, MatTransverselyAnisotropic] = \
        field(default_factory=dict)
    mat_laminated_glass: Dict[int, MatLaminatedGlass] = field(default_factory=dict)
    mat_rigid: Dict[int, MatRigid] = field(default_factory=dict)
    mat_null: Dict[int, MatNull] = field(default_factory=dict)
    mat_power_law: Dict[int, MatPowerLaw] = field(default_factory=dict)
    mat_samp: Dict[int, MatSAMP] = field(default_factory=dict)          # *MAT_187 → /MAT/LAW76
    fail_gissmo: Dict[int, FailGissmo] = field(default_factory=dict)    # *MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2
    mat_add_erosion: Dict[int, MatAddErosion] = field(default_factory=dict)   # *MAT_ADD_EROSION → /FAIL
    # Foam / honeycomb material families
    mat_crushable_foam: Dict[int, MatCrushableFoam] = field(default_factory=dict)     # MAT_063 → /MAT/LAW50
    mat_low_density_foam: Dict[int, MatLowDensityFoam] = field(default_factory=dict)  # MAT_057 → /MAT/LAW38
    mat_fu_chang_foam: Dict[int, MatFuChangFoam] = field(default_factory=dict)        # MAT_083 → /MAT/LAW70
    mat_honeycomb: Dict[int, MatHoneycomb] = field(default_factory=dict)              # MAT_026 → /MAT/LAW28
    # Foam batch (dyna2rad targets):
    #   MAT_005 → /MAT/LAW21 (DPRAG) with the P(mu) abscissa transform
    #   MAT_073 → /MAT/LAW90 + /VISC/PRONY (explicit Gi/BETAi branch only)
    #   MAT_126 → /MAT/LAW50 on a synthesized /PROP/TYPE6 (SOL_ORTH)
    #   MAT_154 → /MAT/LAW115 (DESHFLECK, deterministic Istat=0 card)
    #   MAT_177 → /MAT/LAW62 (constants branch; LCID>0 fit branch warn-skips)
    mat_soil_and_foam: Dict[int, MatSoilAndFoam] = field(default_factory=dict)
    mat_low_density_viscous_foam: Dict[int, MatLowDensityViscousFoam] = \
        field(default_factory=dict)
    mat_modified_honeycomb: Dict[int, MatModifiedHoneycomb] = \
        field(default_factory=dict)
    mat_deshpande_fleck: Dict[int, MatDeshpandeFleckFoam] = \
        field(default_factory=dict)
    mat_hill_foam: Dict[int, MatHillFoam] = field(default_factory=dict)
    # Hyperelastic rubber batch (dyna2rad targets):
    #   MAT_007 → LAW42 fixed form; MAT_027 → LAW42 or LAW69; MAT_077_O → LAW42
    #   (embedded Prony) or LAW69; MAT_077_H → LAW95 (+/VISC/PRONY) or LAW69
    mat_blatz_ko: Dict[int, MatBlatzKo] = field(default_factory=dict)
    mat_mooney_rivlin: Dict[int, MatMooneyRivlin] = field(default_factory=dict)
    mat_ogden: Dict[int, MatOgdenRubber] = field(default_factory=dict)
    mat_hyper_rubber: Dict[int, MatHyperelasticRubber] = field(default_factory=dict)
    # Metal plasticity batch 2 (dyna2rad targets):
    #   MAT_012 → /MAT/LAW2 (PLAS_JOHNS), G/K derived to E/nu
    #   MAT_019 → /MAT/LAW121 (PLAS_RATE)
    #   MAT_120 → /MAT/LAW52 (GURSON) [+ /FAIL/JOHNSON for the _JC damage set]
    #   MAT_122 → /MAT/LAW43 (HILL_TAB) or /MAT/LAW32 (HILL, HR=2)
    #   MAT_124 → /MAT/LAW66 [+ /VISC/PRONY] [+ /FAIL/JOHNSON or /FAIL/TENSSTRAIN]
    # (MAT_081/082 and MAT_105 ride the MAT_024 container mat_plas_tab, which
    #  carries their extra damage fields — see MatPlasTAB.family.)
    mat_iso_elas_plas: Dict[int, MatIsoElasPlas] = field(default_factory=dict)
    mat_strain_rate_plas: Dict[int, MatStrainRatePlas] = field(default_factory=dict)
    mat_gurson: Dict[int, MatGurson] = field(default_factory=dict)
    mat_hill_3r: Dict[int, MatHill3R] = field(default_factory=dict)
    mat_plas_comp_tens: Dict[int, MatPlasCompTens] = field(default_factory=dict)
    # Viscoelastic batch (dyna2rad targets):
    #   MAT_006      → /MAT/LAW34 (BOLTZMAN), an exact 1:1 of G(t)
    #   MAT_061      → /MAT/LAW40 (KELVINMAX), G1 = G0-GI, BETA1 = DC
    #   MAT_076      → /MAT/LAW42 (OGDEN) carrier + /VISC/PRONY (Itab 0 or 1)
    #   MAT_181/183  → /MAT/LAW88 (TABULATED_HYPERELASTIC) [+ /VISC/PRONY]
    #   MAT_091/092  → /MAT/LAW42 (OGDEN), isotropic ground substance only
    mat_viscoelastic: Dict[int, MatViscoelastic] = field(default_factory=dict)
    mat_kelvin_maxwell: Dict[int, MatKelvinMaxwell] = field(default_factory=dict)
    mat_general_visco: Dict[int, MatGeneralViscoelastic] = field(default_factory=dict)
    mat_simplified_rubber: Dict[int, MatSimplifiedRubber] = field(default_factory=dict)
    mat_soft_tissue: Dict[int, MatSoftTissue] = field(default_factory=dict)
    # Adhesives / cohesive batch (dyna2rad targets):
    #   MAT_138 → /MAT/LAW117 (linear mixed-mode cohesive)
    #   MAT_169 → /MAT/LAW169 (ARUP_ADHESIVE — radioss2025 card, WARNING 100211
    #             under /BEGIN 2022, parsed correctly and non-fatal)
    #   MAT_240 → /MAT/LAW116 (rate-dependent elastoplastic cohesive;
    #             _THERMAL/_3MODES/_FUNCTIONS variants warn-skip)
    #   MAT_252 → /MAT/LAW120 (TAPO)
    #   MAT_ADD_DAMAGE_DIEM → /FAIL/INIEVO (rider keyed by parent MID, like
    #             fail_gissmo/mat_add_erosion above; coexists with both)
    mat_cohesive_mixed_mode: Dict[int, MatCohesiveMixedMode] = field(default_factory=dict)
    mat_arup_adhesive: Dict[int, MatArupAdhesive] = field(default_factory=dict)
    mat_cohesive_mm_epr: Dict[int, MatCohesiveMMEPR] = field(default_factory=dict)
    mat_toughened_adhesive: Dict[int, MatToughenedAdhesive] = field(default_factory=dict)
    fail_diem: Dict[int, FailDiem] = field(default_factory=dict)
    # *MAT_TABULATED_JOHNSON_COOK (224) → /MAT/LAW109 [+ /FAIL/TAB1]
    mat_tabulated_jc: Dict[int, MatTabulatedJC] = field(default_factory=dict)
    # Impact / blast materials:
    #   MAT_110 → /MAT/LAW79  (Johnson-Holmquist JH-2 ceramics)
    #   MAT_111 → /MAT/LAW126 (Johnson-Holmquist concrete)
    #   MAT_001 + _FLUID → /MAT/LAW6 (HYD_VISC) + /EOS/POLYNOMIAL. Its OWN
    #   container: the plain *MAT_ELASTIC path (mat_elastic → /MAT/ELAST,
    #   LAW1) must stay byte-identical, and only the fluid variant carries
    #   K/VC/CP.
    mat_jh_ceramics: Dict[int, MatJHCeramics] = field(default_factory=dict)
    mat_jh_concrete: Dict[int, MatJHConcrete] = field(default_factory=dict)
    mat_elastic_fluid: Dict[int, MatElasticFluid] = field(default_factory=dict)
    # *MAT_FABRIC / *MAT_034 → /MAT/LAW19 (+ /PROP/TYPE9) or /MAT/LAW58
    # (+ /PROP/TYPE16). Its OWN container: the law is chosen per material from
    # FORM plus the card-7 curves, and the choice decides the PROPERTY type as
    # well (see MatFabric and writer/fabric.py).
    mat_fabric: Dict[int, MatFabric] = field(default_factory=dict)
    # *INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] blocks (one entry per keyword
    # instance, in deck order) → /XREF per intersecting part
    foam_ref_geoms: List[FoamRefGeometry] = field(default_factory=list)
    # *AIRBAG_REFERENCE_GEOMETRY[_ID][_BIRTH][_RDT] blocks (one entry per
    # keyword instance, deck order) → /XREF per intersecting part. Kept apart
    # from foam_ref_geoms so the two keywords can be NAMED separately in the
    # warnings and so the _ID scaling / _BIRTH sensor stay on their own card;
    # both feed the same _resolve_xref_parts / _make_xref pair.
    airbag_ref_geoms: List[AirbagRefGeometry] = field(default_factory=list)
    # *AIRBAG_SHELL_REFERENCE_GEOMETRY[_ID][_RDT] blocks → /EREF/SHELL +
    # /EREF/SH3N per owning part.
    airbag_shell_ref_geoms: List[AirbagShellRefGeometry] = field(default_factory=list)
    # pid -> ([(quad eid, [n1..n4])], [(tri eid, [n1..n3])]) resolved by
    # writer/inistate.py::_resolve_airbag_eref at /EREF write time (it needs
    # state.shell_elem_ids / sh3n_elem_ids, which only exist once the
    # elements have been written), screened against the emitted mesh, the
    # node table and the /XREF parts (starter ERROR 1011 / 1098).
    airbag_eref_rows: Dict[int, Tuple[List[Tuple[int, List[int]]],
                                      List[Tuple[int, List[int]]]]] = field(
        default_factory=dict)
    # *AIRBAG_<MODEL> cards, deck order → /MONVOL/PRES|AIRBAG1|GAS|LFLUID
    # |COMMU1|FVMBAG2
    airbags: List[Airbag] = field(default_factory=list)
    # *AIRBAG_INTERACTION cards, deck order. NOT Airbags: each is a RELATION
    # that promotes both of its partner bags to /MONVOL/COMMU1 and writes one
    # row into each partner's Nbag block. Kept apart so a card naming a bag
    # this deck never defines can be reported by both ids rather than becoming
    # a monitored volume of its own.
    airbag_interactions: List[AirbagInteraction] = field(default_factory=list)
    # (monvol_id, title) of every /MONVOL actually written by
    # writer/monvol.py::_make_monvols — filled AT THE LINE that writes the
    # card, never derived from `airbags` (a model whose surface resolves to no
    # shell element is dropped). *DATABASE_ABSTAT's /TH/MONV lists exactly
    # these, the #106 dangling-id rule: a /TH group naming an entity the deck
    # does not define is refused outright, which is worse than losing the
    # channel. Same accounting pattern as blast_surf_ids / cluster_ids.
    monvol_ids: List[Tuple[int, str]] = field(default_factory=list)
    # Parts that actually receive a /XREF (writer prepass _resolve_xref_parts:
    # intersection with the reference tables, gated by the starter's solid
    # /XREF law whitelist and the 8/4-node solid restriction). Solid sections
    # serving these parts are emitted with Ismstr=10 (starter ERROR 2013
    # otherwise: /XREF rejects fully-integrated solids at small strain).
    xref_part_ids: set = field(default_factory=set)
    # Discrete-element (spring/damper) materials → /PROP/TYPE4 fields
    mat_spring_elastic: Dict[int, MatSpringElastic] = field(default_factory=dict)             # MAT_S01
    mat_spring_nonlinear: Dict[int, MatSpringNonlinearElastic] = field(default_factory=dict)  # MAT_S04
    mat_damper_viscous: Dict[int, MatDamperViscous] = field(default_factory=dict)             # MAT_D01
    mat_spring_elastoplastic: Dict[int, MatSpringElastoplastic] = field(default_factory=dict)         # MAT_S03
    mat_damper_nl_viscous: Dict[int, MatDamperNonlinearViscous] = field(default_factory=dict)         # MAT_S05
    mat_spring_general_nl: Dict[int, MatSpringGeneralNonlinear] = field(default_factory=dict)         # MAT_S06
    mat_spring_inelastic: Dict[int, MatSpringInelastic] = field(default_factory=dict)                 # MAT_S08
    # *SECTION_BEAM ELFORM=6 discrete-beam materials → 6-DOF /PROP/TYPE8 (skew
    # oriented, = /MAT/LAW108's card body) or /PROP/TYPE13 (node oriented, =
    # /MAT/LAW113's card body) /SPRING connectors
    mat_dbeam_linear: Dict[int, MatDiscreteBeamLinear] = field(default_factory=dict)                  # MAT_066
    mat_dbeam_nl_elastic: Dict[int, MatDiscreteBeamNonlinearElastic] = field(default_factory=dict)    # MAT_067
    mat_dbeam_nl_plastic: Dict[int, MatDiscreteBeamNonlinearPlastic] = field(default_factory=dict)    # MAT_068
    mat_cable_dbeam: Dict[int, MatCableDiscreteBeam] = field(default_factory=dict)                    # MAT_071
    mat_elastic_spring_dbeam: Dict[int, MatElasticSpringDiscreteBeam] = field(default_factory=dict)   # MAT_074
    mat_gnl_6dof: Dict[int, MatGeneralNonlinear6dof] = field(default_factory=dict)                    # MAT_119
    mat_gnl_1dof: Dict[int, MatGeneralNonlinear1dof] = field(default_factory=dict)                    # MAT_121
    mat_general_spring_dbeam: Dict[int, MatGeneralSpringDiscreteBeam] = field(default_factory=dict)   # MAT_196
    # mid → (keyword, RO) of a discrete-beam material that is RECOGNISED but
    # has no OpenRadioss spring counterpart (MAT_069/070/093/094/095/097/146).
    # Only those two fields are parsed: the keyword so the connector writer can
    # name what the deck loses instead of leaving the *PART with no material at
    # all, and RO so the inert connector still gets its real lumped mass.
    # dyna2rad drops all seven silently.
    mat_unsupported_dbeam: Dict[int, Tuple[str, float]] = field(default_factory=dict)
    # *MAT_SPOTWELD (MAT_100) beam parts → /PROP/TYPE13 /SPRING connectors
    mat_spotweld: Dict[int, MatSpotweld] = field(default_factory=dict)

    # ── Seatbelts / restraints ─────────────────────────────────
    # ONE dict for every *MAT_SEATBELT / *MAT_B01 spelling, `_2D` included:
    # which LAW the material becomes is decided by the PROPERTY its parts
    # carry, not by the keyword (dyna2rad convertmats.cxx:517-526 branches on
    # `propKeyWord.find("SEATBELT")` vs `..."SHELL"`). writer/seatbelts.py::
    # _seatbelt_mat_law is the ONE router, read by the material writer, the
    # property writer AND mesh._target_mat_law — the #100 one-map rule.
    mat_seatbelt: Dict[int, MatSeatbelt] = field(default_factory=dict)
    seatbelt_elems: List[SeatbeltElem] = field(default_factory=list)
    seatbelt_sliprings: List[SeatbeltSlipring] = field(default_factory=list)
    seatbelt_retractors: List[SeatbeltRetractor] = field(default_factory=list)
    seatbelt_pretensioners: List[SeatbeltPretensioner] = \
        field(default_factory=list)
    # SBSID → the card. A DICT, not a list, because every consumer
    # (retractor SID1..4, pretensioner SBSID1..4) reaches it by id, and a
    # duplicate SBSID is a deck error the last card wins in LS-DYNA too.
    seatbelt_sensors: Dict[int, SeatbeltSensor] = field(default_factory=dict)
    seatbelt_accels: List[SeatbeltAccelerometer] = field(default_factory=list)
    # part_id → synthesized /PROP/TYPE9 (SH_ORTH) id for a 2D belt part. Same
    # split mechanism as fabric_prop_ids: /MAT/LAW119 declares SHELL_ORTHOTROPIC
    # (hm_read_mat119.F:218), so the part cannot stay on the isotropic
    # /PROP/SHELL its *SECTION_SHELL would give it — starter ERROR 3047.
    seatbelt_prop_ids: Dict[int, int] = field(default_factory=dict)
    # Emitted ids, recorded AT THE LINE that writes each card (the #106 rule) —
    # *DATABASE_SBTOUT's /TH/SLIPRING and /TH/RETRACTOR list exactly these, and
    # a /TH naming an entity the deck does not define is starter ERROR 69.
    slipring_ids: List[Tuple[int, str]] = field(default_factory=list)
    retractor_ids: List[Tuple[int, str]] = field(default_factory=list)
    # /SENSOR and /ACCEL ids already SPOKEN FOR: every id minted by
    # next_sensor_id()/next_accel_id(), plus every USER id the writer emits
    # verbatim (writer/seatbelts.py adds each SBSID and SBACID at the line that
    # writes its card). Its job is that two callers in one build cannot be
    # handed the same id. The user half is belt AND braces, not the only
    # guard: next_sensor_id() also dodges state.seatbelt_sensors (the SBSID
    # dict) and next_accel_id() the seatbelt_accels SBACIDs, both filled at
    # parse time and so populated before any writer runs. The seatbelt writer
    # screens a Sens_ID against _SensorPool's own map, not against this set.
    sensor_ids: Set[int] = field(default_factory=set)
    accel_ids: Set[int] = field(default_factory=set)
    # The /ACCELs a *ELEMENT_SEATBELT_ACCELEROMETER asked for, i.e. the ones
    # /TH/ACCEL should record. A SUBSET of accel_ids: the accelerometer a
    # SBSTYP=1 *ELEMENT_SEATBELT_SENSOR needs exists only to feed its
    # /SENSOR/ACCE (sensor_acce.cfg's accel_ID is mandatory) and recording it
    # would add a channel the deck never requested, on a node it already
    # records through the sensor's own accelerometer.
    th_accel_ids: List[Tuple[int, str]] = field(default_factory=list)
    # *CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT with
    # failure forces → stiff /PROP/TYPE13 /SPRING (no-failure ones become
    # 2-node CNRBs at parse time and go through state.cnrbs instead)
    constrained_spotwelds: List[ConstrainedSpotweld] = field(default_factory=list)
    # *DEFINE_HEX_SPOTWELD_ASSEMBLY[_N] → /CLUSTER/BRICK + its /GRBRIC/BRIC
    hex_spotweld_assemblies: List[HexSpotweldAssembly] = field(default_factory=list)
    # (cluster_id, title) of each emitted /CLUSTER/BRICK — set by the writer's
    # _make_hex_spotweld_clusters, consumed by the *DATABASE_SWFORC accounting
    # (same pattern as sect_ids / blast_surf_ids)
    cluster_ids: List[Tuple[int, str]] = field(default_factory=list)
    # sprg_IDs actually written as /SPRING by _make_spotweld_beam_connectors.
    # *DATABASE_SWFORC must list only these: the connector writer skips a whole
    # MAT_100 part when the welds are zero-length, carry no *SECTION_BEAM, or
    # size to no area, and a /TH/SPRING naming an element that was never
    # emitted is starter ERROR 69 (hm_read_thgrne.F:189, MSGTYPE=MSGERROR) —
    # the deck is refused, not degraded. Same accounting pattern as cluster_ids.
    spotweld_spring_eids: Set[int] = field(default_factory=set)
    # The same accounting, for the two connector families LS-DYNA reports in its
    # OWN two discrete-element databases (Vol I R16 p.1944-1945):
    #   *DATABASE_DEFORC  -> "*ELEMENT_DISCRETE data"          -> discrete_spring_eids
    #   *DATABASE_DISBOUT -> "discrete beam element, type 6"   -> dbeam_spring_eids
    # Both writers `continue` past elements they cannot emit (a grounded
    # discrete element whose anchor node has no coordinates; a discrete-beam
    # part with no usable beams), so these are filled AT THE LINE THAT WRITES
    # the /SPRING, never from the parsed element list — a /TH/SPRING naming an
    # id the deck does not define is starter ERROR 69 and the whole run is
    # refused. Synthesized springs (PLOTEL, --ground-springs,
    # *CONSTRAINED_SPOTWELD ties, joints) are deliberately NOT in here: their
    # ids are invented by the converter and match no LS-DYNA deforc/disbout row.
    discrete_spring_eids: Set[int] = field(default_factory=set)
    dbeam_spring_eids: Set[int] = field(default_factory=set)
    # EVERY /SPRING id this conversion wrote, from ALL SEVEN producers — the
    # three above plus *ELEMENT_PLOTEL, --ground-springs, the
    # *CONSTRAINED_SPOTWELD ties and the *CONSTRAINED_JOINT_* springs, whose
    # ids are minted by next_id() during section emission and were recorded
    # NOWHERE before this batch. The three sets above stay separate because
    # each answers ONE LS-DYNA database card and must not report the others'
    # elements; this one answers "does a /SPRING with this id exist?", which is
    # the question *DATABASE_HISTORY_DISCRETE (and the /BEAM->/SPRING fallback
    # of *DATABASE_HISTORY_BEAM) has to ask before naming an id — a /TH/SPRING
    # on an id the deck never defines is starter ERROR 69, not a lost channel.
    # Filled AT the line that writes each /SPRING row.
    spring_elem_ids: Set[int] = field(default_factory=set)
    # The same accounting for /BEAM. NOT derivable from state.beam_elems: a
    # beam on a *MAT_SPOTWELD part or on a *SECTION_BEAM ELFORM=6 part is
    # emitted as a /SPRING instead, and a beam whose PID has no *PART record is
    # never emitted at all (writer/mesh.py skips the whole part).
    beam_elem_ids: Set[int] = field(default_factory=set)
    # The same accounting for the two shell families and for the solids, and
    # for the same reason: an *ELEMENT_SHELL / *ELEMENT_SOLID whose PID has no
    # *PART record is parsed into state.shell_elems / solid_elems and warned
    # about ("MESH LOSS"), but writer/mesh.py never visits that part, so no row
    # is written. *DATABASE_HISTORY_SHELL / _SOLID / _TSHELL (and their _SET
    # spellings) screen against these before naming an id — a /TH/SHEL or
    # /TH/BRIC on an element the deck does not define is starter ERROR 69 and
    # the whole run is refused. The SHEL/SH3N split is the writer's own: a
    # 3-distinct-corner shell goes to sh3n_elem_ids, so /TH/SHEL and /TH/SH3N
    # get exactly the ids their element blocks hold. /TETRA4 and /TETRA10 join
    # solid_elem_ids — they are /TH/BRIC's own id pool (all three read IXS).
    # Filled AT the six lines in _make_parts_and_elements that write a row.
    shell_elem_ids: Set[int] = field(default_factory=set)
    sh3n_elem_ids: Set[int] = field(default_factory=set)
    solid_elem_ids: Set[int] = field(default_factory=set)
    # Every /RBODY id this conversion wrote. THREE Radioss-side emission sites
    # (writer/rbody.py:645 *MAT_RIGID parts — which also covers *PART_INERTIA,
    # element-free CoG masters and *CONSTRAINED_RIGID_BODIES merge masters;
    # :1004 *CONSTRAINED_NODAL_RIGID_BODY; :1086 the implicit no-rigid-body
    # probe), i.e. four LS-DYNA sources funnelling through three writers.
    # rbody_info cannot stand in for it:
    # the probe body is not in rbody_info at all, a CNRB/part id collision
    # drops one record, and a merge aliases several dict keys onto one master.
    # *DATABASE_RBDOUT lists exactly this set.
    rbody_ids: Set[int] = field(default_factory=set)
    # Nodes an /IMPDISP, /IMPVEL or /IMPACC was actually written for, and
    # whether any of those motions drives a ROTATIONAL dof. This is the
    # *DATABASE_BNDOUT scope (dyna2rad.cxx:456 collects the node groups of
    # exactly those three cards). Recorded by the two imposed-motion writers at
    # the point of emission, so a row that was warned-and-dropped (unsupported
    # DOF, missing /RBODY, empty box intersection) contributes no node.
    imp_motion_nodes: Set[int] = field(default_factory=set)
    imp_motion_rot: bool = False
    # *ELEMENT_DISCRETE eids carrying PF=1, the deforc PRINT flag: "EQ.1: forces
    # are not printed DEFORC file" (Vol I R16 p.19-32), and p.1944 names it as
    # one of the two ways a deck narrows the deforc selection. It is an OUTPUT
    # flag only — the /SPRING is emitted either way — so it subtracts from the
    # *DATABASE_DEFORC /TH/SPRING group and nothing else.
    deforc_suppressed_eids: Set[int] = field(default_factory=set)
    # *CONSTRAINED_JOINT_<KIND> → per joint one /PART + /PROP/TYPE45 (KJOINT2)
    # + one 2..4-node /SPRING, plus a /SKEW/FIX carrying the joint frame
    constrained_joints: List[ConstrainedJoint] = field(default_factory=list)
    # *CONSTRAINED_JOINT_STIFFNESS_GENERALIZED / _TRANSLATIONAL → the DOF
    # stiffness/damping/friction/stop blocks of the matched joint's /PROP/TYPE45
    joint_stiffnesses: List[JointStiffness] = field(default_factory=list)
    # Joint index (position in constrained_joints) → the /SKEW id carrying its
    # local frame. Filled by the writer prepass _resolve_joints so the ids are
    # reserved in the shared /SKEW+/FRAME namespace before /FRAME allocation.
    joint_skew_ids: Dict[int, int] = field(default_factory=dict)
    # Every node a converted joint /SPRING touches — the implicit free-node
    # guard must see these (they carry joint stiffness, so /BCS-fixing them
    # would weld the joint solid).
    joint_spring_nodes: set = field(default_factory=set)
    # Ground nodes synthesized by the connector writer (registered in
    # state.nodes for id-collision safety; excluded from the implicit
    # free-node guard because they are already fully fixed by /BCS)
    connector_ground_nodes: set = field(default_factory=set)
    constrained_node_sets: List[ConstrainedNodeSet] = field(default_factory=list)  # *CONSTRAINED_NODE_SET → /RLINK
    # Curve ids a law consumes through a *table* slot rather than a function
    # slot — emitted as a 1-D /TABLE/1 (with its mandatory "#dimension" card)
    # instead of a /FUNCT, so _make_functions can route them. Populated by the
    # LAW76 (*MAT_187) yield tables and the LAW52 (*MAT_120) Tab_ID.
    table_1d_ids: set = field(default_factory=set)
    # High-explosive / EOS (coupled ALE / JWL detonation):
    #   *MAT_HIGH_EXPLOSIVE_BURN + *EOS_JWL (shared id) → /MAT/LAW5
    #   *MAT_NULL carrier + *EOS_* (shared id)          → /MAT/LAW6 + /EOS/*
    mat_high_explosive: Dict[int, MatHighExplosiveBurn] = field(default_factory=dict)
    eos_jwl: Dict[int, EosJwl] = field(default_factory=dict)      # eosid → JWL params
    eos_cards: Dict[int, EosCard] = field(default_factory=dict)   # eosid → /EOS/<kind>

    curves: Dict[int, Curve] = field(default_factory=dict)
    # *DEFINE_CURVE lcids in deck parse order — used to resolve the legacy
    # *DEFINE_TABLE form (curves follow the table positionally).
    curve_order: List[int] = field(default_factory=list)
    # *DEFINE_TABLE[_2D] → /TABLE/1 (Ndim=2), keyed by table id (shares the
    # LS-DYNA load-curve id space with state.curves).
    define_tables: Dict[int, DefineTable] = field(default_factory=dict)
    # *DEFINE_TABLE_3D → /TABLE/1 (Ndim=3), same shared id space. Validated
    # (+ marked resolved) by _resolve_define_tables_3d; *MAT_224 LCK1 slices
    # the nesting instead of referencing the flat 3-D card.
    define_tables_3d: Dict[int, DefineTable3D] = field(default_factory=dict)
    # Synthesized multi-dimensional /TABLE/1 cards (Ndim 2/3) with explicit
    # (fct, coords, Scale_y) rows — built by writer prepasses (the MAT_224
    # LAW109/TAB1 wiring, the *DEFINE_TABLE_3D flat emission), emitted by
    # _make_functions. Keyed by the emitted table id (a *DEFINE_TABLE_3D
    # keeps its deck id; fresh ids come from next_curve_id, checked free of
    # every table namespace too).
    auto_tables: Dict[int, AutoTable] = field(default_factory=dict)
    coord_sys: Dict[int, CoordSys] = field(default_factory=dict)
    # *DEFINE_COORDINATE_NODES → /SKEW (moving or fixed)
    coord_nodes: Dict[int, CoordNodes] = field(default_factory=dict)
    # *DEFINE_COORDINATE_VECTOR → /SKEW/FIX (cid → record; skew id = cid)
    coord_vectors: Dict[int, CoordVector] = field(default_factory=dict)
    # *DEFINE_VECTOR / *DEFINE_VECTOR_NODES → /SKEW (vid → record). The writer
    # prepass assigns each a /SKEW id (recorded in vector_skew_ids) that avoids
    # every converted-coordinate id (shared /SKEW+/FRAME starter namespace).
    define_vectors: Dict[int, DefineVector] = field(default_factory=dict)
    # *DEFINE_SD_ORIENTATION → /SKEW (vid → record); the IOP 0/2 skews are the
    # orientation frame for a *ELEMENT_DISCRETE VID, recorded in sdorient_skew_ids
    sd_orientations: Dict[int, SdOrientation] = field(default_factory=dict)
    # LS-DYNA vector VID → converted /SKEW id (define_vectors / sd_orientations)
    vector_skew_ids: Dict[int, int] = field(default_factory=dict)
    sdorient_skew_ids: Dict[int, int] = field(default_factory=dict)
    # /SKEW ids minted by the WRITERS for synthesized orthotropy frames (the
    # LAW128 solid skews in writer/mesh.py, the AOPT=2 composite skews in
    # writer/composites.py). Both emitters run in the same build_starter pass
    # and both allocate by bumping off all_skew_ids(), so the reservation has
    # to be shared or the second one can land on an id the first already took
    # (starter ERROR 79 DUPLICATE ID).
    synth_skew_ids: Set[int] = field(default_factory=set)
    # *DEFINE_BOX[_LOCAL] → numeric node-membership scoping (box_id → record)
    boxes: Dict[int, DefineBox] = field(default_factory=dict)

    # ── Sets / groups ──────────────────────────────────────────
    node_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)   # nsid → (title, [nids])
    part_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)   # psid → (title, [pids])
    # *SET_PART_ADD: psid → (title, [child part-set ids]) — one level of
    # part-set nesting (dyna2rad CC:692-727: an "ADD" set's ids are part-SET
    # ids). Expanded ONCE post-parse by _flatten_part_set_adds (writer/mesh.py)
    # into a plain part_sets entry, so every part-set consumer resolves it.
    part_set_adds: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)
    part_set_adds_flattened: bool = False    # _flatten_part_set_adds ran
    # *SET_PART[_LIST|_ADD] header attributes DA1..DA4. For *CONTACT_INTERIOR
    # these are per-set defaults: PSF (penalty scale), Fa (activation factor),
    # ED (contact stiffness modulus), TYPE (1 uniform compression / 2 combined
    # compression+shear) — none has an Icontrol counterpart, warned when set.
    part_set_attrs: Dict[int, Tuple[float, float, float, float]] = \
        field(default_factory=dict)
    # *SET_SEGMENT → segment sets (used by /LOAD/PBLAST as /SURF/SEG)
    segment_sets: Dict[int, SegmentSet] = field(default_factory=dict)           # sid → SegmentSet
    # *SET_SHELL/_SOLID/_BEAM element sets: sid → (title, [eids]).
    # Referenced by *DATABASE_CROSS_SECTION_SET (→ the /SECT element groups)
    # and by the *DATABASE_HISTORY_<FAMILY>_SET expansion.
    shell_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)
    solid_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)
    beam_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)
    # *SET_DISCRETE[_LIST]: the *ELEMENT_DISCRETE twin of the three above. Its
    # only consumer today is *DATABASE_HISTORY_DISCRETE_SET, whose cfg accepts
    # a SET_DISCRETE_IDPOOL or a SET_COMPONENT_IDPOOL id
    # (database_history_discrete_set.cfg:25).
    discrete_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)

    # ── Boundary conditions ────────────────────────────────────
    bcs_spcs: List[BcsSpc] = field(default_factory=list)
    # /BCS written by the CNRB _SPC path (see CnrbSpcBc). Rebuilt from scratch
    # on every _make_cnrb_rbodies call, so re-running the writer is idempotent.
    cnrb_spc_bcs: List[CnrbSpcBc] = field(default_factory=list)
    prescribed_motions: List[PrescribedMotionRigid] = field(default_factory=list)
    prescribed_motion_sets: List[PrescribedMotionSet] = field(default_factory=list)
    # *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL: pid → the three synthesized nodes
    # that carry the body's co-rotating /SKEW/MOV triad. Filled by
    # _synthesize_local_motion_frames and folded into that body's /RBODY
    # secondary-node group by _make_rbodies / _make_cnrb_rbodies, so the triad
    # rotates rigidly with the body. Kept OUT of extra_rigid_nodes on purpose:
    # that field is *CONSTRAINED_EXTRA_NODES input and its "not a *MAT_RIGID
    # part" warning would misreport these.
    local_frame_nodes: Dict[int, List[int]] = field(default_factory=dict)

    #: Every node id the SOURCE deck defined, snapshotted by build_starter as its
    #: very first act — i.e. before any prepass synthesizes a node. The writer
    #: adds plenty: /RBODY CoG masters, the /SKEW/MOV third nodes, the
    #: *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL triads, rigid-wall carriers,
    #: *ELEMENT_BEAM_ORIENTATION third nodes. A *DEFINE_BOX names a region of
    #: the USER's model, so anything resolving box membership by scanning
    #: state.nodes has to intersect with this set or it drives k2rad's own
    #: artefacts (see _box_node_ids). Empty means "not snapshotted yet", in which
    #: case consumers fall back to the whole node table.
    source_node_ids: Set[int] = field(default_factory=set)

    # ── Constraints ────────────────────────────────────────────
    # *CONSTRAINED_NODAL_RIGID_BODY[_SPC] → /RBODY (+ /BCS)
    cnrbs: List[ConstrainedNodalRigidBody] = field(default_factory=list)

    # *CONSTRAINED_EXTRA_NODES_NODE/_SET: pid → extra node ids merged into
    # that rigid part's /RBODY secondary-node group
    extra_rigid_nodes: Dict[int, List[int]] = field(default_factory=dict)

    # *CONSTRAINED_RIGID_BODIES: (master_pid, slave_pid) pairs — the slave
    # rigid part's nodes are folded into the master's single /RBODY
    rigid_body_merges: List[Tuple[int, int]] = field(default_factory=list)

    # *PART_INERTIA cards 3-6, keyed by PID → the /RBODY Mass/Jxx..Jxz override,
    # the main node's position and the card-5 /INIVEL. Only rigid parts consume
    # it ("This applies to rigid bodies (see *MAT_RIGID) only", Vol I R17
    # p.37-2); a non-rigid part's entry is warned and dropped by the writer.
    part_inertias: Dict[int, RigidInertia] = field(default_factory=dict)

    # *PART_CONTACT card 8, keyed by PID → the /PART card's Thick column (OPTT);
    # every other field is warn-dropped. See PartContact.
    part_contacts: Dict[int, PartContact] = field(default_factory=dict)

    # *CONSTRAINED_INTERPOLATION[_LOCAL] → /RBE3 + one /GRNOD/NODE per weight/DOF
    # group. Raw ids only; the writer resolves DNID/INID against state.nodes and
    # state.node_sets and CIDI against the converted /SKEW ids.
    interpolations: List[ConstrainedInterpolation] = field(default_factory=list)

    #: Every node an emitted /RBE3 references (dependent + independent), filled by
    #: _make_rbe3. The implicit free-node guard must treat them as ATTACHED: the
    #: dependent node's DOFs are eliminated (or penalised) by the RBE3, so they are
    #: not zero rows, and a /BCS 111 111 on it would fight the constraint outright.
    rbe3_nodes: Set[int] = field(default_factory=set)

    # *RIGIDWALL_PLANAR → /RWALL/PLANE
    rigid_walls: List[RigidWallPlanar] = field(default_factory=list)
    # *RIGIDWALL_GEOMETRIC_* → /RWALL/CYL, /SPHER, /PLANE, /PARAL (x6 for a prism)
    rigid_walls_geometric: List[RigidWallGeometric] = field(default_factory=list)

    # ── Loads ──────────────────────────────────────────────────
    load_rigid_bodies: List[LoadRigidBody] = field(default_factory=list)
    # *LOAD_NODE_POINT / *LOAD_NODE_SET → /CLOAD
    load_nodes: List[LoadNode] = field(default_factory=list)
    inivel_nodes: List[InitialVelocityNode] = field(default_factory=list)
    inivel_rbodies: List[InitialVelocityRigidBody] = field(default_factory=list)
    # *INITIAL_VELOCITY (base set form) → /INIVEL/TRA (+ /INIVEL/ROT)
    inivel_general: List[InitialVelocity] = field(default_factory=list)
    # *INITIAL_VELOCITY_GENERATION → /INIVEL/AXIS + /FRAME/FIX
    inivel_generations: List[InitialVelocityGeneration] = field(default_factory=list)
    pressure_loads: List[PressureLoad] = field(default_factory=list)
    # *LOAD_SEGMENT_SET rows → /PLOAD (segments resolved from segment_sets
    # at write time so the *SET_SEGMENT may be defined later in the deck)
    segment_set_pressure_loads: List[SegmentSetPressureLoad] = field(default_factory=list)
    # *LOAD_SHELL_ELEMENT / _SET rows → /SURF/SEG (shell connectivity) + /PLOAD
    shell_pressure_loads: List[ShellPressureLoad] = field(default_factory=list)
    # *LOAD_GRAVITY_PART rows → /GRAV (non-modal decks only)
    gravity_loads: List[GravityLoadPart] = field(default_factory=list)
    # *LOAD_BODY_{X,Y,Z} whole-model base-acceleration rows → /GRAV
    body_loads: List[LoadBody] = field(default_factory=list)
    # *LOAD_BODY_VECTOR rows → /GRAV + a companion /SKEW/FIX (local X' = +V)
    body_load_vectors: List[LoadBodyVector] = field(default_factory=list)
    # *LOAD_BODY_RX/_RY/_RZ rows → /LOAD/CENTRI (+ /FRAME/FIX for the axis)
    body_load_rots: List[LoadBodyRot] = field(default_factory=list)
    # *LOAD_BODY_PARTS PSID — restricts EVERY *LOAD_BODY_* row to that part set
    # (Manual Vol I R16 p.33-25: the data applies to the complete problem
    # "unless a part subset is specified via the *LOAD_BODY_PARTS keyword", and
    # "Only one *LOAD_BODY_PARTS card is permitted per deck"). 0 = whole model.
    body_load_psid: int = 0
    # *LOAD_BLAST_ENHANCED sources keyed by bid, and the
    # *LOAD_BLAST_SEGMENT_SET rows that apply them → /LOAD/PBLAST + /SURF/SEG
    blast_sources: Dict[int, LoadBlastEnhanced] = field(default_factory=dict)
    blast_segment_loads: List[LoadBlastSegmentSet] = field(default_factory=list)
    # (surf_id, title) of each blast-loaded /SURF/SEG the writer emitted —
    # set by _make_blast_loads, consumed by the *DATABASE_BINARY_BLSTFOR
    # /TH/SURF output (same pattern as th_sub_ids for /TH/INTER)
    blast_surf_ids: List[Tuple[int, str]] = field(default_factory=list)
    # *INITIAL_DETONATION → /DFS/DETPOINT (JWL burn origin for LAW5 explosives)
    detonations: List[InitialDetonation] = field(default_factory=list)
    # ── Coupled ALE / FSI ──────────────────────────────────────
    # *ALE_MULTI-MATERIAL_GROUP → /MAT/LAW51 (MULTIMAT) submaterial order
    ale_mmgs: List[AleMultiMaterialGroup] = field(default_factory=list)
    # *CONSTRAINED_LAGRANGE_IN_SOLID → /INTER/TYPE18 (fluid-structure coupling)
    lagrange_in_solid: List[ConstrainedLagrangeInSolid] = field(default_factory=list)
    # *INITIAL_VOLUME_FRACTION[_GEOMETRY] → /INIVOL (initial ALE fill)
    volume_fractions: List[InitialVolumeFraction] = field(default_factory=list)
    # *BOUNDARY_NON_REFLECTING → /EBCS/NRF (silent far-field)
    non_reflecting: List[BoundaryNonReflecting] = field(default_factory=list)
    # *CONTROL_ALE → /ALE advection hints (mostly informational)
    control_ale: Optional[ControlAle] = None
    # Unit system (mass, length, time) implied by a *LOAD_BLAST_ENHANCED UNIT
    # flag. The TM5-1300 empirical blast formulas are unit-dependent, so the
    # /BEGIN unit labels must match the deck's real units for /LOAD/PBLAST to
    # convert correctly; convert() applies this when the caller left units at
    # the default. None = no blast load / unknown flag.
    blast_unit_system: Optional[Tuple[str, str, str]] = None
    # *ELEMENT_MASS additions: node_ID → total added translational mass
    # (in input unit, typically ton). Used to set /RBODY Mass field
    # for rigid-body master nodes (provides M contribution to K_eff in
    # implicit analyses), or to emit /ADMAS for ordinary nodes.
    added_node_masses: Dict[int, float] = field(default_factory=dict)
    # *ELEMENT_MASS_PART additions: part_ID → (addmass, finmass).
    # ADDMASS  = extra mass distributed across the part's nodes (or set
    #            directly on the rigid-body master if part is rigid).
    # FINMASS  = target total mass; if nonzero, ADDMASS = FINMASS − existing.
    # Per LS-DYNA R16 Manual p.19-67: exactly one of ADDMASS/FINMASS is
    # nonzero. For rigid-body parts, the resulting mass is applied to the
    # /RBODY Mass field (no need to distribute over slave nodes).
    element_mass_parts: Dict[int, Tuple[float, float]] = field(default_factory=dict)
    # Populated by build_starter after _make_rbodies: pid → grnod_id of all rbody nodes
    rbody_grnods: Dict[int, int] = field(default_factory=dict)
    # pid → grnod_id containing ONLY the independent node (used by /CLOAD)
    rbody_ind_grnods: Dict[int, int] = field(default_factory=dict)

    # ── Contacts ───────────────────────────────────────────────
    contacts_single: List[ContactAutoSingle] = field(default_factory=list)
    contacts_surf2surf: List[ContactAutoSurf2Surf] = field(default_factory=list)
    # *CONTACT_AUTOMATIC_GENERAL with a SOFT sentinel → /INTER/TYPE7|11|19
    contacts_general: List[ContactAutoGeneral] = field(default_factory=list)
    # *CONTACT_TIED_* → /INTER/TYPE2 (kinematic) or /INTER/TYPE10 (penalty tie)
    contacts_tied: List[ContactTied] = field(default_factory=list)
    # *CONTACT_SPOTWELD[...] → /INTER/TYPE2 Spotflag=28, Idel2=1
    contacts_spotweld: List[ContactSpotweld] = field(default_factory=list)
    # *CONTACT_ERODING_* and *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE →
    # /INTER/TYPE25 (self / surface-to-surface / one-way node-to-surface)
    contacts_type25: List[ContactType25] = field(default_factory=list)
    # *DEFINE_FRICTION tables → /FRICTION, keyed by their (preserved) id and
    # kept in deck order so "exactly one table in the model" is decidable.
    define_frictions: Dict[int, DefineFriction] = field(default_factory=dict)
    # Interface ids the writers REFUSED to emit (filled by _drop_interface).
    # /TH/INTER is assembled from the parsed contact records, so it has to
    # subtract these or the starter answers WARNING 257 NONEXISTENT INTER.
    dropped_inter_ids: Set[int] = field(default_factory=set)
    force_transducers: List[ContactForceTransducer] = field(default_factory=list)
    # (sub_id, title) for each emitted /INTER/SUB → used to build /TH/SUBS
    th_sub_ids: List[Tuple[int, str]] = field(default_factory=list)
    # *CONTACT_INTERIOR part-set ids, in deck order (the keyword is a free
    # PSID list and may appear more than once). The natural Radioss target is
    # Icontrol=1 on the parts' solid /PROP — a radioss2025-only input column
    # that a /BEGIN 2022 deck cannot carry (measured: the starter reads the
    # trailing prop card as "Ndir sphpartID" only, echoes ICONTROL 0 and
    # raises WARNING 100213) — so the writer prepass resolves the sets and
    # warns instead of emitting; see writer/mesh.py::_resolve_contact_interior.
    contact_interior_psids: List[int] = field(default_factory=list)

    # ── Control ────────────────────────────────────────────────
    ctrl_accuracy: Optional[ControlAccuracy] = None
    ctrl_contact: Optional[ControlContact] = None
    ctrl_cpu: Optional[ControlCpu] = None
    ctrl_energy: Optional[ControlEnergy] = None
    ctrl_hourglass: Optional[ControlHourglass] = None
    # *CONTROL_PARALLEL → engine /PARITH. A LIST, not a single record: LS-DYNA
    # allows several cards and dyna2rad ORs their CONST flags
    # (convertcards.cxx:978-986), so one CONST=1 anywhere turns parallel
    # arithmetic on and a later CONST=2 cannot turn it back off.
    ctrl_parallels: List[ControlParallel] = field(default_factory=list)
    ctrl_implicit_auto: Optional[ControlImplicitAuto] = None
    ctrl_implicit_dyn: Optional[ControlImplicitDynamics] = None
    ctrl_output: Optional[ControlOutput] = None
    ctrl_shell: Optional[ControlShell] = None
    ctrl_solid: Optional[ControlSolid] = None
    ctrl_implicit_gen: Optional[ControlImplicitGeneral] = None
    ctrl_implicit_sol: Optional[ControlImplicitSolution] = None
    ctrl_implicit_eig: Optional[ControlImplicitEigenvalue] = None
    ctrl_termination: Optional[ControlTermination] = None
    ctrl_timestep: Optional[ControlTimestep] = None
    damping_global: Optional[DampingGlobal] = None
    damping_part_stiffness: List[DampingPartStiffness] = field(default_factory=list)
    damping_part_mass: List[DampingPartMass] = field(default_factory=list)
    damping_frequency_range: List[DampingFrequencyRange] = field(default_factory=list)
    damping_relative: List[DampingRelative] = field(default_factory=list)

    # ── Database / output ──────────────────────────────────────
    db_d3plot: Optional[DbD3Plot] = None
    db_elout_dt: float = 0.0
    db_glstat_dt: float = 0.0
    db_histories: List[DbHistory] = field(default_factory=list)
    db_abstat_dt: float = 0.0
    db_d3thdt_dt: float = 0.0
    db_intfor_dt: float = 0.0
    db_deforc_dt: float = 0.0
    db_disbout_dt: float = 0.0
    db_jntforc_dt: float = 0.0
    db_matsum_dt: float = 0.0
    db_nodout_dt: float = 0.0
    db_rcforc_dt: float = 0.0
    db_rwforc_dt: float = 0.0
    db_secforc_dt: float = 0.0
    db_sleout_dt: float = 0.0
    # *DATABASE_SPHOUT — the SPH particle database. It requests no channel of
    # its own in Radioss (the /TH/SPHCEL groups come from
    # *DATABASE_HISTORY_SPH), but its dt DOES join the /TFILE minimum scan, the
    # same treatment dyna2rad gives it (convertcards.cxx:99, inside dbCardList).
    db_sphout_dt: float = 0.0
    # *DATABASE_SWFORC → /TH/SPRING over the *MAT_SPOTWELD (MAT_100) /PROP/TYPE13
    # weld connectors, /TH/BRIC over MAT_100 solid welds, and /TH/CLUSTER over
    # the *DEFINE_HEX_SPOTWELD_ASSEMBLY clusters
    db_swforc_dt: float = 0.0
    # *DATABASE_SBTOUT → /TH/SLIPRING + /TH/RETRACTOR over the emitted seatbelt
    # devices. LS-DYNA writes ONE sbtout file for the whole restraint system;
    # Radioss splits it across two group types, so both are emitted (dyna2rad
    # emits NEITHER — its *DATABASE_SBTOUT is a bare dbCardList member whose
    # only effect is its DT, convertcards.cxx:94, and `grep -rn "TH/RETRACTOR"`
    # over the whole reader tree returns zero hits).
    db_sbtout_dt: float = 0.0
    db_sbtout_seen: bool = False
    # *DATABASE_SPCFORC → /TH/NODE REAC* on the /BCS nodes + /ANIM/VECT/FREAC
    db_spcforc_dt: float = 0.0
    # *DATABASE_NCFORC → /TH/INTER on every converted contact interface
    db_ncforc_dt: float = 0.0
    # *DATABASE_BINARY_BLSTFOR → /TH/SURF (P,A) on the blast-loaded
    # surfaces + /ANIM/NODA/PEXT + /ANIM/VECT/FEXT
    db_blstfor_dt: float = 0.0
    # *DATABASE_BNDOUT → /TH/NODE REAC* over the nodes an /IMPDISP, /IMPVEL or
    # /IMPACC actually drives (dyna2rad.cxx:456 names exactly those three).
    db_bndout_dt: float = 0.0
    # *DATABASE_RBDOUT → /TH/RBODY over EVERY emitted /RBODY (state.rbody_ids).
    db_rbdout_dt: float = 0.0
    # PRESENCE of the two cards above, separate from their interval. The
    # reference trigger for both is presence alone (convertrigids.cxx:767
    # selDatabaseRbdout.Count(), dyna2rad.cxx:461 selDbCard.Count()); k2rad also
    # needs a positive dt, because DT=0 is "no output is printed" (Vol I R16
    # p. 16-7) and a BLANK dt defers to an LCDT curve that /TFILE cannot
    # express. Distinguishing "card absent" from "card present, no usable
    # interval" is what lets the writer warn about the second WITHOUT warning
    # about the first.
    db_rbdout_seen: bool = False
    db_bndout_seen: bool = False
    # *DATABASE_ABSTAT present (whatever its DT) — so a card with a
    # blank or zero DT can be reported as "asked for, not emitted"
    # instead of vanishing. Same pattern as the two above.
    db_abstat_seen: bool = False
    # *DATABASE_NODFOR — the ASCII nodal-force-group database. It selects no
    # channel of its own; it states the OUTPUT INTERVAL of the /TH/NODE groups
    # *DATABASE_NODAL_FORCE_GROUP builds ("The output interval must be
    # specified using *DATABASE_NODFOR", Vol I R16 p.16-121), so its dt joins
    # the /TFILE minimum exactly the way *DATABASE_SPHOUT's does.
    db_nodfor_dt: float = 0.0
    # *DATABASE_TPRINT — the THERMAL ASCII database interval. Parsed so it can
    # be reported, and deliberately NOT in the /TFILE chain: k2rad converts no
    # thermal keyword at all, so there is no thermal channel for it to pace.
    db_tprint_dt: float = 0.0
    # *DATABASE_NODAL_FORCE_GROUP[_TITLE] → one /TH/NODE per card, 7 variables,
    # per-node skew_ID = CID.
    db_nodal_force_groups: List[DbNodalForceGroup] = field(default_factory=list)
    db_extent_binary: Optional[DbExtentBinary] = None
    # *DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG → offline post-processing
    db_freq_binary: Dict[str, DbFreqBinary] = field(default_factory=dict)

    # ── Initial state / cross sections ─────────────────────────
    # *INITIAL_STRESS_SHELL → /INISHE/STRS_F[/GLOB]
    ini_stress_shells: List[InitialStressShell] = field(default_factory=list)
    # *INITIAL_STRESS_SOLID → /INIBRI/STRS_FGLO
    ini_stress_solids: List[InitialStressSolid] = field(default_factory=list)
    # *DATABASE_CROSS_SECTION_PLANE/_SET → /SECT
    cross_sections: List[CrossSection] = field(default_factory=list)
    # (sect_id, title) of each emitted /SECT — set by the writer's
    # _make_cross_sections, consumed by _make_starter_th_sectio (the
    # *DATABASE_SECFORC → /TH/SECTIO pairing; same pattern as blast_surf_ids)
    sect_ids: List[Tuple[int, str]] = field(default_factory=list)
    # *MAT_ADD_FATIGUE per material id → offline fatigue post-processing
    mat_add_fatigue: Dict[int, MatAddFatigue] = field(default_factory=dict)
    # How many /TH/<type>/<id> blocks build_starter actually wrote, counted from
    # the emitted lines by _warn_duplicate_th_group_ids. build_engine reads it
    # to decide whether an INVENTED /TFILE frequency (no *DATABASE_ card states
    # a dt) is worth warning about: with no /TH group in the deck the invented
    # number governs nothing anyone reads. Stays 0 for a caller that runs
    # build_engine without build_starter — silence, never a spurious warning.
    th_groups_emitted: int = 0

    # ── Skipped / warnings ─────────────────────────────────────
    warnings: List[str] = field(default_factory=list)
    # True once the "/TH/NODE REAC* is an accumulated impulse, not a force"
    # derivation has been written into a warning on this deck. Two conversion
    # paths emit REAC* channels (*DATABASE_SPCFORC and
    # *BOUNDARY_PRESCRIBED_MOTION_RIGID); the second one to fire back-references
    # the first instead of repeating it. See writer/output.py:_warn_reac_impulse.
    reac_impulse_warned: bool = False
    skipped_keywords: List[str] = field(default_factory=list)
    # Keywords the parser RECOGNIZED (they have a handler, so they never reach
    # skipped_keywords) but which produce no card in either output deck. Without
    # this channel a handler that stores a dt and returns is indistinguishable,
    # in the log, from a handler that converts something — and "skipped: 0
    # unsupported keyword(s)" silently reads as "everything was converted".
    # Record with note_recognized_not_emitted(); reported by the conversion log.
    recognized_not_emitted: List[Tuple[str, str]] = field(default_factory=list)

    def note_recognized_not_emitted(self, keyword: str, reason: str) -> None:
        """Record *keyword* as parsed-but-not-converted, with the reason why.

        Deduplicated on the keyword, so a deck repeating a card does not repeat
        the log line."""
        if any(kw == keyword for kw, _ in self.recognized_not_emitted):
            return
        self.recognized_not_emitted.append((keyword, reason))

    def next_id(self) -> int:
        """Return next auto-generated entity ID."""
        v = self._auto_id
        self._auto_id += 1
        return v

    def next_curve_id(self) -> int:
        """A next_id() guaranteed free in the /FUNCT *and* /TABLE namespaces.

        The starter checks FUNCTION and TABLE ids in ONE merged duplicate scan
        (hm_read_table.F:88 counts "total number /TABLE + /FUNCT" before the
        UDOUBLE pass), so a synthesized /FUNCT must dodge user *DEFINE_TABLE /
        _2D / _3D ids and already-synthesized AutoTables as well as user
        curves — a collision is starter ERROR 79 (DUPLICATE ID in "FUNCTION &
        TABLE DEFINITION"), reachable whenever a renumbered deck carries a
        table id at or above the auto-id base (90001). A no-op vs next_id()
        in the common case (no user id that high), so it does not shift ids."""
        fid = self.next_id()
        while (fid in self.curves or fid in self.define_tables
               or fid in self.define_tables_3d or fid in self.auto_tables):
            fid = self.next_id()
        return fid

    def next_sensor_id(self) -> int:
        """A next_id() guaranteed free in the /SENSOR namespace.

        Until the seatbelt batch nothing in the deck could OWN a /SENSOR id:
        the only producer was the *LOAD_SHELL/_SEGMENT_SET arrival-time gate,
        whose ids all come from next_id(). ``*ELEMENT_SEATBELT_SENSOR`` changes
        that — ``SBSID`` is a USER id that is written through verbatim, so a
        deck with a sensor at or above the auto-id base (90001) would otherwise
        collide with a minted one and the starter would answer ERROR 79
        (DUPLICATE ID) over the whole /SENSOR table.

        Same guard shape as next_curve_id / next_part_id / next_prop_id, and a
        no-op vs next_id() in the common case, so it does not shift ids on any
        ordinary deck. Every id it hands out is recorded, so two callers in one
        build cannot be given the same one."""
        sid = self.next_id()
        while sid in self.seatbelt_sensors or sid in self.sensor_ids:
            sid = self.next_id()
        self.sensor_ids.add(sid)
        return sid

    def next_accel_id(self) -> int:
        """A next_id() guaranteed free in the /ACCEL namespace.

        The twin of next_sensor_id: ``*ELEMENT_SEATBELT_ACCELEROMETER``'s
        SBACID is written through verbatim, and an ``*ELEMENT_SEATBELT_SENSOR``
        of SBSTYP 1 needs an /ACCEL of its own on the node it watches (Radioss
        has no "accelerometer-free" acceleration sensor — sensor_acce.cfg's
        ``accel_ID`` is mandatory)."""
        aid = self.next_id()
        used = {a.sbacid for a in self.seatbelt_accels if a.sbacid > 0}
        while aid in used or aid in self.accel_ids:
            aid = self.next_id()
        self.accel_ids.add(aid)
        return aid

    def next_part_id(self) -> int:
        """A next_id() guaranteed free in the /PART namespace, so a synthesized
        connector /PART can never collide with a converted *PART whose PID
        happens to be at or above the auto-id base (90001). Same guard shape as
        next_curve_id, and a no-op vs next_id() in the common case."""
        pid = self.next_id()
        while pid in self.parts:
            pid = self.next_id()
        return pid

    def next_prop_id(self) -> int:
        """A next_id() guaranteed free in the /PROP namespace, so a synthesized
        property (the joint /PROP/TYPE45, the spring /PROP/TYPE4 / TYPE8 /
        TYPE13) can never collide with a converted *SECTION_*: /PROP/SHELL,
        /PROP/SOLID and /PROP/BEAM are all emitted under the SECID verbatim, so
        a SECID at or above the auto-id base (90001) lands on the same id. Same
        guard shape as next_curve_id / next_part_id, and a no-op vs next_id()
        in the common case (no user section that high), so it does not shift
        ids on any ordinary deck.

        The ids of the synthesized ortho / hourglass properties come from
        next_id() themselves and are therefore unique by construction; only the
        SECID-keyed properties can clash. *SECTION_TSHELL joined that list with
        the thick-shell batch — /PROP/TYPE20|21|22 is emitted under the SECID
        verbatim too, so a deck with a *SECTION_TSHELL at or above 90001 would
        otherwise collide with a synthesized ply/joint/spring property.
        *SECTION_SPH joined it with the SPH batch, for exactly the same reason —
        /PROP/SPH is emitted under the SECID verbatim. *SECTION_SEATBELT joined
        it with the seatbelt batch: /PROP/TYPE23 is emitted under the SECID
        verbatim too."""
        prop_id = self.next_id()
        while (prop_id in self.sec_shells or prop_id in self.sec_solids
               or prop_id in self.sec_beams or prop_id in self.sec_tshells
               or prop_id in self.sec_sph or prop_id in self.sec_seatbelts):
            prop_id = self.next_id()
        return prop_id

    def all_mat_ids(self) -> set:
        """Every /MAT id the deck emits under a USER id. Every k2rad material
        emitter writes ``/MAT/<law>/<mid>`` with the LS-DYNA MID verbatim, so
        this is exactly the union of the per-family material dicts (plus the
        *MAT_032 glass companions, which are synthesized but already reserved).
        """
        ids = set()
        for d in (self.mat_elastic, self.mat_plas_tab, self.mat_plas_kin,
                  self.mat_johnson_cook, self.mat_aniso_visco, self.mat_rigid,
                  self.mat_null, self.mat_power_law, self.mat_samp,
                  self.mat_crushable_foam, self.mat_low_density_foam,
                  self.mat_fu_chang_foam, self.mat_honeycomb,
                  self.mat_soil_and_foam, self.mat_low_density_viscous_foam,
                  self.mat_modified_honeycomb, self.mat_deshpande_fleck,
                  self.mat_hill_foam, self.mat_blatz_ko,
                  self.mat_mooney_rivlin, self.mat_ogden, self.mat_hyper_rubber,
                  self.mat_high_explosive, self.mat_spotweld,
                  self.mat_orthotropic, self.mat_enhanced_composite,
                  self.mat_transverse_aniso, self.mat_laminated_glass,
                  self.mat_iso_elas_plas, self.mat_strain_rate_plas,
                  self.mat_gurson, self.mat_hill_3r,
                  self.mat_plas_comp_tens, self.mat_viscoelastic,
                  self.mat_kelvin_maxwell, self.mat_general_visco,
                  self.mat_simplified_rubber, self.mat_soft_tissue,
                  self.mat_cohesive_mixed_mode, self.mat_arup_adhesive,
                  self.mat_cohesive_mm_epr, self.mat_toughened_adhesive,
                  self.mat_tabulated_jc, self.mat_jh_ceramics,
                  self.mat_jh_concrete, self.mat_elastic_fluid,
                  self.mat_fabric,
                  # *MAT_SEATBELT / *MAT_B01 (+_2D) → /MAT/LAW114 or LAW119,
                  # both under the MID verbatim.
                  self.mat_seatbelt):
            ids |= set(d)
        ids |= {g.glass_mid for g in self.mat_laminated_glass.values()
                if g.glass_mid}
        return ids

    def next_mat_id(self) -> int:
        """A next_id() guaranteed free in the /MAT namespace, so a SYNTHESIZED
        material (the *MAT_032 glass companion, the ALE /MAT/LAW51) can never
        collide with a converted *MAT whose MID happens to be at or above the
        auto-id base (90001). Same guard shape as next_curve_id / next_part_id /
        next_prop_id, and a no-op vs next_id() in the common case (no user
        material that high), so it does not shift ids on any ordinary deck.

        k2rad emits every /MAT under the LS-DYNA MID verbatim (there is no
        material-duplication remap as in dyna2rad), so a clash here is a starter
        ERROR 79 DUPLICATE ID."""
        used = self.all_mat_ids()
        mid = self.next_id()
        while mid in used:
            mid = self.next_id()
        return mid

    def next_grnod_id(self) -> int:
        """A next_id() guaranteed free in the /GRNOD namespace.

        k2rad re-emits every user *SET_NODE under its own SID: the SPC path
        writes /GRNOD/NODE/<nsid> and _make_extra_groups re-emits the sets no
        other card consumed, both verbatim. A *SET_NODE whose SID happens to sit
        at or above the auto-id base (90001) therefore lands on the same id as
        a synthesized group, and the starter aborts with
        ``ERROR ID : 79  ** ERROR: DUPLICATE ID / IN NODE GROUP DEFINITION``
        (MSGID=79 over the merged /GRNOD table) — the whole deck stops
        converting into a runnable model, not just the one group.

        Same guard shape as next_curve_id / next_part_id / next_prop_id, and a
        no-op vs next_id() in the common case (no user node set that high), so
        it does not shift ids on any ordinary deck.

        NOTE: the gravity groups, the *BOUNDARY_PRESCRIBED_MOTION_SET motion
        groups and that path's zero-scale /BCS groups draw from this. The other
        synthesized /GRNOD ids (contacts, /INIVEL, the /RBODY node groups, ...)
        still use next_id() and carry the same latent hazard."""
        gid = self.next_id()
        while gid in self.node_sets:
            gid = self.next_id()
        return gid

    def next_monvol_id(self, used: set) -> int:
        """A next_id() guaranteed free in the /MONVOL namespace.

        /MONVOL ids are ONE Radioss namespace across PRES / AIRBAG1 / GAS /
        LFLUID while LS-DYNA's ``*AIRBAG_<MODEL>_ID`` ids are per keyword, so
        writer/monvol.py renumbers a colliding bag onto the auto stream. Without
        this guard the renumbered id is never re-checked against the ids the
        deck ITSELF states: a bag carrying an explicit ``_ID`` at or above the
        auto-id base (90001) can be handed the very id a later un-ID'd bag then
        draws, and both /MONVOLs go into the starter under the same number —
        ``ERROR 79 DUPLICATE ID``, which refuses the whole deck. The failure the
        renumbering exists to prevent, reintroduced by the renumbering.

        Same guard shape as next_curve_id / next_part_id / next_prop_id /
        next_mat_id / next_grnod_id, and a no-op vs next_id() in the common case
        (no user airbag id that high), so it does not shift ids."""
        mid = self.next_id()
        while mid in used:
            mid = self.next_id()
        return mid

    def next_node_id(self) -> int:
        """Reserve and return a /NODE id guaranteed free in the NODE namespace.

        Every other node-synthesis site (the /RBODY CoG masters, the /SKEW/MOV
        third nodes, the connector ground nodes, the moving-rigid-wall carriers)
        open-codes ``max(self.nodes) + 1``. That is safe only because each of
        them writes the new id into ``self.nodes`` BEFORE the next site computes
        its own maximum — an undocumented, unenforced invariant. A site that
        allocates a batch of ids first and registers them afterwards hands the
        same id out twice, and because ``self.nodes`` is a dict the second write
        silently REPLACES the first node: no starter error, just a node teleported
        to another node's coordinates (a folded element, or a rigid body whose
        centre of gravity moved).

        This allocator closes that hole by also skipping ids it has already
        handed out, so a caller may allocate first and register later. Ids start
        one above the current maximum (90000001 on an empty model, the same base
        the open-coded sites use), so it is a no-op vs the existing convention on
        any ordinary deck and does not shift ids."""
        nid = (max(self.nodes) + 1) if self.nodes else 90000001
        while nid in self.nodes or nid in self._reserved_node_ids:
            nid += 1
        self._reserved_node_ids.add(nid)
        return nid

    def all_skew_ids(self) -> set:
        """Every /SKEW id the deck emits — from *DEFINE_COORDINATE_SYSTEM/_NODES/
        _VECTOR (id = cid) and the *DEFINE_VECTOR[_NODES]/_SD_ORIENTATION skews
        assigned by the writer prepass. /SKEW and /FRAME share ONE starter id
        namespace (UDOUBLE over the combined table), so any synthesized /FRAME
        (or box-local skew) id must avoid this set or the starter aborts with
        ERROR 79 DUPLICATE ID."""
        return (set(self.coord_sys) | set(self.coord_nodes)
                | set(self.coord_vectors)
                | set(self.vector_skew_ids.values())
                | set(self.sdorient_skew_ids.values())
                | set(self.joint_skew_ids.values())
                | set(self.synth_skew_ids))

    def reserve_skew_id(self, preferred: int) -> int:
        """Claim a free /SKEW id at or above *preferred* and record it, so a
        later synthesized skew (from any writer module) cannot reuse it."""
        used = self.all_skew_ids()
        skew_id = preferred
        while skew_id in used:
            skew_id += 1
        self.synth_skew_ids.add(skew_id)
        return skew_id

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
