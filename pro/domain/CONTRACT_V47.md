# Domain pack contract — v4.7

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, deterministic seeds, Blender 4.5 and 5.2,
precise `ValueError` validation.

## animation_advanced.py

```python
def create_nla_track(server, object_name, action_name,
                     start_frame=1) -> dict

def add_camera_shake(server, camera_name, strength=0.05, frame_start=1,
                     frame_end=60, seed=0) -> dict

def add_timeline_marker(server, name, frame=1) -> dict

def set_motion_paths(server, object_name, enabled=True) -> dict

def set_animation_curve_preset(server, object_name,
                               preset="ease_in_out") -> dict

def retime_action(server, object_name, factor=1.0) -> dict

def create_camera_cut(server, camera_names, frame_ranges) -> dict

def validate_animation(server, object_name) -> dict
```

## physics_extra.py

```python
def add_force_field(server, name="Wind", field_type="WIND", strength=1.0,
                    location=(0.0, 0.0, 0.0)) -> dict

def create_rigid_body_chain(server, object_names, mass=1.0) -> dict

def create_cloth_preset(server, object_name, preset="silk") -> dict

def create_fluid_domain(server, domain_name, size=(2.0, 2.0, 2.0),
                        resolution=32) -> dict

def create_fluid_inflow(server, object_name, domain_name,
                        velocity=(0.0, 0.0, -1.0)) -> dict

def create_collision_object(server, object_name,
                            thickness=0.02) -> dict

def bake_physics(server, frame_end=60) -> dict

def validate_physics(server, object_name=None) -> dict
```

## qa_extra.py

```python
def scene_audit(server, include_hidden=False) -> dict

def material_audit(server) -> dict

def texture_audit(server) -> dict

def performance_budget(server, max_triangles=100000,
                       max_texture_mb=256) -> dict

def export_preflight(server, profile="generic-gltf") -> dict

def detect_floating_objects(server, tolerance=0.001) -> dict

def detect_duplicate_geometry(server, tolerance=0.0001) -> dict

def scene_repair_plan(server) -> dict
```

## environment_extra.py

```python
def create_rain_system(server, name="Rain", count=500, area=10.0,
                       seed=0) -> dict

def create_snow_system(server, name="Snow", count=500, area=10.0,
                       seed=0) -> dict

def create_lightning_rig(server, name="Lightning", location=(0.0, 0.0, 5.0),
                         energy=1000.0) -> dict

def create_wind_field(server, name="Wind", strength=1.0,
                      direction=(1.0, 0.0, 0.0)) -> dict

def create_atmospheric_haze(server, density=0.01,
                            color=(0.8, 0.85, 0.9)) -> dict

def create_sunset_lighting(server) -> dict

def create_night_lighting(server, moon_energy=0.5) -> dict

def create_weather_scene(server, weather="rain", size=10.0,
                         seed=0) -> dict
```
