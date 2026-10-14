# AERO-OPS (SIH26250) — Judge Q&A Preparation & Technical Defense

This document details the ten most challenging questions a technical judge or defense evaluator could ask during the AERO-OPS evaluation, complete with precise source code citations, architectural rationale, and exact live demo actions that prove the answer.

---

### Q1: How do you prevent lower ranks or unauthorized users from viewing operational data or modifying other squadrons' assets?
- **Honest Technical Answer**:
  All access control is enforced **strictly on the server side** in `apps/core/permissions.py` and `apps/core/selectors.py`. The frontend never filters security boundaries.
  * When a request arrives, `apps/core/permissions.py:get_user_scope()` inspects the user's active `RoleAssignment` in the database.
  * Every query selector (e.g. `get_visible_equipment`, `get_visible_orders`) applies strict database filtering (`filter(airbase__in=..., squadron__in=...)`).
  * In `apps/core/views.py:api_equipment_status_update_view` (lines 530-580), if a Squadron Leader attempts to mutate equipment outside their assigned squadron, the request is rejected with `HTTP 403 Forbidden` and audited via `log_security_denial()`.
- **Live Demo Proof**:
  Log in as Squadron Leader `sqnldr_ajoshi` (assigned to `SQ-DEMO-01`). The UI renders only 12 aircraft. Execute a curl command attempting to change aircraft `EQ-DEMO-014` (assigned to `SQ-DEMO-02`) -> Immediate `403 Forbidden` with an entry logged in `AuditLog`.

---

### Q2: Does your AI/ML model autonomously dispatch aircraft or make operational decisions?
- **Honest Technical Answer**:
  **No.** AERO-OPS strictly enforces human-in-the-loop decision support. In `apps/suggestion/predict.py`:
  * Every recommendation is advisory (`"synthetic, advisory only"` label).
  * Hard deterministic physical constraints are evaluated **first** before ML inference:
    1. Runway length check (`apps/suggestion/predict.py:REQUIRED_RUNWAY_M_BY_CATEGORY`).
    2. Fuel reserve check (minimum 150 MT reserve required).
    3. Crew duty hours check (FDTL <= 12 hours).
  * If any hard constraint fails, the option is flagged `feasible: false` and the ML model cannot override it.
- **Live Demo Proof**:
  Open the Suggestion Panel. Show the hard constraint breakdown and verify that infeasible options (e.g. Type-B with 2400m requirement on an 1800m auxiliary strip) are marked ineligible with clear human-readable reason codes.

---

### Q3: What happens if your XGBoost model file is corrupted, missing, or receives malformed features?
- **Honest Technical Answer**:
  The system uses a **graceful degradation and resilient fallback architecture**:
  * In `apps/suggestion/features.py:validate_feature_vector()`, all 6 features (`utilization_ratio_7d`, `flight_hours_since_last_phase_check`, `open_maintenance_alerts_count`, `component_cycles_to_overhaul_pct`, `airbase_hangar_occupancy_ratio`, `environmental_corrosion_index`) are validated for type, nullity, and range `[0.0, 1.0]` or non-negativity.
  * In `apps/suggestion/predict.py:predict_equipment_readiness()`, if the XGBoost artifact fails checksum validation or is missing, the engine automatically falls back to `deterministic_readiness_baseline()` (`FALLBACK_MODEL_VERSION = "deterministic-fallback-v1"`), records `fallback_used: true`, and returns valid predictions without throwing an unhandled exception or 500 error.
- **Live Demo Proof**:
  Run `curl http://localhost:8000/api/suggestions/?force_fallback=true` -> The response returns 200 OK with `model_version: "deterministic-fallback-v1"` and explicit advisory reason codes.

---

### Q4: How do you handle high-throughput radar feeds and prevent duplicate sensor packets from creating duplicate alerts?
- **Honest Technical Answer**:
  Section 07 canonical Event Envelope and database idempotency in `apps/radar_simulation/engine.py:ingest_observation()` (lines 600-645).
  * Each incoming packet has a synthetic `event_id` and unique `idempotency_key = f"idem-{event_id}"`.
  * The database performs an atomic `get_or_create(idempotency_key=...)`.
  * If an event with the same ID arrives twice, `created` evaluates to `False`, the duplicate packet is idempotently ignored (`duplicate_ignored: true`), and no duplicate WebSocket broadcasts or alerts are created.
- **Live Demo Proof**:
  Run automated test `apps.core.tests.test_phase5_simulation_workflows.Phase5SimulationWorkflowsTests.test_s06_04_event_store_idempotency_ignores_duplicates` -> 100% pass verification of zero duplicate alerts.

---

### Q5: How do you guarantee WebSocket security and prevent a client from subscribing to another airbase's live radar stream?
- **Honest Technical Answer**:
  WebSocket connections in `apps/radar_simulation/consumers.py:EventConsumer` use Django session authentication:
  * Anonymous WebSocket connections are rejected immediately during handshake with code `4403`.
  * Client cannot request arbitrary channels. Channels groups are **strictly derived on the server** in `apps/core/permissions.py:get_authorised_ws_groups(user)`.
  * An Airbase Commander only receives `airbase_{code}`. A Squadron Leader only receives `squadron_{code}`. If a client attempts to inject an unauthorized group string, `EventConsumer.receive_json()` blocks it and logs an audit security event.
- **Live Demo Proof**:
  Run `docker compose exec -T web python manage.py test apps.core.tests.test_phase7_websocket` -> Tests verify that unauthorized group subscriptions are blocked and cross-scope event leakage is impossible.

---

### Q6: Can an administrator or compromised account modify or delete the audit logs to cover their tracks?
- **Honest Technical Answer**:
  **No.** `AuditLog` records are immutable at the ORM and database level in `apps/core/models.py:AuditLog`:
  * `AuditLog.save()`: Overridden to raise `django.core.exceptions.ValidationError("AuditLog records are immutable and cannot be modified.")` if attempting to update an existing record (`self.pk is not None`).
  * `AuditLog.delete()`: Overridden to raise `django.core.exceptions.PermissionDenied("AuditLog records cannot be deleted.")`.
- **Live Demo Proof**:
  Run `test_phase7_database_and_spatial.Phase7DatabaseAndSpatialTests.test_s14_08_audit_log_immutability_save_and_delete_tampering_blocked` -> Throws `ValidationError` on save tampering and `PermissionDenied` on deletion attempts.

---

### Q7: How does the system handle sensor failures, communication blackouts, or degraded GPS feeds?
- **Honest Technical Answer**:
  The system includes an integrated Fault Injector in `apps/radar_simulation/engine.py:inject_sensor_fault()`:
  * When a synthetic radar sensor (e.g. `SENSOR-DEMO-03`) goes offline or experiences data latency, its health state transitions to `OFFLINE` or `STALE`.
  * The feed status transitions from `LIVE` to `DEGRADED`.
  * Associated tracks and synthetic observations are marked with `quality: degraded`.
  * Airbase operational readiness dynamically recalculates to alert commanders to lost surveillance coverage.
- **Live Demo Proof**:
  Trigger fault injection via UI or `POST /api/simulation/control/` with `{"action": "inject_fault", "sensor_code": "SENSOR-DEMO-03", "health_state": "OFFLINE"}` -> Sensor turns red on map, feed health updates, and readiness score drops.

---

### Q8: How does the system prevent crew exhaustion and enforce Flight Duty Time Limitations (FDTL)?
- **Honest Technical Answer**:
  Enforced via the Crew Duty State Machine in `apps/core/models.py:CrewReadiness` and `apps/core/services.py:update_crew_duty_state()`:
  * Duty states: `READY`, `ON_DUTY`, `REST_REQUIRED`, `TRAINING`, `UNAVAILABLE`.
  * When cumulative duty hours exceed 12 hours, the state machine triggers an automatic lockout to `REST_REQUIRED`.
  * Transition from `REST_REQUIRED` back to `READY` is strictly blocked until mandatory rest is logged, preventing unsafe pilot dispatch.
- **Live Demo Proof**:
  Update a crew unit's duty hours to 13.0 hours -> System automatically locks status to `REST_REQUIRED` and rejects any manual assignment.

---

### Q9: Can this demonstration be deterministically replayed and verified, or does it depend on random generation?
- **Honest Technical Answer**:
  The entire simulation is **100% deterministic and reproducible**:
  * Scenarios are seeded with fixed seed `26250` (`apps/radar_simulation/scenarios.py:DEFAULT_SIMULATION_SEED`).
  * The management command `seed_demo_data` exports initial baseline states to `fixtures/demo_seed.json`.
  * Calling `POST /api/simulation/control/` with `action: "reset"` restores the database to the clean seed baseline and generates the exact same sequence of event IDs (`EVT-DEMO-26250-0001`, `0002`...) on every execution.
- **Live Demo Proof**:
  Run the Section 15 Runbook E2E test `test_phase7_runbook_e2e.py` -> Executes the full 8-step runbook and resets cleanly.

---

### Q10: How does AERO-OPS comply with military security and defense classification guidelines regarding real weapons and platforms?
- **Honest Technical Answer**:
  AERO-OPS strictly follows the **Scope Guard**:
  * All active operational platforms utilize generic synthetic designations (`Type-A Fighter`, `Type-B Multirole`, `Type-C Light Combat`, `Recon UAV`).
  * Airbase coordinates and flight tracks are invented synthetic data points within fictional operational zones (`ZONE-DEMO-A`).
  * Real platform tables (`Weapon`, `AdversaryAircraft`, `AircraftSpecification`) are inert reference tables only. They are completely decoupled from all views, recommendation engines, and operational workflows.
  * Every page clearly renders the persistent watermark: `SYNTHETIC SIMULATION MODE — NON-OPERATIONAL DEMO (SIH26250)`.
- **Live Demo Proof**:
  Inspect `apps/suggestion/predict.py` and verify that no targeting, weapon allocation, or real combat calculations exist.
