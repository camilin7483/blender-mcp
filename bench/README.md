# BlenderMCP-Bench

Deterministic task suite for measuring whether this server produces correct
Blender geometry. It is not optimized only for this server: tasks use public
Blender operations and `expected.json` values, so another MCP/agent can run the
same scenarios.

## Current result

- Blender **4.5.4 LTS**, Linux x64, 3 runs.
- **8/8 tasks passed** in every run.
- Raw data: `bench/results/latest/summary.json`, `trace.jsonl`, and per-task
  `metrics.json`.
- This is a functional baseline, not evidence of superiority over another
  server. No external comparison has been performed.

## Covered categories

| Category | Task | Expected |
|---|---|---|
| primitives | 1000 mm cube | 1000 ± 1 mm, manifold |
| dimensions | desk 1600 × 800 × 750 mm | ± 5 mm |
| assemblies | desk width 1600 → 1200 mm | ± 5 mm, no duplicates |
| topology | clean cube | 0 non-manifold, loose, zero-area |
| inspection | front orthographic render | ORTHO camera, image exists |
| export | godot GLB + reimport | reimport matches dimensions |
| anchors | cube top-center | position `[0,0,1]`, source |
| constraints | desk ground + no-intersection | all constraints pass |

Not yet covered: materials, Geometry Nodes, animation, rigging and open visual
scenes. Do not claim those categories until tasks and raw results exist.

## Reproduce

```bash
BLENDER_BIN=/path/to/blender ./scripts/run_bench.sh --runs 3 --output bench/results/latest
```

Each task gets a fresh scene, executes through the add-on API, compares against
`expected.json`, and writes:

```
bench/results/latest/
  summary.json
  trace.jsonl
  run_<n>/<task>/
    metrics.json
    scene.blend
    bench_cube.glb        # export task
    inspection/.../*.png  # inspection task
```

## External comparison protocol

A valid comparison against another server requires the same LLM, model version,
prompt, Blender version, machine, token budget, timeout, assets, seed and
maximum tool calls. Run multiple trials, publish raw outputs, medians,
deviation, failures and exact commits. Never publish a savings percentage
without the benchmark run that supports it.
