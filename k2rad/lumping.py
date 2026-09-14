"""Lumped nodal masses, and the rigid-body momentum average built on them.

Two consumers, ONE rule:

* ``tools/modal_solve`` pairs :func:`nodal_masses_from_state` with the
  stiffness matrix the engine exported from the converted ``.rad``;
* ``writer/loads``'s ``--mass-weighted-inivel`` uses it, through
  :func:`rigid_body_momentum_velocity`, to form the momentum average Vol I R17
  p.28-129 Remark 3 describes for a rigid body an ``*INITIAL_VELOCITY`` card
  covers only partly.

The lumper used to live in ``tools/modal_solve``; a writer may not import from
``tools/``, so it moved here and ``tools/modal_solve`` imports it back. Nothing
about its arithmetic changed — see :func:`nodal_masses_from_state` for the
reporter argument, which is the only new parameter.

PURE STANDARD LIBRARY. No numpy, no scipy: this module is imported by the
writer, and ``k2rad`` must run without either. The 3x3 symmetric eigenproblem
the momentum average needs is solved with a cyclic Jacobi sweep
(:func:`_sym3_eigen`), which is exact enough for a 3x3 and has no dependency.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .state import ConversionState
# The two derivations this module must NOT re-implement: the writer's
# thickness-to-section-constants rule (the /PROP/BEAM the engine's stiffness
# matrix came from used it) and the converter's own RO <= 0 floor (the .rad it
# came from carries it). See _beam_section_area and _material_rho.
from .writer.beams import _constants_from_thicknesses
from .writer.materials import _ZERO_DENSITY_FLOOR

#: *SECTION_BEAM ELFORMs whose card 2 states THICKNESSES instead of section
#: constants (Vol I R17 p.41-11: cards 2a and 2e) -- the ones
#: ``_constants_from_thicknesses`` is written for.
_THICKNESS_BEAM_ELFORMS = frozenset({0, 1, 4, 5, 11})


def _tri_area(p1, p2, p3) -> float:
    ux, uy, uz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
    vx, vy, vz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def _tet_volume(p1, p2, p3, p4) -> float:
    a = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
    b = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
    c = (p4[0] - p1[0], p4[1] - p1[1], p4[2] - p1[2])
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return abs(det) / 6.0


# Hexa8 split into 6 tets fanned around the 0-6 body diagonal (exact for any
# hexa whose faces are planar, standard approximation otherwise). NOTE: an
# earlier corner-based table ended with tet (5,4,6,7) — the four TOP-FACE
# corners, which are coplanar (zero volume) — so every hexa's volume/mass came
# out 5/6 of the true value (+9.5% bias on hexa-model eigenfrequencies).
_HEXA_TETS = ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6),
              (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6))


def _material_rho(state: ConversionState,
                  zero_density_floor: bool = True,
                  report: Optional[Callable[[str], None]] = None
                  ) -> Dict[int, float]:
    """``mid -> rho`` for every law this module can weigh.

    ``zero_density_floor`` mirrors the CONVERTER's own ``RO <= 0`` floor
    (``writer/materials._ZERO_DENSITY_FLOOR``). This is not a fabrication and
    not a modelling choice: the stiffness matrix this module pairs the mass
    with was exported by the engine from the CONVERTED ``.rad``, in which
    k2rad has already written ``rho = 1e-24`` for exactly these materials.
    Building M at ``rho = 0`` while K comes from a model at ``rho = 1e-24``
    pairs a mass matrix with a stiffness matrix from a DIFFERENT model — and
    the zero rows are what makes the eigensolve fail (see ``solve_modes``).
    The substitution is printed the way the converter prints it, and
    ``--no-zero-density-floor`` turns it off.

    ``nvh/example-06-02/6.2.PSD_Beam_Example_LSTC.k`` is the measured carrier:
    its ``*MAT_ELASTIC`` card 1 parses as ``mid 1 | RO 0.0 | E 68947.5729 |
    PR 0.33``, so the density really is zero in the source.
    """
    rho: Dict[int, float] = {}
    floored: List[int] = []
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_rigid, state.mat_null, state.mat_power_law):
        for mid, m in mats.items():
            r = m.rho
            if r <= 0.0 and zero_density_floor:
                r = _ZERO_DENSITY_FLOOR
                floored.append(mid)
            rho[mid] = r
    if floored and report is not None:
        report(f"  NOTE: material(s) {sorted(floored)} state RO <= 0; the mass "
               f"matrix uses rho = {_ZERO_DENSITY_FLOOR:g}, the same floor "
               "k2rad wrote into the .rad the stiffness matrix was exported "
               "from (writer/materials._ZERO_DENSITY_FLOOR). "
               "--no-zero-density-floor keeps the stated zero.")
    return rho


def _beam_section_area(sec) -> float:
    """Cross-section AREA of a *SECTION_BEAM that states only thicknesses.

    ELFORM 0/1/4/5/11 carry no A/Iyy/Izz/Ixx at all — their card 2 is
    ``TS1 TS2 TT1 TT2 ...`` — so ``sec.area`` is 0 and this module weighed the
    beam at zero. The WRITER already derives the constants for exactly these
    formulations (``k2rad.writer.beams._constants_from_thicknesses``, CST 0/2
    rectangular TS1 x TT1, CST 1 tubular with TS1 the OUTER and TT1 the INNER
    diameter), so the derivation is IMPORTED rather than repeated here: the
    /PROP/BEAM the engine built its stiffness matrix from used those very
    numbers, and a second copy of the rule is how the two drift apart.

    MEASURED on ``nvh/example-06-02/6.2.PSD_Beam_Example_LSTC.k``: elform 1,
    area 0.0, ts1 6.35, tt1 50.8, cst 0 ->
    ``_constants_from_thicknesses(0, 6.35, 50.8) = (322.58, 69371.904,
    1083.936, 70455.840)``, and I = 50.8*6.35**3/12 = 1083.936 gives
    k = 3EI/L**3 = 109.4543 and f = 110.5541 Hz against the deck's own
    ``.eigout`` f1 = 110.4521 Hz (-0.09 %).
    """
    if getattr(sec, "elform", -1) not in _THICKNESS_BEAM_ELFORMS:
        return 0.0
    got = _constants_from_thicknesses(sec.cst, sec.ts1, sec.tt1)
    return float(got[0]) if got else 0.0


def nodal_masses_from_state(
        state: ConversionState, zero_density_floor: bool = True,
        report: Optional[Callable[[str], None]] = None
) -> Tuple[Dict[int, float], Dict[int, float]]:
    """Lumped nodal masses and rotary inertias [deck units] from the parsed deck.

    Returns ``(mass, inertia)``: translational mass and rotational inertia per
    node.  Element mass is split evenly over the element's nodes (row-sum
    lumping for the linear elements used here); shell nodes also receive the
    Radioss rotary-inertia lumping IN = (m_elem/n_nodes)·(A_elem + t²)/12.
    Both reproduce the OpenRadioss starter's MS/IN nodal arrays to machine
    precision (verified on the W14 bogie). *ELEMENT_MASS /
    *ELEMENT_MASS_PART additions are then applied to the masses.

    *report* takes the one NOTE this pass can print (a material stating
    ``RO <= 0``, floored the way the converter floors it). ``None`` — the
    default, and what the WRITER passes — prints nothing: a conversion's
    diagnostics go through ``state.warn``, not stdout. ``tools/modal_solve``
    passes ``print`` so its console output is exactly what it was before this
    function moved into the package.

    TWO CONSUMERS now: ``tools/modal_solve`` builds the modal mass matrix from
    it, and ``writer/loads``'s ``--mass-weighted-inivel`` builds the momentum
    average of Vol I R17 p.28-129 Remark 3 from it. It lives here rather than
    in ``tools/`` because the package must never import from ``tools/``, and
    a second copy of the rule is how the two drift apart.
    """
    rho_by_mid = _material_rho(state, zero_density_floor, report)
    nodes = state.nodes
    mass: Dict[int, float] = {}
    inertia: Dict[int, float] = {}

    def add(nids: Sequence[int], m_elem: float) -> None:
        share = m_elem / len(nids)
        for n in nids:
            mass[n] = mass.get(n, 0.0) + share

    part_mass: Dict[int, float] = {}

    def add_part(pid: int, m_elem: float) -> None:
        part_mass[pid] = part_mass.get(pid, 0.0) + m_elem

    for e in state.shell_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        sec = state.sec_shells.get(part.secid)
        rho = rho_by_mid.get(part.mid, 0.0)
        if sec is None or rho == 0.0:
            continue
        try:
            p = [ (nodes[n].x, nodes[n].y, nodes[n].z) for n in e.nodes ]
        except KeyError:
            continue
        area = _tri_area(p[0], p[1], p[2])
        if len(p) == 4:
            area += _tri_area(p[0], p[2], p[3])
        m_elem = area * sec.t1 * rho
        add(e.nodes, m_elem)
        add_part(e.pid, m_elem)
        in_share = (m_elem / len(e.nodes)) * (area + sec.t1 ** 2) / 12.0
        for n in e.nodes:
            inertia[n] = inertia.get(n, 0.0) + in_share

    for e in state.solid_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        rho = rho_by_mid.get(part.mid, 0.0)
        if rho == 0.0:
            continue
        try:
            p = [ (nodes[n].x, nodes[n].y, nodes[n].z) for n in e.nodes ]
        except KeyError:
            continue
        if len(p) >= 8:                       # hexa8 (or degenerate penta/hexa)
            vol = sum(_tet_volume(p[a], p[b], p[c], p[d])
                      for a, b, c, d in _HEXA_TETS)
        else:                                 # tet4 / tet10 (corner volume)
            vol = _tet_volume(p[0], p[1], p[2], p[3])
        m_elem = vol * rho
        add(e.nodes, m_elem)
        add_part(e.pid, m_elem)

    for e in state.beam_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        sec = state.sec_beams.get(part.secid)
        rho = rho_by_mid.get(part.mid, 0.0)
        if sec is None or rho == 0.0:
            continue
        area = sec.area or _beam_section_area(sec)
        if area <= 0.0:
            continue
        try:
            p1 = nodes[e.n1]; p2 = nodes[e.n2]
        except KeyError:
            continue
        length = math.dist((p1.x, p1.y, p1.z), (p2.x, p2.y, p2.z))
        m_elem = length * area * rho
        add((e.n1, e.n2), m_elem)   # rho*A*L/2 per end node
        add_part(e.pid, m_elem)

    # *ELEMENT_MASS point masses (per node).
    for nid, m in state.added_node_masses.items():
        mass[nid] = mass.get(nid, 0.0) + m

    # *ELEMENT_MASS_PART: ADDMASS spread evenly over the part's nodes;
    # FINMASS = target total -> spread (FINMASS - current part mass).
    if state.element_mass_parts:
        part_nodes: Dict[int, set] = {}
        for e in state.shell_elems:
            part_nodes.setdefault(e.pid, set()).update(e.nodes)
        for e in state.solid_elems:
            part_nodes.setdefault(e.pid, set()).update(e.nodes)
        for e in state.beam_elems:
            part_nodes.setdefault(e.pid, set()).update((e.n1, e.n2))
        for pid, (addmass, finmass) in state.element_mass_parts.items():
            nids = sorted(part_nodes.get(pid, ()))
            if not nids:
                continue
            extra = (finmass - part_mass.get(pid, 0.0)) if finmass > 0 else addmass
            if extra:
                share = extra / len(nids)
                for n in nids:
                    mass[n] = mass.get(n, 0.0) + share
    return mass, inertia

# ─────────────────────────────────────────────────────────────────────────────
# The rigid-body momentum average (Vol I R17 p.28-129 Remark 3)
# ─────────────────────────────────────────────────────────────────────────────

#: A body whose total lumped mass is below this fraction of the MODEL's own
#: lumped mass carries no momentum worth re-pointing, and dividing by it would
#: manufacture a velocity out of round-off. RELATIVE rather than absolute
#: because the deck's unit system is the user's: ``inirby.F:200-201`` refuses
#: ``MASRB <= 1e-30`` (ANCMSG 679) in the SOLVER's units, and a real 37-node
#: CNRB on this corpus lumps to 4.55e-24 in a model whose own mass is ~1e-4 —
#: an absolute ``M <= 0`` test misses it, and an absolute 1e-30 test would
#: accept it.
_ZERO_BODY_MASS_RATIO = 1.0e-12

#: The scale-free rank test on the inertia tensor: an eigenvalue at or below
#: ``_INERTIA_RANK_TOL * M * R2max`` (total mass times the largest squared
#: distance from the centre of mass) is a direction the body has no extent in
#: — a single node, two coincident nodes, or a COLLINEAR body about its own
#: axis. Dividing by it is what turns a 1e-12 determinant into a 500x wrong
#: angular velocity.
_INERTIA_RANK_TOL = 1.0e-10

_Vec = Tuple[float, float, float]


def _sym3_eigen(a: Sequence[Sequence[float]]
                ) -> Tuple[List[float], List[_Vec]]:
    """Eigenvalues and ORTHONORMAL eigenvectors of a symmetric 3x3 matrix.

    Cyclic Jacobi: rotate away the largest off-diagonal entry until the
    off-diagonal norm stops moving. For a 3x3 this converges in a handful of
    sweeps and needs no library. Returns ``(values, vectors)`` with
    ``vectors[k]`` the unit eigenvector of ``values[k]``.
    """
    A = [[float(a[i][j]) for j in range(3)] for i in range(3)]
    V = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    scale = max(abs(A[i][j]) for i in range(3) for j in range(3)) or 1.0
    for _sweep in range(60):
        off = abs(A[0][1]) + abs(A[0][2]) + abs(A[1][2])
        if off <= 1e-15 * scale:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = A[p][q]
            if abs(apq) <= 1e-18 * scale:
                continue
            theta = (A[q][q] - A[p][p]) / (2.0 * apq)
            sign = 1.0 if theta >= 0.0 else -1.0
            t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            for k in range(3):                       # columns
                akp, akq = A[k][p], A[k][q]
                A[k][p] = c * akp - s * akq
                A[k][q] = s * akp + c * akq
            for k in range(3):                       # rows
                apk, aqk = A[p][k], A[q][k]
                A[p][k] = c * apk - s * aqk
                A[q][k] = s * apk + c * aqk
            for k in range(3):                       # accumulate the rotation
                vkp, vkq = V[k][p], V[k][q]
                V[k][p] = c * vkp - s * vkq
                V[k][q] = s * vkp + c * vkq
    values = [A[0][0], A[1][1], A[2][2]]
    vectors = [(V[0][k], V[1][k], V[2][k]) for k in range(3)]
    return values, vectors


def _pinv_times(inertia: Sequence[Sequence[float]], rhs: _Vec,
                tol: float) -> _Vec:
    """``I^+ . rhs`` — the Moore-Penrose pseudo-inverse applied to a vector.

    Directions whose eigenvalue is at or below *tol* are DROPPED instead of
    divided by. On a collinear body that discards exactly nothing: the angular
    momentum ``L = sum d_i x m_i v_i`` of a body whose mass sits on one line is
    perpendicular to that line by construction (every ``d_i`` is along it), so
    its component on the null direction is 0 and the pseudo-inverse is the
    EXACT answer, not an approximation of one.
    """
    values, vectors = _sym3_eigen(inertia)
    out = [0.0, 0.0, 0.0]
    for lam, vec in zip(values, vectors):
        if lam <= tol:
            continue
        coef = (vec[0] * rhs[0] + vec[1] * rhs[1] + vec[2] * rhs[2]) / lam
        out[0] += coef * vec[0]
        out[1] += coef * vec[1]
        out[2] += coef * vec[2]
    return out[0], out[1], out[2]


def rigid_body_momentum_velocity(
        coords: Sequence[_Vec], masses: Sequence[float],
        velocities: Sequence[Optional[_Vec]],
        model_mass: float = 0.0,
) -> Tuple[Optional[_Vec], Optional[_Vec], Optional[_Vec], str]:
    """The rigid motion LS-DYNA gives a body from PRESCRIBED nodal velocities.

    ``(v_cm, omega, centre of mass, refusal)`` — on a refusal the first three
    are ``None`` and the fourth says why, in words a warning can print.

    Vol I R17 p.28-129 ``*INITIAL_VELOCITY_GENERATION`` Remark 3 (and
    ``*INITIAL_VELOCITY`` Remark 4, p.28-125): *"During initialization, the
    translational and rotational rigid body momentums are computed based on the
    prescribed nodal velocities. From this rigid body motion, the velocities of
    the nodal points are computed and reset to the new values."* So:

        M      = sum m_i                      over EVERY node of the body
        x_cm   = sum m_i x_i / M
        v_cm   = sum m_i v_i / M              over the PRESCRIBED nodes only
        L      = sum d_i x m_i v_i            d_i = x_i - x_cm, prescribed only
        omega  = I_cm^+ L                     I_cm over EVERY node

    A node the card does NOT name contributes its MASS to M and to ``I_cm`` and
    ZERO momentum — that is what makes the average smaller than the card's own
    velocity, and it is what reproduces LS-DYNA's number: on
    ``intro-by-j.-day/joint/joint-ii/translat.k``, 2 of 4 equal corner masses
    carrying ``v`` give ``v_cm = v/2`` and ``1/2 M (v/2)^2 = 97.0`` against a
    glstat cycle-0 K-ENERGY of 189.962, whose other 93.0 is the spin this
    ``omega`` supplies.

    *velocities* is per node, ``None`` for a node the card does not name.
    *model_mass* is the whole model's lumped mass, used only for the RELATIVE
    zero-mass refusal.

    THE GUARD. ``I_cm`` is singular for a single node, for coincident nodes and
    for a COLLINEAR body about its own axis, and nearly singular for a thin
    one: the real 2-node CNRB of the Yaris suspension deck (nodes 9.784467 mm
    apart) has ``det`` 8.75e-12 and condition number 1.34e16, where a
    ``solve()`` returns a 500x wrong angular velocity with no diagnostic at
    all. So this never inverts: it eigen-decomposes, drops every direction at
    or below ``_INERTIA_RANK_TOL * M * R2max`` (scale-free — the tolerance
    scales with the body's own mass and size, so it means the same thing in
    ``t/mm`` and in ``kg/m``), and applies the pseudo-inverse. On a collinear
    body the dropped component of ``L`` is exactly 0, so the answer is exact
    and its axial spin is exactly zero — which is the physically right answer:
    a line of point masses has no moment of inertia about itself.
    """
    n = len(coords)
    if not (n and len(masses) == n and len(velocities) == n):
        return None, None, None, (
            "the body's node list, masses and velocities do not line up")
    total = math.fsum(masses)
    floor = max(1e-30, _ZERO_BODY_MASS_RATIO * max(model_mass, 0.0))
    if total <= floor:
        return None, None, None, (
            f"its lumped mass is {total:g}, at or below the {floor:g} floor "
            "(1e-12 of the model's own lumped mass, or the solver's own "
            "MASRB <= 1e-30, whichever is larger) - k2rad will not divide a "
            "momentum by it. inirby.F:200-201 refuses such a body with "
            "ANCMSG 679")
    cx = math.fsum(m * p[0] for m, p in zip(masses, coords)) / total
    cy = math.fsum(m * p[1] for m, p in zip(masses, coords)) / total
    cz = math.fsum(m * p[2] for m, p in zip(masses, coords)) / total
    cog = (cx, cy, cz)

    px = math.fsum(m * v[0] for m, v in zip(masses, velocities) if v)
    py = math.fsum(m * v[1] for m, v in zip(masses, velocities) if v)
    pz = math.fsum(m * v[2] for m, v in zip(masses, velocities) if v)
    v_cm = (px / total, py / total, pz / total)

    lx = ly = lz = 0.0
    ixx = iyy = izz = ixy = ixz = iyz = 0.0
    r2max = 0.0
    for m, p, v in zip(masses, coords, velocities):
        dx, dy, dz = p[0] - cx, p[1] - cy, p[2] - cz
        r2 = dx * dx + dy * dy + dz * dz
        if m > 0.0:
            r2max = max(r2max, r2)
        ixx += m * (dy * dy + dz * dz)
        iyy += m * (dx * dx + dz * dz)
        izz += m * (dx * dx + dy * dy)
        ixy -= m * dx * dy
        ixz -= m * dx * dz
        iyz -= m * dy * dz
        if v:
            lx += m * (dy * v[2] - dz * v[1])
            ly += m * (dz * v[0] - dx * v[2])
            lz += m * (dx * v[1] - dy * v[0])
    inertia = ((ixx, ixy, ixz), (ixy, iyy, iyz), (ixz, iyz, izz))
    tol = _INERTIA_RANK_TOL * total * r2max
    omega = _pinv_times(inertia, (lx, ly, lz), tol)
    return v_cm, omega, cog, ""
