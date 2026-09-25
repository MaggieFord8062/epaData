import sqlite3

DB_PATH = "epaData.db"

# Columns shown on the results page, with readable header names
RESULT_COLUMNS = """
    facility.facility_name          AS "Facility",
    facility.epa_facility_id        AS "Facility ID",
    facility.state                  AS "State",
    facility.county                 AS "County",
    unit.epa_unit_id                AS "Unit",
    unit.unit_type                  AS "Unit Type",
    unit.primary_fuel               AS "Primary Fuel",
    unit.secondary_fuel             AS "Secondary Fuel",
    annual_records.year             AS "Year",
    annual_records.operating_time   AS "Operating Time (hrs)",
    annual_records.gross_load       AS "Gross Load (MWh)",
    annual_records.steam_load       AS "Steam Load (1000 lb)",
    annual_records.heat_input       AS "Heat Input (mmBtu)",
    annual_records.co2_mass         AS "CO2 (tons)",
    annual_records.so2_mass         AS "SO2 (tons)",
    annual_records.nox_mass         AS "NOx (tons)",
    annual_records.so2_control_info AS "SO2 Controls",
    annual_records.nox_control_info AS "NOx Controls",
    annual_records.pm_control_info  AS "PM Controls",
    annual_records.program_code     AS "Programs"
"""

BASE_JOIN = """
    FROM facility
    JOIN unit
        ON facility.epa_facility_id = unit.epa_facility_id
    JOIN annual_records
        ON unit.internal_unit_key = annual_records.internal_unit_key
"""

# Text filters: form field name -> database column (exact match)
TEXT_FILTERS = {
    "epa_facility_id": "facility.epa_facility_id",
    "facility_name": "facility.facility_name",
    "epa_unit_id": "unit.epa_unit_id",
    "state": "facility.state",
    "county": "facility.county",
    "source_category": "facility.source_category",
    "reporting_year": "annual_records.year",
    "primary_fuel": "unit.primary_fuel",
    "secondary_fuel": "unit.secondary_fuel",
    "unit_type": "unit.unit_type",
}

# Filters that get a dropdown whose choices depend on the other filters
FACETS = [
    "facility_name", "state", "county", "source_category",
    "reporting_year", "unit_type", "primary_fuel", "secondary_fuel",
]

# Control filters use a partial match, since one unit can list several controls
CONTROL_FILTERS = {
    "so2_control": "annual_records.so2_control_info",
    "nox_control": "annual_records.nox_control_info",
    "pm_control": "annual_records.pm_control_info",
}

# Numeric filters: form field prefix -> database column
NUMERIC_FILTERS = {
    "operating_time": "annual_records.operating_time",
    "gross_load": "annual_records.gross_load",
    "steam_load": "annual_records.steam_load",
    "heat_input": "annual_records.heat_input",
    "co2_mass": "annual_records.co2_mass",
    "so2_mass": "annual_records.so2_mass",
    "nox_mass": "annual_records.nox_mass",
}


def to_number(value):
    """Turn a form value into a float, or None if it's empty or not a number."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def run_query(query, parameters):
    """Run a query and return a list of dicts like {"Facility": "...", "State": "KY", ...}."""
    connection = connect()
    results = [dict(row) for row in connection.execute(query, parameters).fetchall()]
    connection.close()
    return results


def build_where(filters, exclude=()):
    """
    Build the WHERE clause for the search filters.
    Anything named in `exclude` is skipped, which lets each dropdown
    see what's available given all the *other* filters.
    """
    clauses = ["1=1"]
    parameters = []

    for field, column in TEXT_FILTERS.items():
        value = str(filters.get(field) or "").strip()
        if value and field not in exclude:
            clauses.append(f"{column} = ?")
            parameters.append(value)

    for field, column in CONTROL_FILTERS.items():
        value = str(filters.get(field) or "").strip()
        if value and field not in exclude:
            clauses.append(f"{column} LIKE ?")
            parameters.append(f"%{value}%")

    for field, column in NUMERIC_FILTERS.items():
        if field in exclude:
            continue

        operator = filters.get(f"{field}_operator")
        low = to_number(filters.get(f"{field}_min"))
        high = to_number(filters.get(f"{field}_max"))
        equal = to_number(filters.get(f"{field}_equals"))

        if operator == "Equals" and equal is not None:
            clauses.append(f"{column} = ?")
            parameters.append(equal)

        elif operator == "Greater than" and low is not None:
            clauses.append(f"{column} > ?")
            parameters.append(low)

        elif operator == "Less than" and high is not None:
            clauses.append(f"{column} < ?")
            parameters.append(high)

        elif operator == "Between" and low is not None and high is not None:
            if low > high:
                low, high = high, low
            clauses.append(f"{column} BETWEEN ? AND ?")
            parameters.extend([low, high])

    return " WHERE " + " AND ".join(clauses), parameters


def build_basic_query(**filters):
    """Build the basic search SQL and its parameters from the form fields."""
    where, parameters = build_where(filters)
    query = (
        f"SELECT {RESULT_COLUMNS} {BASE_JOIN} {where}"
        " ORDER BY facility.facility_name, unit.epa_unit_id, annual_records.year"
    )
    return query, parameters


def search_data(**filters):
    query, parameters = build_basic_query(**filters)
    return run_query(query, parameters)


def get_filter_options(limit=100, **filters):
    """
    Everything the search page needs to stay in sync with the data:
      - options: the values still available for each dropdown
      - ranges:  the smallest and largest value for each number filter
      - count:   how many records match right now
      - rows:    the first `limit` matching records
    """
    connection = connect()

    options = {}
    for facet in FACETS:
        column = TEXT_FILTERS[facet]
        where, parameters = build_where(filters, exclude={facet})
        query = (
            f"SELECT DISTINCT {column} AS value {BASE_JOIN} {where}"
            f" AND {column} IS NOT NULL AND {column} != '' ORDER BY value"
        )
        values = [row["value"] for row in connection.execute(query, parameters)]
        if facet == "reporting_year":
            values.sort(reverse=True)
        options[facet] = values

    ranges = {}
    for field, column in NUMERIC_FILTERS.items():
        where, parameters = build_where(filters, exclude={field})
        row = connection.execute(
            f"SELECT MIN({column}) AS low, MAX({column}) AS high {BASE_JOIN} {where}",
            parameters,
        ).fetchone()
        ranges[field] = [row["low"], row["high"]]

    where, parameters = build_where(filters)
    count = connection.execute(f"SELECT COUNT(*) {BASE_JOIN} {where}", parameters).fetchone()[0]
    connection.close()

    query, parameters = build_basic_query(**filters)
    rows = run_query(query + " LIMIT ?", parameters + [int(limit)])

    return {"count": count, "options": options, "ranges": ranges, "rows": rows}


def find_facilities(text, limit=8):
    """Facility names containing `text`, names that start with it first."""
    text = (text or "").strip()
    if not text:
        return []
    connection = connect()
    rows = connection.execute(
        """
        SELECT facility_name, state, COUNT(unit.internal_unit_key) AS units
        FROM facility
        LEFT JOIN unit ON unit.epa_facility_id = facility.epa_facility_id
        WHERE facility_name LIKE ?
        GROUP BY facility.epa_facility_id
        ORDER BY facility_name LIKE ? DESC, facility_name
        LIMIT ?
        """,
        [f"%{text}%", f"{text}%", limit],
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


# Fields the advanced search can rank by: form value -> column header
RANK_FIELDS = {
    "co2_mass": "CO2 (tons)",
    "so2_mass": "SO2 (tons)",
    "nox_mass": "NOx (tons)",
    "gross_load": "Gross Load (MWh)",
    "heat_input": "Heat Input (mmBtu)",
    "operating_time": "Operating Time (hrs)",
}

RANK_FILTERS = ["state", "county", "source_category", "reporting_year",
                "unit_type", "primary_fuel", "secondary_fuel"]


def build_advanced_query(type=None, limit=None, order="DESC", field=None, **filters):
    """Build the advanced search (ranking) SQL and its parameters."""
    order = "ASC" if order == "ASC" else "DESC"

    # Only the dropdown filters apply to rankings
    ranking_filters = {name: filters.get(name) for name in RANK_FILTERS}
    where, parameters = build_where(ranking_filters)

    if type == "Facility":
        # One row per facility, with emissions totaled across its units
        query = f"""
            SELECT
                facility.facility_name             AS "Facility",
                facility.epa_facility_id           AS "Facility ID",
                facility.state                     AS "State",
                facility.county                    AS "County",
                COUNT(DISTINCT unit.internal_unit_key) AS "Units",
                SUM(annual_records.operating_time) AS "Operating Time (hrs)",
                SUM(annual_records.gross_load)     AS "Gross Load (MWh)",
                SUM(annual_records.heat_input)     AS "Heat Input (mmBtu)",
                SUM(annual_records.co2_mass)       AS "CO2 (tons)",
                SUM(annual_records.so2_mass)       AS "SO2 (tons)",
                SUM(annual_records.nox_mass)       AS "NOx (tons)"
            {BASE_JOIN} {where}
            GROUP BY facility.epa_facility_id
        """
    elif type in ("Unit", "Annual Record"):
        query = f"SELECT {RESULT_COLUMNS} {BASE_JOIN} {where}"
    else:
        return None, []

    if field in RANK_FIELDS:
        header = RANK_FIELDS[field]
        # Rows with no value always go last
        query += f' ORDER BY "{header}" IS NULL, "{header}" {order}'

    number = to_number(limit)
    if number is not None and number > 0:
        query += " LIMIT ?"
        parameters.append(int(number))

    return query, parameters


def advance_search(**options):
    query, parameters = build_advanced_query(**options)
    if query is None:
        return []
    return run_query(query, parameters)