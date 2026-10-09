"""
retrieval.py
Pulls data from the CAM API into the database, one reporting year at a time.
Every pull is validated and recorded as a Dataset (provenance).

Used by ingest.py from the command line, and by the Retrieve page on the website.
"""
import json
import re
from collections import Counter
from datetime import datetime

from sqlalchemy import func

from models import Dataset, Facility, Unit, AnnualRecord, HourlyRecord
from validation import from_campd, validate_record, validate_hourly_record

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


def report(progress, message):
    """Send a status message to whoever is watching (the retrieval page), if anyone is."""
    if progress is not None:
        progress(message)


def retrieve_emissions(session, client, index, year, filters=None, progress=None):
    """
    Pull one year of annual emissions, validate every row, and store the new ones.
    Returns the Dataset record, which holds the counts and notes.
    """
    filters = {key: value for key, value in (filters or {}).items() if value}
    report(progress, f"Requesting {year} annual emissions from the CAM API")
    items = client.get_data(
        year,
        on_page=lambda total: report(progress, f"Received {total:,} emissions records so far"),
        **filters,
    )["items"]
    report(progress, f"Validating and saving {len(items):,} emissions records")

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


def retrieve_attributes(session, client, index, year, filters=None, progress=None):
    """
    Pull one year of facility and unit attributes and fill in the fields the
    emissions data doesn't have: county, latitude, longitude, source category,
    operating (commercial operation) date and retirement date.
    Newer years overwrite older ones, so each facility ends up with its latest attributes.
    """
    filters = {key: value for key, value in (filters or {}).items() if value}
    report(progress, f"Requesting {year} facility attributes from the CAM API")
    items = client.get_facility_attributes(
        year,
        on_page=lambda total: report(progress, f"Received {total:,} attribute records so far"),
        **filters,
    )["items"]
    report(progress, f"Updating facility and unit details from {len(items):,} records")

    params = dict({"year": year}, **filters)
    dataset = start_dataset(session, f"CAMPD facility attributes {year}", year, params, len(items))

    facilities_updated = set()
    units_updated = 0
    not_in_database = 0
    rejected = Counter()
    categories = {}  # facility_id -> Counter of its units' source categories this year

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
            latitude = to_float(row.get("latitude"))
            longitude = to_float(row.get("longitude"))
            if latitude is not None and -90 <= latitude <= 90:
                facility.latitude = latitude
            if longitude is not None and -180 <= longitude <= 180:
                facility.longitude = longitude
            if row.get("sourceCategory"):
                categories.setdefault(facility_id, Counter())[row["sourceCategory"]] += 1
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

    # Source category is reported per unit. A power plant with small auxiliary boilers
    # can list "Industrial Boiler" on those units, so use the category most of its units have,
    # preferring "Electric Utility" when it's a tie.
    for facility_id, counts in categories.items():
        best = max(counts.items(), key=lambda item: (item[1], item[0] == "Electric Utility"))
        index.facilities[facility_id].source_category = best[0]

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

def retrieve_hourly_records(session, client, unit, operating_date, progress=None):
    """Retrieve, validate, merge MATS mercury, de-duplicate, and save hourly data for one unit/day."""
    day = operating_date.isoformat() if hasattr(operating_date, "isoformat") else str(operating_date)
    year = int(day[:4])
    filters = {"facilityId": unit.epa_facility_id, "unitId": unit.epa_unit_id}
    report(progress, f"Requesting hourly emissions for Unit {unit.epa_unit_id}, {day}")
    items = client.get_hourly_data(
        day, on_page=lambda total: report(progress, f"Received {total:,} hourly records so far"),
        **filters,
    )["items"]
    report(progress, f"Received {len(items):,} regular hourly records; requesting hourly MATS mercury data")

    # Hg is supplied by CAMPD's separate apportioned hourly MATS endpoint.
    # Index its values by the normalized date/hour timestamp used by HourlyRecord.
    mats_hg_by_timestamp = {}
    try:
        mats_items = client.get_hourly_mats_data(
            day, on_page=lambda total: report(progress, f"Received {total:,} hourly MATS records so far"),
            **filters,
        )["items"]
    except Exception as error:
        # Preserve the existing regular hourly import if the optional MATS request fails.
        mats_items = []
        report(progress, f"Warning: hourly MATS Hg request failed; importing other emissions without new Hg values ({error})")

    for mats_row in mats_items:
        mats_clean, mats_problem = validate_hourly_record(
            mats_row, expected_facility_id=unit.epa_facility_id,
            expected_unit_id=unit.epa_unit_id, expected_year=year, expected_date=day,
        )
        if mats_problem or mats_clean is None:
            continue
        if mats_clean.get("hg_mass") is not None:
            mats_hg_by_timestamp[mats_clean["timestamp"]] = mats_clean["hg_mass"]

    report(progress, f"Validating {len(items):,} regular hourly records")
    dataset = start_dataset(
        session,
        f"CAMPD hourly emissions {day} - Facility {unit.epa_facility_id}, Unit {unit.epa_unit_id}",
        year, {"beginDate": day, "endDate": day, **filters}, len(items),
    )
    inserted = skipped = updated_hg = 0
    rejected = Counter()
    seen = set()
    try:
        for row in items:
            clean, problem = validate_hourly_record(
                row, expected_facility_id=unit.epa_facility_id,
                expected_unit_id=unit.epa_unit_id, expected_year=year, expected_date=day,
            )
            if problem:
                rejected[problem] += 1
                continue
            timestamp = clean["timestamp"]
            if clean.get("hg_mass") is None:
                clean["hg_mass"] = mats_hg_by_timestamp.get(timestamp)
            key = (unit.internal_unit_key, timestamp)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            existing = session.query(HourlyRecord).filter_by(
                internal_unit_key=unit.internal_unit_key, timestamp=timestamp
            ).first()
            if existing:
                # Re-imports should fill Hg on previously saved rows without overwriting
                # any Hg value that is already present.
                if existing.hg_mass is None and clean.get("hg_mass") is not None:
                    existing.hg_mass = clean["hg_mass"]
                    updated_hg += 1
                else:
                    skipped += 1
                continue
            session.add(HourlyRecord(
                internal_unit_key=unit.internal_unit_key, timestamp=timestamp,
                dataset_id=dataset.dataset_id, operating_time=clean["operating_time"],
                gross_load=clean["gross_load"], steam_load=clean["steam_load"],
                heat_input=clean["heat_input"], co2_mass=clean["co2_mass"],
                so2_mass=clean["so2_mass"], nox_mass=clean["nox_mass"],
                hg_mass=clean.get("hg_mass"),
            ))
            inserted += 1
        dataset.num_accepted_records = inserted
        notes = [f"{inserted} new hourly records", f"{updated_hg} existing records updated with Hg", f"{skipped} duplicates/already stored",
                 f"{sum(rejected.values())} rejected", f"{len(mats_hg_by_timestamp)} hourly MATS Hg values matched"]
        notes.extend(f"Rejected ({count}): {reason}" for reason, count in rejected.most_common())
        if not items:
            notes.append("The regular hourly API returned no records for this unit and date")
        if not mats_items:
            notes.append("The hourly MATS API returned no records; Hg may remain blank for this date")
        dataset.notes = "; ".join(notes)
        session.commit()
        report(progress, f"Saved {inserted:,} new hourly records; updated Hg on {updated_hg:,} existing records; skipped {skipped:,}; rejected {sum(rejected.values()):,}; matched {len(mats_hg_by_timestamp):,} MATS Hg values")
        return {"dataset": dataset, "received": len(items), "inserted": inserted,
                "updated_hg": updated_hg, "mats_received": len(mats_items),
                "mats_hg_matched": len(mats_hg_by_timestamp), "skipped": skipped,
                "rejected": sum(rejected.values())}
    except Exception:
        session.rollback()
        raise
