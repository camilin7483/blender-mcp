# Migration v3 -> v4

## Status

**Draft. v4 is not released.** This document describes the intended breaking
changes and the compatibility wrappers. It will be updated before each v4
release candidate.

## What changes

| Area | v3 baseline | v4 target | Compatibility |
|---|---|---|---|
| Tool names | 53 tools | Same names; new tools added behind profiles | Old names keep working until v4.1 |
| Response shape | JSON text with free-form keys | Same keys plus `requirements`, `metrics`, `failures`, `warnings` | Old keys preserved during migration |
| Audit | `passed` computed before blueprint | `passed` computed last; structured failures | `critical_issues` and `warnings` remain as derived views. Blueprint, ground, scale, collision and symmetry requirements block `passed`; topology is `report` or `strict`. |
| Protocol | `{"type","params","auth_token"}` | Adds `protocol_version`, `request_id`; newline framing | v3 messages accepted by a compatibility parser |
| Auth | Optional `BLENDER_AUTH_TOKEN` | Per-install token file (0600), enabled by default; default path `$XDG_CONFIG_HOME/blender-mcp/token` | `BLENDER_AUTH_TOKEN` overrides the file; `BLENDER_MCP_ALLOW_NO_AUTH=1` is the unsafe legacy bypass |
| `execute_code` | Enabled and unauthenticated | Disabled by default; explicit opt-in | `BLENDER_MCP_ALLOW_EXECUTE_CODE=1` restores the old behavior for trusted local use |
| Destructive tools | Run immediately | Require `confirm=true`; dry-run otherwise | `BLENDER_MCP_ALLOW_UNSAFE_OPS=1` for legacy automation |
| Output paths | Any path | Confined to `BLENDER_MCP_OUTPUT_DIR` | `BLENDER_MCP_ALLOW_ANY_PATH=1` for trusted automation |
| Downloads | Provider URL followed | HTTPS allowlist, private-IP block, size caps, safe ZIP | No legacy bypass |
| Render | Perspective quad in a temp dir | Ortho FRONT/RIGHT/TOP + ISO, modes, metadata, hash output dir | Same `quad_image_path`; new `mode`/`include_overlays` |
| Tool discovery | All 53 tools always | Profiles: `core`, `modeling`, `materials`, `animation`, `rigging`, `geometry_nodes`, `inspection`, `export`, `full` | `full` preserves the v3 surface |
| Blender support | 4.5.4 tested | 4.5 LTS required, 5.2 LTS secondary | ADR-0002 |

## Migration steps

1. Update the bridge and the add-on together. A v4 bridge can talk to a v3
   add-on only through the compatibility parser; a v4 add-on can serve v3
   messages.
2. On first start, the add-on creates a token file. Point the bridge at the
   same file, or set `BLENDER_AUTH_TOKEN` on both sides.
3. If your automation uses `execute_code`, enable it explicitly in the add-on
   preferences or with `BLENDER_MCP_ALLOW_EXECUTE_CODE=1`. Do not enable it for
   untrusted clients.
4. Review calls to `clear_scene`, `delete_object`, `boolean_operation` and
   `rollback_checkpoint`. Add `confirm=true` or use the dry-run response.
5. Move exports under `BLENDER_MCP_OUTPUT_DIR`, or set
   `BLENDER_MCP_ALLOW_ANY_PATH=1` for trusted automation. Inspection renders
   also write under that directory (`inspection/<render_id>/`); update scripts
   that read the old temporary path.
6. Re-run your scenes through `audit_3d_model`. New metrics and failures are
   additive; a previously passing scene may now fail if it relied on the old
   AABB collision heuristic or on blueprint warnings that never affected
   `passed`.

## Deprecation timeline

| Release | Behavior |
|---|---|
| `v4.0.0-alpha` | Compatibility parser, old keys, `full` profile. Auth and `execute_code` defaults change. |
| `v4.0.0-beta` | Structured audit failures; legacy keys derived. |
| `v4.0.0-rc` | Wrappers frozen; only bug fixes. |
| `v4.0.0` | Stable contract. |
| `v4.1.0` | Legacy wrappers may be removed after a deprecation notice. |

v4 stable is not published until the global acceptance criteria are met,
including real Blender CI and published benchmark artifacts.
