"""Domain tool packs loaded by the Blender add-on."""

from . import lighting, materials_uv, physics, terrain, vegetation, water

PACKS = {
    "terrain": terrain,
    "vegetation": vegetation,
    "water": water,
    "materials_uv": materials_uv,
    "lighting": lighting,
    "physics": physics,
}

__all__ = ["PACKS", *PACKS.keys()]
