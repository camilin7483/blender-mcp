# Blender MCP Pro — Agent Rules

## Mission

Build a general-purpose, verifiable Blender production server. Quality and
evidence come before tool count. No fake tools, no simulated results, no
unverified release claims.

## Non-negotiable rules

- Blender `bpy` calls only from the Blender main thread.
- Every public tool has a real handler, a typed schema, a description and a
  test. Count only real capabilities; never aliases, wrappers or stubs.
- Geometry decisions use evaluated data. AABB is broad-phase only; collisions
  use BVH overlap.
- Do not weaken tests, delete failing checks or hide errors to get green.
- Do not enable `execute_code`, network downloads or destructive operations by
  default.
- Code, comments, identifiers and project files are in English. User-facing
  conversation is in Spanish.
- Keep legacy contracts working until a documented breaking release.

## Architecture

- `pro/blender_mcp.py`: Blender add-on entry point, main-thread queue,
  legacy domain methods and dispatcher.
- `pro/domain/`: new domain tool packs loaded by the add-on. Pure modules with
  `bpy`; no imports from the add-on module to avoid cycles.
- `src/blender_mcp/server.py`: FastMCP bridge and tool registration.
- `src/blender_mcp/transport.py`: socket transport and auth.
- `src/blender_mcp/config.py`: environment and limits.
- `pro/mcp_server.py`: legacy bridge wrapper.
- `tests/blender/`: real Blender tests. `tests/contracts`: schema/parity.
  `tests/unit`: host-only logic.

## Domain module contract

Each module in `pro/domain/` exposes functions with this shape:

```python
def create_thing(server, name: str, ...) -> dict:
    """One-line description."""
```

- `server` is the add-on instance; use it only for shared helpers or audits.
- Do not import `blender_mcp` from a domain module.
- Validate all user input. Raise `ValueError` with a precise message.
- Return plain JSON-serializable dictionaries; include `success`, object names,
  dimensions and any relevant metadata.
- Keep functions deterministic when a `seed` is provided.
- Use only Blender 4.5 and 5.2 compatible APIs.
- Do not write files outside the configured output sandbox.

## Evidence

A task is complete only after:

1. The implementation exists in the workspace.
2. Relevant tests were executed and passed.
3. The diff was reviewed.
4. Documentation and changelog were updated.
5. The commit is identifiable.

## Releases

Tags follow SemVer. Do not move existing tags. Stable releases require green CI
on supported platforms and the gates in `docs/release-checklist.md`.
