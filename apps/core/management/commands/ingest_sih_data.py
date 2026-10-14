"""
Management command: python manage.py ingest_sih_data
Ingests the official SIH26250 defense raw datasets from fixtures/raw_data/:
1. fixtures/raw_data/SIH250.csv (25 IAF aircraft specifications)
2. fixtures/raw_data/Weapon_data.csv (69 weapons across INDIA, CHINA, PAKISTAN)
3. fixtures/raw_data/enemy aircraft.xlsx (9 adversary aircraft)
"""
import csv
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import AdversaryAircraft, AircraftSpecification, Equipment, Weapon


def clean_num(val: Any) -> Optional[float]:
    """Extracts first valid integer/float from strings containing unit suffixes or ranges."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() in ("N/A", "NAN", "NONE", "VTOL", "UNKNOWN"):
        return None
    s = s.replace(",", "")
    match = re.search(r"[-+]?\d*\.?\d+", s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def clean_int(val: Any, default: int = 0) -> int:
    num = clean_num(val)
    return int(round(num)) if num is not None else default


class Command(BaseCommand):
    help = "Ingests SIH26250 raw datasets (SIH250.csv, Weapon_data.csv, enemy aircraft.xlsx)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Purge existing specification records before re-ingesting.",
        )

    def handle(self, *args, **options):
        base_dir = Path(settings.BASE_DIR)
        raw_dir = base_dir / "fixtures" / "raw_data"
        reset = options["reset"]

        sih_csv_path = raw_dir / "SIH250.csv"
        weapon_csv_path = raw_dir / "Weapon_data.csv"
        enemy_xlsx_path = raw_dir / "enemy aircraft.xlsx"

        if not sih_csv_path.exists():
            self.stderr.write(self.style.ERROR(f"Missing {sih_csv_path}"))
            return

        with transaction.atomic():
            if reset:
                AircraftSpecification.objects.all().delete()
                Weapon.objects.all().delete()
                AdversaryAircraft.objects.all().delete()
                self.stdout.write(self.style.WARNING("Existing raw specification tables purged."))

            # -------------------------------------------------------------
            # 1. Ingest SIH250.csv (25 IAF Aircraft)
            # -------------------------------------------------------------
            ingested_sih = 0
            with open(sih_csv_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ac_id = int(clean_num(row.get("Aircraft_ID")) or 0)
                    if not ac_id:
                        continue
                    model = row.get("Aircraft_Model", "").strip()
                    takeoff_rwy_raw = str(row.get("Takeoff_Runway_Length_m(minimum)", "")).strip()
                    landing_rwy_raw = str(row.get("Landing_Runway_Length_m(minimum)", "")).strip()
                    is_vtol = "VTOL" in takeoff_rwy_raw.upper() or "VTOL" in landing_rwy_raw.upper()

                    takeoff_m = 0.0 if is_vtol else clean_num(takeoff_rwy_raw)
                    landing_m = 0.0 if is_vtol else clean_num(landing_rwy_raw)

                    # Extract rate of climb ms
                    roc_raw = row.get("Rate_of_Climb", "").strip()
                    roc_ms = clean_num(roc_raw)

                    # Extract number of engines
                    num_eng = clean_int(row.get("Number_of_Engines"), default=1)

                    # Extract endurance
                    endurance_val = clean_num(row.get("Flight_Endurance_hours(Without refuelings)"))

                    AircraftSpecification.objects.update_or_create(
                        aircraft_id=ac_id,
                        defaults={
                            "model": model,
                            "aircraft_type": row.get("Aircraft_Type", "").strip(),
                            "role": row.get("Aircraft_Role", "").strip(),
                            "generation": row.get("Aircraft_Generation", "").strip(),
                            "max_speed_mach": clean_num(row.get("Maximum_Speed_Mach")),
                            "max_altitude_ft": clean_num(row.get("Maximum_Altitude_ft/service_ceiling")),
                            "max_range_km": clean_num(row.get("Maximum_Range_km")),
                            "combat_radius_km": clean_num(row.get("Combat_Radius_km(maximum)")),
                            "flight_endurance_hours": endurance_val,
                            "max_takeoff_weight_kg": clean_num(row.get("Maximum_Takeoff_Weight_kg")),
                            "empty_weight_kg": clean_num(row.get("Empty_Weight_kg")),
                            "max_payload_kg": clean_num(row.get("Maximum_Payload_kg")),
                            "internal_fuel_capacity_kg": clean_num(row.get("Internal_Fuel_Capacity_kg")),
                            "aircraft_weight_kg": clean_num(row.get("Aircraft_Weight_kg")),
                            "engine_type": row.get("Engine_Type", "").strip(),
                            "number_of_engines": num_eng,
                            "rate_of_climb": roc_raw,
                            "rate_of_climb_ms": roc_ms,
                            "aircraft_length_m": clean_num(row.get("Aircraft_Length_m")),
                            "aircraft_height_m": clean_num(row.get("Aircraft_Height_m")),
                            "takeoff_runway_length_m": takeoff_m,
                            "landing_runway_length_m": landing_m,
                            "is_vtol": is_vtol,
                            "number_of_hardpoints": clean_int(row.get("Number_of_Hardpoints")),
                            "limitations": row.get("Limitations", "").strip(),
                            "crew_capacity": row.get("Crew_Capacity", "").strip(),
                            "max_passenger_capacity": row.get("Maximum_Passenger_Capacity", "").strip(),
                            "crew_qualification": row.get("Crew_Qualification/rank", "").strip(),
                        },
                    )
                    ingested_sih += 1

            self.stdout.write(
                self.style.SUCCESS(f"[1/3] Successfully ingested {ingested_sih} IAF aircraft from SIH250.csv")
            )

            # -------------------------------------------------------------
            # 2. Ingest Weapon_data.csv (69 Weapons)
            # -------------------------------------------------------------
            ingested_weapons = 0
            if weapon_csv_path.exists():
                with open(weapon_csv_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        w_id = row.get("Weapon_ID", "").strip()
                        if not w_id:
                            continue
                        w_name = row.get("Weapon_Name", "").strip()
                        rng_str = row.get("Maximum_Range_km", "").strip()
                        spd_str = row.get("Maximum_Speed_Mach", "").strip()

                        Weapon.objects.update_or_create(
                            weapon_id=w_id,
                            defaults={
                                "name": w_name,
                                "country_deployed": row.get("Country_deployed", "").strip(),
                                "category": row.get("Weapon_Category", "").strip(),
                                "weapon_type": row.get("Weapon_Type", "").strip(),
                                "guidance_type": row.get("Guidance_Type", "").strip(),
                                "propulsion_type": row.get("Propulsion_Type", "").strip(),
                                "max_range_km": rng_str,
                                "max_range_val_km": clean_num(rng_str),
                                "max_speed_mach": spd_str,
                                "max_speed_mach_val": clean_num(spd_str),
                                "length_m": clean_num(row.get("Length_m")),
                                "diameter_mm": clean_num(row.get("Diameter_mm")),
                                "warhead_type": row.get("Warhead_Type", "").strip(),
                                "target_type": row.get("Target_Type", "").strip(),
                                "launch_platform": row.get("Launch_Platform", "").strip(),
                                "weight_kg": clean_num(row.get("Weight_kg")),
                            },
                        )
                        ingested_weapons += 1

                self.stdout.write(
                    self.style.SUCCESS(f"[2/3] Successfully ingested {ingested_weapons} weapons from Weapon_data.csv")
                )

            # -------------------------------------------------------------
            # 3. Ingest enemy aircraft.xlsx (9 Adversary Aircraft)
            # -------------------------------------------------------------
            ingested_adversary = 0
            if enemy_xlsx_path.exists():
                with zipfile.ZipFile(enemy_xlsx_path) as z:
                    sst_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                    strings = [
                        elem.text or ""
                        for elem in sst_root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                    ]

                    sheet_root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
                    headers: List[str] = []
                    for i, row in enumerate(sheet_root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row")):
                        vals: List[str] = []
                        for c in row.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                            t = c.get("t")
                            v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                            val = v.text if v is not None else ""
                            if t == "s" and val.isdigit() and int(val) < len(strings):
                                val = strings[int(val)]
                            vals.append(val)
                        if i == 0:
                            headers = vals
                        else:
                            row_dict = dict(zip(headers, vals))
                            ac_id = int(clean_num(row_dict.get("Aircraft_ID")) or 0)
                            if not ac_id:
                                continue
                            model = row_dict.get("Aircraft_Model", "").strip()

                            AdversaryAircraft.objects.update_or_create(
                                aircraft_id=ac_id,
                                defaults={
                                    "model": model,
                                    "country": row_dict.get("Country", "").strip(),
                                    "aircraft_type": row_dict.get("Aircraft_Type", "").strip(),
                                    "role": row_dict.get("Aircraft_Role", "").strip(),
                                    "generation": str(row_dict.get("Aircraft_Generation", "")).strip(),
                                    "max_speed_mach": clean_num(row_dict.get("Maximum_Speed_Mach")),
                                    "max_altitude_ft": clean_num(row_dict.get("Maximum_Altitude_ft")),
                                    "max_range_km": clean_num(row_dict.get("Maximum_Range_km")),
                                    "combat_radius_km": clean_num(row_dict.get("Combat_Radius_km(maximum)")),
                                    "flight_endurance_hours": clean_num(row_dict.get("Flight_Endurance_hours(Without refuelings)")),
                                    "max_takeoff_weight_kg": clean_num(row_dict.get("Maximum_Takeoff_Weight_kg")),
                                    "empty_weight_kg": clean_num(row_dict.get("Empty_Weight_kg")),
                                    "max_payload_kg": clean_num(row_dict.get("Maximum_Payload_kg")),
                                    "internal_fuel_capacity_kg": clean_num(row_dict.get("Internal_Fuel_Capacity_kg")),
                                    "aircraft_weight_kg": clean_num(row_dict.get("Aircraft_Weight_kg")),
                                    "engine_type": row_dict.get("Engine_Type", "").strip(),
                                    "number_of_engines": clean_int(row_dict.get("Number_of_Engines"), default=1),
                                    "rate_of_climb": row_dict.get("Rate_of_Climb", "").strip(),
                                    "length_m": clean_num(row_dict.get("Aircraft_Length_m")),
                                    "height_m": clean_num(row_dict.get("Aircraft_Height_m")),
                                    "takeoff_runway_m": clean_num(row_dict.get("Takeoff_Runway_Length_m(minimum)")),
                                    "landing_runway_m": clean_num(row_dict.get("Landing_Runway_Length_m(minimum)")),
                                    "number_of_hardpoints": clean_int(row_dict.get("Number_of_Hardpoints")),
                                    "radar_detection_range_km": clean_num(row_dict.get("Radar_Detection_Range_km(maximum)")),
                                    "weather_operating_limits": row_dict.get("Weather_Operating_Limits", "").strip(),
                                    "crew_capacity": row_dict.get("Crew_Capacity", "").strip(),
                                    "max_passenger_capacity": row_dict.get("Maximum_Passenger_Capacity", "").strip(),
                                    "crew_qualification": row_dict.get("Crew_Qualification/rank", "").strip(),
                                },
                            )
                            ingested_adversary += 1

                self.stdout.write(
                    self.style.SUCCESS(f"[3/3] Successfully ingested {ingested_adversary} adversary aircraft from enemy aircraft.xlsx")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Ingestion complete: {ingested_sih} IAF aircraft, {ingested_weapons} weapons, {ingested_adversary} adversary aircraft."
            )
        )
