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

| # | class | decks | closed by round 1 | round 2 | round 3 | round 4 |
|--:|---|--:|---|---|---|---|
| 1 | `/PART` → `/MAT` id never emitted (starter ERROR 179) | 29 | **22** — the thermal-only stand-in, `*MAT_004`, `*MAT_CWM`, `*MAT_010`, `*MAT_014`; 7 are deliberate refusals BY NAME (`*MAT_102`, `*MAT_090` ×2, `*MAT_031`, `*MAT_148`, `*MAT_002` ANIS) and 2 are the named `*MAT_THERMAL_CWM` weld seam | — | — | — |
| 2 | IE collapse — NORMAL run, `or_ie_final ≈ 0` against a real LS reference | 36 | no — a physics item of its own | **the SUPPORT half.** `*NODE` TC/RC (part A) sits under 44 of the class's rows and the `*SET_*` range spellings (part B) under 25 more. Measured: `taylor1` 0.000 → IE 42 590 (+2.4 % vs 41 588.6), `plate.typ13` 0.0 → a contact carrying 4151 of elastic contact energy. **Re-census AFTER the campaign re-run, not before** | **the LOAD PATH and the ELEMENT halves.** Item A registers 16 `*CONTACT` spellings that sit under 18 of the 30 STRICT IE-collapse rows; item B gives 46 more decks the hourglass control LS-DYNA defaults to; item C re-points the 7 rigid-body velocity carriers. **Re-census after the campaign re-run** — and state WHICH criterion: `analyze_pass1.py e` STRICT (`|or_ie| <= 1e-15 < |ls_ie|`, status normal) is **30 of 266** at `b3807bd`, `ie_dev_pct <= -99` on normals is **46**, over all statuses **68**, and the report's §0.15 headline "45" is a MOVERS carry-forward, not a census | **the CONSTRAINT and the RIGID-BODY halves.** B1 makes a `*DEFORMABLE_TO_RIGID` part rigid at t = 0 (4 keys / 2 models; `pend.imp`'s ENGINE energy-error column 99.9 % → −0.0 %, KE −0.017 % against the reference — its `ie_dev` row stays a `deviation` at +17.19 %, both energies being structural zeros), B2 restores the load path on every explicit all-rigid-SSID contact (4 keys / 5 interfaces swapped + 1 key kept), and part A's items close three strict zero models (`ex_17`, `ex_18`, `thermal-stress`). Strict zero models 9 → 5 with `bumper`, 2 icfd and 2 ALE named. **Re-census after the campaign re-run** |
| 3 | implicit engine will not advance (`TIMESTEP LIMIT` / `LOADING DATA` / indefinite stiffness) | 37 | no — the `/IMPL` recipe item; expect the 8 class-3 decks to reach it now that they START | partly: 27 of the class carry `*NODE` TC/RC and 5 more (`ex_06`, `ex_08` ×3, `ex_09`, `ex_10`) a `*BOUNDARY_SPC_SET` on a `_GENERATE` set. `ex_03` went from a TIMESTEP-LIMIT death at t = 0.22 to NORMAL at t = 1.0. **The residue is the `/IMPL` recipe item and must be re-measured after BOTH parts, or the attribution is unreadable** | **partly, and the rest is censused rather than guessed.** Item F removes `/IMPL/DT/FIXPOINT` from the default output: measured, ten decks that died `SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT` reach NORMAL TERMINATION (`ex_01` x3, `ex_14` x4, `ex_15` x3), and three currently-NORMAL controls do not regress. The residue is grouped by FAMILY, with its mechanism per family, in *The implicit residue after round 3* below | **partly.** A1 raises `/IMPL/QSTAT/DTSCAL` 0.1 → 10 on all 51 carriers (`4.2.frf.cant-1` 4 cycles + ERROR → 104 cycles at t = 1.000, IE −0.31 %), A2 adds the RIKS `/IMPL/DT/3` behind `--arclength-riks`, and the four `thermal/welding-new` rows are re-verdicted not-comparable BY CONSTRUCTION. `bumper` stays a NORMAL zero model by the IMPLICIT gate on B2, NAMED. The per-family residue table below is updated in place |
| 4 | `nvh` frequency-domain family (7 NORMAL at cycle ≤ 1, 6 stall at cycle 0) | 13 | no — the #110 class | the modal CHAIN is fixed for `6.2.PSD` (f1 110.5541 Hz on an exact matrix, +0.09 % vs its `eigout`), but that is `tools/`, not the `.rad` — the family's engine behaviour is unchanged | unchanged, and now separated from row 3 by measurement: the 6 cycle-0 stalls are SSD / ERP / PSD frequency-domain requests, not an `/IMPL` recipe problem — OpenRadioss has no frequency-domain solver at all | unchanged — still queue row 4, no frequency-domain solver |
| 5 | `/MAT` density ≤ 0 (ERROR 683, 8) + beam property (ERROR 314/315, 8) | 16 | **14** — all 8 density decks and the 6 ELFORM-3 truss decks | — | — | — |
| — | `/MAT/LAW51` (ERROR 99): 4 `Bunreacted`, 5 submaterial | 9 | **8** — `point_source.k` stays refused (`*MAT_GAS_MIXTURE`) | — | — | — |
| — | singles: ERROR 156, 580, 581 | 3 | **3** | — | — | — |
| — | starter ERROR 611 (zero-normal secondary node) | 2 | no | **2** — both start at 0 errors now and move `error_starter` → `error_engine` | — | — |

**What round 3 closes, by class and deck count** (measured on the branch;
the campaign RE-RUN and the two-half corpus sweep are the PR's own gates and
are not folded into these figures):

| item | class | roster decks that MOVE | measured outcome |
|---|---|--:|---|
| A | 16 `*CONTACT_*` spellings in no dispatch table | **41** on the sweep roster / 44 on the F: census (the three extra are the Yaris `_MORTAR` carriers the include-closure cap excludes) | the load path exists; 18 of the 30 strict IE-collapse rows carry one |
| B | 1-point `*SECTION_SOLID` with the hourglass control DEFAULTED | **69** R14-roster decks MEASURED on the two-half sweep (217 over the whole 885-deck roster) - the census's 46 + 8 ELFORM 5/6/7 + 8 that DO state a card and move through the implicit re-type / fluid override / QM-inheritance arms; 70 by the campaign's own renumber-aware classifier | `sloshing_A` t = 0.18 death → NORMAL at t = 2.0 (IE −0.254 %); `ex_03_solid_elform_1` −20.4 % → −4.1 % |
| C | `*INITIAL_VELOCITY_GENERATION` on rigid members | **10** hand-counted (7 all-rigid + `brake`/`brake_debug` + the mixed `pipe`); **16** by the campaign's renumber-aware classifier, which also credits the six decks whose only C-side change is an auto-id shift below the re-pointed `/GRNOD` | cycle-0 KE within +0.006 %…−0.003 % of each deck's own LS reference, where it was 0.000 |
| D | the tied family keyed on the keyword and the solver | **0** (both sign-rule carriers are implicit and keep `/INTER/TYPE10`) | the routing is now stated rather than accidental; `--tie-stfac` is the lever |
| E | `*SECTION_SOLID` ELFORM 5/6/7 | **0** `.rad` movers — warn only | `state.warnings` is the mover half; the `Iale` remap is a measured NO-GO |
| F | `/IMPL/DT/FIXPOINT` off by default | **84** of the 161 implicit sweep decks actually CARRY the card (86 movers; 72 on the R14 roster, of 135 that emit an `/IMPL` block) - the emitter gates it on `state.ctrl_termination and endtim > 0`, so 77 implicit decks never had it | 10 `error_engine` decks → NORMAL; 3 controls unchanged, 2 improved |

**What round 3 deliberately does NOT close** — named so the next round starts
from a list rather than a re-census:

- **The mass-weighted arm of item C.** A rigid body an initial-velocity card
  covers only PARTLY gets the card's FULL velocity on its main node when the
  card names nothing else, and nothing at all when the card also names
  deformable nodes. Neither is LS-DYNA's answer. Measured by hand on
  `translat.k`, whose card names 2 of rigid part 1's 4 element nodes: LS-DYNA's
  own glstat reads 189.962 = 97.0 translational (`1/2 M (v/2)^2`) + 93.0
  rotational (the two loaded nodes sit on one edge, so the body SPINS at
  `omega = (300, 0, -45)`), against the shipped re-point's 387.9 (+104 %) and
  the refusal's 0.000. The blocker is NOT that the masses are unavailable —
  `tools/modal_solve.nodal_masses_from_state(state)` already lumps element
  mass and rotary inertia off exactly the `ConversionState` the writer holds
  and applies `*ELEMENT_MASS` / `*ELEMENT_MASS_PART` (it reproduces the
  starter's own MS/IN arrays on the W14 bogie), so a graded mesh and an added
  point mass are both handled. What is missing is EVIDENCE: the arm has one
  carrier, `translat`, and a momentum split has to be measured against the LS
  reference on more than one before it ships. The WRITER computes no nodal
  masses today; wiring that lumper into it is the round-4 work.
- **The implicit contact stub's guard tests PARSED records, not EMITTED
  interfaces.** `k2rad/__init__.py` `_inject_implicit_contact_stub` returns
  early on `state.contacts_single or state.contacts_surf2surf or
  state.contacts_general`. Item A fills `contacts_surf2surf` on
  `implicit/basic-examples/contact-i/bumper.k`, whose 1404 secondary nodes are
  all `*MAT_RIGID` members, so `_resolve_contact_slave` then DROPS the contact
  and the deck ends with zero interfaces — the stub suppressed by a contact
  that is not in the emitted deck (the #130 shape: a "what will this deck
  emit?" screen that does not reproduce the emitter's drops). Measured reach is
  one deck: over the 356-deck roster exactly one loses an interface. Not fixed
  in round 3 because the faithful predicate needs the writer's rigid-body
  resolution, which does not exist at the stub's stage — the honest fix is to
  re-evaluate the stub after `_make_interfaces`, an architectural change no
  measurement in this round covers. `bumper` reaches NORMAL TERMINATION with no
  interface at all, so the stub's own stated premise (the implicit solver
  segfaults without one) does not hold there; the injected probe `/RBODY`
  covers the real trigger.
  **CLOSED in round 4, measured-not-worth-fixing.** The forced-stub arm on
  `bumper` — the one deck the predicate reaches — ERRORs at `t = 1e-4` against
  the shipped NORMAL zero model at `t = 0.05`, so making the predicate faithful
  would REPLACE a NORMAL termination with an error termination on the only
  carrier. The wider class is inert: **53 `/INTER/TYPE7` rows on the roster
  carry the injected stub title `auto_implicit_stabilization_self_contact`**,
  and five of them (`ex_14_solid_elform_1`, `ex_04_solid_elform_2`,
  `ex_03_solid_elform_2`, `ex_02_thick_shell_elform_2`,
  `ex_27_..._penalty_implicit` — three distinct emitted models) were measured
  with the stub DELETED and are byte-inert in the iterates. The architectural
  fix (re-evaluate after `_make_interfaces`) buys nothing on this corpus.
- **An explicit `Gapmin` for SOLID-SEGMENT `/INTER/TYPE7` interfaces —
  AUTOMATIC spellings included.** The scope is the ELEMENT TYPE, not the
  spelling: k2rad writes `Igap 0` with `Gapmin 0` on every `/INTER/TYPE7` it
  emits (verified on the already-registered AUTOMATIC carrier
  `ex_26_thin_shell_elform_16` as well as on `pend.imp`), and
  `i7sti3.F:1055-1063` then takes the mesh-size branch `GAP = 0.1 * GAPMX`
  whenever no shell thickness was accumulated — `DXM` only ever takes `THK`
  (`i7sti3.F:499/506/591`), so a solid-segment main surface never reaches the
  thickness branch. Round 3 only made MORE decks reach a pre-existing
  behaviour. **ANSWERED in round 4, and the answer is a FLAG, not a default:**
  `--derived-gapmin` (with `--derived-gapmin-factor F`, default 0.005) writes
  `F x the smallest main-surface segment side`, ceiling `0.5 x` that side (the
  starter's own `WARNING 94` gate, `i7sti3.F:1075`) and never a non-positive
  value (`ERROR 785`, `:1068`). It is OFF by default and a warning names the
  starter-derived `GAP MIN` on every carrier either way; `--auto-gapmin` was
  NOT the lever, because it needs numpy + scipy and measures a different
  quantity (nodal clearance, not mesh size). The class, censused with the
  writer's own resolver over the 356-key roster, is **15 solid-only-main
  interfaces on 14 deck keys** — one of them created by round 4's own swap
  (`sphere1`); exactly **two of the 15** (`twobar`, `sphere1`) have a
  measured solver arm at the shipped factor and **13 are unmeasured** — see
  the round-4
  NOT-closed list for why that keeps it opt-in.
  `twobar`'s +1151 % internal energy is NOT the two-way loss the
  first draft of the `twoway` note blamed: the verification round changed ONE
  cell of the emitted `.rad` — the `Gapmin` k2rad leaves at 0 and the starter
  then derives as `GAP MIN = 1.0` mm on a 10 mm bar — to 0.05 and the deck
  reads IE 2866 against the LS reference 3036.17 (-5.6 %) and KE 1.127e5
  against 1.20123e5 (-6.2 %). A default Gapmin is a policy constant and must be
  measured against the population it would select, not against `twobar`.
- **The tied family's `_OFFSET` split.** Vol I R17 p.11-127 General Remark 7
  puts `TIED_*_OFFSET` / `_BEAM_OFFSET` in LS-DYNA's PENALTY family;
  `_tied_interface_type` keys on the solver and the variant only and sends them
  to `/INTER/TYPE2` on an explicit deck — at **Spotflag 27**
  (`_TIED_SPOTFLAG["SURFACE_TO_SURFACE"]`, `writer/contacts.py`), which is an
  AUTO-PENALTY variant, not a kinematic constraint (`_TIED_PENALTY_SPOTFLAGS =
  (25, 26, 27, 28)`). CORRECTED in round 4: this entry used to claim that card
  moves the secondary nodes onto the main segment and so removes the offset
  the keyword exists for (the retracted wording is quoted verbatim in the
  round-4 CHANGELOG entry). Radioss does **not** move a TYPE2 secondary
  node: no TYPE2 starter routine writes `X(1..3, .)` at all — `i2buc1.F`,
  `i2chk3.F`, `i2cor3.F`, `i2dst3.F`, `i2dst3_27.F`, `i2surfs.F`, `i2tid3.F`,
  `i2_dtn.F`, `i2_dtn_27.F`, `i2_dtn_28.F`, `interf1/i2master.F` and
  `inter2d1/inint2.F` read the coordinate array and never assign to it. FOUR
  starter interface files do move a node and none is TYPE2: the
  initial-penetration removers `i3pen3.F:187-197` (TYPE3), `i7pwr3.F:213-242`
  (TYPE7 under `INACTI` 3/4) and `i24pen3.F:317-319` (TYPE24), plus
  `in12r.F:120-133`, the TYPE12 frame transform (`inint3.F:1203-1242`). What Spotflag 27 (the glue formulation, "like 5") does not
  do that 28 ("like 1", the spotweld formulation) does is carry the offset as a
  rigid link of constant stiffness. `ContactTied.offset` is stored by the
  handler and **read nowhere**: `grep -n "\.offset" k2rad/writer/contacts.py`
  returns exactly one hit, inside a docstring. The round-5 variant is therefore
  the one-cell change that reads the field already parsed — **Spotflag 27 -> 28
  when a `SURFACE_TO_SURFACE` tie's keyword carries `_OFFSET`** — with its own
  measured reach: **0 R14-roster decks** (the two `F:` `_OFFSET` carriers,
  `05_2_welding_shell_thin` and `000_yaris_dynamic_roof_crush_01`, are both
  IMPLICIT and already take TYPE10/Spotflag 28) and 1 off-roster model (four
  `getriebekette` files). Do NOT route `_OFFSET` to TYPE10 on an explicit deck:
  the repo's own determinate tie coupon reads 209.2 at Spotflag 1/5/27 against
  a closed form of 210.0, and **67.85 = -67.6 %** at TYPE10's default STFAC.
  Measured reach today is ZERO (all 29 `*CONTACT_TIED_*` decks on
  `F:`, `C:/openradioss_run` and `Ryan_Lee` convert identically on both trees),
  so it is a fidelity item, not a live defect; `getriebekette` is the deck to
  measure both arms on.
- **The all-rigid-SSID contact class — CLOSED in round 4 for EXPLICIT decks.**
  Round 3's entry claimed that "`/INTER/TYPE7`'s secondary side is a node group
  and could not hold `/RBODY` members (the retracted wording is quoted verbatim
  in the round-4 CHANGELOG entry, which is the place for it). That is REFUTED:
  the OpenRadioss
  starter accepts them at **0 ERROR(S)** (measured on `sphere1` and on
  `mat_spring.belted-dummy`; the only extra diagnostic is `WARNING 343 INITIAL
  PENETRATIONS`), and the secondary nodal stiffness is element-based
  (`i7stslav.F:55-58 STIFINT`), not nodal-mass-based. The drop was a k2rad
  POLICY, not a solver constraint, and `starter_message_description.txt`
  contains no message coupling a rigid-body secondary node to an interface.
  Round 3's census was also short: over the full 356-key roster (the four Yaris
  `*INCLUDE` pullers excluded BY NAME) it is **7 deck keys / 8 interfaces**
  that lose a whole interface, and it mis-assigned `mat_spring.belted-dummy` —
  BOTH sides of its dropped interface are wholly rigid (SSID 148/148, MSID
  228/228), so a swap cannot restore it.
  Round 4 ships the swap on an EXPLICIT deck, default ON,
  `--no-rigid-secondary-swap` to opt out: the DEFORMABLE MSID side supplies the
  tracked nodes and the rigid SSID side the main `/SURF`, because
  `/INTER/TYPE7` is an ASYMMETRIC node-to-segment contact. This CHANGES WHICH
  SIDE IS PENALISED and the warning says so (Vol I R17 p.11-10 item 4: a
  non-AUTOMATIC contact is one-sided, so the swap reverses its direction; an
  AUTOMATIC one checks both surfaces and the swap keeps the half the deformable
  mesh can resolve). Where BOTH sides are wholly rigid the interface is emitted
  with the rigid secondary group KEPT rather than dropped. MEASURED at `nt 4`
  (`sphere1` reproduced at `nt 2`):

  | deck | shipped | round 4 | LS-DYNA reference |
  |---|---|---|---|
  | `intro-by-j.-day/contact/sphere/sphere1.k` | IE 0 (−100 %), 1 344 cycles | IE 77 830 (**−1.66 %**), KE −1.73 %, NORMAL 1 592 cycles, starter 0 ERROR / 2 WARNING | IE 79 147.3 / KE 7.0275e6 |
  | `show-cases/contact-interference/EXP_SC_CONTACT_INTERFERENCE.k` | IE 0 / KE 0 (−100 % / −100 %) | IE 1 069 (**−42.80 %**), KE 0.1293 (−16.02 %), NORMAL 1 826 cycles, 0 ERROR / 3 WARNING (the third is the press fit's 112 initial penetrations) | IE 1 868.92 / KE 0.153971 |
  | `introduction/examples-manual/load/presrcibed/boundary_prescribed_motion.blow-mold.k` | **`timeout`** — 241 934 cycles at t = 0.0061 of 0.015, 99.9 % energy error | **NORMAL TERMINATION** at t = 0.015 in 25 675 cycles (49 s), energy error −1.3 %, IE 1.091e5 (+25.25 %), KE 16.095 (−46.49 %) | IE 8.71049e4 / KE 30.0765 |
  | `ale/misc/forging-a/forging_A.k` | 0 `/INTER` | **2** `/INTER` — reach only, the deck still fails the starter with `ERROR 179 MATERIAL ID=1 DOES NOT EXIST` | — |
  | `introduction/examples-manual/material/spring/mat_spring.belted-dummy.k` | 10 of 11 interfaces | **11** (the both-rigid KEEP), starter 0 ERROR / 5 WARNING unchanged | LS's own `sleout` books −2 418 / +2 044 through that interface against 9.69e5 over all 11 — it carries nothing either way |

  Off-roster reach, counted and never quoted as accuracy (no LS reference on
  that roster): `Ryan_Lee_Examples/W2_Door_Impact*` ×5 go 3 → **7** `/INTER`
  and `W6_SETUP_SandwichImpact*` ×6 go **0 → 1**.
  Two keys are held back by the IMPLICIT gate and stay dropped —
  `implicit/basic-examples/contact-i/bumper.k` and
  `implicit/Yaris%20Dynamic%20Roof%20Crush` — see the round-4 NOT-closed list.
  The THIRD shape, a PARTLY rigid secondary side silently thinned, is NOT
  touched this round; its measured arm is recorded in the same list.
- **The non-AUTOMATIC spellings map to a TWO-SIDED `/INTER/TYPE7`.** The
  campaign re-run named four carriers where the reverse side looks engaged or
  over-stiff: `hemi`, `twobar`, `thick` — and `pend.imp`, which the
  post-review round REMOVED from this item by measurement. **`pend.imp` is an
  item-B carrier, not an item-A one.** Three arms, `nt = 4`, fresh
  conversions from `F:`, the two branch arms differing in exactly two `.rad`
  lines (`Isolid` 17 -> 1, h 0 -> 0.1) with the item-A `/INTER/TYPE7/90005`
  present in BOTH:

  | arm | IE | KE | energy error | cycles |
  |---|--:|--:|--:|--:|
  | master `b3807bd` (no contact at all) | 5.658e-06 | 21.87 | −0.0 % | 119 157 |
  | branch + `--no-default-hourglass` (contact present, `Isolid` 17) | **5.658e-06** | 21.87 | −0.0 % | 119 156 |
  | branch as shipped (`Isolid` 1, h 0.1) | **5.162e5** | 21.86 | **99.9 %** | 125 052 |

  Arms 1 and 2 agree to every printed digit, so the two-sided TYPE7 is
  measurably INERT here and the whole excess is item B's viscous hourglass on
  bodies meshed with ONE hex each. Two further facts the old entry had
  wrong: the LS reference IE is a structural zero because
  `*DEFORMABLE_TO_RIGID` switches BOTH bobs rigid at t = 0 (the deck's own
  `pend.imp.d3hsp` prints `number of deformable to rigid = 2`) and k2rad
  SKIPS that keyword, so the converted bobs are deformable `/BRICK`s and
  internal energy there is a dropped keyword rather than a spurious contact.
  **No clean probe for the two-sided item exists on this corpus yet** — one
  whose colliding parts are deformable in LS-DYNA too (`thick`, `hemi`) has
  to be measured first. `pend.imp` belongs with item B: it is the branch's
  single worst benchmark row (an energy balance that was exact at −0.0 % now
  runs at 99.9 % under a NORMAL banner) and it is filed there.
- **`IHQ 8/9/10`.** CORRECTED in round 4 — this entry used to name two
  metal-forming/assumed-strain authors and call 8/9/10 "co-rotational forms",
  and neither half was right (the retracted wording is quoted verbatim in the
  round-4 CHANGELOG entry, which is the place for it). Vol I R17 p.12-271 `*CONTROL_HOURGLASS`: `EQ.8`
  *"Activates full projection warping stiffness for shell formulations 9, 16
  and -16"* — a SHELL option, not a solid hourglass form (Remark 1, same page:
  *"Only shell forms 9, 16 and -16 use the warping stiffness invoked by
  IHQ = 8"*); `EQ.9` Puso [2000] enhanced assumed strain for 3D hexahedra;
  `EQ.10` Cosserat Point Element (Jabareen & Rubin [2008]). The assumed-strain
  co-rotational form the entry named is `EQ.6`, **Belytschko-Bindeman [1993]**.
  `k2rad/writer/mesh.py:2182-2185` already stated this correctly; the table did
  not. `_ihq_to_isolid` (`writer/mesh.py:1978-1993`) returns None for 8/9/10,
  so the section keeps its ELFORM-derived `Isolid` and `writer/mesh.py`'s
  unsupported-IHQ branch warns once per distinct IHQ. **Reach on the R14
  roster: IHQ 9 and IHQ 10 have ZERO carriers; IHQ 8 has FOUR, and all four
  state `*SECTION_SHELL` ELFORM 16 -> `Ishell 12` (QBAT, fully integrated),
  where the hourglass coefficients are physically inert** —
  `introduction/intro-by-a.-tabiei/contact/contact-spotweld/spotweld.k`,
  `show-cases/bolts/typea/explicit/mainboltaexpl.k`,
  `show-cases/contact-overview/main.k` (`run_pass = 2`) and
  `thermal/thick-thin-shells/07_metalstrip.k`. Only `mainboltaexpl` has a solid
  part (one ELFORM -1 section) and it is the only one whose conversion log
  carries the IHQ-8 line. **The `fl_exp_ihq8*` coupon family this entry used
  to name as its only roster reach does not exist** — a `find` for `*ihq*` over `F:`, `C:/openradioss_run` and
  `E:/foxcore_data` returns nothing. NO-GO, doc fix only.
- `SOLN = 1` / `TGMULT` policy (the thermal-only solution class).
- ALE mesh consolidation onto one `/PART` + `/INIVOL`, and with it the real
  ALE conversion for ELFORM 5/6/7 (see the closed entry below for the four
  measured arms that rule out the cheap version).
- the `nvh` frequency-domain family — queue row 4; OpenRadioss has no solver
  for it, so it is not an `/IMPL` recipe row.
- **ERROR 495** (`icfd`, no ICFD solver), **`ex_16_thin_shell_elform_13`**
  (`*SECTION_BEAM` ELFORM 7, 2-D plane strain), **`show-cases/contact-overview/
  mesh.k`** (a deck defect), and the **refused materials**
  (`*MAT_GAS_MIXTURE`, `*MAT_102/090/031/148/002 ANIS`).
- the **beam/truss contact-secondary asymmetry** (`_resolve_contact_slave.
  add_part_nodes` does not walk them while `_part_node_ids` does).
- **`_make_bcs`'s `*BOUNDARY_SPC` re-point vs the `*NODE` TC/RC one** — the two
  answer the same question and should share one screen.
- the **`/TH/NODE REAC*` scope** of the TC/RC nodes.
- **`*EOS_IDEAL_GAS` `T0 = 0`** (the `zero_t0_sentinel` class, one law further).
- the **four parse-time set readers** that still resolve eagerly.
- **the rigid-SSID contact class on an IMPLICIT deck** — `bumper` and
  `Yaris Dynamic Roof Crush`. `sphere1`, `EXP_SC_CONTACT_INTERFERENCE`,
  `blow-mold` and `forging_A` are closed by round 4's swap and `belted-dummy`
  by the both-sides-rigid keep. The node group CAN hold rigid nodes (the
  starter accepts them at 0 ERROR(S)); what is missing is an implicit
  stabilization that REACHES a rigid-MAIN interface — `_recipe_active` /
  `deformable_deformable_inter_ids` (`writer/contacts.py`) exclude one by
  construction, which is why `--deformable-contact-recipe` is a byte-identical
  no-op on `bumper`. That gate is the concrete thing round 5 would have to
  change and re-measure.
- **ELFORM −1/−2 → a locking-free 8-point `Isolid`**, with the numbers
  measured by round 3 and recorded in the item-B entry below.

**What round 4 deliberately does NOT close** - each entry with the measurement
that decided it and the deck that would decide it next.

1. **The mass-weighted mixed `*INITIAL_VELOCITY` re-point.** The lumper
   (`tools/modal_solve.nodal_masses_from_state`) reproduces LS-DYNA's own
   `d3hsp` rigid-body mass, CoG and inertia to **8 digits** on shell bodies
   (`translat` parts 1 and 2, `transducer` part 1) and to +0.16 % / +0.86 % on
   distorted solid bodies (`sphere1`, `matfoamsoil`); the momentum average
   reproduces the `translat` glstat's cycle-0 kinetic energy to six significant
   figures (**189.962129** against `1.89962E+02`) and returns the card's own
   velocity with zero spin in the degenerate full-coverage case, so no
   fully-covered deck would move. The solver arm moves cycle-0 KE
   **+104.2 % -> +16.1 %**, and the residual is fully attributed: Radioss's
   `/RBODY` carries the four shell nodes' own lumped rotary inertia,
   `4 x (m/4)(A + t^2)/12 = 6.65667e-04` on every diagonal
   (`NEW INERTIA 0.2642894E-02` against LS-DYNA's `0.1977E-02`). NOT shipped
   for two reasons: there is exactly ONE carrier with an LS-DYNA reference on
   356 + 501 + 36 deck files (`translat`; `Ryan_Lee_Examples/W16_SW_door_*` has
   no reference results anywhere), and `I_cm` is **singular for a collinear
   rigid body** - the rule needs a pseudo-inverse, or a rank check that falls
   back to `omega = 0`, before it can be default-ON.
2. **`ELFORM -1/-2` -> a locking-free `Isolid`.** Round 4 ships the WARNING only
   (part A, item A5). `Isolid 17` IS LS-DYNA ELFORM 2 to -0.030 % / +0.055 % on
   two byte-identical sibling meshes, while the ELFORM -1 references are
   -21.66 % / -5.78 % away; every alternative regresses more than it gains -
   `Isolid 24` loses the population's only `match`
   (`ex_27_solid_elform_-2_rigidwall`, ke_dev +9.75 % -> +15.43 %), costs
   `mainboltaexpl` -72.7 % -> -81.4 % at 5x the wall time, and sends
   `ex_14_solid_elform_-1/-2` from +314 % / +494 % to +1373 % / +2014 %. Net 4
   worse, 2 better. The round-5 measurement is NAMED: a **bending coupon meshed
   1/2/4 elements through the depth**, at `Isolid` 17/24/18/14, with a
   nu = 0.499 companion, under a load path that actually locks (pure bending or
   clamped-clamped) - round 3's cantilever measured `Isolid 17` 86 % SOFTER
   than converged, the opposite sign.
3. **The IMPLICIT all-rigid-SSID swap** (`bumper`, `Yaris Dynamic Roof Crush`).
   Six restoration arms at `nt` 2 AND `nt` 4, all `ISTOP = -2` / `MESSAGE ID
   79`: the swap reaches t = 2.0e-4 of 0.05; the swap with an explicit Gapmin
   0.14986 reaches t = 7.1e-3 (35x further) and still ERROR-terminates; the
   forced stub t = 1.0e-4; the rigid-nodes-kept arm t = 1.0e-4.
   `--deformable-contact-recipe` is a BYTE-IDENTICAL no-op there. `bumper`
   stays a NORMAL **zero model**, named. What round 5 must change: the
   `_recipe_active` / `deformable_deformable_inter_ids` gate in
   `writer/contacts.py`, which excludes a rigid-MAIN interface by construction.
4. **The PARTLY rigid secondary side, silently thinned - 10 keys, 6
   non-giant.** `transducer` (6 of 22 nodes, 27 %), `EXP_SC_PRELOAD` (274 of
   1392, 20 %), `mainboltaexpl` (68 of 1943), `doorbeam` (16 of 214), `pipe`
   (20 of 1400, a `match`), `belted-dummy` ssid 9 (39 of 49, 80 %), plus 4
   Yaris giants. The ARM is now recorded, measured on `transducer.k` at `nt 4`
   (LS reference IE 161.523 / KE 1092.45): shipped 974 cycles, IE 122.6
   (-24.10 %), KE 845.8 (-22.58 %), engine error -26.9 %; with the 6 rigid
   nodes KEPT in the secondary group, 974 cycles, IE 191.1 (**+18.31 %**), KE
   883.1 (-19.16 %), engine error **-18.9 %**, 0 ERROR(S) / 3 WARNING(S) both
   ways. Both channels improve in magnitude and the energy error improves, but
   internal energy OVERSHOOTS - one carrier is not the class, and `pipe` is a
   `match` that could be lost.
5. **The `ex_27` implicit pair.** Round 4 corrects its ATTRIBUTION only (the
   `_rigidwall` twin has no `*RIGIDWALL`); the divergence itself is untouched
   and needs a DOF-level residual dump. See the implicit-residue table.
6. **The tied `_OFFSET` `Spotflag 27 -> 28` one-cell variant** - 0 roster
   reach; `getriebekette` is the deck to measure both arms on.
7. **`ELFORM 5/6/7` -> a real ALE model** - 12 deck keys on ~7 emitted models
   (`taylor` A-D are ONE file; `advection` A == B == C, because the Lagrangian
   fallback erases the distinction). `advection_B` is the probe.
8. **The `*INITIAL_VOID_PART` MAPPING and the `/INTER/TYPE18` `Iauto 2` /
   `PFAC` / `Vref` cells.** Round 4 ships the WARNING (part A, item A5); the
   mapping waits until `ale_wavehitcol` and `cylinder_impact_B` are measured.
9. **The beam/truss contact SECONDARY** - `_contact_part_nodes` does not walk
   them while `_part_node_ids` does; 3 decks, and the only non-giant's beam has
   `n2 = 0`.
10. **The one-node `*MAT_SPOTWELD` beam** (`spotweld.k`; LS-DYNA carries it at
    length 2.0).
11. **`*CONSTRAINED_SHELL_TO_SOLID` / `_GENERALIZED_WELD_BUTT` /
    `_JOINT_SCREW`** - unregistered, 3 tiny `F:` decks at ie -100 %. **Round
    5's FIRST research item.**
12. **CNRB DOF releases** - 1 858 `F:` cards on 10 decks, 4 of them giants.
13. **Dropped from the queue with their census: `*EOS_IDEAL_GAS` `T0`,
    Ignition-and-Growth, `*CONSTRAINED_BEAM_IN_SOLID`, `*PARTICLE_BLAST`,
    `NIP > 10` - 0 carriers on 893 deck files.**
14. **`--derived-gapmin` as a DEFAULT.** The flag ships (see the answered
    round-3 entry above); making it the default does not. Censused with the
    writer's own resolver over the 356-key R14 roster, the class is **15
    solid-only-main `/INTER/TYPE7` interfaces on 14 deck keys** - one of them
    created by round 4's own swap (`sphere1`) - and **13 of the 15 have no
    measured arm**. The two that do disagree: `twobar` goes +1151 % -> -5.60 %
    at factor 0.005, and `sphere1` goes -1.66 % -> **-7.77 % at 4.1x the
    cycles**. What would decide it: the 13 unmeasured carriers, above all the
    five `thermal/welding-new/*` decks (0.0582845 each),
    `nvh/example-11-01/11.1.sbrake.k` (x2 at 0.261611) and
    `implicit/Salzburg_2017/.../4.3_General_Nonlinearity.k` (0.0657821).
    Two CORRECTIONS to the round's own pre-research, both measured with the
    resolver and cross-checked against the starter's own `GAP MIN =` echo: the
    echo appears for the SHELL-thickness branch too (`i7sti3.F:1064` sits
    inside `IF(GAP <= ZERO)`, after BOTH arms), so it is not evidence of a
    solid main - `boundary_prescribed_motion.blow-mold` (echoes 0.8905 /
    0.5170 / 0.8916), `EXP_SC_CONTACT_INTERFERENCE` (0.2) and `forging_A` are
    NOT in the class once the swap has run, because their post-swap main
    surfaces are SHELL segments. The `*CONTACT_*_INTERFERENCE` exclusion the
    flag carries is therefore a RULE with 0 measured carriers on this corpus,
    not a measured save.

15. **The `*BOUNDARY_THERMAL_*` / `*BOUNDARY_TEMPERATURE_{RSW,TRAJECTORY,
    PERIODIC_SET}` family, as a CONVERSION.** Round 4's finalize round made
    them BLOCK the `TGMULT` restatement — they are temperature drivers and a
    hard Dirichlet `/IMPTEMP` beside one would clamp the field it drives away
    (`fixtemp.F:180-199`) — but they still convert to nothing. `F:` carries
    four `*BOUNDARY_THERMAL_WELD_TRAJECTORY` decks (the `thermal/welding-new/*`
    family), all of which state `TGMULT 0.0`, so the gate's reach is 0 and none
    of them is blocked in practice today. What would decide it: whether a
    moving weld source has ANY Radioss counterpart — `/IMPFLUX` on a moving
    segment set is the only candidate, and nothing in
    `engine/source/constraints/thermic` moves a segment group with time.

16. **The `Isolid` 24 arm of the assumed-strain `ELFORM -1/-2/3`.** The A5-i
    warning is gated on `isolid != 17`, and `ex_12_solid_elform_{-1,-2,3}`
    carry an explicit `*HOURGLASS` IHQ 6, take the per-part overlay and emit
    `/PROP/SOLID/90001` at `Isolid` **24** — so the warning is silent on two of
    the roster's ELFORM -1/-2 carriers and on one of its two ELFORM-3 carriers.
    The substitution on that arm — an 8-point assumed-strain hex becoming a
    1-POINT `Isolid` 24 (`sgrtails.F:1107-1123`) — is at least as large as the
    one the warning describes. It is NOT simply given the same sentence,
    because the Isolid-24 arm is also the one that keeps
    `ex_27_solid_elform_-2_rigidwall`'s `match`: the two cannot be separated on
    a comment. What would decide it: the same bending coupon meshed 1/2/4
    through the depth that item 2 above needs.

17. **Faceting the 6-node pentahedron and the 5-node pyramid in
    `writer/contacts._solid_boundary_faces`.** Round 4's finalize round made an
    unfaceted shape clear `all_solid`, so the derived-Gapmin rule and its
    default-ON warning both STAND DOWN on such a side rather than measure a
    partial skin — the failure mode being a part that MIXES hexes with wedges,
    where the face they share is seen once and counted EXTERNAL and the minimum
    edge comes out too small. Standing down is the safe direction, not the
    complete one: a solid-only main built entirely of wedges now falls out of
    the class silently. No carrier of the 15-interface class has that shape, so
    the reach today is 0. What would decide it: a wedge-meshed contact main
    with an LS-DYNA reference — none exists on the three measured corpora.

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

- ~~**THE `*SECTION_SOLID` ELFORM → `Isolid` MAPPING, exposed by the TC/RC
  pins on three `*MAT_NULL` decks.**~~ **CLOSED in round 3 (part B), with
  one half re-scoped.** A 1-point `*SECTION_SOLID` whose deck leaves the
  hourglass control DEFAULTED now takes LS-DYNA's own default — IHQ 2 →
  `Isolid` 1 explicit, IHQ 6 → `Isolid` 24 implicit, `h` 0.1 (Vol I R17
  p.12-271 Remark 1, echoed in each deck's own d3hsp) — through the
  EXISTING `_ihq_to_isolid` remap, ON by default with
  `--no-default-hourglass`. MEASURED: `sloshing_A` goes from the TIMESTEP-LIMIT
  death below to **NORMAL at t = 2.0, 34 119 cycles, IE −0.254 %** against
  its LS reference; `sloshing_C` timeout → NORMAL at +2.823 %; `taylor_A`
  +2.562 % → +0.002 %; `rodsol` +2.884 % → −1.719 %; `ex_03_solid_elform_1`
  −20.379 % → −4.139 %, with its `_elform_2` control's `/PROP/SOLID`
  byte-identical. `sloshing_B`, the three-line twin, does not move.
  **Re-scoped, NOT closed: ELFORM −1/−2.** They are screened OUT of the
  default, because Vol I R17 p.41-104 Remark 13 says a formulation −1 hex
  has *"no hourglass energy, and the behavior is not affected by hourglass
  parameters"* — so a hourglass default has nothing to act on there. They
  are nevertheless measurably too stiff at `Isolid` 17:
  `ex_03_solid_elform_-1` is −21.72 % against its LS reference at 17 and
  **−5.87 % at `Isolid` 24, −6.96 % at 18, −6.33 % at 14**. That is a
  LOCKING item — "ELFORM −1/−2 wants a locking-free 8-point Isolid, not the
  H8C 17" — and it needs its own measurement, because
  `writer/materials._exact_all_ip` gates a `/FAIL/TAB1` `Ifail_so = 2`
  exactness claim on `elform ∈ (2, −1, −2)` AND `Isolid == 17`, and
  `Isolid` 18/14 bring their own material-based `Ismstr`/`Icpre` defaults.
  The original entry is kept below because its CAUSE analysis is what made
  the fix findable.

- **(the original entry) THE `*SECTION_SOLID` ELFORM → `Isolid` MAPPING,
  exposed by the TC/RC pins on three `*MAT_NULL` decks.** Round 2 shipped this as *"a constrained mesh
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
  escape and NAMES the risk at conversion time. *(Round 3 did the sweep and
  shipped the remap; the single-hex pull that hourglassed was at Isolid **2**
  — Hallquist, no orthogonalisation — not the Isolid 1 the default selects,
  which measures +0.002 % on `taylor_A`.)*

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
  *(Round 3 gives it the Isolid its ELFORM asks for whenever the deck leaves
  the hourglass control defaulted. What is LEFT of this entry is the screened
  set: an `ELFORM = 2` or `−1/−2` section, a preloaded deck, a `/MAT/LAW115`
  section, or `--no-default-hourglass` — those still ship `Isolid` 17 and
  still need TSSFAC <= 0.4 on a one-element coupon.)*

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

  **Round-3 correction and status.** The class is **fifteen**, not fourteen,
  at `b3807bd`: the round-3 census re-counted it over the whole database and
  `thermal-stress` joins the list (its LS reference is IE 0.0 / KE 2.78817e-9,
  which the *"LS reference not a structural zero"* clause reads as real on
  the kinetic side, exactly as it does for `quadrature_A`). Of the fifteen,
  round 3 addresses **nine by construction**: the seven
  `*INITIAL_VELOCITY_GENERATION` carriers through item C — measured cycle-0
  kinetic energy now within +0.006 %…−0.003 % of each deck's own LS-DYNA
  `glstat` where it was 0.000 — and `sphere1` +
  `EXP_SC_CONTACT_INTERFERENCE` through item A. `sphere1` is the honest
  exception: its velocity is now right and its `*CONTACT_SURFACE_TO_SURFACE`
  is registered, but the interface is still dropped for the rigid-SSID reason
  item A names, so it stays a zero model on the INTERNAL energy while its
  kinetic channel becomes exact. **The list must be re-censused AFTER the
  campaign re-run, not from this paragraph** — the #136 rule that a residual
  class counted over one round's movers is not a database census.

  **The campaign re-run censused it: fifteen → ten → NINE after the finalize
  round** (the nine round 4 will face are `ale_wavehitcol`,
  `cylinder_impact_B`, `Intermediate_fsi_flap/main_fsi`,
  `intermediate-fsi-2-flaps/main`, `bumper`, `ex_17_spring_elform_0`,
  `ex_18_spring_elform_0`, `EXP_SC_CONTACT_INTERFERENCE` and
  `thermal-stress`). The ten below is the count BEFORE `translat` was
  re-pointed (eight cleared, two new).
  The two NEW ones are the round's own, and both are named rather than counted:
  `translat` (item C's first-draft coverage rule refused an all-rigid card and
  made it inert — FIXED in the finalize round, which re-points it and names the
  +104 % over-estimate; it leaves the class again and was re-run) and `bumper`
  (item F takes it `error_engine` → NORMAL while item A's newly registered
  `*CONTACT_SURFACE_TO_SURFACE` is DROPPED for its wholly-rigid SSID side, so
  the deck terminates with no interface at all and `camp_evolve` reports
  FLAT-ZERO on every one of its 502 cycles — the #135 shape, kept in the class
  and filed as the all-rigid-SSID round-4 item). 19 of the 20 newly-NORMAL
  decks EVOLVE; `bumper` is the one that does not.

- ~~**An `*INITIAL_VELOCITY_GENERATION` over a rigid part's nodes is still
  emitted and inert**~~ — **CLOSED in round 3 (part B).** The card is
  re-pointed onto the `/RBODY` main node like the other two forms, and it
  needs NO arithmetic to keep the spin: `hm_read_inivel.F:580-617` writes
  BOTH `VR = omega*n` and `V + omega x (x − O)` on every node of an
  `/INIVEL/AXIS` group when `IRODDL > 0`, and `contrl.F:1053` puts `NRBODY`
  in the `IRODDL` minimum — so the sentence below (*"the body NO spin at
  all"*) was a docstring rationale that had never been solver-measured.
  Measured cycle-0 KE against each deck's own LS-DYNA `glstat`, all of them
  0.000 before: `sphere1` −0.003 %, `wood-post` −0.003 %,
  `projectile-block` −0.003 %, `section_solid.hourglassing` +0.006 %,
  `quadrature_A` +0.000 %, `brake`'s ROTATIONAL 1.345e7 vs 1.33808e7
  = +0.517 %, `brake_debug` inert at −4.4e-11 against LS's own 0.0, and the
  MIXED `pipe` −0.100 % → −0.005 %. A mixed card is SPLIT in place. A
  PARTLY covered body is refused and named when the card ALSO names
  deformable nodes, and RE-POINTED with the over-estimate named when it does
  not (Vol I R17 p.28-129 Remark 3 makes LS-DYNA's answer a mass-weighted
  momentum average k2rad cannot form; refusing an all-rigid card does not fall
  back on a deformable half, it makes the card inert). The first draft of
  round 3 refused BOTH and thereby un-cleared one of round 2's own six:
  `translat.k` went back to I-ENERGY = K-ENERGY = 0.000 on all 13980 cycles
  against an LS-DYNA glstat of 189.962. The three arms are in
  `_warn_inivel_on_rigid_members`; the mass-weighted arm is a round-4 item. **Named consequence:** with the body actually moving,
  `quadrature_B` and `_C` can diverge in their ALE FSI where the zero model
  terminated NORMAL — two `deviation → error/timeout` rows are expected in
  the campaign census. The original entry follows.

- **(the original entry) An `*INITIAL_VELOCITY_GENERATION` over a rigid
  part's nodes is still emitted and inert** — the uniform-translation forms were re-pointed in the
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

- **CLOSED in round 3 (part A): THE TIED-CONTACT FAMILY IS PICKED BY THE WRONG
  FIELD, AND THE CARD THAT RUNS IS SOFT.** Both halves shipped at once, as this
  entry required.

  *The family.* The sign rule `(SFST*SST + SFMT*MST)/2 < 0` is DELETED.
  `_tied_interface_type` now keys on the KEYWORD and the SOLVER: a
  non-`SURFACE_TO_SURFACE` variant is always `/INTER/TYPE2`; a
  `SURFACE_TO_SURFACE` one is `/INTER/TYPE10` on an implicit deck and
  `/INTER/TYPE2` on an explicit one. Vol I R17 p.11-33 (`SAST`) and General
  Remark 4 (p.11-125) make the negative cell a tying SEARCH DISTANCE, which
  `_tied_dsearch` still consumes; General Remark 7 (p.11-127) keys the family on
  the keyword.

  *What decided the solver split.* EXPLICIT — on the determinate two-hex coupon
  (closed form IE 210.0, merged bar 209.2) `/INTER/TYPE2` at Spotflag 1, 5 AND
  27 reproduces the bar exactly at no time-step cost, while `/INTER/TYPE10` at
  the default STFAC carries 67.85. IMPLICIT — on `05_4_2` every `/INTER/TYPE2`
  arm fails: Spotflag 25/26 by a HARD refusal (`ind_glob_k.F:4594-4599`,
  ERROR 241 for ILEV 10..25; 26 downgrades to 25 with WARNING 1177) and
  27/28/1/5 by divergence at cycles 16/8/9/19, with `dsearch`, `Ignore` and
  `Stfac` all inert (three byte-identical runs).

  *CORRECTION to this entry's own numbers.* It said the `/INTER/TYPE10` arm
  carries "68.34 / 119.6 / **-42.8 %**" and quoted a sweep "1 -> -13.0 %,
  10 -> -1.5 %, 100 -> -0.1 %". **-42.8 % is the ENGINE's own energy-error
  column, not the load-transfer deviation.** Against the merged bar (209.2) the
  deviations are **-67.6 / -24.3 / -2.63 / -0.10 %** at STFAC 0.2 / 1 / 10 / 100
  — the shipped sentence understated the default tie's loss by a factor of ~1.6
  and mislabelled the quantity.

  *The STFAC half.* `i7sti3.F:148/:444` make the tie spring `STFAC*A^2*K/V` per
  tied secondary node = `STFAC/(3(1-2nu))` times the stiffness of the element it
  welds, so `--tie-stfac auto` resolves to `100*3(1-2nu)` (120 at nu = 0.3,
  measured +0.05 %), 30 is the no-Poisson fallback (-0.76 %), and `dt` scales as
  `1/sqrt(STFAC)` (141 cycles at 0.2, 2435 at 120). Opt-in, because STFAC 10
  changes IE by -30.5 % and halves the implicit step on the welding deck. The
  all-rigid-secondary arm — which used to be a DROP — takes the derived value
  unconditionally.

  *Still open, named:* on an implicit deck the tie is a penalty spring, so a
  converged implicit weld transfers less than a constraint would. That residual
  is now a consequence of ERROR 241 and the divergence table, with `--tie-stfac`
  as the lever.

- ~~**`*SECTION_SOLID` ELFORM 5/6/7 (the 1-point ALE solids) convert to a
  LAGRANGIAN solid, silently.**~~ **CLOSED in round 3 (part B) as the SECOND
  of the two options this entry offered — warn, and say what it costs —
  because the first was MEASURED destructive.** `hm_read_prop14.F:264-267`
  refuses `Iale /= 0` on any `Isolid` but 0, 1 or 2 (ERROR 131 + 608: 9 starter
  errors on `taylor_B`, 4 on `advection_B`), and with `Isolid` 1 the remap
  takes `taylor_B` from IE +5.1 % / KE +4.9 % against its LS reference to a
  **99.9 % energy error at 198 220 cycles** and `channel_A` from −98.9 % /
  −25.6 % to **−100 % / −94.3 %**; `Iale = 2` is the same. `taylor_B/_C/_D`
  are `match` TODAY as Lagrangian, so the remap would have been a regression
  on three decks to fix none. What DID ship is the half that is unambiguous:
  ELFORM 5/6/7 are 1-point elements and LS-DYNA gives them hourglass control
  (its own d3hsp echoes `solid formulation = 11` with hourglass type 2 /
  coefficient 0.1 for a stated ELFORM 5), so item B now carries it —
  `taylor_B` +5.061 % → **+2.439 %**, `sloshing_C` timeout → **NORMAL at
  +2.823 %**. **Still open, scoped:** a REAL ALE conversion for these
  formulations, which needs an `/ALE/GRID` formulation (with no card the
  default is `NWALE = 1` "DISP", `hm_read_ale_grid.F:202-208`), an
  ALE-capable material and the inflow/void boundaries the ELFORM cell does
  not state — plus ELFORM 7's `AET` (default 4, pressure inflow/outflow),
  which is named as dropped. The original entry follows.

- **(the original entry) `*SECTION_SOLID` ELFORM 5/6/7 (the 1-point ALE
  solids) convert to a LAGRANGIAN solid, silently.** Found while correcting the `*MAT_NULL` class:
  `ale/sloshing/sloshing-c` and `-d` state `*SECTION_SOLID` ELFORM 5 beside a
  `*CONTROL_ALE`, and the emitted `/PROP/SOLID` has `Iale = 0` (read off the
  card). The only thing the conversion log says about ALE on those decks is the
  `*CONTROL_ALE` note — *"OpenRadioss keeps its default ALE advection"* — which
  reads as if the ALE scheme were preserved. Either map ELFORM 5/6/7 onto
  `Iale`, or warn that the element became Lagrangian and say what that costs.
  (ELFORM 11/12 already map to `Iale`; this is the 1-point family only.)

- **CLOSED in round 3 (part A): `*CONTACT_SURFACE_TO_SURFACE` and fifteen
  sibling contact keywords were not registered at all.** This entry's own
  numbers were a FLOOR and are corrected here rather than merely closed: it
  named **nine** spellings and "34 cards", counted from the type-0 contact
  SIDES of item C's census. The round-3 census, which opened every roster deck
  on `F:` and resolved one level of `*INCLUDE`, measures **16 spellings, 78
  cards, 44 of the 356 roster decks** — 37 of which have NO other contact, and
  **18 of the 30 decks whose OpenRadioss internal energy is zero against a
  non-zero LS-DYNA reference** carry one. The full list is
  `_SURFACE_TO_SURFACE` (36 cards / 19 decks), `_ONE_WAY_SURFACE_TO_SURFACE`,
  `_FORMING_ONE_WAY_SURFACE_TO_SURFACE`, `_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR`,
  `_FORMING_SURFACE_TO_SURFACE_MORTAR`, `_SINGLE_SURFACE`, `_SINGLE_EDGE`,
  `_SLIDING_ONLY`, `_SURFACE_TO_SURFACE_INTERFERENCE`, `_DRAWBEAD`, `_ENTITY`,
  `_AUTOMATIC_GENERAL_MPP`, `_SURFACE_TO_SURFACE_THERMAL`,
  `_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR_THERMAL`,
  `_TIED_SURFACE_TO_SURFACE_THERMAL` and
  `_TIED_SURFACE_TO_SURFACE_OFFSET_THERMAL`. All sixteen are registered from
  ONE table (`handlers._CONTACT_SPELLINGS`, 31 spellings with the `_MPP`
  siblings); `_DRAWBEAD`, `_ENTITY` and `_SLIDING_ONLY` are refused BY NAME with
  their source lines and physical consequence.

  *Left open by the fix, each measured and named:*

  - **Three of the 44 carriers still emit no interface** for a PRE-EXISTING
    reason the registration cannot touch: `sphere1`, `bumper` and
    `EXP_SC_CONTACT_INTERFERENCE` put a rigid part on the SECONDARY (SSID)
    side, so `_resolve_contact_slave`'s rigid filter emptied the node group and
    the contact was dropped with the side-swap remedy. `bumper` even
    goes `error_engine -> NORMAL` because of it, as a NORMAL-terminating ZERO
    model (IE identically 0) — the #135 shape. Whether k2rad should swap the
    sides, or emit `/INTER/TYPE25` (whose secondary side is a `/SURF`), is its
    own item with its own measurement. **ROUND 4 ANSWERED IT**: the drop was a
    k2rad POLICY, not a solver constraint — the starter accepts `/RBODY` member
    nodes in a TYPE7 secondary group at 0 ERROR(S) — and the swap now ships on
    an EXPLICIT deck. `sphere1` reads −1.66 % and
    `EXP_SC_CONTACT_INTERFERENCE` −42.80 %; `bumper` is IMPLICIT and stays a
    named zero model. See the all-rigid-SSID entry in the defect queue.
  - **`twobar` and `ring_01` leave zero and OVERSHOOT.** `twobar` moves from
    IE -100 % to **+1151 %** (37 990 against the LS reference's 3036) at an
    engine energy error of -11.3 %; `ring_01` from -100 % to +207 %. Two
    suspects were tested and only the second is the answer. One-way
    `/INTER/TYPE7` scoping where LS-DYNA is two-way is NOT it: a hand-built
    `/INTER/TYPE25` over two `/SURF`, in both k2rad's parameterisations
    (`Istf` 2 with zero Gap_max, and `Istf` 4 with `Igap0` 1000 / `Gap_max`
    1e30), develops **peak IE 0.95 and 0.78 out of 125 000** — i.e. no contact
    at all — while the TYPE7 arm peaks at 44 590, so routing the two-way
    spellings to TYPE25 is not the fix either. **The derived `Gapmin` IS.** The
    finalize round changed ONE cell of the emitted `twobar_0000.rad` — the
    `Gapmin` k2rad leaves 0, which the starter then echoes as
    `GAP MIN = 1.000000000000` on bars of 10 mm cross-section — to 0.05, and
    the same deck reads IE 2866 against the LS reference 3036.17 (-5.6 %) and
    KE 1.127e5 against 1.20123e5 (-6.2 %). The direction agrees: a one-way
    check UNDER-transfers load and cannot produce a 12x energy excess, and
    `twobar`'s own LS-DYNA glstat books 6.38 of sliding-interface energy in
    125018 total, i.e. the reference contact is nearly inactive in the window.
    The `twoway` note no longer attributes the overshoot to one-wayness; a
    default Gapmin is a round-4 item for every SOLID-SEGMENT `/INTER/TYPE7`
    k2rad emits, AUTOMATIC spellings included (a policy constant needs the
    population it selects, not one deck - and that population is the element
    type, not the spelling: `Igap 0` / `Gapmin 0` goes on all of them).
  - **`05_4_2` and `05_5_2` regress NORMAL -> ERROR TERMINATION.** Registering
    `_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR` adds a second penalty interface to
    an implicit quasi-static weld whose two plates already interpenetrate
    (1537 initial penetrations on 384 of 9984 secondary nodes), and the
    implicit Newton overflows (`|r|/|r0| = 1.96e6`, `RELATIVE R = 0.1000E+31`)
    at cycle 1. NINE arms were measured on the deck's own `.rad`, all
    ERROR except the first: delete the interface (NORMAL, 79 cycles, identical
    to master), `Inacti` 0, `Inacti` 1, `Stfac` 0.01, `Fric` 0, `GAP_MAX` 1e-3,
    `Igap` 1 (constant zero gap), `Igap` 2, `Istf` 2, and removing the tie's
    secondary nodes from the group (they do not overlap it at all). It is NOT a
    general "implicit + new penalty contact" failure — `hemi`, an implicit
    `SURFACE_TO_SURFACE` carrier, stays NORMAL and moves IE from -99.998 % to
    +265 % — so no family-level screen is justified by one model. The decision
    (accept the two rows, or screen the MORTAR family on implicit decks) is
    owed to the campaign re-run, which is where the whole-database arithmetic
    is. **The campaign re-run took the accept arm** (item A clears 21 strict
    IE-collapse carriers and costs these two NORMAL terminations, both on decks
    whose own LS-DYNA reference is IE = KE = 0, so no benchmark number is lost
    — only a status), and the finalize round added a caveat the nine arms did
    not cover: **the verdict on this pair FLIPS with the OpenMP thread count**.
    Measured on fresh conversions from `F:`, starter 0 ERRORS on every arm —
    `nt = 3`: master ERROR (ISTOP -2, cycle 5), branch NORMAL (44 cycles,
    t = 98.0, IE 28800); `nt = 4`: master NORMAL (88 cycles, IE 21810), branch
    ERROR (cycle 2). So at the campaign's own `nt = 4` the branch loses and at
    `nt = 3` it wins. Any later arm on this pair must fix `nt` and repeat, and
    every implicit figure in report 0.16 states its `nt`.

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

### The implicit residue after round 3

Round 3 (part B, item F) removed `/IMPL/DT/FIXPOINT` from the default engine
deck and that closed three whole families. This is the census of what is LEFT,
grouped the way the decks themselves group: **every one of the 28 structural
rows dies with `** ERROR: SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT **`,
`ISTOP = -2` (`imp_solv.F:2031`), and each family dies at an IDENTICAL cycle**,
which is what says one mechanism per family rather than 28 problems. Two
divergence flavours precede it, both from `nl_solv.F` (`:490-503` under
`IMCONV <= -2`): `ITERATION DIVERGE with RELATIVE R=` and the norm, when
`RR1 = sqrt(R2/R02) > 1`, and `--ITERATION DIVERGE with MAX_ITER REACHED--`.
`RELATIVE R = 0.1000E+31` is the overflow sentinel — `nl_solv.F:400/427-428`
sets `IMCONV = -2; RR1 = EP30` when the residual force norm passes 1e30.

Population: **34** roster decks with `*CONTROL_IMPLICIT_GENERAL` `IMFLAG > 0`
and status `error_engine` or `timeout` — 28 structural plus 6 frequency-domain
stalls, which are NOT the same class.

The **round 4** column below says what the round did to each family. Read it
with two cautions the round measured for itself: (a) `4.2.frf`, `6.5`,
`tensile2` and `doorbeam` are expected `error_engine` movers but the campaign
re-run is the gate, not this table; (b) the four `thermal/welding-new` rows
are BOTH A1 carriers AND the re-verdict's exclusion class — the two effects
must never be added together.

| family | decks | death | verdict after round 3 | round 4 |
|---|--:|---|---|---|
| `ex_01` thin shells `elform_2/6/16` | 3 | cycle **20**, t = 0.1052 of 1.0, identical | **FIXED** by dropping the FIXPOINT grid — `ex_01_thin_shell_elform_2` reaches NORMAL at t = 1.000, 28 cycles, IE 0.7061 vs the reference's 0.818398 (−13.72 %) | A1 raises `/IMPL/QSTAT/DTSCAL` to 10 on all three; re-run by the campaign |
| `ex_14` solids `elform_1/-1/2/-2` | 4 | cycle **33**, t = 0.004954 of 0.02 | **FIXED** — all four are ONE model (every ELFORM collapses to the same `/PROP/SOLID`); `ex_14_solid_elform_1` reaches NORMAL at t = 0.01839 with the energy error ≤ 0.8 % at every cycle, where it used to hit 99.9 % by cycle 14 | A1 carrier; re-run by the campaign |
| `ex_15` thick shells `elform_2/3/5` | 3 | cycle **38**, t = 0.00559 of 0.02 | **FIXED** — NORMAL to t = 0.01963 | A1 carrier; re-run by the campaign |
| Salzburg `4.2_Buckling_of_Beer_Can` | 1 | cycle 38, t = 0.1298 of 1.0 | **IMPROVED, not fixed** — reaches t = 0.3661 (2.8×) and its KE falls from 7.26e10 to 1.56e5 | A1 carrier; re-run by the campaign |
| beams `ex_05`, `ex_06`, `ex_07`, `ex_11` | 4 | t = 1e-5 / 0.387 / 3e-8 / 0.0945-of-0.1 | **NOT fixed** (`ex_06` moves 0.3869 → 0.3870). MAX_ITER on three; `ex_11` prints a NORMAL banner at 94.5 % of target, the #110 shape. Own mechanism — the beam property or the `/IMPL` recipe | **A1 + A2, the COMBINED arm.** All four are A1 carriers and three are also A2's only carriers (`ex_05` NSOLVR 6, `ex_06` **ARCCTL 6** — the predicate is the OR, not NSOLVR alone — `ex_07` NSOLVR 6). A2 ships OPT-IN behind `--arclength-riks` because the required second-`nt` repeat REFUTED the default: `ex_05` turns a 1.5 s `error_engine` into a 600 s TIMEOUT at t = 5e-11, and `ex_06`'s NORMAL flips to an ERROR at t = 0 between nt 4 and nt 3. With the flag ON, `ex_07` walks from t = 3e-8 to **t = 1.000** and lands at **−1.72 %** of its LS-DYNA reference while still exiting ERROR on the last increment — it buys the load path, not the answer, and is counted as ZERO movers |
| `ex_27` implicit Taylor bar ×2 | 2 | cycle 1 / 3, t ≈ 1e-7 of 8e-5 | **NOT fixed**, byte-identical with and without the grid. **The "rigid-wall class" attribution this row used to carry is WRONG and was corrected in round 4**: `ex_27_solid_elform_2_rigidwall_constrained_nodes_implicit.k` has **no `*RIGIDWALL` keyword at all** (`grep -c RIGIDWALL` = 0; its keyword list carries `*CONSTRAINED_GLOBAL` instead) while only the `_penalty_` twin has `*RIGIDWALL_PLANAR_ID` (`grep -c` = 1). Both are the SAME Taylor copper bar at 227 000 mm/s under Newmark trapezoidal at `DT0 = 1e-6`, both diverge from cycle 1 (`RELATIVE R` to 2.3e15), cutting Δt 22 times to `DT_MIN = 1e-10` where `\|r\|/\|r0\|` still sits at ≈ 5.0; the arm `DT_MAX 0 → 1e-6` (LS's own constant step) changes nothing. A real solver constraint worth recording for the `_penalty_` twin ONLY: `nl_solv.F:520` `IF (ILINE_S>0.AND.ISIGN>=0.AND.IRWALL==0)` — the line search is bypassed outright whenever a rigid wall is active — and `imp_solv.F:673-700` forces a full stiffness reform on every rigid-wall impact. What is missing is a DOF-level residual dump (`/IMPL/NONLIN/SOLVINFO`, or a higher `/IMPL/PRINT/NONL`); it is not obtainable from the cycle table. Note the grouping: `ex_27_-1_rigidwall` ≡ `ex_27_-2_rigidwall` is ONE emitted model on 2 deck keys, one row a `match` and one a `deviation` | attribution corrected (see the round-3 cell); the divergence is UNTOUCHED and is item 5 of the round-4 NOT-closed list |
| Salzburg `4.1` / `4.3` | 2 | 4.1 timeout at 0.3 % of target; 4.3 cycle 56 | **NOT fixed**. `4.3` is also the one roster deck with an `*INITIAL_STRESS_SECTION`, and its solids are ELFORM −1, so neither item B nor item F reaches it | A1 carriers; `4.3` is also one of the 15 `--derived-gapmin` carriers (derived `GAP MIN` 0.0657821), unmeasured |
| `tensile2` | 1 | cycle 349, t = 0.7701 of 1.0 | marginal (t → 0.7804): genuine near-completion nonlinearity, plus `Warning: MUMPS workspace too small. Retry` | A1 carrier, expected to move — its own arm is +7.36 %; re-run by the campaign |
| `doorbeam` | 1 | cycle 6, t = 2.6e-7 of 0.0011 | **NOT fixed**, byte-identical death | **A1 x the implicit TYPE25 drop, a COMBINED arm.** NORMAL with A1, at +380 % — which is that deck's dropped implicit interface, not A1's error. Not counted as a fix |
| `bumper` | 1 | cycle 1 | an **item A** deck (`*CONTACT_SURFACE_TO_SURFACE`, its only contact). It now reaches NORMAL — as a zero model, because its rigid SSID side still drops the interface. Re-measure after the rigid-secondary item, not here | **NOT fixed, and now NAMED rather than deferred.** B2 gates the all-rigid-SSID swap to EXPLICIT decks: six restoration arms at nt 2 AND nt 4 all die `ISTOP = -2`, and `--deformable-contact-recipe` is a byte-identical no-op because `_recipe_active` excludes a rigid-MAIN interface. `bumper` stays a NORMAL **zero model**. Item 3 of the round-4 NOT-closed list |
| `05_1` / `05_2` welding | 2 | cycle 26 / cycle 0 | **items A + D.** Re-measure after the campaign re-run | **re-verdicted `not_comparable` BY CONSTRUCTION** (campaign bookkeeping, a DEFINITION change and not a fix): `*LOAD_THERMAL_D3PLOT` has no Radioss counterpart, the LS-DYNA reference internal energy is identically 0 on all four rows, and the `nt` flip is OpenMP nondeterminism — `05_4_2` terminates NORMAL only at `nt = 3`, and three identical `nt = 3` runs give IE 1.611e4 / 2.428e4 / 2.217e4, a 51 % spread. `openradioss.status` is UNTOUCHED. The same four rows are A1 carriers and their A1 result is reported separately — never added to the −4 |
| Yaris roof-crush / door-sag | 2 | cycle 0 | `run_pass = 2` giants — **do not launch** | `run_pass = 2` giants — still **do not launch**; both are A1 carriers and are RE-CONVERTED only |
| `nvh` frequency-domain 5.3, 5.4, 5.5, 10.2, 8.11 ×2 | 6 | cycle 0, 600 s, `final_time = 0.0` | **NOT an `/IMPL` recipe row at all.** SSD / ERP / PSD frequency-domain requests; OpenRadioss has no frequency-domain solver. They belong to queue row 4 | unchanged — queue row 4, no frequency-domain solver |
| `6.5` / `4.2.frf` | 2 | cycle 11 / 4 | MAX_ITER, same neighbourhood; `6.5`'s sibling `6.5.tbl.psd.prepressure.k` is `normal` at IE −0.38 % | **FIXED by A1.** `4.2.frf.cant-1` goes from 4 cycles + `ERROR: SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT` to **104 cycles at t = 1.000**, IE 7922 against the LS-DYNA reference 7946.31 (**−0.31 %**), reproduced at `nt` 3 AND `nt` 4; `6.5.tbl.psd.prepressure-1` +0.03 % |

Two smaller findings from the same census. **Both were text-only and both
were FIXED in the post-review round** (the entries stay for their measured
census, which is round-4 input):

- ~~**`*CONTROL_IMPLICIT_SOLUTION` `NSOLVR` is parsed and never used.**~~
  **The field comment is CORRECTED** (it now says parsed-and-unused and names
  the right keyword); the `/IMPL/LINEAR` gate below is still not implemented.
  `state.py` used to declare `nsolvr: int  # solver (11=MUMPS,12=PARDISO)` — that
  comment describes `*CONTROL_IMPLICIT_SOLVER`'s `LSOLVR`, not this field.
  `handlers.py` reads it; `_make_engine_implicit` never looks at it and always
  writes `/IMPL/NONLIN/1`. Census over the 34: **`NSOLVR = 1` (LINEAR) on 8** —
  `ex_01` ×3 and the nvh 5.4 / 5.5 / 10.2 / 8.11 ×2 — with `ex_01`'s own d3hsp
  printing `solution method … 1 / eq.1: linear`; **12 on 21**; **6 on 2**
  (`ex_05`, `ex_07`). Measured, `/IMPL/LINEAR` turns `ex_01` into NORMAL at
  IE −22.6 % — WORSE than the −14.12 % dropping the FIXPOINT grid already gives
  on the shipped combined arm (−13.7 % before round 4's `--qstat-dtscal 10`),
  and it solves in one step so the deck loses its 100-state time history; on an
  `NSOLVR = 12` deck it produces garbage that only looks like success (`ex_14`
  KE 3.75e9 against 3.94e7). So: correct the field comment, and if `/IMPL/LINEAR`
  ever ships, gate it on `NSOLVR ∈ {1, -1}` and NAME the lost history.
- ~~**The `RCTOL` warning's stated reason is wrong on 15 of these decks.**~~
  **FIXED in the post-review round.** `RCTOL = 1.00000E10` is LS-DYNA's
  documented "force criterion off" idiom — Vol I R17 p.12-362 Remark 5,
  verbatim: *"By default, residual norm ratio (RCTOL) criterion is effectively
  disabled (RCTOL = 10^10)"* — and `assembly.py` used to tell the reader
  *"This usually means an all-blank leading card shifted the fixed-format
  columns — check the card"*. The fallback to `ECTOL` was always right; the
  warning now names the disabled-criterion idiom first and keeps the
  column-shift as the secondary reading.

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
