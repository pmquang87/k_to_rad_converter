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

A label must be one the **starter** parses, not merely one a human reads:
`unit_code.F:70-98` splits the field into an SI prefix plus a base letter and
accepts a token of one, two or three characters only, ending in `g` (mass),
`m` (length) or `s` (time). A longer token blanks the unit and raises
`ERROR 573 INVALID UNIT CODE`. So microseconds are **`mus`** (or `us`) — not
`micros`, `usec` or `microsecond`. Legal prefixes are
`y z a f p n mu u m c d (none) da h k K M G T P E Z Y`; note `M` is 1e6 while
`m` is 1e-3, and the base letter is case-sensitive (`S` is rejected). A field
that parses as a plain real number is taken as the conversion factor directly
(`1.0E-6` works), and a blank one is `ERROR 574 UNIT NOT DEFINED`.

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
`*NODE`, `*ELEMENT_SHELL`, `*ELEMENT_SOLID`, `*ELEMENT_TSHELL` (+ `_BETA` /
`_COMPOSITE` — see **Thick shells**), `*ELEMENT_SPH` (+ `_VOLUME`; the `MASS`
column's sign and the suffix both select mass-vs-volume, and the `NEND` range
generator is expanded — see **SPH particles**), `*ELEMENT_BEAM`, `*ELEMENT_MASS`,
`*ELEMENT_MASS_NODE_SET`, `*ELEMENT_MASS_PART`, `*ELEMENT_MASS_PART_SET`,
`*PART` **and every legal option stacking** — `_INERTIA` / `_REPOSITION`,
`_CONTACT`, `_PRINT`, `_ATTACHMENT_NODES`, `_AVERAGED`, `_FIELD`, in **any
order** (all 3588 spellings are generated from one grammar, because "Options 1,
2, 3, 4, 5, and 6 may be specified in any order"; the CARD order stays the fixed
Card-Summary one whichever way the keyword is spelled). The option cards are
consumed positionally by the option set — a blank line inside the block is a card
of all-defaults, never padding, and `_INERTIA` card 6 is read only when the
card-3 `IRCS` value is 1. **The mesh survives every stacking**, modelled or not:
- `*PART_INERTIA` → the part's `/RBODY` carries defined mass properties —
  `TM` → `Mass`, `IXX/IYY/IZZ` → `Jxx/Jyy/Jzz`, `IXY/IYZ/IXZ` → `Jxy/Jyz/Jxz`
  (a pure field-order permutation, **no sign change**: both LS-DYNA and Radioss
  hold the inertia *tensor* component, i.e. minus the product of inertia), and
  `ICoG = 4` so the mesh's own mass and inertia are ignored and the centre of
  gravity is pinned where the card puts it. The main node is placed at `NODEID`
  (reused when element-free, else copied to a synthesized free node) or at
  `XC/YC/ZC`. `IRCS = 1` binds `/RBODY Skew_ID` — the card-6 `CID`
  `*DEFINE_COORDINATE_*` 1:1, or a synthesized `/SKEW/FIX` built from the two
  card-6 vectors (`z' = x_L × v_ip`, `y' = z' × x_L`); a dangling `CID` or a
  degenerate vector pair warns and stays global. Card 5 `VTX..VRZ` →
  `/INIVEL/TRA` + `/INIVEL/ROT` on a group holding **only** the main node, which
  is exact because `/INIVEL/ROT` writes the nodal angular velocity and the rigid
  body then rotates about its main node = the centre of gravity. An
  `*INITIAL_VELOCITY_RIGID_BODY` on the same part supersedes card 5 (Remark 5)
  and the card-5 values are dropped with a warning. A blank `TM` or a zero
  inertia diagonal is a source-deck defect (Remark 3: "There are no default
  values") — the override is refused with a warning rather than emitted as
  starter `ERROR 679` / `ERROR 274`, and a non-rigid or merged-away part reports
  the lost `TM` by value
- `*PART_CONTACT` → `OPTT` into the `/PART` card's `Thick` column (cols 31–50),
  the virtual contact thickness the starter reads as the FIRST of three gap
  levels (`THK_PART`, then the element thickness, then the property's —
  `i7sti3.F:230`). Written only when non-zero (the starter's own test is
  `THK_PART /= ZERO`, so a literal zero is indistinguishable from blank).
  `FS`/`FD`/`DC`/`VC`, `SFT`, `SSF` and `CPARM8` are warn-dropped — Radioss has
  no per-part friction or stiffness scale, and `SFT` is deliberately *not* folded
  into `Thick` (it scales the true thickness; `Thick` replaces it). Three ways the
  value can reach `Thick` and still not be read are each warned per part: a part
  carrying per-element `*ELEMENT_SHELL_THICKNESS` too (`OPTT` supersedes it for
  the contact gap, while the element value keeps the structural thickness), a
  SOLID-only part (the starter has no solid `THK_PART` loop, though LS-DYNA
  applies `OPTT` to solids under `SOFT = 2`), and an interface written with
  `Igap = 0` — on `/INTER/TYPE7` the whole `THK_PART` block sits inside
  `IF(IGAP >= 1)`, so the plain TYPE7 k2rad emits ignores it while the TYPE25 and
  `SOFT=-7` routes (`Igap = 2`) honour it
- `_REPOSITION`, `_PRINT` (`PRBF`), `_ATTACHMENT_NODES` (`ANSID`) and `_FIELD`
  (`FIDBO`) are warn-dropped with their cards consumed, so the walk stays in
  phase; `_AVERAGED` adds no card. `*PART_SENSOR` / `_ADD` / `_MODES` / `_MOVE` /
  `_DUPLICATE` / `_ANNEAL` / `_STACKED_ELEMENTS` are separate keywords, not
  `*PART` options — they are warn-skipped by name rather than parsed into phantom
  parts

`*PART_COMPOSITE` (+ `_TITLE` / `_LONG` / `_CONTACT`; `_TSHELL` on a
thick-shell mesh converts to a real `/PROP/TYPE22` — see **Thick shells** —
while `_IGA_SHELL` and a `_TSHELL` on a THIN-shell mesh warn and fall back to a
plain shell property, see **Composites**), `*SECTION_TSHELL` (+ `_TITLE`; every
card SET under one header, striding over the `ICOMP` angle block, which sits one
card EARLIER than `*SECTION_SHELL`'s because a thick shell has no thickness card
— see **Thick shells**), `*SECTION_SPH` (+ `_TITLE` / `_ELLIPSE` / `_TENSOR` /
`_INTERACTION` / `_USER`; every card SET under one header, striding the
`_ELLIPSE` anisotropic-h card by RAW position — see **SPH particles**),
`*SECTION_SHELL`
(+ `_TITLE`; every card SET under one header, not just the first, striding over
the `ICOMP` angle cards, the keyword-option card and the ELFORM 101–105
user-shell cards 5/5.1/5.2; `ICOMP = 1` reads the card-3 `B1..B8` per-layer
material angles, and a negative card-1 field 6 `QR/IRID` binds an
`*INTEGRATION_SHELL` rule — see **Composites**),
`*INTEGRATION_SHELL` (user through-thickness integration rules: per-layer
thickness `WF_i`, material `PID_i`, `ESOP = 0/1` — see **Composites**),
`*SECTION_SOLID` (+ `_TITLE`; every card SET under one header, striding over the
`_EFG`/`_SPG`/`_MISC` option cards and the ELFORM 101–105 user-solid cards
3/4/5; cohesive ELFORM ±19/20/±21/22 → `/PROP/TYPE43`, and `_MISC` is now a
registered spelling whose card-2c `COHTHK` becomes TYPE43's `True_thickness` —
see **Adhesives / cohesives** under Materials), `*SECTION_BEAM` (+ `_TITLE`; every card SET under one header, with the
card-2 dialect — `2a` thicknesses, `2b` named `SECTION_nn`, `2c` `A/ISS/ITT/J`,
`2d` truss, `2e`/`2h`/`2i`/`2j` — chosen per set from `ELFORM` and the card's own
first 10 columns, so the `OPTCARD` and `ELFORM = 12` riders stride correctly; a
negative card-1 field 4 `QR/IRID` binds an `*INTEGRATION_BEAM` rule — see
**Integrated beams**), `*SECTION_DISCRETE` (+ `_TITLE`; every card SET),
`*INTEGRATION_BEAM` (user cross-section integration rules: the `ICST = 0`
`S/T/WF` cell cloud → `/PROP/TYPE18` integration points, or `ICST = 1..22`
standard shapes → `Isect = ICST + 9` — see **Integrated beams**)
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
`*ELEMENT_DISCRETE` + `*SECTION_DISCRETE` + a discrete spring/damper material —
`*MAT_SPRING_ELASTIC` (S01), `*MAT_SPRING_ELASTOPLASTIC` (S03),
`*MAT_SPRING_NONLINEAR_ELASTIC` (S04), `*MAT_DAMPER_NONLINEAR_VISCOUS` (S05),
`*MAT_SPRING_GENERAL_NONLINEAR` (S06), `*MAT_SPRING_INELASTIC` (S08) or
`*MAT_DAMPER_VISCOUS` (S02) — → `/PROP/TYPE4` (SPRING) `/SPRING` connectors
(grounded `N2=0` springs get a fixed ground node + `/BCS`). Each of these is a
1-DOF connector and lands in the single DOF block of the property, which carries
the whole Radioss spring law (loading function, hardening flag, rate function,
unloading function, damping function, rupture displacements), so no `/MAT` is
written and the `/PART` keeps `mat_id 0`. dyna2rad instead pairs an empty
`/MAT/LAW108` with a `/PROP/TYPE23` and fills it from the property pass; the card
BODY is the same six DOF blocks either way, and the property route avoids
TYPE23's rule that its `/PART` must carry a MID whose law is 108/113/114/135
(ERROR 179 / ERROR 1715). S03 gets a synthesized 5-point elastic-plastic function
with `H=1`; S06's `LCDL`/`LCDU` become `fct_ID11`/`fct_ID31` with `H=6`, demoted
to `H=0` with a warning when `LCDU` is blank (`H=6` without `fct_ID31` is starter
ERROR 1057); S08's one-sided `LCFD` is mirrored into the opposite quadrant per
`CTF` and gets `H=1` on `K1=KU` (dyna2rad leaves `H` at 0, which silently turns an
inelastic spring elastic). A part whose material, curve or elements cannot be
converted still gets an INERT `/PROP/TYPE4` + `/PART`: the pid is claimed by the
connector path either way, so dropping it would delete the `/PART` id from under
every `*SET_PART` member, `/GRNOD/PART` scope, contact and `/TH` channel that
names it

An element oriented by a `*DEFINE_SD_ORIENTATION` (`VID`) becomes an oriented
`/PROP/TYPE8` (SPR_GENE) whose local DOF 1 acts along that orientation's `/SKEW`
axis (only TYPE8 and TYPE23+LAW108 honour a `skew_ID`); an unresolvable `VID`
(`IOP=1/3`, which dyna2rad lacks too) stays warned + skipped. A `DRO=1`
(torsional) section is a MOMENT-per-radian spring, so it moves to local DOF 4 of
a 6-DOF property — `/PROP/TYPE13`, whose local X is node1→node2, so the torsion
acts about the element's own axis, or DOF 4 of the oriented `/PROP/TYPE8`. LS-DYNA
already states a `DRO=1` spring in moment per radian, so nothing is rescaled;
zero-length and grounded torsional elements are warn-skipped (no axis to twist
about). `KD`/`V0` (dynamic magnification) and `CL` (clearance, which makes the
LS-DYNA spring compression-only) have no Radioss slot and are warn-dropped
individually

`*SECTION_BEAM` `ELFORM=6` is a DISCRETE BEAM — a 6-DOF spring, not a beam: its
card 2f states a lumped `VOL`/`INER` and a `CID`, never a cross-section, so a
`/PROP/BEAM` from it is starter ERROR 314-317. Such a part becomes a
`/PROP/TYPE8` (skew oriented) or `/PROP/TYPE13` (node oriented) `/SPRING`
connector instead, from `*MAT_066` (linear elastic), `*MAT_067` (nonlinear
elastic), `*MAT_068` (nonlinear plastic), `*MAT_071` (cable), `*MAT_074` (elastic
spring), `*MAT_119` (general nonlinear 6-DOF), `*MAT_121` (general nonlinear
1-DOF) or `*MAT_196` (general spring). The frame rule: `|SCOOR| = 2` ("the local
r-axis is realigned along n1→n2") selects TYPE13; otherwise a resolvable `CID`
selects TYPE8 with that `/SKEW`; otherwise TYPE13 again, because a TYPE8 with no
skew would silently fall back to the GLOBAL axes — the hole dyna2rad has here.
`*MAT_071` and `*MAT_074` are always TYPE13 (both act along the element); a
resolved `CID` is still written on the TYPE13 property, where `r4buf3.F` reads it
as the XY-plane reference for elements that carry no third node — which is what
`|SCOOR| = 2` + `CID` means in LS-DYNA too ("a final adjustment is made … so that
the local r-axis lies along the n1 to n2 axis", Manual Vol I R17 p.41-26). Mass is
`RO·VOL` (`RO·CA` per unit length for the cable when `VOL` is blank, which also
sets `Ileng=1`; a non-zero `VOL` wins, per Manual Vol II R17 p.2-531);
`INER=-1` is resolved as a solid sphere of volume `VOL`, `INER=-2` as the lumped
`m·L²/12` with a warning. The cable's `LCID` is engineering STRESS vs engineering
strain, so its ordinates are multiplied by `CA` and the result clamped at zero
force with a flat compression branch — a cable must not push. `*MAT_069`/`070`/`093`/`094`/`095`/`097`/`146` have no
OpenRadioss spring law: the connector is still written, inert, and a warning
names the device the deck loses (dyna2rad drops all seven silently)

Elements are emitted **per `*PART`**, so an element whose `PID` no `*PART`
defines cannot be written at all. Rather than let that mesh disappear quietly,
the conversion opens with an orphan-element guard: one `MESH LOSS` warning
naming every missing part id and how many shells / solids / beams / discretes
went with it. It fires on an `*INCLUDE` that did not resolve, a `PID` typo, a
deck assembled from a subset of its parts, and on any `*PART` variant the parser
does not yet recognize.

The reverse case — a `*PART` with **no elements at all** — keeps its `/PART`
and is given a placeholder `/PROP/SHELL`. An empty part is idiomatic
(`*INTEGRATION_SHELL`'s `PID_i` "may reference a part with no elements",
Vol I R17 p.29-17, purely to carry a layer material; an element-free
`*MAT_RIGID` part with `*CONSTRAINED_EXTRA_NODES` forms a real `/RBODY`), and
its id stays addressable by `*SET_PART` members, `/GRNOD/PART` gravity scopes
and subsets. Without a property the starter rejects the deck outright
(ERROR 178, `PROPERTY ID=<pid> DOES NOT EXIST`); the placeholder has no
elements to act on, so it changes no physics. The parts are named in a warning,
since an empty part is as often missing mesh as it is a deliberate carrier.

### Materials
`*MAT_ELASTIC` (also the numeric `*MAT_001`/`*MAT_1`) → `/MAT/LAW1`; the
`_FLUID` option variant takes a different target entirely — see
`*MAT_ELASTIC_FLUID` below
`*MAT_PIECEWISE_LINEAR_PLASTICITY` (+ `_MODIFIED_`) → `/MAT/LAW36`
`*MAT_PLASTIC_KINEMATIC` → `/MAT/LAW44` (`b` = plastic hardening modulus
E·ETAN/(E−ETAN); `Chard` = 1−BETA — the iso/kinematic conventions run in
opposite directions)
`*MAT_FABRIC` / `*MAT_034` → `/MAT/LAW19` (FABRI) + `/PROP/TYPE9`, or
`/MAT/LAW58` (FABR_A) + `/PROP/TYPE16` when `FORM` is one of 4/14/-14/24 AND
the card-7 curves are given. The property is not a choice: each law declares a
shell class the starter enforces (`ERROR 3047`). See *Airbags / monitored
volumes*
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
`*MAT_PLASTICITY_WITH_DAMAGE` / `*MAT_081` / `*MAT_082` (+ `_ORTHO`, `_RCDC`,
`_RCDC1980`, `_STOCHASTIC`) → the MAT_024 base plasticity (`/MAT/LAW36`) **plus**
a live `/FAIL/TAB1` built from the damage strains: `EPPFR` (rupture) becomes the
mandatory `TABLE1_ID` failure-strain plateau and `EPPF` (softening onset) the
`TABLE2_ID` instability plateau, both flat over triaxiality −1…+1. Leaving
`Dcrit`/`D`/`n` blank makes the reader's defaults (`Dcrit=1`, `n=1`) reproduce
LS-DYNA's linear ω = (εp−EPPF)/(EPPFR−EPPF) exactly, and **`FAD_EXP = 1`** makes
the *softening* half of the law real: `hm_read_fail_tab1.F:170-174` sets
`DMG_FLAG = 1` only when `FADE_EXPO > 0` (a TABLE2 zeroes `ECRIT`, the other
trigger), and `fail_tab_c.F:441-455` gates the whole necking block — the only
reader of `EPPF` — on that flag, then computes
`DMG_SCALE = 1 − (εp−EPPF)/(EPPFR−EPPF)`, LS-DYNA's own `1−ω`, which
`mulawc.F90` multiplies into the layer stress. Measured on a live shell run:
within **0.07 %** of `(1−ω)·σy` at every point between `EPPF` and `EPPFR`.
**SHELLS only** — `fail_tab_s.F` reads `TABLE1` alone and has no `DMG_SCALE`
path, so a *solid* element carries full yield stress to rupture whatever is
written; the rupture strain itself is exact on both. `Ifail_sh=2` (delete only
when the whole through-thickness stack has failed) also makes the reader honour
`P_thickfail`, which is where **`NUMINT` lands, as a POSITIVE ratio** —
`hm_read_fail_tab1.F:181-187` honours `P_thickfail` only on the `> 0` branch
and silently replaces a negative one (the exact "fraction of failed IPs" form,
which only `/FAIL/GENE1` passes through) with "all thickness must fail", so the
count is divided by the shell's `NIP` and carried as the equivalent broken-
*thickness* fraction — identical for a uniformly weighted stack, off by the
integration weights for a Gauss one (dropped with a warning when no
`*SECTION_SHELL` on the material states a `NIP`). A blank `EPPF`/`EPPFR` is written
as `1e14` so that leg never engages (LS-DYNA's own 1e12/1e14 defaults); both
blank ⇒ no `/FAIL` card at all. `LCSR` (yield-stress scale vs strain rate) is
expanded into the LAW36 rate-function family — the one static yield function
repeated once per curve point with that point's ordinate as `Fscale`.
**`LCDM` is deliberately NOT transferred**: LS-DYNA's LCDM is ω as a function
of *effective plastic strain* while TAB1's only curve of that shape (`fct_IDd`)
is a function of the *current damage D* returning a damage-*rate* multiplier —
a direct transfer would silently change the softening law, so it is dropped
with a warning (use `*MAT_ADD_DAMAGE_GISSMO` → `/FAIL/TAB2` for a tabulated
damage evolution). `*MAT_082`/`_ORTHO` converts with its directional damage
reported as not reproduced, and the `_RCDC` Wilkins card is named and not read
— `dyna2rad` recognizes neither and drops the whole keyword *silently*, leaving
the part with no material. `TDEL` is dropped with a warning
`*MAT_DAMAGE_2` / `*MAT_105` → the same MAT_024 `/MAT/LAW36` path, with card 3
as an exact `/FAIL/LEMAITRE` triple (`EPSD`→`EPS_D`, `S`→`S_D`, `DC`→`DC`) and
`FAIL`→`/FAIL/JOHNSON` alongside it, exactly as LS-DYNA runs both. A blank `DC`
is written as LS-DYNA's documented default **0.5**, not the reader's own 1.0
(which would delay deletion to full rupture). `/FAIL/LEMAITRE` exists only from
the radioss2026 config, so a `/BEGIN 2022` deck draws one cosmetic starter
`WARNING 100211` and parses every field correctly (verified live). `LCSR` rides
the same rate-family expansion as MAT_081; `TDEL` is dropped with a warning
`*MAT_STRAIN_RATE_DEPENDENT_PLASTICITY` / `*MAT_019` → `/MAT/LAW121`
(PLAS_RATE), a 1:1 target: LAW121's kernel is literally MAT_019's law
`σy = σ0(ε̇) + E·Et/(E−Et)·εp`, so no curve is resampled. `LC1`→`Fct_SIG0`,
`LC2`→`Fct_YOUN`, `LC3`→`Fct_TANG`, `LC4`→`Fct_FAIL`, `VP`→`Ivisc`,
`TDEL`→`DTMIN` and `RDEF`→`Ifail` value-for-value (Radioss does the `Ep`
conversion itself, so `ETAN` goes into `TANG` verbatim). **`TANG` changes
meaning when `LC3` is given** — it is then that curve's ordinate SCALE, so it
is written as `1.0` rather than left at the 0 dyna2rad leaves there, which
would zero the hardening; the other `Xscale_*`/`Yscale_*` factors are likewise
written as an explicit 1.0 whenever their function slot is used. A missing
`LC1` (the material's only yield input) is warned against by name — starter
`ERROR 2060` — and `VP=1` with `LC2` names `WARNING 2061`, where the reader
silently forces `Ivisc` back to 0
`*MAT_PLASTICITY_COMPRESSION_TENSION` / `*MAT_124` → `/MAT/LAW66`, with
`LCIDC`/`LCIDT`→`funct_IDc`/`funct_IDt`, `EC`/`RPCT` verbatim, and
`SRFLAG=2`→`VP=1`. **`P_c`/`P_t` carry `PC`/`PT`**, the compressive/tensile
*mean stress* at which each yield curve takes over — the starter echoes those
columns as "COMPRESSION/TRACTION MEAN STRESS", and `RPCT` is defined as a
fraction of that same pair on both sides, which pins the correspondence;
dyna2rad instead writes the pressure cut-offs `PCUTC`/`PCUTT` there and drops
`PC`/`PT`, which moves the yield-curve blend band onto unrelated numbers. The
Cowper-Symonds factor `1 + (ε̇/C)^(1/P)` maps as `Epsilon_0`←`C` (the reference
rate) and `c`←`P`; dyna2rad writes only the latter, so the reference rate is
lost to the reader's substituted 1.0. `LCSRC`/`LCSRT` promote the law to
`Iyld_rate=3` (`fnYrt_IDc`/`fnYrt_IDt`), which has no `VP` column — reported.
**Both slots of each pair are always filled**: `hm_read_mat66.F:269-278` loops
`IFUNC(1..MFUNC)` and raises `MSGID=126 MSGERROR` "WRONG REFERENCE TO FUNCTION
ID=0" on any zero, so a half-filled pair is an ERROR TERMINATION, not a
degraded run. A lone `LCIDC`/`LCIDT` is **mirrored** into the empty slot (the
manual requires both, p.2-877 remark 1, so such a deck is already degenerate);
a lone `LCSRC`/`LCSRT` — both documented independently Optional — gets a
synthesized **flat unit-scale curve** on the other side, which is exactly
LS-DYNA's "no rate effect there" because LAW66 applies those functions as
multiplicative yield factors (`sigeps66.F:481-487`).
A `K>0` plus `Gi/BETAi` pairs become a `/VISC/PRONY` of the material id.
Failure: `FAIL>0`→`/FAIL/JOHNSON` (`Ifail_sh=2`, k2rad's all-points rule for
every LS-DYNA built-in material failure); `LCFAIL`→`/FAIL/TENSSTRAIN` with
`Epsilon_t1=1.0`/`Epsilon_t2=1.1` and the curve in the `FCT_ID` scaling slot,
but only under LS-DYNA's own four activation conditions — outside them the
curve is dropped and `FAIL` applies (dyna2rad emits nothing at all there).
`PCUTC`/`PCUTT`/`PCUTF`, `SRFILT` and `TDEL` are dropped with warnings
`*MAT_GURSON` / `*MAT_120` (+ `_JC` / `_RCDC` / `_BFRAC`) → `/MAT/LAW52`
(GURSON). The porosity set maps one-for-one — `FC`→`Fc`, `F0`→`Fi`, `EN`→`EpsN`,
`SN`→`SN`, `FN`→`FN`, `Q1`/`Q2`→`alpha_1`/`alpha_2`, `SIGY`→`A` — and
**`alpha_3` (q3) is written as `Q1²`**, the standard Tvergaard closure: the
LAW52 reader does *not* default it, and leaving it 0 is a different flow
surface. Hardening follows the manual's "only used if LCSS = 0" precedence:
`LCSS` (curve or table) wins and becomes `Tab_ID` with `Iyield=1` (a plain
curve is re-emitted as a 1-D `/TABLE/1`, which is what that slot reads); else
`ATYP=2` gives `B = E·ETAN/(E−ETAN)`, `ATYP=3` an 8-point table, and **`ATYP=1`
(power law) is sampled onto a table** from the manual's
`σY = SIGY·((εp + SIGY/E)/(SIGY/E))^(1/N)` — dyna2rad has no conversion there
at all and leaves LAW52 with `n = 0`. An `LCSS` naming a `*DEFINE_TABLE` that
could not be resolved falls back to the `ATYP` ladder rather than writing a
`Tab_ID` with no `/TABLE` behind it (starter `ERROR 779`). The element-length
curves all collapse onto LAW52's scalars the same way — `LCFF`, `LCF0`, `LCFC`
and `LCFN` each become the **mean** of their ordinates (dyna2rad reads the
`LCF0` slot under the wrong name and never applies it) — and `FF0` is used only
when neither `LCFF` nor the `(L1..L4, FF1..FF4)` table is given, as the manual
says; dyna2rad averages `(FF1+…+FF4)/4` unconditionally and so zeroes `FF0` in
the common case. The
`f0 ≤ fc ≤ fF` ordering is checked and starter `ERROR 1745` named. `_JC` adds a
companion `/FAIL/JOHNSON` from its card-5 `D1-D4` with **`D3` VERBATIM** — this
keyword's `σH/σM` is the *mean hydrostatic stress* ratio, tension-positive
across the manual (GISSMO p.2-76, `*MAT_252` p.2-1694 "σm = I1/3 … as in
Johnson and Cook [1985]", `*MAT_124` remark 1 "a positive mean stress (meaning
a negative pressure) is indicative of tension"), which is exactly Radioss's
`P/σVM`; only `*MAT_JOHNSON_COOK`'s `σ* = p/σeff` uses LS-DYNA's
compression-positive *pressure* and gets the flip. `LCJC > 0` suppresses the
`/FAIL/JOHNSON` entirely, because LS-DYNA then ignores `D1`–`D3` (p.2-838) and
the replacement triaxiality curve has no `/FAIL/JOHNSON` slot.
`_RCDC`/`_BFRAC` convert the
plain Gurson law of cards 1-4 and leave cards 5 AND 6 **unread** rather than
striding them at a guessed layout. `NUMINT`, `VGTYP`, `DEXP`, `L1..L4` and a
negative `EN`/`SN` (element-length curve ids) are dropped with warnings
`*MAT_ISOTROPIC_ELASTIC_PLASTIC` / `*MAT_012` → `/MAT/LAW2` (PLAS_JOHNS). The
one LS-DYNA plasticity card written in **shear + bulk modulus**, so
`E = 9KG/(3K+G)` and `ν = (3K−2G)/(2(3K+G))` are derived first (a degenerate
`3K+G ≤ 0` is reported instead of dyna2rad's unguarded NaN, and an unphysical ν
is named). **`ETAN` goes into `b` verbatim with `n = 1`**: the manual calls
MAT_012's ETAN the "Plastic hardening modulus" (Vol II R17 p.2-206), i.e.
dσ/dεₚ, so it must NOT get the `E·ETAN/(E−ETAN)` rescale that `*MAT_003`'s
identically-named *tangent* modulus needs on the `/MAT/LAW44` path. No
strain-rate, thermal or failure terms exist on this card
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
with a warning, so review the converted card against the source foam.
Foam batch 2 (dyna2rad's targets, constants followed exactly):
`*MAT_SOIL_AND_FOAM` (005) → `/MAT/LAW21` (DPRAG) — `E=9GK/(3K+G)`,
`ν=(3K−2G)/(6K+2G)` clamped to [0, 0.495] (the clamp warned when it fires),
`A0/A1/A2` verbatim (identical yield surface `J2 = a0+a1·p+a2·p²`),
`PC → P_min` verbatim (the `PC=0` blank default flips meaning — LS-DYNA's
active zero-tension floor becomes LAW21's `-INFINITY` unlimited tension —
warned), `Kt = B = KUN` for `VCR=0` — a conscious fix over dyna2rad's
`Kt = KUN/100`: with `Mu_max` unset the starter substitutes `1e20` and the
engine's unloading bulk `α·B + (1−α)·Kt`, `α = μ/Mu_max`, degenerates to
`Kt` (`m21law.F:166-170`), so d2r's `B` is a DEAD field and its soil
unloads at `KUN/100` in both signs, retracing the loading curve
(measured: ~0% dissipation); `Kt = KUN` restores LS-DYNA's elastic-line
unloading. `VCR=1` keeps d2r's `B=0` + `Kt=KUN/100` pair on purpose — the
starter substitutes `B=Kt` (WARNING 829) and the soft modulus reproduces
VCR=1's load=unload retrace (measured), warned; the
pressure curve (`LCID` preferred, else the `EPS/P` pairs, trailing blank
slots stripped, the LS-DYNA auto-`(0,0)` point reproduced) gets THE axis
transform `mu = exp(−EPS) − 1`: LS-DYNA tabulates `P` vs `EPS = ln(V/V0)`
(negative in compression), the LAW21 engine evaluates `P(mu = ρ/ρ0 − 1)`
(positive in compression, `mmain.F90:686`), so the points transform and
re-sort ascending with ordinates unchanged; an all-positive curve (both
dyna2rad branches require a negative abscissa and silently emit NO function)
converts as `|EPS|` with a warning.
`*MAT_LOW_DENSITY_VISCOUS_FOAM` (073) → `/MAT/LAW90` — `E→E0`, the `LCID`
nominal-stress curve referenced by id as the single quasi-static loading
function (`NL=1`, `Ismooth=1` — dyna2rad's fixed values), `HU→Hys`,
`SHAPE→Shape`; the explicit `Gi/BETAi` cards (LCID2=0 branch) become a
`/VISC/PRONY` of the same material id with the `BETAi>0` filter; the
`LCID2>0` relaxation-fit and `LCID2=−1` frequency-data branches convert
rate-independent with a loud warning (nobody performs LS-DYNA's internal
fit); `TC/FAIL/KCON` are radioss2026-only LAW90 fields (`Tcut/FAIL/Kcont`)
and are named-dropped at `/BEGIN 2022`, `DAMP` likewise (dyna2rad moves it
onto the property; k2rad keeps the section-derived `/PROP/SOLID`, matching
its MAT_057 policy). The MAT_073 parts' `/PROP/SOLID` is pinned to
`Ismstr=10` (total strain) unconditionally — dyna2rad's own rule for every
MAT_073 section (CP:484-495), not only on the `/XREF` path; a non-foam part
sharing the section switches along, warned.
`*MAT_MODIFIED_HONEYCOMB` (126) → `/MAT/LAW50` on a synthesized
`/PROP/TYPE6` (SOL_ORTH) via the shared AOPT machinery (`AOPT=2 →
/SKEW/FIX`, 0/1/3/4/`<0` per the composite table) — TYPE6 is required
because only `IGTYP 6` builds the orthotropy tensor (`SMORTH3`,
`s8zinit3.F:435`); the starter would silently collapse the directions on
`/PROP/TYPE14`. The property pins `Isolid=1` + `Ismstr=1` (dyna2rad's
fixed honeycomb values, CP:415/472): MAT_126's default element is
LS-DYNA's 1-point corotational type 0 whose yield curves are
ENGINEERING-strain — a large-strain formulation would evaluate them at
LOG strain and pull the densification knee ~28% early (measured); a
non-corotational source ELFORM (log-strain curves per the manual) is
warned. Slot order `11/22/33/12/23/31` with the LS-DYNA fallback
chain (`LCB/LCC→LCA`, shear→`LCS→LCA`), moduli `EAAU..GCAU` with `0→E` /
`0→E/2(1+PR)` fallbacks, `Iflag1=Iflag2=−1`; a curve whose first abscissa
is `>0` is stress-vs-`V/V0` and is recomputed to `1−V/V0` as a new
`/FUNCT` (dyna2rad's rule); `LCSR>0` samples up to 5 `(rate, scale)` pairs
(the curve's FIRST FIVE points — the MODIFIED rule) and replicates each
direction's function per rate with `Fscale`=ordinate; `LCSR=−1`
per-direction rate cards are dropped loudly (dyna2rad never reads them);
`TSEF/SSEF → Eps_max` (the `<0` curve forms warned); the `LCA<0`
transversely-isotropic surface follows dyna2rad's remap under a loud
approximation warning (its damage curves become yield curves), `ECCU<0`'s
third surface is named-dropped; the compacted-state block (`E/PR/SIGY/VF`)
maps onto LAW50's radioss2025-only compaction card and is inexpressible at
`/BEGIN 2022` — warned, never silently emitted.
`*MAT_DESHPANDE_FLECK_FOAM` (154) → `/MAT/LAW115` (DESHFLECK, deterministic
`Istat=0`) — the direct 1:1 counterpart, hardening constants verbatim
(identical flow law), `CFAIL→EPSVP_F` and `PFAIL→SIGP_F` (a conscious fix:
dyna2rad's cfg never parses PFAIL, its SIGP_F is silently always 0);
`DERFI` (a derivative flag, NOT the `Ires` return-mapping selector) and
`NUM` (Radioss fails on the FIRST violation) are named-dropped. LAW115 hex
parts are routed to `/PROP/SOLID Isolid=24` (HEPH — dyna2rad's own hex
default): on the ELFORM-derived full-integration `Isolid=17` LAW115 is
ENGINE-fatal — the solid dt collapses below DTMIN at cycle 0 and the run
"completes" after 1 cycle with NORMAL TERMINATION and an empty result
(measured; at 24 the same deck runs to completion, 0 warnings). Tet
formulations keep their derived value with the WARNING-1905 window
pre-announced.
`*MAT_HILL_FOAM` (177) → `/MAT/LAW62` (VISC_HYP), constants branch —
`Nu = N/(1+2N)`, `mu_i = Ci·Bi/2`, `alpha_i = Bi` INDEX-ALIGNED over the
nonzero-C slots (dyna2rad compacts the C and B lists independently and
mispairs them when a `Ci` is zero mid-list); card 1 is `MID RO K N MU`
(manual p.2-1216, and the shipped mat_177.cfg agrees — field 4 is N);
the `nu_i` block is emitted as explicit zeros (2022-format card
the starter reads); `K/MU/LCSR` and the Mullins `R/M` card are
named-dropped. The `LCID>0` curve-fit branch has NO LAW62 counterpart
(LAW62 has no `Itab`/fit path at all) and warn-skips at parse — dyna2rad
emits nothing and silently wires the part's mat to 0.
`*CONTACT_INTERIOR` → the Radioss counterpart is `Icontrol=1` (solid
distortion control) on the listed parts' `/PROP` — an input column that
exists only in the radioss2025 property format. Measured on `starter_win64`:
under `/BEGIN 2022` the trailing card reads as `Ndir sphpartID` only (the
per-part echo stays `ICONTROL 0`, plus WARNING 100213); under `/BEGIN 2025`
the same card echoes `ICONTROL 1` cleanly. k2rad emits 2022 decks, so the
keyword is resolved (each PSID is a `*SET_PART`; a `*SET_PART_ADD` is
flattened post-parse into a plain part set — one level of part-set
nesting — for EVERY part-set consumer, contacts and `--auto-gapmin`
included, and its header `DA1..DA4` attributes —
PSF/Fa/ED/TYPE — are read) and converted to a LOUD warning naming the solid
parts left without interior contact (mitigation: `/DT/BRICK/CST`, or set
`Icontrol=1` by hand after migrating to the 2025 format), the parts whose
property type has no Icontrol at any version, and the dropped attributes;
`note_recognized_not_emitted` records the keyword. Emitting the dead field
would be silently wrong.
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
`Ismstr=10`, which the starter would force anyway — WARNING 1200). **Running a
LAW95 part free and explicit needs care.** At a realistic `PR≈0.495` the bulk
modulus is ~100× the shear modulus, so the volumetric mode is two orders of
magnitude stiffer than the deviatoric one and, being essentially undamped, it
rings: the part's volume oscillates (and can grow) long after the deviatoric
response has settled. Nothing in the conversion is wrong when this happens —
it is the near-incompressible explicit problem itself. Mitigate it by ramping
the load instead of applying it as a step, by adding damping or bulk viscosity,
or by running the load case implicit quasi-static. Note also that the sibling
`/MAT/LAW42` bulk curve is not an escape hatch: `funIDbulk`'s ordinate is a
dimensionless multiplier on the `Nu`-derived bulk (`sigeps42.F`,
`K_eff = RBULK·Fscale·f(J)`), and supplying it BYPASSES the no-curve branch's
anti-buckling `P_FAC` floor. `N>0` →
`/MAT/LAW69`; its
`Gi/BETAi` list becomes `/VISC/PRONY` of the material id on BOTH branches
(`Beta_i` used directly, no inversion). `*INITIAL_FOAM_REFERENCE_GEOMETRY`
(`_RAMP`) → one `/XREF` per intersecting part with the stress-free reference
coordinates (`NDTRRG`→`Nitrs`); emission follows dyna2rad (unconditional, the
material `REF` flags only drive coverage warnings), but parts the starter
would reject are warn-skipped instead (solid `/XREF` accepts laws
1/35/38/42/70/88/90 only — ERROR 2014 — and 8/4-node solids — ERROR 2013;
the law comes from the shared `_target_mat_law` routing, so a `*MAT_RIGID` or
`*MAT_SPOTWELD` part reaching `/MAT/ELAST` counts as LAW1 like any other),
and the kept parts' solid sections switch to `Ismstr=10` (starter ERROR 2013
otherwise on the fully-integrated `Isolid=17`). One skip is a PHYSICS rule and
not a starter one: a `*MAT_RIGID` part converts to an `/RBODY`, so its nodes
are kinematically slaved and it has no strain state to define — the starter
takes the block (measured `0 ERROR(S) 0 WARNING(S)`) but it is inert, and
emitting it would drag the part's `*SECTION_SOLID`, and any deformable part
sharing it, to `Ismstr=10`. `REF=1` without usable
reference geometry is warned, and so is the mirror case — a `/XREF` landing on
a `REF=0` material, which LS-DYNA would not apply (`EQ.0.0: Off`) but which
dyna2rad and k2rad both still emit.

Viscoelastics (dyna2rad's law choices and constants followed, its documented
field-map defects corrected): `*MAT_VISCOELASTIC` (006) → `/MAT/LAW34`
(BOLTZMAN) — the one EXACT 1:1 in the batch, since LS-DYNA's
`G(t) = GI + (G0−GI)e^{−βt}` is literally LAW34's kernel and `BETA` is a decay
rate on both sides (engine-validated on a single-element shear-relaxation run:
0.007 % worst error over 195 states); a negative `BULK`/`G0`/`GI`/`BETA` is a
temperature-curve id, which LAW34 cannot carry, so it is collapsed to the value
at the LOWEST tabulated temperature and warned — including `BULK`, which
dyna2rad never reads at all, leaving `K=0` and an unreadable card.
`*MAT_KELVIN-MAXWELL_VISCOELASTIC` (061) → `/MAT/LAW40` (KELVINMAX) with
`G_inf=GI`, `G1=G0−GI`, `BETA1=DC` and `Astass/Bstass/Kvm=0` (the starter turns
0 into infinity, i.e. no Stassi/von-Mises cap); `FO=1` selects the KELVIN form,
where `DC` is a *retardation* constant under a different evolution equation that
LAW40 cannot express — loudly warned instead of silently converted, and the
`ERROR 49` Poisson gate (`BULK ≥ (2/3)·G0`) and LAW40's **solids-only**
applicability (`ERROR 3046` on a shell part, with `*MAT_006` named as the
shell-capable substitute) are both checked up front.
`*MAT_GENERAL_VISCOELASTIC` (076, + `_MOISTURE`) → a `/MAT/LAW42` elastic
carrier (`Nu=0.495`, `Mu=±0.01·BULK`, `alpha=±2` — dyna2rad's fixed form, with a
warning naming the ground shear modulus `0.02·BULK` and the derived bulk
modulus `1.993·BULK` it really produces, plus the `Nu` that would pin `BULK`
exactly) plus `/VISC/PRONY`: explicit `GI/BETAI/KI/BETAKI` rows go in as
`Itab=0` with **all four columns** (dyna2rad asks for `"BETAK"` instead of
`BETAKI` and drops every bulk decay constant), and the `LCID`/`NT` +
`LCIDK`/`NTK` relaxation-curve form becomes `Itab=1`, so the starter runs the
same least-squares Prony fit LS-DYNA does — a branch dyna2rad can never reach
(it reads `LSD_LCIDK`, an attribute that does not exist) and whose absence makes
it emit an empty `/VISC/PRONY`, i.e. `ERROR 2026` on the whole deck. An elastic
MAT_076 gets no `/VISC/PRONY` at all rather than that error. The single
`M = min(max(NT,NTK),6)` counts only the fits that RUN: "if zero the default is
6" is per fit, and LS-DYNA fits the bulk series only when `LCIDK` is given, so
an absent curve contributes 0 — defaulting it to 6 would pin `M` at 6 for every
single-curve card and trip the starter's `2·M < npoints` rule (`ERROR 1921`) on
a deck LS-DYNA fits fine. `PCF` is *not*
written into `sigma_cut` (a flag into a stress field would impose a 1-unit
cut-off), and `EF`/`TREF`/`A`/`B`/`BSTART`/`TRAMP` and the whole `_MOISTURE`
card are warn-dropped. `*MAT_SIMPLIFIED_RUBBER/FOAM` (181, +
`_WITH_FAILURE`/`_LOG_LOG_INTERPOLATION`) and
`*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE` (183) → `/MAT/LAW88`
(TABULATED_HYPERELASTIC): a `*DEFINE_TABLE` `LC/TBID` becomes the `FCT_ID_LI`
/`EPSI_LI` rate family with the top curve repeated at 10× the highest rate
(dyna2rad's flat-extrapolation guard), a `*DEFINE_CURVE` becomes a single row,
and unloading follows `LCUNLD` → `HU`/`SHAPE` → the loading curve itself —
though note that LAW88 uses `FCT_ID_UN` only as a normalised SHAPE RATIO
`g_unl/g_load` clamped to `[0,1]` (`sigeps88.F90:762-790`, after
`hm_read_mat88.F90:405-421` forces the endpoints together and rescales both
axes), so an LS-DYNA MAT_183 hysteresis loop is not reproduced curve-for-curve.
A loading curve with no negative-strain branch is warned, because LAW88
evaluates it at all three principal stretches and uniaxial tension drives the
lateral ones into compression (measured: the cell bifurcated at `eps=0.65` and
still reached NORMAL TERMINATION with wrong results). The
specimen normalization is baked into the curve POINTS (abscissa `1/SGL`,
ordinate `1/(SW·ST)`, into a `_Duplicate` `/FUNCT`) because a `/BEGIN 2022`
starter forces `SGL=SW=ST=1.0`; a blank dimension reads as 1.0 instead of
dyna2rad's refusal to write any curve, which turns an already-normalized deck
into `NL=0` (`ERROR 866`). `PR` goes into `NU` verbatim — LAW88's own
`nu≤0 → beta=|nu|, nu:=0.495` rule *is* LS-DYNA's viscous-pressure input, which
dyna2rad loses by writing 0 — and `TENSION` is transferred (dyna2rad asks for
`"TENSIOM"`, a string that appears nowhere else in the Radioss tree, so its
MAT_181 rate-effect flag never arrives). `0 < PR < 0.49` selects LS-DYNA's
compressible **Hill foam**, which LAW88 has no branch for (dyna2rad's
MAT_181→LAW70 foam converter exists but has no caller) — loudly warned. The
fields the `/BEGIN 2022` LAW88 card physically cannot carry — `RTYPE`,
`G`/`SIGF`, `SGL/SW/ST` and the whole `_WITH_FAILURE` `K/GAMA1/GAMA2/EH`
criterion, all of which live on the radioss2026 revision a 2022 starter
*swallows without an error* — are warn-dropped rather than emitted as silent
data loss, as is MAT_181's `MU` (a property field in dyna2rad). MAT_181's
optional `Gi/BETAi` cards become a `/VISC/PRONY` of the material id.
`*MAT_SOFT_TISSUE` (091) / `_VISCO` (092) → `/MAT/LAW42` with `Mu_1=2·C1`,
`Mu_2=−2·C2`, `alpha=±2`, `Nu=0.495` and the `S_i`/`T_i` pairs in LAW42's own
`Gamma_arr`/`Tau_arr` (relaxation *times* on both sides, so no inversion), with
the non-zero pairs COMPACTED — dyna2rad counts the non-zero `S_i` but copies the
first M slots, so a gap converts the wrong terms. This one gets the loudest
warning in the batch: the material becomes an **isotropic incompressible
Mooney-Rivlin rubber**, the transversely-isotropic collagen fibre term
(`C3/C4/C5`, `XLAM`, `XLAM0`, `FANG`), the entire fibre orientation, the bulk
modulus `XK` and all three `FAILS*` modes are dropped, and for a ligament or
tendon that is not a physically equivalent material — dyna2rad performs exactly
the same conversion without saying so. A second warning names the `S_i` unit
mismatch it inherits (LS-DYNA's `S_i` are dimensionless factors; Radioss reads
`Gamma_i` as a shear modulus) and prints the `S_i·MU0` values that would carry
the intended viscous stiffness

Adhesives / cohesives (dyna2rad's law choices followed; its two documented
flag/gate defects corrected, its silent drops warned; every card
starter-validated at `/BEGIN 2022`, 0 errors, plus a negative control that
draws the real `ERROR 3047`): `*MAT_COHESIVE_MIXED_MODE` (138) →
`/MAT/LAW117` — `EN`/`ET` copy RAW (stiffness per unit length on both sides,
no thickness rescale), `ROFLG` 0/1 → `Imass` 2/1 written explicitly (a blank
`Imass` is coerced to 1 = AREA density, which would silently flip the LS-DYNA
volume default), `XMU`'s **sign** is the criterion switch (`>0` power law →
`Irupt=1`/`EXP_G`; `<0` Benzeggagh-Kenane → `Irupt=2`/`EXP_BK=|XMU|`, written
explicitly since `EXP_BK` has no starter default), a negative `T`/`S` is a
peak-traction-vs-element-size curve → `Fct_TN`/`Fct_TT` with `TMAX=1.0`, and
`T=0` back-computes `TN = 2·GIC/UND` from the ultimate displacement (LS-DYNA's
own `GIC = T·UND/2` identity, which also keeps the input below the starter's
`GIC ≥ TN²/(2·EN)` floor); curve-valued `GIC`/`GIIC` (negative, R13 form) have
no LAW117 slot — zeroed loudly. `INTFAIL` transfers as the `Idel` failed-IP
count with its two semantic gaps warned: `INTFAIL=0` is LS-DYNA's
*never-delete* state (Radioss coerces `Idel` 0→1, the element WILL erode) and
a negative `INTFAIL` selects Newton-Cotes, which TYPE43's fixed 4-Gauss-point
scheme cannot hold.
`*MAT_ARUP_ADHESIVE` (169) → `/MAT/LAW169` (the dedicated radioss2025 ARUP
card; under k2rad's `/BEGIN 2022` the starter prints non-fatal
`WARNING 100211` and parses the 2025 layout correctly — verified against a
`/BEGIN 2025` control run). Two layout traps handled: `SHT_SL` moves into the
MIDDLE of LAW169 card 2, and `PWRT`/`PWRS` are `%10d` INTEGERS (a non-integer
exponent is rounded and warned). Only the static core converts — the rate
scaling (`EDOT0`/`EDOT2` + `SDFAC/SGFAC/SDEFAC/SGEFAC`), the `EXTRA` edge
cards, `THKDIR`, `BTHK` and the negative-value curve forms of the strengths
are all warn-dropped (dyna2rad drops them silently) — and LAW169 always uses
VOLUME density (absent from the `sini43.F` area-mass list), so a zero-height
ARUP cohesive gets zero mass: warned whenever MAT_169 lands on a cohesive
ELFORM.
`*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE` (240) → `/MAT/LAW116` — `EMOD`/
`GMOD` are TRUE moduli (the starter divides by `Thick` itself:
`UPARAM(1)=E/THICK`; dividing in the converter would apply it twice), and the
rate encodings map sign-for-sign: `G*C_0<0` activates rate-dependent
toughness (`GC_ini=|G*C_0|`, `GC_inf`, `SRATG`), `T0<0` rate-dependent yield
with `T1`'s sign picking the quadratic/linear-log form (`ORDER` 2/1),
`FG>0`/`<0` the energy/displacement failure criterion (`FAIL` 1/2). Two
dyna2rad defects fixed consciously: the mode-II rate gate keys on `G2C_0<0`
like mode I and the manual (d2r keys on `EDOT_G2<0` — a slip that zeroes the
mode-II reference rate on every valid deck), and `Idel` carries `|INTFAIL|`
(d2r hard-codes 1, ~4× over-erosion for an `INTFAIL=4` bondline). `INICRT`
maps onto `Icrit` against the engine kernel (0 quadratic → default; 1/2
maximum nominal → `Icrit=2`); `THICK=0` is warned (LS-DYNA = element
geometric thickness, LAW116 = 1.0 length unit); `LCG1C`/`LCG2C` toughness-vs-
thickness curves are warned as the override they are (LS-DYNA *ignores* the
scalars when they are set); the `_THERMAL`/`_3MODES`/`_FUNCTIONS` variants
warn-skip (their cards hold curve ids / mode-III data with no LAW116 slot —
dyna2rad drops them with no message and a dangling part).
`*MAT_TOUGHENED_ADHESIVE_POLYMER` (252) → `/MAT/LAW120` (TAPO — the same
model): a near 1:1 copy including `D1→D1F`, `D2→D2F`, `D3→Dtrx`, `D4→Djc`,
with `LCSS` re-emitted as a 1-D `/TABLE/1` (LAW120's `Table_Id` is a TABLE
slot; both codes ignore the analytic `TAU0..GAMM` when it is set). The three
flags translate against the engine kernels — `FLG` 0/2 → `Iform` 1/2, `JCFL`
0/1 → `Itrx` 2/1, `DOPT` 0/1 → `Idam` 2/1 — fixing dyna2rad's dead `== 2`
switch branches, under which every `JCFL=1`/`DOPT=1` deck silently ran the
wrong engine branch. `SRFILT` and `IHIS` are parsed from the R16 positions
(the local R7.1 cfg blanks both) and warn-dropped.
`*MAT_ADD_DAMAGE_DIEM` → `/FAIL/INIEVO` (a rider keyed by the parent MID,
coexisting with `*MAT_ADD_EROSION`'s `/FAIL/GENE1` and GISSMO's `/FAIL/TAB2`
on the same material): `NDIEMC` criteria (max 5) map 1:1 — `DITYP` 0..4 →
`INITYPE` 1..5 in the same order, `P1`/`P5` → `TAB_ID`/`TAB_EL` (TABLE slots,
curves re-routed to 1-D `/TABLE/1`), `P2`/`P3` → `PARAM` per `DITYP`,
`DETYP`/`DCTYP` +1 → `EVOTYPE`/`COMPTYP`, `Q1` → `DISP` or `ENER`, `Q3` →
`ALPHA` with the exponential `EVOSHAP=2`. `P4` → `ISHEAR` INVERTED (the flags
have opposite sense: LS-DYNA `P4=0` *includes* the transverse shear stresses,
Radioss `ISHEAR=1` *considers* them) and written explicitly; a per-criterion
`P4` conflict is warned (one global flag — last wins, dyna2rad parity).
`NUMFIP` resolves against the parts that actually reference the MID —
`FAILIP` for solid use, `PTHICKFAIL` through the same NUMFIP rule
`/FAIL/GENE1` uses for shell use — instead of dyna2rad's whole-model
element-count heuristic with its stale per-part NIP. A table-form `Q1`
(negative) collapses to its MINIMUM ordinate (dyna2rad's conservative rule,
warned with the value); `DCTYP=-1` (damage kept OFF the stress) has no
counterpart and is warned as the physics change it is; `DINIT`/`DEPS`/
`VOLFRAC`/`Q2`/`Q4` and the MSFLD/FLD layer selection are warn-dropped;
`P1=0`/`Q1=0` name the exact starter errors (2088/2089/2090) they will draw.
**Cohesive element path**: `*SECTION_SOLID` ELFORM ±19/20/±21/22 →
`/PROP/TYPE43` (CONNECT) under the SECID verbatim — `Ismstr=1` pinned (what
the starter resolves anyway), `True_thickness` from `*SECTION_SOLID_MISC`
`COHTHK` (its exact analogue). The LS-DYNA node convention (bottom face
1-2-3-4, top 5-6-7-8) is identical to TYPE43's, so `*ELEMENT_SOLID`
connectivity passes through unpermuted, pentahedron cohesives (±21/22,
`N1 N2 N3 N3 N5 N6 N7 N7`) stay the same degenerate `/BRICK` pattern, and
zero-height pads survive every degenerate-element screen (TYPE43 is
area-based; the validation run gave a zero-height pad its full `ρ·A` mass).
A section is ALSO routed to TYPE43 when any part on it carries a
SOLID_COHESIVE law (LAW116/117/169 — dyna2rad's material rule, covering
`*MAT_ARUP_ADHESIVE` on ordinary ELFORM 1/2/15 bricks), while MAT_252 stays
on the plain solid property unless the ELFORM itself is cohesive (LAW120 is
SOLID_ALL — legal on both, d2r parity). Every pairing the starter would
refuse is warned with the real id: a non-TYPE43-class law on a cohesive
section (and the reverse) is `ERROR 3047` — measured verbatim on a negative
control — ELFORM 20/22's shell-offset moments and `COHOFF` have no TYPE43
mechanism, `GASKETT` is not an adhesive path, and hourglass splits
(`*HOURGLASS`/`*CONTROL_HOURGLASS`) never touch a cohesive part.
`*EOS_LINEAR_POLYNOMIAL` → `/EOS/POLYNOMIAL`, `*EOS_GRUNEISEN` → `/EOS/GRUNEISEN`,
`*EOS_IDEAL_GAS` → `/EOS/IDEAL-GAS` (γ = Cp/Cv, P0 = ρ(Cp−Cv)T0)
`*MAT_TABULATED_JOHNSON_COOK` (224, `_LOG_INTERPOLATION` → `I_smooth=2`) →
`/MAT/LAW109` `[+ /FAIL/TAB1]` — the fully tabulated flow stress
`σ_y = k1(ε_p, ε̇)·kt(ε_p,T)/kt(ε_p,T_ref)`. `CP` copies 1:1 (LAW109's `C_p`
is per-MASS — the engine divides by ρ itself — unlike the LAW2/LAW4 `rhoC_p`);
adiabatic self-heating is law-internal, so NO `/HEAT/MAT` is emitted (its
presence would switch LAW109 to the imposed-temperature path). `LCK1` routes
by form: a plain curve is re-emitted as a 1-D `/TABLE/1` (dyna2rad leaves the
slot 0 — deck broken); a 2-D table is referenced by id under `I_smooth=1`;
every `I_smooth=2` table — the `_LOG_INTERPOLATION` spelling or a NEGATIVE
first rate (LS-DYNA's natural-log axis, `exp()`-unwrapped) — is rebuilt with
BOTH flat-clamp rows: dyna2rad's high-rate sentinel (last curve duplicated at
`10·max+1`) plus the first curve anchored at rate `1e-10`, because the engine
clamps only the log-lookup SAMPLE there and otherwise EXTRAPOLATES in log10
below the lowest rate — at the zero plastic strain rate of every elastic
phase the yield goes NEGATIVE (e.g. rates `[1,100,1000]`: `6·Y1−5·Y2`) and
the run diverges silently under NORMAL TERMINATION; solver-validated, the
anchored deck tracks the log10 prediction to 0.0000%. A 3-D `σ(ε_p,ε̇,T)` is
SPLIT — `tab_ID_h` = the plane nearest `T_ref`, `tab_ID_t` = the per-plane
lowest-rate curves over T (LAW109's yield lookup hard-stops on NDIM>2 at
cycle 1; d2r wires the 3-D id straight in and produces exactly that crash;
the split is exact iff rate/temperature separate multiplicatively — warned,
`LCKT` then ignored like LS-DYNA does), and when the nearest plane is NOT at
`T_ref`, `Yscale_h = kt(T_ref)/kt(T_plane)` cancels the constant separable-
factor offset the reconstruction would otherwise carry. `BETA≥0` → `ETA`;
`BETA<0` → `TAB_ETA` (curve → 1-D table; a negative first abscissa makes the
WHOLE axis ln(rate) per LS-DYNA's stated convention, so EVERY point is
`exp()`-unwrapped — d2r exp()s only the negative points, scrambling
mixed-sign axes; 2-D table direct — LS-DYNA's (T → rate) nesting IS
TAB_ETA's (rate, T) axis order, per the manual's own level tags for the
3-D/4-D forms and d2r's untransposed pass-through; TABLE_3D would need a
full axis transpose → the table warn-drops and a representative scalar
`ETA`, sampled at (lowest rate, plane nearest `T_ref`, ε_p→0), replaces the
old flat 1.0). Failure emits `/FAIL/TAB1` ONLY for a usable `LCF` (d2r
writes its card unconditionally → starter ERROR 3000 on LCF-less decks): the
triaxiality axis is FLIPPED (LS-DYNA `p/σ_vm` compression-positive → Radioss
`σ_m/σ_vm` tension-positive), a Lode-dependent LCF adds dim 3 with
`θ = (2/π)·asin(ξ)` (Radioss interpolates the normalized Lode ANGLE, not the
Lode parameter; shells read the axis at θ=0), and `LCG` — which has no TAB1
function slot — becomes the PRE-MULTIPLIED `ε_f(triax)·g(rate)` tensor grid
via per-row `Scale_y` (a natural-log LCG axis is `exp()`-unwrapped; d2r
copies it raw). `LCI` → `fct_IDel` with `EI_ref` blank → 1.0 (abscissa =
absolute element size, same as LCI); `NUMINT` → `Ifail_sh=1` (count 1),
`P_thickfail=count/NIP` (d2r's `FAILIP=NUMINT/100` truncates every
0<NUMINT<100 to zero), or `|NUMINT|/100` for the percent form; `NUMINT=8` on
fully integrated solids (ELFORM 2/−1/−2 → Isolid 17, 8 IPs both sides) maps
to `Ifail_so=2` — deletion when ALL IPs fail, exactly LS-DYNA's 8-of-8 rule
— other solid counts keep first-IP deletion, warned; `NUMINT=-200` (no
erosion) emits NO /FAIL. `LCH` is ALWAYS warn-dropped: TAB1's `fct_IDT` is
evaluated at `TSTAR`, which no LAW109 engine path ever fills — a mapped
`LCH(T)` would read at abscissa 0 every cycle and erode the mesh at cycle 1.
`E<0` (E(T) curve) is sampled at `T_ref` (d2r takes the first ordinate);
`BFLG`/`ERODE`/`LCPS`/`FAILOPT`/`NUMAVG`/`NCYFAIL` warn-drop; the `_GYS`
(224_GYS) and `_ORTHO_PLASTICITY` (264) variants warn-skip — dyna2rad drops
both SILENTLY with the part wired to `mat_ID=0`. `Xscale_h` deliberately
stays blank: the engine applies it to the pre-yield rate sample but NOT to
the in-loop plastic re-lookup (sigeps109.F:221 vs 349), so the two lookups
agree only at 1.0. Note LAW109 has no initial-temperature input in LS-DYNA's
MAT_224 either — `T_ini` defaults to `T_ref` and a second temperature is
reachable only through self-heating (or a thermal analysis); the engine's
plastic-strain-rate filter is hardwired FCUT = 10 kHz, so mass-scaled decks
with dt > 1.6e-5 s put the filter recursion outside its stability range.
Starter-validated end to end (0 errors, field-by-field echo incl. the 3-D
grid's `1.2·1.3=1.56` Scale_y product; ERROR-3089 negative control) and
solver-validated on 22 single-element decks (rate table to 0.2%, log10
interpolation to 0.0000%, adiabatic heating to 0.002%, triaxiality-flipped
failure to 0.06%, LCG/LCI scaling to 0.12%, NUMINT layer counting exact) —
see `tests/test_tabulated_jc.py`.

`*MAT_JOHNSON_HOLMQUIST_CERAMICS` (110) → `/MAT/LAW79` (`JOHN_HOLM`),
`*MAT_JOHNSON_HOLMQUIST_CONCRETE` (111) → `/MAT/LAW126` — the two impact
laws, and the family whose defining property is that **nothing is normalized
on conversion**. Both codes state JH in the same normalized-strength form, and
the Radioss starter/engine re-derive every normalizer with the identical
definitions LS-DYNA uses: JH-2's σ_HEL = 1.5(HEL−PHEL) and T\* = T/PHEL are
formed by the starter, P\* = P/PHEL and σ\* = σ_vm/σ_HEL by the engine; JHC's
P\* = P/f′c, σ\* = σ_vm/f′c and T\* = T/f′c likewise, with the yield
multiplied back up by f′c. So `A B C M N SFMAX EFMIN D1 D2` (and JHC's
volumetric strains) pass through as the dimensionless numbers they are on both
sides, and `HEL PHEL T FC PC PL G K1 K2 K3` as physical stresses — pre-dividing
T by PHEL/f′c, or writing σ_HEL where HEL belongs, would apply the
normalization twice and silently soften the material. `K1/K2/K3` are each
law's **own** polynomial pressure law, so **no `/EOS` is emitted** for either
(LAW126's `HYDRO_EOS` class tag is a pressure-treatment capability, not a
request for a companion block). Two field-order traps are handled: `*MAT_110`
card 1 runs `… C M N` while LAW79 card 3 runs `a b m n` with `c` moving to the
next card and `BETA` to the last, and `*MAT_111` card 1 field 7/8 are `N` then
`FC` where 110 has `M` then `N` (LS-DYNA `UC`/`UL` are Radioss `MUC`/`MUL`).
`FS` splits by law, because both the LS-DYNA meanings and the Radioss `IDEL`
enumerations differ between them: MAT_111's `FS<0 / =0 / >0` → `IDEL 3 / 1 / 2`
(+`EPS_MAX=FS`) works and is emitted, matching dyna2rad; MAT_110's
`FS<0 / >0` → `IDEL 1 / 2` is **not expressible** under the emitted
`/BEGIN 2022`, where LAW79's `IDEL`/`EPSMAX` are radioss2023 fields the reader
does not have — so it is warn-dropped naming the criterion and the
`*MAT_ADD_EROSION` remedy (dyna2rad drops MAT_110's `FS` *silently* at every
version, though it implements the flag for MAT_111; note the tensile cutoff
PMIN = −T\*·PHEL·(1−D) still applies at `IDEL=0`, so only element deletion is
lost). LAW126 is first registered in the radioss2024 profile, so a 2022 deck
draws one cosmetic `WARNING 100211` and is read with the 2024 layout — warned
so the starter output does not read as a defect; its `IFAILSO` is a
radioss2025 field, unreachable at 2022 and pinned to 1 (dyna2rad never sets it
either). Every guard the starter lacks is supplied by the converter, because
both laws are unusually quiet — LAW126 in particular has **no ANCMSG check at
all**, and its compaction divisions `k0 = PC/MUC` and `h = (PL−PC)/MUL` are
unguarded, so `UC=0`/`UL=0` produce a NaN Young's modulus and Poisson ratio at
*0 ERROR /
0 WARNING*. `EPS0 ≤ 0` with `C ≠ 0` is substituted with the starter's own
rate-free default (fatal ERROR 910 on LAW79 otherwise, and a per-cycle
`C·log(ε̇/0)` on LAW126) — **expressed in the deck's time unit**, since `EPS0`
is a 1/time quantity (Vol II R16 `*MAT_015`, which both cards refer to) and
k2rad rescales nothing, so a bare `1.0` would be 1000 s⁻¹ on a ton-mm-ms deck
and, because both engines clamp the rate factor to 1 *below* `EPS0`, would
switch rate hardening off rather than shift its onset. Both laws are
solid/SPH-only (no `SHELL_*` class on either), so a shell part is warned as
`ERROR 3046`.

**`PHEL` is the one field of this batch that is not a straight copy.** A blank
or zero `PHEL` is not a malformed card but a *documented LS-DYNA input mode*:
given `HEL` and `G`, LS-DYNA solves
`HEL = K1·μ + K2·μ² + K3·μ³ + (4/3)·G·μ/(1+μ)` for μ_hel and then sets
`PHEL = K1·μ + K2·μ² + K3·μ³` and `σ_HEL = 1.5(HEL−PHEL)` — *"These are
calculated automatically by LS-DYNA if p_hel is zero on input"* (Vol II R16
p.2-763/764). `/MAT/LAW79` has no such derivation: the starter forms
`T* = T/PHEL` directly and its only guard is `PHEL > HEL`, so a copied-through
0 passes with **0 ERROR / 0 WARNING** and then leaves every `P*` and `T*` at
Inf/NaN for the whole run (what a dyna2rad-converted deck does). k2rad
reproduces LS-DYNA's own iteration and emits the derived `PHEL`, reporting
μ_hel, `PHEL` and `σ_HEL`; when the derivation is not possible (`HEL ≤ 0`,
`K1 ≤ 0`, `G ≤ 0`) the hard warning stands, and a stated `PHEL` is never
touched.

`*MAT_ELASTIC_FLUID` (001 with the `_FLUID` option; also `*MAT_001_FLUID` and
`*MAT_1_FLUID`, which dyna2rad's keyword map misses entirely — there they
produce no `/MAT` and the part is wired to `mat_ID=0`) → `/MAT/HYD_VISC`
(LAW6) **+ `/EOS/POLYNOMIAL` of the same id**. The `/EOS` is not optional: a
2-card LAW6 without one passes the starter with 0 errors and 0 warnings but
leaves `PM(32) = C1 = 0`, i.e. zero bulk modulus and zero sound speed. `K` is
card-1 field 7 (not a second card) and becomes `C1`, with
`C0 = C2 = C3 = C4 = C5 = E0 = Psh = 0` — P = K·μ is exactly the linear form.
When `K` is blank the manual's own relation `K = E/(3(1−2ν))` is used with the
**real** Poisson ratio; dyna2rad's expression spells the token `NU` where the
attribute is `Nu`, identifier lookup is case-sensitive, and an unresolved
token silently becomes 0, so it computes `E/3` and loses ν entirely (a
negative `K` matches neither of its branches and leaves a zero-sound-speed
fluid — here it falls back too, warned). `E`/`PR` are otherwise dropped
because LS-DYNA ignores them under `_FLUID` and zeroes the shear modulus, and
LAW6 has no shear slot at all, so the pure-hydrodynamic response is exact
rather than approximated; `DA`/`DB` are beam-only damping. `VC` is
**dropped, not copied**: LS-DYNA's `VC` is a *dimensionless* tensor-viscosity
coefficient scaling S′ᵢⱼ = VC·ΔL·a·ρ·ε̇′ᵢⱼ, while the Radioss slot is a *true*
kinematic viscosity in L²/T entering as σ_dev = 2ρν·ε̇_dev — the factor ΔL·a
between them is per-element and not knowable at material-conversion time, so
the verbatim copy dyna2rad makes is wrong by orders of magnitude; the warning
carries the hand-conversion recipe ν ≈ VC·ΔL·a with a = √(K/ρ) already
evaluated. `CP` (cavitation pressure) → `Pmin` with the sign flipped, but only
when it is a real limit: LS-DYNA's documented default `CP = 1e20` means "no
cavitation" and maps to `Pmin = 0` → −INFINITY, not to −1e20 (an explicit
`CP = 0.0` is the one semantic Radioss cannot state, since `Pmin = 0` is the
reader's no-cutoff sentinel — reported). That default is a **raw literal**, so
a unit-converted deck carries it rescaled — the corpus bird-strike fluid reads
`CP = 1e20` in its kg-m-s copy and `CP = 1e14` in the ton-mm-s one, the same
material — and testing the literal alone would make the emitted card depend on
the deck's units; a `CP` at or above 10⁶·K is therefore treated as the default
too (it is unreachable: `Pmin` binds at a volumetric strain of `CP/K`), warned
with the ratio. LAW6 declares `SOLID_POROUS` rather
than `SOLID_ISOTROPIC`, so an ordinary `/PROP/TYPE14` solid is fine but an
orthotropic/composite solid property is `ERROR 3047`; shells are `ERROR 3046`.
See `tests/test_impact_mats.py`.

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

`*MAT_HILL_3R` (122) → `/MAT/LAW43` (HILL_TAB) or `/MAT/LAW32` (HILL), on the
same `/PROP/TYPE9` split. Unlike MAT_037 this card states **three independent
Lankford values**, so `R00`/`R45`/`R90` drop straight into their own slots (each
0 falls back to the reader's silent 1.0 = von Mises, warned). `HR` picks the
target law:

* `HR = 1` (linear) → LAW43 with a synthesized bilinear `/FUNCT`
  `[(0, P2), (1, P2 + E·P1/(E−P1))]`. **`P1` is the TANGENT modulus and `P2` the
  YIELD STRESS** (Vol II R17 p.2-852) — dyna2rad builds `{(0, P1), (1, P1+P2)}`,
  i.e. the two swapped — and because the LAW43 curve is stress vs *plastic*
  strain, `P1` needs the `E·P1/(E−P1)` rescale that MAT_037's already-plastic
  `ETAN` does not.
* `HR = 2` (exponential, σ = k·(E0+εp)ⁿ) → **`/MAT/LAW32`**, whose analytic Swift
  law `σ = A·(EPSILON_0 + εp)ⁿ` reproduces it exactly (`A`←`P1`,
  `EPSILON_0`←`E0`, `n`←`P2`). dyna2rad has no `HR = 2` branch at all, so the
  material silently ends up with `NUM_CURVES = 0` and starter `ERROR 366`.
* `HR = 3` (load curve) → LAW43 with `LCID` → `func_IDi`; a missing curve names
  `ERROR 366`.

`C_hard = 0` (MAT_122 has no iso/kinematic split) and `Iyield0 = 0` (the yield
stress is the r-value average form). The material-axis cards move to the
**property**, where `/PROP/TYPE9`'s single reference system covers `AOPT = 2`:
the a-vector becomes `Vx/Vy/Vz` and `BETA` the `Phi` rotation. `AOPT` 0/3 and a
negative (`*DEFINE_COORDINATE`) `AOPT` have no TYPE9 column and fall back to
global X with a warning naming where to set it by hand. dyna2rad reads none of
that block.

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
warn-dropped. **`_TSHELL` on a mesh of `*ELEMENT_TSHELL` converts to a real
`/PROP/TYPE22` with per-ply `mat_IDi` / `ti/t` / `Phi_i` — see **Thick shells**.
`_IGA_SHELL`, a `_TSHELL` whose elements are THIN shells, and an empty layup
warn and fall back to a plain shell property carrying the summed layup
thickness — the part and all its elements are always emitted.** (Before this
batch `*PART_COMPOSITE` had no handler at all, so the whole *part record*
vanished and took its entire mesh with it, silently.)

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
`PID_i` material-carrier part — the idiom the manual explicitly allows — works
as written: the element-free-`*PART` placeholder gives it a `/PROP/SHELL`, so
its `/PART` resolves instead of hitting starter ERROR 178.

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

### Thick shells

`*ELEMENT_TSHELL` → `/BRICK`, `*SECTION_TSHELL` → a three-way split onto
`/PROP/TYPE20` (`TSHELL`, isotropic), `/PROP/TYPE21` (`TSH_ORTH`, orthotropic)
or `/PROP/TYPE22` (`TSH_COMP`, layered) — the same branch dyna2rad takes
(`convertprops.cxx:4279-4312`): `ICOMP = 1` always wins, and an `ICOMP = 0`
section splits on whether the PART's material is orthotropic. The property sits
under the **SECID verbatim**, exactly where `/PROP/SOLID` would, so no `/PART`
repoint is needed.

**Connectivity is copied 1:1 and `Icstr` is written explicitly as `010`.** That
pair is what carries the thickness direction: LS-DYNA's "nodes n1 to n4 define
the lower surface, and nodes n5 to n8 define the upper surface" (Vol I R16
p.2703 Remark 1) is exactly the pairing Radioss reads at `Icstr = 010` —
`scdtchk3.F:84-246` takes the through-thickness edges as (1-5) (2-6) (3-7)
(4-8), and `scortho3.F` builds the same `S` axis out of the connectivity. So a
permutation would be a bug, not a fix. The field is genuinely read: patching
only `010` → `100` on an otherwise untouched deck moved the tip deflection by
**2.08x**, bit-identically onto the value the wrong connectivity gives. dyna2rad
leaves the column blank and lets the starter default it — but that default
(`IF (IHBE == 14 .AND. ICSTR == 0) ICSTR = 10`) exists for `Isolid = 14` only;
on `Isolid = 15` a blank column echoes `CONSTANT STRESS FLAG = 0`. Writing it
removes the dependence on both formulations.

A **degenerate 6-node** thick shell keeps LS-DYNA's collapsed
`n1 n2 n3 n3 n4 n5 n6 n6` form: written with trailing zeros it becomes an
`ISOLNOD = 6` penta, which Radioss then refuses on a thick-shell property unless
`Isolid = 15` (ERROR 639). A card that names only SIX ids — not a form LS-DYNA
defines, since Remark 1 spells the pentahedron out in all eight slots — is
expanded into exactly that spelling, and so is one written `n1..n6 0 0`.
Repeating the LAST id instead collapses the upper face to a point and halves the
volume (measured 1.950E-10 against the correct 3.900E-10, with the starter
reporting NORMAL TERMINATION and 0 ERRORS); all three spellings now give ρ·V.

`ELFORM` → `Isolid`: **1 → 15** (HSEPH, under-integrated + physical
stabilization), **everything else → 14** (HA8, locking-free full integration) —
dyna2rad's own total map. What that costs is named per section: ELFORM 5 and 6
lose their REDUCED integration, and ELFORM 1/2/6 lose their PLANE-STRESS
treatment, because they are extruded thin shells with an uncoupled
thickness-direction stiffness (Vol I R16 p.3717 Remark 1) while **every** Radioss
thick shell is a 3D-stress element. A **blank** `ELFORM` is LS-DYNA's default 1,
not 0 — dyna2rad reads the blank as 0 and lands on the full-integration HA8,
i.e. the opposite element class from the one the deck asked for by leaving the
field empty. An out-of-range value (there is no ELFORM 4) is warned and mapped
like the non-default forms.

`NIP` → `Inpts`, a **packed `ijk` field**. On `Isolid = 14` it is
`2 · 100 + clamp(NIP,1,9) · 10 + 2`, never below 212: the CFG only splits the
digits when the value exceeds 200, so a leading digit below 2 would be read as a
bare `Inpts_S` with zero points in `r` and `t`. On `Isolid = 15` it is the plain
`NIP`, clamped to 1..9 — dyna2rad clamps only the packed branch and passes a raw
`NIP > 9` through to starter ERROR 563. A blank `NIP` is LS-DYNA's default 2
("EQ.0: set to 2 integration points"), where dyna2rad keeps the raw 0 and then
writes zero ply cards against a property expecting one.

**Orthotropy (TYPE21/TYPE22)** reuses the same `AOPT` machinery as
`*PART_COMPOSITE`, translated into what a thick-shell card can hold — it has
`Vx/Vy/Vz + skew_ID + Phi` and no `Ip` column, and `scmorth3.F:126-134` resolves
the pair to ONE vector (`SKEW(1:3, ISKV)`, the skew's first axis, when
`skew_ID` is set) which it then PROJECTS onto the element mid-plane. So
`AOPT = 2` becomes a synthesized `/SKEW/FIX` whose `X'` is `a`, and a negative
`AOPT` becomes the `*DEFINE_COORDINATE` skew id — both exact. **`AOPT = 3`
carries a −90° shift on `Phi`**: LS-DYNA makes direction 1 the cross product
`v × n` rotated by `BETA`, and `v × n = R(−90°)·proj(v)` for any `v`, so
`V = v` with `Phi = BETA − 90` reproduces it exactly. dyna2rad copies `v` and
leaves `Phi` at 0, i.e. swaps material directions 1 and 2 — and for
`AOPT ∈ {0, 1, 4, negative}` it writes nothing at all, leaving a zero reference
vector that the starter rejects **per element** with ERROR 526. Here those three
modes (element frame, reference point, cylindrical) have no thick-shell
expression either, but they warn and fall back to global X so the deck still
starts.

**`/PROP/TYPE22` layers.** From `*SECTION_TSHELL ICOMP = 1` the card states one
`B_i` **angle** per integration point and nothing else — no per-layer material,
no per-layer thickness — so the layers come out equal-thickness on the part's own
material, and the warning says where a heterogeneous laminate would have to come
from. From **`*PART_COMPOSITE_TSHELL`** they carry real per-ply `mat_IDi`, angle
and `ti/t = THICKi / ΣTHICKj` — the manual makes those thicknesses relative on a
thick shell anyway ("the total thickness is obtained from the positions of the
nodes … the THICKi are also scaled to conform to the geometry", Vol I R16
p.3529), which is precisely TYPE22's `ti/t` semantic. `Zi` is left 0 with
`Ipos = 0` so the starter stacks the layers itself
(`Z1 = −0.5 + t1/2`, `Zk = Z(k−1) + (tk + t(k−1))/2`) — the `*INTEGRATION_SHELL`
lesson applied to a thick shell — which also means each layer carries ONE
integration point at its own mid-plane, so an N-equal-layer stack realises
`1 − 1/N²` of the exact bending stiffness (25 % soft at N = 2, 6.3 % at 4, 1.6 %
at 8, all measured). That is faithful to LS-DYNA's own one-point-per-ply rule
and the warning says so, because it means switching `ICOMP` 0 → 1 at the same
`NIP` changes the bending stiffness. More than nine layers on `Isolid = 14` use
the `Iint` encoding (thickness digit 0, count in `Iint`); on `Isolid = 15` the
count IS `Inpts` with no cap below `NLYMAX = 200` — `hm_read_prop22.F`'s
`CASE(15)` has no range check, the 1..9 limit MSGID 563 enforces belongs to
TYPE20/TYPE21 — so a laminate keeps the deck's own `ELFORM` either way.
**dyna2rad emits `/PROP/TYPE51` + `/PROP/TYPE19` for `*PART_COMPOSITE_TSHELL`**
— it dispatches on the substring `COMPOSITE` alone — and its own starter then
refuses that on the bricks: `ERROR ID : 60 INVALID PROPERTY ID=1 (TYPE = 51) FOR
BRICK ELEMENT`, `ERROR ID : 226 WRONG SOLID PROPERTY TYPE 51`.

**`*ELEMENT_TSHELL_BETA` and `_COMPOSITE` keep their mesh, and their data where
Radioss can hold it.** dyna2rad's CFG declares no `BETA` attribute and no option
on this keyword at all, so it cannot match either header and drops the whole
block, elements included. Here `_BETA` (five F16 cells, the angle in cols 65–80)
is FOLDED into the property angle when every thick shell on the section agrees
— `/BRICK` has no per-element angle column, unlike `/SHELL` — and warn-dropped
when they disagree; `_COMPOSITE`'s per-element ply stack is promoted to a
per-part `/PROP/TYPE22` when every element of the part declares the same one,
and warn-dropped otherwise. An unrecognized suffix takes the provisional path:
every line that can only be connectivity is kept, then screened against the node
table before it reaches the deck.

**Material compatibility is checked pre-starter.**
`check_mat_elem_prop_compatibility.F:198-234` gates each property on the
material's `PROP_SOLID` class — TYPE20 takes 1/5/6, TYPE21 takes 1/2/6, TYPE22
takes 1/2/3/6 — and anything else is ERROR 3047 (a law with no solid class at
all is ERROR 3046 one step earlier). So an orthotropic law on a TYPE20, a porous
`/MAT/LAW6` on a TYPE21/22 and a shell-only `/MAT/LAW27` / `LAW32` / `LAW43`
anywhere are all named by part id and law before the deck is written.
`/MAT/LAW1` additionally makes the starter **force-reset** `Inpts` to 222 / 2 on
TYPE20 and TYPE21 (`sgrtails.F:694-704`, WARNING 791, TYPE22 exempt), so the
deck's `NIP` is reported as lost rather than silently discarded.

Which sections actually emit a property is gated three ways, each guarding a
starter refusal: a section **no `*PART` names** is skipped (it has no material
either, and an `ICOMP = 1` one would be a `/PROP/TYPE22` with `mat_IDi = 0` —
ERROR 676); a section **all** of whose `*PART`s carry shells or ordinary solids
is skipped and warned, because that element family auto-creates its own section
under the same id and two `/PROP` cards on one id is ERROR 79, while a section
of MIXED families keeps both — the thick-shell property moves to a synthesized
id and its parts are repointed; and an **element-free** `*PART` on a
`*SECTION_TSHELL` still gets its property, because the placeholder path treats a
defined thick-shell section as already resolved (ERROR 178 otherwise).

Warn-dropped: `PROPT` (a printout option), `TSHEAR` (constant vs parabolic
transverse shear — a real physics difference, and Radioss thick shells are
always parabolic; on `*PART_COMPOSITE_TSHELL` it sits in card 3b's eighth
column, where the thin-shell card 3a has `THSHEL`), a negative `QR` (an
`*INTEGRATION_SHELL` rule; thick shells take no user quadrature), and `SHRF` on
TYPE20/TYPE21, which have no transverse-shear column at all. On TYPE22 `SHRF`
**is** carried, to `Ashear` — dyna2rad drops it there too — and a value outside
`(0, 1]`, which `Ashear` cannot take, is named rather than dropped in silence.
So are: the `NIP > 9` clamp on BOTH formulations; a non-default `AOPT` on a
material whose Radioss law is `PROP_SOLID` class 1 and therefore lands on
`/PROP/TYPE20`, which has no reference-vector card (`*MAT_MODIFIED_HONEYCOMB` →
`/MAT/LAW50` is the case to watch); a THIN `*PART_COMPOSITE` on a thick-shell
mesh, a pairing LS-DYNA does not accept either; and the `ELFORM` losses of the
`*PART_COMPOSITE_TSHELL` card-3b route, which shares the section route's report.

Everything that walks the element tables sees thick shells: the orphan-element
census, the `/XREF` per-part node inventory, contact sides and `/SURF/PART`
(they are `/BRICK`, so a thick-shell part builds the same surface a brick part
does — without that the whole `/INTER` was dropped), `/RBODY` secondary nodes,
`/DAMP` (node-based Rayleigh damping, so it reaches them — the element-level
`/DAMP/FREQUENCY_RANGE` still cannot), `*INITIAL_VELOCITY_GENERATION`,
`*DATABASE_CROSS_SECTION_PLANE`, `--auto-gapmin`'s surface extraction, the
implicit no-contact stub — and, above all, the two guards that decide which
nodes carry stiffness: the implicit free-node `/BCS` (which otherwise clamped
the ENTIRE mesh in all six DOFs, 0 starter errors and a model that cannot move)
and the modal dummy `/CLOAD` (whose candidate set was otherwise empty, so a
modal thick-shell deck could not start at all).
`*DATABASE_HISTORY_TSHELL` rides `/TH/BRIC`, the same block
`*DATABASE_HISTORY_SOLID` takes.

### SPH particles

`*ELEMENT_SPH` → `/SPHCEL/<part_ID>`, `*SECTION_SPH` → `/PROP/SPH`
(= `/PROP/TYPE34`), `*CONTROL_SPH` `NMNEIGH` → `/SPHGLO`. The property sits
under the **SECID verbatim**, exactly where `/PROP/SOLID` would, so no `/PART`
repoint is needed unless the SECID is also claimed by another element family.

**An SPH particle has no connectivity: it IS its supporting node.** The
`/SPHCEL` id column is read as the NODE user id and the cell id is then forced
equal to it (`hm_read_sphcel.F:243-250`, "same identifier as the node"), so a
cell can never be renumbered independently of a node — which is why the
`*INCLUDE_TRANSFORM` offset spec gives field 0 the **node** bucket (`IDNOFF`),
the only `*ELEMENT_` card in this converter where that is true. dyna2rad cannot
follow: it emits a `//SUBMODEL` and lets Radioss apply the offsets, and the
`/SPHCEL` id column is a plain `INT` with no entity type, so the submodel
machinery leaves it alone while `/NODE` moves — measured, an
`*INCLUDE_TRANSFORM` with `IDNOFF = 1000` (with or without a matching `IDEOFF`)
gave four `ERROR 78 … NODE ID=1 DOES NOT EXIST` and `TOTAL MASS = 0`. k2rad
bakes the offsets into the deck text, so it is immune by construction.

#### Where the mass lives, and what it costs

Radioss can state a particle's mass in exactly two places, and they are mutually
exclusive because **the one that carries the mass also decides the smoothing
length**:

| where the mass is | particle mass | smoothing length `h` |
|---|---|---|
| `/SPHCEL` `Flag = 1`, `MASS = m` | `m` per particle, exact whatever the deck says | Radioss DERIVES `(√2·m/ρ)^(1/3)`; the property's `h` is **ignored** (`spinih.F:85-95`) |
| `/SPHCEL` `Flag = 2`, `MASS = V` | `ρ·V` | same, from `(√2·V)^(1/3)` |
| `/SPHCEL` MASS blank (`Flag = 0`) | `Mp` from `/PROP/SPH` | the property's `h`, verbatim |

k2rad picks the **second** route whenever the section's particles all carry the
identical mass and the deck states a usable `h` — then the total is
`N × Mp`, exact, *and* the deck's own smoothing length survives; and the first
route otherwise, which keeps the mass exact per particle and reports the
smoothing-length ratio it costs, in numbers:

> `Radioss will use h = (sqrt(2)*9.683426e-05/938)^(1/3) = 0.00526559 against
> the deck's 0.00565387 — a ratio of 0.9313, i.e. 6.87 % smaller support radius
> and 19.2 % fewer neighbours per particle.`

(the figures are the W11 bird-strike deck's own — 18 795 particles of
9.683426e-05 at ρ = 938, measured spacing 4.7116 mm — as they would read if its
masses were not uniform. They are, so that deck takes the exact route instead.)

When the masses genuinely differ the report gives the **span**, not one number:
`h` is derived per particle, so a single value from the mean mass is a value no
particle has, and on a two-population cloud its direction is wrong for half of
them. Measured on 500 particles at 8e-9 plus 500 at 1.6e-8, the mean-mass
reading said "7.07 % larger" while `spinih.F` gives 2.2449 for the light half
(6.5 % *smaller*) and 2.8284 for the heavy — and the starter's governing time
step matched the *smallest* `h`. So the message names the min, the max, and
which one sets the step (`mdtsph.F:132`).

Both mass columns are written with a formatter that **round-trips**. The
converter's shared float field renders anything below 1e-4 with `%.6E`, and in
Mg-mm-s every particle mass is below 1e-4: a deck stating `1.234567891E-09` on
1000 particles came back from the starter as `TOTAL MASS = 1.2345680000000E-06`
against the exact `1.234567891E-06`. Negligible in engineering terms, but mass
is this batch's correctness criterion and the field is twenty characters wide
with twelve used, so the digits were lost to the formatter rather than to the
column.

If **no** particle of a section states a mass or a volume, there is nothing to
read one from, and writing `Mp ≤ 0` hands the fabrication to the starter (which
invents 1.0 mass unit per particle behind a single `WARNING 138`). k2rad derives
one from the fill instead — `ρ · d_ref³`, the mass of the cube each particle
occupies — and reports it as `MASS INVENTED:`, stating the number now in the
deck and that the source stated none. The deck's own `h` still survives, because
a type-0 particle leaves the property's `h` alone.

The `h` the deck asks for is `SPHINI` when given, else `CSLH × d_ref` with
`d_ref` = "the maximum of the minimum distance between every particle" (Vol I
R16 Remark 1), measured here from the node cloud with a uniform-grid
nearest-neighbour search (exact on a lattice, a lower bound on a graded fill
above 20 000 particles per part, where the queries are subsampled). Radioss's
own `√2` is exactly the FCC packing factor, so its default support is
systematically *smaller* than LS-DYNA's — **0.9354× on a simple-cubic fill,
0.8333× on close packing** — which is why the choice is made rather than
defaulted. `Mp` is **always** written positive: dyna2rad never sets the field, so
`hm_read_prop34.F:235-239` raises `WARNING 138` on every deck it converts and
forces `Mp = 1` **in the deck's mass unit** — harmless while the cells carry
mass, and a fabricated whole mass unit per particle when they do not (measured:
four blank-mass particles gave `TOTAL MASS = 4.0`).

Three LS-DYNA conventions neither dyna2rad nor OpenRadioss's own native `.k`
reader implements, all measured through `starter_win64`:

* **`MASS < 0` is a VOLUME** ("the absolute value will be used as volume … SPH
  element mass is calculated by |MASS| × ρ") → `/SPHCEL` `Flag = 2`. Passed
  through signed, the starter discards it and the `Mp = 1` fallback takes over —
  `8.0 kg` where the deck states `0.016 kg`.
* **the `_VOLUME` suffix means the same thing with a positive number** → wrong by
  exactly ρ otherwise (`1.6E-05` instead of `1.6E-02`).
* **`NEND > 0` GENERATES the cards** from `NID` to `NEND` → `NUMSPH = 1` instead
  of a whole cloud otherwise. Generated ids with no `*NODE` are dropped with
  their own count (a `/SPHCEL` id with no node is `ERROR 78`).

A zero-mass cell is written `Flag = 0`, **never** `Flag = 1`: an explicit
`Flag = 1` with a blank MASS keeps `TYPE = 1` and `spinit3.F:142` computes
`VOL = 0/ρ` — measured `TOTAL MASS = 0.000000000000` with no diagnostic at all.

#### `/PROP/SPH` at `/BEGIN 2022`

Two data cards, never three. `hmin` / `hmax` / `hcst` are **radioss2026-only**
and a 2022 reader discards them **silently** while still accepting `h_1D = 3` on
card 1 — measured, `hmin=0.37 hmax=3.77 hcst=1.77` echoed back as the hard-coded
`0.2 / 2.0 / 1.2`, `0 ERROR(S)`, only advisory `WARNING 100213`, i.e. the
bounded-dilatation algorithm running with bounds nobody chose. dyna2rad emits
exactly that combination (and targets the attribute `"hcst"`, which does not
exist — the real name is `h_scal`). So `h_1D` here is `0` (3D dilatation) or
`2` (constant `h`), the latter only for LS-DYNA's own exact spelling of a
constant smoothing length, `HMIN = HMAX = 1.0`. `Order` stays `0`: dyna2rad maps
`SPHKERN == 2` onto it, but Radioss's `Order` is the *renormalisation correction*
order and `spcompl.F:107-118` dispatches on `-1/0/1` only, so an `Order = 2`
particle gets no kernel correction at all. `*HOURGLASS` / `*CONTROL_HOURGLASS`
never reach `h`: SPH has no hourglass modes, and dyna2rad's copy of `QM`/`QH`
into the field named `"h"` puts a dimensionless viscosity coefficient into a
LENGTH — measured, `QM = 0.13` with `SPHINI = 0.5` echoed
`SMOOTHING LENGTH = 0.13`, and a global `QH` **zeroed it outright**.

The material is gated at conversion time against the laws that declare SPH
compatibility (`INIT_MAT_KEYWORD(...,"SPH")`, `init_mat_keyword.F:272-273`);
anything else is starter `ERROR 3046`/`3047` and is named before the run.
dyna2rad imposes no law filter at all.

One material is re-routed rather than only reported. `*MAT_PLASTIC_KINEMATIC`
lands on `/MAT/LAW44` (COWPER), which `hm_read_mat44.F` does **not** declare for
SPH — so a particle on it is `ERROR 3046` and the whole deck is refused, as it
was for r14 `sph/bar-i/bar1.k` and `sph/bar-ii/bar2.k`, two decks LS-DYNA runs.
`/MAT/LAW2` (PLAS_JOHNS) **is** declared (`mat002/hm_read_mat02_jc.F90:383`) and
describes the identical curve — `a = SIGY`, `b = E·ETAN/(E−ETAN)`, `n = 1` is
the same bilinear plastic branch LAW44 is given — whenever the material carries
no Cowper-Symonds rate term (`SRC`/`SRP`) and no *effective* kinematic hardening
(`BETA < 1` matters only when `ETAN > 0`). When it does, the particle parts get
LAW2: under the material's own MID if nothing else uses it, otherwise under a
**cloned** `/MAT` id with only those parts repointed, because one Radioss `/MAT`
id cannot be two laws and the shells or solids sharing the material still need
LAW44. A material that is *not* expressible keeps LAW44 and keeps the loud
`ERROR 3046` report — a different constitutive law is never substituted
silently.

#### `*CONTROL_SPH`

Only `NMNEIGH` maps — to `/SPHGLO` `Lneigh` and `Nneigh` — and **only when it
asks for more than Radioss's own defaults** (120 computed / 240 stored). Writing
a smaller value would reduce those caps for nothing, and an all-blank `/SPHGLO`
is worse still: measured, it HALVES the stored cap from 240 to 120, so the card
is emitted with every field explicit or not at all. Every other column is
dropped by name — `NCBS`, `BOXID`, `DT`, `FORM`, `START`, `MAXV`, `CONT`,
`DERIV`, `INI`, `ISHOW`, `IEROD`, `ICONT`, `IAVIS`, `ISYMP`, `ITHK`, `ISTAB`,
`QL`, `SPHSORT`, `ISHIFT` — with `IDIM ≠ 3` singled out as the one whose loss
changes the ANSWER rather than the accuracy (**OpenRadioss SPH is 3D only**).
dyna2rad drops the whole keyword silently. Cards 2 and 3 are optional and are
claimed by RAW contiguity (the `#119` rule): an all-blank card 2 IS a card, and
"the next non-blank line" would read card 3 as card 2.

Everything that walks the element tables sees particles: the orphan-element
census, the `/PART` "is this part meshed?" test, contact SECONDARY node groups
(`SSTYP = 2/3` part scoping now works, not just the node-set spelling), `/RBODY`
secondary nodes, `*PART_INERTIA` node coverage, `/DAMP`,
`*INITIAL_VELOCITY_GENERATION` (the idiomatic way to launch a bird — the group
was otherwise EMPTY and the projectile did not move), `--auto-gapmin`'s node-side
clearance, the `*PART_CONTACT` `OPTT` "no effect" bucket (there is no `NUMSPH`
loop in `i7sti3.F` either) — and, above all, the two guards that decide which
nodes carry stiffness: the implicit free-node `/BCS` (which would otherwise clamp
every particle in all six DOFs, 0 starter errors and a cloud that cannot move)
and the modal dummy `/CLOAD`.

Four sites get a **named warning instead of an arm**, because a particle has no
face and no second node: a contact MAIN surface (`/SURF` over an SPH part builds
nothing — and with other parts in scope the interface converts *looking healthy*
while the particles are absent), `--auto-gapmin`'s surface faceting,
`*DATABASE_CROSS_SECTION_PLANE` (a `/SECT` has no SPH group at any version, so
its force UNDER-REPORTS by the whole SPH contribution) and
`*INITIAL_FOAM_REFERENCE_GEOMETRY` (`/XREF` is solid-only, `ERROR 2013`).

**Not converted, and named as such:** `*BOUNDARY_SPH_SYMMETRY_PLANE` /
`_FLOW` / `_NOFLOW` and `*SPH_SYMMETRY_PLANE` (Radioss target `/SPHBCS`),
`*DEFINE_SPH_*` injection / massflow / active-region (`/SPH/RESERVE`,
`/SPH/INOUT`), `*DEFINE_ADAPTIVE_SOLID_TO_SPH` (`/PROP/SOLID` `Nsphdir`), and
the anisotropic `_ELLIPSE` smoothing lengths, `DEATH` / `START`, `SPHKERN ≠ 0`
and any `HMIN`/`HMAX` pair other than `1/1`.

### Integrated beams

`*INTEGRATION_BEAM` → `/PROP/TYPE18` (`INT_BEAM`), a beam whose cross-section is
integrated cell by cell instead of condensed into `A/Iyy/Izz/Ixx`. The rule is
bound from `*SECTION_BEAM` **card-1 field 4** (`QR/IRID`, cols 31–40) when that
field is *negative* — the exact analogue of `*SECTION_SHELL`'s field 6, and the
same "the absolute value of the negative number refers to user defined
integration rule number" sentence covers both (Vol I R17 p.29-1). The field is a
**float**, so `-77` and `-77.0` both work, and on that branch the quadrature
scalar is **dead**: a reader that kept reading it would see `QR = 0` and stack
the 2-point rectangular rule on top of the user rule it was already given.

**This is net-new capability, not parity.** dyna2rad converts none of it: the
keyword is commented out of the R14.1 data hierarchy, so the native LS-DYNA
reader drops the card with no entity and no message (`displayMessage` is
compiled out), and the `*SECTION_BEAM` branch that would consume a rule is an
empty stub awaiting "RD-6730" (`convertprops.cxx:1343-1347`) — it emits a
`/PROP/TYPE18` with `ISFLAG`/`NITRS` never set, silently.

Card 1 is `IRID NIP RA ICST K`, and the two card blocks that follow are
**additive, not exclusive**: the reader takes the `D1 D2 D3 D4 SREF TREF D5 D6`
dimension card whenever `ICST > 0` **and** `NIP` `S T WF PID` cards whenever
`NIP ≠ 0`, exactly as the manual's two independent headings say. The HyperMesh
CFG gates the point list on `ICST == 0 && NIP > 0` and is wrong about it —
verified against LS-PrePost, where a rule that supplies one card too few
swallows the next rule's header and loses that rule entirely. Several rules may
stack under one header; there is no `_TITLE` variant.

**`ICST = 0` — the cell cloud.** `S` and `T` are *normalized* quadrature
coordinates in [−1, +1] and `WF` is the area *fraction* `A_i/A`, while Radioss
wants absolute local coordinates and an absolute area. The ±1 square is
`*SECTION_BEAM` card 2a's `TS1 × TT1` rectangle and the gross area is
`RA · TS1 · TT1` (`RA` = relative area, i.e. how much of that bounding box the
section actually fills), so

    Y_i = (S_i − NSLOC) · TS1/2    Z_i = (T_i − NTLOC) · TT1/2
    A_i = WF_i/ΣWF · RA·TS1·TT1

`NSLOC`/`NTLOC` (card 2a fields 5/6) give the "location of the reference
surface" — the beam's *node line* — inside that same ±1 square: `1.0` = the side
at `s = 1`, `0.0` = centre, `−1.0` = the side at `s = −1` (p.41-13/41-14).
Subtracting them re-expresses the cells relative to the nodes, which is the
frame `/PROP/TYPE18`'s `Yi/Zi` live in. This is how a beam hangs off a shell
surface, and ignoring it re-centres the whole section on the nodes.

The `ΣWF` normalization is the same one dyna2rad applies on the *shell* rule
(`convertprops.cxx:1991-1996`) and is a no-op on a well-formed deck; LS-DYNA
itself applies `WF` literally, so a deck whose weights do not add up to 1 is
told the scale factor that was applied. `TS1` and `TT1` are the s-direction and
t-direction thickness **at node 1** — not `TS1` and `TS2`, which are the
s-thickness at *both* nodes; dyna2rad's `L1←TS1, L2←TS2` map (`:1274-1275`)
reads a beam's taper as its depth. A real `TS2`/`TT2` taper is reported, since
`/PROP/TYPE18` is prismatic. `CST = 1` is *refused* rather than mis-read: it
redefines `TS1`/`TT1` as the outer and inner **diameter** (p.41-13), so
denormalizing the rule onto them would state an annulus as a solid box. The
point count is capped at 100 (`prop_p18_int_beam.cfg:90`, starter ERROR 977) and
a non-positive cell area is refused rather than emitted (ERROR 314).
`Iref = 1` with `Y0 = Z0 = 0` keeps the reference axis on the beam's node line,
where LS-DYNA puts it; `Iref = 0` would make the starter re-centre the section
on the area-weighted barycentre of the cells and shift every point by it
(`hm_read_prop18.F:267-279`), silently relocating the neutral axis of a
deliberately eccentric section.

**`ICST = 1..22` — the standard shapes.** LS-DYNA's 22 types line up 1:1 with
Radioss's own predefined sections at **`Isect = ICST + 9`** (starter
`defbeam_sect_new.F90`), and the per-shape dimension counts agree with
LS-DYNA's *own* `SECTION_nn` card-2b field counts on every row. `L1..Ln ←
D1..Dn`, and `K` becomes `NITRS` clamped to that shape's `intr_max` (exceeding
it is ERROR 3060). Only the shapes needing **at most two** dimensions are
emitted — ICST 8 (circular, `L1` = radius), 9 (tubular, outer/inner radius) and
11 (solid box). Everything else is reported and falls back, because the
`/PROP/TYPE18` card layout a `/BEGIN 2022` deck resolves to declares `L1` and
`L2` and nothing else (the CFG search runs *downward* from the requested
version, so `radioss2024`'s six-dimension form is invisible). Verified against
the real starter: the same `Isect = 10` deck earns `WARNING 100213` +
`ERROR 3059 MISSING DIMENSIONS FOR PREDEFINED SECTION` at `/BEGIN 2022` and
reads `L3`/`L4` cleanly at `/BEGIN 2026`.

**The material gate is checked before the property type is chosen**, not after.
`PROP_BEAM` is a per-law flag: LAW0/2/13/44 are `BEAM_ALL`, LAW34/36/71 are
`BEAM_INTEGRATED`, and **LAW1 (`/MAT/ELAST`) is `BEAM_CLASSIC` — TYPE3 only**
(`check_mat_elem_prop_compatibility.F:239-241`, ERROR 3047 followed by
ERROR 745). A beam part whose material converts to LAW1 therefore keeps
`/PROP/BEAM`, and the rule is condensed into the four section constants:

    Iyy = Σ(A_i²/12 + A_i·z_i²)    Izz = Σ(A_i²/12 + A_i·y_i²)    Ixx = Iyy + Izz

**`Iyy` is the `z`-based sum**, and the *engine* is what pins that, not the
starter's listing. `/PROP/BEAM` develops `MOM(2) = KYY·E·Iyy` (`m1lawp.F:108`)
while `/PROP/TYPE18` develops `MOM(2) = E·KYY·Σ(A_i·z_i²)` in the same slot
(`mulaw_ib.F:139` + `main_beam18.F:253`), so equating them gives
`Iyy = Σ(A_i·z_i²)`. The starter's *print* block labels these the other way
round (`hm_read_prop18.F:295`, `TIYY_I` accumulated from `RYI`) but never stores
`TIYY_I` anywhere — it is a listing bug, not the semantics, and two further
cross-checks agree with the engine: the ICST=11 closed form
(`Iyy = D1·D2³/12`, with `D1` along `y` per `defbeam_sect_new.F90` case(20)) and
`*SECTION_BEAM` ELFORM 2's `Iyy ← ISS`, LS-DYNA's "moment of inertia about the
local *s*-axis" = `∫t² dA` = `∫z² dA`. The `A_i²/12` self term models each cell
as a square patch, which is what the starter does and is exact only for square
cells; a rule states no cell *shape*, so nothing better is recoverable.
`Ixx = Iyy + Izz` is the polar moment. The standard shapes fall back through
their closed forms instead (ICST 8/9/11). The warning names the trade: the
stiffness survives, the through-section stress distribution and any plasticity
front do not — and, since the gate is per *section*, it names the parts dragged
along by a neighbour's material choice.

Rule support covers **ELFORM 0, 1, 4, 5 and 11**. dyna2rad reaches a rule-aware
path for 1 and 4 only and drops 5 and 11 with no message at all (no switch case
and no `default:`). `ELFORM 14` is reported separately and accurately: it is the
*elbow* element, and the one formulation that **mandates** a user rule (a
tubular one, ICST 9) — Radioss simply has no elbow to put it on. Every other
route is reported by name: a dangling `IRID`, a rule on an `ELFORM` that
integrates no cross-section, a section no beam uses, a spotweld-only section, a
missing `TS1`/`TT1`, a tubular `CST = 1`, a `TS2`/`TT2` taper, `RA = 0`
(substituted with 1.0 so the deck still runs, and said so), `ΣWF = 0`, a `ΣWF`
that is not 1 (renormalized, with the scale factor quoted), a per-cell `PID_i`
(`/PROP/TYPE18` has one material for the whole section), and `SREF`/`TREF`
(Radioss has no reference-axis offset column).

A `*SECTION_BEAM` that states its section as card-2 **thicknesses**
(ELFORM 0/1/4/5/11) and binds no rule no longer lands on an all-zero
`/PROP/BEAM`: that is not a soft beam but a *refused* deck
(`hm_read_prop03.F:151-182` raises ERROR 314/315/316/317 on each non-positive
value). The prismatic section is derived from `TS1`/`TT1` instead — a solid
`TS1 × TT1` rectangle, or the annulus `TS1`/`TT1` describe as outer/inner
diameter when `CST = 1` — and the substitution is reported.

Note when migrating an `ELFORM = 2` deck onto a rule: Radioss integrates
transverse shear over the **full** section area on `/PROP/TYPE18`
(`main_beam18.F:266-271`) where `/PROP/BEAM` applies the usual `5/6`
(`pmat3.F:74`), so an integrated beam is slightly more shear-flexible than the
resultant beam carrying the same `A/Iyy/Izz`. At `L/h = 12.5` that is ~0.3 %;
it grows for stubby beams.

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
`*DEFINE_TABLE_3D` → `/TABLE/1` (Ndim=3, flat): one row per (inner VALUE,
outer VALUE) pair — dim 1 = the leaf curves' own abscissa, dim 2 = the inner
`*DEFINE_TABLE`s' VALUEs (their own SFA/OFFA applied — dyna2rad's generic 3-D
path drops them), dim 3 = the outer card's VALUEs, ascending by (B, A). The
starter demands a COMPLETE rectangular secondary grid (a function for every
(A,B) pair — ERROR 3089, negative-control-measured), so a 3-D table whose
planes carry different inner grids is warned and not emitted flat (`*MAT_224`
LCK1 still slices its planes); `*DEFINE_TABLE_4D`+ have no `/TABLE` target
(Ndim caps at 4, no consumer) and stay skipped
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
included `*NODE` coordinates **and `*RIGIDWALL_*` wall geometry** (base + head
points, the `_FINITE`/`_FLAT`/`_PRISM` edge head, and a `_MOTION` card's
direction cosines under the linear part only — the starter's `SUBROTPOINT`
submodel replay). Wall *dimensions* (`LENL`/`LENM`/`LENP`, `RADCYL`, `RADSPH`)
are lengths: exact under translation/rotation/mirror, warned under scale.
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
`*CONSTRAINED_NODAL_RIGID_BODY` → `/RBODY` (id = the `/RBODY` main node id, as on
the `*MAT_RIGID` path; `NSID` blank = `PID`), in **all 326 option spellings** —
`_SPC`, `_INERTIA`, `_OVERRIDE`, `_THERMAL`, `_TITLE` in any order, generated
from one grammar, with the cards consumed in the fixed Card-Summary order. `_SPC` → an inline `/BCS` on the master node (see
**Boundary conditions**); `_INERTIA` carries the *same* card set as
`*PART_INERTIA` (Vol I Appendix X: "the same keyword data (except … CID2)") and
gets the same transfer — `Mass`, `Jxx..Jxz`, `ICoG = 4`, the main node at
`NODEID`/`XC,YC,ZC`, `CID2` → `Skew_ID` when `IRCS = 1`, and card 5 →
`/INIVEL/TRA` + `/INIVEL/ROT`. `PNODE` is not used as the main node on an
`_INERTIA` body (LS-DYNA relocates `PNODE` to the centre of mass itself, so it is
a readout node); `DRFLAG`/`RRFLAG` DOF releases, the `_OVERRIDE` card
(`ICNT`/`IBAG`/`IPSM`) and the `_THERMAL` card (`IDTHRM`) are warn-dropped
`*CONSTRAINED_INTERPOLATION` / `_LOCAL` → `/RBE3` (id = `ICID`, `I_modif = 2` so
Radioss may not modify the weights) plus one `/GRNOD/NODE` per set. `DNID` →
`Node_IDr`, `DDOF` → `Trarot_ref` (digit-set membership: `1356` means DOFs
1/3/5/6; blank = `123456`). The independent rows are **grouped on
(`IDOF`, weight, `CIDI`)** and each group becomes its own set with its own `WTi`,
`Trarot_Mi`, `skew_IDi` and node group — Radioss carries one scalar weight per
SET, so collapsing them would throw the per-node weights away. `ITYP = 1` resolves
each `INID` as a `*SET_NODE`; `_LOCAL` `CIDI` → the per-set `skew_IDi` (a card
paired with every independent row). `CIDD`, `IDNSW` and `FGM` are warn-dropped
(the 2022 `/RBE3` dependent card has no skew column, and `DDOF` is global
regardless); per-component `TWGHTY..RWGHTZ` are not representable and fall back
to `TWGHTX` with a warning. Guarded against the starter's own hard failures: a
`DNID` that is not a node (`ERROR 78`/`760`), a dependent node that is an
`/RBODY` main node (`ERROR 810` / `WARNING 3104`) or an `/RBODY` secondary, a node
in two sets with different weights (`ERROR 705`, de-duplicated first-row-wins), a
dangling `CIDI` (`ERROR 184`), and the dependent node appearing in its own
independent list. The `/RBE3` nodes are also excluded from the implicit free-node
`/BCS` guard, which would otherwise fight the constraint (`WARNING 3115`)

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
`*DATABASE_JNTFORC` → `/TH/SPRING` over the joint springs. Unlike the
`/TH/INTER` / `/TH/SECTIO` / `/TH/RWALL` force channels, these really are
instantaneous forces and moments: `thres.F:355-361` writes `GBUF%FOR` and
`GBUF%MOM` straight out, with no `dt` factor and no accumulator.

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
`*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL` → the same three cards driven in a
**co-rotating** `/SKEW/MOV`, built on three synthesized element-free nodes that
join the body's `/RBODY` secondary group so the triad turns with it
(`newskw.F` rebuilds it every cycle, `fixvel.F:390-417` projects the imposed
component onto the updated row). Its axes are **initialised to the global
axes**: LS-DYNA takes them from `LCO` on `*MAT_RIGID` / `CID` on
`*CONSTRAINED_NODAL_RIGID_BODY`, or from the body's *principal inertia*
directions when that is 0, and k2rad reads neither — so the conversion is exact
if the body's local system is global-aligned at t=0 and off by that constant
rotation otherwise (warned). The moving system goes in the **`skew_ID`** column,
never `frame_ID`: measured under `/BEGIN 2022` an `/IMPDISP` carrying `frame_ID`
echoes `FRAME 0` and silently falls back to the global axis. The Radioss
dyna-reader ignores `_LOCAL` entirely, freezing the axes at t=0
`*BOUNDARY_PRESCRIBED_MOTION_SET_BOX` → the `_SET` path scoped to
`nodes(NSID) ∩ nodes-inside(BOXID)` (`NSID=0` → the box alone, `BOXID=0` → the
plain set). Box membership is a **t=0 snapshot** — LS-DYNA re-tests it every
timestep — and `TOFFSET` (per-node curve time shift) and `LCBCHK` have no
equivalent; all three are warned
`VAD=3` (velocity-vs-displacement) and `VAD=4` (relative displacement) are
**refused**, not silently written as an `/IMPDISP`: all three `/IMP*` cards
evaluate their function against *time*
`|DOF| = 4`/`8` (translation along / rotation about a `*DEFINE_VECTOR`) now bind
that vector's `/SKEW` in the `skew_ID` column, so `Dir = X`/`XX` really means
"along V"/"about V"; the negative forms `-4`/`-8` additionally hold the two
transverse axes at zero. `|DOF| = 9/10/11` and `12` have no single skew axis and
are warn-skipped (the continuation card they carry is consumed, not misread as
another motion)
`*RIGIDWALL_PLANAR` (+`_ID`, `_FORCES`) → `/RWALL/PLANE` (fixed infinite plane;
`FRIC` 0 → sliding, exactly 1 → tied, 2/3 → the WVEL-gated weld (degraded +
warned), anything else positive → Coulomb friction; `NSID=0` tracks all
nodes via a search distance sized from the mesh bounding box;
`*DATABASE_RWFORC` → `/TH/RWALL`,
whose `FNX/Y/Z` + `FTX/Y/Z` are a time-accumulated **impulse** — `rgwal0.F:504-509`
sums the per-cycle nodal impulses, while the engine's `/DT12`-divided true wall
force goes only to `/ANIM` and the sensors (`rgwal0.F:496-500`), so rwforc
parity needs `d(FNX)/dt`)
`*RIGIDWALL_PLANAR_MOVING` (+`_FORCES`) → moving `/RWALL/PLANE`: a synthesized
free carrier node holds the wall `MASS` and `V0` along the wall normal —
exactly the starter reader's moving-wall semantics, no extra cards needed
`*RIGIDWALL_PLANAR_FINITE` (+`_MOVING`) → `/RWALL/PARAL` with the corner
points computed from `XHEV`/`LENL`/`LENM` (a zero length means semi-infinite
in LS-DYNA and falls back to the infinite plane with a warning);
`_ORTHO` (orthotropic friction) still warn-skips — no `/RWALL` equivalent
"The ordering of the options in the keyword name is unimportant" (p. 40-16), so
every ordering of `ORTHO`/`FINITE`/`MOVING`/`FORCES` is generated into the
dispatch table — all 65 spellings, not just the 13 canonical ones. A spelling
without a row would miss the exact-match lookup and, with no `RIGIDWALL_PLANAR`
prefix fallback, land in the generic skipped list: the wall silently gone, the
user told only that "a keyword" was skipped. The `*INCLUDE_TRANSFORM` offset
table is generated from the same source, so the two cannot drift apart.
(`_DISPLAY` is legal on this family and needs no extra card, but is **not** yet
registered — a known gap, not a silent one.)
The `_FORCES` option's extra card (`SOFT SSID N1 N2 N3 N4`, always the LAST of
the card set whatever order the options are spelled in — Manual p. 40-17 Card
Summary) is read rather than assumed absent. `N1..N4` are visualization nodes
and drop silently; `SOFT` (cycles over which the relative velocity is ramped to
zero, softening the initial force spike) and `SSID` (a `*SET_SEGMENT` splitting
the wall force for per-area rwforc output) have no `/RWALL` equivalent and are
warned when non-default. Consuming it is also what lets the multi-card-set
guard work on the planar family: LS-DYNA reads one card set per wall and keeps
going to the next keyword (p. 40-5), k2rad converts the **first** set only, and
extra sets are now caught with a warning instead of vanishing
`*RIGIDWALL_GEOMETRIC_CYLINDER` → `/RWALL/CYL`: `M` = tail, `M1` = head (only
`normalize(M1−M)` survives as the axis), `Phi = 2 × RADCYL` — the card field is
a **diameter** while LS-DYNA gives a radius (`hm_read_rwall_cyl.F:272` halves
it). `/RWALL/CYL` has no length field and is **axially infinite**, so a
`LENCYL > 0` cylinder is warned (the converted wall also blocks beyond both
ends); `NSEGS` sub-cards are per-segment force output with no counterpart and
are warned + skipped (their card count is honoured, so the `_MOTION` card is
still found)
`*RIGIDWALL_GEOMETRIC_SPHERE` → `/RWALL/SPHER` (`M` = centre = tail,
`Phi = 2 × RADSPH`; the card has no `XM1` line at all)
`*RIGIDWALL_GEOMETRIC_FLAT` → `/RWALL/PLANE` when `LENL` or `LENM` is zero
("a zero value defines an infinite size plane", Manual p. 40-9 — an exact
mapping; dyna2rad instead builds a 1e20 quadrant that misses half the model),
else `/RWALL/PARAL` with `M1 = T + LENL·l̂`, `M2 = T + LENM·m̂`,
`m̂ = n̂ × l̂` normalized. `l̂` comes from `HEV − T` (tail-relative, so the
classification is `*INCLUDE_TRANSFORM`-invariant); a degenerate `l̂` falls back
to the infinite plane + warning
`*RIGIDWALL_GEOMETRIC_PRISM` → **six** `/RWALL/PARAL` faces with outward
normals (Radioss has no box rigid wall; the five extra walls get fresh ids and
share the tracked group, friction and prescribed motion). `LENP = 0` (an
infinitely deep prism) emits the top face only + warning — dyna2rad emits four
walls with a zero edge vector, which the starter rejects with `ERROR 168`
`*RIGIDWALL_GEOMETRIC_*_MOTION` → the moving `/RWALL` form (synthesized carrier
node per face, `Mass`/`VX0..VZ0` = 0) driven by `/IMPVEL` (`OPT=0`) or
`/IMPDISP` (`OPT≠0`) on the LS-DYNA `LCID`, along the local X′ of a synthesized
`/SKEW/FIX` built from the `VX/VY/VZ` direction cosines. `/RWALL` has no
motion-curve field and the imposed motion wins over the wall reaction
(`resol.F` calls `FIXVEL` after `RGWALF`). `LCID = 0`, a missing curve or
all-zero direction cosines degrade to a FIXED wall + warning rather than to
dyna2rad's free-floating / silently-global-X wall
`*RIGIDWALL_GEOMETRIC_*_DISPLAY` — the `PID/RO/E/PR` card is a visualization
mesh with no solution effect (Manual p. 40-13): parsed away and warned.
`_INTERIOR` (`CYLINDER`/`SPHERE`) warn-**skips** — Radioss always pushes nodes
outward (`DP <= RA2`) and has no inversion flag, so converting it would invert
the physics. `_DEFORM` and any other spelling k2rad cannot parse warn-skip by
name (their extra cards would shift every card index after them), and several
card sets under one keyword convert the first only, loudly
`FRIC` maps by EXACT value, not by threshold ("FRIC could be any positive
value. Three special values ... trigger special treatments", Manual p. 40-20):
`0.0 → Slide 0`, exactly `1.0 → Slide 1` (tied), anything else positive
`→ Slide 2` + the coefficient. The geometric card has no weld values, so a
geometric `FRIC = 2.0` is a Coulomb `mu = 2.0`; on `*RIGIDWALL_PLANAR` the
WVEL-gated welds `2.0`/`3.0` degrade to Slide 0 / Slide 1 with a warning.
dyna2rad's geometric path turns a tied `FRIC = 1.0` into `mu = 1.0` instead
A wall with `NSID = 0` tracks ALL nodes, which `/RWALL` has no group id for:
`D_search` is set to the largest `DISN` the starter would measure over the mesh
bounding box (a bbox *diagonal* is not an upper bound — an impactor parked
further away than the mesh is wide would track nothing and be silently inert),
and synthesized moving-wall carrier nodes are excluded via `grnd_ID2`

### Loads
`*LOAD_RIGID_BODY` → `/CLOAD` on rigid body master node
`*LOAD_NODE_POINT/_SET` → `/CLOAD` (forces DOF 1-3, moments DOF 5-7; the CID
local system maps to the `/CLOAD` skew; follower loads 4/8 are warned)
`*LOAD_SEGMENT`, `*LOAD_SEGMENT_ID` → `/PLOAD`
`*LOAD_SEGMENT_SET` → `/PLOAD` (pressure on a `*SET_SEGMENT` surface). The
segment orientation carries the direction, so the scale passes through
**un-negated**
`*LOAD_SHELL_ELEMENT` / `_SET` → `/SURF/SEG` (the shell connectivity pasted
column-for-column) + `/PLOAD` with **`Fscale_y = -SF`**: LS-DYNA's positive
pressure acts along the shell's *negative* normal (Manual Vol I R16 p.3421,
"positive pressure acting in the negative t-direction") while a `/PLOAD` with
positive `Fscale_y` pushes along the *positive* segment normal
(`force.F90:451-465` sums `+P·A·n̂`) — so exactly **one** flip is right, and
reversing the node order as well would cancel it back out. A blank `SF` reads as
1.0. Each `_ELEMENT` row keeps its own `LCID`/`SF`/`AT` (the dyna-reader
collapses them onto row 0); `LCID = -1`/`-2` (Brode/ConWep) are refused, since
those are `/LOAD/PBLAST` sources
Arrival time `AT > 0` on `*LOAD_SHELL*` **or** `*LOAD_SEGMENT_SET` → a
`/SENSOR/TIME` with `Tdelay = AT` in the `/PLOAD` `sens_ID` column: the load is
zero for `t < AT` and the curve is then evaluated at `t − AT`
(`sensor_time.F:66-68` sets `TSTART = TDELAY`, `force.F90:216-218` evaluates at
`ts = tt − TSTART`) — a *shift*, warned, since a curve whose abscissa is already
absolute time must be pre-shifted instead
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
`*LOAD_BODY_VECTOR` → **one** `/GRAV` with `DIR = X` inside a companion
`/SKEW/FIX` whose local X′ is `+V`, and `Fscale_Y = -SF`. The two halves belong
together: `/GRAV` adds `+Fscale_Y·f(t)` along `DIR` (`gravit.F:147`), so the
applied acceleration is along **−V**, which is what LS-DYNA prescribes (p.33-29 —
the manual's own validation example writes `V = (−1,−1,−1)` to obtain gravity
along `+(1,1,1)`). Reproducing one half without the other flips the load. `|V|`
is irrelevant (both codes use `V` as a direction only); `CID` maps `V1/V2/V3`
from that system's basis to global; `XC/YC/ZC` become the skew origin (inert for
a uniform field); a zero `V` is refused (the dyna-reader turns it into a global
−X load)
`*LOAD_BODY_RX` / `_RY` / `_RZ` → `/LOAD/CENTRI` (+ a `/FRAME/FIX` for the
rotation axis). `LCID` carries the **angular velocity ω(t), linearly**: LS-DYNA
forms `b = ρ·[ω × (ω × r)]` internally (p.33-20 Remark 3) and the engine squares
the curve for itself (`cfield.F`: `VROT = Fscaley·f(t)`, then `VROT2 = VROT·VROT`,
`AREL = r⊥·VROT2`) — do **not** pre-square or square-root it. There is **no sign
flip** either: unlike the translational forms, both codes push radially outward.
`Dir` is emitted as **`XX`/`YY`/`ZZ`**, never `X`/`Y`/`Z` — the starter accepts
both but the engine only branches on `IDIR` 4/5, so 1/2/3 all rotate about the
*frame's Z axis*, silently (the dyna-reader writes `X`/`Y`/`Z` and is therefore
wrong for `RX` and `RY`). `Ivar = 1` omits the `dω/dt` Euler term, matching
LS-DYNA Remark 2. `XC/YC/ZC` become the frame origin, or the `CID` origin when
`CID` is set (`CID` supersedes the centre fields); with neither, `frame_ID = 0`
is the global axes through the global origin and no `/FRAME` card is emitted.
Each card gets its own frame id — the dyna-reader's `GetDynaMaxEntityID`-in-a-loop
gives two cards two `/FRAME`s with **one** id (`ERROR 79`)
`*LOAD_BODY_GENERALIZED` warn-skips: its per-part scaling is neither a uniform
`/GRAV` nor a single-axis `/LOAD/CENTRI` (split it into `*LOAD_GRAVITY_PART`
rows, which k2rad does convert)
`*LOAD_BODY_PARTS` → the `PSID` part set becomes the `/GRNOD/PART` scope of
every `*LOAD_BODY_*` in the deck — the `_X/_Y/_Z`, `_VECTOR` and `_R*` forms all
share that one group (one card per deck, last one wins)
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
`*LOAD_BLAST_ENHANCED`, `*LOAD_BLAST` (legacy) → `/LOAD/PBLAST`. The TM5-1300
formula is unit-dependent — `/LOAD/PBLAST` converts its internal `{g, cm, mus}`
data using the `/BEGIN` labels — so the card's `UNIT` flag sets those labels
when the caller states none. All five consistent systems of the manual's
eight-row table (Vol I R16/R17 p.33-17) are mapped:

| `UNIT` | LS-DYNA system | `/BEGIN` |
|---|---|---|
| 1 | pound-mass, foot, second, psi | *(none — imperial)* |
| 2 | kilogram, meter, second, Pascal | `kg m s` |
| 3 | dozen slugs, inch, second, psi | *(none — imperial)* |
| 4 | centimeters, grams, microseconds, Megabars | `g cm mus` |
| 5 | user conversions on Card 2 | *(none — unnamed)* |
| 6 | kilogram, millimeter, millisecond, GPa | `kg mm ms` |
| 7 | metric ton, millimeter, second, MPa | `Mg mm s` |
| 8 | gram, millimeter, millisecond, MPa | `g mm ms` |

Every triple is checked against the starter's own label grammar (see `--units`
above); `mus`, not `micros`, is the microsecond OpenRadioss accepts. `UNIT=1`
and `3` have no legal `*g`/`*m`/`*s` label at all, and `UNIT=5` states its units
only as the `CFM/CFL/CFT/CFP` factors, so those three get no automatic mapping —
state them with `--units`. The legacy `*LOAD_BLAST` card's `IUNIT` is documented
`1..5` only, so `6/7/8` are not applied there.
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
`*INITIAL_VELOCITY_NODE` → `/INIVEL/TRA` (+ `/INIVEL/ROT` for rotational DOFs),
grouped by identical 6-tuple velocity
`*INITIAL_VELOCITY_RIGID_BODY` → `/INIVEL/TRA` (+ `/INIVEL/ROT`) on the rigid
body's MASTER node only — its 6 DOFs drive the body, and Radioss overwrites the
secondary nodes from it anyway. (`TRA`/`ROT` are the only `/INIVEL` subtypes
k2rad emits here; `/INIVEL/NODE` and `/INIVEL/RBODY` are not used.)
A `*PART_INERTIA` / `*CONSTRAINED_NODAL_RIGID_BODY_INERTIA` card-5 `VTX..VRZ` on
the same body is superseded by this card and dropped with a warning (*PART
Remark 5), since `/INIVEL` assigns rather than accumulates
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
`*CONTACT_AIRBAG_SINGLE_SURFACE` (contact type a13, + `_MPP`) — a near-alias of
the single-surface path: its card grid is the two-sided grid with the B-side
cells blank, so `SSID`/`SSTYP`/`SFS`/`SST`/`SFST` land on the same field
indices. `SOFT = -19` routes to the airbag flavour of `/INTER/TYPE19`
(`Istf = 4`, `Idel = 2`, `Ibag = 1`, `Gapmin = |SST|/2·SFST`); anything else
falls back to the single-surface routing above. See *Airbags / monitored
volumes*
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
`*CONTACT_ERODING_{SINGLE_SURFACE,SURFACE_TO_SURFACE,NODES_TO_SURFACE}` (each
optionally `_MPP` / `_ID` / `_TITLE`) → `/INTER/TYPE25`, following dyna2rad's
routing (`convertcontacts.cxx:117-131` and the generic `NODES_TO_SURFACE`
branch at `:212-216`). The three side topologies map onto the starter's `ILEV`
classification (`hm_read_inter_type25.F:399-434`): SINGLE_SURFACE →
`surf_ID1` = the SSID surface with `surf_ID2=0` (ILEV=1, self-impact);
SURFACE_TO_SURFACE → both surfaces (ILEV=2, symmetric); NODES_TO_SURFACE →
`surf_ID1=0`, `grnd_IDs` = the SSID node group, `surf_ID2` = the MSID surface
(ILEV=3, genuinely **one-way**).
**The solid side is emitted as `/SURF/PART/ALL`, not `/SURF/PART/EXT`** — the
single thing that makes an eroding contact behave like one. The starter puts
every interior (two-solid) face in the segment list with a *negative* stiffness
(`i25sti3.F:950-951`) and the engine flips it active the moment one of its two
solids dies (`check_surface_state.F:174-203`), which is LS-DYNA's `IADJ=1` /
`EROSOP=1` behaviour exactly. With `/EXT` the machinery still arms
(`i25surfi.F:607-625` sets `IPARI(100)=1` on `Idel>0` alone) but has no interior
segment to wake, so the crater face a dying brick exposes carries no contact at
all — and **nothing in the solver output says so**. dyna2rad has precisely this
gap: it builds every contact surface from a bare `PART` clause with no `opt_A`
(`convertcontacts.cxx:264-274`). `--eroding-surf-ext` (CLI) / the GUI checkbox
falls back to `/EXT` (LS-DYNA SMP's literal `IADJ=0`); parts carrying
**quadratic** solids fall back on their own, because the 2022 Reference Guide
p.372 wants `/EXT` there so the mid-side nodes take part in the contact.
`Idel=2` (remove the main segment as soon as *one* attached element dies) rather
than dyna2rad's `1` — LS-DYNA's own per-element face removal, and already the
k2rad convention on every other penalty interface. Note the 2022 Reference Guide
p.372 states `/SURF/PART/ALL` "is not available with TYPE25"; the current
OpenRadioss starter implements it and has no check that rejects it, but an older
binary may not. A third, purely operational consequence: the segment list grows
roughly 5× for a solid block (a 16×16×6 brick mesh has 896 external faces but
5056 total), so **any per-segment starter diagnostic is multiplied by the same
factor**. On `W9_SETUP_MSLprojectile` — whose own unconverted
`*MAT_CSCM_CONCRETE` fires a `WARNING 96` per main segment on both branches —
the warning count goes 25 250 → 209 108 and the starter `.out` 7 MB → 46 MB.
That is amplification of a pre-existing deck defect, not a new error class (a
healthy deck fires none of them), but a large listing file on an eroding deck
is worth reading as "fix the underlying warning", not "the contact is broken".
The Card-4 fields `ISYM` / `EROSOP` / `IADJ` are all **reported**
(dyna2rad parses and discards all three with no message — including `EROSOP`,
whose entire purpose is to enable eroding contact), as are the `SST`/`MST`
thicknesses, which `/INTER/TYPE25` has no column for at `/BEGIN 2022`.
`*CONTACT_NODES_TO_SURFACE` and `*CONTACT_AUTOMATIC_NODES_TO_SURFACE` (+ `_MPP`)
→ the same `/INTER/TYPE25` ILEV=3 one-way form. dyna2rad does **not** symmetrize
this family (`surfAttrNames[0] = "grnd_IDs"`), so neither does k2rad: the
secondary nodes stay secondary and the main surface's own nodes are never
tracked against them. `SSTYP=4` (a `*SET_NODE_LIST`, LS-DYNA's own
recommendation for an eroding node-to-surface contact — Vol I p.11-65 remark 2)
resolves, as do the part (`3`) and part-set (`2`) forms. A **`*SET_SEGMENT`
side does not**: `SSTYP=0`/`1` fall back to looking the id up as a part, part
set or node set, so a real segment-set id resolves only by coincidence. The
main (`MSID`) side always needs a part or a part set. A side that resolves to
nothing drops the interface with a remedy naming what to point it at, rather
than converting a contact with no load path.
`*DEFINE_FRICTION` → `/FRICTION`, **id preserved 1:1** (which is what makes the
`fric_ID` binding work). LS-DYNA's
`μ = FD + (FS − FD)·exp(−DC·|v_rel|)` maps *exactly* onto Radioss `Ifric=2`
(Darmstad) with `Fric = FD`, `C5 = FS − FD`, `C6 = −DC` and `C1..C4 = 0` — the
engine evaluates `XMU = Fric + C5·e^(C6·v)` once the other terms vanish
(`i7for3.F:1911-1914`). That is dyna2rad's mapping and the only 2022-legal one:
Radioss's own exponential-decay law `Ifric=4` needs one fewer sign flip but does
not exist before `radioss2023`. The Card-1 defaults become the `/FRICTION`
header row (the engine seeds every contact pair from it,
`frictionparts_model.F:88-92`) and each Card-2 part pair becomes one pair block,
in deck order, un-expanded; a `PSET` row gets a `/GRPART/PART`. A contact binds
the table with **Card-2 `FS = −2`**, written to the `fric_ID` column at cols
91–100 of card 6 on `/INTER/TYPE7` and `/INTER/TYPE25`. One table in the deck →
it applies to every `FS=−2` contact; several → the `FD` column names the one to
use; none or no match → friction 0 with a warning (dyna2rad's message 200029).
An interface with `fric_ID` set ignores its own `Fric`/`Ifric` entirely (2022
Reference Guide p.268, remark 16). `/INTER/TYPE11`, `/INTER/TYPE19`,
`/INTER/TYPE2` and `/INTER/TYPE10` have **no `fric_ID` column** in their newest
`/BEGIN 2022` FORMAT, so an `FS=−2` on one of those gets a loud warning naming
the interface instead of a silent frictionless run.
Card-2 `FS = −1` ("use the `*PART_CONTACT` coefficients") is **not** written
through literally any more — that put a *negative* Coulomb coefficient on the
interface card. It becomes `Fric=0` with a warning naming the interface.
`FS = 2` (LS-DYNA reinterprets `FD` as a `*DEFINE_TABLE` id, μ(pressure,
velocity)) keeps its literal value and warns only when the deck really does
contain that table — OpenRadioss has no pressure-and-velocity friction table.
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
`*CONTACT_SPOTWELD` (+ `_WITH_TORSION`, `_BEAM_OFFSET`, `_CONSTRAINED_OFFSET`,
each optionally `_PENALTY` / `_MPP` / `_ID`) → `/INTER/TYPE2` with
`Ignore=2`, `Spotflag=28`, **`Idel2=1`** — dyna2rad's spotweld defaults
(`convertcontacts.cxx:49`). This is what attaches the weld elements to the
sheets they join: without it the `*MAT_SPOTWELD` nuggets reach the solver
joined to nothing but each other and the weld force stays 0.000 N. The
secondary (SSID) side is resolved over **beam** end nodes as well as shells and
solids — `SSTYP=3` on a spot-weld card names the *weld* part, which is beams —
for `SSTYP` 0 (segment set), 1 (shell set), 2 (part set), 3 (part), 4 (node
set); the main (MSID) side takes the same part / part-set / segment-set routes
as the tied contacts. `dsearch` comes from the card: `0.6*(SST+MST)` when both
Card-3 thicknesses are positive (dyna2rad drops them here but uses exactly that
formula for the sibling tied contacts, and it is the starter's own internal
term), a negative `SST`/`MST` as an absolute tie distance, otherwise 0 = the
starter's average-main-segment default. The `_WITH_TORSION` / `_BEAM_OFFSET` /
`_CONSTRAINED_OFFSET` flavours emit the same card and **warn** about the
dropped behaviour (dyna2rad parses the flag and never reads it)
`ignore=0/1/2` → `Inacti=5` (LS-DYNA neutralizes initial penetrations at
initialization for every ignore setting; `Inacti=0` would apply the full
penalty force to resting-contact nodes at cycle 0). Exception: an implicit
deck with an SST/MST-derived `Gapmin` keeps `Inacti=0` (the documented
pre-engagement bootstrap needs the t=0 stiffness path). `Inacti=5` can only
*shrink* the gap, never create clearance, so two parts drawn **exactly
coincident** still hit starter **ERROR 611** (`INITIAL PENETRATION = ...
IMPOSSIBLE TO CALCULATE NEW COORDINATES OF SECONDARY NODE`) — the penetration
equals the whole element-derived gap and there is nowhere to shift the node to.
Met in practice on a friction rig whose slab touched its plate: 264 × ERROR 611,
cleared by a 0.01 mm modelling clearance
A contact **master surface** built from a part that carries 3-corner shells
splits by topology: quads → `/GRSHEL/SHEL` + `/SURF/GRSHEL`, triangles →
`/GRSH3N/SH3N` + `/SURF/GRSH3N`, solids → `/SURF/PART/EXT` (or
`/SURF/PART/ALL` on an `*CONTACT_ERODING_*`, see above), combined under a
`/SURF/SURF` when more than one kind is present. A `/SH3N` id inside a
`/GRSHEL/SHEL` is starter **ERROR 70** (`ELEMENT ID=n DOES NOT EXIST`), which
rejects the whole deck

### Airbags / monitored volumes

| LS-DYNA | OpenRadioss | note |
|---|---|---|
| `*AIRBAG_SIMPLE_PRESSURE_VOLUME` | `/MONVOL/PRES` (ITYPE 2) | `Itypfun = 0`, `Fscale = BETA·CN` on a unit-slope `/FUNCT` |
| `*AIRBAG_SIMPLE_AIRBAG_MODEL` | `/MONVOL/AIRBAG1` (ITYPE 7) + `/MAT/GAS/CSTA\|MASS` + `/PROP/INJECT1` [+ one vent hole] | |
| `*AIRBAG_ADIABATIC_GAS_MODEL` | `/MONVOL/GAS` (ITYPE 3) | `Pini = P0 + PE` (gauge → absolute) |
| `*AIRBAG_LOAD_CURVE` | `/MONVOL/PRES` | `Itypfun = 1` (pressure vs time), `STIME` folded into the curve |
| `*AIRBAG_LINEAR_FLUID` | `/MONVOL/LFLUID` (ITYPE 10) | `P = K·ln(V0/V) + Padd`, term for term |
| `*AIRBAG_REFERENCE_GEOMETRY[_ID][_BIRTH][_RDT]` | one `/XREF` per owning part | `_ID` scaling baked in, `_BIRTH` → `/SENSOR/TIME` |
| `*AIRBAG_SHELL_REFERENCE_GEOMETRY[_ID][_RDT]` | `/EREF/SHELL` + `/EREF/SH3N` per part | |
| `*MAT_FABRIC` / `*MAT_034` | `/MAT/LAW19` + `/PROP/TYPE9`, or `/MAT/LAW58` + `/PROP/TYPE16` | see *Fabric* below |
| `*CONTACT_AIRBAG_SINGLE_SURFACE` | the single-surface interface, or `/INTER/TYPE19` on `SOFT = -19` | |
| `*DATABASE_ABSTAT` | one `/TH/MONV` per monitored-volume model | its `DT` joins the `/TFILE` minimum |

`*AIRBAG_WANG_NEFSKE*`, `*AIRBAG_HYBRID*`, `*AIRBAG_PARTICLE`, `*AIRBAG_ALE`,
`*AIRBAG_ADVANCED_ALE`, `*AIRBAG_FLUID_AND_GAS` and `*AIRBAG_INTERACTION` are
**registered but not converted**: each one warns by name and says what the
Radioss counterpart would be. That matters more than it looks — an airbag that
disappears is not a missing output card, it is a bag that never inflates, on a
run that terminates *normally*.

#### The external surface must be element-backed

`/SURF/SEG` is a **hard failure** for a monitored volume, not a degradation.
`check_surf.F:55-62` sets `IGRSURF%ISH4N3N` only for `ELTYP` 3 (4-node shell)
and 7 (SH3N), a segment surface is never resolved back to an element at all
(`tsurftag.F:293` passes `0, 0`), and every `hm_read_monvol_type*.F` then
answers

```
ERROR ID :     18   -- SURFACE ID: 1000 IS NOT DEFINED WITH SHELLS
ERROR ID :     54   ** ERROR IN INPUT FORMAT
```

and aborts (starter exit 172, measured). LS-DYNA's `SIDTYP` is inverted
relative to intuition — **0 = `*SET_SEGMENT`**, non-zero = `*SET_PART` — so the
segment-set case is the common one. k2rad resolves those segments back to the
shells that own them (by corner-node **set**, since the segment's start corner
and winding are free variables) and builds the surface as `/SURF/GRSHEL`, plus
a `/SURF/GRSH3N` under a `/SURF/SURF` where the bag has triangles. A part in
the scope that carries no shells is named and left out rather than emitted.

When the named set family has no set with that id but the other one does, the
deck's `SIDTYP` is simply wrong and the other family is used, with a warning —
the r14 example `introduction/intro-by-a.-tabiei/misc/airbag-i/volume.k`
writes `SIDTYP=0` and then defines a `*SET_PART_LIST 11` and a
`*SET_NODE_LIST 11` and no segment set at all.

#### Orientation and closure are the starter's job — k2rad measures them

Every MONVOL reader runs the same four calls in the same order:

```fortran
CALL MONVOL_CHECK_SURFCLOSE(...)      ! free edges, then triangulate the holes
CALL MONVOL_ORIENT_SURF(..., ITYPE)   ! all normals onto the same side
CALL MONVOL_COMPUTE_VOLUME(...)
CALL MONVOL_REVERSE_NORMALS(..., VOL) ! IF (VOL < ZERO) flip everything
```

so an inward-wound bag is corrected automatically and a converter-side flip
would be a *second* correction of an already-correct surface. The connectivity
is therefore passed through untouched, and what k2rad does instead is measure
and report, with the engine's own expression
(`get_volume_area.F90:156-169`, `V = Σ ⅓ (N·c)` with `N = ½ (x13 × x24)`):

* the **signed volume** — negative means inward-wound, which the starter fixes;
* the **free-edge count** — the bag is open there, and the starter attempts an
  automatic closure and reports `WARNING 1875` only if it cannot;
* the **non-manifold edge count** — a T-connection, on which
  `MONVOL_ORIENT_SURF` gives up (`WARNING 1882`) and `MONVOL_REVERSE_NORMALS`
  then returns immediately, so the normals stay as written.

Measured on the r14 corpus: `airbag.deploy.k` 2432 segments, volume 754757,
wound **inward**; `volume.k` 1538 segments, 1.17e7; both `tire-compression.k`
decks 1296 segments, 6.887e7 with **144 free edges** (the bead ring, open by
design). A near-zero volume is warned about separately: it means the segment
normals *cancel*, i.e. the winding is mixed and there is nothing consistent
for the starter to flip.

#### The slots that are silently catastrophic

* **`/PROP/INJECT1 Iflow = 1`.** LS-DYNA's `LCID` is a mass **flow rate**
  ("Load curve ID specifying input mass flow rate", Vol I R16 p.3-13);
  `airbaga1.F:349-362` branches on `IFLU = IGEO(24)` and with `Iflow = 0`
  *differences* the curve (`DGMASS = GMASS − GMASS_OLD`) instead of integrating
  it. No starter diagnostic, an error of order `1/Δt`. `Ascale_T` is written as
  an explicit `1.0`: it *divides* the time abscissa while the `IFLU == 1`
  integration multiplies by `DT1` without dividing, so the two disagree for any
  other value.
* **`/MAT/GAS` carries a mass-specific `Cp` polynomial and Radioss derives
  `Cv = Cp − R/MW`.** `CV ≠ 0` → `/MAT/GAS/CSTA` with `Cp | Cv` verbatim (both
  are mass-specific on the LS-DYNA card too); `CV = 0` → `/MAT/GAS/MASS` with
  `Cpa = A/MW`, `Cpb = B/MW`, because card 4a's `A`/`B` are **molar**
  (Vol I p.3-16 Remark 3). Writing LS-DYNA's `CV` into a `Cp` slot inverts the
  gas.
* **`/MONVOL/GAS Pini = P0 + PE`.** LS-DYNA's `P0` is a **gauge** pressure
  (`e₀ = (p₀ + pₑ)/(ρ(γ−1))`, Vol I p.3-18) while Radioss feeds `Pini` straight
  into `EI = PINI·(V+VEPS−VINC)/(GAMMA−1)` and applies `DP = Q + PRES − PEXT`.
* **`/MONVOL/LFLUID` `P_LIMIT` goes through a flat `/FUNCT`.**
  `hm_read_monvol_type10.F` overwrites `Fscale_Pmax` with `INFINITY` whenever
  no function is given — probe: `5.5E+06` echoed as
  `MAXIMUM PRESSURE TIME FUNCTION SCALE FACTOR = 1.0000000200409E+20`.
  (`Fscale_Padd` with `fct_Padd = 0` **is** honoured, which is why a scalar
  `BULK` rides its own scale factor and `P_LIMIT` cannot.)
* **The vent's `fct_IDP` is a function of the GAUGE pressure `P − Pext`.** A
  negative `MU` or `AREA` is a curve of that quantity vs **absolute** pressure
  in LS-DYNA, so it is re-emitted with every abscissa shifted by `−PE`. This is
  the most unit-sensitive number in the batch.

#### The scaling contract, and what it costs

Vol I R16 p.3-4, verbatim: `V_cvolume = (VSCA × V_femodel) − VINI` and
`P_femodel = PSCA × P_cvolume`. So `VSCA`/`PSCA` are a **unit bridge** and
`VINI` is subtracted *after* the volume scale — it is the Radioss `Vinc`
(incompressible volume) in model units, `VINI/VSCA`, and only `/MONVOL/GAS` has
that column. `PSCA` folds into the `/MONVOL/PRES` `Fscale`; everything else is
warned about and dropped. On a `PRES` bag `VSCA` cancels out of the `V0/V`
ratio exactly, so it only loses something when `VINI` is also non-zero.
`RBID` (a user subroutine or a built-in sensor arming the inflator), `MWD` and
`SPSF` have no `/MONVOL` counterpart and are each named.

#### Fabric

The law and its property are **one decision**, because the starter enforces the
pairing through the material's declared shell class:

| `*MAT_FABRIC` | Radioss law | class | the only property it may sit on |
|---|---|---|---|
| `FORM ∈ {4, 14, −14, 24}` **with** a card-7 curve | `/MAT/LAW58` (FABR_A) | `SHELL_ANISOTROPIC`, `PROP_SHELL 4` | `/PROP/TYPE16` (SH_FABR) |
| everything else | `/MAT/LAW19` (FABRI) | `SHELL_ORTHOTROPIC`, `PROP_SHELL 2` | `/PROP/TYPE9` (SH_ORTH) |

Crossing them — or leaving the fabric on the isotropic `/PROP/SHELL` its
`*SECTION_SHELL` would give it — is starter **ERROR 3047** and refuses the whole
deck (`check_mat_elem_prop_compatibility.F:174-197`). Fabric parts are
therefore repointed at a synthesized per-part property, and a `*SECTION_SHELL`
shared with a non-fabric part keeps its own `/PROP/SHELL` for the others.

Every `FORM` whose specialisation has no faithful target — 1, 2, 3, 8, 12, 13,
24, and the `−14` card-8 block (the biaxial `LCAA`/`LCBB` pair, the hysteresis
`H`, the coat layer) — converts to the closest of the two laws with the
refinement **named** as dropped. So do the liner (`EL`/`PRL`/`LRATIO`), the
porosity family (`FLC`/`FAC`/`FVOPT`/`X0`/`X1`/`A0REF`) and `ELA`/`LNRC`.

Fabric-specific property settings, and why each is not a default:

* `Ismstr = 4` (full geometric non-linearity) — a membrane that deploys from a
  folded state would otherwise carry the fold as stiffness;
* `Ish3n = 2` so a bag meshed with triangles behaves like the quads beside it;
* `Ip = 2` (reference direction from each element's own first two nodes) — on a
  **closed** bag any single global `Vx/Vy/Vz` is nearly normal to some shell,
  and that is `ERROR 197` raised **once per element**. An explicit `AOPT` 2 or 3
  vector is honoured instead where the deck states one (AOPT 3 adds the 90°
  offset, since LS-DYNA measures `BETA` from `v × n`);
* `Istrain = 1` — `cinit3.F:529` gates the reference-state initial-strain pass
  on it, so an emitted `/XREF` on an `Istrain = 0` fabric part would be read,
  echoed and then do nothing;
* `Dm` carries the card's own `DAMP` (Radioss has no damping field on the law);
* `N` is collapsed to 1 only for the pure **membrane** `ELFORM = 9`; 2/5/16 are
  ordinary shells whose `NIP` is real.

Two column traps, both verified with a starter twin probe at `/BEGIN`
2022 / 2024 / 2026:

* `/MAT/LAW19` card 4 columns 21-40 are a **dead slot** the reader never touches
  (a written `9.99` is echoed nowhere) — `ZEROSTRESS` is at 41-60;
* `/PROP/TYPE9` card 4 columns **81-90** hold nothing at 2022 and become `Ipos`
  from 2024, silently and with no `WARNING 100211` either way, so k2rad leaves
  them blank. `Ip` is at 91-100 at every version. (`/PROP/TYPE16` *does* have a
  real `Ipos` cell at 2022, at columns 71-80.)

#### Reference geometry

`*AIRBAG_REFERENCE_GEOMETRY` feeds the same per-part `/XREF` that
`*INITIAL_FOAM_REFERENCE_GEOMETRY` does. A **shell** part needs no law check —
`hm_read_xref.F`'s MTN whitelist is gated on `ITYP == 2`, i.e. solid parts only
— and `cepsini.F`'s `CMLAWI` dispatch covers `ILAW` 1, 19 and 58, so both
fabric laws honour a reference state. The `_ID` card's `SX/SY/SZ` about `NIDO`
is applied at conversion time (Radioss has no scale or origin column) about
`NIDO`'s own **reference** position. `_BIRTH` becomes a `/SENSOR/TIME` on the
fabric law's `SENS_ID`, with `*MAT_FABRIC`'s own `RGBRTH` winning where both
are stated. `_RDT` has no counterpart and is named.

`*AIRBAG_SHELL_REFERENCE_GEOMETRY` becomes `/EREF/SHELL` + `/EREF/SH3N`, one of
each per owning part; the LS-DYNA `PID` column is read and discarded, because
Radioss takes the part from the header. The rows are screened three ways: an
element not in the emitted mesh is `ERROR 1011`, a ghost node in no `/NODE`
cannot carry coordinates, and **a node in both an `/EREF` and a `/XREF` is
`ERROR 1098`**. Since the two LS-DYNA cards are written *together* — the node
card gives the coordinates, the shell card names the elements — the `/XREF`
wins for a part covered by both and the `/EREF` rows are dropped, named.

#### `*DATABASE_ABSTAT`

One `/TH/MONV` **per monitored-volume model**, not one for all of them. The
whole 19-name vocabulary is legal on every type (a probe took all sixteen
non-vent names on a `PRES` bag without complaint), but the engine only fills
the `FSAV` slots its own pressure law computes — `volpfv.F` sets `FSAV(1) = 0`
on a `PRES` bag — so a union would write flat zeros that read as data:

| model | variables |
|---|---|
| `PRES` | `VOL P A` |
| `GAS` | `MASS VOL P A T GAMA` |
| `AIRBAG1` | `MASS VOL P A T CP CV GAMA MASS-IN ENTHA-IN ENER-INT WORK DTBAG` (+ `AO UO AC UC` when the bag has a vent) |
| `LFLUID` | `MASS VOL P A MASS-IN` |

The per-vent-hole channels (`AOUT1`…`HOUT10`) are **not** requestable here —
probe: `ERROR ID : 260 … TH VARIABLE AOUT1 IS NOT AVAILABLE`. They live in a
second group the starter auto-generates after every `/TH/MONV`
(`hm_read_thgrou.F:2745-2762`, titled `"VENT " // <title>`), so the converter
neither needs nor may emit one.


### Damping
`*DAMPING_GLOBAL` → `/DAMP` `Alpha` (mass-proportional Rayleigh; `VALDMP` is
carried verbatim, both sides apply `F = -α·m·v`). `LCID` is not converted —
plain `/DAMP` has no function slot, so a time-varying curve is warned about and
the constant `VALDMP` used. The per-DOF scale factors `STX..SRZ` are warned
about and dropped
`*DAMPING_PART_STIFFNESS` → `/DAMP` `Beta`. LS-DYNA derives `β_part = 2·COEF/ω_max`
from each part's own highest frequency, which is not knowable at conversion
time, so `COEF` is passed straight through and the largest value across the
listed parts becomes one global `β` — both facts are warned about. Note the
engine caps `β` at the current time step (`MIN(DAMP_B, DAMPT)` in `damping.F`)
All three `/DAMP` cards damp **thick shells** as well as shells and solids:
`/DAMP` is node-based Rayleigh damping over a `/GRNOD`, with no element-type
restriction. (The frequency-range card below is the opposite case.)
`*DAMPING_PART_MASS` / `_SET` → a part-scoped `/DAMP` `Alpha` per card, with
`Alpha = SF · curve`. Unlike `*DAMPING_GLOBAL` this card has **no
constant-value column** — the damping constant is read entirely off `LCID` — so
`LCID=0` is a dropped card, and a *time-varying* curve is reduced to its first
ordinate with a warning (exact for the flat curves these decks normally carry).
`FLAG=1` maps `STX..SRZ` onto the `/DAMP` Format-2 per-DOF rows
(`α_i = SF·curve·ST_i`); `FLAG=1` with all six left at 0.0 is read as "uniform"
rather than as "no damping". LS-DYNA forbids combining this card with
`*DAMPING_GLOBAL`, and Radioss would apply both additively, so a deck holding
both is warned. **dyna2rad does not convert this keyword at all** — k2rad's
mapping is a deliberate super-set
`*DAMPING_FREQUENCY_RANGE` / `_DEFORM` → `/DAMP/FREQUENCY_RANGE`
(`CDAMP`→`Cdamp`, `FLOW`→`Freq_low`, `FHIGH`→`Freq_high`, `PSID`→`grpart_ID`).
`0 < FLOW < FHIGH` is enforced by the converter because the starter enforces
neither: with `FLOW=0` its three-Maxwell fit collocates at
`sqrt(FLOW·FHIGH) = 0`, the 3×3 system is singular and NaN damping parameters
propagate silently into every element of the group.
This is a **radioss2025 keyword and k2rad writes `/BEGIN 2022`**, so the starter
draws `WARNING 100211 Unsupported option /DAMP/FREQUENCY_RANGE in format < 2025`.
Measured on `starter_win64`: that warning is advisory — every field reads
correctly and the echo is identical under `/BEGIN` 2022 and 2025 — so the card
is emitted and the warning restated. Bumping `/BEGIN` to 2025 by hand silences
it, at the cost of `WARNING 100217 "card is missing"` on the other cards k2rad
writes in the 2022 layout (measured harmless: 0 errors, every field still reads
back identically) — the warning says so.
`PSID=0` means "all parts **except** those claimed by other
`*DAMPING_FREQUENCY_RANGE` cards", which is the *opposite* of Radioss
`grpart_ID=0` (that grabs every part and silently re-tags the ones an earlier
card took). k2rad therefore emits `grpart_ID=0` only when nothing else claims a
part, and an explicit complement `/GRPART/PART` otherwise
The single Radioss card **is** LS-DYNA's `_DEFORM` behaviour: damping is applied
as a Maxwell/Prony viscous stress inside the material law, not as a nodal force.
So `_DEFORM` is a clean 1:1 *on the elements Radioss can reach*, and the blank
option is an approximation that gets a loud warning — rigid-body motion is not
damped and natural frequencies shift *up* instead of down. The element scope is
narrower on both options — and unlike plain `/DAMP` this one really cannot
reach a thick shell, because it enters inside the shell/solid material law
rather than at the nodes: Radioss damps only shells and solids, while LS-DYNA
also damps beams, thick shells and discrete elements (Vol I R16 Remark 4), so
any part in the damped scope carrying none of the former is named as
**completely undamped**. `PIDREL`, `IFLG`, `ICARD2`/`CDAMPV`/`IPWP`
have no Radioss counterpart and are warned and dropped; the `_DEFORM_DMIG`
superelement variant is dropped whole. `Tstart`/`Tstop` are written as the
neutral 0 / 1e30 because they are inert for this damping type — the starter
stores and echoes them, and nothing applies them
`*DAMPING_RELATIVE` → `/DAMP/VREL`: **resolved and reported, not emitted.** The
mapping is exact (LS-DYNA's `D = 4π·CDAMP·FREQ` is byte-for-byte Radioss's
`damp_a = Alpha_x·4π·Freq`), but `/DAMP/VREL` needs the **radioss2024** card
format. Measured on `starter_win64` with `/BEGIN` 2022-vs-2025 twins: at 2022
the reader falls back to the reduced radioss2023 layout, swallows the
`Freq RbodyID FuncID Xscale` card as if it were the `Alpha_y` row, and leaves
`Freq` at 0 — which switches the engine to its `α = Cdamp/dt_initial` branch,
roughly twelve orders of magnitude off. Emitting a card that reads as something
else is worse than emitting none, so k2rad resolves everything and puts the
finished card in a warning: `Alpha_*`, `Alpha2_x` (from `DV2`), `Freq`,
`RbodyID` (from `PIDRB`, looked up against the emitted `/RBODY`), `FuncID`
(from `LCID`, resolved through the `*DEFINE_CURVE` → `/FUNCT` table) and the
`grnod` scope — ready to paste into a deck whose `/BEGIN` says 2024 or later.
Three traps are called out in that warning: `Alpha_*` must be **1.0** when a
curve is given (LS-DYNA's `LCID` *replaces* `CDAMP`, Radioss's `FuncID`
*multiplies* `Alpha_x`, so copying both double-counts); `Alpha2_*` is ignored
unless `RbodyID ≠ 0`; and `Xscale` is dead in the shipped engine, so abscissa
scaling has to be baked into the curve's own X values
Several `/DAMP*` cards covering the same node compound their α terms but share
one per-node history buffer, which corrupts the `β` term of whichever is read
first, so overlapping scopes are warned about. A part named by two
`/DAMP/FREQUENCY_RANGE` cards is resolved by plain overwrite in the starter —
last one wins, silently — and is warned about too

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
`*DATABASE_SECFORC` → `/TH/SECTIO` on every section. **The `FNX/Y/Z`,
`FTX/Y/Z` and `M1/M2/M3` channels are time-accumulated impulses and angular
impulses, not the instantaneous section resultants secforc reports** —
`section_c.F:459-467` (shells) and `section_s.F:565-572` (solids) accumulate
`DT12*FST`, and the same never-reset `FSAV` story as `/TH/INTER` applies. Use
`d(FNX)/dt`
`*DATABASE_HISTORY_SHELL` → `/TH/SHEL`, and `/TH/SH3N` for any named element
the mesh writer emitted as a 3-node `/SH3N` (`/TH/SHEL` records only 4-node
shells, so a triangle listed there is absent from the T01). The split reads the
writer's own two registries back rather than re-deciding the topology, so the
group and the element block cannot drift;
`*DATABASE_HISTORY_SOLID` and `*DATABASE_HISTORY_TSHELL` → `/TH/BRIC` (a thick
shell IS a `/BRICK` in the emitted deck); `*DATABASE_HISTORY_SPH` and
`*DATABASE_HISTORY_SPH_SET` → `/TH/SPHCEL` (the `_SET` form's ids are
`*SET_NODE` ids, not particle ids, and are expanded first).
**EVERY family is screened against the entities the conversion actually
emitted** — nodes against `state.nodes`, SPH against `state.sph_cell_ids`,
beams against `beam_elem_ids ∪ spring_elem_ids`, discretes against
`spring_elem_ids`, shells against `shell_elem_ids ∪ sh3n_elem_ids`, solids and
thick shells against `solid_elem_ids`. Each of those registries is filled **at
the line that writes the element row**, never derived from the parsed
container, because the two differ: an `*ELEMENT_SHELL` whose PID has no `*PART`
record is parsed and warned about ("MESH LOSS") and then never written. A `/TH`
group naming an element the deck does not define is starter `ERROR 69` and the
whole run is refused — measured: a two-shell deck with one such element gave
`ERROR ID : 69 ... TH ELEMENT SELECTION ID=999 DOES NOT EXIST` twice. So a
dangling id is dropped with a named warning, and a group that screens to
nothing is not written at all. Note that an entity-less group is **not** an
error: `hm_read_thgrne.F:123` raises `ERROR 1109` only for `NVAR == 0` (no
VARIABLE), and a group with a title, a var line and no id card is accepted,
runs, and writes a T01 group holding zero entities — a silent channel loss,
which is why the guard exists;
`*DATABASE_HISTORY_NODE` → `/TH/NODE`
**The variable line is PER FAMILY, dyna2rad's `outVars` verbatim**
(`converttimehistory.cxx:238-296`): `/TH/NODE` asks for `DEF A AR VR`,
`/TH/SHEL` / `/TH/SH3N` / `/TH/BRIC` for `DEF STRAIN`, and `/TH/BEAM`,
`/TH/SPRING` and `/TH/SPHCEL` for `DEF` alone. `DEF` on a node is only six
channels — `DX DY DZ VX VY VZ` (`hm_read_thgrou.F` `IVARNG` row 1) — so
without `A`/`AR`/`VR` a `*DATABASE_HISTORY_NODE` drops the nine acceleration
and rotation channels LS-DYNA's own `nodout` carries, and an element group
without `STRAIN` drops the strain tensor. Measured against the plain-`DEF`
baseline on one run: `/TH/NODE` 6 → 15 channels, `/TH/SHEL` 11 → 19,
`/TH/BRIC` 11 → 17, starter `0 ERROR(S)`, every added channel carrying real
time-varying data
`*DATABASE_HISTORY_BEAM[_SET]` → `/TH/BEAM`, **and `/TH/SPRING` for any named
element k2rad emitted as a spring** — an `*ELEMENT_BEAM` on a `*MAT_SPOTWELD`
part or on a `*SECTION_BEAM` `ELFORM=6` part is a `/PROP/TYPE13`/`TYPE8`
`/SPRING`, not a `/BEAM`, so one card can produce two groups. This is
dyna2rad's own per-element `FindRadElement` fallback chain (`/BEAM` → `/SPRING`
→ `/TRUSS`, `convertutils.cxx:298-312`); k2rad emits no `/TRUSS`, so the third
link has no target. `*DATABASE_HISTORY_DISCRETE[_SET]` → `/TH/SPRING`.
Both are screened against the emitted `/BEAM` and `/SPRING` ids (`ERROR 69`) —
dyna2rad's DISCRETE branch is the one element branch with **no** existence
check at all (`converttimehistory.cxx:256-261` assigns the raw list straight
into the group)
Every `_SET` spelling of the family (`_BEAM_SET`, `_DISCRETE_SET`,
`_NODE_SET`, `_SHELL_SET`, `_SOLID_SET`, `_TSHELL_SET`, `_SPH_SET`) is expanded
before the screen. Per the cfgs each accepts **two** id pools — its own element
set (`*SET_BEAM`, `*SET_DISCRETE`, `*SET_SHELL`, `*SET_SOLID`) *or* a
`*SET_PART`, which expands to every element of that family in the named parts.
A set id that resolves in neither is warned and dropped, never written through
as if it were an entity id (dyna2rad's `*SET_PART_LIST` branch keys on the
literal string `"*SET_PART_LIST_TITLE"`, so a plain `*SET_PART_LIST` falls
through and its **part** ids are pushed as **element** ids)
`*DATABASE_HISTORY_NODE_LOCAL[_ID]` and `*DATABASE_HISTORY_NODE_SET_LOCAL` →
`/TH/NODE` with a **per-node `skew_ID`** in columns 11-20 of each id card.
`/TH/NODE` is the only group in this family whose card has that column
(`th_node.cfg` `CARD("%10d%10d%-80s")`; `/TH/BEAM` and `/TH/SPRING` have ten
*blank* columns there and answer a skew with `WARNING 100214` and a silent
drop), which lines up exactly with LS-DYNA, where `_LOCAL` exists only for
`NODE` / `NODE_SET`. The column takes a `/SKEW` **or** a `/FRAME` id —
`hm_read_thgrou.F:2560-2588` scans the skew table then falls through to the
frame table, and the starter echoes it as `SKEW(OR FRAME)`. `REF` picks which:
`REF=0` ("the local system fixed for all time") → the CID's `/SKEW/FIX`, or a
newly synthesized `/SKEW/FIX` frozen from the t=0 node positions when the CID
is a co-rotating `*DEFINE_COORDINATE_NODES` (LS-DYNA calls that combination
invalid; REF wins, and the new id **is** written back — dyna2rad builds the
same frozen skew and then orphans it, `converttimehistory.cxx:468-507`);
`REF=1` ("the projection of the node's absolute motion onto the local system")
→ the CID as it stands; `REF=2` ("the motion of the node expressed in the local
system **attached to node N1** of CID", i.e. *relative* motion) → a
synthesized `/FRAME/MOV` built from the CID's `N1/N2/N3` + `DIR`. One frame per
CID, not per node (a duplicated `/FRAME` id is `ERROR 79` over the merged
`/SKEW`+`/FRAME` table). An unresolvable CID becomes `skew_ID 0` with a warning
naming the quantitative consequence — the channels are then the global
components — rather than dangling into `ERROR 434`. `HFO` (LS-DYNA's
`nodouthf` selector) has no Radioss counterpart and is dropped
The `_ID` spelling of every family carries a per-entity 70-char `HEADING`
beside the id (`CARD("%10d%-70s")`, the two columns **fused**), which is
written into the group's `elem_name` column so a T01 channel keeps the label
the deck gave it. The reader keeps 40 characters of it
(`hm_read_thgrne.F:169`)
`*DATABASE_HISTORY_SEATBELT` → **nothing**, with the gap named in
`recognized_not_emitted`. dyna2rad probes the *first* listed element's
`PID → SECID` and routes the whole list to `/TH/SPRING` (a `*SECTION_SEATBELT`
1D belt) or `/TH/SHEL` (a `*SECTION_SHELL` 2D belt) on that one answer. k2rad
converts neither `*ELEMENT_SEATBELT` nor `*SECTION_SEATBELT`, so **both**
branches are unreachable: there is no element in the output deck carrying those
ids, and naming them is `ERROR 69` — a deck that "converts" and then refuses to
run. The 2D-belt route becomes correct as soon as `*ELEMENT_SEATBELT` is
converted
`*DATABASE_NODAL_FORCE_GROUP[_TITLE]` → one `/TH/NODE` per card over the
expanded `*SET_NODE`, with the seven variables dyna2rad writes verbatim
(`DEF REACX REACY REACZ REACXX REACYY REACZZ`) and `skew_ID = CID` on every
node. The interval comes from `*DATABASE_NODFOR` ("the output interval must be
specified using `*DATABASE_NODFOR`", p.16-121), which is otherwise
interval-only and reports itself as such. **Read the change of meaning**: the
`REAC*` channels are the *time-accumulated* reaction impulse (below), *and*
LS-DYNA's nodfor is a **free-body cut** — the force the rest of the model
exerts on the group, nonzero anywhere in the mesh — while the Radioss `REAC*`
channel is the **kinematic constraint reaction** and is identically zero on a
node carrying no `/BCS`, `/RBODY` or imposed motion. For a real free-body
section force use `*DATABASE_CROSS_SECTION_PLANE/_SET` → `/SECT` + `/TH/SECTIO`
`*DATABASE_RBDOUT` → one `/TH/RBODY` over **every** `/RBODY` the conversion
wrote — a presence-only trigger with no id list, the same "collect every
converted entity" shape `/TH/RWALL`, `/TH/SECTIO` and `/TH/INTER` use. All four
producers are covered: `*MAT_RIGID` parts (with `*PART_INERTIA`, the
element-free CoG masters and the `*CONSTRAINED_RIGID_BODIES` merge masters),
`*CONSTRAINED_NODAL_RIGID_BODY`, and the implicit no-rigid-body probe body.
Two `/TH/RBODY`-only card rules: the id list is a **ten-per-line** cell list
with no name and no skew column (`th_rbody.cfg` `FREE_CELL_LIST`), and a
leading id of `0` selects **all** rigid bodies
(`hm_read_thgrki_rbody.F:123-125`), so a placeholder zero is never written.
`DEF` = `FX FY FZ MX MY MZ RX RY RZ`, and the two halves read differently:
`FX..MZ` are a time-accumulated force/moment **impulse**
(`rgbodfp.F:261-266`, `FS(1)=FS(1)+AFM1*DT1*WEIGHT(M)`) while `RX/RY/RZ`
integrate the angular *velocity* (`rgbodv.F:91-93`) and **are** the body's
rotation angle. LS-DYNA's rbdout is a motion file; for rigid-body translation
add a `*DATABASE_HISTORY_NODE` on the body's main node
`*DATABASE_BNDOUT` → one `/TH/NODE` named `TH_NODE_BNDOUT` with
`REACX/Y/Z` (+ `REACXX/YY/ZZ` when a prescribed motion drives a rotational dof)
over every node an `/IMPDISP`, `/IMPVEL` or `/IMPACC` actually drives —
dyna2rad names exactly those three cards as the source (`dyna2rad.cxx:456`).
The scope is recorded at the point of emission, so a motion row that was
warned about and dropped (unsupported DOF, a pid with no `/RBODY`, an empty box
intersection) contributes no node and cannot dangle into `ERROR 78`. A
zero-scale `*BOUNDARY_PRESCRIBED_MOTION_SET` row is deliberately **out** of
scope: `sf=0` means "fix this dof" and becomes a `/BCS`, which is
`*DATABASE_SPCFORC`'s territory. The *energy* half of bndout has no `/TH`
channel; take it from the global energy balance
`*DATABASE_TPRINT` → **nothing**, deliberately. dyna2rad answers it with
`/ANIM/NODA TEMP` + `/ANIM/ELEM TEMP` and a `TEMP` variable appended to every
existing `/TH/NODE` and `/TH/BRIC` group, with no check that a thermal solution
was ever requested. k2rad converts **no** thermal keyword at all (no
`*CONTROL_THERMAL_*`, `*MAT_THERMAL_*`, `*INITIAL_TEMPERATURE` or
`*BOUNDARY_TEMPERATURE`, and no `/HEAT/MAT`), so a converted deck cannot run a
thermal solve and the channel cannot carry data. What it would carry instead
was measured on a 576-brick deck: with `/MAT/ELAST` the nodal and element
temperature fields come out **all zero**, with `/MAT/PLAS_JOHNS` (which
allocates `GBUF%TEMP` but never integrates it) a **frozen 300** — and the
scalar is *always* created in the A-file (`genani.F:1905`, `:4547`), so the
result is a flat fringe that looks like data. The starter says the same thing
on the TH side and nowhere else (`WARNING 1087 OUTPUT TEMP WHILE TEMPERATURE IS
NOT COMPUTED`, `hm_read_thgrne.F:228`); there is no equivalent warning on the
ANIM side, so an emitted `/ANIM/*/TEMP` is silently uninformative. Its `dt`
also stays **out** of the `/TFILE` minimum, per the membership rule: a card
with no `/TH` consumer would only thicken the T01 for channels that are not in
it
`*CONTROL_PARALLEL` → engine `/PARITH/ON` when `CONST=1` on any card,
`/PARITH/OFF` otherwise — **and only when the deck actually carries the card**.
`CONST=1` requires "that all contributions to global vectors be summed in a
precise order independently of the number of processors used" (p.12-449), which
is exactly `/PARITH/ON`: the engine writes each contribution into a fixed
per-node slot of the skyline `FSKY` array and gathers them in a deterministic
walk (`asspar4.F`), so the sum order is invariant in both the thread count and
the MPI domain count. Measured on a 576-brick LAW2 model: `/PARITH/ON` gives a
**bitwise identical** T01 at `nt=1` and `nt=4`, `/PARITH/OFF` differs in the
7th digit — which is also how to verify the card was consumed. `NCPU`,
`NUMRHS` and `PARA` have no Radioss counterpart (NCPU is the runtime `-nt`
argument, not a deck card) and are named as dropped. dyna2rad creates `/PARITH`
*unconditionally* and defaults it to `OFF` (`convertcards.cxx:973`) before it
has even looked for the LS-DYNA card, which silently flips OpenRadioss's own
default of `ON` (`contrl.F:400`) on every deck it converts; k2rad does not
change a solver default from a card the deck does not carry. Note `/IMPL` and
`/EIG` veto `/PARITH/ON` at run time (`lectur.F:681`), which the warning says
`*DATABASE_SPCFORC` → `/TH/NODE` `REACX/Y/Z` (+ `REACXX/YY/ZZ` when a
rotational DOF is constrained) on every SPC-constrained node, plus engine
`/ANIM/VECT/FREAC`. **The `REAC*` channel is a time-accumulated reaction
*impulse*, not a force** — the engine adds `m*a*dt` to it every cycle
(`reaction_forces_th.F:62`, and `bcs1th.F:143-155` on the `/BCS` path itself,
where the rotational channels use the nodal inertia `IN`, so `REACXX/YY/ZZ` are
*angular* impulses) and zeroes the accumulator only once, *before* the
iteration loop (`resol.F:1901`, loop head `:2612`), so it rises monotonically
under a steady load and carries force x time units. The spcforc-equivalent
force is its time derivative, `F = d(REAC)/dt` (`tools/th_to_csv.py` writes
that column; or `numpy.gradient(reac, t)` on the T01 column, or a
least-squares slope over a steady window — validated to -0.0002% against a
known weight). The converter warns about this on every converted deck. The
companion `/ANIM/VECT/FREAC` field *is* the instantaneous force
(`reactions.F:328`, and `bcs1th.F:281-287` runs the identical algebra with no
`dt` factor). The implicit path integrates trapezoidally instead of
rectangularly (`bcs1th_imp.F:46-56`) but is still an integral — no solver path
writes an instantaneous `/TH` reaction.
**Both** `/BCS` sources count: `*BOUNDARY_SPC_*` and the
`*CONSTRAINED_NODAL_RIGID_BODY_SPC` option (whose `/BCS` acts on the rigid
body's master node, so that node is the reaction node)
`*DATABASE_NCFORC`, `*DATABASE_RCFORC` → `/TH/INTER` resultants over
every converted contact interface (OpenRadioss has no per-node contact-force
time history; for `NCFORC` the nodal-resolution view is the
`/ANIM/VECT/CONT` + `/PCONT` vectors). **The `FNX/Y/Z` + `FTX/Y/Z` channels
are a time-accumulated contact *impulse*, not a force** — `i7for3.F:1459-1476`
adds `F*dt` every cycle under the engine's own comment `SAUVEGARDE DE
L'IMPULSION NORMALE`, `thkin.F:56` writes it out undivided, and nothing resets
it on the rank that writes the T01 (`hist2.F:616-622` zeroes `FSAV` only for
`ISPMD/=0`; `sortie_main.F:1945`, headed "TRAITEMENT SUR FSAV NON CUMULE",
resets only the monvol block, `FSAV(26)` and `FSAV(29)`). The rcforc-equivalent
force is `d(FNX)/dt`; `tools/th_to_csv.py` writes that column
`*DATABASE_SWFORC` → the three spot-weld force channels, matching dyna2rad's
own two-pass split (`dyna2rad.cxx:613-695`, where `SWFORC` appears twice):
`/TH/SPRING` over the `*MAT_SPOTWELD` (MAT_100) **beam** welds, listed by their
original `*ELEMENT_BEAM` ids (the `/PROP/TYPE13` connectors keep them, so a T01
channel maps 1:1 onto an swforc row) with variables **`DEF FAIL`** — `FAIL` is
the weld rupture flag and is *not* part of `DEF` (`hm_read_thgrou.F:1519`);
`/TH/BRIC` over the MAT_100 **solid** welds (`DEF` = stress and internal
energy — the force *resultant* needs a `/CLUSTER`); and `/TH/CLUSTER` over the
`*DEFINE_HEX_SPOTWELD_ASSEMBLY` welds with **`DEF FLOC`**, where `FLOC` adds the
local `FS`/`FN`/`MS`/`MN` weld resultants dyna2rad never requests. Unlike the
`/TH/INTER` / `/TH/NODE REAC*` channels these are instantaneous forces — and
they must be read from the T01, not the animation: `/ANIM/SPRING/FORC` writes
zeros for `/PROP/TYPE13` connectors that the T01 shows carrying kilonewtons.
Only welds that were actually emitted are listed: naming a weld whose part the
connector writer skipped (zero-length, no `*SECTION_BEAM`, no area) is starter
`ERROR 69` and the deck is refused, so those ids are dropped with a warning
instead. A deck that asks for swforc but defines no weld gets a warning and
**no** dangling `/TH` block; the `dt` joins the `/TFILE` minimum
`*DATABASE_DEFORC`, `*DATABASE_DISBOUT` → one `/TH/SPRING` each, over the
two connector families LS-DYNA keeps in separate databases: DEFORC is
"discrete spring and discrete damper (`*ELEMENT_DISCRETE`) data" and DISBOUT is
"discrete beam element, type 6" (Vol I R16 p.1944-1945), so the springs
synthesized from `*ELEMENT_DISCRETE` and the ones from a `*SECTION_BEAM`
`ELFORM=6` part get their own group and each T01 channel stays attributable to
the card the deck wrote. Variables `DEF` = `OFF FX FY FZ MX MY MZ LX LY LZ RX
RY RZ IE LENGTH` (`hm_read_thgrou.F:1518-1520`). Element ids are the original
LS-DYNA ones, **one per line** — `/TH/SPRING` is read by `hm_read_thgrne.F`,
not the ten-per-line `hm_read_thgrki.F` that `/TH/CLUSTER` uses, and a second
id on the same line is `WARNING 100214` with the id **silently dropped**. As
with swforc, only ids a `/SPRING` was actually written for are listed (both
spring writers skip elements — a grounded element whose anchor node has no
coordinates, a part with no usable beams — and naming one is starter
`ERROR 69`, which refuses the whole deck). These are instantaneous forces and
they are in **raw deck units**: k2rad rescales nothing, so a ton-mm-s deck
reports newtons and millimetres exactly as the `.k` states them. A deck that
asks for either card but has no matching connector gets a warning and no
`/TH` block, and both `dt`s join the `/TFILE` minimum.
LS-DYNA offers two ways to narrow the deforc selection (p.1944): `PF=1` on
`*ELEMENT_DISCRETE` ("forces are **not** printed DEFORC file", p.19-32) is
**honoured** — the `/SPRING` is still emitted, only the `/TH` group shrinks —
while `*DATABASE_HISTORY_DISCRETE` gets its own `/TH/SPRING` group over exactly
the elements it names, so a deck using both ends up with the deforc group as a
**superset** of its own deforc file. That is over-reporting, never
under-reporting, and the emitted warning says so whenever the card is present
`*DEFINE_HEX_SPOTWELD_ASSEMBLY` (+ `_1` … `_16`) → one `/GRBRIC/BRIC` +
one `/CLUSTER/BRICK` per assembly (LS-DYNA caps an assembly at 16 hexes,
`/CLUSTER` at 500, so the 1:1 map always fits). `ID_SW` is reused verbatim as
the cluster id when it is usable (a blank/zero or repeated `ID_SW` is replaced
by a generated id with a warning — `/CLUSTER/BRICK/0` would make the
`/TH/CLUSTER` request read as *all* clusters); `skew_ID=0` lets the starter
build the weld frame from the cluster's own bottom→top face normal; `Ifail=3`
(multi-directional). Failure limits come from the `*MAT_SPOTWELD` of the first
element's part: `Fn_fail1=NRR`, `Mt_fail=MRR` straight through, and each
two-direction pair collapsed to its live minimum — `Fs_fail=min(NRS,NRT)`,
`Mb_fail=min(MSS,MTT)` — with `a1..a4=1` and **`b1..b4=2`**. Radioss scores one
shear resultant against one limit (`clusterf.F:365,367`) where MAT_100 scores
`NRS` and `NRT` separately, and `min` is the reduction that agrees with the
quadratic exponent: it reproduces MAT_100's `(Nrr/NRR)²+…≥1` criterion exactly
when `NRS==NRT` and `MSS==MTT`, and is conservative otherwise. (`sqrt(NRS²+NRT²)`
paired with `b=2` would halve the shear damage; dyna2rad's `b=1` makes the
interaction linear and fails a combined-load weld early — neither half is right
on its own.) Element ids that are not 8-node `/BRICK` (tetrahedra, unknown ids)
are screened out of the group with a warning — the starter *accepts* a tet
there, which is exactly the problem: a cluster takes the weld's two joined faces
from the hex node ordering (`hm_read_cluster.F:201-205`), so a tet's degenerate
top face corrupts the local frame and the whole failure surface with it
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
per-entity `/TH` blocks only for entities a `*DATABASE_HISTORY_*` names),
`*DATABASE_GLSTAT` (no card needed — OpenRadioss writes the global energy
balance automatically), `*DATABASE_NODFOR` on a deck with no
`*DATABASE_NODAL_FORCE_GROUP` (it is an interval, not a channel selection),
`*DATABASE_TPRINT` (no thermal solver exists to schedule) and
`*DATABASE_HISTORY_SEATBELT` (no `*ELEMENT_SEATBELT` in the output deck to
name). Except for `TPRINT`, whose channels do not exist at all, the `dt` is
still honoured as the `/TFILE` frequency. The same channel carries any
`*CONTACT` that produced
no `/INTER` (and any `*CONTACT_FORCE_TRANSDUCER` that produced no
`/INTER/SUB`), with the lost interface ids named — a missing contact
changes the physics, not just the instrumentation, so it can never be
invisible in the log.

### Output frequencies the deck does not state

Radioss has ONE time-history frequency for the whole T01, so the whole
`*DATABASE_*` family collapses to a single `/TFILE`. k2rad takes the **minimum**
of every interval the deck asked for — never the first one in some arbitrary
order, which would sample a channel coarser than requested.

Membership is a rule, not a list: a card's `dt` joins the minimum **iff** that
card drives a real `/TH` group. `NODOUT`, `ELOUT`, `GLSTAT`, `MATSUM`,
`SPCFORC`, `NCFORC`, `RCFORC`, `BLSTFOR`, `RWFORC`, `SECFORC`, `SWFORC`,
`DEFORC`, `DISBOUT`, `JNTFORC`, `SPHOUT`, `BNDOUT`, `RBDOUT`, `NODFOR` and
`ABSTAT` are in. `BINARY_D3THDT`, `BINARY_INTFOR` and `SLEOUT` stay out — they
have no `/TH` consumer at all, so honouring them would only thicken the T01 for
channels that are not in it — and so does `TPRINT`, because k2rad emits no
thermal solver. Four of the members are gated on their **own** consumer rather
than on the card's presence, because the test is "does this card pace a channel
that is *in* the T01": `BNDOUT` needs a prescribed motion, `RBDOUT` a rigid
body, `NODFOR` a nodal-force group, and `ABSTAT` a converted `/MONVOL`. The `*DATABASE_HISTORY_*` family has no `DT` field at all in
any spelling, and `*DATABASE_NODAL_FORCE_GROUP` has none either: its interval
is `*DATABASE_NODFOR`'s, which is why that card is in the list despite
selecting nothing itself.

A **negative** `DT` means "output every `-DT` time steps" (p.16-7). Radioss's
`/TFILE` is a *time* interval with no cycle-based form, so such a request cannot
be honoured and takes no part in the minimum — but it is named in the warning
below rather than counted as "the deck stated nothing".

When **no** `*DATABASE_` card states a positive interval at all, the frequency
has to be invented, and it is derived from the run length: `/TFILE =
ENDTIM/1000`, i.e. 1000 samples over `*CONTROL_TERMINATION` — the same shape as
the `/ANIM/DT` default (`ENDTIM/40`, 40 frames). A fixed constant is wrong at
both ends of the scale: `0.001 s` on a `0.01 s` impact is ten T01 records for
the whole event.

`0.001` remains the floor whenever `ENDTIM` is not a usable run length — no
`*CONTROL_TERMINATION` at all (an include-only fragment), `ENDTIM <= 0`, or an
`ENDTIM >= 1e6` **sentinel**, the idiom for a deck that really terminates on
`ENDCYC`/`ENDENG`. Scaling from a `1e20` sentinel would derive `/TFILE 1E+17`, a
T01 that never fires — a silent total loss of output, worse than the constant.
(The whole 201-deck regression corpus states an `ENDTIM` between `8.5e-5` and
`30`, four orders of magnitude below that threshold.) The floor also matters
because a zero `/TFILE` is *silently ignored* by the engine (`lectur.F:335`) and
the T01 would then be written at a frequency nobody chose. The derivation is
reported as a warning whenever the deck actually contains a `/TH` group.

`/ANIM/DT` is guarded the same way but in the opposite direction: with
`ENDTIM <= 0` and no `*DATABASE_BINARY_D3PLOT` `DT`/`NPLTC`, the animation
frequency computes to zero — and `/ANIM/DT  0. 0` is **not** a harmless no-op.
`freanim.F:131-134` raises engine `MESSAGE 293` ("TIME FREQUENCY … MUST BE
GREATER THAN ZERO") and calls `ARRET(0)`, so the run stops before cycle 1. k2rad
**omits the card entirely** in that case (`DTANIM0` stays zero,
`lectur.F:2648-2651` pushes `TANIM` to 1e30, no A-files, no error) and warns
that no animation will be written. Verified end to end: the same cycle-
terminated deck `ERROR TERMINATION`s with the zero card and
`NORMAL TERMINATION`s without it.

### Reading the T01: which channels are integrated

Several OpenRadioss `/TH` channels are written as a running **time integral**
rather than as the instantaneous quantity their name suggests. Nothing in the
engine, the starter or any post-processor flags this: the column simply climbs,
and an engineer comparing it against the LS-DYNA file it stands in for is
comparing an impulse against a force.

Every `/TH` variable k2rad emits, audited against the engine source at
`C:/OpenRadioss/source`:

| `/TH` block | channels | what the T01 actually holds | engine evidence |
|---|---|---|---|
| `/TH/NODE` | `REACX/Y/Z`, `REACXX/YY/ZZ` | **accumulated impulse** (force·time; the `XX/YY/ZZ` are moment·time) | `reaction_forces_th.F:62`, `bcs1th.F:143-155` add `m·a·dt` / `I·ar·dt`; only reset `resol.F:1901`, before loop head `:2612`; written raw `thnod.F:176-178` |
| `/TH/NODE` | `DX/DY/DZ`, `VX/VY/VZ` (`DEF`) | instantaneous | `thnod.F:124-135` |
| `/TH/INTER`, `/INTER/SUB` | `FNX/Y/Z`, `FTX/Y/Z` (`DEF`) | **accumulated impulse** | `i7for3.F:1459-1476` (`+F*DT12`, comment `SAUVEGARDE DE L'IMPULSION NORMALE`), `:3055-3079`, `:1559-1561`; copied raw `thkin.F:56`; `FSAV` zeroed only for `ISPMD/=0` (`hist2.F:616-622`), `sortie_main.F:1945` resets only monvol / `FSAV(26)` / `FSAV(29)` |
| `/TH/SECTIO` | `FNX/Y/Z`, `FTX/Y/Z`, `M1/M2/M3` (`DEF`) | **accumulated impulse + angular impulse** | `section_c.F:459-467`, `section_s.F:565-572` (`+DT12*FST`) |
| `/TH/RWALL` | `FNX/Y/Z`, `FTX/Y/Z` (`DEF`) | **accumulated impulse** | `rgwal0.F:504-509`; the `÷DT12` true force goes only to `FOPT` (/ANIM) and the sensors, `:496-500` |
| `/TH/SURF` | `P`, `A` | **per-`/TFILE`-interval aggregate** — `P` is the interval mean, `A` is the loaded area × cycle count, so `P*A` is not a force | `pblast_1.F:418-419` accumulate; `hist2.F:688` divides `P` by `A`; `sortie_main.F:1976-1982` resets both every write |
| `/TH/SPRING` | `FX..MZ`, `LX..RZ` (`DEF`) | instantaneous, in **raw deck units** (k2rad never rescales, so a ton-mm-s deck reports N and mm) | `thres.F:355-361` writes `GBUF%FOR` / `GBUF%MOM` directly |
| `/TH/SHEL`, `/TH/SH3N` | `F1/F2/F12`, `M1/M2/M12`, `OFF` (`DEF`) | instantaneous element state | `thcoq.F:305-315` |
| `/TH/BRIC` | `OFF`, `SX..SXZ`, `DENS`, `TEMP` (`DEF`) | instantaneous element state | `thsol.F:329-336` |
| `/TH/BEAM` | `OFF`, `F1/F2/F3`, `M1/M2/M3`, `IE` (`DEF`) | instantaneous element state | `hm_read_thgrou.F` `IVARPG` row 1 = indices 1-8 |
| `/TH/RBODY` | `FX/FY/FZ`, `MX/MY/MZ` (half of `DEF`) | **accumulated impulse + angular impulse** | `rgbodfp.F:261-266` (`FS(1)=FS(1)+AFM1*DT1*WEIGHT(M)`), copied raw by `thkin.F` |
| `/TH/RBODY` | `RX/RY/RZ` (the other half of `DEF`) | the body's **rotation angle** — an integral of the angular velocity, so already a displacement-like quantity; do **not** differentiate | `rgbodv.F:91-93` (`FS(7)=FS(7)+VR(1,M)*DT2*WEIGHT(M)`) |
| all types | `IE`, `KE`, `PLAS`, energies | cumulative by nature (an energy, not a rate) — no correction needed | — |

The instantaneous quantity is the time derivative of the accumulated column.
`tools/th_to_csv.py` extracts a T01 to CSV and writes that derivative as a
sibling column next to every accumulated channel:

```bash
python tools/th_to_csv.py runT01              # writes run_th_<TYPE>_<id>.csv
python tools/th_to_csv.py runT01 --list       # inventory only, writes nothing
```

```
time,      3_REACY,   3_REACY_ddt
0.030000,  0.073500,  3.850418        # N*s        # N
```

The `_ddt` columns are on by default (`--no-derivative` opts out) and are
purely additive — every original column keeps its name and order. The suffix
is deliberately unit-neutral, because `d/dt` of `REACX` is a force while
`d/dt` of `REACXX` or of a `/TH/SECTIO` `M1` is a moment. `/TH/SURF` is left
alone with a printed warning: an interval aggregate is not a running integral,
so differentiating it would mean nothing.

The tool is **standard library only** — no numpy needed. Its T01 reader was
validated cell-by-cell against Altair's own `th_to_csv` binary on four real
T01 files (1.29 million values), with no disagreement beyond the reference
CSV's print rounding.

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
│   ├── th_to_csv.py      # T01 → CSV, with d/dt columns for the accumulated channels
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
  `*RIGIDWALL_*` wall geometry only (literal geometry inside other
  keywords of the include — coordinate-system origins, box extents,
  velocity vectors under rotation, literal rotation-axis points under any
  transform — is warned per keyword).
- **Single-element / sparsely-connected SOLID validation decks need
  `*CONTROL_TIMESTEP TSSFAC <= 0.35`.** `*SECTION_SOLID ELFORM = 1` maps to
  `/PROP/SOLID` `Isolid = 17`, which is FULL 2x2x2 integration
  (`hm_read_prop14.F:333-341` sets `NPT = NPG = 8`); LS-DYNA's `TSSFAC = 0.9`
  default was calibrated for the UNDER-integrated `ELFORM = 1` element k2rad
  substitutes away from. No `/DT` card is emitted unless the deck states
  `TSSFAC > 0`, so the engine then runs at Radioss's own default `Tsca = 0.9`
  (`dt = 0.857 L/c`), which is super-critical for a lightly-connected hex:
  measured on a 10 mm steel hex, an unstable mode amplified round-off by x3.07
  per cycle (a brick driven rigidly on all 8 nodes — physically unable to deform
  — grew 0.2906 mm of in-plane distortion out of 1.85e-18, with I-ENERGY still
  ~1e-27), and sibling decks hit ENERGY ERROR LIMIT at 1121-1323 cycles.
  `Isolid = 24` at the same step does not help. Real meshes share nodal mass
  across up to 8 elements, which lowers `omega_max` by up to `sqrt(8)`, so this
  bites validation decks rather than production models — but a one-element deck
  that "diverges" is almost always this and not the keyword under test. Adding
  `TSSFAC = 0.3` makes k2rad emit `/DT  0.3  0` and the same deck reaches
  NORMAL TERMINATION.

---

## License

MIT
