# Blender MCP

**Blender MCP** is a Blender add-on that enables AI-powered 3D content creation through the **Model Context Protocol (MCP)**. It connects Blender to AI coding assistants like Claude, OpenCode, Cursor, and other MCP-compatible tools, allowing you to control Blender using natural language.

## Editions

- **Legacy** — `blender_mcp.py` at the repository root. Original single-file add-on.
- **Pro v4 (pre-release)** — [`pro/`](pro/README.md). 58-tool FastMCP bridge plus the precision geometry engine. Both editions use `localhost:9876`; enable only one at a time.

## Status

The `v3.0.0-baseline` tag is a development baseline, not a hardened release.
The tagged baseline had optional authentication. This branch adds a
per-install token file (0600), routes commands through a main-thread queue,
disables `execute_code` by default and audits evaluated geometry with a
requirements-first contract. Collision claims now come from BVH intersection;
AABB is broad-phase only. Inspection renders use documented orthographic
cameras for FRONT/RIGHT/TOP, a fixed ISO perspective camera, reproducible
output paths and camera metadata. Tested with Blender 4.5.4 and 5.2.4 LTS.
See [`SECURITY.md`](SECURITY.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Security and threat model](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Compatibility](docs/compatibility.md)
- [Migration v3 -> v4](docs/migration-v3-v4.md)
- [Benchmark methodology and results](bench/README.md)
- [Release checklist](docs/release-checklist.md)
- [Changelog](CHANGELOG.md)

## Features



- **Natural Language Control** — Create, modify, and manipulate 3D scenes using plain English
- **Socket Server** — Runs a local server inside Blender (port 9876) that listens for JSON commands
- **Full Blender API Access** — Create objects, materials, cameras, lights, animations, and more
- **Poly Haven Integration** — Download free HDRI, texture, and 3D model assets directly into your scene
- **AI-Powered Generation** — Text-to-3D via Rodin API, texture generation via Replicate
- **Deterministic inspection** — Orthographic FRONT/RIGHT/TOP plus ISO,
  silhouette, wireframe, normals and UV checker modes, with camera metadata
  and a reproducible output hash.
- **Game-ready export** — `godot`, `unity`, `unreal` and `generic-gltf`
  profiles validate scale, materials, UVs, armatures, actions, LOD and
  collision meshes, then reimport the file and compare dimensions.
- **Constraint validation** — Read-only checks for mate, align, flush,
  center, offset, distance, parallel, perpendicular, ground contact,
  symmetry, no-intersection, inside and surface contact, with structured
  expected/actual/tolerance/method results.
- **Declarative assemblies** — `create_assembly` builds a desk from
  `dimensions_mm` or any explicit component list; `update_assembly` merges a
  patch and rebuilds without duplicating objects.
- **MCP Compatible** — Works with Claude, OpenCode, Cursor, and any MCP-compatible assistant

## Tool profiles

Set `BLENDER_MCP_PROFILE` before starting the bridge to reduce the visible
tool surface. Profiles are `core` (13 tools), `modeling`, `materials`,
`animation`, `rigging`, `geometry_nodes`, `inspection`, `export`, `assets`
and `full` (default, 58 tools). `execute_code` is full-only and remains
disabled in the add-on by default. Unknown profile names fail open to
`full`. Profiles filter bridge registration only; the add-on keeps every
handler.

## How It Works

```
+-------------------+      JSON Commands      +---------------------+
|  AI Assistant     | ----------------------> |  Blender Add-On     |
|  (Claude/Code)    |                         |  (this add-on)      |
|                   | <---------------------- |                     |
|  MCP Client       |      JSON Responses     |  Socket Server      |
+-------------------+                         |  localhost:9876     |
                                              +---------------------+
```

The add-on starts a **socket server** inside Blender on `localhost:9876`. When an AI assistant sends a command, the server executes it using Blender's Python API (`bpy`) and returns the result.

## Installation

### Prerequisites

- **Blender 3.0+** (tested up to 4.5)
- **Python 3.10+** (comes bundled with Blender)

### Install the Add-on

1. Open **Blender**
2. Go to **Edit > Preferences > Add-ons**
3. Click **Install from Disk...**
4. Navigate to and select `blender_mcp.py`
5. **Enable** the add-on by checking the checkbox next to "Interface: Blender MCP"
6. Find the panel in **View3D > Sidebar > BlenderMCP** tab

## Usage

### Starting the Server

1. Open Blender
2. Go to **View3D > Sidebar > BlenderMCP**
3. Click **Start Server** (or **Connect**)
4. The server will start listening on `localhost:9876`

### Example Commands

Once the server is running and connected to your AI assistant, you can ask things like:

- "Create a red sphere at position (0, 0, 0)"
- "Add a camera pointing at the origin"
- "Import an HDRI from Poly Haven"
- "Create an animation of a rotating cube"
- "Apply a metallic material to the selected object"

## Technical Architecture

### Server (BlenderMCPServer)

The core of the add-on is the `BlenderMCPServer` class which:

1. Opens a **TCP socket** on `localhost:9876`
2. Listens for **JSON-encoded commands** in a background thread
3. Routes each command to the appropriate **handler function**
4. Returns **JSON responses** with results or error messages

### Available Endpoints

| Category | Commands |
|----------|----------|
| **Objects** | create_object, select_object, delete_object, duplicate_object, transform_object, rename_object, get_object_info, list_objects |
| **Materials** | create_material, assign_material, set_material_property, get_material_info, list_materials |
| **Scene** | get_scene_info, set_scene_property, render_scene, clear_scene |
| **Camera** | add_camera, set_active_camera, frame_object |
| **Lights** | add_light, set_light_property, list_lights |
| **Animation** | set_keyframe, add_rotation_animation, add_movement_animation, add_scale_animation |
| **Poly Haven** | search_polyhaven, download_asset, import_asset |
| **AI** | generate_3d_text (Rodin API), generate_texture (Replicate API) |
| **System** | exec_code (raw bpy execution), get_addon_info, export_scene |

## Poly Haven Integration

The add-on can search and download free assets from [Poly Haven](https://polyhaven.com/):

- **HDRI** environments for realistic lighting
- **Textures** (albedo, roughness, normal maps, etc.)
- **3D Models** (HDRIs, textures, and models)

Use the `search_polyhaven` command with parameters like `type: hdri`, `type: texture`, or `type: model`.

## AI Features

### Rodin Text-to-3D (Free Trial)

- Uses the Rodin API with free trial key
- Generate 3D models from text descriptions
- Imports generated models directly into the scene

### Replicate Texture Generation

- Generate textures using AI models via Replicate API
- Requires a Replicate API token configured in preferences

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt -r pro/requirements.txt
.venv/bin/python -m pytest tests/contracts tests/unit tests/integration -q
BLENDER_BIN=/path/to/blender-4.5.4-linux-x64/blender ./scripts/run_blender_tests.sh
```

The Pro tests need a real Blender 4.5 LTS with its event loop. On Linux
without `DISPLAY`, the script uses `xvfb-run`; `blender --background` does not
pump timers. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Credits


Original code by **Siddharth Ahuja** (github.com/ahujasid)
Repository maintained by **CamiloDev**

- Poly Haven integration uses the Poly Haven API
- Rodin AI integration for text-to-3D generation
- Replicate integration for AI texture generation

## License

MIT - See LICENSE for details.
