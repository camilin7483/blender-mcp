# Blender MCP Pro v4.0.0-alpha.2

Blender MCP Pro connects an MCP client to Blender for metric 3D modeling, scene inspection, and export. The `mcp_server.py` bridge exposes 60 tools over MCP stdio. Set
`BLENDER_MCP_PROFILE` to `core`, `modeling`, `materials`, `animation`,
`rigging`, `geometry_nodes`, `inspection`, `export`, `assets` or `full`. It sends JSON commands to the Blender add-on on `localhost:9876`, where they run on Blender’s main thread.

## What’s new

| Workflow | Pro tools |
| --- | --- |
| Precision assembly | Metric blueprints, parametric parts, semantic anchors, surface placement, and symmetry |
| Modeling and rigging | Revolved profiles, curve sweeps, lofts, deformation, mesh fusion, and humanoid auto-rigging |
| Architecture | Floorplan walls, fitted openings, roofs, stairs, building shells, and façade arrays |
| Inspection and recovery | Requirements-first audit, evaluated geometry, contact graph, topology, semantic anchors, deterministic multi-view renders, mesh repair, and scene checkpoints |
| Materials, assets, and export | Procedural materials, Poly Haven search and import, Sketchfab search and download, collision hulls, and game-profile export (`godot`, `unity`, `unreal`, `generic-gltf`) with validation and reimport |
| Network visualization | Build a 3D room with devices and cables from Packet Tracer TopologyPlan JSON |

See the [changelog](CHANGELOG.md) and [Precision 3D Modeling Protocol](MODELING_SYSTEM_PROMPT.md) for the modeling workflow and migration details.

## Set up Pro

Use Blender 4.5 LTS and a separate Python 3.10+ environment for the MCP bridge. The integration was tested with Blender 4.5.4 LTS and `mcp` 1.30.0.

1. Disable the legacy Blender MCP add-on if it is active. Both editions use the same local port and Blender operator names.
2. In Blender, open **Edit → Preferences → Add-ons → Install from Disk** and select `pro/blender_mcp.py` from the repository. Enable **Blender MCP Pro Engine** to start its local server. Open the **MCP Pro** tab in the 3D Viewport sidebar (`N`) for the server controls. [Blender add-on installation guide](https://docs.blender.org/manual/en/4.5/editors/preferences/addons.html)
3. Install the Python dependency from the repository’s `pro/` directory.

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install "mcp==1.30.0"
   ```

4. Configure your MCP client to launch `mcp_server.py` over stdio using the virtual environment’s Python. Replace the example paths with the actual absolute paths. On Windows, use `.venv\Scripts\python.exe` for the executable.

   ```json
   {
     "mcpServers": {
       "blender-mcp-pro": {
         "command": "/absolute/path/to/blender-mcp/pro/.venv/bin/python",
         "args": ["/absolute/path/to/blender-mcp/pro/mcp_server.py"]
       }
     }
   }
   ```

   Clients with their own configuration use the same executable and argument. [OpenCode local MCP setup](https://opencode.ai/docs/mcp-servers/)

5. Ask the client to inspect the active scene with `get_scene_info`. Then try a work request such as “Build a table from the metric blueprint, check its ground contact, and show the four inspection views.”

## Example inspection

This table was built with the metric `table` blueprint and passed `audit_3d_model` with a score of 100. The image is the PNG returned by `render_multiview_inspection`.

![Front, right, top, and isometric views of a parametric table](docs/table-inspection.png)

## Local configuration

| Environment variable | Where to set it | Purpose |
| --- | --- | --- |
| `BLENDER_MCP_TOKEN_FILE` | Blender and the MCP bridge | Override the token file path. Default: `$XDG_CONFIG_HOME/blender-mcp/token` (Linux/macOS) or `%APPDATA%\blender-mcp\token` (Windows). |
| `BLENDER_AUTH_TOKEN` | Blender and the MCP bridge | Override the token value. Supply the same value to both processes. |
| `BLENDER_MCP_ALLOW_NO_AUTH` | Blender and the MCP bridge | Unsafe: disable local authentication. Use only for a trusted local process that cannot read the token file. |
| `BLENDER_MCP_ALLOW_EXECUTE_CODE` | Blender | Enable `execute_code`. Prefer the add-on preference; this variable is for automation. |
| `BLENDER_MCP_ALLOW_UNSAFE_OPS` | Blender | Skip the dry-run for `clear_scene`, `delete_object`, `rollback_checkpoint` and `setup_studio_lighting`. Unsafe; use only for trusted automation. |
| `BLENDER_MCP_OUTPUT_DIR` | Blender | Export sandbox. Default: `~/BlenderMCP/output`. Relative export paths resolve here; absolute paths must stay inside. |
| `BLENDER_MCP_ALLOW_ANY_PATH` | Blender | Disable the export sandbox. Unsafe; use only for trusted automation. |
| `BLENDER_HOST`, `BLENDER_PORT` | MCP bridge | Socket destination. The add-on listens on `localhost:9876` in a standard installation. |
| `SKETCHFAB_API_TOKEN` | Blender | Required by the Sketchfab download tool. |

Authentication is required by default. The add-on creates the token file with mode 0600 on first start. `execute_code` is disabled until you enable it explicitly. Keep the Blender socket on loopback and grant access only to trusted clients. The tools can modify the active scene, write files, and execute Python inside Blender.

## License and credits

See the [repository license](../LICENSE) and [project credits](../README.md#credits).
