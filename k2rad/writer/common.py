"""Shared low-level helpers: field formatting, group/surface emitters, small vector math."""

from __future__ import annotations

from typing import List, Set
from ..state import ConversionState

__all__ = [
    "HDR",
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
    "_spotweld_beam_pids",
    "_emit_surf_seg",
    "_emit_line_seg",
    "_emit_line_surf",
    "_part_node_sets",
    "_ref_flag_materials",
]


HDR = "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|"


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
            grshel_id = state.next_id()
            out_lines += _emit_grshel(grshel_id, f"{title}_grshel", quad_eids)
            out_lines += _emit_surf_grshel(surf_id, title, grshel_id)
        elif tri_eids:
            grsh3n_id = state.next_id()
            out_lines += _emit_grsh3n(grsh3n_id, f"{title}_grsh3n", tri_eids)
            out_lines += _emit_surf_grsh3n(surf_id, title, grsh3n_id)
        else:
            out_lines += _emit_solid_surf(surf_id, title, solid_pids)
        return True

    sub_ids: List[int] = []
    if quad_eids:
        grshel_id = state.next_id()
        sub_shell = state.next_id()
        out_lines += _emit_grshel(grshel_id, f"{title}_grshel", quad_eids)
        out_lines += _emit_surf_grshel(sub_shell, f"{title}_shells", grshel_id)
        sub_ids.append(sub_shell)
    if tri_eids:
        grsh3n_id = state.next_id()
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
    — there are nine, not one:

    * ``inistate._resolve_xref_parts`` / ``inistate._make_xref`` and
      ``materials._resolve_mat_ref_geometry`` — /XREF reference geometry, which
      is for SOLID elements (``hm_read_xref.F``; the starter's whitelist is laws
      1/35/38/42/70/88/90 on 8/4-node solids, ERROR 2013/2014 otherwise). This
      is the exclusion's REASON: counting particles would let an
      *INITIAL_FOAM_REFERENCE_GEOMETRY node set that happens to touch an SPH
      cloud claim that part for a /XREF — and, worse, drag its *SECTION into
      Ismstr=10 along with every sibling part on it. ``_resolve_xref_parts``
      names an SPH part reached that way instead.
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
                   | set(state.mat_spring_inelastic))
    pids = {e.pid for e in state.discrete_elems}
    for pid, p in state.parts.items():
        secid = p.secid if p.secid > 0 else pid
        if secid in state.sec_discrete or p.mid in spring_mids:
            pids.add(pid)
    return pids


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
    discrete_pids = _discrete_part_ids(state)
    pids: Set[int] = set()
    for pid, p in state.parts.items():
        if pid in continuum_pids or pid in discrete_pids:
            continue
        secid = p.secid if p.secid > 0 else pid
        if secid in elform6 or p.mid in dbeam_mids:
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
