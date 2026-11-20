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
  - Colors follow the thing they stand for: CO2 is always blue, SO2 orange, NOx green,
    coal blue, gas orange, oil and other green. A filter never repaints them.
  - One y-axis per chart. Measures with different units are indexed or drawn as separate charts.
  - Every value on a chart is also in the table under it.
  - The title, a headline number and the legend sit in the card above the plot (templates/_chart.html),
    in the style of the charts in Apple's Health and Stocks apps; static/charts.js keeps them up to date.
"""

import html
import math

import numpy as np
import pandas as pd

import analysis
import explain

# ---------- Look ----------
#
# Charts in the style of Apple's own (Health, Stocks, Fitness). The title, a big headline number,
# a range picker and the legend sit in the card above the plot (templates/_chart.html), so the plot
# itself is only data: gray 11px axis text, dotted hairline grids, no frame, values on the right of
# time series, rounded bars with their names above them, lines that end in a ringed dot, and a
# gradient under single lines. Moving over a single-line chart shows that year in the headline.
#
# Series colors are tuned to Apple's blue and orange and checked with the dataviz palette validator
# (scripts/validate_palette.js): the first three pass the color-blind checks for every pair
# (scatter plots and maps use at most three), and all four pass for neighbors.

FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Helvetica Neue", Helvetica, Arial, sans-serif'
INK = "#1d1d1f"
INK_2 = "#6e6e73"
MUTED = "#86868b"
GRID = "#e8e8ed"
AXIS = "#d2d2d7"
SURFACE = "#ffffff"

# Categorical colors, always used in this order: CO2 / coal / group A, SO2 / gas / group B,
# NOx / oil and other, gross load
SERIES = ["#0071e3", "#f56300", "#00a86b", "#eda100"]
OTHER = "#a1a1a6"

POLLUTANT_COLORS = {"co2_mass": SERIES[0], "so2_mass": SERIES[1], "nox_mass": SERIES[2], "gross_load": SERIES[3]}
FAMILY_COLORS = {"Coal": SERIES[0], "Gas": SERIES[1], "Oil and other": SERIES[2]}

# One blue, light to dark, for amounts (maps)
SEQUENTIAL = [[0.0, "#d6e8fc"], [0.25, "#8ec0f5"], [0.5, "#3d94ec"], [0.75, "#0066cc"], [1.0, "#003a75"]]
# Red (negative) to gray (zero) to blue (positive), for correlations
DIVERGING = [[0.0, "#e34948"], [0.5, "#f5f5f7"], [1.0, "#0071e3"]]

# Bars: each row is this tall, with the name above the bar
BAR_ROW = 40
BAR_GAP = 0.52


def fill(color, alpha):
    """A series color as a see-through fill."""
    color = color.lstrip("#")
    return f"rgba({int(color[0:2], 16)},{int(color[2:4], 16)},{int(color[4:6], 16)},{alpha})"


def gradient(color, top=0.26):
    """A fill that fades from the series color under the line to nothing at the bottom (as in Stocks)."""
    return {"type": "vertical", "colorscale": [[0, fill(color, 0)], [1, fill(color, top)]]}


def axis(title, **extra):
    """A recessive axis: gray 11px ticks, dotted hairline grid, no frame."""
    settings = {
        "title": {"text": title, "font": {"color": MUTED, "size": 11}, "standoff": 10},
        "gridcolor": GRID,
        "griddash": "dot",
        "gridwidth": 1,
        "showline": False,
        "linecolor": AXIS,
        "linewidth": 1,
        "zeroline": False,
        "ticks": "",
        "ticklabelstandoff": 6,
        "tickfont": {"color": MUTED, "size": 11},
        "automargin": True,
    }
    settings.update(extra)
    return settings


def layout(title, x_title="", y_title="", height=380, **extra):
    """
    A figure layout. The title isn't drawn inside the plot: the card above it shows the title with the
    headline number, and the PNG download adds the title back (static/charts.js).
    """
    settings = {
        "font": {"family": FONT, "size": 12, "color": INK_2},
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "height": height,
        "margin": {"l": 8, "r": 8, "t": 14, "b": 8},
        "xaxis": axis(x_title),
        "yaxis": axis(y_title),
        "hoverlabel": {"bgcolor": "rgba(255,255,255,0.98)", "bordercolor": GRID,
                       "font": {"family": FONT, "color": INK, "size": 13}, "align": "left"},
        "legend": {"orientation": "h", "x": 0, "xanchor": "left", "y": 1.02, "yanchor": "bottom",
                   "font": {"color": INK_2, "size": 12}, "bgcolor": "rgba(0,0,0,0)", "itemsizing": "constant"},
        "barcornerradius": 6,
        "showlegend": False,
        "hovermode": "closest",
        "dragmode": "zoom",
        "modebar": {"bgcolor": "rgba(0,0,0,0)", "color": MUTED, "activecolor": INK},
    }
    settings.update(extra)
    if settings.get("showlegend"):
        settings["margin"] = dict(settings["margin"], t=44)
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


# ---------- The card above each chart ----------
#
# Optional fields a builder can add to its spec; templates/_chart.html draws them and
# static/charts.js keeps them up to date as the reader moves over the chart:
#   eyebrow   small gray line above the title ("Indexed, 2000 = 100")
#   headline  the big number: value, unit, context, delta (a change pill), note, eyebrow
#   legend    named color chips (click one to hide or show that series)
#   ranges    year-range buttons (5Y, 10Y, 20Y, All), as in Stocks
#   readout   which trace drives the headline while hovering, and how to describe it

def compact_parts(value):
    """406,123,456 -> ("406", "million"); 0.8442 -> ("0.8442", ""): a headline number and its word."""
    words = analysis.format_compact(value)
    for word in ("trillion", "billion", "million"):
        if words.endswith(" " + word):
            return words[:-len(word) - 1], word
    return words, ""


def short_number(value):
    """Labels on bars and axes, in the same style as the axis ticks: 1.23B, 456M, 12.3k, 87.5, 0.42."""
    if value is None:
        return "—"
    size = abs(value)
    for limit, letter in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if size >= limit * 0.9995:
            return f"{value / limit:.3g}{letter}".replace("-", "−")
    if size >= 0.01:
        return f"{value:.3g}".replace("-", "−")
    return analysis.format_number(value).replace("-", "−")


def percent_change(new, old):
    if new is None or old is None or old <= 0:
        return None
    return (new - old) / old * 100


def delta(pct, after):
    """A change pill: arrow, size and what it's compared with. Gray, not red or green: the reader decides."""
    if pct is None:
        return None
    direction = "up" if pct >= 0.05 else ("down" if pct <= -0.05 else "flat")
    return {"text": f"{abs(pct):,.1f}%", "dir": direction, "after": after}


def headline(value, unit, context="", change=None, note="", eyebrow=""):
    number, word = compact_parts(value)
    return {"value": number.replace("-", "−"), "unit": (word + " " + unit).strip(), "context": context,
            "delta": change, "note": note, "eyebrow": eyebrow}


def legend_item(name, color, value="", style="line", group=None):
    """A legend chip. group names the traces it shows and hides; "" makes it a plain label."""
    return {"name": name, "color": color, "value": value, "style": style, "group": name if group is None else group}


def end_dot(x, y, color, group):
    """The latest point of a line: a dot with a white ring."""
    return {"type": "scatter", "mode": "markers", "x": [x], "y": [y], "name": "", "showlegend": False,
            "legendgroup": group, "hoverinfo": "skip", "cliponaxis": False,
            "marker": {"size": 11, "color": color, "line": {"color": SURFACE, "width": 3}}}


def year_ranges(years):
    """Buttons above a yearly chart, like the range picker in Stocks."""
    span = years[-1] - years[0] + 1 if years else 0
    options = [{"label": f"{n}Y", "years": n} for n in (5, 10, 20) if span > n + 1]
    return options + [{"label": "All", "years": 0}] if options else []


def time_axes(figure, years, unified=True):
    """Years along a baseline with a crosshair; values on the right."""
    figure["xaxis"].update(showgrid=False, showline=True, dtick=year_step(years), tickformat="d",
                           range=[years[0] - 0.4, years[-1] + 0.4], showspikes=True, spikemode="across",
                           spikethickness=1, spikecolor=AXIS, spikedash="solid", spikesnap="data")
    figure["yaxis"].update(side="right", rangemode="tozero")
    figure["hovermode"] = "x unified" if unified else "x"
    figure["hoverdistance"] = -1
    figure["spikedistance"] = -1


def bar_rows(figure, names, values=None, show_axis=False, suffix="", axis_title=""):
    """
    Horizontal bars with each name above its bar (left-aligned, as on apple.com comparisons), so long
    facility names never squeeze the bars. Without show_axis, the value axis is hidden and each bar
    carries its own label (value_labels). Margins are fixed (no automargin) so every row is exactly
    BAR_ROW pixels and the names sit right above their bars.
    """
    count = len(names)
    bottom = (48 if axis_title else 30) if show_axis else 8
    figure["margin"] = dict(figure["margin"], l=4, t=22, r=8, b=bottom)
    figure["height"] = BAR_ROW * count + 22 + bottom
    figure["bargap"] = BAR_GAP
    if show_axis:
        # room for the first and last tick labels
        figure["margin"].update(l=14, r=22)
    figure["yaxis"].update(showgrid=False, showticklabels=False, autorange="reversed", title={"text": ""},
                           fixedrange=True, automargin=False, type="category")
    bar_half = BAR_ROW * (1 - BAR_GAP) / 2
    present = [v for v in (values or []) if v is not None]
    leftward = not show_axis and present and max(present) <= 0
    figure["annotations"] = list(figure.get("annotations", [])) + [{
        "x": 0, "xref": "x" if leftward else "paper", "y": name, "yref": "y", "text": name, "showarrow": False,
        "xanchor": "right" if leftward else "left", "yanchor": "bottom", "yshift": bar_half + 1,
        "align": "right" if leftward else "left", "font": {"color": INK, "size": 12},
    } for name in names]
    if show_axis:
        figure["xaxis"].update(ticksuffix=suffix, showline=False, automargin=False, fixedrange=True,
                               title={"text": axis_title, "font": {"color": MUTED, "size": 11}, "standoff": 8})
        return
    high = max(present + [0])
    low = min(present + [0])
    room = (high - low) * 0.2 or 1
    figure["xaxis"].update(showgrid=False, showticklabels=False, title={"text": ""}, fixedrange=True,
                           automargin=False, range=[low - (room if low < 0 else 0), high + room],
                           zeroline=low < 0, zerolinecolor=AXIS, zerolinewidth=1)


def value_labels(values, formatter=None):
    """Short labels at the end of each bar, in the text color (never the bar color)."""
    formatter = formatter or short_number
    return {"text": [formatter(v) if v is not None else "" for v in values], "textposition": "outside",
            "cliponaxis": False, "constraintext": "none", "textfont": {"color": INK, "size": 12}}


def text(value):
    """Facility and unit names go into tooltips; escape them so they show as plain text."""
    return html.escape(str(value), quote=False)


def unit_of(key):
    return analysis.VARIABLES[key]["unit"]


def log_axis(settings, low=None, high=None):
    """
    A log axis labeled only at powers of ten (10, 100, 1k, 10k ...), so it stays quiet. When the values
    (low to high) span less than two powers of ten, Plotly picks in-between labels instead.
    """
    settings["type"] = "log"
    if low is None or high is None or low <= 0 or high / low >= 100:
        settings["dtick"] = 1


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
    return "%{y:,.4~r} " + unit


def year_step(years):
    """Year axis tick spacing: every year for short spans, every 2 or 5 years for long ones."""
    span = (max(years) - min(years)) if len(years) else 0
    if span <= 12:
        return 1
    if span <= 24:
        return 2
    return 5


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
    title = "Emissions and generation over time"
    years = selection_years(frame)
    if len(years) < 2:
        return empty_chart("indexed", title, "This selection covers one year, so there is no trend to show.")

    keys = ["co2_mass", "so2_mass", "nox_mass", "gross_load"]
    names = {"co2_mass": "CO2", "so2_mass": "SO2", "nox_mass": "NOx", "gross_load": "Gross load"}
    totals = frame.groupby("year")[keys].sum(min_count=1).reindex(years)

    data, dots, annotations, legend = [], [], [], []
    details = {}
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
        color = POLLUTANT_COLORS[key]
        data.append({
            "type": "scatter", "mode": "lines", "name": names[key], "legendgroup": names[key],
            "x": years, "y": [clean(v) for v in index],
            "customdata": [[clean(v)] for v in series],
            "line": {"color": color, "width": 3},
            "hovertemplate": f"{names[key]}  <b>%{{y:.1f}}</b>  (total %{{customdata[0]:,.0f}} {unit_of(key)})"
                             "<extra></extra>",
        })
        for point, year in enumerate(years):
            if pd.notna(index[year]):
                details[f"{len(data) - 1}:{point}"] = explain.index_detail(
                    names[key], year, float(series[year]), float(series[base_year]), base_year, float(index[year]),
                    unit_of(key))
        last = next((year for year in reversed(years) if pd.notna(index[year])), None)
        if last is not None:
            dots.append(end_dot(last, clean(index[last]), color, names[key]))
            annotations.append({"x": last, "y": float(index[last]), "text": f"<b>{names[key]}</b>",
                                "showarrow": False, "xanchor": "left", "xshift": 12, "yanchor": "middle",
                                "font": {"color": INK, "size": 12}})
            legend.append(legend_item(names[key], color, signed_percent(float(index[last]) - 100)
                                      + f" since {base_year}"))

    rows = []
    for year in years:
        rows.append([year] + [clean(totals.loc[year, k]) for k in keys] + [clean(indexes[k][year]) for k in keys])

    spread_labels(annotations)
    figure = layout(title, "", "", height=360, annotations=annotations)
    time_axes(figure, years)
    figure["yaxis"].update(side="left", rangemode="normal")
    figure["shapes"] = [{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 100, "y1": 100, "layer": "below",
                         "line": {"color": MUTED, "width": 1, "dash": "dash"}}]
    figure["margin"]["r"] = 92
    note = ("Each line is the yearly total for the selected records divided by that line's first-year total, so "
            "the dashed line at 100 is where every line starts. Totals also change when units start or stop "
            "reporting.")
    spec = chart("indexed", title, data + dots, figure, columns, rows, note)
    spec["eyebrow"] = "Indexed to the first year = 100"
    spec["legend"] = legend
    spec["details"] = details
    spec["about"] = explain.about(
        "How the yearly totals of CO2, SO2, NOx and gross load changed, all on one scale.",
        "For each measure, every year's total over the selected records is divided by the same measure's total in "
        "its first year with data, then multiplied by 100. A value of 80 means 20% below that first year; 150 "
        "means 50% above it.",
        "The four measures have different units (short tons and MWh) and very different sizes, so one axis in "
        "real units would flatten SO2 and NOx, and two axes would invite false comparisons. Indexing puts every "
        "line on the same scale, starting together at 100.",
        "Lines under the dashed line at 100 are below their first year. When emissions fall faster than gross load, "
        "each MWh is being generated with less pollution.",
        explain.source_text(frame))
    return spec


def signed_percent(value):
    if value is None:
        return "—"
    if abs(value) < 0.5:
        return "0%"
    return ("+" if value > 0 else "−") + f"{abs(value):,.0f}%"


def split_words(split):
    """'SO2 control' -> 'SO2 control', 'Fuel family' -> 'fuel family'."""
    return lower_first(SPLITS[split])


def series_drill(split, name):
    """Explore filters for one line of a split trend, or None when Explore can't pick out exactly that group."""
    if split == "none":
        return {}
    if split in ("so2_control", "nox_control") and name.startswith("No "):
        return {split: "none"}
    return None


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

    single = len(series) == 1
    changes = item["group"] != "Year-over-year change"
    data, dots, legend = [], [], []
    details = {}
    columns = ["Year"]
    values_by_series = []
    for name, part, color in series:
        found = explain.parts(part, key, part["year"])
        filter_for = series_drill(split, name)
        previous = None
        for point, year in enumerate(years):
            if year not in found.index or pd.isna(found.loc[year, "value"]):
                previous = None
                continue
            row = found.loc[year]
            facts = []
            if changes and previous is not None and previous[1] != 0:
                facts.append([f"Change from {previous[0]}",
                              explain.signed_percent((row["value"] - previous[1]) / abs(previous[1]) * 100)])
            drill = None if filter_for is None else dict(filter_for, reporting_year=int(year))
            details[f"{len(data)}:{point}"] = explain.aggregate_detail(
                key, row, str(year), "" if single else name, drill, facts)
            previous = (year, float(row["value"]))
        table = analysis.aggregate(part, key, part["year"]).reindex(years)
        values = [clean(v) for v in table["value"]]
        counts = [0 if pd.isna(c) else int(c) for c in table["records"]]
        values_by_series.append(values)
        columns.append(f"{name}: {value_title(key)}")
        trace = {
            "type": "scatter", "mode": "lines", "name": name, "legendgroup": name, "x": years, "y": values,
            "customdata": [[c] for c in counts],
            "line": {"color": color, "width": 3},
            "hovertemplate": f"{text(name)}  <b>%{{y:,.4~r}} {item['unit']}</b>  (%{{customdata[0]:,}} records)"
                             "<extra></extra>",
            "connectgaps": False,
        }
        if single:
            # As in Stocks: a gradient under the line, and the hovered year shown in the headline above
            trace.update(fill="tozeroy", fillgradient=gradient(color), hoverinfo="none")
            del trace["hovertemplate"]
        data.append(trace)
        present = [(year, value) for year, value in zip(years, values) if value is not None]
        if present:
            dots.append(end_dot(present[-1][0], present[-1][1], color, name))
            legend.append(legend_item(name, color, f"{short_number(present[-1][1])} in {present[-1][0]}"))

    rows = [[year] + [values[i] for values in values_by_series] for i, year in enumerate(years)]
    figure = layout(title, "", "", height=340)
    time_axes(figure, years, unified=not single)
    if any(value is not None and value < 0 for values in values_by_series for value in values):
        figure["yaxis"].update(rangemode="normal", zeroline=True, zerolinecolor=AXIS)
    word = analysis.aggregate_label(key)
    note = {
        "Overall ratio": "Each point divides the year's total of the numerator by the total of the denominator.",
        "Total": "Each point is the year's total over the selected records.",
        "Mean": "Each point is the year's average over the selected records.",
    }[word]
    spec = chart("trend", title, data + dots, figure, columns, rows, note)
    spec["details"] = details
    spec["about"] = explain.about(
        f"{word if word != 'Overall ratio' else 'The overall'} {lower_first(item['label'])} for each year of the "
        f"selection{'' if single else ', one line per ' + split_words(split)}.",
        explain.how_aggregated(key) + " " + item["definition"],
        "A line shows direction and turning points over time, and the years are evenly spaced, so slopes can be "
        "compared directly. One measure, one axis.",
        ("Move along the line to see each year in the headline; the pill compares it with the first year shown. "
         "Use 5Y, 10Y or 20Y to look at recent years." if single else
         "Each color is one group; select a name in the legend to hide or show its line."),
        explain.source_text(frame))
    eyebrow = "Overall" if word == "Overall ratio" else word
    if not single:
        spec["eyebrow"] = f"{eyebrow}, by {split_words(split)}"
        spec["legend"] = legend
        return spec

    present = [(year, value) for year, value in zip(years, values_by_series[0]) if value is not None]
    if not present:
        return spec
    first_year, first = present[0]
    last_year, last = present[-1]
    peak_year, peak = max(present, key=lambda pair: pair[1])
    spec["headline"] = headline(
        last, item["unit"], f"In {last_year}",
        delta(percent_change(last, first), f"since {first_year}") if changes else None,
        f"Peak: {analysis.format_compact(peak)} in {peak_year}" if peak_year not in (first_year, last_year) else "",
        eyebrow)
    spec["readout"] = {"trace": 0, "unit": item["unit"], "delta": changes, "count": "records"}
    spec["ranges"] = year_ranges([year for year, _ in present])
    return spec


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
    names = [text(n) for n in shown.index]
    values = [clean(v) for v in shown["value"]]
    data = [dict({
        "type": "bar", "orientation": "h", "x": values, "y": names,
        "customdata": [[int(r)] for r in shown["records"]],
        "marker": {"color": SERIES[0]},
        "hovertemplate": "%{y}<br><b>%{x:,.4~r} " + item["unit"] + "</b>  (%{customdata[0]:,} records)<extra></extra>",
    }, **value_labels(values))]
    figure = layout(title)
    bar_rows(figure, names, values)

    columns = [group_name, value_title(key), "Records"]
    rows = [[name, clean(row["value"]), int(row["records"])] for name, row in table.iterrows()]
    found = explain.parts(frame, key, analysis.group_labels(frame, group))
    total = float(table["value"].sum())
    details = {}
    for point, name in enumerate(shown.index):
        facts = [["Rank", f"{point + 1} of {len(table)}"]]
        if item["group"] == "Measured" and total > 0:
            facts.append(["Share of the selection's total", f"{found.loc[name, 'value'] / total * 100:.1f}%"])
        details[f"0:{point}"] = explain.aggregate_detail(key, found.loc[name], str(name), group_name,
                                                         explain.drill_for(group, name), facts)
    note = f"Highest {len(shown)} of {len(table)} groups shown; the table and download have all of them."
    if len(table) <= BAR_LIMIT:
        note = f"All {len(table)} groups, highest first."
    spec = chart("bars", title, data, figure, columns, rows, note)
    spec["details"] = details
    spec["about"] = explain.about(
        f"{value_title(key).rsplit(' (', 1)[0]} for each {group_name.lower()} in the selection, highest first.",
        explain.how_aggregated(key) + " " + item["definition"],
        "Bars compare amounts across categories: length is easy to judge, and sorting puts the ranking in reading "
        "order. Names sit above the bars so long ones never squeeze them.",
        "Each bar's number is its value; select a bar for the records and calculation behind it.",
        explain.source_text(frame))
    word = analysis.aggregate_label(key)
    top = headline(values[0], item["unit"], f"{shown.index[0]}, the highest of {len(table)}",
                   eyebrow=f"Highest {group_name.lower()}")
    if word == "Total" and len(table) > 1 and total > 0 and values[0] > 0:
        top["note"] = f"{values[0] / total * 100:.1f}% of the selection's total"
    spec["headline"] = top
    return spec


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
    switched = scale == "log" and bool((values < 0).any())
    if switched:
        scale = "linear"   # changes can be negative, which a log scale can't show
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
    median = float(values.median())

    # On a log scale every bin is equally wide in powers of ten, so the bars are drawn at log10 positions
    # on a plain axis whose labels are written back as real values (100, 1K, 10K, ...). That keeps the
    # bars rounded and evenly spaced, which a log axis can't do.
    def position(value):
        return math.log10(value) if scale == "log" else value

    lefts = [position(e) for e in edges[:-1]]
    rights = [position(e) for e in edges[1:]]
    data = [{
        "type": "bar", "x": [(a + b) / 2 for a, b in zip(lefts, rights)], "y": [int(c) for c in counts],
        "width": [(b - a) * 0.8 for a, b in zip(lefts, rights)],
        "customdata": ranges, "marker": {"color": SERIES[0]},
        "hovertemplate": "%{customdata[0]:,.4~r} to %{customdata[1]:,.4~r} " + item["unit"]
                         + "<br><b>%{customdata[2]:,} records</b><extra></extra>",
    }]
    figure = layout(title, f"{item['label']} ({item['unit']}{', log scale' if scale == 'log' else ''})", "",
                    height=320, barcornerradius=3)
    figure["xaxis"].update(showgrid=False, showline=True)
    figure["yaxis"].update(side="right", tickformat="~s")
    if scale == "log":
        low, high = math.floor(lefts[0]), math.ceil(rights[-1])
        ticks = [k for k in range(low, high + 1) if lefts[0] - 0.05 <= k <= rights[-1] + 0.05]
        if len(ticks) < 2:
            ticks = [lefts[0], rights[-1]]
        figure["xaxis"].update(tickvals=ticks, ticktext=[short_number(10 ** k) for k in ticks],
                               range=[lefts[0] - 0.04, rights[-1] + 0.04])
    marker = position(median)
    figure["shapes"] = [{"type": "line", "xref": "x", "yref": "paper", "x0": marker, "x1": marker, "y0": 0, "y1": 1,
                         "line": {"color": INK, "width": 1.5, "dash": "dot"}}]
    figure["annotations"] = [{"x": marker, "y": 1, "xref": "x", "yref": "paper", "yanchor": "bottom",
                              "xanchor": "left", "xshift": 5, "showarrow": False,
                              "text": f"Median {short_number(median)}", "font": {"color": INK, "size": 11}}]
    figure["margin"]["t"] = 26

    note = f"{len(values):,} records in {bins} bins; the dotted line marks the median."
    if excluded:
        note += f" {excluded:,} records with a value of 0 are left out because a log scale can't show 0."
    if switched:
        note += " Some values are below 0, which a log scale can't show, so this chart uses a linear scale."
    columns = [f"From ({item['unit']})", f"To ({item['unit']})", "Records"]
    spec = chart("histogram", title, data, figure, columns, ranges, note)
    spec["details"] = {f"0:{i}": explain.bin_detail(key, ranges[i][0], ranges[i][1], ranges[i][2], len(values), scale,
                                                     i, bins) for i in range(len(ranges))}
    spec["about"] = explain.about(
        f"How many records have each value of {item['label']}: every bar counts the records in one range.",
        f"The range from the smallest to the largest value is cut into {bins} bins of equal width"
        + (" in powers of ten (a log scale)" if scale == "log" else "") + ", and the records in each bin are "
        "counted. The dotted line is the median: half of the records are below it, half above.",
        "A histogram shows the shape of the data: where most records fall, whether there are several groups, and "
        "how long the tail of very large values is. Emissions are heavily skewed (a few large plants emit far more "
        "than most units), so a log scale spreads small and large values evenly instead of crowding most records "
        "into the first bar.",
        "Taller bars mean more records in that range. Each label on the axis is ten times the one before on a log "
        "scale.",
        explain.source_text(frame))
    busiest = max(range(len(counts)), key=lambda index: counts[index])
    spec["headline"] = headline(median, item["unit"], f"half of the {len(values):,} records are above it", eyebrow="Median",
                                note=f"Most common: {short_number(ranges[busiest][0])} to "
                                     f"{short_number(ranges[busiest][1])} {item['unit']}")
    return spec


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


def box_trace(name, x, stats, color):
    """Slim boxes in the series color with a solid median, as in Health's range charts."""
    return {
        "type": "box", "name": name, "x": x,
        "q1": [s["q1"] for s in stats], "median": [s["median"] for s in stats], "q3": [s["q3"] for s in stats],
        "lowerfence": [s["lower"] for s in stats], "upperfence": [s["upper"] for s in stats],
        "mean": [s["mean"] for s in stats],
        "boxpoints": False, "width": 0.42, "whiskerwidth": 0, "marker": {"color": color},
        "line": {"color": color, "width": 1.5}, "fillcolor": fill(color, 0.16),
    }


def box(frame, key, group, scale="log"):
    item = analysis.VARIABLES[key]
    group_name = analysis.GROUPS[group]
    title = f"Spread of {lower_first(item['label'])} within each {group_name.lower()}"
    data_frame = pd.DataFrame({"group": analysis.group_labels(frame, group), "value": frame[key]}).dropna()
    data_frame = data_frame[data_frame["group"] != analysis.NOT_REPORTED]
    switched = scale == "log" and bool((data_frame["value"] < 0).any())
    if switched:
        scale = "linear"   # changes can be negative, which a log scale can't show
    if scale == "log":
        data_frame = data_frame[data_frame["value"] > 0]
    counts = data_frame.groupby("group").size()
    counts = counts[counts >= 5].sort_values(ascending=False)
    if counts.empty:
        return empty_chart("box", title, "No group has at least 5 values to draw a box plot.")
    names = list(counts.index[:BOX_LIMIT])
    stats = [box_stats(data_frame.loc[data_frame["group"] == name, "value"]) for name in names]

    data = [box_trace(item["label"], [text(n) for n in names], stats, SERIES[0])]
    figure = layout(title, "", "", height=340)
    if scale == "log":
        log_axis(figure["yaxis"], min(s["lower"] for s in stats), max(s["upper"] for s in stats))
    figure["xaxis"].update(showgrid=False, showline=True, tickfont={"color": INK, "size": 12}, type="category")
    figure["yaxis"].update(side="right")
    columns = [group_name, "Records", "Minimum", "Lower whisker", "Q1", "Median", "Mean", "Q3", "Upper whisker",
               "Maximum", "Outliers beyond whiskers"]
    rows = [[n, s["count"], s["min"], s["lower"], s["q1"], s["median"], s["mean"], s["q3"], s["upper"], s["max"],
             s["outliers"]] for n, s in zip(names, stats)]
    note = (f"The {len(names)} largest groups, in {item['unit']}{' on a log scale' if scale == 'log' else ''}. "
            "Boxes run from Q1 to Q3 with the median inside; whiskers reach the furthest values within 1.5 × IQR. "
            "Points beyond the whiskers are counted in the table, not drawn.")
    if scale == "log":
        note += " Values of 0 are left out on the log scale."
    if switched:
        note += " Some values are below 0, which a log scale can't show, so this chart uses a linear scale."
    spec = chart("box", title, data, figure, columns, rows, note)
    spec["detail_key"] = "x"
    spec["details"] = {text(name): explain.box_detail(name, stats[index], item["label"], item["unit"],
                                                       explain.drill_for(group, name), f"{group_name} · spread")
                       for index, name in enumerate(names)}
    spec["about"] = explain.about(
        f"How the {item['label']} of individual records spreads out within each of the largest groups.",
        "For each group, the records' values are sorted. The box runs from the 25th percentile (Q1) to the 75th "
        "(Q3), so it holds the middle half; the line inside is the median and the dashed line the mean. The "
        "whiskers reach the furthest values within 1.5 × the box's height.",
        "One average per group hides how different the records inside it are. A box plot shows the middle, the "
        "spread and the extremes of every group side by side.",
        "A tall box means the group's records vary a lot. A median far below the mean means a few very large "
        "values pull the average up.",
        explain.source_text(frame))
    top = max(range(len(stats)), key=lambda index: stats[index]["median"])
    spec["headline"] = headline(stats[top]["median"], item["unit"], f"median of {names[top]}",
                                eyebrow="Highest median")
    return spec


# ---------- Relationships ----------

def strength(r):
    size = abs(r)
    if size < 0.2:
        return "Little or no relationship"
    word = "very strong" if size >= 0.9 else "strong" if size >= 0.7 else "moderate" if size >= 0.4 else "weak"
    return f"{word.capitalize()}: {'they rise together' if r > 0 else 'one falls as the other rises'}"


def scatter(frame, x_key, y_key, scale="log"):
    x_item = analysis.VARIABLES[x_key]
    y_item = analysis.VARIABLES[y_key]
    title = f"{y_item['label']} against {lower_first(x_item['label'])}"
    data_frame = pd.DataFrame({
        "x": frame[x_key], "y": frame[y_key],
        "family": frame["primary_fuel"].map(analysis.fuel_family),
        "name": analysis.unit_labels(frame), "year": frame["year"],
        "facility": frame["facility_id"], "unit": frame["unit_id"],
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

    data, legend = [], []
    for family in analysis.FUEL_FAMILIES:
        part = shown[shown["family"] == family]
        if part.empty:
            continue
        data.append({
            "type": "scattergl", "mode": "markers", "name": family, "legendgroup": family,
            "x": [float(v) for v in part["x"]], "y": [float(v) for v in part["y"]],
            "text": [f"{text(n)}, {int(y)}" for n, y in zip(part["name"], part["year"])],
            "customdata": [[None if pd.isna(f) else int(f), "" if pd.isna(u) else str(u), int(y)]
                           for f, u, y in zip(part["facility"], part["unit"], part["year"])],
            "marker": {"size": 7, "color": FAMILY_COLORS[family], "opacity": 0.7,
                       "line": {"color": SURFACE, "width": 0.5}},
            "hovertemplate": "<b>%{text}</b><br>" + x_item["label"] + "  %{x:,.4~r} " + x_item["unit"]
                             + "<br>" + y_item["label"] + "  %{y:,.4~r} " + y_item["unit"]
                             + "<extra>" + family + "</extra>",
        })
        legend.append(legend_item(family, FAMILY_COLORS[family],
                                  f"{int((data_frame['family'] == family).sum()):,} records", "dot"))
    figure = layout(title, f"{x_item['label']} ({x_item['unit']})", f"{y_item['label']} ({y_item['unit']})",
                    height=400)
    if scale == "log":
        log_axis(figure["xaxis"], float(data_frame["x"].min()), float(data_frame["x"].max()))
        log_axis(figure["yaxis"], float(data_frame["y"].min()), float(data_frame["y"].max()))
    figure["xaxis"].update(showline=True)

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
    spec = chart("scatter", title, data, figure, columns, rows, note)
    spec["legend"] = legend
    spec["detail_template"] = {
        "kind": "record",
        "x": {"label": x_item["label"], "unit": x_item["unit"], "definition": x_item["definition"]},
        "y": {"label": y_item["label"], "unit": y_item["unit"], "definition": y_item["definition"]},
    }
    spec["about"] = explain.about(
        f"Each dot is one record (one unit in one year): its {x_item['label']} across and its {y_item['label']} up, "
        "colored by fuel family.",
        "Both values come straight from the record (or from its own reported values, for derived indicators). The "
        "correlations in the headline use every record with both values; Spearman compares their ranks, Pearson "
        "the values themselves.",
        "A scatter plot shows whether two measurements rise together, one record at a time, including the records "
        "that don't follow the pattern. Coal, gas and oil burn differently, so coloring by fuel separates lines "
        "that would otherwise blur together.",
        "Dots along a rising band mean the two rise together. Separate bands by color mean the relationship "
        "differs by fuel." + (" Both axes are log scales." if scale == "log" else ""),
        explain.source_text(frame))
    if pd.notna(spearman):
        spec["headline"] = {"value": f"{spearman:.2f}".replace("-", "−"), "unit": "Spearman correlation",
                            "context": strength(spearman), "delta": None, "eyebrow": "Relationship",
                            "note": f"Pearson {pearson:.2f}".replace("-", "−") if pd.notna(pearson) else ""}
    return spec


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
    strongest = None
    for i in range(len(keys)):
        for j in range(len(keys)):
            r = z[i][j]
            if i != j and r is not None and abs(r) >= 0.7:
                annotations.append({"x": names[j], "y": names[i], "text": f"{r:.2f}".replace("-", "−"),
                                    "showarrow": False,
                                    "font": {"color": SURFACE if abs(r) >= 0.85 else INK, "size": 11}})
            if i < j and r is not None and (strongest is None or abs(r) > abs(strongest[0])):
                strongest = (r, names[i], names[j])
    data = [{
        "type": "heatmap", "x": names, "y": names, "z": z, "customdata": counts,
        "zmin": -1, "zmax": 1, "zmid": 0, "colorscale": DIVERGING, "xgap": 3, "ygap": 3,
        "colorbar": {"title": {"text": "r", "side": "top", "font": {"color": MUTED, "size": 11}}, "thickness": 8,
                     "outlinewidth": 0, "tickfont": {"color": MUTED, "size": 11}, "len": 0.6,
                     "tickvals": [-1, -0.5, 0, 0.5, 1], "ticktext": ["−1", "−0.5", "0", "0.5", "1"]},
        "hovertemplate": "%{y} and %{x}<br><b>r = %{z:.2f}</b>  (%{customdata:,} records)<extra></extra>",
    }]
    figure = layout(title, "", "", height=480, annotations=annotations)
    figure["yaxis"]["autorange"] = "reversed"
    figure["xaxis"]["tickangle"] = -40
    for name in ("xaxis", "yaxis"):
        figure[name].update(showgrid=False, showline=False, tickfont={"color": INK_2, "size": 11})
    columns = ["Variable"] + names
    rows = [[names[i]] + z[i] for i in range(len(keys))]
    note = (f"Each pair uses the records that have both values (at least {CORRELATION_MINIMUM}). "
            "1 means two variables rise together perfectly, −1 that one falls as the other rises, 0 no "
            "relationship. Values of 0.7 or more either way are labeled. Correlation is not causation.")
    if method == "spearman":
        note += " Spearman compares ranks, so a few very large plants don't dominate it."
    spec = chart("correlation", title, data, figure, columns, rows, note)
    spec["detail_key"] = "yx"
    spec["details"] = {f"{names[i]}|{names[j]}": explain.correlation_detail(names[j], names[i], z[i][j], counts[i][j],
                                                                            method)
                       for i in range(len(keys)) for j in range(len(keys)) if z[i][j] is not None}
    spec["about"] = explain.about(
        "How strongly each pair of measured and derived variables moves together, for every pair at once.",
        ("Spearman correlation ranks each variable's values and correlates the ranks" if method == "spearman" else
         "Pearson correlation measures how closely the two variables follow a straight line")
        + f", using the records that have both values (at least {CORRELATION_MINIMUM}). It runs from −1 (one "
        "falls as the other rises) through 0 (no relationship) to 1 (they rise together).",
        "A heat map shows all the pairs in one view, with color for direction (blue together, red opposite) and "
        "strength (darker is stronger), so the strong relationships stand out.",
        "Read across a row and down a column to find a pair. The table is symmetric, and the diagonal is 1.",
        explain.source_text(frame))
    if strongest:
        spec["headline"] = {"value": f"{strongest[0]:.2f}".replace("-", "−"), "unit": "correlation",
                            "context": f"{strongest[1]} and {strongest[2]}", "delta": None, "note": "",
                            "eyebrow": "Strongest pair"}
    return spec


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

    labels = analysis.unit_labels(frame) if level == "unit" else analysis.group_labels(frame, "facility")
    found = explain.parts(frame, key, labels)
    ids = pd.DataFrame({"label": labels, "facility": frame["facility_id"], "unit": frame["unit_id"]}) \
        .drop_duplicates("label").set_index("label")

    def drill(name):
        if name not in ids.index or pd.isna(ids.at[name, "facility"]):
            return {}
        filters = {"epa_facility_id": int(ids.at[name, "facility"])}
        if level == "unit" and pd.notna(ids.at[name, "unit"]):
            filters["epa_unit_id"] = str(ids.at[name, "unit"])
        return filters

    def bar_chart(chart_id, title, part, note, eyebrow):
        names = [text(n) for n in part.index]
        values = [clean(v) for v in part["value"]]
        data = [dict({
            "type": "bar", "orientation": "h", "x": values, "y": names,
            "customdata": [[clean(g)] for g in part["gross_load"]],
            "marker": {"color": SERIES[0]},
            "hovertemplate": "%{y}<br><b>%{x:,.4~r} " + item["unit"]
                             + "</b><br>Gross load %{customdata[0]:,.0f} MWh<extra></extra>",
        }, **value_labels(values))]
        figure = layout(title)
        bar_rows(figure, names, values)
        columns = ["Rank", "Unit" if level == "unit" else "Facility", value_title(key), "Gross load (MWh)", "Records"]
        rows = []
        for rank, (name, row) in enumerate(part.iterrows(), start=1):
            rows.append([rank, name, clean(row["value"]), clean(row["gross_load"]), int(row["records"])])
        spec = chart(chart_id, title, data, figure, columns, rows, note)
        pool = len(table) if chart_id == "rank_high" else len(lowest_pool)
        spec["details"] = {
            f"0:{point}": explain.aggregate_detail(
                key, found.loc[name], str(name), "Unit" if level == "unit" else "Facility", drill(name),
                [["Rank", f"{point + 1} {'highest' if chart_id == 'rank_high' else 'lowest'} of {pool:,}"],
                 ["Gross load", explain.with_unit(clean(part.loc[name, "gross_load"]), "MWh")]])
            for point, name in enumerate(part.index)}
        spec["about"] = explain.about(
            f"The {noun} at the {'top' if chart_id == 'rank_high' else 'bottom'} of the ranking by "
            f"{value_title(key).rsplit(' (', 1)[0].lower()}.",
            explain.how_aggregated(key) + f" Each of the {noun} is ranked by that value."
            + (f" Only {noun} with at least {min_load:,.0f} MWh of gross load are ranked, so tiny ones with "
               "unusual ratios don't top the list by chance." if item["ratio"] else "")
            + (" Zeros are left out of the lowest, so they show the lowest that reported any." if item["additive"]
               and chart_id == "rank_low" else ""),
            "Horizontal bars leave room for long names and make the order easy to read from top to bottom.",
            "Select a bar for the records behind it and a link to them in Explore.",
            explain.source_text(frame))
        if len(part):
            spec["headline"] = headline(values[0], item["unit"], str(part.index[0]), eyebrow=eyebrow)
        return spec


    high = table.head(RANK_COUNT)
    low = lowest_pool.tail(RANK_COUNT).iloc[::-1]
    return (bar_chart("rank_high", high_title, high, f"Out of {len(table):,} {noun}." + common,
                      f"Highest of {len(table):,}"),
            bar_chart("rank_low", low_title, low, f"Lowest first, out of {len(lowest_pool):,} {noun}." + low_note
                      + common, f"Lowest of {len(lowest_pool):,}"))


# ---------- Maps ----------

def map_colorbar(unit):
    """A thin horizontal color key centered under the map."""
    return {"title": {"text": unit, "side": "top", "font": {"color": MUTED, "size": 11}}, "orientation": "h",
            "x": 0.5, "xanchor": "center", "y": 0, "yanchor": "top", "ypad": 6, "len": 0.42, "thickness": 6,
            "outlinewidth": 0, "tickfont": {"color": MUTED, "size": 11}}


def map_layout(title, land):
    figure = layout(title, height=400)
    figure["geo"] = {"scope": "usa", "bgcolor": SURFACE, "lakecolor": SURFACE, "showlakes": False,
                     "showland": True, "landcolor": land, "subunitcolor": SURFACE, "subunitwidth": 1.5,
                     "countrycolor": SURFACE, "projection": {"type": "albers usa"}}
    figure["margin"] = {"l": 0, "r": 0, "t": 4, "b": 58}
    figure["dragmode"] = False
    return figure


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
        "colorscale": SEQUENTIAL, "marker": {"line": {"color": SURFACE, "width": 1.5}},
        "colorbar": map_colorbar(item["unit"]),
        "hovertemplate": "<b>%{text}</b><br>%{z:,.4~r} " + item["unit"] + "  (%{customdata[0]:,} records)<extra></extra>",
    }]
    figure = map_layout(title, "#f5f5f7")
    columns = ["State", "State code", value_title(key), "Records"]
    rows = [[name, code, clean(v), int(r)] for name, code, v, r in zip(names, codes, table["value"], table["records"])]
    rows.sort(key=lambda row: -(row[2] or 0))
    note = (f"{analysis.aggregate_label(key)} for each state with records in the selection. Darker means higher; "
            "states in light gray have no records.")
    spec = chart("state_map", title, data, figure, columns, rows, note)
    found = explain.parts(frame, key, frame["state"].fillna(analysis.NOT_REPORTED))
    order = sorted(codes, key=lambda code: -(found.loc[code, "value"] or 0))
    spec["details"] = {f"0:{point}": explain.aggregate_detail(
        key, found.loc[code], f"{name} ({code})", "State", {"state": code},
        [["Rank", f"{order.index(code) + 1} of {len(codes)}"]]) for point, (code, name) in enumerate(zip(codes, names))}
    spec["about"] = explain.about(
        f"{value_title(key).rsplit(' (', 1)[0]} for each state with records in the selection.",
        explain.how_aggregated(key) + " Each state's records are combined that way; darker blue means higher.",
        "A map shows where values are concentrated, which a list of states can't show at a glance. One blue from "
        "light to dark keeps the order clear without suggesting good or bad.",
        "States in light gray have no records in the selection. Select a state for its numbers.",
        explain.source_text(frame))
    spec["headline"] = headline(rows[0][2], item["unit"], rows[0][0],
                                eyebrow=f"Highest of {len(rows)} state{'' if len(rows) == 1 else 's'}")
    return spec


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
    found = explain.parts(frame, key, labels)
    # For the detail drawn on click: id, records, records used, total (or numerator), denominator
    facility_numbers = []
    for i in shown.index:
        row = found.loc[i]
        first = row["num"] if item["ratio"] else row["value"]
        second = row["den"] if item["ratio"] else None
        facility_numbers.append([int(i), int(row["records"]), int(row["used"]), clean(first), clean(second)])
    data = [{
        "type": "scattergeo", "mode": "markers",
        "lat": [places[int(i)][0] for i in shown.index], "lon": [places[int(i)][1] for i in shown.index],
        "text": names, "customdata": facility_numbers,
        "marker": {"size": 9, "color": [clean(v) for v in shown["value"]], "colorscale": SEQUENTIAL,
                   "line": {"color": SURFACE, "width": 1.5}, "opacity": 0.95,
                   "colorbar": map_colorbar(item["unit"])},
        "hovertemplate": "<b>%{text}</b><br>%{marker.color:,.4~r} " + item["unit"] + "<extra></extra>",
    }]
    figure = map_layout(title, "#f0f0f2")
    figure["geo"]["subunitcolor"] = "#d2d2d7"
    figure["geo"]["subunitwidth"] = 0.75

    columns = ["Facility ID", "Facility", "Latitude", "Longitude", value_title(key), "Gross load (MWh)"]
    rows = [[int(i), info.at[i, "facility_name"], places[int(i)][0], places[int(i)][1], clean(row["value"]),
             clean(row["gross_load"])] for i, row in shown.iloc[::-1].iterrows()]
    note = f"{len(shown):,} facilities; the highest values are drawn on top."
    if len(with_place) > len(shown):
        note += (f" The {MAP_FACILITY_LIMIT:,} with the highest "
                 f"{'gross load' if item['ratio'] else item['label']} are drawn.")
    if without:
        note += f" {without:,} facilities have no stored location and are not drawn."
    if item["ratio"]:
        note += f" Facilities with under {min_load:,.0f} MWh of gross load are left out."
    spec = chart("facility_map", title, data, figure, columns, rows, note)
    parts = explain.RATIO_PARTS.get(key)
    spec["detail_template"] = {
        "kind": "facility", "label": item["label"], "unit": item["unit"], "ratio": item["ratio"],
        "kicker": explain.kicker_for(key),
        "num": [parts[0], parts[1]] if parts else None, "den": [parts[2], parts[3]] if parts else None,
        "scale": list(parts[4]) if parts and parts[4] else None,
    }
    spec["about"] = explain.about(
        f"Every facility with a stored location, colored by its {value_title(key).rsplit(' (', 1)[0].lower()}.",
        explain.how_aggregated(key) + " Each facility's records (all its units and years in the selection) are "
        "combined that way.",
        "Plotting each facility where it is shows clusters and outliers that a state total hides.",
        "Darker dots are higher, and the highest are drawn on top. Select a dot for its numbers.",
        explain.source_text(frame))
    top = max(rows, key=lambda row: row[4] if row[4] is not None else float("-inf"))
    spec["headline"] = headline(top[4], item["unit"], str(top[1]),
                                eyebrow=f"Highest of {len(shown):,} facilit{'y' if len(shown) == 1 else 'ies'}")
    return spec


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
    shown = [item for item in totals if item["total"]]
    if not shown:
        return empty_chart("impact_shares", title, "No impact could be calculated for this selection.")
    names = [item["name"] for item in shown]
    data, legend = [], []
    for pollutant in traci.POLLUTANT_ORDER:
        label = traci.POLLUTANTS[pollutant]["label"]
        shares = []
        details = []
        for item in shown:
            part = next((c for c in item["contributions"] if c["pollutant"] == pollutant), None)
            if part is None or part["amount"] is None:
                shares.append(None)
                details.append(["", "", []])
                continue
            shares.append(clean(part["share"]))
            summary = f"{label}: {part['share']:.1f}% of {item['name']}"
            short = (f"{traci.number(part['tons'], 3)} short tons × {traci.SHORT_TON_KG} × {part['factor']:.6g} = "
                     f"{traci.number(part['amount'])} {item['unit']}")
            lines = traci.calculation_lines(item["name"], item["unit"], item["contributions"], item["total"],
                                            records=item["used"], focus=label,
                                            heading=f"{item['name']}: the part from {label}")
            details.append([summary, short, lines])
        if all(share is None for share in shares):
            continue
        data.append({
            "type": "bar", "orientation": "h", "name": label, "legendgroup": label, "x": shares, "y": names,
            "customdata": details,
            "marker": {"color": POLLUTANT_COLORS[pollutant], "line": {"color": SURFACE, "width": 2}},
            "hovertemplate": "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Click for the full calculation"
                             "<extra></extra>",
        })
        legend.append(legend_item(label, POLLUTANT_COLORS[pollutant], style="square"))
    figure = layout(title, "", "", barmode="stack")
    bar_rows(figure, names, show_axis=True, suffix="%")
    figure["xaxis"].update(range=[0, 100], dtick=25, fixedrange=True)
    columns = ["Impact category", "Unit", "Total"] + [f"Share from {traci.POLLUTANTS[p]['label']} (%)"
                                                     for p in traci.POLLUTANT_ORDER]
    rows = []
    for item in totals:
        shares = {c["pollutant"]: c["share"] for c in item["contributions"]}
        rows.append([item["name"], item["unit"], clean(item["total"])]
                    + [clean(shares.get(p)) for p in traci.POLLUTANT_ORDER])
    note = "Each bar is one impact category. Categories are never added together because their units differ."
    spec = chart("impact_shares", title, data, figure, columns, rows, note)
    spec["explain"] = "Click any part of a bar to see exactly how its number was calculated."
    spec["eyebrow"] = "Share of each category, by pollutant"
    spec["about"] = explain.about(
        "For each potential impact category, how much of the selection's total comes from CO2, SO2 and NOx.",
        "Each pollutant's mass is converted from short tons to kilograms (× 907.18474) and multiplied by its TRACI "
        "2.2 characterization factor for the category. A pollutant's share is its part ÷ the category total × 100.",
        "Categories have different units (kg CO2 eq, kg SO2 eq, ...) and must never be added together, so each "
        "gets its own 100% bar; shares are comparable across categories even though the totals are not.",
        "Select any colored part for its full calculation.",
        "EPA CAMPD annual emissions (as selected in Explore) × EPA TRACI 2.2 characterization factors.")
    spec["legend"] = legend
    return spec


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

    def parts_for(item):
        parts = []
        for pollutant in traci.POLLUTANT_ORDER:
            if pollutant not in item["contributions"]:
                continue
            parts.append({"label": traci.POLLUTANTS[pollutant]["label"], "tons": item["tons"].get(pollutant),
                          "factor": item["factors"][pollutant], "amount": item["contributions"].get(pollutant)})
        return parts

    legend = []
    figure = layout(title, "", "", barmode="stack")
    if per_mwh:
        details = []
        for row in shown:
            item = row[key]
            lines = traci.calculation_lines(name, unit, parts_for(item), item["total"], item["load"],
                                            item["intensity"], item["used"], heading=f"{name}: {row['group']}")
            details.append([f"{text(row['group'])}: {traci.number(item['intensity'], 4)} {value_unit}",
                            f"{traci.number(item['intensity'] * item['load'])} {unit} ÷ "
                            f"{traci.number(item['load'])} MWh", lines])
        values = [clean(row[key]["intensity"]) for row in shown]
        data = [dict({
            "type": "bar", "orientation": "h", "x": values, "y": names,
            "customdata": details, "marker": {"color": SERIES[0]},
            "hovertemplate": "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Click for the full calculation"
                             "<extra></extra>",
        }, **value_labels(values))]
        bar_rows(figure, names, values)
    else:
        data = []
        pollutants = [p for p in traci.POLLUTANT_ORDER if p in shown[0][key]["contributions"]]
        for pollutant in pollutants:
            label = traci.POLLUTANTS[pollutant]["label"]
            details = []
            for row in shown:
                item = row[key]
                amount = item["contributions"].get(pollutant)
                tons = item["tons"].get(pollutant)
                if amount is None or tons is None:
                    details.append(["", "", []])
                    continue
                lines = traci.calculation_lines(name, unit, parts_for(item), item["total"], records=item["used"],
                                                focus=label, heading=f"{name}: {row['group']}, the part from {label}")
                details.append([f"{text(row['group'])}: {label} {traci.number(amount)} {unit}",
                                f"{traci.number(tons, 3)} short tons × {traci.SHORT_TON_KG} × "
                                f"{item['factors'][pollutant]:.6g}", lines])
            data.append({
                "type": "bar", "orientation": "h", "name": label, "legendgroup": label, "y": names,
                "x": [clean(row[key]["contributions"].get(pollutant)) for row in shown], "customdata": details,
                "marker": {"color": POLLUTANT_COLORS[pollutant], "line": {"color": SURFACE, "width": 2}},
                "hovertemplate": "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Click for the full calculation"
                                 "<extra></extra>",
            })
            legend.append(legend_item(label, POLLUTANT_COLORS[pollutant], style="square"))
        bar_rows(figure, names, show_axis=True, axis_title=f"{name} ({value_unit})")
        figure["xaxis"]["rangemode"] = "tozero"
    columns = [group_name, f"{name} ({unit})", f"{name} per MWh ({unit}/MWh)", "Records used", "Records"]
    table = [[row["group"], clean(row.get(key, {}).get("total")), clean(row.get(key, {}).get("intensity")),
              row.get(key, {}).get("used"), row["records"]] for row in rows]
    note = f"The {len(shown)} highest of {len(usable)} groups."
    if not per_mwh and len(data) > 1:
        note += " Each bar is split by the pollutant it comes from."
    spec = chart("impact_groups", title, data, figure, columns, table, note)
    spec["explain"] = "Click any bar to see exactly how its number was calculated."
    spec["about"] = explain.about(
        f"The potential {name.lower()} impact of each {group_name.lower()}"
        + (", per MWh of gross load." if per_mwh else ", split by the pollutant it comes from."),
        "For every record, each pollutant's short tons × 907.18474 kg per short ton × its TRACI 2.2 factor; the "
        "group's records are added up"
        + (" and divided by their gross load." if per_mwh else ". Records missing a pollutant the category needs are "
           "left out rather than counted as 0."),
        "Horizontal bars rank the groups and leave room for long names" + ("" if per_mwh else
        "; stacking shows which pollutant drives each group's impact") + ".",
        "These are potential-impact indicators, not measured health or environmental outcomes. Select a bar for "
        "its full calculation.",
        "EPA CAMPD annual emissions (as selected in Explore) × EPA TRACI 2.2 characterization factors.")
    top = shown[0][key][field]
    spec["headline"] = headline(top, value_unit, f"{shown[0]['group']}, the highest of {len(usable)}",
                                eyebrow=f"Highest {group_name.lower()}")
    if len(legend) > 1:
        spec["legend"] = legend
    return spec
