# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Prior history (before this changelog was introduced) is summarized in the
`git log` — each keyword conversion and bug fix landed as its own commit / PR.

## [Unreleased]

### Added

- **Discrete spring/damper + discrete-beam materials batch**
  (`*MAT_SPRING_ELASTOPLASTIC` S03, `*MAT_DAMPER_NONLINEAR_VISCOUS` S05,
  `*MAT_SPRING_GENERAL_NONLINEAR` S06, `*MAT_SPRING_INELASTIC` S08;
  `*MAT_LINEAR_ELASTIC_DISCRETE_BEAM` 066, `*MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM`
  067, `*MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM` 068, `*MAT_CABLE_DISCRETE_BEAM`
  071, `*MAT_ELASTIC_SPRING_DISCRETE_BEAM` 074,
  `*MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM` 119,
  `*MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM` 121,
  `*MAT_GENERAL_SPRING_DISCRETE_BEAM` 196; plus `*MAT_069`/`070`/`093`/`094`/
  `095`/`097`/`146` as recognised-but-unmappable) — the roadmap P1 "Discrete
  spring/damper + discrete-beam mats" item. **All were `SKIPPED` before**, and
  an `ELFORM=6` `*SECTION_BEAM` only warned that the `/PROP/BEAM` k2rad wrote
  from it would be refused with starter `ERROR 314-317`. Numeric aliases
  (`MAT_S03`/`S05`/`D02`/`S06`/`S08`, `MAT_066`/`66` … `MAT_196`) and
  `*INCLUDE_TRANSFORM` offset specs registered for every spelling, including a
  bespoke walker for `*MAT_196`'s repeating card PAIRS (its curve ids sit on the
  second card of each pair, so a flat `data` spec would offset the DOF/TYPE
  integers too) and the `*SECTION_BEAM` card-2f `CID` under `IDDOFF`.

  **The batch's defining decision: k2rad emits the PROPERTY-driven twin of
  dyna2rad's material-driven pair.** dyna2rad sends every one of these to
  `/PROP/TYPE23` (SPR_MAT) plus `/MAT/LAW108` (SPR_GENE) or `/MAT/LAW113`
  (SPR_BEAM), switching on `SCOOR = ±2` (`convertmats.cxx:3359-3376`, the same
  17-line block copied into `p_ConvertMatL66/67/68/119/121`). The card BODY of
  LAW108 is byte-identical to `/PROP/TYPE8`'s six DOF blocks and LAW113's to
  `/PROP/TYPE13`'s, with an absolute `Mass`/`Inertia` in place of `RHO` and
  TYPE23's `Volume`; the orientation is the same both ways (`rinit3.F:703` sends
  TYPE23+LAW108 and TYPE8 to the same frame builder `R2BUF3`, TYPE23+LAW113 and
  TYPE13 to `R4BUF3`). The property route additionally sidesteps TYPE23's own
  rules — `hm_read_part.F` makes a `MID = 0` on a TYPE23 part `ERROR 179` and a
  law other than 108/113/114/135 `ERROR 1715` — because TYPE4/8/13 need no
  material at all, so every connector `/PART` is written with `mat_id 0`, the
  pattern the MAT_100 spotweld connectors already use.

  **The one place the two routes genuinely differ, measured in the starter
  source: `A`.** `/PROP/TYPE4`, `/PROP/TYPE8` and `/PROP/TYPE13` all store the
  stiffness as `K / A` (`hm_read_prop04.F:249`, `hm_read_prop08.F:282,410,537,
  667,794,922`, `hm_read_prop13.F:295,450,605,777,930,1083`), which exactly
  cancels the `·A` the engine applies in the no-function branch of
  `redef3.F90:1148`. `/MAT/LAW108` stores `XK` raw (`hm_read_mat108.F:271`) and
  does NOT cancel. So dyna2rad's `A1 = 1e-20` trick for `*MAT_S04`'s `LCR`
  (`convertprops.cxx:974`, which makes `F = f(δ)·[A + E·g] ≈ f·g`) is a LAW108-
  only device: written on a property-driven spring it would multiply the
  time-step stiffness by 1e20 and collapse `dt` at cycle 0. `LCR` therefore
  stays warn-dropped, now saying exactly that, and the per-element force scale
  `S` on a nonlinear spring pre-multiplies `K` by `S²` so the stored `K/A` is
  the true scaled tangent `S·K` (it used to store `K/S`, understating the
  time-step stiffness by `S²`).

  - **`*MAT_SPRING_ELASTOPLASTIC` (S03) → `/PROP/TYPE4` `K1 = K`, `H1 = 1`**
    plus a synthesized symmetric 5-point elastic-plastic `/FUNCT`
    `(-(FY/K+1), -(FY+KT)) (-FY/K, -FY) (0,0) (FY/K, FY) (FY/K+1, FY+KT)` —
    dyna2rad's shape (`convertprops.cxx:914-935`), i.e. an elastic branch of
    slope `K` to the yield force and a plastic branch of slope `KT` carried one
    displacement unit past yield (Radioss extrapolates the last segment). A
    blank or non-positive `K`/`FY` is warn-skipped instead of producing the
    `inf`/`NaN` abscissae dyna2rad's unguarded `FY/K` gives.
  - **`*MAT_DAMPER_NONLINEAR_VISCOUS` (S05) → `fct_ID41 = LCDR`**, the `h(δ̇)`
    additional-damping-force slot, with `Hscale1` left 0 (reader default 1.0) —
    LS-DYNA's `F = LCDR(δ̇)` exactly. `K`/`C` stay 0; the whole force comes from
    the function. dyna2rad also sets `destCard = "/PROP/TYPE8"` on this branch
    (`convertprops.cxx:989`), which has no effect at all — the TYPE23 was
    already instantiated 130 lines earlier.
  - **`*MAT_SPRING_GENERAL_NONLINEAR` (S06) → `fct_ID11 = LCDL`,
    `fct_ID31 = LCDU`, `H1 = 6`.** `H=6` with a blank `fct_ID31` is starter
    `ERROR 1057` (`hm_read_prop04.F:171`, and the identical guard in
    `hm_read_mat108.F`), so a missing `LCDU` DEMOTES the flag to `H=0` with a
    warning rather than shipping a deck that cannot start — dyna2rad writes
    `H=6` unconditionally. `BETA`/`TYI`/`CYI` are warn-dropped naming what each
    means; Radioss's kinematic flag `H=4` is deliberately never emitted (it is
    `ERROR 230` on LAW108/113 unconditionally and on TYPE4 whenever `K=0`).
  - **`*MAT_SPRING_INELASTIC` (S08) → `K1 = KU`, `H1 = 1`, `fct_ID11` = the
    mirrored `LCFD`.** `LCFD` is defined in the POSITIVE quadrant only whatever
    the tension/compression sense, so it is reflected per `CTF` (`-1` tension
    only → prepend `(-1, 0)`; `+1` compression only, the LS-DYNA default →
    reflect through the origin and close with `(+1, 0)`), reproducing
    `HandleCurveLCFD` (`convertprops.cxx:1066-1128`). **`H1 = 1` is a
    deliberate deviation:** LS-DYNA S08 unloads along `max(KU, max loading
    slope)`, which is precisely Radioss `H=1`; dyna2rad never sets the flag
    (`convertprops.cxx:1000-1028`), leaving an INELASTIC spring converted as a
    nonlinear ELASTIC one that dissipates nothing. A blank `KU` demotes back to
    `H=0` with a warning, because there would be no slope to unload along.
  - **`*SECTION_DISCRETE` `DRO=1` (torsional) is now converted.** It used to be
    a warn-and-skip. `/PROP/TYPE4` is purely translational, so the payload moves
    to local DOF 4 (Rx) of a 6-DOF property: `/PROP/TYPE13`, whose local X is
    `node1→node2` by construction (`r4buf3.F:145`), so the torsion acts about
    the element's own axis; or DOF 4 of the oriented `/PROP/TYPE8` when the
    element carries a `*DEFINE_SD_ORIENTATION`, whose skew's local X IS the
    orientation axis. LS-DYNA already states a `DRO=1` spring in moment per
    radian, so nothing is rescaled — only the DOF changes, which is also all
    dyna2rad does (`(lsdDRO == 0) ? "K1" : "K4"`, and it never touches DOF 5/6
    either). Zero-length and grounded (`N2=0`) torsional elements are
    warn-skipped: there is no axis to twist about, and `r4buf3.F` answers
    `WARNING 325`. `KD`/`V0` (the `F=(1+KD·V/V0)·F_static` dynamic
    magnification) and `CL` (clearance, which makes the LS-DYNA spring
    compression-only with `CL` of free travel first) now warn INDIVIDUALLY and
    name what the converted spring does instead; dyna2rad drops `KD`, `V0`,
    `CL`, `FD`, `CDL` and `TDL` silently (grep-verified over its whole tree).

  **Discrete beams — `*SECTION_BEAM` `ELFORM=6`.** The section's card 2f
  (`VOL INER CID CA OFFSET RRCON SRCON TRCON`, Manual Vol I R17 p.41-20) is now
  read; `SectBeam.cfg`'s `COMMENT` mislabels fields 4/5 as `DOFN1`/`DOFN2` (that
  is card 2g, the `*MAT_146` dialect) while its `CARD` spec binds `LSD_CA` /
  `LSD_OFFSET`, which is what the manual says and what k2rad reads. Card 1's
  `SCOOR` is read too. The part is claimed by a new connector writer
  (`k2rad/writer/dbeam.py`), so it never reaches `_make_properties` — an
  `ELFORM=6` section states no cross-section at all, so its `/PROP/BEAM` is
  `ERROR 314` (AREA), `315` (IYY), `316` (IZZ) and `317` (IXX). The section is
  suppressed by the same `spotweld_only_secids` construct the ELFORM-9 welds
  use, and the parts join the `_warn_beam_type3_material` exclusion set, so a
  discrete-beam part is no longer reported as "no `/MAT` at all".

  **Frame rule (stated positively rather than as dyna2rad's law switch).**
  `|SCOOR| = 2` means "node 1/2 rotates AND the r-axis is realigned along
  n1→n2" — that IS `/PROP/TYPE13`, it is what `*MAT_066/067/068/196` require for
  a finite-length discrete beam, and it is exactly the test dyna2rad makes to
  pick LAW113. Otherwise a resolvable `CID` gives a real triad →
  `/PROP/TYPE8` with that `/SKEW`. Otherwise `/PROP/TYPE13` again, **with a
  warning**, because a TYPE8 with no skew falls back to the GLOBAL axes —
  dyna2rad's `convertprops.cxx:1471` leaves `skew_ID` 0 whenever the CID does
  not resolve and the local frame is silently lost. `*MAT_071` and `*MAT_074`
  are always TYPE13 (both act along the element), matching dyna2rad's
  unconditional LAW113. A `CID` that names no converted
  `*DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR` is warn-dropped rather than written
  (an unresolved `skew_ID` is `ERROR 137`).

  **Mass model.** `Mass = RO·VOL` (LS-DYNA's `Imass=2` equivalent), except the
  cable, which is `RO·CA` with `Ileng=1` — `rinit3.F:408-412` makes the TYPE8/13
  `Mass` field a mass PER UNIT LENGTH when `Ileng > 0`, so `RO·CA·L` comes out
  right and the stiffness and curve abscissae become strains, which is what a
  cable wants. `INER = -1` ("compute it as a solid sphere of volume VOL") is
  resolved exactly, `INER = -2` ("pick it so the rotational time step matches
  the translational one", `*MAT_196` only) as the lumped `m·L²/12` with a
  warning. `OFFSET`, `RRCON`, `SRCON` and `TRCON` are warn-dropped naming what
  each does; dyna2rad drops them silently.

  - **`*MAT_066` → K1..K6 = `TKR TKS TKT RKR RKS RKT`, C1..C6 =
    `TDR … RDT`** (`p_ConvertMatL66`, CM:3352-3481 — `r,s,t → 1,2,3` and
    `4,5,6` straight through, no axis swap anywhere in the family). A non-zero
    preload becomes a 2-point stiffness function `(0, P) (1, K+P)` whose
    y-intercept IS the preload; a zero preload creates no curve, so `FOR…MOT`
    are only lost where they are already zero.
  - **`*MAT_067` → `fct_ID1i = LCIDTR…LCIDRT`, `fct_ID4i = LCIDTDR…LCIDRDT`**
    with `Hscale_i = 1` on the damped DOFs (`p_ConvertMatL67`, CM:3483-3707). A
    loading curve that starts at `x ≥ 0` is extended by ODD symmetry into the
    third quadrant (Radioss reads a spring function over the whole deformation
    range and extrapolates its end segments), and a preload is added to every
    ORDINATE — dyna2rad puts MAT_068's and MAT_196's preload on the ABSCISSA
    instead, a 7-argument `CreateCurve` call where the 8-argument one was meant
    (`convertmats.cxx:3827`, `:6603`), which shifts a displacement by a force.
    **`K` is taken from the slope of the loading curve at the origin**: MAT_067
    states no stiffness, and a `K=0` spring contributes nothing to the explicit
    time step (`r1len3.F:81-105` only fills `STI` when `XK` or `XC` is
    non-zero); with `H=0` the force still comes entirely from the function, so
    `K` is free to carry the tangent. dyna2rad leaves it 0.
  - **`*MAT_068` → MAT_066's K/C plus `LCPDR…LCPMT` on `fct_ID1i` with
    `H_i = 1`** (`p_ConvertMatL68`, CM:3709-3887). The curve abscissae are
    PLASTIC displacement and gain the elastic part `F/K` to become the TOTAL
    displacement Radioss reads, then are mirrored through the origin
    (`ConvertPlasticDispPointsTotalDisp`, CM:8862-8921). Only emitted where the
    DOF has a stiffness, since the conversion divides by it. dyna2rad's absolute
    `+0.01` monotonicity patch is a unit-dependent magic number; k2rad uses a
    `1e-9` tie-break instead. `RYLD` (card 2 cols 61-70, `Keyword971_R12.0` only)
    is read and warn-dropped.
  - **Failure criteria.** `*MAT_067` prefers the DISPLACEMENT limits
    (`UFAIL*`/`TFAIL*`) and `*MAT_068` the FORCE ones (`FFAIL*`/`MFAIL*`) — a
    real dyna2rad inconsistency (CM:3680 vs :3848) that k2rad keeps, because it
    is each material's documented behaviour. What k2rad does NOT keep is 067's
    detection test: dyna2rad checks `sum > 0` there, so mixed-sign entries can
    cancel and suppress the whole failure block, while 068 checks `any ≠ 0`;
    k2rad always checks "any non-zero". Limits are written as `(-|v|, +|v|)`,
    not dyna2rad's `(-v, +v)` — the CFG constrains `MIN_RUP <= 0` and a negative
    input would otherwise invert its own interval. `Ifail = 1`
    (multi-directional) on 067/068/119, `Ifail2 = 1` for displacement and `2`
    for force.
  - **`*MAT_071` (cable) → a TENSION-ONLY `/PROP/TYPE13` DOF 1 with
    `Ileng = 1`.** `E < 0` means the value already IS the stiffness; `E > 0`
    gives `K = E·CA` with `CA` from the section's card 2f (dyna2rad reads that
    `CA` into an UNINITIALISED local, `convertmats.cxx:4156`). The force
    function is `(-1,0) (0,0) (1,K)` — flat in compression, so the cable goes
    slack. **The pretension is applied as a shifted SLACK POINT, not a plain
    ordinate offset**: LS-DYNA's law is `F = max(F0 + K·strain, 0)`, so the flat
    branch has to end at `strain = -F0/K`; dyna2rad's `Fshifty = F0`
    (`convertmats.cxx:4205`) loses the `max` and leaves the cable PUSHING with
    `F0` in compression. A user `LCID` is shifted and then clamped at zero with
    the exact crossing inserted. `TMAXF0 ≠ 0` (time-limited pretension) drops
    the offset entirely, as dyna2rad does — a Radioss spring carries it for the
    whole run or not at all. `TRAMP` and the `IREAD > 0` card 2
    (`OUTPUT/TSTART/FRACL0/MXEPS/MXFRC`) are warn-dropped.
  - **`*MAT_074` → `K→K1`, `D→C1`, `-|CDF|→DeltaMin1`, `TDF→DeltaMax1`,
    `FLCID→fct_ID11`, `HLCID→fct_ID21`, `C2→B1`, `C1→E1`, `DLE→D1`.** Two
    dyna2rad defects are not reproduced: it maps `D` to the cfg ATTRIBUTE `C1`,
    which on LAW113 is the relative-velocity coefficient `c1` on the tail cards
    and not the damping (`convertmats.cxx:4345` — the exact trap its own author
    guarded against 100 lines earlier with `//DAMP1...DAMP6 are used because
    C1...C6 are variables in the cfg`), and it puts the whole `DLE`/`C1`/`C2`/
    `GLCID` block INSIDE `if (FLCID valid)`, so a blank `FLCID` silently loses
    the rate law. k2rad writes by COLUMN, so `D` lands in the damping column by
    construction, and the rate terms apply unconditionally. `F0` with no `FLCID`
    becomes a 3-point line of slope `K` through `(0, F0)`. `GLCID` is
    warn-dropped: dyna2rad writes it to a `fct_ID51` field that does not exist
    on LAW113 at any format version, so it is lost there too.
  - **`*MAT_119` → `fct_ID1i` loading / `fct_ID3i` unloading / `fct_ID4i`
    damping, `K1..3 = KT`, `K4..6 = KR`, `+UTFAIL*`/`-UCFAIL*`.**
    `IUNLD → H` is `0→0`, `1→6`, `2→7`, **`3→5`** — dyna2rad maps `3` only for
    `*MAT_121` (CM:6062) and leaves MAT_119's `IUNLD=3` springs purely elastic,
    though the LS-DYNA option means the same thing on both cards. A DOF whose
    unloading curve is absent or identical to its loading curve is written as
    nonlinear elastic with `fct_ID3i` cleared (dyna2rad's rule at CM:5795), and
    every remaining `H ∈ {5,6,7}` is guarded against the starter's hard errors
    (`231` / `1057` / `1058`) before the card is written. `IFLAG → Iequil` is
    NOT reproduced: LS-DYNA's `IFLAG` is a local-frame/strain formulation flag
    and Radioss's `Iequil` the force/moment equilibrium flag, so `IFLAG=2`
    (crushable-frame buckling, whose cards 9-15 no Radioss spring law can hold)
    and `IUNLD=2`'s card-15 unloading stiffnesses are reported instead. Card 5's
    `LCIDTE*` elastic-scale curves, `OFFSET`, `DAMPF` and `FCRIT` are
    warn-dropped naming what each does. Cards 9-15 are absent from the shipped
    `Keyword971/MAT/mat_119.cfg`, which also omits `FCRIT`; both are read from
    the manual's columns.
  - **`*MAT_121` → the 1-DOF flavour** (`K→K1`, `LCIDT→fct_ID11`,
    `LCIDTU→fct_ID31`, `LCIDTD→fct_ID41`, `UTFAIL→DeltaMax1`,
    `-UCFAIL→DeltaMin1`, `H1` from `IUNLD` with the same override and guards).
    `LCIDTE`, `OFFSET` and `DAMPF` are warn-dropped.
  - **`*MAT_196` → one card PAIR per active DOF, each filling the slot it
    names** (`K→Ki`, `D→Ci`, `C2→Bi`, `DLE→Di`, `C1→Ei`, `-|CDF|`/`+|TDF|`,
    `HLCID→fct_ID2i`, `FLCID→fct_ID1i`). `TYPE ≠ 0` (inelastic) runs the same
    plastic→total displacement conversion as MAT_068 **and sets `H_i = 1`** —
    dyna2rad never sets `H` here (CM:6549-6613), leaving an inelastic DOF
    converted as nonlinear elastic. It also reads `FLCID` with a FIXED index
    `(…, 0, 0)`, i.e. the first DOF's curve reused for every DOF; k2rad reads
    each pair's own. `MDFAIL` (0 = largest deflection/limit ratio over all DOFs,
    1 = separate tension/compression, 2 = combined) and `DOSPOT` are absent from
    the shipped `mat_196.cfg` — both are read from the manual's columns and
    warn-reported, since Radioss offers only `Ifail` 0/1 and the per-DOF limits
    are checked independently.
  - **`*MAT_069`/`070`/`093`/`094`/`095`/`097`/`146` are RECOGNISED and
    warn-dropped**, each naming the device the deck loses (the tabulated
    orifice/piston damper, the hydraulic+gas strut law, the 6-DOF elastic spring
    with per-DOF unloading, the 1-/6-DOF inelastic springs with yield offsets,
    the penalty-stiffness general joint — which should be a
    `*CONSTRAINED_JOINT_*` instead, k2rad's `/PROP/TYPE45` path — and the
    generalized 1-DOF spring between two arbitrary nodal DOFs). MID and `RO` are
    parsed so the connector still gets its real lumped mass; the `/PROP` and
    `/SPRING` are written with every DOF inert, so the run starts and the
    elements stay addressable. dyna2rad has no `case` for any of them: they fall
    to its `default:` branch, which builds the target card name by POINTER
    ARITHMETIC on a string literal (`convertutils.cxx:1011`, `const char* +
    unsigned`) and produces no usable `/MAT` — silently, because the
    unsupported-material error at `convertmats.cxx:530` is commented out.
  - **Element side.** `*ELEMENT_BEAM` on a discrete-beam part becomes a
    `/SPRING` row keeping the beam EID and the third node verbatim (dyna2rad
    `resize(2)`s the connectivity and DISCARDS N3 unless the `_ORIENT` option is
    used, `convertelements.cxx:171-231`); the family joins
    `_spring_eid_families`, so an id it shares with the `*ELEMENT_DISCRETE`,
    spotweld-beam or PLOTEL springs is reported before the starter answers
    `ERROR 79`. A node-oriented connector whose beams carry no third node warns
    that the axial DOF is still right but the shear/bending pair may be rotated
    about it.

  **Starter-validated, and two decisions the starter made for us.** A deck
  exercising every new path at once (S03/S05/S06/S08 springs, a `DRO=1`
  torsional spring, MAT_066 on `SCOOR=2`, MAT_119 on a `CID`, a MAT_071 cable,
  plus a real shell part) converts and runs `starter_win64` to **0 ERROR(S)**.
  Two of its warnings were k2rad's own and are now fixed:

  - `WARNING 506` "STIFFNESS VALUE IS NOT CONSISTENT WITH THE MAXIMUM SLOPE OF
    THE YIELD FUNCTION — THE STIFFNESS VALUE IS CHANGED" on the S06 spring.
    Under `H=6` `K1` IS the unloading stiffness, and the starter refuses to let
    it be smaller than the loading curve's steepest segment: it raises it
    silently, i.e. the hysteresis loop the deck runs was being chosen
    downstream. `K1` now comes from that same maximum slope. `*MAT_S04` keeps
    its slope-at-the-origin `K` (with `H=0`, `K` only feeds the time step — and
    changing it would move the Yaris/Camry canaries), and `*MAT_S08` keeps `KU`,
    because the starter applying its own rule to it reproduces LS-DYNA's
    `max(KU, max loading slope)` exactly.
  - `WARNING 432` "INERTIA OF SPRING SEEMS TO BE MASS AND LENGTH INCONSISTENT
    (REFERENCE INERTIA = MASS·LENGTH²)" on the torsional connector, which used a
    fixed `1e-6` token inertia. It now uses `mass·L²` from the elements' own
    geometry — the starter's own reference. An inertia that came from a
    `*SECTION_BEAM` `INER` is left alone: that is the deck's number, not one
    k2rad invents, and the same warning on it is then correct feedback about the
    deck.

  **Corpus census + sweep.** A structured scan of the 628 unique
  `.k`/`.key`/`.dyn`/`.inc` files across the repo, `E:\openradioss_run` (incl.
  `Ryan_Lee_Examples` and `ls-dyna_example`) and `E:\foxcore_data` finds **zero**
  hits for every keyword in this batch: no `*SECTION_BEAM` with `ELFORM=6`, no
  `*MAT_066/067/068/069/070/071/074/093/094/095/119/121/196`, and none of the
  `*MAT_S03/S05/S06/S08` spellings. The 201-deck byte-identity sweep (the 73
  repo decks, the 127-deck `Ryan_Lee_Examples` tree and the one
  `ls-dyna_example` deck) is therefore a **pure no-movement check**, and the
  only decks that can move at all are the Yaris and Camry, whose suspension
  springs are `*MAT_SPRING_ELASTIC` / `_NONLINEAR_ELASTIC` / `*MAT_DAMPER_VISCOUS`
  on `DRO=0` sections with blank `S`/`VID`/`OFFSET` — every field this batch
  touches is at its pre-existing default there. All the evidence is therefore in
  the 78 new column-exact tests plus the two byte-identity canaries in
  `tests/test_discrete_springs.py::ByteIdentityTests`.

- **Impact / blast materials batch** (`*MAT_JOHNSON_HOLMQUIST_CERAMICS` 110,
  `*MAT_JOHNSON_HOLMQUIST_CONCRETE` 111, `*MAT_ELASTIC_FLUID` 001+`_FLUID`) —
  the roadmap P1 "Impact/blast mats" item. All were `SKIPPED` before. Numeric
  aliases `MAT_110`/`MAT_111` registered, plus three spellings dyna2rad lacks:
  `MAT_001_FLUID` and `MAT_1_FLUID` (its `dynamatlawkeywordmap.h` has
  `*MAT_ELASTIC_FLUID` but not the numeric form, so there the keyword misses
  the map, falls into the broken `Convert1To1` fallback and produces **no
  `/MAT` at all** — part wired to `mat_ID=0`, starter `ERROR 3046`; its own
  `convertprops.cxx:331` does test both spellings, so the omission is an
  inconsistency, not intent) and the bare `MAT_001`/`MAT_1`, which k2rad
  previously dropped into `skipped_keywords`, leaving every referencing
  `/PART` without a material. `*INCLUDE_TRANSFORM` offset specs for every
  spelling — MID only, since every other cell on all three cards is a physical
  constant (no curve, table or set id anywhere in this family).

  **The batch's defining property: NOTHING is normalized on conversion.** Both
  Johnson-Holmquist laws state their strength surfaces in the same normalized
  form on both sides, and the Radioss starter/engine re-derive every
  normalizer with the identical definitions LS-DYNA uses — JH-2's
  `sigma_HEL = 1.5*(HEL-PHEL)` and `T* = T/PHEL` at `hm_read_mat79.F:211-213`,
  `P* = P/PHEL` and `sigma* = sigma_vm/sigma_HEL` at `sigeps79.F:153,190`;
  JHC's `P* = P/FC`, `sigma* = sigma_vm/FC`, `T* = T/FC` and the
  `sigy = fc*sigy` de-normalization at `sigeps126.F90:264,305,338,383`. So
  `A B C M N SFMAX EFMIN D1 D2 MUC MUL` pass through as the dimensionless
  numbers they are, and `HEL PHEL T FC PC PL G K1 K2 K3` as physical stresses.
  Pre-dividing `T` by PHEL/FC, or writing `sigma_HEL` into a stress slot,
  would apply the normalization TWICE and silently soften the material — this
  is the classic trap of the family and the reason dyna2rad copies all 18/21
  fields verbatim. `K1/K2/K3` are each law's OWN polynomial pressure law
  (`sigeps79.F:143-147`, LAW126 `uparam(14..16)`), so **no `/EOS` is emitted
  for either** — LAW126's `HYDRO_EOS` class tag is a pressure-treatment
  capability, not a request for a companion block, and an `/EOS` sharing the
  material id would be starter `ERROR 79`.

  - **`*MAT_JOHNSON_HOLMQUIST_CERAMICS` (110) → `/MAT/LAW79` (`JOHN_HOLM`)**
    (dyna2rad `p_ConvertMatL110`, CM:12491-12506 — 18 verbatim copies and
    nothing else; layout audited against `radioss120/MAT/matl79_79.cfg`
    `FORMAT(radioss120):207-236`, the newest LAW79 block a `/BEGIN 2022` deck
    reads — LAW79 is registered natively at 2022
    (`radioss2022/data_hierarchy.cfg:1301-1307`) so there is **no** version
    warning, and the layout is identical to the worked Al2O3 example in the
    Altair Radioss 2022 Reference Guide p.634). Card 1 is written with ONE
    density field: the CFG runs `CARD_PREREAD("%20s")` on cols 21-40 and any
    non-blank there switches it to the two-field `rho_i`/`rho_0` form. Two
    field-order traps handled: `*MAT_110` card 1 runs `… C M N` (M at field 7,
    N at field 8) while LAW79 card 3 runs `a b m n` with `c` moving to card 4,
    and `BETA` moves from LS-DYNA card 2 to the END of LAW79 card 7. Note
    `MAT_E`/`MAT_EPS` are the cfg SKeywords of the **HEL** and **PHEL** slots —
    legacy generic attribute names, not Young's modulus and strain.

    **`FS` is NOT EXPRESSIBLE at `/BEGIN 2022` and is warn-dropped.** LAW79's
    `IDEL`/`EPSMAX` live on the `FORMAT(radioss2023)` card 8 only; the
    `FORMAT(radioss120)` block a 2022 deck reads ends at `D1`/`D2`, and
    `Fcut` (card 4 field 4) is likewise 2023+. Emitting them anyway would draw
    `WARNING 100213` for fields the starter then discards, so the cards stop
    where the reader does and the criterion is reported instead — naming what
    it meant (`FS>0` → `IDEL=2` with `EPSMAX=FS`; `FS<0` → `IDEL=1`, deletion
    in tension, per `hm_read_mat79.F:275-280`), the `*MAT_ADD_EROSION` remedy
    (a `/FAIL` card, version-independent), the `/BEGIN 2023` alternative, and
    the fact that the tensile pressure cutoff `PMIN = -T*.PHEL.(1-D)` IS still
    applied at `IDEL=0` (`sigeps79.F:149-151`), so only element DELETION is
    lost. `FS=0` needs no warning: it is "no failure" in LS-DYNA and `IDEL=0`
    "no deletion" in Radioss — the default on both sides. dyna2rad drops
    MAT_110's `FS` **silently at every format version**, though the same
    converter implements the flag for MAT_111.

    **Note a defect in the reference material, recorded here because it is the
    kind that propagates:** the dyna2rad-semantics write-up's own
    reimplementation checklist proposes reusing MAT_111's three-way rule for
    MAT_110 (`FS<0 → IDEL 3`, `FS=0 → IDEL 1`). That is wrong for this law —
    both the LS-DYNA `FS` meanings and the Radioss `IDEL` enumerations differ
    between 110 and 111 (MAT_110 `FS<0` is "fail if p*+t* < 0" → LAW79 `IDEL 1`
    "tension only", and MAT_110 `FS=0` is "no failure" → `IDEL 0`, whereas
    MAT_111 `FS<0` is "damage strength < 0" → LAW126 `IDEL 3` "SIGY ≤ 0" and
    its `FS=0` is the tensile default → `IDEL 1`). Moot in the emitted deck
    since neither field is writable at 2022, but the warning states the
    semantically correct mapping and `tests/test_impact_mats.py` pins both
    rules against each other so a later `/BEGIN` bump cannot transplant one
    onto the other.

    **`PHEL` is the one field of the batch that is NOT copied verbatim**, and
    it is the one place where "copy the number on the card" is the wrong rule:
    a blank/zero `PHEL` is a DOCUMENTED LS-DYNA input mode, not a defective
    card. Vol II R16 p.2-763 — *"Given HEL and G, μ_hel can be found
    iteratively from `HEL = k1·μ + k2·μ² + k3·μ³ + (4/3)·g·μ/(1+μ)`"*, then
    `P_hel = k1·μ + k2·μ² + k3·μ³` and `σ_hel = 1.5(HEL − P_hel)` — and
    p.2-764: *"These are calculated automatically by LS-DYNA if p_hel is zero
    on input."* `/MAT/LAW79` implements none of that: `hm_read_mat79.F:211`
    forms `UPARAM(10) = TMAX/PHEL` directly and the ONLY PHEL guard anywhere
    is `PHEL > HEL` (`ERROR 907`), so a copied-through 0 passes the starter
    with **0 ERROR / 0 WARNING** (measured: the `.out` echoes
    `PRESSURE AT HUGONIOT ELASTIC LIMIT = 0.000000000000`) and then leaves
    every `P*`, `T*` and `σ_HEL` at Inf or 0/0 for the whole run — which is
    exactly what a dyna2rad-converted deck does. k2rad reproduces LS-DYNA's
    own derivation instead: the smallest root of that equation in `(0, 1]` by
    scan + bisection (a scan, not Newton, so a negative `K2` cannot hand back
    a larger root), and emits the derived `PHEL`, reporting μ_hel, `PHEL` and
    `σ_HEL` in the warning. The derived value can never trip `ERROR 907`
    (`PHEL = HEL − (4/3)·G·μ/(1+μ) < HEL` for `G > 0`), a stated `PHEL` is
    never touched, and when the iteration cannot run (`HEL ≤ 0`, `K1 ≤ 0`,
    `G ≤ 0`, or no root below μ = 1) the original hard warning stands.
    Worked check, hand-solved independently in the test: `K1 = 130.95e9`,
    `G = 90.16e9`, `K2 = K3 = 0`, `HEL = 19e9` → μ_hel = 0.07837428750607,
    `PHEL = 1.0263112948920e10`, `σ_HEL = 1.3105330576620e10`.

    Guards the starter does not have, all warned: **`EPS0 ≤ 0` with `C ≠ 0`**
    is FATAL (`ERROR 910`) and a dyna2rad-converted deck walks straight into
    it; k2rad substitutes the rate-free value the starter itself uses when
    `C == 0` (`hm_read_mat79.F:159`), so the deck runs — the LS-DYNA card is
    equally undefined at `EPS0 = 0`. The substitution is **expressed in the
    deck's time unit**: `EPS0` is a 1/time quantity (Vol II R16 `*MAT_015`,
    which this card's `EPS0` refers to: *"input in units of [time]⁻¹ … if the
    system of units for the model input is {kg, mm, ms}, then EPS0 should be
    set to 10⁻⁵"*) and k2rad rescales nothing, so a bare `1.0` would be
    1000 s⁻¹ on a ton-mm-ms deck; and because `sigeps79.F:178-182` sets
    `CE = 1` for `ε̇ ≤ EPS0` (LAW126 the same at `sigeps126.F90:279`), an
    over-large `EPS0` switches rate hardening **off** across the range of
    interest rather than shifting its onset. The emitted value is
    `1 s⁻¹` converted into the deck's time label, parsed the way the starter
    parses `/BEGIN` itself (`unit_code.F:99-143`: at most three characters,
    last one `s`, leading one or two an SI prefix) — so `1.0` on the default
    Mg-mm-s deck, `1e-3` on ms, `1e-6` on µs, and the raw starter default for
    a label the starter would itself reject. `C == 0` with a zero `EPS0` is
    left alone (the starter fixes it and 910 never fires). `G ≤ 0`
    (`ERROR 908`), `K1 ≤ 0` (`ERROR 909`), `BETA` outside `[0,1]`
    (`ERROR 911`) and `PHEL > HEL` (`ERROR 907`) are reported with their ids.

  - **`*MAT_JOHNSON_HOLMQUIST_CONCRETE` (111) → `/MAT/LAW126`** (dyna2rad
    `p_ConvertMatL111`, CM:5639-5674; layout audited against
    `radioss2024/MAT/matl126_johnson_holmquist_concrete.cfg`
    `FORMAT(radioss2024):189-202` — the OLDEST block that exists for this law,
    so a `/BEGIN 2022` deck falls forward into it, including card 7's
    `%20lg%20lg%10s%10d%20lg` shape where `IDEL` is a 10-char INTEGER at cols
    51-60 after a 10-char blank run). Card 1 takes EXACTLY one density field —
    unlike LAW79 there is no `CARD_PREREAD` and no `Refer_Rho` attribute, so a
    second field is `WARNING 100213`. `*MAT_111` card 1 field 7/8 are `N` then
    `FC` where 110 has `M` then `N`, and LS-DYNA `UC`/`UL` are Radioss
    `MUC`/`MUL`. **Not LAW24 (`CONC`)** — that is Radioss's own smeared-crack
    concrete with a completely different card set.

    **`FS` → `IDEL`/`EPS_MAX` DOES work at 2022** (the fields are in the 2024
    format): `FS>0 → IDEL=2` + `EPS_MAX=FS`; `FS=0 → IDEL=1` (tensile
    `P*+T* ≤ 0` — LS-DYNA's default for THIS law, and writing it explicitly is
    required because LAW126's own blank default `IDEL=0` means no deletion);
    `FS<0 → IDEL=3` (`SIGY ≤ 0`). `EPS_MAX` carries `FS` verbatim including
    the meaningless negative value at `IDEL=3`, exactly as dyna2rad does — it
    is inert there (only `IDEL=2` reads it) and keeps the source value visible.

    **`WARNING 100211` is expected and warned about**: LAW126 is first
    registered in the radioss2024 profile (`radioss2022/data_hierarchy.cfg`
    has no LAW126 entry at all), so a 2022 deck draws one cosmetic
    "Unsupported option … in format < 2024" and is then parsed with the 2024
    FORMAT — the same trade-off `/MAT/LAW169` and `/MAT/LAW127` already ship
    under. Reported once per material so the starter listing does not read as
    a conversion defect. Real consequence of the gate: `IFAILSO` (post-failure
    stress handling) is a radioss2025 field, unreachable at 2022 and pinned to
    its clamped default 1 — dyna2rad never sets it either, so nothing is lost
    relative to that converter. `FCUT` is written blank (no rate filter) and
    the radioss2026 `CT/POWT/CC/POWC` card is not emitted.

    `hm_read_mat126.F90` contains **no ANCMSG check at all** — unlike LAW79,
    `G ≤ 0`, `K1 ≤ 0` and `EPS0 ≤ 0` all pass silently — so every diagnostic
    for this law comes from the converter. The two compaction divisions
    `k0 = PC/MUC` (`:140`) and `h = (PL-PC)/MUL` (`:146`) have **no zero
    guard**: `UC=0` yields an infinite region-1 bulk modulus and a NaN Young's
    modulus and Poisson ratio while the starter reports *0 ERROR / 0 WARNING*
    — a silent NaN, warned as such, and `UL=0` likewise. `EPS0 ≤ 0` with
    `C ≠ 0` is substituted with the starter's own `if (cc==zero) eps0=one`
    default rather than left to evaluate `C*log(eps_dot/0)` every cycle — in
    the deck's time unit, for the reason spelled out under LAW79 above
    (`sigeps126.F90:279` applies the rate factor only ABOVE `EPS0`).
    `G`, `K1` and `FC` at ≤ 0 are warned naming that the starter checks
    nothing — `FC` in particular is the JHC normalizer, so a zero makes the
    entire yield surface Inf/NaN. The derived Poisson ratio
    `(3*k0-2G)/(6*k0+2G)` is checked against `[0, 0.5)` and warned when a
    too-soft `PC/UC` pair against `G` drives it negative, which the starter
    prints without complaint.

  - **`*MAT_ELASTIC` `_FLUID` option (001) → `/MAT/HYD_VISC` (LAW6) +
    `/EOS/POLYNOMIAL` of the same id** (dyna2rad `p_ConvertMatL1_FLUID`,
    CM:12093-12136; LAW6 layout audited against `radioss2020/MAT/mat_law6.cfg`
    `FORMAT(radioss2018):318-326`, the newest LAW6 block a `/BEGIN 2022` deck
    reads, and the EOS against `radioss2022/MAT/mat_EOS.cfg`
    `FORMAT(radioss2022)`). The option is a SUBSTRING test on the keyword,
    exactly as both dyna2rad (`sourceCard.find("FLUID")`) and the LS-DYNA
    reader (`ASSIGN(MAT_OPTION,_FIND(TYPE,"_FLUID"),IMPORT)`) define it, so
    `*MAT_ELASTIC_FLUID_TITLE` is handled — the same one-handler-one-flag
    shape as MAT_224's `_LOG_INTERPOLATION`.

    **Kept in its own container, so the plain `*MAT_ELASTIC` path is
    byte-for-byte untouched**: `/MAT/ELAST`, its LAW1 entry in
    `_target_mat_law` and therefore its place on the starter's solid-`/XREF`
    law whitelist are unchanged, and no existing deck's `/XREF` decisions can
    move. (Asserted directly in `TestMat001BaseVsFluidSplit`, including that a
    card-1 `K` field on a non-FLUID `*MAT_ELASTIC` still does nothing.)

    **The `/EOS` is mandatory, not optional**: a 2-card LAW6 with no `/EOS`
    passes the starter with 0 errors and 0 warnings but leaves `IEOS = 0` and
    `PM(32) = C1 = 0`, i.e. zero bulk modulus and zero sound speed. The modern
    2-card form is emitted rather than the legacy embedded-EOS form (which is
    gated on the trailing free-card COUNT, `hm_read_mat06.F:105,113-116`,
    needs exactly 3 or exactly 0 trailing cards, and binds `Pmin` twice with
    the later value winning). `/EOS/POLYNOMIAL` is used where dyna2rad writes
    `/EOS/LINEAR`: the two express the same law — `P = C0 + C1*mu` with
    `C0 = 0` IS the linear form, and the 2022 Reference Guide p.1060 Comment 3
    confirms `C2`/`C3` are simply not evaluated for a linear volumetric
    material — but POLYNOMIAL is native to the radioss2022 profile this
    converter targets and is the block k2rad already emits for
    `*EOS_LINEAR_POLYNOMIAL`.

    `K` is card-1 field 7 (**not** a second card — the FLUID-only card 2
    carries only `VC` and `CP`) and becomes `C1`, with
    `C0 = C2 = C3 = C4 = C5 = E0 = Psh = 0`. **The `K == 0` fallback uses the
    REAL Poisson ratio**, `K = E/(3(1-2*PR))` — the relation the LS-DYNA
    manual itself states for this option (Vol II R16 p.2-148, Remark 5).
    dyna2rad's expression spells the token `NU` where the `mat_001.cfg`
    attribute is `Nu` (solver name `PR`), identifier lookup is case-sensitive,
    and an unresolved token silently becomes `"0"`
    (`convertutilsbase.cxx:192`), so it computes `E/3` and loses Poisson's
    ratio entirely — measured on a live starter as `BULK MODULUS = 1.0e9`
    where `E=3e9, PR=0.25` should give `2.0e9`. `K < 0` matches NEITHER of its
    two branches and leaves `B = 0`, a fluid with zero sound speed, silently;
    k2rad falls back to the same E/PR relation and warns. `PR ≥ 0.5` makes the
    fallback unusable — singular at 0.5, negative above it — and takes a
    branch of its own that reports the inert-fluid consequence WITHOUT quoting
    a derived value, since at that Poisson ratio the expression has none (the
    internal 0.0 there is a sentinel, not a result).

    **`VC` is DROPPED, not copied.** LS-DYNA's `VC` is a **dimensionless**
    tensor-viscosity coefficient scaling an artificial deviatoric stress
    `S'ij = VC*dL*a*rho*edot'ij` (dL the characteristic element length, a the
    bulk sound speed); the Radioss slot it lands in is `DAMP1`, a **true
    kinematic viscosity** with `DIMENSION="eddyviscosity"` (L²/T) entering as
    `sigma_dev = 2*rho*nu*edot_dev`. The factor `dL*a` between them is
    per-element and not knowable at material-conversion time, so dyna2rad's
    verbatim copy is wrong by orders of magnitude on any real mesh. k2rad
    writes `Nu = 0` and carries the hand-conversion recipe in the warning with
    `a = sqrt(K/rho)` already evaluated (`nu ≈ VC*dL*a = <number>*dL`). A zero
    `VC` needs no warning.

    **`CP` → `Pmin` with the sign flipped, but only when it is a real limit.**
    LS-DYNA's documented `CP` default is `1e20` = "no cavitation"
    (`mat_001.cfg:52`), and Radioss reads `Pmin = 0` as the sentinel for no
    cut-off (`hm_read_mat06.F:154  IF (PMIN == ZERO) PMIN = -INFINITY`), so an
    absent card 2, a blank `CP` cell and a defaulted `1e20` all map to `0` —
    **not** to `-1e20`. A finite `CP` becomes `-CP`; a negative one is
    sign-corrected and warned. An **explicit** `CP = 0.0` ("cavitate at zero
    pressure") is the one semantic the Radioss card cannot state and is
    reported as inexpressible with the small-negative-`Pmin` remedy — the
    handler tracks cell blankness (`cp_given`) precisely so blank and explicit
    zero can be told apart, which dyna2rad cannot do.

    The `1e20` default is a **raw literal**, so a magnitude test against it
    alone is unit-system dependent — and the corpus proves it on one material:
    `W11_SETUP_SPH_BirdStrike_Multi`'s "Head" fluid writes `K = 2.2e9` /
    `CP = 1.00000E20` in its kg-m-s copy and `K = 2200` / `CP = 1E+14` in the
    kunit-converted ton-mm-s copy — the same 1e20 Pa, the same physical
    material, one hitting the sentinel and one missing it. A `CP` at or above
    `1e6 × K` is therefore recognised as the default too: `Pmin = -CP` binds
    at a volumetric strain of `CP/K`, so such a cut-off is unreachable in
    either code, and 1e6 sits far above any physical cavitation pressure
    (which is at most a fraction of K). The substitution is warned with the
    measured ratio; with `K` unresolvable there is nothing to scale by and
    only the raw literal is still recognised. `E`/`PR` are otherwise
    dropped (LS-DYNA ignores them under FLUID and zeroes the shear modulus;
    LAW6 has no shear slot at all, so the pure-hydrodynamic response is exact
    rather than approximated) and `DA`/`DB` are beam-only damping.

  - **Solid-only enforcement, `_target_mat_law`, beam and REF classification.**
    None of LAW79 / LAW126 / LAW6 declares any `SHELL_*` class, so a shell
    part on any of them is starter `ERROR 3046` — warned per the PR #110
    pattern (keyword + mid + the offending pids + the exact declared class
    list + the reader file:line + the error id + a remedy), from a
    `_shell_parts_by_mid` map built ONCE per conversion. dyna2rad checks none
    of the three: its converters never look at the element type at all.
    `_target_mat_law` gains all three families (79 / 126 / 6); none is on
    `_XREF_SOLID_LAWS`, so `inistate._resolve_xref_parts` warn-skips such
    parts NAMING the law instead of misreporting "no `/MAT` at all". Neither
    beam frozenset changes — no `BEAM_*` keyword on any of them, so
    `PROP_BEAM` stays 0 and the existing "no beam keyword at all" message is
    already right; the `INIT_MAT_KEYWORD` grep audit is recorded in
    `writer/mesh.py` alongside the earlier batches, including the finding that
    **LAW6 declares `SOLID_POROUS`, not `SOLID_ISOTROPIC`** — both include
    `/PROP/TYPE14` so an ordinary solid part is fine, but LAW6 is NOT
    compatible with the orthotropic/composite solid properties TYPE 6/20/21/22
    (`ERROR 3047`) the way LAW79/LAW126 are. No `_ref_flag_materials` entries:
    none of `*MAT_110`, `*MAT_111` or `*MAT_ELASTIC(_FLUID)` carries a REF
    flag on any card — recorded in `writer/common.py` so the next batch does
    not re-derive it.

  **Corpus census + sweep**, `master` (b762de2) vs this branch. Census first:
  `*MAT_110` / `*MAT_JOHNSON_HOLMQUIST_CERAMICS` and `*MAT_111` /
  `*MAT_JOHNSON_HOLMQUIST_CONCRETE` have **zero hits anywhere** — not in the
  repo's `.k`/`.key`/`.dyn` decks, not in the 127-deck
  `E:\openradioss_run\Ryan_Lee_Examples` tree, not under `E:\foxcore_data\`.
  `*MAT_ELASTIC_FLUID` appears in exactly one deck — 5 copies of it:
  `Ryan_Lee_Examples/W11_SETUP_SPH_BirdStrike_Multi.k` in-repo, an identical
  copy on `E:`, and three `__ton-mm-s` unit-converted copies — as
  `*MAT_ELASTIC_FLUID_TITLE` "Head", a real bird-strike "bird as fluid"
  material and the source of this batch's realistic field values. The five
  split by unit system, and the split matters: the **2 SI (kg-m-s) copies**
  carry ρ=2600, E=8.5e8, ν=0.24, K=2.2e9, VC=0.0, **CP=1.00000E20**, while the
  **3 `__ton-mm-s` copies** carry ρ=2.6e-9, E=850, K=2200, VC=0.0 and
  **CP=1E+14** — the same 1e20 Pa, rescaled by the unit converter, which is
  precisely why the CP sentinel is tested against the bulk modulus and not only
  against the literal. `*MAT_001`/`*MAT_1` have zero hits, so registering those
  aliases moves nothing.

  The sweep is therefore a near-pure no-movement check, and measured over
  **201 decks** — the 73 `.k`/`.key`/`.dyn` decks in the repo, the 127-deck
  `E:\openradioss_run\Ryan_Lee_Examples` tree and the one
  `E:\openradioss_run\ls-dyna_example` deck — (`master` b762de2 vs
  `feat/impact-mats`, 0 exceptions on either side) it is exactly that:
  **196/201 byte-identical on BOTH `_0000.rad` and `_0001.rad`, with identical
  warning sets and identical skip lists**. Total warnings 2164 → 2172. The 5
  that moved are precisely the 5 W11 copies, and they
  moved only in the starter deck (`_0001.rad` unchanged — materials live in
  `_0000.rad` alone): `MAT_ELASTIC_FLUID` leaves `skipped_keywords` and a
  `/MAT/HYD_VISC/3` + `/EOS/POLYNOMIAL/3` pair appears where PART 8's material
  previously dangled. The 2 SI copies gain exactly one warning (the dropped
  E/PR); the 3 ton-mm-s copies gain two, the second naming the rescaled CP
  (`CP=1e+14 is 4.54545e+10 x the bulk modulus K=2200`). All five emit
  `Nu = 0` and `Pmin = 0` → `-INFINITY`, i.e. the **same** cavitation card
  regardless of units — the very case where dyna2rad would write a finite
  `Pmin = -1e20` (SI) or `-1e14` (ton-mm-s). That deck is a card-source, not
  an end-to-end validation case: its MID 3 sits on PART 8 → SECID 2 =
  `*SECTION_SPH`, and k2rad has no SPH path at all, so the part still has no
  property and the deck still cannot run.
  **What this corpus cannot see**: anything about the new cards
  themselves. That evidence is the column-exact tests plus the starter probes
  the card layouts were audited against — `/BEGIN` 2022/2023/2024/2025/2026
  round-trips that measured which fields each version actually reads (LAW79
  `Fcut`/`IDEL`/`EPSMAX` dropped with `WARNING 100213` below 2023; LAW126 read
  at 2022 under `WARNING 100211`; LAW126 `IFAILSO` dropped below 2025) and
  field-by-field `.out` echoes for the SI values used throughout the tests
  (LAW79: derived `E = 219991445311.7`, `nu = 0.22000579…` from `K1`/`G`;
  LAW126: `IDEL = 2`, `EPS_MAX = 0.30`, `IFAILSO = 1`, `K0 = PC/MUC = 16e9`;
  LAW6: `VISCOSITY 0.1`, `PRESSURE CUTOFF −1000000`, `BULK MODULUS 2.2e9`) —
  and, for the `PHEL` derivation, an end-to-end starter run: the same card
  with a blank `PHEL` echoes `PRESSURE AT HUGONIOT ELASTIC LIMIT =
  0.000000000000` at *0 ERROR / 0 WARNING* before the fix and
  `= 10263112950.00` after it, both NORMAL TERMINATION.

  **Robustness.** The three handlers carry the file's standard
  empty-material-card guard (21 other handlers already have it), placed in
  `handle_mat_elastic` BEFORE the `_FLUID` split so it covers every spelling:
  a block with no data card was aborting the whole conversion with a bare
  `IndexError` — which `*MAT_ELASTIC` already did before this batch, so the
  guard closes a pre-existing hole as well as the four new keyword families —
  and a card whose MID cell is blank was silently emitting `/MAT/LAW79/0` or
  `/MAT/HYD_VISC/0` + `/EOS/POLYNOMIAL/0`, the `/MAT/LAW76/0` failure mode
  already recorded for `*MAT_187`. Card-1 reads past MID are guarded the same
  way, so a truncated card still converts.

  Suite 2185 → **2313 passed**, 2 skipped, 544 → **645 subtests**; 128 new
  column-exact tests in `tests/test_impact_mats.py`, every physics constant
  recomputed by hand — `sigma_HEL = 1.5*(19e9-1.46e9) = 2.631e10` and
  `T* = 0.2e9/1.46e9 = 0.1369863` asserted **absent** from every emitted field,
  `T*/FC = 1/12` likewise, `E = 9*K1*G/(3*K1+G)` and
  `nu = (3*K1-2G)/(6*K1+2G)` matched against the starter's own echo,
  `k0 = PC/MUC = 16e9`, `(PL-PC)/MUL = 7.84e9`, the negative derived Poisson
  `-0.7480403`, `K = E/(3(1-2*PR)) = 2.0e9` with dyna2rad's `E/3 = 1.0e9`
  asserted absent, `a = sqrt(2.2e9/2600) = 919.8662` in the VC recipe, and the
  `PHEL` derivation Newton-solved independently in the test
  (μ_hel = 0.07837428750607 → `PHEL = 1.0263112948920e10`). The nine
  `_OFFSET_SPECS` spellings get the `test_offset_specs_cover_every_spelling`
  assertion the two preceding batches carry, plus a live `*INCLUDE_TRANSFORM`
  with `IDMOFF` that checks all four emitted ids actually move.

- **Tabulated Johnson-Cook batch** (`*MAT_TABULATED_JOHNSON_COOK` 224 incl.
  `_LOG_INTERPOLATION`, `*DEFINE_TABLE_3D`) — the roadmap P1 item. All were
  `SKIPPED` before. Numeric alias `MAT_224` registered; the `_GYS` (224_GYS)
  and `_ORTHO_PLASTICITY` (264) variants get a LOUD warn-skip (dyna2rad drops
  both SILENTLY: `_GYS` is absent from its keyword map and 264 has no case in
  its dispatch switch, so each falls into the broken `Convert1To1` fallback —
  no /MAT, no message, part wired to `mat_ID=0`, CM:140-143/196-201/527-554).
  `*INCLUDE_TRANSFORM` offset specs for every spelling (card 2 = six
  curve/table ids, card 3 = LCPS; the `E<0`/`BETA<0` negative float-cell
  encodings are deliberately NOT offset and instead draw the dangling
  warnings).

  - **`*MAT_TABULATED_JOHNSON_COOK` (224) → `/MAT/LAW109`** (dyna2rad
    `p_ConvertMatL224`, CM:11108-11705; layout audited against `mat109.cfg`
    `FORMAT(radioss2021)` — the ONLY block, read as-is at `/BEGIN 2022`,
    including card 4's 30 literal blanks before `I_smooth` and the
    NOT-optional card 5). `RHO/E/PR/TR` verbatim (`TR=0` keeps the starter's
    293 default; `T_ini` blank → `T_ref`). **`CP` copies 1:1 — LAW109's
    `C_p` is specific heat per unit MASS** (the engine divides by ρ itself,
    `sigeps109.F:419`), deliberately unlike the MAT_015 → LAW2/LAW4
    ρ-premultiplied `rhoC_p`; adiabatic self-heating is law-internal, so no
    `/HEAT/MAT` is emitted (it would SWITCH LAW109 to the
    imposed-temperature path, `sigeps109.F:411-414`). `E<0` (E(T) curve) is
    sampled at `T_ref` and warned (d2r takes the curve's FIRST ordinate
    regardless of TR, CM:11141-11161). `LCK1` by form: plain curve →
    re-emitted 1-D `/TABLE/1` under its id (d2r's branch requires "TABLE",
    CM:11196, and leaves `tab_ID_h=0` — deck broken); 2-D table →
    referenced by id under `I_smooth=1`; every `I_smooth=2` table — the
    `_LOG_INTERPOLATION` spelling or a negative first rate value (LS-DYNA's
    natural-log axis, Vol II p.357, `exp()`-unwrapped) — is rebuilt with
    BOTH flat-clamp rows: d2r's high-rate sentinel (last curve duplicated
    at `10·max+1`, CM:11219-11250) **plus the first curve anchored at rate
    `1e-10`** — the engine clamps only the log-lookup SAMPLE there
    (`table2d_vinterp_log.F:206`) and otherwise EXTRAPOLATES in log10 below
    the lowest rate, so an unanchored table returns a NEGATIVE yield at the
    zero plastic strain rate of every elastic phase (rates `[1,100,1000]`:
    `6·Y1−5·Y2`) and the run diverges silently under NORMAL TERMINATION;
    solver-validated, the anchored deck tracks the log10 prediction to
    0.0000% where the bare one collapses dt 24×. **3-D table → SPLIT** into
    `tab_ID_h` = the plane nearest `T_ref` and `tab_ID_t` = the per-plane
    lowest-rate curves over T, because LAW109's yield lookup is strictly 2-D
    (`table2d_vinterp_log.F:93-97` `ANCMSG(36)+ARRET(2)` at cycle 1 — d2r
    wires the 3-D id straight in and produces exactly that crash), warned as
    exact-iff-separable, with `LCKT` then ignored (LS-DYNA's own rule);
    when the nearest plane is NOT at `T_ref`, `Yscale_h = kt(T_ref)/
    kt(T_plane)` cancels the constant separable-factor offset the
    reconstruction `k1·kt(T)/kt(T_ref)` would otherwise carry, and
    duplicate plane temperatures are deduped (first kept, warned — the
    synthesized `tab_ID_t` would repeat an outer value, starter ERROR 3088).
    `LCKT` 2-D table → `tab_ID_t` (Radioss forms the `kt(T)/kt(T_ref)` ratio
    internally — absolute curves pass through); a plain-curve `LCKT` carries
    no temperature family (ratio ≡ 1) → warn-drop (d2r drops silently).
    `BETA≥0` → `ETA`; `BETA<0` curve → 1-D `TAB_ETA` with the WHOLE axis
    `exp()`-unwrapped on a negative first abscissa (LS-DYNA: "the natural
    logarithm of the strain rate value is used for all abscissa values" —
    d2r exp()s only the negative points, CM:11320, scrambling mixed-sign
    axes, and forces the YIELD table's `I_smooth` to 2 off a BETA curve;
    neither replicated); 2-D table → direct (LS-DYNA's T → rate-curves
    nesting lands exactly on TAB_ETA's (rate, T) axes, per the manual's own
    level tags on the 3-D/4-D forms and d2r's untransposed pass-through,
    CM:11342); TABLE_3D → the table warn-drops (LS-DYNA nests (T, rate, εp),
    TAB_ETA reads (rate, T, εp) — a full axis transpose) and a
    representative scalar `ETA`, sampled at (lowest rate, plane nearest
    `T_ref`, εp→0), replaces the old flat 1.0; `BFLG≠0`
    reinterprets the tables → warn-drop. `FAILOPT/NUMAVG/NCYFAIL/ERODE/LCPS`
    warn-drop (no TAB1/LAW109 counterpart; LCPS is post-processing-only even
    in LS-DYNA). `Xscale_h` deliberately stays blank: the engine applies it
    to the pre-yield rate sample but not to the in-loop plastic re-lookup
    (`sigeps109.F:221` vs `349`) — the two agree only at 1.0.

  - **`*MAT_224` LCF/LCG/LCI/NUMINT → `/FAIL/TAB1`** (layout audited against
    `fail_tab1.cfg` `FORMAT(radioss2021)`; card 2 all-blank keeps
    `Dcrit=1, D=0, n=1` — measured — which IS MAT_224's instant
    `F = ∫dε_p/ε_f ≥ 1` criterion, with no TABLE2/FAD_EXP so `DMG_FLAG=0`,
    no softening, nothing double-counted). Emitted ONLY when a usable `LCF`
    exists — d2r creates its failure card for EVERY MAT_224 and hits starter
    ERROR 3000 on an LCF-less deck. The triaxiality axis is FLIPPED
    (LS-DYNA LCF tabulates pressure-based `p/σ_vm`, compression-positive;
    Radioss `TRIAX = σ_m/σ_vm` tension-positive, `fail_tab_s.F:163-172`)
    with the *DEFINE_CURVE scales baked in before the flip — avoiding d2r's
    `Ashiftx=OFFA` slip (CM:11623). A Lode-dependent LCF (2-D table) adds
    dim 3 with **`θ = (2/π)·asin(ξ)`** — Radioss interpolates the normalized
    Lode ANGLE (`fail_tab_s.F:180`) while LCF tabulates the Lode PARAMETER
    `ξ = 27J₃/2σ_vm³` (they coincide only at −1/0/+1; d2r passes ξ through
    unchanged); shells read the axis at θ=0 (Radioss-documented); without
    LCG a two-plane flat rate axis carries the Lode dimension (dim 2 of a
    3-D TAB1 table IS the strain rate). `LCG` has NO function slot on TAB1,
    so the grid is the PRE-MULTIPLIED `ε_f(triax)·g(rate)` tensor product
    via per-row `Scale_y`; a negative-first-abscissa LCG (natural-log rates)
    is `exp()`-unwrapped — d2r copies the log axis raw into its rate slot
    (CM: LCG→FCT_SR raw id copy). `LCH` is ALWAYS warn-dropped: TAB1's
    `fct_IDT` is evaluated at `TSTAR` and NO LAW109 engine path ever fills
    `TSTAR` (grep: only the Johnson-Cook-family laws do) — a mapped
    absolute-temperature `LCH` would read `LCH(0)≈0` every cycle and erode
    the whole mesh at cycle 1. `LCI` → `fct_IDel` with `EI_ref` blank → 1.0
    length unit (abscissa `l_c/EI_ref` = absolute element size, same as
    LCI); a multi-row LCI table warn-drops (TAB1's regularization has no
    triaxiality axis), a 1-row table collapses to its curve. LCF-table rows
    whose curves parsed to zero points are dropped (an empty synthesized
    /FUNCT is a starter reject); no surviving row → no /FAIL. `NUMINT`:
    count 1 → `Ifail_sh=1`/`Ifail_so=1` (first-IP deletion); count > 1 →
    `Ifail_sh=2` + `P_thickfail = count/NIP` via the shell stack that
    references the MID (d2r's `FAILIP=NUMINT/100` integer-truncates every
    `0<NUMINT<100` to 0 → starter default 1); percent form →
    `P_thickfail=|NUMINT|/100`; **`NUMINT=8` on fully integrated solids**
    (ELFORM 2/−1/−2 → Isolid 17, 8 IPs on both sides) → `Ifail_so=2`,
    deletion when ALL integration points fail — exactly LS-DYNA's 8-of-8
    rule (`fail_tab_s.F:258`); other solid counts keep first-IP deletion
    (warned: solids erode earlier); `NUMINT=-200` (LS-DYNA: track damage,
    never erode) → NO /FAIL at all, warned (Radioss has no
    track-but-never-delete mode).

  - **`*DEFINE_TABLE_3D` → `/TABLE/1` Ndim=3 (flat)** — one row per
    (inner VALUE, outer VALUE): dim 1 = leaf-curve abscissa, dim 2 = the
    inner tables' VALUEs (their own SFA/OFFA applied — d2r's generic 3-D
    path never reads them, and it also puts the OUTER value on dim 2), dim 3
    = the outer card's VALUEs, rows ascending by (B, A), `Scale_y=1`. The
    starter's grid rules are enforced up front: ragged plane grids warn and
    skip the flat emission (naming ERROR 3089), duplicate outer VALUEs too
    (same (A,B) under two fct ids = contradictory data, ERROR 3088), and a
    single-row flat grid as well (NFUN==1, ERROR 778) — while `*MAT_224`
    LCK1 plane-slicing still converts. `*DEFINE_TABLE_4D`+ stay
    skipped (Radioss `/TABLE` caps at Ndim=4; no supported consumer).
    Unsupported consumers warn: a `*MAT_024` LCSS pointing at a 3-D table
    (temperature-dependent hardening) now warn-falls-back to bilinear
    instead of silently wiring the id into a function slot (dangling /FUNCT,
    starter ERROR 779); the MAT_120/252/DIEM table slots already carried
    loud dangling warnings that cover the 3-D case.

  - **Shared /FUNCT + /TABLE id namespace** — the starter runs FUNCTION and
    TABLE ids through ONE duplicate scan (`hm_read_table.F:88`, ERROR 79
    on a clash), so `ConversionState.next_curve_id()` now dodges the
    `*DEFINE_TABLE`/`_2D`/`_3D` registries and synthesized AutoTables as
    well as user curves — a renumbered deck carrying a table id at/above
    the auto-id base (90001) no longer collides with a synthesized /FUNCT
    (starter-proven ERROR 79 before the fix). This hardens every
    pre-existing `_add_auto_curve` call site too. The `*INCLUDE_TRANSFORM`
    offset specs for the `*DEFINE_TABLE` family gained the point-card
    width (`data_w=20`): the 2E20.0 "VALUE LCID/TABLEID" rows were being
    sliced at the header's 10-char width, which corrupted the VALUE
    (`293` → `1293`) and left the actual reference dangling — fixed for
    `*DEFINE_TABLE`, `_2D` and `_3D` alike.

  - **Live-starter validation** (starter_win64 2026-05-20, `/BEGIN 2022`,
    np=1): the converted combined deck — LAW109 all-cards + 1-D/2-D/3-D
    `/TABLE/1` + `/FAIL/TAB1` with the Ndim=3 (triax, rate, Lode) grid —
    answers NORMAL TERMINATION, 0 ERROR(S), 0 WARNING(S), with the listing
    echoing every asserted field (`SPECIFIC HEAT COEFFICIENT = 450000000`,
    `STRAIN TABLE ID = 90003`, `REFERENCE ELEMENT LENGTH = 1.0`,
    `TEMPERATURE SCALE FUNCTION = 0`, one-layer/first-IP deletion) and the
    3-D ordinate echo reproducing the `Scale_y` product numerically
    (`1.2·1.3 = 1.56`). Negative control: the same deck minus ONE grid row →
    `ERROR ID: 3089` twice. **Full-solver validation** on 22 single-element
    decks (engine_win64 2026-05-20): the 3-curve rate table tracks all three
    on-table rates and the linear between-rate interpolation to ≤0.17%; the
    `I_smooth=2` paths track the engine-exact log10 prediction to 0.0000%
    (both the `_LOG_INTERPOLATION` rebuild and the ln-axis unwrap, incl.
    above-range sentinel clamping — and the unanchored negative-yield
    divergence is reproduced by the pre-fix decks as the negative control);
    3-D-split temperature scaling engages through adiabatic self-heating
    (T to 0.001%, σ_vm to 0.014%); adiabatic heating matches the closed
    form to 0.002%; triaxiality-flipped failure hits LCF(−1/3)=1.0000 and
    LCF(−2/3)=1.5000 to 0.06% with the compression-positive sign convention
    proven; LCG rate scaling to 0.12%; LCI element-size regularization
    exact on both plateaus; NUMINT=1/3/5 delete on exactly the 1st/3rd/5th
    failed layer. 63 tests (column-exact, hand-computed) in
    `tests/test_tabulated_jc.py` + the *DEFINE_TABLE offset coverage in
    `tests/test_include_transform.py`.

- **Foam batch** (`*MAT_SOIL_AND_FOAM` 005, `*MAT_LOW_DENSITY_VISCOUS_FOAM`
  073, `*MAT_MODIFIED_HONEYCOMB` 126, `*MAT_DESHPANDE_FLECK_FOAM` 154,
  `*MAT_HILL_FOAM` 177, `*CONTACT_INTERIOR`, `*SET_PART_ADD`) — the roadmap
  P1 batch. All were `SKIPPED` before. Numeric aliases
  `MAT_5/005`, `MAT_73/073`, `MAT_126`, `MAT_154`, `MAT_177` registered, with
  `*INCLUDE_TRANSFORM` offset specs for every spelling.
  `*MAT_SOIL_AND_FOAM_FAILURE` (014) deliberately stays skipped — dyna2rad
  maps it to law 14, which has no case in its dispatch switch, and silently
  converting away its failure semantics onto LAW21 would be worse.

  - **`*MAT_SOIL_AND_FOAM` (005) → `/MAT/LAW21` (DPRAG)** (dyna2rad
    `p_ConvertMatL5`, CM:719-983; layout audited against `matl21_dprag.cfg`
    `FORMAT(radioss130)`, the block a `/BEGIN 2022` deck reads — including
    the card-4 `%10d` + 10 literal blanks before `Kt`). `E = 9GK/(3K+G)`,
    `ν = (3K−2G)/(6K+2G)` clamped `[0, 0.495]` — the clamp WARNED when it
    fires (d2r clamps silently); `A0/A1/A2` verbatim (identical yield
    algebra); `PC → P_min` verbatim, with the `PC=0` blank default's
    semantic flip warned (LS-DYNA: an ACTIVE zero-tension floor, Manual
    Remark 1; LAW21: `PMIN==0 → -INFINITY`, unlimited tension —
    `hm_read_mat21.F:120`). **`Kt = B = KUN` for `VCR=0` — a conscious,
    solver-measured fix over dyna2rad's `Kt = KUN/100`**: with `Mu_max`
    unset the starter substitutes `1e20` and the engine's unloading bulk
    `α·B + (1−α)·Kt` with `α = μ/Mu_max` degenerates to `Kt` for every
    reachable μ (`m21law.F:166-170`), so d2r's `B` is a DEAD field
    (bitwise-identical run with B 200→2) and its converted soil unloads at
    `KUN/100` in BOTH signs — it retraces the loading curve and dissipates
    ~nothing (measured −0.12% retained IE); with `Kt = KUN` the unload leg
    matches LS-DYNA's elastic line (measured 5.296 vs 5.256 at μ=0.20).
    `VCR=1` keeps d2r's `B=0` + `Kt=KUN/100` ON PURPOSE: the starter
    substitutes `B=Kt` (its WARNING 829) and that soft modulus reproduces
    VCR=1's load=unload retrace (measured), warned with tension named.
    THE pressure-curve transform encoded from the engine sources, not
    intuition: LS-DYNA tabulates `P` vs `EPS = ln(V/V0)` (negative in
    compression, Manual Remark 1) while the LAW21 engine evaluates the
    function at `mu = ρ/ρ0 − 1` (positive in compression,
    `mmain.F90:686-692`; `P` compression-positive on BOTH sides,
    `m21law.F:143/161`) → `mu = exp(−EPS) − 1`, points re-sorted ascending,
    ordinates unchanged. `LCID` preferred (`*DEFINE_CURVE` scales bake in
    BEFORE the exp — the physical EPS is `SFA·x`), else the `EPS/P` card
    pairs with unused trailing `(0,0)` slots stripped and LS-DYNA's
    auto-generated `(0,0)` first point reproduced. Mixed-sign curves follow
    dyna2rad (keep `x ≥ 0` as `|EPS|`, warned); an ALL-POSITIVE curve is a
    closed d2r gap — both its branches require a negative abscissa
    (CM:814/837) and silently create NO function — k2rad converts it as
    `|EPS|` under a warning. Points with `|EPS| > 700` are dropped with a
    wrong-curve warning instead of crashing the conversion (`exp()`
    overflow), and points folding onto a duplicated μ abscissa collapse to
    the last ordinate, warned (a `/FUNCT` cannot carry a vertical step).
    Starter-validated: echo `PRESSURE FUNCTION NUMBER = 90001`,
    `TENSILE BULK = 500`, `UNLOADING BULK = 500` for KUN=500,
    0 ERROR(S).

  - **`*MAT_LOW_DENSITY_VISCOUS_FOAM` (073) → `/MAT/LAW90` [+
    `/VISC/PRONY`]** (dyna2rad `p_ConvertMatL73`, CM:4275-4338; layout
    audited against `LAW90.cfg` `FORMAT(radioss2022)` — `TFLAG` needs ≥2024
    and `FAIL/Kcont/Tcut` ≥2026, so `TC/FAIL/KCON` are named-dropped as
    version-gated, not merely unmapped). `E→E0`; `LCID` referenced BY ID as
    the single quasi-static loading row (`NL=1`, rate 0), `Ismooth=1`,
    `Fcut=0` — dyna2rad's fixed values; `HU→Hys`, `SHAPE→Shape` with the
    blank-field defaults 1.0 through `_ffield` (a bare `to_float` would
    flip LAW90 into a different unloading regime). The explicit `Gi/BETAi`
    cards (LCID2=0) become a same-id `/VISC/PRONY` with the `BETAi>0`
    filter (d2r filters identically; its `radTimeRel/radGammaArr` names are
    misleading — the map is 1:1 `GI→G_i`, `BETAI→Beta_i`). The `LCID2>0`
    relaxation-fit branch (LS-DYNA fits internally; nobody re-fits) and the
    `LCID2=−1` frequency-data branch convert rate-independent LOUDLY, with
    the conditional card-3 forms walked so the parse position never drifts.
    `DAMP` (blank = the LS-DYNA 0.05 default) is named-dropped — dyna2rad
    moves it onto `/PROP/TYPE14 Mu/Lambda`; k2rad keeps the section-derived
    `/PROP/SOLID`, matching its MAT_057 policy. The per-term `REF` flag
    folds into the `_ref_flag_materials` registry (both /XREF diagnostics
    fire). LAW90 is already on the starter's solid-/XREF whitelist, so the
    `_target_mat_law` entry alone makes MAT_073 parts RECEIVE
    `*INITIAL_FOAM_REFERENCE_GEOMETRY` blocks. The parts' `/PROP/SOLID` is
    pinned `Ismstr=10` (total strain) UNCONDITIONALLY — dyna2rad's own
    rule for every MAT_073 section (CP:484-495), not only on the /XREF
    path (LAW90 is a total-formulation law; deep-crush robustness) — with
    a drag warning when a non-foam part shares the section.
    Starter-validated: NORMAL TERMINATION 0 ERROR(S) 0 WARNING(S), echo
    `ORDER OF PRONY SERIES = 2`.

  - **`*MAT_MODIFIED_HONEYCOMB` (126) → `/MAT/LAW50` + `/PROP/TYPE6`**
    (dyna2rad `p_ConvertMatL26` + `UpdateMatConvertingLoadCurves`,
    CM:1744-1815/8923-9213 + CP:404-415; layout audited against
    `mat_law50.cfg` `FORMAT(radioss90)`, the 24-card block a `/BEGIN 2022`
    deck reads — `Irate` and the whole `ECOMP NU SIGY ET VCOMP` compaction
    card exist only in `FORMAT(radioss2025)`, so the compacted-state block
    `E/PR/SIGY/VF` is INEXPRESSIBLE at 2022 and warned, never emitted as a
    stray 25th card). Slot order `11/22/33/12/23/31`
    (`hm_read_mat50.F90:308-315`); identity map `a→11 b→22 c→33 ab→12
    bc→23 ca→31` with the LS-DYNA fallback chain; moduli `EAAU..GCAU` with
    `0→E` / `0→E/2(1+PR)` fallbacks; `Iflag1=Iflag2=−1` (yield vs −strain,
    compression-positive — d2r's values). Curves whose FIRST abscissa is
    `>0` are stress-vs-`V/V0` and recompute to `1−V/V0` as a new `/FUNCT`
    (d2r `RecomputeCurvesBasedOnFirstAbcissa`, CM:9215-9266), originals
    kept; `LCSR>0` samples the curve's FIRST FIVE points (the MODIFIED
    rule, CM:9017-9021 — the plain MAT_026 rule takes the first 4 + the
    LAST instead) and replicates each direction's base function per rate
    with `Fscale`=ordinate; `LCSR=−1` per-direction cards are dropped
    loudly (d2r never reads them). The `LCA<0` transversely-isotropic
    surface follows d2r's remap (`fun11←LCB`, `fun22=fun33←LCC`,
    shears←LCS; `E22=E33=EBBU`, `G12=GBCU`, `G23=G31=GABU`; `Iflag 0/1`)
    under a loud approximation warning — the LS-DYNA damage curves become
    yield curves; `ECCU<0`'s third surface named-dropped. `TSEF/SSEF →
    Eps_max` components (negative curve forms warned to 0). The
    `/PROP/TYPE6` rides the composite AOPT machinery (`AOPT=2 →
    /SKEW/FIX`, part repointed, isotropic section prop suppressed) — with
    the honest reason: the starter ACCEPTS LAW50 on `/PROP/TYPE14`
    (SOLID_ISOTROPIC class) but only `IGTYP 6` builds the orthotropy tensor
    (`SMORTH3`, `s8zinit3.F:435`) — on TYPE14 the directions silently
    collapse onto the element frame. **The property pins `Isolid=1` +
    `Ismstr=1` — dyna2rad's fixed honeycomb values (CP:415 overrides the
    ELFORM map, CP:472), solver-measured**: MAT_126's default element is
    LS-DYNA solid type 0, a 1-point corotational "nonlinear spring-type
    solid" whose yield curves are ENGINEERING strain (the manual's LCA
    note scopes log strain to the NON-corotational formulations, warned
    when the deck states one); the previous ELFORM-derived
    `Isolid=17`/`Ismstr=0→4` evaluated the curves at LOG strain
    (measured: |SX| = curve(0.5108) at 0.40 nominal crush to 5 digits),
    pulling a densification knee at 0.70 forward to `1−exp(−0.70)` = 0.50
    nominal — 28% early. LAW50 itself declares SMALL_STRAIN
    (`hm_read_mat50.F90:437`). A MAT_126 part holding SHELL elements
    is refused (LAW50 has no shell class → ERROR 3046). Starter-validated:
    NORMAL TERMINATION 0/0, `YIELD STRESS 11` echo listing exactly the 5
    sampled `STRAIN RATE` lines.

  - **`*MAT_DESHPANDE_FLECK_FOAM` (154) → `/MAT/LAW115`** (dyna2rad
    `p_ConvertMatL154`, CM:6363-6386; layout audited against
    `matl115_deshfleck.cfg` `FORMAT(radioss2021)`, deterministic `Istat=0`
    branch). The direct 1:1 counterpart — LAW115 IS the Deshpande-Fleck
    surface, no formulation selector exists; hardening constants transfer
    verbatim (identical law `σy = SIGP + GAMMA·(ε̂/EPSD) +
    ALPHA2·ln[1/(1−(ε̂/EPSD)^BETA)]`). `CFAIL→EPSVP_F`; **`PFAIL→SIGP_F`
    is a conscious d2r fix**: the shipped `mat_154.cfg` parses only 6
    fields on card 2 (no PFAIL attribute at all), so dyna2rad's
    `CopyValue("PFAIL","SIGP_F")` silently no-ops and its SIGP_F is always
    0 — the k2rad validation run echoed `MAX. PRINCIPAL STRESS AT FAILURE
    = 25`. `DERFI` named-dropped (a derivative-evaluation flag; LAW115's
    `Ires` selects the return-mapping ALGORITHM — not the same
    enumeration), `NUM` named-dropped (LS-DYNA needs NUM sustained
    violation steps, Radioss deletes on the FIRST — earlier erosion
    possible). Starter bound checks pre-announced (`ALPHA ∉ [0,√4.5]` →
    ERROR 1897, `PR ∉ [0,0.5)` → ERROR 49). **LAW115 hex parts are routed
    to `/PROP/SOLID Isolid=24` (HEPH), ENGINE-measured**: on the
    ELFORM-derived full-integration `Isolid=17` the starter only answers
    WARNING 1905 (`sgrtails.F:631` gates `JHBE 3..20` without checking
    Istat), but the ENGINE collapses the solid time step below DTMIN at
    cycle 0, jumps past the end time and prints NORMAL TERMINATION after
    1 cycle — a silent empty run (all four LAW115 validation decks did
    this; the identical decks at Isolid=24 ran 24k-264k cycles to
    completion with 0 ERROR(S) 0 WARNING(S)). Isolid=24 is also dyna2rad's
    default hex formulation, so d2r decks never see the trap. Only the
    measured-fatal 17 is remapped — tet formulations keep their derived
    value with the 1905 window pre-announced — and a non-LAW115 part
    sharing the *SECTION_SOLID is drag-warned by name.

  - **`*MAT_HILL_FOAM` (177) → `/MAT/LAW62` (VISC_HYP)** (dyna2rad
    `p_ConvertMatL177H`, CM:9741-9896; layout audited against
    `matl62_visc_hyp.cfg` `FORMAT(radioss2022)` — the `nu_i` CELL_LIST
    block is part of the 2022 card and read by the starter even though the
    2022 Reference Guide omits it, so it is emitted as explicit zeros: any
    nonzero `nu_i` would OVERRIDE the card-2 `Nu`). Constants branch only:
    `Nu = N/(1+2N)`; `mu_i = Ci·Bi/2`, `alpha_i = Bi` per the exact
    Hill→Ogden identity, **INDEX-ALIGNED over the nonzero-C slots — a d2r
    defect fixed consciously**: dyna2rad compacts the C and B lists
    independently (CM:9877-9883), so a zero `Ci` mid-list makes it read
    `Bi` out of alignment (and potentially out of range). Card 1 is
    `MID RO K N MU LCID FITTYPE LCSR` — the manual (p.2-1216) and the
    shipped `Keyword971/mat_177.cfg` agree, field 4 is N (an earlier
    draft of this batch read the two transposed, feeding MU into
    `Nu = N/(1+2N)`; caught in review, fixed before merge). `K` (LAW62
    derives bulk from Nu),
    `MU`, `LCSR` and the Mullins `R/M` card are named-dropped. The
    `LCID>0` curve-fit branch warn-skips AT PARSE (it changes the card
    layout — no C/B cards — the MAT_240-variant policy): LAW62 has no
    `Itab`/fit path anywhere (`hm_read_mat62.F` reads constants only), and
    dyna2rad emits NOTHING while silently wiring the part's mat to 0.
    Starter-validated: NORMAL TERMINATION 0/0, echo `EQUIVALENT POISSON
    RATIO = 0.25` = N/(1+2N) for N=0.5 read from FIELD 4 of a
    manual-order deck (a transposed read of that deck would print 0.0454
    from MU=0.05). The only shell-capable law of the batch
    (SHELL_ISOTROPIC + SOLID_ISOTROPIC).

  - **`*CONTACT_INTERIOR` → `Icontrol` resolution (warned, not emitted)**
    (dyna2rad `ConvertContactInterior`, CC:671-767 — its whole conversion
    is `SetValue(prop, "Icontrol", 1)` per part; the earlier per-part
    `/INTER/TYPE7` synthesis is commented out in its source). **Version
    gate MEASURED on starter_win64, not guessed**: the Icontrol input
    column exists only in the radioss2025 property formats
    (`prop_p14_solid.cfg`/`prop_p6_sol_orth.cfg` `FORMAT(radioss2025)`
    last card `Ndir sphpartID Icontrol`; the 2022 blocks end at
    `Ndir sphpartID`) — appending the 3-field card under `/BEGIN 2022`
    leaves the per-part echo at `ICONTROL 0` and draws WARNING 100213,
    while the identical deck under `/BEGIN 2025` echoes `ICONTROL 1` with
    0 warnings. Emitting the dead field would be silently wrong, so k2rad
    resolves and WARNS: each PSID resolves per d2r CC:692-727 (a
    `*SET_PART`'s ids are part ids; a new `*SET_PART_ADD` handler stores
    one level of part-set nesting — the Yaris/Camry NCAC decks use
    exactly that shape), solid parts are NAMED as running
    without interior contact (mitigation: `/DT/BRICK/CST`, or hand-set
    `Icontrol=1` after migrating the deck to the 2025 format), parts
    whose property type has no Icontrol at ANY version are named
    separately, unresolvable/unknown ids are named, and the set-header
    `DA1..DA4` attributes (PSF/Fa/ED/TYPE — defined on the referenced set
    per Manual Vol I; d2r reads none of them) are named-dropped, TYPE=2
    specifically. `note_recognized_not_emitted` records the keyword.

  - **`*SET_PART_ADD` flattened for EVERY part-set consumer** — the
    post-parse `_flatten_part_set_adds` prepass expands each `_ADD` set
    (one nesting level, order-independent: only sets that were DIRECT
    `*SET_PART[_LIST]`s at parse count as children; nested `_ADD`
    children and unresolvable ids are warned) into a plain
    `state.part_sets` entry, so contact sides `SSTYP/MSTYP=2`,
    `--auto-gapmin`, `/GRAV` scopes, ALE groups and `*CONTACT_INTERIOR`
    all resolve it through the ordinary lookup. Before the pass, a
    contact referencing an `_ADD` set resolved to an EMPTY side with a
    warning blaming the set for "naming no parts" — a diagnosability
    regression over the old skipped-keyword report, and a silently-empty
    interface. An `_ADD` colliding with a direct set of the same id
    keeps the direct set, warned. (Parse-time consumers —
    `*ELEMENT_MASS_PART_SET`, `*LOAD_BODY_PARTS` — still resolve during
    dispatch and see only direct sets, a pre-existing deck-order
    limitation.)

  - Registry plumbing: the five families extend `_target_mat_law` (LAW21/
    90/50/115/62 — only LAW90 is on the starter's solid-/XREF whitelist;
    the off-whitelist four now warn-skip NAMING the law instead of
    misreporting "no /MAT"), `all_mat_ids()` (ERROR-79 collision
    avoidance), and the beam-compat classification block (none of the five
    declares a BEAM_* keyword — verified against every `INIT_MAT_KEYWORD`
    call site in the 2026-05-20 starter tree — so neither beam frozenset
    changes; LAW62 alone declares SHELL_ISOTROPIC). Solid-only shell-part
    refusals warned per family (ERROR 3046; negative control measured:
    MAT_005 on a shell part answers exactly `ERROR 3046 ... MATERIAL ...
    OF TYPE 21`).

  - tests/test_foams.py: 77 tests + 68 subtests; suite 2046 → 2123
    (2121 passed + 2 skipped). Every emitted card starter-validated live
    (`starter_win64` 2026-05-20, `/BEGIN 2022`, np=1): the combined
    all-five-materials deck reads back NORMAL TERMINATION, 0 ERROR(S),
    0 WARNING(S); goldens
    byte-identical. Engine-validated on single-element and crush decks
    (see the PR): MAT_005 pressure curve ≤0.53% + exact Drucker-Prager
    limits + LS-DYNA-line unloading after the Kt fix, MAT_126 exact
    2.0/3.0/4.0 MPa per-direction plateaus + skew-rotated frame swap,
    MAT_154 SIGP −0.01% and hardening ≤0.01% (now runnable as emitted),
    MAT_177 Ogden nominal-stress match ≤0.01%, MAT_073 loading curve
    +viscous ≤2% with measured Prony stiffening and HU hysteresis.

- **Adhesives / cohesive batch** (`*MAT_COHESIVE_MIXED_MODE` 138,
  `*MAT_ARUP_ADHESIVE` 169, `*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE` 240,
  `*MAT_TOUGHENED_ADHESIVE_POLYMER` 252, `*MAT_ADD_DAMAGE_DIEM`, and the
  cohesive `*SECTION_SOLID` ELFORM ±19/20/±21/22 → `/PROP/TYPE43` element
  path) — the roadmap P1 batch. All were `SKIPPED` before; a cohesive ELFORM
  additionally fell through `_elform_to_isolid`'s default to a full-integration
  structural-hex `/PROP/SOLID` (Isolid 17), i.e. a zero-thickness cohesive on a
  volume element. Numeric aliases `*MAT_138`/`*MAT_252` are registered too —
  they are absent from dyna2rad's own keyword table and die in its broken
  `Convert1To1` fallback (no `/MAT`, no message).

  - **`*MAT_COHESIVE_MIXED_MODE` (138) → `/MAT/LAW117`** (dyna2rad
    `p_ConvertMatL138`, CM:6248-6360; card layout audited against `mat117.cfg`
    `FORMAT(radioss2022)` — the 2021 block lacks the whole
    `Fct_TN/Fct_TT/Fscale_x` card and reads `GAMMA` as an integer). `EN`/`ET`
    copy RAW — both sides are stiffness PER UNIT LENGTH (`DIMENSION="PRESSURE
    PER UNIT LENGTH"`, mat117.cfg:25-26), no thickness rescale. `ROFLG` 0/1 →
    `Imass` 2/1 written EXPLICITLY: the starter coerces blank/0 to 1 = AREA
    density (`hm_read_mat117.F:140`), which would silently flip LS-DYNA's
    volume default — the validation run measured the difference as part mass
    `ρ·A = 1.1e-7` vs `ρ·V = 2.2e-7`. `XMU>0` → power law
    (`Irupt=1`, `EXP_G=XMU`); `XMU<0` → Benzeggagh-Kenane (`Irupt=2`,
    `EXP_BK=|XMU|` — written explicitly, `EXP_BK` has NO starter default);
    negative `T`/`S` → element-size traction curves (`Fct_TN/TT`, `TMAX=1.0`,
    UND-fallback suppressed exactly as d2r's curve branch does); `T=0` →
    `TN = 2·GIC/UND` (LS-DYNA's `GIC = T·UND/2` inverted — stays under the
    starter's `GIC ≥ TN²/(2·EN)` floor by construction); a zero peak traction
    with no curve warns in BOTH modes (the mode-II case additionally names
    the starter's own division by zero: `UTD = 2·GIIC/(DELTA0S·ET)` with
    `DELTA0S = TT/ET = 0`, `hm_read_mat117.F:162-166`); negative `GIC`/`GIIC`
    (R13 curve form) zeroed LOUDLY (d2r loses them silently through a scalar
    read). `INTFAIL` → `Idel` with both semantic gaps warned: 0 is LS-DYNA's
    never-delete state (starter coerces `Idel` 0→1 — the element WILL erode),
    negative is Newton-Cotes (TYPE43 is fixed 4-point Gauss; only the count
    carries). `GAMMA` copies raw — dyna2rad's `GAMMA==0 → 2` branch is dead
    code (its post-handler attribMap overwrites it, CM:6357 vs 609).

  - **`*MAT_ARUP_ADHESIVE` (169) → `/MAT/LAW169`** (dyna2rad
    `p_ConvertMatL169`, CM:6426-6439; layout audited against
    `radioss2025/MAT/LAW169.cfg`, the card's only FORMAT block). Two layout
    traps handled: `SHT_SL` moves to the MIDDLE of LAW169 card 2 (between `PR`
    and `TENMAX`; starter echo `SLOPE OF YIELD SURFACE AT ZERO TENSION`
    confirmed the slot) and `PWRT`/`PWRS` are `%10d` INTEGERS (floats in
    LS-DYNA — rounded with a warning naming the exponent change; d2r
    truncates silently). Version gate measured, not guessed: LAW169 is
    registered only from radioss2025, and under k2rad's `/BEGIN 2022` the
    starter prints non-fatal `WARNING 100211` then parses the card with the
    2025 layout anyway — byte-identical field echo vs a `/BEGIN 2025` control,
    NORMAL TERMINATION; the k2rad warning says exactly that so the starter
    output does not read as a conversion defect. Warned drops (d2r drops all
    of them silently — `LAW169.cfg` comments them out): `EDOT0`/`EDOT2` rate
    scaling + the `SDFAC/SGFAC/SDEFAC/SGEFAC` card it gates, the `EXTRA` edge
    cards (walked in the true 3,4,5,6 order — the `EDOT2` card sits BETWEEN
    the edge pair and the `BTHK` card), `BTHK`, and negative (curve-form)
    strengths, which fall back to the 1e20 no-failure default with the
    consequence named (`SHRP`'s curve form is special-cased: it is the shear
    PLATEAU ratio, absent from `LAW169.cfg`'s `DEFAULTS` block, so the
    dropped curve leaves NO plateau — the 1e20 no-failure default applies
    only to the four strengths/energies). `THKDIR != 1` warns the
    ORIENTATION trap, not a mere drop: LS-DYNA's default `THKDIR=0` detects
    the bond normal as each element's SMALLEST dimension, while
    `/PROP/TYPE43` always uses face 1-2-3-4 → 5-6-7-8 (the `THKDIR=1`
    convention, which converts exactly and stays silent) — an element whose
    smallest dimension is not its 1234→5678 axis gets its
    traction-separation directions rotated 90° with no starter complaint.
    LAW169 is absent from the `sini43.F`
    area-mass list → VOLUME density always: a zero-height ARUP cohesive has
    zero nodal mass, warned whenever MAT_169 lands on a cohesive ELFORM.

  - **`*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE` (240) → `/MAT/LAW116`**
    (dyna2rad `p_ConvertMatL240`, CM:6619-6757; layout audited against
    `mat116.cfg FORMAT(radioss2021)` — no 2022 revision exists). `EMOD`/`GMOD`
    are TRUE moduli: the starter divides by `Thick` itself
    (`UPARAM(1)=E/THICK`, `hm_read_mat116.F:197`) — dividing in the converter
    would apply it twice (the LAW117-vs-LAW116 stiffness-dimension trap).
    Rate encodings sign-for-sign: `G*C_0<0` → rate-dependent toughness
    (`GC_ini/GC_inf/SRATG`), `T0<0` → rate-dependent yield with `T1`'s sign
    picking quadratic/linear-log (`ORDER` 2/1), `FG` sign picking the
    energy/displacement criterion (`FAIL` 1/2), all magnitudes through
    `abs()` as d2r does. **Three dyna2rad defects fixed consciously**:
    (1) the mode-II rate gate keys on `G2C_0<0` like mode I and the LS-DYNA
    manual — d2r keys on `EDOT_G2<0` (CM:6715), a transcription slip that
    zeroes `GC2_inf`/`SRATG2` on every valid rate-dependent deck (`EDOT_G2`
    is a positive reference rate) and would pass a negative one through raw;
    starter echo confirmed `SRATG2=0` for `G2C_0>0` despite `EDOT_G2=0.4` on
    the card, and both fields kept for `G2C_0<0`. (2) `Idel` carries
    `|INTFAIL|` — d2r hard-codes `Idel=1` for ANY positive `INTFAIL`
    (CM:6754), turning an `INTFAIL=4` all-IPs bondline into delete-on-first-
    IP (~4× over-erosion). (3) the yield rate terms `T1`/`EDOT_T` (and
    `S1`/`EDOT_S`) are gated on `T0 < 0` (`S0 < 0`) as the manual states
    ("only considered if T0 < 0") — d2r copies them unconditionally
    (CM:6725), and since the LAW116 engine switches rate hardening on for
    ANY `SIGB > 0` (`sigeps116.F:143`) a static-yield deck with stale
    `T1`/`EDOT_T` fields would run rate-dependent in Radioss where LS-DYNA
    ran a constant yield (live-confirmed in a starter echo); zeroed live
    fields are warned. `INICRT` (which d2r never reads — its cfg
    mislabels the field `OUTPUT`) maps onto `Icrit` against the engine
    kernel (`sigeps116.F:226`: `ICRIT==1` = quadratic interaction, else
    pure-mode maximum): 0 → default, 1/2 → `Icrit=2` (+ output note for 2),
    negative (flexible-exponent criterion) warned. Also warned: `THICK<=0`
    (LS-DYNA = element geometric thickness; LAW116 coerces 0 → 1.0 LENGTH
    UNIT, `hm_read_mat116.F:149-152` — silent stiffness change; a NEGATIVE
    `THICK` is written 0 too, because the starter's guard is `== 0` only and
    a raw copy would survive to `UPARAM(1)=E/THICK` as a negative
    stiffness), `LCG1C`/`LCG2C` (LS-DYNA IGNORES the scalar toughness when
    the thickness curve is set — the copied scalars are then not what the
    LS-DYNA run used), `FG=0`/`GC_ini=0` (the STARTER silently disables that
    mode's failure, `hm_read_mat116.F:147-148`), and the optional R16 Card 6
    (`RFILTF/COMPY/SMOLIM/XMU` — the manual's cards 4/5 are the `_3MODES`
    mode-III cards, so this card sits fourth in the option-free spelling;
    LAW116 filters rate with a fixed
    `ALPHA=0.005`). The `_THERMAL`/`_3MODES`/`_FUNCTIONS` spellings (all six
    legal combinations registered — `THERMAL_FUNCTIONS` is not one) WARN-SKIP
    with a `recognized_not_emitted` entry: their cards hold curve ids /
    mode-III data with no LAW116 slot, and parsing them as the base card
    would read curve ids as moduli. dyna2rad's gate
    (`lsdThermal==0 && lsd3Modes==0`, CM:6664) drops them with no message
    and a part whose `mat_ID` dangles.

  - **`*MAT_TOUGHENED_ADHESIVE_POLYMER` (252) → `/MAT/LAW120` (TAPO)**
    (dyna2rad `p_ConvertMatL252`, CM:6759-6815; layout audited against
    `mat120_tapo.cfg FORMAT(radioss2022)`, including the card-1
    reference-density `CARD_PREREAD` trap — columns 21-40 stay blank). LAW120
    IS the TAPO model, so the copy is near 1:1 including `D1→D1F`, `D2→D2F`,
    `D3→Dtrx`, `D4→Djc` (CM:6806-6809). `LCSS` → `Table_Id` with the curve
    re-emitted as a 1-D `/TABLE/1` (a TABLE slot — the LAW76/LAW52
    `table_1d_ids` mechanism); both codes ignore the analytic `TAU0..GAMM`
    when it is set (LS-DYNA drops them, the reader zeroes them,
    `hm_read_mat120.F:183-189`), so copying both is exact either way.
    **dyna2rad defect fixed consciously**: its `JCFL`/`DOPT` switch tests
    `== 2` — DEAD branches, the LS-DYNA fields are 0/1 — so every `JCFL=1`
    (triaxiality factor in tension AND compression) deck silently converted
    to the tension-only default, and `DOPT=1` to the wrong damage variable.
    Verified against the engine kernels (`sigeps120_*.F:108-111`: `ITRX=1`
    pressure-dependent for all T / `=2` none for T<0; `IDAM=1` plastic arc
    length / `=2` scaled damage plastic strain): `FLG` 0/2 → `Iform` 1/2,
    `JCFL` 0/1 → `Itrx` 2/1, `DOPT` 0/1 → `Idam` 2/1, undefined values
    warned. `SRFILT` and `IHIS` are parsed from the R16 manual positions —
    the local Altair R7.1 cfg blanks both cells, so a cfg-driven parse drops
    them silently — and warn-dropped (no LAW120 slot); the `IHIS` warning
    names what is actually lost: `IHIS >= 1` is INPUT initialization
    (per-element stiffness/plasticity/damage scaling factors read from
    `*INITIAL_STRESS_SOLID` process-simulation data, R16 Remark 1), not
    history-variable output.

  - **`*MAT_ADD_DAMAGE_DIEM` → `/FAIL/INIEVO`** (dyna2rad
    `p_ConvertMatAddDamageDiem`, CM:10111-10515; layout audited against
    `fail_inievo.cfg FORMAT(radioss2022)` + `hm_read_fail_inievo.F` — no
    title line, four lines per criterion, and line 5 is `DISP, ALPHA, ENER`,
    NOT the order the starter's own listing prints). A rider keyed by the
    parent MID like GISSMO/ADD_EROSION, and coexisting with both (`/FAIL`
    types are independent entities in Radioss — the integration deck carries
    `/FAIL/GENE1` + `/FAIL/INIEVO` on one MID). Criterion map 1:1:
    `DITYP` 0..4 → `INITYPE` 1..5 (same order), `P1`→`TAB_ID` (mandatory —
    `P1=0` warns naming starter ERROR 2088), `P2`/`P3`→`PARAM` per DITYP
    (the MSFLD/FLD layer flag and the DITYP-1 shell-shear flag warn-drop),
    `P5`→`TAB_EL`, `DETYP`/`DCTYP`+1 → `EVOTYPE`/`COMPTYP`, `Q1`→`DISP`/
    `ENER` (zero warns ERROR 2089/2090), `Q3`→`ALPHA` with `EVOSHAP=2`.
    `P4` → `ISHEAR` INVERTED — verified sense: LS-DYNA `P4=0` *includes* the
    transverse shear stresses, Radioss `ISHEAR=1` *considers* them
    (`hm_read_fail_inievo.F:291-293`), so d2r's inversion is correct and the
    flag is always written explicitly (the Radioss blank default would
    silently exclude what the LS-DYNA default includes); a per-criterion
    conflict on the ONE global flag is warned, last wins (d2r parity —
    CM:10273 writes it inside the loop, silently). A table-form `Q1`
    (negative) collapses to the MINIMUM ordinate over the already-scaled
    `(y+OFFO)·SFO` points — d2r's conservative rule (CM:10399/10473), warned
    with the value. **Deliberate fix of d2r's scoping**: `NUMFIP` resolves
    against the parts that actually reference the MID — `FAILIP` for solid
    use, `PTHICKFAIL` for shell use through the same `_numfip_to_pthickfail`
    rule `/FAIL/GENE1` uses — instead of d2r's whole-model element-count
    heuristic with solids-take-priority and a stale `p_PartBeingConverted`
    NIP — with `NUMFIP < -100` clamped to -100 (all layers) first, because
    the `_numfip_to_pthickfail` helper carries `*MAT_ADD_EROSION`'s
    `(|NUMFIP|-100) integration points` convention and DIEM defines a
    negative `NUMFIP` as a percentage of layers ONLY (R16 p.2-56). A DIEM
    `P1` `*DEFINE_TABLE` whose FIRST rate value is negative warns the
    LS-DYNA log-rate-axis convention ("assumed to be given with respect to
    logarithmic strain rate") — `/TABLE` interpolation reads the same
    abscissae as literal rates. `DCTYP=-1` (damage kept OFF the stress in
    LS-DYNA) is warned as the
    physics change it becomes; `DINIT`/`DEPS`/`VOLFRAC`/`Q4` warn-drop; `Q2`
    is a d3hsp log flag (output-only, ignored as d2r does); a second DIEM on
    one MID overwrites with a warning; short criterion lists reduce
    `NINIEVO` to the cards that exist.

  - **Cohesive element path: `*SECTION_SOLID` ELFORM ±19/20/±21/22 →
    `/PROP/TYPE43` (CONNECT)** under the SECID verbatim (layout audited
    against `prop_p43_connect.cfg FORMAT(radioss140)`: title + ONE card,
    `Ismstr(1-10)` + 70 blanks + `True_thickness(81-100)`). `Ismstr=1`
    pinned (the starter collapses every input to 1 or 4 anyway,
    `hm_read_prop43.F:121-124`; 1 is what d2r sets for its MAT_138/240
    CONNECT props). A section is ALSO routed to TYPE43 when any part on it
    carries a SOLID_COHESIVE law — d2r's material rule (`convertprops.cxx:
    385-395` routes on the *MAT keyword and never looks at ELFORM), needed
    because `*MAT_ARUP_ADHESIVE` runs on ordinary ELFORM 1/2/15 bricks in
    LS-DYNA and `/MAT/LAW169` on a plain `/PROP/SOLID` is starter ERROR
    3047. MAT_252 deliberately does NOT trigger the material route (d2r
    sends it to the plain solid property; LAW120 is SOLID_ALL — legal on
    both). Pairing enforcement from the starter source
    (`check_mat_elem_prop_compatibility.F:228-232`: TYPE43 takes PROP_SOLID
    classes 4/6/7 = laws {59,83,116,117,169} ∪ {13,120} ∪ {77,88}): every
    off-class pairing warns naming ERROR 3047 + ERROR 658 — both measured
    verbatim on a negative control (`PROPERTY ID 100 OF TYPE 43 IS NOT
    COMPATIBLE WITH MATERIAL ID 5 OF TYPE 36` plus the 658 mirror `MATERIAL
    TYPE 36 IS NOT COMPATIBLE WITH PROPERTY TYPE 43`, exit 2) — aggregated
    per (section, law) so a many-part shared section produces one line, not
    one per part (the LAW169 volume-density and LAW120-Thick notes
    aggregate the same way). The REVERSE orientation is warned too: a
    cohesive material (LAW116/117/169) referenced by SHELL parts — LS-DYNA's
    cohesive-shell path, `*SECTION_SHELL` ELFORM 29 — has no Radioss
    counterpart at all, and the emitted `/MAT` + `/PROP/SHELL` pairing is
    the starter's ERROR 3046 + 658 (live-confirmed); without the warning the
    only trace was the generic ELFORM→Ishell remap note, which mislabels the
    cohesive-shell formulation as an integration choice. Node ordering passes through
    unpermuted (LS-DYNA bottom 1-2-3-4 / top 5-6-7-8 IS TYPE43's t-axis
    convention); pentahedron cohesives (±21/22, `N1 N2 N3 N3 N5 N6 N7 N7`)
    stay the same degenerate `/BRICK` pattern; zero-height pads survive the
    degenerate-element screens (8 distinct ids) and took their full `ρ·A`
    mass on the validation run. `*SECTION_SOLID_MISC` is now a registered
    spelling: card-2c `COHTHK` (supersedes `*MAT_240 THICK` in LS-DYNA) →
    `True_thickness`, its exact Radioss analogue. Card 2c is OPTIONAL in the
    manual and holds only field 1, so it is consumed per set only when the
    next line positionally IS one (fields 2..8 blank, field 1 numeric or
    blank) — a multi-set `_MISC` block that omits it no longer loses the
    following set to a mis-stride (`True_thickness` = that set's SECID).
    `COHOFF`, `GASKETT` and the ELFORM 20/22 shell-offset moments warn (no
    TYPE43 mechanism); hourglass control never splits a cohesive part onto a
    `/PROP/SOLID` clone (`_solid_hg_values` gate + a material-route-aware
    skip in `_assign_hourglass_props`); `_target_mat_law` covers all four
    families (beam parts draw the ERROR 3046 wording — none of
    LAW116/117/120/169 declares a BEAM_* or SHELL_* class — and the
    solid-/XREF gate now names the law instead of claiming "no /MAT");
    `all_mat_ids()` includes the four dicts (the ERROR 79 duplicate-id
    guard). No REF-flag registry entries: MAT_138/169/240/252 carry no REF
    field (`ROFLG` is a density-per-area flag, not REF).

  Starter-validated end to end (`starter_win64`, `/BEGIN 2022`, np=1): a
  five-part probe deck (LAW117 + LAW116 on ELFORM 19 incl. a shared-section
  part and a zero-thickness pad, LAW169 material-routed off ELFORM 1, LAW120
  on a plain solid, LAW36 + GENE1 + INIEVO on shells with `/TABLE/1` rerouted
  curves) runs **0 ERROR(S), exit 0**, with two warnings: the documented
  `WARNING 100211` (the only batch-attributable one) and the pre-existing
  GENE1-path `WARNING 3029` (`/PROP/SHELL`'s starter-default PTHICKFAIL
  0.999999 vs the `/FAIL` rider's negative failed-IP-fraction convention —
  the starter reconciles the sign in the engine, verified to delete on the
  first failed IP exactly as `NUMFIP=1` asks); the listing echoes every
  field in the slot the tests assert. `*INCLUDE_TRANSFORM` offsets ship for every spelling —
  negative-encoded curve cells on MAT_138/169 (with MAT_169's conditional
  SDFAC-card index), per-spelling curve-cell tables for the six MAT_240
  variants, and NDIEMC-repeated criterion cells on the DIEM rider.

  **Corpus census + sweep**, `master` (b482c50) vs this branch: zero hits for
  every batch keyword and zero cohesive-ELFORM `*SECTION_SOLID` card-1s in
  both corpora (the repo's 73 `.k`/`.key`/`.dyn` decks and the 127-deck
  `E:\openradioss_run\Ryan_Lee_Examples` tree — a structured scan, not a
  grep), so the sweep is a pure no-movement check: every one of the 200
  decks is byte-identical on `_0000.rad` and `_0001.rad`, with identical
  warning sets and skip lists, 0 exceptions on either side. What this corpus
  cannot see: anything about the new cards — that evidence is the starter
  probe/negative-control pair and the column-exact tests
  (tests/test_adhesives.py: 71 tests + 74 subtests; suite 1963 → 2034
  passed, 2 skipped, 398 → 472 subtests).

- **Viscoelastic batch** (`*MAT_VISCOELASTIC` 006, `*MAT_KELVIN-MAXWELL_-`
  `VISCOELASTIC` 061, `*MAT_GENERAL_VISCOELASTIC` 076 + `_MOISTURE`,
  `*MAT_SIMPLIFIED_RUBBER/FOAM` 181 + `_WITH_FAILURE` /
  `_LOG_LOG_INTERPOLATION`, `*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE` 183,
  `*MAT_SOFT_TISSUE` 091 / `_VISCO` 092) — the roadmap P1 batch. All seven were
  `SKIPPED` before, i.e. the part reached the solver with no material at all.

  - **`*MAT_VISCOELASTIC` (006) → `/MAT/LAW34` (BOLTZMAN)** — the one exact 1:1
    here. LS-DYNA's `G(t) = GI + (G0−GI)·exp(−BETA·t)` is literally LAW34's
    kernel (`engine/.../mat034/sigeps34.F:88-101`:
    `GE = G_INF; GV = G_INS−G_INF; C1 = 1 − EXP(−BETA*TIMESTEP)`), and `BETA` is
    a decay RATE on both sides — no inversion, unlike the `Tau = 1/BETA` the
    MAT_077_O embedded-LAW42 path needs. Card layout from
    `matl34_boltzman.cfg FORMAT(radioss51)`; all four data cards are
    unconditional, `P0/Phi/Gamma0` stay 0 (the air-in-foam term off), and the
    density line stops at column 20 because the reader pre-scans columns 21-40
    for a reference density.
    From R6.1 on each of `BULK/G0/GI/BETA` is a `SCALAR_OR_OBJECT` whose
    NEGATIVE form is a temperature-curve id. LAW34 has no temperature slot, so
    the curve is collapsed to its value at the LOWEST tabulated temperature —
    dyna2rad's rule for `G0/GI/BETA`, applied here to `BULK` as well, which
    dyna2rad never reads (`BULK_CURVES` appears nowhere in `convertmats.cxx`),
    leaving `K = 0`.
    Non-positive fields are graded by what the SOLVER does, not by the
    `matl34_boltzman.cfg` `CHECK` block (which asks for
    `BULK/DECAY/G0/GI/RHO > 0` but is HyperMesh-side — `hm_read_mat34.F`
    contains no `ANCMSG` at all). Measured on `starter_win64` +
    `engine_win64`: `RHO = 0` is the only hard stop (`ERROR 683`); `G0 = 0`
    and `BULK = 0` pass the starter but zero `YOUNG` (and `G0 = 0` gives a
    `1.0E+21` element time step); `GI = 0` is fully LEGAL — "relaxes
    completely" — and runs clean; and `BETA = 0` passes the starter and then
    makes the engine form `C2 = −(1−exp(−BETA·dt))/BETA = 0/0`
    (`sigeps34.F:101`), so every deviatoric stress increment is NaN while the
    run still reports NORMAL TERMINATION (measured: 1114 NaN cycles).

  - **`*MAT_KELVIN-MAXWELL_VISCOELASTIC` (061) → `/MAT/LAW40` (KELVINMAX)** —
    `G_inf = GI`, `G1 = G0 − GI`, `BETA1 = DC`, branches 2-5 zero
    (`p_ConvertMatL61`, CM:3317-3350). `Astass/Bstass/Kvm = 0` is deliberate:
    `hm_read_mat40.F:122-124` turns anything ≤ 1e-20 into INFINITY, which
    disables the Stassi/von-Mises yield surface and leaves pure viscoelasticity.
    Three things dyna2rad does not do. `FO = 1` selects the KELVIN formulation,
    in which `DC` is a *retardation* time constant obeying a different evolution
    equation; LAW40's kernel is `exp(−BETA·dt)`, Maxwell only, so dyna2rad
    converts a Kelvin card as if it were Maxwell **silently** — k2rad emits the
    same card and says so. `SO` (a d3plot strain-output selector) is reported as
    dropped-but-harmless. And the `ERROR 49` Poisson gate
    (`hm_read_mat40.F:126-143`: `nu` computed from `K` against both `G_inf` and
    `G_inf + ΣG_i` must lie in `[0, 0.5)`) is checked up front, with the
    `BULK ≥ (2/3)·G0` remedy in the message.
    LAW40 declares only `SOLID_ISOTROPIC` and `SPH` (`hm_read_mat40.F:184-185`)
    and `sigeps40` is never called from the shell path, so a `*MAT_061` on a
    shell part is `ERROR 3046` — warned, naming `*MAT_006` → LAW34 (which has
    the identical Maxwell `G(t)` and IS shell-capable) as the substitute.
    dyna2rad emits it with no check at all.

  - **`*MAT_GENERAL_VISCOELASTIC` (076, + `_MOISTURE`) → `/MAT/LAW42` +
    `/VISC/PRONY`.** The elastic carrier is `p_ConvertMatL76` verbatim
    (CM:4457-4472): `Nu = 0.495`, `Mu_1 = +0.01·BULK`, `Mu_2 = −0.01·BULK`,
    `alpha = ±2`. LAW42 has no bulk field — the starter derives one from `Nu`
    (`hm_read_mat42.F:193-195`) — so a warning states what that construction
    really encodes: ground shear modulus `0.02·BULK`, effective bulk modulus
    `1.993·BULK`, plus the `Nu` that would pin `BULK` exactly.
    The Prony series goes onto the separate `/VISC/PRONY`, the only Radioss
    card carrying all four LS-DYNA columns (LAW42's own embedded `Gamma/Tau`
    arrays have no bulk column and use relaxation *times*). Four dyna2rad
    defects fixed rather than reproduced: `BETAKI` is written (dyna2rad asks the
    reader for `"BETAK"`, CM:4526, so every bulk decay constant is lost and the
    bulk branch runs with `Ki ≠ 0`, `β_ki = 0`); the `LCID`/`NT` +
    `LCIDK`/`NTK` relaxation-curve form becomes `Itab = 1`, so the starter runs
    the same Levenberg-Marquardt Prony fit LS-DYNA does — dyna2rad's `Itab=1`
    branch is **unreachable**, because it reads the second curve through
    `sdiIdentifier("LSD_LCIDK")` and the cfg attribute is `LSD_LCID2`
    (CM:4496), and its `Ifunc_G`/`Ifunc_K` would in any case land on the LAW42
    MATERIAL, which has no such fields (CM:4509-4516); an ELASTIC MAT_076 gets
    NO `/VISC/PRONY` at all instead of dyna2rad's unconditional empty block,
    which is `ERROR 2026` and stops the whole deck; and the numeric spelling
    `*MAT_076`, missing from dyna2rad's keyword table (so it falls into the raw
    1:1 dump), is registered.
    `/VISC/PRONY` carries a single `M` for both fits, computed as
    `min(max(NT, NTK), 6)`. The "if zero, the default is 6" rule (p.2-560)
    applies per fit and only to a fit that RUNS: LS-DYNA fits the bulk series
    only when `LCIDK` is given, so an absent curve contributes 0, not 6 —
    otherwise `M` is pinned at 6 for every single-curve card, `NT` is thrown
    away, and a 10-point curve that LS-DYNA fits with `NT = 2` trips the
    starter's `2·M < npoints` rule (`hm_read_visc_prony.F:473`, `ERROR 1921`).
    Verified on `starter_win64`: `NT = 2` on a 10-point
    `G(t) = 200 + 1000·exp(−t/0.05)` returns `G = 999.9999997806`,
    `BETA = 20.00000000532` plus the equilibrium term, cost function
    `7.1E−19`; the same curve at `M = 6` is `ERROR 1921` ("THE MAXIMUM ORDER
    IN THIS CASE IS : 5"). `NT ≠ NTK` with both curves present is warned,
    since only the larger survives.
    `PCF` is *not* written into `sigma_cut`: that field is a stress, not a flag,
    and a literal 1.0 would impose a 1-unit tensile cut-off. `EF`, the
    `TREF/A/B` WLF/Arrhenius shift, the `BSTART/TRAMP` fit seeds and the whole
    `_MOISTURE` card are warn-dropped (dyna2rad drops them silently and does not
    even parse the moisture card).

  - **`*MAT_SIMPLIFIED_RUBBER/FOAM` (181) and `*MAT_SIMPLIFIED_RUBBER_WITH_-`
    `DAMAGE` (183) → `/MAT/LAW88` (TABULATED_HYPERELASTIC)**, layout from
    `mat_law88.cfg FORMAT(radioss2017)` — EXACTLY three cards plus the `NL`
    rows. The radioss2026 revision adds an `SGL/SW/ST/G/SIGF` card and a
    `KFAIL/GAM1/GAM2/EH/FAILIP` card that a `/BEGIN 2022` starter **swallows
    without an error** (measured: `SGL = 0.05` reads back as `1.0`), so emitting
    them would be silent data loss rather than a diagnosable version complaint —
    they are warn-dropped instead, and the specimen normalization is baked into
    the curve POINTS (abscissa `× 1/SGL`, ordinate `× 1/(SW·ST)`, into a
    `_Duplicate` auto-`/FUNCT`; the original curve is left untouched).
    `F_SMOOTH` is written blank because the current starter never calls
    `hm_get_intv('LAW88_Fsmooth')` — those ten columns are consumed by the
    format and discarded.
    A `*DEFINE_TABLE` `LC/TBID` becomes the `FCT_ID_LI`/`EPSI_LI` rate family
    with the highest-rate curve REPEATED at 10× that rate (dyna2rad's deliberate
    flat-extrapolation guard, CM:5022-5027), guarded here against a
    non-increasing extra rate, which would be `ERROR 478`; a `*DEFINE_CURVE`
    becomes a single row at rate 1.0. Unloading follows dyna2rad's priority:
    `LCUNLD` → `HU`/`SHAPE` (181 only, and only when the optional card 4 is
    really present — `HU` defaults to 1.0 per the cfg, so a BLANK `HU` on a
    present card is 1.0, not 0) → the loading curve itself, which the starter
    then nulls out.
    **What `FCT_ID_UN` is, and is not.** The `LCUNLD` → `FCT_ID_UN` mapping is
    right (the starter echoes `UNLOADING STRESS-STRAIN FUNCTION ID = 20`) and
    hysteresis really does appear, but LAW88 does NOT follow the unloading
    curve as a stress-strain path. `hm_read_mat88.F90:405-421` forces the
    unloading curve's two endpoints onto the loading curve's and then rescales
    both axes, and `sigeps88.F90:762-790` uses the result only as a scalar
    shape ratio `R = g_unl(x̂)/g_load(x̂)` clamped to `[0,1]`, applied to all
    three principal stresses. Measured on a fully-prescribed isochoric
    load-unload cycle: two runs with DIFFERENT `LCUNLD` shapes returned
    byte-for-byte the same `R`, and the deviatoric axial stress collapsed to
    `R ≈ 0.001` (99.96 % of the stored energy dissipated) where the
    curve-ratio implies `R = 0.38..0.89`. So an LS-DYNA MAT_183 hysteresis
    loop is not reproduced curve-for-curve. This is engine-side, not a
    conversion defect — nothing to fix in k2rad, but do not read the converted
    unloading curve as the path the material will take.
    Four more dyna2rad defects fixed: `TENSION` is transferred (dyna2rad asks
    for `"TENSIOM"` for MAT_181, CM:5150 — the only occurrence of that string in
    the entire Radioss tree — so its rate-effect flag never arrives and the
    material silently falls back to "compressive loading only"; it gets MAT_183
    right); `PR` goes into `NU` verbatim, because LAW88's own
    `nu ≤ 0 → beta = |nu|, nu := 0.495` rule (`hm_read_mat88.F90:186-191`) IS
    LS-DYNA's `PR ≤ 0` viscous-pressure input, which dyna2rad loses by writing
    `NU = 0`; a blank `SGL`/`SW`/`ST` reads as 1.0 instead of dyna2rad's refusal
    to write ANY curve unless all three are non-zero (CM:4955), which turns a
    deck whose curve is already engineering stress-strain into `NL = 0`, i.e.
    `ERROR 866` — and for MAT_183 leaves the two scale factors literally
    uninitialised (CM:5165-5166); and `*MAT_183`, also missing from dyna2rad's
    keyword table, is registered.
    `0 < PR < 0.49` selects LS-DYNA's COMPRESSIBLE Hill FOAM formulation, which
    LAW88 has no branch for. dyna2rad's `ConvertMatL181ToMatL70` foam converter
    exists in its source but has **no caller** (`grep` matches only the
    declaration and the definition), so every simplified foam silently becomes
    an incompressible rubber — loudly warned here, naming
    `*MAT_LOW_DENSITY_FOAM` / `*MAT_FU_CHANG_FOAM` as the alternatives.
    `MU` (a `/PROP/SOLID` viscosity field in dyna2rad, which would need a
    per-part property split here), `RTYPE`, `AVGOPT`, `PRTEN`, `STOL`,
    `HISOUT`, `VFLAG` and the `_LOG_LOG_INTERPOLATION` option are warn-dropped.
    `REF` is NOT dropped — see the `/XREF` note under *Plumbing*.
    A loading curve with no NEGATIVE-strain branch is warned: LAW88
    interpolates the same curve at all three principal stretches
    (`sigeps88.F90:375-377`), so uniaxial tension drives the two lateral
    stretches into compression, where a tension-only table is extrapolated.
    Measured on a single-element cell: the lateral stretches bifurcated at
    `eps = 0.65` (`lam2` 0.79 → 0.41 while `lam3` grew to 1.45, kinetic energy
    up four decades) and the run still reached NORMAL TERMINATION with wrong
    results; adding the compression branch fixed it exactly
    (`lam2 = lam3 = 0.70734` at `eps = 1`, `J = 1.00066`).
    The rate family is clamped to the starter's `maxfunc = 128`
    (`hm_read_mat.F90:294`), which sizes `ifunc/rate/yfac/lambda` at
    `maxfunc+1` and then reads `do i = 1,nl` with no bound — an over-long
    `*DEFINE_TABLE` would be an out-of-bounds write rather than a diagnosable
    error.
    MAT_181's optional `Gi/BETAi` cards become a `/VISC/PRONY` of the material
    id, with the LS-DYNA `VISCO`/solids-only gate reported rather than enforced
    (older card-4 layouts have no `VISCO` field at all).

  - **`*MAT_SOFT_TISSUE` (091) / `_VISCO` (092) → `/MAT/LAW42`** —
    `Mu_1 = 2·C1`, `Mu_2 = −2·C2`, `alpha = ±2`, `Nu = 0.495`
    (`p_ConvertMatL91_92`, CM:10973-11026), with the `S_i`/`T_i` pairs in
    LAW42's own `Gamma_arr`/`Tau_arr` — relaxation TIMES on both sides, so `T_i`
    needs no inversion, and no `/VISC/PRONY` is involved. The non-zero pairs are
    COMPACTED: dyna2rad counts every non-zero `S_i` but then copies slots
    `0..M−1`, so an `S1 = 0` with `S2 ≠ 0` converts the wrong terms — and it
    indexes an `sdiDoubleList` that was only `reserve()`d, not `resize()`d,
    which is out of bounds on top of that (CM:11001-11021).
    This keyword gets the loudest warning in the batch, because the conversion
    is a real fidelity loss and dyna2rad performs it in silence: the material
    becomes an **isotropic incompressible Mooney-Rivlin rubber**, and the
    transversely-isotropic collagen fibre term (`C3/C4/C5`, `XLAM`, `XLAM0`,
    `FANG`), the entire fibre orientation (`AOPT`, the a/b vectors, `LA1-LA3`,
    `MACF`), the bulk modulus `XK` and all three `FAILS*` modes are dropped. For
    a ligament or tendon, where the fibre term dominates, that is not a
    physically equivalent material. A second warning names the unit mismatch it
    inherits — LS-DYNA's `S_i` are DIMENSIONLESS relaxation factors, while
    Radioss multiplies `Gamma_i` by a strain-history term
    (`engine/.../mat042/sigeps42.F:475`), i.e. reads it as a shear MODULUS — and
    prints the `S_i · MU0` values (`MU0 = 2·(C1+C2)`) that would carry the
    intended viscous stiffness.

  - **Plumbing.** `_target_mat_law` (`writer/mesh.py`) gained all five families
    (34 / 40 / 42 / 88), which reaches both of its callers: the `/PROP/BEAM`
    compatibility warning and `writer/inistate.py`'s solid-`/XREF` gate. LAW42
    and LAW88 are both in `_XREF_SOLID_LAWS`, so a `*MAT_076/091/092/181/183`
    solid part in a deck with `*INITIAL_FOAM_REFERENCE_GEOMETRY` now RECEIVES a
    `/XREF` (and its section switches to `Ismstr=10`) where it used to be
    warn-skipped — asserted, not assumed. Because that makes the `REF` flag
    reachable for these families, BOTH directions are now reported, off one
    shared registry (`writer/common.py::_ref_flag_materials`, which also feeds
    the four older rubber families): `REF = 1` with no usable reference
    geometry says nothing was initialized, and a `/XREF` landing on a
    `REF = 0` material says the block was emitted anyway. The emission stays
    unconditional — that is dyna2rad's rule and the pre-existing k2rad
    behaviour, so already-validated rubber decks do not move — but LS-DYNA
    would not apply it there (`EQ.0.0: Off`), so the deviation is stated
    instead of left in the results. Neither beam frozenset changes: LAW34
    is BEAM_INTEGRATED (`hm_read_mat34.F:162`) and already listed, LAW40/42/88
    declare no beam class at all; the classification is recorded above the sets
    with the `hm_read_matNN.F` line for each. The two existing `/VISC/PRONY`
    writers were refactored onto one `_visc_prony_lines` core which now also
    serves the four-column and `Itab=1` forms; since no checked-in golden uses
    `*MAT_077_H` or `*MAT_124`, that refactor was verified directly — a probe
    deck carrying both converts to the identical starter file on `master` and
    on this branch (`sha256 fdae79c734b6a9f43ae9a638e647acb24ca57d3f55985abb4d47fa127839f659`).

  **Starter-validated** (`starter_win64`, `/BEGIN 2022`): a nine-part probe deck
  carrying every keyword runs **0 ERROR(S), 2 WARNING(S)** — both the cosmetic
  `WARNING 1927` ("least square fitting has converged, but Prony parameters
  values must be checked") that the `Itab=1` fit always raises. The starter's
  own echo confirms the field-by-field placement asserted in the tests:
  `SHEAR MODULUS (SHORT TIME) = 100.0` / `(LONG TIME) = 20.0` /
  `DECAY CONSTANT = 300.0` (LAW34); `LONG TIME SHEAR MODULUS = 20.0`,
  `SHEAR MODULUS 1 = 80.00000000000` (= `G0 − GI`) and
  `STASSI A COEFFICIENT = 1.0000000200409E+20` (LAW40);
  `INITIAL SHEAR MODULUS = 40.0` with `BULK MODULUS = 3986.666666667` for
  `BULK = 2000` (LAW42/076, the 1.993× the warning predicts);
  `BETAK DECAY BULK MODULUS = 2.000000000000` / `0.4000000000000`
  (`/VISC/PRONY` — the column dyna2rad drops);
  `TABULATED PRONY SERIES FLAG = 1` with
  `LEAST SQUARE FITTING FROM SHEAR MODULUS G FUNCTION ID = 801`;
  `NUMBER OF LOADING FUNCTIONS (NL) = 4` with rates `1e-3 / 1 / 100 / 1000` and
  the last two on the same function id, `RATE EFFECT FLAG (TENSION) = 1`,
  `HYSTERETIC UNLOADING FACTOR = 0.7`,
  `SPECIMEN GAUGE LENGTH (SGL) = 1.000000000000` (the forced value that makes
  the point-level rescale necessary) and
  `EXPONENTIAL FILTERING FREQUENCY (BETA) = 5.0E-02` for `PR = −0.05` (LAW88);
  and `RELAXATION TIME = 1.0E-02` (LAW42/092).

  Two checks that can FAIL rather than merely pass. The `Itab=1` route was
  verified **quantitatively**: relaxation curves built as
  `1000·exp(−t/0.05) + 200` and `2500·exp(−t/0.08) + 500` came back out of the
  starter's own fit as `G = 999.9999728409` / `BETA = 20.00000377956`,
  `K = 2499.999582091` / `BETAK = 12.50000591816`, plus the two equilibrium
  terms `200.0000972109` / `500.0008474738` at `β ≈ 2e-6`. And a **negative
  control** — pointing `Ifunc_G` at an id no `/FUNCT` defines — makes the same
  starter answer `ERROR 1928`, so the clean run is a real check.

  **Engine-validated.** A single-element shear-relaxation run of the LAW34
  mapping (10 mm hex, bottom face fixed, top face ramped to `gamma = 0.01` over
  100 µs and held to 20 ms, `NORMAL TERMINATION` at 3254 cycles):
  `sigma_xy(t)/gamma` traces `GI + (G0−GI)·exp(−BETA·t)` with a worst relative
  error of **0.007 %** over 195 output states, once the finite ramp is accounted
  for — the best-fit time shift is 94 µs against the 100 µs half-ramp of the
  prescribed motion, which is the offset it should be. Without the shift the
  residual is a flat 2.2 %, i.e. `exp(BETA · 74 µs)`, and monotonically
  decaying — the signature of a time offset, not a modelling error.

  82 tests in `tests/test_viscoelastic.py` (1874 → 1956 repo-wide,
  302 → 398 subtests). Fourteen of them came out of the review pass below and
  cover the two `*INCLUDE_TRANSFORM` offset callables end-to-end — both
  mutation-checked, since registry membership alone cannot catch a wrong card
  index (`_off_mat_181`'s `_WITH_FAILURE` shift) or a skipped `IDFOFF`
  (`_off_mat_006`'s negative temperature-curve cells).

  **Corpus SHA256 sweep**, `master` (fa474ec) vs this branch: **every one of the
  73 `.k`/`.key`/`.dyn` decks in the local corpus is byte-identical** on both
  `_0000.rad` and `_0001.rad`, and so is the full warning set per deck. Re-run
  after the review pass over a wider set — the same 73 plus the whole
  127-deck `E:\openradioss_run\Ryan_Lee_Examples` tree, 201 conversions per
  tree — still 0 starter, 0 engine and 0 warning-set differences, 0 exceptions
  on either tree.
  This is a pure-addition batch and no deck in the
  corpus carries any of these seven keywords: zero hits for
  `*MAT_VISCOELASTIC`, `*MAT_GENERAL_VISCOELASTIC`,
  `*MAT_KELVIN-MAXWELL_VISCOELASTIC`, `*MAT_SIMPLIFIED_RUBBER*`,
  `*MAT_SOFT_TISSUE*` and every numeric alias, across the whole repo tree and
  — checked separately, because they are the largest real decks available and
  the only ones that touch `_law42_lines` at all — the 161 MB Toyota Yaris and
  237 MB Camry `.key` files under `E:\openradioss_run`.
  That also means the repo corpus contains **zero** `*MAT_BLATZ-KO_RUBBER` /
  `_MOONEY-RIVLIN_` / `_OGDEN_` / `_HYPERELASTIC_RUBBER` cards, i.e. not one of
  its 73 decks exercises the shared `_law42_lines` emitter at all — so it
  cannot detect a regression there. The two decks that DO were swept
  separately: the 161 MB Toyota Yaris (13 hyperelastic-rubber cards) and the
  237 MB Camry (19), both byte-identical on `_0000.rad` and `_0001.rad`
  (`yaris 0000 c4867716…`, `0001 abe6c972…`; `camry 0000 04b8d704…`,
  `0001 6e911aa1…`).

  What this corpus *cannot* see: for this batch, **anything about the new
  cards**. The sweep is a pure no-movement check. Every claim about the
  emitted cards rests on the synthetic probe decks run through the live starter
  and engine, and on the unit tests — which were themselves mutation-checked
  (breaking `G1 = G0−GI`, forcing LAW88 `TENSION` to 0, re-introducing
  dyna2rad's dropped `Beta_ki`, restoring the `NTK`-defaults-to-6 bug,
  disabling the `REF = 0` `/XREF` check, and flattening `_off_mat_181`'s
  `_WITH_FAILURE` card shift each make the intended test fail, so they are
  checks that can fail).

  **Review pass.** Two defects found and fixed before merge, both confirmed
  against the OpenRadioss source and a live solver rather than argued:

  1. *MAT_076 `NTK` defaulted to 6 even with no bulk curve*, pinning
     `/VISC/PRONY` `M` at 6 for **every** `Itab=1` deck. Beyond discarding the
     user's `NT`, that broke convertible decks: `hm_read_visc_prony.F:473`
     needs `2·M < npoints`, so a 10-point curve LS-DYNA fits with `NT = 2`
     stopped the starter with `ERROR 1921` — an error k2rad's own warning then
     presented as inherent rather than self-inflicted. Fixed to default each
     order only when its own curve exists, and re-validated on the starter
     (see the MAT_076 entry above).
  2. *`REF` was reported backwards.* MAT_181/183 listed `REF` as a dropped
     field with "REF needs `*INITIAL_FOAM_REFERENCE_GEOMETRY` for a real
     `/XREF`" on runs that emitted `/XREF/7`, and MAT_091/092 parsed `REF` and
     never mentioned it at all. Both directions are now reported off one shared
     registry covering all six REF-bearing families.

  Also from the review, each verified first: the LAW34 zero-field warning was
  re-graded by measurement (`GI = 0` is legal and was being called fatal;
  `BETA = 0` was being called merely unreadable when it is a silent NaN run);
  a tension-only LAW88 loading curve is now warned; the LAW88 rate family is
  clamped to the starter's `maxfunc`; an unresolved `*DEFINE_TABLE` no longer
  reports itself as a missing `*DEFINE_CURVE`; four write-only `MatViscoelastic`
  fields were removed and the two write-only `MatSoftTissue` ones (`AOPT`,
  `MACF`) are now printed by the fibre-drop warning instead of being named as
  prose; and the MAT_061 shell scan was hoisted out of its per-material loop.

- **Spotweld joining** (`*CONTACT_SPOTWELD` + `_WITH_TORSION` / `_BEAM_OFFSET` /
  `_CONSTRAINED_OFFSET`, each × `_PENALTY` × `_MPP` × `_ID`;
  `*DEFINE_HEX_SPOTWELD_ASSEMBLY` + `_1` … `_16`; `*DATABASE_SWFORC`) — the
  roadmap P1 batch. All three were `SKIPPED` before, and the loss was not
  cosmetic: on `W16_spotweld_E1` the four `*MAT_SPOTWELD` weld beams
  (nodes 2059–2066) share **zero** nodes with the 2058-node sheet mesh, so the
  nuggets reached the solver attached to nothing but each other and the weld
  force was 0.000 N before *and* after the impact.

  - **`*CONTACT_SPOTWELD` → `/INTER/TYPE2`** with `Ignore=2`, `Spotflag=28`,
    `Idel2=1` — dyna2rad's spotweld defaults verbatim
    (`convertcontacts.cxx:49` `interTypeVsMapDefaultVals["TYPE2"]`, reached
    through the `keyWord.find("SPOTWELD")` branch at `:183-189`). Spotflag 28
    is the auto-penalty spotweld formulation and the kinematic ones are not an
    option here: `chktyp2.F:82` tags a TYPE2's secondary nodes only when
    Spotflag is outside {25,26,27,28}, and any MAIN node carrying that tag is
    hard `ERROR 556`; a weld meshed conformally with the sheets it joins puts
    the same node in both the secondary `/GRNOD` and the main `/SURF`.
    `itagsl2.F:225-245` is the other half — for 27/28 only, a secondary node
    that collides with a rigid body, an `/RBE2`/`/RBE3` or another tie is
    switched to a penalty tie (`WARNING 1179`) instead of failing the run.
    `Idel2=1` (the tie dies with the sheet segment it welds) is what separates
    this from the `*CONTACT_TIED_*` path, which deliberately keeps `Idel2=0`;
    it survives the starter's whitelist because 28 is in it
    (`hm_read_inter_type02.F:269`). The mandatory penalty Card 2
    (`Stfac Visc <20 blanks> Istf` = `1.0 / 0.05 / 2`) is emitted by the same
    `_emit_inter_type2` the tied path uses, which now takes an `idel2` keyword
    argument and is otherwise untouched.

    **The secondary side is resolved over BEAM end nodes**, and that single
    difference is what makes the keyword work. `SSTYP=3` on a spot-weld card
    names the *weld* part, and a weld part is `*ELEMENT_BEAM` nuggets — that is
    the card on every W16/W17 deck in the corpus (`ssid=3 sstyp=3`,
    `msid=1 mstyp=2`). Reusing `_tied_slave_nids`, which walks shells and
    solids only, returns an empty node group and the interface is dropped for
    "no nodes at all", which is worse than skipping the keyword because it
    looks converted. `_spotweld_slave_nids` covers `SSTYP` 0 (segment set),
    1 (shell element set), 2 (part set), 3 (part), 4 (node set) over
    `_part_node_sets`, which already counts beams. The main side reuses
    `_tied_master_surface` (now parameterised with a title tag and a
    `measure=False` switch that skips the surface tessellation the tied path
    needs for its measured `dsearch` and a spotweld does not).

    **`dsearch` comes from the card, and this is one place k2rad exceeds
    native.** dyna2rad reads `SST`/`MST` and then drops them for
    `*CONTACT_SPOTWELD` (`convertcontacts.cxx:61,318` — the
    `dSearch = 0.6*(lsdSST + lsdMST)` branch at `:205` is entered only for
    `TIED_NODES_TO_SURFACE` / `TIEBREAK_NODES`). That is a gap, not a decision:
    the starter's own default for `dsearch = 0` contains the identical
    `0.6*(t_s + t_m)` term (`i2cor3.F:198`,
    `GAPV = MAX(0.05*DD, 0.6*(THKSECND + THKMAIN))`), so feeding it the deck's
    thicknesses can only agree better with LS-DYNA than ignoring them. Both
    must be positive, exactly as dyna2rad's own branch requires; a NEGATIVE
    Card-3 `SST`/`MST` is LS-DYNA's absolute tie-criterion distance and wins
    over the computed value; otherwise 0 = the starter's own default, which is
    what the native reader always gets. Every corpus deck has `SST=MST=0`, so
    the corpus reproduces dyna2rad exactly and the new term only fires on a
    deck that actually supplies thicknesses.

    All **sixteen** legal spellings are generated rather than hand-listed
    (`_SPOTWELD_CONTACT_KEYWORDS`), because the CFG advertises five
    `USER_NAMES` while `contact_spotweld.cfg:827-856` also parses `_PENALTY`
    and `_MPP`, and a missed spelling is a silently unwelded model. `_MPP`
    inserts its own card *before* mandatory Card 1, optionally followed by a
    second card recognised by a literal `&` in column 1
    (`CARD_PREREAD("%-1s")`) — both are stepped over, so `SSID` cannot come
    back as the MPP `IGNORE` flag. The `_WITH_TORSION` / `_BEAM_OFFSET` /
    `_CONSTRAINED_OFFSET` flavours emit the same card as the plain one (there
    is no `/INTER/TYPE2` field for any of them) and **warn** about what was
    dropped — dyna2rad parses the same flag into `ContactOption` and then never
    reads it, so all five spellings convert byte-identically there, silently.
    `*INCLUDE_TRANSFORM` id offsetting is registered for the twelve non-`_MPP`
    spellings from the same generated list; the `_MPP` ones are deliberately
    left to the unmapped warn rather than have `_off_contact` rewrite the MPP
    bucket parameters as if they were `SSID`/`MSID`.

  - **`*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N]` → `/GRBRIC/BRIC` + `/CLUSTER/BRICK`.**
    First `/CLUSTER` card in the converter. `ID_SW` (which sits on its own card,
    not on the keyword line) is reused as the cluster id when it is usable — a
    blank/zero or repeated `ID_SW` is replaced by a generated id with a warning,
    because `/CLUSTER/BRICK/0` puts a literal `0` in the `/TH/CLUSTER` object
    list and `hm_read_thgrki.F:123-137` reads that as *every* cluster
    (`WARNING 3083`), and a repeat is a duplicate-id rejection. `skew_ID=0`
    lets the starter build the weld frame from the cluster's own bottom→top
    face normal (`hm_read_cluster.F:104`); `Ifail=3`. All five data cards are
    emitted unconditionally — the CFG puts no `if` around cards 2–5, and
    omitting one makes the starter read the next keyword's line as a failure
    limit. The `_N` suffix is the total number of ELEMENTS (1…16, Vol I R16
    p.17-300), not a card count.

    **The failure surface: `b1..b4 = 2.0` *paired with* a `min()` resultant
    reduction.** The engine forms
    `DMG = a1*(FN/Fn)^b1 + a2*(FT/Fs)^b2 + a3*(MR/Mt)^b3 + a4*(MB/Mb)^b4`
    (`clusterf.F:386-390`) with `FT = sqrt(Fx²+Fy²)` (`:365`) and
    `MB = sqrt(Mx²+My²)` (`:367`), while `*MAT_SPOTWELD`'s own criterion is
    `(Nrr/NRR)² + (Nrs/NRS)² + … ≥ 1` — quadratic in every term, and scored per
    direction. Two things have to agree, not one:

    - the EXPONENT is 2, where dyna2rad hardcodes 1
      (`convertdefinehexspotweldassembly.cxx:76-79`). With `b=1` a weld at 40 %
      of both its tension and shear limits reaches `DMG = 0.8` and is one small
      increment from failing, against `0.4² + 0.4² = 0.32` in LS-DYNA.
    - the two-direction limits collapse by `Fs_fail = min(NRS, NRT)`,
      `Mb_fail = min(MSS, MTT)`, because Radioss scores ONE shear resultant
      against ONE limit. The obvious `sqrt(NRS²+NRT²)` does *not* agree with
      `b=2`: for `NRS = NRT = S` it makes the shear term `(Fx²+Fy²)/(2S²)`,
      exactly **half** of MAT_100's `(Fx²+Fy²)/S²`, i.e. a weld `sqrt(2)` too
      strong in shear (+28 % to +60 % on `NRS=5000/NRT=4000`). `min()` is exact
      whenever `NRS == NRT` and `MSS == MTT` — the round-nugget norm — and
      conservative otherwise; the warning names the anisotropic case.

    `Fn_fail1 = NRR` and `Mt_fail = MRR` are single-direction and pass straight
    through. Starter-echo confirmed: `FAILURE EXPONENT N1..N4 = 2.0`,
    `FAILURE COEFFICIENT A1..A4 = 1.0`, `MAX TANGENT FORCE = 20000.0`.
    Solver-confirmed on a pure in-plane-shear hex weld: the engine's own `FAIL`
    channel matches `DMG` recomputed from the emitted card to **0.0000 %** at
    every sampled state, and equals MAT_100's criterion to **+0.0000 %** — where
    the `sqrt` reduction scores **−50.0000 %** on the same measured state.

    Element ids that are not 8-node `/BRICK` are screened out of the group with
    a warning naming them. Not because the starter rejects them — measured, it
    does not: a `/GRBRIC/BRIC` listing a `/TETRA4` id resolves and the cluster
    counts it, 0 ERROR(S). Because the result is silently wrong:
    `hm_read_cluster.F:201-205` takes the weld's two joined faces from
    `IXS(2:5)` and `IXS(6:9)` — the hex's bottom and top faces — so a collapsed
    tet contributes a degenerate top face and corrupts the local frame, and
    with it the FN/FT/MR/MB split the entire failure surface is evaluated on,
    for the *whole* weld. The Reference Guide says the same in prose
    (`/CLUSTER` comment 2, 8-node hexa only) and notes it is not code-enforced.
    An assembly with no usable brick, or with no reachable MAT_100 (every limit
    0, which the starter promotes to INFINITY → a weld that never fails), is
    reported with its physical consequence rather than left to be discovered in
    the results.

  - **`*DATABASE_SWFORC` → `/TH/SPRING` + `/TH/BRIC` + `/TH/CLUSTER`**, matching
    dyna2rad's own split (`dyna2rad.cxx:613-695`, where `SWFORC` appears TWICE
    in `dbCardList`: i=3 filters `*ELEMENT_DISCRETE`/`*ELEMENT_BEAM` on a
    MAT_100 part to `/TH/SPRING`, i=4 filters `*ELEMENT_SOLID` to `/TH/BRIC`)
    plus the `/TH/CLUSTER` its hex-weld converter emits separately
    (`convertdefinehexspotweldassembly.cxx:315`). The spring list is the
    MAT_100 beams the connector writer actually emitted — the PR #104 path
    writes `sprg_ID = e.eid` under a `/SPRING/<original PID>`, so the ids are
    the deck's own and a T01 channel maps 1:1 onto an swforc row, but that
    writer skips a whole part for zero-length welds, a missing `*SECTION_BEAM`
    or a zero cross-section area. Naming a skipped id is not a lost channel, it
    is `ERROR 69` (`hm_read_thgrne.F:189`, `MSGTYPE=MSGERROR`) and the deck is
    refused outright, so the emitted ids are tracked on state and intersected
    here, with a warning listing what was lost. Two variable-list corrections
    over dyna2rad:
    `/TH/SPRING` asks for **`DEF FAIL`** (index 66 `FAIL`, the weld rupture
    flag, is not in `DEF` — `hm_read_thgrou.F:1519` — and on a weld it is the
    channel swforc is *about*), and `/TH/CLUSTER` asks for **`DEF FLOC`**
    (`FLOC` = the local `FS`/`FN`/`MS`/`MN` weld resultants,
    `hm_read_thgrou.F:1763-1766`; dyna2rad requests `DEF` alone, so the local
    frame never reaches its T01). Object ids follow the two different reader
    paths: one per line for `/TH/SPRING` and `/TH/BRIC` (`hm_read_thgrne.F`),
    ten per line for `/TH/CLUSTER` (`hm_read_thgrki.F`). A deck that requests
    swforc with no weld at all gets a warning and **no** block — a `/TH` group
    listing nothing is a starter error. `db_swforc_dt` also joins the `/TFILE`
    selection, which a SWFORC-only deck previously fell through to the 1e-3
    default.

  **Starter-validated** (`starter_win64`, `/BEGIN 2022`): the converted
  `W16_spotweld_E1` runs **0 ERROR(S)** and the starter echoes
  `FORMULATION LEVEL = 28`, `SEARCH FORMULATION = 2`, `STIFFNESS FACTOR = 1.0`,
  `STIFFNESS FORMULATION = 2`, `CRITICAL DAMPING FACTOR = 5.0E-02`,
  `IGNORE FLAG = 2`, `DELETION FLAG CASE FAILURE OF MAIN ELEMENT SET TO 1` —
  every field asserted in the tests. A hex-weld probe deck echoes
  `SPOTWELD CLUSTER OF BRICK ELEMENTS`, group id, `FAILURE FLAG = 3`,
  `MAX NORMAL FORCE`, `MAX TANGENT FORCE`, `MAX TORSION MOMENT`,
  `MAX BENDING MOMENT`, and `A1..A4 = 1.0` / `N1..N4 = 2.0`. The `/TH` variable
  names were confirmed by a **negative control**: replacing the emitted
  `DEF FLOC` with the CFG GUI's `FT MB` makes the same starter answer
  `ERROR 260` on the same THGROUP — so the clean run is a check that can fail.

  **Engine-validated.** `W16_spotweld_E1` reaches `NORMAL TERMINATION` at
  t = 0.1 s (1 712 068 cycles): the four welds transmit 12.1 kN at 1 mm rising
  smoothly to 57.4 kN at 10 mm, agreeing with the independent external-work
  slope to within ±0.8 % at every checkpoint. Deleting only the `/INTER/TYPE2`
  block from the same converted deck drops the weld force to **exactly 0.000 N**
  with 99.07 % free separation between the sheets, against 1.25 % with the tie —
  that is the loss this batch repairs, measured. `W16_spotweld_E1_Fail` ruptures
  at t = 0.02472 s against 0.0247 s predicted from the no-fail curve (+0.08 %),
  at F = NRR = 5000 N (+0.04 %), and the `FAIL` channel is exactly `(F/NRR)²`.
  A synthetic hex-weld deck's `/TH/CLUSTER` normal force lands on the applied
  405.0 N to −0.001 %, and a pure-shear variant reproduces MAT_100's damage to
  +0.0000 % (see the failure-surface note above).

  79 tests in `tests/test_spotweld_joining.py` (1795 → 1874 repo-wide,
  231 → 302 subtests).

  **Corpus SHA256 sweep**, `master` (68cf5e7) vs this branch: the decks that
  change are the eight carrying one of the three keywords —
  `W16_spotweld_E1`, `W16_spotweld_E1_Fail`, `W16_spotweld_D1`,
  `W16_InitialModel_spotweld_D1`, `W16_SW_door_{INITIAL,NoFail,Fail}`,
  `W17_RS_FloorFrame` — plus `W2_Door_Impact` (the master-surface repair below)
  and, from the `/TH/INTER` fix below, `W6_SETUP_SandwichImpact` and
  `W15_SETUP_Fabric_Impact_model`. Everything else is byte-identical, including
  the whole `implicit_hr-anlenkung` family (spot-checked byte-for-byte, and
  provably on the unchanged path: no dropped interface, and its `*DATABASE_*`
  minimum is already what the old first-non-zero rule picked). What this corpus
  *cannot* see: no deck in it has a `*DEFINE_HEX_SPOTWELD_ASSEMBLY`, a MAT_100
  SOLID part, an `_MPP` or `_WITH_TORSION` spelling, or a nonzero Card-3
  `SST`/`MST` on a spotweld card — every one of those paths is covered only by
  the unit tests and the probe decks run through the live solver.

### Fixed

- **`/TH/SURF` blast surfaces beyond the SPMD-reduced prefix recorded exactly
  0.0 — inert padding `/SURF` cards now keep every one inside it.** Observed
  2026-08-03 on two independent OpenRadioss 2026 MPI runs: the single
  `/TH/SURF` block from `*DATABASE_BINARY_BLSTFOR` listed every blast-loaded
  surface, yet only the lower-indexed ones carried P/A data
  (`E:\w13\stack4\run\main_blastT01.csv`: surface 90031 peak 222.7 MPa at
  64 µs, surface 90034 all-zero; `E:\w13\neuberger\run_fine\neubergerT01.csv`:
  90001 peak 25.2 MPa, 90003 all-zero). NOT a "one surface per block" limit —
  multiple ids per block are legal and fully wired (starter
  `hm_read_thgrsurf.F:147-175` flags each listed id, the segment→surface CSR
  in `th_surf_load_pressure.F` maps every loaded segment to every containing
  TH surface, engine `thsurf.F:71-80` writes one var-set per surface). The
  root cause is an OpenRadioss engine bug: the `/TH/SURF` channel array is
  `(TH_SURF_NUM_CHANNEL=6, NSURF)` (`th_surf_mod.F:96-100`, global surface
  count per `resol_alloc.F90:336`), but the MPI reduction covers only its
  first `5*NSURF` elements — `engine/source/output/th/hist2.F:679`
  `IF(NSPMD > 1)CALL SPMD_GLOB_DSUM9(FSAVSURF,5*NSURF)`, a stale length from
  before the 6th channel existed. Column-major, surface I channel c sits at
  flat position `6*(I-1)+c`, so any surface violating
  `6*(I-1)+5 <= 5*NSURF` never gets its P (ch4) / loaded-area (ch5) summed
  across domains; domain 0 then writes its local zeros and `hist2.F:687-691`
  zeroes P outright when the unreduced ch5 stays 0. The arithmetic locks all
  four observations: stack4 (12 domains, 13 surfaces) 90031 = 10th surface →
  positions 58/59 ≤ 65 ✓ correct, 90034 = 12th → 70/71 > 65 ✗ zero;
  neuberger (6 domains, 2 surfaces) 90001 = 1st ✓, 90003 = 2nd → ch4 at
  position 10 reduced but ch5 at 11 not, divide-guard zeroes P ✗. (Had
  `/SURF/PLANE` not counted toward NSURF, 90031 — 10th of 11, position
  59 > 55 — would have failed too; it did not, pinning the index model.)
  `writer/assembly.py:_pad_surfaces_for_spmd_th_surf` now runs after all
  starter sections and appends `K = ceil((6*I_max − 1 − 5*NSURF)/5)` inert
  `/SURF/SEG` cards (a copy of one blast segment, referenced by nothing,
  ids from `next_id()` so they sort last under both deck-order and id-order
  numbering) — 1 card on the neuberger deck, 2 on stack4 — plus a conversion
  log warning naming the engine bug. Harmless on SMP runs; drop once the
  engine is fixed upstream (`5*NSURF` → `TH_SURF_NUM_CHANNEL*NSURF`).
  Regression: `tests/test_th_surf_spmd_padding.py` pins the block shape, the
  padding count/position/ids, the donor segment and the no-padding cases.

- **`/TH/INTER` listed contacts the writer had dropped**, so the starter
  answered `WARNING 257 NONEXISTENT INTER <id>` on decks that otherwise convert
  clean. The id list was built from the PARSED `*CONTACT` records; a contact
  whose side resolves to no geometry is dropped with a loud warning but its
  record stays in state. `_drop_interface` — the single choke point every
  contact writer goes through — now records the id, and the `/TH` builder
  subtracts it. Removes the warning from `W17_RS_FloorFrame` (10 → 9 warnings)
  and `W16_SW_door_NoFail` (8 → 7); on `W6_SETUP_SandwichImpact`, whose only
  contact is dropped, the whole dangling `/TH/INTER` block now correctly
  disappears and the existing "no interface to output" warning fires instead.
  Also affects `W15_SETUP_Fabric_Impact_model` (two ids).

- **`/TFILE` took the first non-zero `*DATABASE_*` interval, not the minimum.**
  Radioss has one time-history frequency for the whole T01, and an `or`-chain
  hands it to whichever card sits earliest in a fixed order — `*DATABASE_NODOUT`
  first. A deck asking `NODOUT DT=0.01` and `SWFORC DT=1e-5` therefore sampled
  every weld channel 1000× coarser than requested. Now the minimum over the
  whole family, which can only ever write more data than asked for, never less.
  No corpus deck changes (in all 13 decks with mixed intervals the minimum is
  already what the old rule picked).

- **`*DEFINE_HEX_SPOTWELD_ASSEMBLY` element ids were not offset under
  `*INCLUDE_TRANSFORM`.** The keyword had no `_OFFSET_SPECS` entry, so its
  `EID` cards kept the un-offset ids, no `*ELEMENT_SOLID` matched, and
  `_make_hex_spotweld_clusters` emitted **no** `/CLUSTER/BRICK` at all — the hex
  weld silently lost its failure criterion and held for the whole run. Now every
  field after the `ID_SW` card moves with `IDEOFF`; `ID_SW` itself has no
  offset bucket and stays put.

- **Comma/free-format element cards on `*DEFINE_HEX_SPOTWELD_ASSEMBLY` were
  silently corrupted.** The `EID` cards used a bare `parse_fixed(row, 8, 10)`
  while the `ID_SW` card two lines above already used `_card`, so a line written
  `101,102,103` sliced to `['101,102,10', '3', …]`: ids 101/102/103 were dropped
  and element **3** was silently added to the weld cluster, with no warning if
  element 3 happens to be a solid.

- **`*CONTACT_..._TITLE` read Card 1 off its own heading line.**
  `_parse_contact_header` handled `_ID` only, so a `_TITLE` block came back
  `ssid=0 sstyp=0 msid=0 mstyp=0` and the interface was then dropped for
  "resolved to no nodes" — a spelling that looked handled and produced nothing.
  `contact_spotweld.cfg:1720-1725` is explicit that `_TITLE` consumes the same
  `CARD("%10d%-70s", _ID_, TITLE)` as `_ID`, so both now do. Pre-existing on the
  `*CONTACT_TIED_*` path too; no corpus deck uses the spelling.

- **A contact master surface built from a part that carries 3-corner shells was
  rejected by the starter.** `_make_master_surface` put every shell id of the
  part into a `/GRSHEL/SHEL` group, but since `d1ade12` a shell with 3 distinct
  corners — written as 3 ids *or* as a collapsed quad `n1 n2 n3 n3` — is
  emitted as `/SH3N`, and a `/GRSHEL/SHEL` resolves only 4-node `/SHELL` ids.
  The result is hard `ERROR 70` (`ELEMENT ID=n DOES NOT EXIST`) and the deck is
  refused. `_emit_grsh3n`'s own docstring already stated the rule
  ("callers must split a mixed shell id list with
  `_split_shell_eids_by_topology` first") that this caller did not follow.

  Triangles now get their own `/GRSH3N/SH3N` + `/SURF/GRSH3N` (the starter
  reads it through the branch symmetric to `/SURF/GRSHEL`,
  `hm_read_surf.F:925` vs `:893`), and a surface that mixes two or three of
  {quads, triangles, solids} combines them under a `/SURF/SURF`. The
  single-kind and quad+solid `state.next_id()` allocation orders are unchanged,
  so a master surface with no triangles is emitted byte-for-byte as before.

  Found by the new `*CONTACT_SPOTWELD` path, which is the first thing to build
  a master surface over `W16_spotweld_E1`'s welded sheets — they carry the
  collapsed quad `529 = 695/665/664/664`. The failure also cost the tie two
  secondary nodes it could not project (`WARNING 1071`) before the missing
  segments were restored; with the fix all 8 weld nodes tie and the run is
  clean.

  **This was live on `master`, not a latent risk.** `W2_Door_Impact.k` — an
  ordinary `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` deck with no spotweld
  keyword anywhere — converts on `master` to a starter deck the solver
  **refuses**: 19 `ERROR(S)`, the first being `ERROR 70` /
  `** ERROR IN SHEL ELEMENT GROUP` / `GROUP TITLE: contact_master_1_grshel` /
  `ELEMENT ID=190 DOES NOT EXIST`. The same deck converted on this branch runs
  the starter with **0 ERROR(S)**. It is the ninth changed deck in the corpus
  sweep above, and it is the only one that changed for a reason other than the
  three new keywords.

- **Metal plasticity batch 2** (`*MAT_PLASTICITY_WITH_DAMAGE` / `*MAT_081` /
  `*MAT_082` + `_ORTHO` / `_ORTHO_RCDC` / `_ORTHO_RCDC1980` / `_STOCHASTIC` /
  `*MAT_082_RCDC` / `*MAT_082_RCDC1980`; `*MAT_DAMAGE_2` / `*MAT_105`;
  `*MAT_STRAIN_RATE_DEPENDENT_PLASTICITY` / `*MAT_019` / `*MAT_19`;
  `*MAT_PLASTICITY_COMPRESSION_TENSION` / `*MAT_124`; `*MAT_GURSON` /
  `*MAT_120` + `_JC` / `_RCDC` / `_BFRAC`; `*MAT_ISOTROPIC_ELASTIC_PLASTIC` /
  `*MAT_012` / `*MAT_12`; `*MAT_HILL_3R` / `*MAT_122`; each `+ _TITLE`) — the
  roadmap P1 batch:

  - **`*MAT_081/082` → `/MAT/LAW36` + `/FAIL/TAB1`.** The elasto-plastic half is
    card-for-card `*MAT_024`, so the record rides `state.mat_plas_tab` (new
    `MatPlasTAB.family` discriminator) and reuses the whole
    LCSS-table / LCSS-curve / EPS-ES / bilinear resolution ladder. Only two
    fields differ in MEANING at their column — card 1 field 7 is `EPPF` where
    MAT_024 has `FAIL`, and `VP` sits one slot further right — which is exactly
    why it cannot share the MAT_024 handler. Layout from
    `FAIL/fail_tab1.cfg FORMAT(radioss2021)`. `EPPFR` becomes the mandatory
    `TABLE1_ID` failure-strain plateau and `EPPF` the `TABLE2_ID` instability
    plateau, flat over triaxiality −1…+1; leaving card 2 blank makes the
    reader's `Dcrit=1`/`n=1` defaults reproduce LS-DYNA's linear
    `ω = (εp−EPPF)/(EPPFR−EPPF)` (Vol II R17 p.2-606) exactly. Unlike the
    MAT_123 carrier card this TAB1 is LIVE — MAT_081 has no `FAIL` field, so
    nothing is double-counted. **`FAD_EXP = 1`** turns the softening half of
    that law on: `hm_read_fail_tab1.F:153-157` zeroes `ECRIT` as soon as a
    TABLE2 is given, so `:170-174` leaves `DMG_FLAG = 0` for a blank exponent,
    and `fail_tab_c.F:441-455` gates the whole necking block — the only reader
    of `EPSF_N`, i.e. of `EPPF` — on that flag. With `FAD_EXP = 1` and `D = 0`
    it yields `DMG_SCALE = 1 − (εp−EPPF)/(EPPFR−EPPF)`, LS-DYNA's own `1−ω`,
    which `mulawc.F90:2656/2724` multiplies into the layer stress; measured
    within **0.07 %** of `(1−ω)·σy` on a live shell run. SHELLS only —
    `fail_tab_s.F` reads `TABLE1` alone and has no `DMG_SCALE` path, so on
    solids the instability table is inert (the rupture strain is exact on
    both, and the solid time-history is byte-identical with and without the
    exponent). `NUMINT` → a POSITIVE `P_thickfail`, divided by the shell's
    `NIP`: `hm_read_fail_tab1.F:181-187` honours the value only on the
    `> 0 .and. IFAIL_SH > 1` branch and silently substitutes "all thickness
    must fail" for a negative one, so the reader's failed-IP-FRACTION form
    (which `fail_setoff_c.F:139-146` does implement, and `/FAIL/GENE1` does
    pass through) never survives TAB1 — the count is carried as the equivalent
    broken-THICKNESS fraction instead, exact for a uniformly weighted stack and
    off by the integration weights for a Gauss one. `Ifail_sh=2` is what makes
    the reader honour it at all. A blank
    `EPPF`/`EPPFR` is written as `1e14` (LS-DYNA's 1e12/1e14 "no failure"
    defaults, which a blank cell reads as 0); both blank ⇒ no `/FAIL` card.
    **`LCDM` is deliberately not transferred** — LS-DYNA's LCDM is ω(εp) while
    TAB1's `fct_IDd` is a function of the current damage D returning a
    damage-RATE multiplier, a different independent variable, so a direct
    transfer would silently change the softening law. `LCSR` is expanded into
    the LAW36 rate-function family (the one static function repeated per curve
    point with that point's ordinate as `Fscale` — dyna2rad's branch B without
    its SFA/SFO double-scaling, since k2rad's curve reader has already applied
    them), and is ignored when LCSS is a table exactly as LS-DYNA ignores it.
    **dyna2rad has no `*MAT_082` (or any option-suffix) entry in
    `dynaMatLawKeywordMap`**, so every one of those spellings falls to the
    `default:` branch whose error message is commented out — the keyword is
    dropped with no message at all and the `/PART` gets `mat_ID = 0`. Here the
    base material converts and only the directional damage / Wilkins Rc-Dc card
    / per-element stochastic scatter are named as not reproduced.
  - **`*MAT_105` → `/MAT/LAW36` + `/FAIL/LEMAITRE` (+ `/FAIL/JOHNSON`).** Cards
    1/2 are MAT_024's (no `VP` column — MAT_105 is always fully viscoplastic),
    with the EPS/ES pair one card lower because of the Lemaitre card 3, which
    is an exact triple: `EPSD`→`EPS_D`, `S`→`S_D`, `DC`→`DC`. Layout from
    `FAIL/fail_lemaitre.cfg FORMAT(radioss2026)` — the card exists ONLY in that
    directory, which is the "keyword only in a newer dir" case: the reader
    warns `WARNING 100211` and then parses the newer FORMAT block in full and
    correctly (verified live, 0 ERROR(S)). A blank `DC` is written as LS-DYNA's
    documented 0.5 rather than left 0, which the reader would clamp to 1.0 — a
    materially different law. `FAIL` still becomes `/FAIL/JOHNSON` with
    `Ifail_sh=2`, so both criteria coexist as in LS-DYNA.
  - **`*MAT_019` → `/MAT/LAW121` (PLAS_RATE).** Layout from
    `MAT/matl121_plasrate.cfg FORMAT(radioss2022)`. A genuine 1:1 target:
    LAW121's kernel (`mat121c_newton.F:194`) is literally MAT_019's
    `σy = σ0(ε̇) + E·Et/(E−Et)·εp`, so `ETAN` goes into `TANG` verbatim and
    Radioss does the `Ep` conversion itself; no curve is resampled. `RDEF` maps
    onto `Ifail` value-for-value including 0. Two divergences from dyna2rad
    (`p_ConvertMatL19`), both places where it leaves a 0 that means something
    else: card 5's `TANG` is the curve's ORDINATE SCALE once `Fct_TANG != 0`
    (so 1.0, not 0, which would zero the hardening), and the `Xscale_*`/
    `Yscale_*` factors are written as an explicit 1.0 whenever their function
    slot is used rather than relying on a blank default the reader documents
    for `SIG0` only. A missing `LC1` names starter `ERROR 2060`; `VP=1` with
    `LC2` names `WARNING 2061`, where the reader silently forces `Ivisc` to 0.
  - **`*MAT_124` → `/MAT/LAW66`** (+ `/VISC/PRONY`, + a failure card). Layout
    from `MAT/mat_law66.cfg FORMAT(radioss2022)` (the revision that adds
    `EC`/`RPCT` to card 3). Two deliberate divergences from dyna2rad, both
    traced to the manual and then confirmed by the starter's own echo:
    **`P_c`/`P_t` carry `PC`/`PT`** — "compressive/tensile mean stress at which
    the yield stress follows LCIDC/LCIDT" (Vol II R17 p.2-876), which the
    starter echoes as `COMPRESSION MEAN STRESS` / `TRACTION MEAN STRESS`, and
    `RPCT` is stated as a fraction of that same pair on both sides;
    dyna2rad writes `PCUTC`/`PCUTT` there (gated on `PCUTF`, and its `P_t` gate
    tests `PCUTT` instead — `convertmats.cxx:10105`) and drops `PC`/`PT`
    entirely, moving the yield-curve blend band onto unrelated numbers. And
    **`Epsilon_0` carries `C`**: LS-DYNA's factor is `1 + (ε̇/C)^(1/P)`, so C is
    the reference rate and P the exponent — dyna2rad maps `c ← P` correctly but
    never writes `Epsilon_0`, so the reference rate is lost to the reader's
    substituted 1.0. `LCSRC`/`LCSRT` promote to `Iyld_rate=3`, whose card has
    no `VP` column (reported rather than lost silently). **Every function slot
    of a pair is filled**, because `hm_read_mat66.F:269-278` loops
    `IFUNC(1..MFUNC)` — 2 for the yield pair, 4 once `Iyld_rate=3` adds the
    rate pair — and raises `MSGID=126 MSGERROR` "WRONG REFERENCE TO FUNCTION
    ID=0" on any zero, i.e. a half-filled pair is an ERROR TERMINATION rather
    than a degraded run, while LS-DYNA accepts half of either. A lone
    `LCIDC`/`LCIDT` is MIRRORED into the empty slot (p.2-877 remark 1 requires
    both curves, so such a deck is already degenerate and mirroring is the only
    reading that keeps the stated branch); a lone `LCSRC`/`LCSRT` — each
    documented independently Optional, p.2-875 — gets a synthesized FLAT
    unit-scale `/FUNCT` on the other side, which reproduces LS-DYNA's "no rate
    effect there" exactly because LAW66 applies `IFUNC(3)`/`IFUNC(4)` as
    multiplicative yield factors (`sigeps66.F:481-487`). `LCFAIL` →
    `/FAIL/TENSSTRAIN` under LS-DYNA's own four activation conditions
    (p.2-878); outside them the curve is dropped and `FAIL` applies, where
    dyna2rad's `else if (lcfailId > 0)` swallows both and emits no failure at
    all. `FAIL>0` → `/FAIL/JOHNSON` with k2rad's `Ifail_sh=2` all-points rule
    (dyna2rad writes 1 here, the outlier among its own MAT_024/081/105 paths).
  - **`*MAT_120` → `/MAT/LAW52` (GURSON).** Layout from
    `MAT/matl52_gurson.cfg FORMAT(radioss130)`. `alpha_3` (q3) is written as
    `Q1²` because the LAW52 reader does NOT default it (verified) and 0 is a
    different flow surface. Four fixes over dyna2rad, all confirmed against the
    manual's own wording: **`ATYP=1` is converted** by sampling
    `σY = SIGY·((εp + SIGY/E)/(SIGY/E))^(1/N)` (p.2-828) onto an 11-point
    `/TABLE/1`, where dyna2rad's branch is a bare `// no conversion available`
    that leaves LAW52 with `n = 0`; **`FF0` survives** — the
    `(L1..L4, FF1..FF4)` mean is applied only when that table is actually given
    ("FF0 is only used if no curve is given by (L1,FF1)-(L4,FF4) and LCFF = 0"),
    where dyna2rad averages `/4` unconditionally and so zeroes `FF0` in the
    common case; **`LCF0` reaches `Fi`**, where dyna2rad looks up the attribute
    `"L1"` (a FLOAT) and the handle never resolves; and the `f0 ≤ fc ≤ fF`
    ordering is checked with starter `ERROR 1745` named. A `LCSS` curve is
    re-emitted as a 1-D `/TABLE/1` because that slot reads a table, not a
    function — the `state.law76_table_ids` set was generalized to
    `state.table_1d_ids` for it; an `LCSS` naming a `*DEFINE_TABLE` that could
    not be resolved falls back to the `ATYP` ladder instead of writing a
    `Tab_ID` with no `/TABLE` behind it (starter `ERROR 779`), the same guard
    the MAT_024 path already had. All four element-length inputs (`LCFF`,
    `LCF0`, `LCFC`, `LCFN`) collapse the same way, to the MEAN of their
    ordinates, and LCFF's precedence over the `(L, FF)` table is tracked with a
    flag rather than by comparing the result against `FF0`. `_JC` adds a
    companion `/FAIL/JOHNSON` from its card-5 `D1-D4` with **`D3` VERBATIM**:
    this keyword's `σH/σM` is the *mean hydrostatic stress* ratio, which the
    manual uses tension-positive throughout (GISSMO p.2-76; `*MAT_252`
    p.2-1694 "σm = I1/3 … as in Johnson and Cook [1985]"; `*MAT_124` remark 1
    "a positive mean stress (meaning a negative pressure) is indicative of
    tension"), matching Radioss's `P = (σxx+σyy)/3` over `σVM`
    (`fail_johnson_c.F:113-117`) — only `*MAT_JOHNSON_COOK`'s `σ* = p/σeff`
    uses LS-DYNA's compression-positive PRESSURE and needs the flip. `LCJC > 0`
    suppresses the card entirely, because LS-DYNA then ignores `D1`–`D3`
    (p.2-838) and the replacement triaxiality curve has no `/FAIL/JOHNSON`
    slot, so building one from card-5 leftovers would erode on a criterion the
    source deck never evaluates. `_RCDC`/`_BFRAC` convert cards 1-4 and
    leave cards 5 AND 6 UNREAD rather than striding an unmodelled card 5 and
    silently inventing an LCSS/LCFF/LCF0 set. dyna2rad drops all three variants
    silently.
  - **`*MAT_012` → `/MAT/LAW2` (PLAS_JOHNS)**, `E = 9KG/(3K+G)` and
    `ν = (3K−2G)/(2(3K+G))` derived in a prepass — dyna2rad evaluates the same
    two expressions through exprtk with no zero guard
    (`convertutilsbase.cxx:140-276`), so a card missing `G` or `BULK` writes
    `NaN` into the `/MAT`; both degenerate cases are reported here instead.
    `a = SIGY`, `b = ETAN` **verbatim**, `n = 1`: the manual calls MAT_012's
    ETAN the "Plastic hardening modulus" (Vol II R17 p.2-206), i.e. dσ/dεₚ,
    which is exactly LAW2's `b` with `n = 1` — it must NOT get the
    `E·ETAN/(E−ETAN)` rescale that `*MAT_003`'s identically-named *tangent*
    modulus needs. The LAW2 card body was extracted into a shared
    `_law2_plas_johns_lines` helper so the `*MAT_JOHNSON_COOK` output stays
    byte-identical.
  - **`*MAT_122` → `/MAT/LAW43` (HR=1/3) or `/MAT/LAW32` (HR=2)**, on the same
    `/PROP/TYPE9` split the MAT_037 path uses (LAW32 declares
    `SHELL_ORTHOTROPIC` only — `hm_read_mat32.F:247-252` — exactly like LAW43,
    so a solid part is warn-refused too). Three independent Lankford values go
    into their own slots, unlike MAT_037's collapsed r-bar. For `HR=1`,
    **`P1` is the TANGENT modulus and `P2` the YIELD STRESS** (p.2-852) — the
    opposite of dyna2rad's `{(0, P1), (1, P1+P2)}` curve — and because the LAW43
    curve is stress vs PLASTIC strain, `P1` gets the `E·P1/(E−P1)` rescale that
    MAT_037's already-plastic `ETAN` correctly does not. `HR=2` routes to
    `/MAT/LAW32` (`matl32_hill.cfg FORMAT(radioss140)`), whose analytic Swift
    law `σ = A·(EPSILON_0 + εp)ⁿ` reproduces `k·(E0+εp)ⁿ` exactly; dyna2rad has
    no `HR=2` branch at all, leaving `NUM_CURVES = 0` and starter `ERROR 366`.
    `AOPT=2`'s a-vector and `BETA` reach the `/PROP/TYPE9` `Vx/Vy/Vz` + `Phi`
    columns (dyna2rad reads none of MAT_122's axis block); the other AOPT modes
    have no TYPE9 column and are named — including `AOPT=0`, the card's default
    and what a blank field means, which gets its own message because "material
    axes determined by element nodes 1, 2 and 4" (p.2-853) is a real rule being
    dropped, and on a Hill sheet law the rolling direction is the point.
  - Wiring: `_target_mat_law` (`writer/mesh.py`) gains a branch per new family,
    including the `use_law32` split, so the beam-compat check and the `/XREF`
    law gate both see them. The beam whitelists need NO change and the comment
    now records why, read from the 2026-05-20 starter tree: LAW52
    (`hm_read_mat52.F:238-241`), LAW66 (`mat66:326-329`), LAW121
    (`mat121:277-285`) and LAW32 (`mat32:247-252`) all leave `PROP_BEAM` at its
    0 default, so the existing "no beam keyword at all — starter ERROR 3046"
    message is already correct for them; LAW2 is `BEAM_ALL` and already
    whitelisted, so a `*MAT_012` beam part converts and runs. `all_mat_ids()`
    gains the five new containers (the `next_mat_id()` guard against starter
    `ERROR 79`), and every keyword is registered in
    `k2rad/assembly.py::_OFFSET_SPECS` with its curve-reference fields.

  **Validated on a live starter run.** A nine-part deck — one shell part per
  keyword, every material referenced — converts and reads with
  **`0 ERROR(S)`, `1 WARNING(S)`** on `starter_win64` at `/BEGIN 2022`, that one
  being the documented cosmetic `WARNING 100211` for `/FAIL/LEMAITRE`. The
  starter's echo was read back field by field and matches the asserted columns
  (LAW52's q3/void fractions/`Tab_ID`, LAW66's mean stresses and `1/c`, LAW121's
  `IFAIL`/`IVISC`/scale factors, TAB1's strain+necking tables and
  `PTHICKFAIL`, LEMAITRE's `EPSD/S/DC`). A second probe deck covering the
  half-filled LAW66 pairs (lone `LCIDC`, lone `LCIDT`, lone `LCSRC`, lone
  `LCSRT`) and the `*MAT_GURSON_JC` `LCJC` case also reads **`0 ERROR(S)`,
  `0 WARNING(S)`**, with the echo confirming the mirrored yield functions and
  the synthesized unit-rate curves in `fnYrt_IDc`/`fnYrt_IDt`.

  **Validated end-to-end on the engine.** Ten single-element decks (1 mm cube /
  1 mm quad, 1/8-symmetry minimal-constraint anchoring, prescribed velocity,
  `IE = EXT-WORK` to 4 digits with `KE/IE ≈ 1e-8` so the response is the
  material's): all NORMAL TERMINATION. MAT_124 discriminates tension from
  compression (200.50 vs 300.50 MPa flow, +0.002 %/−0.001 % vs the curves);
  MAT_081 deletes at `εp = 0.19999` against `EPPFR = 0.200` (−0.005 %) and, on
  the shell path, fades the stress to within **0.07 %** of `(1−ω)·σy` at every
  point between `EPPF` and `EPPFR`; MAT_019 hits both rate plateaus exactly
  (200.000 and 300.000 MPa at ~1/s and ~100/s); MAT_012 reproduces
  `E = 211764.71` to −0.001 % with `b = ETAN` verbatim; MAT_122 returns a
  Lankford ratio of `R = 1.9844` against the stated `R = 2.0` (−0.78 %; von
  Mises would give 1.0) with yield onset at `P2`; MAT_120's Gurson uniaxial
  initial yield lands at 297.488 MPa against the 297.466 the `q1/q2/q3/f0` set
  solves for (+0.008 %); MAT_105 deletes at `εp = 0.12497` against the 0.12500
  the Lemaitre triple predicts (−0.024 %).

  **81 new tests in a new `tests/test_metal_plasticity_2.py`** (1703 → 1784,
  159 → 231 subtests). No flag, and a deck without these cards is byte-identical
  (all five goldens unchanged, asserted again inside the batch's own test
  module, and all 72 `.k`/`.key`/`.dyn` decks in the repo re-convert to the same
  SHA256 as on `master`).

- **`*INTEGRATION_BEAM` user cross-section rules: a beam's section is now
  integrated cell by cell instead of being emitted as a zero-stiffness
  resultant.** Nothing in `k2rad/` parsed the keyword, and `handle_section_beam`
  never read card-1 field 4, so the reference was lost twice over — a deck whose
  beam section lives in a rule (an I-beam frame, a tube, a tapered spar) got a
  `/PROP/BEAM` with `Area = Iyy = Izz = Ixx = 0` and no warning that its beams
  had no stiffness at all. 75 new tests in a new `tests/test_integration_beam.py`
  plus 9 in `tests/test_include_transform.py`; no flag.

  **What is byte-identical, precisely.** Every `.k`/`.key`/`.dyn` deck in the
  repo re-converts to the same SHA256 as on `master`, and all five goldens are
  unchanged — but that corpus cannot detect the whole change, because all six
  repo decks carrying a `*SECTION_BEAM` use `ELFORM = 9`, the one dialect kept
  verbatim. The `*SECTION_BEAM` card-2 dialect rewrite below *does* change output
  for `ELFORM 0/3/4/5/6/7/8/11/14` and blank, none of which are new cards: those
  used to read a thickness (or a ramp time, or an A10 string) as `A/ISS/ITT/J`
  and now read their real card. See "Three latent card-2 mis-reads" further
  down for what each becomes.

  **This is net-new capability, not parity — dyna2rad converts none of it.**
  There are two independent stops on the Altair side. `INTEGRATION_BEAM` is
  commented out of the R14.1 data hierarchy (`data_hierarchy.cfg:4244-4253`), so
  `HWCFGReader::readHeader` bails with no descriptor, no pre-object and no
  message (the error text is real but `displayMessage` is compiled out in both
  `mec_msg_manager.cpp:51-63` and `meci_read_context.cpp:111-123`) — the card is
  silently dropped. And the `*SECTION_BEAM` branch that would consume a rule is
  an explicit empty stub, *"NOT YET SUPPORTED (waits for RD-6730 to be solved)"*
  (`convertprops.cxx:1343-1347`), which still emits a `/PROP/TYPE18` with
  `ISFLAG` and `NITRS` never set. A grep for every `*INTEGRATION_BEAM` attribute
  name across the whole `dyna2rad` tree returns zero hits.

  **The link is card-1 field 4 (`QR/IRID`, cols 31–40) and it is a FLOAT.**
  `EQ.-n`: `|n|` is the rule id (Vol I R17 p.41-4) — the exact analogue of
  `*SECTION_SHELL`'s field 6, and `-77`, `-77.0` and `-7.700E+01` all occur in
  real decks. On the object branch the quadrature scalar is **dead**: dyna2rad's
  own `SCALAR_OR_OBJECT` cell force-zeroes it
  (`meci_data_reader.cpp:6990-7003`), so a converter that read `QR` without
  checking the sign would see `QR = 0` and stack the 2-point rectangular rule on
  top of the user rule it was already given. k2rad stores the two separately.

  **The rule's two card blocks are ADDITIVE, not exclusive.** Card 1 is
  `IRID NIP RA ICST K`; the reader takes the `D1 D2 D3 D4 SREF TREF D5 D6`
  dimension card whenever `ICST > 0` **and** `NIP` `S T WF PID` cards whenever
  `NIP ≠ 0`, exactly as the manual's two independent headings say. The HyperMesh
  CFG gates the point list on `if(LSD_ICST == 0 && LSD_NIP > 0)` and is wrong —
  verified with LS-PrePost 4.13, where a `ICST=5, NIP=2` rule followed by one
  card too few swallows the next rule's header as the missing point card and
  loses that rule entirely. Per-rule stride is therefore
  `1 + [ICST>0] + [NIP≠0]·NIP`, several rules may stack under one header, and
  there is no `_TITLE` variant. Note `SREF`/`TREF` sit *between* `D4` and `D5`,
  so `D5`/`D6` are fields 7 and 8.

  **`ICST = 0` → `/PROP/TYPE18` `Isect = 0` with one `Yi Zi AREA` card per
  cell.** `S`/`T` are normalized quadrature coordinates in [−1, +1] and `WF` is
  the area fraction `A_i/A`, while Radioss wants absolute coordinates and an
  absolute area (`prop_p18_int_beam.cfg:29-31`). The ±1 square is
  `*SECTION_BEAM` card 2a's `TS1 × TT1` rectangle and the gross area is
  `RA·TS1·TT1`, so `Y_i = (S_i − NSLOC)·TS1/2`, `Z_i = (T_i − NTLOC)·TT1/2`,
  `A_i = WF_i/ΣWF · RA·TS1·TT1`.

  `NSLOC`/`NTLOC` (card 2a fields 5/6) are the "location of the reference
  surface" — the beam's *node line* — inside the same ±1 square: `1.0` = the side
  at `s = 1`, `0.0` = centre, `−1.0` = the side at `s = −1` (p.41-13/41-14).
  `/PROP/TYPE18`'s `Yi/Zi` are measured from the nodes, so subtracting them is
  what puts the section where LS-DYNA has it. A beam hung off a shell surface
  with `NSLOC = 1` would otherwise be silently re-centred on its own nodes,
  deleting exactly the eccentricity that couples axial force to bending. The
  rule's `SREF`/`TREF` override them "even if `SREF = 0`" (p.29-3) but live on
  the `ICST > 0` dimension card, which never reaches this path, so the two
  cannot collide.

  The `ΣWF` normalization mirrors dyna2rad's *shell* rule
  (`convertprops.cxx:1991-1996`) and is a no-op on a well-formed deck; LS-DYNA
  applies `WF` literally, so weights that do not add up to 1 now get the applied
  scale factor quoted rather than silently changing the section area.
  **`TS1`/`TT1`, not `TS1`/`TS2`** — those are the s-direction thickness at
  node 1 and node 2, so dyna2rad's `L1←TS1, L2←TS2` map (`:1274-1275`) reads a
  taper as a depth and turns a prismatic rectangle into a square. A real
  `TS2`/`TT2` taper is reported (`/PROP/TYPE18` is prismatic), and **`CST = 1` is
  refused rather than mis-read**: it redefines `TS1`/`TT1` as the outer and inner
  *diameter* (p.41-13), so denormalizing the rule's ±1 square onto them would
  emit `TS1·TT1` of area where the annulus really has `π/4·(TS1²−TT1²)` — 2.8×
  too stiff axially on a 20/16 tube, with nothing said. `Iref = 1` with
  `Y0 = Z0 = 0` keeps the reference axis on the node line where LS-DYNA puts it;
  `Iref = 0` makes the starter recompute the centre as the area-weighted
  barycentre and shift every point by it (`hm_read_prop18.F:267-279`), silently
  relocating the neutral axis of a deliberately eccentric section.

  **`ICST = 1..22` → `Isect = ICST + 9`.** The map is exact and 1:1 with a
  constant offset of 9 against the starter's own shape table
  (`defbeam_sect_new.F90`, whose `case` blocks name each shape and set `nb_dim`
  / `intr_max`), and the dimension counts agree with LS-DYNA's *own*
  `SECTION_nn` card-2b field counts on all 22 rows. `L1..Ln ← D1..Dn`; `K`
  becomes `NITRS` clamped to that shape's `intr_max` (ERROR 3060 above it). Only
  the shapes needing **≤ 2** dimensions are emitted — ICST 8 (circular, `L1` =
  radius, `area = pi*l(1)**2`), 9 (tubular) and 11 (solid box):

  | `/BEGIN` | CFG resolved | `L3..L6` | `Isect=10, L1..L4` |
  |---|---|---|---|
  | 2022 (what k2rad writes) | `radioss120` | absent | `WARNING 100213` + `ERROR 3059` |
  | 2026 | `radioss2024` | present | reads cleanly, 27 points |

  Both rows are the real starter on two decks differing only in `/BEGIN`. The
  CFG search runs *downward* from the requested version
  (`cfg_kernel.cpp:266`, `vers.substr(found)`), so `radioss2024`'s six-dimension
  form is invisible at 2022 and the first hit declares `L1`/`L2` only. Shapes
  needing more are reported with both ways out named (restate as an `ICST=0`
  rule, which has no version gate, or as `A/ISS/ITT/J` on an `ELFORM=2`
  section) rather than emitted onto a deck the starter refuses.

  **The material gate runs before the property type is chosen, not after.**
  `PROP_BEAM` is a per-law flag (`init_mat_keyword.F:250-258`): LAW0/2/13/44 are
  `BEAM_ALL`, LAW34/36/71 are `BEAM_INTEGRATED`, and **LAW1 (`/MAT/ELAST`) is
  `BEAM_CLASSIC`, i.e. TYPE3 only** — `check_mat_elem_prop_compatibility.F:239-241`
  rejects it on TYPE18 with ERROR 3047 followed by ERROR 745, which kills the
  run. Such a section stays on `/PROP/BEAM` and the rule is condensed into
  `Iyy = Σ(A_i²/12 + A_i·z_i²)`, `Izz = Σ(A_i²/12 + A_i·y_i²)`,
  `Ixx = Iyy + Izz`.

  **`Iyy` is the `z`-based sum, and the ENGINE is what pins that** — the
  starter's listing block is not usable as the spec here. `hm_read_prop18.F:295`
  accumulates `TIYY_I` from `RYI` (the *y* coordinate) and prints it under the
  heading `IYY`, but it never stores `TIYY_I` into `GEO` and nothing downstream
  reads it. What the solver actually does: `/PROP/BEAM` develops
  `MOM(2) = KYY·E·GEO(2)` with `GEO(2) = IYY` (`m1lawp.F:108`,
  `hm_read_prop03.F:114`), while `/PROP/TYPE18` develops
  `MOM(2) = Σ(A_i·σ_i·z_i) = E·KYY·Σ(A_i·z_i²)` in the same slot
  (`mulaw_ib.F:139` `DEPSXX = EXX − YPT·KZZ + ZPT·KYY`, then
  `main_beam18.F:253`). Equating them gives `Iyy = Σ(A_i·z_i²)`. Two independent
  cross-checks inside this repo agree with the engine and not with the listing:
  the ICST=11 closed form `Iyy = D1·D2³/12` (with `D1` along `y`,
  `defbeam_sect_new.F90` case(20) `dy1 = l(1)*fac`), and `*SECTION_BEAM`
  ELFORM 2's `Iyy ← ISS`, LS-DYNA's "area moment of inertia about the local
  *s*-axis" = `∫t² dA` = `∫z² dA` (p.41-15). Tests pin the convention on a
  deliberately asymmetric section, on the two-cell degenerate case where one
  axis collapses to the self term, and by requiring the point route and the
  shape route to agree on the same rectangle.

  The `A_i²/12` self term models each cell as a square patch — the starter's own
  choice, exact only for square cells (a 4×4 grid of 0.5 × 2.0 cells wants
  `0.5·2³/12 = 0.333` each and gets `1/12`), but a rule states no cell *shape*,
  only a position and an area, so nothing better is recoverable. `Ixx` as the
  polar moment is the same approximation dyna2rad makes when `J = 0`
  (`convertprops.cxx:1400-1402`). ICST 8/9/11 fall back through their closed
  forms. The whitelist is deliberate: an unrecognized material keeps today's
  `/PROP/BEAM` rather than being promoted into a starter error. The gate is per
  *section*, so one incompatible part moves every part on it — the warning names
  the ones dragged along, since a `BEAM_INTEGRATED` law among them is itself an
  ERROR 3047 that the `/PROP/BEAM` material gate then reports in turn.

  Rule support covers **ELFORM 0, 1, 4, 5 and 11**; dyna2rad reaches a
  rule-aware path for 1 and 4 only and drops 5 and 11 entirely (no switch case,
  no `default:`, so the part ends up with `prop_ID = 0`). `ELFORM = 14` gets its
  own message and an accurate one: it is the **elbow** element and the one
  formulation that *mandates* a user rule — "A user-defined integration rule
  with a tubular cross section (9) must be used" (p.41-11) — so the rule is
  understood and it is Radioss that has no elbow to put it on. Warn-dropped or
  warn-reported by name, every one: a dangling `IRID`; a rule on an `ELFORM`
  that integrates no cross-section; a section no `*ELEMENT_BEAM` uses; a
  spotweld-only section; a missing `TS1`/`TT1`; a tubular `CST = 1`; a
  `TS2`/`TT2` taper; `RA ≤ 0` (its card default is 0.0, which would
  make every cell zero-area — starter ERROR 314 — so 1.0 is substituted and said
  so); `ΣWF = 0`; a `ΣWF ≠ 1` (renormalized, scale factor quoted); a
  non-positive cell area; more than 100 cells (ERROR 977); a
  short `S/T/WF/PID` block (with the `NIP`-vs-point-count guard Altair's shell
  code lacks — `convertprops.cxx:1991-2016` loops to `NIP` over both lists with
  no size check); point cards under an `ICST > 0` rule (consumed, data ignored,
  as LS-DYNA does); a per-cell `PID_i` (`/PROP/TYPE18` has one material for the
  whole section); `SREF`/`TREF`; an unsupported `ICST`; a missing dimension; a
  duplicate `IRID`; and a rule nobody references (recorded in the *recognized but
  not emitted* channel rather than vanishing from the accounting).

  Starter-validated: three cantilevers whose `*SECTION_BEAM` card sets are
  stacked under ONE header, binding three rules stacked under one
  `*INTEGRATION_BEAM` header — an `ICST = 0` six-cell cloud on a 20 × 30
  section, an `ICST = 8` circle of radius 8 with `K = 1`, and an `ICST = 11`
  18 × 26 box with `K = 2` — runs through `starter_win64.exe` with **0 errors,
  0 warnings**, and its echo reproduces every number:

  | prop | `SECTION TYPE` | points | `BEAM AREA` | expected |
  |---|---|---|---|---|
  | 5 | 0 | 6 (as written) | 600.000 | `RA·TS1·TT1 = 1.0·20·30` |
  | 6 | 17 | 64 (starter-generated) | 201.0619298297 | `π·8²` |
  | 7 | 20 | 25 (starter-generated) | 468.000 | `18·26` |

  Every one of property 5's six cells comes back at the hand-computed
  `(S·TS1/2, T·TT1/2, WF·A)` — `(±10, ±15, 120)` and `(0, ±7.5, 60)` — which
  also confirms `L1` is the circle's RADIUS and not its diameter.

- **Rider: `*SECTION_BEAM`, `*SECTION_SOLID` and `*SECTION_DISCRETE` read every
  card SET under one header.** All three handlers read one fixed card index and
  returned, so every section after the first in a multi-set block was dropped
  silently — and a `*PART` pointing at one of them fell through to an
  auto-generated placeholder property. Same defect and same fix shape as
  `*SECTION_SHELL` got in the release above; `*SECTION_BEAM` is the harder one
  because its card 2 is ELFORM-dependent *in its very existence*:

  ```
  *SECTION_BEAM      : T? + 1 + 1 + [OPTCARD] + [card 2c.1]
  *SECTION_SOLID     : T? + 1 + [option cards] + [1 + NIP + ceil(LMC/8)]
  *SECTION_DISCRETE  : T? + 2                                   (fixed)
  ```

  The card-2 dialect is picked per set from `ELFORM` **and** a look-ahead on
  that card's own first 10 columns — "the first 7 characters of the card spell
  out SECTION" selects the named standard-section form, which the CFG does
  literally with `CARD_PREREAD("%10s", SectType)` + `_FIND(SectType,"SECTION")`
  (`sect_beam.cfg:611-612`). Both riders hang off it: `OPTCARD` only for
  `ELFORM = 2` on a named card 2b when the next line really starts with
  `OPTCARD`, and card 2c.1 only for `ELFORM = 12` whose card 2 was the
  **numeric** 2c — "Include this card if ELFORM equals 12 and the preceding card
  is Card 2c" is exact, and an `ELFORM = 12` + `SECTION_09` set takes no 2c.1 at
  all (verified against LS-PrePost on a 7-set block containing both spellings).
  `ELFORM = 10` is not a defined formulation, so the walk stops there loudly
  rather than guessing a stride. Under `_TITLE` the 80a card is consumed
  **unconditionally per set** — eating it once shifts every later set up a line
  and registers a phantom section that overwrites a real one. Each keyword now
  reports a duplicate `SECID`.

  Three latent card-2 mis-reads fall out of the dialect table, all of them the
  old catch-all "fields 1-4 are `A/ISS/ITT/J`" branch firing on a card that says
  something else: `ELFORM = 3` (truss) put `RAMPT`, a ramp *time*, and `STRESS`,
  an initial *stress*, into two bending inertias; a named `SECTION_nn` card put
  the A10 string itself into `Area` (0.0) and `D1..D3` into `Iyy/Izz/Ixx`; and
  `ELFORM = 0/4/5/11` put a *thickness* into `Area`. Each is now read into the
  right field or reported as unconvertible. `ELFORM = 9` keeps the exact fields
  k2rad's `/PROP/TYPE13` spotweld-connector path already read, so no nugget
  moves.

  Reading them right must not make a runnable-if-wrong deck unrunnable, so
  `ELFORM 0/1/4/5/11` — whose card 2 is thicknesses and carries no resultants at
  all — now **derive** the prismatic section from `TS1`/`TT1` instead of landing
  on an all-zero `/PROP/BEAM`. An all-zero one is not a soft beam: the starter
  refuses it outright, `hm_read_prop03.F:151-182` raising ERROR 314 (`AREA`),
  315 (`IYY`), 316 (`IZZ`) and 317 (`IXX`) on each non-positive value. `CST = 0`
  gives the solid `TS1 × TT1` rectangle, `CST = 1` the annulus its outer/inner
  *diameters* describe, and the substitution is reported. Where no section can
  be derived at all — `ELFORM 6`, `14`, `7`/`8` (no t-extent), a named
  `SECTION_nn`, an undefined section — the message now names those four ERROR
  ids instead of saying the beam merely has no stiffness.

  `*INCLUDE_TRANSFORM` gets four new walkers to match (`_off_section_beam`,
  `_off_section_solid`, `_off_section_discrete`, `_off_integration_beam`),
  replacing three declarative specs that offset only the first set's `SECID`.
  `*SECTION_BEAM`'s `QR/IRID` is the **second** negated back-reference this
  converter meets and reuses `_rewrite_neg_ref` unchanged; on the rule, the
  `*PART` reference is field **4** of a point card, not field 3 as on the shell
  rule, and the `ICST > 0` dimension card has to be strided over or the next
  rule's card 1 is read out of the middle of this one. Both riders and the
  ELFORM 101-105 user-solid stride are covered through a transform as well, each
  followed by a set with a distinct `SECID` so a one-line de-sync cannot pass.

  `*SECTION_DISCRETE` also reports the one malformed shape it has always
  tolerated silently: a set that omits its card 2 mid-block makes the walk read
  the *next* set's card 1 as `CDL`/`TDL` and stride over it, losing that section
  and putting every set after it one line out of phase.

- **`*INTEGRATION_SHELL` user integration rules: a shell's per-layer
  thicknesses and materials now come from the deck instead of an even split.**
  Nothing in `k2rad/` parsed the keyword — it landed in `skipped_keywords` — and
  `handle_section_shell` never read card-1 field 6, so the reference was lost
  twice over. A laminated windshield, a foam-core sandwich, any deck whose layer
  thicknesses live in a rule, converted to N identical layers with no warning
  that the stack had been flattened. 75 new tests in a new
  `tests/test_integration_shell.py` plus 5 in `tests/test_include_transform.py`
  (1413 → 1493); no flag, and a deck without these cards is byte-identical (all
  five goldens unchanged, and all 73 `.k`/`.key`/`.dyn` decks in the repo
  re-convert to the same SHA256 as on `master`).

  **The link is card-1 field 6 (`QR/IRID`, cols 51–60), not `NIP`.** "Quadrature
  rules in the `*SECTION_SHELL` and `*SECTION_BEAM` cards need to be specified as
  a negative number. The absolute value of the negative number refers to user
  defined integration rule number" (Vol I R17 p.29-1); dyna2rad encodes the same
  cell as `SCALAR_OR_OBJECT(Sect_Option, LSD_QR, LSD_IRID)` (`SectShll.cfg:699`)
  and picks the object branch on the sign alone (`meci_data_reader.cpp:6847`). A
  negative `NIP` is a different thing — a mis-keyed count — and now gets its own
  warning instead of silently clamping to 2 *and* mis-trimming the `ICOMP` angle
  block to the first two angles without tripping that block's own truncation
  check. Card 1 is `IRID NIP ESOP FAILOPT`; `ESOP = 0` adds one `S WF PID` card
  per point (`CARD_LIST(NIP)` — one triple per card, not eight to a card like the
  `ICOMP` angles); several rules may stack under one header.

  Each point becomes a layer: `t_i = WF_i / ΣWF · T1`, material from
  `PID_i → *PART → MID` with a blank field inheriting the element's own part
  material. The **rule's `NIP` wins** over the section's (dyna2rad reads it off
  the rule and never off the section, `convertprops.cxx:1890-1892`) and is pushed
  onto the section, so it also corrects the shared `/PROP/SHELL` point count,
  `/INISHE`'s layer count and the `NUMFIP` count-to-ratio conversion —
  **clamped at 10 on the way onto the section**, because that is what a
  `/PROP/SHELL`'s `N` column takes (`hm_read_prop01.F:260` ERROR 788,
  `hm_read_prop09.F:368` ERROR 33), while the layered property the rule drives
  counts its plies off the rule directly and is capped at 100 instead
  (`hm_read_prop11.F:130` `NLYMAX`). The two limits are deliberately different:
  clamping the section's `N` never deletes a laminate layer, and not clamping it
  made any rule with more than 10 points ERROR-terminate the whole deck.
  `ESOP = 1`
  is NIP *equal* layers on one material — exactly a plain `/PROP/SHELL` with N
  points — so no property is split. `ICOMP = 1` and a rule **compose**: LS-DYNA
  gives each integration point one `B_i` and the rule gives that same point its
  `S`/`WF`/`PID`, so angle, thickness and material all survive, and the ICOMP
  even-split warning is retired on that path (kept verbatim where no rule
  exists). The same applies to `*MAT_LAMINATED_GLASS`, the material that
  *requires* a rule in LS-DYNA: `PID_i` wins over `F_i` where it resolves, and
  the glass/polymer pick otherwise, exactly as `convertprops.cxx:2017-2050` does.

  **The `S → Zi` mapping is a deliberate divergence from dyna2rad, measured.**
  `S_i` is a quadrature *sampling* coordinate in [−1, +1]; a Radioss layer `Zi`
  is the physical *middle of a slab*. dyna2rad writes `Zi = S_i·T1/2` with
  `Ipos = 1` (`:2015`), and the starter then takes the shell thickness from the
  layer **envelope** (`stackgroup.F`: `THICKT = max(Zi+t/2) − min(Zi−t/2)`),
  which for a canonical rule reaching `S = ±1` pushes half of each outer layer
  outside the shell and leaves the rest not tiling. k2rad stacks by cumulative
  `WF` (`Ipos = 0`) instead:

  | deck | `T1` | rule | k2rad `THICKT` | dyna2rad `THICKT` |
  |---|---|---|---|---|
  | windshield | 2.0 | `S = −1, −0.3, 0.3, 1`; `WF = .4 .1 .1 .4` | **2.000** | 2.800 (1.40×) |
  | sandwich | 2.0 | `S = −1, 0, 1`; `WF = .25 .5 .25` | **2.000** | 2.500 (1.25×) |
  | carbon | 1.2 | `S = −1, 0, 1`; `WF = 1 2 1` | **1.200** | 1.500 (1.25×) |

  The k2rad column is the starter's own `SHELL THICKNESS` echo, not a
  calculation; the dyna2rad column is `stackgroup.F`'s envelope formula evaluated
  on the same rule (it reproduces every row of an independent 7-deck dyna2rad
  readback: 2.0→2.2, 4.0→5.0, 2.0→2.5, 2.0→0.667). The starter also echoes the
  auto-computed positions — layer 1 at −0.6 spanning [−1.0, −0.2], layer 2 at
  −0.1 spanning [−0.2, 0.0] — i.e. contiguous and gap-free. A rule whose `S`
  column runs top-down or out of order is re-ordered bottom-up first, carrying
  each layer's `ICOMP` angle with it (LS-DYNA leaves that ordering arbitrary,
  Figure 29-25, but an `Ipos = 0` stack is built in list order from the bottom
  face).

  **The target property is chosen by what the starter accepts.** `/PROP/TYPE11`
  is a *single-law* property: `hm_read_prop11.F:505-563` takes only Radioss laws
  15, 25, 27 and ≥ 29 on layer 1 (ERROR 30) and requires every other layer to
  repeat it (ERROR 334). A layup therefore stays on TYPE11 only when it is
  law-uniform by construction — every layer on the part's own `*MAT_002`/
  `*MAT_054` material, or on the `*MAT_032` glass/polymer pair (two LAW27 cards)
  — and otherwise goes to `/PROP/TYPE51` + one `/PROP/TYPE19` per layer, which
  carries its materials on per-ply objects and has no whitelist. That is also
  dyna2rad's own target for this keyword. One case has no Radioss home at all:
  `hm_read_part.F:289` bans LAW1 from every layered or orthotropic shell property
  (IGTYP 9/10/11/16/17/51/52, ERROR 658) because it is integrated globally and
  carries no through-thickness state, so a rule on a `*MAT_ELASTIC` part is
  warn-dropped rather than emitted onto a deck the starter would reject.

  Warn-dropped or warn-reported by name, every one counted: a dangling `IRID`
  (dyna2rad falls through in silence); `NIP ≤ 0`; `ESOP ∉ {0,1}` (dyna2rad's bare
  `switch` has no default branch and emits a property declaring NIP plies with
  *no* ply objects); `ΣWF = 0` (dyna2rad divides by it unguarded → `inf`/`nan`);
  a short `S`/`WF`/`PID` block or a short `F` array (dyna2rad indexes both to NIP
  with no bounds check); `|S| > 1`; `FAILOPT` (TYPE11 carries one global
  `P_Thick_Fail`, not a per-layer failure policy — dyna2rad never reads the
  field); a `PID_i` naming no `*PART` (dyna2rad silently inherits); a layer
  material with no converted `/MAT`; more than 100 layers; a solid part; a
  `*PART_COMPOSITE` on the same part (which wins); the MAT_037/MAT_103
  `/PROP/TYPE9` route; and a rule nobody references (recorded in the conversion
  log's *recognized but not emitted* channel rather than vanishing from the
  accounting). An element-free `PID_i` material-carrier part — the idiom Vol I
  R17 p.29-17 explicitly allows — needs nothing from this pass: the
  element-free-`*PART` placeholder gives it a `/PROP/SHELL` and reports it by
  name, so its `/PART` resolves and the deck no longer hits starter ERROR 178.

  dyna2rad's own verdict on the keyword survives as dead code: message
  `/MESSAGE/200024`, *"IRID<0 is not supported"*, commented out at
  `convertprops.cxx:657-658`.

  Starter-validated: a three-band panel — a `*MAT_032` windshield on a
  0.8/0.2/0.2/0.8 rule, an isotropic sandwich whose middle layer takes its
  material from a `PID_i` carrier part, and a `*MAT_002` layup with `ICOMP = 1`
  angles `0/45/−45` on a `WF = 1/2/1` rule, all three rules stacked under one
  `*INTEGRATION_SHELL` header — runs through `starter_win64.exe` with **0 errors,
  0 warnings**, and its echo reproduces every layer: thickness, position, angle
  and material number, with `SHELL THICKNESS` equal to `T1` on all three.

- **Rider: `*SECTION_SHELL` reads every card SET under one header.** "Card Sets.
  For each shell section, of a type matching the keyword's options, include one
  set of data cards. This input ends at the next keyword ("\*") card"
  (Vol I R17 p.41-62), and under `_TITLE` "an addition line is read for each
  section" (p.41-1). The handler read exactly two card indices, so every section
  after the first in a multi-set block was dropped silently — and a `*PART`
  pointing at one of them fell through to `_auto_section_shell`'s **zero-
  thickness** placeholder, which the starter rejects. The cursor now advances by
  what each set actually consumed: `1 title + 2 cards + ceil(NIP/8)` angle cards
  when `ICOMP = 1`, `+1` for the card the `EFG`/`THERMAL`/`XFEM`/`MISC` keyword
  option adds, and `+1 + NIPP + ceil(LMC/8)` for the ELFORM 101–105 user-shell
  cards 5/5.1/5.2 (p.41-63). Those last ones cannot be detected by content —
  card 5 begins with `NIPP`, a *positive* integer, so a "stop when the next
  field is not a SECID" guard never fires on it and the section BEFORE it gets
  clobbered by a phantom read out of card 5's own columns. Only a genuinely
  unreadable card stops the walk, and it says so.

  The per-set 80a title card is likewise consumed **unconditionally**, blank or
  not — the manual reads one per set with no "if non-empty" proviso, and
  `parser.py` deliberately preserves a blank line as a card placeholder. Treating
  a blank title as padding shifted the set up one line and registered a phantom
  section under `int(T1)` that overwrote a real one, silently, leaving both
  shells zero-thick. A duplicate `SECID` is now reported instead of overwriting
  in silence. Scoped to `*SECTION_SHELL`: `handle_section_solid` / `_beam` /
  `_discrete` have the same first-set-only shape and are left for their own
  change.

- **`*INCLUDE_TRANSFORM` id offsets follow both keywords' card SETS.** A
  declarative offset spec addresses one set, so a second `*SECTION_SHELL` set
  kept its original `SECID` (dangling for any `*PART` in the same include) and a
  second stacked `*INTEGRATION_SHELL` rule kept its `IRID` while its `ESOP`
  column was offset with `IDPOFF` as if card 1 were a point card. Both keywords
  now use a walker. It also carries the **negated** `QR/IRID` back-reference
  across with `IDROFF`, which the declarative form structurally could not —
  `_rewrite_line` only touches positive cells, so the rule's own id moved and
  the reference to it did not, and a transformed include's section/rule pair
  always dangled into a silent even-thickness split.

- **`tools/th_to_csv.py` — T01 to CSV, with the time-derivative column the
  accumulated `/TH` channels actually need.** Standard library only (no numpy),
  so it runs anywhere the converter does.

  Several OpenRadioss `/TH` channels are a running time integral, not the
  instantaneous quantity their name suggests (see the sweep under *Fixed*
  below). The tool writes a differentiated sibling column next to each one:

  ```
  time,      3_REACY,   3_REACY_ddt
  0.030000,  0.073500,  3.850418          # N*s        # N
  ```

  The `_ddt` suffix is unit-neutral on purpose: `d/dt` of `REACX` is a force,
  of `REACXX` or of a `/TH/SECTIO` `M1` a moment, so no single word fits every
  column it is applied to.

  **On by default** (`--no-derivative` opts out), following the
  `--no-rigid-cog-master` precedent. The raw column is the trap; a flag you
  have to know to set is exactly the knowledge the user is missing. The
  addition is non-destructive — every original column keeps its name and
  relative order, so a consumer selecting columns by name is unaffected.
  `/TH/SURF` is deliberately excluded and warned about instead: `P` and `A` are
  per-`/TFILE`-interval aggregates rather than a running integral, so
  differentiating them would be meaningless.

  **The T01 reader is validated, not assumed.** It parses the engine's default
  IEEE-binary `/TH` format directly — records framed by big-endian 4-byte
  length markers (`wrtdes.F`), big-endian `int32`/`float32` payloads
  (`ieee.cpp`; the engine narrows `my_real` to `REAL*4`, so there is no
  double-precision T01), the `hist1.F` header sequence and the `hist2.F`
  per-state sequence, plus the gzip-wrapped `/TH` format variants. Diffed
  cell-by-cell against Altair's own `th_to_csv_win64.exe` on four real T01
  files — **1.29 million values, 29 to 10 000 states, node / part / interface
  groups — with zero disagreement beyond the reference CSV's 7-significant-digit
  print rounding** (max relative deviation 5e-7, exactly half an ulp of `%e`).
  Group and variable *names* are decoded from the starter's own code tables,
  which the reference converter does not do (it labels everything `var N`).

  27 new tests build **synthetic T01 files in the test itself** rather than
  checking in a binary fixture, so the format assumption stays reviewable: a
  linear ramp must differentiate back to its exact slope, the sibling must sit
  next to its source without moving any original column, an instantaneous-only
  group must gain no columns, a truncated final state must be dropped rather
  than guessed, and a non-T01 file must be rejected loudly. The derivative
  kernel (`numpy.gradient`'s scheme, reimplemented in the standard library)
  was cross-checked against numpy itself over 200 random non-uniformly spaced
  cases: max relative deviation **4e-14**.

  One bug was caught during development by the non-uniform-spacing test and is
  worth recording: the first interior-difference implementation had the forward
  and backward steps swapped. That is invisible to every evenly spaced test —
  the two formulas coincide when `h` is constant — and T01 output times are not
  always evenly spaced. The test that pins it is kept.

- **`*SECTION_SHELL` `ICOMP = 1` becomes a real layered property: the card-3
  `B1..B8` per-layer material angles now reach the `/PROP/TYPE11` layup.**
  `handle_section_shell` read only `SECID`/`ELFORM`/`NIP`/`T1`; the `ICOMP` flag
  was named in a comment and never read, and neither were the angle cards it
  brings. A composite section therefore degraded to a single-angle laminate with
  no warning of any kind. 21 new tests (1293 → 1314); no flag, and a deck with
  `ICOMP = 0` is byte-identical (goldens unchanged).

  The flag declares a layered orthotropic/anisotropic section — "A material
  angle in degrees is defined for each through-thickness integration point.
  Thus, each layer has one integration point" (Manual Vol I R17 p.41-67) — with
  the angles on the card-3 `B1..B8` block, eight values per card over
  `ceil(NIP/8)` cards (p.41-70). Each `B_i` goes **verbatim** into that layer's
  `Phi_i` (no sign flip: LS-DYNA's `β_i` and Radioss's `Phi_i` are both measured
  counter-clockwise about the shell normal from the material reference
  direction) and is **added** to the material's own `AOPT`/`BETA` rotation —
  the same composition `*PART_COMPOSITE`'s per-ply `B_i` already used. The
  existing `_emit_prop_type11` emitter is reused unchanged; only the layer list
  it is handed changes.

  **The silent-degradation magnitude, measured.** Three single-element membrane
  pulls (same MAT_002 carbon UD, same 1.2 mm total thickness, `σ_y = 0`,
  `γ_xy = 0`) run through the OpenRadioss engine to `NORMAL TERMINATION`, with
  the effective `E_x` recovered from the internal energy and compared against
  classical lamination theory computed independently in the check script:

  | layup | `E_x` CLT | `E_x` solver | diff |
  |---|---|---|---|
  | `[0/0/0/0]` | 150000.0 | 149940.0 | −0.04% |
  | `[0/45/−45/90]` | 57401.6 | 57384.4 | −0.03% |
  | `[90/90/90/90]` | 10000.0 | 10009.0 | +0.09% |

  Ratios agree to 0.13%. Before this change the `[0/45/−45/90]` deck converted
  to the first row — **2.61× too stiff along the pull axis**, and with the
  laminate's shear coupling gone.

  **dyna2rad has no thin-shell `ICOMP` path at all.** Its
  `p_ConvertSectionShell` (`convertprops.cxx:641-765`) dispatches purely on the
  *material* keyword and reads `LSD_ICOMP` only as a `*MAT_FABRIC`
  `NIP`-normalization switch (`:1704-1713`, `:3346-3351`); the per-layer `LSD_B`
  array is read on its `*SECTION_TSHELL` composite path and nowhere else
  (`ConvertSecTShellsRelatedMatComposite`, `:4528-4540`, where it also splits
  the thickness `1/NIP` per layer and repeats the part material — the same two
  conventions used here).

  `ICOMP = 1` carries **angles only** — the keyword has no per-layer thickness
  or material field — so the section thickness is still split evenly, and the
  warning names where unequal plies would have to come from. Every route that
  *cannot* carry an angle is reported by name instead of dropping it silently:
  a `*PART_COMPOSITE` on the same part **wins** (in LS-DYNA it replaces the
  `*PART`/`*SECTION_SHELL` pair outright — its own card carries `ELFORM`/`SHRF`
  and no `SECID`); MAT_037 and MAT_103 land on a single-direction
  `/PROP/TYPE9`; `*MAT_LAMINATED_GLASS` becomes two *isotropic* LAW27 phases
  with no material direction to rotate; a part on an isotropic law keeps a plain
  `/PROP/SHELL`; a solid part on a shell section has no counterpart at all. An
  all-zero angle block stays silent — it degrades to exactly the section it
  would have been anyway. A blank `NIP` still reads one angle card (LS-DYNA's
  default is 2.0), `NIP > 10` clamps the angles with the layers, and a truncated
  angle block is zero-padded **and warned**, because a half-read `[0/45/−45/90]`
  is a different laminate rather than a slightly wrong one.

  Starter-validated: a two-part panel (`ICOMP = 1` with `NIP = 4` angles
  `0/45/−45/90` on one `*MAT_ORTHOTROPIC_ELASTIC`, and `NIP = 6` angles
  `0/90/45/−45/30/−30` on a second material with `AOPT = 3`/`BETA = 15`) runs
  through `starter_win64.exe` with **0 errors, 0 warnings**, and its echo
  reproduces every layer — angle, thickness, position and material number —
  including the `+15°` `BETA` composition on the second part
  (`15/105/60/−30/45/−15`).

- **Element variants: `*ELEMENT_SHELL_THICKNESS` / `_BETA` / `_MCID` /
  `_OFFSET` / `_DOF` (and every combination) → the `/SHELL` // `SH3N` per-element
  `Phi` and `Thick` columns, `*ELEMENT_BEAM_ORIENTATION` → a synthesized third
  node, and `*ELEMENT_PLOTEL` → an inert `/SPRING`.** No flag: a deck without
  these cards is byte-identical (all five goldens unchanged). 79 new tests
  (1293 -> 1372).

  **The headline is not the thickness — it is that a `*ELEMENT_SHELL_THICKNESS`
  block used to lose the ELEMENTS.** `dispatch()` is an exact dict lookup, and
  `_make_parts_and_elements` emits elements *inside* the `state.parts` loop, so
  the block landed in `skipped_keywords`, the `/PART` was written with **no
  `/SHELL` block under it**, and `result.warnings` said nothing. The same held
  for `_BETA`, `_MCID`, `_OFFSET`, `_DOF`, `_COMPOSITE`, `_SHL4_TO_SHL8` and
  every `*ELEMENT_BEAM_*` spelling. Now the 24 legal `*ELEMENT_SHELL` and 4
  `*ELEMENT_BEAM` option spellings are registered from the grammar, and
  `dispatch()` additionally falls back on the family PREFIX, so an *unknown*
  option keeps every element it can identify as connectivity and says loudly
  what it could not interpret.

  That identification is in TWO halves, and the content half alone is not
  enough. Content: every field of a connectivity card is a plain positive
  integer, plus a per-block unique-EID rule. **Sufficiency:
  `_screen_provisional_elements` then re-checks each candidate against the node
  table** (after all parsing, so `*NODE` may follow `*ELEMENT` and `*INCLUDE`s
  are merged) and drops the ones whose nodes the deck does not define, whose
  /BEAM has `N1 == N2`, or whose /SHELL has fewer than 3 distinct corners. An
  option card whose values happen to be integers otherwise becomes an element:
  a `*ELEMENT_BEAM_THICKNESS` 10x10 square section written `10 10 10 10`, or an
  `*ELEMENT_SHELL_COMPOSITE` ply card `mid thick beta tmid …` whose leading MID
  is not an EID already seen. That is strictly worse than the old silent skip —
  measured on `starter_win64`, the section-card deck produced `3 x ERROR ID 78`
  (UNDEFINED NODE NUMBER, `NODE ID=10 DOES NOT EXIST`) + `ERROR ID 222` (`BEAM
  ID=10 IS INCONSISTENT: N1=N2`), `4 ERROR(S)`, `ERROR TERMINATION`, while the
  converter reported "3 element(s) were kept" for a 2-beam block. With the
  screen the same deck converts to exactly 2 beams and runs 0 errors / NORMAL
  TERMINATION, and the warning names the kept count AND the dropped one.
  `_NURBS_PATCH` stays a whole-block skip regardless: its card *is* six positive
  integers (NPEID PID NPR PR NPS PS) meaning polynomial orders and
  control-point counts, so there is no mesh in it to keep.
  `k2rad/assembly.py`'s `*INCLUDE_TRANSFORM` offset
  table got the same grammar and the same prefix fallback (an unmapped element
  keyword would otherwise keep its original node ids while the nodes around it
  were renumbered — dangling connectivity, not just a missing warning).

  Card layouts: the base connectivity card is 10 x I8, the shared optional card
  is **5 x F16** (`THIC1..THIC4` + `BETA`|`MCID`, present for `_THICKNESS`,
  `_BETA` and `_MCID` alike — `Keyword971/ELEMENTS/shell.cfg:193`), `_OFFSET`
  adds one more F16 and `_DOF` a `%16s%8d%8d%8d%8d` card; `THIC5..THIC8` appears
  only when the mid-side nodes N5..N8 are defined. `*ELEMENT_BEAM_ORIENTATION`'s
  card is **3 x F10**, not F16 (`beam.cfg`, `if_ORIENTATION==1`) — the beam
  family mixes 8-, 10- and 16-char fields across its own cards.

  **`/SH3N`'s optional columns are 61-80 / 81-100, the same as `/SHELL`'s — the
  shipped cfg is wrong.** `radioss41/ELEM/shell3n.cfg` writes the blank gap as
  `%30s` (Phi at 71-90, Thick at 91-110) while the `COMMENT()` line in the same
  file says 61-80 / 81-100. The starter follows the comment: an `/IOFLAG` IPRI=5
  probe read a value ending in column 90 back as the THICKNESS and discarded
  everything past column 100. One code path therefore serves both cards.
  `Phi` is in DEGREES on the card (`hm_read_shell.F:170` multiplies by PI/180)
  and `Thick = 0` is the documented "use the `/PROP/SHELL` thickness" value
  (`cinmas.F:324-329`), which is why the two fields are emitted only when there
  is something to say. The nodal thickness cells are keyed on the CARD SLOT, and
  a collapsed quad may repeat a corner in ANY slot (`n1 n1 n2 n3` survives with
  slots 0, 2, 3), so the mean is taken over the surviving corners' slots rather
  than over the first three cells.

  **`Thick` resolves a zero cell against the `*SECTION_SHELL` thickness, per
  VALUE.** Vol I R17 *ELEMENT_SHELL Card 2 defaults `THIC1..THIC4` to `0.` — so
  a blank cell and an explicit `0.0` are the SAME input — and Remark 1 reads
  "Default values in place of zero shell thicknesses are taken from the
  cross-section property definition of the PID". With `T=1.5`, `THIC1=4.0` plus
  three empty cells is therefore `(4+1.5+1.5+1.5)/4 = 2.125`. Both other
  readings are wrong and wrong differently: dyna2rad divides the written values
  by the node count (`convertelements.cxx:290-301`) and gets 1.0, and averaging
  only the non-empty cells gets 4.0 — the latter also makes two LS-DYNA-identical
  elements differ by 4x depending on which spelling of "zero" was used. When the
  part has no usable section thickness (k2rad's auto-section is 0.0) the
  non-zero cells are averaged on their own.

  **`BETA` on an orthotropic part is folded into the PROPERTY, because that is
  the only place the solver reads it.** k2rad writes the angle to the `/SHELL`
  `Phi` column and the starter reads it back correctly (90° echoes as
  1.570796326795 rad under `/IOFLAG` IPRI=5) — and then discards it.
  `starter/source/elements/shell/coque/corthini.F` builds the layer angle from
  the property alone for IGTYP 1 (`:110`, an early RETURN), 9 (`:202`), 10/11
  (`:206-217`) and 16 (`:429-435`); only IGTYP 17/51/52 do
  `PHI1(J,I) = ANGLE(I) + …`. Measured on a *MAT_002 plate with E1/E2 = 100
  pulled along global X: per-element `BETA=90` on the `/PROP/TYPE11` part gave
  **103094.25 MPa, byte-identical to its `BETA=0` twin (ratio 1.000000)**, where
  `Q22 = 25789.81` was required — the 90° fibre rotation did nothing at all. So
  when every shell of such a part shares one angle it is now added to the
  property's own reference angle (`/PROP/TYPE9` `GEO(10)` / the `/PROP/TYPE11`
  layer `Phi`) and the element column is cleared; re-measured, that deck reads
  **25773.52 MPa, ratio 0.250000 exactly (dev -0.063% vs Q22)**. A per-element
  *variation* cannot be represented at all — one `/PROP` serves the part — and is
  warned about loudly instead. `*PART_COMPOSITE` (`/PROP/TYPE51`) is untouched:
  `ANGLE(I)` IS added there, measured at ratio 0.250084.

  `*ELEMENT_PLOTEL` has no PID column at all — LS-DYNA assigns part id 10000000
  implicitly (Vol I R17, Remark 1) — so the converter fabricates a `/PART` and a
  `/PROP/TYPE4`, both at that id, both guarded against a deck that already uses
  it. `MASS = 1.1e-15` is the smallest legal value: `hm_read_prop04.F:136-142`
  rejects `MASS <= 1e-15` with ERROR 229. `K = C = 0` is what makes it inert in
  both senses — `r1len3.F:81-105` leaves `STI` at zero unless `XK` or `XC` is
  non-zero (no nodal-stiffness contribution to the parts it is drawn on), and
  `r1len3.F:139`'s `DT = XM/MAX(EM15, SQRT(XC²+XM·XK)+XC)` floors at the EM15
  clamp instead of dividing by zero, giving ~1.1 s raw, which the starter's
  damping-limit term (`rinit3.F`, `DTC = HALF*XM/MAX(EM15,XCM)`) halves: the
  element table prints **0.55 s** against 1.7e-6 s for the shells in the same
  model. Because `K = C = 0` really does mean no stiffness, a node touched only
  by a PLOTEL is still FREE for the implicit singularity guard — it is not in
  the guard's element-node set, the same way a synthesized beam-orientation node
  is subtracted from it. (The `1.1e-15` per element does move the starter's
  TOTAL MASS echo, `1.2560000000000E-05` → `1.2560000003300E-05` Mg for three
  PLOTELs: a 2.6e-10 relative change with every part mass, the time step and the
  result history bit-identical.)

  `*ELEMENT_DISCRETE`, MAT_100 spotweld beams and `*ELEMENT_PLOTEL` all become
  `/SPRING` under their SOURCE-deck ids, which LS-DYNA keeps in three separate
  namespaces and Radioss in one; every pairwise overlap is now reported up front
  rather than surfacing as starter ERROR 79 (DUPLICATE ID) with no restart file.

  Validated end to end: `starter_win64.exe` on a deck carrying all three
  families reports **0 errors**, echoes ANGLE 0.5235987755983 rad (= 30°) /
  THICKNESS 2.5 for the quad and 0.2617993877991 rad (= 15°) / 1.0 for the
  `/SH3N`, reads the MCID variant's angle back as 0.0, gives the PLOTEL springs
  a 0.55 s time step, and lands a total mass of 1.4130000002200E-05 Mg — the
  hand calculation to the last digit, including the 2.2e-15 the two PLOTELs add.
  The engine runs it to NORMAL TERMINATION in 9082 cycles.

  New `state.next_node_id()`, in the `next_curve_id` / `next_part_id` /
  `next_prop_id` family. Every existing node-synthesis site open-codes
  `max(state.nodes) + 1`, which is safe only because each registers its id
  before the next site computes its own maximum — an undocumented, unenforced
  invariant. A site that allocates a batch and registers afterwards hands the
  same id out twice, and since `state.nodes` is a dict the second write silently
  *replaces* a node rather than erroring. The new allocator also skips ids it
  has already handed out; it starts from the same base, so it shifts nothing.

  **Deliberate divergences from dyna2rad, each a defect it has rather than a
  convention it holds:**
  * dyna2rad recognizes only `*ELEMENT_SHELL`, `_THICKNESS`, `_BETA` and
    `*ELEMENT_BEAM_ORIENTATION`. Its CFG keyword table matches USER_NAMES
    exactly (`mv_solver_input_infos.cpp:494-499`, `myUserNameExactMatch`), so
    every other spelling — including all the combined ones — is an unmatched
    header and the whole block is skipped with an error whose text is even the
    wrong message (`msg_arrays.cfg` index 1 instead of 2). k2rad keeps the mesh
    for all of them.
  * The thickness mean substitutes the `*SECTION_SHELL` value for every zero
    cell, which is LS-DYNA's documented rule. dyna2rad's reader cannot
    distinguish a blank cell from an explicit `0.0` and always divides by the
    node count (`convertelements.cxx:290-301`), so `THIC1=2.0` with three blank
    cells converts to 0.5 — a quarter of the thickness, a quarter of the mass
    and a sixty-fourth of the bending stiffness.
  * `_BETA` keeps its thicknesses. dyna2rad reads the shared card and then tests
    `elemKeyWord.find("THICK")`, which fails under `_BETA`, forcing `Thick = 0`
    and discarding values it had already parsed.
  * `MCID` is never written into the `Phi` column. It shares columns 65-80 with
    `BETA` but names a `*DEFINE_COORDINATE_SYSTEM`; treating it as degrees would
    silently rotate the material axes by `<cid>` degrees.
  * The synthesized third node is actually wired into the beam.
    `convertelements.cxx:229-232` executes `elemNodes[2] = <new id>` *before*
    `elemNodes.resize(3)`, and a beam whose N3 column is blank — the normal
    `_ORIENTATION` case — arrives with only two nodes, so the resize
    value-initializes slot 2 back to 0. dyna2rad therefore creates the node and
    emits `node_ID3` as 0 for exactly the elements the option exists for.
  * One node per distinct (N1, vector) pair instead of one per element, and a
    warning when the vector is parallel to the beam's own N1-N2 axis (a
    collinear third node cannot define the local Y-Z frame; dyna2rad does not
    check).
  * The orientation VECTOR is rotated by a `*INCLUDE_TRANSFORM` TRANID, not only
    the ids. Under a 30° `ROTATE` the nodes move but an untransformed vector
    leaves the local Y-Z frame behind (verified: the third node landed at
    `(0.866, 1.5, 0)` instead of `(0.366, 1.366, 0)`) and at 90° it can become
    collinear with the rotated beam axis. Under an option suffix k2rad does not
    model the vector card's POSITION is unknown, so those blocks fall back to
    the existing "carries literal geometry that was NOT transformed" warning.
  * The `*ELEMENT_BEAM` base card is read by COLUMN when a fixed I8 reading is
    consistent with the whitespace split. The manual says N3 "should be left
    undefined" under `_ORIENTATION`, so a card that also sets the trailing
    `LOCAL` flag splits to five tokens and the flag is read as the orientation
    node — a silently wrong local frame, or an id that does not exist. Free
    format and sloppily aligned cards keep the whitespace reading.

- **Composites: `*MAT_ORTHOTROPIC_ELASTIC` (002) → `/MAT/LAW93`,
  `*MAT_ENHANCED_COMPOSITE_DAMAGE` (054/055) → `/MAT/LAW127`,
  `*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC` (037) → `/MAT/LAW43`,
  `*MAT_LAMINATED_GLASS` (032) → a `/MAT/PLAS_BRIT` (LAW27) pair, and
  `*PART_COMPOSITE` → `/PROP/TYPE51` + one `/PROP/TYPE19` per ply.** No flag: a
  deck without composite cards is byte-identical (all five goldens unchanged,
  asserted again inside `tests/test_composites.py`). New writer module
  `k2rad/writer/composites.py`; 103 new tests (1147 -> 1250).

  Every one of these laws registers as orthotropic- or composite-class in the
  starter (`PROP_SHELL = 2`, `init_mat_keyword.F:212-249`) and `/PROP/SHELL`
  (IGTYP 1) accepts only classes 1 and 5
  (`check_mat_elem_prop_compatibility.F:173-176`), so **a converted part can
  never stay on its section's isotropic property** — each is repointed onto a
  synthesized orthotropic one via a new `state.composite_prop_ids` split, the
  same mechanism the LAW128 (MAT_103) path uses. This is a real dyna2rad
  defect, not just a design choice: its `p_ConvertSectionShell`
  (`convertprops.cxx:734-765`) matches neither MAT_054/055 nor
  `*MAT_ANISOTROPIC_ELASTIC`, so both fall through to `/PROP/TYPE1` and
  hard-fail the starter with ANCMSG 3047.

  **`*PART_COMPOSITE` had no handler at all before this batch, and the failure
  mode was mesh loss, not a skip.** `_make_parts_and_elements` emits elements
  *inside* the `state.parts` loop, so a part with no `PartData` is never
  reached — the entire part and every element on it vanished from the deck with
  no warning of any kind. The handler now always registers the `*PART`, for
  every OPTION1/2/3 spelling including the ones whose layup cannot be
  converted.

  Card layouts are from the `hm_cfg_files` revision a `/BEGIN 2022` deck
  actually reads: `MAT/matl93_ORTH_HILL.cfg FORMAT(radioss2021)`,
  `MAT/matl43_HILL_TAB.cfg FORMAT(radioss2021)`,
  `MAT/matl27_plas_brit.cfg FORMAT(radioss2019)`,
  `MAT/matl127_enhanced_composite.cfg`,
  `PROP/prop_p11_sh_sandw.cfg FORMAT(radioss2022)`,
  `PROP/prop_p51.cfg FORMAT(radioss2022)`,
  `PLY/prop_ply.cfg FORMAT(radioss2017)`,
  `FAIL/fail_fld.cfg FORMAT(radioss2019)` and
  `FAIL/fail_gene1.cfg FORMAT(radioss2022)`.

  **The Poisson conventions are the one real numeric trap, and the two target
  laws disagree with each other.** LS-DYNA states its compliance matrix with
  `−ν_ba/E_b` in the (1,2) slot (Manual Vol II R16 p.2-156) and calls `PRBA` the
  *minor* ratio; Radioss LAW93 states it with `−NU12/E11` and derives
  `NU21 = NU12·E22/E11` (`hm_read_mat93.F:192,203`), so `NU12` is the *major*
  ratio and reciprocity forces `NU12 = PRBA·EA/EB`, `NU13 = PRCA·EA/EC`,
  `NU23 = PRCB·EB/EC` — a 1:1 copy is wrong by `EA/EB`, an order of magnitude
  for a typical UD ply. LAW127 is the opposite: `hm_read_mat127.F90:127-129`
  reads `PRBA→nu21`, `PRCA→nu31`, `PRCB→nu32` and does the reciprocity step
  itself (`:186-198`), so those are copied **raw** and applying the LAW93
  rescale would double-apply it. The two paths deliberately share no helper.
  Also note LAW93's shear swap, `GBC→G23` and `GCA→G13`.

  **LAW127 at `/BEGIN 2022`.** `matl127_enhanced_composite.cfg` exists only in
  the `radioss2026` cfg folder, so on paper the downward-only cfg search path
  puts it out of reach. Empirically it is not: `starter_win64.exe` reads a
  `/BEGIN 2022` deck containing `/MAT/LAW127` with **0 errors** and echoes
  E1/E2/E3, G12/G13/G23, nu21/nu31/nu32, XT/XC/YT/YC/SC and every SLIM* factor
  at their exact input values, at the cost of one cosmetic `WARNING 100211`
  ("Unsupported option /MAT/LAW127 in format < 2025"). That is the identical
  trade-off `/MAT/LAW128` already ships under, so LAW127 is used rather than
  degrading MAT_054 to `/MAT/LAW25`. Both the full composite deck and a
  variants/fallback deck were run through the starter to 0 errors.

  Deliberate divergences from dyna2rad, each a defect it has rather than a
  convention it holds:

  * `*MAT_ANISOTROPIC_ELASTIC` (the 002 6×6 C-matrix dialect) is **not
    emitted**. `p_ConvertMatL2` never checks the dialect, so it writes a
    `/MAT/LAW93` with **all moduli zero and no warning** — a silently
    stiffness-free material. LAW93 has nine engineering-constant slots and no
    home for the 12 coupling terms; inverting `C` is only well-defined when they
    all vanish, and guessing the Voigt shear-index convention would risk exactly
    the silently-wrong material being avoided. k2rad warns loudly, names the
    referencing parts and reports it under *recognized but not emitted*.
  * The MAT_037 hardening curve is actually **bound**. dyna2rad emits the same
    `{(0, SIGY), (1, SIGY + |ETAN|)}` slope, but never binds it: missing braces
    at `convertmats.cxx:3100-3102` put line 3102 outside the `if/else`,
    overwriting `func_IDi[0]` with `HLCID` (= 0) in both branches and leaving
    `NUM_CURVES = 1` pointing at function 0 → starter ANCMSG 366
    (`hm_read_mat43.F:158-164`).
  * **The `TFAIL` band.** LS-DYNA switches criterion at **0.1**, not at 1
    (Vol II R17 p.2-441): `0 < TFAIL ≤ 0.1` is an *absolute* minimum time step,
    `TFAIL > 0.1` is the *ratio* `dt/dt₀`. dyna2rad gates its `/FAIL/GENE1`
    companion on `0 < TFAIL < 1` (`convertmats.cxx:3205-3219`), so every ratio
    in `(0.1, 1)` is re-emitted as an absolute `dtmin` — and `/FAIL/GENE1`'s
    `dtmin` really is absolute (`fail_gene1_c.F:398`
    `IF (GBUF_DT(I)*DTFAC1(1) <= DTMIN)`), so in a Mg/mm/s deck (`dt ≈ 1e-7`) a
    `TFAIL` of 0.5 deletes **every element of the part on cycle 1**, silently.
    The band here is the manual's; the ratio form is warn-dropped, because it
    has no Radioss counterpart *and* does not survive in the LAW127 `TFAIL`
    column either — `hm_read_mat127.F90` never fetches that field.
  * The MAT_032 `F_i` polarity. LS-DYNA: `F_i = 0` → glass, `1.0` → polymer.
    `ConvertSecShellsRelatedMatLaminate` (`convertprops.cxx:1620-1641`) inverts
    it **and** rewrites the `/PART`'s `mat_ID` inside the layer loop, so every
    layer after the first polymer one also gets the polymer; its own
    `*INTEGRATION_SHELL` path (`:2024-2050`) has the correct polarity. The
    correct one is used.
  * `*PART_COMPOSITE` missing-ply filtering. A layer with `THICK = 0` and
    `MID = -1` is LS-DYNA's alignment padding. dyna2rad reduces `lsdNip` to the
    valid *count* but its emission loop still walks indices `0 … nipOk-1`, so a
    hole in the middle silently drops the **last** ply
    (`convertprops.cxx:3588-3680`). Filtering is by identity here.
  * `*PART_COMPOSITE` material axes. dyna2rad reads ply 0's material
    unconditionally; LS-DYNA specifies the **first orthotropic** integration
    point (Remark 1 — later plies' AOPT/BETA are ignored), so an isotropic ply 0
    would lose the axes. Its `AOPT < 0` branch (`convertprops.cxx:3630-3634`) is
    also dead code — `axisOptFlag` is never negative after the cfg's enum remap
    — so a `*DEFINE_COORDINATE` system is lost entirely on TYPE51; here it binds
    to that system's own `/SKEW` id with `Ip = 0`.
  * `MANGLE` (MAT_054's material-angle offset, card 3 field 7 — distinct from
    card 6's `BETA`, which is the shear-term weighting) is never read anywhere
    in dyna2rad; it is carried onto the property rotation. `BETA` is applied
    whenever nonzero rather than only when `> 0`, which silently drops a legal
    negative rotation.
  * `EA*PRBA/EB` and friends are evaluated by dyna2rad through exprtk with **no
    zero guard** (`convertmats.cxx:643-645`), yielding `inf`/`NaN`; zero `EB`/`EC`
    take the starter's own `E22←E11`, `E33←E22` fallbacks here, and an unstable
    `NUij·NUji ≥ 1` pair is warned before the starter's ERROR 3068 / ERROR 307.

  Faithfully replicated dyna2rad behaviour: the MAT_032 id convention (polymer
  keeps the LS-DYNA MID, glass takes a synthesized id, the `/PART` points at the
  glass) and its `EFG` / `EFG+0.05` / `EFG+0.1` damage ramp; `RATIO = |PFL|`;
  the `/FAIL/GENE1` `dtmin` companion itself (`hm_read_fail_gene1.F:146`), on
  the manual's `TFAIL` band rather than dyna2rad's; `/FAIL/FLD` with
  `Ifail_sh = 2` and `Istrain` 2/1 from the `ECHANGE_OPTION` enum;
  `NLOC`→`Ipos` 0/4/3 and `Ithick = 1`; and the `NIP > 10` layer clamp.
  `*PART_COMPOSITE`'s `Ishell` deliberately does **not** follow dyna2rad's
  hard-wired 12/24 split on `ELFORM` −16/9: it goes through the same
  `_elform_to_ishell` mapping — and therefore the same `--shell-formulation`
  option — as every other k2rad shell property, so one LS-DYNA `ELFORM` cannot
  produce two different Radioss formulations depending on whether the part used
  `*SECTION_SHELL` or `*PART_COMPOSITE`. Likewise a **blank** `SHRF` keeps
  Radioss's 5/6 `Ashear` (dyna2rad never sets the field) instead of LS-DYNA's
  own 1.0 default, which would stiffen transverse shear by 20% off a default
  rather than off deck data; an explicitly given `SHRF` is still carried.

  Warn-dropped with the physics consequence named, not silently as dyna2rad
  does: MAT_054's `SOFT`/`SOFT2`/`SOFTG` (crashfront softening — a crush front
  propagates less readily than in LS-DYNA), `KF`, `DT` and `CRIT = 55` (LAW127
  is Chang-Chang only; the cfg declares `LSD_CRIT` but no `CARD()` ever writes
  it, so dyna2rad's MAT_054 and MAT_055 output is byte-identical);
  `TFAIL > 0.1`'s ratio form (Radioss `dtmin` is absolute, and LAW127's `TFAIL`
  column is never read by the starter, so it survives nowhere); MAT_037's
  negative-`ETAN` include-normal-stresses flag (the magnitude is kept as the
  hardening modulus); MAT_002's `MACF` axis
  swap, `G`, `SIGF` and `REF`; MAT_037's `STRAINLT` (the `/FAIL/FLD` `ALPHA`
  column does not exist in the FORMAT(radioss2019) block a `/BEGIN 2022` deck
  reads); and `*PART_COMPOSITE`'s `OPTCARD` `IRPL`, `_CONTACT` `OPTT`, `TMID`,
  `ADPOPT` and `THSHEL`. `*PART_COMPOSITE`'s `MAREA` is warn-dropped too, but
  the warning says so explicitly: dyna2rad *does* convert it (to an `/ADMAS`
  type 2 over a `/SET/GENERAL` of the part), so a layup with non-structural mass
  comes out lighter here than through dyna2rad, changing inertia and the nodal
  time step.

  Supporting changes: `ConversionState.next_mat_id()` + `all_mat_ids()` (the
  `/MAT` namespace guard the MAT_032 glass companion needs — k2rad emits every
  `/MAT` under the LS-DYNA MID verbatim, so a synthesized id colliding with a
  user MID at or above the auto-id base is starter ERROR 79); the ALE
  `/MAT/LAW51` in `blast_ale.py` now uses that guard instead of a bare
  `next_id()`, fixing the same latent hazard.

- **`*CONSTRAINED_JOINT_*` → `/PROP/TYPE45` (KJOINT2) + `/SPRING` + a
  node-derived `/SKEW/FIX`, with `*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED` /
  `_TRANSLATIONAL` filling the per-DOF blocks.** All seven kinematic joint kinds
  (`SPHERICAL`, `REVOLUTE`, `CYLINDRICAL`, `PLANAR`, `UNIVERSAL`,
  `TRANSLATIONAL`, `LOCKING`) with the `_ID`, `_TITLE`, `_LOCAL` and `_FAILURE`
  options. No flag: a deck without joints is byte-identical (all five goldens
  unchanged, asserted again inside `tests/test_joints.py`).

  `Type` integers are taken from `prop_p45_kjoint2.cfg:261-272`, cross-checked
  against dyna2rad's own dispatch (`convertconstrainedjoints.cxx`
  1613/1640/1666/1692/1718/1744/1770): 1 spherical, 2 revolute, 3 cylindrical,
  4 planar, 5 universal, 6 translational, **8** locking. `LOCKING` is *Fixed
  (Rigid)*, not 7 (*Oldham*) — Oldham is a planar joint without rotation and has
  no LS-DYNA counterpart.

  The frame is the load-bearing part. LS-DYNA's `N1`/`N2`, `N3`/`N4`, `N5`/`N6`
  are coincident pairs, so a naive 2-node `/SPRING` gives `LEN ≈ 0` and
  `GET_SKEW45` (`rini45.F:380-658`) aborts with **ERROR 936** for every `Type`
  except 1 and 8. `N3` is therefore forwarded into spring slot 3 (`UNIVERSAL`
  adds `N4`, `LOCKING` adds `N5`) and a `/SKEW/FIX` is emitted alongside,
  computed branch-for-branch the way `GET_SKEW45` would: 3 nodes → x = N3−N1 with
  the largest-|component| transverse rule; ≥4 nodes → x = N3−N1, ȳ = N4−N1;
  ≥4 and `Type=5` → y = N3−N1, z = N4−N1, **x = y×z** (the universal joint is the
  only kind that assigns the node directions to y/z rather than x/y). The skew is
  written as local **Y′ then Z′** per `skew_fix.cfg` — the starter rebuilds
  X′ = Y′×Z′ — and it is a *fallback*: the node branches are tested first and the
  `Skew_ID1` branch last, so writing it changes nothing in the normal case.

  A frame is **never** derived from just `N1`→`N2`. `GET_SKEW45` reads
  `Skew_ID1` only when the spring has exactly two nodes coincident to within
  `EM10` (`rini45.F:643`); above that the node branches win and the skew is
  ignored — and for `Type` 1/8 a non-zero `Skew_ID1` is actively harmful,
  because the clean global-frame branch (`rini45.F:439`) is gated on
  `IDSK1 == 0`, so writing one demotes the joint's axes to whatever mesh offset
  separates the two nodes. When a 2-node joint *is* coincident and a stiffness
  card names a `CIDA`, that converted `/SKEW` is used (and said so); when it is
  not, the `CIDA` is withheld and the mismatch is warned. `ERROR 936` is
  predicted off the starter's own `NNOD2` (`rini45.F:421-425`, bumped 2 → 3 for
  a non-coincident pair), not off the raw node count, so the prediction is exact
  in both directions. A `CYLINDRICAL` joint written with `N3 = 0` — the
  documented way to join a free node to a rigid body (R16 Vol I p.10-62) —
  falls back to `N4`, which is the same point by design, instead of emitting a
  2-node spring the starter rejects.

  `Kn = 0` (blocking stiffness derived from the time step) and `Cr` blank
  (starter default 0.05, `hm_read_prop45.F:155`). With `Kn = 0`, `ScF` **is**
  LS-DYNA's `RPS`: the engine applies it as `KX = ScF·KX ; KR = ScF·KR`
  (`joint_block_stiffness.F:220-221`, on the branch chosen by
  `FLAG = NINT(Kn) == 0`; GEO slot 10 = `Kn`, 11 = `ScF`,
  `hm_read_prop45.F:1087-1088`). The length² reading `Kn·MAX(ScF, LEN2)` belongs
  to the `Kn > 0` path only, so the mapping is exact and is not warned about.
  `RPS ≤ 0` therefore becomes **1.0** — LS-DYNA's own default, and a blank
  fixed-format column is indistinguishable from `0.0` — not dyna2rad's 0.01,
  which would divide the blocking stiffness by 100 and leave every joint a
  hundred times sloppier than the deck asks for. (The starter agrees: `ScF = 0`
  with `Kn = 0` is replaced by 1.0, `hm_read_prop45.F:163-169`.) A negative
  `RPS` (a load-curve id) is dropped loudly and falls back to the same 1.0.

  **dyna2rad defects deliberately not replicated** (all from its own source):
  * *One shared `/PROP/TYPE45` per joint KIND* for the whole model
    (`joints.cxx:1563-1576`), which silently discards the `RPS` of every joint
    after the first. k2rad emits one property per joint; properties are tiny.
  * *`Type = 0` on the `JID`-given stiffness path* (`joints.cxx:456-490`,
    `1160-1194`: `jntType` is never assigned) → starter **ERROR 938** `WRONG
    JOINT TYPE`. k2rad reads the type from the referenced joint.
  * *`"NSDY","PSDY"` read twice* (`joints.cxx:788`), so `NSDZ`/`PSDZ` silently
    receive the **Y** stop displacements.
  * *`{"SAx+", lsdNSAPS}`* (`joints.cxx:355`, 635, 1065, 1341) — the positive
    stop written from the negative value.
  * *No deg→rad factor on the `jntType==3` GENERALIZED stop angles*
    (`joints.cxx:225`), where the sibling branch at `:254` applies it. k2rad
    applies exact π/180 (not the hard-coded `0.01745`) to every rotational stop.
  * *Translational data written into the ROTATIONAL friction fields*
    (`joints.cxx:913`: `Kfrx ← ESX`, `FMx ← FFX`) and *translational stops
    written to `SAx±` instead of `SDx±`* throughout `ConvertStiffTransJoints` —
    for `Type=6` those fields are not even exported (`p45.cfg:1159-1173`), so the
    whole card is silently lost.
  * *Two `/SKEW/FIX` created with the same literal id*
    `GetDynaMaxEntityID(*DEFINE_COORDINATE)` (`joints.cxx:384-411` and six more),
    colliding with each other and with the existing max-id skew. k2rad needs no
    permuted skew at all: the joint's own frame already has the joint axis as its
    local X, so only the *channel selection* needs `CIDA`.
  * *Substring dispatch* (`keyWord.find("TRANS")`, `:1707`) would read a future
    `*CONSTRAINED_JOINT_TRANSLATIONAL_MOTOR` as a plain translational joint.
    k2rad registers 28 exact keywords, so motors/gears/rack-and-pinion/pulley/
    screw/constant-velocity land in `skipped_keywords` instead.
  * *`LOCK → 5`* in the stiffness pass's own classifier (`joints.cxx:150`), where
    5 is UNIVERSAL, and *UNIVERSAL/PLANAR unclassifiable* there at all. One
    correct table serves both paths.

  DOF blocks are **all-or-nothing**: the starter counts them against the `Type`'s
  requirement and raises **ERROR 973** `ONLY %d DOF DEFINED %d REQUIRED` on a
  partial set. A joint with no stiffness card therefore emits header + title +
  card 1 only — a complete, valid pure-kinematic joint — and one with a stiffness
  card emits the full set for its `Type`, empty blocks included. `Icomb_*` stays 0
  throughout: combining stops needs ≥2 flagged DOFs with *identical* stop values
  (`hm_read_prop45.F:1020-1068`) or it is ERROR 1598/1599/1600, and nothing in
  `*CONSTRAINED_JOINT_STIFFNESS` expresses one.

  Stop angles are converted degrees→radians and **sign-forced** (`SA-` ≤ 0 or
  ERROR 943, `SA+` ≥ 0 or ERROR 944) regardless of how the `.k` wrote them; stop
  displacements are lengths and are not scaled. A negative `FM*`/`FF*` is
  LS-DYNA's "−id is a curve" encoding and moves to the separate
  `fct_fm*`/`fct_ff*` field with the magnitude left blank (the starter then reads
  it as a 1.0 scale). A curve id no `*DEFINE_CURVE` defines is dropped rather
  than left dangling into a missing `/FUNCT`.

  Channel→DOF mapping: for a single-free-axis joint (`Type` 2/3/6) the `CIDA`
  axis within |cos| > 0.99 of the joint axis selects which of φ/θ/ψ (or x/y/z)
  drives the free DOF — exact, and the manual's own worked example (R16 p.977) is
  φ about local x of `CIDA`. The match keeps its **sign**: an anti-parallel
  `CIDA` makes a positive LS-DYNA rotation a negative Radioss one, so the
  asymmetric stop pair is mirrored (swapped and negated) rather than copied
  through — otherwise a −5°/+60° limit lets the joint travel 60° in the
  direction LS-DYNA caps at 5°. Referenced curves cannot be mirrored in place
  and that is said explicitly. For multi-DOF joints (1/4/5) φ→`Rx`, θ→`Ry`,
  ψ→`Rz` is an **approximation** — LS-DYNA's are z-y-z Euler angles, not Radioss
  local rotations — and is warned about. A channel carrying data for a DOF the
  `Type` does not have is dropped loudly. Where dyna2rad's unmatched-axis branch
  is literally `/* // post warning /error */` (`joints.cxx:442`, 722, 1146,
  1428), k2rad falls back to channel 0 and says so.

  One `_GENERALIZED` **and** one `_TRANSLATIONAL` card can share a joint: a
  cylindrical (`Tx`, `Rx`) or planar (`Ty`, `Tz`, `Rx`) `Type` carries both
  families and LS-DYNA writes them on separate cards, so they fill disjoint
  blocks and both are kept (a second card of the *same* option is what
  conflicts). `RPS` on the stiffness card overrides the joint card's only for
  `_TRANSLATIONAL` — "It only applies for keyword options TRANSLATIONAL and
  CYLINDRICAL", R16 Vol I p.10-91. `FS`/`FD` (card 2c.3 fields 7-8) are static /
  dynamic friction *coefficients*; `/PROP/TYPE45` knows only absolute
  force/moment limits, so they are dropped with a warning instead of silently.

  Checks dyna2rad does not make, each turning an opaque starter abort into a
  converter warning that names the joint: joint nodes belonging to **no `/RBODY`**
  (an LS-DYNA joint acts between two *rigid* bodies; k2rad refuses to attach them
  silently, since that changes the model's inertia and constrained set), a
  **degenerate axis** (ERROR 934/935/1009 — the universal branch reproduces
  `rini45.F:610`'s own `|z·y| / (|y×z| + |y|)` test verbatim, which is *not* a
  cosine and whose rejection angle depends on the model's length unit), a
  **node list shorter than the `Type` requires** with no frame to stand in for it
  (ERROR 936), a **stop with zero elastic stiffness**, which `/PROP/TYPE45`
  simply violates, a **`JID` carried by more than one joint** (silently
  last-wins otherwise), and an **all-rigid deck**: rigid-body elements are
  excluded from the time step, so a mechanism with no deformable element leaves
  the engine nothing to compute one from and `Kn = 0` asks it for exactly that —
  `joint_block_stiffness.F:92-99` aborts at cycle 0 with `ERROR NO TARGET TIME
  STEP DT= 1000000.00 / STIFFNESS CAN NOT BE COMPUTED` while the starter stays
  clean. All five joint validation decks needed one constrained deformable hex
  purely to pace the step.

  Plumbing: `/SKEW` ids come from a `build_starter` prepass (`_resolve_joints`)
  so they are reserved before `/FRAME` allocation — the two share ONE starter id
  namespace and a collision is `ERROR 79 DUPLICATE ID`, no restart file. The same
  prepass registers every joint spring node with the implicit free-node guard,
  which would otherwise `/BCS 111 111` a joint node attached to no element and
  weld the joint solid. `/PART` ids come from a new `state.next_part_id()`
  (guarded against `state.parts`, mirroring `next_curve_id`), because `next_id()`
  starts at 90001 and a deck numbering a real `*PART` there would collide. The
  `/PROP` namespace had the same hole and now has the same guard,
  `state.next_prop_id()` — `/PROP/SHELL`, `/PROP/SOLID` and `/PROP/BEAM` are
  emitted under the `*SECTION_*` SECID verbatim, so a SECID at or above 90001
  collided with the joint's synthesized `/PROP/TYPE45`; the other synthesized
  properties (`TYPE4`/`TYPE8`/`TYPE13` in `writer/loads.py`) draw from it too.
  Both allocators are unit-tested directly, because a converted deck usually
  walks the auto counter past the seeded id before the allocation happens and a
  broken guard would still ship green.
  `mat_ID = 0` on the synthesized `/PART` is correct and needs no `/MAT`:
  `hm_read_part.F:215-236` excludes `IGTYP 45` from the ERROR 179 list and
  substitutes an internal spring material. `*INCLUDE_TRANSFORM` offset maps cover
  all 28 joint keywords plus a callable for the stiffness cards (the `ES*` fields
  are floats sharing a card with the `FM*` ids, so a static field map would
  rewrite `ESPH=1000.0` into `1000+IDFOFF`; a negative `FM*` is warned instead of
  guessed at).

  `*DATABASE_JNTFORC` stops being a dead end — it stored a dt that nothing read
  — and now emits `/TH/SPRING` over the joint springs, with the group id drawn
  from `state.next_id()` per PR #83.

  The `_ID` heading is read from columns 1-10 only when it looks fixed-format:
  a comma now disqualifies it as well as a space, because the free-format
  heading `77,hinge` fits inside those ten columns, has no space, and
  `to_int("77,hinge")` is 0 — which silently unbound every stiffness card
  pointing at that `JID`.

  96 new tests in `tests/test_joints.py` (1051 → 1147): the `Type` integer and
  `/SPRING` node list for every kind, numeric `/SKEW` axis asserts (including
  orthonormality and right-handedness on an oblique 3-4-12 axis), exact column
  positions on every `/PROP/TYPE45` card, RPS/DAMP mapping, curve wiring,
  `_ID`/`_TITLE` dispatch (fixed and comma-delimited), id uniqueness across a
  7-joint deck, a swept `SECID` 90001..90030 `/PROP` collision check, the
  `_GENERALIZED` + `_TRANSLATIONAL` merge in both card orders, the anti-parallel
  `CIDA` stop mirror, the 2-node frame policy, the scale-dependent universal
  colinearity test, the degenerate / short-node-list / duplicate-`JID` /
  time-step-pacing warnings, and the golden fixtures re-asserted byte-for-byte.
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

- **The composite writer no longer predicts starter ERROR 3047 for an
  element-free part.** Diagnostics only — no emitted card changes, all five
  goldens byte-identical.

  `_assign_composite_props` used to tell the user that a part carrying an
  orthotropic or composite material but no elements "keeps its default
  property, which the starter rejects as incompatible with an orthotropic
  material (ERROR 3047) — check the mesh". That hard-failure prediction is
  false. `check_mat_elem_prop_compatibility.F` runs `DO NG = 1,NGROUP` over
  **element groups** and only then over each group's layers, so a part with no
  elements contributes no group and is never tested. Measured on
  `starter_win64` (nt=6): a meshed `*MAT_024` plate plus an element-free
  `*PART` on `*MAT_002` — `/MAT/LAW93`, `PROP_SHELL = 2` — resolving to the
  element-free-`*PART` placeholder `/PROP/SHELL` (IGTYP 1) gives
  `0 ERROR(S) 0 WARNING(S)`, `NORMAL TERMINATION`, the empty part echoed as
  "ISOTROPIC SHELL PROPERTY SET NUMBER 9" and "Part id,name: 9 ortho carrier,
  Mat type: 93 Elm type: N/A". Same at 0/0 with a `*PART_COMPOSITE` layup on
  the empty part, and when the empty part is also an `*INTEGRATION_SHELL`
  `PID_i` carrier.

  The message is now a **mesh sanity check**: an orthotropic or composite
  material is normally written for a meshed part, so an empty one is usually a
  PID typo or an `*INCLUDE` that did not resolve — and a deliberately
  element-free part, such as an `*INTEGRATION_SHELL` `PID_i` material carrier,
  is idiomatic and needs no fix. It also now names the `*PART_COMPOSITE` layup
  as dropped where there is one. The genuine ERROR-3047 warning on *meshed*
  composite parts, which really would hard-fail on the isotropic
  `/PROP/SHELL`, is unchanged.

- **The `*INTEGRATION_SHELL` `PID_i` material-carrier warning is gone** (it was
  dropped in the merge of the element-free-`*PART` fix; recorded here for the
  release notes). It told the user to give an element-free carrier part a
  `*SECTION_SHELL` by hand or delete the `*PART`, on the grounds that the deck
  would otherwise hit starter ERROR 178. Since element-free parts get a
  placeholder property automatically, there is nothing to repair and the
  ERROR 178 no longer happens. Verified on `starter_win64`: a rule whose
  `PID_i` names a part with no elements **and no `*SECTION`** converts and runs
  `0 ERROR(S) 0 WARNING(S)`, identical to the control deck where the carrier is
  given a `*SECTION_SHELL` by hand. The synthesized `/PROP` is still explained
  once, by the generic element-free-`*PART` report that names the pid — one
  message per empty part, not two.

- **⚠ BEHAVIOUR CHANGE — every gravity deck converts differently now.** Two
  independent corrections land together in the `/GRAV` emitter (details and
  solver evidence under *Fixed*, below):
  1. **every deck with a rigid body** (`*MAT_RIGID` or
     `*CONSTRAINED_NODAL_RIGID_BODY`) **plus `*LOAD_GRAVITY_PART` or
     `*LOAD_BODY_*`** gets a different `/GRNOD` — the rigid body used to
     receive **no gravity at all** and now receives the correct load. This
     includes the W13 blast decks (their `*LOAD_BODY_Y` covers a `*MAT_RIGID`
     ground part);
  2. **every `*LOAD_BODY_{X,Y,Z}` deck may change sign** — `Fscale_Y` is now
     `-SF` instead of `+SF`. A deck that was hand-tuned by flipping `SF` to
     make the old conversion fall the right way will now fall **upward**;
     restore the `SF` its LS-DYNA deck actually carries.

  Re-run any archived gravity conversion; do not compare new results against
  old `.rad` files without re-converting the `.k`.
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

- **Every `ELFORM = 9` spot weld converted with a nugget area that was not an
  area. `*SECTION_BEAM` card 2 was read as the wrong card, and the six spot weld
  decks in `Ryan_Lee_Examples/` all change.**

  `handle_section_beam`'s ELFORM = 9 branch was commented
  `VOL INER CID CA OFFSET RRCON SRCON TRCON` and stored field 1 as a nugget
  *volume* and field 4 as a cross-section *area*. That is **card 2f**, and card
  2f is for `ELFORM = 6`, the discrete beam. The spot weld beam has its own
  card: "Spot Weld Card (type 9). Include this card when ELFORM equals 9 —
  `TS1 TS2 TT1 TT2 PRINT - ITOFF -`" (Vol I R17 p.41-22), where `TS1`/`TS2` are
  the "outer diameter (CST = 1.0) in 푠-direction at node 푛1 / 푛2" and
  `TT1`/`TT2` the matching **inner** diameters (p.41-22/23). dyna2rad's cfg
  agrees field for field —
  `CARD("%10lg%10lg%10lg%10lg%10lg", LSD_THIC1s, LSD_THIC2s, LSD_THIC1t, LSD_THIC2t, LSD_TPRINT)`
  under `else if (LSD_ELFORM == 9)` (`Keyword971/PROPERTY/SectBeam.cfg:464-470`).

  So the "area" was `TT2`, which is **0.0 on all six decks**, and the writer's
  fallback then divided the "volume" — really `TS1`, a diameter — by the weld
  length:

  ```python
  area = sec.ca                     # = TT2 = 0.0
  if area <= 0.0 and sec.vol > 0.0:
      area = sec.vol / L            # = diameter / length: dimensionless
  ```

  A length over a length. In an SI (m) deck that lands near **1**, so
  `W16_spotweld_E1.k` sized its 3 mm welds at **A = 1.5 m²** instead of
  7.07e-06 m² — 212 000× too stiff, `K_axial` 1.575E+14 instead of 7.42E+08,
  and a weld *mass* of 23.55 kg apiece. The `*MAT_SPOTWELD` yield force
  `SIGY·A` came out at 5.25E+08 N for a 3 mm nugget, i.e. the weld could never
  reach yield and behaved as a rigid link. In a mm deck the same expression
  lands near 1 mm² and reads as *under*-stiff instead
  (`W16_SW_door_*.k`: 0.44–1.23 mm² against the true π mm²). Worst of all it
  scaled with `L`: identical welds off one `*SECTION_BEAM` got **different**
  stiffnesses depending on how far apart the sheets happened to be.

  Card 2i is now parsed into honestly named fields — `SectionBeam.ts1/ts2/tt1/
  tt2`, plus `cst` (card 1 field 5) and `itoff` (card 2i field 7); the
  `vol`/`ca` slots that only ever held mis-parsed diameters are gone. The
  nugget is sized as the circular section the diameters describe,

  ```
  d_o = mean(TS1, TS2)      d_i = mean(TT1, TT2)
  A   = π (d_o² − d_i²) / 4     I = π (d_o⁴ − d_i⁴) / 64     J = 2I
  ```

  which is dyna2rad's `ConvertToPropType13` verbatim (`convertprops.cxx`:
  `meanTS = (lsdTS1 + lsdTS2) / 2.0`, `area = piVal * (pow(meanTS, 2) -
  pow(meanTT, 2)) / 4.0`) and, at `TT = 0`, is exactly the `π d²/4` the
  neighbouring `ELFORM = 1` branch already used — the two spot weld
  formulations finally agree. The **mean** is the right reduction because
  `TS1`/`TS2` are the diameters at the two *ends* of one beam and a
  `/PROP/TYPE13` spring is prismatic; a blank end column is treated as an
  omission (the populated diameter is used for both ends, with a warning)
  rather than a nugget tapering to a point, because averaging the blank in
  would quarter the area for no stated reason.

  Warnings now report the resolved geometry (`outer d=…, inner d=… -> A=…`) and
  flag the three things this mapping does not honour: `CST ≠ 1` (a rectangular
  or user-rule section still becomes a round nugget — dyna2rad makes the same
  assumption), `TT ≥ TS` (sized solid instead), and `ITOFF = 1` (torsion-free
  welds keep their elastic `Rx` stiffness).

  **The starter never complained — before or after.** `W16_spotweld_E1.k`
  converts to `0 ERROR(S)`, `6 WARNING(S)` both ways; the bug was invisible to
  every check the deck passes. What the starter *does* print is the giveaway:

  ```
                              master                    fixed
  SPRING MASS         23.55000000000        1.1097676050000E-04
  TOTAL MASS          95.23557817859             1.036022085632
  ```

  95.2356 − 1.0360 = 94.1996 = 4 × 23.5499: the four spot welds were carrying
  **94.2 kg of spurious mass on a 1.04 kg model**, a 92× error, and it rode
  through the starter silently.

  The engine settles it. The fixed deck runs the full 0.1 s to
  **`NORMAL TERMINATION`** in 721 395 cycles (42:38, np=1/nt=6), time step held
  at `1.386E-07 s` throughout, `MAS.ERR 0.000`, `MASS ADDED 0.000`. The master
  conversion is dt-limited to `5.816E-10 s` — 238× lower, `SPRIN` element 1
  governing in both — and after 38 285 cycles had reached `t = 2.226E-05 s` of
  the 100 ms event, i.e. 0.02 %. It would need ~1.7e8 cycles to finish and was
  stopped; a `/TH/SPRING` probe on it produced **zero** samples because it never
  reached the first output interval. So there is no before/after weld-force
  curve to show: the old conversion was not merely wrong, it was
  computationally infeasible.

  Scope: of the 83 `.k`/`.key`/`.dyn` decks on this machine exactly six carry an
  `ELFORM = 9` `*SECTION_BEAM`, and a before/after SHA256 sweep over every deck
  reachable from the repo changes those six and nothing else. All five goldens
  are byte-identical. 10 new tests in `tests/test_connectors.py`
  (1563 → 1573 at this branch's base; 1587 → 1597 once the concurrent PRs are
  merged in).

  Two things this deck shows that are **not** this bug, recorded so they are not
  rediscovered: `*CONTACT_SPOTWELD` is still `SKIPPED`, so the weld beams'
  nodes (2059–2066 here) reach the starter attached to nothing but each other —
  weld force is 0.000 N before *and* after, and the mass/stiffness numbers above
  are what actually verifies this fix. And all four springs draw starter
  `WARNING ID 327`, "BAD SPRING FRAME DEFINITION (PARALLEL AXIS)", identically
  on master and here.

- **A `*INITIAL_FOAM_REFERENCE_GEOMETRY` was dropped on `*MAT_RIGID` and
  `*MAT_SPOTWELD` parts under a warning that named a law violation that does not
  exist.** `inistate.py` resolved each part's law through its own private
  7-family table for the starter's solid-`/XREF` whitelist (1/35/38/42/70/88/90,
  `hm_read_xref.F:222-226`, else ERROR 2014). The table returned `None` — read as
  "some other law" — for the two families that reach `/MAT/ELAST` by a route
  other than `*MAT_ELASTIC`: `*MAT_RIGID`, and the `*MAT_SPOTWELD` fallback a
  MAT_100 part gets when it is not a pure-beam connector. **Both are LAW1 and
  LAW1 is on that whitelist**, so both lost their stress-free reference geometry
  and were told the wrong reason for it.

  The table is gone. The gate now reads `mesh.py::_target_mat_law`, the complete
  mid → law routing added with the `/PROP/BEAM` material check below, so there
  is ONE such map in the codebase; the off-whitelist message gained the actual law
  number as a side effect (`/MAT/LAW36, which is outside …` instead of `a law
  outside …`), and distinguishes it from a material that gets no `/MAT` at all.
  The two families are then decided on their own merits, both measured on
  `starter_win64` (nt=6), one hexa on a `*SECTION_SOLID` with a 4-node reference
  geometry:

  - **`*MAT_SPOTWELD` fallback → the `/XREF` is emitted.** It is an ordinary
    deformable part with a real unstressed configuration. Converted deck:
    `NORMAL TERMINATION`, `0 ERROR(S) 0 WARNING(S)`. The section is promoted to
    `Ismstr=10` with it, as for any other kept `/XREF` part (ERROR 2013
    otherwise). The pure-beam MAT_100 connector is untouched — it has no `/MAT`
    at all and no solid elements, so it never reaches the gate.
  - **`*MAT_RIGID` → still no `/XREF`, for the right reason.** The part converts
    to an `/RBODY`, every node it owns is kinematically slaved to the rigid
    master, and it has no strain state a reference geometry could define. This
    is *not* a starter rejection — force-emitting the block on a rigid brick
    also measures `NORMAL TERMINATION`, `0 ERROR(S) 0 WARNING(S)` — it is inert,
    while dragging the part's `*SECTION_SOLID` from `Ismstr 0` to `10`
    (measured), which the shared-section rule then propagates to any deformable
    part using that section. The warning now says that instead. Applied before
    the solid/shell split, so a rigid *shell* part — which the shell branch,
    having no law gate, used to hand an equally meaningless `/XREF` — follows
    the same rule.

- **The element-free composite warning claimed the starter accepts a part that
  it ERROR-TERMINATES on.** The check guarded on "no shell or solid elements",
  which is also true of a part holding only BEAM elements, and then promised
  "the starter ACCEPTS that: its material/property compatibility check runs per
  ELEMENT GROUP … and a part with no elements contributes none". A beam-only
  part contributes a group. Measured on `starter_win64` (nt=6), two
  `*ELEMENT_BEAM` on one `*SECTION_BEAM` ELFORM=2, part material
  `*MAT_ORTHOTROPIC_ELASTIC` (`/MAT/LAW93`) — `1 ERROR(S)`,
  `ERROR TERMINATION`:

  ```
  ERROR ID :   3046
  ** ERROR IN MATERIAL/ELEMENT COMPATIBILITY
  DESCRIPTION :
     THE FOLLOWING MATERIAL LAW/ELEMENT TYPE COMBINATIONS ARE NOT SUPPORTED:
     ELEMENTS OF TYPE BEAM ARE NOT COMPATIBLE WITH MATERIAL ID 2 OF TYPE 93
  ```

  3046 and not 3047: every composite law k2rad emits (LAW93/127/43/27) leaves
  `PROP_BEAM` at the 0 default from `ini_mat_elem.F:89`, which fails the
  MATERIAL/ELEMENT test in `check_mat_elem_prop_compatibility.F` before any
  property is examined — so no property this prepass could synthesize would
  change the outcome, and the warning gives deck-level advice (a beam-capable
  material, or re-mesh as shells) rather than a mesh hint. The `/PROP/BEAM`
  material-compatibility check added in the previous release reports the same
  ERROR 3046 from the property side; the two now agree instead of contradicting
  each other. A `*PART_COMPOSITE` on a beam part whose own material is fine
  reports only the dropped layup, mirroring the solid branch.

  **The genuinely element-free case is unchanged** — its softened mesh-check
  wording is correct and re-measured: the same deck without the beams is
  `NORMAL TERMINATION`, `0 ERROR(S) 0 WARNING(S)`.

- **Stale comment**: the `HANDLERS` table said
  `*MAT_ANISOTROPIC_VISCOPLASTIC (103) → /MAT/LAW36 (isotropic reduction)`. The
  shipped conversion has been `/MAT/LAW128` (HILL_VISC_PLAST) since the LAW128
  work landed — Hill surface, Voce hardening and the viscous term all carried
  over. Comment only; no behaviour change.

- **All three are diagnostics and routing only, no card-format change.** All
  five goldens are byte-identical and the 72-deck local example corpus
  re-converts to the same starter+engine SHA256 as on `master`. 22 new tests
  (1581 → 1603) in a new `tests/test_xref_material_routing.py` plus
  `tests/test_composites.py`; the `/XREF` block the spotweld fallback now keeps
  is asserted column-exact.

- **A `*MAT_NULL` whose only equation of state was an `*EOS_JWL` vanished from
  the deck entirely — no `/MAT` card of that id at all, and every `/PART` on it
  dangling with starter ERROR 179.**

  ```
  ERROR ID :    179
  ** ERROR IN PART DEFINITION (MATERIAL)
     -- PART ID: 1
     MATERIAL ID=2 DOES NOT EXIST
  ```

  Two routing sets disagreed. `_make_materials` suppressed `/MAT/VOID` for any
  `*MAT_NULL` whose id appeared in `state.eos_cards` **or** `state.eos_jwl`, on
  the assumption that an EOS-carrying material would be emitted for it further
  down. But `*EOS_JWL` is stored *only* in `state.eos_jwl` (`handle_eos_jwl`),
  and the `/MAT/LAW6` (`HYD_VISC`) carrier loop in
  `_make_explosive_and_eos_materials` walks `state.eos_cards` alone. So a deck
  with `*MAT_NULL` id N + `*EOS_JWL` id N and no `*MAT_HIGH_EXPLOSIVE_BURN` of
  that id fell through every branch: no `/MAT/VOID` (suppressed), no
  `/MAT/LAW5` (the id is not in `state.mat_high_explosive`), no carrier (the id
  is not in `state.eos_cards`). The only sign was an `*EOS_JWL` warning about
  the missing explosive, which never mentioned that the `*MAT_NULL` had gone
  with it.

  **The null now falls back to `/MAT/VOID` and the warning says so.** The
  suppression set is narrowed to `set(eos_cards) | (set(eos_jwl) &
  set(mat_high_explosive))` in a new shared `_void_null_mids()` helper, so a
  JWL id only claims a null when the explosive that carries it actually exists.
  `*MAT_NULL` + `*EOS_JWL` **cannot** be converted faithfully: OpenRadioss has
  no standalone `/EOS/JWL` — JWL exists only inside `/MAT/LAW5`
  (`mat_EOS.cfg` lists GRUNEISEN, POLYNOMIAL, PUFF, SESAME, TILLOTSON,
  MURNAGHAN, OSBORNE, LSZK, NOBLE-ABEL, STIFF-GAS, IDEAL-GAS, LINEAR,
  COMPACTION, NASG, TABULATED, and no JWL; the keyword is reachable only as
  LAW5/LAW97 in `data_hierarchy.cfg`). Emitting a `/MAT/LAW5` from the null
  instead was rejected: LAW5 needs the detonation velocity `D` and `P_CJ` that
  only `*MAT_HIGH_EXPLOSIVE_BURN` carries, and a LAW5 with `D = 0` never burns
  — a silent zero-pressure explosive is worse than an obvious void. So the
  material stays `/MAT/VOID` (the same fallback a bare `*MAT_NULL` already
  takes, starter-clean on a Lagrangian `/BRICK`: 0 errors), and the warning now
  names what was emitted, what was lost, and what to add:

  ```
  *EOS_JWL 2: no companion *MAT_HIGH_EXPLOSIVE_BURN (same id) — OpenRadioss
  carries JWL only inside the /MAT/LAW5 explosive, so the JWL parameters were
  NOT emitted and the same-id *MAT_NULL fell back to /MAT/VOID/2: that part now
  has NEITHER strength NOR pressure (the detonation-product expansion is lost,
  so it applies no load to its surroundings). Add a *MAT_HIGH_EXPLOSIVE_BURN of
  id 2 (density, detonation velocity D, P_CJ) to get the /MAT/LAW5 JWL
  explosive.
  ```

  Every other route through the block is untouched and verified byte-identical
  against `master`: the intended `*MAT_HIGH_EXPLOSIVE_BURN` + `*EOS_JWL` pair
  still merges into one `/MAT/LAW5`, a `*MAT_NULL` with a same-id
  `*EOS_LINEAR_POLYNOMIAL` still becomes `/MAT/LAW6` + `/EOS/POLYNOMIAL`, a
  `*PART`-`EOSID`-bound null still wins over a same-id JWL, an `*EOS_JWL` with
  no material of its id at all keeps its original wording, and a bare
  `*MAT_NULL` still stays `/MAT/VOID` (all five goldens plus real blast, bogie
  and gear-train decks re-convert to the same SHA256). 6 new tests in
  `tests/test_converter.py` (1563 → 1569); the repro deck now converts and
  runs the starter with 0 errors.

- **A beam part whose material is not one of five Radioss laws converted to a
  deck that ERROR-TERMINATES the starter, and k2rad said nothing at all.**
  `_make_properties` writes a `/PROP/BEAM` (IGTYP 3) for every `*SECTION_BEAM`
  without ever looking at the material, and the classic beam property accepts
  only `PROP_BEAM` 1 or 3 — `/MAT/LAW0`, `LAW1`, `LAW2`, `LAW13`, `LAW44`.
  `*MAT_PIECEWISE_LINEAR_PLASTICITY`, by some distance the most common LS-DYNA
  beam material, routes to `/MAT/LAW36`, so the single likeliest beam deck there
  is was converted straight into an unrunnable one, silently.

  ```
  ERROR ID :   3047
  ** ERROR IN MATERIAL/PROPERTY COMPATIBILITY
     PROPERTY ID 2  OF TYPE 3  IS NOT COMPATIBLE WITH MATERIAL ID 1  OF TYPE 36
  ERROR ID :    745
  ** ERROR IN MATERIAL-PROPERTY COMPATIBILITY
     ON ELEMENT ID=11, PID TYPE 2 IS NOT COMPATIBLE WITH
     MATERIAL LAW 36
  ```

  **The whitelist is transcribed from the starter, not from the manual.**
  The gate is on the MATERIAL: each law declares a class through
  `INIT_MAT_KEYWORD` — 1 `BEAM_CLASSIC` (TYPE3 only), 2 `BEAM_INTEGRATED`
  (TYPE18 only), 3 `BEAM_ALL` (`init_mat_keyword.F:251-258`) — and IGTYP 3
  demands 1 or 3 (`check_mat_elem_prop_compatibility.F:379-381`). Grepping every
  `INIT_MAT_KEYWORD` call under `starter/source/materials/` returns 10 call
  sites, all unconditional, and that is the complete list: LAW1 is BEAM_CLASSIC
  (`hm_read_mat01.F:148`); LAW0 (`mat00:133`), LAW2 in all three of its readers
  (`_jc:381`, `_zerilli:342`, `_predef:392`), LAW13 (`mat13:128`) and LAW44
  (`mat44:319`) are BEAM_ALL; LAW34 (`mat34:162`), LAW36 (`mat36:360`) and LAW71
  (`mat71:251`) are BEAM_INTEGRATED. Every other law keeps the `PROP_BEAM = 0`
  default from `ini_mat_elem.F:89`.

  **The two error ids are not interchangeable, and the split is structural.** A
  law at `PROP_BEAM == 0` fails the ELEMENT test first (`IF
  (MAT_PARAM(IMAT)%PROP_BEAM == 0) COMPAT_ELEM = .FALSE.`, same file
  lines 153-155 / 342-343) and reports **3046** — material-vs-element, the
  property never enters it. Only a law that *is* beam material of the wrong
  class, i.e. BEAM_INTEGRATED LAW34/36/71, passes that and fails the property
  test as **3047**, joined by the legacy hard-coded pair check in
  `initia.F:2806-2817` firing **ERROR 745** once per beam element. The warning
  names whichever id the user will actually read. Measured on `starter_win64`
  (nt=6), one `*SECTION_BEAM` ELFORM=2 and two `*ELEMENT_BEAM` per deck,
  everything else held constant:

  | beam material | law | starter |
  |---|---|---|
  | `*MAT_ELASTIC` | 1 | NORMAL TERMINATION, 0 ERROR(S) 0 WARNING(S) |
  | `*MAT_JOHNSON_COOK` | 2 | 0 ERROR(S) (only unrelated warnings) |
  | `*MAT_PLASTIC_KINEMATIC` | 44 | NORMAL TERMINATION, 0 ERROR(S) 0 WARNING(S) |
  | `*MAT_PIECEWISE_LINEAR_PLASTICITY` | 36 | 3 ERROR(S): 3047 + one 745 per element |
  | `*MAT_BLATZ-KO_RUBBER` | 42 | 1 ERROR(S): 3046 |

  The check resolves the law through the new `_target_mat_law`, which follows
  **k2rad's own routing** rather than the LS-DYNA material number — `*MAT_024`
  and `*MAT_POWER_LAW_PLASTICITY` are different keywords on the same LAW36,
  `*MAT_JOHNSON_COOK` is LAW2 or LAW4 depending on an attached `*EOS_*`,
  `*MAT_NULL` is `/MAT/VOID` alone but the `/MAT/LAW6` carrier with one, and
  each rubber keyword picks its law off a curve or order field. It is the first
  mid → law map in the codebase that covers every material container;
  `inistate.py::_xref_target_law` covers 7 of them and is left alone here.

  **Warn-only, deliberately — no auto-promotion to `/PROP/TYPE18`.** A promotion
  is not information-preserving: `*SECTION_BEAM` ELFORM=2 states four
  independent resultants (A, Iss, Itt, J) while `/PROP/TYPE18` integrates a
  point cloud whose `Ixx` the starter *defines* as `Iyy + Izz`
  (`hm_read_prop18.F:289-301`) — the polar moment, equal to the torsion constant
  only for a circular section — so promoting means inventing a cross-section and
  overwriting the deck's J. It would also rescue only a subset: TYPE18 takes
  LAW34/36/71, but a beam on LAW38/42/50/70/76/95/127/128 has no beam property
  in Radioss at either type and still needs a different material. A warning that
  names the remedy covers every case; a promotion covers a third of them.

  Diagnostics only: no emitted card changes. The `/PROP/BEAM` of a rejected
  LAW36 deck is line-for-line the one a starter-clean LAW44 deck gets, the five
  goldens are byte-identical, and the `*MAT_024` repro deck re-converts to the
  same SHA256 as on `master` — with 0 warnings there and 1 here. 18 new tests in
  a new `tests/test_beam_mat_prop_compat.py` (1563 → 1581, 125 → 143 subtests).

- **An element-free `*PART` produced a `/PART` pointing at a property that was
  never emitted — starter ERROR 178, and the whole conversion dead on a part
  carrying no mesh.**

  ```
  ERROR ID :    178
  ** ERROR IN PART DEFINITION (PROPERTY)
     -- PART ID: 88
     PROPERTY ID=88 DOES NOT EXIST
  ```

  k2rad emits a `/PART` for every `*PART` record and points it at the part's
  SECID when no composite / orthotropic / per-part-hourglass property has
  claimed it. The placeholder sections that back that last case were derived
  from the **elements** naming a secid (`missing_shells` / `missing_solids` /
  `missing_beams` are built from `shell_elems` / `solid_elems` / `beam_elems`),
  so a `*PART` with no elements and no `*SECTION` was reached by none of them.
  Two cards, one meshed part and one empty one, were enough to reproduce it.

  An element-free part is **idiomatic, not a mistake**: `*INTEGRATION_SHELL`'s
  `PID_i` "may reference a part with no elements" (Vol I R17 p.29-17) purely to
  carry a layer material, and an element-free `*MAT_RIGID` part with
  `*CONSTRAINED_EXTRA_NODES` forms a working `/RBODY` from borrowed nodes. So
  the part now **keeps** its id, title, material and subset, and is given the
  same placeholder `/PROP/SHELL` a sectionless *meshed* shell part already got
  (`_auto_section_shell`: ELFORM 2 → `Ishell` 12, `N` 3, zero thickness). It
  has no elements to act on, so it changes no physics — the starter's
  ELEM/PROP/MAT compatibility checks run per element group and this property
  has none. A warning names the parts, because an empty part is usually either
  a material carrier or mesh the user did not realise was missing.

  **Dropping the `/PART` instead was rejected on measurement, not taste.**
  Nothing in k2rad filters set / group / surface members against the parts that
  were actually emitted: `writer/contacts.py` builds an all-parts
  `/SURF/PART/EXT` straight from `state.parts.keys()`, and `writer/loads.py`
  does the same for a `/GRNOD/PART` gravity scope. Hand-stripping `/PART/88`
  from a converted `*LOAD_BODY_PARTS` deck traded ERROR 178 for starter
  **WARNING 194, "REFERENCE TO NONEXISTENT PART ID=88"** — quieter, still a
  broken deck, and the part's material binding gone with it.

  **dyna2rad is deliberately not followed here, because it is broken the same
  way.** The native reader writes the `/PART` with `prop_ID = 0`
  (`convertprops.cxx:110-150` — a SECID of 0 leaves `radPropEdit` invalid and
  the else-branch stores entity id 0), and its own starter then raises the
  *same* ERROR 178, just reporting `PROPERTY ID=0`
  (`hm_read_part.F:203-210`; note `MID = 0` gets a fictitious-material fallback
  a few lines further down, `PID = 0` gets none). There was no correct native
  behaviour to match.

  Validated against the real starter, `0 ERROR(S)` on all three where master
  gives ERROR 178: the bare repro deck, the same deck with the empty part
  inside a `*SET_PART` reaching `/GRNOD/PART` (which also confirms no WARNING
  194 — the reference resolves), and an element-free `*MAT_RIGID` carrier whose
  `/RBODY` still forms. 18 new tests plus a deck-wide invariant — every
  `/PART`'s property column must name a `/PROP` the deck emits — and the five
  golden fixtures stay byte-identical.

- **The `/TH` channel sweep: `REAC*` was not the only integrated channel.
  `/TH/INTER`, `/TH/SECTIO` and `/TH/RWALL` forces are accumulated impulses
  too, and `/TH/SURF` `P`/`A` are per-interval aggregates.** Docs, emitted deck
  comments and four new warnings — every mapping was already correct, and **no
  emitted card changes**.

  A previous entry corrected `/TH/NODE` `REAC*` and explicitly left the rest of
  the `/TH` surface unaudited. This is that audit: every `/TH` variable the
  converter emits, classified against the engine source and cited.

  | `/TH` block | channels | verdict | engine evidence |
  |---|---|---|---|
  | `/TH/NODE` | `REACX/Y/Z`, `REACXX/YY/ZZ` | **accumulated impulse** | `reaction_forces_th.F:62`; **also `bcs1th.F:143-155`** on the `/BCS` path (`*MS*DT12`, and `*IN*DT12` for the rotations); only reset `resol.F:1901`, before loop head `:2612`; written raw `thnod.F:176-178` |
  | `/TH/NODE` | `DX/DY/DZ`, `VX/VY/VZ` | instantaneous | `thnod.F:124-135` |
  | `/TH/INTER`, `/INTER/SUB` | `FNX/Y/Z`, `FTX/Y/Z` | **accumulated impulse** | `i7for3.F:1459-1476` (`+F*DT12`), `:3055-3079`, `:1559-1561`; raw copy `thkin.F:56` |
  | `/TH/SECTIO` | `FNX/Y/Z`, `FTX/Y/Z`, `M1/M2/M3` | **accumulated impulse + angular impulse** | `section_c.F:459-467`, `section_s.F:565-572` (`+DT12*FST`) |
  | `/TH/RWALL` | `FNX/Y/Z`, `FTX/Y/Z` | **accumulated impulse** | `rgwal0.F:504-509` |
  | `/TH/SURF` | `P`, `A` | **per-`/TFILE`-interval aggregate** | `pblast_1.F:418-419`, `hist2.F:688`, `sortie_main.F:1976-1982` |
  | `/TH/SPRING` | `FX..MZ`, `LX..RZ` | instantaneous | `thres.F:355-361` |
  | `/TH/SHEL`, `/TH/SH3N` | `F1/F2/F12`, `M1/M2/M12` | instantaneous | `thcoq.F:305-315` |
  | `/TH/BRIC` | `OFF`, `SX..SXZ`, `DENS`, `TEMP` | instantaneous | `thsol.F:329-336` |
  | all | `IE`, `KE`, `PLAS` | cumulative by nature | — |

  **The `FSAV` family.** `/TH/INTER`, `/TH/SECTIO` and `/TH/RWALL` all read one
  shared engine array, and it is cumulative by design. The engine says so in
  its own comments: `i7for3.F:1443` heads the contact block
  `SAUVEGARDE DE L'IMPULSION NORMALE` ("save the normal impulse"), and
  `sortie_main.F:1945` heads the reset block `TRAITEMENT SUR FSAV NON CUMULE`
  ("handling of the NON-cumulated `FSAV`") — a heading that only makes sense
  because the rest of `FSAV` *is* cumulated. That reset touches only the monvol
  block, `FSAV(26)` (contact elastic energy) and `FSAV(29)` (`CAREA`). The one
  other zeroing, `hist2.F:616-622`, is guarded by `IF (ISPMD/=0)` — it clears
  the *non-master* ranks after their contribution has been summed in, so on
  `np=1` nothing is ever reset. `thkin.F:56` then copies `FSAV` into the T01
  buffer with no division by time.

  `/TH/RWALL` is the sharpest case, because the engine computes the quantity
  the user wants and then does not write it: `rgwal0.F:496-500` forms
  `DIVDT12 = 1/DT12` and `RWL(17..19) = (FXN+FXT)*DIVDT12` — the true wall
  force — but routes it only to `FOPT` (`/ANIM`) and the sensor buffer
  `FBSAV6`, while `:504-509` accumulates the undivided impulses into `FSAV`.
  That is the same `FREAC`-vs-`FTHREAC` split as the reaction channels, one
  array further along.

  **Confirmed on real data.** On a converted `getriebekette` deck the T01
  `/TH/INTER` `FNY` channel climbs monotonically from 0 to 38.7 over the run
  while its derivative is a physically sensible contact force ramping 17 to
  62 N — an instantaneous force channel would oscillate about a value, not
  climb by 38 units.

  **`/TH/SURF` is a different failure, not the same one.** `P` and `A` are
  neither instantaneous nor a running integral. `pblast_1.F:418-419` adds
  `AREA*P` into channel 4 and `AREA` into channel 5 every cycle (into
  `th_surf%channels`, which `resol.F:3447` passes as the `FSAVSURF` dummy — the
  two names are one array), `hist2.F:688` divides channel 4 by channel 5 just
  before the write, and `sortie_main.F:1976-1982` zeroes channels 1-5 after
  every write. So **`P` is the area-weighted mean pressure over the `/TFILE`
  interval** — a blast peak falling between two writes is averaged away — and
  **`A` is the loaded area times the number of cycles in that interval**. The
  old claim that `P*A` is the total blast force was wrong by exactly that cycle
  count. Differentiating an interval aggregate would be meaningless, so
  `tools/th_to_csv.py` leaves `/TH/SURF` alone and prints the caveat instead.

  **A superseded rule of thumb.** `writer/contacts.py` told users the T01
  contact force was "impulse-scaled" and that "x2 recovered the applied load to
  ~1%". The first half was right; the second was a coincidence of one deck at
  one instant. There is no constant factor — the ratio between the raw channel
  and the force is the elapsed accumulation time, which grows with the run. The
  warning now says to differentiate, and says explicitly that no constant
  correction exists.

  **A second reaction-path accumulation site**, not cited before: the `/BCS`
  path `bcs1th.F:143-155` accumulates `MS*DT12` for the translations and
  `IN*DT12` for the rotations, so `REACXX/YY/ZZ` are *angular* impulses
  (moment × time). The `/ANIM` twin in the same file, `bcs1th.F:281-287`, runs
  the identical algebra with **no** `dt` factor. On the implicit path the
  integration is trapezoidal rather than rectangular (`bcs1th_imp.F:46-56`) but
  is still an integral: **no solver path writes an instantaneous `/TH`
  reaction.**

  New: four `state.warn`s (`/TH/INTER`, `/TH/SECTIO`, `/TH/RWALL`, `/TH/SURF`),
  impulse notes in each emitted `/TH` block, corrected docstrings in
  `writer/output.py`, `writer/inistate.py`, `writer/loads.py`,
  `writer/contacts.py`, a corrected `README.md` (with the full sweep table
  under *Reading the T01*) and `docs/BLAST_ALE_JWL_MAPPING.md`. Three existing
  tests that hard-indexed a fixed line offset under a `/TH` title now scan past
  the comment run instead, and the force-transducer test asserts the corrected
  claim.

- **`*BOUNDARY_PRESCRIBED_MOTION_RIGID`: the imposed-motion reaction readout
  now warns that `REAC*` is an accumulated impulse.** Previously only
  `*DATABASE_SPCFORC` warned, on the reasoning that it is the one with a named
  LS-DYNA file to compare against. But the `TH_reaction` block is the one that
  puts `REACX/Y/Z` directly next to `DX/Y/Z` on the same node — the exact shape
  of a force-vs-displacement extraction, and the plot that silently goes wrong
  — and a deck can have imposed motion with no `*DATABASE_SPCFORC` anywhere, so
  it never reached the other warning. The deck comment already said so, but a
  comment inside a `.rad` file is only read by someone who opens the `.rad`
  file; the conversion log is what gets read.

  The new warning gives the recipe, not just the diagnosis: build the curve
  from `numpy.gradient(reac, t)` against `DX/Y/Z`, because the raw channel
  rises monotonically and an untreated `REAC`-vs-`DX` curve has both a
  meaningless slope and a meaningless enclosed area (it is not the work done).

  A deck that triggers **both** paths would otherwise carry the same
  three-sentence derivation twice, so `_warn_reac_impulse` emits the shared
  engine-source explanation once and back-references it the second time. Each
  path always keeps its own actionable sentence — that is the part that
  actually differs — and both variants still contain "impulse", `d(REAC)/dt`
  and `reaction_forces_th.F`, so a grep-style check behaves identically
  whichever fired first.

- **The orphan-element guard now runs AFTER the provisional-element screen in
  `build_starter`.** A screened-out phantom — an all-integer option card from an
  unmodelled `*ELEMENT_SHELL/_BEAM` suffix that imitated connectivity on node
  ids the deck never defines — is an option card, not lost mesh, and must not
  draw a `MESH LOSS` line. `convert()` already screened before `build_starter`
  (so the CLI path never showed the false alarm); this pins the ordering for
  the direct-writer callers `build_starter` supports, as recorded in PR #92's
  merge-order note. Two new tests fail on the old ordering.

- **`*DATABASE_SPCFORC`: the `/TH/NODE` `REAC*` channel was documented as a
  reaction *force*. It is a time-accumulated reaction *impulse*.** Docs,
  emitted deck comments and a new warning only — the mapping was already
  correct (right channel, right nodes) and no emitted card changes.

  The engine never divides by time and never resets the accumulator:

  ```fortran
  ! engine/source/output/reaction_forces_th.F:60-62
  FTHREAC(k,NODREAC(N)) = FTHREAC(k,NODREAC(N)) + IFLAG * MS(N)*A(k,N)*DT12

  ! engine/source/engine/resol.F
  1901   FTHREAC = ZERO      ! the ONLY zeroing in the engine ...
  2612   100 CONTINUE        ! ... and it is BEFORE the iteration loop head
  7304   IFLAG = -1 ; CALL REACTION_FORCES_TH(...)   ! before kinematic conds
  7386   IFLAG = +1 ; CALL REACTION_FORCES_TH(...)   ! after  -> += m(A-A~)*dt
  9294   GOTO 100            ! back edge: no reset in between

  ! engine/source/output/th/thnod.F:178-208
  WA(IJK) = FTHREAC(1,NODREAC(I))            ! written straight out, as-is
  ```

  So `REAC*` sums `m*a*dt` monotonically for the whole run and carries
  force x time units, while LS-DYNA's `spcforc` column is an instantaneous
  force. Plotting one against the other compares an impulse with a force, with
  no error or warning anywhere. Measured on a settled column+block deck of
  total weight **3.850425 N**: `REACY` ramps linearly (0.0735 N*s at t = 0.03
  to 1.1178 N*s at t = 0.30) and the least-squares slope over t >= 0.15 is
  **3.8504181 N — -0.0002% off the analytic weight**. The fix is therefore to
  say so, everywhere, and to tell the reader that `F(t) = d(REAC)/dt`.

  The companion `/ANIM/VECT/FREAC` the same code path emits is *not* affected —
  `reactions.F:328` finalizes `FREAC = MS*A - FREAC` each cycle with no `DT12`
  and no accumulation, so that field really is the instantaneous force. `FREAC`
  and `FTHREAC` are separate arrays with deliberately different semantics; only
  the `/TH` one is integrated. The same correction applies to the
  `*BOUNDARY_PRESCRIBED_MOTION_RIGID` reaction readout
  (`_make_starter_th_node_reac`), whose `REACX/Y/Z` sits next to plain `DX/Y/Z`
  displacement channels — a force-vs-displacement curve has to be built from
  `numpy.gradient(reac, t)`, not from `REAC` directly.

  Pre-existing since PR #41. Changed: the two `writer/output.py` docstrings and
  their emitted `#` comment lines (each block now also carries a one-line
  `REAC* accumulates m*a*dt ... = d(REAC*)/dt` reminder in the `.rad` itself),
  the `handlers.py` handler docstring, the `writer/assembly.py` `/ANIM/VECT/
  FREAC` comment, the README `*DATABASE_*` table, and a new `state.warn` that
  fires on every converted `*DATABASE_SPCFORC` deck.

- **An element whose `PID` no `*PART` defines used to vanish from the converted
  deck without a single word — no warning, no skip line, nothing.** The writer
  emits elements from *inside* the `for pid, part in sorted(state.parts.items())`
  loop of `_make_parts_and_elements` (and the spring/damper connectors the same
  way, from the per-part loops in `writer/loads.py`), so such an element is never
  *reached*: the loop does not visit that id, the element is not written, and
  nothing downstream notices — the starter only ever sees what was written.

  This is the quietest failure mode the converter has. The produced `.rad` is
  valid, the starter accepts it, the engine runs it to NORMAL TERMINATION — and
  it is simply not the model the user drew: lighter, softer, and missing whatever
  contact surface those elements carried. It is exactly what happened to every
  `*PART_COMPOSITE` part before that keyword got a handler (see *Added*, above),
  and the same silence covered every other route to a missing `PID`: an
  `*INCLUDE` that did not resolve, an id typo, a deck assembled from a subset of
  its parts, a `*PART` variant the parser does not recognize yet.

  A read-only prepass now runs **first** in `build_starter`, before any pass
  edits the element stores (the TET10 downgrade and the sliver screening both
  delete solids and announce their own drops), and reports what the `.k` file
  actually contained:

  ```
  MESH LOSS: 5 element(s) reference 3 part id(s) that no *PART card defines,
  and are NOT in the converted deck — PID 77 (2 shell); PID 88 (1 solid, 1
  beam); PID 99 (1 discrete). ...
  ```

  All four element stores are scanned — `shell_elems`, `solid_elems`,
  `beam_elems`, `discrete_elems`. `*ELEMENT_DISCRETE` was the only one that
  already had a guard of its own (`_make_discrete_springs` warns per part); it is
  scanned anyway, so this stays the one place that answers *"did the conversion
  drop any of my mesh?"* even if that emitter is short-circuited or reordered.
  The enumerated part ids are capped at 12 (a missing `*INCLUDE` can orphan
  hundreds; the totals stay exact), and the guard changes no output — every
  golden is byte-identical, asserted again inside
  `tests/test_orphan_elements.py`. 13 new tests (1293 -> 1306).

- **Gravity on a rigid body did nothing at all: a free `*MAT_RIGID` block under
  `*LOAD_BODY_Y` never moved — 526 cycles, every displacement 0, KE = 0.** And
  the same emitter had the `*LOAD_BODY` sign inverted and a `/GRAV` card ten
  columns too short. Three defects, one card.

  **1. The load never reached the rigid body.** `/GRAV` adds an *acceleration*
  to every node of its group, and it does so at a point in the cycle where a
  rigid secondary node can no longer pass anything on:

  ```fortran
  ! engine/source/loads/general/grav/gravit.F:147
  A(N2,N1)=A(N2,N1)+AA                     ! no mass factor: AA is an accel.

  ! engine/source/engine/resol.F  — one cycle, in order
  5502   CALL RBYFOR(...)   ! secondary forces summed INTO the rbody main node
  6690   CALL ACCELE(...)   ! A <- A / M
  6884   CALL GRAVIT(...)   ! A(dir,n) += Fscale_Y*f(t)   <-- 1382 lines too late
  7572   CALL RBYVIT(...)   ! -> rgbodv.F

  ! engine/source/constraints/general/rbody/rgbodv.F:109-155
  A(1,N)= AM1 + (...)                      ! "=", not "+=": the secondary's
  A(2,N)= AM2 + (...)                      !  acceleration is OVERWRITTEN
  A(3,N)= AM3 + (...)                      !  from the main node AM1..AM3
  ```

  So gravity deposited on a rigid secondary node is never summed into the main
  (`RBYFOR` already ran) and is then discarded (`RGBODV` assigns over it). Net
  effect on motion: exactly zero. With `--rigid-cog-master` — the default since
  PR #54 — the `/RBODY` main is a *synthesized element-free node* at the part
  centroid, so a `/GRNOD/PART` can never contain it and the body is left with
  nothing. Measured on a free rigid block: as converted it sat still for the
  whole run; with the main node in the group it free-falls exactly, **DY
  4.727803E-01 mm against the analytic 4.727802E-01**.

  A part that k2rad turned into an `/RBODY` is now **swapped out** of the
  `/GRNOD/PART` and replaced by its main node — what the Radioss dyna-reader
  itself does (`convertloads.cxx:887-902`, via `storeRbodyPIDVsMasterNode`).
  The main carries the summed mass of the whole body (`inirby.F:187-243, 837`),
  so one main node at `g` is the exact load; keeping the secondaries as well
  would change no displacement but would inflate `WFEXT` by
  `Σ m_secondary·g·v·dt` (`gravit.F:148`), because the starter does **not**
  zero secondary masses. A `*CONSTRAINED_NODAL_RIGID_BODY` is different — its
  secondaries are ordinary nodes of *deformable* parts, so the part stays and
  the CNRB main is added on top. The two groups are combined with a
  `/GRNOD/GRNOD` union, which the starter resolves by group id and
  de-duplicates in node order (`hm_lecgrn.F:232-236`, `hm_grogronod.F:179-219`).

  Altair's own starter performs precisely this union — `rpart_grav_check` in
  `starter/source/constraints/general/rbody/rbody_part_modif.F90` appends the
  main node to any `/GRAV` group holding one of its secondaries — but it is
  gated on `npby(21,i) /= 0`, true only for rigid bodies auto-generated from a
  `/PART` with a rigid material. k2rad emits explicit `/RBODY` cards, so it
  never fires on a k2rad deck and k2rad has to do it itself.

  **2. `*LOAD_BODY_{X,Y,Z}` had the sign inverted.** The manual is explicit:
  a base acceleration accelerates the coordinate system, so the inertial loads
  on the model are of opposite sign (Vol I R16 p.33-27), and the manual's own
  `*LOAD_BODY_Z` gravity example — `SF = 0.00981` on a constant `+1.0` curve,
  commented as acting in the negative Z-direction — is annotated *"Positive
  body load acts in the negative direction."* (p.33-28). `Fscale_Y = -SF` now,
  matching `convertloads.cxx:247` and this converter's own
  `*LOAD_GRAVITY_PART` path, which has always negated. The old warning telling
  the user to check the direction and flip `SF` themselves is gone.

  **3. The `/GRAV` data card was ten columns short, and it silently ate the
  sign.** `grav.cfg`'s `FORMAT(radioss51)` card is
  `%10d%10s%10d%10d%10d          %20lg%20lg` — ten literal blanks between
  `grnod_ID` and `Ascale_x`, giving a 100-character line with `Ascale_x` at
  61-80 and `Fscale_Y` at 81-100 (cross-checked against Altair's own
  `RD-E-1602` `SEAT_0000.rad:10907-10910`). k2rad packed the fields with no
  gap, so `Fscale_Y` sat at 71-90. That read back correctly only while the
  rendered number was ≤ 10 characters; at 11 the field boundary cut through it.
  Measured with `starter_win64.exe`:

  | `Fscale_Y` written | starter echo `SCALE_Y` | verdict |
  |---|---|---|
  | `-9810` | `-9810.000000000` | ok (5 chars) |
  | `-0.00980665` | `9.8066500000000E-03` | **sign lost — gravity up** |
  | `-9.810000E-06` | `0.8100000000000` | **sign lost + 8×10⁴ magnitude error** |

  i.e. every mm/ms deck and every `%.6E` value. Signed `Fscale_Y` is now the
  norm on both paths, so this was not optional.

  End-to-end on one deck (3 parts, part 2 `*MAT_RIGID`, a CNRB on part 3's
  nodes, `*LOAD_GRAVITY_PART` ACCEL `0.00980665` on all three), read back from
  the starter's own `GRAVITY LOADS` echo:

  | | before | after |
  |---|---|---|
  | `SCALE_Y` | `9.8066500000000E-03` (up) | `-9.8066500000000E-03` (down) |
  | resolved node list | `1 … 12` | `1 2 3 4 9 10 11 12 13 14` |
  | rigid block (nodes 5-8) | in the group, load discarded | main node **13** loaded |
  | CNRB (nodes 9-12) | no load on the body | main node **14** loaded |
  | starter result | — | 0 errors |

  Also in the same emitter: `*LOAD_BODY_PARTS` now has a handler — its `PSID`
  becomes the part-set scope of every `*LOAD_BODY_*` in the deck (one card per
  deck, last one wins, Vol I R16 p.33-25 and `convertloads.cxx:167-182`);
  previously it fell through to `skipped_keywords` and a deck that scoped
  gravity to one part set silently got **whole-model** gravity. And
  `*LOAD_GRAVITY_PART` with `ACCEL = 0` and no curve now emits nothing instead
  of a `Fscale_Y = 0` card, because `hm_read_grav.F:190` reads a zero back as
  the unit-system factor (`1.0`) — i.e. "no gravity" used to become *unit*
  gravity.

  A deck whose gravity scope holds no rigid body emits **the same `/GRNOD`
  cards, with the same ids, titles and order** as before (verified by diffing a
  full conversion against `master`). The `/GRAV` card itself changes on *every*
  gravity deck — the column layout, plus the `*LOAD_BODY` sign — so "no rigid
  body" does not mean "no re-conversion needed". All five goldens are
  unchanged; they carry no gravity at all.

  **Review round — four more defects in the same card**, three of them older
  than this branch and one introduced by it:

  * **The `/GRNOD` id allocator had no namespace guard, and this branch drew
    enough extra ids to make that fatal.** k2rad re-emits every user
    `*SET_NODE` under its own SID (`/GRNOD/NODE/<nsid>` on the SPC path,
    `_make_extra_groups` for the rest), while the synthesized groups came from
    the unguarded `state.next_id()` — so a deck with a `*SET_NODE` id at or
    above the auto-id base (90001) hands the starter two `/GRNOD` cards with
    the same id and it aborts the **whole deck**: `ERROR ID : 79 ** ERROR:
    DUPLICATE ID / IN NODE GROUP DEFINITION`. The union and mains groups added
    here are 1-2 extra draws per `/GRAV`, which pushed the counter into ids
    that used to be safe: a 3-part deck with `*SET_NODE_LIST 90006` converted
    and ran on `master`, and stopped running on this branch. The gravity groups
    now draw from a new `state.next_grnod_id()` (the guard shape of
    `next_curve_id` / `next_part_id` / `next_prop_id`, a no-op on an ordinary
    deck so no id moves). *The other synthesized `/GRNOD` ids — contacts,
    `/INIVEL`, the `/RBODY` groups — still use `next_id()` and carry the same
    latent hazard; out of scope here.*
  * **`*LOAD_GRAVITY_PART` with a load curve silently dropped `ACCEL`.**
    `fscale = -1.0 if lc > 0 else -accel` — but the manual defines `LC` as the
    "Load curve defining **factor** as a function of time" and `ACCEL` as the
    "Acceleration (will be multiplied by factor from curve)", with Remark 1a
    adding "a constant factor of 1.0 is assumed if LC is not specified"
    (p.33-57). The load is `ACCEL × factor(t)`. Measured: `ACCEL = 9810` on a
    0→1 ramp emitted `Fscale_Y = -1`, a **factor-9810 under-load** on exactly
    the staged-construction ramp the keyword exists for. Now `Fscale_Y =
    -ACCEL` with `fct_IDT = LC` in both forms; a *blank* `ACCEL` beside a curve
    (its own default is 0) is taken as 1.0 — the curve carries the
    acceleration — and the substitution is warned rather than assumed.
  * **`CID` and `LCIDDR` were read off the `*LOAD_BODY` card and thrown away.**
    `CID` is a local system the acceleration is expressed in ("The
    accelerations (LCID) are with respect to CID", p.33-27); a rotated body
    load converted to a **global-axis** `/GRAV` with no warning at all. It now
    becomes the `/GRAV` `skew_ID`, which the engine honours
    (`gravit.F:150-162`: for `ISK > 1` it adds `SKEW(3·N2-2 … 3·N2, ISK)·AA`
    instead of the global axis) — and an unresolvable `CID` falls back to
    global *loudly*, because a `/GRAV` naming a skew that is not emitted is
    `MSGID=137`, a starter **error**. `LCIDDR` (the dynamic-relaxation curve)
    is now warned about, the way `LCDR` on `*LOAD_GRAVITY_PART` always was.
  * **A `*LOAD_BODY_PARTS` scope that nothing consumed left no trace in the
    log** — it has a handler, so it never reached `skipped_keywords` either.
    Now reported through `recognized_not_emitted`.

  Two honesty fixes, no behaviour change: a **scoped** load that covers only
  *part* of a rigid cluster (a CNRB reaching outside the scope, or a
  `*CONSTRAINED_RIGID_BODIES` merge with an unscoped partner) now warns that
  the whole cluster is accelerated at `g` where LS-DYNA gives
  `g·m_scoped/m_cluster` — the converted load is an upper bound, and that
  asymmetry against the "a rigid part outside the scope is not pulled in" rule
  is now stated deliberately rather than left looking like an oversight. And a
  `*CONSTRAINED_NODAL_RIGID_BODY` whose `PID` collides with a `*MAT_RIGID`
  part id is reported: `rbody_info` merges two id namespaces, so the CNRB
  record silently replaced the part's.

  Also here: every `*LOAD_BODY_*` card in a deck now shares **one** group set
  (the scope is deck-global by construction) instead of re-emitting an
  identical `/GRNOD` triple per card, and the `{pid: nodes}` inventory is built
  once per conversion instead of once per gravity group.

  New coverage in `tests/test_gravity.py` (43 tests): sign on both paths,
  column-exact card asserts including the 11-character regression, `ACCEL ×
  curve`, `/RBODY` main routing for `*MAT_RIGID`, CNRB, merged bodies and
  `--no-rigid-cog-master`, `*LOAD_BODY_PARTS` scoping, `CID`/`LCIDDR`,
  the `/GRNOD` id-collision guard (and that it does not shift ids without a
  colliding set), shared groups across three body loads, and the partial-scope
  and PID-collision warnings.

  *Provenance:* every LS-DYNA manual quote and every OpenRadioss
  starter/engine/cfg citation above was verified against the files on disk. The
  `convertloads.cxx` line citations are to Altair's dyna2rad source, which is
  **not** part of this repository — but the behaviour they assert was confirmed
  the way that actually matters, by reading the same `.k` files straight into
  `starter_win64.exe` (which goes through dyna2rad) and comparing its own
  `GRAVITY LOADS` echo against k2rad's:

  | card | dyna2rad, native `.k` | k2rad |
  |---|---|---|
  | `*LOAD_BODY_Y SF=+9810` | `SCALE_Y = -9810` | `SCALE_Y = -9810` |
  | `*LOAD_BODY_Y SF=-9810` | `SCALE_Y = +9810` | `SCALE_Y = +9810` |
  | `*LOAD_GRAVITY_PART 1 2 1 9810` on a `*MAT_RIGID` part | `SCALE_Y = -9810`, curve 1, group = `{213}` | identical |

  The last row is the whole PR in one line: the sign, `ACCEL` surviving
  alongside the curve, and the rigid part represented by its main node alone —
  all three matching Altair's own reader exactly.

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
