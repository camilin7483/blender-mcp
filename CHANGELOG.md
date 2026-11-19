# Changelog

All notable changes to this repository are documented here.

## Unreleased

### Added

- Baseline harness with real Blender 4.5 LTS: headless import/geometry test
  and GUI socket round-trip under `xvfb-run`.
- Contract test that verifies 1:1 parity between the 53 FastMCP tools and the
  add-on command table.
- `SECURITY.md` threat model, `ARCHITECTURE.md`, `CONTRIBUTING.md`,
  `docs/compatibility.md`, `docs/benchmark.md` and
  `docs/migration-v3-v4.md`.
- Pinned bridge dependency in `pro/requirements.txt` (`mcp==1.30.0`).

### Changed

- Consolidated the Pro v3 sources under `pro/` in the canonical repository.
- `pro/sync_addon.sh` now resolves paths relative to the script and accepts
  `BLENDER_ADDONS_DIR`.
- Root README documents the legacy and Pro editions.

### Security

- Local authentication is enabled by default. The add-on creates a per-install
  token file (0600) and the bridge reads it; `BLENDER_AUTH_TOKEN` still
  overrides the file. `BLENDER_MCP_ALLOW_NO_AUTH=1` is the explicit unsafe
  escape hatch.
- `execute_code` is disabled by default. Enable it in the add-on preferences
  or with `BLENDER_MCP_ALLOW_EXECUTE_CODE=1`.
- `clear_scene`, `delete_object`, `rollback_checkpoint` and
  `setup_studio_lighting` return a dry-run unless called with `confirm=true`.
  `BLENDER_MCP_ALLOW_UNSAFE_OPS=1` preserves the old behavior for trusted
  automation.
- `export_scene` is confined to `BLENDER_MCP_OUTPUT_DIR`, validates the
  extension and rejects unknown formats. `BLENDER_MCP_ALLOW_ANY_PATH=1`
  preserves the old behavior for trusted automation.
- Batched requests are parsed incrementally instead of being dropped, and
  request/response sizes are bounded.
- Commands are routed through a main-thread queue with one persistent timer,
  removing the unsupported `bpy.app.timers.register()` call from socket
  threads.
- Still open: unrestricted `execute_code`, unsafe ZIP extraction, unvalidated
  download URLs and the AABB-only collision decision. See `SECURITY.md`.

## 3.0.0 - 2026-11-18

See [pro/CHANGELOG.md](pro/CHANGELOG.md) for the Pro v3.0.0 feature list.
The `v3.0.0-baseline` tag marks the code exactly as found before v4 work.
