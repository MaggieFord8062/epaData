"""
ingest.py
Pulls EPA CAMPD annual emissions data for ALL states, validates every record,
and saves it to epaData.db along with a provenance record in the dataset table.

Run from the project folder:
    python ingest.py

Safe to run more than once: records already in the database are skipped.
"""
import os
from collections import Counter
from datetime import datetime

from dotenv import load_dotenv
from client import CAMPDClient
from database import SessionLocal
from models import Dataset, Facility, Unit, AnnualRecord
from validation import from_campd, validate_record

# Add more years here if you want them, e.g. [2022, 2023, 2024]
YEARS = [2024]

SOURCE = "EPA CAMPD API"

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
    (r.epa_facility_id, r.internal_unit_key, r.year): r
    for r in session.query(AnnualRecord).all()
}

for year in YEARS:
    print(f"\nFetching {year} data for all states (this can take a minute)...")
    items = client.get_data(year)["items"]
    print(f"  Fetched {len(items)} records from the API")

    # Provenance: record this pull before saving anything from it
    dataset = Dataset(
        dataset_name=f"CAMPD annual emissions {year}",
        data_source=SOURCE,
        reporting_year=str(year),
        retrieval_date=datetime.now().isoformat(timespec="seconds"),
        og_filename=None,
        num_raw_records=len(items),
    )
    session.add(dataset)
    session.flush()  # gives dataset a dataset_id

    inserted = 0
    already_stored = 0
    linked = 0
    duplicates_in_pull = 0
    rejected = Counter()
    seen_this_pull = set()

    for row in items:
        record, problem = validate_record(from_campd(row))
        if problem:
            rejected[problem] += 1
            continue

        facility_id = record["facility_id"]
        unit_id = record["unit_id"]

        # Facility
        if facility_id not in facilities:
            session.add(Facility(
                epa_facility_id=facility_id,
                facility_name=record["facility_name"],
                state=record["state"],
            ))
            session.flush()
            facilities.add(facility_id)

        # Unit
        unit_key = units.get((facility_id, unit_id))
        if unit_key is None:
            unit = Unit(
                epa_facility_id=facility_id,
                epa_unit_id=unit_id,
                unit_type=record["unit_type"],
                primary_fuel=record["primary_fuel"],
                secondary_fuel=record["secondary_fuel"],
            )
            session.add(unit)
            session.flush()
            unit_key = unit.internal_unit_key
            units[(facility_id, unit_id)] = unit_key

        record_key = (facility_id, unit_key, record["year"])

        # The API listed the same unit and year twice in this pull
        if record_key in seen_this_pull:
            duplicates_in_pull += 1
            continue
        seen_this_pull.add(record_key)

        # Already stored from an earlier run
        if record_key in existing:
            already_stored += 1
            old = existing[record_key]
            if old.dataset_id is None:
                # Saved before provenance existed: attach it to this pull
                old.dataset_id = dataset.dataset_id
                linked += 1
            continue

        new_record = AnnualRecord(
            epa_facility_id=facility_id,
            internal_unit_key=unit_key,
            year=record["year"],
            dataset_id=dataset.dataset_id,
            operating_time=record["operating_time"],
            gross_load=record["gross_load"],
            steam_load=record["steam_load"],
            heat_input=record["heat_input"],
            co2_mass=record["co2_mass"],
            so2_mass=record["so2_mass"],
            nox_mass=record["nox_mass"],
            so2_control_info=record["so2_control_info"],
            nox_control_info=record["nox_control_info"],
            pm_control_info=record["pm_control_info"],
            program_code=record["program_code"],
        )
        session.add(new_record)
        existing[record_key] = new_record
        inserted += 1

    # Finish the provenance record
    accepted = inserted + already_stored
    dataset.num_accepted_records = accepted

    notes = [f"{inserted} new", f"{already_stored} already stored"]
    if linked:
        notes.append(f"{linked} older records linked to this dataset")
    if duplicates_in_pull:
        notes.append(f"{duplicates_in_pull} duplicate rows in the API response")
    for reason, count in rejected.most_common():
        notes.append(f"Rejected ({count}): {reason}")
    if not items:
        notes.append("the API returned no records; check the API key or try again later")
    dataset.notes = "; ".join(notes)

    session.commit()

    print(f"  Accepted: {accepted}   New: {inserted}   Already stored: {already_stored}")
    if linked:
        print(f"  Linked {linked} older records to this dataset")
    if duplicates_in_pull:
        print(f"  Duplicates in the API response: {duplicates_in_pull}")
    if rejected:
        print(f"  Rejected: {sum(rejected.values())}")
        for reason, count in rejected.most_common():
            print(f"    {reason}: {count}")
    print(f"  Saved as dataset #{dataset.dataset_id}")

session.close()

print("\nDone.")
print(f"Data saved in: {os.path.abspath('epaData.db')}")