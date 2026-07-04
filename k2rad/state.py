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
class PressureLoad:
    """*LOAD_SEGMENT / *LOAD_SEGMENT_ID → /PLOAD."""
    lcid: int
    sf: float
    nodes: List[int]


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
    # Element-free CoG masters for *MAT_RIGID parts (opt-in). By default the
    # /RBODY master is the part's lowest-id mesh node, which (a) is an element
    # corner → starter WARNINGs 448 "MAIN NODE CONNECTED TO AN ELEMENT" + 1624
    # "MAIN NODE REMOVED FROM SECONDARY NODE SET", and (b) gets relocated to the
    # part's centre of mass at runtime (ICoG default) so that mesh node's
    # coordinates appear to change in post-processing. With this flag on, each
    # *MAT_RIGID part gets a NEW synthesized node at its nodal centroid as the
    # /RBODY master (the same treatment CNRBs always get) — mesh nodes stay
    # put and the warnings disappear. Off by default: it renumbers every rigid
    # master, which breaks byte-identical output and any script that addresses
    # loads/readouts by the old master-node id.
    rigid_cog_master: bool = False


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

        # ── Model entities ─────────────────────────────────────────
        self.parts: Dict[int, PartData] = {}
        self.sec_shells: Dict[int, SectionShell] = {}
        self.sec_solids: Dict[int, SectionSolid] = {}
        self.sec_beams: Dict[int, SectionBeam] = {}

        self.mat_elastic: Dict[int, MatElastic] = {}
        self.mat_plas_tab: Dict[int, MatPlasTAB] = {}
        self.mat_plas_kin: Dict[int, MatPlasKin] = {}
        self.mat_rigid: Dict[int, MatRigid] = {}
        self.mat_null: Dict[int, MatNull] = {}
        self.mat_power_law: Dict[int, MatPowerLaw] = {}
        # High-explosive / EOS (coupled ALE / JWL detonation):
        #   *MAT_HIGH_EXPLOSIVE_BURN + *EOS_JWL (shared id) → /MAT/LAW5
        #   *MAT_NULL carrier + *EOS_* (shared id)          → /MAT/LAW6 + /EOS/*
        self.mat_high_explosive: Dict[int, MatHighExplosiveBurn] = {}
        self.eos_jwl: Dict[int, EosJwl] = {}            # eosid → JWL params
        self.eos_cards: Dict[int, EosCard] = {}         # eosid → /EOS/<kind>

        self.curves: Dict[int, Curve] = {}
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

        # ── Loads ──────────────────────────────────────────────────
        self.load_rigid_bodies: List[LoadRigidBody] = []
        self.inivel_nodes: List[InitialVelocityNode] = []
        self.inivel_rbodies: List[InitialVelocityRigidBody] = []
        self.pressure_loads: List[PressureLoad] = []
        # *LOAD_GRAVITY_PART rows → /GRAV (non-modal decks only)
        self.gravity_loads: List[GravityLoadPart] = []
        # *LOAD_BODY_{X,Y,Z} whole-model base-acceleration rows → /GRAV
        self.body_loads: List[LoadBody] = []
        # *LOAD_BLAST_ENHANCED sources keyed by bid, and the
        # *LOAD_BLAST_SEGMENT_SET rows that apply them → /LOAD/PBLAST + /SURF/SEG
        self.blast_sources: Dict[int, LoadBlastEnhanced] = {}
        self.blast_segment_loads: List[LoadBlastSegmentSet] = []
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
