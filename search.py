import sqlite3
print(sqlite3.sqlite_version)

# def search_data (
#     facility_id=None,
#     facility_name=None,
#     unit_id=None,
#     state=None,
#     county=None,
#     reporting_year=None,
#     primary_fuel=None,
#     secondary_fuel=None,
#     unit_type=None,
#     so2_control=None,
#     nox_control=None,
#     pm_control=None
# ):

# connection = sqlite3.connect("sqData.db")
# cursor = connection.cursor()

# query = """
#     SELECT *
#     FROM facility AS f
#     JOIN unit AS u
#         ON f.epa_facility_id = u.epa_facility_id
        

