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
  `*CONTACT_..._TIEBREAK` → `/INTER/TYPE7` (contact-only, cohesive bond warned);
  the impact/blast materials `*MAT_JOHNSON_HOLMQUIST_CERAMICS`/`_CONCRETE` →
  `/MAT/LAW79`/`LAW126` and `*MAT_ELASTIC_FLUID` → `/MAT/LAW6` +
  `/EOS/POLYNOMIAL`.
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
  "keep the mesh, warn about the rest"), `*ELEMENT_BEAM_OFFSET` eccentricities
  (would need synthesized rigid links), and `*ELEMENT_SEATBELT*`.
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
  `/TH/MONV` (see CHANGELOG). **Open for batch 2:** `*AIRBAG_WANG_NEFSKE*`
  (a `/PROP/INJECT1` per inflator gas + one vent-hole block per orifice),
  `*AIRBAG_HYBRID*` (`N_gases > 1` + a `/MAT/GAS` per species),
  `*AIRBAG_INTERACTION` (`/MONVOL/COMMU1`), the fabric porosity family
  (`FLC`/`FAC`/`FVOPT` → an `Nporsurf` porous-surface block or `/LEAK/MAT`),
  named vent-hole SURFACES (`surf_IDv`, which needs the bag split into a bag
  part and a vent part), and `*AIRBAG_PARTICLE` (`/MONVOL/FVMBAG1`, a
  different solver).
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
