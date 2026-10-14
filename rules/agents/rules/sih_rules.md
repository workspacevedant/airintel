# AERO-OPS (SIH26250) Agent Rules
1. UI Aesthetic: Strictly preserve the NIC / GovTech Variant C compact 3-column layout (navy #002147/#0c2a5e, off-white #f4f5f7, sharp 1px-2px borders, native HTML radio/select inputs). Never introduce SaaS gradients, rounded cards, or Tailwind.
2. Architecture: Maintain strict separation across the three Django apps (`core`, `radar_simulation`, `suggestion`)[cite: 48, 62].
3. Fallbacks: If Redis, PostGIS, or the `.xgb` artifact fails during local startup, ensure the deterministic fallback and local spatial/polling fallbacks work without crashing the server[cite: 47, 55, 56].
4. Audit & RBAC: Every state mutation must write to `AuditLog` and enforce server-side role/scope checks[cite: 48, 50].