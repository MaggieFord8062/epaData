"""
retrieval.py
Pulls data from the CAM API into the database, one reporting year at a time.
Every pull is validated and recorded as a Dataset (provenance).

Used by ingest.py from the command line, and later by the retrieval page.
"""
import json
import re
from collections import Counter
from datetime import datetime

from sqlalchemy import func

from models import Dataset, Facility, Unit, AnnualRecord
from validation import from_campd, validate_record

SOURCE = "EPA CAMPD API"


class DatabaseIndex:
    """
    What's already in the database, loaded once so each API row
    doesn't need its own query. Kept up to date as rows are added.
    """

    def __init__(self, session):
        self.facilities = {f.epa_facility_id: f for f in session.query(Facility).all()}
        self.units = {(u.epa_facility_id, u.epa_unit_id): u for u in session.query(Unit).all()}
        self.records = {
            (r.epa_facility_id, r.internal_unit_key, r.year): r
            for r in session.query(AnnualRecord).all()
        }

        # Newest year each facility and unit has data for, so an older year
        # never overwrites newer names, fuels or unit types
        self.facility_year = dict(
            session.query(AnnualRecord.epa_facility_id, func.max(AnnualRecord.year))
            .group_by(AnnualRecord.epa_facility_id).all()
        )
        self.unit_year = dict(
            session.query(AnnualRecord.internal_unit_key, func.max(AnnualRecord.year))
            .group_by(AnnualRecord.internal_unit_key).all()
        )
        self.attribute_year = {}  # facility_id -> year its attributes came from


def start_dataset(session, name, year, params, raw_count):
    """Create the provenance record for a pull before anything from it is saved."""
    dataset = Dataset(
        dataset_name=name,
        data_source=SOURCE,
        reporting_year=str(year),
        retrieval_date=datetime.now().isoformat(timespec="seconds"),
        og_filename=None,
        num_raw_records=raw_count,
        query_parameters=json.dumps(params),
    )
    session.add(dataset)
    session.flush()  # gives it a dataset_id
    return dataset


def retrieve_emissions(session, client, index, year, filters=None):
    """
    Pull one year of annual emissions, validate every row, and store the new ones.
    Returns the Dataset record, which holds the counts and notes.
    """
    filters = {key: value for key, value in (filters or {}).items() if value}
    items = client.get_data(year, **filters)["items"]

    params = dict({"year": year}, **filters)
    dataset = start_dataset(session, f"CAMPD annual emissions {year}", year, params, len(items))

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
        record_year = record["year"]

        # Facility: add it, or refresh its name if this is the newest year seen
        facility = index.facilities.get(facility_id)
        if facility is None:
            facility = Facility(
                epa_facility_id=facility_id,
                facility_name=record["facility_name"],
                state=record["state"],
            )
            session.add(facility)
            session.flush()
            index.facilities[facility_id] = facility
        if record_year >= index.facility_year.get(facility_id, 0):
            facility.facility_name = record["facility_name"]
            facility.state = record["state"]
            index.facility_year[facility_id] = record_year

        # Unit: add it, or refresh its type and fuels if this is the newest year seen
        unit = index.units.get((facility_id, unit_id))
        if unit is None:
            unit = Unit(epa_facility_id=facility_id, epa_unit_id=unit_id)
            session.add(unit)
            session.flush()
            index.units[(facility_id, unit_id)] = unit
        if record_year >= index.unit_year.get(unit.internal_unit_key, 0):
            unit.unit_type = record["unit_type"]
            unit.primary_fuel = record["primary_fuel"]
            unit.secondary_fuel = record["secondary_fuel"]
            index.unit_year[unit.internal_unit_key] = record_year

        record_key = (facility_id, unit.internal_unit_key, record_year)

        # The API listed the same unit and year twice in this pull
        if record_key in seen_this_pull:
            duplicates_in_pull += 1
            continue
        seen_this_pull.add(record_key)

        # Already stored from an earlier pull
        if record_key in index.records:
            already_stored += 1
            old = index.records[record_key]
            if old.dataset_id is None:
                # Saved before provenance existed: attach it to this pull
                old.dataset_id = dataset.dataset_id
                linked += 1
            continue

        new_record = AnnualRecord(
            epa_facility_id=facility_id,
            internal_unit_key=unit.internal_unit_key,
            year=record_year,
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
        index.records[record_key] = new_record
        inserted += 1

    dataset.num_accepted_records = inserted + already_stored

    notes = [f"{inserted} new", f"{already_stored} already stored"]
    if linked:
        notes.append(f"{linked} older records linked to this dataset")
    if duplicates_in_pull:
        notes.append(f"{duplicates_in_pull} duplicate rows in the API response")
    for reason, count in rejected.most_common():
        notes.append(f"Rejected ({count}): {reason}")
    if not items:
        notes.append("The API returned no records for this year and these filters")
    dataset.notes = "; ".join(notes)

    session.commit()
    return dataset


def parse_retirement(status):
    """
    CAMPD reports retired units with an operating status like "Retired (06/01/2019)".
    Returns "2019-06-01", the status text if there's no date, or None if the unit isn't retired.
    """
    if not status or "retired" not in status.lower():
        return None
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", status)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return status.strip()


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def retrieve_attributes(session, client, index, year, filters=None):
    """
    Pull one year of facility and unit attributes and fill in the fields the
    emissions data doesn't have: county, latitude, longitude, source category,
    operating (commercial operation) date and retirement date.
    Newer years overwrite older ones, so each facility ends up with its latest attributes.
    """
    filters = {key: value for key, value in (filters or {}).items() if value}
    items = client.get_facility_attributes(year, **filters)["items"]

    params = dict({"year": year}, **filters)
    dataset = start_dataset(session, f"CAMPD facility attributes {year}", year, params, len(items))

    facilities_updated = set()
    units_updated = 0
    not_in_database = 0
    rejected = Counter()

    for row in items:
        try:
            facility_id = int(row.get("facilityId"))
        except (TypeError, ValueError):
            rejected["Missing or invalid facility ID"] += 1
            continue

        facility = index.facilities.get(facility_id)
        if facility is None:
            # Facility has no emissions records stored, so there's nothing to attach this to
            not_in_database += 1
            continue

        if year >= index.attribute_year.get(facility_id, 0):
            facility.county = row.get("county") or facility.county
            facility.source_category = row.get("sourceCategory") or facility.source_category
            latitude = to_float(row.get("latitude"))
            longitude = to_float(row.get("longitude"))
            if latitude is not None and -90 <= latitude <= 90:
                facility.latitude = latitude
            if longitude is not None and -180 <= longitude <= 180:
                facility.longitude = longitude
            index.attribute_year[facility_id] = year
            facilities_updated.add(facility_id)

        unit = index.units.get((facility_id, str(row.get("unitId") or "").strip()))
        if unit is not None:
            if row.get("commercialOperationDate"):
                unit.operating_date = row["commercialOperationDate"]
            retirement = parse_retirement(row.get("operatingStatus"))
            if retirement:
                unit.retirement_date = retirement
            units_updated += 1

    accepted = len(items) - not_in_database - sum(rejected.values())
    dataset.num_accepted_records = accepted

    notes = [
        f"{len(facilities_updated)} facilities updated",
        f"{units_updated} units updated",
        "Adds county, location, source category and operating/retirement dates (stores no annual records)",
    ]
    if not_in_database:
        notes.append(f"{not_in_database} rows skipped: facility has no emissions data stored")
    for reason, count in rejected.most_common():
        notes.append(f"Rejected ({count}): {reason}")
    if not items:
        notes.append("The API returned no records for this year and these filters")
    dataset.notes = "; ".join(notes)

    session.commit()
    return dataset