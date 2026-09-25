import os
import sqlite3

DB_PATH = "epaData.db"

if not os.path.exists(DB_PATH):
    print(f"{DB_PATH} not found. Run `python ingest.py` first.")
    raise SystemExit(1)

print("Data source: EPA CAMPD API (apportioned annual emissions)")
print(f"Stored in:   {os.path.abspath(DB_PATH)}")
print(f"File size:   {os.path.getsize(DB_PATH) / 1024:.1f} KB\n")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("Row counts:")
for table in ["facility", "unit", "annual_records"]:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"  {table:<15} {cur.fetchone()[0]}")

print("\nRecords by state and year:")
cur.execute("""
    SELECT f.state, a.year, COUNT(*)
    FROM annual_records a
    JOIN facility f ON a.epa_facility_id = f.epa_facility_id
    GROUP BY f.state, a.year
    ORDER BY f.state, a.year
""")
for state, year, count in cur.fetchall():
    print(f"  {state} {year}: {count} records")

print("\nTop 5 units by CO2 mass:")
cur.execute("""
    SELECT f.facility_name, f.state, u.epa_unit_id, a.year, a.co2_mass
    FROM annual_records a
    JOIN unit u ON a.internal_unit_key = u.internal_unit_key
    JOIN facility f ON a.epa_facility_id = f.epa_facility_id
    WHERE a.co2_mass IS NOT NULL
    ORDER BY a.co2_mass DESC
    LIMIT 5
""")
for name, state, unit, year, co2 in cur.fetchall():
    print(f"  {name} ({state}), unit {unit}, {year}: {co2:,.1f} tons CO2")

conn.close()