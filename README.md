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
`*ELEMENT_DISCRETE` + `*SECTION_DISCRETE` + `*MAT_SPRING_ELASTIC` /
`*MAT_SPRING_NONLINEAR_ELASTIC` / `*MAT_DAMPER_VISCOUS` → `/PROP/TYPE4`
(SPRING) `/SPRING` connectors (grounded `N2=0` springs get a fixed ground node
+ `/BCS`). An element oriented by a `*DEFINE_SD_ORIENTATION` (`VID`) becomes an
oriented `/PROP/TYPE8` (SPR_GENE) whose local DOF 1 acts along that orientation's
`/SKEW` axis (only TYPE8 carries a `skew_ID`); a `DRO=1` torsional section and an
unresolvable `VID` (`IOP=1/3`, which dyna2rad lacks too) stay warned + skipped

### Materials
`*MAT_ELASTIC` → `/MAT/LAW1`
`*MAT_PIECEWISE_LINEAR_PLASTICITY` (+ `_MODIFIED_`) → `/MAT/LAW36`
`*MAT_PLASTIC_KINEMATIC` → `/MAT/LAW44` (`b` = plastic hardening modulus
E·ETAN/(E−ETAN); `Chard` = 1−BETA — the iso/kinematic conventions run in
opposite directions)
`*MAT_ANISOTROPIC_VISCOPLASTIC` (103) → `/MAT/LAW128` (HILL_VISC_PLAST) — the
near 1:1 Radioss counterpart. The Voce (`QR/CR`) + kinematic (`QX/CX`)
hardening and the Hill surface (shell Lankford `R00/R45/R90` or brick
`F/G/H/L/M/N`) carry over verbatim; the iso/kin split becomes `CHARD` (`1−ALPHA`
for the `FLAG=1` fit, else the kinematic fraction `QX/(QR+QX)`); and MAT_103's
*additive* viscous overstress `VK·ε̇^VM` is matched to LAW128's *multiplicative*
Cowper-Symonds factor at the initial yield (`CP=1/VM`, `EPSP0=(SIGY/VK)^(1/VM)`)
— a rate-dependent `LCSS` table is used directly instead. Every Radioss Hill law
is **orthotropic-only**, so each converted part is repointed from the isotropic
`/PROP/SHELL|SOLID` onto a synthesized `/PROP/TYPE9` (shell) or `/PROP/TYPE6`
(solid). The orthotropy reference direction is **auto-mapped from MAT_103's
`AOPT`** when it is a global vector — `AOPT=2` (the global a-vector) → `Vx/Vy/Vz`,
`AOPT=3` (vector v + `BETA`) → `Vx/Vy/Vz` + `Phi` — which covers a straight
build/fibre axis (e.g. the SLS print direction). The element-local (`AOPT=0`),
point-radial (`AOPT=1`) and cylindrical (`AOPT=4`) systems have no single global
vector and fall back to global-X with a warning (set `Vx/Vy/Vz`+`Phi` on the
`/PROP` manually). LAW128 is a 2026-format law: the deck stays at `/BEGIN 2022` and
LAW128 reads correctly but draws one cosmetic starter `WARNING 100211`
("unsupported option in format < 2026"). (A prior isotropic reduction to
`/MAT/LAW36` — dropping the Hill anisotropy — is available if LAW128 proves
unsuitable for a given model.)
`*MAT_POWER_LAW_PLASTICITY` → `/MAT/LAW36` (auto-generated curve)
`*MAT_SIMPLIFIED_JOHNSON_COOK` → `/MAT/LAW36` (σ = A + B·εpⁿ sampled into an
auto-generated yield table, capped at `SIGMAX`; a nonzero `C` converts the
`(1 + C·ln ε̇*)` rate term as a sampled multi-rate curve family on LAW36's
`N_funct`/`Eps_dot_i` block instead of being dropped)
`*MAT_024` with `LCSS` pointing at a `*DEFINE_TABLE` expands into the same
LAW36 rate-curve family (one function per table strain rate)
`*MAT_SPOTWELD` (100) on beam weld parts → `/PROP/TYPE13` (SPR_BEAM) `/SPRING`
connectors — stiffnesses from the beam section, `NRR/NRS/NRT/MRR/MSS/MTT` →
the TYPE13 force/moment failure criteria, `SIGY/EH` → a bilinear axial
force-displacement function. (Deliberately not `/MAT/LAW59`, which binds to
`/PROP/TYPE43` connection *solids*, not springs.) Validate on a single-weld
pull / lap-shear coupon; non-beam MAT_100 parts fall back to elastic with a
loud warning
`*MAT_187` / `*MAT_SAMP-1` → `/MAT/LAW76` (SAMP-1 polymer; the tension/
compression/shear yield curves become `/TABLE/1` cards)
Material failure strain (MAT_003 `FS` / MAT_024 `FAIL` / MAT_018 `EPSF`) →
`/FAIL/JOHNSON` `D1` with `Ifail_sh=2` (delete only when ALL through-thickness
points fail, LS-DYNA's built-in erosion rule) instead of the material `Eps_max`
(first-point deletion, which over-eroded 5x on the W13 blast validation pair)
`*MAT_ADD_DAMAGE_GISSMO` → `/FAIL/TAB2` (GISSMO tabulated damage: `LCSDG`→
`EPSF_ID`, `DMGEXP`→`N`, `DCRIT`, `NUMFIP`→`FAILIP`, `LCREGD`→`TAB_EL`; a
negative `ECRIT`/`FADEXP` is resolved to the instability/fading curve)
`*MAT_ADD_EROSION` → `/FAIL/GENE1`, the card that carries the whole card-1/
card-2 scalar-criteria set: `MXPRES`→`Pmax`, `MNPRES`→`Pmin`, `SIGP1`→
`SigP1_max`, `SIGVM`→`Sig_max` (or `fct_IDsm` for the `<0` load-curve form),
`MXEPS`→`Eps_max` (or `fct_IDps`), `MNEPS`→`Eps_min`, `EFFEPS`→`Eps_eff`,
`VOLEPS`→`Eps_vol`, `EPSSH`→`Eps_s`, `SIGTH`→`Sigr`, `IMPULSE`→`K`, `FAILTM`→
`Time_max`, `NCS`→`NCS`, `NUMFIP`→`Pthickfail`. Signs follow the GENE1 reader
(it forces `Pmin=-|·|`, `Pmax=+|·|`, `Eps_min=-|·|`) and `0` = inactive on both
sides; a non-zero `EXCL` is applied (fields equal to it are made inactive) and
warned. `NUMFIP` maps to the engine's negative-`Pthickfail` broken-IP-ratio form
(`-|NUMFIP|/100` for the percent form, `-NUMFIP/NPTT` for a count using the
`*SECTION_SHELL` `NIP`, `-1e-6` = first-IP for the default). `IDAM≥1` (GISSMO/
DIEM embedded in the erosion card) still warns — the scalar criteria convert
regardless; for the damage model use `*MAT_ADD_DAMAGE_GISSMO`
`*MAT_123` / `*MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY` → the MAT_024 base
plasticity (`/MAT/LAW36`, `FAIL`→`/FAIL/JOHNSON`) **plus** its three extra
failure inputs: `EPSTHIN`→`/FAIL/TAB1` `P_THICKFAIL` (`Ifail_sh=2`; the
mandatory strain table is an inert `10.0` plateau so `FAIL` is not double-
counted — but because `FAIL` rides on `/FAIL/JOHNSON`, no IP fails via TAB1 and
`P_THICKFAIL` never fires, so EPSTHIN thinning erosion is a carrier only, not
reproduced, matching `dyna2rad`), `EPSMAJ`→`/FAIL/FLD` (a flat forming-limit
curve at `|EPSMAJ|`), and `NUMINT` (failed-integration-point count) approximated
by the `Ifail_sh=2` all-points rule on whichever `/FAIL` card(s) the material
emits, with a warning
`*MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION`(`_2D`) → the MAT_024 path
with `/MAT/LAW36` `F_smooth=2` (logarithmic rather than linear interpolation
between the strain-rate yield curves)
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
`*SET_NODE_LIST` (+ `*SET_NODE`), `*SET_PART_LIST` (+ `*SET_PART`),
`*SET_SHELL`/`_SOLID`/`_BEAM` element sets (feed the `/SECT` element groups)
`*DEFINE_CURVE`, `*DEFINE_COORDINATE_SYSTEM`, `*DEFINE_COORDINATE_NODES`
`*DEFINE_COORDINATE_VECTOR` → `/SKEW/FIX` (local Z = X×V, local Y = Z×X; id = the
LS-DYNA CID; an R16 co-rotation `NID` is warned + dropped, matching dyna2rad)
`*DEFINE_VECTOR` → `/SKEW/FIX`, `*DEFINE_VECTOR_NODES` → `/SKEW/MOV` — a skew
whose local X′ follows the tail→head direction (the `_NODES` moving form gets a
synthesized third node; the vector `VID` maps to a converted `/SKEW` id that
dodges every coordinate-system id, since `/SKEW`+`/FRAME` share one starter
namespace)
`*DEFINE_SD_ORIENTATION` → the orientation `/SKEW` of an oriented
`*ELEMENT_DISCRETE` (`IOP=0` → `/SKEW/FIX` aligned with the vector, `IOP=2` →
`/SKEW/MOV` from the node pair; `IOP=1/3` unhandled — as in dyna2rad)
`*DEFINE_BOX` / `*DEFINE_BOX_LOCAL` → **numeric node-membership scoping** (no
`/BOX` entity is emitted): every box consumer intersects its node group with the
box's contained nodes at conversion time (a `_LOCAL` box tests each node in the
box's own frame). Consumed by `*INITIAL_VELOCITY` `BOXID` and `*RIGIDWALL_*`
`BOXID` (box-only scopes the tracked `/GRNOD`; a box that encloses no node = no
slave nodes = inactive wall, so it is skipped rather than tracking ALL nodes;
`NSID`+`BOXID` drops the box and `NSID` wins, matching dyna2rad). Contact
`SBOXID`/`MBOXID` — including on `*CONTACT_FORCE_TRANSDUCER_PENALTY`, the one
contact dyna2rad maps them for — do **not** map cleanly onto a contact surface
here, so they are dropped with a loud warning; the
`_ADAPTIVE`/`_COARSEN`/`_DRAWBEAD`/`_SPH` box variants are skipped
`*DEFINE_TABLE_2D` → `/TABLE/1` (Ndim=2, rows sorted by the rate/parameter
value); legacy `*DEFINE_TABLE` resolves explicit-LCID rows directly and
bare-VALUE rows positionally (value *i* pairs with the *i*-th `*DEFINE_CURVE`
parsed after the table — LS-DYNA's "curves follow" rule; unpairable tables
warn + skip)
`*DEFINE_CURVE_FUNCTION` → `/FUNCT` (a pure single-variable `x`/`time` analytic
expression is sampled into an X-Y function over `[0, termination]`; expressions
that reference parameters, other curves, or runtime state are warned + skipped)
`*PARAMETER` (fixed and free format, `R`/`I` types) — `&name` references are
resolved wherever a field is parsed; `*PARAMETER_EXPRESSION` is not evaluated
(warned). LS-DYNA **comma-delimited free format** is accepted on every card.

### Assembly / includes
`*INCLUDE` and `*INCLUDE_PATH[_RELATIVE]` — included files are parsed and
merged inline.
`*INCLUDE_TRANSFORM` → applied **numerically at parse time** (k2rad inlines
includes, so no `//SUBMODEL` is emitted): the id offsets
(`IDNOFF`/`IDEOFF`/`IDPOFF`/`IDMOFF`/`IDSOFF`/`IDFOFF`/`IDDOFF`/`IDROFF`)
are added to every id the included file defines **and** references (per-keyword
field map covering the supported keyword families; an included keyword outside
the map warns loudly), and the `TRANID` `*DEFINE_TRANSFORMATION` moves the
included `*NODE` coordinates **and `*RIGIDWALL_PLANAR*` wall geometry** (base +
head points, `_FINITE` edge head — the starter's `SUBROTPOINT` submodel replay).
TRANID binds against **post-offset** definition ids (dyna2rad's
offset-then-resolve order; a nested include card's TRANID shifts with the
enclosing files' cumulative `IDDOFF`). Nested `*INCLUDE_TRANSFORM`s accumulate
offsets additively and compose transforms innermost-first (the dyna2rad
`//SUBMODEL` / starter `LECSUBMOD` semantics). `FCTMAS`/`FCTTIM`/`FCTLEN`/
`FCTTEM` unit factors are **not** applied (use kunit to convert the include
first — warned), and literal geometry inside other keywords of a transformed
include (coordinate-system origins, boxes; direction vectors under rotation;
literal rotation-axis points under any transform) is warned per keyword.
`*DEFINE_TRANSFORMATION` → composed row-by-row (top-to-bottom, each row acting
on the previous result, matching `/TRANSFORM` starter math): `TRANSL`,
`ROTATE` (direction form and two-`POINT` form, degrees, right-hand rule),
`SCALE` (0 → 1), `MIRROR` (A7 coordinate-system mirroring warned),
`POINT`+`POS6P`, `POS6N`, `TRANSL2ND`, `ROTATE3NA` (pivot node honoured),
`MATRIX` (R16 cards 3-4). Unknown verbs warn loudly and are skipped.
`*NODE_TRANSFORM` → the `TRSID` transform applied to the `NSID`
`*SET_NODE_LIST` nodes after all include transforms (LS-DYNA `IMMED=0`
semantics; `IMMED=1` is treated as deferred with a warning).

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
`*CONSTRAINED_SPOTWELD` / `*CONSTRAINED_GENERALIZED_WELD_SPOT` — without
failure forces the node pair becomes a 2-node nodal rigid body (the validated
CNRB machinery); with `SN`/`SS` failure it becomes a stiff `/PROP/TYPE13`
`/SPRING` connector carrying the failure forces (`TF`/`EP` and non-quadratic
exponents are warned)

### Boundary conditions / motion
`*BOUNDARY_SPC` (+ `_NODE`/`_SET`) → `/BCS`
`*BOUNDARY_PRESCRIBED_MOTION_RIGID` → `/IMPDISP`, `/IMPVEL`, `/IMPACC`
`*BOUNDARY_PRESCRIBED_MOTION_SET` / `_NODE` → `/IMPDISP` (or `/BCS` when
`sf=0`, a common LS-DYNA idiom for symmetry/fixed-DOF)
`*RIGIDWALL_PLANAR` (+`_ID`, `_FORCES`) → `/RWALL/PLANE` (fixed infinite plane;
`FRIC` 0 → sliding, 0<f<1 → Coulomb friction, ≥1 → tied; `NSID=0` tracks all
nodes via a bounding-box search distance; `*DATABASE_RWFORC` → `/TH/RWALL`)
`*RIGIDWALL_PLANAR_MOVING` (+`_FORCES`) → moving `/RWALL/PLANE`: a synthesized
free carrier node holds the wall `MASS` and `V0` along the wall normal —
exactly the starter reader's moving-wall semantics, no extra cards needed
`*RIGIDWALL_PLANAR_FINITE` (+`_MOVING`) → `/RWALL/PARAL` with the corner
points computed from `XHEV`/`LENL`/`LENM` (a zero length means semi-infinite
in LS-DYNA and falls back to the infinite plane with a warning);
`_ORTHO` (orthotropic friction) still warn-skips — no `/RWALL` equivalent

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
`*INITIAL_VELOCITY` (base set form) → `/INIVEL/TRA` (+ `/INIVEL/ROT` for
rotational DOFs); `NSID`/`NSIDEX` node-set scoping (whole model when `NSID` is
omitted or 0), `NSIDEX` removed by set difference, `BOXID` intersected against
the `*DEFINE_BOX` contained nodes (numeric membership at conversion time), `ICID`
mapped to the matching `/SKEW` from a converted `*DEFINE_COORDINATE_*` (else
global) — a rigid-overwrite `IRIGID` and the Card-3 per-exempt-node velocities
are warned + dropped
`*INITIAL_VELOCITY_GENERATION` → `/INIVEL/AXIS` + a generated `/FRAME/FIX`
(rotation axis through `(XC,YC,ZC)` along `(NX,NY,NZ)`, or node-defined when
`NX=-999`); `OMEGA`→`VR` about the axis and translational `VX/VY/VZ` projected
into the frame; a nonzero `ICID` rotates `VX/VY/VZ` and the vector axis from that
local system to global (else warned + global); `STYP` all/part-set/part/node-set
scoping (`*ELEMENT_DISCRETE` springs included in the part scan; `PHASE`, `IVATN`,
`IRIGID` warned + dropped; `_GENERATION_START_TIME` skipped)
`*INITIAL_STRESS_SHELL` → `/INISHE/STRS_F/GLOB` (ILOC=0, LS-DYNA's global
default — lossless incl. σzz, plastic strain and the through-thickness
position) or the local `/INISHE/STRS_F` for ILOC=1 (σzz/T warned + dropped).
The layer count must match the part's `/PROP/SHELL` integration points or the
element is warned + skipped (the starter enforces it); `NPLANE>1` in-plane
points are averaged per layer with a warning
`*INITIAL_STRESS_SOLID` → `/INIBRI/STRS_FGLO` (NINT 1→8 replicates exactly;
other counts average with a warning)

### Contact
`*CONTACT_AUTOMATIC_SINGLE_SURFACE` (+ `_MORTAR`) → `/INTER/TYPE25` self-contact
(explicit) or `/INTER/TYPE7` node→surface (implicit)
`*CONTACT_AUTOMATIC_GENERAL` → routed by the optional-Card-A `SOFT` field, matching
dyna2rad's sentinel convention: `SOFT=-7` → `/INTER/TYPE7`, `SOFT=-11` →
`/INTER/TYPE11` **edge-to-edge (line) contact**, `SOFT=-19` → `/INTER/TYPE19`
(surface+edge); any ordinary `SOFT` (0/1/2/blank) falls back to the single-surface
routing above. For `SOFT=-11` k2rad **synthesizes the `/LINE` group(s)** the
interface needs — a `/LINE/SEG` (2-node edges) from a `*SET_SEGMENT`'s segment
edges, otherwise a `/LINE/SURF` over the part surface so the starter derives the
edges — and references them from the interface (`line_IDm=0` = self edge-impact).
`SOFT=-19` hands two `/SURF` to the starter, which auto-generates the child
TYPE7+TYPE11 (no hand-built `/LINE`). (`--inter-gapmin`/`--auto-gapmin` do not
reach these SOFT-routed interfaces; their engagement gap is the Card-3 `SST`/`MST`.)
`*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` (+ `_ONE_WAY_*`) → `/INTER/TYPE7`
`*CONTACT_..._TIEBREAK` (`SURFACE_TO_SURFACE_TIEBREAK`, `_ONE_WAY_...`,
`TIEBREAK_{SURFACE,NODES}_TO_SURFACE`) → `/INTER/TYPE7` for the post-failure
contact, **with a warning that the cohesive pre-bond (NFLS/SFLS stress failure)
has no open-source OpenRadioss equivalent and is dropped** — the parts contact
but do not pre-bond
`*CONTACT_TIED_{NODES,SHELL_EDGE,SURFACE}_TO_SURFACE` (+ `_OFFSET` variants) →
`/INTER/TYPE2` (tied **kinematic** interface): slave `*SET_NODE_LIST` (SSTYP=4) →
`/GRNOD`, master `*SET_SEGMENT` (MSTYP=0) → `/SURF/SEG`; parts / part sets on
either side are also resolved. `Spotflag=1` (spotweld formulation) for the
NODES/SHELL_EDGE weld variants, `Spotflag=5` (standard) for SURFACE_TO_SURFACE.
A `*CONTACT_TIED_SURFACE_TO_SURFACE[_OFFSET]` with a **negative offset** —
dyna2rad's discriminator `(SFST*SST + SFMT*MST)/2 < 0` (raw Card-3 scale factors,
no zero→1 defaulting, so a blank `SFST`/`SFMT` always stays TYPE2) — instead
becomes `/INTER/TYPE10` (**penalty** tie: bonds by a spring over `GAP=(|SST|+|MST|)/2`,
so its secondary nodes may coexist with `/RBODY` and rotations are not tied).
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
`*HOURGLASS` + `*PART` HGID / `*CONTROL_HOURGLASS` → **per-part hourglass
control** on the `/PROP` (the `dyna2rad` mapping). For solids the LS-DYNA `IHQ`
selects the Radioss `Isolid` (`1/2/3`→`1`, `4/5`→`5`, `6/7`→`24`) and `QM`/`QH`
becomes the hourglass coefficient `h`; tetra/ALE sections are left untouched, and
`IHQ 0/8/9/10` keep the section's ELFORM `Isolid` (warned — no faithful Radioss
formulation). A `*HOURGLASS` referenced by a part **overrides** the global
`*CONTROL_HOURGLASS`; `HGID=0`, or a dangling id (warned loudly), falls back to
it. Because k2rad `/PROP`s are per-`*SECTION`, a part whose effective hourglass
differs from its section's base is split into its own dedicated `/PROP` (the
shared section prop is kept for the section's other parts and dropped only when
every part on it was split). Shells carry the coefficient into `Hm/Hf/Hr`
(clamped to the Radioss `0.05` limit), but k2rad's ELFORM-selected `Ishell`
`12` (QBAT) / `24` (QEPH) make those coefficients physically inert (warned).
_Note: `*CONTROL_HOURGLASS` was previously parsed and dropped; it is now honored,
so a deck with one may see its solid `Isolid` change off the ELFORM default._
`*CONTROL_ACCURACY`, `*CONTROL_CONTACT`, `*CONTROL_OUTPUT`, `*CONTROL_SHELL`,
`*CONTROL_SOLID`, `*CONTROL_ENERGY`, `*CONTROL_CPU`
`*DATABASE_*` (binary output, time-history channels)
`*DATABASE_CROSS_SECTION_SET[_ID]` → `/SECT` (node set + `*SET_SHELL`/`_SOLID`/
`_BEAM` element groups); `*DATABASE_CROSS_SECTION_PLANE[_ID]` → `/SECT` via a
geometric resolver (elements whose nodes straddle the cutting plane,
part-restricted and radius-filtered; a finite `LENL`/`LENM` parallelogram is
approximated as the infinite plane with a warning); `*DATABASE_SECFORC` →
`/TH/SECTIO` on every section
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
  the buckling factors and `P_cr`. Beam/rod/truss elements are validated
  against the analytic Euler pin-pinned column (`P_cr = π²EI/L²`) to 0.001 %;
  shells are supported at the classical consistent-membrane level (membrane
  resultants → plate-buckling `K_g` on the out-of-plane DOFs), validated
  against the analytic simply supported square plate (`k = 4`) to 2.2 % on an
  8×8 mesh with quadratic convergence. Solid elements are counted and skipped
  with a warning rather than reported with a wrong factor.
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
│   ├── parser.py         # .k file parser (handles *INCLUDE / *INCLUDE_TRANSFORM)
│   ├── assembly.py       # *INCLUDE_TRANSFORM id offsets + *DEFINE_TRANSFORMATION /
│   │                     #   *NODE_TRANSFORM applied numerically at parse time
│   ├── transform.py      # Pure affine math for the transform rows
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
  file). `*INCLUDE_TRANSFORM` applies its id offsets and TRANID transform
  numerically at parse time; unit factors (`FCTMAS`/`FCTTIM`/`FCTLEN`/
  `FCTTEM`) are **not** applied (convert the include with kunit first —
  warned loudly), and the TRANID transform moves `*NODE` coordinates and
  `*RIGIDWALL_PLANAR*` wall geometry only (literal geometry inside other
  keywords of the include — coordinate-system origins, box extents,
  velocity vectors under rotation, literal rotation-axis points under any
  transform — is warned per keyword).

---

## License

MIT
