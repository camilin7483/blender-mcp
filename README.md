# Blender MCP Pro

[![CI on main](https://github.com/camilin7483/blender-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/camilin7483/blender-mcp/actions/workflows/ci.yml)
[![Latest Pro prerelease](https://img.shields.io/badge/Pro-v4.9.0--alpha.2-176a70)](https://github.com/camilin7483/blender-mcp/releases/tag/v4.9.0-alpha.2)

Blender MCP Pro connects an MCP client to Blender for modeling, rigging,
scene inspection, rendering, and export. The standard `full` profile exposes
**313 tools**. The bridge uses MCP over stdio and forwards requests to the
authenticated Blender add-on on `localhost:9876`.

## Showcase

**PELAGOS 07** is an original subsea inspection vehicle with a ceramic pressure
hull, ducted thrusters and an optical sensor assembly.

[![PELAGOS 07 inspection vehicle rendered in Blender](docs/showcase/pelagos-07.webp)](docs/showcase/README.md#pelagos-07)

**NEREID 07** is its humanoid survey pilot. Its 35-bone rig articulates the
segmented pressure suit, including the hands and fingers.

<a href="docs/showcase/README.md#nereid-07"><img src="docs/showcase/nereid-07.webp" alt="Full-body Blender render of the NEREID 07 humanoid survey pilot" width="460"></a>

Both images were rendered with Cycles in Blender's background mode. The
[showcase guide](docs/showcase/README.md) includes the editable `.blend` files,
detail renders, measured checks, and commands to regenerate the scenes.

## Installation

1. Download [`blender_mcp_pro-4.9.0.zip` from v4.9.0-alpha.2](https://github.com/camilin7483/blender-mcp/releases/download/v4.9.0-alpha.2/blender_mcp_pro-4.9.0.zip).
2. In Blender, open **Edit → Preferences → Get Extensions**. Use the top-right
   menu to select **Install from Disk**, then select the ZIP. Enable **Blender
   MCP Pro Engine** if prompted.
3. Open the 3D Viewport sidebar with **N** and select **MCP Pro** to see the
   connection status. If needed, click **Start Server**.
4. Set up the MCP bridge in its own Python 3.10+ environment. Use the source
   matching your installation. For the published ZIP:

   ```bash
   git clone --branch v4.9.0-alpha.2 https://github.com/camilin7483/blender-mcp.git
   cd blender-mcp
   python3 -m venv .venv
   .venv/bin/python -m pip install .
   ```

5. Configure the MCP client to launch the bridge by its absolute path. On
   Windows, use `.venv\Scripts\blender-mcp.exe`.

   ```json
   {
     "mcpServers": {
       "blender-mcp-pro": {
         "command": "/absolute/path/to/blender-mcp/.venv/bin/blender-mcp"
       }
     }
   }
   ```

Ask the client to run `get_scene_info` to verify the connection.
[Configuration details](pro/README.md#local-configuration) cover the auth token,
profiles and output directory. The [v3 migration guide](docs/migration-v3-v4.md)
covers the single-file legacy add-on in [`legacy/`](legacy/). Both editions use
the same local port, so enable one at a time.

## Workflows

| Workflow | Capabilities |
| --- | --- |
| Precision modeling | Parametric solids, metric assemblies, evaluated topology, BVH overlap, and spatial constraints |
| Characters | Anatomy and garment tools, procedural grooming, rig binding, posing, and character quality reports |
| Scene production | Architecture, terrain, procedural materials, UVs, lighting, cameras, and physics |
| Inspection | Orthographic and isometric views, silhouettes, wireframes, normals, and UV checker renders |
| Game export | Godot, Unity, Unreal, and generic glTF profiles with validation and reimport checks |
| Discovery | `tools_catalog`, `tools_search`, `tools_describe`, and bounded batches via `run_workflow` |

Set `BLENDER_MCP_PROFILE` in the bridge process to `nano`, `guided`, `core`,
`modeling`, `materials`, `animation`, `rigging`, `geometry_nodes`,
`inspection`, `export`, `assets`, or `full`.

## Compatibility and verification

Linux CI runs Blender **4.5.4 LTS** and **5.2.4 LTS** with the real headless
geometry and GUI socket suites, the 46-task functional benchmark, and extension
package validation. Windows and macOS have Python and experimental headless
Blender lanes. See the [platform matrix](docs/compatibility.md) for each lane's
coverage.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt -r pro/requirements.txt
.venv/bin/python -m pytest tests/contracts tests/unit tests/integration -q
BLENDER_BIN=/path/to/blender ./scripts/run_blender_tests.sh
BLENDER_BIN=/path/to/blender ./scripts/run_bench.sh --runs 3 --output out/bench
```

The GUI socket suite uses the Blender event loop. On Linux without a display,
the test script uses `xvfb-run`. The showcase generators run in background mode
and call the modeling code on Blender's main thread.

## Documentation

- [Pro setup and configuration](pro/README.md)
- [Architecture](ARCHITECTURE.md)
- [Benchmarks and reproduction](bench/README.md)
- [Release evidence and checklist](docs/release-checklist.md)
- [v4.9.0-alpha.2 release notes](docs/releases/v4.9.0-alpha.2.md)
- [Changelog](CHANGELOG.md)

## Security

The add-on requires a local auth token by default. `execute_code` requires
explicit opt-in in Blender. See the [threat model and security policy](SECURITY.md).

## Contributing

Use the host and Blender test commands above to verify changes. See the
[contribution guide](CONTRIBUTING.md) for repository conventions.

## Credits

Original code by [Siddharth Ahuja](https://github.com/ahujasid). Repository
maintained by **CamiloDev**. Optional asset integrations include Poly Haven,
Sketchfab, Rodin, and Replicate.

## License

[MIT](LICENSE)
