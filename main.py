import os
from dotenv import load_dotenv
from client import CAMPDClient

load_dotenv()

api_key = os.getenv("CAMPD_API_KEY")

print("API key loaded:", api_key is not None)
print("API key length:", len(api_key) if api_key else 0)

client = CAMPDClient(api_key)

data = client.get_data(2025, "KY")

print(data)
