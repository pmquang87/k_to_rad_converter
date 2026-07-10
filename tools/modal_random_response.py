#!/usr/bin/env python3
"""
modal_random_response.py – random-vibration PSD/RMS/fatigue post-processing.

LS-DYNA's frequency-domain keywords *DATABASE_FREQUENCY_BINARY_D3PSD / D3RMS /
D3FTG and *MAT_ADD_FATIGUE have NO OpenRadioss equivalent, so k2rad implements
them OFFLINE on top of the modal results of tools/modal_solve.py: classic
modal-superposition random vibration of a base-excited structure.

Physics
-------
Uniform base acceleration a(t) with one-sided PSD S_a(f) along one global
direction; relative-motion formulation::

    M·ü + C·u̇ + K·u = -M·r·a(t),      r = unit translation along the direction

* participation factors  Γ_j = φ_jᵀ·M·r  (φ mass-normalized, so the effective
  modal mass is Γ_j²);
* modal FRF (relative displacement per base acceleration)::

      H_j(f) = -Γ_j / (ω_j² - ω² + 2·i·ζ·ω_j·ω),      ω = 2πf

* any response quantity  y = cᵀu  has the one-sided PSD
  S_y(f) = |Σ_j (cᵀφ_j)·H_j(f)|²·S_a(f) — the full modal superposition
  including all cross terms;
* RMS values come from the modal covariance  G_jk = ∫ Re(H_j·H_k*)·S_a df:
  σ_y² = Σ_jk (cᵀφ_j)(cᵀφ_k)·G_jk.

Element stresses use modal stress recovery: per-element strain-displacement
at the centroid (CST / bilinear quad shells with membrane+bending surfaces at
z = ±t/2, constant-strain tets, trilinear hexas) applied to each mode shape;
the equivalent von Mises stress PSD is Segalman's  G_vm(f) = tr(Q·S_σ(f))
with Q the von Mises quadratic form.  Fatigue damage integrates the Dirlik
stress-RANGE pdf (or the narrow-band Rayleigh pdf with --fatigue-method
narrowband) against the *MAT_ADD_FATIGUE S-N data:

    damage/s = E[P] · ∫ p(S) / N(S) dS,   E[P] = sqrt(m4/m2) peaks per second

with the spectral moments m_k = ∫ f^k·G_vm(f) df of each element's von Mises
PSD.  S-N data per *MAT_ADD_FATIGUE: curve (lcid, ltype 0=semi-log/1=log-log)
or power law N·S^b = a; sntype 0 means S is a stress RANGE (default), 1 an
amplitude; snlimt 0/1/2 = last-point life / extrapolate / no damage below the
curve; sthres = threshold below which stress ranges do no damage.

What the deck provides (and what it cannot)
-------------------------------------------
* The D3PSD card's fmin/fmax band (deck frequency units) is the default
  output/integration band.  NOTE: the LS-DYNA frequency-domain examples in
  kg-mm-ms units carry bands like 0.1–2.0 (= 100–2000 Hz) while their first
  modes sit far lower — the tool WARNS when no solved mode falls inside the
  band (the response is then the small off-resonant tail) and the band can be
  overridden with --fmin/--fmax (in Hz).
* The input acceleration PSD curve: the deck (converted from LS-PrePost's
  frequency-domain dialogs) does not carry *FREQUENCY_DOMAIN_RANDOM_VIBRATION,
  so the excitation is taken as BASE acceleration through the SPC support.
  The PSD curve is auto-picked (the only *DEFINE_CURVE not referenced as S-N
  data; override with --psd-curve).  Curve ordinate: acceleration²/frequency
  in deck units by default (a kg-mm-ms deck: (mm/ms²)²/kHz), or g²/Hz with
  --psd-unit g2hz (+ --g for the deck-unit value of g, default 9810 mm/s²).
* Excitation direction: --dir, default the deck's gravity direction
  (*LOAD_GRAVITY_PART, the vertical), else Z.
* Modal damping: --damping, default 0.02 (2 % critical) — the deck has no
  usable damping definition for the eigen recipe.

Outputs (<stem> = npz path without _modes.npz; override with -o)
----------------------------------------------------------------
  <stem>_rms_displacement.csv   – per node: RMS relative displacement X/Y/Z+mag  [D3RMS]
  <stem>_rms_stress.csv         – per element: RMS von Mises (worst surface)     [D3RMS]
  <stem>_fatigue.csv            – per element: m0..m4, damage/s, damage, life    [D3FTG]
  <stem>_psd_node_<id>.csv      – response-PSD spectra at probe nodes            [D3PSD]
  <stem>_random_vtk/random_response.vtk – all of the above as ParaView fields
  <stem>_fatigue_lsprepost.txt  – "eid life" pairs (the calculate_fatigue_pylife
                                  format, capped at 1e9 for fringe color scaling)

Usage
-----
    python tools/modal_random_response.py <jobname>_modes.npz <model.k>
        [--damping 0.02] [--dir auto|X|Y|Z] [--psd-curve LCID]
        [--psd-unit deck|g2hz] [--g 9810] [--curve-freq-unit deck|hz]
        [--fmin HZ] [--fmax HZ] [--nfreq N] [--duration SEC]
        [--fatigue-method dirlik|narrowband] [--probe-nodes N1 N2 ...]
        [--time-unit auto|s|ms] [-o STEM]

Dependencies: numpy (scipy not needed).  See docs/DEPENDENCIES.md.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from k2rad.state import ConversionState, MatAddFatigue   # noqa: E402
from modal_common import (                                # noqa: E402
    Mesh, _HAVE_NUMPY, build_mesh, default_output_stem,
    freq_scale_from_args, load_modes, parse_deck, shapes_on_mesh, write_vtk,
)
import modal_solve                                        # noqa: E402

if _HAVE_NUMPY:                                           # pragma: no branch
    import numpy as np

_DIRS = {"X": 0, "Y": 1, "Z": 2}
_LIFE_CAP = 1.0e9        # cap for the LS-PrePost fringe file (color scaling)


def _trapz(y, x, axis=-1):
    f = getattr(np, "trapezoid", None) or np.trapz
    return f(y, x, axis=axis)


# ─────────────────────────────────────────────────────────────────────────────
# Excitation: PSD curve, direction, frequency grid
# ─────────────────────────────────────────────────────────────────────────────

def pick_psd_curve(state: ConversionState,
                   requested: Optional[int]) -> Tuple[int, str]:
    """The input-PSD *DEFINE_CURVE: --psd-curve wins, else the only curve that
    is not referenced as S-N data (curves titled *SN* excluded as tiebreak)."""
    if requested:
        if requested not in state.curves:
            raise SystemExit(f"ERROR: --psd-curve {requested} is not a "
                             "*DEFINE_CURVE in the deck")
        return requested, f"--psd-curve {requested}"
    sn_ids = {f.lcid for f in state.mat_add_fatigue.values() if f.lcid > 0}
    cands = [c for c in state.curves.values() if c.lcid not in sn_ids]
    if len(cands) > 1:      # tiebreak: prefer titles that look like a PSD
        titled = [c for c in cands if "PSD" in (c.title or "").upper()]
        if len(titled) == 1:
            cands = titled
    if len(cands) != 1:
        raise SystemExit(
            "ERROR: cannot auto-pick the input PSD curve "
            f"({len(cands)} candidate curve(s)); pass --psd-curve LCID")
    c = cands[0]
    return c.lcid, (f"auto-picked curve {c.lcid} "
                    f"('{c.title}')" if c.title else f"auto-picked curve {c.lcid}")


def excitation_direction(state: ConversionState,
                         requested: str) -> Tuple[int, str]:
    """0/1/2 = X/Y/Z.  --dir wins; else the deck's gravity direction; else Z."""
    if requested.upper() in _DIRS:
        return _DIRS[requested.upper()], f"--dir {requested.upper()}"
    for g in state.gravity_loads:
        if g.dof in (1, 2, 3):
            d = "XYZ"[g.dof - 1]
            return g.dof - 1, (f"deck gravity direction ({d} from "
                               "*LOAD_GRAVITY_PART - the vertical)")
    return 2, "no gravity in deck - defaulting to Z (override with --dir)"


def psd_interpolator(state: ConversionState, lcid: int, freq_scale: float,
                     psd_unit: str, g_value: float,
                     curve_freq_unit: str) -> Tuple[Callable, Tuple[float, float]]:
    """Return S_a(f_Hz) in (deck-length/s²)²/Hz + the curve's band in Hz.

    Curve abscissa: deck frequency units (× freq_scale → Hz) unless
    --curve-freq-unit hz.  Ordinate: (deck-length/deck-time²)²/(deck-freq) by
    default — the working-unit conversion is freq_scale³ — or g²/Hz with
    --psd-unit g2hz (× g_value²).  Outside the curve the END VALUES are held
    constant — LS-DYNA's load-curve convention, so results match what LS-DYNA
    would excite there.
    """
    pts = state.curves[lcid].pts
    if len(pts) < 2:
        raise SystemExit(f"ERROR: PSD curve {lcid} has {len(pts)} point(s)")
    f_raw = np.array([p[0] for p in pts])
    v_raw = np.array([p[1] for p in pts])
    fs = 1.0 if curve_freq_unit == "hz" else freq_scale
    f_hz = f_raw * fs
    if psd_unit == "g2hz":
        v = v_raw * g_value ** 2
    else:
        v = v_raw * freq_scale ** 3
    order = np.argsort(f_hz)
    f_hz, v = f_hz[order], v[order]

    def s_a(f):
        return np.interp(f, f_hz, v)     # ends clamped (LS-DYNA convention)

    return s_a, (float(f_hz[0]), float(f_hz[-1]))


def output_band(state: ConversionState, freq_scale: float,
                fmin_cli: Optional[float], fmax_cli: Optional[float],
                modes_hz: "np.ndarray") -> Tuple[float, float, str]:
    """Band [Hz]: CLI override > deck D3PSD card > modes ±50 %."""
    d3psd = state.db_freq_binary.get("D3PSD")
    if d3psd is not None and d3psd.fmax > 0.0:
        fmin, fmax = d3psd.fmin * freq_scale, d3psd.fmax * freq_scale
        why = (f"deck *DATABASE_FREQUENCY_BINARY_D3PSD band {d3psd.fmin:g}-"
               f"{d3psd.fmax:g} deck-units -> {fmin:g}-{fmax:g} Hz")
    else:
        fmin, fmax = 0.5 * modes_hz.min(), 1.5 * modes_hz.max()
        why = "no D3PSD band in deck - using solved modes +/-50%"
    if fmin_cli is not None:
        fmin, why = fmin_cli, why + f"; --fmin {fmin_cli:g}"
    if fmax_cli is not None:
        fmax, why = fmax_cli, why + f"; --fmax {fmax_cli:g}"
    if not (0.0 <= fmin < fmax):
        raise SystemExit(f"ERROR: bad frequency band {fmin:g}-{fmax:g} Hz")
    return fmin, fmax, why


def frequency_grid(fmin: float, fmax: float, modes_hz: "np.ndarray",
                   zeta: float, n_base: int) -> "np.ndarray":
    """Log-spaced band grid + refinement clusters at each in-band resonance
    (±3 half-power widths, where |H|² varies fastest)."""
    lo = max(fmin, 1e-6)
    grid = [np.geomspace(lo, fmax, n_base)]
    for fj in modes_hz:
        if fmin <= fj <= fmax:
            half = 3.0 * max(zeta, 1e-4) * fj
            grid.append(np.linspace(max(lo, fj - half), min(fmax, fj + half), 41))
    g = np.unique(np.concatenate(grid))
    return g[(g >= lo) & (g <= fmax)]


# ─────────────────────────────────────────────────────────────────────────────
# Modal response machinery
# ─────────────────────────────────────────────────────────────────────────────

def participation_factors(mesh: Mesh, disp3: "np.ndarray",
                          node_mass: Dict[int, float],
                          direction: int) -> "np.ndarray":
    """Γ_j = φ_jᵀ·M·r for a unit base translation along ``direction``."""
    m = np.array([node_mass.get(int(n), 0.0) for n in mesh.node_ids])
    return np.einsum("n,jn->j", m, disp3[:, :, direction])


def frf_matrix(modes_hz: "np.ndarray", grid_hz: "np.ndarray", zeta: float,
               gamma: "np.ndarray") -> "np.ndarray":
    """H (n_freq × n_modes), relative displacement per base acceleration."""
    wj = 2.0 * math.pi * modes_hz[np.newaxis, :]
    w = 2.0 * math.pi * grid_hz[:, np.newaxis]
    return -gamma[np.newaxis, :] / (wj ** 2 - w ** 2 + 2j * zeta * wj * w)


def modal_covariance(H: "np.ndarray", sa: "np.ndarray",
                     grid_hz: "np.ndarray") -> "np.ndarray":
    """G_jk = ∫ Re(H_j·H_k*)·S_a df — RMS of y=cᵀu is sqrt(c_j c_k G_jk)."""
    integrand = np.real(H[:, :, np.newaxis] * np.conj(H[:, np.newaxis, :]))
    return _trapz(integrand * sa[:, np.newaxis, np.newaxis], grid_hz, axis=0)


def rms_from_modal(coeffs: "np.ndarray", G: "np.ndarray") -> "np.ndarray":
    """coeffs (n_modes, ...) → RMS over the band with all modal cross terms."""
    c = coeffs.reshape(coeffs.shape[0], -1)
    var = np.einsum("jn,kn,jk->n", c, c, G)
    return np.sqrt(np.maximum(var, 0.0)).reshape(coeffs.shape[1:])


# ─────────────────────────────────────────────────────────────────────────────
# Modal stress recovery
# ─────────────────────────────────────────────────────────────────────────────

def _material_elastic(state: ConversionState) -> Dict[int, Tuple[float, float]]:
    """mid → (E, nu) across all supported material keywords."""
    out: Dict[int, Tuple[float, float]] = {}
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_rigid, state.mat_null, state.mat_power_law):
        for mid, m in mats.items():
            out[mid] = (m.E, m.nu)
    return out


@dataclass
class ShellStressModel:
    """Everything needed to turn 6-DOF shapes into shell surface stresses."""
    index: "np.ndarray"      # (n, 4) node indices (tri: last repeated)
    n_nodes: "np.ndarray"    # (n,) 3 or 4
    rot: "np.ndarray"        # (n, 3, 3) global→local rotation (rows e1,e2,n)
    dndx: "np.ndarray"       # (n, 4) shape-fn x-derivatives at centroid
    dndy: "np.ndarray"       # (n, 4)
    dmat: "np.ndarray"       # (n, 3, 3) plane-stress Hooke matrix
    half_t: "np.ndarray"     # (n,) t/2
    valid: "np.ndarray"      # (n,) bool: has material + geometry
    eids: "np.ndarray"       # (n,)


def build_shell_stress_model(state: ConversionState, mesh: Mesh) -> Optional[ShellStressModel]:
    """Local frames, centroid B-operators and D-matrices for every shell."""
    n = len(mesh.shell_conn)
    if n == 0:
        return None
    emat = _material_elastic(state)
    idx = np.zeros((n, 4), dtype=np.int64)
    nn = np.zeros(n, dtype=np.int64)
    dmat = np.zeros((n, 3, 3))
    half_t = np.zeros(n)
    valid = np.ones(n, dtype=bool)
    for i, conn in enumerate(mesh.shell_conn):
        nn[i] = len(conn)
        idx[i, :len(conn)] = conn
        if len(conn) == 3:
            idx[i, 3] = conn[2]
        eid_part = int(mesh.shell_part[i])
        part = state.parts.get(int(mesh.part_ids[eid_part]))
        sec = state.sec_shells.get(part.secid) if part else None
        E, nu = emat.get(part.mid, (0.0, 0.0)) if part else (0.0, 0.0)
        if sec is None or E <= 0.0 or sec.t1 <= 0.0:
            valid[i] = False
            continue
        half_t[i] = 0.5 * sec.t1
        c = E / (1.0 - nu * nu)
        dmat[i] = [[c, c * nu, 0.0], [c * nu, c, 0.0],
                   [0.0, 0.0, 0.5 * c * (1.0 - nu)]]

    p = mesh.coords[idx]                                     # (n, 4, 3)
    tri = nn == 3
    # local frame from mid-edge directions (robust for warped quads; for tris
    # p4 == p3 so d1/d2 still span the plane)
    d1 = 0.5 * (p[:, 1] + p[:, 2]) - 0.5 * (p[:, 0] + p[:, 3])
    d2 = 0.5 * (p[:, 2] + p[:, 3]) - 0.5 * (p[:, 0] + p[:, 1])
    nv = np.cross(d1, d2)
    nrm = np.linalg.norm(nv, axis=1)
    degenerate = nrm < 1e-30
    valid &= ~degenerate
    nrm[degenerate] = 1.0
    nv /= nrm[:, np.newaxis]
    e1 = d1 - np.einsum("ni,ni->n", d1, nv)[:, np.newaxis] * nv
    l1 = np.linalg.norm(e1, axis=1)
    bad = l1 < 1e-30
    valid &= ~bad
    l1[bad] = 1.0
    e1 /= l1[:, np.newaxis]
    e2 = np.cross(nv, e1)
    rot = np.stack([e1, e2, nv], axis=1)                     # (n, 3, 3)

    centr = p.mean(axis=1)
    xy = np.einsum("nij,nkj->nki", rot[:, :2, :], p - centr[:, np.newaxis, :])
    x, y = xy[..., 0], xy[..., 1]                            # (n, 4)

    dndx = np.zeros((n, 4))
    dndy = np.zeros((n, 4))
    # CST triangles
    if tri.any():
        xt, yt = x[tri, :3], y[tri, :3]
        a2 = ((xt[:, 1] - xt[:, 0]) * (yt[:, 2] - yt[:, 0])
              - (xt[:, 2] - xt[:, 0]) * (yt[:, 1] - yt[:, 0]))
        ok = np.abs(a2) > 1e-30
        a2[~ok] = 1.0
        sub = np.zeros((tri.sum(), 4))
        sub[:, 0] = (yt[:, 1] - yt[:, 2]) / a2
        sub[:, 1] = (yt[:, 2] - yt[:, 0]) / a2
        sub[:, 2] = (yt[:, 0] - yt[:, 1]) / a2
        dndx[tri] = sub
        sub = np.zeros((tri.sum(), 4))
        sub[:, 0] = (xt[:, 2] - xt[:, 1]) / a2
        sub[:, 1] = (xt[:, 0] - xt[:, 2]) / a2
        sub[:, 2] = (xt[:, 1] - xt[:, 0]) / a2
        dndy[tri] = sub
        v = valid[tri]
        v &= ok
        valid[tri] = v
    # bilinear quads at the centroid
    quad = ~tri
    if quad.any():
        dxi = 0.25 * np.array([-1.0, 1.0, 1.0, -1.0])
        deta = 0.25 * np.array([-1.0, -1.0, 1.0, 1.0])
        j11 = x[quad] @ dxi; j12 = y[quad] @ dxi
        j21 = x[quad] @ deta; j22 = y[quad] @ deta
        det = j11 * j22 - j12 * j21
        ok = np.abs(det) > 1e-30
        det[~ok] = 1.0
        inv11, inv12 = j22 / det, -j12 / det
        inv21, inv22 = -j21 / det, j11 / det
        dndx[quad] = inv11[:, np.newaxis] * dxi + inv12[:, np.newaxis] * deta
        dndy[quad] = inv21[:, np.newaxis] * dxi + inv22[:, np.newaxis] * deta
        v = valid[quad]
        v &= ok
        valid[quad] = v
    return ShellStressModel(index=idx, n_nodes=nn, rot=rot, dndx=dndx,
                            dndy=dndy, dmat=dmat, half_t=half_t, valid=valid,
                            eids=mesh.shell_ids)


def shell_modal_stress(model: ShellStressModel,
                       disp6: "np.ndarray") -> "np.ndarray":
    """Centroid surface stresses per mode: (n_modes, n_shells, 2, 3).

    Surfaces are z = +t/2 and −t/2; components (σxx, σyy, τxy) in the element
    local frame.  Triangles carry a zero-weight 4th node (index repeats node 3
    but its dN/dx is zero, so the duplicate contributes nothing).
    """
    u = disp6[:, model.index, :3]                # (m, n, 4, 3) global
    th = disp6[:, model.index, 3:]               # (m, n, 4, 3) global rotations
    # rotate into the local frame
    ul = np.einsum("nij,mnkj->mnki", model.rot, u)
    tl = np.einsum("nij,mnkj->mnki", model.rot, th)
    dndx, dndy = model.dndx, model.dndy
    exx = np.einsum("nk,mnk->mn", dndx, ul[..., 0])
    eyy = np.einsum("nk,mnk->mn", dndy, ul[..., 1])
    gxy = (np.einsum("nk,mnk->mn", dndy, ul[..., 0])
           + np.einsum("nk,mnk->mn", dndx, ul[..., 1]))
    kxx = np.einsum("nk,mnk->mn", dndx, tl[..., 1])
    kyy = -np.einsum("nk,mnk->mn", dndy, tl[..., 0])
    kxy = (np.einsum("nk,mnk->mn", dndy, tl[..., 1])
           - np.einsum("nk,mnk->mn", dndx, tl[..., 0]))
    em = np.stack([exx, eyy, gxy], axis=-1)      # (m, n, 3)
    kv = np.stack([kxx, kyy, kxy], axis=-1)
    z = model.half_t[np.newaxis, :, np.newaxis]
    eps = np.stack([em + z * kv, em - z * kv], axis=2)       # (m, n, 2, 3)
    sig = np.einsum("nij,mnsj->mnsi", model.dmat, eps)
    sig[:, ~model.valid] = 0.0
    return sig


@dataclass
class SolidStressModel:
    index: "np.ndarray"      # (n, 8) node indices (padded by repetition)
    dndxyz: "np.ndarray"     # (n, 8, 3) shape-fn derivatives at centroid
    dmat: "np.ndarray"       # (n, 6, 6) 3-D Hooke
    valid: "np.ndarray"
    eids: "np.ndarray"


_HEXA_XI = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                     [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],
                    dtype=float) if _HAVE_NUMPY else None


def build_solid_stress_model(state: ConversionState, mesh: Mesh) -> Optional[SolidStressModel]:
    """Centroid B-operators for tet4 (constant strain), hexa8 (trilinear) and
    tet10 (corner sub-tet approximation, warned by the caller)."""
    n = len(mesh.solid_conn)
    if n == 0:
        return None
    emat = _material_elastic(state)
    idx = np.zeros((n, 8), dtype=np.int64)
    kind = np.zeros(n, dtype=np.int64)          # 4 = tet, 8 = hexa
    dmat = np.zeros((n, 6, 6))
    valid = np.ones(n, dtype=bool)
    for i, conn in enumerate(mesh.solid_conn):
        c = conn[:4] if len(conn) == 10 else conn
        if len(c) >= 8:
            idx[i] = c[:8]
            kind[i] = 8
        else:
            idx[i, :4] = c[:4]
            idx[i, 4:] = c[3]
            kind[i] = 4
        part = state.parts.get(int(mesh.part_ids[int(mesh.solid_part[i])]))
        E, nu = emat.get(part.mid, (0.0, 0.0)) if part else (0.0, 0.0)
        if E <= 0.0:
            valid[i] = False
            continue
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        mu = 0.5 * E / (1 + nu)
        D = np.zeros((6, 6))
        D[:3, :3] = lam
        D[np.arange(3), np.arange(3)] += 2 * mu
        D[3:, 3:] = np.eye(3) * mu
        dmat[i] = D

    dndxyz = np.zeros((n, 8, 3))
    p = mesh.coords[idx]                                     # (n, 8, 3)
    tet = kind == 4
    if tet.any():
        pt = p[tet, :4]
        # constant-strain tet: shape-fn gradients from the edge matrix inverse
        e = pt[:, 1:] - pt[:, :1]                            # (t, 3, 3) rows = edges
        det = np.linalg.det(e)
        ok = np.abs(det) > 1e-30
        e_safe = e.copy()
        e_safe[~ok] = np.eye(3)
        einv = np.linalg.inv(e_safe)
        g = np.zeros((int(tet.sum()), 8, 3))
        g[:, 1:4] = np.transpose(einv, (0, 2, 1))
        g[:, 0] = -g[:, 1:4].sum(axis=1)
        dndxyz[tet] = g
        v = valid[tet]
        v &= ok
        valid[tet] = v
    hexa = kind == 8
    if hexa.any():
        # trilinear derivatives at the centroid (ξ=η=ζ=0): dN_i/dξ_a = ξ_ia/8
        dloc = 0.125 * _HEXA_XI                              # (8, 3)
        J = np.einsum("kj,nki->nji", dloc, p[hexa])          # (h, 3, 3)
        det = np.linalg.det(J)
        ok = np.abs(det) > 1e-30
        Jsafe = J + (~ok)[:, None, None] * np.eye(3)
        Jinv = np.linalg.inv(Jsafe)
        dndxyz[hexa] = np.einsum("nij,kj->nki", Jinv, dloc)
        v = valid[hexa]
        v &= ok
        valid[hexa] = v
    return SolidStressModel(index=idx, dndxyz=dndxyz, dmat=dmat, valid=valid,
                            eids=mesh.solid_ids)


def solid_modal_stress(model: SolidStressModel,
                       disp6: "np.ndarray") -> "np.ndarray":
    """Centroid stresses per mode: (n_modes, n_solids, 6) as
    (σxx, σyy, σzz, τxy, τyz, τzx)."""
    u = disp6[:, model.index, :3]                            # (m, n, 8, 3)
    grad = np.einsum("nkj,mnki->mnji", model.dndxyz, u)      # (m, n, 3du, 3dx)?
    # grad[m, n, i, j] = du_i/dx_j
    gxx = grad[..., 0, 0]; gyy = grad[..., 1, 1]; gzz = grad[..., 2, 2]
    gxy = grad[..., 0, 1] + grad[..., 1, 0]
    gyz = grad[..., 1, 2] + grad[..., 2, 1]
    gzx = grad[..., 2, 0] + grad[..., 0, 2]
    eps = np.stack([gxx, gyy, gzz, gxy, gyz, gzx], axis=-1)
    sig = np.einsum("nij,mnj->mni", model.dmat, eps)
    sig[:, ~model.valid] = 0.0
    return sig


# von Mises quadratic forms:  σ_vm² = σᵀ·Q·σ
_Q_PLANE = np.array([[1.0, -0.5, 0.0],
                     [-0.5, 1.0, 0.0],
                     [0.0, 0.0, 3.0]]) if _HAVE_NUMPY else None
_Q_SOLID = None
if _HAVE_NUMPY:
    _Q_SOLID = np.zeros((6, 6))
    _Q_SOLID[:3, :3] = np.array([[1.0, -0.5, -0.5],
                                 [-0.5, 1.0, -0.5],
                                 [-0.5, -0.5, 1.0]])
    _Q_SOLID[np.arange(3, 6), np.arange(3, 6)] = 3.0


def evms_moments(stress_modal: "np.ndarray", Q: "np.ndarray", H: "np.ndarray",
                 sa: "np.ndarray", grid_hz: "np.ndarray",
                 chunk: int = 512) -> "np.ndarray":
    """Spectral moments (m0, m1, m2, m4) of the von Mises stress PSD.

    stress_modal: (n_modes, n_items, n_comp) modal stresses; the equivalent
    von Mises PSD is  G_vm(f) = Σ_ab Q_ab · Re(A_a·A_b*) · S_a(f)  with
    A_a(f) = Σ_j s_ja·H_j(f)  (Segalman's EVMS).  Returns (n_items, 4).
    """
    n_items = stress_modal.shape[1]
    out = np.zeros((n_items, 4))
    fpow = np.stack([np.ones_like(grid_hz), grid_hz,
                     grid_hz ** 2, grid_hz ** 4], axis=1)    # (n_freq, 4)
    for i0 in range(0, n_items, chunk):
        s = stress_modal[:, i0:i0 + chunk, :]                # (m, c, a)
        A = np.einsum("fj,jca->fca", H, s)                   # complex
        g = np.einsum("fca,ab,fcb->fc", A, Q, np.conj(A)).real
        g *= sa[:, np.newaxis]
        out[i0:i0 + chunk] = _trapz(g[:, :, np.newaxis] * fpow[:, np.newaxis, :],
                                    grid_hz, axis=0)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# S-N data and damage integration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SNFunction:
    """Vectorized S(range) → N cycles, built from *MAT_ADD_FATIGUE."""
    fatigue: MatAddFatigue
    describe: str
    _eval: Callable

    def cycles(self, s_range: "np.ndarray") -> "np.ndarray":
        return self._eval(np.asarray(s_range, dtype=float))


def sn_function(state: ConversionState, fat: MatAddFatigue) -> SNFunction:
    """Build N(S_range) from a *MAT_ADD_FATIGUE definition.

    Curve data (lcid > 0): abscissa N, ordinate S; ltype 0 = semi-log
    (S linear vs log10 N), 1 = log-log.  Plateaus are resolved conservatively
    (the smallest N for a given S).  sntype 1 means the curve's S is an
    amplitude — the Dirlik/narrow-band pdf is over RANGES, so S_range/2 is
    looked up.  Below the smallest curve stress: snlimt 0 = the life of the
    last (largest-N) point, 1 = extrapolate the last segment, 2 = infinite
    life.  sthres is an absolute no-damage threshold on top.
    """
    if fat.lcid > 0:
        curve = state.curves.get(fat.lcid)
        if curve is None or len(curve.pts) < 2:
            raise SystemExit(f"ERROR: *MAT_ADD_FATIGUE mid {fat.mid} "
                             f"references missing/short curve {fat.lcid}")
        n_raw = np.array([p[0] for p in curve.pts], dtype=float)
        s_raw = np.array([p[1] for p in curve.pts], dtype=float)
        if (n_raw <= 0).any() or (s_raw <= 0).any():
            raise SystemExit(f"ERROR: S-N curve {fat.lcid} has non-positive "
                             "values")
        # sort by S ascending; on ties (plateaus) keep the SMALLEST N
        order = np.lexsort((n_raw, s_raw))
        s_sorted, n_sorted = s_raw[order], n_raw[order]
        keep = np.ones(len(s_sorted), dtype=bool)
        keep[1:] = np.diff(s_sorted) > 0.0
        s_axis, n_axis = s_sorted[keep], n_sorted[keep]
        log_n = np.log10(n_axis)
        log_s = np.log10(s_axis)
        s_min, s_max = s_axis[0], s_axis[-1]
        # snlimt=0 "life at the last point": the curve's largest N, taken from
        # the ORIGINAL points (the plateau dedupe above keeps the smallest N
        # per stress, so n_axis no longer carries it)
        log_n_last = float(np.log10(n_raw.max()))
        big_n = np.log10(np.finfo(float).max / 10.0)

        def interp(s):
            if fat.ltype == 1:
                return np.interp(np.log10(np.maximum(s, 1e-300)), log_s, log_n)
            return np.interp(s, s_axis, log_n)

        # slope of the last segment towards low stress, for snlimt=1
        if fat.ltype == 1:
            x0, x1 = log_s[0], log_s[1]
        else:
            x0, x1 = s_axis[0], s_axis[1]
        slope = (log_n[1] - log_n[0]) / (x1 - x0) if x1 != x0 else 0.0

        def _eval(s):
            s = np.maximum(s, 1e-300)
            if fat.sntype == 1:
                s = s / 2.0
            ln = interp(s)
            below = s < s_min
            if fat.snlimt == 2:
                ln = np.where(below, big_n, ln)      # infinite life
            elif fat.snlimt == 1 and slope != 0.0:
                x = np.log10(s) if fat.ltype == 1 else s
                x0v = log_s[0] if fat.ltype == 1 else s_axis[0]
                ln = np.where(below, log_n[0] + slope * (x - x0v), ln)
            else:                                    # snlimt 0: last-point life
                ln = np.where(below, log_n_last, ln)
            above = s > s_max
            ln = np.where(above, log_n[-1], ln)      # clamp: strongest damage
            n = 10.0 ** np.minimum(ln, big_n)
            return n

        kind = {0: "semi-log", 1: "log-log"}.get(fat.ltype, f"ltype={fat.ltype}")
        desc = (f"S-N curve {fat.lcid} ({kind}, "
                f"{'amplitude' if fat.sntype == 1 else 'range'} S, "
                f"snlimt={fat.snlimt}"
                + (f", threshold {fat.sthres:g}" if fat.sthres > 0 else "")
                + ")")
        return SNFunction(fatigue=fat, describe=desc, _eval=_eval)

    if fat.a > 0.0 and fat.b > 0.0:
        def _eval(s):
            s = np.maximum(s, 1e-300)
            if fat.sntype == 1:
                s = s / 2.0
            return fat.a * s ** (-fat.b)
        desc = f"S-N power law N*S^{fat.b:g} = {fat.a:g}"
        return SNFunction(fatigue=fat, describe=desc, _eval=_eval)
    raise SystemExit(f"ERROR: *MAT_ADD_FATIGUE mid {fat.mid} has neither a "
                     "curve (lcid) nor a/b power-law constants")


def damage_rates(moments: "np.ndarray", sn: SNFunction,
                 method: str = "dirlik", n_z: int = 240) -> "np.ndarray":
    """Fatigue damage per second from von Mises PSD spectral moments.

    Dirlik's rainflow-range pdf (default) or the narrow-band Rayleigh pdf::

        damage/s = E[P] · ∫ p(S)·/N(S) dS

    integrated on a normalized range grid Z = S/(2√m0), 0..12.
    """
    m0, m1, m2, m4 = (moments[:, k] for k in range(4))
    live = (m0 > 1e-300) & (m2 > 1e-300) & (m4 > 1e-300)
    rate = np.zeros(len(m0))
    if not live.any():
        return rate
    m0l, m1l, m2l, m4l = m0[live], m1[live], m2[live], m4[live]
    z = np.linspace(1e-6, 12.0, n_z)                        # (nz,)
    two_sqrt_m0 = 2.0 * np.sqrt(m0l)                        # (n,)
    s = two_sqrt_m0[:, np.newaxis] * z[np.newaxis, :]       # ranges (n, nz)

    # moments are over f in Hz, so the rates are sqrt-ratios directly
    # (the familiar /2π applies only to ω-based moments)
    if method == "narrowband":
        ep = np.sqrt(m2l / m0l)                             # zero upcrossings/s
        pdf = z * np.exp(-0.5 * z * z)                      # Rayleigh in Z
    else:
        ep = np.sqrt(m4l / m2l)                             # peaks/s
        alpha2 = m2l / np.sqrt(m0l * m4l)
        xm = (m1l / m0l) * np.sqrt(m2l / m4l)
        d1 = 2.0 * (xm - alpha2 ** 2) / (1.0 + alpha2 ** 2)
        r = np.where(
            np.abs(1.0 - alpha2 - d1 + d1 ** 2) > 1e-12,
            (alpha2 - xm - d1 ** 2) / (1.0 - alpha2 - d1 + d1 ** 2), 0.5)
        r = np.clip(r, 1e-6, 1.0 - 1e-6)
        d2 = np.clip((1.0 - alpha2 - d1 + d1 ** 2) / (1.0 - r), 0.0, None)
        d3 = np.clip(1.0 - d1 - d2, 0.0, None)
        q = np.where(np.abs(d1) > 1e-12,
                     1.25 * (alpha2 - d3 - d2 * r) / d1, 1.0)
        q = np.clip(q, 1e-6, None)
        zz = z[np.newaxis, :]
        pdf = (d1[:, None] / q[:, None] * np.exp(-zz / q[:, None])
               + d2[:, None] * zz / r[:, None] ** 2
               * np.exp(-0.5 * zz ** 2 / r[:, None] ** 2)
               + d3[:, None] * zz * np.exp(-0.5 * zz ** 2))

    n_cycles = sn.cycles(s)
    inv_n = 1.0 / n_cycles
    if sn.fatigue.sthres > 0.0:
        inv_n = np.where(s < sn.fatigue.sthres, 0.0, inv_n)
    rate[live] = ep * _trapz(pdf * inv_n, z, axis=-1)
    return rate


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
        prog="modal_random_response",
        description="Offline modal-superposition random vibration: response "
                    "PSD / RMS / Dirlik fatigue from a k2rad modal run "
                    "(implements *DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG "
                    "and *MAT_ADD_FATIGUE).")
    ap.add_argument("npz", help="<jobname>_modes.npz from tools/modal_solve.py")
    ap.add_argument("k_file", help="source LS-DYNA .k file")
    ap.add_argument("-o", "--output-stem", default=None, metavar="STEM")
    ap.add_argument("--damping", type=float, default=0.02, metavar="ZETA",
                    help="modal damping ratio (default 0.02 = 2%% critical)")
    ap.add_argument("--dir", default="auto", metavar="X|Y|Z",
                    help="base-excitation direction (default: the deck's "
                         "gravity direction, else Z)")
    ap.add_argument("--psd-curve", type=int, default=None, metavar="LCID",
                    help="input acceleration-PSD *DEFINE_CURVE (default: "
                         "auto-picked)")
    ap.add_argument("--psd-unit", choices=("deck", "g2hz"), default="deck",
                    help="PSD ordinate: 'deck' = accel^2 per deck-frequency "
                         "unit (default), 'g2hz' = g^2/Hz")
    ap.add_argument("--g", type=float, default=9810.0, metavar="ACCEL",
                    help="g in deck length/s^2 for --psd-unit g2hz "
                         "(default 9810 = mm)")
    ap.add_argument("--curve-freq-unit", choices=("deck", "hz"), default="deck",
                    help="PSD curve abscissa unit (default deck frequency "
                         "units)")
    ap.add_argument("--fmin", type=float, default=None, metavar="HZ",
                    help="output band lower bound in Hz (default: deck D3PSD)")
    ap.add_argument("--fmax", type=float, default=None, metavar="HZ",
                    help="output band upper bound in Hz (default: deck D3PSD)")
    ap.add_argument("--nfreq", type=int, default=600, metavar="N",
                    help="base frequency-grid points (default 600; resonances "
                         "get extra refinement)")
    ap.add_argument("--duration", type=float, default=1.0, metavar="SEC",
                    help="exposure time for the total damage column "
                         "(default 1 s; the damage RATE is duration-free)")
    ap.add_argument("--fatigue-method", choices=("dirlik", "narrowband"),
                    default="dirlik")
    ap.add_argument("--probe-nodes", type=int, nargs="+", default=None,
                    metavar="NODE", help="nodes for response-PSD spectra "
                    "(default: the 3 highest-RMS nodes)")
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

    # ── Excitation ───────────────────────────────────────────────────────
    direction, why_dir = excitation_direction(state, args.dir)
    lcid, why_curve = pick_psd_curve(state, args.psd_curve)
    sa_func, curve_band = psd_interpolator(
        state, lcid, scale_hz, args.psd_unit, args.g, args.curve_freq_unit)
    fmin, fmax, why_band = output_band(state, scale_hz, args.fmin, args.fmax,
                                       modes_hz)
    print(f"  excitation: base acceleration along {'XYZ'[direction]} "
          f"({why_dir})")
    print(f"  input PSD:  {why_curve}; curve covers "
          f"{curve_band[0]:g}-{curve_band[1]:g} Hz "
          f"(ordinate unit: {args.psd_unit})")
    print(f"  band:       {fmin:g}-{fmax:g} Hz ({why_band})")
    in_band = (modes_hz >= fmin) & (modes_hz <= fmax)
    if not in_band.any():
        print("  WARNING: NO solved mode lies inside the output band - the "
              "response is the small off-resonant tail of the modes at "
              f"{modes_hz.min():.1f}-{modes_hz.max():.1f} Hz. If the deck's "
              "D3PSD band was authored in Hz rather than deck units, rerun "
              f"with e.g. --fmin {0.5 * modes_hz.min():.0f} "
              f"--fmax {1.5 * modes_hz.max():.0f}")
    if curve_band[0] > fmin or curve_band[1] < fmax:
        print("  NOTE: the band extends beyond the PSD curve "
              f"({curve_band[0]:g}-{curve_band[1]:g} Hz) - the curve's end "
              "values are held constant there (LS-DYNA load-curve "
              "convention). Check --curve-freq-unit if that is unintended.")

    grid = frequency_grid(fmin, fmax, modes_hz, args.damping, args.nfreq)
    sa = sa_func(grid)

    # ── Modal machinery ──────────────────────────────────────────────────
    disp6 = shapes_on_mesh(mesh, modes, rotations=True)
    disp3 = disp6[..., :3]
    node_mass, _ = modal_solve.nodal_masses_from_state(state)
    gamma = participation_factors(mesh, disp3, node_mass, direction)
    print("\n  mode |   f [Hz] | participation | eff. mass")
    total_mass = sum(node_mass.values())
    for j in range(modes.n_modes):
        print(f"  {j + 1:4d} | {modes_hz[j]:8.2f} | {gamma[j]:13.4G} | "
              f"{gamma[j] ** 2:9.4G}"
              + ("  (in band)" if in_band[j] else ""))
    print(f"  total structural mass {total_mass:.6G}; effective mass in the "
          f"{'XYZ'[direction]} direction {np.sum(gamma ** 2):.6G} "
          f"({100 * np.sum(gamma ** 2) / total_mass:.1f}% - the rest is in "
          "higher, unsolved modes)")

    H = frf_matrix(modes_hz, grid, args.damping, gamma)
    G = modal_covariance(H, sa, grid)

    # ── D3RMS: displacement ─────────────────────────────────────────────
    rms_disp = rms_from_modal(disp3, G)                      # (n_nodes, 3)
    rms_mag = np.linalg.norm(rms_disp, axis=1)
    stem = args.output_stem or default_output_stem(args.npz)
    _write_csv(stem + "_rms_displacement.csv",
               "node,rms_ux,rms_uy,rms_uz,rms_mag",
               ((int(mesh.node_ids[i]), f"{rms_disp[i, 0]:.6G}",
                 f"{rms_disp[i, 1]:.6G}", f"{rms_disp[i, 2]:.6G}",
                 f"{rms_mag[i]:.6G}") for i in range(mesh.n_nodes)))
    top = np.argsort(rms_mag)[::-1][:5]
    print("\n  RMS relative displacement (deck length units) - top nodes:")
    for i in top:
        print(f"    node {int(mesh.node_ids[i]):8d}: |u|rms = {rms_mag[i]:.5G}")

    # ── D3PSD: probe-node spectra ───────────────────────────────────────
    probes = args.probe_nodes or [int(mesh.node_ids[i]) for i in top[:3]]
    for nid in probes:
        i = mesh.nid_to_idx.get(int(nid))
        if i is None:
            print(f"  WARNING: probe node {nid} not in the mesh - skipped")
            continue
        amp = np.einsum("fj,jc->fc", H, disp3[:, i, :])      # (n_freq, 3)
        psd = (np.abs(amp) ** 2) * sa[:, np.newaxis]
        _write_csv(stem + f"_psd_node_{nid}.csv",
                   "freq_hz,psd_ux,psd_uy,psd_uz",
                   ((f"{grid[k]:.6G}", f"{psd[k, 0]:.6G}",
                     f"{psd[k, 1]:.6G}", f"{psd[k, 2]:.6G}")
                    for k in range(len(grid))))
    print(f"  response-PSD spectra written for node(s) "
          f"{', '.join(str(n) for n in probes)}")

    # ── Stress recovery + D3RMS stress + D3FTG fatigue ──────────────────
    if any(len(c) == 10 for c in mesh.solid_conn):
        print("  NOTE: 10-node tets use their 4 corner nodes for stress "
              "recovery (constant-strain approximation).")
    shell_model = build_shell_stress_model(state, mesh)
    solid_model = build_solid_stress_model(state, mesh)
    if len(mesh.beam_conn):
        print(f"  NOTE: {len(mesh.beam_conn)} beam element(s) carry no stress "
              "recovery - they are excluded from RMS-stress/fatigue output.")

    stress_items: List[Tuple[str, "np.ndarray", "np.ndarray", "np.ndarray"]] = []
    if shell_model is not None:
        smod = shell_modal_stress(shell_model, disp6)        # (m, n, 2, 3)
        m_shell = evms_moments(
            smod.reshape(modes.n_modes, -1, 3), _Q_PLANE, H, sa, grid)
        m_shell = m_shell.reshape(-1, 2, 4)
        worst = np.argmax(m_shell[:, :, 0], axis=1)          # worst surface
        m_shell = m_shell[np.arange(len(worst)), worst]
        stress_items.append(("shell", shell_model.eids, m_shell,
                             shell_model.valid))
    if solid_model is not None:
        smod = solid_modal_stress(solid_model, disp6)        # (m, n, 6)
        m_solid = evms_moments(smod, _Q_SOLID, H, sa, grid)
        stress_items.append(("solid", solid_model.eids, m_solid,
                             solid_model.valid))

    # fatigue data: per element via its part's material
    mid_of_part = {int(pid): state.parts[int(pid)].mid for pid in mesh.part_ids
                   if int(pid) in state.parts}
    sn_cache: Dict[int, Optional[SNFunction]] = {}

    def sn_for(part_row: "np.ndarray") -> List[Optional[SNFunction]]:
        out = []
        for pi in part_row:
            mid = mid_of_part.get(int(mesh.part_ids[int(pi)]), 0)
            if mid not in sn_cache:
                fat = state.mat_add_fatigue.get(mid)
                sn_cache[mid] = sn_function(state, fat) if fat else None
            out.append(sn_cache[mid])
        return out

    eid_all: List[int] = []
    rms_vm_all: List[float] = []
    rate_all: List[float] = []
    mom_all: List["np.ndarray"] = []
    for family, eids, mom, valid in stress_items:
        part_row = mesh.shell_part if family == "shell" else mesh.solid_part
        sns = sn_for(part_row)
        rms_vm = np.sqrt(np.maximum(mom[:, 0], 0.0))
        rate = np.zeros(len(eids))
        # group elements by S-N function (usually one per model)
        groups: Dict[int, List[int]] = {}
        for i, sn in enumerate(sns):
            if sn is not None and valid[i]:
                groups.setdefault(id(sn), []).append(i)
        for _, idxs in groups.items():
            sn = sns[idxs[0]]
            rate[idxs] = damage_rates(mom[idxs], sn, args.fatigue_method)
        eid_all.extend(int(e) for e in eids)
        rms_vm_all.extend(rms_vm)
        rate_all.extend(rate)
        mom_all.append(mom)
        if any(sn is None for sn in sns):
            n_no = sum(1 for sn in sns if sn is None)
            print(f"  NOTE: {n_no} {family} element(s) have no *MAT_ADD_FATIGUE"
                  " on their material - damage 0 there.")

    if stress_items:
        for mid, sn in sn_cache.items():
            if sn is not None:
                print(f"  fatigue (material {mid}): {sn.describe}; "
                      f"{args.fatigue_method} rainflow-range pdf")
        eid_arr = np.array(eid_all)
        rms_vm_arr = np.array(rms_vm_all)
        rate_arr = np.array(rate_all)
        mom_arr = np.vstack(mom_all)
        life = np.where(rate_arr > 0.0, 1.0 / np.maximum(rate_arr, 1e-300),
                        np.inf)
        _write_csv(stem + "_rms_stress.csv", "element,rms_von_mises",
                   ((int(eid_arr[i]), f"{rms_vm_arr[i]:.6G}")
                    for i in range(len(eid_arr))))
        _write_csv(stem + "_fatigue.csv",
                   "element,m0,m1,m2,m4,damage_per_s,"
                   f"damage_{args.duration:g}s,life_s",
                   ((int(eid_arr[i]), f"{mom_arr[i, 0]:.6G}",
                     f"{mom_arr[i, 1]:.6G}", f"{mom_arr[i, 2]:.6G}",
                     f"{mom_arr[i, 3]:.6G}", f"{rate_arr[i]:.6G}",
                     f"{rate_arr[i] * args.duration:.6G}",
                     f"{life[i]:.6G}") for i in range(len(eid_arr))))
        # LS-PrePost fringe file in the calculate_fatigue_pylife format
        with open(stem + "_fatigue_lsprepost.txt", "w", newline="\n") as fh:
            for i in range(len(eid_arr)):
                fh.write(f"{int(eid_arr[i])} "
                         f"{min(life[i], _LIFE_CAP):.6G}\n")
        iworst = int(np.argmax(rate_arr))
        print(f"\n  RMS von Mises stress (deck stress units) - "
              f"max {rms_vm_arr.max():.5G} at element "
              f"{int(eid_arr[np.argmax(rms_vm_arr)])}")
        if rate_arr[iworst] > 0.0:
            print(f"  worst fatigue: element {int(eid_arr[iworst])} - "
                  f"damage {rate_arr[iworst]:.4G}/s, life "
                  f"{life[iworst]:.4G} s ({life[iworst] / 3600.0:.4G} h)")
        else:
            print("  no fatigue damage accumulated in the band (all stress "
                  "ranges below the S-N data / threshold)")

    # ── ParaView VTK with everything as fields ──────────────────────────
    vtk_dir = Path(stem + "_random_vtk")
    vtk_dir.mkdir(parents=True, exist_ok=True)
    cell_scalars: Dict[str, "np.ndarray"] = {}
    if stress_items:
        # rms_vm_all / rate_all follow the stress_items order (shells then
        # solids), which is exactly the VTK cell order; beams (appended last
        # in the cell list) stay at zero damage / capped life.
        vm = np.zeros(mesh.n_cells)
        dr = np.zeros(mesh.n_cells)
        lg = np.full(mesh.n_cells, math.log10(_LIFE_CAP))
        vm_arr = np.array(rms_vm_all)
        rate_arr = np.array(rate_all)
        vm[:len(vm_arr)] = vm_arr
        dr[:len(rate_arr)] = rate_arr
        lg[:len(rate_arr)] = np.log10(
            np.minimum(np.where(rate_arr > 0, 1.0 / np.maximum(rate_arr, 1e-300),
                                _LIFE_CAP), _LIFE_CAP))
        cell_scalars = {"rms_von_mises": vm, "damage_per_s": dr,
                        "log10_life_s": lg}
    write_vtk(str(vtk_dir / "random_response.vtk"), mesh,
              comment=f"k2rad random-vibration response ({fmin:g}-{fmax:g} Hz)",
              point_vectors={"rms_displacement": rms_disp},
              point_scalars={"rms_displacement_magnitude": rms_mag},
              cell_scalars=cell_scalars or None)

    print(f"\n  outputs written with stem: {stem}")
    print("    _rms_displacement.csv (D3RMS), _psd_node_<id>.csv (D3PSD),")
    if stress_items:
        print("    _rms_stress.csv (D3RMS), _fatigue.csv (D3FTG), "
              "_fatigue_lsprepost.txt,")
    print(f"    _random_vtk{Path('/')}random_response.vtk (ParaView)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
