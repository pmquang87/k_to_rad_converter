# Radioss card → `.k` keyword: the k2rad route table

The CardStack FEM pipeline wrote its OpenRadioss decks by hand. Runs 03-26
converted only the mesh with k2rad and appended hand-written `/GRAV`, `/DAMP`,
`/RWALL`, `/BCS`, `/IMPDISP` and `/FUNCT` text; runs 12-21 patched k2rad's
output at fixed line offsets; run 27 wrote the whole deck as Python strings.
Every Radioss trap then has to be avoided by hand, and run 27 walked into
several (gravity at 1e-4 g from a second `/GRAV` data line, 1253 % added mass,
a tied ceiling wall in earlier runs).

This page is the reverse table: for each Radioss card those runs wrote by hand,
the LS-DYNA keyword that makes k2rad write it, and the traps on the way. The
rule that follows from it:

* Write every card family in the `.k`, convert with k2rad, run the starter
  through `run_or.ps1`, and read the audit. `0 ERROR(S)` is necessary, not
  sufficient.
* Never hand-write a Radioss card. Never patch the `.rad` by line offset: k2rad's
  automatic ids (90001, 90002, ...) and card layout are not stable.
* Patch only the cells no `.k` field can express as LS-DYNA reads it
  (section 4), by keyword search, and record each patch next to the deck.

**What "this tree" means.** Every route below was verified on 2026-10-31 against
the k2rad tree of the CardStack batch (master `d7652da` plus the batch's
changes), by a grep of the handler and writer and, where a number is given, by
a conversion and an OpenRadioss run (section 6 names each measurement). On
2026-11-01 the statements that cite 6.7 or 6.8 were measured again on the
final tree of the batch, the tree the end-to-end proof ran (`git diff` sha1
`d61c19f8`): by probe conversions, with the starter where 6.7 says so (6.7),
and by the proof's own runs (6.8). A statement without a 6.7 or 6.8 reference
keeps the date of its own record. The engine results of section 6 (6.1, 6.3 to
6.6 and the joint drift of 3.4) were not run again: they are the records of
2026-10-31. Rows carry the id (K-xx) of the change that made them; re-check
them after the batch merges.

---

## 1. Starter cards

| Radioss card (run 27) | `.k` keyword that writes it | Where in k2rad | Status |
|---|---|---|---|
| `/BEGIN` unit line `Mg mm s` | `*CONTROL_UNITS` (`mm sec mtrc_ton`), or `--units Mg mm s` | `writer/output.py` (`/BEGIN`) | as hand-written; labels only, values are never rescaled (README, [CardStack FEM-pipeline options](../README.md#cardstack-fem-pipeline-options-2026-10)) |
| `/TITLE` | `*TITLE` | `writer/output.py` | as hand-written |
| `/MAT/ELAST` | `*MAT_ELASTIC` (MID RO E PR) | `writer/materials.py` | cell for cell |
| `/PROP/SOLID` (TET4) | `*SECTION_SOLID` ELFORM 10, tets as 4-node or degenerate 8-node `*ELEMENT_SOLID` rows | `writer/mesh.py` | Isolid 1 on an all-tet section (K-30, default ON, `--no-tet-isolid1`); run 27 wrote 0. Inert for a 4-node tet: Isolid 14, 1 and 0 gave bit-identical results on a LAW1 tet cantilever (D5-16). ELFORM 13: see 4.4 |
| `/PROP/SHELL` (Ishell 12, N 5, Thick 0.35, Ashear, Idrill 1) | `*SECTION_SHELL` ELFORM 16 (Ishell 12 by default), NIP, T1 | `writer/mesh.py` `_emit_prop_shell` | Idrill is always 0: see 4.1. A blank NIP gives N 2: see 3.6. On a LAW1 (`*MAT_ELASTIC`) section N is 0 (K-31, default ON, `--no-law1-shell-global-n`) - the starter switches such a group to N 0 itself (WARNING 1084). Ashear carries `*SECTION_SHELL` SHRF since R14 round 10 (A1, default ON, `--no-shrf-ashear` writes 0 everywhere): a blank / 0 as LS-DYNA's default 1.0, 0 < SHRF <= 1 as stated, within 0.005 of 5/6 the cell 0, which the starter reads as its own 5/6 (`hm_read_prop01.F:244`; 0 again for N 1, `:258`) - so run 27's 0.8333 keeps the cell 0, 5/6 to four digits; NIP-1, membrane ELFORM 5 / 9 and 2-D sections keep 0 (LS-DYNA does not shear them), each kept or substituted value named in the log |
| `/NODE` | `*NODE` | `writer/mesh.py` | cell for cell |
| `/PART` | `*PART` | `writer/mesh.py` | cell for cell |
| `/TETRA4` | `*ELEMENT_SOLID` (tets) | `writer/mesh.py` | cell for cell (first row of run 27 and of the reduced `.k` deck identical) |
| `/SHELL` | `*ELEMENT_SHELL` | `writer/mesh.py` | cell for cell |
| `/GRNOD/NODE` | `*SET_NODE_LIST` | `writer/common.py` | cell for cell; k2rad also writes the groups a card needs (the `/DAMP` group) |
| `/FUNCT` | `*DEFINE_CURVE` | `writer/loads.py` `_emit_funct`; the zero-tail copies in `writer/loadcurves.py` | cell for cell; an applied-load curve that ends before the run end is zero after its last point: see 3.3 |
| `/RBODY` (ICoG 3, main node on the pivot, Ikrem 1) | `*MAT_RIGID`, or `*CONSTRAINED_NODAL_RIGID_BODY[_SPC]`; for a pivot: the `_INERTIA` form or `*PART_INERTIA` (ICoG 4), or a `*CONSTRAINED_JOINT_REVOLUTE` to ground | `writer/rbody.py` | NOT the same body: for `*MAT_RIGID` and CNRB bodies k2rad writes ICoG 0 (4 with `_INERTIA` or `*PART_INERTIA`), never ICoG 3, and every `/RBODY` it writes has Ikrem 0 (all six producers in `writer/rbody.py`), so run 27's body (Ikrem 1; Mass and J 0, computed by the starter) cannot be written. ICoG 3 (Mass 0) appears only on the ties k2rad builds itself from `*CONSTRAINED_SHELL_TO_SOLID` and `*CONSTRAINED_GENERALIZED_WELD_BUTT`, and on the screw-joint carriage (Mass 1e-6) (6.7). On the ICoG 4 route the main node sits on the pivot and TM and IXX..IZZ are the deck's own, computed by hand about the pivot (6.7: v3 and v7 write Mass 6.28e-8 and Jxx..Jzz 1e-5 as stated). A drive acts at the centre of mass: see 3.1 and 3.2 |
| `/BCS` | `*BOUNDARY_SPC_NODE` / `_SET`; on a rigid body `*MAT_RIGID` CMO 1 CON1 / CON2, or the CNRB `_SPC` CON1 / CON2 | `writer/loads.py`, `writer/rbody.py` | cell for cell (`111 111` housing; `111 110` axis from CON1 7 CON2 4). \|CMO\| = 2 is not converted: see 3.2 |
| `/IMPDISP` on a node group | `*BOUNDARY_PRESCRIBED_MOTION_SET` VAD 2 | `writer/loads.py` | cell for cell |
| `/IMPDISP` on an `/RBODY` main node (X, Y, ZZ) | `*BOUNDARY_PRESCRIBED_MOTION_RIGID` VAD 2, DOF 1-3 / 5-7 | `writer/loads.py` | the drive acts at the body's centre of mass: see 3.1 |
| `/EBCS/INLET/VP` + its `/SURF/SEG` (not in run 27) | `*BOUNDARY_PRESCRIBED_MOTION_SET` / `_NODE` VAD 0, DOF 1-3, whose nodes cover boundary faces of an ELFORM 11 / 12 (Iale) mesh (R14 round 10, A7 1b, default ON; `--no-ale-inflow-ebcs` keeps the `/IMPVEL`) | `writer/loads.py` `_pm_inlet_decision`, `writer/blast_ale.py` `ale_inlet_lines` | the faces in outward node order; vel_flag 1, the DOF's component = the row's own `/FUNCT` x its Fscale, the other two 0; one material row: volume fraction 1, density = the face bricks' fluid RHO_I, pressure 0 (`radioss2019/LOADS/inlet.cfg:165-205`). The EBCS imposes the velocity on its nodes every cycle (`ebcs8_inlet.F90:693-716`); an `/IMPVEL` on an Eulerian ALE face moves the nodes and admits no material (`aflux3.F:488-524`). Measured on the 3-brick coupon `tests/fixtures/round10/r10_ale_inlet_coupon.k` (starter 0 ERROR(S), `NUMBER OF SEGMENTS FOUND 1`, engine NORMAL TERMINATION) and on stagnation_A (the README's round-10 options) |
| a LAW6 void copy `/MAT/HYD_VISC` + `/EOS`, its own `/GRBRIC/PART` and a second `/INTER/TYPE18` (not in run 27) | an `*INITIAL_VOID_PART` / `_SET` part in the fluid (master) set of a `*CONSTRAINED_LAGRANGE_IN_SOLID` coupling, no `*ALE_REFERENCE_SYSTEM_*` card (R14 round 10, A10 2b, default ON; `--no-initial-void-copy` writes the void at full density) | `writer/blast_ale.py` `_resolve_initial_void_copy`, `_make_fsi_coupling` | RHO_I = 1e-3 x RO (a numerical floor of this converter, not a value LS-DYNA states), the fluid's `/EOS` with RHO_0 = RO, through the round-8 B10 maps (a copy MID when another part shares the `*MAT_NULL`); the fluid's `/GRBRIC/PART` loses the void part, which gets its own group and interface at the fluid's Stfval x 1e-3, the same surface, Gap and times. Measured on quadrature_B (the README's round-10 options) |
| `/INTER/TYPE18` Stfval = PFAC x m_node / dt0^2 (not in run 27) | `*CONSTRAINED_LAGRANGE_IN_SOLID` card 2 PFAC (> 0; 0 = 0.1) under the opt-in `--clis-pfac-stiffness` (R14 round 10, A10 2a) | `writer/blast_ale.py` `_clis_pfac_stiffness`, `clis_dt0_estimate` | m_node = the median lumped nodal mass of the coupled fluid, dt0 = Tsca x the starter's smallest element step estimated from the deck (`dtel.F` / `cndleni.F`; `tests/fixtures/round10/r10_clis_dt0*.k`); a negative PFAC (a curve) and a deck with a LAW0 `*MAT_VACUUM` are refused |
| `/MAT/HYD_VISC` + `/EOS` under a `*MAT_VACUUM` MID (not in run 27) | `*MAT_VACUUM` in an `*ALE_MULTI-MATERIAL_GROUP` whose one other material is a `*MAT_NULL` + `*EOS_*` fluid (R14 round 10, A7 1a, default ON; `--no-vacuum-light-fluid` writes `/MAT/VOID`) | `writer/materials.py` `_resolve_vacuum_light_fluid` | RHO_I = the vacuum RO; the fluid's `/EOS` copied under the vacuum MID with its RHO_0 cell = the fluid RO, so the starter's reference density PM(1) stays the fluid's (`hm_read_eos_gruneisen.F:117-123`); Pmin -1e-20; the fluid's Nu |
| `/GRAV` | `*LOAD_BODY_Z` (LCID, SF 9810) + `*LOAD_BODY_PARTS` | `writer/loads.py` | better than hand-written: one data line, Fscale_Y -9810. Run 27's second data line was not read, so its gravity was 1 mm/s² (starter echo SCALE_Y 1.0) |
| `/DAMP` Alpha, grnod, Tstart / Tstop | `*DAMPING_PART_MASS` (box curve = a settle window) or `*DAMPING_GLOBAL` (VALDMP, or its LCID curve) | `writer/loads.py` | Alpha cell for cell; a box curve becomes one alpha-only `/DAMP` per level with its Tstart / Tstop (K-20, default ON; `--no-damping-curve-window` writes one `/DAMP` for the whole run). Measured (6.7): alpha 200, Tstart 0, Tstop 0.00050005. Beta: see 4.2 (`*DAMPING_PART_STIFFNESS` only; the `_SET` form is skipped) |
| `/SURF/PART/EXT` (tooling) | written by k2rad for a contact on solid parts | `writer/common.py` `_emit_surf_part` | cell for cell |
| `/SURF/PART` (all cards) | the part set of a contact (`*SET_PART_LIST`) | `writer/common.py`, `writer/contacts.py` | k2rad writes `/SURF/GRSHEL` for a part-set TYPE7, `/SURF/PART/EXT` for the all-parts TYPE25 |
| `/INTER/TYPE25` card to card, single surface over the cards only | none | `writer/contacts.py` | NOT expressible: see 4.3 |
| `/INTER/TYPE25` single surface over ALL parts | `*CONTACT_AUTOMATIC_SINGLE_SURFACE` SSID 0 (explicit) | `writer/contacts.py` | the scope includes the tooling (6.8: 15 tooling-to-tooling initial penetrations on the reduced CardStack deck). Gap = min(Gap_scale x t/2, Gap_max) per side, 0 on solids. Gap_max is not a `.k` cell: k2rad writes Gap_scale 1.0 and Gap_max 1e30, which the starter echoes. The `.k` lever is `*PART_CONTACT` OPTT, written as the `/PART` Thick column: OPTT 0.10 gives `/PART` Thick 0.1, the 0.05 per card side of run 27's Gap_max 0.05 (6.7; a byte-identical T01, recorded by this batch's verification). Card-3 SST / MST / SFST are no gap inputs here and are named in a warning (K-13); SFST is not converted to Gap_scale (6.7: SFST 2 changes no byte of the deck but its title). Inacti 6 does not exist on TYPE25 (the starter turns it into 5, WARNING 1559), so 5 is the faithful value for run 27's 6, and `--inter-inacti` refuses a TYPE25 id by name (6.7). Card-2 BT / DT -> Tstart / Tstop (K-11; `--no-contact-birth-death`: 0 / 0) and Card E SRNDE 1 -> Ishape 2 on shells (K-16; `--no-srnde-ishape`: Ishape 0, starter GAP SHAPE 1, 2026-11-01) |
| `/INTER/TYPE25` tooling to cards, two surfaces | `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` + `--s2s-type25` (K-08B, opt-in), or `*CONTACT_ERODING_SURFACE_TO_SURFACE` + `--eroding-surf-ext` | `writer/contacts.py` | measured (6.2, 6.7): both write a two-surface TYPE25 with surf_ID1 = the SSID surface and surf_ID2 = the MSID surface (a solid side as `/SURF/PART/EXT`). `--s2s-type25` writes Istf 4, Igap 2, Gap_max 0 (= 1e30), Inacti 5, Idel 2, Iedge 1000; the eroding route writes Istf 2. Against run 27's `/INTER/TYPE25/2` (surf_ID1 = tooling, surf_ID2 = cards, Idel at its default 1000, no deletion): with the cards on the SSID side the surface order is swapped, and Idel 2 does nothing while no element fails (6.8). The 2026-11-01 logs still printed the one-way TYPE7 warning of `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` after `--s2s-type25` had routed the card to TYPE25 (cosmetic: no TYPE7 is written for that card; 6.7, 6.8); since 2026-11-07 the warning prints only where the TYPE7 is written (CHANGELOG). The eroding route writes SOFT 2's Iedge 22 only with DEPTH 5 / 15 / 25 / 35 / 45 / 55 or SBOPT 1 (K-10; `--no-soft2-iedge-gate`: 22 for every SOFT 2 card, starter EDGE FLAG 22, 2026-11-01); both routes write Card-2 BT / DT as Tstart / Tstop (K-11; `--no-contact-birth-death`: as stated, so a negative DT switches the contact off from t 0, STOP TIME -4.0E-03, 2026-11-01) |
| `/INTER/TYPE7` (runs 03-26) | `*CONTACT_AUTOMATIC_SINGLE_SURFACE` SSID = part set; `*CONTACT_AUTOMATIC_GENERAL` SSID = part set; `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` | `writer/contacts.py` | measured (6.2, 6.7). AUTOMATIC_S2S becomes a ONE-WAY TYPE7 (SSID nodes against MSID segments), Gapmin (SST + MST)/2, and is warned; `--s2s-type25` gives the two-surface TYPE25 of the row above. The single-surface routes write Gapmin = \|SST\| (K-12, default ON; `--no-single-surface-sst-gap` writes the old (\|SST\| + \|MST\|)/2): SST 0.35 gives Gapmin 0.35 (starter MINIMUM GAP 0.35), with the flag Gapmin 0.175 (6.7). Friction goes on card 2 (FS, FD), never in the card-1 SPR / MPR columns: see 3.5. Card-2 BT / DT -> Tstart / Tstop (K-11; `--no-contact-birth-death`: 0 / 0) |
| `/RWALL/PLANE` (runs 03-26) | `*RIGIDWALL_PLANAR[_FINITE]` (NSID, tail XT..ZT, head XH..ZH, FRIC) | `writer/loads.py` `_rwall_slide` | exact matches, not thresholds: FRIC 0 -> Slide 0 (frictionless sliding); FRIC 1.0 -> Slide 1 (TIED); on `*RIGIDWALL_PLANAR` FRIC 2.0 -> Slide 0 and FRIC 3.0 -> Slide 1, the WVEL-gated weld itself not converted (warned); FRIC < 0 -> Slide 0 (warned); any other FRIC -> Slide 2 (Coulomb, mu = FRIC); re-measured case by case (6.7). `_FINITE` writes `/RWALL/PARAL`, and a face that covers none of its tracked nodes is named (K-21; 6.7). The hand-written walls used Slide 1, which is tied |
| joints | `*CONSTRAINED_JOINT_REVOLUTE` (N1..N4) | `writer/joints.py` | `/PROP/TYPE45` Type 2 + `/SPRING`; a joint to a fixed body works as a pivot: see 3.4 |
| `/END` | always written | `writer/assembly.py` (the starter's last card) | as hand-written |

## 2. Engine cards

| Radioss card (run 27) | `.k` keyword or flag | Where in k2rad | Status |
|---|---|---|---|
| `/RUN` | `*CONTROL_TERMINATION` ENDTIM | `writer/assembly.py` | cell for cell |
| `/ANIM/DT` | `*DATABASE_BINARY_D3PLOT` DT | `writer/assembly.py` | cell for cell |
| `/ANIM/VECT/DISP`, `/ANIM/VECT/VEL`, `/ANIM/VECT/CONT`, `/ANIM/ELEM/VONM`, `/ANIM/BRICK/TENS/STRESS` | always written | `writer/assembly.py` `_make_engine_output` | k2rad's fixed list is a superset of run 27's |
| `/ANIM/SHELL/TENS/STRESS/ALL` | `*DATABASE_EXTENT_BINARY` MAXINT > 3 (K-42; `--no-maxint-stress-all` writes no such line) | `handlers.py` `handle_database_extent_binary` (card 1 field 3, blank = 3), `writer/assembly.py` | measured (6.7): MAXINT 5 writes `/ANIM/SHELL/TENS/STRESS/ALL` right after MEMB / UPPER / LOWER, and the log names it. A blank MAXINT (= 3) writes MEMB, UPPER and LOWER only; a MAXINT below -3 is named in the log and not converted. The engine runs the line to NORMAL TERMINATION (6.5; 6.8, the rigid-tooling CardStack run) |
| `/DT/NODA/CST` Tsca, Tmin | `*CONTROL_TIMESTEP` TSSFAC, DT2MS < 0 | `writer/assembly.py` `_make_engine_timestep` | Tmin = \|DT2MS\| by default; `--dt2ms-tssfac-product` writes TSSFAC x \|DT2MS\|, LS-DYNA's minimum step (6.4). Read the added mass: see 3.7 |
| `/STOP` (added-mass limit) | `*CONTROL_TERMINATION` ENDMAS + `--stop-added-mass` (K-40) | `writer/assembly.py` `_make_engine_stop` | `0. ENDMAS/100 0. 1 1 0`: Mmax is a RATIO, ENDMAS a percent (6.3). Only on a DT2MS < 0 deck with `/DT/NODA/CST`: an ENDMAS < 0 curve, `--ams` and the routed 2-D deck get a warning and no `/STOP` (6.7). A stopped run ends NORMAL TERMINATION then USER BREAK with engine exit 0 and writes its engine restart file although the deck says `/RFILE/OFF` (6.3): read the listing, not the exit code |
| `/PRINT/-2000` | `--print-every 2000`, or `*CONTROL_OUTPUT` IKEDIT 2000 on a deck WITHOUT `*DATABASE_GLSTAT` (K-42) | `writer/assembly.py` `_print_cadence` | LS-DYNA ignores IKEDIT when glstat is written, and so does k2rad; else `/PRINT/-1` (6.5) |
| `/PARITH/ON` | `*CONTROL_PARALLEL` CONST 1 | `writer/output.py` | parith is on by default anyway: `/ANALY` Iparith 0 sets IPARI0 1 (`hm_read_analy.F`), and an engine deck without `/PARITH` takes it (`rdresa.F:282`) |
| `/TFILE` | the smallest DT of the `*DATABASE_*` cards that feed the T01 (`*DATABASE_GLSTAT`, `_MATSUM`, `_NODOUT`, ...) | `writer/assembly.py` `_make_engine_output` | not in run 27; k2rad writes it. `*DATABASE_BNDOUT`, `_RBDOUT`, `_NODFOR`, `_ABSTAT` and `_SBTOUT` count only when their `/TH` groups are written; `*DATABASE_BINARY_D3PLOT`, `_BINARY_D3THDT`, `_BINARY_INTFOR` and `*DATABASE_SLEOUT` never count. Without such an interval the deck gets ENDTIM / 1000. Measured (6.7, ENDTIM 0.004, D3PLOT 8e-4 in every probe): 4e-6 with no other card; `*DATABASE_MATSUM` 4e-5 gives 4e-5, and `*DATABASE_GLSTAT` 2.5e-5 beside it 2.5e-5; `*DATABASE_BNDOUT` 1e-5 gives 4e-6 without a prescribed motion and 1e-5 with one; SLEOUT, BINARY_INTFOR and BINARY_D3THDT 1e-5 give 4e-6 |
| `/END` | not needed | - | k2rad's engine file ends with `/MON/ON` and has no `/END`; the engine reads to the end of the file (every engine run of section 6 ended NORMAL TERMINATION) |

## 3. Traps on the `.k` route

### 3.1 A rigid-body drive acts at the centre of mass

`*BOUNDARY_PRESCRIBED_MOTION_RIGID` drives the body at its centre of mass (CoM).
A translation moves the CoM; a rotation (DOF 5-7) turns the body about its CoM,
not about a pivot node. LS-DYNA does the same (it resets a CNRB PNODE to the
CoM, Vol I R17 p.10-148). Run 27's `/RBODY` ICoG 3 kept the main node on the
pivot; k2rad writes ICoG 0, which the starter reads as 1 (`hm_read_rbody.F:244`)
and so moves the main node to the CoM (`inirby.F:186-211`). The trap is silent:
0 starter errors, 0 starter warnings, and no k2rad warning about it.

Measured (6.1): an eccentric hex (CoM at x 11, pivot at x 0) driven 0.5 rad
about z, `*CONSTRAINED_NODAL_RIGID_BODY_SPC` with PNODE on the pivot: node 3
moves DX -0.59515 / DY +0.35503 at t 0.99 ms, the rotation about the CoM (about
the pivot it is -1.91585 / +5.58103).

The fix is the `_INERTIA` form (`*CONSTRAINED_NODAL_RIGID_BODY_SPC_INERTIA`, or
`*MAT_RIGID` with `*PART_INERTIA`) with XC / YC / ZC at the pivot: k2rad writes
ICoG 4 with the main node there (measured: rotation about the pivot). Two rules
come with it:

* State TM = the body's mesh mass and IXX..IZZ about the PIVOT (parallel axis).
  ICoG 4 takes the main node's mass only and ignores the secondary nodes'
  (`inirby.F:265-270`), and it does not transport the inertia (`:322` corrects
  it only for ICoG <= 3).
* It is an approximation: the CoM moves to the pivot, so gravity and reaction
  moments change (`*MAT_RIGID` Remark 5c). The kinematics of a driven axis do
  not change.

### 3.2 |CMO| = 2 is not converted

LS-DYNA's own first remedy for a pivot is CMO +-2 with SPCNID or XSPC / YSPC /
ZSPC (CNRB Remark 4a, `*MAT_RIGID` Remark 5a). k2rad does not honour it: on
`*MAT_RIGID` it writes no `/BCS` at all (`writer/rbody.py:1157-1162`, warned); on
a CNRB it puts the `/BCS` on the CoM main node and says the offset point is not
applied (`writer/rbody.py:1571`). Measured (6.1): both turn about the CoM, with 0
starter warnings. Use 3.1's `_INERTIA` form or a joint (3.4) instead.

### 3.3 An applied-load curve is zero after its last point

LS-DYNA does not extrapolate a load curve (`*DEFINE_CURVE` Remark 5). k2rad
reproduces that by default (`--load-curve-offscale-zero`, README "An
applied-load curve is zero off its abscissa range"): a `/IMPDISP`, `/IMPVEL`,
`/IMPACC`, `/CLOAD`, `/PLOAD` or `/GRAV` whose curve ends before
min(ENDTIM, Tstop) reads a copy with zero points after the last abscissa, and
the log names each copy. A stroke curve that ends at the end of the stroke then
snaps the part back to 0. Measured (6.1): a 0.5 rad drive whose curve ends at
0.5 ms turns back from +0.4902 to -0.0191 rad between t 0.490 and 0.500 ms. Let
every drive curve run past ENDTIM (the CardStack curves end at t 1.0 s, so they
are safe). Only DATTYP 0 curves without a sensor and not `/FUNCT_SMOOTH` are
padded (`writer/loadcurves.py`). Measured (6.7): of three drives whose curves
end at 0.5 ms of a 1 ms run, the DATTYP 0 one reads the zero-tail copy, the
DATTYP 1 one and the `*DEFINE_CURVE_SMOOTH` one read their curves as written;
the sensor case was not measured.

### 3.4 A joint to ground works as a pivot

`*CONSTRAINED_JOINT_REVOLUTE` with N1 / N3 on the driven body and N2 / N4 on a
fully fixed rigid body (coincident pairs) becomes `/PROP/TYPE45` Type 2 +
`/SPRING`. Measured (6.1): the body turns about the pivot (node 3 DX -1.91580 /
DY +5.58086 at t 0.990 ms against -1.91585 / +5.58103 for a rigid rotation
about the pivot). The pivot node is not held exactly: in the T01 (one sample
every 1.0e-5 s) it moves up to 0.0236 mm, at the first sample after the start
(t 1.03e-5 s), and the motion decays: 0.0140 mm at t 0.1 ms, below 0.0026 mm
after t 0.5 ms. Faster motion between two samples is not resolved. The joint
is a penalty spring, so the drift is not zero (0.0236 mm on the 11 mm arm of
this probe). Give the driven body no translation constraint of its own
(CON1 0).

### 3.5 Friction in the card-1 SPR / MPR columns

FS and FD belong on card 2. Typed into card 1's SPR / MPR columns (fields 7-8)
they are read as SPR / MPR, and the interface gets Fric 0; master `d7652da`
gave no warning (D5-10). This tree names both cells as output flags and says
that no friction is read there (K-07). Measured (6.7): 0.22 / 0.20 in fields
7 / 8 with FS / FD 0 give Fric 0 and the starter echoes FRICTION COEFFICIENT 0.

### 3.6 A blank NIP gives N 2

A blank `*SECTION_SHELL` NIP is read as 0 (`handlers.py`, card 1 field 4) and
written as N = max(2, NIP) = 2 (`writer/mesh.py` `_shell_prop_n`), not the 5 a
deck author may mean (run 26's `2         2` card,
re-measured in the D5-12 verification: N 2). On a LAW1 section the question is
moot: N is 0 there (K-31), as the starter would run it anyway. State NIP on
every non-elastic section.

### 3.7 Mass scaling: read the added mass, not the starter's 'ADDED MASS'

`*CONTROL_TIMESTEP` DT2MS < 0 becomes `/DT/NODA/CST/0` Tsca = TSSFAC (blank ->
0.9; 6.7), Tmin = |DT2MS|. OpenRadioss then adds mass to every node whose own
step is below Tmin and lifts that step to Tmin (`dtnoda.F:270-303`; the global step
is clamped up to Tmin only when it fell below it, `:654-655`). A deck whose
nodal steps all stay above Tmin keeps its own, larger step and gets no added
mass. The starter's 'ADDED MASS' lines are the `/RBODY` echo. The added mass is
in two other places:

* the starter's 'INITIAL ADDED MASS ESTIMATION for /DT/NODA/CST' table: the
  target step for DM/M 1 .. 5 % at the first cycle, at scale factor 0.9 and
  0.67 (`add_mass_stat.F`);
* the engine's MAS.ERR column in `<stem>_0001.out` (DM/M on the console):
  (M - M0) / M0 from cycle 0 on, M0 being the mass before the cycle-0 added
  mass (`ecrit.F:505`, `:516`).

Run 27's `/DT/NODA/CST 0.9 2e-6` added 12.5x the physical mass (MAS.ERR 12.53
at cycle 0); the 0.07 % quoted in troubles.md did not describe that run. State
`*CONTROL_TERMINATION` ENDMAS and pass `--stop-added-mass`: the run then stops
at the limit (6.3). Make tooling `*MAT_RIGID` instead of mass-scaling its
CAD micro-edges (D5-2: rigid tooling gave the same 1.89e-6 s step with zero
added mass). `--dt2ms-tssfac-product` makes the step LS-DYNA's (6.4).

Two limits of these readings, measured by the end-to-end proof (6.8; the first
mechanism corrected on 2026-11-01 from the starter source):

* On a deck with rigid bodies the starter's estimate can be too high, and not
  because of the secondary nodes: `inirby.F:876-883` lumps each rigid body's
  mass and the summed stiffness of its secondary nodes on the body's main node
  and sets the secondary nodes to EM20 before the estimate, so the estimate
  (`add_mass_stat.F:82`) and the engine (`rgbodfp.F:753-754`) both leave the
  secondary nodes out, and the main node gets the smallest step of the table.
  With the body's elements switched off (`Ioptoff` 0, which k2rad writes) the
  engine's main node never carries that stiffness. On the 2-card benchmark
  only the two rigid main nodes lie below Tmin/Tsca (8.4e-9 and 1.2e-8 s; the
  first deformable node at 9.3e-7 s), the audit's forecast ratio is 1.06x and
  the run's MAS.ERR 0.000; on the rigid CardStack variant 582 card nodes lie
  just below the bound (2.004e-6 against 2.222e-6 s), the ratio is 4.78x and
  the cards took +22.7 % mass behind MAS.ERR 0.0276. The launcher audit's
  `mass-forecast` rule (revised 2026-11-01) therefore reads the listing's
  NODAL TIME STEP (estimation) table: a NOTE only when every node below
  Tmin/Tsca is a rigid main node, the table reaches the bound and Tmin is
  below 2x the limit; a FLAG otherwise, naming the smallest other node and
  the Tmin to set. (The earlier text here, 'rigid-body secondary nodes
  included', was wrong; corrected from the starter source on 2026-11-01.)
* MAS.ERR and ENDMAS are ratios over the whole model. On the rigid CardStack
  variant the base is 86 % of the 1.450e-4 Mg, so MAS.ERR 0.0276 passes the
  0.05 gate while every card node took mass (2244 of 2244; mean +23.2 %, max
  +163.8 %; 4.007e-6 Mg on the cards' 1.765e-5 Mg, +22.7 %; 6.8). The
  fem-pipeline results check (row 7) reads the added mass per part from the
  per-node mass change of the animation files (`/ANIM/NODA/DMAS`, which k2rad
  writes; `anim_to_vtk` names it Mass_Change, the relative change per node);
  k2rad and the launcher audit do not.

### 3.8 One `/GRAV` data line, and gravity at 1 g

The `/GRAV` reader takes Ascale_x and Fscale_Y from the same line as funct_IDT.
A second data line is not read (run 27: SCALE_Y 1.0, gravity 1e-4 g, no
warning). `*LOAD_BODY_Z` writes the one-line card. The launcher audit flags a
`/GRAV` that is not 1 g of the work units.

### 3.9 `0 ERROR(S)` is necessary, not sufficient

Run 27 had 0 ERROR(S) with gravity at 1e-4 g, TYPE25 gaps capped at 0.05, alpha
damping over the whole run and 1253 % added mass. Read the k2rad log's warnings
and the `run_or.ps1` audit (`<root>_000N.audit.txt`) of every run.

## 4. Cells no `.k` field can express as LS-DYNA reads it

Patch these by keyword search (the card header and its title, never a line
offset) and record each patch next to the deck.

### 4.1 `/PROP/SHELL` Idrill

k2rad writes Idrill 0 on every `/PROP/SHELL` (`writer/mesh.py`
`_emit_prop_shell`, the fourth cell of its first data line). Run 27 had Idrill
1 (starter echo DRILLING D.O.F. FLAG = 1). On Ishell 12 the flag selects a
different QBAT membrane path (`cbaforc3.F` IDRIL branches), so it is not
cosmetic (D5-12 verification). No `*SECTION_SHELL` field maps to it.
Re-measured (6.7, 6.8): `/PROP/SHELL` carries Idrill 0 on the probes, and the
reduced CardStack decks echo DRILLING D.O.F. FLAG 0 where run 27 echoes 1. The
`/PROP/TYPE9`, `/PROP/TYPE11` and `/PROP/TYPE51` writers write 0 as well (a
grep of `writer/fabric.py`, `composites.py`, `mesh.py` and `seatbelts.py`).

### 4.2 `/DAMP` Beta

k2rad's only Beta source is the per-PID `*DAMPING_PART_STIFFNESS`: its COEF is
written as Beta directly, with a warning that LS-DYNA scales it by 2/omega_max
(`writer/loads.py`, the `*DAMPING_PART_STIFFNESS` sentence). So a `.k` field
does reach the cell, but no `.k` that LS-DYNA reads the same way gives run 27's
Beta 1e-7; that is why Beta stays in this section. Measured (6.7, 6.8):

* Run 27's single `/DAMP` (alpha 2500 and Beta 1e-7 over the cards for the
  whole run) can be written: `*DAMPING_GLOBAL` VALDMP 2500 (LCID 0) beside a
  `*DAMPING_PART_STIFFNESS` COEF 1e-7 on every card PID gives ONE `/DAMP`,
  alpha 2500 and Beta 1e-7 on each of its six DOF rows (run 27 wrote the
  one-row form), Tstart 0, Tstop 1e30, over the nodes of the stiffness parts.
  The starter echoes ALPHA 2500 and BETA 1e-7 in each of the six directions
  and STOP TIME 1e30; run 27's echo has the same three values once. LS-DYNA
  would run that `.k` differently: it scales COEF by 2/omega_max (warned), and
  its `*DAMPING_GLOBAL` damps every deformable node and each rigid body's mass
  centre (the group k2rad writes when no stiffness card is present), where
  k2rad narrows the alpha to the stiffness parts without a warning (a
  deformable part without a stiffness card gets no `/DAMP`).
* A windowed alpha cannot carry Beta. With a box curve on `*DAMPING_GLOBAL`
  LCID and a Beta, k2rad writes one ungated `/DAMP` at the curve's value at
  t 0 and warns that the time variation is LOST. On the `*DAMPING_PART_MASS`
  route the Beta goes on a second `/DAMP` (alpha 0) beside the alpha windows,
  over the same nodes, and k2rad warns that two `/DAMP` cards sharing nodes
  corrupt the Beta term (2022 Reference Guide p.130 comment 4): 9 and 12 shared
  nodes on the probes, 2244 card nodes on the reduced CardStack deck.
* `*DAMPING_PART_STIFFNESS_SET` is skipped as unsupported (the log's skipped
  list); write one `*DAMPING_PART_STIFFNESS` per PID.

### 4.3 A card-only single-surface `/INTER/TYPE25`

Run 27's `/INTER/TYPE25/1` is a single-surface interface over the card parts
only (surf_ID1 = all cards, surf_ID2 0). Measured (6.2):
`*CONTACT_AUTOMATIC_SINGLE_SURFACE` and `*CONTACT_AUTOMATIC_GENERAL` with SSID =
the card part set both become `/INTER/TYPE7`; with SSID 0 the TYPE25 covers all
parts, the tooling included. Re-measured (6.7) with the same result. On the
reduced CardStack deck the all-parts TYPE25 adds tooling-to-tooling pairs: 15
initial penetrations on 15 nodes, where the deck with a card TYPE7 and the
two-surface tooling-to-cards TYPE25 of `--s2s-type25` has none (6.8). Keep the
all-parts TYPE25, or patch the card-only interface, recorded. The tooling-to-cards
interface needs no patch: `--s2s-type25` writes it (section 1).

### 4.4 Out of scope here

* `*SECTION_SOLID` ELFORM 13 (the nodal-pressure tet) is written as the
  one-point tet (Itetra4 0, read as 1000), like ELFORM 10; its Radioss match
  would be Itetra4 3 (D3-4 verification).
* A section with both hexes and tets keeps one `/PROP/SOLID`; the Isolid 1 rule
  of K-30 acts on all-tet sections only (D3-4 verification; 6.7: an ELFORM 10
  section of two tets and one hex keeps Isolid 14, its all-tet twin gets 1).

## 5. Routes this batch changes

Until each change has merged, master `d7652da` keeps these `.k` routes lossy as
described in D2-8 / D5-12. This tree has every one of them (re-measured on
2026-11-01, 6.7):

| Route | Change | State in this tree (2026-11-01) |
|---|---|---|
| `*CONTROL_UNITS` -> `/BEGIN` labels | K-0P | done: `Mg mm s` from `mm sec mtrc_ton`; a `--units` that disagrees is written and warned |
| damping curve -> `/DAMP` time windows | K-20 | done, default ON (`--no-damping-curve-window`): alpha 200, Tstart 0, Tstop 0.00050005 |
| finite rigid-wall footprint lint | K-21 | done: a `_FINITE` face over none of its 9 nodes is named |
| DT2MS < 0: Tmin = TSSFAC x \|DT2MS\| | K-41 | done, opt-in `--dt2ms-tssfac-product`: 4.5e-6 for 0.9 x 5e-6 |
| ENDMAS -> `/STOP` Mmax | K-40 | done, opt-in `--stop-added-mass`: `/STOP 0. 0.05 0. 1 1 0` for ENDMAS 5 |
| `/PRINT/-N` from `--print-every` / IKEDIT | K-42 | done: IKEDIT 50 without glstat gives `/PRINT/-50`, with glstat `/PRINT/-1`; `--print-every 2000` gives `/PRINT/-2000` |
| MAXINT > 3 -> `/ANIM/SHELL/TENS/STRESS/ALL` | K-42 (the handler read came later in the batch) | done, default ON (`--no-maxint-stress-all`): MAXINT 5 writes it; blank (= 3) and -5 do not, -5 is named |
| two-surface TYPE25 for AUTOMATIC_S2S | K-08B | done, opt-in `--s2s-type25`: surf_ID1 = the SSID surface; the one-way TYPE7 warning still printed beside it (cosmetic; withdrawn on 2026-11-07, CHANGELOG) |
| friction typed into SPR / MPR warned | K-07 | done: both cells named, Fric 0 |
| single-surface SST gap | K-12 | done, default ON (`--no-single-surface-sst-gap`): Gapmin 0.35 for SST 0.35, 0.175 with the flag |
| all-tet Isolid 1, LAW1 shell N 0 | K-30, K-31 | active (default ON): Isolid 1 and N 0; the opt-outs give Isolid 14 and N 5 |

## 6. Measurements behind this page

All runs: k2rad of this tree, OpenRadioss through `run_or.ps1` (starter +
engine unless said), 2026-10-31; 6.7 and 6.8 are of 2026-11-01. The d7652da
warning counts quoted in 6.6 are the exception: they are the D5-12
verification's record, not re-run here.

**6.1 Pivot and drive probes** (one 2 x 2 x 2 mm steel hex, CoM (11, 0, 1),
pivot at (0, 0, 1) - the element-free node 100 on v1 / v3; v5 has no node 100,
its revolute joint axis runs through nodes 101 (0, 0, 0) and 102 (0, 0, 2), and
its drift below is node 101's - a far dummy hex for the time step;
`*BOUNDARY_PRESCRIBED_MOTION_RIGID` DOF 7 VAD 2, 0.5 rad over 1 ms; nt 1). The
`.k` decks are the D2-8 verification's; every converted deck is byte-identical
to the d7652da conversion. Node 3 at t 0.99 ms (about the CoM: DX -0.59515 / DY
+0.35503; about the pivot: -1.91585 / +5.58103):

| Probe | `.k` | Turns about |
|---|---|---|
| v1 | CNRB_SPC CMO 1 CON1 7 CON2 4, PNODE on the pivot | CoM |
| v2 | CNRB_SPC CMO 2, SPCNID = pivot | CoM |
| v3 | CNRB_SPC_INERTIA, XC / YC / ZC = pivot | pivot |
| v4 | `*MAT_RIGID` CMO 2, SPCNID = pivot | CoM |
| v5 | `*CONSTRAINED_JOINT_REVOLUTE` to a fixed CNRB | pivot; the pivot node (node 101) moves up to 0.0236 mm in the T01 (1.0e-5 s samples; peak at t 1.03e-5 s, 0.0140 mm at 0.1 ms, below 0.0026 mm after 0.5 ms) |
| v6 | as v3, curve ends at 0.5 ms | snaps back +0.4902 -> -0.0191 rad at 0.5 ms |
| v7 | `*MAT_RIGID` + `*PART_INERTIA` at the pivot | pivot |

Every starter 0 ERROR(S) 0 WARNING(S); every engine NORMAL TERMINATION in 3506
cycles.

**6.2 Contact probes** (a 4 x 4 x 1 mm tool block, part 1, and two 4 x 4 mm
ELFORM 16 cards, parts 101 / 102 in part set 1; starter only):

| `.k` | k2rad writes |
|---|---|
| `*CONTACT_AUTOMATIC_SINGLE_SURFACE` SSID 0 | `/INTER/TYPE25` over `/SURF/PART/EXT` {1, 101, 102} |
| `*CONTACT_AUTOMATIC_SINGLE_SURFACE` SSID = set 1 | `/INTER/TYPE7` |
| `*CONTACT_AUTOMATIC_GENERAL` SSID = set 1 | `/INTER/TYPE7` |
| `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` tool -> set 1 | `/INTER/TYPE7`, one-way, warned |
| `*CONTACT_ERODING_SURFACE_TO_SURFACE` + `--eroding-surf-ext` | `/INTER/TYPE25`, surf_ID1 tool `/SURF/PART/EXT`, surf_ID2 the cards |
| AUTOMATIC_S2S + `--s2s-type25` | on 2026-10-31 `/INTER/TYPE7` (K-08B not active then); on 2026-11-01 `/INTER/TYPE25`, surf_ID1 tool `/SURF/PART/EXT`, surf_ID2 the cards (6.7) |

Every starter 0 ERROR(S) (0 or 1 WARNING(S)).

**6.3 `--stop-added-mass`** (a free 12 x 28 shell card, `*MAT_ELASTIC` rho
1.35e-9 E 3200, VX 1000 mm/s, ENDTIM 2 ms, DT2MS -5e-6, nt 2; MAS.ERR 3.455
from cycle 0): ENDMAS 5 -> `/STOP 0. 0.05 0. 1 1 0`: MESSAGE 208 'TOTAL MASS
ERROR LIMIT REACHED' at cycle 0, 1 cycle, the listing ends NORMAL TERMINATION
then USER BREAK, engine exit 0. MESSAGE 208 also sets the restart flag
(`ecrit.F:597`): that run wrote `p_0001_0001.rst` (860043 B; listing 'RESTART
FILES: p_0001_[0001-0001].rst WRITTEN') although its engine deck says
`/RFILE/OFF`. ENDMAS 400 (Mmax 4.0): 401 cycles, NORMAL TERMINATION, no engine
restart file. The same `/STOP` added by hand beside `/DT/AMS` never fires
(MAS.ERR 0.000 on all 401 rows), and beside a routed 2-D deck's DT2MS > 0
density cell neither (MAS.ERR 0.000, 11 cycles): k2rad warns there and writes no
`/STOP`.

**6.4 `--dt2ms-tssfac-product`** (R14 `control_timestep.billet-forge.k`, DT2MS
-1.2e-7, TSSFAC blank, nt 4; LS-DYNA steps at 1.08e-7 throughout): default
`/DT/NODA/CST/0 0.9 1.2e-7` -> engine echo NODAL MINIMUM TIME STEP 1.2e-7,
12501 cycles, end KE +16.99 % against LS-DYNA; with the flag 1.08e-7 -> echo
1.08e-7, 13890 cycles, end KE -5.13 %; end IE +0.135 % in both. On the shell
card of 6.3 the flag cuts the added mass at cycle 0 from 1.371e-5 to 1.035e-5
Mg.

**6.5 `/PRINT/-N`** (the card of 6.3, 401 cycles): `--print-every 100` prints
cycles 0, 100, .., 400; IKEDIT 50 without `*DATABASE_GLSTAT` prints every 50th
cycle (engine echo PRINTOUT CYCLE FREQUENCY -50); `--print-every 7` prints 0,
7, .., 399, so the last row sits before the last cycle. MAXINT on the same
card (on 2026-10-31 the field was set by a probe-script wrapper around the
handler, which did not read card 1 field 3 then; the handler reads it now,
6.7): MAXINT 5 writes `/ANIM/SHELL/TENS/STRESS/ALL` after
`.../STRESS/LOWER`, the engine runs 401 cycles to NORMAL TERMINATION, and the
first A-file grows from 84736 B (MAXINT 3) to 105301 B.

**6.6 The reduced run-27 decks** (D5-12: base + top shuttle as tets, four
cards; 28,604 nodes, 88,138 elements): `A_base` and `G_rigid_tooling` convert in
15.0 s and 16.8 s; both starters 0 ERROR(S), 2 WARNING(S) (WARNING 94 twice).
Recorded by the D5-12 verification, not re-run here: the d7652da conversions
of the same decks drew 1350 starter warnings on `A_base` (WARNING 791 x 1346,
94 x 2, 1084 x 2) and 1352 on `G_rigid_tooling` (791 x 1348, 94 x 2, 1084 x
2); K-30 and K-31 remove the 791 and 1084.

**6.7 Re-measurement on the final tree** (2026-11-01; `python k2rad.py --help`
prints 1671 lines, the same text the end-to-end proof captured). The probe
decks are small `.k` files written by a probe script, one folder per case,
outside this repository (the CardStack pipeline recipe names the folders in
its section 16); every conversion exits 0. The contact probes use the geometry
of 6.2 (c4 is its S2S deck with a new title):

| Probe | `.k` | k2rad writes |
|---|---|---|
| c1 | `*CONTACT_AUTOMATIC_SINGLE_SURFACE` SSID 0, card-3 SST 0.35 | `/INTER/TYPE25` over `/SURF/PART/EXT` {1, 101, 102}, surf_ID2 0, Istf 4, Igap 2, Gap_scale 1.0, Gap_max 1e30, Inacti 5, Idel 2; the SST is named as no gap input. With `--inter-inacti 90001=6`: refused by name, Inacti 5 kept |
| c1s | c1 with SFST 2 | the deck of c1 but its title (Gap_scale 1.0) |
| c1o | c1 with `*PART_CONTACT` OPTT 0.10 on both cards | `/PART/101` and `/PART/102` Thick 0.1; starter MAXIMUM SECONDARY / MAIN GAP VALUE 1e30 |
| c2 | `*CONTACT_AUTOMATIC_SINGLE_SURFACE` SSID = set 1, SST 0.35 | `/INTER/TYPE7` Gapmin 0.35 (starter MINIMUM GAP 0.35), main `/SURF/GRSHEL`; `--no-single-surface-sst-gap`: Gapmin 0.175 |
| c3 | `*CONTACT_AUTOMATIC_GENERAL` SSID = set 1, SST 0.35 | `/INTER/TYPE7` Gapmin 0.35 |
| c4 | `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE` tool -> set 1 | `/INTER/TYPE7`, one-way, warned. `--s2s-type25`: `/INTER/TYPE25` surf_ID1 tool `/SURF/PART/EXT`, surf_ID2 the cards `/SURF/GRSHEL`, Istf 4, Igap 2, Gap_max 0, Inacti 5, Idel 2, Iedge 1000; the one-way warning still in the log |
| c4c | the same, set 1 -> tool, SST 0.35 | `/INTER/TYPE7` Gapmin 0.175. `--s2s-type25`: surf_ID1 the cards, surf_ID2 the tool; the one-way warning still in the log |
| c6 | `*CONTACT_ERODING_SURFACE_TO_SURFACE` tool -> set 1 + `--eroding-surf-ext` | `/INTER/TYPE25` surf_ID1 tool `/SURF/PART/EXT`, surf_ID2 the cards, Istf 2 |
| c7 | c2 with 0.22 / 0.20 in card-1 fields 7 / 8 and FS / FD 0 | both cells named as output flags; Fric 0 (starter FRICTION COEFFICIENT 0) |

The starter through `run_or.ps1 -Strict` (starter only) on c1o, c2, c4 and c4c
with `--s2s-type25`, c6 and c7: each 0 ERROR(S), 0 WARNING(S), exit 0. The
other probes:

* s1: a `*MAT_ELASTIC` shell section with NIP 5 and SHRF 0.8333, a
  `*MAT_PIECEWISE_LINEAR_PLASTICITY` shell section with NIP blank and SHRF 1.0,
  one ELFORM 10 and one ELFORM 13 tet as degenerate 8-node rows; s2: the same
  tets as 4-node rows. `/PROP/SHELL` Ishell 12, Idrill 0 and Ashear 0 on both
  sections; N 0 on the elastic one (`--no-law1-shell-global-n`: 5), N 2 on the
  blank NIP; the SHRF 1.0 is named. `/TETRA4` and `/PROP/SOLID` Isolid 1,
  Itetra4 0 on both tet sections, in s1 and s2 (`--no-tet-isolid1`: Isolid 14).
  (Measured before R14 round 10. Since its A1 the SHRF 1.0 section is written
  Ashear 1 - the factor is carried, so it is no longer named - and the 0.8333
  one keeps 0, inside the 0.005 window around 5/6; `--no-shrf-ashear` writes
  the bytes above and names the 1.0.)
* e1: one 2 x 2 shell card; `*CONTROL_UNITS` mm sec mtrc_ton, ENDTIM 0.002,
  ENDMAS 5, DT2MS -5e-6, `*CONTROL_PARALLEL` CONST 1, IKEDIT 50, MAXINT 5, no
  glstat. `/BEGIN` Mg mm s, `/RUN` 0.002, `/PARITH/ON`, `/TFILE` 2e-6,
  `/PRINT/-50`, `/ANIM/DT` 0 0.0005, `/ANIM/SHELL/TENS/STRESS/ALL` after
  `.../STRESS/LOWER`, `/DT/NODA/CST/0` 0.9 5e-6, ENDMAS named and no `/STOP`;
  the engine file ends with `/MON/ON` and has no `/END`. With `--stop-added-mass`:
  `/STOP 0. 0.05 0. 1 1 0`; `--dt2ms-tssfac-product`: Tmin 4.5e-6;
  `--print-every 2000`: `/PRINT/-2000`; `--units kg m s`: `/BEGIN` kg m s and a
  warning that it disagrees with `*CONTROL_UNITS`. e2 (MAXINT blank,
  `*DATABASE_GLSTAT` 1e-5): `/PRINT/-1`, `/TFILE` 1e-5, no STRESS/ALL. e3
  (MAXINT -5): no STRESS/ALL, MAXINT named.
* l1: two 2 x 2 shell cards; `*LOAD_BODY_Z` SF 9810 on a constant curve with
  `*LOAD_BODY_PARTS`; `*DAMPING_PART_MASS` on a box curve, alpha 200 to 0.5 ms;
  `*DAMPING_PART_STIFFNESS` COEF 1e-7 on the same part; six `*RIGIDWALL_PLANAR`
  with FRIC 0, 1.0, 2.0, 3.0, -1.0 and 0.3; a `_FINITE` wall far from its
  nodes; a VAD 2 drive on a curve that ends at 1 ms, ENDTIM 2 ms. One `/GRAV`
  data line, Fscale_Y -9810; `/DAMP` alpha 200, Tstart 0, Tstop 0.00050005
  (`--no-damping-curve-window`: one `/DAMP` to the end, the lost time variation
  named); a second `/DAMP` alpha 0, Beta 1e-7 on the same 9 nodes, with the
  2/omega_max warning and the shared-node warning; Slide 0, 1, 0, 1, 0 and 2
  (fric 0.3); `/RWALL/PARAL` for the finite wall, named as covering none of its
  9 nodes; the drive reads `/FUNCT/90010` `FUNCT_30_offscale_zero`, named in
  the log. l2 (`*DAMPING_PART_STIFFNESS_SET` instead): listed as skipped
  (unsupported), no Beta `/DAMP`. l3 (`*DAMPING_GLOBAL` LCID = the box curve):
  alpha 200, Tstart 0, Tstop 0.00050005.
* v1-v7, the 6.1 decks converted again: all 14 files are byte-identical to the
  2026-10-31 conversions, so the engine results of 6.1 stand. v1: ICoG 0,
  Ikrem 0, `/BCS` 111 110, no warning about the centre of mass; v2: the `/BCS`
  on the main node and the |CMO| = 2 warning; v3 and v7: ICoG 4, Mass 6.28e-8
  and Jxx..Jzz 1e-5 as stated; v4: no `/BCS`, warned; v5: `/PROP/TYPE45`
  Type 2 with a `/SPRING`; v6: the zero-tail copy `/FUNCT/90004`.

Second pass (2026-11-01, after the review of the first pass; new probes, same
tree, every conversion exits 0):

* d1-d5: two 3 x 2 shell cards (parts 11 and 12, 12 nodes each) and a
  `*MAT_RIGID` block (part 13). d1, `*DAMPING_GLOBAL` VALDMP 2500 with
  `*DAMPING_PART_STIFFNESS` COEF 1e-7 on parts 11 and 12: one `/DAMP`, alpha
  2500 and Beta 1e-7 on six rows, Tstart 0, Tstop 1e30, over the 24 card nodes;
  the log's only damping line is the 2/omega_max warning; the starter (0
  ERROR(S), 0 WARNING(S), audit 0 flags) echoes ALPHA 2500 and BETA 1e-7 in each
  direction and STOP TIME 1e30. d2, the stiffness card on part 11 only: the
  same card over part 11's 12 nodes, no `/DAMP` on part 12, and no warning
  about it. d3, `*DAMPING_GLOBAL` alone: one alpha-only `/DAMP` over 25 nodes
  (both cards and the rigid body's main node). d4, a box curve (2500 up to
  0.4 ms) on `*DAMPING_GLOBAL` LCID beside the Beta of d1: one ungated `/DAMP`,
  alpha 2500, Tstop 1e30, and the warning that the curve's time variation is
  LOST. d5, `*DAMPING_PART_MASS` on that curve beside a stiffness card on part
  11: the alpha window (Tstop 0.00040005) and a second `/DAMP` (alpha 0, Beta
  1e-7) over the same 12 nodes, with the shared-node warning.
* r1, `*CONSTRAINED_SHELL_TO_SOLID` (two shell nodes, each tied to two hex
  nodes), and r2, `*CONSTRAINED_GENERALIZED_WELD_BUTT` (two coincident pairs):
  every `/RBODY` ICoG 3, Ikrem 0, Mass 0; starter 0 ERROR(S), 2 x WARNING 448
  (the main node is a mesh node), audit 0 flags. r3, the R14 deck
  `show-cases/joint-screw`: its two `*MAT_RIGID` bodies ICoG 0, the screw
  carriage `/RBODY` ICoG 3 with Mass 1e-6, Ikrem 0 on all three. v1, v3, v4
  and v7 converted again: byte-identical to the 2026-10-31 conversions, ICoG 0,
  4, 0 and 4, Ikrem 0.
* t1-t7: a 4 x 2 shell card, ENDTIM 0.004, `*DATABASE_BINARY_D3PLOT` 8e-4;
  the `/TFILE` values are in the section 2 row.
* m1-m3: a 3 x 2 shell card, DT2MS -4e-6. ENDMAS -7 (a curve) with
  `--stop-added-mass`: `/DT/NODA/CST/0` 0.8 4e-6, no `/STOP`, warned. ENDMAS 3
  with `--stop-added-mass --ams`: `/DT/AMS`, no `/STOP`, warned; without
  `--ams`: `/STOP 0. 0.03 0. 1 1 0`. TSSFAC blank: Tsca 0.9 (a stated 0.7
  stays 0.7).
* q1: a routed 2-D deck (ELFORM 15 shells in the xy-plane), ENDMAS 5,
  `--stop-added-mass`: with DT2MS -4e-6 no `/DT/NODA/CST` and no `/STOP`; with
  DT2MS +4e-6 the density cell and no `/STOP`; both warned.
* s3: an ELFORM 10 section of two tets and one hex: one `/PROP/SOLID`, Isolid
  14, with and without `--no-tet-isolid1`; the same section without the hex:
  Isolid 1 (14 with the flag); an ELFORM 1 section of two tets and one hex:
  Isolid 1.
* f1: three `*BOUNDARY_PRESCRIBED_MOTION_SET` drives on curves that end at
  0.5 ms of a 1 ms run: the DATTYP 0 curve is read through its zero-tail copy,
  the DATTYP 1 curve and the `*DEFINE_CURVE_SMOOTH` as written.

**6.8 The end-to-end proof** (2026-11-01; its report and run folders are named
in the CardStack pipeline recipe, section 10). `.k` decks went through this
tree, the starter and the engine:

* The 2-card benchmark (folders `r3`, `r4`): k7, k25s, k25 and k7i6 each give
  starter 0 ERROR(S) and engine NORMAL TERMINATION. The echoes show TYPE7
  MINIMUM GAP 0.40 (= |SST|, K-12) beside 0.21 (= (SST + MST)/2), the
  two-surface TYPE25 of `--s2s-type25` (k25s) and Inacti 6 from `--inter-inacti`
  (k7i6). The k25s log prints the one-way TYPE7 warning beside the TYPE25 line.
  At DT2MS -1.5e-7 the audit's only FLAG was the mass forecast (1.06x) at
  MAS.ERR 0.000 (3.7); at DT2MS 0 `run_or.ps1 -Both -Strict` exits 0 (r4).
* The reduced CardStack decks (folder `cs2`): a (all-parts TYPE25) and b (card
  TYPE7 + `--s2s-type25`) match run 27's cards cell for cell or in the starter
  echo (Isolid, shell N, Ashear, Inacti, the TYPE25 gap), apart from the
  intended corrections (one `/GRAV` line, the alpha window, `/STOP`), the run-27
  inputs left out on purpose (prescribed card DOFs, calibrated stress patches)
  and the cells of section 4; `/ANIM/SHELL/TENS/STRESS/ALL` comes from
  MAXINT 5. Both echo DRILLING D.O.F. FLAG 0 (run 27: 1). Deck a has 15 initial
  penetrations on 15 nodes, tooling against tooling; deck b has none.
  Deck b's TYPE25/2 has surf_ID1 = the cards (its SSID), surf_ID2 = the tooling
  and Idel 2; run 27's has surf_ID1 = the tooling and Idel 1000 (its starter
  echo). Deck b's log prints the one-way warning beside the TYPE25 line. The
  first run of deck a skipped `*DAMPING_PART_STIFFNESS_SET`; the per-PID form,
  beside the deck's `*DAMPING_PART_MASS_SET` settle window, gives a second
  `/DAMP` over the same 2244 card nodes, warned. The rigid-tooling
  variant (`ar`) ran 1001 cycles to NORMAL TERMINATION with STRESS/ALL in its
  engine deck; its forecast FLAG read 4.78x at MAS.ERR 0.0276, and all 2244 card
  nodes took mass (3.7).

**Recorded sources.** D2-8 and D5-12 (CardStack batch findings and their
verification), D3-4 (ELFORM 13, mixed sections), D5-2 (rigid tooling), D5-10
(friction columns), D5-16 (Isolid on tets); the end-to-end proof of
2026-11-01 (6.8); OpenRadioss source
`inirby.F`, `ecrit.F`, `add_mass_stat.F`, `freform.F`, `dtnoda.F`,
`hm_read_prop01.F`, `rgbodfp.F`; LS-DYNA Vol I R17 `*CONTROL_TERMINATION`
p.12-558, `*CONTROL_TIMESTEP` p.12-585.
