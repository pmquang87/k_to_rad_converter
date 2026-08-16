"""Starter header/title/analysis cards, time-history outputs, /EIG, notes and skipped-keyword comment."""

from __future__ import annotations

from typing import Dict, List, Set
from ..state import ConversionState
from .common import (
    HDR, _f, _i, _split_shell_eids_by_topology, _spotweld_beam_pids,
)
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
    "_spotweld_solid_pids",
    "_make_starter_th_swforc",
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
    """*DATABASE_HISTORY_* → /TH/<type>.

    A *DATABASE_HISTORY_SHELL request has to be split by element topology:
    since d1ade12 a 3-corner shell is emitted as /SH3N, and /TH/SHEL resolves
    only 4-node /SHELL ids, so a triangle named there is silently absent from
    the T01 instead of being recorded. Those ids go to /TH/SH3N.
    """
    if not state.db_histories:
        return []
    lines = ["#-  TIME HISTORY OUTPUTS:", HDR]
    counter = 1
    type_map = {"SHELL": "SHEL", "SOLID": "BRIC", "NODE": "NODE"}

    def _emit_block(rad_type: str, ids: List[int], n: int) -> List[str]:
        block = [
            f"/TH/{rad_type}/{n}",
            f"TH_{rad_type}_{n}",
            "#     var1      var2",
            "DEF       ",
        ]
        for eid in ids:
            block.append(_i(eid))
        return block

    for dbh in state.db_histories:
        rad_type = type_map.get(dbh.db_type, dbh.db_type)
        if dbh.db_type == "SHELL":
            quad_ids, tri_ids = _split_shell_eids_by_topology(state, dbh.ids)
            if quad_ids:
                lines += _emit_block("SHEL", quad_ids, counter)
                counter += 1
            if tri_ids:
                lines += _emit_block("SH3N", tri_ids, counter)
                counter += 1
            continue
        lines += _emit_block(rad_type, dbh.ids, counter)
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


# ─────────────────────────────────────────────────────────────────────────────
# /TH/NODE REAC* is an accumulated impulse — shared warning text
# ─────────────────────────────────────────────────────────────────────────────
#
# Two independent conversion paths emit REACX/Y/Z channels and both have to
# say that those channels are integrated, not instantaneous:
#   * *DATABASE_SPCFORC          → _make_starter_th_node_spc  (the SPC reaction
#                                  readout that stands in for LS-DYNA's spcforc)
#   * *BOUNDARY_PRESCRIBED_MOTION_RIGID
#                                → _make_starter_th_node_reac (the imposed-motion
#                                  reaction readout, TH_reaction)
# Sources for the claim (verified, PR #93): engine/source/output/
# reaction_forces_th.F:60-62 accumulates ``FTHREAC = FTHREAC + IFLAG*MS*A*DT12``,
# the only ``FTHREAC = ZERO`` in the engine is engine/source/engine/resol.F:1901
# which runs BEFORE the explicit iteration-loop head at :2612 (back edge
# ``GOTO 100`` at :9294), and engine/source/output/th/thnod.F:178-208 writes the
# accumulator out undivided.
_REAC_IMPULSE_PHYSICS = (
    "the OpenRadioss REAC* channels are a time-ACCUMULATED reaction impulse "
    "(force x time), not an instantaneous force — the engine adds m*a*dt every "
    "cycle (reaction_forces_th.F:60-62) and zeroes the accumulator only once, "
    "before the iteration loop (resol.F:1901, loop head :2612)."
)
# Shown instead of the full derivation when this deck already carried it, so a
# deck that triggers BOTH paths does not repeat three identical sentences.
_REAC_IMPULSE_BACKREF = (
    "the REAC* channels are a time-ACCUMULATED reaction impulse (force x time), "
    "not an instantaneous force — same reaction_forces_th.F accumulation as the "
    "other REAC* warning on this deck."
)


def _warn_reac_impulse(state: ConversionState, lead: str, action: str) -> None:
    """Warn that a just-emitted REAC* block carries an impulse, not a force.

    ``lead`` names the conversion path, ``action`` is what the user must
    actually do with the column — that sentence differs between the two callers
    (compare against an LS-DYNA spcforc file vs. build a force-vs-displacement
    curve) and is therefore ALWAYS emitted in full. Only the shared
    engine-source derivation is deduplicated: the first caller on a deck writes
    it out, a second caller gets a back-reference to it. Both variants still
    contain the words "impulse", "d(REAC)/dt" and "reaction_forces_th.F", so a
    grep-style check on either warning behaves the same whichever fired first.
    """
    if state.reac_impulse_warned:
        physics = _REAC_IMPULSE_BACKREF
    else:
        physics = _REAC_IMPULSE_PHYSICS
        state.reac_impulse_warned = True
    state.warn(f"{lead}: {physics} {action}")


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
      * *DATABASE_RCFORC (contact resultant forces): the closest equivalent of
        a /TH/INTER channel — LS-DYNA's rcforc is the per-contact force
        resultant, so every converted interface is listed here too.
    Only emitted when a transducer, *DATABASE_NCFORC or *DATABASE_RCFORC
    exists, so other decks are unchanged.

    **The DEF channels FNX/Y/Z and FTX/Y/Z are a time-ACCUMULATED contact
    IMPULSE, not a force** — the same defect class as /TH/NODE REAC*
    (_make_starter_th_node_spc below), and it is why an rcforc comparison needs
    differentiating first. The engine says so itself:
    engine/source/interfaces/int07/i7for3.F:1443 heads the block
    ``SAUVEGARDE DE L'IMPULSION NORMALE`` ("save the normal impulse") and
    :1459-1476 accumulates ``IMPX = F*DT12`` into FSAV(1..3), with the
    tangential half at :3055-3079; /INTER/SUB channels take the same path
    (:1559-1561). engine/source/output/th/thkin.F:56 copies FSAV into the T01
    buffer with no division by time.

    Nothing resets it on the rank that writes: hist2.F:616-622 zeroes FSAV only
    ``IF (ISPMD/=0)`` — i.e. on the non-master ranks after their contribution
    has been summed into the master — and sortie_main.F:1945, under its own
    heading ``TRAITEMENT SUR FSAV NON CUMULE`` ("handling of the NON-cumulated
    FSAV"), resets only the monvol block, FSAV(26) (contact elastic energy) and
    FSAV(29) (CAREA). The force columns are absent from that list precisely
    because they ARE cumulated. So on np=1 the channel is integral(F dt) since
    t=0 and carries force x time units.

    The instantaneous force is d(FNX)/dt — tools/th_to_csv.py writes that
    column. This supersedes the older "multiply by 2" folklore recorded on the
    force-transducer path (writer/contacts.py): the factor between the raw
    channel and the force is the elapsed accumulation time, not a constant.
    """
    # Parsed contacts MINUS the ones the writers refused to emit. A contact
    # whose side resolves to nothing is dropped with a loud warning, but its
    # record stays in state — listing it here is starter WARNING 257
    # "NONEXISTENT INTER <id>" on a deck that otherwise converts clean, and the
    # channel does not exist either way. All four contact writers run before
    # this section, so state.dropped_inter_ids is complete.
    all_inter_ids = [c.inter_id for c in (
        list(state.contacts_single) + list(state.contacts_surf2surf)
        + list(state.contacts_general) + list(state.contacts_type25)
        + list(state.contacts_tied) + list(state.contacts_spotweld))
        if c.inter_id not in state.dropped_inter_ids]
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
            "/TH/INTER resultants for every converted contact interface "
            "(T01 file, /TFILE frequency). LS-DYNA's rcforc reports the "
            "master/slave force resultant per contact; the /TH/INTER channel "
            "is the same quantity integrated over time — see the impulse "
            "warning below.")
        ids += [i for i in all_inter_ids if i not in ids]
    if not ids:
        return []
    # The units differ from LS-DYNA's, so say so on every deck that gets the
    # block. Same failure mode as the /TH/NODE REAC* channels: plotting the raw
    # column against an rcforc curve compares an impulse with a force, and
    # nothing anywhere reports an error.
    state.warn(
        "/TH/INTER FNX/Y/Z + FTX/Y/Z (contact interface forces): these "
        "channels are a time-ACCUMULATED contact IMPULSE (force x time), not "
        "an instantaneous force — the engine adds F*dt every cycle "
        "(i7for3.F:1459-1476, under its own comment 'SAUVEGARDE DE "
        "L'IMPULSION NORMALE') and never resets the accumulator on the rank "
        "that writes the T01 (hist2.F:616-622 zeroes FSAV only for ISPMD/=0; "
        "sortie_main.F:1945 resets only monvol, FSAV(26) and FSAV(29)). "
        "Differentiate with respect to time (F = d(FNX)/dt, e.g. "
        "numpy.gradient, or tools/th_to_csv.py which writes the differentiated "
        "column) before comparing against an LS-DYNA rcforc/ncforc file.")
    # The TH group id namespace is GLOBAL across /TH types, not per type: the
    # starter rejects a deck carrying both /TH/NODE/1 and /TH/INTER/1 with
    # "ERROR ID : 79 / DUPLICATE ID / IN TH GROUP DEFINITION / ID=1 is
    # DUPLICATED" and writes NO RESTART FILE, so the engine cannot run at all.
    # This id used to be the literal 1, which collides with the first block
    # _make_starter_th numbers off its own 1..N counter (:111) — so any deck
    # asking for both a *DATABASE_HISTORY_* and a *DATABASE_RCFORC /
    # *DATABASE_NCFORC / *CONTACT_FORCE_TRANSDUCER died at the starter while
    # the conversion itself reported success. Every other /TH emitter already
    # draws from next_id() (_make_starter_th_node_reac, _make_starter_th_surf,
    # _make_starter_th_node_spc below; inistate._make_starter_th_sectio;
    # the /TH/RWALL in loads) — this was the one hard-coded id.
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (interface / force-transducer):", HDR,
        f"/TH/INTER/{th_id}",
        "TH_interface_forces",
        "#  DEF = FNX/Y/Z + FTX/Y/Z: contact IMPULSE (force x time), not force",
        "#  FSAV accumulates F*dt every cycle: contact force = d(FNX)/dt",
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
    is the readout of the applied load vs. the imposed DX/Y/Z. This complements
    the /INTER/SUB force transducer as an independent reaction readout. Only
    emitted when a *BOUNDARY_PRESCRIBED_MOTION_RIGID exists, so other decks are
    unchanged.

    **REACX/Y/Z is a time-accumulated reaction IMPULSE, not the instantaneous
    force** — see _make_starter_th_node_spc below for the engine source lines.
    The applied force is the time derivative of the plotted channel,
    F(t) = d(REAC)/dt; the DX/Y/Z channels alongside it are ordinary
    displacements and need no such treatment. So a force-vs-displacement curve
    has to be built from numpy.gradient(reac, t) against DX, not from REAC
    against DX. This path raises its own warning (_warn_reac_impulse): the
    *DATABASE_SPCFORC one does not cover it — a deck can have imposed motion
    and no *DATABASE_SPCFORC at all, and this block is the one that puts a
    reaction channel and a displacement channel side by side, which is the
    shape that invites the wrong plot.
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
    # This block pairs REACX/Y/Z with DX/Y/Z on the same node, which is exactly
    # the shape of a force-vs-displacement extraction — and exactly the plot
    # that silently goes wrong if REAC is used raw. The deck comment says so,
    # but a comment inside a .rad file is only read by someone who opens the
    # .rad file; the conversion log is what the engineer actually reads.
    _warn_reac_impulse(
        state,
        "*BOUNDARY_PRESCRIBED_MOTION_RIGID -> /TH/NODE TH_reaction "
        "(REACX/Y/Z next to DX/Y/Z on the rigid-body master node)",
        "Build the force-vs-displacement curve from numpy.gradient(reac, t) "
        "(F = d(REAC)/dt) against DX/Y/Z, not from REAC against DX/Y/Z — "
        "tools/th_to_csv.py writes that differentiated column for you. The raw "
        "channel rises monotonically under a steady load, so an untreated "
        "REAC-vs-DX curve has a meaningless slope and a meaningless enclosed "
        "area (it is not the work done). The DX/Y/Z channels alongside it are "
        "ordinary displacements and need no such treatment.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (imposed-motion reaction impulse on rigid-body master):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_reaction",
        "#  reaction IMPULSE (REACX/Y/Z) + displacement (DX/Y/Z) of the master node",
        "#  REAC* accumulates m*a*dt over the run: reaction force = d(REAC*)/dt",
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
      * /TH/SURF on the loaded /SURF/SEG — P is the blast pressure and A the
        loaded area, written to the T01 at the /TFILE frequency (but read the
        caveat below before doing arithmetic with them);
      * /ANIM/NODA/PEXT — the nodal blast-pressure fringe (the spatial
        pressure field the blstfor file is fringed for in LS-PrePost);
      * /ANIM/VECT/FEXT — the external (blast) nodal force vectors.
    The two /ANIM options are added engine-side at the /ANIM/DT frequency.
    Emitted only when the deck requests *DATABASE_BINARY_BLSTFOR, so other
    decks are unchanged.

    **P and A are per-/TFILE-interval aggregates, and P*A is NOT the blast
    force.** Both are accumulated per cycle and reset at every TH write, so
    neither is a snapshot:

      * pblast_1.F:418-419 (and :468-469 / :506-507 for the other two blast
        models) adds ``AREA*P`` into channel 4 and ``AREA`` into channel 5 on
        every cycle — these are ``th_surf%channels``, which resol.F:3447 passes
        as the ``FSAVSURF`` dummy argument, so the two names are one array;
      * hist2.F:688 then divides channel 4 by channel 5 right before the write
        ("The pressure in an average pressure");
      * sortie_main.F:1976-1982 zeroes channels 1-5 after every TH write.

    So **P** is the area-weighted MEAN pressure over the /TFILE interval — not
    the instantaneous value, and a peak that falls between two TH writes is
    averaged away. **A** is the loaded area multiplied by the NUMBER OF CYCLES
    in the interval, so it only equals the loaded area when the T01 is written
    every cycle; ``P*A`` is inflated by that same cycle count. Use /TFILE close
    to the timestep if the peak matters, and take the total blast force from
    /ANIM/VECT/FEXT rather than from P*A.

    Because these are interval aggregates rather than a running integral,
    differentiating them (the fix for the REAC* and /TH/INTER channels) is
    meaningless — tools/th_to_csv.py deliberately leaves /TH/SURF alone and
    prints this caveat instead.

    **Multiple ids in ONE block are legal and correct** (starter
    hm_read_thgrsurf.F flags each id; engine thsurf.F writes one P/A pair per
    listed surface) — but on an SPMD (MPI) run the engine only reduces the
    first 5*NSURF of the 6*NSURF /TH/SURF channel elements across domains
    (hist2.F:679), which silently zeroes the highest-indexed surfaces. The
    deck-shape fix lives in assembly._pad_surfaces_for_spmd_th_surf, which
    runs after all sections are assembled and appends inert padding /SURF
    cards so every surface listed here stays inside the reduced prefix.
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
        "OpenRadioss — mapped to /TH/SURF (P, A; T01 at the /TFILE frequency) "
        "on the /LOAD/PBLAST surface plus /ANIM/NODA/PEXT (nodal pressure "
        "fringe) and /ANIM/VECT/FEXT (external force vectors) at the /ANIM/DT "
        "frequency.")
    state.warn(
        "/TH/SURF P and A are per-/TFILE-interval AGGREGATES, not snapshots: "
        "the engine adds AREA*P and AREA every cycle (pblast_1.F:418-419), "
        "divides P by A just before writing (hist2.F:688) and zeroes both "
        "after every TH write (sortie_main.F:1976-1982). So P is the MEAN "
        "pressure over the output interval — a peak falling between two writes "
        "is averaged away — and A is the loaded area times the NUMBER OF "
        "CYCLES in that interval, so P*A is NOT the blast force. Put /TFILE "
        "near the timestep if the peak matters, and take the total blast force "
        "from /ANIM/VECT/FEXT.")
    th_id = state.next_id()
    lines = [
        "#-  TIME HISTORY (*DATABASE_BINARY_BLSTFOR -> blast surface pressure):", HDR,
        f"/TH/SURF/{th_id}",
        "TH_blast_surf",
        "#  P = MEAN pressure over the /TFILE interval; A = loaded area x cycles",
        "#  both are reset at every TH write: P*A is NOT the blast force",
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
    that constraint reaction when reaction output is requested: /TH/NODE REAC*
    (or /ANIM/VECT/FREAC) switches the engine's constraint-reaction assembly on
    (engine reactions.F), and it is assembled on the /BCS nodes — so REACX/Y/Z
    on the /BCS node groups is the right channel on the right nodes, written to
    the T01 at the /TFILE frequency. Rigid-body member nodes are mapped to the
    /RBODY master node — the /BCS acts there and the reaction is assembled
    there. Emitted only when the deck requests *DATABASE_SPCFORC, so other
    decks are unchanged.

    **The REAC* channel is a time-accumulated reaction IMPULSE, not an
    instantaneous force — it is NOT numerically interchangeable with an
    LS-DYNA spcforc column.** engine/source/output/reaction_forces_th.F does

        FTHREAC(k,NODREAC(N)) = FTHREAC(k,NODREAC(N))
                              + IFLAG * MS(N)*A(k,N)*DT12

    i.e. it adds mass x acceleration x timestep, not mass x acceleration. It is
    called twice per cycle, IFLAG=-1 before the kinematic conditions are applied
    and IFLAG=+1 after (resol.F:7304 / :7386), so the per-cycle increment is the
    reaction m*(A - A~) times dt. Nothing ever resets it: the only
    ``FTHREAC = ZERO`` in the whole engine is resol.F:1901, which runs *before*
    the explicit iteration loop head at resol.F:2612 (back edge ``GOTO 100`` at
    :9294). thnod.F:178-208 then writes FTHREAC straight into TH channels
    620-625 with no division by time. The channel therefore rises monotonically
    under a steady load and carries force x time units (N*s in SI, mN*ms in the
    ton/mm/s system).

    reaction_forces_th.F is not the only accumulation site, and the /BCS one
    matters most here because these channels sit on /BCS nodes. The SPC path
    engine/source/output/th/bcs1th.F (called from thbcs.F) does the same thing
    for the constrained DOFs:

        FTHREAC(1..3,NODREAC(L)) += FTHREAC0(1..3) * MS(L) * DT12   (:143-148)
        FTHREAC(4..6,NODREAC(L)) += FTHREAC0(4..6) * IN(L) * DT12   (:150-155)

    so REACXX/YY/ZZ are ANGULAR impulses (moment x time, nodal inertia IN in
    place of the mass), not moments. The /ANIM counterpart in the same file
    accumulates the identical algebra with NO dt factor —
    ``FANREAC(1..6,L) += FANREAC0(1..6) * MS(L)/IN(L)`` (bcs1th.F:281-287) —
    which is the /BCS-path twin of the reactions.F:328 contrast below. On the
    IMPLICIT path the integration is trapezoidal rather than rectangular,
    ``FTHREAC -= (A + A_prev)*DT3/2`` (bcs1th_imp.F:46-56), but it is still an
    integral over time: no solver path writes an instantaneous /TH reaction.

    **How to read it:** the spcforc-equivalent force is the time derivative of
    the plotted channel, F(t) = d(REAC)/dt — ``numpy.gradient(reac, t)`` on the
    T01 column, or a least-squares slope over a window where the reaction is
    steady. Measured on a settled column+block deck of total weight
    3.850425 N: REACY ramps linearly (0.0735 N*s at t=0.03 to 1.1178 N*s at
    t=0.30) and the least-squares slope over t >= 0.15 is 3.8504181 N, which is
    -0.0002% off the analytic weight. A raw REAC* value on its own is
    meaningless as a force and grows without bound as the run gets longer.

    The instantaneous force is available as a nodal *field* instead: the
    engine-side /ANIM/VECT/FREAC (+MREAC) this writer also emits really is a
    force — reactions.F:328 finalizes ``FREAC = MS*A - FREAC`` every cycle, with
    no DT12 factor and no accumulation across cycles. FREAC and FTHREAC are
    separate arrays with deliberately different semantics; only the /TH one is
    integrated.
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
    # The units differ from LS-DYNA's, so say so on every converted deck: an
    # engineer who plots the T01 REAC* column against an spcforc curve gets a
    # monotonically rising line instead of a force, with no error anywhere.
    _warn_reac_impulse(
        state,
        "*DATABASE_SPCFORC -> /TH/NODE REACX/Y/Z",
        "Differentiate the T01 columns with respect to time "
        "(F = d(REAC)/dt, e.g. numpy.gradient(reac, t), or tools/th_to_csv.py "
        "which writes the differentiated column for you) before comparing them "
        "against an LS-DYNA spcforc file. The instantaneous force is available "
        "as the nodal field /ANIM/VECT/FREAC, which is also emitted.")
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
        "#-  TIME HISTORY (*DATABASE_SPCFORC -> SPC reaction impulse per /BCS node):", HDR,
        f"/TH/NODE/{th_id}",
        "TH_spc_reactions",
        "#  reaction IMPULSE (REACX/Y/Z) [+ angular impulse (REACXX/YY/ZZ)] per constrained node",
        "#  REAC* accumulates m*a*dt over the run: spcforc force = d(REAC*)/dt",
        # TH variable names are read in fixed 10-char columns (not free-format),
        # so each keyword must occupy its own field.
        "".join(v.rjust(10) for v in th_vars),
    ]
    lines += [_i(nd) for nd in nodes]
    lines.append(HDR)
    return lines


def _spotweld_solid_pids(state: ConversionState) -> Set[int]:
    """*MAT_SPOTWELD (MAT_100) parts that carry SOLID elements — the hex/nugget
    welds. Complement of _spotweld_beam_pids, which claims the beam-only MAT_100
    parts for the /PROP/TYPE13 spring path; a MAT_100 solid part falls back to
    /MAT/ELAST and its weld behaviour comes from a /CLUSTER instead."""
    if not state.mat_spotweld:
        return set()
    solid_pids = {e.pid for e in state.solid_elems}
    return {pid for pid, p in state.parts.items()
            if p.mid in state.mat_spotweld and pid in solid_pids}


def _make_starter_th_swforc(state: ConversionState) -> List[str]:
    """*DATABASE_SWFORC → /TH/SPRING (beam welds) + /TH/BRIC (solid welds).

    swforc is LS-DYNA's spot-weld force database. dyna2rad answers it with two
    blocks, both keyed on parts whose material is a *MAT_SPOTWELD
    (dyna2rad.cxx:613-695 — "SWFORC" appears TWICE in ``dbCardList``):

      * i=3: *ELEMENT_DISCRETE / *ELEMENT_BEAM  → /TH/SPRING
      * i=4: *ELEMENT_SOLID                     → /TH/BRIC

    k2rad's MAT_100 beam welds are /SPRING elements that keep their LS-DYNA
    *ELEMENT_BEAM ids VERBATIM (writer/loads.py _make_spotweld_beam_connectors
    writes ``sprg_ID = e.eid`` under a ``/SPRING/<original PID>``), so the ids
    listed here are exactly the ones the deck used and a channel maps 1:1 onto
    an LS-DYNA swforc row. Solid weld ids are likewise verbatim.

    The third block, /TH/CLUSTER over the *DEFINE_HEX_SPOTWELD_ASSEMBLY welds,
    is emitted next to the clusters themselves (writer/loads.py
    _make_hex_spotweld_clusters), the way dyna2rad emits it from its hex-weld
    converter rather than from the database card.

    Variables: ``DEF FAIL`` for the springs. ``DEF`` alone is what dyna2rad
    asks for, and hm_read_thgrou.F:1518-1520 expands it to indices 1-14 + 65 =
    OFF FX FY FZ MX MY MZ LX LY LZ RX RY RZ IE LENGTH — index 66, ``FAIL``, is
    NOT in the group. On a weld that is the one channel the user came for (it
    is *the* thing swforc reports), so it is requested explicitly. /TH/BRIC has
    no FAIL variable at all, so it takes ``DEF``.

    Element ids go ONE PER LINE for both types: /TH/SPRING and /TH/BRIC are
    read by hm_read_thgrne.F (``elem_ID`` cols 1-10, optional name in 21-100),
    not by the ten-per-line hm_read_thgrki.F that /TH/CLUSTER uses.
    """
    if not state.db_swforc_dt:
        return []
    weld_pids = _spotweld_beam_pids(state)
    # Only the springs the connector writer ACTUALLY emitted. It `continue`s
    # over a whole MAT_100 part whose welds are zero-length, carry no
    # *SECTION_BEAM, or size to no cross-section area — emitting neither
    # /PROP/TYPE13 nor /SPRING while the beams stay in state.beam_elems. A
    # /TH/SPRING naming one of those ids is not a lost channel, it is starter
    # ERROR 69 ("TH ELEMENT SELECTION ID=n DOES NOT EXIST", hm_read_thgrne.F:189
    # MSGTYPE=MSGERROR) and the whole deck is refused — strictly worse than the
    # degraded-but-running deck the "welds NOT converted" warning describes.
    # state.spotweld_spring_eids is filled by _make_spotweld_beam_connectors,
    # which the section registry runs first (same ordering the /CLUSTER +
    # cluster_ids pair relies on).
    parsed_eids = sorted(b.eid for b in state.beam_elems if b.pid in weld_pids)
    spring_eids = [e for e in parsed_eids if e in state.spotweld_spring_eids]
    if len(spring_eids) != len(parsed_eids):
        lost = [e for e in parsed_eids if e not in state.spotweld_spring_eids]
        state.warn(
            f"*DATABASE_SWFORC: {len(lost)} *MAT_SPOTWELD beam weld(s) "
            f"(element id(s) {lost[:10]}{' ...' if len(lost) > 10 else ''}) "
            "have no /SPRING in the converted deck — their part was skipped by "
            "the connector writer (see its own warning for the cause: "
            "zero-length welds, a missing *SECTION_BEAM, or no cross-section "
            "area). Those swforc channels are LOST. They are left out of the "
            "/TH/SPRING on purpose: listing an element the deck never defines "
            "is starter ERROR 69 and the run would not start at all.")
    solid_pids = _spotweld_solid_pids(state)
    # EVERY solid on a MAT_100 part, with no topology screening. /TH/BRIC is
    # read over the whole solid array (hm_read_thgrou.F ITYP=1, NUMELS), so a
    # /TETRA4 or /TETRA10 id resolves there exactly like a /BRICK — verified on
    # a live starter run, 0 ERROR(S) with a TET4 in the list. (The /CLUSTER path
    # DOES screen tets, for a different reason: it reads the hex node ordering
    # to build the weld frame. Screening them here would silently drop a
    # requested channel.) A weld already covered by a /CLUSTER is still listed:
    # /TH/BRIC reports stress and internal energy, which the cluster's force
    # resultants do not.
    brick_eids = sorted(e.eid for e in state.solid_elems if e.pid in solid_pids)
    if not spring_eids and not brick_eids:
        if not state.cluster_ids:
            state.warn(
                "*DATABASE_SWFORC requested but this deck has no spot weld "
                "k2rad could output: no *MAT_SPOTWELD (MAT_100) beam or solid "
                "part was converted and there is no "
                "*DEFINE_HEX_SPOTWELD_ASSEMBLY. No /TH block is "
                "emitted (a /TH group listing nothing is a starter error). The "
                "dt is still honoured as the /TFILE frequency. If the welds in "
                "this deck are *CONSTRAINED_SPOTWELD ties, their springs are "
                "synthesized with generated ids and are not covered here — "
                "request them with *DATABASE_HISTORY_* instead.")
        return []
    lines = [
        "#-  TIME HISTORY (*DATABASE_SWFORC -> spot-weld forces, "
        f"dt={state.db_swforc_dt:g}):", HDR,
    ]
    if spring_eids:
        th_id = state.next_id()
        lines += [
            f"/TH/SPRING/{th_id}",
            f"TH_SPOTWELD_SPRINGS_{th_id}",
            "#     var1      var2",
            "DEF       FAIL      ",
        ]
        lines += [_i(e) for e in spring_eids]
        lines.append(HDR)
        state.warn(
            f"*DATABASE_SWFORC -> /TH/SPRING/{th_id} over {len(spring_eids)} "
            "*MAT_SPOTWELD beam weld(s), listed by their ORIGINAL LS-DYNA "
            "element id (the /PROP/TYPE13 connectors keep it), so a T01 "
            "channel maps 1:1 onto an swforc row. Variables DEF + FAIL: FAIL "
            "is the weld rupture flag and is NOT part of DEF "
            "(hm_read_thgrou.F:1519). Unlike the /TH/INTER and /TH/NODE REAC* "
            "channels these are INSTANTANEOUS forces (thres.F writes GBUF%FOR "
            "and GBUF%MOM with no dt) — no differentiation needed. READ THE "
            "WELD FORCE FROM THE T01, NOT FROM THE ANIMATION: measured on a "
            "live run, /ANIM/SPRING/FORC writes 0.00 N for /PROP/TYPE13 "
            "connectors that the T01 shows carrying 13.4 kN, so the A-files "
            "are not a usable weld-force source. Note also that a weld whose "
            "*ELEMENT_BEAM card gives no third node (N3=0, the usual case) has "
            "no transverse frame of its own: the starter says WARNING 327 and "
            "resolves DOFs 2/3/5/6 against global X. That is harmless while "
            "the weld is loaded along its axis and while NRS==NRT and "
            "MSS==MTT, but on a lap-shear weld with unequal transverse limits "
            "the failure directions are not the ones the deck named — give the "
            "beam an N3 if that matters.")
    if brick_eids:
        th_id = state.next_id()
        lines += [
            f"/TH/BRIC/{th_id}",
            f"TH_SPOTWELD_SOLIDS_{th_id}",
            "#     var1      var2",
            "DEF       ",
        ]
        lines += [_i(e) for e in brick_eids]
        lines.append(HDR)
        state.warn(
            f"*DATABASE_SWFORC -> /TH/BRIC/{th_id} over {len(brick_eids)} "
            "*MAT_SPOTWELD solid weld element(s) (dyna2rad's second SWFORC "
            "pass, dyna2rad.cxx:685-689). DEF gives OFF/SX..SXZ/IE/DENS/PLAS/"
            "TEMP — element STRESS, not the weld force resultant LS-DYNA's "
            "swforc prints. The resultant needs a /CLUSTER: add a "
            "*DEFINE_HEX_SPOTWELD_ASSEMBLY over the nugget and k2rad emits "
            "/CLUSTER/BRICK + /TH/CLUSTER with FX..MZ and FS/FN/MS/MN.")
    return lines
