# Domain pack contract — v4.4

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, deterministic seeds, Blender 4.5 and 5.2,
precise `ValueError` validation.

## pipeline.py

File paths in these functions are resolved by the add-on wrapper before the
call. Domain functions may read the given input path and write only to the
given output path/directory.

```python
def import_model(server, filepath, format="AUTO") -> dict

def export_selected(server, filepath, format="GLB") -> dict

def batch_export(server, object_names, directory, format="GLB") -> dict

def create_lod_chain(server, object_name, ratios=(1.0, 0.5, 0.25),
                     suffix="_LOD") -> dict

def validate_lod_chain(server, object_name, suffix="_LOD") -> dict

def pack_images(server) -> dict

def save_images(server, directory, format="PNG") -> dict

def generate_asset_manifest(server, object_names, filepath) -> dict
```

## render_qa.py

```python
def configure_render(server, engine="BLENDER_EEVEE_NEXT", samples=32,
                     resolution_x=960, resolution_y=540,
                     film_transparent=False, fps=24) -> dict

def enable_render_pass(server, pass_name="AO", enabled=True) -> dict

def render_turntable(server, directory, frames=12, resolution_x=256,
                     resolution_y=256, samples=8) -> dict

def render_contact_sheet(server, image_paths, filepath,
                         columns=4) -> dict

def create_studio_backdrop(server, name="Backdrop", width=6.0, depth=4.0,
                           height=3.0,
                           color=(0.5, 0.5, 0.5, 1.0)) -> dict

def setup_compositor_glare(server, threshold=1.0, size=6,
                           mix=0.0) -> dict

def validate_render(server, filepath, min_width=1,
                    min_height=1) -> dict

def compare_renders(server, image_a, image_b) -> dict
```

## rigging.py

```python
def list_bones(server, armature_name) -> dict

def create_bone(server, armature_name, bone_name, head, tail,
                parent=None, connected=False) -> dict

def create_ik_chain(server, armature_name, base_bone, target_name,
                    chain_count=2, pole_target=None) -> dict

def add_copy_rotation_constraint(server, armature_name, bone_name,
                                 target_name, influence=1.0) -> dict

def add_limit_rotation_constraint(server, armature_name, bone_name,
                                  axes=("X", "Y", "Z"),
                                  limits=(-90.0, 90.0)) -> dict

def set_bone_rotation(server, armature_name, bone_name,
                      rotation_degrees) -> dict

def set_bone_location(server, armature_name, bone_name,
                      location) -> dict

def skin_mesh_to_armature(server, mesh_name, armature_name,
                          automatic=True) -> dict
```

## textures.py

```python
def create_image(server, name="Texture", width=256, height=256,
                 color=(0.0, 0.0, 0.0, 1.0), checker=False) -> dict

def create_checker_texture(server, name="Checker", width=256, height=256,
                           color_a=(0.1, 0.1, 0.1, 1.0),
                           color_b=(0.9, 0.9, 0.9, 1.0),
                           cells=8) -> dict

def add_image_texture_node(server, material_name, image_name,
                           mapping="UV", scale=1.0) -> dict

def resize_image(server, image_name, width, height) -> dict

def set_image_colorspace(server, image_name,
                         colorspace="sRGB") -> dict

def pack_image(server, image_name) -> dict

def save_image(server, image_name, filepath, format="PNG") -> dict

def image_to_material(server, image_name, material_name,
                      roughness=0.5) -> dict
```
