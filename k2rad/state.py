"""
k2rad.state  –  ConversionState: all data collected from the .k file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class NodeData:
    x: float
    y: float
    z: float


@dataclass
class ShellElem:
    eid: int
    pid: int
    nodes: List[int]   # 3 or 4 node IDs (trailing zeros stripped)


@dataclass
class SolidElem:
    eid: int
    pid: int
    nodes: List[int]   # 4 or 8 node IDs


@dataclass
class BeamElem:
    eid: int
    pid: int
    n1: int
    n2: int
    n3: int            # orientation node


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


@dataclass
class PartData:
    pid: int
    title: str
    secid: int
    mid: int


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


@dataclass
class MatSAMP:
    """*MAT_187 / *MAT_SAMP-1 → /MAT/LAW76 (SAMP-1 semi-analytical polymer).

    Uses the classic SAMP-1 card layout (the one that maps 1:1 onto /MAT/LAW76):
    Card1 mid ro e nu numint; Card2 tab_idt tab_idc tab_ids nu_p fct_idpr;
    Card3 fct_id1 epfail deprpt lcid_tri lcid_lc; Card4 iconv; Card5 asrate.
    The three yield tables (tension/compression/shear) become /TABLE/1 cards.
    """
    mid: int
    title: str
    rho: float
    E: float
    nu: float
    tab_idt: int          # tension yield table   → /TABLE
    tab_idc: int          # compression yield table
    tab_ids: int          # shear yield table
    nu_p: float           # plastic Poisson ratio (Nu_p)
    fct_idpr: int         # pressure-dependence function (fct_IDpr)
    fct_id1: int          # damage function (fct_ID1)
    epfail: float         # plastic failure strain (EPS_f_p)
    deprpt: float         # element deletion plastic strain (EPS_r_p)
    iconv: int            # convexity flag (ICONV)
    asrate: float         # strain-rate smoothing cutoff (→ Fcut)


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
    """*MAT_ADD_EROSION (non-GISSMO criteria) → an OpenRadioss /FAIL model.
    Only the strain-based criteria map cleanly: EFFEPS → /FAIL/JOHNSON,
    MXEPS → /FAIL/TENSSTRAIN. Other criteria and IDAM>=1 (GISSMO/DIEM embedded
    in the erosion card) are reported but not converted."""
    mid: int
    effeps: float      # max effective strain at failure  → /FAIL/JOHNSON D1
    mxeps: float       # max principal strain at failure   → /FAIL/TENSSTRAIN
    numfip: float
    idam: int
    other: List[str]   # names of other active criteria (for the warning)


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
    """
    inter_id: int
    title: str
    ssid: int; sstyp: int   # slave side: 4=node set, 3=part, 2=part set, 0=segment set
    msid: int; mstyp: int   # master side: 0=segment set, 3=part, 2=part set
    variant: str            # "NODES_TO_SURFACE" | "SURFACE_TO_SURFACE" | "SHELL_EDGE_TO_SURFACE"
    offset: bool = False    # _OFFSET / _CONSTRAINED_OFFSET / _BEAM_OFFSET keyword flavour
    sst: float = 0.0        # Card3 SST (negative = absolute tie distance)
    mst: float = 0.0        # Card3 MST (negative = absolute tie distance)


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
    The applied acceleration field is ``sf × lcid(t)`` along ``dir``; maps to an
    OpenRadioss /GRAV over every part. LS-DYNA's base-acceleration sign
    convention is transcribed directly (Fscale = sf), which the writer flags for
    the user to verify against /GRAV.
    """
    dir: str            # "X" | "Y" | "Z"
    lcid: int
    sf: float


@dataclass
class GravityLoadPart:
    """*LOAD_GRAVITY_PART — gravity body load on one part → /GRAV.

    LS-DYNA card: pid dof lc accel lcdr stga stgr.  DOF 1/2/3 loads the part in
    the NEGATIVE X/Y/Z direction (all-positive inputs give a downward load); the
    Radioss dyna-reader maps it to /GRAV the same way, so the writer emits
    Fscaley = -accel (or -1 × curve LC when lc > 0).  Gravity is irrelevant to a
    non-prestressed eigenproblem, so modal decks only get an informational note.
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


# ══════════════════════════════════════════════════════════════════════════════

class ConversionState:
    """Holds all data parsed from the .k file.  Written by handlers,
    read by the writer to produce .rad output."""

    def __init__(self):
        # ── Identity ───────────────────────────────────────────────
        self.model_title: str = "Model"
        self.is_implicit: bool = False
        # *CONTROL_IMPLICIT_EIGENVALUE present → normal-modes (/EIG) analysis.
        # Switches the engine to a one-shot /IMPL/LINEAR eigensolve and skips
        # the inert contact stub (the eigen path ignores contact, and the stub
        # crashes the implicit-eigen setup).
        self.is_modal: bool = False
        self._auto_id: int = 90001          # counter for auto-generated IDs
        # Unit system written to the /BEGIN header (mass, length, time).
        # Defaults to the LS-DYNA ton-mm-s system; overridable via convert().
        self.units: Tuple[str, str, str] = ("Mg", "mm", "s")
        # Opt-in conversion switches (CLI flags); see ConvertOptions.
        self.options: ConvertOptions = ConvertOptions()

        # ── Mesh ───────────────────────────────────────────────────
        self.nodes: Dict[int, NodeData] = {}
        self.shell_elems: List[ShellElem] = []
        self.solid_elems: List[SolidElem] = []
        self.beam_elems: List[BeamElem] = []
        # *ELEMENT_DISCRETE → /SPRING (on a /PROP/TYPE4 built by the writer)
        self.discrete_elems: List[DiscreteElem] = []

        # ── Model entities ─────────────────────────────────────────
        self.parts: Dict[int, PartData] = {}
        self.sec_shells: Dict[int, SectionShell] = {}
        self.sec_solids: Dict[int, SectionSolid] = {}
        self.sec_beams: Dict[int, SectionBeam] = {}
        # *SECTION_DISCRETE → /PROP/TYPE4 flags (spring/damper connectors)
        self.sec_discrete: Dict[int, SectionDiscrete] = {}

        self.mat_elastic: Dict[int, MatElastic] = {}
        self.mat_plas_tab: Dict[int, MatPlasTAB] = {}
        self.mat_plas_kin: Dict[int, MatPlasKin] = {}
        self.mat_rigid: Dict[int, MatRigid] = {}
        self.mat_null: Dict[int, MatNull] = {}
        self.mat_power_law: Dict[int, MatPowerLaw] = {}
        self.mat_samp: Dict[int, MatSAMP] = {}          # *MAT_187 → /MAT/LAW76
        self.fail_gissmo: Dict[int, FailGissmo] = {}    # *MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2
        self.mat_add_erosion: Dict[int, MatAddErosion] = {}   # *MAT_ADD_EROSION → /FAIL
        # Foam / honeycomb material families
        self.mat_crushable_foam: Dict[int, MatCrushableFoam] = {}   # MAT_063 → /MAT/LAW50
        self.mat_low_density_foam: Dict[int, MatLowDensityFoam] = {}  # MAT_057 → /MAT/LAW38
        self.mat_fu_chang_foam: Dict[int, MatFuChangFoam] = {}      # MAT_083 → /MAT/LAW70
        self.mat_honeycomb: Dict[int, MatHoneycomb] = {}           # MAT_026 → /MAT/LAW28
        # Discrete-element (spring/damper) materials → /PROP/TYPE4 fields
        self.mat_spring_elastic: Dict[int, MatSpringElastic] = {}          # MAT_S01
        self.mat_spring_nonlinear: Dict[int, MatSpringNonlinearElastic] = {}  # MAT_S04
        self.mat_damper_viscous: Dict[int, MatDamperViscous] = {}          # MAT_D01
        # *MAT_SPOTWELD (MAT_100) beam parts → /PROP/TYPE13 /SPRING connectors
        self.mat_spotweld: Dict[int, MatSpotweld] = {}
        # *CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT with
        # failure forces → stiff /PROP/TYPE13 /SPRING (no-failure ones become
        # 2-node CNRBs at parse time and go through state.cnrbs instead)
        self.constrained_spotwelds: List[ConstrainedSpotweld] = []
        # Ground nodes synthesized by the connector writer (registered in
        # state.nodes for id-collision safety; excluded from the implicit
        # free-node guard because they are already fully fixed by /BCS)
        self.connector_ground_nodes: set = set()
        self.constrained_node_sets: List[ConstrainedNodeSet] = []  # *CONSTRAINED_NODE_SET → /RLINK
        # curve ids referenced as LAW76 yield tables — emitted as /TABLE/1 (not
        # /FUNCT); tracked so _make_functions can exclude them.
        self.law76_table_ids: set = set()
        # High-explosive / EOS (coupled ALE / JWL detonation):
        #   *MAT_HIGH_EXPLOSIVE_BURN + *EOS_JWL (shared id) → /MAT/LAW5
        #   *MAT_NULL carrier + *EOS_* (shared id)          → /MAT/LAW6 + /EOS/*
        self.mat_high_explosive: Dict[int, MatHighExplosiveBurn] = {}
        self.eos_jwl: Dict[int, EosJwl] = {}            # eosid → JWL params
        self.eos_cards: Dict[int, EosCard] = {}         # eosid → /EOS/<kind>

        self.curves: Dict[int, Curve] = {}
        # *DEFINE_CURVE lcids in deck parse order — used to resolve the legacy
        # *DEFINE_TABLE form (curves follow the table positionally).
        self.curve_order: List[int] = []
        # *DEFINE_TABLE[_2D] → /TABLE/1 (Ndim=2), keyed by table id (shares the
        # LS-DYNA load-curve id space with state.curves).
        self.define_tables: Dict[int, DefineTable] = {}
        self.coord_sys: Dict[int, CoordSys] = {}
        # *DEFINE_COORDINATE_NODES → /SKEW (moving or fixed)
        self.coord_nodes: Dict[int, CoordNodes] = {}

        # ── Sets / groups ──────────────────────────────────────────
        self.node_sets: Dict[int, Tuple[str, List[int]]] = {}   # nsid → (title, [nids])
        self.part_sets: Dict[int, Tuple[str, List[int]]] = {}   # psid → (title, [pids])
        # *SET_SEGMENT → segment sets (used by /LOAD/PBLAST as /SURF/SEG)
        self.segment_sets: Dict[int, SegmentSet] = {}           # sid → SegmentSet

        # ── Boundary conditions ────────────────────────────────────
        self.bcs_spcs: List[BcsSpc] = []
        self.prescribed_motions: List[PrescribedMotionRigid] = []
        self.prescribed_motion_sets: List[PrescribedMotionSet] = []

        # ── Constraints ────────────────────────────────────────────
        # *CONSTRAINED_NODAL_RIGID_BODY[_SPC] → /RBODY (+ /BCS)
        self.cnrbs: List[ConstrainedNodalRigidBody] = []

        # *CONSTRAINED_EXTRA_NODES_NODE/_SET: pid → extra node ids merged into
        # that rigid part's /RBODY secondary-node group
        self.extra_rigid_nodes: Dict[int, List[int]] = {}

        # *CONSTRAINED_RIGID_BODIES: (master_pid, slave_pid) pairs — the slave
        # rigid part's nodes are folded into the master's single /RBODY
        self.rigid_body_merges: List[Tuple[int, int]] = []

        # *RIGIDWALL_PLANAR → /RWALL/PLANE
        self.rigid_walls: List[RigidWallPlanar] = []

        # ── Loads ──────────────────────────────────────────────────
        self.load_rigid_bodies: List[LoadRigidBody] = []
        # *LOAD_NODE_POINT / *LOAD_NODE_SET → /CLOAD
        self.load_nodes: List[LoadNode] = []
        self.inivel_nodes: List[InitialVelocityNode] = []
        self.inivel_rbodies: List[InitialVelocityRigidBody] = []
        self.pressure_loads: List[PressureLoad] = []
        # *LOAD_SEGMENT_SET rows → /PLOAD (segments resolved from segment_sets
        # at write time so the *SET_SEGMENT may be defined later in the deck)
        self.segment_set_pressure_loads: List[SegmentSetPressureLoad] = []
        # *LOAD_GRAVITY_PART rows → /GRAV (non-modal decks only)
        self.gravity_loads: List[GravityLoadPart] = []
        # *LOAD_BODY_{X,Y,Z} whole-model base-acceleration rows → /GRAV
        self.body_loads: List[LoadBody] = []
        # *LOAD_BLAST_ENHANCED sources keyed by bid, and the
        # *LOAD_BLAST_SEGMENT_SET rows that apply them → /LOAD/PBLAST + /SURF/SEG
        self.blast_sources: Dict[int, LoadBlastEnhanced] = {}
        self.blast_segment_loads: List[LoadBlastSegmentSet] = []
        # (surf_id, title) of each blast-loaded /SURF/SEG the writer emitted —
        # set by _make_blast_loads, consumed by the *DATABASE_BINARY_BLSTFOR
        # /TH/SURF output (same pattern as th_sub_ids for /TH/INTER)
        self.blast_surf_ids: List[Tuple[int, str]] = []
        # *INITIAL_DETONATION → /DFS/DETPOINT (JWL burn origin for LAW5 explosives)
        self.detonations: List[InitialDetonation] = []
        # ── Coupled ALE / FSI ──────────────────────────────────────
        # *ALE_MULTI-MATERIAL_GROUP → /MAT/LAW51 (MULTIMAT) submaterial order
        self.ale_mmgs: List[AleMultiMaterialGroup] = []
        # *CONSTRAINED_LAGRANGE_IN_SOLID → /INTER/TYPE18 (fluid-structure coupling)
        self.lagrange_in_solid: List[ConstrainedLagrangeInSolid] = []
        # *INITIAL_VOLUME_FRACTION[_GEOMETRY] → /INIVOL (initial ALE fill)
        self.volume_fractions: List[InitialVolumeFraction] = []
        # *BOUNDARY_NON_REFLECTING → /EBCS/NRF (silent far-field)
        self.non_reflecting: List[BoundaryNonReflecting] = []
        # *CONTROL_ALE → /ALE advection hints (mostly informational)
        self.control_ale: Optional[ControlAle] = None
        # Unit system (mass, length, time) implied by a *LOAD_BLAST_ENHANCED UNIT
        # flag. The TM5-1300 empirical blast formulas are unit-dependent, so the
        # /BEGIN unit labels must match the deck's real units for /LOAD/PBLAST to
        # convert correctly; convert() applies this when the caller left units at
        # the default. None = no blast load / unknown flag.
        self.blast_unit_system: Optional[Tuple[str, str, str]] = None
        # *ELEMENT_MASS additions: node_ID → total added translational mass
        # (in input unit, typically ton). Used to set /RBODY Mass field
        # for rigid-body master nodes (provides M contribution to K_eff in
        # implicit analyses), or to emit /ADMAS for ordinary nodes.
        self.added_node_masses: Dict[int, float] = {}
        # *ELEMENT_MASS_PART additions: part_ID → (addmass, finmass).
        # ADDMASS  = extra mass distributed across the part's nodes (or set
        #            directly on the rigid-body master if part is rigid).
        # FINMASS  = target total mass; if nonzero, ADDMASS = FINMASS − existing.
        # Per LS-DYNA R16 Manual p.19-67: exactly one of ADDMASS/FINMASS is
        # nonzero. For rigid-body parts, the resulting mass is applied to the
        # /RBODY Mass field (no need to distribute over slave nodes).
        self.element_mass_parts: Dict[int, Tuple[float, float]] = {}
        # Populated by build_starter after _make_rbodies: pid → grnod_id of all rbody nodes
        self.rbody_grnods: Dict[int, int] = {}
        # pid → grnod_id containing ONLY the independent node (used by /CLOAD)
        self.rbody_ind_grnods: Dict[int, int] = {}

        # ── Contacts ───────────────────────────────────────────────
        self.contacts_single: List[ContactAutoSingle] = []
        self.contacts_surf2surf: List[ContactAutoSurf2Surf] = []
        # *CONTACT_TIED_* → /INTER/TYPE2 (tied kinematic interface)
        self.contacts_tied: List[ContactTied] = []
        self.force_transducers: List[ContactForceTransducer] = []
        # (sub_id, title) for each emitted /INTER/SUB → used to build /TH/SUBS
        self.th_sub_ids: List[Tuple[int, str]] = []

        # ── Control ────────────────────────────────────────────────
        self.ctrl_accuracy: Optional[ControlAccuracy] = None
        self.ctrl_contact: Optional[ControlContact] = None
        self.ctrl_cpu: Optional[ControlCpu] = None
        self.ctrl_energy: Optional[ControlEnergy] = None
        self.ctrl_hourglass: Optional[ControlHourglass] = None
        self.ctrl_implicit_auto: Optional[ControlImplicitAuto] = None
        self.ctrl_implicit_dyn: Optional[ControlImplicitDynamics] = None
        self.ctrl_output: Optional[ControlOutput] = None
        self.ctrl_shell: Optional[ControlShell] = None
        self.ctrl_solid: Optional[ControlSolid] = None
        self.ctrl_implicit_gen: Optional[ControlImplicitGeneral] = None
        self.ctrl_implicit_sol: Optional[ControlImplicitSolution] = None
        self.ctrl_implicit_eig: Optional[ControlImplicitEigenvalue] = None
        self.ctrl_termination: Optional[ControlTermination] = None
        self.ctrl_timestep: Optional[ControlTimestep] = None
        self.damping_global: Optional[DampingGlobal] = None
        self.damping_part_stiffness: List[DampingPartStiffness] = []

        # ── Database / output ──────────────────────────────────────
        self.db_d3plot: Optional[DbD3Plot] = None
        self.db_elout_dt: float = 0.0
        self.db_glstat_dt: float = 0.0
        self.db_histories: List[DbHistory] = []
        self.db_abstat_dt: float = 0.0
        self.db_d3thdt_dt: float = 0.0
        self.db_intfor_dt: float = 0.0
        self.db_deforc_dt: float = 0.0
        self.db_jntforc_dt: float = 0.0
        self.db_matsum_dt: float = 0.0
        self.db_nodout_dt: float = 0.0
        self.db_rcforc_dt: float = 0.0
        self.db_rwforc_dt: float = 0.0
        self.db_secforc_dt: float = 0.0
        self.db_sleout_dt: float = 0.0
        # *DATABASE_SPCFORC → /TH/NODE REAC* on the /BCS nodes + /ANIM/VECT/FREAC
        self.db_spcforc_dt: float = 0.0
        # *DATABASE_NCFORC → /TH/INTER on every converted contact interface
        self.db_ncforc_dt: float = 0.0
        # *DATABASE_BINARY_BLSTFOR → /TH/SURF (P,A) on the blast-loaded
        # surfaces + /ANIM/NODA/PEXT + /ANIM/VECT/FEXT
        self.db_blstfor_dt: float = 0.0
        self.db_extent_binary: Optional[DbExtentBinary] = None
        # *DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG → offline post-processing
        self.db_freq_binary: Dict[str, DbFreqBinary] = {}
        # *MAT_ADD_FATIGUE per material id → offline fatigue post-processing
        self.mat_add_fatigue: Dict[int, MatAddFatigue] = {}

        # ── Skipped / warnings ─────────────────────────────────────
        self.warnings: List[str] = []
        self.skipped_keywords: List[str] = []

    def next_id(self) -> int:
        """Return next auto-generated entity ID."""
        v = self._auto_id
        self._auto_id += 1
        return v

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
