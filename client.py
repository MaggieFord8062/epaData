import requests

class CAMPDClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def get_data(self, year, state=None):
        url = "https://api.epa.gov/easey/emissions-mgmt/emissions/apportioned/annual"

        params = {
            "api_key": self.api_key,
            "year": year,
            "page": 1,
            "perPage": 100
        }

        if state:
            params["stateCode"] = state

        response = requests.get(url, params=params)

        print("Status:", response.status_code)

        return response.json()

