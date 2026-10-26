"""
Tests for the Statistics page and its downloads, using the Flask test client and the
fixture database from conftest.py.
"""

import io

import pandas as pd
from openpyxl import load_workbook


def test_statistics_page_opens_with_default_variable(client):
    response = client.get("/statistics")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "CO2 intensity" in page
    assert "Every record in the database" in page
    assert "0.6" in page                 # median
    assert "undefined" in page           # explains the zero-gross-load record


def test_statistics_uses_explore_filters(client):
    page = client.get("/statistics?state=OH&variable=co2_mass").get_data(as_text=True)
    assert "State: Ohio (OH)" in page
    assert "90,000" in page              # total CO2 for the Ohio unit


def test_text_search_selection(client):
    page = client.get("/statistics?q=alpha&variable=co2_mass").get_data(as_text=True)
    # Alpha Station = units 1 and 2: 1,000,000 + 900,000 + 0 + 200,000 + 240,000 = 2,340,000
    assert "2,340,000" in page


def test_unknown_choices_fall_back_to_defaults(client):
    response = client.get("/statistics?variable=nonsense&group=nonsense&gsort=nonsense")
    assert response.status_code == 200
    assert "CO2 intensity" in response.get_data(as_text=True)


def test_empty_selection(client):
    response = client.get("/statistics?state=ZZ")
    assert response.status_code == 200
    assert "No records in this selection" in response.get_data(as_text=True)


def test_grouped_table(client):
    page = client.get("/statistics?variable=co2_mass&group=state").get_data(as_text=True)
    assert "By state" in page
    assert "2,780,000" in page


def test_summary_csv_has_metadata_and_statistics(client):
    response = client.get("/statistics/download?variable=co2_intensity&what=summary")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    text = response.get_data(as_text=True)
    assert text.startswith("# Export,Descriptive statistics")
    for item in ["# Analysis date", "# Selection fingerprint", "# Definition", "# Percentile method",
                 "# Software version", "# Dataset identifier"]:
        assert item in text

    table = pd.read_csv(io.StringIO(text), comment="#")
    values = dict(zip(table["Statistic"], table["Value"]))
    assert float(values["Median (short tons/MWh)"]) == 0.6
    assert int(values["Missing values"]) == 1


def test_grouped_excel_has_results_and_metadata_sheets(client):
    response = client.get("/statistics/download?variable=co2_mass&group=state&what=groups&format=xlsx")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.data))
    assert workbook.sheetnames == ["Results", "Metadata"]
    results = list(workbook["Results"].values)
    assert results[0][0] == "State"
    assert {row[0] for row in results[1:]} == {"KY", "OH"}
    metadata = dict(list(workbook["Metadata"].values)[1:])
    assert metadata["Grouped by"] == "State"


def test_analytical_dataset_export(client):
    response = client.get("/statistics/download?what=dataset")
    text = response.get_data(as_text=True)
    assert "# Definition: CO2 intensity (short tons/MWh)" in text
    table = pd.read_csv(io.StringIO(text), comment="#")
    assert len(table) == 8
    units = table["Unit"].astype(str)
    zero_load = table[(table["Facility"] == "Alpha Station") & (units == "1") & (table["Year"] == 2025)]
    assert len(zero_load) == 1
    assert zero_load["CO2 intensity (short tons/MWh)"].isna().all()   # left blank, not 0


def test_explore_links_to_statistics(client):
    page = client.get("/explore?state=KY").get_data(as_text=True)
    assert "/statistics?state=KY" in page
