"""
Charts for the Predictions page (proposal 5) and the Scenarios page (proposal 6).

Built the same way as the dashboard charts (dashboard.py): a Plotly figure plus the table of
numbers behind it, drawn in the browser by static/charts.js, with PNG and data downloads.

  model_errors       each model's test-year error (mean absolute error), baseline in gray
  predicted_actual   predicted against actual emissions for every test-year record
  trend_forecast     the selection's annual totals with each year-trend model and its forecast
  sensitivity        the prediction as one input changes (baseline point, reference lines,
                     out-of-training-range region shaded and its points drawn open)
  scenarios          each named scenario's prediction compared with the baseline
"""

import analysis
import prediction
from dashboard import (FAMILY_COLORS, INK, INK_2, OTHER, SERIES, SURFACE, chart, clean, empty_chart, layout, text,
                       year_step)

# Status color for "outside the training range"; always paired with a label and an open marker
WARNING_FILL = "rgba(250, 178, 25, 0.16)"
WARNING_LINE = "#b25000"
REFERENCE = "#86868b"
SCATTER_LIMIT = 4000


def scale_for(values):
    """(divisor, unit words) so axis numbers stay short: tons, thousand tons or million tons."""
    largest = max([abs(value) for value in values if value is not None] or [0])
    if largest >= 1e8:
        return 1e6, "million short tons"
    if largest >= 1e5:
        return 1e3, "thousand short tons"
    return 1.0, "short tons"


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


# ---------- Predictions page ----------

def model_errors(result):
    """Test-year mean absolute error of each model; the baseline in gray, the chosen model labeled."""
    target = prediction.TARGETS[result["target"]]["label"]
    year = prediction.period(result["split"]["test"])
    title = f"Average miss in {year} by model ({target})"
    kinds = list(prediction.MODELS)
    names = [prediction.MODELS[kind]["name"] + (" (chosen)" if kind == result["chosen"] else "") for kind in kinds]
    values = [result["test"][kind]["mae"] for kind in kinds]
    colors = [OTHER if kind == "mean" else SERIES[0] for kind in kinds]
    labels = [analysis.format_number(value) for value in values]
    data = [{
        "type": "bar", "orientation": "h", "x": [clean(v) for v in values], "y": names,
        "marker": {"color": colors}, "text": labels, "textposition": "outside", "cliponaxis": False,
        "textfont": {"color": INK, "size": 13},
        "customdata": [[result["validation"][kind]["mae"], result["test"][kind]["r2"]] for kind in kinds],
        "hovertemplate": "<b>%{y}</b><br>Test MAE %{x:,.4~g} short tons<br>Validation MAE %{customdata[0]:,.4~g}"
                         "<extra></extra>",
    }]
    figure = layout(title, "Mean absolute error (short tons)", "", height=260, bargap=0.45)
    figure["yaxis"]["autorange"] = "reversed"
    figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    figure["xaxis"]["rangemode"] = "tozero"
    figure["xaxis"]["range"] = [0, max(values) * 1.18 if max(values) > 0 else 1]
    figure["margin"]["r"] = 40
    columns = ["Model", "Validation MAE", "Test MAE", "Test RMSE", "Test R²", "Test weighted % error"]
    rows = [[prediction.MODELS[kind]["name"], clean(result["validation"][kind]["mae"]),
             clean(result["test"][kind]["mae"]), clean(result["test"][kind]["rmse"]),
             clean(result["test"][kind]["r2"]), clean(result["test"][kind]["wape"])] for kind in kinds]
    note = ("Shorter is better. Each model was refit on the training and validation years and scored once on the "
            "test year; the chosen model had the lowest error on the validation years.")
    return chart("model_errors", title, data, figure, columns, rows, note)


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
    data = []
    for family in analysis.FUEL_FAMILIES + [analysis.NOT_REPORTED]:
        part = sampled[sampled["fuel_family"] == family]
        if len(part) == 0:
            continue
        error_pct = (part[column] - part["actual"]) / part["actual"] * 100
        data.append({
            "type": "scattergl", "mode": "markers", "name": family,
            "x": part["actual"].tolist(), "y": part[column].tolist(),
            "customdata": [[text(label), pct] for label, pct in zip(part["label"], error_pct)],
            "marker": {"color": FAMILY_COLORS.get(family, OTHER), "size": 8, "opacity": 0.8,
                       "line": {"color": SURFACE, "width": 0.5}},
            "hovertemplate": "<b>%{customdata[0]}</b><br>Actual %{x:,.4~g} short tons<br>"
                             "Predicted %{y:,.4~g} short tons<br>Miss %{customdata[1]:+.1f}%<extra>" + family
                             + "</extra>",
        })
    low = float(min(shown["actual"].min(), shown[column].min()))
    high = float(max(shown["actual"].max(), shown[column].max()))
    data.append({
        "type": "scatter", "mode": "lines", "name": "Perfect prediction", "x": [low, high], "y": [low, high],
        "line": {"color": REFERENCE, "width": 1.5, "dash": "dash"}, "hoverinfo": "skip",
    })
    figure = layout(title, f"Actual {target} (short tons, log scale)", f"Predicted {target} (short tons, log scale)",
                    height=460, showlegend=True)
    for name in ("xaxis", "yaxis"):
        figure[name]["type"] = "log"
        figure[name]["dtick"] = 1
        figure[name]["exponentformat"] = "power"
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
    return chart("predicted_actual", title, data, figure, columns, rows, note)


def trend_forecast(trend, target):
    """Annual totals, the three year-trend models fitted to every year, and their forecasts."""
    label = prediction.TARGETS[target]["label"]
    title = f"Annual {label} total and year-trend forecast"
    totals = trend["totals"]
    years = [row["year"] for row in totals]
    future = [row["year"] for row in trend["forecast"]["rows"]]
    divisor, unit = scale_for([row["total"] for row in totals])
    data = [{
        "type": "scatter", "mode": "lines+markers", "name": "Actual total",
        "x": years, "y": [row["total"] / divisor for row in totals],
        "line": {"color": SERIES[0], "width": 2.5}, "marker": {"size": 6, "color": SERIES[0]},
        "customdata": [row["units"] for row in totals],
        "hovertemplate": "%{x}: %{y:,.4~g} " + unit + "<br>%{customdata:,} units<extra>Actual</extra>",
    }]
    styles = {"linear": (SERIES[1], "dash"), "tree": (SERIES[2], "dash"), "mean": (REFERENCE, "dot")}
    for kind in ("linear", "tree", "mean"):
        color, dash = styles[kind]
        values = trend["forecast"]["fitted"][kind] + [row[kind] for row in trend["forecast"]["rows"]]
        data.append({
            "type": "scatter", "mode": "lines", "name": prediction.MODELS[kind]["name"],
            "x": years + future, "y": [value / divisor for value in values],
            "line": {"color": color, "width": 2, "dash": dash, "shape": "hv" if kind == "tree" else "linear"},
            "hovertemplate": "%{x}: %{y:,.4~g} " + unit + "<extra>" + prediction.MODELS[kind]["name"] + "</extra>",
        })
    figure = layout(title, "Reporting year", f"Total {label} ({unit})", height=440, showlegend=True,
                    hovermode="x unified")
    figure["yaxis"]["rangemode"] = "tozero"
    figure["xaxis"]["dtick"] = year_step(years + future)
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
    columns = ["Year", "Actual total (short tons)", "Units reporting", "Mean baseline", "Linear regression",
               "Decision tree"]
    fitted = trend["forecast"]["fitted"]
    rows = [[row["year"], clean(row["total"]), row["units"], clean(fitted["mean"][index]),
             clean(fitted["linear"][index]), clean(fitted["tree"][index])] for index, row in enumerate(totals)]
    rows += [[row["year"], None, None, clean(row["mean"]), clean(row["linear"]), clean(row["tree"])]
             for row in trend["forecast"]["rows"]]
    note = ("Model lines are fitted to every year and extended past the last one. A decision tree can't extend a "
            "trend, so its forecast stays flat; a straight line keeps the past trend going.")
    return chart("trend_forecast", title, data, figure, columns, rows, note)


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

    hover = ("<b>" + info["label"] + " %{x:,.4~g} " + info["unit"] + "</b> (%{customdata[0]})<br>"
             "Predicted %{y:,.4~g} short tons<br>Change %{customdata[1]} (%{customdata[2]})")
    data = [{
        "type": "scatter", "mode": "lines", "name": "Prediction", "showlegend": False,
        "x": [row["value"] for row in rows], "y": [row["prediction"] for row in rows],
        "line": {"color": SERIES[0], "width": 2, "shape": "hv" if kind == "tree" else "linear"}, "hoverinfo": "skip",
    }, {
        "type": "scatter", "mode": "markers", "name": "Prediction",
        "x": [row["value"] for row in inside], "y": [row["prediction"] for row in inside],
        "customdata": [details(row) for row in inside],
        "marker": {"color": SERIES[0], "size": 8, "line": {"color": SURFACE, "width": 2}},
        "hovertemplate": hover + "<extra></extra>",
    }]
    if beyond:
        data.append({
            "type": "scatter", "mode": "markers", "name": "Outside training range",
            "x": [row["value"] for row in beyond], "y": [row["prediction"] for row in beyond],
            "customdata": [details(row) for row in beyond],
            # Open symbols draw their outline in marker.color
            "marker": {"color": WARNING_LINE, "size": 10, "symbol": "circle-open", "line": {"width": 2}},
            "hovertemplate": hover + "<br>⚠ Outside the training range<extra></extra>",
        })
    base_x = baseline["inputs"][variable]
    data.append({
        "type": "scatter", "mode": "markers+text", "name": "Baseline",
        "x": [base_x], "y": [base_prediction], "text": ["Baseline"], "textposition": "top left",
        "textfont": {"color": INK, "size": 12},
        "marker": {"color": INK, "size": 12, "line": {"color": SURFACE, "width": 2}},
        "hovertemplate": ("<b>Baseline</b><br>" + info["label"] + " %{x:,.4~g} " + info["unit"]
                          + "<br>Predicted %{y:,.4~g} short tons<extra></extra>"),
    })
    figure = layout(title, f"{info['label']} ({info['unit']})", f"Predicted {label} (short tons)", height=440,
                    showlegend=True)
    figure["yaxis"]["rangemode"] = "tozero"
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
    return chart("sensitivity", title, data, figure, columns, table, note)


def scenario_bars(rows, target, base_prediction):
    """Each scenario's prediction, baseline in gray, with the change from the baseline on every bar."""
    label = prediction.TARGETS[target]["label"]
    title = f"Predicted {label} by scenario"
    names = [row["name"] + (" ⚠" if row["warnings"] else "") for row in rows]
    values = [row["prediction"] for row in rows]
    colors = [OTHER if row["key"] == "baseline" else SERIES[0] for row in rows]
    patterns = ["/" if row["warnings"] else "" for row in rows]
    labels = []
    for row in rows:
        if row["key"] == "baseline":
            labels.append(analysis.format_number(row["prediction"]))
        else:
            labels.append(f"{analysis.format_number(row['prediction'])}  ({percent(row['change_pct'])})")
    data = [{
        "type": "bar", "orientation": "h", "x": [clean(v) for v in values], "y": names,
        "marker": {"color": colors, "pattern": {"shape": patterns, "fgcolor": SURFACE, "size": 7, "solidity": 0.25}},
        "text": labels, "textposition": "outside", "cliponaxis": False, "textfont": {"color": INK, "size": 12},
        "customdata": [[row["about"], signed(row["change"], " short tons"), percent(row["change_pct"]),
                        "<br>⚠ " + "<br>⚠ ".join(row["warnings"]) if row["warnings"] else ""] for row in rows],
        "hovertemplate": ("<b>%{y}</b><br>%{customdata[0]}<br>Predicted %{x:,.4~g} short tons<br>"
                          "Change %{customdata[1]} (%{customdata[2]})%{customdata[3]}<extra></extra>"),
    }]
    figure = layout(title, f"Predicted {label} (short tons)", "", height=max(300, 44 * len(rows) + 110),
                    bargap=0.4)
    figure["yaxis"]["autorange"] = "reversed"
    figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    top = max(values) if values else 1
    figure["xaxis"]["range"] = [0, top * 1.45 if top > 0 else 1]   # room for the labels, even on a phone
    figure["margin"]["r"] = 40
    figure["shapes"] = [{"type": "line", "xref": "x", "yref": "paper", "x0": base_prediction, "x1": base_prediction,
                         "y0": 0, "y1": 1, "line": {"color": REFERENCE, "width": 1, "dash": "dash"}}]
    columns = ["Scenario", "What changes", f"Predicted {label} (short tons)", "Change from baseline (short tons)",
               "Change from baseline (%)", "Warnings"]
    table = [[row["name"], row["about"], clean(row["prediction"]), clean(row["change"]), clean(row["change_pct"]),
              " ".join(row["warnings"]) or "None"] for row in rows]
    note = ("The dashed line marks the baseline prediction. Striped bars and ⚠ mark scenarios with an input "
            "outside what the model saw in training; treat them as extrapolations.")
    return chart("scenarios", title, data, figure, columns, table, note)

