# Decisions

## D-001 Domain packs load dynamically

The add-on stays a single legacy entry point. New domain tools live in
`pro/domain/` and are loaded through `importlib` from the add-on directory.
This keeps Blender add-on compatibility while allowing independent modules.

## D-002 Tool count means implemented tools

Aliases, wrappers and empty placeholders do not count. The catalog is generated
from the real FastMCP registry and the add-on command table must match 1:1.

## D-003 No external API dependency

Terrain, vegetation, water, materials, lighting and physics are local Blender
operations. Paid services remain optional and disabled by default.
