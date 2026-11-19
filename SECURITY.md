# Security

## Status

The `v3.0.0-baseline` tag is a **development baseline, not a hardened
release**. This document describes the threat model and the mitigations that
v4 must implement. It does not certify the current code as safe.

The baseline is known to have open P0 issues: `execute_code` is unrestricted,
authentication is optional, the socket protocol has no message-size limit,
downloads accept provider-controlled URLs, and ZIP extraction is unsafe. See
the audit in the repository history and the migration plan.

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
| Confused deputy | The add-on has more privileges than the caller and executes a request on the caller's behalf. | The socket has no per-client authorization; any local client can call any tool. | Per-session token, capability scopes, explicit user consent for privileged operations. | Local user session compromise. |
| SSRF | A crafted asset URL or provider response points to `127.0.0.1`, link-local, metadata services or an internal host. | Provider URLs are followed without host or IP validation. | HTTPS-only allowlist, DNS resolution and private/link-local/loopback blocking, redirect re-validation, pinned IP per connection. | DNS rebinding needs pinned resolution; document residual risk. |
| Token theft | `BLENDER_AUTH_TOKEN` or the Sketchfab token is read from env, logs, process listings or a world-readable file. | Token is optional and passed in plaintext JSON; no file permissions policy. | Token file mode 0600, constant-time comparison, never log tokens, rotate on start, redact errors. | Same-user process can read the file. |
| Arbitrary code execution | `execute_code` calls `exec()` with full builtins. | Enabled by default and unauthenticated. | Disabled by default; explicit preference/env opt-in; structured refusal; no hidden execution path. | An opted-in user grants full Blender Python access. |
| Data exfiltration | A tool reads scene data, files or tokens and sends them to a remote host. | `execute_code` and download tools can read files and make network calls. | Output sandbox, no arbitrary file reads, network allowlist, audit log, user confirmation for exports. | A user-approved export can still leak data. |
| Destructive scene operations | `clear_scene`, `delete_object`, `boolean_operation`, `rollback_checkpoint` mutate or replace the scene. | No confirmation or dry-run. | `confirm` flag, dry-run preview, checkpoint before mutation, undo integration where possible. | Confirmed destructive calls still destroy data. |
| Malicious asset files | A `.blend`, `.glb`, texture or archive exploits the importer, contains a zip-slip path, or fills the disk. | `zipfile.extractall()` without validation; no size limits. | Safe extraction (resolve, reject `..`, absolute paths, symlinks), uncompressed-size and file-count caps, importer sandboxing where available. | Importer vulnerabilities remain. |
| Malicious paths | `export_scene`, checkpoint names or download IDs escape the output directory. | Arbitrary paths accepted; `uid`/`asset_id` interpolated into temp names. | Resolve and confine to `BLENDER_MCP_OUTPUT_DIR`; reject traversal and symlinks; sanitize IDs; extension allowlist. | A user-approved path outside the sandbox. |
| DNS rebinding | A hostname resolves to a public IP during validation and to a private IP at connect time. | No DNS validation at all. | Resolve once, reject private ranges, connect to the validated IP, re-validate redirects. | A compromised resolver or OS-level attack. |
| Supply chain | A compromised `mcp` package, Blender build, add-on zip or GitHub Action runs with the user's privileges. | `mcp==1.30.0` only in the README; no hashes, no pinned CI actions. | Pin dependencies and Actions by commit, publish hashes, sign releases, reproducible build, dependency review. | Upstream compromise before pinning. |

## Secure defaults for v4

- Authentication enabled by default with a per-install token file (0600).
- `execute_code` disabled unless explicitly enabled in add-on preferences or
  `BLENDER_MCP_ALLOW_EXECUTE_CODE=1`.
- Destructive tools require `confirm=true`; a dry-run response is returned
  otherwise.
- Output paths are confined to `BLENDER_MCP_OUTPUT_DIR`.
- Downloads are HTTPS-only, host-allowlisted, size-capped, and extracted with
  a safe ZIP routine.
- The bridge binds to loopback and refuses non-loopback hosts by default.
- Every privileged call is logged with a request ID and a redacted argument
  summary.

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
