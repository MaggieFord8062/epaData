"""
client.py
Talks to EPA's CAM API. The API key comes from the caller (read from .env),
so it's never written in the code, sent to the browser, or committed to GitHub.
"""
import time

import requests

BASE_URL = "https://api.epa.gov/easey"
EMISSIONS_URL = f"{BASE_URL}/emissions-mgmt/emissions/apportioned/annual"
ATTRIBUTES_URL = f"{BASE_URL}/facilities-mgmt/facilities/attributes"

PER_PAGE = 500


class CAMPDError(Exception):
    """The API returned an error or something we couldn't read."""


class CAMPDClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def _get_all_pages(self, url, params, on_page=None):
        """
        Request every page of results and return them as one list.
        on_page, if given, is called with the running total after each page (used for progress messages).
        """
        all_items = []
        page = 1

        while True:
            request_params = dict(params, api_key=self.api_key, page=page, perPage=PER_PAGE)
            batch = self._get_with_retry(url, request_params)

            # The API has returned both {"items": [...]} and a plain list, so accept either
            if isinstance(batch, list):
                items = batch
            else:
                items = batch.get("items") or []

            if not items:
                break

            all_items.extend(items)
            if on_page is not None:
                on_page(len(all_items))

            if len(items) < PER_PAGE:
                break

            page += 1

        return all_items

    def _get_with_retry(self, url, params, attempts=3):
        """One request, retried a few times if the API is busy or briefly down."""
        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(url, params=params, timeout=60)
            except requests.RequestException as error:
                if attempt == attempts:
                    raise CAMPDError(f"Could not reach the CAM API: {error}")
                time.sleep(2 * attempt)
                continue

            if response.status_code in (429, 500, 502, 503, 504) and attempt < attempts:
                time.sleep(2 * attempt)
                continue

            if response.status_code != 200:
                raise CAMPDError(f"CAM API returned HTTP {response.status_code}: {response.text[:200]}")

            try:
                return response.json()
            except ValueError:
                raise CAMPDError("CAM API returned something that isn't JSON")

        raise CAMPDError("CAM API request failed")

    def get_data(self, year, state=None, on_page=None, **filters):
        """
        Annual emissions: one row per unit per year.
        Optional filters use CAM API parameter names, e.g. stateCode="KY", unitFuelType="Coal".
        """
        params = {"year": year}
        if state:
            params["stateCode"] = state
        params.update({key: value for key, value in filters.items() if value})
        return {"items": self._get_all_pages(EMISSIONS_URL, params, on_page)}

    def get_facility_attributes(self, year, state=None, on_page=None, **filters):
        """
        Facility and unit attributes: county, latitude/longitude, source category,
        commercial operation date and operating status, one row per unit per year.
        """
        params = {"year": year}
        if state:
            params["stateCode"] = state
        params.update({key: value for key, value in filters.items() if value})
        return {"items": self._get_all_pages(ATTRIBUTES_URL, params, on_page)}