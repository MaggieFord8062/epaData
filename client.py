import requests

class CAMPDClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def get_data(self, year, state=None):
        url = "https://api.epa.gov/easey/emissions-mgmt/emissions/apportioned/annual"
        all_items = []
        page = 1

        while True:
            params = {
            "api_key": self.api_key,
            "year": year,
            "page": page,
            "perPage": 500
            }

            if state:
                params["stateCode"] = state

            response = requests.get(url, params=params)
            batch = response.json()

            if not batch.get("items"):
                break

            all_items.extend(batch["items"])

            if len(batch["items"]) < 500:
                break

            page += 1

        return {"items": all_items}

