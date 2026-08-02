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
`*PART`, `*PART_COMPOSITE` (+ `_TITLE` / `_LONG` / `_CONTACT`; `_TSHELL` /
`_IGA_SHELL` warn and fall back — see **Composites**), `*SECTION_SHELL`
(+ `_TITLE`; every card SET under one header, not just the first, striding over
the `ICOMP` angle cards, the keyword-option card and the ELFORM 101–105
user-shell cards 5/5.1/5.2; `ICOMP = 1` reads the card-3 `B1..B8` per-layer
material angles, and a negative card-1 field 6 `QR/IRID` binds an
`*INTEGRATION_SHELL` rule — see **Composites**),
`*INTEGRATION_SHELL` (user through-thickness integration rules: per-layer
thickness `WF_i`, material `PID_i`, `ESOP = 0/1` — see **Composites**),
`*SECTION_SOLID`, `*SECTION_BEAM`
`*ELEMENT_SHELL_THICKNESS` / `_BETA` (+ every `_THICKNESS`/`_BETA`|`_MCID`/
`_OFFSET`/`_DOF` combination): the nodal thicknesses `THIC1..THIC4` become the
element's own `Thick` field — the arithmetic mean over the 3 or 4 corners, with
the part's `*SECTION_SHELL` thickness substituted for every ZERO or blank cell,
which is LS-DYNA's own per-value rule (Vol I R17 Remark 1; blank and `0.` are
the same input there). An all-zero card leaves `Thick=0`, the documented "use
the `/PROP/SHELL` thickness" value. `BETA` becomes the element's `Phi` field in
degrees — but **OpenRadioss reads that column only for `IGTYP` 17/51/52**
(`corthini.F:202-217`, `:429-435` take the layer angle from the property alone),
so on a part k2rad routes to `/PROP/TYPE9`/`TYPE10`/`TYPE11`/`TYPE16` a uniform
`BETA` is FOLDED into that property's reference angle instead (and a
per-element *variation*, which one property cannot express, is warned about).
On a `*PART_COMPOSITE` part (`/PROP/TYPE51`) the element angle is honoured by
the solver and is left where it is.
`MCID` (a coordinate-system id, **not** an angle), the `_OFFSET` mid-surface
offset and the `_DOF` scalar nodes have no Radioss element field and are
dropped with a counted warning. **Any other `*ELEMENT_SHELL_<option>` — known
or not, including `_COMPOSITE` and `_SHL4_TO_SHL8` — still keeps every element**
whose node ids the deck actually defines (an all-integer option card can imitate
connectivity, so the candidates are re-checked against the node table before
they are emitted, and the dropped count is reported). The one whole-block
exception is `_NURBS_PATCH`, an isogeometric patch rather than a mesh: its card
holds polynomial orders where an element card holds node ids, so it is skipped
and warned about
`*ELEMENT_BEAM_ORIENTATION` → a synthesized `/NODE` at `pos(N1) + (VX,VY,VZ)`
wired into the beam's `node_ID3` (raw vector, unnormalized; one node shared per
distinct `N1`+vector; the vector is rotated with a `*INCLUDE_TRANSFORM` TRANID).
A zero vector creates nothing and leaves the starter's own `INFO 2093` default
(`N3 := N2`); a vector parallel to the beam axis is warned about.
`*ELEMENT_BEAM_OFFSET` end offsets are dropped with a counted warning; any
other `*ELEMENT_BEAM_<option>` keeps its elements
`*ELEMENT_PLOTEL` → an inert 2-node `/SPRING` on a synthesized `/PART` +
`/PROP/TYPE4` id 10000000 (the id LS-DYNA assigns PLOTELs) with `K=0`, `C=0`,
`MASS=1.1e-15`: no stiffness, no nodal stiffness, and a spring time step the
starter prints as 0.55 s, so it never governs. The `1.1e-15` per element does
reach the starter's TOTAL MASS echo in its 11th significant digit; every part
mass, the time step and the result history are unchanged. Because the spring
carries no stiffness, a node attached to nothing else still counts as FREE for
the implicit singularity guard
`*ELEMENT_DISCRETE` + `*SECTION_DISCRETE` + `*MAT_SPRING_ELASTIC` /
`*MAT_SPRING_NONLINEAR_ELASTIC` / `*MAT_DAMPER_VISCOUS` → `/PROP/TYPE4`
(SPRING) `/SPRING` connectors (grounded `N2=0` springs get a fixed ground node
+ `/BCS`). An element oriented by a `*DEFINE_SD_ORIENTATION` (`VID`) becomes an
oriented `/PROP/TYPE8` (SPR_GENE) whose local DOF 1 acts along that orientation's
`/SKEW` axis (only TYPE8 carries a `skew_ID`); a `DRO=1` torsional section and an
unresolvable `VID` (`IOP=1/3`, which dyna2rad lacks too) stay warned + skipped

Elements are emitted **per `*PART`**, so an element whose `PID` no `*PART`
defines cannot be written at all. Rather than let that mesh disappear quietly,
the conversion opens with an orphan-element guard: one `MESH LOSS` warning
naming every missing part id and how many shells / solids / beams / discretes
went with it. It fires on an `*INCLUDE` that did not resolve, a `PID` typo, a
deck assembled from a subset of its parts, and on any `*PART` variant the parser
does not yet recognize.

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
`*MAT_JOHNSON_COOK` (015) → `/MAT/LAW2` (PLAS_JOHNS) with the native
`A/B/N/C/EPS0` flow stress and `M/TM/TR` thermal softening (`rhoC_p` = `RO·CP`
— LS-DYNA's CP is per *mass*, Radioss's per *volume*; blank `EPS0` takes the
LS-DYNA default 1.0 rather than dyna2rad's 0, which trips starter ERROR 298;
`E` falls back to `2G(1+ν)`). When the `*PART` attaches an `*EOS_*` (`EOSID`;
or — warned — an `*EOS_*` sharing the material id that no part in the deck
binds, k2rad's pairing convention; a part-bound same-id EOS belongs to that
binding and the material stays LAW2, exactly like dyna2rad), the material
reroutes to the
hydrodynamic `/MAT/LAW4` (HYD_JCOOK) + the `/EOS` rebound to the material id —
dyna2rad's law-choice rule — with `PC`→`Pmin` (forced negative) and `TR`→`T0`
(initial temperature; deliberately NOT dyna2rad's `TR`→`Tmax` quirk, which
would disable thermal softening above room temperature). Failure: `D1-D5` →
`/FAIL/JOHNSON` (`D3` forced negative — the σ* triaxiality conventions run in
opposite signs; `EPSILON_DOT_0` = `EPS0` so the `D4` rate term keeps the
material's reference rate, unlike dyna2rad's 0; `EROD≠0`→`Ifail_so=2`);
`DTF>0` → `/FAIL/GENE1` `dtmin`, which *suppresses* `D1-D5` on the shell path
and is ignored on the EOS path (both dyna2rad rules, warned). `PC` on the
LAW2 path, `EFMIN` (no `EPSF_MIN` slot in the radioss2017 `/FAIL/JOHNSON`),
`VP=1`/`RATEOP`, `SPALL`, `IT`, `C2` and `NUMINT` are dropped with warnings
`*MAT_SIMPLIFIED_JOHNSON_COOK` → `/MAT/LAW36` (σ = A + B·εpⁿ sampled into an
auto-generated yield table, capped at `SIGMAX`; a nonzero `C` converts the
`(1 + C·ln ε̇*)` rate term as a sampled multi-rate curve family on LAW36's
`N_funct`/`Eps_dot_i` block instead of being dropped)
`*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE` (099) → `/MAT/LAW2` with the
native `a/b/n/c` (dyna2rad's isotropic reduction): `EPPFR`→`EPS_p_max`,
`min(SIGSAT, SIGMAX)`→`SIG_max0` (blanks take their LS-DYNA 1e28 defaults so
one blank cannot discard the other's real cap), `Fsmooth=1`, and `PSFAIL>0` →
a flat `/FAIL/FLD` limit curve at `PSFAIL + A/E` over minor strain −1..1
(dyna2rad's exact 2-point construction). The `LCDM` orthotropic damage curve
has no isotropic counterpart — dropped loudly, damage evolution not reproduced
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
Hyperelastic rubbers (dyna2rad's law choices, constants followed exactly):
`*MAT_BLATZ-KO_RUBBER` (007) → `/MAT/LAW42` fixed form (`Mu_1=G`, `alpha_1=2`,
`Nu=0.463`); `*MAT_MOONEY-RIVLIN_RUBBER` (027) → `/MAT/LAW42` with `Mu_1=2A`,
`Mu_2=−2B`, `alpha=±2`, `Nu=PR` verbatim and dyna2rad's 500-point `funIDbulk`
bulk-scale curve (reproduced as-built, including its C++ integer-division
`j^0` terms — the shipped converter is the validation reference), or, when
`LCID` names a parsed test curve, `/MAT/LAW69` `LAW_ID=2` with the curve id
unmodified (the starter runs the Mooney-Rivlin fit; `SGL/SW/ST` are NOT
applied on this path, warned); `*MAT_OGDEN_RUBBER` (077_O) `N=0` →
`/MAT/LAW42` (`mu_i/alpha_i` 1:1 — pairs 6-8 warn-dropped, the `/BEGIN 2022`
radioss140 card has 5 slots; `Nu=|PR|` with the Mullins `PR<0` warning;
`I_form=2`; `BETAI>0` terms embedded as `Gamma_i=GI`, `Tau_i=1/BETAI`) or
`N>0` → `/MAT/LAW69` (`LAW_ID=int(DATA)`, `N_PAIR=N`, `LCID1` rescaled to
engineering stress-strain by `1/SGL`, `1/(SW*ST)` into a `_Duplicate`
function; the `GI/BETAI` terms are dropped-with-warning on this path, and
`G`/`SIGF` damping too — dyna2rad's `/VISC/PLAS` only exists from the
radioss2025 input format); `*MAT_HYPERELASTIC_RUBBER` (077_H) `N=0` →
`/MAT/LAW95` (`C10..C30` 1:1 in the Radioss column order, incompressibility as
`D1=|2/K|`, `K=2G(1+PR)/3/(1−2PR)`, `G=2(C10+C01)`; blank `PR` reproduces
dyna2rad's `K=2G/3`, i.e. ν=0 — warned; its solid sections are emitted with
`Ismstr=10`, which the starter would force anyway — WARNING 1200) or `N>0` →
`/MAT/LAW69`; its
`Gi/BETAi` list becomes `/VISC/PRONY` of the material id on BOTH branches
(`Beta_i` used directly, no inversion). `*INITIAL_FOAM_REFERENCE_GEOMETRY`
(`_RAMP`) → one `/XREF` per intersecting part with the stress-free reference
coordinates (`NDTRRG`→`Nitrs`); emission follows dyna2rad (unconditional, the
material `REF` flags only drive coverage warnings), but parts the starter
would reject are warn-skipped instead (solid `/XREF` accepts laws
1/35/38/42/70/88/90 only — ERROR 2014 — and 8/4-node solids — ERROR 2013),
and the kept parts' solid sections switch to `Ismstr=10` (starter ERROR 2013
otherwise on the fully-integrated `Isolid=17`); `REF=1` without usable
reference geometry is warned
`*EOS_LINEAR_POLYNOMIAL` → `/EOS/POLYNOMIAL`, `*EOS_GRUNEISEN` → `/EOS/GRUNEISEN`,
`*EOS_IDEAL_GAS` → `/EOS/IDEAL-GAS` (γ = Cp/Cv, P0 = ρ(Cp−Cv)T0)

### Composites

Every law in this family is **orthotropic- or composite-class** in the starter
(`PROP_SHELL = 2`), and `/PROP/SHELL` (IGTYP 1) accepts only classes 1 and 5 — so
each converted part is repointed from its section's isotropic property onto a
synthesized orthotropic one, the same `/PROP`-split mechanism the LAW128 path
uses. Without that the starter hard-fails with **ERROR 3047**, which is what
dyna2rad's own MAT_054/055 route does.

`*MAT_ORTHOTROPIC_ELASTIC` (002, + `_TITLE`) → `/MAT/LAW93` (ORTH_HILL) on a
`/PROP/TYPE11` (SH_SANDW) shell or `/PROP/TYPE6` (SOL_ORTH) solid. **The Poisson
conversion is the one real numeric trap**: LS-DYNA states its compliance matrix
with `−ν_ba/E_b` in the (1,2) slot and calls `PRBA` the *minor* ratio, while
Radioss states it with `−NU12/E11` (`hm_read_mat93.F:203`) and derives
`NU21 = NU12·E22/E11`. Reciprocity therefore gives `NU12 = PRBA·EA/EB`,
`NU13 = PRCA·EA/EC`, `NU23 = PRCB·EB/EC` — a naive 1:1 copy is wrong by `EA/EB`,
which for a typical UD ply is an order of magnitude. Note the shear swap
(`GBC → G23`, `GCA → G13`) and that this is the **opposite** of LAW127 below.
MAT_002 is purely elastic while LAW93 is Hill plasticity, so `sigma_y = 1e30` and
all `R** = 1.0` keep the yield surface unreachable. Zero `EB`/`EC` take the
starter's own fallbacks instead of dyna2rad's unguarded `inf/NaN`, and an
unstable `NUij·NUji ≥ 1` pair is warned before the starter's ERROR 3068/307.

`*MAT_ANISOTROPIC_ELASTIC` / `*MAT_002_ANIS` (the 6×6 C-matrix dialect) is
recognized but **deliberately not emitted**: `/MAT/LAW93` carries nine
engineering constants and has no home for the 12 anisotropic coupling terms.
dyna2rad converts this dialect to a LAW93 with **all moduli zero and no
warning** — a silently stiffness-free material; k2rad warns loudly, names the
referencing parts, and reports it under *recognized but not emitted*.

`*MAT_ENHANCED_COMPOSITE_DAMAGE` (054 / 055, + numeric aliases) → `/MAT/LAW127`
(ENHANCED_COMPOSITE) on a `/PROP/TYPE11`. The strengths (`XT/XC/YT/YC/SC`), the
`SLIM*` stress-limit factors, the `DFAIL*` strains-to-failure, `ALPH/BETA/FBRT/
YCFAC/EFS/EPSF/EPSR/TSMD/NCYRED/2WAY/TI` and the five strain-rate curves are 1:1.
**Poisson is copied RAW here** — `hm_read_mat127.F90:127-129` reads `PRBA→nu21`,
`PRCA→nu31`, `PRCB→nu32` and performs the reciprocity step itself, so applying
the LAW93 rescale would double-apply it (the two never share a helper). `PFL`
becomes LAW127's element-deletion `RATIO = |PFL|`, and a `TFAIL` in
`0 < TFAIL <= 0.1` — LS-DYNA's *absolute* minimum-dt criterion; the band
switches at **0.1**, not 1 (Vol II R17 p.2-441) — additionally emits a
`/FAIL/GENE1` of the same id carrying `dtmin`. `TFAIL > 0.1` is the *ratio*
`dt/dt₀` form, which Radioss's absolute `dtmin` cannot express, so it is
warn-dropped; it does not survive in the LAW127 `TFAIL` column either, because
`hm_read_mat127.F90` never fetches that field. `CRIT = 55` (Tsai-Wu) has no LAW127 switch — the law is Chang-Chang
only — and is warned loudly rather than dropped silently as dyna2rad does
(whose MAT_054 and MAT_055 output is byte-identical); `/MAT/LAW25` (COMPSH)
`Iform=0` is the Tsai-Wu law if that criterion is essential. `SOFT`/`SOFT2`/
`SOFTG` (crashfront softening), `KF` and `DT` have no columns and are warned.
LAW127 is a 2026-format law: the deck stays at `/BEGIN 2022`, every field reads
correctly, and the only cost is one cosmetic starter `WARNING 100211` — the same
trade-off LAW128 already ships under (**verified against `starter_win64.exe`:
0 errors, and the echo reproduces every modulus, ratio and strength exactly**).

`*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC` (037, + `_ECHANGE` /
`_NLP_FAILURE` / `_NLP2` / `_ECHANGE_NLP_FAILURE`) → `/MAT/LAW43` (HILL_TAB) on a
`/PROP/TYPE9`. MAT_037 is transversely isotropic, so the single Lankford r-bar
fills all three slots: `r00 = r45 = r90 = |R|` (`R < 0` requests a stabilized
scheme, not a negative ratio), with `C_hard = 0` and `Iyield0 = 0`. LAW43 is
**tabular-only** — no `SIGY`/`ETAN` slot — so `HLCID = 0` synthesizes a bilinear
`/FUNCT` `[(0, SIGY), (1, SIGY + ETAN)]`. The slope is `ETAN` **verbatim**: the
LAW43 curve is stress vs *plastic* strain and MAT_037's `ETAN` is already the
plastic hardening modulus (Vol II R17 p.2-398, against p.2-172 where
`*MAT_PLASTIC_KINEMATIC` calls its same-named field a *tangent* modulus — only
that one needs the `H = E·ETAN/(E−ETAN)` rescale). A negative `ETAN` is
LS-DYNA's include-normal-stresses flag, so the magnitude is used and the flag
warn-dropped. dyna2rad writes the same slope but then never binds the curve at
all (a missing pair of braces at
`convertmats.cxx:3100-3102` overwrites `func_IDi[0]` with `HLCID = 0` in both
branches → starter ANCMSG 366). `IDSCALE → FUNCT_IDE` and the `_ECHANGE`
Young's-modulus evolution `EA/COE → EINF/CE`. An `ICFLD` forming-limit curve
becomes a `/FAIL/FLD` of the same id with `Ifail_sh = 2` and `Istrain` from the
option (3/5 → 2, 4 → 1); `STRAINLT` would map to the FLD `ALPHA` field, which
does not exist in the `FORMAT(radioss2019)` block a `/BEGIN 2022` deck reads, and
is warn-dropped.

`*MAT_LAMINATED_GLASS` (032, + `_TITLE`) → a synthesized **`/MAT/PLAS_BRIT`
(LAW27) pair** — a brittle glass and a ductile polymer interlayer — bound per
integration point by a layered `/PROP/TYPE11`. Following dyna2rad the polymer
inherits the LS-DYNA MID (so existing references resolve) and the glass takes a
fresh id from the new `next_mat_id()` guard. The `F_i` array selects the phase
per layer with **LS-DYNA's polarity** (`F_i = 0` → glass, `≠ 0` → polymer):
dyna2rad has two contradictory implementations of this and its SH_SANDW one both
inverts the test *and* mutates the `/PART` mat_ID inside the layer loop, so every
layer after the first polymer one also becomes polymer. Only the glass can fail,
so `EFG` becomes a brittle-damage ramp (`EPS_t = EFG`, `EPS_m = EFG+0.05`,
`EPS_f = EFG+0.1`) and the polymer keeps the never-damage defaults. `ETG`/`ETP`
go straight into the LAW27 `b` (with `n = 1`, `b` **is** `dSigma/dEps_plastic`)
— the manual names both fields "Plastic hardening modulus" (Vol II R17
p.2-314/315), so no tangent-modulus rescale applies. Layer thicknesses come from
the `*INTEGRATION_SHELL` rule the material requires, so a real 0.8/0.2/0.2/0.8
windshield converts as written; a deck that references no rule still gets the
even split, and still says so.

`*PART_COMPOSITE` (+ `_TITLE` / `_LONG` / `_CONTACT`, and the optional
`OPTCARD`) → `/PROP/TYPE51` (stack) + one `/PROP/TYPE19` (PLY) per layer,
replacing the section-derived property for that part. `ELFORM` → `Ishell` through
the same `_elform_to_ishell` mapping (and the same `--shell-formulation` option)
every other shell property uses; `NLOC` 0/−1/+1 → `Ipos` 0/4/3; an explicitly
given `SHRF` → `Ashear` (a blank field keeps Radioss's 5/6 rather than
LS-DYNA's 1.0 default, which would silently stiffen transverse shear by 20%
against both dyna2rad and every other k2rad shell); each ply's
`B_i` rides on its own `delta_phi`. **Each ply takes two lines** on the TYPE51
card — the ply card plus a mandatory blank — because the importer counts free
cards and divides by two. Layers with `MID ≤ 0` or zero thickness are LS-DYNA's
*missing ply* padding and are filtered by identity, not by count: dyna2rad
shrinks `NIP` but still walks the leading indices, so a hole in the middle
silently drops the **last** ply there. The layup's orthotropy system comes from
the **first orthotropic ply material**, which is what LS-DYNA specifies (Remark 1
— later plies' AOPT/BETA are ignored); dyna2rad reads ply 0 unconditionally and
loses the axes when ply 0 happens to be isotropic. `MAREA`, the `OPTCARD` `IRPL`
integration rule, `_CONTACT`'s `OPTT`, `TMID`, `ADPOPT` and `THSHEL` are
warn-dropped. **`_TSHELL` / `_IGA_SHELL` and an empty layup warn and fall back to
a plain shell property carrying the summed layup thickness — the part and all
its elements are always emitted.** (Before this batch `*PART_COMPOSITE` had no
handler at all, so the whole *part record* vanished and took its entire mesh with
it, silently.)

`*SECTION_SHELL` **`ICOMP = 1`** → the per-layer material angles of the
`/PROP/TYPE11` layup. The flag declares a layered orthotropic/anisotropic
section — "A material angle in degrees is defined for each through-thickness
integration point. Thus, each layer has one integration point" (Vol I R17
p.41-67) — and the angles ride on the card-3 `B1..B8` block, eight values per
card over `ceil(NIP/8)` cards (p.41-70). Each `B_i` goes verbatim into that
layer's `Phi_i` (no sign flip: both codes measure counter-clockwise about the
shell normal) and is **added** to the material's own `AOPT`/`BETA` reference
rotation, the same composition `*PART_COMPOSITE`'s per-ply `B_i` uses. A blank
`NIP` still reads one card (LS-DYNA's default is 2.0); `NIP > 10` clamps the
layers *and* the angles; a truncated angle block is padded with zeros and
warned, because a half-read `[0/45/-45/90]` is a different laminate, not a
slightly wrong one. **Before this, a composite section silently degraded to a
unidirectional one** — four 0° layers instead of `[0/45/-45/90]` is 2.6× the
axial membrane stiffness (measured, see below). **dyna2rad drops these angles
entirely on a thin shell:** its `p_ConvertSectionShell`
(`convertprops.cxx:641-765`) dispatches on the *material* keyword alone and
reads `LSD_ICOMP` only as a `*MAT_FABRIC` `NIP`-normalization switch
(`:1704-1713`, `:3346-3351`); the per-layer `LSD_B` array is read on its
`*SECTION_TSHELL` composite path and nowhere else (`:4528-4540`).

`ICOMP = 1` carries **angles only** — there is no per-layer thickness or
material field anywhere on the keyword — so on its own the section thickness
stays split evenly and the warning names where unequal plies would have to come
from (`*PART_COMPOSITE`, or an `*INTEGRATION_SHELL` rule). The two keywords
**compose** when both are present: LS-DYNA gives each integration point one
`B_i` and the rule gives that same point its `S`/`WF`/`PID`, so the emitted layup
carries the angle *and* the real thickness *and* the per-layer material.
The routes that *cannot* carry an angle each say so by name rather than dropping
it silently: `*PART_COMPOSITE` on the same part **wins** (it replaces the
`*PART`/`*SECTION_SHELL` pair outright in LS-DYNA, carrying its own `ELFORM`/
`SHRF` and no `SECID`); MAT_037/MAT_103 land on a single-direction
`/PROP/TYPE9`; `*MAT_LAMINATED_GLASS` becomes two *isotropic* LAW27 phases with
no material direction to rotate; an isotropic law keeps a plain `/PROP/SHELL`.
An all-zero angle block is silent — it degrades to exactly the section it would
have been anyway.

`*INTEGRATION_SHELL` → the **real** per-layer thicknesses and materials of a
layered shell. The rule is bound from `*SECTION_SHELL` **card-1 field 6**
(`QR/IRID`, cols 51–60) when that field is *negative*: "Quadrature rules in the
`*SECTION_SHELL` and `*SECTION_BEAM` cards need to be specified as a negative
number. The absolute value of the negative number refers to user defined
integration rule number" (Vol I R17 p.29-1). It is **not** the `NIP` field — a
negative `NIP` is a mis-keyed count and gets its own warning. Card 1 is
`IRID NIP ESOP FAILOPT`; with `ESOP = 0` one `S WF PID` card follows per
integration point (`CARD_LIST(NIP)`, one triple per card — *not* packed eight to
a card like the `ICOMP` angles). Several rules may be stacked under one header.

Each point becomes one layer: `t_i = WF_i / ΣWF · T1` (the sum-normalization is
real, not an assumption that LS-DYNA's "the weights should sum to 1" convention
was honoured), and the layer's material is `PID_i → *PART → MID`, falling back
to the element's own part material when the field is blank. The **rule's `NIP`
wins** over the section's and is pushed onto the section, so it also drives the
shared `/PROP/SHELL` point count, `/INISHE`'s layer count and the `NUMFIP`
count-to-ratio conversion — clamped at 10 on the way there, which is what a
`/PROP/SHELL`'s `N` column takes (ERROR 788). The layered property the rule
drives counts its plies off the rule directly and is capped at 100 instead, so
that clamp never costs a laminate layer. `ESOP = 1` is NIP *equal* layers on one
material — identical to a plain `/PROP/SHELL` with N points, so no property is
split.

**Layer positions are the cumulative-`WF` stack (`Ipos = 0`), not `S_i`** — a
deliberate divergence from dyna2rad. `S_i` is a quadrature *sampling* coordinate
in [−1, +1]; a Radioss layer `Zi` is the physical *middle of a slab*. dyna2rad
writes `Zi = S_i·T1/2` with `Ipos = 1` (`convertprops.cxx:2015`), and the starter
then derives the shell thickness from the layer **envelope**
(`stackgroup.F`: `THICKT = max(Zi+t/2) − min(Zi−t/2)`), which for a canonical
rule reaching `S = ±1` pushes half of each outer layer outside the shell and
leaves gaps between the rest. On the validation windshield below that inflates a
2.0 mm laminate to 2.8 mm; auto-stacking reproduces 2.0 mm exactly and tiles
without gaps, which the starter's own echo confirms (layer 1 at −0.6 spanning
[−1.0, −0.2], layer 2 at −0.1 spanning [−0.2, 0.0]). The trade has two halves and
the conversion warning states both: the emitted stack reproduces `T1` and every
`t_i` exactly, but it integrates at the layer **centres**, not at the rule's own
sampling stations `S_i·T1/2` — so a rule whose outermost `S` is ±1 no longer
samples the outer fibre, and `Σ t_i·z_i²` (hence the bending response) shifts
with it. A rule whose `S` column runs top-down or out of order is **re-ordered
bottom-up** first, carrying each layer's `ICOMP` angle with it — LS-DYNA leaves
that ordering arbitrary (Figure 29-25) but an `Ipos = 0` stack is built in list
order from the bottom face.

The target property is chosen by what the **starter** accepts, not by preference.
`/PROP/TYPE11` is a *single-law* property: `hm_read_prop11.F` takes only Radioss
laws 15, 25, 27 and ≥ 29 on layer 1 (ERROR 30) and requires every other layer to
repeat that law (ERROR 334). So a layup stays on TYPE11 only when it is law-
uniform by construction — every layer on the part's own `*MAT_002`/`*MAT_054`
material, or on the `*MAT_032` glass/polymer pair (two LAW27 cards) — and
otherwise goes to `/PROP/TYPE51` + one `/PROP/TYPE19` per layer, which carries
its materials on per-ply objects and has no whitelist. That is dyna2rad's own
target for this keyword. One case has **no** Radioss home at all: Radioss bans
LAW1 from every layered or orthotropic shell property (IGTYP 9/10/11/16/17/51/52,
`hm_read_part.F:289`, ERROR 658) because it is integrated globally and carries no
through-thickness state, so a rule on a `*MAT_ELASTIC` part is warn-dropped
rather than emitted onto a deck the starter would reject.

Warn-dropped or warn-reported, each by name: a dangling `IRID` (dyna2rad falls
through in silence); `NIP ≤ 0`; `ESOP ∉ {0,1}` (dyna2rad's bare `switch` has no
default and emits a property declaring NIP plies with *no* ply objects);
`ΣWF = 0` (dyna2rad divides by it unguarded and writes `inf`/`nan`); a short
`S`/`WF`/`PID` block; `|S| > 1`; `FAILOPT` (TYPE11 carries one global
`P_Thick_Fail`, not a per-layer failure policy — dyna2rad never reads the field);
a `PID_i` naming no `*PART`; a layer material with no converted `/MAT`; more than
100 points; a solid part, a `*PART_COMPOSITE` on the same part (which *wins*), a
MAT_037/MAT_103 `/PROP/TYPE9` route; and a rule nobody references (recorded in
the conversion log's *recognized but not emitted* channel). An element-free
`PID_i` material-carrier part — the idiom the manual explicitly allows — is
reported too, because k2rad still emits a `/PART` for it and a `/PART` with no
property is starter ERROR 178.

The reference converter still carries its own verdict on this keyword as dead
code — message `/MESSAGE/200024`, *"IRID<0 is not supported"*, commented out at
`convertprops.cxx:657-658`, so a user rule that dyna2rad cannot place is neither
converted nor reported.

**AOPT material axes** are mapped for MAT_002 and MAT_054/055 on both the
layered shell and the stack: `AOPT=0` → `Ip=20` (Radioss's element-connectivity
N1→N2 frame, which is exactly LS-DYNA's element-node convention — an exact
match, not a fallback); `AOPT=2` → a synthesized `/SKEW/FIX` whose `X' = a` and,
when `d` is given, whose `Z' = a×d`, referenced with `Ip=22`; `AOPT=3` → `Ip=23`
with `Vx/Vy/Vz = v`; `AOPT < 0` → `Ip=0` + the `*DEFINE_COORDINATE` system's own
`/SKEW` id. On solids `AOPT=1` → `Ip=21` (point) and `AOPT=4` → `Ip=24`
(cylindrical) as well. Every remaining combination — `AOPT=1`/`4` on a shell, a
null `a` or `v`, an undefined coordinate id — falls back to the element frame
with a loud warning naming the mode. The rotation angle (MAT_002 `BETA`,
MAT_054 `MANGLE`) is applied whenever nonzero; dyna2rad never reads `MANGLE` at
all, applies `BETA` only when `> 0` (silently losing a legal negative rotation),
and its `AOPT < 0` handler on TYPE51 is dead code, so a `*DEFINE_COORDINATE`
system is lost there entirely. Synthesized skew ids are reserved against the
shared `/SKEW`+`/FRAME` namespace (starter ERROR 79 otherwise).

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

### Joints
`*CONSTRAINED_JOINT_SPHERICAL` / `_REVOLUTE` / `_CYLINDRICAL` / `_PLANAR` /
`_UNIVERSAL` / `_TRANSLATIONAL` / `_LOCKING` (+ `_ID`, `_TITLE`, `_LOCAL`,
`_FAILURE`) → one `/PROP/TYPE45` (KJOINT2) + `/PART` + 2..4-node `/SPRING` **per
joint**, plus a `/SKEW/FIX` carrying the joint frame computed from the joint's
own node geometry (only for a 3+-node spring — with two nodes the starter never
reads `Skew_ID1` unless they are coincident, and writing one there would demote
a spherical/locking joint's global frame to the `N1`→`N2` mesh offset).
`Type` = 1/2/3/4/5/6/8 in that order (`LOCKING` is 8, Fixed — not 7, Oldham).
`N1`/`N2` go to spring slots 1-2 and `N3` to slot 3, which is
what builds the local axis; `UNIVERSAL` forwards `N4` and `LOCKING` forwards
`N5` into slot 4. A cylindrical joint written with `N3`=0 (the documented way to
join a free node to a rigid body) falls back to `N4` for the axis. `RPS` → `ScF`
(1.0 — LS-DYNA's own default — when not positive), `Kn`=0 so the starter
derives the blocking stiffness from the time step, `Cr` blank → its 0.05 default.
Dropped with a warning: `DAMP` (a relative scale with no absolute-`Cr` equivalent),
`_LOCAL` `RAID`/`LST` (an output frame only), `_FAILURE` (joints never fail),
and `TRANSLATIONAL` `N5`/`N6` (roll about the sliding axis; kinematically inert).
A joint node on no `/RBODY`, a degenerate axis (starter `ERROR 934`/`935`/`1009`),
a node list shorter than the `Type` requires (`ERROR 936`) and an all-rigid deck
with nothing to pace the engine time step are each warned about by name.
`*DATABASE_JNTFORC` → `/TH/SPRING` over the joint springs.

`*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED` / `_TRANSLATIONAL` → the matched
joint's per-DOF stiffness / damping / friction / stop blocks (`LCID*`→`fct_K*`,
`DLCID*`→`fct_C*`, `ES*`→`Kfr*`/`Kft*`, `FM*`/`FF*`→the friction limit or, when
negative, `fct_fm*`/`fct_ff*`). `NSA*`/`PSA*` stop angles are converted
degrees→radians and sign-forced (`SA-`≤0, `SA+`≥0 — otherwise starter
`ERROR 943`/`944`); `NSD*`/`PSD*` stop displacements go to `SD*` unconverted.
The card binds by `JID`, or by node membership in `PIDA`/`PIDB` (including their
`*CONSTRAINED_EXTRA_NODES`). One `_GENERALIZED` **and** one `_TRANSLATIONAL`
card can share a joint — on a cylindrical (`Tx`,`Rx`) or planar (`Ty`,`Tz`,`Rx`)
joint they fill disjoint DOF blocks and both are kept. For a single-free-axis
joint the `CIDA` axis aligned with the joint axis selects which of φ/θ/ψ drives
`Rx`, and an anti-parallel one mirrors the stop pair (the curves are not
mirrored — that is warned); for multi-DOF
joints the φ→`Rx`, θ→`Ry`, ψ→`Rz` mapping is an approximation (LS-DYNA's are
z-y-z Euler angles) and says so. A channel the `Type` has no free DOF for, and
the `FS`/`FD` friction coefficients (`/PROP/TYPE45` knows only absolute
force/moment limits), are dropped with a warning. `RPS` on the stiffness card is
honoured only for `_TRANSLATIONAL`, per the manual. `_FLEXION-TORSION` and
`_CYLINDRICAL` have no field map
and are reported as recognized-but-not-emitted (the joint itself still converts).

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
the load is `ACCEL × factor(t)` — `LC` supplies the factor curve and never
replaces `ACCEL` (Manual p.33-57) — and DOF 1/2/3 loads along −X/−Y/−Z, so
`Fscale_Y = -accel` with `fct_IDT = LC`. Modal decks get an informational note
instead — gravity does not change a non-prestressed eigenproblem)
`*LOAD_BODY_{X,Y,Z}` → `/GRAV` (base acceleration; a POSITIVE card acts along
the NEGATIVE axis — Manual Vol I R16 p.33-28, "Positive body load acts in the
negative direction" — so `Fscale_Y = -SF`, matching the Radioss dyna-reader
and the `*LOAD_GRAVITY_PART` path. `CID` becomes the `/GRAV` `skew_ID`;
`LCIDDR` has no equivalent and is warned)
`*LOAD_BODY_PARTS` → the `PSID` part set becomes the `/GRNOD/PART` scope of
every `*LOAD_BODY_*` in the deck (one card per deck, last one wins; all the
`/GRAV` cards share that one group)
Both gravity paths route around rigid bodies: a `/GRAV` whose group holds only
rigid *secondary* nodes moves nothing, because the engine overwrites their
acceleration from the `/RBODY` main node after `GRAVIT` has run
(`rgbodv.F`). A rigid part in scope is therefore represented by its `/RBODY`
main node instead of its mesh nodes, and a `*CONSTRAINED_NODAL_RIGID_BODY`
whose secondaries are inside the scope gets its main node added — the groups
are combined with a `/GRNOD/GRNOD` union. A deck with no rigid body in the
load's scope emits the same `/GRNOD` cards with the same ids; only the `/GRAV`
column layout and the `*LOAD_BODY` sign change. A **scoped** load that covers
only part of a rigid cluster is warned about: a rigid body has one main node
and one mass, so it cannot be loaded fractionally and the whole cluster gets
`g` (an upper bound)

### Blast & coupled ALE / high explosive
Empirical (ConWep / TM5-1300) air blast:
`*LOAD_BLAST_ENHANCED`, `*LOAD_BLAST` (legacy) → `/LOAD/PBLAST`
`*LOAD_BLAST_SEGMENT_SET`, `*LOAD_BLAST_SEGMENT` (per-segment) → `/SURF/SEG` +
`/LOAD/PBLAST` (surface bursts synthesize a `/SURF/PLANE` reflecting ground,
`--blast-ground`); `*SET_SEGMENT` → `/SURF/SEG`; `*LOAD_BODY_{X,Y,Z}` → `/GRAV`
(see **Loads** above for the body-load sign convention)

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
`*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` (+ `_ONE_WAY_*`) → `/INTER/TYPE7`.
The SSID side becomes the secondary `/GRNOD` and the MSID side the main
`/SURF`, so **the deformable part belongs on the SSID side**: `/INTER/TYPE7`
is an asymmetric node-to-surface contact, and rigid-body nodes cannot form a
secondary node group. A contact whose SSID side is entirely rigid (a loading
platen or impactor put on the secondary side) therefore has no interface to
emit; k2rad **warns, names the interface, states the physical consequence and
the side-swap remedy, and reports the loss under "Recognized but not
emitted"** rather than dropping it silently. It deliberately does *not* swap
the sides for you — that would convert a model you did not write. The same
reporting covers a main side that resolves to no surface, an all-parts
self-contact with no deformable nodes, the `SOFT`-routed
`*CONTACT_AUTOMATIC_GENERAL` interfaces and `*CONTACT_TIED_*`. A *partially*
rigid secondary side keeps its interface and warns about the nodes removed
from it.
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
`*CONTROL_TIMESTEP` `TSSFAC` with `DT2MS`>=0 (no mass scaling) → engine `/DT`
(`Tsca` = `TSSFAC`, `Tmin` = 0). `TSSFAC` is LS-DYNA's scale factor on the
computed critical step and `Tsca` is the identical quantity in OpenRadioss, so
the safety factor is carried across rather than dropped. `Tmin` is 0 (no lower
bound) deliberately — `/DT`'s `Tmin` is a run-*stop* threshold and LS-DYNA's
`TSLIMT` is not converted, so nothing stops or deletes on a small step.
`TSSFAC`=0 emits nothing (LS-DYNA's default 0.9 is also the `/DT` default).
Explicit decks only.
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
`*SECTION_SHELL` `ELFORM` → `/PROP/SHELL` `Ishell`. `ELFORM` −16/9/20/21/26 map
to `Ishell=24` (QEPH) unambiguously; **everything else — `ELFORM=2`
(Belytschko-Tsay) above all, the most common shell formulation in LS-DYNA
decks — has no exact counterpart**, and which one it gets is a choice:
`--shell-formulation {qbat,qeph}` (CLI) / a GUI radio pair /
`convert(shell_formulation=...)`.
`qbat` (**default**) emits `Ishell=12`, *fully* integrated — what every previous
conversion produced, so no existing deck moves. But `ELFORM=2` is
*under*-integrated, so this changes the element's integration class, and under
`/FAIL/JOHNSON Ifail_sh=2` it takes 4 Gauss × 2 through-thickness = **8 failure
events to delete an element instead of 2**, measured at up to **~1.7×
under-erosion** on a 38k-shell blast model.
`qeph` emits `Ishell=24` — reduced integration with *physical* stabilisation,
much closer to Belytschko-Tsay, and it drops the `dn=1e-3` numerical damping the
starter injects for `Ishell=12`. It is not the default because it **changes
results on every shell deck** (4 `/PROP/SHELL` props across 3 of this repo's
golden fixtures flip 12→24). Either way the mapping is now **stated in the
conversion log** — the original defect was that it happened silently.
Under-integrated `Ishell=1..4` is deliberately not offered: it would activate
the `Hm/Hf/Hr` hourglass path this repo documents as inert and set
`inistate.py`'s `npg` 4→1, corrupting `*INITIAL_STRESS_SHELL` transfer. Implicit
decks are always `Ishell=24` regardless of the option.
`*CONTROL_TIMESTEP` `TSLIMT`/`ERODE` → **`/DT/{SHELL,SH_3N,BRICK}/DEL`**, a
time-step *deletion* floor: OpenRadioss deletes any element whose step reaches
`Tmin`. Emitted **only on explicit consent**, because the card removes mass and
stiffness the LS-DYNA original may have kept — either the deck asks (`ERODE=1`
**and** `TSLIMT>0`) or the user does (`--dt-del <seconds>` / GUI entry /
`convert(dt_del=...)`). A half-request (`ERODE` without `TSLIMT`, or the
reverse) emits nothing and is *reported*; it used to be dropped silently.
It coexists with `/DT/NODA/CST`: the deletion test runs on the element's own
geometric step (length/sound speed, no mass term) and executes before the
`NODADT` early return (`cdt3.F:146` vs `:200`), so nodal mass scaling does not
make the floor unreachable. Under `--ams` the step *is* mass-based
(`cdt3.F:105-109`) and the interaction is warned about instead. Choose `Tmin`
as a **deletion** threshold, not a mass-scaling target: ~0.9× the initial step
deletes elements that merely stretched ~10%, ~0.4–0.5× reserves it for
near-total element collapse.
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
approximated as the infinite plane with a warning). The cut shell set is split
by topology: 4-node shells into a `/GRSHEL/SHEL` on `grshel_ID`, 3-node shells
into a `/GRSH3N/SH3N` on `grtria_ID` — a `/SH3N` ID is not resolved by a 4-node
group, so without the split a cut triangle contributes no force to the section.
`*DATABASE_SECFORC` → `/TH/SECTIO` on every section
`*DATABASE_HISTORY_SHELL` → `/TH/SHEL`, and `/TH/SH3N` for any named element
the mesh writer emitted as a 3-node `/SH3N` (`/TH/SHEL` records only 4-node
shells, so a triangle listed there is absent from the T01);
`*DATABASE_HISTORY_SOLID` → `/TH/BRIC`; `*DATABASE_HISTORY_NODE` → `/TH/NODE`
`*DATABASE_SPCFORC` → `/TH/NODE` `REACX/Y/Z` (+ `REACXX/YY/ZZ` when a
rotational DOF is constrained) on every SPC-constrained node, plus engine
`/ANIM/VECT/FREAC`. **The `REAC*` channel is a time-accumulated reaction
*impulse*, not a force** — the engine adds `m*a*dt` to it every cycle
(`reaction_forces_th.F`) and zeroes the accumulator only once, *before* the
iteration loop (`resol.F:1901`, loop head `:2612`), so it rises monotonically
under a steady load and carries force x time units. The spcforc-equivalent
force is its time derivative, `F = d(REAC)/dt` (`numpy.gradient(reac, t)` on
the T01 column, or a least-squares slope over a steady window — validated to
-0.0002% against a known weight). The converter warns about this on every
converted deck. The companion `/ANIM/VECT/FREAC` field *is* the instantaneous
force (`reactions.F:328`, no `dt` factor, overwritten each cycle).
**Both** `/BCS` sources count: `*BOUNDARY_SPC_*` and the
`*CONSTRAINED_NODAL_RIGID_BODY_SPC` option (whose `/BCS` acts on the rigid
body's master node, so that node is the reaction node)
`*DATABASE_NCFORC`, `*DATABASE_RCFORC` → `/TH/INTER` force resultants over
every converted contact interface (OpenRadioss has no per-node contact-force
time history; for `NCFORC` the nodal-resolution view is the
`/ANIM/VECT/CONT` + `/PCONT` vectors)
`*DATABASE_FREQUENCY_BINARY_D3PSD/D3RMS/D3FTG`, `*MAT_ADD_FATIGUE` → no
OpenRadioss equivalent; honoured **offline** by
`tools/modal_random_response.py` on top of the modal solution (see
*Random vibration & fatigue* in [`docs/MODAL.md`](docs/MODAL.md)) — never
bare-skipped

Unsupported keywords are listed in `result.skipped_keywords` and as
comments in the generated `_0000.rad`.

A keyword can also be *recognized* — it has a handler, so it is **not**
counted as skipped — and still produce no card. Those are listed separately in
`result.recognized_not_emitted` as `(keyword, reason)` pairs, and printed by
the CLI and the conversion log under **"Recognized but not emitted"**, so
`skipped: 0 unsupported keyword(s)` cannot be read as "everything was
converted". Currently: `*DATABASE_MATSUM` (per-part energy needs `/TH/PART`,
not yet emitted), `*DATABASE_NODOUT` / `*DATABASE_ELOUT` (k2rad writes the
per-entity `/TH` blocks only for entities a `*DATABASE_HISTORY_*` names) and
`*DATABASE_GLSTAT` (no card needed — OpenRadioss writes the global energy
balance automatically). In every case the `dt` is still honoured as the
`/TFILE` frequency. The same channel carries any `*CONTACT` that produced
no `/INTER` (and any `*CONTACT_FORCE_TRANSDUCER` that produced no
`/INTER/SUB`), with the lost interface ids named — a missing contact
changes the physics, not just the instrumentation, so it can never be
invisible in the log.

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
