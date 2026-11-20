# Domain pack contract — v4.2

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, no file writes, deterministic seeds,
Blender 4.5 and 5.2, precise `ValueError` validation.

## architecture_shell.py

```python
def create_room_shell(server, name="Room", width=5.0, depth=4.0, height=3.0,
                      wall_thickness=0.12, floor_thickness=0.10,
                      door_width=0.9, door_height=2.1,
                      window_width=1.2, window_height=1.2,
                      location=(0.0, 0.0, 0.0)) -> dict

def create_door(server, name="Door", width=0.9, height=2.1, thickness=0.04,
                frame_thickness=0.06, location=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0)) -> dict

def create_window(server, name="Window", width=1.2, height=1.2,
                  frame_thickness=0.06, glass_thickness=0.01,
                  location=(0.0, 0.0, 0.0),
                  rotation=(0.0, 0.0, 0.0)) -> dict
```

## architecture_furniture.py

```python
def create_table(server, name="Table", width=1.4, depth=0.8, height=0.75,
                 top_thickness=0.04, leg_size=0.06) -> dict

def create_chair(server, name="Chair", seat_width=0.45, seat_depth=0.45,
                 seat_height=0.45, back_height=0.45,
                 leg_size=0.04) -> dict

def create_shelf(server, name="Shelf", width=1.0, height=1.8, depth=0.3,
                 shelf_count=4, board_thickness=0.03) -> dict

def create_bed(server, name="Bed", width=1.6, length=2.0, height=0.5,
               headboard_height=0.9) -> dict

def create_sofa(server, name="Sofa", width=2.0, depth=0.9, height=0.8,
                seat_count=3) -> dict

def create_kitchen_block(server, name="Kitchen", width=2.4, depth=0.6,
                         height=0.9, cabinet_count=4,
                         counter_thickness=0.04) -> dict
```

Furniture must be one joined mesh per object, grounded at Z=0, with real
legs/frames/cushions/shelves and approximate requested dimensions.

## hardsurface_modifiers.py

```python
def add_bevel_modifier(server, object_name, width=0.02, segments=2,
                       angle_limit=30.0) -> dict

def add_solidify_modifier(server, object_name, thickness=0.02,
                          offset=-1.0) -> dict

def add_array_modifier(server, object_name, count=3,
                       offset=(0.0, 0.0, 0.0), relative=False) -> dict

def add_mirror_modifier(server, object_name, axis="X",
                        bisect=False) -> dict

def apply_all_modifiers(server, object_name) -> dict
```

## hardsurface_primitives.py

```python
def create_text_object(server, text="Text", name="Text", size=1.0,
                       extrude=0.0, align_x="CENTER") -> dict

def create_curve_tube(server, name="Tube", points=None, radius=0.05,
                      resolution=12, cyclic=False) -> dict

def create_metaball(server, name="Metaball", radius=0.5, stiffness=2.0,
                    location=(0.0, 0.0, 0.0)) -> dict

def convert_to_mesh(server, object_name) -> dict
```
