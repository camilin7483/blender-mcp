# Roadmap

## Current

- Baseline: `v4.0.0-alpha.4` plus audit-blocker fixes.
- Branch: `feat/v4.1-domain-engine`.
- Tool count: 89 real tools on this branch (61 baseline + 24 domain + 4 discovery).
- Verified: Blender 4.5.4 and 5.2.4 headless/GUI, 14/14 local benchmark tasks.

## v4.1 — Tool registry, discovery and domain engine

- [x] Tool catalog metadata: category, safety, cost, units and schema.
- [x] Discovery tools: `tools_search`, `tools_describe`, `tools_catalog`.
- [x] Batch execution: `run_workflow`.
- [x] Terrain pack: terrain, sculpt region, scatter, rock.
- [x] Vegetation pack: tree, bush, grass, flowers.
- [x] Water pack: water plane, river, pond, water material.
- [x] Lighting/render pack: light, camera, world, still render.
- [x] Material/UV pack: procedural material, smart UV, UV packing, materials.
- [x] Physics pack: rigid body, collision, cloth, bake.
- [x] Profile `nano` and `guided` for small models.
- [x] Real-Blender tests for every new pack.
- [x] Benchmark tasks for the new domains (20/20, 3 runs).
- [ ] Docs and changelog.

## v4.2 — Precision modeling

- More hard-surface components, booleans, bevels and assemblies.
- Decal/trim sheets and manufacturing dimensions.
- Repair and topology diagnostics.

## v4.3 — Architecture and interiors

- Rooms, doors, windows, kitchens, bathrooms, furniture.
- Multi-floor buildings, facades, stairs, roofs.
- Architectural lighting and render presets.

## v4.4 — Nature and vegetation

- Erosion, biomes, slope-aware distribution, LOD vegetation.
- Rocks, cliffs, caves, beaches and islands.

## v4.5 — Water, physics and simulations

- Rivers, lakes, oceans, waterfalls, foam and underwater materials.
- Rigid bodies, cloth, fluids and bake management.

## v4.6 — Materials, UV and textures

- PBR library, procedural shaders, UDIM, baking and texture export.

## v4.7 — Character engine

- Parametric anatomy, landmarks, eyes, hair, garments, rig and skinning.
- Explicitly separate a production-ready character from a primitive blockout.

## v4.8 — Rigging and animation

- IK/FK, constraints, retargeting, facial shapes and deformation checks.

## v4.9 — AAA quality

- Grooming, microdetail, UDIM, cinematic lighting and high-fidelity pipelines.

## v4.10 — Autocorrection and workflows

- Visual diagnosis, repair loops, declarative specs and resumable jobs.

## v4.11 — Cost optimization

- Token benchmarks, batch workflows, caching, delta scene inspection.

## v4.12 — Render and visual QA

- Render passes, composition, visual regression and turntables.

## v5.0 — Universal pipeline

- Integrated scene, character, architecture, environment and export pipeline.

## Rules

- Advance one release at a time.
- Do not publish a release without tests, docs, changelog and artifacts.
- Do not count placeholders, aliases or stubs as tools.
