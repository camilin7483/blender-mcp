# Domain pack contract — v4.3

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, no file writes, deterministic seeds,
Blender 4.5 and 5.2, precise `ValueError` validation.

## environment.py

```python
def create_sky_lighting(server, name="Sky", sun_elevation=45.0,
                        sun_rotation=135.0, sun_energy=3.0,
                        sky_strength=1.0) -> dict

def create_fog_volume(server, name="Fog", size=20.0, density=0.02,
                      color=(0.8, 0.85, 0.9),
                      location=(0.0, 0.0, 0.0)) -> dict

def create_cloud_layer(server, name="Clouds", size=20.0, altitude=10.0,
                       density=1.0, seed=0) -> dict

def create_ground(server, name="Ground", size=20.0, subdivisions=16,
                  style="grass", seed=0) -> dict

def create_cliff(server, name="Cliff", width=5.0, height=3.0, depth=2.0,
                 seed=0, subdivisions=24) -> dict

def create_beach(server, name="Beach", width=20.0, depth=10.0,
                 slope=0.08, seed=0) -> dict

def create_biome_scatter(server, target_name, tree_name, bush_name,
                         count=20, seed=0) -> dict

def create_water_shore(server, name="Shore", radius=5.0, seed=0) -> dict
```

## character.py

```python
def create_humanoid_blockout(server, name="Humanoid", height=1.75,
                             build="average") -> dict

def create_eye_pair(server, name="Eyes", radius=0.012, spacing=0.065,
                    height=1.62) -> dict

def create_teeth_set(server, name="Teeth", width=0.05, height=0.02,
                     depth=0.04) -> dict

def create_hair_cap(server, name="Hair", head_object=None, radius=0.10,
                    strand_count=100, seed=0) -> dict

def create_garment(server, name="Shirt", body_width=0.40, body_depth=0.22,
                   torso_height=0.55, garment_type="shirt") -> dict

def create_face_landmarks(server, head_object, eye_spacing=0.065,
                          head_height=0.22) -> dict

def create_hand_blockout(server, name="Hand", side="L",
                         scale=1.0) -> dict

def create_foot_blockout(server, name="Foot", side="L",
                         length=0.26) -> dict
```

Character outputs are explicit blockouts, not AAA characters. Return a
`limitations` string saying so.

## materials_pbr.py

```python
def create_metal_material(server, name="Metal", color=(0.7, 0.7, 0.75, 1.0),
                          roughness=0.25) -> dict

def create_wood_material(server, name="Wood",
                         light_color=(0.45, 0.28, 0.14, 1.0),
                         dark_color=(0.20, 0.10, 0.05, 1.0),
                         scale=4.0) -> dict

def create_fabric_material(server, name="Fabric",
                           color=(0.2, 0.3, 0.5, 1.0),
                           roughness=0.8, sheen=0.3) -> dict

def create_glass_material(server, name="Glass",
                          color=(0.8, 0.9, 1.0, 1.0), roughness=0.05,
                          ior=1.45) -> dict

def create_skin_material(server, name="Skin",
                         color=(0.65, 0.45, 0.35, 1.0),
                         subsurface=0.15, roughness=0.45) -> dict

def create_concrete_material(server, name="Concrete",
                             color=(0.5, 0.5, 0.5, 1.0),
                             roughness=0.8, scale=8.0) -> dict

def create_emission_material(server, name="Emission",
                             color=(1.0, 0.8, 0.4, 1.0),
                             strength=5.0) -> dict

def assign_material_to_faces(server, object_name, material_name,
                             face_indices=None) -> dict
```

## animation.py

```python
def set_frame_range(server, start=1, end=250, fps=24) -> dict

def keyframe_path(server, object_name, points=None, frame_start=1,
                  frame_end=100, interpolation="BEZIER") -> dict

def create_turntable_animation(server, object_name, frames=120,
                               axis="Z") -> dict

def create_camera_rig(server, name="CameraRig", target=(0.0, 0.0, 1.0),
                      distance=6.0, height=3.0) -> dict

def add_follow_path_constraint(server, object_name, curve_name,
                               offset=0.0) -> dict

def set_keyframe_interpolation(server, object_name,
                               interpolation="LINEAR") -> dict

def create_action(server, object_name, name="Action") -> dict

def clear_animation(server, object_name) -> dict
```
