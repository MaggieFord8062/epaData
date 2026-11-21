"""
Tests for county breakdowns, maps that zoom to the selection, the single navigation bar, the chart
colors and the small touches (sortable tables, nearby facilities), using the fixture database in
conftest.py. The fixture stores no counties, so the county tests add them for the length of a test.

Alpha Station (1001, KY): CO2 2,340,000 in all years. Beta Plant (1002, KY): 440,000 in 2025.
"""

import contextlib
import math
import sqlite3
from urllib.parse import urlencode

import pytest

import analysis
import dashboard
import explain
import search
import smart_search

COUNTIES = {1001: "Warren County", 1002: "Jefferson County"}


def selection(params=None):
    rows = smart_search.explore(params or {}, everything=True)["rows"]
    return analysis.build_frame(rows)


@contextlib.contextmanager
def counties_stored():
    """Give the two Kentucky facilities a county, then take them away again."""
    connection = sqlite3.connect("epaData.db")
    try:
        for facility_id, county in COUNTIES.items():
            connection.execute("UPDATE facility SET county = ? WHERE epa_facility_id = ?", (county, facility_id))
        connection.commit()
        yield
    finally:
        connection.execute("UPDATE facility SET county = NULL")
        connection.commit()
        connection.close()


# ---------- Counties ----------

def test_county_labels_name_the_state():
    assert "county" in analysis.GROUPS
    with counties_stored():
        labels = analysis.group_labels(selection(), "county")
    assert set(labels) == {"Warren County, KY", "Jefferson County, KY", analysis.NOT_REPORTED}


def test_county_links_open_the_county_in_explore():
    assert explain.drill_for("county", "Warren County, KY") == {"county": "Warren County", "state": "KY"}
    assert explain.drill_for("county", analysis.NOT_REPORTED) is None


def test_bars_by_county_with_the_headline_bar_in_black():
    with counties_stored():
        spec = dashboard.bars(selection({"state": "KY"}), "co2_mass", "county")
    trace = spec["data"][0]
    assert trace["y"] == ["Warren County, KY", "Jefferson County, KY"]
    assert trace["x"] == [2_340_000, 440_000]
    assert trace["marker"]["color"] == [dashboard.BLACK, dashboard.REST]
    assert spec["headline"]["context"].startswith("Warren County, KY")


def test_one_state_gets_a_county_map_zoomed_to_it():
    with counties_stored():
        kentucky = selection({"state": "KY"})
        assert dashboard.one_state(kentucky)
        spec = dashboard.region_map(kentucky, "co2_mass")
        assert not dashboard.one_state(selection())      # two states: the state map
        assert dashboard.region_map(selection(), "co2_mass")["id"] == "state_map"
    assert spec["id"] == "county_map"
    assert len(spec["data"][0]["lat"]) == 2
    assert spec["layout"]["geo"]["projection"]["scale"] > 1
    # Without counties a one-state selection keeps the state map
    assert not dashboard.one_state(selection({"state": "KY"}))
    assert dashboard.region_map(selection({"state": "KY"}), "co2_mass")["id"] == "state_map"


def test_maps_zoom_only_to_small_areas():
    figure = dashboard.map_layout("Test", "#f5f5f7")
    assert dashboard.zoom_to(figure, [37.0, 38.2], [-86.4, -85.7])
    assert figure["geo"]["center"] == pytest.approx({"lat": 37.6, "lon": -86.05})
    assert figure["geo"]["projection"]["type"] == "albers usa"
    national = dashboard.map_layout("Test", "#f5f5f7")
    assert not dashboard.zoom_to(national, [25.0, 48.0], [-120.0, -70.0])
    assert "center" not in national["geo"]


def test_dashboard_compares_counties_within_one_state(client):
    with counties_stored():
        page = client.get("/dashboard?state=KY").get_data(as_text=True)
    assert "Compared by county." in page
    assert 'id="spec-county_map"' in page
    # Without counties, or across states, it compares states
    assert "Compared by state." in client.get("/dashboard?state=KY").get_data(as_text=True)
    assert "Compared by state." in client.get("/dashboard").get_data(as_text=True)


def test_comparison_by_county(client):
    query = urlencode({"cmp": "county", "a": "Warren County, KY", "b": "Jefferson County, KY",
                       "variable": "co2_mass"})
    with counties_stored():
        response = client.get("/comparison?" + query)
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Warren County, KY" in page and "Jefferson County, KY" in page


# ---------- Navigation ----------

def test_one_navigation_bar_that_keeps_the_selection(client):
    page = client.get("/dashboard?state=KY").get_data(as_text=True)
    assert 'class="ln' not in page and "gn-brand" not in page     # no second bar, no logo
    assert '<a class="gn-link" href="/"' in page and '<li><a href="/">Home</a></li>' in page
    assert 'href="/statistics?state=KY' in page                   # other pages keep the selection
    assert "data-copy-link" in page                                # Copy link
    assert 'class="gn-item gn-title" aria-hidden="true">Dashboard<' in page


# ---------- Small touches ----------

def test_chart_tables_can_be_sorted(client):
    page = client.get("/dashboard?state=KY").get_data(as_text=True)
    assert "data-sortable" in page
    assert 'class="num" data-value="2340000' in page
    assert "/static/touches.js" in page
    assert "data-count-up" in page


def test_headline_marks_are_black_and_the_rest_gray():
    high, low = dashboard.rankings(selection(), "co2_mass", "facility")
    for spec in (high, low):
        colors = spec["data"][0]["marker"]["color"]
        assert colors[0] == dashboard.BLACK and set(colors[1:]) <= {dashboard.REST}
    histogram = dashboard.histogram(selection(), "co2_mass", "log")
    assert histogram["data"][0]["marker"]["color"] == dashboard.REST
    assert histogram["layout"]["shapes"][0]["line"]["color"] == dashboard.BLACK


def test_distance_in_miles():
    assert search.miles_between(0, 0, 1, 0) == pytest.approx(math.pi * 3958.8 / 180)   # one degree of latitude
    assert search.miles_between(37.0, -86.4, 37.0, -86.4) == 0


def test_nearby_facilities(client):
    nearby = search.nearby_facilities(1001, 37.0, -86.4)
    assert [item["facility_id"] for item in nearby] == [1002]      # Gamma has no location
    assert nearby[0]["miles"] == pytest.approx(search.miles_between(37.0, -86.4, 38.2, -85.7))
    assert nearby[0]["year"] == 2025 and nearby[0]["co2"] == 440_000
    assert search.nearby_facilities(2001, None, None) == []
    page = client.get("/facility/1001").get_data(as_text=True)
    assert "Nearby" in page and "Beta Plant" in page
    assert "/compare?facility=1001&amp;facility=1002" in page
    assert "Nearby" not in client.get("/facility/2001").get_data(as_text=True)
