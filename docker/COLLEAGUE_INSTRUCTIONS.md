# LS-DYNA → OpenRadioss modal analysis in one container (k2rad)

This is a ready-to-run, containerized copy of our **complete modal-analysis
workflow**: you give it an LS-DYNA `.k` deck with `*CONTROL_IMPLICIT_EIGENVALUE`,
it converts the deck to OpenRadioss (k2rad), runs the implicit solver, solves the
eigenmodes offline, and writes **viewable results**:

- **`<model>_modes.d3plot`** — open in **LS-PrePost**: one state per mode, the
  state *time* is the mode frequency in **Hz**. Step through the states to browse
  the modes; exaggerate with the displacement scale factor.
- **`<model>_modes_vtk\mode_01_44.6Hz.vtk` …** — open in **ParaView**: apply
  *Warp By Vector* on the `mode_shape` array.
- If the deck carries `*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG` and
  `*MAT_ADD_FATIGUE`: random-vibration post-processing too — RMS displacement and
  von Mises stress CSVs, response-PSD spectra, Dirlik fatigue damage/life
  (`_fatigue.csv`, plus an LS-PrePost fringe file and a ParaView VTK).

It runs the exact same solver and tools we use, inside a small Linux container,
so it behaves identically on your machine — **AMD or Intel, nothing else to
install** (no Intel oneAPI, MPI, or Python setup; it's all inside the image).
The frequencies were validated against LS-DYNA R14 on our bogie test model:
modes 1–8 agree within 0.5 % with MAC = 1.000.

## What you received

Put these two files together in a folder (e.g. `C:\openradioss`):

| File | What it is |
|---|---|
| `openradioss-k2rad-20260703.tar` | The prebuilt image: OpenRadioss (MUMPS implicit, modal-patched engine) + k2rad + eigensolver + exporters (~3 GB) |
| `or.ps1` | Small PowerShell helper to run jobs |

---

## One-time setup

### 1. Install Docker Desktop
- Download & install: <https://www.docker.com/products/docker-desktop/>
- Keep **"Use WSL 2"** selected during install. Reboot if prompted.
- If install says WSL is missing: open **PowerShell as Administrator**, run
  `wsl --install`, reboot.
- Launch **Docker Desktop** and wait until the whale icon says **"Engine
  running."** Docker must be running whenever you launch a job.

### 2. Load the image (once)
Open **PowerShell**, go to the folder with the `.tar`, and run:

```powershell
docker load -i openradioss-k2rad-20260703.tar
docker images openradioss-k2rad     # should list tag 20260703
```

You won't need the `.tar` again after this.

---

## Running a modal job (the main workflow)

1. Put the LS-DYNA deck in a folder, e.g. `D:\runs\mymodel\mymodel.k`
   (the deck must contain `*CONTROL_IMPLICIT_EIGENVALUE`; the whole model in
   one file or with its `*INCLUDE` files next to it).
2. Copy **`or.ps1`** into that folder (or pass `-RunDir "D:\runs\mymodel"`).
3. Open **PowerShell in that folder** and run:

   ```powershell
   .\or.ps1 -KFile mymodel.k -Modal
   ```

   This does everything: convert → starter → implicit engine (np=1, exact
   stiffness export) → offline eigensolve → mode-shape export → (if the deck
   has the frequency-domain cards) random-vibration PSD/RMS/fatigue
   post-processing.

4. When it finishes, the folder contains:

   | Output | Open with |
   |---|---|
   | `mymodel_modes.d3plot` + `mymodel_modes.d3plot01` | **LS-PrePost** — keep the two files together (the states live in the `01` file). One state per mode, state time = frequency [Hz]. |
   | `mymodel_modes_vtk\mode_NN_<f>Hz.vtk` | **ParaView** — *Warp By Vector* on `mode_shape` |
   | `mymodel_modes.npz` | the raw eigensolution (frequencies + mass-normalized shapes) |
   | `mymodel_rms_displacement.csv`, `mymodel_rms_stress.csv` | RMS response (D3RMS equivalent) |
   | `mymodel_psd_node_<id>.csv` | response-PSD spectra at the highest-RMS nodes (D3PSD) |
   | `mymodel_fatigue.csv`, `mymodel_fatigue_lsprepost.txt` | Dirlik fatigue damage & life (D3FTG); the `.txt` loads as an LS-PrePost user fringe |
   | `mymodel_random_vtk\random_response.vtk` | all RMS/damage fields for ParaView |
   | `mymodel_conversion.log`, `*.out` | conversion notes + solver logs |

> The frequency table is printed at the end of the eigensolve — for a kg-mm-ms
> deck the `f [Hz] if deck time is ms` column is the one to read.

> **If PowerShell blocks the script** ("running scripts is disabled"), run:
> `powershell -ExecutionPolicy Bypass -File .\or.ps1 -KFile mymodel.k -Modal`

### Useful options

```powershell
.\or.ps1 -KFile mymodel.k -Modal -NModes 20   # solve more modes than the deck's NEIG
.\or.ps1 -KFile mymodel.k -ConvertOnly        # just produce the _0000/_0001.rad decks
```

Good to know about the physics:

- Mode shapes are exported **mass-normalized** (raw physics). If a mode looks
  invisible in LS-PrePost, raise the displacement scale factor.
- The eigensolver applies LS-DYNA-parity **drilling-rotation stiffness** by
  default, so shell models don't grow spurious drilling modes and the real
  structure lands in the PSD band (on the bogie: modes 4–10 at 129–274 Hz,
  all in the deck's 100–2000 Hz band).
- The random-vibration step assumes **base acceleration through the SPC support**
  along the deck's gravity direction, 2 % critical damping, and uses the deck's
  D3PSD band **in deck frequency units** (a kg-mm-ms deck's `0.1–2.0` band means
  100–2000 Hz). If no solved mode falls inside that band it warns loudly — the
  warning tells you the exact `--fmin/--fmax` override, or just solve more
  modes with `-NModes`.
- The run leaves the intermediates behind too: the converted `_0000/_0001.rad`
  decks, `.rst` restarts, animation files, and the raw exported stiffness
  matrix `local_stiffness_matrix_domain0` (~130 MB on the bogie). All safe to
  delete once you have the results.

---

## Ordinary (non-modal) runs — same as the vortex container

The image also contains everything the previous container did:

```powershell
# Explicit/implicit solve of converted decks (stem = name without _0000.rad):
docker run --rm --shm-size=2g -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 run mymodel 4 1

# Convert OpenRadioss animations to LS-DYNA d3plot:
docker run --rm -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 d3plot mymodel

# Convert an LS-DYNA .k deck only (extra k2rad flags pass through):
docker run --rm -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 convert mymodel.k

# Full modal chain without the helper script (optional mode count at the end):
docker run --rm --shm-size=2g -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 modal mymodel.k
docker run --rm --shm-size=2g -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 modal mymodel.k 20

# Interactive shell:
docker run --rm -it -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 bash
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running — start it, wait for "Engine running". |
| `/data` looks empty / "file not found" | Run PowerShell **from the model folder**, or pass `-RunDir`. Network drives: copy the model to a local disk first. |
| `modal` stops with "engine wrote no local_stiffness_matrix_domain0" | The `.k` has no `*CONTROL_IMPLICIT_EIGENVALUE` (add it, or run a normal solve), or the starter/engine failed earlier — scroll up in the log / check the `*.out` files. |
| Modal run stops with MESSAGE ID 79 / 44 | Should not happen (k2rad injects the dummy load / probe rigid body automatically) — send us the `_conversion.log`. |
| Random-vibration step warns "no solved mode inside the PSD band" | Solve more modes (`-NModes 30`) or rerun `modal_random_response.py` with the `--fmin/--fmax` the warning suggests (interactive shell). |
| Job killed / out of memory on big models | Docker Desktop → **Settings → Resources** → raise **Memory**. The implicit solve of a ~100k-DOF model wants several GB. |
| `mymodel_modes.d3plot` opens with 0 states | The `...d3plot01` file is missing — keep the pair together when copying. |
| Frequencies look 1000× too small | Your deck's time unit is seconds, not ms — read the `f [1/time-unit]` column instead. |

---

*Build: OpenRadioss `latest-20260520` + MUMPS 5.5.1 (Linux, double precision), engine
modal-patched (`imp_mumps.F`: exact E24.16 stiffness export + no-hang np=1 merge skip),
Vortex-Radioss anim→d3plot converter, k2rad converter + offline eigensolver (`--drill`
LS-DYNA-parity default) + mode-shape / random-vibration exporters. Validated against
LS-DYNA R14 on the W14 bogie: modes 1–8 within 0.5 %, MAC 1.000.*
