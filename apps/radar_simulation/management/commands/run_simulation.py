"""
Management command:
    python manage.py run_simulation --scenario SCENARIO-BASELINE-01 --seed 26250 --action start
Also supports the shorthand from Section 16:
    python manage.py run_simulation scenario baseline --seed 26250
"""
import time
from django.core.management.base import BaseCommand
from apps.radar_simulation.engine import HybridRadarEngine
from apps.radar_simulation.scenarios import DEFAULT_SIMULATION_SEED


class Command(BaseCommand):
    help = "Controls or runs the deterministic AERO-OPS hybrid radar simulator (seed 26250)."

    def add_arguments(self, parser):
        parser.add_argument("positional_args", nargs="*", help="Optional positional scenario args.")
        parser.add_argument(
            "--scenario",
            type=str,
            default="SCENARIO-BASELINE-01",
            help="Scenario code or alias (default: SCENARIO-BASELINE-01).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_SIMULATION_SEED,
            help="Deterministic RNG seed (default: 26250).",
        )
        parser.add_argument(
            "--action",
            type=str,
            default="start",
            choices=["start", "pause", "resume", "step", "inject_fault", "reset", "loop"],
            help="Control action to execute.",
        )
        parser.add_argument(
            "--sensor",
            type=str,
            default="SENSOR-DEMO-03",
            help="Target sensor code when --action=inject_fault.",
        )
        parser.add_argument(
            "--fault-state",
            type=str,
            default="OFFLINE",
            choices=["STALE", "OFFLINE", "LIVE"],
            help="Target sensor health state when --action=inject_fault.",
        )
        parser.add_argument(
            "--steps",
            type=int,
            default=4,
            help="Number of steps to run when --action=loop.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=2.0,
            help="Seconds between steps when --action=loop.",
        )

    def handle(self, *args, **options):
        scenario_arg = options["scenario"]
        pos = options.get("positional_args") or []
        if len(pos) >= 2 and pos[0].lower() == "scenario":
            scenario_arg = pos[1]
        elif len(pos) == 1:
            scenario_arg = pos[0]

        seed = options["seed"]
        action = options["action"]
        engine = HybridRadarEngine(scenario_code=scenario_arg, seed=seed)

        if action == "loop":
            self.stdout.write(
                self.style.SUCCESS(
                    f"[SIMULATION MODE] Starting deterministic playback loop for {engine.scenario_code} (seed={seed})..."
                )
            )
            run = engine.get_or_create_scenario_and_run()
            for i in range(options["steps"]):
                step_res = engine.step_next(run=run)
                env = step_res["event_envelope"]
                self.stdout.write(
                    f"  -> Seq #{step_res['sequence_num']}: {env['event_id']} [{env['event_type']}] "
                    f"from {env['source_id']} (created={step_res['idempotent_created']})"
                )
                if i < options["steps"] - 1:
                    time.sleep(options["interval"])
            return

        result = engine.control(
            action=action,
            sensor_code=options["sensor"],
            fault_state=options["fault_state"],
        )
        self.stdout.write(
            self.style.SUCCESS(f"[SIMULATION MODE] Executed action='{action}': {result}")
        )
