# Implicit dynamic notes

[← back to README](../README.md#implicit-dynamic-notes)

The converter generates OpenRadioss implicit dynamic engine files using
`/IMPL/DYNA/2` (Newmark) when the `.k` file specifies
`*CONTROL_IMPLICIT_DYNAMICS IMASS=1`.

## Stabilizing free DOFs on small-mass rigid bodies

LS-DYNA implicit dynamic tolerates rigid bodies with very small inherent
mass (typical for thin-shell impactors / loading platens). OpenRadioss
MUMPS direct solver does **not** — the effective stiffness
`K_eff = K + M/(βΔt²)` becomes singular at the rigid body master node
when:

- the rigid body is loaded by `*LOAD_RIGID_BODY` in a free DOF, and
- the inherent (element + density) mass is too small to make
  `M/(βΔt²)` comparable to `K`.

The converter has two complementary stabilization mechanisms:

### 1. Automatic `/BCS` on non-loaded translation DOFs

If a loaded rigid body has translation DOFs that are not loaded AND not
already constrained by `*MAT_RIGID CMO/CON1/CON2`, the converter adds a
`/BCS` to fix those DOFs. Emits a warning naming the affected axes.

### 2. `*ELEMENT_MASS_PART` for true added mass (preferred)

To preserve the original physics (no extra constraints), add explicit
non-structural mass to the rigid body:

```
*ELEMENT_MASS_PART
$#       pid   addmass   finmass      lcid       mwd
  10000000          1         0         0         0
  10000001          1         0         0         0
```

- `pid`: part ID of the rigid body
- `addmass`: extra translational mass in input units (Mg = tonne).
  `1` ≈ 1000 kg, plenty for stabilization on impactor-sized rigid bodies.

When the converter sees `*ELEMENT_MASS_PART` (or `*ELEMENT_MASS` on the
master node) for a rigid body, it **skips the automatic `/BCS`** and
relies on the user-provided mass for K_eff stabilization instead.

Both formats are accepted: fixed I10 columns or free format
(whitespace / comma separated).

## Why both layers exist

The order of operations matters in OpenRadioss's MUMPS solver:

1. Card-3 of `/RBODY` puts added mass on the rigid body's master node
2. The mass term `M(z,z)/(βΔt²)` enters the diagonal of `K_eff`
3. If that diagonal entry is too small (< `1e-6` × typical K entry),
   MUMPS reports `INFO(1)=-10` (singular) at that row
4. Without a `/BCS` to anchor the DOF instead, the run aborts

Empirically, `addmass = 1 Mg` (1 tonne) on the test model is enough to
let MUMPS factorize without artificial constraints.

## Matching contact `Gapmin` to the mesh clearance (`--auto-gapmin`)

For a solid `/SURF/PART/EXT` contact the converter writes `Igap=0` (constant
gap), so the engagement gap **is** `Gapmin`. `Gapmin` must sit just *below* the
real clearance between the two contacting parts:

- `Gapmin` **>** clearance → secondary nodes start already penetrated
  (starter `WARNING 343 INITIAL PENETRATIONS`). Under a pull the releasing-side
  nodes flip-flop in and out of the penalty gap, the force residual sticks, and
  the implicit solve never converges — a **contact limit cycle**.
- `Gapmin` **≪** clearance → contact never engages under load → no load path.

Because the clearance is mesh-specific, a `Gapmin` hand-tuned for one mesh fails
when the model is re-meshed. (The elevator-linkage deck converges on a TET4 mesh
with `Gapmin` `0.03 / 0.03 / 0.14` per interface, then stalls in a limit cycle
when the same uniform value is re-used on a finer TET10 mesh whose measured pin
clearances are `0.12` and `0.16`.)

`--auto-gapmin` removes the guesswork: it sets each surface-to-surface
interface's `Gapmin` to `--gapmin-factor` × the minimum node-to-node distance
between its two parts (default factor `0.8`). Inspect first with
`--suggest-gapmin` (read-only — prints the clearances and exits); an explicit
`--inter-gapmin ID=VAL` always wins over the suggestion. Self-contacts and
single-surface contacts have no two-part clearance and are reported as skipped.

```bash
python k2rad.py model.k --suggest-gapmin                  # report clearances
python k2rad.py model.k --auto-gapmin                     # apply (factor 0.8)
python k2rad.py model.k --auto-gapmin --gapmin-factor 0.6 # more conservative
```

Lower the factor if an interface still reports initial penetration (node-to-node
distance over-estimates the true node-to-segment clearance); raise it toward
`1.0` if a contact fails to engage.

## Deformable–deformable contact (`--deformable-contact-recipe`)

When two **deformable** parts contact in an implicit deck (e.g. force control
through a clearance-fit deformable pin), the penalty solve hits two stalls that
default settings do not survive:

- an **active-set chatter** — a sub-mesh-scale `Gapmin` flips contact nodes in
  and out of the gap each Newton iteration (no `Stfac` value fixes it); and
- a **force-control soft-mode step-overshoot** — the assembly is
  under-constrained until contact fully engages, so the step oscillates.

By default the converter does **not** silently restabilize such a deck — it
**warns** when it detects a deformable-vs-deformable `/INTER/TYPE7` and points
here. Pass `--deformable-contact-recipe` (GUI: the **“Deformable–deformable
contact recipe”** checkbox) to apply the validated fix:

- `Inacti=5` on each deformable-deformable interface (mesh-scale engagement gap,
  no t=0 force spike — keep the contact’s Card-3 SST/MST `Gapmin`; do **not**
  also `--auto-gapmin` it, which shrinks the gap below mesh scale);
- `/IMPL/DT/2` `L_dtn=50` (iteration cap for the slow *linear* contact-force
  convergence); and
- `/IMPL/QSTAT/DTSCAL=0.05` (anchors the soft mode — physics-neutral for
  nonlinear analysis).

```bash
python k2rad.py model.k --deformable-contact-recipe
```

The recipe is a no-op on a deck without deformable-deformable contact, and the
`L_dtn`/`QSTAT` engine globals are otherwise left at their defaults (engine
`L_dtn=20`, `DTSCAL=0.1`).

## Diagnosing a divergence: /IMPL/NONLIN/SOLVINFO

The cycle table says THAT an implicit run diverges, not WHERE. OpenRadioss has
a DOF-level residual dump for that: add the engine card

```
/IMPL/NONLIN/SOLVINFO
```

(no data line) to the `_0001.rad`. `freimpl.F:320-321` sets `SOLVNFO` (the
`KEY3 = 'SOLVI'` branch), and after every nonlinear iteration
`imp_solv.F:1715-1725` calls `PR_SOLNFO`, which writes the largest residual
force, displacement increment and correction — each with its node id and DOF —
to the run's `_implicit.info` file. `radioss2.F:688-760` opens it beside the
`.hist`, `.tpl`, `.monitor` and `.progress` files, and only for a NONLINEAR
implicit run (`radioss2.F:691`: `IMPL_S > 0 .AND. ILINE == 0 .AND.
SOLVNFO > 0`), so it does nothing on a modal (`/IMPL/LINEAR`) deck — which is
why the converter names it only on non-modal decks.

What it showed on the R14 `ex_27` Taylor-bar pair (round 6): on the penalty
twin, cycles 1-3 were accepted "based on small residual energy" with the
largest residual still 2.1e4-1.5e5 at the interior ring r 2.904; cycle 4's
attempt maximum grew by three to four orders of magnitude over 12-13
cut-backs (1.3e5 → 2.6e8 in round 6's run, 1.31e5 → 5.91e8 in the post-review
re-run), on node 5244 (x 0, y 2.904, z 15.3; DOF 3) in 8 of 12 and 9 of 13
attempts. On the constrained twin WITHOUT its `*CONSTRAINED_GLOBAL` plane (the
pre-round-6 deck, or `--no-constrained-global`), cycle 2's cut-backs grew it
to 2.0e10 / 9.1e9, on node 1423 in 18 of 22 and 16 of 21 attempts. Which node,
and on how many cut-backs, varies from run to run; the ring does not — every
named node sits on r 2.904. The dump located the ring; it did not explain it —
the next section does.

## Known engine defect: implicit dynamics with an initial velocity

An implicit deck with `*CONTROL_IMPLICIT_DYNAMICS` `IMASS > 0` (k2rad writes
`/IMPL/DYNA/2` Newmark) and any `*INITIAL_VELOCITY*` card is wrong in the
OpenRadioss ENGINE, whatever the converter writes. MEASURED on the R14
Taylor-bar pair (`ex_27_solid_elform_2_rigidwall_{constrained_nodes,
penalty}_implicit`):

- With the deck's own first step (`/IMPL/DTINI` 1e-6) the first increment does
  not converge, every cut-back restarts from a corrupted state (the attempt KE
  grows × 2.76, 2.55, 2.44 … → 2.25 per cut, i.e. KE ~ 1/dt²) and the run stops
  at `TIMESTEP LIMIT` — cycle 0 (the constrained twin with its
  `*CONSTRAINED_GLOBAL` plane converted, as k2rad ships it since round 6: 23
  cut-back rows, KE 2.383e5 → 1.297e6), cycle 1 (the same twin without the
  plane, t 6.667e-7, KE 1.054e13) and cycle 3 (penalty twin, t 9.726e-8, KE
  5.819e9), `nt` 4 = `nt` 2 to every printed digit.
- With a first step small enough to converge (`/IMPL/DTINI` 1e-8) the FREE bar
  — the penalty twin, and the constrained twin without its plane
  (`--no-constrained-global`) — ends **NORMAL TERMINATION** (72 cycles,
  t 7.888e-5) with the T01 Z-momentum going **−2.099317 → +6.297951 =
  −3.0000000 × the initial** and KE × 9.00000 from the first converged
  increment on: the bar flies AWAY from the wall, with 0 `RIGID WALL IMPACT`
  lines (7 in the shipped arm). The constrained twin WITH its plane also ends
  NORMAL in 72 cycles (t 7.593e-5), but reads −2.9445759 × (KE × 8.806619) at
  the first T01 sample (t 1.694e-7) and its base is HELD by the plane
  (Z-momentum 8.8e-4 at the end, IE 4 291); `nt` 4 = `nt` 2 on all three.
- The same with the injected contact stub deleted (no contact of any kind) and
  with `/INIVEL/TRA` instead of `/INIVEL/AXIS`.

What is known about the cause is negative only: the Newmark cells are not
swapped (`lectur.F:3432-3434` reads `NEWM_A >= 1/2` as gamma and `NEWM_B` as
beta), and the engine special-cases exactly this path (`imp_dyna.F`
`DYNA_INA`'s `IF (NINVEL>0)` block, `INTE_DYNA`, `imp_solv.F:797-807`). The
faulty line is not isolated, so the converter's warning describes the
measurement and cites no line as the cause. A smaller `/IMPL/DTINI` is NOT a
fix — it trades the error termination for a completed run with the wrong
velocity — so none is shipped. The upstream reproducer is the free bar at
`/IMPL/DTINI` 1e-8 with no wall and no contact: the penalty twin, or the
constrained twin converted with `--no-constrained-global` (72 cycles). Run
such a model EXPLICIT until the engine is fixed.

## Round 9, part A: implicit routes measured

- **Implicit node-to-surface contacts** (A2, default ON,
  `--no-implicit-n2s-type7` keeps the TYPE25). OpenRadioss builds no implicit
  stiffness for an `/INTER/TYPE25` (`imp_int_k.F:111-200` has no TYPE25
  branch; `ind_glob_k.F:4601-4605` prints MESSAGE 232), so on an implicit,
  non-modal deck a `*CONTACT_NODES_TO_SURFACE` /
  `*CONTACT_AUTOMATIC_NODES_TO_SURFACE` is written as a ONE-WAY `/INTER/TYPE7`
  on the same groups (BT / DT in Tstart / Tstop), beside the all-parts
  implicit stub, which carries the contact's friction when every routed
  contact agrees on it. MEASURED on doorbeam (part-driven since A1): IE END
  -15.85 .. -28.08 %, RMS 10.34 .. 15.25 % of the LS peak over twelve runs at
  nt 4 and nt 2, where the TYPE25 ended +53.91 % / 81.05 %. A 4-node one-way
  TYPE7 on a coarse RIGID base can end NORMAL with the block through - a
  silent failure where the TYPE25 stops loudly.
- **Implicit gravity on a rigid part** (A4, default ON,
  `--no-implicit-rigid-gravity-nodes` restores the main-node group). Gravity
  on a `/RBODY` main node alone leaves an implicit body frozen (`gravit_imp.F`
  read; the dropping routine is not located), so on an implicit deck the
  rigid parts' own nodes stay in the `/GRAV` group beside their main: ex_16's
  disk KE -100 % at every fifth -> +0.42 / +0.20 / +0.14 % at the first three
  fifths (NORMAL in 1101 cycles, nt 4 = nt 2; the last two fifths are the
  skipped `*CONTACT_2D`). Explicit decks are unchanged.
- **Arc-length without the quasi-static term** (A11, inside the opt-in
  `--arclength-riks`): the flag writes no `/IMPL/QSTAT` card unless
  `--qstat-dtscal` is given, because the term adds
  `M/((1+alpha)*beta*(DTSCAL*dt)^2)` to the stiffness diagonal
  (`imp_dyna.F:351-355`) and the engine has no QSTAT-versus-RIKS guard
  (`lectur.F:3517-3532` disarms only FIXPOINT). MEASURED on
  `ex_07_beam_elform_1` (five runs of identical bytes): the converged load
  factor loops down to -0.4412 where LS-DYNA's path turns once, at 0.3745,
  and never goes below 0; NORMAL 4 of 5 (1206 / 1192 cycles at nt 4, 1202
  twice at nt 2), ERROR once (MESSAGE 79); `ex_05_beam_elform_3_&_6` still
  stops; both references are UNMATCHED - a load path, not the answer.
- **Implicit CMO -1** (A13): measured on a coupon in the round-9 census -
  u . x' = 1.00000e-2 mm, off-axis <= 1.4e-8, no rotation, IE = EXT-WORK,
  nt 4 = nt 2; six codes x two rotated frames off-axis <= 2.1e-9, energy error
  0.0 %. A `*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL` drive on the same main
  node shares the `/BCS` skew (A9): two skew ids on one node make the implicit
  solver impose a frame-dependent wrong displacement (a two-block coupon:
  x0.750 of the drive in two oblique frames, x1.000 in one skew, nt 4 = nt 2)
  and the starter print WARNING 312.
