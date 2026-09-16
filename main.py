import os
import pandas as pd
from dotenv import load_dotenv
from client import CAMPDClient

load_dotenv()

api_key = os.getenv("CAMPD_API_KEY")

print("API key loaded:", api_key is not None)
print("API key length:", len(api_key) if api_key else 0)

client = CAMPDClient(api_key)

# -------------------------
# Kentucky
# -------------------------
data_ky = client.get_data(2024, "KY")
df_ky = pd.DataFrame(data_ky["items"])

print("\n================ KY ================")
print("Number of records:", len(df_ky))

print("\nColumns:")
print(df_ky.columns.tolist())

print("\nFirst 5 records:")
print(df_ky.head())

print("\nMissing values per column:")
print(df_ky.isnull().sum())

print("\nData types:")
print(df_ky.dtypes)

print("\nDuplicate facility-unit-year combos:")
dupes_ky = df_ky.duplicated(
    subset=["facilityId", "unitId", "year"]
).sum()
print(dupes_ky)


# -------------------------
# Texas
# -------------------------
data_tx = client.get_data(2024, "TX")
df_tx = pd.DataFrame(data_tx["items"])

print("\n================ TX ================")
print("Number of records:", len(df_tx))

print("\nFirst 5 records:")
print(df_tx.head())

print("\nMissing values per column:")
print(df_tx.isnull().sum())

print("\nDuplicate facility-unit-year combos:")
dupes_tx = df_tx.duplicated(
    subset=["facilityId", "unitId", "year"]
).sum()
print(dupes_tx)


# -------------------------
# Compare KY and TX
# -------------------------
print("\n================ COMPARISON ================")

print("Same columns:", set(df_ky.columns) == set(df_tx.columns))

print("KY records:", len(df_ky))
print("TX records:", len(df_tx))
print("Total records:", len(df_ky) + len(df_tx))

print("\nAPI response keys:")
print(data_ky.keys())

print("\nKY record count from API:")
print(data_ky.get("recordCount") or data_ky.get("totalRecords"))

print("\nTX record count from API:")
print(data_tx.get("recordCount") or data_tx.get("totalRecords"))


# -------------------------
# Show selected useful fields
# -------------------------
print("\n================ SAMPLE DATA ================")

columns_to_show = [
    "facilityId",
    "facilityName",
    "stateCode",
    "unitId",
    "unitType",
    "primaryFuelInfo",
    "year",
    "sumOpTime",
    "grossLoad",
    "heatInput",
    "co2Mass",
    "so2Mass",
    "noxMass"
]

available_columns = [
    col for col in columns_to_show
    if col in df_ky.columns
]

print(pd.concat([
    df_ky[available_columns],
    df_tx[available_columns]
]).head(10).to_string(index=False))