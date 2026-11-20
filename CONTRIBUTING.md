# Contributing

## Setup

```bash
git clone <repo>
cd blender-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -r pro/requirements.txt
```

Blender runs its own Python. Do not install the bridge dependencies into
Blender's interpreter.

## Tests

Host-side tests:

```bash
.venv/bin/python -m pytest tests/contracts tests/unit tests/integration -q
```

Real Blender 4.5 LTS:

```bash
BLENDER_BIN=/path/to/blender-4.5.4-linux-x64/blender ./scripts/run_blender_tests.sh
```

Real Blender 5.2 LTS:

```bash
BLENDER_BIN=/path/to/blender-5.2.4-linux-x64/blender ./scripts/run_blender_tests.sh
```

BlenderMCP-Bench:

```bash
BLENDER_BIN=/path/to/blender ./scripts/run_bench.sh --runs 3 --output bench/results/latest
```

Extension build and validation:

```bash
BLENDER_BIN=/path/to/blender ./scripts/build_extension.sh
"$BLENDER_BIN" --factory-startup --command extension validate build/blender_mcp_pro-4.0.0.zip
```

The GUI test needs an event loop. On Linux without `DISPLAY`, the script uses
`xvfb-run`. `blender --background` does not pump timers and is only used for
import/geometry tests.

Lint:

```bash
.venv/bin/ruff check tests scripts bench
```

## Rules

- One pull request, one responsibility. Do not mix a refactor with a behavior
  change.
- Use conventional commits: `test:`, `fix:`, `feat:`, `refactor:`, `docs:`,
  `security:`, `build:`, `ci:`.
- A bug fix starts with a test that reproduces the bug. Confirm it fails, fix
  the root cause, confirm it passes, add a regression test.
- Use real Blender for geometry, depsgraph, modifier, timer and socket
  behavior. Mock `bpy` only for pure logic that does not need Blender.
- Do not claim a test was executed without the CI log or a local command
  output.
- Do not weaken a test, skip a check or change an expected value to make a
  failure disappear.
- AABB is broad-phase only. A collision claim needs a narrow-phase method.
- `passed` is computed after all audit requirements, never before.
- New tools need a contract test and, when they touch Blender, a real Blender
  test.
- Breaking changes need an ADR and an entry in `docs/migration-v3-v4.md`.
- Code, comments and identifiers are in English. User-facing documentation may
  be translated separately.

## Security-sensitive changes

Changes to authentication, input handling, paths, network access, archive
extraction or `execute_code` need a security review and a test in
`tests/security/`. Update `SECURITY.md` when the threat model changes.

## Blender add-on install

`pro/blender_mcp.py` is a single-file add-on. Use
`pro/sync_addon.sh` to copy it into Blender's add-ons directory, or install it
with **Edit -> Preferences -> Add-ons -> Install from Disk**. Only one edition
(legacy or Pro) may be enabled because both bind `localhost:9876`.
