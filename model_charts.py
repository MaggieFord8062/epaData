"""
Charts for the Predictions page (proposal 5) and the Scenarios page (proposal 6).

Built the same way as the dashboard charts (dashboard.py): a Plotly figure plus the table of
numbers behind it, drawn in the browser by static/charts.js, with PNG and data downloads, and
the same card above each chart (eyebrow, headline number, legend).

  model_errors       each model's test-year error (mean absolute error), baseline in gray
  predicted_actual   predicted against actual emissions for every test-year record
  trend_forecast     the selection's annual totals with each year-trend model and its forecast
  sensitivity        the prediction as one input changes (baseline point, reference lines,
                     out-of-training-range region shaded and its points drawn open)
  scenarios          each named scenario's prediction compared with the baseline
"""

import analysis
import explain
import prediction
from dashboard import (FAMILY_COLORS, INK, INK_2, OTHER, SERIES, SURFACE, bar_rows, chart, clean,
                       delta, empty_chart, end_dot, gradient, headline, layout, legend_item, percent_change,
                       short_number, text, time_axes, value_labels)

# Status color for "outside the training range"; always paired with a label and an open marker
WARNING_FILL = "rgba(250, 178, 25, 0.16)"
WARNING_LINE = "#b25000"
REFERENCE = "#86868b"
SCATTER_LIMIT = 4000


def tons(value):
    return analysis.format_number(value) + " short tons"


def signed(value, suffix=""):
    if value is None:
        return "—"
    if abs(value) < 5e-10:
        return "0" + suffix
    return ("+" if value > 0 else "−") + analysis.format_number(abs(value)) + suffix


def percent(value):
    if value is None:
        return "—"
    if abs(value) < 0.05:
        return "0%"
    return ("+" if value > 0 else "−") + f"{abs(value):,.1f}%"


def big_number(value, unit, context="", note="", eyebrow=""):
    """A headline whose number is already written out (a percentage or a score)."""
    return {"value": value, "unit": unit, "context": context, "delta": None, "note": note, "eyebrow": eyebrow}


# ---------- Predictions page ----------

def model_errors(result):
    """Test-year mean absolute error of each model; the baseline in gray, the chosen model labeled."""
    target = prediction.TARGETS[result["target"]]["label"]
    year = prediction.period(result["split"]["test"])
    title = f"Average miss in {year} by model ({target})"
    kinds = list(prediction.MODELS)
    names = [prediction.MODELS[kind]["name"] + (" (chosen)" if kind == result["chosen"] else "") for kind in kinds]
    values = [clean(result["test"][kind]["mae"]) for kind in kinds]
    colors = [OTHER if kind == "mean" else SERIES[0] for kind in kinds]
    data = [dict({
        "type": "bar", "orientation": "h", "x": values, "y": names,
        "marker": {"color": colors},
        "customdata": [[result["validation"][kind]["mae"], result["test"][kind]["r2"]] for kind in kinds],
        "hovertemplate": "<b>%{y}</b><br>Test MAE %{x:,.4~r} short tons<br>Validation MAE %{customdata[0]:,.4~r}"
                         "<extra></extra>",
    }, **value_labels(values))]
    figure = layout(title)
    bar_rows(figure, names, values)
    columns = ["Model", "Validation MAE", "Test MAE", "Test RMSE", "Test R²", "Test weighted % error"]
    rows = [[prediction.MODELS[kind]["name"], clean(result["validation"][kind]["mae"]),
             clean(result["test"][kind]["mae"]), clean(result["test"][kind]["rmse"]),
             clean(result["test"][kind]["r2"]), clean(result["test"][kind]["wape"])] for kind in kinds]
    note = ("Shorter is better; the gray bar is the baseline that always predicts the training average. Each model "
            "was refit on the training and validation years and scored once on the test year; the chosen model had "
            "the lowest error on the validation years.")
    spec = chart("model_errors", title, data, figure, columns, rows, note)
    details = {}
    for point, kind in enumerate(kinds):
        test = result["test"][kind]
        name = prediction.MODELS[kind]["name"]
        records = test.get("n") or result["counts"]["test"]
        details[f"0:{point}"] = {
            "kicker": f"Test year {year} · {target}", "title": names[point],
            "value": explain.number(test["mae"]), "unit": "short tons, average miss",
            "summary": (f"On average, the {name.lower()}'s prediction for a {year} record was "
                        f"{explain.number(test['mae'])} short tons away from what the unit actually reported."),
            "calc": [{"op": "Σ", "label": f"|predicted − actual| over {records:,} test-year records", "value": ""},
                     {"op": "÷", "label": "Records", "value": f"{records:,}"},
                     {"op": "=", "label": "Mean absolute error", "value": explain.with_unit(test["mae"], "short tons"),
                      "result": True}],
            "facts": [["Validation MAE", explain.with_unit(result["validation"][kind]["mae"], "short tons")],
                      ["Test RMSE", explain.with_unit(test["rmse"], "short tons")],
                      ["Test R²", "—" if test["r2"] is None else f"{test['r2']:.3f}".replace("-", "−")],
                      ["Weighted % error", "—" if test["wape"] is None else f"{test['wape']:.1f}%"],
                      ["Mean error (bias)", explain.with_unit(test["bias"], "short tons")]],
            "note": ("The baseline ignores every input and always predicts the training years' average; a useful "
                     "model has to beat it." if kind == "mean" else
                     "Chosen because it had the lowest error on the validation years, before the test year was "
                     "scored." if kind == result["chosen"] else ""),
            "drill": {},
        }
    spec["details"] = details
    spec["about"] = explain.about(
        f"How far each model's predictions were from the actual {target} of the {year} records it never saw.",
        "Each model is fitted on the training years, compared on the validation years, then refitted on both and "
        "scored once on the test year. Mean absolute error is the average of |predicted − actual| over the "
        "test-year records, in short tons.",
        "Bars make it easy to see how much smaller the models' errors are than the baseline's; a model is only "
        "useful if its bar is clearly shorter than the gray one.",
        "Shorter is better. Select a bar for every score of that model.",
        f"{explain.SOURCE}. Test year {year}: {result['counts']['test']:,} unit records.")
    chosen = result["chosen"]
    baseline = result["test"]["mean"]["mae"]
    mae = result["test"][chosen]["mae"]
    spec["headline"] = headline(mae, "short tons", f"average miss per record, {prediction.MODELS[chosen]['name'].lower()}",
                                eyebrow=f"Chosen model, {year}")
    if baseline and mae is not None:
        spec["headline"]["note"] = f"{abs(1 - mae / baseline) * 100:.0f}% {'smaller' if mae <= baseline else 'larger'} " \
                                   f"than the baseline's {short_number(baseline)}"
    return spec


def predicted_actual(result):
    """Every test-year record: actual emissions across, the chosen model's prediction up, log scales."""
    target = prediction.TARGETS[result["target"]]["label"]
    chosen = result["chosen"]
    year = prediction.period(result["split"]["test"])
    title = f"Predicted vs. actual {target}, {year} ({prediction.MODELS[chosen]['name'].lower()})"
    tested = result["tested"]
    column = "predicted_" + chosen
    shown = tested[(tested["actual"] > 0) & (tested[column] > 0)]
    hidden = len(tested) - len(shown)
    if len(shown) == 0:
        return empty_chart("predicted_actual", title, "No test-year record has emissions above 0 to plot.")
    sampled = shown
    if len(shown) > SCATTER_LIMIT:
        sampled = shown.sample(SCATTER_LIMIT, random_state=prediction.RANDOM_STATE)
    data, legend = [], []
    for family in analysis.FUEL_FAMILIES + [analysis.NOT_REPORTED]:
        part = sampled[sampled["fuel_family"] == family]
        if len(part) == 0:
            continue
        error_pct = (part[column] - part["actual"]) / part["actual"] * 100
        color = FAMILY_COLORS.get(family, OTHER)
        data.append({
            "type": "scattergl", "mode": "markers", "name": family, "legendgroup": family,
            "x": part["actual"].tolist(), "y": part[column].tolist(),
            "customdata": [[text(label), pct, load, heat, hours, unit_type]
                           for label, pct, load, heat, hours, unit_type in zip(
                               part["label"], error_pct, part["gross_load"], part["heat_input"],
                               part["operating_time"], part["unit_type"].fillna("Not reported"))],
            "marker": {"color": color, "size": 7, "opacity": 0.72, "line": {"color": SURFACE, "width": 0.5}},
            "hovertemplate": "<b>%{customdata[0]}</b><br>Actual  %{x:,.4~r} short tons<br>"
                             "Predicted  %{y:,.4~r} short tons<br>Miss  %{customdata[1]:+.1f}%<extra>" + family
                             + "</extra>",
        })
        legend.append(legend_item(family, color, f"{int((shown['fuel_family'] == family).sum()):,} records", "dot"))
    low = float(min(shown["actual"].min(), shown[column].min()))
    high = float(max(shown["actual"].max(), shown[column].max()))
    data.append({
        "type": "scatter", "mode": "lines", "name": "Perfect prediction", "legendgroup": "Perfect prediction",
        "x": [low, high], "y": [low, high], "line": {"color": REFERENCE, "width": 1.5, "dash": "dash"},
        "hoverinfo": "skip",
    })
    legend.append(legend_item("Perfect prediction", REFERENCE, style="dash"))
    figure = layout(title, f"Actual {target} (short tons, log scale)", f"Predicted {target} (short tons, log scale)",
                    height=420)
    for name in ("xaxis", "yaxis"):
        figure[name]["type"] = "log"
        figure[name]["dtick"] = 1
    figure["xaxis"]["showline"] = True
    columns = ["Unit", "Fuel", "Actual (short tons)", "Predicted (short tons)", "Miss (short tons)", "Miss (%)"]
    ordered = tested.reindex(tested["error"].abs().sort_values(ascending=False).index)
    rows = [[row.label, row.fuel_family, clean(row.actual), clean(getattr(row, column)), clean(row.error),
             clean(row.error / row.actual * 100) if row.actual > 0 else None] for row in ordered.itertuples()]
    note = ("Points on the dashed line were predicted exactly; above it the model predicted too much, below it too "
            "little. Both axes are logarithmic because units range from a few tons to millions.")
    if hidden:
        note += f" {hidden:,} records with zero actual or predicted emissions can't be shown on a log scale."
    if len(shown) > SCATTER_LIMIT:
        note += f" A random sample of {SCATTER_LIMIT:,} of {len(shown):,} records is drawn; the table has all of them."
    spec = chart("predicted_actual", title, data, figure, columns, rows, note)
    spec["legend"] = legend
    spec["detail_template"] = {"kind": "prediction", "target": target, "year": year,
                               "model": prediction.MODELS[chosen]["name"]}
    spec["about"] = explain.about(
        f"Every {year} record: the {target} the unit actually reported (across) and what the "
        f"{prediction.MODELS[chosen]['name'].lower()} predicted from its inputs (up).",
        "The model was trained on earlier years only. For each test-year record it takes the unit's gross load, "
        "heat input, operating time, fuel family, unit type and control flags, and predicts the year's emissions; "
        "the miss is predicted − actual.",
        "Plotting predicted against actual shows every miss at once, including which kinds of units the model gets "
        "wrong; one summary score can't show that. Log scales because units range from a few tons to millions.",
        "Points on the dashed line are perfect predictions; above it the model predicted too much, below it too "
        "little. Select a point for that record's inputs and miss.",
        f"{explain.SOURCE}. Test year {year}: {len(tested):,} unit records.")
    r2 = result["test"][chosen]["r2"]
    if r2 is not None:
        spec["headline"] = big_number(f"{r2:.2f}".replace("-", "−"), "R²",
                                      f"of the record-to-record variation in {year} is explained" if r2 > 0 else
                                      f"the model does worse than the test year's own average in {year}",
                                      f"{len(tested):,} test-year records", "How close")
    return spec


def trend_forecast(trend, target):
    """Annual totals, the three year-trend models fitted to every year, and their forecasts."""
    label = prediction.TARGETS[target]["label"]
    title = f"Annual {label} total and year-trend forecast"
    totals = trend["totals"]
    years = [row["year"] for row in totals]
    future = [row["year"] for row in trend["forecast"]["rows"]]
    actual = [row["total"] for row in totals]
    data = [{
        "type": "scatter", "mode": "lines", "name": "Actual total", "legendgroup": "Actual total",
        "x": years, "y": actual, "line": {"color": SERIES[0], "width": 3},
        "fill": "tozeroy", "fillgradient": gradient(SERIES[0], 0.18),
        "customdata": [row["units"] for row in totals],
        "hovertemplate": "Actual  <b>%{y:,.4~r} short tons</b>  (%{customdata:,} units)<extra></extra>",
    }]
    styles = {"linear": (SERIES[1], "dash"), "tree": (SERIES[2], "dash"), "mean": (REFERENCE, "dot")}
    legend = [legend_item("Actual total", SERIES[0], f"{short_number(actual[-1])} in {years[-1]}")]
    dots = [end_dot(years[-1], actual[-1], SERIES[0], "Actual total")]
    for kind in ("linear", "tree", "mean"):
        color, dash = styles[kind]
        name = prediction.MODELS[kind]["name"]
        values = trend["forecast"]["fitted"][kind] + [row[kind] for row in trend["forecast"]["rows"]]
        data.append({
            "type": "scatter", "mode": "lines", "name": name, "legendgroup": name,
            "x": years + future, "y": values,
            "line": {"color": color, "width": 2, "dash": dash, "shape": "hv" if kind == "tree" else "linear"},
            "hovertemplate": name + "  %{y:,.4~r} short tons<extra></extra>",
        })
        if future:
            legend.append(legend_item(name, color, f"{short_number(values[-1])} in {future[-1]}", "dash"))
    figure = layout(title, "", "", height=380)
    time_axes(figure, years + future)
    split = trend["split"]
    bands = [("Validation", split["validation"]), ("Test", split["test"]), ("Forecast", future)]
    figure["shapes"], figure["annotations"] = [], []
    for name, band in bands:
        if not band:
            continue
        figure["shapes"].append({
            "type": "rect", "xref": "x", "yref": "paper", "x0": band[0] - 0.5, "x1": band[-1] + 0.5, "y0": 0, "y1": 1,
            "fillcolor": "rgba(0,0,0,0.035)" if name != "Forecast" else "rgba(0,113,227,0.06)", "line": {"width": 0},
            "layer": "below",
        })
        # Validation and test sit side by side, so their labels meet at the boundary instead of overlapping
        if name == "Validation":
            x, anchor = band[-1] + 0.5, "right"
        elif name == "Test":
            x, anchor = band[0] - 0.5, "left"
        else:
            x, anchor = (band[0] + band[-1]) / 2, "center"
        figure["annotations"].append({
            "x": x, "y": 1, "xref": "x", "yref": "paper", "yanchor": "bottom", "xanchor": anchor,
            "text": name, "showarrow": False, "font": {"size": 11, "color": INK_2},
        })
    figure["margin"]["t"] = 30
    columns = ["Year", "Actual total (short tons)", "Units reporting", "Mean baseline", "Linear regression",
               "Decision tree"]
    fitted = trend["forecast"]["fitted"]
    rows = [[row["year"], clean(row["total"]), row["units"], clean(fitted["mean"][index]),
             clean(fitted["linear"][index]), clean(fitted["tree"][index])] for index, row in enumerate(totals)]
    rows += [[row["year"], None, None, clean(row["mean"]), clean(row["linear"]), clean(row["tree"])]
             for row in trend["forecast"]["rows"]]
    note = ("Model lines are fitted to every year and extended past the last one. A decision tree can't extend a "
            "trend, so its forecast stays flat; a straight line keeps the past trend going. The gray bands are the "
            "validation and test years, the blue band the forecast.")
    spec = chart("trend_forecast", title, data + dots, figure, columns, rows, note)
    spec["legend"] = legend
    role = {}
    for name, band in (("training", split["train"]), ("validation", split["validation"]), ("test", split["test"])):
        for item in band:
            role[item] = name
    details = {}
    for point, row in enumerate(totals):
        details[f"0:{point}"] = {
            "kicker": f"Total {label} · actual", "title": str(row["year"]),
            "value": explain.big(row["total"], "short tons")[0], "unit": explain.big(row["total"], "short tons")[1],
            "summary": f"The {label} of every unit in the selection that reported in {row['year']}, added up.",
            "calc": [{"op": "Σ", "label": f"{label} of {row['units']:,} units", "value": ""},
                     {"op": "=", "label": f"Total {label}", "value": explain.with_unit(row["total"], "short tons"),
                      "result": True}],
            "facts": [["Units reporting", f"{row['units']:,}"],
                      ["Used for", {"training": "Training the trend models", "validation": "Choosing a model",
                                    "test": "The final test"}.get(role.get(row["year"]), "—")]],
            "note": "Totals also change when units start or stop reporting.",
            "drill": {"reporting_year": int(row["year"])},
        }
    by_year = {row["year"]: row["total"] for row in totals}
    for offset, kind in enumerate(("linear", "tree", "mean"), start=1):
        name = prediction.MODELS[kind]["name"]
        values = trend["forecast"]["fitted"][kind] + [row[kind] for row in trend["forecast"]["rows"]]
        for point, (year_value, value) in enumerate(zip(years + future, values)):
            actual_value = by_year.get(year_value)
            facts = [["Actual total", explain.with_unit(actual_value, "short tons")]] if actual_value is not None else []
            if actual_value is not None:
                facts.append(["Difference", explain.signed_percent((value - actual_value) / actual_value * 100)
                              if actual_value else "—"])
            details[f"{offset}:{point}"] = {
                "kicker": name, "title": f"{year_value}{' forecast' if year_value in future else ''}",
                "value": explain.big(value, "short tons")[0], "unit": explain.big(value, "short tons")[1],
                "summary": ({"linear": "A straight line through every year's total, extended past the last year.",
                             "tree": "A shallow decision tree splits the years into periods and predicts each "
                                     "period's average; it can't extend a trend, so its forecast stays flat.",
                             "mean": "The average of every year's total, the same for every year."}[kind]),
                "calc": [{"op": "=", "label": f"{name} for {year_value}", "value": explain.with_unit(value, "short tons"),
                          "result": True}],
                "facts": facts,
                "note": ("A forecast assumes the past pattern continues; it can't know about new plants, closures or "
                         "rules." if year_value in future else ""),
                "drill": {},
            }
    spec["details"] = details
    spec["about"] = explain.about(
        f"The selection's total {label} for each year, three simple models of the trend, and where each would "
        "go next.",
        "Each year's total adds up every reporting unit. The models use only the year: a straight line (linear "
        "regression), a shallow decision tree, and the average of all years as a baseline. They are scored on the "
        "validation and test years (shaded), then refitted on every year for the forecast.",
        "A line chart shows the history and the forecasts on one time axis, so you can judge whether a model "
        "follows the pattern before trusting where it goes.",
        "Solid is what happened; dashed and dotted are models. The blue band is the future.",
        f"{explain.SOURCE}, totals of every unit in the selection.")
    chosen = trend.get("chosen")
    forecast_note = ""
    if chosen and future:
        forecast_note = (f"{prediction.MODELS[chosen]['name']} (chosen) forecast for {future[-1]}: "
                         f"{analysis.format_compact(trend['forecast']['rows'][-1][chosen])} short tons")
    spec["headline"] = headline(actual[-1], "short tons", f"In {years[-1]}",
                                delta(percent_change(actual[-1], actual[0]), f"since {years[0]}"), forecast_note,
                                eyebrow=f"Total {label}")
    return spec


# ---------- Scenarios page ----------

def sensitivity(rows, baseline, variable, target, kind, ranges, base_prediction):
    """The prediction as one input changes, everything else held at the baseline."""
    info = prediction.NUMERIC_INPUTS[variable]
    label = prediction.TARGETS[target]["label"]
    title = f"Predicted {label} as {info['label'].lower()} changes"
    inside = [row for row in rows if not row["outside"]]
    beyond = [row for row in rows if row["outside"]]

    def details(row):
        return [percent(row["input_change_pct"]), signed(row["change"], " short tons"), percent(row["change_pct"])]

    hover = ("<b>" + info["label"] + " %{x:,.4~r} " + info["unit"] + "</b> (%{customdata[0]})<br>"
             "Predicted %{y:,.4~r} short tons<br>Change %{customdata[1]} (%{customdata[2]})")
    data = [{
        "type": "scatter", "mode": "lines", "name": "Prediction", "showlegend": False,
        "x": [row["value"] for row in rows], "y": [row["prediction"] for row in rows],
        "line": {"color": SERIES[0], "width": 3, "shape": "hv" if kind == "tree" else "linear"},
        "fill": "tozeroy", "fillgradient": gradient(SERIES[0], 0.16), "hoverinfo": "skip",
    }, {
        "type": "scatter", "mode": "markers", "name": "Prediction", "legendgroup": "Prediction",
        "x": [row["value"] for row in inside], "y": [row["prediction"] for row in inside],
        "customdata": [details(row) for row in inside],
        "marker": {"color": SERIES[0], "size": 7, "line": {"color": SURFACE, "width": 1.5}},
        "hovertemplate": hover + "<extra></extra>",
    }]
    legend = [legend_item("Prediction", SERIES[0])]
    if beyond:
        data.append({
            "type": "scatter", "mode": "markers", "name": "Outside training range",
            "legendgroup": "Outside training range",
            "x": [row["value"] for row in beyond], "y": [row["prediction"] for row in beyond],
            "customdata": [details(row) for row in beyond],
            # Open symbols draw their outline in marker.color
            "marker": {"color": WARNING_LINE, "size": 10, "symbol": "circle-open", "line": {"width": 2}},
            "hovertemplate": hover + "<br>⚠ Outside the training range<extra></extra>",
        })
        legend.append(legend_item("Outside training range", WARNING_LINE, f"{len(beyond)} of {len(rows)} values",
                                  "ring"))
    base_x = baseline["inputs"][variable]
    data.append({
        "type": "scatter", "mode": "markers+text", "name": "Baseline", "legendgroup": "Baseline",
        "x": [base_x], "y": [base_prediction], "text": ["Baseline"], "textposition": "top left",
        "textfont": {"color": INK, "size": 12}, "cliponaxis": False,
        "marker": {"color": INK, "size": 12, "line": {"color": SURFACE, "width": 3}},
        "hovertemplate": ("<b>Baseline</b><br>" + info["label"] + " %{x:,.4~r} " + info["unit"]
                          + "<br>Predicted %{y:,.4~r} short tons<extra></extra>"),
    })
    legend.append(legend_item("Baseline", INK, "", "dot"))
    figure = layout(title, f"{info['label']} ({info['unit']})", "", height=400)
    figure["xaxis"].update(showline=True, showgrid=False)
    figure["yaxis"].update(side="right", rangemode="tozero")
    xs = [row["value"] for row in rows]
    low, high = min(xs), max(xs)
    pad = (high - low) * 0.03 or max(abs(high), 1) * 0.03
    figure["xaxis"]["range"] = [low - pad, high + pad]
    shapes = [
        {"type": "line", "xref": "x", "yref": "paper", "x0": base_x, "x1": base_x, "y0": 0, "y1": 1,
         "line": {"color": REFERENCE, "width": 1, "dash": "dash"}},
        {"type": "line", "xref": "paper", "yref": "y", "x0": 0, "x1": 1, "y0": base_prediction, "y1": base_prediction,
         "line": {"color": REFERENCE, "width": 1, "dash": "dash"}},
    ]
    annotations = []
    train_low, train_high = ranges["numeric"][variable]["min"], ranges["numeric"][variable]["max"]
    # Shade only the sides where some tried value is actually outside the training range
    regions = []
    if low < train_low:
        regions.append((low - pad, train_low, "right"))
    if high > train_high:
        regions.append((train_high, high + pad, "left"))
    for start, end, anchor in regions:
        shapes.append({"type": "rect", "xref": "x", "yref": "paper", "x0": start, "x1": end, "y0": 0, "y1": 1,
                       "fillcolor": WARNING_FILL, "line": {"width": 0}, "layer": "below"})
        annotations.append({"x": end if anchor == "right" else start, "y": 0.99, "xref": "x", "yref": "paper",
                            "yanchor": "top", "xanchor": anchor, "text": "⚠ Outside training range",
                            "showarrow": False, "font": {"size": 11, "color": WARNING_LINE},
                            "bgcolor": "rgba(255,255,255,0.7)"})
    figure["shapes"] = shapes
    figure["annotations"] = annotations
    columns = [f"{info['label']} ({info['unit']})", "Input change from baseline (%)",
               f"Predicted {label} (short tons)", "Change from baseline (short tons)", "Change from baseline (%)",
               "Outside training range"]
    table = [[clean(row["value"]), clean(row["input_change_pct"]), clean(row["prediction"]), clean(row["change"]),
              clean(row["change_pct"]), "Yes" if row["outside"] else "No"] for row in rows]
    note = (f"Only {info['label'].lower()} changes; every other input stays at the baseline unit's value. The dashed "
            f"lines cross at the baseline. Training range: {analysis.format_number(train_low)} to "
            f"{analysis.format_number(train_high)} {info['unit']}.")
    spec = chart("sensitivity", title, data, figure, columns, table, note)
    spec["legend"] = legend
    held = [fact for fact in explain.model_inputs(baseline["inputs"]) if fact[0] != info["label"]]

    def sweep_detail(row):
        return {
            "kicker": f"Only {info['label'].lower()} changes",
            "title": f"{info['label']} {explain.with_unit(row['value'], info['unit'])}",
            "value": explain.big(row["prediction"], "short tons")[0],
            "unit": "predicted " + explain.big(row["prediction"], "short tons")[1],
            "summary": (f"This is the baseline unit's own {info['label'].lower()}, so the prediction is the baseline "
                        "prediction." if row["input_change_pct"] is not None and abs(row["input_change_pct"]) < 0.05
                        else f"Setting {info['label'].lower()} {explain.signed_percent(row['input_change_pct'])} away "
                             f"from the baseline changes the predicted {label} by "
                             f"{explain.signed_percent(row['change_pct'])}, with every other input unchanged."),
            "calc": [{"op": "", "label": "Prediction at this value", "value": explain.with_unit(row["prediction"], "short tons")},
                     {"op": "−", "label": "Baseline prediction", "value": explain.with_unit(base_prediction, "short tons")},
                     {"op": "=", "label": "Change", "value": signed(row["change"], " short tons"), "result": True},
                     {"op": "÷", "label": "Baseline prediction", "value": explain.with_unit(base_prediction, "short tons")},
                     {"op": "=", "label": "Change in %", "value": percent(row["change_pct"]), "result": True}],
            "facts": [["Input change", percent(row["input_change_pct"])],
                      ["Inside the training range", "No ⚠" if row["outside"] else "Yes"]] + held,
            "note": ("⚠ This value is outside what the model saw in training, so the prediction is an extrapolation."
                     if row["outside"] else ""),
            "drill": {},
        }

    details = {f"1:{point}": sweep_detail(row) for point, row in enumerate(inside)}
    if beyond:
        details.update({f"2:{point}": sweep_detail(row) for point, row in enumerate(beyond)})
    details[f"{len(data) - 1}:0"] = {
        "kicker": "Baseline", "title": baseline.get("label", "Baseline unit"),
        "value": explain.big(base_prediction, "short tons")[0],
        "unit": "predicted " + explain.big(base_prediction, "short tons")[1],
        "summary": f"The model's prediction for the baseline unit's actual {baseline['year']} inputs.",
        "calc": [], "facts": explain.model_inputs(baseline["inputs"]), "note": "", "drill": {},
    }
    spec["details"] = details
    spec["about"] = explain.about(
        f"How the predicted {label} responds when only {info['label'].lower()} changes.",
        f"Starting from the baseline unit's actual inputs, {info['label'].lower()} is set to each value along the "
        "axis while every other input stays exactly at the baseline, and the fitted model predicts each time. "
        "Change = prediction − baseline prediction; % change = change ÷ baseline prediction × 100.",
        "A sensitivity curve shows the whole response, not just one what-if: where it is steep, flat, or (for a "
        "decision tree) jumps in steps.",
        "The dashed lines cross at the baseline. Open orange circles and the shaded side are outside the training "
        "range. This is how the model responds, not a promise of how a real plant would.",
        f"Model trained on {explain.SOURCE.split(',')[0]}; baseline: {baseline.get('label', 'the chosen unit')}, "
        f"{baseline['year']}.")
    predictions = [row["prediction"] for row in rows]
    spec["headline"] = headline(base_prediction, "short tons",
                                f"predicted at the baseline's {analysis.format_number(base_x)} {info['unit']}",
                                note=f"From {analysis.format_compact(min(predictions))} to "
                                     f"{analysis.format_compact(max(predictions))} short tons across the values tried",
                                eyebrow="Baseline prediction")
    return spec


def scenario_bars(rows, target, base_prediction):
    """Each scenario's prediction, baseline in gray, with the change from the baseline on every bar."""
    label = prediction.TARGETS[target]["label"]
    title = f"Predicted {label} by scenario"
    names = [row["name"] + (" ⚠" if row["warnings"] else "") for row in rows]
    values = [clean(row["prediction"]) for row in rows]
    colors = [OTHER if row["key"] == "baseline" else SERIES[0] for row in rows]
    patterns = ["/" if row["warnings"] else "" for row in rows]
    labels = []
    for row in rows:
        if row["key"] == "baseline":
            labels.append(short_number(row["prediction"]))
        else:
            labels.append(f"{short_number(row['prediction'])}  {percent(row['change_pct'])}")
    data = [{
        "type": "bar", "orientation": "h", "x": values, "y": names,
        "marker": {"color": colors, "pattern": {"shape": patterns, "fgcolor": SURFACE, "size": 7, "solidity": 0.25}},
        "text": labels, "textposition": "outside", "cliponaxis": False, "constraintext": "none",
        "textfont": {"color": INK, "size": 12},
        "customdata": [[row["about"], signed(row["change"], " short tons"), percent(row["change_pct"]),
                        "<br>⚠ " + "<br>⚠ ".join(row["warnings"]) if row["warnings"] else ""] for row in rows],
        "hovertemplate": ("<b>%{y}</b><br>%{customdata[0]}<br>Predicted %{x:,.4~r} short tons<br>"
                          "Change %{customdata[1]} (%{customdata[2]})%{customdata[3]}<extra></extra>"),
    }]
    figure = layout(title)
    bar_rows(figure, names, values)
    top = max([v for v in values if v is not None] or [1])
    figure["xaxis"]["range"] = [0, top * 1.4 if top > 0 else 1]   # room for the labels, even on a phone
    figure["shapes"] = [{"type": "line", "xref": "x", "yref": "paper", "x0": base_prediction, "x1": base_prediction,
                         "y0": 0, "y1": 1, "line": {"color": REFERENCE, "width": 1, "dash": "dash"}, "layer": "below"}]
    columns = ["Scenario", "What changes", f"Predicted {label} (short tons)", "Change from baseline (short tons)",
               "Change from baseline (%)", "Warnings"]
    table = [[row["name"], row["about"], clean(row["prediction"]), clean(row["change"]), clean(row["change_pct"]),
              " ".join(row["warnings"]) or "None"] for row in rows]
    note = ("The gray bar and the dashed line are the baseline prediction. Striped bars and ⚠ mark scenarios with an "
            "input outside what the model saw in training; treat them as extrapolations.")
    spec = chart("scenarios", title, data, figure, columns, table, note)
    details = {}
    for point, row in enumerate(rows):
        calc = [{"op": "", "label": "Scenario prediction", "value": explain.with_unit(row["prediction"], "short tons")},
                {"op": "−", "label": "Baseline prediction", "value": explain.with_unit(base_prediction, "short tons")},
                {"op": "=", "label": "Change", "value": signed(row["change"], " short tons"), "result": True},
                {"op": "÷", "label": "Baseline prediction", "value": explain.with_unit(base_prediction, "short tons")},
                {"op": "=", "label": "Change in %", "value": percent(row["change_pct"]), "result": True}]
        details[f"0:{point}"] = {
            "kicker": "Scenario" if row["key"] != "baseline" else "Baseline",
            "title": row["name"],
            "value": explain.big(row["prediction"], "short tons")[0],
            "unit": "predicted " + explain.big(row["prediction"], "short tons")[1],
            "summary": row["about"],
            "calc": calc if row["key"] != "baseline" else [],
            "facts": explain.model_inputs(row["inputs"]),
            "note": " ".join("⚠ " + warning for warning in row["warnings"]),
            "drill": {},
        }
    spec["details"] = details
    spec["about"] = explain.about(
        f"The predicted {label} for the baseline unit and for each named what-if.",
        "Each scenario copies the baseline unit's inputs, changes only the ones it names, and runs the same fitted "
        "model. Change = scenario − baseline; % change = change ÷ baseline × 100.",
        "Bars put every scenario beside the baseline, so the size and direction of each change is clear at a "
        "glance.",
        "The gray bar and dashed line are the baseline. Striped bars have an input outside the training range; "
        "treat them as extrapolations. Select a bar for its inputs.",
        f"{explain.SOURCE}; predictions from the model trained on this selection.")
    changed = [row for row in rows if row["key"] != "baseline" and row["change_pct"] is not None]
    if changed:
        biggest = max(changed, key=lambda row: abs(row["change_pct"]))
        spec["headline"] = big_number(percent(biggest["change_pct"]), "",
                                      f"{biggest['name']}: {analysis.format_compact(biggest['prediction'])} short tons, "
                                      f"against {analysis.format_compact(base_prediction)} at the baseline",
                                      "⚠ Outside the training range" if biggest["warnings"] else "",
                                      "Biggest change")
    return spec
