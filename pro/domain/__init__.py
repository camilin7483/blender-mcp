"""Domain tool packs loaded by the Blender add-on."""

from . import (
    architecture_furniture,
    architecture_shell,
    hardsurface_modifiers,
    hardsurface_primitives,
    lighting,
    materials_uv,
    physics,
    terrain,
    vegetation,
    water,
)

PACKS = {
    "terrain": terrain,
    "vegetation": vegetation,
    "water": water,
    "materials_uv": materials_uv,
    "lighting": lighting,
    "physics": physics,
    "architecture_shell": architecture_shell,
    "architecture_furniture": architecture_furniture,
    "hardsurface_modifiers": hardsurface_modifiers,
    "hardsurface_primitives": hardsurface_primitives,
}

__all__ = ["PACKS", *PACKS.keys()]
