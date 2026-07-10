# Modal analysis (`*CONTROL_IMPLICIT_EIGENVALUE`)

[← back to README](../README.md#modal-analysis)

The **open-source OpenRadioss engine cannot solve `/EIG`**: the eigensolver
kernel (`engine/com/eig/*.F`) is not in the source release — only no-op stubs
gated behind an undefined `DNC` build macro — so the engine segfaults at init
(MESSAGE ID 44) the moment `NEIG>0`, and no build configuration can fix that.

So by default k2rad converts a modal deck to the validated **stiffness-export
recipe** the open-source engine *can* run:

1. **Starter**: the converted model **without `/EIG`**, plus an inert
   fully-fixed probe rigid body (see below) and — if the deck has no load —
   a dummy unit `/CLOAD` (the implicit engine refuses to start with no
   loading data, MESSAGE ID 79; the exported matrix is load-independent).
2. **Engine**: one linear implicit step — `/IMPL/LINEAR` +
   `/IMPL/PRINT/STIF` (data line `0 1 0`) + `/IMPL/SOLVER/2` +
   `/IMPL/MUMPS/AUTOCORE` + `/IMPL/DTINI`. `/IMPL/PRINT/STIF` is an
   undocumented engine keyword that makes MUMPS write the **exact assembled
   stiffness matrix** it factorizes to `local_stiffness_matrix_domain0`
   (run **np=1**).
3. **Offline eigensolve**: `tools/modal_solve.py` parses the matrix, rebuilds
   the lumped mass matrix from the source `.k` (identical to the engine's own
   MS/IN nodal lumping, verified to machine precision), and solves the
   generalized eigenproblem with `scipy.sparse.linalg.eigsh` (shift-invert):

```bash
python k2rad.py model.k                       # modal deck detected automatically
<starter/engine np=1 run>                     # writes local_stiffness_matrix_domain0
python tools/modal_solve.py run/local_stiffness_matrix_domain0 model.k -n 12
# static validation (must match an engine /CLOAD run to ~0%):
python tools/modal_solve.py run/local_stiffness_matrix_domain0 --static 17980 Z 1
```

Frequencies come out in cycles per deck **time unit** (kg-mm-ms deck → kHz);
mode shapes are saved to `modes.npz` (`freq`, `phi`, `user_node`, `dof`).
`modal_solve.py` needs `pip install scipy` (same optional stack as
`--auto-gapmin`; see `DEPENDENCIES.md`).

The eigensolve runs offline in its own Python process, so the engine's
`<stem>_0001.out` never captures the modal results. `modal_solve.py` therefore
mirrors everything it prints to a **`modal_solve.log`** next to the matrix file
(override with `--log PATH`, disable with `--no-log`).

**Validated** on the W14 bogie random-fatigue example (17 980 nodes, 4 shell
parts, 4×100 kg point masses): the exported-K static solve reproduces the
engine displacements to **0.000 %**, the first modes match an independent
explicit impulse ring-down FFT, and the spectrum matches LS-DYNA R14 (below).

## Drilling-rotation stiffness (`--drill`, LS-DYNA parity)

The rotation of a shell node about the element normal (the "drilling" DOF)
has near-zero stiffness in the exported K but finite lumped rotary inertia,
so the raw eigenproblem grows **spurious rotation-dominated modes** — on the
W14 bogie, 9 junk modes at 63–81 Hz that hid the real 129–290 Hz structure.
LS-DYNA implicit suppresses exactly this ("Drilling Rotation Constraint
Parameter 1.0" + AUTOSPC in d3hsp); `modal_solve.py` applies the same cure by
default: `K += factor · G·t·A/n_nodes · (n̂ n̂ᵀ)` on every shell node's
rotational block (`--drill`, default 1e-3; 0 disables).

**Cross-validated against an LS-DYNA R14 run of the same deck**
(`eigout` + `d3eigv`, `E:\openradioss_run\Ryan_Lee_Examples\W14_bogie_dyna`):

| mode | LS-DYNA [Hz] | k2rad chain [Hz] | Δf | MAC |
|---|---|---|---|---|
| 1–3 | 44.75 / 46.67 / 59.19 | 44.55 / 46.50 / 59.14 | ≤0.5 % | 1.000 |
| 4–8 | 128.9 … 228.3 | 128.9 … 227.3 | ≤0.5 % | 1.000 |
| 9 | 280.88 | 280.89 (our mode 11) | 0.003 % | 0.997 |

Mode-1 modal participation/effective mass also match `eigout` (Γ_Y = 20.45,
418 kg = 91.4 %). The retained modes are insensitive to the factor over
1e-4…3e-3, so the default needs no tuning. Our modes 9–10 are a ~274 Hz
near-degenerate local pair that LS-DYNA's DKQ shells place elsewhere —
at >6× the first frequency, formulation differences (QEPH vs DKQ) appear;
solve extra modes (`-n`) if you need parity in that tail.

## Stock-engine caveats (and the 1-line patches)

Two bugs in the stock engine's `/IMPL/PRINT/STIF` path — both worked around
automatically, both fixed by 1-line patches in
`engine/source/implicit/imp_mumps.F` (upstream PR candidates):

- **E10.2 precision**: the matrix is printed with `FORMAT(I10,I10,E10.2)` —
  2 significant digits, ~1 % stiffness rounding, **~0.5–1 % frequency
  error** (`modal_solve.py` detects this and warns). Patch: change FORMAT
  label 1003 from `E10.2` to `E24.16` (exact).
- **np=1 post-print hang**: after `--STIFFNESS MATRIX IS PRINTED--` the
  engine enters an O(NZ²) duplicate-merge scan meant for multi-domain runs
  and hangs for hours on millions of entries. **Kill the process — the
  per-domain file is already complete.** Patch: `IF (NSPMD==1) RETURN`
  right after the per-domain file is closed.

A locally patched engine with both fixes lives at
`C:\OpenRadioss_old\source\OpenRadioss-latest-20260520\engine\cbuild_engine_win64_impi_ninja\engine_win64_impi.exe`
(sources backed up as `*.orig_k2rad`); with it the run is exact and
terminates normally in seconds.

## `--eig`: classic /EIG output for commercial Radioss

Commercial Altair Radioss ships the real eigensolver, so users with a
commercial license can pass `--eig` (API: `emit_eig=True`) to get the classic
output instead: a starter `/EIG` block (whole structure, free eigenmodes) and
a one-shot `/IMPL/LINEAR` eigensolve engine. This deck **starter-validates
with 0 errors** but the open-source engine segfaults on it.

## Inert probe rigid body (all implicit decks)

The OpenRadioss implicit engine **segfaults at solver init (MESSAGE ID 44)
when the model contains no rigid body** — for every implicit flavor and
independent of contact. Whenever an implicit deck (modal or not) has no
`/RBODY`, the converter injects an inert probe: 3 nodes far outside the
model tied into a `/RBODY` with `Mass=Jxx=Jyy=Jzz=1e-3` (zero rigid-body
inertia is ERROR 274) whose master node is fully fixed (`/BCS 111 111`).
It adds no equations and has zero effect on results, the eigenmodes, or the
exported stiffness matrix. For modal decks it also **replaces** the inert
contact stub, which must not be emitted there — its initial-penetration
corrections pollute the exported K (on the W14 bogie they shifted the static
response ~2× and the first eigenfrequency 44.5 → 24.7 Hz).

## Viewing the mode shapes (LS-PrePost + ParaView)

`tools/modal_shapes_export.py` turns the `modes.npz` + source `.k` into
directly viewable files:

```bash
python tools/modal_shapes_export.py run/model_modes.npz model.k
```

- **LS-PrePost**: `model_modes.d3plot` + `model_modes.d3plot01` — a d3plot
  family in the style of LS-DYNA's `d3eigv`: one state per mode, the state
  *time* is the mode frequency in **Hz**, the nodal displacements are the
  mass-normalized shape (constrained nodes zero). Open the root file and step
  through the states; exaggerate with the displacement scale factor.
  **Keep the two files together** — the states live in the `01` file
  (lasso-python always splits, even with `single_file=True`). Naming the file
  `d3eigv` does *not* work: LS-PrePost's d3eigv reader expects LS-DYNA's extra
  eigen records and reads 0 states (verified with LS-PrePost 4.13).
- **ParaView**: `model_modes_vtk/mode_01_44.5Hz.vtk` … — one legacy VTK per
  mode with a point vector `mode_shape` (plus its magnitude), ready for
  *Warp By Vector*. `--animate N` adds N sinusoidal frames per mode plus a
  ParaView `.vtk.series` index for direct playback.

Options: `--modes 1,3-5` (subset), `--scale F` (uniform factor),
`--normalize PCT` (rescale every mode's peak to PCT % of the model size —
useful for rotation-dominated modes, e.g. a lumped `*ELEMENT_MASS` node
pivoting about its shell patch, whose translational amplitudes are tiny),
`--formats d3plot,vtk`, `--time-unit auto|s|ms`.

The npz frequencies are cycles per deck **time unit**; the Hz labels use
`--time-unit` (default `auto`: guessed from the deck's gravity magnitude,
else material wave speed + model size, and printed — a kg-mm-ms deck gives
×1000). The d3plot writer needs `pip install lasso-python`; the VTK export
runs on numpy alone.

## Random vibration & fatigue (D3PSD / D3RMS / D3FTG, `*MAT_ADD_FATIGUE`)

LS-DYNA's frequency-domain databases have **no OpenRadioss equivalent**, so
k2rad implements them offline on top of the modal solution — classic
modal-superposition random vibration of a base-excited structure:

```bash
python tools/modal_random_response.py run/model_modes.npz model.k \
       [--damping 0.02] [--dir Y] [--fmin 20 --fmax 120]
```

- **Excitation**: uniform base acceleration through the SPC support, along
  `--dir` (default: the deck's gravity direction, else Z), with the input
  acceleration PSD from the deck's `*DEFINE_CURVE` (auto-picked: the only
  curve not referenced as S-N data; `--psd-curve` overrides). Curve ordinate
  is acceleration²/frequency in deck units (`--psd-unit g2hz` + `--g` for
  g²/Hz data); outside the curve the end values are held constant (LS-DYNA
  load-curve convention).
- **Band**: the deck's D3PSD `fmin/fmax` (deck frequency units — cycles per
  time unit, so a kg-mm-ms deck's `0.1–2.0` means 100–2000 Hz). The tool
  **warns when no solved mode falls inside the band** (the LS-PrePost-authored
  examples carry bands above their first modes) and `--fmin/--fmax` (in Hz)
  override it.
- **Damping**: `--damping`, default **2 % critical** (the eigen recipe carries
  no usable damping definition).
- **Outputs** (`<jobname>_…`): `_rms_displacement.csv` + `_rms_stress.csv`
  (D3RMS), `_psd_node_<id>.csv` response spectra (D3PSD), `_fatigue.csv`
  with spectral moments / damage rate / life (D3FTG),
  `_fatigue_lsprepost.txt` (`eid life` pairs, the `calculate_fatigue_pylife`
  fringe format, capped at 1e9), and `_random_vtk/random_response.vtk` with
  everything as ParaView fields.

The theory: participation factors `Γ_j = φ_jᵀ M r` (lumped M identical to the
engine's), modal FRFs `H_j(f) = -Γ_j/(ω_j²-ω²+2iζω_jω)`, full modal
superposition including all cross terms; element stresses by centroid strain
recovery (CST/bilinear shells with ±t/2 bending surfaces, constant-strain
tets, trilinear hexas); von Mises stress PSD via Segalman's EVMS
`G_vm = tr(Q·S_σ)`; fatigue damage by integrating the **Dirlik** stress-range
pdf (`--fatigue-method narrowband` for the Rayleigh pdf) against the
`*MAT_ADD_FATIGUE` S-N data (curve semi-log/log-log per LTYPE, range or
amplitude per SNTYPE, below-curve behaviour per SNLIMT, threshold STHRES).
The machinery is validated in the test suite against a direct
frequency-domain solve (2-DOF, machine precision), closed-form narrow-band
damage, and exact stress patch tests; on the W14 bogie the resonant RMS
displacement matches Miles' equation within ~1 %.

## GUI integration

The OpenRadioss GUI's modal post-step (`runopenradioss.py`,
`modal_post_solve`) runs the whole chain automatically after a modal job:
`modal_solve.py` → `modal_shapes_export.py` (viewable mode shapes) → and,
when the deck carries D3PSD/D3RMS/D3FTG/`*MAT_ADD_FATIGUE` cards,
`modal_random_response.py`. Point the GUI at the k2rad checkout with the
`K2RAD_PATH` environment variable.
