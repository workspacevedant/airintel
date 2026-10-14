"""
Hybrid Radar Simulation Engine for AERO-OPS (SIH26250).
Implements Section 06 (Radar simulation design) & Section 07 (Shared Event Envelope & Idempotency).
Supports deterministic scenario playback (seed 26250) + live synthetic event generation,
plus start, pause, resume, reset, step, and inject_fault controls.
"""
import random
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from apps.core.models import Airbase, Alert, AuditLog, Event, Notification, User, Zone
from apps.core.services import broadcast_scoped_ws_event, recalculate_airbase_readiness
from apps.radar_simulation.models import (
    Scenario,
    SensorNode,
    SensorObservation,
    SimulationRun,
    Track,
)
from apps.radar_simulation.scenarios import DEFAULT_SIMULATION_SEED, get_scenario_definition


def build_event_envelope(
    *,
    event_id: str,
    scenario_id: str,
    source_type: str,
    source_id: str,
    event_type: str,
    occurred_at: Optional[Any] = None,
    quality: str = "simulated",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Constructs the canonical shared Event Envelope defined in Section 07 of the Master Specification.
    """
    ts = (occurred_at or timezone.now()).isoformat()
    return {
        "event_id": event_id,
        "scenario_id": scenario_id,
        "source_type": source_type,
        "source_id": source_id,
        "event_type": event_type,
        "occurred_at": ts,
        "received_at": timezone.now().isoformat(),
        "quality": quality,
        "payload": payload or {},
    }


class HybridRadarEngine:
    """
    Deterministic & live synthetic radar simulator (seed 26250).
    Persists observations, tracks, events, and alerts idempotently before broadcasting via Channels.
    """

    def __init__(self, scenario_code: str = "SCENARIO-BASELINE-01", seed: int = DEFAULT_SIMULATION_SEED):
        self.scenario_def = get_scenario_definition(scenario_code)
        self.scenario_code = self.scenario_def["code"]
        self.seed = int(seed or self.scenario_def.get("seed", DEFAULT_SIMULATION_SEED))

    def get_or_create_scenario_and_run(self, actor: Optional[User] = None) -> SimulationRun:
        scenario, _ = Scenario.objects.get_or_create(
            code=self.scenario_code,
            defaults={
                "name": self.scenario_def["name"],
                "version": self.scenario_def["version"],
                "seed": self.seed,
                "status": Scenario.ScenarioStatus.ACTIVE,
                "configuration": self.scenario_def,
                "is_demo": True,
            },
        )
        run = (
            SimulationRun.objects.filter(scenario=scenario)
            .order_by("-started_at")
            .first()
        )
        if not run:
            run = SimulationRun.objects.create(
                run_code=f"RUN-DEMO-{self.seed}-01",
                scenario=scenario,
                started_at=timezone.now(),
                simulated_clock=timezone.now(),
                state=SimulationRun.RunState.RUNNING,
                speed=1.0,
                seed=self.seed,
                current_sequence=0,
                last_heartbeat_at=timezone.now(),
                initiated_by=actor,
            )
        return run

    @transaction.atomic
    def control(
        self,
        *,
        action: str,
        actor: Optional[User] = None,
        sensor_code: str = "SENSOR-DEMO-03",
        fault_state: str = "OFFLINE",
    ) -> Dict[str, Any]:
        """
        Execute simulator control commands: start, pause, resume, reset, step, inject_fault.
        Audits every control invocation (Section 06, 10 & 11).
        """
        action_clean = str(action).lower().strip()
        run = self.get_or_create_scenario_and_run(actor=actor)
        old_state = run.state
        now = timezone.now()
        result_meta: Dict[str, Any] = {}

        if action_clean == "start":
            run.state = SimulationRun.RunState.RUNNING
            run.last_heartbeat_at = now
            run.save()
            step_data = self.step_next(run=run, actor=actor)
            result_meta["step"] = step_data

        elif action_clean == "pause":
            run.state = SimulationRun.RunState.PAUSED
            run.last_heartbeat_at = now
            run.save()

        elif action_clean == "resume":
            run.state = SimulationRun.RunState.RUNNING
            run.last_heartbeat_at = now
            run.save()

        elif action_clean == "step":
            run.state = SimulationRun.RunState.RUNNING
            run.last_heartbeat_at = now
            run.save()
            result_meta["step"] = self.step_next(run=run, actor=actor)

        elif action_clean == "inject_fault":
            result_meta["fault"] = self.inject_sensor_fault(
                run=run,
                sensor_code=sensor_code,
                health_state=fault_state,
                actor=actor,
            )

        elif action_clean == "reset":
            result_meta["reset"] = self.reset_scenario(run=run, actor=actor)
            run.refresh_from_db()

        else:
            raise ValueError(
                f"Unsupported simulation control action '{action}'. "
                "Allowed: start, pause, resume, step, inject_fault, reset."
            )

        AuditLog.objects.create(
            actor=actor,
            action=f"SIMULATION_CONTROL_{action_clean.upper()}",
            object_type="SimulationRun",
            object_id=run.run_code,
            before={"state": old_state, "sequence": run.current_sequence},
            after={
                "state": run.state,
                "sequence": run.current_sequence,
                "seed": run.seed,
                "meta": result_meta,
            },
            source="radar_simulation.engine",
        )

        groups = ["zone_ZONE-DEMO-A", "zone_ZONE-DEMO-B", "airbase_AB-DEMO-01"]
        transaction.on_commit(
            lambda: broadcast_scoped_ws_event(
                groups=groups,
                message_type="simulation.status",
                payload={
                    "run_code": run.run_code,
                    "scenario_code": run.scenario.code,
                    "action": action_clean,
                    "state": run.state,
                    "seed": run.seed,
                    "current_sequence": run.current_sequence,
                    "simulated_clock": run.simulated_clock.isoformat(),
                    "last_heartbeat_at": run.last_heartbeat_at.isoformat(),
                    "details": result_meta,
                },
            )
        )

        return {
            "run_code": run.run_code,
            "scenario_code": run.scenario.code,
            "action": action_clean,
            "state": run.state,
            "seed": run.seed,
            "current_sequence": run.current_sequence,
            "simulated_clock": run.simulated_clock.isoformat(),
            "last_heartbeat_at": run.last_heartbeat_at.isoformat(),
            **result_meta,
        }

    @transaction.atomic
    def step_next(self, *, run: SimulationRun, actor: Optional[User] = None) -> Dict[str, Any]:
        """
        Advances the simulation by one deterministic step from the scripted sequence,
        or generates a deterministic seeded synthetic update when past scripted steps (hybrid mode).
        Enforces strict idempotency on event_id and idempotency_key (Section 06 & 07).
        """
        sequence_list = self.scenario_def.get("sequence", [])
        next_seq = run.current_sequence + 1
        now = timezone.now()
        sim_time = run.simulated_clock + timedelta(seconds=30)

        scripted_step = next((s for s in sequence_list if s["seq"] == next_seq), None)

        if scripted_step:
            event_id = scripted_step["event_id"]
            event_type = scripted_step["event_type"]
            source_id = scripted_step["source_id"]
            track_code = scripted_step["track_code"]
            callsign_label = scripted_step["callsign_label"]
            zone_code = scripted_step["zone_code"]
            lat = float(scripted_step["lat"])
            lon = float(scripted_step["lon"])
            bearing = float(scripted_step["bearing"])
            range_km = float(scripted_step["range_km"])
            altitude_m = float(scripted_step["altitude_m"])
            speed_kts = float(scripted_step["speed_kts"])
            quality = scripted_step["quality"]
            track_state = scripted_step["track_state"]
            sensor_health = scripted_step.get("sensor_health")
            create_alert = bool(scripted_step.get("create_alert", False))
            alert_title = scripted_step.get("alert_title", "")
            alert_summary = scripted_step.get("alert_summary", "")
            alert_severity = scripted_step.get("alert_severity", "WARNING")
        else:
            # Hybrid live deterministic generator seeded by (seed + sequence_num)
            rng = random.Random(self.seed + next_seq)
            event_id = f"evt-demo-{self.seed}-{next_seq:04d}"
            event_type = "TRACK_UPDATED"
            source_id = "SENSOR-DEMO-01"
            track_code = "H-01 J-20"
            callsign_label = "H-01 J-20 (Synthetic High-Altitude Profile)"
            zone_code = "ZONE-DEMO-A"
            lat = round(30.9500 + rng.uniform(-0.08, 0.08), 4)
            lon = round(76.9500 + rng.uniform(-0.08, 0.08), 4)
            bearing = round((210.0 + rng.uniform(-8.0, 8.0)) % 360.0, 1)
            range_km = round(max(35.0, 72.0 - (next_seq - 3) * 2.5 + rng.uniform(-1.5, 1.5)), 1)
            altitude_m = 10800.0
            speed_kts = 545.0
            quality = "simulated"
            track_state = "ACTIVE"
            sensor_health = None
            create_alert = False
            alert_title = ""
            alert_summary = ""
            alert_severity = "INFO"

        zone = Zone.objects.filter(code=zone_code).first() or Zone.objects.first()
        sensor = SensorNode.objects.filter(fictional_code=source_id).first()
        if sensor:
            if sensor_health:
                sensor.health_state = sensor_health
            sensor.last_seen_at = now
            sensor.save()

        track, _ = Track.objects.update_or_create(
            run=run,
            fictional_track_code=track_code,
            defaults={
                "callsign_label": callsign_label,
                "state": track_state,
                "last_position": Point(lon, lat, srid=4326),
                "bearing": bearing,
                "range_km": range_km,
                "altitude_m": altitude_m,
                "speed_kts": speed_kts,
                "quality": quality,
                "source_sensor": sensor,
                "zone": zone,
                "last_seen_at": now,
            },
        )

        obs_idem_key = f"obs-{self.seed}-{run.run_code}-seq{next_seq:04d}"
        if sensor and not SensorObservation.objects.filter(idempotency_key=obs_idem_key).exists():
            SensorObservation.objects.create(
                run=run,
                sensor=sensor,
                track=track,
                sequence_num=next_seq,
                observed_at=sim_time,
                position=Point(lon, lat, srid=4326),
                bearing=bearing,
                range_km=range_km,
                quality=quality,
                payload={
                    "fictional_track_code": track_code,
                    "zone_ref": zone.code if zone else zone_code,
                    "state": track_state.lower(),
                },
                idempotency_key=obs_idem_key,
            )

        envelope = build_event_envelope(
            event_id=event_id,
            scenario_id=self.scenario_code,
            source_type="synthetic_sensor",
            source_id=source_id,
            event_type=event_type,
            occurred_at=sim_time,
            quality=quality,
            payload={
                "track_ref": track_code,
                "zone_ref": zone.code if zone else zone_code,
                "state": track_state.lower(),
                "bearing": bearing,
                "range_km": range_km,
                "lat": lat,
                "lon": lon,
            },
        )

        idem_key = f"idem-{event_id}"
        event_obj, evt_created = Event.objects.get_or_create(
            idempotency_key=idem_key,
            defaults={
                "event_id": event_id,
                "scenario_id": self.scenario_code,
                "event_type": event_type,
                "source_type": "synthetic_sensor",
                "source_id": source_id,
                "occurred_at": sim_time,
                "received_at": now,
                "quality": quality,
                "payload": envelope["payload"],
            },
        )

        alert_obj = None
        if create_alert and evt_created:
            airbase = Airbase.objects.filter(code="AB-DEMO-01").first()
            alert_obj = Alert.objects.create(
                event=event_obj,
                severity=alert_severity,
                zone=zone,
                airbase=airbase,
                title=alert_title,
                summary=alert_summary,
                status=Alert.AlertStatus.NEW,
                transition_history=[
                    {
                        "actor": "HYBRID_SIMULATOR",
                        "timestamp": now.isoformat(),
                        "previous_state": None,
                        "new_state": "NEW",
                        "reason": f"Triggered by {event_id} (seq {next_seq}).",
                    }
                ],
            )

        run.current_sequence = next_seq
        run.simulated_clock = sim_time
        run.last_heartbeat_at = now
        run.save()

        groups = [f"zone_{zone.code}" if zone else "zone_ZONE-DEMO-A", "airbase_AB-DEMO-01"]

        def _publish():
            broadcast_scoped_ws_event(
                groups=groups,
                message_type="event.created" if evt_created else "event.updated",
                payload={
                    **envelope,
                    "sequence_num": next_seq,
                    "duplicate_ignored": not evt_created,
                },
            )
            if alert_obj:
                broadcast_scoped_ws_event(
                    groups=groups,
                    message_type="alert.created",
                    payload={
                        "alert_id": str(alert_obj.id),
                        "event_id": event_obj.event_id,
                        "severity": alert_obj.severity,
                        "title": alert_obj.title,
                        "summary": alert_obj.summary,
                        "status": alert_obj.status,
                    },
                )

        transaction.on_commit(_publish)

        return {
            "sequence_num": next_seq,
            "event_envelope": envelope,
            "idempotent_created": evt_created,
            "alert_created": str(alert_obj.id) if alert_obj else None,
        }

    @transaction.atomic
    def inject_sensor_fault(
        self,
        *,
        run: SimulationRun,
        sensor_code: str = "SENSOR-DEMO-03",
        health_state: str = "OFFLINE",
        actor: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Forces a synthetic sensor (default SENSOR-DEMO-03) into STALE or OFFLINE state
        to demonstrate multi-source data uncertainty, marks dependent tracks as STALE/uncertain,
        recalculates airbase readiness, and broadcasts live warnings (Section 06, 07 & 15).
        """
        now = timezone.now()
        state_clean = str(health_state).upper().strip()
        if state_clean not in {c[0] for c in SensorNode.HealthState.choices}:
            state_clean = SensorNode.HealthState.OFFLINE

        sensor = SensorNode.objects.filter(fictional_code=sensor_code).first()
        if not sensor:
            raise ValueError(f"Synthetic sensor '{sensor_code}' not found.")

        old_health = sensor.health_state
        sensor.health_state = state_clean
        sensor.save()

        # Mark tracks reported by this sensor as uncertain/STALE (Section 06)
        affected_tracks = list(Track.objects.filter(run=run, source_sensor=sensor))
        for t in affected_tracks:
            t.state = Track.TrackState.STALE
            t.quality = Track.TrackQuality.UNCERTAIN
            t.callsign_label = f"{t.fictional_track_code} (UNCERTAIN — {sensor.fictional_code} {state_clean})"
            t.save()

        event_id = f"evt-fault-{sensor.fictional_code.lower()}-{state_clean.lower()}"
        idem_key = f"idem-{event_id}-seq{run.current_sequence}"
        envelope = build_event_envelope(
            event_id=event_id,
            scenario_id=self.scenario_code,
            source_type="synthetic_sensor",
            source_id=sensor.fictional_code,
            event_type="SENSOR_OUTAGE_INJECTED",
            occurred_at=now,
            quality="uncertain",
            payload={
                "sensor_code": sensor.fictional_code,
                "before_health": old_health,
                "after_health": state_clean,
                "affected_tracks": [t.fictional_track_code for t in affected_tracks],
                "zone_ref": sensor.zone.code if sensor.zone else "ZONE-DEMO-B",
                "uncertainty_notice": "Feed is stale/offline; tracks from this node are labelled uncertain and not treated as current.",
            },
        )

        event_obj, created = Event.objects.get_or_create(
            idempotency_key=idem_key,
            defaults={
                "event_id": f"{event_id}-{uuid.uuid4().hex[:4]}" if Event.objects.filter(event_id=event_id).exists() else event_id,
                "scenario_id": self.scenario_code,
                "event_type": "SENSOR_OUTAGE_INJECTED",
                "source_type": "synthetic_sensor",
                "source_id": sensor.fictional_code,
                "occurred_at": now,
                "received_at": now,
                "quality": "uncertain",
                "payload": envelope["payload"],
            },
        )

        airbase = Airbase.objects.filter(code="AB-DEMO-01").first()
        alert_obj = Alert.objects.create(
            event=event_obj,
            severity=Alert.Severity.WARNING if state_clean == "STALE" else Alert.Severity.HIGH,
            zone=sensor.zone or Zone.objects.filter(code="ZONE-DEMO-A").first(),
            airbase=airbase,
            title=f"Sensor Outage Injected: {sensor.fictional_code} is {state_clean}",
            summary=(
                f"{sensor.fictional_code} transitioned {old_health} -> {state_clean}. "
                f"Dependent tracks ({', '.join(t.fictional_track_code for t in affected_tracks) or 'none'}) "
                "are labelled UNCERTAIN/STALE."
            ),
            status=Alert.AlertStatus.NEW,
            transition_history=[
                {
                    "actor": actor.username if actor else "FAULT_INJECTOR",
                    "timestamp": now.isoformat(),
                    "previous_state": None,
                    "new_state": "NEW",
                    "reason": f"Demo fault injection on {sensor.fictional_code} ({state_clean}).",
                }
            ],
        )

        if airbase:
            recalculate_airbase_readiness(
                airbase, trigger_reason=f"sensor_fault:{sensor.fictional_code}->{state_clean}"
            )

        groups = ["zone_ZONE-DEMO-A", "zone_ZONE-DEMO-B", "airbase_AB-DEMO-01"]
        transaction.on_commit(
            lambda: broadcast_scoped_ws_event(
                groups=groups,
                message_type="alert.created",
                payload={
                    "alert_id": str(alert_obj.id),
                    "event_id": event_obj.event_id,
                    "sensor_code": sensor.fictional_code,
                    "health_state": state_clean,
                    "affected_tracks": [t.fictional_track_code for t in affected_tracks],
                    "title": alert_obj.title,
                    "summary": alert_obj.summary,
                },
            )
        )

        return {
            "sensor_code": sensor.fictional_code,
            "previous_health": old_health,
            "health_state": state_clean,
            "affected_tracks": [t.fictional_track_code for t in affected_tracks],
            "event_id": event_obj.event_id,
            "alert_id": str(alert_obj.id),
        }

    @transaction.atomic
    def reset_scenario(self, *, run: SimulationRun, actor: Optional[User] = None) -> Dict[str, Any]:
        """
        Hard reset to restore deterministic baseline fixture state between judge runs (Section 06 & 15).
        """
        from django.core.management import call_command

        call_command("seed_demo_data", reset=True, export_fixture=False)
        return {
            "reset_completed": True,
            "seed": self.seed,
            "scenario_code": self.scenario_code,
            "timestamp": timezone.now().isoformat(),
        }
