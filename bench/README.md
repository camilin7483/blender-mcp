# BlenderMCP-Bench

Deterministic task suite for measuring whether this server produces correct
Blender geometry. It is not optimized only for this server: tasks use public
Blender operations and `expected.json` values, so another MCP/agent can run the
same scenarios.

## Current result

- Blender **4.5.4 LTS**, Linux x64, 3 runs.
- **20/20 tasks passed** in every run.
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
| terrain | terrain + rock + scatter | 4×4 m, six instances |
| vegetation | tree, bush, grass, flowers | non-empty meshes |
| water | plane, river, pond | dimensions and faces |
| materials/UV | procedural + unwrap | UV layer, nodes |
| physics | rigid body + collision | ACTIVE, mass 2 |
| lighting/render | light, camera, 64 px still | file exists |
| materials | Principled metal | assigned, metallic 0.8, roughness 0.2 |
| geometry_nodes | GN-only cube | 1000 ± 1 mm, one audited object |
| repair | non-uniform scale | normalized scale |
| visual_scenes | desk + monitor | no collisions, contacts found |
| animation | two keyframes | action, frame range 1–20 |
| rigging | two-bone armature | bone count and parent |

All 11 requested categories are covered; inspection, anchors and constraints
are additional tasks. External comparison is still not performed.

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
