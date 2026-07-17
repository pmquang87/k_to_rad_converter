# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Prior history (before this changelog was introduced) is summarized in the
`git log` — each keyword conversion and bug fix landed as its own commit / PR.

## [Unreleased]

### Added

- **Failure criteria**
  - `*MAT_ADD_EROSION` now converts its **full card-1/card-2 scalar-criteria
    set to a single `/FAIL/GENE1`** (layout audited against `hm_cfg_files`
    `FAIL/fail_gene1.cfg` `FORMAT(radioss2022)` — the block a `/BEGIN 2022`
    deck reads with, which has **no** trailing `FAILIP` on card 6, unlike
    2025+), following the `dyna2rad` `p_ConvertMatAddErosion`
    (`convertmats.cxx:6817`) `IDAM==0` mapping: `MXPRES`→`Pmax`, `MNPRES`→
    `Pmin`, `SIGP1`→`SigP1_max`, `SIGVM`→`Sig_max`/`fct_IDsm`, `MXEPS`→
    `Eps_max`/`fct_IDps`, `MNEPS`→`Eps_min`, `EFFEPS`→`Eps_eff`, `VOLEPS`→
    `Eps_vol`, `EPSSH`→`Eps_s`, `SIGTH`→`Sigr`, `IMPULSE`→`K`, `FAILTM`→
    `Time_max`, `NCS`→`NCS`, `NUMFIP`→`Pthickfail`.
    - **Migration**: `MXEPS` and `EFFEPS` moved out of the old standalone
      `/FAIL/TENSSTRAIN` + `/FAIL/JOHNSON` into GENE1 `Eps_max`/`Eps_eff`
      (consolidated, as `dyna2rad` does). This is also *more* faithful: the old
      `EFFEPS`→`/FAIL/JOHNSON` borrowed the material-failure `Ifail_sh=2`
      all-points rule, but `*MAT_ADD_EROSION` erosion is governed by `NUMFIP`
      (default `1` = first failed IP), which GENE1 expresses through
      `Pthickfail`.
    - **Signs / sentinels**: the GENE1 reader (`hm_read_fail_gene1.F`) forces
      `Pmin=-ABS`, `Pmax=+ABS`, `Eps_min=-ABS` and treats `0` as inactive
      (`0`→`±INFINITY`), a structural match to LS-DYNA's `EXCL=0` convention —
      so the common case passes straight through. A **non-zero `EXCL`** is now
      applied (fields equal to it are zeroed = made inactive) and warned,
      rather than `dyna2rad`'s silent pass-through (`EXCL` is a documented
      dead read there, `convertmats.cxx:6862`). `FAILTM<0` maps as `|FAILTM|`
      with a warning (the dynamic-relaxation-inactive nuance has no GENE1
      flag); `SIGVM<0`/`MXEPS<0` become the `fct_IDsm`/`fct_IDps` load-curve
      slots with a `1.0` ordinate scale.
    - **`NUMFIP`→`Pthickfail`** uses the engine's negative-`Pthickfail`
      broken-IP-ratio form (`fail_setoff_c.F`: `Pthk<0` → delete when
      `count/NPTT >= |Pthk|`), which is exact for the percent form
      (`-|NUMFIP|/100`) and, resolving `NPTT` from the material's
      `*SECTION_SHELL` `NIP`, for the count forms; the `NUMFIP=1` default is
      the first-IP `-1e-6`. This is preferred over `dyna2rad`'s positive
      thickness-fraction algebra, whose documented bugs (shell `Volfrac`
      write, `abs(NUMFIP-100)`, cross-iteration `Pthickfail` leak) it sidesteps.
    - `IDAM≥1` (GISSMO/DIEM embedded in the erosion card) still warns, but the
      scalar criteria now convert regardless (they are independent of the
      damage model); the standalone `*MAT_ADD_DAMAGE_GISSMO`→`/FAIL/TAB2` path
      is untouched. Validated with a full OpenRadioss starter run (0 errors;
      the one WARNING 3029 is the benign `/PROP`-vs-`/FAIL` `Pthickfail` sign
      reconciliation the engine handles automatically).
  - `*MAT_123` (`*MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY`) **stops dropping
    `EPSTHIN`/`EPSMAJ`/`NUMINT`** (per `dyna2rad` `p_ConvertMatL123`,
    `convertmats.cxx:6169`). The base plasticity conversion is unchanged
    (`/MAT/LAW36`, `FAIL`→`/FAIL/JOHNSON`, `Eps_p_max` hard-zeroed); the three
    card-2 extras are added as trailers, discriminated from plain MAT_024 by
    the keyword so a MAT_024 whose slots happen to be non-blank is not
    mis-parsed:
    - `EPSTHIN`→`/FAIL/TAB1` `P_THICKFAIL` (layout from
      `FAIL/fail_tab1.cfg` `FORMAT(radioss2021)`, `Ifail_sh=2`). The mandatory
      `table1_ID` strain-vs-triaxiality table is a flat inert `10.0` plateau
      across `[-0.3, 0, +0.3]` (`dyna2rad`'s `FAIL==0`→`10.0` sentinel) so the
      card carries only the thinning criterion and does not double-count `FAIL`
      (which stays on `/FAIL/JOHNSON`). Fidelity note: because `FAIL` rides on
      `/FAIL/JOHNSON`, no IP fails *via* the inert TAB1 table, so its
      `P_THICKFAIL` never actually triggers — EPSTHIN thinning erosion is a
      carrier only, not reproduced (the same limitation as `dyna2rad`, whose
      inert plateau this mirrors). `EPSTHIN<0` is dropped with a warning.
    - `EPSMAJ`→`/FAIL/FLD` (layout from `FAIL/fail_fld.cfg`
      `FORMAT(radioss2019)`, `Ifail_sh=2`, `I_marg=1`), a flat forming-limit
      curve at `|EPSMAJ|`.
    - `NUMINT` (integration points that must fail before deletion) is
      approximated by the `Ifail_sh=2` all-points rule on whichever `/FAIL`
      card(s) the material emits (`/FAIL/JOHNSON`/`/FAIL/TAB1`/`/FAIL/FLD`),
      warned when non-zero (`NUMINT=0` = ALL points is exactly that rule, so
      silent) — the same limitation as MAT_103's `NUMINT`.
    - A new `/ANIM/ELEM/DAMG` engine channel is emitted when TAB1/FLD damage
      models are present (as for GISSMO's `/FAIL/TAB2`).
  - `*MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION` and `…_2D` (and
    `…_LOG_INTERPOLATION_2D`) now **dispatch onto the MAT_024 path** (they were
    silently skipped) and set `/MAT/LAW36` `F_smooth=2` — logarithmic rather
    than linear interpolation between the strain-rate yield curves (`dyna2rad`
    branches on `keyWordLog.find("LOG_INTERPOLATION")`). The LAW36 reader forces
    `F_smooth=0` for a single static curve, so this only takes effect with a
    rate-curve family; plain MAT_024 keeps `F_smooth=0` (unchanged). Also added
    the missing numeric `MAT_024`/`MAT_24`/`MAT_123` alias keys (such decks were
    silently skipped, dangling the `/PART`).
- **Element formulation / hourglass**
  - `*HOURGLASS` (new handler) + the `*PART` `HGID` field + a now-honored
    `*CONTROL_HOURGLASS` → **per-part hourglass control** on `/PROP/SOLID`
    (and `/PROP/SHELL`), following the `dyna2rad`
    `ConvertProp::ConvertEntities` mapping. Solid `IHQ` → `Isolid`
    (`1/2/3`→`1`, `4/5`→`5`, `6/7`→`24`) and `QM`/`QH` → the hourglass
    coefficient `h`; the map is gated to non-tetra, non-ALE sections, and
    `IHQ 0/8/9/10` keep the section's ELFORM `Isolid` (warned — no faithful
    Radioss formulation). A part's `*HOURGLASS` **overrides** the global
    `*CONTROL_HOURGLASS`; `HGID=0`, or a dangling reference (warned loudly),
    falls back to it. Since k2rad `/PROP`s are per-`*SECTION`, a part whose
    effective hourglass differs from its section's base is split into a
    dedicated `/PROP` (the same split mechanism as the LAW128 orthotropy
    props — the shared section prop is retained for the section's other
    parts, suppressed only when every part on it was split). Shells carry the
    coefficient into `Hm/Hf/Hr` (clamped to the Radioss `0.05` limit) but keep
    the ELFORM-selected `Ishell` `12` (QBAT) / `24` (QEPH), for which the
    coefficient is physically inert (warned; no `IHQ`→`Ishell` map is
    invented). Previously `*CONTROL_HOURGLASS` was parsed then silently
    dropped and every `/PROP` hourglass field was hard-zeroed to the Radioss
    defaults. Starter- and engine-validated (0 errors: `Isolid 5` accepted
    with `h` active, `Isolid 24` from the global card).
- **Contact interfaces**
  - `*CONTACT_AUTOMATIC_GENERAL` now honours the `dyna2rad` **`SOFT`-sentinel
    routing** (`convertcontacts.cxx` cc:133-164) instead of the old blunt
    single-surface alias: `SOFT=-7` → `/INTER/TYPE7`, `SOFT=-11` →
    `/INTER/TYPE11` **edge-to-edge (line) contact**, `SOFT=-19` →
    `/INTER/TYPE19` (surface+edge); any ordinary `SOFT` (0/1/2/blank, or no
    optional Card A) keeps the validated single-surface routing byte-for-byte
    (`/INTER/TYPE25` explicit self-contact or `/INTER/TYPE7` implicit).
    - **New `/LINE` emission** (greenfield — k2rad emitted no edge/line entity
      before). The `SOFT=-11` path **synthesizes the `/LINE` group(s)** the
      `/INTER/TYPE11` `line_IDs`/`line_IDm` fields require (`/SETS/LINE`, per
      `hm_cfg_files` `INTER/inter_type11.cfg` `FORMAT(radioss2020)` +
      `hm_read_inter_type11.F`): a **`/LINE/SEG`** (2-node edges, layout audited
      against `SETS/line.cfg` `FORMAT(radioss51)`) built from a `*SET_SEGMENT`'s
      consecutive-node-pair edges, otherwise a **`/LINE/SURF`** over the part
      surface so the starter derives the edges. `line_IDm=0` = self edge-impact.
      (`dyna2rad` forwards the raw `/SET/GENERAL` into `line_IDs` and defers edge
      derivation to the starter; k2rad has no `/SET/GENERAL` contact path and
      TYPE11 requires genuine `/LINE` groups, so it builds them — the faithful
      option (b) the `dyna2rad` source itself names.) `SOFT=-19` needs no
      `/LINE`: it hands two `/SURF` to the starter, which auto-generates the
      child TYPE7+TYPE11.
    - Friction (`FS` → scalar Coulomb `Fric`), Gapmin (Card-3 `SST`/`MST` via
      `_sst_mst_to_gapmin`), Inacti (`IGNORE` via `_ignore_to_inacti`), VisS
      (`VDC`) and Stfac (`SFS`) route through the same plumbing as TYPE7/TYPE25.
      `--inter-gapmin`/`--auto-gapmin` deliberately do **not** reach the
      SOFT-routed interfaces (a separate `state.contacts_general` list). That
      list is threaded into the three sites that treat single/surf2surf/tied as
      *all* contacts: the implicit contact-free stabilization stub is suppressed
      when a general contact exists (no spurious all-parts self-contact), and
      `*DATABASE_NCFORC` → `/TH/INTER` plus the `*CONTACT_FORCE_TRANSDUCER`
      parent fallback both include general interfaces.
    - The `SOFT=-7` route emits **`Istf=2`, `Igap=2`** (matching `dyna2rad`'s
      routed-TYPE7 map cc:52 + the `SOFT<1` rule cc:626), not the plain
      single-surface emitter defaults (`Istf=4`, `Igap=0`), so all three routed
      types share `dyna2rad`'s stiffness/gap model. Deliberate, documented
      deviations from `dyna2rad` (all consistent with k2rad's validated TYPE7
      family and harmless when scale factors are unit/blank and `FS==FD`): the
      engagement gap is `(|SST|+|MST|)/2` rather than the scale-weighted
      `fabs(SST·SFST+MST·SFMT)/2`; `Inacti=5` (validated — node-moving
      `Inacti=6` seg-faults rigid-body secondary nodes) rather than a fixed 6;
      scalar `Fric=FS`/`Ifric=0` rather than `FD·FSF`+decay/`Ifric=2` on the
      -7/-19 routes. `SOFT=-7`/`-19` sides resolve part/part-set only (a
      `*SET_SEGMENT`/`*SET_NODE` side is skipped with a warning; use `-11` or
      restrict to parts).
  - `*CONTACT_TIED_SURFACE_TO_SURFACE` (+ `_OFFSET`/`_CONSTRAINED_OFFSET`) now
    applies the `dyna2rad` **negative-offset discriminator** (`convertcontacts.cxx`
    cc:220) `(SFST*SST + SFMT*MST)/2 < 0` → **`/INTER/TYPE10`** (penalty tie,
    `FORMAT(radioss120)`) instead of the always-`/INTER/TYPE2`; `≥ 0` keeps the
    kinematic TYPE2. The discriminator uses the **raw** Card-3 `SFST`/`SFMT`
    (no zero→1 defaulting — a blank scale factor always stays TYPE2), so TYPE10
    needs a nonzero `SFST`/`SFMT` together with a negative `SST`/`MST`. TYPE10
    bonds by a penalty spring over `GAP=(|SST|+|MST|)/2`, so (unlike the
    kinematic TYPE2) its secondary nodes may coexist with `/RBODY` and its
    rotations are not tied. Card-3 `SST`/`MST`/`SFST`/`SFMT`/`SFS`/`SFM` are now
    parsed (previously only `SST`/`MST` were kept). NODES/SHELL_EDGE tied
    variants stay kinematic TYPE2 (the discriminator is a SURFACE construct).
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
    `*RIGIDWALL_*` `BOXID` (box-only scopes the tracked `/GRNOD`; a box enclosing
    no node = no slave nodes = inactive wall, so it is skipped rather than
    tracking ALL nodes; `NSID`+`BOXID` drops the box, `NSID` wins — matching
    dyna2rad). Contact `SBOXID`/`MBOXID` — including on
    `*CONTACT_FORCE_TRANSDUCER_PENALTY`, the one contact dyna2rad maps them for —
    do not map onto a contact surface here, so they are dropped with a loud
    warning; `_ADAPTIVE`/`_COARSEN`/`_DRAWBEAD`/`_SPH` box variants are skipped.
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

- **TET10 midside ordering (two bugs, both on LS-DYNA-ordered `*ELEMENT_SOLID`
  ten-node meshes).** LS-DYNA and Radioss `/TETRA10` agree on corners 1-4 and the
  base midsides 5/6/7 but order the three **apex** midsides differently
  (LS-DYNA n8=mid(2,4)/n9=mid(3,4)/n10=mid(1,4) vs Radioss
  n8=mid(1,4)/n9=mid(2,4)/n10=mid(3,4)). The converter now normalizes every
  10-node tet to Radioss order in a new `_normalize_tet10_ordering` writer
  pre-pass before any consumer (the mid-edge snap, `--auto-gapmin` faceting, and
  the `/TETRA10` emit) reads the midside slots. This fixes:
  - the **`ERROR 558` storm** — the snap pass, applying the Radioss mid-edge map
    to un-permuted LS-DYNA connectivity, sent the elements sharing a midside node
    to conflicting straight-edge targets; last-write-wins collapsed distinct
    nodes onto one point, producing null-area `/SURF/PART/EXT` segments (measured
    3230× on a 143901-tet part);
  - the **silent ~−30% `/TETRA10` element volume/mass** — the emit wrote the
    LS-DYNA node order verbatim into Radioss slots, so the engine read the wrong
    node in each apex slot (a unit cell reproduces the exact 0.7× mass ratio;
    `ERROR 489` never caught it because it only fires on a zero/negative
    sub-volume).

  The source order is detected geometrically per element (nearest apex-edge
  midpoint); the whole mesh then takes one convention chosen by **majority** of
  the classified elements, so a stray sliver/degenerate element that fails to
  classify can no longer flip a clearly-Radioss/Abaqus (C3D10) deck into a
  wrongful permutation (an already-Radioss deck stays untouched). Ties and
  ambiguous / mixed / coordinate-less meshes default to the LS-DYNA→Radioss
  permutation **with a loud warning** (matching every real LS-DYNA deck and
  Altair's hm_reader) plus a shared-midside consistency verifier. The read-only
  `--suggest-gapmin` inspection path (`gapmin.analyze_file`) now runs the same
  normalization before measuring, so the clearance/Gapmin it prints matches the
  surface the engine builds and the value `--auto-gapmin` bakes into the deck.
  The neutral `topology.TET10_MIDEDGE` remains the single Radioss-order source of
  truth for the snap pass, gapmin faceting, and emit; `--tet10-to-tet4` keeps the
  (never permuted) corner nodes and is unaffected (its /TETRA10-repair warnings
  are suppressed, since it emits no /TETRA10).
- `*LOAD_SEGMENT_SET` pressure loads were silently dropped; now converted to
  `/PLOAD`.
- `*EOS_LINEAR_POLYNOMIAL` now warns when the `C6·μ²·E` term is nonzero (it has
  no `/EOS/POLYNOMIAL` equivalent) instead of ignoring it silently.
