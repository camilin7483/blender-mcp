# Benchmark

## Status

The [v4.9.0-alpha.2 release gate](releases/v4.9.0-alpha.2.md) passed 46 of 46
tasks in each of three runs on Blender 4.5.4 and 5.2.4. GitHub Actions retains
per-version task artifacts with the workflow run. Tool registration is
verified separately through MCP stdio and the schema/handler contract tests.

## Published baseline

A first local run is published in `bench/results/latest/`:

- Blender 4.5.4 LTS, Linux x64, 3 runs.
- 46/46 tasks passed in every run.
- `summary.json` contains medians and per-run results; `trace.jsonl` contains
  the per-task trace; `run_1/` contains `.blend`, `.glb` and render artifacts.
- All 11 baseline categories are covered by at least one task. External
  comparison remains open.

The [showcase](showcase/README.md) includes art, editable projects and
scene-specific checks alongside the functional benchmark.

## BlenderMCP-Bench

The benchmark must not be optimized only for this server. It is a task suite
that any Blender MCP server can run.

### Categories

1. Primitives
2. Dimensions
3. Assemblies
4. Topology
5. Materials
6. Geometry Nodes
7. Animation
8. Rigging
9. Repair
10. Export
11. Visual scenes

### Task format

Each task directory contains:

```
task.json          prompt, allowed tools, timeout, token budget
expected.json      dimensional/topological/contact requirements
assets/            optional input assets
```

Example `expected.json`:

```json
{
  "dimensions_mm": {
    "width": {"target": 1000, "tolerance": 1}
  },
  "topology": {"non_manifold_edges": 0}
}
```

### Artifacts

A run produces:

```
.blend
.glb
metrics.json
trace.jsonl
renders/
```

`metrics.json` records the measured values, the method, the tolerance and
pass/fail. `trace.jsonl` records each tool call with timestamps and token
usage.

### External comparison

To compare two servers, hold constant:

- LLM and exact model version
- prompt
- Blender version
- machine
- token budget
- timeout
- assets
- seed
- maximum number of tool calls

Run multiple trials. Publish raw results, methodology, failures, medians,
standard deviation, exact versions and commits. Include the cases where this
server loses.

### Reporting rules

- No percentage claims without the raw artifacts.
- Separate model quality from server quality.
- Report failed runs, not only successful ones.
- Do not compare runs with different models, prompts or budgets.
