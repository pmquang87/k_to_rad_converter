# Roadmap

Deferred future work for k2rad, organised by theme. Each item carries a short
rationale. Nothing here is committed — it is a planning artifact that records
where the effort is best spent next and why. For the current supported-keyword
set and the shipped behaviour, see [`README.md`](README.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Architecture refactors

The core pipeline (parse → dispatch → `ConversionState` → writer) is sound; the
following would pay down accumulated structural debt without changing behaviour.

- **Split `writer.py` into a `writer/` package by section.** At ~5.5 k lines it
  is by far the largest module and mixes every card format. Break it into
  `materials`, `mesh`, `contacts`, `rbody`, `loads`, `blast_ale`, and `engine`
  submodules mirroring the `_make_*` groupings already present. *Rationale:*
  faster navigation, smaller review surface per change, and a natural home for
  per-family tests.
- **Make `ConversionState` a dataclass / grouped sub-dataclasses.** It is
  currently a hand-written class with ~90 attributes set in `__init__`. Convert
  it to a dataclass and group related fields into sub-dataclasses (mesh,
  entities, loads, contacts, control, output). *Rationale:* typo-safe field
  access, free `repr`/defaults, and a documented shape for contributors.
- **Move writer-private symbols into a shared topology module.**
  `writer._TET10_MIDEDGE` is already reached into by `__init__.py` and
  `gapmin.py`; promote it (and related connectivity/faceting helpers) into a
  neutral `k2rad/topology.py`. *Rationale:* removes the cross-module reach into
  writer internals and gives the optional `gapmin` path a dependency that does
  not drag in the whole writer.
- **Add a `build_starter` section registry.** The starter is assembled by a long
  fixed sequence of `_make_*` calls. Replace it with a data-driven ordered
  registry of `(name, builder)` entries. *Rationale:* makes the section order
  explicit and testable, and lets a new section be inserted without editing the
  middle of `build_starter`.

## Keyword coverage roadmap

Tiered by frequency × effort. Lower tiers reuse existing infrastructure; higher
tiers are dedicated milestones.

### Tier 1 — high frequency, low effort (reuse existing infra)

- `*DEFINE_TABLE` / `*DEFINE_TABLE_2D` → `/TABLE/1` — the LAW76/`/TABLE/1` path
  already exists; wire the table keyword to it.
- `*DEFINE_CURVE_FUNCTION` → `/FUNCT` — reuses the curve/function emitter.
- `*CONSTRAINED_RIGID_BODIES` → merged `/RBODY` — fold the listed parts into a
  single rigid body using the existing `/RBODY` machinery.
- `*CONSTRAINED_SPOTWELD` / `*CONSTRAINED_GENERALIZED_WELD` → `/INTER/TYPE2`
  `Spotflag` — the tied-interface writer already emits TYPE2 with a spotweld
  flag for the `*CONTACT_TIED_*` weld variants.

*Rationale:* each is a common deck ingredient that maps onto machinery already
shipped, so the marginal cost is small.

### Tier 2 — crash essentials

- `*MAT_SPOTWELD` (100) → LAW59 + spring-beam.
- `*ELEMENT_DISCRETE` + `*MAT_SPRING_*` / `*MAT_DAMPER_*` → `/PROP/TYPE4`.
- Foams: `MAT_63` → LAW50, `MAT_57` → LAW38, `MAT_83` → LAW70,
  `MAT_26` → LAW28/50.
- `*CONTACT_TIEBREAK_*` → TYPE2-with-rupture.
- `*INITIAL_STRESS_SHELL` / `*INITIAL_STRESS_SOLID` → `/INISHE` / `/INIBRI`.

*Rationale:* these are the recurring building blocks of automotive crash decks;
covering them unlocks a large class of real models.

### Tier 3 — large subsystems (dedicated milestones)

- Composites: `MAT_54` / `MAT_55` + multi-ply `/PROP/TYPE10` / `TYPE11` /
  `TYPE17`.
- `*CONSTRAINED_JOINT_*` (revolute/spherical/… joints).
- `*AIRBAG_*` → `/MONVOL`.
- `*DATABASE_CROSS_SECTION` → `/SECT` + `/TH/SECTIO`.
- Seatbelts.

*Rationale:* each is a self-contained subsystem with its own card family and
validation needs — sized as a milestone rather than an incremental add.

### Tier 4 — analysis-type extensions (ride the validated modal K-export chain)

The modal stiffness-export chain (`/IMPL/PRINT/STIF` → offline solve) is a
validated foundation for further linear analyses:

- **Linear buckling** (`Kφ = λ K_g φ`) — add offline geometric-stiffness
  assembly on top of the exported K. *Highest-leverage new analysis:* it reuses
  the whole export/solve chain and delivers a capability the open-source engine
  otherwise lacks.
- **Harmonic / FRF output** — the modal FRFs `H_j(f)` are already computed in
  `modal_random_response.py`; expose them as a direct frequency-response output.
- **Thermal.**

*Rationale:* these extend the proven modal machinery rather than opening a new
solver path, so risk is contained.

## Lossy conversions to tighten

Cases that convert today but drop or approximate detail worth recovering:

- **Simplified Johnson-Cook rate term** — the `(1 + C·ln ε̇*)` term is dropped;
  needs a `/TABLE`-based rate representation.
- **`*MAT_PLASTIC_KINEMATIC` Cowper-Symonds rate params** — parsed
  (`src`/`srp`) but not emitted; wire them through to the LAW44 rate fields.
- **`*RIGIDWALL_MOVING` / `_FINITE`** — currently skipped with a warning.
- **CNRB per-node DOF releases** — nodal rigid bodies are tied in all DOFs; the
  per-node release codes are not honoured.
- **EOS `V0` / `C6`** — `V0 ≠ 1` is warned and the polynomial `C6` term is
  ignored (Radioss has no C6).
- **`*MAT_ADD_EROSION` non-strain criteria** — only `MXEPS`/`EFFEPS` map; other
  criteria and `IDAM≥1` are reported but not converted.

## Testing / CI / DX

Open developer-experience items. Marked with whether they are in progress now or
deferred.

- **Golden-file end-to-end regression fixtures** *(deferred, blocked)* — a
  parametrised suite that converts a fixed `.k` and diffs the `.rad` against a
  checked-in golden. Blocked by `.gitignore` excluding `*.k`/`*.rad`; needs an
  un-ignored `tests/fixtures/` subtree.
- **Coverage gate** *(deferred)* — enforce a minimum coverage threshold in CI.
- **mypy** *(deferred)* — add static type checking (helped by the
  `ConversionState`-dataclass refactor above).
- **Windows CI leg** *(deferred)* — the primary validation target is Windows +
  Intel MPI; add a Windows job to the matrix.
- **PyPI publish + releases** *(deferred)* — package and publish tagged
  releases.
- **Docker bash launchers + hardening** *(deferred)* — add `or.sh` /
  `build-and-export.sh` bash equivalents of the PowerShell launchers, de-brittle
  the date-pinned image tag, and pin the scipy version in the image.
