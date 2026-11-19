# Changelog

All notable changes to this repository are documented here.

## 4.0.0-alpha - 2026-11-19 (unreleased)

### Added

- Evaluated `GeometryService`: local/world AABB, world-space BVH, contact
  graph, topology metrics, symmetry error, ground contact and absolute/
  relative tolerance model.
- `audit_3d_model` now returns `requirements`, `dimensions`, `topology`,
  `contacts`, `collisions`, `symmetry` and structured `failures`, while
  preserving the legacy `critical_issues`, `warnings`, `joints` and
  `llm_fix_commands` views.
- Deterministic inspection renders: orthographic FRONT/RIGHT/TOP, fixed ISO
  perspective, `silhouette`/`wireframe`/`normals`/`uv_checker` modes,
  reproducible output directories, camera metadata and optional AABB overlay.
- Semantic anchors with position, normal, tangent, local frame, source,
  confidence and tolerance: center, face, surface (BVH raycast), edge, corner,
  socket (empty), bone and custom anchors. `list_semantic_anchors` and
  `anchor_operation` cover align, mate, offset, orient_normal, distribute and
  mirror.
- Read-only constraint validator: mate, align, flush, center, offset,
  distance, parallel, perpendicular, ground_contact, symmetry,
  no_intersection, inside and surface_contact, with structured expected/
  actual/tolerance/method results.
- Tool profiles (`core`, `modeling`, `materials`, `animation`, `rigging`,
  `geometry_nodes`, `inspection`, `export`, `assets`, `full`) filter FastMCP
  registration through `BLENDER_MCP_PROFILE`; unknown names fail open.
- Game-ready export profiles (`godot`, `unity`, `unreal`, `generic-gltf`)
  validate scale, materials, UVs, armatures, actions, LOD and collision
  meshes, then reimport the file into the scene and compare dimensions.
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
- Collision decisions use BVH surface intersection; AABB is broad-phase only.
  Geometry Nodes-only objects are measured and audited.
- `audit_3d_model` computes `passed` after every requirement. Blueprint
  dimensions, ground contact, absolute scale, surface intersections and
  optional symmetry now block `passed`; topology is report-only unless
  `topology_policy="strict"`. Negative scale is accepted as a mirror.
- `render_multiview_inspection` uses orthographic FRONT/RIGHT/TOP cameras,
  writes under `<output>/inspection/<render_id>/`, returns camera metadata
  and accepts `mode` plus `include_overlays`.

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
- Remote assets are limited to HTTPS Poly Haven and Sketchfab hosts, reject
  private/link-local/loopback addresses and redirects to them, cap download
  size, and extract ZIPs with path, symlink, file-count and size checks.
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
