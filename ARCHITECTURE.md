# Architecture

## Current baseline (v3.0.0)

```
MCP client (Claude/OpenCode/Cursor)
    |  stdio, FastMCP tools
    v
pro/mcp_server.py            host Python, one socket per command
    |  JSON {"type","params","auth_token"} + "\n"
    v  localhost:9876
pro/blender_mcp.py           Blender add-on, socket thread
    |  bpy.app.timers.register(...)
    v
Blender main thread          _execute_command_internal -> handlers -> bpy
```

### Components

| Component | File | Responsibility |
|---|---|---|
| MCP bridge | `pro/mcp_server.py` | Registers 53 FastMCP tools; serializes each call to a socket command; returns JSON text. |
| Socket transport | `pro/mcp_server.py` | New connection per command; 60 s / 180 s timeouts; JSON response parsing. |
| Add-on server | `pro/blender_mcp.py` | Binds `localhost:9876`; accepts clients in threads; validates optional token; rate-limits. |
| Main-thread dispatcher | `pro/blender_mcp.py` | Registers a timer per request; waits for completion; returns the response. |
| Command table | `pro/blender_mcp.py` | Maps command names to `BlenderMCPServer` methods. |
| Geometry helpers | `pro/blender_mcp.py` | Evaluated AABB, world-space BVH, surface gap, contact heuristics. |
| Audit | `pro/blender_mcp.py` | Ground, scale, overlap and parent-child floating checks. |
| Rendering | `pro/blender_mcp.py` | Four-view inspection sheet and three-point lighting. |
| Asset downloads | `pro/blender_mcp.py` | Poly Haven and Sketchfab search/download/import. |
| Add-on UI | `pro/blender_mcp.py` | Start/stop operators and sidebar panel. |

### Threading rules

1. `bpy` is only touched on Blender's main thread.
2. Socket threads may parse JSON, validate auth, rate-limit and enqueue work.
3. `bpy.app.timers` callbacks run on the main thread. A real Blender 4.5.4 +
   `xvfb-run` round-trip confirmed the callback thread, not a mock.
4. **Registering a timer from a worker thread is not supported by Blender.**
   It does not raise, but it mutates a global timer list without a lock
   (`bpy_app_timers.cc` / `BLI_timer.cc`). The current per-request
   `bpy.app.timers.register()` from the socket thread is therefore a data
   race. The v4 dispatcher must use a `queue.Queue` plus one persistent timer
   registered from the main thread that drains the queue.
5. A permanent pump timer must use `persistent=True`. Opening a `.blend`
   file removes non-persistent timers; after `open_mainfile`, all previous
   `bpy` references are invalid.
6. `blender --background` does **not** pump timers. The add-on therefore
   cannot serve commands in pure background mode. Tests must use a GUI event
   loop (`xvfb-run` on Linux). The legacy add-on warned about this; Pro does
   not yet.
7. A socket handler blocks one thread until the main thread finishes or the
   timeout expires. There is no queue, cancellation or fairness policy.

### Geometry authority

- `GeometryService.snapshot()` evaluates the depsgraph and stores world/local
  AABB, world vertices, face centers/areas and a world-space BVH.
- `contact_graph()` uses AABB only as a broad-phase filter. Surface
  intersection comes from `BVHTree.overlap`; separation distance comes from
  BVH nearest queries with a method and confidence label.
- `topology_metrics()` reports non-manifold and boundary edges, loose
  vertices/edges, zero-area and degenerate faces, duplicate vertices,
  inverted normals, disconnected components and optional self-intersections.
- `symmetry_error()` and `ground_contact()` use evaluated geometry.
- `audit_3d_model()` collects all metrics, evaluates requirements, computes
  the score, and only then sets `passed`. Blueprint, ground, scale, collision
  and symmetry requirements block `passed`; topology is report-only unless
  `topology_policy="strict"`.
- AABB is never the sole proof of collision.

### Known architectural debt

- Two unversioned sources of truth before the `v3.0.0-baseline` tag.
- One 3.3k-line add-on file and one 0.8k-line bridge file.
- No protocol version negotiation beyond the optional `request_id`.
- No tool profiles; all 53 tools are always registered.
- Destructive and network operations have a policy layer, but no per-tool
  capability scopes.
- The bridge and add-on duplicate parameter knowledge with no shared schema.

## Target v4

```
src/blender_mcp/
    server.py            FastMCP app and lifecycle
    config.py            env, paths, timeouts, limits
    tools/               one module per tool category
    schemas/             request/response models and JSON Schema
    protocol/            framing, version negotiation, errors
    transport/           socket client, retries, health

addon/blender_mcp_pro/
    server.py            socket server and lifecycle
    dispatcher.py        command table, capability checks
    main_thread.py       queue + persistent timer, no bpy off-thread
    handlers/            one module per command category
    geometry/            snapshot, bvh, topology, contacts, symmetry
    validation/          paths, URLs, limits, policy
    rendering/           deterministic views, overlays, metadata
```

### Dependency direction

- `protocol/` and `schemas/` have no `bpy` and no FastMCP dependency.
- `transport/` depends on `protocol/`, not on tool implementations.
- `tools/` depends on `schemas/` and `transport/`.
- `addon/` depends on `geometry/`, `validation/` and `rendering/`, but never
  imports `src/blender_mcp/` at runtime.
- The wire contract is the shared JSON Schema. Contract tests compare both
  sides; no duplicated Python models are required inside Blender.
- Legacy wrappers keep v3 tool names and response keys until the migration
  window closes.

### Invariants

1. One canonical repository, one tag per release.
2. `bpy` only on the main thread; the dispatcher asserts it.
3. AABB is broad-phase only. A collision claim needs a narrow-phase method.
4. Measurements use evaluated geometry when modifiers/constraints exist.
5. Audit computes `passed` after all requirements, never before.
6. Every failure names the rule, object, expected value, actual value,
   tolerance and measurement method.
7. Every tool has a contract test and, when it touches Blender, a real
   Blender test.
8. No release claim without a CI log and, for benchmarks, published artifacts.

## Decisions

Architecture decisions are recorded as ADRs. The initial set:

- ADR-0001: canonical repo and `src/` + `addon/` layout.
- ADR-0002: Blender 4.5 LTS required, 5.2 LTS secondary.
- ADR-0003: secure defaults (auth, execute gate, output sandbox).
- ADR-0004: protocol v4 (newline JSON, request IDs, version).
- ADR-0005: geometry authority (evaluated depsgraph, BVH narrow-phase).
- ADR-0006: audit contract (`passed` last, structured failures).
