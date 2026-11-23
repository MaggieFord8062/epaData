import numpy as np
from sqlalchemy import func
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor

from database import SessionLocal
from models import AnnualRecord, Unit


# Supported prediction targets
POLLUTANTS = {
    "co2_mass": "CO2",
    "so2_mass": "SO2",
    "nox_mass": "NOx"
}


def get_historical_data(pollutant):
    if pollutant not in POLLUTANTS:
        return []

    session = SessionLocal()

    try:
        target_column = getattr(AnnualRecord, pollutant)

        records = (
            session.query(AnnualRecord, Unit)
            .join(
                Unit,
                AnnualRecord.internal_unit_key == Unit.internal_unit_key
            )
            .filter(
                target_column.isnot(None),
                AnnualRecord.gross_load.isnot(None),
                AnnualRecord.heat_input.isnot(None),
                AnnualRecord.operating_time.isnot(None),
                Unit.primary_fuel.isnot(None)
            )
            .all()
        )

        data = []

        for record, unit in records:
            data.append({
                "unit_key": record.internal_unit_key,
                "year": record.year,
                "gross_load": record.gross_load,
                "heat_input": record.heat_input,
                "operating_time": record.operating_time,
                "fuel_type": unit.primary_fuel,
                "target_value": getattr(record, pollutant)
            })

        return data

    finally:
        session.close()


def train_sensitivity_models(pollutant):
    if pollutant not in POLLUTANTS:
        return {"error": "Invalid pollutant selection."}

    data = get_historical_data(pollutant)

    if len(data) < 5:
        return {
            "error": f"Not enough historical data to train a model for {POLLUTANTS[pollutant]}."
        }

    feature_names = [
        "gross_load",
        "heat_input",
        "operating_time",
        "fuel_type"
    ]

    X = [
        [
            row["gross_load"],
            row["heat_input"],
            row["operating_time"],
            row["fuel_type"]
        ]
        for row in data
    ]

    y = np.array([row["target_value"] for row in data])

    preprocessor = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median"), [0, 1, 2]),
        ("fuel", OneHotEncoder(handle_unknown="ignore"), [3])
    ])

    linear_model = Pipeline([
        ("preprocessor", preprocessor),
        ("regressor", LinearRegression())
    ])

    tree_model = Pipeline([
        ("preprocessor", preprocessor),
        ("regressor", DecisionTreeRegressor(
            max_depth=3,
            random_state=42
        ))
    ])

    linear_model.fit(X, y)
    tree_model.fit(X, y)

    return {
        "linear_regression": linear_model,
        "decision_tree": tree_model,
        "training_data": data,
        "input_ranges": {
            "gross_load": {
                "min": min(row["gross_load"] for row in data),
                "max": max(row["gross_load"] for row in data)
            },
            "heat_input": {
                "min": min(row["heat_input"] for row in data),
                "max": max(row["heat_input"] for row in data)
            },
            "operating_time": {
                "min": min(row["operating_time"] for row in data),
                "max": max(row["operating_time"] for row in data)
            }
        }
    }


def run_sensitivity_analysis(
    internal_unit_key,
    model_name,
    gross_load_changes,
    heat_input_changes,
    fuel_type,
    pollutant="co2_mass"
):
    models = train_sensitivity_models(pollutant)

    if "error" in models:
        return models

    if model_name not in ["linear_regression", "decision_tree"]:
        return {"error": "Invalid prediction model."}

    data = models["training_data"]

    available_fuels = {
        row["fuel_type"] for row in data
    }

    if fuel_type not in available_fuels:
        return {
            "error": f"{fuel_type} was not represented in the model's training data."
        }

    unit_records = [
        row for row in data
        if row["unit_key"] == internal_unit_key
    ]

    if not unit_records:
        return {
            "error": "No complete historical records were found for this unit and pollutant."
        }

    baseline = max(unit_records, key=lambda row: row["year"])

    model = models[model_name]

    baseline_inputs = [[
        baseline["gross_load"],
        baseline["heat_input"],
        baseline["operating_time"],
        baseline["fuel_type"]
    ]]

    baseline_prediction = float(
        model.predict(baseline_inputs)[0]
    )

    results = []

    for gross_change, heat_change in zip(
        gross_load_changes,
        heat_input_changes
    ):
        modified_gross_load = (
            baseline["gross_load"] * (1 + gross_change / 100)
        )

        modified_heat_input = (
            baseline["heat_input"] * (1 + heat_change / 100)
        )

        modified_inputs = [[
            modified_gross_load,
            modified_heat_input,
            baseline["operating_time"],
            fuel_type
        ]]

        prediction = float(model.predict(modified_inputs)[0])

        absolute_change = prediction - baseline_prediction

        percent_change = (
            (absolute_change / baseline_prediction) * 100
            if baseline_prediction != 0
            else None
        )

        gross_range = models["input_ranges"]["gross_load"]
        heat_range = models["input_ranges"]["heat_input"]

        out_of_range = (
            modified_gross_load < gross_range["min"]
            or modified_gross_load > gross_range["max"]
            or modified_heat_input < heat_range["min"]
            or modified_heat_input > heat_range["max"]
        )

        results.append({
            "gross_load_change": gross_change,
            "gross_load_value": modified_gross_load,
            "heat_input_change": heat_change,
            "heat_input_value": modified_heat_input,
            "fuel_type": fuel_type,
            "predicted_emissions": prediction,
            "absolute_change": absolute_change,
            "percent_change": percent_change,
            "out_of_range": out_of_range
        })

    return {
        "unit": internal_unit_key,
        "model": model_name,
        "pollutant": pollutant,
        "pollutant_name": POLLUTANTS[pollutant],
        "baseline_year": baseline["year"],
        "baseline_gross_load": baseline["gross_load"],
        "baseline_heat_input": baseline["heat_input"],
        "baseline_fuel_type": baseline["fuel_type"],
        "selected_fuel_type": fuel_type,
        "baseline_prediction": baseline_prediction,
        "results": results,
        "input_ranges": models["input_ranges"]
    }
