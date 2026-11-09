"""
Phase 2 visualization dashboard (proposal 4.4).

Every chart is built here as a Plotly figure (data + layout) plus the table of numbers behind it.
The page draws the figures with Plotly.js, shows the table under each chart, and offers the
table as CSV/Excel and the chart as a PNG image.

Charts
  indexed       CO2, SO2, NOx and gross load over time, each indexed to its first year = 100
  trend         the chosen variable over time, optionally one line per fuel family or control group
  bars          the chosen variable compared across states, fuels, unit types, facilities or controls
  histogram     the distribution of the chosen variable
  box           the distribution for each group (box plots)
  scatter       one variable against another, one color per fuel family
  correlation   correlation heat map of the main measured and derived variables
  rank_high     facilities or units with the highest values
  rank_low      facilities or units with the lowest values
  state_map     the chosen variable by state
  facility_map  facility locations colored by the chosen variable

Design rules (kept the same on every chart)
  - Colors follow the thing they stand for: CO2 is always blue, SO2 orange, NOx green-blue,
    coal blue, gas orange, oil and other green-blue. A filter never repaints them.
  - One y-axis per chart. Measures with different units are indexed or drawn as separate charts.
  - Every value on a chart is also in the table under it.
"""

import html
import math

import numpy as np
import pandas as pd

import analysis

# ---------- Look ----------

FONT = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, Arial, sans-serif'
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#ffffff"

# Categorical colors, always used in this order (checked for color-blind separation)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#a8a7a1"

POLLUTANT_COLORS = {"co2_mass": SERIES[0], "so2_mass": SERIES[1], "nox_mass": SERIES[2], "gross_load": SERIES[3]}
FAMILY_COLORS = {"Coal": SERIES[0], "Gas": SERIES[1], "Oil and other": SERIES[2]}

# One blue, light to dark, for amounts (maps)
SEQUENTIAL = [[0.0, "#cde2fb"], [0.25, "#86b6ef"], [0.5, "#3987e5"], [0.75, "#1c5cab"], [1.0, "#0d366b"]]
# Red (negative) to gray (zero) to blue (positive), for correlations
DIVERGING = [[0.0, "#e34948"], [0.5, "#f0efec"], [1.0, "#2a78d6"]]


def axis(title, **extra):
    settings = {
        "title": {"text": title, "font": {"color": INK_2, "size": 13}, "standoff": 12},
        "gridcolor": GRID,
        "linecolor": AXIS,
        "zeroline": False,
        "tickfont": {"color": MUTED, "size": 12},
        "automargin": True,
    }
    settings.update(extra)
    return settings


def layout(title, x_title="", y_title="", height=400, **extra):
    settings = {
        "title": {"text": title, "x": 0, "xanchor": "left", "y": 0.98, "yanchor": "top",
                  "font": {"size": 16, "color": INK}},
        "font": {"family": FONT, "size": 13, "color": INK_2},
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "height": height,
        "margin": {"l": 16, "r": 24, "t": 72, "b": 16},
        "xaxis": axis(x_title),
        "yaxis": axis(y_title),
        "hoverlabel": {"bgcolor": SURFACE, "bordercolor": GRID, "font": {"family": FONT, "color": INK, "size": 13}},
        "legend": {"orientation": "h", "x": 0, "xanchor": "left", "y": 1.0, "yanchor": "bottom",
                   "font": {"color": INK_2, "size": 12}, "bgcolor": "rgba(0,0,0,0)"},
        "barcornerradius": 4,
        "showlegend": False,
    }
    settings.update(extra)
    return settings


def chart(chart_id, title, data, figure_layout, columns, rows, note="", empty=None):
    return {
        "id": chart_id,
        "title": title,
        "note": note,
        "empty": empty,
        "data": data,
        "layout": figure_layout,
        "table": {"columns": columns, "rows": rows},
        "filename": "epadata-" + chart_id,
    }


def empty_chart(chart_id, title, message):
    return chart(chart_id, title, [], {}, [], [], empty=message)


def text(value):
    """Facility and unit names go into tooltips; escape them so they show as plain text."""
    return html.escape(str(value), quote=False)


def unit_of(key):
    return analysis.VARIABLES[key]["unit"]


def log_axis(settings):
    settings["type"] = "log"
    settings["dtick"] = "D2"


def lower_first(label):
    """'Gross load' -> 'gross load', but 'CO2 mass' stays as it is."""
    if label[:3] in ("CO2", "SO2", "NOx"):
        return label
    return label[0].lower() + label[1:]


def value_title(key):
    """'Total CO2 mass (short tons)' or 'Overall CO2 intensity (short tons/MWh)'."""
    item = analysis.VARIABLES[key]
    word = analysis.aggregate_label(key)
    if word == "Overall ratio":
        word = "Overall"
    return f"{word} {lower_first(item['label'])} ({item['unit']})"


def spread_labels(annotations, gap_share=0.05):
    """Nudge end-of-line labels apart so they don't sit on top of each other."""
    if len(annotations) < 2:
        return
    values = [item["y"] for item in annotations]
    gap = (max(values) - min(values)) * gap_share or 1.0
    ordered = sorted(annotations, key=lambda item: item["y"])
    for lower, upper in zip(ordered, ordered[1:]):
        if upper["y"] - lower["y"] < gap:
            upper["y"] = lower["y"] + gap


def hover_number(unit):
    return "%{y:,.4~g} " + unit


def selection_years(frame):
    years = sorted(int(year) for year in frame["year"].dropna().unique())
    return years


# ---------- Options shown on the page ----------

SPLITS = {
    "none": "No split",
    "fuel_family": "Fuel family",
    "so2_control": "SO2 control",
    "nox_control": "NOx control",
}

SCALES = {"log": "Log scale", "linear": "Linear scale"}
CORRELATION_METHODS = {
    "spearman": "Spearman (ranks)",
    "pearson": "Pearson (linear)",
}
RANK_LEVELS = {"facility": "Facilities", "unit": "Units"}

CORRELATION_VARIABLES = [
    ("co2_mass", "CO2"), ("so2_mass", "SO2"), ("nox_mass", "NOx"), ("gross_load", "Gross load"),
    ("heat_input", "Heat input"), ("operating_time", "Operating time"), ("co2_intensity", "CO2/MWh"),
    ("so2_intensity", "SO2/MWh"), ("nox_intensity", "NOx/MWh"), ("heat_rate", "Heat rate"),
    ("operating_utilization", "Utilization"),
]

# Variables offered for the scatter plot (no year-over-year changes)
SCATTER_VARIABLES = [key for key, item in analysis.VARIABLES.items() if item["group"] != "Year-over-year change"]

CORRELATION_MINIMUM = 5
BAR_LIMIT = 20
BOX_LIMIT = 10
SCATTER_SAMPLE = 4000
RANK_COUNT = 10
MAP_FACILITY_LIMIT = 1000
DEFAULT_MIN_LOAD = 10000


def split_labels(frame, split):
    if split == "fuel_family":
        return frame["primary_fuel"].map(analysis.fuel_family), list(analysis.FUEL_FAMILIES), FAMILY_COLORS
    if split in ("so2_control", "nox_control"):
        labels = analysis.group_labels(frame, split)
        pollutant = "SO2" if split == "so2_control" else "NOx"
        order = [f"With {pollutant} control", f"No {pollutant} control reported"]
        return labels, order, {order[0]: SERIES[0], order[1]: SERIES[1]}
    return None, [], {}


# ---------- Trends ----------

def indexed_trend(frame):
    """CO2, SO2, NOx and gross load totals by year, each indexed to its first year = 100."""
    title = "Emissions and generation over time (first year = 100)"
    years = selection_years(frame)
    if len(years) < 2:
        return empty_chart("indexed", title, "This selection covers one year, so there is no trend to show.")

    keys = ["co2_mass", "so2_mass", "nox_mass", "gross_load"]
    names = {"co2_mass": "CO2", "so2_mass": "SO2", "nox_mass": "NOx", "gross_load": "Gross load"}
    totals = frame.groupby("year")[keys].sum(min_count=1).reindex(years)

    data = []
    annotations = []
    columns = ["Year"] + [f"{names[k]} total ({unit_of(k)})" for k in keys] + [f"{names[k]} index" for k in keys]
    indexes = {}
    for key in keys:
        series = totals[key]
        base_year = next((year for year in years if pd.notna(series[year]) and series[year] > 0), None)
        if base_year is None:
            indexes[key] = pd.Series(np.nan, index=years)
            continue
        index = series / series[base_year] * 100
        indexes[key] = index
        data.append({
            "type": "scatter", "mode": "lines+markers", "name": names[key],
            "x": years, "y": [clean(v) for v in index],
            "customdata": [[clean(v)] for v in series],
            "line": {"color": POLLUTANT_COLORS[key], "width": 2},
            "marker": {"size": 8, "color": POLLUTANT_COLORS[key], "line": {"color": SURFACE, "width": 2}},
            "hovertemplate": f"{names[key]}: %{{y:.1f}} (total %{{customdata[0]:,.0f}} {unit_of(key)})<extra></extra>",
        })
        last = next((year for year in reversed(years) if pd.notna(index[year])), None)
        if last is not None:
            annotations.append({"x": last, "y": float(index[last]), "text": names[key], "showarrow": False,
                                "xanchor": "left", "xshift": 10, "yanchor": "middle",
                                "font": {"color": INK_2, "size": 12}})

    rows = []
    for year in years:
        row = [year] + [clean(totals.loc[year, k]) for k in keys] + [clean(indexes[k][year]) for k in keys]
        rows.append(row)

    spread_labels(annotations)
    figure = layout(title, "Reporting year", "Index (first year with data = 100)", showlegend=True,
                    hovermode="x unified", annotations=annotations)
    figure["xaxis"]["dtick"] = 1
    figure["xaxis"]["range"] = [years[0] - 0.3, years[-1] + 0.3]
    figure["margin"]["r"] = 96
    note = ("Each line is the yearly total for the selected records divided by that line's first-year total. "
            "Totals also change when units start or stop reporting.")
    return chart("indexed", title, data, figure, columns, rows, note)


def trend(frame, key, split="none"):
    item = analysis.VARIABLES[key]
    title = f"{item['label']} over time"
    years = selection_years(frame)
    if len(years) < 2:
        return empty_chart("trend", title, "This selection covers one year, so there is no trend to show.")

    labels, order, colors = split_labels(frame, split)
    if labels is None:
        series = [("All selected records", frame, SERIES[0])]
    else:
        series = [(name, frame[labels == name], colors[name]) for name in order if (labels == name).any()]

    data = []
    columns = ["Year"]
    values_by_series = []
    for name, part, color in series:
        table = analysis.aggregate(part, key, part["year"]).reindex(years)
        values = [clean(v) for v in table["value"]]
        counts = [0 if pd.isna(c) else int(c) for c in table["records"]]
        values_by_series.append(values)
        columns.append(f"{name}: {value_title(key)}")
        data.append({
            "type": "scatter", "mode": "lines+markers", "name": name, "x": years, "y": values,
            "customdata": [[c] for c in counts],
            "line": {"color": color, "width": 2},
            "marker": {"size": 8, "color": color, "line": {"color": SURFACE, "width": 2}},
            "hovertemplate": f"{text(name)}: %{{y:,.4~g}} {item['unit']} (%{{customdata[0]:,}} records)<extra></extra>",
            "connectgaps": False,
        })

    rows = [[year] + [values[i] for values in values_by_series] for i, year in enumerate(years)]
    figure = layout(title, "Reporting year", value_title(key), showlegend=len(series) > 1, hovermode="x unified")
    figure["xaxis"]["dtick"] = 1
    note = {
        "Overall ratio": "Each point divides the year's total of the numerator by the total of the denominator.",
        "Total": "Each point is the year's total over the selected records.",
        "Mean": "Each point is the year's average over the selected records.",
    }[analysis.aggregate_label(key)]
    return chart("trend", title, data, figure, columns, rows, note)


# ---------- Comparisons across groups ----------

def bars(frame, key, group):
    item = analysis.VARIABLES[key]
    group_name = analysis.GROUPS[group]
    title = f"{item['label']} by {group_name.lower()}"
    table = analysis.aggregate(frame, key, analysis.group_labels(frame, group))
    table = table[table["value"].notna()].sort_values("value", ascending=False, kind="mergesort")
    if table.empty:
        return empty_chart("bars", title, "No values for this variable in the selection.")

    shown = table.head(BAR_LIMIT)
    names = list(shown.index)
    data = [{
        "type": "bar", "orientation": "h",
        "x": [clean(v) for v in shown["value"]], "y": [text(n) for n in names],
        "customdata": [[int(r)] for r in shown["records"]],
        "marker": {"color": SERIES[0]},
        "hovertemplate": "%{y}<br><b>%{x:,.4~g} " + item["unit"] + "</b> (%{customdata[0]:,} records)<extra></extra>",
    }]
    height = max(260, 34 * len(names) + 110)
    figure = layout(title, value_title(key), "", height=height, bargap=0.25)
    figure["yaxis"]["autorange"] = "reversed"
    figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"

    columns = [group_name, value_title(key), "Records"]
    rows = [[name, clean(row["value"]), int(row["records"])] for name, row in table.iterrows()]
    note = f"Highest {len(shown)} of {len(table)} groups shown; the table and download have all of them."
    if len(table) <= BAR_LIMIT:
        note = f"All {len(table)} groups, highest first."
    return chart("bars", title, data, figure, columns, rows, note)


# ---------- Distributions ----------

def positive_or_all(values, scale):
    if scale == "log":
        return values[values > 0]
    return values


def histogram(frame, key, scale="log"):
    item = analysis.VARIABLES[key]
    title = f"Distribution of {item['label']}"
    values = frame[key].dropna()
    excluded = 0
    if scale == "log":
        positive = values[values > 0]
        excluded = int(len(values) - len(positive))
        values = positive
    if len(values) < 2 or values.min() == values.max():
        return empty_chart("histogram", title, "Not enough different values to draw a distribution.")

    bins = 40
    if scale == "log":
        edges = np.logspace(math.log10(values.min()), math.log10(values.max()), bins + 1)
    else:
        edges = np.linspace(values.min(), values.max(), bins + 1)
    # Rounding in logspace can put the outer edges a hair inside the data; pin them to it
    edges[0] = values.min()
    edges[-1] = values.max()
    counts, edges = np.histogram(values, bins=edges)

    ranges = [[float(edges[i]), float(edges[i + 1]), int(counts[i])] for i in range(len(counts))]
    if scale == "log":
        # A step outline: correct bin edges on a log axis
        data = [{
            "type": "scatter", "mode": "lines", "x": [float(e) for e in edges],
            "y": [int(c) for c in counts] + [int(counts[-1])],
            "customdata": ranges + [ranges[-1]],
            "line": {"shape": "hv", "color": SERIES[0], "width": 2},
            "fill": "tozeroy", "fillcolor": "rgba(42,120,214,0.18)",
            "hovertemplate": "%{customdata[0]:,.4~g} to %{customdata[1]:,.4~g} " + item["unit"]
                             + "<br><b>%{customdata[2]:,} records</b><extra></extra>",
        }]
    else:
        centers = (edges[:-1] + edges[1:]) / 2
        data = [{
            "type": "bar", "x": [float(c) for c in centers], "y": [int(c) for c in counts],
            "width": [float(edges[i + 1] - edges[i]) * 0.94 for i in range(len(counts))],
            "customdata": ranges, "marker": {"color": SERIES[0]},
            "hovertemplate": "%{customdata[0]:,.4~g} to %{customdata[1]:,.4~g} " + item["unit"]
                             + "<br><b>%{customdata[2]:,} records</b><extra></extra>",
        }]

    figure = layout(title, f"{item['label']} ({item['unit']}){', log scale' if scale == 'log' else ''}",
                    "Number of records", bargap=0)
    if scale == "log":
        log_axis(figure["xaxis"])

    note = f"{len(values):,} records in {bins} bins."
    if excluded:
        note += f" {excluded:,} records with a value of 0 are left out because a log scale can't show 0."
    columns = [f"From ({item['unit']})", f"To ({item['unit']})", "Records"]
    return chart("histogram", title, data, figure, columns, ranges, note)


def box_stats(values):
    q1 = float(values.quantile(0.25))
    median = float(values.median())
    q3 = float(values.quantile(0.75))
    spread = q3 - q1
    low_limit = q1 - 1.5 * spread
    high_limit = q3 + 1.5 * spread
    inside = values[(values >= low_limit) & (values <= high_limit)]
    lower = float(inside.min()) if len(inside) else float(values.min())
    upper = float(inside.max()) if len(inside) else float(values.max())
    outliers = int(((values < low_limit) | (values > high_limit)).sum())
    return {"q1": q1, "median": median, "q3": q3, "mean": float(values.mean()), "lower": lower, "upper": upper,
            "outliers": outliers, "count": int(len(values)), "min": float(values.min()), "max": float(values.max())}


def box(frame, key, group, scale="log"):
    item = analysis.VARIABLES[key]
    group_name = analysis.GROUPS[group]
    title = f"Spread of {lower_first(item['label'])} within each {group_name.lower()}"
    data_frame = pd.DataFrame({"group": analysis.group_labels(frame, group), "value": frame[key]}).dropna()
    data_frame = data_frame[data_frame["group"] != analysis.NOT_REPORTED]
    if scale == "log":
        data_frame = data_frame[data_frame["value"] > 0]
    counts = data_frame.groupby("group").size()
    counts = counts[counts >= 5].sort_values(ascending=False)
    if counts.empty:
        return empty_chart("box", title, "No group has at least 5 values to draw a box plot.")
    names = list(counts.index[:BOX_LIMIT])
    stats = [box_stats(data_frame.loc[data_frame["group"] == name, "value"]) for name in names]

    data = [{
        "type": "box", "name": item["label"], "x": [text(n) for n in names],
        "q1": [s["q1"] for s in stats], "median": [s["median"] for s in stats], "q3": [s["q3"] for s in stats],
        "lowerfence": [s["lower"] for s in stats], "upperfence": [s["upper"] for s in stats],
        "mean": [s["mean"] for s in stats],
        "boxpoints": False, "marker": {"color": SERIES[0]},
        "line": {"color": SERIES[0], "width": 2}, "fillcolor": "rgba(42,120,214,0.18)",
    }]
    figure = layout(title, group_name, f"{item['label']} ({item['unit']})", height=420)
    if scale == "log":
        log_axis(figure["yaxis"])
    figure["xaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    columns = [group_name, "Records", "Minimum", "Lower whisker", "Q1", "Median", "Mean", "Q3", "Upper whisker",
               "Maximum", "Outliers beyond whiskers"]
    rows = [[n, s["count"], s["min"], s["lower"], s["q1"], s["median"], s["mean"], s["q3"], s["upper"], s["max"],
             s["outliers"]] for n, s in zip(names, stats)]
    note = (f"The {len(names)} largest groups. Boxes run from Q1 to Q3 with the median inside; whiskers reach the "
            f"furthest values within 1.5 × IQR. Points beyond the whiskers are counted in the table, not drawn.")
    if scale == "log":
        note += " Values of 0 are left out on the log scale."
    return chart("box", title, data, figure, columns, rows, note)


# ---------- Relationships ----------

def scatter(frame, x_key, y_key, scale="log"):
    x_item = analysis.VARIABLES[x_key]
    y_item = analysis.VARIABLES[y_key]
    title = f"{y_item['label']} against {lower_first(x_item['label'])}"
    data_frame = pd.DataFrame({
        "x": frame[x_key], "y": frame[y_key],
        "family": frame["primary_fuel"].map(analysis.fuel_family),
        "name": analysis.unit_labels(frame), "year": frame["year"],
    }).dropna(subset=["x", "y"])
    if scale == "log":
        data_frame = data_frame[(data_frame["x"] > 0) & (data_frame["y"] > 0)]
    if len(data_frame) < 3:
        return empty_chart("scatter", title, "Fewer than 3 records have both values.")

    pearson = data_frame["x"].corr(data_frame["y"], method="pearson")
    spearman = data_frame["x"].corr(data_frame["y"], method="spearman")
    shown = data_frame
    if len(shown) > SCATTER_SAMPLE:
        shown = shown.sample(n=SCATTER_SAMPLE, random_state=0)

    data = []
    for family in analysis.FUEL_FAMILIES:
        part = shown[shown["family"] == family]
        if part.empty:
            continue
        data.append({
            "type": "scattergl", "mode": "markers", "name": family,
            "x": [float(v) for v in part["x"]], "y": [float(v) for v in part["y"]],
            "text": [f"{text(n)}, {int(y)}" for n, y in zip(part["name"], part["year"])],
            "marker": {"size": 8, "color": FAMILY_COLORS[family], "opacity": 0.75,
                       "line": {"color": SURFACE, "width": 1}},
            "hovertemplate": "%{text}<br>" + x_item["label"] + ": <b>%{x:,.4~g}</b> " + x_item["unit"]
                             + "<br>" + y_item["label"] + ": <b>%{y:,.4~g}</b> " + y_item["unit"]
                             + "<extra>" + family + "</extra>",
        })
    figure = layout(title, f"{x_item['label']} ({x_item['unit']})", f"{y_item['label']} ({y_item['unit']})",
                    height=460, showlegend=True, hovermode="closest")
    if scale == "log":
        log_axis(figure["xaxis"])
        log_axis(figure["yaxis"])

    note = (f"Correlation over all {len(data_frame):,} records with both values: "
            f"Spearman {spearman:.2f}, Pearson {pearson:.2f}.")
    if len(data_frame) > SCATTER_SAMPLE:
        note += f" The chart draws a random sample of {SCATTER_SAMPLE:,} points so the page stays fast."
    if scale == "log":
        note += " Records with a 0 are left out on the log scale."
    columns = ["Fuel family", "Records", "Spearman correlation", "Pearson correlation"]
    rows = []
    for family in analysis.FUEL_FAMILIES:
        part = data_frame[data_frame["family"] == family]
        if len(part) >= 3:
            rows.append([family, int(len(part)), clean(part["x"].corr(part["y"], method="spearman")),
                         clean(part["x"].corr(part["y"], method="pearson"))])
    rows.append(["All", int(len(data_frame)), clean(spearman), clean(pearson)])
    return chart("scatter", title, data, figure, columns, rows, note)


def correlation(frame, method="spearman"):
    method = method if method in CORRELATION_METHODS else "spearman"
    title = f"How the variables move together ({method.title()} correlation)"
    keys = [key for key, _ in CORRELATION_VARIABLES if key in frame.columns]
    names = [name for key, name in CORRELATION_VARIABLES if key in frame.columns]
    values = frame[keys].astype("float64")
    if len(values.dropna(how="all")) < CORRELATION_MINIMUM:
        return empty_chart("correlation", title,
                           f"At least {CORRELATION_MINIMUM} records are needed for correlations.")
    matrix = values.corr(method=method, min_periods=CORRELATION_MINIMUM)
    present = values.notna().astype(int)
    pairs = present.T.dot(present)

    z = [[clean(matrix.iloc[i, j]) for j in range(len(keys))] for i in range(len(keys))]
    counts = [[int(pairs.iloc[i, j]) for j in range(len(keys))] for i in range(len(keys))]
    annotations = []
    for i in range(len(keys)):
        for j in range(len(keys)):
            r = z[i][j]
            if i != j and r is not None and abs(r) >= 0.7:
                annotations.append({"x": names[j], "y": names[i], "text": f"{r:.2f}", "showarrow": False,
                                    "font": {"color": SURFACE if abs(r) >= 0.85 else INK, "size": 11}})
    data = [{
        "type": "heatmap", "x": names, "y": names, "z": z, "customdata": counts,
        "zmin": -1, "zmax": 1, "zmid": 0, "colorscale": DIVERGING, "xgap": 2, "ygap": 2,
        "colorbar": {"title": {"text": "r", "side": "top"}, "thickness": 12, "outlinewidth": 0,
                     "tickfont": {"color": MUTED}, "len": 0.8},
        "hovertemplate": "%{y} and %{x}<br><b>r = %{z:.2f}</b> (%{customdata:,} records)<extra></extra>",
    }]
    figure = layout(title, "", "", height=560, annotations=annotations)
    figure["yaxis"]["autorange"] = "reversed"
    figure["xaxis"]["tickangle"] = -40
    for name in ("xaxis", "yaxis"):
        figure[name]["gridcolor"] = "rgba(0,0,0,0)"
        figure[name]["linecolor"] = "rgba(0,0,0,0)"
        figure[name]["ticks"] = ""
    columns = ["Variable"] + names
    rows = [[names[i]] + z[i] for i in range(len(keys))]
    note = (f"Each pair uses the records that have both values (at least {CORRELATION_MINIMUM}). "
            "1 means two variables rise together perfectly, −1 that one falls as the other rises, 0 no "
            "relationship. Values of 0.7 or more either way are labeled. Correlation is not causation.")
    if method == "spearman":
        note += " Spearman compares ranks, so a few very large plants don't dominate it."
    return chart("correlation", title, data, figure, columns, rows, note)


# ---------- Rankings ----------

def ranking_table(frame, key, level, min_load):
    """Every facility or unit with its value and gross load, sorted highest first."""
    if level == "unit":
        labels = analysis.unit_labels(frame)
    else:
        labels = analysis.group_labels(frame, "facility")
    table = analysis.aggregate(frame, key, labels)
    load = pd.DataFrame({"group": labels, "load": frame["gross_load"]}).groupby("group", sort=False)["load"] \
        .sum(min_count=1)
    table["gross_load"] = load
    table = table[table["value"].notna()]
    excluded = 0
    if analysis.VARIABLES[key]["ratio"]:
        keep = table["gross_load"].fillna(0) >= min_load
        excluded = int((~keep).sum())
        table = table[keep]
    return table.sort_values("value", ascending=False, kind="mergesort"), excluded


def rankings(frame, key, level="facility", min_load=DEFAULT_MIN_LOAD):
    item = analysis.VARIABLES[key]
    level = level if level in RANK_LEVELS else "facility"
    noun = RANK_LEVELS[level].lower()
    table, excluded = ranking_table(frame, key, level, min_load)

    high_title = f"Highest {item['label']}: top {RANK_COUNT} {noun}"
    low_title = f"Lowest {item['label']}: bottom {RANK_COUNT} {noun}"
    if table.empty:
        message = "No values for this variable in the selection."
        return empty_chart("rank_high", high_title, message), empty_chart("rank_low", low_title, message)

    lowest_pool = table
    low_note = ""
    if item["additive"]:
        lowest_pool = table[table["value"] > 0]
        low_note = " Zeros are left out, so these are the lowest that reported any."
    common = ""
    if item["ratio"]:
        common = (f" Only {noun} with at least {min_load:,.0f} MWh of gross load in the selection are ranked, so "
                  f"very small ones don't top the list by chance ({excluded:,} left out).")

    def bar_chart(chart_id, title, part, note):
        names = list(part.index)
        data = [{
            "type": "bar", "orientation": "h", "x": [clean(v) for v in part["value"]],
            "y": [text(n) for n in names], "customdata": [[clean(g)] for g in part["gross_load"]],
            "marker": {"color": SERIES[0]},
            "hovertemplate": "%{y}<br><b>%{x:,.4~g} " + item["unit"]
                             + "</b><br>Gross load %{customdata[0]:,.0f} MWh<extra></extra>",
        }]
        figure = layout(title, value_title(key), "", height=max(260, 34 * len(names) + 110), bargap=0.25)
        figure["yaxis"]["autorange"] = "reversed"
        figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
        columns = ["Rank", "Unit" if level == "unit" else "Facility", value_title(key), "Gross load (MWh)", "Records"]
        rows = []
        for rank, (name, row) in enumerate(part.iterrows(), start=1):
            rows.append([rank, name, clean(row["value"]), clean(row["gross_load"]), int(row["records"])])
        return chart(chart_id, title, data, figure, columns, rows, note)

    high = table.head(RANK_COUNT)
    low = lowest_pool.tail(RANK_COUNT).iloc[::-1]
    return (bar_chart("rank_high", high_title, high, f"Out of {len(table):,} {noun}." + common),
            bar_chart("rank_low", low_title, low, f"Lowest first, out of {len(lowest_pool):,} {noun}." + low_note
                      + common))


# ---------- Maps ----------

def state_map(frame, key):
    item = analysis.VARIABLES[key]
    title = f"{item['label']} by state"
    table = analysis.aggregate(frame, key, frame["state"].fillna(analysis.NOT_REPORTED))
    table = table[table["value"].notna() & (table.index != analysis.NOT_REPORTED)]
    if table.empty:
        return empty_chart("state_map", title, "No state values for this variable in the selection.")
    codes = list(table.index)
    names = [analysis_state_name(code) for code in codes]
    data = [{
        "type": "choropleth", "locationmode": "USA-states", "locations": codes,
        "z": [clean(v) for v in table["value"]], "text": names,
        "customdata": [[int(r)] for r in table["records"]],
        "colorscale": SEQUENTIAL, "marker": {"line": {"color": SURFACE, "width": 1}},
        "colorbar": {"title": {"text": item["unit"], "side": "top"}, "thickness": 12, "outlinewidth": 0,
                     "tickfont": {"color": MUTED}, "len": 0.75},
        "hovertemplate": "%{text}<br><b>%{z:,.4~g} " + item["unit"] + "</b> (%{customdata[0]:,} records)<extra></extra>",
    }]
    figure = layout(title, height=460)
    figure["geo"] = {"scope": "usa", "bgcolor": SURFACE, "lakecolor": SURFACE, "showlakes": False,
                     "subunitcolor": SURFACE, "projection": {"type": "albers usa"}}
    figure["margin"] = {"l": 0, "r": 0, "t": 72, "b": 0}
    columns = ["State", "State code", value_title(key), "Records"]
    rows = [[name, code, clean(v), int(r)] for name, code, v, r in zip(names, codes, table["value"], table["records"])]
    rows.sort(key=lambda row: -(row[2] or 0))
    note = f"{analysis.aggregate_label(key)} for each state with records in the selection. Darker means higher."
    return chart("state_map", title, data, figure, columns, rows, note)


def analysis_state_name(code):
    import smart_search
    return smart_search.CODE_TO_STATE.get(code, code)


def facility_map(frame, key, min_load=DEFAULT_MIN_LOAD):
    item = analysis.VARIABLES[key]
    title = f"Facility locations colored by {item['label']}"
    labels = frame["facility_id"]
    table = analysis.aggregate(frame, key, labels)
    loads = pd.DataFrame({"group": labels, "load": frame["gross_load"]}).groupby("group", sort=False)["load"] \
        .sum(min_count=1)
    table["gross_load"] = loads
    table = table[table["value"].notna()]
    if item["ratio"]:
        table = table[table["gross_load"].fillna(0) >= min_load]
    if table.empty:
        return empty_chart("facility_map", title, "No facility values for this variable in the selection.")

    places = analysis.facility_locations(table.index)
    with_place = table[[int(i) in places for i in table.index]]
    without = len(table) - len(with_place)
    if with_place.empty:
        return empty_chart("facility_map", title, "None of these facilities has a location in the database. "
                                                  "Retrieve facility attributes to add latitude and longitude.")
    order_column = "gross_load" if item["ratio"] else "value"
    shown = with_place.sort_values(order_column, ascending=False).head(MAP_FACILITY_LIMIT)
    shown = shown.sort_values("value")   # largest drawn last, on top

    info = frame.drop_duplicates("facility_id").set_index("facility_id")
    names = [f"{text(info.at[i, 'facility_name'])} ({info.at[i, 'state']})" for i in shown.index]
    data = [{
        "type": "scattergeo", "mode": "markers",
        "lat": [places[int(i)][0] for i in shown.index], "lon": [places[int(i)][1] for i in shown.index],
        "text": names, "customdata": [[int(i)] for i in shown.index],
        "marker": {"size": 8, "color": [clean(v) for v in shown["value"]], "colorscale": SEQUENTIAL,
                   "line": {"color": SURFACE, "width": 1}, "opacity": 0.9,
                   "colorbar": {"title": {"text": item["unit"], "side": "top"}, "thickness": 12,
                                "outlinewidth": 0, "tickfont": {"color": MUTED}, "len": 0.75}},
        "hovertemplate": "%{text}<br><b>%{marker.color:,.4~g} " + item["unit"] + "</b><extra></extra>",
    }]
    figure = layout(title, height=460)
    figure["geo"] = {"scope": "usa", "bgcolor": SURFACE, "showland": True, "landcolor": "#f5f5f3",
                     "subunitcolor": "#d9d8d1", "showlakes": False, "projection": {"type": "albers usa"}}
    figure["margin"] = {"l": 0, "r": 0, "t": 72, "b": 0}

    columns = ["Facility ID", "Facility", "Latitude", "Longitude", value_title(key), "Gross load (MWh)"]
    rows = [[int(i), info.at[i, "facility_name"], places[int(i)][0], places[int(i)][1], clean(row["value"]),
             clean(row["gross_load"])] for i, row in shown.iloc[::-1].iterrows()]
    note = f"{len(shown):,} facilities."
    if len(with_place) > len(shown):
        note += (f" The {MAP_FACILITY_LIMIT:,} with the highest "
                 f"{'gross load' if item['ratio'] else item['label']} are drawn.")
    if without:
        note += f" {without:,} facilities have no stored location and are not drawn."
    if item["ratio"]:
        note += f" Facilities with under {min_load:,.0f} MWh of gross load are left out."
    return chart("facility_map", title, data, figure, columns, rows, note)


# ---------- Everything at once ----------

def build_all(frame, choices):
    key = choices["variable"]
    high, low = rankings(frame, key, choices["level"], choices["min_load"])
    return [
        indexed_trend(frame),
        trend(frame, key, choices["split"]),
        bars(frame, key, choices["group"]),
        histogram(frame, key, choices["scale"]),
        box(frame, key, choices["group"], choices["scale"]),
        scatter(frame, choices["x"], choices["y"], choices["scale"]),
        correlation(frame, choices["corr"]),
        high,
        low,
        state_map(frame, key),
        facility_map(frame, key, choices["min_load"]),
    ]


def build_one(frame, choices, chart_id):
    key = choices["variable"]
    builders = {
        "indexed": lambda: indexed_trend(frame),
        "trend": lambda: trend(frame, key, choices["split"]),
        "bars": lambda: bars(frame, key, choices["group"]),
        "histogram": lambda: histogram(frame, key, choices["scale"]),
        "box": lambda: box(frame, key, choices["group"], choices["scale"]),
        "scatter": lambda: scatter(frame, choices["x"], choices["y"], choices["scale"]),
        "correlation": lambda: correlation(frame, choices["corr"]),
        "rank_high": lambda: rankings(frame, key, choices["level"], choices["min_load"])[0],
        "rank_low": lambda: rankings(frame, key, choices["level"], choices["min_load"])[1],
        "state_map": lambda: state_map(frame, key),
        "facility_map": lambda: facility_map(frame, key, choices["min_load"]),
    }
    if chart_id not in builders:
        return None
    return builders[chart_id]()


# ---------- JSON safety ----------

def clean(value):
    """numpy numbers and NaN -> plain numbers and None, so the page gets valid JSON."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def json_safe(value):
    """Clean every number in a nested structure of dicts and lists."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (bool, str)) or value is None:
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return clean(value)
    return value


# ---------- Impact charts (proposal 4.6) ----------

def impact_share_chart(totals):
    """For each impact category, the share that comes from CO2, SO2 and NOx (one 100% bar each)."""
    import traci

    title = "Where each potential impact comes from"
    names = [item["name"] for item in totals if item["total"]]
    if not names:
        return empty_chart("impact_shares", title, "No impact could be calculated for this selection.")
    data = []
    for pollutant in traci.POLLUTANT_ORDER:
        label = traci.POLLUTANTS[pollutant]["label"]
        shares = []
        amounts = []
        for item in totals:
            if not item["total"]:
                continue
            part = next((c for c in item["contributions"] if c["pollutant"] == pollutant), None)
            shares.append(clean(part["share"]) if part else None)
            amounts.append([clean(part["amount"]) if part else None, item["unit"]])
        if all(share is None for share in shares):
            continue
        data.append({
            "type": "bar", "orientation": "h", "name": label, "x": shares, "y": names, "customdata": amounts,
            "marker": {"color": POLLUTANT_COLORS[pollutant], "line": {"color": SURFACE, "width": 2}},
            "hovertemplate": label + ": <b>%{x:.1f}%</b> (%{customdata[0]:,.4~g} %{customdata[1]})<extra></extra>",
        })
    figure = layout(title, "Share of the category total (%)", "", height=max(260, 56 * len(names) + 120),
                    barmode="stack", showlegend=True, bargap=0.35)
    figure["legend"]["traceorder"] = "normal"
    figure["xaxis"]["range"] = [0, 100]
    figure["xaxis"]["ticksuffix"] = "%"
    figure["yaxis"]["autorange"] = "reversed"
    figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    figure["barcornerradius"] = 0
    columns = ["Impact category", "Unit", "Total"] + [f"Share from {traci.POLLUTANTS[p]['label']} (%)"
                                                     for p in traci.POLLUTANT_ORDER]
    rows = []
    for item in totals:
        shares = {c["pollutant"]: c["share"] for c in item["contributions"]}
        rows.append([item["name"], item["unit"], clean(item["total"])]
                    + [clean(shares.get(p)) for p in traci.POLLUTANT_ORDER])
    note = "Each bar is one impact category. Categories are never added together because their units differ."
    return chart("impact_shares", title, data, figure, columns, rows, note)


IMPACT_CHART_LIMIT = 15


def impact_group_chart(rows, categories, choices, group_name):
    """The chosen impact category for the largest groups, split by pollutant (or per MWh)."""
    import traci

    category = next(((key, name, unit) for key, name, unit in categories if key == choices["isort"]), None)
    if category is None:
        return empty_chart("impact_groups", "Potential impacts by group", "No TRACI factors are loaded.")
    key, name, unit = category
    per_mwh = choices["per_mwh"]
    title = f"{name} by {group_name.lower()}" + (" per MWh" if per_mwh else "")
    field = "intensity" if per_mwh else "total"
    usable = [row for row in rows if row.get(key, {}).get(field) is not None]
    if not usable:
        return empty_chart("impact_groups", title, "No group has a value for this category.")
    shown = usable[:IMPACT_CHART_LIMIT]
    names = [text(row["group"]) for row in shown]
    value_unit = unit + (" per MWh" if per_mwh else "")

    if per_mwh:
        data = [{
            "type": "bar", "orientation": "h", "x": [clean(row[key]["intensity"]) for row in shown], "y": names,
            "marker": {"color": SERIES[0]},
            "hovertemplate": "%{y}<br><b>%{x:,.4~g} " + value_unit + "</b><extra></extra>",
        }]
        legend = False
    else:
        data = []
        pollutants = [p for p in traci.POLLUTANT_ORDER if p in shown[0][key]["contributions"]]
        for pollutant in pollutants:
            label = traci.POLLUTANTS[pollutant]["label"]
            data.append({
                "type": "bar", "orientation": "h", "name": label, "y": names,
                "x": [clean(row[key]["contributions"].get(pollutant)) for row in shown],
                "marker": {"color": POLLUTANT_COLORS[pollutant], "line": {"color": SURFACE, "width": 2}},
                "hovertemplate": label + ": <b>%{x:,.4~g} " + unit + "</b><extra>%{y}</extra>",
            })
        legend = len(pollutants) > 1
    figure = layout(title, f"{name} ({value_unit})", "", height=max(280, 34 * len(names) + 130),
                    barmode="stack", showlegend=legend, bargap=0.25)
    figure["legend"]["traceorder"] = "normal"
    figure["yaxis"]["autorange"] = "reversed"
    figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    if not per_mwh and len(data) > 1:
        figure["barcornerradius"] = 0
    columns = [group_name, f"{name} ({unit})", f"{name} per MWh ({unit}/MWh)", "Records used", "Records"]
    table = [[row["group"], clean(row.get(key, {}).get("total")), clean(row.get(key, {}).get("intensity")),
              row.get(key, {}).get("used"), row["records"]] for row in rows]
    note = f"The {len(shown)} highest of {len(usable)} groups."
    if not per_mwh and len(data) > 1:
        note += " Each bar is split by the pollutant it comes from."
    return chart("impact_groups", title, data, figure, columns, table, note)
