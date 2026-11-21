"""
Tests for county breakdowns, maps that zoom to the selection, the single navigation bar, the chart
colors and the small touches (sortable tables, nearby facilities), using the fixture database in
conftest.py. The fixture stores no counties, so the county tests add them for the length of a test.

Alpha Station (1001, KY): CO2 2,340,000 in all years. Beta Plant (1002, KY): 440,000 in 2025.
"""

import contextlib
import json
import math
import re
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


# ---------- Years with few units ----------

def sparse_first_year():
    """The fixture without unit 1's 2023 record: 2023 then has 1 unit reporting, 2024 has 2 and 2025 has 4."""
    frame = selection()
    return frame[~((frame["year"] == 2023) & (frame["unit_key"] == 1))]


def test_coverage_finds_the_first_well_covered_year():
    assert dashboard.coverage(selection(), [2023, 2024, 2025]) is None      # 2 of 4 units: half is enough
    cover = dashboard.coverage(sparse_first_year(), [2023, 2024, 2025])
    assert cover["start"] == 2024 and cover["first_units"] == 1 and cover["busiest"] == 4


def test_trends_measure_change_from_the_first_well_covered_year():
    frame = sparse_first_year()
    indexed = dashboard.indexed_trend(frame)
    co2 = next(trace for trace in indexed["data"] if trace["name"] == "CO2")
    assert co2["x"] == [2024, 2025]
    assert co2["y"] == pytest.approx([100, 710_000 / 1_100_000 * 100])
    assert indexed["eyebrow"] == "Indexed to 2024 = 100"
    assert [row[0] for row in indexed["table"]["rows"]] == [2023, 2024, 2025]   # the table keeps every year
    trend = dashboard.trend(frame, "co2_mass")
    assert trend["data"][0]["x"] == [2023, 2024, 2025]                        # drawn, but shaded
    assert trend["layout"]["shapes"][-1]["x1"] == 2023.5
    assert trend["headline"]["delta"]["after"] == "since 2024"
    assert trend["readout"]["base"] == 2024
    assert "Before 2024 fewer than half as many units reported" in trend["note"]
    # With every year covered nothing changes
    assert dashboard.trend(selection(), "co2_mass")["readout"]["base"] is None


# ---------- Charts on the facility, unit, history, Compare facilities and Rankings pages ----------

def chart_ids(page):
    return set(re.findall(r'<script type="application/json" id="spec-([a-z_0-9]+)">', page))


def test_facility_and_unit_pages_have_charts(client):
    alpha = client.get("/facility/1001").get_data(as_text=True)
    assert {"trend", "indexed", "rank_high"} <= chart_ids(alpha)               # Alpha has 2 units
    assert "/dashboard?epa_facility_id=1001" in alpha
    assert "rank_high" not in chart_ids(client.get("/facility/1002").get_data(as_text=True))   # one unit
    # The charts' downloads are the dashboard's, for exactly this facility
    download = client.get("/dashboard/data?epa_facility_id=1001&level=unit&chart=rank_high")
    assert download.status_code == 200 and "Alpha Station" in download.get_data(as_text=True)
    assert {"trend", "indexed"} <= chart_ids(client.get("/unit/1").get_data(as_text=True))
    history = client.get("/history?unit=1&year_from=2023&year_to=2025").get_data(as_text=True)
    assert {"trend", "indexed"} <= chart_ids(history)


def test_compare_facilities_charts_keep_each_facility_color(client):
    page = client.get("/compare?facility=1001&facility=1002&year=2025").get_data(as_text=True)
    assert {"trend", "trend_intensity", "bars_co2_mass", "bars_co2_intensity"} <= chart_ids(page)
    frame = selection()
    frame = frame[frame["facility_id"].isin([1001, 1002])]
    charts = dashboard.facility_comparison(frame, ["Beta Plant", "Alpha Station"], 2025)
    lines = [trace for trace in charts[0]["data"] if trace.get("mode") == "lines"]
    assert [(trace["name"], trace["line"]["color"]) for trace in lines] == [
        ("Beta Plant", dashboard.BLACK), ("Alpha Station", dashboard.BLUE)]
    bars = charts[2]["data"][0]
    assert bars["x"] == [440_000, 240_000]                                   # 2025: Beta, then Alpha
    colors = dict(zip([label.split(" (")[0] for label in bars["y"]], bars["marker"]["color"]))
    assert colors == {"Beta Plant": dashboard.BLACK, "Alpha Station": dashboard.BLUE}


def test_rankings_have_a_bar_chart(client):
    page = client.get("/advanced-search?type=Facility&field=co2_mass&limit=3&order=DESC&reporting_year=2025")
    text = page.get_data(as_text=True)
    assert "ranking" in chart_ids(text)
    spec = json.loads(re.search(r'id="spec-ranking">(.*?)</script>', text, re.S).group(1))
    assert spec["data"][0]["x"] == [440_000, 240_000, 30_000]
    assert spec["data"][0]["marker"]["color"] == [dashboard.BLACK, dashboard.REST, dashboard.REST]
    grouped = client.get("/advanced-search?type=Facility&field=co2_mass&limit=1&group=state").get_data(as_text=True)
    assert "ranking" not in chart_ids(grouped)
