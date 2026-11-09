"""
Phase 2 comparative analysis (proposal 4.5).

Compares two groups of records from the current selection:
  - two reporting periods (e.g. 2015–2017 against 2023–2025), optionally only units in both
  - two states, fuels or unit types
  - units with and without an SO2 or NOx control
  - two facilities or two units

For the chosen variable it reports each group's summary statistics, absolute and percentage
differences, the same comparison for every normalized indicator, two statistical tests with a
plain-language reading, charts, and a ranking of every group in the chosen dimension.

The differences are always B minus A, and the percentage difference is (B − A) ÷ |A| × 100.
"""

import math

import numpy as np
import pandas as pd
import scipy
from scipy import stats

import analysis
import dashboard

DIMENSIONS = {
    "period": "Reporting periods",
    "state": "States",
    "primary_fuel": "Fuels",
    "unit_type": "Unit types",
    "so2_control": "With vs. without an SO2 control",
    "nox_control": "With vs. without a NOx control",
    "facility": "Facilities",
    "unit": "Units",
}

# Indicators compared side by side in every comparison
INDICATORS = ["co2_mass", "so2_mass", "nox_mass", "gross_load", "heat_input", "co2_intensity", "so2_intensity",
              "nox_intensity", "heat_rate", "operating_utilization"]

def scipy_version():
    return scipy.__version__


RANKING_LIMIT = 50
TEST_GROUP_LIMIT = 50

CAVEATS = [
    "Each record is one unit in one year, and the same unit usually appears in several years. Records are "
    "therefore not fully independent, so treat the p-values and confidence intervals as approximate.",
    "These are observed differences, not proven causes. Units with and without a control, or in different states, "
    "also differ in size, age, fuel and how much they run.",
    "Emissions are very uneven (a few large units emit most of the total), so the median and the Mann–Whitney "
    "test are usually more reliable guides than the mean and the t-test.",
]


# ---------- Defining the two groups ----------

def to_year(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def choose(frame, params):
    """
    Work out the comparison from the URL: the dimension, the two groups, their labels and masks,
    and the choices offered on the page.
    """
    dimension = params.get("cmp") if params.get("cmp") in DIMENSIONS else "period"
    years = dashboard.selection_years(frame)
    first = years[0] if years else None
    last = years[-1] if years else None
    definition = {"dimension": dimension, "name": DIMENSIONS[dimension], "options": [], "matched": False,
                  "years": years}

    if dimension == "period":
        a_from = to_year(params.get("pa_from"), first)
        a_to = to_year(params.get("pa_to"), a_from)
        b_from = to_year(params.get("pb_from"), last)
        b_to = to_year(params.get("pb_to"), b_from)
        if a_from is not None and a_to is not None and a_from > a_to:
            a_from, a_to = a_to, a_from
        if b_from is not None and b_to is not None and b_from > b_to:
            b_from, b_to = b_to, b_from
        year = frame["year"]
        mask_a = (year >= (a_from or 0)) & (year <= (a_to or 0))
        mask_b = (year >= (b_from or 0)) & (year <= (b_to or 0))
        matched = params.get("matched") == "1"
        if matched:
            both = set(frame.loc[mask_a, "unit_key"].dropna()) & set(frame.loc[mask_b, "unit_key"].dropna())
            in_both = frame["unit_key"].isin(both)
            mask_a = mask_a & in_both
            mask_b = mask_b & in_both
        definition.update({
            "a": {"from": a_from, "to": a_to}, "b": {"from": b_from, "to": b_to},
            "a_label": period_label(a_from, a_to), "b_label": period_label(b_from, b_to),
            "matched": matched,
        })
    elif dimension in ("so2_control", "nox_control"):
        labels = analysis.group_labels(frame, dimension)
        pollutant = "SO2" if dimension == "so2_control" else "NOx"
        a_label = f"No {pollutant} control reported"
        b_label = f"With {pollutant} control"
        mask_a = labels == a_label
        mask_b = labels == b_label
        definition.update({"a_label": a_label, "b_label": b_label})
    else:
        labels, options = group_choices(frame, dimension)
        values = [value for value, _, _ in options]
        a_value = params.get("a") if params.get("a") in values else (values[0] if values else None)
        b_default = values[1] if len(values) > 1 else a_value
        b_value = params.get("b") if params.get("b") in values else b_default
        names = {value: name for value, name, _ in options}
        mask_a = labels == a_value
        mask_b = labels == b_value
        definition.update({"a_value": a_value, "b_value": b_value, "options": options,
                           "a_label": names.get(a_value, "—"), "b_label": names.get(b_value, "—")})

    definition["mask_a"] = mask_a.fillna(False) if hasattr(mask_a, "fillna") else mask_a
    definition["mask_b"] = mask_b.fillna(False) if hasattr(mask_b, "fillna") else mask_b
    definition["same"] = definition["a_label"] == definition["b_label"]
    return definition


def period_label(start, end):
    if start is None:
        return "—"
    return str(start) if start == end else f"{start}–{end}"


def group_choices(frame, dimension):
    """
    Each record's group as a string, and the groups offered in the menus:
    [(value, label, records)], largest first (facilities and units A to Z).
    """
    if dimension == "facility":
        labels = frame["facility_id"].map(lambda v: "" if pd.isna(v) else str(int(v)))
        names = analysis.group_labels(frame, "facility")
    elif dimension == "unit":
        labels = frame["unit_key"].map(lambda v: "" if pd.isna(v) else str(int(v)))
        names = analysis.unit_labels(frame)
    else:
        labels = analysis.group_labels(frame, dimension)
        names = labels
    data = pd.DataFrame({"value": labels, "name": names})
    counts = data.groupby(["value", "name"], sort=False).size().reset_index(name="records")
    counts = counts[counts["value"] != ""]
    if dimension in ("facility", "unit"):
        counts = counts.sort_values("name", kind="mergesort")
    else:
        counts = counts.sort_values(["records", "name"], ascending=[False, True], kind="mergesort")
    options = [(row.value, row.name, int(row.records)) for row in counts.itertuples(index=False)]
    return labels, options


# ---------- Numbers ----------

def difference(a, b):
    """(B − A, (B − A) ÷ |A| × 100); the percentage is missing when A is 0 or missing."""
    if a is None or b is None:
        return None, None
    change = b - a
    percent = (change / abs(a) * 100) if a != 0 else None
    return change, percent


def group_summary(part):
    summary = analysis.selection_summary(part)
    years = "—"
    if summary["first_year"] is not None:
        years = period_label(summary["first_year"], summary["last_year"])
    summary["years"] = years
    return summary


def summary_rows(key, stats_a, stats_b):
    """Statistic, A, B, difference and percentage difference for the chosen variable."""
    variable = analysis.VARIABLES[key]
    names = [("count", "Values present"), ("missing", "Missing values"), ("mean", "Mean"), ("median", "Median"),
             ("std", "Standard deviation"), ("q1", "First quartile (Q1)"), ("q3", "Third quartile (Q3)"),
             ("iqr", "Interquartile range"), ("min", "Minimum"), ("max", "Maximum")]
    if variable["additive"]:
        names.append(("total", "Total"))
    if variable["ratio"]:
        names.append(("overall", "Overall ratio (" + dashboard.lower_first(variable["overall_label"]) + ")"))
    rows = []
    for name, label in names:
        a = stats_a.get(name)
        b = stats_b.get(name)
        change, percent = (None, None)
        if name not in ("count", "missing"):
            change, percent = difference(a, b)
        else:
            change = (b - a) if (a is not None and b is not None) else None
        rows.append({"key": name, "label": label, "a": a, "b": b, "change": change, "percent": percent,
                     "headline": name in ("mean", "median", "total", "overall")})
    return rows


def indicator_rows(part_a, part_b):
    """Every normalized indicator (and the main totals) for both groups, with differences."""
    rows = []
    for key in INDICATORS:
        label_a = pd.Series("A", index=part_a.index)
        label_b = pd.Series("B", index=part_b.index)
        a = analysis.aggregate(part_a, key, label_a)["value"]
        b = analysis.aggregate(part_b, key, label_b)["value"]
        value_a = analysis.clean(a.iloc[0]) if len(a) else None
        value_b = analysis.clean(b.iloc[0]) if len(b) else None
        change, percent = difference(value_a, value_b)
        rows.append({"key": key, "label": analysis.VARIABLES[key]["label"], "unit": analysis.VARIABLES[key]["unit"],
                     "measure": analysis.aggregate_label(key), "a": value_a, "b": value_b, "change": change,
                     "percent": percent})
    return rows


def signed(value):
    """-841248.3 -> "−841,248", 4581 -> "+4,581"."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return sign + analysis.format_number(abs(value))


def describe_p(p):
    """'p = 0.052' or 'p < 0.001'."""
    if p is None:
        return "p not available"
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"


def tests(key, values_a, values_b, a_label, b_label):
    """Welch's t-test with a 95% confidence interval, and the Mann–Whitney U test, explained in words."""
    unit = analysis.VARIABLES[key]["unit"]
    label = analysis.VARIABLES[key]["label"]
    n_a = len(values_a)
    n_b = len(values_b)
    result = {"n_a": n_a, "n_b": n_b, "welch": None, "mann_whitney": None, "sentences": []}
    if n_a < 2 or n_b < 2:
        result["sentences"].append("Each group needs at least 2 values for these tests.")
        return result

    mean_a = float(np.mean(values_a))
    mean_b = float(np.mean(values_b))
    var_a = float(np.var(values_a, ddof=1))
    var_b = float(np.var(values_b, ddof=1))
    change = mean_b - mean_a
    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se > 0:
        df = (var_a / n_a + var_b / n_b) ** 2 / (
            (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1))
        t_value = change / se
        p_value = float(2 * stats.t.sf(abs(t_value), df))
        margin = float(stats.t.ppf(0.975, df)) * se
        result["welch"] = {"difference": change, "low": change - margin, "high": change + margin,
                           "t": t_value, "df": df, "p": p_value}
        direction = "higher" if change > 0 else "lower"
        number = analysis.format_number
        sentence = (f"On average, {b_label} is {number(abs(change))} {unit} {direction} than {a_label}. "
                    f"The 95% confidence interval for the difference (B − A) runs from {signed(change - margin)} to "
                    f"{signed(change + margin)} {unit}.")
        if p_value < 0.05:
            sentence += (f" A difference this large would be unlikely if both groups had the same average "
                         f"(Welch's t-test, {describe_p(p_value)}).")
        else:
            sentence += (f" The data are consistent with both groups having the same average "
                         f"(Welch's t-test, {describe_p(p_value)}).")
        result["sentences"].append(sentence)
    else:
        result["sentences"].append("Every value is identical, so the averages can't be tested.")

    u_value, p_value = stats.mannwhitneyu(values_b, values_a, alternative="two-sided")
    superiority = float(u_value) / (n_a * n_b)
    result["mann_whitney"] = {"u": float(u_value), "p": float(p_value), "superiority": superiority}
    sentence = (f"If you pick one record from each group at random, the {b_label} record has the higher {label} "
                f"{superiority * 100:.0f}% of the time (50% would mean neither group tends to be higher).")
    if p_value < 0.05:
        sentence += f" That tendency is unlikely to be chance (Mann–Whitney test, {describe_p(float(p_value))})."
    else:
        sentence += f" That could easily be chance (Mann–Whitney test, {describe_p(float(p_value))})."
    result["sentences"].append(sentence)
    return result


# ---------- Every group in the dimension ----------

def all_groups(frame, key, dimension):
    """
    Every group in the dimension (every year for periods), ranked by the variable's total,
    overall ratio or mean, with its difference from the whole selection; plus tests of whether
    the groups differ at all (one-way ANOVA and Kruskal–Wallis).
    """
    if dimension == "period":
        labels = frame["year"].map(lambda v: "" if pd.isna(v) else str(int(v)))
    elif dimension == "unit":
        labels = analysis.unit_labels(frame)
    else:
        labels = analysis.group_labels(frame, dimension)

    table = analysis.aggregate(frame, key, labels)
    values = pd.DataFrame({"group": labels, "value": frame[key]})
    grouped = values.groupby("group", sort=False)["value"]
    table["mean"] = grouped.mean()
    table["median"] = grouped.median()
    table = table[table.index != ""]

    overall = analysis.aggregate(frame, key, pd.Series("all", index=frame.index))["value"]
    overall_value = analysis.clean(overall.iloc[0]) if len(overall) else None

    ranked = table[table["value"].notna()].sort_values("value", ascending=False, kind="mergesort")
    rows = []
    for rank, (group, row) in enumerate(ranked.iterrows(), start=1):
        value = analysis.clean(row["value"])
        change, percent = (None, None)
        if not analysis.VARIABLES[key]["additive"]:
            change, percent = difference(overall_value, value)
        rows.append({"rank": rank, "group": group, "records": int(row["records"]), "count": int(row["count"]),
                     "value": value, "mean": analysis.clean(row["mean"]), "median": analysis.clean(row["median"]),
                     "change": change, "percent": percent,
                     "share": (value / overall_value * 100) if (analysis.VARIABLES[key]["additive"]
                                                               and overall_value) else None})

    # Do the groups differ at all? Use the largest groups with at least 3 values.
    sizes = values.dropna().groupby("group").size()
    sizes = sizes[(sizes >= 3) & (sizes.index != "")].sort_values(ascending=False).head(TEST_GROUP_LIMIT)
    test = None
    if len(sizes) >= 2:
        samples = [values.loc[(values["group"] == g) & values["value"].notna(), "value"].to_numpy() for g in sizes.index]
        anova = stats.f_oneway(*samples)
        kruskal = stats.kruskal(*samples)
        test = {"groups": int(len(sizes)), "anova_f": analysis.clean(anova.statistic), "anova_p": analysis.clean(anova.pvalue),
                "kruskal_h": analysis.clean(kruskal.statistic), "kruskal_p": analysis.clean(kruskal.pvalue)}
        if test["kruskal_p"] is not None and test["kruskal_p"] < 0.05:
            test["sentence"] = (f"Across the {test['groups']} largest groups, at least one group's values are "
                                f"typically higher or lower than the others' (Kruskal–Wallis "
                                f"{describe_p(test['kruskal_p'])}; one-way ANOVA {describe_p(test['anova_p'])}).")
        else:
            test["sentence"] = (f"Across the {test['groups']} largest groups, the values are consistent with the groups "
                                f"not differing (Kruskal–Wallis {describe_p(test['kruskal_p'])}; one-way ANOVA "
                                f"{describe_p(test['anova_p'])}).")
    return {"rows": rows, "overall": overall_value, "test": test, "measure": analysis.aggregate_label(key)}


# ---------- Charts ----------

A_COLOR = dashboard.SERIES[0]
B_COLOR = dashboard.SERIES[1]


def box_chart(key, values_a, values_b, a_label, b_label, scale):
    item = analysis.VARIABLES[key]
    title = f"{item['label']}: {a_label} and {b_label}"
    traces = []
    rows = []
    for label, values, color in ((a_label, values_a, A_COLOR), (b_label, values_b, B_COLOR)):
        shown = values[values > 0] if scale == "log" else values
        if len(shown) < 1:
            continue
        s = dashboard.box_stats(pd.Series(shown))
        traces.append({
            "type": "box", "name": dashboard.text(label), "x": [dashboard.text(label)],
            "q1": [s["q1"]], "median": [s["median"]], "q3": [s["q3"]],
            "lowerfence": [s["lower"]], "upperfence": [s["upper"]], "mean": [s["mean"]],
            "boxpoints": False, "line": {"color": color, "width": 2}, "fillcolor": rgba(color, 0.18),
            "marker": {"color": color},
        })
        rows.append([label, s["count"], s["min"], s["lower"], s["q1"], s["median"], s["mean"], s["q3"], s["upper"],
                     s["max"], s["outliers"]])
    if not traces:
        return dashboard.empty_chart("compare_box", title, "No values to compare.")
    figure = dashboard.layout(title, "", f"{item['label']} ({item['unit']})", height=420)
    figure["xaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    if scale == "log":
        dashboard.log_axis(figure["yaxis"])
    columns = ["Group", "Records", "Minimum", "Lower whisker", "Q1", "Median", "Mean", "Q3", "Upper whisker",
               "Maximum", "Outliers beyond whiskers"]
    note = "Boxes run from Q1 to Q3 with the median inside; whiskers reach the furthest values within 1.5 × IQR."
    if scale == "log":
        note += " Values of 0 are left out on the log scale."
    return dashboard.chart("compare_box", title, traces, figure, columns, rows, note)


def rgba(color, alpha):
    color = color.lstrip("#")
    return f"rgba({int(color[0:2], 16)},{int(color[2:4], 16)},{int(color[4:6], 16)},{alpha})"


def indicator_chart(rows, a_label, b_label):
    title = f"How {b_label} differs from {a_label}"
    usable = [row for row in rows if row["percent"] is not None]
    if not usable:
        return dashboard.empty_chart("compare_indicators", title, "No indicator can be compared as a percentage.")
    names = [f"{row['label']} ({row['measure'].lower()})" for row in usable]
    data = [{
        "type": "bar", "orientation": "h", "x": [row["percent"] for row in usable], "y": names,
        "customdata": [[row["a"], row["b"], row["unit"]] for row in usable],
        "marker": {"color": dashboard.SERIES[0]},
        "hovertemplate": "%{y}<br><b>%{x:+.1f}%</b><br>" + dashboard.text(a_label) + ": %{customdata[0]:,.4~g} "
                         "%{customdata[2]}<br>" + dashboard.text(b_label)
                         + ": %{customdata[1]:,.4~g} %{customdata[2]}<extra></extra>",
    }]
    figure = dashboard.layout(title, "% difference, B compared with A", "",
                              height=max(300, 34 * len(names) + 120), bargap=0.3)
    figure["yaxis"]["autorange"] = "reversed"
    figure["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    figure["xaxis"]["zeroline"] = True
    figure["xaxis"]["zerolinecolor"] = dashboard.AXIS
    figure["xaxis"]["ticksuffix"] = "%"
    columns = ["Indicator", "Measure", "Unit", a_label, b_label, "Difference (B − A)", "% difference"]
    table = [[row["label"], row["measure"], row["unit"], row["a"], row["b"], row["change"], row["percent"]]
             for row in rows]
    note = ("Totals add up the records; intensities, heat rate and utilization are overall ratios (total ÷ total), "
            "so large units count more. Bars to the right mean B is higher.")
    return dashboard.chart("compare_indicators", title, data, figure, columns, table, note)


def trend_chart(frame, key, definition):
    item = analysis.VARIABLES[key]
    years = definition["years"]
    if definition["dimension"] == "period":
        title = f"{item['label']} by year, with the two periods marked"
        if len(years) < 2:
            return dashboard.empty_chart("compare_trend", title, "The selection covers one year.")
        table = analysis.aggregate(frame, key, frame["year"]).reindex(years)
        data = [{
            "type": "scatter", "mode": "lines+markers", "name": "All selected records", "x": years,
            "y": [dashboard.clean(v) for v in table["value"]],
            "line": {"color": dashboard.INK_2, "width": 2},
            "marker": {"size": 8, "color": dashboard.INK_2, "line": {"color": dashboard.SURFACE, "width": 2}},
            "hovertemplate": "%{x}: <b>%{y:,.4~g} " + item["unit"] + "</b><extra></extra>",
        }]
        shapes = []
        annotations = []
        for side, color, label in (("a", A_COLOR, "A"), ("b", B_COLOR, "B")):
            start = definition[side]["from"]
            end = definition[side]["to"]
            if start is None:
                continue
            shapes.append({"type": "rect", "xref": "x", "yref": "paper", "x0": start - 0.45, "x1": end + 0.45,
                           "y0": 0, "y1": 1, "fillcolor": rgba(color, 0.12), "line": {"width": 0}, "layer": "below"})
            annotations.append({"x": (start + end) / 2, "y": 1, "yref": "paper", "yanchor": "bottom",
                                "text": f"{label}: {period_label(start, end)}", "showarrow": False,
                                "font": {"color": dashboard.INK_2, "size": 12}})
        figure = dashboard.layout(title, "Reporting year", dashboard.value_title(key), shapes=shapes,
                                  annotations=annotations, hovermode="x unified")
        figure["xaxis"]["dtick"] = 1
        columns = ["Year", dashboard.value_title(key), "Records"]
        rows = [[year, dashboard.clean(v), 0 if pd.isna(r) else int(r)]
                for year, v, r in zip(years, table["value"], table["records"])]
        return dashboard.chart("compare_trend", title, data, figure, columns, rows,
                               "Shaded years are the two periods being compared.")

    title = f"{item['label']} by year: {definition['a_label']} and {definition['b_label']}"
    if len(years) < 2:
        return dashboard.empty_chart("compare_trend", title, "The selection covers one year.")
    data = []
    columns = ["Year"]
    series_values = []
    for label, mask, color in ((definition["a_label"], definition["mask_a"], A_COLOR),
                               (definition["b_label"], definition["mask_b"], B_COLOR)):
        part = frame[mask]
        table = analysis.aggregate(part, key, part["year"]).reindex(years)
        values = [dashboard.clean(v) for v in table["value"]]
        series_values.append(values)
        columns.append(f"{label}: {dashboard.value_title(key)}")
        data.append({
            "type": "scatter", "mode": "lines+markers", "name": dashboard.text(label), "x": years, "y": values,
            "line": {"color": color, "width": 2},
            "marker": {"size": 8, "color": color, "line": {"color": dashboard.SURFACE, "width": 2}},
            "hovertemplate": dashboard.text(label) + ": <b>%{y:,.4~g} " + item["unit"] + "</b><extra></extra>",
        })
    figure = dashboard.layout(title, "Reporting year", dashboard.value_title(key), showlegend=True,
                              hovermode="x unified")
    figure["xaxis"]["dtick"] = 1
    rows = [[year] + [values[i] for values in series_values] for i, year in enumerate(years)]
    return dashboard.chart("compare_trend", title, data, figure, columns, rows,
                           "Gaps are years with no records for that group.")


# ---------- Everything ----------

def compare(frame, key, definition, scale="log"):
    part_a = frame[definition["mask_a"]]
    part_b = frame[definition["mask_b"]]
    stats_a = analysis.describe(part_a, key)
    stats_b = analysis.describe(part_b, key)
    values_a = part_a[key].dropna().to_numpy(dtype="float64")
    values_b = part_b[key].dropna().to_numpy(dtype="float64")
    indicators = indicator_rows(part_a, part_b)
    a_label = definition["a_label"]
    b_label = definition["b_label"]
    return {
        "groups": [
            {"side": "A", "label": a_label, "summary": group_summary(part_a), "stats": stats_a},
            {"side": "B", "label": b_label, "summary": group_summary(part_b), "stats": stats_b},
        ],
        "rows": summary_rows(key, stats_a, stats_b),
        "indicators": indicators,
        "tests": tests(key, values_a, values_b, a_label, b_label),
        "ranking": all_groups(frame, key, definition["dimension"]),
        "charts": [
            box_chart(key, values_a, values_b, a_label, b_label, scale),
            indicator_chart(indicators, a_label, b_label),
            trend_chart(frame, key, definition),
        ],
    }


# ---------- Tables for export ----------

def summary_table(key, result):
    a_label = result["groups"][0]["label"]
    b_label = result["groups"][1]["label"]
    unit = analysis.VARIABLES[key]["unit"]
    columns = ["Statistic", f"A: {a_label} ({unit})", f"B: {b_label} ({unit})", "Difference (B − A)", "% difference"]
    rows = [["Records", result["groups"][0]["summary"]["records"], result["groups"][1]["summary"]["records"], None,
             None],
            ["Facilities", result["groups"][0]["summary"]["facilities"], result["groups"][1]["summary"]["facilities"],
             None, None],
            ["Units", result["groups"][0]["summary"]["units"], result["groups"][1]["summary"]["units"], None, None]]
    for row in result["rows"]:
        rows.append([row["label"], row["a"], row["b"], row["change"], row["percent"]])
    welch = result["tests"]["welch"]
    if welch:
        rows.append(["Welch's t-test: difference in means", None, None, welch["difference"], None])
        rows.append(["Welch's t-test: 95% CI low", None, None, welch["low"], None])
        rows.append(["Welch's t-test: 95% CI high", None, None, welch["high"], None])
        rows.append(["Welch's t-test: p-value", None, None, welch["p"], None])
    mann = result["tests"]["mann_whitney"]
    if mann:
        rows.append(["Mann–Whitney: P(B record > A record)", None, None, mann["superiority"], None])
        rows.append(["Mann–Whitney: p-value", None, None, mann["p"], None])
    return columns, rows


def ranking_table(key, dimension, ranking):
    measure = ranking["measure"]
    unit = analysis.VARIABLES[key]["unit"]
    group_name = "Year" if dimension == "period" else DIMENSIONS[dimension]
    columns = ["Rank", group_name, "Records", f"{measure} ({unit})", f"Mean ({unit})", f"Median ({unit})"]
    if analysis.VARIABLES[key]["additive"]:
        columns.append("Share of selection total (%)")
    else:
        columns += ["Difference from selection", "% difference from selection"]
    rows = []
    for row in ranking["rows"]:
        line = [row["rank"], row["group"], row["records"], row["value"], row["mean"], row["median"]]
        if analysis.VARIABLES[key]["additive"]:
            line.append(row["share"])
        else:
            line += [row["change"], row["percent"]]
        rows.append(line)
    return columns, rows


def indicators_table(result):
    for chart in result["charts"]:
        if chart["id"] == "compare_indicators" and chart["table"]["columns"]:
            return chart["table"]["columns"], chart["table"]["rows"]
    a_label = result["groups"][0]["label"]
    b_label = result["groups"][1]["label"]
    columns = ["Indicator", "Measure", "Unit", a_label, b_label, "Difference (B − A)", "% difference"]
    rows = [[r["label"], r["measure"], r["unit"], r["a"], r["b"], r["change"], r["percent"]]
            for r in result["indicators"]]
    return columns, rows
