# LS-DYNA to OpenRadioss Converter (k2rad)

[![tests](https://github.com/pmquang87/k_to_rad_converter/actions/workflows/tests.yml/badge.svg)](https://github.com/pmquang87/k_to_rad_converter/actions/workflows/tests.yml)

Convert LS-DYNA keyword files (`.k`) to OpenRadioss starter/engine files
(`*_0000.rad` and `*_0001.rad`). Targets **explicit and implicit dynamic**
structural analyses with rigid bodies, contact, prescribed motion, and
plasticity.

Tested against OpenRadioss 2022 / 2024+ on Windows + Intel MPI. The
implicit dynamic engine successfully runs on a 568 k DOF model with two
rigid bodies and a contact interface (`implicit_hr-anlenkung` test case).

---

## Contents

- [Quick start](#quick-start)
- [Supported LS-DYNA keywords](#supported-ls-dyna-keywords)
- [Unit system](#unit-system)
- [Implicit dynamic notes](#implicit-dynamic-notes)
- [Modal analysis](#modal-analysis)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [License](#license)

Deeper references: [`docs/IMPLICIT.md`](docs/IMPLICIT.md) ·
[`docs/MODAL.md`](docs/MODAL.md) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) ·
[`docs/BLAST_ALE_JWL_MAPPING.md`](docs/BLAST_ALE_JWL_MAPPING.md) ·
[`ROADMAP.md`](ROADMAP.md)

---

## Quick start

```bash
git clone https://github.com/pmquang87/k_to_rad_converter.git
cd k_to_rad_converter
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # Linux/macOS
```

No external dependencies — pure standard-library Python ≥ 3.9.

### CLI

```bash
python k2rad.py path/to/model.k
python k2rad.py path/to/model.k output/stem
python k2rad.py path/to/model.k --quiet
python k2rad.py path/to/model.k --units Mg mm s
```

`--units` sets the labels written to the `/BEGIN` header only — values are
never rescaled, so the labels should match the units already used in the
`.k` file. The default is the LS-DYNA `Mg mm s` system.

Output is written as `<stem>_0000.rad` (starter) and `<stem>_0001.rad`
(engine) next to the input file by default.

### Python API

```python
from k2rad import convert

result = convert("path/to/model.k")
print(result.starter_path, result.engine_path)
print(result.skipped_keywords, result.warnings)
```

Or edit `run_converter.py` to set a hardcoded path and run
`python run_converter.py`.

### Docker container (converter + solver + modal chain, zero setup)

The [`docker/`](docker/) directory packages the **complete workflow into one
Linux container** — k2rad, OpenRadioss with MUMPS implicit and the
modal-patched engine, the offline eigensolver, mode-shape exporters and the
random-vibration/fatigue post-processing — so an LS-DYNA
`*CONTROL_IMPLICIT_EIGENVALUE` deck runs end-to-end with nothing installed
but Docker:

```powershell
.\or.ps1 -KFile mymodel.k -Modal      # convert -> solve -> modes -> PSD/RMS/fatigue
docker run --rm --shm-size=2g -v "${PWD}:/data" -w /data openradioss-k2rad:20260703 modal mymodel.k
```

See [docker/COLLEAGUE_INSTRUCTIONS.md](docker/COLLEAGUE_INSTRUCTIONS.md) for
the end-user guide (setup, outputs, troubleshooting) and
[docker/Dockerfile](docker/Dockerfile) /
[docker/build-and-export.ps1](docker/build-and-export.ps1) to build and
export the image.

---

## Supported LS-DYNA keywords

### Mesh & geometry
`*NODE`, `*ELEMENT_SHELL`, `*ELEMENT_SOLID`, `*ELEMENT_BEAM`, `*ELEMENT_MASS`,
`*ELEMENT_MASS_NODE_SET`, `*ELEMENT_MASS_PART`, `*ELEMENT_MASS_PART_SET`,
`*PART`, `*SECTION_SHELL`, `*SECTION_SOLID`, `*SECTION_BEAM`

### Materials
`*MAT_ELASTIC` → `/MAT/LAW1`
`*MAT_PIECEWISE_LINEAR_PLASTICITY` (+ `_MODIFIED_`) → `/MAT/LAW36`
`*MAT_PLASTIC_KINEMATIC` → `/MAT/LAW44` (`b` = plastic hardening modulus
E·ETAN/(E−ETAN); `Chard` = 1−BETA — the iso/kinematic conventions run in
opposite directions)
`*MAT_POWER_LAW_PLASTICITY` → `/MAT/LAW36` (auto-generated curve)
`*MAT_SIMPLIFIED_JOHNSON_COOK` → `/MAT/LAW36` (σ = A + B·εpⁿ sampled into an
auto-generated yield table, capped at `SIGMAX`; the `(1 + C·ln ε̇*)` rate term
has no LAW36 mapping and is dropped with a warning)
`*MAT_187` / `*MAT_SAMP-1` → `/MAT/LAW76` (SAMP-1 polymer; the tension/
compression/shear yield curves become `/TABLE/1` cards)
Material failure strain (MAT_003 `FS` / MAT_024 `FAIL` / MAT_018 `EPSF`) →
`/FAIL/JOHNSON` `D1` with `Ifail_sh=2` (delete only when ALL through-thickness
points fail, LS-DYNA's built-in erosion rule) instead of the material `Eps_max`
(first-point deletion, which over-eroded 5x on the W13 blast validation pair)
`*MAT_ADD_DAMAGE_GISSMO` → `/FAIL/TAB2` (GISSMO tabulated damage: `LCSDG`→
`EPSF_ID`, `DMGEXP`→`N`, `DCRIT`, `NUMFIP`→`FAILIP`, `LCREGD`→`TAB_EL`; a
negative `ECRIT`/`FADEXP` is resolved to the instability/fading curve)
`*MAT_ADD_EROSION` → an OpenRadioss `/FAIL` model for the strain criteria:
`MXEPS` (max principal strain) → `/FAIL/TENSSTRAIN`, `EFFEPS` (max effective
strain) → `/FAIL/JOHNSON`. Other criteria and `IDAM≥1` (GISSMO/DIEM embedded in
the erosion card) are reported but not converted (use `*MAT_ADD_DAMAGE_GISSMO`)
`*MAT_RIGID` → `/MAT/LAW1` + `/RBODY`. By default the `/RBODY` master is a
**synthesized element-free node** at the part's nodal centroid (the treatment
CNRBs always get): mesh nodes keep their source coordinates, the starter
WARNINGs 448/1624 (master connected to an element / removed from the secondary
set) disappear, and the deck is AMS-compatible (a mesh-node master trips AMS
`ERROR 1066`). Pass `--no-rigid-cog-master` to instead reuse the part's
lowest-id mesh node as the master (keeps that node id stable for scripts that
address loads/readouts by it; OpenRadioss then relocates it to the CoM at
runtime, so it appears to move in post-processing).
`*MAT_NULL` → `/MAT/VOID` (or a `/MAT/LAW6` hydro carrier when it has an `*EOS_*`)
`*MAT_HIGH_EXPLOSIVE_BURN` (+ its `*EOS_JWL`) → `/MAT/LAW5` (JWL)
Foams & honeycomb: `*MAT_CRUSHABLE_FOAM` (63) → `/MAT/LAW50`,
`*MAT_LOW_DENSITY_FOAM` (57) → `/MAT/LAW38`, `*MAT_FU_CHANG_FOAM` (83) →
`/MAT/LAW70`, `*MAT_HONEYCOMB` (26) → `/MAT/LAW28`. The referenced stress-strain
`*DEFINE_CURVE`s become `/FUNCT`s; law-specific unmapped fields (foam tension
cutoff / damping / hysteresis shape, honeycomb compaction modulus) are dropped
with a warning, so review the converted card against the source foam
`*EOS_LINEAR_POLYNOMIAL` → `/EOS/POLYNOMIAL`, `*EOS_GRUNEISEN` → `/EOS/GRUNEISEN`,
`*EOS_IDEAL_GAS` → `/EOS/IDEAL-GAS` (γ = Cp/Cv, P0 = ρ(Cp−Cv)T0)

### Sets & coordinate systems
`*SET_NODE_LIST` (+ `*SET_NODE`), `*SET_PART_LIST` (+ `*SET_PART`)
`*DEFINE_CURVE`, `*DEFINE_COORDINATE_SYSTEM`
`*DEFINE_CURVE_FUNCTION` → `/FUNCT` (a pure single-variable `x`/`time` analytic
expression is sampled into an X-Y function over `[0, termination]`; expressions
that reference parameters, other curves, or runtime state are warned + skipped)
`*PARAMETER` (fixed and free format, `R`/`I` types) — `&name` references are
resolved wherever a field is parsed; `*PARAMETER_EXPRESSION` is not evaluated
(warned). LS-DYNA **comma-delimited free format** is accepted on every card.

### Constraints
`*CONSTRAINED_NODE_SET` → `/RLINK` (nodes share the same velocity along the
constrained DOF; `DOF` 1/2/3 = x/y/z translation, 4 = all translations, 5/6/7 =
rotation. `TF` failure time has no `/RLINK` equivalent and is dropped)
`*CONSTRAINED_EXTRA_NODES_NODE/_SET` — the extra nodes join the rigid part's
`/RBODY` secondary-node group (also lets an element-free `*MAT_RIGID` part form
a rigid body)
`*CONSTRAINED_RIGID_BODIES` → one merged `/RBODY`: the slave rigid part's nodes
fold into the master's secondary-node group (chains `A←B←C` resolve
transitively), and the slave part id still resolves for loads/motions/readouts

### Boundary conditions / motion
`*BOUNDARY_SPC` (+ `_NODE`/`_SET`) → `/BCS`
`*BOUNDARY_PRESCRIBED_MOTION_RIGID` → `/IMPDISP`, `/IMPVEL`, `/IMPACC`
`*BOUNDARY_PRESCRIBED_MOTION_SET` / `_NODE` → `/IMPDISP` (or `/BCS` when
`sf=0`, a common LS-DYNA idiom for symmetry/fixed-DOF)
`*RIGIDWALL_PLANAR` (+`_ID`, `_FORCES`) → `/RWALL/PLANE` (fixed infinite plane;
`FRIC` 0 → sliding, 0<f<1 → Coulomb friction, ≥1 → tied; `NSID=0` tracks all
nodes via a bounding-box search distance; `*DATABASE_RWFORC` → `/TH/RWALL`.
The `_MOVING`/`_FINITE`/`_ORTHO` flavours are skipped with a warning)

### Loads
`*LOAD_RIGID_BODY` → `/CLOAD` on rigid body master node
`*LOAD_NODE_POINT/_SET` → `/CLOAD` (forces DOF 1-3, moments DOF 5-7; the CID
local system maps to the `/CLOAD` skew; follower loads 4/8 are warned)
`*LOAD_SEGMENT`, `*LOAD_SEGMENT_ID` → `/PLOAD`
`*LOAD_SEGMENT_SET` → `/PLOAD` (pressure on a `*SET_SEGMENT` surface)
`*LOAD_GRAVITY_PART[_SET]` → `/GRAV` on a `/GRNOD/PART` (non-modal decks;
DOF 1/2/3 loads along −X/−Y/−Z, so `Fscale_Y = -accel`. Modal decks get an
informational note instead — gravity does not change a non-prestressed
eigenproblem)

### Blast & coupled ALE / high explosive
Empirical (ConWep / TM5-1300) air blast:
`*LOAD_BLAST_ENHANCED`, `*LOAD_BLAST` (legacy) → `/LOAD/PBLAST`
`*LOAD_BLAST_SEGMENT_SET`, `*LOAD_BLAST_SEGMENT` (per-segment) → `/SURF/SEG` +
`/LOAD/PBLAST` (surface bursts synthesize a `/SURF/PLANE` reflecting ground,
`--blast-ground`); `*SET_SEGMENT` → `/SURF/SEG`; `*LOAD_BODY_{X,Y,Z}` → `/GRAV`

Coupled ALE / fluid-structure (high-explosive detonation):
`*INITIAL_DETONATION` → `/DFS/DETPOINT`
`*ALE_MULTI-MATERIAL_GROUP` → `/MAT/LAW51` (MULTIMAT, ordered submaterials)
`*SECTION_SOLID` ELFORM 11/12 → `/PROP/SOLID` `Iale=1` (ALE)
`*CONSTRAINED_LAGRANGE_IN_SOLID` → `/INTER/TYPE18` (penalty FSI) + `/GRBRIC/PART`
`*BOUNDARY_NON_REFLECTING` → `/EBCS/NRF`
`*CONTROL_ALE` → ALE advection note; `*INITIAL_VOLUME_FRACTION_GEOMETRY` →
`/INIVOL` (recognised; container geometry needs a manual `/SURF`)

See `docs/BLAST_ALE_JWL_MAPPING.md` for the full mapping table, card formats and
unit/sign gotchas.

### Initial conditions
`*INITIAL_VELOCITY_NODE` → `/INIVEL/NODE`
`*INITIAL_VELOCITY_RIGID_BODY` → `/INIVEL/RBODY`

### Contact
`*CONTACT_AUTOMATIC_SINGLE_SURFACE` (+ `_MORTAR`, `_GENERAL`) → `/INTER/TYPE7`
`*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` (+ `_ONE_WAY_*`) → `/INTER/TYPE7`
`*CONTACT_..._TIEBREAK` (`SURFACE_TO_SURFACE_TIEBREAK`, `_ONE_WAY_...`,
`TIEBREAK_{SURFACE,NODES}_TO_SURFACE`) → `/INTER/TYPE7` for the post-failure
contact, **with a warning that the cohesive pre-bond (NFLS/SFLS stress failure)
has no open-source OpenRadioss equivalent and is dropped** — the parts contact
but do not pre-bond
`*CONTACT_TIED_{NODES,SHELL_EDGE,SURFACE}_TO_SURFACE` (+ `_OFFSET` variants) →
`/INTER/TYPE2` (tied kinematic interface): slave `*SET_NODE_LIST` (SSTYP=4) →
`/GRNOD`, master `*SET_SEGMENT` (MSTYP=0) → `/SURF/SEG`; parts / part sets on
either side are also resolved. `Spotflag=1` (spotweld formulation) for the
NODES/SHELL_EDGE weld variants, `Spotflag=5` (standard) for SURFACE_TO_SURFACE.
The TYPE2 `dsearch` is measured from the mesh — the worst slave-node-to-master-
segment distance × 1.2 — so tied nodes offset from a shell master's MID-PLANE
by half the plate thickness (the usual welded-shell layout) stay tied;
`Ignore=2` makes the starter drop (and print) any node beyond it, and a
negative Card-3 `SST`/`MST` (LS-DYNA's absolute tie distance) floors `dsearch`.
`ignore=0/1/2` → `Inacti=5` (LS-DYNA neutralizes initial penetrations at
initialization for every ignore setting; `Inacti=0` would apply the full
penalty force to resting-contact nodes at cycle 0). Exception: an implicit
deck with an SST/MST-derived `Gapmin` keeps `Inacti=0` (the documented
pre-engagement bootstrap needs the t=0 stiffness path)

### Control / output
`*CONTROL_IMPLICIT_GENERAL/SOLUTION/AUTO/DYNAMICS` → `/IMPL/*` blocks
`*CONTROL_IMPLICIT_EIGENVALUE` → modal stiffness-export recipe
(`/IMPL/PRINT/STIF` + `tools/modal_solve.py`), or `/EIG` with `--eig`
`*CONTROL_TERMINATION` → engine `/RUN/...`
Engine restart (`.rst`) files are **off by default** (`/RFILE/OFF` in the engine
deck) — they are only needed for `/RERUN`/crash recovery and are large; pass
`--write-restart` (CLI) or tick the GUI box to keep OpenRadioss's default restart
writing. (The starter's `_0000_*.rst` model-handoff file is always written.)
`*CONTROL_TIMESTEP` `DT2MS`<0 → engine `/DT/NODA/CST/0` (nodal mass scaling that
holds the explicit time step at `|DT2MS|`; `Tsca` = `TSSFAC` or 0.9). Without it
OpenRadioss runs at the raw smallest-element step — on a fine/TET mesh that can
be ~100× below `DT2MS`, i.e. a ~100× slower run. Explicit decks only.
`--ams` (CLI) / GUI checkbox swaps that nodal mass scaling for **Advanced Mass
Scaling**: engine `/DT/AMS` (`Tsca` 0.67) + starter `/AMS` (all parts; the
solver auto-skips rigid bodies). AMS holds `|DT2MS|` with a *coupled* mass
matrix that preserves the low-frequency response instead of adding real nodal
mass — useful when `/DT/NODA/CST`'s added mass dwarfs the physical mass on a fine
mesh and swamps the dynamics (kinetic energy runs away). It solves a
preconditioned conjugate gradient each cycle and **can diverge** (`AMS IS LIKELY
DIVERGING`) on stiff / high-stiffness-contrast / contact-heavy models or at a
large `|DT2MS|`/element-step ratio; if it does, drop `--ams` (back to the default
`/DT/NODA/CST`) or lower `|DT2MS|`. Off by default. Needs element-free rigid
masters (the default; a whole-part rigid body's master must not be an element
node or AMS aborts with `ERROR 1066`), so `--ams` force-enables them even if you
passed `--no-rigid-cog-master`. Explicit decks only.
`*CONTROL_ACCURACY`, `*CONTROL_CONTACT`, `*CONTROL_HOURGLASS`,
`*CONTROL_OUTPUT`, `*CONTROL_SHELL`, `*CONTROL_SOLID`, `*CONTROL_ENERGY`,
`*CONTROL_CPU`
`*DATABASE_*` (binary output, time-history channels)
`*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG`, `*MAT_ADD_FATIGUE` → no
OpenRadioss equivalent; honoured **offline** by
`tools/modal_random_response.py` on top of the modal solution (see
*Random vibration & fatigue* in [`docs/MODAL.md`](docs/MODAL.md)) — never
bare-skipped

Unsupported keywords are listed in `result.skipped_keywords` and as
comments in the generated `_0000.rad`.

---

## Unit system

The converter declares `Mg mm s` (megagram / millimetre / second) in the
generated `/BEGIN` block — i.e. the **LS-DYNA default** ton-mm-s-N-MPa
system. Numerical values are written as-is; the converter does **not**
rescale.

| Quantity | Unit | Example |
|---|---|---|
| Mass | Mg (tonne) | steel density `7.86e-9` |
| Length | mm | element edge `~1` |
| Time | s | termination `1.0` |
| Force | N | rigid-body load `6000` |
| Stress | MPa | Young's modulus `200000` |

---

## Implicit dynamic notes

The converter generates OpenRadioss implicit dynamic engine files using
`/IMPL/DYNA/2` (Newmark) when the `.k` file specifies
`*CONTROL_IMPLICIT_DYNAMICS IMASS=1`. Small-mass loaded rigid bodies are
stabilized against a singular `K_eff = K + M/(βΔt²)` by two complementary
layers (an automatic `/BCS` on non-loaded DOFs, or `*ELEMENT_MASS_PART` added
mass), and contact convergence is handled by matching each interface `Gapmin`
to the measured mesh clearance (`--auto-gapmin`) plus a validated
deformable–deformable stabilization recipe (`--deformable-contact-recipe`).

See [`docs/IMPLICIT.md`](docs/IMPLICIT.md) for the full treatment — the K_eff
stabilization mechanics, the `/BCS`/`*ELEMENT_MASS_PART` layering, the
`--auto-gapmin` / `--suggest-gapmin` workflow, and the deformable-contact
recipe.

---

## Modal analysis

A modal deck (`*CONTROL_IMPLICIT_EIGENVALUE`) is handled through a validated
**stiffness-export recipe**, because the open-source OpenRadioss engine has no
eigensolver kernel and segfaults on `/EIG`. k2rad emits a one-step
`/IMPL/LINEAR` + `/IMPL/PRINT/STIF` run that writes the exact assembled
stiffness matrix, then `tools/modal_solve.py` rebuilds the lumped mass matrix
and solves the eigenproblem offline with scipy (cross-validated against LS-DYNA
R14 to ≤0.5 %). Mode shapes export to LS-PrePost d3plot / ParaView VTK, and
LS-DYNA's frequency-domain databases (D3PSD/D3RMS/D3FTG, `*MAT_ADD_FATIGUE`)
are honoured offline as modal-superposition random vibration and Dirlik
fatigue. Commercial Altair Radioss users can instead pass `--eig` for classic
`/EIG` output.

See [`docs/MODAL.md`](docs/MODAL.md) for the full chain — the export recipe,
drilling-stiffness parity (`--drill`), stock-engine caveats and 1-line patches,
the inert probe rigid body, mode-shape viewing, random vibration & fatigue, and
GUI integration.

### Further linear analyses on the exported stiffness matrix

The same offline stiffness-export chain drives two more analysis types the
open-source engine otherwise lacks:

- **Linear buckling** — `tools/modal_buckling.py` solves `K φ = λ(−K_g)φ`
  (static pre-solve → consistent geometric stiffness → eigensolve) and reports
  the buckling factors and `P_cr`. Beam/rod/truss elements are supported and
  validated against the analytic Euler pin-pinned column (`P_cr = π²EI/L²`) to
  0.001 %; shell/solid elements are counted and skipped with a warning rather
  than reported with a wrong factor.
- **Harmonic / frequency response (FRF)** — `tools/modal_frf.py` sweeps a
  modal-superposition FRF for base excitation (`--dir`) or a nodal harmonic load
  (`--load`) and writes per-node magnitude/phase spectra plus a resonance-peak
  table (validated against the closed-form SDOF response).

Both need the optional `[modal]` extra (numpy + scipy).

---

## Project structure

```
k_to_rad_converter/
├── k2rad.py              # CLI entry point
├── run_converter.py      # Script-style entry with hardcoded path
├── k2rad/
│   ├── __init__.py       # convert() function and ConversionResult
│   ├── parser.py         # .k file parser (handles *INCLUDE)
│   ├── handlers.py       # One handler per LS-DYNA keyword
│   ├── state.py          # ConversionState data model
│   ├── gapmin.py         # Suggest /INTER/TYPE7 Gapmin from mesh clearance
│   └── writer.py         # Generates _0000.rad starter + _0001.rad engine
├── tools/
│   ├── modal_solve.py    # Offline eigensolver for the modal K-export recipe
│   ├── modal_common.py   # Shared mesh/npz/unit/VTK helpers for the tools
│   ├── modal_shapes_export.py    # Mode shapes → LS-PrePost d3plot + ParaView VTK
│   └── modal_random_response.py  # D3PSD/D3RMS/D3FTG + MAT_ADD_FATIGUE offline
├── tests/                # Standard-library unittest suite
├── tutorial_example/     # Sample .k files
├── Ryan_Lee_Examples/    # Larger test models (W2-W7)
└── implicit_hr-anlenkung/ # Implicit dynamic regression test
```

## Testing

The test suite uses only the standard library (no pytest required):

```bash
python -m unittest discover -s tests
```

---

## Known limitations

- `/RBODY` uses the OpenRadioss 2-card variant (10-field card 3 + 6-inertia
  card 4). The 4-card "documented" form (Reference Guide p.1877) triggers
  ERROR 760 segfault during element-group setup when `Mass>0`. The 2-card
  form produces a soft `WARNING 100217` ("card is missing") but otherwise
  solves correctly.
- `/IMPL/SOLVER/7` (Auto solver) is **deprecated** in OpenRadioss 2024+
  (MESSAGE ID 296). Use `/IMPL/SOLVER/2` (MUMPS direct) for SPMD, falls
  back to `/IMPL/SOLVER/1` (PCG) for memory-constrained large models.
- `*INCLUDE` is supported (file path resolved relative to the parent .k
  file).

---

## License

MIT
