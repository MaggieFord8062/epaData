"""
Tests for the unusual-observation list on the Statistics page (proposal goal 5): records outside
Tukey's fences, Q1 − 1.5 × IQR and Q3 + 1.5 × IQR, checked by hand.
"""

import pytest

import analysis

ROWS = [{"Facility": f"Plant {n}", "Facility ID": 9000 + n, "State": "KY", "Unit": "1", "Year": 2024,
         "Primary Fuel": "Coal", "CO2 (tons)": value, "_unit_key": n}
        for n, value in enumerate([1.0, 2.0, 3.0, 4.0, 100.0], start=1)]


def test_unusual_observations_by_hand():
    frame = analysis.build_frame(ROWS, with_changes=False)
    found = analysis.unusual(frame, "co2_mass")
    # Q1 = 2, Q3 = 4, IQR = 2, so the fences are −1 and 7
    assert (found["low"], found["high"]) == (-1.0, 7.0)
    assert found["above"] == 1 and found["below"] == 0
    assert found["highest"][0]["value"] == 100.0
    assert found["highest"][0]["label"] == "Plant 5 (KY) unit 1"
    assert found["highest"][0]["distance"] == pytest.approx((100 - 7) / 2)
    assert found["share"] == pytest.approx(20.0)
    assert analysis.unusual(frame.head(3), "co2_mass") is None


def test_statistics_page_lists_unusual_values(client):
    page = client.get("/statistics?variable=co2_mass").get_data(as_text=True)
    assert "Unusual observations" in page
    response = client.get("/statistics/download?variable=co2_mass&what=unusual")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "# Rule" in text and "# Fences" in text
