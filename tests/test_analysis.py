"""
Tests for analysis.py: derived indicators and descriptive statistics, checked against
values worked out by hand from the fixture records in conftest.py.

CO2 intensity (short tons/MWh) for the 8 fixture records:
    unit 1: 2023 1.0, 2024 1.125, 2025 undefined (gross load 0)
    unit 2: 2024 0.4, 2025 0.4
    unit 3: 2025 1.1
    unit 4: 2023 0.6, 2025 0.6
Sorted, the 7 defined values are 0.4, 0.4, 0.6, 0.6, 1.0, 1.1, 1.125.
"""

import numpy as np
import pandas as pd
import pytest

import analysis
import smart_search


@pytest.fixture()
def frame():
    """Every fixture record, with derived indicators and year-over-year change."""
    rows = smart_search.explore({}, everything=True)["rows"]
    return analysis.build_frame(rows)


def record(frame, unit_key, year):
    rows = frame[(frame["unit_key"] == unit_key) & (frame["year"] == year)]
    assert len(rows) == 1
    return rows.iloc[0]


# ---------- Derived indicators (proposal 4.3) ----------

def test_intensity_is_mass_divided_by_gross_load(frame):
    row = record(frame, 1, 2023)
    assert row["co2_intensity"] == pytest.approx(1.0)
    assert row["so2_intensity"] == pytest.approx(1000 * 2000 / 1_000_000)   # 2.0 lb/MWh
    assert row["nox_intensity"] == pytest.approx(2000 * 2000 / 1_000_000)   # 4.0 lb/MWh
    assert row["heat_rate"] == pytest.approx(10.0)


def test_zero_gross_load_leaves_ratio_missing_not_zero(frame):
    row = record(frame, 1, 2025)
    for key in ["co2_intensity", "so2_intensity", "nox_intensity", "heat_rate"]:
        assert pd.isna(row[key]), key


def test_missing_input_leaves_ratio_missing(frame):
    row = record(frame, 4, 2023)   # SO2 not reported
    assert pd.isna(row["so2_intensity"])
    assert row["co2_intensity"] == pytest.approx(0.6)


def test_operating_utilization_uses_leap_years(frame):
    assert record(frame, 1, 2024)["operating_utilization"] == pytest.approx(7000 / 8784 * 100)
    assert record(frame, 1, 2023)["operating_utilization"] == pytest.approx(8000 / 8760 * 100)


def test_year_over_year_change(frame):
    row = record(frame, 1, 2024)
    assert row["co2_mass_change"] == pytest.approx(-100_000)
    assert row["co2_mass_change_pct"] == pytest.approx(-10.0)
    assert record(frame, 2, 2025)["co2_mass_change_pct"] == pytest.approx(20.0)


def test_year_over_year_needs_the_previous_year(frame):
    # Unit 4 has 2023 and 2025 but no 2024, so 2025 has nothing to compare with
    row = record(frame, 4, 2025)
    assert pd.isna(row["co2_mass_change"])
    assert pd.isna(row["co2_mass_change_pct"])
    # The first year on record has nothing to compare with either
    assert pd.isna(record(frame, 2, 2024)["co2_mass_change"])


def test_percent_change_from_zero_is_missing(frame):
    # A unit going from 0 to something would divide by 0; here unit 1 goes 900,000 -> 0, which is fine
    assert record(frame, 1, 2025)["co2_mass_change_pct"] == pytest.approx(-100.0)


def test_year_over_year_reads_previous_year_outside_the_selection():
    # A 2025-only selection still gets 2024 values from the database
    rows = smart_search.explore({"reporting_year": "2025"}, everything=True)["rows"]
    frame = analysis.build_frame(rows)
    assert len(frame) == 4
    assert record(frame, 2, 2025)["co2_mass_change"] == pytest.approx(40_000)


def test_safe_ratio_rules():
    numerator = pd.Series([10.0, 10.0, np.nan, 10.0, 0.0])
    denominator = pd.Series([2.0, 0.0, 2.0, -5.0, 4.0])
    result = analysis.safe_ratio(numerator, denominator)
    assert result[0] == 5.0
    assert pd.isna(result[1])     # divide by zero
    assert pd.isna(result[2])     # missing numerator
    assert pd.isna(result[3])     # negative denominator
    assert result[4] == 0.0       # a real zero stays zero


# ---------- Descriptive statistics (proposal 4.2) ----------

def test_describe_matches_hand_calculation(frame):
    stats = analysis.describe(frame, "co2_intensity", [10, 90])
    values = [0.4, 0.4, 0.6, 0.6, 1.0, 1.1, 1.125]

    assert stats["records"] == 8
    assert stats["count"] == 7
    assert stats["missing"] == 1
    assert stats["zero_denominator"] == 1
    assert stats["min"] == pytest.approx(0.4)
    assert stats["max"] == pytest.approx(1.125)
    assert stats["mean"] == pytest.approx(sum(values) / 7)
    assert stats["median"] == pytest.approx(0.6)
    assert stats["q1"] == pytest.approx(0.5)      # position 1.5 between 0.4 and 0.6
    assert stats["q3"] == pytest.approx(1.05)     # position 4.5 between 1.0 and 1.1
    assert stats["iqr"] == pytest.approx(0.55)
    assert stats["std"] == pytest.approx(np.std(values, ddof=1))
    assert stats["percentiles"][0][1] == pytest.approx(np.percentile(values, 10))
    assert stats["percentiles"][1][1] == pytest.approx(np.percentile(values, 90))
    # Overall ratio: total CO2 ÷ total gross load over the 7 defined records
    assert stats["overall"] == pytest.approx(2_870_000 / 3_450_000)
    assert stats["total"] is None   # adding intensities means nothing


def test_describe_total_for_additive_variable(frame):
    stats = analysis.describe(frame, "co2_mass")
    assert stats["total"] == pytest.approx(2_870_000)
    assert stats["overall"] is None


def test_describe_empty_selection():
    frame = analysis.build_frame([])
    stats = analysis.describe(frame, "co2_intensity")
    assert stats["records"] == 0
    assert stats["count"] == 0
    assert stats["mean"] is None
    assert stats["overall"] is None


def test_single_value_has_no_standard_deviation():
    rows = smart_search.explore({"state": "KY", "reporting_year": "2023"}, everything=True)["rows"]
    stats = analysis.describe(analysis.build_frame(rows), "co2_mass")
    assert stats["count"] == 1
    assert stats["std"] is None


def test_grouped_totals_by_state(frame):
    groups = {row["group"]: row for row in analysis.describe_groups(frame, "co2_mass", "state")}
    assert groups["KY"]["total"] == pytest.approx(2_780_000)
    assert groups["OH"]["total"] == pytest.approx(90_000)
    assert groups["KY"]["records"] == 6


def test_grouped_overall_ratio_by_fuel(frame):
    groups = {row["group"]: row for row in analysis.describe_groups(frame, "co2_intensity", "primary_fuel")}
    # Coal: (1,000,000 + 900,000 + 440,000) ÷ (1,000,000 + 800,000 + 400,000); the zero-load year is left out
    assert groups["Coal"]["overall"] == pytest.approx(2_340_000 / 2_200_000)
    assert groups["Coal"]["missing"] == 1


def test_missing_group_values_are_kept_as_not_reported(frame):
    groups = {row["group"]: row for row in analysis.describe_groups(frame, "co2_mass", "unit_type")}
    assert groups[analysis.NOT_REPORTED]["records"] == 2


def test_group_by_control(frame):
    groups = {row["group"]: row for row in analysis.describe_groups(frame, "so2_mass", "so2_control")}
    assert groups["With SO2 control"]["records"] == 3
    assert groups["No SO2 control reported"]["records"] == 5


def test_group_sorting(frame):
    by_total = analysis.describe_groups(frame, "co2_mass", "state", "total")
    assert [row["group"] for row in by_total] == ["KY", "OH"]
    by_year = analysis.describe_groups(frame, "co2_mass", "year")   # years default to oldest first
    assert [row["group"] for row in by_year] == ["2023", "2024", "2025"]


# ---------- Percentiles, fingerprint, formatting ----------

def test_parse_percentiles():
    assert analysis.parse_percentiles("") == [5, 10, 90, 95]
    assert analysis.parse_percentiles("95, 5, abc, 150, 5") == [5.0, 95.0]
    assert analysis.parse_percentiles("2.5 97.5%") == [2.5, 97.5]


def test_fingerprint_identifies_the_selection(frame):
    same = analysis.build_frame(smart_search.explore({}, everything=True)["rows"])
    other = analysis.build_frame(smart_search.explore({"state": "OH"}, everything=True)["rows"])
    assert analysis.selection_fingerprint(frame) == analysis.selection_fingerprint(same)
    assert analysis.selection_fingerprint(frame) != analysis.selection_fingerprint(other)


def test_format_number():
    assert analysis.format_number(None) == "—"
    assert analysis.format_number(float("nan")) == "—"
    assert analysis.format_number(2_870_000) == "2,870,000"
    assert analysis.format_number(123.456) == "123.5"
    assert analysis.format_number(1.5) == "1.50"
    assert analysis.format_number(0.0045213) == "0.004521"
    assert analysis.format_number(0.6) == "0.6"
    assert analysis.format_number(0) == "0"
