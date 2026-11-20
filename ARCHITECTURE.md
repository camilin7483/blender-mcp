# Architecture

## Current baseline (v4.0.0-alpha.3)

```
MCP client (Claude/OpenCode/Cursor)
    |  stdio, FastMCP tools
    v
src/blender_mcp/server.py    host Python, one socket per command
    |  JSON {"type","params","auth_token"} + "\n"
    v  localhost:9876
pro/blender_mcp.py           Blender add-on, socket thread
    |  bpy.app.timers.register(...)
    v
Blender main thread          _execute_command_internal -> handlers -> bpy
```

`pro/mcp_server.py` is the legacy entry-point wrapper around
`src/blender_mcp/server.py`; existing MCP client configurations keep working.
`src/blender_mcp/transport.py` owns socket framing/auth and `config.py` owns
environment and timeout limits. `legacy/blender_mcp.py` is the v3 add-on.

### Components

| Component | File | Responsibility |
|---|---|---|
| MCP bridge | `src/blender_mcp/server.py` | Registers 301 FastMCP tools; serializes each call to a socket command; returns JSON text. |
| Socket transport | `src/blender_mcp/transport.py` | Auth token loading, one connection per command, framing, request IDs and response limits. |
| Bridge config | `src/blender_mcp/config.py` | Host, port, token paths, response limits and heavy-command timeouts. |
| Legacy entry point | `pro/mcp_server.py` | Thin wrapper that imports the package and keeps old MCP configurations working. |
| Legacy add-on | `legacy/blender_mcp.py` | Original v3 single-file add-on; not the Pro bridge. |
| Add-on server | `pro/blender_mcp.py` | Binds `localhost:9876`; accepts clients in threads; requires a token by default; rate-limits. |
| Main-thread dispatcher | `pro/blender_mcp.py` | Persistent queue drained by one timer; background and worker starts fail fast. |
| Command table | `pro/blender_mcp.py` | Maps command names to `BlenderMCPServer` methods. |
| Geometry service | `pro/blender_mcp.py` | Evaluated snapshots, world BVH, contact graph, topology, symmetry, tolerances. |
| Anchors | `pro/blender_mcp.py` | Center/face/surface/edge/corner/socket/bone/custom anchors and operations. |
| Audit | `pro/blender_mcp.py` | Collects metrics, evaluates requirements, computes the score, sets `passed` last. |
| Domain packs | `pro/domain/` | Terrain, vegetation, water, materials/UV, lighting and physics modules loaded dynamically by the add-on. |
| Rendering | `pro/blender_mcp.py` | Deterministic inspection cameras, modes, metadata and optional AABB overlay. |
| Export | `pro/blender_mcp.py` | Game profiles, scene validation, file write and reimport dimension check. |
| Asset downloads | `pro/blender_mcp.py` | Poly Haven and Sketchfab search/download/import. |
| Add-on UI | `pro/blender_mcp.py` | Start/stop operators and sidebar panel. |

### Threading rules

1. `bpy` is only touched on Blender's main thread.
2. Socket threads may parse JSON, validate auth, rate-limit and enqueue work.
3. `bpy.app.timers` callbacks run on the main thread. A real Blender 4.5.4 +
   `xvfb-run` round-trip confirmed the callback thread, not a mock.
4. The add-on registers one timer on the main thread and uses a
   `queue.Queue` to transfer requests from socket threads.
5. The timer uses `persistent=True` so it can keep dispatching after a
   checkpoint load. Scene data references must be reacquired after
   `open_mainfile`.
6. `blender --background` lacks the timer event loop. The add-on rejects
   server startup in that mode. Headless geometry tests call handlers directly.
7. The bridge sends a queue timeout within its end-to-end response budget.
   The dispatcher atomically claims requests and skips expired work. The bridge
   also opts into cancelling queued work on socket disconnect. Legacy clients
   may omit both fields. When a handler has started, Blender reports an unknown
   result on expiry. Callers must inspect the scene before retrying a mutation.

### Geometry authority

- `GeometryService.snapshot()` evaluates the depsgraph and stores world/local
  AABB, world vertices, face centers/areas and a world-space BVH.
- `contact_graph()` uses AABB only as a broad-phase filter. Surface
  intersection comes from `BVHTree.overlap`; separation distance comes from
  BVH nearest queries with a method and confidence label. When closed meshes
  have disjoint boundaries, a ray-parity test checks each connected boundary
  component for solid overlap, including shells with empty cavities.
- `topology_metrics()` reports non-manifold and boundary edges, loose
  vertices/edges, zero-area and degenerate faces, duplicate vertices,
  inverted normals, disconnected components and optional self-intersections.
- `symmetry_error()` and `ground_contact()` use evaluated geometry.
- `audit_3d_model()` collects all metrics, evaluates requirements, computes
  the score, and only then sets `passed`. Blueprint, ground, scale, collision
  and symmetry requirements block `passed`; topology is report-only unless
  `topology_policy="strict"`. Strict mode also requires every structural
  part to have a contact path to the ground. The `suspended` list exempts
  intentionally unsupported objects from that requirement.
- AABB is never the sole proof of collision.
- `AnchorService` exposes world position, normal, tangent, local frame,
  source, confidence and tolerance for center, face, surface, edge, corner,
  socket, bone and custom anchors. AABB anchors are world-axis-aligned;
  arbitrary-orientation mates need custom or local anchors.
- `validate_constraints()` evaluates mate, align, flush, center, offset,
  distance, parallel, perpendicular, ground_contact, symmetry,
  no_intersection, inside and surface_contact without changing the scene.
  `inside` requires a closed container. It rejects ambiguous contact on
  nonconvex boundaries when containment cannot be certified.
- `create_assembly()` builds a declarative assembly from a desk template or
  explicit components; `update_assembly()` deep-merges changes and rebuilds
  from the stored spec. Components are parented to a root empty.

### Visual inspection

- `render_multiview_inspection()` uses documented cameras: FRONT, RIGHT and
  TOP are orthographic with an ortho scale derived from the evaluated
  assembly AABB; ISO is a 50 mm perspective camera at a fixed angle.
- Every view uses a fixed inspection world, fixed lights and fixed render
  settings (EEVEE, 16 samples, PNG, Standard view transform).
- Outputs go to `BLENDER_MCP_OUTPUT_DIR/inspection/<render_id>/`, where
  `render_id` is a SHA-256 hash of cameras, resolution, AABB and overlays.
  `metadata.views` records camera type, location, rotation, ortho scale or
  lens, engine, shading and file.
- Modes: `quad`, `front`, `side`, `top`, `iso`, `silhouette`, `wireframe`,
  `normals`, `uv_checker`. `include_overlays` adds an AABB wireframe and
  reports dimensions in metadata.
- Pixel identity is only claimed for the same Blender build and GPU.

### Known architectural debt

- Two unversioned sources of truth before the `v3.0.0-baseline` tag.
- One 3.3k-line add-on file and one 0.8k-line bridge file.
- No protocol version negotiation beyond the optional `request_id`.
- Profiles filter FastMCP registration at bridge import; the add-on keeps
  every handler. `execute_code` is full-only.
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
