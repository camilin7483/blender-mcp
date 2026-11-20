# Blender MCP Pro maintenance notes

The final v4 audit began at `v4.0.0-alpha.4` on `audit/v4-final`.
Assembly updates preserve existing scene objects when a staged build raises.
Audit verdicts account for requested meshes and failed optional checks.
Capsule, torus and tube now use connected revolved profiles. Without bevels,
their envelopes use the requested X, Y and Z dimensions. Torus thickness
sets radial cross-section depth. Tube thickness sets wall depth.

The independent audit added evaluated solid containment and support tracing.
See the [release checklist](docs/release-checklist.md) for the current coverage
and outstanding stable-release checks.

The alpha.2 build preserves native automatic skinning and binds on the
base character cage before restoring subdivision. The PELAGOS 07 and NEREID
07 showcase scenes are reproducible in background Blender. Linux CI reopens
their checked-in projects and exercises the authenticated socket from the
installed extension on both Blender versions.

The public tool reference and JSON catalog come from the local FastMCP
registry. Run `python scripts/generate_tool_reference.py` after changing a
tool, schema or profile. CI checks both outputs.
