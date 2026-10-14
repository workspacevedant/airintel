"""
Deterministic Scenario Registry for AERO-OPS Hybrid Radar Simulator (Section 06 & Appendix A).
Fixed seed 26250 guarantees reproducible sequence playback during SIH judging.
"""
from typing import Dict, Any, List

DEFAULT_SIMULATION_SEED = 26250

SCENARIO_REGISTRY: Dict[str, Dict[str, Any]] = {
    "SCENARIO-BASELINE-01": {
        "code": "SCENARIO-BASELINE-01",
        "name": "Sector 7 Dynamic Readiness & Sensor Degradation Drill",
        "version": "1.0",
        "seed": DEFAULT_SIMULATION_SEED,
        "zone_code": "ZONE-DEMO-A",
        "airbase_code": "AB-DEMO-01",
        "sequence": [
            {
                "seq": 1,
                "event_id": "evt-demo-000101",
                "event_type": "TRACK_UPDATED",
                "source_type": "synthetic_sensor",
                "source_id": "SENSOR-DEMO-01",
                "track_code": "SYNTH-TRACK-01",
                "callsign_label": "SYNTH-TRACK-01 (Synthetic High-Altitude Profile)",
                "zone_code": "ZONE-DEMO-A",
                "lat": 31.1800,
                "lon": 77.1200,
                "bearing": 215.0,
                "range_km": 94.5,
                "altitude_m": 11200.0,
                "speed_kts": 540.0,
                "quality": "simulated",
                "track_state": "UNDER_REVIEW",
                "create_alert": False,
            },
            {
                "seq": 2,
                "event_id": "evt-demo-000104",
                "event_type": "TRACK_UPDATED",
                "source_type": "synthetic_sensor",
                "source_id": "SENSOR-DEMO-03",
                "track_code": "TRACK-DEMO-12",
                "callsign_label": "TRACK-DEMO-12 (Synthetic Perimeter Buffer Track)",
                "zone_code": "ZONE-DEMO-B",
                "lat": 30.8800,
                "lon": 78.0500,
                "bearing": 260.0,
                "range_km": 68.0,
                "altitude_m": 7800.0,
                "speed_kts": 430.0,
                "quality": "simulated",
                "track_state": "UNDER_REVIEW",
                "create_alert": False,
            },
            {
                "seq": 3,
                "event_id": "evt-demo-000105",
                "event_type": "TRACK_APPROACHING_SECTOR",
                "source_type": "synthetic_sensor",
                "source_id": "SENSOR-DEMO-01",
                "track_code": "SYNTH-TRACK-01",
                "callsign_label": "SYNTH-TRACK-01 (Synthetic High-Altitude Profile)",
                "zone_code": "ZONE-DEMO-A",
                "lat": 30.9800,
                "lon": 76.9900,
                "bearing": 212.0,
                "range_km": 72.0,
                "altitude_m": 10900.0,
                "speed_kts": 555.0,
                "quality": "simulated",
                "track_state": "ACTIVE",
                "create_alert": True,
                "alert_severity": "HIGH",
                "alert_title": "Sector 7 Track SYNTH-TRACK-01 Approaching — Review Order ORD-0092",
                "alert_summary": "Synthetic track SYNTH-TRACK-01 closed range to 72.0 km on bearing 212°. Verify readiness pair RF-102 / RF-104.",
            },
            {
                "seq": 4,
                "event_id": "evt-demo-000106",
                "event_type": "SENSOR_HEALTH_DEGRADED",
                "source_type": "synthetic_sensor",
                "source_id": "SENSOR-DEMO-03",
                "track_code": "TRACK-DEMO-12",
                "callsign_label": "TRACK-DEMO-12 (Uncertain — Stale Feed)",
                "zone_code": "ZONE-DEMO-B",
                "lat": 30.8750,
                "lon": 78.0100,
                "bearing": 258.0,
                "range_km": 66.2,
                "altitude_m": 7800.0,
                "speed_kts": 430.0,
                "quality": "uncertain",
                "track_state": "STALE",
                "sensor_health": "STALE",
                "create_alert": True,
                "alert_severity": "WARNING",
                "alert_title": "Synthetic Sensor Feed Degradation: SENSOR-DEMO-03 STALE",
                "alert_summary": "SENSOR-DEMO-03 telemetry heartbeat missed; TRACK-DEMO-12 marked UNCERTAIN/STALE and excluded from high-confidence fusion.",
            },
        ],
    }
}


def get_scenario_definition(code_or_alias: str) -> Dict[str, Any]:
    normalized = (code_or_alias or "SCENARIO-BASELINE-01").upper().strip()
    if normalized in ("BASELINE", "BASELINE-01", "DEFAULT"):
        normalized = "SCENARIO-BASELINE-01"
    return SCENARIO_REGISTRY.get(normalized, SCENARIO_REGISTRY["SCENARIO-BASELINE-01"])
