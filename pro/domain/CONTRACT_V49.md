# Domain pack contract — v4.9 character depth

Same rules as `CONTRACT.md`: real `bpy`/`bmesh`/`mathutils`, main-thread,
JSON-serializable dicts, no stubs, deterministic seeds, Blender 4.5 and 5.2,
precise `ValueError` validation.

This tranche builds a **high-detail procedural character base**. It must not
claim AAA or photoreal certification. `character_quality_report` must return
`aaa_certified: false` and explicit missing requirements unless a future
external asset/human-review gate changes that contract.

## character_pro.py

```python
def create_anatomical_head(server, name="HeadPro", height=0.23, width=0.15,
                           depth=0.19, subdivisions=2) -> dict

def create_eye_assembly(server, name="EyePro", radius=0.012,
                        iris_color=(0.2, 0.4, 0.7, 1.0)) -> dict

def create_skin_material_pro(server, name="SkinPro",
                             base_color=(0.65, 0.45, 0.35, 1.0),
                             subsurface=0.15, roughness=0.45,
                             pore_scale=80.0) -> dict

def create_dental_arch(server, name="DentalArchPro", width=0.05,
                       depth=0.04, tooth_count=16) -> dict

def create_character_body_pro(server, name="BodyPro", height=1.75,
                              build="average", subdivisions=1) -> dict

def create_garment_shell_pro(server, name="GarmentPro", body_width=0.40,
                             body_depth=0.22, torso_height=0.55,
                             garment_type="shirt") -> dict
```

## character_groom.py

```python
def create_hair_groom(server, name="HairGroom", head_object=None,
                      strand_count=500, length=0.18, seed=0) -> dict

def create_eyebrow_groom(server, name="BrowsPro", head_object=None,
                         strand_count=80, seed=0) -> dict

def create_eyelash_groom(server, name="LashesPro", head_object=None,
                         strand_count=60, radius=0.014, seed=0) -> dict

def create_character_rig_pro(server, mesh_name,
                             armature_name="CharacterRig") -> dict

def create_character_studio(server, name="CharacterStudio",
                            target=(0.0, 0.0, 1.0)) -> dict

def character_quality_report(server, mesh_name, armature_name=None,
                             hair_objects=None) -> dict
```
