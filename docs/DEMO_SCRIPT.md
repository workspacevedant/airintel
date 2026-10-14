# AERO-OPS (SIH26250) — Master Judging Demo Script & Runbook

This runbook guides the demo operator through an exact, minute-by-minute presentation of the AERO-OPS system adhering to Section 15 of the Master Specification (`AERO_OPS_SIH26250_Master_Specification.pdf`).

---

## Pre-Flight Check (Before Speaking)

Run the pre-flight health check to verify all services are active and ready:

```bash
curl -i http://localhost:8000/health/
```

**Expected Response (HTTP 200 OK):**
```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "simulation": "ready (RUNNING)"
}
```

If needed, the demo is also mapped to `http://localhost:5008/health/`.

---

## Seeded Demo Credentials

| Role | Username | Password | Assigned Scope | Key Capabilities |
| :--- | :--- | :--- | :--- | :--- |
| **Airbase Commander** | `cmdr_vsingh` | `AeroOps@26250` | `AB-DEMO-01` (Ambala Fictional) | Base fleet (25 units), maintenance, readiness overrides, simulation control |
| **Squadron Leader** | `sqnldr_ajoshi` | `AeroOps@26250` | `SQ-DEMO-01` (No. 17 Golden Arrows) | Unit inbox, order acknowledgement, crew FDTL reporting |
| **Zonal Commander** | `aircmde_kmenon` | `AeroOps@26250` | `ZONE-DEMO-A` (Western Sector) | Multi-base oversight, aggregated readiness, feed health, read-only |

> [!NOTE]
> All operational data, coordinates, flight paths, and designations are **synthetic and fictional**. Fictional aircraft categories use generic designations: `Type-A Fighter`, `Type-B Multirole`, `Type-C Light Combat`, and `Recon UAV`.

---

## 7-Minute Minute-by-Minute Runbook

### Minute 0:00 – 0:45: Role-Based Authentication & Scope Isolation
1. **Open Browser**: Navigate to `http://localhost:8000/login/`.
2. **Log In as Airbase Commander**:
   - Username: `cmdr_vsingh`
   - Password: `AeroOps@26250`
   - **Observer Note**: Point out the active role indicator `Airbase Commander | Base: AB-DEMO-01` and the top persistent banner:
     `SYNTHETIC SIMULATION MODE — NON-OPERATIONAL DEMO (SIH26250)`.
3. **Demonstrate Scope Isolation**:
   - Airbase Commander sees the complete 25-aircraft inventory across all squadrons at Base `AB-DEMO-01`.
   - Now switch role to **Squadron Leader** (`sqnldr_ajoshi`) using the judging role-switch dropdown or login.
   - Point out that Squadron Leader sees **only** 12 aircraft assigned to `SQ-DEMO-01`. All other base aircraft are omitted.
   - Tampering demonstration: Attempting to access other squadrons or unauthorized POSTs returns HTTP 403 Forbidden.

---

### Minute 0:45 – 1:30: Common Operational Picture & Hybrid Radar
1. **Switch to Zonal Commander** (`aircmde_kmenon`):
   - Navigate to `http://localhost:8000/zonal/`.
   - **Observer Note**: Show aggregated status across multiple airbases (`AB-DEMO-01`, `AB-DEMO-02`) in `ZONE-DEMO-A`.
2. **Examine Map**:
   - Rendered using vendored Leaflet (offline-capable).
   - Shows fictional airbase coordinates, spatial boundary polygon of `ZONE-DEMO-A`, and sensor nodes (`SENSOR-DEMO-01`, `SENSOR-DEMO-02`, `SENSOR-DEMO-03`).
   - Dual clocks: Highlight the separation between **Simulated Scenario Time** and **Wall-Clock Time**.

---

### Minute 1:30 – 2:15: Deterministic Scenario Playback
1. **Switch Back to Airbase Commander** (`cmdr_vsingh`).
2. **Start Simulation**:
   - Click the green **"Start Simulation"** button on the Scenario Controls toolbar, or execute via terminal:
     ```bash
     curl -X POST http://localhost:8000/api/simulation/control/ \
       -H "Content-Type: application/json" \
       -d '{"action": "start", "scenario_code": "SCENARIO-BASELINE-01", "seed": 26250}'
     ```
3. **Observe Live Ingestion**:
   - Synthetic tracks and radar observations appear on the map and stream into the Event Centre.
   - Live updates arrive via Django Channels WebSocket (`/ws/events/`) with sub-2-second latency.
   - Each event contains the canonical Section 07 Event Envelope: `event_id`, `scenario_id`, `source_type`, `occurred_at`, `quality`, and `payload`.

---

### Minute 2:15 – 3:00: Fault Injection & Multi-Source Uncertainty
1. **Trigger Sensor Fault**:
   - In the Scenario Control panel, select sensor `SENSOR-DEMO-03` and click **"Inject Fault (Offline)"**, or execute:
     ```bash
     curl -X POST http://localhost:8000/api/simulation/control/ \
       -H "Content-Type: application/json" \
       -d '{"action": "inject_fault", "sensor_code": "SENSOR-DEMO-03", "health_state": "OFFLINE"}'
     ```
2. **Observe System Response**:
   - Radar map immediately flags `SENSOR-DEMO-03` in red (OFFLINE).
   - Sensor Feed Health indicator transitions from `LIVE` to `DEGRADED / STALE`.
   - Dependent tracks are flagged with uncertainty labels (`quality: degraded`).
   - Airbase readiness score dynamically recalculates.

---

### Minute 3:00 – 4:00: Equipment Maintenance & Append-Only Audit Trail
1. **Open Maintenance & Refit Module**:
   - Locate aircraft `SB-512` (Type-B Multirole).
   - Update its state from `AVAILABLE` to `MAINTENANCE` with note: `"Hydraulic actuator pressure drop detected during pre-flight check"`.
2. **Verify State Machine & Audit Trail**:
   - Status transitions strictly adhere to Section 05.5 state machine (`AVAILABLE -> MAINTENANCE -> INSPECTED -> AVAILABLE`).
   - Inspect the Audit Log table:
     - Shows actor: `cmdr_vsingh`
     - Action: `EQUIPMENT_STATUS_UPDATED`
     - Before: `AVAILABLE` | After: `MAINTENANCE`
     - Immutability: Database constraints prevent tampering or deleting audit records.

---

### Minute 4:00 – 5:00: AI/ML Suggestion Engine & Explainability
1. **Open Decision Support Panel**:
   - View Model A (7-day Unavailability Risk) and Model B (Option Scorer).
2. **Highlight Transparent Metrics**:
   - **Model A (Readiness XGBoost)**: ROC-AUC = 0.9032 (compared side-by-side with Logistic Regression baseline ROC-AUC = 0.9085).
   - **Model B (Option Scorer)**: NDCG@3 = 0.9978, ranking agreement = 99.42%.
3. **Hard Feasibility Constraints**:
   - Point out that **deterministic constraints override ML**:
     * Primary runway length >= required takeoff roll (2,400m for Type-B).
     * Airbase fuel reserve >= 150 MT minimum reserve threshold.
     * Crew Flight Duty Time Limitations (FDTL) <= 12 hours.
   - Infeasible options are filtered out *before* scoring.
4. **Advisory Disclaimer**:
   - Highlight the prominent UI label: `"SYNTHETIC, ADVISORY ONLY — Human decision required before operational action"`.

---

### Minute 5:00 – 6:00: Squadron Leader Orders Inbox & Crew Duty Workflow
1. **Switch to Squadron Leader** (`sqnldr_ajoshi`):
   - Navigate to Orders Inbox.
   - Locate high-priority directive `ORD-DEMO-0007` (`"Prepare standby patrol unit"`).
   - Click **"Acknowledge Directive"**. Status transitions from `PENDING` to `ACKNOWLEDGED` with timestamp and user ID.
2. **Submit Crew Duty Status**:
   - Open Crew Status tab.
   - Transition crew report from `DRAFT` -> `SUBMITTED`.
   - Demonstrate that duty hours exceeding 12 hours trigger automatic `REST_REQUIRED` lockout.

---

### Minute 6:00 – 7:00: Deterministic Replay & Reset
1. **Reset Simulation**:
   - Click the red **"Reset Simulation"** button, or execute:
     ```bash
     curl -X POST http://localhost:8000/api/simulation/control/ \
       -H "Content-Type: application/json" \
       -d '{"action": "reset", "scenario_code": "SCENARIO-BASELINE-01", "seed": 26250}'
     ```
2. **Verify Determinism**:
   - State returns to the exact baseline initial conditions.
   - Replaying produces the identical sequence of event IDs (`EVT-DEMO-26250-0001`, `0002`, `0003...`) with zero variance.

---

## Rapid Fallback Procedure (Under 10 Seconds)

If Docker Desktop crashes or is unavailable on the judging laptop:

```bash
# 1. Activate virtual environment
source .venv/bin/activate  # Or: .venv\Scripts\activate on Windows

# 2. Run local server with SQLite fallback
python manage.py runserver 8000
```

The system automatically detects the missing PostgreSQL/PostGIS connection and falls back to SQLite + InMemoryChannelLayer, allowing the full UI, RBAC, REST APIs, and simulation replay to run seamlessly.
