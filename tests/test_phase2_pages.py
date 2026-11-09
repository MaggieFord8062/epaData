"""
Tests for the Phase 2 dataset builder filters (4.1), dashboard (4.4) and comparisons (4.5),
using the fixture database in conftest.py. Expected values are worked out by hand:

CO2 totals by year: 2023 = 1,000,000 + 60,000 = 1,060,000
                    2024 = 900,000 + 200,000   = 1,100,000
                    2025 = 0 + 240,000 + 440,000 + 30,000 = 710,000
CO2 by facility:    Alpha 2,340,000 (gross load 2,900,000 MWh), Beta 440,000 (400,000), Gamma 90,000 (150,000)
"""

import json
import re

import pytest
from scipy import stats

import analysis
import comparison
import dashboard
import smart_search


def selection(params=None):
    rows = smart_search.explore(params or {}, everything=True)["rows"]
    return analysis.build_frame(rows)


# ---------- 4.1 Analytical dataset builder ----------

def test_program_filter_matches_whole_codes():
    assert smart_search.explore({"program": "CSSO2G2"}, everything=True)["total"] == 3   # unit 1 only
    assert smart_search.explore({"program": "csosg2"}, everything=True)["total"] == 1    # unit 3, any case
    assert smart_search.explore({"program": "ARP"}, everything=True)["total"] == 6


def test_control_filters_including_none():
    assert smart_search.explore({"so2_control": "Wet Limestone"}, everything=True)["total"] == 3
    assert smart_search.explore({"so2_control": "none"}, everything=True)["total"] == 5
    assert smart_search.explore({"nox_control": "Selective"}, everything=True)["total"] == 1


def test_year_range_and_minimum_load():
    assert smart_search.explore({"year_from": "2024", "year_to": "2025"}, everything=True)["total"] == 6
    assert smart_search.explore({"gross_load_min": "500000"}, everything=True)["total"] == 4


def test_control_and_program_refinements_have_counts():
    facets = smart_search.explore({})["facets"]
    so2 = {item["value"]: item["count"] for item in facets["so2_control"]["items"]}
    assert so2 == {"Wet Limestone": 3, "none": 5}
    programs = {item["value"]: item["count"] for item in facets["program"]["items"]}
    assert programs["CSNOX"] == 7
    assert programs["ARP"] == 6


def test_variable_availability_lists_every_group():
    available, missing = analysis.variable_availability(selection())
    assert list(available) == ["Facility", "Unit", "Annual", "Derived indicators"]
    county = next(item for item in missing if item["name"] == "County")
    assert county["missing"] == 8 and county["percent"] == 100
    heat_rate = next(item for item in missing if item["name"].startswith("Heat rate"))
    assert heat_rate["missing"] == 1   # the zero-load year


def test_hourly_summary_for_the_selection():
    kentucky = smart_search.hourly_summary({"state": "KY"})
    assert kentucky["records"] == 3 and kentucky["units"] == 1 and kentucky["unit_days"] == 1
    mercury = next(item for item in kentucky["missing"] if item["name"] == "Mercury mass")
    assert mercury["missing"] == 1
    assert smart_search.hourly_summary({"state": "OH"})["records"] == 0


def test_explore_page_summary_and_links(client):
    page = client.get("/explore?state=KY").get_data(as_text=True)
    assert "Variables available for analysis" in page
    assert "Heat rate (mmBtu/MWh)" in page
    assert "3 hourly records are stored for 1 of these units" in page
    for path in ("/statistics?state=KY", "/dashboard?state=KY", "/comparison?state=KY", "/impacts?state=KY"):
        assert path in page
    assert "None reported" in client.get("/explore").get_data(as_text=True)


# ---------- 4.4 Dashboard ----------

def test_indexed_trend():
    spec = dashboard.indexed_trend(selection())
    co2 = next(trace for trace in spec["data"] if trace["name"] == "CO2")
    assert co2["x"] == [2023, 2024, 2025]
    assert co2["y"] == pytest.approx([100, 1_100_000 / 1_060_000 * 100, 710_000 / 1_060_000 * 100])


def test_trend_uses_overall_ratio_for_intensity():
    spec = dashboard.trend(selection(), "co2_intensity")
    # 2025: (240,000 + 440,000 + 30,000) ÷ (600,000 + 400,000 + 50,000); the zero-load record adds nothing
    assert spec["data"][0]["y"][2] == pytest.approx(710_000 / 1_050_000)


def test_bars_by_state():
    spec = dashboard.bars(selection(), "co2_mass", "state")
    assert spec["data"][0]["y"] == ["KY", "OH"]
    assert spec["data"][0]["x"] == [2_780_000, 90_000]


def test_histogram_counts_every_value():
    spec = dashboard.histogram(selection(), "co2_mass", "log")
    assert sum(row[2] for row in spec["table"]["rows"]) == 7      # the 0 is left out on a log scale
    assert "1 records with a value of 0 are left out" in spec["note"]
    linear = dashboard.histogram(selection(), "co2_mass", "linear")
    assert sum(row[2] for row in linear["table"]["rows"]) == 8


def test_rankings():
    high, low = dashboard.rankings(selection(), "co2_mass", "facility")
    assert high["table"]["rows"][0][1].startswith("Alpha Station")
    assert high["table"]["rows"][0][2] == 2_340_000
    assert low["table"]["rows"][0][1].startswith("Gamma Energy")
    # Ratios only rank facilities with enough gross load
    high, _ = dashboard.rankings(selection(), "co2_intensity", "facility", min_load=200_000)
    names = [row[1] for row in high["table"]["rows"]]
    assert not any(name.startswith("Gamma") for name in names)


def test_correlation_matrix():
    spec = dashboard.correlation(selection(), "spearman")
    z = spec["data"][0]["z"]
    assert z[0][0] == pytest.approx(1.0)
    for i in range(len(z)):
        for j in range(len(z)):
            if z[i][j] is not None:
                assert z[i][j] == pytest.approx(z[j][i])


def test_state_and_facility_maps():
    frame = selection()
    states = dashboard.state_map(frame, "co2_mass")
    assert states["data"][0]["locations"] == ["KY", "OH"]
    facilities = dashboard.facility_map(frame, "co2_mass")
    assert len(facilities["data"][0]["lat"]) == 2     # Gamma has no stored location
    assert "1 facilities have no stored location" in facilities["note"]


def test_every_chart_is_valid_json():
    choices = {"variable": "co2_intensity", "group": "primary_fuel", "split": "fuel_family", "x": "heat_input",
               "y": "co2_mass", "scale": "log", "corr": "pearson", "level": "unit", "min_load": 0}
    for spec in dashboard.build_all(selection(), choices):
        json.dumps(dashboard.json_safe(spec), allow_nan=False)


def test_dashboard_page(client):
    page = client.get("/dashboard?state=KY&variable=co2_intensity").get_data(as_text=True)
    blocks = re.findall(r'<script type="application/json" id="spec-([a-z_]+)">(.*?)</script>', page, re.S)
    ids = {chart_id for chart_id, _ in blocks}
    assert {"indexed", "trend", "bars", "histogram", "box", "scatter", "correlation", "rank_high", "rank_low",
            "state_map", "facility_map"} <= ids
    for _, body in blocks:
        json.loads(body)
    assert "plotly" in page.lower()


def test_dashboard_chart_download(client):
    text = client.get("/dashboard/data?chart=bars&variable=co2_mass&group=state").get_data(as_text=True)
    assert "# Chart,CO2 mass by state" in text
    assert "KY,2780000.0,6" in text
    assert client.get("/dashboard/data?chart=nonsense").status_code == 404


# ---------- 4.5 Comparisons ----------

def test_period_comparison():
    frame = selection()
    definition = comparison.choose(frame, {"cmp": "period"})
    assert (definition["a_label"], definition["b_label"]) == ("2023", "2025")
    result = comparison.compare(frame, "co2_intensity", definition)
    overall = next(row for row in result["rows"] if row["key"] == "overall")
    assert overall["a"] == pytest.approx(1_060_000 / 1_100_000)
    assert overall["b"] == pytest.approx(710_000 / 1_050_000)
    assert overall["percent"] == pytest.approx((710 / 1050 - 1060 / 1100) / (1060 / 1100) * 100)


def test_matched_units_only():
    frame = selection()
    definition = comparison.choose(frame, {"cmp": "period", "matched": "1"})
    # Units 1 and 4 report in both 2023 and 2025
    assert set(frame.loc[definition["mask_b"], "unit_key"]) == {1, 4}
    result = comparison.compare(frame, "co2_intensity", definition)
    overall = next(row for row in result["rows"] if row["key"] == "overall")
    assert overall["b"] == pytest.approx(30_000 / 50_000)


def test_welch_and_mann_whitney_match_scipy():
    frame = selection()
    definition = comparison.choose(frame, {"cmp": "state", "a": "KY", "b": "OH"})
    result = comparison.compare(frame, "co2_mass", definition)
    kentucky = frame.loc[frame["state"] == "KY", "co2_mass"].to_numpy()
    ohio = frame.loc[frame["state"] == "OH", "co2_mass"].to_numpy()
    expected = stats.ttest_ind(ohio, kentucky, equal_var=False)
    welch = result["tests"]["welch"]
    assert welch["t"] == pytest.approx(expected.statistic)
    assert welch["p"] == pytest.approx(expected.pvalue)
    assert welch["difference"] == pytest.approx(ohio.mean() - kentucky.mean())
    assert welch["low"] < welch["difference"] < welch["high"]
    u = stats.mannwhitneyu(ohio, kentucky, alternative="two-sided")
    assert result["tests"]["mann_whitney"]["superiority"] == pytest.approx(u.statistic / (len(ohio) * len(kentucky)))


def test_control_comparison_and_ranking():
    frame = selection()
    definition = comparison.choose(frame, {"cmp": "so2_control"})
    assert int(definition["mask_b"].sum()) == 3 and int(definition["mask_a"].sum()) == 5
    ranking = comparison.all_groups(frame, "co2_mass", "state")
    assert ranking["rows"][0]["group"] == "KY"
    assert ranking["rows"][0]["share"] == pytest.approx(2_780_000 / 2_870_000 * 100)


def test_comparison_pages(client):
    page = client.get("/comparison?cmp=state&a=KY&b=OH&variable=co2_mass").get_data(as_text=True)
    assert "What the tests say" in page
    assert "Every normalized indicator" in page
    same = client.get("/comparison?cmp=state&a=KY&b=KY").get_data(as_text=True)
    assert "Choose two different groups" in same
    text = client.get("/comparison/download?cmp=state&a=KY&b=OH&variable=co2_mass").get_data(as_text=True)
    assert "States: A = KY, B = OH" in text
    assert "Welch's t-test: p-value" in text
    for what in ("indicators", "groups"):
        assert client.get(f"/comparison/download?cmp=period&what={what}&format=xlsx").status_code == 200
