# Compatibility

## Supported matrix

| Component | Baseline tested | Notes |
|---|---|---|
| Blender | **4.5.4 LTS** | GUI and headless tests on Linux x64. The installer download is pinned by SHA-256. |
| Blender | **5.2.4 LTS** | GUI and headless tests on Linux x64. The installer download is pinned by SHA-256. |
| Host Python | 3.10+ | The MCP bridge runs outside Blender. GitHub Actions uses Python 3.12 on Linux, Windows, and macOS. |
| Blender Python | Bundled with Blender 4.5 (3.11) | The add-on runs inside Blender, not in the host venv. |
| `mcp` | `1.30.0` | Pinned in `pro/requirements.txt`. |
| OS | Linux x64 | Baseline: Arch Linux, Blender 4.5.4, `xvfb-run` for GUI tests. |
| OS | Windows / macOS | Python tests and experimental Blender 5.2 headless checks. The Windows runner skips render cases that need its unavailable OpenGL context. The macOS Blender runner is arm64. |

## Execution modes

| Mode | Add-on server | Notes |
|---|---|---|
| Blender GUI | Works | `bpy.app.timers` runs on the main thread. |
| Blender GUI under `xvfb-run` | Works | Used by `tests/blender/smoke_gui.py`. |
| `blender --background` | Does **not** work | The event loop does not pump timers. `start()` now fails fast with an explicit message; use a GUI session or `xvfb-run`. |
| Headless modeling/rendering | Works with `-b` | Scripts call modeling methods on Blender's main thread. The [showcase scenes](showcase/README.md) use this mode. |

## Known conflicts

- The legacy add-on and Pro both use `localhost:9876` and the same operator
  names. Enable only one at a time.
- `pro/sync_addon.sh` installs the add-on as both `blender_mcp_pro.py` and
  `blender_mcp.py`. Do not enable both copies. The extension package
  (`build/blender_mcp_pro-4.9.0.zip`) is a third install path; enable only one.
- The v4 add-on creates a token file on first start. The bridge and add-on must
  read the same path. See `SECURITY.md`.

## Stable release coverage

- Linux CI runs the GUI socket and headless suite, rebuilds and reopens the
  showcase scenes, and benchmarks 46 tasks. Both lanes install the extension
  into a fresh profile and rerun the authenticated socket suite from the
  installed package. Mirror downloads must match the pinned SHA-256.
- Windows and macOS run Python tests and a separate Blender 5.2 headless
  job. The Windows job skips render checks. Interactive socket, render,
  and installed-extension smoke tests on native Windows/macOS remain
  part of the stable-release validation.

## Versioning

- The repository follows SemVer. The current candidate is `4.9.0-alpha.2`.
- v3 tools keep their names during the v4 migration. Breaking changes require
  a wrapper and a note in `docs/migration-v3-v4.md`.
- A v4 stable release requires the acceptance criteria in the project plan,
  including real Blender CI and published benchmark artifacts.
