# Domain pack contract — v4.8

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, deterministic seeds, Blender 4.5 and 5.2,
precise `ValueError` validation.

## character_rig.py

```python
def create_face_rig(server, mesh_name, armature_name="FaceRig") -> dict

def create_jaw_bone(server, armature_name, head, tail) -> dict

def create_eyelid_bones(server, armature_name, eye_spacing=0.065,
                        head_height=0.22) -> dict

def create_finger_rig(server, armature_name, side="L",
                      scale=1.0) -> dict

def create_ik_leg_rig(server, armature_name, hip, knee, ankle,
                      target_name) -> dict

def create_ik_arm_rig(server, armature_name, shoulder, elbow, wrist,
                      target_name) -> dict

def add_face_shape_keys(server, mesh_name, names=None) -> dict

def validate_character_rig(server, armature_name, mesh_name=None) -> dict
```

## world_building.py

```python
def create_city_block(server, name="CityBlock", width=40.0, depth=40.0,
                      building_count=6, seed=0) -> dict

def create_road(server, name="Road", length=40.0, width=7.0,
                lane_count=2) -> dict

def create_street(server, name="Street", length=40.0, width=8.0,
                  seed=0) -> dict

def create_bridge(server, name="Bridge", length=20.0, width=8.0,
                  height=4.0) -> dict

def create_tunnel(server, name="Tunnel", length=20.0, width=8.0,
                  height=4.0) -> dict

def create_skyscraper(server, name="Skyscraper", width=12.0, depth=12.0,
                      height=60.0, floors=20) -> dict

def create_park(server, name="Park", width=20.0, depth=20.0,
                tree_count=8, seed=0) -> dict

def create_plaza(server, name="Plaza", width=20.0, depth=20.0,
                 seed=0) -> dict
```

## material_library.py

```python
def create_marble_material(server, name="Marble",
                           color=(0.85, 0.85, 0.82, 1.0),
                           vein_color=(0.25, 0.25, 0.28, 1.0),
                           scale=3.0) -> dict

def create_brick_material(server, name="Brick",
                          color=(0.45, 0.16, 0.10, 1.0),
                          mortar_color=(0.75, 0.75, 0.72, 1.0),
                          scale=8.0) -> dict

def create_asphalt_material(server, name="Asphalt",
                            color=(0.08, 0.08, 0.09, 1.0),
                            roughness=0.9) -> dict

def create_grass_material(server, name="Grass",
                          color=(0.12, 0.35, 0.08, 1.0),
                          scale=12.0) -> dict

def create_sand_material(server, name="Sand",
                         color=(0.76, 0.65, 0.45, 1.0),
                         scale=10.0) -> dict

def create_rust_material(server, name="Rust",
                         color=(0.35, 0.12, 0.05, 1.0),
                         scale=6.0) -> dict

def create_chrome_material(server, name="Chrome",
                           roughness=0.05) -> dict

def create_ceramic_material(server, name="Ceramic",
                            color=(0.9, 0.9, 0.88, 1.0),
                            roughness=0.15) -> dict
```

## animation_fx.py

```python
def create_particle_system(server, object_name, name="Particles",
                           count=500, lifetime=60) -> dict

def create_trail(server, object_name, name="Trail",
                 length=20) -> dict

def create_muzzle_flash(server, name="MuzzleFlash",
                        location=(0.0, 0.0, 1.0),
                        energy=200.0) -> dict

def create_explosion(server, name="Explosion",
                     location=(0.0, 0.0, 1.0),
                     radius=2.0) -> dict

def create_smoke_plume(server, name="Smoke",
                       location=(0.0, 0.0, 0.0),
                       height=4.0, seed=0) -> dict

def create_fire_effect(server, name="Fire", radius=0.5,
                       height=1.5) -> dict

def create_spark_burst(server, name="Sparks",
                       location=(0.0, 0.0, 1.0),
                       count=100, seed=0) -> dict

def create_shockwave(server, name="Shockwave",
                     location=(0.0, 0.0, 1.0),
                     radius=3.0) -> dict
```

## utility.py

```python
def project_info(server) -> dict

def health_check(server) -> dict
```
