# Benchmark

## Status

**No benchmark results are published yet.** This document defines the
methodology. Do not claim savings or superiority without a published run.

The only baseline facts currently measured are:

- 53 registered MCP tools.
- 47,792 characters of tool-schema JSON, measured with
  `FastMCP.list_tools()` on `mcp==1.30.0`.
- 53 add-on handlers with 1:1 name parity (see
  `tests/contracts/test_tool_parity.py`).

These are baseline measurements, not improvements. The current branch
registers 203 tools; remeasure schema size before publishing any comparison.

## Published baseline

A first local run is published in `bench/results/latest/`:

- Blender 4.5.4 LTS, Linux x64, 3 runs.
- 34/34 tasks passed in every run.
- `summary.json` contains medians and per-run results; `trace.jsonl` contains
  the per-task trace; `run_1/` contains `.blend`, `.glb` and render artifacts.
- No external comparison has been performed. Categories not covered yet:
  All 11 requested categories are covered by at least one task.

These are functional measurements, not evidence of superiority.

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
