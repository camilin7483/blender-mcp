# Blender MCP Pro

Blender MCP Pro connects an MCP client to Blender for metric 3D modeling, scene inspection, and export. The `mcp_server.py` bridge exposes 53 tools over MCP stdio. It sends JSON commands to the Blender add-on on `localhost:9876`, where they run on Blender’s main thread.

[**Download Blender MCP Pro v3.0.0**](https://github.com/camilin7483/blender-mcp/releases/latest)

![Front, right, top, and isometric views of a parametric table made with Blender MCP Pro](docs/table-inspection.png)

## What’s new

| Workflow | Pro tools |
| --- | --- |
| Precision assembly | Metric blueprints, parametric parts, semantic anchors, surface placement, and symmetry |
| Modeling and rigging | Revolved profiles, curve sweeps, lofts, deformation, mesh fusion, and humanoid auto-rigging |
| Architecture | Floorplan walls, fitted openings, roofs, stairs, building shells, and façade arrays |
| Inspection and recovery | Grounding, contact and overlap audits, mesh repair, four-angle renders, and scene checkpoints |
| Materials, assets, and export | Procedural materials, Poly Haven search and import, Sketchfab search and download, collision hulls, and GLB, glTF, FBX, or OBJ export |
| Network visualization | Build a 3D room with devices and cables from Packet Tracer TopologyPlan JSON |

See the [changelog](CHANGELOG.md) and [Precision 3D Modeling Protocol](MODELING_SYSTEM_PROMPT.md) for the modeling workflow and migration details.

## Set up Pro

Use Blender 4.5 LTS and a separate Python 3.10+ environment for the MCP bridge. The integration was tested with Blender 4.5.4 LTS and `mcp` 1.30.0.

1. Download and extract `Blender-MCP-Pro-3.0.0.zip` from the [release page](https://github.com/camilin7483/blender-mcp/releases/tag/v3.0.0). If you have the original Blender MCP add-on installed, disable it before enabling Pro.
2. In Blender, open **Edit → Preferences → Add-ons → Install from Disk** and select `blender_mcp_pro.py` from the extracted folder. Enable **Blender MCP Pro Engine** and find the controls in **3D Viewport → Sidebar → MCP Pro**. [Blender add-on installation guide](https://docs.blender.org/manual/en/4.5/editors/preferences/addons.html)
3. Open a terminal in the extracted folder or the repository root and install the MCP bridge dependency.

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install "mcp==1.30.0"
   ```

4. Configure your MCP client to launch `mcp_server.py` over stdio using the virtual environment’s Python. Replace the example paths with the actual absolute paths. On Windows, use `.venv\Scripts\python.exe` for the executable.

   ```json
   {
     "mcpServers": {
       "blender-mcp-pro": {
         "command": "/absolute/path/to/blender-mcp-pro-3.0.0/.venv/bin/python",
         "args": ["/absolute/path/to/blender-mcp-pro-3.0.0/mcp_server.py"]
       }
     }
   }
   ```

   Clients with their own configuration use the same executable and argument. [OpenCode local MCP setup](https://opencode.ai/docs/mcp-servers/)

5. Ask the client to inspect the active scene with `get_scene_info`. Then try a work request such as “Build a table from the metric blueprint, check its ground contact, and show the four inspection views.”

## Verification

The featured table was generated from a metric blueprint and scored 100 in the geometry audit. The Linux smoke test also covered startup and port-conflict recovery, the 53-tool catalog, a four-view render, GLB export, checkpoint restoration, and invalid-token rejection. Windows, macOS, external asset downloads, and the other export formats still need verification.

## Local configuration

| Environment variable | Where to set it | Purpose |
| --- | --- | --- |
| `BLENDER_AUTH_TOKEN` | Blender and the MCP bridge | Optional shared token. Supply the same value to both processes. |
| `BLENDER_HOST`, `BLENDER_PORT` | MCP bridge | Socket destination. The add-on listens on `localhost:9876` in a standard installation. |
| `SKETCHFAB_API_TOKEN` | Blender | Required by the Sketchfab download tool. |

Keep the Blender socket on loopback and grant access only to trusted clients. The tools can modify the active scene, write files, and execute Python inside Blender.

## Credits

Original code by **Siddharth Ahuja**. Repository maintained by **CamiloDev**. [Original Blender MCP project](https://github.com/ahujasid/blender-mcp)

## License

[MIT](LICENSE).
