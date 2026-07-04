# LS-DYNA ↔ OpenRadioss blast / ALE / high-explosive keyword mapping

Research report backing the k2rad coupled-explosion converter work. It continues
the empirical-blast path shipped in PR #38 (`*LOAD_BLAST_ENHANCED` +
`*LOAD_BLAST_SEGMENT_SET` → `/LOAD/PBLAST`; see `docs`/README blast section).

Two physical families are covered:

* **A. Empirical (ConWep / TM5-1300) air blast** — a pressure–time load applied
  directly to a Lagrangian surface. No fluid mesh. Already the shipped path;
  this report closes the remaining legacy variants.
* **B. Coupled ALE / high-explosive** — the explosive and surrounding air/water
  are *meshed* as a multi-material Eulerian/ALE domain, a JWL (or other) EOS
  drives the detonation-product pressure, and the fluid pushes the Lagrangian
  structure through a fluid–structure coupling interface. This is the real gap.

All OpenRadioss card layouts below are taken from the **hm_cfg_files reader
spec** (`C:\OpenRadioss\hm_cfg_files\config\CFG\radioss<NNNN>\...`), using the
newest `FORMAT(radiossNNNN)` block ≤ the deck's `/BEGIN` version — the same
method as the PR #17 card-format audit. Cross-checked against the official
OpenRadioss FSI example `Drop_Container/fsi_drop_container_0000.rad`
(`/BEGIN Invers 2023`), which is a complete, known-good water/air-drop ALE deck.

---

## 0. Summary mapping table

| LS-DYNA keyword | OpenRadioss target | Status in k2rad | Notes |
|---|---|---|---|
| `*LOAD_BLAST_ENHANCED` | `/LOAD/PBLAST` | shipped (#38) | ConWep source |
| `*LOAD_BLAST_SEGMENT_SET` | `/LOAD/PBLAST` + `/SURF/SEG` | shipped (#38) | applicator |
| `*LOAD_BLAST` (legacy CONWEP) | `/LOAD/PBLAST` | **added** | one implicit charge; see §A |
| `*LOAD_BLAST_SEGMENT` (per-seg) | `/LOAD/PBLAST` + `/SURF/SEG` | **added** | ad-hoc segment list |
| `*MAT_HIGH_EXPLOSIVE_BURN` (008) | `/MAT/LAW5` (JWL) | **added** | merged with its `*EOS_JWL` |
| `*EOS_JWL` (002) | `/MAT/LAW5` A,B,R1,R2,ω,E0 | **added** | folded into the LAW5 above |
| `*EOS_LINEAR_POLYNOMIAL` (001) | `/EOS/POLYNOMIAL` | **added** | on a `/MAT/LAW6` carrier |
| `*EOS_GRUNEISEN` (004) | `/EOS/GRUNEISEN` | **added** | " |
| `*EOS_IDEAL_GAS` | `/EOS/IDEAL-GAS` | **added** | γ = Cp/Cv conversion |
| `*MAT_NULL` (+ EOS) | `/MAT/LAW6` (HYD_VISC) | **added** | fluid carrier for an EOS |
| `*INITIAL_DETONATION` | `/DFS/DETPOINT` | **added** | JWL lighting point/time |
| `*ALE_MULTI-MATERIAL_GROUP` | `/MAT/LAW51` (MULTIMAT) submat order | **added** | AMMG order = phase order |
| `*SECTION_SOLID` ELFORM 11/12 | `/PROP/SOLID` Iale=1 | **added** | ALE solid formulation |
| `*CONTROL_ALE` | `/ALE/…` + engine notes | partial | advection/euler flags, warn |
| `*INITIAL_VOLUME_FRACTION_GEOMETRY` | `/INIVOL` (+ `/SURF/PLANE`) | **added** (plane) | plane container only |
| `*INITIAL_VOLUME_FRACTION` (set) | `/INIVOL` | warn/skip | needs per-element fractions |
| `*CONSTRAINED_LAGRANGE_IN_SOLID` | `/INTER/TYPE18` | **added** | FSI penalty coupling |
| `*BOUNDARY_NON_REFLECTING` | `/EBCS/NRF` | **added** | non-reflecting frontier |
| `*BOUNDARY_AMBIENT` / ambient AMMG | `/EBCS/INLET` (or `/EBCS/NRF`) | warn/skip | reservoir state, see §B7 |
| `*ALE_REFERENCE_SYSTEM_*` | `/ALE/GRID/*` | skip-with-warning | mesh-motion control, no 1:1 |
| `*DATABASE_BINARY_BLSTFOR` | — | skip (#38) | binary DB, no equivalent |

`/INTER/TYPE22` (ALE/Lagrange with a cut-cell, "conservative" FSI) is the other
candidate for `*CONSTRAINED_LAGRANGE_IN_SOLID`; TYPE18 (penalty) is chosen as
the default because it is the method used in the official `Drop_Container`
example and is far more robust for first-pass conversion. TYPE22 is noted as an
alternative in the warning.

---

## A. Empirical blast — legacy completeness

The shipped path covers the modern `*LOAD_BLAST_ENHANCED` + `_SEGMENT_SET` pair.
Two legacy variants remain:

### `*LOAD_BLAST` (original CONWEP, no `_ENHANCED`)
One implicit blast source per deck (no `BID`). Card:

```
WGT  XBO  YBO  ZBO  TBO  IUNIT  ISURF  CFM  CFL  CFT  CFP  DEATH  NEGPHS
```

`WGT` = equivalent TNT mass, `XBO/YBO/ZBO` = charge coordinates, `TBO` = arrival
offset, `IUNIT` = the same unit flag as `_ENHANCED` (default 2 = kg,m,s,Pa),
`ISURF` = 2 hemispherical surface / 1 spherical air. It is applied to whatever
segments a subsequent `*LOAD_BLAST_SEGMENT[_SET]` names. Mapped by synthesizing a
`LoadBlastEnhanced` with an auto `bid` and `blast = ISURF`, so it flows through
the existing `/LOAD/PBLAST` writer unchanged.

### `*LOAD_BLAST_SEGMENT` (per-segment, not `_SET`)
Applies a blast source to an *ad-hoc* segment (four node ids) rather than a named
`*SET_SEGMENT`. Card: `BID N1 N2 N3 N4`. Collected into a synthesized segment
set (one per `bid`) so the same `/SURF/SEG` + `/LOAD/PBLAST` machinery is reused.

**Verdict:** worth adding — both are cheap (they reuse the shipped
`LoadBlastEnhanced` / `blast_segment_loads` machinery and the `/LOAD/PBLAST`
writer) and cover older ConWep decks. Neither introduces new physics.

---

## B. Coupled ALE / high-explosive

### B1. JWL detonation products — `*MAT_HIGH_EXPLOSIVE_BURN` + `*EOS_JWL` → `/MAT/LAW5`

In LS-DYNA a high explosive is **two paired cards** sharing a material id:

* `*MAT_HIGH_EXPLOSIVE_BURN` (MAT_008): `MID RO D PCJ BETA K G SIGY`
  — density `RO`, detonation velocity `D`, Chapman–Jouguet pressure `PCJ`, a burn
  flag `BETA`.
* `*EOS_JWL` (EOS_002): `EOSID A B R1 R2 OMEG E0 V0`
  — the JWL pressure law `p = A(1−ω/R1V)e^(−R1V) + B(1−ω/R2V)e^(−R2V) + ωE/V`.

OpenRadioss `/MAT/LAW5` (aka `/MAT/JWL`) **combines both** into one material.
Reader spec `MAT/matl5_jwl.cfg` `FORMAT(radioss2019)` (newest ≤ 2022):

```
/MAT/LAW5/<id>
<title>
#              RHO_I
<RO>
#                  A                   B                  R1                  R2               OMEGA
<A>   <B>   <R1>   <R2>   <OMEG>
#                  D                P_CJ                  E0                Eadd   I_BFRAC      Qopt
<D>   <PCJ>   <E0>   0   0   0
#                 P0                 PSH          Bunreacted
0   0   0
```

**Merge rule:** the two LS-DYNA cards are joined by shared MID. `E0` is the JWL
detonation energy per unit volume — from `*EOS_JWL` (`E0`, already per initial
volume when `V0 = 1`). `V0 ≠ 1` is warned (Radioss assumes the reference volume).
`BETA`/`K`/`G`/`SIGY` from MAT_008 have no LAW5 counterpart (LAW5 is a pure
detonation-product EOS with programmed burn) and are dropped with a note.

**Detonation is separate:** LAW5 needs a lighting time, which comes from
`*INITIAL_DETONATION` → `/DFS/DETPOINT` (§B4), not from the material card.

### B2. Other EOS — `/MAT/LAW6` carrier + `/EOS/<type>`

For non-explosive ALE fluids (air, water) LS-DYNA pairs a **carrier material**
(usually `*MAT_NULL`, sometimes `*MAT_ELASTIC_FLUID`) with an `*EOS_*`. In
OpenRadioss the carrier is `/MAT/LAW6` (hydrodynamic viscous, keyword alias
`/MAT/HYD_VISC`) and the EOS is a **separate `/EOS/<type>` block whose id equals
the material id**. Confirmed in `Drop_Container`:

```
/MAT/HYD_VISC/4000492      <- carrier, RHO + kinematic viscosity + Pmin
AIR
#              RHO_I
1.22e-12
#                 Nu                Pmin
<blank>
/EOS/IDEAL-GAS/4000492     <- SAME id 4000492
AIR
#              Gamma                  P0                 PSH                  T0               RHO_0
1.4   0.1
```

Reader spec `MAT/mat_EOS.cfg` `FORMAT(radioss2022)` gives every EOS option's card
(`EOS_Options` selects the keyword):

| LS-DYNA | OpenRadioss | LAW5-cfg option | Card fields |
|---|---|---|---|
| `*EOS_LINEAR_POLYNOMIAL` | `/EOS/POLYNOMIAL` | 3 | `C0 C1 C2 C3` / `C4 C5 E0 P_sh RHO_0` |
| `*EOS_GRUNEISEN` | `/EOS/GRUNEISEN` | 2 | `C S1 S2 S3` / `Y0 a E0 RHO_0` |
| `*EOS_IDEAL_GAS` | `/EOS/IDEAL-GAS` | 12 | `Gamma P0 PSH T0 RHO_0` |
| `*EOS_JWL` | (folded into `/MAT/LAW5`) | — | see §B1 |

**Field mapping & gotchas**

* **Linear polynomial (001 → POLYNOMIAL):** `C0..C5` map 1:1; LS-DYNA card 2
  carries `E0 V0` — `E0` → Radioss `E0`, `V0 ≠ 1` warned. `P_sh` (pressure shift)
  defaults 0. `C6` is ignored (Radioss has no C6 term).
* **Grüneisen (004 → GRUNEISEN):** LS-DYNA `C S1 S2 S3 GAMAO A E0 V0` →
  Radioss `C S1 S2 S3` then `Y0=GAMAO  a=A  E0  RHO_0`. Same μ = ρ/ρ₀−1
  convention. Sign of `S1..S3` identical.
* **Ideal gas:** LS-DYNA `*EOS_IDEAL_GAS` is parameterised by `CV0, CP0` (heat
  capacities) and initial temperature, **not** γ. Radioss `/EOS/IDEAL-GAS` wants
  `Gamma, P0, PSH, T0, RHO_0`. Conversion: **γ = CP0 / CV0**; `P0` from the
  initial state if given, else left blank (Radioss derives it). This is the one
  EOS that needs a real unit-aware conversion, so it is warned.
* **EOS id == MAT id** is mandatory in OpenRadioss — the `/EOS` block binds to
  the material of the same id. The converter emits them with matched ids.
* **Carrier choice:** a bare `*MAT_NULL` (no EOS) stays `/MAT/VOID` (its existing
  mapping, used for vacuum/void ALE phases). A `*MAT_NULL` *with* a companion
  `*EOS_*` becomes `/MAT/LAW6` so the EOS has a hydro carrier.

### B3. ALE multi-material — `*ALE_MULTI-MATERIAL_GROUP` + `*SECTION_SOLID` 11/12 → `/MAT/LAW51`

`*ALE_MULTI-MATERIAL_GROUP` (AMMG) declares the ordered list of ALE materials
that share the Eulerian mesh — each line names a `SID/IDTYPE` (part or part-set).
Order matters: it is the **phase index** referenced later by `*INITIAL_VOLUME_
FRACTION` and the ALE advection. OpenRadioss expresses the same thing as one
**`/MAT/LAW51`** ("MULTIMAT") material with `Iform = 12`, listing the
sub-materials in order. Reader spec `MAT/mat_law51.cfg` `FORMAT(radioss2023)`:

```
/MAT/LAW51/<id>
<title>
<blank>
#    Iform
        12
#                                     NU              Nu_Vol
<blank>
#    MatID           ALPHA_MAT
   <submat1>   <alpha1>
   <submat2>   <alpha2>
   ...
```

Each `submatN` is a `/MAT/LAW6 + /EOS` pair from §B2 (or a `/MAT/LAW5` explosive).
`ALPHA_MAT` is the *reference* initial volume fraction (used where no `/INIVOL`
overrides). The phase order (1-based) is exactly the AMMG order, so `/INIVOL`'s
`ALE_PHASE` and `*INITIAL_VOLUME_FRACTION`'s AMMG index stay consistent.

`*SECTION_SOLID` **ELFORM 11** (1-pt ALE multi-material) and **ELFORM 12** (1-pt
ALE single material) mark the property as ALE: `/PROP/SOLID` field 3
**Iale = 1** (reader spec `PROP/prop_p14_solid.cfg` confirms
`Isolid Ismstr Iale Icpre …`; the reference Eulerian deck uses Iale = 2). k2rad
maps ELFORM 11/12 → Iale = 1 (ALE) and warns that a purely Eulerian
(fixed-mesh) run wants Iale = 2.

### B4. Detonation point — `*INITIAL_DETONATION` → `/DFS/DETPOINT`

`*INITIAL_DETONATION`: `PID X Y Z LT` — explosive part (0 = all), lighting point
`X Y Z`, lighting time `LT`. OpenRadioss `/DFS/DETPOINT` sets the JWL burn origin
for a LAW5 material:

```
/DFS/DETPOINT/<id>
<title>
#               Xdet                Ydet                Zdet                Tdet    mat_ID
<X>   <Y>   <Z>   <LT>   <matID>
```

`mat_ID` is the LAW5 material to light. `*INITIAL_DETONATION PID` names the part;
the converter resolves `part → mat_ID`. `/DFS/DETPOINT` is read by the starter's
native reader (the hm_cfg `detpointset.cfg` only formalises the newer
`/DFS/DETPOINT/GRNOD` node-group variant at `FORMAT(radioss2024)`), so the point
form is emitted and starter-verified rather than cfg-checked.

`/DFS/DETLINE` (line source) and `/DFS/DETPLAN` (plane) are the counterparts of a
multi-point / planar detonation but LS-DYNA expresses those with multiple
`*INITIAL_DETONATION` rows, so DETLINE/DETPLAN are not needed for a 1:1 map.

### B5. Initial fill — `*INITIAL_VOLUME_FRACTION[_GEOMETRY]` → `/INIVOL`

`/INIVOL` fills the ALE elements of a **part** with a phase up to a geometric
surface. Reader spec `TABLE/inivol.cfg` `FORMAT(radioss2019)`:

```
/INIVOL/<part_ID>/<id>
<title>
#  surf_ID ALE_PHASE  FILL_OPT     ICUMU          FILL_RATIO
<surfID>   <phase>   <fillopt>   0   0.0
...
```

`ALE_PHASE` = the 1-based phase index into the `/MAT/LAW51` submaterial list
(§B3). `surf_ID` is a closed `/SURF` **or** an infinite `/SURF/PLANE`; the
existing `_synthesize_blast_ground` already emits `/SURF/PLANE`, so a
`*INITIAL_VOLUME_FRACTION_GEOMETRY` **plane** container reuses it. Box / sphere /
cylinder containers have no infinite-`/SURF` primitive and are warned as
unsupported (the user supplies a meshed `/SURF`). The non-geometry
`*INITIAL_VOLUME_FRACTION` (explicit per-element fraction of a *set*) has no
`/INIVOL` analogue (which is surface-based) and is warned/skipped.

### B6. Fluid–structure coupling — `*CONSTRAINED_LAGRANGE_IN_SOLID` → `/INTER/TYPE18`

Couples a Lagrangian structure (SLAVE) to the ALE fluid (MASTER). Card 1:
`SLAVE MASTER SSTYP MSTYP NQUAD CTYPE DIREC MCOUP`; card 2 penalty/friction.
OpenRadioss `/INTER/TYPE18` (penalty ALE/Lagrange) reader spec
`INTER/inter_type18.cfg` `FORMAT(radioss2022)`:

```
/INTER/TYPE18/<id>
<title>
#            surf_ID grbric_id                Igap               Ipres      Idel
<surfID>   <grbricID>   0   0   0
#             Stfval                Vref                 Gap              Tstart               Tstop
<Stfval>   0   <Gap>   0   0
```

`surf_ID` = the Lagrangian structure surface (from LS-DYNA SLAVE), `grbric_id` =
the ALE brick group (from MASTER). `Stfval`/`Gap` must be > 0 (cfg `CHECK`);
k2rad emits a small default `Gap` (a fraction of the fluid element size) and a
default `Stfval`, warned for tuning. **TYPE22** (cut-cell) is the more accurate
alternative and is named in the warning.

### B7. Non-reflecting / ambient boundaries → `/EBCS`

* `*BOUNDARY_NON_REFLECTING` (`NSID AD AS`): a set of segments acting as a silent
  far-field. → **`/EBCS/NRF`** on the `/SURF/SEG` built from that segment set.
  Reader spec `LOADS/ebcs_nrf.cfg` `FORMAT(radioss2022)`:

  ```
  /EBCS/NRF/<id>
  <title>
  #  surf_ID
  <surfID>
  #            TCAR_P             TCAR_VF
  <lc>   <lc>
  ```

  `TCAR_P`/`TCAR_VF` are relaxation times ≈ element size / sound speed; left 0
  (auto) with a warn.
* `*BOUNDARY_AMBIENT` / ambient AMMG reservoir: a prescribed-state inflow. →
  `/EBCS/INLET` (imposed density/energy) is the closest, but it needs the
  reservoir's thermodynamic state which LS-DYNA carries on a separate ambient
  element — warned/skipped for a first pass (an NRF outflow is usually an
  acceptable substitute and is suggested).

### B8. `*CONTROL_ALE` → `/ALE/…` (partial)

`*CONTROL_ALE` (`DCT NADV METH AFAC … EBC`) sets the advection scheme and mesh
smoothing. OpenRadioss splits these across `/ALE/MUSCL`, `/UPWIND`,
`/ALE/GRID/*` and engine `/DT/ALE`. The advection method `METH` maps roughly:
Donor-cell (`METH=1`) → default upwind; Van-Leer/HIS (`METH=2/3`) → `/ALE/MUSCL`.
Mesh-smoothing (`*ALE_SMOOTHING`, `*ALE_REFERENCE_SYSTEM_*`) has no clean 1:1 and
is documented as skip-with-warning. k2rad emits the ALE materials/props/coupling
but leaves the advection tuning to OpenRadioss defaults (validated as stable in
the `Drop_Container` reference), with a note pointing at `/ALE/MUSCL` + `/UPWIND`
for users who need to reproduce a specific `METH`.

---

## C. Unit / sign gotchas (consolidated)

1. **`/LOAD/PBLAST` is unit-dependent** (shipped-work lesson): the TM5-1300
   formula reads the `/BEGIN` unit labels, so they must be the deck's real units.
   The JWL/EOS path is *not* similarly unit-magic — LAW5/EOS parameters are plain
   physical quantities in the work-unit system — but they must still be
   self-consistent with the mesh units (pressures in the deck's pressure unit,
   `E0` as energy/volume, `D` as velocity).
2. **`*EOS_IDEAL_GAS`** is the only EOS needing a real conversion (γ = Cp/Cv);
   all others map field-for-field.
3. **`V0 ≠ 1`** (initial relative volume) on `*EOS_JWL`/`*EOS_LINEAR_POLYNOMIAL`
   is warned — Radioss references energy to the initial volume implicitly.
4. **EOS id must equal its MAT id** in OpenRadioss.
5. **ALE phase order** must be identical across `/MAT/LAW51`, `/INIVOL ALE_PHASE`
   and any detonation — driven off the AMMG order.
6. **`/BEGIN` version:** the JWL/EOS/DETPOINT cards have `FORMAT ≤ radioss2022`
   and validate at `/BEGIN 2022`; the full multi-material ALE (`/MAT/LAW51`
   Iform=12, `/INIVOL`, `/INTER/TYPE18`, `/EBCS`) is validated by the reference
   at `/BEGIN 2023`. The converter keeps `2022` for non-ALE decks (byte-identical
   guarantee) and is validated per keyword by the starter.

---

## D. What has NO clean equivalent (skip-with-warning)

* `*ALE_REFERENCE_SYSTEM_NODE/_GROUP/_SWITCH` — ALE mesh-motion prescription;
  OpenRadioss `/ALE/GRID/*` is structured differently. Warn.
* `*ALE_SMOOTHING` — mesh relaxation; no 1:1. Warn.
* `*INITIAL_VOLUME_FRACTION` (set form, explicit per-element fractions) —
  `/INIVOL` is surface-based. Warn.
* `*BOUNDARY_AMBIENT` reservoir state — needs the ambient element's
  thermodynamic state; suggest `/EBCS/NRF` outflow. Warn.
* `*CONSTRAINED_LAGRANGE_IN_SOLID` advanced coupling (`CTYPE 4/5`, porous,
  erosion) — only the penalty-coupling subset maps to `/INTER/TYPE18`. Warn on
  the unsupported CTYPEs.
* `*DATABASE_BINARY_BLSTFOR` — no equivalent binary DB (shipped skip).

---

## E. Validation method

Each keyword family is unit-tested against a hand-written `.k` snippet (stdlib
`unittest`, no third-party deps) and the converted `.rad` is run through the
OpenRadioss **starter** (fast, no MUMPS):

```
PATH += C:\OpenRadioss\extlib\hm_reader\win64;C:\OpenRadioss\extlib\intelOneAPI_runtime\win64
RAD_CFG_PATH=C:\OpenRadioss\hm_cfg_files ; KMP_STACKSIZE=400m ; KMP_AFFINITY=disabled
C:\OpenRadioss\exec\starter_win64.exe -i <deck>_0000.rad -np 1
```

then `<deck>_0000.out` is grepped for the `ERROR` count and the echoed values
(charge mass, JWL A/B, EOS γ, detonation coords, phase fractions) are confirmed
against the input. Starter-validation evidence is captured in the PR body.
