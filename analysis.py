"""
Phase 2 analysis: derived performance indicators (proposal 4.3) and descriptive
statistics (proposal 4.2).

How it fits together
  1. The records come from the Explore search (smart_search.explore), so an analysis
     uses exactly the records Explore shows, and the page URL reopens the same analysis.
  2. build_frame() turns those records into a pandas DataFrame and adds the derived
     indicators: intensities, heat rate, operating utilization and year-over-year change.
  3. describe() calculates statistics for the whole selection; describe_groups()
     calculates them for each state, fuel, unit type, year, facility or control group.
  4. export_file() writes a CSV or Excel file with the metadata needed to reproduce it.

Missing and undefined values
  - A ratio is left missing (NaN) when either input is missing or the denominator is
    zero or negative. It is never replaced with 0.
  - Statistics use only the values that exist, and the missing count is always reported.
"""

import csv
import hashlib
import io
import os
import subprocess
from datetime import datetime

import numpy as np
import pandas as pd

from search import connect

# Change this whenever a calculation changes, so exported files say which version made them
PIPELINE_VERSION = "2.2"

POUNDS_PER_SHORT_TON = 2000

# Explore result column -> short name used in the analysis
EXPLORE_COLUMNS = {
    "Facility": "facility_name",
    "Facility ID": "facility_id",
    "State": "state",
    "County": "county",
    "Unit": "unit_id",
    "Unit Type": "unit_type",
    "Primary Fuel": "primary_fuel",
    "Secondary Fuel": "secondary_fuel",
    "Year": "year",
    "Operating Time (hrs)": "operating_time",
    "Gross Load (MWh)": "gross_load",
    "Steam Load (1000 lb)": "steam_load",
    "Heat Input (mmBtu)": "heat_input",
    "CO2 (tons)": "co2_mass",
    "SO2 (tons)": "so2_mass",
    "NOx (tons)": "nox_mass",
    "SO2 Controls": "so2_controls",
    "NOx Controls": "nox_controls",
    "PM Controls": "pm_controls",
    "Programs": "programs",
    "_unit_key": "unit_key",
}

NUMBER_COLUMNS = ["facility_id", "year", "unit_key", "operating_time", "gross_load", "steam_load",
                  "heat_input", "co2_mass", "so2_mass", "nox_mass"]


# ---------- Variables ----------
#
# Every variable a person can analyze.
#   group:      heading in the variable menu
#   additive:   adding values together means something (a total is shown)
#   ratio:      a ratio of two columns (an overall ratio, total ÷ total, is shown)
#   definition: shown on the page and written into every export

def measured(label, unit, definition):
    return {"label": label, "unit": unit, "group": "Measured", "additive": True, "ratio": False,
            "definition": definition}


def derived(label, unit, definition, overall_label):
    return {"label": label, "unit": unit, "group": "Derived indicators", "additive": False, "ratio": True,
            "definition": definition, "overall_label": overall_label}


VARIABLES = {
    "co2_mass": measured("CO2 mass", "short tons", "Annual CO2 mass reported to EPA CAMPD."),
    "so2_mass": measured("SO2 mass", "short tons", "Annual SO2 mass reported to EPA CAMPD."),
    "nox_mass": measured("NOx mass", "short tons", "Annual NOx mass reported to EPA CAMPD."),
    "gross_load": measured("Gross load", "MWh", "Electricity generated during the year (gross)."),
    "heat_input": measured("Heat input", "mmBtu", "Fuel heat input during the year."),
    "operating_time": measured("Operating time", "hours", "Hours the unit operated during the year."),
    "steam_load": measured("Steam load", "1000 lb", "Steam sold during the year (reported only by units that sell steam)."),

    "co2_intensity": derived(
        "CO2 intensity", "short tons/MWh",
        "CO2 mass ÷ gross load.",
        "Total CO2 ÷ total gross load"),
    "so2_intensity": derived(
        "SO2 intensity", "lb/MWh",
        "SO2 mass × 2,000 lb per short ton ÷ gross load.",
        "Total SO2 ÷ total gross load"),
    "nox_intensity": derived(
        "NOx intensity", "lb/MWh",
        "NOx mass × 2,000 lb per short ton ÷ gross load.",
        "Total NOx ÷ total gross load"),
    "heat_rate": derived(
        "Heat rate", "mmBtu/MWh",
        "Heat input ÷ gross load. Lower means less fuel for each MWh (1 mmBtu/MWh = 1,000 Btu/kWh).",
        "Total heat input ÷ total gross load"),
    "operating_utilization": derived(
        "Operating utilization", "% of hours",
        "Operating time ÷ hours in the reporting year (8,760, or 8,784 in a leap year) × 100.",
        "Total operating hours ÷ total hours in the year"),
}

# Year-over-year change for the same unit, for these measured variables
CHANGE_BASES = ["co2_mass", "so2_mass", "nox_mass", "gross_load"]

for base in CHANGE_BASES:
    base_label = VARIABLES[base]["label"]
    VARIABLES[base + "_change"] = {
        "label": base_label + " change from previous year",
        "unit": VARIABLES[base]["unit"],
        "group": "Year-over-year change",
        "additive": True,
        "ratio": False,
        "definition": ("This year's " + base_label + " minus the same unit's " + base_label
                       + " in the previous year. Missing when the unit has no record for the previous year."),
    }
    VARIABLES[base + "_change_pct"] = {
        "label": base_label + " % change from previous year",
        "unit": "%",
        "group": "Year-over-year change",
        "additive": False,
        "ratio": True,
        "definition": ("(This year − previous year) ÷ previous year × 100, for the same unit. Missing when the unit "
                       "has no record for the previous year or the previous value is 0."),
        "overall_label": "Change in the total ÷ previous year's total",
    }

DEFAULT_VARIABLE = "co2_intensity"

VARIABLE_GROUPS = ["Measured", "Derived indicators", "Year-over-year change"]


def variables_by_group():
    """[(group heading, [(key, variable), ...]), ...] for the variable menu."""
    menu = []
    for group in VARIABLE_GROUPS:
        menu.append((group, [(key, item) for key, item in VARIABLES.items() if item["group"] == group]))
    return menu


def variable_title(key):
    item = VARIABLES[key]
    return item["label"] + " (" + item["unit"] + ")"


# ---------- Groups ----------

GROUPS = {
    "state": "State",
    "primary_fuel": "Primary fuel",
    "unit_type": "Unit type",
    "year": "Year",
    "facility": "Facility",
    "so2_control": "SO2 control",
    "nox_control": "NOx control",
}

NOT_REPORTED = "Not reported"

# How the grouped table can be sorted. Numbers sort largest first; group names A to Z.
GROUP_SORTS = {
    "group": "Name",
    "records": "Records",
    "mean": "Mean",
    "median": "Median",
    "total": "Total",
    "overall": "Overall ratio",
}

# The page shows this many groups; downloads include all of them
GROUP_LIMIT = 100


def default_group_sort(key, group):
    if group == "year":
        return "group"
    if VARIABLES[key]["additive"]:
        return "total"
    if VARIABLES[key]["ratio"]:
        return "overall"
    return "mean"


# ---------- Percentiles ----------

DEFAULT_PERCENTILES = [5, 10, 90, 95]
MAX_PERCENTILES = 8

PERCENTILE_METHOD = ("Linear interpolation between the closest ranks (the same method as Excel's "
                     "PERCENTILE.INC and NumPy's default).")
STD_METHOD = "Sample standard deviation (divides by n − 1)."
MISSING_RULE = ("Missing values are left out of every statistic and counted separately. A ratio is missing when "
                "either input is missing or the denominator is zero or negative; it is never set to 0.")
MEAN_VS_OVERALL = ("For ratios, the mean is the average of each record's own ratio, so every unit counts equally. "
                   "The overall ratio divides one total by the other, so large units count more. "
                   "Both are correct; they answer different questions.")


def parse_percentiles(text):
    """
    "5, 10, 90, 95" -> [5.0, 10.0, 90.0, 95.0]. Values outside 0–100 and anything that
    isn't a number are ignored. An empty box gives the default percentiles.
    """
    if text is None or str(text).strip() == "":
        return list(DEFAULT_PERCENTILES)
    found = []
    pieces = str(text).replace(";", ",").replace(" ", ",").split(",")
    for piece in pieces:
        piece = piece.strip().rstrip("%")
        if piece == "":
            continue
        try:
            value = float(piece)
        except ValueError:
            continue
        if 0 <= value <= 100 and value not in found:
            found.append(value)
    found.sort()
    return found[:MAX_PERCENTILES]


def percentile_label(value):
    """5.0 -> "P5", 2.5 -> "P2.5"."""
    if float(value).is_integer():
        return "P" + str(int(value))
    return "P" + str(value)


# ---------- Building the analytical dataset ----------

def safe_ratio(numerator, denominator):
    """numerator ÷ denominator, left missing (NaN) where either is missing or the denominator is 0 or negative."""
    defined = numerator.notna() & denominator.notna() & (denominator > 0)
    result = pd.Series(np.nan, index=numerator.index, dtype="float64")
    result[defined] = numerator[defined] / denominator[defined]
    return result


def hours_in_year(years):
    """8,784 hours in a leap year, 8,760 otherwise (NaN when the year is missing)."""
    leap = ((years % 4 == 0) & (years % 100 != 0)) | (years % 400 == 0)
    hours = pd.Series(np.where(leap, 8784.0, 8760.0), index=years.index)
    hours[years.isna()] = np.nan
    return hours


def add_ratio(frame, key, numerator, denominator, scale=1.0):
    """
    Add a ratio column, plus two hidden helper columns (_num_<key>, _den_<key>) that keep the
    numerator and denominator only where the ratio is defined. The overall ratio
    (total ÷ total) is calculated from those, using exactly the same records.
    """
    value = safe_ratio(numerator, denominator)
    defined = value.notna()
    frame[key] = value * scale
    frame["_num_" + key] = numerator.where(defined)
    frame["_den_" + key] = denominator.where(defined)
    frame["_scale_" + key] = scale
    # Records whose inputs were present but whose denominator was 0 or negative
    frame["_zero_" + key] = numerator.notna() & denominator.notna() & (denominator <= 0)


def previous_year_values(unit_keys, first_year, last_year):
    """
    The same units' values one year earlier, read from the whole database (so a 2025-only
    selection still gets 2024 values for comparison). Returned with "year" set to the
    year they are compared with.
    """
    columns = ["unit_key", "year"] + ["prev_" + base for base in CHANGE_BASES]
    if len(unit_keys) == 0 or first_year is None:
        return pd.DataFrame(columns=columns)

    connection = connect()
    rows = connection.execute(
        "SELECT internal_unit_key, year + 1, " + ", ".join(CHANGE_BASES)
        + " FROM annual_records WHERE year BETWEEN ? AND ?",
        (int(first_year) - 1, int(last_year) - 1),
    ).fetchall()
    connection.close()

    previous = pd.DataFrame([tuple(row) for row in rows], columns=columns)
    previous = previous[previous["unit_key"].isin(set(unit_keys))]
    previous = previous.drop_duplicates(subset=["unit_key", "year"])
    for column in columns:
        # float64 to match build_frame's columns, so the merge keys line up
        previous[column] = pd.to_numeric(previous[column], errors="coerce").astype("float64")
    return previous


def build_frame(rows, with_changes=True):
    """
    Explore result rows -> a DataFrame with short column names, numbers as numbers,
    and every derived indicator added.
    """
    frame = pd.DataFrame(list(rows))
    frame = frame.rename(columns=EXPLORE_COLUMNS)
    for column in EXPLORE_COLUMNS.values():
        if column not in frame.columns:
            frame[column] = pd.Series(dtype="object")
    for column in NUMBER_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")

    add_ratio(frame, "co2_intensity", frame["co2_mass"], frame["gross_load"])
    add_ratio(frame, "so2_intensity", frame["so2_mass"], frame["gross_load"], POUNDS_PER_SHORT_TON)
    add_ratio(frame, "nox_intensity", frame["nox_mass"], frame["gross_load"], POUNDS_PER_SHORT_TON)
    add_ratio(frame, "heat_rate", frame["heat_input"], frame["gross_load"])
    add_ratio(frame, "operating_utilization", frame["operating_time"], hours_in_year(frame["year"]), 100.0)

    add_changes(frame, with_changes)
    return frame


def add_changes(frame, with_changes=True):
    """Year-over-year change for the same unit, absolute and percent."""
    previous = None
    if with_changes and len(frame) > 0 and frame["year"].notna().any():
        previous = previous_year_values(
            frame["unit_key"].dropna().unique(),
            frame["year"].min(),
            frame["year"].max(),
        )

    if previous is not None and len(previous) > 0:
        merged = frame[["unit_key", "year"]].merge(previous, on=["unit_key", "year"], how="left")
        merged.index = frame.index
    else:
        merged = pd.DataFrame(index=frame.index)

    for base in CHANGE_BASES:
        column = "prev_" + base
        if column in merged.columns:
            prev = pd.to_numeric(merged[column], errors="coerce").astype("float64")
        else:
            prev = pd.Series(np.nan, index=frame.index, dtype="float64")
        frame[column] = prev

        current = frame[base]
        difference = current - prev  # NaN when either year is missing
        frame[base + "_change"] = difference
        add_ratio(frame, base + "_change_pct", difference, prev, 100.0)


# ---------- Statistics ----------

def clean(value):
    """numpy number or NaN -> plain float or None, so templates and files can use it."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(number) or np.isinf(number):
        return None
    return number


def overall_ratio(frame, key):
    """Total ÷ total over the records where the ratio is defined (None when it can't be calculated)."""
    if not VARIABLES[key]["ratio"] or len(frame) == 0:
        return None
    numerator = frame["_num_" + key].sum(min_count=1)
    denominator = frame["_den_" + key].sum(min_count=1)
    if pd.isna(numerator) or pd.isna(denominator) or denominator <= 0:
        return None
    return clean(numerator / denominator * frame["_scale_" + key].iloc[0])


def describe(frame, key, percentiles=None):
    """Every descriptive statistic for one variable over the whole selection."""
    if percentiles is None:
        percentiles = DEFAULT_PERCENTILES
    variable = VARIABLES[key]
    if key in frame.columns:
        values = frame[key]
    else:
        values = pd.Series(dtype="float64")
    present = values.dropna()
    count = int(present.size)

    result = {
        "records": int(values.size),
        "count": count,
        "missing": int(values.isna().sum()),
        "min": None, "max": None, "mean": None, "median": None, "std": None,
        "q1": None, "q3": None, "iqr": None,
        "percentiles": [],
        "total": None,
        "overall": None,
        "zero_denominator": None,
    }

    if count > 0:
        result["min"] = clean(present.min())
        result["max"] = clean(present.max())
        result["mean"] = clean(present.mean())
        result["median"] = clean(present.median())
        result["std"] = clean(present.std(ddof=1)) if count > 1 else None
        result["q1"] = clean(present.quantile(0.25))
        result["q3"] = clean(present.quantile(0.75))
        result["iqr"] = clean(result["q3"] - result["q1"])
        for p in percentiles:
            result["percentiles"].append((p, clean(present.quantile(p / 100.0))))
        if variable["additive"]:
            result["total"] = clean(present.sum())

    if variable["ratio"]:
        result["overall"] = overall_ratio(frame, key)
        result["zero_denominator"] = int(frame["_zero_" + key].sum()) if len(frame) else 0

    return result


def group_labels(frame, group):
    """The group each record belongs to, as text. Records with no value go in "Not reported"."""
    if group == "facility":
        names = frame["facility_name"].fillna(NOT_REPORTED).astype(str)
        states = frame["state"].fillna("").astype(str)
        ids = frame["facility_id"].map(lambda value: "" if pd.isna(value) else str(int(value)))
        return names + " (" + states + ", ID " + ids + ")"
    if group == "year":
        return frame["year"].map(lambda value: NOT_REPORTED if pd.isna(value) else str(int(value)))
    if group in ("so2_control", "nox_control"):
        column = "so2_controls" if group == "so2_control" else "nox_controls"
        pollutant = "SO2" if group == "so2_control" else "NOx"
        has_control = frame[column].fillna("").astype(str).str.strip() != ""
        return pd.Series(np.where(has_control, "With " + pollutant + " control",
                                  "No " + pollutant + " control reported"), index=frame.index)
    labels = frame[group].astype("object")
    labels = labels.where(labels.notna() & (labels.astype(str).str.strip() != ""), NOT_REPORTED)
    return labels.astype(str)


def describe_groups(frame, key, group, sort=None):
    """
    Statistics for each group (state, fuel, unit type, year, facility or control group).
    Returns a list of dicts, sorted, one per group.
    """
    if group not in GROUPS or len(frame) == 0 or key not in frame.columns:
        return []
    variable = VARIABLES[key]
    data = frame.copy()
    data["_group"] = group_labels(data, group)

    grouped = data.groupby("_group", sort=False)[key]
    table = pd.DataFrame({
        "records": grouped.size(),
        "count": grouped.count(),
        "mean": grouped.mean(),
        "median": grouped.median(),
        "std": grouped.std(ddof=1),
        "min": grouped.min(),
        "q1": grouped.quantile(0.25),
        "q3": grouped.quantile(0.75),
        "max": grouped.max(),
    })
    table["missing"] = table["records"] - table["count"]

    if variable["additive"]:
        table["total"] = grouped.sum(min_count=1)
    else:
        table["total"] = np.nan

    if variable["ratio"]:
        numerator = data.groupby("_group", sort=False)["_num_" + key].sum(min_count=1)
        denominator = data.groupby("_group", sort=False)["_den_" + key].sum(min_count=1)
        scale = data["_scale_" + key].iloc[0]
        table["overall"] = safe_ratio(numerator, denominator) * scale
    else:
        table["overall"] = np.nan

    if sort not in GROUP_SORTS:
        sort = default_group_sort(key, group)
    if sort == "group":
        table = table.sort_index(key=lambda index: index.map(lambda label: (label == NOT_REPORTED, label)))
    else:
        table = table.sort_values(sort, ascending=False, na_position="last", kind="mergesort")

    rows = []
    for label, row in table.iterrows():
        item = {"group": label}
        for column in ["records", "count", "missing"]:
            item[column] = int(row[column])
        for column in ["mean", "median", "std", "min", "q1", "q3", "max", "total", "overall"]:
            item[column] = clean(row[column])
        rows.append(item)
    return rows


def selection_summary(frame):
    """How many records, facilities, units and years the selection covers."""
    years = frame["year"].dropna()
    return {
        "records": int(len(frame)),
        "facilities": int(frame["facility_id"].dropna().nunique()),
        "units": int(frame["unit_key"].dropna().nunique()),
        "first_year": int(years.min()) if len(years) else None,
        "last_year": int(years.max()) if len(years) else None,
    }


def selection_fingerprint(frame):
    """
    A short code that identifies exactly which unit-years are selected. Running the same
    analysis on the same data gives the same code, so two exports can be checked against each other.
    """
    pairs = []
    for unit_key, year in zip(frame["unit_key"], frame["year"]):
        if pd.notna(unit_key) and pd.notna(year):
            pairs.append(str(int(unit_key)) + ":" + str(int(year)))
    pairs.sort()
    return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()[:12]


# ---------- Reproducibility metadata ----------

_git_commit = {"value": None}


def git_commit():
    """The code's Git commit (short hash), or "unknown" outside a Git checkout."""
    if _git_commit["value"] is None:
        try:
            output = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True, text=True, timeout=5,
            )
            _git_commit["value"] = output.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            _git_commit["value"] = "unknown"
    return _git_commit["value"]


def pipeline_version():
    text = ("epaData analysis " + PIPELINE_VERSION + "; Git commit " + git_commit()
            + "; pandas " + pd.__version__ + "; NumPy " + np.__version__)
    try:
        import scipy
        text += "; SciPy " + scipy.__version__
    except ImportError:
        pass
    return text


def database_state():
    """Which data the database held when the analysis ran: dataset count and the newest dataset."""
    connection = connect()
    try:
        count, newest, retrieved = connection.execute(
            "SELECT COUNT(*), MAX(dataset_id), MAX(retrieval_date) FROM dataset"
        ).fetchone()
    except Exception:
        count, newest, retrieved = 0, None, None
    connection.close()
    if not count:
        return "epaData database (no dataset records)"
    return ("epaData database: " + str(count) + " datasets, newest #" + str(newest)
            + " (latest retrieval or upload " + str(retrieved) + ")")


def metadata(export_kind, frame, filter_labels, explore_url, key=None, group=None, percentiles=None):
    """The (name, value) lines written at the top of every export."""
    summary = selection_summary(frame)
    years = "—"
    if summary["first_year"] is not None:
        years = str(summary["first_year"]) + "–" + str(summary["last_year"])

    lines = [
        ("Export", export_kind),
        ("Analysis date", datetime.now().isoformat(timespec="seconds")),
        ("Data source", "U.S. EPA Clean Air Markets Program Data (CAMPD), annual unit-level records"),
        ("Dataset identifier", database_state()),
        ("Selection fingerprint", selection_fingerprint(frame)),
        ("Selected filters", "; ".join(filter_labels) if filter_labels else "None (all records)"),
        ("Reopen this selection", explore_url),
        ("Records", str(summary["records"])),
        ("Facilities", str(summary["facilities"])),
        ("Units", str(summary["units"])),
        ("Reporting years", years),
    ]
    if key:
        lines.append(("Variable", variable_title(key)))
        lines.append(("Definition", VARIABLES[key]["definition"]))
    if group:
        lines.append(("Grouped by", GROUPS[group]))
    if percentiles is not None:
        lines.append(("Percentiles", ", ".join(percentile_label(p) for p in percentiles) or "None"))
        lines.append(("Percentile method", PERCENTILE_METHOD))
        lines.append(("Standard deviation", STD_METHOD))
    if key is None:
        for item_key, item in VARIABLES.items():
            if item["group"] != "Measured":
                lines.append(("Definition: " + variable_title(item_key), item["definition"]))
    lines.append(("Missing values", MISSING_RULE))
    lines.append(("Software version", pipeline_version()))
    return lines


# ---------- Tables for export ----------

def summary_table(key, stats):
    """The overall statistics as (Statistic, Value) rows."""
    unit = VARIABLES[key]["unit"]
    rows = [
        ("Records selected", stats["records"]),
        ("Count (values present)", stats["count"]),
        ("Missing values", stats["missing"]),
    ]
    if stats["zero_denominator"] is not None:
        rows.append(("Missing because the denominator was 0", stats["zero_denominator"]))
    rows += [
        ("Minimum (" + unit + ")", stats["min"]),
        ("First quartile Q1 (" + unit + ")", stats["q1"]),
        ("Median (" + unit + ")", stats["median"]),
        ("Mean (" + unit + ")", stats["mean"]),
        ("Third quartile Q3 (" + unit + ")", stats["q3"]),
        ("Maximum (" + unit + ")", stats["max"]),
        ("Interquartile range (" + unit + ")", stats["iqr"]),
        ("Standard deviation (" + unit + ")", stats["std"]),
    ]
    for p, value in stats["percentiles"]:
        rows.append((percentile_label(p) + " (" + unit + ")", value))
    if VARIABLES[key]["additive"]:
        rows.append(("Total (" + unit + ")", stats["total"]))
    if VARIABLES[key]["ratio"]:
        rows.append(("Overall ratio: " + VARIABLES[key]["overall_label"] + " (" + unit + ")", stats["overall"]))
    return ["Statistic", "Value"], [list(row) for row in rows]


def groups_table(key, group, groups):
    unit = VARIABLES[key]["unit"]
    columns = [GROUPS[group], "Records", "Count", "Missing",
               "Mean (" + unit + ")", "Median (" + unit + ")", "Std dev (" + unit + ")",
               "Min (" + unit + ")", "Q1 (" + unit + ")", "Q3 (" + unit + ")", "Max (" + unit + ")"]
    names = ["group", "records", "count", "missing", "mean", "median", "std", "min", "q1", "q3", "max"]
    if VARIABLES[key]["additive"]:
        columns.append("Total (" + unit + ")")
        names.append("total")
    if VARIABLES[key]["ratio"]:
        columns.append("Overall ratio (" + unit + ")")
        names.append("overall")
    rows = [[row[name] for name in names] for row in groups]
    return columns, rows


DATASET_COLUMNS = [
    ("facility_name", "Facility"),
    ("facility_id", "Facility ID"),
    ("state", "State"),
    ("unit_id", "Unit"),
    ("unit_type", "Unit Type"),
    ("primary_fuel", "Primary Fuel"),
    ("year", "Year"),
    ("so2_controls", "SO2 Controls"),
    ("nox_controls", "NOx Controls"),
    ("programs", "Programs"),
]


def dataset_table(frame):
    """The analytical dataset: identifying columns, measured values and every derived indicator."""
    columns = [label for _, label in DATASET_COLUMNS]
    names = [name for name, _ in DATASET_COLUMNS]
    for key in VARIABLES:
        columns.append(variable_title(key))
        names.append(key)

    table = pd.DataFrame(index=frame.index)
    for name in names:
        values = frame[name]
        if name in ("facility_id", "year"):
            table[name] = values.astype("Int64")   # whole numbers, missing stays missing
        elif name in VARIABLES:
            table[name] = values.replace([np.inf, -np.inf], np.nan)
        else:
            # CAMPD lists several controls as "A<br>B" or "A|B"
            text = values.astype("object").where(values.notna(), None)
            table[name] = text.map(lambda value: None if value is None
                                   else str(value).replace("<br>", "; ").replace("|", "; "))

    # Missing values become None (an empty cell) rather than NaN
    table = table.astype("object").where(table.notna(), None)
    return columns, table.values.tolist()


def export_file(columns, rows, metadata_lines, file_format="csv"):
    """
    CSV: the metadata as "# name, value" lines, a blank line, then the table.
         (pandas reads it with read_csv(path, comment="#").)
    Excel: the table on a "Results" sheet and the metadata on a "Metadata" sheet.
    Returns (file bytes, MIME type, file extension).
    """
    if file_format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Results"
        sheet.append(columns)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(row)

        info = workbook.create_sheet("Metadata")
        info.append(["Item", "Value"])
        for cell in info[1]:
            cell.font = Font(bold=True)
        for name, value in metadata_lines:
            info.append([name, value])
        info.column_dimensions["A"].width = 34
        info.column_dimensions["B"].width = 110

        buffer = io.BytesIO()
        workbook.save(buffer)
        return (buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx")

    output = io.StringIO()
    writer = csv.writer(output)
    for name, value in metadata_lines:
        writer.writerow(["# " + name, value])
    writer.writerow([])
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return output.getvalue().encode("utf-8"), "text/csv", "csv"


# ---------- Formatting for the page ----------

def format_number(value):
    """
    Readable numbers at any size: 1,234,567 / 123.4 / 12.35 / 0.004521.
    None (missing) shows as a dash.
    """
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(number):
        return "—"
    size = abs(number)
    if size == 0:
        return "0"
    if size >= 1000:
        return "{:,.0f}".format(number)
    if size >= 100:
        return "{:,.1f}".format(number)
    if size >= 1:
        return "{:,.2f}".format(number)
    return "{:.4g}".format(number)


def format_compact(value):
    """Large numbers in words: 16,312,000,000 -> "16.3 billion". Smaller numbers as format_number."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(number):
        return "—"
    for limit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(number) >= limit:
            return "{:.3g} {}".format(number / limit, word)
    return format_number(number)


# ---------- Variables available in a selection (proposal 4.1) ----------

AVAILABILITY_GROUPS = [
    ("Facility", [("facility_name", "Facility name"), ("facility_id", "Facility ID"), ("state", "State"),
                  ("county", "County")]),
    ("Unit", [("unit_id", "Unit ID"), ("unit_type", "Unit type"), ("primary_fuel", "Primary fuel"),
              ("secondary_fuel", "Secondary fuel")]),
    ("Annual", [("year", "Reporting year"), ("operating_time", "Operating time (hours)"),
                ("gross_load", "Gross load (MWh)"), ("steam_load", "Steam load (1000 lb)"),
                ("heat_input", "Heat input (mmBtu)"), ("co2_mass", "CO2 mass (short tons)"),
                ("so2_mass", "SO2 mass (short tons)"), ("nox_mass", "NOx mass (short tons)"),
                ("so2_controls", "SO2 controls"), ("nox_controls", "NOx controls"),
                ("pm_controls", "PM controls"), ("programs", "Emissions programs")]),
]

# Blank in these means "none reported", not an unknown value
BLANK_MEANS_NONE = {"so2_controls", "nox_controls", "pm_controls", "secondary_fuel"}


def blank_mask(series):
    """True where a value is missing or an empty string."""
    if series.dtype == object:
        return series.isna() | (series.astype(str).str.strip() == "")
    return series.isna()


def variable_availability(frame):
    """
    Every variable the selection offers, grouped (facility, unit, annual, derived), with how many
    records have no value. Returns (available, missing): available is {group: [{name, usable, note}]},
    missing is a list of {group, name, missing, total, percent, note}.
    """
    total = int(len(frame))
    groups = list(AVAILABILITY_GROUPS)
    groups.append(("Derived indicators", [(key, variable_title(key)) for key, item in VARIABLES.items()
                                          if item["group"] != "Measured"]))
    available = {}
    missing = []
    for group, items in groups:
        available[group] = []
        for column, label in items:
            count = int(blank_mask(frame[column]).sum()) if column in frame.columns else total
            note = "Blank means none reported" if column in BLANK_MEANS_NONE else ""
            available[group].append({"name": label, "usable": total > 0 and count < total, "note": note})
            missing.append({"group": group, "name": label, "missing": count, "total": total,
                            "percent": (count / total * 100) if total else 0.0, "note": note})
    return available, missing


# ---------- Fuel families and facility locations (dashboard, comparisons) ----------

# Three families, so scatter plots and maps never need more than three colors
FUEL_FAMILIES = ["Coal", "Gas", "Oil and other"]


def fuel_family(fuel):
    text = str(fuel or "").lower()
    if "coal" in text:
        return "Coal"
    if "gas" in text:
        return "Gas"
    return "Oil and other"


def facility_locations(facility_ids):
    """{facility ID: (latitude, longitude)} for facilities that have a location."""
    ids = sorted({int(value) for value in facility_ids if pd.notna(value)})
    if not ids:
        return {}
    connection = connect()
    found = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        rows = connection.execute(
            "SELECT epa_facility_id, latitude, longitude FROM facility WHERE epa_facility_id IN ("
            + ",".join("?" * len(chunk)) + ") AND latitude IS NOT NULL AND longitude IS NOT NULL",
            chunk,
        ).fetchall()
        for row in rows:
            found[int(row[0])] = (float(row[1]), float(row[2]))
    connection.close()
    return found


def unit_labels(frame):
    """'Alpha Station (KY) unit 1' for each record."""
    names = frame["facility_name"].fillna(NOT_REPORTED).astype(str)
    states = frame["state"].fillna("").astype(str)
    units = frame["unit_id"].fillna("?").astype(str)
    return names + " (" + states + ") unit " + units


def aggregate(frame, key, labels):
    """
    One value per group for a variable: the total for amounts that add up, the overall ratio
    (total ÷ total) for ratios, otherwise the mean. Returns a DataFrame indexed by group with
    columns value, records, count.
    """
    variable = VARIABLES[key]
    data = pd.DataFrame({"group": labels, "value": frame[key]})
    if variable["ratio"]:
        data["num"] = frame["_num_" + key]
        data["den"] = frame["_den_" + key]
    grouped = data.groupby("group", sort=False)
    table = pd.DataFrame({"records": grouped.size(), "count": grouped["value"].count()})
    if variable["ratio"]:
        scale = frame["_scale_" + key].iloc[0] if len(frame) else 1.0
        table["value"] = safe_ratio(grouped["num"].sum(min_count=1), grouped["den"].sum(min_count=1)) * scale
    elif variable["additive"]:
        table["value"] = grouped["value"].sum(min_count=1)
    else:
        table["value"] = grouped["value"].mean()
    return table


def aggregate_label(key):
    """What aggregate() returns for this variable, in words."""
    if VARIABLES[key]["ratio"]:
        return "Overall ratio"
    if VARIABLES[key]["additive"]:
        return "Total"
    return "Mean"
