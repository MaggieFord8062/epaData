import os
import pandas as pd
from dotenv import load_dotenv
from client import CAMPDClient

load_dotenv()

api_key = os.getenv("CAMPD_API_KEY")

print("API key loaded:", api_key is not None)
print("API key length:", len(api_key) if api_key else 0)

client = CAMPDClient(api_key)

data = client.get_data(2024, "KY")

df = pd.DataFrame(data["items"])

print("Number of records:", len(df))
print("\nColumns:")
print(df.columns.tolist())

print("\nFirst 5 records:")
print(df.head())

print("\nMissing values per column:")
print(df.isnull().sum())

print("\nData types:")
print(df.dtypes)

print("\nDuplicate facility-unit-year combos:")
dupes = df.duplicated(subset=["facilityId", "unitId", "year"]).sum()
print(dupes)

data_tx = client.get_data(2024, "TX")
df_tx = pd.DataFrame(data_tx["items"])
print(set(df.columns) == set(df_tx.columns))
print("TX records fetched:", len(df_tx))
print("TX total available:", data_tx.get("recordCount") or data_tx.get("totalRecords") or "check response keys")