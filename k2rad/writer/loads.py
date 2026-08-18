"""Starter loads and constraints: BCS, cloads, pressure, gravity, imposed motions, inivel, rigid walls, springs/connectors, added masses, damping."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from ..state import (
    ConversionState, NodeData, BeamElem, SectionDiscrete, PartData, Curve,
    DampingFrequencyRange, PM_VAD_KEYWORD, RigidWallGeomFace,
)
from .common import (
    HDR, _discrete_beam_pids, _dof_string, _emit_grnod_grnod, _emit_grnod_node,
    _emit_grpart_part, _emit_id_group, _f, _fmt_eid_list, _i, _part_node_sets,
    _spotweld_beam_pids, _vcross, _vnorm, _vsub,
)
from .mesh import _emit_skew_fix, _emit_skew_mov, _ortho_skew_axes

__all__ = [
    "_make_rlinks",
    "_make_bcs",
    "_FORCE_DOF_AXIS",
    "_emit_spr_gene_dof",
    "_emit_spr_gene_dof_kc",
    "_make_grounding_springs",
    "SpringDof",
    "_as_spring_dof",
    "_emit_spring_dof",
    "_emit_prop_type4",
    "_emit_prop_type8",
    "_emit_prop_type13",
    "_pts_slope_at_origin",
    "_curve_slope_at_origin",
    "_mirror_one_sided_curve",
    "_plastic_to_total_disp",
    "_card_value",
    "_monotonic_abscissae",
    "_emit_funct",
    "_s03_curve_points",
    "_curve_max_slope",
    "_finite_length",
    "_element_length",
    "_new_ground_node",
    "_emit_spring_part",
    "_make_discrete_springs",
    "PLOTEL_ID",
    "PLOTEL_MASS",
    "_spring_eid_families",
    "_warn_spring_eid_collisions",
    "_make_plotel_elements",
    "_box_basis",
    "_box_global_corners",
    "_box_contains",
    "_box_node_ids",
    "_resolve_box_nodes",
    "_make_spotweld_beam_connectors",
    "_make_constrained_spotweld_springs",
    "_CLUSTER_IFAIL",
    "_CLUSTER_A",
    "_CLUSTER_B",
    "_cluster_brick_eids",
    "_cluster_failure_limits",
    "_emit_cluster_brick",
    "_emit_th_cluster",
    "_make_hex_spotweld_clusters",
    "_DOF_DIR",
    "_emit_imp_card",
    "_pm_skew_for",
    "_pm_lock_cards",
    "_make_imposed_motions",
    "_synthesize_local_motion_frames",
    "_PM_DOF_TO_BCS",
    "_or_dof_codes",
    "_pm_set_nodes",
    "_make_imposed_motions_set",
    "_emit_grnod_part",
    "_emit_grav_card",
    "_rbody_mains_in_scope",
    "_grav_groups",
    "_make_gravity_loads",
    "_make_body_loads",
    "_emit_centri_card",
    "_centri_frame",
    "_emit_inivel",
    "_make_inivel",
    "_emit_frame_fix",
    "_emit_inivel_axis",
    "_make_initial_velocity",
    "_make_initial_velocity_generation",
    "_emit_pload_card",
    "_emit_sensor_time",
    "_shell_load_segments",
    "_make_pressure_loads",
    "_make_added_masses",
    "_make_starter_cloads",
    "_make_node_cloads",
    "_synthesize_rwall_moving_nodes",
    "_rwall_finite_corners",
    "_rwall_geom_triad",
    "_rwall_geom_faces",
    "_resolve_geometric_rigid_walls",
    "_make_geometric_rwall_motion",
    "_emit_rwall_geom_face",
    "_rwall_node_groups",
    "_rwall_slide",
    "_make_rigid_walls",
    "_make_modal_dummy_cload",
    "_make_damping",
    "_make_damping_part_mass",
    "_make_damping_frequency_range",
    "_resolve_damping_relative",
    "_make_free_node_constraints",
]


def _make_rlinks(state: ConversionState) -> List[str]:
    """*CONSTRAINED_NODE_SET → /RLINK: every node in the set keeps the same
    velocity along the constrained direction(s). The set is emitted as a /GRNOD
    by _make_extra_groups, which /RLINK references by the same id."""
    if not state.constrained_node_sets:
        return []
    # The Trarot code field is the same "   TTT RRR" layout /BCS uses: a 3-digit
    # translation code (Tx Ty Tz) then a 3-digit rotation code (Rx Ry Rz) within
    # one 10-char field (a packed 6-digit code is mis-decoded by the reader).
    dof_code = {1: ("100", "000"), 2: ("010", "000"), 3: ("001", "000"),
                4: ("111", "000"), 5: ("000", "100"), 6: ("000", "010"),
                7: ("000", "001")}
    lines = ["#-  RIGID LINKS (*CONSTRAINED_NODE_SET):", HDR]
    for cns in state.constrained_node_sets:
        code = dof_code.get(cns.dof)
        if code is None:
            code = ("111", "000")
            state.warn(f"*CONSTRAINED_NODE_SET nsid={cns.nsid}: DOF={cns.dof} "
                       "unrecognized — defaulted to all three translations.")
        tra, rot = code
        if cns.tf < 1e19:
            state.warn(f"*CONSTRAINED_NODE_SET nsid={cns.nsid}: failure time "
                       f"TF={cns.tf:g} dropped (/RLINK has no failure time).")
        title = (state.node_sets.get(cns.nsid, ("", []))[0]
                 or f"CONSTRAINED_NODE_SET_{cns.nsid}")
        lines += [
            f"/RLINK/{cns.nsid}",
            title,
            "#   Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}{_i(0)}{_i(cns.nsid)}",
            HDR,
        ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: boundary conditions
# ─────────────────────────────────────────────────────────────────────────────

def _make_bcs(state: ConversionState, rbody_info: Dict) -> List[str]:
    if not state.bcs_spcs:
        return []
    lines = ["#-  BOUNDARY CONDITIONS:", HDR]
    
    node_to_ind = {}
    for pid, info in rbody_info.items():
        ind_node = info["ind_node"]
        for node in info["nodes"]:
            node_to_ind[node] = ind_node

    emitted_grnods: Set[int] = set()
    for bc in state.bcs_spcs:
        nsid = bc.nsid
        raw_nids = state.node_sets.get(nsid, ("", []))[1]

        mapped_nids = set()
        for n in raw_nids:
            if n in node_to_ind:
                mapped_nids.add(node_to_ind[n])
            else:
                mapped_nids.add(n)

        if not mapped_nids:
            state.warn(f"BCS {bc.bc_id} (nsid={nsid}): all nodes mapped to empty set – skipped")
            continue

        # *BOUNDARY_SPC CID: constraint acts in that local system → /BCS skew.
        # Only reference it when a matching /SKEW is actually emitted
        # (_make_skews writes /SKEW/<cid> for every *DEFINE_COORDINATE_*).
        skew_id = 0
        if bc.cid:
            if bc.cid in state.coord_sys or bc.cid in state.coord_nodes:
                skew_id = bc.cid
            else:
                state.warn(
                    f"BCS {bc.bc_id} (nsid={nsid}): local system cid={bc.cid} "
                    "not found — constraint applied in the GLOBAL system.")

        tra = _dof_string(bc.dofx, bc.dofy, bc.dofz)
        rot = _dof_string(bc.dofrx, bc.dofry, bc.dofrz)
        lines += [
            f"/BCS/{bc.bc_id}",
            f"BC_{bc.bc_id}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}{_i(skew_id)}{_i(nsid)}",
            HDR,
        ]
        if nsid in emitted_grnods:
            continue          # several SPC cards on one set share the /GRNOD
        emitted_grnods.add(nsid)
        set_title = state.node_sets.get(nsid, ("", []))[0]
        lines += _emit_grnod_node(nsid, set_title or f"SET_{nsid}", sorted(mapped_nids))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: grounding springs  (force-control bootstrap stabilization)
# ─────────────────────────────────────────────────────────────────────────────

# *LOAD_RIGID_BODY translational DOF (1=Fx,2=Fy,3=Fz) → global axis index.
_FORCE_DOF_AXIS = {1: 0, 2: 1, 3: 2}


def _emit_spr_gene_dof_kc(k: float, c: float = 0.0, a: float = 0.0,
                          fct: int = 0, h: int = 0,
                          dmin: float = 0.0, dmax: float = 0.0,
                          fct2: int = 0, fct3: int = 0, fct4: int = 0,
                          b: float = 0.0, d: float = 0.0, e: float = 0.0,
                          hscale: float = 0.0) -> List[str]:
    """The 3 data lines of one /PROP/TYPE8 (SPR_GENE) DOF, with stiffness K,
    viscous C, scale A, an optional force function fct (+ hardening flag H) and
    the rupture displacements DeltaMin/DeltaMax. Zero-valued A/B/D and rupture
    fields take the reader defaults (A=1, B=0, ±1e30) — the same convention the
    validated grounding-spring emitter relies on.

    The un-indexed comment header is kept (rather than the DOF-numbered one
    /PROP/TYPE13 uses) so the grounding-spring and oriented-discrete-spring
    output stays byte-identical; new 6-DOF emitters use _emit_spring_dof."""
    return [
        "#                 K                   C                   A                   B                   D",
        f"{_f(k)}{_f(c)}{_f(a)}{_f(b)}{_f(d)}",
        "#  fct_ID1         H   fct_ID2   fct_ID3   fct_ID4                      DeltaMin            DeltaMax",
        f"{_i(fct)}{_i(h)}{_i(fct2)}{_i(fct3)}{_i(fct4)}          {_f(dmin)}{_f(dmax)}",
        "#                 F                   E              Ascale              Hscale",
        f"{_f(0.0)}{_f(e)}{_f(0.0)}{_f(hscale)}",
    ]


def _emit_spr_gene_dof(k: float) -> List[str]:
    """The 3 data lines of one /PROP/TYPE8 (SPR_GENE) DOF: a linear spring with
    only the stiffness K set (C=A=B=D=0, no function, no failure).

    Layout verified against the OpenRadioss source + hm_cfg and a validated run
    (add_grounding_springs.py): the reader forces A=1,B=0 and ±1e30 failure
    displacements when no function is given, so only K matters here.
    """
    return _emit_spr_gene_dof_kc(k)


def _make_grounding_springs(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Inject soft /PROP/TYPE8 grounding springs on force-loaded rigid bodies
    (opt-in: --ground-springs). Returns [] when off → byte-identical output.

    A *LOAD_RIGID_BODY that pulls a rigid body held to ground only by
    clearance-fit penalty contact has a singular tangent in the loaded DOFs at
    t=0 (a rigid-body mode → MUMPS zero pivot / frozen residual; force control
    cannot bootstrap because load≈0 → the gap never closes → no stiffness). The
    Altair-documented fix (User Guide p.483) is a weak artificial spring on the
    free loaded DOFs: it removes the singular mode yet stays soft enough that
    contact carries the load once engaged (spring reaction ≈ k·u — a few % of
    the applied force at k=100 N/mm). Displacement control sidesteps this by
    imposing the motion; force control does not. See durable lesson #3.

    One zero-length SPR_GENE spring per loaded rigid body, from its /RBODY
    master node to a new fully-fixed ground node at the same location, with K on
    each loaded translational axis. A soft K on a DOF that is otherwise /BCS-
    constrained is inert, so spring-on-loaded-axes is safe and reproduces the
    validated RB_pull result (free Y+Z carry the pull; X stays fixed).
    """
    if not state.options.ground_springs or not state.load_rigid_bodies:
        return []

    # Union the loaded translational axes per rigid-body part (a |F| load, dof
    # 4, grounds all three; moments dof 5/6/7 are not sprung).
    axes_by_pid: Dict[int, Set[int]] = defaultdict(set)
    for lb in state.load_rigid_bodies:
        if lb.dof == 4:
            axes_by_pid[lb.pid] |= {0, 1, 2}
        elif lb.dof in _FORCE_DOF_AXIS:
            axes_by_pid[lb.pid].add(_FORCE_DOF_AXIS[lb.dof])

    if not axes_by_pid:
        return []

    k = state.options.ground_spring_k
    lines: List[str] = [
        "#-  GROUNDING SPRINGS (force-control bootstrap stabilization):", HDR]
    next_ground_node = (max(state.nodes) if state.nodes else 0) + 1
    emitted = False

    for pid, axes in sorted(axes_by_pid.items()):
        info = rbody_info.get(pid)
        if info is None:
            state.warn(
                f"--ground-springs: *LOAD_RIGID_BODY pid={pid} has no rigid body "
                "(no /RBODY master node) — grounding spring skipped."
            )
            continue
        master = info["ind_node"]
        nd = state.nodes.get(master)
        if nd is None:
            state.warn(
                f"--ground-springs: rigid body pid={pid} master node {master} has "
                "no coordinates — grounding spring skipped."
            )
            continue

        ground_node = next_ground_node
        next_ground_node += 1
        grnod_id = state.next_id()
        bcs_id = state.next_id()
        prop_id = state.next_prop_id()
        part_id = state.next_id()
        elem_id = state.next_id()
        kx = k if 0 in axes else 0.0
        ky = k if 1 in axes else 0.0
        kz = k if 2 in axes else 0.0
        axis_names = ",".join(
            n for n, on in zip("XYZ", (0 in axes, 1 in axes, 2 in axes)) if on)

        lines += [
            f"#-- master node {master}, axes {axis_names}, K={k:g} N/mm per loaded axis",
            "/NODE",
            f"{_i(ground_node)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}",
            f"/GRNOD/NODE/{grnod_id}",
            f"spring_ground_pid{pid}",
            f"{_i(ground_node)}",
            f"/BCS/{bcs_id}",
            f"fix_spring_ground_pid{pid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   111 111         0{_i(grnod_id)}",
            f"/PROP/TYPE8/{prop_id}",
            f"soft_ground_spring_pid{pid}",
            "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
            f"{_f(1.0e-4)}{_f(1.0e-6)}{_i(0) * 6}",
        ]
        # 6 DOF blocks: X Y Z RX RY RZ — K only on the loaded translational axes.
        lines += (_emit_spr_gene_dof(kx) + _emit_spr_gene_dof(ky) + _emit_spr_gene_dof(kz)
                  + _emit_spr_gene_dof(0.0) + _emit_spr_gene_dof(0.0) + _emit_spr_gene_dof(0.0))
        # Trailing strain-rate card (Fsmooth/Fcut). FORMAT(radioss2018) — the newest
        # SPR_GENE reader cfg ≤ /BEGIN-2022 — closes the /PROP/TYPE8 block with one
        # more "%10d%20lg" card (ISRATE, Asrate). Omitting it makes the reader run
        # past the property into the following /PART and raise WARNING 100217
        # ("card is missing"). Strain-rate smoothing off (ISRATE=0) → Asrate inert.
        lines += [
            "#  Fsmooth                Fcut",
            f"{_i(0)}{_f(0.0)}",
        ]
        lines += [
            f"/PART/{part_id}",
            f"soft_ground_spring_part_pid{pid}",
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{part_id}",
            "# sprg_ID  node_ID1  node_ID2",
            f"{_i(elem_id)}{_i(master)}{_i(ground_node)}",
            HDR,
        ]
        emitted = True
        state.warn(
            f"--ground-springs: injected a /PROP/TYPE8 grounding spring (K={k:g} "
            f"N/mm on axis/axes {axis_names}) from rigid-body pid={pid} master "
            f"node {master} to new fixed ground node {ground_node}. Removes the "
            "t=0 rigid-body singularity in the loaded DOFs; carries negligible "
            "load once contact engages. Remove if this is not force control "
            "through a clearance-fit contact."
        )

    return lines if emitted else []


class SpringDof:
    """One local DOF of a Radioss spring property (/PROP/TYPE4 slot 1, or one
    of the six blocks of /PROP/TYPE8 and /PROP/TYPE13).

    The three cards are byte-identical across all three properties (and across
    /MAT/LAW108 and /MAT/LAW113, whose bodies are the same blocks with RHO in
    place of Mass), so ONE payload object drives every spring emitter:

        K  C  A  B  D
        fct_ID1  H  fct_ID2  fct_ID3  fct_ID4  <10 blanks>  DeltaMin  DeltaMax
        F  E  Ascale  Hscale

    Force law (redef3.F90:1140-1148):
        F = f(δ)·[A + B·ln(max(1,|δ̇/D|)) + E·g(δ̇)] + C·δ̇ + Hscale·h(δ̇)
    with f = fct_ID1 (loading), g = fct_ID2 (rate scale), fct_ID3 the unloading
    curve used by H = 4/5/6/7/9, and h = fct_ID4 (extra damping force).

    ⚠ ``A`` is NOT a free scale factor on a PROPERTY-driven spring: the readers
    store the stiffness as ``K / A`` (hm_read_prop04.F:249, hm_read_prop08.F:282
    and hm_read_prop13.F:295, once per DOF), which exactly cancels the ``·A`` the
    engine applies in the no-function branch. /MAT/LAW108 and /MAT/LAW113 store
    XK raw (hm_read_mat108.F:271) and do NOT cancel. So dyna2rad's
    ``A1 = 1e-20`` trick for *MAT_S04's LCR (convertprops.cxx:974) is a LAW108-
    only device — writing it on a TYPE4/8/13 would multiply the time-step
    stiffness by 1e20 and collapse dt at cycle 0. Leave A at 0 (→ reader default
    1.0) unless the force really is scaled, and then pre-multiply K by A so the
    stored K/A is the true tangent.
    """

    __slots__ = ("k", "c", "a", "b", "d", "fct1", "h", "fct2", "fct3", "fct4",
                 "dmin", "dmax", "f", "e", "ascale", "hscale")

    def __init__(self, k: float = 0.0, c: float = 0.0, a: float = 0.0,
                 b: float = 0.0, d: float = 0.0, fct1: int = 0, h: int = 0,
                 fct2: int = 0, fct3: int = 0, fct4: int = 0,
                 dmin: float = 0.0, dmax: float = 0.0, f: float = 0.0,
                 e: float = 0.0, ascale: float = 0.0, hscale: float = 0.0):
        self.k, self.c, self.a, self.b, self.d = k, c, a, b, d
        self.fct1, self.h, self.fct2, self.fct3, self.fct4 = \
            fct1, h, fct2, fct3, fct4
        self.dmin, self.dmax = dmin, dmax
        self.f, self.e, self.ascale, self.hscale = f, e, ascale, hscale


def _as_spring_dof(dof) -> SpringDof:
    """Accept a SpringDof or the legacy ``(k, fct, h, dmin, dmax)`` 5-tuple the
    spotweld connectors pass — the tuple form maps onto a SpringDof whose other
    fields are all 0, i.e. byte-identical output."""
    if isinstance(dof, SpringDof):
        return dof
    k, fct, h, dmin, dmax = dof
    return SpringDof(k=k, fct1=fct, h=h, dmin=dmin, dmax=dmax)


def _emit_spring_dof(i: int, dof) -> List[str]:
    """The 6 lines (3 comments + 3 data cards) of spring DOF block *i* (1..6).

    Column layout is identical for /PROP/TYPE8, /PROP/TYPE13, /MAT/LAW108 and
    /MAT/LAW113: %20lg x5, then %10d x5 + 10 blanks + %20lg x2, then %20lg x4.
    Cols 51-60 of the middle card MUST stay blank at /BEGIN 2022 — they only
    become ``fct_ID5i`` at radioss2023."""
    d = _as_spring_dof(dof)
    return [
        f"#                 K{i}                  C{i}                  A{i}                  B{i}                  D{i}",
        f"{_f(d.k)}{_f(d.c)}{_f(d.a)}{_f(d.b)}{_f(d.d)}",
        f"# fct_ID1{i}        H{i}  fct_ID2{i}  fct_ID3{i}  fct_ID4{i}                     DeltaMin{i}           DeltaMax{i}",
        f"{_i(d.fct1)}{_i(d.h)}{_i(d.fct2)}{_i(d.fct3)}{_i(d.fct4)}          {_f(d.dmin)}{_f(d.dmax)}",
        f"#                 F{i}                  E{i}             Ascale{i}             Hscale{i}",
        f"{_f(d.f)}{_f(d.e)}{_f(d.ascale)}{_f(d.hscale)}",
    ]


def _emit_prop_type4(prop_id: int, title: str, mass: float, k: float, c: float,
                     a: float, fct1: int, hflag: int,
                     dmin: float, dmax: float, fct2: int = 0, fct3: int = 0,
                     fct4: int = 0, b: float = 0.0, d: float = 0.0,
                     e: float = 0.0, hscale: float = 0.0) -> List[str]:
    """/PROP/TYPE4 (SPRING). Layout: prop_p4_spring.cfg FORMAT(radioss140), the
    newest TYPE4 reader format ≤ /BEGIN-2022. Zero-valued A/B/D and rupture
    displacements take the reader defaults (A=1, B=0, D=1, ±1e30) — same
    convention the validated TYPE8 grounding-spring emitter relies on.

    The optional fct_ID21/31/41 + B/D/E/Hscale arguments carry the rate,
    unloading and damping-function slots the S03/S05/S06/S08 spring materials
    need; leaving them at their defaults reproduces the original card exactly.
    """
    return [
        f"/PROP/TYPE4/{prop_id}",
        title,
        "#               MASS                                 sens_ID    Isflag     Ileng",
        f"{_f(mass)}{' ' * 30}{_i(0)}{_i(0)}{_i(0)}",
        "#                  K                   C                   A                   B                   D",
        f"{_f(k)}{_f(c)}{_f(a)}{_f(b)}{_f(d)}",
        "# fct_ID11        H1  fct_ID21  fct_ID31  fct_ID41                      DeltaMin            DeltaMax",
        f"{_i(fct1)}{_i(hflag)}{_i(fct2)}{_i(fct3)}{_i(fct4)}          {_f(dmin)}{_f(dmax)}",
        "#                 F1                  E1             AScale1             HScale1",
        f"{_f(0.0)}{_f(e)}{_f(0.0)}{_f(hscale)}",
        HDR,
    ]


def _emit_prop_type8(prop_id: int, title: str, mass: float, inertia: float,
                     skew_id: int, dofs, ifail: int = 0, ifail2: int = 0,
                     iequil: int = 0) -> List[str]:
    """/PROP/TYPE8 (SPR_GENE). Layout: prop_p8_spr_gene.cfg FORMAT(radioss2018).

    Card 1 is ``Mass I skew_ID sens_ID Isflag Ifail Ifail2 Iequil`` — note the
    order differs from /PROP/TYPE13's ``… Ifail Ileng Ifail2``, and that TYPE8
    accepts Ifail2 ∈ {1,2} only (hm_read_prop08.F:150 forces anything else to 0;
    there is no energy criterion here).

    This is the SKEW-oriented 6-DOF spring: r2buf3.F builds the local triad
    entirely from the skew (per-element /SPRING Skew_ID first, else the property
    skew_ID, else global). It is the property-driven twin of /PROP/TYPE23 +
    /MAT/LAW108, with an absolute Mass in place of RHO×Volume.
    """
    lines = [
        f"/PROP/TYPE8/{prop_id}",
        title,
        "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
        f"{_f(mass)}{_f(inertia)}{_i(skew_id)}{_i(0)}{_i(0)}{_i(ifail)}{_i(ifail2)}{_i(iequil)}",
    ]
    for i, dof in enumerate(dofs, start=1):
        lines += _emit_spring_dof(i, dof)
    lines += [
        "#  Fsmooth                Fcut",
        f"{_i(0)}{_f(0.0)}",
        HDR,
    ]
    return lines


def _emit_prop_type13(prop_id: int, title: str, mass: float, inertia: float,
                      ifail: int, ifail2: int, dofs, ileng: int = 0,
                      skew_id: int = 0) -> List[str]:
    """/PROP/TYPE13 (SPR_BEAM). Layout: prop_p13_spr_beam.cfg
    FORMAT(radioss2018), the newest TYPE13 reader format ≤ /BEGIN-2022.
    ``dofs`` is 6 SpringDof (or legacy ``(k, fct_id, hflag, dmin, dmax)``
    tuples) for Tx Ty Tz Rx Ry Rz.
    With Ifail2=2 the DeltaMin/DeltaMax fields are failure FORCES (moments on
    the rotational DOFs); zero-valued fields take the ±1e30 'no failure'
    reader defaults.

    This is the NODE-oriented 6-DOF spring: r4buf3.F sets local X along
    node_ID1→node_ID2 and takes the XY plane from node_ID3 (falling back to the
    property skew's Y′). It is the property-driven twin of /PROP/TYPE23 +
    /MAT/LAW113. ``Ileng=1`` makes K, the input curves and the failure limits
    per unit length (strain based) — what *MAT_CABLE_DISCRETE_BEAM needs."""
    lines = [
        f"/PROP/TYPE13/{prop_id}",
        title,
        "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail     Ileng    Ifail2",
        f"{_f(mass)}{_f(inertia)}{_i(skew_id)}{_i(0)}{_i(0)}{_i(ifail)}{_i(ileng)}{_i(ifail2)}",
    ]
    for i, dof in enumerate(dofs, start=1):
        lines += _emit_spring_dof(i, dof)
    lines += [
        "#                 Vo                  Wo                Fcut   Fsmooth",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
    ]
    for i in range(1, 7):
        lines += [
            f"#                 c{i}                  n{i}              alpha{i}               beta{i}",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        ]
    lines.append(HDR)
    return lines


def _pts_slope_at_origin(pts) -> float:
    """Slope of the segment spanning (or nearest to) the origin of a raw point
    list — the stiffness a nonlinear spring's force function implies there."""
    pts = sorted((float(a), float(o)) for a, o in pts)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x2 > x1 and x1 <= 0.0 <= x2:
            return (y2 - y1) / (x2 - x1)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x2 > x1:
            return (y2 - y1) / (x2 - x1)
    return 0.0


def _curve_slope_at_origin(curve: Curve) -> float:
    """Slope of the curve segment spanning (or nearest to) the origin — used as
    the /PROP/TYPE4 K (unloading / time-step stiffness) for a nonlinear
    spring's force-displacement function."""
    return _pts_slope_at_origin(curve.pts)


def _mirror_one_sided_curve(pts, tension_only: bool):
    """Mirror a ONE-SIDED force-displacement curve into the opposite quadrant.

    ``*MAT_SPRING_INELASTIC`` (S08) defines LCFD in the POSITIVE quadrant only
    whatever the tension/compression sense; CTF picks the sense. Radioss reads a
    spring function over the full displacement range and extrapolates the end
    segments, so a positive-only curve on a compression-only spring would invent
    a tensile force. dyna2rad's ``HandleCurveLCFD`` (convertprops.cxx:1066-1128)
    is reproduced here: an already two-quadrant curve is left alone, otherwise

      * ``CTF = -1`` (tension only)  → prepend ``(-1, 0)``: zero force in
        compression, the given branch in tension;
      * ``CTF = +1`` (compression only, the LS-DYNA default) → reflect the
        branch through the origin (x,y → -x,-y, order reversed) and close it off
        with ``(+1, 0)``.

    Returns the new point list; ``[]`` when the input cannot be used.
    """
    pts = sorted((float(a), float(o)) for a, o in pts)
    if len(pts) < 2:
        return []
    if pts[0][0] < 0.0:
        return pts                      # already spans both quadrants
    if tension_only:
        # Keep the positive branch; a flat zero-force point one unit into
        # compression makes the extrapolated compressive force zero.
        head = [(-1.0, 0.0)]
        if pts[0][0] > 0.0:
            head.append((0.0, 0.0))
        return head + pts
    # Compression only: reflect the branch through the origin, then close it
    # off with a flat zero-force point one unit into tension.
    out = [(-a, -o) for a, o in reversed(pts)]
    if out[-1][0] < 0.0:
        out.append((0.0, 0.0))
    return out + [(1.0, 0.0)]


def _plastic_to_total_disp(pts, stiff: float):
    """LS-DYNA PLASTIC-displacement abscissa → Radioss TOTAL displacement.

    ``*MAT_068``'s LCPD*/LCPM* curves and ``*MAT_196``'s TYPE≠0 FLCID give the
    yield force against the PLASTIC deformation; a Radioss spring function is
    read against the TOTAL deformation, so every abscissa gains the elastic part
    ``F/K`` (dyna2rad ``ConvertPlasticDispPointsTotalDisp``,
    convertmats.cxx:8862-8921). The curve is then mirrored through the origin so
    the spring yields symmetrically in compression, which is what LS-DYNA does
    for a one-sided plastic curve.

    Returns ``[]`` when *stiff* is zero (no elastic branch to add) or the curve
    is unusable, so the caller can warn instead of emitting nonsense.
    """
    pts = [(float(a), float(o)) for a, o in pts]
    if len(pts) < 2 or stiff == 0.0:
        return []
    pts.sort()
    if any(a < 0.0 for a, _ in pts):
        # Already a two-quadrant curve: keep the positive half only, so the
        # mirroring below stays symmetric (dyna2rad:8866-8883 does the same).
        pts = [p for p in pts if p[0] >= 0.0]
        if len(pts) < 2:
            return []
    total = []
    for a, o in pts:
        x = a + o / stiff
        if total and x <= total[-1][0]:
            # Non-monotonic after the elastic shift: a Radioss function must
            # have strictly increasing abscissae, so nudge past the previous
            # point.
            prev = total[-1][0]
            x = prev + max(_PLASTIC_CURVE_EPS, abs(prev) * _PLASTIC_CURVE_REL)
        total.append((x, o))
    if total[0][0] > 0.0:
        total.insert(0, (0.0, 0.0))
    return [(-a, -o) for a, o in reversed(total) if a != 0.0] + total


#: Abscissa nudge that keeps a plastic→total curve strictly increasing
#: (dyna2rad hard-codes 0.01 at convertmats.cxx:8892, a unit-dependent magic
#: number). The step has to survive ``_f``'s %.10G card field, so it is RELATIVE
#: to the running abscissa with an absolute floor: 1e-9 alone vanishes at
#: |x| >= 10 (``_f(20.0)`` and ``_f(20.0 + 1e-9)`` are both "20"), which would
#: put a DUPLICATE abscissa on the card and earn starter ERROR 156. 1e-7
#: relative is two decades above the ten-significant-digit resolution and still
#: far below any meaningful deformation.
_PLASTIC_CURVE_EPS = 1.0e-9
_PLASTIC_CURVE_REL = 1.0e-7


def _curve_max_slope(curve: Curve) -> float:
    """The largest |secant slope| of a force-displacement function.

    ``hm_read_prop04.F``'s companion check (starter WARNING 506, "STIFFNESS
    VALUE IS NOT CONSISTENT WITH THE MAXIMUM SLOPE OF THE YIELD FUNCTION - THE
    STIFFNESS VALUE IS CHANGED") compares the spring's K against exactly this
    number and RAISES K itself when it is smaller. On an elastic-plastic spring
    (H != 0) K is the unloading stiffness, so letting the starter pick it means
    shipping a card whose physics is decided downstream — better to state it."""
    pts = sorted(curve.pts)
    best = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x2 > x1:
            best = max(best, abs((y2 - y1) / (x2 - x1)))
    return best


def _finite_length(state: ConversionState, e) -> bool:
    """True when a 2-node connector element has two REAL, distinct nodes — the
    precondition for any node-oriented frame (r4buf3.F builds local X from
    node1→node2 and answers WARNING 325 when it cannot). A grounded element
    (N2=0) fails it: its synthesized ground node sits on top of N1."""
    return _element_length(state, e) > 1e-12


def _element_length(state: ConversionState, e) -> float:
    """Distance between a 2-node connector element's nodes; 0 when either end
    is missing or the element is grounded (N2=0)."""
    if e.n1 <= 0 or e.n2 <= 0:
        return 0.0
    a, b = state.nodes.get(e.n1), state.nodes.get(e.n2)
    if a is None or b is None:
        return 0.0
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2
            + (a.z - b.z) ** 2) ** 0.5


#: Artificial mass every discrete-spring connector property carries. LS-DYNA's
#: discrete elements are massless (nodal mass comes from *ELEMENT_MASS) but
#: hm_read_prop04.F:136 rejects MASS <= 1e-15 outright (ERROR 229), and the
#: explicit time step needs a finite one.
_SPRING_TOKEN_MASS = 1.0e-4


def _connector_inertia(state: ConversionState, elems) -> float:
    """The rotational inertia written on a synthesized 6-DOF spring property.

    ``rinit3.F:427-437`` measures every /PROP/TYPE8, /TYPE13 and /TYPE25 spring
    against ``RATIO = Mass·L²`` and answers WARNING 432 outside a factor of
    1000 either way, so an inertia k2rad invents should BE that reference
    rather than a fixed token: with the 1e-4 spring mass, a flat 1e-6 already
    trips the check at any element longer than ~3.2 length units. TYPE8 skips
    the check for zero-length elements only (``.NOT.((IGTYP == 8).AND.
    (LENGTH < EM15))``), which is exactly the grounded-spring case the 1e-20
    floor covers."""
    lens = [x for x in (_element_length(state, e) for e in elems) if x > 0.0]
    l_mean = (sum(lens) / len(lens)) if lens else 1.0
    return max(_SPRING_TOKEN_MASS * l_mean * l_mean, 1.0e-20)


def _emit_inert_spring_part(state: ConversionState, pid: int, title: str,
                            reason: str) -> List[str]:
    """An inert /PROP/TYPE4 + /PART for a discrete-spring part whose elements
    could not be converted.

    ``_discrete_part_ids`` claims the part unconditionally, so the ordinary
    /PART emitter skips it — dropping it here would delete the /PART id along
    with every *SET_PART member, /GRNOD/PART scope, contact and /TH channel
    that names it. The sibling discrete-BEAM writer guards the same hazard the
    same way (dbeam.py's ``wrong_section`` branch)."""
    state.warn(
        f"*ELEMENT_DISCRETE part {pid}: {reason} An INERT /PROP/TYPE4 + "
        f"/PART/{pid} (zero stiffness, token mass, no /SPRING) was written in "
        "its place so the part id stays addressable — a *SET_PART member, a "
        "/GRNOD/PART scope or a contact that names it would otherwise dangle.")
    prop_id = state.next_prop_id()
    return _emit_prop_type4(
        prop_id, f"{title} (inert - not converted)", _SPRING_TOKEN_MASS,
        0.0, 0.0, 0.0, 0, 0, 0.0, 0.0) + [
        f"/PART/{pid}",
        title,
        f"{_i(prop_id)}{_i(0)}{_i(0)}",
        HDR,
    ]


def _new_ground_node(state: ConversionState, at: NodeData) -> int:
    """Synthesize a fully-fixed ground node at *at*'s coordinates. Registered in
    state.nodes so later id allocations (e.g. --ground-springs) cannot collide,
    and in state.connector_ground_nodes so the implicit free-node guard skips
    it (it is already /BCS-fixed by the caller)."""
    nid = (max(state.nodes) + 1) if state.nodes else 90000001
    state.nodes[nid] = NodeData(at.x, at.y, at.z)
    state.connector_ground_nodes.add(nid)
    return nid


def _emit_spring_part(state: ConversionState, part_id: int, prop_id: int,
                      title: str, g_elems, pid: int,
                      spring_kind_label: str = "TYPE4") -> List[str]:
    """Emit /PART + /SPRING for a group of discrete elements on *prop_id*,
    synthesizing a fixed ground node (+ /BCS 111 111) for each grounded element
    (N2=0). Shared by the axial /PROP/TYPE4 and the oriented /PROP/TYPE8 paths."""
    lines = [
        f"/PART/{part_id}",
        title,
        f"{_i(prop_id)}{_i(0)}{_i(0)}",
        f"/SPRING/{part_id}",
        "# sprg_ID  node_ID1  node_ID2",
    ]
    ground_nodes: List[int] = []
    for e in g_elems:
        n1, n2 = e.n1, e.n2
        if n1 <= 0 or n2 <= 0:
            anchor = n1 if n1 > 0 else n2
            nd = state.nodes.get(anchor)
            if nd is None:
                state.warn(f"*ELEMENT_DISCRETE {e.eid}: grounded "
                           f"element's node {anchor} has no "
                           "coordinates — element skipped.")
                continue
            gnid = _new_ground_node(state, nd)
            ground_nodes.append(gnid)
            n1, n2 = anchor, gnid
        lines.append(f"{_i(e.eid)}{_i(n1)}{_i(n2)}")
        # Recorded at the line that writes it, not from g_elems: the `continue`
        # just above drops a grounded element whose anchor node has no
        # coordinates, and *DATABASE_DEFORC must list only ids that reached the
        # deck (a /TH/SPRING on a missing element is starter ERROR 69).
        state.discrete_spring_eids.add(e.eid)
    lines.append(HDR)
    if ground_nodes:
        grnod_id = state.next_id()
        bcs_id = state.next_id()
        lines.append("/NODE")
        for gnid in ground_nodes:
            nd = state.nodes[gnid]
            lines.append(f"{_i(gnid)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}")
        lines += _emit_grnod_node(grnod_id,
                                  f"discrete_ground_pid{pid}",
                                  ground_nodes)
        lines += [
            f"/BCS/{bcs_id}",
            f"fix_discrete_ground_pid{pid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   111 111         0{_i(grnod_id)}",
            HDR,
        ]
        state.warn(f"*ELEMENT_DISCRETE part {pid}: {len(ground_nodes)} "
                   "grounded element(s) (N2=0) tied to new fully-fixed "
                   "ground node(s) at the attached node's coordinates "
                   f"(zero-length {spring_kind_label} spring = central "
                   "restoring force toward the anchor point).")
    return lines


def _card_value(v: float) -> float:
    """The number the starter reads back from a ``_f`` field.

    ``_f`` prints %.10G (or %.6E outside 1e-4 .. 1e15), so the card carries ten
    significant digits — anything finer than that is invented precision that
    only exists in the converter."""
    return float(_f(v))


def _monotonic_abscissae(pts):
    """Force a /FUNCT point list to be strictly increasing AS PRINTED.

    ``hm_read_funct.F:143`` refuses a function whose abscissa does not grow —
    ``IF (PLD(NPC(L+1)) <= PLD(NPC(L+1)-2)) ... MSGID = 156`` (MSGERROR), i.e.
    the deck is rejected, not degraded. The comparison the starter makes is on
    the CARD value, so the invariant has to be checked on ``_f``'s output and
    not on the float: a tie-break below the ten-digit field resolution survives
    in memory and disappears on the card.

    This is a last-resort guard — every builder that can produce a tie (the
    plastic→total mapping, the cable's zero-crossing insertion) breaks it with a
    step of its own. Points that are already strictly increasing are returned
    unchanged, so the emitted card is byte-identical for every well-formed
    curve."""
    out = []
    for a, o in pts:
        x = float(a)
        if out:
            prev = _card_value(out[-1][0])
            step = max(abs(prev), 1.0) * 1.0e-8
            for _ in range(64):
                if _card_value(x) > prev:
                    break
                x = prev + step
                step *= 2.0
        out.append((x, float(o)))
    return out


def _emit_funct(fid: int, title: str, pts) -> List[str]:
    """A /FUNCT written INLINE in a connector section.

    The single /FUNCT emitter (materials.py::_make_functions) runs at the
    "functions" step, which is BEFORE every connector step in the writer
    dispatch, so a curve registered in state.curves from here would never reach
    the deck. Connector-synthesized functions are therefore written where they
    are built — the same thing the spotweld bilinear-axial function does."""
    lines = [f"/FUNCT/{fid}", title[:100],
             "#                  X                   Y"]
    for a, o in _monotonic_abscissae(pts):
        lines.append(f"{_f(a)}{_f(o)}")
    lines.append(HDR)
    return lines


def _s03_curve_points(k: float, kt: float, fy: float):
    """The 5-point symmetric elastic-plastic force function of *MAT_S03.

    dyna2rad (convertprops.cxx:923) synthesizes

        (-(FY/K + 1), -(FY + KT))  (-FY/K, -FY)  (0,0)  (FY/K, FY)
        (FY/K + 1, FY + KT)

    i.e. an elastic branch of slope K up to the yield force FY, then a plastic
    branch of slope KT carried ONE displacement unit past yield (Radioss
    extrapolates the last segment, so the branch continues at slope KT beyond
    it). Returns [] when the card cannot produce a usable curve."""
    if k <= 0.0 or fy <= 0.0:
        return []
    dy = fy / k
    return [(-(dy + 1.0), -(fy + kt)), (-dy, -fy), (0.0, 0.0),
            (dy, fy), (dy + 1.0, fy + kt)]


def _make_discrete_springs(state: ConversionState) -> List[str]:
    """*ELEMENT_DISCRETE + *SECTION_DISCRETE + a discrete spring/damper material
    → /PROP/TYPE4 (SPRING) + /PART + /SPRING.

    Materials: ``*MAT_SPRING_ELASTIC`` (S01), ``*MAT_SPRING_ELASTOPLASTIC``
    (S03), ``*MAT_SPRING_NONLINEAR_ELASTIC`` (S04),
    ``*MAT_DAMPER_NONLINEAR_VISCOUS`` (S05),
    ``*MAT_SPRING_GENERAL_NONLINEAR`` (S06), ``*MAT_SPRING_INELASTIC`` (S08) and
    ``*MAT_DAMPER_VISCOUS`` (S02). Every one of them is a 1-DOF connector and
    lands in the single DOF block of a /PROP/TYPE4, which carries the full
    Radioss spring law — loading function, hardening flag, rate function,
    unloading function, damping function and the rupture displacements — so no
    /MAT is written and the /PART keeps mat_id 0.

    dyna2rad instead pairs an (initially empty) /MAT/LAW108 with a /PROP/TYPE23
    and fills the stiffness in from the property pass; the card BODY is the same
    six DOF blocks either way, and the property-driven route avoids TYPE23's
    "a /PART on it must carry a MID whose law is 108/113/114/135" rule
    (hm_read_part.F, ERROR 179 / ERROR 1715).

    A grounded element (N2=0) gets a fixed ground node at N1's coordinates +
    /BCS 111 111 (the _make_grounding_springs pattern); the zero-length TYPE4
    spring then acts as a central restoring force F=K·|d| toward the anchor —
    TYPE4 explicitly allows zero-length springs.

    A DRO=1 (torsional) section puts the same payload on the ROTATIONAL DOF of a
    6-DOF property instead: /PROP/TYPE13 slot 4 (Rx = torsion about the element's
    own n1→n2 axis) for an unoriented spring, /PROP/TYPE8 slot 4 for one carrying
    a *DEFINE_SD_ORIENTATION. LS-DYNA already states a DRO=1 spring in
    moment-per-radian, which is exactly what the Radioss rotational slot wants,
    so no unit conversion applies — only the DOF changes.

    A part whose material, curve or elements cannot be converted still gets an
    INERT /PROP/TYPE4 + /PART (``_emit_inert_spring_part``): the pid is claimed
    by ``_discrete_part_ids`` either way, so dropping it would delete the /PART
    id from under every *SET_PART member, /GRNOD/PART scope, contact and /TH
    channel that names it."""
    if not state.discrete_elems:
        return []
    lines: List[str] = [
        "#-  DISCRETE SPRING/DAMPER CONNECTORS (*ELEMENT_DISCRETE -> /PROP/TYPE4 + /SPRING):",
        HDR]
    emitted = False

    by_pid: Dict[int, List] = defaultdict(list)
    for e in state.discrete_elems:
        by_pid[e.pid].append(e)

    for pid in sorted(by_pid):
        elems = by_pid[pid]
        part = state.parts.get(pid)
        if part is None:
            state.warn(f"*ELEMENT_DISCRETE: part {pid} is not defined — "
                       f"{len(elems)} discrete element(s) skipped.")
            continue
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_discrete.get(secid)
        if sec is None:
            state.warn(f"*ELEMENT_DISCRETE part {pid}: no *SECTION_DISCRETE "
                       f"{secid} found — a default translational section is "
                       "assumed (no failure deflection).")
            sec = SectionDiscrete(secid, "")
        torsional = sec.dro == 1
        title = part.title or f"DISCRETE_{pid}"

        # Material → the single spring DOF (K / C / A / B / D, fct_ID1..4, H).
        k = c = 0.0
        b_coef = d_coef = e_coef = hscale = 0.0
        fct1 = fct2 = fct3 = fct4 = 0
        hflag = 0
        kind = None
        funct_lines: List[str] = []
        mat_lin = state.mat_spring_elastic.get(part.mid)
        mat_nl = state.mat_spring_nonlinear.get(part.mid)
        mat_dmp = state.mat_damper_viscous.get(part.mid)
        mat_ep = state.mat_spring_elastoplastic.get(part.mid)
        mat_nlv = state.mat_damper_nl_viscous.get(part.mid)
        mat_gnl = state.mat_spring_general_nl.get(part.mid)
        mat_inel = state.mat_spring_inelastic.get(part.mid)
        if mat_lin is not None:
            k = mat_lin.k
            kind = "linear spring"
        elif mat_nl is not None:
            curve = state.curves.get(mat_nl.lcd)
            if curve is None or len(curve.pts) < 2:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_NONLINEAR_ELASTIC {part.mid}'s load curve "
                    f"LCD={mat_nl.lcd} is not defined, so its {len(elems)} "
                    "element(s) carry no force at all.")
                emitted = True
                continue
            fct1 = mat_nl.lcd            # curve is already emitted as /FUNCT
            hflag = 0                    # H=0: nonlinear ELASTIC (S04 semantics)
            k = _curve_slope_at_origin(curve)
            if k <= 0.0:
                state.warn(f"*MAT_SPRING_NONLINEAR_ELASTIC {part.mid}: LCD "
                           f"{mat_nl.lcd} has a non-positive slope at the "
                           "origin — TYPE4 K left 0 (engine time-step/unloading "
                           "stiffness); verify the curve.")
                k = 0.0
            if mat_nl.lcr:
                # LS-DYNA S04 is F = LCD(δ)·LCR(δ̇). The Radioss spring law is
                # F = f(δ)·[A + B·ln(…) + E·g(δ̇)] + …, so an exact match needs
                # A = 0 and E = 1 — and A = 0 is re-defaulted to 1 by the
                # reader, giving f·(1 + g). dyna2rad dodges that with A = 1e-20
                # (convertprops.cxx:974), which is only legal on /MAT/LAW108:
                # the PROPERTY readers store the stiffness as K/A
                # (hm_read_prop04.F:249), so A = 1e-20 would multiply the
                # time-step stiffness by 1e20 and collapse dt at cycle 0.
                state.warn(f"*MAT_SPRING_NONLINEAR_ELASTIC {part.mid}: rate "
                           f"scale curve LCR={mat_nl.lcr} has no /PROP/TYPE4 "
                           "slot that reproduces F=LCD(d)*LCR(d/dt) — the "
                           "spring is converted RATE-INDEPENDENT (F=LCD(d)). "
                           "The A=1e-20 trick dyna2rad uses is a /MAT/LAW108 "
                           "device: a property-driven spring stores K/A, so it "
                           "would blow up the time step. Fold the rate scale "
                           "into LCD if it matters.")
            kind = "nonlinear elastic spring"
        elif mat_ep is not None:
            pts = _s03_curve_points(mat_ep.k, mat_ep.kt, mat_ep.fy)
            if not pts:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_ELASTOPLASTIC {part.mid} states K="
                    f"{mat_ep.k:g}/FY={mat_ep.fy:g}, and both must be positive "
                    "to place the yield point (the elastic branch is FY/K "
                    f"wide), so its {len(elems)} element(s) carry no force.")
                emitted = True
                continue
            fct1 = state.next_curve_id()
            funct_lines = _emit_funct(
                fct1, f"MATS03_elastoplastic_mid{part.mid}", pts)
            k = mat_ep.k
            hflag = 1                    # isotropic hardening, unloads along K
            kind = "elastoplastic spring"
        elif mat_nlv is not None:
            if not mat_nlv.lcdr or mat_nlv.lcdr not in state.curves:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_DAMPER_NONLINEAR_VISCOUS {part.mid}'s force-vs-rate "
                    f"curve LCDR={mat_nlv.lcdr} is not defined, so its "
                    f"{len(elems)} element(s) carry no damping force.")
                emitted = True
                continue
            # fct_ID41 is h(δ̇), added to the force as Hscale·h(δ̇) — exactly
            # LS-DYNA's F = LCDR(δ̇). Hscale = 0 takes the reader default 1.0.
            fct4 = mat_nlv.lcdr
            kind = "nonlinear viscous damper"
        elif mat_gnl is not None:
            if not mat_gnl.lcdl or mat_gnl.lcdl not in state.curves:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_GENERAL_NONLINEAR {part.mid}'s loading curve "
                    f"LCDL={mat_gnl.lcdl} is not defined, so its {len(elems)} "
                    "element(s) carry no force.")
                emitted = True
                continue
            fct1 = mat_gnl.lcdl
            # H=6 makes K1 the UNLOADING stiffness, and the starter refuses to
            # let it be smaller than the loading curve's steepest segment: it
            # raises it silently under WARNING 506. State it instead, so the
            # hysteresis loop the deck runs is the one the card says.
            k = _curve_max_slope(state.curves[mat_gnl.lcdl])
            if mat_gnl.lcdu and mat_gnl.lcdu in state.curves:
                fct3 = mat_gnl.lcdu
                hflag = 6                # iso. hardening + nonlinear unloading
            else:
                # H=6 with fct_ID31 = 0 is a hard starter ERROR 1057
                # (hm_read_prop04.F:171). Demote rather than emit a deck that
                # cannot start.
                hflag = 0
                state.warn(f"*MAT_SPRING_GENERAL_NONLINEAR {part.mid}: "
                           f"LCDU={mat_gnl.lcdu} (the unloading curve) is "
                           "missing, and H=6 without fct_ID31 is starter ERROR "
                           "1057 — the spring was DEMOTED to H=0 (nonlinear "
                           "ELASTIC: it unloads along the loading curve and "
                           "dissipates nothing). Supply LCDU to keep the "
                           "hysteresis.")
            # BETA is tested against 1.0, NOT against 0: LS-DYNA's BLANK
            # default BETA=0.0 selects "tensile and compressive yield with
            # strain SOFTENING" and any other non-unit value selects KINEMATIC
            # hardening (Manual Vol II R17 p.2-2087) — both differ from the
            # isotropic H=6 that is emitted. BETA=1.0 is the one value that
            # matches it exactly, so it is the one value that must stay silent.
            dropped = [n for n, v in (("TYI", mat_gnl.tyi),
                                      ("CYI", mat_gnl.cyi)) if v]
            if mat_gnl.beta != 1.0:
                dropped.insert(0, f"BETA={mat_gnl.beta:g}")
            if dropped:
                state.warn(f"*MAT_SPRING_GENERAL_NONLINEAR {part.mid}: "
                           f"{', '.join(dropped)} have no Radioss spring slot "
                           "— dropped. BETA selects LS-DYNA's hardening "
                           "flavour (0.0, the BLANK DEFAULT = tensile and "
                           "compressive yield with strain softening; 1.0 = "
                           "isotropic; anything else = kinematic) and TYI/CYI "
                           "the initial tensile/compressive yield; the "
                           "converted spring always uses the ISOTROPIC rule "
                           "H=6 with the yield taken from the loading curve. "
                           "Radioss's kinematic flag H=4 is not an option — "
                           "hm_read_prop04.F:157 rejects it outright when K=0 "
                           "and LAW108 rejects it unconditionally (ERROR 230).")
            kind = "general nonlinear spring"
        elif mat_inel is not None:
            curve = state.curves.get(mat_inel.lcfd)
            if curve is None or len(curve.pts) < 2:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_INELASTIC {part.mid}'s force-vs-displacement "
                    f"curve LCFD={mat_inel.lcfd} is not defined, so its "
                    f"{len(elems)} element(s) carry no force.")
                emitted = True
                continue
            pts = _mirror_one_sided_curve(curve.pts, mat_inel.ctf < 0.0)
            if not pts:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_INELASTIC {part.mid}'s LCFD "
                    f"{mat_inel.lcfd} could not be mirrored into the opposite "
                    f"quadrant, so its {len(elems)} element(s) carry no force.")
                emitted = True
                continue
            fct1 = state.next_curve_id()
            side = "tension" if mat_inel.ctf < 0.0 else "compression"
            funct_lines = _emit_funct(
                fct1, f"MATS08_{side}_only_mid{part.mid}", pts)
            k = mat_inel.ku
            if k > 0.0:
                # LS-DYNA S08 unloads along max(KU, max loading slope) — that
                # is precisely Radioss H=1 (elastic-plastic, unloading with K).
                # dyna2rad leaves H at 0 here (convertprops.cxx:1000-1028),
                # which silently turns the INELASTIC spring into a nonlinear
                # ELASTIC one that dissipates nothing; k2rad sets the flag.
                hflag = 1
            else:
                state.warn(f"*MAT_SPRING_INELASTIC {part.mid}: KU (the "
                           "unloading stiffness) is blank, so there is no "
                           "slope to unload along — the spring is converted "
                           "as nonlinear ELASTIC (H=0) and dissipates NO "
                           "energy. Give KU to keep the inelastic loop.")
            state.warn(f"*MAT_SPRING_INELASTIC {part.mid}: LCFD "
                       f"{mat_inel.lcfd} is one-sided (CTF={mat_inel.ctf:g} = "
                       f"{side} only), so it was mirrored into the opposite "
                       f"quadrant and closed off with a flat zero-force point "
                       f"-> /FUNCT/{fct1} ({len(pts)} points). Radioss reads a "
                       "spring function over the whole displacement range and "
                       "extrapolates its end segments, so an unmirrored curve "
                       "would invent force on the inactive side.")
            kind = "inelastic spring"
        elif mat_dmp is not None:
            c = mat_dmp.dc
            kind = "viscous damper"
        else:
            lines += _emit_inert_spring_part(
                state, pid, title,
                f"material {part.mid} is not a discrete spring/damper material "
                "k2rad converts (S01/S02/S03/S04/S05/S06/S08), so its "
                f"{len(elems)} element(s) carry no force.")
            emitted = True
            continue

        if sec.kd or sec.v0:
            state.warn(f"*SECTION_DISCRETE {secid}: KD={sec.kd:g}/V0={sec.v0:g} "
                       "(the dynamic magnification F=(1+KD·V/V0)·F_static) has "
                       "no Radioss spring slot that reproduces it — DROPPED, "
                       "the spring is converted rate-independent. The nearest "
                       "equivalent is a B/D log-rate pair or an fct_ID21 rate "
                       "curve on the property; state it there if the "
                       "magnification carries load.")
        if sec.cl:
            state.warn(f"*SECTION_DISCRETE {secid}: CL={sec.cl:g} (clearance — "
                       "a non-zero value makes the LS-DYNA spring "
                       "COMPRESSION-ONLY with CL of free travel first) has no "
                       "Radioss spring field and is DROPPED: the converted "
                       "spring carries load in both directions from zero "
                       "displacement. Restate it as a shifted, one-sided "
                       "force-displacement function if it matters.")
        # Failure deflections: TDL/CDL deflection limits and the FD failure
        # deflection map to the TYPE4 rupture displacements (element deletion
        # in both codes). 0 = no limit (reader default ±1e30).
        dmax = sec.tdl if 0.0 < sec.tdl < 1e19 else 0.0
        dmin = -sec.cdl if 0.0 < sec.cdl < 1e19 else 0.0
        if sec.fd > 0.0:
            dmax = min(dmax, sec.fd) if dmax else sec.fd
        elif sec.fd < 0.0:
            dmin = max(dmin, sec.fd) if dmin else sec.fd

        # Per-element force scale S becomes a cloned property per distinct S:
        # linear K/C scale directly; a nonlinear function is scaled through the
        # A coefficient (F = f(δ)·A when B=0). Elements oriented by a
        # *DEFINE_SD_ORIENTATION (VID) that resolved to a /SKEW are grouped by
        # (vid, S) onto an oriented /PROP/TYPE8; everything else is axial
        # /PROP/TYPE4.
        groups: Dict[float, List] = defaultdict(list)
        ori_groups: Dict[Tuple[int, float], List] = defaultdict(list)
        n_vid = 0
        n_bad = 0
        for e in elems:
            if e.n1 <= 0 and e.n2 <= 0:
                n_bad += 1
                continue
            if e.vid:
                if state.sdorient_skew_ids.get(e.vid) is None:
                    n_vid += 1
                    continue
                if e.offset:
                    state.warn(f"*ELEMENT_DISCRETE {e.eid}: OFFSET={e.offset:g} "
                               "(initial preload offset) has no /SPRING "
                               "equivalent — dropped.")
                ori_groups[(e.vid, e.s if e.s else 1.0)].append(e)
                continue
            if e.offset:
                state.warn(f"*ELEMENT_DISCRETE {e.eid}: OFFSET={e.offset:g} "
                           "(initial preload offset) has no /SPRING equivalent "
                           "— dropped.")
            groups[e.s if e.s else 1.0].append(e)
        if n_vid:
            state.warn(f"*ELEMENT_DISCRETE part {pid}: {n_vid} element(s) "
                       "reference a *DEFINE_SD_ORIENTATION VID that is undefined "
                       "or uses IOP=1/3 (an unsupported spring-axis projection) "
                       "— those elements were NOT converted.")
        if n_bad:
            state.warn(f"*ELEMENT_DISCRETE part {pid}: {n_bad} element(s) have "
                       "no valid nodes — skipped.")

        # MASS: LS-DYNA discrete elements are massless (nodal mass comes from
        # *ELEMENT_MASS); OpenRadioss wants a spring mass > 0 for the explicit
        # time step. _SPRING_TOKEN_MASS is the same inert token mass the
        # validated grounding-spring emitter uses.
        part_id_used = [False]

        def _alloc_part_id():
            if not part_id_used[0]:
                part_id_used[0] = True
                return pid          # keep the DYNA part id for traceability
            return state.next_id()

        def _scaled(s):
            """(K, C, A, Hscale) for a per-element force scale S.

            With no function the force is K·δ and A cancels out entirely (the
            reader stores K/A, the engine multiplies by A again), so K and C
            are scaled directly. With a loading function the force is f(δ)·A,
            so A carries the scale — but then the STORED stiffness is K/A, and
            the true scaled tangent is S·K, so K must be pre-multiplied by S²
            for K/A to come out right. Leaving that out understates the
            time-step stiffness by S² on a scaled nonlinear spring.

            ``A`` does NOT reach the fct_ID4 damping force: the engine adds it
            as a separate ``Hscale·h(δ̇)`` term (redef3.F90:1143), so a
            curve-driven damper (*MAT_S05, whose whole payload sits on
            fct_ID41 with K = C = 0) needs the scale on Hscale or S is lost
            without a trace."""
            a_coef = 0.0            # 0 → reader default 1.0
            k_s, c_s, h_s = k, c, hscale
            if s != 1.0:
                if fct1:
                    a_coef = s      # scales f(δ) (A coefficient, B=0)
                    k_s, c_s = k * s * s, c * s
                else:
                    k_s, c_s = k * s, c * s
                if fct4:
                    # 0 → reader default 1.0, so the unscaled base is 1.
                    h_s = (hscale or 1.0) * s
            return k_s, c_s, a_coef, h_s

        def _dof(s):
            """The loaded SpringDof for per-element force scale *s*."""
            k_s, c_s, a_coef, h_s = _scaled(s)
            return SpringDof(k=k_s, c=c_s, a=a_coef, b=b_coef, d=d_coef,
                             fct1=fct1, h=hflag, fct2=fct2, fct3=fct3,
                             fct4=fct4, dmin=dmin, dmax=dmax, e=e_coef,
                             hscale=h_s)

        # ── translational (axial) springs → /PROP/TYPE4 ────────────────────
        # A DRO=1 torsional section cannot use TYPE4 (a purely translational
        # 1-DOF property): the payload moves to slot 4 (Rx) of a /PROP/TYPE13,
        # whose local X is node1→node2 by construction (r4buf3.F:145), so the
        # torsion acts about the element's own axis exactly as in LS-DYNA.
        pid_emitted = False
        for s in sorted(groups):
            g_elems = groups[s]
            if torsional:
                usable = [e for e in g_elems if _finite_length(state, e)]
                if len(usable) < len(g_elems):
                    state.warn(
                        f"*SECTION_DISCRETE {secid}: {len(g_elems) - len(usable)}"
                        f" of part {pid}'s DRO=1 (torsional) element(s) are "
                        "ZERO-LENGTH or grounded (N2=0), so there is no "
                        "node1->node2 axis to twist about — those elements were "
                        "NOT converted. Give the torsional spring a second "
                        "node, or orient it with a *DEFINE_SD_ORIENTATION "
                        "(VID), which k2rad puts on a skew-oriented "
                        "/PROP/TYPE8 instead.")
                    g_elems = usable
                if not g_elems:
                    continue
            prop_id = state.next_prop_id()
            part_id = _alloc_part_id()
            if part_id != pid:
                state.warn(f"*ELEMENT_DISCRETE part {pid}: elements with force "
                           f"scale S={s:g} were split onto auto part {part_id} "
                           "(the per-element scale has no /SPRING field).")
            lines += funct_lines
            funct_lines = []       # one /FUNCT, shared by every scaled clone
            if torsional:
                dofs = [SpringDof(), SpringDof(), SpringDof(),
                        _dof(s), SpringDof(), SpringDof()]
                lines += _emit_prop_type13(
                    prop_id, f"{title} ({kind}, torsional DRO=1)",
                    1.0e-4, _connector_inertia(state, g_elems), 0, 0, dofs)
            else:
                k_s, c_s, a_coef, h_s = _scaled(s)
                lines += _emit_prop_type4(
                    prop_id, f"{title} ({kind})", 1.0e-4, k_s, c_s, a_coef,
                    fct1, hflag, dmin, dmax, fct2=fct2, fct3=fct3, fct4=fct4,
                    b=b_coef, d=d_coef, e=e_coef, hscale=h_s)
            lines += _emit_spring_part(
                state, part_id, prop_id, title, g_elems, pid,
                spring_kind_label="TYPE13" if torsional else "TYPE4")
            emitted = pid_emitted = True
            state.warn(f"*ELEMENT_DISCRETE part {pid} ({kind}, "
                       f"{len(g_elems)} element(s)) -> "
                       + (f"/PROP/TYPE13/{prop_id} (SPR_BEAM): the section is "
                          "torsional (DRO=1), so the payload sits on local DOF "
                          "4 (Rx = rotation about the node1->node2 axis) and "
                          "K/C are read as MOMENT per radian and per rad/s — "
                          "the units LS-DYNA already states them in, so "
                          "nothing is rescaled"
                          if torsional else f"/PROP/TYPE4/{prop_id}")
                       + f" + /SPRING on /PART/{part_id}. The spring carries a "
                       "small artificial mass (1e-4) for the explicit time "
                       "step — add *ELEMENT_MASS-equivalent mass if dynamics "
                       "of the spring ends matter.")

        # ── oriented springs → /PROP/TYPE8 (SPR_GENE) on the VID's /SKEW ────
        # Only TYPE8 carries a skew_ID, so an oriented discrete element becomes a
        # SPR_GENE whose local DOF 1 (Tx) acts along the skew's local X (= the
        # *DEFINE_SD_ORIENTATION axis); DOFs 2-6 stay inert.
        # A DRO=1 section puts the payload on slot 4 instead: the skew's local X
        # IS the *DEFINE_SD_ORIENTATION axis, so Rx is rotation about it.
        slot = 4 if torsional else 1
        for (vid, s) in sorted(ori_groups):
            g_elems = ori_groups[(vid, s)]
            skew_id = state.sdorient_skew_ids[vid]
            prop_id = state.next_prop_id()
            part_id = _alloc_part_id()
            k_s, c_s, a_coef, h_s = _scaled(s)
            lines += funct_lines
            funct_lines = []
            lines += [
                f"/PROP/TYPE8/{prop_id}",
                f"{title} ({kind}, oriented VID {vid})",
                "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
                f"{_f(1.0e-4)}{_f(_connector_inertia(state, g_elems))}"
                f"{_i(skew_id)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}",
            ]
            for j in range(1, 7):
                if j == slot:
                    lines += _emit_spr_gene_dof_kc(
                        k_s, c_s, a_coef, fct1, hflag, dmin, dmax,
                        fct2=fct2, fct3=fct3, fct4=fct4, b=b_coef, d=d_coef,
                        e=e_coef, hscale=h_s)
                else:
                    lines += _emit_spr_gene_dof_kc(0.0)
            lines += [
                "#  Fsmooth                Fcut",
                f"{_i(0)}{_f(0.0)}",
            ]
            lines += _emit_spring_part(state, part_id, prop_id, title,
                                       g_elems, pid, spring_kind_label="TYPE8")
            emitted = pid_emitted = True
            state.warn(
                f"*ELEMENT_DISCRETE part {pid} ({kind}, {len(g_elems)} "
                f"element(s)) oriented by *DEFINE_SD_ORIENTATION VID={vid} -> "
                f"/PROP/TYPE8/{prop_id} (SPR_GENE) + /SPRING on /PART/{part_id} "
                f"with skew_ID={skew_id}; stiffness on local DOF {slot} ("
                + ("rotation about" if torsional else "translation along")
                + " the orientation axis). Carries a small artificial mass "
                "(1e-4) for the explicit time step.")

        if not pid_emitted:
            # Every element was filtered out (grounded/zero-length under DRO=1,
            # node-less, or bound to an unresolved *DEFINE_SD_ORIENTATION), so
            # no /PART was written above — but the pid is still claimed by
            # _discrete_part_ids and would vanish from the deck entirely.
            lines += _emit_inert_spring_part(
                state, pid, title,
                f"none of its {len(elems)} element(s) could be converted.")
            emitted = True

    return lines if emitted else []


# *ELEMENT_PLOTEL part / property id. LS-DYNA Vol I R17, *ELEMENT_PLOTEL
# Remark 1: "Part ID, 10000000, is assigned to PLOTEL elements." The card has no
# PID column at all, so the converter has to fabricate the part; dyna2rad picks
# the same id (convertelements.cxx:242-262).
PLOTEL_ID = 10000000
# /PROP/TYPE4 MASS. hm_read_prop04.F:136-142 rejects MASS <= 1e-15 outright:
#   IF(GEO(1)<=EM15) ... ANCMSG(MSGID=229) -> "** ERROR IN SPRING PROPERTY (MASS)"
# so this is the smallest legal value with a margin, and it is exactly what
# dyna2rad writes (1.1*pow(10.0,-15)). k2rad's /BEGIN gives the input and work
# unit systems the same values, so the comparison is against the same number the
# card carries.
PLOTEL_MASS = 1.1e-15


def _spring_eid_families(state: ConversionState) -> List[Tuple[str, Set[int]]]:
    """Every /SPRING element id k2rad takes VERBATIM from the source deck.

    Radioss has ONE /SPRING element-id namespace, but LS-DYNA hands these
    families three separate ones, so ids that are legal input collide after
    conversion (starter ERROR 79, DUPLICATE ID, IN SPRING ELEMENT DEFINITION,
    and no restart file):

      * ``*ELEMENT_DISCRETE``  → ``_make_discrete_springs`` / the grounding
        springs, keyed on the discrete EID;
      * ``*ELEMENT_BEAM`` on a *MAT_SPOTWELD (MAT_100) part →
        ``_make_spotweld_beam_connectors``, keyed on the BEAM EID;
      * ``*ELEMENT_BEAM`` on a *SECTION_BEAM ELFORM=6 discrete-beam part →
        ``_make_discrete_beam_connectors``, also keyed on the BEAM EID (so the
        two beam families cannot clash with each other — their part sets are
        disjoint — but both can clash with the discrete and PLOTEL springs);
      * ``*ELEMENT_PLOTEL`` → ``_make_plotel_elements``, keyed on the PLOTEL EID.

    The joint (/PROP/TYPE45) and *CONSTRAINED_SPOTWELD springs are not listed:
    their ids come from ``next_id()`` during section emission, so they are
    unique by construction and not yet allocated when this runs.
    """
    weld_pids = _spotweld_beam_pids(state)
    dbeam_pids = _discrete_beam_pids(state)
    return [
        ("*ELEMENT_DISCRETE", {d.eid for d in state.discrete_elems}),
        ("*ELEMENT_BEAM on a *MAT_SPOTWELD part",
         {b.eid for b in state.beam_elems if b.pid in weld_pids}),
        ("*ELEMENT_BEAM on a *SECTION_BEAM ELFORM=6 discrete-beam part",
         {b.eid for b in state.beam_elems if b.pid in dbeam_pids}),
        ("*ELEMENT_PLOTEL", {p.eid for p in state.plotel_elems}),
    ]


def _warn_spring_eid_collisions(state: ConversionState) -> None:
    """Report every source-deck id two /SPRING families would both claim."""
    fams = [(name, eids) for name, eids in _spring_eid_families(state) if eids]
    for i, (name_a, eids_a) in enumerate(fams):
        for name_b, eids_b in fams[i + 1:]:
            clash = eids_a & eids_b
            if not clash:
                continue
            state.warn(
                f"{len(clash)} element id(s) are used by BOTH {name_a} and "
                f"{name_b} (first: {sorted(clash)[0]}). LS-DYNA keeps those in "
                "separate id namespaces, but both convert to /SPRING, which is "
                "ONE namespace in the starter — the deck will be rejected with "
                "ERROR 79 (DUPLICATE ID, IN SPRING ELEMENT DEFINITION). "
                "Renumber one of the two families in the .k file.")


def _make_plotel_elements(state: ConversionState) -> List[str]:
    """*ELEMENT_PLOTEL → inert /SPRING + one /PART + one /PROP/TYPE4.

    PLOTEL is a pure visualization line: it must add NO stiffness, NO mass and
    must not govern the time step. /PROP/TYPE4 with K=0, C=0 does all three:

      * NODAL stiffness — r1len3.F:81-105 initialises STI(1,I)=STI(2,I)=ZERO and
        only overwrites them when XK/=0 or XC/=0, so a K=C=0 spring contributes
        exactly zero to the nodal time step of the parts it is drawn on.
      * ELEMENT time step — r1len3.F:139, DT = XM/MAX(EM15, SQRT(XC²+XM·XK)+XC).
        With K=C=0 the denominator floors at the EM15 clamp instead of going to
        zero, giving DT = M/1e-15 ~ 1.1 s raw; the starter's damping-limit term
        (rinit3.F, DTC = HALF*XM/MAX(EM15,XCM)) halves it, and the element table
        prints 0.55 s — MEASURED, against 1.67e-6 s for the shells of the same
        deck, so it never governs. (The MASS>1e-15 hard error is what keeps M
        out of the DT=0 branch at r1len3.F:143.)
      * Mass — 1.1e-15 per element, split over its two nodes. It DOES show up in
        the starter's TOTAL MASS echo (1.2560000000000E-05 -> 1.2560000003300E-05
        Mg for three PLOTELs, a 2.6e-10 relative change); every structural part
        mass, the time step and the result history are bit-identical.

    Everything else stays at the /PROP/TYPE4 reader defaults (no functions, no
    rupture limits), matching dyna2rad, which sets MASS and nothing else.
    """
    if not state.plotel_elems:
        return []

    # Prefer the LS-DYNA id, but never collide: /PART and /PROP ids are checked
    # against what the deck already occupies (k2rad emits /PROP/SHELL|SOLID|BEAM
    # under the SECID verbatim), because a duplicate is starter ERROR 79.
    part_id = (PLOTEL_ID if PLOTEL_ID not in state.parts
               else state.next_part_id())
    prop_id = PLOTEL_ID
    if (PLOTEL_ID in state.sec_shells or PLOTEL_ID in state.sec_solids
            or PLOTEL_ID in state.sec_beams):
        prop_id = state.next_prop_id()

    lines: List[str] = [
        "#-  PLOTEL VISUALIZATION ELEMENTS (*ELEMENT_PLOTEL -> inert /SPRING):",
        HDR,
    ]
    lines += _emit_prop_type4(prop_id, "PLOTEL", PLOTEL_MASS, 0.0, 0.0, 0.0,
                              0, 0, 0.0, 0.0)
    lines += [
        f"/PART/{part_id}",
        "PLOTEL",
        # mat_ID is left 0: /PROP/TYPE4 needs no material, and dyna2rad never
        # sets one on the PLOTEL part either.
        f"{_i(prop_id)}{_i(0)}{_i(0)}",
        f"/SPRING/{part_id}",
        "# sprg_ID  node_ID1  node_ID2",
    ]
    missing: List[int] = []
    kept = 0
    for e in state.plotel_elems:
        if e.n1 not in state.nodes or e.n2 not in state.nodes:
            missing.append(e.eid)
            continue
        lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}")
        kept += 1
    lines.append(HDR)

    if missing:
        state.warn(
            f"*ELEMENT_PLOTEL: {len(missing)} element(s) reference a node with "
            f"no *NODE record (first: EID {missing[0]}) — dropped, because a "
            "/SPRING on an undefined node is starter ERROR 78 (USR2SYS). Only "
            "the visualization line is lost.")
    state.warn(
        f"*ELEMENT_PLOTEL: {kept} visualization element(s) converted to inert "
        f"/SPRING on the synthesized /PART/{part_id} + /PROP/TYPE4/{prop_id} "
        f"(K=0, C=0, MASS={PLOTEL_MASS:g} per element). They add no stiffness "
        "and do not govern the time step, but they DO appear in the animation "
        "and in the part list — delete the *ELEMENT_PLOTEL cards if you want "
        "them out of the model entirely.")

    # (The /SPRING id-namespace collision check covering this family lives in
    # _warn_spring_eid_collisions, a build_starter prepass — the clash is not
    # PLOTEL-specific and must be reported even on a deck with no PLOTELs.)
    return lines


def _mean_diameter(d1: float, d2: float) -> float:
    """Mean of a spot weld nugget's node-1 / node-2 diameters (card 2i).

    A tapered weld is reduced to one prismatic spring at the mean diameter,
    matching dyna2rad's ``meanTS = (TS1+TS2)/2``. A blank/zero column on one
    end is an omission rather than a nugget that tapers to a point, so the
    populated value is used for both ends — averaging the blank in would
    silently quarter the weld area.
    """
    if d1 > 0.0 and d2 > 0.0:
        return (d1 + d2) / 2.0
    return max(d1, d2, 0.0)


def _make_spotweld_beam_connectors(state: ConversionState) -> List[str]:
    """*MAT_SPOTWELD (MAT_100) beam parts → /PROP/TYPE13 (SPR_BEAM) /SPRING
    connectors.

    Route note: /MAT/LAW59 (CONNECT) was evaluated and rejected — its cfg
    (matl59_CONNECT.cfg) binds it to /PROP/TYPE43 8-node connection SOLIDS,
    not to 2-node spring elements, so a LAW59 card here could not be attached
    to the converted beams. The complete spotweld behaviour therefore lives in
    the TYPE13 property: local Tx is the beam axis (Radioss and LS-DYNA share
    that convention for a 2-node spring/beam), per-DOF elastic stiffness comes
    from E, G=E/2(1+ν) and the *SECTION_BEAM resultants, and MAT_100 card 2
    (NRR NRS NRT MRR MSS MTT) becomes the Ifail=1/Ifail2=2 multi-directional
    FORCE failure surface — the same quadratic resultant criterion LS-DYNA
    applies. SIGY/EH give a bilinear axial force function (H=1 elastic-plastic)
    when SIGY > 0.
    """
    pids = sorted(_spotweld_beam_pids(state))
    if not pids:
        return []
    lines: List[str] = [
        "#-  SPOTWELD CONNECTORS (*MAT_SPOTWELD beam parts -> /PROP/TYPE13 + /SPRING):",
        HDR]
    emitted = False

    beams_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    for e in state.beam_elems:
        beams_by_pid[e.pid].append(e)

    for pid in pids:
        part = state.parts[pid]
        mat = state.mat_spotweld[part.mid]
        beams = beams_by_pid.get(pid, [])
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_beams.get(secid)

        # Mean weld length from the node coordinates.
        lens = []
        for e in beams:
            a, b = state.nodes.get(e.n1), state.nodes.get(e.n2)
            if a is not None and b is not None:
                lens.append(((a.x - b.x) ** 2 + (a.y - b.y) ** 2
                             + (a.z - b.z) ** 2) ** 0.5)
        L = (sum(lens) / len(lens)) if lens else 0.0
        if L <= 1e-12:
            state.warn(f"*MAT_SPOTWELD part {pid}: zero-length (or node-less) "
                       "spotweld beams — /PROP/TYPE13 needs a finite length; "
                       f"{len(beams)} weld(s) NOT converted. Tie the sheets "
                       "with *CONSTRAINED_SPOTWELD instead.")
            continue

        # Cross-section area + inertias from the *SECTION_BEAM.
        area = iyy = izz = ixx = 0.0
        if sec is None:
            state.warn(f"*MAT_SPOTWELD part {pid}: no *SECTION_BEAM {secid} — "
                       "cannot size the weld stiffness; welds NOT converted.")
            continue
        if sec.elform == 1:
            # Integrated beam: TS1 is the (outer) section dimension; assume a
            # solid circular spotweld nugget of diameter TS1.
            d = sec.ts1
            area = math.pi * d * d / 4.0
            iyy = izz = math.pi * d ** 4 / 64.0
            ixx = 2.0 * iyy
            if d > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=1) on spotweld part "
                           f"{pid}: assumed a solid circular nugget of diameter "
                           f"TS1={d:g} (card 2a's TS2/TT1/TT2 and CST are not "
                           "read on this path).")
        elif sec.elform == 9:
            # Spot weld beam, *SECTION_BEAM card 2i: TS1/TS2 are the nugget
            # OUTER diameter at node 1/2 and TT1/TT2 the INNER diameter — the
            # card carries diameters, never a volume or an area. A tapered
            # weld (TS1 != TS2) collapses to ONE prismatic /PROP/TYPE13 spring,
            # so the section is taken at the MEAN diameter; that is also what
            # dyna2rad does (convertprops.cxx ConvertToPropType13:
            #   meanTS = (TS1+TS2)/2, meanTT = (TT1+TT2)/2,
            #   area   = pi*(meanTS^2 - meanTT^2)/4).
            # With TT = 0 this is the solid circle pi*d^2/4 of the ELFORM=1
            # branch above, so both spot weld formulations agree.
            do = _mean_diameter(sec.ts1, sec.ts2)
            di = _mean_diameter(sec.tt1, sec.tt2)
            if di >= do > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: inner diameter TT ({di:g}) is not smaller "
                           f"than the outer diameter TS ({do:g}) — the nugget "
                           "was sized as SOLID (TT ignored).")
                di = 0.0
            area = math.pi * (do * do - di * di) / 4.0
            # Solid/annular circular nugget: I = pi(do^4-di^4)/64 about either
            # bending axis, polar J = 2I = pi(do^4-di^4)/32.
            iyy = izz = math.pi * (do ** 4 - di ** 4) / 64.0
            ixx = 2.0 * iyy
            if do > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: nugget sized from card 2i as a circular "
                           f"section, outer d={do:g}"
                           + (f", inner d={di:g}" if di > 0.0 else "")
                           + f" -> A={area:g} (mean of TS1={sec.ts1:g}/"
                           f"TS2={sec.ts2:g}); bending/torsion inertia follow "
                           "from the same section.")
            if (sec.ts1 > 0.0) != (sec.ts2 > 0.0):
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: only one of TS1/TS2 is populated "
                           f"(TS1={sec.ts1:g}, TS2={sec.ts2:g}) — the weld was "
                           f"sized prismatic at d={do:g} instead of tapering "
                           "to a point. Fill in both columns if the nugget "
                           "really is conical.")
            if sec.cst != 1 and do > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: CST={sec.cst} (not tubular) — TS/TT are "
                           "then RECTANGULAR thicknesses, but the weld was "
                           "still sized as a circular nugget of diameter "
                           f"{do:g} (same assumption dyna2rad makes). Check "
                           "the weld stiffness if the nugget is not round.")
            if sec.itoff == 1:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: ITOFF=1 (torsion free) is NOT applied — "
                           "the /PROP/TYPE13 keeps its elastic Rx stiffness.")
        else:
            area, iyy, izz, ixx = sec.area, sec.iyy, sec.izz, sec.ixx
        if area <= 0.0:
            state.warn(f"*MAT_SPOTWELD part {pid}: *SECTION_BEAM {secid} gives "
                       "no cross-section area — welds NOT converted.")
            continue
        if iyy <= 0.0 or izz <= 0.0:
            est = area * area / (4.0 * math.pi)
            iyy = iyy if iyy > 0.0 else est
            izz = izz if izz > 0.0 else est
            state.warn(f"*MAT_SPOTWELD part {pid}: missing bending inertia in "
                       f"*SECTION_BEAM {secid} — estimated as a solid circular "
                       "section from the area.")
        if ixx <= 0.0:
            ixx = iyy + izz

        E = mat.E
        G = E / (2.0 * (1.0 + mat.nu)) if mat.nu > -1.0 else E / 2.0
        k1 = E * area / L            # axial Tx
        k23 = G * area / L           # shear Ty/Tz
        k4 = G * ixx / L             # torsion Rx
        k5 = E * iyy / L             # bending Ry
        k6 = E * izz / L             # bending Rz

        mass = mat.rho * area * L
        if mass <= 0.0:
            mass = 1.0e-4
            state.warn(f"*MAT_SPOTWELD part {pid}: non-positive weld mass "
                       "(RO or section) — token mass 1e-4 used.")
        inertia = max(mass * L * L / 12.0, 1e-20)

        # Failure surface (Ifail=1 multi-directional + Ifail2=2 force criteria:
        # the combined quadratic force/moment resultant criterion, matching
        # MAT_100's (N/NRR)²+(Ns/NRS)²+(Nt/NRT)²+(M/M..)² ≥ 1). Zero fields
        # default to ±1e30 = that component never fails, like a blank in DYNA.
        has_fail = any(v > 0.0 for v in (mat.nrr, mat.nrs, mat.nrt,
                                         mat.mrr, mat.mss, mat.mtt))
        ifail, ifail2 = (1, 2) if has_fail else (0, 0)

        # Axial elastic-plastic bilinear force function from SIGY/EH.
        fct1 = 0
        h1 = 0
        funct_lines: List[str] = []
        if mat.sigy > 0.0:
            fy = mat.sigy * area
            dy = fy / k1
            if mat.et > 0.0 and mat.et < E:
                # EH is the plastic hardening modulus: tangent = E·EH/(E+EH).
                kt = (E * mat.et / (E + mat.et)) * area / L
            else:
                kt = k1 * 1e-4       # near-perfectly-plastic fallback
            dend = dy * 101.0        # 100·δy of plastic range; Radioss
            fend = fy + kt * (dend - dy)   # extrapolates the last segment
            fct1 = state.next_id()
            h1 = 1                   # elastic-plastic, unloading with K1
            funct_lines = [
                f"/FUNCT/{fct1}",
                f"spotweld_axial_bilinear_pid{pid}",
                "#                  X                   Y",
                f"{_f(-dend)}{_f(-fend)}",
                f"{_f(-dy)}{_f(-fy)}",
                f"{_f(0.0)}{_f(0.0)}",
                f"{_f(dy)}{_f(fy)}",
                f"{_f(dend)}{_f(fend)}",
                HDR,
            ]
            state.warn(f"*MAT_SPOTWELD part {pid}: SIGY={mat.sigy:g}/EH="
                       f"{mat.et:g} sampled into a bilinear axial "
                       f"force-displacement /FUNCT/{fct1} (yield force "
                       f"SIGY·A={fy:.6G}, H=1 elastic-plastic). Shear/bending "
                       "DOFs stay elastic up to the failure surface.")

        dofs = [
            (k1, fct1, h1, 0.0, mat.nrr),          # Tx: tension-only failure
            (k23, 0, 0, -mat.nrs, mat.nrs),        # Ty
            (k23, 0, 0, -mat.nrt, mat.nrt),        # Tz
            (k4, 0, 0, -mat.mrr, mat.mrr),         # Rx torsion
            (k5, 0, 0, -mat.mss, mat.mss),         # Ry bending
            (k6, 0, 0, -mat.mtt, mat.mtt),         # Rz bending
        ]
        prop_id = state.next_prop_id()
        lines += funct_lines
        lines += _emit_prop_type13(
            prop_id, (part.title or f"SPOTWELD_{pid}") + " (MAT_100 spotweld)",
            mass, inertia, ifail, ifail2, dofs)
        lines += [
            f"/PART/{pid}",
            part.title or f"SPOTWELD_{pid}",
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{pid}",
            "# sprg_ID  node_ID1  node_ID2  node_ID3",
        ]
        for e in beams:
            lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}{_i(e.n3)}")
            # Record what was ACTUALLY written: *DATABASE_SWFORC lists these
            # sprg_IDs, and every `continue` above skips a whole part without
            # emitting a /SPRING. A /TH/SPRING naming a skipped id is starter
            # ERROR 69 and the deck is refused outright.
            state.spotweld_spring_eids.add(e.eid)
        lines.append(HDR)
        emitted = True

        dropped = [name for name, v in (("DT", mat.dt), ("TFAIL", mat.tfail),
                                        ("EFAIL", mat.efail), ("NF", mat.nf))
                   if v and 0.0 < v < 1e19]
        if dropped:
            state.warn(f"*MAT_SPOTWELD part {pid}: {', '.join(dropped)} have no "
                       "/PROP/TYPE13 slot — dropped (no weld time-step mass "
                       "scaling / timed failure / plastic-strain failure / "
                       "force filtering).")
        if has_fail and abs(mat.nf) > 0.0:
            pass  # NF already reported above
        state.warn(
            f"*MAT_SPOTWELD part {pid} ({len(beams)} weld beam(s)) -> "
            f"/PROP/TYPE13/{prop_id} SPR_BEAM /SPRING connectors "
            f"(K_axial=E·A/L={k1:.6G}, K_shear=G·A/L={k23:.6G}, failure "
            f"forces/moments from MAT_100 card 2 via Ifail2=2). APPROXIMATE "
            "mapping: validate against LS-DYNA on a single-weld pull and "
            "lap-shear coupon before trusting a full-vehicle result.")

    return lines if emitted else []


def _make_constrained_spotweld_springs(state: ConversionState) -> List[str]:
    """*CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT with failure
    forces → one stiff /PROP/TYPE13 /SPRING per weld (Ifail=1/Ifail2=2:
    DeltaMax1=SN axial tension, ±SS on the shear DOFs). The no-failure flavour
    was already turned into a 2-node CNRB at parse time."""
    welds = state.constrained_spotwelds
    if not welds:
        return []
    lines: List[str] = [
        "#-  CONSTRAINED SPOTWELDS WITH FAILURE (-> stiff /PROP/TYPE13 + /SPRING):",
        HDR]
    emitted = False

    # Stiffness rationale: the weld must be rigid relative to the joined
    # sheets. A sheet loads the weld through a patch of membrane stiffness
    # ~E·t; with t of the order of the weld gap L, K = 10·E_ref·L is ~10x
    # stiffer than the surroundings (a firm tie that does not wreck the
    # explicit time step the way a huge penalty K would). E_ref is the
    # stiffest converted structural material.
    e_candidates = ([m.E for m in state.mat_elastic.values()]
                    + [m.E for m in state.mat_plas_tab.values()]
                    + [m.E for m in state.mat_plas_kin.values()]
                    + [m.E for m in state.mat_power_law.values()])
    e_ref = max([e for e in e_candidates if e > 0.0], default=0.0)
    if e_ref <= 0.0:
        e_ref = 210000.0
        state.warn("*CONSTRAINED_SPOTWELD: no structural material found to "
                   "scale the tie stiffness — defaulted E_ref=210000 (steel, "
                   "N/mm² assumed); check the unit system.")

    for w in welds:
        label = w.title or (f"spotweld_{w.n1}_{w.n2}" if w.nsid == 0
                            else f"gen_weld_spot_{w.nsid}")
        n1, n2 = w.n1, w.n2
        if w.nsid > 0:
            nids = sorted({n for n in state.node_sets.get(w.nsid, ("", []))[1]
                           if n > 0})
            if len(nids) != 2:
                state.warn(f"*CONSTRAINED_GENERALIZED_WELD_SPOT nsid={w.nsid}: "
                           f"node set has {len(nids)} node(s) (need exactly 2) "
                           "— weld NOT converted.")
                continue
            n1, n2 = nids
        a, b = state.nodes.get(n1), state.nodes.get(n2)
        if a is None or b is None:
            state.warn(f"*CONSTRAINED_SPOTWELD {label}: node {n1 if a is None else n2} "
                       "has no coordinates — weld NOT converted.")
            continue
        L = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
        if L <= 1e-12:
            state.warn(f"*CONSTRAINED_SPOTWELD {label}: nodes {n1}/{n2} are "
                       "coincident — /PROP/TYPE13 needs a finite length; weld "
                       "NOT converted (merge the nodes or use a tied contact).")
            continue
        if (w.n and abs(w.n - 2.0) > 1e-9) or (w.m and abs(w.m - 2.0) > 1e-9):
            state.warn(f"*CONSTRAINED_SPOTWELD {label}: failure exponents "
                       f"N={w.n:g}/M={w.m:g} differ from 2 — the converted "
                       "multi-directional criterion is quadratic (N=M=2).")

        k = 10.0 * e_ref * L
        krot = k * L * L / 12.0
        dofs = [
            (k, 0, 0, 0.0, w.sn),        # Tx: tension failure force SN
            (k, 0, 0, -w.ss, w.ss),      # Ty: shear failure force SS
            (k, 0, 0, -w.ss, w.ss),      # Tz
            (krot, 0, 0, 0.0, 0.0),      # Rx/Ry/Rz: no moment failure in the
            (krot, 0, 0, 0.0, 0.0),      #   DYNA criterion (defaults ±1e30)
            (krot, 0, 0, 0.0, 0.0),
        ]
        prop_id = state.next_prop_id()
        part_id = state.next_id()
        elem_id = state.next_id()
        # Token mass/inertia, same rationale as the grounding springs: the tie
        # itself is massless in LS-DYNA.
        lines += _emit_prop_type13(prop_id, f"{label} (stiff weld tie)",
                                   1.0e-4, 1.0e-6, 1, 2, dofs)
        lines += [
            f"/PART/{part_id}",
            label,
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{part_id}",
            "# sprg_ID  node_ID1  node_ID2",
            f"{_i(elem_id)}{_i(n1)}{_i(n2)}",
            HDR,
        ]
        emitted = True
        state.warn(
            f"*CONSTRAINED_SPOTWELD {label}: converted to a stiff "
            f"/PROP/TYPE13/{prop_id} spring (K=10·E_ref·L={k:.6G} per "
            f"translational DOF; failure SN={w.sn:g} axial / SS={w.ss:g} "
            "shear via Ifail2=2 force criteria). APPROXIMATE: the pre-failure "
            "tie is penalty-stiff, not rigid — validate the failure load on a "
            "single-weld case.")

    return lines if emitted else []


# ─────────────────────────────────────────────────────────────────────────────
# Starter: hex spot welds  (*DEFINE_HEX_SPOTWELD_ASSEMBLY → /CLUSTER/BRICK)
# ─────────────────────────────────────────────────────────────────────────────

# /CLUSTER Ifail: 3 = multi-directional (the general power-law interaction).
# dyna2rad hardcodes the same value (convertdefinehexspotweldassembly.cxx:70).
_CLUSTER_IFAIL = 3

# /CLUSTER failure-surface coefficients a1..a4 and exponents b1..b4. The engine
# forms (clusterf.F:386-390, the IFAIL==3 branch)
#
#   DMG = a1*(FN/Fn_fail1)^b1 + a2*(FT/Fs_fail)^b2
#       + a3*(MR/Mt_fail)^b3  + a4*(MB/Mb_fail)^b4      -> fails at DMG > 1
#
# and *MAT_SPOTWELD's own criterion (LS-DYNA Vol I R16, MAT_100) is
#
#   (Nrr/NRR)^2 + (Nrs/NRS)^2 + (Nrt/NRT)^2
# + (Mrr/MRR)^2 + (Mss/MSS)^2 + (Mtt/MTT)^2  >= 1
#
# i.e. QUADRATIC in every term, so b = 2 is the right exponent and dyna2rad's
# b1..b4 = 1.0 (convertdefinehexspotweldassembly.cxx:76-79) is not: its LINEAR
# interaction fails a weld held at 40% of both its tension and its shear limit
# at DMG = 0.4 + 0.4 = 0.8, where LS-DYNA gets 0.4^2 + 0.4^2 = 0.32.
#
# But the EXPONENT is only half the mapping. Radioss compares one SHEAR
# RESULTANT FT = sqrt(Fx^2+Fy^2) against ONE limit Fs_fail (clusterf.F:365-366),
# where MAT_100 scores its two shear directions separately against NRS and NRT.
# The exponent and the resultant reduction have to agree, and the obvious
# reduction does NOT agree with b = 2: with Fs_fail = sqrt(NRS^2+NRT^2) the
# shear term becomes (Fx^2+Fy^2)/(NRS^2+NRT^2), which for NRS = NRT = S is
# (Fx^2+Fy^2)/(2S^2) — exactly HALF of MAT_100's (Fx^2+Fy^2)/S^2. Measured on
# NRS=5000/NRT=4000: the weld then survives to 6403 N in pure s-shear where
# LS-DYNA breaks at 5000 (+28%), and to 6403 N in pure t-shear where LS-DYNA
# breaks at 4000 (+60%). Un-conservative in every load state involving shear.
# (dyna2rad pairs that same sqrt with b = 1, whose over-strength happens to
# cancel the other way; neither half is right on its own.)
#
# The reduction that agrees with b = 2 is the MINIMUM of the pair — see
# _resultant_limit. It is EXACT whenever NRS == NRT (a round nugget: the normal
# case, and the only one a single Radioss limit can carry) and conservative
# otherwise, which is the safe direction for a failure criterion.
_CLUSTER_A = 1.0
_CLUSTER_B = 2.0


def _resultant_limit(a: float, b: float) -> float:
    """One Radioss resultant limit for a MAT_100 direction PAIR (NRS,NRT) /
    (MSS,MTT).

    /CLUSTER scores the shear RESULTANT FT = sqrt(Fx^2+Fy^2) against a single
    Fs_fail (clusterf.F:365), so the two LS-DYNA per-direction limits have to
    collapse to one number. With the quadratic exponent b = 2 the term is
    (Fx^2+Fy^2)/Fs_fail^2, and MAT_100's is Fx^2/NRS^2 + Fy^2/NRT^2. Taking
    ``Fs_fail = min(NRS, NRT)`` makes the two IDENTICAL when NRS == NRT, and
    otherwise gives 1/min^2 >= 1/NRS^2 and >= 1/NRT^2, i.e. damage at or above
    LS-DYNA's — the weld fails no later than it would in LS-DYNA.

    A zero field is LS-DYNA's "this component never fails", so it is skipped
    rather than taken as the minimum: min(5000, 0) = 0 would be promoted to
    INFINITY by the starter (hm_read_cluster.F:293-296) and disable the shear
    term entirely. With one of the pair blank the surviving limit is used, which
    over-counts the blank direction's force into FT — unavoidable, because
    Radioss cannot ignore one shear direction of a single resultant. Both blank
    returns 0.0 and the starter's INFINITY promotion is then correct.
    """
    live = [v for v in (a, b) if v > 0.0]
    return min(live) if live else 0.0


def _pair_is_directional(a: float, b: float) -> bool:
    """True when a MAT_100 limit pair carries direction dependence a single
    Radioss resultant limit cannot reproduce — the two are live but unequal, or
    exactly one of them is blank. Both equal (the round-nugget norm) or both
    blank map exactly; anything else only maps conservatively."""
    if a > 0.0 and b > 0.0:
        return a != b
    return (a > 0.0) != (b > 0.0)


def _cluster_brick_eids(state: ConversionState, eids: List[int]):
    """Split an assembly's element ids into (bricks, tets, unknown).

    Applies the identical distinct-node test _make_parts_and_elements uses to
    route a solid to /TETRA4 (4 distinct corners) or /TETRA10 (10 nodes) rather
    than /BRICK, so the two cannot drift apart.

    A tetrahedron is NOT rejected by the starter here — measured: a /GRBRIC/BRIC
    listing a TET4 id resolves, and the cluster reports it in its element count
    with 0 ERROR(S). It is screened out because the result is silently wrong.
    hm_read_cluster.F:201-205 takes the weld's two joined faces from IXS(2:5)
    and IXS(6:9) — the hex's bottom and top faces — and on a collapsed tet
    (n1 n2 n3 n4 n4 n4 n4 n4) the "top face" is one repeated node, so the local
    frame the starter builds from the two face centroids, and with it the
    FN/FT/MR/MB split the whole failure surface is evaluated on, is meaningless.
    The Radioss Reference Guide says the same in prose (/CLUSTER comment 2:
    8-node hexa only) and notes it is not code-enforced.
    """
    by_eid = {e.eid: e for e in state.solid_elems}
    bricks: List[int] = []
    tets: List[int] = []
    unknown: List[int] = []
    for eid in eids:
        e = by_eid.get(eid)
        if e is None:
            unknown.append(eid)
        elif len(e.nodes) == 10 or len(set(n for n in e.nodes if n > 0)) == 4:
            tets.append(eid)
        else:
            bricks.append(eid)
    return bricks, tets, unknown


def _cluster_failure_limits(state: ConversionState, eids: List[int]):
    """(Fn_fail1, Fs_fail, Mt_fail, Mb_fail, mat_id) for one weld assembly.

    The limits come from the *MAT_SPOTWELD of the PART the assembly's FIRST
    element belongs to — dyna2rad does the same walk (element -> PID -> MID,
    convertdefinehexspotweldassembly.cxx:98-113). LS-DYNA forbids an assembly
    element from sharing a MID with anything outside an assembly
    (Vol I R16 p.17-301), so one lookup describes the whole nugget.

    The engine scores ONE shear resultant FT = sqrt(Fx^2+Fy^2) against ONE
    Fs_fail and one bending resultant MB against one Mb_fail (clusterf.F:365,
    367), so each MAT_100 direction PAIR collapses to a single limit via
    _resultant_limit — the minimum of the live pair, which is what agrees with
    the quadratic exponent b=2 (see the _CLUSTER_B comment for the arithmetic).
    Returns mat_id 0 when no MAT_100 is reachable.
    """
    by_eid = {e.eid: e for e in state.solid_elems}
    for eid in eids:
        e = by_eid.get(eid)
        if e is None:
            continue
        part = state.parts.get(e.pid)
        if part is None:
            continue
        m = state.mat_spotweld.get(part.mid)
        if m is None:
            continue
        return (m.nrr,
                _resultant_limit(m.nrs, m.nrt),
                m.mrr,
                _resultant_limit(m.mss, m.mtt),
                part.mid,
                _pair_is_directional(m.nrs, m.nrt)
                or _pair_is_directional(m.mss, m.mtt))
    return 0.0, 0.0, 0.0, 0.0, 0, False


def _emit_cluster_brick(cluster_id: int, title: str, group_id: int,
                        fn_fail: float, fs_fail: float,
                        mt_fail: float, mb_fail: float) -> List[str]:
    """/CLUSTER/BRICK card (FORMAT radioss140 — the only one that exists).

      C1  group_ID(1-10) skew_ID(11-20) Ifail(21-30)
      C2  Fn_fail1(1-20)  a1(21-40)  b1(41-60)
      C3  Fs_fail(1-20)   a2(21-40)  b2(41-60)
      C4  Mt_fail(1-20)   a3(21-40)  b3(41-60)
      C5  Mb_fail(1-20)   a4(21-40)  b4(41-60)

    All five data cards are UNCONDITIONAL — the CFG puts no `if` around cards
    2-5, so they must be written even for Ifail=0 or the starter reads the next
    keyword's line as a failure limit.

    skew_ID=0 lets the starter build the weld's local frame from the cluster's
    own bottom-face -> top-face normal (hm_read_cluster.F:104 `IF (IFAIL > 0
    .and. ISKN == 0)`), which is the correct frame for a through-thickness weld
    and is what dyna2rad emits. A zero limit auto-promotes to INFINITY when
    Ifail > 0 (:293-296), so an unknown resultant disables that term rather
    than failing the weld instantly.

    There is deliberately no Kn/Kt on this card: a /CLUSTER adds no stiffness
    of its own — it is a force/moment monitor around real brick elements, and
    the weld stiffness comes from their own material.
    """
    return [
        f"/CLUSTER/BRICK/{cluster_id}",
        (title or f"HEX_SPOTWELD_{cluster_id}")[:100],
        "# group_ID   skew_ID     Ifail",
        f"{_i(group_id)}{_i(0)}{_i(_CLUSTER_IFAIL)}",
        "#           Fn_fail1                  a1                  b1",
        f"{_f(fn_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        "#            Fs_fail                  a2                  b2",
        f"{_f(fs_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        "#            Mt_fail                  a3                  b3",
        f"{_f(mt_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        "#            Mb_fail                  a4                  b4",
        f"{_f(mb_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        HDR,
    ]


def _emit_th_cluster(th_id: int, cluster_ids: List[int]) -> List[str]:
    """/TH/CLUSTER over every emitted weld cluster.

    Variable names are read from the STARTER's table, not the CFG's GUI list:
    hm_read_thgrou.F:1249-1252 `DATA VARCLUS` is FX FY FZ MX MY MZ FS FN MS MN
    FAIL, and the two group names (:1763-1766) expand to

      DEF  -> FX FY FZ MX MY MZ FAIL   (global frame + damage)
      FLOC -> FS FN MS MN              (LOCAL shear/normal force, bending/torsion)

    dyna2rad asks for DEF alone (convertdefinehexspotweldassembly.cxx:321), so
    the local weld resultants — the quantities a weld report is actually about,
    and the ones swforc prints in LS-DYNA — never reach the T01. Both groups
    are requested here. (The CFG's dropdown offers FT/MB/MT; the starter does
    not know those names and answers ERROR 260.)

    Object ids are cluster ids, TEN PER LINE — /TH/CLUSTER goes through
    hm_read_thgrki.F, not the one-id-per-line hm_read_thgrne.F that /TH/SPRING
    and /TH/BRIC use. A leading 0 in that list would mean "all clusters"
    (WARNING 3083), so the rows are never padded.
    """
    lines = [
        f"/TH/CLUSTER/{th_id}",
        f"TH_CLUSTERS_{th_id}",
        "#     var1      var2",
        "DEF       FLOC      ",
    ]
    row: List[str] = []
    for cid in cluster_ids:
        row.append(_i(cid))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _make_hex_spotweld_clusters(state: ConversionState) -> List[str]:
    """*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N] → /GRBRIC/BRIC + /CLUSTER/BRICK
    (+ one /TH/CLUSTER when *DATABASE_SWFORC asks for weld forces).

    One assembly becomes one cluster: LS-DYNA caps an assembly at 16 hexes and
    /CLUSTER caps a group at 500 (hm_read_cluster.F:86, ERROR 1055), so the 1:1
    map is always inside both limits.

    The cluster is a monitor, not a joint — the hexes keep whatever material
    the deck gave them, and the cluster deletes all of them at once when its
    failure surface is reached. dyna2rad emits the element group as a
    /SET/GENERAL with a SOLID clause; k2rad emits the classic /GRBRIC/BRIC,
    which the starter fills with the same GRTYPE=1 that hm_read_cluster.F:180
    demands.
    """
    if not state.hex_spotweld_assemblies:
        return []
    lines: List[str] = []
    cluster_ids: List[int] = []
    seen_ids: Set[int] = set()
    for a in state.hex_spotweld_assemblies:
        # ID_SW is a user id and goes straight through, like every other
        # passthrough in the writer — but only when it is USABLE. A blank or
        # zero ID_SW would emit /CLUSTER/BRICK/0, and a 0 in the /TH/CLUSTER
        # object list is read as "every cluster" (WARNING 3083,
        # hm_read_thgrki.F:123-137), silently widening the group. A repeated
        # ID_SW is a duplicate-id starter rejection. LS-DYNA requires ID_SW to
        # be unique (Vol I R16 p.17-300), so both cases are malformed decks;
        # repair them the way handle_contact_spotweld repairs a bad interface
        # id rather than passing the fault on to the starter.
        cluster_id = a.sw_id
        if cluster_id <= 0 or cluster_id in seen_ids:
            cluster_id = state.next_id()
            state.warn(
                "*DEFINE_HEX_SPOTWELD_ASSEMBLY: ID_SW "
                + (f"{a.sw_id} is used by more than one assembly"
                   if a.sw_id > 0 else "is blank or zero")
                + f" — the /CLUSTER/BRICK was given generated id {cluster_id} "
                "instead. LS-DYNA requires ID_SW to be unique and non-zero "
                "(Vol I R16 p.17-300); a zero would additionally make the "
                "/TH/CLUSTER request read as ALL clusters (WARNING 3083). The "
                "weld itself is unaffected — only the id it reports under.")
        seen_ids.add(cluster_id)
        bricks, tets, unknown = _cluster_brick_eids(state, a.eids)
        if unknown:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: element id(s) "
                f"{_fmt_eid_list(unknown)} name no *ELEMENT_SOLID in this deck "
                "and were left out of the /CLUSTER/BRICK group.")
        if tets:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: element id(s) "
                f"{_fmt_eid_list(tets)} are tetrahedra and were left OUT of the "
                "/CLUSTER/BRICK group. The starter would accept them without "
                "complaint, which is the problem: a cluster takes the weld's "
                "two joined faces from the hex node ordering "
                "(hm_read_cluster.F:201-205), so a tet contributes a degenerate "
                "top face and corrupts the local frame — and with it the "
                "normal/shear/torsion/bending split the whole failure surface "
                "is evaluated on — for the ENTIRE weld. A hex spot weld must be "
                "meshed with 8-node hexahedra (Radioss Reference Guide, "
                "/CLUSTER comment 2). The remaining bricks are still clustered; "
                "the tets stay in the model as ordinary solids.")
        if not bricks:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: none of its "
                f"{len(a.eids)} element id(s) resolved to an 8-node /BRICK, so "
                "NO /CLUSTER/BRICK was emitted. PHYSICAL CONSEQUENCE: this "
                "weld has no failure criterion in the converted model — its "
                "elements behave as ordinary solids and never delete, so the "
                "joint holds for the whole run. REMEDY: check the element ids "
                "on the card and that the nugget is hex-meshed.")
            continue
        if len(bricks) > 500:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: {len(bricks)} "
                "elements exceed the starter's 500-per-cluster limit "
                "(hm_read_cluster.F:86, ERROR 1055) — the deck will be "
                "rejected. Split the assembly.")
        grbric_id = state.next_id()
        lines += _emit_id_group("GRBRIC/BRIC", grbric_id,
                                f"hex_spotweld_{cluster_id}_bricks", bricks)
        fn, fs, mt, mb, mid, aniso = _cluster_failure_limits(state, bricks)
        lines += _emit_cluster_brick(cluster_id,
                                     a.title or f"HEX_SPOTWELD_{cluster_id}",
                                     grbric_id, fn, fs, mt, mb)
        cluster_ids.append(cluster_id)
        state.cluster_ids.append((cluster_id, a.title))
        if mid:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id} -> "
                f"/CLUSTER/BRICK/{cluster_id} over {len(bricks)} brick(s), "
                f"failure limits from *MAT_SPOTWELD {mid}: Fn_fail1=NRR="
                f"{fn:g}, Fs_fail=min(NRS,NRT)={fs:g}, Mt_fail=MRR="
                f"{mt:g}, Mb_fail=min(MSS,MTT)={mb:g}, with a1..a4=1 and "
                f"b1..b4={_CLUSTER_B:g}. /CLUSTER scores ONE shear resultant "
                "against ONE limit where MAT_100 scores NRS and NRT "
                "separately, so the pair is collapsed to its minimum: that "
                "REPRODUCES MAT_100 exactly when NRS==NRT and MSS==MTT, and is "
                "otherwise conservative (the weld fails no later than in "
                "LS-DYNA). dyna2rad writes b=1 there, which fails a "
                "combined-load weld early. A zero limit is promoted to "
                "INFINITY by the starter (that term is then inactive)."
                + (" NOTE: this weld's transverse limits are NOT equal, so the "
                   "single Radioss resultant cannot carry the direction "
                   "dependence — the converted weld is STRONGER-direction "
                   "conservative, breaking earlier than LS-DYNA when the load "
                   "leans towards the larger limit." if aniso else ""))
        else:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id} -> "
                f"/CLUSTER/BRICK/{cluster_id} over {len(bricks)} brick(s) with NO "
                "failure limits: no *MAT_SPOTWELD (MAT_100) is reachable from "
                "the parts of its elements. Every limit is 0, which the "
                "starter promotes to INFINITY — the weld monitors force and "
                "moment but NEVER fails. Give the nugget part a *MAT_SPOTWELD "
                "if the joint is meant to break.")
    if not lines:
        return []
    head = ["#-  HEX SPOT WELDS (*DEFINE_HEX_SPOTWELD_ASSEMBLY -> /CLUSTER/BRICK):",
            HDR]
    if cluster_ids and state.db_swforc_dt:
        lines += [
            f"#-- *DATABASE_SWFORC -> hex weld cluster forces (dt={state.db_swforc_dt:g})"
        ]
        lines += _emit_th_cluster(state.next_id(), cluster_ids)
    return head + lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: imposed motions
# ─────────────────────────────────────────────────────────────────────────────

#: *BOUNDARY_PRESCRIBED_MOTION DOF -> the /IMPVEL|/IMPACC|/IMPDISP ``Dir``
#: field. 1/2/3 = translation along x/y/z, 5/6/7 = rotation about x/y/z, and
#: +-4 / +-8 = translation along / rotation about the *DEFINE_VECTOR VID, which
#: reach the same X / XX spelling but only make sense together with a
#: ``skew_ID`` whose local X' is that vector — see _pm_skew_for.
_DOF_DIR = {1: "X", 2: "Y", 3: "Z", 4: "X", 5: "XX", 6: "YY", 7: "ZZ", 8: "XX"}

#: /IMPVEL|/IMPACC|/IMPDISP card 1 header. All three share the column grid to
#: col 50; ``frame_ID``/``Icoor`` (51-70) exist only on /IMPVEL and /IMPDISP
#: (FORMAT radioss120) and are written as zeros on /IMPACC too, which the
#: reader ignores (measured: no WARNING 100214).
_IMP_COMMENT = ("#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID"
                "  frame_ID     Icoor")
_IMP_COMMENT2 = ("#           Ascale_x            Fscale_Y"
                 "              Tstart               Tstop")


def _emit_imp_card(keyword: str, motion_id: int, title: str, lcid: int,
                   dir_str: str, grnod_id: int, fscale: float,
                   tstart: float, tstop: float,
                   skew_id: int = 0) -> List[str]:
    """One /IMPVEL | /IMPACC | /IMPDISP block.

    ``skew_id`` goes in cols 21-30 and is the ONLY system column that is safe on
    all three keywords. ``frame_ID`` (cols 51-60) is deliberately left at 0 even
    where a moving system is wanted: measured under ``/BEGIN 2022`` an /IMPDISP
    with ``frame_ID=300`` echoes ``FRAME 0`` and falls back to the global axis
    with NO error and NO warning, because ``radioss120/LOADS/impdisp.cfg``
    never populates the attribute ``read_impdisp.F:140-142`` reads (the
    ``CARD_PREREAD`` that fixes it was added in FORMAT radioss2025, which a 2022
    deck cannot reach). /IMPVEL has that CARD_PREREAD already in radioss120 and
    its frame_ID does work — but ``read_impvel.F:322-325`` then makes it
    ERROR 3091 if a driven node is one of the frame's own N1/N2/N3, a constraint
    /SKEW/MOV does not impose. So: skews, never frames.
    """
    return [
        f"/{keyword}/{motion_id}",
        title,
        _IMP_COMMENT,
        f"{_i(lcid)}{dir_str.rjust(10)}{_i(skew_id)}{_i(0)}{_i(grnod_id)}"
        f"{_i(0)}{_i(0)}",
        _IMP_COMMENT2,
        f"{_f(1.0)}{_f(fscale)}{_f(tstart)}{_f(tstop)}",
        HDR,
    ]


def _pm_skew_for(state: ConversionState, pm, keyword: str, ref: str) -> int:
    """The ``skew_ID`` a prescribed motion needs, or 0 for the global system.

    Two independent sources. ``|DOF| in (4, 8)`` WINS over the _LOCAL option,
    because a VID direction is explicitly NOT body-attached — LS-DYNA: "the
    direction is not updated with time" (Manual Vol I R16 p.751):

    1. ``|DOF| in (4, 8)`` — the DOF is expressed along / about the
       *DEFINE_VECTOR ``VID``, not a global axis. The vector's own /SKEW (local
       X' = tail->head = +V, ``_emit_define_vector_skew``) carries it, so
       ``Dir = "X"`` / ``"XX"`` then means "along V" / "about V" exactly as
       LS-DYNA does. This is what dyna2rad does too (``convertbcs.cxx:339``:
       ``inputsystem = GetRadiossSkewIdFromLsdVID(VID)``). k2rad <= PR #116
       wrote ``skew_ID = 0`` here, so DOF 4 became global X and DOF 8 global XX
       with NO warning — a silently wrong direction.
    2. the _LOCAL option's co-rotating /SKEW/MOV (rigid form only), assigned by
       ``_synthesize_local_motion_frames``.

    A negative DOF (-4 / -8) additionally forbids motion in the two transverse
    directions; that lock is emitted separately (see ``_pm_lock_cards``).
    """
    local_skew = getattr(pm, "skew_id", 0)
    if abs(pm.dof) not in (4, 8):
        if pm.vid:
            state.warn(
                f"*{keyword} {ref}: VID={pm.vid} is only used by |DOF| 4 or 8 "
                f"(translation along / rotation about the vector); DOF={pm.dof} "
                "names a global axis, so the vector is ignored — which is what "
                "LS-DYNA does as well.")
        return local_skew
    if not pm.vid:
        state.warn(
            f"*{keyword} {ref}: DOF={pm.dof} means "
            + ("translation along" if abs(pm.dof) == 4 else "rotation about")
            + " the *DEFINE_VECTOR VID, but VID is 0 — the motion is applied "
            "along the GLOBAL "
            + ("X axis" if abs(pm.dof) == 4 else "X axis (XX)")
            + " instead. Give the card a VID.")
        return local_skew
    if local_skew:
        state.warn(
            f"*{keyword} {ref}: DOF={pm.dof} names the *DEFINE_VECTOR VID, and "
            "an explicit vector direction is NOT body-attached (Manual Vol I "
            "R16 p.751: \"the direction is not updated with time\"), so the "
            f"fixed VID skew is used and the co-rotating /SKEW/MOV/{local_skew} "
            "the _LOCAL option built is left unused for this card.")
    # *DEFINE_VECTOR[_NODES] keeps its VID as the /SKEW id when that is free and
    # falls back to a reserved auto id (state.vector_skew_ids records which).
    # A VID naming a *DEFINE_COORDINATE_* system is accepted too, because
    # _make_skews emits all three flavours under their own cid (_SYSTEM and
    # _VECTOR via _emit_skew_fix / _emit_coord_vector_skew, _NODES via
    # _emit_skew_from_nodes) — so a skew with that id really is in the deck and
    # the card resolves. All three registries are tested, the same set
    # _make_body_loads accepts for its CID; leaving coord_nodes out sent a card
    # whose VID named a *DEFINE_COORDINATE_NODES system down the "no /SKEW exists
    # — THE DIRECTION IS WRONG" exit while the skew sat in the same .rad.
    skew_id = state.vector_skew_ids.get(pm.vid)
    if skew_id:
        return skew_id
    if (pm.vid in state.coord_vectors or pm.vid in state.coord_sys
            or pm.vid in state.coord_nodes):
        return pm.vid
    state.warn(
        f"*{keyword} {ref}: DOF={pm.dof} references *DEFINE_VECTOR {pm.vid}, "
        "which is not in the deck (or is degenerate) — no /SKEW exists for it, "
        "so the motion is applied along the GLOBAL "
        + ("X" if abs(pm.dof) == 4 else "XX")
        + " axis instead. THE DIRECTION IS WRONG unless that vector happens to "
        "be the global axis.")
    return local_skew


def _pm_lock_cards(state: ConversionState, pm, keyword: str,
                   ref: str) -> Tuple[List[str], int, List[str]]:
    """The ``Dir`` letters a NEGATIVE DOF (-4 / -8) must additionally hold at
    zero, as ``(dirs, zero_funct_id, funct_lines)``.

    LS-DYNA's -4 / -8 mean "motion along/about VID, and motion in the normal
    directions is NOT permitted" (Manual Vol I R16 p.750). The lock needs a
    synthesized FLAT-ZERO /FUNCT and ``Fscale_Y = 1``, not the real curve with
    ``Fscale_Y = 0``: a zero ordinate scale is SILENTLY replaced by the
    unit-system factor — ``read_impvel.F:248`` ``IF (YSCALE == ZERO) YSCALE =
    ONE * FSCAL_V``. Measured on a live starter run, the lock cards written with
    ``Fscale_Y = 0`` echoed ``FSCALE 1.0`` and would have driven the two
    transverse axes at FULL scale on the real curve — the exact opposite of
    locking them. dyna2rad uses a synthetic 2-point ``(0,0),(1,0)`` function for
    the same reason (``convertbcs.cxx:644,663``).
    """
    if pm.dof not in (-4, -8):
        return [], 0, []
    locked = (["Y", "Z"] if pm.dof == -4 else ["YY", "ZZ"])
    fct = state.next_curve_id()
    lines = _emit_funct(fct, f"ZERO_FUNCT_LOCK_{fct}", [(0.0, 0.0), (1.0, 0.0)])
    state.warn(
        f"*{keyword} {ref}: DOF={pm.dof} also FORBIDS motion in the two "
        f"directions normal to the vector, so {'/'.join(locked)} of the same "
        f"skew are additionally driven to zero — two extra /IMP* cards on a "
        f"synthesized flat-zero /FUNCT/{fct}. It cannot be the real curve with "
        "Fscale_Y = 0: read_impvel.F:248 replaces a zero ordinate scale with "
        "the unit-system factor, so those cards would drive the transverse "
        "axes at FULL scale (measured on a live starter run). dyna2rad uses the "
        "same synthetic 2-point function (convertbcs.cxx:644,663). NOTE the "
        "precondition k2rad does NOT test: LS-DYNA applies the negative forms "
        "\"to rigid bodies [only] if |CMO| = 2 on *MAT_RIGID or "
        "*CONSTRAINED_NODAL_RIGID_BODY\" (p.750). The manual does not document "
        "what it does instead when |CMO| != 2, so k2rad emits the lock either "
        "way rather than guessing the constraint away — on a rigid body with "
        "|CMO| != 2 these two cards may therefore be an OVER-CONSTRAINT LS-DYNA "
        "would have ignored. Check card 2 of the body's *MAT_RIGID / "
        "*CONSTRAINED_NODAL_RIGID_BODY_SPC.")
    return locked, fct, lines


def _make_imposed_motions(state: ConversionState, rbody_info: Dict) -> List[str]:
    """*BOUNDARY_PRESCRIBED_MOTION_RIGID[_LOCAL] -> /IMPVEL | /IMPACC | /IMPDISP
    on the rigid body's /RBODY main node."""
    lines: List[str] = []
    if not state.prescribed_motions:
        return lines
    lines.append("#-  IMPOSED MOTIONS:")

    # /IMPVEL, /IMPACC and /IMPDISP ids come from a local counter, not
    # state.next_id(). _make_imposed_motions_set writes the same three keywords,
    # but from next_id(), whose _auto_id base is 90001 — far above anything this
    # counter reaches — so the two cannot collide, and no user id can either (the
    # starter's UDOUBLE scan runs separately per option,
    # hm_read_impvel.F:129/169). Keeping the counter means a deck with no _LOCAL /
    # no VID motion converts byte-identically to PR #116.
    motion_counter = 1
    # Several cards may drive the same body on different DOFs, and the _LOCAL
    # prepass gives them ONE shared /SKEW/MOV — emitting the card per motion
    # would write that id twice (starter ERROR 79 DUPLICATE ID over the merged
    # /SKEW+/FRAME table, no restart file).
    skews_written: Set[int] = set()
    for pm in state.prescribed_motions:
        keyword = ("BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL" if pm.local
                   else "BOUNDARY_PRESCRIBED_MOTION_RIGID")
        info = rbody_info.get(pm.pid)
        if not info:
            state.warn(f"BOUNDARY_PRESCRIBED_MOTION_RIGID pid={pm.pid}: no RBODY found; motion skipped")
            continue

        # Impose the motion on the rigid body's PRIMARY (master) node only, NOT on
        # every node of the rigid part. The secondary nodes are slaved by /RBODY;
        # adding /IMPDISP on them creates "incompatible kinematic conditions"
        # (Starter WARNING ID 312) which OpenRadioss resolves in favour of the
        # rigid body — silently dropping the imposed motion so the part never moves
        # (zero reaction → zero strain energy → zero stress). Driving the master
        # node (the same node the rigid-body /BCS constrains) translates the whole
        # body correctly.
        grnod_id = info["ind_grnod_id"]
        base_dir = _DOF_DIR.get(abs(pm.dof))
        if base_dir is None:
            state.warn(
                f"*{keyword} pid={pm.pid}: DOF={pm.dof} has no /IMP* Dir "
                "equivalent — nothing emitted. |DOF| 9/10/11 rotate about an "
                "axis parallel to x/y/z through (OFFSET1, OFFSET2), which "
                "LS-DYNA itself does not allow on a rigid body, and DOF=12 "
                "(translation along segment normals) is *_SET_SEGMENT only. "
                "dyna2rad emits an EMPTY /IMPVEL for these instead "
                "(convertbcs.cxx:634-675).")
            continue
        ref = f"pid={pm.pid}"
        skew_id = _pm_skew_for(state, pm, keyword, ref)
        tstart = pm.birth if pm.birth < 1e27 else 0.0
        tstop = pm.death if pm.death < 1e27 else 0.0
        # PM_VAD_KEYWORD is the SAME dict handlers._pm_vad_supported gates on,
        # so this index can never miss (a VAD outside it never reaches here).
        kw = PM_VAD_KEYWORD[pm.vad]
        if pm.local and pm.skew_id and pm.skew_id not in skews_written:
            skews_written.add(pm.skew_id)
            lines += _emit_skew_mov(
                pm.skew_id, f"SKEW_MOV_LOCAL_PID{pm.pid}", *pm.mov_nodes, "X")
        lines += _emit_imp_card(kw, motion_counter, f"Motion_{motion_counter}",
                                pm.lcid, base_dir, grnod_id, pm.sf,
                                tstart, tstop, skew_id)
        motion_counter += 1
        locked, zero_fct, fct_lines = _pm_lock_cards(state, pm, keyword, ref)
        lines += fct_lines
        for lock_dir in locked:
            lines += _emit_imp_card(kw, motion_counter,
                                    f"Motion_{motion_counter}_lock",
                                    zero_fct, lock_dir, grnod_id, 1.0,
                                    tstart, tstop, skew_id)
            motion_counter += 1
    # A triad the prepass built for a card the loop then dropped (no /RBODY for
    # the pid — an element-free rigid part, or a *CONSTRAINED_RIGID_BODIES slave
    # whose nodes were merged into its master) still has its three nodes in /NODE
    # and in the body's /RBODY secondary group. Write the /SKEW/MOV that explains
    # them rather than leaving three unaccounted-for element-free nodes behind
    # and a prepass warning describing a skew the deck does not contain. An
    # unreferenced /SKEW is inert.
    for pm in state.prescribed_motions:
        if pm.local and pm.skew_id and pm.skew_id not in skews_written:
            skews_written.add(pm.skew_id)
            lines += _emit_skew_mov(
                pm.skew_id, f"SKEW_MOV_LOCAL_PID{pm.pid}", *pm.mov_nodes, "X")
    return lines


def _local_body_basis(state: ConversionState, pid: int):
    """The rigid body's OWN local system, as ``(basis, source)`` where *basis* is
    the global-frame orthonormal triad ``(ex, ey, ez)``, or ``(None, reason)``.

    LS-DYNA takes the *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL system from
    "LCO and CID in *MAT_RIGID and *CONSTRAINED_NODAL_RIGID_BODY, respectively.
    If LCO/CID is 0, the local coordinate system defaults to the principal
    inertia directions of the rigid body" (Manual Vol I R16 p.756-757 Remark 7;
    *MAT_RIGID's own card 3 repeats it, Vol II R16 p.2-233). k2rad parses both,
    so both are honoured EXACTLY:

      * ``CID`` on *CONSTRAINED_NODAL_RIGID_BODY, and ``LCO`` on *MAT_RIGID card
        3, are *DEFINE_COORDINATE_* ids — the /SKEW k2rad already emits for them,
        read back through ``_icid_basis``;
      * *MAT_RIGID card 3's alternative ``A1-V3`` pair gives the triad directly:
        "the output parameters are in the directions a, b, and c where the latter
        are given by the cross products c = a x v and b = c x a".

    Only the LCO/CID = 0 default is unrecoverable, because it needs the body's
    inertia tensor and k2rad computes none. A CNRB whose PID collides with a
    rigid part's id resolves to the CNRB, matching _make_cnrb_rbodies' precedence.
    """
    for c in state.cnrbs:
        if c.pid != pid:
            continue
        if not c.cid:
            return None, ("*CONSTRAINED_NODAL_RIGID_BODY CID is 0, so LS-DYNA "
                          "uses the body's PRINCIPAL INERTIA directions")
        basis = _icid_basis(state, c.cid)
        if basis is None:
            return None, (f"*CONSTRAINED_NODAL_RIGID_BODY CID={c.cid} is not a "
                          "*DEFINE_COORDINATE_* system in the deck (or is "
                          "degenerate)")
        return basis, f"CID={c.cid} on *CONSTRAINED_NODAL_RIGID_BODY {pid}"
    part = state.parts.get(pid)
    mat = state.mat_rigid.get(part.mid) if part is not None else None
    if mat is None:
        return None, "the part has no *MAT_RIGID card to read a local system from"
    if mat.a_vec is not None and mat.v_vec is not None:
        ex = _vnorm(mat.a_vec)
        ez = _vnorm(_vcross(mat.a_vec, mat.v_vec)) if ex is not None else None
        if ex is None or ez is None:
            return None, (f"*MAT_RIGID {mat.mid} card 3 gives A1-V3, but a and v "
                          "are zero or parallel so c = a x v is degenerate")
        return (ex, _vcross(ez, ex), ez), \
            f"the A1-V3 vector pair on *MAT_RIGID {mat.mid} card 3"
    if not mat.lco:
        return None, (f"LCO on *MAT_RIGID {mat.mid} card 3 is 0 (or blank), so "
                      "LS-DYNA uses the body's PRINCIPAL INERTIA directions")
    basis = _icid_basis(state, mat.lco)
    if basis is None:
        return None, (f"LCO={mat.lco} on *MAT_RIGID {mat.mid} card 3 is not a "
                      "*DEFINE_COORDINATE_* system in the deck (or is degenerate)")
    return basis, f"LCO={mat.lco} on *MAT_RIGID {mat.mid} card 3"


def _synthesize_local_motion_frames(state: ConversionState) -> None:
    """build_starter prepass: give every *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL
    a co-rotating /SKEW/MOV, by synthesizing three nodes that ride the body.

    **Why a moving SKEW.** With the _LOCAL option LS-DYNA expresses DOF in the
    rigid body's own system, whose "orientation rotates with time in accordance
    with the rotation of the rigid body" (Manual Vol I R16 p.756-757 Remark 7).
    A /SKEW/MOV is rebuilt from its three nodes' CURRENT coordinates every cycle
    (``newskw.F``, "SKEW MOBILE", called from ``resol``) and ``fixvel.F:390-417``
    projects the imposed component onto that freshly-updated row — so three nodes
    that move rigidly with the body give exactly the co-rotating triad, and no
    fictitious forces (a moving SKEW carries no omega, unlike a moving FRAME, so
    no entrainment or Coriolis term is ever added — which is what is wanted).
    The skew goes in the ``skew_ID`` column, the only system column that works on
    all three of /IMPVEL, /IMPACC and /IMPDISP (see _emit_imp_card).

    **Why synthesized nodes and not three mesh nodes.** The /SKEW/MOV triad is
    fully determined by its N1/N2/N3, so three arbitrary mesh nodes would give
    some mesh direction, not the body's local axes — a silent redefinition of
    what DOF means. Three purpose-built nodes place the triad exactly. They are
    element-free, so they add no mass and no inertia (the same trick
    ``--rigid-cog-master`` already uses for the /RBODY main), and they are folded
    into the body's /RBODY secondary group via ``state.local_frame_nodes`` so
    they co-rotate with it.

    **The triad's ORIENTATION.** ``_local_body_basis`` reads the body's own local
    system from LCO on *MAT_RIGID card 3 or CID on *CONSTRAINED_NODAL_RIGID_BODY
    — the two fields LS-DYNA itself names (Manual Vol I R16 p.756-757 Remark 7)
    — and places N2/N3 along that ex/ey, so a deck that states its local system
    converts EXACTLY. Only the LCO/CID = 0 default is out of reach: it is the
    body's PRINCIPAL INERTIA directions and k2rad computes no inertia tensor. The
    triad then falls back to the GLOBAL axes and the residual is the CONSTANT
    rotation R0 between them and the true principal system — exact when the body
    happens to be principal-aligned, a fixed misalignment otherwise. Even that is
    strictly better than the Radioss dyna-reader, which never reads
    ``localOption`` at all (``convertbcs.cxx`` has no match for LOCAL) and so
    freezes the axes at t=0 — an error that GROWS as cos(theta(t)) and becomes
    meaningless once the body has turned ~90 degrees.

    Must run BEFORE the /NODE section (the helper nodes have to be emitted),
    before the /RBODY sections (which read ``local_frame_nodes``) and before
    /FRAME allocation (which shares the /SKEW id namespace).
    """
    # A motion on a part that is neither *MAT_RIGID nor a *CONSTRAINED_NODAL_
    # RIGID_BODY has no /RBODY to drive at all: the writer drops it with its own
    # "no RBODY found" warning, and building a triad for it would leave three
    # free nodes attached to nothing. Same reason for the _DOF_DIR test: a DOF
    # with no /IMP* Dir letter (9/10/11/12) is refused by the writer, so a triad
    # for it would be three unexplained nodes plus a warning promising a
    # co-rotating skew that the .rad never contains.
    rigid_pids = {p for p, part in state.parts.items()
                  if part.mid in state.mat_rigid}
    rigid_pids |= {c.pid for c in state.cnrbs}
    locals_ = [pm for pm in state.prescribed_motions
               if pm.local and pm.pid in rigid_pids
               and _DOF_DIR.get(abs(pm.dof)) is not None]
    if not locals_:
        return
    # Node coordinates of each candidate body, to scale the helper offsets: a
    # unit offset on a micrometre-scale model would sit at the rounding limit of
    # the F20 coordinate fields. newskw.F normalises the triad, so only the
    # conditioning matters.
    pnodes = _part_node_sets(state)
    next_node = (max(state.nodes) + 1) if state.nodes else 90000001
    done: Dict[int, Tuple[int, Tuple[int, int, int]]] = {}
    for pm in locals_:
        if pm.pid in done:
            pm.skew_id, pm.mov_nodes = done[pm.pid]
            continue
        pts = [state.nodes[n] for n in pnodes.get(pm.pid, ()) if n in state.nodes]
        if not pts:
            # A CNRB target (its nodes belong to deformable parts) or an
            # element-free part: fall back to the model bbox for the scale and
            # the global origin for the reference point. Both are only used for
            # conditioning — the triad's DIRECTIONS are what carry the physics.
            pts = list(state.nodes.values())
        if not pts:
            state.warn(
                f"*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL pid={pm.pid}: the deck "
                "has no nodes, so no co-rotating /SKEW/MOV could be built — the "
                "motion is applied in the GLOBAL system (which is what the "
                "Radioss dyna-reader always does).")
            continue
        k = len(pts)
        cx = sum(p.x for p in pts) / k
        cy = sum(p.y for p in pts) / k
        cz = sum(p.z for p in pts) / k
        span = max(max(p.x for p in pts) - min(p.x for p in pts),
                   max(p.y for p in pts) - min(p.y for p in pts),
                   max(p.z for p in pts) - min(p.z for p in pts))
        s = span * 0.1 if span > 0.0 else 1.0
        basis, why = _local_body_basis(state, pm.pid)
        ex, ey = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) if basis is None \
            else (basis[0], basis[1])
        n1, n2, n3 = next_node, next_node + 1, next_node + 2
        next_node += 3
        state.nodes[n1] = NodeData(cx, cy, cz)
        # N1->N2 = the body's local X'; N3 fixes the X'Y' plane.
        state.nodes[n2] = NodeData(cx + s * ex[0], cy + s * ex[1], cz + s * ex[2])
        state.nodes[n3] = NodeData(cx + s * ey[0], cy + s * ey[1], cz + s * ey[2])
        pm.skew_id = state.reserve_skew_id(state.next_id())
        pm.mov_nodes = (n1, n2, n3)
        state.local_frame_nodes.setdefault(pm.pid, []).extend([n1, n2, n3])
        done[pm.pid] = (pm.skew_id, pm.mov_nodes)
        common = (
            f"*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL pid={pm.pid}: the DOF is "
            f"driven in a CO-ROTATING /SKEW/MOV/{pm.skew_id}, built on three "
            f"synthesized element-free nodes ({n1}, {n2}, {n3}) that join the "
            "body's /RBODY secondary group so the triad turns with it "
            "(newskw.F rebuilds it every cycle; fixvel.F:390-417 projects the "
            "imposed component onto the updated row). ")
        if basis is not None:
            state.warn(
                common
                + f"Its axes are taken from {why}, which is the field LS-DYNA "
                "itself reads for this option (Manual Vol I R16 p.756-757 "
                "Remark 7), so the local system is reproduced EXACTLY. (The "
                "Radioss dyna-reader ignores the _LOCAL flag entirely, which "
                "freezes the axes at t=0 instead: an error that grows with the "
                "body's rotation.)")
        else:
            state.warn(
                common
                + f"Its axes are INITIALISED TO THE GLOBAL AXES because {why}, "
                "and k2rad computes no inertia tensor, so the true orientation "
                "cannot be recovered. The conversion is therefore EXACT only if "
                "the body's local system is global-aligned at t=0 and off by "
                "that CONSTANT rotation otherwise — check the \"principal "
                "directions\" block of the LS-DYNA d3hsp mass summary, and name "
                "the system explicitly (LCO on *MAT_RIGID card 3, or CID on "
                "*CONSTRAINED_NODAL_RIGID_BODY) to make it exact. (The Radioss "
                "dyna-reader ignores the _LOCAL flag entirely, which freezes the "
                "axes at t=0 instead: an error that grows with the body's "
                "rotation.)")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: imposed motions for node sets
# ─────────────────────────────────────────────────────────────────────────────

# LS-DYNA *BOUNDARY_PRESCRIBED_MOTION DOF → (translation, rotation) /BCS codes.
# 1/2/3 = Tx/Ty/Tz, 5/6/7 = Rx/Ry/Rz. DOF 4 (translation along vector VID) and
# 8 (rotation about VID) have no global X/Y/Z /BCS code and are not mapped here.
_PM_DOF_TO_BCS = {
    1: ("100", "000"), 2: ("010", "000"), 3: ("001", "000"),
    5: ("000", "100"), 6: ("000", "010"), 7: ("000", "001"),
}


def _or_dof_codes(codes: List[str]) -> str:
    """OR a list of 3-char DOF codes, e.g. ['100','001'] → '101'."""
    out = ["0", "0", "0"]
    for c in codes:
        for i in range(3):
            if c[i] == "1":
                out[i] = "1"
    return "".join(out)


def _pm_set_nodes(state: ConversionState, pm,
                  box_cache: Optional[Dict[int, Optional[Set[int]]]] = None
                  ) -> Optional[List[int]]:
    """The node ids one *BOUNDARY_PRESCRIBED_MOTION_SET[_BOX] row drives, or
    None (already warned) when the row cannot be resolved.

    Three shapes, exactly the ones ``convertbcs.cxx:465-540`` distinguishes:

      * NSID, no BOXID   -> the node set verbatim;
      * NSID and BOXID   -> the INTERSECTION with the box's contained nodes
        (dyna2rad builds a /SET/GENERAL with a ``SET`` clause plus a ``SET_I``
        clause, ``:493-520``; k2rad resolves the same membership numerically,
        like every other *DEFINE_BOX consumer);
      * BOXID, no NSID   -> every node inside the box (``:522-535``).

    **Caveat, warned:** LS-DYNA re-evaluates box membership as nodes move in and
    out of the box every timestep; both the numeric resolution here and the
    dyna2rad /SET/GENERAL are a t = 0 SNAPSHOT.

    ``box_cache`` memoizes the per-box resolution across the rows of one deck, so
    N rows naming one missing box report it once instead of N times.
    """
    if pm.boxid:
        label = f"*BOUNDARY_PRESCRIBED_MOTION_SET_BOX nsid={pm.nsid}"
        if box_cache is not None and pm.boxid in box_cache:
            box_nodes = box_cache[pm.boxid]
        else:
            box_nodes = _resolve_box_nodes(state, pm.boxid, label)
            if box_cache is not None:
                box_cache[pm.boxid] = box_nodes
        if pm.nsid:
            if pm.nsid not in state.node_sets:
                state.warn(f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: node set not found – skipped")
                return None
            nids = state.node_sets[pm.nsid][1]
            if box_nodes is None:               # undefined/degenerate box
                return list(nids)
            kept = [n for n in nids if n in box_nodes]
            if not kept:
                state.warn(
                    f"{label}: no node of set {pm.nsid} lies inside "
                    f"*DEFINE_BOX {pm.boxid} (of {len(nids)} in the set) — the "
                    "motion is dropped. LS-DYNA would still pick nodes up as "
                    "they ENTER the box during the run; a Radioss node group is "
                    "resolved once, on the t=0 geometry.")
                return None
            if len(kept) < len(nids):
                state.warn(
                    f"{label}: {len(kept)} of {len(nids)} set nodes lie inside "
                    f"*DEFINE_BOX {pm.boxid} and are driven. The membership is a "
                    "t=0 SNAPSHOT — LS-DYNA re-tests the box every timestep, so "
                    "nodes that move into it later are NOT picked up (and nodes "
                    "that leave keep being driven).")
            return kept
        if box_nodes is None:
            return None
        if not box_nodes:
            state.warn(f"{label}: *DEFINE_BOX {pm.boxid} contains no node — the "
                       "motion is dropped.")
            return None
        state.warn(
            f"*BOUNDARY_PRESCRIBED_MOTION_SET_BOX: NSID is 0, so the box alone "
            f"is the group — all {len(box_nodes)} node(s) inside *DEFINE_BOX "
            f"{pm.boxid} are driven (t=0 snapshot; see above).")
        return sorted(box_nodes)
    # No box: the plain _SET / _NODE path, byte- and message-identical to what
    # k2rad has always emitted. A card that names neither a set nor a box lands
    # here with nsid = 0, which is not a node set either, so it takes the same
    # "node set not found" exit. (The Radioss dyna-reader leaves its set id
    # uninitialised in that case, behind an empty "// warning / error" comment,
    # convertbcs.cxx:536-539.)
    if pm.nsid not in state.node_sets:
        state.warn(f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: node set not found – skipped")
        return None
    return list(state.node_sets[pm.nsid][1])


def _make_imposed_motions_set(state: ConversionState) -> List[str]:
    lines: List[str] = []
    if not state.prescribed_motion_sets:
        return lines

    # _BOX card 2 fields with no OpenRadioss target. Reported once per deck.
    if any(pm.toffset for pm in state.prescribed_motion_sets):
        state.warn(
            "*BOUNDARY_PRESCRIBED_MOTION_SET_BOX: TOFFSET=1 (\"the time value "
            "of the load curve, LCID, will be offset by the time when the node "
            "enters the box\") has no OpenRadioss equivalent — DROPPED. The "
            "curve is evaluated against absolute time for every driven node, so "
            "nodes LS-DYNA would start later start at t=0 here. dyna2rad drops "
            "it silently.")
    if any(pm.lcbchk for pm in state.prescribed_motion_sets):
        state.warn(
            "*BOUNDARY_PRESCRIBED_MOTION_SET_BOX: LCBCHK (curve giving the "
            "discrete box-check times) has no OpenRadioss equivalent — DROPPED. "
            "Radioss resolves the box once, on the t=0 geometry, so there is "
            "nothing to schedule re-checks for. dyna2rad drops it silently.")

    # LS-DYNA convention: *BOUNDARY_PRESCRIBED_MOTION_SET with sf=0 means "fix this
    # DOF" (zero x any_curve = 0 displacement = fixed). Emit a /BCS (constraint)
    # instead of an /IMPDISP with a bogus unit scale — critical for symmetry BCs
    # (treated as IMPDISP with sf=1 the plane nodes would get spurious motion and
    # the stiffness matrix would go singular). All fixed DOFs of one node set are
    # combined into ONE /BCS (OpenRadioss applies the union) rather than one card
    # per DOF — fewer cards and no dependence on whether multiple /BCS stack.
    # Keyed by (nsid, boxid): two rows on the same NSID but different boxes drive
    # different node lists and must not share one /BCS.
    fix_tra: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    fix_rot: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    fix_nodes: Dict[Tuple[int, int], List[int]] = {}
    fix_order: List[Tuple[int, int]] = []
    # (row, its resolved node ids) — carried together rather than looked up by
    # id(pm) later, which only stays unique while the objects are alive.
    motions: List[Tuple[object, List[int]]] = []
    box_cache: Dict[int, Optional[Set[int]]] = {}
    for pm in state.prescribed_motion_sets:
        nids = _pm_set_nodes(state, pm, box_cache)
        if nids is None:
            continue
        if pm.sf == 0.0:
            mapped = _PM_DOF_TO_BCS.get(pm.dof)
            if mapped is None:
                state.warn(
                    f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: dof={pm.dof} is "
                    "not a global X/Y/Z translation (1-3) or rotation (5-7) — e.g. "
                    "4/8 act along a vector — so no zero-motion /BCS was emitted."
                )
                continue
            key = (pm.nsid, pm.boxid)
            if key not in fix_tra:
                fix_order.append(key)
                fix_nodes[key] = nids
            fix_tra[key].append(mapped[0])
            fix_rot[key].append(mapped[1])
        else:
            motions.append((pm, nids))

    for key in fix_order:
        nsid, boxid = key
        set_title = state.node_sets.get(nsid, ("", []))[0]
        nids = fix_nodes[key]
        tra = _or_dof_codes(fix_tra[key])
        rot = _or_dof_codes(fix_rot[key])
        bc_id = state.next_id()
        # next_grnod_id, not next_id: a user *SET_NODE whose SID sits at or above
        # the auto-id base is re-emitted verbatim as /GRNOD/NODE/<sid>, and a
        # collision is starter ERROR 79 DUPLICATE ID / IN NODE GROUP DEFINITION
        # with no restart file. The motion path below already drew from it; this
        # branch, four lines away, still used the unguarded counter.
        grnod_id = state.next_grnod_id()
        lines += [
            f"/BCS/{bc_id}",
            set_title or f"BC_set_{nsid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}         0{_i(grnod_id)}",
            HDR,
        ]
        lines += _emit_grnod_node(grnod_id, set_title or f"SET_{nsid}", nids)

    # Non-zero scale: real prescribed motion → /IMPDISP, /IMPVEL, /IMPACC
    for pm, nids in motions:
        keyword = ("BOUNDARY_PRESCRIBED_MOTION_SET_BOX" if pm.boxid
                   else "BOUNDARY_PRESCRIBED_MOTION_SET")
        set_title = state.node_sets.get(pm.nsid, ("", []))[0]
        base_dir = _DOF_DIR.get(abs(pm.dof))
        if base_dir is None:
            state.warn(
                f"*{keyword} nsid={pm.nsid}: DOF={pm.dof} has no /IMP* Dir "
                "equivalent — nothing emitted. |DOF| 9/10/11 rotate about an "
                "axis parallel to x/y/z through the (OFFSET1, OFFSET2) point of "
                "the continuation card, and DOF=12 (translation along the "
                "segment normals) belongs to *_SET_SEGMENT — neither is a "
                "single skew axis, so no Dir letter can carry it. dyna2rad "
                "emits an EMPTY /IMPVEL for these (convertbcs.cxx:634-675).")
            continue
        ref = f"nsid={pm.nsid}"
        skew_id = _pm_skew_for(state, pm, keyword, ref)
        grnod_id = state.next_grnod_id()
        motion_id = state.next_id()
        tstart = pm.birth if pm.birth < 1e27 else 0.0
        tstop  = pm.death if pm.death < 1e27 else 0.0
        # PM_VAD_KEYWORD is the SAME dict handlers._pm_vad_supported gates on,
        # so this index can never miss (a VAD outside it never reaches here).
        kw = PM_VAD_KEYWORD[pm.vad]
        lines += _emit_imp_card(kw, motion_id, f"Motion_{motion_id}", pm.lcid,
                                base_dir, grnod_id, pm.sf, tstart, tstop,
                                skew_id)
        lines += _emit_grnod_node(grnod_id, set_title or f"SET_{pm.nsid}", nids)
        locked, zero_fct, fct_lines = _pm_lock_cards(state, pm, keyword, ref)
        lines += fct_lines
        for lock_dir in locked:
            lock_id = state.next_id()
            lines += _emit_imp_card(kw, lock_id, f"Motion_{lock_id}_lock",
                                    zero_fct, lock_dir, grnod_id, 1.0,
                                    tstart, tstop, skew_id)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: gravity loads
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grnod_part(grnod_id: int, title: str, pids: List[int]) -> List[str]:
    """/GRNOD/PART — a node group holding all nodes of the listed parts."""
    lines = [f"/GRNOD/PART/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for p in pids:
        row.append(str(p).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


# ── /GRAV card layout ────────────────────────────────────────────────────────
# grav.cfg (radioss51 FORMAT, LOADS/grav.cfg:110-114) is
#   CARD("%10d%10s%10d%10d%10d          %20lg%20lg", curveid, rad_dir,
#        inputsystem, rad_sensor_id, entityid, xscale, magnitude);
# — note the TEN literal blank columns (51-60) between grnod_ID and Ascale_x.
# The data line is 100 characters wide: Ascale_x right-aligned at column 80,
# Fscale_Y at column 100 (cross-checked against Altair's own reference deck
# demos_example/.../RD-E-1602_Implicit/.../SEAT_0000.rad:10907-10910).
#
# k2rad used to pack the fields with no gap, putting Ascale_x at 51-70 and
# Fscale_Y at 71-90. That happened to READ correctly only while both rendered
# numbers were <= 10 characters, because _f right-aligns in width 20. The
# moment Fscale_Y is longer the field boundary cuts through it and the starter
# silently takes the wrong number — measured with starter_win64.exe:
#
#   Fscale_Y written    starter echo SCALE_Y      verdict
#   -9810               -9810.000000000           ok (5 chars)
#   -0.00980665          9.8066500000000E-03      SIGN LOST -> gravity up
#   -9.810000E-06        0.8100000000000          sign lost + 8e4x magnitude
#
# i.e. every mm/ms (0.00980665) or %.6E deck. Signed Fscale_Y is now the norm
# on both gravity paths, so the gap is not cosmetic.
_GRAV_GAP = " " * 10
_GRAV_COMMENT = ("#funct_IDT       DIR   skew_ID sensor_ID  grnod_ID"
                 "                      Ascale_x            Fscale_Y")


def _emit_grav_card(grav_id: int, title: str, fct: int, direction: str,
                    grnod_id: int, fscale: float,
                    skew_id: int = 0) -> List[str]:
    """One /GRAV card in the column layout grav.cfg specifies (see above).

    ``Ascale_x`` is always 1.0: the starter stores ``GRAV(2,K) = ONE/FCX``
    (hm_read_grav.F:236) and the engine evaluates the curve at ``t * FCX``, so
    it is a divisor on the time abscissa, not an ordinate scale.

    ``skew_id`` names the local system the DIR axis is taken in: the starter
    resolves it to an internal index (hm_read_grav.F:177-186 — a MISSING skew
    id is MSGID=137, a starter ERROR, so only ever pass an id that is really
    emitted) and the engine then adds the acceleration along that skew's row
    for DIR instead of the global axis (gravit.F:150-162,
    ``A(1..3,N) += SKEW(3*N2-2..3*N2, ISK) * AA``). 0 = global.
    """
    return [
        f"/GRAV/{grav_id}",
        title,
        _GRAV_COMMENT,
        f"{_i(fct)}{direction.rjust(10)}{_i(skew_id)}{_i(0)}{_i(grnod_id)}"
        f"{_GRAV_GAP}{_f(1.0)}{_f(fscale)}",
        HDR,
    ]


def _rbody_mains_in_scope(state: ConversionState, rbody_info: Dict,
                          pids: List[int], whole_model: bool,
                          pnodes: Optional[Dict] = None,
                          keyword: str = "") -> Tuple[Set[int], List[int]]:
    """Which parts of a /GRAV scope are rigid, and which /RBODY main nodes the
    /GRAV must therefore load.  Returns ``(rigid_part_pids, main_node_ids)``.

    **Why this exists.** /GRAV adds an ACCELERATION to every node of its group
    (``gravit.F:147``: ``A(N2,N1) = A(N2,N1) + AA``, no mass factor — the mass
    only appears in the external-work term). In ``resol.F`` that happens at
    line 6884, i.e. 1382 lines AFTER ``RBYFOR`` (5502) has already summed the
    secondary-node forces into the rigid-body main node, and before ``RBYVIT``
    (7572) → ``rgbodv.F:109-155`` **overwrites** ``A(1..3,N)`` of every
    secondary from the main (``=``, not ``+=``). Gravity deposited on a rigid
    secondary node is therefore never transmitted and then discarded: net
    effect on motion exactly zero.

    With ``--rigid-cog-master`` (the default since PR #54) the main node is a
    synthesized element-free node at the part centroid, so it is in no element
    and can never appear in a ``/GRNOD/PART``. Measured on a free rigid block
    with ``*LOAD_BODY_Y``: as converted the block never moved (526 cycles, all
    displacements 0, KE = 0); with the main node in the group it free-falls
    exactly (DY 4.727803E-01 vs the analytic 4.727802E-01 mm).

    **The mapping.** For a part that k2rad turned into an /RBODY the part is
    swapped OUT of the /GRNOD/PART and its main node put in instead — what
    dyna2rad does for ``*LOAD_GRAVITY_PART`` (``convertloads.cxx:887-902``,
    ``storeRbodyPIDVsMasterNode``). The main carries the summed mass of the
    whole body (``inirby.F:187-243, 837``), so one main node at ``g`` is the
    exact load, and dropping the secondaries keeps ``WFEXT`` exact too — the
    starter does NOT zero secondary masses, so leaving them in the group would
    accumulate a spurious ``Σ m_secondary·g·v·dt`` in the energy balance
    (``gravit.F:148``) without changing a single displacement.

    A *CONSTRAINED_NODAL_RIGID_BODY is different: its secondaries are ordinary
    nodes of DEFORMABLE parts, so the part cannot be swapped out. Its main is
    added on top (the union the starter itself performs for rigid-material
    parts in ``rbody_part_modif.F90``/``rpart_grav_check`` — which never fires
    on a k2rad deck, because that check is gated on ``npby(21,·) /= 0``, true
    only for rigid bodies auto-generated from a /PART, and k2rad emits explicit
    /RBODY cards). The body accelerates correctly and exactly once: the CNRB
    main carries the summed mass of the secondaries whose own contribution is
    discarded. **Energy bookkeeping is the one thing this costs.** The
    secondaries stay in the /GRNOD/PART (they belong to deformable parts that
    must keep their own gravity), so ``gravit.F:148`` accumulates
    ``Σ m_secondary·g·v·dt`` for them *and* the same mass again through the
    main — a CNRB in scope inflates the reported EXT WORK by its own mass
    contribution without moving a single node differently. That is exactly the
    term swapping rigid PARTS out avoids, and it cannot be avoided here.

    **A deliberate asymmetry, in scoped loads.** A rigid part OUTSIDE the scope
    is NOT pulled in even when it shares nodes with a scoped deformable part:
    its main would then take the whole body's mass at ``g`` where LS-DYNA loads
    only the shared fraction. A rigid CLUSTER that straddles the scope is the
    opposite — a CNRB whose secondaries reach outside, or a
    *CONSTRAINED_RIGID_BODIES merge whose partner part is unscoped — because
    there is no way to load *part* of one rigid body: the cluster has a single
    main node and a single mass. Those get the main anyway (case (b) is also
    what the starter's own ``rpart_grav_check`` does), so the whole cluster
    accelerates at ``g`` where LS-DYNA would give ``g·m_scoped/m_cluster``. The
    load is then an upper bound and the caller warns about it.
    """
    if not rbody_info:
        return set(), []
    # Records are tagged by their builder: "part" = a whole *MAT_RIGID PART
    # (the only kind that may be swapped out of a /GRNOD/PART), "cnrb" = a
    # *CONSTRAINED_NODAL_RIGID_BODY over nodes of deformable parts. Reading the
    # tag rather than re-deriving it from state.parts[p].mid also survives the
    # rbody_info/cnrb_info merge in assembly.py, which is keyed by two id
    # namespaces at once.
    part_keyed = {p for p, info in rbody_info.items()
                  if info.get("kind", "part") == "part"}
    rigid_part_pids = {p for p in pids if p in part_keyed}
    # *CONSTRAINED_RIGID_BODIES slaves are aliased onto their master's record,
    # so several pids can share one ind_node — dedupe on the node, not the pid.
    mains: Set[int] = {rbody_info[p]["ind_node"] for p in rigid_part_pids}
    others = [info for k, info in rbody_info.items() if k not in part_keyed]
    if whole_model:
        mains.update(info["ind_node"] for info in others)
        return rigid_part_pids, sorted(mains)
    # Scoped load: report every rigid cluster the scope only partly covers, so
    # the user knows those bodies get g on their FULL mass (see the docstring).
    partial: Set[int] = set()
    cluster: Dict[int, Set[int]] = defaultdict(set)
    for p in part_keyed:
        cluster[rbody_info[p]["ind_node"]].add(p)
    for main in mains:
        if not cluster[main] <= rigid_part_pids:
            partial.add(main)
    if others:
        if pnodes is None:
            pnodes = _part_node_sets(state)
        scope_nodes: Set[int] = set()
        for p in pids:
            if p not in rigid_part_pids:
                scope_nodes |= pnodes.get(p, set())
        if scope_nodes:
            for info in others:
                if scope_nodes.intersection(info["nodes"]):
                    mains.add(info["ind_node"])
                    if not set(info["nodes"]) <= scope_nodes:
                        partial.add(info["ind_node"])
    if partial:
        shown = ", ".join(str(n) for n in sorted(partial)[:8])
        if len(partial) > 8:
            shown += ", ..."
        state.warn(
            f"{keyword or '*LOAD_*'} -> /GRAV on part(s) {sorted(pids)}: the "
            f"scope covers only PART of the rigid body/bodies whose main "
            f"node(s) are {shown} (a *CONSTRAINED_NODAL_RIGID_BODY reaching "
            "outside the scope, or a *CONSTRAINED_RIGID_BODIES merge with an "
            "unscoped partner). A rigid body has one main node and one mass, "
            "so it cannot be loaded fractionally: the WHOLE cluster is "
            "accelerated at g, where LS-DYNA applies g*m_scoped/m_cluster. The "
            "converted load is an UPPER BOUND on those bodies - scope the load "
            "to the whole cluster if that is not what you want.")
    return rigid_part_pids, sorted(mains)


def _grav_groups(state: ConversionState, part_pids: List[int],
                 main_nodes: List[int], stem: str,
                 part_kind: str = "parts") -> Tuple[List[str], int, int]:
    """Build the /GRNOD cards one /GRAV needs. Returns ``(lines, grnod_id,
    grav_id)``, where ``grnod_id`` is what the /GRAV must reference.

    Three shapes, so the common case stays exactly what it always was:

    * parts only  → one ``/GRNOD/PART`` (unchanged);
    * mains only  → one ``/GRNOD/NODE`` (every loaded part is rigid);
    * both        → ``/GRNOD/PART`` + ``/GRNOD/NODE`` + a ``/GRNOD/GRNOD``
      union, which the starter resolves by group id and de-duplicates
      (``hm_grogronod.F:179-219``).

    Id allocation order is deliberate: the part group and the /GRAV itself keep
    the ids they have always drawn, and the two extra groups are allocated
    afterwards and only when they exist. A load whose scope holds no rigid body
    therefore emits the same /GRNOD cards, with the same ids, as the pre-fix
    converter (the /GRAV card itself changes — see _emit_grav_card).

    The group ids come from ``next_grnod_id()``, not ``next_id()``: k2rad
    re-emits user *SET_NODE groups under their own SID, so a deck with a
    *SET_NODE id at or above the auto-id base would otherwise hand the starter
    two /GRNOD cards with the same id (ERROR 79, no restart file).
    """
    grnod_id = state.next_grnod_id() if part_pids else 0
    grav_id = state.next_id()
    lines: List[str] = []
    if part_pids:
        lines += _emit_grnod_part(grnod_id, f"{stem}_{part_kind}_{grav_id}",
                                  part_pids)
    if main_nodes:
        mains_id = state.next_grnod_id()
        lines += _emit_grnod_node(mains_id, f"{stem}_rbody_mains_{grav_id}",
                                  main_nodes)
        if part_pids:
            union_id = state.next_grnod_id()
            lines += _emit_grnod_grnod(union_id, f"{stem}_group_{grav_id}",
                                       [grnod_id, mains_id])
            grnod_id = union_id
        else:
            grnod_id = mains_id
    return lines, grnod_id, grav_id


def _warn_rbody_mains_added(state: ConversionState, keyword: str,
                            mains: Set[int]) -> None:
    if not mains:
        return
    shown = ", ".join(str(n) for n in sorted(mains)[:8])
    if len(mains) > 8:
        shown += ", ..."
    state.warn(
        f"{keyword} -> /GRAV: the load's scope contains rigid bodies, so the "
        f"/GRNOD also lists their /RBODY main node(s) ({shown}) and rigid "
        "PARTS are represented by their main node instead of their mesh nodes. "
        "Gravity landing on a rigid secondary node is discarded by the engine "
        "(rgbodv.F overwrites A(1:3,N) from the main after GRAVIT has run), so "
        "without this the rigid body does not move at all. k2rad <= PR #88 did "
        "not do this: every gravity deck with a rigid body converts "
        "differently now.")


def _make_gravity_loads(state: ConversionState,
                        rbody_info: Optional[Dict] = None) -> List[str]:
    """*LOAD_GRAVITY_PART → /GRAV (non-modal decks).

    Magnitude: the load is ACCEL × factor(t), NOT one or the other. Manual Vol
    I R16 p.33-57 defines LC as the "Load curve defining factor as a function
    of time" and ACCEL as the "Acceleration (will be multiplied by factor from
    curve)", and Remark 1a adds "A constant factor of 1.0 is assumed if LC is
    not specified". So Fscale_Y = ACCEL in BOTH forms, and fct_IDT = LC only
    picks up the factor curve. (k2rad <= PR #88 wrote Fscale_Y = -1 whenever
    LC > 0, dropping ACCEL entirely — a factor-|ACCEL| under-load on exactly
    the ramped staged-construction decks this keyword exists for.) ACCEL is
    itself optional (its default is 0); a blank ACCEL with a curve means the
    curve carries the whole acceleration, so a factor of 1.0 is substituted
    and the substitution warned about.

    Sign: the R16/R17 manual states NO sign for ACCEL — p.33-57 defines it
    only as an acceleration, and no remark in that keyword's section fixes a
    direction — so the convention is taken from the only authority that does
    fix one, Radioss' own dyna-reader (``convertloads.cxx:859``:
    ``Fscale_Y = -lsdACCEL``). That source file is not part of this repo, but
    the behaviour is reproducible here: feeding the same ``.k`` straight to
    ``starter_win64.exe`` (which reads LS-DYNA through dyna2rad) prints

        SKEW  DIRECTION  LOAD CURVE  SENSOR    SCALE_X        SCALE_Y
           0     Y            1        0    1.000000000  -9810.000000000
        213

    for ``*LOAD_GRAVITY_PART 1 2 1 9810`` on a *MAT_RIGID part — the same
    ``Fscale_Y = -ACCEL``, the same curve, and the same main-node-only group
    this function emits.

    Parts sharing (dof, lc, accel) are grouped into one /GRAV; rigid parts in
    that group are replaced by their /RBODY main node (see
    _rbody_mains_in_scope).

    Modal decks emit NO /GRAV: gravity does not change a non-prestressed
    eigenproblem, and the stiffness-export run must stay load-consistent with
    the eigensolve.  A NOTE (not a bare "skipped") records that.
    """
    if not state.gravity_loads:
        return []
    if state.is_modal:
        state.warn(
            "NOTE: *LOAD_GRAVITY_PART is not emitted for a modal deck - "
            "gravity does not affect a non-prestressed eigenproblem, so the "
            "stiffness-export/eigen run omits /GRAV. (A non-modal conversion "
            "maps it to /GRAV.)")
        return [
            "#-  *LOAD_GRAVITY_PART: intentionally NOT converted for the modal",
            "#-  (eigenvalue) run - gravity is irrelevant to a non-prestressed",
            "#-  eigenproblem. A non-modal conversion emits /GRAV instead.",
            HDR,
        ]
    rbody_info = rbody_info or {}
    _DIR = {1: "X", 2: "Y", 3: "Z"}
    groups: Dict[Tuple[int, int, float], List[int]] = {}
    for g in state.gravity_loads:
        groups.setdefault((g.dof, g.lc, g.accel), []).append(g.pid)
        if g.lcdr:
            state.warn(f"LOAD_GRAVITY_PART pid={g.pid}: dynamic-relaxation "
                       f"curve LCDR={g.lcdr} has no OpenRadioss mapping - "
                       "ignored (only the transient gravity is converted).")
        if g.stga or g.stgr:
            state.warn(f"LOAD_GRAVITY_PART pid={g.pid}: staged-construction "
                       f"stages STGA/STGR={g.stga}/{g.stgr} are not supported "
                       "- gravity is applied for the whole run.")
    lines: List[str] = ["#-  GRAVITY LOADS (*LOAD_GRAVITY_PART):", HDR]
    added_mains: Set[int] = set()
    # Built once: _rbody_mains_in_scope needs the {pid: nodes} inventory for
    # every scoped group, and rebuilding it walks every solid/shell/beam.
    pnodes = _part_node_sets(state) if rbody_info else {}
    for (dof, lc, accel), pids in sorted(groups.items()):
        if lc > 0 and lc not in state.curves:
            state.warn(f"LOAD_GRAVITY_PART: load curve {lc} not found - "
                       f"gravity on part(s) {pids} skipped.")
            continue
        pids = sorted(set(pids))
        if accel == 0.0 and lc == 0:
            # Fscale_Y = 0 does NOT mean "no gravity": hm_read_grav.F:190 does
            # IF (FCY == ZERO) FCY = FAC_FCY, silently turning it into the unit
            # -system dimension factor (1.0 in a consistent system). A zero
            # ACCEL with no curve is zero gravity, so emit nothing at all.
            state.warn(f"LOAD_GRAVITY_PART part(s) {pids}: ACCEL = 0 with no "
                       "load curve is zero gravity - no /GRAV emitted (a /GRAV "
                       "with Fscale_Y = 0 would be read back as 1.0 by the "
                       "starter, hm_read_grav.F:190).")
            continue
        rigid_pids, mains = _rbody_mains_in_scope(
            state, rbody_info, pids, whole_model=False, pnodes=pnodes,
            keyword="*LOAD_GRAVITY_PART")
        added_mains.update(mains)
        part_pids = [p for p in pids if p not in rigid_pids]
        if not part_pids and not mains:
            continue
        glines, grnod_id, grav_id = _grav_groups(state, part_pids, mains,
                                                 "gravity")
        lines += glines
        # The load is ACCEL x factor(t) (manual p.33-57), so Fscale_Y = -ACCEL
        # in both forms and fct_IDT only selects the factor curve. ACCEL's own
        # default is 0, so a blank ACCEL alongside a curve means the curve is
        # the acceleration: substitute the factor 1.0 rather than emit a load
        # of literally zero.
        fct = lc if lc > 0 else 0
        if accel == 0.0:
            state.warn(f"LOAD_GRAVITY_PART part(s) {pids}: ACCEL is 0/blank "
                       f"with load curve {lc} - taken as ACCEL = 1.0, i.e. "
                       "curve LC carries the whole acceleration (the literal "
                       "reading, ACCEL x factor, would be zero load).")
            accel = 1.0
        lines += _emit_grav_card(
            grav_id,
            f"Gravity_{_DIR[dof]}_parts_" + "_".join(str(p) for p in pids),
            fct, _DIR[dof], grnod_id, -accel)
    _warn_rbody_mains_added(state, "*LOAD_GRAVITY_PART", added_mains)
    return lines if len(lines) > 2 else []


def _make_body_loads(state: ConversionState,
                     rbody_info: Optional[Dict] = None) -> List[str]:
    """*LOAD_BODY_{X,Y,Z} (+ *LOAD_BODY_PARTS scoping) → /GRAV.

    The load is a base acceleration along the named axis, and a POSITIVE card
    acts along the NEGATIVE axis. Manual Vol I R16 p.33-27/33-28: "base
    acceleration may be thought of as accelerating the coordinate system in the
    direction specified, and, thus, the inertial loads acting on the model are
    of opposite sign", and the manual's own *LOAD_BODY_Z example — SF = 0.00981
    on a constant +1.0 curve, commented "Add gravity such that it acts in the
    negative Z-direction" — is annotated "Note: Positive body load acts in the
    negative direction." So Fscale_Y = -SF, which is also what the Radioss
    dyna-reader emits (``convertloads.cxx:247``: ``Fscale_Y = -lsdSF``). That
    source file is not part of this repo, but the behaviour is reproducible
    here: read the same ``.k`` straight into ``starter_win64.exe`` and its
    GRAVITY LOADS echo gives ``SCALE_Y = -9810`` for ``SF = +9810`` and
    ``SCALE_Y = +9810`` for ``SF = -9810`` — an unconditional negation. The
    manual's *LOAD_BODY_VECTOR example is a third, independent confirmation:
    it specifies ``-1.0, -1.0, -1.0`` to obtain a body force in the POSITIVE
    (1,1,1) direction (p.33-29).

    Scope is the whole model unless a *LOAD_BODY_PARTS card names a part set
    (manual p.33-25; only one such card is permitted per deck, so the last one
    wins). Every *LOAD_BODY_* card in the deck shares that one scope, so the
    /GRNOD group is built once and all the /GRAV cards reference it.

    CID names a local system the acceleration is given in ("The accelerations
    (LCID) are with respect to CID", p.33-27) and becomes the /GRAV skew_ID.
    Rigid parts in scope are represented by their /RBODY main node; see
    _rbody_mains_in_scope.

    Modal decks emit nothing (a body load is a static preload, irrelevant to a
    non-prestressed eigenproblem).
    """
    any_body = bool(state.body_loads or state.body_load_vectors
                    or state.body_load_rots)
    if not any_body or state.is_modal:
        if state.body_load_psid and not state.is_modal:
            # Parsed, stored, and then nothing consumed it: without this the
            # conversion log says nothing at all about the card (it has a
            # handler, so it never reaches skipped_keywords either).
            state.note_recognized_not_emitted(
                "LOAD_BODY_PARTS",
                f"part set {state.body_load_psid} scopes the *LOAD_BODY_* "
                "cards, but the deck has no *LOAD_BODY_{X,Y,Z} card for it to "
                "scope - nothing emitted.")
        return []
    rbody_info = rbody_info or {}
    whole_model = True
    part_kind = "allparts"
    all_pids = sorted(state.parts)
    psid = state.body_load_psid
    if psid:
        pset = state.part_sets.get(psid)
        scoped = sorted({p for p in pset[1] if p in state.parts}) if pset else []
        if not scoped:
            state.warn(
                f"*LOAD_BODY_PARTS: part set {psid} "
                + ("is empty or names no known part"
                   if pset else "not found")
                + " - the body load is applied to the whole model instead.")
        else:
            all_pids = scoped
            whole_model = False
            part_kind = f"pset{psid}"
    if not all_pids:
        return []
    rigid_pids, mains = _rbody_mains_in_scope(state, rbody_info, all_pids,
                                              whole_model=whole_model,
                                              keyword="*LOAD_BODY_*")
    part_pids = [p for p in all_pids if p not in rigid_pids]
    if not part_pids and not mains:
        return []
    lines: List[str] = ["#-  BODY LOADS (*LOAD_BODY_* -> /GRAV):", HDR]
    emitted = False
    grnod_id: Optional[int] = None
    # The scope is deck-global, so ONE group serves every *LOAD_BODY_* card of
    # every flavour. It is built on the first card that survives its checks
    # rather than before the loop, which keeps the first card's ids exactly where
    # they have always been (byte-identity for _X/_Y/_Z-only decks).
    def _first_group():
        nonlocal grnod_id, lines
        glines, grnod_id, load_id = _grav_groups(state, part_pids, mains,
                                                 "body_load", part_kind)
        lines += glines
        return load_id

    for bl in state.body_loads:
        if bl.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_{bl.dir}: load curve {bl.lcid} not found "
                       "— skipped.")
            continue
        emitted = True
        grav_id = _first_group() if grnod_id is None else state.next_id()
        skew_id = 0
        if bl.cid:
            if (bl.cid in state.coord_sys or bl.cid in state.coord_nodes
                    or bl.cid in state.coord_vectors):
                skew_id = bl.cid
            else:
                state.warn(
                    f"*LOAD_BODY_{bl.dir}: local system CID={bl.cid} not found "
                    "— the base acceleration is applied along the GLOBAL "
                    f"{bl.dir} axis.")
        lines += _emit_grav_card(grav_id, f"Body_accel_{bl.dir}", bl.lcid,
                                 bl.dir, grnod_id, -bl.sf, skew_id)
    if emitted:
        state.warn(
            "*LOAD_BODY_{X,Y,Z} -> /GRAV with Fscale_Y = -SF: a POSITIVE LS-DYNA "
            "body load acts along the NEGATIVE axis (Manual Vol I R16 p.33-28, "
            "\"Positive body load acts in the negative direction\"), matching the "
            "Radioss dyna-reader (convertloads.cxx:247) and this converter's own "
            "*LOAD_GRAVITY_PART path. k2rad <= PR #88 wrote Fscale_Y = +SF, so a "
            "deck converted with an older version has the body-load direction "
            "REVERSED.")

    # ── *LOAD_BODY_VECTOR → /GRAV along a synthesized skew's local X' ─────────
    # The two summary warnings below are gated on EMISSION, not on the presence
    # of a parsed card: a *LOAD_BODY_VECTOR whose LCID is missing warns "load
    # curve N not found — skipped" and must not then be followed by a paragraph
    # describing the /GRAV + /SKEW/FIX pair it did not produce.
    vec_emitted = False
    for bv in state.body_load_vectors:
        if bv.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_VECTOR: load curve {bv.lcid} not found "
                       "— skipped.")
            continue
        v = bv.v
        if bv.cid:
            basis = _icid_basis(state, bv.cid)
            if basis is None:
                state.warn(
                    f"*LOAD_BODY_VECTOR: local system CID={bv.cid} not found — "
                    "V1/V2/V3 are taken as GLOBAL components. THE LOAD "
                    "DIRECTION IS WRONG unless that system is global-aligned. "
                    "(The Radioss dyna-reader is worse here: a failed lookup "
                    "leaves it building a /SKEW/FIX from two null vectors, "
                    "convertloads.cxx:607-652.)")
            else:
                # V1..V3 are components IN the CID basis: V_global = X'*V1 +
                # Y'*V2 + Z'*V3 (the same mapping convertloads.cxx:620-624 does).
                v = _local_to_global(basis, bv.v)
        axes = _ortho_skew_axes(v)
        if axes is None:                    # guarded in the handler; belt-and-braces
            state.warn("*LOAD_BODY_VECTOR: the direction vector is degenerate "
                       "after mapping through CID — skipped.")
            continue
        emitted = True
        vec_emitted = True
        grav_id = _first_group() if grnod_id is None else state.next_id()
        skew_id = state.reserve_skew_id(state.next_id())
        # /SKEW/FIX's two vector cards are the local Y' and Z'; the starter
        # rebuilds X' = Y' x Z' (hm_read_skw.F:448-459), and _ortho_skew_axes
        # returns the pair for which that is exactly +V. Origin = (XC,YC,ZC),
        # which is inert for a uniform acceleration field but is where dyna2rad
        # puts it too (convertloads.cxx:668).
        lines += _emit_skew_fix(skew_id, f"SKEW_FIX_GRAV_{grav_id}",
                                (bv.xc, bv.yc, bv.zc), axes[0], axes[1])
        lines += _emit_grav_card(grav_id, "Body_accel_VECTOR", bv.lcid,
                                 "X", grnod_id, -bv.sf, skew_id)
    if vec_emitted:
        state.warn(
            "*LOAD_BODY_VECTOR -> ONE /GRAV with DIR=X in a companion /SKEW/FIX "
            "whose local X' is +V, and Fscale_Y = -SF. The two halves belong "
            "together: /GRAV adds +Fscale_Y*f(t) along DIR (gravit.F:147), so "
            "the applied acceleration is -SF*f(t)*V_hat, i.e. along -V — which "
            "is what LS-DYNA prescribes (Manual Vol I R16 p.33-29: the manual's "
            "own validation example writes V = (-1,-1,-1) to obtain gravity "
            "along +(1,1,1)). Reproducing only one half flips the load. |V| is "
            "irrelevant: the starter normalises the skew, and LS-DYNA uses V as "
            "a direction only.")

    # ── *LOAD_BODY_RX/_RY/_RZ → /LOAD/CENTRI (+ /FRAME/FIX for the axis) ──────
    # The section HEADER is INSERTED at the position it would have been appended
    # at, and only if a card was actually written: a deck whose R* curves are all
    # missing used to get a dangling header plus two paragraphs describing
    # /LOAD/CENTRI cards the .rad does not contain. Inserting (rather than
    # buffering the cards) keeps the header ahead of the shared /GRNOD that
    # _first_group() emits inside the loop, so a deck that DOES emit converts
    # byte-identically.
    rot_header_at = len(lines)
    rot_emitted = False
    for br in state.body_load_rots:
        if br.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_R{br.dir}: angular-velocity curve "
                       f"{br.lcid} not found — skipped (fct_IDT is mandatory on "
                       "/LOAD/CENTRI: a missing function is starter ERROR 883).")
            continue
        emitted = True
        rot_emitted = True
        centri_id = _first_group() if grnod_id is None else state.next_id()
        frame_id, flines = _centri_frame(state, br)
        lines += flines
        lines += _emit_centri_card(centri_id, f"Body_omega_{br.dir}", br.lcid,
                                   br.dir * 2, frame_id, grnod_id, br.sf)
    if rot_emitted:
        lines[rot_header_at:rot_header_at] = [
            "#-  ROTATIONAL BODY LOADS (*LOAD_BODY_R* -> /LOAD/CENTRI):", HDR]
        state.warn(
            "*LOAD_BODY_R{X,Y,Z} -> /LOAD/CENTRI with fct_IDT = LCID and "
            "Fscaley = +SF. The curve carries the ANGULAR VELOCITY omega(t), "
            "LINEARLY: LS-DYNA forms b = rho*[omega x (omega x r)] internally "
            "(Manual Vol I R16 p.33-20 Remark 3) and the OpenRadioss engine "
            "squares the curve for itself (cfield.F: VROT = Fscaley*f(t), then "
            "VROT2 = VROT*VROT, AREL = r_perp*VROT2). Do NOT pre-square or "
            "square-root it. There is NO sign flip either — unlike the "
            "translational forms, both codes apply the acceleration radially "
            "OUTWARD. Ivar = 1, so the dOmega/dt Euler term is omitted, which "
            "is what LS-DYNA does too (Remark 2: \"torsional effects due to "
            "changes in angular velocity are neglected\").")
        state.warn(
            "*LOAD_BODY_R{X,Y,Z} -> /LOAD/CENTRI Dir is written as XX/YY/ZZ, "
            "not X/Y/Z. The starter accepts both (hm_read_load_centri.F:206-211 "
            "maps X/Y/Z to IDIR 1/2/3 and XX/YY/ZZ to 4/5/6) but the engine's "
            "cfield.F:132-144 only branches on 4 and 5, so IDIR 1/2/3 all fall "
            "into the ELSE and rotate about the FRAME'S Z AXIS - silently, with "
            "no error and no warning (measured). The Radioss dyna-reader writes "
            "X/Y/Z (convertloads.cxx:271-288) and is therefore wrong for RX and "
            "RY, and right for RZ only by accident.")
    if not emitted:
        return []
    _warn_rbody_mains_added(state, "*LOAD_BODY_*", set(mains))
    return lines


# ── /LOAD/CENTRI card layout ─────────────────────────────────────────────────
# centri.cfg (radioss120 FORMAT, LOADS/centri.cfg:79) is
#   CARD("%10d%10s%10d%10d%10d%10d%20lg%20lg", curveid, rad_dir, inputsystem,
#        rad_sensor_id, entityid, rad_ivar_flag, xscale, magnitude);
# — note cols 51-60 hold Ivar and are NOT blank. /GRAV's grid looks the same up
# to col 50 but has ten LITERAL blanks there (see _GRAV_GAP), so the two cards
# must NOT share a formatter: writing /GRAV's blank gap here would leave Ivar
# unset (harmless, defaults to 1) while writing Ivar into a /GRAV would be read
# as nothing at all in a field the reader skips.
_CENTRI_COMMENT = ("#funct_IDT       Dir  frame_ID sensor_ID  grnod_ID"
                   "      Ivar             Ascalex             Fscaley")


def _emit_centri_card(load_id: int, title: str, fct: int, direction: str,
                      frame_id: int, grnod_id: int, fscale: float,
                      ivar: int = 1) -> List[str]:
    """One /LOAD/CENTRI card.

    ``direction`` must be ``"XX"``, ``"YY"`` or ``"ZZ"`` (right-justified) — see
    the Dir warning in _make_body_loads. ``Ascalex`` is always 1.0: like /GRAV's
    it is an abscissa DIVISOR (``CFIELD(2,K) = ONE/FCX``), and with ``Ivar = 2``
    the engine's Euler term would additionally be off by that factor because
    ``DWDT = FAC(1,NL)*DYDX`` omits the chain-rule ``1/Ascalex``.
    """
    return [
        f"/LOAD/CENTRI/{load_id}",
        title,
        _CENTRI_COMMENT,
        f"{_i(fct)}{direction.rjust(10)}{_i(frame_id)}{_i(0)}{_i(grnod_id)}"
        f"{_i(ivar)}{_f(1.0)}{_f(fscale)}",
        HDR,
    ]


def _centri_frame(state: ConversionState, br) -> Tuple[int, List[str]]:
    """The /FRAME/FIX a *LOAD_BODY_R* rotation axis needs, as
    ``(frame_id, lines)``. ``frame_id = 0`` (global axes through the global
    origin) when the card names neither a centre nor a CID — ``XFRAME(:,1)`` is
    initialised to the identity with origin (0,0,0),
    ``hm_read_frm.F:133-135``, so no card is needed at all.

    A CID SUPERSEDES XC/YC/ZC: the frame is then the CID's own origin and axes.
    That is a CHOICE, not a documented rule — *LOAD_BODY's card says only
    "Coordinate system ID to define acceleration in local coordinate system. The
    accelerations (LCID) are with respect to CID" (Manual Vol I R16 p.33-27) and
    is SILENT on how CID interacts with the centre of rotation. It follows
    dyna2rad, whose ``_SYSTEM`` branch copies the CID skew's origin verbatim and
    ignores XC/YC/ZC (``convertloads.cxx:325-385``), and it is warned loudly
    whenever a deck supplies both. Note the sibling *LOAD_BODY_GENERALIZED
    documents the OPPOSITE for its own card — "the coordinate (XC, YC, ZC) is
    defined with respect to the local coordinate system if CID is nonzero"
    (p.33-32) — so if that reading is the intended one for *LOAD_BODY too, the
    frame origin should be ``CID_origin + R*(XC,YC,ZC)`` instead.

    Frame ids are drawn one per card from ``reserve_skew_id``: /FRAME and /SKEW
    share ONE starter table, so a collision is ERROR 79. (dyna2rad calls
    ``GetDynaMaxEntityID`` inside the loop, which returns the SAME id every time
    and gives a deck with two *LOAD_BODY_R* cards two /FRAMEs with one id.)
    """
    origin = (br.xc, br.yc, br.zc)
    yax, zax = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    if br.cid:
        basis = _icid_basis(state, br.cid)
        if basis is None:
            state.warn(
                f"*LOAD_BODY_R{br.dir}: local system CID={br.cid} not found — "
                "the rotation axis uses the GLOBAL axes"
                + (f" through ({br.xc:g}, {br.yc:g}, {br.zc:g})" if any(origin)
                   else " through the global origin")
                + ". THE AXIS IS WRONG unless that system is global-aligned. "
                "(dyna2rad silently attaches no frame at all on this path, "
                "convertloads.cxx:342, which additionally loses XC/YC/ZC.)")
        else:
            ex, ey, ez = basis
            yax, zax = ey, ez
            cs = state.coord_sys.get(br.cid)
            cid_origin = (cs.xo, cs.yo, cs.zo) if cs is not None else None
            if cid_origin is None:
                cn = state.coord_nodes.get(br.cid)
                if cn is not None:
                    from .mesh import _skew_axes_from_nodes
                    axes = _skew_axes_from_nodes(state, cn)
                    cid_origin = axes[0] if axes else None
            if cid_origin is None:
                # *DEFINE_COORDINATE_VECTOR has axes but no origin point.
                cid_origin = (0.0, 0.0, 0.0)
            if any(origin) and cid_origin != origin:
                state.warn(
                    f"*LOAD_BODY_R{br.dir}: both CID={br.cid} and a centre of "
                    f"rotation ({br.xc:g}, {br.yc:g}, {br.zc:g}) are given. "
                    f"k2rad lets CID win: the axis passes through the CID origin "
                    f"{cid_origin} and XC/YC/ZC are IGNORED, which is what "
                    "dyna2rad does (convertloads.cxx:325-385). The *LOAD_BODY "
                    "card does NOT document how the two interact (p.33-27 covers "
                    "only the acceleration direction), and the sibling "
                    "*LOAD_BODY_GENERALIZED documents the opposite for its own "
                    "card — \"the coordinate (XC, YC, ZC) is defined with respect "
                    "to the local coordinate system if CID is nonzero\" (p.33-32) "
                    "— which would put the axis through CID_origin + R*(XC,YC,ZC). "
                    "Give only one of the two if the axis position matters.")
            origin = cid_origin
    if not br.cid and not any(origin):
        return 0, []                        # frame 0 = global axes at (0,0,0)
    frame_id = state.reserve_skew_id(state.next_id())
    return frame_id, _emit_frame_fix(
        frame_id, f"FRAME_FIX_LOAD_CENTRI_{frame_id}", origin, yax, zax)


# ─────────────────────────────────────────────────────────────────────────────
# Starter: initial conditions
# ─────────────────────────────────────────────────────────────────────────────

def _emit_inivel(kind: str, inivel_id: int, title: str, grnod_id: int,
                 v: Tuple[float, float, float], skew_id: int = 0) -> List[str]:
    """One /INIVEL/TRA|ROT block — a single data card after the title:
    Vx(20) Vy(20) Vz(20) Gnod_id(10) Skew_id(10)."""
    return [
        f"/INIVEL/{kind}/{inivel_id}",
        title,
        "#                 Vx                  Vy                  Vz   Gnod_id   Skew_id",
        f"{_f(v[0])}{_f(v[1])}{_f(v[2])}{_i(grnod_id)}{_i(skew_id)}",
        HDR,
    ]


def _make_inivel(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Initial velocities → /INIVEL/TRA (+ /INIVEL/ROT for rotational DOFs).

    The only valid /INIVEL subtypes are TRA/ROT (cfg inivel.cfg); rotational
    components need their own /INIVEL/ROT block. For rigid bodies the velocity
    goes on the MASTER node only — its 6 DOFs drive the body, and secondary-
    node values are overridden by /RBODY kinematics anyway.
    """
    lines: List[str] = []

    vel_groups: Dict[Tuple, List[int]] = defaultdict(list)
    for iv in state.inivel_nodes:
        vel_groups[(iv.vx, iv.vy, iv.vz, iv.vxr, iv.vyr, iv.vzr)].append(iv.nid)

    for vel_key, nids in vel_groups.items():
        vx, vy, vz, vxr, vyr, vzr = vel_key
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_nodes_{grnod_id}", sorted(nids))
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVel_{inivel_id}",
                              grnod_id, (vx, vy, vz))
        if vxr or vyr or vzr:
            rot_id = state.next_id()
            lines += _emit_inivel("ROT", rot_id, f"InitVelRot_{rot_id}",
                                  grnod_id, (vxr, vyr, vzr))

    for iv in state.inivel_rbodies:
        info = rbody_info.get(iv.pid)
        if not info:
            state.warn(f"INITIAL_VELOCITY_RIGID_BODY pid={iv.pid}: no RBODY found – skipped")
            continue
        grnod_id = info["ind_grnod_id"]
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVelRB_{inivel_id}",
                              grnod_id, (iv.vx, iv.vy, iv.vz))
        if iv.vxr or iv.vyr or iv.vzr:
            rot_id = state.next_id()
            lines += _emit_inivel("ROT", rot_id, f"InitVelRBRot_{rot_id}",
                                  grnod_id, (iv.vxr, iv.vyr, iv.vzr))

    lines += _make_inertia_inivel(state, rbody_info)

    if lines:
        lines = ["#-  INITIAL CONDITIONS:", HDR] + lines
    return lines


def _make_inertia_inivel(state: ConversionState, rbody_info: Dict) -> List[str]:
    """`_INERTIA` card 5 ``VTX..VRZ`` → /INIVEL/TRA + /INIVEL/ROT on the main node.

    **Why the main node alone is exact.** /INIVEL/ROT has no axis and no origin: it
    writes its three components straight into the nodal rotational-velocity vector
    (``hm_read_inivel.F:535-541``: ``VR(1,NOSYS)=V1`` ... for every node of the
    group), and ``inirby.F`` then propagates the main node's ``V``/``VR`` to the
    secondaries as a rigid field about the main node's position,
    ``V(:,N) = V(:,M) + omega x (X_N - X_M)``. With ICoG=4 that position IS the
    centre of mass the card states, so putting ``VTX..VTZ`` and ``VRX..VRZ`` on a
    group containing only the main node reproduces "translational/rotational
    velocity about the centre of mass" with no correction term — a pure
    translation and a pure omega are both position-independent, which is why
    /INIVEL/AXIS (the only variant that carries an origin, via a /FRAME) is not
    needed and must not be used ("This option cannot be used when /INIVEL/TRA or
    /INIVEL/ROT is applied on the same node").

    ``IRODDL > 0`` is required for the ``VR`` write to happen at all, and
    ``contrl.F:1053`` includes ``NRBODY`` in that MIN(), so any /RBODY in the deck
    guarantees it — always true here.

    **Double-application guard.** *PART Remark 5: "The *INITIAL_VELOCITY card may
    overwrite the initial velocity of the rigid body." Radioss /INIVEL ASSIGNS
    (``V(1,NOSYS) = V1``) rather than accumulating, so two cards on the same node
    are not additive — the LAST one read wins. An
    `*INITIAL_VELOCITY_RIGID_BODY` on the same body therefore makes the card-5
    values dead weight, and they are dropped here with a warning instead of being
    written to be silently overwritten. The whole-model and generated forms are
    warned but kept: they are emitted by LATER sections
    (``_make_initial_velocity`` / ``_make_initial_velocity_generation``), so
    Radioss reads them after these cards and LS-DYNA's precedence falls out of the
    section order by itself.
    """
    if not state.part_inertias and not any(c.inertia for c in state.cnrbs):
        return []
    # Bodies an *INITIAL_VELOCITY_RIGID_BODY already drives, by part id.
    iv_rb_pids = {iv.pid for iv in state.inivel_rbodies}
    # A whole-model *INITIAL_VELOCITY (NSID blank/0 → "whole model", which by then
    # includes the synthesized main node) or an *INITIAL_VELOCITY_GENERATION with
    # STYP=0 covers every node, main nodes included.
    global_iv = ([f"*INITIAL_VELOCITY with NSID={iv.nsid or 0}"
                  for iv in state.inivel_general
                  if not iv.nsid and (iv.vx or iv.vy or iv.vz
                                      or iv.vxr or iv.vyr or iv.vzr)]
                 + [f"*INITIAL_VELOCITY_GENERATION with STYP={g.styp}"
                    for g in state.inivel_generations if not g.styp])

    todo: List[Tuple[int, str, object]] = [
        (pid, f"*PART_INERTIA {pid}", inr)
        for pid, inr in sorted(state.part_inertias.items())]
    todo += [(c.pid, f"*CONSTRAINED_NODAL_RIGID_BODY_INERTIA pid={c.pid}",
              c.inertia) for c in state.cnrbs if c.inertia is not None]

    lines: List[str] = []
    for pid, label, inr in todo:
        if not inr.has_velocity():
            continue
        info = rbody_info.get(pid)
        if not info:
            state.warn(
                f"{label}: the card-5 initial velocity "
                f"(VT={inr.vtx:g},{inr.vty:g},{inr.vtz:g} "
                f"VR={inr.vrx:g},{inr.vry:g},{inr.vrz:g}) is DROPPED — no /RBODY "
                "was emitted for that id, so there is no main node to put it on.")
            continue
        if pid in iv_rb_pids:
            state.warn(
                f"{label}: the card-5 initial velocity is DROPPED because "
                f"*INITIAL_VELOCITY_RIGID_BODY also drives part {pid}. *PART "
                "Remark 5 gives *INITIAL_VELOCITY precedence ('may overwrite the "
                "initial velocity of the rigid body'), and Radioss /INIVEL "
                "ASSIGNS rather than accumulates, so emitting both would leave "
                "the result decided by card order. Remove one of the two cards.")
            continue
        if global_iv:
            state.warn(
                f"{label}: the card-5 initial velocity is applied to /RBODY main "
                f"node {info['ind_node']}, but {global_iv[0]} covers every node "
                "in the model including that one. Radioss /INIVEL assigns rather "
                "than accumulates and the whole-model card is written LATER in "
                "the deck, so it WINS — which is LS-DYNA's own precedence (*PART "
                "Remark 5), but scope the whole-model card if that is not what "
                "was meant.")
        grnod_id = info["ind_grnod_id"]
        if inr.vtx or inr.vty or inr.vtz:
            tid = state.next_id()
            lines += _emit_inivel("TRA", tid, f"InitVelInertia_{tid}", grnod_id,
                                  (inr.vtx, inr.vty, inr.vtz))
        if inr.vrx or inr.vry or inr.vrz:
            rid = state.next_id()
            lines += _emit_inivel("ROT", rid, f"InitVelInertiaRot_{rid}", grnod_id,
                                  (inr.vrx, inr.vry, inr.vrz))
    return lines


def _vdot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _icid_basis(state: ConversionState, cid: int):
    """Global-frame orthonormal basis (ex, ey, ez) of the converted /SKEW whose id
    is *cid* — the local axes of the *DEFINE_COORDINATE_* system, built exactly as
    _make_skews emits them. Returns None when cid has no converted skew (the
    velocity/axis then stay global). Pre-rotating with this basis reproduces what
    Radioss would do if the components carried a Skew_id (as the plain
    *INITIAL_VELOCITY path does)."""
    cs = state.coord_sys.get(cid)
    if cs is not None:
        origin = (cs.xo, cs.yo, cs.zo)
        ex = _vnorm(_vsub((cs.xl, cs.yl, cs.zl), origin))
        if ex is None:
            return None
        ez = _vnorm(_vcross(ex, _vsub((cs.xp, cs.yp, cs.zp), origin)))
        if ez is None:
            return None
        return ex, _vcross(ez, ex), ez
    cn = state.coord_nodes.get(cid)
    if cn is not None:
        from .mesh import _skew_axes_from_nodes
        axes = _skew_axes_from_nodes(state, cn)
        if axes is None:
            return None
        _origin, xax, yax = axes
        return xax, yax, _vcross(xax, yax)
    cv = state.coord_vectors.get(cid)
    if cv is not None:
        # Same basis _emit_coord_vector_skew builds: ex = X̂, ez = X × V, ey = ez × ex.
        ex = _vnorm((cv.xx, cv.yx, cv.zx))
        if ex is None:
            return None
        ez = _vnorm(_vcross((cv.xx, cv.yx, cv.zx), (cv.xv, cv.yv, cv.zv)))
        if ez is None:
            return None
        return ex, _vcross(ez, ex), ez
    return None


def _local_to_global(basis, v):
    """Express a vector whose components *v* are given in the local *basis*
    (columns ex, ey, ez, in global coords) back in global coords:
    g = v0·ex + v1·ey + v2·ez."""
    ex, ey, ez = basis
    return (v[0] * ex[0] + v[1] * ey[0] + v[2] * ez[0],
            v[0] * ex[1] + v[1] * ey[1] + v[2] * ez[1],
            v[0] * ex[2] + v[1] * ey[2] + v[2] * ez[2])


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_BOX membership (numeric node scoping — no /BOX entity emitted)
# ─────────────────────────────────────────────────────────────────────────────

def _box_basis(box):
    """Orthonormal (origin, ex, ey, ez) of a _LOCAL box's frame, built exactly
    as dyna2rad does (convertboxes.cxx): ex = X̂, ez = normalize(X × V), ey =
    ez × ex. Returns None when the X vector is zero or X∥V (a degenerate frame
    with no interior)."""
    ex = _vnorm((box.xx, box.yx, box.zx))
    if ex is None:
        return None
    ez = _vnorm(_vcross((box.xx, box.yx, box.zx), (box.xv, box.yv, box.zv)))
    if ez is None:
        return None
    ey = _vcross(ez, ex)                          # unit (ez ⟂ ex, both unit)
    return (box.cx, box.cy, box.cz), ex, ey, ez


def _box_global_corners(box):
    """Global diagonal corner points (P1, P2) of a box. Plain: the global
    min/max corners. _LOCAL: the local min/max extents baked through the box
    frame (P1 = origin + xmn·ex + ymn·ey + zmn·ez), matching dyna2rad's
    rotateVector corner bake. Returns None for a degenerate _LOCAL frame."""
    lo = (min(box.xmn, box.xmx), min(box.ymn, box.ymx), min(box.zmn, box.zmx))
    hi = (max(box.xmn, box.xmx), max(box.ymn, box.ymx), max(box.zmn, box.zmx))
    if not box.local:
        return lo, hi
    basis = _box_basis(box)
    if basis is None:
        return None
    origin, ex, ey, ez = basis
    p1 = _local_to_global((ex, ey, ez), lo)
    p2 = _local_to_global((ex, ey, ez), hi)
    p1 = (p1[0] + origin[0], p1[1] + origin[1], p1[2] + origin[2])
    p2 = (p2[0] + origin[0], p2[1] + origin[1], p2[2] + origin[2])
    return p1, p2


def _box_contains(box, x: float, y: float, z: float) -> bool:
    """True if the global point (x,y,z) lies in the box. A _LOCAL box tests the
    point's coordinates in the box frame; a plain box tests global coordinates
    against its axis-aligned extents (min/max taken per axis, so P1/P2 may be
    given in either diagonal order)."""
    lox, hix = min(box.xmn, box.xmx), max(box.xmn, box.xmx)
    loy, hiy = min(box.ymn, box.ymx), max(box.ymn, box.ymx)
    loz, hiz = min(box.zmn, box.zmx), max(box.zmn, box.zmx)
    if box.local:
        basis = _box_basis(box)
        if basis is None:
            return False
        origin, ex, ey, ez = basis
        d = (x - origin[0], y - origin[1], z - origin[2])
        u, v, w = _vdot(d, ex), _vdot(d, ey), _vdot(d, ez)
    else:
        u, v, w = x, y, z
    return lox <= u <= hix and loy <= v <= hiy and loz <= w <= hiz


def _box_node_ids(state: ConversionState, box) -> Set[int]:
    """Set of node ids whose coordinates fall inside *box* (O(nodes) scan — the
    same cost class as the existing NSIDEX set-difference; there is no spatial
    index in the codebase). The _LOCAL frame is computed once.

    Only the SOURCE deck's nodes are candidates. By write time ``state.nodes``
    also holds everything the writer synthesized — /RBODY CoG masters, /SKEW/MOV
    third nodes, the *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL triads, rigid-wall
    carriers, *ELEMENT_BEAM_ORIENTATION third nodes — and a *DEFINE_BOX names a
    region of the USER's model, so those artefacts must not be picked up.
    Measured: a box-only ``*BOUNDARY_PRESCRIBED_MOTION_SET_BOX`` round a rigid
    brick emitted an /IMPVEL on the brick's synthesized /RBODY MASTER node, i.e.
    drove the whole body (starter WARNING 312, 0 errors, restart written — the
    wrong model runs), and the ``if not box_nodes`` guard cannot see it because
    the box does contain nodes, just the wrong ones. ``source_node_ids`` is empty
    only when build_starter has not run (direct unit-test calls), in which case
    every node is a candidate as before.
    """
    lox, hix = min(box.xmn, box.xmx), max(box.xmn, box.xmx)
    loy, hiy = min(box.ymn, box.ymx), max(box.ymn, box.ymx)
    loz, hiz = min(box.zmn, box.zmx), max(box.zmn, box.zmx)
    src = state.source_node_ids
    cands = ((nid, nd) for nid, nd in state.nodes.items()
             if not src or nid in src)
    if box.local:
        basis = _box_basis(box)
        if basis is None:
            return set()
        origin, ex, ey, ez = basis
        out: Set[int] = set()
        for nid, nd in cands:
            d = (nd.x - origin[0], nd.y - origin[1], nd.z - origin[2])
            u, v, w = _vdot(d, ex), _vdot(d, ey), _vdot(d, ez)
            if lox <= u <= hix and loy <= v <= hiy and loz <= w <= hiz:
                out.add(nid)
        return out
    return {nid for nid, nd in cands
            if lox <= nd.x <= hix and loy <= nd.y <= hiy and loz <= nd.z <= hiz}


def _resolve_box_nodes(state: ConversionState, box_id: int, label: str):
    """Node ids inside *DEFINE_BOX ``box_id`` (a set), or None (with a warning)
    when the box is undefined or has a degenerate local frame — the caller then
    applies the load/wall to the full node group instead."""
    box = state.boxes.get(box_id)
    if box is None:
        state.warn(f"{label}: no *DEFINE_BOX {box_id} in the deck — box scoping "
                   "ignored (applied to the full node group).")
        return None
    if box.local and _box_basis(box) is None:
        state.warn(f"{label}: *DEFINE_BOX_LOCAL {box_id} has a degenerate local "
                   "frame (zero or parallel defining vectors) — box scoping "
                   "ignored.")
        return None
    return _box_node_ids(state, box)


def _emit_frame_fix(frame_id: int, title: str, origin, yaxis, zaxis) -> List[str]:
    """Emit /FRAME/FIX — same card layout and Y'/Z' rule as /SKEW/FIX: the two
    vector cards are the LOCAL Y' and Z' axes (globalyaxis / globalzaxis). The
    starter rebuilds X' = Y' x Z' then re-orthogonalises Y'' = Z' x X', so the
    Z' card (card 3) is the exactly-preserved local Z; the Y' card only needs to
    be non-parallel to Z'."""
    return [
        f"/FRAME/FIX/{frame_id}",
        title,
        "#                 Ox                  Oy                  Oz",
        f"{_f(origin[0])}{_f(origin[1])}{_f(origin[2])}",
        "#                 X1                  Y1                  Z1   (local Y axis)",
        f"{_f(yaxis[0])}{_f(yaxis[1])}{_f(yaxis[2])}",
        "#                 X2                  Y2                  Z2   (local Z axis)",
        f"{_f(zaxis[0])}{_f(zaxis[1])}{_f(zaxis[2])}",
        HDR,
    ]


def _emit_inivel_axis(inivel_id: int, title: str, frame_id: int, grnod_id: int,
                      v: Tuple[float, float, float], vr: float,
                      dir_axis: str = "Z") -> List[str]:
    """One /INIVEL/AXIS block: card A = DIR(10s) FRAME_id(10) GRNOD_id(10);
    card B = Vxt(20) Vyt(20) Vzt(20) VR(20). Vxt/Vyt/Vzt are the translational
    velocity expressed in the FRAME's local axes; VR is the angular velocity
    about the DIR axis (here the frame's local Z)."""
    return [
        f"/INIVEL/AXIS/{inivel_id}",
        title,
        "#      DIR  FRAME_id  GRNOD_id",
        f"{dir_axis.rjust(10)}{_i(frame_id)}{_i(grnod_id)}",
        "#                Vxt                 Vyt                 Vzt                  VR",
        f"{_f(v[0])}{_f(v[1])}{_f(v[2])}{_f(vr)}",
        HDR,
    ]


def _make_initial_velocity(state: ConversionState) -> List[str]:
    """*INITIAL_VELOCITY (base set form) → /INIVEL/TRA (+ /INIVEL/ROT).

    NSID scopes the node group (blank/0 = whole model); NSIDEX is subtracted by
    set difference (writer phase = every *SET_NODE is resolvable). BOXID and a
    rigid-overwrite IRIGID are warned + dropped; ICID maps to the matching
    /SKEW when *DEFINE_COORDINATE_* produced one, else falls back to global.
    """
    if not state.inivel_general:
        return []
    lines: List[str] = []
    for iv in state.inivel_general:
        has_tra = bool(iv.vx or iv.vy or iv.vz)
        has_rot = bool(iv.vxr or iv.vyr or iv.vzr)
        if not has_tra and not has_rot:
            continue   # zero velocity → no-op card

        # ── resolve the node group ──────────────────────────────────────────
        if iv.nsid:
            ns = state.node_sets.get(iv.nsid)
            if ns is None:
                state.warn(
                    f"*INITIAL_VELOCITY NSID={iv.nsid}: node set not found "
                    "(unsupported *SET_NODE variant?) - skipped")
                continue
            base = set(ns[1])
        else:
            base = set(state.nodes.keys())         # whole model
        if iv.nsidex:
            ex = state.node_sets.get(iv.nsidex)
            if ex is None:
                state.warn(
                    f"*INITIAL_VELOCITY NSIDEX={iv.nsidex}: exclusion set not "
                    "resolvable - applied WITHOUT exclusion")
            else:
                base -= set(ex[1])
        # ── BOXID: intersect the group with the *DEFINE_BOX contained nodes ──
        if iv.boxid:
            box_nids = _resolve_box_nodes(
                state, iv.boxid, f"*INITIAL_VELOCITY BOXID={iv.boxid}")
            if box_nids is not None:
                before = len([n for n in base if n > 0])
                base &= box_nids
                state.warn(
                    f"*INITIAL_VELOCITY BOXID={iv.boxid}: velocity scoped to the "
                    f"{len([n for n in base if n > 0])} node(s) inside "
                    f"*DEFINE_BOX {iv.boxid} (of {before} in the base group).")
        nids = sorted(n for n in base if n > 0)
        if not nids:
            state.warn("*INITIAL_VELOCITY: resolved node group is empty - skipped")
            continue

        # ── lossy fields (warn + continue) ──────────────────────────────────
        if iv.irigid:
            state.warn(
                f"*INITIAL_VELOCITY IRIGID={iv.irigid}: rigid-body velocity "
                "overwrite bookkeeping not modelled - velocity applied to the "
                "node group as-is")
        skew_id = 0
        if iv.icid:
            if (iv.icid in state.coord_sys or iv.icid in state.coord_nodes
                    or iv.icid in state.coord_vectors):
                skew_id = iv.icid
                state.warn(
                    f"*INITIAL_VELOCITY ICID={iv.icid}: velocity components read "
                    f"in /SKEW/{iv.icid} (components not rotated to global, "
                    "matching LS-DYNA)")
            else:
                state.warn(
                    f"*INITIAL_VELOCITY ICID={iv.icid}: no converted /SKEW with "
                    "that id - velocity applied in the GLOBAL frame")

        # ── emit ────────────────────────────────────────────────────────────
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_grp_{grnod_id}", nids)
        if has_tra:
            tid = state.next_id()
            lines += _emit_inivel("TRA", tid, f"InitVel_{tid}", grnod_id,
                                  (iv.vx, iv.vy, iv.vz), skew_id)
        if has_rot:
            rid = state.next_id()
            lines += _emit_inivel("ROT", rid, f"InitVelRot_{rid}", grnod_id,
                                  (iv.vxr, iv.vyr, iv.vzr), skew_id)

    if lines:
        lines = ["#-  INITIAL VELOCITY (set form):", HDR] + lines
    return lines


def _inivel_gen_group_nodes(state: ConversionState, g):
    """Resolve the *INITIAL_VELOCITY_GENERATION STYP scope to sorted node ids.
    Returns None when the STYP target id cannot be resolved (caller falls back
    to the whole model with a warning)."""
    nids: Set[int] = set()

    def add_part_nodes(pid: int):
        for e in state.shell_elems:
            if e.pid == pid:
                nids.update(e.nodes)
        for e in state.solid_elems:
            if e.pid == pid:
                nids.update(e.nodes)
        for e in state.beam_elems:
            if e.pid == pid:
                nids.update((e.n1, e.n2))
        for e in state.discrete_elems:      # *ELEMENT_DISCRETE (springs); n2=0=ground
            if e.pid == pid:
                nids.update((e.n1, e.n2))

    if g.styp == 0 or g.sid == 0:
        return sorted(state.nodes.keys())            # whole model
    if g.styp == 1:                                  # part set
        ps = state.part_sets.get(g.sid)
        if ps is None:
            return None
        for pid in ps[1]:
            add_part_nodes(pid)
    elif g.styp == 2:                                # single part
        if g.sid not in state.parts:
            return None
        add_part_nodes(g.sid)
    elif g.styp == 3:                                # node set
        ns = state.node_sets.get(g.sid)
        if ns is None:
            return None
        nids.update(ns[1])
    else:
        return None
    return sorted(n for n in nids if n > 0)


def _make_initial_velocity_generation(state: ConversionState) -> List[str]:
    """*INITIAL_VELOCITY_GENERATION → /INIVEL/AXIS + a companion /FRAME/FIX.

    The rotation axis (through (XC,YC,ZC) along (NX,NY,NZ), or node-defined when
    NX=-999) becomes the frame's local Z; OMEGA → VR about it; the translational
    (VX,VY,VZ) is projected onto the frame's local axes so Radioss re-expands it
    to the correct global velocity. A nonzero ICID rotates VX/VY/VZ and the
    vector axis from that local system to global (there is no Skew_id field on
    /INIVEL/AXIS, so it is baked in here). STYP selects the node group. PHASE,
    IVATN and IRIGID are lossy and warned.
    """
    if not state.inivel_generations:
        return []
    refX, refY, refZ = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    # /FRAME and /SKEW share ONE id namespace in the starter (UDOUBLE over the
    # combined table), and converted /SKEW ids preserve the LS-DYNA coord cid
    # verbatim — so a synthesized frame id must never land on one, or the starter
    # aborts with ERROR 79 DUPLICATE ID. all_skew_ids() covers every converted
    # skew: coordinate systems/nodes/vectors and the *DEFINE_VECTOR /
    # *DEFINE_SD_ORIENTATION skews the prepass assigned.
    reserved_skew = state.all_skew_ids()
    lines: List[str] = []
    for g in state.inivel_generations:
        if g.phase:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION PHASE={g.phase}: dynamic-relaxation "
                "phase flag not modelled - velocity applied at t=0")
        if g.ivatn:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION IVATN={g.ivatn}: attached "
                "secondary-node scoping dropped")
        if g.irigid:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION IRIGID={g.irigid}: rigid-body "
                "overwrite flag not modelled")
        # ICID: VX/VY/VZ and the (vector) rotation axis are given in this local
        # system. Resolve its global basis and pre-rotate them, mirroring the
        # plain *INITIAL_VELOCITY path (which attaches a Skew_id and lets Radioss
        # rotate) — /INIVEL/AXIS has no skew field, so the rotation is baked here.
        icid_basis = None
        if g.icid:
            icid_basis = _icid_basis(state, g.icid)
            if icid_basis is None:
                state.warn(
                    f"*INITIAL_VELOCITY_GENERATION ICID={g.icid}: no converted "
                    "/SKEW with that id - VX/VY/VZ and the rotation axis applied "
                    "in the GLOBAL frame")
            else:
                state.warn(
                    f"*INITIAL_VELOCITY_GENERATION ICID={g.icid}: VX/VY/VZ and the "
                    f"vector rotation axis rotated from /SKEW/{g.icid} to global")

        # ── origin + raw rotation axis vector ───────────────────────────────
        if -999.5 < g.nx < -998.5:                     # NX=-999 → node-defined axis
            n1 = state.nodes.get(g.node1)
            n2 = state.nodes.get(g.node2)
            if n1 is None or n2 is None:
                state.warn(
                    f"*INITIAL_VELOCITY_GENERATION: axis node {g.node1}/{g.node2} "
                    "missing - rotation axis undefined, OMEGA dropped")
                origin, N = (g.xc, g.yc, g.zc), (0.0, 0.0, 0.0)
            else:
                origin = (n1.x, n1.y, n1.z)      # nodes are global; ICID N/A here
                N = _vsub((n2.x, n2.y, n2.z), origin)
        else:
            origin, N = (g.xc, g.yc, g.zc), (g.nx, g.ny, g.nz)
            if icid_basis is not None:
                N = _local_to_global(icid_basis, N)

        # ── build the local frame triad (local Z = rotation axis) ───────────
        nhat = _vnorm(N)
        vr = g.omega
        if nhat is None:
            if g.omega:
                state.warn(
                    "*INITIAL_VELOCITY_GENERATION: no rotation axis "
                    "(NX=NY=NZ=0 or degenerate nodes) - OMEGA dropped, "
                    "translation only")
            vr = 0.0
            fz = refZ
            fy = _vnorm(_vcross(refZ, refX)) or refY
            fx = _vnorm(_vcross(fy, fz)) or refX
        else:
            fz = nhat
            fy = _vnorm(_vcross(nhat, refX)) or _vnorm(_vcross(nhat, refZ)) or refY
            fx = _vnorm(_vcross(fy, fz)) or refX

        # ── translational velocity, expressed in the frame's local axes ─────
        gV = (g.vx, g.vy, g.vz)
        if icid_basis is not None:       # rotate ICID-local components to global
            gV = _local_to_global(icid_basis, gV)
        vxt = _vdot(fx, gV)              # local X = FrameVect3
        vyt = _vdot(fy, gV)              # local Y = FrameVect1
        vzt = _vdot(fz, gV)             # local Z = FrameVect2

        # ── node group (STYP) ──────────────────────────────────────────────
        nids = _inivel_gen_group_nodes(state, g)
        if nids is None:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION STYP={g.styp} id={g.sid}: scope "
                "target not found - applied to the whole model")
            nids = sorted(state.nodes.keys())
        if not nids:
            state.warn("*INITIAL_VELOCITY_GENERATION: node group empty - skipped")
            continue

        # ── emit /FRAME/FIX then /INIVEL/AXIS ───────────────────────────────
        frame_id = state.next_id()
        while frame_id in reserved_skew:   # never collide with a converted /SKEW
            frame_id = state.next_id()
        lines += _emit_frame_fix(frame_id, f"FRAME_INIVEL_GEN_{frame_id}",
                                 origin, fy, fz)
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_gen_grp_{grnod_id}", nids)
        inivel_id = state.next_id()
        lines += _emit_inivel_axis(inivel_id, f"InitVelGen_{inivel_id}",
                                   frame_id, grnod_id, (vxt, vyt, vzt), vr)

    if lines:
        lines = ["#-  INITIAL VELOCITY GENERATION:", HDR] + lines
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: pressure loads
# ─────────────────────────────────────────────────────────────────────────────

_PLOAD_COMMENT = ("#  surf_ID  functIDT sensor_ID                             "
                  "             Ascale_x            Fscale_y")


def _emit_pload_card(pload_id: int, title: str, surf_id: int, lcid: int,
                     fscale: float, sensor_id: int = 0) -> List[str]:
    """One /PLOAD block.

    Card grid (``radioss2021/LOADS/pload.cfg``, the newest FORMAT block a
    ``/BEGIN 2022`` deck resolves):
      ``surf_ID(10) fct_IDT(10) sens_ID(10) Ipinch(10) Idel(10) <blank 51-60>
        Ascale_x(20) Fscale_y(20)``
    Cols 31-60 are left blank, which the reader takes as ``Ipinch=0`` and
    ``Idel=0 -> 1`` (cancel the pressure once every element of a segment is
    deleted). Cols 51-60 must STAY blank: that is where the 2023-only
    ``Itypfun`` column lives, and writing it into a 2022 deck raises
    ``WARNING ID 100214`` "unsupported field exists" (measured).

    ``Ascale_x`` is always 1.0 — it is an abscissa DIVISOR (the starter stores
    ``PRES(2,K) = ONE/FCX``, ``hm_read_pload.F:166``), and no LS-DYNA pressure
    keyword scales the time axis.
    """
    return [
        f"/PLOAD/{pload_id}",
        title,
        _PLOAD_COMMENT,
        f"{_i(surf_id)}{_i(lcid)}{_i(sensor_id)}" + " " * 30
        + f"{_f(1.0)}{_f(fscale)}",
        HDR,
    ]


def _emit_sensor_time(sensor_id: int, title: str, tdelay: float) -> List[str]:
    """One /SENSOR/TIME block — the only time gate a /PLOAD has.

    Card: ``Tdelay(20) Tstop(20)`` (``radioss2022/SENSOR/sensor.cfg:219-222``
    selects the header ``/SENSOR/TIME/<id>``; ``read_sensor_time.F:69-71`` reads
    the two floats and turns ``Tstop = 0`` into INFINITY, so leaving it 0 means
    "never deactivate").

    What the consumer then does with it, and why it is a SHIFT and not a gate:
    ``sensor_time.F:66-68`` sets ``SENSOR%TSTART = TDELAY`` once the sensor
    fires, and the load evaluation subtracts it — ``force.F90:216-218``:
    ``ts = tt - sensor_tab(isens)%tstart``, with ``IF (ts < ZERO) CYCLE``. So the
    load is zero for ``t < Tdelay`` and the pressure curve is evaluated at
    ``t - Tdelay`` afterwards. That is exactly how LS-DYNA's arrival time AT
    reads, and it is what dyna2rad emits (``convertloads.cxx:803-812``).
    """
    return [
        f"/SENSOR/TIME/{sensor_id}",
        title,
        "#             Tdelay               Tstop",
        f"{_f(tdelay)}{_f(0.0)}",
        HDR,
    ]


def _shell_load_segments(state: ConversionState, eids: List[int],
                         label: str, shells: Optional[Dict] = None
                         ) -> List[List[int]]:
    """The /SURF/SEG rows for a list of shell element ids.

    The connectivity is pasted through UNREVERSED: ``/SHELL`` /``/SH3N``
    ``elem_ID n1 n2 n3 n4`` maps column-for-column onto ``/SURF/SEG``
    ``seg_ID n1 n2 n3 n4`` (Reference Guide 2022 p.2499 Comment 3 says segments
    may be produced by cut-and-paste of shell element input), so the segment
    normal IS the shell normal and the single sign flip lives in Fscale_y.

    Pass *shells* (``{eid: ShellElem}``) when calling this in a loop — building
    it per row is O(elements x rows).
    """
    if shells is None:
        shells = {e.eid: e for e in state.shell_elems}
    segs: List[List[int]] = []
    missing: List[int] = []
    for eid in eids:
        e = shells.get(eid)
        if e is None:
            missing.append(eid)
            continue
        nodes = [n for n in e.nodes if n > 0]
        # A degenerate quad (n4 == n3) is a triangle: /SURF/SEG wants n4 = 0 so
        # hm_read_pload.F:196-200 flags a true tria and force.F90 uses the 1/6
        # per-node factor instead of 1/8.
        if len(nodes) >= 4 and nodes[3] == nodes[2]:
            nodes = nodes[:3]
        if len(nodes) >= 3:
            segs.append(nodes[:4])
    if missing:
        state.warn(
            f"{label}: shell element(s) {_fmt_eid_list(sorted(missing))} are not "
            "in the deck (or are not shells) — those faces carry no /PLOAD. "
            "*LOAD_SHELL only loads shells; a solid face needs *LOAD_SEGMENT.")
    return segs


def _make_pressure_loads(state: ConversionState) -> List[str]:
    """*LOAD_SEGMENT[_SET] and *LOAD_SHELL_ELEMENT/_SET → /SURF/SEG + /PLOAD.

    /PLOAD has ONE data card referencing a surface; see _emit_pload_card for the
    column grid. The segments themselves are a /SURF/SEG entity (seg_ID n1 n2 n3
    n4, five 10-char fields per line; n4=0 → triangle).

    **Sign.** Positive ``Fscale_y`` pushes the surface along its POSITIVE
    segment normal ``n = N1N3 x N2N4`` (Altair help, /PLOAD Comment 1; engine
    ``force.F90:451-465`` sums ``+P*A*n_hat`` over the segment's nodes). The two
    sources differ:

    * *LOAD_SEGMENT gives the pressure on an explicitly ORIENTED segment, and
      k2rad passes both the node order and the scale through verbatim — the
      deck's own segment orientation carries the direction.
    * *LOAD_SHELL gives a pressure on a SHELL, positive "in the negative
      t-direction" (Manual Vol I R16 p.3421), i.e. INTO the top face. Pasting
      the shell connectivity makes ``n_hat = t_hat``, so exactly ONE flip is
      needed and it is applied as ``Fscale_y = -SF``. Reversing the node order
      as well would cancel it back out.
    """
    if not (state.pressure_loads or state.segment_set_pressure_loads
            or state.shell_pressure_loads):
        return []
    # Grouped by (lcid, fscale, at): one /SURF/SEG + one /PLOAD per distinct
    # load. `at` joins the key because it becomes a per-load /SENSOR/TIME.
    groups: Dict[Tuple, List[List[int]]] = defaultdict(list)
    for pl in state.pressure_loads:
        groups[(pl.lcid, pl.sf, pl.at)].append(pl.nodes)
    # *LOAD_SEGMENT_SET: expand each referenced *SET_SEGMENT into per-segment
    # cards, grouped alongside *LOAD_SEGMENT by (lcid, sf).
    for ssl in state.segment_set_pressure_loads:
        segset = state.segment_sets.get(ssl.ssid)
        if segset is None:
            state.warn(f"*LOAD_SEGMENT_SET references *SET_SEGMENT {ssl.ssid}, "
                       "which is not defined — pressure load dropped.")
            continue
        for nodes in segset.segments:
            groups[(ssl.lcid, ssl.sf, ssl.at)].append(list(nodes))
    # *LOAD_SHELL_ELEMENT / _SET: the sign flip is applied HERE, so the group key
    # already holds the emitted Fscale_y.
    flipped = False
    shells = ({e.eid: e for e in state.shell_elems}
              if state.shell_pressure_loads else {})
    for spl in state.shell_pressure_loads:
        eids = spl.eids
        if spl.ssid:
            sset = state.shell_sets.get(spl.ssid)
            if sset is None:
                state.warn(
                    f"{spl.source} references *SET_SHELL {spl.ssid}, which is "
                    "not defined — pressure load dropped.")
                continue
            eids = list(sset[1])
            if not eids:
                state.warn(f"{spl.source}: *SET_SHELL {spl.ssid} is empty — "
                           "pressure load dropped.")
                continue
        segs = _shell_load_segments(state, eids,
                                    f"{spl.source} lcid={spl.lcid}", shells)
        if not segs:
            continue
        flipped = True
        groups[(spl.lcid, -spl.sf, spl.at)].extend(segs)

    lines: List[str] = ["#-  PRESSURE LOADS:", HDR]
    pload_id = 1
    sensors_emitted = False
    for (lcid, sf, at), segs in groups.items():
        if sf == 0.0:
            # Unreachable from the handlers, which default SF = 0 to 1.0 — kept
            # because a /PLOAD carrying a zero ordinate scale is not a zero load
            # but a FULL-amplitude one: hm_read_pload.F:167 is
            # `IF (FCY == ZERO) FCY = FAC_FCY`, so the starter substitutes the
            # unit-system factor. Never let a literal 0 reach the card.
            state.warn(
                f"Pressure load on curve {lcid} resolved to Fscale_y = 0, which "
                "/PLOAD cannot express: hm_read_pload.F:167 replaces a zero "
                "ordinate scale with the unit-system factor, so the load would "
                "run at FULL amplitude. The load is DROPPED instead.")
            continue
        surf_id = state.next_id()
        lines += [
            f"/SURF/SEG/{surf_id}",
            f"PLOAD_{pload_id}_segments",
            "#   seg_ID        n1        n2        n3        n4",
        ]
        for seg_no, nodes in enumerate(segs, start=1):
            quad = (list(nodes) + [0, 0, 0, 0])[:4]
            lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
        sensor_id = 0
        if at > 0.0:
            sensor_id = state.next_id()
            sensors_emitted = True
            lines += _emit_sensor_time(sensor_id, f"PLOAD_{pload_id}_arrival", at)
        lines += _emit_pload_card(pload_id, f"PLOAD_{pload_id}", surf_id, lcid,
                                  sf, sensor_id)
        pload_id += 1
    if flipped:
        state.warn(
            "*LOAD_SHELL_{ELEMENT,SET} -> /PLOAD with Fscale_y = -SF. LS-DYNA's "
            "positive pressure acts along the shell's NEGATIVE normal (Manual "
            "Vol I R16 p.3421: the connectivity follows the right-hand rule and "
            "\"positive pressure acts in the negative t-direction\"), while a "
            "/PLOAD with positive Fscale_y pushes the surface along its POSITIVE "
            "segment normal (force.F90:451-465 sums +P*A*n_hat). The /SURF/SEG "
            "is built by pasting the shell connectivity, so n_hat = t_hat and "
            "ONE flip is correct. Note the Radioss dyna-reader gets this wrong: "
            "ConvertLoadShell writes the value under the name 'Fscale_Y' while "
            "/PLOAD's attribute is 'Fscale_y', the solver-name map is "
            "case-sensitive (mv_descriptor.cpp:93), and the write is silently "
            "discarded — a dyna2rad-converted *LOAD_SHELL runs at Fscale_y = "
            "+1.0, losing SF and inverting the sign.")
    if sensors_emitted:
        state.warn(
            "Pressure-load arrival time AT > 0 -> /SENSOR/TIME with Tdelay = AT "
            "in the /PLOAD sens_ID column: the load is zero for t < AT and the "
            "curve is then evaluated at t - AT, i.e. the abscissa is SHIFTED, "
            "not merely gated (sensor_time.F:66-68 sets TSTART = TDELAY; "
            "force.F90:216-218 evaluates at ts = tt - TSTART). That matches the "
            "usual reading of LS-DYNA's arrival time and is what dyna2rad emits "
            "(convertloads.cxx:803-812) — but if your curve's abscissa is "
            "already absolute time, pre-shift it instead. k2rad <= PR #116 "
            "dropped AT on *LOAD_SEGMENT_SET entirely.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Engine file sections
# ─────────────────────────────────────────────────────────────────────────────

def _make_added_masses(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """*ELEMENT_MASS lumped masses on ORDINARY nodes → /ADMAS/0.

    state.added_node_masses holds every *ELEMENT_MASS nodal mass. Masses on
    rigid-body nodes are already accounted for via the /RBODY Mass field
    (_make_rbodies folds the master-node mass), so /ADMAS is emitted only for
    nodes that are NOT part of any rigid body. /ADMAS/0 adds its Mass value to
    EACH node of the referenced /GRNOD, so nodes are grouped by identical mass
    value (one /GRNOD + /ADMAS/0 per distinct value). Before this, ordinary-node
    *ELEMENT_MASS was silently dropped (writer consumed added_node_masses only
    for rigid masters) — a real mass/dynamics error on any deck with point masses.
    """
    masses_by_value: Dict[float, List[int]] = {}
    skipped_rigid = 0
    for nid, mass in state.added_node_masses.items():
        if mass <= 0 or nid not in state.nodes:
            continue
        if nid in rigid_nodes:
            skipped_rigid += 1          # folded into its /RBODY already
            continue
        masses_by_value.setdefault(mass, []).append(nid)
    if not masses_by_value:
        return []
    lines: List[str] = [HDR, "#-  ADDED MASSES (*ELEMENT_MASS on ordinary nodes):"]
    n_nodes = 0
    total = 0.0
    for mass, nids in sorted(masses_by_value.items()):
        nids = sorted(nids)
        n_nodes += len(nids)
        total += mass * len(nids)
        grnod_id = state.next_id()
        lines += _emit_grnod_node(grnod_id, f"added_mass_{mass:g}_nodes", nids)
        admas_id = state.next_id()
        lines += [
            f"/ADMAS/0/{admas_id}",
            f"added_mass_{mass:g}",
            "#               MASS   grnd_ID",
            f"{_f(mass)}{_i(grnod_id)}",
            HDR,
        ]
    note = (f"*ELEMENT_MASS: emitted /ADMAS/0 for {n_nodes} ordinary node(s) "
            f"(total added mass {total:g}).")
    if skipped_rigid:
        note += (f" {skipped_rigid} mass(es) on rigid-body nodes were left to the "
                 "/RBODY (master-node mass is folded into its Mass field).")
    state.warn(note)
    return lines


def _make_starter_cloads(state: ConversionState) -> List[str]:
    """/CLOAD is a Starter keyword – concentrated loads on node groups.

    Card layout (one 100-col data card after the title — same columns from
    radioss51 through 2026; cfg radioss2023+ reads cols 51-60 as Itypfun,
    older input versions blank-skip them):
      fct_IDT(10) Dir(10) skew_ID(10) sens_ID(10) grnd_ID(10) Itypfun(10)
      Ascalex(20) Fscaley(20)
    Itypfun stays BLANK (= default 1, abscissa is time, matching
    *LOAD_RIGID_BODY LCID semantics): /BEGIN-2022 readers flag any non-blank
    text in skipped columns with WARNING 100214 "unsupported field exists",
    while 2023+ readers take blank as 1 — blank is warning-free either way.
    """
    if not state.load_rigid_bodies:
        return []

    _DOF_DIR_FORCE = {1: "X", 2: "Y", 3: "Z", 5: "XX", 6: "YY", 7: "ZZ"}
    lines: List[str] = ["#-  CONCENTRATED LOADS (RIGID BODY):"]
    load_id = 1
    emitted = False
    for lb in state.load_rigid_bodies:
        ind_grnod_id = state.rbody_ind_grnods.get(lb.pid)
        if ind_grnod_id is None:
            state.warn(f"LOAD_RIGID_BODY pid={lb.pid}: rigid body not found – skipped")
            continue

        if lb.dof == 4:
            dirs_to_emit = [("X", lb.sf), ("Y", lb.sf), ("Z", lb.sf)]
        else:
            d = _DOF_DIR_FORCE.get(lb.dof)
            if d is None:
                state.warn(f"LOAD_RIGID_BODY pid={lb.pid} DOF={lb.dof}: unknown DOF – skipped")
                continue
            dirs_to_emit = [(d, lb.sf)]

        for dir_str, sf in dirs_to_emit:
            lines += [
                f"/CLOAD/{load_id}",
                f"LoadRB_{load_id}",
                "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
                f"{_i(lb.lcid)}{dir_str.rjust(10)}{_i(lb.cid)}         0{_i(ind_grnod_id)}"
                f"          {_f(1.0)}{_f(sf)}",
                HDR,
            ]
            load_id += 1
            emitted = True

    return lines if emitted else []


def _make_node_cloads(state: ConversionState) -> List[str]:
    """*LOAD_NODE_POINT / *LOAD_NODE_SET → /CLOAD on the node (set)'s /GRNOD.

    Same card layout as the rigid-body /CLOAD above; the CID local system maps
    to the /CLOAD skew (the /SKEW of the same id is emitted by _make_skews),
    falling back to global with a warning when no such system exists.
    """
    if not state.load_nodes:
        return []

    _DOF_DIR_FORCE = {1: "X", 2: "Y", 3: "Z", 5: "XX", 6: "YY", 7: "ZZ"}
    lines: List[str] = ["#-  CONCENTRATED LOADS (NODES):"]
    grnod_by_nsid: Dict[int, int] = {}
    for ln in state.load_nodes:
        set_title, nids = state.node_sets.get(ln.nsid, ("", []))
        if not nids:
            state.warn(f"LOAD_NODE nsid={ln.nsid}: node set not found – skipped")
            continue
        skew_id = 0
        if ln.cid:
            if ln.cid in state.coord_sys or ln.cid in state.coord_nodes:
                skew_id = ln.cid
            else:
                state.warn(
                    f"LOAD_NODE nsid={ln.nsid}: local system cid={ln.cid} not "
                    "found — load applied in the GLOBAL system.")
        grnod_id = grnod_by_nsid.get(ln.nsid)
        emit_grnod = grnod_id is None
        if emit_grnod:
            grnod_id = state.next_id()
            grnod_by_nsid[ln.nsid] = grnod_id
        load_id = state.next_id()
        lines += [
            f"/CLOAD/{load_id}",
            set_title or f"LoadNode_{load_id}",
            "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
            f"{_i(ln.lcid)}{_DOF_DIR_FORCE[ln.dof].rjust(10)}{_i(skew_id)}         0{_i(grnod_id)}"
            f"          {_f(1.0)}{_f(ln.sf)}",
            HDR,
        ]
        if emit_grnod:
            lines += _emit_grnod_node(grnod_id, set_title or f"SET_{ln.nsid}", nids)
    return lines if len(lines) > 1 else []


def _synthesize_rwall_moving_nodes(state: ConversionState) -> None:
    """Give each *RIGIDWALL_PLANAR_MOVING wall its /RWALL carrier node.

    The OpenRadioss moving /RWALL form (cfg RWALL/plane.cfg + paral.cfg,
    FORMAT radioss51; starter hm_read_rwall_plane.F) takes node_ID > 0: the
    node's coordinates become the wall base point M, and the wall card's own
    "Mass VX0 VY0 VZ0" line adds the wall mass to that node and sets its
    initial velocity (MS(MSR) += Mass; V(:,MSR) = VX0..) — so no /ADMAS or
    /INIVEL is needed. Synthesize a free node at the LS-DYNA tail point
    (XT,YT,ZT), like the rigid-cog master synthesis in _make_rbodies (new ids
    above the current maximum). Must run before the /NODE section is built.
    """
    movers = [rw for rw in state.rigid_walls if rw.moving and rw.node_id == 0]
    if not movers:
        return
    next_free = (max(state.nodes) + 1) if state.nodes else 90000001
    for rw in movers:
        rw.node_id = next_free
        next_free += 1
        state.nodes[rw.node_id] = NodeData(rw.xt, rw.yt, rw.zt)
        state.warn(
            f"*RIGIDWALL_PLANAR_MOVING id={rw.rwid}: wall carried by "
            f"synthesized free node {rw.node_id} at the wall tail point; the "
            "/RWALL card's Mass/V0 fields give that node the wall mass and "
            "the initial velocity V0 along the wall normal.")


def _rwall_finite_corners(rw, state: ConversionState):
    """Corner points M1/M2 of the /RWALL/PARAL form for a _FINITE wall.

    LS-DYNA: the l-edge direction is the in-plane projection of
    (HEV − tail); the m-edge is m = n × l; the wall spans lenl and lenm from
    the tail corner. /RWALL/PARAL takes the two opposite in-plane corner
    POINTS M1 = M + lenl·l̂ and M2 = M + lenm·m̂ (cfg RWALL/paral.cfg); the
    starter derives the outward normal as (M1−M)×(M2−M) =
    lenl·lenm·(l̂×m̂) = lenl·lenm·n̂ (hm_read_rwall_paral.F), so the normal
    orientation is preserved. Returns (M1, M2) or None when the wall cannot
    be expressed as a finite parallelogram (→ infinite-plane fallback, with
    a warning naming the reason).
    """
    label = f"*RIGIDWALL_PLANAR_FINITE id={rw.rwid}"
    n = _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt))
    if n is None:
        state.warn(f"{label}: degenerate wall normal (head == tail) — "
                   "emitted as an infinite plane.")
        return None
    if rw.lenl <= 0.0 or rw.lenm <= 0.0:
        # DYNA convention: a zero LENL/LENM means infinite extent in that
        # direction. /RWALL/PARAL is strictly finite (no semi-infinite
        # form), so fall back to the infinite plane.
        state.warn(
            f"{label}: LENL/LENM = 0 means an infinite extent in that "
            "direction in LS-DYNA; /RWALL/PARAL cannot express a "
            "semi-infinite wall — emitted as an infinite plane.")
        return None
    triad = _rwall_geom_triad(rw, n)
    if triad is None:
        state.warn(
            f"{label}: the edge-vector head (XHEV,YHEV,ZHEV) coincides with "
            "the wall tail or projects onto the wall normal (no in-plane l "
            "direction) — emitted as an infinite plane.")
        return None
    _n, lu, mu = triad
    m1 = (rw.xt + rw.lenl * lu[0], rw.yt + rw.lenl * lu[1],
          rw.zt + rw.lenl * lu[2])
    m2 = (rw.xt + rw.lenm * mu[0], rw.yt + rw.lenm * mu[1],
          rw.zt + rw.lenm * mu[2])
    return m1, m2


def _rwall_geom_triad(rw, n):
    """The (n̂, l̂, m̂) orthonormal triad of a FLAT/PRISM/_FINITE rigid wall.

    ``n`` is the already-validated unit wall normal (LS-DYNA's
    normalize(head − tail)). The l-edge direction comes from
    (XHEV,YHEV,ZHEV) − tail and m = n × l (Manual p. 40-9); the HEV vector is
    projected into the wall plane first, because a raw normalize(HEV − T) —
    what dyna2rad uses, convertrwalls.cxx:255-259 — leaves m̂ = n̂ × l̂ short by
    sin(theta) whenever HEV is not exactly perpendicular to the normal, so
    every m-edge length comes out wrong by that factor.

    Returns None when (HEV − tail) has no in-plane component, i.e. when the
    l direction does not exist. The test is deliberately TAIL-RELATIVE, not
    "is XHEV/YHEV/ZHEV the global origin": HEV is a POINT, so an
    *INCLUDE_TRANSFORM translation moves it, and an absolute test would
    classify the same physical wall differently depending on how the deck is
    assembled. Shared by the *RIGIDWALL_PLANAR _FINITE path and the
    *RIGIDWALL_GEOMETRIC FLAT/PRISM path so the two cannot drift.
    """
    v = (rw.xhev - rw.xt, rw.yhev - rw.yt, rw.zhev - rw.zt)
    dot = v[0] * n[0] + v[1] * n[1] + v[2] * n[2]
    proj = (v[0] - dot * n[0], v[1] - dot * n[1], v[2] - dot * n[2])
    vmag = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
    pmag = (proj[0] ** 2 + proj[1] ** 2 + proj[2] ** 2) ** 0.5
    if pmag <= 1e-10 * max(1.0, vmag):
        return None
    lu = (proj[0] / pmag, proj[1] / pmag, proj[2] / pmag)
    return n, lu, _vcross(n, lu)        # n ⊥ l and both unit ⇒ |n × l| = 1


def _rwall_geom_faces(rw, state: ConversionState, label: str, title: str,
                      alloc_rwid) -> List[RigidWallGeomFace]:
    """Resolve one *RIGIDWALL_GEOMETRIC card to its Radioss /RWALL wall(s).

    CYLINDER → one /RWALL/CYL, SPHERE → one /RWALL/SPHER, FLAT → one
    /RWALL/PLANE (infinite) or /RWALL/PARAL (finite), PRISM → six /RWALL/PARAL
    faces with outward normals, because Radioss has no box rigid wall (the only
    /RWALL readers are hm_read_rwall_{plane,paral,cyl,spher,lagmul,therm}.F).
    Returns [] when nothing can be emitted; every loss is warned.
    """
    if rw.shape == "CYLINDER":
        # /RWALL/CYL: M and M1 are two absolute points, the axis is
        # normalize(M1 − M) and only the DIRECTION survives (the length is
        # divided out, hm_read_rwall_cyl.F:240-254) — so the LS-DYNA head
        # point is carried over verbatim, exactly as dyna2rad does.
        if _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt)) is None:
            state.warn(f"{label}: the cylinder axis is degenerate (head == "
                       "tail) — the starter would abort with ERROR 167, so "
                       "the wall was skipped.")
            return []
        if rw.radcyl <= 0.0:
            state.warn(f"{label}: RADCYL = {rw.radcyl:g} — a zero-radius "
                       "cylinder never contacts anything, so the wall was "
                       "skipped.")
            return []
        if rw.lencyl > 0.0:
            state.warn(
                f"{label}: LENCYL = {rw.lencyl:g} makes the LS-DYNA cylinder "
                "FINITE (length running from the tail plane along -n), but "
                "/RWALL/CYL stores only a base point, an axis direction and a "
                "diameter and is AXIALLY INFINITE (there is no length field; "
                "the engine's only contact test is the perpendicular distance "
                "to the axis line, rgwalc.F:129-133) — the converted wall also "
                "blocks nodes beyond both ends of the LS-DYNA cylinder.")
        return [RigidWallGeomFace(
            rwid=rw.rwid, title=title, form="CYL",
            m=(rw.xt, rw.yt, rw.zt), m1=(rw.xh, rw.yh, rw.zh),
            diameter=2.0 * rw.radcyl)]

    if rw.shape == "SPHERE":
        if rw.radsph <= 0.0:
            state.warn(f"{label}: RADSPH = {rw.radsph:g} — a zero-radius "
                       "sphere never contacts anything, so the wall was "
                       "skipped.")
            return []
        # /RWALL/SPHER has no card 4: M is the centre and Diameter the size
        # (hm_read_rwall_spher.F:204-206, 230).
        return [RigidWallGeomFace(
            rwid=rw.rwid, title=title, form="SPHER",
            m=(rw.xt, rw.yt, rw.zt), diameter=2.0 * rw.radsph)]

    # ── FLAT / PRISM ────────────────────────────────────────────────────────
    tail = (rw.xt, rw.yt, rw.zt)
    head = (rw.xh, rw.yh, rw.zh)
    plane_face = RigidWallGeomFace(rwid=rw.rwid, title=title, form="PLANE",
                                   m=tail, m1=head)
    n = _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt))
    if n is None:
        state.warn(f"{label}: degenerate wall normal (head == tail) — the "
                   "wall orientation is undefined, so it was skipped.")
        return []
    if rw.lenl <= 0.0 or rw.lenm <= 0.0:
        # "LENL/LENM: Length of the l/m edge. A ZERO VALUE DEFINES AN INFINITE
        # SIZE PLANE" (Manual p. 40-9, and the same wording for the prism on
        # p. 40-10) — so for a FLAT wall /RWALL/PLANE through the tail with
        # M1 = head is the EXACT conversion, not an approximation, and no
        # warning is due. dyna2rad instead builds a 1e20 x 1e20 PARAL quadrant
        # anchored at the tail, which misses every node on its -l/-m side.
        if rw.shape == "FLAT":
            return [plane_face]
        state.warn(
            f"{label}: LENL/LENM = 0 defines an INFINITE plane (Manual "
            "p. 40-10), so the prism has no finite top face to extrude — "
            "emitted as an INFINITE /RWALL/PLANE through the tail point (the "
            "prism's four side faces and its bottom face are lost).")
        return [plane_face]

    # The wall IS finite, so it needs the in-plane l direction. The test is
    # tail-relative — HEV is a POINT (Manual p. 40-9, "coordinate of head of
    # edge vector l"), so l = HEV - tail; a blank card means l = -tail, not
    # "infinite plane". Classifying on the ABSOLUTE HEV instead (what
    # rigidwall_geometric.cfg:416 does for its HyperMesh geometrytype radio)
    # is not *INCLUDE_TRANSFORM-invariant: a translation moves HEV off the
    # global origin and the same physical wall would convert differently
    # depending on how the deck is assembled.
    triad = _rwall_geom_triad(rw, n)
    if triad is None:
        state.warn(
            f"{label}: the edge-vector head (XHEV,YHEV,ZHEV) coincides with "
            "the wall tail or projects onto the wall normal, so the l edge "
            "direction is undefined — emitted as an INFINITE /RWALL/PLANE "
            "through the tail point, which blocks more than the finite "
            "LS-DYNA wall does"
            + (" (the prism's four side faces and its bottom face are lost)."
               if rw.shape == "PRISM" else "."))
        return [plane_face]

    nu, lu, mu = triad
    lvec = (rw.lenl * lu[0], rw.lenl * lu[1], rw.lenl * lu[2])
    mvec = (rw.lenm * mu[0], rw.lenm * mu[1], rw.lenm * mu[2])
    add = lambda *vs: tuple(sum(v[i] for v in vs) for i in range(3))
    # /RWALL/PARAL takes the two opposite corner POINTS; the starter forms the
    # normal as (M1-M) x (M2-M) = LENL*LENM*(l x m) = +n̂ and keeps the
    # UN-normalized edge vectors as the patch extents (hm_read_rwall_paral.F:
    # 245-267), so the LS-DYNA outward normal is preserved exactly.
    top = RigidWallGeomFace(rwid=rw.rwid, title=title, form="PARAL",
                            m=tail, m1=add(tail, lvec), m2=add(tail, mvec))
    if rw.shape == "FLAT":
        return [top]

    if rw.lenp <= 0.0:
        state.warn(
            f"{label}: LENP = 0 makes the prism infinitely deep along -n; the "
            "four side faces and the bottom face would each need a "
            "semi-infinite /RWALL/PARAL, which does not exist — only the top "
            "face was emitted (dyna2rad emits four walls with a zero edge "
            "vector here, which the starter rejects with ERROR 168).")
        return [top]

    pvec = (-rw.lenp * nu[0], -rw.lenp * nu[1], -rw.lenp * nu[2])
    neg = lambda v: (-v[0], -v[1], -v[2])
    # Box corner T with edges +l (LENL), +m (LENM) and -n (LENP). Each face is
    # (M, M1, M2) with (M1-M) x (M2-M) pointing OUT of the box, so the six
    # walls together keep nodes outside the prism — the same decomposition
    # dyna2rad uses (convertrwalls.cxx:299-374), verified face by face.
    faces = [top]
    for suffix, m0, e1, e2 in (
            ("2", tail,                      pvec,      lvec),   # m = 0
            ("3", tail,                      mvec,      pvec),   # l = 0
            ("4", add(tail, mvec),           lvec,      pvec),   # m = LENM
            ("5", add(tail, mvec, lvec),     neg(mvec), pvec),   # l = LENL
            ("6", add(tail, pvec),           mvec,      lvec)):  # p = LENP
        faces.append(RigidWallGeomFace(
            rwid=alloc_rwid(), title=f"{title}_FACE{suffix}", form="PARAL",
            m=m0, m1=add(m0, e1), m2=add(m0, e2)))
    return faces


def _resolve_geometric_rigid_walls(state: ConversionState) -> None:
    """build_starter prepass for *RIGIDWALL_GEOMETRIC_*.

    Resolves every geometric wall to its concrete Radioss wall(s) (so the
    geometry warnings are raised exactly once), allocates the extra /RWALL ids
    a PRISM's five additional faces need, and synthesizes the _MOTION carrier
    nodes. Must run before the /NODE section is built and alongside the other
    node-synthesizing prepasses, which all allocate off max(state.nodes)+1.
    """
    if not state.rigid_walls_geometric:
        return
    used_rwids = ({rw.rwid for rw in state.rigid_walls}
                  | {g.rwid for g in state.rigid_walls_geometric})
    next_node = (max(state.nodes) + 1) if state.nodes else 90000001

    def alloc_rwid() -> int:
        # /RWALL ids are checked by ONE starter UDOUBLE pass across PLANE, CYL,
        # SPHER and PARAL (read_rwall.F), so a synthesized face id must dodge
        # every wall in the deck, not just the geometric ones.
        rid = state.next_id()
        while rid in used_rwids:
            rid = state.next_id()
        used_rwids.add(rid)
        return rid

    for rw in state.rigid_walls_geometric:
        label = f"*RIGIDWALL_GEOMETRIC_{rw.shape} id={rw.rwid}"
        title = rw.title or f"RWALL_{rw.rwid}"
        rw.faces = _rwall_geom_faces(rw, state, label, title, alloc_rwid)
        if not rw.faces:
            rw.motion = False
            continue
        if len(rw.faces) > 1:
            # Every box EDGE is covered by two of the six faces and every
            # CORNER by three, so the tracked nodes carry overlapping rigid-wall
            # constraints by construction. The starter reports that as
            # WARNING 312 with roughly 5 x (tracked nodes) conditions; it is
            # expected, not a deck error — the engine resolves each wall in
            # turn (rgwal0.F loops over NRWALL) and a convex-edge hit splits
            # the impulse between the two adjoining faces.
            msg = (f"{label}: Radioss has no box rigid wall, so the prism "
                   f"became {len(rw.faces)} separate /RWALL/PARAL faces (ids "
                   + ", ".join(str(f.rwid) for f in rw.faces)
                   + "). They share the tracked node group and overlap along "
                   "the box edges, so the starter raises WARNING ID 312 "
                   "(INCOMPATIBLE KINEMATIC CONDITIONS ... BETWEEN SEVERAL "
                   "RIGID WALLS) — expected for this decomposition.")
            if state.db_rwforc_dt > 0.0:
                msg += (" The /TH/RWALL reaction is likewise split across "
                        f"{len(rw.faces)} entries — sum them to compare "
                        "against one LS-DYNA rwforc record.")
            state.warn(msg)
        if not rw.motion:
            continue
        # ── _MOTION validity ────────────────────────────────────────────────
        if rw.lcid <= 0:
            state.warn(
                f"{label}: the MOTION card has no load curve (LCID = 0), so "
                "there is nothing to prescribe — the wall is emitted as a "
                "FIXED wall rather than as a free, unconstrained one "
                "(dyna2rad emits the massless free wall).")
            rw.motion = False
            continue
        if rw.lcid not in state.curves:
            state.warn(
                f"{label}: MOTION curve LCID={rw.lcid} is not in the deck — "
                "the wall is emitted as a FIXED wall.")
            rw.motion = False
            continue
        if _vnorm((rw.vx, rw.vy, rw.vz)) is None:
            state.warn(
                f"{label}: the MOTION direction cosines VX/VY/VZ are all zero, "
                "so the motion direction is undefined — the wall is emitted as "
                "a FIXED wall (dyna2rad silently moves it along global +X).")
            rw.motion = False
            continue
        # A moving /RWALL takes its base point M from the carrier node's
        # coordinates and replaces the XM/YM/ZM card with "Mass VX0 VY0 VZ0"
        # (hm_read_rwall_cyl.F:199-230) — so every DISTINCT face base point
        # needs a node there, and one prescribed-motion card drives them all.
        # Faces that share a base point (a prism's top and its two faces
        # through the tail corner) share one node: several /RWALLs may name
        # the same MSR, and fewer carrier nodes means fewer of them landing in
        # a neighbouring face's secondary-node search.
        by_point: Dict[Tuple[float, float, float], int] = {}
        for face in rw.faces:
            nid = by_point.get(face.m)
            if nid is None:
                nid = by_point[face.m] = next_node
                next_node += 1
                state.nodes[nid] = NodeData(*face.m)
            face.node_id = nid
        state.warn(
            f"{label}: MOTION → the wall is carried by synthesized free "
            f"node(s) {', '.join(str(n) for n in sorted(by_point.values()))} "
            f"driven by /{'IMPVEL' if rw.opt == 0 else 'IMPDISP'} on curve "
            f"{rw.lcid}; /RWALL itself has no motion-curve field, and the "
            "imposed motion wins over the wall reaction (resol.F calls FIXVEL "
            "after RGWALF). The wall's own Mass field stays 0, matching the "
            "LS-DYNA card, which specifies no wall mass — and a zero-mass "
            "carrier node makes the motion PURELY kinematic: rgwal0.F:417-423 "
            "scales the wall reaction by MS(MSR)/(MS(MSR)+Sum(m_secondary)), "
            "which is 0 here, so contact can never accelerate or laterally "
            "drift the wall (unlike a *RIGIDWALL_PLANAR_MOVING wall, which "
            "carries a real mass).")


def _make_geometric_rwall_motion(rw, state: ConversionState,
                                 grnod_id: int) -> List[str]:
    """The /SKEW/FIX + /GRNOD + /IMPVEL|/IMPDISP driving a _MOTION wall.

    LS-DYNA gives a motion DIRECTION (VX,VY,VZ direction cosines) plus a curve
    that carries the amplitude; /IMPVEL and /IMPDISP prescribe along one axis
    of a skew, so the direction becomes a /SKEW/FIX whose local X' is the
    motion vector and the card asks for Dir = "X". /SKEW/FIX's two vector
    cards are the local Y' and Z' (NOT X and Y), and the starter rebuilds
    X' = Y' x Z' (hm_read_skw.F:448-459): with Y' = ê x V and Z' = V x Y',
    X' = Y' x Z' = V |Y'|^2, i.e. exactly +V.
    """
    v = _vnorm((rw.vx, rw.vy, rw.vz))
    # ê = global Z, or global X when V is parallel to Z (a zero cross product).
    yax = _vnorm(_vcross((0.0, 0.0, 1.0), v))
    if yax is None:
        yax = _vnorm(_vcross((1.0, 0.0, 0.0), v))
    zax = _vnorm(_vcross(v, yax))
    skew_id = state.reserve_skew_id(state.next_id())
    motion_id = state.next_id()
    keyword = "IMPVEL" if rw.opt == 0 else "IMPDISP"
    lines = _emit_skew_fix(skew_id, f"RWALL_{rw.rwid}_MOTION_DIR",
                           (0.0, 0.0, 0.0), yax, zax)
    lines += [
        f"/{keyword}/{motion_id}",
        f"RWALL_{rw.rwid}_MOTION",
        "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID  frame_ID     Icoor",
        f"{_i(rw.lcid)}{'X'.rjust(10)}{_i(skew_id)}         0{_i(grnod_id)}"
        "         0         0",
        "#           Ascale_x            Fscale_Y              Tstart               Tstop",
        f"                   1{_f(1.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, f"RWALL_{rw.rwid}_MOTION_NODES",
                              sorted({f.node_id for f in rw.faces}))
    return lines


def _emit_rwall_geom_face(face: RigidWallGeomFace, slide: int, fric: float,
                          grnd1: int, grnd2: int, d: float) -> List[str]:
    """One /RWALL block in the exact cfg FORMAT(radioss51) layout.

    Card 1 is exactly 40 columns (cols 41-50 are the 2026-only Iform, silently
    dropped at /BEGIN 2022); card 2 is the full 90-column
    "d fric Diameter ffac ifq" (20/20/20/20/10). Diameter is meaningful for CYL
    and SPHER only and is read-but-unused for PLANE/PARAL. The title line is
    MANDATORY: omitting it shifts every following card by one and the starter
    accepts the result with 0 ERRORS.
    """
    lines = [
        f"/RWALL/{face.form}/{face.rwid}",
        face.title,
        "#  node_ID     Slide  grnd_ID1  grnd_ID2",
        f"{_i(face.node_id)}{_i(slide)}{_i(grnd1)}{_i(grnd2)}",
        "#           D_search                fric            Diameter"
        "                ffac       ifq",
        f"{_f(d)}{_f(fric if slide == 2 else 0.0)}{_f(face.diameter)}"
        f"{_f(0.0)}{_i(0)}",
    ]
    if face.node_id:
        # Moving form: M comes from the node, and the card carries the wall
        # mass + initial velocity instead. A *RIGIDWALL_PLANAR_MOVING wall
        # puts its LS-DYNA mass and V0 here; a geometric _MOTION wall leaves
        # both at 0 — that card specifies no mass, and the prescribed motion
        # (applied by FIXVEL, after RGWALF) sets the velocity every cycle.
        lines += [
            "#               Mass                VX_0             "
            "   VY_0                VZ_0",
            f"{_f(face.mass)}{_f(face.v0[0])}{_f(face.v0[1])}{_f(face.v0[2])}",
        ]
    else:
        lines += [
            "#                 XM                  YM                  ZM",
            f"{_f(face.m[0])}{_f(face.m[1])}{_f(face.m[2])}",
        ]
    if face.m1 is not None:                      # PLANE, CYL, PARAL
        lines += [
            "#                XM1                 YM1                 ZM1",
            f"{_f(face.m1[0])}{_f(face.m1[1])}{_f(face.m1[2])}",
        ]
    if face.m2 is not None:                      # PARAL only
        lines += [
            "#                XM2                 YM2                 ZM2",
            f"{_f(face.m2[0])}{_f(face.m2[1])}{_f(face.m2[2])}",
        ]
    lines.append(HDR)
    return lines


def _rwall_bbox_corners(state: ConversionState):
    """The 8 corners of the mesh bounding box, or [] for an empty mesh."""
    if not state.nodes:
        return []
    xs = [n.x for n in state.nodes.values()]
    ys = [n.y for n in state.nodes.values()]
    zs = [n.z for n in state.nodes.values()]
    return [(x, y, z) for x in (min(xs), max(xs))
            for y in (min(ys), max(ys)) for z in (min(zs), max(zs))]


def _rwall_search_distance(face: RigidWallGeomFace, corners,
                           state: ConversionState, label: str) -> float:
    """The ``d`` that makes the /RWALL distance search cover the whole mesh.

    LS-DYNA's NSID = 0 means "All nodes are tracked with respect to the rigid
    wall" (Manual p. 40-7). The 2022 /RWALL format has no "all nodes" group
    id, so the tracked set has to come from the search distance — and the
    starter measures that distance from the wall SURFACE, keeping only
    ``DISN >= 0 .AND. DISN <= DIST`` (hm_read_rwall_{plane,paral,cyl,spher}.F):

        PLANE / PARAL   DISN = (X - M) . n̂
        CYL             DISN = |(X - M) - ((X - M).â)â| - Phi/2
        SPHER           DISN = |X - M| - Phi/2

    The model's bounding-box DIAGONAL is NOT an upper bound for any of those
    — an impactor cylinder or sphere parked outside the structure (the normal
    geometry for the geometric family) is further from the mesh than the mesh
    is wide, and the wall then tracks NOTHING, is emitted completely inert,
    and neither the converter nor the starter says a word.

    Each DISN above is a convex function of X, so its maximum over the mesh is
    attained at a bounding-box CORNER: eight evaluations give a tight,
    guaranteed-sufficient d (with a 0.1% margin for the 10-significant-digit
    card field). Returns 0.0 when no corner is in front of the wall, after
    warning — no search distance can help there.
    """
    if not corners:
        return 1e10                     # no mesh: keep the wall harmless
    m = face.m
    rel = [(c[0] - m[0], c[1] - m[1], c[2] - m[2]) for c in corners]
    if face.form == "SPHER":
        vals = [math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
                - 0.5 * face.diameter for v in rel]
    elif face.form == "CYL":
        ax = _vnorm((face.m1[0] - m[0], face.m1[1] - m[1], face.m1[2] - m[2]))
        if ax is None:                  # already refused upstream (ERROR 167)
            return 1e10
        vals = []
        for v in rel:
            d1 = v[0] * ax[0] + v[1] * ax[1] + v[2] * ax[2]
            d2 = v[0] ** 2 + v[1] ** 2 + v[2] ** 2
            vals.append(math.sqrt(max(d2 - d1 * d1, 0.0)) - 0.5 * face.diameter)
    else:                               # PLANE / PARAL
        if face.m2 is None:             # PLANE: n̂ = normalize(M1 - M)
            nrm = _vnorm((face.m1[0] - m[0], face.m1[1] - m[1],
                          face.m1[2] - m[2]))
        else:                           # PARAL: n̂ = normalize((M1-M) x (M2-M))
            nrm = _vnorm(_vcross(
                (face.m1[0] - m[0], face.m1[1] - m[1], face.m1[2] - m[2]),
                (face.m2[0] - m[0], face.m2[1] - m[1], face.m2[2] - m[2])))
        if nrm is None:                 # already refused upstream
            return 1e10
        vals = [v[0] * nrm[0] + v[1] * nrm[1] + v[2] * nrm[2] for v in rel]
    top = max(vals)
    if top > 0.0:
        return top * 1.001
    if top < 0.0:
        state.warn(
            f"{label}: the wall tracks ALL nodes (NSID = 0), but every node "
            "in the model lies BEHIND its outward normal — the starter's "
            "search keeps only DISN >= 0, so the wall gets no secondary nodes "
            "and is inert. Check the tail/head order on Card 2: the normal "
            "points FROM (XT,YT,ZT) TO (XH,YH,ZH).")
    # top == 0 means every node sits exactly on the wall surface; any d > 0
    # takes them all, and d = 0 would switch the search off entirely
    # (``IF (DIST /= ZERO)``), so never return zero here.
    return 1e10


def _rwall_node_groups(state: ConversionState, label: str, rwid: int,
                       nsid: int, nsidex: int, boxid: int,
                       carrier_nodes=(), carrier_grnod=None):
    """A rigid wall's tracked (grnd_ID1) and excluded (grnd_ID2) node groups.

    Returns (grnd_ID1, grnd_ID2, /GRNOD blocks), or None when the wall must be
    dropped entirely. NSID wins over BOXID (matching dyna2rad); a box-only wall
    becomes a /GRNOD of the in-box nodes; neither means "track ALL nodes",
    which the caller expresses with a search distance d because the 2022
    /RWALL format has no "all nodes" group id.

    ``carrier_nodes`` are the synthesized moving-wall carrier nodes in the
    deck. They are real /NODE entries, so a "track ALL nodes" distance search
    picks them up as SECONDARY nodes of a neighbouring wall — the starter
    excludes only the wall's own main node (``I /= MSR``,
    hm_read_rwall_paral.F:281) — and the rigid-wall constraint then fights the
    /IMPVEL|/IMPDISP that is supposed to drive them (starter WARNING 312, and
    the prescribed motion is no longer trustworthy). A prism's six faces sit on
    each other's box corners, so they hit this at DISN = 0 exactly. Putting
    them in grnd_ID2 clears it: the "Node group -" pass runs AFTER the distance
    search and simply zeroes LPRW (hm_read_rwall_spher.F:266-274). Feeding a
    face its OWN carrier node there is harmless, so all walls share one group
    — ``carrier_grnod`` is a one-element cache the caller uses to emit it once.
    """
    grnd1 = grnd2 = 0
    grnod_blocks: List[str] = []
    if nsid > 0:
        set_title, nids = state.node_sets.get(nsid, ("", []))
        if nids:
            grnd1 = state.next_id()
            grnod_blocks += _emit_grnod_node(
                grnd1, set_title or f"rwall_{rwid}_nodes", nids)
        else:
            state.warn(
                f"{label}: node set {nsid} not "
                "found — the wall tracks ALL nodes instead.")
    # BOXID scopes the tracked node group. dyna2rad drops the box when NSID
    # is also given (NSID wins); a box-only wall becomes a /GRNOD of the
    # in-box nodes (the same role the NSID set plays above).
    if boxid:
        if grnd1:
            state.warn(
                f"{label}: both NSID and BOXID given "
                "— BOXID dropped, the NSID node set scopes the wall "
                "(matching dyna2rad).")
        else:
            box_nids = _resolve_box_nodes(
                state, boxid, f"{label} BOXID={boxid}")
            if box_nids:
                box_nids = sorted(box_nids)
                grnd1 = state.next_id()
                grnod_blocks += _emit_grnod_node(
                    grnd1, f"rwall_{rwid}_box{boxid}", box_nids)
                state.warn(
                    f"{label}: tracked nodes scoped "
                    f"to the {len(box_nids)} node(s) inside *DEFINE_BOX "
                    f"{boxid}.")
            elif box_nids is not None:          # resolved but empty
                state.warn(
                    f"{label}: *DEFINE_BOX {boxid} "
                    "encloses no mesh node — no slave nodes, so the wall is "
                    "inactive (LS-DYNA tracks nothing); the wall was skipped "
                    "rather than falling back to tracking ALL nodes.")
                return None
    # Only a distance search (grnd_ID1 = 0) can sweep in a foreign carrier
    # node; an explicit tracked group never contains one, and d is 0 there.
    extra = sorted(carrier_nodes) if not grnd1 else []
    if nsidex > 0:
        set_title, nids = state.node_sets.get(nsidex, ("", []))
        if nids or extra:
            grnd2 = state.next_id()
            grnod_blocks += _emit_grnod_node(
                grnd2, set_title or f"rwall_{rwid}_excluded",
                sorted(set(nids) | set(extra)))
        if not nids:
            state.warn(
                f"{label}: excluded node set "
                f"{nsidex} not found — no nodes excluded.")
    elif extra:
        if carrier_grnod:                       # already emitted for a sibling
            grnd2 = carrier_grnod[0]
        else:
            grnd2 = state.next_id()
            grnod_blocks += _emit_grnod_node(
                grnd2, "rwall_moving_carrier_nodes", extra)
            if carrier_grnod is not None:
                carrier_grnod.append(grnd2)
    return grnd1, grnd2, grnod_blocks


def _rwall_slide(fric: float, state: ConversionState, label: str,
                 planar: bool) -> int:
    """LS-DYNA FRIC → the /RWALL ``Slide`` flag.

    0 = frictionless sliding, 1 = tied, 2 = Coulomb friction with the
    coefficient on card 2. "FRIC could be any positive value. Three special
    values of FRIC trigger special treatments" (Manual p. 40-20) — so the
    table is a set of EXACT matches, not a threshold, and it differs by
    family:

    *RIGIDWALL_PLANAR (Manual p. 40-20)   *RIGIDWALL_GEOMETRIC (p. 40-8)
      0.0  frictionless sliding             0.0  frictionless sliding
      1.0  no sliding                       1.0  no sliding
      2.0  weld above WVEL, sliding ok      -    (no weld values)
      3.0  weld above WVEL, no sliding      -
      else Coulomb mu = FRIC                else Coulomb mu = FRIC

    The geometric card documents only 0.0 and 1.0, so FRIC = 2.0 there is a
    plain Coulomb coefficient of 2.0 and must NOT be read as a weld. A
    ``FRIC >= 1.0 → tied`` threshold silently turns every high-friction wall
    into a no-slip one and throws the coefficient away; dyna2rad's geometric
    path has the opposite defect (``FRIC > 0 → Slide 2``, which turns the
    tied FRIC = 1.0 into mu = 1.0, convertrwalls.cxx:234-238).
    """
    if fric == 0.0:
        return 0
    if fric == 1.0:
        return 1
    if fric < 0.0:
        state.warn(f"{label}: FRIC = {fric:g} is negative; LS-DYNA's FRIC is "
                   '"any positive value" (Manual p. 40-20) — treated as a '
                   "frictionless wall (Slide 0).")
        return 0
    if planar and fric in (2.0, 3.0):
        # WVEL-gated welding: the node sticks to the wall once its normal
        # impact velocity exceeds WVEL. /RWALL has no velocity-gated mode, so
        # take the closest unconditional one and say so.
        tied = fric == 3.0
        state.warn(
            f"{label}: FRIC = {fric:g} welds a node to the wall once its "
            "normal impact velocity exceeds WVEL (Manual p. 40-20"
            + ("; no sliding after welding)" if tied else
               "; frictionless sliding after welding)")
            + ". /RWALL has no velocity-gated weld, so the wall is emitted "
            + ("tied (Slide 1) UNCONDITIONALLY — nodes below WVEL are tied "
               "too, and they would rebound in LS-DYNA."
               if tied else
               "frictionless (Slide 0) — nodes above WVEL are NOT held "
               "against the wall and will rebound, which LS-DYNA prevents."))
        return 1 if tied else 0
    return 2


def _rwall_planar_face(rw, state: ConversionState) -> RigidWallGeomFace:
    """The one Radioss wall a *RIGIDWALL_PLANAR resolves to.

    M = LS-DYNA tail (XT,YT,ZT), M1 = head (XH,YH,ZH): both codes point the
    outward normal from the first point to the second. _FINITE becomes
    /RWALL/PARAL with the two opposite corner points (falling back to the
    infinite /RWALL/PLANE, with a warning, when the extents are unusable), and
    _MOVING becomes the moving form: node_ID = the synthesized carrier node,
    with the wall mass and V0 (along the outward unit normal) on its card.
    """
    title = rw.title or f"RWALL_{rw.rwid}"
    paral = _rwall_finite_corners(rw, state) if rw.finite else None
    face = RigidWallGeomFace(
        rwid=rw.rwid, title=title,
        form="PARAL" if paral is not None else "PLANE",
        m=(rw.xt, rw.yt, rw.zt),
        m1=paral[0] if paral is not None else (rw.xh, rw.yh, rw.zh),
        m2=paral[1] if paral is not None else None)
    if not rw.moving:
        return face
    face.node_id = rw.node_id
    face.mass = rw.mass
    nrm = _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt))
    if nrm is None:
        state.warn(
            f"*RIGIDWALL_PLANAR_MOVING id={rw.rwid}: degenerate wall normal "
            "(head == tail) — initial velocity V0 dropped (wall starts at "
            "rest).")
    else:
        face.v0 = (rw.v0 * nrm[0], rw.v0 * nrm[1], rw.v0 * nrm[2])
    return face


def _make_rigid_walls(state: ConversionState) -> List[str]:
    """*RIGIDWALL_PLANAR and *RIGIDWALL_GEOMETRIC_* → /RWALL/*.

    Every wall of both families goes through ONE card writer
    (``_emit_rwall_geom_face``) in the exact cfg FORMAT(radioss51) layout
    (hm_cfg_files RWALL/{plane,paral,cyl,sphere}.cfg): the mandatory title
    line, card 1 "node_ID Slide grnd_ID1 grnd_ID2" (4 x I10, exactly 40
    columns), card 2 "D_search fric Diameter ffac ifq" (20/20/20/20/10), then
    "Mass VX0 VY0 VZ0" (moving, node_ID > 0) or "XM YM ZM" (fixed), then
    "XM1 YM1 ZM1" (PLANE/CYL/PARAL) and "XM2 YM2 ZM2" (PARAL).

    A wall with NSID = 0 tracks ALL nodes; /RWALL has no "all" group id, so
    grnd_ID1 stays 0 and the tracked set comes from the search distance d —
    see ``_rwall_search_distance`` for how far that has to reach.
    """
    if not (state.rigid_walls or state.rigid_walls_geometric):
        return []
    lines: List[str] = []

    corners = _rwall_bbox_corners(state)
    # Every synthesized moving-wall carrier node in the deck: excluded from
    # any OTHER wall's "track all nodes" distance search (see the
    # _rwall_node_groups docstring). carrier_grnod caches the shared /GRNOD id.
    carriers = {rw.node_id for rw in state.rigid_walls if rw.node_id > 0}
    carriers |= {f.node_id for rw in state.rigid_walls_geometric
                 for f in rw.faces if f.node_id > 0}
    carrier_grnod: List[int] = []

    th_wall_ids: List[Tuple[int, str]] = []

    def emit(label: str, rwid: int, nsid: int, nsidex: int, boxid: int,
             fric: float, faces: List[RigidWallGeomFace], planar: bool,
             motion=None) -> None:
        # A face's OWN carrier node is already excluded by the starter's
        # `I /= MSR`, so the exclusion group is only worth emitting when some
        # face would otherwise sweep in a FOREIGN one.
        foreign = carriers if any(carriers - {f.node_id} for f in faces) else ()
        groups = _rwall_node_groups(state, label, rwid, nsid, nsidex, boxid,
                                    foreign, carrier_grnod)
        if groups is None:
            return
        grnd1, grnd2, grnod_blocks = groups
        slide = _rwall_slide(fric, state, label, planar)
        # All faces of a prism share one tracked group, one friction setting
        # and (for _MOTION) one prescribed-motion card.
        for face in faces:
            d = 0.0 if grnd1 else _rwall_search_distance(
                face, corners, state, label)
            lines.extend(_emit_rwall_geom_face(face, slide, fric,
                                               grnd1, grnd2, d))
            th_wall_ids.append((face.rwid, face.title))
        if motion is not None:
            lines.extend(motion())
        lines.extend(grnod_blocks)

    for rw in state.rigid_walls:
        emit(f"*RIGIDWALL_PLANAR id={rw.rwid}", rw.rwid, rw.nsid, rw.nsidex,
             rw.boxid, rw.fric, [_rwall_planar_face(rw, state)], planar=True)

    # *RIGIDWALL_GEOMETRIC_* — geometry already resolved to concrete Radioss
    # walls by the _resolve_geometric_rigid_walls prepass (which also created
    # the _MOTION carrier nodes, since those must exist before /NODE).
    for rw in state.rigid_walls_geometric:
        if not rw.faces:
            continue
        emit(f"*RIGIDWALL_GEOMETRIC_{rw.shape} id={rw.rwid}", rw.rwid,
             rw.nsid, rw.nsidex, rw.boxid, rw.fric, rw.faces, planar=False,
             motion=(lambda rw=rw: _make_geometric_rwall_motion(
                 rw, state, state.next_id())) if rw.motion else None)

    # *DATABASE_RWFORC → /TH/RWALL (wall resultant IMPULSE time history).
    #
    # DEF expands to FNX/Y/Z + FTX/Y/Z (starter hm_read_thgrou.F IVARRWG), and
    # those are a time-ACCUMULATED impulse, not the instantaneous wall force
    # LS-DYNA's rwforc reports. engine/source/constraints/general/rwall/
    # rgwal0.F:504-509 does FSAV(1..6) = FSAV(1..6) + FXN..FZT, where FXN..FZT
    # are the summed nodal IMPULSES for the cycle — the engine divides them by
    # DT12 one line earlier to get the true force (:496-500, DIVDT12 = 1/DT12)
    # but routes that only to FOPT (/ANIM) and the sensor buffer FBSAV6
    # (:485-493), never to /TH. thkin.F:56 then copies FSAV out undivided, and
    # nothing resets it on the writing rank (hist2.F:616-622 zeroes FSAV only
    # for ISPMD/=0). Exactly the FTHREAC-vs-FREAC split of the /TH/NODE REAC*
    # channels, one array further along the same FSAV block.
    if state.db_rwforc_dt > 0.0 and th_wall_ids:
        state.warn(
            "*DATABASE_RWFORC -> /TH/RWALL FNX/Y/Z + FTX/Y/Z: these channels "
            "are a time-ACCUMULATED impulse (force x time), not the "
            "instantaneous wall force rwforc reports — the engine accumulates "
            "the per-cycle nodal impulse sums (rgwal0.F:504-509) and sends the "
            "divided-by-dt force only to /ANIM and the sensors "
            "(rgwal0.F:496-500). Differentiate with respect to time "
            "(F = d(FNX)/dt, e.g. numpy.gradient, or tools/th_to_csv.py which "
            "writes the differentiated column) before comparing against an "
            "LS-DYNA rwforc file.")
        th_id = state.next_id()
        lines += [f"/TH/RWALL/{th_id}", "rwall_forces",
                  "#  DEF = FNX/Y/Z + FTX/Y/Z: IMPULSE (force x time), not force",
                  "#  FSAV accumulates F*dt every cycle: wall force = d(FNX)/dt",
                  "#     var1", "DEF       "]
        for rwid, _tit in th_wall_ids:
            lines.append(_i(rwid))
        lines.append(HDR)
    # Every wall may have been dropped by the geometry checks (a degenerate
    # cylinder axis, an empty *DEFINE_BOX); do not leave an empty section.
    return ["#-  RIGID WALLS:", HDR] + lines if lines else []


def _make_modal_dummy_cload(state: ConversionState,
                            rigid_nodes: Set[int]) -> List[str]:
    """Dummy unit load for the modal stiffness-export run.

    The implicit engine refuses to start a solve with no loading data at all
    (MESSAGE ID 79 ``SOLVER IMPLICIT STOPPED DUE TO LOADING DATA``) — and a
    modal deck usually has none, because its LS-DYNA loads (e.g. gravity) are
    irrelevant to the eigenproblem and are skipped by the conversion. So give
    the one /IMPL/LINEAR step a unit /CLOAD on a free structural node: the
    exported stiffness matrix is load-independent, and the resulting static
    solution doubles as the validation reference — the same load solved
    offline (``tools/modal_solve.py --static <node> Z 1``) must reproduce the
    engine displacements to ~0% (exact-K check; W14 bogie: 0.000%).
    """
    if not state.is_modal or state.options.emit_eig:
        return []
    if (state.load_rigid_bodies or state.pressure_loads
            or state.segment_set_pressure_loads
            or state.prescribed_motions or state.prescribed_motion_sets):
        return []                       # the deck already loads something
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2))
    constrained: Set[int] = set()
    for bc in state.bcs_spcs:
        constrained.update(state.node_sets.get(bc.nsid, ("", []))[1])
    candidates = elem_nodes - constrained - rigid_nodes
    if not candidates:
        state.warn(
            "Modal stiffness-export run has no load and no free node to put a "
            "dummy /CLOAD on — the engine will stop with MESSAGE ID 79. Add "
            "any load to the deck manually.")
        return []
    node = max(candidates)              # deterministic, away from low-id corners
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    funct_id = state.next_id()
    grnod_id = state.next_id()
    cload_id = state.next_id()
    state.warn(
        "Modal stiffness-export run: the deck has no load, but the implicit "
        "engine refuses to start without loading data (MESSAGE ID 79). Added "
        f"a dummy unit /CLOAD (node {node}, dir Z). The exported stiffness "
        "matrix is load-independent; the static solution can be cross-checked "
        f"with: tools/modal_solve.py <matrix> --static {node} Z 1"
    )
    lines = [
        "#-  DUMMY STATIC LOAD (modal stiffness-export run needs loading data):",
        HDR,
        f"/FUNCT/{funct_id}",
        "const_unit_load",
        "#                  X                   Y",
        f"{_f(0.0)}{_f(1.0)}",
        f"{_f(max(2.0 * endtim, 1.0))}{_f(1.0)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, "modal_dummy_load_node", [node])
    lines += [
        f"/CLOAD/{cload_id}",
        "modal_dummy_static_load",
        "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
        f"{_i(funct_id)}{'Z'.rjust(10)}{_i(0)}         0{_i(grnod_id)}"
        f"          {_f(1.0)}{_f(1.0)}",
        HDR,
    ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Top-level assemblers
# ─────────────────────────────────────────────────────────────────────────────

#: /DAMP card 1 column header, naming the FORMAT(radioss110) fields of
#: ``radioss110/DAMP/Damp.cfg`` — Alpha(20) Beta(20) grnod_ID(10) skew_ID(10)
#: Tstart(20) Tstop(20). k2rad's own wording, NOT that cfg's COMMENT string:
#: the cfg's is 100 chars with every label right-aligned on its field's last
#: column, this one is 102 and sits two columns to the right of the values it
#: labels. Inherited verbatim from the pre-existing inline literal and kept
#: byte-for-byte, because it is a ``#`` comment the starter never reads and
#: re-aligning it would move the hash of every /DAMP-bearing deck in the
#: corpus for a purely cosmetic gain.
_DAMP_CARD1_HDR = ("#               alpha                beta   grnod_ID"
                   "   skew_ID              Tstart               Tstop")


def _damping_part_nodes(state: ConversionState, pids: Set[int],
                        rigid_nodes: Set[int]) -> List[int]:
    """Deformable nodes carried by *pids*, rigid-body nodes excluded.

    Only shells and solids are scanned — the same scope ``_make_damping`` has
    always used. Beam / spring / SPH nodes are therefore NOT damped by a
    part-scoped /DAMP; a deck whose damped part is built only from those
    element families gets an empty group and a warning instead of a card.
    """
    return sorted(
        {n for e in state.shell_elems if e.pid in pids
         for n in e.nodes if n > 0 and n not in rigid_nodes}
        | {n for e in state.solid_elems if e.pid in pids
           for n in e.nodes if n > 0 and n not in rigid_nodes}
    )


def _damping_resolve_pids(state: ConversionState, pid: int, is_set: bool,
                          what: str) -> Optional[List[int]]:
    """PID or *SET_PART PSID → a list of part ids, or None when unresolvable.

    *SET_PART_ADD sets arrive pre-expanded by ``_flatten_part_set_adds`` (one
    nesting level), so a single ``state.part_sets`` lookup covers both variants
    — which is also why the resolution has to happen HERE, in the writer, and
    not in the handler.
    """
    if is_set:
        entry = state.part_sets.get(pid)
        if entry is None:
            state.warn(
                f"{what}: *SET_PART {pid} is not defined in this deck (or uses "
                "an unsupported variant such as _COLUMN/_GENERATE) — the "
                "damping scope cannot be resolved, so the card is DROPPED and "
                "those parts run UNDAMPED.")
            return None
        pids = [p for p in entry[1] if p in state.parts]
        missing = sorted(set(entry[1]) - set(pids))
        if missing:
            state.warn(f"{what}: *SET_PART {pid} lists part id(s) {missing} "
                       "with no *PART card — ignored.")
        return pids
    if pid not in state.parts:
        state.warn(f"{what}: part {pid} has no *PART card — the card is "
                   "DROPPED.")
        return None
    return [pid]


def _make_damping(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """Emit /DAMP from *DAMPING_GLOBAL and *DAMPING_PART_STIFFNESS.

    Rayleigh damping: C = α·M + β·K.
    - α from *DAMPING_GLOBAL valdmp (mass-proportional, damps low-freq modes)
    - β from *DAMPING_PART_STIFFNESS coef (stiffness-prop, damps high-freq waves)

    OpenRadioss /DAMP (Reference Guide p.130):
    - Format 1: single α, all DOFs
    - Format 2: per-DOF α and β, 6 lines

    Target nodes:
    - If *DAMPING_PART_STIFFNESS specifies parts, damp those parts' nodes only
    - Otherwise damp all deformable nodes (non-rigid-body)
    OpenRadioss /DAMP does NOT accept grnod_ID=0 as "all nodes" — we always
    emit an explicit /GRNOD/NODE block.

    Note: LS-DYNA's per-part β semantics (β_part = 2·coef/ω_max) cannot be
    exactly preserved without ω_max — we pass the largest coef as-is and warn
    if multiple parts have different values.
    """
    if state.damping_global is None and not state.damping_part_stiffness:
        return []

    alpha = state.damping_global.valdmp if state.damping_global else 0.0
    # Aggregate β from *DAMPING_PART_STIFFNESS — use max coef across all parts
    beta = max((d.coef for d in state.damping_part_stiffness), default=0.0)
    if alpha == 0.0 and beta == 0.0:
        # Reachable through *DAMPING_PART_STIFFNESS with every COEF = 0.0 and no
        # *DAMPING_GLOBAL: COEF EQ.0.0 is documented "Inactive" (Manual Vol I
        # R16 p.15-12), so there is nothing to damp with. Emitting the card
        # anyway costs a /GRNOD over every deformable node in the model and a
        # /DAMP that applies exactly zero damping. Same rule the sibling
        # _make_damping_part_mass applies to SF x curve == 0.
        state.warn(
            "*DAMPING_*: the deck's damping resolves to alpha=0 AND beta=0 "
            "(a *DAMPING_PART_STIFFNESS whose every COEF is 0.0 — documented "
            "'Inactive' — with no *DAMPING_GLOBAL), so there is nothing to "
            "apply; /DAMP not emitted.")
        return []
    target_pids: Set[int] = set()
    if state.damping_part_stiffness:
        coefs = [d.coef for d in state.damping_part_stiffness]
        target_pids = {d.pid for d in state.damping_part_stiffness}
        unique_pids = sorted(target_pids)
        if len(set(coefs)) > 1:
            state.warn(
                f"*DAMPING_PART_STIFFNESS: multiple different coefs across parts "
                f"{unique_pids} - using max={beta:.6G} as global beta (per-part "
                f"damping not directly mappable to /DAMP)."
            )
        state.warn(
            f"*DAMPING_PART_STIFFNESS pid(s) {unique_pids}: coef={beta:.6G} "
            f"used as /DAMP beta directly. LS-DYNA scales by 2/omega_max"
            f" - if waves aren't damped enough, try beta ~ 1e-7 to 1e-6."
        )

    # Resolve target node set
    if target_pids:
        target_nodes = sorted(
            {n for e in state.shell_elems if e.pid in target_pids
             for n in e.nodes if n > 0 and n not in rigid_nodes}
            | {n for e in state.solid_elems if e.pid in target_pids
               for n in e.nodes if n > 0 and n not in rigid_nodes}
        )
        grnod_title = f"damping_target_pids_{'_'.join(str(p) for p in sorted(target_pids))}"
    else:
        # No specific parts → all deformable nodes (rigid bodies excluded —
        # they translate as a unit, damping their nodes is meaningless)
        target_nodes = sorted(
            {n for e in state.shell_elems
             if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
             for n in e.nodes if n > 0 and n not in rigid_nodes}
            | {n for e in state.solid_elems
               if state.parts.get(e.pid, PartData(0, "", 0, 0)).mid not in state.mat_rigid
               for n in e.nodes if n > 0 and n not in rigid_nodes}
        )
        grnod_title = "damping_target_all_deformable"

    if not target_nodes:
        state.warn("*DAMPING_*: no target deformable nodes found - /DAMP not emitted.")
        return []

    # next_grnod_id, not next_id: k2rad re-emits every user *SET_NODE under its
    # own SID, so a set numbered at or above the auto-id base collides with this
    # synthesized group and the starter aborts the whole deck with ERROR 79
    # DUPLICATE ID / IN NODE GROUP DEFINITION. A no-op on any deck without such
    # a set, so no ordinary deck's ids shift.
    grnod_id = state.next_grnod_id()
    damp_id = state.next_id()
    lines = _emit_grnod_node(grnod_id, grnod_title, target_nodes)

    # If only α and no β, use Format 1 (simpler, smaller deck)
    if beta == 0.0:
        d = state.damping_global
        # The guard is now belt-and-braces: alpha comes ONLY from
        # *DAMPING_GLOBAL, so `d is None` implies alpha == 0, and this branch
        # implies beta == 0 — the pair the early return above already took.
        # Before that return existed, a *DAMPING_PART_STIFFNESS whose every
        # COEF was 0.0 reached here with d None and reading d.stx aborted the
        # WHOLE conversion with an AttributeError, not just this card.
        per_dof = ((d.stx, d.sty, d.stz, d.srx, d.sry, d.srz) if d
                   else (0.0,) * 6)
        if any(s != 0.0 for s in per_dof):
            state.warn(
                f"*DAMPING_GLOBAL: per-DOF scale factors (stx..srz) ignored; "
                f"using uniform alpha={alpha:.6G} on all DOFs (/DAMP Format 1)."
            )
        # The /DAMP card always reads Beta from cols 21-40 — there is no
        # "alpha-only" card layout. Beta must be written explicitly as 0,
        # otherwise the grnod_ID digits land in the Beta field and are parsed
        # as a (huge) stiffness-damping coefficient.
        lines += [
            f"/DAMP/{damp_id}",
            f"Rayleigh mass damping (alpha={alpha:.6G})",
            _DAMP_CARD1_HDR,
            f"{_f(alpha)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
            HDR,
        ]
        return lines

    # Format 2: per-DOF α + β. Use uniform (αx=αy=...=α, βx=βy=...=β).
    title = f"Rayleigh damping (alpha={alpha:.6G}, beta={beta:.6G})"
    lines += [
        f"/DAMP/{damp_id}",
        title,
        _DAMP_CARD1_HDR,
        f"{_f(alpha)}{_f(beta)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        f"{_f(alpha)}{_f(beta)}",
        HDR,
    ]
    return lines


def _damping_curve_constant(state: ConversionState, lcid: int,
                            what: str) -> Optional[float]:
    """The single ordinate a /BEGIN 2022 /DAMP can carry for curve *lcid*.

    LS-DYNA's *DAMPING_PART_MASS states its damping constant as ``D_s(t) =
    SF * f_LCID(t)``; plain /DAMP has only a scalar ``Alpha``, and the Radioss
    card that DOES take a function — /DAMP/FUNCT, whose engine kernel computes
    ``alpha = f(t)*Alpha*Alpha_dir`` (``damping_funct_ini.F90:80-99``) — first
    exists in ``radioss2026/DAMP/Damp_funct.cfg``, far above the /BEGIN 2022
    this converter writes.

    So the curve is reduced to its ordinate at the first abscissa. That is
    EXACT for the flat curves these decks almost always use (the corpus case
    ``11.3.sqt_iga_s.k`` is ``(0, 200) (0.01, 200)``), and is warned about
    otherwise. Returns None when the curve cannot be used at all.
    """
    curve = state.curves.get(lcid)
    if curve is None or not curve.pts:
        state.warn(
            f"{what}: load curve {lcid} is not defined in this deck (or has no "
            "points) — the damping constant comes ENTIRELY from that curve, so "
            "the card is DROPPED and those parts run UNDAMPED.")
        return None
    ordinates = [o for _, o in curve.pts]
    value = ordinates[0]
    if any(o != value for o in ordinates):
        state.warn(
            f"{what}: load curve {lcid} is time-VARYING "
            f"(ordinates {min(ordinates):.6G}..{max(ordinates):.6G}); a "
            f"/BEGIN 2022 /DAMP carries a constant Alpha only, so the value at "
            f"the first point ({value:.6G}) is used for the whole run and the "
            "time variation is LOST. The Radioss card that takes a function, "
            "/DAMP/FUNCT, is a radioss2026 keyword.")
    return value


def _make_damping_part_mass(state: ConversionState,
                            rigid_nodes: Set[int]) -> List[str]:
    """*DAMPING_PART_MASS / _SET -> one part-scoped /DAMP per card.

    Both sides apply the SAME force. LS-DYNA (Manual Vol I R16 p.15-8):
    ``F_damp = D_s*m*v``. Radioss ``DAMPING51`` (``engine/source/assembly/
    damping.F:127-170``) subtracts ``DAMP_A*V`` from the nodal acceleration,
    i.e. ``F = -Alpha*m*v``. So ``Alpha = D_s = SF * curve``, with no unit
    conversion and no frequency term — this is the one damping keyword of the
    batch that needs no version bump at all, because plain /DAMP has been
    readable since radioss42.

    dyna2rad does NOT convert this keyword: ``convertdampings.cxx`` runs exactly
    four converters (:38-44) and its only ``SelectionRead`` calls are at lines
    51/167/247/321 — GLOBAL, PART_STIFFNESS, RELATIVE, FREQUENCY_RANGE. The card
    parses cleanly into its model (registered in every profile's
    ``data_hierarchy.cfg`` as ``DAMPING/DampMass.cfg``) and is then silently
    dropped. k2rad converting it is a deliberate super-set, not a parity item.

    Scoping: LS-DYNA damps the PART's nodes; Radioss /DAMP takes a grnod, so one
    /GRNOD/NODE is emitted per card (``grnod_ID = 0`` is NOT "all nodes" on this
    card — see _make_damping).
    """
    if not state.damping_part_mass:
        return []
    lines: List[str] = []
    # LS-DYNA Manual Vol I R16 p.15-9: "cannot be combined with
    # *DAMPING_GLOBAL". Radioss would happily apply both (hm_read_damp.F:146
    # loops over every /DAMP card and damping.F:101 sums their contributions),
    # so the deck would come out MORE damped than LS-DYNA would have run it.
    if state.damping_global is not None:
        state.warn(
            "*DAMPING_PART_MASS: the deck also carries *DAMPING_GLOBAL, which "
            "LS-DYNA forbids combining with it. Radioss applies every /DAMP "
            "card additively, so the converted model is damped by the SUM of "
            "the two — remove one of them.")
    # The /DAMP that _make_damping builds from *DAMPING_PART_STIFFNESS carries a
    # non-zero Beta, and Beta is the term that a shared history buffer corrupts.
    # The clash is on NODES, not on part ids: two conformally meshed parts share
    # the nodes along their common edge, so a part-id intersection would miss
    # exactly the case that bites. And the pid set has to be the one
    # _make_damping actually puts in that /GRNOD — ALL *DAMPING_PART_STIFFNESS
    # pids, unfiltered — not just the ones whose own COEF is non-zero: the
    # single card carries beta = max(coefs), so a part written with COEF 0.0
    # still rides inside the beta-bearing group and its nodes still collide.
    # What decides whether there is a clash at all is whether that MAXIMUM is
    # non-zero.
    stiff_nodes: Set[int] = set()
    stiff_pids = {d.pid for d in state.damping_part_stiffness}
    if stiff_pids and max(d.coef for d in state.damping_part_stiffness) != 0.0:
        stiff_nodes = set(_damping_part_nodes(state, stiff_pids, rigid_nodes))
    for dm in state.damping_part_mass:
        kw = "*DAMPING_PART_MASS_SET" if dm.is_set else "*DAMPING_PART_MASS"
        what = f"{kw} ({'PSID' if dm.is_set else 'PID'}={dm.pid})"
        if dm.lcid == 0:
            state.warn(
                f"{what}: LCID=0. Unlike *DAMPING_GLOBAL this card has NO "
                "constant-value column — the damping constant is read entirely "
                "off the curve — so there is nothing to apply; card DROPPED.")
            continue
        value = _damping_curve_constant(state, dm.lcid, what)
        if value is None:
            continue
        alpha = dm.sf * value
        if alpha == 0.0:
            state.warn(
                f"{what}: SF={dm.sf:.6G} x curve {dm.lcid} = 0, so the card "
                "damps nothing — /DAMP not emitted for it. (If the curve is "
                "flat at zero it really does ask for no damping; if it only "
                "STARTS at zero and ramps up, the time variation that is being "
                "lost has been reported separately — a /BEGIN 2022 /DAMP "
                "carries a constant Alpha and cannot ramp.)")
            continue
        pids = _damping_resolve_pids(state, dm.pid, dm.is_set, what)
        if pids is None:
            continue
        if not pids:
            # An empty (or fully unresolvable) *SET_PART. Distinguished from the
            # "no deformable mesh" case below, which would otherwise report
            # "part(s) [] carry no ... nodes" and name the wrong cause — the
            # same branch _make_damping_frequency_range already has.
            state.warn(f"{what}: *SET_PART {dm.pid} resolved to no existing "
                       "part — /DAMP not emitted for this card.")
            continue
        nodes = _damping_part_nodes(state, set(pids), rigid_nodes)
        if not nodes:
            state.warn(
                f"{what}: part(s) {sorted(pids)} carry no deformable shell or "
                "solid nodes (only rigid, beam, spring or SPH ones, or no mesh "
                "at all) — /DAMP not emitted for this card.")
            continue
        # Per-DOF scale factors. LS-DYNA FLAG=1 means "the global components of
        # the damping forces require separate scale factors"; Radioss holds them
        # in the /DAMP Format-2 per-DOF rows, so alpha_i = SF*curve*ST_i.
        scales = (dm.stx, dm.sty, dm.stz, dm.srx, dm.sry, dm.srz)
        per_dof = dm.flag == 1
        if per_dof and not any(s != 0.0 for s in scales):
            state.warn(
                f"{what}: FLAG=1 requests per-DOF damping scale factors but "
                "STX..SRZ are all 0.0, which would scale the damping to zero "
                "on every DOF. Read as 'uniform' (the all-six-zero convention "
                f"dyna2rad applies on /DAMP/FUNCT) and alpha={alpha:.6G} is "
                "used on all six DOFs.")
            per_dof = False
        if shared := sorted(stiff_nodes.intersection(nodes)):
            # Two /DAMP cards sharing a node share the single per-node history
            # buffer DAMP(1:6,I): damping.F:145 stores A() into it and the next
            # card overwrites, so the FIRST card's Beta term reads a foreign
            # acceleration from the following cycle on. Alpha-only overlap is
            # harmless, which is why only the Beta-bearing case is reported.
            state.warn(
                f"{what}: {len(shared)} node(s) of part(s) {sorted(pids)} "
                f"(e.g. {shared[:5]}) are ALSO in the stiffness-damping /DAMP "
                "built from *DAMPING_PART_STIFFNESS on part(s) "
                f"{sorted(stiff_pids)} — conformally meshed parts share the "
                "nodes along their common edge even when the part lists are "
                "disjoint. Radioss keeps ONE per-node damping history buffer, "
                "so two /DAMP cards sharing a node corrupt the Beta "
                "(stiffness) term of whichever is read first (2022 Reference "
                "Guide p.130 comment 4). Merge them or scope them apart.")
        grnod_id = state.next_grnod_id()
        damp_id = state.next_id()
        lines += _emit_grnod_node(
            grnod_id, f"damping_part_mass_{'pset' if dm.is_set else 'pid'}"
                      f"_{dm.pid}", nodes)
        if not per_dof:
            lines += [
                f"/DAMP/{damp_id}",
                f"Mass damping *DAMPING_PART_MASS lcid={dm.lcid} "
                f"(alpha={alpha:.6G})",
                _DAMP_CARD1_HDR,
                f"{_f(alpha)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
                HDR,
            ]
        else:
            ax, ay, az, axx, ayy, azz = (alpha * s for s in scales)
            # Format 2: the PRESENCE of the five extra cards is what sets
            # Mass_Damp_Factor_Option — there is no explicit switch column.
            lines += [
                f"/DAMP/{damp_id}",
                f"Mass damping *DAMPING_PART_MASS lcid={dm.lcid} per-DOF "
                f"(alpha={alpha:.6G} x STX..SRZ)",
                _DAMP_CARD1_HDR,
                f"{_f(ax)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
                f"{_f(ay)}{_f(0.0)}",
                f"{_f(az)}{_f(0.0)}",
                f"{_f(axx)}{_f(0.0)}",
                f"{_f(ayy)}{_f(0.0)}",
                f"{_f(azz)}{_f(0.0)}",
                HDR,
            ]
    if not lines:
        return []
    return ["#-  PART MASS DAMPING (*DAMPING_PART_MASS -> /DAMP):", HDR] + lines


def _dfr_what(dfr: DampingFrequencyRange) -> str:
    """The keyword spelling + card values that every warning below leads with.

    Built in one place so the two passes of _make_damping_frequency_range
    cannot drift apart in how they name the same card.
    """
    kw = ("*DAMPING_FREQUENCY_RANGE_DEFORM_DMIG" if dfr.dmig else
          "*DAMPING_FREQUENCY_RANGE_DEFORM" if dfr.deform else
          "*DAMPING_FREQUENCY_RANGE")
    return (f"{kw} (CDAMP={dfr.cdamp:.6G}, FLOW={dfr.flow:.6G}, "
            f"FHIGH={dfr.fhigh:.6G})")


def _make_damping_frequency_range(state: ConversionState) -> List[str]:
    """*DAMPING_FREQUENCY_RANGE[_DEFORM] -> /DAMP/FREQUENCY_RANGE.

    Card layout, ``radioss2025/DAMP/Damp_freq_range.cfg``::

        /DAMP/FREQUENCY_RANGE/damp_ID
        title
        #              Cdamp                     grpart_ID          Tstart      Tstop
                %20lg   (20 dead cols)      %10d   (10 dead cols)    %20lg      %20lg
        #           Freq_low           Freq_high
                %20lg               %20lg

    The two dead 10-column slots on card 1 are real: the card was laid out to
    keep ``grpart_ID`` in the same column block as the sibling cards' ``grnod_id``
    / ``skew_id``. They must be spaces.

    VERSION GATE — measured, not assumed. ``radioss2022/data_hierarchy.cfg``
    registers only ``DAMP`` and ``DAMP_INTER`` under ``DAMPING``, so a /BEGIN
    2022 deck names a keyword its registry does not carry. Measured on
    starter_win64 (2026-05-20) with twin decks differing only in /BEGIN: at 2022
    the starter draws ``WARNING ID : 100211  Unsupported option
    /DAMP/FREQUENCY_RANGE in format < 2025`` and then reads the card ANYWAY,
    with every field correct — echo ``PART GROUP ID 91004 / DAMPING RATIO
    2.0E-02 / LOWEST FREQUENCY 10.0 / HIGHEST FREQUENCY 200.0``, identical to
    the /BEGIN 2025 run. (The cfg has exactly one FORMAT block, radioss2025, so
    there is no older layout for the reader to fall back to.) The card is
    therefore emitted, with the warning restated for the user — the opposite
    call from ``*DAMPING_RELATIVE``, whose twin measurement came out MISREAD.

    Fidelity: the single Radioss card IS LS-DYNA's ``_DEFORM`` behaviour.
    Damping is applied as a Maxwell/Prony viscous stress inside the material law
    (``damping_range_{shell,shell_mom,solid}.F90``, reached through
    ``mulawc.F90:1974`` / ``viscmain.F``), gated by the static per-element-group
    flag ``IPARG(93)`` — never as a nodal force, so rigid-body motion is not
    damped and natural frequencies shift UP. Radioss has no nodal variant, so
    the blank (non-DEFORM) LS-DYNA option is an approximation and says so.
    """
    if not state.damping_frequency_range:
        return []
    parts_all = sorted(state.parts)
    # Parts Radioss can actually reach with frequency-range damping — see the
    # element-scope warning below.
    meshed_pids = ({e.pid for e in state.shell_elems}
                   | {e.pid for e in state.solid_elems})

    # Pass 1: validate, then resolve each surviving card's part scope, so the
    # PSID=0 complement and the overlap check both see the whole picture
    # (dyna2rad builds the same union at convertdampings.cxx:323-334). The
    # validation has to happen HERE and not in pass 2: `claimed` is what a
    # PSID=0 card subtracts, and subtracting the parts of a card that is about
    # to be dropped would shrink the complement for no reason. Resolving a DMIG
    # card's PSID would likewise be wrong — there it is a SUPERELEMENT id, not
    # a *SET_PART id, and would draw a misleading "set is not defined" warning.
    resolved: List[Tuple[DampingFrequencyRange, Optional[List[int]]]] = []
    claimed: Set[int] = set()
    for dfr in state.damping_frequency_range:
        what = _dfr_what(dfr)
        if dfr.dmig:
            state.warn(
                f"{what}: the _DMIG option damps a SUPERELEMENT (PSID is a "
                "superelement id, not a part set). k2rad converts no "
                "superelement keywords and Radioss has no equivalent — card "
                "DROPPED.")
            continue
        # The starter's KEY(1:4)=='FREQ' branch validates NEITHER bound. With
        # Freq_low = 0 the starter's f_mid = sqrt(f_low*f_high) is 0, the 3x3
        # collocation matrix of damping_range_compute_param.F90 fills with 0/0
        # and NaN alpha/tau propagate into every element of the group.
        if dfr.flow <= 0.0 or dfr.fhigh <= dfr.flow:
            state.warn(
                f"{what}: needs 0 < FLOW < FHIGH. The Radioss starter fits "
                "three Maxwell branches at [FLOW, sqrt(FLOW*FHIGH), FHIGH] and "
                "validates neither bound, so this card would make that 3x3 "
                "system singular and push NaN damping parameters into every "
                "element of the group — card DROPPED.")
            continue
        if dfr.cdamp <= 0.0:
            state.warn(f"{what}: CDAMP <= 0 damps nothing — card DROPPED.")
            continue
        if dfr.psid == 0:
            resolved.append((dfr, None))
            continue
        pids = _damping_resolve_pids(state, dfr.psid, True, f"{what} PSID")
        if pids is None:
            continue                     # unresolvable PSID, already warned
        if not pids:
            state.warn(f"{what}: *SET_PART {dfr.psid} resolved to no existing "
                       "part — card DROPPED.")
            continue
        resolved.append((dfr, pids))
        claimed |= set(pids)

    lines: List[str] = []
    tagged: Dict[int, str] = {}          # part id -> the card that claimed it
    n_all_parts = 0
    gate_warned = False
    for dfr, pids in resolved:
        # Pass 2 never sees a DMIG card — pass 1 drops those — so _dfr_what's
        # third spelling cannot appear here.
        what = _dfr_what(dfr)

        # ── scope ────────────────────────────────────────────────────────────
        pre: List[str] = []
        if dfr.psid != 0:
            scope = sorted(set(pids or []))
            grpart_id = state.next_id()
            pre = _emit_grpart_part(
                grpart_id, f"damping_freq_range_pset_{dfr.psid}", scope)
        else:
            # LS-DYNA: "If PSID = 0, the damping is applied to all parts EXCEPT
            # those referred to by other *DAMPING_FREQUENCY_RANGE cards."
            # Radioss grpart_ID=0 means all parts with no exclusion AND, worse,
            # re-tags every part (hm_read_damp.F:305-307 DAMP_RANGE_PART(J)=I),
            # silently overriding every earlier card. So the complement is made
            # explicit whenever anything else claimed parts.
            n_all_parts += 1
            scope = [p for p in parts_all if p not in claimed]
            if not claimed:
                grpart_id = 0
                pre = []
            elif not scope:
                state.warn(
                    f"{what}: PSID=0 means 'all parts except those claimed by "
                    "other *DAMPING_FREQUENCY_RANGE cards', and the other "
                    "cards already claim every part in the deck — nothing "
                    "left to damp, card DROPPED.")
                continue
            else:
                grpart_id = state.next_id()
                pre = _emit_grpart_part(
                    grpart_id, "damping_freq_range_all_other_parts", scope)
        if n_all_parts == 2:
            state.warn(
                f"{what}: a SECOND *DAMPING_FREQUENCY_RANGE card also has "
                "PSID=0. Both then cover the same complement set, and Radioss "
                "resolves overlaps by plain overwrite (hm_read_damp.F:299-307) "
                "— the LAST card silently wins on every shared part.")
        if overlap := sorted(p for p in scope if p in tagged):
            state.warn(
                f"{what}: part(s) {overlap} are already damped by "
                f"{tagged[overlap[0]]}. Radioss allows only ONE "
                "/DAMP/FREQUENCY_RANGE per part and resolves the clash by "
                "overwrite, so the LAST card silently wins on them.")
        for p in scope:
            tagged[p] = what

        # ── fidelity warnings ────────────────────────────────────────────────
        if not gate_warned:
            gate_warned = True
            state.warn(
                "*DAMPING_FREQUENCY_RANGE -> /DAMP/FREQUENCY_RANGE is a "
                "radioss2025 keyword and k2rad writes /BEGIN 2022, so the "
                "starter draws 'WARNING ID : 100211 Unsupported option "
                "/DAMP/FREQUENCY_RANGE in format < 2025'. Measured on "
                "starter_win64: the warning is advisory — the card is read "
                "with every field correct (Cdamp/grpart_ID/Freq_low/Freq_high "
                "echo identically under /BEGIN 2022 and 2025), so it is "
                "emitted rather than dropped. Bumping /BEGIN to 2025 by hand "
                "silences it, but note that a 2025 read then raises "
                "'WARNING ID : 100217 card is missing' on the OTHER cards "
                "k2rad writes in the 2022 layout (several gained a trailing "
                "card by 2025 — measured, about a dozen on a small deck, with "
                "0 ERRORS and every field still read back identically).")
        if not dfr.deform:
            state.warn(
                f"{what}: this is the BLANK option, which damps global NODE "
                "motion. Radioss has only the element-level form — damping "
                "enters as a Maxwell/Prony viscous stress inside the material "
                "law (damping_range_shell/solid.F90, gated by IPARG(93)), "
                "which is LS-DYNA's _DEFORM behaviour. Two consequences on "
                "this deck: rigid-body motion is NOT damped, and natural "
                "frequencies shift UP instead of down (Manual Vol I R16 "
                "Remark 3).")
        # Element scope — applies to BOTH options, so it lives outside the
        # blank-option branch. LS-DYNA damps solids, beams, shells, thick
        # shells and discrete elements (Manual Vol I R16 Remark 4); Radioss
        # reaches only shells and solids (damping_range_shell / _shell_mom /
        # _solid.F90), and LAW25 shells are excluded outright
        # (mulawc.F90:1972). Under _DEFORM — advertised as the clean 1:1 —
        # a beam-only or tshell-only part would otherwise lose ALL its damping
        # without a word.
        if unmeshed := sorted(p for p in scope if p not in meshed_pids):
            shown = (f"{unmeshed[:10]} (+{len(unmeshed) - 10} more)"
                     if len(unmeshed) > 10 else str(unmeshed))
            state.warn(
                f"{what}: {len(unmeshed)} part(s) {shown} in the damped scope "
                "carry no shell or solid element. Radioss applies "
                "frequency-range damping inside the shell and solid material "
                "laws only (damping_range_shell/_shell_mom/_solid.F90, and "
                "LAW25 shells are excluded outright, mulawc.F90:1972), while "
                "LS-DYNA damps solids, beams, shells, thick shells and "
                "discrete elements (Manual Vol I R16 Remark 4) — those part(s) "
                "come out COMPLETELY UNDAMPED.")
        if dfr.pidrel:
            state.warn(
                f"{what}: PIDREL={dfr.pidrel} asks for damping of the motion "
                "RELATIVE to that rigid body. /DAMP/FREQUENCY_RANGE has no "
                "such field at any format version (the relative-velocity "
                "reference lives on /DAMP/VREL, a different card) — DROPPED, "
                "so the rigid body's own motion is damped along with "
                "everything else.")
        if dfr.iflg == 0:
            state.warn(
                f"{what}: IFLG=0 selects LS-DYNA's ITERATIVE fit (errors ~1% "
                "of the target CDAMP). Radioss implements a one-shot 3-point "
                "collocation instead (damping_range_compute_param.F90 has no "
                "refinement loop), i.e. the analogue of IFLG=1. Expect the "
                "achieved damping to sit BELOW target across the band — about "
                "-8%..0% at CDAMP=0.01, about -26%..-4% at CDAMP=0.05.")
        if dfr.icard2 == 1:
            state.warn(
                f"{what}: ICARD2=1 supplies CDAMPV={dfr.cdampv:.6G} "
                f"(volumetric/pressure damping for solids) and IPWP={dfr.ipwp} "
                "(pore pressure). Radioss applies one damping ratio to both "
                "the deviatoric and the volumetric branch (damping_range_"
                "solid.F90 scales gv from the shear modulus and kv from Young "
                "with the SAME alpha) and has no pore-pressure switch — both "
                "fields are DROPPED and CDAMP alone is used.")

        # ── the card ─────────────────────────────────────────────────────────
        damp_id = state.next_id()
        scope_txt = "all other parts" if dfr.psid == 0 and grpart_id else \
                    "all parts" if dfr.psid == 0 else f"pset {dfr.psid}"
        lines += pre
        lines += [
            f"/DAMP/FREQUENCY_RANGE/{damp_id}",
            f"Frequency-range damping {dfr.cdamp:.6G} over "
            f"{dfr.flow:.6G}-{dfr.fhigh:.6G} Hz ({scope_txt})",
            "#              Cdamp                     grpart_ID"
            "                        Tstart               Tstop",
            # Tstart/Tstop are read and echoed but INERT for this type: both
            # nodal kernels skip it (damping.F:120-127 guards on
            # FL_FREQ_RANGE==0, DAMPING44 likewise) and the material-law path
            # has no time argument at all. Written as the neutral 0 / 1e30.
            f"{_f(dfr.cdamp)}{' ' * 20}{_i(grpart_id)}{' ' * 10}"
            f"{_f(0.0)}{_f(1.0E30)}",
            "#           Freq_low           Freq_high",
            f"{_f(dfr.flow)}{_f(dfr.fhigh)}",
            HDR,
        ]
    if not lines:
        return []
    return ["#-  FREQUENCY-RANGE DAMPING "
            "(*DAMPING_FREQUENCY_RANGE -> /DAMP/FREQUENCY_RANGE):", HDR] + lines


def _resolve_damping_relative(state: ConversionState,
                              rbody_info: Dict[int, dict]) -> List[str]:
    """*DAMPING_RELATIVE -> /DAMP/VREL: resolved, reported, NOT emitted.

    The mapping itself is exact. LS-DYNA Remark 3 gives ``F = -(D*m*v) -
    (DV2*m*v^2)`` with ``D = 4*pi*CDAMP*FREQ`` and ``v`` relative to the rigid
    body ``PIDRB``; the Radioss engine computes ``damp_a = fact*Alpha_x*4*pi*
    freq`` (``damping_vref_compute_dampa.F90``) and applies ``F = -alpha*m*
    (v - v_ref)`` (``damping.F:231-266``). Field for field:
    ``CDAMP->Alpha_x``, ``FREQ->Freq``, ``PIDRB->RbodyID``, ``DV2->Alpha2_x``,
    ``LCID->FuncID``, ``PSID->grnod_id``.

    VERSION GATE — measured, and it fails. /DAMP/VREL first appears in
    ``radioss2023/DAMP/Damp_Vrel.cfg``; the 2023 block is REDUCED (``Alpha_x
    <blank> grnod_id skew_id Tstart Tstop`` / ``Alpha_y`` / ``Alpha_z``) and
    only radioss2024 adds the ``Freq RbodyID FuncID Xscale`` card and the
    quadratic columns. Measured on starter_win64 (2026-05-20), /BEGIN 2022 vs
    2025 twins carrying the identical 6-line 2024-format card:

      2025  DAMPING FUNCTION ID 91002 / X 3.0E-02 / Y 3.0E-02 / Z 3.0E-02
            DAMPING FREQUENCY 12.5                                    (correct)
      2022  WARNING 100211 "Unsupported option /DAMP/VREL in format < 2023"
            WARNING 100213 "unsupported field exists at the end of line"
            DAMPING FUNCTION ID 0 / X 3.0E-02 / Y 12.5 / Z 3.0E-02
            DAMPING FREQUENCY 0.0

    i.e. at 2022 the reader falls back to the reduced 2023 layout, swallows the
    ``Freq RbodyID FuncID Xscale`` card as if it were the ``Alpha_y`` row, and
    leaves ``Freq`` at 0. That is not a degraded card, it is a wrong one twice
    over: ``Alpha_y`` becomes 12.5 instead of 0.03, and with ``Freq == 0`` the
    engine takes the other branch of ``damping_vref_compute_dampa.F90``,
    ``damp_a = Alpha_x/dt_initial`` — for a dt around 1e-6 that is roughly
    twelve orders of magnitude away from the intended ``4*pi*CDAMP*FREQ``.

    Emitting a card that reads as something else is exactly what
    ``_resolve_contact_interior`` refused to do, so this follows that
    precedent: resolve everything, name every resolved id in the warning so the
    user can paste the correct card into a /BEGIN 2024 deck by hand, and emit
    nothing. Returns [] always; the return type keeps it registry-shaped.
    """
    if not state.damping_relative:
        return []
    state.note_recognized_not_emitted(
        "*DAMPING_RELATIVE",
        "its Radioss counterpart /DAMP/VREL needs the radioss2024 card format; "
        "under the /BEGIN 2022 this converter writes, the starter falls back "
        "to the reduced radioss2023 layout and MISREADS it (measured: Freq "
        "lost to 0, which switches the engine to the alpha=Cdamp/dt_initial "
        "branch, and the Freq value lands in Alpha_y) — the resolved card is "
        "reported in a warning instead")
    for dr in state.damping_relative:
        what = f"*DAMPING_RELATIVE (CDAMP={dr.cdamp:.6G}, FREQ={dr.freq:.6G})"

        if dr.freq <= 0.0:
            # Altair's online card documents the Freq=0 branch as
            # "alpha = CDAMP * dt * Func(t)"; the shipped engine DIVIDES by the
            # initial timestep instead (damping_vref_compute_dampa.F90:
            # `damp_a(1) = fact*dampr(3,id)*(one/dtini)`), latched on first
            # activation. At dt ~ 1e-6 the two readings are ~1e12 apart, so the
            # card is unusable at Freq=0 whichever /BEGIN it lands in.
            state.warn(
                f"{what}: FREQ is 0, and LS-DYNA reads CDAMP as the fraction of "
                "critical damping AT that frequency (D = 4*pi*CDAMP*FREQ), so "
                "the card asks for zero damping. Radioss does something else "
                "entirely on Freq=0 — the engine divides by the INITIAL "
                "timestep (alpha = Alpha_x/dt_initial), which its own "
                "documentation describes as a multiplication; the two readings "
                "are about 1e12 apart at a dt of 1e-6. Set a real FREQ (the "
                "lowest mode of interest) before using the resolved card below.")

        # RbodyID: PIDRB's OWN part, not "any /RBODY built from that part's
        # material" — dyna2rad walks PIDRB -> MID -> conversion log
        # (convertdampings.cxx:274-293) and, when several parts share one
        # *MAT_RIGID, its loop lets the LAST /RBODY win, which is generally not
        # PIDRB's. k2rad keys rbody_info by part id, so the lookup is direct.
        # The emitted /RBODY id is the main node id (writer/rbody.py:624).
        rbody_id = 0
        if dr.pidrb <= 0:
            state.warn(
                f"{what}: PIDRB is 0, so there is no rigid body to measure "
                "velocity against — the card would degrade to ordinary "
                "absolute damping, which is not what *DAMPING_RELATIVE means.")
        else:
            info = rbody_info.get(dr.pidrb)
            if info is None:
                state.warn(
                    f"{what}: PIDRB={dr.pidrb} is not a rigid body in the "
                    "converted deck (no *MAT_RIGID part and no "
                    "*CONSTRAINED_NODAL_RIGID_BODY of that id), so there is no "
                    "/RBODY for the relative-velocity reference to point at.")
            else:
                rbody_id = info["ind_node"]

        pids = _damping_resolve_pids(state, dr.psid, True, f"{what} PSID") \
            if dr.psid else None
        scope_txt = (f"*SET_PART {dr.psid} -> parts {sorted(pids)}"
                     if pids else
                     f"*SET_PART {dr.psid} (unresolved)" if dr.psid else
                     "PSID=0 (no part scope given)")

        # FuncID — THE deliberate deviation from dyna2rad. convertdampings.cxx:
        # 305 routes the CURVE id through GetRadiossSetIdFromLsdSet(lcid,
        # "*SET_PART") with the SET entity type, a copy-paste of the PSID line
        # above it. When that id also numbers two or more *SET_* families the
        # part-set branch fires and a part-set id is written into a /FUNCT slot
        # — either pointing at the wrong curve (silent) or at no curve at all
        # (starter ERROR 3049). k2rad resolves LCID against state.curves, the
        # *DEFINE_CURVE -> /FUNCT table, and never against part_sets.
        func_id = 0
        alpha_x = dr.cdamp
        if dr.lcid:
            if dr.lcid in state.table_1d_ids:
                state.warn(
                    f"{what}: LCID={dr.lcid} is consumed by a material through "
                    "a TABLE slot, so k2rad emits it as /TABLE/1/"
                    f"{dr.lcid} rather than /FUNCT/{dr.lcid} — a /DAMP/VREL "
                    "FuncID pointing at it would dangle (starter ERROR 3049). "
                    "The time-varying damping reference is DROPPED.")
            elif dr.lcid not in state.curves:
                state.warn(
                    f"{what}: LCID={dr.lcid} has no *DEFINE_CURVE in this deck "
                    "— a dangling FuncID is starter ERROR 3049, so the "
                    "time-varying damping reference is DROPPED.")
            else:
                func_id = dr.lcid
                # LS-DYNA: "CDAMP will be ignored if LCID is non-zero" — the
                # curve REPLACES the constant. Radioss MULTIPLIES: damp_a =
                # fact*Alpha_x*4*pi*freq. Copying CDAMP into Alpha_x alongside
                # a FuncID would therefore double-count, so Alpha_* becomes 1.0.
                alpha_x = 1.0

        alpha2 = dr.dv2
        if dr.dv2 != 0.0 and rbody_id == 0:
            # DAMPR(22:24) is referenced in exactly one engine file,
            # damping_vref_rby.F90:141-143, inside `if (id_rby > 0)`. The
            # grnod path of damping.F:231 never touches it.
            state.warn(
                f"{what}: DV2={dr.dv2:.6G} (quadratic velocity term) is only "
                "applied by Radioss on the rigid-body path — with no usable "
                "RbodyID the Alpha2_* columns are read and then ignored.")
            alpha2 = 0.0

        state.warn(
            f"{what}: NOT EMITTED. The Radioss equivalent /DAMP/VREL is a "
            "radioss2024 card and k2rad writes /BEGIN 2022, where the starter "
            "falls back to the reduced radioss2023 layout and MISREADS it "
            "(measured on starter_win64: WARNING 100211 + 100213, Freq lost to "
            "0 so the engine switches to the alpha=Cdamp/dt_initial branch — "
            "about 1e12 off for a dt of 1e-6 — and the Freq value lands in "
            "Alpha_y). Emitting a card that reads as something else would be "
            "silently wrong, so the run is left UNDAMPED for this card. "
            "Resolved mapping, ready to paste into a deck whose /BEGIN says "
            f"2024 or later: Alpha_x=Alpha_y=Alpha_z={alpha_x:.6G}, "
            f"Alpha2_x={alpha2:.6G}, Freq={dr.freq:.6G}, RbodyID={rbody_id} "
            f"(from PIDRB={dr.pidrb}), FuncID={func_id} (from LCID={dr.lcid}, "
            f"resolved through the *DEFINE_CURVE -> /FUNCT table), grnod_id = a "
            f"node group covering {scope_txt}. Note Xscale must stay 1.0: the "
            "starter reads it into DAMPR(27) and no engine file ever reads "
            "that slot back, so abscissa scaling has to be baked into the "
            "curve's own X values.")
    return []


def _make_free_node_constraints(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """Implicit guard: fix nodes attached to no element and no rigid body.

    A free node carries no stiffness, so its DOFs are zero rows in the implicit
    tangent → a singular matrix → the MUMPS factorization fails (or floods the
    solver with null pivots). LS-DYNA tolerates such reference nodes — e.g.
    *DEFINE_COORDINATE_NODES nodes (we bake those into /SKEW/FIX coordinates so
    they end up unreferenced) and lone origin markers — but OpenRadioss implicit
    does not. Constrain them (they drive nothing, so fixing them is inert).

    Nodes of a MOVING skew (/SKEW/MOV, *DEFINE_COORDINATE_NODES flag=1) are left
    free so the frame can co-rotate. Explicit runs skip this entirely.
    """
    if not state.is_implicit or not state.nodes:
        return []
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2, e.n3))
    # /SPRING connector nodes carry spring stiffness; the synthesized ground
    # nodes are already fully /BCS-fixed by the connector section.
    #
    # *ELEMENT_PLOTEL is deliberately NOT in this list: its /PROP/TYPE4 is
    # K=0/C=0 by construction, and r1len3.F:81-105 leaves STI at zero unless XK
    # or XC is non-zero, so a node whose only attachment is a PLOTEL has exactly
    # the same (zero) stiffness as a genuinely free node. Counting the drawing
    # line as an attachment would switch the singularity guard off for that
    # node — the same reasoning that makes a synthesized beam-orientation node
    # subtractable a few lines below.
    for d in state.discrete_elems:
        elem_nodes.update((d.n1, d.n2))
    for w in state.constrained_spotwelds:
        elem_nodes.update((w.n1, w.n2))
    # A beam's THIRD node is a geometric reference only — the starter tags it
    # CHECK_USED, not CHECK_BEAM (hm_read_beam.F:179-181), and the engine takes
    # the local frame from the stored co-rotational triad, not from that node's
    # current position (pevec3.F reads E2 from RLOC). So a SYNTHESIZED
    # orientation node, which by construction no other element touches, carries
    # no stiffness at all: leaving it out of the constraint set would put six
    # zero rows per node into the implicit tangent. Fixing it is inert.
    elem_nodes -= state.beam_orient_nodes
    # *CONSTRAINED_JOINT nodes carry the /PROP/TYPE45 joint spring; fixing them
    # here would weld the joint solid. Registered by the _resolve_joints prepass
    # so this does not depend on the joint section having run yet.
    elem_nodes.update(state.joint_spring_nodes)
    elem_nodes.update(state.connector_ground_nodes)
    # /RBE3 nodes are kinematically coupled, so they are not zero rows — and a
    # /BCS 111 111 on an /RBE3 DEPENDENT node fights the constraint outright
    # (starter WARNING 3115: a dependent node that also has boundary conditions
    # silently switches the whole element to the penalty formulation). Filled by
    # _make_rbe3, which the section registry runs before this guard.
    elem_nodes.update(state.rbe3_nodes)
    keep_free: Set[int] = set()
    for cn in state.coord_nodes.values():
        if cn.flag == 1:
            keep_free.update((cn.n1, cn.n2, cn.n3))
    # Moving rigid-wall carrier nodes must stay free to translate the wall —
    # both the *RIGIDWALL_PLANAR_MOVING node (free-flying under contact) and
    # the *RIGIDWALL_GEOMETRIC_*_MOTION carrier nodes, which /IMPVEL|/IMPDISP
    # drives: a /BCS 111 111 on the same node would fight the imposed motion.
    keep_free.update(rw.node_id for rw in state.rigid_walls if rw.node_id > 0)
    keep_free.update(f.node_id for rw in state.rigid_walls_geometric
                     for f in rw.faces if f.node_id > 0)
    free = sorted(n for n in state.nodes
                  if n > 0 and n not in elem_nodes and n not in rigid_nodes
                  and n not in keep_free)
    if not free:
        return []
    state.warn(
        f"{len(free)} free node(s) attached to no element or rigid body were "
        "constrained with /BCS to keep the implicit tangent non-singular (e.g. "
        "*DEFINE_COORDINATE_NODES reference nodes baked into /SKEW/FIX, or origin "
        "markers). They drive nothing, so the constraint is inert."
    )
    bc_id = state.next_id()
    grnod_id = state.next_id()
    lines = [
        "#-  FREE-NODE CONSTRAINTS (implicit singularity guard):", HDR,
        f"/BCS/{bc_id}",
        "fix_free_reference_nodes",
        "#  Tra rot   skew_ID  grnod_ID",
        f"   111 111         0{_i(grnod_id)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, "free_reference_nodes", free)
    return lines
