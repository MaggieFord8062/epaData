import sqlite3

connection = sqlite3.connect("sqData.db")

cursor = connection.cursor()

cursor.execute("""
CREATE TABLE dataset (
    dataset_id INTEGER PRIMARY KEY,
    dataset_name TEXT,
    data_source TEXT,
    reporting_year TEXT,
    retrieval_date TEXT,
    og_filename TEXT,
    num_raw_records TEXT,
    num_accepted_records TEXT,
    notes TEXT
);
""")

cursor.execute("""
CREATE TABLE facility (
    epa_facility_id INTEGER PRIMARY KEY,
    facility_name TEXT,
    state TEXT,
    county TEXT,
    latitude TEXT,
    longitude TEXT,
    source_category TEXT
);
""")

cursor.execute("""
CREATE TABLE unit (
    internal_unit_key INTEGER PRIMARY KEY,
    epa_facility_id INTEGER,
    epa_unit_id INTEGER,
    unit_type TEXT,
    primary_fuel TEXT,
    secondary_fuel TEXT,
    operating_date TEXT,
    retirement_date TEXT,
    FOREIGN KEY (epa_facility_id) REFERENCES facility(epa_facility_id)
);
""")

cursor.execute("""
CREATE TABLE annual_records (
    annual_record_id INTEGER PRIMARY KEY,
    operating_time REAL,
    gross_load REAL,
    steam_load REAL,
    heat_input REAL,
    co2_mass REAL,
    so2_mass REAL,
    nox_mass REAL,
    so2_control_info TEXT,
    nox_control_info TEXT,
    pm_control_info TEXT,
    program_code TEXT
);
""")

cursor.execute("""
CREATE TABLE traci_factors (
);
""")

cursor.execute("""
CREATE TABLE uploaded_files (
);
""")

cursor.execute("""
CREATE TABLE data_provenance (
);
""")

cursor.execute("""
CREATE TABLE indicator_definitions (
);
""")

cursor.execute("""
CREATE TABLE calculated_indicators (
);
""")

cursor.execute("""
CREATE TABLE weight_scenarios (
);
""")

cursor.execute("""
CREATE TABLE scenario_weights (
);
""")

cursor.execute("""
CREATE TABLE score_results (
);
""")

connection.commit()

connection.close()

