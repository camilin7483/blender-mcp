"""Domain tool packs loaded by the Blender add-on."""

from . import (
    animation,
    architecture_furniture,
    architecture_shell,
    character,
    environment,
    hardsurface_modifiers,
    hardsurface_primitives,
    lighting,
    materials_pbr,
    materials_uv,
    physics,
    pipeline,
    render_qa,
    rigging,
    terrain,
    textures,
    vegetation,
    water,
)

PACKS = {
    "terrain": terrain,
    "vegetation": vegetation,
    "water": water,
    "materials_uv": materials_uv,
    "materials_pbr": materials_pbr,
    "lighting": lighting,
    "physics": physics,
    "architecture_shell": architecture_shell,
    "architecture_furniture": architecture_furniture,
    "hardsurface_modifiers": hardsurface_modifiers,
    "hardsurface_primitives": hardsurface_primitives,
    "environment": environment,
    "character": character,
    "animation": animation,
    "pipeline": pipeline,
    "render_qa": render_qa,
    "rigging": rigging,
    "textures": textures,
}

__all__ = ["PACKS", *PACKS.keys()]
