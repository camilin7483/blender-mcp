# Compatibility

## Supported matrix

| Component | Baseline tested | Notes |
|---|---|---|
| Blender | **4.5.4 LTS** | Real GUI/headless tests on Linux x64. Released 2025-07-15; supported until 2027-07. Required gate for v4. GitHub Actions workflow pins the Linux tarball by SHA256. |
| Blender | 5.2 LTS | Released 2026-07-14; supported until 2028-07. Not installed in the baseline environment. CI target; add when a portable build is pinned with SHA256. If the add-on cannot support both, 4.5 LTS remains the gate and the decision is recorded in ADR-0002. |
| Host Python | 3.10+ | `pro/mcp_server.py` runs outside Blender. Baseline host: Python 3.14.10. |
| Blender Python | Bundled with Blender 4.5 (3.11) | The add-on runs inside Blender, not in the host venv. |
| `mcp` | `1.30.0` | Pinned in `pro/requirements.txt`. |
| OS | Linux x64 | Baseline: Arch Linux, Blender 4.5.4, `xvfb-run` for GUI tests. |
| OS | Windows / macOS | Python contract/unit tests run in the CI matrix. Blender headless jobs are not yet validated; see the CI workflow. |

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

- The repository follows SemVer. The current pre-release is `4.0.0-alpha`.
- v3 tools keep their names during the v4 migration. Breaking changes require
  a wrapper and a note in `docs/migration-v3-v4.md`.
- A v4 stable release requires the acceptance criteria in the project plan,
  including real Blender CI and published benchmark artifacts.
