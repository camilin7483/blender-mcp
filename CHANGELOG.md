# Blender MCP Pro changelog

## [3.0.0] - 2026-11-18

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

### Upgrade

- Install `blender_mcp_pro.py` and point the MCP client to `mcp_server.py` in the extracted release. The Pro bridge has its own command schema.
