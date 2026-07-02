# Dependencies

## Baseline: standard library only

k2rad's core — parsing a LS-DYNA `.k` deck and writing the OpenRadioss
`_0000.rad` / `_0001.rad` starter and engine decks — uses **only the Python
standard library**. `import k2rad` and a default conversion

```
python k2rad.py model.k
```

never import any third-party package. The Tkinter GUI (`k2rad_gui.py`) uses only
`tkinter`, which ships with CPython. So a plain conversion has **no install
step** beyond Python 3.8+.

## Optional: numpy + scipy (auto-Gapmin and the modal eigensolver)

Three features need numpy + scipy. Two measure the **node-to-segment contact
clearance** to suggest a per-interface `/INTER/TYPE7` `Gapmin`; the third is
the offline eigensolver of the modal stiffness-export recipe:

| Feature | Flag / entry point |
|---|---|
| Apply auto-Gapmin during conversion | `--auto-gapmin` / "Auto Gapmin from mesh clearance" checkbox |
| Report suggested Gapmins (read-only) | `--suggest-gapmin` |
| Solve normal modes from an `/IMPL/PRINT/STIF` export | `python tools/modal_solve.py` (sparse symmetric eigsh, shift-invert) |

These need a fast point-to-mesh distance query, which requires:

```
pip install scipy          # numpy comes in as a dependency
```

(installs `numpy` + `scipy`; tested with numpy 2.4.6 / scipy 1.17.1 on
Python 3.12, Windows).

### Behaviour when they are absent

The dependency is **optional and degrades gracefully**:

* A default conversion (no `--auto-gapmin`) is unaffected — it never touches this
  code path.
* `--auto-gapmin` applies **no** Gapmin and prints a clear message telling you to
  `pip install scipy`. The `.rad` output is otherwise identical to a plain
  conversion, so nothing breaks — you simply do not get an auto-Gapmin.
* `--suggest-gapmin` prints the same note and suggests nothing.
* `tools/modal_solve.py` exits with a clear `pip install scipy` message.
  (Converting a modal deck itself needs nothing — only the offline solve does.)

There is intentionally **no node-to-node fallback** (see below).

## Why node-to-segment, and why scipy

OpenRadioss `/INTER/TYPE7` engages a secondary **node** against a main
**segment** (a surface facet). The clearance the solver actually sees is the
distance from each secondary node to the nearest *point of a facet* — which
usually lies on the facet interior, not at a vertex.

An earlier version measured node-to-**node** distance (closest approach between
the two parts' *nodes*). That over-estimates the real clearance, so a `Gapmin`
derived from it still left initial penetrations (starter `WARNING 343`) — on the
elevator-linkage decks, **even at factor 0.1**. Node-to-node was therefore
**removed**; node-to-segment is the only measure.

The node-to-segment search is a point-to-mesh query over a large mesh
(~100 MB / hundreds of thousands of nodes and facets), so it must be accelerated
by a spatial tree. The backend choice:

* **libigl** (`igl.point_mesh_squared_distance`) — would be ideal (single call,
  internal AABB tree), but it ships **no Windows / CPython 3.12 wheel** and its
  source build fails here (its bundled embree will not compile with the local
  toolchain). Rejected: not installable as a simple optional dependency.
* **trimesh + rtree/embree** — works, but `closest_point` loops per query point
  in Python (slow without pre-pruning) and pulls in more packages. Heavier.
* **scipy.spatial.cKDTree + an exact point-triangle kernel** *(chosen)* —
  reliable prebuilt Windows wheels, and `numpy` is already pulled in. A cKDTree
  gives a global upper bound on the closest approach, which prunes the secondary
  nodes to those near the surface and, per node, the facets near it; the exact
  point-to-triangle distance then runs on only a handful of pairs. This keeps the
  query in the **seconds range** on the large TET10 mesh. The point-to-triangle
  kernel (Ericson, *Real-Time Collision Detection* §5.1.5) is implemented in
  `k2rad/gapmin.py` — pure Python for the reference/tests, vectorised with numpy
  for the hot path.

## TET10 contact faceting

For a `/TETRA10` part the engine builds each external face as **4 linear
sub-triangles** through the mid-edge nodes (this is what `/SURF/SEG`/`/SURF/PART`
needs to avoid `ERROR 611`). The clearance measurement matches that exactly,
reusing the writer's validated mid-edge map (`writer._TET10_MIDEDGE`), so the
distance reported is the one the engine actually sees.

## Summary

| You want to… | Need |
|---|---|
| Convert a deck (CLI or GUI) | Python 3.8+ only |
| Use `--auto-gapmin` / `--suggest-gapmin` | `pip install scipy` |
| Solve modes with `tools/modal_solve.py` | `pip install scipy` |
