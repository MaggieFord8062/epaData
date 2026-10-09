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

# CAMPD API field aliases -> our field names. Annual summary endpoints often
# prefix aggregate values with "sum"; keep the raw names as fallbacks for
# endpoint/version differences.
CAMPD_FIELD_ALIASES = {
    "facility_id": ("facilityId", "facility_id"),
    "facility_name": ("facilityName", "facility_name"),
    "state": ("stateCode", "state"),
    "unit_id": ("unitId", "unit_id", "unit_id"),
    "year": ("year",),
    "unit_type": ("unitType", "unit_type"),
    "primary_fuel": ("primaryFuelInfo", "primaryFuel", "primary_fuel"),
    "secondary_fuel": ("secondaryFuelInfo", "secondaryFuel", "secondary_fuel"),
    "operating_time": ("sumOpTime", "countOpTime", "operatingTime", "opTime", "operating_time"),
    "gross_load": ("sumGrossLoad", "grossLoad", "gross_load"),
    "steam_load": ("sumSteamLoad", "steamLoad", "steam_load"),
    "heat_input": ("sumHeatInput", "heatInput", "heat_input"),
    "co2_mass": ("sumCo2Mass", "sumCO2Mass", "co2Mass", "co2_mass"),
    "so2_mass": ("sumSo2Mass", "sumSO2Mass", "so2Mass", "so2_mass"),
    "nox_mass": ("sumNoxMass", "sumNOxMass", "noxMass", "nox_mass"),
    "so2_control_info": ("so2ControlInfo", "so2_control_info"),
    "nox_control_info": ("noxControlInfo", "nox_control_info"),
    "pm_control_info": ("pmControlInfo", "pm_control_info"),
    "program_code": ("programCodeInfo", "programCode", "program_code"),
}


def from_campd(row):
    """Normalize CAMPD API fields across annual-summary response variants."""
    normalized = {}
    for ours, aliases in CAMPD_FIELD_ALIASES.items():
        normalized[ours] = next(
            (row[key] for key in aliases if key in row and row[key] not in (None, "")),
            None,
        )
    return normalized


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

# CAMPD hourly response fields differ from the annual summary response.
HOURLY_NUMBER_FIELDS = {
    "operating_time": ("operatingTime", "opTime", "operating_time"),
    "gross_load": ("grossLoad", "gross_load"),
    "steam_load": ("steamLoad", "sumSteamLoad", "steam_load"),
    "heat_input": ("heatInput", "heat_input"),
    "co2_mass": ("co2Mass", "co2_mass"),
    "so2_mass": ("so2Mass", "so2_mass"),
    "nox_mass": ("noxMass", "nox_mass"),
    "hg_mass": ("hgMass", "mercuryMass", "hg_mass"),
}

def validate_hourly_record(row, expected_facility_id=None, expected_unit_id=None, expected_year=None, expected_date=None):
    """Normalize and validate one hourly API row; return (clean, error)."""
    from datetime import datetime

    def first(*keys):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    facility_value = first("facilityId", "facility_id")
    if facility_value is not None and expected_facility_id is not None and str(facility_value) != str(expected_facility_id):
        return None, "Hourly row belongs to a different facility"
    unit_value = first("unitId", "unit_id")
    if unit_value is not None and expected_unit_id is not None and str(unit_value) != str(expected_unit_id):
        return None, "Hourly row belongs to a different unit"

    date_value = first("opDate", "date", "operatingDate", "beginDate", "timestamp", "dateHour")
    if date_value is None:
        return None, "Missing hourly operating date"
    text = str(date_value).strip().replace("T", " ")
    inferred_hour = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        parsed_date = parsed.date()
        inferred_hour = parsed.hour if ("T" in str(date_value) or ":" in str(date_value)) else None
    except ValueError:
        try:
            parsed_date = datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None, "Invalid hourly operating date"
    if expected_year is not None and parsed_date.year != int(expected_year):
        return None, "Hourly row is outside the selected reporting year"
    if expected_date is not None and parsed_date.isoformat() != str(expected_date):
        return None, "Hourly row is outside the selected date"

    hour_value = first("opHour", "hour", "hourOfDay", "hourEnding")
    if hour_value is None:
        hour = inferred_hour
    else:
        try:
            hour = int(float(hour_value))
        except (TypeError, ValueError):
            return None, "Invalid hourly hour value"
        # Some CAMPD data uses hour-ending values 1..24; preserve the API's hour label.
        if not 0 <= hour <= 24:
            return None, "Hourly hour must be between 0 and 24"
    timestamp = f"{parsed_date.isoformat()} {hour:02d}:00" if hour is not None else parsed_date.isoformat()
    clean = {"timestamp": timestamp}
    for field, keys in HOURLY_NUMBER_FIELDS.items():
        value = first(*keys)
        if value is None:
            clean[field] = None
            continue
        number = to_float(value)
        if number is None:
            return None, f"{field.replace('_', ' ').title()} is not numeric"
        if number < 0:
            return None, f"{field.replace('_', ' ').title()} cannot be negative"
        clean[field] = number
    return clean, None
