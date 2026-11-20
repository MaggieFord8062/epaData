"""
Tests for the prediction module (proposal 5) and sensitivity and scenario analysis (proposal 6).

The fixture database has only 3 years and 8 records, too few to train on, so most model tests
use a synthetic selection built here, where the answer is known exactly:

    40 units (half coal, half gas), 2018–2023
    heat input  = 100,000 × (1 + unit mod 10) × (1 + 0.03 × (year − 2018)) mmBtu
    gross load  = heat input ÷ 10 (coal) or ÷ 7 (gas)
    CO2         = 0.1 × heat input            (so linear regression can fit it exactly)

The chronological split for 2018–2023 is: train 2018–2020, validate 2021–2022, test 2023.
"""

import io
import json
import os
import re

import numpy as np
import pandas as pd
import pytest

import analysis
import prediction
import scenarios
import smart_search

YEARS = list(range(2018, 2024))


def synthetic_rows():
    rows = []
    for unit in range(1, 41):
        coal = unit % 2 == 1
        for year in YEARS:
            heat = 100_000 * (1 + unit % 10) * (1 + 0.03 * (year - 2018))
            rows.append({
                "Facility": f"Plant {unit}", "Facility ID": 5000 + unit, "State": "KY" if unit < 20 else "OH",
                "County": None, "Unit": "1",
                "Unit Type": ("Tangentially-fired" if unit % 4 == 1 else "Dry bottom wall-fired boiler") if coal
                else ("Combined cycle" if unit % 4 == 0 else "Combustion turbine"),
                "Primary Fuel": "Coal" if coal else "Pipeline Natural Gas", "Secondary Fuel": None,
                "Year": year, "Operating Time (hrs)": 4000 + 100 * (unit % 20),
                "Gross Load (MWh)": heat / (10 if coal else 7), "Steam Load (1000 lb)": None,
                "Heat Input (mmBtu)": heat, "CO2 (tons)": 0.1 * heat,
                "SO2 (tons)": (0.002 if coal else 0.00001) * heat * (0.1 if unit % 3 == 0 else 1),
                "NOx (tons)": 0.0003 * heat, "SO2 Controls": "Wet Limestone" if coal and unit % 3 == 0 else None,
                "NOx Controls": "Selective Catalytic Reduction" if unit % 5 == 0 else None, "PM Controls": None,
                "Programs": "ARP", "_unit_key": unit,
            })
    return rows


@pytest.fixture()
def frame():
    return analysis.build_frame(synthetic_rows(), with_changes=False)


@pytest.fixture()
def fitted(frame):
    return prediction.train(frame, "co2_mass")


# ---------- Splitting and scoring ----------

def test_chronological_split():
    split = prediction.split_years(range(1995, 2026))
    assert split["train"] == list(range(1995, 2023))
    assert split["validation"] == [2023, 2024]
    assert split["test"] == [2025]
    assert prediction.split_years([2021, 2022, 2023, 2024, 2025]) == {
        "train": [2021, 2022, 2023], "validation": [2024], "test": [2025]}
    assert prediction.split_years([2024, 2025]) is None


def test_scores_by_hand():
    # actual 1, 2, 3, 4; predicted 2 every time: errors +1, 0, −1, −2
    result = prediction.scores([1, 2, 3, 4], [2, 2, 2, 2])
    assert result["mae"] == pytest.approx(1.0)
    assert result["rmse"] == pytest.approx(np.sqrt(6 / 4))
    assert result["r2"] == pytest.approx(1 - 6 / 5)          # SS_res 6, SS_tot 5
    assert result["wape"] == pytest.approx(4 / 10 * 100)
    assert result["mape"] == pytest.approx((1 + 0 + 1 / 3 + 2 / 4) / 4 * 100)
    assert result["bias"] == pytest.approx(-0.5)


def test_no_input_reveals_the_target():
    for name in prediction.FEATURES:
        assert "co2" not in name and "so2_mass" not in name and "nox_mass" not in name
        assert "intensity" not in name and "change" not in name


def test_missing_and_negative_records_are_left_out(frame):
    frame.loc[frame.index[0], "co2_mass"] = np.nan
    frame.loc[frame.index[1], "heat_input"] = -5
    rows, left_out = prediction.model_frame(frame, "co2_mass")
    assert left_out == 2
    assert len(rows) == len(frame) - 2


# ---------- Unit models ----------

def test_models_are_trained_and_tested_in_time_order(fitted):
    assert fitted["split"] == {"train": [2018, 2019, 2020], "validation": [2021, 2022], "test": [2023]}
    assert fitted["counts"] == {"train": 120, "validation": 80, "test": 40}
    assert set(fitted["tested"]["year"]) == {2023}
    # Linear regression recovers CO2 = 0.1 × heat input exactly
    assert fitted["test"]["linear"]["r2"] == pytest.approx(1.0, abs=1e-9)
    heat = next(item for item in fitted["linear_effects"] if item["input"] == "Heat input")
    assert heat["effect"] == pytest.approx(0.1, rel=1e-6)
    # Both candidates beat the mean baseline, and the chosen one had the lowest validation error
    for kind in prediction.CANDIDATES:
        assert fitted["validation"][kind]["mae"] < fitted["validation"]["mean"]["mae"]
    chosen = fitted["chosen"]
    assert all(fitted["validation"][chosen]["mae"] <= fitted["validation"][kind]["mae"]
               for kind in prediction.CANDIDATES)
    assert fitted["tree_depth"] in prediction.TREE_DEPTHS
    assert sum(item["share"] for item in fitted["tree_importance"]) == pytest.approx(100)


def test_test_year_never_influences_training_or_the_choice(frame, fitted):
    # Make every test-year target absurd: training, validation, depth and choice must not change
    changed = frame.copy()
    changed.loc[changed["year"] == 2023, "co2_mass"] *= 1000
    again = prediction.train(changed, "co2_mass")
    assert again["validation"] == fitted["validation"]
    assert again["tree_depth"] == fitted["tree_depth"]
    assert again["chosen"] == fitted["chosen"]
    assert again["test"]["linear"]["mae"] > fitted["test"]["linear"]["mae"]


def test_too_few_years_or_records_give_a_message():
    fixture = analysis.build_frame(smart_search.explore({}, everything=True)["rows"], with_changes=False)
    result = prediction.train(fixture, "co2_mass")
    assert "Not enough records" in result["error"]
    one_year = fixture[fixture["year"] == 2025]
    assert "at least three reporting years" in prediction.train(one_year, "co2_mass")["error"]


def test_models_are_saved_and_reopened(frame):
    first = prediction.fitted_models(frame, "co2_mass", ["test selection"])
    assert os.path.exists(first["file_path"])
    saved = prediction.saved_models(first["run_key"])
    assert [row["kind"] for row in saved] == ["mean", "linear", "tree"]
    assert sum(row["chosen"] for row in saved) == 1
    second = prediction.fitted_models(frame, "co2_mass", ["test selection"])
    assert second["run_key"] == first["run_key"]
    assert second["trained_at"] == first["trained_at"]          # reopened, not retrained
    # A changed file is not trusted: the models are trained again
    with open(first["file_path"], "ab") as handle:
        handle.write(b"tampered")
    assert prediction.load_run(first["run_key"]) is None
    third = prediction.fitted_models(frame, "co2_mass", ["test selection"])
    assert third["chosen"] == first["chosen"]
    assert prediction.load_run(first["run_key"]) is not None


# ---------- Year-trend forecast ----------

def test_trend_of_a_straight_line():
    totals = [{"year": year, "total": 1000.0 - 10 * (year - 2015), "units": 5, "records": 5}
              for year in range(2015, 2026)]
    result = prediction.train_prediction_models(totals)
    assert result["test"]["linear"]["mae"] == pytest.approx(0, abs=1e-6)
    forecast = prediction.generate_forecast(totals)["rows"]
    assert [row["year"] for row in forecast] == [2026, 2027, 2028, 2029, 2030]
    assert forecast[0]["linear"] == pytest.approx(890)
    assert forecast[-1]["linear"] == pytest.approx(850)
    # A tree can't extend a trend: its forecast is flat
    assert len({round(row["tree"], 6) for row in forecast}) == 1


def test_coverage_warning():
    totals = [{"year": 2020 + i, "total": 1.0, "units": units, "records": units}
              for i, units in enumerate([100, 100, 200])]
    assert "between 100 and 200 units" in prediction.coverage_note(totals)
    assert prediction.coverage_note(totals[:2]) is None


# ---------- Sensitivity and scenarios ----------

@pytest.fixture()
def linear_case(fitted):
    pipeline = fitted["pipelines"]["linear"]
    baseline = scenarios.baseline_record(fitted, 7)
    return fitted, pipeline, baseline


def test_one_variable_at_a_time_holds_the_rest_constant(linear_case):
    fitted, pipeline, baseline = linear_case
    settings, points, problems = scenarios.read_sweep({}, baseline["inputs"]["heat_input"], fitted["ranges"],
                                                      "heat_input")
    assert problems == []
    assert [round(pct) for _, pct in points] == list(range(-50, 51, 10))
    base, rows = scenarios.one_at_a_time(pipeline, fitted["ranges"], baseline, "heat_input", points)
    heat = baseline["inputs"]["heat_input"]
    assert base == pytest.approx(0.1 * heat, rel=1e-6)
    for row in rows:
        # CO2 is proportional to heat input, so the % change in the prediction equals the % change in the input
        assert row["change_pct"] == pytest.approx(row["input_change_pct"], abs=1e-6)
        assert row["change"] == pytest.approx(0.1 * (row["value"] - heat), rel=1e-6, abs=1e-3)
    assert sum(row["is_baseline"] for row in rows) == 1


def test_scenarios_compare_with_the_baseline(linear_case):
    fitted, pipeline, baseline = linear_case
    base, rows = scenarios.run_scenarios(pipeline, fitted["ranges"], baseline, "co2_mass",
                                         scenarios.read_custom({"c_heat": "-20"}))
    by_key = {row["key"]: row for row in rows}
    assert by_key["baseline"]["change"] == pytest.approx(0, abs=1e-6)
    assert by_key["heat_down"]["change_pct"] == pytest.approx(-5.0, abs=1e-6)
    assert by_key["runs_more"]["change_pct"] == pytest.approx(10.0, abs=1e-6)
    assert by_key["load_up"]["change_pct"] == pytest.approx(0.0, abs=1e-6)   # CO2 doesn't depend on load here
    assert by_key["custom"]["change_pct"] == pytest.approx(-20.0, abs=1e-6)
    assert by_key["efficient"]["change_pct"] == pytest.approx(-5.0, abs=1e-6)


def test_out_of_range_values_are_flagged(linear_case):
    fitted, pipeline, baseline = linear_case
    top = fitted["ranges"]["numeric"]["heat_input"]["max"]
    settings, points, problems = scenarios.read_sweep(
        {"mode": "value", "low": "0", "high": str(top * 2), "step": str(top / 4)},
        baseline["inputs"]["heat_input"], fitted["ranges"], "heat_input")
    _, rows = scenarios.one_at_a_time(pipeline, fitted["ranges"], baseline, "heat_input", points)
    assert any(row["outside"] for row in rows)
    assert all(row["outside"] == (row["value"] > top or row["value"] < fitted["ranges"]["numeric"]["heat_input"]["min"])
               for row in rows)
    inputs = dict(baseline["inputs"], fuel_family="Gas", unit_type="Tangentially-fired")
    warnings = scenarios.warnings_for(inputs, fitted["ranges"], 2023)
    assert any("extrapolation" in warning for warning in warnings)


def test_bad_sweep_choices_fall_back_with_a_message(linear_case):
    fitted, _, baseline = linear_case
    value = baseline["inputs"]["gross_load"]
    _, points, problems = scenarios.read_sweep({"low": "abc", "step": "0"}, value, fitted["ranges"], "gross_load")
    assert any("isn't a number" in p for p in problems) and any("more than 0" in p for p in problems)
    _, points, problems = scenarios.read_sweep({"low": "50", "high": "10"}, value, fitted["ranges"], "gross_load")
    assert any("above the start" in p for p in problems)
    _, points, problems = scenarios.read_sweep({"low": "-100", "high": "100", "step": "0.01"}, value,
                                               fitted["ranges"], "gross_load")
    assert len(points) <= scenarios.MAX_POINTS + 1


# ---------- Pages and downloads (synthetic selection in place of Explore) ----------

@pytest.fixture()
def synthetic_explore(monkeypatch):
    rows = synthetic_rows()

    def fake(params, page=None, per_page=None, everything=False):
        return {"rows": rows, "total": len(rows), "partial": False,
                "parsed": {"understood": [], "terms": []}}
    monkeypatch.setattr(smart_search, "explore", fake)


def read_csv(response):
    return pd.read_csv(io.StringIO(response.get_data(as_text=True)), comment="#")


def test_predictions_page_and_downloads(client, synthetic_explore):
    page = client.get("/predictions").get_data(as_text=True)
    for text in ("Three models. One honest test.", "Mean baseline", "Linear regression", "Decision tree",
                 "No target leakage", "2018–2020", "2021–2022", "Chosen", "Year-trend forecast", "Biggest misses"):
        assert text in page
    # Every chart explains itself, and selecting a bar shows how its error was calculated
    for chart_id in ("model_errors", "predicted_actual", "trend_forecast"):
        assert f'id="about-{chart_id}"' in page and f'id="explain-{chart_id}"' in page
    errors = json.loads(re.search(r'<script type="application/json" id="spec-model_errors">(.*?)</script>', page,
                                  re.S).group(1))
    assert errors["details"]["0:0"]["calc"][-1]["label"] == "Mean absolute error"
    evaluation = client.get("/predictions/download?what=evaluation")
    text = evaluation.get_data(as_text=True)
    for line in ("# Prediction target", "# Training years,2018–2020 (120 records)", "# Test year,2023 (40 records)",
                 "# Model: Decision tree", "scikit-learn", "# Saved models"):
        assert line in text
    table = read_csv(evaluation)
    assert set(table["Model"]) == {"Mean baseline", "Linear regression", "Decision tree"}
    assert len(read_csv(client.get("/predictions/download?what=predictions"))) == 40
    assert client.get("/predictions/download?what=predictions&format=xlsx").status_code == 200
    assert client.get("/predictions/download?what=trend").status_code == 200
    assert client.get("/predictions/download?chart=model_errors").status_code == 200
    assert client.get("/predictions/download?chart=nope").status_code == 404
    assert "SO2" in client.get("/predictions?target=so2_mass").get_data(as_text=True)


def test_scenarios_page_and_downloads(client, synthetic_explore):
    page = client.get("/scenarios?model=linear&unit=7&input=heat_input").get_data(as_text=True)
    for text in ("Change one thing.", "The baseline.", "One at a time.", "Heat input −5%", "Runs 10% more",
                 "High efficiency (combined)", "model-response"):
        assert text in page
    sweep = client.get("/scenarios/download?model=linear&unit=7&input=heat_input&what=sensitivity")
    text = sweep.get_data(as_text=True)
    assert "# Held constant,Every other input at the baseline value" in text
    assert '# Baseline,"Plant 7 (KY) unit 1, 2023 (unit key 7)"' in text
    assert len(read_csv(sweep)) == 11
    scenarios_spec = json.loads(re.search(r'<script type="application/json" id="spec-scenarios">(.*?)</script>',
                                          page, re.S).group(1))
    heat = next(detail for detail in scenarios_spec["details"].values() if detail["title"] == "Heat input −5%")
    assert heat["calc"][-1]["value"] == "−5.0%"
    compared = read_csv(client.get("/scenarios/download?model=linear&unit=7&what=scenarios"))
    assert compared.loc[compared["Scenario"] == "Heat input −5%", "Change from baseline (%)"].iloc[0] == \
        pytest.approx(-5.0, abs=1e-6)
    # Bad choices don't break the page; they come back as messages
    page = client.get("/scenarios?unit=999&step=0&low=abc").get_data(as_text=True)
    assert "has no 2023 record" in page
    assert "more than 0" in page


def test_prediction_pages_explain_when_there_is_not_enough_data(client):
    page = client.get("/predictions").get_data(as_text=True)
    assert "Not enough records" in page
    assert "Year-trend forecast" in page
    assert client.get("/scenarios").status_code == 200
    assert client.get("/scenarios/download?what=sensitivity").status_code == 404
