"""
Tests for traci.py (proposal 4.6): reading the TRACI workbook with exact matching only, the
bundled extract, and the impact calculation checked by hand against the fixture records.

Fixture emissions (short tons), from conftest.py:
    CO2 total 2,870,000 over 8 records
    SO2 is missing for unit 4 in 2023, so categories that use SO2 use 7 records:
        SO2 = 1000 + 800 + 0 + 1 + 1.2 + 400 + 0.5 = 2,202.7
        NOx = 2000 + 1600 + 0 + 50 + 60 + 600 + 5   = 4,315
    NOx over all 8 records = 4,325
"""

import pytest
from openpyxl import Workbook

import analysis
import smart_search
import traci

KG = traci.SHORT_TON_KG

HEADER = ["CAS #", "Formatted CAS #", "Substance Name", "Acidification Air (kg SO2 eq / kg substance)",
          "Global Climate Air (kg CO2 eq / kg substance)", "HH Particulate Air (PM2.5 eq / kg substance)",
          "Ozone Depletion Air (kg CFC-11 eq / kg substance)", "Smog Air (kg O3 eq / kg substance)"]

ROWS = [
    [124389, 124389, "CARBON DIOXIDE", "n/a", 1, "n/a", "n/a", "n/a"],
    [7446095, 7446095, "SULFUR DIOXIDE", 1, "n/a", 0.0611, "n/a", "n/a"],
    [10102440, 10102440, "NITROGEN DIOXIDE", 0.7, "n/a", 0.0072, "n/a", 16.8],   # decoy
    [10102439, 10102439, "NITRIC OXIDE", 1.07, "n/a", "n/a", "n/a", 24.8],       # decoy
    ["x", "x", "NITROGEN OXIDES", 0.7, "n/a", 0.0072, "n/a", 24.8],
]


def write_workbook(path, rows):
    workbook = Workbook()
    title = workbook.active
    title.title = "TRACI_2_2"
    title.append(["TRACI 2.2"])
    title.append(["Tool for the Reduction and Assessment of Chemical and other environmental Impacts 2.2 "
                  "(Updated 3/2/2022)"])
    sheet = workbook.create_sheet("Substances")
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_read_workbook_matches_exactly(tmp_path):
    path = tmp_path / "traci.xlsx"
    write_workbook(path, ROWS)
    factors = traci.read_workbook(str(path))
    found = {(f["campd_pollutant"], f["impact_category"]): f for f in factors}

    assert found[("co2_mass", "global_warming")]["factor_value"] == 1
    assert found[("so2_mass", "acidification")]["cas_number"] == "7446-09-5"
    # NOx comes from the NITROGEN OXIDES row (smog 24.8), never NITROGEN DIOXIDE (16.8)
    assert found[("nox_mass", "smog_formation")]["factor_value"] == 24.8
    assert found[("nox_mass", "smog_formation")]["substance_name"] == "NITROGEN OXIDES"
    assert found[("nox_mass", "smog_formation")]["source_row"] == 6
    assert factors[0]["traci_version"] == "TRACI 2.2 (updated 3/2/2022)"
    # "n/a" cells are not factors
    assert ("co2_mass", "acidification") not in found
    assert len(factors) == 6


def test_no_fallback_to_similar_names(tmp_path):
    # Without a NITROGEN OXIDES row the import must stop, not use NITROGEN DIOXIDE
    path = tmp_path / "traci.xlsx"
    write_workbook(path, [row for row in ROWS if row[2] != "NITROGEN OXIDES"])
    with pytest.raises(ValueError, match="NITROGEN OXIDES"):
        traci.read_workbook(str(path))


def test_cas_number_must_have_the_expected_name(tmp_path):
    rows = [list(row) for row in ROWS]
    rows[0][2] = "SOMETHING ELSE"
    path = tmp_path / "traci.xlsx"
    write_workbook(path, rows)
    with pytest.raises(ValueError, match="CARBON DIOXIDE"):
        traci.read_workbook(str(path))


def test_bundled_extract_has_the_official_factors():
    factors = {(f["campd_pollutant"], f["impact_category"]): f for f in traci.read_extract()}
    assert factors[("co2_mass", "global_warming")]["factor_value"] == 1.0
    assert factors[("so2_mass", "acidification")]["factor_value"] == 1.0
    assert factors[("so2_mass", "particulate_matter")]["factor_value"] == pytest.approx(0.0611111)
    assert factors[("nox_mass", "acidification")]["factor_value"] == 0.7
    assert factors[("nox_mass", "particulate_matter")]["factor_value"] == pytest.approx(0.00722222)
    assert factors[("nox_mass", "smog_formation")]["factor_value"] == pytest.approx(24.7935897)
    assert factors[("nox_mass", "smog_formation")]["substance_name"] == "NITROGEN OXIDES"
    assert all(f["traci_version"] == "TRACI 2.2 (updated 3/2/2022)" for f in factors.values())
    assert len(factors) == 6


@pytest.fixture()
def impacts():
    factors = traci.ensure_factors()
    frame = analysis.build_frame(smart_search.explore({}, everything=True)["rows"])
    traci.add_impacts(frame, factors)
    return factors, frame


def test_factors_are_stored_with_provenance(impacts):
    factors, _ = impacts
    assert len(factors) == 6
    assert all(f["dataset_id"] for f in factors)
    assert {f["traci_version"] for f in factors} == {"TRACI 2.2 (updated 3/2/2022)"}


def test_impact_totals_match_hand_calculation(impacts):
    factors, frame = impacts
    totals = {item["key"]: item for item in traci.summarize(frame, factors)}

    assert totals["global_warming"]["total"] == pytest.approx(2_870_000 * KG * 1)
    assert totals["global_warming"]["used"] == 8
    assert totals["acidification"]["total"] == pytest.approx((2202.7 * 1 + 4315 * 0.7) * KG)
    assert totals["acidification"]["missing"] == 1          # unit 4 in 2023 has no SO2
    assert totals["smog_formation"]["total"] == pytest.approx(4325 * KG * 24.7935897, rel=1e-6)
    # Per MWh uses the gross load of the same records (the zero-load year adds nothing)
    assert totals["global_warming"]["intensity"] == pytest.approx(2_870_000 * KG / 3_450_000)
    assert totals["acidification"]["intensity"] == pytest.approx((2202.7 + 4315 * 0.7) * KG / 3_350_000)


def test_contributions_add_up(impacts):
    factors, frame = impacts
    for item in traci.summarize(frame, factors):
        assert sum(c["amount"] for c in item["contributions"]) == pytest.approx(item["total"])
        assert sum(c["share"] for c in item["contributions"]) == pytest.approx(100)


def test_missing_pollutant_leaves_the_category_missing(impacts):
    _, frame = impacts
    row = frame[(frame["unit_key"] == 4) & (frame["year"] == 2023)].iloc[0]
    assert row["impact_acidification"] != row["impact_acidification"]   # NaN, not 0
    assert row["impact_smog_formation"] == pytest.approx(10 * KG * 24.7935897, rel=1e-6)


def test_impacts_by_state(impacts):
    factors, frame = impacts
    groups = traci.summarize_groups(frame, factors, frame["state"])
    warming = {row["group"]: row for row in groups["global_warming"]}
    assert warming["KY"]["total"] == pytest.approx(2_780_000 * KG)
    assert warming["OH"]["total"] == pytest.approx(90_000 * KG)


def test_impacts_page_and_downloads(client):
    page = client.get("/impacts?by=primary_fuel").get_data(as_text=True)
    assert "TRACI 2.2" in page
    assert "NITROGEN OXIDES" in page
    assert "do not measure actual illness" in page

    text = client.get("/impacts/download?what=totals").get_data(as_text=True)
    assert "# TRACI version,TRACI 2.2 (updated 3/2/2022)" in text
    assert "# Unit conversion,1 short ton = 907.18474 kg" in text
    assert "Global warming,kg CO2 eq,2603620203.8" in text

    factors = client.get("/impacts/download?what=factors").get_data(as_text=True)
    assert "Exact substance name NITROGEN OXIDES" in factors
    assert client.get("/impacts/download?what=records&format=xlsx").status_code == 200
