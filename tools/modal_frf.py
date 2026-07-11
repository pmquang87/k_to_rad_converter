#!/usr/bin/env python3
"""
modal_frf.py – harmonic / frequency-response (FRF) output by modal superposition.

LS-DYNA's *FREQUENCY_DOMAIN_FRF (steady-state response to a harmonic
excitation) has no OpenRadioss equivalent, so k2rad computes it OFFLINE on top
of the modal results of tools/modal_solve.py.  This is the deterministic sister
of tools/modal_random_response.py: instead of integrating a response PSD it
sweeps a frequency band and reports the complex steady-state response at each
frequency.

Physics
-------
The modal FRF machinery is exactly the one already used (and validated) in
modal_random_response.py — this tool factors it out and reuses it.  For a
structure with mass-normalized modes φ_j and natural frequencies ω_j, modal
damping ζ, the modal amplitude of mode j at forcing frequency ω = 2πf is::

    q_j(f) = f_j / (ω_j² − ω² + 2·i·ζ·ω_j·ω)

and the physical response is the modal sum  u(x, f) = Σ_j φ_j(x)·q_j(f).

Two excitation types are supported:

* **Base excitation** (default): a uniform harmonic base acceleration of unit
  amplitude along a global direction.  The modal force is the participation
  factor with the relative-motion sign, f_j = −Γ_j, Γ_j = φ_jᵀ·M·r — i.e.
  q_j = H_j(f), the *same* modal FRF (relative displacement per base
  acceleration) that modal_random_response.frf_matrix() returns.  The reported
  response is the relative displacement per unit base acceleration.

* **Nodal harmonic load** (``--load NODE DIR [FORCE]``): a harmonic point force
  of amplitude FORCE on a single DOF.  The modal force is f_j = FORCE·φ_j(NODE,
  DIR) and the reported response is the displacement per that load.

Outputs (<stem> = npz path without _modes.npz; override with -o)
----------------------------------------------------------------
  <stem>_frf_node_<id>.csv  – per probe node: freq, |u|/phase per component + |u|_mag
  <stem>_frf_peaks.csv      – per probe node: peak |u|_mag and the frequency it occurs
  console                   – a resonance table: at each in-band mode, the node
                              with the largest response magnitude

Usage
-----
    python tools/modal_frf.py <jobname>_modes.npz <model.k>
        [--dir X|Y|Z] [--load NODE DIR [FORCE]] [--damping 0.02]
        [--fmin HZ] [--fmax HZ] [--nf N]
        [--probe-nodes N1 N2 ...] [--time-unit auto|s|ms] [-o STEM]

Validation
----------
Validated in tests/test_modal_analysis.py against:
* the closed-form single-DOF FRF — peak dynamic-amplification = 1/(2ζ) at
  resonance and half-power bandwidth Δf = 2ζ·f_n (both to <1 %);
* modal_random_response.frf_matrix() — the base-excitation coefficients are bit
  identical (the very same reused function).

Dependencies: numpy (scipy not needed).  See docs/DEPENDENCIES.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from k2rad.state import ConversionState                     # noqa: E402,F401
from modal_common import (                                  # noqa: E402
    ModeSet, _HAVE_NUMPY, build_mesh, default_output_stem,
    freq_scale_from_args, load_modes, parse_deck, shapes_on_mesh,
)
import modal_solve                                          # noqa: E402
from modal_random_response import (                         # noqa: E402
    excitation_direction, frequency_grid, frf_matrix, participation_factors,
)

if _HAVE_NUMPY:                                             # pragma: no branch
    import numpy as np

_DIR_TO_DOF = {"X": 1, "Y": 2, "Z": 3, "XX": 4, "YY": 5, "ZZ": 6,
               "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}


# ─────────────────────────────────────────────────────────────────────────────
# Modal FRF coefficients (reuse modal_random_response.frf_matrix)
# ─────────────────────────────────────────────────────────────────────────────

def base_modal_coeffs(modes_hz: "np.ndarray", grid_hz: "np.ndarray",
                      zeta: float, gamma: "np.ndarray") -> "np.ndarray":
    """Modal amplitudes q_j(f) per unit base acceleration (n_freq × n_modes).

    This is exactly modal_random_response.frf_matrix — the modal FRF
    H_j(f) = −Γ_j/(ω_j²−ω²+2iζω_jω) (relative displacement per base
    acceleration) — reused verbatim so FRF and random-vibration share one
    validated kernel.
    """
    return frf_matrix(modes_hz, grid_hz, zeta, gamma)


def load_modal_coeffs(modes_hz: "np.ndarray", grid_hz: "np.ndarray",
                      zeta: float, modal_force: "np.ndarray") -> "np.ndarray":
    """Modal amplitudes q_j(f) = f_j/(ω_j²−ω²+2iζω_jω) for a harmonic nodal load.

    Built from the same denominator as frf_matrix (which carries a −gamma
    numerator), so ``−frf_matrix(…, modal_force)`` yields ``+modal_force/den``.
    """
    return -frf_matrix(modes_hz, grid_hz, zeta, modal_force)


def assemble_response(coeffs: "np.ndarray", shapes: "np.ndarray") -> "np.ndarray":
    """Physical complex response u(f, …) = Σ_j q_j(f)·φ_j(…).

    ``coeffs`` is (n_freq, n_modes); ``shapes`` is (n_modes, …) — e.g.
    (n_modes, n_nodes, 3) translational mode shapes.  Returns (n_freq, …).
    """
    return np.einsum("fj,j...->f...", coeffs, shapes)


def nodal_modal_force(modes: ModeSet, node: int, dof: int,
                      force: float) -> "np.ndarray":
    """Generalized force f_j = force·φ_j(node, dof) for a harmonic point load."""
    sel = (modes.user_node == node) & (modes.dof == dof)
    if not sel.any():
        raise SystemExit(
            f"ERROR: node {node} DOF {dof} is not a free DOF of the modes "
            "(constrained, rigid-slaved, or absent) - cannot apply the load")
    return force * modes.phi[sel][0]


def frf_band(fmin_cli: Optional[float], fmax_cli: Optional[float],
             modes_hz: "np.ndarray") -> Tuple[float, float, str]:
    """Sweep band [Hz]: CLI --fmin/--fmax override the solved-modes ±50 % auto."""
    fmin = 0.5 * float(modes_hz.min())
    fmax = 1.5 * float(modes_hz.max())
    why = "solved modes +/-50%"
    if fmin_cli is not None:
        fmin, why = fmin_cli, why + f"; --fmin {fmin_cli:g}"
    if fmax_cli is not None:
        fmax, why = fmax_cli, why + f"; --fmax {fmax_cli:g}"
    if not (0.0 <= fmin < fmax):
        raise SystemExit(f"ERROR: bad frequency band {fmin:g}-{fmax:g} Hz")
    return fmin, fmax, why


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _write_csv(path: str, header: str, rows) -> None:
    with open(path, "w", newline="\n") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write(",".join(str(v) for v in r) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="modal_frf",
        description="Offline modal-superposition harmonic / frequency-response "
                    "(FRF) output from a k2rad modal run: steady-state complex "
                    "response to a harmonic base acceleration or a nodal load.")
    ap.add_argument("npz", help="<jobname>_modes.npz from tools/modal_solve.py")
    ap.add_argument("k_file", help="source LS-DYNA .k file")
    ap.add_argument("-o", "--output-stem", default=None, metavar="STEM")
    ap.add_argument("--damping", type=float, default=0.02, metavar="ZETA",
                    help="modal damping ratio (default 0.02 = 2%% critical)")
    ap.add_argument("--dir", default="auto", metavar="X|Y|Z",
                    help="base-excitation direction for unit harmonic base "
                         "acceleration (default: the deck's gravity direction, "
                         "else Z). Ignored when --load is given.")
    ap.add_argument("--load", nargs="+", default=None,
                    metavar="NODE DIR [FORCE]",
                    help="harmonic nodal load instead of base excitation: apply "
                         "FORCE (default 1.0) on user NODE along DIR "
                         "(X|Y|Z|XX|YY|ZZ)")
    ap.add_argument("--fmin", type=float, default=None, metavar="HZ",
                    help="sweep lower bound in Hz (default: lowest mode -50%%)")
    ap.add_argument("--fmax", type=float, default=None, metavar="HZ",
                    help="sweep upper bound in Hz (default: highest mode +50%%)")
    ap.add_argument("--nf", "--nfreq", type=int, default=600, dest="nf",
                    metavar="N", help="base frequency-grid points (default 600; "
                    "resonances get extra refinement)")
    ap.add_argument("--probe-nodes", type=int, nargs="+", default=None,
                    metavar="NODE", help="nodes for the per-node FRF spectra "
                    "(default: the 3 highest-response nodes)")
    ap.add_argument("--time-unit", choices=("auto", "s", "ms"), default="auto",
                    help="deck time unit (default auto, printed)")
    args = ap.parse_args(argv)

    if not _HAVE_NUMPY:
        print("ERROR: numpy is required (pip install numpy - see "
              "docs/DEPENDENCIES.md)", file=sys.stderr)
        return 1

    print(f"Reading mode shapes:  {args.npz}")
    modes = load_modes(args.npz)
    print(f"Parsing deck:         {args.k_file}")
    state = parse_deck(args.k_file)
    mesh = build_mesh(state)
    scale_hz, why = freq_scale_from_args(args.time_unit, state, mesh)
    print(f"  frequency unit: x{scale_hz:g} -> Hz ({why})")
    modes_hz = modes.freq * scale_hz
    print(f"  {modes.n_modes} modes: {modes_hz.min():.2f} .. "
          f"{modes_hz.max():.2f} Hz; damping {args.damping:g} "
          f"({100 * args.damping:g}% critical)")

    disp3 = shapes_on_mesh(mesh, modes, rotations=False)     # (m, n_nodes, 3)

    # ── Excitation → modal force per mode ────────────────────────────────────
    if args.load:
        node = int(args.load[0])
        try:
            dof = _DIR_TO_DOF[str(args.load[1]).upper()]
        except (KeyError, IndexError):
            print("ERROR: --load needs NODE DIR [FORCE] with DIR in "
                  "X|Y|Z|XX|YY|ZZ", file=sys.stderr)
            return 1
        force = float(args.load[2]) if len(args.load) > 2 else 1.0
        modal_force = nodal_modal_force(modes, node, dof, force)
        excite = (f"harmonic nodal load {force:g} on node {node} "
                  f"DOF {str(args.load[1]).upper()}")
        resp_unit = "displacement per unit load"

        def coeffs_fn(grid):
            return load_modal_coeffs(modes_hz, grid, args.damping, modal_force)
    else:
        direction, why_dir = excitation_direction(state, args.dir)
        node_mass, _ = modal_solve.nodal_masses_from_state(state)
        gamma = participation_factors(mesh, disp3, node_mass, direction)
        excite = (f"unit harmonic base acceleration along {'XYZ'[direction]} "
                  f"({why_dir})")
        resp_unit = "relative displacement per unit base acceleration"

        def coeffs_fn(grid):
            return base_modal_coeffs(modes_hz, grid, args.damping, gamma)

    # ── Frequency grid ───────────────────────────────────────────────────────
    fmin, fmax, why_band = frf_band(args.fmin, args.fmax, modes_hz)
    grid = frequency_grid(fmin, fmax, modes_hz, args.damping, args.nf)
    print(f"  excitation: {excite}")
    print(f"  response:   {resp_unit}")
    print(f"  band:       {fmin:g}-{fmax:g} Hz ({why_band}); "
          f"{len(grid)} frequency points")
    in_band = (modes_hz >= fmin) & (modes_hz <= fmax)
    if not in_band.any():
        print("  WARNING: NO solved mode lies inside the sweep band - the "
              "response is the small off-resonant tail. Override with "
              "--fmin/--fmax (Hz).")

    # ── Response ─────────────────────────────────────────────────────────────
    coeffs = coeffs_fn(grid)                                  # (n_freq, m)
    u3 = assemble_response(coeffs, disp3)                     # (n_freq, n_nodes, 3)
    umag = np.linalg.norm(np.abs(u3), axis=2)                # (n_freq, n_nodes)

    peak_per_node = umag.max(axis=0)                          # (n_nodes,)
    peak_freq_node = grid[np.argmax(umag, axis=0)]
    top = np.argsort(peak_per_node)[::-1]

    stem = args.output_stem or default_output_stem(args.npz)
    _write_csv(stem + "_frf_peaks.csv",
               "node,peak_mag,peak_freq_hz",
               ((int(mesh.node_ids[i]), f"{peak_per_node[i]:.6G}",
                 f"{peak_freq_node[i]:.6G}") for i in range(mesh.n_nodes)))

    probes = args.probe_nodes or [int(mesh.node_ids[i]) for i in top[:3]]
    written = []
    for nid in probes:
        i = mesh.nid_to_idx.get(int(nid))
        if i is None:
            print(f"  WARNING: probe node {nid} not in the mesh - skipped")
            continue
        comp = u3[:, i, :]                                    # (n_freq, 3)
        mag = np.abs(comp)
        ph = np.degrees(np.angle(comp))
        _write_csv(
            stem + f"_frf_node_{nid}.csv",
            "freq_hz,mag_ux,phase_ux_deg,mag_uy,phase_uy_deg,"
            "mag_uz,phase_uz_deg,mag_total",
            ((f"{grid[k]:.6G}", f"{mag[k, 0]:.6G}", f"{ph[k, 0]:.6G}",
              f"{mag[k, 1]:.6G}", f"{ph[k, 1]:.6G}",
              f"{mag[k, 2]:.6G}", f"{ph[k, 2]:.6G}",
              f"{umag[k, i]:.6G}") for k in range(len(grid))))
        written.append(nid)

    # ── Resonance-peak summary ──────────────────────────────────────────────
    print("\n  resonance peaks (largest nodal response near each in-band mode):")
    print("   mode |   f [Hz] |  node    |  peak |u|")
    for j in np.nonzero(in_band)[0]:
        k = int(np.argmin(np.abs(grid - modes_hz[j])))
        inode = int(np.argmax(umag[k]))
        print(f"   {j + 1:4d} | {modes_hz[j]:8.2f} | "
              f"{int(mesh.node_ids[inode]):8d} | {umag[k, inode]:.5G}")
    inode = int(top[0])
    print(f"  overall peak response {peak_per_node[inode]:.5G} at node "
          f"{int(mesh.node_ids[inode])}, f = {peak_freq_node[inode]:.2f} Hz")

    print(f"\n  outputs written with stem: {stem}")
    print(f"    _frf_peaks.csv; _frf_node_<id>.csv for node(s) "
          f"{', '.join(str(n) for n in written) or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
