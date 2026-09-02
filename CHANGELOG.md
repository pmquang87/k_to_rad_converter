# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Prior history (before this changelog was introduced) is summarized in the
`git log` — each keyword conversion and bug fix landed as its own commit / PR.

## [Unreleased]

### Added

- **THERMAL SOLVER batch — the three heat-source boundaries, the two engine
  thermal keywords and the richer thermal materials, closing the deferred
  registry the RARE MATERIALS batch left behind.** Six engine-source verdicts
  drove the scope, and five of them CORRECT a claim the old registry texts made.

  - **`*BOUNDARY_FLUX_{SEGMENT,SET}` → `/IMPFLUX`, with the SIGN INVERTED.**
    Vol I R17 p.5-49 Remark 1 verbatim: *"The segment normal has no bearing on
    the flux. A negative flux transfers energy INTO the volume; a positive flux
    transfers energy OUT of the volume."* `fixflux.F:165-172` adds
    `+AREA·FLUX_DENS·DT1N` to the nodal heat and `tempur.F:51` turns that into a
    temperature RISE, so `Fscale_y = −MLC`. MEASURED on converter output, a 1 mm
    brick over 1.00012284e-3 s: `MLC = −70000` gave
    `IMPOSED FLUX_DENSITY HEAT = +70.008599 mJ` against `q″·A·t = 70.0086`, and
    the `MLC = +70000` twin gave `−70.008599`. Shipping this unflipped would
    have inverted every flux boundary in every deck at 0 starter diagnostics.
    `MLC1..MLC4` are PER-NODE weights that `/IMPFLUX` cannot express (it splits
    the segment evenly, `fixflux.F:167`), so unequal ones refuse the record;
    `LCID < 0` (flux vs temperature) and `NHISV > 0` (`usrflux`) likewise.
  - **`*BOUNDARY_CONVECTION_{SEGMENT,SET}` → `/CONVEC`, with NO sign change.**
    LS-DYNA writes the flux out of the surface, `q″ = h(T_s − T_∞)` (p.5-32
    Remark 1); `convec.F:152` writes the heat in, `AREA·H·(T_INF − TE)·dt`. The
    two expressions mirror, so `HMULT → H` maps 1:1 positive. MEASURED: `h =
    100` on all six faces of the brick gave `CONVECTION HEAT = 387.00946 mJ`
    against a lumped `387.005245` (+0.0011 %). A curve on `HLCID` is
    inexpressible — `H` is a raw scalar (`hm_read_convec.F:165`) and the card's
    one function slot already carries `T_∞` — and is a named drop rather than a
    flattened coefficient the deck never states.
  - **`*BOUNDARY_RADIATION_{SEGMENT,SET}` TYPE 1 → `/RADIATION`, with
    `E = FMULT / σ_deck`.** This is the highest-risk cell in the batch: LS-DYNA's
    `FMULT` is *"the radiation heat transfer coefficient, f = σεF"* (p.5-117
    Remark 1) with the Stefan-Boltzmann constant ALREADY IN IT, while Radioss's
    `E` is a bare emissivity and `hm_read_radiation.F:140-142/174` computes
    `SIGMA = STEFBOLTZ·FAC_T³/FAC_M` itself from the `/BEGIN` unit line. Writing
    `FMULT` through would over-scale radiation by 1/σ — a factor 1.76e10 on a
    Mg-mm-s deck, invisible to the starter. MEASURED: `FMULT = 5.6704e-11`
    (ε = 1), `T_∞ = 1000`, `T_0 = 300` gave `RADIATION HEAT = 0.056251513 mJ`
    against a closed-form `0.056251607` (−0.0002 %); with the SI σ the same deck
    would have stored 56.25 mJ. `σ_deck` is derived from the emitted `/BEGIN`
    WORK line per `unit_code.F:99-151` (`5.6704e-11` for Mg-mm-s), which Vol I
    R17 p.12-567's hot-stamping example confirms independently
    (`sbc = 5.67e-11`). A de-scaled `E` outside (0, 1] refuses the card with both
    numbers rather than emitting a physically impossible emissivity.
  - **An OpenRadioss defect worked around without an engine patch.**
    `radiation.F:249` places `T_INF = FCY*T_INF` OUTSIDE the cache guard it
    opens at `:239`, so under `/PARITH/ON` (the default) a multi-segment card
    with `Fscale_y ≠ 1` re-applies the ordinate scale ONCE PER SEGMENT and
    reaches NaN within a few cycles; `convec.F:241` has the identical line
    INSIDE its guard and is immune. Four-run isolation: 6 segments + FSCALE 1000
    + P/ON → NaN; T_∞ in the curve with FSCALE 1 → 0.33750793 (correct); P/OFF →
    0.33750793; 1 segment → correct either way. k2rad therefore bakes `T_∞` into
    the `/FUNCT` and writes `Fscale_y = 1.0`.
  - **`*CONTROL_SOLUTION` SOLN=1 → the engine card `/DT/THERM`.** The old
    warning said *"Radioss has no thermal-only run mode"*; that was FALSE.
    `freform.F:950-951` sets `IDT_THERM = 1`, `resol.F:1738`'s
    `BCSDTTH_COPY(...,1)` then writes `ICODT = ICODR = 7` on EVERY node
    (restored at `:9167`), `resol.F:5807-5809` replaces the mechanical step with
    the conduction one, and `lectur.F:696-698` prints `THERMAL ANALYSIS ONLY`.
    Refused together with `--ams` (`freform.F:1327-1330` is a hard
    `ANCMSG(301)` + `ARRET(0)`), and refused on a deck that arms no thermal
    solve. Two traps are guarded, both MEASURED under NORMAL TERMINATION with
    0 ERROR / 0 WARNING: (1) an `ENDTIM` not larger than one thermal step does
    exactly ONE cycle at `DT1 = 0` and stores ZERO heat
    (`resol.F:5870-5880` clamps the step to the remaining time) — the LS-DYNA
    `ENDTIM` was written for the mechanical time scale; (2) the step is a
    CONDUCTION stability limit only, so a stiff surface load diverges — the same
    brick at `ENDTIM = 0.2 s` reached `HEAT STORED = 7 901 590 mJ` where the
    physical saturation is `2527.7`, a factor 3126. The guard estimates the step
    as `0.9·0.5·Lc²·RHO0_CP/k` from the emitted `/HEAT/MAT` and the model's
    shortest element edge (it matched the engine's own `0.3611E-01` to four
    figures) and prescribes a scale factor — `0.225` on that deck, verified to
    give `2527.6994` against an analytic `2527.7000`.
  - **`*CONTROL_THERMAL_SOLVER` TSF → the engine card `/THERM`, FWORK →
    `/HEAT/MAT` EFRAC.** `/THERM` (`frethermal.F:64-70`) carries exactly one
    cell, `THEACCFACT`, which multiplies the conductivity (`dttherm.F90:114`) and
    the time argument of every thermal source — term for term LS-DYNA's Thermal
    Speedup Factor (p.12-576). MEASURED as a with/without TWIN, so the card's
    CONSUMPTION is proven and not just its emission (#118): the `/CONVEC`
    coupon with `TSF = 10` stored `2048.0415 mJ` against a hand-computed
    `2047.947` (τ/10, +0.005 %) where the same deck without the card stores
    `387.00946` — a factor 5.29 — and the starter echoes
    `FACTOR TO SPEED-UP THERMAL ANALYSIS = 10.00000`.
    `FWORK` and `EFRAC` are both *"the fraction of
    mechanical work converted into heat"* and both turn a stated 0 into 1.0
    (echoed by the starter as `FRACTION OF STRAIN ENERGY CONVERTED INTO HEAT`).
    The
    card's other 15 cells are named per-field drops, `EQHEAT ≠ 1` is called out
    as a unit inconsistency the converted deck cannot carry, and `SBC` becomes a
    CROSS-CHECK against the σ `/BEGIN` implies — a mismatch there would put
    every converted `/RADIATION` emissivity off by the same ratio.
  - **`*MAT_THERMAL_ISOTROPIC_TD[_LC]` → `/HEAT/MAT` by a least-squares LINE.**
    The registry text this replaces called `/HEAT/MAT`'s conductivity *"the
    linear AS + BS*T only"*, and for the HEAT FLOW that is exactly right: every
    Lagrangian conduction operator reads `AS`/`BS` (`PM(75)`/`PM(76)`) and
    nothing else — twelve of them: `stherm.F:82-83/106`, `s8etherm.F:86/110`,
    `s4therm.F:67/84`, `s4therm-itet1.F:118/135`, `s10therm.F:61/81`,
    `s20therm.F:60/79`, `sctherm.F:94`, `s6ctherm.F:95`, `thermc.F:62/69`,
    `therm3c.F:62/72`, `cbatherm.F:61/67`, `pforc3.F:379-380/382`, all of them
    `KC = (AS + BS*T_element)`. The two-segment `below/above T1` form does exist
    — in the thermal TIME-STEP routines (`dttherm.F90:102-106`,
    `mqviscb.F:653-657`) and in the ALE / SPH / `/INTER/TYPE9` / rigid-wall
    paths (`atherm.F:137`, `forintp.F:336/350`, `i9grd2.F:140`,
    `rgwat2.F:176`), none of which this converter emits. So the deck's table is
    fitted with ONE line, whose worst
    deviation the warning states, and that line is MIRRORED into `AL`/`BL` — not
    as a second segment but so a `/DT/THERM` run above `T1` keeps a sane
    stability step and interface conductance. `T1` itself is carried from the
    mechanical law unchanged, because `/HEAT/MAT` OVERWRITES
    `MAT_PARAM%THERM%TMELT` and that is what `mmain.F90:790` divides by for the
    Johnson-Cook `T*`. The real loss is `RHO0_CP`, which is ONE constant with no
    temperature dependence at any cfg version, so a capacity varying by more
    than 2× refuses the card instead of averaging it into a different material.
    `_TD_LC`'s `HCLC`/`TCLC` curves are sampled in the WRITER prepass, not at
    parse time — a `*DEFINE_CURVE` may follow the material.
  - **`*MAT_THERMAL_ORTHOTROPIC` → `/HEAT/MAT` when `K1 = K2 = K3`.** That is an
    isotropic card written on the orthotropic keyword and converts exactly (AOPT
    and the material-axis cards are then provably inert). Three different
    conductivities are a named drop that prints all three and their ratio, rather
    than picking `K1` or inventing an average.
  - **The eight `*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_{BEAM,SHELL,SOLID,
    TSHELL}` spellings → `/IMPTEMP` over the elements' own nodes.** The `_OPTION`
    suffix is MANDATORY on both keywords (Vol I R17 p.33-162 lists
    `CONSTANT_ELEMENT_OPTION` and `VARIABLE_ELEMENT_OPTION`), so the bare
    spellings the registry carried were eight DEAD entries — a real deck writes
    `*LOAD_THERMAL_CONSTANT_ELEMENT_SHELL` and that reached the
    unrecognized-keyword list. The card is element-centric (*"a uniform element
    temperature"*, p.33-168) and `/IMPTEMP` is nodal (`fixtemp.F:196-205`), so the
    element → node expansion is emitted only when the resulting map is
    single-valued; a node claimed by two elements at two temperatures drops the
    whole card by name rather than letting the last writer fabricate a field.
    Element ids are looked up PER FAMILY, never over a union registry.
  - **Full spelling coverage.** `_SEGMENT` was missing from all three boundary
    families (a probe deck carrying `*BOUNDARY_FLUX_SEGMENT` came out under
    *"Skipped (unsupported) keywords"* on master), and so were the nine
    `*BOUNDARY_RADIATION_*_VF_*`/`_ENCLOSURE` spellings,
    `*BOUNDARY_FLUX_TRAJECTORY`, `*CONTROL_THERMAL_{FORMING,EIGENVALUE}`,
    `*LOAD_THERMAL_VARIABLE_{BEAM,SHELL}_SET` and the numeric material aliases
    `*MAT_T01/T02/T03/T10`. Every one either converts or carries a named drop
    with its reason; none is silently unrecognized.
  - **Output + gating.** `_thermal_solve_active` now accepts a `/CONVEC`,
    `/RADIATION` or `/IMPFLUX` as the temperature-moving card, so a deck with no
    `/IMPTEMP` at all still arms `/ANIM/NODA/TEMP` and the `/TH/NODE TEMP` group
    — which now covers the boundary segments' nodes, because a `/CONVEC`-only
    deck has no driven nodes to cover. MEASURED that those three really do move
    the temperature on their own: `/HEAT/MAT` + `/CONVEC`, every node in
    `/BCS 111 111`, no engine card, ran 7011 cycles and stored 68.120647 mJ,
    against 7.4e-32 for the twin with the `/CONVEC` removed. **Nothing new is
    wired on the `/TH` side**: `hm_read_thgrou.F:1255` gives `/TH/SURF` exactly
    `AREA, MASSFLOW, VELOCITY, P, A, MASS`, and no thermal-load `/TH` family
    exists — there is not even a legal-but-zero channel to be tempted by (#122).
    The whole-model heat balance is `thermbilan.F:71-76` in the engine `.out`,
    which is the independent checker every number above was read from.
  - Corpus reach, stated with its SCOPE, and re-measured line by line over the
    whole of each root (the pattern covers the batch's keywords AND the
    pre-existing thermal ones — `*MAT_ADD_THERMAL_EXPANSION`,
    `*INITIAL_TEMPERATURE`, `*BOUNDARY_TEMPERATURE`, `*CONTROL_SOLUTION`):

    | root | files | lines | occurrences | carrier files |
    |---|---|---|---|---|
    | `C:\openradioss_run` | 509 | 39.37 M | **0** | 0 |
    | `E:\foxcore_data` | 36 | 24.58 M | **0** | 0 |
    | `dynaexamples_r14_ton-mm-s` | 356 | 13.66 M | **148** | **34** |

    So it is zero on the project's own corpus and NOT zero everywhere: the
    LS-DYNA official examples tree is where the batch's third-party regression
    carriers live (28 × `*CONTROL_SOLUTION`, 23 × `*MAT_THERMAL_ISOTROPIC`,
    18 × `*CONTROL_THERMAL_SOLVER`, 8 × `*BOUNDARY_RADIATION_SET`, 6 ×
    `*BOUNDARY_CONVECTION_SET`, 2 × `*BOUNDARY_FLUX_SET`, …). The two-half
    sweep — output files AND `state.warnings` + `skipped_keywords` +
    `recognized_not_emitted`, stated separately per the #129 rule — is
    therefore reported per roster rather than as one number. All PHYSICS
    validation is synthetic, as with the viscoelastic and adhesive batches.

### Fixed

- **`/HEAT/MAT` wrote `AL = BL = 0.0` beside a real `T1`.** Above `T1` the
  thermal STABILITY STEP then becomes `DTFACTHERM·0.5·Lc²·ρCp/max(0, 1e-20)`
  and the element's interface conductance `CONDE` collapses to zero
  (`dttherm.F90:105/116`, `mqviscb.F:654/669`). Both routines are gated on
  `IDT_THERM == 1`, so this bites a thermal-only (`/DT/THERM`) run, where it can
  jump the whole run in one step; the heat FLOW itself never reads those cells
  (`stherm.F:106` and its siblings are `AS + BS·T`). `AS`/`BS` are now mirrored
  into `AL`/`BL`.
- **`*CONTROL_SOLUTION` SOLN=1's warning asserted something false.** It said
  *"Radioss has no thermal-only run mode; the structural degrees of freedom stay
  live"*. `/DT/THERM` is exactly that run mode and freezes every one of them
  (`resol.F:1738`). Corrected, and the same claim removed from
  `writer/thermal.py`'s `mat_ID = 0` warning.
- **Three registry texts named a Radioss card that does not exist.**
  `*CONTROL_THERMAL_TIMESTEP`'s target was `/DTTHERM`: `dttherm.F90` is a
  SUBROUTINE, and the engine's keyword table (`freform.F:213-232`) has `'DT '`
  and `'THERM'` and nothing else. `*CONTROL_THERMAL_{SOLVER,NONLINEAR}` named
  *"the /THERM engine controls"* and *"the /THERM nonlinear controls"*: `/THERM`
  exists but carries exactly ONE cell, and there is no nonlinear-control family
  because there is no nonlinear solve. All three rewritten, and both surviving
  drops now name every field on their card (all eight of `_TIMESTEP`, all seven
  of `_NONLINEAR` — the old text named three).

- **THERMAL SOLVER post-review round — two card-losing defects and ten accuracy
  fixes, found by re-checking the verification round's own cited facts against
  the manual and the engine source, and by five solver runs.** The round's
  central lesson repeated one layer down: a guard that reads a field the deck
  never wrote, and a comment whose mechanism was never checked.

  - **MAJOR: a TRIANGULAR `*BOUNDARY_FLUX` record was refused, and the whole
    flux boundary lost.** `_resolve_flux` compared all FOUR `MLC` cells no
    matter how many nodes `_bc_segments` had already decided the segment has.
    Vol I R17 p.5-48 defines `MLCk` as *"curve multiplier at node Nk"* and
    p.5-47's Card 2 defaults every one to `0.`, so on `N1 N2 N3` — a trailing
    blank, or the `N4 = N3` spelling of p.43-63 — `MLC4` is blank BY
    CONSTRUCTION and the spread was always the full multiplier. MEASURED before
    the fix: `5 6 7` with `MLC1..MLC3 = −70000` emitted ZERO `/IMPFLUX` and told
    the reader to *"give all four the same multiplier"* on a segment this
    converter itself had read as three-noded — the #125 class, and internally
    inconsistent with `test_a_trailing_zero_makes_a_triangle`. Only `mlcs[:n]`
    is compared now, `n` from the WIDEST resolved segment (so a mixed quad/tri
    set still compares four), and a stated multiplier beyond `n` is NAMED as
    ignored rather than swallowed. SOLVER-VALIDATED: the two-triangle deck
    stores `IMPOSED FLUX_DENSITY HEAT = 70.008599 mJ = HEAT STORED` over 7011
    cycles at 0 ERROR / 0 WARNING / NORMAL TERMINATION — digit-for-digit its
    quad twin, and `q″·A·t = 70.0086`.
  - **MAJOR: a stated `TYPE = 0` on `*BOUNDARY_RADIATION_{SET,SEGMENT}` dropped
    the record with a FALSE reason.** p.5-122 (`SSID TYPE _ _ _ _ PSEROD`) and
    p.5-117 (`N1 N2 N3 N4 TYPE`) both print TYPE with **Default 1** and list
    exactly one value, *"EQ.1: Radiation to environment"*. `TYPE = 2`
    (*"Radiation within an enclosure"*) and page 5-126 belong to the SEPARATE
    `_VF` / `_ENCLOSURE` keywords, which k2rad refuses under their own names —
    so on these two spellings enclosure radiation is not even expressible. A
    `0` typed into a defaulted fixed-width integer column, the ordinary way to
    write "use the default", lost a fully convertible boundary while the log
    asserted a value the deck never wrote (#130). It now takes the Default row,
    the way `_efrac` applies p.12-575's `EQ.0.0` rule to FWORK; any other value
    quotes what the deck ACTUALLY stated and cites the card's OWN page. The
    refusal is also a per-RECORD `state.warn` now rather than a keyword-scoped
    `recognized_not_emitted` entry — MEASURED on a two-record probe, that
    listed `BOUNDARY_RADIATION_SET` as unemitted while a `/RADIATION` built
    from its sibling record was in the `.rad`.
  - **The implicit exclusion's MECHANISM, found at source.** The code comment
    said convec / radiation / fixflux / fixtemp are *"called from the EXPLICIT
    loop in resol.F and never from imp_solv"*, and that is measurably false:
    `resol.F:1802/2994/3006/3025` carry NO `IMPL_S` test at all, unlike their
    immediate neighbours at `:2869` (NCONLD), `:2898` (NFXVEL), `:2916`
    (NLOADP_F) and `:2937` (PBLAST). What is dead is the ACCUMULATION —
    `resol.F:6547`, inside `IF (IMPL_S == 1)`, is a `GOTO 111` to the label at
    `:7949`, which skips the `IF (ILAG + IALE + IEULER /= 0)` block opened at
    `:6552` in which the one and only `CALL TEMPUR` sits (`:6736`), and
    `tempur.F:51-58` is the whole integrator (`TEMP += FTHE/MCP`) and the only
    writer of `HEAT_STORED`. MEASURED on a fresh twin: the same converted flux
    brick reports `IMPOSED FLUX_DENSITY HEAT = 70.000000` with
    `HEAT STORED = 0.0000000` over 11 implicit cycles, against
    `70.008599 = 70.008599` over 7011 explicit ones. So the boundary cards ARE
    emitted on an implicit deck, ARE read, and their source counters DO
    advance; the warnings now say that, because a reader who stops at the first
    line of `** THERMAL ANALYSIS **` sees a perfectly plausible number.
  - **The `/DT/THERM` surface-rate guard prescribed a factor that leaves the
    run stable but OSCILLATING.** `τ = RHO0_CP·Lc/h` is the constant of a node
    fed by ONE loaded face per element; a body a few elements thick and loaded
    on several sides runs faster than that by
    `r = max(loaded segments per node / elements per node)`, which
    `_surface_load_concentration` now counts from the emitted deck. Both the
    trip point and the prescription are divided by `r`, so an ordinary thick
    mesh (`r = 1`) keeps exactly the arithmetic that shipped. SOLVER-VALIDATED
    on a six-face 1 mm coupon (`r = 3`), three runs, all NORMAL TERMINATION at
    0 ERROR / 0 WARNING:

    | `/DT/THERM` | cycles | nodal temperature | `HEAT STORED` |
    |---|---|---|---|
    | default 0.9 | 6 | diverges | 7 901 590.2 |
    | 0.225 (the old prescription) | 23 | 300 → **1350.0** → 825 → 1087.5 … | 2527.6994 |
    | 0.075 (`r`-scaled) | 67 | 300 → 650 → 825 → 912.5 → 956.25 … | 2527.7000 |

    The middle row is the point: stable, saturating at the right total heat to
    seven figures, and its first step 350 K PAST the environment temperature —
    so the *"confirm the heat balance is physical"* the message used to
    prescribe cannot see the overshoot. It now says to read the TEMPERATURE
    HISTORY as well. The predicted step change `2·r·dt/τ·(T_∞ − T)` is 1050 K
    and 350 K, which the engine reproduced exactly.
  - Also fixed: the no-`/HEAT/MAT` boundary message prescribed *"Add
    `*MAT_THERMAL_ISOTROPIC` + `*PART` TMID"* on a deck that HAS one, naming a
    spelling k2rad does not parse (`_resolve_heat_materials`' own unparsed arm
    cannot fire on that shape — its `wanted` set is built from parts whose TMID
    RESOLVES); the `--ams` screen for `/DT/THERM` gated on `options.ams` alone
    while `/DT/AMS` and the starter `/AMS` need `*CONTROL_TIMESTEP` with
    `DT2MS < 0`, so a SOLN=1 deck with no timestep card lost its `/DT/THERM`
    under a message saying *"`/DT/AMS` is kept"* on a deck carrying none (one
    shared non-mutating predicate, `_ams_is_emitted`, now serves all three call
    sites); a blank `TMULT` beside a `TLCID` was resolved to 1.0 SILENTLY on
    `/RADIATION` while the identical substitution is named on `/CONVEC`
    (p.5-123/p.5-118 give it the same printed default of `0.` and
    `hm_read_radiation.F:137` the same `FCY_DIM` clamp — and `T_∞` enters
    `radiation.F:155` to the FOURTH power); and `*CONTROL_SOLUTION` named
    `LCINT = 100` and `NCDCF = 1` as dropped inputs when p.12-532 gives exactly
    those as the Default row.
  - **29 thermal spellings still fell into the generic skipped-keyword list.**
    The `*MAT_T##` aliases are now GENERATED from one table (Vol II R17 p.2-9,
    re-read spelling by spelling: T01-T10, T11-T15 as five aliases of one card,
    no T16, T17 and T18), so an alias can never be less well diagnosed than the
    name it aliases — `*MAT_T07` was silent while its exact synonym
    `*MAT_THERMAL_CWM`, registered two screens away, got a named drop. The
    eight remaining `*MAT_THERMAL_*` families and the seven
    `*BOUNDARY_{TEMPERATURE,THERMAL}_*` thermal spellings get named rows of
    their own, and `_thermal_deferred` keys its entry on the spelling the DECK
    wrote rather than on the canonical name.
  - **Two stale comments stated the OPPOSITE of the engine.** `_emit_heat_mat`'s
    docstring and the `_TD_CP_SPREAD_LIMIT` comment claimed `AL = BL = 0` gives
    *"every node above T1 k = 0 EXACTLY"* and *"silently insulates the hot
    region"*. Twelve conduction operators read `AS + BS·T` unconditionally and
    never look at `AL`/`BL`/`TMELT`; what a zero second segment breaks is the
    `/DT/THERM` step and `CONDE`, which is what the CHANGELOG and the shipped
    warning already said. The companion `_fit_td_conductivity` claim that the
    two-segment form exists ONLY in `IDT_THERM`-gated time-step routines was
    over-narrow on both halves: it also lives in the ALE (`atherm.F:137`), SPH
    (`forintp.F:336/350`), `/INTER/TYPE9` (`i9grd2.F:140`, `i9grd3.F:164`) and
    rigid-wall (`rgwat2.F:176`, `rgwat3.F:213`) paths, and `mqviscb.F:282/:592`,
    `mqvisc8.F:170` and `mdtsph.F:142` gate on `JTHE > 0` alone. The POLICY is
    unaffected and better supported than it was argued.
  - Four drifting source citations re-anchored against the checked-in tree
    (`stherm.F:104` → `:106`, `pforc3.F:379` → `:382`,
    `freform.F:1327-1331` → `:1327-1330`, `mqviscb.F:651-656` → `:653-657`),
    and the engine `KEY0` keyword table — quoted as `:214-231`, `:214-236` and
    `:214-250` in three different places — settled on `freform.F:213-232`,
    which is where the `DATA KEY0/` block actually begins and ends.
  - **The `/CONVEC` blocker's numbers are now ones this repo can reproduce.**
    The shipped warning quoted `1389.1850 / 1425.3912 / 2381.4601`, measured on
    a deck the round did not keep. Re-anchored on a twin that IS described in
    full — a 1 mm brick, `RHO0_CP = 3.611`, its six faces split 3 + 3 between
    two `*BOUNDARY_CONVECTION_SET` records sharing TLCID 900 (constant 1000) at
    TMULT 1.0 and 2.0, h = 100, ENDTIM 2.4e-3, four runs of 16 823 cycles at
    0 ERROR / 0 WARNING / NORMAL TERMINATION:

    | deck | `nt=1` | `nt=6` |
    |---|---|---|
    | this converter's output | **1425.0461** | **1425.0461** |
    | the same physics on ONE shared curve at `Fscale_y` 1.0 and 2.0 | **831.27686** | **854.63629** |

    `CONVECTION HEAT` in mJ against a lumped closed form of 1425.7
    (`T_eq = 1500 K`, `tau = 6.0183e-3 s`), i.e. −0.05 % on the fixed column.
    The unfixed column is wrong AND not reproducible across thread counts,
    which is the defect stated as plainly as it can be — and the mechanism was
    re-read at source first (`convec.F:127` carries `.OR. FCY_OLD /= FCY` and
    assigns `FCY_OLD` at `:138`; `convec.F:234` has neither).

- **THERMAL SOLVER verification round — one blocker, five majors and six minors,
  found by re-checking the batch's own cited facts against the engine source and
  by twin measurements on converted decks.** Three of the batch's own claims
  turned out to be false, and one of them had shipped as a fix's rationale.

  - **BLOCKER: `/CONVEC` wrote `TMULT` to `Fscale_y`, which the engine's DEFAULT
    parallel mode reads WRONG.** `convec.F:234`'s `/PARITH/ON` cache key is
    `IF(IFUNC_OLD /= IFUNC .OR. TS_OLD /= TS)` — `FCY_OLD` is missing from it,
    while the `/PARITH/OFF` branch at `convec.F:127` has
    `.OR. FCY_OLD /= FCY` — so two `/CONVEC` cards sharing ONE `T_∞` curve at
    different scales silently reuse the FIRST card's `T_∞`, and the cache is
    per OMP THREAD, so the answer depends on the thread count. MEASURED on
    converter output (1 mm brick, `ρCp = 3.611`, two `*BOUNDARY_CONVECTION_SET`
    records both on TLCID 900 at TMULT 1.0 and 2.0, h = 100, six faces):
    branch-HEAD deck gives `CONVECTION HEAT = 1389.1850 mJ` at `nt=1` and
    `1425.3912` at `nt=6`; the fixed deck gives `2381.4601` at BOTH, against a
    closed form of `2381.4170` (+0.0018 %). Every run reported 16 823 cycles at
    0 ERROR / 0 WARNING / NORMAL TERMINATION. `TMULT` is now BAKED into a copy
    of the curve with `Fscale_y = 1.0` — the treatment `/RADIATION` already got
    for the sibling COMPOUNDING defect at `radiation.F:249` — and the batch's
    claim that *"convec.F:241 puts the identical multiply INSIDE its guard and
    is immune"* is corrected: the multiply's POSITION is not the whole hazard.
    `/IMPFLUX` (`fixflux.F:278-288` caches the unscaled density) and `/IMPTEMP`
    (`fixtemp.F:180-199`, per entry, no cache) are genuinely immune.
  - **MAJOR: `*MAT_T10` was read with the wrong card layout, losing the whole
    thermal material.** Vol II R17 p.2-9 and the card's own header on p.3-37
    give `*MAT_T10` = `*MAT_THERMAL_ISOTROPIC_TD_LC`, but the handler keyed the
    layout on `kw.endswith("_TD_LC")`, so card 2's `HCLC TCLC HCHSV TCHSV TGHSV`
    was read as the T1..T8 temperature row and cards 3-4 (which do not exist) as
    the C/K rows. The `*INCLUDE_TRANSFORM` offset walker had ALWAYS treated
    `MAT_T10` as `_TD_LC` — two readers of one card disagreeing, the #132 class.
    Messages now name the deck's own spelling with the canonical one beside it.
  - **MAJOR: a BLANK `FWORK` is 1.0, not "off".** p.12-573's Card 1 Default row
    prints `1.` under FWORK, so LS-DYNA reads a blank cell as full conversion.
    The gate on "was the cell physically typed" gave the same card two different
    physics depending on whitespace, on exactly the coupled thermo-mechanical
    deck the keyword exists for. The card's PRESENCE is now the test. The
    warning also states what actually CONSUMES `EFRAC`, which is not the same
    quantity on the two sides: Radioss scales the element's TOTAL
    internal-energy increment (elastic included) for every law with
    `HEAT_FLAG = 0` — `mmain.F90:2035-2037` for solids, `cmain3.F:360` for
    shells of law < 28 or law 32, `pforc3.F:321` for beams — and only LAW2
    shells scale real plastic work (`sigeps02c.F:223`).
  - **MAJOR: `*LOAD_THERMAL_*` is a STRUCTURAL-ONLY load and is now dropped on a
    thermal deck.** Vol I R17 p.33-162, the family's own head page: its nodal
    temperatures *"are all applied in a structural only analysis. They are
    ignored in a thermal only or coupled thermal/structural analysis"*. Emitting
    them as `/IMPTEMP` on a `*CONTROL_SOLUTION` SOLN=1/2 deck put a HARD
    Dirichlet reset (`fixtemp.F:180-199`, every cycle) on top of the very solve
    the deck asks for — a composition that only became possible when this batch
    added the heat sources. `*BOUNDARY_TEMPERATURE` and `*INITIAL_TEMPERATURE`
    are untouched, because p.33-162 scopes its sentence to
    `*LOAD_THERMAL_OPTION` alone. The mirror case — a STATED SOLN=0 beside
    thermal cards, which LS-DYNA runs with no thermal analysis at all — is named
    but not dropped, and the asymmetry is stated in both messages.
  - **MAJOR: the temperature OUTPUT channels were armed on IMPLICIT decks.**
    `_make_engine_thermal` already excluded implicit and modal runs, but
    `_thermal_solve_active` did not, so `/ANIM/NODA/TEMP` and a `/TH/NODE TEMP`
    group rode along on decks where they are flat by construction (#122).
    MEASURED on a twin pair of converted decks (10-brick bar, `/HEAT/MAT`
    AS = 50, an `/IMPTEMP` holding one end at 400 K against an `/INITEMP` of
    300): the explicit deck carries the far end 300 → 399.731 → 400.000 K over
    84 111 cycles, while the same `.k` plus a `*CONTROL_IMPLICIT_GENERAL` leaves
    it at exactly 300.000 K at every one of its 61 implicit cycles with
    `HEAT STORED = 0.0000000`. Only the imposed nodes move (`resol.F:1802`
    FIXTEMP is reached); nothing conducts. The pre-existing implicit warnings
    now cite that measurement instead of a grep.
  - **MAJOR: the "two-segment `k(T)`" claim was false for the heat flow** — see
    the `/HEAT/MAT` entry above. Every docstring, warning, README row and
    CHANGELOG sentence that repeated it is corrected, and `_fit_td_conductivity`
    now fits ONE line and mirrors it instead of putting half the deck's table
    into cells the conduction never reads.
  - Minors: the PSEROD erosion citation is now per card kind (p.5-49 Remark 5
    for FLUX, p.5-32 Remark 4 for CONVECTION, p.5-124 Remark 4 for RADIATION —
    one page copied across all three was wrong on two of them); a boundary
    record's SEGMENT SOURCE is resolved BEFORE the per-kind resolver announces
    what it converts to, so an undefined `*SET_SEGMENT` no longer prints a full
    "→ /CONVEC with H = 100 …" sentence and no longer leaves an orphan `/FUNCT`
    behind; the BARE `*LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT` spellings say
    their `_OPTION` suffix is mandatory instead of claiming a deck full of
    elements has none; a `*PART` TMID naming a `*MAT_THERMAL_*` spelling k2rad
    does not parse gets its own arm instead of "no `*PART` TMID names one"; one
    TMID stated by two thermal material types is named rather than resolved
    silently; `_warn_law2_self_heating` and the `RHO0_CP` placeholder text read
    the EMITTED `EFRAC` instead of asserting the 1e-20 the same commit made
    variable; and `_min_element_edge` says "node-pair distance", which is what
    its cyclic connectivity walk actually measures.
  - **New: a `/THERM_STRESS/MAT` beside drivers that never move is named.** The
    companion `/INITEMP` starts those nodes at the driver's own constant, so
    `mmain.F90:772-775`'s increment is identically zero and the expansion
    develops NO thermal strain — while LS-DYNA's `*LOAD_THERMAL_CONSTANT*`
    measures from a *"null state"* (p.33-168/33-169) and does develop `α·T`.
    Radioss has no reference-temperature cell to express that, so the gap is
    STATED rather than engineered around with an `/INITEMP` at 0 K, which would
    corrupt conduction, Johnson-Cook `T*` and radiation alike.
  - **New: the `/TH/NODE` groups built from `*DATABASE_HISTORY_NODE` gain
    `TEMP`** on a deck that really runs a thermal solve. Before this the TEMP
    channels lived only in the auto-built group over the driven and loaded
    nodes, so a request for the interior of a heated bar came back with
    DEF/A/AR/VR and the history had to be read out of the ANIM. Measured on
    converter output: the column carries 300 → 941.3 K, and the starter reports
    0 ERROR / 0 WARNING (WARNING 1087 needs a MISSING `/HEAT/MAT`).
  - **The COMPOSITION deck** — `*CONTROL_SOLUTION` SOLN=2 +
    `*CONTROL_THERMAL_{SOLVER,TIMESTEP,NONLINEAR}` + all three boundary
    families (two `/CONVEC` cards sharing one curve at two multipliers) + a
    tabulated `*MAT_THERMAL_ISOTROPIC_TD` + `*MAT_ADD_THERMAL_EXPANSION` + a
    `*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID`, with the whole thermal half inside
    an `*INCLUDE_TRANSFORM` — converts and runs at **0 starter ERROR /
    0 WARNING, NORMAL TERMINATION, 28 038 cycles**, with all four heat channels
    live at once and the balance closing to eight figures (`4.0000348 +
    0.18907485 + 376.39368 + 0.0057459296 = 380.58853 = HEAT STORED`). It also
    caught an ordering defect in this round's own SOLN fix: the element
    resolver announced *"→ /IMPTEMP over the elements' OWN nodes"* and the SOLN
    screen then dropped the record two passes later, leaving a false sentence
    standing (#130). The screen now runs first.
  - **The two-half sweep, halves stated separately (#129).** 855 decks —
    **504 under `C:\openradioss_run`** and **351 under
    `dynaexamples_r14_ton-mm-s`** — each converted twice, once at the
    pre-round commit and once here, in separate subprocesses. Ten files were
    excluded and named: five over a 60 MB cap (`yaris-detailed-v2j.key`
    169.1 MB, `camry-detailed-v5a.key` 248.4 MB, `Model-318_Achshebel-fein`
    73.4 MB, and three Yaris implicit decks, 101.5-191.5 MB) and the Yaris and
    Camry `combine.key` `*INCLUDE` pullers. **0 errors, 0 timeouts.**

    | half | movers | under `C:\openradioss_run` |
    |---|---|---|
    | **1** — the emitted `_0000.rad` + `_0001.rad`, by sha256 | **5** | **0** |
    | **2** — `state.warnings` + `skipped_keywords` + `recognized_not_emitted` | **21** | **0** |

    Every HALF 1 mover is the SAME change and all five are IMPLICIT decks: the
    `/TH/NODE TEMP` group and the `/ANIM/NODA/TEMP` engine card are gone,
    because an implicit run integrates no temperature (measured above) and
    those channels were flat by construction. Every HALF 2 mover is a message
    this round rewrote or added — the `FWORK` consumption sentence, the
    corrected PTYPE citation, the reworded implicit warnings, the
    `EFRAC`-reading `RHO0_CP` placeholder text, the corrected `T1/AL/BL`
    sentence, the new stated-`SOLN=0` note, and `*DATABASE_TPRINT` flipping to
    its no-target branch on the two implicit welding decks.

    A first attempt at this sweep reported **41 phantom movers**, and that was
    a HARNESS defect rather than a converter change: it copied each deck into a
    random `mkdtemp`, so any deck with an unresolvable `*INCLUDE` differed on
    the absolute path quoted in its own "file not found" warning. The work dir
    is now derived from a hash of the deck path and is identical on both sides.

- **SIDE-DEFECT follow-up round — one blocker, one major and six minors found
  by re-verifying the review round below against the manual, the starter and
  engine source, and twin measurements.** Two of the round's own fixes turned
  out to be half-applied, and one of its diagnostics was wrong on 188 corpus
  files because of a pre-existing reader defect underneath it.

  - **BLOCKER, a regression the review round's own `*PARAMETER_LOCAL` fix
    opened: the LOCAL scope never reached `assembly.finalize`.** That pass
    runs from `parse_k_file` AFTER `_pop_local_scope()`, and an inner
    include's frame is popped even earlier by its own recursive parse, so
    every walk in `assembly.py` that feeds a raw cell to `to_int`/`to_float`
    saw an empty scope. MEASURED on a parent/child twin (IDNOFF 6000 /
    IDEOFF 7000 / IDPOFF 8000, child declares `*PARAMETER_LOCAL Ipid 7` and
    writes `*PART &pid`): master emits `/PART/7` AND `/PART/8007` +
    `/SHELL/8007`; the branch emitted ONE `/PART/7` titled *"child plate"* —
    the child's part had silently REPLACED the parent's, its element was
    dropped under *"MESH LOSS ... PID 8007"*, and the log carried a FALSE
    *"'&pid' is undefined"* for a parameter that is perfectly well defined.
    The geometry half is worse, because `_rewrite_node_blocks` REWRITES what
    it reads: under a TRANID translation a `&xc = 25.0` coordinate came out as
    a literal `0`. Fixed by `assembly._scoped_block`, installed at every
    per-block walk in the finalize path. A `*PARAMETER` control deck is the
    fence in both directions.
  - **MAJOR (pre-existing): a `*NODE` id welded to a negative first coordinate
    was read as node 0.** The fixed-vs-free discrimination tested the WIDTH of
    fields 2–4 and never looked at field 1. `*NODE` is I8 + 3×E16, so a
    negative coordinate fills its field completely and glues onto the field
    before it; when X and Y are negative and Z is not, the split yields four
    ordinary-looking tokens with the node id welded to the first —
    `'5-1.000000000E+01-1.000000000E+01'`. MEASURED on
    `dynaexamples/sph/bar-iv/taylor1.k`: master emits node ids
    `[0, 1, 2, 3, 4, 6, 8]` — nodes 5 and 7 GONE, a phantom node 0 in their
    place, the deck's only `/BRICK` still referencing 5 and 7, at ZERO
    warnings, and the starter answers with two `ERROR ID 78 UNDEFINED NODE
    NUMBER`. Both are gone after the fix. Corpus reach: **58 303 rows across
    188 files**, all this one shape; classifying every non-integer field-1
    token found no comma-format, blank or `&parameter` id to trade against,
    and `_free_node_id` accepts `&name` regardless.

    `assembly._parse_node_line` carried the identical test, and its docstring
    says it *"mirrors handlers.handle_node"* — a contract that broke the
    moment the handler was fixed. There the welded row returns `None`, i.e. it
    is SKIPPED by the `*INCLUDE_TRANSFORM` offset pass and by the TRANID
    geometry rewrite. MEASURED on a parent/child twin (IDNOFF 6000) with the
    handler fixed and the walker not: node ids
    `[5, 7, 6001, 6002, 6003, 6004, 6006, 6008]` — the welded rows kept their
    PRE-offset ids, colliding with whatever the parent numbers 5 and 7, while
    6005 and 6007 did not exist and the `/BRICK` referencing them was broken.
    Not corpus-reachable — each of the 10 `*INCLUDE_TRANSFORM` cards in the two
    roots was resolved to its card-1 filename and none of those children
    carries a welded row — which is why nothing measured it.
  - **The `/GRNOD` half of the group-allocator item is closed.** The review
    round routed all 18 element-group sites and the `/SECT` node group through
    the guarded allocators and named the rest as an open hazard in
    `next_grnod_id`'s own docstring; the remaining 24 `/GRNOD` sites (contact
    secondaries, `/INIVEL`, `*ELEMENT_MASS`, `*LOAD_NODE`, the rigid-wall
    groups, the modal dummy `/CLOAD`, the free-node constraint group, the
    `/RBODY` and CNRB groups) now draw from `next_grnod_id` too.
    STARTER-MEASURED with a probe aimed at the id the allocator actually takes
    (#131's rule — the order was printed first): before, `/GRNOD/NODE/90001`
    twice and `ERROR ID 79 DUPLICATE ID / IN NODE GROUP DEFINITION`, ERROR
    TERMINATION; after, 0 ERRORS. A new AST fence fails if any future
    `_emit_grnod_node` site is left on the bare allocator.
  - **`paramexpr`'s depth cap did not cover the `**` chain.** `_enter` was
    called from `expr` and `signed` only; `power` is right-associative and
    recursed into itself for the exponent, so `self.depth` returned to its
    entry value at every `**`. MEASURED: `evaluate("1" + "**1"*1000)` raised
    `RecursionError` — the exact escape the cap exists to prevent — killing
    the whole conversion instead of refusing one parameter by name. The
    manual's exponent semantics are unchanged (`2**3**2 = 512`,
    `-3**2 = 9`, `2**-1 = 0.5`).
  - **`*PARAMETER_DUPLICATION` quoted p.36-6 Remark 2 and did not implement
    it.** *"Only one \*PARAMETER_DUPLICATION card is allowed. If more than one
    is found, a warning is issued and any after the first are ignored."* The
    assignment was unconditional, so a SECOND card won: `DFLAG 1` then
    `DFLAG 2` then two `R thk` definitions ended at `thk = 9.0` where LS-DYNA
    keeps `1.0`. Vol I p.138's R17 release note is the independent
    corroboration — *"Also, only honor the first \*PARAMETER_DUPLICATION
    card."* — and its MUTABLE sentence (*"even if \*PARAMETER_DUPLICATION says
    redefinition is not allowed"*) independently supports the first-wins
    default this batch shipped, which p.36-5's worked example appears to
    contradict. That conflict is now named in `_pop_local_scope`'s docstring,
    which previously stated a `VAL1` outcome the code does not produce, and
    pinned in both directions.
  - **`*DAMPING_GLOBAL`'s STX..SRZ were dropped on BOTH `/DAMP` branches** —
    with a warning on Format 1, in complete silence on Format 2 — so `STX = 1`
    damped all six DOFs. p.15-9 Remark 2 defaults the six to unity only when
    ALL SIX are zero, so they now map to Format 2 `alpha_i = VALDMP × ST_i`
    (x, y, z, xx, yy, zz), the mapping the `*DAMPING_PART_MASS` FLAG = 1
    emitter already uses against `hm_read_damp.F:104-115`. Beta stays uniform:
    it comes from `*DAMPING_PART_STIFFNESS`, which has no per-DOF cells. **No
    corpus deck moves** — scanning both roots (2404 files) found 53
    `*DAMPING_GLOBAL` cards and not one non-zero scale factor.
  - **p.16-50's RADIUS exemption covers five cells, and three were exempted.**
    *"If RADIUS ≠ 0.0, the variables XHEV, YHEV, ZHEV, LENL, and LENM ... will
    be ignored."* A RADIUS-limited card carrying LENL/LENM was still told it
    lost a finite extent that LS-DYNA ignores itself — the #125/#130 class in
    its over-alarming direction.
  - **The bare-`*EOS_*` refusals printed the RADIOSS spelling of the keyword.**
    `EosCard.kind` is the Radioss suffix, so `"*EOS_" + kind` produced
    `*EOS_POLYNOMIAL 3` — a keyword+id pair in neither the deck (which spells
    it `*EOS_LINEAR_POLYNOMIAL`) nor the `.rad` (`/EOS/POLYNOMIAL/3`) — and
    `*EOS_IDEAL-GAS`, which is not even legal LS-DYNA. The source keyword now
    travels on the record and `label()` prints both. (#131's label class.)
  - **One deck, two through-thickness point counts, one global offset.**
    `INISHVAR = 22 + NIP*6` is set per RECORD into the COM01 common
    (`hm_read_inistate_d00.F:2206`) while `csigini.F:231/233` and
    `scigini4.F:345/347` read `SIGSH(INISHVAR+IT)` at CONSUME time, so two
    shell parts at NIP 3 and NIP 5 in one `/INISHE|/INISH3 STRS_F` pass make
    every element whose NIP differs from the last record's read its sigma_zz
    and station positions from the wrong slots, at 0 starter ERROR. Each
    record passes its own NTHICK check, so nothing else in the pass can see
    it. Pre-existing and unchanged — the emitted records are correct — but now
    named, because item (D) adds a second block kind to the same pass.
  - Also recorded rather than claimed: p.15-9 Remark 3 (no mass damping on
    prescribed-motion or `CONSTRAINED_NODE_SET` nodes) is not implemented.
    `fixvel.F:370-372` overwrites the prescribed DOF's acceleration and runs
    after `DAMPING` in the same cycle (`resol.F:7216` vs `:7345`), so the
    MOTION is unaffected — but the overwrite is per DOF where the exemption is
    per NODE, and `damping.F:167-170` books the damping energy first. The
    docstring says exactly that instead of claiming parity.

- **SIDE-DEFECT review round — two blockers, three majors and six minors found
  by reviewing the batch below.** Every one was self-consistent in the code and
  wrong against a measurement or the manual's own sentence, and none of them is
  reachable by the corpus sweep, so the batch's clean sweep was not evidence
  they were safe.

  - **`_plane_cut`'s degenerate-normal arm returned a 4-tuple** while every
    other path and BOTH call sites unpack 5 since the spring arm was added. A
    `*DATABASE_CROSS_SECTION_PLANE` whose `XCT->XCH` is a zero vector (all six
    coordinate cells blank — legal, every field defaults to 0.0) killed the
    WHOLE conversion with `ValueError: not enough values to unpack (expected
    5, got 4)` and wrote no deck at all. Master converts that deck and warns.
  - **`*PARAMETER_LOCAL` was defined and then DISCARDED before anything could
    use it.** LS-DYNA scoping is a PARSE-TIME concept; k2rad resolves `&name`
    LAZILY, in the handlers, so popping the frame at the end of each file
    removed the binding first. MEASURED: `/PROP/SHELL Thick 0` with
    *"'&lthk' is undefined"* on a valid deck (starter `ERROR ID : 495`, ERROR
    TERMINATION) where master emitted 2.5, and the masking case silently
    emitting the OUTER value (1.0) where the manual's own worked example says
    9.0. The fix is not "stop popping": each Block now carries the LOCAL
    bindings live where it was READ and `dispatch` installs them for the
    handler, so BOTH halves of p.36-4 Remark 5 hold — `VAL2 = 20.0` inside the
    include, `2.0` after it, `VAL4` gone.
  - **`*PARAMETER_TYPE` was dropped, and the warning stated the opposite of the
    manual.** p.36-11: *"*PARAMETER_TYPE is a variation on the *PARAMETER
    keyword command.  In addition to its basic function of associating a
    parameter name (PRMR) with a numerical value (VAL) ..."* — Card 1 is
    `PRMR VAL PRTYP`. MEASURED: master resolved `&thkp` to 7, the branch fell
    back to the card default 2.
  - **The `/SECT` `TSID` arm resolved a `*SET_TSHELL` id in the `*SET_SHELL`
    registry** — the #125/#128 two-namespace trap this repo documents in
    `writer/rarecards.py:110-118`. MEASURED: a `*SET_SHELL_LIST 5` holding
    shell 101 put `101` into `/GRBRIC/BRIC/90003`, where the starter resolves
    it against the brick table.
  - **`RADIUS < 0`** (XCT/XCH are node ids) **was resolved in the HANDLER**,
    but handlers run in deck-block order and `handle_node` fills `state.nodes`
    in that same pass. MEASURED on twin decks differing only in card order,
    both nodes present in both: the card-before-`*NODE` deck printed *"they
    are not nodes of this deck"* and emitted no `/SECT`. Resolution moved to
    the writer.
  - **The comma-delimited `*PARAMETER_EXPRESSION`** — the form p.36-8 Remark 1
    uses in its OWN worked example — **was split at column 10**, so
    `rplot,term/(states-30)` became `/(states-30)` and `rxmin, -96` (exactly
    ten characters) came out EMPTY. Real carrier: dynaexamples
    `IGA_tensile_test_input/tensile_test_iga.k`, which writes four such base
    parameters plus eight box parameters that reference them.
  - **The `_PLANE` spring arm reported a force `secforc` does not.** p.16-48,
    Figure 16-2's caption: *"The automatic deﬁnition does not check for springs
    and dampers in the section."* The springs are now NAMED and left out, and
    the message points at LS-DYNA's own `_SET`/`DSID` slot instead of telling
    the user to delete elements from a correct deck. Re-routed BEAMS still go
    to `grsprg_ID` — LS-DYNA's plane cut does include those. Measured on twin
    engine runs: `2.296195E7 N/s` vs the analytic shell-only `2.307692E7`
    (−0.50 %), and splicing the spring's group back in adds `1.999977E8`
    against the spring's own `k·v = 2.0E8` (−0.0012 %).
  - **`Iframe` 0 → 10.** p.16-50 gives the card's output-frame cell `ID` the
    default *"global"*. `section_skew.F:103-139` keeps the node-derived normal
    at `Iframe ≥ 10` and `:146-150`/`:151-164` compute the same origin, so
    only the moment axes move — measured on an `Iframe 0` twin, 44 of 48
    section channels are IDENTICAL and the four that move are one section's
    moment going from the local `M1` to the global `M3` (5000 in both).
  - **The section `/GRNOD` came from the bare allocator.** Probe aimed at the
    id the allocator actually takes (#131's rule): master emits
    `/GRNOD/NODE/90002` TWICE (starter `ERROR 79 IN NODE GROUP DEFINITION`);
    `next_grnod_id()` dodges to 90003.
  - A `RecursionError` escaped both `except ExprError` sites (a nesting cap
    makes it a named refusal); a UTF-8 em-dash reached the emitted `.rad`, the
    first non-ASCII byte k2rad has ever written; p.36-6 Remark 1 scopes the
    duplication exemption to LOCAL-over-NON-LOCAL (*"a LOCAL that masks another
    LOCAL ... will"* trigger the actions); and `_sect_synth_frame`'s docstring
    named two of its three return values — the missing one selects `Iframe`.

- **`*NODE`'s own `TC`/`RC` constraint cells were dropped in complete
  silence** (pre-existing, found while reviewing). Vol I R17 makes `*NODE`
  Card 1 `NID X Y Z TC RC`, and TC/RC are constraint codes (0 none, 1 x, 2 y,
  3 z, 4 xy, 5 yz, 6 zx, 7 xyz) in the GLOBAL system — exactly the triples
  `*BOUNDARY_SPC_NODE` states one flag at a time. `handle_node` reads only
  NID/X/Y/Z. MEASURED on a spring-mass coupon whose anchor carried
  `tc=7/rc=7`: no `/BCS` was emitted, the anchor was free, and the whole
  oscillator drifted at the centre-of-mass velocity (node-2 DX reached
  6.68 mm against an intended 0.317 mm amplitude) while the engine printed
  NORMAL TERMINATION — the #122 class, legal and accepted and wrong.
  **Not converted, and the reason is the SCREENING rather than the direction
  of the error** (an earlier draft argued that an extra constraint is the
  harder failure to notice, which does not by itself justify shipping a
  missing one). A correct `/BCS` pass has to screen two things this round
  cannot validate: p.35-3 Remark 1 — *"No attempt should be made to apply
  boundary conditions to nodes belonging to rigid bodies"* — and any DOF
  already driven by `/IMPVEL` or `/IMPDISP`, which would fight the constraint
  over the same slot. Both need their own twin campaign, so the conversion is
  a ROADMAP item behind an opt-in `--node-tc-rc-to-bcs` and the interim is the
  note. The loss is named once per deck, with the count, a few ids and the
  `*BOUNDARY_SPC_NODE` remedy; no deck's bytes move. The detector was checked
  against a scanner that does not use k2rad: same decks, no false positives,
  no misses.

- **SIDE-DEFECT batch — ten defects at the edges of cards this converter
  already handles.** Each is reachable, none is the main line of any single
  keyword, and four of them changed a NUMBER on a real corpus deck. Measured
  master-vs-branch throughout; two of the research verdicts this batch started
  from were themselves refuted by those measurements, and both refutations are
  recorded below rather than shipped.

  1. **(A) The bare `*EOS_*` `/MAT/LAW6` carrier collided in the `/MAT`
     namespace, and could never have been legal anyway.** A bare `*EOS_*` — no
     same-id `*MAT_NULL`, named by no `*PART` EOSID — used to mint a carrier
     under the EOS id, guarded by `_impact_claimed_mids`, a hand-kept list of
     THREE families standing in for the semantic quantity "does any other
     emitter put a `/MAT` under this id?" (#124 class). MEASURED on the corpus
     carrier `dynaexamples_r14/ale-s-ale/s-ale/wavestructure/2Dlag.k`, whose
     orphan `*EOS_LINEAR_POLYNOMIAL 3` sits on a `*MAT_JOHNSON_COOK` (in none
     of the three): `/MAT/LAW4/3` AND `/MAT/HYD_VISC/3`, starter
     `ERROR ID : 79 ... IN MATERIAL DEFINITION ID=3 is DUPLICATED`,
     3 ERROR(S), ERROR TERMINATION — plus `/EOS/GRUNEISEN/3` beside
     `/EOS/POLYNOMIAL/3`, which nothing diagnosed. The branch is REMOVED, not
     renumbered: NONE of the three `*EOS_*` spellings k2rad reads carries a
     density cell (LS-DYNA takes it from the `*PART`'s own `*MAT`, Vol I R17
     p.37-6), so every handler stores `rho0 = 0.0` and a `/MAT/LAW6` with
     `RHO_I 0` is starter `ERROR 683` — measured on the very deck
     `tests/test_impact_mats.py` pinned as CORRECT, which was therefore
     pinning an unrunnable output. Dropping is also what LS-DYNA and dyna2rad
     do with an `*EOS_*` no `*PART` names. `2Dlag.k` after the fix: one card
     per id in both namespaces, starter 3 ERROR(S) → 1 (the survivor is the
     out-of-scope `ERROR 3046`). Adds the tenth deck-wide duplicate scan,
     `_warn_duplicate_eos_ids`: `/EOS` is the namespace with NO starter check
     at all — `hm_read_eos.F` contains no `UDOUBLE` anywhere, so two `/EOS` on
     one id are accepted at 0 ERROR / 0 WARNING and the last silently replaces
     the material's pressure law.

  2. **(B) `*INITIAL_STRESS_SHELL` and `_SOLID` had no `*INCLUDE_TRANSFORM`
     offset row**, being registered directly in `HANDLERS` instead of through
     `INITIAL_STATE_PRELOAD_KEYWORDS`. MEASURED with/without twin on a
     parent+child pair (IDEOFF 6000, IDPOFF 7000, all offsets distinct):
     MASTER put the child's stress record on the PARENT deck's shell 1 — a
     different part, a different thickness, a different place — and dropped
     the other two under a generic "keyword has no offset map" warning, with
     no `/INIBRI` block at all; the branch lands `/INISHE 6001` and
     `/INIBRI 6001`, rows of the child's own offset mesh. Both offsetters are
     driven by NEW record walkers extracted from the handlers, because a
     declarative `data` spec would rewrite a stress of 1.5 as the id 1 and an
     all-blank stress card is legal (#116/#119). The audit found a third
     keyword without a row, `*INITIAL_VOLUME_FRACTION_GEOMETRY`, whose `FMSID`
     lives in two id namespaces selected by `FMIDTYP` beside it (#125).

  3. **(C) `/DAMP` reached only four element families, so a beam+spring model
     ran completely undamped.** Both target-node arms of `_make_damping`
     walked `shell_elems | solid_elems | tshell_elems | sph_elems` and nothing
     else. MEASURED at master on a 2-beam + 1-spring + 1-`*ELEMENT_MASS` deck
     carrying `VALDMP 10.0`: the "no target deformable nodes found" exit and
     zero `/DAMP` cards. The scope was never a property of `/DAMP` —
     `hm_read_damp.F:415-429` validates only the group id,
     `hm_lecgrn.F:538-550` collects beam/truss/spring nodes into a
     `/GRNOD/PART`, and `damping.F:148-150` walks the node list with the sole
     exclusion `TAGSLV_RBY(I)==0`, opening a SECOND loop at `:175` for the
     rotational DOFs. Measured on a spring-only oscillator: log decrement
     0.18857418 against the hand-computed 0.18858044, i.e. alpha recovered as
     600.000132 from an input of 600, with alpha-0 and wrong-group twins as
     controls. The branch emits `/DAMP` over all five nodes; starter
     0 ERROR / 0 WARNING, engine NORMAL TERMINATION, 59 cycles. Two docstrings
     asserting the OPPOSITE of the engine are deleted (#130), and the scope
     grows the two LS-DYNA states that were missing: the `*ELEMENT_MASS` nodes
     and each `/RBODY` MAIN node ("the nodes of deformable bodies and ... the
     mass center of the rigid bodies", p.15-8). Side defect on the same card:
     `handle_damping_global` split its FIXED-format card 1 free-format, so a
     blank interior column shifted every later field — SRX read as STZ, SRZ
     lost.

  4. **(D) `/INISH3/STRS_F/GLOB` is emitted — initial stress on a 3-node shell
     was dropped, under a warning whose cited fact was FALSE.** It said the
     card "is a different card layout this converter does not write yet", and
     the code comment beside it said "the card layout differs". `diff` of the
     extracted `FORMAT(radioss2021)` blocks of `inish3_strs_f_glob_sub.cfg`
     and `inishe_strs_f_glob_sub.cfg` is EMPTY (#131 class). The ONE
     difference is `npg`, and the two rules are OPPOSITE: 4 on a QUAD
     (`scigini4.F:160`), 0 or 1 on a `/SH3N`, whose check is `NPGI > 1` at
     `csigini.F:143` — measured `ERROR 26` for npg 3 and 4, clean for 0 and 1.
     MEASURED on a MIXED deck (quad stress + tri stress + quad strain, the
     #127 shape): starter 0 ERROR / 0 WARNING, engine NORMAL TERMINATION,
     70 cycles, and CONSUMED rather than merely accepted — with/without twin,
     cycle 1 I-ENERGY -11.75 vs -4.125 and K-ENERGY 5.468 vs 1.705 at
     identical total mass. The #127 companion rule is extended to tris because
     `ITHKSHEL = 2` is global AND cross-family, and the companion warning now
     names the card each record actually went into.

  5. **(E) The `/SECT` reporting frame was conditioning-picked**, not read
     from the card: N1 = the lowest node id of the cut, N2 = the farthest
     node, N3 = the largest triangle. That frame is not decoration —
     `section_skew.F:82-99` makes `e6 = (N2-N1) x (N3-N1)` the section NORMAL
     and `section_c.F:385-389` SPLITS every nodal force with it. MEASURED on a
     shell strip cut at x = 25 with normal +X: the picked frame's `e6` was
     `(0,0,-1)`, **90.00 degrees off**, with the origin at `(20,0,0)` — not on
     the plane — at 0 starter ERROR; on a cantilever the same defect cost
     89.6 % of the true normal force, gave 1.34x the tangential one and moved
     every moment component including the global ones. The frame is now three
     synthesized element-free nodes built from the card (#127's preload
     precedent), so `e6` is the card's normal to 12 places and the
     `Iframe = 0` origin lands exactly on `(XCT,YCT,ZCT)`. `XHEV/YHEV/ZHEV`,
     `ITYPE` and `RADIUS < 0` (which makes `XCT`/`XCH` NODE IDS) are read for
     the first time. `/TH/SECTIO` also requests `GLOBAL` and `CENTER`, because
     `CX/CY/CZ` is the only way to audit the frame from the T01.

  6. **(F) `_plane_cut` had no spring arm**, so a section plane through a belt
     or a discrete spring found nothing and `grsprg_ID` stayed 0. MEASURED,
     starter echo, master vs branch on one deck: `NUMBER OF SPRING ELEMENTS`
     0 -> 1 (`SPRING 10, N1=1 N2=0`, the correct tail-side pack code) and
     section nodes 3 -> 4, both at 0 starter ERROR. The walk keys on
     `state.discrete_elems` and the 1-D `state.seatbelt_elems`, never on the
     nine-producer union `state.spring_elem_ids` (#128), and the group is
     emitted whenever the column is non-zero because `elegror.F:92-94` returns
     0 for a missing group and says NOTHING. The DIVERGENCE is named: Vol I
     R17 Figure 16-2's caption says LS-DYNA's automatic plane definition "does
     not check for springs and dampers in the section", so this is a
     deliberate super-set. On the `_SET` spelling `TSID` and `DSID` are
     converted too — they were dropped with the stated reason "no
     converter-side element type", false on BOTH counts (#130).

  7. **(G) `/DYNAIN` under implicit is MEASURED to work, so no guard is
     added** — and the research's predicted defect is REFUTED. Implicit probe:
     `QUASI-STATIC NON-LINEAR`, 97 nonlinear iterations, NORMAL TERMINATION in
     20 cycles, three `.dynain` files of 22 225 bytes with all four blocks,
     distinct md5 each, driven edge 20.1960 / 20.1980 / **20.2000** — the
     terminal state captured exactly, because `imp_dt.F:53-56` clamps the last
     quasi-static step onto `TSTOP`. The terminal-state caveat is rescoped to
     explicit-only. The research proposed a warning naming every QEPH part, on
     the reading that QEPH loses its `*INITIAL_STRAIN_SHELL` block; that
     warning is NOT shipped, because the implicit probe above IS a QEPH deck
     (`_elform_to_ishell` returns 24 unconditionally under implicit) and its
     dynain HAS 164 strain records. The real mechanism, found by chasing the
     refutation: `check_qeph_stra.F:64-76` compares the first **25**
     characters of each engine-deck line against the literal
     `/DYNAIN/SHELL/STRAIN/FULL`, while `fredynain.F:140` accepts the card on
     five characters — so the short `STRAI` spelling parses and silently loses
     the block. MEASURED spelling twin: 22 225 B with the strain block vs
     12 422 B without, the same figure the research attributed to QEPH. k2rad
     already writes the long form; it now comes from a named constant the
     tests assert character for character.

  8. **(H) Seventeen of eighteen element-group emission sites used the bare
     `next_id()`**, with `next_elem_group_id()` on one (`/ACTIV`). All of them
     use the guarded allocator now, with a per-site verdict — the five `/SURF`
     ids sitting beside those emitters deliberately stay bare, because `/SURF`
     is its own starter namespace and may share a number with any `/GR*`
     group. Adds the eleventh deck-wide scan, `_warn_duplicate_group_ids`,
     keyed PER FAMILY: MEASURED on twelve probe decks, `/GRBRIC` + `/GRSHEL`,
     `/GRSPRI` + `/GRBEAM`, `/GRNOD` + `/GRBRIC`, `/SURF` + `/GRSHEL` and even
     NINE groups on one id are all ACCEPTED at 0 ERROR, while `/GRBRIC/BRIC`
     twice — or beside `/GRBRIC/PART` — is `ERROR 79`. A single scan over
     "any `/GR*` id" would have fired on five decks the starter accepts.

  9. **(I) `*PARAMETER_EXPRESSION` is evaluated, and so is inline arithmetic
     in a data field.** Two measured corpus losses recovered: LSTC's own
     `efg/metal-cutting/main.k` writes `TRISE` as `&tend/6.0` in a plain
     10-char column, so the back-solved `VMAX` came out 9/0.03 = **300 mm/s**
     where the deck means 9/0.025 = **360** — a 16.7 % under-speed on the
     cutting tool, plus a rectangular plateau instead of a trapezoid; and
     `set-yaris-detailed-v2j.key` defines its occupant masses with
     `&DUM_1*.035+1e-3` and writes `&M1_1` into ten `*ELEMENT_MASS` cards, all
     ten of which were dropped — **0.15208 Mg = 152.08 kg** of occupant mass
     silently deleted from the flagship public crash deck, now restored to the
     digit. The evaluator (`k2rad/paramexpr.py`) is recursive descent with NO
     `eval()`, because three of the manual's rules are LS-DYNA-specific and
     Python gets each wrong: the unary minus binds TIGHTER than exponentiation
     (`-3**2` is 9, not -9), the integer/real type of each operand is honoured
     (`2/5` is 0, `2.0/5` is 0.4, integer division truncating toward zero),
     and the intrinsics are Fortran's (`sign(-4,8) = 4`, `int`/`aint` truncate
     while `nint`/`anint` round and differ in the TYPE they return, NINT
     rounding half away from zero). Also implemented: `*PARAMETER_DUPLICATION`
     DFLAG 1-5, whose **default 1 means the FIRST definition wins** where the
     parser had LAST-wins; `MUTABLE`; `LOCAL` scoping as a MASK that is
     restored when the file ends; `C`-typed parameters as a named refusal
     rather than a silent 0; `*PARAMETER_TYPE` read and ignored with its
     reason. `to_float`'s trigger was `"&" in t[:2]`, so `2.0*&thick` and
     `(&thick)` returned the caller's default with NO diagnostic at all.

  10. **(J) The dead `if c.only:` tiebreak branch is removed**, with the
      reason stated correctly. The comment called it unreachable "with today's
      mapping"; it is unreachable by the LS-DYNA CARD GRAMMAR. Vol I R17
      p.11-14/15 enumerates the family exhaustively and exactly two of eleven
      spellings contain `ONLY`, taking Card 4: TIEBREAK_NODES (a FORCE
      criterion) and Card 4: TIEBREAK_SURFACE (a STRESS criterion) — neither
      has a length field, and `PARAM`/`CCRIT` lives only on Card 4:
      AUTOMATIC_..._TIEBREAK, mandatory for four spellings none of which has
      an `_ONLY` variant. Same in R16. The semantics the branch encoded are
      kept as prose. The pinning test found a weakness in ITSELF — sweeping
      every option showed `_tiebreak_bond_class` DOES return CCRIT for a
      hand-made SURFACE record at option 6 or 8, because it classifies the
      AUTOMATIC enumeration and knows nothing about spellings — so the
      invariant is now asserted over records the PARSER produced from real
      decks, at the layer that actually holds it.

- **TIEBREAK post-review round — the `Isym = 1` claim the previous round ADDED
  was inverted, and a refusal named a card the converter had already dropped.**
  Diagnostics only, plus one screening line; no corpus deck moves.

  1. **`Isym = 1` DOES exclude compression on a coincident glue joint** — the
     opposite of what the verification round shipped. The refuted text told the
     reader *"the compression exclusion does NOT apply and the tie can also
     release in compression — offset the two surfaces by more than half a
     length unit if you need the asymmetry"*, i.e. a false fact about the
     converted deck **and** a mesh change prescribed on a correct one (the #125
     class). Two errors behind it: `int2rupt.F:244` is
     `INORM = SIGN(IONE, NINT(SUM))` with `IONE = 1`, and Fortran `SIGN(A, B)`
     returns `|A|` for `B >= 0` — so `SIGN(1, 0)` is `+1`, **not** `0`, which is
     byte-identical to the `Isym = 0` arm's `INORM(II) = IONE` at `:246`; and
     `INORM` is only a sign multiplier on the segment normal (`:346`), so
     `ruptint2.F`'s `ISYM == 1` branch keeps both compression gates armed
     (`:162` `IF (SIGN > ZERO) FACN = …`, `:164` `IF (DIS_N > ZERO .AND.
     DIS_NA > DNMAX .OR. DIS_T > DTMAX)`). **MEASURED**, four-run twin on a
     coincident 2×2 brick glue coupon (`NFLS = 100` over a 400 mm² bond → a
     40 kN cap), all NORMAL TERMINATION: `Isym = 1` tension **9/9 ruptures**,
     tie force capped at **39.27 kN** (−1.8 %); `Isym = 1` compression **0/9**,
     tie carrying **3.76 MN = 94× NFLS entirely uncapped**; `Isym = 0` tension
     9/9 at the identical 39.27 kN; `Isym = 0` compression **9 START / 8 TOTAL**
     capped at 41.37 kN. That last arm is the control proving the compressive
     load reaches the branch (#130). A fifth run with the main `*SET_SEGMENT`
     node order REVERSED gave the same rupture times to the digit — for a solid
     main surface `insol3.F:167-175` re-orients the segment outward itself — so
     there is no inverted-segment hazard either. The Reference Guide p.213
     sentence is quoted accurately but the 2026 source contradicts it; the
     warning now says so instead of presenting `int2rupt.F` **as** that
     sentence. Same correction in the README and the ROADMAP.
  2. **The `ERROR 556` guard refused on records that emit no interface.**
     `_emitted_type2_mains` screened each `*CONTACT_TIED_*` /
     `*CONTACT_SPOTWELD` on its SECONDARY side only. A tie whose MAIN side
     cannot become a `/SURF` — `MSTYP = 4`, a node set — is dropped by
     `_make_tied_interfaces` and emits **no `/INTER` at all**, yet it still cost
     the tiebreak its rupture and the message told the user that record
     *"converts to a second /INTER/TYPE2"* and *"would fail even though it is
     clean by itself"*. Direction was safe (a lost rupture, never a shipped
     ERROR 556), but the printed statement was about a card not in the deck.
     New non-mutating `_tied_main_surface_resolves` mirrors
     `_tied_master_surface` + `_make_master_surface` and screens all three
     producers. **VALIDATED** on the deck the finding cites (rupture tiebreak
     beside a `*CONTACT_TIED_NODES_TO_SURFACE` whose `MSID` is a node set): the
     `.rad` carries exactly one `/INTER/TYPE2`, now at **Spotflag 22 with the
     rupture cards** instead of the downgraded 27, and the starter answers
     **0 ERROR / 0 WARNING** — no `ERROR 556` anywhere — while the engine runs
     to NORMAL TERMINATION with **9 START / 9 TOTAL RUPTURE**. The refusal was
     costing a real, legal rupture.
  3. **`CT2CN` / `CN` at OPTION −9 / −11 were reported INERT although LS-DYNA
     reads them.** p.11-36 enumerates the negative OPTIONs as *"EQ.-9: See 9.
     NFLS/SFLS/ERATEN/ERATES are functions of temperature"* — those four cells
     are the only ones redefined, so `CT2CN`/`CN` are read exactly as at 9/11,
     which is why the sibling `ERATEN`/`ERATES` entries already carried them.
     The table disagreed with itself and printed a real drop as *"INERT in
     LS-DYNA too, not lost"*.
  4. **The `CT2CN`/`CN` drop message quoted the wrong card.** It said the tie
     *"is a kinematic constraint with no stiffness input at Spotflag 20/21/22
     (the Stfac/Visc/Istf card is gated on 25/26/27/28)"* — but those two cells
     are live only at OPTION 9/±11/13/14 and on the `_USER` Card 4.1, none of
     which is `CCRIT`, so every record reaching that line is emitted at
     **Spotflag 27/28**, where `_emit_inter_type2` **does** write
     `Stfac 1.0 / Visc 0.05 / Istf 2`. True conclusion, false premise (#129).
     `_tiebreak_no_stiffness_reason` now follows the card actually emitted: at
     27/28 the reason is that the penalty stiffness is *computed* from the two
     sides' own stiffnesses through `Istf` (RefGuide p.214 remark 16) and
     `Stfac` is only the dimensionless *"Stiffness factor"* on that result
     (p.210), with no slot for a stress/length `CN` or a ratio; the delegated
     OPTION-4 and self-tie routes emit no `/INTER/TYPE2` at all and say that
     instead.
  5. **`Inacti = 5` was credited with a measurement that cannot show it.** The
     cited evidence is a with/without-**COMPANION** twin, which discriminates
     nothing about `Inacti`. Direct twin on the brick coupon: `Inacti = 0` and
     `Inacti = 5` are identical to every printed digit (first `START RUPTURE`
     0.185460815E-04 s, last `TOTAL RUPTURE` 0.508858180E-03 s in both), while
     deleting the companion moves the last one to 0.509698831E-03 s (−0.165 %)
     — `Igap = 2` over solid parts gives the companion a zero gap, so there is
     no initial penetration for `Inacti` to act on. Restated: the shift is the
     companion existing, and `Inacti = 5` is the DEFENSIVE choice for the
     untested SHELL geometry where `Igap = 2` gives a half-thickness gap.
  6. **The Spotflag-20 area note printed the solids-only sentence.** Since the
     per-node `ERROR 670` screen, Spotflag 20 means *genuinely mixed*, and
     `i2surfs.F:70-73` leaves both element loops live at ILEV 20 while
     `:74-139` sums them — so the shell-backed nodes get the exact mid-surface
     normalisation and only the solid-backed ones the `(1 + t/a + t/b)/3`
     factor. The note contradicted the MIXED disclosure emitted one warning
     earlier; it now has its own third branch.
  7. **The companion's `FS`-sentinel warning named a keyword+id pair that does
     not exist.** `_contact_friction` was called with the SOURCE keyword and the
     COMPANION's minted id, so the message read
     `*CONTACT_..._TIEBREAK 90005: Card-2 FS=-1 …` for a card in neither the
     deck nor the `.rad`. Both functions take a `label` override now and the
     message reads `*<keyword> <source id> -> companion /INTER/TYPE25/<id>`.
  8. **Citation and grammar repairs.** The `ERROR 117` duplicate scan is
     `hm_read_interfaces.F:229-234` (`DO K=1,NI-1` / `IF (NOINT ==
     IPARI(15,K))` / `ANCMSG(MSGID=117)`, under the `IF (IPARI(71,NI) <= 0)`
     guard), not `:237-241`, which is the unrelated `IFRONTPLUS` block — three
     sites plus this file. The three FLAG entries of `_TIEBREAK_PARAM_ROLE`
     produced *"at OPTION 4 it is PARAM = 1 makes SFLS a frictional stress
     limit"*. The `*SET_SHELL` spelling of the `A1`/`A2` per-segment override
     (p.11-72 Remark 1) is named as a known unnamed loss — unreachable today,
     because a `SURFA` on a shell element set resolves to no nodes at all and
     the record is dropped by name first.
  9. **`test_grnod_dodges_a_user_node_set_at_the_auto_id_base` could not
     fail.** Its `*SET_NODE_LIST 90001` collided with the tiebreak's main
     `/SURF`, which is allocated first, so the group landed on 90002 under
     `next_id()` and `next_grnod_id()` alike — reverting the guard left the file
     green. At SID **90002** the two differ; the test now also pins which id is
     emitted. (Mutation-checked: all nine fixes above are caught by a test that
     fails without them.)

- **TIEBREAK verification round — two guards whose SCOPE did not match their
  consumer's, an `_MPP` delegation that lost a whole interface, and four
  warnings that stated something untrue.** Every item below was reachable in a
  probe deck; none of them in the corpus, which carries only `OPTION 1` and one
  `*CONTACT_TIEBREAK_NODES_ONLY`.

  1. **`ERROR 556` is a DECK-WIDE check and the guard tested one interface
     pair.** `chktyp2.F:80-83` tags the secondary nodes of **every**
     `/INTER/TYPE2` whose `Spotflag` lies outside `{25,26,27,28}` — the rupture
     flags 20/21/22 do — and `:87-108` then checks the MAIN nodes of **every**
     `/INTER/TYPE2` against that tag (its `IF (ILEV /= 25 .OR. ILEV /= 26)` is
     a tautology, so 27/28 mains are scanned too). A rupturing tiebreak is the
     only interface k2rad emits outside that set, so it is the sole tag
     producer — and its tag poisons every other TYPE2 in the deck: each
     `*CONTACT_TIED_*` and each `*CONTACT_SPOTWELD`, which are exempt from
     being TAGGED but not from being CHECKED. The guard only tested
     `sec_nids & main_nids` of its own record. PROVEN with a with/without twin
     (rupture tiebreak on part 1 beside a `*CONTACT_TIED_NODES_TO_SURFACE`
     whose MAIN side is part 1): **4 × `ERROR 556` + ERROR TERMINATION, no
     restart file**, against 0 ERROR without the tied card — and the converter
     said nothing at all. A glued flange plus spot welds on the same part is
     the ordinary production shape. Now: the secondary set is tested against
     the MAIN node set of every `/INTER/TYPE2` the deck will emit, and a hit
     falls back to the permanent auto-penalty tie with the colliding interface
     id and node count named.
  2. **`ERROR 670` is a PER-NODE check and the guard tested the set.**
     `i2surfs.F` computes `AREA(I)` for each secondary node in turn
     (`DO I=1,NSN`) and `:287-293` raises the hard error for **any single**
     node still at zero after the `Area` fallback — which is the rupture
     card's own `Area` cell, written 0. The old test was an OR over the whole
     group, so one free node in an otherwise solid-backed `*SET_NODE` shipped
     `2 × ERROR 670` + ERROR TERMINATION with no warning. Now the classes are
     resolved per node: `Spotflag 21` needs a shell on *every* node, `22` a
     solid on every one, `20` is used only for a genuinely mixed set, and a
     node with neither refuses the rupture by name (with the node ids listed).
     As a side effect a set where every node carries a shell now gets the
     EXACT-normalisation `21` instead of the summing `20`.
  3. **The `_MPP` card offset was lost on the two delegating routes.**
     `handle_contact_tiebreak` shifts past the MPP card for its own Card-1..4
     reads, then handed the raw block to
     `handle_contact_automatic_surface_to_surface` (OPTION 4) and
     `handle_contact_automatic_single_surface` (self-tie), which re-derived the
     offset from `_parse_contact_header` and read Card 1 off the MPP card.
     MEASURED on `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_MPP_ID` with
     OPTION 4: `SSID` came back as the MPP `IGNORE` flag, the contact was
     **dropped entirely** ("resolved to no nodes at all") and a phantom
     `SBOXID/MBOXID` warning was built from `PARMAX = 1.1`. On
     `*CONTACT_AUTOMATIC_SINGLE_SURFACE_TIEBREAK_MPP` — the spelling p.11-40
     Remark 2 restricts to MPP in the first place — the same shift silently
     widened a part-scoped self-contact to an all-parts one. Both handlers now
     take the resolved `card1` (and `inter_id`) from the caller.
  4. **The OPTION-4 and self-tie routes `return`ed before the Card-4
     inventory** (the `#129` round-2 trap verbatim), so those two routes lost
     their whole field accounting — and `SFLS` is not incidental at OPTION 4:
     *"For OPTION = 4, SFLS is a frictional stress limit if PARAM = 1. This
     frictional stress limit is independent of the normal force at the tie"*
     (p.11-38). The record is now built before the branches and every exit runs
     the inventory.
  5. **`PARAM` was reported with a role LS-DYNA does not give it.** p.11-38/39
     enumerates SIX roles — thickness-offset flag (OPTION 2), frictional-stress
     -limit flag (4), `CCRIT` (6/8), friction angle (7/10), damage exponent
     (±9/±11), tiebreak-layer thickness (13/14) — and **no role at all** at
     OPTION 1/−1, 3/−3, 5 and 101..105. The message named "a friction angle, a
     damage exponent or a layer thickness" for all of them, and reported the
     cell as a LOSS where LS-DYNA does not read it. `PARAM` now has an entry in
     `_TIEBREAK_FIELD_SCOPE` (out-of-scope → the INERT half) and a per-OPTION
     role.
  6. **The `_USER` flavour has its own Card 4.1** — p.11-43: *"These cards,
     4.1, 4.2, and 4.3, are mandatory"*, and 4.1 is `OPTION NHV CT2CN CN OFFSET
     NHMAT NHWLD`, not `OPTION NFLS SFLS PARAM …`. The old code read the
     ordinary layout (reporting `NHV` as a normal failure stress and `CT2CN` as
     a shear one) and counted ONE card where three follow, landing every
     optional-card read three rows early.
  7. **`*CONTACT_AUTOMATIC_{SINGLE_SURFACE,GENERAL}_TIEBREAK_BEAM_OFFSET` were
     not dispatched at all.** p.11-16 offers `BEAM_OFFSET` for exactly those
     two members of the family; both landed in `skipped_keywords` with zero
     warnings and no interface — a missing LOAD PATH, which is the very outcome
     the one-source generator exists to prevent. Added as an `OPTION4`
     dimension scoped to those two bases, with the offset springs and the
     Card-E `FTORQ` moment transfer named as dropped.
  8. **The companion `/INTER/TYPE25` wrote `Fric = FS` raw**, bypassing the
     three LS-DYNA sentinels every other emitter routes through
     `_contact_friction`: `FS = −1` (*PART_CONTACT), `−2` (*DEFINE_FRICTION →
     `fric_ID`), `2` (`FD` is a *DEFINE_TABLE id). MEASURED: a rupturing
     tiebreak with `FS = −1` emitted `Fric = −1.000000000000`, echoed by the
     starter at 0 ERROR — a negative Coulomb coefficient presented as
     legitimate (the `#114` class).
  9. Four smaller ones, each a false or missing statement rather than wrong
     output: the `*SET_NODE DA1..DA4` per-set override was named as a LOSS on
     every `NODES`-family record, including the corpus carrier `plates.tied.k`
     whose four cells are `0.0` (the DA cells are now recorded and the override
     is named only when the deck states one — as is the `*SET_SEGMENT` A1/A2
     override on the SURFACE family, p.11-72 Remark 1); blank `NEN`/`MES` were
     printed as `0` although p.11-70 defaults them to `2`, making the reported
     criterion `(|fn|/NFLF)^0 + (|fs|/SFLF)^0 ≡ 2 ≥ 1`; the SURFACE family's
     warning printed the AUTOMATIC OPTION-5 sentence (a plastic yield stress
     and a crack-opening curve) for a keyword p.11-72 defines as plain tensile
     and shear failure stresses; and the self-tie refusal claimed a self-tie
     *"resolves to an EMPTY tie"* from `i2trivox.F90:234`, which only skips the
     segment a node is a CORNER of — the refusal's real grounds
     (`ERROR 556` at 20/21/22, self-welding at 27) are now what it states.
  10. Registry and id work the round turned up: `_solid_contact_master_pids`
      was a sixth walk of the contact containers that the first audit missed,
      so an implicit tiebreak deck lost the "RUN THIS DECK WITH np=1" warning
      although the tiebreak still builds the same `/SURF/PART/EXT`;
      `_report_unconsumed_gapmin` called a `/INTER/TYPE25`, tied or spot-weld
      id "unknown" although the `.rad` plainly contains it;
      `_warn_duplicate_inter_ids` matched `/INTER/SUB`, which
      `hm_read_interfaces.F:154` `CYCLE`s past **before** `NI = NI + 1` at
      `:156` so it never enters `IPARI` and never reaches the `ERROR 117` loop
      at `:229-234`; the tiebreak's secondary `/GRNOD` now draws from
      `next_grnod_id()` (the `ERROR 79` node-group guard) rather than
      `next_id()`; and the warning tag was built from the RAW header id, so a
      deck whose CID sits above 90000 had every log line name an id the `.rad`
      does not contain.
  11. **`/ANIM/NODA/DAMA2` is now emitted behind a rupturing tie.** The rupture
      warning told the reader to look at the per-node damage fringe, but
      `ruptint2.F:143/155/169` fill `PDAMA2` only under
      `ANIM_N(15)==1 .OR. H3D_DATA%N_SCAL_DAMA2 == 1` and the engine deck
      carried no such card, so half the advice was unactionable. Gated on a
      `Rupt = 2` interface existing, per the `#122` rule — with no rupturing
      tie the channel is legal, accepted and exactly 0.0 forever.

  **Solver evidence for the round** (short run dirs, `nt = 6`, all harvested
  and deleted). Both refusal guards were proven with a with/without twin at the
  starter, the "without" side produced by disabling the guard on a throwaway
  copy of the tree and restored afterwards: the ERROR-556 shape gives
  **4 × `ERROR 556` "MAIN NODE ID=5/6/7/8 IS ALSO SECONDARY NODE OF ANOTHER
  INTERFACE TYPE2" + ERROR TERMINATION** unguarded and **0 ERROR** guarded; the
  ERROR-670 shape **2 × `ERROR 670` + ERROR TERMINATION** unguarded and
  **0 ERROR / NORMAL TERMINATION** guarded. The `/ANIM/NODA/DAMA2` twin is the
  #122 check on the new card: with the pre-round engine deck the anim carries
  **no damage field at all** (`NODE_ID`, `Time_Step`, `Mass_Change` only);
  with it, `%damage(type2 interface) Normal` and `Tangent` appear and go
  **0 → 100** on the tied nodes at rupture. The emitted rupture coupon still
  reads back `SCAL_F 100.0 / DN_MAX 2.0E-02 / IFUNN 90013 / IFUNT 90014 /
  IMOD 2 / ISYM 1 / IFILTR 0` at **0 ERROR / 0 WARNING** and runs to
  **NORMAL TERMINATION at 2918 cycles** with `START RUPTURE` and
  `TOTAL RUPTURE` on all nine secondary nodes. Both carriers re-run clean:
  the Kurbel prime carrier `/INTER/TYPE2/10`, `FORMULATION LEVEL 27`,
  **0 ERROR(S)**, 4459 of 4540 secondary nodes deleted (81 tied, unchanged),
  and `plates.tied.k` **0 ERROR(S)**, `/INTER/TYPE2/90006`,
  `FORMULATION LEVEL 28`.

  **Round sweep, in two halves**, pre-round `cb49c70` vs this commit. Roster:
  the batch's own 827-deck roster, **deduplicated by content hash** (287
  byte-identical copies dropped — the corpus holds ~30 copies each of several
  models) and **capped at 3 MB per deck** → **456 decks**, 198 MB, 0 conversion
  exceptions on either side. The 84 unique decks over the cap are the gear-unit
  and thin-shell models; the one that matters, the 27.6 MB Kurbel prime
  carrier, was converted on BOTH trees separately and its `_0000.rad` and
  `_0001.rad` are **byte-identical**.
  * **Half 1 — the `.rad` files**: **0 of 456 differ** — *on this roster*. Not
    one corpus deck reaches the rupture path (the only tiebreak spelling in the
    corpus is `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK` at `OPTION 1`,
    a permanent tie), so none of the round's OUTPUT changes is visible here:
    the new `/ANIM/NODA/DAMA2` engine line, the companion `Fric` now routed
    through `_contact_friction`, and the `_MPP` `OPTION 4` interface the
    delegation fix recovers all move the `.rad` on a deck that does reach it —
    measured on the coupon twins and on the synthetic probe decks, not here.
    What the 0 of 456 does establish is the no-regression half: nothing the
    round touched moved a deck that was already converting.
  * **Half 2 — the diagnostics**: **1 of 456 differs**, and it is exactly the
    intended fix — `plates.tied.k` loses the clause *"the per-node override of
    NFLF/SFLF/NEN/MES through the \*SET_NODE DA1..DA4 attributes"*, because its
    `*SET_NODE_LIST 3` header is `3  0.0  0.0  0.0  0.0` and the deck states no
    override. (Its `NEN`/`MES` are an explicit `1`, so the new default does not
    touch it.) No deck gained a skipped keyword; none gained a
    duplicate-`INTERFACE ID` warning; `skipped_keywords` and
    `recognized_not_emitted` are identical on all 456.

### Added

- **MILESTONE-2 BATCH 2 — the cohesive `*CONTACT_..._TIEBREAK` family is a TIE,
  and the one OPTION class that states a release distance now RUPTURES.** All
  fifteen LS-DYNA spellings (×`_MPP`, ×`_ID`/`_TITLE` — 30 dispatch keys) reach
  a handler, against
  the four the old table listed by hand, and every one of them emits
  `/INTER/TYPE2` instead of the bond-less `/INTER/TYPE7` the four dispatched
  ones used to become. The keyword's own definition is the reason — Vol I R17
  p.11-9: *"TIEBREAK is a special case of a tied contact allowing failure in
  which the contact usually becomes a regular one-way, two-way, or single
  surface version after failure."* A penalty contact has no bond at all, so the
  joint's load path was missing **from t = 0**, not only after failure.

  MEASURED on the two carriers the corpus actually contains:
  `dynaexamples_r14_ton-mm-s/intro-by-k.-weimar/spotweld/spotweld-iv/plates.tied.k`
  carries `*CONTACT_TIEBREAK_NODES_ONLY`, the **only** joint between its two
  plates, and it was an unnamed entry in `skipped_keywords` — 8 warnings, 4
  `recognized_not_emitted` entries, and not one of them about the missing tie.
  It now emits `/INTER/TYPE2/90006` Spotflag 28. The prime carrier
  `getriebekette/wip_quang/…/319_rigid_bodies_plastic_feinseite_kurbel-super-fine-mesh.k`
  went from `/INTER/TYPE7/90001` (a sliding contact between two parts LS-DYNA
  sticks permanently) to `/INTER/TYPE2/10 "Kurbel self tiebreak contact"`,
  Spotflag 27, 4540 secondary nodes — **0 ERROR(S)** at the starter, the only
  warnings being the `1071` node-deletion notes the whole-part secondary side
  earns.

  1. **The mapping is decided by ONE fact about the two solvers, not by
     taste: OpenRadioss releases a `/INTER/TYPE2` tie on DISPLACEMENT and
     nothing else.** `ruptint2.F:138` (`Rupt = 2`) sets `IRUPT = 1` only when
     `|d_n| > Max_N_Dist .OR. d_t > Max_T_Dist`; the stress functions at
     `:130-136` merely CAP the transmitted traction
     (`FACN = MIN(1, |SIGNMAX/SIGN|)`) and set the *partial*-rupture state
     `IRUPT = -1`. There is no stress-triggered release anywhere in the code.
     So the only LS-DYNA OPTIONs whose failure can be converted are the ones
     that state a **distance** — 6 and 8, whose `PARAM` is exactly that:
     *"After the failure stress tiebreak criterion is met, damage is a linear
     function of the distance between points initially in contact. When the
     distance equals PARAM, damage is fully developed, and interface failure
     occurs"* (p.11-37). A constant traction cap with no `Max_N_Dist` would be
     a tie that is force-limited forever and never releases — legal, accepted
     by the starter, and the wrong physics.

  2. **OPTION 6/8 → the real rupture cards, term for term, with no invented
     factor.** `Max_N_Dist = Max_T_Dist = PARAM` (CCRIT) 1:1;
     `Fscalestress = NFLS`; the linear damage ramp as two synthesized
     `/FUNCT`s, `1 → 0` over `[0, CCRIT]` for the normal one and
     `SFLS/NFLS → 0` for the shear one (a ratio of two card cells, not a
     conversion factor); `Isym = 1`, which is `ruptint2.F:161-173` and gives
     *"compressive stress does not contribute to the failure equation"*
     — **on a coincident glue joint as well**. The Reference Guide p.213 says
     *"If the distance is zero (secondary node lies on the main surface), the
     rupture will be symmetric, even with Isym = 1"*, but the manual and the
     source disagree here and the source decides: `int2rupt.F:244` is
     `INORM = SIGN(1, NINT(VN·XSM))` and Fortran `SIGN(1,0)` is `+1`, not `0`,
     so a zero offset gives the same `INORM = +1` as the `Isym = 0` arm at
     `:246` while `ruptint2.F:162/164` keeps both compression gates armed. A
     zero offset only decides which side counts as opening, and for a solid
     main surface `insol3.F:167-175` orients that normal outward whatever the
     deck's node order. **MEASURED** on a coincident brick coupon (`NFLS = 100`
     over a 400 mm² bond, cap 40 kN): `Isym = 1` ruptured **9 of 9** nodes in
     tension at a capped 39.27 kN (−1.8 %) and **0 of 9** in compression, where
     the tie carried **3.76 MN = 94× NFLS uncapped**; the `Isym = 0` twin
     capped at 41.37 kN and ruptured in **both** directions — that arm is the
     control proving the compressive load reaches the branch. Reversing the
     main `*SET_SEGMENT` node order changed the rupture times not at all.
     `Rupt = 2` always.
     **VALIDATED on a coupon**: the starter
     echoes `SCAL_F 50.00000000000`, `DN_MAX 5.0000000000000E-03`,
     `IFUNN 90003 / IFUNT 90004`, `IMOD 2 / ISYM 1 / IFILTR 0` at 0 ERROR, and
     the engine prints `START RUPTURE` / `TOTAL RUPTURE` per node. The
     load-bearing measurement is the scaling twin: doubling `NFLS` from 50 to
     100 on an otherwise identical deck moved `START RUPTURE` from
     **6.60566149E-04 s to 1.32113230E-03 s — a ratio of exactly 2.000000**,
     which is what a 1:1 transfer into a linear-elastic ramp must give. Its
     `NFLS = 1e10` twin produced **no rupture event at all**, and the CCRIT
     twin (0.005 → 0.010) left the onset byte-identical while stretching the
     START→TOTAL interval from 4.28 µs to 46.6 µs.

  3. **`Rupt = 1` is never emitted, because it is dimensionally broken in this
     OpenRadioss build.** `ruptint2.F:147-150` normalises into `DIS_NA` and
     `DIS_T` and then evaluates `SQRT(DIS_N*DIS_N + DIS_T*DIS_T) > ONE` with
     the RAW, un-normalised `DIS_N` — a length added to a ratio, so the normal
     term ignores `Max_N_Dist` entirely. 2 is also the starter's own default
     (`hm_read_inter_type02.F:372`).

  4. **Every other OPTION class becomes a PERMANENT tie with a named
     warn-drop, and the drop text is different for the class that loses
     nothing.** `OPTION 1`/`−1` is *"tracked nodes in contact and those that
     come into contact will permanently stick"* with **no** failure criterion —
     it is not in Remark 3's list, and `NFLS`/`SFLS`/`ERATEN` are not in its
     field list either (p.11-38/39). Saying "the failure is DROPPED" there
     would state a fact the deck does not contain, so that class reports "that
     bond NEVER FAILS in LS-DYNA either" and names the one thing that really is
     lost: the *growing* tie set, since the starter fixes the tied pairs once.
     The same rule governs the per-cell inventory — `_TIEBREAK_FIELD_SCOPE`
     carries each Card-4 cell's own OPTION list, so on the prime carrier
     `NFLS 1000 / SFLS 1000 / ERATEN 1.0` are reported as **inert in LS-DYNA
     too, not lost**. (The `#130` lesson: an exclusion's stated reason needs the
     same audit as a warning's.)

  5. **The conformal-mesh trap is a conversion-time refusal, because there is
     no penalty flavour of the rupture tie.** `hm_read_inter_type02.F:343`
     gates the rupture cards on `Spotflag ∈ {20,21,22}` and `:301` gates the
     penalty `Stfac/Visc/Istf` card on `{25,26,27,28}` — **disjoint**. And
     `chktyp2.F:82` tags the secondary nodes of every TYPE2 *outside*
     25/26/27/28, with `:98-104` raising the hard `ERROR 556` for any MAIN node
     so tagged. MEASURED on two conformally adjacent bricks: Spotflag 5 and 22
     both gave **3 × ERROR 556 + ERROR TERMINATION**; 27 and 28 gave **0 errors
     and NORMAL TERMINATION**. So a tiebreak whose two sides share nodes falls
     back to the auto-penalty tie and says why. Three more refusals with the
     same shape: an implicit deck and a deck emitting `/DT/NODA/CST` (Reference
     Guide p.1947 Comment 6 forbids both for 20/21/22, and neither the starter
     nor the engine checks it), and a secondary side carrying no shell or solid
     (`i2surfs.F:287-292`, `ERROR 670` on a zero nodal area).

  6. **`NFLS`/`SFLS` = 0 is refused, not written.** *"Both NFLS and SFLS must be
     defined … If failure in only tension or shear is required, then set the
     other failure force to a large value (10¹⁰)"* (p.11-73 Remark 2) — the
     manual's own idiom for "no failure in this mode" is a huge value, never
     zero, so a 0 is a malformed card rather than a request. It also could not
     be written: `hm_read_inter_type02.F:373` turns `Fscalestress = 0` into ONE
     pressure unit, which would silently become a 1-MPa bond.

  7. **The post-failure contact is a COMPANION `/INTER/TYPE25`, and `Irem_i2`
     is the cell that makes it exist.** A totally ruptured secondary node is a
     completely free particle — `i2for10.F` has branches for `IRUPT == 0`
     (kinematic transfer) and `IRUPT == -1` (spring) and **no branch at all**
     for `IRUPT == 1` — so LS-DYNA's *"behaves as a surface-to-surface
     contact"* (p.11-39 Remark 1) needs a second interface. It is emitted with
     `Irem_i2 = 3` ("no change to secondary nodes"); at the `/DEFAULT` value 1
     the starter removes the TYPE2-tied nodes from it once and for all
     (`i7remnode.F:882-901`) and the card is legal, echoes correctly and does
     **nothing** — the `#118`/`#122` shape. MEASURED with/without on the
     emitted deck (break the tie, then drive the freed body back down at
     −20 mm/s): without the companion node 11 keeps the full **−20.0 mm/s** and
     sinks **0.0548034 mm** through the other body at 7.73 mJ of external work;
     with it, **−13.3090 mm/s** and **0.0364657 mm**, at 1439 mJ. `Inacti = 5`
     is what keeps it inert *before* failure. The `_ONLY` spellings get **no**
     companion — *"stops acting as a contact altogether"* (p.11-71/11-73
     Remark 3) is precisely the bare tie's own semantics, and bolting one on
     would contradict the keyword.

  8. **Two OPTION classes keep their old route on purpose.** `OPTION = 4`
     permits *"tangential motion with frictional sliding"* before failure, so
     LS-DYNA's own pre-failure state is not a tie and `/INTER/TYPE2` — which
     always inhibits tangential motion — would over-constrain it; it keeps the
     penalty contact and the normal bond is a named drop.
     `*CONTACT_AUTOMATIC_{SINGLE_SURFACE,GENERAL}_TIEBREAK` tie a surface to
     itself, which `/INTER/TYPE2` has no shape for: it takes a secondary
     `/GRNOD` and a SEPARATE main `/SURF`, and here the two would be the same
     node list. The rupture Spotflags are then a guaranteed `ERROR 556` — the
     tag `chktyp2.F:82` sets on the secondary nodes is checked at `:97-98` against
     the same interface's main nodes — while the auto-penalty Spotflag 27 would
     be accepted and then weld the part to itself, because `i2trivox.F90:234`
     excludes only the segment a node is a CORNER of, not the neighbouring
     segments of its own surface. They keep the self-contact route with the
     bond named as dropped.

  9. **`*CONTACT_TIEBREAK_SURFACE_TO_SURFACE[_ONLY]` is classified by LS-DYNA's
     own documented rewrite rule**, not by a guess: p.11-72 `THKOFF` — *"It
     works by substituting with `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK`
     (OPTION = 2 if TBLCID is not specified; OPTION = 5 if TBLCID is
     specified)"* — so one classification table serves all three Card-4 layouts.
     The `NODES` family gets the sentinel `option = 0` because its criterion is
     **force**-based, `(|fn|/NFLF)^NEN + (|fs|/SFLF)^MES ≥ 1`, with no OPTION
     counterpart at all; converting `NFLF` to `Fscalestress` would need each
     node's tributary area from `i2surfs.F`, which is mesh geometry the card
     does not carry, so it is named rather than fudged.

  10. **The `NFLS → Fscalestress` normalisation is EXACT for shells and
      mesh-dependent for solids, and that is stated rather than fitted.**
      LS-DYNA divides the tie force by the reference SEGMENT area; Radioss by
      the secondary node's own tributary area. For shells
      (`i2surfs.F:110,136`: `ΣA_quad/4 + ΣA_tri/3`) the two are the same
      quantity — a three-way probe on one mesh matched the prediction to
      **0.000 %**. For bricks `i2surfs.F:265-278` sums the three faces meeting
      at the node over 12, so the ratio to the tributary bond area `ab/4` is
      `(1 + t/a + t/b)/3` — exactly 1 for cubic elements (measured 5000.7 N
      against a predicted 5000.0), **2/3** at `t = a/2` (measured 0.6667), 1/3
      in the thin-plate limit. That factor is per-node mesh geometry, so `NFLS`
      goes through unchanged and the solid path warns.

  11. **Registry work this batch had to do, because a `*CONTACT` can now
      produce TWO interfaces for the first time.** `contacts_tiebreak` and the
      minted `companion_inter_ids` both join `_make_starter_th_inter`'s
      `all_inter_ids` (a missing id there is a missing `*DATABASE_RCFORC`
      channel for the entire post-failure load path). The two `/FUNCT`s come
      from `state.next_curve_id()`, which dodges the merged `/FUNCT` + `/TABLE`
      namespace (`ERROR 79`). And a new deck-wide
      `_warn_duplicate_inter_ids` scan closes the one id namespace that still
      had none — `ERROR 117 INTERFACE ID USED TWICE OR MORE`, the `#125`
      "per-id memo PLUS a deck-wide scan for every namespace" rule.

  **Corpus sweep, in two halves** (a sweep that compares only output files
  cannot see a warning change — #129 round 2). 783 decks: the repo's
  `ls-dyna_example`, all of `C:/openradioss_run` (Ryan-Lee examples included)
  and `dynaexamples_r14_ton-mm-s`, master `a1447e1` vs this branch, **0
  conversion exceptions on either side**.
  * **Half 1 — the `.rad` files** (SHA-256 of `_0000.rad` and `_0001.rad`):
    **34 of 783 differ.**
  * **Half 2 — the diagnostics** (`warnings` + `skipped_keywords` +
    `recognized_not_emitted`): **34 of 783 differ** — the same 34, none in only
    one half.

  Every mover accounted for, with arithmetic: **7 are tiebreak carriers**
  (`plates.tied.k` plus the six `getriebekette.k` `*INCLUDE` drivers of the
  Kurbel model), and **27 change in exactly one way — the deck's own
  `*CONTACT_*_ID` is preserved** where the butted-title header used to make it
  an auto-id (`90001 → 1`, `90002 → 100`, …). 7 + 27 = 34. No deck gained a
  duplicate-`INTERFACE ID` warning, and no deck gained a skipped keyword.
  Re-converting all 34 on the final HEAD reproduced the swept build
  byte-for-byte, and 40 sampled contact-carrying non-movers stayed identical to
  master.

  **The size cap, stated rather than left implicit.** 83 of the 866 decks
  found are over the 12 MB per-deck cap and were not swept — the Camry
  (248 MB), the four Yaris models (101–192 MB) and, relevant here, **37 copies
  of the Kurbel deck itself** (27.6 MB each; the `getriebekette.k` drivers that
  `*INCLUDE` them ARE in the 783 and did move). The prime carrier was converted
  separately instead, in 10.2 s, and starter-run: `/INTER/TYPE2/10 "Kurbel self
  tiebreak contact"`, `FORMULATION LEVEL 27`, **0 ERROR(S)**, 2 WARNING(S) —
  both `1071`, the whole-part secondary side's node deletions, which leave 81
  of 4540 nodes tied. That is **not** parity with the native reader, and the
  difference is the point of the batch: run through `hm_reader` + `dyna2rad`,
  the same file's `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_ID 10` comes
  back as `INTERFACE NUMBER : 10 / TYPE==25 MUTI-TYPE IMPACTING` — a plain
  contact, no `/INTER/TYPE2` anywhere in the `.out`, no `WARNING 1071` block,
  and therefore **zero tied nodes** (plus `WARNING 100213 … unsupported field
  exists at the end of line` on Card 4, which d2r never reads).
  `convertcontacts.cxx:117-126` is why: `AUTOMATIC_SURFACE_TO_SURFACE`
  substring-matches the `_TIEBREAK` spelling and routes it to `TYPE25`;
  only `TIEBREAK_NODES` reaches its `TYPE2` branch (`:183-189`), and no d2r
  branch fills a rupture slot at all. `plates.tied.k` likewise:
  **0 ERROR(S)**, `/INTER/TYPE2/90006` `FORMULATION LEVEL 28`,
  `SEARCH DISTANCE 2.4`.

  **What this corpus cannot see.** A census over the repo, `C:/openradioss_run`
  (including the Ryan-Lee examples), `dynaexamples_r14_ton-mm-s` and
  `E:/foxcore_data` found **exactly two carrier shapes**: nine copies of the
  user's own Kurbel model, all `OPTION 1`, and one
  `*CONTACT_TIEBREAK_NODES_ONLY`. There is **zero** occurrence of
  `AUTOMATIC_ONE_WAY_…_TIEBREAK`, of `TIEBREAK_SURFACE_TO_SURFACE`, of
  `TIEBREAK_NODES_TO_SURFACE`, and of any `OPTION ≠ 1` anywhere. Everything
  except the permanent-tie route and the `NODES_ONLY` disposition is therefore
  **synthetic-validation-only**: the evidence for it is the column-exact tests
  (built against the CFG `FORMAT` blocks field by field), the starter echo that
  reads those cards back, and the coupon twins quoted above. The one file a
  future census will find and should not re-open is
  `dynaexamples_r14_ton-mm-s/introduction/process_simulation/metal-forming-iv/275key2.k`,
  whose `TIEBREAK` lines are all commented out (`$*CONTACT_TIEBREAK_…`).

- **MILESTONE-2 BATCH 1, part A — the whole `*SET_<FAMILY>_ADD` boolean-union
  family: `*SET_NODE_ADD`, `*SET_SEGMENT_ADD`, `*SET_SHELL_ADD`,
  `*SET_SOLID_ADD`, `*SET_BEAM_ADD`, `*SET_DISCRETE_ADD` and
  `*SET_NODE_ADD_ADVANCED` (plus every `_TITLE` form) join the shipped
  `*SET_PART_ADD` on ONE shared, recursive resolver.** Six of the seven were
  unnamed entries in `skipped_keywords` before, and the loss was silent by
  construction: a `*BOUNDARY_SPC_SET` on a `*SET_NODE_ADD` produced no `/BCS`
  at all, and the converted deck then read **0 ERROR(S), 0 WARNING(S)** at the
  starter — an unconstrained model that looks clean. MEASURED on
  `dynaexamples_r14_ton-mm-s/implicit/Yaris Static Door Sag/000_yaris_stat_doorsag_fine_02.k`
  (`*SET_NODE_ADD 110 = {101, 102}`, both plain `*SET_NODE_LIST`): before,
  `*CONSTRAINED_NODAL_RIGID_BODY pid=110: node set 110 not found — /RBODY not
  emitted`, and with it went `BOUNDARY_PRESCRIBED_MOTION_RIGID pid=110: no
  RBODY found; motion skipped`, `LOAD_RIGID_BODY pid=110: rigid body not found
  – skipped` and the whole `*DATABASE_BNDOUT` channel. After: a
  `/GRNOD/NODE/110` of 25 nodes, `/RBODY` count 1268 → **1269**, the prescribed
  motion and the rigid-body load applied, and `*DATABASE_BNDOUT →
  /TH/NODE/94806`. Three dropped physics cards and one lost output channel,
  from one unexpanded set.

  1. **ONE resolver, not seven — and it is now RECURSIVE.**
     `writer/mesh._flatten_set_adds` walks a single family table
     (`state.SET_ADD_FAMILIES`) that also generates the parser keys
     (`handlers._set_add_keywords`) and the `*INCLUDE_TRANSFORM` offset rows
     (`assembly._OFFSET_SPECS`), so a guard added for one family cannot go dead
     on a sibling (the #124 lesson). The shipped `*SET_PART_ADD` expanded
     exactly ONE level and warn-dropped a nested `_ADD` child; that restriction
     is **lifted** — the reference implementation recurses without a limit and
     memoises to break cycles (`convertsets.cxx:1248-1277`), and the LS-DYNA
     `*SET` chapter states no nesting rule either way. k2rad adds an explicit
     cycle guard (the branch is cut, named, and the rest of the union kept) and
     a depth cap of 16 that WARNS and says it is a converter policy, not a
     manual rule. The cap is keyed on the subtree's intrinsic HEIGHT, not on
     traversal depth, so which unions the deck happens to number lower cannot
     decide whether it fires.

  2. **De-duplication is load-bearing for exactly one family.** `/GRNOD`,
     `/GRSHEL`, `/GRBRIC`, `/GRBEAM`, `/GRSPRI` and `/GRPART` all collapse
     duplicates inside the starter (`sysfus.F:468-479` for nodes,
     `nintrr.F:814-828` — "WITH REMOVAL OF DUPLICATE NOS" — for elements), so
     for six families the union's own dedup only matches what the solver does.
     `/SURF/SEG` and `/SURF/SURF` do **not**: measured with a free-floating
     `/PLOAD` impulse, the same four nodes on two seg rows applies exactly
     **2.0000×** the load at 0 ERROR (only `/SURF/DSURF` de-duplicates, and
     k2rad emits the flat `/SURF/SEG` form). A segment union therefore
     de-duplicates at conversion time, keyed on the smallest CYCLIC ROTATION of
     the corner list: a quad `1 2 3 4` and `2 3 4 1` are one segment with one
     normal, while the REVERSED `4 3 2 1` is the opposite face normal and is
     deliberately kept — dropping it would silently delete a load direction.

  3. **`*SET_TSHELL_ADD` is NOT a keyword and is not invented.** It is absent
     from the `*SET` chapter index of Vol I R17 *and* R16, and a full-text
     search finds it in neither; it exists only in HyperMesh's cfg pool
     (`Keyword971/SETS/tshell_add.cfg:60`, `data_hierarchy.cfg:165`). This is
     the "a cfg can lie about semantics" case (#115) in its strongest form — a
     cfg that defines a keyword the solver does not. Such a block stays in
     `skipped_keywords`, named. (`*SET_TSHELL` itself remains an open gap.)

  4. **Card 1 is NOT the same shape across the family, and each spelling's
     count comes from its own manual page.** `SID DA1 DA2 DA3 DA4 SOLVER` on
     NODE (p.43-45) and PART (p.43-57); `SID SOLVER` on SEGMENT (p.43-71) and
     SOLID (p.43-96); `SID` alone on SHELL (p.43-85), BEAM (p.43-8) and
     DISCRETE (p.43-18). Reading six cells on a SID-only family would take the
     following blanks as DA1..DA4. Only `*SET_PART_ADD`'s DA1..DA4 are
     recorded, because only they have a k2rad consumer (`*CONTACT_INTERIOR`);
     `*SET_NODE_ADD`'s are the `*CONTACT_TIEBREAK_NODES_TO_SURFACE` nodal
     attributes NFLF/NSFL/NNEN/NMES (p.43-43 Remark 1), a keyword k2rad does
     not convert.

  5. **`*SET_NODE_ADD_ADVANCED` is a union across seven families, not a
     boolean-operator table — and dyna2rad reads it wrong.** Card 2b is
     `SID1 TYPE1 … SID4 TYPE4`, four PAIRS (Vol I R17 p.43-46: "EQ.1: Node set
     EQ.2: Shell set … EQ.7: Thick shell set"); there is no operator column
     anywhere on the page, and the purpose line is still "define a node set by
     combining …". A non-node member contributes the NODES of its entities.
     dyna2rad matches the substring `"ADD"` (`convertsets.cxx:103`) and never
     dispatches on TYPE, so it feeds the TYPE column to `GetValue("ids")` as if
     it were another set id. k2rad reads the pairs; TYPE 7 (thick shell) is
     warn-dropped BY NAME because k2rad has no `*SET_TSHELL` container, and an
     undocumented TYPE is warn-dropped naming the value. A BEAM member
     contributes N1 and N2 only: its third node is an orientation reference,
     and on an `*ELEMENT_BEAM_ORIENTATION` beam k2rad SYNTHESIZES it, so
     including it would put a converter artefact into a set the deck defined.

  6. **Every member cell takes IDSOFF, not the base keyword's entity bucket.**
     LS-DYNA has exactly ONE set bucket — Vol I R17 `*INCLUDE_{OPTION}` Card
     2b.1/2b.2 (p.27-5/27-6) gives "IDSOFF: Offset to set ID" and no per-family
     split — so a `*SET_NODE_ADD` member row is `"s"` where a `*SET_NODE_LIST`
     member row is `"n"`. Getting that wrong is invisible on any deck without
     an `*INCLUDE_TRANSFORM`, which is why the offset rows are generated from
     the same family table as the parser keys. `*SET_NODE_ADD_ADVANCED` gets a
     hand-shaped spec instead: only the EVEN cells are ids, and an `(ALL, "s")`
     spec would offset every TYPE enumeration too. Trailing zero padding — the
     LS-PrePost house style, present in two corpus carriers — is never offset
     and never a member.

  7. **A union that resolves to NOTHING is not registered as an empty set.**
     Four `*SET_NODE_ADD` blocks in the 2010 Yaris and one in the 2012 Camry
     name `*SET_NODE_GENERAL` children k2rad does not convert. Registering an
     empty set there would claim the deck's union is empty when it is only
     unresolved here, and MEASURED on `starter_win64` (2026-05-20) an empty
     `/GRNOD/NODE` draws `WARNING ID : 690 ** WARNING IN NODE GROUP DEFINITION
     / THE NODE GROUP ID=… IS EMPTY` (0 ERRORS, NORMAL TERMINATION) — a
     diagnostic pointing at the wrong culprit. The union warns naming its
     unresolved members instead, and consumers report the id as undefined. A
     union that is a MEMBER of another union still resolves through the memo,
     so a chain is unaffected.

  8. **The gap-analysis claim that native "hard-rejects `_ADD` sets (msg
     200038)" is refuted as stated.** `convertsets.cxx` converts every `_ADD`
     kind; message 200038 is a WARNING emitted from exactly ONE site
     (`converttimehistory.cxx:125-129`), i.e. only for a
     `*DATABASE_HISTORY_<type>_SET` whose referenced set is an `_ADD` set.
     A `grep -rn 200038` over this build's reader tree returns nothing at all.
     The real converter-side gap was k2rad's, and it was measured above.

- **MILESTONE-2 BATCH 1, part B — `*MAT_COMPOSITE_DAMAGE` (MAT_022) →
  `/MAT/LAW25` (COMPSH) `Iform = 0` + `/FAIL/CHANG` on a shell-only material,
  `/MAT/LAW127` when any of its parts holds solids or thick shells.** The
  keyword was an unnamed `skipped_keywords` entry, and the deck it appears in
  did not run: MEASURED on
  `dynaexamples_r14_ton-mm-s/introduction/intro-by-a.-tabiei/tension/tension-vi/tension6.k`,
  the converted deck answered `ERROR ID : 179 ** ERROR IN PART DEFINITION
  (MATERIAL) / MATERIAL ID=1 DOES NOT EXIST` + `ERROR ID : 760` and the starter
  refused it (exit 3). That carrier now reads **0 ERROR(S), 1 WARNING(S)**
  (3030, the PTHICKFAIL note — its text names `PROPERTY ID 90013 IS A TYPE 11`
  here and `PROPERTY ID 90002/90003 IS A TYPE 51` on W6; see the *Ifail_sh* note
  below) and the engine runs it to **NORMAL TERMINATION over 20 807 cycles**,
  with the 90° plies of its `[0/90/0/90/90/0/90/0]` E-glass laminate failing
  first — 2400 events, all `FAILURE (CHANG) IN SHELL ELEMENT … MODE 3 -
  TENSILE MATRIX`, in layers 2, 4, 5 and 7 and in no other layer. That is the
  physically right mode as well as the right order: a 90° ply pulled along the
  laminate's direction 1 is loaded across its fibres and fails in transverse
  MATRIX tension, and the 0° plies survive.

  The native reader is not a fallback here: `dynamatlawkeywordmap.h:59` maps
  the keyword to law 22 but `convertmats.cxx` has **no `case 22:`**, so it
  reaches a `default:` whose `sdiString radiossOption = "/MAT/LAW" +
  OptionNumber;` (`convertutils.cxx:1011`) is C++ *pointer arithmetic on a
  string literal*, not concatenation. No `/MAT` is written at all and the
  `*PART`'s MID dangles.

  1. **The split is by ELEMENT KIND, and it is one router.**
     `writer/composites._mat022_law` decides; `_make_composite_materials`, the
     `/PROP` split and `mesh._target_mat_law` all read it, so the emitted law,
     the property class and every warning that names a law cannot disagree
     (the `_fabric_law` / `_seatbelt_mat_law` pattern). A MID can carry only
     ONE `/MAT` card — the `/MAT` id namespace is global across laws, starter
     ERROR 79 — so a material shared by shell and solid parts goes to LAW127
     whole, and the warning says which case it was.

  2. **Why solids may not go to LAW25.** Its solid kernels decouple direction 3
     entirely — `mat25_tsaiwu_s.F90:230` is `e3 = s3(i)/e33` and `:289`
     `s3(i) = e33*eps(i,3)`, with no `nu13`/`nu23` term anywhere — so PRCA and
     PRCB would be lost STRUCTURALLY, not merely dropped. And `/FAIL/CHANG`
     **cannot delete a solid at `/BEGIN 2022`**: `fail_changchang_s.F90:222`
     gates the whole relaxation/deletion path on `failip > 0`, and `Failip` is
     a 2023-only input column (measured: a 2022 deck carrying it draws
     `WARNING 100213 … unsupported field exists at the end of line` and reads
     it back as 0). LAW127 carries `E1/E2/E3`, `G12/G13/G23` and
     `nu21/nu31/nu32` and runs its own Chang-Chang criterion on both element
     kinds; its cost at 2022 is one cosmetic `WARNING 100211`, the same
     trade-off the shipped MAT_054/055 path runs under.

  3. **`/FAIL/CHANG` is the MAT_022 failure model, term for term.** With
     `ALPH = 0` — where LS-DYNA's `tau_bar = [t12²/2G12 + ¾αt12⁴] /
     [S12²/2G12 + ¾αS12⁴]` collapses to `(t12/S12)²`, a term-for-term
     identity, not an approximation — and `Beta = 1`,
     `fail_changchang_c.F90:155-181` reproduces Theory Manual R16 eqs
     23.22.3/.4/.5 exactly under `Sigma_1t = XT`, `Sigma_2t = YT`,
     `Sigma_12 = SC`, `Sigma_2c = YC`. **No conversion factor is needed and
     none is invented.** `Sigma_1c` is left BLANK: MAT_022 has no
     compressive-FIBRE mode and `hm_read_fail_chang.F90:102` turns a blank into
     infinity, i.e. exactly "that mode never trips" — the fabrication this
     project refuses is not required anywhere on the card.

     MEASURED end to end on a 10×10×1 quad built from the EMITTED cards
     (`/IMPDISP` ramp, `/TH/SHEL`): peak `sigma_xx = 2502.248 MPa` against the
     hand-computed onset `sigma_xx = XT = 2500` — **+0.0899 %**, inside one
     3.938 MPa TH sample — followed by a collapse to zero within 1.6e-6 s of
     the `Tau_max = 1e-7` relaxation window.

  4. **Three cells on that rider have no MAT_022 source, and all three default
     to a value that silently changes the physics.** `Beta` has no
     `if (beta == zero) beta = one` in the reader, so a blank one DELETES the
     shear term from the fibre criterion. A blank `Tau_max` becomes infinity
     (`:104`), `dmg_scale = exp(-(t-t_f)/Tau_max)` then stays 1 forever and the
     rider computes damage indices that soften and delete NOTHING — the #118
     "emitted and inert" trap. A blank `Ifail_sh` is 0, which gates the
     relaxation off entirely (`fail_changchang_c.F90:191`). So: `Beta = 1`;
     `Ifail_sh = 2`, which sets `pthkf = 1.0` and deletes the element only once
     EVERY layer has failed — the closest analogue of LS-DYNA zeroing a failed
     layer's moduli while the element survives (`Ifail_sh = 1` would delete on
     the FIRST failed layer, which LS-DYNA never does); and
     `Tau_max = 1e-4 × ENDTIM`, stated as a converter choice **with its number**
     in the warning. A deck with no `*CONTROL_TERMINATION` has no time scale to
     size it from, so the rider is emitted with `Ifail_sh = 0` and the warning
     says in as many words that it is then a damage INDEX with no stiffness
     loss.

  5. **Poisson: the two arms use OPPOSITE conventions and must never share a
     helper.** LAW25's `MAT_PRAB` is the MAJOR ratio — `read_mat25_tsaiwu.F90:
     129` reads it into `n12` and `:282` derives `n21 = n12*e22/e11` — so it
     takes the LAW93 rescale `NU12 = PRBA·EA/EB` (Vol II R17 p.2-262 Remark 3).
     LAW127 reads PRBA verbatim as the MINOR `nu21` and does the reciprocity
     itself (`hm_read_mat127.F90:127`/`:187`). Getting it backwards is SILENT
     on both: LAW25's only guard is `detc = 1 − n12·n21 ≤ 0 → ERROR 307`, and
     raw PRBA only makes `detc` larger. Measured on the corpus carrier:
     `0.0557 × 38600/8270 = 0.2600`, which the starter echoes as
     `POISSON'S RATIO N12 = 0.2600E+00`; the raw 0.0557 would be wrong by the
     factor `EA/EB = 4.667`.

  6. **Two LAW127 defaults would INVENT physics and are neutralised.** `YCFAC`
     defaults to **2** (`hm_read_mat127.F90:287`) and `sigeps127.F90:289` then
     runs `xc(i) = ycfac*yc(i)` once matrix compression has failed — giving
     MAT_022 a compressive-FIBRE limit of `2·YC` (50 MPa on the W6 corpus
     deck) that it does not have. And a blank `SLIMT1/SLIMT2/SLIMSC/SLIMC1/
     SLIMC2` becomes **1.0** (`:289-293`), which `sigeps127c.F90:400-403` then
     uses to clamp the failed mode's stress at `1.0 ×` its FULL strength — a
     perfect-plastic plateau at the failure stress, i.e. a failure model that
     is emitted, accepted and completely inert. MAT_022 zeroes the failed ply's
     moduli, so both are written explicitly (`1e18` and `1e-8`), and the
     starter echo confirms them.

  7. **Named warn-drops:** `KFAIL` (bulk modulus of the failed material — no
     slot on either law), `MACF ≠ 1` (axis swap, no `/PROP` column),
     `ATRACK = 1` (the a-axis follows the DEFORMED line; Radioss's `Ip`/`IREP`
     selects a storage frame, not deformation tracking), `SN`/`SYZ`/`SZX` (the
     solid delamination criterion `(max(0,σ3)/SN)² + (τ23/SYZ)² + (τ31/SZX)²`,
     Theory eq 23.22.140) and `ALPH` on the shell arm. `/FAIL/HASHIN` has
     similarly named `Sigma_3t`/`Sigma_23`/`Sigma_13` slots but implements
     Hashin's quadratic delamination — a different formula on different
     strengths — so it is deliberately **not** substituted. The report runs
     from a helper both arms call, so a field cannot be lost on one of them.

  8. **A guard gated on two card spellings, found and fixed.**
     `_type11_carries` tested `own in state.mat_orthotropic or own in
     state.mat_enhanced_composite`, so a MAT_022 shell fell through to
     `/PROP/TYPE51` + per-ply `/PROP/TYPE19` even though `hm_read_prop11.F`
     names law 25 in its own whitelist ("PLEASE USE ONE OF THE FOLLOWING
     COMPATIBLE MATERIAL LAWS: 15,25,27, OR > 28"). Same class as the
     `_resolve_icomp_sections` membership test, which would otherwise have
     reported the `tension6.k` `[0/90/0/90/90/0/90/0]` layup as DROPPED. Both
     now list the container; `writer/composites.py`'s two-arm law LABEL became
     a three-way router for the same reason.

- **Sweep for MILESTONE-2 BATCH 1, in TWO HALVES** — re-run against the FINAL
  branch, so these numbers describe the code that ships. The corpus (this
  repo's tests, the r14 dynaexamples, `C:\openradioss_run`, `E:\foxcore_data`,
  all four present) holds **906** `.k`/`.key`/`.dyn` files, **586 distinct by
  SHA-256 within a 90 MB per-file cap** — converting the same bytes twice
  proves nothing. **584 of them were converted on master and on this branch
  and compared; 0 conversion errors on either tree.**

  Not in that roster, and why: 13 files above the cap (four 190-250 MB Yaris /
  Camry meshes, six 108-196 MB foxcore meshes, the 169 MB
  `yaris-detailed-v2j.key`, the 111 MB door-sag Yaris and the 101 MB roof
  crush), and the two vehicle `combine.key` `*INCLUDE` masters, each of which
  pulls a >160 MB child. An **exhaustive keyword scan of all 906 files** puts
  every batch carrier on the record: `*MAT_COMPOSITE_DAMAGE` in 5 files
  (`tension6.k` + four `W6` copies), `*SET_NODE_ADD` in 3
  (the door-sag Yaris, `show-cases/contact-overview/main.k`, the getriebekette
  `Model-318_Achshebel-fein_tobi.k` in its `_TITLE` spelling), and
  `*SET_NODE_ADD` + `*SET_PART_ADD` in the two `combine.key` masters. **Zero
  `*SET_SEGMENT/SHELL/SOLID/BEAM/DISCRETE/TSHELL_ADD` and zero
  `*SET_NODE_ADD_ADVANCED` exist anywhere in the corpus** — those, and the
  negative-range form, are synthetic-validation only. The door-sag Yaris was
  converted separately on both trees (below); the two `combine.key` masters
  carry only POSITIVE `_ADD` member ids (checked in the source), so nothing in
  this round can move them beyond the `#-- SKIPPED:` line the first cut
  measured.

  Compared **explicitly in two halves and reported as two numbers**, because a
  sweep that compares only output files cannot see a warning change (#129
  round 2):

  * **Half 1 — the `.rad` files** (SHA-256 of `_0000.rad` and `_0001.rad`):
    **22 of 584 differ.**
  * **Half 2 — the diagnostics** (`warnings` + `skipped_keywords` +
    `recognized_not_emitted`): **8 of 584 differ.**

  Six decks are in both halves, **two are in half 2 only** and **sixteen are in
  half 1 only** — the two halves genuinely see different things:

  * **Both halves (6):** `tension6.k` (loses `MAT_COMPOSITE_DAMAGE` from
    `skipped_keywords`, +3 warnings: the `/FAIL/CHANG` note, the
    PRCA/PRCB drop and the `/PROP/TYPE11` + `/SKEW` notes, and it stops
    reporting its 8-ply `ICOMP=1` layup as DROPPED); the three `W6` sandwich
    decks (same, +1); `show-cases/contact-overview/main.k` and the
    getriebekette `Model-318_Achshebel-fein_tobi.k` (lose `SET_NODE_ADD` from
    `skipped_keywords`; `main.k` gains the two named warnings for a union whose
    `*SET_NODE_GENERAL` children k2rad still cannot resolve, `Model-318` gains
    its `/GRNOD` and no warning at all).
  * **Half 2 only (2):** `contact-foam/matfoamsoil.k` and
    `contact-rubber/matrubber.k`, whose `.rad` is byte-identical and whose only
    change is the corrected TEXT of an existing warning —
    `*DATABASE_NODAL_FORCE_GROUP` used to name `*SET_NODE_ADD` as a spelling
    k2rad does not expand and now names `*SET_NODE_GENERAL`, which it still
    does not. Exactly what half 1 alone would have hidden.
  * **Half 1 only (16):** ten `W13` blast decks and six `W8` CrushBox decks,
    all from the `*SET_SEGMENT` triangle canonicalisation — they write their
    triangles as `n1 n2 n3 n3` and now emit `n1 n2 n3 0`. **Both families are
    solver-validated paths and both were re-validated:** starter on master and
    on the branch gives 0 ERROR / 4 WARNING (W13) and 0 ERROR / 21 WARNING
    (W8) on each tree, the `.out` echoes are identical line for line, and the
    restart files — 107 889 661 bytes for W13, 13 157 936 for W8 — differ in
    exactly **6 bytes each, all in the trailing timestamp record**. The starter
    builds the identical model, exactly as `hm_read_surf.F:318-321`
    (`IF(N4/=0) … ELSE N4 = N3`) says it must.

  **Door-sag Yaris, converted separately on both trees** (111 MB,
  `implicit/Yaris Static Door Sag/000_yaris_stat_doorsag_fine_02.k`):
  `/GRNOD/NODE/110` goes from absent to present with its 25 nodes, `/RBODY`
  1268 → **1269**, and four warnings disappear —
  `*CONSTRAINED_NODAL_RIGID_BODY pid=110: node set 110 not found — /RBODY not
  emitted`, `no RBODY found; motion skipped`, `rigid body not found – skipped`
  and `*DATABASE_BNDOUT requested but this deck drives no node …`, the last
  replaced by `*DATABASE_BNDOUT → /TH/NODE/94806`.

- **MILESTONE-2 BATCH 1, post-review round — ten confirmed defects, two of
  them changing physics silently.** Each was re-derived from the manual or the
  starter/engine source before it was touched, and each has a regression test
  that fails on the old behaviour.

  1. **`/MAT/LAW25`'s `alpha` cell was left at 0, which made the "elastic
     carrier" elastic only in MPa-like unit systems.**
     `read_mat25_tsaiwu.F90:273` turns a blank or zero `alpha` into **1**, and
     `:315` then gives the Tsai-Wu interaction coefficient
     `f12 = -alpha/(2·sqrt(min(1e20, σ_y⁴))) = -5e-11` beside
     `f11 = f22 = 1e-20`. `ft1 = f11·f22 - 4·f12²` is NEGATIVE — the surface is
     an open hyperbola, not the closed ellipse the six 1e20 yields assume — and
     in any tension-compression state the cross term `2·f12·s1·s2` dominates
     and reaches `fyld = 1` at `|σ| ≈ 1e5` **in the deck's stress unit**
     (`mat25_tsaiwu_c.F90:481-487`). 1e5 MPa is unreachable; 1e5 Pa is 0.1 MPa,
     and 1e5 psi is 690 MPa. MEASURED on twin decks differing in that ONE cell
     (single shell, every nodal DOF prescribed, `eps_xx = +1e-3` /
     `eps_yy = -1e-3`, starter+engine 2026-05-20, 0 ERROR / NORMAL TERMINATION
     on all four): in **kg-m-s** the `alpha = 0` arm recorded **ZERO**
     `FAILURE (CHANG)` events and I-ENERGY 4.651e-3 J, the `alpha = 1e-20` arm
     the four the criterion calls for and 5.232e-3 J — which is what the
     Mg-mm-s twin gives in BOTH arms (5.232 mJ), so the fix also makes the two
     unit systems agree to four figures. Without it a Pa- or psi-unit ply
     plastifies on a spurious surface from the first cycle and the whole
     `/FAIL/CHANG` rider — the entire point of the LAW25 arm — never trips.
     `alpha` has exactly two consumers in the reader (this formula and the echo
     at `:452`), and the starter now echoes `F12 REDUCTION FACTOR =
     1.0000000000000E-20` / `F12 = -0.5000E-30` on the W6 carrier. Both corpus
     carriers are ton-mm-s and are numerically unchanged.

  2. **`*PART_COMPOSITE` discarded a MAT_022 ply's AOPT with no diagnostic at
     all.** `_emit_part_composite` picks the layup's orthotropy system from the
     "first ORTHOTROPIC ply material", testing `mat_orthotropic` and
     `mat_enhanced_composite` only — the ONE walk of the three composite
     containers that the batch missed (`tshell._AOPT_MAT_DICTS`,
     `_emit_composite_props` and `_composite_ref_axis` all had it). A MAT_022
     ply therefore left `axis` at the `Ip=20` default and no `/SKEW` was
     written, and on master the same deck was REFUSED outright (ERROR 179), so
     the batch turned a loud failure into a silent wrong answer.

     **`Ip=20` is the ELEMENT frame, not global X** — material direction 1 is
     the element's own N1→N2 edge, and the `Vx Vy Vz` cell written beside it is
     inert. Measured on a two-run twin differing ONLY in the connectivity
     (same nodes, same AOPT, same loading, same BCs): with N1→N2 along global
     +X the pre-fix run measures `a11`, with the same quad respelled 2-3-4-1 it
     measures `a22`. So the fallback follows the mesh, and the reach is not
     "decks whose `a` is not global X" — it is every deck whose element edges
     do not happen to line up with `a`.

     Reach on the **W6** sandwich carrier's `*PART_COMPOSITE` 12 and 13
     (4 MAT_022 plies each, layup `[0/90/45/-45]` at 1.0 mm per ply): the
     element N1→N2 axis sits at a **median 49.07° / 49.20°** to the in-plane
     projection of the plies' `a = (1,0,0)`, and 2819 of 3078 / 2793 of 3059
     quads are more than 1° off. What that costs is layup-specific, and W6's
     layup is the forgiving one: `[0/90/45/-45]` equal-thickness is
     **quasi-isotropic in-plane**, so its `A` matrix is invariant under any
     rotation of the reference frame — `A11/h = A22/h = 79 401`, `A12/h =
     35 037`, `A16 = 0` at 0° and at 49° alike (CLT with the reader's own
     `nu12 = PRBA·EA/EB = 0.4333`, `detc = 0.935`). The MEMBRANE answer on W6
     really is unchanged. The bending and per-ply answers are not: the stack is
     unsymmetric, `D11` drops from 514 382 to 320 607 (**−37.7 %**) over that
     49° rotation, and under a unit global `eps_xx` the fibre stress moves from
     the 0° ply to the 45° ply (`sig_1` 129.8 → 32.6 on the former, 44.7 →
     129.0 on the latter) — i.e. which ply reaches a Chang-Chang index first
     changes completely. For a sandwich IMPACT deck that is the part that
     matters, so the pre-fix W6 answer was wrong, not merely undiagnosed.

  3. **The two documented spellings of a triangular `*SET_SEGMENT` were two
     different segments.** Vol I R17 p.43-63 verbatim: *"N4 — Nodal point n4.
     To define a triangular segment, set N4 = N3."* — while a trailing blank is
     the other house style, and `hm_read_surf.F:318-321`
     (`IF(N4/=0) … ELSE N4 = N3`) makes them one face inside the starter.
     `handle_set_segment` popped only trailing ZEROS, so `1 2 3 0` was stored
     as `[1,2,3]` and `1 2 3 3` as `[1,2,3,3]`, and `_segment_key` — the one
     de-duplication this batch calls load-bearing — keyed them apart. MEASURED
     on a free-floating plate with `*SET_SEGMENT 30` = `1 2 3 0`,
     `*SET_SEGMENT 31` = `1 2 3 3`, `*SET_SEGMENT_ADD 32 = {30, 31}` and a
     `*LOAD_SEGMENT_SET` on it: the emitted `/SURF/SEG` carried BOTH rows, and
     against the one-row twin (identical in every other byte, both runs
     0 ERROR / NORMAL TERMINATION / 67 cycles) EXT-WORK went 18.35 -> 73.39 and
     K-ENERGY 17.68 -> 70.73 — a factor of **4.0005**, i.e. impulse x**2.0001**:
     the pressure on that face applied exactly TWICE. Both spellings now collapse at
     PARSE time, so every consumer sees one — the same normalisation
     `_shell_load_segments` (`writer/loads.py:4415`) already applied on the
     `*LOAD_SHELL` path, and it is applied to `*LOAD_BLAST_SEGMENT`'s inline
     segments too. Scope, stated exactly: the collapse makes the two SPELLINGS
     one segment. It does not de-duplicate a face a single `*SET_SEGMENT` block
     genuinely lists twice — two identical rows still emit two `/SURF/SEG` rows
     and the pressure still lands twice, which is what LS-DYNA does with them.

     This is the one fix in the round that moves `.rad` bytes on decks that
     have nothing to do with `_ADD` sets: the ten **W13 blast** corpus decks
     (11 distinct-by-SHA256 `W13*.k`, less the mesh-only
     `W13_INITIAL_VehicleMesh.k`) write their `*SET_SEGMENT` triangles in the
     `n1 n2 n3 n3` spelling, so on the `W13_SETUP_BlastVehicle` carrier 370
     `/SURF/SEG` rows change from `… n3 n3` to `… n3 0` — counted independently
     in the SOURCE deck, 370 of its 33 420 `*SET_SEGMENT` rows carry
     `n4 == n3`. **Re-validated on that
     solver-validated path**: starter on both trees, 0 ERROR / 4 WARNING(S)
     each, `.out` echoes identical line for line except the reported free-RAM
     figure, and the two 107 889 661-byte `_0000_0001.rst` restart files differ
     in exactly **6 bytes, all in the trailing timestamp record** (offsets
     107 889 654…659). The starter builds the identical model, exactly as
     `hm_read_surf.F:318-321` says it must.

  4. **`*SET_PART_ADD`'s negative RANGE form was silently dropped.** Vol I R17
     p.43-57 gives `PSID[N]` two readings: *"GT.0: PSID[N] is added to SID,
     LT.0: All part sets with ID between PSID[N-1] and -PSID[N], including
     PSID[N-1] and -PSID[N], will be added to SID"*, with p.43-58 requiring
     `PSID[N-1] > 0` and `|PSID[N]| >= PSID[N-1]`. So `… 5, -9` means part sets
     5..9; the shared `if v > 0` member filter kept 5 and dropped 6..9 with no
     word (and the batch's new docstring explained that filter as trailing-zero
     padding only, documenting the range form out of existence). The parser now
     keeps a non-zero cell and `writer/mesh._expanded_member_ids` resolves the
     range where every child set is known. Checked against the R17 text
     family by family: the NODE, SEGMENT, SHELL, SOLID, BEAM and DISCRETE
     `_ADD` pages carry **no** `GT.0`/`LT.0` block at all, so a negative cell
     there is warn-dropped BY NAME rather than guessed at. The
     `*INCLUDE_TRANSFORM` side gets the matching sign-preserving rewriter —
     `_rewrite_line` touches only `v > 0`, which would have left a range
     endpoint behind while its start moved with `IDSOFF`.

  5. **A deep chain of nested unions raised `RecursionError` instead of hitting
     the depth cap.** The cap is an INTRINSIC-HEIGHT cap — deliberately so, or
     a deck's set numbering would decide whether it fires — and a height can
     only be evaluated bottom-up, so the walk must reach the end of a chain
     before the cap can act. MEASURED: 400 links survived, 800 aborted
     `convert()` with a traceback, and whether it aborted depended on whether
     the ids ascended or descended. The traversal is now an explicit stack;
     the docstring's "keeps a pathological input from costing unbounded work"
     is corrected to what the cap actually does.

  6. **Every diagnostic for a `*SET_NODE_ADD_ADVANCED` block named
     `*SET_NODE_ADD`.** The two spellings share one id namespace and one
     resolver, and five messages (cycle, depth cap, dangling member, direct-set
     collision, empty union) were formatted with the family keyword — so a
     reader grepping the deck for the card the warning names finds nothing.
     Each message now takes the spelling its own sid was written with.

  7. **`_advanced_members` raised its drop diagnostics with a bare
     `state.warn`.** A cycle-cut subtree is deliberately NOT memoised, so an
     ADVANCED union inside a cycle is re-expanded and re-reported — measured,
     the same "member set id(s) … carry TYPE=7" line twice. It now goes through
     the resolver's `warn_once`, keyed on the sid its text names (the #129
     round-2 rule the module's own comment cites).

  8. **`ConversionState.all_mat_ids()` did not list `mat_composite_damage`**,
     so the new family was invisible to every consumer of that registry: the
     `*PART_COMPOSITE` "ply material N is NOT emitted as a /MAT" warning fired
     FALSELY on correct decks (twice on the W6 carrier), `seatbelts._belt_mat_ids`
     would keep a MAT_022 MID for a synthesized `/MAT/LAW114` (starter ERROR 79
     DUPLICATE ID, measured), and `next_mat_id()` could mint a synthesized
     material onto a live MAT_022 MID at or above 90001. The `#120`
     "audit every registry walk" class. Two sibling walks in `writer/thermal.py`
     got the same treatment: `_is_anisotropic` now knows the family (so the
     LCIDY/LCIDZ loss on a `*MAT_ADD_THERMAL_EXPANSION` is reported), and
     `_material_registries` NAMES it in the "deliberately not here" list —
     MAT_022's shell arm writes a `/FAIL/CHANG` keyed on the same mid, so a
     bare record copy would leave the failure model behind, exactly the
     `mat_laminated_glass` situation.

  9. **The `*DAMPING_FREQUENCY_RANGE` element-scope guard went dead on LAW25.**
     `mulawc.F90:1963/1972` skips `prony_modelc` AND `damping_range_shell`
     whenever `ilaw == 25`, and the existing warning's own text already said so
     — but its condition was "the part carries no shell or solid element", and
     a MAT_022 shell part is meshed. It came out completely undamped in
     silence. The #124 "a guard gated on one condition goes dead on its
     sibling" class, found by auditing the new law against every walk that
     reasons about materials.

  10. **Both arms of the MAT_022 split refused DIFFERENT degeneracies of the
      same card** — the #129 rule, found by asking what the other arm does with
      each guard the first one has. Two guards were one-sided:
      * A ZERO elastic constant. `/MAT/LAW25` refuses `e11/e22/g12/g23/g31` at
        or below zero (`ancmsg(msgid=306)`,
        `read_mat25_tsaiwu.F90:193-199`) and only SUBSTITUTES `e33`
        (`:201`, `max(e11,e22)`) — k2rad warned about all five.
        `hm_read_mat127.F90` has **no** zero-modulus guard at all: `:178-182`
        substitutes `e2 = e1`, `e3 = e2`, `g13 = g12`, `g23 = g13`, and `e1`
        itself is never checked, so a zero EA reaches `c11 = one/e1` at `:226`
        unguarded. The arm that said nothing was the dangerous one.
      * `1 - NU12·NU21 <= 0`. The two arms write the Poisson slot with opposite
        conventions, but the reader ends up with `nu12 = nu21·e1/e2` either way
        (`read_mat25_tsaiwu.F90:282` / `hm_read_mat127.F90:187`), so
        `1 - PRBA²·EA/EB` is the same number on both and rejects the material
        on both — ERROR 307 on LAW25, ERROR 3068 then 307 on LAW127. Only the
        LAW25 arm checked it. Both checks now live in helpers `_emit_mat022`
        calls before it dispatches.

  Also corrected, without changing behaviour: `Ifail_sh = 2`'s stated rationale
  (the 1-vs-2 half of it is INERT on the layered shell properties MAT_022
  actually reaches — `check_pthickfail.F:121-128` fires WARNING 3030 and
  `fail_setoff_c.F:268-272` compares against the PROPERTY's `P_THICKG`, which
  k2rad writes as 0 and `hm_read_prop11.F:201` turns into `1-1e-6`, the same
  threshold; what IS load-bearing is the flag being positive and below 3, and
  the warning now names the 3030 as expected); `PRCA`/`PRCB` are added to the
  named drop list on the LAW25 arm (LAW25 has one Poisson slot, and the
  LAW127-selection note that mentioned them only reached decks where they are
  NOT lost); `_mat022_law` now also scans `*PART_COMPOSITE` plies, because
  `state.parts` carries only the FIRST real ply's MID and a MAT_022 in a later
  layer of a `*PART_COMPOSITE_TSHELL` was routed to LAW25 on a thick shell;
  and two tests that could not fail were replaced — `_LAW127_NO_RESIDUAL` was
  asserted `< 1e-6`, which `0.0` satisfies and which is exactly the value the
  reader turns back into 1.0, and the Chang-Chang onset test plugged the
  emitted strengths back into their own identity.

  **The two measured claims that were misquoted are corrected against a rerun**
  (`tension6.k`, 0 ERROR / 1 WARNING, NORMAL TERMINATION, 20 807 cycles): the
  2400 failure events are `MODE 3 - TENSILE MATRIX`, not `MODE 1 - TENSILE
  FIBER` — the 90° plies (layers 2, 4, 5, 7 and no others) are loaded across
  their fibres — and WARNING 3030 names `PROPERTY ID 90013 IS A TYPE 11` there
  and `TYPE 51` on W6, not "the TYPE51 note".

- **MILESTONE-2 BATCH 1, verification round — one false diagnostic the review
  round introduced, five losses that were silent or wrongly explained, and
  four documentation claims that were not true.** Everything here was
  re-derived from the manual or the starter/engine source before it was
  touched, and each of the ten code changes has a regression test that was
  mutation-checked (11 planted reversions, 11 caught).

  1. **A `*SET_PART_ADD` range that spans the union's OWN id drew a false
     "this union is reached from itself" warning.** `_expanded_member_ids`
     resolved the range against every part set the deck defines — including
     the union itself — so `*SET_PART_ADD 7` with members `5, -9`, and the
     "select everything" idiom `1, -99999`, made the union a member of itself.
     The MEMBERS were always right (a union with itself is a no-op); the
     message was not, and it told the engineer to "fix the deck" on a deck
     Vol I R17 p.43-57 declares legal. Second-order: the cycle guard set
     `cyclic = True`, which propagates up through `absorb` and barred that
     union and every union above it from the memo. The union's own id is now
     excluded from its own range, exactly as the range's start already was. A
     genuine cycle reached THROUGH a range is still cut and named. MEASURED
     two-tree on a valid probe — the review round's own `rv_rngSelf.k` cannot
     see this, because it also defines a `*SET_PART_LIST 7`, so the
     direct-set-collision branch short-circuits the expansion before the range
     is ever resolved — `_0000.rad` SHA-256 identical on both trees, warning
     present at HEAD and gone here. Diagnostic-only, so no solver re-run.

  2. **`*SET_NODE_ADD_ADVANCED` dropped a NEGATIVE member id silently** while
     the review round had just made every plain `_ADD` family warn by name for
     the same cell. Dropping is right — Vol I R17 p.43-46 gives card 2b's
     `SID[N]` no `GT.0`/`LT.0` reading — but only an exact ZERO is padding, and
     the parser's `if sid > 0` conflated the two.

  3. **A MAT_022 in layer 2..n of a `*PART_COMPOSITE` was invisible to two
     more walks.** The review round fixed the AOPT walk this way; the same
     `state.parts[pid].mid` blind spot (a composite part's fallback `PartData`
     carries only the FIRST real ply's MID) was still in
     `loads._make_damping_frequency_range`'s LAW25 arm — so a MAT_022 ply
     inside a `*DAMPING_FREQUENCY_RANGE` scope came out COMPLETELY UNDAMPED
     with no note (`mulawc.F90:1972` excludes `ilaw == 25`) — and in
     `_emit_mat022_law127`'s `mixed` test, which made the LAW127-selection note
     say "its parts hold SOLID or THICK-SHELL elements" on a MID that is in
     fact shared with a shell part. Both now go through one helper,
     `composites._part_mat_mids`.

  4. **A BLANK card-5 strength produced a completely INERT `/FAIL/CHANG` while
     the note beside it affirmed the criteria are LS-DYNA's "term for term …
     with NO conversion factor".** `hm_read_fail_chang.F90:99-104` substitutes
     `infinity` (= 1e20, `constant_mod.F:521`) for every exact zero, so a blank
     `XT`/`YT`/`YC`/`SC` is not carried and not defaulted — the mode it gates
     is switched off. With all four blank the emitted row is `0 0 0 <blank> 0`,
     the starter reads it without a murmur and nothing can ever trip. Now named
     per cell, with the mode each one kills, on BOTH arms —
     `hm_read_mat127.F90:279-284` runs the identical `if (x == zero) x = ep20`
     line — and the "term for term" clause is qualified when any cell is zero.
     This is the #122 class the batch already names for `EC → max(E11,E22)`,
     `XC → 1e20`, `SLIM* → 1.0` and `alpha → 1`.

  5. **`ERROR 306` was overstated as "at or below zero", and a NEGATIVE modulus
     was screened by neither side.** `read_mat25_tsaiwu.F90:193-199` tests
     `== zero` exactly (contrast `:201`, `if (e33 <= zero)`), so a negative
     `EA` walks straight past it into `c11 = 1/e1` — and k2rad's own guard read
     `v == 0.0`. The docstring and the warning now say EXACTLY zero, and a
     negative modulus gets its own message on both arms.

  6. **`thermal._material_registries` excluded `*MAT_COMPOSITE_DAMAGE` on a
     FALSE cited fact, and printed that fact to the user.** The stated reason
     was that MAT_022's shell arm "writes a companion `/FAIL/CHANG` keyed on
     the SAME mid, so a bare record copy would leave the failure model behind".
     It does not: `_emit_fail_chang` writes `f"/FAIL/CHANG/{mat.mid}"` FROM the
     record it is handed, so the rider is GENERATED for the clone and follows
     it. So a convertible `*MAT_ADD_THERMAL_EXPANSION` was being dropped with a
     reason that is not true. The family is now in the registry (verified
     end-to-end: a deck with parts 100/101 on MAT_022 mid 7 and the expansion
     on one of them emits `/MAT/LAW25/7 + /FAIL/CHANG/7`,
     `/MAT/LAW25/90001 + /FAIL/CHANG/90001` and `/THERM_STRESS/MAT/90001`), the
     refusal warning names four producers instead of five, and
     `_structural_density` gains a MAT_022 `rho`.

     The two remaining exclusions were re-checked against their emitters rather
     than taken on the same trust, and both hold for reasons now stated
     precisely: `_emit_mat_law5` looks its JWL up in `state.eos_jwl.get(mid)`,
     a SECOND dict keyed by the OLD mid that a record copy does not bring — the
     clone would come out with no `/EOS`; and `_emit_mat_law27_pair` writes one
     card under `mat.mid` and one under the record's own reserved `glass_mid`,
     which a copy KEEPS — so the clone would write a duplicate
     `/MAT/LAW27/{glass_mid}` and hit starter ERROR 79. "Generated from the
     record", "looked up in a second dict" and "a second id travelling on the
     record" are three different answers, and only the first is safe to clone.

  7. **Documentation and test hygiene.** `handlers.py` and `CHANGELOG.md` cited
     `_shell_segment_rows`, which does not exist — the function is
     `_shell_load_segments` (`writer/loads.py:4415`). `CHANGELOG.md` contradicted
     itself on the W13 count (five vs ten; the corpus holds 11 distinct-by-SHA256
     `W13*.k`, one of them the mesh-only `W13_INITIAL_VehicleMesh.k`, so ten,
     and the 370-row figure is per-carrier — counted independently in the source
     deck: 370 of 33 420 `*SET_SEGMENT` rows have `n4 == n3`). The
     `*LOAD_BLAST_SEGMENT` half of the triangle canonicalisation had NO test —
     mutation-checked, reverting it left the whole suite green — so the round's
     "every one has a regression test" was untrue for that site; it has one now.
     Three test assertions were stale or vacuous: an emitted-alpha check
     asserted `0.0` to 12 places (which `1e-20` satisfies, and `0.0` is exactly
     the value the reader turns back into 1); the Chang-Chang onset test's
     inequalities cancelled their own strengths and held for every value (they
     now evaluate each criterion at a FIXED stress state against a hand-computed
     constant); and the Tsai-Wu cross-term test computed `f12` straight from the
     constant, so it passed with `alpha = 0` — the very defect it reasons about
     — and now applies the reader's `:273` zero→1 substitution first.

  8. **The `*PART_COMPOSITE` ply-AOPT fix's stated reach on W6 was wrong in the
     reassuring direction, and is corrected above.** `Ip=20` is the ELEMENT
     frame, not global X, so W6's layup frame really was ~49° off on 6137
     quads. Its `[0/90/45/-45]` stack is quasi-isotropic in-plane, so the `A`
     matrix genuinely is rotation-invariant and the membrane answer is
     unchanged — but `D11` moves −37.7 % and the per-ply stresses permute, so
     the pre-fix answer on a sandwich IMPACT deck was wrong rather than merely
     undiagnosed.

  **Regression sweep, both halves, HEAD `20e2f59` vs this round.** Slice: the
  35 `m2b1_val` decks, the 18 `m2b1_rev` decks, and every distinct-by-SHA256
  corpus deck under 12 MB that carries a keyword this round can reach —
  `*PART_COMPOSITE`, `*MAT_COMPOSITE_DAMAGE`, any `*SET_*_ADD`,
  `*SET_SEGMENT`, `*LOAD_BLAST_SEGMENT`, `*DAMPING_FREQUENCY_RANGE`,
  `*MAT_ADD_THERMAL_EXPANSION` or a sibling composite material (28 carriers,
  including both vehicle `combine.key` `*INCLUDE` masters and the W6/W8/W13
  carriers) — plus 40 random controls that carry none of them. **107 decks,
  0 conversion errors on both trees, 0 differences in either half**: half 1 =
  `.rad` SHA-256, half 2 = `warnings` + `skipped_keywords` +
  `recognized_not_emitted`. Every change here is a diagnostic no corpus deck
  triggers or a path no corpus deck takes, so no solver re-run was needed; the
  one change that could have moved bytes (the range exclusion) was measured
  two-tree on its own probe and is SHA-identical. Tests 4263 passed /
  2 skipped / 1518 subtests; `ruff` clean.

- **The RARE CARDS batch: `*DEFINE_ELEMENT_DEATH_{SOLID,BEAM,SHELL,THICK_SHELL}[_SET]`
  → `/ACTIV`; `*DEFINE_CURVE_SMOOTH[_TITLE]` → `/FUNCT_SMOOTH`;
  `*PERTURBATION_NODE` → `/RANDOM[/GRNOD]`;
  `*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY` → `/IMPDISP/FGEO`; and
  `*INTERFACE_SPRINGBACK_LSDYNA` → the engine `/DYNAIN` block.** All five were
  unnamed entries in `skipped_keywords` before, and one of them was actively
  breaking a deck: MEASURED on
  `dynaexamples_r14_ton-mm-s/efg/metal-cutting/main.k`, the skipped
  `*DEFINE_CURVE_SMOOTH` LCID 1 was still referenced by the `/IMPVEL` that
  `*BOUNDARY_PRESCRIBED_MOTION_RIGID` emitted, and the starter answered
  `ERROR ID : 120 ** ERROR IN FUNCTION REFERENCE / -- IMPOSED VELOCITIES /
  WRONG REFERENCE TO FUNCTION ID=1` and refused the deck (exit 2). That carrier
  now reads at **0 errors, exit 0**, with the other five warnings unchanged.

  1. **`/ACTIV` `Tstop = 0` means NEVER; LS-DYNA `TIME = 0` means IMMEDIATELY —
     and `TIME`'s default IS 0.** `hm_read_activ.F:139` is
     `IF (STOPT == ZERO) STOPT = INFINITY`, measured: a card written with
     `Tstop = 0.0` echoes `STOP-TIME 0.1000000020041E+21` and the group is never
     deactivated. dyna2rad's `CopyValue("TIME","Tstop")`
     (`convertdefineelementdeath.cxx:76`, and on all seven of its branches)
     therefore INVERTS the card on LS-DYNA's own default. k2rad refuses such a
     card by name — it neither writes `Tstop = 0` nor invents a small positive
     one, because nothing on the card derives it. **The identical
     `Tstop == 0 → INFINITY` idiom in `read_impdisp_fgeo.F:161` is CORRECT for
     `/IMPDISP/FGEO`**, because LS-DYNA's `DEATHD` default is *infinity* too
     (Vol I R17 p.5-73). Same starter idiom, opposite verdict; checked per card.
  2. **`Iform = 1` with no sensor is a silent no-op.** MEASURED: an `Iform = 1`
     `/ACTIV` with `sens_ID = 0` produced zero activation/deactivation events
     over a whole run, at zero starter and engine diagnostics. LS-DYNA element
     death has no sensor, so `Iform = 2` is the only expressible form — and it
     needs its card 3 (`%20lg%20lg` `Tstart Tstop`), which `activ.cfg:142-157`
     emits only `if(ACTIV_Iform == 2)`. `activ.cfg` exists only in
     `radioss2019`, and twin decks at `/BEGIN 2019` and `/BEGIN 2022` echo
     byte-identically with no warning on the card — the ordinary
     newest-format-is-older case, so it is emitted as written.
  3. **The element scope is keyed on what was EMITTED, per family.** A `SHELL`
     scope splits `/GRSHEL/SHEL` (quads) from `/GRSH3N/SH3N` (3-corner shells,
     which k2rad writes as `/SH3N`) — dyna2rad puts ONE `/SET/GENERAL` id in
     both slots (`convertdefineelementdeath.cxx:156-157`); a `THICK_SHELL` id
     lands in `/GRBRIC/BRIC` because k2rad writes a thick shell as a `/BRICK`;
     and a `BEAM` re-routed to a `/SPRING` goes in `grspr_ID`, tested against
     the three PRODUCER-specific registries
     (`dbeam_spring_eids | spotweld_spring_eids | muscle_beam_spring_eids`) and
     never against the `state.spring_elem_ids` union, which also holds
     `*ELEMENT_DISCRETE`, `*ELEMENT_PLOTEL`, belt and joint ids living in their
     own LS-DYNA namespaces (the #128 regression, verbatim). Elements that
     reached no emitted family are dropped with their ids named — a group
     member the deck does not define is starter `ERROR 69`, which refuses the
     whole run, while dyna2rad drops the entire card silently (`:96`).
  4. **`BOXID` and `TIME` are two INDEPENDENT criteria, so a boxed card with a
     positive `TIME` still converts.** The elements are considered for deletion
     *"either by meeting the BOXID/INOUT criterion or the independent
     TIME/IDGRP/PERCENT criterion"* (Vol I R17 p.17-251); the box fires
     *"without regard to TIME, IDGRP, or PERCENT"* — meaning it needs no other
     condition, not that the others go away — and `TIME` is switched off only
     when it is ZERO (*"If BOXID is nonzero, a TIME value of zero is reset to
     1e16"*). LS-DYNA therefore deletes at `min(box crossing, TIME)`. k2rad
     emits the `/ACTIV` for the `TIME` half and names the spatial half as
     dropped, exactly as it does for the equally independent `IDGRP`/`PERCENT`
     rule; only `TIME ≤ 0` with a box (the genuinely box-only card) is refused.
     `/ACTIV` is time- or sensor-driven and has no geometric form; dyna2rad
     reads none of the five fields.
  5. **`/FUNCT_SMOOTH` shares ONE id namespace with `/FUNCT` and `/TABLE`.**
     `hm_read_funct.F` reads both keywords (`HM_OPTION_COUNT('/FUNCT')` :103,
     `('/FUNCT_SMOOTH')` :104) into the same `NPC/PLD/NOM_OPT` arrays under one
     running index, differing only by `NPC(2*NFUNCT+L+1) = ISMOOTH`; measured,
     `/FUNCT/8002` beside `/FUNCT_SMOOTH/8002` is
     `ERROR ID : 79 ** ERROR: DUPLICATE ID / IN FUNCTION & TABLE DEFINITION`,
     and `/FUNCT_SMOOTH/301` beside `/TABLE/0/301` adds `ERROR 604`. The smooth
     curve is therefore stored in `state.curves` like any other curve and only
     FLAGGED for the writer, so `next_curve_id` dodges it and all 97 existing
     "is this LCID defined?" membership tests resolve it, with no new registry
     for a future allocator to forget (the #111 lesson). A new
     `_warn_duplicate_function_ids` scan over the assembled starter names the
     collision the deck itself can still state.
  6. **`/FUNCT_SMOOTH` is the faithful target, not a nicety: the plain `/FUNCT`
     runs the tool BACKWARDS past `TEND`.** The ISMOOTH flag makes the `/IMP*`
     consumers interpolate with the quintic smoothstep
     `S(u) = u³(10 − 15u + 6u²)` instead of linearly, and on `/IMPVEL` it also
     clamps outside the point range — `fixvel.F:314/316` dispatches to
     `VINTER_SMOOTH`, which returns the segment end ordinate there
     (`vinter_smooth.F:68-71`). (The clamp belongs to that consumer, not to the
     flag: `/IMPDISP/FGEO` goes through `FINTER2_SMOOTH`,
     `finter_smooth.F:116-152`, which has none.) A plain `/FUNCT`
     extrapolates. Measured on the
     same four points: at t = 1.1501e-2 the smooth curve held DX at 10.000000
     while the plain one had fallen to 9.296098, i.e. −1250 mm/s of invented
     return stroke. The trapezoid itself needs **no conversion factor** — the
     LS-DYNA identity `DIST = VMAX·(TEND − TSTART − TRISE)` is term for term
     what the four vertices integrate to, and stays exact for the quintic blend
     because `∫₀¹S(u)du = ½` on each ramp (the #128 rule). Two dyna2rad gaps are
     closed: its `break` at `convertcurves.cxx:323` aborts the loop over all
     remaining smooth curves, and its `!= 0.0` divisor test at `:325` lets a
     span that is only float noise (`0.03 − 0.01 − 0.02 = −3.5e-18`) through
     into `VMAX ≈ 1e18`.
  7. **`/RANDOM`'s `ALEAT()` is symmetric — the Reference Guide is wrong, so
     `DTYPE` decides the amplitude.** `aleat.F:48-49` returns
     `(I − 32768.)/32768.`, uniform on `(−1, +1)`; measured on a 1000-node block
     at `XALEA = 0.5`, dX/dY/dZ spanned −0.4997…+0.4998 with std 0.293/0.288/0.294
     against the theoretical `XALEA/√3 = 0.2887`, and two runs of the same deck
     moved every node by byte-identical amounts. So LS-DYNA `DTYPE = 1`
     (`SCL × [−AMPL, AMPL]`) is `XALEA = SCL·AMPL` exactly, while `DTYPE = 0` —
     **the default**, one-sided `SCL × [0, AMPL]` — becomes `XALEA = SCL·AMPL/2`,
     which reproduces the zero-mean noise (same half-width, same standard
     deviation) and drops only a rigid translation of `+SCL·AMPL/2` per axis.
     dyna2rad ignores `DTYPE` and writes `SCL·AMPL` for both, i.e. double the
     spread on the default form. Only TYPE 8 converts: TYPE 1 (harmonic) is a
     deterministic mode-shaped trigger and TYPE 2 (fade) does not perturb
     anything at all, yet dyna2rad turns both into white noise.
  8. **A global `/RANDOM` and a `/RANDOM/GRNOD` in one deck perturb NOTHING.**
     `hm_read_rand.F:152/156/175` runs the all-nodes branch only when
     `NRANDG == 0` and the group branch only when `IALL == 0`; measured with one
     of each, there is no `RANDOM NOISE` block in the `.out` at all, 0 ERROR,
     0 WARNING, and not one node moved. One LS-DYNA deck may legitimately carry
     an `NSID = 0` card beside an `NSID > 0` one, so the conflict is resolved at
     conversion time (the all-nodes card wins, and the per-set amplitudes are
     named) rather than shipped.
  9. **A negative `NID` on `*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY` is a
     PROJECTION, not a collapse.** *"all the nodes in this node set are
     displaced from their initial positions to the projected points on the
     xy-plane with Z offset"* (Vol I R17 p.5-74): each member keeps its own x
     and y. dyna2rad pushes the same `(X, Y, Z)` for every member
     (`convertbcs.cxx:741-746`), collapsing the set onto one point. The per-row
     `LCID`/`DEATH` also override the header `LCIDF`/`DEATHD` when nonzero
     (p.5-75), which Radioss's one-`fct_ID`-per-card layout can only honour by
     splitting into several `/IMPDISP/FGEO` — dyna2rad reads neither field. And
     `BIRTH` does BOTH things at once in LS-DYNA (*"the abscissa values are
     shifted by an amount BIRTH … the same effect as setting OFFA = BIRTH"*)
     while the Radioss `Tstart` is a pure gate (`fixfingeo.F:155/168`), so it is
     emitted as `Tstart = BIRTH` **and** a curve copy shifted by `+BIRTH` — the
     #128 `/IMPTEMP` lesson in reverse. The node cards are sliced I8/E16/E16/E16/I8/E16
     (card 2a) or …/I8/E8/E8 (card 2b, `IBRTH = 1`), the column spans recovered
     from the R17 table's own ten-column ruler; a uniform 10-wide slice would
     start `Y` inside `X` (the `*ELEMENT_MASS` failure).
  10. **`/DYNAIN`'s end-of-run rescue is DEAD CODE, so the trigger has to be a
      schedule.** `sortie_main.F:922` fires `GENDYNAIN` on `TT >= TDYNAIN` and
      `SORTIE_MAIN` runs every cycle (`resol.F:8233`) — but an explicit run's
      last computed cycle lands BELOW `TSTOP` and the overshoot happens after
      that call. `resol.F:8358-8368` does set `ILASTDYNAIN = 1` and pull
      `TDYNAIN` back to `TT − 1e-10` there, and then **nothing ever reads
      `ILASTDYNAIN`**: the "run one more cycle" decision at `resol.F:9265-9295`
      is taken on `ILASTANIM`/`ILASTH3D` alone. MEASURED on an `ENDTIM = 1e-2`
      deck (3478 cycles, dt growing 1.15e-6 → 5.5e-4 so an animation was written
      on each of the last cycles): `/DYNAIN/DT 0.0098 1E+30` wrote **zero**
      `.dynain` files at NORMAL TERMINATION, 0 ERROR, 0 WARNING — the "legal,
      accepted, and empty" class (#122) one step further on. dyna2rad's
      `Tstart = Tfreq = ENDTIM` (`convertcards.cxx:1242-1243`) has the same
      hole. k2rad writes `0.9·ENDTIM  0.02·ENDTIM`: at most six files, and it
      does not depend on any other output card being present. The capture is a
      SCHEDULE, so the newest file holds the last state written at or after
      `0.9·ENDTIM` and can precede termination by up to one interval — the
      warning says so rather than promising the terminal state. Verified end to
      end — the last file carries
      `*ELEMENT_SHELL_THICKNESS`, `*NODE`, a full `*INITIAL_STRESS_SHELL`
      (5 through-thickness × 4 in-plane records with EPSP), `*INITIAL_STRAIN_SHELL`
      and `*END`, and `k2rad.parser.parse_k_file` reads it straight back.
  11. **The STARTER re-parses the engine file, and a comment line kills it.**
      `check_dynain.F` opens `<root>_0001.rad` from inside the starter and walks
      the `/DYNAIN/DT` block; its guard
      `IF(CARTE(1:1)/='#'.OR.CARTE(1:1)/='$')` (:144) is always TRUE, so the
      line after `Tstart Tfreq` goes into an `(I10)` internal READ. A `#`/`$`
      COMMENT line passes the tautology, enters the `DO WHILE` at :145 and
      reaches the token READ at :153 — `forrtl: severe (64)`, the starter dies
      with no `.out` at all; a BLANK line instead fails that loop's own
      `LEN_TRIM(CARTE)/=0` and exits at once, leaving `NPRT = 0` — starter
      `ERROR 1909`. Both are fatal, by different routes. The part ids therefore follow that line immediately, and
      are capped at ten per line because `fredynain.F` reads them into a fixed
      `IV2(10)`. An empty part list is `ERROR 1909` and an unknown part id
      `ERROR 1908`, both fatal at the starter, so `PSID = 0` / an unresolvable
      or fully-dropped `*SET_PART` falls back to `/DYNAIN/DT/ALL` with the
      widening named. `/DYNAIN` is SHELLS ONLY (`fredynain.F` has no other
      element writer) at BOTH scopes: a shell-free deck emits nothing, and a
      `*SET_PART` naming parts that own no `/SHELL` or `/SH3N` has those parts
      dropped from the list — if none is left the block is refused rather than
      widened. Measured on a deck whose set named a solid part while shells
      existed elsewhere: the engine accepted it and wrote six 118-byte files
      whose entire body is `*NODE` + `*END`, at 0 ERROR / 0 WARNING / NORMAL
      TERMINATION. Several `*INTERFACE_SPRINGBACK` cards in one deck are merged
      into ONE block. Two PART-SCOPED blocks would have UNIONED anyway —
      `fredynain.F` initialises `NDYNAINPRT` once (:89), zeroes it only in the
      `/ALL` branch (:109) and APPENDS every id in the part branch (:123/:124)
      — losing only the EARLIER block's `Tstart/Tfreq` (:103 overwrites them
      per block); it is MIXING an `/ALL` block with a part-scoped one that is
      order-dependent, because `read_dynain.F:80/93` resolves the scope with an
      `ELSEIF` (the part list wins whenever `NDYNAINPRT ≠ 0`) and whichever
      card comes second decides. One block with one schedule is what the engine
      would have done for the part-scoped case regardless.
  12. `*INCLUDE_TRANSFORM` buckets for every new spelling, from the same source
      as the handlers (#116/#124), a WALKER wherever the cell layout is not a
      uniform id grid — `*DEFINE_CURVE_SMOOTH` is the one declarative spec,
      because `LCID` is its only id cell and every other cell is a float:
      the death cards' cell 1 is an element id in the plain spelling and a set
      id in `_SET`; `*PERTURBATION_NODE`'s card 2 is float-bearing on every
      TYPE (a wavelength of `1.5` would read back as the id `1`) and card 2c is
      a FILE NAME; the FGEO node rows mix ids with floats at non-10 widths AND
      put one cell in two namespaces by sign (#125); and the springback
      `OPTCARD` rows carry counts, not ids. `IDGRP` is deliberately left alone —
      it is a bare grouping tag whose only relation is equality within the
      include.
  13. Post-review verification round, on top of the above:
      * `/DYNAIN`'s shells-only rule now screens the PART LIST, not only the
        deck. A `*SET_PART` naming solid parts in a deck that has shells
        elsewhere used to pass the deck-wide guard; measured, the engine
        accepted it and wrote six 118-byte files whose whole body is `*NODE` +
        `*END`, at 0 ERROR / 0 WARNING / NORMAL TERMINATION.
      * Several `*INTERFACE_SPRINGBACK` cards merge into ONE `/DYNAIN` block:
        `read_dynain.F:80/93` resolves the scope with an `ELSEIF` while
        `fredynain.F:109-110` zeroes `NDYNAINPRT` inside the `/ALL` branch, so
        two blocks silently honour one card and drop the other, depending on
        their order.
      * A `BOXID` beside a POSITIVE `TIME` now converts. The two are
        INDEPENDENT criteria (p.17-251) and only `TIME = 0` is switched off by
        the box, so refusing the whole card dropped an expressible death; the
        `/ACTIV` fires at the stated TIME (measured: `BRICK DEACTIVATION: 101
        AT TIME: 0.40000E-02`, on a run that terminates at 0.0 % energy error).
      * A `THICK_SHELL_SET` no longer falls back to `*SET_SHELL` — a third SID
        namespace whose members cannot be thick shells (the #125/#128 class).
      * The `BIRTH` curve copy keeps the SOURCE card's kind: a
        `*DEFINE_CURVE_SMOOTH` is re-emitted as `/FUNCT_SMOOTH`, not `/FUNCT`,
        or `fixfingeo.F:196-199` picks `FINTER2` and loses the quintic blend
        (measured `f = 0.1036` against the plain twin's `0.2503` at
        `u = 0.25`). NOT a clamp: `FINTER2_SMOOTH` (`finter_smooth.F:116-152`)
        has none on this path either — it extrapolates the last segment with
        the same quintic, so the smooth copy runs FURTHER past the end of the
        curve than a plain one would (measured `f = −7.62` vs `−1.50`). The
        clamping routines are other entry points with other callers:
        `VINTER_SMOOTH` (`vinter_smooth.F:68-71`), which the `/IMPVEL` path
        uses (`fixvel.F:314/316`), and `FINTER_SMOOTH`
        (`finter_smooth.F:71/74`, `gravit.F`/`forcefingeo.F`).
      * Two all-nodes `*PERTURBATION_NODE` cards collapse to one `/RANDOM` at
        the largest amplitude, with the rest named: `hm_read_rand.F:135-136`
        overwrites one module-level `XALEA` per record and `:156-163` applies
        it once, while LS-DYNA sums separate cards (p.38-10 Remark 2).
      * A `*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY` driver curve that is not the
        0 → 1 scale factor p.5-73 requires is named. `fixfingeo.F:243-256` has
        no clamp on `f`, and a `*DEFINE_CURVE_SMOOTH` can never satisfy the
        requirement (its last vertex is `(TEND, 0)` by construction) — measured
        on that pairing, a `VMAX = 200` plateau drove a 1 mm offset to 98 mm
        and the run died on the energy-error limit under a NORMAL TERMINATION
        banner. The warning also says what happens PAST the last abscissa,
        which is not "the node holds": both interpolators extrapolate the last
        segment, so unless `DEATH` bounds the card the node keeps going.
      * `*INTERFACE_SPRINGBACK_EXCLUDE_NOTHICKNESS`, the one corner of the
        4 × 2 OPTION1 × OPTION2 grid a hand-written variant list had lost, is
        dispatched; the eight spellings are now generated from one source and
        tested against an independent enumeration (#116).
      * A `*DEFINE_CURVE` and a `*DEFINE_CURVE_SMOOTH` on the same LCID are
        named, and the smooth flag is cleared when the plain curve wins, so the
        emitted card kind always matches the surviving points. A smooth curve
        is also no longer appended to `state.curve_order`, which is the
        `*DEFINE_CURVE` ordering the legacy positional `*DEFINE_TABLE` form
        resolves against (p.17-444 scopes it to that keyword by name).
      * `DIST = 0` on a smooth curve is named: every field on that card has
        default *none*, so a blank `DIST` is a missing input. With `VMAX`
        BLANK the emitted curve really is identically zero; with `VMAX` STATED
        the card is REFUSED instead, because there the back-solve
        `TEND = DIST/VMAX + TSTART + TRISE` collapses the window onto
        `TSTART+TRISE` and the abscissa nudge turns it into a `VMAX`-height
        spike one card digit wide, with the deck's own `TEND` discarded. Same
        for a `DIST` whose sign contradicts `VMAX`'s (a negative window). Those
        are the two degeneracies the `VMAX`-blank arm already refused, reached
        from the other side.
      * `/IMPDISP` ids minted by the rigid-wall geometric-motion path now dodge
        the deck's `BPFGID`s and are recorded — that path is the one `/IMPDISP`
        producer whose section runs after the FGEO one, so it could not be
        screened from there.
      * Two texts corrected against the code they cite: the contact note said
        k2rad's TYPE7/TYPE25 default to `Idel = 0` (it writes 2 — the real
        reason dead elements keep their segments is that `desacti.F`/`eloff.F`
        never arm `IDEL7NOK`, which is what `resol.F:5015-5153` gates on), and
        the file-count claim read `int((1−0.9)/0.02) + 1 = 5` where IEEE-754
        makes that quotient 4.999… and the engine writes SIX. The `/DYNAIN`
        text now describes a schedule rather than promising the terminal state.
        The `/ACTIV` note also names the one family `eloff.F` does NOT zero:
        `:479` writes `OFFG = -ABS(OFFG)` for 4-node shells (while `:418`
        zeroes the solids in the dedicated `IGBR` pre-loop, `:522` the beams,
        `:565` the `/SH3N` and `:458` the 2-D quads k2rad never emits), so
        their `/TH` force and moment channels FREEZE at the death value instead
        of dropping to 0 — a stale channel, not a loaded element.
  14. SECOND verification round, on top of round one:
      * `DIST = 0` beside a STATED `VMAX` is now refused rather than emitted
        under an "identically zero … does not move at all" warning. On that arm
        the back-solve collapses `TEND` onto `TSTART+TRISE`, the abscissa nudge
        turns the trapezoid into a `VMAX`-height spike one card digit wide
        (measured `(0,0) (1e-3,100) (1.00001e-3,100) (1.00002e-3,0)`), and a
        stated `TEND` is discarded — the #122 class in the UNDER-alarming
        direction. A `DIST` whose sign contradicts `VMAX`'s is refused with it
        (it back-solved a NEGATIVE `TEND`). The blank-`VMAX` arm is unchanged:
        there the curve really is identically zero and is still emitted.
      * The smooth-flag clear was gated on ONE curve spelling and dead on its
        sibling (#124 again): `*DEFINE_CURVE_FUNCTION` also overwrites
        `state.curves[lcid]`, with SAMPLED piecewise-linear points, and left
        the flag set — a 101-point ramp went out as `/FUNCT_SMOOTH`, with no
        duplicate-id warning either, because the deck-wide text scan sees only
        one `*DEFINE_CURVE_SMOOTH` header. Both producers now call one helper.
      * The `/IMPDISP/FGEO` range diagnostic de-duplicated per DECK instead of
        per (card, curve), so a second card driven by the same out-of-range
        curve was emitted in silence — the warning names the BPFGID, so the
        drop was invisible.
      * `*INTERFACE_SPRINGBACK` dropped-field accounting now runs on REFUSED
        cards too. All three refusal `continue`s skipped it, so `NHSV`/`FTYPE`/
        `FTENSR`/`RFLAG`/`INTSTRN`/`NTHHSV`/the `OPTCARD` cards/the Card-4 rows
        vanished without a word on exactly the cards a reader most needs them.
      * Five texts corrected against the code they cite: the springback merge
        (two PART-SCOPED blocks are additive, not order-dependent — only the
        mixed `/ALL` case races), the `/RANDOM` overwrite
        (`hm_read_rand.F:135-136` / `:156-163`, not `:118-126` / `:152-163`),
        the FGEO smooth-copy dispatch (`fixfingeo.F:196-199`, and there is NO
        clamp on that path — `FINTER2_SMOOTH` extrapolates the last segment
        quintically, so the smooth copy runs FURTHER past the curve, not less;
        the clamp belongs to `VINTER_SMOOTH` on the `/IMPVEL` path), and the
        `eloff.F` family list (`:418` zeroes the solids in the `IGBR` pre-loop;
        `:458` is the 2-D QUAD branch k2rad never emits). `check_dynain.F`'s
        two bad lines are now distinguished: `#`/`$` is `forrtl: severe (64)`,
        a blank line is `ERROR 1909`. Both `state.imp_card_ids` docstrings now
        list all THREE producers instead of one, and `ROADMAP.md`'s
        element-GROUP deferral no longer leans on `next_elem_group_id`, which
        guards exactly one of the element-group emission sites.
      * Tests: the `4 × 2` spelling test asserted `kw in _RARE_CARD_OFFSETS`,
        which assembly.py's None-fill makes true by construction — it now
        asserts the VERDICT (walker for the two `LSDYNA` spellings, `None` for
        the six warn-drops). New coverage for the `/IMPDISP` id dodge in the
        rigid-wall direction, which round one changed with no test at all.
      * Inertness measured in TWO halves, `.rad` and warnings, because a sweep
        that compares only output files cannot see a warning change — which is
        how round one came to claim "0 warning logs differ" for a round whose
        stated purpose was rewriting warning texts. Round two vs round one,
        MEASURED on all 397 corpus decks with both halves compared (0
        conversion errors on either tree): **0 of 397 `.rad` differ and 0 of
        397 warning streams differ**, the 8 rare-card carriers included —
        every text this round rewrote needs a deck shape the corpus does not
        contain (two springback cards, an `/IMPDISP/FGEO` card, two global
        `*PERTURBATION_NODE` cards, an element-death card). They fire on the
        rare-cards VALIDATION set instead: 0 of 76 decks change a `.rad` byte,
        so no solver deck needed re-running, and 31 of 76 change warning text
        — exactly the rewrites listed above.

- **The RARE MATERIALS batch: `*MAT_SHAPE_MEMORY` / `*MAT_030` → `/MAT/LAW71`;
  `*MAT_MUSCLE` / `*MAT_156` + `*MAT_SPRING_MUSCLE` / `*MAT_S15` →
  `/PROP/TYPE46` (`SPR_MUSCLE`) + `/SPRING`; and
  `*MAT_ADD_THERMAL_EXPANSION` → `/THERM_STRESS/MAT` + `/HEAT/MAT` with the
  minimal temperature-driver foothold (`*INITIAL_TEMPERATURE[_SET|_NODE]` →
  `/INITEMP`, `*LOAD_THERMAL_{CONSTANT,LOAD_CURVE,VARIABLE}[_NODE]` and
  `*BOUNDARY_TEMPERATURE[_SET|_NODE]` → `/IMPTEMP`,
  `*MAT_THERMAL_ISOTROPIC` via `*PART` TMID → the `/HEAT/MAT` values).**
  Keywords that landed in `skipped_keywords` before, on a conversion whose only
  other sign of trouble was one "part references a material no `/MAT` defines"
  line — or, for the thermal cards, on a conversion that was **completely
  silent**: the material resolved, so nothing dangled, and the whole
  thermal-expansion physics vanished into a two-line "skipped" list. The
  superelastic alloy simply had no constitutive law; the muscle either kept full
  bending stiffness on a `/PROP/BEAM` it should never have had or became an
  inert zero-stiffness spring.

  Also in this batch, and worth a line of its own: **`*SECTION_SHELL_THERMAL` is
  now registered.** `handle_section_shell`'s card-set walk already strode the
  option card (`_SECTION_SHELL_OPTION_CARDS`), so the spelling was one dict row
  away from working — without it the section was lost whole and
  `thermal/thick-thin-shells/07_metalstrip.k` converted to **40 × `ERROR 495`
  "SHELL ID=n HAS A NULL THICKNESS"**. It now starts at 0 errors.

  1. **`ALPHA` is copied 1:1 — dyna2rad's `sqrt(2/3)` factor is a d2r defect.**
     Both codes state the SAME quantity in the SAME normalisation, so any
     factor is wrong. LS-DYNA Vol II R17 p.2-307 Remark 1 *defines*
     `alpha = sqrt(2/3)·(−σ_s^{AS,−} − σ_s^{AS,+})/(−σ_s^{AS,−} + σ_s^{AS,+})`
     with `−sqrt(2/3) < alpha < sqrt(2/3)` and
     `σ_s^{AS,−} = (alpha + sqrt(2/3))/(alpha − sqrt(2/3))·σ_s^{AS,+}`; p.2-309
     Remark 2 gives `F = ‖t‖ + 3·alpha·p ≥ (alpha + sqrt(2/3))·σ_tr`. That is
     term for term `sigeps71.F:171/245/277` (`SQDT = SQRT(TWO/THREE)`,
     `RSAS = YLD_ASS*(SQDT+ALPHA)`, `FS = SV + THREE*ALPHA*P`), whose uniaxial
     compression onset is `sig_sas·(sqrt(2/3)+alpha)/(sqrt(2/3)−alpha)` — the
     manual's own closed form. **`ALPHA` is sqrt(2/3) TIMES the asymmetry
     ratio, not the ratio**, which is the algebra step that makes the shrink
     look right; the measured pair `sig_sas 400 / ALPHA 0.1` giving
     `(σ_C−σ_T)/(σ_C+σ_T) = 0.1225 = ALPHA/sqrt(2/3)` is exactly what Remark 1
     asks for. Starter-measured with the card written both ways: `alpha = 0.1`
     → compression onset **513.50** against the LS-DYNA closed form 511.65
     (+0.36 %), `alpha = sqrt(2/3)·0.1` → **490.52** (−4.1 %, and the error
     grows with ALPHA: 37 % low at ALPHA 0.6). The range guard follows the same
     correction: it now fires at `|ALPHA| ≥ sqrt(2/3) = 0.8164966`, LS-DYNA's
     own bound and exactly where `hm_read_mat71.F:154-160` answers `ERROR 1124`
     — the old `|ALPHA| > 1` test let an LS-DYNA-illegal `ALPHA = 0.9` through
     with no warning at all. dyna2rad's
     `SetExpressionValue("sqrt(2/3)*ALPHA","alpha")` (`convertmats.cxx:1931`)
     is deliberately **not** reproduced.

  2. **`YMRT → E_mart` — a slot dyna2rad never writes.**
     `CopyValue("YMTR","E_mart")` (`convertmats.cxx:1929`) misspells the cfg's
     `YMRT` (`Keyword971_R7.1/MAT/mat_030.cfg:40`), the attribute lookup
     silently resolves to nothing, and every converted SMA echoes
     `MARTENSITE YOUNG'S MODULUS = 0.0` for a card stating 50000 — so
     `hm_read_mat71.F:176` leaves `EFLAG = 0` and the martensite branch is never
     taken. Measured post-transformation slope: 22750 with the field set
     (`E_mart` 25000) against 46000 without it (`E` 50000).

  3. **A negative transformation stress is a curve id, and emitting it is worse
     than dropping it.** The four `SIG_*` cells are `SCALAR_OR_OBJECT`
     (`meci_data_reader.cpp:6845-6848`): `LT.0.0` means `-SIG_xxx` is a load
     curve of temperature or plastic strain. `/MAT/LAW71` has one scalar per
     threshold and no function field anywhere on the card, so dyna2rad's
     "copy only when `> 0`" leaves all four at zero,
     `hm_read_mat71.F:163-166` substitutes `1e-20`, and the ordering checks at
     `:139-153` refuse the deck with `ERROR 1122` + `ERROR 1123` **once per
     material**. k2rad warn-skips the material by name instead, so the log says
     which physics was lost rather than the starter saying the alloy is
     backwards.

  4. **The eight temperature terms stay blank on purpose.** They are not inert:
     `TSAS/TFAS/TSSA/TFSA` blank → 298.0 K and `TINI` blank → 360.0 K
     (`hm_read_mat71.F:168-175`), so a non-zero `CAS`/`CSA` shifts every
     threshold by `CAS·(TINI−TSAS)/sqrt(2/3)` — measured, `sig_sas` 400 → onset
     478 MPa at `CAS = CSA = 1`. LS-DYNA MAT_030 has no counterpart for any of
     them, so writing anything there would be an invented load. `CP` blank →
     1e20 pins the adiabatic self-heating term at `TINI` (`sigeps71.F:238`),
     which is what makes the choice self-consistent.

  5. The R7.1 optional card 3 (`LCID_AS`/`LCID_SA`, a `FREE_CARD`) is claimed by
     **raw row index** on both the read and the `*INCLUDE_TRANSFORM` side — an
     all-blank optional card is legal LS-DYNA and a content scan walks past it
     into the next keyword (#109/#117/#119). Its two ids, `LCSS`, `LCSSC` and
     `IDPP` are named-dropped; `LCID_AS` additionally says that the emitted
     plateau is the card-1 constant LS-DYNA would have overwritten.

  6. **A zero function id is not "no function" — it silently kills the whole
     active muscle force.** `ruser46.F:207` calls `GET_U_FUNC(IFUNCi, …)` with
     no `id == 0` guard; `GET_U_FUNC(0)` reads `NPF(0)` (`ufunc.F:183`,
     `eng_callback_c.c:176` does raw pointer arithmetic `sav_buf + decalage - 1`)
     and returns 0. Measured on four separate decks — `f1 = 0`, `f2 = 0`,
     `f3 = 0`, and `f2 = f3 = 0` — every one gives **exactly zero active force**
     at 0 starter errors and 0 warnings, with only the `f4` passive branch and
     the `Damp` term surviving. All four slots are therefore always written, with
     a synthesized constant where the LS-DYNA card leaves the factor
     unspecified.

  7. **`Force` never lands on dyna2rad's `*MAT_MUSCLE` path**, so every muscle it
     converts has an identically-zero ACTIVE force. `radProp.SetValue(…,
     sdiIdentifier("Force"), …)` at `convertprops.cxx:2617` fails to resolve
     while the identical call with `"Scale_F"` one line later succeeds: measured
     `MAXIMUM FORCE = 0.0` for `PIS = 0.3` and for `PIS = 4.0`, against
     `FORCE SCALE FACTOR = 7.5` / `100.0` on the same decks. A hand-written
     `/PROP/SPR_MUSCLE` with the same value in card-1 column 4 echoes
     `MAXIMUM FORCE = 7.5`, so the starter reads `NFORCE` fine.
     **Validated end to end**: a `*MAT_156` truss (`PIS = 0.3`, `A = 25`,
     `SNO = 1.25`, an `SVS` curve peaking 0.8 at `λ = 1.25`) pulling a free mass
     gives `px/t = 5.99999957 N` against the hand-computed
     `PIS·A·f_SVS(SNO) = 6.0`; an S15 muscle (`FMAX = 1000`, all factors 1)
     gives `px/t = −1000.0000 N` and `x = ½(F/m)t²` to 7 digits.

  8. **`Vel_max ← SRM`, `Damp ← DMP` and `Mass ← RO·A` are dimensionally wrong,
     and `SNO`/`SFR`/`SV` are dropped.** `SRM` is a strain rate and `DMP`
     multiplies a strain rate (`mat_156.cfg:32/36`), while `/PROP/TYPE46` wants a
     velocity and a force-per-velocity; `SNO` sets the muscle's reference length
     `l_orig = l0/SNO` *and* its lineic mass. Carried through instead as
     `Vel_max = SRM·L0/SNO`, `Scale_v = SFR/SNO` (so the Radioss rate abscissa
     `(L/L0)·v/(Vel_max·Scale_v)` **is** LS-DYNA's `ε̄̇`),
     `Mass = RHO·A/SNO` with `Idens = 0`, and `Damp = DMP·A·SNO²/L0` — the one
     linearised value, matched at the element's initial configuration because
     the LS-DYNA damper is quadratic in the stretch and Radioss offers `Damp·v`
     only. `L0` is the part's reference element length; when the part's muscle
     elements are not all the same length the mean is used **and the spread is
     reported**.

  9. **`*MAT_S15`'s `FPE < 0` curve gets the transform its sibling `TL` gets.**
     dyna2rad hands the raw curve id to `fct_id4` with neither the `(L−1)·L0`
     abscissa nor a scale (`convertprops.cxx:3308-3316`, measured
     `fct_id4 = 5`, `Scale_F = 1.0`) while its `TL < 0` path *does* transform.
     Here both branches carry `X = L·L0 − l_init` and share `Scale_F = FMAX`,
     which is what `SDMAT15.cfg:38` states the curve is —
     *"Normalized force, as a function of length for parallel elastic element"*.

 10. **Guards dyna2rad does not have**: `SSM = 0` divides by zero in the
     `*MAT_156` exponential (`:2859`), `L0 = 0` in the S15 one (`:3286`), and
     `LMAX = 0` silently produces no `fct_id4` at all (`:3253`); an `SSP < 0`
     **table** id (the 2-D `h(ε̄̇, λ)` form) is handed to `fct_id4` as if it were
     a 1-D `/FUNCT`. Each is warn-dropped by name with a constant-zero passive
     function in its place.

 11. **Per-element muscle force cannot be output.** `/TH/SPRING` on a TYPE46
     element writes 15 channels of **exact zero** — force, deflection, length
     and even the OFF flag — in every load case, while a `/PROP/TYPE4` spring in
     the SAME `/TH/SPRING` group of the SAME deck reports `OFF = 1` and
     `LENGTH = 100` correctly. The force is real (`rforc3.F:1419-1425` writes
     `GBUF%FOR`, and the global `SPRING ENERGY` channel is right), only the
     per-element history is dead. Muscle spring ids are therefore kept out of the
     `*DATABASE_DEFORC` pool (`state.muscle_spring_eids`) and the warning names
     `/TH/NODE REACX` and `SPRING ENERGY` as the working alternatives — the #122
     rule: an emitted channel that is legal, accepted and all zeros is worse than
     an honest warn-and-drop.

 12. **The thermal-expansion card ships WITH a temperature driver, because
     without one it is provably inert.** Radioss's expansion is INCREMENTAL -
     `ETH = alpha(T)*Fscale*(T_n - T_(n-1))`, accumulated cycle by cycle
     (`cmain3.F:235-240` via `thermexpc.F:172-174` for shells,
     `mmain.F90:770-786` inline for solids) - so with a `/HEAT/MAT` and no
     driver `DTEMP` is identically zero on every cycle and the emitted
     `/THERM_STRESS/MAT` does nothing while the starter reports 0 errors. The
     foothold is therefore part of the same slice, and the whole chain is
     **engine-validated**: a 10-hex bar under symmetry mounts, alpha = 1.2e-5,
     dT = 100 K, gave a free-end `DX = 0.0119843 mm` against the closed-form
     `alpha*dT*L = 0.012` - **-0.13 %** - with the `/TH/NODE TEMP` channel
     evolving 20 -> 120 K (not the zeros of #122).

 13. **dyna2rad transports the wrong coefficient, off by 8.3e4, silently.**
     `convertmats.cxx:12261-12266` writes `Fscale_x/y/z` + `Fct_ID_Tx/T/Tz`,
     which is a NEWER card shape: the only `mat_THERM_STRESS.cfg` on this build
     declares exactly `Fct_ID_T` + `Fscale_y` and
     `hm_read_therm_stress.F90:119-120` reads only those two, so five of its six
     writes go nowhere and the two that land are `Fct_ID_T <- LCIDY` and
     `Fscale_y <- MULTY`. Measured on the corpus carrier's own numbers
     (`LCID 0, MULT 1.2e-5, LCIDY 0, MULTY 1.0`): the converted coefficient came
     out **1.0 instead of 1.2e-5**, at 0 errors and 0 warnings. `LCID`/`MULT`
     are the pair carried here.

 14. **A constant coefficient MUST become a synthesized `/FUNCT`.**
     `Fct_ID_T = 0` with `Fscale_y = alpha` gives `alpha = FINTER(0,T)*Fscale =
     0`, i.e. NO expansion - measured twice on independent code paths (a free
     solid bar: `DX == 0`; a clamped LAW2 shell: `F1 == 0`). And an unresolvable
     `Fct_ID_T` is **accepted at 0 errors** and reinterpreted as an internal
     function index: `hm_read_therm_stress.F90:121-128`'s unknown-function
     branch is dead code (`ifunc_alpha = func_id` is pre-set before the search
     loop). Every id is resolved at conversion time.

 15. **The LS-DYNA card is per PART, the Radioss card is per MATERIAL - so a
     shared material is SPLIT.** The corpus carrier has exactly that shape:
     PIDs 1, 2 and 3 on MID 1 with `*MAT_ADD_THERMAL_EXPANSION` on PID 1 only.
     dyna2rad resolves PID -> the part's MID and stops (`convertmats.cxx:12236`),
     expanding all three. Here part 1 is repointed at a fresh copy of the
     material (every per-mid `/FAIL` rider travels with it) and mid 1 keeps the
     parts the deck did not name. Two cards on one MID: dyna2rad emits two
     entities with the same id, no duplicate error, first wins, second silently
     lost (measured).

 16. **`/HEAT/MAT` is mandatory and it OVERWRITES things.** `/THERM_STRESS/MAT`
     on a material with no `/HEAT/MAT` is a hard `ERROR 1129`
     (`hm_read_therm_stress.F90:130-132`), so the pair is always emitted
     together. But `/HEAT/MAT` also overwrites `MAT_PARAM%THERM%TMELT` with
     `T1` - the very variable `mmain.F90:790` divides by for the Johnson-Cook
     `T*` - and a blank `T1` defaults to 1e20: measured, the law echoes
     `MELTING TEMPERATURE 1800` while `/HEAT/MAT` echoes `1e20`, `T*` collapses
     to 0 and the thermal softening is dead at 0 warnings (`WARNING 764` is
     gated on the Zerilli form only). The law's own melt temperature is copied
     into `T1`, and a `RHO0_CP` that differs from the law's own `rhoC_p` is
     named (starter `WARNING 765`). On `*MAT_TABULATED_JOHNSON_COOK` the pair is
     REFUSED outright: a `/HEAT/MAT` switches LAW109 off its self-heating path
     (`sigeps109.F:411-414`), and without one the expansion card is
     `ERROR 1129`. `EFRAC` carries `1e-20` rather than the blank the reader
     turns into **1.0** ("convert all strain energy into heat"), which is the
     opposite of what a deck prescribing its temperature field states.

 17. **Two element-family verdicts, both re-measured on the branch's own
     converted decks.** A `/MAT/ELAST` (LAW1) SHELL gets **no expansion at
     all** - LAW1 is the one law Radioss integrates GLOBALLY through the
     thickness (`WARNING 1084 ... FORMULATION IS SWITCHED TO GLOBAL
     INTEGRATION N=0`) and `thermexpc.F` only reaches the
     per-integration-point stresses, so there is nothing for it to correct.
     Measured on a 10 x 1 mm strip at alpha = 1.2e-5 over dT = 100 K
     (closed form 0.012 mm): **2.66e-07 mm at NIP 5 and -5.11e-08 mm at
     NIP 1** - the integration-point count is not the cure, because LAW1
     discards it. So the material is **RESTATED as `/MAT/LAW36` with a flat
     yield curve at 1000 x E** whenever every part on it is a shell, which is
     proven elastically neutral: the same strip pulled mechanically to the same
     elongation reports 209.977 / 419.561 / 628.914 / 838.231 MPa under LAW1
     against 210.003 / 419.709 / 629.086 / 838.410 under the restatement
     (**+0.012 % to +0.035 %**, against the closed form 210 / 420 / 630 / 840),
     and the free edge follows the imposed motion to 8 digits. The one cost is
     a **-4.6 %** time step. End to end: the same .k file that produced
     2.66e-07 mm now produces **0.0120078 mm (+0.065 %)** at 0 starter errors
     and 0 warnings. A material shared with SOLID parts is NOT restated - a
     LAW1 solid expands correctly, because `mmain.F90:757` applies the
     expansion before the law dispatch - and its shell half is named as inert
     instead.

     On SOLIDS the physics is exact wherever the engine is stable, and the
     instability now has a **sharp measured trigger: a run of elements free to
     TRANSLATE laterally as a group.** Same bar, one variable at a time:

     | mount / variant | free-end DX | dt held? |
     |---|---|---|
     | quarter symmetry at every cross-section | 0.01198664 mm | yes |
     | end face pinned in x + 3 DOFs, nothing else | **-3.6886 mm** | NO (2e-19) |
     | the same end pinning + lateral anchors | 0.01198628 mm | yes |
     | encastre end face + lateral anchors | 0.01229825 mm | yes |
     | ONE hex, end face pinned in x + 3 DOFs | 0.01198825 mm | yes |

     It is **not** the clamp (the encastre face WITH lateral anchors is stable
     and energy-balanced, I-ENERGY 0.1315 vs EXT-WORK 0.1312), **not** the
     thermal solve (a `/HEAT/MAT` with no `/THERM_STRESS` on the diverging
     mount held dt for 46 000 cycles at zero energy), **not** the card (a
     CONSTANT imposed temperature held dt for 45 000 cycles), **not** the load
     (alpha 1.2e-9, 10 000x smaller, diverges identically), **not** the element
     formulation (Isolid 17/24/1, Ismstr 4/10 and Icpre 1 all diverge; Isolid
     12 "stabilises" only by making the expansion inert, DX = 0, and the
     starter calls it obsolete, `WARNING 1160`), **not** the law (LAW1 and
     LAW36 alike) and it needs more than one element. `/DT/NODA/CST` is not a
     cure either: with `DT2MS = -1e-7` the run stops at cycle 1000 while
     PRINTING **NORMAL TERMINATION**, I-ENERGY 3.089e5 against EXT-WORK 0.099.
     No card-level cure was found, so the card is emitted and the warning
     names the trigger and the prescription (one lateral anchor per
     cross-section, or shells on a through-thickness-integrated law). The
     implicit engine has no thermal solve at all (`grep ITHERM
     engine/source/implicit` -> nothing), which is warned about too.

 18. **`*LOAD_THERMAL_VARIABLE`'s `T = TB + TS*f(t)` needs a synthesized
     curve.** `/IMPTEMP` computes `Fscale_y*f((t-T_start)/Ascale_x)` only
     (`fixtemp.F:180-200`) - there is no additive slot - so the offset is baked
     into a copy of the curve point by point. A constant `*BOUNDARY_TEMPERATURE`
     (`TLCID = 0` -> T is the constant `TMULT`, an OVERRIDE on the LS-DYNA side)
     likewise gets a two-point function: `func_IDT = 0` is `ERROR 120` **once
     per node**. `/INITEMP` is emitted in the group form only - `fld_type = 1`
     takes a per-node list, is accepted at 0 errors and the per-node
     temperatures are LOST (measured: every node came back at the group value).
     dyna2rad converts NO temperature driver at all (`grep` over its whole tree
     for `LOAD_THERMAL` / `INITIAL_TEMPERATURE` / `BOUNDARY_TEMPERATURE` /
     `MAT_THERMAL` / `CONTROL_THERMAL` returns zero hits), and its native reader
     cannot even READ the two carrier decks (`ERROR 100210` on
     `*LOAD_THERMAL_LOAD_CURVE`).

  All five `*MAT_ADD_THERMAL_EXPANSION` carriers in the r14 verification corpus
  convert and start at **0 ERRORS**, `07_metalstrip.k` included (40 x
  `ERROR 495` before).

 19. **Every `*LOAD_THERMAL_*` spelling REPEATS, and the temperature-output
     gate reads what was EMITTED.** The manual says so per keyword - *"Card
     Sets. Include as many sets ... as desired"* (`_CONSTANT` p.33-166,
     `_VARIABLE` p.33-179), *"Node Cards. Include as many cards in this format
     as desired"* (`_CONSTANT_NODE` p.33-169, `_VARIABLE_NODE` p.33-185),
     *"Thermal Load Curve Cards ..."* (`_LOAD_CURVE` p.33-171) - so every
     record is read, and the two CARD-SET spellings walk RAW PAIRS because an
     all-blank card 1 is legal there (NSID defaults to all nodes). `NSIDEX`
     (*"nodes that are exempted from the imposed temperature"*) is SUBTRACTED
     from the `/GRNOD` - `/IMPTEMP` is a hard Dirichlet reset every cycle
     (`fixtemp.F:180-200`), so an exempted node was being driven anyway - and
     `BOXID` is named. `TBIRTH` is not just a gate: `fixtemp.F:118-129`
     evaluates the curve at `t - T_start`, so the driver curve is emitted
     pre-shifted by `-TBIRTH` and LS-DYNA's absolute-time reading is preserved.
     A blank `TMULT` beside a curve is resolved to 1.0 at conversion time
     rather than left to `hm_read_imptemp.F:139`'s own 0 -> 1 default (a cell
     that means the opposite of what it does). `T0 = TB + TS x f(0)`
     (p.33-180 Remark 1) uses the ORIGINAL scale. And the gate that decides
     whether `/TH/NODE TEMP` and `/ANIM/NODA/TEMP` are written now reads
     `state.thermal_driver_emitted`, set at the line that writes an
     `/IMPTEMP`: several corpus decks state a driver on a `*SET_NODE_GENERAL` /
     `*SET_NODE_LIST_GENERATE` k2rad cannot read, so the driver is dropped and
     nothing changes the temperature - `mat-add/main_steel_frame.k` and
     `07_metalstrip.k` are exactly that shape and now get no TEMP channel and
     an explicit "this expansion is INERT" warning instead of a frozen fringe
     (the #122 rule).

  **Post-review verification — three defects the review round itself
  introduced or left, plus one rejection the evidence overturned.** Every one
  reproduced on a converted deck before it was touched.

  V1. **A `*DATABASE_CROSS_SECTION` plane silently lost a real `/BEAM` — a
      REGRESSION against master.** The review round's new "this beam was
      re-routed to a `/SPRING`" filter tested a BEAM eid against
      `state.spring_elem_ids`, which has **nine** producers and only three of
      them beam-derived; the other six are `*ELEMENT_DISCRETE`, `*ELEMENT_PLOTEL`,
      grounding springs, `*CONSTRAINED_JOINT`, `*CONSTRAINED_SPOTWELD` and belt
      springs. LS-DYNA element ids are PER-TYPE namespaces, so `*ELEMENT_BEAM 50`
      and `*ELEMENT_DISCRETE 50` are both legal in one deck (the #125 "one cell,
      two id namespaces" class). Measured on a probe with exactly that pair:
      master emits `/GRBEAM/BEAM/90005` holding `50` with `grbeam_ID = 90005`;
      the branch emitted **no `/GRBEAM` at all**, `grbeam_ID = 0`, and a warning
      blaming a re-route that never happened — while the same deck still wrote
      `/BEAM/2` element 50. Now tested against the three BEAM-derived registries
      only (`dbeam_spring_eids | spotweld_spring_eids | muscle_beam_spring_eids`,
      the last one new). Same fix on the `/TH` door: `_drop_muscle_springs` takes
      the caller's own namespace — `*ELEMENT_BEAM` ids for
      `*DATABASE_HISTORY_BEAM`, `*ELEMENT_DISCRETE` ids for `_DISCRETE` — and the
      `_SEATBELT` arm loses its muscle screen entirely, because no
      `*ELEMENT_SEATBELT` can be a muscle spring.

  V2. **`grsprg_ID` is emitted after all — the "the cfg tree does not carry that
      spelling" rejection was wrong on all four of its legs.**
      `radioss110/SETS/spring.cfg` IS the spring group card (its header reads
      "Group Setup File / /GRSPRI"); `radioss110/SECT/sect.cfg:37` declares
      `grsprg_id = VALUE(SETS,…) { SUBTYPES = (/SETS/GRSPRI) }`; the starter reads
      it (`hm_read_sect.F:301` `HM_GET_INTV('grsprg_id',IGUR,…)`, `:548`
      `NSEGR=ELEGROR(IGUR,IGRSPRING,NGRSPRI,'SPRI',…)`); and k2rad **already
      writes that exact spelling** on the `/PRELOAD/AXIAL` path
      (`writer/preload.py`, merged in #127). So a re-routed connector now goes
      into a `/GRSPRI/SPRI` group named by `grsprg_ID` instead of being warned
      away. Starter-validated on the emitted deck: **0 ERRORS / 0 WARNINGS**,
      with the echo `NUMBER OF SPRING ELEMENTS . . . 1 / SPRING N1 N2 / 50 1 0`.
      Engine-measured on twin decks (imposed velocity through the connector, both
      `NORMAL TERMINATION`): **with** the group every `/TH/SECTIO` channel
      carries data (e.g. `-2.905e-09` at the last state), **without** it every
      channel is `0.000000e+00`. The named loss was avoidable with a card the
      project already writes.

  V3. **`TE` / `TSE` / `TBE` / `LCIDE` are the EXEMPTED nodes' own temperature,
      and the companion `/INITEMP` was reaching nodes the card exempts.** The
      warnings called them "the temperature seen by the thermal-EXPANSION term
      alone". Vol I R17 p.33-167 reads *"TE — Temperature of exempted nodes
      (optional)"* and p.33-180 *"TSE — Scaled temperature of the exempted nodes
      … TBE — Base temperature of the exempted nodes … LCIDE — Load curve ID that
      multiplies the scaled temperature of the exempted nodes"*, under the same
      `T = TB + TS·f(t)` law. Worse, the review round's own NSIDEX fix left an
      internal contradiction: measured on a probe with `NSID 0 / NSIDEX {2,3} /
      T 500 / TE 20`, the `/IMPTEMP` correctly covered `{1,4,5,6,7,8}` at 500
      while the companion `/INITEMP` covered **all eight** nodes at 500 — the
      exempted nodes were initialised at the very temperature they are exempt
      from and then carried no driver at all. Both halves fixed: the companion
      `/INITEMP` inherits the driver's scope, and the exempted nodes get a SECOND
      `/IMPTEMP` of their own carrying `TE` (or `TBE + TSE·f_LCIDE(t)`), which is
      an exact statement of the LS-DYNA card. Engine-measured on a 10-hex bar
      with `TS 1 / TB 0 / LCID f` and `TSE 1 / TBE −80 / LCIDE f`: the 40 driven
      nodes follow 40 → 100 → 120 K and the 4 exempted ones −40 → 20 → 40 K,
      both to the closed form, 0 starter errors, `NORMAL TERMINATION` at 56 028
      cycles. Nothing is invented: a scaled exempt temperature with a BLANK
      `LCIDE` is named and dropped, because the manual prints only a down-arrow
      in that Default cell and guessing a curve would fabricate the whole
      exempted-node history (the #124 rule). `LCIDR` / `LCIDEDR` stay dropped as
      the dynamic-relaxation columns they are.

  V4. **A refused expansion group could hand its parts the OTHER card's
      expansion — a REGRESSION the review round introduced while removing an
      orphan `/MAT`.** When two `*MAT_ADD_THERMAL_EXPANSION` cards name two parts
      that SHARE one MID and the card on the LOWER pid is unresolvable, the
      refusal `continue`d BEFORE the clone, so the refused parts stayed on the
      original mid; the surviving group then satisfied `covered[mid] ==
      all_pids`, kept that same mid, and wrote `/THERM_STRESS/MAT` on it.
      Reproduced on a 2-hex probe (parts 1+2 on `/MAT/ELAST/1`; card A on pid 1
      with `LCID=404` undefined, card B on pid 2 with `MULT=2.4e-5`): ONE
      `/MAT/ELAST/1`, both parts pointing at it, `/THERM_STRESS/MAT/1` carrying
      2.4e-5 — so part 1 expanded although its own card was dropped, while the
      warning said verbatim "the material is NOT split off for it either".
      `_resolve_expansion` is now two passes: pass 1 decides which groups
      survive, and `covered` / `last_group_on` are built from the SURVIVORS, so a
      mid with a refused group is disqualified from keeping the original id and
      the refused parts keep a card-free material.

  Four smaller ones from the same round:

  * `*LOAD_THERMAL_DYNAIN` was a **fabricated keyword** in a user-facing
    catalogue — it appears in no LS-DYNA manual (Vol I R16/R17, Vol III R17) and
    in no shipped `hm_cfg_files` tree. Dropped, and replaced by the spellings
    that DO exist and were unhandled: `*LOAD_THERMAL_RSW`, `_TOPAZ`,
    `_{CONSTANT,VARIABLE}_ELEMENT`, `_VARIABLE_{BEAM,SHELL}`, each named with
    what it states and why `/IMPTEMP` cannot carry it.
  * A zero-force muscle left an **orphaned `/FUNCT`** in the deck: `_resolve_ssp`
    / `_resolve_fpe` emit their function as they mint it, so overwriting `fct4`
    afterwards burned a curve id on a 100-row exponential table nothing
    references. The zero case is now decided first.
  * `/THERM_STRESS/MAT`'s `Fscale_y` was written as a literal `0` and rescued by
    `hm_read_therm_stress.F90:135`'s `0 → 1.0` — the same "a cell that means the
    opposite of what it does" the round fixed elsewhere. Now an explicit `1.0`.
    Physics-neutral and measured so: 46 of the 76 validation decks move by
    **exactly that one line and nothing else**, the starter echoes
    `THERMAL EXPANSION FUNCTION SCALE FACTOR = 1.000000000000` either way, and a
    full engine re-run of `th_c1_free` (56 028 cycles) produces a **byte-identical
    T01**.
  * Two warning texts: the solid prescription now says the anchor must remove
    BOTH transverse translations (one node held in only ONE transverse direction
    still diverges — +0.389 mm, I-ENERGY 2036 against EXT-WORK 4.283, under a
    `NORMAL TERMINATION` banner), and the muscle scale-cell warning no longer
    repeats the deck-specific prefix inside its quoted manual sentence. An INERT
    `/THERM_STRESS/MAT` on a material whose LAW1 was restated to LAW36 now says
    the law changed, because that costs −4.6 % of the time step for a card that
    does nothing.

  **Coverage.** The three `*INCLUDE_TRANSFORM` offset fixes of the review round
  had ZERO tests — reverting each left the FULL suite green — so
  `IncludeTransformOffsetTests` gained five: a negative-PID
  `*MAT_ADD_THERMAL_EXPANSION` under IDMOFF beside a positive one under IDPOFF,
  the SECOND card set of `*LOAD_THERMAL_CONSTANT` and `_VARIABLE` (sets and curve
  cells alike), every row of the three per-row spellings, and
  `*SECTION_SHELL_THERMAL`'s option cell staying UNCHANGED under IDMOFF. All
  thirteen fixes above are mutation-checked on a throwaway copy of the tree:
  reverting any one of them fails at least one test.


- **The PRELOAD / initial-state batch:
  `*INITIAL_STRAIN_SHELL` (+ `_SET`) → `/INISHE/STRA_F/GLOB` and
  `/INISH3/STRA_F/GLOB`,
  `*INITIAL_STRESS_SECTION[_TITLE]` → `/PRELOAD` on a dedicated `/SECT`, and
  `*INITIAL_AXIAL_FORCE_BEAM` → `/PRELOAD/AXIAL` on `/GRBEAM/BEAM` and the new
  `/GRSPRI/SPRI`.** Three keywords that produced no card at all before — two of
  them the entire pre-tension of every bolt in the model, on a conversion that
  ran to termination with the joints loose.

  1. **`/PRELOAD`'s `Fct_ID` column does not exist below `/BEGIN 2026`, and
     dyna2rad's way of using it is identically zero stress even at 2026.**
     `radioss2018/LOADS/preload.cfg` has `%10s _BLANK_` in cols 31-40; the
     `curveid` cell appears only in `FORMAT(radioss2026)`. Twin decks differing
     in nothing but the `/BEGIN` line echoed `IFUNC 0` at 2019, 2021, 2022,
     2023, 2024 and 2025 with `WARNING ID : 100214 unsupported field exists`,
     and `IFUNC 900` at 2026 — and the 2022 pair with and without the function
     produced **byte-identical engine T01 histories**. Worse, the Radioss
     function is a *dimensionless scale* on `Preload`, not the stress itself
     (`sboltini.F:76-81` builds `LOAD·n⊗n`, `boltst.F:83-89` applies
     `SIG = SFAC·BPRELD`, `preload_solid_ini.F90:106` sets `SFAC`), so
     dyna2rad's `Preload = 0.0` + `Fct_ID` (`convertinitialstresses.cxx:801-805`)
     gives `σ = f(t)·0 ≡ 0` — with no diagnostic, because the only warning,
     `MSGID 1255`, is gated on `IFUN == 0`. k2rad therefore resolves the LCID at
     conversion time: `Itype = 2`, `Preload` = the curve's plateau,
     `Tstart`/`Tstop` = the window LS-DYNA's Remark 2 defines, cols 31-40 left
     blank, and a warning naming the curve id, the plateau and both times.

  2. **The lost ramp costs less than it looks, because the WINDOW is what the
     bolt law actually uses.** With no function the stress appears as a hard
     step at `Tstart` (`boltst.F:59-74`, measured: 200 MPa at t = 0), but
     `sboltlaw.F` replaces the material law of the preloaded elements with a
     linear-elastic one at `1e-4·E` until `Tstart + 0.4·ΔT`, ramps the modulus
     to full at `Tstart + 0.7·ΔT`, and then rewrites the reference density so
     the preloaded state becomes the new zero-pressure reference — the preload
     locks, no strain reset. So the tightening DURATION survives even though the
     ramp shape does not. (The 2022 Reference Guide p.2120 says the stiffness is
     restored "at Tstop"; the code restores it at `0.7·ΔT`, and the transient at
     exactly that time is visible in the probe runs.)

  3. **`Tstop` follows LS-DYNA Remark 2, not dyna2rad's `/PRELOAD` loop.** Both
     preload keywords say "when the end of the load curve is reached, **or when
     the value of the load decreases from its maximum value**, the
     initialization stops" (Vol I R17 pp. 3063 and 3144). One shared helper
     keeps the leading non-decreasing run — point 0 always, then every point
     whose ordinate is `>=` the running maximum, stopping at the first strictly
     lower one. dyna2rad implements exactly this for `/PRELOAD/AXIAL`
     (`convertinitialaxialforces.cxx:118-133`) but, for `/PRELOAD`, truncates
     only on an ordinate that is EXACTLY zero
     (`convertinitialstresses.cxx:781-793`), so a curve decaying to a lower
     positive value is not truncated at all. A degenerate window (one point, or
     a curve that falls from the first segment) is refused rather than emitted:
     `sboltlaw.F` divides by `0.3·(Tstop-Tstart)`, and `TFIN == 0` becomes
     `EP30` at `hm_read_preload.F:152`, i.e. a part left at `1e-4·E` for the
     whole run.

  4. **The `/SECT` frame k2rad already emits does not encode the cutting-plane
     normal, so the preload gets its own section.** `hm_read_preload.F:203-217`
     takes the pretension direction from `(N2-N1)×(N3-N1)` of the section's
     three frame nodes and from nothing else. `_sect_frame_nodes` picks the
     three best-CONDITIONED nodes of the cut, which is right for a force-output
     frame and unrelated to the plane: measured on a 1×1×2 bar cut at x = 0.5
     with normal (1,0,0) the starter echoed `NX/NY/NZ = (-0.707, 0, 0.707)` —
     45° off, at zero diagnostics; on the corpus deck the same construction was
     3.35° off. So each `/PRELOAD` now hangs on a **dedicated** `/SECT` with
     three SYNTHESIZED frame nodes placed at the cutting-plane point plus two
     orthonormal in-plane vectors whose cross product is the normal exactly. The
     `*DATABASE_CROSS_SECTION`'s own `/SECT` and its `/TH/SECTIO` scope are left
     untouched — dyna2rad instead OVERWRITES `grbric_ID`/`grshel_ID`/`grtria_ID`
     of the existing section (`convertinitialstresses.cxx:873-875`), silently
     redefining what the user's `*DATABASE_SECFORC` reports.

  5. **`PSID` is a second restriction, intersected — and a blank one means "no
     extra restriction", not "nothing".** Vol I R17 p.3144: "Stress is
     initialized on only those parts included in both PSID from this card and
     the PSID field from the associated `*DATABASE_CROSS_SECTION` card."
     `_plane_cut` grew an optional second part filter and the intersection goes
     into the dedicated section's own `/GRBRIC/BRIC`. dyna2rad's blank-PSID path
     produces an EMPTY intersection and wipes the section's element scope
     (`convertinitialstresses.cxx:822 + 854-858`), which is starter ERROR 1251.

  6. **`/PRELOAD` acts on BRICKS only, and two whole classes of solid take it
     silently and do nothing.** `hm_read_preload.F:233` refuses `NS == 0` with
     ERROR 1251, and `SBOLTINI` is reached only from `sinit3`, `s4init3`,
     `s8zinit3` and `s10init3` — never from `S6ZINIT3` or any thick-shell
     initialiser. So a solid the starter classifies `ISOLNOD=6` keeps a zero
     `BPRELD` and `SECTAREA` (no `ISOLNOD==6` branch) adds nothing to the echoed
     area — when the deck runs at all: measured on an all-penta section spelled
     with BLANK cells 7-8, `Isolid 24` gives `AREA 0.000E+00`, every stress 0 for
     the whole run, 0 errors and 0 warnings, while every other `Isolid` —
     including the 17 this converter emits for ELFORM 1 — is `ERROR 3107`
     "6-NODES PENTAHEDRON (/PENTA6) WITH SOLID PROPERTIES ARE ONLY COMPATIBLE
     WITH ISOLID = 24" and a refused deck (`initia.F:1081-1094`). That
     classification is on the EMITTED card and card FAMILY, not the source
     connectivity — `hm_read_solid.F:167` wants `IXS(8)+IXS(9) == 0`, a wedge
     written the usual LS-DYNA way leaves k2rad as a degenerate HEX8 which IS
     pre-tensioned (measured: `AREA 1.000E+00`, `/TH/BRIC SZ = 200.00 MPa` at t=0
     on both cut wedges of an 8-wedge bolt bar, identical to its hex twin), and a
     4-node tet spelled `n1 n2 n3 n4 0 0 0 0` goes to `/TETRA4`, a card with no
     cells 7-8 at all. Thick shells are
     dropped from the preload group by name — they ride in `solid_eids` so the
     REPORTING section still sees them, and LS-DYNA does not pre-tension them
     either (Vol I R17 p.3145 Remark 4 lists solid element types only). So is
     the formulation: measured at 200 MPa on a 1×1×4 bar, `Isolid` 1 and 2 hit
     ZERO OR NEGATIVE VOLUME at cycle 0, `Isolid 12` is a completely silent
     no-op, `Isolid 24` diverges late in the window and never recovers
     (re-measured 1266 → 1370 MPa against the 200 MPa target; an earlier probe of
     the same bar reached 1400-1500 MPa), and `Isolid` 5, 14 and 17 hold the
     preload.

  7. **`/PRELOAD/AXIAL` shows the OTHER half of the version-gate rule, so it is
     emitted.** `/PRELOAD/AXIAL` exists only as `FORMAT(radioss2024)`, but a new
     KEYWORD falls back to the newest format and parses correctly, where a new
     FIELD inside an old keyword is dropped (finding 1). Twin decks at `/BEGIN`
     2022, 2024 and 2026 echoed an identical `BOLT 1D-ELEMENT PRELOADINGS` table
     and produced bit-identical engine T01 histories; 2022 adds only `WARNING ID
     : 100211 Unsupported option /PRELOAD/AXIAL in format < 2024`, which k2rad
     restates instead of hiding. This is the `#119` mode-(a) case, and the
     contrast with `/PRELOAD`'s Fct_ID in the same batch is why the twin-deck
     test is not optional.

  8. **One `*SET_BEAM` can straddle two Radioss element families, and one
     `set_id` resolves to exactly ONE of them.**
     `hm_read_preload_axial.F90:262-292` scans `/GRSPRI`, then `/GRBEAM`, then
     `/GRTRUSS` and takes the first non-empty match, so a single card would
     preload the springs and silently drop the beams. The BSID is split by what
     was ACTUALLY emitted — `state.beam_elem_ids` vs `state.spring_elem_ids`,
     the registries filled at each write line — into one `/PRELOAD/AXIAL` per
     family. That needed the first `/GRSPRI/SPRI` emitter in the converter
     (`radioss110/SETS/spring.cfg:98`, `hm_lecgrn.F:645`). Ids in neither
     registry are named and left out: a group naming an element the deck does
     not define is starter ERROR 69.

  9. **A spring's PROPERTY decides whether it can be preloaded at all, and
     getting it wrong is a hard stop.** `rinit3.F:1627-1690` accepts
     `CASE(4,13)` only with a non-zero axial `fct_ID1` **and** a hardening flag
     `H` in 1..7 (else ERROR 3057) and `CASE(23)` only with `MTN == 113` (else
     ERROR 3053) — so a `/PROP/TYPE8` discrete-beam connector, a
     `*CONSTRAINED_SPOTWELD` tie and a `*MAT_SPOTWELD` with `SIGY = 0` all
     refuse the deck outright. New registry `state.spring_axial_preloadable`,
     filled at the two write lines whose property can qualify, gates the
     emission; everything else is warn-dropped by name with the error id.

  10. **Truncating the axial curve is what makes the bolt behave like LS-DYNA,
      and it does NOT snap the force back.** `preload_axial.F90` takes
      `t_start`/`t_stop` from the FUNCTION's own abscissa range and inside that
      window replaces the element's axial force outright (`stf_f` is
      unconditionally zero). Measured on twin beams — a curve ending at 1e-4 vs
      one flat to 1e30 — the force after `t_stop` does not reset: the element's
      rate-form law resumes from the force it holds and oscillates about it
      (mean ≈ 1000 N in the probe, and 28.8 kN on the corpus bolt). That is
      exactly LS-DYNA's "the initialization stops", so the leading
      non-decreasing run is the right window.

  11. **`*INITIAL_STRAIN_SHELL` is not `*INITIAL_STRESS_SHELL` with a different
      name.** `LARGE` is cell 4 and `ILOCAL` cell 8 (cols 71-80) on card 1,
      there are no NHISV/NTENSR/thermal cards at all, the small strain card is
      `EPSxx..EPSzx T` (7×10, T LAST, where the stress card has T FIRST) and the
      large form is 5×16 + **2**×16 (`Keyword971_R13.0/TABLE/
      initial_strain_shell_subobj.cfg:110-142`). Re-pointing the stress walker
      at it would have read the wrong `LARGE` cell and sliced the 16-wide cards
      at width 10.

  12. **`npg = 1` on a strain-ONLY deck, because `npg = 4` fails two different
      ways there.** Measured with `/PROP/SHELL Istrain=1` and `/TH/SHEL` read at
      t = 0: `npg=4` on `Ishell=24` (QEPH) yields `E1 = 0` — a SILENT no-op,
      because `hm_read_inistate_d00.F:2498-2512` assigns `IHBE` only on its
      `npg<=1` branch and then still tests it to write the `SIGSH(INISHVAR1)`
      marker and the `PT+1` shift that `cstraini4.F:107-110` reads back — and
      `npg=4` on `Ishell=1..4` is starter ERROR 1904. `npg=1` is consumed
      correctly by BT, BATOZ, QEPH and both SH3N formulations, so one uniform
      form removes both branches. The 2022 Reference Guide p.2048 pairs `npg=4`
      with BATOZ; on a strain-only deck the measurement says it is not required.
      A deck that also emits an initial-STRESS block is a different case —
      see "Mixed initial-stress + initial-strain decks" below.

  13. **`nb_integr = 2` is not a simplification — the reader keeps two
      stations.** `hm_read_inistate_d00.F:2525-2528` reads `NPP*NPG` values and
      then stores `DO N=1,MIN(2,NPP)`, where the STRS_F branches at `:2207`,
      `:2274`, `:3348` and `:3417` all use the full `DO N=1,NIP`. Radioss
      rebuilds membrane + one curvature from the pair (`cstraini4.F:120,153-158`
      with `AA = HALF·THKE`), so the two EXTREME stations with their own T
      values are exact for a linear through-thickness field and the best fit
      otherwise. The layer-count cross-check that guards the STRS_F variants
      does not fire here (with only STRA_F present `ITHKSHEL = 2` and
      `ISIGSH = 0`, so both branches of `csigini.F:144-163` are skipped) —
      verified: `nb_integr = 2` against `/PROP/SHELL N = 5` runs clean and the
      strain is consumed. (With a stress block present those checks DO fire; see
      below.) A record that states one station, or leaves the T column blank, is
      written at `T = -1` and `T = +1`, because two records at the same
      parametric position is ERROR 1904 — and the two cases are reported
      separately, since replicating ONE station is a genuine zero-curvature
      membrane state while placing two blank-T rows at ±1 INFERS the positions
      and turns the difference between them into a curvature.

  14. **`eps_XY/YZ/ZX` is the TENSOR component on both sides.** `CG2LEPS`
      (`scigini4.F:791-834`) rotates the full 3×3 tensor into the element frame
      and outputs `EPS(3) = TWO*UXY`, i.e. the starter itself doubles the card
      value into the engineering shear held in `GBUF%STRA` — measured, a card
      `eps_XY = 0.005` reads back as `/TH/SHEL E12 = 0.01`. LS-DYNA documents
      `EPSij` only as "the ij strain component ... in the GLOBAL Cartesian
      system" (Vol I R17 p.3121) and dyna2rad copies it unscaled too, so the
      copy is 1:1 — and the assumption is stated in a warning whenever a shear
      component is non-zero, since a source deck holding engineering shears
      would be off by exactly 2.

  15. **`/PROP/SHELL Istrain` is forced on whenever an initial strain exists —
      as defence-in-depth, not because the block would otherwise be inert.**
      k2rad set `Istrain` from `*DATABASE_EXTENT_BINARY STRFLG` alone; one
      shared `_shell_istrain_flag` now drives the plain and the composite
      property writers so a deck carrying `*INITIAL_STRAIN_SHELL` without
      `STRFLG` gets it too. What it buys is a correctly SIZED strain buffer:
      `elbuf_ini.F:1584` allocates `GBUF%G_STRA = 8` only for
      `ISTRA > 0 .OR. IFAIL > 0 .OR. ...`, the /PROP/SHELL property tag leaves
      `PTAG%G_STRA` at 0, and `cbainit3.F:549` calls the ingest regardless —
      `cstraini4.F` then writes its membrane average into that buffer.
      **Correction to an earlier draft of this entry**, which claimed the block
      would be "accepted, echoed and ignored" citing `csigini.F:165`: that is
      NOT reproducible on this build. Twin decks with `Istrain` hand-set back to
      0 (Ishell 12 / 24 / 1, with and without a `/FAIL`) read the strain back
      IDENTICALLY — `/TH/SHEL E1 = 0.01`, `K1 = 0.02` either way, and a
      `/FAIL/TENSSTRAIN` deletion still moves to the same t. The ISTRAIN gate at
      `csigini.F:165` / `scigini4.F:168` is simply not the path these
      formulations take: `cbainit3.F:549` reaches `cstraini4.F`, which takes
      `ISTRAIN` as an argument and never reads it.

  16. **`ILOCAL=1` is dropped by name, not routed to the local card.** LS-DYNA
      documents the value itself as "local (not supported)" (Vol I R17 p.3121),
      and the Radioss local `/INISHE/STRA_F` is not the local twin of the GLOB
      flavour but a different quantity — `eps_1 eps_2 eps_12 eps_23 eps_31` plus
      curvatures `k1 k2 k12`, one group per `npg`, with no `eps_ZZ` and no `T`
      (`radioss110/TABLE/inishe_stra_f_sub.cfg`). Writing element-local
      components into the GLOB card would ask `CG2LEPS` to rotate an already
      local tensor.

  17. **A registry audit found a live node-id collision that predates this
      batch.** `_make_probe_rbody` (the implicit no-rigid-body guard) and the
      `--ground-springs` path both allocated off `max(state.nodes) + 1` and then
      never registered the result, breaking the invariant
      `next_node_id`'s docstring names. Measured: on the implicit
      `4.3_General_Nonlinearity` deck the three synthesized `/PRELOAD` frame
      nodes were handed the SAME ids 472950-472952 as the probe rigid body's.
      Both sites now draw from `state.next_node_id()`, which reserves what it
      returns — byte-identical ids on every existing deck, and the class is
      closed for the next synthesis site. Also added, per `#125`, the deck-wide
      `_warn_duplicate_preload_ids` (`/PRELOAD` and `/PRELOAD/AXIAL` are one
      keyword to `hm_read_preload.F:110`'s option loop, so they share an id
      namespace) and `_warn_duplicate_sect_ids`.

  18. **`*INCLUDE_TRANSFORM` buckets come from the same dict the handlers do.**
      `ISSID` → IDROFF, `CSID` → IDPOFF (Vol I R17 p.2979 names CROSS SECTION ID
      explicitly under it), `LCID`/`ISTIFF` → IDFOFF, `PSID`/`BSID` → IDSOFF,
      `VID` → IDDOFF, `EID` → IDEOFF and the `_SET` shell-set id → IDSOFF. The
      strain walk is a callable sharing `handlers.initial_strain_shell_records`
      with the parser, because a flat `data` spec would read a strain of `1.5`
      as the id `1` and rewrite it to `1 + IDEOFF`, and because an all-blank
      strain card is legal and must not be mistaken for the next record's card 1
      (`#119`). `*INITIAL_AXIAL_FORCE_BEAM` takes a `data` walk since the card
      may repeat. Both strain spellings join `_DIRECTION_BEARING`.

  19. **A bolt preload silently takes Ismstr=10 away from the parts that need
      it.** `sgrtails.F:1387-1412` shifts a PRELOADED element group's Ismstr
      10 -> 4 (11 -> 1, 12 -> 2) with WARNING 1775, and k2rad sets Ismstr=10 on
      exactly the parts that need it: `/XREF` reference geometry, `/MAT/LAW95`
      (MAT_077_H with N=0) and `/MAT/LAW90` (MAT_073). Two write-line
      registries let the `/PRELOAD` writer name the affected PARTS at
      conversion time, where the starter reports the shift only per element and
      only after the fact.

  20. **One shell named by two initial-strain records loses one of them
      silently.** The starter keeps a single strain slot per element
      (`SIGSH(...,PTSHEL(IE))`, `hm_read_inistate_d00.F:2486-2492`), so two
      cards — or a card plus a `_SET` that contains the element — leave the LAST
      one read in force with no diagnostic. Scanned and named, the same
      per-namespace discipline `#125` added for `/MAT` and `/PROP`.

  **Validation.** Starter AND engine, not emission alone.
  *Bolt (synthetic 1×1×4 bar, cut at brick 2, 200 MPa over [0, 2e-4]):* starter
  **0 ERRORS, 0 WARNINGS**, echo `AREA 1.000E+00 · NX/NY/NZ 0/0/1 · PRELOAD
  2.000E+02 · START-T 0 · END-T 2.000E-04 · IFUNC 0` — the direction is exactly
  the cutting-plane normal. Engine NORMAL TERMINATION over 2813 cycles:
  `/TH/BRIC` `SZ` of the preloaded brick is **200.00 MPa at t = 0** and
  **200.3 MPa at t = 4e-4**, well past `Tstop`, and all four bricks settle to
  ~200 MPa — the uniaxial equilibrium a fixed-ended bar must satisfy.
  *Axial (r14 `mainboltaexpl.k`):* starter 0 ERRORS, echo `BOLT 1D-ELEMENT
  PRELOADINGS 90021 · 90020 · SPRING · 0 · 90019 · 1.000E+00 · 0.000E+00`.
  Engine NORMAL TERMINATION over 51762 cycles: `/TH/SPRING FX` = 10225 N at
  t = 3.55e-4 against `28800 × 0.355 = 10224` — exactly on the ramp — then free
  oscillation about the plateau, no snap-back.
  *Strain (synthetic quad + collapsed triangle, both fully fixed):* starter 0
  ERRORS. `/TH/SHEL` at t = 0 reads `E1 = 0.01`, `K1 = 0.02` and `E12 = 0.01`
  from a card carrying `eps_XX` 0.0/0.02 at `T = ∓1` and `eps_XY = 0.005` — the
  hand-computed membrane/curvature split (`AA = 0.5·Thick`, `κ = Δε/(AA·ΔT)`)
  and the tensor→engineering doubling, both exact. The `/SH3N` twin reads
  `E1/E2/E12 = 0.008/0.002/-0.008` for a global `eps_XX = 0.01`: the same tensor
  rotated into the triangle's own frame, trace preserved. Re-run with
  `--shell-formulation qeph` — the formulation on which `npg=4` is a
  measured silent no-op — the same deck reads back `E1 = 0.01`,
  `E12 = 0.01`, `K1 = 0.02` unchanged, which is what makes `npg=1`
  safe for every formulation rather than merely convenient.
  *Corpus:* `4.3_General_Nonlinearity.key` emits one `/PRELOAD` on `/SECT/90011`
  with `NZ = 1.0`, `PRELOAD = 100`, `END-T = 0.25`, and the PENTA guard fires on
  part 3; its 486 `ERROR 611` contact-preconditioning errors are pre-existing and
  unchanged.

  **Sweep.** 559 decks (this repo, the r14 dynaexamples corpus, the Ryan-Lee
  examples, `E:\openradioss_run\ls-dyna_example` and the two Toyota production
  models), converted with master and with this branch and compared by SHA-256:
  **555 byte-identical starters, 559 byte-identical engines, 0 conversion errors
  on either side.** The four movers are exactly the four corpus carriers the
  scan found — the three copies of `4.3_General_Nonlinearity` and
  `mainboltaexpl.k` — each losing one entry from `skipped_keywords` and gaining
  2-3 warnings. Every emitter in this batch draws its first id only when its
  keyword is present, which is what keeps the other 555 unchanged.

  **Review round — mixed initial-stress + initial-strain decks, and two
  false-positive warnings.** The reviews found that the batch above is correct
  on a strain-ONLY deck and breaks on the shape LS-DYNA itself writes.

  R1. **A deck carrying BOTH initial-state keywords was ERROR TERMINATION — a
      REGRESSION against master, which simply skipped the strain keyword.**
      Reproduced on a 3-element hand-written deck (one `*INITIAL_STRESS_SHELL`,
      one `*INITIAL_STRAIN_SHELL`, `STRFLG=1`): master 0 errors, this branch
      **8 errors, ERROR TERMINATION** — 4× `ERROR 26` on the strain element and
      4× `ERROR 1904` on the stress element. Two independent causes:

      * Reading a `/STRA_F` block sets `ITHKSHEL = 2` **globally**
        (`hm_read_inistate_d00.F:2469`, its own comment: "instead of ISIGSH to
        avoid memory issue in case of STRA_F w/o STRS_F"). `scigini4.F:168` then
        runs the strain reconstruction for every element whose `SIGSH(17)` is
        set — and the STRS_F reader sets that same flag (`:2164`). A stress-only
        element enters with an empty payload, reads `Z1 == Z2 == 0` and raises
        `ERROR 1904` once per Gauss point.
      * A `/STRS_F` block sets `ISIGSH`, which un-gates the layer/Gauss
        cross-checks. `npg = 1` then leaves `NPGI = 0` against `csigini4`'s
        `NPG = 4` on BATOZ, and `nb_integr = 2` mismatches any `/PROP/SHELL`
        `N != 2` — both `ERROR 26`.

      Fixed by making the strain card agree with the property once a stress
      block exists: `npg` per formulation (4 on Ishell 12; 1 on QEPH, where the
      reader fills `NPGI` itself and `npg=4` is the measured silent no-op; 1 on
      `/INISH3`), `nb_integr` = the property N with the record's two stations
      re-sampled onto N positions spanning T = −1..+1 (the starter keeps the
      first two and the reconstruction is affine, so this is EXACT, not an
      approximation), and an all-zero companion record for every stress-carrying
      quad the strain keyword does not name. The companion is not an invented
      quantity — an element no `*INITIAL_STRAIN_SHELL` card names has zero
      initial strain in LS-DYNA — and it is measured inert: the stress element's
      `/TH/SHEL` channels (`F1 101.25 · F2 201.25 · F12 50.625 · M1 0.208333`)
      are IDENTICAL to the same deck with no strain block at all. Re-measured
      end to end through the converter: **0 ERRORS, NORMAL TERMINATION**, and
      the strain element still reads `E1 = 0.01`, `K1 = 0.02` — at `N = 2`, at
      `N = 5`, and on `--shell-formulation qeph`. A strain-only deck keeps the
      compact `nb_integr=2 / npg=1` card unchanged, so nothing already validated
      moved. One configuration is refused rather than emitted: if the
      initial-state shells do not all share one formulation AND an `npg>1`
      record exists, a stale `IHBE` on the reader's `npg>1` branch could shift a
      BATOZ record's payload by one slot, so the strain block is dropped with a
      warning and the stress is kept.

  R2. **The PENTA warning fired on correct decks.** It classified from the
      LS-DYNA source connectivity (`len(unique(nodes)) == 6`), but the /BRICK
      writer pads a short list with `nodes[-1]` and `hm_read_solid.F:167` only
      sets `ISOLNOD=6` when cells 7 AND 8 are BLANK. So the usual LS-DYNA wedge
      leaves k2rad as a degenerate HEX8 and IS pre-tensioned — measured on an
      8-wedge bolt bar: `AREA 1.000E+00` (identical to its hex twin) and
      `/TH/BRIC SZ = 200.00 MPa` at t=0 on both cut wedges, holding past
      `Tstop`. The warning told the user their bolt silently carried less than
      the card asks and prescribed a remesh, on a deck where nothing was wrong —
      the `#125` class. Re-gated on the EMITTED spelling, which is the only one
      that loses the preload; the corpus carrier's assertion was inverted to
      match, and a synthetic pair (degenerate vs blank-cell) now covers both
      sides.

  R3. **`Isolid = 5` was flagged as unsupported without ever being measured.**
      `*CONTROL_HOURGLASS` IHQ 4/5 maps to it, and it holds the preload as well
      as Isolid 17 does — measured 200.0 MPa at t=0, 199.1 after `Tstop`, 0
      ERRORS, NORMAL TERMINATION. Added to `_PRELOAD_STABLE_ISOLID`; the
      Isolid 24 divergence in the same message was re-measured and stands
      (1266 → 1370 MPa against a 200 MPa target). Both arms now have synthetic
      tests — the whole guard could previously be deleted with the suite still
      green.

  R4. **Thick shells reached the preload group and were silently un-preloaded.**
      `_plane_cut` appends `state.tshell_elems` to `solid_eids` on purpose so a
      section through a thick-shell part still records force, but `SBOLTINI` is
      reached from no thick-shell initialiser, and `_warn_preload_formulation`
      resolved the part through `state.sec_solids` and `continue`d past them. So
      they sat in the `/GRBRIC`, were counted in the starter's `NS` and carried
      no pre-stress. Split out of the preload group by name; the reporting
      `/SECT` keeps them. LS-DYNA does not support it either (Vol I R17 p.3145
      Remark 4).

  R5. **Smaller corrections.** The preload's section-node `/GRNOD` now draws
      from `next_grnod_id()` — a user `*SET_NODE` at or above the auto base is
      re-emitted verbatim and would collide (starter `ERROR 79`, a refused
      deck); the `/PRELOAD` id gained the `while ... in used_preload` retry its
      two sibling allocators already had; a preload window that closes AFTER
      `*CONTROL_TERMINATION ENDTIM` is now named (`sboltlaw.F:119-128` holds the
      bolted parts at `1e-4·E` until `0.4·ΔT` and restores them at `0.7·ΔT`, so
      a run that ends first never gets its stiffness back, silently — the
      normal shape when the source deck tightened the bolt inside a
      `*CONTROL_DYNAMIC_RELAXATION` phase); the blank-T report was split from
      the single-station one; the `ISTIFF` comment was corrected (it is a curve
      id, per Vol I R17 p.3144, not a flag encoding) and the drop
      message now describes both spellings; and an audit of the stress path
      found that a `*INITIAL_STRESS_SHELL` record on a 3-node shell is written
      into `/INISHE`, which the starter resolves against the 4-node table only —
      dropped into its NONEXIST tally, now named.

  **Verification round — one silent-wrong-physics regression, one fabricated
  input field, and four claims that did not survive re-measurement.** The
  post-review verification ran the review round's own new paths on the real
  starter/engine.

  V1. **The 3-node-shell stress record R5 merely NAMED had to be dropped from
      the deck: written alongside the review round's new `/STRA_F` block it
      fabricates stress on an unrelated element.** `hm_read_inistate_d00.F:2105`
      arms the global `ISIGSH` BEFORE it looks the shell_ID up (`:2124-2127` only
      bumps `NONEXIST`), so an unresolvable record leaves the flag on with no
      resolvable payload behind it. `scigini4.F:285` `IF (ISIGSH==0) CYCLE` then
      passes for a strain-only quad whose `SIGSH(17)` the `/STRA_F` reader set to
      ONE, and `:287` runs the GLOBAL stress reconstruction over slots that hold
      no stress. Measured on deck `m7` (quad 1 = `*INITIAL_STRAIN_SHELL`, tri 2 =
      `*INITIAL_STRESS_SHELL`, everything clamped): quad 1 read
      `F1 = -0.24875 · F2 = -0.247875 · M1 = 1.50298` constant for all 163
      states on a deck that states no stress at all, at **0 starter ERRORS and
      NORMAL TERMINATION** — for scale, the only genuine initial moment in these
      probes is `M1 = 0.208333`, seven times smaller. Master cannot produce it
      (it never writes a `/STRA_F` block). The record is now left out of the
      `/INISHE` block by `_inishe_stress_entries`, which the writer's existing
      warning already told the author had happened. Post-fix `m7` is byte-equal
      to its `m7b` control (the same deck with the stress keyword removed) on
      **every one of 20 channels × 163 states, on both elements**, `max|F*|` and
      `max|M*|` on quad 1 exactly 0, strain unchanged (`E1 0.012 · E2 -0.003 ·
      E12 0.004 · K1 0.004`), starter 0 ERRORS / 1 unrelated WARNING 1084,
      engine NORMAL TERMINATION 163 cycles. Dropping the record also un-mixes a
      deck whose ONLY stress record was on a tri, so its strain card returns to
      the compact `nb_integr=2 / npg=1` form.

  V2. **`*INITIAL_STRESS_SHELL` has no `ILOC` field — the parser was reading a
      cell LS-DYNA does not define, and the review round's companion synthesis
      would have mis-framed it.** Card 1 is eight fields, `EID/SID NPLANE NTHICK
      NHISV NTENSR LARGE NTHINT NTHHSV` (Vol I R17 p.28-95, identical in R16 and
      in `Keyword971/TABLE/initial_stress_shell_subobj.cfg`), and the card's own
      text says "SIGij Define the ij stress component. The stresses are defined
      in the GLOBAL cartesian system" (p.28-98). `ILOCAL` exists only on
      `*INITIAL_STRAIN_SHELL` (p.28-67 card 1 field 8), which k2rad reads
      correctly at its own index. Reading cols 81-90 as an ILOC flag switched
      the writer to the local `/INISHE/STRS_F` card, which has no σzz and no T
      slot — real data loss driven by a value LS-DYNA ignores. Worse in
      combination: the local reader sets `SIGSH(17) = ZERO`
      (`hm_read_inistate_d00.F:2355`) while the `/STRA_F/GLOB` reader sets it to
      ONE (`:2495`) and is read LAST, so the review round's all-zero companion
      record would have flipped a LOCAL payload (6 values per point) into the
      GLOBAL reader (8 per point, with a `CG2LSIG` rotation). The ILOC parse is
      gone; the local writer branch with it; a non-zero ninth cell is reported
      and ignored, the way LS-DYNA treats it. Control: the pre-fix tree
      converting the conforming 8-field deck and the fixed tree converting the
      9-cell deck produce **byte-identical starter AND engine files**
      (`24e9e11e…` / `a7578d9d…`), and that deck runs 0 ERRORS / NORMAL
      TERMINATION 133 cycles with the stress consumed.

  V3. **The re-gated PENTA classifier still read the LS-DYNA connectivity, so it
      fired on tets.** `mesh.py` sends any solid with 4 distinct nodes to
      `/TETRA4` (and a 10-node one to `/TETRA10`) — cards with no cells 7-8 at
      all — but a tet spelled `n1 n2 n3 n4 0 0 0 0` still has zeros in its raw
      row, so R2's blank-cell test flagged it and prescribed a remesh on a bolt
      that pre-tensions correctly (`SBOLTINI` IS reached from `s4init3`). The
      test now runs only on elements that reach the `/BRICK` branch.

  V4. **The PENTA message's measured claim held for only one property.** It
      asserted "AREA echoes 0.000E+00, every element stress stays 0 … at 0
      starter errors and 0 warnings" unconditionally; that is the `Isolid 24`
      outcome. At every other `Isolid` — including the 17 this converter emits
      for `*SECTION_SOLID` ELFORM 1 — a real `ISOLNOD=6` penta is `ERROR 3107`
      and a refused deck. Both outcomes are now named.

  V5. **Three more statements corrected against their own authority.**
      (a) `ISTIFF` is a `*DEFINE_CURVE` id in BOTH spellings — "GT.0: Load curve
      ID defining stiffness fraction as a function of time" and "LT.0: |ISTIFF|
      is the load curve ID for the stiffness fraction as a function of time"
      (Vol I R17 p.3144); the sign selects only whether the preload stress is
      auto-adjusted ±10%. R5 fixed the rarer spelling and left the common one
      described as a bare flag, so the reader was never told a curve reference
      had been dropped. Both the offset-bucket comment and the drop message now
      name the id in both spellings.
      (b) The `ENDTIM` warning's consequence was true only below
      `Tstart+0.4·ΔT`. `sboltlaw.F:120-127` is `REDUC = 1e-4·(1-w) + w` with
      `w = (TT-T1)/(T2-T1)` on the ramp, so a run ending between `0.4·ΔT` and
      `0.7·ΔT` is soft by far less than 1e4 — measured 0.328 of `E`
      (analytic 0.3334) on a fully kinematically prescribed hexa, against
      1.033e-4 (analytic 1e-4) for a run ending inside the hold. The message now
      splits by where `ENDTIM` lands and quotes the fraction actually reached.
      (c) The `NPLANE>1` averaging warning stated the emitted card's `npg`, which
      the handler cannot know: it said `npg=1` while the writer emits `npg=4` on
      `Ishell 12` once a stress block exists. The npg sentence moved to the
      writer, where the decision is made.

  **Verification sweep.** 94 decks (the whole `preload_val` validation set, every
  review-round probe and every fidelity probe) converted with the branch before
  and after this round and compared by SHA-256: **0 conversion errors, 6 movers,
  all `_0000.rad` only** — the two tri-stress decks (the unresolvable record
  disappears) and the four ILOC probes (local card → GLOB card, σzz and T
  restored). Every solver-validated deck — `s1_*`, `a1_*`, `e1_*`, `e2_*`,
  `t5_*`, `w1_*`, `c1_*`, `m1`-`m6`, `m8`, `m9`, `bolta`, `gn43` — is
  byte-identical on BOTH files. The same 559-deck corpus, converted with the
  branch before and after this round: **0 conversion errors, 0 movers** — every
  `_0000.rad` AND `_0001.rad` byte-identical, so this round moved nothing in the
  corpus, only in the shapes it exists for.

- **The seatbelt / restraint batch:
  `*ELEMENT_SEATBELT` → `/SPRING` on `/PROP/TYPE23` + `/MAT/LAW114` (1D) or
  `/SHELL` on `/PROP/TYPE9` + `/MAT/LAW119` (2D),
  `*ELEMENT_SEATBELT_SLIPRING` → `/SLIPRING/SPRING`,
  `*ELEMENT_SEATBELT_RETRACTOR` → `/RETRACTOR/SPRING` with
  `*ELEMENT_SEATBELT_PRETENSIONER` folded onto its card 3,
  `*ELEMENT_SEATBELT_SENSOR` → `/SENSOR/ACCE|TIME|DIST`,
  `*ELEMENT_SEATBELT_ACCELEROMETER` → `/ACCEL` + `/SKEW/MOV` + `/ADMAS/0`,
  `*SECTION_SEATBELT` → `/PROP/TYPE23`, `*MAT_SEATBELT` / `*MAT_B01` (+ both
  `_2D` spellings) → `/MAT/LAW114` or `/MAT/LAW119`, `*DATABASE_SBTOUT` →
  `/TH/SLIPRING` + `/TH/RETRACTOR`, and `*DATABASE_HISTORY_SEATBELT` now
  LIVE.** Eleven keywords that landed in `skipped_keywords` before, on a
  conversion that ran to termination with the occupant unbelted.

  1. **The force–strain curve crosses between the two solvers UNTOUCHED, and
     that is a measured fact rather than an omission.** LS-DYNA's `LLCID` is
     "the points of which are (Strain, Force). Strain is defined as engineering
     strain"; `/MAT/LAW114`'s `fct_load` is evaluated at
     `ε = (L − L₀)/max(L₀, LMIN)` — `r23l114def3.F:366` sets
     `XL0 = MAX(X0, LMIN)` and `redef_seatbelt.F90:162` divides by it — and the
     starter names the axis on the listing itself:
     `FORCE-ENGINEERING STRAIN CURVE`. Same quantity on both axes, so `Xscale`
     and `Fscale` stay at the reader default and no transform is applied.
     This is the one curve in k2rad that needs none.

  2. **`K` and `C` are left 0 on purpose, and `C = 0` is a MATCH.**
     `law114_upd.F:80,126` raises `K` to the maximum curve slope ÷ `Xscale` —
     the exact tangent — and answers `WARNING 1640` plus an overwrite if a
     smaller one is stated, so 0 is the only value that cannot be wrong. With
     `C = 0` the starter computes its own belt damping
     (`SEATBELTS DEFAULT DAMPING COMPUTATION` on the listing), which is exactly
     what LS-DYNA's 1D belt does — its damping is automatic and capped at
     `0.1·mass·v_rel/dt`. `DAMP` on card 1 is LS-DYNA's *shell* Rayleigh
     coefficient, so on a 1D belt nothing is lost and the note says so instead
     of reporting a phantom gap.

  3. **`ρ × Area == MPUL`, and the SPLIT decides the stiffness.** Mass is
     `GEO(1) · max(L₀,LMIN) · RHO` (`rinit3.F:464,474`), so the product fixes
     the mass whichever way it is split — but the area also sets
     `XK_COMP = E·AREA` (`r23l114def3.F:224`) and through it the element time
     step. So it comes from `*MAT_SEATBELT` card 2's `A`, the belt's real
     cross-section, and never from `*SECTION_SEATBELT`'s `AREA`, which LS-DYNA
     uses only for contact stiffness and defaults to 0.01 — a search parameter,
     not a webbing section. dyna2rad reads the same cell
     (`convertprops.cxx:2538`) and ignores the section card entirely; k2rad does
     the same and names the drop.

  4. **`Imass` is written 1 always.** It is inert for LAW114 —
     `rinit3.F:331-334` and `:453-456` force `IMASS = 1` for `MTN == 114`, and a
     twin probe differing only in that cell gave bit-identical total mass, total
     inertia and every element and nodal time step. What it is not is
     cosmetic: dyna2rad writes 2 whenever the material states no cross-section
     (`convertprops.cxx:2549`), which makes the starter listing print
     `SPRING VOLUME` for a number that is an area, in the one artefact an
     engineer reads to check the model.

  5. **With no card 2 the belt is TENSION-ONLY, and that is reached by writing
     ZERO.** `hm_read_mat114.F:169-170` has the `F_MAX = INFINITY` default
     *commented out*, so a blank `FMAX` really is 0; with `E = 0` the
     compression tangent `E·AREA` is 0 too, and `redef_seatbelt.F90:310-311,
     478-482` then gives no compressive force at all — LS-DYNA's "zero forces
     being generated whenever the strain becomes negative", exactly. A
     "helpful" non-zero `FMAX` would give the belt compressive strength the deck
     never asked for. When card 2 IS present the LS-DYNA defaults are applied —
     `J = 2I`, `AS = A`, `F = M = 1e20`, `R = 0.05` — because each is real
     physics a blank cell *states*; dyna2rad's `CopyValue` does no defaulting at
     all (`convertutilsbase.cxx:101-137`), so a blank `F` reaches LAW114 as
     `FMAX = 0` on a deck that explicitly asked for the bending model.

  6. **`SLEN` is warn-dropped with the physics cost named.** Radioss forms the
     strain from the element's initial *geometric* length
     (`r23l114def3.F:263` `X0 = ALDP` at `TT == 0`) and nothing on `/SPRING`,
     `/PROP/TYPE23` or `/MAT/LAW114` shifts it — `LMIN` floors the DENOMINATOR
     only, leaving `(L − L₀)` untouched, so it cannot express slack either. The
     converted belt therefore starts taut: it carries load at once instead of
     after the slack is taken up, so the occupant is restrained earlier and the
     peak belt force is higher. Baking it into the mesh would move every other
     element sharing those nodes, so the warning names the loss and points at
     `/INISPRI`. dyna2rad never reads the field — `grep '"SLEN"'` over its whole
     tree returns zero hits.

  7. **The device anchorage node is SPLIT off the belt, and without it the deck
     does not start.** LS-DYNA lets a retractor's `SBRNID` be a node of its
     mouth element and a slipring's be the node its two strands share; Radioss
     requires a separate COINCIDENT node — `hm_read_retractor.F:341-345` raises
     `ERROR 2030 ANCHORAGE NODE ID=n CANNOT BE ON THE SEATBELT`, with
     `ERROR 2029`/`2004` for the slipring. MEASURED: copying `SBRNID` straight
     through, which is what dyna2rad does
     (`convertelements.cxx:862 CopyValue(…, "SBRNID", "Node_ID")`), gave
     `ERROR TERMINATION / 1 ERROR(S) / --- SEATBELTS` on the very first probe
     deck built from a faithful LS-DYNA belt. So the BELT gets a new node at the
     same coordinates and the ORIGINAL keeps its id and every structural
     attachment — that direction and not the reverse, because the anchorage is
     the thing bolted to the car and a fresh node has nothing holding it.
     Nothing else has to constrain the new node: the device imposes the tie
     itself as a kinematic condition (`kine_seatbelt_force.F:112-127` adds the
     mouth node's whole force and stiffness onto the anchor and then zeroes its
     acceleration; `kine_seatbelt_vel.F:188-190` sets its velocity to the
     anchor's plus the material flow), which is precisely what the shared node
     expressed.

  8. **`TDEL` and the pretensioner's `TIME` fold into the sensor as a FULL
     copy.** `/RETRACTOR/SPRING` has no `Tdel` cell at all — locking happens in
     the same cycle the sensor's `TSTART` is passed
     (`material_flow.F:695-702`), gated only by `LOCK_PULL >= Pullout`. So the
     delay has to live on the sensor, and dyna2rad's duplicate copies only
     `Sensor_Type` and `Tdelay` (`convertelements.cxx:906-916`, `:997-1004`):
     its `/DIST` copy has `N1 = N2 = Dmin = Dmax = 0` (starter `ERROR 78`,
     twice, under a title that prints as `538976288` = `0x20202020`), its
     `/ACCE` copy has `Nacc = 0` and no accelerometer, and its `/TIME` copy
     loses the original `TIME` so it fires at `TDEL` instead of `TIME + TDEL` —
     the wrong absolute instant. Copying the whole card costs one extra id and
     fixes all three.

  9. **`SID1..SID4` become a `/SENSOR/OR` tree — k2rad exceeding the
     reference.** LS-DYNA gives a retractor four lock sensors and a
     pretensioner four trigger sensors, ORed; `/RETRACTOR/SPRING` has one
     `Sens_ID1` and one `Sens_ID2`, and dyna2rad simply takes the FIRST
     NON-ZERO of each four (`convertelements.cxx:838-846`, `:944-951`), so a
     belt that should lock on either the sled decelerating OR the webbing
     paying out locks only on whichever the deck listed first. `/SENSOR/OR`
     takes exactly two inputs (`sensor_or.F:75-78`), so three or four chain —
     and the delay is folded into the LEAVES, because the OR gate sets
     `TSTART = TT` with no reference to its own `Tdelay`. For latching sensors
     that is exact: `min(t₁,t₂) + d == min(t₁+d, t₂+d)`.

  10. **`/SENSOR/SENS` looks like the natural delay wrapper and is NOT one.**
      Its `Tdelay` is a STOP delay: `sensor_sens.F:110-138` activates it at the
      input sensor's own `TSTART` with no delay added, then DEACTIVATES it at
      `TSTART + TDELAY` and sets `STATUS = -1` ("will never wake up again").
      Recorded because the card's field name and the starter's echo
      (`TIME DELAY BEFORE ACTIVATION`) both suggest the opposite.

  11. **`Flow_flag` is established from the ENGINE, not from the two cards'
      field names.** `material_flow.F:266-267` grows strand 1's unstretched
      length by `DELTA_LO` and shrinks strand 2's by the same amount, so
      `DELTA_LO > 0` means material flowing from element 2 INTO element 1; and
      `:253-254` blocks `FL_FLAG == 1` exactly when `DELTA_LO > 0`. So
      `Flow_flag 1` forbids 2→1, i.e. permits only 1→2 — which is LS-DYNA's
      `DIRECT = 12`. Anything other than 0/12/21 writes 0 with the reason
      named; dyna2rad leaves the cell unset, which reads as the same 0 without
      saying so.

  12. **`SBPRTY 7` → `Tens_typ 4`, which dyna2rad never produces.** LS-DYNA's
      type 7 is the INDEPENDENT pretensioner/retractor, and Radioss's
      `Tens_typ 4` is the additive force — `material_flow.F:576-581` and `:623`
      `YY = YY + PRETENS` — which is exactly "independent": it adds to the
      retractor rather than replacing it. dyna2rad maps 6 and 7 both to 3
      (`convertelements.cxx:1019`), so `Tens_typ 4` is unreachable there. The
      full table is 1→1, 4→2, 5→1, 6→3, 7→4, 8→5; **2, 3 and 9 have no target**
      and the whole pretensioner is dropped with the reason named, where
      dyna2rad writes `Tens_typ = 0` with the sensor, the curve and the force
      still attached — a retractor carrying a pretensioner's data and doing
      nothing with it.

  13. **Pretensioners are matched to retractors through a map built up front.**
      dyna2rad's `SelectionRead selSeatbeltPretensioner` is constructed ONCE
      outside the retractor loop (`convertelements.cxx:826`) and never
      `Restart()`ed, although it uses `Restart()` in five other places. Both
      selections iterate in ascending id order, so the pretensioners are
      consumed GLOBALLY: verified on its own probe decks, a retractor with no
      matching pretensioner eats the rest of the list (`v6`: retractor 42 got
      no `Sens_ID2`, no `Tens_typ`, no `Force` and no `Fct_ID3` at all), and two
      pretensioners on one retractor make the second vanish AND strand the
      retractor after it (`v7`).

  14. **`RE` runs the OTHER WAY from dyna2rad, and `PRBA` goes to `NU12`.**
      `RCOMP` MULTIPLIES the compressive stress —
      `law119_membrane.F:190-191` `SIGNXX = (A11·EPSXX + A12·EPSYY)·RCOMP` in
      the compression branch — so ELIMINATING compression is a SMALL `RE`.
      `convertmats.cxx:11047` writes `RE = (CSE==0) ? 1.0 : 0.01`, so the
      LS-DYNA DEFAULT (CSE = 0, "eliminate compressive stresses in shell
      fabric", `SB_MAT.cfg:142-147`) converts to a membrane with FULL
      compressive stiffness and a deck that explicitly asked to KEEP
      compression gets it eliminated — both directions wrong on every deck that
      states the field. Its own `*MAT_FABRIC` route has the sign right
      (`convertmats.cxx:2085`). Separately, `convertmats.cxx:11049` copies
      `PRBA` into `VC`, the COATING's Poisson ratio, leaving the belt's own
      `NU12` at 0 — while `hm_read_mat119.F:165` `IF (NUCOAT == ZERO)
      NUCOAT = N12` shows `NUCOAT` is meant to be left blank so the reader can
      default it. k2rad deviates on both.

  15. **The LAW119 determinant is enforced before the starter refuses it.**
      `create_seatbelt.F:903` forms `N21 = N12·FSCALET` with
      `FSCALET = 100·Fscale22`, and `:911` `DET = 1/(1 − N12·N21)`; a negative
      determinant is raised LATE, from `:920`, as `ERROR 307 DETERMINANT OF
      MATERIAL MATRIX IS LESS THAN 0` under the misleading title
      `SEATBELT MATERIAL`. With `FSCALET` = `E22/E11` that product is exactly
      the standard 2D orthotropic condition `ν₁₂·ν₂₁ < 1`, so a deck violating
      it states a material that cannot exist; `NU12` is clamped to the boundary
      — the stiffness ratio is a measured property, the minor Poisson ratio is
      what the symmetry constrains — and the deck is told. dyna2rad never writes
      `Fscale22` at all and lets the reader default it to 0.1, which puts the
      LS-DYNA default `PRBA = 0.3` one decimal from failure.

  16. **`*DATABASE_SBTOUT` → BOTH `/TH/SLIPRING` and `/TH/RETRACTOR`.** LS-DYNA
      writes one `sbtout` file; Radioss splits the same data across two group
      types with separate channel sets (`hm_read_thgrou.F:1258`
      `RINGSLIP FN F1 F2 THETA GAMMA`, `:1261` `SLIP FN LOCK` — the cfg's
      advertised `FORCE` variable does not exist in either reader), so both are
      emitted with different group ids (sharing one is `ERROR 79`). dyna2rad
      handles the card only as a `dbCardList` member whose sole effect is the
      `/TFILE` interval (`convertcards.cxx:94`), and
      `grep -rn "TH/RETRACTOR"` over the whole of `reader/source` returns
      **zero hits** — a retractor's force, pull-out and lock state are simply
      unavailable there. `RINGSLIP` and `SLIP` are RUNNING TOTALS
      (`material_flow.F:284`), already lengths, so unlike the `/TH/INTER` force
      channels they need no differentiation; said in the warning.

  17. **`*DATABASE_HISTORY_SEATBELT` splits PER ELEMENT.** dyna2rad probes
      `elemidList[0]`'s `PID → SECID` and routes the whole list on that one
      answer (`converttimehistory.cxx:312-340`), so a card mixing a 1D shoulder
      belt with a 2D lap belt sends every id to one keyword and the others
      become `ERROR 69`. k2rad reads the writer's own registries, so after the
      screen every surviving id is in exactly one of `/TH/SPRING`, `/TH/SHEL`
      and `/TH/SH3N`. The 2D groups take `DEF` alone: a `/MAT/LAW119` shell does
      not stay a shell — `starter0.F:782-803` hands it to
      `hm_convert_2d_elements_seatbelt.F`, which rewrites the part into 1D
      springs AND rewrites every `/TH/SHEL` that named those shells into a
      `/TH/SPRING` (`:135-141`) — and `STRAIN` is not a `/TH/SPRING` variable.

  18. **The registry audit, verified rather than assumed.** A belt element is
      the EIGHTH `/SPRING` producer, so it registers into
      `state.spring_elem_ids` at the line that writes the row, and it is a
      FIFTH LS-DYNA element-id namespace, so it joins `_spring_eid_families`
      (a belt eid and a discrete eid may legally collide in the source deck and
      both become `/SPRING`, `ERROR 79`). It joins the orphan mesh-loss census,
      the OPTT non-solid split, `_referenced_node_ids` (with every device node —
      slipring anchorage and orientation, retractor anchorage, sensor nodes,
      accelerometer triad — because each is named on an emitted card without
      owning an element), the `*INITIAL_VELOCITY_GENERATION` part scope (a sled
      test scopes by part set, and leaving the belt out would yank it taut at
      t=0), the joint pacing census (a belt has a time step of its own,
      `r2len3.F:182`) and the implicit free-node guard's `elem_nodes` (a belt
      carries stiffness; a `/BCS 111 111` there would weld it to ground). It is
      NOT added to `--auto-gapmin`'s faceting or part-node map, to the contact
      scoping, or to `keep_free`: a 2-node spring has no face, and the device
      nodes carry no stiffness of their own, so pinning an orphan one changes no
      trajectory — the same argument the `*AIRBAG_HYBRID_JETTING` node markers
      already record.

  19. **The `*INCLUDE_TRANSFORM` walks.** Four of the six device keywords need a
      card walker rather than a declarative spec, each for a reason a flat spec
      cannot express: `*ELEMENT_SEATBELT` calls the HANDLER's own slicer so the
      two readers of its 8/8/8/8/8/**16**/8/8 grid cannot desync (a uniform
      8-wide re-render moves `N3`/`N4` into the right half of `SLEN`, which
      silently turns a 1D belt into a 2D one); a slipring's `SBID1`/`SBID2`/
      `SBRNID` change BUCKET with the sign of `SBRNID`, and a negative `FC`/
      `FCS` is a signed curve reference; a sensor's card-2 field 0 is a NODE on
      SBSTYP 1/4 and a RETRACTOR on 2/5; and the retractor's and
      pretensioner's card 2 are claimed by RAW CONTIGUITY, because an all-blank
      card 2 is legal on both and on SBPRTY 7/8/9 the legacy cfg writes the
      pretensioner's field 0 literally blank. Both tables are generated from the
      SAME dict, with an assert that they cover the same spellings (#116).

  20. **Validated against the real OpenRadioss starter.** A probe deck carrying
      five belt springs, two sliprings (one scalar friction, one curve-driven),
      a retractor with a two-sensor OR lock and a pretensioner, four sensors
      (SBSTYP 1/2/3/4), an accelerometer, `*DATABASE_SBTOUT` and
      `*DATABASE_HISTORY_SEATBELT`: **0 ERROR(S)**, and every card reads back
      as written — `FORCE-ENGINEERING STRAIN CURVE = 910`,
      `SEATBELTS DEFAULT DAMPING COMPUTATION`,
      `MAXIMUM FORCE FOR SHEAR/COMPRESSION = 0`, the slipring's
      `FLOW FLAG = 1 / A = 0.5500 / ED = 0.7500 / FRICD = 0.2500`, the
      retractor's `SENSOR ID1 = <the OR gate> / PRETENSION TYPE = 2 /
      MAXIMUM FORCE = 7777.`, and `SENSOR TYPE 5: SENSOR1 OR SENSOR2` over the
      two delayed copies. The same deck inside an `*INCLUDE_TRANSFORM` with all
      eight offsets distinct: **NORMAL TERMINATION, 0 ERROR(S) / 0 WARNING(S)**.

  **Corpus.** MEASURED over the whole corpus, the only seatbelt keyword any
  production deck carries is `*ELEMENT_SEATBELT_ACCELEROMETER` — 11 on the
  Toyota Yaris and 9 on the Camry, all with `IGRAV`/`INTOPT`/`MASS` blank —
  plus four `*DATABASE_SBTOUT` on the implicit Yaris variants and one keyword
  TEMPLATE (`275key2.k`, every seatbelt card commented out). On master all of
  them landed in `skipped_keywords` with **no warning naming the lost
  channel**: twenty acceleration channels, which is exactly what the crash-test
  post-processing needs. The sweep is therefore a REGRESSION check, on the same
  footing as the batch-2 airbag sweep.

  **Sweep.** 377 decks (the repo tree, the r14 dynaexamples corpus and the two
  Toyota production decks, deduplicated by content hash), converted with master
  and with this branch and compared by SHA-256:

  * **373 byte-identical starters, 377 byte-identical engines, 0 conversion
    errors on either side.**
  * The only four differing decks are exactly the four that carry
    `*ELEMENT_SEATBELT_ACCELEROMETER` (the Yaris and Camry `set-*.key` masters
    and their two `combine.key` includes). Each loses that keyword from
    `skipped_keywords` and gains exactly ONE warning — the one naming the
    channels it just recovered.
  * The seven seatbelt-carrying decks swept separately: the four
    `*DATABASE_SBTOUT` Yaris variants move the keyword from `skipped_keywords`
    to `recognized_not_emitted` (they define no slipring or retractor, so a
    note is the correct answer and the warning count is unchanged), the
    keyword-template deck is byte-identical, and the Yaris and Camry emit
    **11 and 9 `/ACCEL` cards with their full `/SKEW/MOV` triads plus a
    `/TH/ACCEL` group**.
  * A deck of the Yaris/Camry shape — two accelerometers with blank
    IGRAV/INTOPT/MASS and a `*DATABASE_SBTOUT` with no device — runs through
    the real OpenRadioss starter to **NORMAL TERMINATION, 0 ERROR(S) /
    0 WARNING(S)**.

  21. **Review round — one blocker, four majors, and four defects the reviews
      did not reach.** Everything below was verified against the LS-DYNA R16
      manuals and the OpenRadioss sources before it was acted on; the
      conversion-behaviour changes are all on paths no corpus deck reaches, so
      the 558-deck sweep comes back byte-identical either side of them
      (measured below).

      * **BLOCKER — `/PROP/TYPE23` and `/MAT/LAW114` were emitted once per
        belt PART, not once per id.** A shoulder-belt `*PART` and a lap-belt
        `*PART` on one `*SECTION_SEATBELT` and one `*MAT_SEATBELT` — the
        ordinary two-strand restraint layout — wrote both cards TWICE, and
        `_seatbelt_prop_ids` hands both parts the same prop id by design when
        their areas agree. MEASURED: `ERROR ID : 79 DUPLICATE ID` over BOTH the
        material and the PID table, `ERROR TERMINATION, 2 ERROR(S)`. Each card
        now goes out once; the `/PART` row and the `/SPRING` block still go out
        per part. The per-material and per-section NOTES were duplicated the
        same way and are now emitted once as well, and the `LFED < 3·LMIN`
        check is scoped to the retractors whose mouth element is actually on
        that material instead of firing P×R times.
      * **A new `assembly._warn_duplicate_mat_ids` scan** over the assembled
        starter, the twin of `_warn_duplicate_prop_ids`, so this whole CLASS
        of failure can never be silent again — `/MAT` had no such scan at all.
      * **MAJOR — the INERT belt material could collide.** The branch that
        exists for a belt part pointing at an ORDINARY material wrote its
        placeholder `/MAT/LAW114` under `part.mid` verbatim, so
        `materials.py`'s card and this one landed on one id: `ERROR 79`, then
        `ERROR 1715` and `ERROR 3046` on the `/PART`. The id is now reused only
        when no other material writer owns it; otherwise a fresh one is minted
        and the `/PART` row is repointed at it.
      * **MAJOR — `*ELEMENT_SEATBELT` was free-split FIRST.** A column-correct
        `8/8/8/8/8/16/8/8` card with any BLANK interior cell then shifted every
        later field one slot: `'…       0                       7       8'`
        (SLEN blank, N3=7 N4=8) read as SLEN=7, N3=8, N4=0, so a 2D shell belt
        became a 1D `/SPRING` with 7 mm of invented slack and the part was
        claimed by BOTH routes (`ERROR 79` + `1715` + `78` + `760`). It is now
        SLICED first with the free split as the fallback — the rule
        `_card(fixed=True)` already uses — verified on all four card shapes.
      * **MAJOR — the retractor's mandatory-curve guard read the RAW `LLCID`.**
        `hm_read_retractor.F:236-242` refuses `ISENS(1) > 0` with
        `IFUNC(1) == 0` (`ERROR 2031`), and `_resolve_belt_curve` returns 0 for
        a curve the converted deck does not define — so a `LLCID` naming a
        missing curve emitted `Sens_ID1` beside `Fct_ID1 = 0` and the deck
        refused to start. The guard now tests the RESOLVED id and drops the
        sensor with it, mirroring the `ERROR 2025` handling two blocks below.
      * **MAJOR — the `/SENSOR` namespace guard was incomplete.**
        `next_sensor_id()` existed, but `writer/fabric.py` (a `*MAT_FABRIC`
        `RGBRTH` birth sensor) and `writer/inistate.py`
        (`*AIRBAG_REFERENCE_GEOMETRY_BIRTH`) still minted from the raw auto-id
        stream, so a USER `SBSID` at or above the auto-id base collided —
        MEASURED, two `/SENSOR/TIME` cards on one id. Airbag fabric and belt
        sensors live in the same occupant-restraint decks. Both call sites
        converted.
      * **`CSE` only says anything when `FORM` is non-zero, and only one
        sentence in the manual says so.** Vol II *MAT_SEATBELT, CSE: the option
        is "available since r137465/dev **for non-zero FORM** … **For non-zero
        FORM:** EQ.0.0: don't eliminate …; EQ.1.0: eliminate …".
        `_seatbelt_2d_re` now branches on `FORM`, and `CSE = 2` is named as
        undefined outside `FORM = 0` ("still works if and only if FORM = 0").
        Neither review reached this; dyna2rad has no `FORM` branch at all.
        *(The FORM = 0 half of what this round wrote was itself wrong and is
        corrected in 22 below — the cfg table it leaned on is a stale GUI
        list, not solver behaviour.)*
      * **`SBRID` on a pretensioner sits in TWO id namespaces.** Vol I
        *ELEMENT_SEATBELT_PRETENSIONER: "Retractor number (SBPRTY = 1, 4, 5, 6,
        7 or 8) or **spring element number** (SBPRTY = 2, 3 or 9)" — one cell,
        chosen by a field on the OTHER card. Keyed on it regardless, a spring
        element id that equals a retractor id sorted first on SBPRID, took that
        retractor's ONE card-3 slot, resolved to `Tens_typ 0` — and the REAL
        pretensioner beside it was dropped as "extra". The spring types are now
        kept out of the map and reported for the right reason, and the
        `*INCLUDE_TRANSFORM` walker offsets that cell with IDEOFF instead of
        IDROFF when SBPRTY is 2/3/9.
      * **A stated `E` with a BLANK `A` no longer invents a stiffness.** Card
        2's `A` defaults to 0.0, so LS-DYNA's bending/compression model is
        `E × A = 0` — inert — while `/MAT/LAW114` forms `XK_COMP = E × Area`
        against the NEUTRAL `Area = 1` the mass split uses. `E` is written as 0
        and the drop is named, rather than filling in the unstated
        cross-section.
      * **Each hard failure was reproduced on the real starter and then
        cleared, before and after, on the same deck.**

        | probe | pre-review | this branch |
        |---|---|---|
        | two belt parts, one section, one material | `ERROR 79` ×2 (MATERIAL + PID), **2 ERROR(S)** | **0 ERROR(S) / 0 WARNING(S)**, engine NORMAL TERMINATION, 55 cycles |
        | belt part on a `*MAT_ELASTIC` a shell also uses | `ERROR 79` + `1715` + `3046`, **3 ERROR(S)** | **0 ERROR(S)** (the one warning left is the pre-existing `WARNING 1084` on the shell section) |
        | retractor + lock sensor, `LLCID` names an undefined curve | `ERROR 2031 FUNCTION ID1 MUST BE INPUT FOR LOCKING AS SENSOR IS DEFINED`, **1 ERROR(S)** | **0 ERROR(S) / 0 WARNING(S)** |
        | 2D belt card with a BLANK `SLEN` cell | `ERROR 79` + `1715` + `78` ×2 + `760`, **4 ERROR(S)** | **0 ERROR(S) / 0 WARNING(S)** |

      * **The solver-validated decks are untouched, and that is byte-exact.**
        All **30** purpose-built physics decks from the validation campaign
        (belt law, LMIN, slipring capstan at three wrap angles, retractor lock
        and pull-out, the three sensor types, both pretensioner laws, the
        accelerometer triad, the 2D warp/weft pair) re-converted with this
        branch produce **byte-identical `_0000.rad` AND `_0001.rad`** — 30
        starters and 30 engines, SHA-256 equal to the ones the OpenRadioss runs
        were made from. Nothing above moved a number that a solver run had
        already checked.
      * **Corpus sweep, 558 decks** (the repo tree, the r14 `dynaexamples`
        corpus, the Ryan-Lee examples and the two Toyota production models),
        converted with the branch as the reviews saw it and with this one and
        compared by SHA-256: **558 byte-identical starters, 558 byte-identical
        engines, 0 conversion errors on either side, 0 movers.** Every
        conversion-behaviour change above is on a path no corpus deck reaches.
        ONE deck gains ONE warning — `ale-s-ale/s-ale/wavestructure/2Dlag.k`,
        where the new `/MAT` duplicate scan reports a PRE-EXISTING defect it was
        the first thing ever to look for: `/MAT/LAW4/3` and `/MAT/HYD_VISC/3`
        on one id, because LS-DYNA's `*EOS_*` `EOSID` and `*MAT_*` `MID` are
        separate namespaces while the bare-`*EOS_*` LAW6 carrier is written
        under the EOSID. Nothing to do with seatbelts, and left for its own
        change.
      * **Smaller, all measured.** `LMTFRC` is dropped on `SBPRTY = 1`, the one
        place where LS-DYNA ignores it ("limiting force for retractor types 5
        and 8") and Radioss reads it (`material_flow.F:546`, `Tens_typ 1`). A
        LAW119 loading/unloading pair that never CROSSES at a positive abscissa
        is screened by `func_inters.F`'s own algorithm and `fct_uload` dropped
        with `ERROR 3081` named — an ORDINARY LS-DYNA pair fails that
        Radioss-only rule. A 2D belt whose `(n1,n2)/(n4,n3)` edges run ACROSS
        the strip is named against `ERROR 2075` (the test itself is corrected
        in 22 below). A 2D belt element whose EID
        collides with an `*ELEMENT_SHELL` is no longer dropped in silence. A
        BLANK card 3 on a `_2D` material no longer swallows the `GAB` card. The
        implicit free-node guard no longer pins the accelerometer's
        `/SKEW/MOV` triad, the slipring orientation node (the engine rebuilds
        the ring frame from its CURRENT position every cycle,
        `kine_seatbelt_vel.F:91-108`), a sensor's watched nodes, or a device
        ANCHORAGE (which receives the belt's force AND stiffness every cycle,
        `kine_seatbelt_force.F:91,117`). 1D belt nodes now reach the SECONDARY
        side of a part- or part-set-scoped `*CONTACT`, and are excluded from
        the `_INERTIA` / CNRB "element-free master" tests, where they carry
        mass and a geometry the ICoG move would change. `LCFL` moves with
        IDFOFF. `assembly.py`'s four offset walkers now IMPORT
        `handlers._seatbelt_rows` instead of re-implementing it.

  22. **Post-review verification — three defects the review round itself
      introduced or left standing.** Two of its own fixes were wrong in a
      documented corner, and one pre-existing defect survived the round that
      documented its cause. Each was re-derived from the primary source before
      being touched.

      * **MAJOR — on `FORM = 0` the `CSE` cell controls NOTHING, so the review
        round's "FORM = 0 table" is not a table.** Vol II R17 *MAT_SEATBELT
        (p.2-2101): "Compressive stress elimination option **for nonzero
        FORM** … Note that **for FORM = 0, the solver automatically determines**
        whether or not to eliminate the compressive stresses", and Remark 6
        (p.2-2105): "From versions R8 through R11, eliminating the compressive
        stresses was **always determined by the solver**. As of R12, **for
        nonzero FORM**, CSE … was reused". The shipped cfg's CSE list does not
        refute that — it is **byte-identical in `Keyword971_R8.0` and
        `Keyword971_R12.0`**, a pre-R8 GUI table nobody updated. Reading it as
        live made `FORM = 0` + `CSE = 1` emit `RE = 1`, a membrane with FULL
        compressive stiffness (`law119_membrane.F:190` multiplies the
        compressive stress by `RCOMP`) — a plate, not webbing. Every `FORM = 0`
        material now takes the ELIMINATE side, `RE = 0.01`, under a warning
        that says plainly this is the converter's CHOICE and not a value the
        deck states. The non-zero-`FORM` half is unchanged. MEASURED: the two
        2D validation decks are the exact `FORM = 0` / `CSE = 1` cell, and
        their re-run is below.
      * **Every `RE` note now states how little `RE` moves.** It scales the
        LAW119 SHELL membrane only, and the starter's own 2D→1D strand chain
        carries the RAW loading-curve slope in compression through
        `iecrou = 12` ("non linear elastic in tension with compression … for 2d
        seatbelts only", `redef_seatbelt.F90:335`), untouched by `RE`.
        MEASURED at `eps = -0.02`: 79998 N from the strands against 801 N of
        membrane at `RE = 1.0` and 8 N at `RE = 0.01` — the flag moves **0.99 %
        of the belt's compressive response**. A note that called `RE = 0.01`
        "what a slack belt does physically" over-promised that.
      * **MAJOR — `_warn_2d_belt_direction` false-fired on every belt more than
        ONE element wide.** Its premise — a proper strip never repeats a
        `(n1,n2)`/`(n4,n3)` edge — holds only for a one-element-wide strip: in
        an n-wide strip row k's `(n4,n3)` IS row k+1's `(n1,n2)` by
        construction, and the reader de-duplicates on purpose
        (`GlobalModelSdi.cpp:2409-2410` pushes `std::minmax()` pairs, `:2420`
        "Create elements deleting dupplicated connectivity"). `ERROR 2075` fires
        only when two belt entities on ONE material get `SECTION`s differing by
        more than 1e-5 (`create_seatbelt.F:756-759`, `SECTION` being the belt's
        WIDTH × thickness summed along its end frame, `:512`), which
        equal-width strands never do. MEASURED false positive: an ordinary
        2-wide × 2-long strip with `n1→n2` along the pull, told to rotate
        connectivity that was already right. The check now de-duplicates the
        edge multiset the way the reader does and compares the two edge
        directions' chain lengths, naming the part only when the PERPENDICULAR
        pair chains longer.

        Measured on the two production restraint models in the examples corpus
        (`BELT_PA_50th_HIII_ml_br19_sr17.k`, `04_belt_pa_030.k`), which between
        them hold three 2D belt parts. The old check warned on all three; the
        new one warns on two and clears one, and the geometry says which is
        which:

        | deck / part | shells | belt-edge runs | perpendicular runs | verdict |
        |---|---|---|---|---|
        | `BELT_PA` 66000003 | 62 | 53 edges, **1071 mm** | 17 edges, 350 mm | correct — now **silent** |
        | `BELT_PA` 66000002 | 88 | 16 edges, 352 mm | 71 edges, **1446 mm** | transverse — still named |
        | `04_belt_pa_030` 66000002 | 488 | 269 edges, 3274 mm | 349 edges, **4208 mm** | transverse — still named |

        So two of the three were true positives the old check happened to reach
        for the wrong reason, and are now reported with the numbers that make
        the call checkable. The synthetic control is intact too: `t9b` still
        reports "strands at most 1 element long, while the PERPENDICULAR pair
        chains 4 long", and its starter still answers **2 × `ERROR 2075`**.
      * **MAJOR — the `*INCLUDE_TRANSFORM` rewriter re-introduced, on the WRITE
        side, the field shift the review round fixed on the READ side.** When an
        id outgrows its 8-wide cell — routine for any belt id ≥ 100,000,000,
        which is what `*INCLUDE_TRANSFORM` exists for — `_off_element_seatbelt`
        fell back to a SPACE-joined free card, and a blank interior cell joins
        to nothing between two spaces. MEASURED, with `e = n = 1e8`:
        `'66000004…       0                6600005766000058'` (I8, SLEN blank)
        was rewritten as
        `'166000004 66000002 166000002 166000172 0  166000057 166000058'` and
        read back as SLEN = 166000057, N3 = 166000058, N4 empty — **the 2D shell
        belt became a 1D `/SPRING` with 166,000,057 units of invented slack**,
        the same failure the round lists as a fixed MAJOR. The fallback is now
        the COMMA form, where "two consecutive commas hold an EMPTY field in its
        position" (`parse_free`), so the card round-trips through
        `_seatbelt_elem_card` unchanged and nothing is invented to fill the gap.
      * **`--auto-gapmin` now measures the belt.** `contacts.py` gained a 1D
        belt arm this batch, so a part- or part-set-scoped `*CONTACT` reaches
        the webbing; `gapmin._part_nodes_map` did not, so the clearance was
        measured over every OTHER part in that contact. It has the same arm now
        — the SPH precedent, for the same reason: nodes but no faces. Beams and
        `*ELEMENT_DISCRETE` are still missing there and are still pre-existing.
      * **An IMPLICIT deck carrying a 1D belt is now told it is not solving the
        belt.** `imp_glob_k.F`'s `ITY==6` arm builds spring stiffness for
        `IGTYP` 4, 8, 12 and 13 only (`R4KE3`/`R8KE3`/`R12KE3`/`R13KE3`);
        everything else falls to the `IETY=16` arm and format 1005, `*****
        WARNING : SPRING ELEMENT PROP.TYPE = 23 IS NOT AVAILABLE FOR STIFFNESS
        MATRIX BUILDING, STIFFNESS IGNORED *****`. MEASURED: the assembled
        matrix collapsed from SYMBOLIC ND=18 NZ=27 to FINAL ND=6 NZ=3 — only
        the synthesized probe rigid body survived. The belt's mass and the
        devices' kinematics still act; the tangent has no belt in it.
      * **Two comment/doc corrections.** `state.sensor_ids` / `accel_ids` do
        hold the user `SBSID`/`SBACID`s the writer emits (`writer/seatbelts.py`
        adds each at the line that writes its card) — the review round replaced
        an accurate comment with a false one, and the accurate wording is back.
        `_belt_curves_intersect`'s justification for dropping `FAC1`/`FAC2` now
        gives the real reason: `hm_read_mat119.F:113-114` reads `Fcoeft1` and
        `Fcoeft2` as two INDEPENDENT cells, and they coincide here only because
        THIS writer always emits both as 0.
      * **The solver-validated decks, re-measured.** 28 of the 30 are still
        **byte-identical on both `_0000.rad` and `_0001.rad`**. The two that
        move are `t9a_2d_warp` and `t9b_2d_weft`, the `FORM = 0` / `CSE = 1`
        pair, and they differ by **exactly one cell** — `/MAT/LAW119` card 2
        `RE`, `1` → `0.01` — with the engine decks byte-identical. Both were
        re-run on the real solver: `t9a` gives **NORMAL TERMINATION, 4804
        cycles, 0 ERROR / 0 WARNING** on both sides and its **`T01` is
        bit-for-bit identical**, because it is a pure-tension run and `RCOMP`
        only multiplies the compression branch (`law119_membrane.F`,
        `BETA(I) = RCOMP` in the non-tension arm); `t9b` is the rotated-
        connectivity negative control and still answers **2 × `ERROR 2075`,
        5 WARNING(S)** on both sides. No physics a solver run had checked has
        moved.
      * **Corpus sweep, 558 decks**, converted with the branch as the reviews
        saw it and with this one: **558 byte-identical starters, 558
        byte-identical engines, 0 movers, 0 warning-count deltas.** Every change
        above is on a path no corpus deck reaches — none carries a 2D belt
        material, a belt id that overflows its cell under an
        `*INCLUDE_TRANSFORM` offset, or an implicit deck with a 1D belt.

  Tests: `tests/test_seatbelts.py`, **174 tests + 98 subtests**, every card
  asserted by column with a distinct number per slot; nine load-bearing claims
  verified by MUTATION in the first round (each fails the suite when the line
  is changed to what dyna2rad does), plus the `_slipring_card2_follows`
  discriminator, which was the one mutation that survived it. The review
  round's own battery: **18 mutations, 18 caught** — one per fix above, each
  flipping the line back to what it did before. The verification round adds
  **5 mutations, 5 caught**: the `FORM = 0` CSE table restored (4 failures),
  the edge-uniqueness belt-direction test restored (1), the space-joined offset
  fallback restored (2), the gapmin belt arm removed (1) and the implicit-belt
  warning removed (1).

- **The airbag / monitored-volume batch 2:
  `*AIRBAG_HYBRID[_JETTING][_CM]` → `/MONVOL/AIRBAG1` with `N_gases > 1` plus
  one `/MAT/GAS/MOLE` per species, `*AIRBAG_PARTICLE[_MPP][_DECOMPOSITION]
  [_MOLEFRACTION/_INFLATION/_JET][_SEGMENT][_TIME]` → `/MONVOL/FVMBAG2`, and
  `*AIRBAG_INTERACTION` → `/MONVOL/COMMU1` on both bags with reciprocal `Nbag`
  communicating rows.** The three multi-gas keywords batch 1 registered as
  *recognized but not emitted*, and the machinery they share: a multi-row
  injector, named vent surfaces, and the mixture rule that turns a mass
  fraction into a molar one. `*AIRBAG_INTERACTION` is k2rad exceeding the
  reference converter outright — `grep AIRBAG_INTERACTION` over the whole of
  `reader/source/dyna2rad` returns **zero hits**, so two bags that should share
  gas simply do not there.

  1. **`*AIRBAG_HYBRID` targets `/MONVOL/AIRBAG1`, not dyna2rad's `COMMU1`.**
     `convertcontrolvols.cxx:2428` creates a COMMU1 and the source gives no
     reason for it anywhere in the tree. Reading the two card definitions
     against each other, COMMU1 has exactly ONE capability AIRBAG1 lacks — the
     communicating-bag block (`monvol_commu1.cfg:120-131`) — and dyna2rad never
     writes `NBAG` or any row into it. Everything else is shared: vents are the
     same sub-block on both (`radioss140/PROP/venthole1.cfg:17` names itself
     *"SUBOBJECT of AIRBAG1, COMMU1 AND FVMBAG1"*), `N_gases` lives on the
     `/PROP/INJECT1` both reference, jetting exists on both
     (`injector1.cfg:24-29` vs `monvol_commu1.cfg:47-51`, and d2r sets neither),
     and both carry `Nporsurf`. A COMMU1 with the block empty is not even
     well-formed — `monvol_commu1.cfg:255-259` carries
     `CHECK(COMMON) { NBAG > 0; NBAG <= 20; }`. So a stand-alone hybrid bag is
     an AIRBAG1 and **both** partners are promoted to COMMU1 the moment an
     `*AIRBAG_INTERACTION` gives the block something to hold. The promotion is
     loss-free: `monvol0.F` dispatches `ITYP==7 .OR. ITYP==9` to the same
     `AIRBAGA1`/`AIRBAGB1` pair. One consequence of d2r's choice is that its
     hybrid bags get **no `/TH/MONV` at all**, because
     `p_CreateTHMonVolForDBAbstat` runs at `ConvertEntities():47` and
     `ConvertAirbagHybrid` at `:53`, so its `SelectionRead` cannot see them.

  2. **`/MAT/GAS/MOLE` takes the molar coefficients VERBATIM — the divide
     happens once, and not here.** LS-DYNA's A/B/C are molar on both the simple
     and the hybrid card ("Coefficient of MOLAR heat capacity", Vol I R17
     p.3-50), but the two Radioss targets differ: batch 1's `/MAT/GAS/MASS`
     slot is mass-specific so the CONVERTER divides by MW, while
     `/MAT/GAS/MOLE`'s is molar and the SOLVER divides —
     `hm_read_matgas.F:295-302`, `CPA = CPA / MW * FAC`. Cross-checked against
     the hard-coded PREDEF gases, which take the same `IMOLE=1` path with SI
     molar numbers (`:158-166`: N2 is `MW = 0.02801` kg/mol and
     `CPA = 26.0920000` J/(mol K), i.e. 931 J/(kg K), correct). Dividing in
     both places understates Cp by a factor MW — 36× on a 0.028 kg/mol gas.
     Note also that **MOLE has no `Cpf` card**: the reader takes `MAT_F` only
     for `IGAS == 2`, so a sixth line after a MOLE gas is the next keyword read
     as a Cpf and everything below it shifts.

  3. **The initial mixture is a MOLE-FRACTION average, not dyna2rad's
     mass-weighted mean.** `INITM` is a mass fraction ("The sum of INITM of all
     gas components should be 1.0") while MW and A/B/C are molar, so averaging
     the latter with the former is not a mixture rule. The weights are
     converted first — `x_i = (w_i/M_i)/Σ(w_j/M_j)`,
     `M = Σw_i/Σ(w_i/M_i)`, `Cp = Σ x_i Cp_i` — which is exact and lands where
     it should: the solver's
     divide turns it into `Σ w_i·(Cp_i/M_i)`, the mass-fraction average of the
     mass-specific heat capacities, which is what Dalton's law says a mixture's
     `c_p` is. `convertcontrolvols.cxx:2494-2497` accumulates
     `radMW += MW_i*INITM_i/sum(INITM)` and the same for A/B/C and feeds it to
     the same divide; the two agree only when every MW is equal. For a
     50/50-by-mass argon/helium fill (M = 0.03995 / 0.004) d2r states
     M = 0.0220 where the mixture's is 0.00727, a factor of 3. Its
     `INITM >= 1.0` gate is worse still: a species carrying its documented
     fraction — 0.79 nitrogen, 0.21 oxygen — contributes to neither the mixture
     nor an injector, and vanishes from the deck entirely.

     The numerator is `Σw_i`, **not 1**: `M = 1/Σ(w_i/M_i)` is the same number
     only when the `INITM` column already sums to 1, and LS-DYNA only says it
     *should* (Vol I R17 p.3-50). The mole fractions normalise themselves, so
     Cpa/Cpb/Cpc are unaffected either way and ONLY MW moves — by exactly
     `1/Σw`. MEASURED: the same composition stated as the percentages 79/21
     instead of 0.79/0.21 gave MW 0.0002875481386 rather than 0.02875481386, a
     factor of 100 on the one number the starter builds everything else on
     (`CVI = CPI − R_IGC1/MW`, `MI = PINI·(VOL+VEPS)/(RMWI·TI)`), with no
     starter diagnostic. Ironically dyna2rad's own formula does divide by
     `sum(INITM)`.

  4. **No `/SENSOR/TIME`, and `Ittf = 0`.** dyna2rad strips the leading
     zero-flow dead time off each `LCIDM`, re-emits the curve shifted by
     `−TTF`, arms a `/SENSOR/TIME` with `Tdelay = TTF` and writes `Ittf = 3`
     (`:2686`, `:2760`, `:3216`). On the INJECTOR that is a wash — `airbaga1.F`
     reads the mass curve at `TSG = (TT − TSTART)/ASTIME` with `TSTART` the
     same sensor's start, so the shift and the delay cancel exactly. On the
     VENT it is not: d2r writes `LCC23`/`LCP23` RAW while `Ittf = 3` makes
     `airbagb1.F` evaluate them at `TT − TTF − TVENT`, i.e. `TTF` seconds
     early. Doing neither is simpler and strictly more faithful, and it costs
     one sensor and one rebuilt `/FUNCT` per gas that carried no information.
     The same reasoning settles `Tswitch` on FVMBAG2, which `fv_up_switch.F`
     measures as `TT − TTF`: with no sensor it is measured from t = 0, which is
     exactly what LS-DYNA's `TSW` means.

  5. **Every leak path is a VENT HOLE and `Nporsurf` is 0.** Radioss has a
     porous-surface block that looks like the natural target for the fabric
     porosity, and d2r uses it. Two things argue against copying that. The
     vent sub-block is the one whose layout is pinned identical across the
     three monitored volumes this batch writes, while the porous block's is
     documented for `/MONVOL/COMMU1` (type 9) only — and there
     `hm_read_monvol_type9.F` DISCARDS half of what d2r writes into it whenever
     `Iformps == 0`: `IF (CLEAK > ZERO) IPORT = 0`, `IF (AVENT > ZERO)
     IPORA = 0`, `IPVENT = 0`, `IBLOCKAGE = 0`. MEASURED on a probe — a porous
     surface written with `surf_IDps=8005, Iblockage=1, fct_IDcps=106,
     fct_IDaps=108` echoes back `POROUS SURFACE ID = 0` and both functions 0.
     Second, `CP23` is a dimensionless orifice coefficient and `AP23` an area,
     so their product is an effective leak area — exactly the shape of batch
     1's `MU*AREA`, and exactly what `Avent` means with no named surface.

  6. **`OPT` is honoured, and dyna2rad never reads it.** LS-DYNA itself zeroes
     `CP23`/`LCP23`/`AP23`/`LCAP23` whenever `OPT != 0` and takes the porosity
     from `*MAT_FABRIC`'s FLC/FAC instead (Vol I R17 p.3-48, mirrored by the
     reader cfg at `subobj_airbag_hybrid.cfg:43`). `grep LSD_OPTHybrid` over the
     whole of `convertcontrolvols.cxx` returns nothing, so an `OPT != 0` deck
     gets a leak path the LS-DYNA run does not have. Here the four columns are
     ignored and the `*MAT_FABRIC` leakage path — which this batch does not
     convert — is named as the loss.

  7. **A pop-open pressure needs `Tstart` pushed out of reach.**
     `airbagb1.F:290` ORs the two opening criteria —
     `IF(IDEF==0 .AND. TT>TVENT .AND. TT<TSTOPE) IDEF=1` — so a vent whose
     `Tstart` is 0 opens on the first cycle and `dPdef` is never tested. That
     is why d2r's `dPdef = 1e30` does not seal a vent, and why writing `PVENT`
     into `dPdef` alone would not open one. Both `PVENT` (HYBRID card 5) and
     `PPOP` (PARTICLE vent rows) become `dPdef` with `Tstart = 1e30`, the same
     sentinel the starter uses itself for a zero-area vent
     (`hm_read_monvol_type11.F:809-810`). d2r never reads `PPOP` at all, so a
     vent that should stay shut until the bag reaches that pressure opens at
     t=0 there. `PVENT` gates the ORIFICE only: a weave leaks whenever there is
     a pressure difference across it, and putting the threshold on the fabric
     porosity too would SEAL a leak LS-DYNA has open from t=0.

  8. **Named vent surfaces, and the subset rule.** The `surf_IDv != 0`
     machinery batch 1 deferred. A vent whose card names a part — HYBRID's
     negative `A23` (a `*PART` when `LCA23 != -1`, a `*SET_PART` when it is
     `-1`) or PARTICLE's `SID3`/`STYPE3` — gets its own `/SURF` from the same
     element-backed builder the bag's external surface uses, and `Avent` then
     changes meaning: an absolute AREA with `surf_IDv = 0`, a SCALE FACTOR on
     the surface's current area otherwise. Three rules are enforced at
     conversion time: shell-backed (`ERROR 330` / `ERROR 532`), a **subset of
     the bag's own external surface** — which Radioss states outright for the
     communicating case, `ERROR 902` *"COMMUNICATING SURFACE ID=%d IS NOT
     INCLUDED INTO AIRBAG SURFACE ID=%d"*, so elements outside the bag are
     dropped with that quoted — and the sharing is REQUIRED rather than double
     counting, because `surf_IDex` measures the volume while `surf_IDv` scales
     an area and nothing is summed across the two.

  9. **`_JETTING` is read in full and its jet is DROPPED, with every field
     named.** Radioss's jet block is node-based — `Ijet`, `node_ID1` (the focal
     point), `node_ID2` (a point on the axis), `node_ID3` (0 conical, non-zero
     dihedral, `hm_read_monvol_type9.F` formats 1460/1461) — and LS-DYNA states
     the same geometry twice, as coordinates AND as optional nodes that
     OVERRIDE them, so the GEOMETRY looks like a 1:1 map. **The functions are
     not, and without them the geometry cannot be written at all.** `Ijet = 1`
     obliges `fct_IDPt`, `fct_IDPTheta` and `fct_IDPDelta`, and the reader has
     NO zero guard: `hm_read_monvol_type7.F:579-620` (identically `_type9.F`
     `:594-635`) searches each id in `NPC` inside `IF (IJET(II) > 0)` and calls
     `ANCMSG(MSGID = 12/13/14, MSGTYPE = MSGERROR)` when it is not found, and
     id 0 never is. MEASURED on two converted decks: 3 ERROR(S), `UNDEFINED
     POROSITY/TIME|PRESSURE|AREA FUNCTION ID=0`, ERROR TERMINATION, no restart
     file — the run never starts. Two of the three could be defended
     (`f_theta` from the cone half-angle `CA`, `f_t` and `f_delta` flat) but
     `FscalePt` is a jet PRESSURE and LS-DYNA states none: it derives the jet
     from the inflator mass flow and the Bernoulli efficiency `BETA` through a
     different formulation. Radioss SUPERPOSES the jet on the uniform pressure
     (`volpres.F`: the uniform loop applies `DP`, the jet loop then ADDS
     `PJ = ¼·FscalePt·f_t·max(0,cos α)·f_theta·f_delta` on the same segments),
     so an invented `FscalePt` is an invented load on top of a correct one. A
     dropped jet under-states the directionality; a fabricated one mis-states
     the force. So `Ijet = 0`, the node columns 0, and a warning naming
     node_ID1/2/3, `CA`, `BETA`, `PSID` and `NREACT` by value. VALIDATED: the
     converted deck is byte-identical to the same bag without the jetting card
     apart from its title, starter 0 ERROR(S), engine NORMAL TERMINATION.
     Dropping it also makes the jet nodes a non-question — they are never
     written, so they cannot name a node the deck does not define, the ERROR-70
     class every other reference in this module is screened against.
     dyna2rad reads NONE of the jetting block — `jettingoption`, `XJFP`,
     `XJVH`, `NODE1`, `NREACT`, `PSID` and `LSD_CA` are all zero-hit greps —
     and issues no warning. **Card 7 is read by the MANUAL, not by the reader
     cfg**, which writes it as seven fields with `IDUM` omitted: a
     cfg-following reader puts `NODE1` in the `IDUM` slot and drops `NODE3`.

  10. **`/MONVOL/FVMBAG2` is emitted and CANNOT RUN on an open-source build.**
      `init_monvol.F` demotes FVMBAG2 to FVMBAG1 immediately after reading
      (*"FVMABG2 are in fact FVMBAG1 with simplified input"*) and then meshes
      the bag's interior with tetrahedra. `hm_read_monvol_type11.F:299`
      hard-wires `KMESH = 14`, `init_monvol.F` dispatches `CASE (12, 14)` to
      `HYPERMESH_TETRA`, and `starter/stub/fvmbags_stub.F` is a stub that
      prints `FVMBAGS require a mesher` and `STOP`s. MEASURED on a probe deck:
      the reader echoes the entire `/MONVOL` cleanly and the starter then dies
      before writing a restart file. The card is the correct conversion and a
      commercial build meshes it, so it stays the default — with a warning that
      quotes the stub — and **`--airbag-particle-uniform`** trades the
      finite-volume pressure field for a uniform-pressure `/MONVOL/AIRBAG1`
      that inflates. Gas species, injector, vents and porous surfaces are
      identical either way.

  11. **`SD1 \ SD2` is the external surface and `SD2` is the internal one.**
      An internal baffle left in the external surface is a T-connection on
      every one of its edges — `WARNING 1882`, *"EXTERNAL SURFACE CONTAINS
      T-CONNECTIONS CANNOT BE ORIENTED BY RADIOSS STARTER"* — and the
      orientation pass then gives up on the WHOLE bag. Note `STYPE1`/`STYPE2`/
      `STYPE3` use the OPPOSITE convention from card 1's `SIDTYP` on the other
      six models: **0 is a PART here** and a `*SET_SEGMENT` there.

  12. **The nozzle classification fixes three dyna2rad defects.** Only `VDi`
      of −1/−2 (and −3/−4 with an offset) makes `NIDi` a SHELL ELEMENT id
      rather than a node id, which is the only form that can become
      `surf_IDinj`; Radioss says so itself, message 200035 *"Inflator nozzles
      can be defined only by shells VID=-1 or VID=-2"*. d2r declares its
      `sh4n`/`sh3n` flags OUTSIDE the loop and never resets them
      (`:1467-1483`), so once one `NIDi` resolves as a `/SHELL` every later one
      is pushed into the quad list whatever it is; both branches write
      `surf_IDinj` row 0, so the SH3N write at `:1518` overwrites the SHELL one
      and a mixed bag loses its quads; and both sets are written with the
      `/PART` entity type for what are element ids. Here each id is classified
      on its own and a mixed set is wrapped in a `/SURF/SURF`.

  13. **`Iswitch = 1` accompanies `Tswitch`, which is inert without it.**
      `fv_up_switch.F` gates the whole uniform-pressure switch on `IVOLU(74)`,
      and `monvol_fvmbag2.cfg:393` reads 0 as *"No switch to uniform
      pressure"* — so d2r's `CopyValue("TSW","Tswitch")` at `:2255` can never
      fire. Worse, that copy sits INSIDE its porous-surface loop, so on a bag
      with no LAW58 fabric part `TSW` is not copied at all. `Cgmerg = 0.05`
      (the cfg default is 0.02 — d2r deliberately coarsens the merge, which
      keeps the FV count and hence the bag's own step from collapsing as the
      bag folds), `Dtsca = 0.9` and `Dtmin` per the `UNIT` flag (1e-4 for the
      ms system, 1e-7 for the two s systems — one floor written twice; `UNIT=3`
      states its factors on a card this converter does not read, so `Dtmin` is
      left blank and said so).

  14. **`IH3D` is not written.** It appears at columns 41-50 of FVMBAG2 card 1
      from `FORMAT(radioss2023)` on, and this converter writes `/BEGIN 2022`.
      MEASURED on a twin-deck probe: writing it at 2022 costs `WARNING 100213`
      ("unsupported field exists at the end of line") and the field is dropped
      with no shift — survivable, but a warning for a column carrying nothing.

  15. **`*AIRBAG_INTERACTION` is one row per DIRECTION, not one per card.**
      The Radioss block is not reciprocal — each volume carries its own entry
      naming the other — and the engine only ever pushes gas downhill,
      `airbagb1.F` guarding the whole flow with
      `IF(IDEF==1 .AND. P>PVOIS .AND. …)`. So LS-DYNA's two-way `IFLOW = 0` is
      two rows and a one-way IFLOW is one, and with a one-way flow the
      RECEIVING bag stays `/MONVOL/AIRBAG1`: the same gas model, its AC/UC
      channels would read zero anyway, and a COMMU1 with `Nbag = 0` is exactly
      what `monvol_commu1.cfg:255-259` refuses. `AREA` becomes `Acom` (an
      absolute area with no `surf_IDc`, a scale factor with one), `SF < 0`
      becomes `fct_IDCt`, `PID` becomes the shared partition surface, and
      `LCID`, `EXCP` and a negative `AREA` each get a named verdict — the last
      because `airbagb1.F` evaluates a communicating vent's pressure function
      at `(P − PVOIS)`, the PARTNER difference, so an absolute-pressure curve
      has no abscissa to be shifted onto. A partner that is not
      COMMU1-expressible drops the interaction naming BOTH bag ids and what
      each converted to.

  16. **`/TH/MONV` gains two rows and is keyed on the resolved card type.**
      `COMMU1` moves `AC`/`UC` into the base set (they are the `DO I=1,NAV`
      communication loop's own sums, and a COMMU1 only exists here because an
      interaction filled its block, so they are never structurally zero).
      `FVMBAG2` gets **`DTBAG`, `NFV` and `UPCRIT` back** — the #123 handoff:
      both were dropped from AIRBAG1 as MEASURED flat zeros and named as
      belonging "to the batch that adds `/MONVOL/FVMBAG1`". `fvbag1.F:1832`
      sets `FSAV(13) = DTX`, `:1801` sets `FSAV(14) = NPOLH`, and
      `FSAV(19) = PDISP` is the switch criterion; `AC`/`UC` (no communication
      loop) and `WORK` (never assigned on the FV path) stay out. The map reads
      `Airbag.radioss_type`, not the keyword, because a hybrid bag becomes a
      COMMU1 when an interaction names it and a particle bag becomes an
      AIRBAG1 under `--airbag-particle-uniform` — keying off the keyword would
      request channels the emitted card does not fill.

  17. **Count-driven card walks, and the one that cannot be walked (#119).**
      A `*AIRBAG_HYBRID` gas pair is ONE card or TWO depending on whether the
      deck carries the `FMASS` line (a later addition real decks omit), and the
      stride positions the jetting cards below it — so it is decided by
      CONTENT: card 5.2 has at most one populated cell, so a card with two or
      more at that position is the next gas's card 5.1. A BLANK card is not
      the end of the block: `FMASS`'s default is "none" (Vol I R17 p.3-49), so
      an all-spaces card 5.2 is legal and is how a preprocessor writes
      `FMASS = 0` — and it has ZERO populated cells, the same count an ABSENT
      card has. MEASURED with `NGAS = 2` and a blank card 5.2, deciding on that
      card alone collapsed the stride to 1: gas 2 came back `MW = 0`, no
      `/MAT/GAS` was emitted for it, the injector lost a row and the mixture
      was built from gas 1 alone (MW 0.03544303797 instead of 0.02875481386) —
      on a deck the starter accepts and runs. So a blank card is disambiguated
      by looking one further: a blank followed by a populated card was card
      5.2. `*AIRBAG_PARTICLE` walks `NVENT`, `NGAS`, `NORIF`
      and the `VDi ∈ {−3,−4}` offset card, skips `NPDATA` rows by count, and
      finds its two optional continuation cards by their leading `+`. The
      `STYPE2 == 2` block is `|SD2|` rows — a count that only exists after the
      `*SET_PART` is resolved, i.e. after parsing — so that case ABANDONS the
      walk with a warning rather than guessing; everything past it would be
      read one card out of place. The abandonment costs the cards BELOW card 1
      and not card 1 itself — the walk has already computed that index and
      hands it back, because recomputing it as `_title_offset(block)` misses
      the `_MPP` and `_TIME` prelude cards and reads `SID1` off the `SX SY SZ`
      line. `_MPP` also moves the `_ID`/`_TITLE` card: Vol I R17 p.3-94's Card
      Summary puts *Card MPP* BEFORE *Card ID*, so on `*AIRBAG_PARTICLE_MPP_ID`
      the ABID and heading are `raw[1]`, not `raw[0]` — only the card COUNT is
      order-independent. dyna2rad's own reader has the `NPDATA` block
      commented out (`airbag_Particle.cfg:1068-1086`), so those rows are
      consumed as VENT cards there.

  18. **The `#120` registry audit.** `/MONVOL` ids stay on `next_monvol_id`
      (a HYBRID `_ID` 42 and a PARTICLE `_ID` 42 both want 42 — `ERROR 79`
      without the guard); `/MAT/GAS`, `/PROP/INJECT1`, `/FUNCT` and the `/SURF`
      groups stay on their existing guarded allocators. The implicit free-node
      guard, `keep_free` and `--auto-gapmin` are **untouched**, and the premise
      that lets them be is re-stated: a monitored volume owns no node, and the
      finite-volume mesh of an FVMBAG2 is generated inside the STARTER
      (`init_monvol.F` appends its extra vertices to `ITAB` itself), so no FV
      node exists in the deck to be found free. Nor does any other: the
      jetting `node_ID1/2/3` are not emitted at all (decision 9) and
      `*AIRBAG_PARTICLE`'s node-form orifices and its card-7 nozzle-frame
      `NID1..NID3` are named-and-dropped, so the batch adds **no node
      reference of any kind** to the deck. `*INCLUDE_TRANSFORM` specs walk all three
      card stacks, including every cell whose BUCKET depends on a neighbour:
      `A23`'s sign with `LCA23` (a `*PART` id or a `*SET_PART` id), `SD1`/`SD2`
      /`SID3` with their type flags, and `NIDi` with `VDi` — the one cell in
      the family whose ENTITY TYPE, not just its namespace, depends on another
      cell.

  **Corpus.** The batch-2 keywords have **zero carriers** anywhere available —
  an exhaustive `^\*AIRBAG` scan over the repo tree, `E:/openradioss_run`,
  `E:/foxcore_data` and the 356-deck `dynaexamples_r14_ton-mm-s` corpus finds
  only `*AIRBAG_SIMPLE_AIRBAG_MODEL` and `*AIRBAG_SIMPLE_PRESSURE_VOLUME`. So
  the sweep is a REGRESSION check rather than a coverage one: master vs branch
  over the 6 airbag/fabric carriers plus the Yaris and Camry production decks
  plus a random 140-deck sample (2 kB – 2 MB, seeded), **0 differing `.rad`
  files and 0 return-code mismatches**. Batch 1 shares the vent emitter, the
  injector emitter and the `/TH/MONV` table with batch 2, so all three had to
  stay strict no-ops for it, and they are — pinned twice over by the five
  checked-in goldens and by a `*AIRBAG_SIMPLE_AIRBAG_MODEL` asserted column for
  column through the now list-taking emitters.

  The review round re-ran that check against its own changes: all **6 real
  `*AIRBAG` carriers** in the corpus (`airfilled.sphere.k`, two
  `airbag.deploy.k`, `volume.k`, two `tire-compression.k`) convert
  byte-identically on master and on the branch with identical warning counts —
  as do the **4 Yaris production decks** (1512 / 1978 / 4823 / 4823 warnings,
  unchanged) — and **21 of the 23** solver-validated batch-2 decks regenerate
  with the same
  SHA256 and the same warning count as the run that validated them. The two
  that changed are the jetting pair, and they changed to the deck the no-jet
  control already produced.

  Tests: `tests/test_airbag_batch2.py`, **131 tests + 70 subtests**, every card
  assertion by COLUMN and every fixture number distinct per slot so a swap
  between two of them cannot pass — the two gases differ in MW by 14 %, in
  INITM by 3.8×, and in A/B/C by ~5 %, 3.7× and 2.8×, which is what makes the
  mole-fraction rule falsifiable against dyna2rad's arithmetic mean. Hand-
  computed values pinned in the docstrings: the mixture from
  `Σ = 0.79/0.028 + 0.21/0.032 = 34.7767857143` giving
  `MW = 0.0287548139`, `x₁ = 0.8112943633`, `x₂ = 0.1887056367`; `Avent = 70`
  as an area and `Avent = 0.7` as a scale factor; the `−Pext` shift
  `0.101325 → 0` and `0.201325 → 0.1` with the ordinates untouched; `Dtmin`
  1e-4 / 1e-7 / 1e-7 for `UNIT` 0 / 1 / 2; and `Iflow = 1` on a FLAT rate
  curve, chosen so that the differenced reading of it would be zero rather
  than merely small.

  **Review round.** Fourteen defects found by an adversarial re-read of the
  batch against the starter/engine source and Vol I R17, and by running the
  converted decks. Two were blockers.

  a. **`_JETTING` emitted a deck the starter REFUSES** — see decision 9, now
     rewritten. `Ijet = 1` with three zero function ids is `ERROR 12/13/14`;
     MEASURED, 3 ERROR(S) and no restart file on every jetting deck. Now
     `Ijet = 0` with a loud drop, VALIDATED: byte-identical to the same bag
     without the jetting card apart from the title, starter 0 ERROR(S), engine
     NORMAL TERMINATION at 375 cycles — the no-jet control's own cycle count.
  b. **The card-4 AREA columns multiplied where LS-DYNA overrides.** A23/LCA23
     and AP23/LCAP23 obey the same override the coefficient columns do — see
     the note under decision 8. `A23 = 0` with `LCA23 > 0`, the documented
     pressure-dependent form, gave `Avent = 0·C23 = 0`: a bag that NEVER vents,
     MEASURED as `WARNING 1019 ... AREA IS NOT DEFINED, AVENT = 0` on a run
     with 0 ERROR(S). `A23 ≠ 0` with `LCA23 > 0` vented through `A23·f(P)`
     rather than `A23`.
  c. **The mixture MW was not normalised by `Σ INITM`** — see decision 3.
  d. **The negative-gamma guard was dead on the whole batch.** It gated on
     `/MAT/GAS/MASS`, and every batch-2 gas is `MOLE`. MOLE is at risk
     identically (`hm_read_matgas.F:295` divides the entered Cp by MW, so the
     solver reaches the same mass-specific Cp) and MORE likely to be wrong,
     because the card then carries the raw SI molar numbers that look correct
     on paper. MEASURED: the batch-1 MASS card was flagged while the batch-2
     MOLE card passed in silence and the starter echoed
     `GAMMA AT INITIAL TEMPERATURE = -3.5972E-03` with 0 ERROR(S).
  e. **A blank `FMASS` card collapsed the NGAS stride** — see decision 17.
  f. **Only the FIRST `*AIRBAG_INTERACTION` touching a bag converted.**
     `_COMMU1_PROMOTABLE` held `AIRBAG1` alone, so the middle bag of a chain
     was already a COMMU1 when the second card was read and the second card was
     dropped — with a warning that contradicted itself ("gas exchange needs
     BOTH bags on /MONVOL/COMMU1, and airbag 43 converts to /MONVOL/COMMU1").
     Multi-chamber bags are the primary reason the keyword exists, the `Nbag`
     block is N-row by construction and `monvol_commu1.cfg:255-259` allows
     `NBAG <= 20` — now honoured, cap included.
  g. **A stated `AREA` was discarded whenever `PID` resolved.** "EQ.0.0: AREA
     is taken as the surface area of the part ID defined below" (Vol I R17
     p.3-91) — so PID supplies the area ONLY when AREA is 0. On a 100 mm²
     partition, `AREA 33.3` with `SF 0.85` vented through 85 rather than 28.3,
     byte-identical to a deck stating no AREA at all. A stated AREA now becomes
     `Acom = AREA·SF` with `surf_IDc = 0` (a CONSTANT orifice, which is what a
     stated AREA means) and the partition `/SURF` is dropped rather than
     orphaned.
  h. **`*AIRBAG_HYBRID_CHEMKIN` was routed to the HYBRID reader.** It is a
     MODEL of its own — Vol I R17 p.3-54 gives it card 3 `LCIDM LCIDT NGAS DATA
     ATMT ATMP RG`, card 4 `HCONV`, card 5 `C23 A23` and per-species
     thermodynamic cards — so reading it as a HYBRID takes its curve ids for
     ATMOST/ATMOSP. Master had it on `handle_airbag_unsupported`; it is back
     there, with `_CHAMBER` (not a documented `*AIRBAG` option at all) left to
     the named prefix net.
  i. **`*AIRBAG_PARTICLE_MPP`'s ABID came off the `SX SY SZ` card** — see
     decision 17. A wrong ABID also makes every `*AIRBAG_INTERACTION` naming it
     report the bag as undefined, and let the `*INCLUDE_TRANSFORM` header
     rewriter add an id offset to `SX`.
  j. **The `STYPE2 == 2` abandonment threw away the card-1 index it had** —
     see decision 17.
  k. **A vent part OUTSIDE the bag was sealed.** For `*AIRBAG_HYBRID`'s
     negative `A23` that configuration is documented: "airbag pressure will not
     be applied to part/set |A23| ... if part/set |A23| is not included in SID
     ... The area of this part/set becomes the vent orifice area" (Vol I R17
     p.3-46). `ERROR 902` is the COMMUNICATING-surface rule and does not reach
     it. The part's initial area is now frozen into `Avent` with
     `surf_IDv = 0`, with the loss of area tracking named.
  l. **A blank `C23`/`CP23` was read as 1.0.** "Vent orifice coefficient which
     applies to exit hole. Set to zero if LCC23 is defined below" (p.3-46) —
     the mass flow is `C23·A23·<isentropic>`, so a blank with no curve is NO
     flow. The converted bag leaked where LS-DYNA's was sealed; now no vent
     hole is emitted, for the same reason the `OPT ≠ 0` branch drops the fabric
     columns.
  m. **`SEGSID`, `JNODE`, card 7's `NID1..NID3` and `_INFLATION` were read past
     in silence.** Each is now named by value: `SEGSID` NARROWS the monitored
     volume ("The segments define the volume and should belong to the parts
     from SID1", p.3-99) so dropping it makes the bag measure more volume than
     LS-DYNA's; `JNODE` takes the vent thrust reaction (Remark 18); `NID1-3`
     are "Three nodes defining a moving coordinate system for the direction of
     flow through the gas inlet nozzles" (p.3-104); `_INFLATION` ADDS MASS over
     the `NPRLX` steps to hold the starting pressure (Remark 17).
  n. **Housekeeping.** A species with no mass-flow curve no longer allocates a
     `/MAT/GAS` id or synthesizes an injection-temperature `/FUNCT` that
     nothing references; `Ittf` is a declared field of `Airbag` rather than one
     attached by the writer; `AirbagVent`'s never-assigned `iform`-companions
     (`bvent`, `fct_a`, `pids`) are gone; and `_make_monvols` diagnoses an
     unresolved `radioss_type` instead of falling through to `/MONVOL/PRES`.

  Suite 3495/2/1239 → **3626/2/1325**.

  **Verification round (post-merge).** An independent adversarial
  re-verification of the merged batch raised thirteen findings, none of them a
  blocker and none of them a wrong emitted number. Two changed behaviour, one
  narrowed a card-walk look-ahead, three closed test gaps and the rest were
  prose that had drifted from the code.

  1. **An orphan `/FUNCT` on a bag with no vent.** `_gauge_shifted_curve`
     allocates an id and calls `add_curve` as a SIDE EFFECT, and it was
     evaluated BEFORE the branch that decides whether a vent hole exists. A
     card 4 with `C23` blank, `LCC23 = 0`, `A23 = 0` and `LCA23 > 0` therefore
     wrote `MONVOL_<id>_LCA23_GAUGE` onto a bag emitting `Nvent 0` — MEASURED,
     the id occurs exactly once in the whole starter, on its own definition
     line. Harmless to the reader, but it spends a `/FUNCT` id and breaks the
     "every synthesized `MONVOL_*` function is referenced" invariant the batch
     pins. The copy is now built inside the branch that consumes it.
  2. **A stated constant `C23` with no area was dropped in silence.** The
     "coefficient but no AREA" warning gated on `fct_t`, which is only set when
     the coefficient arrived through `LCC23`, so `C23 = 0.7` with
     `A23 = LCA23 = 0` fell off the end of the chain — while the mirror case on
     the fabric path (`CP23` stated, `AP23 = 0`) had always warned. The branch
     is now a plain `else` (`c23 != 0.0` is guaranteed there, because the only
     way it can be zero is the "neither `C23` nor `LCC23`" branch above it) and
     names the dropped coefficient by value. The **"NO VENT at all"** text no
     longer claims card 4 "gives neither a vent orifice (C23/A23) nor a fabric
     porosity" on a deck that states one: it lists what the card DOES state and
     defers to the warning that explains which half is missing.
  3. **The blank-`FMASS` look-ahead is decided on COLUMNS, not on a cell
     count.** With a blank card where 5.2 would be, the stride was 2 whenever
     the card one further on had ≥ 2 populated cells. An entirely blank
     jetting card 6 IS a legal jet — `NODE1`/`NODE2` on card 7 override
     `XJFP`/`XJVH` (Vol I R17 p.3-51) and `CA`/`BETA` are optional — so at
     NGAS = 1 with the FMASS card genuinely ABSENT, card 7 in node form
     (columns 1-50 empty) was taken for a gas card 5.1 and card 6 was then read
     off card 7: the drop warning reported `node_ID1/2/3 = 0` and `CA`/`BETA`
     out of the node columns. A card populated only in slots 5-7 is now
     recognised as card 7, because a gas card 5.1 must carry `MW` in slot 3
     (`MW = 0` is starter `ERROR 710`). **Nothing emitted changes** — the jet
     is dropped unconditionally either way and `Ijet` is written 0; what
     changes is that the warning names the nodes the deck states.
  4. **Three fixes that had no guarding test now have one**, each
     mutation-checked: the `NBAG <= 20` cap (`monvol_commu1.cfg:255-259`,
     `CHECK(COMMON) { NBAG > 0; NBAG <= 20; }`), the "an uninjected species
     consumes no `/MAT` id" half of the housekeeping fix — pinned as the whole
     synthesized id stream, since an emitted-block count cannot see a burnt id
     — and `_make_monvols`' diagnosing `else`, which no deck can reach and
     which therefore needed a direct test rather than a comment.
  5. **`*DEFINE_CPM_*` is now a named warn-drop.** The six documented
     spellings (`_BAG_INTERACTION`, `_CHAMBER`, `_GAS_PROPERTIES`, `_NPDATA`,
     `_SWITCH_REGION`, `_VENT`; Vol I R17 pp. 17-88…17-99) fell to the generic
     unsupported-keyword skip list, which names them but gives no reason. They
     are extended inputs of an `*AIRBAG_PARTICLE` bag that still converts, so
     the only sign that a chamber or a vent option has stopped applying is the
     line that says so. `HANDLERS` only, never `_OFFSET_SPECS` — an unmodelled
     card stack must not have its cells rewritten by position.
  6. **Citations and counts corrected.** The A23 comment quoted
     `*AIRBAG_WANG_NEFSKE`'s p.3-23 wording ("EQ.0.0: Set A23 to zero if LCA23
     is ≠ 0") as though it were `*AIRBAG_HYBRID`'s; p.3-46 reads *"Set A23 to
     zero if a positive LCA23 is defined below"*, and "a POSITIVE LCA23" is the
     load-bearing half — it is what excludes the `LCA23 = -1` part-set
     sentinel, which the code already had right. The jet-guard citation is
     widened from `hm_read_monvol_type7.F:585-620` to `:579-620` (the guard
     opens at `:579`, the three `ANCMSG` are at `:594`/`:606`/`:618`) and the
     `_type9.F` companion corrected from `:594-637` to `:594-635`; the fabric
     porosity is described as `VENT HOLE n of n` rather than always "a SECOND
     VENT HOLE", which contradicted the `Nvent 1` it produced on a bag with no
     exit orifice; the test module's mixture rule is restated as
     `M = sum(w_i) / sum(w_i/M_i)` with the scale-invariance note; and the
     README's `*AIRBAG_PARTICLE` row gains `_INFLATION` and `_JET`. For the
     record, since the merged PR body states otherwise: the generated
     `AIRBAG*` registry is **434** `HANDLERS` keys and **384** `_OFFSET_SPECS`
     keys at this commit (469/424 was the pre-review count), the 50-key
     difference being the warn-drop models, which are deliberately `HANDLERS`
     only; and `*AIRBAG_WANG_NEFSKE*` has **six** option combos —
     `{_JETTING/_MULTIPLE_JETTING}{_POP}` — i.e. 30 generated keys, not four.

  Suite 3626/2/1325 → **3641/2/1335**; every emitted `.rad` byte-identical
  across the whole validation corpus except the three shapes named in items 1
  and 2, which no corpus deck carries.

- **The airbag / monitored-volume batch 1:
  `*AIRBAG_SIMPLE_PRESSURE_VOLUME` → `/MONVOL/PRES`,
  `*AIRBAG_SIMPLE_AIRBAG_MODEL` → `/MONVOL/AIRBAG1` + `/MAT/GAS` +
  `/PROP/INJECT1`, `*AIRBAG_ADIABATIC_GAS_MODEL` → `/MONVOL/GAS`,
  `*AIRBAG_LOAD_CURVE` → `/MONVOL/PRES`, `*AIRBAG_LINEAR_FLUID` →
  `/MONVOL/LFLUID`, `*MAT_FABRIC` → `/MAT/LAW19` + `/PROP/TYPE9` or
  `/MAT/LAW58` + `/PROP/TYPE16`, `*AIRBAG_REFERENCE_GEOMETRY` → `/XREF`,
  `*AIRBAG_SHELL_REFERENCE_GEOMETRY` → `/EREF/SHELL` + `/EREF/SH3N`,
  `*CONTACT_AIRBAG_SINGLE_SURFACE` → the single-surface interface or
  `/INTER/TYPE19`, and `*DATABASE_ABSTAT` → `/TH/MONV`.** Nine keywords that
  between them are the whole inflatable-structure subsystem, and on master
  every one of them landed in `skipped_keywords` **with no warning of any
  kind**. Measured over the corpora: `*AIRBAG_SIMPLE_AIRBAG_MODEL` in **7**
  decks (20 occurrences), `*AIRBAG_SIMPLE_PRESSURE_VOLUME` in **2**,
  `*MAT_FABRIC` in **2** — ten decks in all, every one of them in the r14
  `dynaexamples` tree plus the Toyota Yaris and Camry production models, whose
  four tire-pressure bags each are the only thing holding the tires up. A
  dropped airbag is not a missing output card: the mesh, materials, contacts
  and time history all convert, the run reaches NORMAL TERMINATION, and the bag
  simply never inflates. It also took the fabric with it — measured on
  `airbag.deploy.k`, `/PART/3` ("Airbag - Fabric") pointed at MID 3 while a grep
  of the whole `_0000.rad` returned only `/MAT/ELAST/1` and `/MAT/ELAST/2`, with
  no diagnostic on any branch of the converter.

  1. **The external surface must be ELEMENT-BACKED, and a `/SURF/SEG` aborts
     the run.** `check_surf.F:55-62` sets `IGRSURF%ISH4N3N` only for `ELTYP` 3
     (4-node shell) and 7 (SH3N); a segment surface is never resolved back to
     an element at all (`tsurftag.F:293` passes `0, 0`); and every
     `hm_read_monvol_type*.F` then answers `ERROR ID : 18 -- SURFACE ID: %d IS
     NOT DEFINED WITH SHELLS` plus `ERROR ID : 54` and calls `FREERR(3)` —
     starter exit 172, measured on a twin probe. LS-DYNA's `SIDTYP` is inverted
     relative to intuition (**0 = `*SET_SEGMENT`**, non-zero = `*SET_PART`), so
     the segment case is the common one; k2rad resolves those segments back to
     the shells that own them, keyed on the corner-node **set** (a segment's
     start corner and winding are free variables, and a monitored volume's
     surface is oriented by the starter anyway), and emits `/SURF/GRSHEL` plus
     a `/SURF/GRSH3N` under a `/SURF/SURF` where the bag has triangles. When the
     named set family has no set with that id but the other one does, the other
     is used with a warning — which is the difference between converting and
     dropping the r14 deck `introduction/intro-by-a.-tabiei/misc/airbag-i/
     volume.k`, whose `SIDTYP=0` names a `*SET_PART_LIST`.

  2. **Orientation and closure are the STARTER's job, so k2rad measures them
     instead of doing them.** Every MONVOL reader runs
     `MONVOL_CHECK_SURFCLOSE` → `MONVOL_ORIENT_SURF` (all normals onto one
     side) → `MONVOL_COMPUTE_VOLUME` → `MONVOL_REVERSE_NORMALS`
     (`IF (VOL < ZERO)` flip everything), so an inward-wound bag is corrected
     automatically and a converter-side flip would be a *second* correction of
     an already-correct surface. The connectivity is passed through untouched
     and the conversion instead reports, with the engine's own expression
     (`get_volume_area.F90:156-169`, `V = Σ ⅓ (N·c)` with `N = ½ (x13 × x24)`):
     the signed volume, the free-edge count (open bag → the starter tries an
     automatic closure and reports `WARNING 1875` only if it cannot) and the
     non-manifold edge count (a T-connection, on which `MONVOL_ORIENT_SURF`
     gives up with `WARNING 1882` and the reverse pass then returns
     immediately). MEASURED on the corpus: `airbag.deploy.k` 2432 segments,
     volume 754757, wound **inward**; `volume.k` 1538 segments, 1.17e7; both
     `tire-compression.k` decks 1296 segments, 6.887e7 with **144 free edges**
     (the bead ring, open by design). A near-zero volume gets its own warning:
     it means the normals *cancel*, i.e. the winding is mixed and there is
     nothing consistent for the starter to flip.

  3. **`/PROP/INJECT1 Iflow = 1`, the catastrophic slot.** LS-DYNA's `LCID` is
     a mass FLOW RATE (Vol I R16 p.3-13, "Load curve ID specifying input mass
     flow rate", and Remark 2); `airbaga1.F:349-362` branches on
     `IFLU = IGEO(24, I_INJ)` and with `Iflow = 0` DIFFERENCES the curve
     (`DGMASS = MAX(ZERO, GMASS - GMASS_OLD)`) instead of integrating it
     (`GMASS = GMASS*DT1 + GMASS_OLD`). There is no starter diagnostic for it
     and the error is of order `1/Δt`. `Ascale_T` is written as an explicit
     `1.0` for a related reason: it DIVIDES the time abscissa
     (`airbaga1.F:255`) while the `IFLU == 1` integration multiplies by `DT1`
     WITHOUT dividing, so the two paths disagree for any other value.

  4. **`/MAT/GAS` carries a mass-specific `Cp` POLYNOMIAL and Radioss derives
     `Cv`.** `hm_read_monvol_type7.F` forms `CPI = Cpa + Cpb·T + …` then
     `CVI = CPI - R_IGC1/MWI`, so writing LS-DYNA's `CV` into a `Cp` slot
     inverts the gas. LS-DYNA splits the same way (Vol I p.3-16 Remark 3): with
     `CV ≠ 0` the card's `CV`/`CP` are used directly and both are
     mass-specific → `/MAT/GAS/CSTA` with `Cp | Cv` verbatim; with `CV = 0`
     they come from `c_p = (a + bT)/MW`, i.e. card 4a's `A`/`B` are MOLAR →
     `/MAT/GAS/MASS` with `Cpa = A/MW`, `Cpb = B/MW`. The card-4 LAYOUT
     branches on `CV` as well (4a is `LOU T_EXT A B MW GASC`, 4b is `LOU`
     alone), and a deck that writes the 4a columns under `CV ≠ 0` is told they
     are ignored rather than having an ambient temperature invented for it.

  5. **`/MONVOL/GAS Pini = P0 + PE`.** LS-DYNA documents `P0` as a GAUGE
     pressure (`e₀ = (p₀ + pₑ)/(ρ(γ−1))`, Vol I p.3-18) while Radioss feeds
     `Pini` straight into `EI = PINI·(V+VEPS−VINC)/(GAMMA−1)` and applies
     `DP = Q + PRES − PEXT`. dyna2rad writes `PSF·P0` and adds no `PE` — one
     atmosphere short on any SI deck — and drops `RO` and `VINI` entirely, so
     the starter cannot even form the gas's `Cv` (`RVOLU(19)` is only computed
     when `RHOI ≠ 0`). Both are carried here: `Rhoi = RO` and
     `Vinc = VINI/VSCA`.

  6. **`/MONVOL/LFLUID` `P_LIMIT` has to go through a flat `/FUNCT`.**
     `hm_read_monvol_type10.F` overwrites the scale factor whenever no function
     is given — `IF (IFPMAX > 0) … ELSE SFPMAX = INFINITY * FAC_GEN`. Probe:
     `fct_Pmax = 0` with `Fscale_Pmax = 5.5E+06` echoes `MAXIMUM PRESSURE TIME
     FUNCTION SCALE FACTOR = 1.0000000200409E+20`. `Fscale_Padd` with
     `fct_Padd = 0` IS honoured (probe: 1234.0 preserved), which is why a
     scalar `BULK` rides its own scale factor and `P_LIMIT` cannot.

  7. **The SPV pressure law is emitted EXACTLY, with no assumption about V0.**
     LS-DYNA's law is `Pressure = BETA·CN / (V/V0)`, i.e. `p = BETA·CN·V0/V`,
     and Radioss `Itypfun = 0` feeds the function precisely `V0/V`
     (`volpfv.F:61-88`: `XFUN = (V0-VINC)/(VOL-VINC)`) — so a UNIT-SLOPE
     two-point `/FUNCT` with `Fscale = BETA·CN` *is* the law. dyna2rad instead
     bakes `BETA·CN·x` into a 27-point table, silently absorbing a factor `V0`,
     which is right only when `V0 == 1` in deck units. `CN < 0` (|CN| is a
     curve of CN(t)) routes to `Itypfun = 3` — "P = (1/V) F(T)", the one slot
     that evaluates a time function and multiplies by `V0/V` — and `LCID > 0`
     to `Itypfun = 2`, which is LS-DYNA's own relative-volume abscissa.

  8. **`*AIRBAG_LOAD_CURVE`'s `STIME` prepends `(0, 0)`, not `(-1, 0)`.**
     Radioss has no start-time column on `/MONVOL/PRES`, so the curve is
     rebuilt with every abscissa shifted by `+STIME` and a leading zero point
     so the pressure is exactly zero at `t = 0`. dyna2rad prepends `(-1, 0)`,
     which leaves a NON-ZERO pressure at `t = 0` for any `STIME > 1`.

  9. **The vent's `fct_IDP` is a function of the GAUGE pressure `P − Pext`,**
     so a negative `MU` or `AREA` (in LS-DYNA a curve of that quantity vs
     ABSOLUTE pressure) is re-emitted with every abscissa shifted by `−PE` —
     the single most unit-sensitive number in the batch. When BOTH are curves
     the AREA curve is used and the shape-factor curve is named as dropped;
     dyna2rad combines the two point-by-point, ADDING their abscissae and
     scaling the ordinate by the AREA curve's ABSCISSA factor — two defects in
     four lines (`convertcontrolvols.cxx:253-256`).

  10. **The fabric law and its property are ONE decision.** `/MAT/LAW19`
      declares `SHELL_ORTHOTROPIC` (`hm_read_mat19.F:236` → `PROP_SHELL 2`) and
      `check_mat_elem_prop_compatibility.F:174-179` accepts that on
      `/PROP/TYPE9` only; `/MAT/LAW58` declares `SHELL_ANISOTROPIC`
      (`hm_read_mat58.F:334` → `PROP_SHELL 4`), accepted on `/PROP/TYPE16`
      only. Either crossing — and leaving the fabric on the isotropic
      `/PROP/SHELL` its `*SECTION_SHELL` gives it — is `ERROR 3047` and refuses
      the whole deck, so fabric parts are repointed at a synthesized per-part
      property (the #110 honeycomb mechanism) and every other property-assignment
      prepass skips them. The law branch is ONE predicate both writers read
      (the #100 one-map rule): `FORM ∈ {4, 14, −14, 24}` **and** at least one
      card-7 curve → LAW58, everything else → LAW19 — widened from dyna2rad's
      `{14, −14}` so a `FORM = 4` or `24` deck's curves are not discarded.
      `/PROP/TYPE16` is new to k2rad; `/PROP/TYPE9` gains a fabric parametrisation
      (`Ismstr = 4`, `Ish3n = 2`, `Ip = 2`, `Istrain = 1`, `Dm = DAMP`).

  11. **Two fabric column traps, both from a starter twin probe at `/BEGIN`
      2022 / 2024 / 2026.** `/MAT/LAW19` card 4 columns 21-40 are a DEAD SLOT
      the reader never touches (a written `9.99` is echoed nowhere) —
      `ZEROSTRESS` is at 41-60. And `/PROP/TYPE9` card 4 columns **81-90** hold
      nothing at 2022 and become `Ipos` from 2024, silently, with no
      `WARNING 100211` either way — so k2rad leaves them blank and writes `Ip`
      at 91-100, where it lives at every version. (`/PROP/TYPE16` DOES have a
      real `Ipos` cell at 2022, at columns 71-80.) `Ip = 2` rather than a
      global `Vx/Vy/Vz` is itself a fabric rule: on a CLOSED bag any single
      global vector is nearly normal to some shell, and that is `ERROR 197`
      raised ONCE PER ELEMENT.

  12. **`*AIRBAG_REFERENCE_GEOMETRY` and `*AIRBAG_SHELL_REFERENCE_GEOMETRY` are
      mutually exclusive per part.** A node in both a `/XREF` and an `/EREF` is
      `ERROR 1098` (`COMMON NODE IN EREF AND XREF OPTIONS`), and the two
      LS-DYNA cards are written TOGETHER — the node card gives the coordinates,
      the shell card names the elements — so the `/XREF` wins for a part covered
      by both and the `/EREF` rows are dropped, named. The node keyword feeds
      the same per-part `/XREF` the foam keyword does (a SHELL part needs no
      law check: `hm_read_xref.F`'s MTN whitelist is gated on `ITYP == 2`, and
      `cepsini.F::CMLAWI` dispatches `ILAW` 1, 19 and 58, so both fabric laws
      honour it). The `_ID` card's `SX/SY/SZ` about `NIDO` is baked into the
      coordinates about `NIDO`'s own REFERENCE position, where dyna2rad takes
      the structural one and mixes the two geometries. `_BIRTH` becomes a
      `/SENSOR/TIME` on the fabric law's `SENS_ID`, with `*MAT_FABRIC`'s own
      `RGBRTH` winning; `_RDT` is named as dropped.

  13. **`*DATABASE_ABSTAT` gets one `/TH/MONV` PER MODEL, and its `dt` joins
      the `/TFILE` minimum gated on `state.monvol_ids`.** The whole 19-name
      vocabulary is legal on every monitored volume (a probe took all sixteen
      non-vent names on a `PRES` bag without complaint) but the engine only
      fills the `FSAV` slots its own pressure law computes — `volpfv.F` sets
      `FSAV(1) = 0` on a `PRES` bag — so a union would write flat zeros that
      read as data, the trap the `*DATABASE_TPRINT` decision already refused.
      `PRES` takes `VOL P A`, `GAS` adds `MASS T GAMA`, `AIRBAG1` adds the
      mixture `CP CV`, the injected mass and enthalpy, `ENER-INT`, `WORK` and
      `DTBAG` (plus `AO UO AC UC` when the bag really has a vent), `LFLUID`
      takes `MASS VOL P A MASS-IN`. The `/TFILE` exclusion comment that named
      ABSTAT is rewritten rather than left contradicting the code, and the gate
      is the #122 membership test — "does this card pace a channel that is IN
      the T01", not "is this card in the deck".

  14. **`*CONTACT_AIRBAG_SINGLE_SURFACE` is a handler ALIAS, verified by
      column.** `contact_airbag_single_surface.cfg:556-563` writes card 1 as
      `%10d          %10d          %10d          %10d%10d`, i.e. the two-sided
      grid with the B-side cells blank — so `SSID`, `SSTYP`, `SBOX` and `SPR`
      land on grid indices 0, 2, 4 and 6 exactly as on `*CONTACT_AUTOMATIC_*`,
      and card 3's `SFS`/`SST`/`SFST` on 0, 2 and 4. The only genuinely new
      field is `IFLAG` in slot 7, which dyna2rad reads and then IGNORES (both
      of its `IFLAG` branches are commented out and the live test is on
      `SOFT`), so it is named rather than acted on. `SOFT = -19` routes to the
      airbag flavour of `/INTER/TYPE19`: `Istf = 4`, `Idel = 2`, `Ibag = 1` and
      `Gapmin = |SST|/2 · SFST` (single-sided and scale-weighted; the card has
      no `MST` column, so the two-sided helper would read a blank as a second
      thickness). `Ibag` is gated on a converted `/MONVOL` — with `NVOLU == 0`
      the starter resets it and raises `WARNING 614`
      (`hm_read_inter_type07.F:403-410`) — and `Edge_scale_gap` (dyna2rad
      writes 0.9) is NOT emitted, because that column exists only from
      radioss2024 while k2rad declares `/BEGIN 2022`.

  15. **A `/MONVOL` id already claimed by another `*AIRBAG_*` is RENUMBERED.**
      LS-DYNA's airbag ids are per KEYWORD while Radioss's `/MONVOL` namespace
      is shared across `PRES`/`AIRBAG1`/`GAS`/`LFLUID`, so a collision is legal
      input; dyna2rad's second `CreateEntity` fails its `IsValid()` guard and
      the bag vanishes with no message (`convertcontrolvols.cxx:85`). Two bags
      taking their surface from the same set are also named — each gets its own
      `/SURF` and the starter measures both independently, but they describe one
      cavity and their pressures add.

  16. **Registry audit (#120).** A monitored volume owns no node and no
      element, so the implicit free-node guard, `keep_free`, the `--auto-gapmin`
      faceting and side resolution, and contact scoping over fabric parts are
      all untouched — verified rather than assumed, because two of the r14
      airbag decks are IMPLICIT and do exercise the free-node guard. What did
      need work: the `/TFILE` chain (13 above), `_target_mat_law` and the
      `_ref_flag_materials` negative record for `*MAT_FABRIC` (it carries no
      `REF` flag on any of its eight cards), `*INCLUDE_TRANSFORM` offset specs
      for `*MAT_FABRIC` (a callable — card 7's index moves with `FORM` and
      `FVOPT`) and for `*CONTACT_AIRBAG_SINGLE_SURFACE`, and — new — a deck-wide
      **part → material existence scan** beside `_warn_duplicate_prop_ids`,
      which turns the silent `/PART`-points-at-nothing class into a named
      warning the way that scan turned a silent `ERROR 79` into a named one.

  17. **The card walks are RAW-contiguity (#119) on three keywords whose card
      indices really move.** `*AIRBAG_*` card 3 sits up to SIX lines below card
      1: `RBID > 0` inserts an `N` card plus `ceil(N/5)` constant cards and
      `RBID < 0` inserts three sensor cards, so a fixed `offset + 1` reads a
      sensor's acceleration magnitudes as the model's thermodynamic constants.
      `*MAT_FABRIC` shifts on `FVOPT < 0` (card 4) and on `FORM` (cards 7 and
      8) — reading card 5 blind on an `FVOPT < 0` deck takes the `L/R/C1/C2/C3`
      leakage row as `RGBRTH/A0REF/A1..A3` and synthesizes a birth sensor the
      deck never asked for. Both suffix stacks are generated from ONE source
      (#116), including every legal permutation of the reference-geometry
      options, and the seven unconvertible `*AIRBAG_*` models are REGISTERED to
      a handler that warns by name rather than left to `skipped_keywords`.

  18. **Validated against the real OpenRadioss starter, which caught three
      defects the test suite could not.** A probe deck exercising every card in
      the batch — four monitored volumes (one per model), a LAW19 fabric part,
      a LAW58 fabric part with all six curves, a /XREF, an airbag contact and
      a *DATABASE_ABSTAT — was run through `starter_win64.exe`:

      * `Ip = 2` on the fabric properties gave **99 x ERROR 197** ("REFERENCE
        DIRECTION IS ALMOST NORMAL TO SHELL ID=%d", one per element per pass)
        and ERROR TERMINATION. `IRP` is a SPARSE ENUM, not an index:
        `corthini.F:122` is a `SELECT CASE (IRP)` over exactly 0/20/22/23/24/25
        and a 2 matches no branch, so `Vx/Vy/Vz` are never assigned and the
        projection check at `:610` reads uninitialised memory. **20** is
        "N1 -> N2 (nodes)", the per-element direction actually wanted. AOPT 3
        likewise moves to `Ip = 23` ("proj on the element, V x normal"), which
        computes the cross product LS-DYNA's AOPT 3 defines, so BETA carries
        over with NO +90 offset.
      * The LAW58 **shear** curves needed two rewrites: the abscissa is the
        shear ANGLE IN DEGREES (`sigeps58c.F:527`,
        `PHI = atan(TAN_PHI)*180/PI`) where LS-DYNA gives an engineering shear
        STRAIN, and the curve must span BOTH signs — `law58_upd.F`'s
        `FUNC_INTERS_SHEAR` wants two loading/unloading intersections
        straddling zero and answers `ERROR 1716` otherwise, measured with two
        curves that genuinely crossed on the positive side. Both are done
        exactly (`atan` per point, not dyna2rad's flat x57).
      * `/MAT/GAS/MASS` produced `GAMMA AT INITIAL TEMPERATURE = -3.61E-03`
        with **0 ERROR(S)** and TERMINATION WITH WARNING. The starter does not
        use the card's `GASC`: it uses 8.314 rescaled into the `/BEGIN` unit
        system (`hm_read_matgas.F:293`), so a gas stated in SI on a mm mesh
        gets an R three orders of magnitude too large and a NEGATIVE Cv. The
        converter now reproduces that arithmetic and warns, quoting the
        numbers — its `-0.0036102085` against the starter's
        `-3.6102084432184E-03`. (The constant is the solver's own
        `R_IGC = 8.314472`, `constant_mod.F:932`, not the textbook 8.314; the
        starter's `MOLECULAR WEIGHT = 2.8970286405876E-05` echo pins it.)

      Final state of the probe: **0 ERROR(S), TERMINATION WITH WARNING**, with
      the starter echoing 4 monitored volumes, `SURFACE ERROR(NE.0 FOR NON
      CLOSED SURF) = 0.0` and `INITIAL VOLUME = 1000.0` on each,
      `INITIAL PRESSURE = 0.151325` on the GAS bag (= P0 0.05 + PE 0.101325,
      the gauge-to-absolute fix), `AVENT:VENT HOLE AREA = 14.0` (= MU 0.7 x
      AREA 20) under `ISENTHALPIC VENTING MODEL`, and the `/XREF` reference
      state on the fabric part. The two remaining warnings are `WARNING 1084`
      (LAW1 with NIP>1 on the probe's non-fabric boxes, pre-existing) and
      `WARNING 863` ("ELEMENT(S) IS(ARE) INITIALLY IN TENSION", which is what a
      reference geometry is for).

      A SECOND probe covers the per-element reference geometry and the mixed
      quad+triangle surface: five quads and two triangles on one fabric bag,
      with `/EREF/SHELL/1` and `/EREF/SH3N/1` over ghost nodes at 0.9 scale.
      **0 ERROR(S)**, the starter echoing `REFERENCE STATE (EREF)` for both
      blocks, `SURFACE ERROR = 0.0` and `INITIAL VOLUME = 1000.0` on a surface
      the converter built as `/SURF/GRSHEL` + `/SURF/GRSH3N` under a
      `/SURF/SURF`.

  19. **Review round — five defects that changed physics, each measured on the
      real solver rather than argued.**

      * **`NU12 ← PRBA` was wrong by the factor EA/EB.** LS-DYNA's `PRBA` is
        the **minor** ratio ν_ba (`mat_034.cfg:32`) while Radioss's `NU12` is
        the one paired with E11 (`hm_read_mat19.F:122`, `N21 = N12*E22/E11`;
        the CFG field the reader pulls is literally `MAT_PRAB`), so
        reciprocity gives `NU12 = PRBA·EA/EB` — the #90 lesson
        `composites.py::_emit_mat_law93` already records for
        *MAT_ORTHOTROPIC_ELASTIC, unapplied here. MEASURED: `EA 1000 /
        EB 13789.5 / PRBA 0.3` gave `nu21 = 4.137`, `DETC = −0.241` and
        `ERROR ID : 307 DETERMINANT OF MATERIAL MATRIX IS LESS THAN 0` +
        ERROR TERMINATION; the reciprocity value 0.021755 runs to NORMAL
        TERMINATION. The `DETC ≤ 0` screen `_emit_mat_law93` carries is added
        alongside it. The old test could not see the defect because its
        fixture had EB == EA, so the factor was 1.
      * **`TSRFAC = 0` wrote `ZEROSTRESS = 1.0`, which CANCELS the reference
        geometry it is meant to arm.** `sigeps19c.F:131-167` (and
        `sigeps58c.F:1690-1729`, identical) gate the whole reference-state
        block on `IF (ZEROSTRESS /= ZERO)`: a non-zero value memorises the
        /XREF pre-stress at cycle 1, SUBTRACTS it and relaxes it away. So
        "no tensile stress reduction" (LS-DYNA's default) is **0**, and the
        old map was non-monotone — 0 → 1.0, 0.5 → 0.5, 1.0 → 1.0. MEASURED on
        a 0.5 %-pre-stretched LAW19 membrane loaded to ε=+0.01 and unloaded
        (internal energy, mJ; analytic in brackets): peak **74.41** at ZS=1 vs
        **134.04** at ZS=0 [135.0]; end **−28.98** at ZS=1 vs **+15.78** at
        ZS=0 [15.0]. ZS=1 halved the loading-path work and drove the internal
        energy NEGATIVE on unload — energy returned that was never stored.
        Both variants are starter-clean, so nothing else says so. The
        knock-on is named: both laws read the reference-state BIRTH sensor
        only from inside that block, so an RGBRTH delay is inert while
        ZEROSTRESS is 0, and Radioss has no slot that holds both.
      * **A blank `S1`/`S2` on `/MAT/LAW58` is a DERIVATION REQUEST, not "no
        crimp".** `hm_read_mat58.F:210-211` does `IF (EMBC == ZERO) EMBC =
        EM01`, inventing a **10 %** yarn crimp *MAT_FABRIC has no concept of —
        starter echo `NOMINAL WARP STRETCH = 0.1000000000000`. That crimp
        rescales both axes of every tabulated curve: the engine evaluates
        FCT_ID1 at `DCC = sqrt(LC²+HC0²) − DC0` and projects the fibre force
        through `LC/DC` (`sigeps58c.F:474-477,507-509`). MEASURED end-to-end
        on a FORM=14 uniaxial deck whose LCA has slope 400: **σ_xx = 2.501 MPa
        at ε = 0.00971, i.e. 64 % of the curve's own 3.884**. Writing
        `S1 = S2 = 1e-4` (dyna2rad's value, `convertmats.cxx:2156-2157`) gives
        **σ_xx = 3.89459 at ε = 0.009733 — 400.1 apparent modulus, +0.04 %
        against the curve**, hand-derivable from the crimp geometry to 0.05 %,
        and the EA/EB anisotropy ratio moves from 3.25× to **3.971×**
        (target 4.0). This is the "LAW58 ordinate mapping not validated" gap
        closed, not just a slot filled.
      * **A blank loading curve beside a stated unloading one silently
        dropped the whole hysteresis model.** `LCAB = 0` is legal — Vol II R16
        card 7, "LCAB … If zero, GAB is used" — but LAW58 makes all three
        loading functions mandatory as soon as one unloading function is set
        (`hm_read_mat58.F:176-195`, ERROR 1578/1579/1580), so the FCT_ID4/5/6
        card was withheld with no warning of any kind, and the /FUNCT already
        built for LCUAB was left in the deck referenced by nothing. The blank
        slot is now SYNTHESIZED from the analytic constant the engine itself
        would have used — `τ(Φ) = GAB·tan Φ` in degrees for shear
        (`sigeps58c.F:540`, which is also LS-DYNA's own `τ = GAB·γ`), the
        linear `f(x) = E·x` for warp/weft — but **only where the slot's own
        unloading twin is also blank**, because the reader then sets
        `IFUNC(n+3) = IFUNC(n)` and `law58_upd.F:297,318,344` takes the
        `FUNC == FUND` arm, which never calls the intersection search whose
        failure is ERROR 1716. Where it cannot be synthesized the drop is
        named by curve id.
      * **The `/MONVOL` id allocator's fallback did not re-check the ids the
        deck states.** `used_monvol_ids` was consulted only for the LS-DYNA
        `_ID` value, so a bag carrying an explicit `*AIRBAG_..._ID` at or
        above the auto-id base (90001) could be handed the same id a later
        un-ID'd bag drew — two `/MONVOL`s under one number, starter ERROR 79,
        the whole deck refused. `state.next_monvol_id()` joins the five
        existing `next_*_id` guards.

  20. **Two `/TH/MONV` channels were structurally INERT and the column order
      did not match the card (#118/#122 class).** `volpvg.F` does write
      `FSAV(1) = AMTOT` and `FSAV(5) = TEMPERATURE`, but AMTOT comes from
      `RVOLU(20) = MI`, which `hm_read_monvol_type3.F:300-315` only derives
      when `I_equi > 0`, and TEMPERATURE is assigned only inside
      `IF (IEQUI > 0)` — and `_emit_monvol_gas` hard-writes `I_equi = 0` and
      `Mini = 0`. MEASURED over 505 samples / 675 cycles of the adiabatic box:
      MASS and T both min = max = 0 while VOL/P/A/GAMA carry real data. On
      AIRBAG1 the same applies to `DTBAG`: `airbagb1.F:655-679` fills FSAV
      1-12 and 15-18 and never 13, which belongs to the FVMBAG routines
      (`fvbag1.F:1808,1832`). All three are dropped. Separately, the starter
      SORTS the requested names into its own `VARMV` table order
      (`hm_read_thgrou.F:1181-1186`) and the T01 columns come back in THAT
      order — a group written `… GAMA MASS-IN … DTBAG AO UO AC UC` came back
      with AO/UO/AC/UC in columns 6-9, mis-labelling 9 of 17 channels for
      anyone indexing `th_to_csv` positionally. The names are now emitted
      pre-sorted, verified column by column against a real T01
      (`AO = 70.0 = Avent` in column 6, `ENER-INT = 2.498258E+05 = U₀` in
      column 15). And the AIRBAG1 group now splits by VENT state instead of
      dropping AO/UO/AC/UC for every vented bag whenever one sealed bag sits
      beside it.

  21. **The legacy `*AIRBAG_<MODEL>_1` spelling was silently skipped, and it
      is the majority spelling in the corpus.** `dispatch()` is an exact dict
      lookup, so `*AIRBAG_SIMPLE_PRESSURE_VOLUME_1` and
      `*AIRBAG_SIMPLE_AIRBAG_MODEL_1` landed in `skipped_keywords` with NO
      warning — the very hazard the registration block's own comment names.
      MEASURED over the r14 `dynaexamples` corpus: **16 of the 28** `*AIRBAG_*`
      occurrences use it (12 + 4), and three of the six unique airbag-carrying
      decks — `airfilled.sphere.k` and both `tire-compression.k` — lost their
      only pressure source while the run terminated normally. The card stack
      is the base model's verbatim (the corpus decks carry the base model's own
      field-name comments above each card), so the suffix is stripped by
      `_airbag_base_keyword` and every airbag spelling is registered with and
      without it, in HANDLERS and in `_OFFSET_SPECS` alike.

  22. **Four smaller fidelity fixes.** (a) The `_ID` card is
      `ABID(I10) HEADING(A70)` and was read by whitespace split, so a real
      deck's `        42Driver airbag` parsed ABID as 0 and auto-renumbered the
      bag; it now goes through the repo's column-first `_id_heading_card`.
      (b) A zero MU beside an AREA curve (or a zero AREA beside a MU curve) was
      promoted to `Avent = 1.0`, venting at full curve area a bag LS-DYNA
      SEALS — `mu·A = 0` is now no vent, named. (c) `PE = 0` is warned,
      because `hm_read_monvol_type7.F:417-418` reads a blank Pext as a request
      for ONE ATMOSPHERE and `:421`/`:536` then derive `PINI` and the initial
      gas mass from it, with 0 ERROR(S) either way. (d) `_off_mat_fabric` read
      card 3 with the bare 10-char slicer instead of the module's
      free-format-aware `_fields` — on a comma-separated *MAT_FABRIC inside an
      *INCLUDE_TRANSFORM, FORM came back 0 and the six card-7 curve ids were
      left un-offset while the MID on the same block and the *DEFINE_CURVEs in
      the same include both moved (#119). It also now reads the FORM set from
      `state.FABRIC_CURVE_FORMS` rather than a second hardcoded copy (#116).

  **Corpus sweep**, `master 346af1d` vs this branch, over **827 decks** (the
  repo tree, `Ryan_Lee_Examples`, `E:/openradioss_run`, `E:/foxcore_data` and
  the 351-deck `dynaexamples_r14_ton-mm-s` tree, excluding the handful above
  8 MB, which are converted and inspected individually): **0 exceptions on
  either side**, and **819 / 827 `_0000.rad` byte-identical**. The eight that
  changed are *exactly* the eight decks carrying an `*AIRBAG_*` or a
  `*MAT_FABRIC` — `airfilled.sphere.k`, both `airbag.deploy.k`, `volume.k`,
  both `tire-compression.k`, and the Toyota Yaris and Camry production models.
  Skip lists move on the same eight and nowhere else; the one `_0001.rad` that
  differs is `volume.k`, whose `/TFILE` now honours its `*DATABASE_ABSTAT`.

  Warnings 18059 → 18383 (**+324** over 288 decks), and the split is the whole
  story: **280** of those decks gain nothing but the new part → material
  existence scan, which is a PRE-EXISTING defect finally named — every one
  spot-checked is a `/PART` pointing at a material the converter does not
  write, which the starter refuses. The other 8 are the airbag decks. Nothing
  is *lost*: the handful of warnings that differ textually on those 8 decks are
  auto-ids inside an existing message, shifted because a monitored volume draws
  from the same `next_id()` stream.

  **Re-validated on the real solver after the review round**, because three
  of the fixes change conversion behaviour on a solver-validated path. 26
  purpose-built decks re-converted and re-run through
  `starter_win64.exe` + `engine_win64.exe` (Mg/mm/s, np=1, nt=4): **every one
  NORMAL TERMINATION, 0 ERROR(S)**, the only warning being the `WARNING 863`
  ("ELEMENT(S) IS(ARE) INITIALLY IN TENSION") that a reference geometry is for.
  What the re-run pins:

  * **LAW58 crimp.** Starter echo `NOMINAL WARP STRETCH = 1.0000000000000E-04`
    (was 0.1), and the FORM=14 uniaxial deck whose `LCA` has slope 400 now
    measures **σ_xx = 3.89459 MPa at ε = 0.009733** against the curve's own
    3.8932 — **+0.04 %**, where the blank slot gave 64 %. Hand-derivable from
    the crimp geometry (`DC0 = 1.0001`, `HC0 = 0.0141425`,
    `DCC = 0.0097323`, `LC/DC = 0.99990` → 3.8925) to 0.05 %. The slot-swap
    twin measures 0.98069 at ε = 0.0097248, so the EA/EB ratio is **3.971×**
    against a target of 4.0 (it was 3.25×).
  * **ZEROSTRESS.** The `/XREF` membrane's internal energy now reads
    14.90 / **134.04** / **+15.78** mJ against an analytic 15.0 / 135.0 / 15.0
    at t=0 / peak / end — the reference-geometry work is CONSUMED and the
    unload leg no longer ends negative. The five no-`/XREF` LAW19 decks are
    unchanged to seven digits (`IE_end` 59.3666 / 14.9522 / 60.1932 /
    0.749167, `IE(EA)/IE(EB) = 3.97042`, CSE tension-safe ratio 1.000000),
    which is the check that ZEROSTRESS really is inert without a reference
    state.
  * **`/TH/MONV` column order**, verified against a real T01 rather than the
    card: the vented AIRBAG1 group comes back `MASS VOL P A T AO UO AC UC CP
    CV GAMA MASS-IN ENTHA-IN ENER-INT WORK` — `AO = 70.0 = Avent` in column 6,
    `ENER-INT = 2.498258E+05 = U₀` in column 15 — i.e. the card now describes
    the file. `DTBAG` is gone (16 channels, not 17) and the GAS group is down
    to its four live ones.
  * **Nothing else moved.** The adiabatic law still tracks
    `P = P₀(V₀/V)^1.4` to +0.00001 % (0.529171 measured vs 0.529171 predicted
    at V₀/V = 1.5); the sealed AIRBAG1 still tracks the pinned
    `P = 0.1 + 38.58 t` to 1e-5 % at four times; the deformable mini-bag
    reproduces its whole balance unchanged (V +11.442 %, P 0.1 → 0.1711,
    T 295 → 420.3, IE 2514.61, KE 78.14, EXTW 2649.19, bag WORK 2649.57,
    contact energy 0, added mass 0).

  **Review-round sweep**, `master 346af1d` vs the final branch, over a
  **367-deck** roster (the repo tree, `data/`, the 356-deck
  `dynaexamples_r14_ton-mm-s` corpus and the raw r14 `*AIRBAG_*`/`*MAT_FABRIC`
  carriers that hold the legacy `_1` spellings): **0 exceptions on either
  side**, **354 / 367 `_0000.rad` byte-identical**, and every one of the 13
  movers carries an `*AIRBAG_*` — **0 non-carrier movers**. Two `_0001.rad`
  differ, both copies of `volume.k` and both for the `*DATABASE_ABSTAT`
  `/TFILE` term. Skip lists move on exactly those 13 and nowhere else, and the
  keywords that leave them include `AIRBAG_SIMPLE_PRESSURE_VOLUME_1` on
  `airfilled.sphere.k` and `AIRBAG_SIMPLE_AIRBAG_MODEL_1` on
  `tire-compression.k` — the legacy-suffix fix landing on the corpus.
  Warnings 20343 → 20439 (+96) over 38 decks; the 25 decks whose warning count
  moves with **byte-identical** output each gain exactly +1, and it is the same
  pre-existing part → material existence scan documented above.

  Tests: `tests/test_airbag_monvol.py`, 150 tests + 184 subtests, every card
  assertion by COLUMN and every hand-computed value derived in the docstring
  (the SPV `Fscale = BETA·CN`, the `Cpa = A/MW` molar division, the
  `Pini = P0 + PE` gauge conversion, the `|SST|/2·SFST` contact gap, the exact
  1000 mm³ of the reference box, the `R_work = 8314.472` unit rescale and the
  `Cv = −286025.71` it produces on an SI gas card in a mm deck). The four
  mutations that used to survive the whole suite — dropping the `FAC_T²` from
  the gas-constant rescale, flipping the sign of `Cv = Cp − R/MW`, changing
  `_R_IGC_SI`, and stubbing `_warn_gas_gamma` out entirely — are each caught
  now, as are `_off_mat_fabric`'s free-format card-3 read and its FVOPT<0 card
  shift. Suite 3345/2/1055 → **3495/2/1239**.

- **The output / instrumentation parity batch:
  `*DATABASE_HISTORY_BEAM[_SET]` → `/TH/BEAM` (+ `/TH/SPRING`),
  `*DATABASE_HISTORY_DISCRETE[_SET]` → `/TH/SPRING`, the `_SET` and `_LOCAL`
  spellings of the whole `*DATABASE_HISTORY_*` family,
  `*DATABASE_NODAL_FORCE_GROUP[_TITLE]` → `/TH/NODE`, `*DATABASE_RBDOUT` →
  `/TH/RBODY`, `*DATABASE_BNDOUT` → `/TH/NODE`, and `*CONTROL_PARALLEL` →
  engine `/PARITH`.** Eighteen keyword spellings that a deck writes to say
  *what to record*, and every one of them was silently discarded. Measured on master
  over 975 corpus decks: `*DATABASE_BNDOUT` in **119** decks,
  `*DATABASE_RBDOUT` in **36** (an explicit `handle_skip` row, while
  `handlers.py:1568` already told users the card "maps to `/TH/RBODY`"),
  `*DATABASE_NODAL_FORCE_GROUP` in **30**, `*DATABASE_HISTORY_BEAM` in **22**,
  `*DATABASE_HISTORY_NODE_SET` in **21**, `*DATABASE_TPRINT` in **18**,
  `*DATABASE_NODFOR` in **28**, `*DATABASE_HISTORY_SHELL_SET` in **7**,
  `_SOLID_SET` in **4**, `*CONTROL_PARALLEL` in **3**, `_BEAM_SET` and
  `_NODE_SET_LOCAL` in one each — all in `skipped_keywords`, none of them
  warned about. A lost instrumentation card does not change the physics, but it
  does mean the channel the engineer asked for is simply absent from the T01
  with no diagnostic anywhere.

  1. **`*DATABASE_HISTORY_BEAM` resolves PER ELEMENT, because k2rad's beams do
     not all become `/BEAM`.** An `*ELEMENT_BEAM` on a `*MAT_SPOTWELD` part is
     a `/PROP/TYPE13` `/SPRING` and one on a `*SECTION_BEAM` `ELFORM=6` part is
     a `/PROP/TYPE8|13` `/SPRING`, so one card can produce two groups. That is
     also dyna2rad's own rule — `FindRadElement` re-initialises the keyword
     INSIDE the id loop and walks `/BEAM` → `/SPRING` → `/TRUSS`
     (`converttimehistory.cxx:246`, `convertutils.cxx:298-312`) — and it
     matters here because the two families are screened against DIFFERENT
     registries. k2rad emits no `/TRUSS`, so the third link of the chain has no
     target and is not implemented.

  2. **Every new `/TH` type is screened against what was actually emitted (the
     #106 rule), which needed four new registries filled AT the write line.**
     A `/TH` group naming an entity the deck does not define is not a lost
     channel: it is `ERROR 69` (`TH ELEMENT SELECTION ID=n DOES NOT EXIST`,
     `hm_read_thgrne.F:187-193`) for the element types and `ERROR 78`
     (`UNDEFINED NODE NUMBER ... IN TH GROUP`, via `USR2SYS`) for nodes, and
     the whole deck is refused. `state.spring_elem_ids` covers **all seven**
     `/SPRING` producers — `*ELEMENT_DISCRETE`, `*MAT_SPOTWELD` beams,
     `ELFORM=6` discrete beams, `*ELEMENT_PLOTEL`, `--ground-springs`,
     `*CONSTRAINED_SPOTWELD` ties and `*CONSTRAINED_JOINT_*` — of which the
     last three mint their ids with `next_id()` and were recorded NOWHERE
     before this batch; `state.beam_elem_ids` covers `/BEAM`;
     `state.rbody_ids` covers **all four** `/RBODY` producers;
     `state.imp_motion_nodes` covers the emitted `/IMP*` node scope. None is
     derivable from the parsed containers: `state.beam_elems` includes the
     beams that became springs and the beams whose PID has no `*PART` record
     (never emitted at all), and `rbody_info` misses the implicit probe body
     entirely, drops one record on a CNRB/part id collision, and aliases
     several keys onto one main node after a `*CONSTRAINED_RIGID_BODIES` merge.
     Fifteen registration sites; each of the thirteen distinct arms has a
     test that FAILS when the line is removed (verified by mutation), and the
     two remaining ones are the lock-card duplicates of the imposed-motion
     register, which add no node their base card did not.

  3. **The `_LOCAL` route is a real per-entity skew binding, not a warn-drop.**
     `/TH/NODE` is the one group in this family whose id card has a `skew_ID`
     column (`th_node.cfg` `CARD("%10d%10d%-80s")`, cols 11-20) — which lines
     up exactly with LS-DYNA, where `_LOCAL` exists only for `NODE` and
     `NODE_SET` (a full-text scan of the R16 and R17 manuals finds no
     `BEAM_LOCAL`, `DISCRETE_LOCAL` or `SEATBELT_LOCAL`). The column is fetched
     with the same index as the id INSIDE the id loop
     (`hm_read_thgrne.F:167-171`), and it accepts a `/SKEW` id **or** a
     `/FRAME` id: `hm_read_thgrou.F:2560-2588` scans the skew table and then
     falls through to the frame table, raising `ERROR 434` only when neither
     matches, and the starter echoes the column as `SKEW(OR FRAME)`. Verified
     live at `/BEGIN 2022` and at the newest `/BEGIN 2612` with a `/SKEW/FIX`,
     a `/FRAME/MOV` and a `0` in one group — 0 errors, identical parse at both.
     `REF` picks which entity a CID becomes: **0** → the CID's `/SKEW/FIX`;
     **1** → the CID as it stands (the projection onto a possibly co-rotating
     system); **2** → a synthesized `/FRAME/MOV` from the CID's `N1/N2/N3` +
     `DIR`, because REF=2 asks for the motion RELATIVE to the system attached
     to node N1 and only a `/FRAME` subtracts the frame's own motion. One frame
     per CID, not per node.

     Writing a skew into cols 11-20 of a `/TH/BEAM` or `/TH/SPRING` id card
     instead is `WARNING 100214` with the value SILENTLY dropped (measured), so
     the emitter refuses to put one there at all.

  4. **`*DATABASE_TPRINT` emits nothing, deliberately, and this is the one
     place the batch departs from dyna2rad on purpose rather than to fix a
     defect.** dyna2rad answers the card with `/ANIM/NODA TEMP` +
     `/ANIM/ELEM TEMP` and appends a `TEMP` variable to every existing
     `/TH/NODE` and `/TH/BRIC` group (`dyna2rad.cxx:497-551`), with no check
     that a thermal solution was ever requested. k2rad converts **no** thermal
     keyword at all — no `*CONTROL_THERMAL_*`, `*MAT_THERMAL_*`,
     `*INITIAL_TEMPERATURE` or `*BOUNDARY_TEMPERATURE`, and it emits no
     `/HEAT/MAT` — so a converted deck cannot run a thermal solve and the
     channel cannot carry data. What it WOULD carry was measured on a
     576-brick deck with the A-file decoded by `anim_to_vtk_win64.exe`: with
     `/MAT/ELAST` both `Nodal_Temperature` and `3DELEM_Temperature` come out
     **all zero**; with `/MAT/PLAS_JOHNS`, which allocates `GBUF%TEMP` and
     initialises it to 300 but never integrates it, both come out a **constant
     300** while the `Von_Mises` control field has 576 distinct values. The
     scalar is *always* created in the A-file (`genani.F:1905`, `:4547`), never
     omitted, so the result is a flat fringe that reads as data. The starter
     itself says so on the TH side and nowhere else — `WARNING 1087 OUTPUT TEMP
     WHILE TEMPERATURE IS NOT COMPUTED (NO HEAT/MAT)`,
     `hm_read_thgrne.F:228-236` — and there is **no** equivalent warning on the
     ANIM side. An honest `recognized_not_emitted` note that says all of this
     is worth more than three channels of zeros. Its `dt` also stays out of the
     `/TFILE` minimum, on the documented membership rule: a card with no `/TH`
     consumer would only thicken the T01 for channels that are not in it.

  5. **`*DATABASE_HISTORY_SEATBELT` emits nothing either, for a different
     reason: BOTH of dyna2rad's branches are unreachable here.** It probes the
     FIRST listed element's `*ELEMENT_SEATBELT` → PID → SECID and routes the
     whole list to `/TH/SPRING` (a `*SECTION_SEATBELT` 1D belt) or `/TH/SHEL`
     (a `*SECTION_SHELL` 2D belt) on that single answer
     (`converttimehistory.cxx:303-341`). k2rad converts neither
     `*ELEMENT_SEATBELT` nor `*SECTION_SEATBELT`, so no `/SPRING` and no
     `/SHELL` in the output deck carries those ids and naming them is `ERROR
     69` — a deck that "converts" and then refuses to run, the worst of the
     three outcomes. The gap is named in `recognized_not_emitted` and points at
     the later seatbelt / retractor / slipring batch, after which the 2D-belt
     route becomes correct (and, unlike dyna2rad's, should be decided per
     element: a card mixing 1D and shell belts is misrouted wholesale by the
     first-element rule).

  6. **`*CONTROL_PARALLEL` is honoured, and the card is emitted only when the
     deck carries it.** `CONST=1` requires "that all contributions to global
     vectors be summed in a precise order independently of the number of
     processors used" (Vol I R16 p.12-449), which is exactly `/PARITH/ON`: the
     engine writes each contribution into a fixed per-node slot of the skyline
     `FSKY` array and gathers it in a deterministic walk
     (`engine/source/assembly/asspar4.F`), so the sum order is invariant in
     both the thread count and the MPI domain count. **Measured** on a
     576-brick / 845-node LAW2 model, T01 decoded to full precision with
     `th_to_csv_win64.exe`: `/PARITH/ON` is **bitwise identical** between
     `nt=1` and `nt=4` (200 rows x 41 cols); `/PARITH/OFF` differs (row 183 KE
     `3.495637e-02` vs `3.495636e-02`). That diff IS the consumption check.
     Cost on that model was 1.65x at nt=4 (it is far too small to amortize the
     extra `FSKY` traffic; LS-DYNA quotes "at least 15 percent").

     dyna2rad creates `/PARITH` **unconditionally** and defaults it to `OFF`
     (`convertcards.cxx:973-974`) before it has even looked for the LS-DYNA
     card. That is not neutral: OpenRadioss's own default is ON
     (`starter/source/starter/contrl.F:400` sets `IPARI0 = 1` before
     `HM_READ_ANALY`), so a dyna2rad deck silently flips the solver default on
     every model it converts, parallelism card or not. k2rad does not change a
     solver default from a card the deck does not carry — so a deck with no
     `*CONTROL_PARALLEL` gets no `/PARITH` and its engine file is unchanged —
     and when the card IS there both of its answers are honoured, `OFF`
     included. `NCPU`, `NUMRHS` and `PARA` have no counterpart (NCPU is the
     runtime `-nt` argument, not a deck card, and LS-DYNA itself disabled the
     field in 971 R5) and are named as dropped. `/ANALY` `Iparith` is left at 0,
     so nothing on the starter side vetoes `ON`; `/IMPL` and `/EIG` do veto it
     at run time (`lectur.F:681`, `contrl.F:926`), which the warning says.

  7. **`*DATABASE_RBDOUT` lists every emitted `/RBODY`, with two card rules
     that are unique to `/TH/RBODY`.** It is a presence-only trigger with no id
     list, answered by collecting every converted rigid body — the same shape
     `/TH/RWALL`, `/TH/SECTIO` and `/TH/INTER` use
     (`convertrigids.cxx:766-772`). The id list is a **ten-per-line** cell list
     with no name and no skew column (`th_rbody.cfg`
     `FREE_CELL_LIST(idsmax,"%10d",ids,100)`), not the one-id-per-line layout
     every element group uses; and a leading id of `0` makes the reader loop
     over the WHOLE `/RBODY` table instead of the requested list
     (`hm_read_thgrki_rbody.F:123-125`), so a placeholder zero is never
     written. A stale id here is only `WARNING 257 NONEXISTENT RBODY` rather
     than the hard `ERROR 69` the element groups give, but the list is still
     built from the emitted set so the group count is right.

     **The two halves of `DEF` read differently, and the warning says so.**
     `FX FY FZ MX MY MZ` are a time-ACCUMULATED force/moment impulse —
     `rgbodfp.F:261-266` does `FS(1)=FS(1)+AFM1*DT1*WEIGHT(M)` — so the force
     is `d(FX)/dt`, the same treatment `/TH/INTER` and `/TH/NODE REAC*` need.
     `RX RY RZ` integrate the angular VELOCITY (`rgbodv.F:91-93`,
     `FS(7)=FS(7)+VR(1,M)*DT2*WEIGHT(M)`) and therefore ARE the body's rotation
     angle, needing no differentiation. LS-DYNA's rbdout is a MOTION file, so
     only the rotation half of it is in this group; the translation half is a
     `*DATABASE_HISTORY_NODE` on the body's main node.

  8. **`*DATABASE_NODAL_FORCE_GROUP` is emitted with the change of meaning
     stated.** Seven variables, verbatim from dyna2rad
     (`DEF REACX REACY REACZ REACXX REACYY REACZZ`, `convertcards.cxx:1045`),
     `skew_ID = CID` on every expanded node. But LS-DYNA's nodfor is a
     **free-body cut** — the force the rest of the model exerts on the group,
     nonzero anywhere in the mesh — while the Radioss `REAC*` channel is the
     **kinematic constraint reaction** and is identically zero on a node
     carrying no `/BCS`, `/RBODY` or imposed motion. dyna2rad maps the two onto
     each other with no comment; the emitted warning names the difference and
     points at `*DATABASE_CROSS_SECTION_PLANE/_SET` → `/SECT` + `/TH/SECTIO`,
     which IS a free-body cut, on top of the usual impulse-vs-force
     derivation. The card's interval comes from `*DATABASE_NODFOR`, now parsed
     for that purpose ("the output interval must be specified using
     *DATABASE_NODFOR", p.16-121) and reported as interval-only when no group
     card is present.

  9. **Two live defects fixed on the way, both of which produced a deck the
     starter refuses.**

     * **The `_ID` card layout was mis-read, and the writer then emitted an
       EMPTY `/TH` group.** `CARD("%10d%-70s")` FUSES the id and the heading —
       `   5000390Left Rear Seat` is the literal layout in the Toyota Yaris
       deck — so the free split every spelling used read `5000390Left`,
       `to_int` returned 0, and EVERY requested channel was dropped. The writer
       then wrote `/TH/NODE/1` with a title, a variable line and no entity,
       which is starter `ERROR 1109` (`NO TH VARIABLE`). Measured on master:
       `set-yaris-detailed-v2j.key` and `set-camry-detailed-v5a.key` both
       convert to `db_histories: [('NODE', 0)]`. Both halves are fixed — the
       fixed-column read, and an empty-group guard on every family (it existed
       only on the SHELL and SPH branches).
     * **The `*INCLUDE_TRANSFORM` walk and the handler read different rows.**
       `_offset_block` starts its `data` walk at `_title_offset`, which is 1
       whenever the `_ID` option is present — but on this family `_ID` is a
       PER-ENTITY heading, not a card-level "id + title" header, so the
       offsetter skipped the deck's first requested entity while the handler
       read it. (Invisible only because the handler could not read an `_ID`
       card either.) The family now uses a callable spec that reuses the
       handler's own row walk, and the `_LOCAL_ID` heading card is claimed by
       RAW CONTIGUITY (#119) in BOTH walks: a blank heading is legal and drops
       out of the filtered row list, so "the next filtered row" would swallow
       the following entity card. `_rewrite_line` cannot touch an `_ID` card at
       all (`_split_card` sees the space inside the heading and field 0 becomes
       `5000390Left`), so it goes through `_rewrite_id_header`, which rewrites
       columns 1-10 and leaves the rest byte-identical. `REF` and `HFO` on a
       `_LOCAL` card are flags and are NOT offset.

  10. **The `_SET` twins of the whole family, and `*SET_DISCRETE`.** With one
      `_SET` expander in place, `_NODE_SET` (21 decks), `_SHELL_SET` (7) and
      `_SOLID_SET` (4) cost one dispatch row each and were completed with the
      batch rather than left as the only unrouted spellings of keywords that
      are otherwise handled. Per the cfgs each `_SET` accepts TWO id pools —
      its own element set or a `*SET_PART`, which expands to every element of
      that family in the named parts — so `*SET_DISCRETE[_LIST]` was added to
      give `_DISCRETE_SET` its element pool. A set id that resolves in neither
      pool is warned and dropped, never written through as an entity id:
      dyna2rad's `*SET_PART_LIST` branch keys on the literal string
      `"*SET_PART_LIST_TITLE"` (`converttimehistory.cxx:184`), so a plain
      `*SET_PART_LIST` falls through to the `else` and its PART ids are pushed
      as ELEMENT ids.

  11. **Three documented dyna2rad defects deviated from, each with the reason
      in a comment.** (a) The REF=0 frozen `/SKEW/FIX` id **is written back**
      into the TH entry; `converttimehistory.cxx:468-507` builds the same skew
      and never assigns it (unlike `:424` and `:461`), so its group silently
      keeps the co-rotating system and the new card is orphaned. (b) A
      `_SET_LOCAL` card applies **each set's own** CID and REF; dyna2rad
      compares the CID-column length against the EXPANDED entity count and, on
      the inevitable mismatch, broadcasts `DH_cid[0]` to every entity of every
      set while discarding REF entirely (`:382-391`) — on the only `_SET_LOCAL`
      deck in the corpus that would put the second intrusion set's nodes in the
      first one's coordinate system. (c) An unresolvable CID becomes `skew_ID
      0` (global, warned with the quantitative consequence) instead of the raw
      CID written through (`:400`), which dangles into `ERROR 434` and refuses
      the deck.

  12. **`_make_starter_th` keeps its own `1..N` group counter.** The two id
      streams cannot collide — `_auto_id` starts at 90001, four orders of
      magnitude above anything that counter reaches — and moving them would
      rewrite the starter of every corpus deck carrying a `*DATABASE_HISTORY_*`
      card for no behavioural gain. The collision that cost PR #83 an `ERROR
      79` was a hard-coded `/TH/INTER/1`, not this counter, and the three new
      sections all draw from `state.next_id()`;
      `assembly._warn_duplicate_th_group_ids` scans the emitted deck for the
      next one.

  13. **Validated on a live starter, not only against the sources.** A probe
      deck exercising every route at once — `/TH/BEAM` x2, `/TH/SPRING` x2,
      `/TH/BRIC`, three `/TH/NODE` (`_ID` with headings, `_LOCAL` with REF=0
      and REF=2, `_SET_LOCAL` with REF=1), the nodal force group, the BNDOUT
      group, `/TH/RBODY`, a `/SKEW/FIX`, a `/SKEW/MOV` and a synthesized
      `/FRAME/MOV` — was run through `starter_win64.exe`: **0 ERRORS**, one
      unrelated `WARNING 275` from the probe's own two-node CNRB. With
      `/IOFLAG` raised, the starter's own echo confirms every decision:

      ```
      TH GROUP:         1,TH_BEAM_1,  8 VAR,    2 BEAM      :
      OFF       F1        F2        F3        M1        M2        M3        IE
      BEAM        P_SPMD       NAME
             101         0
      TH GROUP:         5,TH_NODE_5,  6 VAR,    2 NODES     :
          NODE  SKEW(OR FRAME)     NAME
               1         0         front left corner
      TH GROUP:         6,TH_NODE_6,  6 VAR,    2 NODES     :
               2        70                          <- REF=0, the CID's /SKEW/FIX
               5     90006                          <- REF=2, the new /FRAME/MOV
      TH GROUP:     90007,left rail cut, 12 VAR,    4 NODES :
      DX DY DZ VX VY VZ REACX REACY REACZ REACXX REACYY REACZZ
      TH GROUP:     90009,TH_NODE_BNDOUT,  3 VAR,    2 NODES :
      TH GROUP:     90008,TH_RBODY_90008,  9 VAR    1RBODY  :
      FX        FY        FZ        MX        MY        MZ        RX RY RZ
      ```

      The `_ID` heading reaches the channel name, the skew column is literally
      labelled `SKEW(OR FRAME)` and resolves both an id from the skew table and
      one from the frame table, and the eleven group ids (1-8 from
      `_make_starter_th`'s counter, 90007-90009 from `next_id()`) coexist with
      no `ERROR 79`.

  14. **Corpus sweep.** 533 deduped decks — the 201-deck regression roster
      (`Ryan_Lee_Examples` in the repo and on `E:`, `ls-dyna_example`, the
      demo/tutorial decks and the five golden fixtures) plus the whole
      `dynaexamples_r14` ton-mm-s tree, where this batch's keywords actually
      live, plus the Toyota Yaris and Camry instrumentation includes and
      `zug_test3`, which carry spellings nothing else does. Converted on master
      and on the branch, comparing SHA-256 over **both** `_0000.rad` and
      `_0001.rad` plus the warning / skip / not-emitted sets:
      **340 byte-identical, 193 moved, 0 conversion errors either side.**

      **The smaller roster is not a smaller sample of this batch**: it holds
      every single occurrence of all twelve keywords the 974-deck corpus
      contains — the per-keyword mover counts below match the corpus-wide
      census exactly. What it leaves out is decks that carry none of them, and
      chiefly the repo's `implicit_hr-anlenkung` folder, whose two decks take
      ~80 s each to convert.

      Every mover is accounted for. 192 of the 193 have at least one batch
      keyword leaving `skipped_keywords` — `BNDOUT` on 119, `RBDOUT` on 36,
      `NODAL_FORCE_GROUP` on 30, `NODFOR` on 28, `HISTORY_BEAM` on 22,
      `HISTORY_NODE_SET` on 21, `TPRINT` on 18, `HISTORY_SHELL_SET` on 7,
      `HISTORY_SOLID_SET` on 4, `CONTROL_PARALLEL` on 3, `HISTORY_BEAM_SET`
      and `HISTORY_NODE_SET_LOCAL` on 1 each — and **no batch keyword is left
      in `skipped_keywords` on any deck in the roster**. The 193rd is
      `set-camry-detailed-v5a.key`, whose keyword
      (`*DATABASE_HISTORY_NODE_ID`) normalizes to an already-handled base and
      therefore never appeared in `skipped_keywords` at all; its entire diff is
      the nine id cards the `_ID` layout fix recovered, against a master
      `/TH/NODE/1` that had none:

      ```
      + 9000008         0Left Rear floor
      + 9000016         0Right Rear floor
      + 9000024         0Engine Top          ... (9 cards)
      ```

      **187 of the 340 unchanged decks carry a `*DATABASE_HISTORY_*` card** —
      the evidence that rewriting the shared card reader moved only the
      spellings it was meant to. There were **zero** log-only movers (a deck
      whose two output decks hash the same but whose warnings or notes changed),
      so nothing shifted a diagnostic without shifting a card.

  **Review round.** Eleven findings from the fidelity / code / solver reviews
  were confirmed against the source and fixed; two were rejected with reasons
  (below). The behaviour changes worth naming:

  * **The variable line is now PER FAMILY, not `DEF` everywhere.** dyna2rad
    starts `outVars` at `{"DEF"}` and pushes `STRAIN` on the SHELL and SOLID
    branches and `A`/`AR`/`VR` on the NODE branch
    (`converttimehistory.cxx:238-296`); k2rad emitted the bare `DEF` for all of
    them. On a node `DEF` is only six channels — `DX DY DZ VX VY VZ`
    (`hm_read_thgrou.F` `IVARNG` row 1) — so every `*DATABASE_HISTORY_NODE`
    silently dropped the accelerations and the rotational velocity and
    acceleration that LS-DYNA's own `nodout` carries, and every element group
    dropped the strain tensor. MEASURED on a shell + solid bending probe, the
    plain-`DEF` baseline against this, same run: `/TH/NODE` 6 → **15**
    channels, `/TH/SHEL` 11 → **19**, `/TH/BRIC` 11 → **17**, starter
    `0 ERROR(S)`, and every added channel carries real time-varying data. The
    decoded T01 is now **byte-identical** to the same deck with dyna2rad's var
    lists planted into the `.rad` by hand. The one structural zero is
    `VR*`/`AR*` on a node that belongs only to solids, where the dof genuinely
    does not exist — a true answer, unlike the un-computed zero that keeps
    `*DATABASE_TPRINT` out (above). Confirmed legal on `/TH/SH3N` and on a
    `/TH/BRIC` built from `/TETRA4` ids by live starter runs.

  * **`/TH/SHEL`, `/TH/SH3N` and `/TH/BRIC` ARE screened now** — the item this
    batch previously listed as out of scope. `state.shell_elem_ids`,
    `sh3n_elem_ids` and `solid_elem_ids` are filled at the six lines in
    `_make_parts_and_elements` that write an element row (the "written from ten
    different places" estimate was wrong; they are six, all in one function).
    An `*ELEMENT_SHELL` whose PID has no `*PART` record is parsed into
    `state.shell_elems` and warned about ("MESH LOSS") but never written, and
    both the plain and the new `_SET` spelling synthesized their id list from
    that parsed container: MEASURED on a two-shell deck, the starter answered
    `ERROR ID : 69 ... TH ELEMENT SELECTION ID=999 DOES NOT EXIST` **twice** and
    refused the deck. The SHEL/SH3N split now reads the two registries back
    instead of re-deciding the topology, so the group and the element block
    cannot drift. `/TETRA4`, `/TETRA10` and `/BRICK` share `solid_elem_ids`
    because they share one Radioss solid id pool (all three land in `IXS`) —
    confirmed live: a `/TH/BRIC` naming two `/TETRA4` ids gives `0 ERROR(S)` and
    records both. **Audited independently over 394 corpus decks** by parsing
    every emitted element block out of the `.rad` text and comparing it against
    the registry in both directions: **0 mismatches**, all six families.

  * **`*SET_DISCRETE` / `*SET_DISCRETE_LIST` get their `_OFFSET_SPECS` rows.**
    They had a handler and no offset map, which was inert until this batch gave
    the set a consumer — `*DATABASE_HISTORY_DISCRETE_SET` offsets its set-id
    reference through `_off_db_history("s")`, so under an `*INCLUDE_TRANSFORM`
    the two halves of one lookup moved apart. MEASURED on an IDSOFF=6000 /
    IDEOFF=2000 include: without the rows the history card resolved to nothing
    and the `/TH/SPRING` was dropped; with them the group lists the include's
    own spring `2201` rather than the parent deck's. The `#116` spelling test
    now iterates the whole generated set, not just the HISTORY half.

  * **`*DATABASE_HISTORY_SPH[_ID]` goes through `_th_screen`** like every other
    family, so screening a particle out takes its NAME with it. It used to
    reassign only the id column while `_th_id_lines` pairs `names[k]` with
    `ids[k]` positionally: a dangling id in the middle of the list slid every
    later heading onto the wrong particle (`501 "alpha"`, `9999 "ghost"`,
    `502 "beta"` on a deck holding only 501/502 emitted `502 "ghost particle"`).

  * **The `_LOCAL_ID` walk claims its heading BEFORE the non-positive-id
    guard**, where `assembly._off_db_history(local=True)` claims it — the #119
    rule. A heading whose columns 1-10 happen to parse was otherwise read as an
    entity id: `id 0` followed by `"9000      Beam A"` made the handler invent
    entity 9000, swallow the REAL next entity card as that entity's heading,
    and lose BOTH channels the card asked for.

  * **A present `*DATABASE_RBDOUT` / `*DATABASE_BNDOUT` with a blank or zero DT
    now warns.** The reference trigger is presence alone
    (`convertrigids.cxx:767`, `dyna2rad.cxx:461`); k2rad also needs a positive
    interval, which is right — `DT=0` is "no output is printed" (Vol I R16
    p. 16-7) and a blank DT defers to an `LCDT` curve `/TFILE` cannot express —
    but doing it silently turned a mistyped DT into an empty T01 selection with
    no diagnostic. Two new `db_*_seen` flags separate "card absent" from "card
    present, no usable interval" so the warning fires only for the second.

  * **`/TFILE` counts a dt only when its card paces a channel that is in the
    T01.** `state.db_bndout_dt` / `db_rbdout_dt` / `db_nodfor_dt` are each gated
    on their own consumer, which is the same argument that keeps
    `*DATABASE_TPRINT` out and it has to apply here too or the rule is not a
    rule. It is reachable: 52 of the 118 `*DATABASE_BNDOUT` decks in the corpus
    carry no `*BOUNDARY_PRESCRIBED_MOTION`.

  * **`tools/th_to_csv.py` learns `/TH/RBODY`.** `ACCUMULATED_CHANNELS` had no
    row for the group this batch newly emits, so its `FX..MZ` columns got no
    differentiated sibling — while the RBDOUT warning tells the user the force
    is `d(FX)/dt` "the same treatment `/TH/INTER` and `/TH/NODE REAC*` need".
    Only the force/moment half is listed (`rgbodfp.F:261-266`); `RX/RY/RZ`
    integrate the angular VELOCITY (`rgbodv.F:91-93`) and ARE the rotation
    angle, so differentiating them would turn an angle back into a rate.

  * **The "an empty `/TH` group is starter `ERROR 1109`" claim was wrong and is
    corrected everywhere it appeared.** `hm_read_thgrne.F:123` raises 1109 only
    for `NVAR == 0` (no VARIABLE). A group with a title, a `DEF` line and zero
    id cards is ACCEPTED, runs to NORMAL TERMINATION and writes a T01 group
    holding zero entities — which is worse than a refusal, not milder: on the
    Yaris deck that was 94 channels lost in silence. The empty-group guard is
    right and stays; only its justification changes.

  * Cosmetic, in the same pass: the `*DATABASE_NODAL_FORCE_GROUP` section
    banner is emitted once instead of once per card; the variable cells are
    LEFT-justified, as every `/TH` cfg declares
    (`FREE_CELL_LIST(...,"%-10s",VAR,100)`) and as every hand-written var line
    in the writer already was; the `/RBODY` producer count says three Radioss
    emission sites (four LS-DYNA sources funnelling through the first) instead
    of "four producers", matching the `1 of 3` annotations at the sites; and
    the `*DATABASE_DEFORC`/`_DISBOUT` note no longer says k2rad does not
    convert `*DATABASE_HISTORY_DISCRETE`, which this batch does.

  **Rejected, with reasons.**

  * *"Register the `*RIGIDWALL_GEOMETRIC_*_MOTION` carrier nodes into the
    `*DATABASE_BNDOUT` scope, because dyna2rad does."* dyna2rad does, but only
    because it rebuilds the scope by re-walking the OUTPUT model's `/IMPVEL`
    cards (`dyna2rad.cxx:456-479`) and cannot tell a prescribed motion from a
    rigid-wall driver. LS-DYNA reports a wall reaction in `rwforc`, i.e.
    `*DATABASE_RWFORC` → `/TH/RWALL`, never in `bndout`; k2rad's carrier nodes
    are SYNTHESIZED (`loads.py:4980`), so they carry ids that appear in no
    LS-DYNA deck; and they are massless free nodes with no element, so their
    `REAC*` is identically zero — the same flat-channel-that-reads-as-data the
    `*DATABASE_TPRINT` decision refused. The exclusion is now argued in
    `_make_geometric_rwall_motion` and in `_make_starter_th_bndout`, and the
    warning text no longer claims the deck has "no converted /IMPDISP, /IMPVEL
    or /IMPACC" when it has one.

  * Two pre-existing defects found during solver validation are real and are
    **out of scope for an output-parity change**, because both move mass or
    energy on solver-validated paths: `*ELEMENT_MASS` on a
    `*CONSTRAINED_NODAL_RIGID_BODY` SECONDARY node is silently dropped
    (`writer/rbody.py:969` reads only the master node's added mass, while the
    `*MAT_RIGID` branch at `:559` sums over all of the part's nodes and
    `_make_added_masses` skips every rigid-body node); and OpenRadioss's
    default time-step factor 0.9 was observed to diverge on a plain converted
    elastic solid bar where 0.7 and below converge. Both need their own PR and
    their own validation.

  **Review-round validation.**

  * *Corpus, `origin/master` vs the branch over SHA-256 of both `.rad` files
    plus the warning / skipped / note sets:* **395 decks, 0 conversion errors
    on either side, 41 identical, 354 moved.** Every one of the 354 carries at
    least one batch keyword; **0 moved without one and 0 keyword-carrying deck
    failed to move**; **0 log-only movers**; **no keyword newly appears in
    `skipped_keywords` anywhere**; and none of the 41 unchanged decks carries a
    batch keyword. The mover count is up from 193 before the review round
    purely because of the variable-line fix: 334 of them carry a
    `*DATABASE_HISTORY_NODE`, 203 a `_SHELL`, 160 a `_SOLID`, and each of those
    groups now asks for its family's variables instead of the bare `DEF`.
  * *Is the starter delta exactly the `/TH` region?* Deleting every `/TH` block,
    its banner, the rules around it and the `#-- SKIPPED` notes leaves the two
    starters **identical**, including on the 1.49-million-line Yaris roof-crush
    deck.
  * *Engine:* exactly **3** of 395 engine decks differ. Two are the
    `*CONTROL_PARALLEL` decks (`+/PARITH/ON` on `2Dlag.k`, `+/PARITH/OFF` on
    `projectile.k`) and the third is `000_yaris_dynamic_roof_crush_01.k`, whose
    `/TFILE` drops 0.01 → 1e-4 because it really does emit a `TH_NODE_BNDOUT`
    group. The consumer gate was measured over all 140 decks carrying one of
    the three gated cards and changes `/TFILE` on exactly **one**:
    `000_yaris_stat_doorsag_fine_02.k`, which asks for `*DATABASE_BNDOUT` at
    1e-3, drives no node with a `*BOUNDARY_PRESCRIBED_MOTION`, and therefore
    keeps master's 0.01 instead of writing a 10x denser T01 for channels that
    do not exist.
  * *Registry audit, independent of the registries:* every emitted `/SHELL`,
    `/SH3N`, `/BRICK`, `/TETRA4`, `/TETRA10`, `/BEAM`, `/SPRING` and `/SPHCEL`
    row was parsed out of the `.rad` TEXT on **394 decks** and compared against
    `state.*_elem_ids` in both directions: **0 mismatches**. (The first run of
    that auditor cried wolf on `/SPRING` and `/SPHCEL` because it treated the
    `# sprg_ID  node_ID1` column header as the end of the block; the registries
    were right and the check was wrong.)
  * *Live solver:* a deck exercising every reviewed route at once — quad and
    tri shells, solids, a beam, a discrete spring, a rigid body, a prescribed
    motion, `_NODE`, `_NODE_LOCAL_ID` (with a zero-id row), `_SHELL_SET`,
    `_SOLID`, `_BEAM`, `_DISCRETE`, two nodal-force groups, RBDOUT, BNDOUT and
    `/PARITH/ON` — gives **0 ERROR(S)** and NORMAL TERMINATION at 4542 cycles.
    The prescribed node, driven at a constant 1000 mm/s stated before the run,
    reports `DZ(t) = 1000*t` to within **0.00001 %** and `VZ = 1000.0000`
    exactly at every sampled state. The deck that used to answer `ERROR 69`
    twice now gives 0 ERROR(S).
  * *Tests:* **3345 passed, 2 skipped, 1055 subtests** (master baseline
    measured in a worktree at `a6484f7`: 3202 / 2 / 922). `ruff check k2rad/
    tests/ tools/` clean. All **11** review-round fixes were mutation-checked
    one at a time — reverting each one produces a failing test.

- **The SPH batch: `*ELEMENT_SPH` (+ `_VOLUME`) → `/SPHCEL`, `*SECTION_SPH`
  (+ `_ELLIPSE` / `_TENSOR` / `_INTERACTION` / `_USER`) → `/PROP/SPH`
  (TYPE34), `*CONTROL_SPH` → `/SPHGLO`, and `*DATABASE_HISTORY_SPH[_SET]` →
  `/TH/SPHCEL`.** Before this batch the whole family landed in
  `skipped_keywords`, and for an element keyword that is not a soft failure.
  Measured on master for `Ryan_Lee_Examples/W11_SETUP_SPH_BirdStrike.k`:
  `SKIPPED: ['CONTROL_SPH', 'ELEMENT_SPH', 'SECTION_SPH']`, a bare `/PART/2` on
  a placeholder `/PROP/SHELL/2` and **0 of 18 795 particles emitted — 1.8199 kg,
  100 % of the projectile, with no `MESH LOSS:` warning**, because the orphan
  census can only report elements that were parsed and none were. Worse than an
  absent bird: those 18 795 nodes were still emitted, still carried
  `*INITIAL_VELOCITY_NODE`, and were still the secondary side of two converted
  eroding `/INTER/TYPE25` contacts — 18 795 massless free nodes flying into a
  contact that reported itself healthy. The same shape on all ten independent
  r14 SPH decks (1 000 / 18 759 / 19 848 / 683 394 … particles).

  1. **Mass is transferred exactly, on both of the two routes Radioss offers,
     and the ROUTE is chosen rather than defaulted.** A `/SPHCEL` row that
     carries its own `MASS` is exact per particle — and makes the solver DERIVE
     that particle's smoothing length as `(sqrt(2)*m/rho)^(1/3)` and IGNORE the
     property's `h` (`spinih.F:85-95`, `spinit3.F:139-153`). A row that leaves
     the column blank takes `Mp` from `/PROP/SPH`, which is exact too whenever
     the particles agree on one mass — and then the deck's own `h` survives. So
     k2rad states the mass ONCE on the property when the section's particles all
     carry the identical value and the deck gives a usable `h`, and per cell
     otherwise, reporting the smoothing-length ratio the second route costs in
     numbers. Verified through `starter_win64` on the converted r14 `foam.k`:
     `NUMSPH : NUMBER OF SMOOTH PARTICLES (SPH CELLS) . . . 1000`,
     `PARTICLES MASS = 2.2640880000000E-07`, and the per-part echo
     `PART : 101 … Mass 2.26408800E-04` — exactly 1000 × 2.264088e-07, to every
     printed digit, with **no `WARNING 138`**. Converted W11 and r14 `boot.k`
     (3 sections, 19 848 particles) both read back `0 ERROR(S) 0 WARNING(S)`.

     The `h` the deck asks for is `SPHINI`, else `CSLH × d_ref` with `d_ref` =
     "the maximum of the minimum distance between every particle" (Vol I R16
     *SECTION_SPH Remark 1), measured from the node cloud with a uniform-grid
     nearest-neighbour search (exact on a lattice; above 20 000 particles per
     part the queries are subsampled, which can only under-estimate a max of
     minima and is exact on any regular fill). Radioss's `sqrt(2)` is the FCC
     packing factor, so its derived support is systematically SMALLER than
     LS-DYNA's — **0.9354x on a simple-cubic fill, 0.8333x on close packing** —
     which is why the choice is worth making. Numerically confirmed against the
     starter: with `m = 0.002`, `rho = 1000` the ratio of two runs' time steps
     (3.5700719306875E-06 / 3.1050391479609E-06 = 1.149769) matches the h ratio
     0.0141421 / 0.0123 exactly, ruling out the `(m/2rho)^(1/3)` reading some
     renderings of the Altair help card show.

  2. **`Mp` is always written positive.** dyna2rad never sets the field, so
     `hm_read_prop34.F:235-239` raises `WARNING 138` on EVERY deck it converts
     and forces `MP = 1` **in the deck's mass unit**. Harmless while the cells
     carry mass; a fabricated whole mass unit per particle when they do not —
     measured, four blank-mass particles gave `TOTAL MASS = 4.000000000000`.
     For the same reason a zero-mass cell is written `Flag = 0` and never
     `Flag = 1`: an explicit `Flag = 1` with a blank MASS keeps `TYPE = 1` and
     `spinit3.F:142` computes `VOL = 0/rho` — measured
     `TOTAL MASS = 0.000000000000` **with no diagnostic at all**.

  3. **Three LS-DYNA conventions neither dyna2rad nor OpenRadioss's own native
     `.k` reader implements**, each measured through `starter_win64`:
     `MASS < 0` is a VOLUME ("the absolute value will be used as volume … SPH
     element mass is calculated by |MASS| x rho") → `/SPHCEL` `Flag = 2`; passed
     through signed, the starter discards it and the `Mp = 1` fallback takes
     over — **8.0 kg where the deck states 0.016 kg**. The `_VOLUME` suffix means
     the same thing with a positive number — **wrong by exactly rho
     (1.6E-05 instead of 1.6E-02)** otherwise. And `NEND > 0` GENERATES the cards
     from `NID` to `NEND` — **`NUMSPH = 1`** instead of a whole cloud otherwise;
     generated ids with no `*NODE` are dropped with their own count, since a
     `/SPHCEL` id with no node is `ERROR 78`.

  4. **`h_1D = 3` and the `hmin`/`hmax`/`hcst` cells are NEVER emitted**, and
     the LS-DYNA card defaults are applied by the PARSER. Those three cells live
     on a `radioss2026`-only third card that a `/BEGIN 2022` reader discards
     SILENTLY — measured, `hmin=0.37 hmax=3.77 hcst=1.77` echoed back as the
     hard-coded `0.2 / 2.0 / 1.2`, `0 ERROR(S)`, only advisory
     `WARNING 100213` — while `h_1D = 3` on card 1 IS accepted, i.e. the bounded
     dilatation algorithm running with bounds nobody chose. dyna2rad emits
     exactly that combination on its `CSLH <= 0` branch, and targets the
     attribute `"hcst"`, which is not an attribute of the property at all (the
     real name is `h_scal`), so the value is discarded even at 2026. That branch
     is also the COMMON one on its side: the CFG declares
     `DEFAULTS(COMMON){ LSD_CSLH = 1.2; LSD_HMIN = 0.2; LSD_HMAX = 2.0;
     LSD_TDEATH = 1.0e20; }` and the SDI read path does NOT apply them, so a
     blank `CSLH` reaches `p_ConvertSectionSph` as 0 and a deck that left the
     cell empty to take the manual's 1.2 is converted to a CONSTANT smoothing
     length with `SPHINI` discarded (probe decks h and i:
     `CONSTANT SMOOTHING LENGTH` + `SMOOTHING LENGTH AUTOMATICALLY COMPUTED`).
     `HMIN = HMAX = 1.0` — LS-DYNA's own spelling of a constant `h` — is the one
     pair that maps exactly, to `h_1D = 2`.

  5. **`Order` stays 0 and hourglass never reaches `h`.** dyna2rad maps
     `SPHKERN == 2` onto `ORDER = 2`; Radioss's `Order` is the RENORMALISATION
     correction order, `spcompl.F:107-118` dispatches on `-1/0/1` only (so such a
     particle gets no kernel correction at all) and `spgrhead.F:180-185` packs
     the value into two bits of the group-sort key. Its own map is unreachable
     anyway — the R11.1 IMPORT card reads seven fields, so `SPHKERN` is never
     populated (verified: `FORMULATION CORRECTION ORDER = 0`). Separately,
     dyna2rad copies `*HOURGLASS` `QM` / `*CONTROL_HOURGLASS` `QH` into the
     `/PROP/SPH` field named `"h"` — a dimensionless viscosity coefficient into a
     LENGTH, on a property with no hourglass field because SPH has no hourglass
     modes. Measured: a part `*HOURGLASS QM=0.13` with `SPHINI=0.5` echoed
     `SMOOTHING LENGTH = 0.13`, and a global `*CONTROL_HOURGLASS QH=0.07`
     **zeroed the smoothing length outright** (its attribute is `LSD_QH`, which
     the identifier `"QH"` does not resolve, so an empty value is written).

  6. **`/TH/SPHCEL` lists only ids that reached a `/SPHCEL` — the #106 rule.**
     A dangling id is not a lost channel, it is starter `ERROR 69` ("TH ELEMENT
     SELECTION ID=n DOES NOT EXIST", `hm_read_thgrne.F:189`) and the whole deck
     is refused; a group that screens to nothing is not written at all
     (`ERROR 1109`). dyna2rad's SPH branch is the ONLY element branch in
     `converttimehistory.cxx` with no `FindRadElement` filter, so a deck naming a
     node that is not a particle converts "successfully" and then will not run.
     Ids go ONE PER LINE: packing them the way `*DATABASE_HISTORY_SPH` writes
     them (eight per card) is *worse* than an error — measured, seven dangling
     ids in columns 11+ gave 0 errors and only advisory `WARNING 100214`, i.e.
     the channels vanished without even reaching the ERROR 69 check.

  7. **`*CONTROL_SPH`: only `NMNEIGH` maps, and only upward.** `/SPHGLO`
     `Lneigh`/`Nneigh` are written only when the deck asks for more than
     Radioss's own defaults (120 computed / 240 stored), never to reduce them —
     and never blank: measured, an all-zero `/SPHGLO` HALVES the stored cap from
     240 to 120, so every field is explicit or the card is omitted. The other
     nineteen columns are dropped BY NAME, with `IDIM != 3` singled out as the
     one whose loss changes the ANSWER rather than the accuracy (OpenRadioss SPH
     is 3D only; r14 `bar-i/bar1.k` is exactly that deck). dyna2rad drops the
     keyword whole and silently — the string `CONTROL_SPH` does not occur
     anywhere under `reader/source/dyna2rad/`. Cards 2 and 3 are optional and
     are claimed by RAW contiguity (the #119 rule) in BOTH the handler and the
     `*INCLUDE_TRANSFORM` offset walk.

  8. **The `#120` element-registry audit, walked in full for a family with no
     connectivity.** An SPH particle IS its node, which changes most verdicts:
     it gets an arm at the implicit free-node `/BCS` guard (without it every
     particle is clamped `111 111`, which the starter accepts with 0 ERRORS and
     which freezes the whole cloud — the thick-shell `#120` bug exactly, and
     latent here because every corpus SPH deck is explicit), the modal dummy
     `/CLOAD`, `/DAMP` part scoping, `*INITIAL_VELOCITY_GENERATION` (the group
     was otherwise EMPTY and the projectile did not move), contact SECONDARY
     node groups, `/RBODY` and `*PART_INERTIA` node coverage, the orphan census,
     `_referenced_node_ids`, the element-free-part test, `--auto-gapmin`'s
     node-side clearance and the `*PART_CONTACT` `OPTT` "no effect" bucket
     (there is no `NUMSPH` loop in `i7sti3.F` either — that warning now reads
     "SOLID or SPH elements"). Four sites get a NAMED WARNING instead of an arm,
     because a particle has no face and no second node: a contact MAIN surface,
     `--auto-gapmin`'s faceting, `*DATABASE_CROSS_SECTION_PLANE` (a `/SECT` has
     no SPH group at any version, so its force under-reports by the whole SPH
     contribution) and `*INITIAL_FOAM_REFERENCE_GEOMETRY` (`/XREF` is solid-only,
     `ERROR 2013`). Every real arm has a test that FAILS when the arm is removed.

  9. **The `/SPHCEL` id column takes `IDNOFF`, not `IDEOFF`** — the only
     `*ELEMENT_` card in this converter whose field 0 is a NODE. Radioss forces
     the cell id equal to the node id (`hm_read_sphcel.F:243-250`), so no other
     offset can apply. This is where dyna2rad cannot follow at all: it emits a
     `//SUBMODEL` and lets Radioss apply the offsets, and the `/SPHCEL` id
     column is a plain `INT` with no entity type, so the submodel machinery
     leaves it alone while `/NODE` moves — measured, `IDNOFF = 1000` with or
     without a matching `IDEOFF` gave four `ERROR ID : 78 … NODE ID=1 DOES NOT
     EXIST` and `TOTAL MASS = 0`. k2rad bakes the offsets into the deck text, so
     it is immune by construction; the 16-wide `MASS` column is preserved
     literally rather than re-sliced at 10 (the `*ELEMENT_MASS` defect).

  10. **`*SECTION_SPH` is a FIFTH SECID-keyed `/PROP` namespace.**
      `next_prop_id()` guards against it, and a SECID shared with a shell /
      solid / thick-shell / beam part moves the SPH property to a synthesized id
      with its parts repointed — two `/PROP` cards on one id is starter
      `ERROR 79` (DUPLICATE ID IN PID DEFINITION). Corpus sweep over 528 deduped
      decks, master vs branch: **501 fully identical, 27 moved, 0 conversion
      errors either side, and the moved set is exactly the 27 SPH decks.**

  11. **Review round.** Five defects that each produced a deck the starter
      refuses or silently mutilates, plus the reports that described the wrong
      thing:

      * **The `*INCLUDE_TRANSFORM` rewriter read the particle card on a fixed
        `8/8/16/8` slice while the handler that reads the same card prefers a
        WHITESPACE split**, so the two disagreed on every layout whose columns
        are not exactly 8/8/16. Measured with `IDNOFF=1000 IDPOFF=30`, the I10
        card `"       101         2   9.6834260e-05"` came out as
        `"    1001      31   2   9.6834260e-05"` — read back as node 1001, part
        31 and a mass 20 000x out — and an end-to-end I10 include lost **100 %
        of its particles** to a MESH LOSS that named ids the deck never
        contained. The rewriter now makes the handler's own free-vs-fixed
        decision, rewrites the id CELLS in place (so an I8 deck keeps its
        columns and the mass text is untouched), and then **re-parses its own
        output and asserts it equals source + offsets**, falling back to a plain
        space-separated card when a layout cannot keep both. 24 000 generated
        layout/offset combinations agree.
      * **`*DATABASE_HISTORY_SPH[_SET]` had no offset spec** while every sibling
        (`_NODE` / `_SHELL` / `_SOLID` / `_TSHELL`) has one, so the requested ids
        stayed put while the particles they name moved with `IDNOFF` — measured,
        an include offset to 1001-1004 asking for 1-4 got the PARENT deck's
        particles, which the `ERROR 69` screen cannot catch because those ids do
        exist as `/SPHCEL`. The ids are NODE ids (`IDNOFF`); the `_SET` spelling
        takes `IDSOFF`.
      * **A section whose particles ALL leave the MASS blank reproduced the
        exact `Mp = 1` fabrication this batch exists to prevent**, and every
        diagnostic denied it — "the fabrication cannot happen here", "the mean
        of the particles that DO state one" when none does, "the particles carry
        DIFFERENT masses" about eight identical blanks, and an h ratio computed
        from the invented number. `Mp` is now derived from the FILL,
        `rho x d_ref^3`, with a single `MASS INVENTED:` report stating the
        number now in the deck and that the source stated none; the deck's own
        `h` survives, because a type-0 particle leaves the property's `h` alone.
      * **A `*SECTION_SPH` whose id is claimed by another family emitted a
        SECOND `/PROP` on it** — starter `ERROR 79`, silently. Two holes, both
        found by sweeping all four other meshed families x (meshed /
        element-free / unreferenced): a section no particle sits on now takes
        the `wrong_family` refusal `writer/tshell.py` already makes, and the
        mixed-SECID split now also fires on another family's *CARD*, not only on
        another family's meshed part (an unreferenced `*SECTION_SHELL` still
        emits `/PROP/SHELL/<secid>`). Under both, a new deck-wide
        `_warn_duplicate_prop_ids` scan over the assembled starter — the `/PROP`
        analogue of `_warn_duplicate_th_group_ids` — names any duplicate no
        single writer can see, including the pre-existing non-SPH ones.
      * **The provisional-element screen keyed every family into ONE flat set of
        ids.** SPH is keyed by its NODE id and LS-DYNA element ids are per
        family, so any deck with two provisional blocks lost the intersection of
        their id ranges: measured, a provisional `*ELEMENT_SPH_MADEUP` on nodes
        1..8 beside a provisional `*ELEMENT_SHELL_MADEUP` with EIDs 1,2,3 lost
        particles 1, 2 and 3 — 37.5 % of the cloud — while the report blamed the
        SPH block's own node screen, which had passed. The set is keyed
        `(family, id)` now.
      * **`*MAT_PLASTIC_KINEMATIC` on a particle part refused the whole deck.**
        `/MAT/LAW44` (COWPER) does not declare SPH — `hm_read_mat44.F` states
        BEAM_ALL / ELASTO_PLASTIC / EOS / INCREMENTAL / LARGE_STRAIN /
        SHELL_ISOTROPIC / SOLID_ISOTROPIC / TRUSS — so `ERROR 3046` refused r14
        `sph/bar-i/bar1.k` and `sph/bar-ii/bar2.k`, two decks LS-DYNA runs.
        `/MAT/LAW2` IS declared (`mat002/hm_read_mat02_jc.F90:383`) and
        describes the identical curve whenever the material has no
        Cowper-Symonds rate term and no EFFECTIVE kinematic hardening
        (`a = SIGY`, `b = E*ETAN/(E-ETAN)`, `n = 1` is the same bilinear plastic
        branch LAW44 is given). Both corpus decks share MID 1 between solid and
        particle parts, and one `/MAT` id cannot be two laws, so a LAW2 CLONE is
        written and only the SPH parts are repointed at it; the solid keeps
        LAW44. A material that is NOT expressible keeps LAW44 and keeps the
        loud `ERROR 3046` report — a different constitutive law is never
        substituted silently. Both decks now read back **`0 ERROR(S)
        0 WARNING(S)`** from `starter_win64`.
      * Smaller, each measured: the two mass columns use a formatter that
        ROUND-TRIPS (`common._f` writes `%.6E` below 1e-4, and in Mg-mm-s every
        particle mass is — a stated `1.234567891E-09` came back as
        `1.2345680000000E-06` over 1000 particles); the per-cell route reports
        the derived `h` as a min..max SPAN and names the SMALLEST as the one
        that sets the time step, instead of one value from the mean mass that no
        particle has and whose direction is wrong for the governing half;
        `*CONTROL_SPH` losses — `IDIM` above all — are reported even when the
        particles never reached the state; a `_ELLIPSE` card 2 written as
        explicit zeros is no longer reported as lost anisotropy; a blank MASS
        with a populated `NEND` is read as the range it is; law **106** joined
        the SPH whitelist (`mat106/hm_read_mat106.F90:295`) and the `/MAT/USER`
        slots 29/30/31 are all three or none; `_discrete_beam_pids` no longer
        claims a particle part (which was skipped WHOLE — `/PART`, `/SPHCEL`
        block and `/TH/SPHCEL` alike); `_warn_no_pacing_element` counts
        particles, which do pace the engine step (`mdtsph.F:132`); and the
        `_interparticle_distance` / `_part_node_sets` / `_assign_hourglass_props`
        comments now state what is actually true.

  Out of scope, and named in the README rather than silently absent:
  `*BOUNDARY_SPH_SYMMETRY_PLANE` / `_FLOW` / `_NOFLOW` and
  `*SPH_SYMMETRY_PLANE` (Radioss target `/SPHBCS`), `*DEFINE_SPH_*` injection /
  massflow / active-region (`/SPH/RESERVE`, `/SPH/INOUT`),
  `*DEFINE_ADAPTIVE_SOLID_TO_SPH` (`/PROP/SOLID` `Nsphdir`), and the anisotropic
  `_ELLIPSE` smoothing lengths, `DEATH` / `START`, `SPHKERN != 0` and any
  `HMIN`/`HMAX` pair other than `1/1`.

- **The thick-shell batch: `*ELEMENT_TSHELL` (+ `_BETA` / `_COMPOSITE`) →
  `/BRICK`, `*SECTION_TSHELL` → the three-way `/PROP/TYPE20` (TSHELL, isotropic)
  / `TYPE21` (TSH_ORTH, orthotropic) / `TYPE22` (TSH_COMP, layered) split, and
  `*PART_COMPOSITE_TSHELL` → a real `/PROP/TYPE22` with per-ply `mat_IDi`,
  `ti/t` and `Phi_i`.** Before this batch the whole family landed in
  `skipped_keywords`, and for an element keyword that is not a soft failure:
  `_make_parts_and_elements` emits elements inside the `state.parts` loop, so
  the part stayed in the deck with NO element block under it. Measured on master
  for all nine r14 thick-shell decks, identically:
  `SKIPPED: ['DATABASE_HISTORY_TSHELL', 'ELEMENT_TSHELL', 'SECTION_TSHELL']`,
  emitted mesh/prop cards `['/PART/1', '/PROP/SHELL/1']` and nothing else —
  **100 % mesh loss with no `MESH LOSS:` warning**, because the orphan census
  can only report elements that were parsed and none were. dyna2rad converts the
  bare keyword but its CFG declares no option at all on it
  (`Keyword971/ELEMENTS/tshell.cfg` is one `CARD` line), so `_BETA` and
  `_COMPOSITE` are unmatched headers whose whole block it drops the same way.

  1. **The thickness direction is carried by a VERBATIM connectivity copy plus
     an explicit `Icstr = 010`, and by nothing else.** LS-DYNA's "nodes n1 to n4
     define the lower surface, and nodes n5 to n8 define the upper surface"
     (Vol I R16 p.2703 Remark 1) is exactly the pairing Radioss reads at
     `Icstr = 010`: `scdtchk3.F:84-246` takes the through-thickness edges there
     as (1-5) (2-6) (3-7) (4-8), and `scortho3.F:71-99` builds the same `S` axis
     out of the connectivity. So a permutation would be a bug, not a fix — the
     `/TETRA10` lesson in reverse. **dyna2rad leaves the `Icstr` column blank**
     and relies on the starter's own `IF (IHBE == 14 .AND. ICSTR == 0) ICSTR =
     10`, which exists for `IHBE == 14` ONLY — nothing restores the field on
     `Isolid = 15`, where a blank column echoes `CONSTANT STRESS FLAG = 0`.

     The field is genuinely load-bearing, and the counterfactual proves it:
     patching only `Icstr` from `010` to `100` on an otherwise untouched deck
     moved the tip deflection by **2.08x**, landing bit-identically on the value
     the WRONG connectivity gives (−0.950539 vs −1.973132 mm). Node order and
     `Icstr` are the two halves of one statement and both are read. k2rad writes
     it on all three property types so the answer never depends on a starter
     default that covers one formulation.

     *(An earlier revision of this entry also claimed a blank `Icstr` desyncs
     the TYPE22 layer-card COUNT, citing `WARNING ID : 100213` + `ERROR ID :
     675` with an empty last layer. That does not reproduce on the 2026-05-20
     build — blanking the column on both an `Isolid=14 / Inpts=222` and an
     `Isolid=15 / Inpts=2` two-layer TYPE22 gives 0 ERRORS, 0 WARNINGS and a
     bit-identical engine result — so the claim is withdrawn and the
     justification above is the one that holds.)*

  2. **A degenerate 6-node thick shell keeps LS-DYNA's collapsed
     `n1 n2 n3 n3 n4 n5 n6 n6` form**, and the thick shells get a bucket of
     their own rather than joining `solid_elems`. Both follow from the same
     fact: `hm_read_solid.F:145-192` classifies a solid by its ZERO trailing
     slots, so a wedge written with zeros becomes `ISOLNOD = 6` and is then
     refused on any thick-shell property with `Isolid != 15` — **ERROR 639**,
     whose own message names `n1 n2 n3 n4 n5 n6 n6 n5` as the alternative. The
     `/BRICK` writer's solid path meanwhile splits by DISTINCT-node count
     (4 → `/TETRA4`, 10 → `/TETRA10`), which a 6-distinct-node thick shell would
     have fallen into.

     A card that names only SIX ids is not a form LS-DYNA defines — Remark 1
     spells the pentahedron out in all eight slots — but it has one obvious
     reading, so it is expanded into exactly that spelling
     (`n1 n2 n3 n3 n4 n5 n6 n6`), and a card written `n1..n6 0 0` takes the same
     route because the trailing zeros are examined before they are stripped.
     Padding by repeating the LAST id instead — the first cut of this batch —
     produced `n1..n6 n6 n6`, whose upper face has collapsed to a point:
     measured on one prism, **1.950E-10 against the correct 3.900E-10**, i.e.
     exactly half the mass and volume, with the starter reporting NORMAL
     TERMINATION, 0 ERRORS and 0 WARNINGS. That is the `/TETRA10` silent
     under-volume failure mode again. All three spellings (six fields, the
     manual's eight, and the trailing-zero form) now emit identical connectivity
     and measure `3.90000000E-10` = ρ·V exactly. Four, five and seven ids still
     repeat the last id — legal for seven (a pyramid), a collapsed face for four
     or five — and say so.

  3. **`ELFORM` → `Isolid` follows dyna2rad's total map — `1 → 15`, everything
     else `→ 14` — but a BLANK `ELFORM` is LS-DYNA's default 1, not 0.**
     dyna2rad reads the blank as 0, which falls into the `else` of its own
     `elform == 1 ? 15 : 14` test, so a deck that asked for the one-point
     reduced-integration default by leaving the field empty gets the
     FULL-integration HA8 instead — the opposite element class. The same
     divergence applies to `NIP`: blank is 2 ("EQ.0: set to 2 integration
     points", Vol I R16 p.3717) where dyna2rad keeps the raw 0 (measured — a
     blank-NIP section echoed `NIP = 0`), which on the composite branch writes
     ZERO ply cards against a property expecting one, ERROR 675 again. What
     ELFORM costs is named per section: 5 and 6 lose their REDUCED integration,
     and 1/2/6 lose their PLANE-STRESS treatment (they are extruded thin shells
     with an uncoupled thickness-direction stiffness, Remark 1, while every
     Radioss thick shell is a 3D-stress element).

  4. **`Inpts` is a packed `ijk` field with an unpack gate at 200.** On
     `Isolid = 14` k2rad writes `2·100 + clamp(NIP,1,9)·10 + 2`, never below
     212: the CFG splits the digits only when the value exceeds 200, so a
     leading digit below 2 — or a bare `200` — is read as `Inpts_S = NBP` with
     zero points in `r` and `t`. On `Isolid = 15` it is the plain `NIP`, clamped
     to 1..9; **dyna2rad clamps only the packed branch** and passes a raw
     `NIP > 9` straight through to starter MSGID 563. The clamp is REPORTED on
     both formulations, naming the requested and the delivered count — it is a
     through-thickness physics reduction either way.

  5. **The >9-layer encoding — and why TYPE22 does NOT change formulation for
     it.** More than nine layers cannot live in a packed digit, so an
     `Isolid = 14` `/PROP/TYPE22` zeroes the thickness digit and puts the count
     in `Iint` (`hm_read_prop22.F:272-275` reads `NLY` from `IINT` exactly when
     `NPTS` is 0). On `Isolid = 15` no such trick is needed: that branch is
     `CASE(15) / NLY = NPT / IP = 3` with **no range check at all**, and the
     only guards after it are ERROR 27 (`NLY <= 0`) and ERROR 28
     (`NLY > NLYMAX = 200`). The 1..9 cap that MSGID 563 enforces belongs to
     `hm_read_prop20.F:204-213` / `hm_read_prop21.F` — TYPE20 and TYPE21 — not
     to TYPE22. The CFG agrees: for `Iint <= 9` and `NBP <= 200` the import
     chain of `prop_p22_tsh_comp.cfg` falls through to `ASSIGN(N, NBP)`.

     So a laminate of up to 200 layers is expressible on EITHER formulation and
     the deck's own `ELFORM` is kept. An intermediate cut of this batch forced
     `Isolid 15 → 14` above nine layers, which would have swapped HSEPH/PA6 (one
     in-plane point, physical stabilization) for the fully integrated HA8 on the
     most common composite case — LS-DYNA's own default `ELFORM 1` — for nothing.
     Verified live: a 12-ply `ELFORM = 1` ICOMP section now emits
     `Isolid 15 / Inpts 12 / Iint 0` and the starter echoes
     `NUMBER OF INTEGRATION POINTS = 12` and `NUMBER OF LAYERS = 12` with
     **0 ERRORS, 0 WARNINGS**; the `ELFORM = 2` control still takes the
     `202 / Iint 12` encoding and echoes the same 12 layers. The invariant
     "cards written == count declared" is asserted over `ELFORM x NIP` in the
     tests, and covers both encodings.

  6. **Orthotropy: the #90 `AOPT` machinery, TRANSLATED — a thick-shell
     property has no `Ip` column.** `scmorth3.F:126-134` resolves the whole
     `Vx/Vy/Vz + skew_ID` input to ONE vector (`SKEW(1:3, ISKV)`, the skew's
     FIRST axis, when a skew is given) and then PROJECTS it onto the element
     mid-plane. So `AOPT = 2` maps exactly onto a synthesized `/SKEW/FIX` whose
     `X'` is `a`, and a negative `AOPT` onto the `*DEFINE_COORDINATE` skew id.
     **`AOPT = 3` needs a −90° shift on `Phi`**: LS-DYNA makes direction 1 the
     cross product `v × n` rotated by `BETA`, and `v × n = R(−90°)·proj(v)` for
     any `v` (the out-of-plane part drops out of the cross product), so `V = v`
     with `Phi = BETA − 90` reproduces it exactly. dyna2rad copies `v` and
     leaves `Phi` at 0 — material directions 1 and 2 swapped — and for
     `AOPT ∈ {0, 1, 4, negative}` it writes NOTHING, leaving a zero reference
     vector that the starter rejects **per element** with ERROR 526 "REFERENCE
     DIRECTION IS ALMOST NORMAL TO THICK SHELL MID-SURFACE". Those three modes
     (element frame, reference point, cylindrical) genuinely have no
     thick-shell expression, so here they warn and fall back to global X, which
     at least starts.

  7. **`*PART_COMPOSITE_TSHELL` is the one genuine gap this batch fills.**
     dyna2rad dispatches it on the substring `COMPOSITE` alone
     (`convertprops.cxx:92`) and emits the THIN-shell `/PROP/TYPE51` +
     `/PROP/TYPE19` sandwich, which its own starter then refuses on the bricks —
     `ERROR ID : 60 INVALID PROPERTY ID=1 (TYPE = 51) FOR BRICK ELEMENT` plus
     `ERROR ID : 226 WRONG SOLID PROPERTY TYPE 51` — and its ply thicknesses go
     out as ABSOLUTE lengths where TYPE22 wants a fraction. Here the layup
     becomes a per-part `/PROP/TYPE22` with real `mat_IDi`, `Phi_i` and
     `ti/t = THICKi / ΣTHICKj`; the manual makes those thicknesses relative on a
     thick shell anyway ("the total thickness is obtained from the positions of
     the nodes … the THICKi are also scaled to conform to the geometry",
     Vol I R16 p.3529). `Zi` is left 0 with `Ipos = 0` so the starter stacks the
     layers itself — the `*INTEGRATION_SHELL` `Zi` lesson applied to a thick
     shell. A `_TSHELL` spelling whose elements are THIN shells keeps the
     pre-existing warn-and-fall-back path unchanged.

  8. **A per-element angle or layup cannot exist on a `/BRICK`** — there is no
     per-element column at all, unlike `/SHELL`'s `Phi` (which the #91 finding
     showed is itself read for only some IGTYPs). `*ELEMENT_TSHELL_BETA`'s angle
     (five F16 cells, cols 65–80; the manual's 10-column table is wrong, an
     LS-PrePost round trip re-emits the ruler `$# - - - - beta`) is therefore
     FOLDED into the property angle when every thick shell on the section
     agrees, and warn-dropped when they disagree. `_COMPOSITE`'s per-element ply
     stack — a variable-length card-2b block whose end is found positionally,
     "the fourth field must be zero or blank to be interpreted as a Card 2b" —
     is promoted to a per-part `/PROP/TYPE22` when every element of the part
     declares the same one, and warn-dropped otherwise. Either way the mesh
     survives, and an unrecognized suffix takes the provisional path (kept by
     content, then screened against the node table, with a `/BRICK` arm added to
     `_screen_provisional_elements`).

  9. **Material compatibility is reported pre-starter**, the
     `_warn_beam_type3_material` shape applied to `PROP_SOLID`:
     `check_mat_elem_prop_compatibility.F:198-234` lets TYPE20 take classes
     1/5/6, TYPE21 1/2/6 and TYPE22 1/2/3/6, so an orthotropic law on a TYPE20,
     a porous `/MAT/LAW6` on a TYPE21/22 and a shell-only `/MAT/LAW27` /
     `LAW32` / `LAW43` anywhere are each named by part id and law (ERROR 3047,
     or 3046 one step earlier for a law with no solid class at all).
     `/MAT/LAW1` additionally makes the starter force-RESET `Inpts` to 222 / 2
     on TYPE20 and TYPE21 (`sgrtails.F:694-704`, WARNING 791; TYPE22 exempt),
     which is reported rather than left to be discovered in the `.out`.
     Class 3 `SOLID_COMPOSITE` is declared by **no** law in the tree, so
     TYPE22's extra allowance for it is unreachable.

  10. **A mesh that exists has to be visible to everything that walks the
      element tables**, and until this batch nothing walked `tshell_elems`
      because it did not exist. Thick shells therefore joined
      `_warn_orphan_elements` / `_ORPHAN_ELEM_KINDS`, `_part_node_sets`,
      `_element_free_part_ids` (both the "meshed" and the "defined section"
      sides) and `next_prop_id`'s guard set — `/PROP/TYPE20|21|22` sits under
      the SECID verbatim, so `sec_tshells` is a FOURTH SECID-keyed property
      namespace and a `*SECTION_TSHELL` at or above the 90001 auto-id base would
      otherwise collide with a synthesized property. Four of these were not
      bookkeeping but real losses, each measured on a one-element deck:

      * **`/DAMP`.** Radioss Rayleigh damping is NODE-based over a `/GRNOD`,
        with no element-type restriction, so a thick shell's nodes damp exactly
        like a brick's — this is the tshell half of the scope caveat the damping
        batch wrote down. `ex_15_thick_shell_elform_2.k` reported
        `*DAMPING_*: no target deformable nodes found - /DAMP not emitted` on
        master and now echoes
        `NDAMP: NUMBER OF RAYLEIGH DAMPING GROUPS = 1` /
        `RAYLEIGH DAMPING  NODE GROUP ID 90007  ALPHA 11.535`. (The
        `/DAMP/FREQUENCY_RANGE` path is the opposite case — it enters as a
        viscous stress INSIDE the shell/solid material law and genuinely cannot
        reach a thick shell — so its own "come out COMPLETELY UNDAMPED" warning
        is left exactly as it was.)
      * **Contact.** `_make_master_surface` classified a part as "solid" by
        `any(e.pid == pid for e in state.solid_elems)`, so a contact naming a
        thick-shell part built NO surface and the whole `/INTER` was dropped
        (loudly, via `_drop_interface`, but dropped). Thick shells are `/BRICK`
        in the emitted deck, so they take the same `/SURF/PART[/EXT]`; the
        secondary-side node harvesters, `_solid_contact_master_pids` and
        `_solid_pids_by_part` follow the same rule.
      * **Rigid bodies.** `*MAT_RIGID` gathers its `/RBODY` secondary nodes from
        the element tables, and the CNRB master-node placement needs the set of
        nodes that carry an element; a thick-shell part missing from both gave a
        rigid body with no nodes.
      * **The implicit no-contact stub.** Its gate read "no deformable surface
        to build the interface from" as *shells or solids*, so the one deck
        class this batch enables — every r14 `*ELEMENT_TSHELL` deck is implicit
        — was the one that never got it. `NINTER` now reads 1 on the
        `example-02` and `example-15` families; the modal `example-13` is still
        excluded by the `is_modal` guard that exists to keep contact stiffness
        out of an exported stiffness matrix.

      Every one of these is a union with a container that is EMPTY on any deck
      without `*ELEMENT_TSHELL`, which is what makes them safe — and the corpus
      sweep confirms it. `_assign_composite_props` and `_assign_ortho_props`
      instead SKIP a thick-shell part explicitly, before their element-kind
      ladder, which would otherwise have read a tshell-only part as "no shell or
      solid elements" and warned about a mesh that is perfectly fine.

      **The first cut of item 10 was not exhaustive**, and the two walks it
      missed are the two that decide WHICH NODES CARRY STIFFNESS — the place
      where being invisible is fatal rather than lossy, and the place a
      starter-only check cannot see, because a `/BCS` on real nodes is perfectly
      legal and reports 0 ERRORS:

      * **`_make_free_node_constraints`.** The implicit singularity guard fixes
        every node attached to no element in all six DOFs. Without a thick-shell
        arm it classified the ENTIRE MESH as free reference nodes: measured on
        `ex_15_thick_shell_elform_2.k`, **323 of 323 brick nodes inside
        `/BCS/90008 … 111 111`** — a model that cannot move, on exactly the deck
        class this batch exists to enable.
      * **`_make_modal_dummy_cload`.** Same shape, same file: a modal run needs
        a unit `/CLOAD` on a free structural node or the implicit engine stops
        with MESSAGE ID 79, and on an all-thick-shell mesh the candidate set was
        EMPTY — `ex_13_thick_shell_elform_2.k` reported *"no free node to put a
        dummy /CLOAD on"* and could not have run.

      Four more walks were lossy rather than fatal and are now covered:
      `_damping_part_nodes` (the `*DAMPING_PART_MASS`/`_SET` route, which shares
      its rationale with the `/DAMP` fix above but resolves its node group
      through a different helper), `_inivel_gen_group_nodes`
      (`*INITIAL_VELOCITY_GENERATION` scoped to a thick-shell part resolved to
      an empty group and the initial condition was dropped), `_plane_cut`
      (`*DATABASE_CROSS_SECTION_PLANE` cut nothing and no `/SECT` was written),
      and `_referenced_node_ids`. Three more were only cosmetic and are
      corrected for accuracy: `gapmin._surface_triangles` / `_part_nodes_map`
      (`--auto-gapmin` had no surface to measure on a thick-shell contact side),
      `_warn_part_contact_fields` (a thick-shell part's `OPTT` is unread for the
      same missing-`NUMELS`-loop reason a solid's is) and
      `_resolve_contact_interior` (whose comment still said k2rad has no
      `*ELEMENT_TSHELL` path). The remaining `solid_elems` sites are TET10-,
      spotweld-, ALE- or `/XREF`-specific and have no thick-shell reading.
      `_make_damping_frequency_range` is deliberately left alone: `IPARG(93)` is
      consumed only in `cmain3.F`, the SHELL material path, so its "cannot reach
      a thick shell" warning is correct as written.

  11. **`*DATABASE_HISTORY_TSHELL` → `/TH/BRIC`**, the last member of the family
      that was still unroutable. Until the elements existed there was nothing to
      record; now that a thick shell IS a `/BRICK`, the same block
      `*DATABASE_HISTORY_SOLID` takes resolves its ids exactly. It was in
      `skipped_keywords` on all nine r14 decks, all of which name real element
      ids there (`ex_15` asks for 28/29/36/37).

  Dropped, with a message each (dyna2rad drops all four silently): `PROPT`, a
  printout option; `TSHEAR`, constant vs parabolic transverse shear, a real
  physics difference since Radioss thick shells are always parabolic; a negative
  `QR`, i.e. an `*INTEGRATION_SHELL` rule reference; and `SHRF` on TYPE20/TYPE21,
  which have no transverse-shear column at all. On TYPE22 `SHRF` **is** carried,
  to `Ashear` — dyna2rad drops it there as well (measured: `SHRF = 0.7` echoed
  `SHEAR AREA REDUCTION FACTOR = 1.000`). `*PART_COMPOSITE_TSHELL` card 3b puts
  `TSHEAR` in the column the thin-shell card 3a uses for `THSHEL`, so it needed
  its own read — naming the field on the `*SECTION_TSHELL` route and losing it
  silently on the other would have been worse than either. An out-of-range
  `SHRF` on the one property that DOES carry it is named too: `Ashear` takes
  `(0, 1]` and anything else falls back to the solver default 1.0.

  Four more drops that used to be silent, all of the "the module's standard is
  that everything dropped is named, and these were not" shape:

  * The `NIP > 9` clamp on `Isolid = 14` (see item 4). `ELFORM = 2, NIP = 15`
    emitted `Inpts 292` — nine points, six lost — with ZERO warnings.
  * A `*SECTION_TSHELL` on a TYPE20 whose material carries a non-default `AOPT`.
    The iso/ortho split keys on the EMITTED law's `PROP_SOLID` class, not on
    dyna2rad's "the card HAS an `AOPT` field", and the two disagree for exactly
    one shape: `*MAT_MODIFIED_HONEYCOMB` → `/MAT/LAW50`, which declares
    `SOLID_ISOTROPIC` yet carries per-direction moduli and yield curves. It
    lands on `/PROP/TYPE20`, which has no reference-vector card at all, so the
    axes are dropped and the frame falls back to the connectivity. Routing to
    TYPE21 anyway (d2r's answer) would change the property type on a path with
    no solver validation, so the drop is NAMED instead.
  * A THIN `*PART_COMPOSITE` on a thick-shell mesh. Neither the layup route
    (which wants `_TSHELL`) nor `_assign_composite_props` (which now skips every
    thick-shell part) claimed it, so its whole laminate went out under the
    generic "PLACEHOLDER created" note. LS-DYNA does not accept the pairing
    either, so it is reported rather than quietly promoted.
  * `ELFORM` losses on the `*PART_COMPOSITE_TSHELL` card-3b route. The same
    value on a `*SECTION_TSHELL` produced the plane-stress and reduced-
    integration warnings; on the layup route it produced none. `_warn_elform`
    now takes `(label, elform, blank, isolid)` and both routes call it.

  Three parser paths that used to lose a card in silence now report it: a
  connectivity line the reader refuses (an interior zero — the orphan census
  cannot see it, because no element was ever created); a `_BETA` card 2a written
  in the manual's own ten-column spelling rather than the five-F16 ruler
  LS-PrePost writes, which used to read as `beta = 0.0` — the worst available
  failure mode on the one layout claim in this batch backed by a round trip
  rather than the manual, so the value is now taken from the column it is found
  in and the deviation named; and a FREE-FORMAT card 2b that omits the gap
  columns, which `_card`'s fixed→free fallback turned into six tokens whose
  fourth is the second MID — measured as a whole layup vanishing with no
  message, and on the `*INCLUDE_TRANSFORM` side as node offsets landing on `2`
  and `90.0`. The free branch is taken on the same test `_card` itself uses to
  fall back, never on the token count, because a properly FIXED card with blank
  gap columns whitespace-splits to six tokens too.

  Two hazards found in self-review, both fixed by the gate that now decides
  whether a section property is emitted at all — plus the case that gate must
  NOT break. An **unreferenced**
  `*SECTION_TSHELL` (no `*PART` names it) has no material either, so an ICOMP=1
  one would have produced a `/PROP/TYPE22` with `mat_IDi = 0` — starter
  ERROR 676 — and is now skipped the way dyna2rad skips it (reported on the
  recognized-not-emitted channel); and a `*PART` on a `*SECTION_TSHELL` whose
  elements are SHELLS or ordinary SOLIDS would have got BOTH its own family's
  auto-created property and a thick-shell one under the same SECID, which is
  starter ERROR 79. That second gate only covered HALF the case at first — it
  fired when NO part on the section was thick-shell meshed, and a MIXED section
  (one thick-shell part, one shell part, one SECID) slipped through it: measured
  `/PROP/SHELL/1` *and* `/PROP/TYPE20/1` in one deck and
  `ERROR ID : 79 ** ERROR: DUPLICATE ID / IN PID DEFINITION / ID=1` plus 60, 226
  and 495, with no converter warning at all. Both families need a property in
  that case, so `_split_mixed_family_sections` (a prepass, because the /PART
  repoint happens long before the /PROP is written) moves the thick-shell one to
  a synthesized id and repoints its parts. Re-measured on the same deck:
  `/PROP/SHELL/1` + `/PROP/TYPE20/90001`, ERROR 79 gone. An element-free
  `*PART` on a `*SECTION_TSHELL` still gets
  its property, because `_element_free_part_ids` counts a defined `sec_tshells`
  entry as resolved and hands out no placeholder — without it that /PART would
  point at an id nothing writes (ERROR 178). All three are pinned by tests.

  **Regression evidence.** `starter_win64` (2026-05-20), `np=1`, on fourteen
  decks: the r14 `example-02` and `example-15` thick-shell decks (ELFORM 2 / 3 /
  5, 16 and 192 elements) and eight hand-built TYPE21/TYPE22 decks, since **the
  corpus contains no ICOMP=1 and no orthotropic-material thick shell anywhere**
  — all nine r14 decks are ELFORM ∈ {2,3,5}, ICOMP=0, NIP=5, `*MAT_ELASTIC`.

  ```
  ef2/ef3/ef5     0 ERROR(S)  2 WARNING(S)   ids 791
  x152/x153/x155  0 ERROR(S)  5 WARNING(S)   ids 791, 312
  val21 val21v val21b val22 val22b val22c val22d val22pc
                  0 ERROR(S)  0 WARNING(S)   NORMAL TERMINATION
  ```

  **0 ERRORS on every one.** The repeats of 791 are the same warning on the same
  property — the starter runs its compatibility pass again after the interface's
  group setup — and the `example-15` 312 is PRE-EXISTING and unrelated: the same
  deck converted on master reads `1 WARNING(S) … WARNING ID : 312` too. What
  changed on that deck is the census, which is the whole point:

  ```
                        master        this branch
  NUMELS                     0                192
  NINTER                     0                  1
  NDAMP                      0                  1
  element type               -   THICK-SHELL HEXA
  ```

  The 791 on all six is exactly the one k2rad predicted before writing the deck:

  ```
  WARNING ID :    791
  ** WARNING IN PROPERTY SET
     -- PROPERTY ID: 1
     MATERIAL LAW 1 IS USED WITH ISOLID = 14 AND A NUMBER OF INTEGRATION POINTS
     IN THICKNESS DIRECTION NOT EQUAL TO 2, SET IT TO 2
  ```

  The elements are recognised as thick shells, not as ordinary bricks —
  `Part id,name: 1 … Elm type: THICK-SHELL HEXA` — and the TYPE20 echo reads
  back every field:

  ```
       STANDARD THICK SHELL PROPERTY SET
       FORMULATION FLAG. . . . . . . . . . . .=        14
       CONSTANT STRESS FLAG. . . . . . . . . .=        10      <- the Icstr k2rad writes
       NUMBER OF INTEGRATION POINTS. .  . .  .= 20 (252)       <- 2 x NIP=5 x 2
  ```

  `val22pc` (`*PART_COMPOSITE_TSHELL`, plies `1/1.5/0°` and `2/0.5/45°`) is the
  decisive one, and the starter derives the layer positions from the fractions
  exactly as `hm_read_prop22.F:429-433` says (`Z1 = −0.5 + t1/2 = −0.125`,
  `Z2 = Z1 + (t2+t1)/2 = +0.375`):

  ```
       COMPOSITE LAYERED THICK SHELL PROPERTY SET
       WITH HETEROGENIOUS PROPERTY IN THICKNESS
       NUMBER OF LAYERS. . . . . . . . . . . .=         2
       POSITION INPUT FLAG . . . . . . . . . .=         0
       SHEAR AREA REDUCTION FACTOR . . . . . .= 0.7000000000000
       LAYER :  1   ANGLE  0.0   THICKNESS 0.75   POSITION -0.125   MATERIAL 1
       LAYER :  2   ANGLE 45.0   THICKNESS 0.25   POSITION +0.375   MATERIAL 2
  ```

  and the other five confirm each remaining branch: `val21` the AOPT=2 skew
  (`ORTHOTROPIC SKEW FRAME = 1`, `Inpts 242`, `CONSTANT STRESS FLAG = 10`),
  `val21v` the AOPT=3 shift (`REFERENCE VECTOR VY = 1.0`, `ORTHOTROPIC ANGLE =
  −75.0` from `BETA = 15`), `val21b` the folded `*ELEMENT_TSHELL_BETA`
  (`ORTHOTROPIC ANGLE = 30.0`), `val22b`/`val22c` the >9-layer encodings
  (`Inpts 202` / `Iint 12` on `ELFORM = 2`, positions −0.4583 … +0.4583; the
  `ELFORM = 1` twin keeps `Isolid 15` and states the count in `Inpts` directly),
  and `val22d` the single-layer edge (`Isolid 15`, `Inpts 1`, and the starter's
  own `NLY == 1 → ASHEAR = 1e-10`).

  **Review round.** Six further probe decks, `starter_win64` (2026-05-20):
  a 12-ply ICOMP section on `ELFORM = 1` and on `ELFORM = 2`
  (`Isolid 15 / Inpts 12 / Iint 0` and `Isolid 14 / Inpts 202 / Iint 12`, both
  echoing `NUMBER OF LAYERS = 12`, both 0 ERRORS 0 WARNINGS); the same
  pentahedron in all three spellings (six fields, the manual's eight, and the
  trailing-zero form) all giving `TOTAL MASS = 3.90000000E-10` = ρ·V exactly
  where the six-field form used to give half that; and the mixed shell +
  thick-shell SECID, whose `ERROR ID : 79` is gone.

  All **nine r14 decks re-run: 0 starter ERRORS**, the free-node `/BCS` group
  is absent on every one (it used to hold the entire mesh), the modal
  `example-13` now gets the dummy `/CLOAD` it needs to start at all, and
  `*DATABASE_HISTORY_TSHELL` rides `/TH/BRIC` instead of sitting in
  `skipped_keywords`.

  **Corpus sweep** (415 deduped decks over the repo, `Ryan_Lee_Examples`,
  `ls-dyna_example` and the r14 ton-mm-s tree), SHA-256 over both `_0000.rad`
  and `_0001.rad` plus warning-set / skip-list / `recognized_not_emitted`
  deltas, master `3cd12d5` vs this branch: **406/415 fully identical, 0
  conversion errors either side, and `_0001.rad` byte-identical on all 415** —
  the whole delta is starter-side, which is the right shape. The nine movers are
  exactly the nine thick-shell decks — `example-02`, `example-13` and
  `example-15` at ELFORM 2, 3 and 5 — every one of which went from a mesh-free
  `/PART` on a placeholder `/PROP/SHELL` to its full 16 / 192 / 192 `/BRICK`
  elements on a `/PROP/TYPE20`. That is the intended delta, not noise.
  (`example-13` still gets no implicit contact stub — the `is_modal` guard doing
  its job, since a stub would pollute the exported stiffness matrix.)

  **The 52 solver-validated decks regenerate byte-identical.** The bending,
  thickness-direction, orthotropy and ply-order campaign below was measured at
  the first cut of this batch; every deck of it re-converts to a `_0000.rad` and
  `_0001.rad` with the SAME SHA-256 afterwards, so none of those numbers moved.

  Tests 2956 → 3061 (+105), subtests 888 (unchanged); `ruff check .` clean.

- **The damping batch: `*DAMPING_PART_MASS`/`_SET` → a part-scoped `/DAMP`,
  `*DAMPING_FREQUENCY_RANGE`/`_DEFORM` → `/DAMP/FREQUENCY_RANGE`, and
  `*DAMPING_RELATIVE` → `/DAMP/VREL` resolved-and-reported rather than
  emitted.** All three previously landed in `skipped_keywords` with **no warning
  at all** — the same silent class as the `*LOAD_BODY_R*` defect of the previous
  batch. Measured live before the change: `8.1.plate_vibem.k` reported
  `Skipped (unsupported) keywords (3): *DAMPING_FREQUENCY_RANGE, …` and
  `11.3.sqt_iga_s.k` reported `*DAMPING_PART_MASS`, neither with a single
  damping warning. Six new dispatch keys (`_SET`, `_DEFORM`, `_DEFORM_DMIG`
  each need their own row — `parser._split_keyword` strips only a trailing
  `_ID`/`_TITLE`, so `_DEFORM` does **not** fall back to the base keyword).

  1. **The version gate was measured, not assumed — and it came out DIFFERENT
     for the two new cards.** `radioss2022/data_hierarchy.cfg:2545-2571`
     registers only `DAMP` and `DAMP_INTER` under `DAMPING`; `Damp_Vrel.cfg`
     first exists in `radioss2023` (reduced) / `radioss2024` (full) and
     `Damp_freq_range.cfg` in `radioss2025`. k2rad writes `/BEGIN 2022`. Twin
     decks differing only in the `/BEGIN` line, on `starter_win64` 2026-05-20:

     ```
     /BEGIN 2025   (both cards, 0 ERROR, no 100211/100213)
       RAYLEIGH DAMPING WITH RELATIVE VELOCITIES
         DAMPING FUNCTION ID     91002
         MASS DAMPING COEFFICIENT IN X/Y/Z-DIRECTION  3.0E-02 / 3.0E-02 / 3.0E-02
         DAMPING FREQUENCY       12.5
       DAMPING OVER FREQUENCY RANGE
         PART GROUP ID 91004 / RATIO 2.0E-02 / LOW 10.0 / HIGH 200.0

     /BEGIN 2022
       WARNING 100211  Unsupported option /DAMP/VREL in format < 2023
       WARNING 100213  unsupported field exists at the end of line
                       -- LINE: 12.5         0     91002                   1
       WARNING 100211  Unsupported option /DAMP/FREQUENCY_RANGE in format < 2025
       RAYLEIGH DAMPING WITH RELATIVE VELOCITIES
         DAMPING FUNCTION ID     0            <-- LOST
         MASS DAMPING COEFFICIENT IN X/Y/Z-DIRECTION  3.0E-02 / 12.5 / 3.0E-02
                                                                ^^^^ the Freq value
         DAMPING FREQUENCY       0.0          <-- LOST
       DAMPING OVER FREQUENCY RANGE
         PART GROUP ID 91004 / RATIO 2.0E-02 / LOW 10.0 / HIGH 200.0   <-- CORRECT
     ```

     So `/DAMP/FREQUENCY_RANGE` **is emitted**: its cfg carries exactly one
     `FORMAT` block (radioss2025), there is no older layout to fall back to, and
     every field reads identically at 2022 and 2025 — the 100211 is advisory and
     is restated to the user. `/DAMP/VREL` is **not**: at 2022 the reader falls
     back to the reduced radioss2023 layout, swallows the
     `Freq RbodyID FuncID Xscale` card as the `Alpha_y` row, and leaves `Freq`
     at 0 — which switches the engine from `damp_a = Alpha_x*4*pi*freq` to
     `damp_a = Alpha_x/dt_initial` (`damping_vref_compute_dampa.F90`), about
     1e12 off at a dt of 1e-6, on top of an `Alpha_y` 400× too large. Emitting a
     card that reads as something else is what `_resolve_contact_interior`
     already refused to do, so this follows that precedent: resolve everything,
     name every resolved id in the warning so the card can be pasted into a
     `/BEGIN 2024` deck by hand, emit nothing, and record the keyword in
     `recognized_not_emitted`.

  2. **The dyna2rad `FuncID` defect is deliberately NOT reproduced.**
     `convertdampings.cxx:305` routes `*DAMPING_RELATIVE`'s **curve** id through
     `GetRadiossSetIdFromLsdSet(lcid, "*SET_PART")` — the part-SET map, written
     with the SET entity type — a copy-paste of the `PSID` line at `:299`. Since
     `dyna2rad.cxx:139-150` only remaps when one number is used by two or more
     `*SET_*` families, this misfires exactly when the curve id collides with a
     multiply-used part-set id, and then either points at the wrong `/FUNCT`
     (silent) or at none (starter **ERROR 3049**, run aborts) — the latter made
     likelier by `convertsets.cxx:149-166` renumbering duplicate sets to
     `max+1`. k2rad resolves `LCID` against `state.curves`, the
     `*DEFINE_CURVE` → `/FUNCT` table, and never against `part_sets`. Both
     failure shapes have their own test: a curve id matching no set, and one
     numerically colliding with a part-set id (there the deck also proves the
     curve is really emitted as `/FUNCT/3` while `*SET_PART 3` resolves to its
     own parts). Two further d2r defects are also avoided — `RbodyID` is looked
     up from `PIDRB`'s **own** part (d2r walks `PIDRB → MID → conversion log`,
     so parts sharing one `*MAT_RIGID` give a last-one-wins wrong body), and
     `PIDRB=0` / a non-rigid `PIDRB` are guarded instead of dereferenced. Three
     further traps ride in the same warning: `Alpha_*` must be **1.0** when a
     curve is given (LS-DYNA's `LCID` *replaces* `CDAMP`, Radioss's `FuncID`
     *multiplies* `Alpha_x` — copying both double-counts); `Alpha2_*` is read
     only by `damping_vref_rby.F90` inside `if (id_rby > 0)`, so `DV2` without a
     usable rigid body is zeroed and said so; and `Xscale` is **dead** — the
     starter stores it in `DAMPR(27)` and no engine file reads that slot back,
     so abscissa scaling has to be baked into the curve's own X values.
     `FREQ = 0` gets its own warning: LS-DYNA reads `CDAMP` as the damping
     fraction *at* `FREQ` so the card asks for nothing, while Radioss's
     documented `alpha = CDAMP*dt*Func(t)` disagrees with its own source, which
     *divides* by the initial timestep (`damp_a = Alpha_x/dt_initial`) — about
     1e12 apart at a dt of 1e-6.

  3. **`PSID = 0` on `*DAMPING_FREQUENCY_RANGE` is the opposite of
     `grpart_ID = 0`.** LS-DYNA: "the damping is applied to all parts **except
     those referred to by other** `*DAMPING_FREQUENCY_RANGE` cards". Radioss:
     `hm_read_damp.F:299-307` tags `DAMP_RANGE_PART(J) = I` for **every** part
     with no exclusion, and by plain overwrite — so a single `grpart_ID = 0`
     card silently overrides every earlier one. k2rad emits `grpart_ID = 0` only
     when no other card claims a part (there the two agree exactly) and an
     explicit complement `/GRPART/PART` otherwise; a second `PSID=0` card, and
     any part claimed twice, each get their own last-one-wins warning.

  4. **The Radioss card *is* LS-DYNA's `_DEFORM` behaviour, so the plain option
     is the approximation — not the other way round.** Damping enters as a
     Maxwell/Prony viscous stress inside the material law
     (`damping_range_{shell,shell_mom,solid}.F90`, reached from `mulawc.F90:1974`
     and `viscmain.F`, gated by the static `IPARG(93)`), never as a nodal force:
     rigid-body motion is not damped and natural frequencies shift **up**.
     `_DEFORM` therefore converts clean and silent; the blank option gets the
     loud warning. dyna2rad cannot even tell them apart — `data_hierarchy.cfg`
     folds `_DEFORM` into the base subtype as a `USER_NAMES` alias and
     `ConvertDampingFrequencyRange` never calls `GetKeyword()`.

  5. **`FLOW`/`FHIGH` are validated because the starter validates neither.** The
     `KEY(1:4)=='FREQ'` branch reads and proceeds; with `FLOW = 0` the
     three-Maxwell fit of `damping_range_compute_param.F90` collocates at
     `f_mid = sqrt(FLOW*FHIGH) = 0`, its 3×3 matrix fills with `0/0`, and NaN
     `alpha`/`tau` propagate into every element of the group. `FLOW <= 0`,
     `FHIGH <= FLOW` and `CDAMP <= 0` are dropped with the reason. `IFLG=0` (the
     LS-DYNA iterative default, ~1% error) is warned about because Radioss
     implements only the one-shot 3-point collocation, i.e. the `IFLG=1`
     analogue: about −8%…0% at `CDAMP=0.01`, −26%…−4% at 0.05. `PIDREL`,
     `ICARD2`/`CDAMPV`/`IPWP` and the `_DEFORM_DMIG` superelement variant have
     no counterpart and say so. `Tstart`/`Tstop` are written as the neutral
     0 / 1e30 — the starter stores and echoes them and **nothing applies them**
     for this type (`damping.F:120-127` and `DAMPING44` both guard on
     `FL_FREQ_RANGE == 0`, and the material-law path has no time argument).

  6. **`*DAMPING_PART_MASS` is a deliberate super-set: dyna2rad has no converter
     for it at all.** `convertdampings.cxx` runs exactly four converters (`:38-44`)
     and its only `SelectionRead` calls are at `:51/167/247/321` — the card
     parses cleanly into its model and is then silently dropped. k2rad maps it to
     plain `/DAMP`, which needs no version bump (readable since radioss42):
     `Alpha = SF · curve`, both sides applying `F = -α·m·v`. The card has **no
     constant-value column** — unlike `*DAMPING_GLOBAL`'s `VALDMP`, the constant
     is read entirely off `LCID` — so `LCID=0` is a dropped card with that
     reason, and since plain `/DAMP` has no function slot (`/DAMP/FUNCT` is a
     radioss2026 keyword) a time-varying curve is reduced to its first ordinate
     with a warning. That reduction is *exact* for the flat curves these decks
     carry — the corpus case `11.3.sqt_iga_s.k` is `(0, 200) (0.01, 200)` — so
     the warning fires only when the curve really varies. `FLAG=1` maps
     `STX..SRZ` onto the Format-2 per-DOF rows (`α_i = SF·curve·ST_i`), with
     `FLAG=1`-and-all-six-zero read as "uniform" rather than "no damping". `SF`
     is one of the rare LS-DYNA fields whose default is **not** zero, so it is
     read through `_ffield` — `to_float("")` would have silently zeroed the
     damping.

  7. **Overlap is reported on both mechanisms, and the check is on NODES.** Two
     `/DAMP` cards covering one node compound their α terms harmlessly but share
     a single per-node history buffer `DAMP(1:6,I)`: `damping.F:145` stores
     `A()` into it and the next card overwrites, so the first card's `β` term
     reads a foreign acceleration from the following cycle on (2022 Reference
     Guide p.130 comment 4). The clash is therefore nodal, not per-part — two
     conformally meshed parts share the nodes along their common edge even when
     the part lists are disjoint, which a part-id intersection would miss — so
     the part-mass grnod is intersected with the node group of the
     `*DAMPING_PART_STIFFNESS` `/DAMP`, and only when that card actually carries
     a non-zero `β`. Separately, a deck holding both `*DAMPING_PART_MASS` and
     `*DAMPING_GLOBAL` is warned — LS-DYNA forbids the combination and Radioss
     would apply both additively.

  8. **`*INCLUDE_TRANSFORM` offsets could not use a flat `data` spec.**
     `_rewrite_line` decides what is an id with `to_int(tok) > 0` and `to_int`
     goes through `float`, so a damping scale factor of `1.5` reads back as the
     id `1` and would be rewritten to `1 + IDPOFF` — a scale factor silently
     turned into a part number. `*DAMPING_PART_MASS` therefore gets a
     stride-walking callable (the `_off_mat_196` situation) that offsets
     `PID`(`p`)/`PSID`(`s`) and `LCID`(`f`) on each card 1 and steps over the
     `FLAG=1` Scale Factor Card. `*DAMPING_FREQUENCY_RANGE` offsets `PSID`(`s`)
     and `PIDREL`(`p`), `*DAMPING_RELATIVE` offsets `PIDRB`(`p`), `PSID`(`s`) and
     `LCID`(`f`). Every one of the six spellings has a row, so none can draw the
     "id offsets are NOT applied" warning.

  Scoping runs in the **writer**, not the handler, so `*SET_PART_ADD` sets —
  flattened by `_flatten_part_set_adds` post-parse — resolve for all three
  keywords. Not in scope and still unhandled: `*DAMPING_PART_STIFFNESS_SET`
  (mapping it to the existing handler would silently read its `PSID` as a `PID`,
  which is worse than the current skip), and `*DAMPING_GLOBAL`'s per-DOF
  `STX..SRZ`, which stay warned-and-dropped.

  Regression evidence: starter-validated on `starter_win64`. A converted deck
  carrying both new emitting keywords gives **0 ERROR**, exactly one advisory
  `WARNING 100211`, and the echo `NODE GROUP ID 90001 / ALPHA 200.0 /
  BETA 0.0` for the part-mass card (`SF=1.0` × the flat curve's 200.0) plus
  `PART GROUP ID 90003 / DAMPING RATIO 2.0E-02 / LOWEST 10.0 / HIGHEST 200.0`
  for the frequency-range card. The Format-2 per-DOF path was run separately —
  `SF=2.0`, a flat 200.0 curve and `STX..SRZ = 1.0 0.5 0.0 0.25 0.1 2.0` echo
  back as **0 ERROR** and

  ```
  ALPHA IN X-DIRECTION.  400.0     BETA IN X-DIRECTION.  0.0
  ALPHA IN Y-DIRECTION.  200.0     BETA IN Y-DIRECTION.  0.0
  ALPHA IN Z-DIRECTION.    0.0     BETA IN Z-DIRECTION.  0.0
  ALPHA IN RX-DIRECTION. 100.0     BETA IN RX-DIRECTION. 0.0
  ALPHA IN RY-DIRECTION.  40.0     BETA IN RY-DIRECTION. 0.0
  ALPHA IN RZ-DIRECTION. 800.0     BETA IN RZ-DIRECTION. 0.0
  ```

  i.e. exactly `2.0 × 200.0 × ST_i` on all six DOFs, with the per-direction echo
  confirming the starter took the Format-2 read from the presence of the five
  extra cards alone. The first of those decks was then run through the **engine**
  as well — 89 975 cycles to `NORMAL TERMINATION` with both new cards live, so
  the radioss2025 `/DAMP/FREQUENCY_RANGE` under `/BEGIN 2022` is accepted by the
  engine and not only by the starter. Corpus sweep over the full 201-deck roster
  (repo tree 73 + `E:\openradioss_run\Ryan_Lee_Examples` 127 +
  `ls-dyna_example` 1), master `62a53e8` vs this commit, SHA-256 over BOTH the
  `_0000.rad` and the `_0001.rad`: **201/201 converted on each side, 0 hash
  deltas, 0 conversion errors, 0 error deltas.** None of those decks carries any
  of the three new keywords, and the three new sections return `[]` before
  touching `state.next_id()`, so no auto id shifts — pinned by its own test, and
  the five golden fixtures stay byte-identical. The four dynaexamples decks that DO carry them were converted
  end-to-end: the three NVH plates
  (`8.1.plate_vibem` / `8.2.plate_rayleigh` / `8.3.plate_kirchhoff`, all
  `CDAMP=0.01 FLOW=30 FHIGH=300 PSID=0`) now emit
  `/DAMP/FREQUENCY_RANGE` with `grpart_ID = 0` instead of landing in
  `skipped_keywords`. `8.1.plate_vibem.k` was taken all the way to the starter
  as a production-deck check — **0 ERROR**, one advisory `WARNING 100211`, and

  ```
  DAMPING OVER FREQUENCY RANGE
    PART GROUP ID . . . .        0
    DAMPING RATIO . . . .        1.0000000000000E-02
    LOWEST FREQUENCY  . .        30.00000000000
    HIGHEST FREQUENCY . .        300.0000000000
  ```

  i.e. the LS-DYNA card read straight back out. `11.3.sqt_iga_s.k` — an IGA deck whose
  `*ELEMENT_SHELL_NURBS_PATCH` mesh k2rad drops whole — now reports its
  `*DAMPING_PART_MASS` as "*SET_PART … resolved to no existing part"
  instead of silently vanishing.

  **Review round.** Nine defects found by an adversarial re-read of the batch
  and fixed on top of it; each was reproduced before being touched.

  - **A blank Scale Factor Card swallowed the following card set.** `FLAG = 1`
    plus an all-blank card 2 is legal LS-DYNA — every `STX..SRZ` defaults to
    0.0 (Vol I R16 p.15-10) — but the parser keeps a blank card as a `""`
    placeholder and `_damping_data_rows` filters placeholders out, so "the next
    row" was the *following* card 1. Measured: `1 201 1.0 1 / <blank> /
    2 202 3.0` parsed to ONE entry with `STX=2, STY=202, STZ=3.0`, i.e. part 1
    damped on Y by a part number and part 2 lost, no warning. The card-2 slot is
    now claimed by RAW contiguity. `assembly._off_damping_part_mass_common`
    walked the same filtered list and desynced identically, so the offsetter got
    the same fix — otherwise an `*INCLUDE_TRANSFORM`'d deck left the swallowed
    card's PID/LCID un-offset.
  - **The offsetter and the handler disagreed about which line is card 1.**
    `DAMPING_FREQUENCY_RANGE[_DEFORM[_DMIG]]` and `DAMPING_RELATIVE` had flat
    `{"cards": {0: …}}` specs addressing `raw[_title_offset + 0]` while their
    handlers skip blank placeholders. Measured through `_offset_block` with one
    blank line after the keyword: `psid 4`, `pidrel 9`, `pidrb 7`, `lcid 201`
    all came through **un-offset**, with no "id offsets are NOT applied"
    warning. All four are now callables using the handler's own rule. The
    `_DEFORM_DMIG` row also stopped offsetting field 3 with the SET bucket:
    there `PSID` is an `*ELEMENT_DIRECT_MATRIX_INPUT` superelement id, not a
    `*SET_PART` id (Vol I R16 p.15-3).
  - **A zero-COEF part still rides in the beta-bearing `/DAMP`.** The node
    overlap check filtered `state.damping_part_stiffness` on `coef != 0.0`, but
    `_make_damping` puts *every* stiffness pid in its `/GRNOD` and writes
    `beta = max(coefs)` on it. Measured on node-disjoint parts 1 (COEF 0.0) and
    2 (1e-7) with `*DAMPING_PART_MASS` on part 1: `/GRNOD` 1-8 driving
    `beta=1E-07`, part-mass `/DAMP` on 1-4, and **no warning** — precisely the
    shared-history-buffer corruption it exists to catch. The check now uses the
    pid set `_make_damping` actually uses and gates on `max(coefs) != 0.0`.
  - **A stacked second card set vanished in silence** on both
    `*DAMPING_FREQUENCY_RANGE` and `*DAMPING_RELATIVE` (both read `rows[0]`
    only). For FREQUENCY_RANGE that also corrupted the `PSID=0` route, since the
    dropped card's parts never entered `claimed`. Whether LS-DYNA reads a
    stacked set is unresolved — both HM cfgs and the manual show one card set —
    so the extra lines are still not *interpreted*, but they are now quoted back
    in a warning instead of dropped.
  - **The element-scope caveat only fired for the blank option.** LS-DYNA's
    `_DEFORM` covers "solid, beam, shell, thick shell and discrete elements"
    (Vol I R16 Remark 4); Radioss reaches only `damping_range_shell` /
    `_shell_mom` / `_solid.F90`. So under the option advertised as the clean 1:1
    a beam-only or tshell-only part lost **all** its damping without a word. The
    caveat moved out of the `if not dfr.deform` branch and became scope-aware:
    it names the parts in scope that carry no shell or solid element.
  - **An alpha=0 + beta=0 `/DAMP` is no longer emitted.** The crash fix above
    left the deck with an inert card plus a `/GRNOD` over every deformable node
    in the model. `COEF EQ.0.0` is documented "Inactive" (p.15-12), so the card
    is dropped with a warning — the rule `_make_damping_part_mass` already
    applied to `SF × curve == 0`.

    This is the **one change in the review round that moves real corpus decks**,
    and not through the `*DAMPING_PART_STIFFNESS` door it was written for: four
    r14 decks (`beam.free`, `control_damping.beam`,
    `control_adaptive.cup-draw`, `integration_shell.lobotto.beam`) carry a
    `*DAMPING_GLOBAL` with `VALDMP = 0.0`, three of them with a non-zero `LCID`
    — a curve `_make_damping` has never read (`handle_damping_global` already
    warns "lcid=N … not supported; using constant valdmp=0.0"). They were
    emitting the inert card. The warning is therefore case-aware and names
    which door was taken, so a `VALDMP=0 + LCID` deck is not mis-reported as an
    all-zero-COEF one. Verified per deck: the whole `.rad` delta is the removed
    `/GRNOD` + `/DAMP` pair and the auto-ids after it shifting down by 2,
    `_0001.rad` byte-identical, and the starter gives the **same 0 ERROR / same
    warning count before and after** on all of them — so the renumbering
    dangles nothing. `dps_zero.k` now converts to a `.rad` whose SHA-256 is
    **identical to the same mesh carrying no damping card at all**, which is
    the cleanest statement of what was dropped.
  - **`_make_damping`'s `/GRNOD` drew from the unguarded `next_id()`**
    (pre-existing on master). Measured: a user `*SET_NODE 90001` plus
    `*DAMPING_GLOBAL` emitted `/GRNOD/NODE/90001` **twice** → starter `ERROR 79
    DUPLICATE ID / IN NODE GROUP DEFINITION`, which stops the whole model. Now
    `next_grnod_id()`, like the new part-mass path; a no-op on any deck without
    such a set.
  - **`PID = 0` on `*DAMPING_PART_MASS`** was skipped silently unless the whole
    block produced nothing; it is now reported per card. An **empty `*SET_PART`**
    was reported as "part(s) `[]` carry no deformable shell or solid nodes",
    naming the wrong cause; it gets the dedicated branch
    `_make_damping_frequency_range` already had.
  - **Two documentation defects.** `_DAMP_CARD1_HDR`'s docstring claimed to be
    ``radioss110/DAMP/Damp.cfg``'s `COMMENT` string; that one is 100 chars with
    every label right-aligned on its field, this one is 102 and sits two columns
    off. The value is inherited verbatim from master's inline literal and is
    kept byte-for-byte (re-aligning a `#` comment the starter never reads would
    move the hash of every `/DAMP`-bearing deck), so the provenance claim was
    corrected instead and the two duplicate literals in `_make_damping` now use
    the constant. And the version-gate advice "bump `/BEGIN` to 2025 to silence
    the warning" now says what that costs: `WARNING 100217 "card is missing"` on
    the other cards k2rad writes in the 2022 layout — measured harmless (0
    errors, every field still read back identically), but it reads like a
    regression to anyone who follows the advice without being told.

  Also settled from the manual rather than guessed: the bare
  `*DAMPING_FREQUENCY_RANGE_DMIG` spelling (OPTION2 without OPTION1) has no
  dispatch row because **it does not exist** — "OPTION2 is available only when
  OPTION1 is DEFORM" (Vol I R16 p.15-2) — and the `HANDLERS` comment now says
  so, rather than leaving the gap looking accidental.

  **Re-sweep after the review round**, 474 decks (the 462-deck roster above
  plus the 12 solver-validation decks), `c1dee97` vs the fixed tree, SHA-256
  over both `_0000.rad` and `_0001.rad`: **469/474 byte-identical, 0 conversion
  errors either side, 0 skip deltas, 0 `recognized_not_emitted` deltas.** The 5
  movers are `dps_zero.k` and the four `VALDMP=0` decks above — every one of
  them the inert-card change, none of them a damping card that was doing
  anything. Against master `62a53e8` the movers are the 14 decks that carry a
  damping keyword at all, and `dps_zero.k` additionally goes from an
  `AttributeError` crash to a clean conversion.

  **11 of the 12 solver-validation decks are byte-identical to the commit the
  physics campaign ran** — every `fr_*`, `vfr_trans` and `vrel_*` deck behind
  the decay, momentum-conservation and LCID-switching numbers — so those
  measurements carry over verbatim rather than needing a re-run. The twelfth is
  `dps_zero.k`, which was the crash reproducer, not a physics deck.

  Tests 2850 → 2956 (+106), subtests 860 → 888; `ruff check .` clean.

- **Rigid-body inertia and load distribution: `*PART_INERTIA` (and every legal
  `*PART` option stacking) → `/RBODY` `Mass`/`Jxx..Jxz` with `ICoG=4`,
  `*CONSTRAINED_NODAL_RIGID_BODY_INERTIA` → the same transfer on the CNRB path,
  `*PART_CONTACT` `OPTT` → the `/PART` `Thick` column, and
  `*CONSTRAINED_INTERPOLATION[_LOCAL]` → `/RBE3` + one `/GRNOD/NODE` per
  weight/DOF group.** Before this batch `*PART_INERTIA` was not a dispatch key at
  all, and that was not a soft failure: the block landed in `skipped_keywords`,
  the part was never registered, and because `_make_parts_and_elements` emits
  elements inside the `state.parts` loop, **every element on the part was
  dropped**. Measured on a one-solid deck:

  ```
  SKIPPED: ['PART_INERTIA']
  WARNINGS:
   * MESH LOSS: 1 element(s) reference 1 part id(s) that no *PART card defines …
  /PART cards in starter: ['/PART/2']      <- the rigid part is simply gone
  ```

  The naive fix is worse. Aliasing `HANDLERS["PART_INERTIA"] = handle_part` makes
  the old stride-of-2 (title, data) walk read card 3 as a title and card 4 as a
  data card, which registered a phantom `/PART/4321` from `IXX = 4321.0`, with
  `secid=0`, `mid=0`, a coordinate card for a title — and no warning. So the walk
  is now driven by the option SET at the Card-Summary order. Eight findings pin
  the batch:

  **1. The product-of-inertia sign — VERBATIM, do not negate.** Both sides define
  the off-diagonals as the inertia *tensor* component, i.e. minus the product of
  inertia. LS-DYNA `*PART` Remark 4 (Vol I R17 p.37-14), verbatim: *"Note that the
  off-diagonal terms of the inertia tensor are opposite in sign from the products
  of inertia."* Radioss matches — `starter/…/rbody/inirby.F:154-160` packs the 3×3
  with the user values inserted **positively** on the off-diagonals:

  ```fortran
  RBY(2,NRB)=RBY(5,NRB)   ! (1,2) <- Jxy
  RBY(4,NRB)=RBY(5,NRB)   ! (2,1) <- Jxy
  RBY(3,NRB)=RBY(7,NRB)   ! (1,3) <- Jxz     [RBY(6) untouched -> (2,3) = Jyz]
  ```

  while `:331-339` accumulates the mesh contribution into the SAME slots with a
  minus:

  ```fortran
  RBY(2,NRB)=RBY(2,NRB)-XY*XMG
  RBY(3,NRB)=RBY(3,NRB)-XZ*XMG
  RBY(6,NRB)=RBY(6,NRB)-YZ*XMG
  ```

  Two quantities summed into one tensor entry must share one convention, so
  `Jxy = IXY` exactly. The only transformation is the FIELD ORDER: LS-DYNA card 4
  is `IXX IXY IXZ IYY IYZ IZZ` on one line, Radioss is `Jxx Jyy Jzz` then
  `Jxy Jyz Jxz` on two — and the second line is **not** `Jxy Jxz Jyz`. Pinned
  empirically: a body fed `Jxx=100 Jyy=200 Jzz=250 / Jxy=10 Jyz=0 Jxz=0` echoed
  `ADDED INERTIA 100.0 200.0 250.0 10.00 0.000 0.000`, printed in reader-storage
  order `Mass, Jxx, Jyy, Jzz, Jxy, Jyz, Jxz` (`hm_read_rbody.F:553`). A negation
  is invisible in the `.rad`; the only hint it ever leaves is starter
  `WARNING 542` "NONPHYSICAL INERTIA".

  **2. `ICoG = 4`, and only 4.** It is the sole flag that means "defined rather
  than calculated from the finite element mesh". `inirby.F:266-282` + the gate at
  `:322`:

  ```fortran
        ELSEIF(ICDG==4)THEN
          DO J=1,3 ; XG(J)=X(J,M) ; ENDDO      ! COG = the main node, unmoved
          MASRB=MS(M)                          ! secondary mesh mass IGNORED
        ENDIF
  …
        IF(ICDG<=3)THEN                        ! <- 4 skips ALL inertia transport
  ```

  Measured on five otherwise-identical bodies (probe `pinE`; main node at
  x = n·100, secondaries centred 20 further out, user `Mass` 1e-6, mesh mass
  7.86e-7):

  | ICoG | starter `NEW X` | starter `NEW MASS` |
  |---|---|---|
  | 1 | 108.8018 | 1.786e-6 (combined centroid; mesh mass added) |
  | 2 | 220.0000 | 1.786e-6 (secondary centroid; main node MOVED) |
  | 3 | 300.0000 | 1.786e-6 (main node kept; mesh mass still added) |
  | **4** | **400.0000** | **1.000e-6** (main node kept; mesh mass DROPPED) |
  | blank | 508.8018 | 1.786e-6 (= 1, and `Ispher` echoes 2) |

  Any value but 4 double-counts the mesh, and 1/2 additionally move the COG off
  the `XC/YC/ZC` the card states. Residual to respect: `inirby.F:146,166-169`
  ALWAYS adds the main node's own `MS(M)`/`IN(M)`, so every `_INERTIA` main node
  k2rad writes is element-free (a `NODEID` that carries elements is copied to a
  synthesized free node at the same coordinates — reusing it would also be
  `WARNING 448`, or the fatal `ERROR 1066` under `--ams`). For the same reason
  `TM` **supersedes** any `*ELEMENT_MASS`/`_PART` on the body rather than being
  added to it, with a warning naming both numbers.

  **3. `IRCS = 1` goes through `/RBODY Skew_ID`, and that is exact.**
  `inirby.F:161-164` applies `CALL CHBAS(SKEW(1,NOSKEW), RBY(1,NRB))` to the
  packed 3×3 before any mesh contribution, and `chbas.F:29-67` computes
  `M_out = A·M_in·Aᵀ` (its own header comment says `Aᵀ·M·A` and is wrong relative
  to the code) with `A` filled column-major from `SKEW`, i.e. `A = [X′|Y′|Z′]` = R
  (local→global). So `J_global = R·J_local·Rᵀ`, which is LS-DYNA's `IRCS=1`
  definition. **Validated end to end**: a deck stating `J_local = diag(20,25,30)`
  in a frame with X′=Z, Y′=X, Z′=Y came back from the starter as

  ```
       RIGID BODY ID         19 rigid brick local frame
            SKEW NUMBER                                  90001
            CENTER OF MASS FLAG                              4
            NEW X,Y,Z              22.00000      2.000000      2.000000
            NEW MASS               7.250000
            NEW INERTIA xx yy zz   25.00000      30.00000      20.00000
  ```

  — the hand-computed `R J Rᵀ` — with **NORMAL TERMINATION, 0 ERROR, 0 WARNING**.
  Card-6 `CID` binds the converted `/SKEW` 1:1; two card-6 vectors synthesize a
  `/SKEW/FIX` (`z′ = x_L × v_ip`, `y′ = z′ × x_L`, written on the **Y′ and Z′**
  lines after the mandatory ORIGIN line — a three-data-line card; omitting the
  origin is `WARNING 100217` and silently shifts Y′ into it). A dangling `CID`
  would be `ERROR 137`, so it is checked and warned instead. `IRCS = 0` binds
  nothing — a deliberate divergence from dyna2rad, whose CNRB path binds card-1
  `CID` as `Skew_ID` when `IRCS == 0` (`convertrigids.cxx:126-127`) and so rotates
  a GLOBAL tensor (measured: `4.11 5.22 6.33` → `5.22 6.33 4.11`).

  **4. Card-5 `VTX..VRZ` on the main node alone is exact.** `/INIVEL/ROT` has no
  axis and no origin — `hm_read_inivel.F:535-541` writes the three components
  straight into the nodal `VR` — and `inirby.F` then propagates the main node's
  `V`/`VR` to the secondaries as `V(:,N) = V(:,M) + ω × (X_N − X_M)`. With
  `ICoG=4` that origin IS the stated centre of mass, so a one-node group
  reproduces "velocity about the COG" with no correction term. `/INIVEL/AXIS` (the
  only variant with an origin) is deliberately not used: it needs a `/FRAME` and
  "cannot be used when /INIVEL/TRA or /INIVEL/ROT is applied on the same node".
  `IRODDL > 0` is required for the `VR` write and `contrl.F:1053` includes
  `NRBODY` in that `MIN()`, so any `/RBODY` guarantees it. An
  `*INITIAL_VELOCITY_RIGID_BODY` on the same body supersedes card 5 (*PART Remark
  5: "The \*INITIAL_VELOCITY card may overwrite the initial velocity of the rigid
  body") and the card-5 values are dropped with a warning rather than written to
  be silently overwritten — Radioss `/INIVEL` assigns, so two cards on one node
  are decided by order, not summed.

  **5. `/RBE3` is written from scratch, not mirrored from dyna2rad.** Its output
  is non-functional in the shipped build — a minimal four-node deck produced
  `NODE ID=0 DOES NOT EXIST` → `ERROR 78` → `ERROR 760`, plus
  `1.0 1.0 1.0 0.0 0.0 0.0` for every node whatever the deck said. Three
  independent defects: `DNID` resolves through `GetEntityHandle` against the cfg
  object name `NODE` while the LS-DYNA view keys nodes as `*NODE`, so the handle
  is always invalid and `Node_IDr` is written 0; the per-set weights and
  independent `Trarot_Mi` are written as SCALARS into attributes the cfg declares
  `ARRAY[nset]` (and the weight list is an `sdiIntList` against a `FLOAT` array,
  so it comes back empty and the `SetValue` never runs); and every independent
  node is forced into ONE set. k2rad instead groups the rows on
  `(IDOF, weight, CIDI)` and emits one set + one `/GRNOD/NODE` per group.
  Validated at `Ipri=5` on a deck with `IDOF` 123/1234/12345/3 and weights
  2/3/4/5:

  ```
       WEIGHTING FACTORS OF INDEPENDENT NODES
           NODE  SKEW    DIR_TRA_1  DIR_TRA_2  DIR_TRA_3  DIR_ROT_1  DIR_ROT_2  DIR_ROT_3
              5     0          2.0        2.0        2.0        0.0        0.0        0.0
              6     0          3.0        3.0        3.0        3.0        0.0        0.0
              7     0          4.0        4.0        4.0        4.0        4.0        0.0
              8     0          0.0        0.0        5.0        0.0        0.0        0.0
  ```

  — exactly the deck, on a run with 0 ERROR.

  **6. The `Trarot` sub-columns are positional, and getting them wrong is
  silent.** `radioss110/RBODY/rbe3.cfg` writes
  `CARD("%10d   %1d%1d%1d %1d%1d%1d%10d%10d", …)`: inside the 10-wide field, three
  literal blanks, TxTyTz, one literal blank, RxRyRz. Corroborated by the Reference
  Guide 2022 p.1957 sub-column table, whose TX/TY/TZ glyphs sit in grid cells
  4/5/6 and whose θ glyphs sit in 8/9/10 with cell 7 empty. Negative control
  (probe `pinD`): the six digits right-aligned as `      111111` produced
  `WARNING 100213/100214/100217`, `REFERENCE DOF(Trarot) 000 111` — the three
  translations silently lost — and the run still **TERMINATED NORMALLY**. Also
  pinned: a blank `Trarot_Mi` does NOT mean all six DOFs, contradicting the
  Reference Guide's own "Default (blank or 6 zeros), set on all DOF" — the reader
  sets only the translations (`hm_read_rbe3.F:244-248`), confirmed empirically. So
  k2rad writes all six digits explicitly and leans on neither side's default.
  `I_modif = 2` (modification forbidden) keeps the deck's weights exactly; it is
  the one value the starter leaves alone (`:322` `IF (IMODIF/=2) IRBE3(8,I)=4`,
  and the floor-raising `WARNING 757` pass at `:516` is likewise gated on it).
  `Iform` is **not** emitted — it is radioss2026-only; at 2022 the reader gets 0
  and `SELECT CASE(IFORM) CASE(0,1)` maps it to 1, which is the 2022 behaviour.

  **7. `*PART_CONTACT` `OPTT` → the `/PART` card's 4th field, cols 31-50.**
  `hm_read_part.F:193-198` stores it raw as `THK_PART(I)`, and `i7sti3.F:226-238`
  picks it as the first of three levels:

  ```fortran
        IF ( THK_PART(IP) /= ZERO .AND. IINTTHICK == 0) THEN
          DX=HALF*THK_PART(IP)
        ELSEIF ( THK(I)  /= ZERO .AND. IINTTHICK == 0) THEN
          DX=HALF*THK(I)
  ```

  The test is `/= ZERO`, so a written `0.0` is indistinguishable from blank — a
  literal zero contact thickness is not expressible through `/PART` at all — and
  suppressing the field keeps every deck without the option byte-identical.
  Read-back assertion from the starter: `VIRT. THICKN: 0.5000000000000` on the
  part carrying `OPTT`, `0.000000000000` on the one without. `SFT` is deliberately
  NOT folded into `Thick` (it scales the true thickness; `Thick` replaces it), and
  `FS/FD/DC/VC`, `SSF`, `CPARM8` are warn-dropped — dyna2rad drops all seven
  without a word (`convertparts.cxx:133-138` reads `OPTT` and nothing else; a grep
  over its source finds zero references to the rest).

  **8. Option spellings are GENERATED, and positional consumption is absolute.**
  "Options 1, 2, 3, 4, 5, and 6 may be specified in any order on the \*PART card"
  (Vol I R17 p.37-2) makes **3588** legal `*PART` spellings and **326**
  `*CONSTRAINED_NODAL_RIGID_BODY` ones; the CARD order stays the fixed
  Card-Summary one whichever way the keyword is spelled. Altair's own reader
  matches the whole suffix against a closed list of 12 (`_CONTACT_INERTIA` falls
  into the final `else` and is mis-parsed), so both grammars are generated from
  one function each and `_OFFSET_SPECS` in `assembly.py` is generated from the
  SAME functions — the #116 lesson, where a hand-written rigid-wall list had
  already fallen three spellings behind the registry. And a blank line inside an
  option block is a card of all-DEFAULTS, never padding (the #117 lesson): card 6
  is conditional on the `IRCS` VALUE read from card 3, so a skipped blank card 3
  puts the whole rest of the block one card out of phase and on `*PART` eats the
  next part's `HEADING`. `*PART_SENSOR`/`_ADD`/`_MODES`/`_MOVE`/`_DUPLICATE`/
  `_ANNEAL`/`_STACKED_ELEMENTS` are separate keywords whose first card is not a
  heading — they are warn-skipped by name rather than parsed into phantom parts.

  **Regression evidence.** Full-deck starter validation: a combined probe
  (`*PART_INERTIA_CONTACT` + `*PART_CONTACT` + `*CONSTRAINED_NODAL_RIGID_BODY_`
  `INERTIA` + `*CONSTRAINED_INTERPOLATION`) runs **0 ERROR**, with the starter
  echoing `CENTER OF MASS FLAG 4`, `NEW X,Y,Z 22.05 2.125 0.75` (= `XC/YC/ZC`),
  `NEW MASS 7.250000` (= `TM`, the mesh mass absent), `NEW INERTIA xx yy zz
  20.0 25.0 30.0` / `xy yz zx 1.0 2.0 3.0`, the CNRB body at `0.25 0.35 0.45` with
  `31.0 35.0 40.0 / 1.0 2.0 3.0`, `VIRT. THICKN 0.5`, three `/INIVEL` and
  `RBE3_ID 500 DEPENDENT_NODE 200 REF_DOF 111 111 #IND. 4 IMODIF 2`. The
  `IRCS = 1` probe terminates **NORMAL, 0 ERROR, 0 WARNING**, and a second
  `IRCS = 1` case through a CNRB `CID2` echoed `35.0 31.0 40.0 / -1.0 3.0 -2.0`
  from a stated `31/35/40 / 1/2/3` — the hand-computed `R·J·Rᵀ` for a +90°-about-Z
  skew, again 0 ERROR. Corpus sweep over **191/191 decks** (repo tree +
  `Ryan_Lee_Examples` + `ls-dyna_example`), converted with `origin/master` and
  with this branch and compared on both `_0000.rad` and `_0001.rad`: **0 hash
  deltas, 0 warning-set deltas, 0 skip-list deltas** (the eight
  `implicit_hr-anlenkung` TET10 decks are slow enough to need their own longer
  budget and were re-run separately; they match too) — the
  corpus contains no `*PART_INERTIA`, `*PART_CONTACT`,
  `*CONSTRAINED_NODAL_RIGID_BODY_INERTIA` or `*CONSTRAINED_INTERPOLATION` at all
  (two independent passes over 618 files across the repo, `E:\openradioss_run` and
  `E:\foxcore_data`, plus a header sniff of 6804 extensionless files), so every
  new branch is gated on a spelling nothing in the corpus uses and the shared
  `/PART`, `/RBODY`, `/GRNOD` and `/INIVEL` paths are untouched. Tests
  2768 → 2828 (+60, all in the new `tests/test_rigid_inertia_rbe3.py`), subtests
  851 → 854; `ruff check .` clean.

  **Review round.** Fifteen findings from an adversarial fidelity pass, an
  independent code review and an end-to-end solver run were confirmed against the
  starter source and fixed. Two of them were the kind that ships silently:

  * `*CONSTRAINED_NODAL_RIGID_BODY` spellings with `_TITLE` in a NON-FINAL option
    position were dropped WHOLE. The generator permuted only the four data
    options, and `parser._split_keyword` recovers a further 65 spellings by
    stripping a TRAILING `_TITLE` — so 130 of the 326 legal spellings worked and
    **196 did not**. Measured on one deck: `*..._INERTIA_TITLE` → `/RBODY/205`,
    Mass 7.25, `ICoG 4`; `*..._TITLE_INERTIA` → `SKIPPED` and no rigid body
    anywhere, with nothing to notice the loss (a CNRB owns no elements). `TITLE`
    is now in the permutation (326 keys, both tables), and both the handler and
    `assembly._off_cnrb` take the title-card offset from the keyword as well as
    from `block.options`.
  * The `*PART_CONTACT` `OPTT` / `*ELEMENT_SHELL_THICKNESS` clash warning stated
    the precedence **backwards** and its remedy would have changed the physics.
    `i7sti3.F:230-238` tests `IF (THK_PART(IP) /= ZERO .AND. IINTTHICK == 0)`
    FIRST and only falls through to `THK(I)` when the part value is zero (the same
    cascade at `:248/264/275/285/494/580/750/833` and in
    `i11sti3`/`i20sti3`/`i24sti3`). Measured: an `/INTER/TYPE7` at `Igap=1` over
    `*ELEMENT_SHELL_THICKNESS 2.0` read `GAP MIN = 1.000000000000` without OPTT
    and `7.0000000000000E-03` with `OPTT=0.007` — a factor of ~143 the other way
    from what the warning claimed. A user who followed "OPTT has no effect …
    drop one of the two" would have silently restored the 1.0 gap. (The Reference
    Guide's `/PART` Comment 3 is about the shell PROPERTY thickness, level 3.)

  Two more OPTT diagnostics were added for cases where the value reaches `Thick`
  and is then never read: a **SOLID-only** part (the starter applies `THK_PART`
  in its `NUMELC`/`NUMELTG`/`NUMELT`/`NUMELP`/`NUMELR` loops only,
  `i7sti3.F:226-293` — there is no solid loop — while LS-DYNA does apply OPTT to
  solids under `SOFT = 2`, Vol I R17 p.37-11), and an interface at **`Igap = 0`**
  (on TYPE7 the whole `THK_PART` block sits inside `IF(IGAP >= 1)`,
  `i7sti3.F:222`; k2rad's plain TYPE7 is `Igap=0`). Measured live: identical
  decks with and without `OPTT = 5.0` on the 1.0 mm moving plate gave the SAME
  contact onset `0.0090042418 s`; patching only that deck's `Igap` column to 1
  moved it to `0.0070024668 s`, against `0.002000 s` predicted (+0.089 %). The
  TYPE25 route (`Igap=2`) is live as shipped: `0.0090043144 → 0.0070017553 s`
  (+0.128 %). The README's "feeds the gap in `/INTER/TYPE7, 11, 18, 19, 20, 21,
  24, 25`" is corrected to name the gate.

  The rest:

  * The `_INERTIA` completeness guard now checks **each** diagonal term, not just
    "all three zero". `TM=7.25 IXX=20 IYY=IZZ=0` used to emit `/RBODY` `ICoG=4`
    with `Jxx=20 Jyy=0 Jzz=0` and zero warnings — starter `ERROR 274`, since with
    `ICoG=4` the parallel-axis block is skipped (`inirby.F:322`) and the main node
    is a fresh free node, so nothing fills the zero in. A partial tensor is the
    plausible defect: the CNRB Card 4 Default row reads `none 0 0 none 0 0`.
  * A `*PART_INERTIA` part carrying `*ELEMENT_MASS` emitted **two contradictory
    warnings** back to back — "…placed in /RBODY Mass field" (false; `TM` is what
    the field holds) followed by "…SUPERSEDED by TM". The first is now gated on
    the override having been refused, so exactly one fires.
  * `/RBE3` gained the two `rbe3chk` pre-checks whose failures are starter
    `ERROR 706`, a hard stop on input LS-DYNA accepts: a translation-restricted
    `IDOF` leaving an axis weight-sum at zero (`IERR = 326/327/328`,
    `hm_read_rbe3.F:685-695`) and exactly two independent NODES with no rotational
    participation (`IERR = 322`, `:637`). Both are skipped when a set carries a
    skew, because `EL(I,axis,K)` then mixes the axes (`:669-673`). It also warns
    for `WTi <= 0` — a zero weight is REWRITTEN to 1.0 by the starter
    (`IF (W==ZERO.OR.IMODIF==3) W=ONE`, `:227`), i.e. the node runs at full weight
    — and for a duplicate `ICID`, which the reader has no pass to catch.
  * `dispatch`'s prefix fallback matches on a **token boundary** now, so
    `*PARTICLE_BLAST` is no longer routed into the `*PART` fallback and told that
    "`_ICLE_BLAST` is not one of INERTIA/REPOSITION, CONTACT, …". Diagnostics
    only — the emitted deck was identical either way. Same change in
    `assembly._apply_offsets`.
  * `RigidInertia.has_local_card` was written and never read; it now records
    whether card 6 was PRESENT (not merely promised by `IRCS = 1`) and splits the
    "local system is unusable" warning into its two distinct source-deck defects.
  * `dof_digits_to_flags` moved from `handlers.py` (no caller there) to
    `writer/rbe3.py` next to `_trarot`, so the writer stops reaching back into the
    handler layer through a deferred import that was never breaking a cycle.
  * The blank-tail probe on the `/RBE3` independent-node list no longer re-slices
    `raw[i:]` per pair card (quadratic on a thousand-node spider); the last
    non-blank line is located once. Same in `assembly.
    _off_constrained_interpolation`.
  * The node-id collision guard — the one silent-corruption path the batch
    introduced, where `state.next_node_id()` and the open-coded `_next_free`
    counter can hand out the same id and the second `state.nodes` write REPLACES
    the first — now has direct coverage on both the `*PART_INERTIA` and the CNRB
    side, asserting distinct main-node ids AND that each `/NODE` row holds its own
    body's coordinates. A mutation that deletes both `while … in state.nodes`
    loops left the old suite entirely green.
  * README: the CNRB `/RBODY` id is the main node id, not the `PID`.

  Sweep after the review round, `ccc792d` vs this commit over the same corpus
  (564 files → 254 unique decks): **0 `.rad` hash deltas** on either file, 0
  skip-list deltas; the only warning-set deltas are the added OPTT and RBE3
  diagnostics on the decks that carry those keywords. Tests 2828 → 2849 (+21),
  subtests 854 → 860; `ruff check .` clean.

- **Prescribed-motion and body/pressure load VARIANTS: `*BOUNDARY_PRESCRIBED_`
  `MOTION_RIGID_LOCAL` → a co-rotating `/SKEW/MOV`, `*BOUNDARY_PRESCRIBED_`
  `MOTION_SET_BOX` → the `_SET` path scoped by `*DEFINE_BOX`,
  `*LOAD_SHELL_ELEMENT`/`_SET` → `/SURF/SEG` + `/PLOAD`, `*LOAD_BODY_VECTOR` →
  `/GRAV` + `/SKEW/FIX`, and `*LOAD_BODY_RX`/`_RY`/`_RZ` → `/LOAD/CENTRI` +
  `/FRAME/FIX`.** All five spellings previously landed in `skipped_keywords`
  with **no warning at all** — the `*LOAD_BODY_*` handler's docstring claimed
  the rotational and generalized forms were "skipped with a warning" but they
  were never registered, so nothing said anything. Five keyword families,
  five conventions that are invisible in the `.rad` and one of them
  catastrophic if it is guessed:

  **1. `*LOAD_SHELL` pressure sign — one flip, not two.** LS-DYNA's positive
  pressure acts along the shell's NEGATIVE normal: Vol I R16 p.3421 requires the
  connectivity to follow the right-hand rule and states "positive pressure
  acting in the negative t-direction". A Radioss `/PLOAD` with a positive
  `Fscale_y` does the opposite — it pushes the surface along its POSITIVE
  segment normal `n = N1N3 × N2N4`. Engine ground truth,
  `engine/source/loads/general/force.F90:451-465`:

  ```fortran
  aa = fcy*f1*xsens
  nx = (x(2,n3)-x(2,n1))*(x(3,n4)-x(3,n2)) - (x(3,n3)-x(3,n1))*(x(2,n4)-x(2,n2))
  fx = aa*nx*one_over_8
  a(1,n1)=a(1,n1)+fx        ! and +fx on n2, n3, n4
  ```

  `|(X3−X1)×(X4−X2)| = 2A`, so the four nodes sum to `+P·A·n̂` (tria branch
  `:550-555`, factor `1/6`, same result). Altair's own help card says the same in
  words: "positive pressure acts in direction n = N1N3 × N2N4". k2rad builds the
  `/SURF/SEG` by pasting the shell connectivity column-for-column (Reference
  Guide 2022 p.2499 Comment 3 explicitly blesses that: segments "may be produced
  by cut-and-paste of shell element input data"), so `n̂ = t̂` and exactly ONE
  flip is correct — `Fscale_y = -SF`, node order untouched. Flipping the scale
  AND reversing the segment to `n1 n4 n3 n2` cancels back to the wrong
  direction, which is the trap this batch was warned about.

  **2. `*LOAD_BODY_R*` ω vs ω² — LINEAR, both sides.** `LCID` carries the
  angular velocity, and the engine squares it for itself,
  `engine/source/loads/general/load_centri/cfield.F:121,128,232-237`:

  ```fortran
  VROT  = FAC(1,NL)*FINTER(IFUNC,TS*FAC(2,NL),NPC,TF,DYDX)   ! omega = Fscaley*f(t)
  VROT2 = VROT*VROT
  DIST(1)=X1-(X1*X2+Y1*Y2+Z1*Z2)*X2                          ! r_perp
  AREL(1) = DIST(1)*VROT2                                    ! a = omega^2 * r_perp
  ```

  `centri.cfg:22,55-58` types the curve `Y_DIMENSION="ang_velocity"` and titles
  it "Rotational velocity vs time"; Reference Guide 2022 p.2103 says "Time
  function identifier, giving the rotational velocity … versus time". LS-DYNA
  does the same internally — Vol I R16 p.33-20 Remark 3 gives the body force
  density as `b = ρ·[ω × (ω × r)]` and Remark 2 notes ω is "in radians per unit
  time" and the load acts radially outward. So the mapping is **1:1 and linear**:
  `Fscaley = SF`. A pre-squared `Fscaley = SF²` would be off by `SF` itself and
  there is nothing in the `.rad` to notice it by, which is why
  `test_omega_is_linear_not_squared` pins it with hand-computed numbers
  (`SF = 4.0` → emitted `4.0`, not `16.0`, not `2.0`; the engine then applies
  `4² × 3 = 48.0` at `r⊥ = 3`).

  Corollary: **no sign flip on `/LOAD/CENTRI`**, unlike `/GRAV`. Both codes push
  outward. dyna2rad writes `Fscaley = -SF` (`convertloads.cxx:313`), which is
  inert only because `VROT2 = VROT*VROT` squares it away — copying it "because
  /GRAV needs it" is cargo-culting, and it would bite the moment `Ivar = 2`
  turned the un-squared `DWDT = FAC(1,NL)*DYDX` Euler term on.

  **3. `/LOAD/CENTRI` `Dir` must be `XX`/`YY`/`ZZ`.** The starter accepts both
  spellings — `hm_read_load_centri.F:206-211` maps `X`/`Y`/`Z` to `IDIR` 1/2/3
  and `XX`/`YY`/`ZZ` to 4/5/6, stored verbatim in `ICFIELD(2,K)` with no remap
  anywhere (grep `ICFIELD(2` → only `hm_read_load_centri.F:275`, `cfield.F:85`,
  `cfield_imp.F:83`). But the engine only branches on 4 and 5,
  `cfield.F:132-144`, so `IDIR` 1/2/3 all fall into the trailing `ELSE` and take
  `XFRAME(7:9)` — the frame's **Z axis**. Measured: a `/LOAD/CENTRI` with
  `Dir=X` echoes `DIR = X`, 0 errors, 0 relevant warnings, and rotates about Z.
  The implicit solver disagrees with the explicit one, which is worse:
  `cfield_imp.F:135-147` has no `ELSE` at all, so with a frame attached the axis
  is whatever `X2/Y2/Z2` held from the previous loop iteration. **dyna2rad emits
  `X`/`Y`/`Z`** (`convertloads.cxx:271-288`) and is therefore silently wrong for
  `RX` and `RY`, and right for `RZ` only by accident. This is the single
  highest-value correction in the batch and is not ported.

  **4. `*LOAD_BODY_VECTOR` — the sign and the skew are ONE decision.** `/GRAV`
  adds `+Fscale_Y·f(t)` as an acceleration along the `DIR` axis of its skew
  (`gravit.F`, real lines 105-160: `AA = GAMA`, then
  `A(1,N1)=A(1,N1)+SKEW(K1,ISK)*AA`). LS-DYNA's `_VECTOR` body force acts along
  **−V** — Vol I R16 p.33-29, and the manual's own validation example writes
  `V = (−1,−1,−1)` to obtain gravity along `+(1,1,1)`. So k2rad emits ONE
  `/GRAV` with `DIR = "X"`, `Fscale_Y = -SF`, and a companion `/SKEW/FIX` whose
  local X′ is `+V`; the net acceleration is `-SF·f(t)·V̂`. Reproducing the
  negation without the `+V` skew (or the reverse) flips the load, and each half
  looks right on its own. Same pairing dyna2rad uses (`convertloads.cxx:550` and
  `:595-606`), so PR #89's `Fscale_Y = -SF` lesson carries over unchanged.
  `|V|` is ignored on both sides (the starter normalises the skew); `CID` maps
  `V1/V2/V3` from that basis to global via the existing `_icid_basis`;
  `XC/YC/ZC` become the skew origin, which is inert for a uniform field but is
  where dyna2rad puts them too.

  Note the `/SKEW/FIX` two vector cards are the local **Y′ and Z′** and the
  starter rebuilds `X′ = Y′ × Z′` (`hm_read_skw.F:448-459`) — the existing
  `_ortho_skew_axes` returns exactly the pair for which that is `+V`, which is
  the same construction the `*RIGIDWALL_GEOMETRIC_*_MOTION` path already uses.

  **5. `_RIGID_LOCAL` — a co-rotating `/SKEW/MOV` in the `skew_ID` column.**
  With the `_LOCAL` option LS-DYNA expresses DOF in the rigid body's own system,
  whose "orientation rotates with time in accordance with the rotation of the
  rigid body" (Vol I R16 p.756-757 Remark 7). A `/SKEW/MOV` is rebuilt from its
  three nodes' CURRENT coordinates every cycle — `engine/source/tools/skew/`
  `newskw.F` ("`SKEW MOBILE`"), called from `resol`:

  ```fortran
  IF (N1+N2+N3/=0) THEN
    IF(IMOV == 1)THEN
      IF (IDIR == 1)THEN
        P(1)=X(1,N2)-X(1,N1) ; P(2)=X(2,N2)-X(2,N1) ; P(3)=X(3,N2)-X(3,N1)
  ```

  and `constraints/general/impvel/fixvel.F:390-417` projects the imposed
  component onto the freshly-updated row (`VV = SKEW(K1,ISK)*V(1,I)+…`, then
  `A(1,I)=A(1,I)+SKEW(K1,ISK)*AA`). A moving *skew* carries no ω, so no
  entrainment or Coriolis term is ever added — exactly what is wanted here
  (a moving *frame* would maintain `XFRAME(13:18)` and `RELFRAM_M1` would add
  them). k2rad therefore synthesizes three element-free nodes at the body's
  nodal centroid + 10 % of its span along global x̂ and ŷ, folds them into that
  body's `/RBODY` secondary group through the new `state.local_frame_nodes`, and
  puts the skew id in the `skew_ID` column.

  **Why not `frame_ID`.** Measured, `/BEGIN 2022`: an `/IMPDISP` written with
  `frame_ID = 300` in cols 51-60 echoes

  ```
       IMPOSED DISPLACEMENTS
           NODE         SKEW        FRAME  DIRECTION   LOAD_CURVE   SENSOR
             21            0            0          Y           10        0
  ```

  — `FRAME = 0`, motion silently on the GLOBAL axis, **no error and no
  warning**. Cause: `read_impdisp.F:140-142` fetches the frame via
  `HM_GET_INTV('frame_ID', …)` but `radioss120/LOADS/impdisp.cfg` neither
  declares the attribute nor runs the `CARD_PREREAD` that populates it — that
  was added only in `FORMAT(radioss2025)`, unreachable from a 2022 deck, so the
  guard `IF (FRAME_ID > 0 …)` can never fire. `/IMPVEL` does have the
  `CARD_PREREAD` in radioss120 and its `frame_ID` works (measured: echoes
  `FRAME 300`), but `read_impvel.F:322-325` then raises **ERROR 3091** if a
  driven node is one of the frame's own `N1/N2/N3` — a constraint `/SKEW/MOV`
  does not impose. `/IMPACC` has no frame column at all below 2022. So
  `skew_ID` is the only route safe on all three, and it is verified working on
  all three (`/IMPDISP` with `skew_ID=401` → `SKEW 401`; `/IMPVEL` with
  `Dir=XX` + `skew_ID=401` → `SKEW 401  DIRECTION XX`).

  **What is approximated, and by how much.** The triad is initialised to the
  GLOBAL axes. LS-DYNA takes them from `LCO` on `*MAT_RIGID` / `CID` on
  `*CONSTRAINED_NODAL_RIGID_BODY`, defaulting to the body's PRINCIPAL INERTIA
  directions when that is 0; k2rad parses neither (`*MAT_RIGID` card 3 is not
  read) and computes no inertia tensor. The residual error is therefore the
  CONSTANT rotation R₀ between the global axes and the true local system: exact
  whenever the body's local system is global-aligned at t=0, a fixed
  misalignment otherwise, and the warning says so and points at the "principal
  directions" block of the LS-DYNA `d3hsp` mass summary. That is strictly better
  than dyna2rad, which never reads `localOption` at all (grep
  `LOCAL|Iframe|iframe` over `convertbcs.cxx` → *no matches*) and so treats
  `_RIGID_LOCAL` as plain `_RIGID`, freezing the axes at t=0 — an error that
  grows as `cos θ(t)` and is meaningless once the body has turned ~90°, with no
  diagnostic of any kind.

  **`_SET_BOX` membership is `set ∩ box`, and a t=0 snapshot.** The extra card
  is `BOXID TOFFSET LCBCHK` (`boundary_prescribed_motion_set.cfg:319-324`,
  `FORMAT(Keyword971_R7.1)`; the R6.1 form has only `BOXID TOFFSET`, so a
  two-field card parses identically). dyna2rad builds the intersection as a
  two-clause `/SET/GENERAL` with `SET` + `SET_I` (`opt_I = 1`,
  `convertbcs.cxx:493-520`); k2rad resolves the same membership numerically,
  like every other `*DEFINE_BOX` consumer since PR #66, reusing
  `_resolve_box_nodes`. `NSID = 0` → the box alone (`:522-535`); `BOXID = 0` →
  the plain `_SET` (`:476-479`); neither → dyna2rad leaves `setId` uninitialised
  behind an empty `// warning / error` comment, k2rad warns. **LS-DYNA
  re-evaluates box membership as nodes move in and out every timestep** — both
  the numeric resolution and dyna2rad's `/SET/GENERAL` are a t=0 snapshot, and
  `TOFFSET` (offset the curve by when the node entered the box) and `LCBCHK`
  have no equivalent. All three are warned; dyna2rad drops all three silently.

  **Arrival time `AT` now has a target: `/SENSOR/TIME`.** k2rad emitted no
  `/SENSOR` card anywhere and dropped `AT` on `*LOAD_SEGMENT_SET` with a
  warning. `/SENSOR/TIME` carries `Tdelay` and `Tstop`
  (`radioss2022/SENSOR/sensor.cfg:219-222` for the header,
  `read_sensor_time.F:69-71`, `Tstop = 0 → INFINITY`), and the semantics chain
  is a SHIFT, not a gate: `sensor_time.F:66-68` sets `SENSOR%TSTART = TDELAY`
  when the sensor fires, and `force.F90:216-218` evaluates the load at
  `ts = tt - sensor_tab(isens)%tstart` with `IF(ts < ZERO) CYCLE`. So the load
  is zero for `t < AT` and the curve is read at `t - AT`, which is how LS-DYNA's
  arrival time reads and what dyna2rad emits (`convertloads.cxx:803-812`). It is
  warned, because a curve whose abscissa is already absolute time must be
  pre-shifted instead. Applied to `*LOAD_SHELL*` and `*LOAD_SEGMENT_SET` alike.

  **`/PLOAD` and `/LOAD/CENTRI` column grids do NOT match `/GRAV`'s.** All three
  put `Ascale_x` at cols 61-80 and `Fscale_y` at 81-100, but cols 51-60 differ:
  ten LITERAL blanks on `/GRAV` (`_GRAV_GAP`), `Ivar` on `/LOAD/CENTRI`
  (`radioss120/LOADS/centri.cfg:79`,
  `CARD("%10d%10s%10d%10d%10d%10d%20lg%20lg", …)`), and blanks again on
  `/PLOAD` — where they must STAY blank, because that is the 2023-only
  `Itypfun` column and writing it into a 2022 deck raises **`WARNING ID 100214`
  "unsupported field exists"** (measured on a `/BEGIN 2022` deck). Three
  separate emitters, and the tests assert all three grids by column.

  Also fixed in the same code, all confirmed by running the converter rather
  than inferred:

  - **the continuation card was parsed as a phantom card 1.** Both prescribed-
    motion handlers looped over every non-blank line and read each as a card 1,
    but the reader takes ONE extra card (`OFFSET1 OFFSET2 LRB NODE1 NODE2`)
    after a card 1 with `|DOF|` in 9/10/11 or `VAD = 4`. `parse_fixed` always
    returns `n` padded fields, so the `len(f) < 4` guard could never fire: a
    `DOF=11` card's `OFFSET1 = 1.5` became the node-set id and `OFFSET2` the
    DOF, i.e. a PHANTOM motion on whatever set `OFFSET1` happened to name —
    silent whenever that set existed. There is now one shared card walker
    (`_bpm_walk`), which also knows about the `_BOX` card;
    `assembly._bpm_cards` had implemented the correct rule for the
    `*INCLUDE_TRANSFORM` offsets since PR #92 and is now extended the same way
    (the `_BOX` card's `BOXID` moves with `IDDOFF`, `LCBCHK` with `IDFOFF`);
  - **`VAD = 3`/`4` silently became an `/IMPDISP`.** The map was
    `{0:IMPVEL, 1:IMPACC, 2:IMPDISP}.get(vad, "IMPDISP")`, so
    velocity-versus-DISPLACEMENT (3) and RELATIVE displacement (4) were written
    as ordinary displacement-vs-time cards, silently. All three `/IMP*` cards
    evaluate their function against TIME, so both are now refused with the
    reason. dyna2rad warns (code 200002) for `VAD=3` on `_RIGID` and emits an
    `/IMPVEL` anyway, and skips `VAD=4` and `VAD=3`-on-non-rigid with a bare
    `continue`;
  - **`|DOF| = 4`/`8` ignored `VID` entirely.** `_DOF_DIR[4] = "X"` with a
    hard-coded `skew_ID = 0` reinterpreted "translation along `*DEFINE_VECTOR`
    VID" as "translation along global X", and `DOF = 8` as "rotation about
    global X" — with no warning at all (the existing DOF-4/8 warning fired only
    in the `SF = 0 → /BCS` branch). The vector's own `/SKEW` (local
    X′ = tail→head = `+V`) now goes in the `skew_ID` column, which is what
    dyna2rad does (`convertbcs.cxx:339`). `-4`/`-8` additionally hold the two
    transverse axes at zero — the same lock dyna2rad builds from a synthetic
    flat-zero 2-point function (`:638-675`), here as two extra `/IMP*` cards
    with `Fscale_Y = 0` on the SAME curve, which needs no synthesized `/FUNCT`.
    `|DOF| = 9/10/11` and `12` are no single skew axis and now warn-skip instead
    of becoming a global-X card (dyna2rad emits an EMPTY `/IMPVEL` for them).

    The lock needs a **synthesized flat-zero `/FUNCT` at `Fscale_Y = 1`**, not
    the real curve at `Fscale_Y = 0`. Measured: the first implementation used
    the real curve with a zero ordinate scale, and the starter echoed

    ```
         IMPOSED VELOCITIES
             NODE         SKEW  DIRECTION   LOAD_CURVE          FSCALE
                1           30          Y           10    1.000000000000
    ```

    — `FSCALE 1.0`. `read_impvel.F:248` is
    `IF (YSCALE == ZERO) YSCALE = ONE * FSCAL_V`, the same silent unit-factor
    substitution `/GRAV` does for `FCY`, so those cards would have driven the two
    transverse axes at FULL scale on the real curve: the exact opposite of
    locking them, with no error and no warning. With the flat-zero `/FUNCT` the
    echo reads `LOAD_CURVE 90009  FSCALE 1.0` on all four locked rows. This is
    why dyna2rad synthesizes the 2-point function too, and it is a case where
    reading back what the starter parsed caught a bug the `.rad` looked fine for;
  - `*BOUNDARY_PRESCRIBED_MOTION_SET`'s `/GRNOD` now comes from
    `next_grnod_id()` rather than `next_id()` — the allocator that exists to
    dodge a user `*SET_NODE` SID at or above the auto-id base (`ERROR 79`). A
    no-op on any deck without such a set, so no ids move;
  - two `_RIGID_LOCAL` cards on ONE body share their `/SKEW/MOV` and it is now
    emitted once. Written per motion it would have been a duplicate id in the
    merged `/SKEW`+`/FRAME` table — `ERROR 79`, no restart file. Frame ids for
    `*LOAD_BODY_R*` likewise come one per card from `reserve_skew_id`; dyna2rad
    calls `GetDynaMaxEntityID` inside its loop, which returns the SAME id every
    time and gives a deck with two `*LOAD_BODY_R*` cards two `/FRAME` entities
    with one id;
  - `*LOAD_BODY_GENERALIZED` is now REGISTERED so its skip is reported with a
    reason (split it into `*LOAD_GRAVITY_PART` rows) instead of arriving as a
    mute `skipped_keywords` entry, which is what the handler docstring had been
    claiming for two PRs;
  - `*LOAD_BODY_PARTS` gained an `_OFFSET_SPECS` row (its `PSID` is a part SET,
    `IDSOFF`), and `*LOAD_BODY_RX/RY/RZ` are registered in
    `_carries_literal_axis_point` so a `TRANID` include reports that their
    `XC/YC/ZC` centre of rotation is literal geometry k2rad does not move.

  Deliberately NOT registered, so they stay in `skipped_keywords` rather than
  being read as a near-alias: `_SET_LINE`, `_SET_SEGMENT`, `_SET_POINT_UVW`,
  `_SET_EDGE_UVW`, `_SET_FACE_XYZ`, `_NODE_LOCAL`, `_SET_LOCAL`. None of them
  exists anywhere in `hm_cfg_files` (verified by grep over the whole cfg tree),
  so the Radioss dyna-reader rejects them at parse time too; `_SET_SEGMENT` in
  particular carries `DOF = 12` (translation along the segment normals), which
  no `/IMPVEL` `Dir` letter can express. `_ID` needs no key on any of the new
  spellings — `parser._split_keyword` strips it — but `_BOX` and `_LOCAL` stay
  in the base name and do need one, the same rule `*DEFINE_BOX_LOCAL` follows.

  **What this corpus cannot see.** All five keywords have **ZERO** occurrences
  across 628 unique deck files (the 83-file repo tree, the 127-deck
  `Ryan_Lee_Examples`, the remaining 382 files under `E:\openradioss_run`
  including the Toyota Yaris and Camry `.key`s, and 36 files under
  `E:\foxcore_data`) — and neither does any `*BOUNDARY_PRESCRIBED_MOTION` card
  in that corpus carry a non-zero `VID`, a `DOF` outside {1,2,3,5,6,7}, or a
  `VAD` other than 0 or 2. So no sweep deck exercises a single new path, and no
  sweep deck can regress on the `VID`, `VAD` or continuation-card fixes either:
  they are latent-only in this corpus. Everything above is pinned by
  column-exact tests built from the CFG `FORMAT` blocks and the engine/starter
  sources.

  What the corpus DOES confirm — the byte-identity sweep. Measured over **201
  decks** (the 73 `.k`/`.key`/`.dyn` decks in the repo tree, the 127-deck
  `E:\openradioss_run\Ryan_Lee_Examples` tree and the one
  `E:\openradioss_run\ls-dyna_example` deck), `master 2d067cf` vs this branch,
  0 exceptions on either side:

  **201/201 byte-identical on BOTH `_0000.rad` and `_0001.rad`, with identical
  warning sets and identical skip lists. Total warnings 2392 → 2392, delta +0.**

  Nothing moved, and that is the arithmetic the census predicts: 24 decks carry
  `*BOUNDARY_PRESCRIBED_MOTION_RIGID`, 65 carry `_SET`, 20 carry
  `*LOAD_BODY_{Y,Z}`, 7 carry `*LOAD_SEGMENT*` and 16 carry `*DEFINE_BOX` — all
  of them through code this batch rewrote — but every new branch in it is gated
  on a condition no corpus deck meets: `_LOCAL`, `_BOX`, `*LOAD_SHELL`,
  `*LOAD_BODY_VECTOR`/`_R*`, a non-zero `VID`, `|DOF|` outside {1,2,3,5,6,7},
  `VAD` other than 0/2, or `AT > 0`. The three refactors that DO sit on the
  common path were written to be output-neutral and are confirmed so here: the
  `/IMPVEL`-family card emitter (`_emit_imp_card`, byte-for-byte the old inline
  f-strings), the `/PLOAD` card emitter (same 100-column grid, `sens_ID` written
  as `_i(0)` where the literal `"         0"` used to be), and the `_SET`
  motion's `/GRNOD` moving from `next_id()` to `next_grnod_id()` (identical
  unless a user `*SET_NODE` SID sits at or above the auto-id base).

  The five golden fixtures (`shell_explicit`, `solid_plastic`, `rigid_contact`,
  `tied_weld`, `implicit_qstat`) carry none of these keywords and are unchanged.

  And a live `starter_win64.exe` run DOES cover the emitted cards. A synthetic
  deck carrying all five new keywords at once (`_RIGID_LOCAL` on a `*MAT_RIGID`
  brick, `_SET_BOX`, `_SET` with `DOF = -4` + a `*DEFINE_VECTOR`, two
  `*LOAD_SHELL_ELEMENT` rows plus a `*LOAD_SHELL_SET`, `*LOAD_BODY_VECTOR`, and
  `*LOAD_BODY_RZ` + `*LOAD_BODY_RX`) converts and runs the starter to
  **0 ERROR(S), 2 WARNING(S)** (ELEM/PROP/MAT compatibility + KINEMATIC
  CONDITIONS, both expected), and every field reads back as intended:

  ```
       PRESSURE   LOADS
         SEGM   NODE1 NODE2 NODE3 NODE4  CURVE  SENSOR   SCALE-X      SCALE-Y
            1       1     2     3     4     10       0       1.0         -2.5
            2       5     6     7     8     20   90013       1.0         -3.0
            3       1     2     3     4     10       0       1.0         -7.5
            4       5     6     7     8     10       0       1.0         -7.5

       IMPOSED VELOCITIES
           NODE      SKEW   FRAME  DIRECTION  LOAD_CURVE   FSCALE
             22     90001       0          X          10      2.5     <- _LOCAL
              1        30       0          X          10      2.0     <- DOF -4
              1        30       0          Y       90009      1.0     <- lock
              1        30       0          Z       90009      1.0     <- lock
       IMPOSED DISPLACEMENTS         (nodes 1 and 4 only - the box intersection)
              1         0       0          Y          10      1.5

       SKEW SYSTEM SETS
         NUMBER   N1  N2  N3     VECTORS                    ORIGIN
          90001   19  20  21   (1,0,0) (0,1,0) (0,0,1)    (22, 2, 2)

       GRAVITY LOADS
          SKEW  DIRECTION  LOAD CURVE   SCALE_X    SCALE_Y
         90019          X          10       1.0       -2.0

       CENTRIFUGAL LOAD 90020 / VARIATION OF VELOCITY FUNCTION NOT TAKEN INTO ACCOUNT
         NODE GROUP  FRAME  DIR  LOAD_CURVE  SCALE_X  SCALE_Y
              90018  90021   ZZ          10      1.0      4.0
       CENTRIFUGAL LOAD 90022 / VARIATION OF VELOCITY FUNCTION NOT TAKEN INTO ACCOUNT
              90018      0   XX          10      1.0      1.5
  ```

  i.e. `/PLOAD` keeps `-SF` and picks up the `/SENSOR/TIME`; the `_RIGID_LOCAL`
  motion is bound to the moving skew, whose triad is the global one at the
  brick's centroid on its three synthesized nodes; the `_SET_BOX` group is the
  2-of-4 intersection; `/GRAV` carries `-SF` in the vector skew; and both
  `/LOAD/CENTRI` cards read `Dir = ZZ`/`XX` with `+SF` and `Ivar = 1`.

  What is still NOT covered: no ENGINE run, so the resulting motion and load
  fields are argued from the engine sources and the manual rather than measured
  end to end.

- **`*DATABASE_DEFORC` / `*DATABASE_DISBOUT` → `/TH/SPRING`.** Both cards were
  parsed into state and consumed by nothing: no `/TH` block, and not even a
  contribution to the `/TFILE` frequency, so a deck asking for discrete-element
  forces got a converted deck with the channel missing and no diagnostic.
  (`*DATABASE_DISBOUT` had no handler at all and reached the generic skipped
  list.) LS-DYNA keeps the two families in separate databases and so does this:
  Vol I R16 p.1944 defines DEFORC as "discrete spring and discrete damper
  (`*ELEMENT_DISCRETE`) data", p.1945 defines DISBOUT as "discrete beam element,
  type 6, relative displacements, rotations, and forces". k2rad converts both
  families to `/SPRING` elements, so each answers with its own `/TH/SPRING`
  group and every T01 channel stays attributable to the card the deck wrote.

  Format pinned against `hm_cfg_files/config/CFG/radioss110/OUTPUTBLOCK/
  th_spring.cfg` `FORMAT(radioss51)` (the only `th_spring.cfg` in the CFG tree)
  and verified on live `starter_win64` runs:

  - the TITLE line after `/TH/SPRING/<id>` is **mandatory** — the reader takes
    the first line after the header as the title unconditionally, so omitting it
    feeds `DEF` to the title and the deck then dies with `ERROR 260` ×2 +
    `ERROR 1109` (measured);
  - element ids go **one per line** (`%10d`, optional name from column 21).
    `/TH/SPRING` is read by `hm_read_thgrne.F`, not the ten-per-line
    `hm_read_thgrki.F` that `/TH/CLUSTER` uses — measured, a second id on the
    same line is `WARNING 100214` and the id is **silently dropped**, exit 0.
    Data loss with no error, which is why the writer never packs them;
  - `DEF` expands to 15 variables (`hm_read_thgrou.F:1518-1520`, indices
    1-14 + 65): `OFF FX FY FZ MX MY MZ LX LY LZ RX RY RZ IE LENGTH`. `ALL_42` is
    not a superset — it stops at index 16 (`NVALL = 16` for SPRING,
    `hm_read_thgrou.F:2501`), gaining `F1`/`F2` but losing `LENGTH`;
  - the group id comes from `state.next_id()`, never a literal: `/TH` ids are
    ONE namespace across every `/TH` type and a hard-coded one already cost this
    converter an `ERROR 79` with no restart file (PR #83).

  **Only ids a `/SPRING` line was actually written for are listed.** Both spring
  writers have live `continue` paths — an `*ELEMENT_DISCRETE` part with no
  `*PART` record or no `*SECTION_DISCRETE`, a grounded element whose anchor node
  has no coordinates, a discrete-beam part with no usable beams — and a
  `/TH/SPRING` naming an element the deck never defines is starter `ERROR 69`
  (`hm_read_thgrne.F:189`, `MSGTYPE=MSGERROR`): the deck is **refused**, not
  degraded. The accounting sets (`state.discrete_spring_eids`,
  `state.dbeam_spring_eids` — the twin the PR #113 note asked for) are therefore
  filled at the line that writes the `/SPRING`, and the emitter is registered
  after `discrete_springs` / `discrete_beams` in the starter section registry so
  they are populated when it runs. Proven live on a synthetic deck: the
  converted `/TH/SPRING` lists 11 and 12 but not the grounded 13, and the
  starter says `0 ERROR(S)` — while the same deck with 13 spliced back in gives
  `ERROR ID : 69 ** ERROR IN TH SELECTION (ELEMENT)`, exit 2.

  A deck that asks for either card but has no matching connector gets a warning
  and **no** dangling `/TH` block (an empty group is `ERROR 1109`); the `dt` is
  still honoured as the `/TFILE` frequency. The warning states that the values
  are in **raw deck units** — k2rad rescales nothing, so a ton-mm-s deck reports
  newtons and millimetres exactly as the `.k` writes them — and README's `/TH`
  semantics table now says the same next to the `/TH/SPRING` row.
  New tests in `tests/test_th_output_losses.py`. No corpus deck contains
  `*ELEMENT_DISCRETE`, so the fixtures and the starter runs are the evidence;
  the 13 corpus `*DATABASE_DEFORC` decks (all `implicit_hr-anlenkung`) have no
  discrete element and no discrete beam, so they get the warning and stay
  byte-identical.

- **Geometric rigid walls** (`*RIGIDWALL_GEOMETRIC_{FLAT,PRISM,CYLINDER,SPHERE}`,
  each with any ordering of `_MOTION` / `_DISPLAY` / `_INTERIOR` and `_ID`) —
  the roadmap P1 "geometric rigidwalls" item. **All 42 spellings were silently
  `SKIPPED` before**: no handler, no dispatch prefix, no offset map, so a deck's
  cylinder or prism barrier simply vanished behind the generic skipped-keyword
  note. Card layouts follow `hm_cfg_files/config/CFG/radioss110/RWALL/
  {plane,paral,cyl,sphere}.cfg` `FORMAT(radioss51)` — the newest FORMAT block at
  or below `/BEGIN 2022` — cross-checked against the starter readers
  `hm_read_rwall_{plane,paral,cyl,spher}.F` and the engine contact routines
  `rgwal{c,s,p}.F`.

  - `_CYLINDER` → `/RWALL/CYL`. `XM/YM/ZM` = the LS-DYNA tail, `XM1/YM1/ZM1` =
    the head verbatim; the starter keeps only `normalize(M1-M)` as the axis and
    divides `|M1-M|` out (`hm_read_rwall_cyl.F:240-254`), so the head point is a
    pure direction hint. `Phi = 2 x RADCYL`: the Radioss field is a **DIAMETER**
    while LS-DYNA gives a **RADIUS**, and every consumer halves it
    (`hm_read_rwall_cyl.F:272 DISN = SQRT(D2-D1**2) - HALF*DIAM`,
    `rgwalc.F:81 RA2=(HALF*RWL(7))**2`). `/RWALL/CYL` has **no length field** —
    the engine's only contact test is the perpendicular distance to the axis
    *line* (`rgwalc.F:129-133`; the axial coordinate `DD` is computed and never
    bounded) — so a `LENCYL > 0` finite cylinder is loudly warned instead of
    silently over-constraining, which is what dyna2rad does (`lsdLenCyl` is read
    at `convertrwalls.cxx:193-194` and never used again). A degenerate axis
    (head == tail) would abort the starter with `ERROR 167`, so it is refused
    with a warning rather than emitted. `NSEGS` and its `VL/HEIGHT` sub-cards
    are per-segment force output with no `/RWALL` counterpart: warned and
    skipped, but their card count is honoured so the following `_MOTION` /
    `_DISPLAY` cards are still read from the right lines.
  - `_SPHERE` → `/RWALL/SPHER`. `M` = the centre = the tail point,
    `Phi = 2 x RADSPH` (`hm_read_rwall_spher.F:230, 243`). The block is exactly
    five lines: `/RWALL/SPHER` has **no card 4** at all.
  - `_FLAT` → `/RWALL/PLANE` when the wall is infinite and `/RWALL/PARAL` when
    it is finite. **`LENL` / `LENM` decide** — "Length of the l/m edge. A zero
    value defines an infinite size plane" (Manual p. 40-9) — and `/RWALL/PLANE`
    with `M` = tail, `M1` = head expresses that infinite plane *exactly*, so no
    warning is due. dyna2rad has no branch for it and builds a 1e20 x 1e20 PARAL
    *quadrant* anchored at the tail, which never catches a node on its -l or -m
    side (and hard-fails `ERROR 168` when the tail is the origin). The finite
    form takes the corner points `M1 = T + LENL*l`, `M2 = T + LENM*m` with `l` =
    the **in-plane projection** of `HEV - T` and `m = n x l` **normalized**; the
    starter recomputes the normal as `(M1-M) x (M2-M) = LENL*LENM*n`
    (`hm_read_rwall_paral.F:245-267`), so the LS-DYNA outward normal is
    preserved exactly. dyna2rad normalizes `HEV - T` raw and leaves `m`
    un-normalized, which shortens every m-edge by `sin(theta)` whenever `HEV` is
    not exactly perpendicular to the normal. The l direction is taken
    **tail-relatively** (`l = HEV - T`, matching the manual's "coordinate of
    head of edge vector l" and the sibling `*RIGIDWALL_PLANAR_FINITE` path);
    classifying on the ABSOLUTE `HEV` — what `rigidwall_geometric.cfg:416` does
    for its HyperMesh `geometrytype` radio button — is not
    `*INCLUDE_TRANSFORM`-invariant, because a translation moves `HEV` off the
    global origin and the same physical wall would then convert to a different
    Radioss wall depending on how the deck is assembled. A degenerate l (HEV on
    the tail, or projecting onto the normal) still falls back to the infinite
    plane, with a warning.
  - `_PRISM` → **six** `/RWALL/PARAL` faces. Radioss has no box rigid wall (the
    only `/RWALL` readers are
    `hm_read_rwall_{plane,paral,cyl,spher,lagmul,therm}.F`), so the box
    decomposes into top + four sides + bottom, each `(M, M1, M2)` chosen so
    `(M1-M) x (M2-M)` points **out** of the box and the assembly keeps nodes
    outside it. The five extra walls take fresh `/RWALL` ids (checked against
    every wall in the deck — the starter's `UDOUBLE` pass spans
    PLANE/CYL/SPHER/PARAL together) and share the parent's tracked group,
    friction and prescribed motion. Every box EDGE is covered by two faces and
    every CORNER by three, so the starter reports the decomposition as
    `WARNING ID 312` (INCOMPATIBLE KINEMATIC CONDITIONS ... BETWEEN SEVERAL
    RIGID WALLS) — expected, not a deck error, and the converter now says so
    unconditionally rather than only when `*DATABASE_RWFORC` is present.
    `LENP = 0` means an infinitely deep prism; the four sides and the bottom
    would each need a semi-infinite PARAL, so only the top face is emitted, with
    a warning — dyna2rad applies its `0 -> 1e20` substitution to `LENL`/`LENM`
    but **not** to `LENP`, so it emits four walls with a zero edge vector, i.e.
    `ERROR 168` x 4.
  - `_MOTION` → the moving `/RWALL` form. Each face gets a synthesized carrier
    node at that face's own base point `M` (a moving wall has **no** `XM/YM/ZM`
    card — `M` is the node's position, `hm_read_rwall_cyl.F:199-230`), and one
    `/IMPVEL` (`OPT = 0`) or `/IMPDISP` (`OPT != 0`) on the LS-DYNA `LCID`
    drives all of them through a single `/GRNOD/NODE`. `/RWALL` itself has no
    motion-curve field; the imposed motion is legal on the wall's main node and
    *wins*, because `resol.F` calls `FIXVEL` (7345) after `RGWALF` (5577) and
    `KINSET` is applied only to the secondary nodes. The `VX/VY/VZ` direction
    cosines become a synthesized `/SKEW/FIX` whose local **X'** is the motion
    vector, referenced with `Dir = "X"`: with `Y' = e x V` and `Z' = V x Y'` the
    starter's `X' = Y' x Z'` (`hm_read_skw.F:448-459`) comes out parallel to
    `+V` (`e` = global Z, falling back to global X when `V` is parallel to Z).
    Three degenerate inputs that dyna2rad converts *silently wrong* are warned
    and degraded to a FIXED wall instead: `LCID = 0` (dyna2rad leaves a
    massless, unconstrained free-floating wall), a `LCID` that is not in the
    deck, and all-zero direction cosines (dyna2rad's `Dir="X"` then silently
    means global +X). The wall's own `Mass` field stays 0, matching the LS-DYNA
    card, and that makes the motion **purely kinematic**: `rgwal0.F:417-423`
    scales the wall reaction by `MS(MSR)/(MS(MSR)+Sum(m_secondary))`, which is 0
    here, so contact can never accelerate or laterally drift the carrier node —
    unlike a `*RIGIDWALL_PLANAR_MOVING` wall, which carries a real mass and does
    get that drift caveat.
  - `_DISPLAY`'s `PID/RO/E/PR` card describes a visualization mesh with no
    solution effect (Manual p. 40-13) — parsed away so the card cursor stays
    correct, and warned. `_INTERIOR` (`CYLINDER`/`SPHERE` only) confines nodes
    *inside* the form, but `/RWALL/CYL` and `/RWALL/SPHER` test `DP <= RA2` and
    push nodes **outward** (`rgwalc.F:132-133`, `rgwals.F:126-127`) with no
    inversion flag anywhere on the card: converting it would invert the physics,
    so it warn-**skips**. dyna2rad parses the option and then ignores it.
  - Secondary-node selection matches the planar path and dyna2rad's decision
    table: `NSID` -> `grnd_ID1`; `NSIDEX` -> `grnd_ID2`; `BOXID` alone -> a
    `/GRNOD` of the in-box nodes; `NSID` + `BOXID` -> the box is dropped and
    `NSID` wins; blank `NSID` = *all nodes*, expressed with the search distance
    `d` because the 2022 `/RWALL` format has no "all" group id. For CYL/SPHER
    the starter measures `d` from the wall **surface** and keeps only
    `DISN >= 0`, so nodes already inside the obstacle are never auto-selected —
    correct, since an exterior wall cannot resolve an initial penetration.
  - `FRIC` maps by EXACT value, not by threshold. "FRIC could be any positive
    value. Three special values of FRIC trigger special treatments" (Manual
    p. 40-20), and the special set differs by family: the geometric card
    documents only `EQ.0.0` frictionless and `EQ.1.0` no-sliding (p. 40-8),
    while the planar card adds the WVEL-gated welds `EQ.2.0` / `EQ.3.0`. So
    `0.0 -> Slide 0`, exactly `1.0 -> Slide 1` (tied), anything else positive
    `-> Slide 2` with the coefficient on card 2 — a geometric `FRIC = 2.0` is a
    Coulomb mu of 2.0, and a planar `FRIC = 2.0`/`3.0` degrades to Slide 0 /
    Slide 1 with a warning naming the lost velocity gate. dyna2rad's geometric
    path instead does `FRIC > 0 -> Slide = 2, fric = FRIC`
    (`convertrwalls.cxx:234-238`), which turns LS-DYNA's tied `FRIC = 1.0` into
    a Coulomb coefficient of 1.0 — its single highest-impact rigidwall defect.
  - `*DATABASE_RWFORC` -> `/TH/RWALL` covers the new walls through the existing
    single-block path, prism faces included; a prism's reaction is therefore
    split across six entries, and that is warned explicitly (sum them before
    comparing against one LS-DYNA `rwforc` record). The `DEF` channels remain a
    time-accumulated **impulse**, as already documented.
  - Every spelling is generated, including `_ID` in a **non-final** position
    (`*RIGIDWALL_GEOMETRIC_SPHERE_ID_MOTION`): "the order of the OPTIONS is
    arbitrary" (Manual p. 40-4) and the cfg locates `_ID` with an unanchored
    `_FIND`, but the keyword parser only strips a TRAILING `_ID` into
    `block.options` — so without its own key the RWID header card would be read
    as Card 1 and the whole wall would vanish. A spelling that is still NOT
    understood (today: `_DEFORM`, whose Cards 3c.2/3c.3 sit between the cylinder
    card and the MOTION card) now reaches a keyword-PREFIX fallback that names
    the offending option and warn-skips, instead of leaving a bare
    skipped-keyword note.
  - LS-DYNA allows several **card sets** under one keyword ("for each rigid wall
    include one set of the following data cards", p. 40-5). k2rad converts the
    first set only and now says so loudly, in `warnings` and in
    `recognized_not_emitted`, instead of dropping the extra walls in silence.
  - `*INCLUDE_TRANSFORM`: every spelling gets an id-offset map (`NSID`/`NSIDEX`
    -> `IDSOFF`, `BOXID` -> `IDDOFF`, the `_MOTION` `LCID` -> `IDFOFF`, the
    `_DISPLAY` `PID` -> `IDPOFF`, the `_ID` header -> `IDPOFF`) whose card index
    walks past the shape card and any `NSEGS` sub-cards, and the TRANID
    transform now moves geometric wall geometry too — both wall points, the
    `_FLAT`/`_PRISM` edge head, and a `_MOTION` card's direction cosines under
    the linear part only. Wall dimensions (`LENL`/`LENM`/`LENP`, `RADCYL`,
    `RADSPH`) are warned, not rescaled, under scale/shear.

  New tests in `tests/test_rwall_geometric.py` and
  `tests/test_include_transform.py` (column-exact card lines, hand-computed
  diameters / corner points / skew axes, all six prism face normals recomputed
  the way the starter does, suffix-permutation dispatch, multi-wall and
  `/TH/RWALL` coverage). There is **no** `*RIGIDWALL_GEOMETRIC` deck anywhere in
  the reference corpora, so the corpus sweep proves no regression but exercises
  no new path — the fixtures and the starter/engine runs are the evidence.

### Fixed

- **The mandatory tiebreak Card 4 shifted every optional-card read by one
  row.** Vol I R17 p.11-6 lists Card 4 as required for the whole family and the
  optional Cards A–G follow *after* it, but `handle_contact_tiebreak` delegated
  with `extra = 0`, so `_read_contact_ignore` took `IGNORE` from optional
  Card B field 1 = `THKOPT`. Proven with a with/without twin — two decks
  identical except for the presence of Card 4, both carrying `IGNORE = 2` on
  Card C: the plain one reported `ignore=2`, the tiebreak one **`ignore=0`**.
  The consequences were a factually wrong warning on every such deck and, on an
  implicit deck, a diverging card (`_ignore_to_inacti` returns 5 for a misread
  `THKOPT ∈ {1,2}` *before* reaching the `is_implicit and gapmin > 0` branch
  that would have kept `Inacti = 0`). `_tiebreak_card4_extra` now also counts
  Card 4.1a (`_DAMPING` **and** `OPTION 9/11`) and Cards 4.1b + 4.2b
  (`OPTION 13/14`). The same routine's last branch printed a hard-coded
  `ignore=0` for any value outside `{0,1,2}` — it now prints the value it read.

- **`*CONTACT_*_ID` free-parsed its fixed-format header.** The card is
  `CARD("%10d%-70s", _ID_, TITLE)` and LS-PrePost butts the title against the
  id, so a free split of `"        10Kurbel self tiebreak contact"` yielded the
  single token `10Kurbel`, which reads back as **id 0** — the deck's own
  interface id was silently replaced by an auto-id (breaking
  `--inter-gapmin ID=…`, the `/TH/INTER` keying and every log line naming the
  interface) and the first word of the title was eaten. The fixed read is tried
  first now, with the free split kept as the fallback for a comma- or
  space-separated header. Measured on the prime carrier: `/INTER/TYPE7/90001` /
  `"self tiebreak contact"` became `/INTER/TYPE2/10` /
  `"Kurbel self tiebreak contact"`.

- **An all-zero `*DAMPING_PART_STIFFNESS` aborted the whole conversion.**
  Surfaced by the damping batch above and fixed with it. `_make_damping`'s early
  return only fires when there is neither a `*DAMPING_GLOBAL` nor any
  `*DAMPING_PART_STIFFNESS`, so a deck carrying a stiffness card whose every
  `COEF` is `0.0` reaches the `beta == 0.0` Format-1 branch with
  `state.damping_global` still `None` — and that branch opened with
  `d = state.damping_global; per_dof = (d.stx, …)`. Verified against master
  `62a53e8` on a one-shell deck holding nothing but
  `*DAMPING_PART_STIFFNESS / 1  0.0`:

  ```
  MASTER CRASH: AttributeError: 'NoneType' object has no attribute 'stx'
  ```

  It is an `AttributeError` out of the writer, so it takes down the **entire**
  conversion — no starter, no engine, no warning list — not just the one card.
  The per-DOF tuple now falls back to all-zeros when there is no
  `*DAMPING_GLOBAL`, which leaves the emitted card byte-identical on every deck
  that did not crash.

- **Motion/load variants, review round.** Twelve defects found against the batch
  above by an adversarial fidelity pass, a code review and an end-to-end solver
  campaign, verified against `hm_cfg_files`, the starter/engine sources and the
  pinned manuals before acting. Two were REGRESSIONS vs `master`, four more were
  silent-wrong loads or kinematics, the rest documentation of record.

  **1. An unhandled `VAD` aborted the whole conversion.** `_pm_vad_supported`
  enumerated only the known-bad values (`3` and `4`), so any OTHER value — a
  typo, a negative, a future LS-DYNA code — passed the guard and reached the
  writer's bare `{0:IMPVEL,1:IMPACC,2:IMPDISP}[pm.vad]`: `KeyError`, traceback,
  no deck at all. Reproduced on both paths (`VAD=7` on `_RIGID`, `VAD=9` on
  `_SET`); `master` produced a deck via `.get(vad, "IMPDISP")`, so this was
  strictly worse. The mapping now lives in ONE place, `state.PM_VAD_KEYWORD`,
  which the guard tests membership of and the writer indexes — the guard is
  total by construction, and a test asserts the two agree for `VAD` in
  `-2..12`.

  **2. A BLANK continuation card swallowed the NEXT entity's card 1.** Every
  field of card 3 defaults (`OFFSET1 0., OFFSET2 0., LRB 0, NODE1 0, NODE2 0` —
  Vol I R16 p.753), so an all-blank card 3 is legal input. `_bpm_walk` skipped
  blank lines while hunting for it and then advanced unconditionally, eating the
  following row. Measured: a `_SET` block with `nsid 20, DOF 11, VAD 0`, one
  blank line, then `nsid 21, DOF 2, VAD 2, curve 10, SF 2.0` — `master` emitted
  entity 2's `/IMPDISP`, HEAD emitted NOTHING and never mentioned it. The
  `assembly._bpm_cards` half was worse (and pre-existed on `master`): entity 2's
  card 1 got the CONTINUATION id spec, leaving NSID un-offset, `VAD+IDPOFF`,
  `LCID+IDNOFF` and the float `SF` rewritten as `5002`. Cards 2 and 3 are
  POSITIONAL and are now consumed as such in both walkers — blank means
  all-defaults — while only the card-1 hunt skips blanks (an all-default card 1
  has `TYPEID 0` and is not an entity).

  **3. `SF = 0.0` became a FULL-scale pressure.** `hm_read_pload.F:167` is
  `IF (FCY == ZERO) FCY = FAC_FCY`, so a `/PLOAD` written with `Fscale_y = 0` is
  silently replaced by the unit-system factor. Measured on a live starter: a
  `*LOAD_SHELL_ELEMENT / 1 10 0.0` row echoed `SCALE-Y 1.000000000000` — unit
  magnitude with the sign INVERTED — while its blank-`SF` sibling echoed `-1.0`.
  This is the exact `read_impvel.F:248` trap the batch already documents for
  `_pm_lock_cards`, one function away. Every card in the family documents
  `SF ... Default 1.` (p.33-99 / p.33-115 / p.3421) and LS-DYNA applies its
  defaults on a ZERO test — the same keyword family spells that out for `DEATH`,
  "EQ.0.0: default set to 1e28" — so `0.0` now reads as `1.0`, WARNED, because a
  zeroed `SF` is also a common way of switching a load off by hand and `/PLOAD`
  cannot express either reading of a zero. Applied to `*LOAD_SHELL`,
  `*LOAD_SEGMENT` and `*LOAD_SEGMENT_SET` (the last two pre-existing), plus a
  belt-and-braces refusal in the emitter so no literal `0` can ever reach the
  card.

  **4. Plain `*LOAD_SEGMENT` dropped the arrival time `AT` silently.** Field 2
  was never read — the code's own comment listed it, its `_SET` sibling now
  routes `AT` to a `/SENSOR/TIME`, and the summary warning implied `AT` was
  covered everywhere. Measured: `*LOAD_SEGMENT 10 2.0 0.004 1 2 3 4` produced
  `sensor_ID = 0` and ZERO warnings, i.e. the pressure started at `t = 0`
  instead of `t = 0.004`. `PressureLoad` carries `at` now and joins the
  three-element group key, so the existing `/SENSOR/TIME` emitter picks it up;
  Remark 3 (p.33-101) confirms the shift semantics ("evaluated at the offset
  time given by the difference of the solution time and AT").

  **5. `_SET_BOX` with `NSID = 0` drove nodes k2rad had SYNTHESIZED.**
  `_box_node_ids` scanned `state.nodes`, which by write time also holds the
  `/RBODY` CoG masters, the `/SKEW/MOV` third nodes, the rigid-wall carriers and
  this batch's own `_LOCAL` triads. Measured: a box round a `*MAT_RIGID` brick
  meshed on nodes 11-18 emitted `/GRNOD/NODE ... 11 … 18 19`, where 19 is the
  synthesized `/RBODY` MASTER — so the `/IMPVEL` drove the whole body, a
  kinematic condition the source deck never states (starter WARNING 312,
  0 ERRORS, restart written: the wrong model runs). The `if not box_nodes` guard
  cannot see it, because the box DOES contain nodes. `build_starter` now
  snapshots the deck's own node ids into `state.source_node_ids` before any
  prepass synthesizes one, and `_box_node_ids` intersects with it — which also
  closes the same flaw on the pre-existing rigid-wall and `/INIVEL` `BOXID`
  paths.

  **6. `_RIGID_LOCAL`'s triad now comes from the DECK, not the global axes.**
  LS-DYNA takes the local system from "LCO and CID in `*MAT_RIGID` and
  `*CONSTRAINED_NODAL_RIGID_BODY`, respectively. If LCO/CID is 0, the local
  coordinate system defaults to the principal inertia directions" (p.756-757
  Remark 7). k2rad ALREADY parsed the CNRB's `CID` — with zero consumers — so
  the triad was global-aligned even when `/SKEW/FIX/40` carrying exactly the
  right axes sat in the same `.rad`, and the warning asserted k2rad read neither
  field. Measured: `*CONSTRAINED_NODAL_RIGID_BODY 500 40 200` with a `CID 40`
  whose local x is global `+Y` gave `N1->N2 = +X`, i.e. 90° wrong AT `t = 0`,
  not the "exact at t=0" the warning promised. `handle_mat_rigid` now reads card
  3 as well (`LCO or A1 A2 A3 V1 V2 V3`, Vol II R16 p.2-233 — a non-zero
  `V1/V2/V3` selects the vector form, whose triad is `c = a × v`, `b = c × a`;
  a lone non-zero field 1 is `LCO`), and `_local_body_basis` resolves CNRB
  `CID`, `*MAT_RIGID` `LCO` and the `A1-V3` pair through the `/SKEW` k2rad
  already emits. Named systems are now EXACT; only the LCO/CID = 0
  principal-inertia default is approximated, and the warning says which case it
  is in and how to make it exact. This closes the measured 30° fidelity gap on
  the solver campaign's `t4c` (a 40×20×20 box rotated 30° about Z: `u_y` was
  0.49935 mm, 50 % of `|u|`, short).

  **7. The `_LOCAL` helper triad shifted the written `/RBODY` master.** The
  three helpers must be `/RBODY` secondaries to co-rotate, and `_make_rbodies`
  used that same node list for the `--rigid-cog-master` centroid — so the master
  landed at (22.036364, 2.036364, 2) instead of the mesh centroid (22, 2, 2),
  0.9 % of the body span, because the offsets are 0.1·span. Inert at runtime
  (`hm_read_rbody.F` forces `ICoG` and relocates the master to the true CoM; the
  helpers are massless) but a silently wrong pre-run coordinate, and wrong
  outright the moment `ICoG=2` is ever emitted. Both `_make_rbodies` and
  `_make_cnrb_rbodies` take the centroid over the MESH nodes only now.

  **8. Triads were built for motions the writer then dropped.** The prepass
  created three element-free nodes and folded them into the `/RBODY` group before
  `_make_imposed_motions` decided anything, so a `|DOF|` of 9/10/11/12 (no
  `/IMP*` `Dir` letter) or a pid with no `rbody_info` left unexplained nodes plus
  a warning describing a `/SKEW/MOV` the `.rad` never contained. The prepass now
  skips DOFs with no `Dir`, and any triad whose card is dropped later still gets
  its `/SKEW/MOV` written (an unreferenced `/SKEW` is inert) so nothing in
  `/NODE` is unaccounted for.

  **9. Two summary warnings described conversions that had not happened.** Both
  new paragraphs fired on the presence of a PARSED card (`if
  state.body_load_vectors:` / `if state.body_load_rots:`), so a
  `*LOAD_BODY_VECTOR` with a missing `LCID` warned "load curve 999 not found —
  skipped" and then asserted the `/GRAV` + `/SKEW/FIX` mapping anyway. Both are
  gated on emission now, matching the `*LOAD_BODY_{X,Y,Z}` paragraph beside
  them, and the `#- ROTATIONAL BODY LOADS` section header is buffered so it
  cannot dangle.

  **10. `/GRNOD` id allocation was inconsistent inside one function.** The
  motion path drew from `next_grnod_id()`; the `SF = 0` → `/BCS` path four lines
  away still used plain `next_id()`, so a user `*SET_NODE` at or above the
  auto-id base could land on the same `/GRNOD` id twice — starter ERROR 79
  DUPLICATE ID / IN NODE GROUP DEFINITION, no restart file, which is exactly the
  hazard `next_grnod_id` exists to close.

  **11. Dispatch and walker coverage.** `*LOAD_BODY_GENERALIZED_SET_NODE` and
  `_SET_PART` were still mute `skipped_keywords` entries — the manual's name is
  `*LOAD_BODY_GENERALIZED_OPTION` with OPTION in {SET_NODE, SET_PART} (p.33-31)
  and only the bare form was registered, i.e. the two spellings a real deck
  actually uses were the ones the registration failed to cover.
  `_pm_skew_for`'s `VID` fallback omitted `state.coord_nodes`, so a `|DOF| 4/8`
  card naming a `*DEFINE_COORDINATE_NODES` system took the "no /SKEW exists …
  THE DIRECTION IS WRONG" exit while `_emit_skew_from_nodes` had put that very
  skew in the deck. `_carries_literal_axis_point` called `_bpm_cards` without
  `is_box`, the one call site the two-card walk was not threaded through. A
  `*LOAD_SHELL` row with a blank/zero `EID`/`ESID` was dropped with no warning,
  unlike every other rejection in that handler.

  **12. Documentation of record.** The `-4`/`-8` lock warning now names the
  precondition k2rad does NOT test — the negative forms apply "to rigid bodies
  [only] if |CMO| = 2" (p.750), and since the manual does not say what LS-DYNA
  does instead, the lock is still emitted but flagged as a possible
  over-constraint. `_centri_frame` no longer claims "LS-DYNA reads the centre
  fields only when CID is blank": `*LOAD_BODY` is SILENT on the interaction
  (p.33-27 describes `CID` as the acceleration's system only) and the sibling
  `*LOAD_BODY_GENERALIZED` documents the OPPOSITE for its own card — "the
  coordinate (XC, YC, ZC) is defined with respect to the local coordinate system
  if CID is nonzero" (p.33-32) — so the docstring and the warning now present
  CID-wins as k2rad's choice, following dyna2rad, with both readings named. The
  `handle_load_shell` docstring said "/PLOAD's attribute is `Fscale_y`"; the cfg
  attribute is `magnitude` (`radioss2021/LOADS/pload.cfg:25`) and `Fscale_y` is
  only the COMMENT label — the substantive claim (dyna2rad's `Fscale_Y` write is
  discarded and the cfg default `1.` survives) is unchanged and holds. Stale
  comments on `next_grnod_id` and on `_make_imposed_motions`' id counter
  corrected; the box resolution is memoized so N rows on one missing box report
  it once; the `_SET_BOX` label is built only where it is used and the resolved
  node lists are carried with their rows instead of keyed on `id(pm)`.

  **Regression evidence.** 201-deck roster (73 repo + 127 `Ryan_Lee_Examples` +
  1 `ls-dyna_example`; 100 distinct file contents — the corpora hold byte-equal
  copies of the same deck under several paths, 4x `tobias_mesh.k` at 195 MB
  among them) converted with `origin/master` (2d067cf) and with HEAD:
  **100/100 byte-identical on both `_0000.rad` and `_0001.rad`**, 0 conversion
  failures either side, identical warning sets and skip lists (1205 distinct
  warnings, delta +0). Measured, not assumed: the corpus contains ZERO decks with
  any of the five new spellings, and every changed shared path is a no-op on it
  (`_bpm_walk`: 39 decks / 103 rows, all `DOF ∈ {1,2,3,5,6,7}`, `VAD` all `2`,
  `VID` literally `0`, ZERO rows needing a continuation card; `SF = 0` guards: no
  zero-`SF` pressure row anywhere; `AT`: every `*LOAD_SEGMENT[_SET]` row carries
  `AT` blank or `0.0`; `next_grnod_id`: no deck pairs a `*SET_NODE` at/above
  90001 with a zero-scale motion; `_box_node_ids`: the only `*DEFINE_BOX` in the
  corpus feeds a contact, not a box-scoped load).

  **Re-validation of the solver-validated decks.** Of the 17 decks the batch's
  solver campaign ran, 14 regenerate BYTE-IDENTICALLY against the pre-review
  commit. The three movers are the `_RIGID_LOCAL` decks, whose only changed data
  line is the `/RBODY` master coordinate — `(0.2483682545, 0.2483682545, 0)` →
  `(0, 0, 0)` on t4a/t4b and `(0.40582742, 0.40582742, 0)` → `(0, 0, 0)` on t4c,
  i.e. the fix. All three were re-run on the real solver
  (`starter_win64`/`engine_win64`, np=1 nt=6): **0 ERRORS, 0 WARNINGS, NORMAL
  TERMINATION each**, and every measured quantity reproduces its ANALYTIC target:
  t4a/t4c master `u_x` = 0.99869615 mm vs 1000·t_end (+0.0000%), `u_y = u_z = 0`
  exactly, worst mesh-node deviation from a pure global-X translation 6.9e-08 mm;
  t4b body rotation worst `|θ − ωt|` = 2.42e-07 rad over a full revolution, CoG
  trajectory within 0.048% of the one-DOF co-rotating solution at s = π/2, π and
  ~6, prescribed component `|v·x̂′ − 1000|` ≤ 1.06 mm/s (the T01
  central-difference resolution). The written coordinate is a pre-run value only:
  `hm_read_rbody.F:244` is `IF(ICDG == 0) ICDG=1`, so the starter relocates the
  master to the mass-weighted CoG and the massless helpers cannot move it.

  2768 tests + 851 subtests pass (+52 tests / +35 subtests over the batch;
  the master baseline is 2633 / 787, verified independently), ruff clean.

- **`*LOAD_BLAST_ENHANCED` `UNIT=6/7/8` had no unit mapping, and the docs said
  the table was complete.** The `UNIT` table was transcribed from a five-row
  LSTC note ("Blast Loading in LS-DYNA"), but the keyword defines **eight**
  values — verified by full-text extraction of both pinned manuals, Vol I R16
  p.33-17 and R17 p.33-17, which agree word for word:

  | `UNIT` | LS-DYNA system | `/BEGIN` |
  |---|---|---|
  | 1 | pound-mass, foot, second, psi | *(none — imperial)* |
  | 2 | kilogram, meter, second, Pascal | `kg m s` |
  | 3 | dozen slugs (lbf-s²/in), inch, second, psi | *(none — imperial)* |
  | 4 | centimeters, grams, microseconds, Megabars | `g cm mus` |
  | 5 | user conversions (Card 2) | *(none — unnamed)* |
  | 6 | kilogram, millimeter, millisecond, GPa | `kg mm ms` |
  | 7 | metric ton, millimeter, second, MPa | `Mg mm s` |
  | 8 | gram, millimeter, millisecond, MPa | `g mm ms` |

  `6/7/8` are as physically consistent as `2` and `4` — `kg·mm/ms² = kN` over
  `mm²` is `GPa`; `Mg·mm/s² = N` over `mm²` is `MPa`; `g·mm/ms² = N` over `mm²`
  is `MPa`, each matching the pressure unit the manual states — and every label
  they need (`kg`, `mm`, `ms`, `Mg`, `g`) is already in the starter's grammar,
  so all three now map automatically instead of falling to the
  "no automatic mapping" warning. `UNIT=7` is exactly k2rad's own default
  `Mg mm s`. The docstring table, `README.md` and the warning text all carry the
  manual's eight rows now, and the warning renders the mapped flags **from the
  table** so the two cannot drift. The starter-grammar test loops `range(0, 12)`
  instead of `range(1, 6)` and asserts which flags are mapped, so a new row
  cannot slip past unchecked; it also imports `_SI_PREFIX_FACTORS` from the
  writer rather than re-typing the 22-entry prefix set, closing the second copy
  of that grammar.

  The legacy `*LOAD_BLAST` card shares the mapping function but its `IUNIT` is
  documented `1..5` only (Vol I R16 p.33-11/33-12: the list ends at "EQ.5: user
  conversions will be supplied" and runs straight into `ISURF`), so it now
  passes `legacy=True` and `6/7/8` are **not** applied there — a legacy deck
  carrying one is malformed, and inventing a unit system LS-DYNA itself would
  not apply is exactly the silent-wrong-units failure this batch is about.
- **`*LOAD_BLAST_ENHANCED` `UNIT=4` wrote a `/BEGIN` time label the starter
  rejects.** The blast `UNIT` flag sets the `/BEGIN` unit labels (the TM5-1300
  formula is unit-dependent — `/LOAD/PBLAST` converts its internal `{g, cm, mus}`
  data using them), and `UNIT=4` mapped the microsecond to `micros`. That is not
  a label OpenRadioss can read: `unit_code.F:70-98` splits the `%20s` field into
  an SI prefix plus a base letter and accepts a token of **one, two or three**
  characters only; a longer one takes the `ELSE` branch at `:92-98`, which blanks
  `CUNIT` and sets `IERR1=0`, and the test at `:151-158` then fires
  `ANCMSG(MSGID=573)` **INVALID UNIT CODE**. Measured end to end on a converted
  `UNIT=4` deck: master writes the bad label on **both** unit lines and the
  starter answers `2 GLOBAL UNITS ERROR(S)`, exit 2 — while reporting the time
  factor as `1.0E+00`, i.e. seconds, a silent 1e6 error had the run continued.
  The correct label is **`mus`** (what `begin.cfg:127` itself lists, and what
  the `/LOAD/PBLAST` reader echoes as `DEFAULT UNIT SYSTEM IS {g,cm,mus}`); the
  same deck now gives `0 ERROR(S)`, exit 0, with `TIME 1.0000000000000E-06`.
  The rest of the table was audited against the same source and is correct
  (`kg`/`m`/`s` for `UNIT=2`, and `g`, `cm`; `UNIT=1/3/5` deliberately have no
  automatic mapping — `UNIT=3`'s inch has no legal `*m` label at all).
  **That audit was itself incomplete and is corrected below** — it covered only
  the five rows of an older LSTC note, while `*LOAD_BLAST_ENHANCED` defines
  eight. The PR
  #112 transcription of the prefix table in `writer/materials.py`
  (`_SI_PREFIX_FACTORS`, `_time_unit_in_seconds`) was cross-checked line by line
  against `unit_code.F:100-149`: all 22 entries match, including `mu`/`u` → 1e-6,
  both `k` and `K` → 1e3, and the `J > 3` / last-character-`s` rule. The two
  tables are deliberately **not** shared — `handlers.py` imports only
  `.parser`/`.state`, and reaching into `k2rad.writer` from a handler would
  invert the layer direction — so the constraint is documented at both ends
  instead, and a new test walks the whole `_blast_unit_system` table against the
  starter's grammar (length 1-3, base letter by slot, prefix from the table).
- **`*RIGIDWALL_PLANAR_*FORCES` dropped its extra card, and that blocked the
  multi-card-set guard on the whole planar family.** The `_FORCES` option
  appends one card — `SOFT SSID N1 N2 N3 N4`, always the **last** of the set
  whatever order the options are spelled in the keyword name (Manual p. 40-17
  Card Summary: ID → 1 → 2 → [ORTHO 3,4] → [FINITE 5] → [MOVING 6] →
  [FORCES 7]). `handle_rigidwall_planar` advanced its card index for `_FINITE`
  and `_MOVING` only, so `SOFT` and `SSID` vanished without a trace, and the
  "further card line(s)" guard added for the geometric family in the previous
  release could not be extended here: it would have fired on all 15 corpus
  `*RIGIDWALL_PLANAR_MOVING_FORCES` decks (the W8 CrushBox family), reporting
  each wall's own FORCES card as a phantom second wall. The card is now consumed
  leniently — it is optional on the last card set, the same idiom the geometric
  `_DISPLAY` card uses — and then the guard applies. `N1..N4` are "Optional node
  for visualization" and drop in silence; `SOFT` (cycles over which the relative
  velocity is ramped to zero, softening the initial contact-force spike) and
  `SSID` (a `*SET_SEGMENT` splitting the wall force for per-area rwforc output)
  have no `/RWALL` equivalent and are warned when non-default. There is no
  second FORCES card and no `WPSET` field — a full-text scan of Vol I R16 and
  R17 returns zero pages containing that string.
  Effect assertion: `Ryan_Lee_Examples/W8_SETUP_CrushBox.k` (+`_refined`,
  `_refined_angled`) convert to **byte-identical** `_0000.rad` / `_0001.rad`
  with the identical 16 warnings and the identical not-emitted set, while a
  synthetic `_FORCES` deck with `SOFT=3 SSID=7` gains the two warnings and a
  two-card-set deck — plain or `_FORCES` — is now caught instead of silently
  losing its second wall.
- **Eleven legal `*RIGIDWALL_PLANAR` spellings had no registry row, and the
  offset table had already drifted from the handler table.** "The ordering of
  the options in the keyword name is unimportant. For example, both
  `*RIGIDWALL_PLANAR_ORTHO_FINITE` and `*RIGIDWALL_PLANAR_FINITE_ORTHO` are
  valid and have the same effect" (Manual p. 40-16) — only the *card* order is
  fixed. The registry listed the canonical orderings only, so three `_ORTHO`
  spellings and **eight of the sixteen** legal non-ORTHO orderings
  (`_FORCES_MOVING`, `_MOVING_FINITE`, `_FINITE_ORTHO`, …) missed the
  exact-match lookup; with no `RIGIDWALL_PLANAR` row in `_PREFIX_HANDLERS` to
  catch them they fell into the generic skipped-keyword list, so the wall
  vanished from the model and the user was told only that "a keyword" was
  skipped — never that a rigid wall was lost.

  All 65 spellings are now **generated** by `_rwall_planar_keywords()`, the same
  way `_rwall_geometric_keywords()` has generated the geometric family, and
  `assembly._OFFSET_SPECS` is generated from that one source instead of a
  hand-kept literal. That literal had already fallen three spellings behind the
  registry, which is live the moment `_ORTHO` becomes convertible: an unmapped
  keyword keeps its original `NSID`/`BOXID` while the rest of an
  `*INCLUDE_TRANSFORM` is offset, i.e. dangling or colliding references. A test
  now asserts the two tables cover the same set.

  Not generated, and deliberately: `_ID` (the parser strips a trailing `_ID`
  into `block.options`, and p. 40-16 lists it apart from the `{OPTION}` slots)
  and `_DISPLAY` (legal here and needing **no** extra card — the Card Summary
  stops at Card 7 — but registering it would start *converting* walls that are
  skipped today, which is a feature, not a fix; it stays a known gap).
- **The multi-card-set guard was duplicated verbatim across the two rigid-wall
  handlers.** Eleven identical lines, differing only in the family name in the
  advice. Extracted to `_warn_extra_rwall_card_sets()`; the message text is
  unchanged (both `tests/test_rwall_geometric.py` and
  `tests/test_rwall_variants.py` assert on its wording).
- **The `/TFILE` fallback frequency was a hard-coded `1e-3` with no relation to
  the run.** When no `*DATABASE_` card states an interval — 57 of the 201 corpus
  decks — the T01 frequency has to be invented, and the constant is wrong at
  both ends of the scale: on a 0.01 s impact (`W2_Door_Impact.k`) it wrote
  **ten** T01 records for the whole event; on a 100 s quasi-static run it would
  write a hundred thousand. It is now derived from the termination time,
  `ENDTIM/1000` — 1000 samples over the run, the same shape as the `/ANIM/DT`
  default (`ENDTIM/40`, 40 frames) immediately below it. A deck with no
  `*CONTROL_TERMINATION` (an include-only fragment, or one terminating on
  `ENDCYC`) keeps `1e-3` as a floor, because a zero `/TFILE` is *silently
  ignored* by the engine (`lectur.F:335`, `IF(DTH /= ZERO) …`) and the T01 would
  then be written at a frequency nobody chose. The derivation is warned about
  once, but only when the deck actually contains a `/TH` group — with no
  time-history block the invented number governs nothing anyone reads. All five
  golden fixtures ride this path and every one has `ENDTIM = 1.0`, so
  `1.0/1000 = 0.001` reproduces the checked-in `/TFILE 0.001` exactly: no golden
  regeneration.

  The derivation is **windowed**, not open-ended: an `ENDTIM >= 1e6` is treated
  as a sentinel rather than a run length and falls back to the `1e-3` floor.
  `*CONTROL_TERMINATION ENDTIM = 1e20` is the common idiom for a deck that
  really terminates on `ENDCYC`/`ENDENG` (neither of which k2rad converts), and
  scaling from it would derive `/TFILE 1E+17` — a T01 that never fires at all,
  a silent *total* loss of time-history output and strictly worse than the
  constant it replaced. The threshold is four orders of magnitude above the
  largest run length in the corpus (every one of the 201 decks states an
  `ENDTIM` between `8.5e-5` and `30`), so no genuine run is caught by it, and
  the warning names the sentinel as the reason.
- **A negative `*DATABASE_` `DT` was silently treated as "the deck said
  nothing".** "If `DT < 0.0`, the result will be output every `-DT` time steps"
  (Manual p. 16-7) — a cycle-based request. Radioss's `/TFILE` is a *time*
  interval with no cycle-based form, so it still cannot be honoured, but the
  derived-frequency warning no longer claims "no `*DATABASE_` card states an
  output interval" when one does; it says *positive* interval and names the
  cycle-based cards it had to ignore. (`DT == 0` really is "no output is
  printed", p.16-7, and is still skipped.)
- **`*DATABASE_DEFORC`, `*DATABASE_DISBOUT` and `*DATABASE_JNTFORC` were absent
  from the `/TFILE` minimum chain.** All three now drive a real `/TH/SPRING`
  (the first two are new above; JNTFORC has driven one since the joints batch),
  so leaving them out sampled a group the deck *did* ask for at whatever coarser
  frequency the other cards happened to set. `ABSTAT`, `BINARY_D3THDT`,
  `BINARY_INTFOR` and `SLEOUT` stay out on purpose: they have no `/TH` consumer
  at all, so honouring them would only thicken the T01 for channels that are not
  in it. Measured across the 27 corpus decks carrying `*DATABASE_JNTFORC`, its
  `dt` is never the minimum, so no corpus deck changes.
- **`/ANIM/DT  0. 0` on a deck with `ENDTIM <= 0` stopped the engine before
  cycle 1.** With no `*DATABASE_BINARY_D3PLOT` `DT`/`NPLTC`, the animation
  frequency is `ENDTIM/40`, which is `0.0` for a cycle-terminated deck
  (`*CONTROL_TERMINATION 0.0` with `ENDCYC`) — and nothing re-checked it. That
  card is not a harmless no-op: `freanim.F:131-134` raises `MESSAGE 293` ("TIME
  FREQUENCY AT WHICH DATA IS WRITTEN TO THE ANIM FILE MUST BE GREATER THAN
  ZERO") and calls `ARRET(0)`. The converter was silent about all of it. k2rad
  now **omits the card entirely** in that case, which is the branch
  `lectur.F:2648-2651` proves safe — `DTANIM0` stays zero from
  `anim_set2zero_struct.F`, `TANIM` is pushed to 1e30, no A-files and no error —
  and warns that no animation will be written, since silently getting none is
  its own failure mode. Verified end to end: the same deck `ERROR
  TERMINATION`s on master and `NORMAL TERMINATION`s with the card omitted. The
  `NPLTC` branch is guarded the same way: with `ENDTIM = 0` it no longer
  substitutes a 1 s run length (that stand-in stays reserved for a deck with no
  `*CONTROL_TERMINATION` at all, matching what `/RUN` is written with). No
  corpus deck has `ENDTIM <= 0`, so nothing changes there. The warning no longer
  *misattributes* the cause on a deck that does state `NPLTC`: it said "no
  `*DATABASE_BINARY_D3PLOT` states a positive `DT` or `NPLTC`" even when
  `NPLTC = 20` was right there, sending the user to edit the wrong card — it now
  names the zero `ENDTIM` that makes `ENDTIM/NPLTC` useless. (The test covering
  that branch was also fixed: its deck put `20` in columns 11-20, which is
  `LCDT` — `NPLTC` is field 4 — so it left `NPLTC` at `0` and exercised nothing.)
- **`PF = 1` on `*ELEMENT_DISCRETE` was ignored, and the deforc `1:1` claim was
  unqualified.** LS-DYNA gives a deck two ways to narrow the deforc element
  selection (Vol I R16 p.1944): `*DATABASE_HISTORY_DISCRETE_OPTION`, or
  `PF = 1` — the print flag, "EQ.0: forces are printed in DEFORC file, EQ.1:
  forces are **not** printed DEFORC file" (p.19-32). `handle_element_discrete`
  read field 6 as `S` and then jumped to field 8, never touching `PF` at all.
  It is now parsed into `state.deforc_suppressed_eids` and subtracted from the
  `*DATABASE_DEFORC` `/TH/SPRING` group. It is an **output** flag, so the
  `/SPRING` element itself is still emitted — dropping it would change the
  model, which the flag never asks for. `*DATABASE_HISTORY_DISCRETE` still has
  no handler; rather than leave the unqualified claim standing, the warning now
  says the group is a **superset** of the deforc file whenever that card is
  present in the deck. (`*ELEMENT_BEAM` has no `PF` field, so `disbout` has
  nothing to honour.)
- The `/TH/SPRING` emitter is renamed `_make_starter_th_discrete_connectors`
  (it emits `DISBOUT` as much as `DEFORC`) and its driving table is a
  `NamedTuple` holding real accessors instead of `getattr(state, "…")` strings,
  which no type checker or IDE rename could follow.
- Docs: README gains the LAW95 free-explicit **volumetric-ringing** note (at
  `PR ≈ 0.495` the bulk modulus is ~100× the shear modulus and essentially
  undamped, so the volume oscillates and can grow; mitigate with a ramped load,
  damping/bulk viscosity, or an implicit quasi-static run — and the `/MAT/LAW42`
  `funIDbulk` curve is not an escape hatch, since its ordinate is a
  dimensionless multiplier on the `Nu`-derived bulk and supplying it bypasses
  the no-curve branch's anti-buckling `P_FAC` floor), the starter's `/BEGIN`
  unit-label grammar next to `--units`, the full eight-row blast `UNIT` table,
  the `PF` / `*DATABASE_HISTORY_DISCRETE` qualification on the deforc `1:1`
  claim, and a section on the two output frequencies a deck does not state.
  `ROADMAP.md` marks `*DATABASE_DEFORC`/`_DISBOUT` → `/TH/SPRING` done and
  narrows the remaining gap on that family to `*DATABASE_HISTORY_DISCRETE`.
  The backlog's "README overstates
  `*DATABASE_SPCFORC` `REAC*` as forces" item is **stale**: README already
  states in bold that `REAC*` is a time-accumulated reaction impulse, with the
  `reaction_forces_th.F` / `bcs1th.F` / `resol.F` citations, the
  `F = d(REAC)/dt` recipe and the `/ANIM/VECT/FREAC` contrast — PR #93 fixed it
  and its own CHANGELOG entry records that. No change made.

- **`*RIGIDWALL_PLANAR` fixed infinite plane used a card layout that does not
  exist.** The emission put the search distance `d` in card-1 columns 41-60 and,
  for `Slide = 2`, the friction alone on a 20-column card of its own — neither
  is in `RWALL/plane.cfg` `FORMAT(radioss51)`, whose card 1 is exactly 4 x I10
  (40 columns) and whose card 2 is the 90-column `d fric Diameter ffac ifq`. The
  starter therefore read every following card one line early, at **0 ERRORS**.
  Measured on the real 2010 Toyota Yaris deck, whose four ground planes
  (`*RIGIDWALL_PLANAR`, `FRIC = 0.9`, `NSID` given) take the `Slide = 2` flavour:
  the stray friction card was read as card 2, giving `d = 0.9` and `fric = 0`,
  and the starter echoed `NUMBER OF NODES . . . 15` and `FRICTION COEFFICIENT
  0.000` for each — 15 of 1 492 728 nodes, frictionless. After the fix the same
  four walls echo `NUMBER OF NODES . . . 1492728` and `FRICTION COEFFICIENT
  0.9000`, and the five `WARNING ID 100213` ("unsupported field exists at the
  end of line") are gone. Without the friction card (`Slide != 2`) the block is
  one card SHORT instead, and the reader consumes the following block's header
  (`WARNING 100217`), leaving a mis-oriented, inert wall. Both families now go
  through one card writer.
- **`d` for a wall that tracks ALL nodes was sized from the mesh bounding-box
  DIAGONAL**, but the starter measures `DISN` from the wall SURFACE
  (`hm_read_rwall_{plane,paral,cyl,spher}.F`), so a wall parked further away
  than the mesh is wide tracked nothing and was emitted completely inert — the
  normal geometry for an impactor cylinder or sphere. `d` is now the maximum of
  the starter's own `DISN` over the eight model-bbox corners (each `DISN` is
  convex in X, so a corner attains the maximum), plus a 0.1% margin for the
  card's 10-significant-digit field. Measured: an elastic hex flying at
  5000 mm/s into a `RADSPH = 10` sphere 40 mm below it, `NSID = 0` — before,
  `NUMBER OF NODES . . . 0`, wall impulse exactly 0 and the impactor passed
  straight through at an unchanged −5000 mm/s; after, contact at
  t = 8.1901660e-03 s against a hand-computed 8.1889230e-03 s (**+0.015%**), CoM
  velocity reversing to +2441.88 mm/s, and `|wall impulse| = 1.261844e-02` N*s
  matching the impactor's `m*dv` to **-0.0000%**. A wall whose outward normal
  faces away from every node in the model is now warned instead of being
  silently inert.
- **Synthesized moving-wall carrier nodes are excluded from other walls'
  distance search.** They are real `/NODE` entries, and the starter excludes only
  a wall's OWN main node (`I /= MSR`), so a prism's six faces took each other's
  corner-mounted carrier nodes as secondary nodes at `DISN = 0` and the rigid-wall
  constraint fought the `/IMPVEL` driving them. They now go in `grnd_ID2`, which
  the starter applies AFTER the search. Measured on a moving 4x3x2 prism scoped
  to a 4-node plate: secondary-node counts per face fell from 8/5/6/3/2/0 (24, of
  which 20 were carrier nodes) to 4/2/2/2/2/0, and the starter's WARNING 312 lost
  its `RIGID WALL / IMPOSED ACCELERATION, IMPOSED DISPLACEMENT, IMPOSED VELOCITY`
  clause entirely (20 -> 8 conditions, the remainder being the expected box-edge
  overlap between faces). Faces that share a base point now also share one
  carrier node.
- **`*RIGIDWALL_GEOMETRIC_*_MOTION` carrier nodes are exempt from the implicit
  free-node guard.** On a `*CONTROL_IMPLICIT_*` deck they were swept into the
  `/BCS 111 111` singularity fix-up, which fights the `/IMPVEL`/`/IMPDISP` on the
  same node; the guard only knew about `*RIGIDWALL_PLANAR_MOVING` nodes.
  Measured on a `*CONTROL_IMPLICIT_GENERAL` deck with a moving prism: all six
  carrier nodes 5..10 used to land in `/GRNOD/NODE` `free_reference_nodes` under
  `/BCS/... 111 111`; now the deck has no FREE-NODE CONSTRAINTS block at all.
- The `_ID` header card is `CARD("%10d%-70s", _ID_, TITLE)` in both rigidwall
  cfgs, so a canonical unpadded title is *fused* to the id
  (`"       777my wall"`). The previous free split read that as the token
  `777my`, silently costing the wall both its user id and its name; both
  `*RIGIDWALL_PLANAR` and the geometric handler now slice the I10 field first
  and fall back to the free split. **This shifts `*RIGIDWALL_PLANAR` output on
  decks with a fused `_ID` header** (no corpus deck has that shape — they are
  all zero-padded with a blank title, which both readings agree on).

- **Eroding / node-to-surface contact + `*DEFINE_FRICTION` batch**
  (`*CONTACT_ERODING_SINGLE_SURFACE`, `*CONTACT_ERODING_SURFACE_TO_SURFACE`,
  `*CONTACT_ERODING_NODES_TO_SURFACE`, `*CONTACT_NODES_TO_SURFACE`,
  `*CONTACT_AUTOMATIC_NODES_TO_SURFACE` — each also `_MPP` — and
  `*DEFINE_FRICTION`) — the roadmap P1 "eroding/n2s contact batch +
  DEFINE_FRICTION" item. **All were `SKIPPED` before**, and these were the *only*
  unhandled `*CONTACT_` spellings left in the reference corpus: 30 ×
  `ERODING_NODES_TO_SURFACE` across the three W11 bird-strike decks and their
  unit-converted copies, 7 × `ERODING_SURFACE_TO_SURFACE` across the W9 missile
  decks. `dispatch()` is an exact dict lookup with no `CONTACT_` prefix
  fallback, and a skipped `*CONTACT` is not a missing output card — it is a
  missing load path, in impact decks whose entire point is the contact.
  The ten spellings are generated rather than hand-listed (same policy as the
  spotweld grammar), and every non-`_MPP` one is registered in
  `*INCLUDE_TRANSFORM`'s `_OFFSET_SPECS`.

  **The batch's defining decision: `/SURF/PART/ALL` for the solid side of an
  eroding contact, not the `/SURF/PART/EXT` every other k2rad contact uses.**
  This is the one thing that makes an eroding contact behave like one, and it
  is a delta against the reference converter, not a copy of it. `/INTER/TYPE25`
  already implements LS-DYNA's `EROSOP=1` exactly: the starter puts every
  interior (two-solid) face in the segment list with a *negative* stiffness
  (`i25sti3.F:950-951`, `C -----Case of internal segment : put stiffness to
  negative ------`), and the engine flips one active the moment a neighbour
  element dies (`check_surface_state.F:174-203`, `NB_CONNECTED_ELM==1 .AND.
  STFM(k)<ZERO → ACTIVATION`, then `STFM(K) = ABS(STFM(K))`). Interior segments
  only exist if the `/SURF` was built with `ALL` — `hm_read_surf.F:636-641`
  stores `EXT_ALL=2` for `ALL` vs `1` for `EXT`, and `ssurftag.F:122`
  (`IF(IEXT==1)THEN … C External surface only.`) masks every shared solid face
  in the `EXT` case. With `/EXT` the machinery still **arms** —
  `i25surfi.F:607-625` sets `IPARI(100)=1` on `IDEL>0 .AND. SOLID_SEGMENT>0`
  alone — and then has nothing to wake, so the crater face a dying brick
  exposes carries no segment, no stiffness and no friction, and **nothing in
  the solver output says so**. dyna2rad has precisely this gap: it builds every
  contact surface from a bare `PART` clause with no `opt_A`
  (`convertcontacts.cxx:264-274`), so `IELEM_M(2,I)` is never `>0`. It also
  parses `ISYM`/`EROSOP`/`IADJ` in the CFG and discards all three with no
  message — a grep for `EROSOP|IADJ|ISYM` over the whole `dyna2rad` tree returns
  zero hits, *including* `EROSOP`, the flag whose entire purpose is eroding
  contact.
  Independently checked rather than asserted: the same 2-brick deck converted
  both ways and run through the starter gives a restart file of **303 630 B with
  `/ALL` against 303 122 B with `/EXT`** — the extra interior segments are
  really there — at **0 ERROR(S)** either way.
  Escape hatches: `--eroding-surf-ext` (CLI) / a GUI checkbox reproduces
  LS-DYNA SMP's literal `IADJ=0`, and parts carrying **quadratic** solids fall
  back to `/EXT` on their own, because the 2022 Reference Guide p.372 wants
  `/EXT` there so the mid-side nodes take part in the contact. `IADJ=0`/blank is
  treated as 1 (LS-DYNA MPP hardcodes it to 1, Vol I p.11-66) and `EROSOP=0` as
  1 (hardcoded in both SMP and MPP, p.11-65), both said out loud. Caveat also
  said out loud: the 2022 Reference Guide p.372 states `/SURF/PART/ALL` "is not
  available with TYPE25" — the current OpenRadioss starter implements it and has
  no check that rejects it (grepped `EXT_ALL` across the whole starter: it
  appears only in `hm_read_surf.F`, `i25surfi.F` and the `/SET` plumbing), but
  an older binary may not.

  **Side topology follows the starter's own ILEV classification**
  (`hm_read_inter_type25.F:399-434`), verified in the starter echo (`CONTACT
  TYPES (1:S1/S1;2:S1/S2;3:N/S`): SINGLE_SURFACE → `surf_ID1` = the SSID surface
  with `surf_ID2=0` (ILEV=1); SURFACE_TO_SURFACE → both surfaces (ILEV=2);
  NODES_TO_SURFACE → `surf_ID1=0`, `grnd_IDs` = the SSID node group, `surf_ID2`
  = the MSID surface (**ILEV=3**). ILEV=3 is a genuine one-way contact, and
  dyna2rad does not symmetrize this family either (`surfAttrNames[0] =
  "grnd_IDs"`, `convertcontacts.cxx:128-129, 212-216`) — the one place it *does*
  lose one-way-ness is `AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE`, a different
  keyword k2rad routes elsewhere. `Istf` follows dyna2rad's two-branch `SOFT`
  if-chain including its undocumented asymmetry at `SOFT=2` (`:583-613` gives
  ERODING_SURFACE_TO_SURFACE and AUTOMATIC_NODES_TO_SURFACE `Istf=2` +
  `Iedge=22`; `:614-628` gives the other three the coarse `Istf = 4 if SOFT>=1`).
  `Idel=2` rather than dyna2rad's `1`: `2` removes the main segment as soon as
  **one** attached element dies, which is LS-DYNA's own per-element face removal
  and the literal engine split (`check_surface_state.F:155-171` runs
  `CHECK_ACTIVE_ELEM_EDGE` for `IDEL==1` and sets `DEACTIVATION=.TRUE.`
  unconditionally for `IDEL==2`); dyna2rad's `1` is just a copy of its
  per-interface-type default table (`convertcontacts.cxx:47`), which has no
  eroding-specific logic at all.

  **`*DEFINE_FRICTION` → `/FRICTION`, id preserved 1:1** (which is what makes
  the `fric_ID` binding work at all). LS-DYNA's `μ = FD + (FS − FD)·exp(−DC·
  |v_rel|)` maps **exactly** onto Radioss `Ifric=2` (Darmstad) with `Fric = FD`,
  `C5 = FS − FD`, `C6 = −DC` and `C1..C4 = 0`, because the engine's
  `XMU = FRICC + C1·e^(C2·v)·p² + C3·e^(C4·v)·p + C5·e^(C6·v)`
  (`i7for3.F:1911-1914`) collapses to `Fric + C5·e^(C6·v)`. That is dyna2rad's
  mapping (`convertfrictions.cxx:64, 94-97`) and the only 2022-legal one:
  Radioss's own exponential-decay law `Ifric=4` needs one fewer sign flip but is
  absent from `radioss2020/FRICTION/friction.cfg:87-93` (which offers 0-3) and
  from the 2022 Reference Guide p.223 — emitting it from a `/BEGIN 2022` deck
  would be `WARNING 100211` territory. The Card-1 defaults become the
  `/FRICTION` header row, which is not decoration: the engine SEEDS every
  contact pair from it (`frictionparts_model.F:88-92`) and a part-pair row only
  overrides where a pair matches, so the deck's default friction has to land
  there rather than on the interface card. Each Card-2 row becomes one pair
  block in deck order, un-expanded and un-deduplicated; a `PSET` row gets a
  `/GRPART/PART`. `Idir` is always 0 — `*DEFINE_FRICTION_ORIENTATION` is a
  separate keyword neither converter handles.
  Binding is `fric_ID` at **cols 91-100 of card 6** on `/INTER/TYPE7`
  (`radioss2020/INTER/inter_type7.cfg`) and `/INTER/TYPE25`
  (`radioss2022/INTER/inter_type25.cfg`), activated by *CONTACT Card-2
  `FS = −2`, with dyna2rad's rules: one table in the deck → it applies to every
  `FS=−2` contact regardless of `FD`; several → `FD` names the one; none or no
  match → friction 0 and a warning (dyna2rad's message 200029). **Minus
  dyna2rad's hole**: it reads the table id from `LSDYNA_FD_DefineFriction`, an
  attribute the LS-DYNA CFG only fills for the `_AUTOMATIC_` node-to-surface
  spelling (`contact_option_nodes_to_surface.cfg:2506-2548` gates the FS
  pre-read on `ContactOption == 2`), so with ≥2 tables it silently zeroes the
  friction of a plain `*CONTACT_NODES_TO_SURFACE` whose table exists — k2rad
  reads the raw FD column itself. The binding is written on **every sliding
  interface type this converter emits** — `TYPE7` (`radioss2020/INTER/
  inter_type7.cfg` card 6), `TYPE11` (`radioss2020/INTER/inter_type11.cfg:
  409-410`, a card of its own: 90 blank columns then `%10d`, read by
  `hm_read_inter_type11.F:185` into `IPARI(72)`), `TYPE19`
  (`radioss2021/INTER/inter_type19.cfg:801-802`, appended to the `Ifric` card;
  the hm_reader carries it onto every child interface the TYPE19 expands into,
  `GlobalModelSdi.cpp:1247/1341/1432`) and `TYPE25`
  (`radioss2022/INTER/inter_type25.cfg` card 6) — all four at cols 91-100. Only
  `/INTER/TYPE2` and `/INTER/TYPE10` are excluded, because they are *tied*
  interfaces with no friction model at all; an `FS=−2` on one of those gets a
  loud warning naming the interface instead of a silently frictionless run. The
  extra columns are written only when a table is actually bound, so a
  table-free deck stays byte-identical. `inter_dcod_friction.F:80` confirms the
  accepted set is exactly `NTYP 7/11/19/21/24/25`. One caveat k2rad now states
  up front: on an **edge** contact the pair *coefficients* act but the `Ifric=2`
  Darmstad velocity decay does not — `inter_dcod_friction.F:101-112` raises
  `WARNING 1595` for `NTYP==11` whenever the table's `FRICMOD > 0` and copies
  only `FRICFORM` into `IPARI(30)`, and the engine agrees (`i11mainf.F:233-241`
  pulls the pair tables, `i11cor3.F:386` resolves the pair, but `i11for3.F` uses
  the flat `FRICC` with no `exp` term). `/INTER/TYPE19` inherits it through its
  TYPE11 child; its TYPE7 child gets the full law. Only the `DC` term is lost,
  and the contact is **not** frictionless — which is what it used to be.

  **Fixed on the way through.** `FS = −1` ("the `*PART_CONTACT` coefficients are
  to be used") was written straight through as `Fric = −1` — a *negative* Coulomb
  coefficient on the interface card, on every contact family, silently. It now
  becomes `Fric=0` with a warning naming the interface. `FS = 2` is the same
  class of bug and gets the same treatment: it is the LS-DYNA sentinel for "`FD`
  is a friction *table* id", μ(contact pressure, relative velocity) — Vol I
  p.11-28 *"FS.EQ.2: Table ID for a table that specifies two or more values of
  contact pressure…"* — and used to fall through as a literal Coulomb
  coefficient of 2.0, which is 4-40× a real table's typical 0.05-0.5. It now
  writes `Fric=0` and warns **unconditionally**; the old warning was gated on
  the table being resolvable, so a blank, dangling or `*DEFINE_TABLE_2D` `FD`
  wrote μ=2.0 in total silence. `_select_parent_interface` and
  `_match_parent_interface` did not filter `state.dropped_inter_ids`
  (`writer/contacts.py:653`), so a deck whose first contact was dropped parented
  its `/INTER/SUB` — and the `/TH/INTER` parent id — on an interface that was
  never written: starter `ERROR 581` / `WARNING 257` on a conversion that
  reported success. Both now filter, and both were already ordered after every
  drop-registering writer, so no ordering work was needed.
  `_read_contact_soft`/`_read_contact_ignore` take an `extra` card offset,
  because the mandatory ERODING Card 4 (`ISYM`/`EROSOP`/`IADJ`) pushes optional
  cards A and C down one line — reading blind takes `ISYM` for `SOFT` and Card
  B's `THKOPT` for `IGNORE`, i.e. the wrong `Inacti`.

  **Side resolution.** A bare `SSID`/`MSID` of 0 used to expand to *every part
  in the deck* on both sides of every variant. LS-DYNA gives it that meaning on
  exactly one side of one family — Vol I p.11-24, *"SURFA … EQ.0: Includes all
  parts in the case of single surface contact types"*, against *"SURFB … EQ.0:
  SURFB side is not applicable for single surface contact types"*. A
  surface-to-surface or node-to-surface deck that simply dropped its `MSID` was
  therefore turned into a plausible-looking contact over the whole model, with
  the secondary part on *both* sides, and nothing said so. Now only a
  `SINGLE_SURFACE`'s `SSID` reads 0 as "all parts"; every other side falls
  through to the normal drop-with-remedy path. `SURFATYP`/`SURFBTYP = 5`
  ("include all non-spot-weld parts", p.11-25) is a different thing and still
  expands on either side.

  **Reported, not dropped in silence**: `ISYM=1` (no `/SURF` equivalent for
  "omit symmetry-plane faces"), `EROSOP=0`, `IADJ=0`, the SMP friction
  exclusion (Vol I p.11-65 remark 4 — SMP LS-DYNA runs
  `*CONTACT_ERODING_NODES_TO_SURFACE` and `*CONTACT_ERODING_SURFACE_TO_SURFACE`
  **frictionless** unless `SOFT=2`, while `/INTER/TYPE25` applies the friction
  unconditionally, so an SMP-authored deck *gains* friction it never had — the
  one direction every other note in this list does not cover), per-side
  `SST`/`MST` (the
  `Igap=5` + `THICK_S`/`THICK_M` route is radioss2026-only, so `/INTER/TYPE25`
  has nowhere to put them at 2022), Card-2 `DC` on a contact with no friction
  table, the `SOFT=2` companion flag `IPSTIF` (no 2022 column), the `_MPP`
  option cards, `VC` (LS-DYNA's viscous friction *stress cap*, `F_lim = VC ·
  A_contact`, is not Radioss's `VIS_f` friction damping coefficient — and
  `hm_read_friction.F:182` zeroes `VIS_f` for `Iform=2` anyway, as does
  `frictionparts_model.F:108-112` for NTY 24/25), an `ICNEP` flag, a
  `*DEFINE_FRICTION` row naming a part or part set the deck does not have *or
  whose part id column is blank*, a `/TH/INTER` block on a self-impact
  (`surf_ID2=0`) interface — whose `FN`/`FT` resultants are a signed sum over
  both sides and cancel, measured −63.6 % against the true `m·Δv` where the
  two-surface interface came in at +4.4 % — and the interaction with
  `Ishell=12`'s ~1.7× under-erosion (an eroding surface can only retreat as
  fast as elements actually fail).

  **Solver validation — the `fric_ID` binding on every type.** Three decks
  differing only in the `SOFT` sentinel (`-7` → TYPE7, `-11` → TYPE11, `-19` →
  TYPE19), each with `FS=-2` against a two-pair `*DEFINE_FRICTION`: starter
  **0 ERROR(S)** on all three, each echoing `INTERFACE FRICTION MODEL. 5` — the
  binding really is read on TYPE11 and TYPE19, which is what the old "no
  fric_ID column" claim denied — and engine **NORMAL TERMINATION** (19 185 and
  21 576 cycles). TYPE11 and TYPE19 additionally raise the informational
  `WARNING 1595` described above; TYPE7 raises none.

  Converting the same deck with the pre-fix package gives the control: zero
  `fric_ID` occurrences, i.e. the frictionless interface the old code produced,
  with the `/FRICTION` column fix and the `fric_ID` card as the only deltas.
  Running both, the TYPE19 pair diverges as it should — the prescribed motion
  now works against friction:

  | TYPE19 | cycles | I-ENERGY | EXT-WORK |
  |---|---|---|---|
  | no binding (old) | 21 502 | 100.1 | 192.5 |
  | table bound (new) | 21 575 | **159.0** | **715.2** |

  External work **3.7×**, internal energy **+59 %** — the friction the old code
  silently discarded, doing real work. The TYPE11 pair came out
  energy-identical: that rig is a slab-on-plates geometry built for surface
  contact, so its edge-to-edge interface carries no sustained sliding load and
  friction has nothing to act on. A rig limitation, not a binding one — the
  starter echo shows the table is read either way.

  **Solver validation.** A synthetic deck exercising all three eroding variants
  plus a bound `/FRICTION` runs the starter at **0 ERROR(S)** (2 warnings, both
  the unrelated `LAW1` integration-point note), and its echo reads every field
  back: `FRICTION MODEL 2 (Darmstad Law)` with `Muo=0.2 C5=0.2 C6=-1.5` from
  `FS_D=0.4 FD_D=0.2 DC_D=1.5` and the part-pair row `Muo=0.3 C5=0.2 C6=-2.0`
  from `0.5/0.3/2.0`; `INTERFACE FRICTION MODEL. 7`; `DELETION FLAG ON FAILURE
  OF MAIN ELEMENT (1:YES-ALL/2:YES-ANY/1000:NO) : 2`; `CONTACT TYPES` 2 for the
  surface-to-surface and **3** for both node-to-surface interfaces. The real
  corpus deck `W11_SETUP_SPH_BirdStrike.k` (two
  `*CONTACT_ERODING_NODES_TO_SURFACE`, one with `MBOXID`) converts and reaches
  starter **NORMAL TERMINATION, 0 ERROR(S) 0 WARNING(S)**. `W9_SETUP_
  MSLprojectile.k` converts its eroding contact to `/INTER/TYPE25/1` over two
  `/SURF/PART/ALL` solid sides, but still fails the starter on a **pre-existing**
  gap unrelated to this batch: `*MAT_CSCM_CONCRETE` is not converted, so PART 3
  has no material (`ERROR 179`/`61`/`3046`, and the 209 106 `WARNING 96` all
  read `MATERIAL OF SOLID ... IS EQUAL TO 0` on the pre-existing `/INTER/TYPE7`).

  **Corpus sweep.** Measured over **201 decks** — the 73 `.k`/`.key`/`.dyn`
  decks in the repo, the 127-deck `E:\openradioss_run\Ryan_Lee_Examples` tree
  and the one `E:\openradioss_run\ls-dyna_example` deck — `master` 7d504ba vs
  `feat/eroding-contacts`, 0 conversion exceptions on either side:
  **179/201 byte-identical on BOTH `_0000.rad` and `_0001.rad`, with identical
  warning sets and identical skip lists.** Total warnings 2172 → 2379. The 22
  that moved are exactly the 22 decks the census predicts — 15 `W11_SETUP_SPH_
  BirdStrike{,_Multi,_thick}` copies and 7 `W9_SETUP_MSLprojectile` /
  `W9s` copies — and every one of them moved only in the starter deck
  (`_0001.rad` unchanged on all 22: contacts live in `_0000.rad` alone).
  `CONTACT_ERODING_NODES_TO_SURFACE` leaves `skipped_keywords` on 15 and
  `CONTACT_ERODING_SURFACE_TO_SURFACE` on 7, which is the entire census of those
  two spellings. Each W9 copy gains 6 warnings (the interface, the `IADJ`
  reading, one `/SURF/PART/ALL` note per solid side, `Inacti`, and the
  once-per-deck erosion-rate note); each W11 copy gains 12 and LOSES one — the
  old "`*DATABASE_RCFORC` requested but no `*CONTACT` was converted" — because
  the two eroding contacts it now emits are what that request was for. +207 net,
  which is exactly 7×6 + 15×11.
  **What this corpus cannot see**: any deck with `*DEFINE_FRICTION`, with a
  contact `FS` of −1/−2/2, or with `*CONTACT_[AUTOMATIC_]NODES_TO_SURFACE` or
  `*CONTACT_ERODING_SINGLE_SURFACE` — the census counts all of those at **zero**
  occurrences. That evidence is the column-exact tests (built against the CFG
  `FORMAT` blocks field by field) plus the starter echo above, which is what
  actually reads the cards back.

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

  **Corpus census + sweep.** A structured scan of the **618** unique
  `.k`/`.key`/`.dyn`/`.inc` files across the repo, `E:\openradioss_run` (incl.
  `Ryan_Lee_Examples` and `ls-dyna_example`) and `E:\foxcore_data` finds **zero**
  hits for every keyword in this batch: none of the
  `*MAT_066/067/068/069/070/071/074/093/094/095/119/121/196` spellings, none of
  `*MAT_S03/S05/S06/S08`, and — read back through k2rad's own parser rather than
  a regex — the corpus's **24 `*SECTION_BEAM` sets (15 files) are ELFORM 1 (×10)
  and 9 (×14) with `SCOOR = 0` throughout, so there is no `ELFORM=6` section
  anywhere**. Two independent scans (a Python walk and a PowerShell
  `Select-String` pass) agree.

  The sweep is therefore a **pure no-movement check**, and it was run over
  exactly the decks that can reach code this batch touched — every deck carrying
  an `*ELEMENT_DISCRETE`, `*SECTION_DISCRETE`, `*SECTION_BEAM`,
  `*ELEMENT_PLOTEL`, `*MAT_SPRING_*`, `*MAT_DAMPER_*` or `*MAT_SPOTWELD`, i.e.
  the six W16/W17 spotweld decks (which exercise the refactored
  `_emit_prop_type13`), the Yaris and its variants and the Camry (the only decks
  in the corpus with `*ELEMENT_DISCRETE` at all), and the `ls-dyna_example`
  deck. Result: **16/16 byte-identical on BOTH `_0000.rad` and `_0001.rad`, with
  identical warning sets (12 705 warnings on each side) and identical skip
  lists.** The Yaris/Camry suspension springs are `*MAT_SPRING_ELASTIC` /
  `_NONLINEAR_ELASTIC` / `*MAT_DAMPER_VISCOUS` on `DRO=0` sections with blank
  `S`/`VID`/`OFFSET`, so every field this batch touches is at its pre-existing
  default there — which is exactly what the sweep confirms. The rest of the
  evidence is the 88 new column-exact tests plus the byte-identity canaries in
  `tests/test_discrete_springs.py::ByteIdentityTests`.

  **Review round (post-implementation), 15 confirmed defects fixed.** Every
  item below was verified against the OpenRadioss starter/engine source or the
  LS-DYNA manual before it was touched; the `.rad` output of all 8
  solver-validated decks is **byte-identical (SHA256) after the round**, so the
  measured force-deflection / hysteresis / 6-DOF numbers still describe the
  decks the engine ran.

  - **`*MAT_071`'s `LCID` is engineering STRESS, not force.** "The points on
    the load curve are defined as engineering stress versus engineering strain"
    (Manual Vol II R17 p.2-530) — the ordinates now get multiplied by the
    section area `CA` before they reach the `/PROP/TYPE13` function, which reads
    a FORCE. Passing the curve through raw made the cable a factor `CA` too
    weak, and added `F0` (a force) to stress ordinates. A blank `CA` refuses the
    curve with a warning instead of writing it unscaled — LS-DYNA gets zero
    force out of a zero-area cable too (`F = A·σ`).
  - **A one-sided cable curve made the cable PUSH.** The tension-only clamp was
    gated on the curve carrying negative force or on `F0` being kept, so a curve
    that merely starts at (0, 0) went through untouched and Radioss extrapolated
    its first segment into compression — the one behaviour `*MAT_071` exists to
    prevent. The clamp now always runs, and prepends a FLAT leading point so the
    extrapolated compression branch is zero (LS-DYNA holds a load curve at its
    end value, so the flat continuation is also the faithful end condition).
  - **The cable's `VOL` is no longer ignored.** "The cable mass will be
    calculated from length × area × density if `VOL` is set to zero on
    `*SECTION_BEAM`. Otherwise, `VOL` × density will be used" (p.2-531). A
    non-zero `VOL` now sets the mass, carried as `RO·VOL/L` because `Ileng=1` is
    not optional (it is what makes the stiffness and curve abscissae
    strain-based); the warning says so, and names the mean element length it
    divided by.
  - **`*MAT_074`/`*MAT_196`: `HLCID` was in the wrong slot.** It is an ADDITIVE
    force-vs-relative-velocity curve — `F = … + D·ΔL̇ + g(ΔL)·h(ΔL̇)` (p.2-553
    and p.2-1322) — and the engine's additive rate term is `Hscale·h(δ̇)` on
    `fct_ID4` (`redef3.F90:1143`, `gx2 ← ifunc3 ← IGEO(119) ← fct_ID4`), while
    `fct_ID2` is the MULTIPLICATIVE `E·g(δ̇)` inside the `A + B·ln(…) + E·g(δ̇)`
    bracket. Writing it to `fct_ID2` (dyna2rad's slot) made it multiply the
    deflection curve, and took `C1` down with it: with `HLCID` present `C1`
    became `C1·HLCID(rate)`, and without one `if(ifv(i)==0) gx(i)=zero`
    (`redef3.F90:1126`) made `C1` vanish silently. `HLCID` now goes to `fct_ID4`
    with `Hscale = 1`, and `C1` gets a 2-point IDENTITY function in `fct_ID2`
    with `E = C1`, which reproduces `1 + C1·ΔL̇` exactly (`vinter2` extrapolates
    the end segments, so two points cover the whole rate range). `GLCID` stays
    warn-dropped, now named as the deflection scale ON `HLCID` that it is.
  - **`K` is a dimensionless SCALE when `FLCID > 0`.** `[K] = unitless` for
    `FLCID > 0` against `[force]/[length]` when blank (p.2-1322 dimension
    table), and the elastic force is `K·f(ΔL)·[…]`. Radioss reads `fct_ID1` raw
    (`A` defaults to 1, `hm_read_prop04.F:220`), so the product is now baked
    into the ordinates and the `K` column carries the SCALED curve's tangent at
    the origin — the number the explicit time step actually needs. `K = 0` with
    a curve keeps the curve unscaled and says why (LS-DYNA's own formula gives
    zero force there).
  - **`/FUNCT` abscissae are now strictly increasing AS PRINTED.** The
    plastic→total tie-break was a fixed `1e-9`, which is below `_f`'s %.10G card
    resolution for `|x| ≥ 10` — `_f(20.0)` and `_f(20.0 + 1e-9)` are both `"20"`
    — so a `*MAT_068`/`*MAT_196` softening branch steeper than `-K` shipped a
    DUPLICATE abscissa and `hm_read_funct.F:143` answered `ERROR 156`
    (`IF (PLD(NPC(L+1)) <= PLD(NPC(L+1)-2))`, MSGERROR: the deck is refused).
    The nudge is now relative (`max(1e-9, |x|·1e-7)`) and `_emit_funct` carries
    a last-resort repair that checks the invariant on the CARD value, which also
    covers the cable's inserted zero crossing.
  - **A `/PART` id could be written TWICE.** `_discrete_beam_pids` excluded
    shell and solid parts but not `*ELEMENT_DISCRETE` parts, so a part claimed
    by both writers got two `/PART/<pid>` blocks — starter `ERROR 79`
    (DUPLICATE ID), deck refused. Reachable without anything exotic: a `*PART`
    with a blank `SECID` falls back to `secid = pid`, so a discrete-spring part
    whose id equals an `ELFORM=6` `*SECTION_BEAM`'s id lands in both sets. The
    `*ELEMENT_DISCRETE` side now wins and the discrete-beam writer reports what
    it lost.
  - **A resolved `CID` now reaches the `/PROP/TYPE13` card.** With `|SCOOR| = 2`
    the section's coordinate system was dropped silently. LS-DYNA keeps it:
    "a final adjustment is made to the local coordinate system so that the local
    r-axis lies along the n1 to n2 axis of the beam" (Manual Vol I R17 p.41-26,
    Remark 8) — the CID still fixes the other two axes, which is exactly what
    `r4buf3.F:194-203` reads the property skew for. The `skew_ID` is written,
    the partial-frame rule is warned, and the "no third node" message no longer
    promises a property-skew fallback the card did not carry.
  - **A dangling DAMPING curve no longer kills the hysteresis.** `*MAT_119` and
    `*MAT_121` zeroed `H` whenever ANY of the three curve slots named an
    undefined curve, including `fct_ID4`. The starter's `H` guards (MSGID 231 /
    1057 / 1058 / 1059) only ever test `fct_ID1` and `fct_ID3`, so a DOF with a
    valid loading and unloading curve is no longer demoted from `H=6/7` to `H=0`
    (which would dissipate nothing); `Hscale` is cleared with the slot.
  - **`*MAT_S02` registered.** `*MAT_DAMPER_VISCOUS`'s numeric alias is `S02`
    (Manual Vol II R17 p.2-2083 headers the card with both names; `MAT_D01`
    appears nowhere in the manual and is kept only as a k2rad legacy spelling).
    Without it an S02 deck lost the damper AND its `/PART`.
  - **`*MAT_S06`'s `BETA` warning was inverted.** The dropped-field test fired
    only when `BETA` was non-zero, so the deck that is faithfully converted
    (`BETA = 1.0` IS "isotropic hardening without strain softening", the emitted
    `H=6`) got warned and the one that is not (the BLANK default `BETA = 0.0` =
    "tensile and compressive yield with strain softening", p.2-2087) stayed
    quiet. It now warns for every `BETA ≠ 1.0` and names all three flavours.
  - **The per-element force scale `S` reaches a curve-driven damper.** `*MAT_S05`
    puts its whole payload on `fct_ID41`, which the engine adds as
    `Hscale·h(δ̇)` — the `A` coefficient never touches it, so two elements with
    `S = 1` and `S = 4` used to produce byte-identical properties. `Hscale` now
    carries the scale.
  - **Parts that could not be converted keep their id.** Every bad-input branch
    of the discrete-spring writer (`continue`) used to delete the `/PART` along
    with the elements, even though `_discrete_part_ids` claims the pid either
    way — so a `*SET_PART` member, a `/GRNOD/PART` scope or a contact naming it
    was left dangling. All of them (including a `DRO=1` part whose elements are
    all zero-length or grounded) now emit an INERT `/PROP/TYPE4` + `/PART`, the
    same guard the sibling discrete-beam writer already had.
  - **The oriented `DRO=1` connector's inertia** was a fixed `1e-6` while its
    unoriented twin used `mass·L²`. `rinit3.F:427-437` measures every
    TYPE8/13/25 spring against `Mass·L²` and answers `WARNING 432` outside a
    factor of 1000 either way, so the token tripped it on any element longer
    than ~3.2 length units. Both routes now use the starter's own reference.
  - **A discrete-beam material on a continuum part is reported.** Recognising
    the keyword removed the `skipped_keywords` line that used to be the only
    diagnosis: the `/PART` still carries the MID and no `/MAT` is written for a
    discrete-beam material, so the deck came out referencing a material it does
    not contain and the log said nothing at all. Same pattern as `*MAT_SPOTWELD`
    on a continuum part.
  - **Housekeeping.** The payload builders no longer run on a part whose section
    is missing or not `ELFORM=6` — their result was discarded but their warnings
    and their `/FUNCT` ids were not, so the log described a conversion that never
    happened. `state.dbeam_spring_eids` (populated, never read) was dropped until
    the `/TH/SPRING` route that would consume it exists, and the builder-contract
    comment now states the 5-tuple the builders actually return.

  Byte-identity re-checked at the end of the round over every corpus deck that
  can reach any touched code — the six W16/W17 spotweld decks, `W17_RS_FloorFrame`,
  the Yaris (`combine.key` + its two component decks) and the Camry, and the
  73 MB `Model-318_Achshebel-fein_tobi.k` — plus the 8 solver-validation decks:
  identical `_0000.rad`/`_0001.rad` SHA256 on both sides, with only the three
  intentionally-corrected warning TEXTS differing (the cable's no-third-node
  message, and `BETA` moving from the faithful deck to the unfaithful one).

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
