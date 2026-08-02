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
    node order, with ``None`` for a BLANK cell — blank and an explicit ``0.0``
    are DIFFERENT here (see writer/mesh.py: only populated cells enter the
    element-thickness mean), which is exactly the distinction dyna2rad's reader
    throws away. ``beta`` is the *ELEMENT_SHELL_BETA / _THICKNESS material angle
    in DEGREES → the /SHELL / /SH3N ``Phi`` column (the solver converts to
    radians itself, hm_read_shell.F:170).
    """
    eid: int
    pid: int
    nodes: List[int]   # 3 or 4 node IDs (trailing zeros stripped)
    thick_nodes: List[Optional[float]] = field(default_factory=list)
    beta: float = 0.0


@dataclass
class SolidElem:
    eid: int
    pid: int
    nodes: List[int]   # 4 or 8 node IDs


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


@dataclass
class SectionSolid:
    secid: int
    title: str
    elform: int
    # ALE/Euler flag for /PROP/SOLID field 3 (Iale): 0 Lagrange, 1 ALE, 2 Euler.
    # LS-DYNA *SECTION_SOLID ELFORM 11 (1-pt ALE multi-material) / 12 (1-pt ALE
    # single material) set this to 1.
    iale: int = 0


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
    # ELFORM=9 (spotweld beam) card2 is VOL INER CID CA ... — no area/inertia:
    vol: float = 0.0   # spotweld nugget volume
    ca: float = 0.0    # spotweld cross-sectional area


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
# the starter (PROP_SHELL=2), so a converted part can never sit on the isotropic
# /PROP/SHELL (ERROR 3047) — each gets a synthesized orthotropic property, see
# ``ConversionState.composite_prop_ids``.
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
    long_form: bool = False
    irpl: int = 0        # optional OPTCARD: 103 = 3-point Simpson per layer
    optt: float = 0.0    # _CONTACT contact thickness


@dataclass
class MatRigid:
    """*MAT_RIGID → /MAT/ELAST + /RBODY (deferred)."""
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    cmo: float
    con1: int
    con2: int


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


@dataclass
class PrescribedMotionRigid:
    pid: int            # rigid part ID
    dof: int            # 1=X,2=Y,3=Z,5=RX,6=RY,7=RZ
    vad: int            # 0=vel,1=acc,2=disp
    lcid: int
    sf: float
    death: float
    birth: float


@dataclass
class PrescribedMotionSet:
    """*BOUNDARY_PRESCRIBED_MOTION_SET / *_NODE — applies to a node set."""
    nsid: int           # node set ID (0=node ID for _NODE variant)
    dof: int            # 1=X,2=Y,3=Z,4=RX,5=RY,6=RZ
    vad: int            # 0=vel,1=acc,2=disp
    lcid: int
    sf: float           # scale factor (0 → zero displacement → /BCS)
    death: float
    birth: float


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
class FoamRefGeometry:
    """*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] → one /XREF per part whose nodes
    intersect the keyword's node table (dyna2rad ConvertInitialFoamReferenceGeometry;
    conversion is unconditional — the material REF flags are never consulted)."""
    ndtrrg: int = 0                        # _RAMP ramp steps → Nitrs (only if >0)
    nodes: Dict[int, Tuple[float, float, float]] = field(default_factory=dict)


@dataclass
class PressureLoad:
    """*LOAD_SEGMENT / *LOAD_SEGMENT_ID → /PLOAD."""
    lcid: int
    sf: float
    nodes: List[int]


@dataclass
class SegmentSetPressureLoad:
    """*LOAD_SEGMENT_SET — a pressure/traction on every segment of a *SET_SEGMENT.

    ``ssid`` references a *SET_SEGMENT (``state.segment_sets``); the segments are
    resolved at write time so the set may be defined anywhere in the deck. Each
    segment becomes one /PLOAD entry with function ``lcid`` scaled by ``sf``.
    """
    ssid: int
    lcid: int
    sf: float


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
    db_type: str        # "SHELL", "SOLID", "NODE"
    ids: List[int] = field(default_factory=list)


@dataclass
class DbExtentBinary:
    """*DATABASE_EXTENT_BINARY — controls what goes into binary output files."""
    strflg: int = 0     # strain tensor output flag
    sigflg: int = 1     # stress tensor output flag
    epsflg: int = 1     # effective strain output flag
    rltflg: int = 1     # resultant stresses flag
    engflg: int = 1     # energy output flag
    shge: int = 0       # shell hourglass energy flag


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
    sec_solids: Dict[int, SectionSolid] = field(default_factory=dict)
    sec_beams: Dict[int, SectionBeam] = field(default_factory=dict)
    # *SECTION_DISCRETE → /PROP/TYPE4 flags (spring/damper connectors)
    sec_discrete: Dict[int, SectionDiscrete] = field(default_factory=dict)
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
    # *PART_COMPOSITE parts, keyed by PID — the per-ply layup that replaces the
    # section-derived property (→ /PROP/TYPE51 + one /PROP/TYPE19 per ply).
    part_composites: Dict[int, PartComposite] = field(default_factory=dict)

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
    # Hyperelastic rubber batch (dyna2rad targets):
    #   MAT_007 → LAW42 fixed form; MAT_027 → LAW42 or LAW69; MAT_077_O → LAW42
    #   (embedded Prony) or LAW69; MAT_077_H → LAW95 (+/VISC/PRONY) or LAW69
    mat_blatz_ko: Dict[int, MatBlatzKo] = field(default_factory=dict)
    mat_mooney_rivlin: Dict[int, MatMooneyRivlin] = field(default_factory=dict)
    mat_ogden: Dict[int, MatOgdenRubber] = field(default_factory=dict)
    mat_hyper_rubber: Dict[int, MatHyperelasticRubber] = field(default_factory=dict)
    # *INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] blocks (one entry per keyword
    # instance, in deck order) → /XREF per intersecting part
    foam_ref_geoms: List[FoamRefGeometry] = field(default_factory=list)
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
    # *MAT_SPOTWELD (MAT_100) beam parts → /PROP/TYPE13 /SPRING connectors
    mat_spotweld: Dict[int, MatSpotweld] = field(default_factory=dict)
    # *CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT with
    # failure forces → stiff /PROP/TYPE13 /SPRING (no-failure ones become
    # 2-node CNRBs at parse time and go through state.cnrbs instead)
    constrained_spotwelds: List[ConstrainedSpotweld] = field(default_factory=list)
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
    # curve ids referenced as LAW76 yield tables — emitted as /TABLE/1 (not
    # /FUNCT); tracked so _make_functions can exclude them.
    law76_table_ids: set = field(default_factory=set)
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
    # *SET_SEGMENT → segment sets (used by /LOAD/PBLAST as /SURF/SEG)
    segment_sets: Dict[int, SegmentSet] = field(default_factory=dict)           # sid → SegmentSet
    # *SET_SHELL/_SOLID/_BEAM element sets: sid → (title, [eids]).
    # Referenced by *DATABASE_CROSS_SECTION_SET (→ the /SECT element groups).
    shell_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)
    solid_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)
    beam_sets: Dict[int, Tuple[str, List[int]]] = field(default_factory=dict)

    # ── Boundary conditions ────────────────────────────────────
    bcs_spcs: List[BcsSpc] = field(default_factory=list)
    # /BCS written by the CNRB _SPC path (see CnrbSpcBc). Rebuilt from scratch
    # on every _make_cnrb_rbodies call, so re-running the writer is idempotent.
    cnrb_spc_bcs: List[CnrbSpcBc] = field(default_factory=list)
    prescribed_motions: List[PrescribedMotionRigid] = field(default_factory=list)
    prescribed_motion_sets: List[PrescribedMotionSet] = field(default_factory=list)

    # ── Constraints ────────────────────────────────────────────
    # *CONSTRAINED_NODAL_RIGID_BODY[_SPC] → /RBODY (+ /BCS)
    cnrbs: List[ConstrainedNodalRigidBody] = field(default_factory=list)

    # *CONSTRAINED_EXTRA_NODES_NODE/_SET: pid → extra node ids merged into
    # that rigid part's /RBODY secondary-node group
    extra_rigid_nodes: Dict[int, List[int]] = field(default_factory=dict)

    # *CONSTRAINED_RIGID_BODIES: (master_pid, slave_pid) pairs — the slave
    # rigid part's nodes are folded into the master's single /RBODY
    rigid_body_merges: List[Tuple[int, int]] = field(default_factory=list)

    # *RIGIDWALL_PLANAR → /RWALL/PLANE
    rigid_walls: List[RigidWallPlanar] = field(default_factory=list)

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
    # *LOAD_GRAVITY_PART rows → /GRAV (non-modal decks only)
    gravity_loads: List[GravityLoadPart] = field(default_factory=list)
    # *LOAD_BODY_{X,Y,Z} whole-model base-acceleration rows → /GRAV
    body_loads: List[LoadBody] = field(default_factory=list)
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
    force_transducers: List[ContactForceTransducer] = field(default_factory=list)
    # (sub_id, title) for each emitted /INTER/SUB → used to build /TH/SUBS
    th_sub_ids: List[Tuple[int, str]] = field(default_factory=list)

    # ── Control ────────────────────────────────────────────────
    ctrl_accuracy: Optional[ControlAccuracy] = None
    ctrl_contact: Optional[ControlContact] = None
    ctrl_cpu: Optional[ControlCpu] = None
    ctrl_energy: Optional[ControlEnergy] = None
    ctrl_hourglass: Optional[ControlHourglass] = None
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

    # ── Database / output ──────────────────────────────────────
    db_d3plot: Optional[DbD3Plot] = None
    db_elout_dt: float = 0.0
    db_glstat_dt: float = 0.0
    db_histories: List[DbHistory] = field(default_factory=list)
    db_abstat_dt: float = 0.0
    db_d3thdt_dt: float = 0.0
    db_intfor_dt: float = 0.0
    db_deforc_dt: float = 0.0
    db_jntforc_dt: float = 0.0
    db_matsum_dt: float = 0.0
    db_nodout_dt: float = 0.0
    db_rcforc_dt: float = 0.0
    db_rwforc_dt: float = 0.0
    db_secforc_dt: float = 0.0
    db_sleout_dt: float = 0.0
    # *DATABASE_SPCFORC → /TH/NODE REAC* on the /BCS nodes + /ANIM/VECT/FREAC
    db_spcforc_dt: float = 0.0
    # *DATABASE_NCFORC → /TH/INTER on every converted contact interface
    db_ncforc_dt: float = 0.0
    # *DATABASE_BINARY_BLSTFOR → /TH/SURF (P,A) on the blast-loaded
    # surfaces + /ANIM/NODA/PEXT + /ANIM/VECT/FEXT
    db_blstfor_dt: float = 0.0
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

    # ── Skipped / warnings ─────────────────────────────────────
    warnings: List[str] = field(default_factory=list)
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
        """A next_id() guaranteed free in the /FUNCT (curve) namespace, so a
        synthesized curve can never silently clobber a user *DEFINE_CURVE whose
        LCID happens to be >= the auto-id base (90001). A no-op vs next_id() in
        the common case (no user curve that high), so it does not shift ids."""
        fid = self.next_id()
        while fid in self.curves:
            fid = self.next_id()
        return fid

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
        SECID-keyed properties can clash."""
        prop_id = self.next_id()
        while (prop_id in self.sec_shells or prop_id in self.sec_solids
               or prop_id in self.sec_beams):
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
                  self.mat_fu_chang_foam, self.mat_honeycomb, self.mat_blatz_ko,
                  self.mat_mooney_rivlin, self.mat_ogden, self.mat_hyper_rubber,
                  self.mat_high_explosive, self.mat_spotweld,
                  self.mat_orthotropic, self.mat_enhanced_composite,
                  self.mat_transverse_aniso, self.mat_laminated_glass):
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

        NOTE: only the gravity groups draw from this yet. The other synthesized
        /GRNOD ids (contacts, /INIVEL, the /RBODY node groups, ...) still use
        next_id() and carry the same latent hazard."""
        gid = self.next_id()
        while gid in self.node_sets:
            gid = self.next_id()
        return gid

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
