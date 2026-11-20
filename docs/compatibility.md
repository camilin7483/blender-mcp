# Compatibility

## Supported matrix

| Component | Baseline tested | Notes |
|---|---|---|
| Blender | **4.5.4 LTS** | Real GUI/headless tests on Linux x64. Released 2025-07-15; supported until 2027-07. Required gate for v4. GitHub Actions workflow pins the Linux tarball by SHA256. |
| Blender | 5.2 LTS | **5.2.4 LTS** tested locally (headless and GUI). CI matrix includes 5.2.4 Linux with a pinned SHA256. |
| Host Python | 3.10+ | `pro/mcp_server.py` runs outside Blender. Baseline host: Python 3.14.10. |
| Blender Python | Bundled with Blender 4.5 (3.11) | The add-on runs inside Blender, not in the host venv. |
| `mcp` | `1.30.0` | Pinned in `pro/requirements.txt`. |
| OS | Linux x64 | Baseline: Arch Linux, Blender 4.5.4, `xvfb-run` for GUI tests. |
| OS | Windows / macOS | Python contract/unit tests run in the CI matrix. Blender 5.2 headless jobs are experimental. The Windows hosted runner skips inspection rendering because its OpenGL context crashes Blender; Linux CI still tests rendering. |

## Execution modes

| Mode | Add-on server | Notes |
|---|---|---|
| Blender GUI | Works | `bpy.app.timers` runs on the main thread. |
| Blender GUI under `xvfb-run` | Works | Used by `tests/blender/smoke_gui.py`. |
| `blender --background` | Does **not** work | The event loop does not pump timers. `start()` now fails fast with an explicit message; use a GUI session or `xvfb-run`. |
| Headless import/geometry | Works with `-b` | No timers involved. Used by `tests/blender/import_headless.py`. |

## Known conflicts

- The legacy add-on and Pro both use `localhost:9876` and the same operator
  names. Enable only one at a time.
- `pro/sync_addon.sh` installs the add-on as both `blender_mcp_pro.py` and
  `blender_mcp.py`. Do not enable both copies. The extension package
  (`build/blender_mcp_pro-4.0.0.zip`) is a third install path; enable only one.
- The v4 add-on creates a token file on first start. The bridge and add-on must
  read the same path. See `SECURITY.md`.

## Versioning

- The repository follows SemVer. The current pre-release is `4.0.0-alpha.4`.
- v3 tools keep their names during the v4 migration. Breaking changes require
  a wrapper and a note in `docs/migration-v3-v4.md`.
- A v4 stable release requires the acceptance criteria in the project plan,
  including real Blender CI and published benchmark artifacts.
