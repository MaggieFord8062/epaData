
from sqlalchemy import func

from database import SessionLocal
from models import AnnualRecord

import numpy as np

from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


def get_annual_co2_totals():
    """
    Calculate total CO2 emissions across all units
    for each reporting year.
    """

    session = SessionLocal()

    try:
        results = (
            session.query(
                AnnualRecord.year,
                func.sum(AnnualRecord.co2_mass).label("total_co2")
            )
            .filter(AnnualRecord.co2_mass.isnot(None))
            .group_by(AnnualRecord.year)
            .order_by(AnnualRecord.year)
            .all()
        )

        annual_totals = []

        for row in results:
            annual_totals.append({
                "year": row.year,
                "co2_total": float(row.total_co2)
            })

        return annual_totals

    finally:
        session.close()


def train_prediction_models():
    """
    Train and evaluate three models for predicting annual
    CO2 emissions.

    Training: 1995-2022
    Validation: 2023-2024
    Testing: 2025
    """

    annual_totals = get_annual_co2_totals()

    # Convert database results into model inputs
    years = np.array([row["year"] for row in annual_totals])
    emissions = np.array([row["co2_total"] for row in annual_totals])

    # Split the data
    train_mask = (years >= 1995) & (years <= 2022)
    validation_mask = (years >= 2023) & (years <= 2024)
    test_mask = years == 2025

    X_train = years[train_mask].reshape(-1, 1)
    y_train = emissions[train_mask]

    X_validation = years[validation_mask].reshape(-1, 1)
    y_validation = emissions[validation_mask]

    X_test = years[test_mask].reshape(-1, 1)
    y_test = emissions[test_mask]

    # Make sure all required years exist
    if len(X_train) == 0 or len(X_validation) != 2 or len(X_test) != 1:
        raise ValueError(
            "Missing required historical data. "
            "Check that years 1995-2025 are available."
        )

    # Define models
    models = {
        "Mean Baseline": None,
        "Linear Regression": LinearRegression(),
        "Decision Tree": DecisionTreeRegressor(
            max_depth=3,
            random_state=42
        )
    }

    # Train machine learning models
    for name, model in models.items():
        if model is not None:
            model.fit(X_train, y_train)

    # Evaluate using validation data
    validation_results = {}

    for name, model in models.items():

        if name == "Mean Baseline":
            predictions = np.full(
                len(y_validation),
                np.mean(y_train)
            )
        else:
            predictions = model.predict(X_validation)

        validation_results[name] = {
            "mae": float(mean_absolute_error(y_validation, predictions)),
            "rmse": float(np.sqrt(mean_squared_error(y_validation, predictions)))
        }

    # Evaluate using the 2025 test data
    test_results = {}

    for name, model in models.items():

        if name == "Mean Baseline":
            prediction = float(np.mean(y_train))
        else:
            prediction = float(model.predict(X_test)[0])

        test_results[name] = {
            "predicted": prediction,
            "actual": float(y_test[0]),
            "mae": float(abs(y_test[0] - prediction)),
            "rmse": float(abs(y_test[0] - prediction))
        }

    return {
        "validation_results": validation_results,
        "test_results": test_results
    }

def generate_forecast(future_years=None):
    """
    Generate future annual CO2 emissions forecasts.

    Retrains the models using all available historical data
    through 2025.

    Forecast years: 2026-2030
    """

    if future_years is None:
        future_years = [2026, 2027, 2028, 2029, 2030]

    annual_totals = get_annual_co2_totals()

    # Convert historical data into model inputs
    years = np.array([row["year"] for row in annual_totals])
    emissions = np.array([row["co2_total"] for row in annual_totals])

    # Use all historical data through 2025
    historical_mask = (years >= 1995) & (years <= 2025)

    X_train = years[historical_mask].reshape(-1, 1)
    y_train = emissions[historical_mask]

    if len(X_train) == 0 or 2025 not in years[historical_mask]:
        raise ValueError("Historical CO2 data through 2025 is required.")

    # Define models
    models = {
        "Mean Baseline": None,
        "Linear Regression": LinearRegression(),
        "Decision Tree": DecisionTreeRegressor(
            max_depth=3,
            random_state=42
        )
    }

    # Retrain models using all historical data
    for name, model in models.items():
        if model is not None:
            model.fit(X_train, y_train)

    # Prepare future years
    X_future = np.array(future_years).reshape(-1, 1)

    # Generate forecasts
    forecast_results = []

    for i, year in enumerate(future_years):

        year_results = {
            "year": year
        }

        for name, model in models.items():

            if name == "Mean Baseline":
                prediction = float(np.mean(y_train))
            else:
                prediction = float(model.predict(X_future[i].reshape(1, -1))[0])

            year_results[name] = prediction

        forecast_results.append(year_results)

    return forecast_results


# Run a test when this file is executed directly
if __name__ == "__main__":

    results = train_prediction_models()

    print("\nVALIDATION RESULTS")

    for model, values in results["validation_results"].items():
        print(model, values)

    print("\n2025 TEST RESULTS")

    for model, values in results["test_results"].items():
        print(model, values)

    print("\nFUTURE CO2 FORECAST")

    forecasts = generate_forecast()

    for row in forecasts:
        print(row)