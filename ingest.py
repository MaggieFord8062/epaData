import os
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from client import CAMPDClient
from database import SessionLocal
from models import Facility, Unit, AnnualRecord, Dataset

load_dotenv()
api_key = os.getenv("CAMPD_API_KEY")
client = CAMPDClient(api_key)

session = SessionLocal()

STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY"
]
YEAR = 2024

all_items = []

for state in STATES:
    data = client.get_data(YEAR, state)
    items = data["items"]
    all_items.extend(items)

    dataset = Dataset(
        dataset_name=f"CAMPD Annual Emissions - {state} {YEAR}",
        data_source="EPA CAMPD API (emissions-mgmt/emissions/apportioned/annual)",
        reporting_year=str(YEAR),
        retrieval_date=datetime.now().isoformat(),
        og_filename=None,
        num_raw_records=len(items),
        num_accepted_records=None,
        notes=f"Retrieved via CAM API, state filter {state}"
    )
    session.add(dataset)
    session.flush()
    print(f"Logged dataset: {state} {YEAR} — {len(items)} raw records (dataset_id={dataset.dataset_id})")

df = pd.DataFrame(all_items)
print(f"\nTotal records to ingest: {len(df)}")

skipped = []
inserted = 0

for _, row in df.iterrows():
    facility_id = row["facilityId"]
    unit_id = row["unitId"]
    year = row["year"]

    facility = session.get(Facility, facility_id)
    if facility is None:
        facility = Facility(
            epa_facility_id=facility_id,
            facility_name=row["facilityName"],
            state=row["stateCode"],
            county=None,
            latitude=None,
            longitude=None,
            source_category=None,
        )
        session.add(facility)
        session.flush()

    unit = session.query(Unit).filter_by(
        epa_facility_id=facility_id, epa_unit_id=unit_id
    ).first()
    if unit is None:
        unit = Unit(
            epa_facility_id=facility_id,
            epa_unit_id=unit_id,
            unit_type=row["unitType"],
            primary_fuel=row["primaryFuelInfo"],
            secondary_fuel=row["secondaryFuelInfo"],
            operating_date=None,
            retirement_date=None,
        )
        session.add(unit)
        session.flush()

    existing = session.query(AnnualRecord).filter_by(
        epa_facility_id=facility_id,
        internal_unit_key=unit.internal_unit_key,
        year=year
    ).first()

    if existing:
        skipped.append((facility_id, unit_id, year))
        continue

    record = AnnualRecord(
        epa_facility_id=facility_id,
        internal_unit_key=unit.internal_unit_key,
        year=year,
        operating_time=row["sumOpTime"],
        gross_load=row["grossLoad"],
        steam_load=row["steamLoad"],
        heat_input=row["heatInput"],
        co2_mass=row["co2Mass"],
        so2_mass=row["so2Mass"],
        nox_mass=row["noxMass"],
        so2_control_info=row["so2ControlInfo"],
        nox_control_info=row["noxControlInfo"],
        pm_control_info=row["pmControlInfo"],
        program_code=row["programCodeInfo"],
    )
    session.add(record)
    inserted += 1

session.commit()
session.close()

print(f"\nInserted: {inserted}")
print(f"Skipped (duplicates): {len(skipped)}")
if skipped:
    print("Duplicate keys skipped:", skipped[:5], "..." if len(skipped) > 5 else "")