# Architecture

A design overview for contributors. k2rad turns a LS-DYNA `.k` keyword deck
into an OpenRadioss starter (`_0000.rad`) + engine (`_0001.rad`) pair through a
small, linear pipeline: **parse → dispatch(handlers) → ConversionState →
writer**. The core is pure standard-library Python; numpy/scipy are an isolated,
optional dependency used only by the contact-clearance and offline modal tools.

## Data-flow

```
   model.k
      │
      ▼
┌──────────────┐   list[Block]      ┌──────────────┐
│  parser.py   │ ─────────────────► │ handlers.py  │   one Block at a time
│ parse_k_file │  (keyword,         │  dispatch()  │──┐
│  (*INCLUDE   │   options, raw)    │  HANDLERS{}  │  │ handler mutates state
│   inlined)   │                    └──────────────┘  │
└──────────────┘                                      ▼
                                              ┌─────────────────┐
      convert()  (k2rad/__init__.py)          │    state.py     │
      orchestrates the whole run              │ ConversionState │
                                              │  + ConvertOptions│
      ┌───────── post-dispatch fixups ◄───────│  (parsed model) │
      │  inject implicit contact stub,        └─────────────────┘
      │  auto-Gapmin (gapmin.py, opt-in),              │
      │  np>1 / deformable-contact warnings            │  read-only
      ▼                                                ▼
┌──────────────────────────────────────────────────────────────┐
│  writer.py                                                     │
│    build_starter(state) ─► _make_* section builders ─► text   │──► model_0000.rad
│    build_engine(state)  ─► _make_engine_* builders   ─► text  │──► model_0001.rad
└──────────────────────────────────────────────────────────────┘
      │
      ▼
   ConversionResult(starter_path, engine_path, warnings, skipped_keywords, log_path)


   Offline / out-of-core (separate processes, optional deps):
     engine np=1 run  ─►  local_stiffness_matrix_domain0
                              │
     tools/modal_solve.py ────┴─► modes.npz ─► tools/modal_shapes_export.py  (d3plot/VTK)
                                            └─► tools/modal_random_response.py (PSD/RMS/fatigue)
```

## Stages

### 1. Parse — `k2rad/parser.py`

`parse_k_file(path)` reads the deck and returns a flat `list[Block]`. A `Block`
is a dataclass with:

- `keyword` — the normalised base keyword, e.g. `"CONTROL_IMPLICIT_GENERAL"`;
- `options` — trailing suffix tokens stripped off the keyword line (`["TITLE"]`,
  `["ID"]`, …);
- `raw` — the block's data lines, with `$` comments removed.

`*INCLUDE` directives are resolved relative to the including file and the
included blocks are merged inline, so downstream stages see one flat block
stream. Parse-time problems (missing includes, unresolved `&parameters`) are
collected in the module-level `PARSER_WARNINGS` list, which `convert()` folds
into the result *after* dispatch (handlers resolve `&name` fields lazily).

### 2. Dispatch — `k2rad/handlers.py`

The handler layer is a **table-driven registry**. `HANDLERS` (a `dict` near the
bottom of the module, ~line 2431) maps each LS-DYNA keyword string to a handler
function `handle_*(block, state)`. `dispatch(block, state)` is a one-liner:

```python
def dispatch(block, state):
    handler = HANDLERS.get(block.keyword)
    if handler is not None:
        handler(block, state)
```

A keyword with no entry is silently ignored at dispatch (unsupported keywords
are surfaced separately via `state.skipped_keywords` / `handle_skip`). Adding
support for a new keyword is therefore local: write a `handle_foo` function that
parses the block's `raw` cards and stores the result on `state`, then register
it in `HANDLERS`. Many keywords share one handler — several `*MAT_SAMP` /
`*MAT_187`, `*CONTACT_TIED_*` variants, `*LOAD_BODY_{X,Y,Z}`, and the whole
`*CONTROL_*`/`*DATABASE_*` families all route through common handlers, and
explicitly unsupported ones map to `handle_skip`.

Handlers **only fill state** — they perform no `.rad` formatting. This keeps the
LS-DYNA-side parsing and the OpenRadioss-side emission cleanly separated.

### 3. Model — `k2rad/state.py`

`ConversionState` is the single in-memory model that carries everything between
handlers and the writer. It is a plain class (`__init__` initialises ~90
attributes) holding:

- **identity / flags**: `model_title`, `is_implicit`, `is_modal`, `units`, an
  auto-ID counter (`next_id()`), and `options` (a `ConvertOptions` dataclass);
- **mesh**: `nodes`, `shell_elems`, `solid_elems`, `beam_elems`;
- **entities**: `parts`, section dicts, the per-law material dicts
  (`mat_elastic`, `mat_plas_tab`, `mat_rigid`, `mat_high_explosive`, `eos_*`, …),
  `curves`, coordinate systems;
- **sets / groups**: `node_sets`, `part_sets`, `segment_sets`;
- **BCs, constraints, loads, contacts, ALE/FSI, control, database/output**
  — each a list or dict of small per-keyword dataclasses (`BcsSpc`,
  `ContactTied`, `LoadBlastEnhanced`, `ControlImplicitEigenvalue`, …);
- **diagnostics**: `warnings` (via `state.warn()`) and `skipped_keywords`.

Every LS-DYNA concept has its own small `@dataclass` (defined at the top of
`state.py`) so a handler stores structured data, not raw strings. `warn()` and
`next_id()` are the only behaviour on the state object; everything else is data.

`ConvertOptions` holds the opt-in CLI switches (`auto_gapmin`, `gapmin_factor`,
`deformable_contact_recipe`, `emit_eig`, `ams`, `rigid_cog_master`,
`write_restart`, `blast_ground`, …). All default to off/neutral so a default
conversion is byte-identical regardless of the flags a caller passes.

### 4. Orchestration — `k2rad/__init__.py`

`convert(input_path, output_stem=None, units=..., **options)` drives the run and
returns a `ConversionResult(starter_path, engine_path, warnings,
skipped_keywords, log_path)`:

1. parse the deck to blocks;
2. build a fresh `ConversionState`, attach `units` + a `ConvertOptions`;
3. `dispatch()` every block (with a `progress` callback for the CLI/GUI);
4. run post-dispatch fixups that need the whole model in hand:
   `_inject_implicit_contact_stub` (a contact-free implicit deck segfaults the
   engine), blast-unit reconciliation, opt-in `apply_auto_gapmin`
   (from `gapmin.py`), and the np>1 / deformable-contact warnings imported from
   the writer;
5. `build_starter(state)` and `build_engine(state)` produce the two decks;
6. write both files (utf-8, `\n` newlines) and, unless disabled, an auto-saved
   `<stem>_conversion.log` of warnings + skipped keywords.

`ConversionResult` is the public model of the run's outcome: the two output
paths plus the `warnings` and de-duplicated `skipped_keywords` lists that the
CLI/GUI surface to the user.

### 5. Emit — `k2rad/writer.py`

The writer reads state (never mutates the physics) and returns deck text.

`build_starter(state, progress=None)` first runs a few mesh pre-passes
(`_resolve_mat_*`, `_normalize_tet10_ordering`, optional TET10→TET4 downgrade,
`_snap_tet10_midsides`, `_screen_sliver_tets`), builds the rigid bodies
(`_make_rbodies` +
`_make_cnrb_rbodies` + `_make_probe_rbody`), then assembles the deck by
**appending an ordered list of section blocks**, one per `_make_*` builder:
`_make_header`, `_make_materials`, `_make_nodes`, `_make_parts_and_elements`,
`_make_interfaces`, `_make_tied_interfaces`, `_make_pressure_loads`,
`_make_blast_loads`, `_make_eig`, `_make_damping`, `_make_skipped_comment`, …
Each builder returns a `list[str]` of `.rad` lines; the builders are called in a
fixed sequence and concatenated. (This ordered call sequence is effectively a
hand-maintained section registry — see `ROADMAP.md` for the proposal to make it
a data-driven one.)

`_normalize_tet10_ordering` is the **first** tet10 pre-pass: it rewrites every
10-node tet's connectivity into the Radioss `/TETRA10` midside convention
(`topology.TET10_MIDEDGE`: n8=mid(1,4), n9=mid(2,4), n10=mid(3,4)) before any
other pass reads the midside slots. LS-DYNA `*ELEMENT_SOLID` orders the three
apex midsides differently (n8=mid(2,4), n9=mid(3,4), n10=mid(1,4)); the pass
detects the source order geometrically (nearest apex-edge midpoint, per element)
and permutes LS-DYNA→Radioss via `topology.TET10_DYNA_TO_RADIOSS`, defaulting to
that permutation with a loud warning on ambiguous/mixed/coordinate-less meshes
(every real LS-DYNA deck is DYNA-ordered; Altair hm_reader permutes on import the
same way). It is idempotent (`state.tet10_normalized`; the permutation is a
3-cycle) and also runs before the `--auto-gapmin` clearance analysis so that
analysis sees the same surface the engine builds. Without it, the downstream
snap pass collapsed shared midside nodes (ERROR 558) and the verbatim `/TETRA10`
emit dropped ~30% of every quadratic tet's volume.

`build_engine(state)` is the analogous, much smaller assembly of engine
sections: `_make_engine_header`, `_make_engine_restart`, `_make_engine_output`,
`_make_engine_timestep`, `_make_engine_implicit`, `_make_engine_cpu`, `/MON/ON`.

The writer is the largest module (~5.5 k lines) because it owns every card
format and the empirically-derived OpenRadioss workarounds.

## Optional dependency isolation

The core path — parse, dispatch, state, `build_starter`/`build_engine` — imports
**only the standard library**. Two areas need numpy/scipy and are deliberately
walled off so a default conversion never imports them:

- **`k2rad/gapmin.py`** (`--auto-gapmin` / `--suggest-gapmin`): measures the
  node-to-segment contact clearance with `scipy.spatial.cKDTree` + an exact
  point-triangle kernel to suggest each `/INTER/TYPE7` `Gapmin`. It is imported
  lazily inside `convert()` **only when `options.auto_gapmin` is set**, and
  reports a clear `pip install scipy` message (applying no Gapmin) when the
  packages are absent. It reuses the neutral `topology.TET10_MIDEDGE` map (the
  Radioss `/TETRA10` order) so its faceting matches what the engine builds for a
  `/TETRA10` surface; `_normalize_tet10_ordering` runs first (in `convert()` when
  `--auto-gapmin` is set) so the analyzed connectivity is already Radioss-ordered.
- **`tools/modal_*.py`** (offline modal chain): these are standalone scripts,
  **not part of the `k2rad` package** and never imported by `convert()`. They
  sit *downstream* of the converter — they run on the engine's
  `local_stiffness_matrix_domain0` export plus the source `.k`, after a normal
  np=1 solve. `modal_solve.py` (scipy) solves the eigenproblem; `modal_common.py`
  holds shared mesh/npz/unit helpers; `modal_shapes_export.py` (numpy, optional
  lasso-python) writes viewable mode shapes; `modal_random_response.py` (numpy)
  does PSD/RMS/Dirlik-fatigue post-processing. Each exits with a clear
  `pip install …` message when its dependency is missing.

See [`DEPENDENCIES.md`](DEPENDENCIES.md) for the full dependency matrix and the
rationale for the scipy-cKDTree backend choice.

## Where things live

| File | Role |
|---|---|
| `k2rad/parser.py` | `.k` → `list[Block]`; `*INCLUDE` inlining; `PARSER_WARNINGS` |
| `k2rad/handlers.py` | `HANDLERS` registry + `dispatch()`; one `handle_*` per keyword |
| `k2rad/state.py` | `ConversionState`, per-keyword dataclasses, `ConvertOptions` |
| `k2rad/writer.py` | `build_starter` / `build_engine` + all `_make_*` section builders |
| `k2rad/gapmin.py` | optional (scipy) node-to-segment `Gapmin` suggestion |
| `k2rad/__init__.py` | `convert()` orchestration + `ConversionResult` |
| `k2rad.py` / `run_converter.py` | CLI entry point / hardcoded-path script |
| `tools/modal_*.py` | offline (numpy/scipy) modal solve + post-processing |
