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
                         inter_gapmin_text: str = "",
                         tet10_to_tet4: bool = False,
                         auto_gapmin: bool = False,
                         gapmin_factor_text: str = "",
                         fixpoint_count_text: str = "",
                         deformable_contact_recipe: bool = False,
                         blast_ground: str = "auto",
                         rigid_cog_master: bool = True,
                         write_restart: bool = False,
                         ams: bool = False,
                         shell_formulation: str = "qbat",
                         dt_del: str = "",
                         eroding_surf_ext: bool = False) -> dict:
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
    if fp_text:                                   # blank → convert() default (100)
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

    st = (soften_stfac_text or "").strip()
    if st:
        try:
            kwargs["soften_stfac"] = float(st)
        except ValueError:
            raise ValueError(f"Soften Stfac must be a number, got {st!r}.")

    kwargs["deformable_contact_recipe"] = bool(deformable_contact_recipe)

    bg = (blast_ground or "auto").strip() or "auto"
    if bg.lower() not in {"auto", "none", "x", "y", "z", "-x", "-y", "-z"}:
        raise ValueError(
            "Blast ground must be one of auto / none / X / Y / Z / -X / -Y / -Z, "
            f"got {bg!r}.")
    kwargs["blast_ground"] = bg

    kwargs["rigid_cog_master"] = bool(rigid_cog_master)

    kwargs["write_restart"] = bool(write_restart)

    kwargs["ams"] = bool(ams)

    kwargs["eroding_surf_ext"] = bool(eroding_surf_ext)

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
        self.fixpoint_count = tk.StringVar(value="100")
        self.blast_ground = tk.StringVar(value="auto")
        self.rigid_cog = tk.BooleanVar(value=True)
        self.write_restart = tk.BooleanVar(value=False)
        self.ams = tk.BooleanVar(value=False)
        self.eroding_surf_ext = tk.BooleanVar(value=False)
        # 'qbat' = today's behaviour; see the radio buttons below.
        self.shell_formulation = tk.StringVar(value="qbat")
        self.dt_del = tk.StringVar(value="")
        self.ground = tk.BooleanVar(value=False)
        self.ground_k = tk.StringVar(value="100")
        self.auto_gapmin = tk.BooleanVar(value=False)
        self.gapmin_factor = tk.StringVar(value="0.8")
        self.stfac = tk.StringVar()
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
                           "(1–100, default 100; 0 = off; implicit decks only)",
                  foreground="gray").pack(side="left")

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

        ttk.Label(fc, text="Soften Stfac:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(fc, textvariable=self.stfac, width=10).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(fc, text="penalty stiffness scale on all /INTER/TYPE7, e.g. 0.3 — blank = engine default; "
                           ".k-native per contact: Card-3 SFS (overridden by this field)",
                  foreground="gray").grid(row=4, column=1, columnspan=2, sticky="w", padx=6)

        rc = ttk.Frame(fc)
        rc.grid(row=5, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(
            rc, text="Deformable–deformable contact recipe (Inacti=5 + /IMPL/DT/2 L_dtn=50 "
                     "+ /IMPL/QSTAT/DTSCAL=0.05)",
            variable=self.deformable_recipe).pack(side="left")
        ttk.Label(fc, text="Use when two DEFORMABLE parts contact in an implicit deck (e.g. force control "
                           "through a clearance-fit deformable pin) and the solve chatters or stalls. "
                           "The converter warns when it detects such contact.",
                  foreground="gray").grid(row=6, column=1, columnspan=2, sticky="w", padx=6)

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

    # ── widget callbacks ─────────────────────────────────────────────────────

    def _sync_ground_k(self) -> None:
        self._ground_k_entry.config(state="normal" if self.ground.get() else "disabled")

    def _sync_gapmin_factor(self) -> None:
        self._gapmin_factor_entry.config(
            state="normal" if self.auto_gapmin.get() else "disabled")

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
                tet10_to_tet4=self.tet10.get(),
                auto_gapmin=self.auto_gapmin.get(),
                gapmin_factor_text=self.gapmin_factor.get(),
                fixpoint_count_text=self.fixpoint_count.get(),
                deformable_contact_recipe=self.deformable_recipe.get(),
                blast_ground=self.blast_ground.get(),
                rigid_cog_master=self.rigid_cog.get(),
                write_restart=self.write_restart.get(),
                ams=self.ams.get(),
                shell_formulation=self.shell_formulation.get(),
                dt_del=self.dt_del.get(),
                eroding_surf_ext=self.eroding_surf_ext.get(),
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
        if kwargs.get("fixpoint_count", 100) != 100:
            bits.append(f"fixpoint count={kwargs['fixpoint_count']}")
        if kwargs.get("ground_springs"):
            bits.append(f"ground springs (K={kwargs.get('ground_spring_k', 100.0):g})")
        if kwargs.get("auto_gapmin"):
            bits.append(f"auto gapmin (factor={kwargs.get('gapmin_factor', 0.8):g})")
        if kwargs.get("inter_gapmin"):
            bits.append("gapmin " + ", ".join(f"{i}={v:g}" for i, v in kwargs["inter_gapmin"].items()))
        if kwargs.get("soften_stfac") is not None:
            bits.append(f"soften Stfac={kwargs['soften_stfac']:g}")
        if kwargs.get("deformable_contact_recipe"):
            bits.append("deformable-deformable contact recipe")
        if kwargs.get("blast_ground", "auto") != "auto":
            bits.append(f"blast ground={kwargs['blast_ground']}")
        if not kwargs.get("rigid_cog_master", True):
            bits.append("mesh-node rigid masters (--no-rigid-cog-master)")
        if kwargs.get("write_restart"):
            bits.append("keep restart (.rst) files")
        if kwargs.get("ams"):
            bits.append("Advanced Mass Scaling (/DT/AMS)")
        if kwargs.get("eroding_surf_ext"):
            bits.append("eroding contacts on /SURF/PART/EXT (no interior re-exposure)")
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
