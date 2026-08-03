# Roadmap

Future work for k2rad, organised by theme. Each item carries a short rationale.
This is a planning artifact that records where the effort is best spent next and
why. For the current supported-keyword set and the shipped behaviour, see
[`README.md`](README.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Recently completed

A coverage pass shipped a first tranche of this roadmap (see `CHANGELOG.md`):

- **Architecture:** `k2rad/topology.py` extraction; the `build_starter`
  data-driven section registry; the `ConversionState` dataclass; the
  `k2rad/writer/` package split (byte-identical output).
- **Tier 1:** `*CONSTRAINED_RIGID_BODIES` → merged `/RBODY`;
  `*DEFINE_CURVE_FUNCTION` → sampled `/FUNCT`.
- **Tier 2:** foams/honeycomb `*MAT_CRUSHABLE_FOAM`/`LOW_DENSITY_FOAM`/
  `FU_CHANG_FOAM`/`HONEYCOMB` → `/MAT/LAW50`/`LAW38`/`LAW70`/`LAW28`;
  `*CONTACT_..._TIEBREAK` → `/INTER/TYPE7` (contact-only, cohesive bond warned).
- **Tier 4:** linear buckling (`tools/modal_buckling.py`, Euler-validated) and
  harmonic/FRF (`tools/modal_frf.py`, SDOF-validated).
- **Lossy:** `*EOS_LINEAR_POLYNOMIAL` `C6` now warned. (`*MAT_PLASTIC_KINEMATIC`
  Cowper-Symonds `SRC/SRP` was already emitted correctly to LAW44.)
- **Testing/CI/DX:** golden-file fixtures, coverage gate, advisory mypy, Windows
  CI leg, PyPI publish workflow, Docker bash launchers.

The remaining items below are still open.

## Architecture refactors

The core pipeline (parse → dispatch → `ConversionState` → writer) is sound.
All four originally-listed refactors are now **done** (kept below for the
rationale record): the `writer/` package split, the `ConversionState`
dataclass, the shared `topology` module, and the `build_starter` section
registry. Remaining architecture ideas: grouping the state's ~100 fields into
sub-dataclasses (mesh/loads/contacts/control) and burning down the ~38
advisory mypy findings so the CI job can become blocking.

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
- **Move writer-private symbols into a shared topology module.** *(done)*
  `topology.TET10_MIDEDGE` (the Radioss `/TETRA10` mid-edge map) plus the
  midside-ordering detection/permutation helpers (`TET10_DYNA_TO_RADIOSS`,
  `TET10_MIDEDGE_DYNA`, `classify_tet10_apex_order`) now live in the neutral
  `k2rad/topology.py`; the writer and `gapmin.py` import from there instead of
  reaching into `writer._TET10_MIDEDGE`. *Rationale:* removes the cross-module
  reach into writer internals and gives the optional `gapmin` path a dependency
  that does not drag in the whole writer.
- **Add a `build_starter` section registry.** The starter is assembled by a long
  fixed sequence of `_make_*` calls. Replace it with a data-driven ordered
  registry of `(name, builder)` entries. *Rationale:* makes the section order
  explicit and testable, and lets a new section be inserted without editing the
  middle of `build_starter`.

## Keyword coverage roadmap

Tiered by frequency × effort. Lower tiers reuse existing infrastructure; higher
tiers are dedicated milestones.

### Tier 1 — high frequency, low effort (reuse existing infra)

- `*DEFINE_TABLE` / `*DEFINE_TABLE_2D` → `/TABLE/1` — **done** (Ndim=2 per
  table_1.cfg; legacy tables resolve positionally; MAT_024 LCSS-tables expand
  into the LAW36 rate family). Original note: — the 1-D
  `/TABLE/1` path already exists; the 2-D function-reference layout
  (`Ndim=2`, `fct_ID`/`A` rows) needs its exact column widths pinned against the
  `CURVE/table_1.cfg` before it can be emitted with confidence.
- `*DEFINE_CURVE_FUNCTION` → `/FUNCT` — **done** (sampled).
- `*CONSTRAINED_RIGID_BODIES` → merged `/RBODY` — **done**.
- `*CONSTRAINED_SPOTWELD` / `*CONSTRAINED_GENERALIZED_WELD_SPOT` — **done**
  (no-failure -> 2-node CNRB; with failure -> /PROP/TYPE13 connector). Original
  note: — needs a `/SURF` synthesized from the weld node's
  parent shells; for a *failing* weld the spring-connector path (below) is the
  faithful target.

*Rationale:* each is a common deck ingredient that maps onto machinery already
shipped, so the marginal cost is small.

### Tier 2 — crash essentials

- `*MAT_SPOTWELD` (100) — **done** as /PROP/TYPE13 (SPR_BEAM) connectors; the
  cfg shows LAW59 binds to /PROP/TYPE43 connection solids, so the spring route
  is correct. Validate on a single-weld coupon. Original note: — needs new
  `/MAT/LAW59` + `/PROP/TYPE13` machinery and single-weld pull/shear validation.
- `*ELEMENT_DISCRETE` + `*MAT_SPRING_*` / `*MAT_DAMPER_*` -> /PROP/TYPE4 —
  **done** (S01/S04/D01; grounded springs; oriented/torsional warn+skip).
  Original note: — reuses the grounding-spring `/SPRING` template, but the
  `/PROP/TYPE4` card layout and the orientation/torsional (`VID`, `DRO=1`) cases
  need pinning before shipping.
- Foams: `MAT_63` → LAW50, `MAT_57` → LAW38, `MAT_83` → LAW70,
  `MAT_26` → LAW28 — **done**.
- Johnson-Cook metals (P1): `*MAT_JOHNSON_COOK` (15) → `/MAT/LAW2`
  (PLAS_JOHNS) or, when the part attaches an `*EOS_*`, `/MAT/LAW4`
  (HYD_JCOOK) + `/EOS`; `D1-D5` → `/FAIL/JOHNSON`, `DTF` → `/FAIL/GENE1`
  `dtmin`; `*MAT_099` → `/MAT/LAW2` + flat `/FAIL/FLD` — **done**
  (dyna2rad-faithful law choice and failure priority; see CHANGELOG).
- Hyperelastic rubber batch (P1): `*MAT_BLATZ-KO_RUBBER` (7) → `/MAT/LAW42`
  fixed form; `*MAT_MOONEY-RIVLIN_RUBBER` (27) → `/MAT/LAW42` (+ the
  dyna2rad 500-point funIDbulk curve) or `/MAT/LAW69` (LCID); `*MAT_OGDEN_RUBBER`
  (77_O) → `/MAT/LAW42` (embedded Prony) or `/MAT/LAW69`;
  `*MAT_HYPERELASTIC_RUBBER` (77_H) → `/MAT/LAW95` + `/VISC/PRONY` or
  `/MAT/LAW69`; `*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP]` → `/XREF` with the
  starter's law/formulation gates handled (Ismstr=10 on /XREF solid sections)
  — **done** (dyna2rad-faithful constants; starter-validated; see CHANGELOG).
- Metal plasticity batch 2 (P1): `*MAT_PLASTICITY_WITH_DAMAGE` (81/82) → the
  MAT_024 `/MAT/LAW36` path + `/FAIL/TAB1` (EPPFR/EPPF as the failure and
  instability tables, NUMINT as a negative `P_thickfail`);
  `*MAT_PLASTICITY_COMPRESSION_TENSION` (124) → `/MAT/LAW66` (+ `/VISC/PRONY`,
  + `/FAIL/JOHNSON` or `/FAIL/TENSSTRAIN`); `*MAT_STRAIN_RATE_DEPENDENT_-`
  `PLASTICITY` (19) → `/MAT/LAW121` (PLAS_RATE, a 1:1 curve target);
  `*MAT_GURSON` (120, + `_JC`) → `/MAT/LAW52`; and the riders
  `*MAT_012` → `/MAT/PLAS_JOHNS` (G/K → E/ν), `*MAT_105` → `/MAT/LAW36` +
  `/FAIL/LEMAITRE`, `*MAT_122` → `/MAT/LAW43` or `/MAT/LAW32` — **done**
  (starter-validated, 0 ERROR(S); several dyna2rad defects fixed rather than
  reproduced — see CHANGELOG).
- Viscoelastic batch (P1): `*MAT_VISCOELASTIC` (6) → `/MAT/LAW34` (BOLTZMAN,
  an exact 1:1 of `G(t)`); `*MAT_KELVIN-MAXWELL_VISCOELASTIC` (61) →
  `/MAT/LAW40` (KELVINMAX, `G1 = G0−GI`); `*MAT_GENERAL_VISCOELASTIC` (76,
  + `_MOISTURE`) → a `/MAT/LAW42` carrier + `/VISC/PRONY` (`Itab=0` explicit
  four-column rows, `Itab=1` starter-side least-squares fit for the `LCID`/`NT`
  form); `*MAT_SIMPLIFIED_RUBBER/FOAM` (181, + `_WITH_FAILURE` /
  `_LOG_LOG_INTERPOLATION`) and `*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE` (183) →
  `/MAT/LAW88` with the rate family, the specimen normalization baked into the
  curve points and MAT_181's Prony cards as `/VISC/PRONY`; `*MAT_SOFT_TISSUE`
  (91) / `_VISCO` (92) → `/MAT/LAW42` — **done** (starter-validated 0 ERROR(S);
  the LAW34 mapping additionally engine-validated against the analytic
  relaxation curve to 0.007 %; a dozen dyna2rad defects corrected rather than
  reproduced, including the unreachable `LSD_LCIDK` fit branch, the dropped
  `BETAKI` bulk decay constants, the `TENSIOM` typo and the unconditional
  empty `/VISC/PRONY` — see CHANGELOG). Still open in this family: the
  radioss2026 LAW88 extension cards (`SGL/SW/ST/G/SIGF` and the Feng-Hallquist
  `KFAIL/GAM1/GAM2/EH`), which need `/BEGIN 2026` rather than converter work;
  MAT_181's `MU` on the solid property (a per-part `/PROP/SOLID` split);
  a real foam target for the `0 < PR < 0.49` Hill branch; the
  `*MAT_SOFT_TISSUE` fibre term, which no Radioss law offers; and LAW88's
  unloading, which the engine applies as a normalised shape ratio rather than
  as the LCUNLD stress-strain path, so a MAT_183 hysteresis loop is not
  reproduced curve-for-curve (engine-side — no converter fix exists).
  Also still open, and NOT specific to this batch: `/XREF` emission does not
  read the material `REF` flag (dyna2rad parity), so a `REF=0` material with
  reference-geometry coverage gets a block LS-DYNA would not apply. Both
  directions are now warned off one registry
  (`writer/common.py::_ref_flag_materials`); gating the emission would change
  already-validated MAT_027/077 rubber decks and wants its own change.
- Spotweld joining (P1): `*CONTACT_SPOTWELD` (+ `_WITH_TORSION` /
  `_BEAM_OFFSET` / `_CONSTRAINED_OFFSET` / `_PENALTY` / `_MPP`) →
  `/INTER/TYPE2` Spotflag=28 with `Ignore=2` and `Idel2=1`;
  `*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N]` → `/GRBRIC/BRIC` + `/CLUSTER/BRICK`;
  `*DATABASE_SWFORC` → `/TH/SPRING` + `/TH/BRIC` + `/TH/CLUSTER` — **done**
  (starter-validated, 0 ERROR(S); the secondary side is resolved over BEAM nodes
  so the `SSTYP=3` weld part actually resolves, and the `/CLUSTER` exponents are
  quadratic where dyna2rad's are linear — see CHANGELOG). Original note: — the
  W16/W17 sheets are node-disjoint without it, so the weld force is 0.
- `*CONTACT_TIEBREAK_*` → `/INTER/TYPE7` (contact-only) — **done**; a faithful
  cohesive rupture tie remains open (no open-source equivalent found).
- `*CONTACT_AUTOMATIC_GENERAL` `SOFT`-sentinel routing (`-7`→TYPE7, `-11`→TYPE11
  edge-to-edge with synthesized `/LINE/SEG`|`/LINE/SURF`, `-19`→TYPE19; default →
  single-surface) — **done** (dyna2rad `convertcontacts.cxx` cc:133-164).
- `*CONTACT_TIED_SURFACE_TO_SURFACE[_OFFSET]` negative-offset discriminator
  `(SFST*SST + SFMT*MST)/2 < 0` → `/INTER/TYPE10` penalty tie (else TYPE2) —
  **done** (dyna2rad cc:220).
- `*INITIAL_STRESS_SHELL` / `*INITIAL_STRESS_SOLID` -> /INISHE / /INIBRI —
  **done** (GLOB/local flavours, layer-count checks per the starter readers).
  Original note: — the per-integration-point `/INISTATE` blocks are verbose and
  version-specific; the layer-count-must-match-property constraint and stress
  component/frame order need cfg validation.

*Rationale:* these are the recurring building blocks of automotive crash decks;
covering them unlocks a large class of real models.

### Tier 3 — large subsystems (dedicated milestones)

- Composites: `MAT_54`/`MAT_55` → `/MAT/LAW127`, `MAT_002` → `/MAT/LAW93`,
  `MAT_037` → `/MAT/LAW43`, `MAT_032` → a `/MAT/PLAS_BRIT` pair, and the
  multi-ply `*PART_COMPOSITE` layup — **done**. The layup target is
  `/PROP/TYPE51` + one `/PROP/TYPE19` (PLY) per layer, which is what dyna2rad
  emits, rather than the `TYPE10`/`TYPE17` sketched here; single-material
  orthotropic shells go on `/PROP/TYPE11` (SH_SANDW), solids on `/PROP/TYPE6`
  and `MAT_037` on `/PROP/TYPE9`. Includes the full AOPT → `/SKEW/FIX` +
  `Ip`/`Vx-Vy-Vz` axis mapping and the fix for `*PART_COMPOSITE`'s silent
  whole-mesh loss (see CHANGELOG).
  `*SECTION_SHELL ICOMP=1` (the card-3 `B1..B8` per-layer material angles) and
  `*INTEGRATION_SHELL` user integration rules (the per-layer `WF_i` thicknesses
  and `PID_i` materials, which is where `MAT_032`'s layer thicknesses really
  live) are **done** as well — both starter-validated, and they compose on one
  section. `*SECTION_SHELL` also reads every card set under one header now.
  `*INTEGRATION_BEAM` → `/PROP/TYPE18` is **done** too (both branches: the
  `ICST = 0` `S/T/WF` cell cloud becomes explicit `Yi/Zi/AREA` integration
  points, `ICST = 1..22` maps onto Radioss's own predefined shapes at
  `Isect = ICST + 9`, and a section whose material cannot take TYPE18 keeps
  `/PROP/BEAM` with the constants derived from the rule) — net-new capability,
  since dyna2rad neither parses the keyword nor implements the linkage. All four
  `*SECTION_*` keywords now read every card set under one header.
  Still open in this family: `*SECTION_TSHELL ICOMP=1` → `/PROP/TYPE22`,
  the `*INTEGRATION_BEAM` standard shapes needing three or more dimensions
  (`Isect ≥ 10` with `L3..L6` needs `/BEGIN ≥ 2024`, and k2rad writes 2022 —
  either bump the version declaration for the whole deck or expand the shape to
  explicit integration points, which means writing the 19 shape geometries
  k2rad currently defers to the starter), a beam rule's per-cell `PID_i`
  (`/PROP/TYPE18` has a single material column), a rule on a
  `*MAT_ELASTIC` part (Radioss bans LAW1 from every layered shell property and
  from `/PROP/TYPE18`, so this needs the material re-stated rather than
  converter work), `*SECTION_BEAM ELFORM = 3` → `/PROP/TYPE2` (TRUSS) with
  `*ELEMENT_BEAM` routed to `/TRUSS`, the named `SECTION_nn` standard section on
  `*SECTION_BEAM` card 2b (reported, not converted), the per-element
  ply override of `*ELEMENT_SHELL_COMPOSITE` (its mesh is now kept — see the
  element-variant batch below — but the ply cards themselves are not read; no
  converter implements this, dyna2rad included),
  `*MAT_LAMINATED_COMPOSITE_FABRIC` (058) → `/MAT/LAW125`, and the
  ELFORM 101–105 user-defined shell itself — its cards 5/5.1/5.2 are now strided
  over so the sections around them parse, but the user routine's own integration
  points, extra DOFs and `LMC` constants have no Radioss counterpart and are
  dropped with a warning.
- Element variants (P1): `*ELEMENT_SHELL_THICKNESS`/`_BETA`/`_MCID`/`_OFFSET`/
  `_DOF` (+ every combination) → the per-element `/SHELL` // `SH3N` `Phi` and
  `Thick` columns; `*ELEMENT_BEAM_ORIENTATION` → a synthesized third node at
  `pos(N1) + V`; `*ELEMENT_PLOTEL` → an inert `/SPRING` on a dedicated
  `/PART` + `/PROP/TYPE4` — **done** (starter- and engine-validated; see
  CHANGELOG). The real defect this closed was silent MESH LOSS: elements are
  emitted inside the `state.parts` loop, so any unregistered `*ELEMENT_<family>`
  spelling left the `/PART` in the deck with no element block under it and no
  warning. Dispatch now falls back on the family prefix, so this cannot recur
  for an option nobody has implemented yet.
  Still open in this family: `*ELEMENT_SHELL_COMPOSITE[_LONG]` ply data (above),
  `*ELEMENT_BEAM_{THICKNESS,SECTION,SCALAR,PID,WARPAGE}` extra cards (parsed as
  "keep the mesh, warn about the rest"), `*ELEMENT_BEAM_OFFSET` eccentricities
  (would need synthesized rigid links), and `*ELEMENT_SEATBELT*`.
- `*CONSTRAINED_JOINT_*` (revolute/spherical/… joints) → `/PROP/TYPE45`
  (KJOINT2) + `/SPRING` + a node-derived `/SKEW/FIX`, plus
  `*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED`/`_TRANSLATIONAL` DOF blocks —
  **done** (dyna2rad-faithful type integers and axis conventions, with its
  documented field-map defects corrected; see CHANGELOG).
- `*AIRBAG_*` → `/MONVOL`.
- `*DATABASE_CROSS_SECTION` → `/SECT` + `/TH/SECTIO` — **done** (_SET direct;
  _PLANE via a geometric straddle resolver; SECFORC → /TH/SECTIO).
- Seatbelts.

*Rationale:* each is a self-contained subsystem with its own card family and
validation needs — sized as a milestone rather than an incremental add.

### Tier 4 — analysis-type extensions (ride the validated modal K-export chain)

The modal stiffness-export chain (`/IMPL/PRINT/STIF` → offline solve) is a
validated foundation for further linear analyses:

- **Linear buckling** (`Kφ = λ K_g φ`) — **done** for beam/rod/truss elements
  (`tools/modal_buckling.py`, Euler-validated to 0.001 %). Shells are now also
  **done** (consistent-membrane K_g, SSSS-plate-validated to 2.2 % at 8x8);
  a rigorous solid-element K_g remains open.
- **Harmonic / FRF output** — **done** (`tools/modal_frf.py`).
- **Thermal** *(remaining)* — a separate Radioss `/HEAT` / `/THERM_STRESS`
  solver path; larger, lower priority unless coupled thermo-mechanical decks are
  in scope.

*Rationale:* these extend the proven modal machinery rather than opening a new
solver path, so risk is contained.

## Lossy conversions to tighten

Cases that convert today but drop or approximate detail worth recovering:

- **Simplified Johnson-Cook rate term** — **done**: converts as a sampled
  LAW36 multi-rate curve family (see CHANGELOG).
- **`*MAT_PLASTIC_KINEMATIC` Cowper-Symonds rate params** — already emitted
  correctly (`SRC`→`c`, `SRP`→`p` on the LAW44 rate card); listed here only for
  the record.
- **`*RIGIDWALL_MOVING` / `_FINITE`** — **done** (moving /RWALL/PLANE with a
  synthesized carrier node; /RWALL/PARAL from XHEV/LENL/LENM). _ORTHO remains
  warn-skipped (no /RWALL equivalent).
- **CNRB per-node DOF releases** *(remaining)* — nodal rigid bodies are tied in
  all DOFs; the per-node `DRFLAG`/`RRFLAG` release codes are not honoured
  (Radioss `/RBODY` has no direct partial-release construct).
- **EOS `V0` / `C6`** — `C6` is now **warned**; `V0 ≠ 1` remains warned (Radioss
  references the initial state through density / `/INIBRI`, not a `V0` scalar).
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
