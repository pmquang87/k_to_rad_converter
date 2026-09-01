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
  digits. Radioss has no truss element, so the axial-only muscle becomes a
  spring — which is what an LS-DYNA truss states anyway.
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
- `*CONTACT_TIED_SURFACE_TO_SURFACE[_OFFSET]` negative-offset discriminator
  `(SFST*SST + SFMT*MST)/2 < 0` → `/INTER/TYPE10` penalty tie (else TYPE2) —
  **done** (dyna2rad cc:220).
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
  (`tools/modal_buckling.py`, Euler-validated to 0.001 %). Shells are now also
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
  **Still open (Milestone 2):** the thermal SOLVER controls
  (`*CONTROL_THERMAL_{SOLVER,TIMESTEP,NONLINEAR}` → the `/THERM` engine cards
  and `/DTTHERM`), the flux/convection/radiation boundaries
  (`*BOUNDARY_{FLUX,CONVECTION,RADIATION}[_SET]` → `/IMPFLUX`, `/CONVEC`,
  `/RADIATION`), the richer thermal materials (`*MAT_THERMAL_CWM`,
  `_ORTHOTROPIC`, `_ISOTROPIC_TD`, `_ISOTROPIC_TD_LC`), the per-element and
  per-section temperature spellings (`*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT`,
  `_VARIABLE_{BEAM,SHELL}`, `*LOAD_THERMAL_RSW`) and the external-field loads
  (`*LOAD_THERMAL_D3PLOT`, `_BINOUT`, `_TOPAZ`) — every one of them recognized
  and named in the conversion log today. Two measured limits remain: a
  `*MAT_ELASTIC` shell is restated as `/MAT/LAW36` so it CAN expand, but a
  material shared between shell and solid parts is left on LAW1 and its
  expansion stays inert on the shells; and the solid path diverges when a run
  of elements is free to TRANSLATE laterally as a group — the cure is one
  lateral anchor per cross-section (an end clamp is NOT the trigger).

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
- **`*NODE` `TC`/`RC` → `/BCS`** *(remaining, and the largest of these by
  incidence)* — the card's own constraint codes (0 none, 1 x, 2 y, 3 z, 4 xy,
  5 yz, 6 zx, 7 xyz, global system) are read and NAMED but not converted, so
  those degrees of freedom are free in the emitted model. **721 of 2346 corpus
  decks write a non-zero cell.** The mapping itself is trivial — the codes are
  the same triples `*BOUNDARY_SPC_NODE` states one flag at a time, and the
  `/BCS` writer already exists — what it needs is SCREENING, and that is what
  makes it a campaign rather than a patch:
  - p.35-3 Remark 1, verbatim: *"No attempt should be made to apply boundary
    conditions to nodes belonging to rigid bodies (see \*MAT_RIGID for
    application of rigid body constraints)."* Every rigid-body secondary node
    has to come out, across `*MAT_RIGID` parts, `*CONSTRAINED_NODAL_RIGID_BODY`
    and the synthesized element-free masters.
  - A DOF already driven by `/IMPVEL` or `/IMPDISP` must not also be pinned;
    the two fight over the same slot.

  **How much screening is actually needed is measured, not assumed:** of the
  721 carrying decks, **278 (39 %) also carry a rigid body or a prescribed
  motion** — 139 a `*MAT_RIGID` / `*CONSTRAINED_NODAL_RIGID_BODY` /
  `*CONSTRAINED_EXTRA_NODES`, 211 a `*BOUNDARY_PRESCRIBED_MOTION_*` — so a
  naive pass would be wrong on two decks in five, while the other 443 (61 %)
  would be safe. That split is the case for the flag: most carriers get a
  correct model immediately, and the campaign can concentrate on the 278.

  **Ship it behind an opt-in `--node-tc-rc-to-bcs` (default off)**, the way
  `--ams`, `--tet10-to-tet4`, `--deformable-contact-recipe` and `--auto-gapmin`
  are opt-in, so the 721 decks get a route to a correct model without changing
  the default for everyone; then run the campaign and consider flipping it.
  Validate with a with/without twin on a deck that carries both TC/RC and a
  prescribed motion on the same node, and a second on a rigid-body node.
  Measured consequence of the current state, so the campaign has a target: a
  spring-mass coupon whose anchor carried `tc=7 rc=7` drifted 6.68 mm against
  an intended 0.317 mm amplitude, under NORMAL TERMINATION.
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
