# Release Checklist

Do not publish a stable `v4.0.0` until every required item is checked with
evidence. Items marked `[~]` are implemented but not validated in the target
environment.

## Required gate

- [x] Every FastMCP tool has a matching add-on handler.
- [x] Required parameters match 1:1 (313 tools; `tests/contracts/test_tool_parity.py`).
- [x] Every tool has a docstring and a profile assignment.
- [x] `bpy` command execution runs on Blender's main thread; background start
      fails fast.
- [x] `execute_code` is disabled by default and has an explicit opt-in.
- [x] Local auth token is created with 0600 permissions and compared with
      `hmac.compare_digest`.
- [x] Destructive tools require confirmation or an explicit unsafe opt-in.
- [x] Exports are confined to the output sandbox; unknown formats fail.
- [x] Downloads use HTTPS allowlists, private-IP blocking, size caps and safe
      ZIP extraction.
- [x] Evaluated geometry is used for dimensions, contacts, topology and ground.
- [x] AABB is broad-phase only; collisions come from BVH intersection.
- [x] Audit computes requirements and `passed` last; failures are structured.
- [x] Contract graph, topology metrics, symmetry, anchors and constraints have
      real-Blender tests.
- [x] Multiview cameras are documented and outputs are hashed.
- [x] Export profiles validate and reimport the file.
- [x] Benchmark publishes raw artifacts with `expected.json` and 3 local runs.
- [x] Blender 4.5.4 headless + GUI tests pass.
- [x] Blender 5.2.4 headless + GUI tests pass.
- [x] Extension builds, validates and installs in Blender 4.5 and 5.2.
- [~] GitHub Actions workflow exists and YAML is valid; it has not been
      executed on GitHub. `gh` authentication is invalid and Docker is not
      available, so local Actions emulation is blocked.
- [~] Windows/macOS Blender headless jobs are experimental and not a required
      gate; only the Linux 4.5/5.2 jobs were executed locally.
- [ ] External benchmark comparison against another server.
- [x] 11-category benchmark suite (46 tasks; 3 local runs at 46/46).
- [~] Behavioral tests for every tool: schema/handler parity is 313/313 and
      behavior is covered by 29 host tests, real-Blender sections and 46
      benchmark tasks; it is not one bespoke behavioral test per tool.
- [ ] Stable release approval after the open items close.

## Local release gate

`scripts/release_gate.sh` runs host tests, lint, Blender 4.5/5.2 headless+GUI,
the 46-task benchmark (3 runs), extension build/validation and SBOM generation.
Last local evidence:

- `bench/results/release-gate/gate.json`
- `bench/results/release-gate/SHA256SUMS`
- `bench/results/release-gate/sbom.json`
- `bench/results/release-gate/logs/`

The gate is local evidence, not a substitute for GitHub CI or Windows/macOS
hardware.

## Release candidates

| Tag | Meaning |
|---|---|
| `v4.9.0-alpha.1` | Current pre-release: 313 tools, character depth, world/materials/FX, local release gate green. |
| `v4.0.0-beta` | After CI runs green on Linux 4.5/5.2 and cross-platform Blender is validated. |
| `v4.0.0-rc` | After the external benchmark protocol is published and no critical defect remains. |
| `v4.0.0` | Only when every required item above is checked. |
