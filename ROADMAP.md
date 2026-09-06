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
  `*CONTACT_..._TIEBREAK` → `/INTER/TYPE2` (a tie; OPTION 6/8 also rupture);
  the impact/blast materials `*MAT_JOHNSON_HOLMQUIST_CERAMICS`/`_CONCRETE` →
  `/MAT/LAW79`/`LAW126` and `*MAT_ELASTIC_FLUID` → `/MAT/LAW6` +
  `/EOS/POLYNOMIAL`.
- **Tier 2 (rare materials):** `*MAT_SHAPE_MEMORY` / `*MAT_030` →
  `/MAT/LAW71` (superelastic SMA; `ALPHA` copied 1:1 against the two closed
  forms — dyna2rad's `sqrt(2/3)·ALPHA` is a d2r defect — with the range guard at
  LS-DYNA's own `|ALPHA| < sqrt(2/3)` bound, `YMRT → E_mart` — the slot
  dyna2rad's `"YMTR"` typo never writes, temperature terms deliberately blank,
  the curve form of the four transformation stresses warn-skipped by name).
  `*MAT_MUSCLE` / `*MAT_156` and `*MAT_SPRING_MUSCLE` / `*MAT_S15` →
  `/PROP/TYPE46` (`SPR_MUSCLE`) + `/SPRING`, routed by the PROPERTY the part
  carries (truss vs discrete) and validated against the engine force law to 7
  digits. Radioss DOES have a truss element — `/TRUSS` + `/PROP/TYPE2`, read by
  `hm_read_truss.F` and `hm_read_prop02.F` and integrated by `tforc3.F` — but it
  carries no MUSCLE law: `PROP_TRUSS` is declared by six laws only (0, 1, 2, 13,
  34, 44) and LAW156's Radioss counterpart lives entirely in a spring property,
  so the axial-only muscle becomes a `/PROP/TYPE46` spring. (The premise
  "Radioss has no truss element" was FALSE and was corrected with the R14 truss
  batch; the conclusion is unchanged, for this different reason.)
  `*MAT_ADD_THERMAL_EXPANSION` → `/THERM_STRESS/MAT` + `/HEAT/MAT` with the
  minimal temperature-driver foothold (`/INITEMP`, `/IMPTEMP`); a `*MAT_ELASTIC`
  material whose every part is a SHELL is restated as `/MAT/LAW36` with a
  far-yield curve, because LAW1 runs global integration and cannot expand at all
  (measured 2.7e-07 mm against 0.012 mm; the restatement is elastically neutral
  to +0.035 % and costs −4.6 % of time step). See the Tier 4 *Thermal* entry for
  what is done and what stays open.
- **Tier 2 (rare cards):** `*DEFINE_ELEMENT_DEATH_{SOLID,BEAM,SHELL,THICK_SHELL}[_SET]`
  → `/ACTIV` (`Iform = 2` always — `Iform = 1` needs a sensor LS-DYNA has no
  field for and is a measured silent no-op without one; the element scope splits
  per EMITTED family, and a `TIME = 0` card is refused rather than inverted,
  because `hm_read_activ.F:139` reads that same zero as "never").
  `*DEFINE_CURVE_SMOOTH[_TITLE]` → `/FUNCT_SMOOTH`, the only card that keeps the
  quintic ramp AND clamps past `TEND`; its LCID joins the `/FUNCT` + `/TABLE`
  namespace, which is what takes the EFG metal-cutting carrier from starter
  `ERROR 120` (a dangling `funct_IDT` on the `/IMPVEL` the deck still emitted)
  to 0 errors. `*PERTURBATION_NODE` TYPE 8 → `/RANDOM[/GRNOD]` with the `DTYPE`
  amplitude the symmetric `ALEAT()` actually needs, and the global-vs-grouped
  mutual exclusion resolved at conversion time.
  `*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY` → one `/IMPDISP/FGEO` per distinct
  `(LCID, DEATH, BIRTH)`, with the negative-NID set form PROJECTED onto `z = Z`
  rather than collapsed onto one point. `*INTERFACE_SPRINGBACK_LSDYNA` → the
  engine `/DYNAIN` block, on a schedule rather than a single terminal trigger
  because the engine's own end-of-run rescue sets `ILASTDYNAIN` and never reads
  it — an EXPLICIT-only caveat, MEASURED: under quasi-static implicit
  `imp_dt.F:53-56` clamps the last step onto `TSTOP`, so the run lands on
  `ENDTIM` and the highest-numbered dynain IS the terminal state (probe:
  NORMAL TERMINATION in 20 cycles, three 22 225-byte files with all four
  blocks, driven edge 20.1960 / 20.1980 / 20.2000). No implicit guard is
  applied and none should be.
- **SIDE-DEFECT batch — DONE.** Ten defects at the edges of cards this
  converter already handles: the bare `*EOS_*` /MAT/LAW6 carrier's /MAT
  collision (removed — it could never be legal, since no `*EOS_*` spelling
  carries a density); the missing `_OFFSET_SPECS` rows on
  `*INITIAL_STRESS_SHELL`/`_SOLID` (and `*INITIAL_VOLUME_FRACTION_GEOMETRY`);
  /DAMP reaching only four element families, so a beam+spring model ran
  undamped; `/INISH3/STRS_F`; the conditioning-picked /SECT reporting frame;
  `_plane_cut`'s missing spring arm and the `_SET` spelling's dropped
  TSID/DSID; /DYNAIN under implicit (measured: it works, no guard); the
  element-GROUP allocator on 1 of 18 sites; `*PARAMETER_EXPRESSION`; and the
  dead tiebreak `c.only` branch. Two deck-level numbers changed on real
  corpus decks: the EFG metal-cutting example's tool speed 300 -> 360 mm/s,
  and 152.08 kg of Yaris occupant mass restored. Adds two deck-wide duplicate
  scans (/EOS and the per-family GROUP namespaces), bringing the family from
  nine to eleven. See CHANGELOG for the per-item measurements.
- **Milestone 2, batch 1 (beyond dyna2rad parity) — IN PROGRESS.** The whole
  `*SET_<FAMILY>_ADD` boolean-union family (`NODE`, `SEGMENT`, `SHELL`,
  `SOLID`, `BEAM`, `DISCRETE` + `*SET_NODE_ADD_ADVANCED`, joining the shipped
  `PART`) is expanded at conversion time into the family's ordinary set
  container by ONE shared, recursive resolver with a cycle guard and a warned
  depth cap — so the union id resolves wherever a plain set id does. The
  one-level rule the `*SET_PART_ADD` path used to apply is lifted. There is no
  `*SET_TSHELL_ADD` in LS-DYNA (HyperMesh cfg only), so none is invented.
  `*MAT_COMPOSITE_DAMAGE` (022) converts as well — see the Tier-3 *Composites*
  entry. **Open items this batch surfaced but deliberately did not change,
  because both would move output on decks that have nothing to do with it:**
  `*MAT_ORTHOTROPIC_ELASTIC` and `*MAT_ENHANCED_COMPOSITE_DAMAGE` have NO
  `_OFFSET_SPECS` row, so an `*INCLUDE_TRANSFORM` leaves their MID behind while
  `*PART`'s IDMOFF moves the reference (today that at least warns, "id offsets
  are NOT applied to …"); and `*MAT_054`'s `SLIM*` cells default to 1.0 in
  k2rad, which `sigeps127c.F90:400-403` uses to clamp a failed mode's stress at
  its FULL strength — worth checking against LS-DYNA's own default before
  changing.
  Two more, from the post-review round: **four consumers resolve a set DURING
  dispatch and therefore still see only DIRECT sets** —
  `*CONSTRAINED_EXTRA_NODES_SET`, `*ELEMENT_MASS_PART_SET`,
  `*ELEMENT_MASS_NODE_SET` and `*LOAD_BODY_PARTS` (`handlers.py:7762`, `:8539`,
  `:8584`, `:12781`); this is the shipped `*SET_PART_ADD` behaviour unchanged,
  and lifting it means deferring those four to a prepass. And
  `thermal._structural_density` walks the CLONE registry, so it reads no
  density for the four producers deliberately excluded from it (LAW5+/EOS,
  the LAW27 glass pair, the belt LAW114/119 and the spotweld fallback) —
  today that surfaces only as the honest "rho_cp <= 0" warning on a `/HEAT/MAT`
  built from one of them. (MAT_022 WAS a fifth until the verification round:
  its `/FAIL/CHANG` is generated from the record, so a clone carries it, and
  the entry is now in the registry.)
  **Still open in this area:** `*SET_TSHELL` (so a `THICK_SHELL_SET` scope
  resolves without being restated as a `*SET_SOLID` — a `*SET_SHELL` is
  deliberately NOT accepted as a fallback, since it is a third SID namespace and
  cannot hold a thick-shell id),
  `*PERTURBATION_SHELL_THICKNESS` → `/PERTURB/PART/SHELL`, the `/STATE/*`
  sibling of `/DYNAIN` for the solid/beam/spring state a dynain cannot carry
  (this is also what a shell-less `*SET_PART` on an `*INTERFACE_SPRINGBACK`
  would need — today those parts are dropped from the `/DYNAIN` list by name).
- **Tier 4:** linear buckling (`tools/modal_buckling.py`, Euler-validated) and
  harmonic/FRF (`tools/modal_frf.py`, SDOF-validated).
- **Lossy:** `*EOS_LINEAR_POLYNOMIAL` `C6` now warned. (`*MAT_PLASTIC_KINEMATIC`
  Cowper-Symonds `SRC/SRP` was already emitted correctly to LAW44.)
- **Testing/CI/DX:** golden-file fixtures, coverage gate, blocking mypy (pinned
  2.3.1), Windows CI leg, PyPI publish workflow, Docker bash launchers.

The remaining items below are still open.

## Architecture refactors

The core pipeline (parse → dispatch → `ConversionState` → writer) is sound.
All four originally-listed refactors are **done** (kept below for the rationale
record): the `writer/` package split, the `ConversionState` dataclass, the
shared `topology` module, and the `build_starter` section registry. The mypy
burn-down that used to be listed here alongside them is done too — `mypy k2rad`
is clean and the CI `typecheck` job is **blocking** (see Testing/CI below).

**No architecture refactor is open.** In particular, grouping the state's
fields into sub-dataclasses is **closed as "not worth it"** — see the bullet
below for the measurement.

- **Split `writer.py` into a `writer/` package by section.** At ~5.5 k lines it
  is by far the largest module and mixes every card format. Break it into
  `materials`, `mesh`, `contacts`, `rbody`, `loads`, `blast_ale`, and `engine`
  submodules mirroring the `_make_*` groupings already present. *Rationale:*
  faster navigation, smaller review surface per change, and a natural home for
  per-family tests.
- **Make `ConversionState` a dataclass.** *(done)* It is a `@dataclass` with
  **352 typed, defaulted fields** and 17 methods, organised by section comments
  (`k2rad/state.py`). This delivered the whole original rationale: typo-safe
  field access, free `repr`/defaults, a documented shape for contributors, and
  a mypy-checkable handler↔writer contract.
- **Group those fields into sub-dataclasses.** *(closed — not worth doing;
  measured 2026-09, PR #134.)* The idea was `state.mesh.nodes` in place of
  `state.nodes`. Four measurements closed it:
  1. **It buys nothing for typing.** Of the 194 mypy findings burned down in
     PR #134, **0 were in `state.py`** and 1 of 194 mentioned `ConversionState`
     at all. The root causes were local-variable inference (64 `"object" has no
     attribute"` in four writer modules) and one un-narrowable `SectionBeam |
     None` that accounted for **26** `union-attr` findings on its own — every
     `union-attr` in `writer/dbeam.py`, spread over 24 distinct lines (1045 and
     1064 carry two each). A grouping changes none of them.
  2. **The domain does not decompose into 4-6 groups.** Classifying all 352
     fields by family yields **29 families**, the largest being `materials`
     with 78; the originally proposed `mesh/loads/contacts/control` covers 69 of
     352. Those four figures are a **hand classification by keyword family**,
     not a mechanical count — there is no recipe to re-run, only the field list
     to re-read. Several families (thermal, seatbelts) genuinely span any
     grouping, because the LS-DYNA keyword space is a family × role
     cross-product and the state mirrors it.
  3. **The experiment has already been run, in comment form, and it drifted.**
     Before PR #134, **148 of 352 fields (42 %) sat under a section comment that
     did not describe them** — 77 of the 84 fields under `# ── SPH particles ──`
     were materials, airbags or hourglass records. The 84 is mechanical (parse
     `state.py`'s rule comments, count the annotated fields under each: 18 rules
     on master, 27 here, 352 fields placed either way); the 148 and the 77 are
     the same hand classification as (2). A wrong comment costs one
     line to fix (PR #134 split the two worst sections); a wrong *group* bakes
     the mistake into 5-100 call sites and costs another mechanical rewrite.
  4. **The verification net cannot cover the migration's riskiest part.** The
     state is reached dynamically at **11 sites** in `k2rad/` — `getattr` on a
     computed name at `handlers.py`, `writer/mesh.py` (×5), `writer/tshell.py`;
     `vars(state)` at `writer/sph.py`; plus three vestigial
     `getattr(state, "<literal>", default)` calls (`options`, `define_tables`,
     `contacts_type25`; PR #134 retired a fourth, `table_1d_ids`) — and 6 more
     in `tests/`. Five
     of the eleven fail **silently** rather than raising: the `vars(state)` walk
     in `sph.py` would simply find no `mat_*` dict and report every SPH density
     as 0.0. A 163-deck corpus sweep (all `SET_*_ADD` / SPH / TSHELL carriers in
     `C:\openradioss_run` and the `dynaexamples` tree, 0 errors) reached **0
     decks** for four of those sites and 1 deck for two more; the test suite
     reaches them with 5-9 hits from a single file. A zero-mover byte-identity
     sweep therefore *cannot* prove the migration safe.

  Cost side, for the record: **~4 200 field-access sites over ~78 files** —
  counted by AST, as any `state.<f>` / `st.<f>` whose `<f>` is one of the 352
  declared fields, which gives 4 170 sites in 78 files (`k2rad/` 2 977,
  `tests/` 1 112, `tools/` 81); widening the receiver set to every plausible
  alias gives 4 282 over 79. `tests/` and `tools/` are not covered by CI's
  `files = ["k2rad"]` and would break only at runtime. Add **362 prose
  references** to `state.<declared field>` that no mechanical rewrite touches —
  counted over the same file set by tokenizing each module and keeping only
  `COMMENT` and `STRING` tokens (107 in comments, 159 in docstrings and
  strings) plus a regex over every `*.md` (96) — plus a new CST dependency.
  A blind regex is ruled out because most attribute sites named after a state
  field have some other receiver: by the same AST method, **203 of 437**
  `.nodes` sites and **1 380 of 1 534** `.warnings` sites are on an object that
  is not `state`/`st` (a whole-file regex over the same set gives 208 of 477
  and 1 382 of 1 537 — the case holds under either method).

  **The flat-but-sectioned shape is the design.** What would reopen this:
  (a) `state.py` passing ~600 fields or ~15 000 lines, where navigation cost
  starts to dominate; (b) a second consumer that needs a *subset* of the state
  passed independently (e.g. a back-end taking only mesh + materials); (c) the
  dynamic-access sites falling to ≤ 2 and the corpus growing decks that exercise
  every one of them; (d) a measured mypy or IDE benefit the flat shape provably
  cannot give. Whoever does reopen it should first make the three remaining
  `getattr(state, "literal", default)` calls direct attribute reads, so a rename
  fails loudly, and give `sph.py`'s `vars(state)` walk an explicit registry —
  otherwise the refactor's first symptom is wrong physics at zero diagnostics.
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

- Rigid-body inertia & load distribution (P1): `*PART_INERTIA` and
  `*CONSTRAINED_NODAL_RIGID_BODY_INERTIA` → `/RBODY` `Mass`/`Jxx..Jxz` with
  `ICoG=4` (the one flag that means "defined rather than calculated from the
  mesh"), the main node placed at `NODEID`/`XC,YC,ZC`, `IRCS=1` routed through
  `Skew_ID`, and card 5 `VTX..VRZ` → `/INIVEL/TRA` + `/INIVEL/ROT`;
  `*PART_CONTACT` `OPTT` → the `/PART` `Thick` column; and
  `*CONSTRAINED_INTERPOLATION[_LOCAL]` → `/RBE3` + one `/GRNOD/NODE` per
  weight/DOF group — **done** (starter-validated, 0 ERROR; the products of
  inertia transfer VERBATIM because both sides hold the tensor component, and
  several dyna2rad defects were fixed rather than reproduced: its `/RBE3` is
  unusable (`ERROR 78`/`760`, weights lost), its `NODEID` main-node position is
  discarded, its `ICoG=1` fallback lands the node on the global origin, and it
  rotates a global tensor when a CNRB carries `CID` with `IRCS=0`. See
  CHANGELOG).
  Still open: **`*ELEMENT_INERTIA`**, which Vol I Appendix X pairs with these two
  and which the shared `_read_rigid_inertia` walker could serve directly; merging
  a `*PART_INERTIA` slave into a `*CONSTRAINED_RIGID_BODIES` master (the merged
  body's total mass/inertia about the merged centre of mass is not derivable from
  the two cards, so it is warn-dropped); `DRFLAG`/`RRFLAG` per-node DOF releases
  (the M2 item — still warn-dropped, as in dyna2rad); the `_OVERRIDE`
  (`ICNT`/`IBAG`/`IPSM`) and `_THERMAL` (`IDTHRM`) CNRB cards; `*PART_REPOSITION`;
  a `*PART_CONTACT` `SFT`/`SSF` route (the per-side `Igap=5` + `THICK_S`/`THICK_M`
  pair is radioss2026-only) and `FS=-1` resolved from the per-part coefficients
  rather than warned; and `*CONSTRAINED_INTERPOLATION`'s per-component
  `TWGHTY..RWGHTZ` and `_LOCAL` `CIDD`, neither of which `/RBE3` can express.
  Also open: **`OPTT` is warned but not routed**. It reaches the `/PART` `Thick`
  column and Radioss reads it only for interfaces with `Igap >= 1`
  (`i7sti3.F:222`), while k2rad's plain `/INTER/TYPE7` is `Igap = 0` — measured
  inert, +0.089 % against the prediction once the `Igap` column alone is patched
  to 1. Raising `Igap` on a TYPE7 whose scope includes an `OPTT` part would need
  the part→interface map the writer does not build today (`_make_parts_and_
  elements` runs before `_make_interfaces`), so the converter names the problem
  instead. Likewise `OPTT` on a SOLID part: the starter has no `NUMELS`
  `THK_PART` loop, so there is nothing to route it to.
- `*MAT_SPOTWELD` (100) — **done** as /PROP/TYPE13 (SPR_BEAM) connectors; the
  cfg shows LAW59 binds to /PROP/TYPE43 connection solids, so the spring route
  is correct. Validate on a single-weld coupon. Original note: — needs new
  `/MAT/LAW59` + `/PROP/TYPE13` machinery and single-weld pull/shear validation.
- `*ELEMENT_DISCRETE` + `*MAT_SPRING_*` / `*MAT_DAMPER_*` -> /PROP/TYPE4 —
  **done** (S01/S02/S03/S04/S05/S06/S08; grounded springs; `VID`-oriented →
  `/PROP/TYPE8`; `DRO=1` torsional → DOF 4 of a `/PROP/TYPE13` or `/PROP/TYPE8`;
  only `IOP=1/3` orientations stay warn+skip). Original note: — reuses the
  grounding-spring `/SPRING` template, but the `/PROP/TYPE4` card layout and the
  orientation/torsional (`VID`, `DRO=1`) cases need pinning before shipping.
- Discrete spring/damper + discrete-beam materials (P1): `*MAT_S03/S05/S06/S08`
  on `*SECTION_DISCRETE`, and `*MAT_066/067/068/071/074/119/121/196` on a
  `*SECTION_BEAM` `ELFORM=6` → 6-DOF `/PROP/TYPE8` (skew oriented) or
  `/PROP/TYPE13` (node oriented) `/SPRING` connectors — **done**. k2rad emits
  the PROPERTY-driven twin of dyna2rad's `/MAT/LAW108`//`LAW113` + `/PROP/TYPE23`
  pair: identical card bodies and identical frame builders, no `MID`-on-TYPE23
  rule to satisfy. `*MAT_069/070/093/094/095/097/146` have no Radioss spring law
  and warn-drop to an inert connector naming what is lost. See CHANGELOG for the
  dyna2rad defects reproduced vs. corrected, and for the 15 defects the
  review round found in k2rad's own first pass.
  `*DATABASE_DEFORC` / `*DATABASE_DISBOUT` → `/TH/SPRING` over the converted
  connectors, one group per card, `PF=1` honoured — **done**; both dts also join
  the `/TFILE` minimum. Still open on this family: `*DATABASE_HISTORY_DISCRETE`
  has no handler, so a deck that uses it to narrow the deforc selection gets a
  `/TH/SPRING` listing every converted connector (a superset — the emitted
  warning says so when the card is present).
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
- Adhesives / cohesive batch (P1): `*MAT_COHESIVE_MIXED_MODE` (138) →
  `/MAT/LAW117`; `*MAT_ARUP_ADHESIVE` (169) → `/MAT/LAW169` (radioss2025
  card, non-fatal WARNING 100211 under /BEGIN 2022); `*MAT_COHESIVE_MIXED_-`
  `MODE_ELASTOPLASTIC_RATE` (240) → `/MAT/LAW116`;
  `*MAT_TOUGHENED_ADHESIVE_POLYMER` (252) → `/MAT/LAW120` (TAPO);
  `*MAT_ADD_DAMAGE_DIEM` → `/FAIL/INIEVO`; cohesive `*SECTION_SOLID`
  ELFORM ±19/20/±21/22 (+ `_MISC` COHTHK) and the SOLID_COHESIVE material
  route → `/PROP/TYPE43` (CONNECT) — **done** (starter-validated 0 ERROR(S)
  + engine-validated traction-separation/energy/rate physics on 13 decks to
  <0.1 % of the analytic targets; several dyna2rad defects fixed rather
  than reproduced — the MAT_240 EDOT_G2 and T0/S0 rate gates, the Idel
  collapse, the MAT_252 dead JCFL/DOPT branches — see CHANGELOG). Still
  open in this family: `*MAT_ADD_COHESIVE` (wrap an ordinary material into
  a cohesive element — no Radioss counterpart), cohesive SHELLS
  (`*SECTION_SHELL` ELFORM 29 — Radioss has no cohesive-shell element,
  warned naming starter ERROR 3046), the DIEM `Q4` element-size evolution
  regularization (initiation-side `P5` → `TAB_EL` does carry over), and
  `*MAT_240`'s `_THERMAL`/`_3MODES`/`_FUNCTIONS` variants (curve-valued
  cards / mode III — no LAW116 slots, warn-skipped).
- Impact / blast materials batch (P1): `*MAT_JOHNSON_HOLMQUIST_CERAMICS` (110)
  → `/MAT/LAW79` (JOHN_HOLM, JH-2); `*MAT_JOHNSON_HOLMQUIST_CONCRETE` (111) →
  `/MAT/LAW126` (radioss2024 card, non-fatal WARNING 100211 under /BEGIN 2022);
  `*MAT_ELASTIC`'s `_FLUID` option (1) → `/MAT/HYD_VISC` (LAW6) +
  `/EOS/POLYNOMIAL` of the same id — **done**. Nothing is normalized on
  conversion: σ_HEL = 1.5(HEL−PHEL), T\* = T/PHEL and P\* = P/PHEL for JH-2,
  and P\*/σ\*/T\* = ·/f′c for JHC, are all re-derived by the Radioss
  starter/engine with the identical definitions LS-DYNA uses, so the strength
  constants stay dimensionless and HEL/PHEL/T/FC stay physical stresses;
  `K1/K2/K3` are each law's own polynomial pressure law, so neither emits an
  `/EOS`. Guards the starter itself lacks are supplied by the converter
  (`PHEL ≤ 0`, whose only check is `PHEL > HEL`; LAW126's unguarded
  `k0 = PC/MUC` and `h = (PL−PC)/MUL`, a silent NaN at 0 ERROR / 0 WARNING;
  `EPS0 ≤ 0` with `C ≠ 0`, fatal ERROR 910 on LAW79), and several dyna2rad
  defects are corrected rather than reproduced — the `_FLUID` `K == 0`
  fallback's lost Poisson ratio (its expression's `NU` token never resolves,
  so it computes `E/3`), the `K < 0` zero-sound-speed fluid, the verbatim `VC`
  copy into a slot that means kinematic viscosity rather than a dimensionless
  coefficient, the defaulted `CP = 1e20` landing on a finite `Pmin`, and the
  missing `*MAT_001_FLUID` alias (which there yields no `/MAT` at all) — see
  CHANGELOG. Still open in this family: `*MAT_110`'s `FS` failure flag, which
  is **not expressible under /BEGIN 2022** because LAW79's `IDEL`/`EPSMAX` are
  radioss2023 fields — it is warn-dropped naming the `*MAT_ADD_EROSION`
  remedy. A `/BEGIN` bump is the direct route (LAW79's `Fcut` and LAW126's
  `IFAILSO` and Cowper-Symonds `CT/POWT/CC/POWC` card are gated the same way,
  at 2023 / 2025 / 2026), but not the only conceivable one: `/FAIL` cards are
  version-independent, so `FS > 0` could in principle be auto-emitted as one.
  Neither candidate is a clean drop-in, which is why it was not done —
  `/FAIL/GENE1`'s `Eps_eff` is built from the TOTAL deviatoric strain
  (`fail_gene1_s.F:278-279`), not the plastic strain LAW79's `IDEL=2` uses,
  and a `/FAIL/JOHNSON` with `D2..D5 = 0` would need its own validation.
  LS-DYNA `VC`'s ΔL·a factor, which is
  per-element and cannot be resolved at material-conversion time; an explicit
  `CP = 0.0`, since `Pmin = 0` is Radioss's no-cutoff sentinel. *(The other
  blocker named here — `*SECTION_SPH` / `*ELEMENT_SPH`, "which k2rad does not
  support at all, so the W11 bird-strike fluid converts its material but still
  has no property" — is closed by the SPH batch below; that deck now emits all
  18 795 particles on a `/PROP/SPH` and reads back `0 ERROR(S) 0 WARNING(S)`.)*
- Spotweld joining (P1): `*CONTACT_SPOTWELD` (+ `_WITH_TORSION` /
  `_BEAM_OFFSET` / `_CONSTRAINED_OFFSET` / `_PENALTY` / `_MPP`) →
  `/INTER/TYPE2` Spotflag=28 with `Ignore=2` and `Idel2=1`;
  `*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N]` → `/GRBRIC/BRIC` + `/CLUSTER/BRICK`;
  `*DATABASE_SWFORC` → `/TH/SPRING` + `/TH/BRIC` + `/TH/CLUSTER` — **done**
  (starter-validated, 0 ERROR(S); the secondary side is resolved over BEAM nodes
  so the `SSTYP=3` weld part actually resolves, and the `/CLUSTER` exponents are
  quadratic where dyna2rad's are linear — see CHANGELOG). Original note: — the
  W16/W17 sheets are node-disjoint without it, so the weld force is 0.
- Eroding / node-to-surface contact + friction batch (P1):
  `*CONTACT_ERODING_{SINGLE_SURFACE,SURFACE_TO_SURFACE,NODES_TO_SURFACE}` and
  `*CONTACT_{,AUTOMATIC_}NODES_TO_SURFACE` (each also `_MPP`) →
  `/INTER/TYPE25` at ILEV 1/2/3, plus `*DEFINE_FRICTION` → `/FRICTION`
  (`Ifric=2` Darmstad, bound through `fric_ID`) — **done**. These were the only
  unhandled `*CONTACT_` spellings left in the corpus (W11 bird-strike, W9
  missile). The batch's defining decision is `/SURF/PART/ALL` for the solid
  side of an eroding contact: it is the only way `/INTER/TYPE25`'s dormant
  interior-segment mechanism can re-expose a face when the brick behind it
  dies, and dyna2rad never enables it. Still open: `ISYM=1` (no `/SURF`
  equivalent for "drop symmetry-plane faces"), the LS-DYNA `VC` shear-stress
  friction cap (Radioss `VIS_f` is a different quantity), `FS=2`
  (`*DEFINE_TABLE` μ(p, v) — no Radioss construct; now `Fric=0` + a loud
  warning rather than a literal μ=2.0), `FS=-1` resolved from `*PART_CONTACT`
  rather than warned (the per-part `FS`/`FD`/`DC`/`VC` are now PARSED — see the
  rigid-inertia batch in Tier 2 — but folding them into an interface still needs
  a per-pair `/FRICTION` table, since Radioss has no per-part friction),
  per-side `SST`/`MST` on a TYPE25 (the `Igap=5` +
  `THICK_S`/`THICK_M` route is radioss2026-only), a per-contact `IADJ=0` (only
  the global `--eroding-surf-ext` exists), a `*SET_SEGMENT` / `*SET_SHELL`
  contact side (only the part and part-set forms resolve), and
  `*DEFINE_FRICTION_ORIENTATION` (which is what would make `/FRICTION` `Idir`
  non-zero).
- The plain, non-`AUTOMATIC` `*CONTACT_SURFACE_TO_SURFACE`,
  `*CONTACT_SINGLE_SURFACE` and `*CONTACT_ONE_WAY_SURFACE_TO_SURFACE`
  spellings are still unhandled and land in `skipped_keywords` — a contact that
  silently vanishes. Their card stacks are identical to the `_AUTOMATIC_` ones
  already handled, so this is an aliasing job, not a new conversion. Not in the
  reference corpus, which is why the eroding batch did not surface it.
- `*CONTACT_..._TIEBREAK` (all 15 spellings × `_MPP` = 30 keys) →
  `/INTER/TYPE2` —
  **done**. The old "no open-source equivalent found" note is **refuted**:
  `/INTER/TYPE2` Spotflag 20/21/22 + `Rupt` is a fully implemented bond with
  rupture on this build (`hm_read_inter_type02.F:343`, `ruptint2.F`,
  `int2rupt.F`). What is genuinely *not* expressible, and is warn-dropped by
  name, is a STRESS-triggered release: OpenRadioss releases on displacement
  only, so only `OPTION 6`/`8` — whose `PARAM` is that distance — convert with
  their failure intact. Still open, all named in the per-interface warnings:
  the quadratic *interaction* between the normal and shear criteria (Radioss
  caps the two components independently); `OPTION 5`'s `SFLS` σ(gap) curve,
  which would map onto `fct_IDsn` verbatim but supplies no release distance;
  the force-based `NFLF`/`SFLF` of the `TIEBREAK_NODES` family, which would
  need each secondary node's tributary area from `i2surfs.F`; the `*SET_NODE`
  `DA1..DA4` and `*SET_SEGMENT` `A1`/`A2` per-entity overrides (recorded and
  named only when the deck states one — the `*SET_SHELL` spelling of the same
  override, p.11-72 Remark 1, is not recorded, because a `SURFA` on a shell
  element set resolves to no nodes at all today and the whole record is dropped
  by name first); and the
  `MORTAR` / `_USER` / `OPTION 9/11/13/14` cohesive laws, which have no
  counterpart of any kind.
  SETTLED by the SIDE-DEFECT batch: no `_ONLY` spelling can ever reach the
  rupture path, and the reason is the LS-DYNA CARD GRAMMAR rather than this
  converter's mapping. Vol I R17 p.11-14/15 enumerates the family exhaustively
  and exactly two of the eleven spellings contain `ONLY`, taking Card 4:
  TIEBREAK_NODES (a FORCE criterion) and Card 4: TIEBREAK_SURFACE (a STRESS
  criterion); neither card has a length field, and `PARAM`/`CCRIT` lives only
  on Card 4: AUTOMATIC_..._TIEBREAK, mandatory for four spellings none of which
  has an `_ONLY` variant. Same in R16. The defensive `if c.only:` branch is
  removed and its semantics kept as prose.
- `*CONTACT_AUTOMATIC_GENERAL` `SOFT`-sentinel routing (`-7`→TYPE7, `-11`→TYPE11
  edge-to-edge with synthesized `/LINE/SEG`|`/LINE/SURF`, `-19`→TYPE19; default →
  single-surface) — **done** (dyna2rad `convertcontacts.cxx` cc:133-164).
- `*CONTACT_TIED_SURFACE_TO_SURFACE[_OFFSET]` routing
  `(SFST*SST + SFMT*MST)/2 < 0` → `/INTER/TYPE10` penalty tie (else TYPE2) —
  **shipped, but PRAGMATIC rather than faithful** (the rule is dyna2rad's,
  cc:220; dyna2rad is a peer, never an authority). The two things it used to be
  justified with are false at the LS-DYNA source and the arm that runs has a
  measured cost — see `writer/contacts._tied_interface_type` for all of it, and
  the round-3 entry below.
- `*INITIAL_STRESS_SHELL` / `*INITIAL_STRESS_SOLID` -> /INISHE + /INISH3 /
  /INIBRI — **done** (the GLOB flavours, layer-count checks per the starter
  readers). The 3-node half landed in the SIDE-DEFECT batch: the `/INISH3`
  card is the SAME layout as the `/INISHE` one, and `npg` is the only
  difference — 1 there against 4 on a quad, because a `/SH3N` written with
  `Ish3n = 0` is initialised through `c3init3 -> CSIGINI`, whose check is
  `NPGI > 1` rather than `NPG /= NPGI`.
  Always GLOB: both keywords define their components in the global cartesian
  system (Vol I R17 p.28-98 / p.28-105) and neither card carries a local flag —
  `*INITIAL_STRESS_SHELL` card 1 is the eight fields `EID/SID NPLANE NTHICK
  NHISV NTENSR LARGE NTHINT NTHHSV` and nothing after them, so an ILOC read from
  cols 81-90 was a field LS-DYNA does not define (now reported + ignored).
  Original note: — the per-integration-point `/INISTATE` blocks are verbose and
  version-specific; the layer-count-must-match-property constraint and stress
  component/frame order need cfg validation.
- `*INITIAL_STRAIN_SHELL` (+ `_SET`) -> /INISHE/STRA_F/GLOB +
  /INISH3/STRA_F/GLOB — **done**. On a strain-ONLY deck it is written in the
  minimal form the starter consumes (`nb_integr=2`, `npg=1`, `Thick=0`, the two
  extreme through-thickness stations), because the reader keeps at most two
  stations and `npg=4` is a silent no-op on QEPH and ERROR 1904 on Ishell 1..4.
  On a deck that ALSO emits an initial-STRESS block — the shape LS-DYNA's own
  `dynain` writes — `ISIGSH` un-gates the starter's layer/Gauss cross-checks and
  `ITHKSHEL=2` pulls stress-only elements into the strain reconstruction, so the
  card instead carries `nb_integr` = the property N and a per-formulation `npg`,
  and every stress-carrying quad gets an all-zero companion record. A deck whose
  initial-state shells span two formulations is refused (warn + drop) rather
  than risk the reader's stale-`IHBE` payload shift. `/PROP/SHELL Istrain` is
  forced on as defence-in-depth (it sizes `GBUF%STRA`; the ingest itself is
  reached through `cstraini4.F`, which ignores the flag). `ILOCAL=1`
  warn-dropped (LS-DYNA calls it unsupported and the Radioss local card is a
  different quantity).
- `*INITIAL_STRESS_SECTION` -> /PRELOAD — **done**. A dedicated /SECT with
  three synthesized frame nodes realizes the cutting-plane normal (the
  REPORTING section's frame does so too since the SIDE-DEFECT batch — it used
  to pick the three best-conditioned mesh nodes, measured 90.00 degrees off on
  a +X plane with the origin off the plane entirely; the two sections stay
  separate because they carry different element groups and node scopes), the
  card's PSID is intersected with the
  cross-section's, and the LCID is resolved into `Preload`/`Tstart`/`Tstop`
  because the `Fct_ID` column only exists at /BEGIN 2026. Thick shells in the
  cut are named and left out of the preload group (no thick-shell initialiser
  calls SBOLTINI; LS-DYNA lists solid types only, Vol I R17 p.3145 Remark 4).
  Remaining loss: the ramp SHAPE (a step at `Tstart` instead), `IZSHEAR` and
  `ISTIFF`.
- `*INITIAL_AXIAL_FORCE_BEAM` -> /PRELOAD/AXIAL — **done**. Emitted at /BEGIN
  2022 (advisory WARNING 100211 only, restated), `Preload = SCALE`, the BSID
  split by emitted family into /GRBEAM/BEAM and the new /GRSPRI/SPRI, the
  curve truncated at its first descent. Remaining loss: `KBEND` (multi-beam
  bolt shanks lose LS-DYNA's internal constraints).
- Open, not in this batch: `*INITIAL_STRAIN_SOLID` / `_TSHELL`, and the
  `_SET` spellings of `*INITIAL_STRESS_SHELL` / `_SOLID` (unregistered, so
  they land in skipped keywords; `_split_keyword` keeps `_SET` in the base
  name, so they are NOT misparsed as the plain form — their offset bucket
  would be IDSOFF, not IDEOFF).
- **Closed by the SIDE-DEFECT batch:** the `_OFFSET_SPECS` gap on
  `*INITIAL_STRESS_SHELL`/`_SOLID` (walker-driven rows now, from the same
  walkers the handlers use), and `/INISH3/STRS_F`, which turned out to be the
  SAME card layout as `/INISHE/STRS_F` — the standing note that "the card
  layout differs" was false. Only `npg` differs, and in the opposite
  direction: 1 on a `/SH3N` (`csigini.F:143` refuses `NPGI > 1`) against 4 on
  a quad. A record naming a shell with fewer than 3 distinct corners is still
  dropped before the block is built, for the original `ISIGSH`-arming reason.

*Rationale:* these are the recurring building blocks of automotive crash decks;
covering them unlocks a large class of real models.

### Tier 3 — large subsystems (dedicated milestones)

- Composites: `MAT_54`/`MAT_55` → `/MAT/LAW127`, `MAT_002` → `/MAT/LAW93`,
  `MAT_022` → `/MAT/LAW25` (COMPSH) + `/FAIL/CHANG` on shells and
  `/MAT/LAW127` on solids/thick shells (Milestone 2 batch 1 — the failure
  criteria are term-for-term identical at `ALPH = 0`, with `Sigma_1c` left
  blank because MAT_022 has no compressive-fibre mode; `KFAIL`, `MACF`,
  `ATRACK` and the `SN`/`SYZ`/`SZX` delamination criterion are warn-dropped by
  name), `MAT_037` → `/MAT/LAW43`, `MAT_032` → a `/MAT/PLAS_BRIT` pair, and the
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
  **Thick shells are done** as well: `*ELEMENT_TSHELL` (+ `_BETA` /
  `_COMPOSITE`) → `/BRICK` with the connectivity copied 1:1 and `Icstr = 010`
  carrying the thickness direction, and `*SECTION_TSHELL` → the three-way
  `/PROP/TYPE20` / `TYPE21` / `TYPE22` split, plus `*PART_COMPOSITE_TSHELL` →
  a real `/PROP/TYPE22` with per-ply `mat_IDi` / `ti/t` / `Phi_i` (dyna2rad
  emits the thin-shell `/PROP/TYPE51` sandwich there and its own starter
  refuses it on the bricks, ERROR 60 + 226). Starter-validated on all nine r14
  thick-shell decks (0 ERRORS each) plus fourteen hand-built TYPE21/TYPE22 and
  edge-case decks, and quantitatively validated against Timoshenko beam theory,
  a thickness-direction discriminator, an orthotropic axis swap and a ply-order
  discriminator over 52 purpose-built decks.
  **Open follow-up, newly visible:** the r14 `*ELEMENT_TSHELL` decks are
  implicit-DYNAMIC simply-supported plates, and now that their mesh is no longer
  clamped by the free-node guard the OpenRadioss implicit engine DIVERGES on
  them (`MESSAGE ID 79`, `ISTOP=-2`) — not caused by the conversion (removing
  the injected contact stub and pinning the three in-plane rigid-body modes both
  leave it unchanged), and invisible before, because a fully constrained model
  has nothing to diverge about. Needs its own investigation; the starter is
  clean.
  **SPH is done** as well: `*ELEMENT_SPH` (+ `_VOLUME`) → `/SPHCEL` with the
  per-particle mass transferred exactly, `*SECTION_SPH` (+ four option
  spellings) → `/PROP/SPH` (TYPE34), `*CONTROL_SPH` `NMNEIGH` → `/SPHGLO` and
  `*DATABASE_HISTORY_SPH[_SET]` → `/TH/SPHCEL` screened the #106 way. The
  defining decision is WHERE the mass lives: a `/SPHCEL` row that carries its
  own mass makes Radioss derive that particle's smoothing length from it and
  IGNORE the property's, so a section whose particles all share one mass states
  it once as `/PROP/SPH` `Mp` — exact total AND the deck's own `h` — while
  anything else keeps the per-cell masses and reports the smoothing-length ratio
  in numbers. Starter-validated on the converted r14 `foam.k` (per-part mass
  echo `2.26408800E-04` = 1000 x 2.264088e-07 exactly, no `WARNING 138`), r14
  `boot.k` and W11 (both `0 ERROR(S) 0 WARNING(S)`); corpus sweep 528 decks,
  501 byte-identical, the 27 that moved are exactly the SPH ones.
  The **review round** then closed five defects that each produced a deck the
  starter refuses or silently mutilates: the `*INCLUDE_TRANSFORM` particle-card
  rewriter read a fixed slice where the handler splits on whitespace (100 % mesh
  loss on an I10 include, now self-checked against the handler's own parse);
  `*DATABASE_HISTORY_SPH[_SET]` had no offset spec, so its channels attached to
  the PARENT deck's particles; an all-blank-mass section reproduced the `Mp = 1`
  fabrication the batch exists to prevent (now `rho x d_ref^3`, reported as
  `MASS INVENTED:`); a `*SECTION_SPH` sharing an id with another family's card
  emitted a second `/PROP` (starter `ERROR 79` — closed on both sides, plus a
  deck-wide duplicate-`/PROP`-id scan that also catches the pre-existing
  non-SPH cases); and the provisional-element screen shared one flat id set
  across families, deleting valid particles at the intersection. Plus the
  `*MAT_PLASTIC_KINEMATIC` re-route below.
  **Open follow-up, newly visible:** r14 `bar-iv/taylor1.k` loses `*NODE` 5 and
  7 (and gains a phantom node 0) to a PRE-EXISTING free-format `*NODE` parse
  defect — `       5-1.000000000E+01-1.000000000E+01 0.000000000E+00       7 0`
  glues NID+X+Y into one token — which is unrelated to SPH (it reproduces on a
  four-line deck with no SPH keyword at all) but now surfaces as starter
  `ERROR 78` because the deck's solid element finally has particles to run
  beside. Worth its own fix.
  Still open in the SPH family: `*BOUNDARY_SPH_SYMMETRY_PLANE` / `_FLOW` /
  `_NOFLOW` and `*SPH_SYMMETRY_PLANE` → `/SPHBCS`, `*DEFINE_SPH_*` injection /
  massflow / active region → `/SPH/RESERVE` + `/SPH/INOUT`,
  `*DEFINE_ADAPTIVE_SOLID_TO_SPH` → `/PROP/SOLID` `Nsphdir`, the anisotropic
  `*SECTION_SPH_ELLIPSE` smoothing lengths (Radioss carries one scalar `h`), and
  `HMIN`/`HMAX` bounded dilatation, which needs `h_1D = 3` plus a
  radioss2026-only bounds card that a `/BEGIN 2022` reader discards SILENTLY —
  a `/BEGIN` bump is the direct route there, exactly as for `*MAT_110`'s `FS`.
  Also open: hybrid SPH<->FE coupling via `*CONSTRAINED_LAGRANGE_IN_SOLID`.
  **Material compatibility is a general gap, not an SPH one.** The SPH batch
  closed exactly one case — `*MAT_PLASTIC_KINEMATIC` re-routes from `/MAT/LAW44`
  (not SPH-declared, `ERROR 3046`) to `/MAT/LAW2` when the material has no
  Cowper-Symonds term and no effective kinematic hardening, cloning the `/MAT`
  when it is shared with non-SPH parts — which is what made r14 `bar1.k` and
  `bar2.k` start. Every other law outside `_SPH_COMPATIBLE_LAWS` is still only
  WARNED about. The same shape exists for the other element families
  (`check_mat_elem_prop_compatibility.F` has a `CASE` per element type), and a
  general "is this law legal on this element family, and is there an equivalent
  that is" table would subsume all of them.
  Still open in this family:
  the `*INTEGRATION_BEAM` standard shapes needing three or more dimensions
  (`Isect ≥ 10` with `L3..L6` needs `/BEGIN ≥ 2024`, and k2rad writes 2022 —
  either bump the version declaration for the whole deck or expand the shape to
  explicit integration points, which means writing the 19 shape geometries
  k2rad currently defers to the starter), a beam rule's per-cell `PID_i`
  (`/PROP/TYPE18` has a single material column), a rule on a
  `*MAT_ELASTIC` part (Radioss bans LAW1 from every layered shell property and
  from `/PROP/TYPE18`, so this needs the material re-stated rather than
  converter work), the named `SECTION_nn` standard section on
  `*SECTION_BEAM` card 2b (reported, not converted — on ELFORM 3 the resulting
  zero-area `/PROP/TYPE2` is refused rather than emitted as starter ERROR 497),
  the per-element
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
  "keep the mesh, warn about the rest"), and `*ELEMENT_BEAM_OFFSET`
  eccentricities (would need synthesized rigid links).
  `*ELEMENT_SEATBELT*` is **done** — see the Tier-3 Seatbelts entry.
- `*CONSTRAINED_JOINT_*` (revolute/spherical/… joints) → `/PROP/TYPE45`
  (KJOINT2) + `/SPRING` + a node-derived `/SKEW/FIX`, plus
  `*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED`/`_TRANSLATIONAL` DOF blocks —
  **done** (dyna2rad-faithful type integers and axis conventions, with its
  documented field-map defects corrected; see CHANGELOG).
- `*AIRBAG_*` → `/MONVOL` — **batch 1 done**: the five uniform-pressure models
  (`_SIMPLE_PRESSURE_VOLUME` → `/MONVOL/PRES`, `_SIMPLE_AIRBAG_MODEL` →
  `/MONVOL/AIRBAG1` + `/MAT/GAS` + `/PROP/INJECT1`, `_ADIABATIC_GAS_MODEL` →
  `/MONVOL/GAS`, `_LOAD_CURVE` → `/MONVOL/PRES`, `_LINEAR_FLUID` →
  `/MONVOL/LFLUID`), `*MAT_FABRIC` → `/MAT/LAW19`+`/PROP/TYPE9` or
  `/MAT/LAW58`+`/PROP/TYPE16`, both reference-geometry keywords → `/XREF` /
  `/EREF`, `*CONTACT_AIRBAG_SINGLE_SURFACE` and `*DATABASE_ABSTAT` →
  `/TH/MONV` (see CHANGELOG).

  **Batch 2 done**: `*AIRBAG_HYBRID[_JETTING][_CM]` → `/MONVOL/AIRBAG1` with
  `N_gases > 1` and one `/MAT/GAS/MOLE` per species,
  `*AIRBAG_PARTICLE[_MPP][_DECOMPOSITION][_MOLEFRACTION/_INFLATION/_JET][_SEGMENT][_TIME]`
  → `/MONVOL/FVMBAG2`, and `*AIRBAG_INTERACTION` → `/MONVOL/COMMU1` on both
  bags with reciprocal `Nbag` rows (a keyword dyna2rad does not convert at all).
  With them: the multi-row injector, the mole-fraction mixture rule, **named
  vent-hole surfaces** (`surf_IDv` — the batch-1 deferral, built from the vent
  part and screened as a subset of the bag surface, with `*AIRBAG_HYBRID`'s
  documented outside-the-bag `A23 < 0` case frozen to an absolute area),
  `PVENT`/`PPOP` pop-open thresholds, the `SD1 \ SD2` internal-surface split
  and the `NORIF` inflator-nozzle surface. `/TH/MONV` gained `COMMU1` and
  `FVMBAG2` rows, the latter restoring `DTBAG`/`NFV`/`UPCRIT`. See CHANGELOG
  for the eighteen decisions, the review round's fourteen fixes, the
  verification round's six housekeeping items and the six documented
  deviations from dyna2rad.

  **Not converted by batch 2, and now warn-dropped by name rather than
  mis-read**: `*AIRBAG_HYBRID_CHEMKIN` (a model of its own, with its own card
  stack) and the `_JETTING` **jet itself** — its geometry reads but `Ijet = 1`
  obliges three pressure functions LS-DYNA supplies no scale for, and a zero id
  in any of them is starter `ERROR 12/13/14`. Both are batch-3 candidates.

  **Open for batch 3:**
  - `*AIRBAG_WANG_NEFSKE*` — a `/PROP/INJECT1` per inflator gas plus one
    vent-hole block per orifice. Registered and warn-dropped today. The
    injector and vent machinery batch 2 built is what it needs; what is missing
    is the orifice card stack and its own temperature model.
  - **The fabric porosity family** (`*MAT_FABRIC` `FLC`/`FAC`/`FVOPT` → an
    `Nporsurf` block or `/LEAK/MAT`). Batch 2 deliberately did NOT take this:
    the porous-surface layout is documented for `/MONVOL/COMMU1` (type 9) only,
    and there the reader discards `surf_IDps`, `Iblockage` and both functions
    whenever `Iformps == 0` (MEASURED). It also became the gate for
    `*AIRBAG_HYBRID`'s `OPT != 0`, which LS-DYNA routes to `*MAT_FABRIC`
    instead of to CP23/AP23 — so an `OPT != 0` bag currently loses its fabric
    leakage and says so. Doing this properly needs a probe run that pins the
    type-7 and type-11 porous layouts the way the card-format work pinned the
    type-9 one.
  - **`/PROP/INJECT2`**, for `*AIRBAG_HYBRID` with `LCIDM0` and for
    `*AIRBAG_PARTICLE_MOLEFRACTION`: one common mass-flow and temperature curve
    plus a per-gas molar fraction. Both spellings convert their per-gas curves
    as if they were mass flows today, which is wrong by the ratio of the total
    flow to each fraction — and both say so loudly.
  - **`/MONVOL/FVMBAG1` with an explicit `grbric_ID`**, the only finite-volume
    bag an open-source OpenRadioss build can actually run: `KMESH` resolves to
    1 only when the user supplies the brick mesh, which side-steps the
    `HYPERMESH_TETRA` stub FVMBAG2 dies on. Would turn
    `--airbag-particle-uniform` from the only runnable option into the fallback.
  - **The `_JETTING` jet**, as three real `/FUNCT` plus a defensible
    `FscalePt`. Two of the three have a source (`f_theta` from the cone
    half-angle `CA`; `f_t` and `f_delta` flat), but the jet PRESSURE does not:
    LS-DYNA derives it from the inflator mass flow and the Bernoulli
    efficiency `BETA` through a formulation Radioss does not share, and
    Radioss ADDS the jet on top of the uniform pressure, so an invented scale
    is an invented load. Needs a validated `BETA` → `FscalePt` derivation
    against a reference LS-DYNA run before it can be written.
  - **`*AIRBAG_HYBRID_CHEMKIN`** — card 3 `LCIDM LCIDT NGAS DATA ATMT ATMP RG`,
    card 4 `HCONV`, card 5 `C23 A23`, then a control card and several
    thermodynamic-property cards per species (Vol I R17 p.3-54). The Radioss
    target is `/MONVOL/AIRBAG1` with `Iform = 2` (Chemkin) on the vent holes.
  - **`*AIRBAG_PARTICLE_SEGMENT`'s `SEGSID`**, which narrows the monitored
    volume to a segment subset of SD1. Needs the `*SET_SEGMENT` →
    owning-shell resolution intersected with `SD1 \ SD2`; today the
    restriction is named and dropped, so the bag measures the whole of
    `SD1 \ SD2`.
  - The `*DEFINE_CPM_*` family — `_BAG_INTERACTION`, `_CHAMBER`,
    `_GAS_PROPERTIES`, `_NPDATA`, `_SWITCH_REGION`, `_VENT` (Vol I R17
    pp. 17-88…17-99) — registered and warn-dropped by name, each saying what
    the extended CPM input it carries would have done.
  - `*AIRBAG_ALE` / `_ADVANCED_ALE` / `_FLUID_AND_GAS` — still registered and
    warn-dropped; they need an ALE mesh and `/INTER/TYPE18` coupling.

  Three smaller ones recorded with them: `/MONVOL/GAS`
  `I_equi`/`Mini` are hard-wired to 0, which is what makes the `MASS` and `T`
  `/TH/MONV` channels structurally inert (making them settable would bring
  both channels back — note COMMU1 does NOT share this, it computes
  `MI = Pini*(VOL+VEPS)/(RMWI*TI)` unconditionally, which is why batch 2 keeps
  both channels there); a LAW58 loading slot whose own unloading twin IS stated
  still costs the hysteresis, because synthesizing it would feed
  `FUNC_INTERS`/`FUNC_INTERS_SHEAR` a pair that need not cross (`ERROR 1716`);
  and a reference-geometry BIRTH delay is inert whenever `ZEROSTRESS` is 0,
  since both fabric laws read the sensor only from inside that block — Radioss
  has no slot that holds both the delay and the pre-stress.
- `*DATABASE_CROSS_SECTION` → `/SECT` + `/TH/SECTIO` — **done** (_SET direct;
  _PLANE via a geometric straddle resolver; SECFORC → /TH/SECTIO).
- Seatbelts → `/SPRING` + `/PROP/TYPE23` + `/MAT/LAW114` and the four
  restraint devices — **done**: `*ELEMENT_SEATBELT` (1D → `/SPRING`, 2D →
  `/SHELL` on `/PROP/TYPE9` + `/MAT/LAW119`), `*SECTION_SEATBELT` →
  `/PROP/TYPE23`, `*MAT_SEATBELT`/`*MAT_B01` (+ both `_2D` spellings) →
  `/MAT/LAW114` or `/MAT/LAW119` routed by the PROPERTY the part carries,
  `*ELEMENT_SEATBELT_SLIPRING` → `/SLIPRING/SPRING`,
  `*ELEMENT_SEATBELT_RETRACTOR` → `/RETRACTOR/SPRING` with
  `*ELEMENT_SEATBELT_PRETENSIONER` folded onto its card 3,
  `*ELEMENT_SEATBELT_SENSOR` → `/SENSOR/ACCE|TIME|DIST`,
  `*ELEMENT_SEATBELT_ACCELEROMETER` → `/ACCEL` + `/SKEW/MOV` + `/ADMAS/0`,
  `*DATABASE_SBTOUT` → `/TH/SLIPRING` + `/TH/RETRACTOR`, and
  `*DATABASE_HISTORY_SEATBELT` split per element into `/TH/SPRING` /
  `/TH/SHEL` / `/TH/SH3N`. The force–strain curve crosses UNTOUCHED (both
  solvers read force vs engineering strain), the device anchorage node is split
  off the belt (`ERROR 2030`, which dyna2rad's verbatim `SBRNID` copy hits on
  any faithful deck), `SID1..SID4` become a `/SENSOR/OR` tree, and
  `/TH/RETRACTOR` is emitted at all — `grep -rn "TH/RETRACTOR"` over the whole
  reference converter returns zero hits. See CHANGELOG for the twenty decisions
  and the eight documented deviations from dyna2rad.

  **Not converted, and warn-dropped by name rather than mis-read**: a
  SHELL-belt slipring (`SBRNID < 0`) needs `*SET_SHELL_LIST` → `/GRSHEL` and
  `*SET_NODE` → `/GRNOD` scope resolution plus the starter's collinearity
  (`ERROR 2051`) and rigid-body (`ERROR 2081`) preconditions; a SHELL-belt
  **retractor** has no Radioss card at all. `SBSTYP` 2 and 5 (retractor
  pull-out rate / pull-out) and `SBPRTY` 2, 3 and 9 have no counterpart in the
  `/SENSOR` and `Tens_typ` families. `*ELEMENT_SEATBELT`'s `SLEN`, the
  slipring's `FUNCID`, the retractor's `DSID`/`LCFL`/`FLOPT`, the
  pretensioner's `LMTPIN` and the accelerometer's `IGRAV`/`INTOPT` are each
  named with the physics they cost.

  **Open for a batch 2:** the shell-belt device scope above (it is a set
  resolution plus three starter preconditions, not a card gap); `*SECTION_SHELL`
  `EDGSET` → the 2D belt's flow-direction `/SKEW/MOV` on the property's `Iskew`
  (without it the starter falls back to the shell edges when it builds the 1D
  springs, `GlobalModelSdi.cpp:2400-2412`); and `/INISPRI` initial unstretched
  lengths, which is the only way `SLEN` can be expressed at all — verified
  reachable: `rinit3.F:703-750` routes `IGTYP == 23` through `R8INI`, which
  sets `XL0` from the initial-state record, and `r23l114def3.F:274-278` then
  restores `X0 = XL0` at `TT == 0` instead of taking the geometric length.

  Also open, from the review round: `*SENSOR_SWITCH` has no converter, so the
  retractor's `LCFL` adaptive multi-level load limiter (a curve whose abscissa
  is a switch id) cannot be expressed even in part; and the `FORM = -14`
  coating gate on `*MAT_SEATBELT_2D` — LS-DYNA reads `ECOAT`/`TCOAT` only
  there, `/MAT/LAW119` has no such gate, and k2rad writes them through with the
  stiffness difference named rather than second-guessing the deck.

  From the post-review verification round, two whole-`/SPRING`-family gaps that
  the belt only made more visible:

  * **`*DATABASE_CROSS_SECTION_PLANE` could not cut a belt — DONE** in the
    SIDE-DEFECT batch. `_plane_cut` has a spring arm now, over
    `state.discrete_elems` and the 1-D `state.seatbelt_elems` (never over the
    nine-producer union `state.spring_elem_ids`, which is the #128
    regression), feeding the same `grsprg_ID` column the re-routed beams
    already used. Measured on the starter echo, master vs branch:
    `NUMBER OF SPRING ELEMENTS` 0 → 1 with the correct tail-side pack code.
    The `_SET` spelling's `DSID` and `TSID` are converted at the same time —
    they had been dropped with the stated reason "no converter-side element
    type", false on both counts. Note the PLANE path is now a deliberate
    SUPER-SET of LS-DYNA, whose Figure 16-2 caption excludes springs from the
    automatic definition; the warning says so with the element ids.
  * **`--auto-gapmin` still does not measure BEAM or `*ELEMENT_DISCRETE`
    clearance.** The 1D belt arm was added to `gapmin._part_nodes_map` in the
    verification round; those two families remain missing there for the same
    reason they always were.

  Also recorded, not a converter defect: **an implicit run of a 1D belt is not
  solving the belt.** `imp_glob_k.F` builds spring stiffness for `IGTYP` 4, 8,
  12 and 13 only and answers `SPRING ELEMENT PROP.TYPE = 23 IS NOT AVAILABLE
  FOR STIFFNESS MATRIX BUILDING, STIFFNESS IGNORED` for `/PROP/TYPE23`
  (MEASURED: the matrix collapsed from ND=18 NZ=27 to ND=6 NZ=3). k2rad now
  warns; the fix would have to be an engine one.

  **Not yet covered by a solver run**, so their correctness rests on the unit
  tests and the card-format sources alone: pretensioner `SBPRTY` 5/6/7/8
  (`Tens_typ` 1/3/4/5), the `/SENSOR/OR` gate a retractor gets when it names
  two to four lock sensors, `/SLIPRING/SHELL` and the 2D warn-drops, the
  slipring `FUNCID`/`LCNFFD`/`LCNFFS` friction curves and the orientation-node
  `A·γ²` term, and LAW119 `Ireload` / coating / `GAB`. The highest-value
  additions are `Tens_typ 4` (SBPRTY = 7, the additive pretensioner dyna2rad
  never produces) and the `/SENSOR/OR` gate, because both are places where
  k2rad deliberately exceeds dyna2rad.

*Rationale:* each is a self-contained subsystem with its own card family and
validation needs — sized as a milestone rather than an incremental add.

### Tier 4 — analysis-type extensions (ride the validated modal K-export chain)

The modal stiffness-export chain (`/IMPL/PRINT/STIF` → offline solve) is a
validated foundation for further linear analyses:

- **Linear buckling** (`Kφ = λ K_g φ`) — **done** for beam/rod/truss elements
  (`tools/modal_buckling.py`, Euler-validated to 0.001 %). "truss" there means a
  BEAM element used as an axial rod (`sec.area > 0`, second moments falling back
  to 0), not a Radioss `/TRUSS`; the two coincide because the R14 truss batch
  keeps ELFORM-3 elements in `state.beam_elems` and only branches at write time,
  so `tools/modal_common.py`'s three-family `collect` still sees them. Shells are now also
  **done** (consistent-membrane K_g, SSSS-plate-validated to 2.2 % at 8x8);
  a rigorous solid-element K_g remains open.
- **Harmonic / FRF output** — **done** (`tools/modal_frf.py`).
- **Thermal** — *partly done.* The RARE MATERIALS batch shipped the
  thermal-EXPANSION path plus the minimal temperature-driver foothold that makes
  it verifiable: `*MAT_ADD_THERMAL_EXPANSION` → `/THERM_STRESS/MAT` +
  `/HEAT/MAT` (with the material split a per-PART card on a shared MID needs),
  `*MAT_THERMAL_ISOTROPIC` via `*PART` TMID → the `/HEAT/MAT` values,
  `*INITIAL_TEMPERATURE[_SET|_NODE]` → `/INITEMP`, and
  `*LOAD_THERMAL_{CONSTANT,LOAD_CURVE,VARIABLE}[_NODE]` +
  `*BOUNDARY_TEMPERATURE[_SET|_NODE]` → `/IMPTEMP`, with `/TH/NODE TEMP` and
  `/ANIM/NODA/TEMP` gated on a real thermal solve. Engine-validated to −0.11 %
  on the free bar and −0.135 % on the clamped one against `α·ΔT·L`.
  The THERMAL SOLVER batch then shipped the heat SOURCES and the run controls:
  `*BOUNDARY_{FLUX,CONVECTION,RADIATION}_{SEGMENT,SET}` → `/IMPFLUX`,
  `/CONVEC`, `/RADIATION` (with the LS-DYNA flux SIGN FLIP and the
  `E = FMULT/σ_deck` emissivity de-scaling, both solver-measured),
  `*CONTROL_SOLUTION` SOLN=1 → the engine card `/DT/THERM`,
  `*CONTROL_THERMAL_SOLVER` TSF → `/THERM` and FWORK → `/HEAT/MAT` EFRAC,
  `*MAT_THERMAL_ISOTROPIC_TD[_LC]` → a least-squares line onto `/HEAT/MAT`'s
  `AS + BS·T` (which is the whole of its conduction — twelve operators, `stherm.F:106` and eleven siblings, read it and nothing else),
  `*MAT_THERMAL_ORTHOTROPIC` when it is isotropic in fact, and the eight
  `*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_{BEAM,SHELL,SOLID,TSHELL}`
  spellings → `/IMPTEMP` over the elements' own nodes.
  **Still open:** nothing in the thermal-solver scope that Radioss can express.
  What is left is inexpressible and named in the log: the implicit thermal
  controls (`*CONTROL_THERMAL_{TIMESTEP,NONLINEAR,FORMING,EIGENVALUE}` — Radioss
  has no thermal matrix and no nonlinear iteration, `tempur.F:48-55` is the whole
  integrator), view-factor / enclosure radiation
  (`*BOUNDARY_RADIATION_*_VF_*`, `_ENCLOSURE`), moving heat sources
  (`*BOUNDARY_FLUX_TRAJECTORY`), the welding material `*MAT_THERMAL_CWM`, the
  per-section temperature GRADIENTS
  (`*LOAD_THERMAL_VARIABLE_{BEAM,SHELL}[_SET]` — `/IMPTEMP` carries one value
  per node) and the external-field loads
  (`*LOAD_THERMAL_{RSW,D3PLOT,BINOUT,TOPAZ}`).
  **One thermal spelling class is deliberately NOT named yet:**
  `*CONTACT_*_THERMAL` (measured on the corpus:
  `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR_THERMAL` and
  `*CONTACT_TIED_SURFACE_TO_SURFACE_THERMAL` are still in
  `skipped_keywords`). These are CONTACT cards whose base interface k2rad DOES
  convert; registering them as thermal warn-drops would lose the mechanical
  contact too, which is worse than the present silence. The right fix routes
  them to the contact handler and names only the interface-conductance loss —
  a contact-side change with its own regression surface, so it belongs to a
  contact batch, not this one.
  **Measured limits that remain.** (a) A `*MAT_ELASTIC` shell is restated as
  `/MAT/LAW36` so it CAN expand, but a material shared between shell and solid
  parts is left on LAW1 and its expansion stays inert on the shells. (b) The
  solid expansion path diverges when a run of elements is free to TRANSLATE
  laterally as a group — the cure is one lateral anchor per cross-section (an
  end clamp is NOT the trigger). (c) In a COUPLED run Radioss never computes a
  thermal stability step at all (`dttherm.F90` and `mqviscb.F:644` are both
  gated on `IDT_THERM == 1`), so the temperature is integrated at the MECHANICAL
  step with no thermal check — safe only because that step is normally far
  smaller. (d) In a THERMAL-ONLY run (`/DT/THERM`) the step IS computed, but
  from conduction alone: a stiff `/CONVEC` or `/RADIATION` diverges silently
  under NORMAL TERMINATION, which k2rad screens for and prescribes a scale
  factor against — scaled by the loaded-face concentration counted from the
  emitted deck, because a body a few elements thick loaded on several sides is
  faster than `RHO0_CP·Lc/h` by that factor. The prescription is a MONOTONE
  step, not merely a stable one: measured on a six-face coupon, the unscaled
  0.25·τ is stable and lands the heat balance at 2527.6994 vs an analytic
  2527.7000 while its FIRST step goes 300 → 1350 K against a 1000 K
  environment, so the heat balance alone does not reveal an oscillating
  transient — the warning says to read the temperature history too. (e) `*CONTROL_THERMAL_SOLVER`'s `EQHEAT` has no counterpart,
  so a deck whose mechanical and thermal units are NOT consistent converts with
  its strain-energy-to-heat conversion off by exactly `EQHEAT`. (f) An IMPLICIT
  run integrates NO temperature at all on this build — measured, a twin pair of
  converted decks carries its far end 300 → 400.000 K explicitly and stays at
  exactly 300.000 K under `/IMPL/*` with `HEAT STORED = 0.0000000` — so the
  TEMP output channels and the engine thermal cards are named and left out
  there. The mechanism is `resol.F:6547`: inside `IF (IMPL_S == 1)` a
  `GOTO 111` jumps to the label at `:7949` and skips the block opened at
  `:6552` that holds the one and only `CALL TEMPUR` (`:6736`), which is the
  whole integrator and the only writer of `HEAT_STORED` (`tempur.F:51-58`).
  The SOURCE routines are NOT skipped — `resol.F:1802/2994/3006/3025` carry no
  `IMPL_S` test — so the boundary cards ARE still emitted, ARE read, and their
  `** THERMAL ANALYSIS **` counters advance normally: measured, a flux brick
  reports `IMPOSED FLUX_DENSITY HEAT = 70.000000` beside
  `HEAT STORED = 0.0000000`. Only that last number tells the story.
  (g) Radioss has NO thermal-expansion reference cell, so a driver that never
  changes (`*LOAD_THERMAL_CONSTANT[_NODE|_ELEMENT_<F>]`) develops exactly ZERO
  thermal strain where LS-DYNA measures from a *"null state"* and develops
  `α·T` (Vol I R17 p.33-168/33-169). k2rad names it; carrying it would mean
  starting an absolute-temperature model at 0 K, which corrupts conduction,
  Johnson-Cook `T*` and radiation alike, so the fix is its own decision.
  (h) A genuine THERMAL-ONLY LS-DYNA deck states no structural `*MAT_` at all,
  and `/HEAT/MAT` is keyed on a MATERIAL id — so that deck class gets no
  thermal material and `/DT/THERM` is refused by name. Synthesizing a
  `/MAT/LAW1` from the thermal material's `TRO` for a `*PART` whose MID is 0
  would make it reachable.
  **Next in this neighbourhood:** `*LOAD_HEAT_GENERATION` is the one genuinely
  convertible keyword left — the natural target of `/IMPFLUX`'s `grbric_ID`
  branch (`fixflux.F:200-239`), reusing all of this batch's machinery.

*Rationale:* these extend the proven modal machinery rather than opening a new
solver path, so risk is contained.

## R14 campaign-measured defect queue

Not a wish-list. The user ran the whole 356-deck `dynaexamples` R14 corpus
(ton-mm-s, with the LS-DYNA reference results beside it on
`F:/dynaexamples_r14_ton-mm-s`) through k2rad + OpenRadioss; the tracking
database is `C:/dynaexamples_r14_ton-mm-s_openradioss/_infra/db.json` and the
censuses are `OPENRADIOSS_REPORT.md` §0.3/0.4/0.7. Of 356 decks, 348 converted,
59 then failed in the STARTER and 49 in the engine. The ranking below is the
report's own (§0.7), with what the R14 TRIAGE ROUND 1 batch closes.

| # | class | decks | closed by round 1 | round 2 |
|--:|---|--:|---|---|
| 1 | `/PART` → `/MAT` id never emitted (starter ERROR 179) | 29 | **22** — the thermal-only stand-in, `*MAT_004`, `*MAT_CWM`, `*MAT_010`, `*MAT_014`; 7 are deliberate refusals BY NAME (`*MAT_102`, `*MAT_090` ×2, `*MAT_031`, `*MAT_148`, `*MAT_002` ANIS) and 2 are the named `*MAT_THERMAL_CWM` weld seam | — |
| 2 | IE collapse — NORMAL run, `or_ie_final ≈ 0` against a real LS reference | 36 | no — a physics item of its own | **the SUPPORT half.** `*NODE` TC/RC (part A) sits under 44 of the class's rows and the `*SET_*` range spellings (part B) under 25 more. Measured: `taylor1` 0.000 → IE 42 590 (+2.4 % vs 41 588.6), `plate.typ13` 0.0 → a contact carrying 4151 of elastic contact energy. **Re-census AFTER the campaign re-run, not before** |
| 3 | implicit engine will not advance (`TIMESTEP LIMIT` / `LOADING DATA` / indefinite stiffness) | 37 | no — the `/IMPL` recipe item; expect the 8 class-3 decks to reach it now that they START | partly: 27 of the class carry `*NODE` TC/RC and 5 more (`ex_06`, `ex_08` ×3, `ex_09`, `ex_10`) a `*BOUNDARY_SPC_SET` on a `_GENERATE` set. `ex_03` went from a TIMESTEP-LIMIT death at t = 0.22 to NORMAL at t = 1.0. **The residue is the `/IMPL` recipe item and must be re-measured after BOTH parts, or the attribution is unreadable** |
| 4 | `nvh` frequency-domain family (7 NORMAL at cycle ≤ 1, 6 stall at cycle 0) | 13 | no — the #110 class | the modal CHAIN is fixed for `6.2.PSD` (f1 110.5541 Hz on an exact matrix, +0.09 % vs its `eigout`), but that is `tools/`, not the `.rad` — the family's engine behaviour is unchanged |
| 5 | `/MAT` density ≤ 0 (ERROR 683, 8) + beam property (ERROR 314/315, 8) | 16 | **14** — all 8 density decks and the 6 ELFORM-3 truss decks | — |
| — | `/MAT/LAW51` (ERROR 99): 4 `Bunreacted`, 5 submaterial | 9 | **8** — `point_source.k` stays refused (`*MAT_GAS_MIXTURE`) | — |
| — | singles: ERROR 156, 580, 581 | 3 | **3** | — |
| — | starter ERROR 611 (zero-normal secondary node) | 2 | no | **2** — both start at 0 errors now and move `error_starter` → `error_engine` |

**52 of the 59 starter failures.** What is deliberately left, by name:

**Round 2's REVIEW round** re-derived item E on the solver (the stub keeps
`Inacti = 5`; `Fpenmax = 0.999999` is the measured zero-normal cut, 486 nodes
against 0.99's 928 on `4.3_General_Nonlinearity`; a tied `/INTER/TYPE10` states
`Itied = 1`), bounded item A's LS-DYNA evidence to what reproduces, named the
`*MAT_NULL` stability class it costs four ALE decks, and gave the batch's
headline default-on change the tests it did not have. The campaign was re-run
for every deck whose emitted `.rad` moved — see `OPENRADIOSS_REPORT.md` §0.14.

- ~~**ERROR 611**~~ — **CLOSED in R14 triage round 2.** The reading above is
  wrong twice over and the correction is what fixed it. 611 is not "initial
  penetration cannot be depenetrated": `i7pwr3.F:113-114` raises it only when
  `DN = |N|² ≤ 1e-30`, i.e. the secondary node lies EXACTLY on a main segment
  so no depenetration DIRECTION exists — the reported penetration is then the
  whole gap, which is what made it look like a depth problem. And the gate is
  `IF(INACTI/=1 .AND. INACTI/=2 .AND. FPENMAX==ZERO)`, so `Inacti = 6` would
  not have helped either. `4.3_General_Nonlinearity`'s `Inacti = 5` is also not
  a k2rad default: the deck states `IGNORE = 1` on its own optional `*CONTACT`
  card (line 348) and `_ignore_to_inacti` maps it faithfully. Fix: the
  synthesized stub keeps the ordinary `Inacti = 5` and every `/INTER/TYPE7`
  whose `Inacti` is 3/4/5/6 — the stub included — gains
  `Fpenmax = 0.999999`, a starter-only field that deactivates the nodes with
  no depenetration direction and is measured inert otherwise. The constant is
  measured: four starter runs of `4.3_General_Nonlinearity` give 928
  deactivations at 0.99 against its 486 zero-normal nodes, and 486 at
  0.999999. (The stub stated `Inacti = 1` for one round; that zeroes EVERY
  penetrating node's stiffness and cost `efg/metal-cutting` its NORMAL
  termination, 218 cycles → a TIMESTEP-LIMIT death at t = 0.0084.) A tied
  `/INTER/TYPE10` has no Fpenmax field (`hm_read_inter_type10.F:94`) and uses
  `Itied = 1` instead.
  Measured: `05_1_welding_solid` 310 → 0 starter errors,
  `4.3_General_Nonlinearity` 486 → 0. **Both then fail in the ENGINE** with
  `SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT`, so they move from
  `error_starter` to `error_engine` and belong to the `/IMPL` recipe item, not
  to this one.
- **ERROR 495**, `icfd/basics-examples/Basics_Cylinder_flow_FSI/main_fsi.k` —
  116 × zero-thickness CFD boundary shells. OpenRadioss has no ICFD solver, so
  the deck cannot run whatever the shells say.
- **`ex_16_thin_shell_elform_13.k`** — `*SECTION_BEAM` ELFORM = 7, a 2-D
  plane-strain "beam" on a rigid part. Not a truss, no Radioss counterpart; it
  keeps its ERROR 314-317 and is named here rather than swept into class 4.
- **`show-cases/contact-overview/mesh.k`** — a DECK DEFECT: it never defines the
  `*SECTION_BEAM` its beam parts reference, and 664 of its `/PART`s name no
  material. k2rad's placeholder warning is correct; nothing to fix here.
- **`point_source.k`** — `*MAT_GAS_MIXTURE` is refused whole rather than half,
  because converting the material without
  `*SECTION_POINT_SOURCE_MIXTURE`/`*INITIAL_GAS_MIXTURE` would leave the deck
  with no injection source (see CHANGELOG).

Round 1 closes the STARTER classes only. The engine census is untouched, and two
of its rows are expected to GROW as decks that never started begin to: a
Salzburg deck that starts and then stalls in `/IMPL` is a pass for this batch and
an input to the next.

### Found in the POST-REVIEW of round 1

Four defects the post-review FIXED are in `CHANGELOG.md`; these are what it
found and deliberately did NOT close.

- ~~**`*SET_NODE_LIST_GENERATE` is not read, so `*INITIAL_VELOCITY` is silently
  dropped**~~ — **CLOSED in R14 triage round 2.** Of the two options this entry
  offered, the FIRST was taken — and the resolver was NOT the thing taught. A
  post-parse expansion pass (`writer/mesh._expand_set_ranges_and_generals`,
  immediately before `_flatten_set_adds` at both of its call sites) turns
  `*SET_<FAMILY>_GENERATE`, `_GENERATE_INCREMENT`, `_GENERAL` and `_COLUMN` into the
  family's ordinary set, so **every** consumer of `state.node_sets` and its six
  sibling containers benefits, not just `*INITIAL_VELOCITY`. Vol I R17 p.43-40
  is explicit that this is a post-parse job and that only DEFINED ids join the
  set, so the pass bisects the id pool and never materialises the range (one
  roster deck states a 20 200 000-wide one over 664 parts). MEASURED on
  `taylor1`: the `*SET_NODE_LIST_GENERATE 101` resolves to exactly **4425**
  node ids — the count LS-DYNA's own `glstat` implies (initial energy
  44 807.05 = 4425 × ½ × 2.0251772e-9 × 1e10) — one `/INIVEL/TRA` is written,
  and the engine reaches NORMAL TERMINATION at 4424 cycles with cycle-0
  K-ENERGY 4.481E+04 (+0.007 % against that reference) and a final I-ENERGY of
  **4.259E+04 against LS-DYNA's 41 588.6, +2.4 %**, both channels evolving.
  **`matfoamsoil` did NOT come back with them, and that is the #122 rule
  working**: its set resolves and its `/INIVEL` IS written — onto 125 nodes
  every one of which is a member of `*MAT_RIGID` part 10, so `inirby.F`
  overwrites the velocity and the deck is still `I-ENERGY = K-ENERGY = 0.000`
  at 242 cycles. The converter now names exactly that (see the deferred
  re-point item below); the deck must NOT be scored as a physics pass. The
  original finding, kept because it is the measurement the fix was built on:

  **`*SET_NODE_LIST_GENERATE` is not read, so `*INITIAL_VELOCITY` is silently
  dropped — three decks now reach NORMAL TERMINATION with an identically zero
  model.** `taylor1` (4353 cycles), `taylor2` (2579) and `matfoamsoil` (242)
  print `I-ENERGY 0.000` and `K-ENERGY 0.000` on EVERY cycle against LS-DYNA
  references of 41589 / 42393 / 8573. The converter NAMES it verbatim —
  *"`*INITIAL_VELOCITY` NSID=101: node set not found (unsupported `*SET_NODE`
  variant?) - skipped"* — and the decks define `*SET_NODE_LIST_GENERATE 101`
  (`matfoamsoil`: 99). PRE-EXISTING; round 1 only made it observable, because
  while the decks died in the starter the drop could not be seen. It is the
  #122 signature exactly: legal, accepted, NORMAL — and inert. **The three
  class-1d/1e decks must therefore NOT be read as a physics pass.** Teach the
  `*INITIAL_VELOCITY` NSID resolver (and every other node-set consumer) to read
  the `b1beg`/`b1end` ranges, or refuse the deck by name instead of dropping
  the velocity, then require `IE` to leave zero.

- **Of the five SOLN=1 decks that now reach NORMAL, only ONE stores any heat.**
  `06_heating_plate` closes its balance exactly (`HEAT STORED` = `IMPOSED FLUX
  HEAT` = 7 606 720, 142 cycles) and proves the machinery works. `ex_21` (2
  cycles, 7.5e-12), `ex_22` (32 cycles, −2.9e-11) and
  `01_2_insulated_concrete_wall_transient` (6364 cycles, −2.3e-12) store
  numerical zeros. The three `ATYPE = 0` members (`ex_21`, `ex_23`, `01_1`) are
  a steady-state solve Radioss does not have, and the converter says so
  (*"a run shorter than one thermal step stores ZERO heat under NORMAL
  TERMINATION"*) — those are correctly named limitations, not defects, and the
  campaign report must mark them "starter pass, steady state unreachable"
  rather than counting them as validated.

  **The post-review MEASURED how empty that "normal" is, and it is worse than
  "stores no heat".** `01_1_insulated_concrete_wall_steady_state` converted with
  this branch and run as shipped is **0 ERROR / NORMAL TERMINATION / 1 CYCLE**,
  because k2rad copies `*CONTROL_TERMINATION`'s `ENDTIM = 1.0 s` into `/RUN`
  verbatim and one thermal step eats the whole run. Every interior node is still
  at the deck's own `*INITIAL_TEMPERATURE_SET` value of 293.15 — node 200 reads
  293.15000 against the LS-DYNA steady-state `tprint`'s 17.42925, node 300
  293.15 vs 12.97170, node 500 293.15 vs 14.20991 (mean |error| over all 549
  compared nodes 267.4 K). Only the imposed boundary nodes are right. This is
  the #122 "legal, accepted and meaningless" shape sitting inside the `normal`
  headline, and the campaign report now says so in §0.12.

  **NOT established: that a long enough transient reaches the reference.** A
  post-review reviewer reported the same deck converging to LS-DYNA's field to a
  mean 0.0013 K once the engine `/RUN` end time is raised to 1.98e6 s. I patched
  only that cell and re-ran: 43750 cycles, NORMAL TERMINATION, and the field is
  still 214.4 K away on average — node 300 has moved 293.15 → 277.161 against a
  reference 12.97170. Note also that this deck states its initial condition in
  KELVIN (293.15) and its boundaries on a 10–20 scale, which a steady-state BVP
  solve ignores entirely and a transient march does not. So the settling-time
  reading is UNCONFIRMED and the honest statement remains the converter's own:
  the converted run is transient and has to be given enough physical time to
  settle, and nobody has yet shown how much that is for this deck. The two
  `ATYPE = 1` members that
  store nothing (`ex_22`, `01_2`) are the real item: measure the `/DT/THERM`
  step actually chosen against the conduction stability limit, and check
  whether the boundary drivers are consumed at all (`RADIATION HEAT = 0.0`
  beside an emitted `/RADIATION` card is the tell).

- **`thermal-stress` clears the starter and produces NO MOTION.** 406 568
  cycles, NORMAL TERMINATION, `HEAT STORED` 3.06e-31, and every probed node's
  displacement exactly `0.000000E+00` at all 500 samples against the LS-DYNA
  `nodout`'s 1.50091E-04 in each direction at `t = 3.0`. Two named causes, both
  pre-existing: *"`*MAT_THERMAL_*` 1 -> `/HEAT/MAT/1`: TGMULT dropped"* —
  `TGMULT = 10.0` is the volumetric heat-generation rate, the only thing that
  raises the temperature in this deck — and *"`*NODE`: 7 node(s) state a
  constraint in the card's own TC/RC cells ... k2rad reads only NID/X/Y/Z"*,
  which is the whole symmetry mount. So the deck is NOT evidence for the
  `*MAT_004` mapping.

- **`cylinder_impact_A` cannot validate anything on EITHER side — and this
  does NOT extend to its sibling.** The `_A` reference is itself empty:
  `cylinder_impact_A.glstat`'s last block is kinetic energy `0.000000E+00`,
  internal energy `2.000000E-20`, total/initial 1.0, and every node in its
  `nodout` has `u = (0,0,0)` at `t_end`. OpenRadioss also runs 361 cycles at
  `IE = KE = 0`. Mark `_A` alone `not_comparable` BY CONSTRUCTION in the
  campaign DB — an all-zero result there is indistinguishable from the
  reference and must not be scored as a match.

  **`cylinder_impact_B`'s reference is LIVE and its row is a real deviation.**
  A post-review round read both files on `F:` rather than generalising from
  `_A`: `cylinder_impact_B.glstat` ends at kinetic energy `3.17790E+05` and
  internal energy `1.70429E+08` (t = 9.99202E-04) against OpenRadioss's 0.6584
  and 51537.66 — a genuine −100.0 % IE / −83.78 % KE row that `db.json` already
  records as `deviation`. Exempting the PAIR would have hidden it. `_B` belongs
  on the open ALE IE-collapse list, not on an exclusion list; §0.10 item 7 of
  the campaign report had this right while this entry did not. (The #130 rule:
  an exclusion list's stated reason needs the same audit as a warning's — here
  in its sibling flavour, one file quoted for two decks.)

- ~~**The class-3 MODAL target is unmeasurable with the shipped chain.**~~ —
  **CLOSED in R14 triage round 2, and this entry's diagnosis was right on both
  counts.** `tools/modal_solve.py` takes the beam area from the writer's own
  `_constants_from_thicknesses` for the thickness ELFORMs (6.35 × 50.8 =
  322.58, the number k2rad wrote into the deck's `/PROP/BEAM/1`) and mirrors
  the converter's `RO ≤ 0` floor — not a fabrication, because the K it pairs
  the mass with was exported from a `.rad` that already carries 1e-24. Both are
  necessary: with either one missing the mass matrix keeps RANK 3 and `eigsh`
  still dies −9999 (measured, `--no-zero-density-floor` reproduces it on
  demand). MEASURED **f1 = 110.5541 Hz** against the `eigout`'s 110.4521
  (**+0.09 %**), f2 = 884.4330 = f1 × 8 (the √(Iyy/Izz) pair) and
  f3 = 4422.1651 (axial), on a matrix whose tip stiffness is 109.454 = 3EI/L³
  to six figures — exactly the analytic cross-check this entry derived. The one
  thing it did not predict: the frequency is only reachable on an EXACT matrix.
  This machine's stock engine prints `/IMPL/PRINT/STIF` with
  `FORMAT(...,E10.2)`, and on a 50-element cantilever two significant digits
  turn the soft mode's tip stiffness NEGATIVE and f1 into 0.0000 Hz — the
  shipped export answers 334.196 Hz. So the "~1 % frequency error" the
  low-precision warning used to promise is a compact-model figure; the warning
  now carries the measurement and points at the patched engine (which the k2rad
  Docker image ships and the Windows install does not). The original finding:

  **The class-3 MODAL target is unmeasurable with the shipped chain.**
  `6.2.PSD_Beam_Example_LSTC` (LS-DYNA `eigout` f1 = 110.4521 Hz):
  `tools/modal_solve.py` reports a total deck mass of 0.000226842 — exactly the
  tip `*ELEMENT_MASS`, i.e. the beam contributes nothing — and "49 node(s) in K
  carry zero mass", IDENTICALLY at `RO` 1e-24, 1e-21 and 1e-18, because the
  deck's `*SECTION_BEAM` is ELFORM 1 (thickness cells) so `sec.area` is 0 and
  the mass arm skips the beams entirely; `spla.eigsh(..., sigma=0)` then dies
  with ARPACK −9999 at all three densities. The density floor never reaches the
  modal chain, which reads the SOURCE `.k`. Analytic cross-check of the target:
  `I = 50.8·6.35³/12 = 1083.936`, `k = 3EI/L³ = 109.454 N/mm`,
  `f = (1/2π)√(k/2.268418e-4) = 110.554 Hz` against the `eigout`'s 110.4521
  (−0.09 %); the substitution's own shift is
  `df/f ≈ −0.5·(33/140)·ρV/M = −2.13e-17`, below double precision — so the
  floor is provably harmless here, but the frequency could not be produced.
  Give the beam mass arm the same ELFORM-1/4 thickness→area derivation the
  writer already has (`writer/mesh.py` derives `A = TS·TT`), and either fall
  back to a dense generalized solve or shift `sigma` when `M` is near-singular.

- ~~**`/EOS/GRUNEISEN` turns a stated `a = 0` into `a = gamma0`.**~~ —
  **CLOSED in R14 triage round 2** by the first of the two options, narrowed:
  `a = 1e-20` is written only when the card states `A = 0` **and** its `GAMMA0`
  is non-zero, because `IF(A == ZERO) A = GAMA0` is a NO-OP when GAMMA0 is
  itself 0 and **23 of the 25 `A = 0` cards on the R14 roster are that shape** —
  writing the sentinel there would move 23 emitted decks for no physical
  reason. The two carriers are `sph/bar-iv/taylor1.k` and `sph/bar-v/taylor2.k`
  eos 2, both `GAMMA0 = 2.0`. The value is MEASURED, not chosen: a four-brick
  starter coupon at µ0 = 0.1 echoes `1.0000000000000E-20` verbatim with an
  INITIAL PRESSURE of 15439.03415072 — the `a = 0` closed form to all 13
  printed digits — while `1e-8` already differs in the 12th and `a = 0` itself
  is echoed as `A = 2.000000000000` with 15284.64380921. This entry's "grows as
  mu²" is right for the bulk term and INCOMPLETE: the energy term
  `(GAMMA0 + A·mu)·E` errs by `+mu`, LINEAR in mu, GAMMA0-independent, and the
  larger of the two on anything hot — +10 % at mu = 0.1 against the bulk term's
  −1.00 %. The warning derives both halves from the card's own GAMMA0 rather
  than quoting the coupon's.

  Two sibling "zero means default" EOS traps found while measuring it and
  deliberately NOT fixed here: `hm_read_eos_ideal_gas.F:140` (and `_vt.F:206`,
  `hm_read_eos_nasg.F:152`) turns a stated `T0 = 0` into 300 K while k2rad
  writes `*EOS_IDEAL_GAS`'s T0 verbatim, so a deck stating 0 silently gets
  300 K — the same class as the `/HEAT/MAT T0 = 0 → 300 K` finding already
  recorded; and `hm_read_eos_polynomial.F:163` reclassifies a polynomial EOS as
  ISFLUID when its coefficients happen to form the ideal-gas signature, a
  shape-triggered classification rather than a value override, with no corpus
  carrier checked. The original finding:

  **`/EOS/GRUNEISEN` turns a stated `a = 0` into `a = gamma0`.** Newly
  reachable through `*MAT_010`: k2rad writes the deck's first-order volume
  correction verbatim and `hm_read_eos_gruneisen.F:102` is
  `IF(A == ZERO) A = GAMA0`, which the starter then echoes as
  `A = 2.000000000000` while LS-DYNA's default 0 means no correction at all.
  MEASURED on the `*MAT_010` coupon the effect at `mu = 3.89e-3` is 5e-4 %
  (547.6218 with `a = 2` against 547.6193 with `a = 0`), but the term is
  `−(a/2)·mu² + a·mu·E` and grows as `mu²`, so it is NOT negligible at
  Taylor-impact compressions. Either write a tiny positive `a` so the Radioss
  default cannot fire, or warn by name.

- **Two LS-DYNA reference energies on `F:` are internally inconsistent**, and
  reading them naively reports the class-3 density floor as a catastrophic
  failure. `3.1_Elastic_Beams_etc.glstat` ends `internal energy = 3.45150E+02`
  beside `external work = 5.03994E+00` and `total energy / initial energy =
  6.84828E+01`; `3.5_Linear_Elastic_QS_Plate_Hex.glstat` ends `internal energy
  = 1.69226E+04` beside `external work = 7.22701E+01`. Their four siblings all
  end with `IE == external work` exactly. Against external work — the channel
  that balances on all six — OpenRadioss lands at −0.078 % and −0.014 %, not
  −98.54 % and −99.57 %, and OpenRadioss is self-consistent across the three
  meshes of the same plate (72.26 / 72.28 / 72.54, spread 0.39 %) where the
  LS-DYNA internal-energy column is not (16922.6 / 72.2787 / 72.2996). The
  stored `ie_dev_pct` for those two decks is not a converter result.

- **`*ELEMENT_BEAM_THICKNESS` `PARM1`** (a per-element truss AREA override,
  Vol I p.19-7) is still not read; no corpus carrier.

- **The ALE mesh is still not consolidated onto one `/PART` + per-phase
  `/INIVOL`.** This is the real modelling gap behind the whole class-2 ALE
  story, and dropping the orphan `/MAT/LAW51` does not touch it. k2rad emits
  the LS-DYNA per-fluid layout — each fluid on its own `/PART` with its own
  single-material `/MAT` and `Iale = 1` on its `/PROP/SOLID` — while in
  OpenRadioss the ALE domain is ONE part referencing a LAW51 material with the
  initial fill set by `/INIVOL`. The converted deck starts and runs, but the
  phases CANNOT MIX: on a blast deck the detonation products cannot expand into
  the water region, and on a volume-fraction deck the initial fill is not the
  deck's. Stated to the user in the `*ALE_MULTI-MATERIAL_GROUP` warning, with
  the phase list and the `--ale-multimat-law51` route back to the card; recorded
  here because the previous round's accounting said it was on this list and it
  was not.

- **The drop-the-`/PART` policy for refused materials.** When a material is
  refused BY NAME (seven of them in round 1), the `/PART` keeps its
  unresolvable `mat_ID` and the starter stops with `ERROR 179`. That is the
  honest answer today — an emitted part with a fabricated material would be
  worse — but it means a deck with one unconvertible material cannot be run at
  all, even to look at the rest. A `--drop-refused-parts` mode (drop the part,
  its elements and everything keyed on them, and name every drop) is the
  alternative; not started. Recorded here for the same reason as the item
  above.

### Found while doing round 2, recorded rather than fixed

- **THE `*SECTION_SOLID` ELFORM → `Isolid` MAPPING, exposed by the TC/RC pins
  on three `*MAT_NULL` decks.** Round 2 shipped this as *"a constrained mesh
  with no deviatoric stiffness"* with a `/BCS` vs `/ALE/BCS` decision attached.
  The verification round measured all three parts of that and they are wrong;
  the corrected statement is below, because the wrong CAUSE would have sent
  round 3 after the wrong card.

  What is true: pinning the walls costs `ale/sloshing/sloshing-a` its NORMAL
  termination (33 813 cycles at min dt 5.9e-05, t = 2.0 of 2.0 → 697 421 cycles
  at min dt 2.3e-16, stuck at t = 0.18), and `sloshing-c` and `sloshing-d` the
  same way. `--no-node-tc-rc-bcs` is byte-identical to a true master conversion
  on all three (verified, 0 diff lines each). The DECODE is exactly faithful:
  242 of 242 nodes agree with LS-DYNA's own `nodal spc summary on *NODE cards`
  echo, 0 disagreements.

  What is NOT true, each refuted by measurement:

    * *"the four decks"* — `ale/bird/bird-b` is not in this class. With
      `--no-node-tc-rc-bcs` its `.rad` still differs from a true master
      conversion by 337 added / 6 removed lines, because item B made a
      `*SET_NODE_LIST_GENERATE` resolve and gave the bird an `/INIVEL` master
      dropped entirely; the opt-out arm collapses exactly like the full branch
      (t = 3.34e-5, dt 1.4e-13). It is an item-B row: master's NORMAL was a
      zero model (ie/ke −100 %), the projectile now flies, and the ALE FSI then
      collapses. `/BCS`, `/ALE/BCS` and no-BCS all collapse alike on it.
    * *"`/BCS` vs `/ALE/BCS`"* — a provable no-op on the deck nominated as the
      twin. `sloshing_A.k` carries NO `*ALE_*` and no `*CONTROL_ALE` card at
      all (its `*SECTION_SOLID` is ELFORM 1, Lagrangian), the converted
      `/PROP/SOLID` has `Iale = 0`, and `bcs0.F:66-76` decodes ICODE's two ALE
      fields only `IF(IALE>0)`. An `/ALE/BCS` there is read by nothing.
    * *"LS-DYNA lists the same 242 nodes as `1 1 1`"* — the echo is 180 nodes
      `0 0 1` (TC 3), 40 `1 0 1` (TC 6) and 22 `1 1 1` (TC 7), with `0 0 0` in
      the three rotational columns for all 242 although every node states
      RC = 7 (which is what rule (d) predicts). The substantive half — LS-DYNA
      applies them and runs to t = 2.0 — holds.

  THE CAUSE, measured on the shipped `.rad` with only the `/PROP/SOLID` Isolid
  cell changed, against sloshing_A's own LS `glstat` (IE 3.10688e-3,
  EXT-WORK 0.165455):

    | Isolid | outcome |
    |---|---|
    | 17 (shipped, from ELFORM 1) | dt 2.3e-16, stuck at t = 0.1807 |
    | 24 (HEPH) | dt 9.2e-7, stuck at t = 0.6868 — its stabilisation is stiffness-form and scales with G = 0 |
    | 17 + Ismstr 1 | NORMAL BANNER at IE 1.85e24 — a #110 junk pass, not a run |
    | **1, h = 0.1** | **NORMAL, 34 118 cycles, t = 2.0, IE −0.25 %, EXT-WORK +0.03 %** |
    | 2 | NORMAL, 34 110 cycles, IE 3.101e-3 |

  Same on `sloshing_C` (Isolid 1 → NORMAL, 84 932 cycles, t = 5.0, IE +2.8 %,
  EXT-WORK −0.73 %). **The corpus contains the controlled experiment:**
  `sloshing_A.k` and `sloshing_B.k` are identical except three lines,
  `*CONTROL_HOURGLASS / IHQ 1 / QH 0.005` — and that card alone makes
  `_ihq_to_isolid` remap 17 → 1, which is why `sloshing_B` does not regress.
  LS-DYNA says the same: `sloshing_A.d3hsp` echoes *"solid formulation = 1 …
  eq. 1: 1 point integration"*, *"hourglass type = 2"*, *"hourglass coefficient
  = 1.00000E-01"* and its glstat ends with an hourglass energy of 0.162346
  against an external work of 0.165455 — 98 % of the input work. Vol I R17
  p.12-271 `*CONTROL_HOURGLASS` Remark 1: *"If omitted or if IHQ = 0, the
  default hourglass control types are as follows: … b) For solids: type 2 for
  explicit"* (QH default 0.1), in the same paragraph as *"Without hourglass
  control, these elements would have zero energy deformation modes which could
  grow large and destroy the solution."*

  So the class is: **`*SECTION_SOLID` ELFORM 1 (1-point) → `Isolid` 17
  (8-point) on a material with no deviatoric stiffness, with LS-DYNA's own
  DEFAULT hourglass control (IHQ 2 / QH 0.1) not carried** — `_solid_hg_values`
  remaps to Isolid 1 only when the deck CARRIES a `*CONTROL_HOURGLASS` /
  `*HOURGLASS` card, so a deck relying on the solver default gets an element
  with a different integration rule and no hourglass control. Round 3's item,
  with `sloshing_A` / `sloshing_B` as its three-line twin pair and
  `ex_03_solid_elform_1` as the second carrier (see the cross-deck row in the
  PR's LS-DYNA table). It needs its own corpus sweep: `_elform_to_isolid`'s
  docstring records a single-hex pull that hourglassed at Isolid 2, so the
  remap is not a one-line change. Round 2 leaves `--no-node-tc-rc-bcs` as the
  escape and NAMES the risk at conversion time.

- **A free single-element-thick `Isolid = 17` body is linearly unstable at the
  engine's default time-step scale** — PRE-EXISTING on master, no batch keyword
  involved, and it invalidated three coupons of the round-2 physics validator
  before it was isolated. A k2rad-converted 10x10x10 mm steel cube
  (`*SECTION_SOLID` ELFORM 1 or 2 → `/PROP/SOLID` Isolid 17, q_a = q_b = 0, no
  `/DT` scale) given an exact rigid-body translation grows I-ENERGY x10 per
  cycle from round-off and destroys itself by cycle ~210 — under a NORMAL
  TERMINATION banner. `*CONTROL_TIMESTEP TSSFAC = 0.4` is exactly stable (474
  cycles, KE constant to all printed digits) and so is a 2x2x2 mesh of the same
  block; restoring the artificial bulk viscosity (q_a = 1.1, q_b = 0.05, hand
  patched into the `.rad`) does NOT cure it. Round 2 concluded from that *"the
  cause is the step scale against Isolid 17's own stability limit"*; the
  verification round's `sloshing_A` measurement narrows it — `Isolid 1` is
  stable on that deck at the IDENTICAL `Tsca = 0.7`, so what the step scale
  interacts with is the ELFORM → Isolid mapping above, not a property of the
  step alone. The two entries are one defect. Any coupon or corpus deck of that
  shape needs TSSFAC <= 0.4, a finer mesh, or the Isolid its ELFORM asks for.

- **Fourteen decks terminate NORMAL as numerically-zero models against a
  non-zero LS-DYNA reference** — a WHOLE-DATABASE census, not a movers-only
  one. Round 2 shipped "eleven", which was the evolve table of that round's
  184 `normal` MOVERS presented as the class itself; censused over all 373
  records with the criterion *(status `normal`, both OpenRadioss final energies
  below 1e-10, and the LS reference not a structural zero)* it was **twenty**
  before this verification round and is **fourteen** after it, because the
  `/INIVEL` → `/RBODY` main-node re-point cleared six (`transducer`,
  `typ14-m24`, `translat`, `contact.n2s-sphere`, `matfoamsoil`, `sph/foam`).
  The fourteen that remain, with their LS `ie`/`ke`:

    `quadrature_A` (2e-20 / 15 300 — excluded from round 2's list on its zero
    LS *internal* energy while its kinetic reference is real),
    `quadrature_B` (166.5 / 12 405), `quadrature_C` (335.1 / 12 707),
    `ale_wavehitcol` (5.19e5 / 119.2), `cylinder_impact_B` (1.70e8 / 3.18e5),
    `Intermediate_fsi_flap/main_fsi` (6.65e4 / 8.15),
    `intermediate-fsi-2-flaps/main` (1.22e6 / 1.87e6),
    `sphere1` (7.91e4 / 7.03e6), `ex_17_spring_elform_0` (256.2 / 26.3),
    `ex_18_spring_elform_0` (310.7 / 28.3),
    `section_solid.hourglassing` (1.60e7 / 5.30e7),
    `projectile-block` (1.70e6 / 1.58e7), `wood-post` (4.68e6 / 4.87e7),
    `EXP_SC_CONTACT_INTERFERENCE` (1869 / 0.154).

  Round 3's named input class. Six of the fourteen (`quadrature_A/_B/_C`,
  `sphere1`, `projectile-block`, `wood-post`, `section_solid.hourglassing`)
  carry an `*INITIAL_VELOCITY_GENERATION` entirely on rigid-body members, which
  is the one remaining half of the re-point below.

- **An `*INITIAL_VELOCITY_GENERATION` over a rigid part's nodes is still
  emitted and inert** — the uniform-translation forms were re-pointed in the
  verification round and this one was not. `inirby.F` rebuilds
  every `/RBODY` secondary node's velocity from the body's main node as a rigid
  field before cycle 1, so an `/INIVEL` written on the secondaries is
  overwritten at 0 starter diagnostics. LS-DYNA has no such rule —
  `*INITIAL_VELOCITY` over a rigid part's nodes sets the PART's velocity, which
  is what the IRIGID cell exists to override — so this is a real conversion gap
  and not a deck defect.

  **SHIPPED for the uniform forms** (`*INITIAL_VELOCITY_NODE` and the NSID
  `*INITIAL_VELOCITY`): when EVERY node of the card belongs to a rigid body the
  group is replaced by that body's main node. MEASURED on `matfoamsoil`,
  nothing changed but the group's member list — cycle-0 K-ENERGY 3.547E+04
  against the LS-DYNA reference's own initial total energy 3.54775E+04
  (−0.02 %), where the un-re-pointed card gives 0.000; 1320 cycles NORMAL at
  0 ERRORS / 0 WARNINGS with both channels evolving (final IE +66.7 %,
  KE −36.9 % against 8573.23 / 19834.5) against 242 cycles flat at zero.
  Reach: 8 roster decks re-pointed, and 6 of the 14 remaining zero models are
  cleared by it.

  **NOT shipped for `*INITIAL_VELOCITY_GENERATION`**, which is round 3's half.
  That form emits `/INIVEL/AXIS`, whose `Vr` gives each node the TRANSLATIONAL
  velocity `omega x r` about the frame axis; collapsing the group to the main
  node would give that one node its own `omega x r` and the body NO spin at
  all, because a `/RBODY` secondary's motion comes from the main node's six
  DOFs. The faithful mapping is an angular velocity on the main node, not a
  smaller node group. Reach: 15 roster decks still carry the warning (a mixed
  card, or this form), and `quadrature_A/_B/_C`, `sphere1`, `projectile-block`,
  `wood-post` and `section_solid.hourglassing` are zero models because of it.
  The mixed case (some nodes rigid, some free) deliberately keeps the warning:
  re-pointing only the rigid half would drop the free nodes out of the group.

- **THE TIED-CONTACT FAMILY IS PICKED BY THE WRONG FIELD, AND THE CARD THAT
  RUNS IS SOFT.** Two halves of one round-3 item, both measured in the
  verification round.

  *The family.* `_tied_interface_type` routes on
  `(SFST*SST + SFMT*MST)/2 < 0`, inherited from dyna2rad and shipped with the
  rationale *"LS-DYNA's maintain-the-physical-offset flag"*. Vol I R17 p.11-33
  (`SAST`) is verbatim: *"For the \*CONTACT_TIED_… options, SAST and SBST
  (below) can be defined as negative values, which will cause the determination
  of whether or not a node is tied to depend only on the separation distance
  relative to the absolute value of these thicknesses (see Remark 4 in General
  Remarks)"*, and General Remark 4 (p.11-125) is the tying SEARCH DISTANCE
  `delta = abs(delta_1)`. The sentence that DOES pick the family is General
  Remark 7, "Tying to rigid bodies" (p.11-127), and it keys on the KEYWORD:
  `TIED_SURFACE_TO_SURFACE`, `TIED_NODES_TO_SURFACE`,
  `TIED_SHELL_EDGE_TO_SURFACE` and the `_CONSTRAINED_OFFSET` spellings are
  *constraint-based*; only the plain `_OFFSET` / `_BEAM_OFFSET` spellings are
  *penalty-based*. All five corpus cards the sign rule sends to
  `/INTER/TYPE10` are the plain constraint-based spelling.

  *Why it was not simply corrected.* Routing them to `/INTER/TYPE2` was TRIED
  and reverted, measured on this machine at `nt = 4`, the same deck differing
  only in the tie card: `05_4_2_welding_uncoupled_link_d3plot_structuralstep`
  (an `/IMPL` quasi-static step) with `/INTER/TYPE10` `Itied = 1` reaches
  NORMAL TERMINATION in 81 cycles, and with `/INTER/TYPE2` (Spotflag 27,
  `dsearch` 0.1, starter 0 ERRORS / 0 WARNINGS) diverges at cycle 16, t = 2.299
  — `ITERATION DIVERGE with RELATIVE R = 0.1723E+01` at every reduced step
  until `ERROR: SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT`, `ISTOP = -2`.
  `05_5_2` is the same deck with a different output database. The faithful card
  costs both carriers their NORMAL termination on this build.

  *What the arm that runs costs.* `/INTER/TYPE10`'s `STFAC` is Radioss's own
  documented default — k2rad writes 0, `hm_read_inter_type10.F:135` turns that
  into `ONE_FIFTH`, and `radioss120/INTER/inter_type10.cfg:76` gives
  `TYPE10_SCALE` the default `0.2` (a dimensionless stiffness SCALE, `:27`).
  On a determinate EXPLICIT steel-bar coupon (10x10x20 mm, two hexes, top face
  driven 100 mm/s, closed form `IE = 1/2 E eps^2 A L = 210.0`) the merged
  single bar gives IE 209.2 / EXT-WORK 209.3 / −0.0 % / 316 cycles, the
  `/INTER/TYPE2` twin reproduces that to every printed digit, and this
  `/INTER/TYPE10` carries **68.34 / 119.6 / −42.8 % / 407 cycles**. STFAC sweep
  on the same coupon: 1 → 158.4 (−13.0 %), 10 → 203.5 (−1.5 %), 100 → 209.2
  (−0.1 %). So an EXPLICIT tie routed here transfers about a third less load
  than the seam should carry, and flipping the `_OFFSET` spellings onto it —
  which Remark 7 would justify — would move three more corpus cards
  (`05_2_welding_shell_thin` and two `getriebekette` decks) onto that card.

  Round 3 owes both halves at once: derive a real `STFAC` (or find the TYPE2
  setting the implicit solve accepts), THEN key the family on the keyword.
  Doing either alone trades one measured defect for the other.

- **`*SECTION_SOLID` ELFORM 5/6/7 (the 1-point ALE solids) convert to a
  LAGRANGIAN solid, silently.** Found while correcting the `*MAT_NULL` class:
  `ale/sloshing/sloshing-c` and `-d` state `*SECTION_SOLID` ELFORM 5 beside a
  `*CONTROL_ALE`, and the emitted `/PROP/SOLID` has `Iale = 0` (read off the
  card). The only thing the conversion log says about ALE on those decks is the
  `*CONTROL_ALE` note — *"OpenRadioss keeps its default ALE advection"* — which
  reads as if the ALE scheme were preserved. Either map ELFORM 5/6/7 onto
  `Iale`, or warn that the element became Lagrangian and say what that costs.
  (ELFORM 11/12 already map to `Iale`; this is the 1-point family only.)

- **`*CONTACT_SURFACE_TO_SURFACE` and eight sibling contact keywords are not
  registered at all.** Measured while correcting item C's census: **62 of the
  69 type-0 contact sides on the R14 roster** sit on a `*CONTACT_*` keyword
  that is not in `handlers.HANDLERS` and lands in `skipped_keywords` before any
  side resolution — `*CONTACT_SURFACE_TO_SURFACE` (34 cards, the most frequent
  contact keyword on the roster), `_ONE_WAY_SURFACE_TO_SURFACE`,
  `_FORMING_ONE_WAY_SURFACE_TO_SURFACE`, `_SLIDING_ONLY`, `_SINGLE_EDGE`,
  `*CONTACT_ENTITY`, `_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR`,
  `_TIED_SURFACE_TO_SURFACE_THERMAL` and `_TIED_SURFACE_TO_SURFACE_OFFSET_
  THERMAL`. `plate.typ3.k` is the visible shape: `skipped_keywords =
  ['CONTACT_SURFACE_TO_SURFACE']` and *"`*DATABASE_RCFORC` requested but no
  `*CONTACT` was converted"*. Its own item, with its own sweep; folding it into
  the SSTYP precedence fix would have made both unattributable.

- **`*EOS_IDEAL_GAS` `T0 = 0` silently becomes 300 K.**
  `hm_read_eos_ideal_gas.F:140` (and `_vt.F:206`, `hm_read_eos_nasg.F:152`) is
  `IF (T0 == ZERO) T0 = THREE100`, and `handlers.py` reads `*EOS_IDEAL_GAS`'s
  T0 verbatim into `params["t0"]` for `writer/materials` to write. Same class
  as the `/HEAT/MAT T0 = 0 → 300 K` finding already recorded, and as the
  `/EOS/GRUNEISEN A = 0` round 2 fixed — but the fix is not the same shape (a
  temperature has a physically meaningful zero, so a 1e-20 sentinel is not
  obviously right) and no corpus carrier was measured.
  `hm_read_eos_polynomial.F:163` is a second, different trap on the same page:
  a polynomial EOS whose coefficients happen to form the ideal-gas signature
  (`C1 = C2 = C3 = 0`, `C4 == C5 > 1`, `C6 = 0`) is RECLASSIFIED as ISFLUID —
  a shape-triggered classification, not a value override. No carrier checked.

- **The four PARSE-TIME set readers still see only the plain spellings.**
  `*ELEMENT_MASS_NODE_SET`, `*ELEMENT_MASS_PART_SET`, `*LOAD_BODY_PARTS` and
  `*CONSTRAINED_EXTRA_NODES_SET` resolve their set during dispatch, before the
  post-parse expansion pass and before `_flatten_set_adds`, so a `_GENERATE` or
  `_ADD` set named by one of them is still empty. They inherit the
  `_flatten_set_adds` limitation verbatim rather than gaining a new one, and
  zero corpus decks combine one of those keywords with a range spelling —
  stated here rather than left implicit.

- **A `*SET_<FAMILY>_GENERAL` clause naming a `*SET_<FAMILY>_ADD` union is skipped.** The
  expansion order is ranges → GENERAL → `_flatten_set_adds`, because a GENERAL
  clause may name a plain set and an `_ADD` member may be a `_GENERATE` sid; a
  GENERAL clause naming an `_ADD` union is the one back-edge that order cannot
  serve. Warned by name. No corpus deck does it (the only options in use are
  `SEG`/`PART`/`ALL`/`BOX`/`DPART`), so a fixpoint iteration would be machinery
  for a case that does not exist.

### Found while doing round 1, recorded rather than fixed

- ~~**A `*CONTACT_AUTOMATIC_SINGLE_SURFACE` with `SSTYP = 0` resolves to a
  `*PART`**~~ — **CLOSED in R14 triage round 2.** All ten styp-typed sites in
  `writer/contacts` and the three in `gapmin` read ONE table with no fallback
  chain — 0 → `*SET_SEGMENT` only, 1 → `*SET_SHELL` only — and a missing set is
  a NAMED drop, never a part. The seven sites that already consulted
  `segment_sets` kept a part fallback behind it; that leniency is gone too.
  MEASURED on `plate.typ13`, before → after on the same branch: glstat
  I-ENERGY **0.000 on every one of 251 cycles → 404.24 at the last of 253**,
  peaking at 4631; K-ENERGY **constant at 7850 → 4836 + 760 rotational**
  (a perfectly constant KE is what "the impactor passed through" looks like);
  and the T01 CONTACT ENERGY channel **0.0 for the whole run → a peak of
  4151**. The emitted interface is now a `/SURF/SEG` over the set's five
  segments with a secondary `/GRNOD` of the 13 nodes they own — spanning BOTH
  bodies — where it used to be a `/SURF/GRSHEL` over the plate's 16 shells
  against a `/GRNOD` of the plate's own 25 nodes.

  Two corrections to this entry's own premises, both measured. The ROSTER reach
  is **one** contact card, not 13: 62 of the 69 type-0 sides sit on `*CONTACT_*`
  keywords k2rad does not register at all (`*CONTACT_SURFACE_TO_SURFACE` alone
  is 34 of them, and `plate.typ3.k` reports it in `skipped_keywords` today) —
  registering those is a separate item, not folded in here. And `pipe.k`,
  `EXP_SC_PRELOAD.k`, `mainboltaexpl.k`, `contact-overview/main.k` and the
  square-beam and blow-mold decks are NOT carriers: their cards read SSTYP 2 or
  3, and the number that looked like a type was the SURFA id. The corpus reach
  is Ryan_Lee (76 sides, all on registered keywords) plus `getriebekette` (5,
  which needs the `*SET_SEGMENT_GENERAL` item as well). The original finding:

  **A `*CONTACT_AUTOMATIC_SINGLE_SURFACE` with `SSTYP = 0` resolves to a
  `*PART`, and its `*SET_SEGMENT` is never read.** `contacts._resolve_contact_slave`
  takes the `styp in (0, 1)` branch and looks the id up in `state.parts` FIRST,
  so `plate.typ13`'s `SSID = 1, SSTYP = 0` resolves to part 1 and the deck's own
  `*SET_SEGMENT 1` — which also lists the impactor's segment — is never
  consulted. That is why its converted deck has **no contact at all** (T01
  internal energy 0.0 for the whole run) while LS-DYNA's `sleout` records 6.927
  of sliding energy on that interface. Clearing the transducer's ERROR 580/581
  makes the deck START; it does not make it produce contact. Separate item, and
  a real one.
- **Beams and trusses are NOT walked by `_resolve_contact_slave.add_part_nodes`
  while `_part_node_ids` DOES walk them.** A `/TRUSS` or `/BEAM` node is a
  perfectly good contact SECONDARY node in Radioss, so the exclusion is a
  choice, not a fact — but adding a 1-D family there changes the secondary side
  of every part-scoped contact on hundreds of corpus decks. Its own item with
  its own sweep; the asymmetry is now stated at both sites instead of being
  closed on one.
- **A force transducer whose SURFA has no FACES has no Radioss route.** A
  parentless `/INTER/SUB` measures a `/SURF` (`Main_ID2`; `Second_ID` is not
  decoded on that branch), and an SPH cloud has no face — so such a transducer
  is refused by name. If it ever matters, the route would be a legally parented
  sub-interface whose parent's secondary group provably contains those nodes,
  which is the machinery this batch removed for being unable to guarantee it.
- **The corpus cannot validate the transducer's NUMBER.** Both R14 carriers read
  ZERO on the LS-DYNA side too: `plate.typ13.rcforc`'s transducer rows are
  `x 0.0 y 0.0 z 0.0` for the whole run, and `pipe.rcforc`'s interface 1 is
  identically zero for 811 rows. They validate that the card is accepted and the
  deck runs; the number is validated by the purpose-built shell-impact probe
  (identical to the legally parented form and to the parent interface, and
  93.2 % of `2·m·v₀`).

## Lossy conversions to tighten

Cases that convert today but drop or approximate detail worth recovering:

- **A substituted density on an `RO ≤ 0` material** — the floor is `1e-24`,
  measured from LS-DYNA's own substitution rather than picked (CHANGELOG), and
  it is inert on the static and eigenvalue decks that carry it. What it costs is
  still a substitution: on an EXPLICIT deck the element time step collapses
  (warned, harder), on a modal one the shift is `Δf/f ≈ −½·(33/140)·ρV/M_eff`
  (2.1e-17 on the corpus carrier), and every mass diagnostic on such a deck
  reports k2rad's injected 1e-3 implicit probe rigid body instead of the
  structure. That probe body's hard-coded `Mass = 0.001` / `J = 0.001` is the
  real thing to tighten: it is 17 orders of magnitude above a zero-density
  model's own mass and makes `TOTAL MASS`, `MAS.ERR` and every `/TH` mass
  channel meaningless. `--no-zero-density-floor` opts out.
- **`*SECTION_BEAM` ELFORM = 3 cells with no `/PROP/TYPE2` slot** — `GAP` is
  written 0 always (a non-zero one is a compression-only gap element,
  `tforc3.F:184-186`, which nothing on card 2d asks for). `RAMPT`/`STRESS` are
  screened: inert without a dynamic-relaxation phase, and named as the
  equivalent `/PRELOAD/AXIAL` force `STRESS × A` with one — synthesizing it
  needs a ramp curve and a window the card does not state, so the converted
  truss starts UNSTRESSED. `*ELEMENT_BEAM` `RT1`/`RT2` translational releases
  have no `/TRUSS` column and are a TOTAL loss of that element's freedom;
  `*ELEMENT_BEAM_THICKNESS` `PARM1` (a per-element AREA override, p.19-7) is not
  read at all, and a card-2b named standard section is refused rather than
  emitted with `AREA = 0`.
- **Simplified Johnson-Cook rate term** — **done**: converts as a sampled
  LAW36 multi-rate curve family (see CHANGELOG).
- **`*MAT_PLASTIC_KINEMATIC` Cowper-Symonds rate params** — already emitted
  correctly (`SRC`→`c`, `SRP`→`p` on the LAW44 rate card); listed here only for
  the record.
- **`*RIGIDWALL_MOVING` / `_FINITE`** — **done** (moving /RWALL/PLANE with a
  synthesized carrier node; /RWALL/PARAL from XHEV/LENL/LENM). _ORTHO remains
  warn-skipped (no /RWALL equivalent).
- **Geometric rigidwalls** — **done** (`*RIGIDWALL_GEOMETRIC_{FLAT,PRISM,
  CYLINDER,SPHERE}` + any ordering of `_MOTION`/`_DISPLAY`/`_INTERIOR`/`_ID`
  → /RWALL/CYL, /SPHER, /PLANE, /PARAL, a prism as six outward PARAL faces, and
  the _MOTION route through /IMPVEL|/IMPDISP on a synthesized /SKEW/FIX; see
  CHANGELOG). What genuinely has no /RWALL counterpart and is now warned rather
  than silently dropped: a finite `LENCYL`, `NSEGS` per-segment force output,
  `_INTERIOR` (inverted sidedness — warn-skipped), `_DEFORM` (warn-skipped by
  name), an infinite `LENP`, and several card sets under one keyword (the first
  is converted).
- **CNRB per-node DOF releases** *(remaining)* — nodal rigid bodies are tied in
  all DOFs; the per-node `DRFLAG`/`RRFLAG` release codes are not honoured
  (Radioss `/RBODY` has no direct partial-release construct).
- **EOS `V0` / `C6`** — `C6` is now **warned**; `V0 ≠ 1` remains warned (Radioss
  references the initial state through density / `/INIBRI`, not a `V0` scalar).
- **`*MAT_ADD_EROSION` non-strain criteria** — only `MXEPS`/`EFFEPS` map; other
  criteria and `IDAM≥1` are reported but not converted.
- **`*NODE` `TC`/`RC` → `/BCS`** — **DONE in R14 triage round 2, DEFAULT ON**
  (opt out with `--no-node-tc-rc-bcs`). The entry that stood here prescribed
  shipping it behind an opt-in `--node-tc-rc-to-bcs` and closed with *"then run
  the campaign and consider flipping it"*. **The campaign has run, and it
  flips.**

  Two corrections to the numbers this entry used to carry, both re-measured
  with an independent scanner (no k2rad code) over
  `C:/openradioss_run` + the R14 deck-only tree + `E:/foxcore_data`, the
  Yaris/Camry `*INCLUDE` pullers excluded by name:
  - the old **"721 corpus decks write a non-zero cell — of 2332 scanned here"**
    is **not reproducible**. The three roots hold **893** `.k`/`.key`/`.dyn`
    files in total (501 + 356 + 36), and **137** of them carry a non-zero cell
    — **all 137 in the R14 tree**, none in `C:/openradioss_run` and none in
    `E:/foxcore_data`. The scanner is validated against two known counts
    (`taylor1.k` → 8, the number `tests/test_side_defects_fixround.py` pins;
    `component1.k` → 65) and against LS-DYNA's own d3hsp echo (below).
  - the old **"278 of 721 (39 %) also carry a rigid body or a prescribed
    motion"** was the argument for deferral. On the roster the real screening
    reach is **5 426 nodes in 15 decks** for the rigid-body rule and **148
    nodes in 11 decks** (same node *and* same DOF in 3) for the
    prescribed-motion rule.

  **Why default ON.** 137 of the 356 R14 reference decks carry a non-zero cell
  and **119 of them have no `*BOUNDARY_SPC` at all** — the card's own cells are
  their only support — and those decks sit under **44 of the 69 IE-collapse
  decks and 27 of the 42 implicit-ERROR decks**. It is LS-DYNA's standard,
  always-active semantics, and the decode is not assumed: it reproduces
  LS-DYNA's own `nodal spc summary on *NODE cards` d3hsp echo on **all 162 139
  constrained `*NODE` rows of the 137 carrier decks (267 641 non-zero TC/RC
  cells — the echo prints one row per node; the echo itself is printed by 155
  of the R14 reference runs), with zero translation-code disagreements**. Two
  decks measured against their own `glstat`:
  `intro-by-j.-day/misc/component-i/component1.k` went from NORMAL-but-junk
  (IE 2 224 vs 2 740 230, KE 2.799e8 vs 36 222) to **IE +1.5 % / KE +1.0 %**,
  and `introduction/Introduction/example-03/ex_03_solid_elform_1_4x6x4_mesh.k`
  from a TIMESTEP-LIMIT death at `t = 0.22` to **NORMAL TERMINATION at
  `t = 1.0`**.

  The screening is measured rule by rule and every screened node is named in
  the conversion log — see the CHANGELOG entry and
  `writer/loads._make_node_tc_rc_bcs`. `tools/` needed no arm: `modal_solve`
  builds its mass matrix on the DOFs of the stiffness matrix the ENGINE
  exported from the CONVERTED `.rad`, so the modal chain inherits the
  constraint through the deck.

  **RESOLVED in the verification round, and the other way round.** This entry
  said `writer/loads._make_bcs`'s re-point of a `*BOUNDARY_SPC` on a rigid-body
  member node is *"what neither solver does — LS-DYNA skips such an SPC
  (p.35-3 Remark 1; d3hsp Warning 60257)"*. Vol I R17 p.35-3 Remark 1 is
  verbatim *"No attempt should be made to apply boundary conditions to nodes
  belonging to rigid bodies"* — advice to the deck author, not a statement that
  the solver ignores them — and Warning 60257 is an `IMP+` (implicit) message
  on 1 of the 16 R14 rule-(a) carriers. LS-DYNA's EXPLICIT solver applies the
  constraint to the BODY: on `control_contact.hemi-draw` part 4 (525 nodes at
  TC 7 / RC 7, `*MAT_RIGID` CMO 0, no other constraint anywhere in the deck,
  carrying 1.8e4 of interface-3 contact force) its own `matsum` holds the body
  at rigid-body velocity exactly 0.0 in all three components at all 121 output
  times, while parts 2 and 3 — same material, TC codes unioning to x and z —
  move freely in y. So `_make_bcs`'s re-point is the arm that MATCHES LS-DYNA,
  and the TC/RC path has been aligned WITH it (rule (a) now re-points too,
  through the shared `_rbody_main_of` map) rather than the reverse. One
  rigid-node rule in one writer.
- **`*INITIAL_STRESS_SHELL` records at MIXED `nb_integr` in one deck**
  *(remaining, an OpenRadioss limitation rather than a conversion loss)* —
  `INISHVAR = 22 + NIP*6` is set per RECORD into the COM01 common
  (`hm_read_inistate_d00.F:2206/2389/3347/3516`) while `csigini.F:231/233` and
  `scigini4.F:345/347/487/489` read `SIGSH(INISHVAR+IT)` (sigma_zz) and
  `SIGSH(INISHVAR+NPTI+IT)` (pos_nip) at CONSUME time, i.e. against whatever
  the LAST record left there. Two shell parts at NIP 3 and NIP 5 in one
  `/INISHE|/INISH3 STRS_F` pass therefore make every element whose NIP differs
  from the last record's read its through-thickness stress and its station
  positions from the wrong slots, at 0 starter ERROR / 0 WARNING. k2rad now
  NAMES the deck; splitting the pass (or writing one block per NIP with the
  records grouped) would need a starter-side experiment to establish whether
  the global is re-set per block or per record.
- **`2Dlag.k`'s residual `ERROR 3046`** *(remaining, pre-existing and out of
  the side-defect batch's scope)* — the deck's `ELFORM = 14` 2-D axisymmetric
  elements are written as 3-D `/SHELL` against a solid-only `/MAT/LAW4`, so
  `ERROR IN MATERIAL/ELEMENT COMPATIBILITY / ELEMENTS OF TYPE SHELL ARE NOT
  COMPATIBLE WITH MATERIAL ID 3 OF TYPE 4`. Byte-identical on master, so the
  batch neither caused nor cured it; it is what stands between that deck and 0
  starter errors.
- **A `_SET` cross section whose nodes are COLINEAR gets an invented normal**
  *(remaining)* — `_sect_synth_frame` falls back to a vector perpendicular to
  the node line, so the FN/FT SPLIT is arbitrary (the vector sum and the global
  `MX/MY/MZ` channels are right, and the warning says exactly this). A
  determinate normal is available for the ordinary case, a line of nodes cut
  across a shell plate: `n = t × m`, with `t` the node-line direction and `m`
  the plane normal of the section's OWN elements (the `SSID`/`HSID`/`BSID` sets
  the card already supplies). Checked by hand on
  `dynaexamples/intro-by-k.-weimar/spotweld/spotweld-ii/plates.nrbc.k`, whose
  section nodes 106..110 are colinear along +Y at x = 20 while the section
  shells lie in z = 0: `t × m = (0,1,0) × (0,0,1) = (1,0,0)`, the true cut
  normal. 120 of the corpus's 191 cross-section cards use the `_SET` spelling,
  so this changes many sections' FN/FT split and belongs in a round that can
  re-validate them.

## Testing / CI / DX

Developer-experience items. Every row on this list has now shipped; the section
is kept as the rationale record, and re-checked against the repo at PR #134.

- **Golden-file end-to-end regression fixtures** *(done)* — `tests/test_golden.py`
  converts five checked-in decks and diffs both `.rad` files against
  `tests/fixtures/expected/`, plus a second-run determinism case that guards
  dict/set-ordering nondeterminism. The `.gitignore` blocker was solved with
  `!tests/fixtures/**` overrides.
- **Coverage gate** *(done)* — `coverage report --fail-under=68` in the `test`
  job, plus a guard that fails the build if more than 15 tests self-skip.
- **mypy** *(done — blocking)* — `mypy==2.3.1`, configured in `pyproject.toml`
  `[tool.mypy]`, `k2rad` clean at **0 findings** (down from 194 at PR #134); the
  CI `typecheck` job fails the build on a new finding. The pin is deliberate: an
  unpinned `pip install mypy` lets a future release turn master red with no
  change on our side. Two environments must both stay clean — `mypy k2rad` in a
  venv that has numpy/scipy, and `mypy --no-site-packages k2rad`, which
  reproduces locally the bare environment the CI job runs `mypy k2rad` in.
  *Next tiers, measured on the clean tree, not scheduled:*
  `--check-untyped-defs` = **2** findings (two `Need type annotation for "out"`,
  and it silences the 10 `annotation-unchecked` notes) — a near-free next step;
  `--disallow-untyped-defs` = 479; `--strict` = 1184.
- **Windows CI leg** *(done)* — the `test` job matrix is
  `[ubuntu-latest, windows-latest]` × Python 3.9-3.12.
- **PyPI publish + releases** *(done)* — `.github/workflows/publish.yml` builds
  and publishes on a release.
- **Docker bash launchers + hardening** *(done)* — `docker/or.sh` and
  `docker/build-and-export.sh` alongside the PowerShell pair.
