import os
import pandas as pd
from dotenv import load_dotenv
from client import CAMPDClient
from database import SessionLocal
from models import Facility, Unit, AnnualRecord

load_dotenv()
api_key = os.getenv("CAMPD_API_KEY")
client = CAMPDClient(api_key)

# Pull both states you already validated
data_ky = client.get_data(2024, "KY")
data_tx = client.get_data(2024, "TX")

df = pd.DataFrame(data_ky["items"] + data_tx["items"])
print(f"Total records to ingest: {len(df)}")

session = SessionLocal()

skipped = []
inserted = 0

for _, row in df.iterrows():
    facility_id = row["facilityId"]
    unit_id = row["unitId"]
    year = row["year"]

    # Facility: insert if not already present
    facility = session.get(Facility, facility_id)
    if facility is None:
        facility = Facility(
            epa_facility_id=facility_id,
            facility_name=row["facilityName"],
            state=row["stateCode"],
            county=None,          # not available from this endpoint
            latitude=None,        # not available from this endpoint
            longitude=None,       # not available from this endpoint
            source_category=None, # not available from this endpoint
        )
        session.add(facility)
        session.flush()  # so it's queryable within this loop

    #Unit: insert if not already present (by facility+unit combo)
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
            operating_date=None,   # not available from this endpoint
            retirement_date=None,  # not available from this endpoint
        )
        session.add(unit)
        session.flush()

    # AnnualRecord: skip if this facility+unit+year already exists
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

print(f"Inserted: {inserted}")
print(f"Skipped (duplicates): {len(skipped)}")
if skipped:
    print("Duplicate keys skipped:", skipped[:5], "..." if len(skipped) > 5 else "")