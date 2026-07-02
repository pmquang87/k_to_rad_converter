#!/usr/bin/env python3
"""
modal_shapes_export.py – view the eigenmode shapes of a k2rad modal run.

Reads the ``<jobname>_modes.npz`` written by tools/modal_solve.py plus the
source LS-DYNA ``.k`` and writes the mode shapes in the two formats the
household post-processors open natively:

* **LS-PrePost** — ``<jobname>_modes.d3plot`` + ``<jobname>_modes.d3plot01``:
  a d3plot family in the style of LS-DYNA's d3eigv.  The mesh plus ONE state
  per mode; the state *time* equals the mode frequency in Hz and the nodal
  displacements are the mass-normalized shape (TX/TY/TZ rows of phi,
  constrained nodes zero).  Open the root file in LS-PrePost and step through
  the states to browse the modes; use ``Settings → General Settings → SF for
  displacement`` (or the Anim scale) to exaggerate the shapes —
  mass-normalized amplitudes are physical, not scaled.  Keep the two files
  together: the root holds only the geometry (opens with 0 states alone).
  (Naming the file ``d3eigv`` does NOT help: LS-PrePost's d3eigv reader
  expects LS-DYNA's extra eigen records and then reads 0 states — verified
  with LS-PrePost 4.13.  A plain d3plot name reads all states.)

* **ParaView** — ``<jobname>_modes_vtk/mode_01_44.5Hz.vtk`` …: one legacy
  ASCII unstructured-grid file per mode with a point-data VECTORS array
  ``mode_shape`` (plus its magnitude as SCALARS), so *Warp By Vector* works
  out of the box.  ``--animate N`` additionally writes N sinusoidal frames per
  mode plus a ParaView ``.series`` index for direct animation playback.

Frequencies: the npz stores cycles per deck TIME unit.  The tool converts the
labels to Hz using ``--time-unit`` (default ``auto`` – guessed from the deck's
gravity magnitude or material wave speed + model size, and printed; a kg-mm-ms
deck gives ×1000).

Shape scaling: shapes are exported mass-normalized (the physical content of
the npz).  Rotation-dominated modes (e.g. a lumped *ELEMENT_MASS node pivoting
about its shell patch) can look near-invisible in raw scaling — use
``--normalize PCT`` to rescale every mode so its peak displacement equals
PCT % of the model bounding-box diagonal (display-only convenience).

Usage
-----
    python tools/modal_shapes_export.py <jobname>_modes.npz <model.k>
           [-o STEM] [--formats d3plot,vtk] [--time-unit auto|s|ms]
           [--modes 1,3-5] [--scale F] [--normalize PCT] [--animate N]

Dependencies: numpy (both formats) + lasso-python (d3plot only; the VTK export
runs without it).  See docs/DEPENDENCIES.md.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modal_common import (                       # noqa: E402
    Mesh, ModeSet, _HAVE_NUMPY, build_mesh, default_output_stem,
    freq_scale_from_args, load_modes, parse_deck, parse_mode_list,
    shapes_on_mesh, write_vtk,
)

if _HAVE_NUMPY:                                  # pragma: no branch
    import numpy as np


def have_lasso() -> bool:
    """lasso-python present? (heavy import — only done when d3plot is wanted)."""
    try:                                         # pragma: no cover - env dependent
        import lasso.dyna                        # noqa: F401
        return True
    except ImportError:                          # pragma: no cover - env dependent
        return False


# ─────────────────────────────────────────────────────────────────────────────
# d3plot writer (LS-PrePost)
# ─────────────────────────────────────────────────────────────────────────────

def _d3plot_shell_conn(mesh: Mesh) -> "np.ndarray":
    """(n_shells, 4) 0-based indexes; triangles repeat their last node."""
    conn = np.empty((len(mesh.shell_conn), 4), dtype=np.int64)
    for i, c in enumerate(mesh.shell_conn):
        conn[i] = c + [c[2]] if len(c) == 3 else c
    return conn


def _d3plot_solid_conn(mesh: Mesh) -> "np.ndarray":
    """(n_solids, 8) 0-based indexes; tets repeat node 4 (LS-DYNA convention);
    10-node tets keep their 4 corners (d3plot has no quadratic solids)."""
    conn = np.empty((len(mesh.solid_conn), 8), dtype=np.int64)
    for i, c in enumerate(mesh.solid_conn):
        c = c[:4] if len(c) == 10 else c
        conn[i] = c + [c[-1]] * (8 - len(c)) if len(c) < 8 else c[:8]
    return conn


def _remove_d3plot_family(path: str) -> None:
    """Delete ``path`` and every ``path<NN>`` continuation file, matching
    case-insensitively.

    lasso's ``write_d3plot`` writes the states to ``<path>01`` in APPEND mode
    and its own pre-write cleanup matches family members case-SENSITIVELY, so
    on a Windows filesystem a re-export over an existing family with different
    name casing would silently append a second copy of every state — which
    makes LS-PrePost segfault on open (observed with LS-PrePost 4.13).
    """
    import re
    d = Path(path).parent
    if not d.is_dir():
        return
    pat = re.compile(re.escape(Path(path).name) + r"[0-9]*$", re.IGNORECASE)
    for f in d.iterdir():
        if f.is_file() and pat.match(f.name):
            f.unlink()


def write_modes_d3plot(path: str, mesh: Mesh, freq_hz: "np.ndarray",
                       disp: "np.ndarray", title: str = "k2rad eigenmodes") -> List[str]:
    """d3plot family with a state per mode: state time = frequency [Hz], state
    geometry = undeformed coordinates + shape.  (In the d3plot format the
    per-state "displacement" array holds the deformed coordinates; LS-PrePost
    derives the displacement fringe against the base geometry itself.)

    Returns the file paths written: ``path`` (geometry) + ``path01`` (states)
    — lasso always writes the states to a ``<path>01`` continuation file, the
    standard d3plot family layout.  Keep the two files together: the root
    alone opens with 0 states.
    """
    from lasso.dyna import D3plot, ArrayType

    _remove_d3plot_family(path)
    d3 = D3plot()
    A = d3.arrays
    A[ArrayType.node_ids] = mesh.node_ids
    A[ArrayType.node_coordinates] = mesh.coords
    if len(mesh.shell_conn):
        A[ArrayType.element_shell_ids] = mesh.shell_ids
        A[ArrayType.element_shell_node_indexes] = _d3plot_shell_conn(mesh)
        A[ArrayType.element_shell_part_indexes] = mesh.shell_part
    if len(mesh.solid_conn):
        A[ArrayType.element_solid_ids] = mesh.solid_ids
        A[ArrayType.element_solid_node_indexes] = _d3plot_solid_conn(mesh)
        A[ArrayType.element_solid_part_indexes] = mesh.solid_part
    if len(mesh.beam_conn):
        beam = np.zeros((len(mesh.beam_conn), 5), dtype=np.int64)
        for i, c in enumerate(mesh.beam_conn):
            beam[i, :2] = c
        A[ArrayType.element_beam_ids] = mesh.beam_ids
        A[ArrayType.element_beam_node_indexes] = beam
        A[ArrayType.element_beam_part_indexes] = mesh.beam_part
    A[ArrayType.part_ids] = mesh.part_ids
    A[ArrayType.part_ids_unordered] = mesh.part_ids
    A[ArrayType.part_titles_ids] = mesh.part_ids
    A[ArrayType.part_titles] = np.char.encode(
        np.array(mesh.part_titles, dtype="U72"), encoding="utf-8")
    A[ArrayType.part_ids_cross_references] = np.arange(
        1, len(mesh.part_ids) + 1, dtype=np.int64)

    A[ArrayType.global_timesteps] = np.asarray(freq_hz, dtype=np.float64)
    A[ArrayType.node_displacement] = mesh.coords[np.newaxis, :, :] + disp

    # the d3plot title field is 10 words; with lasso's default 4-byte words
    # that is 40 bytes — a longer title corrupts the header byte checksum
    d3.header.title = title[:40]
    d3.write_d3plot(path, single_file=True)
    written = [path]
    if Path(path + "01").is_file():
        written.append(path + "01")
    return written


# ─────────────────────────────────────────────────────────────────────────────
# VTK writer (ParaView)
# ─────────────────────────────────────────────────────────────────────────────

def write_modes_vtk(out_dir: str, mesh: Mesh, freq_hz: "np.ndarray",
                    disp: "np.ndarray", mode_numbers: List[int],
                    animate: int = 0) -> List[str]:
    """One ``mode_MM_<f>Hz.vtk`` per mode (vector ``mode_shape`` ready for
    Warp By Vector).  With ``animate`` = N > 0 also writes N sinusoidal frames
    per mode + a ParaView ``.vtk.series`` index (time axis = seconds of one
    vibration period).

    Stale ``mode_*`` files/animation folders from a previous export are
    removed first — a re-solve with fewer modes (e.g. the deck's neig default)
    must not leave old higher-mode files lying around.
    """
    import re
    import shutil
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stale = re.compile(r"mode_\d+_.*Hz(\.vtk$|_anim$)")
    for entry in out.iterdir():
        if stale.match(entry.name):
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    written: List[str] = []
    for k, m in enumerate(mode_numbers):
        f = freq_hz[k]
        base = f"mode_{m:02d}_{f:.1f}Hz"
        d = disp[k]
        mag = np.linalg.norm(d, axis=1)
        path = out / f"{base}.vtk"
        write_vtk(str(path), mesh,
                  comment=f"k2rad mode {m}  f={f:.4f} Hz (mass-normalized shape)",
                  point_vectors={"mode_shape": d},
                  point_scalars={"mode_shape_magnitude": mag})
        written.append(str(path))
        if animate > 0:
            frame_dir = out / f"{base}_anim"
            frame_dir.mkdir(exist_ok=True)
            period = 1.0 / f if f > 0 else 1.0
            entries = []
            for j in range(animate):
                phase = math.sin(2.0 * math.pi * j / animate)
                fp = frame_dir / f"{base}_f{j:03d}.vtk"
                write_vtk(str(fp), mesh,
                          comment=f"k2rad mode {m} frame {j}/{animate}",
                          points=mesh.coords + phase * d,
                          point_vectors={"mode_shape": phase * d},
                          point_scalars={"mode_shape_magnitude": phase * mag})
                entries.append(f'    {{ "name" : "{fp.name}", '
                               f'"time" : {j * period / animate:.6G} }}')
            series = frame_dir / f"{base}.vtk.series"
            with open(series, "w", newline="\n") as fh:
                fh.write('{\n  "file-series-version" : "1.0",\n  "files" : [\n'
                         + ",\n".join(entries) + "\n  ]\n}\n")
            written.append(str(series))
    return written


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="modal_shapes_export",
        description="Export k2rad modal_solve.py mode shapes as an LS-PrePost "
                    "d3plot (one state per mode, state time = frequency in Hz) "
                    "and per-mode ParaView VTK files.")
    ap.add_argument("npz", help="<jobname>_modes.npz from tools/modal_solve.py")
    ap.add_argument("k_file", help="source LS-DYNA .k file (the mesh)")
    ap.add_argument("-o", "--output-stem", default=None, metavar="STEM",
                    help="output base path (default: the npz path without "
                         "'_modes.npz')")
    ap.add_argument("--formats", default="d3plot,vtk", metavar="LIST",
                    help="comma list of outputs: d3plot,vtk (default both)")
    ap.add_argument("--time-unit", choices=("auto", "s", "ms"), default="auto",
                    help="deck time unit for the Hz labels (default auto: "
                         "guessed from gravity / wave speed and printed)")
    ap.add_argument("--modes", default=None, metavar="LIST",
                    help="modes to export, e.g. '1,3-5' (default: all)")
    ap.add_argument("--scale", type=float, default=1.0, metavar="F",
                    help="uniform scale factor on all shapes (default 1 = raw "
                         "mass-normalized)")
    ap.add_argument("--normalize", type=float, default=0.0, metavar="PCT",
                    help="rescale each mode so its peak displacement is PCT%% "
                         "of the model bounding-box diagonal (default off; "
                         "display-only convenience)")
    ap.add_argument("--animate", type=int, default=0, metavar="N",
                    help="also write N sinusoidal VTK frames per mode plus a "
                         "ParaView .series index (default off)")
    args = ap.parse_args(argv)

    if not _HAVE_NUMPY:
        print("ERROR: numpy is required (pip install numpy - see "
              "docs/DEPENDENCIES.md)", file=sys.stderr)
        return 1
    formats = {f.strip().lower() for f in args.formats.split(",") if f.strip()}
    unknown = formats - {"d3plot", "vtk"}
    if unknown:
        print(f"ERROR: unknown --formats entries {sorted(unknown)} "
              "(use d3plot,vtk)", file=sys.stderr)
        return 1

    print(f"Reading mode shapes:  {args.npz}")
    modes = load_modes(args.npz)
    print(f"Parsing mesh:         {args.k_file}")
    state = parse_deck(args.k_file)
    mesh = build_mesh(state)
    for w in mesh.warnings:
        print(f"  WARNING: {w}")
    print(f"  {mesh.n_nodes} nodes, {len(mesh.shell_conn)} shells, "
          f"{len(mesh.solid_conn)} solids, {len(mesh.beam_conn)} beams, "
          f"{len(mesh.part_ids)} parts; {modes.n_modes} modes in the npz")

    scale_hz, reason = freq_scale_from_args(args.time_unit, state, mesh)
    print(f"  frequency unit: x{scale_hz:g} -> Hz ({reason})")

    picked = parse_mode_list(args.modes, modes.n_modes)
    freq_hz = modes.freq[[m - 1 for m in picked]] * scale_hz
    disp = shapes_on_mesh(mesh, modes)[[m - 1 for m in picked]]

    # Shape scaling: uniform --scale and/or per-mode --normalize.
    disp = disp * args.scale
    if args.normalize > 0.0:
        target = args.normalize / 100.0 * mesh.bbox_diagonal()
        for k in range(disp.shape[0]):
            peak = float(np.linalg.norm(disp[k], axis=1).max())
            if peak > 0.0:
                disp[k] *= target / peak

    print("\n  mode |    f [Hz] | peak displacement (as exported)")
    for k, m in enumerate(picked):
        peak = float(np.linalg.norm(disp[k], axis=1).max())
        print(f"  {m:4d} | {freq_hz[k]:9.2f} | {peak:.6G}")

    stem = args.output_stem or default_output_stem(args.npz)
    wrote_any = False

    if "d3plot" in formats:
        if have_lasso():
            d3_path = stem + "_modes.d3plot"
            try:
                files = write_modes_d3plot(
                    d3_path, mesh, freq_hz, disp,
                    title=f"{Path(stem).name} eigenmodes (t=f[Hz])")
            except Exception as exc:               # keep the VTK export alive
                print(f"\n  WARNING: d3plot export failed ({exc}) - "
                      "continuing with the VTK export.", file=sys.stderr)
            else:
                print(f"\n  LS-PrePost: {d3_path}")
                print(f"    family of {len(files)} file(s) (geometry + states "
                      "- keep them together); one state per mode; state time "
                      "= frequency [Hz]. Exaggerate with the displacement "
                      "scale factor.")
                wrote_any = True
        else:
            print("\n  WARNING: lasso-python not installed - skipping the "
                  "d3plot export (pip install lasso-python). The VTK export "
                  "does not need it.", file=sys.stderr)

    if "vtk" in formats:
        vtk_dir = stem + "_modes_vtk"
        files = write_modes_vtk(vtk_dir, mesh, freq_hz, disp, picked,
                                animate=args.animate)
        print(f"\n  ParaView:   {vtk_dir}{Path('/')}")
        print(f"    {len(files)} file(s): mode_MM_<f>Hz.vtk with point vector "
              "'mode_shape' - apply Warp By Vector.")
        if args.animate:
            print(f"    per-mode sinusoidal series: mode_MM_*_anim{Path('/')}"
                  "*.vtk.series (open the .series file).")
        wrote_any = True

    if not wrote_any:
        print("ERROR: nothing was written (no usable format).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
