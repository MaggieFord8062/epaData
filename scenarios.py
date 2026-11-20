"""
Phase 2 sensitivity and scenario analysis (proposal section 6).

Both work on a fitted unit model from prediction.py and one baseline record: a generating
unit's inputs in the most recent (test) year of the selection.

One variable at a time (6.2)
    Change one input (gross load, heat input or operating time) across a range while every
    other input stays at its baseline value, and report the input value, the prediction, and
    the absolute and percentage change from the baseline prediction.

Scenarios (6.3)
    Named changes to the baseline (gross load +10%, heat input −5%, a different fuel, a pollution
    control added or removed, a combined high-efficiency case, and the user's own scenario),
    each compared with the baseline.

    % change = (scenario prediction − baseline prediction) ÷ baseline prediction × 100
    (undefined, shown as a dash, when the baseline prediction is 0).

Every value outside what the model saw in training is flagged, because a model is only
checked inside its training data. Results describe how the model responds; they are not
evidence that the change would cause that effect in the real world.
"""

import math

import pandas as pd

import analysis
import prediction

MAX_POINTS = 201
DEFAULT_SWEEP = {"mode": "pct", "low": -50.0, "high": 50.0, "step": 10.0}

INTERPRETATION = ("These are model-response results: they show how the fitted model's prediction moves when an "
                  "input changes. They are not evidence that the change would cause the same effect at a real "
                  "plant, where inputs move together (more load usually means more heat input and hours).")

FUELS = ["Coal", "Gas", "Oil and other"]
SWITCH_TO = {"Coal": "Gas", "Gas": "Coal", "Oil and other": "Gas"}


# ---------- The baseline ----------

def unit_choices(result):
    """Units the baseline can be: every unit in the test year, as (unit key, label), A to Z."""
    tested = result["tested"]
    pairs = sorted({(int(key), label) for key, label in zip(tested["unit_key"], tested["label"])},
                   key=lambda item: item[1].lower())
    return pairs


def default_unit(result):
    """
    A large unit to start from: the test-year record at the 90th percentile of the target among
    units that operated (gross load above 0), so the pollutant matters at the baseline.
    """
    tested = result["tested"]
    running = tested[tested["gross_load"] > 0]
    pool = running if len(running) else tested
    ordered = pool.sort_values(["actual", "unit_key"]).reset_index(drop=True)
    position = int(round(0.9 * (len(ordered) - 1)))
    return int(ordered.loc[position, "unit_key"])


def baseline_record(result, unit_key):
    """The chosen unit's test-year inputs as a dict, or None when the unit isn't in the test year."""
    tested = result["tested"]
    match = tested[tested["unit_key"] == unit_key]
    if len(match) == 0:
        return None
    row = match.iloc[0]
    record = {name: row[name] for name in prediction.FEATURES}
    for name in prediction.NUMERIC_INPUTS:
        record[name] = float(record[name])
    for name in prediction.FLAG_INPUTS:
        record[name] = int(record[name])
    record["fuel_family"] = str(record["fuel_family"])
    record["unit_type"] = str(record["unit_type"])
    return {
        "unit_key": int(row["unit_key"]),
        "label": row["label"],
        "year": int(row["year"]),
        "facility_id": None if pd.isna(row["facility_id"]) else int(row["facility_id"]),
        "primary_fuel": row["primary_fuel"],
        "actual": float(row["actual"]),
        "inputs": record,
    }


def predict_inputs(pipeline, inputs_list):
    """Predictions for a list of input dicts."""
    rows = pd.DataFrame([{name: inputs[name] for name in prediction.FEATURES} for inputs in inputs_list])
    return prediction.predict(pipeline, rows)


def hours_in(year):
    return 8784.0 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 8760.0


# ---------- Out-of-range warnings ----------

def warnings_for(inputs, ranges, year):
    """Plain-language warnings for every input outside the training data."""
    found = []
    for name, info in prediction.NUMERIC_INPUTS.items():
        low, high = ranges["numeric"][name]["min"], ranges["numeric"][name]["max"]
        value = inputs[name]
        if value < low or value > high:
            found.append(f"{info['label']} {analysis.format_number(value)} {info['unit']} is outside the training "
                         f"range ({analysis.format_number(low)} to {analysis.format_number(high)}).")
    if inputs["operating_time"] > hours_in(year):
        found.append(f"Operating time is more than the {int(hours_in(year)):,} hours in {year}.")
    for name, info in prediction.CATEGORY_INPUTS.items():
        if str(inputs[name]) not in ranges["categories"][name]:
            found.append(f"{info['label']} \"{inputs[name]}\" never appears in the training data.")
    pair = f"{inputs['fuel_family']}|{inputs['unit_type']}"
    known_fuel = str(inputs["fuel_family"]) in ranges["categories"]["fuel_family"]
    if known_fuel and pair not in ranges["fuel_unit_types"]:
        found.append(f"No {inputs['fuel_family'].lower()} {inputs['unit_type'].lower()} units are in the training "
                     f"data, so this combination is an extrapolation.")
    for name, info in prediction.FLAG_INPUTS.items():
        if known_fuel and inputs[name] == 1 and f"{inputs['fuel_family']}|{name}" not in ranges.get("fuel_controls", []):
            found.append(f"No {inputs['fuel_family'].lower()} units with an {info['label']} are in the training "
                         f"data, so the model has nothing to learn that control's effect from.")
    return found


def outside(name, value, ranges):
    return value < ranges["numeric"][name]["min"] or value > ranges["numeric"][name]["max"]


# ---------- One variable at a time ----------

def number(text, default):
    try:
        value = float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return default, False
    if math.isnan(value) or math.isinf(value):
        return default, False
    return value, True


def read_sweep(params, baseline_value, ranges, variable):
    """
    The values to try, from the page's choices. mode=pct: percent changes from the baseline
    (low, high, step in %); mode=value: values in the input's own unit. Returns
    (settings, values, problems) where problems are messages for the form.
    """
    mode = params.get("mode") if params.get("mode") in ("pct", "value") else "pct"
    problems = []
    if mode == "pct":
        defaults = (DEFAULT_SWEEP["low"], DEFAULT_SWEEP["high"], DEFAULT_SWEEP["step"])
    else:
        span = ranges["numeric"][variable]
        width = span["max"] - span["min"]
        defaults = (span["min"], span["max"], width / 20 if width > 0 else max(baseline_value, 1.0) / 10)

    values = {}
    for name, default in zip(("low", "high", "step"), defaults):
        raw = params.get(name)
        if raw in (None, ""):
            values[name] = default
            continue
        value, ok = number(raw, default)
        if not ok:
            problems.append(f"\"{raw}\" isn't a number, so the default was used for the {name} value.")
        values[name] = value
    low, high, step = values["low"], values["high"], values["step"]

    if step <= 0:
        problems.append("The step has to be more than 0, so the default step was used.")
        step = defaults[2]
    if high <= low:
        problems.append("The end of the range has to be above the start, so the default range was used.")
        low, high, step = defaults
    if mode == "pct" and low < -100:
        problems.append("A change below −100% would make the input negative, so the range starts at −100%.")
        low = -100.0
    if mode == "value" and low < 0:
        problems.append("Inputs can't be negative, so the range starts at 0.")
        low = 0.0
    if (high - low) / step + 1 > MAX_POINTS:
        problems.append(f"That would be more than {MAX_POINTS} points, so the step was widened.")
        step = (high - low) / (MAX_POINTS - 1)

    count = int(math.floor((high - low) / step + 1e-9)) + 1
    steps = [low + index * step for index in range(count)]
    if mode == "pct":
        points = [(baseline_value * (1 + pct / 100), pct) for pct in steps]
        points.append((baseline_value, 0.0))
    else:
        points = [(value, (value - baseline_value) / baseline_value * 100 if baseline_value > 0 else None)
                  for value in steps]
        points.append((baseline_value, 0.0))
    unique = {}
    for value, pct in points:
        unique.setdefault(round(value, 9), (value, pct))
    points = sorted(unique.values(), key=lambda item: item[0])
    settings = {"mode": mode, "low": low, "high": high, "step": step}
    return settings, points, problems


def change(value, base):
    """(absolute change, % change) of value from base; % change is None when base is 0."""
    difference = value - base
    return difference, (difference / base * 100 if base > 0 else None)


def one_at_a_time(pipeline, ranges, baseline, variable, points):
    """
    Predictions with one input changed and every other input held at its baseline value.
    Each row: input value, % change of the input, prediction, absolute and % change of the
    prediction from the baseline prediction, and whether the input is outside the training range.
    """
    base_inputs = baseline["inputs"]
    base_prediction = float(predict_inputs(pipeline, [base_inputs])[0])
    trials = []
    for value, _ in points:
        inputs = dict(base_inputs)
        inputs[variable] = value
        trials.append(inputs)
    predicted = predict_inputs(pipeline, trials)
    rows = []
    for (value, input_pct), result in zip(points, predicted):
        absolute, percent = change(float(result), base_prediction)
        rows.append({
            "value": float(value),
            "input_change_pct": input_pct,
            "prediction": float(result),
            "change": absolute,
            "change_pct": percent,
            "outside": outside(variable, value, ranges),
            "is_baseline": abs(value - base_inputs[variable]) < 1e-9,
        })
    return base_prediction, rows


# ---------- Scenarios ----------

def control_name(control):
    return prediction.FLAG_INPUTS[control]["label"]


def preset_scenarios(baseline, target):
    """The named scenarios for this baseline: (key, name, what changes, changed inputs)."""
    inputs = baseline["inputs"]
    year = baseline["year"]
    hours = hours_in(year)
    fuel = inputs["fuel_family"] if inputs["fuel_family"] in SWITCH_TO else "Oil and other"
    new_fuel = SWITCH_TO[fuel]
    control = prediction.TARGETS[target]["control"]
    has = inputs[control] == 1
    more_time = min(inputs["operating_time"] * 1.1, hours)
    return [
        ("baseline", "Baseline", f"The unit's actual {year} inputs.", {}),
        ("load_up", "Gross load +10%",
         "Only gross load changes. Heat input and operating time stay at the baseline.",
         {"gross_load": inputs["gross_load"] * 1.1}),
        ("heat_down", "Heat input −5%",
         "The same electricity from 5% less fuel (a 5% better heat rate).",
         {"heat_input": inputs["heat_input"] * 0.95}),
        ("runs_more", "Runs 10% more",
         "Gross load, heat input and operating time all rise 10%, so efficiency stays the same"
         + (f" (operating time capped at the {int(hours):,} hours in {year})." if more_time < inputs["operating_time"] * 1.1 else "."),
         {"gross_load": inputs["gross_load"] * 1.1, "heat_input": inputs["heat_input"] * 1.1,
          "operating_time": more_time}),
        ("fuel", f"Fuel changed to {new_fuel.lower() if new_fuel != 'Oil and other' else 'oil and other'}",
         f"The fuel family changes from {fuel.lower()} to {new_fuel.lower()}; everything else stays the same.",
         {"fuel_family": new_fuel}),
        ("control", f"{control_name(control)} {'removed' if has else 'added'}",
         f"The unit {'no longer reports' if has else 'reports'} an {control_name(control)}; "
         f"everything else stays the same.",
         {control: 0 if has else 1}),
        ("efficient", "High efficiency (combined)",
         "Gross load +10% and heat input −5% together: more electricity from less fuel.",
         {"gross_load": inputs["gross_load"] * 1.1, "heat_input": inputs["heat_input"] * 0.95}),
    ]


def read_custom(params):
    """The user's own scenario from the form (c_load, c_heat, c_time in %; c_fuel; c_so2, c_nox 0/1)."""
    changes, problems, described = {}, [], []
    for key, name in (("c_load", "gross_load"), ("c_heat", "heat_input"), ("c_time", "operating_time")):
        raw = params.get(key)
        if raw in (None, ""):
            continue
        value, ok = number(raw, 0.0)
        if not ok:
            problems.append(f"\"{raw}\" isn't a number, so {prediction.NUMERIC_INPUTS[name]['label'].lower()} "
                            f"was left unchanged in your scenario.")
            continue
        if value < -100:
            problems.append(f"{prediction.NUMERIC_INPUTS[name]['label']} can't fall more than 100%, so −100% was used.")
            value = -100.0
        if value != 0:
            changes[name] = ("pct", value)
            described.append(f"{prediction.NUMERIC_INPUTS[name]['label']} {value:+g}%")
    if params.get("c_fuel") in FUELS:
        changes["fuel_family"] = ("set", params["c_fuel"])
        described.append(f"fuel {params['c_fuel'].lower()}")
    for key, name in (("c_so2", "so2_control"), ("c_nox", "nox_control")):
        if params.get(key) in ("0", "1"):
            changes[name] = ("set", int(params[key]))
            described.append(f"{control_name(name)} {'on' if params[key] == '1' else 'off'}")
    return changes, problems, described


def apply_custom(inputs, changes):
    changed = {}
    for name, (how, value) in changes.items():
        changed[name] = inputs[name] * (1 + value / 100) if how == "pct" else value
    return changed


def run_scenarios(pipeline, ranges, baseline, target, custom=None):
    """Every scenario's prediction compared with the baseline."""
    items = preset_scenarios(baseline, target)
    if custom and custom[0]:
        changes, _, described = custom
        items.append(("custom", "Your scenario", ", ".join(described).capitalize() + ".",
                      apply_custom(baseline["inputs"], changes)))
    trials = []
    for _, _, _, changed in items:
        inputs = dict(baseline["inputs"])
        inputs.update(changed)
        trials.append(inputs)
    predicted = predict_inputs(pipeline, trials)
    base_prediction = float(predicted[0])
    rows = []
    for (key, name, about, changed), inputs, value in zip(items, trials, predicted):
        absolute, percent = change(float(value), base_prediction)
        rows.append({
            "key": key, "name": name, "about": about, "inputs": inputs,
            "changed": [prediction.INPUT_LABELS[name_] for name_ in changed],
            "prediction": float(value), "change": absolute, "change_pct": percent,
            "warnings": warnings_for(inputs, ranges, baseline["year"]),
        })
    return base_prediction, rows


def input_text(name, value):
    """An input value for tables: numbers with units, controls as Yes/No."""
    if name in prediction.NUMERIC_INPUTS:
        return analysis.format_number(value) + " " + prediction.NUMERIC_INPUTS[name]["unit"]
    if name in prediction.FLAG_INPUTS:
        return "Yes" if int(value) == 1 else "No"
    return str(value)


def chosen_model(result, requested):
    """The fitted model to analyze: the one asked for, or the model chosen on the validation years."""
    kind = requested if requested in prediction.CANDIDATES else result["chosen"]
    return kind, result["pipelines"][kind]


def baseline_check(pipeline, baseline):
    """The baseline prediction next to the unit's actual value, so the starting point can be judged."""
    value = float(predict_inputs(pipeline, [baseline["inputs"]])[0])
    absolute, percent = change(value, baseline["actual"])
    return {"prediction": value, "actual": baseline["actual"], "error": absolute, "error_pct": percent}

