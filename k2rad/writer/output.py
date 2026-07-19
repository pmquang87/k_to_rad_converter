"""Starter header/title/analysis cards, time-history outputs, /EIG, notes and skipped-keyword comment."""

from __future__ import annotations

from typing import Dict, List, Set
from ..state import ConversionState
from .common import HDR, _f, _i
from .contacts import _select_parent_interface

__all__ = [
    "_make_header",
    "_make_title",
    "_make_analysis_defaults",
    "_make_ams",
    "_make_starter_th",
    "_make_freq_domain_notes",
    "_make_skipped_comment",
    "_make_eig",
    "_make_starter_th_inter",
    "_make_starter_th_node_reac",
    "_make_starter_th_surf",
    "_spc_constrains_rotations",
    "_make_starter_th_node_spc",
]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: header & defaults
# ─────────────────────────────────────────────────────────────────────────────

def _make_header(state: ConversionState) -> List[str]:
    # /BEGIN block embeds the unit system (Reference Guide).
    # Format:
    #   /BEGIN
    #   <title (80 chars)>
    #   <version>  <flag>
    #   <input mass>  <input length>  <input time>     ← .k file units
    #   <work mass>   <work length>   <work time>      ← internal units
    # LS-DYNA default unit system is ton (Mg) mm s N MPa.
    # Mg = megagram = 1000 kg = 1 tonne. Default is Mg/mm/s to match the .k file;
    # callers may override via convert(units=...) / the CLI --units flag.
    title = state.model_title[:80].ljust(80)
    mass, length, time = state.units
    unit_line = f"{mass.rjust(20)}{length.rjust(20)}{time.rjust(20)}"
    return [
        "#RADIOSS STARTER",
        HDR,
        "/BEGIN",
        title,
        "      2022         0",
        unit_line,
        unit_line,
        HDR,
    ]


def _make_title(state: ConversionState) -> List[str]:
    return ["/TITLE", state.model_title, HDR]


def _make_analysis_defaults(state: ConversionState) -> List[str]:
    cs = state.ctrl_shell
    ithick = 0
    if cs and cs.istupd:
        ithick = 2 if cs.istupd >= 2 else 1

    lines = [
        "/ANALY",
        "         0",
        HDR,
        "/DEF_SHELL",
    ]
    if ithick > 0:
        lines.append(f"         0         0{_i(ithick)}")
    else:
        lines.append("         0")
    lines += [HDR, "/DEF_SOLID", "         0", HDR]
    lines += ["/IOFLAG", "         0", HDR]
    return lines


def _make_ams(state: ConversionState) -> List[str]:
    """Opt-in Advanced Mass Scaling starter card (--ams), paired with the engine
    /DT/AMS (see _make_engine_timestep). grpart_ID = 0 → AMS applies to all
    parts; the solver auto-skips rigid bodies ("NO AMS EXPANSION OVERALL THE
    RBODY"). Only for a mass-scaled explicit deck (*CONTROL_TIMESTEP DT2MS<0);
    implicit/modal decks have no CFL step to scale. --ams forces element-free
    rigid masters (see convert()) so this never trips AMS ERROR 1066."""
    ts = state.ctrl_timestep
    if (not state.options.ams or ts is None or ts.dt2ms >= 0.0
            or state.is_implicit or state.is_modal):
        return []
    return ["/AMS", "#grpart_ID", _i(0), HDR]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: time history outputs
# ─────────────────────────────────────────────────────────────────────────────

def _make_starter_th(state: ConversionState) -> List[str]:
    if not state.db_histories:
        return []
    lines = ["#-  TIME HISTORY OUTPUTS:", HDR]
    counter = 1
    type_map = {"SHELL": "SHEL", "SOLID": "BRIC", "NODE": "NODE"}
    for dbh in state.db_histories:
        rad_type = type_map.get(dbh.db_type, dbh.db_type)
        lines += [
            f"/TH/{rad_type}/{counter}",
            f"TH_{rad_type}_{counter}",
            "#     var1      var2",
            "DEF       ",
        ]
        for eid in dbh.ids:
            lines.append(_i(eid))
        counter += 1
    lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: offline frequency-domain post-processing notes
# ─────────────────────────────────────────────────────────────────────────────

def _make_freq_domain_notes(state: ConversionState) -> List[str]:
    """*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG + *MAT_ADD_FATIGUE.

    OpenRadioss has no frequency-domain binary databases and no S-N fatigue
    material add-on; instead of listing these as bare "skipped" keywords, note
    where the results come from: the offline modal post-processing chain
    (tools/modal_solve.py → tools/modal_shapes_export.py mode shapes;
    tools/modal_random_response.py PSD/RMS/Dirlik fatigue honouring the deck's
    D3PSD band, PSD curve and *MAT_ADD_FATIGUE S-N data).
    """
    kinds = sorted(state.db_freq_binary)
    if not kinds and not state.mat_add_fatigue:
        return []
    what = [f"*DATABASE_FREQUENCY_BINARY_{k}" for k in kinds]
    if state.mat_add_fatigue:
        mids = ", ".join(str(m) for m in sorted(state.mat_add_fatigue))
        what.append(f"*MAT_ADD_FATIGUE (mid {mids})")
    listing = ", ".join(what)
    if state.is_modal:
        state.warn(
            f"NOTE: {listing}: no OpenRadioss equivalent - these results are "
            "produced OFFLINE from the modal solution: run tools/"
            "modal_solve.py (eigenmodes), then tools/modal_shapes_export.py "
            "(mode-shape d3plot + VTK) and tools/modal_random_response.py "
            "(response PSD / RMS / Dirlik fatigue per the deck's D3PSD band, "
            "PSD curve and S-N data). See the README modal section.")
    else:
        state.warn(
            f"NOTE: {listing}: no OpenRadioss equivalent, and the deck is not "
            "a modal (*CONTROL_IMPLICIT_EIGENVALUE) deck - the offline "
            "random-vibration post-processing (tools/modal_random_response.py)"
            " needs the modal solution, so these requests produce no output "
            "here.")
    lines = [
        "#-  FREQUENCY-DOMAIN REQUESTS (no OpenRadioss equivalent - handled OFFLINE):",
    ]
    for w in what:
        lines.append(f"#-    {w}")
    lines += [
        "#-  Results come from the offline modal chain: tools/modal_solve.py ->",
        "#-  tools/modal_shapes_export.py (mode shapes for LS-PrePost/ParaView) ->",
        "#-  tools/modal_random_response.py (PSD / RMS / Dirlik fatigue).",
        HDR,
    ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: skipped keyword comment block
# ─────────────────────────────────────────────────────────────────────────────

def _make_skipped_comment(state: ConversionState) -> List[str]:
    if not state.skipped_keywords:
        return []
    unique = sorted(set(state.skipped_keywords))
    lines = ["#", "# -- SKIPPED (unsupported) keywords --"]
    for kw in unique:
        lines.append(f"#-- SKIPPED: *{kw}")
    lines.append("#")
    return lines


def _make_eig(state: ConversionState) -> List[str]:
    """*CONTROL_IMPLICIT_EIGENVALUE → /EIG (normal-modes request) — opt-in.

    Emitted only with ``--eig`` (options.emit_eig): the open-source OpenRadioss
    engine cannot solve /EIG (the eigensolver kernel is not in the source
    release — the engine segfaults at init the moment NEIG>0), so /EIG output is
    reserved for commercial Altair Radioss users. The default modal conversion
    uses the stiffness-export recipe instead (see _make_engine_modal).

    grnd_ID=0 → modes of the whole structure AS constrained by the model's /BCS;
    grnd_bc=0 → ITYP=1 free eigenmodes (no extra interface static modes). The
    actual eigensolve is driven by /IMPL/LINEAR in the engine. Cutfreq/Freqmin
    stay 0 (engine default shift / no upper cutoff) unless the deck gave a finite
    frequency window.
    """
    eig = state.ctrl_implicit_eig
    if not state.is_modal or eig is None or not state.options.emit_eig:
        return []
    nmod = eig.neig or 100
    eig_id = state.next_id()
    return [
        HDR,
        "#-  EIGENVALUE / MODAL REQUEST (*CONTROL_IMPLICIT_EIGENVALUE):",
        f"/EIG/{eig_id}",
        "modal_eigenvalue_analysis",
        "#  grnd_ID   grnd_bc    Trarot     Ifile",
        "         0         0   000 000         0",
        "#     Nmod     Inorm             Cutfreq             Freqmin",
        f"{_i(nmod)}{_i(0)}{_f(eig.cutfreq)}{_f(eig.freqmin)}",
        "#    Nbloc      Incv     Niter      Ipri                 Tol",
        f"{_i(0)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}",
        HDR,
    ]


def _make_starter_th_inter(state: ConversionState) -> List[str]:
    """Emit /TH/INTER so contact-interface forces reach the T01 time-history file.

    Two requesters share the block:
      * *CONTACT_FORCE_TRANSDUCER → /INTER/SUB: a sub-interface's force is
        written as a channel of its parent interface, so the parent interface
        must be requested in a /TH/INTER block.
      * *DATABASE_NCFORC (nodal contact forces): OpenRadioss has no per-node
        contact-force time history (no /TH/NODE contact variable exists), so
        the request maps to the per-interface force resultants of EVERY
        converted contact interface here (T01, /TFILE frequency); the
        nodal-resolution view is the contact-force/pressure animation vectors
        /ANIM/VECT/CONT + /ANIM/VECT/PCONT the engine deck already carries.
      * *DATABASE_RCFORC (contact resultant forces): the direct equivalent of
        a /TH/INTER channel — LS-DYNA's rcforc is the per-contact force
        resultant, so every converted interface is listed here too.
    Only emitted when a transducer, *DATABASE_NCFORC or *DATABASE_RCFORC
    exists, so other decks are unchanged.
    """
    all_inter_ids = ([c.inter_id for c in state.contacts_single]
                     + [c.inter_id for c in state.contacts_surf2surf]
                     + [c.inter_id for c in state.contacts_general]
                     + [c.inter_id for c in state.contacts_tied])
    want_ncforc = bool(state.db_ncforc_dt) and bool(all_inter_ids)
    want_rcforc = bool(state.db_rcforc_dt) and bool(all_inter_ids)
    if state.db_ncforc_dt and not all_inter_ids:
        state.warn(
            "*DATABASE_NCFORC requested but no *CONTACT was converted — "
            "there is no interface to output (no /TH/INTER emitted).")
    if state.db_rcforc_dt and not all_inter_ids:
        state.warn(
            "*DATABASE_RCFORC requested but no *CONTACT was converted — "
            "there is no interface to output (no /TH/INTER emitted).")
    if not state.th_sub_ids and not want_ncforc and not want_rcforc:
        return []
    # List the parent interface (total contact force) and each force-transducer
    # sub-interface id — a sub-interface is written to the T01 only when its own
    # id is requested here (listing just the parent leaves OUTPUT TO TH = 0).
    ids: List[int] = []
    if state.th_sub_ids:
        parent_id = _select_parent_interface(state)
        if parent_id is not None:
            ids.append(parent_id)
        ids += [sid for sid, _ in state.th_sub_ids]
    if want_ncforc:
        state.warn(
            "*DATABASE_NCFORC (nodal contact forces): OpenRadioss has no "
            "per-node contact-force time history — mapped to /TH/INTER force "
            "resultants for every converted contact interface (T01 file, "
            "/TFILE frequency). The per-node field is in the animation "
            "vectors /ANIM/VECT/CONT + /ANIM/VECT/PCONT (at the /ANIM/DT "
            "frequency), which the engine deck emits by default.")
        ids += [i for i in all_inter_ids if i not in ids]
    if want_rcforc:
        state.warn(
            "*DATABASE_RCFORC (contact interface resultant forces): mapped to "
            "/TH/INTER force resultants for every converted contact interface "
            "(T01 file, /TFILE frequency). This is the direct equivalent — "
            "LS-DYNA's rcforc reports the master/slave force resultant per "
            "contact, which is what an OpenRadioss /TH/INTER channel carries.")
        ids += [i for i in all_inter_ids if i not in ids]
    if not ids:
        return []
    lines = [
        "#-  TIME HISTORY (interface / force-transducer):", HDR,
        "/TH/INTER/1",
        "TH_interface_forces",
        "#     var1",
        "DEF",
    ]
    lines += [_i(i) for i in ids]
    lines.append(HDR)
    return lines


def _make_starter_th_node_reac(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Emit /TH/NODE writing reaction + displacement on the master node of each
    displacement-/velocity-controlled rigid body.

    Under displacement control the reaction at the imposed-motion node IS the
    load being 'measured' (the force the structure pushes back with). For a rigid
    body that reaction is assembled at the /RBODY master node, so REACX/Y/Z there
    gives the applied force vs. the imposed DX/Y/Z. This complements the
    /INTER/SUB force transducer as an independent reaction readout. Only emitted
    when a *BOUNDARY_PRESCRIBED_MOTION_RIGID exists, so other decks are unchanged.
    """
    if not state.prescribed_motions:
        return []
    nodes: List[int] = []
    seen: Set[int] = set()
    for pm in state.prescribed_motions:
        info = rbody_info.get(pm.pid)
        if not info:
            continue
        nd = info["ind_node"]
        if nd not in seen:
            seen.add(nd)
            nodes.append(nd)
    if not nodes:
        return []
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (imposed-motion reaction force on rigid-body master):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_reaction",
        "#  reaction (REACX/Y/Z) + displacement (DX/Y/Z) of the master node",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in ("DX", "DY", "DZ", "REACX", "REACY", "REACZ")),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines


def _make_starter_th_surf(state: ConversionState) -> List[str]:
    """*DATABASE_BINARY_BLSTFOR → /TH/SURF (P, A) on each blast-loaded surface.

    LS-DYNA's blstfor binary database records the blast pressure applied to
    the *LOAD_BLAST_SEGMENT[_SET] segments over time. OpenRadioss has no
    per-segment binary equivalent, but /LOAD/PBLAST feeds three outputs that
    together carry the same information (engine pblast_1.F):
      * /TH/SURF on the loaded /SURF/SEG — the P channel is the surface-
        average external pressure, A the loaded area (P*A = total blast
        force), written to the T01 at the /TFILE frequency;
      * /ANIM/NODA/PEXT — the nodal blast-pressure fringe (the spatial
        pressure field the blstfor file is fringed for in LS-PrePost);
      * /ANIM/VECT/FEXT — the external (blast) nodal force vectors.
    The two /ANIM options are added engine-side at the /ANIM/DT frequency.
    Emitted only when the deck requests *DATABASE_BINARY_BLSTFOR, so other
    decks are unchanged.
    """
    if not state.db_blstfor_dt:
        return []
    if not state.blast_surf_ids:
        state.warn(
            "*DATABASE_BINARY_BLSTFOR requested but no blast-loaded surface "
            "was emitted (no /LOAD/PBLAST) — there is no blast pressure to "
            "output (no /TH/SURF emitted).")
        return []
    state.warn(
        "*DATABASE_BINARY_BLSTFOR: no binary blast database exists in "
        "OpenRadioss — mapped to /TH/SURF (P = average blast pressure, "
        "A = loaded area; T01 at the /TFILE frequency) on the /LOAD/PBLAST "
        "surface plus /ANIM/NODA/PEXT (nodal pressure fringe) and "
        "/ANIM/VECT/FEXT (external force vectors) at the /ANIM/DT frequency.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_BINARY_BLSTFOR -> blast surface pressure):", HDR,
        f"/TH/SURF/{th_id}",
        "TH_blast_surf",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "#     var1      var2",
        "".join(v.rjust(10) for v in ("P", "A")),
    ]
    lines += [_i(sid) for sid, _title in state.blast_surf_ids]
    lines.append(HDR)
    return lines


def _spc_constrains_rotations(state: ConversionState) -> bool:
    """True when any SPC constrains a rotational DOF — gates the REACXX/YY/ZZ
    /TH channels and the /ANIM/VECT/MREAC moment vectors.

    Both /BCS sources count: *BOUNDARY_SPC_* (state.bcs_spcs) and the
    *CONSTRAINED_NODAL_RIGID_BODY_SPC option (state.cnrb_spc_bcs), whose
    rotational mask is the emitted "111"-style rot field."""
    if any(bc.dofrx or bc.dofry or bc.dofrz for bc in state.bcs_spcs):
        return True
    return any(bc.rot != "000" for bc in state.cnrb_spc_bcs)


def _make_starter_th_node_spc(state: ConversionState, rbody_info: Dict) -> List[str]:
    """*DATABASE_SPCFORC → /TH/NODE with REACX/Y/Z (+REACXX/YY/ZZ) on every
    /BCS-constrained node.

    LS-DYNA's spcforc file lists the SPC reaction force (and, for rotational
    constraints, moment) per constrained node. OpenRadioss computes exactly
    that when reaction output is requested: /TH/NODE REAC* (or /ANIM/VECT/
    FREAC) switches the engine's constraint-reaction assembly on (engine
    reactions.F), so REACX/Y/Z on the /BCS node groups IS the spcforc
    content, written to the T01 at the /TFILE frequency. Rigid-body member
    nodes are mapped to the /RBODY master node — the /BCS acts there and the
    reaction is assembled there. The whole-model nodal-field view is added
    engine-side as /ANIM/VECT/FREAC (+MREAC). Emitted only when the deck
    requests *DATABASE_SPCFORC, so other decks are unchanged.
    """
    if not state.db_spcforc_dt:
        return []
    if not state.bcs_spcs and not state.cnrb_spc_bcs:
        state.warn(
            "*DATABASE_SPCFORC requested but the deck SPC-constrains no node "
            "(no *BOUNDARY_SPC_* and no *CONSTRAINED_NODAL_RIGID_BODY_SPC) — "
            "there is no reaction to output (no /TH/NODE emitted).")
        return []
    node_to_ind = {}
    for pid, info in rbody_info.items():
        for node in info["nodes"]:
            node_to_ind[node] = info["ind_node"]
    mapped: Set[int] = set()
    for bc in state.bcs_spcs:
        for n in state.node_sets.get(bc.nsid, ("", []))[1]:
            mapped.add(node_to_ind.get(n, n))
    # *CONSTRAINED_NODAL_RIGID_BODY_SPC: the /BCS acts directly on the /RBODY
    # master node, which is where the engine assembles the reaction — so the
    # master node IS the spcforc node, no set expansion needed.
    for cbc in state.cnrb_spc_bcs:
        mapped.add(cbc.ind_node)
    nodes = sorted(mapped)
    if not nodes:
        state.warn(
            "*DATABASE_SPCFORC: every *BOUNDARY_SPC node set is empty — "
            "no /TH/NODE reaction output emitted.")
        return []
    if len(nodes) > 1000:
        state.warn(
            f"*DATABASE_SPCFORC: {len(nodes)} SPC-constrained nodes get REAC* "
            "/TH channels (matching LS-DYNA's per-node spcforc output) — the "
            "T01 file will be correspondingly large. Trim the /TH/NODE block "
            "by hand if you only need a subset.")
    th_vars = ["REACX", "REACY", "REACZ"]
    if _spc_constrains_rotations(state):
        th_vars += ["REACXX", "REACYY", "REACZZ"]
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_SPCFORC -> SPC reaction force per /BCS node):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_spc_reactions",
        "#  reaction force (REACX/Y/Z) [+ moment (REACXX/YY/ZZ)] per constrained node",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in th_vars),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines
