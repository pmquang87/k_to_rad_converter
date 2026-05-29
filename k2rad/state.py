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
class ControlImplicitSolution:
    nsolvr: int         # solver (11=MUMPS,12=PARDISO)
    ilimit: int         # max stiffness reformations
    maxref: int         # max refinements
    dctol: float        # displacement convergence
    ectol: float        # energy convergence
    nlprint: int        # nonlinear print flag


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


# ══════════════════════════════════════════════════════════════════════════════

class ConversionState:
    """Holds all data parsed from the .k file.  Written by handlers,
    read by the writer to produce .rad output."""

    def __init__(self):
        # ── Identity ───────────────────────────────────────────────
        self.model_title: str = "Model"
        self.is_implicit: bool = False
        self._auto_id: int = 90001          # counter for auto-generated IDs
        # Unit system written to the /BEGIN header (mass, length, time).
        # Defaults to the LS-DYNA ton-mm-s system; overridable via convert().
        self.units: Tuple[str, str, str] = ("Mg", "mm", "s")

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

        self.curves: Dict[int, Curve] = {}
        self.coord_sys: Dict[int, CoordSys] = {}

        # ── Sets / groups ──────────────────────────────────────────
        self.node_sets: Dict[int, Tuple[str, List[int]]] = {}   # nsid → (title, [nids])
        self.part_sets: Dict[int, Tuple[str, List[int]]] = {}   # psid → (title, [pids])

        # ── Boundary conditions ────────────────────────────────────
        self.bcs_spcs: List[BcsSpc] = []
        self.prescribed_motions: List[PrescribedMotionRigid] = []
        self.prescribed_motion_sets: List[PrescribedMotionSet] = []

        # ── Loads ──────────────────────────────────────────────────
        self.load_rigid_bodies: List[LoadRigidBody] = []
        self.inivel_nodes: List[InitialVelocityNode] = []
        self.inivel_rbodies: List[InitialVelocityRigidBody] = []
        self.pressure_loads: List[PressureLoad] = []
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
