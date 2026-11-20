# Security

## Status

The `v3.0.0-baseline` tag is a **development baseline, not a hardened
release**. This document describes the threat model and the mitigations that
v4 must implement. It does not certify the current code as safe.

Pro v4 requires a local token by default, gates arbitrary Python execution,
bounds asset downloads and confines export paths. The compatibility opt-ins
grant broader access. Tool output can contain untrusted text from scene data
and asset metadata. Clients should review repair suggestions and use structured
tool arguments.

## Trust boundaries

| Boundary | Trust |
|---|---|
| MCP client -> bridge (stdio) | The client is trusted to send tool calls, but its prompts and model output are untrusted input. |
| Bridge -> add-on (`localhost:9876`) | Local process boundary. Any local process can attempt to connect unless authentication is enabled. |
| Add-on -> `bpy` | Privileged. Runs on Blender's main thread with full Python access. |
| Add-on -> filesystem | Untrusted paths and untrusted downloaded archives must be treated as hostile. |
| Add-on -> remote asset APIs | Remote responses, redirects and DNS answers are untrusted. |
| Scene files / imported assets | Untrusted data. A `.blend`, `.glb`, texture or archive can be malicious. |

The security boundary is the local machine, not the network. Binding to
loopback is necessary but not sufficient: local malware, a malicious browser
extension, a compromised MCP client, or a prompt-injected agent can all reach
`localhost`.

## Threat model

| Threat | Vector | Current v3 state | Required v4 mitigation | Residual risk |
|---|---|---|---|---|
| Prompt injection | Untrusted text in a scene, filename, asset description or tool result instructs the model to call destructive tools. | No distinction between data and instructions. Destructive tools run directly. | Tool descriptions mark data as untrusted; destructive tools require explicit confirmation; policy checks before execution. | A user can still approve a malicious action. |
| Tool poisoning | A malicious MCP server or tool description impersonates a trusted tool or hides instructions. | The bridge exposes a fixed local tool set; no provenance checks on external tools. | Pin the tool set, sign/verify releases, show tool provenance, reject unknown tool descriptions in clients. | Client-side trust remains. |
| Confused deputy | The add-on has more privileges than the caller and executes a request on the caller's behalf. | A per-install token is required by default; there are no per-tool scopes yet. | Per-session token, capability scopes, explicit user consent for privileged operations. | Local user session compromise. |
| SSRF | A crafted asset URL or provider response points to `127.0.0.1`, link-local, metadata services or an internal host. | HTTPS-only provider allowlist, numeric connection to a validated public DNS answer, redirect re-validation and size caps. | HTTPS-only allowlist, DNS resolution and private/link-local/loopback blocking, redirect re-validation, pinned IP per connection. | A trusted provider can still return untrusted asset content. |
| Token theft | `BLENDER_AUTH_TOKEN` or the Sketchfab token is read from env, logs, process listings or a world-readable file. | Token file is 0600; passed in plaintext JSON over loopback; env override supported. | Token file mode 0600, constant-time comparison, never log tokens, rotate on start, redact errors. | Same-user process can read the file. |
| Arbitrary code execution | `execute_code` calls `exec()` with full builtins. | Disabled by default; explicit add-on preference or `BLENDER_MCP_ALLOW_EXECUTE_CODE=1`. | Disabled by default; explicit preference/env opt-in; structured refusal; no hidden execution path. | An opted-in user grants full Blender Python access. |
| Data exfiltration | A tool reads scene data, files or tokens and sends them to a remote host. | `execute_code` and download tools can read files and make network calls. | Output sandbox, no arbitrary file reads, network allowlist, audit log, user confirmation for exports. | A user-approved export can still leak data. |
| Destructive scene operations | `clear_scene`, `delete_object`, `boolean_operation`, `rollback_checkpoint` mutate or replace the scene. | `clear_scene`, `delete_object`, `rollback_checkpoint` and `setup_studio_lighting` return a dry-run unless `confirm=true` or `BLENDER_MCP_ALLOW_UNSAFE_OPS=1`. | `confirm` flag, dry-run preview, checkpoint before mutation, undo integration where possible. | Confirmed destructive calls still destroy data. |
| Malicious asset files | A `.blend`, `.glb`, texture or archive exploits the importer, contains a zip-slip path, or fills the disk. | Safe ZIP extraction with path, symlink, file-count and size limits; provider-only HTTPS downloads. | Safe extraction (resolve, reject `..`, absolute paths, symlinks), uncompressed-size and file-count caps, importer sandboxing where available. | Importer vulnerabilities remain. |
| Malicious paths | `export_scene`, checkpoint names or download IDs escape the output directory. | `export_scene` is confined to `BLENDER_MCP_OUTPUT_DIR` with an extension allowlist; unknown formats raise. Download IDs and ZIP paths are still open until the next fix. | Resolve and confine to `BLENDER_MCP_OUTPUT_DIR`; reject traversal and symlinks; sanitize IDs; extension allowlist. | A user-approved path outside the sandbox. |
| DNS rebinding | A hostname resolves to a public IP during validation and to a private IP at connect time. | Each HTTPS connection uses a validated numeric address and checks the TLS certificate against the provider hostname. Ambient proxies are bypassed. | Keep address validation per connection. Strip credentials on cross-origin redirects. | A compromised resolver or OS-level attack. |
| Supply chain | A compromised `mcp` package, Blender build, add-on zip or GitHub Action runs with the user's privileges. | `mcp==1.30.0` is pinned in `pro/requirements.txt`; no hashes, no pinned CI actions yet. | Pin dependencies and Actions by commit, publish hashes, sign releases, reproducible build, dependency review. | Upstream compromise before pinning. |

## Secure defaults for v4

Implemented in this branch: per-install token file, main-thread queue,
`execute_code` gate, dry-run destructive operations, export path sandbox and
remote-download hardening. The rest are planned.

- Authentication enabled by default with a per-install token file (0600).
- `execute_code` disabled unless explicitly enabled in add-on preferences or
  `BLENDER_MCP_ALLOW_EXECUTE_CODE=1`.
- Destructive tools require `confirm=true`; a dry-run response is returned
  otherwise.
- Output paths are confined to `BLENDER_MCP_OUTPUT_DIR`.
- Downloads are HTTPS-only, host-allowlisted, size-capped, and extracted with
  a safe ZIP routine.
- The add-on panel starts a loopback listener. The stdio bridge connects to
  loopback by default. `BLENDER_HOST` can override the destination and the TCP
  connection carries the token in plaintext.
- The request ID correlates calls and responses. A durable per-call audit log
  is still planned.

## Token file

- Default: `$XDG_CONFIG_HOME/blender-mcp/token` on Linux/macOS, or
  `%APPDATA%\blender-mcp\token` on Windows. `XDG_CONFIG_HOME` defaults to
  `~/.config`.
- Override the path with `BLENDER_MCP_TOKEN_FILE` on both sides.
- Override the value with `BLENDER_AUTH_TOKEN` on both sides.
- The add-on creates the file with mode 0600 and creates a missing directory
  with mode 0700 on POSIX. A pre-existing override directory retains its mode.
- Rotate the file with Blender stopped, then start Blender again. The bridge
  reads the configured token for every request. An environment token takes
  precedence over the file.
- `BLENDER_MCP_ALLOW_NO_AUTH=1` disables authentication on both sides. Use it
  only for a trusted local process that cannot read the token file.

## Reporting a vulnerability

Do not open a public issue for an exploitable bug. Send a private report to
the maintainers with:

- affected version or commit;
- reproduction steps;
- impact;
- whether the issue requires a malicious MCP client, a local process, or a
  crafted asset.

We will acknowledge the report, prepare a fix, and publish an advisory after
users can update. Do not include real tokens or personal data in the report.

## Non-goals

- Protecting against a compromised local user account.
- Sandboxing Blender's Python interpreter against a user who explicitly
  enables `execute_code`.
- Guaranteeing that third-party importers are free of memory-safety bugs.
