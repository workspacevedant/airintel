# AERO-OPS (SIH26250) — Dynamic Air Operations & Resource Optimisation

A human-in-the-loop, simulation-first decision-support platform designed for the Smart India Hackathon (SIH26250).

> **Safety and Scope Note**: This specification and software describe a synthetic, non-operational demonstration. It intentionally does not define real-world weapon engagement procedures, tactical interception recommendations, classified sensor interfaces, or operational targeting logic.

---

## 1. System Architecture & Tech Stack

- **Application Style**: Django 5.0.8 Modular Monolith (3 apps: `apps.core`, `apps.radar_simulation`, `apps.suggestion`)
- **Frontend**: Django Templates + Utilitarian NIC/GovTech Variant C ("Compact Multi-Section Layout" V3), Vanilla JavaScript, Leaflet for synthetic map layers
- **Database & Spatial**: PostgreSQL 16 + PostGIS 3.4 (EPSG:4326 geometry)
- **Real-Time Delivery**: Django Channels 4.1 + Redis 7.2 (with automated HTTP polling fallback)
- **Machine Learning**: XGBoost 2.1.1 + Scikit-Learn 1.5.1
  - **Model A**: 7-day equipment unavailability probability
  - **Model B**: Generic operational dispatch alternative scoring
  - **Deterministic Gate**: Hard feasibility checks (FDTL crew rest, runway clearance, fuel reserves) always override ML predictions.
- **Audit & Security**: Strict server-side RBAC, object-level scope isolation (Airbase/Squadron/Zone), append-only `AuditLog`.

---

## 2. Quick Start with Docker Compose (Recommended)

To run the complete platform with PostGIS, Redis, ASGI Daphne server, and seeded demonstration data:

```bash
# 1. Clone/navigate to project directory
cd aero_ops

# 2. Build and start containers in background
docker compose up --build -d

# 3. Access the portal in your browser:
# http://localhost:8000/ or http://localhost:5008/
```

The Docker container runs migrations, executes `python manage.py seed_demo_data`, and starts Daphne on port 8000 (also exposed on port 5008 to match judging environments).

---

## 3. Seeded Demo Accounts (Role-Based Access Control)

| Role | Username | Password | Assigned Scope | Key Capabilities |
| :--- | :--- | :--- | :--- | :--- |
| **Airbase Commander** | `cmdr_vsingh` | `AeroOps@26250` | Avalon Forward Base (`AB-DEMO-01`) | Full airbase overview, readiness override, simulation control, acknowledge orders |
| **Squadron Leader** | `sqldr_sharma` | `AeroOps@26250` | No. 17 Squadron (`SQ-DEMO-01`) | Assigned squadron equipment & crew roster, acknowledge orders (Restricted from cross-base/zonal) |
| **Zonal Commander** | `zonal_knair` | `AeroOps@26250` | Sector 7 Forward Zone (`ZONE-DEMO-A`) | Cross-airbase aggregated view, zone-level sensor feeds & directives |

> **1-Click Switching**: Use the "Switch Demo Account" dropdown in the header to instantaneously switch between accounts during judging.

---

## 4. 7-Minute SIH Judge Demonstration Runbook

| Time | Action | Expected Application Behavior |
| :--- | :--- | :--- |
| **0:00–0:45** | Switch between seeded demo accounts | Demonstrates strict scope isolation and role-specific dashboard views. |
| **0:45–1:30** | Open Zonal Commander view (`/zonal/`) | Shows Sector 7 cross-airbase summary, radar nodes, and freshness indicators. |
| **1:30–2:15** | Click `[1. Start Baseline Scenario]` | Synthetic sensor events appear with deterministic seed `26250` and visible `SIMULATION MODE` banner. |
| **2:15–3:00** | Click `[2. Inject Sensor-03 Outage]` | `SENSOR-DEMO-03` goes `OFFLINE`; affected track `TRACK-DEMO-12` is flagged `STALE`. |
| **3:00–4:00** | Open Maintenance/Readiness View | Update equipment status (`SB-512` &rarr; `MAINTENANCE`); audit entry is logged and readiness recalculates. |
| **4:00–5:00** | Review Suggestion Panel | Shows explainable XGBoost score (`0.73`) vs deterministic baseline (`0.68`), reason codes, and FDTL block. |
| **5:00–6:00** | Open Squadron Leader Order Inbox | Acknowledge order `ORD-DEMO-0007`; audit log records actor and timestamp. |
| **6:00–7:00** | Click `[4. Reset Demo Seed 26250]` | Hard reset to clean fixture state for reproducible judging replay. |

---

## 5. Management Commands

- `python manage.py seed_demo_data [--reset]` — Seeds the deterministic demonstration dataset and exports `fixtures/demo_seed.json`.
- `python manage.py run_simulation --scenario baseline --seed 26250` — Runs synthetic scenario engine from CLI.
- `python manage.py train_readiness_model --seed 26250` — Trains and evaluates Model A and Model B artifacts to `ml_artifacts/`.
