# Migration v3 -> v4

## Status

The published [v4.9.0-alpha.2 prerelease](releases/v4.9.0-alpha.2.md) includes
the v4 bridge and extension. Follow the
[stable-release checklist](release-checklist.md) for remaining validation.

## What changes

| Area | v3 baseline | v4 behavior | Compatibility |
|---|---|---|---|
| Tool names | 53 tools in the original Pro baseline | 313 in the full MCP profile, including anchors, constraints, assemblies, animation, rigging and domain packs | Check the active tool's schema before migrating an existing client call. |
| Anchors | AABB words only | `list_semantic_anchors` + `anchor_operation` | `snap_to_semantic_anchor` preserved |
| Constraints | None | `validate_constraints` + `apply_constraints` | Validation is read-only; apply moves align/mate/offset/ground/center/distance |
| Assemblies | Manual primitives | `create_assembly` + `update_assembly` from a declarative spec | Rebuild from stored spec; desk template and custom components |
| Animation | None | `keyframe_object` for property keyframes | Existing actions are preserved |
| Rigging | `auto_rig_humanoid` only | `create_armature` + `auto_rig_humanoid` | Skinning remains automatic-weights only |
| Response shape | JSON text with free-form keys | Same keys plus `requirements`, `metrics`, `failures`, `warnings` | Old keys preserved during migration |
| Audit | `passed` computed before blueprint | `passed` computed last; structured failures | `critical_issues` and `warnings` remain as derived views. Blueprint, ground, scale, collision and symmetry requirements block `passed`; topology is `report` or `strict`. |
| Protocol | `{"type","params","auth_token"}` | Adds `protocol_version`, `request_id`; newline framing | v3 messages accepted by a compatibility parser |
| Auth | Optional `BLENDER_AUTH_TOKEN` | Per-install token file (0600), enabled by default; default path `$XDG_CONFIG_HOME/blender-mcp/token` | `BLENDER_AUTH_TOKEN` overrides the file; `BLENDER_MCP_ALLOW_NO_AUTH=1` is the unsafe legacy bypass |
| `execute_code` | Enabled and unauthenticated | Disabled by default; explicit opt-in | `BLENDER_MCP_ALLOW_EXECUTE_CODE=1` restores the old behavior for trusted local use |
| Destructive tools | Run immediately | Require `confirm=true`; dry-run otherwise | `BLENDER_MCP_ALLOW_UNSAFE_OPS=1` for legacy automation |
| Output paths | Any path | Confined to `BLENDER_MCP_OUTPUT_DIR` | `BLENDER_MCP_ALLOW_ANY_PATH=1` for trusted automation |
| Export | Format-only write | `godot`/`unity`/`unreal`/`generic-gltf` profiles validate and reimport | `force=True` bypasses validation errors |
| Downloads | Provider URL followed | HTTPS allowlist, private-IP block, size caps, safe ZIP | No legacy bypass |
| Render | Perspective quad in a temp dir | Ortho FRONT/RIGHT/TOP + ISO, modes, metadata, hash output dir | Same `quad_image_path`; new `mode`/`include_overlays` |
| Tool discovery | All tools always | `BLENDER_MCP_PROFILE` selects one of [29 profiles](tools.md#profiles) | The default is `full`. Unknown names fall back to `core`. |
| Blender support | 4.5.4 tested | 4.5.4 and 5.2.4 tested on Linux | See the [platform matrix](compatibility.md). |

## Migration steps

1. Update the bridge and the add-on together. Install the Pro extension ZIP
   and configure the bridge from the matching source.
   [Installation guide](../README.md#installation)
2. On first start, the add-on creates a token file. Point the bridge at the
   same file, or set `BLENDER_AUTH_TOKEN` on both sides.
3. If your automation uses `execute_code`, enable it explicitly in the add-on
   preferences or with `BLENDER_MCP_ALLOW_EXECUTE_CODE=1`. Do not enable it for
   untrusted clients.
4. Review calls to `clear_scene`, `delete_object`, `rollback_checkpoint` and
   `setup_studio_lighting`. Use the dry-run response and add `confirm=true`
   when the intended change is ready.
5. Move exports under `BLENDER_MCP_OUTPUT_DIR`, or set
   `BLENDER_MCP_ALLOW_ANY_PATH=1` for trusted automation. Inspection renders
   also write under that directory (`inspection/<render_id>/`); update scripts
   that read the old temporary path.
6. Re-run your scenes through `audit_3d_model`. New metrics and failures are
   additive; a previously passing scene may now fail if it relied on the old
   AABB collision heuristic or on blueprint warnings that never affected
   `passed`.

## Planned stable milestones

| Release | Behavior |
|---|---|
| Beta | Complete the native platform checks. |
| Release candidate | Freeze the compatibility contract and resolve critical defects. |
| Stable | Meet all items in the release checklist. |

v4 stable is not published until the global acceptance criteria are met,
including real Blender CI and published benchmark artifacts.
