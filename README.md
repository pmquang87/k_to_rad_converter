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

---

## Supported LS-DYNA keywords

### Mesh & geometry
`*NODE`, `*ELEMENT_SHELL`, `*ELEMENT_SOLID`, `*ELEMENT_BEAM`, `*ELEMENT_MASS`,
`*ELEMENT_MASS_NODE_SET`, `*ELEMENT_MASS_PART`, `*ELEMENT_MASS_PART_SET`,
`*PART`, `*SECTION_SHELL`, `*SECTION_SOLID`, `*SECTION_BEAM`

### Materials
`*MAT_ELASTIC` → `/MAT/LAW1`
`*MAT_PIECEWISE_LINEAR_PLASTICITY` (+ `_MODIFIED_`) → `/MAT/LAW36`
`*MAT_PLASTIC_KINEMATIC` → `/MAT/LAW44`
`*MAT_POWER_LAW_PLASTICITY` → `/MAT/LAW36` (auto-generated curve)
`*MAT_RIGID` → `/MAT/LAW1` + `/RBODY`
`*MAT_NULL` → void material

### Sets & coordinate systems
`*SET_NODE_LIST` (+ `*SET_NODE`), `*SET_PART_LIST` (+ `*SET_PART`)
`*DEFINE_CURVE`, `*DEFINE_COORDINATE_SYSTEM`

### Boundary conditions / motion
`*BOUNDARY_SPC` (+ `_NODE`/`_SET`) → `/BCS`
`*BOUNDARY_PRESCRIBED_MOTION_RIGID` → `/IMPDISP`, `/IMPVEL`, `/IMPACC`
`*BOUNDARY_PRESCRIBED_MOTION_SET` → `/IMPDISP` (or `/BCS` when `sf=0`, a
common LS-DYNA idiom for symmetry/fixed-DOF)

### Loads
`*LOAD_RIGID_BODY` → `/CLOAD` on rigid body master node
`*LOAD_SEGMENT`, `*LOAD_SEGMENT_ID` → `/PLOAD`

### Initial conditions
`*INITIAL_VELOCITY_NODE` → `/INIVEL/NODE`
`*INITIAL_VELOCITY_RIGID_BODY` → `/INIVEL/RBODY`

### Contact
`*CONTACT_AUTOMATIC_SINGLE_SURFACE` (+ `_MORTAR`, `_GENERAL`) → `/INTER/TYPE7`
`*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` (+ `_ONE_WAY_*`) → `/INTER/TYPE7`

### Control / output
`*CONTROL_IMPLICIT_GENERAL/SOLUTION/AUTO/DYNAMICS` → `/IMPL/*` blocks
`*CONTROL_TERMINATION` → engine `/RUN/...`
`*CONTROL_TIMESTEP`, `*CONTROL_ACCURACY`, `*CONTROL_CONTACT`, `*CONTROL_HOURGLASS`,
`*CONTROL_OUTPUT`, `*CONTROL_SHELL`, `*CONTROL_SOLID`, `*CONTROL_ENERGY`,
`*CONTROL_CPU`
`*DATABASE_*` (binary output, time-history channels)

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
`*CONTROL_IMPLICIT_DYNAMICS IMASS=1`.

### Stabilizing free DOFs on small-mass rigid bodies

LS-DYNA implicit dynamic tolerates rigid bodies with very small inherent
mass (typical for thin-shell impactors / loading platens). OpenRadioss
MUMPS direct solver does **not** — the effective stiffness
`K_eff = K + M/(βΔt²)` becomes singular at the rigid body master node
when:

- the rigid body is loaded by `*LOAD_RIGID_BODY` in a free DOF, and
- the inherent (element + density) mass is too small to make
  `M/(βΔt²)` comparable to `K`.

The converter has two complementary stabilization mechanisms:

#### 1. Automatic `/BCS` on non-loaded translation DOFs

If a loaded rigid body has translation DOFs that are not loaded AND not
already constrained by `*MAT_RIGID CMO/CON1/CON2`, the converter adds a
`/BCS` to fix those DOFs. Emits a warning naming the affected axes.

#### 2. `*ELEMENT_MASS_PART` for true added mass (preferred)

To preserve the original physics (no extra constraints), add explicit
non-structural mass to the rigid body:

```
*ELEMENT_MASS_PART
$#       pid   addmass   finmass      lcid       mwd
  10000000          1         0         0         0
  10000001          1         0         0         0
```

- `pid`: part ID of the rigid body
- `addmass`: extra translational mass in input units (Mg = tonne).
  `1` ≈ 1000 kg, plenty for stabilization on impactor-sized rigid bodies.

When the converter sees `*ELEMENT_MASS_PART` (or `*ELEMENT_MASS` on the
master node) for a rigid body, it **skips the automatic `/BCS`** and
relies on the user-provided mass for K_eff stabilization instead.

Both formats are accepted: fixed I10 columns or free format
(whitespace / comma separated).

### Why both layers exist

The order of operations matters in OpenRadioss's MUMPS solver:

1. Card-3 of `/RBODY` puts added mass on the rigid body's master node
2. The mass term `M(z,z)/(βΔt²)` enters the diagonal of `K_eff`
3. If that diagonal entry is too small (< `1e-6` × typical K entry),
   MUMPS reports `INFO(1)=-10` (singular) at that row
4. Without a `/BCS` to anchor the DOF instead, the run aborts

Empirically, `addmass = 1 Mg` (1 tonne) on the test model is enough to
let MUMPS factorize without artificial constraints.

### Matching contact `Gapmin` to the mesh clearance (`--auto-gapmin`)

For a solid `/SURF/PART/EXT` contact the converter writes `Igap=0` (constant
gap), so the engagement gap **is** `Gapmin`. `Gapmin` must sit just *below* the
real clearance between the two contacting parts:

- `Gapmin` **>** clearance → secondary nodes start already penetrated
  (starter `WARNING 343 INITIAL PENETRATIONS`). Under a pull the releasing-side
  nodes flip-flop in and out of the penalty gap, the force residual sticks, and
  the implicit solve never converges — a **contact limit cycle**.
- `Gapmin` **≪** clearance → contact never engages under load → no load path.

Because the clearance is mesh-specific, a `Gapmin` hand-tuned for one mesh fails
when the model is re-meshed. (The elevator-linkage deck converges on a TET4 mesh
with `Gapmin` `0.03 / 0.03 / 0.14` per interface, then stalls in a limit cycle
when the same uniform value is re-used on a finer TET10 mesh whose measured pin
clearances are `0.12` and `0.16`.)

`--auto-gapmin` removes the guesswork: it sets each surface-to-surface
interface's `Gapmin` to `--gapmin-factor` × the minimum node-to-node distance
between its two parts (default factor `0.8`). Inspect first with
`--suggest-gapmin` (read-only — prints the clearances and exits); an explicit
`--inter-gapmin ID=VAL` always wins over the suggestion. Self-contacts and
single-surface contacts have no two-part clearance and are reported as skipped.

```bash
python k2rad.py model.k --suggest-gapmin                  # report clearances
python k2rad.py model.k --auto-gapmin                     # apply (factor 0.8)
python k2rad.py model.k --auto-gapmin --gapmin-factor 0.6 # more conservative
```

Lower the factor if an interface still reports initial penetration (node-to-node
distance over-estimates the true node-to-segment clearance); raise it toward
`1.0` if a contact fails to engage.

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
