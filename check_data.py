import sqlite3
import os

print("Database file:", os.path.abspath("sqData.db"))

connection = sqlite3.connect("sqData.db")
cursor = connection.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")

tables = cursor.fetchall()

print("Tables in this database:")

for table in tables:
    print(table[0])

connection.close()