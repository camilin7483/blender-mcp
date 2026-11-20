# Domain pack contract — v4.6

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, deterministic seeds, Blender 4.5 and 5.2,
precise `ValueError` validation.

## materials_advanced.py

```python
def bake_ambient_occlusion(server, object_name, image_size=512,
                           samples=16) -> dict

def bake_normal_map(server, object_name, image_size=512) -> dict

def bake_diffuse(server, object_name, image_size=512) -> dict

def create_udim_tiles(server, name="UDIM", tiles=(1001, 1002),
                      size=1024) -> dict

def add_displacement(server, material_name, scale=0.1,
                     midlevel=0.5) -> dict

def create_layer_weight_mix(server, name="LayerMix",
                            color_a=(0.1, 0.2, 0.4, 1.0),
                            color_b=(0.8, 0.6, 0.3, 1.0)) -> dict

def create_parallax_bump(server, material_name, scale=0.05) -> dict

def optimize_material(server, material_name) -> dict
```

## nature_extra.py

```python
def create_forest(server, name="Forest", radius=10.0, tree_count=12,
                  seed=0) -> dict

def create_grass_field(server, name="GrassField", size=10.0,
                       blade_count=100, seed=0) -> dict

def create_rock_cluster(server, name="Rocks", radius=3.0, count=8,
                        seed=0) -> dict

def create_mountain_range(server, name="Mountains", width=40.0,
                          depth=20.0, peak_height=8.0, seed=0) -> dict

def create_cave(server, name="Cave", width=6.0, depth=4.0,
                height=3.0, seed=0) -> dict

def create_island(server, name="Island", radius=8.0, seed=0) -> dict

def create_waterfall(server, name="Waterfall", width=2.0,
                     height=4.0) -> dict

def create_biome(server, name="Biome", size=20.0, seed=0) -> dict
```

## architecture_extra.py

```python
def create_bathroom_set(server, name="Bathroom", width=2.4,
                        depth=2.0) -> dict

def create_kitchen_island(server, name="KitchenIsland", width=2.0,
                          depth=1.0, height=0.9) -> dict

def create_fireplace(server, name="Fireplace", width=1.6,
                     height=1.2, depth=0.4) -> dict

def create_balcony(server, name="Balcony", width=3.0, depth=1.2,
                   height=1.0) -> dict

def create_fence(server, name="Fence", length=6.0, height=1.2,
                 post_count=8) -> dict

def create_gate(server, name="Gate", width=3.0, height=2.0) -> dict

def create_garage(server, name="Garage", width=6.0, depth=6.0,
                  height=2.8) -> dict

def create_pool(server, name="Pool", width=6.0, depth=3.0,
                water_depth=1.2) -> dict
```

## rigging_advanced.py

```python
def add_child_of_constraint(server, armature_name, bone_name,
                            target_name, influence=1.0) -> dict

def add_copy_location_constraint(server, armature_name, bone_name,
                                 target_name, influence=1.0) -> dict

def add_damped_track_constraint(server, armature_name, bone_name,
                                target_name, track_axis="TRACK_Y",
                                influence=1.0) -> dict

def add_stretch_to_constraint(server, armature_name, bone_name,
                              target_name, rest_length=0.0,
                              influence=1.0) -> dict

def set_bone_custom_shape(server, armature_name, bone_name,
                          object_name) -> dict

def create_pose_library_action(server, armature_name,
                               action_name="Pose") -> dict

def mirror_pose(server, armature_name, axis="X") -> dict

def validate_rig(server, armature_name, mesh_name=None) -> dict
```
