"""
What every chart explains about itself.

Two kinds of explanation, drawn by templates/_chart.html and static/charts.js:

  about    "About this chart": what the chart shows, how each value is calculated, where the data
           comes from, why this kind of chart fits, and how to read it.

  details  What you see after clicking a point, bar, box, state or cell: the value, the calculation
           behind it with the real numbers (like a receipt), facts about the records it comes from,
           and a link to those records in Explore.

A detail is a plain dict, so every chart builder makes them the same way and the page draws them
all alike:

  {"kicker": "CO2 mass · 2025",          small gray line
   "title": "2025",                       what was clicked
   "value": "402", "unit": "million short tons",
   "summary": "...",                      one sentence in plain language
   "calc": [{"op": "", "label": "...", "value": "..."}, ..., {"op": "=", ..., "result": True}],
   "facts": [["Records", "1,597"], ...],
   "note": "...",                         anything left out, and why
   "drill": {"reporting_year": 2025}}     Explore filters for "See these records"
"""

import numpy as np
import pandas as pd

import analysis

SOURCE = "EPA Clean Air Markets Program Data (CAMPD), annual emissions reported by each unit"

# The two totals behind each ratio: (numerator, its unit, denominator, its unit, (scale, why))
RATIO_PARTS = {
    "co2_intensity": ("CO2 mass", "short tons", "gross load", "MWh", None),
    "so2_intensity": ("SO2 mass", "short tons", "gross load", "MWh", (2000, "lb per short ton")),
    "nox_intensity": ("NOx mass", "short tons", "gross load", "MWh", (2000, "lb per short ton")),
    "heat_rate": ("heat input", "mmBtu", "gross load", "MWh", None),
    "operating_utilization": ("operating time", "hours", "hours in the reporting year", "hours",
                              (100, "to make a percentage")),
}
for _base in analysis.CHANGE_BASES:
    _unit = analysis.VARIABLES[_base]["unit"]
    RATIO_PARTS[_base + "_change_pct"] = ("change from the previous year", _unit,
                                          "previous year's value", _unit, (100, "to make a percentage"))


# ---------- Numbers ----------

def number(value):
    """Numbers for calculations: whole numbers with commas from 1,000 up, otherwise 4 significant digits."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    value = float(value)
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        text = f"{value:,.0f}"
    elif abs(value) >= 1e-4:
        text = f"{value:#.4g}"
        if "e" in text or abs(float(text)) >= 1000:
            text = f"{value:,.0f}"
    else:
        text = analysis.format_number(value)
    return text.rstrip(".").replace("-", "−")


def lower_first(label):
    """'Gross load' -> 'gross load', but 'CO2 mass' stays as it is."""
    if label[:3] in ("CO2", "SO2", "NOx"):
        return label
    return label[0].lower() + label[1:]


def with_unit(value, unit):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{number(value)} {unit}".strip()


def count(value, noun):
    value = int(value)
    return f"{value:,} {noun}{'' if value == 1 else 's'}"


def big(value, unit):
    """The large number at the top of a detail: ("1.26", "billion short tons")."""
    words = analysis.format_compact(value)
    for word in ("trillion", "billion", "million"):
        if words.endswith(" " + word):
            return words[:-len(word) - 1].replace("-", "−"), f"{word} {unit}".strip()
    return words.replace("-", "−"), unit


def signed_percent(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if abs(value) < 0.05:
        return "0%"
    return ("+" if value > 0 else "−") + f"{abs(value):,.1f}%"


def years_text(first, last):
    if first is None or pd.isna(first):
        return "—"
    first, last = int(first), int(last)
    return str(first) if first == last else f"{first}–{last}"


# ---------- Where the data comes from ----------

def source_text(frame):
    if not {"year", "facility_id", "unit_key"} <= set(frame.columns):
        return f"{SOURCE}: {len(frame):,} records, as selected in Explore."
    summary = analysis.selection_summary(frame)
    return (f"{SOURCE}: {summary['records']:,} records from {summary['facilities']:,} facilities and "
            f"{summary['units']:,} units, {years_text(summary['first_year'], summary['last_year'])}, as selected "
            "in Explore. Values are as reported; nothing is filled in.")


def about(what, how, why, read="", source=""):
    return {"what": what, "how": how, "why": why, "read": read, "source": source}


def how_aggregated(key):
    """How one value per year or group is made from the records, in words."""
    item = analysis.VARIABLES[key]
    if item["ratio"]:
        numerator, _, denominator, _, scale = RATIO_PARTS[key]
        text = (f"{item['label']} is an overall ratio: the total {numerator} of the records divided by their "
                f"total {denominator}")
        if scale:
            text += f", × {scale[0]:,} {scale[1]}"
        return (text + ". Only records with both values (and a denominator above 0) are used, so large units "
                "count more than small ones.")
    if item["additive"]:
        return (f"{item['label']} is added up over the records. A record with no value is left out, never "
                "counted as 0.")
    return f"{item['label']} is averaged over the records that have a value."


# ---------- One value made from many records ----------

def parts(frame, key, labels):
    """
    For each group: the value (as analysis.aggregate makes it) and what went into it: records, records
    used, the totals behind a ratio, and how many units, facilities and years.
    """
    item = analysis.VARIABLES[key]
    table = analysis.aggregate(frame, key, labels)
    data = pd.DataFrame({"group": labels, "value": frame[key], "unit": frame["unit_key"],
                         "facility": frame["facility_id"], "year": frame["year"]})
    if item["ratio"]:
        data["num"] = frame["_num_" + key]
        data["den"] = frame["_den_" + key]
    grouped = data.groupby("group", sort=False)
    table["units"] = grouped["unit"].nunique()
    table["facilities"] = grouped["facility"].nunique()
    table["first"] = grouped["year"].min()
    table["last"] = grouped["year"].max()
    if item["ratio"]:
        table["num"] = grouped["num"].sum(min_count=1)
        table["den"] = grouped["den"].sum(min_count=1)
        table["used"] = grouped["num"].count()
    else:
        table["used"] = table["count"]
    return table


def aggregate_calc(key, row):
    """The receipt for one aggregated value."""
    item = analysis.VARIABLES[key]
    unit = item["unit"]
    if item["ratio"]:
        numerator, num_unit, denominator, den_unit, scale = RATIO_PARTS[key]
        calc = [{"op": "", "label": f"Total {numerator}", "value": with_unit(row["num"], num_unit)}]
        if scale:
            calc.append({"op": "×", "label": f"{scale[0]:,} {scale[1]}", "value": ""})
        calc.append({"op": "÷", "label": f"Total {denominator}", "value": with_unit(row["den"], den_unit)})
        calc.append({"op": "=", "label": item["label"], "value": with_unit(row["value"], unit), "result": True})
        return calc
    if item["additive"]:
        return [{"op": "Σ", "label": f"{item['label']} of {count(row['used'], 'record')}, added up", "value": ""},
                {"op": "=", "label": f"Total {lower_first(item['label'])}", "value": with_unit(row["value"], unit),
                 "result": True}]
    return [{"op": "", "label": f"Average of {count(row['used'], 'record')}", "value": ""},
            {"op": "=", "label": item["label"], "value": with_unit(row["value"], unit), "result": True}]


def left_out_note(key, row):
    item = analysis.VARIABLES[key]
    missing = int(row["records"]) - int(row["used"])
    if missing <= 0:
        return ""
    if item["ratio"]:
        _, _, denominator, _, _ = RATIO_PARTS[key]
        return (f"{count(missing, 'record')} {'is' if missing == 1 else 'are'} left out because a value is missing "
                f"or the {denominator} is 0, so the ratio isn't defined for {'it' if missing == 1 else 'them'}.")
    return (f"{count(missing, 'record')} {'has' if missing == 1 else 'have'} no {item['label']} reported and "
            f"{'is' if missing == 1 else 'are'} left out (not counted as 0).")


def kicker_for(key):
    word = analysis.aggregate_label(key)
    return f"{'Overall' if word == 'Overall ratio' else word} {lower_first(analysis.VARIABLES[key]['label'])}"


def aggregate_detail(key, row, title, prefix="", drill=None, facts=None, summary=""):
    """The detail for one year, group, state or facility. prefix goes before the kicker ("Coal · ...")."""
    item = analysis.VARIABLES[key]
    value, unit = big(row["value"], item["unit"])
    if not summary:
        if item["ratio"]:
            summary = (f"The overall {item['label']} of {count(row['used'], 'record')}: their totals divided, "
                       "not an average of each record's ratio.")
        elif item["additive"]:
            summary = f"The {item['label']} of {count(row['used'], 'record')} added together."
        else:
            summary = f"The average {item['label']} of {count(row['used'], 'record')}."
    rows = [["Records", f"{int(row['records']):,}"]]
    if int(row["used"]) != int(row["records"]):
        rows.append(["Records used", f"{int(row['used']):,}"])
    rows += [["Units", f"{int(row['units']):,}"], ["Facilities", f"{int(row['facilities']):,}"],
             ["Years", years_text(row["first"], row["last"])]]
    detail = {
        "kicker": (prefix + " · " if prefix else "") + kicker_for(key),
        "title": title,
        "value": value,
        "unit": unit,
        "summary": summary,
        "calc": aggregate_calc(key, row),
        "facts": (facts or []) + rows,
        "note": left_out_note(key, row),
        "drill": drill or {},
        "drill_label": f"See {'this record' if int(row['records']) == 1 else 'these ' + format(int(row['records']), ',') + ' records'} in Explore",
    }
    return detail


def drill_for(group, name, frame=None):
    """Explore filters that pick out one group's records, or None when Explore can't filter for it."""
    if name == analysis.NOT_REPORTED:
        return None
    if group == "year":
        return {"reporting_year": int(float(name))}
    if group in ("state", "primary_fuel", "unit_type"):
        return {group: name}
    if group == "county":
        county, _, state = str(name).rpartition(", ")
        return {"county": county, "state": state} if county and state else None
    if group in ("so2_control", "nox_control"):
        return {group: "none"} if name.startswith("No ") else None
    if group == "facility":
        found = str(name).rsplit("ID ", 1)
        if len(found) == 2 and found[1].rstrip(")").isdigit():
            return {"epa_facility_id": int(found[1].rstrip(")"))}
    return None


# ---------- Other kinds of value ----------

def index_detail(name, year, total, base_total, base_year, index, unit):
    value = f"{index:,.1f}"
    direction = "higher" if index > 100 else "lower"
    summary = (f"{name} in {year} was {abs(index - 100):,.1f}% {direction} than in {base_year}."
               if abs(index - 100) >= 0.05 else f"{name} in {year} was the same as in {base_year}.")
    if year == base_year:
        summary = f"{base_year} is the first year with {name} data, so it is the starting point, 100."
    return {
        "kicker": f"{name} · indexed", "title": str(year), "value": value, "unit": f"({base_year} = 100)",
        "summary": summary,
        "calc": [{"op": "", "label": f"Total {name} in {year}", "value": with_unit(total, unit)},
                 {"op": "÷", "label": f"Total {name} in {base_year}", "value": with_unit(base_total, unit)},
                 {"op": "×", "label": "100", "value": ""},
                 {"op": "=", "label": "Index", "value": value, "result": True}],
        "facts": [], "note": "", "drill": {"reporting_year": int(year)},
    }


def bin_detail(key, low, high, records, shown, scale, index, bins):
    item = analysis.VARIABLES[key]
    share = records / shown * 100 if shown else 0
    drill = None
    if key in ("co2_mass", "so2_mass", "nox_mass", "gross_load", "heat_input", "operating_time"):
        drill = {f"{key}_min": float(f"{low:.6g}"), f"{key}_max": float(f"{high:.6g}")}
    return {
        "kicker": f"{item['label']} · bin {index + 1} of {bins}",
        "title": f"{number(low)} to {number(high)} {item['unit']}",
        "value": f"{records:,}", "unit": "record" if records == 1 else "records",
        "summary": f"{share:.1f}% of the {shown:,} records drawn have a {item['label']} in this range.",
        "calc": [{"op": "", "label": "Records in this range", "value": f"{records:,}"},
                 {"op": "÷", "label": "Records drawn", "value": f"{shown:,}"},
                 {"op": "=", "label": "Share", "value": f"{share:.1f}%", "result": True}],
        "facts": [["From", with_unit(low, item["unit"])], ["To", with_unit(high, item["unit"])],
                  ["Bins", f"{bins} of equal width{' in powers of ten' if scale == 'log' else ''}"]],
        "note": "", "drill": drill or {},
        "drill_label": f"See {'this record' if records == 1 else 'these ' + format(records, ',') + ' records'} in Explore",
    }


def box_detail(name, stats, label, unit, drill=None, kicker=""):
    spread = stats["q3"] - stats["q1"]
    return {
        "kicker": kicker or f"{label} · spread",
        "title": name,
        "value": number(stats["median"]), "unit": f"{unit} median",
        "summary": (f"Half of the {stats['count']:,} records lie between {number(stats['q1'])} and "
                    f"{number(stats['q3'])} {unit}; the median splits them in two."),
        "calc": [{"op": "", "label": "Q3 (75th percentile)", "value": with_unit(stats["q3"], unit)},
                 {"op": "−", "label": "Q1 (25th percentile)", "value": with_unit(stats["q1"], unit)},
                 {"op": "=", "label": "Interquartile range", "value": with_unit(spread, unit), "result": True}],
        "facts": [["Records", f"{stats['count']:,}"], ["Mean", with_unit(stats["mean"], unit)],
                  ["Lower whisker", with_unit(stats["lower"], unit)], ["Upper whisker", with_unit(stats["upper"], unit)],
                  ["Minimum", with_unit(stats["min"], unit)], ["Maximum", with_unit(stats["max"], unit)],
                  ["Beyond the whiskers", f"{stats['outliers']:,}"]],
        "note": ("Whiskers reach the furthest values within 1.5 × the interquartile range of the box; values beyond "
                 "them are counted, not drawn."),
        "drill": drill or {},
    }


def strength(r):
    size = abs(r)
    if size < 0.2:
        return "little or no relationship"
    word = "very strong" if size >= 0.9 else "strong" if size >= 0.7 else "moderate" if size >= 0.4 else "weak"
    return f"{word}: {'they rise together' if r > 0 else 'one falls as the other rises'}"


def correlation_detail(x_name, y_name, r, pairs, method):
    size = abs(r)
    if x_name == y_name:
        summary = "Every variable matches itself perfectly, so the diagonal is always 1."
    elif size < 0.2:
        summary = f"Little or no relationship between {y_name} and {x_name} across {pairs:,} records."
    else:
        word = "Very strong" if size >= 0.9 else "Strong" if size >= 0.7 else "Moderate" if size >= 0.4 else "Weak"
        summary = (f"{word} relationship: across {pairs:,} records, {y_name} and {x_name} "
                   f"{'tend to rise together' if r > 0 else 'tend to move in opposite directions'}.")
    how = ("Pearson correlation of the two variables' ranks" if method == "spearman"
           else "Pearson correlation of the two variables' values")
    return {
        "kicker": f"{method.title()} correlation", "title": f"{y_name} and {x_name}",
        "value": f"{r:.2f}".replace("-", "−"), "unit": "r",
        "summary": summary,
        "calc": [{"op": "", "label": how, "value": ""},
                 {"op": "", "label": "Records with both values", "value": f"{pairs:,}"},
                 {"op": "=", "label": "r", "value": f"{r:.3f}".replace("-", "−"), "result": True}],
        "facts": [["Scale", "−1 (opposite) to 1 (together)"]],
        "note": "Correlation shows that two measurements move together, not that one causes the other.",
        "drill": {},
    }


def model_inputs(inputs):
    """Prediction inputs as detail facts, in the model's own order."""
    import prediction
    import scenarios
    return [[prediction.INPUT_LABELS.get(name, name), scenarios.input_text(name, inputs[name])]
            for name in prediction.FEATURES if name in inputs]
