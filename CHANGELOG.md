# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Prior history (before this changelog was introduced) is summarized in the
`git log` — each keyword conversion and bug fix landed as its own commit / PR.

## [Unreleased]

### Added

- **Connectors**
  - `*ELEMENT_DISCRETE` + `*SECTION_DISCRETE` + `*MAT_SPRING_ELASTIC` /
    `*MAT_SPRING_NONLINEAR_ELASTIC` / `*MAT_DAMPER_VISCOUS` → `/PROP/TYPE4`
    `/SPRING` connectors (grounded springs get a fixed ground node + `/BCS`;
    oriented/torsional elements warn + skip).
  - `*MAT_SPOTWELD` (100) beam welds → `/PROP/TYPE13` (SPR_BEAM) connectors
    with the full force/moment failure envelope (not `/MAT/LAW59`, which the
    cfg shows binds to `/PROP/TYPE43` connection solids).
  - `*CONSTRAINED_SPOTWELD` / `*CONSTRAINED_GENERALIZED_WELD_SPOT` → 2-node
    CNRB (no failure) or a TYPE13 connector carrying `SN`/`SS` (with failure).
- **Geometry utility cards**
  - `*DEFINE_COORDINATE_VECTOR` → `/SKEW/FIX` (was `handle_skip`): local
    Z = X×V, local Y = Z×X, id = the LS-DYNA CID; an R16 co-rotation `NID` is
    warned + dropped (dyna2rad treats the card as fixed).
  - `*DEFINE_VECTOR` → `/SKEW/FIX`, `*DEFINE_VECTOR_NODES` → `/SKEW/MOV` — a
    skew whose local X′ follows the tail→head direction (the `_NODES` moving
    form synthesizes the third node it needs). The vector `VID` is mapped to a
    converted `/SKEW` id that dodges every coordinate-system id (a build-starter
    prepass reserves them, since `/SKEW`+`/FRAME` share one starter namespace —
    `all_skew_ids()` now also guards the `*INITIAL_VELOCITY_GENERATION` `/FRAME`
    ids and the LAW128 orthotropy skews).
  - `*DEFINE_SD_ORIENTATION` → the orientation `/SKEW` of an oriented
    `*ELEMENT_DISCRETE` (`IOP=0` → `/SKEW/FIX` aligned with the vector, `IOP=2`
    → `/SKEW/MOV` from the node pair; `IOP=1/3` unhandled, as in dyna2rad). An
    `*ELEMENT_DISCRETE` with a resolvable `VID` now converts to an oriented
    `/PROP/TYPE8` (SPR_GENE) — stiffness on local DOF 1 along the skew axis —
    instead of being skipped; only TYPE8 carries a `skew_ID`. `DRO=1` torsional
    sections and unresolvable `VID`s stay warned + skipped.
  - `*DEFINE_BOX` / `*DEFINE_BOX_LOCAL` → **numeric node-membership scoping**
    (no `/BOX` entity emitted — `/BOX/RECTA` has no reader cfg and dangling
    geometry risks a starter abort). Consumers intersect their node group with
    the box's contained nodes at conversion time, mirroring the `NSIDEX`
    set-difference; a `_LOCAL` box tests each node in the box's own frame
    (origin + X̂/in-plane vectors). Wired into `*INITIAL_VELOCITY` `BOXID` and
    `*RIGIDWALL_*` `BOXID` (box-only scopes the tracked `/GRNOD`; `NSID`+`BOXID`
    drops the box, `NSID` wins — matching dyna2rad). Contact `SBOXID`/`MBOXID`
    do not map onto a contact surface here, so they are dropped with a loud
    warning (dyna2rad only maps them for `*CONTACT_FORCE_TRANSDUCER_PENALTY`);
    `_ADAPTIVE`/`_COARSEN`/`_DRAWBEAD`/`_SPH` box variants are skipped.
    Starter-validated (0 errors; the four new skews, the box-scoped `/GRNOD`s
    and the oriented `/PROP/TYPE8` with `skew_ID` all read cleanly).
- **Tables & strain rates**
  - `*DEFINE_TABLE_2D` (and resolvable legacy `*DEFINE_TABLE`) → `/TABLE/1`
    with `Ndim=2`; `*MAT_024` `LCSS`-tables and `*MAT_SIMPLIFIED_JOHNSON_COOK`'s
    `(1 + C·ln ε̇*)` term now convert as LAW36 multi-rate curve families
    instead of being dropped.
- **Initial state & cross-sections**
  - `*INITIAL_STRESS_SHELL` → `/INISHE/STRS_F[/GLOB]`,
    `*INITIAL_STRESS_SOLID` → `/INIBRI/STRS_FGLO` (layer counts checked
    against the property; mismatches warn + skip per the starter's rules).
  - `*DATABASE_CROSS_SECTION_SET/_PLANE` → `/SECT` (plane form via a
    geometric straddle resolver) + `*DATABASE_SECFORC` → `/TH/SECTIO`;
    `*SET_SHELL`/`_SOLID`/`_BEAM` element sets.
- **Initial velocities**
  - `*INITIAL_VELOCITY` (base set form) → `/INIVEL/TRA` (+ `/INIVEL/ROT` for
    the rotational DOFs). `NSID` scopes the node group (blank/0 = whole model);
    `NSIDEX` is removed by set difference at conversion time; `ICID` maps to the
    matching `/SKEW` from a converted `*DEFINE_COORDINATE_*` (else global with a
    warning). `BOXID` is now intersected against the `*DEFINE_BOX` contained
    nodes (see **Geometry utility cards**); a rigid-overwrite `IRIGID` and the
    Card-3 per-exempt-node velocities are warned + dropped.
  - `*INITIAL_VELOCITY_GENERATION` → `/INIVEL/AXIS` + a companion `/FRAME/FIX`.
    The rotation axis (through `(XC,YC,ZC)` along `(NX,NY,NZ)`, or node-defined
    when `NX=-999`) becomes the frame's local Z; `OMEGA`→`VR`; the translational
    `VX/VY/VZ` is projected onto the frame's local axes so Radioss re-expands it
    to the correct global velocity. A nonzero `ICID` rotates `VX/VY/VZ` and the
    vector rotation axis from that local system to global (mirroring the base
    form's `/SKEW` reference), warned + global when the id has no converted
    `/SKEW`. `STYP` 0/1/2/3 (all / part set / part / node set) scopes the group
    — part scans now include `*ELEMENT_DISCRETE` springs; synthesized `/FRAME`
    ids skip any converted `/SKEW`/coordinate id (shared starter namespace);
    `PHASE`, `IVATN`, `IRIGID` are warned + dropped, and
    `*INITIAL_VELOCITY_GENERATION_START_TIME` stays skipped. Starter- and
    engine-validated (0 errors; cycle-0 KE matches the analytic value).
- **Rigid walls**
  - `*RIGIDWALL_PLANAR_MOVING` (+`_FORCES`) → moving `/RWALL/PLANE` (carrier
    node with mass + V0 along the normal); `*RIGIDWALL_PLANAR_FINITE`
    (+`_MOVING`) → `/RWALL/PARAL` from `XHEV`/`LENL`/`LENM`.
- **Buckling** — shells now supported (consistent-membrane geometric
  stiffness), validated against the analytic SSSS plate (k = 4) to 2.2 %.
- **Materials**
  - `*MAT_ANISOTROPIC_VISCOPLASTIC` (103) → `/MAT/LAW128` (HILL_VISC_PLAST),
    the near 1:1 Radioss counterpart: Voce `QR/CR` + kinematic `QX/CX`
    hardening and the Hill surface (shell Lankford `R00/R45/R90` or brick
    `F/G/H/L/M/N`) carry over verbatim; the iso/kin split becomes `CHARD`
    (`1−ALPHA` for the `FLAG=1` fit, else the kinematic fraction) and the
    additive `VK·ε̇^VM` overstress is matched to LAW128's Cowper-Symonds
    `EPSP0/CP` at initial yield (a rate-table `LCSS` is used directly). Because
    every Radioss Hill law is orthotropic-only, each converted part is
    repointed at a synthesized `/PROP/TYPE9` (shell) or `/PROP/TYPE6` (solid);
    the orthotropy reference direction is auto-mapped from MAT_103's `AOPT`
    when it is a global vector (`AOPT=2` → `Vx/Vy/Vz`, `AOPT=3` → `Vx/Vy/Vz`
    + `Phi`), else falls back to global-X with a warning. Verified reading in the OpenRadioss
    starter (0 errors); LAW128 is a 2026-format law, so the `/BEGIN 2022` deck
    draws one cosmetic `WARNING 100211` but parses correctly.
  - MAT_103 shift guard: fixed-format decks that OMIT the mandatory (but
    `FLAG≥1`-ignored) card-2 `QR/CR/QX/CX` line shift every following card up by
    one, silently leaking the Hill `F/G/H/L/M/N` into the hardening slots. The
    handler now detects the fingerprint (`FLAG=1/2` + nonzero `QR/CR/QX/CX` +
    all-zero `L/M/N`) and warns to insert the blank card-2 line.

### Changed

- `ConversionState` is now a dataclass — a typed, mypy-checkable contract
  between handlers and writer (no-arg construction unchanged).
- The writer was split from a single 7,300-line module into the
  `k2rad/writer/` package (10 family modules + an explicit re-export
  `__init__`; byte-identical output, same public surface).
- Extracted the TET10 connectivity constant into a neutral `k2rad/topology.py`
  (so the optional `gapmin` path no longer imports the whole writer), and made
  `build_starter` assemble the starter from a data-driven section registry
  (output byte-identical).

- **Keyword coverage**
  - `*CONSTRAINED_RIGID_BODIES` → a single merged `/RBODY` (slave rigid part's
    nodes fold into the master; chains resolved transitively).
  - `*CONTACT_..._TIEBREAK` (SURFACE_TO_SURFACE / ONE_WAY / TIEBREAK_*) →
    `/INTER/TYPE7` (contact-only; the cohesive pre-bond is warned as dropped).
  - `*DEFINE_CURVE_FUNCTION` → `/FUNCT` by sampling a pure single-variable
    (x/time) expression; parameter/curve/state-referencing expressions are
    warned and skipped.
  - Foam & honeycomb materials: `*MAT_CRUSHABLE_FOAM` (63) → `/MAT/LAW50`,
    `*MAT_LOW_DENSITY_FOAM` (57) → `/MAT/LAW38`, `*MAT_FU_CHANG_FOAM` (83) →
    `/MAT/LAW70`, `*MAT_HONEYCOMB` (26) → `/MAT/LAW28` (confidence levels and
    dropped fields warned per law).
- **Analyses** (offline, riding the modal stiffness-export chain)
  - Linear buckling (`tools/modal_buckling.py`): `K φ = λ(−K_g)φ` for
    beam/rod/truss elements, validated against the analytic Euler column to
    0.001%; shells/solids warned as unsupported.
  - Harmonic / frequency-response (`tools/modal_frf.py`): modal-superposition
    FRF sweep to base or nodal harmonic excitation, validated against the
    closed-form SDOF response.
- **Packaging / DX**
  - `pyproject.toml` with a `k2rad` console entry point and optional
    `[modal]` / `[viz]` / `[all]` / `[dev]` extras.
  - Contributor scaffolding (LICENSE, CONTRIBUTING, CHANGELOG, PR/issue templates).
  - Golden-file end-to-end regression fixtures (`tests/fixtures/` +
    `tests/test_golden.py`); coverage gate; advisory mypy; Windows CI leg;
    PyPI publish workflow; Docker bash launchers (`or.sh`, `build-and-export.sh`).

### Fixed

- `*LOAD_SEGMENT_SET` pressure loads were silently dropped; now converted to
  `/PLOAD`.
- `*EOS_LINEAR_POLYNOMIAL` now warns when the `C6·μ²·E` term is nonzero (it has
  no `/EOS/POLYNOMIAL` equivalent) instead of ignoring it silently.
