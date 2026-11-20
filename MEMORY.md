# Blender MCP Pro maintenance notes

The final v4 audit began at `v4.0.0-alpha.4` on `audit/v4-final`.
Assembly updates preserve existing scene objects when a staged build raises.
Audit verdicts account for requested meshes and failed optional checks.
Capsule, torus and tube now use connected revolved profiles. Without bevels,
their envelopes use the requested X, Y and Z dimensions. Torus thickness
sets radial cross-section depth. Tube thickness sets wall depth.

The geometry gate still needs explicit solid containment and a support policy
for unparented parts. The existing `inside` constraint checks AABB
containment. Keep those limitations visible in any release decision.
