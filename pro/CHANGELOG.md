# Blender MCP Pro changelog

## 3.0.0

### Added

- A FastMCP stdio bridge with 53 tools and a Blender add-on that schedules socket commands on Blender’s main thread.
- Metric blueprints, parametric parts, semantic snapping, and surface alignment for assembling models from evaluated geometry.
- Revolved profiles, curve sweeps, lofts, deformation, organic mesh fusion, humanoid rigging, and architectural generators.
- Geometry audits for ground alignment, floating parts, and overlaps, with mesh repair, scene checkpoints, and four-view inspection renders.
- Procedural materials, game asset preparation with optional convex collision hulls, and scene export in GLB, glTF, FBX, or OBJ.
- A 3D network room generator for Packet Tracer TopologyPlan JSON.

### Fixed

- Removed six duplicate MCP tool registrations, clearing the startup warnings while preserving each tool’s name, parameters, and behavior.
- The sidebar now shows the live server status after automatic startup. The Start button can retry after a port conflict.

### Migration from the legacy add-on

- Pro is installed separately and uses the **MCP Pro** sidebar. Disable the legacy add-on before enabling Pro, and point your MCP client at `pro/mcp_server.py`. Existing legacy clients can continue using the original add-on at the repository root.
- Pro uses a different command schema and optional shared-token configuration. Existing direct socket clients should stay on the legacy add-on until adapted to the Pro protocol.
- Rodin/Hyper3D, Hunyuan3D, and the legacy viewport screenshot command remain available in the original add-on. Pro includes Poly Haven and Sketchfab asset tools and a four-view inspection workflow.
