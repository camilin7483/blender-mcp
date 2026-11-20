# Blender MCP Pro workflow examples

Start Blender with the extension enabled and connect the bridge with the
`full` profile. Open a fresh scene for each example and remove its default
objects before running the calls. Each JSON block supplies the arguments for
the named MCP tool. The [tool reference](tools.md) lists the other inputs.

## Find a tool and check the connection

| Tool | Example arguments | What to look for |
| --- | --- | --- |
| `get_scene_info` | `{"max_objects": 10}` | The active scene and a sample of its objects. |
| `tools_catalog` | `{"category": "character"}` | The character tools available in the active profile. |
| `tools_search` | `{"query": "geometry", "limit": 5}` | Ranked matches by tool name and description. |
| `tools_describe` | `{"name": "create_character_rig_pro"}` | Required arguments, defaults and the JSON Schema. |

Model dimensions and positions generally use meters. Fields ending in
`_mm` use millimeters, and `rotation_deg` and `rotation_degrees` use degrees.
The modeling convention is +Z up, -Y forward, with ground at Z=0.

## Build and inspect a desk

Call `run_workflow` to create a **1600 × 800 × 750 mm** desk and change its
width to **1200 mm**. The update uses the stored assembly and keeps the
original depth and height.

```json
{
  "steps": [
    {
      "tool": "create_assembly",
      "params": {
        "spec": {
          "name": "GuideDesk",
          "type": "desk",
          "dimensions_mm": {"width": 1600, "depth": 800, "height": 750}
        }
      }
    },
    {
      "tool": "update_assembly",
      "params": {
        "name": "GuideDesk",
        "changes": {"dimensions_mm": {"width": 1200}}
      }
    }
  ]
}
```

Check the `passed` flag and `audit` in each step's `result`. Call
`render_multiview_inspection` with the desk as the only model in the scene.
The result includes the quad PNG and camera metadata.

```json
{"mode": "quad", "resolution": 256, "include_overlays": true}
```

## Create and verify a character rig

Call `run_workflow` to create a **1.75 m** character base, bind it to a
**39-bone** armature and verify the mesh and vertex weights.

```json
{
  "steps": [
    {
      "tool": "create_character_body_pro",
      "params": {"name": "GuideBody", "height": 1.75, "build": "average", "subdivisions": 1}
    },
    {
      "tool": "create_character_rig_pro",
      "params": {"mesh_name": "GuideBody", "armature_name": "GuideRig"}
    },
    {
      "tool": "character_quality_report",
      "params": {"mesh_name": "GuideBody", "armature_name": "GuideRig"}
    }
  ]
}
```

Look for `bone_count: 39` in the rig result and `passed: true` in the
structural report. The report keeps `aaa_certified` set to `false` and lists
the missing production checks.

| v4.9 character tool | Output or check |
| --- | --- |
| `create_anatomical_head` | Procedural head mesh with anatomical landmarks. |
| `create_eye_assembly` | Sclera, iris, pupil, cornea and highlight layers. |
| `create_skin_material_pro` | Skin shader with subsurface scattering and procedural pores. |
| `create_dental_arch` | Upper and lower dental geometry with typed teeth. |
| `create_character_body_pro` | One connected body mesh with `slim`, `average` and `heavy` presets. |
| `create_garment_shell_pro` | A subdivided shirt, jacket or pants shell with trim. |
| `create_hair_groom` | Seeded hair strands as curves, with an optional head target. |
| `create_eyebrow_groom` | Paired curve eyebrows. |
| `create_eyelash_groom` | Paired curve eyelashes. |
| `create_character_rig_pro` | A 39-bone armature with automatic weights. |
| `create_character_studio` | A camera, backdrop and three-point lighting. |
| `character_quality_report` | Topology, material, UV and optional rig and groom checks. |

The [NEREID 07 scene](showcase/README.md#nereid-07) demonstrates a custom
35-bone rig built with `create_armature` for an articulated hard-shell suit.

## Validate and export a GLB

Call `run_workflow` in a fresh scene to create a part with a material and
check it against the Godot export profile.

```json
{
  "steps": [
    {
      "tool": "create_material",
      "params": {"name": "GuideTeal", "color": [0.02, 0.35, 0.32, 1], "metallic": 0.3}
    },
    {
      "tool": "create_parametric_part",
      "params": {
        "name": "GuideBlock",
        "shape": "BOX",
        "dimensions": [0.4, 0.3, 0.2],
        "material_name": "GuideTeal"
      }
    },
    {
      "tool": "export_preflight",
      "params": {"profile": "godot"}
    }
  ]
}
```

Check the preflight result's `passed` field before calling `export_scene`.

```json
{"filepath": "guide/guide-block.glb", "profile": "godot", "verify_reimport": true}
```

Inspect `validation` and `reimport` as well as the file path and size. The
path above is relative to `BLENDER_MCP_OUTPUT_DIR`, which defaults to
`~/BlenderMCP/output`.

| Export profile | Accepted formats | Default |
| --- | --- | --- |
| `godot` | GLB, glTF | GLB |
| `unity` | GLB, glTF | GLB |
| `unreal` | FBX | FBX |
| `generic-gltf` | GLB, glTF, OBJ | GLB |

## Batches and checkpoints

`run_workflow` executes commands sequentially in one Blender main-thread
request. `stop_on_error` defaults to `true` and stops later steps when a
handler raises an error. Earlier edits remain in the scene. Create a
checkpoint before batching edits to an existing project. Check each result's
validation fields before continuing to an export.
