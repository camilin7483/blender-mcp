# Release Checklist

A stable v4 release requires evidence for every item. Open boxes describe the
coverage still pending.

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
- [x] GitHub Actions completed all seven jobs for
      [v4.9.0-alpha.2](https://github.com/camilin7483/blender-mcp/actions/runs/44691708164).
- [x] All seven jobs passed on [the showcase integration](https://github.com/camilin7483/blender-mcp/actions/runs/44766497696),
      including packaged extension installs and reopening both documented scenes.
- [x] Windows x64 and macOS arm64 headless smoke checks passed in CI.
- [ ] Native Windows/macOS interactive socket, rendering, and extension
      installation tests. Windows CI skips render cases.
- [ ] External benchmark comparison against another server.
- [x] 46-task benchmark covering the 11 baseline categories and additional
      domain packs. Each of the three runs per Linux Blender version passed 46/46.
- [ ] Behavioral tests for every tool. Current coverage includes handler and
      schema parity for 313 tools, 34 host tests, real-Blender suites, and the
      46-task benchmark.
- [ ] Stable release approval after the open items close.

## Local release gate

`scripts/release_gate.sh` runs host tests, lint, Blender 4.5/5.2 headless+GUI,
the 46-task benchmark (3 runs per supplied Blender version), extension
build/validation and a bridge dependency inventory. Use `RELEASE_GATE_OUT`
to isolate a run. A missing Blender 5.2 binary produces a partial result.
The gate records both version strings and verifies identical normalized ZIPs
when both versions are supplied.
The [published alpha.2 evidence](releases/v4.9.0-alpha.2.md) records the commit,
extension checksum and CI run. A local rerun writes `gate.json`, `SHA256SUMS`,
`sbom.json`, logs, and benchmark results to the configured output directory.

## Release candidates

| Tag | Meaning |
|---|---|
| `v4.9.0-alpha.2` | Published alpha build with 313 registered tools and a verified Linux gate. |
| Beta | After the full cross-platform Blender checks are validated. |
| Release candidate | After an external benchmark comparison is published and critical defects are resolved. |
| Stable | After all required checks pass. |
