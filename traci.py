"""
EPA TRACI 2.2 characterization factors and impact indicators (proposal 4.6).

What this does
  1. Reads the official TRACI 2.2 workbook (or the small extract of it kept in data/) and keeps
     only the factors that match a CAMPD pollutant emitted to air.
  2. Stores them in the traci_factor table with the TRACI version, substance, impact category,
     factor value, unit and the exact place in the source file each one came from.
  3. Turns CAMPD emissions into potential-impact indicators:
         mass (kg) = mass (short tons) × 907.18474
         impact in category c = Σ over pollutants (mass in kg × factor for category c)
     Categories are never added together, because their units and meanings differ.

How CAMPD pollutants are matched to TRACI (no approximate name matching)
  CO2 -> the TRACI row with CAS 124-38-9, which must be named CARBON DIOXIDE
  SO2 -> the TRACI row with CAS 7446-09-5, which must be named SULFUR DIOXIDE
  NOx -> the TRACI row named exactly NITROGEN OXIDES. TRACI gives that row no CAS number, and it
         also lists NITROGEN DIOXIDE and NITRIC OXIDE with different factors; those are never used.
  If a rule finds no row, or more than one, the import stops with an error instead of guessing.

The official workbook
  https://www.epa.gov/system/files/documents/2024-01/traci_2_2.xlsx
  (the same file is in EPA's GitHub repository: https://github.com/USEPA/TRACI, TraciTool/TRACI_2_2.xlsx)

Commands (run from the project folder)
  python traci.py import                  load the extract in data/ (the website also does this on first use)
  python traci.py import traci_2_2.xlsx   load straight from the official workbook
  python traci.py extract traci_2_2.xlsx  rewrite the extract in data/ from the official workbook
  python traci.py show                    list the factors in the database
"""

import csv
import hashlib
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from search import connect

SHORT_TON_KG = 907.18474

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED_EXTRACT = os.path.join(HERE, "data", "traci_2_2_campd_factors.csv")

OFFICIAL_URL = "https://www.epa.gov/system/files/documents/2024-01/traci_2_2.xlsx"
GITHUB_URL = "https://github.com/USEPA/TRACI/raw/master/TraciTool/TRACI_2_2.xlsx"
TRACI_PAGE = "https://www.epa.gov/traci"

SUBSTANCES_SHEET = "Substances"
MEDIUM = "air"

# CAMPD pollutant -> how its TRACI row is found
POLLUTANTS = {
    "co2_mass": {"label": "CO2", "rule": "cas", "cas": "124-38-9", "name": "CARBON DIOXIDE"},
    "so2_mass": {"label": "SO2", "rule": "cas", "cas": "7446-09-5", "name": "SULFUR DIOXIDE"},
    "nox_mass": {"label": "NOx", "rule": "name", "cas": "", "name": "NITROGEN OXIDES"},
}
POLLUTANT_ORDER = ["co2_mass", "so2_mass", "nox_mass"]


def match_rule_text(pollutant):
    rule = POLLUTANTS[pollutant]
    if rule["rule"] == "cas":
        return f"CAS {rule['cas']}, name must be {rule['name']}"
    return f"Exact substance name {rule['name']} (TRACI lists no CAS number for it)"


# Air-emission columns of the Substances sheet -> (key, category name, impact unit).
# TRACI 2.1 called the climate column "Global Warming Air"; both spellings are accepted.
CATEGORY_COLUMNS = {
    "Global Climate Air (kg CO2 eq / kg substance)": ("global_warming", "Global warming", "kg CO2 eq"),
    "Global Warming Air (kg CO2 eq / kg substance)": ("global_warming", "Global warming", "kg CO2 eq"),
    "Acidification Air (kg SO2 eq / kg substance)": ("acidification", "Acidification", "kg SO2 eq"),
    "HH Particulate Air (PM2.5 eq / kg substance)": ("particulate_matter", "Human health: particulate matter",
                                                     "kg PM2.5 eq"),
    "Smog Air (kg O3 eq / kg substance)": ("smog_formation", "Smog formation", "kg O3 eq"),
    "Ozone Depletion Air (kg CFC-11 eq / kg substance)": ("ozone_depletion", "Ozone depletion", "kg CFC-11 eq"),
}
CATEGORY_ORDER = ["global_warming", "acidification", "particulate_matter", "smog_formation", "ozone_depletion"]

DISCLAIMER = ("These are potential impacts, calculated for comparison. They do not measure actual illness, "
              "local exposure or proven environmental damage.")

LIMITATIONS = [
    "TRACI factors are U.S.-average (site-generic) values, so the same ton of SO2 counts the same in every state.",
    "Only CO2, SO2 and NOx are covered, because those are the pollutants CAMPD reports as annual masses. "
    "Other pollutants from the same plants (for example mercury or direct particulate matter) are not included.",
    "TRACI 2.2 removed its eutrophication factors (EPA moved them to a separate spatial dataset), "
    "so eutrophication is not calculated.",
    "TRACI lists nitrogen oxides, nitrogen dioxide and nitric oxide as separate substances with different factors. "
    "As the proposal requires, CAMPD NOx is matched only to the NITROGEN OXIDES row.",
]


# ---------- Reading the official workbook ----------

def format_cas(value):
    """124389 -> "124-38-9". TRACI stores CAS numbers as plain numbers, and "x" when there is none."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text.lower() in ("", "x", "-", "n/a"):
        return ""
    if text.isdigit() and len(text) > 4:
        return text[:-3] + "-" + text[-3:-1] + "-" + text[-1]
    return text


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def workbook_version(workbook):
    """'TRACI 2.2 (updated 3/2/2022)', read from the title sheet."""
    first = workbook[workbook.sheetnames[0]]
    title = None
    updated = None
    for row in first.iter_rows(min_row=1, max_row=5, values_only=True):
        for value in row:
            if not isinstance(value, str):
                continue
            if title is None and value.strip().upper().startswith("TRACI"):
                title = value.strip()
            if "Updated" in value and updated is None:
                updated = value[value.index("Updated") + len("Updated"):].strip(" )")
    if title is None:
        title = first.title
    return f"{title} (updated {updated})" if updated else title


def read_workbook(path):
    """
    The factors for CO2, SO2 and NOx emitted to air, read from the official TRACI workbook.
    Returns a list of dicts, one per factor. Raises ValueError when a match rule doesn't find
    exactly one row.
    """
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    if SUBSTANCES_SHEET not in workbook.sheetnames:
        raise ValueError(f'No "{SUBSTANCES_SHEET}" sheet in {path}')
    version = workbook_version(workbook)
    sheet = workbook[SUBSTANCES_SHEET]
    rows = sheet.iter_rows(values_only=True)
    header = [str(value).strip() if value is not None else "" for value in next(rows)]

    try:
        cas_column = header.index("CAS #")
        name_column = header.index("Substance Name")
    except ValueError:
        raise ValueError('The Substances sheet has no "CAS #" or "Substance Name" column')
    formatted_column = header.index("Formatted CAS #") if "Formatted CAS #" in header else None
    category_columns = [(index, name) for index, name in enumerate(header) if name in CATEGORY_COLUMNS]
    if not category_columns:
        raise ValueError("None of the expected air-emission impact columns were found")

    found = {pollutant: [] for pollutant in POLLUTANTS}
    for excel_row, row in enumerate(rows, start=2):
        if row is None or len(row) <= name_column:
            continue
        name = str(row[name_column] or "").strip().upper()
        cas = format_cas(row[cas_column])
        if not cas and formatted_column is not None:
            cas = format_cas(row[formatted_column])
        for pollutant, rule in POLLUTANTS.items():
            if rule["rule"] == "cas" and cas == rule["cas"]:
                found[pollutant].append((excel_row, row, name, cas))
            elif rule["rule"] == "name" and name == rule["name"]:
                found[pollutant].append((excel_row, row, name, cas))
    workbook.close()

    source_file = os.path.basename(path)
    sha256 = file_sha256(path)
    factors = []
    for pollutant in POLLUTANT_ORDER:
        rule = POLLUTANTS[pollutant]
        matches = found[pollutant]
        if len(matches) != 1:
            raise ValueError(f"{match_rule_text(pollutant)}: expected exactly one TRACI row, found {len(matches)}")
        excel_row, row, name, cas = matches[0]
        if name != rule["name"]:
            raise ValueError(f"CAS {rule['cas']} is named {name} in this file, not {rule['name']}")
        for index, column_name in category_columns:
            value = row[index] if index < len(row) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value == 0:
                continue   # "n/a" or blank: this substance has no factor in this category
            key, category_name, unit = CATEGORY_COLUMNS[column_name]
            factors.append({
                "traci_version": version,
                "campd_pollutant": pollutant,
                "substance_name": name,
                "cas_number": cas,
                "match_rule": match_rule_text(pollutant),
                "medium": MEDIUM,
                "impact_category": key,
                "impact_category_name": category_name,
                "factor_value": float(value),
                "factor_unit": unit + " / kg substance",
                "source_file": source_file,
                "source_sha256": sha256,
                "source_sheet": SUBSTANCES_SHEET,
                "source_row": excel_row,
                "source_column": column_name,
            })
    return factors


# ---------- The extract kept in the repository ----------

EXTRACT_COLUMNS = ["traci_version", "campd_pollutant", "substance_name", "cas_number", "match_rule", "medium",
                   "impact_category", "impact_category_name", "factor_value", "factor_unit", "source_file",
                   "source_sha256", "source_sheet", "source_row", "source_column"]


def write_extract(factors, path=BUNDLED_EXTRACT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXTRACT_COLUMNS)
        writer.writeheader()
        for factor in factors:
            writer.writerow({column: factor.get(column) for column in EXTRACT_COLUMNS})


def read_extract(path=BUNDLED_EXTRACT):
    factors = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["factor_value"] = float(row["factor_value"])
            row["source_row"] = int(row["source_row"]) if row.get("source_row") else None
            factors.append(row)
    return factors


# ---------- Storing factors ----------

def import_factors(factors, source_description):
    """
    Replace the stored factors for this TRACI version with these, and record the import as a
    dataset (provenance). Returns the number of factors stored.
    """
    import json
    from database import SessionLocal
    from models import Dataset, TraciFactor

    if not factors:
        raise ValueError("No TRACI factors to import")
    version = factors[0]["traci_version"]
    now = datetime.now().isoformat(timespec="seconds")

    session = SessionLocal()
    try:
        session.query(TraciFactor).filter(TraciFactor.traci_version == version).delete()
        dataset = Dataset(
            dataset_name=f"EPA {version.split(' (')[0]} characterization factors",
            data_source="EPA TRACI",
            retrieval_date=now,
            og_filename=factors[0].get("source_file"),
            num_raw_records=len(factors),
            num_accepted_records=len(factors),
            notes=(f"{source_description}. Factors for CAMPD CO2, SO2 and NOx emitted to air. "
                   f"Source file SHA-256 {factors[0].get('source_sha256')}."),
            query_parameters=json.dumps({
                "traci_version": version,
                "match_rules": {POLLUTANTS[p]["label"]: match_rule_text(p) for p in POLLUTANT_ORDER},
                "official_file": OFFICIAL_URL,
            }),
        )
        session.add(dataset)
        session.flush()
        for factor in factors:
            values = {column: factor.get(column) for column in EXTRACT_COLUMNS}
            session.add(TraciFactor(imported_at=now, dataset_id=dataset.dataset_id, **values))
        session.commit()
        return len(factors)
    finally:
        session.close()


def stored_factors(version=None):
    """
    The stored factors of one TRACI version (the most recently imported one unless a version is
    given), as dicts in a fixed order. Factors from different versions are never mixed.
    An empty list if none are loaded yet.
    """
    connection = connect()
    try:
        if version is None:
            latest = connection.execute(
                "SELECT traci_version FROM traci_factor ORDER BY traci_factor_id DESC LIMIT 1").fetchone()
            version = latest[0] if latest else None
        rows = connection.execute("SELECT * FROM traci_factor WHERE traci_version = ?", (version,)).fetchall()
    except Exception:
        rows = []
    connection.close()
    factors = [dict(row) for row in rows]
    factors.sort(key=lambda f: (category_position(f["impact_category"]), POLLUTANT_ORDER.index(f["campd_pollutant"])
                                if f["campd_pollutant"] in POLLUTANT_ORDER else 9))
    return factors


def category_position(key):
    return CATEGORY_ORDER.index(key) if key in CATEGORY_ORDER else len(CATEGORY_ORDER)


def ensure_factors():
    """Load the extract in data/ the first time impacts are needed. Returns the stored factors."""
    factors = stored_factors()
    if not factors and os.path.exists(BUNDLED_EXTRACT):
        import_factors(read_extract(), f"Loaded automatically from {os.path.basename(BUNDLED_EXTRACT)}")
        factors = stored_factors()
    return factors


# ---------- Impact calculation ----------

def categories(factors):
    """[(key, name, unit), ...] for the categories that have at least one factor, in a fixed order."""
    seen = {}
    for factor in factors:
        unit = factor["factor_unit"].replace(" / kg substance", "")
        seen.setdefault(factor["impact_category"], (factor["impact_category_name"], unit))
    return [(key, seen[key][0], seen[key][1]) for key in sorted(seen, key=category_position)]


def factor_lookup(factors):
    """{category: {pollutant: factor value}}."""
    lookup = {}
    for factor in factors:
        lookup.setdefault(factor["impact_category"], {})[factor["campd_pollutant"]] = factor["factor_value"]
    return lookup


def add_impacts(frame, factors):
    """
    Add, for every record and category:
      impact_<category>              the potential impact (missing if any pollutant it needs is missing)
      impact_<category>__<pollutant> each pollutant's contribution
    """
    lookup = factor_lookup(factors)
    for category, by_pollutant in lookup.items():
        total = pd.Series(0.0, index=frame.index)
        complete = pd.Series(True, index=frame.index)
        for pollutant, value in by_pollutant.items():
            mass = pd.to_numeric(frame[pollutant], errors="coerce") if pollutant in frame else \
                pd.Series(np.nan, index=frame.index)
            contribution = mass * SHORT_TON_KG * value
            frame[f"impact_{category}__{pollutant}"] = contribution
            complete &= contribution.notna()
            total = total + contribution.fillna(0.0)
        frame[f"impact_{category}"] = total.where(complete)
    return frame


def summarize(frame, factors):
    """
    Totals for the whole selection, one entry per category:
      total, records used and missing, gross load of those records, impact per MWh,
      and each pollutant's contribution and share.
    """
    results = []
    for key, name, unit in categories(factors):
        column = f"impact_{key}"
        values = frame[column] if column in frame else pd.Series(dtype="float64")
        used = values.notna()
        total = float(values[used].sum()) if used.any() else None
        load = pd.to_numeric(frame["gross_load"], errors="coerce") if len(frame) else pd.Series(dtype="float64")
        with_load = used & load.notna() & (load > 0)
        load_total = float(load[with_load].sum()) if with_load.any() else None
        intensity = None
        if load_total:
            intensity = float(values[with_load].sum()) / load_total

        contributions = []
        for pollutant in POLLUTANT_ORDER:
            part = f"impact_{key}__{pollutant}"
            if part not in frame:
                continue
            amount = float(frame.loc[used, part].sum()) if used.any() else None
            share = (amount / total * 100) if (total and amount is not None) else None
            contributions.append({"pollutant": pollutant, "label": POLLUTANTS[pollutant]["label"],
                                  "amount": amount, "share": share})

        results.append({
            "key": key, "name": name, "unit": unit,
            "total": total,
            "records": int(len(values)),
            "used": int(used.sum()),
            "missing": int((~used).sum()),
            "load_total": load_total,
            "load_records": int(with_load.sum()),
            "intensity": intensity,
            "intensity_unit": unit + " per MWh",
            "contributions": contributions,
        })
    return results


def summarize_groups(frame, factors, labels):
    """
    The same totals for each group (state, fuel, facility...). `labels` gives each record's group.
    Returns {category: [ {group, total, intensity, used, missing, contributions{pollutant: amount}} ]}.
    """
    output = {}
    load = pd.to_numeric(frame["gross_load"], errors="coerce")
    for key, name, unit in categories(factors):
        column = f"impact_{key}"
        data = pd.DataFrame({"group": labels, "impact": frame[column], "load": load})
        data["used"] = data["impact"].notna()
        data["load_ok"] = data["used"] & data["load"].notna() & (data["load"] > 0)
        data["impact_with_load"] = data["impact"].where(data["load_ok"])
        data["load_used"] = data["load"].where(data["load_ok"])
        parts = []
        for pollutant in POLLUTANT_ORDER:
            part = f"impact_{key}__{pollutant}"
            if part in frame:
                data[pollutant] = frame[part].where(data["used"])
                parts.append(pollutant)

        grouped = data.groupby("group", sort=False)
        table = pd.DataFrame({
            "records": grouped.size(),
            "used": grouped["used"].sum(),
            "total": grouped["impact"].sum(min_count=1),
            "impact_with_load": grouped["impact_with_load"].sum(min_count=1),
            "load_used": grouped["load_used"].sum(min_count=1),
        })
        for pollutant in parts:
            table[pollutant] = grouped[pollutant].sum(min_count=1)

        rows = []
        for group, row in table.iterrows():
            load_used = row["load_used"]
            intensity = None
            if pd.notna(load_used) and load_used > 0 and pd.notna(row["impact_with_load"]):
                intensity = float(row["impact_with_load"] / load_used)
            rows.append({
                "group": group,
                "records": int(row["records"]),
                "used": int(row["used"]),
                "missing": int(row["records"] - row["used"]),
                "total": None if pd.isna(row["total"]) else float(row["total"]),
                "intensity": intensity,
                "contributions": {p: (None if pd.isna(row[p]) else float(row[p])) for p in parts},
            })
        output[key] = rows
    return output


def factors_table(factors):
    columns = ["TRACI version", "CAMPD pollutant", "TRACI substance", "CAS number", "How it was matched", "Medium",
               "Impact category", "Factor", "Factor unit", "Source file", "Source sheet", "Source row",
               "Source column", "Source file SHA-256"]
    rows = []
    for f in factors:
        rows.append([f["traci_version"], POLLUTANTS.get(f["campd_pollutant"], {}).get("label", f["campd_pollutant"]),
                     f["substance_name"], f["cas_number"] or "None listed", f["match_rule"], f["medium"],
                     f["impact_category_name"], f["factor_value"], f["factor_unit"], f["source_file"],
                     f["source_sheet"], f["source_row"], f["source_column"], f["source_sha256"]])
    return columns, rows


# ---------- Command line ----------

def main(arguments):
    if not arguments or arguments[0] not in ("import", "extract", "show"):
        print(__doc__)
        return 1
    command = arguments[0]

    if command == "extract":
        if len(arguments) < 2:
            print("Usage: python traci.py extract path/to/traci_2_2.xlsx [output.csv]")
            return 1
        factors = read_workbook(arguments[1])
        output = arguments[2] if len(arguments) > 2 else BUNDLED_EXTRACT
        write_extract(factors, output)
        print(f"Wrote {len(factors)} factors from {factors[0]['traci_version']} to {output}")
        return 0

    if command == "import":
        if len(arguments) > 1:
            factors = read_workbook(arguments[1])
            source = f"Read from {os.path.basename(arguments[1])}"
        else:
            factors = read_extract()
            source = f"Read from {os.path.basename(BUNDLED_EXTRACT)}"
        count = import_factors(factors, source)
        print(f"Stored {count} {factors[0]['traci_version']} factors.")
        arguments = ["show"]

    for factor in stored_factors():
        print(f"{POLLUTANTS[factor['campd_pollutant']]['label']:>4}  {factor['impact_category_name']:<34} "
              f"{factor['factor_value']:>12.6g}  {factor['factor_unit']:<28} "
              f"({factor['substance_name']}, row {factor['source_row']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
