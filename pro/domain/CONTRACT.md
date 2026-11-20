# Domain pack contract

Modules in this directory are loaded by `pro/blender_mcp.py` at import time
through `importlib`. They run on Blender's main thread. Do not import
`blender_mcp` from a domain module; the add-on instance is passed as `server`.

## Rules

- Implement every function fully. No placeholders, no `pass`, no TODO stubs.
- Validate inputs and raise `ValueError` with a precise message.
- Return plain JSON-serializable dictionaries. Include `success`, the created
  object names, dimensions and useful metadata.
- Deterministic when `seed` is provided.
- Compatible with Blender 4.5 LTS and 5.2 LTS.
- Use meters and degrees in public parameters.
- Do not write files. The add-on wrapper resolves output paths.
- Use `bpy`, `bmesh`, `mathutils` and standard library only.

## terrain.py

```python
def create_terrain(server, name="Terrain", size=10.0, subdivisions=64,
                   height=1.0, noise_scale=2.0, seed=0, style="mountains") -> dict

def sculpt_terrain_region(server, object_name, center=(0.0, 0.0, 0.0),
                          radius=1.0, strength=0.5, direction="UP") -> dict

def scatter_objects(server, source_name, target_name, count=50, seed=0,
                    scale_min=0.8, scale_max=1.2, align_to_normal=True) -> dict

def create_rock(server, name="Rock", size=1.0, roughness=0.35, seed=0,
                subdivisions=2) -> dict
```

## vegetation.py

```python
def create_tree(server, name="Tree", height=4.0, trunk_radius=0.15,
                crown_radius=1.5, tree_type="deciduous", seed=0) -> dict

def create_bush(server, name="Bush", radius=0.8, height=0.6, seed=0) -> dict

def create_grass_patch(server, name="GrassPatch", radius=1.0, blade_count=100,
                       blade_height=0.15, seed=0) -> dict

def create_flower_patch(server, name="Flowers", radius=1.0, count=20,
                        seed=0) -> dict
```

## water.py

```python
def create_water_plane(server, name="Water", size=10.0, subdivisions=64,
                       wave_height=0.08, wave_scale=1.5,
                       color=(0.05, 0.25, 0.35, 1.0), roughness=0.15) -> dict

def create_river(server, name="River", points=None, width=2.0, depth=0.2,
                 segments=32) -> dict

def create_pond(server, name="Pond", radius=3.0, depth=0.4, segments=48) -> dict

def create_water_material(server, name="WaterMaterial",
                          color=(0.05, 0.25, 0.35, 1.0), roughness=0.1,
                          transmission=0.6, wave_scale=1.5) -> dict
```

## materials_uv.py

```python
def create_procedural_material(server, name="Procedural",
                               base_color=(0.6, 0.6, 0.6, 1.0), roughness=0.5,
                               metallic=0.0, noise_scale=5.0,
                               bump_strength=0.2, color_variation=0.1) -> dict

def smart_uv_unwrap(server, object_name, angle_limit=66.0,
                    island_margin=0.02) -> dict

def pack_uv_islands(server, object_name, margin=0.001) -> dict

def list_materials(server, used_only=False) -> dict
```

## lighting.py

```python
def create_light(server, name="Light", light_type="POINT", energy=100.0,
                 color=(1.0, 1.0, 1.0), location=(0.0, 0.0, 3.0),
                 rotation=(0.0, 0.0, 0.0), size=0.1,
                 spot_size=45.0) -> dict

def create_camera(server, name="Camera", location=(7.0, -7.0, 5.0),
                  look_at=(0.0, 0.0, 1.0), lens=50.0, ortho_scale=6.0,
                  camera_type="PERSP") -> dict

def setup_world_background(server, color=(0.05, 0.05, 0.05),
                           strength=1.0) -> dict

def render_still(server, filepath, camera_name=None, resolution_x=960,
                 resolution_y=540, samples=32,
                 engine="BLENDER_EEVEE_NEXT", transparent=False) -> dict
```

`filepath` is already resolved and safe when called by the add-on wrapper.
The function must still reject an empty path and create parent directories.

## physics.py

```python
def add_rigid_body(server, object_name, body_type="ACTIVE", mass=1.0,
                   friction=0.5, restitution=0.0) -> dict

def add_collision(server, object_name, shape="CONVEX_HULL",
                  margin=0.04) -> dict

def add_cloth(server, object_name, quality=5, mass=0.3, tension=15.0,
              bending=0.5) -> dict

def bake_simulation(server, frame_start=1, frame_end=250) -> dict
```
