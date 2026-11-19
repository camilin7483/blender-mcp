# Tests

Three layers, with different requirements:

| Directory | Runs with | Purpose |
|---|---|---|
| `tests/contracts/` | `pytest` on the host | Bridge <-> add-on parity, protocol schemas, no `bpy`. |
| `tests/unit/` | `pytest` on the host | Pure Python logic that does not require Blender. |
| `tests/blender/` | Real Blender 4.5 LTS | Geometry, depsgraph, timers and socket round-trips. |
| `tests/integration/` | `pytest` on the host | Fake add-on / protocol end-to-end without `bpy`. |

## Run host tests

```bash
python3 -m pytest tests/contracts tests/unit tests/integration -q
```

## Run real Blender tests

```bash
BLENDER_BIN=/path/to/blender-4.5.4-linux-x64/blender ./scripts/run_blender_tests.sh
```

The script auto-detects a local Blender build when `BLENDER_BIN` is unset.
`tests/blender/import_headless.py` runs with `blender -b`.
`tests/blender/smoke_gui.py` needs Blender's event loop, because the add-on
dispatches commands through `bpy.app.timers`. On Linux without `DISPLAY`,
the script wraps it in `xvfb-run`. `blender -b` alone does not run timers.

## Rules

- Do not mock `bpy` for geometry, depsgraph, modifiers or timer behavior.
- Every tool behavior that touches Blender needs a `tests/blender/` case.
- Do not mark a test as executed unless CI produced the log.
- A bug fix starts with a failing test that reproduces it.
