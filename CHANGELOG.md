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

- No v4 security fix is included in this baseline. The open P0s are tracked in
  `SECURITY.md` and the v4 plan: optional auth, unrestricted `execute_code`,
  unsafe ZIP extraction, unvalidated download URLs and AABB-only collision
  decisions.

## 3.0.0 - 2026-11-18

See [pro/CHANGELOG.md](pro/CHANGELOG.md) for the Pro v3.0.0 feature list.
The `v3.0.0-baseline` tag marks the code exactly as found before v4 work.
