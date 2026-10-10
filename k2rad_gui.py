#!/usr/bin/env python3
"""
k2rad_gui.py  –  A small Tkinter front-end for the LS-DYNA .k → OpenRadioss .rad
converter, so you can pick the input file and set options without typing the
full command line.

Run it with::

    python k2rad_gui.py

Leave every option in the "force-control implicit stabilization" box blank/off
for a standard conversion (identical to ``python k2rad.py model.k``). Fill them
in to reproduce a force-control recipe, e.g. the RB_pull elevator deck:
    Ground springs: on,  K = 100
    Auto Gapmin from mesh clearance: on,  factor = 0.8
    Soften Stfac: 0.3
which is the GUI equivalent of
    python k2rad.py model.k --ground-springs --auto-gapmin --gapmin-factor 0.8 --soften-stfac 0.3

Tick "Auto Gapmin from mesh clearance" to set each contact's Gapmin from the
measured minimum node distance between its two parts (= factor × clearance)
instead of hand-tuning it per mesh — the fix for a deck whose contacts were
tuned for one mesh (e.g. TET4) but re-run on a finer one (e.g. TET10). It is the
GUI equivalent of ``--auto-gapmin --gapmin-factor 0.8``.

Only the standard library is used (tkinter), matching the converter's zero
third-party-dependency policy. The conversion runs on a background thread so a
large mesh does not freeze the window.
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import traceback
from pathlib import Path

# tkinter is optional at *import* time so this module (and its pure helpers
# below) stay importable on a headless box without python3-tk — main() reports a
# clear error if the GUI itself is launched there.
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext
    from tkinter import font as tkfont
    _HAVE_TK = True
except ImportError:                                   # pragma: no cover
    _HAVE_TK = False

# Allow running as a loose script (python k2rad_gui.py) without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from k2rad import convert  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Pure input parsing (no tkinter — unit-tested)
# ─────────────────────────────────────────────────────────────────────────────

def parse_inter_gapmin(text: str) -> dict:
    """Parse a free-text "ID=VAL [ID=VAL ...]" string into {inter_id: gapmin}.

    Pairs may be separated by commas, semicolons, or whitespace/newlines so the
    field is forgiving to paste into. Raises ValueError with a clear message on
    a malformed pair.
    """
    text = (text or "").strip()
    if not text:
        return {}
    out: dict = {}
    for tok in re.split(r"[,;\s]+", text):
        if not tok:
            continue
        if "=" not in tok:
            raise ValueError(f"Gapmin override must be ID=VAL, got {tok!r}.")
        sid, _, sval = tok.partition("=")
        try:
            out[int(sid.strip())] = float(sval.strip())
        except ValueError:
            raise ValueError(
                f"Gapmin override ID and VAL must be numeric, got {tok!r}.")
    return out


def build_convert_kwargs(input_path: str, output_stem: str, units, *,
                         ground_springs: bool, ground_spring_k_text: str,
                         soften_stfac_text: str,
                         tie_stfac_text: str = "",
                         inter_gapmin_text: str = "",
                         tet10_to_tet4: bool = False,
                         auto_gapmin: bool = False,
                         gapmin_factor_text: str = "",
                         derived_gapmin: bool = False,
                         derived_gapmin_factor_text: str = "",
                         rigid_secondary_swap: bool = True,
                         deformable_to_rigid: bool = True,
                         fixpoint_count_text: str = "",
                         qstat_dtscal_text: str = "",
                         arclength_riks: bool = False,
                         zero_tolerance_ectol: bool = True,
                         implicit_constant_step: bool = False,
                         discrete_offset: bool = True,
                         spring_token_mass_compensation: bool = True,
                         shell_to_solid_rbody: bool = True,
                         generalized_weld_butt: bool = True,
                         initial_void_floor: bool = True,
                         weld_exponents: bool = True,
                         constrained_linear: bool = True,
                         constrained_global: bool = True,
                         spotweld_node_synthesis: bool = False,
                         beam_contact_secondary: bool = False,
                         shell_offset_gapmin: bool = True,
                         rigid_shell_rotary_inertia: bool = True,
                         spotweld_shear_yield: bool = True,
                         spotweld_efail_displacement: bool = True,
                         implicit_tshell_solid: bool = True,
                         corotational_orthotropic: bool = True,
                         mat_null_pc_mu: bool = True,
                         joint_screw_gjoint: bool = True,
                         rigid_local_constraints: bool = True,
                         bcs_union: bool = True,
                         bolt_rigid_contact: bool = True,
                         fixed_curve_columns: bool = True,
                         section_nodal_thickness_mean: bool = True,
                         plane_strain_unit_thickness: bool = True,
                         rigid_element_mass_admas: bool = True,
                         spotweld_dt_mass_scaling: bool = True,
                         adaptive_spring_token: bool = True,
                         imflag0_eigen_explicit: bool = True,
                         implicit_smooth_curve_sampling: bool = True,
                         elastic_fluid_cp_cutoff: bool = True,
                         implicit_stub_with_type25: bool = False,
                         tgmult_imptemp: bool = True,
                         deformable_contact_recipe: bool = False,
                         blast_ground: str = "auto",
                         rigid_cog_master: bool = True,
                         zero_density_floor: bool = True,
                         law106_shell_restate: bool = True,
                         zero_t0_sentinel: bool = True,
                         node_tc_rc_bcs: bool = True,
                         default_hourglass: bool = True,
                         assumed_strain_isolid: str = "none",
                         implicit_rigid_secondary_swap: bool = False,
                         mass_weighted_inivel: bool = False,
                         write_restart: bool = False,
                         ams: bool = False,
                         shell_formulation: str = "qbat",
                         dt_del: str = "",
                         he_bunreacted: str = "",
                         ale_multimat_law51: bool = False,
                         eroding_surf_ext: bool = False,
                         airbag_particle_uniform: bool = False) -> dict:
    """Turn the raw widget strings into validated keyword arguments for
    :func:`k2rad.convert`. Raises ValueError (with a user-facing message) on any
    bad field. With everything blank/off the result is just the input path,
    units, and all stabilization/mesh options at their defaults → a byte-identical
    standard conversion.
    """
    input_path = (input_path or "").strip()
    if not input_path:
        raise ValueError("Choose an input .k file first.")
    if not os.path.isfile(input_path):
        raise ValueError(f"Input file not found:\n{input_path}")

    kwargs: dict = {"input_path": input_path}

    out = (output_stem or "").strip()
    if out:
        kwargs["output_stem"] = out

    defaults = ("Mg", "mm", "s")
    kwargs["units"] = tuple((str(units[i]).strip() or defaults[i]) for i in range(3))

    kwargs["tet10_to_tet4"] = bool(tet10_to_tet4)

    fp_text = (fixpoint_count_text or "").strip()
    if fp_text:                                     # blank → convert() default (0)
        try:
            kwargs["fixpoint_count"] = int(fp_text)
        except ValueError:
            raise ValueError(
                f"Implicit FIXPOINT count must be a whole number, got {fp_text!r}.")

    kwargs["ground_springs"] = bool(ground_springs)
    if ground_springs:
        k_text = (ground_spring_k_text or "").strip()
        if k_text:
            try:
                kwargs["ground_spring_k"] = float(k_text)
            except ValueError:
                raise ValueError(
                    f"Ground-spring K must be a number, got {k_text!r}.")

    kwargs["inter_gapmin"] = parse_inter_gapmin(inter_gapmin_text)

    kwargs["auto_gapmin"] = bool(auto_gapmin)
    if auto_gapmin:
        f_text = (gapmin_factor_text or "").strip()
        if f_text:
            try:
                kwargs["gapmin_factor"] = float(f_text)
            except ValueError:
                raise ValueError(
                    f"Gapmin factor must be a number, got {f_text!r}.")

    kwargs["derived_gapmin"] = bool(derived_gapmin)
    if derived_gapmin:
        d_text = (derived_gapmin_factor_text or "").strip()
        if d_text:
            try:
                kwargs["derived_gapmin_factor"] = float(d_text)
            except ValueError:
                raise ValueError(
                    f"Derived-Gapmin factor must be a number, got {d_text!r}.")

    kwargs["rigid_secondary_swap"] = bool(rigid_secondary_swap)

    kwargs["deformable_to_rigid"] = bool(deformable_to_rigid)

    st = (soften_stfac_text or "").strip()
    if st:
        try:
            kwargs["soften_stfac"] = float(st)
        except ValueError:
            raise ValueError(f"Soften Stfac must be a number, got {st!r}.")

    ts = (tie_stfac_text or "").strip()
    if ts:
        if ts.lower() == "auto":
            kwargs["tie_stfac"] = "auto"
        else:
            try:
                kwargs["tie_stfac"] = float(ts)
            except ValueError:
                raise ValueError(
                    f"Tie STFAC must be a number or 'auto', got {ts!r}.")

    qd = (qstat_dtscal_text or "").strip()
    if qd:                                        # blank -> convert() default (10)
        if qd.lower() == "none":
            kwargs["qstat_dtscal"] = "none"
        else:
            try:
                qd_v = float(qd)
            except ValueError:
                raise ValueError(
                    f"/IMPL/QSTAT/DTSCAL must be a number or 'none', got {qd!r}.")
            if qd_v <= 0.0:
                raise ValueError(
                    "/IMPL/QSTAT/DTSCAL must be > 0 (use 'none' to emit no "
                    f"/IMPL/QSTAT card), got {qd!r}.")
            kwargs["qstat_dtscal"] = qd_v

    kwargs["arclength_riks"] = bool(arclength_riks)

    kwargs["zero_tolerance_ectol"] = bool(zero_tolerance_ectol)

    kwargs["implicit_constant_step"] = bool(implicit_constant_step)

    kwargs["discrete_offset"] = bool(discrete_offset)

    kwargs["spring_token_mass_compensation"] = bool(
        spring_token_mass_compensation)

    kwargs["shell_to_solid_rbody"] = bool(shell_to_solid_rbody)

    kwargs["generalized_weld_butt"] = bool(generalized_weld_butt)

    kwargs["initial_void_floor"] = bool(initial_void_floor)

    kwargs["weld_exponents"] = bool(weld_exponents)

    kwargs["constrained_linear"] = bool(constrained_linear)

    kwargs["constrained_global"] = bool(constrained_global)

    kwargs["spotweld_node_synthesis"] = bool(spotweld_node_synthesis)

    kwargs["beam_contact_secondary"] = bool(beam_contact_secondary)

    kwargs["shell_offset_gapmin"] = bool(shell_offset_gapmin)

    kwargs["rigid_shell_rotary_inertia"] = bool(rigid_shell_rotary_inertia)

    kwargs["spotweld_shear_yield"] = bool(spotweld_shear_yield)

    kwargs["spotweld_efail_displacement"] = bool(spotweld_efail_displacement)

    kwargs["implicit_tshell_solid"] = bool(implicit_tshell_solid)

    kwargs["corotational_orthotropic"] = bool(corotational_orthotropic)

    kwargs["mat_null_pc_mu"] = bool(mat_null_pc_mu)

    kwargs["joint_screw_gjoint"] = bool(joint_screw_gjoint)

    kwargs["rigid_local_constraints"] = bool(rigid_local_constraints)

    kwargs["bcs_union"] = bool(bcs_union)

    kwargs["bolt_rigid_contact"] = bool(bolt_rigid_contact)

    kwargs["fixed_curve_columns"] = bool(fixed_curve_columns)

    kwargs["section_nodal_thickness_mean"] = bool(section_nodal_thickness_mean)

    kwargs["plane_strain_unit_thickness"] = bool(plane_strain_unit_thickness)

    kwargs["rigid_element_mass_admas"] = bool(rigid_element_mass_admas)

    kwargs["spotweld_dt_mass_scaling"] = bool(spotweld_dt_mass_scaling)

    kwargs["adaptive_spring_token"] = bool(adaptive_spring_token)

    kwargs["imflag0_eigen_explicit"] = bool(imflag0_eigen_explicit)

    kwargs["implicit_smooth_curve_sampling"] = bool(implicit_smooth_curve_sampling)

    kwargs["elastic_fluid_cp_cutoff"] = bool(elastic_fluid_cp_cutoff)

    kwargs["implicit_stub_with_type25"] = bool(implicit_stub_with_type25)

    kwargs["tgmult_imptemp"] = bool(tgmult_imptemp)

    kwargs["deformable_contact_recipe"] = bool(deformable_contact_recipe)

    bg = (blast_ground or "auto").strip() or "auto"
    if bg.lower() not in {"auto", "none", "x", "y", "z", "-x", "-y", "-z"}:
        raise ValueError(
            "Blast ground must be one of auto / none / X / Y / Z / -X / -Y / -Z, "
            f"got {bg!r}.")
    kwargs["blast_ground"] = bg

    kwargs["rigid_cog_master"] = bool(rigid_cog_master)

    kwargs["zero_density_floor"] = bool(zero_density_floor)

    kwargs["law106_shell_restate"] = bool(law106_shell_restate)

    kwargs["zero_t0_sentinel"] = bool(zero_t0_sentinel)

    kwargs["node_tc_rc_bcs"] = bool(node_tc_rc_bcs)

    kwargs["default_hourglass"] = bool(default_hourglass)

    # A radio pair in the GUI, a {24, none} choice on the CLI -- and nothing
    # else may reach ConvertOptions, whose __post_init__ refuses any other
    # value rather than writing it into /PROP/SOLID verbatim.
    asi = str(assumed_strain_isolid).strip() or "none"
    if asi not in ("24", "none"):
        raise ValueError(
            "assumed_strain_isolid must be '24' or 'none' (got "
            f"{assumed_strain_isolid!r})")
    kwargs["assumed_strain_isolid"] = asi

    kwargs["implicit_rigid_secondary_swap"] = bool(
        implicit_rigid_secondary_swap)

    kwargs["mass_weighted_inivel"] = bool(mass_weighted_inivel)

    kwargs["write_restart"] = bool(write_restart)

    kwargs["ams"] = bool(ams)

    kwargs["ale_multimat_law51"] = bool(ale_multimat_law51)

    kwargs["eroding_surf_ext"] = bool(eroding_surf_ext)

    kwargs["airbag_particle_uniform"] = bool(airbag_particle_uniform)

    if shell_formulation not in ("qbat", "qeph"):
        raise ValueError(
            "Shell formulation must be 'qbat' or 'qeph', not "
            f"{shell_formulation!r}.")
    kwargs["shell_formulation"] = shell_formulation

    # /DT/<elem>/DEL Tmin. Blank = off; the card DELETES elements, so an
    # unparseable value must be an error, never a silently-ignored blank.
    dt_del = (dt_del or "").strip()
    if dt_del:
        try:
            v = float(dt_del)
        except ValueError:
            raise ValueError(
                f"Time-step deletion floor must be a number in seconds, not "
                f"{dt_del!r}.")
        if v <= 0.0:
            raise ValueError(
                "Time-step deletion floor must be > 0 seconds (leave blank to "
                "emit no /DT/.../DEL card).")
        kwargs["dt_del"] = v

    # /MAT/LAW5 Bunreacted override. Blank = k2rad's own rule (the card's K,
    # else 0, which mjwl.F:166 makes exactly LS-DYNA's p = F*p_eos, or the
    # derived JWL isentrope slope for an AMMG member under
    # --ale-multimat-law51); an unparseable value must be an error, never a
    # silently-ignored blank. 0 IS legal and is the default: the ERROR 99 that
    # used to forbid it can only fire on an emitted /MAT/LAW51.
    he_bunreacted = (he_bunreacted or "").strip()
    if he_bunreacted:
        try:
            hb = float(he_bunreacted)
        except ValueError:
            raise ValueError(
                "Unreacted-explosive bulk modulus must be a number in the "
                f"deck's pressure unit, not {he_bunreacted!r}.")
        if hb < 0.0:
            raise ValueError(
                "Unreacted-explosive bulk modulus cannot be negative "
                f"({hb:g}); leave it blank for k2rad's own rule, or pass 0 "
                "for LS-DYNA's p = F*p_eos.")
        kwargs["he_bunreacted"] = hb

    return kwargs


# ─────────────────────────────────────────────────────────────────────────────
# Tkinter GUI
# ─────────────────────────────────────────────────────────────────────────────

class ConverterGUI:
    """The main window. Conversion runs on a worker thread; results are handed
    back to the Tk main loop through a queue polled with ``after``."""

    _K_FILETYPES = [("LS-DYNA keyword", "*.k *.key *.dyn"), ("All files", "*.*")]

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self._queue: "queue.Queue" = queue.Queue()
        self._last_out_dir = None

        root.title("k2rad — LS-DYNA → OpenRadioss converter")
        root.minsize(720, 560)

        # Tk variables
        self.in_path = tk.StringVar()
        self.out_stem = tk.StringVar()
        self.u_mass = tk.StringVar(value="Mg")
        self.u_len = tk.StringVar(value="mm")
        self.u_time = tk.StringVar(value="s")
        self.tet10 = tk.BooleanVar(value=False)
        self.fixpoint_count = tk.StringVar(value="0")
        self.qstat_dtscal = tk.StringVar(value="")
        self.arclength_riks = tk.BooleanVar(value=False)
        self.zero_tolerance_ectol = tk.BooleanVar(value=True)
        self.implicit_constant_step = tk.BooleanVar(value=False)
        self.discrete_offset = tk.BooleanVar(value=True)
        self.spring_token_mass_comp = tk.BooleanVar(value=True)
        self.shell_to_solid_rbody = tk.BooleanVar(value=True)
        self.generalized_weld_butt = tk.BooleanVar(value=True)
        self.initial_void_floor = tk.BooleanVar(value=True)
        self.weld_exponents = tk.BooleanVar(value=True)
        self.constrained_linear = tk.BooleanVar(value=True)
        self.constrained_global = tk.BooleanVar(value=True)
        self.spotweld_node_synthesis = tk.BooleanVar(value=False)
        self.beam_contact_secondary = tk.BooleanVar(value=False)
        self.shell_offset_gapmin = tk.BooleanVar(value=True)
        self.rigid_shell_rotary_inertia = tk.BooleanVar(value=True)
        self.spotweld_shear_yield = tk.BooleanVar(value=True)
        self.spotweld_efail_displacement = tk.BooleanVar(value=True)
        self.implicit_tshell_solid = tk.BooleanVar(value=True)
        self.corotational_orthotropic = tk.BooleanVar(value=True)
        self.mat_null_pc_mu = tk.BooleanVar(value=True)
        self.joint_screw_gjoint = tk.BooleanVar(value=True)
        self.rigid_local_constraints = tk.BooleanVar(value=True)
        self.bcs_union = tk.BooleanVar(value=True)
        self.bolt_rigid_contact = tk.BooleanVar(value=True)
        self.fixed_curve_columns = tk.BooleanVar(value=True)
        self.section_nodal_thickness_mean = tk.BooleanVar(value=True)
        self.plane_strain_unit_thickness = tk.BooleanVar(value=True)
        self.rigid_element_mass_admas = tk.BooleanVar(value=True)
        self.spotweld_dt_mass_scaling = tk.BooleanVar(value=True)
        self.adaptive_spring_token = tk.BooleanVar(value=True)
        self.imflag0_eigen_explicit = tk.BooleanVar(value=True)
        self.implicit_smooth_curve_sampling = tk.BooleanVar(value=True)
        self.elastic_fluid_cp_cutoff = tk.BooleanVar(value=True)
        self.implicit_stub_with_type25 = tk.BooleanVar(value=False)
        self.tgmult_imptemp = tk.BooleanVar(value=True)
        self.blast_ground = tk.StringVar(value="auto")
        self.rigid_cog = tk.BooleanVar(value=True)
        self.zero_density_floor = tk.BooleanVar(value=True)
        self.law106_shell_restate = tk.BooleanVar(value=True)
        self.zero_t0_sentinel = tk.BooleanVar(value=True)
        self.node_tc_rc_bcs = tk.BooleanVar(value=True)
        self.default_hourglass = tk.BooleanVar(value=True)
        self.assumed_strain_isolid = tk.StringVar(value="none")
        self.implicit_rigid_secondary_swap = tk.BooleanVar(value=False)
        self.mass_weighted_inivel = tk.BooleanVar(value=False)
        self.write_restart = tk.BooleanVar(value=False)
        self.ams = tk.BooleanVar(value=False)
        self.ale_multimat_law51 = tk.BooleanVar(value=False)
        self.eroding_surf_ext = tk.BooleanVar(value=False)
        self.airbag_particle_uniform = tk.BooleanVar(value=False)
        # 'qbat' = today's behaviour; see the radio buttons below.
        self.shell_formulation = tk.StringVar(value="qbat")
        self.dt_del = tk.StringVar(value="")
        self.he_bunreacted = tk.StringVar(value="")
        self.ground = tk.BooleanVar(value=False)
        self.ground_k = tk.StringVar(value="100")
        self.auto_gapmin = tk.BooleanVar(value=False)
        self.gapmin_factor = tk.StringVar(value="0.8")
        self.derived_gapmin = tk.BooleanVar(value=False)
        self.derived_gapmin_factor = tk.StringVar(value="0.005")
        self.rigid_secondary_swap = tk.BooleanVar(value=True)
        self.deformable_to_rigid = tk.BooleanVar(value=True)
        self.stfac = tk.StringVar()
        self.tie_stfac = tk.StringVar()
        self.deformable_recipe = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready.")
        self.progress = tk.DoubleVar(value=0.0)

        pad = {"padx": 6, "pady": 4}
        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # ── Input / output ──────────────────────────────────────────────────
        io = ttk.LabelFrame(main, text="Input / output", padding=8)
        io.grid(row=0, column=0, sticky="ew")
        io.columnconfigure(1, weight=1)

        ttk.Label(io, text="Input .k file:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(io, textvariable=self.in_path).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(io, text="Browse…", command=self._pick_input).grid(row=0, column=2, **pad)

        ttk.Label(io, text="Output stem:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(io, textvariable=self.out_stem).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(io, text="Browse…", command=self._pick_output).grid(row=1, column=2, **pad)
        ttk.Label(io, text="(optional — blank writes <input>_0000.rad / _0001.rad next to the input)",
                  foreground="gray").grid(row=2, column=1, sticky="w", padx=6)

        units = ttk.Frame(io)
        units.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(units, text="Units (header labels only — values are never rescaled):").pack(side="left")
        for var, w in ((self.u_mass, 6), (self.u_len, 6), (self.u_time, 6)):
            ttk.Entry(units, textvariable=var, width=w).pack(side="left", padx=3)

        ttk.Checkbutton(
            io, text="Downgrade TET10 → TET4 (linear tets — stiffer / less accurate; "
                     "use when only a TET10 .k is available)",
            variable=self.tet10).grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        fp = ttk.Frame(io)
        fp.grid(row=5, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(fp, text="Implicit FIXPOINT count:").pack(side="left")
        ttk.Entry(fp, textvariable=self.fixpoint_count, width=6).pack(side="left", padx=3)
        ttk.Label(fp, text="evenly spaced output milestones the implicit time step lands on "
                           "(1–100; DEFAULT 0 = off since 2026-09 — the grid makes the adaptive "
                           "step oscillate against /IMPL/DT/2 and cost ten R14 reference decks "
                           "their termination; the price of 0 is fewer output states. "
                           "Implicit decks only)",
                  foreground="gray").pack(side="left")

        qd = ttk.Frame(io)
        qd.grid(row=20, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(qd, text="/IMPL/QSTAT/DTSCAL:").pack(side="left")
        ttk.Entry(qd, textvariable=self.qstat_dtscal, width=8).pack(side="left", padx=3)
        ttk.Label(qd, text="inertia stabilization on a quasi-static implicit deck "
                           "(blank = 10, the default since 2026-09). The added "
                           "stiffness is M/((1+a)*b*(DTSCAL*dt)^2), so it grows as "
                           "1/DTSCAL^2: 0.1 was the OLD default and 100x Radioss's "
                           "own SCAL_DTQ=1. Measured at nt 3 and nt 4: "
                           "4.2.frf.cant-1 goes 4 cycles+ERROR -> 104 cycles, "
                           "t=1.000, IE -0.31 %; the cost is the "
                           "ex_02_thick_shell family (3 keys, one file) going "
                           "normal -> timeout on the pre-round-7 /PROP/TYPE20 "
                           "card (NORMAL in 28 cycles on the round-7 "
                           "/PROP/SOLID route). 'none' emits no card (measured "
                           "worse). The deformable-contact recipe keeps 0.05.",
                  foreground="gray", wraplength=620, justify="left").pack(side="left")

        ttk.Checkbutton(
            io, text="Arc-length (RIKS) /IMPL/DT/3 when *CONTROL_IMPLICIT_SOLUTION asks "
                     "for it (Vol I R17 p.12-354: 6 <= NSOLVR <= 9, or NSOLVR 12 with "
                     "card-3 ARCMTH = 3 — ARCCTL is the controlling NODE ID, not a "
                     "switch) — OFF by default; the request "
                     "is warned about either way. It buys the load path, not the "
                     "answer: ex_07 walks from t=0.3004 to t=1.000 at -1.72 % but still "
                     "ERRORs on the last increment, and ex_05 turns a ~2 s error into a "
                     "600 s timeout",
            variable=self.arclength_riks).grid(
                row=21, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Honour *ELEMENT_DISCRETE OFFSET (shift the force law's abscissae "
                     "by -OFFSET + /INISPRI/FULL pre-stretch energy) — ON. With the "
                     "token-mass compensation below, ex_17/ex_18 go from strict ZERO "
                     "models to IE +0.007 % / +0.006 % against their LS-DYNA glstat",
            variable=self.discrete_offset).grid(
                row=22, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Remove k2rad's artificial spring mass (1e-4 per spring /PROP, "
                     "half on each end node per element) from those nodes again — ON. "
                     "Subtracted from an /ADMAS the deck states, else taken off with a "
                     "NEGATIVE /ADMAS (round 5). plates.nrbc TOTAL MASS 2.0048E-04 -> "
                     "1.0048E-04 = LS-DYNA's own, +1.21 % cycles. Never writes a "
                     "non-positive value on the deck's OWN /ADMAS; refuses a spring "
                     "node with no mass of its own (no element mass, no "
                     "*ELEMENT_MASS): it would sit at exactly MS = 0, which "
                     "nothing catches (chkmsin.F:53 is MS < 0 only)",
            variable=self.spring_token_mass_comp).grid(
                row=23, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*CONSTRAINED_SHELL_TO_SOLID → one /RBODY per card (shell "
                     "node = main, NSID set = secondary, Mass 0, ICoG 3) — ON. "
                     "LS-DYNA names the substitute itself (Vol I R17 p.10-182). "
                     "Cost: the brick fibre can no longer stretch. dome: "
                     "EXT-WORK 1689 vs 1692.55 (−0.21 %), IE 0.6693 → 873.9 "
                     "(−99.90 % → +36.08 %), KE 1.290e5 → 806.4 "
                     "(+12299.9 % → −22.49 %)",
            variable=self.shell_to_solid_rbody).grid(
                row=27, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*CONSTRAINED_GENERALIZED_WELD_BUTT → one /RBODY with "
                     "Ifail=1, FN = FT = SIGY·L·D/BETA — ON, coincident pairs "
                     "only. LS-DYNA's own model of the weld IS a nodal rigid "
                     "body (p.10-32). butt-weld: NORMAL 2082 cycles, IE −100 % "
                     "→ +4.70 %, the right two welds off at t 1.272e-3 vs "
                     "1.26914e-3. EPSF/TFAIL/CID dropped and named",
            variable=self.generalized_weld_butt).grid(
                row=28, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="All-rigid SSID contacts: swap the roles instead of losing the "
                     "interface (explicit decks) — ON. /INTER/TYPE7 is asymmetric "
                     "node-to-segment, so the deformable side must supply the tracked "
                     "nodes. sphere1 IE -100 % -> -1.66 %, blow-mold timeout -> NORMAL. "
                     "Implicit decks keep the drop (bumper diverges on every arm)",
            variable=self.rigid_secondary_swap).grid(
                row=25, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*DEFORMABLE_TO_RIGID -> /RBODY at t = 0 (the part keeps its own "
                     "material) — ON. pend.imp's energy error goes 99.9 % to "
                     "-0.0 % and its 125 052 cycles become 9 480, where LS-DYNA takes "
                     "9 479",
            variable=self.deformable_to_rigid).grid(
                row=26, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_THERMAL_* TGMULT -> /IMPTEMP (the adiabatic closed form "
                     "T = T0 + (TGMULT/(rho*Cp))*INTEGRAL(f dt)) — ON, and only on a deck with NO "
                     "other temperature driver. Measured on thermal-stress: node 2's "
                     "free expansion goes from exactly 0.0 to 1.49531e-04 mm against "
                     "the LS-DYNA nodout's 1.49216e-04 (+0.21 %)",
            variable=self.tgmult_imptemp).grid(
                row=24, column=0, columnspan=3, sticky="w", **pad)

        bg = ttk.Frame(io)
        bg.grid(row=6, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(bg, text="Blast ground plane:").pack(side="left")
        ttk.Combobox(bg, textvariable=self.blast_ground, width=7, state="readonly",
                     values=["auto", "none", "X", "Y", "Z", "-X", "-Y", "-Z"]
                     ).pack(side="left", padx=3)
        ttk.Label(bg, text="reflecting ground for a surface-burst /LOAD/PBLAST — auto infers the "
                           "vertical axis; none = solver default (⊥Z); X/Y/Z force it (blast decks only)",
                  foreground="gray").pack(side="left")

        ttk.Checkbutton(
            io, text="Element-free rigid masters (default on — *MAT_RIGID: /RBODY "
                     "master synthesized at the part's centroid; mesh nodes keep "
                     "their coordinates, clears WARNINGs 448/1624, AMS-compatible. "
                     "Untick to reuse the part's lowest-id mesh node as master)",
            variable=self.rigid_cog).grid(row=7, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Zero-density floor (default on — a material stating RO <= 0 "
                     "gets rho = 1e-24 in the deck's own units, the substitution "
                     "LS-DYNA itself makes; without it the starter refuses the deck "
                     "with ERROR 683. Static/eigenvalue answers are unaffected; an "
                     "EXPLICIT deck is warned that its time step collapses. Untick "
                     "to copy the deck's own RO through)",
            variable=self.zero_density_floor).grid(row=7, column=3, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Restate a shell-only *MAT_004/*MAT_CWM as /MAT/LAW36  "
                     "(default on: a /MAT/LAW106 SHELL does not thermally expand "
                     "at all — sigeps106c.F90:297-298 rebuilds the stress from the "
                     "TOTAL strain and discards what cmain3.F:348's THERMEXPC "
                     "subtracts; measured 0.0000000e+00 vs a closed-form 1.2e-2 mm, "
                     "against an exact 1.2000000e-02 restated. Solids are "
                     "never restated. Untick to keep "
                     "/MAT/LAW106 and its E(T) with zero expansion)",
            variable=self.law106_shell_restate).grid(row=8, column=3, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Dodge Radioss 0-means-300K initial temperature  "
                     "(default on: a deck that STATES T = 0 gets /HEAT/MAT "
                     "T0 = 1e-10 instead, because hm_read_therm.F:236-237 "
                     "turns a zero T0 into 300 K and every node still at 0.0 "
                     "is then overwritten with it. Measured +468.9 % vs the "
                     "LS-DYNA reference without it, +0.91 % with it)",
            variable=self.zero_t0_sentinel).grid(row=9, column=3, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Convert *NODE's own TC/RC constraint cells to /BCS  "
                     "(default on: Vol I R17 p.35-2 makes *NODE card 1 "
                     "'NID X Y Z TC RC', and LS-DYNA applies those codes "
                     "unconditionally — its d3hsp echoes them, matched here "
                     "on all 162139 TC/RC cells of the 137 carrier decks (the "
                     "echo is printed by 155 of the R14 reference runs). "
                     "Without it 137 of "
                     "the 356 R14 reference decks run unsupported: measured, "
                     "component1 goes from IE -99.92 % / KE +772630 % to "
                     "+1.5 % / +1.0 %. Rigid-body nodes and DOFs a "
                     "prescribed motion drives are screened out and counted. "
                     "Untick to leave those DOFs free)",
            variable=self.node_tc_rc_bcs).grid(row=11, column=3, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Write engine restart (.rst) files  (default off → /RFILE/OFF; "
                     "restart files are only needed for /RERUN or crash recovery and "
                     "are large — the starter's mandatory _0000_*.rst is unaffected)",
            variable=self.write_restart).grid(row=8, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Advanced Mass Scaling (DT2MS<0 → /DT/AMS + /AMS instead of "
                     "/DT/NODA/CST: a coupled mass matrix preserves low-frequency "
                     "dynamics instead of adding real mass; can diverge on stiff / "
                     "contact-heavy models — implies element-free rigid masters)",
            variable=self.ams).grid(row=9, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Eroding contacts: external skin only (*CONTACT_ERODING_* "
                     "solid sides on /SURF/PART/EXT instead of the default "
                     "/SURF/PART/ALL). Leave OFF for erosion-correct behaviour — "
                     "/ALL keeps interior solid faces as dormant segments the "
                     "engine wakes when a brick dies; with /EXT the crater face a "
                     "dying element exposes has NO contact and nothing warns you",
            variable=self.eroding_surf_ext).grid(row=10, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Emit the synthesized /MAT/LAW51 for an "
                     "*ALE_MULTI-MATERIAL_GROUP (default OFF: k2rad writes the "
                     "LS-DYNA per-fluid ALE layout, so no /PART it emits can "
                     "reference that card — measured inert, every T01 channel "
                     "identical without it. Keeping it only forced a positive "
                     "/MAT/LAW5 Bunreacted, which mjwl.F:166 turns into a real "
                     "(1-F)*K*mu pre-burn stiffness LS-DYNA does not have. Tick "
                     "it if you will consolidate the ALE mesh onto one /PART "
                     "by hand)",
            variable=self.ale_multimat_law51).grid(row=10, column=3, columnspan=3, sticky="w", **pad)

        # row 13: after the dt_del entry (row 12), the last row this frame uses.
        ttk.Checkbutton(
            io, text="*AIRBAG_PARTICLE as a uniform-pressure /MONVOL/AIRBAG1 "
                     "instead of the finite-volume /MONVOL/FVMBAG2. FVMBAG2 is "
                     "the faithful conversion and the default, but an "
                     "open-source OpenRadioss build has NO FV mesher: the "
                     "starter reads the card cleanly, prints \"FVMBAGS require "
                     "a mesher\" and stops. Turn this ON to get a bag that "
                     "actually inflates — same gas, injector and vents, "
                     "uniform pressure instead of a pressure field",
            variable=self.airbag_particle_uniform).grid(
                row=13, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="LS-DYNA's DEFAULT hourglass control on a defaulted 1-point "
                     "*SECTION_SOLID (default on: Vol I R17 p.12-271 Remark 1 — "
                     "an omitted *CONTROL_HOURGLASS, or IHQ 0, means type 2 for "
                     "explicit and type 6 for implicit solids, QH 0.1; the deck's "
                     "own d3hsp echoes it. Without it those hexes get Isolid 17, "
                     "which prop_p14_solid.cfg calls '2*2*2 Integration Points, "
                     "No Hourglass'. Measured: sloshing_A goes from a "
                     "TIMESTEP-LIMIT death at t = 0.18 to NORMAL at t = 2.0 "
                     "(IE -0.25 %), taylor_A from IE +2.56 % to +0.00 %, the "
                     "implicit ex_03_solid_elform_1 from -20.4 % to -4.1 %. "
                     "ELFORM -1/-2, 2/3/16, tets, ALE, LAW115 and preloaded decks "
                     "are screened out; a *MAT_NULL fluid keeps the viscous form. "
                     "Untick to keep the pre-2026-09 output)",
            variable=self.default_hourglass).grid(
                row=13, column=3, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="ELFORM -1/-2 (assumed-strain hex) \u2192 Isolid 24 instead of "
                     "17 \u2014 OFF. 17 IS the locking ELFORM-2 element -1/-2 exist "
                     "to replace (p.41-104 Remark 13). Opt-in because the arms "
                     "disagree: ex_03 -21.72 % \u2192 -5.87 % and ex_04 -5.84 % \u2192 "
                     "-2.83 % improve, but ex_14 -1/-2 go +314/+494 % \u2192 "
                     "+1373/+2014 %, mainboltaexpl -72.7 \u2192 -81.4 % and "
                     "ex_27_-2_rigidwall loses the class's only match. Reach "
                     "22 keys / 18 models, 19 / 16 with the flag",
            variable=self.assumed_strain_isolid,
            onvalue="24", offvalue="none").grid(
                row=29, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="IMPLICIT deck: swap an all-rigid SSID contact instead of "
                     "dropping it \u2014 OFF. Implies the derived Gapmin and refuses "
                     "to swap without one. bumper (nt 2 and 4): the drop is a "
                     "NORMAL zero model (IE 0 vs 1.23131e7), the bare swap "
                     "ERRORs at t 3.0e-4, swap + Gapmin 0.1499 reaches NORMAL "
                     "131 cycles at IE 6.934e5 (-94.4 %). The verdict cannot "
                     "move \u2014 that deck's LS-DYNA KE is exactly 0",
            variable=self.implicit_rigid_secondary_swap).grid(
                row=30, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*INITIAL_VELOCITY on a PARTLY covered rigid body: write "
                     "the momentum average (p.28-129 Remark 3) on the /RBODY "
                     "main node \u2014 OFF. translat cycle-0 KE 387.9 \u2192 220.58 "
                     "against LS-DYNA's 189.962 (+104.20 % \u2192 +16.12 %), and "
                     "with J = -SUM(IN) on the /RBODY (the default since "
                     "round 7) 189.96. One "
                     "carrier with a reference exists, hence opt-in",
            variable=self.mass_weighted_inivel).grid(
                row=31, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*INITIAL_VOID on an ELFORM-12 fluid: write the cavitation "
                     "floor Pmin = -1e-20 on its /MAT/HYD_VISC — ON. Pmin 0 "
                     "is read as -INFINITY (hm_read_mat06.F:154), an unbounded "
                     "tension. quadrature_B / bird_B timeout → NORMAL (1095 / "
                     "2936 cycles, nt 4) — NORMAL, not a match: the void's "
                     "low density is not written",
            variable=self.initial_void_floor).grid(
                row=32, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Failing *CONSTRAINED_SPOTWELD: write the deck's exponents "
                     "N / M into the /PROP/TYPE13 alpha/beta cells when either "
                     "differs from 2 — ON. A blank cell is read as exponent 2 "
                     "(hm_read_prop13.F:1169-1170). plates.nrbc / plates.spot "
                     "(N = M = 1): rupture +29.4 % → +1.7 % against LS-DYNA, "
                     "0.899x cycles",
            variable=self.weld_exponents).grid(
                row=33, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*CONSTRAINED_LINEAR_LOCAL/_GLOBAL → one /MPC per card "
                     "(Lagrange multiplier, C0 = 0 as in LS-DYNA) — ON. Refused "
                     "by name on a /BCS or imposed-motion DOF, a rigid-body "
                     "node, an element-free node, COEF 0, DOF 7. plates.lce: "
                     "NUMMPC 1, 0 errors, identical on all 683 rows",
            variable=self.constrained_linear).grid(
                row=34, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Solid main against a SHELL secondary LS-DYNA offsets "
                     "(AUTOMATIC_*, or SHLTHK 1/2): write Gapmin = t/2, capped "
                     "at 0.5 x the smallest main edge - ON. The starter would "
                     "derive 0.1 x that edge (i7sti3.F:1055-1063). bend: KE "
                     "-68.65 % -> -45.60 % at matched time, 0.98x cycles",
            variable=self.shell_offset_gapmin).grid(
                row=35, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*CONTROL_IMPLICIT_SOLUTION with DCTOL/ECTOL/RCTOL all 0 or "
                     "blank: write LS-DYNA's own ECTOL default (/IMPL/NONLIN "
                     "Itol 1, Toli 0.01) - ON. Its d3hsp echoes 0.001 / 0.01 on "
                     "all 11 R14 decks of this shape (the reason - no carrier's "
                     "IE history got closer by more than 0.03 % of its peak). "
                     "tensile2 ends +7.36 % -> -0.54 % "
                     "but reads +53 % at t 0.80 (history RMS 2.00 -> 2.48 % of "
                     "peak); doorbeam +380 % -> +582 % (named); ie_shell "
                     "ERROR -> NORMAL at -99.87 % (status only)",
            variable=self.zero_tolerance_ectol).grid(
                row=36, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Cap the implicit step at the deck's own DT0 where LS-DYNA "
                     "runs a CONSTANT step (IAUTO 0 or no *CONTROL_IMPLICIT_AUTO, "
                     "0 < DT0 < ENDTIM) - OFF. ex_15 energy error +74.1 % -> "
                     "-0.9 % at 3.81x cycles (pre-round-7 /PROP/TYPE20 card; "
                     "the round-7 /PROP/SOLID route alone gives -0.7 %, "
                     "capped -1.8 % at 5.94x); on "
                     "the quasi-static decks it costs "
                     "cycles (tensile2 75 -> 168, IE -0.54 % -> -4.36 % at the "
                     "end, history RMS 2.48 -> 1.66 % of peak, the closest "
                     "arm); ex_11 KE +17.9 % at matched time (the shipped run "
                     "+1343 %)",
            variable=self.implicit_constant_step).grid(
                row=37, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*CONSTRAINED_GLOBAL plane -> /BCS on the nodes within TOL "
                     "(1e-6 x the model extent when TOL is 0), the codes "
                     "UNIONED per node with the *NODE TC/RC cells - ON. The "
                     "selection equals LS-DYNA's own spc summary on all 3 R14 "
                     "carriers (305, 54, 24737 nodes)",
            variable=self.constrained_global).grid(
                row=38, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="One-node ELFORM-9 *MAT_SPOTWELD beam: create its second "
                     "node on the nearest reference segment on the other side "
                     "(Vol I R17 p.19-3) - OFF. Alone it only costs cycles "
                     "(7.64x on spotweld.k); pair it with the next box",
            variable=self.spotweld_node_synthesis).grid(
                row=39, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Put beam/truss nodes on a contact side that names their "
                     "part - OFF. With the box above, spotweld.k goes IE "
                     "-99.9 % -> +82.0 % at 7.80x cycles (the sign changes, "
                     "not the size) and the weld never fails",
            variable=self.beam_contact_secondary).grid(
                row=40, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_RIGID / *DEFORMABLE_TO_RIGID part body: write "
                     "J = -SUM(IN) so the starter's tensor is LS-DYNA's "
                     "point-mass sum (it ADDS every shell node's IN, "
                     "inirby.F:355) - ON. Spun plate KE_R +16.83 % -> 0.00 %; "
                     "revo-stiff IE / KE RMS 4.96 / 2.94 -> 0.78 / 0.73 % at "
                     "1.156x cycles",
            variable=self.rigid_shell_rotary_inertia).grid(
                row=41, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_SPOTWELD weld: a bilinear SHEAR curve on Ty/Tz at "
                     "the von Mises shear yield (SIGY/sqrt3)·A - ON. "
                     "plates.mat100 IE / KE RMS 23.53 / 62.56 -> 8.58 / 26.74 % "
                     "at 1.107x cycles (LS's shear plateau 20405)",
            variable=self.spotweld_shear_yield).grid(
                row=42, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_SPOTWELD EFAIL with no resultant cell: Ifail 1 / "
                     "Ifail2 0 displacement failure (delta_y + EFAIL·L, "
                     "sqrt3 on shear) - ON. spotweld.k rupture 1.12650e-3 s "
                     "vs LS 1.17969e-3..1.19792e-3 s",
            variable=self.spotweld_efail_displacement).grid(
                row=43, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="IMPLICIT deck: a *MAT_ELASTIC thick shell goes to "
                     "/PROP/SOLID Isolid 14 instead of /PROP/TYPE20 (its "
                     "implicit tangent has ONE through-thickness point) - ON. "
                     "ex_02 timeout -> NORMAL in 28 cycles; ex_15 energy "
                     "error 74.1 -> -0.7 %",
            variable=self.implicit_tshell_solid).grid(
                row=44, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Element-frame orthotropic /PROP/TYPE6 co-rotational "
                     "(honeycomb Iframe 2, Ip 21/24 -> Isolid 14, LAW93 b/c "
                     "on Ip 21) - ON. MAT_126 crush cube 0 -> 12 of 12 "
                     "cases right",
            variable=self.corotational_orthotropic).grid(
                row=45, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_NULL PC / MU -> /MAT/HYD_VISC Pmin / Nu - ON. "
                     "PC 0 -> -1e-20 (LS cuts at zero); Nu = MU/RO on "
                     "ELFORM-6 fluids only. sph/bird IE +69.4 -> +4.5 %, "
                     "channel_B -98.9 -> -0.1 %",
            variable=self.mat_null_pc_mu).grid(
                row=46, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*CONSTRAINED_JOINT_SCREW -> /GJOINT/RACK (Lagrange, "
                     "carriage /RBODY, contact split; SMP only, -np 1) - ON. "
                     "EXP_SC_JOINT_SCREW nut travel 0 -> 185.70 mm vs LS "
                     "183.59",
            variable=self.joint_screw_gjoint).grid(
                row=47, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_RIGID CMO -1 -> /BCS in the /SKEW of CON1 (one skew "
                     "per node) - ON. block-slide KE +100.10 -> +0.05 %",
            variable=self.rigid_local_constraints).grid(
                row=48, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*BOUNDARY_SPC union: no DOF restated in a second /BCS "
                     "(P1-P3) - ON. Removes starter WARNING 312, 0 physics",
            variable=self.bcs_union).grid(
                row=49, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Bolt-end rigid bodies keep their members on penalty "
                     "contact secondary sides - ON. mainboltaexpl IE -81.87 -> "
                     "-8.49 % (with the curve fix)",
            variable=self.bolt_rigid_contact).grid(
                row=50, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*DEFINE_CURVE: read an unsplittable point line in fixed "
                     "2E20.0 columns - ON. mainboltaexpl /FUNCT/11 2 -> 4 points",
            variable=self.fixed_curve_columns).grid(
                row=51, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*SECTION_SHELL T1..T4 -> their mean thickness - ON. "
                     "cup-draw tool masses = LS-DYNA; OR energy error -4.4 -> "
                     "-17.9 % (named cost)",
            variable=self.section_nodal_thickness_mean).grid(
                row=52, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Plane-strain *SECTION_SHELL (ELFORM 13/43/52/55) -> "
                     "thickness 1.0 - ON. ex_16 disk mass = LS-DYNA",
            variable=self.plane_strain_unit_thickness).grid(
                row=53, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*ELEMENT_MASS on a rigid SECONDARY node -> /ADMAS on that "
                     "node - ON. foam CoG = LS-DYNA; CNRB masses no longer "
                     "dropped",
            variable=self.rigid_element_mass_admas).grid(
                row=54, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_SPOTWELD DT -> TYPE13 Mass / Inertia so the weld "
                     "steps at 0.9 DT - ON. spotweld.k last cycle 1332 = "
                     "LS-DYNA's 1332",
            variable=self.spotweld_dt_mass_scaling).grid(
                row=55, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Spring token MASS from the end-node masses (2 mu min(1, "
                     "2/n)) - ON. the fixed 1e-4 token was killed within 3-6 "
                     "cycles on 3 coupons",
            variable=self.adaptive_spring_token).grid(
                row=56, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="IMFLAG 0 + NEIG 0 eigenvalue deck -> EXPLICIT route "
                     "(LS-DYNA runs it explicit) - ON. tire.k cycle-0 stop -> "
                     "NORMAL in 24329 cycles",
            variable=self.imflag0_eigen_explicit).grid(
                row=57, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="IMPLICIT deck: *DEFINE_CURVE_SMOOTH -> sampled sine /FUNCT "
                     "(the implicit solver reads /FUNCT_SMOOTH as a straight "
                     "ramp) - ON. metal-cutting cycle-26 ERROR -> NORMAL in 202 "
                     "cycles",
            variable=self.implicit_smooth_curve_sampling).grid(
                row=58, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="*MAT_ELASTIC_FLUID stated CP 0.0 -> Pmin -1e-20 (a cut-off "
                     "at zero, as *MAT_NULL PC 0) - ON",
            variable=self.elastic_fluid_cp_cutoff).grid(
                row=59, column=0, columnspan=3, sticky="w", **pad)

        ttk.Checkbutton(
            io, text="Implicit TYPE25-only deck: keep the inert all-parts "
                     "contact stub (as before round 8) - OFF. doorbeam END +582 "
                     "-> +689 %, RMS 393 -> 313 % without it",
            variable=self.implicit_stub_with_type25).grid(
                row=60, column=0, columnspan=3, sticky="w", **pad)

        # ── Shell formulation (issue #77) ───────────────────────────────────
        # A radio PAIR rather than a checkbox: neither value is "the fix", and
        # a checkbox labelled "use QEPH" would imply QBAT is simply wrong. The
        # default is spelled out as the existing behaviour so nobody switches
        # without realising they are changing every shell result they have.
        sf = ttk.LabelFrame(
            io, text="Shell formulation for LS-DYNA ELFORMs with no exact "
                     "Radioss counterpart (ELFORM=2 Belytschko-Tsay above all)",
            padding=6)
        sf.grid(row=10, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Radiobutton(
            sf, text="Ishell=12 QBAT — fully integrated (DEFAULT; what every "
                     "previous conversion produced)",
            value="qbat", variable=self.shell_formulation,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            sf, text="Ishell=24 QEPH — reduced integration, physically "
                     "stabilised. Closer to ELFORM=2, and erodes faithfully "
                     "under Ifail_sh=2 (QBAT needs 8 failure events to delete "
                     "an element instead of 2, under-eroding up to ~1.7x). "
                     "CHANGES RESULTS on every shell deck.",
            value="qeph", variable=self.shell_formulation,
        ).grid(row=1, column=0, sticky="w")

        # ── Time-step deletion floor (issue #78) ────────────────────────────
        # An entry box, not a checkbox: there is no safe default value to tick
        # into existence. The card DELETES elements, so the user names the
        # threshold or gets nothing.
        ttk.Label(
            io, text="Time-step deletion floor Tmin [s] (blank = off):"
        ).grid(row=11, column=0, sticky="w", **pad)
        ttk.Entry(io, textvariable=self.dt_del, width=14).grid(
            row=11, column=1, sticky="w", **pad)
        ttk.Label(
            io, wraplength=760, foreground="#804000",
            text="Emits /DT/{SHELL,SH_3N,BRICK}/DEL — OpenRadioss DELETES any "
                 "element whose time step reaches Tmin, removing mass and "
                 "stiffness the LS-DYNA original may have kept. Leave blank "
                 "unless a run is stalling on one degrading element; a deck "
                 "that asks for deletion itself (*CONTROL_TIMESTEP ERODE=1 "
                 "with TSLIMT>0) is converted without this. Choose it as a "
                 "DELETION threshold, not a mass-scaling target: ~0.9x the "
                 "initial step deletes elements that merely stretched ~10%, "
                 "~0.4-0.5x reserves it for near-total element collapse."
        ).grid(row=12, column=0, columnspan=3, sticky="w", **pad)

        # ── Unreacted-explosive bulk modulus (R14 triage batch) ─────────────
        # An entry box, not a checkbox: the cell is a MODULUS, and there is no
        # safe default to tick into existence — blank means "use the card's
        # own K, or the derived JWL isentrope slope where a LAW51 phase makes
        # a positive value mandatory", and the derivation names itself in the
        # log every time it fires.
        ttk.Label(
            io, text="Unreacted-explosive bulk modulus Bunreacted "
                     "(blank = derive):"
        ).grid(row=13, column=0, sticky="w", **pad)
        ttk.Entry(io, textvariable=self.he_bunreacted, width=14).grid(
            row=13, column=1, sticky="w", **pad)
        ttk.Label(
            io, wraplength=760, foreground="#804000",
            text="Overrides the /MAT/LAW5 Bunreacted cell, in the deck's own "
                 "pressure unit. *MAT_HIGH_EXPLOSIVE_BURN's K is 'BETA = 2.0 "
                 "only', so a beta-burn deck legally states 0 — but "
                 "fill_buffer_51.F:496 refuses a /MAT/LAW51 phase whose "
                 "Bunreacted is <= 0 (ERROR 99). Left blank, k2rad writes the "
                 "card's K when it has one and otherwise derives "
                 "A*R1*exp(-R1) + B*R2*exp(-R2) + omega*E0 from the companion "
                 "*EOS_JWL, for AMMG members only. Fill this in to state a "
                 "measured value instead."
        ).grid(row=14, column=0, columnspan=3, sticky="w", **pad)

        # ── Force-control stabilization ─────────────────────────────────────
        fc = ttk.LabelFrame(
            main, text="Force-control implicit stabilization (leave blank/off for a standard conversion)",
            padding=8)
        fc.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        fc.columnconfigure(1, weight=1)

        gr = ttk.Frame(fc)
        gr.grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        self._ground_chk = ttk.Checkbutton(
            gr, text="Ground springs (soft /PROP/TYPE8 on each loaded rigid body)",
            variable=self.ground, command=self._sync_ground_k)
        self._ground_chk.pack(side="left")
        ttk.Label(gr, text="   K (N/mm):").pack(side="left")
        self._ground_k_entry = ttk.Entry(gr, textvariable=self.ground_k, width=8)
        self._ground_k_entry.pack(side="left", padx=3)

        ag = ttk.Frame(fc)
        ag.grid(row=1, column=0, columnspan=3, sticky="w", **pad)
        self._auto_gapmin_chk = ttk.Checkbutton(
            ag, text="Auto Gapmin from mesh clearance (min node distance between each contact's two parts)",
            variable=self.auto_gapmin, command=self._sync_gapmin_factor)
        self._auto_gapmin_chk.pack(side="left")
        ttk.Label(ag, text="   factor:").pack(side="left")
        self._gapmin_factor_entry = ttk.Entry(ag, textvariable=self.gapmin_factor, width=6)
        self._gapmin_factor_entry.pack(side="left", padx=3)
        ttk.Label(fc, text="Gapmin = factor × node-to-segment clearance (factor < 1 → 0 initial penetrations). "
                           "Needs numpy+scipy; see docs/DEPENDENCIES.md.",
                  foreground="gray").grid(row=2, column=1, columnspan=2, sticky="w", padx=6)

        dg = ttk.Frame(fc)
        dg.grid(row=21, column=0, columnspan=3, sticky="w", **pad)
        self._derived_gapmin_chk = ttk.Checkbutton(
            dg, text="Derived Gapmin on SOLID-only-main /INTER/TYPE7 (pure stdlib, no scipy)",
            variable=self.derived_gapmin, command=self._sync_derived_gapmin_factor)
        self._derived_gapmin_chk.pack(side="left")
        ttk.Label(dg, text="   factor:").pack(side="left")
        self._derived_gapmin_entry = ttk.Entry(
            dg, textvariable=self.derived_gapmin_factor, width=6)
        self._derived_gapmin_entry.pack(side="left", padx=3)
        ttk.Label(fc, text="OFF by default; a warning names the starter-derived GAP MIN either way. "
                           "Gapmin = factor × the smallest main-surface segment side (ceiling 0.5 ×). "
                           "No gap value has promoted a campaign verdict (twobar's end value moves, "
                           "its history does not; sphere1 goes -1.66 % → -7.77 % at 4.1× the cycles); "
                           "cycles grow as ~1/Gapmin below a deck-specific knee, and 8 of the class's "
                           "15 R14-roster interfaces are unmeasured.",
                  foreground="gray").grid(row=22, column=1, columnspan=2, sticky="w", padx=6)

        ttk.Label(fc, text="Soften Stfac:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(fc, textvariable=self.stfac, width=10).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(fc, text="penalty stiffness scale on all /INTER/TYPE7, e.g. 0.3 — blank = engine default; "
                           ".k-native per contact: Card-3 SFS (overridden by this field)",
                  foreground="gray").grid(row=4, column=1, columnspan=2, sticky="w", padx=6)

        ttk.Label(fc, text="Tie STFAC:").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(fc, textvariable=self.tie_stfac, width=10).grid(
            row=5, column=1, sticky="w", **pad)
        ttk.Label(fc, text="penalty-tie stiffness scale on /INTER/TYPE10 — a number, or "
                           "'auto' for 100x the local element stiffness (120 at nu=0.3). "
                           "Blank = Radioss's own 0.2, measured as a -67.6 % tie on a "
                           "determinate coupon; 30 -> -0.76 %, 120 -> +0.05 %, at dt x 0.115 "
                           "and dt x 0.058. Only implicit ties and all-rigid-secondary ties "
                           "use /INTER/TYPE10.",
                  foreground="gray").grid(row=6, column=1, columnspan=2, sticky="w", padx=6)

        rc = ttk.Frame(fc)
        rc.grid(row=7, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(
            rc, text="Deformable–deformable contact recipe (Inacti=5 + /IMPL/DT/2 L_dtn=50 "
                     "+ /IMPL/QSTAT/DTSCAL=0.05)",
            variable=self.deformable_recipe).pack(side="left")
        ttk.Label(fc, text="Use when two DEFORMABLE parts contact in an implicit deck (e.g. force control "
                           "through a clearance-fit deformable pin) and the solve chatters or stalls. "
                           "The converter warns when it detects such contact.",
                  foreground="gray").grid(row=8, column=1, columnspan=2, sticky="w", padx=6)

        # ── Action row ──────────────────────────────────────────────────────
        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._convert_btn = ttk.Button(actions, text="Convert", command=self._on_convert)
        self._convert_btn.pack(side="left")
        self._open_btn = ttk.Button(actions, text="Open output folder",
                                    command=self._open_output, state="disabled")
        self._open_btn.pack(side="left", padx=6)
        ttk.Label(actions, textvariable=self.status, foreground="gray").pack(side="left", padx=10)

        # ── Progress bar ────────────────────────────────────────────────────
        self._progress_bar = ttk.Progressbar(
            main, orient="horizontal", mode="determinate",
            maximum=100.0, variable=self.progress)
        self._progress_bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        # ── Output log ──────────────────────────────────────────────────────
        main.rowconfigure(4, weight=1)
        self._log = scrolledtext.ScrolledText(main, height=14, wrap="word", state="disabled")
        self._log.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        # Warnings render in a larger font (3 pt over the log's base size) so
        # they are not missed in the scroll of output, but in plain black,
        # non-bold text.
        _base = tkfont.nametofont("TkTextFont")
        self._warn_font = tkfont.Font(family=_base.cget("family"),
                                      size=_base.cget("size") + 3, weight="normal")
        self._log.tag_configure("warn", font=self._warn_font, foreground="black")

        self._sync_ground_k()
        self._sync_gapmin_factor()
        self._sync_derived_gapmin_factor()

    # ── widget callbacks ─────────────────────────────────────────────────────

    def _sync_ground_k(self) -> None:
        self._ground_k_entry.config(state="normal" if self.ground.get() else "disabled")

    def _sync_gapmin_factor(self) -> None:
        self._gapmin_factor_entry.config(
            state="normal" if self.auto_gapmin.get() else "disabled")

    def _sync_derived_gapmin_factor(self) -> None:
        self._derived_gapmin_entry.config(
            state="normal" if self.derived_gapmin.get() else "disabled")

    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a LS-DYNA .k file", filetypes=self._K_FILETYPES)
        if path:
            self.in_path.set(path)

    def _pick_output(self) -> None:
        initial = ""
        if self.in_path.get():
            initial = str(Path(self.in_path.get()).with_suffix("").name)
        path = filedialog.asksaveasfilename(
            title="Output stem (without _0000.rad)", initialfile=initial,
            confirmoverwrite=False)
        if path:
            # Strip a trailing _0000/_0001(.rad) if the user picked a generated file.
            path = re.sub(r"_000[01](\.rad)?$", "", path)
            self.out_stem.set(path)

    def _open_output(self) -> None:
        if self._last_out_dir and os.path.isdir(self._last_out_dir):
            try:
                os.startfile(self._last_out_dir)            # Windows
            except AttributeError:                          # pragma: no cover
                self._append(f"\nOutput folder: {self._last_out_dir}\n")

    # ── conversion (threaded) ────────────────────────────────────────────────

    def _on_convert(self) -> None:
        try:
            kwargs = build_convert_kwargs(
                self.in_path.get(), self.out_stem.get(),
                (self.u_mass.get(), self.u_len.get(), self.u_time.get()),
                ground_springs=self.ground.get(),
                ground_spring_k_text=self.ground_k.get(),
                soften_stfac_text=self.stfac.get(),
                tie_stfac_text=self.tie_stfac.get(),
                tet10_to_tet4=self.tet10.get(),
                auto_gapmin=self.auto_gapmin.get(),
                gapmin_factor_text=self.gapmin_factor.get(),
                derived_gapmin=self.derived_gapmin.get(),
                derived_gapmin_factor_text=self.derived_gapmin_factor.get(),
                rigid_secondary_swap=self.rigid_secondary_swap.get(),
                deformable_to_rigid=self.deformable_to_rigid.get(),
                fixpoint_count_text=self.fixpoint_count.get(),
                qstat_dtscal_text=self.qstat_dtscal.get(),
                arclength_riks=self.arclength_riks.get(),
                zero_tolerance_ectol=self.zero_tolerance_ectol.get(),
                implicit_constant_step=self.implicit_constant_step.get(),
                discrete_offset=self.discrete_offset.get(),
                spring_token_mass_compensation=self.spring_token_mass_comp.get(),
                shell_to_solid_rbody=self.shell_to_solid_rbody.get(),
                generalized_weld_butt=self.generalized_weld_butt.get(),
                initial_void_floor=self.initial_void_floor.get(),
                weld_exponents=self.weld_exponents.get(),
                constrained_linear=self.constrained_linear.get(),
                constrained_global=self.constrained_global.get(),
                spotweld_node_synthesis=self.spotweld_node_synthesis.get(),
                beam_contact_secondary=self.beam_contact_secondary.get(),
                shell_offset_gapmin=self.shell_offset_gapmin.get(),
                rigid_shell_rotary_inertia=(
                    self.rigid_shell_rotary_inertia.get()),
                spotweld_shear_yield=self.spotweld_shear_yield.get(),
                spotweld_efail_displacement=(
                    self.spotweld_efail_displacement.get()),
                implicit_tshell_solid=self.implicit_tshell_solid.get(),
                corotational_orthotropic=(
                    self.corotational_orthotropic.get()),
                mat_null_pc_mu=self.mat_null_pc_mu.get(),
                joint_screw_gjoint=self.joint_screw_gjoint.get(),
                rigid_local_constraints=self.rigid_local_constraints.get(),
                bcs_union=self.bcs_union.get(),
                bolt_rigid_contact=self.bolt_rigid_contact.get(),
                fixed_curve_columns=self.fixed_curve_columns.get(),
                section_nodal_thickness_mean=self.section_nodal_thickness_mean.get(),
                plane_strain_unit_thickness=self.plane_strain_unit_thickness.get(),
                rigid_element_mass_admas=self.rigid_element_mass_admas.get(),
                spotweld_dt_mass_scaling=self.spotweld_dt_mass_scaling.get(),
                adaptive_spring_token=self.adaptive_spring_token.get(),
                imflag0_eigen_explicit=self.imflag0_eigen_explicit.get(),
                implicit_smooth_curve_sampling=self.implicit_smooth_curve_sampling.get(),
                elastic_fluid_cp_cutoff=self.elastic_fluid_cp_cutoff.get(),
                implicit_stub_with_type25=self.implicit_stub_with_type25.get(),
                tgmult_imptemp=self.tgmult_imptemp.get(),
                deformable_contact_recipe=self.deformable_recipe.get(),
                blast_ground=self.blast_ground.get(),
                rigid_cog_master=self.rigid_cog.get(),
                zero_density_floor=self.zero_density_floor.get(),
                law106_shell_restate=self.law106_shell_restate.get(),
                zero_t0_sentinel=self.zero_t0_sentinel.get(),
                node_tc_rc_bcs=self.node_tc_rc_bcs.get(),
                default_hourglass=self.default_hourglass.get(),
                assumed_strain_isolid=self.assumed_strain_isolid.get(),
                implicit_rigid_secondary_swap=(
                    self.implicit_rigid_secondary_swap.get()),
                mass_weighted_inivel=self.mass_weighted_inivel.get(),
                write_restart=self.write_restart.get(),
                ams=self.ams.get(),
                shell_formulation=self.shell_formulation.get(),
                dt_del=self.dt_del.get(),
                he_bunreacted=self.he_bunreacted.get(),
                ale_multimat_law51=self.ale_multimat_law51.get(),
                eroding_surf_ext=self.eroding_surf_ext.get(),
                airbag_particle_uniform=self.airbag_particle_uniform.get(),
            )
        except ValueError as exc:
            self._reset_log()
            self._append(f"Cannot convert:\n  {exc}\n")
            self.status.set("Fix the highlighted input and try again.")
            return

        self._reset_log()
        self._append(f"Converting: {kwargs['input_path']}\n")
        self._describe_options(kwargs)
        self._convert_btn.config(state="disabled")
        self._open_btn.config(state="disabled")
        self.progress.set(0.0)
        self.status.set("Converting… (large meshes can take a while)")

        threading.Thread(target=self._worker, args=(kwargs,), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, kwargs: dict) -> None:
        try:
            result = convert(
                progress=lambda fr, lab: self._queue.put(("progress", (fr, lab))),
                **kwargs)
            self._queue.put(("ok", result))
        except Exception:                                    # noqa: BLE001
            self._queue.put(("err", traceback.format_exc()))

    def _poll(self) -> None:
        done = False
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    frac, label = payload
                    self.progress.set(frac * 100.0)
                    self.status.set(f"{int(frac * 100)}%  {label}")
                elif kind == "err":
                    self._append("\nConversion FAILED:\n")
                    self._append(payload)
                    self.status.set("Conversion failed — see the log.")
                    self.progress.set(0.0)
                    done = True
                else:  # ("ok", result)
                    self._show_result(payload)
                    done = True
        except queue.Empty:
            pass

        if done:
            self._convert_btn.config(state="normal")
        else:
            self.root.after(100, self._poll)

    def _show_result(self, result) -> None:
        self._last_out_dir = str(Path(result.starter_path).resolve().parent)
        self._append(f"\n  Starter -> {result.starter_path}\n")
        self._append(f"  Engine  -> {result.engine_path}\n")
        if getattr(result, "log_path", None):
            self._append(f"  Log     -> {result.log_path}\n")
        if result.skipped_keywords:
            self._append(f"\n  Skipped (unsupported) keywords ({len(result.skipped_keywords)}):\n")
            for kw in result.skipped_keywords:
                self._append(f"    *{kw}\n")
        if result.warnings:
            self._append(f"\n  Warnings ({len(result.warnings)}):\n")
            for w in result.warnings:
                self._append(f"    - {w}\n", tag="warn")
        done = "Done (with warnings)." if (result.warnings or result.skipped_keywords) else "Done."
        self._append(f"\n{done}\n")
        self.status.set(done)
        self.progress.set(100.0)
        self._open_btn.config(state="normal")

    def _describe_options(self, kwargs: dict) -> None:
        bits = []
        if kwargs.get("tet10_to_tet4"):
            bits.append("TET10→TET4 downgrade")
        if kwargs.get("fixpoint_count", 0) != 0:
            bits.append(f"fixpoint count={kwargs['fixpoint_count']}")
        if kwargs.get("ground_springs"):
            bits.append(f"ground springs (K={kwargs.get('ground_spring_k', 100.0):g})")
        if kwargs.get("auto_gapmin"):
            bits.append(f"auto gapmin (factor={kwargs.get('gapmin_factor', 0.8):g})")
        if kwargs.get("derived_gapmin"):
            bits.append("derived gapmin on solid-only mains (factor="
                        f"{kwargs.get('derived_gapmin_factor', 0.005):g})")
        if not kwargs.get("rigid_secondary_swap", True):
            bits.append("all-rigid-SSID contacts dropped "
                        "(--no-rigid-secondary-swap)")
        if not kwargs.get("deformable_to_rigid", True):
            bits.append("*DEFORMABLE_TO_RIGID parts left deformable "
                        "(--no-deformable-to-rigid)")
        if kwargs.get("inter_gapmin"):
            bits.append("gapmin " + ", ".join(f"{i}={v:g}" for i, v in kwargs["inter_gapmin"].items()))
        if kwargs.get("soften_stfac") is not None:
            bits.append(f"soften Stfac={kwargs['soften_stfac']:g}")
        if kwargs.get("tie_stfac") is not None:
            _ts = kwargs["tie_stfac"]
            bits.append("tie STFAC=" + (_ts if isinstance(_ts, str)
                                        else f"{_ts:g}"))
        if "qstat_dtscal" in kwargs:
            _qd = kwargs["qstat_dtscal"]
            bits.append("/IMPL/QSTAT/DTSCAL=" + (_qd if isinstance(_qd, str)
                                                 else f"{_qd:g}"))
        if kwargs.get("arclength_riks"):
            bits.append("arc-length /IMPL/DT/3 (--arclength-riks)")
        if not kwargs.get("zero_tolerance_ectol", True):
            bits.append("all-zero implicit tolerances keep Itol 2 "
                        "(--no-zero-tolerance-ectol)")
        if kwargs.get("implicit_constant_step"):
            bits.append("implicit step capped at DT0 "
                        "(--implicit-constant-step)")
        if not kwargs.get("discrete_offset", True):
            bits.append("*ELEMENT_DISCRETE OFFSET dropped "
                        "(--no-discrete-offset)")
        if not kwargs.get("spring_token_mass_compensation", True):
            bits.append("spring token mass left on the nodes "
                        "(--no-spring-token-mass-compensation)")
        if not kwargs.get("shell_to_solid_rbody", True):
            bits.append("*CONSTRAINED_SHELL_TO_SOLID dropped "
                        "(--no-shell-to-solid-rbody)")
        if not kwargs.get("generalized_weld_butt", True):
            bits.append("*CONSTRAINED_GENERALIZED_WELD_BUTT dropped "
                        "(--no-generalized-weld-butt)")
        if not kwargs.get("initial_void_floor", True):
            bits.append("*INITIAL_VOID fluids get no cavitation floor "
                        "(--no-initial-void-floor)")
        if not kwargs.get("weld_exponents", True):
            bits.append("spotweld failure exponents left at 2 "
                        "(--no-weld-exponents)")
        if not kwargs.get("constrained_linear", True):
            bits.append("*CONSTRAINED_LINEAR_* left unconverted "
                        "(--no-constrained-linear)")
        if not kwargs.get("constrained_global", True):
            bits.append("*CONSTRAINED_GLOBAL planes left free "
                        "(--no-constrained-global)")
        if kwargs.get("spotweld_node_synthesis"):
            bits.append("one-node spotweld beams get their second node "
                        "(--spotweld-node-synthesis)")
        if kwargs.get("beam_contact_secondary"):
            bits.append("beam and truss nodes join contact sides "
                        "(--beam-contact-secondary)")
        if not kwargs.get("shell_offset_gapmin", True):
            bits.append("starter-derived gap kept against offset shells "
                        "(--no-shell-offset-gapmin)")
        if not kwargs.get("rigid_shell_rotary_inertia", True):
            bits.append("rigid part bodies keep J = 0 "
                        "(--no-rigid-shell-rotary-inertia)")
        if not kwargs.get("spotweld_shear_yield", True):
            bits.append("spotweld shear kept elastic "
                        "(--no-spotweld-shear-yield)")
        if not kwargs.get("spotweld_efail_displacement", True):
            bits.append("spotweld EFAIL kept dropped "
                        "(--no-spotweld-efail-displacement)")
        if not kwargs.get("implicit_tshell_solid", True):
            bits.append("implicit thick shells kept on /PROP/TYPE20 "
                        "(--no-implicit-tshell-solid)")
        if not kwargs.get("corotational_orthotropic", True):
            bits.append("element-frame /PROP/TYPE6 left as 65ff389 "
                        "(--no-corotational-orthotropic)")
        if not kwargs.get("mat_null_pc_mu", True):
            bits.append("*MAT_NULL PC / MU cells not carried: Pmin 0 = "
                        "-INFINITY, Nu 0 (--no-mat-null-pc-mu)")
        if not kwargs.get("joint_screw_gjoint", True):
            bits.append("*CONSTRAINED_JOINT_SCREW left skipped "
                        "(--no-joint-screw-gjoint)")
        if not kwargs.get("rigid_local_constraints", True):
            bits.append("*MAT_RIGID CMO -1 written as nothing "
                        "(--no-rigid-local-constraints)")
        if not kwargs.get("bcs_union", True):
            bits.append("every *BOUNDARY_SPC card and the free-node guard written "
                        "as before (--no-bcs-union)")
        if not kwargs.get("bolt_rigid_contact", True):
            bits.append("bolt-end rigid members removed from contact secondary "
                        "sides (--no-bolt-rigid-contact)")
        if not kwargs.get("fixed_curve_columns", True):
            bits.append("*DEFINE_CURVE read by the whitespace split alone "
                        "(--no-fixed-curve-columns)")
        if not kwargs.get("section_nodal_thickness_mean", True):
            bits.append("*SECTION_SHELL written with T1 only "
                        "(--no-section-nodal-thickness-mean)")
        if not kwargs.get("plane_strain_unit_thickness", True):
            bits.append("plane-strain *SECTION_SHELL written with its stated T1 "
                        "(--no-plane-strain-unit-thickness)")
        if not kwargs.get("rigid_element_mass_admas", True):
            bits.append("rigid secondary *ELEMENT_MASS folded / dropped as before "
                        "(--no-rigid-element-mass-admas)")
        if not kwargs.get("spotweld_dt_mass_scaling", True):
            bits.append("*MAT_SPOTWELD DT dropped (--no-spotweld-dt-mass-scaling)")
        if not kwargs.get("adaptive_spring_token", True):
            bits.append("fixed 1e-4 spring token MASS "
                        "(--no-adaptive-spring-token)")
        if not kwargs.get("imflag0_eigen_explicit", True):
            bits.append("IMFLAG-0 / NEIG-0 eigen deck kept on the modal route "
                        "(--no-imflag0-eigen-explicit)")
        if not kwargs.get("implicit_smooth_curve_sampling", True):
            bits.append("implicit smooth curves kept as /FUNCT_SMOOTH "
                        "(--no-implicit-smooth-curve-sampling)")
        if not kwargs.get("elastic_fluid_cp_cutoff", True):
            bits.append("*MAT_ELASTIC_FLUID CP 0.0 kept at Pmin 0 "
                        "(--no-elastic-fluid-cp-cutoff)")
        if kwargs.get("implicit_stub_with_type25"):
            bits.append("implicit stub kept beside TYPE25 contacts "
                        "(--implicit-stub-with-type25)")
        if not kwargs.get("tgmult_imptemp", True):
            bits.append("*MAT_THERMAL_* TGMULT dropped "
                        "(--no-tgmult-imptemp)")
        if kwargs.get("deformable_contact_recipe"):
            bits.append("deformable-deformable contact recipe")
        if kwargs.get("blast_ground", "auto") != "auto":
            bits.append(f"blast ground={kwargs['blast_ground']}")
        if not kwargs.get("rigid_cog_master", True):
            bits.append("mesh-node rigid masters (--no-rigid-cog-master)")
        if not kwargs.get("zero_density_floor", True):
            bits.append("deck's own RO <= 0 kept (--no-zero-density-floor)")
        if not kwargs.get("law106_shell_restate", True):
            bits.append("/MAT/LAW106 kept on shells, no thermal expansion "
                        "(--no-law106-shell-restate)")
        if not kwargs.get("zero_t0_sentinel", True):
            bits.append("stated T = 0 written as 0 (--no-zero-t0-sentinel)")
        if not kwargs.get("node_tc_rc_bcs", True):
            bits.append("*NODE TC/RC constraints left free "
                        "(--no-node-tc-rc-bcs)")
        if not kwargs.get("default_hourglass", True):
            bits.append("defaulted 1-point solids left at Isolid 17 with no "
                        "hourglass control (--no-default-hourglass)")
        if kwargs.get("assumed_strain_isolid", "none") != "none":
            bits.append("ELFORM -1/-2 on Isolid "
                        f"{kwargs['assumed_strain_isolid']} "
                        "(--assumed-strain-isolid "
                        f"{kwargs['assumed_strain_isolid']})")
        if kwargs.get("implicit_rigid_secondary_swap"):
            bits.append("implicit all-rigid-SSID contacts SWAPPED with the "
                        "derived Gapmin (--implicit-rigid-secondary-swap)")
        if kwargs.get("mass_weighted_inivel"):
            bits.append("partly covered rigid bodies get the momentum-average "
                        "initial velocity (--mass-weighted-inivel)")
        if kwargs.get("write_restart"):
            bits.append("keep restart (.rst) files")
        if kwargs.get("ams"):
            bits.append("Advanced Mass Scaling (/DT/AMS)")
        if kwargs.get("ale_multimat_law51"):
            bits.append("synthesized /MAT/LAW51 for *ALE_MULTI-MATERIAL_GROUP "
                        "(--ale-multimat-law51)")
        if kwargs.get("eroding_surf_ext"):
            bits.append("eroding contacts on /SURF/PART/EXT (no interior re-exposure)")
        if kwargs.get("airbag_particle_uniform"):
            bits.append("*AIRBAG_PARTICLE as uniform-pressure /MONVOL/AIRBAG1")
        if kwargs.get("he_bunreacted") is not None:
            bits.append(f"Bunreacted={kwargs['he_bunreacted']:g}")
        self._append("  Options: " + (", ".join(bits) if bits else "standard (no extra options)") + "\n")

    # ── log helpers ──────────────────────────────────────────────────────────

    def _reset_log(self) -> None:
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _append(self, text: str, tag: "str | None" = None) -> None:
        self._log.config(state="normal")
        if tag:
            self._log.insert("end", text, tag)
        else:
            self._log.insert("end", text)
        self._log.see("end")
        self._log.config(state="disabled")


def main() -> int:
    if not _HAVE_TK:
        print("ERROR: tkinter is not available in this Python.\n"
              "Install it (Windows: reinstall Python with 'tcl/tk and IDLE';\n"
              "Linux: apt install python3-tk) or use the CLI: python k2rad.py model.k",
              file=sys.stderr)
        return 1
    root = tk.Tk()
    ConverterGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
