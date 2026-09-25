"""
get_all_data.py
Pulls EPA CAMPD annual emissions data for ALL states and saves it to epaData.db.

Run from the project folder:
    python get_all_data.py

Safe to run more than once: records already in the database are skipped.
"""
import os
from dotenv import load_dotenv
from client import CAMPDClient
from database import SessionLocal
from models import Facility, Unit, AnnualRecord

# Add more years here if you want them, e.g. [2022, 2023, 2024]
YEARS = [2024]

load_dotenv()
api_key = os.getenv("CAMPD_API_KEY")
if not api_key:
    print("No CAMPD_API_KEY found in .env")
    raise SystemExit(1)

client = CAMPDClient(api_key)
session = SessionLocal()

# Load what's already in the database so we don't query it once per row
facilities = {f.epa_facility_id for f in session.query(Facility).all()}
units = {(u.epa_facility_id, u.epa_unit_id): u.internal_unit_key for u in session.query(Unit).all()}
existing = {
    (r.epa_facility_id, r.internal_unit_key, r.year)
    for r in session.query(AnnualRecord).all()
}

total_inserted = 0
total_skipped = 0

for year in YEARS:
    print(f"\nFetching {year} data for all states (this can take a minute)...")
    items = client.get_data(year)  # no state = every state
    items = items["items"]
    print(f"  Fetched {len(items)} records from the API")

    if not items:
        print("  Nothing came back. Check your API key or try again later.")
        continue

    inserted = 0
    skipped = 0

    for row in items:
        facility_id = row["facilityId"]
        unit_id = str(row["unitId"])

        # Facility
        if facility_id not in facilities:
            session.add(Facility(
                epa_facility_id=facility_id,
                facility_name=row.get("facilityName"),
                state=row.get("stateCode"),
            ))
            session.flush()
            facilities.add(facility_id)

        # Unit
        unit_key = units.get((facility_id, unit_id))
        if unit_key is None:
            unit = Unit(
                epa_facility_id=facility_id,
                epa_unit_id=unit_id,
                unit_type=row.get("unitType"),
                primary_fuel=row.get("primaryFuelInfo"),
                secondary_fuel=row.get("secondaryFuelInfo"),
            )
            session.add(unit)
            session.flush()
            unit_key = unit.internal_unit_key
            units[(facility_id, unit_id)] = unit_key

        # Annual record
        record_key = (facility_id, unit_key, row["year"])
        if record_key in existing:
            skipped += 1
            continue

        session.add(AnnualRecord(
            epa_facility_id=facility_id,
            internal_unit_key=unit_key,
            year=row["year"],
            operating_time=row.get("sumOpTime"),
            gross_load=row.get("grossLoad"),
            steam_load=row.get("steamLoad"),
            heat_input=row.get("heatInput"),
            co2_mass=row.get("co2Mass"),
            so2_mass=row.get("so2Mass"),
            nox_mass=row.get("noxMass"),
            so2_control_info=row.get("so2ControlInfo"),
            nox_control_info=row.get("noxControlInfo"),
            pm_control_info=row.get("pmControlInfo"),
            program_code=row.get("programCodeInfo"),
        ))
        existing.add(record_key)
        inserted += 1

    session.commit()
    print(f"  Inserted: {inserted}   Skipped (already in DB): {skipped}")
    total_inserted += inserted
    total_skipped += skipped

session.close()

print("\nDone.")
print(f"Total inserted: {total_inserted}")
print(f"Total skipped:  {total_skipped}")
print(f"Data saved in:  {os.path.abspath('epaData.db')}")