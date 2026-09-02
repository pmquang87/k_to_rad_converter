# Contributing to k2rad

Thanks for your interest in improving **k2rad**, the LS-DYNA (`.k`) to
OpenRadioss (`.rad`) converter. This guide is specific to *this* codebase —
please skim it before opening a PR.

## Development setup

The core converter and the Tkinter GUI use **only the Python standard library**,
so there is no install step for ordinary work:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python k2rad.py model.k          # convert a deck; writes model_0000.rad / _0001.rad
```

A few optional features need third-party packages:

- `--auto-gapmin` / `--suggest-gapmin` (mesh-clearance Gapmin) and the offline
  modal eigensolver (`tools/modal_solve.py`) need **scipy** (which pulls in numpy).
- The modal post-processing / visualization tools need **numpy** (and
  `lasso-python` for d3plot export).

Install those only if you touch those paths:

```bash
pip install scipy            # modal / gapmin
pip install numpy lasso-python   # mode-shape export (viz)
```

See [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) for the full matrix and the
graceful-degradation behavior when they are absent (a plain conversion never
imports them).

## Running the tests

Tests are pure `unittest` (no pytest required), runnable with the stdlib alone:

```bash
python -m unittest discover -s tests
```

CI runs exactly that command under `coverage`. `pytest tests/ -q` also works and
is what most contributors use locally — it reports the `subTest` cases
separately, which `unittest` folds into their parent.

The suite is split **one module per keyword family or batch** (the convention
`tests/test_thermal_solver.py` states in its own header). `tests/test_converter.py`
holds the parser, the unit-system header and small end-to-end conversions; the
other modules own their family, and `tests/test_golden.py` converts five
checked-in decks and diffs both `.rad` files byte-for-byte against
`tests/fixtures/expected/`.

## The conversion pipeline

A conversion is a straight-line **parse → dispatch (handlers) → state → writer**
pipeline (see `k2rad/__init__.py::convert`):

1. **Parse** — `k2rad/parser.py::parse_k_file` reads the `.k` deck, resolves
   `*PARAMETER`/`*INCLUDE`, and yields a list of `Block` objects (one per
   `*KEYWORD`), each holding the keyword name and its raw card lines.
2. **Dispatch** — for each block, `k2rad/handlers.py::dispatch` looks the keyword
   up in the `HANDLERS` dict and calls the matching `handle_*` function. Unknown
   keywords are recorded in `state.skipped_keywords` (never a hard error).
3. **State** — each handler parses its cards and appends normalized dataclasses
   onto the shared `ConversionState` (`k2rad/state.py`). Handlers do *not* write
   text; they only populate state.
4. **Write** — `k2rad/writer.py::build_starter` and `build_engine` render the
   `ConversionState` into the `_0000.rad` starter and `_0001.rad` engine decks
   via the many `_make_*` / `_emit_*` helpers.

Keeping parse, state mutation, and text emission in separate stages is the core
design invariant — please preserve it when adding features.

## Adding a new keyword handler

To support a new LS-DYNA keyword:

1. **Write the handler** in `k2rad/handlers.py`: a `handle_<keyword>(block, state)`
   function that reads `block.raw` (use the `_card` / `to_int` / `to_float`
   helpers) and appends dataclass(es) to `state`. Add a new dataclass + a
   collecting field on `ConversionState` in `k2rad/state.py` if the data isn't
   already modeled.
2. **Register it** in the `HANDLERS` dict (near the bottom of `handlers.py`),
   keyed by the keyword string as it appears after the leading `*` (e.g.
   `"LOAD_SEGMENT_SET": handle_load_segment_set`). Aliases map several keys to the
   same handler.
3. **Emit it** — add/extend the relevant `_make_*` / `_emit_*` helper in
   `writer.py` so the new state actually reaches the `.rad` output, and wire it
   into `build_starter` / `build_engine`.
4. **Add a test** in `tests/test_converter.py` — a focused handler test and/or a
   small end-to-end conversion asserting on the emitted Radioss block.
5. **Document it** — add the keyword to the support table in `README.md` and note
   the change in `CHANGELOG.md`.

## Code style

- **Stdlib-only core.** Do not add a third-party import to the core parse/handler/
  writer path. Optional numpy/scipy imports belong behind a feature flag and must
  degrade gracefully (import lazily, print a clear `pip install ...` message).
- Target **Python >= 3.9**. Note that **mypy does not check that floor** — mypy
  2.3.1 refuses `python_version = "3.9"` and checks at 3.10 — so it is enforced
  by `requires-python` and by the 3.9 leg of the CI test matrix, and the
  spelling rules are a review-time convention: `typing.List` / `Dict` /
  `Optional[X]`, never PEP 604 `X | Y` at runtime, no `match` statements.
- Run **ruff** before pushing:

  ```bash
  pip install ruff
  ruff check .
  ```

- Run **mypy** before pushing — the CI type check is **BLOCKING**, and the pin
  matters because a newer mypy can report findings the gate was not measured
  against:

  ```bash
  pip install "mypy==2.3.1"
  mypy k2rad                      # what the CI job runs
  mypy --no-site-packages k2rad   # the same, from a venv that has numpy/scipy
  ```

  Both must be clean. The CI job installs mypy and nothing else, so a dev venv
  with numpy/scipy can see a different picture; `--no-site-packages` reproduces
  the job. A `# type: ignore` must be error-code-scoped and carry a comment
  saying why — `warn_unused_ignores` is on, so a stale one becomes a finding.
- Follow the existing conventions: typed dataclasses in `state.py`, `handle_*`
  functions in `handlers.py`, `_make_*` / `_emit_*` helpers in the `writer/`
  package.

## Pull request workflow

Mirror the convention visible in `git log`: **one feature (or fix) per branch,
one PR per feature**. Branch off, keep the change focused, and open a PR:

```bash
git checkout -b feat/load-segment-set
# ... implement + test ...
git commit -m "Add *LOAD_SEGMENT_SET -> /PLOAD conversion"
```

Make sure `python -m unittest discover -s tests` passes, `ruff check .` is clean
and `mypy k2rad` reports no findings, fill in the PR template, and update
`README.md` / `CHANGELOG.md` as appropriate.
