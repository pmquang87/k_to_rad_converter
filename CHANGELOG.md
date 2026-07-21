# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Prior history (before this changelog was introduced) is summarized in the
`git log` — each keyword conversion and bug fix landed as its own commit / PR.

## [Unreleased]

### Added

- **`*SECTION_SHELL` `ELFORM` → `/PROP/SHELL` `Ishell` is now a user CHOICE
  (`--shell-formulation {qbat,qeph}` / GUI radio pair /
  `convert(shell_formulation=...)`), and it is no longer silent.** Closes #77.

  `ELFORM=2` (Belytschko-Tsay — the most common shell formulation in LS-DYNA
  decks) fell through `_elform_to_ishell` (`writer/common.py:84`) to
  `Ishell=12` (QBAT, **fully** integrated) **with no warning of any kind**.
  LS-DYNA `ELFORM=2` is **under**-integrated, so the element's integration
  class changed underneath the user. Under `/FAIL/JOHNSON Ifail_sh=2` that
  costs erosion: `fail_setoff_npg_c.F` wants 4 Gauss × 2 through-thickness =
  **8 failure events** to delete an element against the 2 the original deck
  implies — measured at up to **~1.7× under-erosion** on a 38k-shell blast
  model (19,512 `FAILURE (JC)` messages, 1,524 elements failed fully
  through-thickness at ≥1 Gauss point, **875 actually deleted**).

  QEPH is **not** simply made the default, because it changes results on every
  existing shell deck. So `qbat` (`Ishell=12`) stays the default and every
  golden is unchanged without the flag; `qeph` (`Ishell=24`, reduced
  integration with *physical* stabilisation) is the closer match to
  Belytschko-Tsay and additionally drops the `dn=1.0e-3` numerical damping the
  starter injects for `Ishell=12` (`hm_read_prop01.F:279`).

  Blast radius of choosing `qeph`, asserted by the suite rather than merely
  documented (`tests/test_shell_formulation_option.py`): **4 `/PROP/SHELL`
  props across 3 fixtures** — `tied_weld` 2, `shell_explicit` 1,
  `rigid_contact` 1, `implicit_qstat` 0 (implicit already returned 24, and the
  option deliberately does not disturb it).

  The option governs the **fallback only**: `ELFORM` −16/9/20/21/26 stay QEPH
  either way, their Radioss counterpart being unambiguous. Under-integrated
  `Ishell=1..4` is deliberately not offered — it would activate the `Hm/Hf/Hr`
  hourglass path that `writer/mesh.py`'s own inert-hourglass warning documents
  as unused, and `writer/inistate.py:94` sets `npg = 4 if ishell in (12, 24)
  else 1`, so 1..4 would silently change `/INISHE` and corrupt
  `*INITIAL_STRESS_SHELL` transfer. Both offered values leave `npg` at 4.

  Crucially the mapping is now **reported either way**
  (`_warn_shell_formulation_choice`, `writer/mesh.py`): the default names the
  Ishell it chose, states the under-erosion consequence and points at the
  alternative; `qeph` states that results will differ from earlier conversions.
  *A default and a silent default are different things, and the second was the
  actual defect.* Follows PR #70, which made the analogous ELFORM→`Isolid`
  correction for solids.
- **`/DT/{SHELL,SH_3N,BRICK}/DEL` time-step deletion floor, on explicit consent
  only — and `*CONTROL_TIMESTEP` `TSLIMT`/`ERODE` stop being silently dropped.**
  Closes #78.

  There was no `/DT/.../DEL` emitter anywhere in the package, and fields 3
  (`TSLIMT`) and 6 (`ERODE`) were sliced off the card in
  `handle_control_timestep` (`handlers.py:2061`) and thrown away — `ERODE=1`,
  which is LS-DYNA for *delete elements whose step falls below the floor*,
  produced a converted deck with no such behaviour and no warning that the
  request had gone missing.

  The card **deletes elements**, so a floor k2rad invented would silently cost
  the model mass and stiffness the LS-DYNA original kept. There are therefore
  exactly two ways to get one, both explicit:

  - the **deck** asks — `ERODE=1` **and** `TSLIMT>0` (`TSLIMT` alone is a step
    limit, not permission to delete; `ERODE` alone has no threshold, and both
    half-requests are now reported via `recognized_not_emitted` rather than
    dropped);
  - the **user** asks — `--dt-del <seconds>` / GUI entry box /
    `convert(dt_del=...)`, the escape hatch for a long run where one degrading
    element drags the global step toward zero. No LS-DYNA counterpart, so it is
    never derived automatically.

  All three element families are emitted: `SH_3N` is a separate family from
  `SHELL` in Radioss, so a deck whose `ESORT` generates triangles would
  otherwise leave them with no floor at all.

  **Ordering against mass scaling**, which #78 called the crux and feared would
  leave one card as dead configuration. Verified in
  `engine/source/elements/shell/coque/cdt3.F` (OpenRadioss 2026-05-20):

  - the element step is `DT = DTFAC1(3)*ALDT/SSP` (`cdt3.F:111-115`) —
    characteristic length over sound speed, **no mass term** — so nodal mass
    scaling cannot lift an element back off the threshold;
  - the `IDTMIN(3)==2` deletion block (`cdt3.F:146`) executes **before** the
    `IF (NODADT/=0...) RETURN` at `cdt3.F:200`.

  So `/DT/NODA/CST` and `/DT/.../DEL` do **not** fight, and the log says so.
  They are not fully independent though, and this is the case the original
  analysis missed: under **AMS** (`IDTMINS==2`) the step comes from
  `SQRT(MAS/STI)` instead (`cdt3.F:105-109`), which *is* mass-based, and
  `cdt3.F:200` also returns early for AMS — so a floor under `--ams` is warned
  about rather than assumed to work.

  `Tmin` here is a **deletion** threshold, not a mass-scaling target, and the
  two want very different values: ~0.9x the initial step deletes elements that
  merely stretched ~10%, which shreds a crushable structure; deletion belongs
  at ~0.4-0.5x, i.e. near-total collapse of an element's characteristic length.
  k2rad carries `TSLIMT` or the user's number and never invents one. Tests in
  `tests/test_dt_deletion_floor.py`.

- **Hyperelastic rubber batch** (`*MAT_BLATZ-KO_RUBBER` / MAT_007,
  `*MAT_MOONEY-RIVLIN_RUBBER` / MAT_027, `*MAT_OGDEN_RUBBER` / MAT_077_O,
  `*MAT_HYPERELASTIC_RUBBER` / MAT_077_H, incl. the underscore spellings of
  the hyphenated names, the numeric aliases and `_TITLE` forms, plus
  `*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP]`) — the roadmap P1 batch, law
  choices and constants per dyna2rad (`p_ConvertMatL27`/`L77`/`L77H`, case 7,
  `ConvertInitialFoamReferenceGeometry`); starter-validated: all seven
  single-material decks (Blatz-Ko, Mooney constants + curve, Ogden direct +
  fit, 077_H polynomial, Blatz-Ko + `/XREF`) pass the OpenRadioss starter
  with 0 errors / 0 warnings and the expected field echoes (`Nu=0.463`,
  `IFORM=2`, `1/D1=K`, uninverted Prony `BETA`, `XREF_PART_<pid>`):
  - New `/MAT/LAW42` emitter (audited against `matl42_Ogden.cfg
    FORMAT(radioss140)`, the block a `/BEGIN 2022` deck reads): the two
    mandatory blank cards after the `Mu` and `alpha` rows, and `funIDbulk` at
    cols 51-60 — cols 41-50 are a phantom `Jstrain` `%10d` the reader consumes
    but never uses. MAT_007 → the fixed form `Mu_1=G`, `alpha_1=2`,
    `Nu=0.463`; MAT_027 (no `LCID`) → `Mu_1=2A`, `Mu_2=−2B`, `alpha=±2`,
    `Nu=PR` verbatim + dyna2rad's 500-point `funIDbulk` bulk-scale curve
    reproduced **as-built** (its `pow(j,(-1/3))`/`pow(j,(1/3))` are C++
    integer divisions → `j^0`; same accumulated `j += 0.01` grid, so the
    `j≈1` point stays finite) — the shipped converter's output is the
    validation reference; degenerate `PR=0.5` / `A=B=0` skip the curve with a
    warning instead of emitting NaN/inf points (starter ERROR 828 named);
    MAT_077_O `N=0` → pairs 1:1 with `Nu=|PR|` (Mullins `PR<0` warned —
    dyna2rad warning 28), `I_form=2`, and the `BETAI>0` viscous terms
    embedded as `Gamma_i=GI` / `Tau_i=1/BETAI` (`BETAI<=0` terms and Ogden
    pairs 6-8 — the radioss140 card has 5 slots — warn-dropped).
  - New `/MAT/LAW69` emitter (`matl69_69.cfg FORMAT(radioss120)`): MAT_027
    with a parsed `LCID` → `LAW_ID=2`, curve id unmodified (the starter runs
    the Mooney-Rivlin fit; dyna2rad applies **no** `SGL/SW/ST` scaling on
    this path — warned when they are non-trivial; a dangling `LCID` falls
    back to the LAW42 branch exactly like dyna2rad's invalid-handle routing);
    MAT_077_O/_H `N>0` → `LAW_ID=int(DATA)` (0 → starter automatic fit),
    `N_PAIR=N`, and `LCID1` rescaled to engineering stress-strain by
    `SFA=1/SGL`, `SFO=1/(SW*ST)` into a `<name>_Duplicate` auto-`/FUNCT`
    (blank `ST` is treated as 1.0 with a warning — dyna2rad leaves `1/(SW*ST)`
    unguarded and writes an infinite scale; the extra scale is applied to the
    already-offset points, sidestepping dyna2rad's unscaled-shift quirk).
  - New `/MAT/LAW95` emitter (`LAW95.cfg FORMAT(radioss2020)` — no NU/IFORM
    fields at this revision): MAT_077_H `N=0` → `C10..C30` 1:1 in the Radioss
    column order (`C10 C01 C20 C11 C02` — C20 before C11, unlike the LS-DYNA
    card), incompressibility as `D1=|2/K|` with `K=2G(1+PR)/3/(1−2PR)`,
    `G=2(C10+C01)`; `PR<0` → Mullins warning and `D1=0` (starter defaults
    ν=0.495); blank `PR` reproduces dyna2rad's exact `K=2G/3` (ν=0) with a
    warning; `C10+C01<=0` leaves `D1=0` warned instead of dyna2rad's
    non-finite `D1`; Bergstrom-Boyce network-B terms all 0 (creep off — the
    starter defaults the zero `C/M/KSI/TAU_REF` to their valid values). Solid
    sections serving a LAW95 part are emitted with `Ismstr=10`: the starter
    force-promotes any LAW95 element group at another Ismstr anyway ("ISMSTR
    IS CHANGED TO 10 SINCE LAW 95 IS ONLY COMPATIBLE WITH ISMSTR=10",
    WARNING 1200, `sgrtails.F`), so pre-setting it yields the identical
    LAW95 formulation with a warning-clean deck; because the native
    promotion is per element group, a non-LAW95 sibling part sharing that
    section is dragged to total strain along with it — warned (mirroring the
    `/XREF` shared-section warning), in both the shared-section and the
    hourglass-overlay split-property paths. An out-of-range `DATA` on the
    `N>0` paths (LAW_ID outside the starter's -1/1/2; blank 0 defaults to
    the -1 automatic fit) is emitted like dyna2rad writes it but flagged
    (starter ERROR 882).
  - New `/VISC/PRONY` machinery (`mat_VISC_PRONY.cfg FORMAT(radioss2021)` —
    **no title line**, 10-space literal gap on the `M` card, 4-field
    `G_i Beta_i Ki Beta_ki` rows): emitted under the material's own id from
    the MAT_077_H `Gi/BETAi` list on BOTH branches, `Beta_i` used directly
    (no `1/BETA` inversion — that belongs to the 077_O embedded form only).
    MAT_077_O's `G>0 & SIGF>0` frequency-independent damping is warn-dropped:
    dyna2rad's `/VISC/PLAS` target only exists from the radioss2025 input
    format and cannot be read in the `/BEGIN 2022` decks k2rad emits.
    `NV`/`LCID2`/`BSTART`/`TRAMP` (relaxation-curve fit), the 077_O `N>0`
    `GI/BETAI` loss, and 077_H's never-read header `G`/`SIGF` and per-term
    `Gj/SIGFj` columns are all warn-dropped (dyna2rad drops them silently).
  - New `/XREF` reference-geometry machinery
    (`xref.cfg FORMAT(radioss90)`): `*INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP]`
    → one `/XREF/<part_id>` (`XREF_PART_<pid>`, `NDTRRG`→`Nitrs`) per
    intersecting part with the stress-free node coordinates, ascending —
    emission is unconditional like dyna2rad's (the material `REF` flags only
    drive coverage warnings: `REF=1` without usable reference geometry warns;
    dyna2rad's MAT_007 nodeless `/XREF` stub is deliberately not replicated).
    Multiple `*INITIAL_FOAM_REFERENCE_GEOMETRY` keyword instances covering
    one part are MERGED into that part's single `/XREF` (later instances win
    per node id; conflicting `_RAMP` `NDTRRG` values resolve to the largest,
    warned) — dyna2rad's per-instance emission writes duplicate
    `/XREF/<pid>` ids there, which the current starter happens to union
    benignly (`hm_read_xref.F` tags nodes per option; starter-verified
    identical reference state), but one `/XREF` per component is the
    spec-sanctioned canonical form.
    Parts the starter would hard-reject are warn-skipped instead of emitted
    (solid `/XREF` law whitelist 1/35/38/42/70/88/90 — ERROR 2014 — and the
    8/4-node solid restriction — ERROR 2013), and the kept parts' solid
    sections are emitted with `Ismstr=10` (`_emit_prop_solid` gained a
    defaulted `ismstr` parameter; the starter rejects `/XREF` on k2rad's
    fully-integrated `Isolid=17` at small strain, ERROR 2013 — a shared
    section dragging non-`/XREF` parts along is warned). The include-affine
    pass lists the keyword as point-bearing (coordinates are not transformed,
    only node ids are offset — warned under a transforming include).
  - All new keywords + aliases registered in the `*INCLUDE_TRANSFORM` offset
    map: MAT_027 card-2 `LCID`; MAT_077_O/_H via a conditional rewriter
    (card 2 carries `LCID1`/`LCID2` only when `N>0` — with `N=0` those columns
    are `MU4/MU6` / `C20/C30` float constants a static spec would corrupt);
    the foam-reference node table in the `*NODE` I8/E16 format (the `_RAMP`
    `NDTRRG` header card is never rewritten).
  - Solver-validation notes (single-element, Mg-mm-s): under prescribed
    isochoric uniaxial deformation the converted LAW42 (Mooney-Rivlin,
    Ogden, Blatz-Ko deviatoric) and LAW95 stresses match the analytic
    incompressible stress-stretch curves to 0.00% at λ = 1.20/1.35/1.50,
    and LAW95 cross-checks LAW42 to machine precision. Caveat for FREE
    near-incompressible explicit runs (K/G ≈ 100 at PR ≈ 0.495, undamped):
    single elements exhibit the classic volumetric ringing / volume-growth
    artifacts of explicit dynamics (the LAW42 `funIDbulk` ordinate is a
    dimensionless multiplier on the Nu-derived bulk — `sigeps42.F`
    `K_eff = RBULK·Fscale·f(J)`, `f(1) ≈ 1.0` as-built, so the Nu-implied
    bulk is active; the curve is NOT a softness bug, but it does bypass the
    no-curve branch's anti-buckling `P_FAC` floor). Real models should ramp
    loads, add damping/bulk viscosity, or run implicit quasi-static —
    solver behavior, not a conversion deviation.

- **Johnson-Cook metals** (`*MAT_JOHNSON_COOK` / MAT_015 and
  `*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE` / MAT_099, incl. the
  numeric aliases and `_TITLE` forms; MAT_098 also gains its `MAT_098`/`MAT_98`
  aliases) — the roadmap P1 batch:
  - MAT_015 → `/MAT/LAW2` (PLAS_JOHNS, new emitter audited against
    `matl2_plas_johns.cfg FORMAT(radioss140)`): `A/B/N/C/EPS0` and `M/TM/TR`
    map 1:1, `rhoC_p = RO·CP` (per-mass → per-volume), `E ← 2G(1+ν)` when only
    `G` is given. Blank `EPS0` takes the LS-DYNA default 1.0 instead of
    dyna2rad's raw 0 (starter ERROR 298 whenever `C>0`).
  - EOS routing per dyna2rad's law choice: a `*PART` `EOSID` (or — warned —
    a shared-id `*EOS_*` that no part in the deck binds via EOSID; a
    part-bound same-id EOS belongs to that binding and the material stays
    LAW2, exactly like dyna2rad, and a shared-id `*EOS_JWL` never reroutes)
    sends the material to `/MAT/LAW4` (HYD_JCOOK, new emitter,
    `matl4_hyd_jcook.cfg` from the **radioss2020** config directory, the one
    a `/BEGIN 2022` deck resolves to — T0 joined the RHOCP heat card in the
    radioss2019 config; the radioss2018 directory's copy has no T0 column) +
    the `/EOS` block rebound to
    the material id (reusing the `_emit_eos` machinery; the standalone
    LAW6-carrier fluid pass skips consumed EOS ids). `PC`→`Pmin` (forced
    negative); `TR`→`T0`, NOT dyna2rad's physically wrong `TR`→`Tmax`.
    An unresolvable/unsupported attached EOS still routes to LAW4 (dyna2rad
    behaviour) but warns; parts sharing the material WITHOUT an EOSID are
    dragged onto the LAW4 and warned (dyna2rad duplicates a multi-part
    material and keeps PLAS_JOHNS for the EOS-less parts).
  - The LAW6-carrier fluid pass now also honours a `*PART` `EOSID` that
    binds an `*EOS_*` to a `*MAT_NULL` of a *different* id: that null (not a
    synthetic orphan) becomes the `/MAT/LAW6` carrier and the `/EOS` is
    re-emitted under the null's mid, warned — previously only the shared-id
    pairing was recognised and such an EOS produced a same-id orphan carrier
    that could collide with another material's id.
  - Failure: `D1-D5` → `/FAIL/JOHNSON` via the extended shared trailer
    (`D3 = −|D3|` sign-convention flip, `EPSILON_DOT_0 = EPS0` — deliberately
    not dyna2rad's 0 — `EROD≠0` → `Ifail_so=2`); `DTF>0` → `/FAIL/GENE1`
    `dtmin` (new GENE1 slot, ridden on the `*MAT_ADD_EROSION` machinery and
    merged when both cards exist), suppressing `D1-D5` on the shell path and
    ignored on the EOS path — dyna2rad's exact priority rules, warned.
    `EFMIN` has no `EPSF_MIN` slot in the radioss2017 `/FAIL/JOHNSON` format
    and is dropped with a warning, as are `VP=1`/`RATEOP`, `SPALL`, `IT`,
    `C2` and `NUMINT`. `/ANIM/ELEM/DAMG` is requested when JC damage or the
    MAT_099 FLD is active.
  - MAT_099 → `/MAT/LAW2` + flat `/FAIL/FLD` at `PSFAIL + A/E` (dyna2rad's
    2-point curve, Ifail_sh=2): `EPPFR`→`EPS_p_max`,
    `min(SIGSAT,SIGMAX)`→`SIG_max0` (blanks take the LS-DYNA 1e28 defaults so
    `min()` cannot discard the one real cap), `Fsmooth=1`; `LCDM` orthotropic
    damage warned (isotropic reduction).
  - `*PART` field 4 (`EOSID`) is now parsed (`PartData.eosid`); all new
    keyword aliases registered in the `*INCLUDE_TRANSFORM` offset map
    (MAT_099's `LCDM` in the curve namespace).

- **Assembly transforms** (`*INCLUDE_TRANSFORM` / `*DEFINE_TRANSFORMATION` /
  `*NODE_TRANSFORM`) — the roadmap's P0 silent-wrong-geometry item. Since
  k2rad inlines includes, the faithful file-to-file mapping is **numeric
  application at parse time** (new `k2rad/assembly.py` + pure-math
  `k2rad/transform.py`) rather than emitting `//SUBMODEL`:
  - `*INCLUDE_TRANSFORM` id offsets (`IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF
    IDFOFF IDDOFF` + `IDROFF`) are added to every id the included file
    defines **and** references, keeping them consistent — driven by a
    per-keyword field map covering the HANDLERS families (mesh, sets,
    sections, materials incl. their curve/table reference fields, curves,
    `*DEFINE` entities, contacts with SSTYP/MSTYP-dependent namespaces,
    BCs/loads/velocities, constraints, rigid walls, database requests).
    Bucket assignment follows the R16 manual / OpenRadioss reader DRAWABLES
    (`IDPOFF` also covers CNRB pids, rigidwall and cross-section ids;
    sections/hourglass/contact ids fall to `IDROFF`; only ids > 0 are
    offset, matching `hcioi_utils.cpp`). An included keyword *outside* the
    map warns loudly instead of silently keeping colliding ids. Conditional
    card layouts are honoured: `*BOUNDARY_PRESCRIBED_MOTION_*` (|DOF| in
    9/10/11 or VAD=4 reads an extra `OFFSET1 OFFSET2 MRB NODE1 NODE2` card
    — MRB/nodes offset, literal axis offsets untouched), `*LOAD_SEGMENT`
    (N5≠0 reads an `N6 N7 N8` node card), `*CONSTRAINED_NODAL_RIGID_BODY_
    SPC` and `*MAT_RIGID` (`CMO<0` makes card-2 `CON1` a
    `*DEFINE_COORDINATE_*` reference in the `IDDOFF` namespace; `CMO≥0`
    leaves it a DOF code).
  - The `TRANID` `*DEFINE_TRANSFORMATION` is composed row-by-row
    (top-to-bottom, each row acting on the previous result — the
    `LECTRANS`/`LECSUBMOD` sequential in-place semantics) into one affine
    map applied to the included `*NODE` coordinates **and to
    `*RIGIDWALL_PLANAR*` literal wall geometry** (base + head points, and
    the `_FINITE` in-plane edge head — the starter's `SUBROTPOINT` replay
    in `hm_read_rwall_plane.F`; `LENL`/`LENM` extents are exact under
    rotation/mirror and warned under scale/shear): `TRANSL`, `ROTATE`
    (direction form and the two-`POINT` alt form detected by the cfg's
    A4-A7-all-zero preread; degrees, Rodrigues/right-hand rule, center =
    rotation point), `SCALE` (zero factors → 1, about the global origin),
    `MIRROR` (plane point + normal point; A7 coordinate-system mirroring
    warned, matching dyna2rad's dead read), `POINT`+`POS6P` (frames per
    `3points_to_frame.F`, `x' = X4 + QQ·PPᵀ·(x−X1)`), `POS6N`, `TRANSL2ND`
    (A3=0 → full node1→node2 distance per the R16 manual, avoiding
    dyna2rad's zero-translation defect), `ROTATE3NA` (axis node1→node2
    **through node3** per the manual; the starter ignores node3), and the
    R16 `MATRIX` cards-3/4 form (`(x,y,z,1)·M` row-vector convention).
    Node-referenced rows resolve parse-time coordinates; a referenced node
    that is itself moved by the transform is pre-transformed through the
    rows composed so far (the `RTRANSPOS` intent, implemented without its
    documented TRA/SYM/SCA collapse defects). `POINT` coordinates are the
    literal card values (dyna2rad behaviour). Unknown verbs warn + skip.
  - Deferred TRANID resolution: the `*DEFINE_TRANSFORMATION` may appear
    before or after the `*INCLUDE_TRANSFORM`, in the parent or another
    include. Binding happens **after** the id-offset pass, against
    post-offset definition ids — dyna2rad's offset-then-resolve order — so
    a same-numbered definition inside an offset include never shadows the
    parent's, and the dyna2rad spelling (TRANID = the definition's
    post-`IDDOFF` id) resolves. A TRANID written on an include card that
    is itself nested inside offset includes shifts with the enclosing
    files' cumulative `IDDOFF` (the reference lives in that file's
    namespace); a main-file TRANID is never shifted. Nested
    `*INCLUDE_TRANSFORM`s accumulate offsets additively and compose
    geometric transforms innermost-first (the `LECSUBMOD` level walk) —
    falling naturally out of registration order.
  - `*NODE_TRANSFORM` (TRSID, NSID[, IMMED]) applies the transform to the
    `*SET_NODE_LIST` nodes **after** all include transforms (`lectur.F`
    order), reading current coordinates like `LECTRANS`; `IMMED=1` is
    treated as deferred with a warning.
  - Everything mutates `Block.raw` before dispatch, so handlers/state/
    writer see final ids/coordinates unchanged; decks without these
    keywords are byte-identical (golden fixtures untouched). Offset-only
    `*NODE` rewrites keep the original coordinate text **verbatim** (zero
    precision loss); transformed coordinates re-emit at the writer's
    `%.10G` precision (widened to `%.17G` when a token overflows its
    16-char field).
  - **Deliberately warned, not applied**: `FCTMAS`/`FCTTIM`/`FCTLEN`/
    `FCTTEM`/`FCTCHG` unit factors (a consistent rescale must touch every
    dimensioned value — kunit's domain; partially scaling only coordinates
    would silently corrupt the physics), `PREFIX`/`SUFFIX` title
    decoration, `IMMED=1`, missing TRANID, unmapped-keyword id offsets,
    and literal geometry in non-`*NODE`/non-`*RIGIDWALL_PLANAR*` keywords
    of a transformed include (coordinate-system origins, boxes,
    detonation/charge points always; direction/tensor carriers like
    `*INITIAL_VELOCITY` or `*INITIAL_STRESS_*` when the transform actually
    rotates/mirrors/scales — a pure translation leaves them valid — and
    additionally `*INITIAL_VELOCITY_GENERATION` with `OMEGA≠0` and
    `*BOUNDARY_PRESCRIBED_MOTION_*` with |DOF| in 9/10/11 under **any**
    transform, because their literal rotation-axis points must move even
    under a pure translation).
  - Tests: `tests/test_include_transform.py` (42 cases — exact TRANSL/
    ROTATE-vs-hand-Rodrigues/SCALE/MIRROR/two-point-ROTATE/POS6P/TRANSL2ND
    coordinates, composition order, offset consistency across
    elements/parts/sets/curves/BCs/contacts/discrete+mass elements,
    ten-node solids, nested includes, TRANID post-offset binding incl. the
    nested-namespace shift, rigid-wall transform incl. `_FINITE`,
    `CMO<0` `CON1` offsets, BPM/LOAD_SEGMENT continuation cards,
    coordinate-text preservation, whitespace free-format rows,
    `*NODE_TRANSFORM` ordering, warning paths, and an end-to-end starter
    `/NODE` roundtrip).

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

- **A `*CONTACT_TIED_*` between two CONFORMALLY meshed parts killed the starter
  with a storm of `ERROR 556`, and the same deck read natively started clean.**
  Reported from the field: a deck combining `*CONTACT_AUTOMATIC_SINGLE_SURFACE`
  and `*CONTACT_TIED_SURFACE_TO_SURFACE_OFFSET_ID` on part sides fails as soon
  as a part is used by both. Reproduced verbatim on that deck — **62 ×
  `ERROR 556 ** ERROR IN INTERFACE TYPE2 / MAIN NODE ID=n IS ALSO SECONDARY
  NODE OF ANOTHER INTERFACE TYPE2`**, `ERROR TERMINATION` — against **0 errors**
  for the identical `.k` read through OpenRadioss's own dyna2rad.

  The `/SURF/PART/EXT` both keywords share is a red herring: a part may appear
  in any number of surfaces. The cause is the **Spotflag**. The two tied parts
  are conformally meshed and **share 3061 nodes** along their common boundary,
  so 3061 of the tie's 4540 secondary nodes are also nodes of its own main
  surface — and `starter/source/interfaces/interf1/chktyp2.F:79` reads

  ```fortran
  IF (ILEV /=25 .and. ILEV/=26 .and. ILEV/=27 .and. ILEV/=28) TAGHIER(J) = 1
  ```

  A TYPE2's secondary nodes are tagged — and can therefore raise `ERROR 556` —
  **only when Spotflag is not one of 25/26/27/28**, i.e. only for the purely
  kinematic formulations, which eliminate their secondary nodes' DOFs outright.
  `_TIED_SPOTFLAG` emitted exactly those: `5` for `SURFACE_TO_SURFACE`, `1` for
  `NODES_`/`SHELL_EDGE_TO_SURFACE`. dyna2rad defaults every routed `/INTER/TYPE2`
  to `Spotflag=28` (`reader/.../convertcontacts.cxx:49`), which is the whole
  reason the native read survives.

  Each formulation is now emitted as its **auto-penalty** counterpart — per the
  Radioss docs, `27` is *"kinematic formulation similar to Spotflag=5 with an
  automatic switch to penalty formulation when incompatible kinematic conditions
  occur"* and `28` is the same for `Spotflag=1`:

  | tied variant | before | after |
  |---|---|---|
  | `SURFACE_TO_SURFACE` | 5 | **27** |
  | `NODES_TO_SURFACE`, `SHELL_EDGE_TO_SURFACE` | 1 | **28** |

  This keeps k2rad's deliberate per-variant formulation choice (a blanket 28
  would silently turn the mesh-transition glue into a spotweld) and adds only
  the fallback: `itagsl2.F:238` demotes an individual conflicting node to a
  penalty tie (`WARNING 1179`) instead of failing the run.

  Spotflag 25–28 also read **one extra card** that was not being written —
  `Stfac(1-20) Visc(21-40) <blank> Istf(61-70)`, the
  `"Optional Card2 : ILEV = 25,26,27,28"` of `hm_read_inter_type02.F:296`.
  Without it the starter consumes the following keyword line as interface data.
  The values emitted (`1.0 / 0.05 / 2`) are the starter's own blank-card
  defaults and match the native reader's echo exactly.

  Result on the reported deck: **62 errors → 0 errors**, `TERMINATION WITH
  WARNING`, restart files written.

- **A tied contact whose SECONDARY side is a whole PART welded ~47× more of the
  model than the source deck asks for.** `_tied_dsearch` sizes the TYPE2 search
  distance from the **worst** secondary-node-to-main-segment distance × 1.2.
  That is correct for the case it was built for — a `*SET_NODE_LIST` weld line
  sitting half a shell thickness off the main mid-plane — but when the side
  names a part, the secondary group is the part's **entire node cloud** and the
  "worst" node is the one on the far side of the part. The measurement then
  returns a part *diameter*, not a surface offset:

  | | dsearch | secondary nodes actually tied |
  |---|---|---|
  | native (dyna2rad) | 0 → starter auto, 1.9e-3 … 2.2e-2 mm | **81** of 4540 |
  | k2rad (before) | **33.98 mm** | **3846** of 4540 |

  The run does not fail — it silently glues most of one part's volume to the
  mating surface. For a part / part-set secondary side dsearch is now left `0`,
  handing the decision to the starter's average-main-segment default (what
  dyna2rad emits unconditionally); the measured worst-node dsearch is kept for
  node-set and segment-set sides, the weld geometry it was validated on. A
  negative Card-3 `SST`/`MST` still overrides both — it is an explicit tie
  distance from the deck. The converted deck now deletes **4459** secondary
  nodes, byte-for-byte the native reader's count.

- **The `*DATABASE_*` family disagreed with itself about how wide its own DT
  field is, and both readings failed SILENTLY.** `*DATABASE_ELOUT`
  (`handlers.py:4520`), `*DATABASE_GLSTAT` (`handlers.py:4533`) and
  `*DATABASE_BINARY_D3PLOT` (`handlers.py:4507`) sliced strict fixed-width
  `w=10` via `_card(..., fixed=True)`, while the other fourteen handlers went
  through `_handle_db_dt` (`handlers.py:2278`), which split free-format first.
  Handed the same card these return different numbers, and neither is right
  on its own:

  | card line | fixed `w=10` | free | correct |
  |---|---|---|---|
  | `1.000000E-05` | **0.0** | 1e-05 | 1e-05 |
  | `     1.0E-05` | **0.0** | 1e-05 | 1e-05 |
  | `   1.0E-05` | 1e-05 | 1e-05 | 1e-05 |
  | `1.0E-05,0,0` | **0.0** | 1e-05 | 1e-05 |
  | `          1.0E-05` | 0.0 | **1e-05** | 0.0 |

  `1.000000E-05` is simply how a 1e-5 is normally written and it is **12
  characters**, so fixed slicing truncated it to `'1.000000E-'` and
  `to_float` (`parser.py:358`) defaulted the wreckage to `0.0` — which is
  indistinguishable from "this output was never requested". The requested
  output was then never written, and nothing said so. The last row is the
  opposite trap and the reason "just use free format everywhere" is not the
  fix: DT is genuinely blank there (output driven by `LCDT` in field 2) and a
  free split returns field 2's value as though it were DT. On
  `*DATABASE_BINARY_D3PLOT` the same truncation set the animation interval to
  0, so the writer fell back to `endtim/40` instead of the interval the deck
  asked for.

  Now ONE rule for the family, in `_db_fields` (`handlers.py:2296`): a comma
  means free format outright; otherwise read fixed columns and fall back to a
  free split **only** when field 1 is non-empty and does not parse as a
  number — the signature of a line that is not actually column-aligned. A
  blank field 1 stays `0.0`, because that is what the deck says.
  `*DATABASE_BINARY_D3PLOT` now takes DT **and** `NPLTC` from that one
  reading, so two fields of the same card can no longer disagree about where
  its columns are. And `_numeric_or_none` (`handlers.py:2281`) lets
  "unreadable" be told from "the number 0", so an unparseable DT is now
  WARNED about with the offending token and the card line rather than
  defaulted to zero in silence. Same root pattern as #80: a handler that
  stores a value and returns is indistinguishable from one that converted
  something. Regression tests in `tests/test_database_dt_field_width.py`,
  including one that asserts every DT site reads a given line **identically**
  — each of the two old policies fails it, in its own direction.

- **`/TH/INTER` carried a hard-coded group id of `1`, colliding with
  `/TH/NODE/1` and killing the starter outright.** The `/TH` group id
  namespace is **global across `/TH` types**, not per type. Six independent
  builders emit `/TH` blocks and they did not share an allocator:
  `k2rad/writer/output.py:100` (`_make_starter_th`) numbers its blocks
  `1..N` from a local counter (`output.py:111`), while
  `_make_starter_th_node_reac` (`output.py:343`), `_make_starter_th_surf`
  (`output.py:389`), `_make_starter_th_node_spc` (`output.py:467`),
  `writer/inistate.py:699` (`/TH/SECTIO`) and `writer/loads.py:2191`
  (`/TH/RWALL`) all draw from `state.next_id()` (the 90001+ auto-id band).
  `_make_starter_th_inter` did neither — `output.py:308` emitted the literal
  `"/TH/INTER/1"`.

  So any deck requesting **both** a `*DATABASE_HISTORY_*` and a
  `*DATABASE_RCFORC` / `*DATABASE_NCFORC` / `*CONTACT_FORCE_TRANSDUCER` got
  `/TH/NODE/1` **and** `/TH/INTER/1`, and the OpenRadioss starter refused the
  whole model:

  ```
  ERROR ID :     79
  ** ERROR: DUPLICATE ID
  DESCRIPTION :
     IN TH GROUP DEFINITION
     ID=1 is DUPLICATED
   .. ERROR ==> NO RESTART FILE
  ```

  No restart file means the engine cannot run at all — yet `convert()`
  returned success with `0` skipped keywords and no warning, so the failure
  surfaced only as an unexplained solver error. The collision became
  reachable with PR #80, which made `*DATABASE_RCFORC` emit `/TH/INTER` for
  the first time; found on the fox-core RVE crush deck
  (`*DATABASE_HISTORY_NODE` for the monitor nodes plus `*DATABASE_RCFORC` for
  the platen contact force).

  `/TH/INTER` now draws from `state.next_id()` like every other `/TH`
  emitter. Because the *shape* of the bug is that a builder can be added
  without knowing about the other five, `build_starter` also gained
  `_warn_duplicate_th_group_ids` (`k2rad/writer/assembly.py`), which scans
  the **emitted deck** for repeated `/TH/<type>/<id>` headers and warns,
  naming the colliding blocks — a class fix rather than a point fix, so a
  seventh builder cannot reintroduce this silently. Ids are matched on whole
  lines: `/TH/INTER/1` is a prefix of `/TH/INTER/10`, so a substring test
  would pass on the unfixed code. Regression coverage in
  `tests/test_th_group_ids.py` (7 tests: the collision deck, the allocated-id
  band, and the guard driven directly, including the prefix case).

- **A `*CONTACT` whose secondary side is a rigid part was deleted from the
  model without a word.** `k2rad/writer/contacts.py:91-93`
  (`_resolve_contact_slave`) filters rigid-body nodes out of the secondary node
  group and returns `0` when nothing is left; `contacts.py:404` and
  `contacts.py:416` then guarded the emission with a bare
  `if slav_grnod and mast_surf:` — **no `else`, no `state.warn()`, no tally
  entry**. A contact whose SSID side is entirely rigid therefore vanished:
  no `/INTER`, no warning, and a conversion log still reading
  `skipped : 0 unsupported keyword(s)`.

  This is the same family as the three defects in PR #80 (a card is accepted,
  produces nothing, and success is reported) but strictly worse, because a
  missing `/INTER` changes the **physics** rather than the instrumentation.
  Found on a unit-cell crush model that put a rigid loading platen on the
  contact secondary side (`*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE`, Card 1
  `92 1 3 3` — SSID=92 the platen, MSID=1 the face plate): 5 `*CONTACT`
  keywords in, 3 `/INTER` out, both platen contacts gone. The run did not
  fail — the platen simply never touched the model. Force appeared only once
  the platen mid-surface reached the plate mid-surface (7.25 mm of dead
  travel), the reaction was then bit-identical across 30+ output states while
  internal energy climbed from 0.66 to 8682 mJ, contact energy exceeded
  external work, and the implicit solve diverged and died at 27-41 % of
  stroke. The k2rad log meanwhile reported only `skipped: DATABASE_RBDOUT`.

  **Behaviour chosen: warn and drop, never silently.** k2rad does *not* emit
  the interface with the sides swapped. LS-DYNA's SSID/MSID order is part of
  the model the user wrote — `/INTER/TYPE7` is an asymmetric node-to-surface
  contact, so swapping it changes which nodes are tracked, which surface
  supplies the segments, and therefore the contact forces. Silently rewriting
  that is the same class of defect as silently deleting it, in the opposite
  direction. So the interface is still not emitted, but the drop is now loud
  and counted:
  - **An actionable warning** naming the `*CONTACT` spelling and interface id,
    which side was emptied and by what (`ssid=`/`sstyp=`, how many nodes
    resolved, that all of them are rigid-body nodes), the **physical
    consequence** in plain words ("these two surfaces will NOT interact … the
    run does not fail: the reaction force simply stays flat … while internal
    and contact energy climb"), and the **concrete remedy** (put the
    deformable part on the SSID side, the rigid part on MSID) together with an
    explicit statement that k2rad will not do that rewrite for the user.
  - **Accounting**, through the `state.recognized_not_emitted` channel PR #80
    introduced for `*DATABASE_*`: one entry per `*CONTACT` spelling naming
    every lost interface id, so the log's summary now carries
    `not emitted: 1 recognized keyword(s) that produced no card` alongside
    `skipped : 0 unsupported keyword(s)`. `skipped: 0` can no longer coexist
    with a missing `/INTER`.

  **The pattern was fixed, not the one line.** Every path in
  `writer/contacts.py` that declines to emit an interface now routes through a
  single choke point (`_drop_interface` + `_note_dropped_interfaces`), which
  warns *and* registers the loss:
  - `_make_interfaces`, four previously **silent** sites: the surface-to-surface
    secondary side (the reported defect), the same shape on
    `contacts_single` with an explicit SSID, its **main** side resolving to no
    `/SURF`, the all-parts self-contact (`SSID=0`) with no deformable nodes or
    no parts, and the implicit self-contact whose `_make_master_surface` fails.
  - `_make_general_interfaces` (`SOFT=-7/-11/-19`) and `_make_tied_interfaces`
    already warned but were **never counted**; they now share the choke point,
    keeping the substrings the existing tests pin. The tied message gained the
    variant-specific remedy: a negative Card-3 `SST`/`MST` routes the tie to the
    penalty `/INTER/TYPE10`, which *does* accept rigid-body secondary nodes.
  - `_make_force_transducers`'s three skips are counted too (as
    `*CONTACT_FORCE_TRANSDUCER`), with instrumentation wording rather than the
    physics one — an `/INTER/SUB` adds no stiffness.
  - A **partially** rigid secondary side was the same silent edit in miniature:
    the filter quietly thinned the `/GRNOD` and the interface was emitted
    anyway. The emitted cards are deliberately unchanged, but the removal is
    now warned (`_warn_partial_rigid_secondary`).

  Mechanically, `_resolve_contact_slave` gained an optional `diag` out-dict
  (`raw` / `rigid_removed` / `clean`) so a caller that gets `0` back can tell
  *"SSID names nothing"* from *"SSID is a rigid platen"* — different mistakes
  with different remedies, and returning a bare `0` for both is exactly how the
  drop stayed invisible. `ContactAutoSingle` / `ContactAutoSurf2Surf` gained a
  `keyword` field (default `""`, set from `block.keyword` in `handlers.py`) so
  the tally names the user's actual `*CONTACT` spelling instead of a guess.

  **No emitted card changes.** The starter/engine output is byte-identical for
  every deck that already converted: the only new code paths are warnings and
  tally entries, and the drop conditions themselves are untouched. Verified —
  all 6 golden fixtures pass unchanged and none of the five decks in
  `tests/fixtures/` moved (`tests/fixtures/rigid_contact.k` already writes the
  deformable part as SSID and the rigid part as MSID, which is why no golden
  ever exercised this path). New `tests/test_contact_silent_drop.py`
  (11 cases); against the pre-fix writers 8 of them fail (5 failures,
  3 errors) and all 11 pass after. Full suite 993 tests, OK;
  `python -m ruff check .` clean.

- **3-node shells silently missing from `/SECT` cross-sections and `/TH`
  time histories.** Follow-on exposure from the `/SH3N` work in d1ade12
  (PR #76): once a 3-corner `*ELEMENT_SHELL` became a real `/SH3N` element
  instead of a collapsed 4-node `/SHELL`, every writer that puts shell
  element IDs into a *group* had to start splitting that list by topology.
  Two did not, and both failed silently — a `/SH3N` ID placed in a 4-node
  container is simply not resolved, so the group comes up short with no
  starter error and no k2rad warning:
  - `k2rad/writer/inistate.py:651-663` (`_make_cross_sections`) put the whole
    cut shell set into a `/GRSHEL/SHEL` referenced by `grshel_ID`, and passed
    a hard-coded `0` for `grtria_ID`. Every triangle a
    `*DATABASE_CROSS_SECTION_PLANE`/`_SET` cut therefore contributed **no
    force** to the section, quietly under-reporting SECFORC. The cut set is
    now split: quads into `/GRSHEL/SHEL` (`grshel_ID`), triangles into a new
    `/GRSH3N/SH3N` wired to `grtria_ID` (`_emit_grsh3n`, `writer/common.py`).
    The docstring at `inistate.py:568-570`, which asserted "All shells this
    converter emits are 4-node `/SHELL` (triangles are degenerate quads), so
    shell sets go into `grshel_ID`; `grtria` stays 0", had been false since
    d1ade12 and is corrected.
  - `k2rad/writer/output.py:105` (`_make_starter_th`) mapped
    `*DATABASE_HISTORY_SHELL` → `/TH/SHEL` unconditionally; `/TH/SHEL`
    records only 4-node `/SHELL`, so a named triangle never reached the T01.
    Shell history requests are now split, triangles going to `/TH/SH3N`. An
    all-quad or all-triangle request still emits exactly one block — no empty
    `/TH` block (a reader error) is produced.

  Both sites share one helper, `_split_shell_eids_by_topology`
  (`writer/common.py`), which derives topology from `state.shell_elems` using
  the *identical* test `_make_parts` uses to choose `/SHELL` vs `/SH3N`
  (`len(_ordered_unique_nodes(e.nodes))`: `>=4` quad, `==3` triangle, `<3`
  dropped as zero-area), rather than re-deciding from the raw node count — so
  the group split and the element emission cannot drift apart. This covers
  both LS-DYNA spellings of a triangle (3 IDs with a blank N4, and the
  collapsed quad `n1 n2 n3 n3`). IDs naming no known shell are left in the
  quad list, preserving the previous pass-through behaviour rather than
  silently discarding a caller's ID.

  Verified on a 2-quad + 1-triangle plate (element 3 written as the collapsed
  quad `3 6 7 7`) cut by a `*DATABASE_CROSS_SECTION_PLANE` at x=15 and named
  together with both quads in a `*DATABASE_HISTORY_SHELL`. Before: element 3
  appeared in `/GRSHEL/SHEL/90003` alongside quad 2 with `grtria_ID = 0`, and
  in `/TH/SHEL/1` alongside elements 1 and 2. After: `/GRSHEL/SHEL/90003` =
  `[2]`, `/GRSH3N/SH3N/90004` = `[3]`, `/SECT/90001` carries
  `grshel_ID = 90003, grtria_ID = 90004`, and the history splits into
  `/TH/SHEL/1` = `[1, 2]` + `/TH/SH3N/2` = `[3]`. New regression tests in
  `tests/test_sh3n_groups.py` (13 cases) pin all of this; 6 of them fail
  against the pre-fix writers. No golden fixture moves — none of the five
  decks in `tests/fixtures/` contains a shell with fewer than 4 distinct
  corners, so no golden exercised this path (which is why the regression went
  unnoticed).

- **Requested time-history outputs that were accepted and then silently
  dropped.** Three defects with one shape: the converter takes a `*DATABASE_*`
  card the user wrote to request an output, emits nothing for it, and reports
  success. Reproduced against a 2-shell deck (`*CONSTRAINED_NODAL_RIGID_BODY_SPC`
  + `*DATABASE_SPCFORC` + `*DATABASE_RCFORC` + `*DATABASE_MATSUM`), whose
  starter previously contained a `/BCS` and no `/TH` block whatsoever while the
  log read `skipped : 0 unsupported keyword(s)`.
  - **`*CONSTRAINED_NODAL_RIGID_BODY_SPC` + `*DATABASE_SPCFORC` produced no
    reaction history, and the warning explaining why was false.** The CNRB
    `_SPC` option is a *second, independent* source of `/BCS`: `writer/rbody.py`
    writes that card inline on the rigid body's master node, whereas
    `state.bcs_spcs` is populated only from `*BOUNDARY_SPC_*`
    (`handlers.py:1636`). Both reaction consumers — the `/TH/NODE` `REAC*`
    emitter (`writer/output.py`) and the engine `/ANIM/VECT/FREAC` gate
    (`writer/assembly.py`) — tested `state.bcs_spcs` alone, so a deck whose only
    constraint came from the `_SPC` option got no reaction output *and* was told
    *"the deck has no `*BOUNDARY_SPC` — no node is SPC-constrained"* — six lines
    after the converter itself emitted the `/BCS`. A user reading that goes
    hunting for a constraint that is not missing. The CNRB `_SPC` constraint is
    now recorded in a new `state.cnrb_spc_bcs` (a `CnrbSpcBc` per emitted card,
    carrying the master node and the `tra`/`rot` masks as written), which both
    consumers read alongside `bcs_spcs`; the warning now names both sources and
    fires only when the deck really does SPC-constrain nothing. The constraint
    is deliberately **not** routed through `state.bcs_spcs`, because `_make_bcs`
    would then emit a duplicate `/BCS` for the same constraint — a regression
    test pins the card count at 1. **The emitted `/BCS` text is byte-identical**;
    the starter diff on the reproduction deck is purely additive
    (`/TH/NODE/90004` `REACX/Y/Z/XX/YY/ZZ` on master node 7, matching what the
    equivalent plain-CNRB + `*BOUNDARY_SPC_SET` control deck already produced),
    plus `/ANIM/VECT/FREAC` + `/MREAC` in the engine.
  - **`*DATABASE_RCFORC` was a complete no-op.** `state.db_rcforc_dt` was stored
    (`handlers.py:2332`) and referenced nowhere else in the package. It is now
    (a) part of the `/TFILE` frequency chain in `writer/assembly.py`, which
    already carried `nodout, elout, glstat, matsum, spcforc, ncforc, blstfor,
    rwforc, secforc` — a deck whose only output request was `rcforc` silently
    fell back to the 1e-3 default — and (b) mapped to `/TH/INTER` over every
    converted contact interface, which is the direct equivalent: LS-DYNA's
    `rcforc` is the per-contact force resultant, exactly what an OpenRadioss
    `/TH/INTER` channel carries. This reuses the emitter `*DATABASE_NCFORC`
    already drives (`writer/output.py`). A `*DATABASE_RCFORC` with no converted
    `*CONTACT` now warns instead of failing silently.
- **`skipped : 0 unsupported keyword(s)` no longer implies "everything was
  converted".** Only keywords with *no* registered handler reach
  `state.skipped_keywords`, so *"has a handler"* was standing in for *"is
  supported"* — and a handler that stores a `dt` and returns is indistinguishable
  from one that converts something. `*DATABASE_MATSUM` (`handlers.py:4771`) has a
  handler and emitted nothing, yet never appeared in any tally. New
  `state.recognized_not_emitted` channel (`note_recognized_not_emitted()`),
  reported in the conversion log and the CLI as *"Recognized but not emitted"*,
  with a per-keyword reason: `*DATABASE_MATSUM` (needs `/TH/PART`, which k2rad
  does not emit — per-part energy remains unavailable), `*DATABASE_NODOUT` /
  `*DATABASE_ELOUT` (k2rad writes `/TH/NODE` and `/TH/SHEL|BRIC|BEAM` only for
  entities a `*DATABASE_HISTORY_*` names), and `*DATABASE_GLSTAT` (no card is
  needed — OpenRadioss writes the global energy balance to the `.out`/T01
  automatically, so the data *is* produced). These are reported *in addition to*,
  not reclassified out of, `skipped_keywords`, and a `dt` of 0 — which disables
  the output in LS-DYNA — is not reported, since nothing was requested. Note
  that the earlier audit blamed `_NO_ID_KEYWORDS` (`writer/assembly.py`) for
  this; that list belongs to the deck-assembly / id-collision module and also
  contains `DATABASE_SPCFORC` and `DATABASE_NCFORC`, which *are* implemented —
  patching it would have been the wrong file.

- **`*CONTROL_TIMESTEP` `TSSFAC` was silently dropped whenever `DT2MS` >= 0.**
  `TSSFAC` only ever reached the engine deck as the `Tsca` field of the
  `/DT/NODA/CST/0` (or `/DT/AMS`) card that `DT2MS` < 0 emits
  (`k2rad/writer/assembly.py:637-676`). With `DT2MS` = 0 or > 0 — no mass
  scaling requested, which is the common case — that branch returns early and
  **no `/DT` card of any kind was written**, so the user's requested time-step
  safety factor vanished without a warning and OpenRadioss silently ran at its
  own default `Tsca`. Reproduced on a minimal deck with `TSSFAC=0.8, DT2MS=0`:
  the whole engine file contained no `/DT` line. `TSSFAC` is LS-DYNA's scale
  factor on the computed critical time step (`dt = TSSFAC * dt_critical`) and
  `Tsca` on the plain OpenRadioss `/DT` card is the identical quantity, so the
  mapping is one-to-one and is now emitted as such:

      /DT
                       0.8                   0

  Deliberate boundaries, so the fix stays a faithful mapping and nothing else:
  - `Tmin` = 0 (no lower bound). `/DT`'s `Tmin` is a run-**stop** threshold, and
    LS-DYNA's counterpart `TSLIMT` is a field `handle_control_timestep`
    (`k2rad/handlers.py:2059-2066`) does not parse — it reads only `dtinit`,
    `tssfac`, `dt2ms`. Inventing a floor would stop runs, or delete elements,
    that the user never asked to stop or delete. **No `/DT/.../DEL` deletion
    floor is added here**; that is a separate design decision.
  - `TSSFAC` = 0 emits nothing. That is LS-DYNA's "use my default" (0.9), which
    is also OpenRadioss's `/DT` default, so there is nothing to carry across.
  - Implicit and modal decks are excluded, as before (no CFL step to scale).
  - **A deck with no `*CONTROL_TIMESTEP` converts byte-for-byte as before** —
    still no time-step card at all. Pinned by a test, along with the unchanged
    `DT2MS` < 0 → `/DT/NODA/CST/0` and `--ams` → `/DT/AMS` paths.

  Note for anyone re-reading the older audit that prompted this: `DT2MS` < 0
  **already worked**, and still does. Verified on `DT2MS=-1.0E-6, TSSFAC=0.8`
  → `/DT/NODA/CST/0` with `Tsca` 0.8, `Tmin` 1.0E-06, plus its warning. The
  deck that motivated the audit simply had `DT2MS=0`, which is exactly the hole
  fixed above. No golden fixture uses `*CONTROL_TIMESTEP`, so no golden moves.
  Regression tests: `tests/test_control_timestep.py` (10 tests).

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
