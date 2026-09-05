"""Shared low-level helpers: field formatting, group/surface emitters, small vector math."""

from __future__ import annotations

import math
from typing import List, Optional, Set
from ..state import ConversionState

__all__ = [
    "HDR",
    "_nid_centroid",
    "_node_cloud_normal",
    "_orthonormal_pair",
    "_preload_sect_scale",
    "_f",
    "_i",
    "_dof_string",
    "_vsub",
    "_vcross",
    "_vnorm",
    "_elform_to_ishell",
    "_elform_to_isolid",
    "_emit_grnod_node",
    "_emit_grnod_grnod",
    "_emit_grshel",
    "_emit_grsh3n",
    "_emit_id_group",
    "_emit_surf_part",
    "_emit_surf_part_all",
    "_emit_grpart_part",
    "_emit_surf_grshel",
    "_emit_surf_grsh3n",
    "_emit_surf_surf",
    "_make_master_surface",
    "_ordered_unique_nodes",
    "_split_shell_eids_by_topology",
    "_fmt_eid_list",
    "_discrete_beam_mids",
    "_discrete_beam_claim_conflicts",
    "_discrete_beam_pids",
    "_discrete_part_ids",
    "_muscle_beam_pids",
    "_muscle_discrete_pids",
    "_muscle_part_ids",
    "_spotweld_beam_pids",
    "_truss_pids",
    "_truss_secids",
    "_emit_surf_seg",
    "_emit_line_seg",
    "_emit_line_surf",
    "_part_node_sets",
    "_ref_flag_materials",
    "_seatbelt_mat_law",
    "_seatbelt_part_ids",
    "_seatbelt_2d_part_ids",
    "_ams_is_emitted",
]


HDR = "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|"


def _ams_is_emitted(state: ConversionState) -> bool:
    """Will this deck actually carry ``/DT/AMS`` (and the starter ``/AMS``)?

    ``--ams`` is a REQUEST, not an outcome: ``_make_engine_timestep`` writes
    ``/DT/AMS`` only for a mass-scaled explicit deck (``*CONTROL_TIMESTEP``
    present with ``DT2MS < 0``), and ``_make_ams`` gates the starter card on
    the identical predicate. Anything that asks "is AMS on this deck?" — the
    ``/DT/THERM`` refusal above all, since ``freform.F:1327`` refuses the pair
    on ``IDTMINS /= 0`` and IDTMINS comes from the ``/DT/AMS`` card — must ask
    THIS rather than ``state.options.ams``. MEASURED before the fix: a SOLN=1
    deck with no ``*CONTROL_TIMESTEP``, converted with ``--ams``, carried
    NEITHER ``/DT/AMS`` NOR ``/AMS`` and still lost its ``/DT/THERM``, under a
    message saying "/DT/AMS is kept" — the #130 class, a statement of what the
    deck will emit that does not mirror the emitter's own drop conditions.

    Non-mutating on purpose: it is called from a screen and from the emitter.
    """
    ts = state.ctrl_timestep
    return bool(state.options.ams and ts is not None and ts.dt2ms < 0.0
                and not state.is_implicit and not state.is_modal)


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v: float, w: int = 20) -> str:
    """Right-aligned float field of width *w*."""
    if v == 0.0:
        s = "0"
    elif abs(v) >= 1e15 or (0.0 < abs(v) < 1e-4):
        s = f"{v:.6E}"
    else:
        s = f"{v:.10G}"
    return s.rjust(w)


def _i(v: int, w: int = 10) -> str:
    return str(v).rjust(w)


def _dof_string(dx: int, dy: int, dz: int) -> str:
    return f"{dx}{dy}{dz}"


# ── Small 3-vector helpers (for /SKEW/FIX axis construction) ──────────────────

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vnorm(a):
    import math
    m = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if m == 0.0:
        return None
    return (a[0] / m, a[1] / m, a[2] / m)


# /PROP/SHELL Ishell values k2rad emits.
ISHELL_QBAT = 12    # fully integrated (4 in-plane points), Batoz
ISHELL_QEPH = 24    # reduced integration, PHYSICALLY stabilised (Q4 + EPH)

#: name -> Ishell, for the user-facing ``shell_formulation`` option.
SHELL_FORMULATIONS = {"qbat": ISHELL_QBAT, "qeph": ISHELL_QEPH}

# LS-DYNA shell ELFORMs k2rad maps to QEPH regardless of the option: already
# reduced-integration / co-rotational forms whose Radioss counterpart is
# unambiguous. Everything else — ELFORM=2 (Belytschko-Tsay) above all, the
# most common shell formulation in LS-DYNA decks — has no exact counterpart
# and falls through to the user's choice.
_ELFORM_ALWAYS_QEPH = {-16, 9, 20, 21, 26}


def _elform_to_ishell(elform: int, is_implicit: bool,
                      default_ishell: int = ISHELL_QBAT) -> int:
    """LS-DYNA ``*SECTION_SHELL`` ELFORM -> Radioss ``/PROP/SHELL`` Ishell.

    ``default_ishell`` is what an ELFORM with no exact Radioss counterpart
    maps to. It is a USER CHOICE (``convert(shell_formulation=...)``) rather
    than a constant, because the two candidates are not interchangeable and
    neither is universally right:

    * **12, QBAT** — the default, and what every existing conversion has
      produced. FULLY integrated, 4 in-plane points. ELFORM=2 is
      UNDER-integrated (1 point), so this changes the element's integration
      class. With ``/FAIL/JOHNSON Ifail_sh=2`` that costs erosion:
      ``fail_setoff_npg_c.F`` then wants 4 Gauss x 2 through-thickness = 8
      failure events to delete an element, against the 2 the original deck
      implies — measured at up to ~1.7x under-erosion on a 38k-shell blast
      model.
    * **24, QEPH** — reduced integration, PHYSICALLY stabilised. Much closer
      to Belytschko-Tsay in integration class and cost, and it drops the
      ``dn=1.0e-3`` numerical damping the starter injects for Ishell=12
      (``hm_read_prop01.F:279``).

    QEPH is NOT simply made the default because it changes results on every
    existing shell deck — 4 ``/PROP/SHELL`` props across 3 of this repo's own
    golden fixtures flip 12 -> 24. That is a physics change, so the user asks
    for it explicitly.

    Under-integrated ``Ishell=1..4`` is deliberately not offered. It would
    activate the Hm/Hf/Hr hourglass path that this repo's own inert-hourglass
    warning documents as unused, and ``inistate.py`` sets ``npg = 4 if ishell
    in (12, 24) else 1``, so 1..4 would silently change ``/INISHE`` and
    corrupt ``*INITIAL_STRESS_SHELL`` transfer. Both 12 and 24 leave that
    untouched.

    Implicit always returns 24 regardless of the option — reduced integration
    with physical stabilisation is what Radioss recommends there, and that
    predates this option.
    """
    if is_implicit:
        return ISHELL_QEPH
    return ISHELL_QEPH if elform in _ELFORM_ALWAYS_QEPH else default_ishell


def _elform_to_isolid(elform: int) -> int:
    # Radioss /PROP/SOLID Isolid (cfg prop_p14_solid):
    #   17 = 8-node full (2x2x2) integration — k2rad's structural-hex default;
    #        no hourglass modes, chosen for implicit accuracy.
    #   14 = tet4 (Kessler).  24 = HEPH (reduced integration, *physically*
    #        stabilized). NB: Isolid=2 is the Hallquist 1-IP viscous-hourglass
    #        hex (under-integrated, hourglass-prone) — it is NOT HEPH and is
    #        intentionally never emitted here.
    # LS-DYNA ELFORM 2 is the FULLY-INTEGRATED selective-reduced (S/R) hex, so
    # it maps to the full-integration Isolid 17 — matching its fully-integrated
    # semantics, keeping every hex ELFORM {0,1,2,16,-1} → 17, and staying
    # consistent with the *HOURGLASS gate (ELFORM 2 = no hourglass modes, so it
    # is excluded from IHQ→Isolid remapping in mesh.py). The previous 2→2
    # mapping put a fully-integrated LS-DYNA element onto an under-integrated
    # Radioss element: a single-hex uniaxial-pull validation hourglassed to a
    # ~99.9% energy-error blow-up (IE 0.14→178 while external work stayed ~2.5),
    # spuriously spiking sigma1 and deleting the element ~8x early; ELFORM 1→17
    # ran clean.
    return {0: 17, 1: 17, 2: 17, 10: 14, 13: 14, 16: 17, -1: 17}.get(elform, 17)


# ─────────────────────────────────────────────────────────────────────────────
# Group emitters (shared by Starter sections)
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grnod_node(grnod_id: int, title: str, nids: List[int]) -> List[str]:
    lines = [f"/GRNOD/NODE/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for n in nids:
        row.append(str(n).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_grnod_grnod(grnod_id: int, title: str, gids: List[int]) -> List[str]:
    """/GRNOD/GRNOD — the de-duplicating UNION of other node groups.

    A group-of-groups: ``hm_lecgrn.F:232-236`` classifies ``GRNOD`` with
    ``GRPGRP=2`` and leaves ``SORTED=0``, and ``hm_grogronod.F:179-219`` resolves
    the members by group id alone (no restriction on the member's own sub-type),
    tags each node once in a scratch buffer, then materialises the survivors in
    node order — so a /GRNOD/PART and a /GRNOD/NODE can be unioned in one card
    and a node listed by both appears once. (``GRNODNS`` sets ``SORTED=1`` and
    concatenates *with* duplicates — not what a union wants.)

    A member id that does not exist is only ``MSGID=174``, a starter WARNING, so
    callers must make sure every id is real.
    """
    lines = [f"/GRNOD/GRNOD/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for g in gids:
        row.append(str(g).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_grshel(grshel_id: int, title: str, eids: List[int]) -> List[str]:
    lines = [f"/GRSHEL/SHEL/{grshel_id}", title or f"GRSHEL_{grshel_id}"]
    row: List[str] = []
    for e in eids:
        row.append(str(e).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_grsh3n(grsh3n_id: int, title: str, eids: List[int]) -> List[str]:
    """3-node shell group, the /SH3N counterpart of /GRSHEL/SHEL.

    A /GRSHEL/SHEL group may only list 4-node /SHELL ids; a /SH3N id put in one
    is not resolved (the group silently comes up short), which is why callers
    must split a mixed shell id list with _split_shell_eids_by_topology first.
    """
    lines = [f"/GRSH3N/SH3N/{grsh3n_id}", title or f"GRSH3N_{grsh3n_id}"]
    row: List[str] = []
    for e in eids:
        row.append(str(e).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_id_group(keyword: str, group_id: int, title: str, ids: List[int]) -> List[str]:
    """Generic id-list group block (/GRBRIC/BRIC, /GRBEAM/BEAM, ...): header,
    title, then ids 10 per row."""
    lines = [f"/{keyword}/{group_id}", title or f"{keyword.split('/')[0]}_{group_id}"]
    row: List[str] = []
    for v in ids:
        row.append(_i(v))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_part(surf_id: int, title: str, pids: List[int]) -> List[str]:
    lines = [f"/SURF/PART/EXT/{surf_id}", title or f"SURF_PART_{surf_id}"]
    row: List[str] = []
    for p in pids:
        row.append(_i(p))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_part_all(surf_id: int, title: str, pids: List[int]) -> List[str]:
    """/SURF/PART/ALL — every face of every solid, INTERIOR faces included.

    The difference from /SURF/PART/EXT is one flag deep in the starter:
    ``hm_read_surf.F:636-641`` sets ``IGRSURF(IGS)%EXT_ALL`` to ``EXT_SURF=1``
    for ``EXT`` and ``ALL_SURF=2`` for ``ALL``, and ``ssurftag.F:122``
    (``IF(IEXT==1) THEN … C External surface only.``) then masks every face
    shared with another tagged solid. With ``ALL`` that masking is skipped, so a
    face between two bricks survives as a segment.

    Only /INTER/TYPE25 can use those interior segments safely: the starter marks
    them dormant by negating the stiffness (``i25sti3.F:950-951``) and the
    engine wakes one up only when a neighbour element dies
    (``check_surface_state.F:174-203``). On any other interface type every
    interior face would be ACTIVE at t=0 — instant self-contact of the solid
    against its own interior. Callers must gate on TYPE25.

    Same card body as /SURF/PART/EXT (``radioss110/SETS/surf_all.cfg``:
    ``HEADER("/SURF/%-s/ALL/%d")`` + title + a free 10-wide id list).
    """
    lines = [f"/SURF/PART/ALL/{surf_id}", title or f"SURF_PART_ALL_{surf_id}"]
    row: List[str] = []
    for p in pids:
        row.append(_i(p))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_grpart_part(grpart_id: int, title: str, pids: List[int]) -> List[str]:
    """/GRPART/PART — a part group, the target of /FRICTION's grpart_ID1/2.

    ``hm_read_grpart.F:212`` accepts ``PART`` (alongside SUBSET/MAT/PROP) as the
    second key, and ``radioss2020/FRICTION/friction.cfg:43-44`` types
    ``grpart_ID1/2`` as ``SUBTYPES = (/SETS/GRPART)``. Body is the usual free
    10-wide id list.
    """
    return _emit_id_group("GRPART/PART", grpart_id, title or f"GRPART_{grpart_id}",
                          pids)


def _emit_surf_grshel(surf_id: int, title: str, grshel_id: int) -> List[str]:
    return [
        f"/SURF/GRSHEL/{surf_id}",
        title or f"SURF_GRSHEL_{surf_id}",
        f"{_i(grshel_id)}",
        HDR,
    ]


def _emit_surf_grsh3n(surf_id: int, title: str, grsh3n_id: int) -> List[str]:
    """The /GRSH3N counterpart of /SURF/GRSHEL.

    The starter reads the two identically — hm_read_surf.F:893 handles
    ``KEY(1:6)=='GRSHEL'`` over IGRSH4N/IXC and :925 ``KEY(1:6)=='GRSH3N'``
    over IGRSH3N/IXTG, same body (one group id), same segment builder.
    """
    return [
        f"/SURF/GRSH3N/{surf_id}",
        title or f"SURF_GRSH3N_{surf_id}",
        f"{_i(grsh3n_id)}",
        HDR,
    ]


def _emit_surf_surf(surf_id: int, title: str, sub_surf_ids: List[int]) -> List[str]:
    lines = [f"/SURF/SURF/{surf_id}", title or f"SURF_SURF_{surf_id}"]
    row: List[str] = []
    for s in sub_surf_ids:
        row.append(_i(s))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _make_master_surface(state: ConversionState, surf_id: int, title: str,
                         pids: List[int], out_lines: List[str],
                         solid_all: bool = False) -> bool:
    """Emit a master surface (for /INTER) from a list of PIDs.

    ``solid_all`` switches the SOLID sub-surface from /SURF/PART/EXT (external
    skin) to /SURF/PART/ALL (interior faces too) — see _emit_surf_part_all.
    Default False, so every existing caller is byte-for-byte unchanged; only
    the /INTER/TYPE25 eroding path sets it.

    The part's shells are split by topology before they are grouped. A
    /GRSHEL/SHEL group resolves only 4-node /SHELL ids, and since d1ade12 a
    shell with 3 distinct corners — written either as 3 ids or as a collapsed
    quad ``n1 n2 n3 n3`` — is emitted as /SH3N. Putting one in the quad group
    is not a soft loss: the starter answers ERROR 70 "ELEMENT ID=n DOES NOT
    EXIST" and refuses the deck. (Measured on W16_spotweld_E1, whose welded
    sheets carry the collapsed quad 529 = 695/665/664/664.) The triangles get
    their own /GRSH3N/SH3N + /SURF/GRSH3N, which the starter reads through the
    symmetric branch at hm_read_surf.F:925.

    One element kind → the surface IS that group; two or three kinds → one
    sub-surface each under a /SURF/SURF. The single-kind and quad+solid id
    allocation orders are unchanged, so a master surface with no triangles in
    it is emitted byte-for-byte as before.
    """
    shell_eids: List[int] = []
    solid_pids: List[int] = []
    tshell_pids = {e.pid for e in state.tshell_elems}
    sph_pids = {c.pid for c in state.sph_elems}
    sph_only: List[int] = []
    for pid in sorted(pids):
        eids_in_pid = [e.eid for e in state.shell_elems if e.pid == pid]
        # A thick shell is a /BRICK in the emitted deck, so its part takes the
        # same /SURF/PART[/EXT] a brick part does. Without this a contact naming
        # a thick-shell part builds NO surface and the whole /INTER is dropped —
        # loudly (``_drop_interface``), but dropped. ``tshell_elems`` is empty
        # on every deck without *ELEMENT_TSHELL, so no other surface moves.
        has_solids = (pid in tshell_pids
                      or any(e.pid == pid for e in state.solid_elems))
        if eids_in_pid:
            shell_eids.extend(eids_in_pid)
        elif has_solids:
            solid_pids.append(pid)
        elif pid in sph_pids:
            # An SPH part contributes NOTHING to a main surface — a particle
            # has no face — and that has to be said rather than left to the
            # `kinds == 0` branch below. When the scope holds other parts too
            # the interface converts LOOKING HEALTHY while the SPH side is
            # simply absent, which is a silence `_drop_interface` can never
            # break because the interface is not dropped at all.
            sph_only.append(pid)
    if sph_only:
        state.warn(
            f"Contact surface '{title}': part(s) {sph_only} hold SPH particles "
            "only, and a particle has NO FACE — so they contribute NOTHING to "
            "the MAIN (segment) side of this interface"
            + (". The interface is built from the other parts in its scope and "
               "looks healthy, but the particles are not on this side of it."
               if (shell_eids or solid_pids) else
               " and the whole interface is dropped below.")
            + " In Radioss an SPH<->structure contact puts the PARTICLES on the "
            "SECONDARY side (a /GRNOD of their nodes, which k2rad does build) "
            "and a structural surface on the main side — so swap the two sides "
            "of the *CONTACT if the particles were meant to be contacted.")

    shell_eids.sort()
    quad_eids, tri_eids = _split_shell_eids_by_topology(state, shell_eids)
    _emit_solid_surf = _emit_surf_part_all if solid_all else _emit_surf_part

    kinds = sum(1 for group in (quad_eids, tri_eids, solid_pids) if group)
    if kinds == 0:
        return False
    if kinds == 1:
        if quad_eids:
            grshel_id = state.next_elem_group_id()
            out_lines += _emit_grshel(grshel_id, f"{title}_grshel", quad_eids)
            out_lines += _emit_surf_grshel(surf_id, title, grshel_id)
        elif tri_eids:
            grsh3n_id = state.next_elem_group_id()
            out_lines += _emit_grsh3n(grsh3n_id, f"{title}_grsh3n", tri_eids)
            out_lines += _emit_surf_grsh3n(surf_id, title, grsh3n_id)
        else:
            out_lines += _emit_solid_surf(surf_id, title, solid_pids)
        return True

    # ``sub_shell``/``sub_tri``/``sub_solid`` are /SURF ids, NOT element-group
    # ids, so they stay on the bare ``next_id()``: /SURF is its own starter
    # namespace (``hm_read_surf.F:428`` runs its own UDOUBLE over
    # 'SURFACE DEFINITION'), and a /SURF may legally share a number with any
    # /GR* group — MEASURED, a deck with /GRBRIC/BRIC/5000 beside
    # /SURF/PART/EXT/5000 is accepted at 0 ERROR. Routing them through
    # ``next_elem_group_id()`` would dodge the element-SET registries for no
    # reason and shift ids on decks that have such a set.
    sub_ids: List[int] = []
    if quad_eids:
        grshel_id = state.next_elem_group_id()
        sub_shell = state.next_id()
        out_lines += _emit_grshel(grshel_id, f"{title}_grshel", quad_eids)
        out_lines += _emit_surf_grshel(sub_shell, f"{title}_shells", grshel_id)
        sub_ids.append(sub_shell)
    if tri_eids:
        grsh3n_id = state.next_elem_group_id()
        sub_tri = state.next_id()
        out_lines += _emit_grsh3n(grsh3n_id, f"{title}_grsh3n", tri_eids)
        out_lines += _emit_surf_grsh3n(sub_tri, f"{title}_tris", grsh3n_id)
        sub_ids.append(sub_tri)
    if solid_pids:
        sub_solid = state.next_id()
        out_lines += _emit_solid_surf(sub_solid, f"{title}_solids", solid_pids)
        sub_ids.append(sub_solid)
    out_lines += _emit_surf_surf(surf_id, title, sub_ids)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Starter: parts + elements
# ─────────────────────────────────────────────────────────────────────────────

def _ordered_unique_nodes(nodes: List[int]) -> List[int]:
    """Distinct positive node IDs, preserving first-seen order.

    LS-DYNA stores a 4-node tet either as 4 IDs or as an 8-slot hex with
    nodes 5-8 collapsed onto node 4 (e.g. n1 n2 n3 n4 n4 n4 n4 n4). Either
    way this returns the 4 distinct corners, so callers can detect tets.
    """
    seen: Set[int] = set()
    out: List[int] = []
    for n in nodes:
        if n > 0 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _split_shell_eids_by_topology(state: ConversionState,
                                  eids: List[int]) -> tuple:
    """Split shell element IDs into (quad_eids, tri_eids).

    Since d1ade12 a *ELEMENT_SHELL with only 3 distinct corners — written
    either as 3 IDs or as a collapsed quad (n1 n2 n3 n3) — is emitted as
    /SH3N, not as a 4-node /SHELL. Every writer that puts shell IDs into a
    group therefore has to make the same split, because /GRSHEL/SHEL and
    /TH/SHEL resolve only 4-node /SHELL IDs and /GRSH3N/SH3N and /TH/SH3N
    resolve only /SH3N IDs. This applies the identical test _make_parts uses
    (len(_ordered_unique_nodes(...))) so the two can never drift apart.

    Shells with fewer than 3 distinct corners are dropped by _make_parts (zero
    area, no element is emitted at all), so they are dropped here too — there
    is nothing left for a group to reference. IDs that name no known shell are
    left in the quad list, preserving the pre-existing pass-through behaviour
    rather than silently discarding a caller's ID.
    """
    by_eid = {e.eid: e for e in state.shell_elems}
    quads: List[int] = []
    tris: List[int] = []
    for eid in eids:
        e = by_eid.get(eid)
        if e is None:
            quads.append(eid)
            continue
        n_distinct = len(_ordered_unique_nodes(e.nodes))
        if n_distinct >= 4:
            quads.append(eid)
        elif n_distinct == 3:
            tris.append(eid)
    return quads, tris


def _fmt_eid_list(eids: List[int], limit: int = 25) -> str:
    """Comma-separated element IDs, truncated past *limit* with a count."""
    s = ", ".join(str(e) for e in eids[:limit])
    if len(eids) > limit:
        s += f", ... (+{len(eids) - limit} more)"
    return s


def _part_node_sets(state: ConversionState) -> dict:
    """{pid: set-of-node-ids} over the structural element containers (solids,
    thick shells, shells, beam end nodes) — the per-part node inventory the
    /XREF reference geometry intersects with (dyna2rad GetNodesOfParts
    equivalent).

    SPH particles are deliberately NOT counted, and that verdict is per CALLER
    — there are eleven, not one:

    * ``inistate._resolve_xref_parts`` / ``inistate._make_xref`` and
      ``materials._resolve_mat_ref_geometry`` — /XREF reference geometry, which
      is for SOLID elements (``hm_read_xref.F``; the starter's whitelist is laws
      1/35/38/42/70/88/90 on 8/4-node solids, ERROR 2013/2014 otherwise). This
      is the exclusion's REASON: counting particles would let an
      *INITIAL_FOAM_REFERENCE_GEOMETRY node set that happens to touch an SPH
      cloud claim that part for a /XREF — and, worse, drag its *SECTION into
      Ismstr=10 along with every sibling part on it. ``_resolve_xref_parts``
      names an SPH part reached that way instead.
    * ``inistate._warn_airbag_ref_options`` and
      ``inistate._resolve_airbag_eref`` — the airbag reference-geometry pair,
      which feeds the same /XREF (so it inherits the reason above) and needs
      the per-part inventory for two more decisions: which fabric materials an
      *AIRBAG_REFERENCE_GEOMETRY_BIRTH arms, and which parts a /XREF already
      covers so their /EREF rows can be dropped (a node in both is starter
      ERROR 1098). Particles have no place in either.
    * ``contacts._spotweld_slave_nids`` — a spot weld's secondary side is the
      weld nugget, and a particle is not one.
    * ``joints._resolve_joint_stiffness_targets`` — resolves a
      *CONSTRAINED_JOINT_STIFFNESS onto rigid JOINT bodies; a particle part is
      not a joint body.
    * ``loads._make_local_prescribed_skews`` and the two
      ``loads._rbody_mains_in_scope`` sites — node-overlap SCOPING of rigid-body
      mains. A rigid body built on particles gets its node inventory from
      ``rbody._make_rbodies`` (which does have an SPH arm), so the omission
      here can only fail to widen a load group's scope onto a rigid main whose
      nodes are exclusively particles — narrow, and it never drops mass or
      clamps a node.
    * ``joints._warn_no_pacing_element`` — the ONE caller that must count
      particles, because an SPH part genuinely paces the engine time step
      (``mdtsph.F``). It adds them itself rather than changing this inventory
      for the /XREF callers' sake.

    Add a caller to that list rather than to this function.
    """
    pnodes: dict = {}
    for e in state.solid_elems:
        s = pnodes.setdefault(e.pid, set())
        s.update(n for n in e.nodes if n > 0)
    for e in state.tshell_elems:
        s = pnodes.setdefault(e.pid, set())
        s.update(n for n in e.nodes if n > 0)
    for e in state.shell_elems:
        s = pnodes.setdefault(e.pid, set())
        s.update(n for n in e.nodes if n > 0)
    for e in state.beam_elems:
        s = pnodes.setdefault(e.pid, set())
        if e.n1 > 0:
            s.add(e.n1)
        if e.n2 > 0:
            s.add(e.n2)
    return pnodes


def _ref_flag_materials(state: ConversionState):
    """Every material container whose LS-DYNA card carries a REF flag ("use
    reference geometry to initialize the stress tensor", EQ.0.0 off / EQ.1.0
    on), as (keyword, {mid: material}) pairs.

    The single list behind both REF diagnostics: the coverage warnings in
    ``materials._warn_rubber_ref`` (REF=1 with no reference geometry to read)
    and the reverse check in ``inistate._resolve_xref_parts`` (a /XREF landing
    on a REF=0 material). Keeping them on one registry is what stops a new
    REF-bearing family from being reported by one and not the other — which is
    exactly how *MAT_SOFT_TISSUE and *MAT_SIMPLIFIED_RUBBER first shipped."""
    return (
        ("*MAT_BLATZ-KO_RUBBER", state.mat_blatz_ko),            # 007, p.2-108
        ("*MAT_MOONEY-RIVLIN_RUBBER", state.mat_mooney_rivlin),  # 027, p.2-249
        ("*MAT_OGDEN_RUBBER", state.mat_ogden),                  # 077_O
        ("*MAT_HYPERELASTIC_RUBBER", state.mat_hyper_rubber),    # 077_H
        ("*MAT_SIMPLIFIED_RUBBER/FOAM", state.mat_simplified_rubber),
        ("*MAT_SOFT_TISSUE", state.mat_soft_tissue),             # 091/092
        # Foam batch. MAT_005 card 2 carries REF directly (p.2-179). MAT_073
        # has no card-level REF: each optional Gi/BETAi card ends in a REF
        # flag, folded to mat.ref = 1.0 when any term sets it (p.2-547).
        # Only MAT_073's LAW90 target is on the starter's solid-/XREF law
        # whitelist; a REF=1 MAT_005 additionally draws the off-whitelist
        # warn-skip from _resolve_xref_parts (LAW21, ERROR 2014).
        # MAT_126/154/177 carry no REF flag at all.
        ("*MAT_SOIL_AND_FOAM", state.mat_soil_and_foam),         # 005
        ("*MAT_LOW_DENSITY_VISCOUS_FOAM",
         state.mat_low_density_viscous_foam),                    # 073
        # Impact / blast batch: *MAT_110, *MAT_111 and *MAT_ELASTIC(_FLUID)
        # carry NO REF flag on any card (mat_110.cfg / mat_111.cfg are three
        # pure-constant cards; mat_001.cfg card 1 ends at K and the FLUID card
        # holds only VC and CP), so none of them belongs on this registry —
        # recorded here so the next batch does not re-derive it. Their /XREF
        # story is the law whitelist instead: LAW79/LAW126/LAW6 are all OFF
        # _XREF_SOLID_LAWS, so inistate._resolve_xref_parts warn-skips such
        # parts naming the law.
        #
        # Airbag / MONVOL batch: *MAT_FABRIC carries NO REF flag on any of its
        # eight cards (card 3 is AOPT FLC/X2 FAC/X3 ELA LNRC FORM FVOPT TSRFAC
        # — no REF column anywhere), so it does not belong on this registry
        # either. Recorded so the next batch does not re-derive it. Its
        # reference-state story is a different mechanism entirely: LS-DYNA's
        # ISREFG / RGBRTH fields ask for the *AIRBAG_REFERENCE_GEOMETRY to be
        # applied, and in Radioss that request IS the emitted /XREF or /EREF —
        # both fabric laws honour one (cepsini.F::CMLAWI dispatches ILAW 1, 19
        # and 58), with no material flag to check. Fabric parts are SHELL
        # parts, so they also skip the solid-/XREF law whitelist altogether.
    )


# ─────────────────────────────────────────────────────────────────────────────
# Starter: connectors (*ELEMENT_DISCRETE springs/dampers, spotwelds)
# ─────────────────────────────────────────────────────────────────────────────

def _discrete_part_ids(state: ConversionState) -> Set[int]:
    """Part ids handled by the discrete-spring connector path: parts referenced
    by *ELEMENT_DISCRETE, or whose section is a *SECTION_DISCRETE, or whose
    material is a discrete spring/damper material. These are skipped by the
    normal /PART emission (their /PART + /PROP/TYPE4 come from
    _make_discrete_springs; the DYNA section/material ids have no /PROP or
    /MAT of their own)."""
    spring_mids = (set(state.mat_spring_elastic) | set(state.mat_spring_nonlinear)
                   | set(state.mat_damper_viscous)
                   | set(state.mat_spring_elastoplastic)
                   | set(state.mat_damper_nl_viscous)
                   | set(state.mat_spring_general_nl)
                   | set(state.mat_spring_inelastic)
                   # *MAT_SPRING_MUSCLE (S15) is a discrete-spring material
                   # too. It is claimed HERE so an element-free S15 part is
                   # skipped by the ordinary /PART emission like every other
                   # spring part; which of the two spring writers then emits it
                   # is decided by _muscle_discrete_pids.
                   | set(state.mat_spring_muscle))
    pids = {e.pid for e in state.discrete_elems}
    for pid, p in state.parts.items():
        secid = p.secid if p.secid > 0 else pid
        if secid in state.sec_discrete or p.mid in spring_mids:
            pids.add(pid)
    return pids


def _muscle_beam_pids(state: ConversionState) -> Set[int]:
    """Part ids handled by the *MAT_MUSCLE (156) → /PROP/TYPE46 path.

    LS-DYNA states MAT_156 for TRUSS elements (Vol II R17 p.2-1071, *"This is
    Material Type 156 for truss elements"*), i.e. a ``*SECTION_BEAM`` with
    ELFORM 3. Radioss DOES have a truss element — ``/TRUSS`` + ``/PROP/TYPE2``,
    which :mod:`k2rad.writer.truss` emits for every OTHER ELFORM-3 part — but
    it carries no muscle law: ``PROP_TRUSS`` is declared by six laws only
    (0, 1, 2, 13, 34, 44 — ``init_mat_keyword.F:269-270``), LAW156 is not among
    them, and a ``/TRUSS`` on one would be starter ERROR 3046. The closest
    faithful target is therefore the muscle SPRING property ``/PROP/TYPE46``,
    not the truss property, whose force law
    ``FX = Force·f1(t)·f2(ΔL)·f3(ΔL̇) + Scale_F·f4(ΔL) + Damp·VX``
    (``ruser46.F:207-211``) is term for term the ``sigma1 + sigma2 + sigma3``
    of the LS-DYNA card. So these parts get their /PART + /PROP + /SPRING from
    ``_make_muscle_springs`` and are skipped WHOLE by the ordinary /PART +
    /BEAM + /PROP/BEAM emission.

    Same claim shape as ``_discrete_beam_pids``: parts carrying shell, solid,
    thick-shell or SPH elements are excluded (a muscle material on a continuum
    part is a modelling error the converter must not silently reinterpret as a
    spring), and so are parts the *ELEMENT_DISCRETE path already owns — BOTH
    writers emit ``/PART/<pid>`` under the source pid, so a doubly claimed part
    would be written twice and the starter would answer ERROR 79.
    """
    if not state.mat_muscle:
        return set()
    continuum_pids = ({e.pid for e in state.shell_elems}
                      | {e.pid for e in state.solid_elems}
                      | {e.pid for e in state.tshell_elems}
                      | {c.pid for c in state.sph_elems})
    discrete_pids = _discrete_part_ids(state)
    return {pid for pid, p in state.parts.items()
            if p.mid in state.mat_muscle
            and pid not in continuum_pids and pid not in discrete_pids}


def _muscle_discrete_pids(state: ConversionState) -> Set[int]:
    """Part ids handled by the *MAT_SPRING_MUSCLE (S15) → /PROP/TYPE46 path.

    These are ORDINARY discrete-spring parts by claim (``_discrete_part_ids``
    already owns them, so ``_make_parts_and_elements`` skips them); what this
    set does is tell ``_make_discrete_springs`` to leave them to
    ``_make_muscle_springs`` instead of writing the inert /PROP/TYPE4 it writes
    for an unconvertible spring material. Without the split BOTH writers would
    emit ``/PART/<pid>`` — starter ERROR 79.
    """
    if not state.mat_spring_muscle:
        return set()
    return {pid for pid, p in state.parts.items()
            if p.mid in state.mat_spring_muscle}


def _muscle_part_ids(state: ConversionState) -> Set[int]:
    """Every part the /PROP/TYPE46 muscle writer owns, from either side."""
    return _muscle_beam_pids(state) | _muscle_discrete_pids(state)


def _discrete_beam_mids(state: ConversionState) -> Set[int]:
    """Every MID that names a *SECTION_BEAM ELFORM=6 discrete-beam material —
    the eight k2rad converts plus the seven it can only warn about."""
    mids: Set[int] = set()
    for d in (state.mat_dbeam_linear, state.mat_dbeam_nl_elastic,
              state.mat_dbeam_nl_plastic, state.mat_cable_dbeam,
              state.mat_elastic_spring_dbeam, state.mat_gnl_6dof,
              state.mat_gnl_1dof, state.mat_general_spring_dbeam,
              state.mat_unsupported_dbeam):
        mids |= set(d)
    return mids


def _discrete_beam_pids(state: ConversionState) -> Set[int]:
    """Part ids handled by the DISCRETE-BEAM connector path: parts whose
    *SECTION_BEAM is ELFORM=6, or whose material is a discrete-beam material.

    An LS-DYNA discrete beam is a 6-DOF spring, so these parts get a
    /PROP/TYPE8 or /PROP/TYPE13 + /SPRING from _make_discrete_beam_connectors
    instead of the ordinary /PART + /PROP/BEAM + /BEAM — an ELFORM=6 section
    states no cross-section at all, so a /PROP/BEAM built from it is starter
    ERROR 314-317 and the deck never starts.

    Parts carrying shell, solid, THICK-SHELL or SPH elements are excluded (the
    same guard _spotweld_beam_pids uses): a discrete-beam material on a
    continuum part is a modelling error k2rad must not silently reinterpret as
    a spring. The last two matter as much as the first two even though the
    coincidence is rarer — a claimed part is skipped WHOLE by
    _make_parts_and_elements, so an SPH part whose SECID happens to match an
    ELFORM=6 *SECTION_BEAM loses its /PART, its entire /SPHCEL block and its
    sph_cell_ids registration, and any /TH/SPHCEL naming those particles then
    empties to nothing.

    Parts already claimed by _discrete_part_ids are excluded too, and for a
    harder reason: BOTH writers emit ``/PART/<pid>`` under the source pid, so a
    part that satisfies both tests would be written twice and the starter would
    answer ERROR 79 (DUPLICATE ID) and refuse the deck. That overlap is
    reachable without anything exotic — a *PART with a blank SECID falls back
    to ``secid = pid`` (see _discrete_part_ids), so a discrete-spring part whose
    id happens to equal an ELFORM=6 *SECTION_BEAM's id lands in both sets. The
    *ELEMENT_DISCRETE side wins because its elements are the ones that name the
    part; _make_discrete_beam_connectors reports what the beam side lost.
    """
    elform6 = {s.secid for s in state.sec_beams.values() if s.elform == 6}
    dbeam_mids = _discrete_beam_mids(state)
    if not elform6 and not dbeam_mids:
        return set()
    continuum_pids = ({e.pid for e in state.shell_elems}
                      | {e.pid for e in state.solid_elems}
                      | {e.pid for e in state.tshell_elems}
                      | {c.pid for c in state.sph_elems})
    # ... and the *MAT_MUSCLE parts, for the same ERROR-79 reason: they get a
    # /PART + /PROP/TYPE46 from _make_muscle_springs.
    discrete_pids = _discrete_part_ids(state) | _muscle_beam_pids(state)
    pids: Set[int] = set()
    for pid, p in state.parts.items():
        if pid in continuum_pids or pid in discrete_pids:
            continue
        secid = p.secid if p.secid > 0 else pid
        if secid in elform6 or p.mid in dbeam_mids:
            pids.add(pid)
    return pids


def _truss_secids(state: ConversionState) -> Set[int]:
    """``*SECTION_BEAM`` ids whose ELFORM is 3 — the TRUSS formulation.

    A FLAG on the section, not a new element container. A truss IS an
    ``*ELEMENT_BEAM`` on a ``*SECTION_BEAM`` in LS-DYNA — ``*SET_BEAM``,
    ``*DATABASE_HISTORY_BEAM`` and the ``*INCLUDE_TRANSFORM`` offset walker all
    address it as a beam — so the elements stay in ``state.beam_elems`` and the
    sections in ``state.sec_beams``, and only the WRITE side branches. That
    keeps every mixed-family SECID test (``writer/sph.py``, ``writer/tshell.py``,
    ``writer/muscle.py``), the ``next_prop_id`` allocator and the
    ``_make_plotel_elements`` id-collision dodge correct with no edit at all —
    a second container would have made each of them a two-dict walk, and a
    missed one is silent mesh loss (the #120 failure mode).
    """
    return {s.secid for s in state.sec_beams.values() if s.elform == 3}


def _truss_pids(state: ConversionState) -> Set[int]:
    """Part ids whose ``*SECTION_BEAM`` is ELFORM=3, i.e. whose ``*ELEMENT_BEAM``
    rows become ``/TRUSS`` and whose property becomes ``/PROP/TYPE2``.

    Parts already claimed by a CONNECTOR path are excluded, exactly as
    ``_discrete_beam_pids`` excludes the discrete-spring ones: ``*MAT_MUSCLE``
    parts are ELFORM=3 by convention and already become a ``/PROP/TYPE46``
    ``/SPRING`` (LAW156 has no Radioss counterpart and ``PROP_TRUSS`` is not
    declared for the muscle law), and both writers emit ``/PART/<pid>`` — two
    of them is starter ERROR 79.

    A part carrying shell/solid/thick-shell/SPH elements is excluded too, on
    the same reasoning ``_discrete_beam_pids`` states: a continuum part whose
    SECID happens to collide with an ELFORM=3 ``*SECTION_BEAM`` must keep its
    own element blocks.
    """
    secids = _truss_secids(state)
    if not secids:
        return set()
    claimed = (_discrete_part_ids(state) | _muscle_beam_pids(state)
               | _muscle_part_ids(state) | _spotweld_beam_pids(state)
               | _discrete_beam_pids(state) | _seatbelt_part_ids(state))
    continuum_pids = ({e.pid for e in state.shell_elems}
                      | {e.pid for e in state.solid_elems}
                      | {e.pid for e in state.tshell_elems}
                      | {c.pid for c in state.sph_elems})
    pids: Set[int] = set()
    for pid, p in state.parts.items():
        if pid in claimed or pid in continuum_pids:
            continue
        secid = p.secid if p.secid > 0 else pid
        if secid in secids:
            pids.add(pid)
    return pids


def _discrete_beam_claim_conflicts(state: ConversionState) -> Set[int]:
    """Parts an ELFORM=6 *SECTION_BEAM (or a discrete-beam material) claims but
    that the *ELEMENT_DISCRETE spring path owns — see _discrete_beam_pids."""
    elform6 = {s.secid for s in state.sec_beams.values() if s.elform == 6}
    dbeam_mids = _discrete_beam_mids(state)
    if not elform6 and not dbeam_mids:
        return set()
    out: Set[int] = set()
    for pid in _discrete_part_ids(state):
        p = state.parts.get(pid)
        if p is None:
            continue
        secid = p.secid if p.secid > 0 else pid
        if secid in elform6 or p.mid in dbeam_mids:
            out.add(pid)
    return out


def _spotweld_beam_pids(state: ConversionState) -> Set[int]:
    """*MAT_SPOTWELD (MAT_100) parts whose elements are exclusively beams —
    these become /PROP/TYPE13 (SPR_BEAM) /SPRING connectors. MAT_100 on
    shell/solid (hexa) spotwelds is NOT converted (falls back to /MAT/ELAST)."""
    if not state.mat_spotweld:
        return set()
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    beam_pids = {e.pid for e in state.beam_elems}
    return {pid for pid, p in state.parts.items()
            if p.mid in state.mat_spotweld and pid in beam_pids
            and pid not in shell_pids and pid not in solid_pids}


def _emit_surf_seg(surf_id: int, title: str, segments) -> List[str]:
    """A /SURF/SEG from a list of node lists (shared by blast/EBCS/FSI)."""
    lines = [f"/SURF/SEG/{surf_id}", (title or f"surf_seg_{surf_id}")[:100],
             "#   seg_ID        n1        n2        n3        n4"]
    for seg_no, nodes in enumerate(segments, start=1):
        quad = (list(nodes) + [0, 0, 0, 0])[:4]
        lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
    lines.append(HDR)
    return lines


def _emit_line_seg(line_id: int, title: str, edges) -> List[str]:
    """A /LINE/SEG line group from a list of 2-node edges [(n1, n2), …].

    The 2-node analogue of _emit_surf_seg: each row is ``seg_ID n1 n2``. The
    starter (`hm_read_lines.F`) identifies the segment purely by (N1, N2) and
    treats col-1 seg_ID as a discarded positional index, so it is emitted as a
    running 1..N counter. Consumed by /INTER/TYPE11 line_IDs / line_IDm.
    """
    lines = [f"/LINE/SEG/{line_id}", (title or f"line_seg_{line_id}")[:100],
             "#   seg_ID        n1        n2"]
    for seg_no, (n1, n2) in enumerate(edges, start=1):
        lines.append(_i(seg_no) + _i(n1) + _i(n2))
    lines.append(HDR)
    return lines


def _emit_line_surf(line_id: int, title: str, surf_ids: List[int]) -> List[str]:
    """A /LINE/SURF line group referencing one or more /SURF ids.

    The starter derives every segment edge of the referenced surface(s) into
    line segments (`hm_read_lines.F` IT5/LINEDGE path), so this is the
    node-pair-free way to build the edge set of an already-emitted /SURF (the
    /INTER/TYPE11 edge contact of a shell/solid part). Consumed by
    /INTER/TYPE11 line_IDs / line_IDm.
    """
    lines = [f"/LINE/SURF/{line_id}", (title or f"line_surf_{line_id}")[:100],
             "#  surf_ID"]
    row: List[str] = []
    for s in surf_ids:
        row.append(_i(s))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines

# ─────────────────────────────────────────────────────────────────────────────
# Starter: seatbelts (*ELEMENT_SEATBELT and its four devices)
# ─────────────────────────────────────────────────────────────────────────────

def _seatbelt_mat_law(state: ConversionState, mid: int) -> Optional[int]:
    """``114``, ``119`` or ``None`` — the law a ``*MAT_SEATBELT`` becomes.

    A pure function of the STATE, so the material writer, the property writer
    and ``mesh._target_mat_law`` cannot drift apart (the #100 one-map rule).

    The branch is on the PROPERTY the material's parts carry, **not** on the
    material keyword — dyna2rad ``convertmats.cxx:517-526``::

        case 801:
            if (propKeyWord.find("SEATBELT") != npos)  p_ConvertMatL801Seatbelt(...);
            else if (propKeyWord.find("SHELL") != npos) p_ConvertMatL801Shell(...);

    so a ``*MAT_SEATBELT`` on a ``*SECTION_SHELL`` is LAW119 and a
    ``*MAT_SEATBELT_2D`` on a ``*SECTION_SEATBELT`` is LAW114: the ``_2D``
    suffix is IGNORED. That is not a defect to route around — it is the only
    rule that can work, because the law has to match the element family the
    part actually holds, and the section is what states that.

    dyna2rad's third branch is the one k2rad does not copy: when the section is
    NEITHER (a belt material on a part with no section at all, or on a
    ``*SECTION_BEAM``), ``destCard`` stays empty and it emits **no material at
    all** (``convertmats.cxx:556-561`` calls ``CreateEntity`` with ``""``),
    leaving the /PART pointing at a MID nothing defines — starter ERROR 21. The
    fallback here is the 1D law, which is what a belt material means when
    nothing says otherwise, and the writer warns by name.
    """
    if mid not in state.mat_seatbelt:
        return None
    on_shell = False
    on_belt = False
    for pid, part in state.parts.items():
        if part.mid != mid:
            continue
        secid = part.secid if part.secid > 0 else pid
        if secid in state.sec_seatbelts:
            on_belt = True
        elif secid in state.sec_shells:
            on_shell = True
    if on_belt:
        return 114
    if on_shell:
        return 119
    return 114


def _seatbelt_part_ids(state: ConversionState) -> Set[int]:
    """*PART ids handled by the 1D-belt connector path — the parts whose
    ``/PART`` + ``/PROP/TYPE23`` + ``/MAT/LAW114`` + ``/SPRING`` all come from
    :func:`_make_seatbelts` and must therefore be skipped by the ordinary mesh
    and property writers (emitting them twice is starter ERROR 79).

    A part is claimed when it owns 1D ``*ELEMENT_SEATBELT`` elements, or its
    section is a ``*SECTION_SEATBELT``, or its material resolves to LAW114 —
    the same three-way test ``common._discrete_part_ids`` makes, including the
    blank-SECID fallback ``secid = pid``.

    Parts holding shell / solid / thick-shell / SPH / beam elements are
    EXCLUDED, the guard ``_discrete_beam_pids`` documents: a claimed part is
    skipped WHOLE by ``_make_parts_and_elements``, so a continuum part that
    happened to satisfy the material test would lose its entire element block
    and every registry entry that depends on it. It is also how a 2D belt stays
    out: those parts hold ``*ELEMENT_SHELL``-shaped seatbelt elements and go
    down the LAW119 route instead.
    """
    if not (state.seatbelt_elems or state.sec_seatbelts
            or state.mat_seatbelt):
        return set()
    # `pid in state.parts` is not a formality: a belt element whose PID has no
    # *PART record is parsed, warned about by the mesh-loss census
    # (assembly._warn_orphan_elements) and never written — claiming its part
    # here would hand the seatbelt writer a pid it cannot look up. The three
    # sibling claimers build from `state.parts` for the same reason.
    belt_1d_pids = {e.pid for e in state.seatbelt_elems
                    if not e.is_2d and e.pid in state.parts}
    law114_mids = {mid for mid in state.mat_seatbelt
                   if _seatbelt_mat_law(state, mid) == 114}
    continuum_pids = ({e.pid for e in state.shell_elems}
                      | {e.pid for e in state.solid_elems}
                      | {e.pid for e in state.tshell_elems}
                      | {c.pid for c in state.sph_elems}
                      | {e.pid for e in state.beam_elems}
                      | {e.pid for e in state.discrete_elems}
                      | {e.pid for e in state.seatbelt_elems if e.is_2d})
    pids = {p for p in belt_1d_pids if p not in continuum_pids}
    for pid, part in state.parts.items():
        if pid in continuum_pids:
            continue
        secid = part.secid if part.secid > 0 else pid
        if secid in state.sec_seatbelts or part.mid in law114_mids:
            pids.add(pid)
    return pids


def _seatbelt_2d_part_ids(state: ConversionState) -> Set[int]:
    """*PART ids that carry a 2D (shell) belt — a /MAT/LAW119 part.

    Claimed by the MATERIAL resolving to LAW119, exactly as the fabric batch
    claims its shell parts: ``/MAT/LAW119`` declares ``SHELL_ORTHOTROPIC``
    (``hm_read_mat119.F:218`` ``CALL INIT_MAT_KEYWORD(MATPARAM,
    "SHELL_ORTHOTROPIC")``, PROP_SHELL = 2), so the part cannot stay on the
    isotropic ``/PROP/SHELL`` its ``*SECTION_SHELL`` would give it —
    ``check_mat_elem_prop_compatibility.F:175-192`` answers ERROR 3047. Unlike
    the 1D path these parts keep their ordinary ``/PART`` and their ordinary
    ``/SHELL`` block; only the property is repointed (#110/#109/#123).
    """
    if not state.mat_seatbelt:
        return set()
    law119_mids = {mid for mid in state.mat_seatbelt
                   if _seatbelt_mat_law(state, mid) == 119}
    if not law119_mids:
        return set()
    return {pid for pid, part in state.parts.items()
            if part.mid in law119_mids}


# ─────────────────────────────────────────────────────────────────────────────
# /SECT frame geometry — shared by writer/preload.py (the *INITIAL_STRESS_
# SECTION bolt-preload /SECT) and writer/inistate.py (the reporting /SECT).
# Both build the SAME thing: three synthesized, element-free nodes whose
# (N2-N1) x (N3-N1) is the section normal by construction. They lived in
# preload.py until the SIDE-DEFECT batch gave the reporting /SECT the same
# treatment, and preload.py imports FROM inistate.py, so the shared home has
# to be here.
# ─────────────────────────────────────────────────────────────────────────────

def _orthonormal_pair(nhat):
    """``(e1, e2)``, orthonormal and perpendicular to ``nhat``, with
    ``e1 x e2 == nhat`` exactly."""
    a = (1.0, 0.0, 0.0) if abs(nhat[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = a[0] * nhat[0] + a[1] * nhat[1] + a[2] * nhat[2]
    e1 = _vnorm((a[0] - d * nhat[0], a[1] - d * nhat[1], a[2] - d * nhat[2]))
    if e1 is None:                                   # pragma: no cover
        return None
    return (e1, _vcross(nhat, e1))


def _node_cloud_normal(state: ConversionState, nids: List[int]):
    """Best-conditioned plane normal of a node cloud, or ``None``.

    Used for a ``*DATABASE_CROSS_SECTION_SET`` whose ``*INITIAL_STRESS_SECTION``
    states no VID. LS-DYNA requires one there ("VID must be set when the SET
    variant of *DATABASE_CROSS_SECTION is used", Vol I R17 p.3144) precisely
    because the node ORDER in the set carries no plane information — which is
    why dyna2rad, which never reads VID, falls back to a dummy
    (0,0,0)/(1,0,0)/(0,1,0) triad and silently preloads along global +Z
    (convertcrosssections.cxx:246-251). Fitting the plane the section nodes
    actually lie in is the honest best effort: exact for a planar cut, and the
    caller says out loud that it was a fit.
    """
    pts = [state.nodes[n] for n in nids if n in state.nodes]
    if len(pts) < 3:
        return None
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    cz = sum(p.z for p in pts) / len(pts)
    rel = [(p.x - cx, p.y - cy, p.z - cz) for p in pts]
    u = max(rel, key=lambda v: v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if u[0] ** 2 + u[1] ** 2 + u[2] ** 2 <= 0.0:
        return None
    best, best_a2 = None, 0.0
    for v in rel:
        c = _vcross(u, v)
        a2 = c[0] ** 2 + c[1] ** 2 + c[2] ** 2
        if a2 > best_a2:
            best, best_a2 = c, a2
    if best is None or best_a2 <= 0.0:
        return None
    return _vnorm(best)


def _nid_centroid(state: ConversionState, nids: List[int]):
    pts = [state.nodes[n] for n in nids if n in state.nodes]
    if not pts:
        return (0.0, 0.0, 0.0)
    return (sum(p.x for p in pts) / len(pts),
            sum(p.y for p in pts) / len(pts),
            sum(p.z for p in pts) / len(pts))


def _preload_sect_scale(state: ConversionState, origin, nids: List[int]) -> float:
    """A length scale for the synthesized frame, taken from the section itself
    so the three new nodes land in the cut's own neighbourhood instead of one
    deck unit away from it (which in a metre model would be a metre)."""
    best = 0.0
    for n in nids:
        nd = state.nodes.get(n)
        if nd is None:
            continue
        d = math.sqrt((nd.x - origin[0]) ** 2 + (nd.y - origin[1]) ** 2
                      + (nd.z - origin[2]) ** 2)
        best = max(best, d)
    return best if best > 0.0 else 1.0
