"""
Phase 2 prediction module (proposal section 5).

Like every analysis page, the models use exactly the records selected in Explore.
The page answers two questions about the chosen pollutant (CO2, SO2 or NOx):

1. Unit model: how much does a generating unit emit in a year, given how it operated?
   - Target:  one unit's annual emissions of the pollutant, in short tons.
   - Inputs:  gross load, heat input and operating time that year, the unit's fuel family
              and unit type, and whether it reports an SO2 control and a NOx control.
   - Not used (target leakage): the same year's CO2, SO2 and NOx, emission intensities
     and year-over-year changes, because they are the target or are calculated from it.
   - Models:  a mean baseline, linear regression and a decision tree (scikit-learn).
   - Testing: chronological. The earlier years train the models, the next years choose
              between them (validation), and the most recent year is the final test,
              used once.
   The fitted models are what the Scenarios page (sensitivity analysis) changes inputs on.

2. Year-trend forecast (the first version of this module): the selection's annual total,
   predicted from the year alone with the same three kinds of model, and forecast a few
   years ahead.

Fitted models are saved with joblib in trained_models/ and described in the
prediction_model table, so the same model can be reopened and every result reproduced.
"""

import hashlib
import json
import os
import threading
from datetime import datetime

import numpy as np
import pandas as pd

import analysis

# Change this whenever the modeling changes, so saved models and exports say which version made them
PREDICTION_VERSION = "1.0"

MODEL_FOLDER = "trained_models"
KEEP_RUNS = 30          # older saved runs are deleted
RANDOM_STATE = 42

# ---------- What is predicted, and from what ----------

TARGETS = {
    "co2_mass": {"label": "CO2", "name": "Annual CO2 mass", "control": "so2_control"},
    "so2_mass": {"label": "SO2", "name": "Annual SO2 mass", "control": "so2_control"},
    "nox_mass": {"label": "NOx", "name": "Annual NOx mass", "control": "nox_control"},
}
DEFAULT_TARGET = "co2_mass"
TARGET_UNIT = "short tons"

NUMERIC_INPUTS = {
    "gross_load": {"label": "Gross load", "unit": "MWh", "per": "MWh"},
    "heat_input": {"label": "Heat input", "unit": "mmBtu", "per": "mmBtu"},
    "operating_time": {"label": "Operating time", "unit": "hours", "per": "hour"},
}
CATEGORY_INPUTS = {
    "fuel_family": {"label": "Fuel", "unit": "Coal, Gas, or Oil and other"},
    "unit_type": {"label": "Unit type", "unit": "as reported to EPA"},
}
FLAG_INPUTS = {
    "so2_control": {"label": "SO2 control", "unit": "1 if the unit reports one, else 0"},
    "nox_control": {"label": "NOx control", "unit": "1 if the unit reports one, else 0"},
}
FEATURES = list(NUMERIC_INPUTS) + list(CATEGORY_INPUTS) + list(FLAG_INPUTS)
INPUT_LABELS = {key: item["label"] for key, item in {**NUMERIC_INPUTS, **CATEGORY_INPUTS, **FLAG_INPUTS}.items()}

EXCLUDED_INPUTS = [
    ("Same-year CO2, SO2 and NOx", "The target itself, or measured from the same stack at the same time."),
    ("Emission intensities (tons or lb per MWh)", "Calculated by dividing the target by gross load."),
    ("Year-over-year changes", "Calculated from the target."),
    ("Facility and unit names or IDs", "The model would memorize individual units instead of learning how "
                                       "operation relates to emissions."),
    ("Reporting year", "The unit model describes how emissions depend on operation, not on the calendar, "
                       "and a tree can't extend to a year it has never seen."),
]

HEAT_INPUT_NOTE = ("EPA calculates much of the reported CO2 from heat input and a fuel-specific factor, so CO2 "
                   "models that use heat input are expected to be very accurate. That is a real physical "
                   "relationship, not the target leaking in, but it means the accuracy describes how CO2 follows "
                   "the fuel burned. It is not a forecast of future years.")

ESTIMATION_NOTE = ("The unit model estimates a year's emissions from that same year's operating data. That makes "
                   "it suited to what-if questions (the Scenarios page). To forecast a future year it would also "
                   "need that year's operation, which is unknown; the year-trend forecast extrapolates totals "
                   "instead.")

LIMITATIONS = [
    "Predictions describe associations in past CAMPD data. They don't show that changing an input causes the "
    "predicted change.",
    "The test year is a single, most recent year. A different year could give different errors.",
    "Units that were rare in training (an unusual fuel and unit-type combination, or very large or small "
    "operation) are predicted less reliably.",
    "Linear regression fits one straight-line effect per input for every fuel, so it can miss differences between "
    "fuels. It can also give negative values, which are shown as 0.",
    "A decision tree predicts the average of similar training records, so its predictions change in steps and "
    "never go beyond the largest value it was trained on.",
    "Year-trend forecasts assume the past trend continues. Totals also change when the database holds more or "
    "fewer units in a year.",
]

MODELS = {
    "mean": {"name": "Mean baseline",
             "about": "Predicts the training years' average for every record. A useful model has to beat it."},
    "linear": {"name": "Linear regression",
               "about": "Fits a straight-line effect for each input (ordinary least squares)."},
    "tree": {"name": "Decision tree",
             "about": "Splits records into groups with similar inputs and predicts each group's average. "
                      "Its depth is chosen on the validation years."},
}
CANDIDATES = ["linear", "tree"]          # the baseline is reported but never chosen as the working model
TREE_DEPTHS = [2, 3, 4, 6, 8, 10, 12, 16]
TREE_MIN_LEAF = 5
TREND_TREE_DEPTH = 3
FORECAST_YEARS = 5

MIN_TRAIN = 20
MIN_EVALUATION = 3
SMALL_TEST = 30

METRICS = {
    "mae": ("MAE", "Mean absolute error: the average size of a miss, in short tons. Lower is better."),
    "rmse": ("RMSE", "Root mean squared error: like MAE, but large misses count more. Lower is better."),
    "r2": ("R²", "Share of the differences between records that the model explains. 1 is perfect, "
                 "0 is no better than predicting the average, below 0 is worse."),
    "wape": ("Weighted % error", "Total absolute error ÷ total actual emissions × 100. Lower is better."),
    "mape": ("MAPE", "Mean absolute percentage error, over records with emissions above 0."),
    "bias": ("Mean error", "Average of predicted − actual. Above 0 means the model predicts too much on average."),
}
MAPE_NOTE = ("Plain MAPE is undefined for records with zero emissions and is dominated by tiny emitters (a 1-ton "
             "miss on a 0.1-ton unit is 1,000%), so the unit model shows the weighted % error instead. MAPE is "
             "still in the downloads.")


def scikit_learn_version():
    import sklearn
    return sklearn.__version__


def software_version():
    return (analysis.pipeline_version() + "; scikit-learn " + scikit_learn_version()
            + "; prediction module " + PREDICTION_VERSION)


# ---------- The modeling table ----------

def has_control(series):
    return (series.fillna("").astype(str).str.strip() != "").astype("int64")


def fuel_families(series):
    """Coal, Gas or Oil and other; a missing fuel stays "Not reported" instead of becoming Oil and other."""
    blank = series.isna() | (series.astype(str).str.strip() == "")
    families = series.map(analysis.fuel_family)
    return families.where(~blank, analysis.NOT_REPORTED)


def model_frame(frame, target):
    """
    One row per record with the inputs and the target, from an analysis DataFrame.
    Records missing the target or a numeric input, or with a negative value, are left out
    (they are counted, never filled in). Returns (rows used, number left out).
    """
    data = pd.DataFrame({
        "unit_key": frame["unit_key"],
        "year": frame["year"],
        "facility_id": frame["facility_id"],
        "label": analysis.unit_labels(frame) if len(frame) else pd.Series(dtype="object"),
        "primary_fuel": frame["primary_fuel"],
        "gross_load": frame["gross_load"],
        "heat_input": frame["heat_input"],
        "operating_time": frame["operating_time"],
        "fuel_family": fuel_families(frame["primary_fuel"]),
        "unit_type": analysis.group_labels(frame, "unit_type"),
        "so2_control": has_control(frame["so2_controls"]),
        "nox_control": has_control(frame["nox_controls"]),
        "target": frame[target],
    }, index=frame.index)
    needed = ["year", "target"] + list(NUMERIC_INPUTS)
    complete = data[needed].notna().all(axis=1)
    complete &= (data[["target"] + list(NUMERIC_INPUTS)].fillna(0) >= 0).all(axis=1)
    used = data[complete].copy()
    used["year"] = used["year"].astype("int64")
    return used, int((~complete).sum())


def split_years(years):
    """
    Chronological split of the reporting years: the most recent year is the test year, the one or two
    years before it are the validation years (two when there are at least six years), and every
    earlier year trains the models. Returns None when there are fewer than three years.
    """
    years = sorted({int(year) for year in years})
    if len(years) < 3:
        return None
    test = years[-1:]
    validation = years[-3:-1] if len(years) >= 6 else years[-2:-1]
    train = years[:len(years) - len(test) - len(validation)]
    return {"train": train, "validation": validation, "test": test}


def period(years):
    if not years:
        return "—"
    if len(years) == 1:
        return str(years[0])
    return f"{years[0]}–{years[-1]}"


# ---------- Models ----------

def make_pipeline(kind, depth=None, features=None):
    """The scikit-learn pipeline for one model: encode the inputs, then fit the regressor."""
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.tree import DecisionTreeRegressor

    features = features or FEATURES
    numbers = [name for name in features if name in NUMERIC_INPUTS]
    flags = [name for name in features if name in FLAG_INPUTS]
    categories = [name for name in features if name in CATEGORY_INPUTS]
    # Gross load and heat input run into the millions while the flags are 0 or 1. Standardizing the
    # numbers keeps least squares numerically stable (results don't depend on the solver's cutoffs);
    # it doesn't change any prediction, and coefficients are converted back to real units.
    encode = ColumnTransformer([
        ("numbers", StandardScaler(), numbers),
        ("flags", "passthrough", flags),
        ("categories", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categories),
    ])
    if kind == "mean":
        regressor = DummyRegressor(strategy="mean")
    elif kind == "linear":
        regressor = LinearRegression()
    else:
        regressor = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=TREE_MIN_LEAF,
                                          random_state=RANDOM_STATE)
    return Pipeline([("encode", encode), ("model", regressor)])


def predict(pipeline, rows):
    """Predictions for a DataFrame of inputs. Emissions can't be negative, so values below 0 become 0."""
    return np.clip(pipeline.predict(rows), 0, None)


def parameters(kind, depth=None):
    if kind == "mean":
        return {"strategy": "mean of the training target"}
    if kind == "linear":
        return {"method": "ordinary least squares", "fit_intercept": True,
                "categories": "one-hot encoded; unseen categories ignored", "negative predictions": "set to 0"}
    return {"max_depth": depth, "min_samples_leaf": TREE_MIN_LEAF, "random_state": RANDOM_STATE,
            "criterion": "squared_error", "depths tried on validation": TREE_DEPTHS}


def scores(actual, predicted):
    """MAE, RMSE, R², weighted % error, MAPE and mean error for one set of predictions."""
    actual = np.asarray(actual, dtype="float64")
    predicted = np.asarray(predicted, dtype="float64")
    n = len(actual)
    if n == 0:
        return {"n": 0, "mae": None, "rmse": None, "r2": None, "wape": None, "mape": None,
                "mape_records": 0, "bias": None, "actual_total": None, "predicted_total": None}
    error = predicted - actual
    spread = float(np.sum((actual - actual.mean()) ** 2))
    positive = actual > 0
    total = float(np.sum(np.abs(actual)))
    return {
        "n": int(n),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "r2": (1 - float(np.sum(error ** 2)) / spread) if n > 1 and spread > 0 else None,
        "wape": float(np.sum(np.abs(error)) / total * 100) if total > 0 else None,
        "mape": float(np.mean(np.abs(error[positive]) / actual[positive]) * 100) if positive.any() else None,
        "mape_records": int(positive.sum()),
        "bias": float(np.mean(error)),
        "actual_total": float(np.sum(actual)),
        "predicted_total": float(np.sum(predicted)),
    }


def training_ranges(rows):
    """What the final models saw in training: numeric ranges and categories, for out-of-range warnings."""
    ranges = {}
    for name in NUMERIC_INPUTS:
        values = rows[name]
        ranges[name] = {"min": float(values.min()), "max": float(values.max())}
    categories = {name: sorted(rows[name].astype(str).unique().tolist()) for name in CATEGORY_INPUTS}
    pairs = sorted({f"{fuel}|{kind}" for fuel, kind in zip(rows["fuel_family"], rows["unit_type"])})
    controls = sorted({f"{fuel}|{name}" for name in FLAG_INPUTS
                       for fuel in rows.loc[rows[name] == 1, "fuel_family"].astype(str).unique()})
    return {"numeric": ranges, "categories": categories, "fuel_unit_types": pairs, "fuel_controls": controls}


def explain_linear(pipeline):
    """Linear-regression coefficients for the numeric inputs and the controls, in plain units."""
    encode = pipeline.named_steps["encode"]
    names = list(encode.get_feature_names_out())
    coefficients = pipeline.named_steps["model"].coef_
    scaler = encode.named_transformers_["numbers"]
    scale = dict(zip(scaler.feature_names_in_, scaler.scale_))
    found = []
    for raw, value in zip(names, coefficients):
        group, _, name = raw.partition("__")
        if group == "numbers":
            # The model saw (value − mean) ÷ standard deviation, so per real unit the effect is coef ÷ sd
            found.append({"input": NUMERIC_INPUTS[name]["label"], "effect": float(value / scale[name]),
                          "reads": "short tons per extra " + NUMERIC_INPUTS[name]["per"]})
        elif group == "flags":
            found.append({"input": FLAG_INPUTS[name]["label"] + " reported", "effect": float(value),
                          "reads": "short tons compared with no control"})
    return found


def explain_tree(pipeline):
    """Share of the decision tree's error reduction that came from each input (sums to 100)."""
    names = list(pipeline.named_steps["encode"].get_feature_names_out())
    importance = pipeline.named_steps["model"].feature_importances_
    totals = {}
    for raw, value in zip(names, importance):
        group, _, name = raw.partition("__")
        if group == "categories":
            name = next(key for key in CATEGORY_INPUTS if name.startswith(key + "_"))
        totals[name] = totals.get(name, 0.0) + float(value)
    found = [{"input": INPUT_LABELS[name], "share": share * 100} for name, share in totals.items()]
    return sorted(found, key=lambda item: -item["share"])


def train(frame, target):
    """
    Fit and evaluate the unit models for one target. Returns a dict with the split, every model's
    validation and test scores, the chosen model, the test-year predictions, the training ranges
    and the fitted final pipelines (under "pipelines"). Returns {"error": message} when the
    selection can't support a chronological test.
    """
    rows, left_out = model_frame(frame, target)
    split = split_years(rows["year"]) if len(rows) else None
    if split is None:
        years = rows["year"].nunique() if len(rows) else 0
        return {"error": (f"The models need at least three reporting years (to train, validate and test); "
                          f"this selection has {years} with complete data. Widen the year range in Explore."),
                "left_out": left_out, "records": int(len(rows))}

    train_rows = rows[rows["year"].isin(split["train"])]
    validation_rows = rows[rows["year"].isin(split["validation"])]
    test_rows = rows[rows["year"].isin(split["test"])]
    counts = {"train": int(len(train_rows)), "validation": int(len(validation_rows)), "test": int(len(test_rows))}
    if counts["train"] < MIN_TRAIN or counts["validation"] < MIN_EVALUATION or counts["test"] < MIN_EVALUATION:
        return {"error": (f"Not enough records for a fair test: {counts['train']:,} training, "
                          f"{counts['validation']:,} validation and {counts['test']:,} test records "
                          f"(at least {MIN_TRAIN}, {MIN_EVALUATION} and {MIN_EVALUATION} are needed). "
                          f"Widen the selection in Explore."),
                "left_out": left_out, "records": int(len(rows)), "split": split, "counts": counts}

    x_train, y_train = train_rows[FEATURES], train_rows["target"].to_numpy()
    x_validation, y_validation = validation_rows[FEATURES], validation_rows["target"].to_numpy()

    # 1. Fit on the training years and compare on the validation years
    validation = {}
    for kind in ("mean", "linear"):
        model = make_pipeline(kind).fit(x_train, y_train)
        validation[kind] = scores(y_validation, predict(model, x_validation))

    depth_search = []
    best_depth = None
    for depth in TREE_DEPTHS:
        model = make_pipeline("tree", depth).fit(x_train, y_train)
        result = scores(y_validation, predict(model, x_validation))
        depth_search.append({"depth": depth, "mae": result["mae"], "rmse": result["rmse"]})
        if best_depth is None or result["mae"] < validation["tree"]["mae"] - 1e-9:
            validation["tree"], best_depth = result, depth
    chosen = min(CANDIDATES, key=lambda kind: (validation[kind]["mae"], CANDIDATES.index(kind)))

    # 2. Refit on training + validation years with those settings; test once on the most recent year
    fit_rows = pd.concat([train_rows, validation_rows])
    x_fit, y_fit = fit_rows[FEATURES], fit_rows["target"].to_numpy()
    x_test, y_test = test_rows[FEATURES], test_rows["target"].to_numpy()
    pipelines, test, predictions = {}, {}, {}
    for kind in MODELS:
        model = make_pipeline(kind, best_depth if kind == "tree" else None).fit(x_fit, y_fit)
        pipelines[kind] = model
        predictions[kind] = predict(model, x_test)
        test[kind] = scores(y_test, predictions[kind])

    # 3. How much the chosen model leans on heat input: the same model refit without it
    without = [name for name in FEATURES if name != "heat_input"]
    reduced = make_pipeline(chosen, best_depth if chosen == "tree" else None, without)
    reduced.fit(fit_rows[without], y_fit)
    without_heat = scores(y_test, predict(reduced, test_rows[without]))

    tested = test_rows[["unit_key", "year", "facility_id", "label", "primary_fuel", "fuel_family", "unit_type",
                        "gross_load", "heat_input", "operating_time", "so2_control", "nox_control"]].copy()
    tested["actual"] = y_test
    for kind in MODELS:
        tested["predicted_" + kind] = predictions[kind]
    tested["error"] = tested["predicted_" + chosen] - tested["actual"]

    return {
        "target": target,
        "split": split,
        "counts": counts,
        "left_out": left_out,
        "records": int(len(rows)),
        "validation": validation,
        "test": test,
        "chosen": chosen,
        "beats_baseline": validation[chosen]["mae"] < validation["mean"]["mae"],
        "tree_depth": best_depth,
        "depth_search": depth_search,
        "parameters": {kind: parameters(kind, best_depth if kind == "tree" else None) for kind in MODELS},
        "without_heat": without_heat,
        "linear_effects": explain_linear(pipelines["linear"]),
        "tree_importance": explain_tree(pipelines["tree"]),
        "ranges": training_ranges(fit_rows),
        "tested": tested.reset_index(drop=True),
        "pipelines": pipelines,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "software": software_version(),
    }


# ---------- Saving and reopening fitted models (joblib file + prediction_model table) ----------

_lock = threading.Lock()


def run_key(frame, target):
    """Identifies one training run: the same selection, data and code give the same key."""
    text = "|".join([PREDICTION_VERSION, target, analysis.selection_fingerprint(frame), analysis.database_state(),
                     scikit_learn_version()])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save_run(key, result, frame, filter_labels):
    """Write the fitted models to trained_models/<key>.joblib and describe each one in the database."""
    import joblib
    from database import SessionLocal
    from models import PredictionModel

    os.makedirs(MODEL_FOLDER, exist_ok=True)
    path = os.path.join(MODEL_FOLDER, key + ".joblib")
    joblib.dump(result, path, compress=3)
    digest = file_sha256(path)

    session = SessionLocal()
    try:
        session.query(PredictionModel).filter(PredictionModel.run_key == key).delete()
        for kind in MODELS:
            session.add(PredictionModel(
                run_key=key,
                created_at=result["trained_at"],
                target=result["target"],
                model_kind=kind,
                model_name=MODELS[kind]["name"],
                is_chosen=kind == result["chosen"],
                features=json.dumps(FEATURES),
                parameters=json.dumps(result["parameters"][kind]),
                train_years=period(result["split"]["train"]),
                validation_years=period(result["split"]["validation"]),
                test_years=period(result["split"]["test"]),
                train_records=result["counts"]["train"],
                validation_records=result["counts"]["validation"],
                test_records=result["counts"]["test"],
                validation_scores=json.dumps(result["validation"][kind]),
                test_scores=json.dumps(result["test"][kind]),
                selection_fingerprint=analysis.selection_fingerprint(frame),
                selection=json.dumps(filter_labels),
                file_path=path,
                file_sha256=digest,
                software=result["software"],
            ))
        session.commit()
    finally:
        session.close()
    remove_old_runs()
    return path, digest


def load_run(key):
    """The saved run for this key, or None when it isn't saved (or its file is missing or was changed)."""
    import joblib
    from database import SessionLocal
    from models import PredictionModel

    session = SessionLocal()
    try:
        saved = session.query(PredictionModel).filter(PredictionModel.run_key == key).first()
        if saved is None:
            return None
        path, digest = saved.file_path, saved.file_sha256
    finally:
        session.close()
    if not path or not os.path.exists(path) or file_sha256(path) != digest:
        return None
    result = joblib.load(path)
    result["file_path"], result["file_sha256"] = path, digest
    return result


def remove_old_runs():
    """Keep the newest KEEP_RUNS training runs; delete older files and rows."""
    from database import SessionLocal
    from models import PredictionModel

    session = SessionLocal()
    try:
        newest = {}
        for key, created in session.query(PredictionModel.run_key, PredictionModel.created_at).all():
            newest[key] = max(newest.get(key, ""), created or "")
        old = sorted(newest, key=lambda key: newest[key], reverse=True)[KEEP_RUNS:]
        for key in old:
            for row in session.query(PredictionModel).filter(PredictionModel.run_key == key).all():
                if row.file_path and os.path.exists(row.file_path):
                    os.remove(row.file_path)
                session.delete(row)
        session.commit()
    finally:
        session.close()


def fitted_models(frame, target, filter_labels):
    """
    The unit models for this selection and target: reopened from trained_models/ when this exact
    selection was trained before on the same data, otherwise trained now and saved.
    """
    key = run_key(frame, target)
    with _lock:
        result = load_run(key)
        if result is None:
            result = train(frame, target)
            if "error" in result:
                return result
            path, digest = save_run(key, result, frame, filter_labels)
            result["file_path"], result["file_sha256"] = path, digest
    result["run_key"] = key
    return result


def saved_models(key):
    """The prediction_model rows for one run, for the page and the export metadata."""
    from database import SessionLocal
    from models import PredictionModel

    session = SessionLocal()
    try:
        rows = session.query(PredictionModel).filter(PredictionModel.run_key == key) \
            .order_by(PredictionModel.prediction_model_id).all()
        return [{"id": row.prediction_model_id, "name": row.model_name, "kind": row.model_kind,
                 "chosen": bool(row.is_chosen), "created": row.created_at, "file": row.file_path,
                 "sha256": row.file_sha256} for row in rows]
    finally:
        session.close()


# ---------- Year-trend forecast (annual totals from the year alone) ----------

def get_annual_totals(frame, target):
    """The selection's total of the target in each year, with how many units reported it."""
    data = pd.DataFrame({"year": frame["year"], "value": frame[target], "unit_key": frame["unit_key"]})
    data = data[data["year"].notna() & data["value"].notna()]
    if len(data) == 0:
        return []
    grouped = data.groupby("year")
    table = pd.DataFrame({"total": grouped["value"].sum(), "units": grouped["unit_key"].nunique(),
                          "records": grouped.size()}).reset_index()
    return [{"year": int(row.year), "total": float(row.total), "units": int(row.units),
             "records": int(row.records)} for row in table.itertuples()]


def trend_model(kind):
    from sklearn.dummy import DummyRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.tree import DecisionTreeRegressor
    if kind == "mean":
        return DummyRegressor(strategy="mean")
    if kind == "linear":
        return LinearRegression()
    return DecisionTreeRegressor(max_depth=TREND_TREE_DEPTH, random_state=RANDOM_STATE)


def train_prediction_models(totals):
    """
    Year-trend models for annual totals: fit on the training years and score on the validation
    years, then refit on training + validation and score on the test year.
    """
    years = [row["year"] for row in totals]
    split = split_years(years)
    if split is None:
        return {"error": f"The trend needs at least three reporting years; this selection has {len(years)}."}
    by_year = {row["year"]: row["total"] for row in totals}

    def arrays(selected):
        return np.array(selected, dtype="float64").reshape(-1, 1), np.array([by_year[y] for y in selected])

    x_train, y_train = arrays(split["train"])
    x_validation, y_validation = arrays(split["validation"])
    x_fit, y_fit = arrays(split["train"] + split["validation"])
    x_test, y_test = arrays(split["test"])

    validation, test, test_predictions = {}, {}, {}
    for kind in MODELS:
        model = trend_model(kind).fit(x_train, y_train)
        validation[kind] = scores(y_validation, np.clip(model.predict(x_validation), 0, None))
        model = trend_model(kind).fit(x_fit, y_fit)
        predicted = np.clip(model.predict(x_test), 0, None)
        test_predictions[kind] = float(predicted[0])
        test[kind] = scores(y_test, predicted)
    chosen = min(CANDIDATES, key=lambda kind: (validation[kind]["mae"], CANDIDATES.index(kind)))
    return {"split": split, "validation": validation, "test": test, "test_predictions": test_predictions,
            "chosen": chosen}


def generate_forecast(totals, horizon=FORECAST_YEARS):
    """Refit each model on every year and extend it `horizon` years past the last one."""
    years = np.array([row["year"] for row in totals], dtype="float64").reshape(-1, 1)
    values = np.array([row["total"] for row in totals], dtype="float64")
    last = int(years.max())
    future = np.arange(last + 1, last + horizon + 1, dtype="float64").reshape(-1, 1)
    rows = [{"year": int(year)} for year in future[:, 0]]
    fitted = {}
    for kind in MODELS:
        model = trend_model(kind).fit(years, values)
        fitted[kind] = np.clip(model.predict(years), 0, None).tolist()
        for row, value in zip(rows, np.clip(model.predict(future), 0, None)):
            row[kind] = float(value)
    return {"rows": rows, "fitted": fitted}


def coverage_note(totals):
    """A warning when the number of reporting units changes a lot between years."""
    units = [row["units"] for row in totals]
    if len(units) < 2 or min(units) == 0:
        return None
    if max(units) / min(units) >= 1.5:
        return (f"The selection has between {min(units):,} and {max(units):,} units a year, so the totals partly "
                f"reflect which units were loaded or operating, not only how much each one emitted.")
    return None


def trend(frame, target):
    """Everything the year-trend section shows: totals, scores and the forecast."""
    totals = get_annual_totals(frame, target)
    result = train_prediction_models(totals)
    if "error" in result:
        return dict(result, totals=totals)
    result.update(totals=totals, forecast=generate_forecast(totals), coverage=coverage_note(totals))
    return result
