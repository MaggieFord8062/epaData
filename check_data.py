import sqlite3

connection = sqlite3.connect("sqData.db")
cursor = connection.cursor()

for table in ["dataset", "facility", "unit"]:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]

    print(f"{table}: {count} rows")

connection.close()