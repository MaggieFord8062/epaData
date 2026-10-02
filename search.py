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
    annual_records.program_code     AS "Programs",
    unit.internal_unit_key          AS "_unit_key"
"""
# Columns starting with "_" are used for links (like the unit detail page)
# and are never shown in tables or written to CSV files.

BASE_JOIN = """
    FROM facility
    JOIN unit
        ON facility.epa_facility_id = unit.epa_facility_id
    JOIN annual_records
        ON unit.internal_unit_key = annual_records.internal_unit_key
"""

# Text filters: form field name -> database column (exact match)
TEXT_FILTERS = {
    "unit_key": "unit.internal_unit_key",
    "dataset_id": "annual_records.dataset_id",
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
    "year": "annual_records.year",
}

# Columns the search results can be sorted by: URL value -> database column
SORT_COLUMNS = {
    "facility": "facility.facility_name",
    "state": "facility.state",
    "county": "facility.county",
    "unit": "unit.epa_unit_id",
    "year": "annual_records.year",
    "unit_type": "unit.unit_type",
    "primary_fuel": "unit.primary_fuel",
    "secondary_fuel": "unit.secondary_fuel",
    "operating_time": "annual_records.operating_time",
    "gross_load": "annual_records.gross_load",
    "steam_load": "annual_records.steam_load",
    "heat_input": "annual_records.heat_input",
    "co2_mass": "annual_records.co2_mass",
    "so2_mass": "annual_records.so2_mass",
    "nox_mass": "annual_records.nox_mass",
}

DEFAULT_ORDER = "facility.facility_name, unit.epa_unit_id, annual_records.year"

PER_PAGE_CHOICES = [25, 50, 100, 250]
DEFAULT_PER_PAGE = 50


def to_number(value):
    """Turn a form value into a float, or None if it's empty or not a number."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def to_positive_int(value, default):
    """Turn a form value into a whole number of at least 1, or use the default."""
    number = to_number(value)
    if number is None or number < 1:
        return default
    return int(number)


def order_clause(sort, direction):
    """
    ORDER BY for the chosen column. Only names in SORT_COLUMNS are allowed,
    so nothing typed into the URL can end up in the SQL.
    Rows with no value always go last, whichever direction is chosen.
    """
    column = SORT_COLUMNS.get(sort)
    if column is None:
        return f" ORDER BY {DEFAULT_ORDER}"
    direction = "DESC" if str(direction).lower() == "desc" else "ASC"
    return f" ORDER BY {column} IS NULL, {column} {direction}, {DEFAULT_ORDER}"


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

    # One control technology in any of the SO2, NOx or PM control fields (used for retrieval queries)
    control = str(filters.get("control_any") or "").strip()
    if control and "control_any" not in exclude:
        clauses.append(
            "(annual_records.so2_control_info LIKE ? OR annual_records.nox_control_info LIKE ?"
            " OR annual_records.pm_control_info LIKE ?)"
        )
        parameters.extend([f"%{control}%"] * 3)

    # Year range, used by historical search (e.g. 2015 through 2025)
    year_from = to_number(filters.get("year_from"))
    year_to = to_number(filters.get("year_to"))
    if year_from is not None and "year_from" not in exclude:
        clauses.append("annual_records.year >= ?")
        parameters.append(int(year_from))
    if year_to is not None and "year_to" not in exclude:
        clauses.append("annual_records.year <= ?")
        parameters.append(int(year_to))

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
    """Build the basic search SQL and its parameters from the form fields, sorted as requested."""
    where, parameters = build_where(filters)
    query = f"SELECT {RESULT_COLUMNS} {BASE_JOIN} {where}"
    query += order_clause(filters.get("sort"), filters.get("dir"))
    return query, parameters


def search_data(**filters):
    query, parameters = build_basic_query(**filters)
    return run_query(query, parameters)


def get_filter_options(**filters):
    """
    Everything the search page needs to stay in sync with the data:
      - options: the values still available for each dropdown
      - ranges:  the smallest and largest value for each number filter
      - count:   how many records match right now
      - rows:    one page of matching records, sorted as requested
      - page, pages, per_page: where that page sits in the full results
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

    per_page = to_positive_int(filters.get("per_page"), DEFAULT_PER_PAGE)
    if per_page not in PER_PAGE_CHOICES:
        per_page = DEFAULT_PER_PAGE
    pages = max(1, -(-count // per_page))  # round up
    page = min(to_positive_int(filters.get("page"), 1), pages)

    query, parameters = build_basic_query(**filters)
    rows = run_query(query + " LIMIT ? OFFSET ?", parameters + [per_page, (page - 1) * per_page])

    return {
        "count": count,
        "options": options,
        "ranges": ranges,
        "rows": rows,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }


def find_facilities(text, limit=8):
    """Facility names containing `text`, names that start with it first."""
    text = (text or "").strip()
    if not text:
        return []
    connection = connect()
    rows = connection.execute(
        """
        SELECT facility.epa_facility_id, facility_name, state, COUNT(unit.internal_unit_key) AS units
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


RANK_GROUPS = {
    "state": "State",
}


def build_advanced_query(type=None, limit=None, order="DESC", field=None, **filters):
    """Build the advanced search (ranking) SQL and its parameters, without any row limit."""
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

    header = RANK_FIELDS.get(field, RANK_FIELDS["co2_mass"])
    # Rows with no value always go last
    query += f' ORDER BY "{header}" IS NULL, "{header}" {order}'

    return query, parameters


def advance_search(limit=None, group=None, **options):
    """
    Rankings. With no group, the top (or bottom) N overall.
    With group="state", the top (or bottom) N within each state, e.g. the top CO2 facility in every state.
    """
    query, parameters = build_advanced_query(**options)
    if query is None:
        return []

    number = to_positive_int(limit, 10)
    group_column = RANK_GROUPS.get(group)

    if group_column is None:
        return run_query(query + " LIMIT ?", parameters + [number])

    # Rows are already in ranked order, so keep the first N rows seen for each group
    ranked = []
    count_in_group = {}
    for row in run_query(query, parameters):
        key = row.get(group_column)
        position = count_in_group.get(key, 0) + 1
        count_in_group[key] = position
        if position <= number:
            ranked.append(dict({f"Rank in {group_column}": position}, **row))

    ranked.sort(key=lambda row: (str(row.get(group_column) or ""), row[f"Rank in {group_column}"]))
    return ranked


# ---------- Facility comparison ----------

COMPARE_LIMIT = 4


def compare_facilities(facility_ids, year):
    """
    Side-by-side totals for a few facilities in one year, plus every unit's numbers
    and each facility's CO2 in every year on record.
    """
    facility_ids = [int(fid) for fid in facility_ids if str(fid).strip().isdigit()][:COMPARE_LIMIT]
    if not facility_ids:
        return {"facilities": [], "units": [], "trend": {}, "years": []}

    marks = ", ".join("?" for _ in facility_ids)
    connection = connect()

    summary_rows = connection.execute(
        f"""
        SELECT
            facility.epa_facility_id AS facility_id,
            facility.facility_name   AS name,
            facility.state, facility.county, facility.source_category,
            COUNT(annual_records.annual_record_id) AS units_reporting,
            SUM(annual_records.operating_time) AS operating_time,
            SUM(annual_records.gross_load)     AS gross_load,
            SUM(annual_records.heat_input)     AS heat_input,
            SUM(annual_records.co2_mass)       AS co2,
            SUM(annual_records.so2_mass)       AS so2,
            SUM(annual_records.nox_mass)       AS nox
        FROM facility
        LEFT JOIN annual_records
            ON annual_records.epa_facility_id = facility.epa_facility_id
            AND annual_records.year = ?
        WHERE facility.epa_facility_id IN ({marks})
        GROUP BY facility.epa_facility_id
        """,
        [year] + facility_ids,
    ).fetchall()

    # Keep the order the user picked them in
    by_id = {row["facility_id"]: dict(row) for row in summary_rows}
    facilities = [by_id[fid] for fid in facility_ids if fid in by_id]
    for facility in facilities:
        # Tons of CO2 per MWh generated: lower means cleaner electricity
        if facility["co2"] is not None and facility["gross_load"]:
            facility["co2_per_mwh"] = facility["co2"] / facility["gross_load"]
        else:
            facility["co2_per_mwh"] = None

    unit_query = (
        f"SELECT {RESULT_COLUMNS} {BASE_JOIN}"
        f" WHERE facility.epa_facility_id IN ({marks}) AND annual_records.year = ?"
    )
    units = [dict(row) for row in connection.execute(unit_query, facility_ids + [year]).fetchall()]
    position = {fid: index for index, fid in enumerate(facility_ids)}
    units.sort(key=lambda row: (position.get(row["Facility ID"], 99), -(row["CO2 (tons)"] or 0)))

    trend_rows = connection.execute(
        f"""
        SELECT epa_facility_id, year, SUM(co2_mass) AS co2
        FROM annual_records
        WHERE epa_facility_id IN ({marks})
        GROUP BY epa_facility_id, year
        """,
        facility_ids,
    ).fetchall()
    connection.close()

    trend = {}
    for row in trend_rows:
        trend.setdefault(row["year"], {})[row["epa_facility_id"]] = row["co2"]
    years = sorted(trend.keys(), reverse=True)

    return {"facilities": facilities, "units": units, "trend": trend, "years": years}


# ---------- Historical search ----------

def facility_units(facility_id):
    """Every unit at a facility, with the years it has data for."""
    connection = connect()
    rows = connection.execute(
        """
        SELECT unit.internal_unit_key AS unit_key, unit.epa_unit_id AS unit_id,
               unit.unit_type, unit.primary_fuel,
               MIN(annual_records.year) AS first_year, MAX(annual_records.year) AS last_year
        FROM unit
        LEFT JOIN annual_records ON annual_records.internal_unit_key = unit.internal_unit_key
        WHERE unit.epa_facility_id = ?
        GROUP BY unit.internal_unit_key
        ORDER BY unit.epa_unit_id
        """,
        [facility_id],
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]