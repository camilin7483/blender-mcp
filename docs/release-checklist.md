# Release Checklist

Do not publish a stable `v4.0.0` until every required item is checked with
evidence. Items marked `[~]` are implemented but not validated in the target
environment.

## Required gate

- [x] Every FastMCP tool has a matching add-on handler.
- [x] Required parameters match 1:1 (139 tools; `tests/contracts/test_tool_parity.py`).
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
- [~] GitHub Actions workflow exists; it has not been executed on GitHub from
      this machine.
- [~] Windows/macOS Blender headless jobs are experimental and not a required
      gate.
- [ ] External benchmark comparison against another server.
- [x] 11-category benchmark suite (26 tasks; 3 local runs at 26/26).
- [ ] Behavioral tests for every legacy tool (schema parity is covered;
      behavior is targeted).
- [ ] Stable release approval after the open items close.

## Release candidates

| Tag | Meaning |
|---|---|
| `v4.3.0-alpha.1` | Current pre-release: security defaults, geometry/audit, anchors, constraints, assemblies, profiles, export, bench. |
| `v4.0.0-beta` | After CI runs green on Linux 4.5/5.2 and cross-platform Blender is validated. |
| `v4.0.0-rc` | After the external benchmark protocol is published and no critical defect remains. |
| `v4.0.0` | Only when every required item above is checked. |
