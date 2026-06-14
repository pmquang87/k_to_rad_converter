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
                         gapmin_factor_text: str = "") -> dict:
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
        self.ground = tk.BooleanVar(value=False)
        self.ground_k = tk.StringVar(value="100")
        self.auto_gapmin = tk.BooleanVar(value=False)
        self.gapmin_factor = tk.StringVar(value="0.8")
        self.stfac = tk.StringVar()
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
                self._append(f"    - {w}\n")
        done = "Done (with warnings)." if (result.warnings or result.skipped_keywords) else "Done."
        self._append(f"\n{done}\n")
        self.status.set(done)
        self.progress.set(100.0)
        self._open_btn.config(state="normal")

    def _describe_options(self, kwargs: dict) -> None:
        bits = []
        if kwargs.get("tet10_to_tet4"):
            bits.append("TET10→TET4 downgrade")
        if kwargs.get("ground_springs"):
            bits.append(f"ground springs (K={kwargs.get('ground_spring_k', 100.0):g})")
        if kwargs.get("auto_gapmin"):
            bits.append(f"auto gapmin (factor={kwargs.get('gapmin_factor', 0.8):g})")
        if kwargs.get("inter_gapmin"):
            bits.append("gapmin " + ", ".join(f"{i}={v:g}" for i, v in kwargs["inter_gapmin"].items()))
        if kwargs.get("soften_stfac") is not None:
            bits.append(f"soften Stfac={kwargs['soften_stfac']:g}")
        self._append("  Options: " + (", ".join(bits) if bits else "standard (no extra options)") + "\n")

    # ── log helpers ──────────────────────────────────────────────────────────

    def _reset_log(self) -> None:
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _append(self, text: str) -> None:
        self._log.config(state="normal")
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
