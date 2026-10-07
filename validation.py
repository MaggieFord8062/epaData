"""
validation.py
Checks one record at a time before it goes into the database.
Used by the API retrievals (ingest.py and the Retrieve page) and by the Upload page,
so every source follows exactly the same rules.
"""
from datetime import date

EARLIEST_YEAR = 1995  # first year of CAMPD annual data
LATEST_YEAR = date.today().year

# Numbers that can't be negative. Missing (blank) values are allowed,
# because many units legitimately have no steam load or no SO2 reading.
NUMBER_FIELDS = [
    "operating_time", "gross_load", "steam_load", "heat_input",
    "co2_mass", "so2_mass", "nox_mass",
]

# Readable names for messages in the data-quality report
NUMBER_LABELS = {
    "operating_time": "Operating time",
    "gross_load": "Gross load",
    "steam_load": "Steam load",
    "heat_input": "Heat input",
    "co2_mass": "CO2",
    "so2_mass": "SO2",
    "nox_mass": "NOx",
}

TEXT_FIELDS = [
    "facility_name", "state", "unit_type", "primary_fuel", "secondary_fuel",
    "so2_control_info", "nox_control_info", "pm_control_info", "program_code",
]

# CAMPD API field name -> our field name
CAMPD_FIELDS = {
    "facilityId": "facility_id",
    "facilityName": "facility_name",
    "stateCode": "state",
    "unitId": "unit_id",
    "year": "year",
    "unitType": "unit_type",
    "primaryFuelInfo": "primary_fuel",
    "secondaryFuelInfo": "secondary_fuel",
    "sumOpTime": "operating_time",
    "grossLoad": "gross_load",
    "steamLoad": "steam_load",
    "heatInput": "heat_input",
    "co2Mass": "co2_mass",
    "so2Mass": "so2_mass",
    "noxMass": "nox_mass",
    "so2ControlInfo": "so2_control_info",
    "noxControlInfo": "nox_control_info",
    "pmControlInfo": "pm_control_info",
    "programCodeInfo": "program_code",
}


def from_campd(row):
    """Rename a CAMPD API row's fields to the names the rest of the app uses."""
    return {ours: row.get(theirs) for theirs, ours in CAMPD_FIELDS.items()}


def is_blank(value):
    return value is None or str(value).strip() == ""


def to_int(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not number.is_integer():
        return None
    return int(number)


def to_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def validate_record(record):
    """
    Check one record.
    Returns (clean_record, None) if it passes,
    or (None, "reason it failed") if it doesn't.
    """
    clean = {}

    # Required identifiers
    facility_id = to_int(record.get("facility_id"))
    if facility_id is None or facility_id <= 0:
        return None, "Missing or invalid facility ID"
    clean["facility_id"] = facility_id

    if is_blank(record.get("unit_id")):
        return None, "Missing unit ID"
    clean["unit_id"] = str(record["unit_id"]).strip()

    year = to_int(record.get("year"))
    if year is None:
        return None, "Missing or invalid year"
    if year < EARLIEST_YEAR or year > LATEST_YEAR:
        return None, f"Year outside {EARLIEST_YEAR}-{LATEST_YEAR}"
    clean["year"] = year

    if is_blank(record.get("facility_name")):
        return None, "Missing facility name"

    state = str(record.get("state") or "").strip().upper()
    if len(state) != 2 or not state.isalpha():
        return None, "Missing or invalid state code"

    # Text fields: trim spaces, blank becomes None
    for field in TEXT_FIELDS:
        value = record.get(field)
        clean[field] = None if is_blank(value) else str(value).strip()
    clean["state"] = state

    # Number fields: blank is fine, but anything else must be a number that isn't negative
    for field in NUMBER_FIELDS:
        value = record.get(field)
        if is_blank(value):
            clean[field] = None
            continue
        number = to_float(value)
        if number is None:
            return None, f"{NUMBER_LABELS[field]} is not a number (\"{value}\")"
        if number < 0:
            return None, f"{NUMBER_LABELS[field]} is negative ({value})"
        clean[field] = number

    if clean["operating_time"] is not None and clean["operating_time"] > 8784:
        return None, "Operating time over 8,784 hours (more hours than a year has)"

    return clean, None