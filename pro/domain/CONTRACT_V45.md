# Domain pack contract — v4.5

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, deterministic seeds, Blender 4.5 and 5.2,
precise `ValueError` validation.

## props.py

```python
def create_barrel(server, name="Barrel", radius=0.3, height=0.8,
                  segments=16, seed=0) -> dict

def create_crate(server, name="Crate", size=0.6, plank_count=4) -> dict

def create_chest(server, name="Chest", width=0.8, depth=0.5,
                 height=0.5) -> dict

def create_lantern(server, name="Lantern", height=0.35,
                   radius=0.12) -> dict

def create_streetlamp(server, name="StreetLamp", height=3.0,
                      arm_length=0.8) -> dict

def create_sword(server, name="Sword", blade_length=0.8,
                 blade_width=0.06, guard_width=0.18) -> dict

def create_shield(server, name="Shield", width=0.6, height=0.8,
                  thickness=0.04) -> dict

def create_potion_bottle(server, name="Potion", height=0.2,
                         radius=0.05) -> dict
```

## furniture_extra.py

```python
def create_desk(server, name="Desk", width=1.6, depth=0.8, height=0.75,
                drawer_count=3) -> dict

def create_wardrobe(server, name="Wardrobe", width=1.2, depth=0.6,
                    height=2.0, door_count=2) -> dict

def create_dresser(server, name="Dresser", width=1.0, depth=0.5,
                   height=0.9, drawer_count=4) -> dict

def create_nightstand(server, name="Nightstand", width=0.5, depth=0.4,
                      height=0.55) -> dict

def create_coffee_table(server, name="CoffeeTable", width=1.2, depth=0.6,
                        height=0.42) -> dict

def create_bench(server, name="Bench", width=1.6, depth=0.45,
                 height=0.45) -> dict

def create_bar_stool(server, name="BarStool", seat_radius=0.18,
                     height=0.75) -> dict

def create_bookshelf(server, name="Bookshelf", width=1.0, height=2.0,
                     depth=0.3, shelf_count=5) -> dict
```

## vehicles.py

```python
def create_wheel(server, name="Wheel", radius=0.35, width=0.22,
                 segments=24) -> dict

def create_car_blockout(server, name="Car", length=4.2, width=1.8,
                        height=1.4) -> dict

def create_bicycle_blockout(server, name="Bicycle", length=1.7,
                            height=1.0) -> dict

def create_motorcycle_blockout(server, name="Motorcycle", length=2.1,
                               height=1.1) -> dict

def create_boat_blockout(server, name="Boat", length=5.0, width=1.8,
                         height=1.0) -> dict

def create_aircraft_blockout(server, name="Aircraft", length=8.0,
                             wingspan=10.0, height=2.5) -> dict

def create_robot_blockout(server, name="Robot", height=1.8,
                          build="humanoid") -> dict

def create_drone_blockout(server, name="Drone", span=0.5,
                          height=0.2) -> dict
```

## character_detail.py

```python
def create_nose(server, name="Nose", width=0.035, height=0.05,
                depth=0.04) -> dict

def create_ear_pair(server, name="Ears", width=0.03, height=0.06,
                    spacing=0.16) -> dict

def create_mouth(server, name="Mouth", width=0.05, height=0.018,
                 depth=0.02) -> dict

def create_brow_pair(server, name="Brows", width=0.04, height=0.01,
                     spacing=0.065) -> dict

def create_eyelash_pair(server, name="Eyelashes", radius=0.014,
                        strand_count=24, seed=0) -> dict

def create_hair_strands(server, name="HairStrands", radius=0.1,
                        strand_count=200, length=0.2,
                        seed=0) -> dict

def create_fingernails(server, name="Nails", radius=0.006,
                       count=10) -> dict

def create_face_proportions(server, head_object, height=0.22) -> dict
```
