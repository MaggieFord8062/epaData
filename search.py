import sqlite3

def search_data (
    epa_facility_id=None,
    facility_name=None,
    epa_unit_id=None,
    state=None,
    county=None,
    latitude=None,
    longitude=None,
    source_category=None,
    reporting_year=None,
    primary_fuel=None,
    secondary_fuel=None,
    unit_type=None,
    operating_time_operator=None,
    operating_time_equals=None,
    operating_time_min=None,
    operating_time_max=None,
    gross_load_operator=None,
    gross_load_equals=None,
    gross_load_min=None,
    gross_load_max=None,
    steam_load_operator=None,
    steam_load_equals=None,
    steam_load_min=None,
    steam_load_max=None,
    heat_input_operator=None,
    heat_input_equals=None,
    heat_input_min=None,
    heat_input_max=None,
    co2_mass_operator=None,
    co2_mass_equals=None,
    co2_mass_min=None,
    co2_mass_max=None,
    so2_mass_operator=None,
    so2_mass_equals=None,
    so2_mass_min=None,
    so2_mass_max=None,
    nox_mass_operator=None,
    nox_mass_equals=None,
    nox_mass_min=None,
    nox_mass_max=None,
    so2_control=None,
    nox_control=None,
    pm_control=None
):

    connection = sqlite3.connect("epaData.db")
    cursor = connection.cursor()

    query = """
        SELECT *
        FROM facility 
        JOIN unit 
            ON facility.epa_facility_id = unit.epa_facility_id
        JOIN annual_records 
            ON unit.internal_unit_key = annual_records.internal_unit_key
        WHERE 1=1
    """
    parameters = []

    if epa_facility_id:
        query += " AND facility.epa_facility_id = ?"
        parameters.append(epa_facility_id)

    if facility_name:
        query += " AND facility.facility_name = ?"
        parameters.append(facility_name)

    if epa_unit_id:
        query += " AND unit.epa_unit_id = ?"
        parameters.append(epa_unit_id)

    if state:
        query += " AND facility.state = ?"
        parameters.append(state)

    if county:
        query += " AND facility.county = ?"
        parameters.append(county)

    if latitude:
        query += " AND facility.latitude = ?"
        parameters.append(latitude)

    if longitude:
        query += " AND facility.longitude = ?"
        parameters.append(longitude)

    if source_category:
        query += " AND facility.source_category = ?"
        parameters.append(source_category)

    if reporting_year:
        query += " AND annual_records.year = ?"
        parameters.append(reporting_year)

    if primary_fuel:
        query += " AND unit.primary_fuel = ?"
        parameters.append(primary_fuel)

    if secondary_fuel:
        query += " AND unit.secondary_fuel = ?"
        parameters.append(secondary_fuel)

    if unit_type:
        query += " AND unit.unit_type = ?"
        parameters.append(unit_type)

    if operating_time_operator == "Equals":
        query += " AND annual_records.operating_time = ?"
        parameters.append(operating_time_equals)

    elif operating_time_operator == "Less than":
        query += " AND annual_records.operating_time < ?"
        parameters.append(operating_time_max)

    elif operating_time_operator == "Greater than":
        query += " AND annual_records.operating_time > ?"
        parameters.append(operating_time_min)

    elif operating_time_operator == "Between":
        query += " AND annual_records.operating_time BETWEEN ? AND ?"
        parameters.append(operating_time_max)
        parameters.append(operating_time_min)

    if gross_load_operator == "Equals":
        query += " AND annual_records.gross_load = ?"
        parameters.append(gross_load_equals)

    elif gross_load_operator == "Less than":
        query += " AND annual_records.gross_load < ?"
        parameters.append(gross_load_max)

    elif gross_load_operator == "Greater than":
        query += " AND annual_records.gross_load > ?"
        parameters.append(gross_load_min)

    elif gross_load_operator == "Between":
        query += " AND annual_records.gross_load BETWEEN ? AND ?"
        parameters.append(gross_load_max)
        parameters.append(gross_load_min)

    if steam_load_operator == "Equals":
        query += " AND annual_records.steam_load = ?"
        parameters.append(steam_load_equals)

    elif steam_load_operator == "Less than":
        query += " AND annual_records.steam_load < ?"
        parameters.append(steam_load_max)

    elif steam_load_operator == "Greater than":
        query += " AND annual_records.steam_load > ?"
        parameters.append(steam_load_min)

    elif steam_load_operator == "Between":
        query += " AND annual_records.steam_load BETWEEN ? AND ?"
        parameters.append(steam_load_max)
        parameters.append(steam_load_min)

    if heat_input_operator == "Equals":
        query += " AND annual_records.heat_input = ?"
        parameters.append(heat_input_equals)

    elif heat_input_operator == "Less than":
        query += " AND annual_records.heat_input < ?"
        parameters.append(heat_input_max)

    elif heat_input_operator == "Greater than":
        query += " AND annual_records.heat_input > ?"
        parameters.append(heat_input_min)

    elif heat_input_operator == "Between":
        query += " AND annual_records.heat_input BETWEEN ? AND ?"
        parameters.append(heat_input_max)
        parameters.append(heat_input_min)

    if co2_mass_operator == "Equals":
        query += " AND annual_records.co2_mass = ?"
        parameters.append(co2_mass_equals)

    elif co2_mass_operator == "Less than":
        query += " AND annual_records.co2_mass < ?"
        parameters.append(co2_mass_max)

    elif co2_mass_operator == "Greater than":
        query += " AND annual_records.co2_mass > ?"
        parameters.append(co2_mass_min)

    elif co2_mass_operator == "Between":
        query += " AND annual_records.co2_mass BETWEEN ? AND ?"
        parameters.append(co2_mass_max)
        parameters.append(co2_mass_min)

    if so2_mass_operator == "Equals":
        query += " AND annual_records.so2_mass = ?"
        parameters.append(so2_mass_equals)

    elif so2_mass_operator == "Less than":
        query += " AND annual_records.so2_mass < ?"
        parameters.append(so2_mass_max)

    elif so2_mass_operator == "Greater than":
        query += " AND annual_records.so2_mass > ?"
        parameters.append(so2_mass_min)

    elif so2_mass_operator == "Between":
        query += " AND annual_records.so2_mass BETWEEN ? AND ?"
        parameters.append(so2_mass_max)
        parameters.append(so2_mass_min)

    if nox_mass_operator == "Equals":
        query += " AND annual_records.nox_mass = ?"
        parameters.append(nox_mass_equals)

    elif nox_mass_operator == "Less than":
        query += " AND annual_records.nox_mass < ?"
        parameters.append(nox_mass_max)

    elif nox_mass_operator == "Greater than":
        query += " AND annual_records.nox_mass > ?"
        parameters.append(nox_mass_min)

    elif nox_mass_operator == "Between":
        query += " AND annual_records.nox_mass BETWEEN ? AND ?"
        parameters.append(nox_mass_max)
        parameters.append(nox_mass_min)

    if so2_control:
        query += " AND annual_records.so2_control_info = ?"
        parameters.append(so2_control)

    if nox_control:
        query += " AND annual_records.nox_control_info = ?"
        parameters.append(nox_control)

    if pm_control:
        query += " AND annual_records.pm_control_info = ?"
        parameters.append(pm_control)


    cursor.execute(query, parameters)
    results = cursor.fetchall()

    connection.close()

    return results
def advance_search (
    type=None,
    limit=None,
    order="DESC",
    field=None,
    state=None,
    county=None,
    source_category=None,
    unit_type=None,
    primary_fuel=None,
    secondary_fuel=None,
    reporting_year=None,
    operating_time=None,
    gross_load=None,
    heat_input=None,
    co2_mass=None,
    so2_mass=None,
    nox_mass=None,
):
    connection = sqlite3.connect("epaData.db")
    cursor = connection.cursor()

    allowed_fields = {"co2_mass", "so2_mass", "nox_mass", "gross_load", "heat_input", "operating_time"}
    allowed_orders = {"ASC", "DESC"}

    if order not in allowed_orders:
        order = "DESC"

    parameters = []

    if type == "Facility":
        query = "SELECT * FROM facility WHERE 1=1"

        if state:
            query += " AND state = ?"
            parameters.append(state)

        if county:
            query += " AND county = ?"
            parameters.append(county)

        if source_category:
            query += " AND source_category = ?"
            parameters.append(source_category)

    elif type == "Unit":
        query = """
            SELECT *
            FROM unit
            JOIN facility ON unit.epa_facility_id = facility.epa_facility_id
            WHERE 1=1
        """

        if unit_type:
            query += " AND unit.unit_type = ?"
            parameters.append(unit_type)

        if primary_fuel:
            query += " AND unit.primary_fuel = ?"
            parameters.append(primary_fuel)

        if secondary_fuel:
            query += " AND unit.secondary_fuel = ?"
            parameters.append(secondary_fuel)

        if state:
            query += " AND facility.state = ?"
            parameters.append(state)

        if county:
            query += " AND facility.county = ?"
            parameters.append(county)

        if source_category:
            query += " AND facility.source_category = ?"
            parameters.append(source_category)

    elif type == "Annual Record":
        query = "SELECT * FROM annual_records WHERE 1=1"

        if reporting_year:
            query += " AND year = ?"
            parameters.append(reporting_year)

        if operating_time:
            query += " AND operating_time = ?"
            parameters.append(operating_time)

        if gross_load:
            query += " AND gross_load = ?"
            parameters.append(gross_load)

        if heat_input:
            query += " AND heat_input = ?"
            parameters.append(heat_input)

        if co2_mass:
            query += " AND co2_mass = ?"
            parameters.append(co2_mass)

        if so2_mass:
            query += " AND so2_mass = ?"
            parameters.append(so2_mass)

        if nox_mass:
            query += " AND nox_mass = ?"
            parameters.append(nox_mass)

    else:
        return []

    if field in allowed_fields and type == "Annual Record":
        query += f" ORDER BY {field} {order}"

    if limit:
        try:
            limit = int(limit)
            query += " LIMIT ?"
            parameters.append(limit)
        except ValueError:
            pass

    cursor.execute(query, parameters)
    results = cursor.fetchall()

    connection.close()

    return results