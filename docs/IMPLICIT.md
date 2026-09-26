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
attempt maximum grew 1.3e5 → 2.6e8 over 12 cut-backs, node 5244 (x 0,
y 2.904, z 15.3; DOF 3) in 8 of the 12. On the constrained twin, over cycle
2's 22 cut-backs it grew 4.2e3 → 2.0e10, node 1423 in 18 of 22. The dump
located the ring; it did not explain it — the next section does.

## Known engine defect: implicit dynamics with an initial velocity

An implicit deck with `*CONTROL_IMPLICIT_DYNAMICS` `IMASS > 0` (k2rad writes
`/IMPL/DYNA/2` Newmark) and any `*INITIAL_VELOCITY*` card is wrong in the
OpenRadioss ENGINE, whatever the converter writes. MEASURED on the R14
Taylor-bar pair (`ex_27_solid_elform_2_rigidwall_{constrained_nodes,
penalty}_implicit`):

- With the deck's own first step (`/IMPL/DTINI` 1e-6) the first increment does
  not converge, every cut-back restarts from a corrupted state (the attempt KE
  grows × 2.76, 2.55, 2.44 … → 2.25 per cut, i.e. KE ~ 1/dt²) and the run stops
  at `TIMESTEP LIMIT` — cycle 1 (constrained twin, t 6.667e-7, KE 1.054e13) and
  cycle 3 (penalty twin, t 9.726e-8, KE 5.819e9), `nt` 4 = `nt` 2 to every
  printed digit.
- With a first step small enough to converge (`/IMPL/DTINI` 1e-8) both twins
  end **NORMAL TERMINATION** (71 cycles, t 7.888e-5) — with the T01 Z-momentum
  going **−2.099317 → +6.297951 = −3.0000000 × the initial** and KE × 9.00000
  from the first converged increment on: the bar flies AWAY from the wall, with
  0 `RIGID WALL IMPACT` lines (7 in the shipped arm).
- The same with the injected contact stub deleted (no contact of any kind) and
  with `/INIVEL/TRA` instead of `/INIVEL/AXIS`.

What is known about the cause is negative only: the Newmark cells are not
swapped (`lectur.F:3432-3434` reads `NEWM_A >= 1/2` as gamma and `NEWM_B` as
beta), and the engine special-cases exactly this path (`imp_dyna.F`
`DYNA_INA`'s `IF (NINVEL>0)` block, `INTE_DYNA`, `imp_solv.F:797-807`). The
faulty line is not isolated, so the converter's warning describes the
measurement and cites no line as the cause. A smaller `/IMPL/DTINI` is NOT a
fix — it trades the error termination for a completed run with the wrong
velocity — so none is shipped. The constrained twin at `/IMPL/DTINI` 1e-8
(no wall, no contact, 71 cycles, ~60 s) is the upstream reproducer. Run such a
model EXPLICIT until the engine is fixed.
