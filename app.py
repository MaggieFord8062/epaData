import csv
import io
import json
import os
import re
import uuid
from datetime import date, datetime
from urllib.parse import urlencode

from flask import Flask, render_template, request, jsonify, Response, abort, redirect, send_file, flash
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from sqlalchemy import func
from database import SessionLocal
from client import CAMPDClient, CAMPDError
from dotenv import load_dotenv
from models import Facility, Unit, AnnualRecord, HourlyRecord, Dataset, UploadedFile
import analysis
import comparison
import dashboard
import retrieval_jobs
import smart_search
import traci
import uploads
from retrieval import retrieve_hourly_records
from search import (search_data, advance_search, find_facilities, compare_facilities,
                    facility_units, RANK_FIELDS, COMPARE_LIMIT)

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "epaData-local-session-key")
app.json.sort_keys = False  # keep result columns in the order search.py lists them

# Refuse uploads over the limit before they're even read (a little extra for the form itself)
app.config["MAX_CONTENT_LENGTH"] = uploads.MAX_FILE_BYTES + 1024 * 1024
os.makedirs(uploads.UPLOAD_DIR, exist_ok=True)


@app.template_filter("fromjson")
def fromjson(text):
    """Lets templates read JSON text stored in the database, like a dataset's query parameters."""
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


@app.template_filter("controls")
def controls(text):
    """CAMPD separates multiple controls with "<br>" or "|"; show them as a readable list."""
    if not text:
        return text
    return ", ".join(part.strip() for part in str(text).replace("<br>", "|").split("|") if part.strip())


def drop_empty_columns(results):
    """Remove columns that are empty in every row (like County, until it's filled in)."""
    if not results:
        return results
    keep = [key for key in results[0] if any(row[key] not in (None, "") for row in results)]
    return [{key: row[key] for key in keep} for row in results]


def clean_rows(results):
    """Drop the link-only columns (names starting with "_") and make control lists readable."""
    cleaned = []
    for row in results:
        values = {}
        for key, value in row.items():
            if key.startswith("_"):
                continue
            if isinstance(value, str):
                # CAMPD lists multiple controls as "A<br>B" or "A|B"
                value = value.replace("<br>", "; ").replace("|", "; ")
            values[key] = value
        cleaned.append(values)
    return cleaned


def file_name(name_parts, extension):
    # e.g. epaData_KY_Coal_2026-09-25.csv
    safe_parts = ["".join(ch for ch in str(part) if ch.isalnum() or ch in "-_") for part in name_parts if part]
    return "_".join(["epaData"] + [part for part in safe_parts if part] + [date.today().isoformat()]) + "." + extension


def file_response(results, name_parts, file_format="csv"):
    """Send rows as a CSV file (the default) or an Excel file."""
    rows = clean_rows(results)
    columns = list(rows[0].keys()) if rows else []

    if file_format == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "epaData"
        sheet.append(columns)
        for row in rows:
            sheet.append([row[column] for column in columns])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return Response(
            buffer.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_name(name_parts, "xlsx")}"'},
        )

    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name(name_parts, "csv")}"'},
    )


def csv_response(results, name_parts):
    return file_response(results, name_parts, "csv")


def distinct_values(session, column):
    """Every non-empty value stored in a column, sorted."""
    return sorted({v[0] for v in session.query(column).distinct().all() if v[0] not in (None, "")})


@app.route("/")
def home():
    session = SessionLocal()

    stats = {
        "facilities": session.query(Facility).count(),
        "units": session.query(Unit).count(),
        "records": session.query(AnnualRecord).count(),
        "datasets": session.query(Dataset).count(),
        "states": session.query(Facility.state).distinct().count(),
        "years": sorted(distinct_values(session, AnnualRecord.year)),
    }

    # Rank by the most recent year only, so 2015-2025 totals aren't mixed together
    stats["latest_year"] = stats["years"][-1] if stats["years"] else None
    stats["last_retrieval"] = session.query(func.max(Dataset.retrieval_date)).scalar()
    stats["uploads"] = session.query(UploadedFile).filter(UploadedFile.status == "imported").count()

    top_emitters = (
        session.query(
            Facility.epa_facility_id,
            Facility.facility_name,
            Facility.state,
            func.sum(AnnualRecord.co2_mass).label("co2"),
        )
        .join(AnnualRecord, Facility.epa_facility_id == AnnualRecord.epa_facility_id)
        .filter(AnnualRecord.year == stats["latest_year"])
        .group_by(Facility.epa_facility_id)
        .order_by(func.sum(AnnualRecord.co2_mass).desc())
        .limit(5)
        .all()
    )

    session.close()

    return render_template("home.html", stats=stats, top_emitters=top_emitters)


@app.route("/explorer")
def explorer():
    """The old browse page. Exploring now happens on the search page."""
    return redirect("/explore")


@app.route("/datasets")
def datasets():
    """Provenance: every API pull and upload, newest first."""
    session = SessionLocal()

    rows = (
        session.query(Dataset, func.count(AnnualRecord.annual_record_id).label("records"))
        .outerjoin(AnnualRecord, AnnualRecord.dataset_id == Dataset.dataset_id)
        .group_by(Dataset.dataset_id)
        .order_by(Dataset.dataset_id.desc())
        .all()
    )
    unlinked = session.query(AnnualRecord).filter(AnnualRecord.dataset_id.is_(None)).count()

    session.close()

    return render_template("datasets.html", rows=rows, unlinked=unlinked)


# CAM API parameter -> (search filter, readable label)
QUERY_TO_SEARCH = {
    "year": ("reporting_year", "Year"),
    "stateCode": ("state", "State"),
    "facilityId": ("epa_facility_id", "Facility ID"),
    "unitFuelType": ("primary_fuel", "Fuel type"),
    "unitType": ("unit_type", "Unit type"),
    "controlTechnologies": ("control_any", "Control technology"),
}

DATASET_PAGE_SIZE = 50


@app.route("/datasets/<int:dataset_id>")
def dataset_detail(dataset_id):
    """
    One retrieval or upload: where it came from, what was asked for, the counts,
    and the records it covers. A repeat retrieval stores nothing new, so this shows both
    the records its query covers and the ones it was first to store.
    """
    session = SessionLocal()
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        session.close()
        abort(404)
    stored_count = session.query(AnnualRecord).filter(AnnualRecord.dataset_id == dataset_id).count()
    upload = session.query(UploadedFile).filter(UploadedFile.dataset_id == dataset_id).first()
    session.close()

    query = fromjson(dataset.query_parameters)
    query_labels = []
    covered_filters = {}
    for parameter, value in query.items():
        search_field, label = QUERY_TO_SEARCH.get(parameter, (None, parameter))
        query_labels.append((label, value))
        if search_field:
            covered_filters[search_field] = value

    # Which records to list: an upload lists what it stored; an API pull lists what its query covers
    show = request.args.get("show")
    if show not in ("covered", "stored"):
        show = "covered" if covered_filters else "stored"
    filters = covered_filters if show == "covered" else {"dataset_id": dataset_id}

    rows = search_data(**filters) if filters else []
    total = len(rows)
    pages = max(1, -(-total // DATASET_PAGE_SIZE))
    page = min(max(request.args.get("page", 1, type=int), 1), pages)
    page_rows = rows[(page - 1) * DATASET_PAGE_SIZE: page * DATASET_PAGE_SIZE]

    # The Search page can open these records when every filter is one it has a field for
    search_url = None
    if show == "covered" and covered_filters and "control_any" not in covered_filters:
        search_url = "/explore?" + urlencode(covered_filters)

    return render_template(
        "dataset.html",
        dataset=dataset,
        query_labels=query_labels,
        stored_count=stored_count,
        covered_available=bool(covered_filters),
        show=show,
        rows=page_rows,
        total=total,
        page=page,
        pages=pages,
        page_size=DATASET_PAGE_SIZE,
        search_url=search_url,
        download_url="/download?" + urlencode(filters) if filters else None,
        upload=upload,
    )


@app.route("/facility/<int:facility_id>")
def facility_detail(facility_id):
    """Facility page with annual summaries and a selector for hourly records."""
    session = SessionLocal()
    try:
        facility = session.get(Facility, facility_id)
        if facility is None:
            abort(404)

        units = (
            session.query(Unit, func.min(AnnualRecord.year).label("first_year"),
                          func.max(AnnualRecord.year).label("last_year"),
                          func.count(AnnualRecord.annual_record_id).label("records"))
            .outerjoin(AnnualRecord, AnnualRecord.internal_unit_key == Unit.internal_unit_key)
            .filter(Unit.epa_facility_id == facility_id)
            .group_by(Unit.internal_unit_key).order_by(Unit.epa_unit_id).all()
        )
        
        # Records used by the facility's data-quality summary
        annual_records = (
            session.query(AnnualRecord)
            .filter(AnnualRecord.epa_facility_id == facility_id)
            .all()
        )

        unit_records = (
            session.query(Unit)
            .filter(Unit.epa_facility_id == facility_id)
            .order_by(Unit.epa_unit_id)
            .all()
        )
        hourly_records = (
            session.query(HourlyRecord)
            .join(Unit, HourlyRecord.internal_unit_key == Unit.internal_unit_key)
            .filter(Unit.epa_facility_id == facility_id)
            .all()
        )

        # Variables shown in the summary.
        # Each entry is (display label, model attribute).
        variable_definitions = {
            "Facility": [
                ("Facility ID", "epa_facility_id"),
                ("Facility Name", "facility_name"),
                ("State", "state"),
                ("County", "county"),
                ("Source Category", "source_category"),
                ("Latitude", "latitude"),
                ("Longitude", "longitude"),
            ],
            "Unit": [
                ("Unit ID", "epa_unit_id"),
                ("Unit Type", "unit_type"),
                ("Primary Fuel", "primary_fuel"),
                ("Secondary Fuel", "secondary_fuel"),
                ("Operating Date", "operating_date"),
                ("Retirement Date", "retirement_date"),
            ],
            "Annual": [
                ("Reporting Year", "year"),
                ("Operating Time", "operating_time"),
                ("Gross Load", "gross_load"),
                ("Steam Load", "steam_load"),
                ("Heat Input", "heat_input"),
                ("CO2 Mass", "co2_mass"),
                ("SO2 Mass", "so2_mass"),
                ("NOx Mass", "nox_mass"),
                ("SO2 Controls", "so2_control_info"),
                ("NOx Controls", "nox_control_info"),
                ("PM Controls", "pm_control_info"),
            ],
            "Hourly": [
                ("Timestamp", "timestamp"),
                ("Operating Time", "operating_time"),
                ("Gross Load", "gross_load"),
                ("Heat Input", "heat_input"),
                ("CO2 Mass", "co2_mass"),
                ("SO2 Mass", "so2_mass"),
                ("NOx Mass", "nox_mass"),
                ("Mercury Mass", "hg_mass"),
            ],
        }

        records_by_group = {
            "Facility": [facility],
            "Unit": unit_records,
            "Annual": annual_records,
            "Hourly": hourly_records,
        }

        available_variables = {}
        missing_summary = {}

        for group, definitions in variable_definitions.items():
            available_variables[group] = []
            missing_summary[group] = []

            records = records_by_group[group]
            total = len(records)

            for label, attribute in definitions:
                values = [
                    getattr(record, attribute, None)
                    for record in records
                ]

                missing = sum(
                    value is None or (
                        isinstance(value, str) and not value.strip()
                    )
                    for value in values
                )

                available_variables[group].append({
                    "name": label,
                    "usable": any(
                        value is not None and (
                            not isinstance(value, str) or value.strip()
                        )
                        for value in values
                    ),
                })

                missing_summary[group].append({
                    "name": label,
                    "missing": missing,
                    "total": total,
                    "percent": (missing / total * 100) if total else None,
                })

        yearly = (
            session.query(AnnualRecord.year,
                          func.count(AnnualRecord.annual_record_id).label("units"),
                          func.sum(AnnualRecord.operating_time).label("operating_time"),
                          func.sum(AnnualRecord.gross_load).label("gross_load"),
                          func.sum(AnnualRecord.heat_input).label("heat_input"),
                          func.sum(AnnualRecord.co2_mass).label("co2"),
                          func.sum(AnnualRecord.so2_mass).label("so2"),
                          func.sum(AnnualRecord.nox_mass).label("nox"))
            .filter(AnnualRecord.epa_facility_id == facility_id)
            .group_by(AnnualRecord.year).order_by(AnnualRecord.year.desc()).all()
        )
        sources = (
            session.query(Dataset).join(AnnualRecord, AnnualRecord.dataset_id == Dataset.dataset_id)
            .filter(AnnualRecord.epa_facility_id == facility_id).distinct()
            .order_by(Dataset.reporting_year.desc(), Dataset.dataset_id.desc()).all()
        )
        choice_rows = (
            session.query(Unit.internal_unit_key, Unit.epa_unit_id, AnnualRecord.year)
            .join(AnnualRecord, AnnualRecord.internal_unit_key == Unit.internal_unit_key)
            .filter(Unit.epa_facility_id == facility_id).distinct()
            .order_by(Unit.epa_unit_id, AnnualRecord.year.desc()).all()
        )
        # One selector option per unit; the selected date determines the year.
        hourly_choices = list({r.internal_unit_key: (r.internal_unit_key, r.epa_unit_id)
                               for r in choice_rows}.values())
        hourly_choices.sort(key=lambda item: (item[1], item[0]))
        selected = request.args.get("hourly_choice", "")
        selected_date = request.args.get("hourly_date", date.today().isoformat())
        hourly_records, hourly_total = [], 0
        if selected:
            try:
                selected_key = int(selected)
                date.fromisoformat(selected_date)
                valid = any(k == selected_key for k, _ in hourly_choices)
                if valid:
                    query = session.query(HourlyRecord).filter(
                        HourlyRecord.internal_unit_key == selected_key,
                        HourlyRecord.timestamp.like(f"{selected_date}%"),
                    ).order_by(HourlyRecord.timestamp.asc())
                    hourly_total = query.count()
                    hourly_records = query.limit(100).all()
                else:
                    selected = ""
            except (ValueError, TypeError):
                selected = ""
                selected_date = date.today().isoformat()
        max_co2 = max([row.co2 or 0 for row in yearly] or [0])
        return render_template("facility.html", facility=facility, units=units, yearly=yearly,
                               sources=sources, max_co2=max_co2, hourly_choices=hourly_choices,
                               selected_hourly_choice=selected, selected_hourly_date=selected_date,
                               hourly_records=hourly_records, hourly_total=hourly_total, annual_records=annual_records,
                                available_variables=available_variables, missing_summary=missing_summary)
    finally:
        session.close()


@app.route("/facility/<int:facility_id>/hourly/import", methods=["POST"])
def import_facility_hourly(facility_id):
    """Retrieve hourly emissions for one selected unit and calendar day."""
    unit_key = request.form.get("unit_key", type=int)
    operating_date = (request.form.get("operating_date") or "").strip()
    choice = str(unit_key or "")
    try:
        parsed_date = date.fromisoformat(operating_date)
    except ValueError:
        parsed_date = None

    session = SessionLocal()
    try:
        facility = session.get(Facility, facility_id)
        unit = session.get(Unit, unit_key) if unit_key else None
        if facility is None or unit is None or unit.epa_facility_id != facility_id or parsed_date is None:
            flash("Choose a valid unit and date.", "error")
            return redirect(f"/facility/{facility_id}")
        exists = session.query(AnnualRecord.annual_record_id).filter_by(
            epa_facility_id=facility_id, internal_unit_key=unit_key, year=parsed_date.year
        ).first()
        if not exists:
            flash("That unit has no annual record for the selected date's year. Import annual data for that year first.", "error")
            return redirect(f"/facility/{facility_id}?hourly_choice={choice}&hourly_date={operating_date}#hourly-records")
        api_key = os.getenv("CAMPD_API_KEY")
        if not api_key:
            flash("CAMPD_API_KEY is missing from your .env file. Add it and restart the app.", "error")
            return redirect(f"/facility/{facility_id}?hourly_choice={choice}&hourly_date={operating_date}#hourly-records")
        result = retrieve_hourly_records(session, CAMPDClient(api_key), unit, operating_date)
        flash(f"Hourly import for {operating_date} finished: received {result['received']:,}, saved {result['inserted']:,}, "
              f"skipped {result['skipped']:,}, rejected {result['rejected']:,}.",
              "success" if result["inserted"] or result["received"] == 0 else "info")
    except CAMPDError as error:
        session.rollback()
        app.logger.exception("CAMPD hourly import failed for facility %s, unit %s, date %s", facility_id, unit_key, operating_date)
        flash(f"EPA hourly retrieval failed: {error}", "error")
    except Exception:
        session.rollback()
        app.logger.exception("Hourly import failed for facility %s, unit %s, date %s", facility_id, unit_key, operating_date)
        flash("Hourly import failed while saving records. Check the VS Code terminal for details.", "error")
    finally:
        session.close()
    return redirect(f"/facility/{facility_id}?hourly_choice={choice}&hourly_date={operating_date}#hourly-records")


@app.route("/unit/<int:unit_key>")
def unit_detail(unit_key):
    """One generating unit: identification, fuel and controls, and every year it reported."""
    session = SessionLocal()

    unit = session.get(Unit, unit_key)
    if unit is None:
        session.close()
        abort(404)

    facility = session.get(Facility, unit.epa_facility_id)

    history = (
        session.query(AnnualRecord, Dataset)
        .outerjoin(Dataset, Dataset.dataset_id == AnnualRecord.dataset_id)
        .filter(AnnualRecord.internal_unit_key == unit_key)
        .order_by(AnnualRecord.year.desc())
        .all()
    )
        # Count annual records for this unit only.
    annual_record_count = len(history)

    # All hourly records currently stored for this unit.
    hourly_records_for_summary = (
        session.query(HourlyRecord)
        .filter(HourlyRecord.internal_unit_key == unit_key)
        .all()
    )

    # Variables to display in the Unit Data Summary.
    variable_definitions = {
        "Facility": [
            ("Facility ID", "epa_facility_id"),
            ("Facility Name", "facility_name"),
            ("State", "state"),
            ("County", "county"),
            ("Source Category", "source_category"),
            ("Latitude", "latitude"),
            ("Longitude", "longitude"),
        ],
        "Unit": [
            ("Unit ID", "epa_unit_id"),
            ("Unit Type", "unit_type"),
            ("Primary Fuel", "primary_fuel"),
            ("Secondary Fuel", "secondary_fuel"),
            ("Operating Date", "operating_date"),
            ("Retirement Date", "retirement_date"),
        ],
        "Annual": [
            ("Reporting Year", "year"),
            ("Operating Time", "operating_time"),
            ("Gross Load", "gross_load"),
            ("Steam Load", "steam_load"),
            ("Heat Input", "heat_input"),
            ("CO2 Mass", "co2_mass"),
            ("SO2 Mass", "so2_mass"),
            ("NOx Mass", "nox_mass"),
            ("SO2 Controls", "so2_control_info"),
            ("NOx Controls", "nox_control_info"),
            ("PM Controls", "pm_control_info"),
        ],
        "Hourly": [
            ("Timestamp", "timestamp"),
            ("Operating Time", "operating_time"),
            ("Gross Load", "gross_load"),
            ("Heat Input", "heat_input"),
            ("CO2 Mass", "co2_mass"),
            ("SO2 Mass", "so2_mass"),
            ("NOx Mass", "nox_mass"),
            ("Mercury Mass", "hg_mass"),
        ],
    }

    # Match each category to the records used to calculate availability.
    records_by_group = {
        "Facility": [facility] if facility else [],
        "Unit": [unit],
        "Annual": [record for record, dataset in history],
        "Hourly": hourly_records_for_summary,
    }

    available_variables = {}
    missing_summary = {}

    for group, variables in variable_definitions.items():
        records = records_by_group[group]
        total = len(records)
        available_variables[group] = []
        missing_summary[group] = []

        for label, field in variables:
            missing = sum(
                getattr(record, field, None) in (None, "")
                for record in records
            )

            available_variables[group].append({
                "name": label,
                "usable": total > 0 and missing < total,
            })

            missing_summary[group].append({
                "name": label,
                "missing": missing,
                "total": total,
                "percent": (missing / total * 100) if total else None,
            })

    # Other units at the same facility, for quick switching
    siblings = (
        session.query(Unit)
        .filter(Unit.epa_facility_id == unit.epa_facility_id, Unit.internal_unit_key != unit_key)
        .order_by(Unit.epa_unit_id)
        .all()
    )

    session.close()

    latest = history[0][0] if history else None
    max_co2 = max([record.co2_mass or 0 for record, _ in history] or [0])

    return render_template(
        "unit.html",
        unit=unit,
        facility=facility,
        history=history,
        latest=latest,
        siblings=siblings,
        max_co2=max_co2,
        annual_record_count=annual_record_count,
        available_variables=available_variables,
        missing_summary=missing_summary,
    )


@app.errorhandler(404)
def not_found(error):
    return render_template("not_found.html"), 404


@app.route("/search")
def search():
    return render_template("search.html")


# ---------- Explore (search) ----------

RANGE_FIELDS = [
    ("co2_mass", "CO2", "tons"),
    ("so2_mass", "SO2", "tons"),
    ("nox_mass", "NOx", "tons"),
    ("gross_load", "Gross load", "MWh"),
    ("heat_input", "Heat input", "mmBtu"),
    ("operating_time", "Operating time", "hours"),
]

SORT_MENU = ["relevance", "newest", "co2-desc", "co2-asc", "so2-desc", "so2-asc", "nox-desc", "nox-asc",
             "load-desc", "heat-desc", "hours-desc", "name-asc"]

REFINEMENT_LABELS = {
    "state": "State", "reporting_year": "Year", "primary_fuel": "Fuel", "unit_type": "Unit type",
    "county": "County", "source_category": "Source", "status": "Status", "year_from": "From",
    "year_to": "To", "epa_facility_id": "Facility ID", "epa_unit_id": "Unit",
    "so2_control": "SO2 control", "nox_control": "NOx control", "pm_control": "PM control", "program": "Program",
}


@app.template_global()
def url_with(params, **changes):
    """The explorer's current URL with some parameters changed (None removes one). Starts again at page 1."""
    updated = {key: value for key, value in params.items() if value not in (None, "")}
    if "page" not in changes:
        updated.pop("page", None)
    for key, value in changes.items():
        if value is None or value == "":
            updated.pop(key, None)
        else:
            updated[key] = value
    return "/explore" + ("?" + urlencode(updated) if updated else "")


@app.template_global()
def facet_label(key, value):
    if key == "state":
        name = smart_search.CODE_TO_STATE.get(value)
        return f"{name} ({value})" if name else value
    if key == "status":
        return "Retired" if value == "retired" else "Operating"
    if key in smart_search.LIST_FACETS and value == smart_search.NO_VALUE:
        return "None reported"
    return value


def explore_params():
    """The explorer's parameters from the URL, without blanks."""
    return {key: value.strip() for key, value in request.args.items() if value.strip()}


@app.route("/explore")
def explore():
    """
    The data explorer: one search box that understands plain words, with refinements
    on the side, sorting, pagination and downloads. Everything lives in the URL.
    """
    params = explore_params()
    result = smart_search.explore(params)
    
    # All records matching the current search and filters, not just the current page
    all_result = smart_search.explore(params, everything=True)
    all_rows = all_result["rows"]

    # Dataset summary
    facility_ids = {
        row.get("Facility ID")
        for row in all_rows
        if row.get("Facility ID") not in (None, "")
    }
    unit_keys = {
        row.get("_unit_key")
        for row in all_rows
        if row.get("_unit_key") not in (None, "")
    }
    years = [
        int(row["Year"])
        for row in all_rows
        if row.get("Year") not in (None, "")
    ]

    dataset_summary = {
        "records": len(all_rows),
        "facilities": len(facility_ids),
        "units": len(unit_keys),
        "first_year": min(years) if years else None,
        "last_year": max(years) if years else None,
    }

    # Variables available for analysis and their missing values (proposal 4.1), including the
    # derived indicators, plus the hourly records stored for these units
    frame = analysis.build_frame(all_rows)
    available_variables, missing_summary = analysis.variable_availability(frame)
    hourly = smart_search.hourly_summary(params)

    q = params.get("q", "")

    # Chips for everything the search understood, each with a link that removes it
    chips = []
    for item in result["parsed"]["understood"]:
        href = None
        if item["text"]:
            href = url_with(params, q=smart_search.query_without(q, item["text"]) or None)
        chips.append({"label": item["label"], "href": href})
    for key, label in REFINEMENT_LABELS.items():
        if params.get(key):
            chips.append({"label": f"{label}: {facet_label(key, params[key])}", "href": url_with(params, **{key: None})})
    for field, label, units in RANGE_FIELDS:
        low = params.get(f"{field}_min")
        high = params.get(f"{field}_max")
        if low or high:
            text = f"{label} {low or 0} to {high}" if (low and high) else (f"{label} over {low}" if low else f"{label} under {high}")
            chips.append({"label": text, "href": url_with(params, **{f"{field}_min": None, f"{field}_max": None})})
    for term in result["parsed"]["terms"]:
        chips.append({"label": f'"{term}"', "href": None})

    corrected_query = q
    for wrong, right in result["parsed"]["corrections"]:
        corrected_query = re.sub(rf"\b{re.escape(wrong)}\b", right, corrected_query, flags=re.IGNORECASE)

    download_params = {key: value for key, value in params.items() if key not in ("page", "per_page")}

    return render_template(
        "explore.html",
        params=params,
        q=q,
        result=result,
        chips=chips,
        corrected_query=corrected_query,
        range_fields=RANGE_FIELDS,
        sort_options=smart_search.SORT_OPTIONS,
        sort_menu=SORT_MENU,
        per_page_choices=smart_search.PER_PAGE_CHOICES,
        query_string=urlencode(download_params),
        dataset_summary=dataset_summary,
        available_variables=available_variables,
        missing_summary=missing_summary,
        hourly=hourly,
        analysis_query=urlencode(analysis_filters(download_params)),
    )


@app.route("/basic-search")
def basic_search():
    """The old search page's address now opens the explorer with the same filters."""
    return redirect("/explore" + ("?" + request.query_string.decode() if request.query_string else ""))


@app.route("/download-explore")
def download_explore():
    """Every result of an explorer search (not just one page), as CSV or Excel."""
    params = explore_params()
    file_format = params.pop("format", "csv")
    result = smart_search.explore(params, everything=True)
    name_parts = [params.get("q", "").replace(" ", "-")[:40], params.get("state"), params.get("reporting_year")]
    return file_response(result["rows"], name_parts, file_format)


@app.route("/api/suggest")
def api_suggest():
    """Suggestions while typing in a search box."""
    return jsonify(smart_search.suggest(request.args.get("q", "")))


@app.route("/api/facilities")
def api_facilities():
    """Called by the facility pickers as you type a facility name."""
    return jsonify(find_facilities(request.args.get("q", "")))


@app.route("/download")
def download():
    """CSV of every record matching the search filters in the URL (all columns, no row limit)."""
    filters = request.args.to_dict()
    filters.pop("page", None)       # a download always includes every matching row,
    filters.pop("per_page", None)   # not just the page on screen
    file_format = filters.pop("format", "csv")
    results = search_data(**filters)
    name_parts = [filters.get(key) for key in ("facility_name", "epa_facility_id", "epa_unit_id",
                                               "state", "reporting_year", "primary_fuel")]
    if filters.get("dataset_id"):
        name_parts.insert(0, f"dataset{filters['dataset_id']}")
    return file_response(results, name_parts, file_format)


@app.route("/download-ranking")
def download_ranking():
    """CSV of a ranking, using the same options as the Rankings form."""
    options = request.args.to_dict()
    if options.get("reporting_year") == "all":
        options.pop("reporting_year")
    results = advance_search(**options)
    name_parts = ["ranking", options.get("type"), options.get("field"), options.get("group"),
                  options.get("state"), options.get("reporting_year")]
    return csv_response(results, name_parts)


@app.route("/advanced-search")
def advanced_search():
    """
    Rankings. The options live in the URL (the form uses GET), so any ranking
    can be bookmarked or shared, e.g. /advanced-search?type=Facility&field=co2_mass&limit=10
    """
    params = {key: value for key, value in request.args.to_dict().items() if value != ""}
    editing = "edit" in params
    params.pop("edit", None)

    if params.get("type") and not editing:
        query = dict(params)
        if query.get("reporting_year") == "all":
            query.pop("reporting_year")  # "All years combined" means no year filter
        results = drop_empty_columns(advance_search(**query))
        return render_template(
            "results.html",
            results=results,
            ranking=params,
            rank_label=RANK_FIELDS.get(params.get("field")),
            download_url="/download-ranking?" + urlencode(params),
            edit_url="/advanced-search?" + urlencode(dict(params, edit=1)),
        )

    session = SessionLocal()
    options = {
        "states": distinct_values(session, Facility.state),
        "years": sorted(distinct_values(session, AnnualRecord.year), reverse=True),
        "unit_types": distinct_values(session, Unit.unit_type),
        "primary_fuels": distinct_values(session, Unit.primary_fuel),
    }
    session.close()

    return render_template(
        "advanced_search.html",
        rank_fields=RANK_FIELDS,
        selected=params,
        **options,
    )


def latest_year():
    session = SessionLocal()
    year = session.query(func.max(AnnualRecord.year)).scalar()
    session.close()
    return year


def all_years():
    session = SessionLocal()
    years = sorted(distinct_values(session, AnnualRecord.year), reverse=True)
    session.close()
    return years


@app.route("/compare")
def compare():
    """
    Facility comparison: up to four facilities side by side for one year.
    The facilities and year are in the URL, e.g. /compare?facility=1364&facility=1356&year=2025
    """
    years = all_years()
    chosen = []
    for value in request.args.getlist("facility"):
        if value.isdigit() and int(value) not in chosen:
            chosen.append(int(value))
    chosen = chosen[:COMPARE_LIMIT]

    year = request.args.get("year", type=int)
    if year not in years:
        year = years[0] if years else None

    data = compare_facilities(chosen, year) if chosen and year else None

    return render_template(
        "compare.html",
        data=data,
        chosen=chosen,
        year=year,
        years=years,
        limit=COMPARE_LIMIT,
        download_url="/download-compare?" + urlencode([("facility", fid) for fid in chosen] + [("year", year)]),
    )


@app.route("/download-compare")
def download_compare():
    """CSV of every unit at the compared facilities for the chosen year."""
    chosen = [value for value in request.args.getlist("facility") if value.isdigit()]
    year = request.args.get("year", type=int) or latest_year()
    data = compare_facilities(chosen, year)
    return csv_response(data["units"], ["comparison", year] + chosen)


@app.route("/history")
def history():
    """
    Historical search: one unit across a range of years, e.g. /history?unit=123&year_from=2015&year_to=2025
    """
    years = all_years()
    unit_key = request.args.get("unit", type=int)
    year_from = request.args.get("year_from", type=int) or (years[-1] if years else None)
    year_to = request.args.get("year_to", type=int) or (years[0] if years else None)
    if year_from and year_to and year_from > year_to:
        year_from, year_to = year_to, year_from

    session = SessionLocal()
    unit = session.get(Unit, unit_key) if unit_key else None
    facility = session.get(Facility, unit.epa_facility_id) if unit else None
    session.close()

    rows = []
    change = None
    if unit:
        filters = {"unit_key": unit_key, "year_from": year_from, "year_to": year_to, "sort": "year", "dir": "asc"}
        rows = search_data(**filters)

        # How CO2 changed between the first and last year in the range
        with_co2 = [row for row in rows if row["CO2 (tons)"] is not None]
        if len(with_co2) >= 2 and with_co2[0]["CO2 (tons)"]:
            first, last = with_co2[0], with_co2[-1]
            change = {
                "first_year": first["Year"],
                "last_year": last["Year"],
                "percent": (last["CO2 (tons)"] - first["CO2 (tons)"]) / first["CO2 (tons)"] * 100,
            }

    max_co2 = max([row["CO2 (tons)"] or 0 for row in rows] or [0])

    return render_template(
        "history.html",
        unit=unit,
        facility=facility,
        units=facility_units(facility.epa_facility_id) if facility else [],
        rows=rows,
        change=change,
        max_co2=max_co2,
        years=years,
        year_from=year_from,
        year_to=year_to,
        download_url="/download?" + urlencode({
            "unit_key": unit_key or "", "year_from": year_from or "", "year_to": year_to or "",
            "sort": "year", "dir": "asc",
        }),
    )


@app.route("/api/units")
def api_units():
    """Units at one facility, for the historical search's unit menu."""
    facility_id = request.args.get("facility", type=int)
    if facility_id is None:
        return jsonify([])
    return jsonify(facility_units(facility_id))


# ---------- Retrieval page ----------

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX",
    "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

FIRST_CAMPD_YEAR = 1995


def retrieval_choices():
    """What each retrieval filter can be set to. Fuel, unit type and control lists come from data already stored."""
    session = SessionLocal()
    fuels = distinct_values(session, Unit.primary_fuel)
    unit_types = distinct_values(session, Unit.unit_type)

    # Control fields can list several technologies at once ("A|B" or "A<br>B"), so split them up
    control_technologies = set()
    for column in (AnnualRecord.so2_control_info, AnnualRecord.nox_control_info, AnnualRecord.pm_control_info):
        for value in distinct_values(session, column):
            for part in str(value).replace("<br>", "|").split("|"):
                if part.strip():
                    control_technologies.add(part.strip())
    session.close()

    return {
        "years": list(range(date.today().year - 1, FIRST_CAMPD_YEAR - 1, -1)),
        "states": US_STATES,
        "fuels": fuels,
        "unit_types": unit_types,
        "controls": sorted(control_technologies),
    }


@app.route("/retrieve", methods=["GET", "POST"])
def retrieve():
    """
    EPA data retrieval: choose filters, pull from the CAM API in the background,
    and watch its status. The API key stays on the server (read from .env).
    """
    choices = retrieval_choices()

    if request.method == "POST":
        form = request.form
        errors = []

        year_value = form.get("year", "").strip()

        if year_value == "":
            year = None  # All Years
        else:
            try:
                year = int(year_value)
                if year not in choices["years"]:
                    errors.append("Choose a valid reporting year.")
            except ValueError:
                year = None
                errors.append("Choose a valid reporting year.")

        # Form field -> (CAM API parameter, allowed values, readable label)
        filter_fields = {
            "state": ("stateCode", choices["states"], "State"),
            "fuel": ("unitFuelType", choices["fuels"], "Fuel type"),
            "unit_type": ("unitType", choices["unit_types"], "Unit type"),
            "control": ("controlTechnologies", choices["controls"], "Control technology"),
        }

        api_filters = {}
        labels = {"Year": year if year is not None else "All years"}
        for field, (parameter, allowed, label) in filter_fields.items():
            value = form.get(field, "").strip()
            if not value:
                continue
            if value not in allowed:
                errors.append(f"{label} \"{value}\" isn't one of the available choices.")
                continue
            api_filters[parameter] = value
            labels[label] = value

        facility_id = form.get("facility_id", "").strip()
        if facility_id:
            if not facility_id.isdigit():
                errors.append("Facility ID must be a number.")
            else:
                api_filters["facilityId"] = int(facility_id)
                labels["Facility"] = form.get("facility_label") or facility_id

        if errors:
            return render_template("retrieve.html", choices=choices, errors=errors, form=form,
                                   job=None, recent=recent_retrievals())

        job_id, started = retrieval_jobs.start_retrieval(
            year,
            api_filters,
            form.get("attributes") == "on",
            labels,
            choices["years"],
        )
        if started:
            # A link to Explore showing what this retrieval covers
            search_params = {
                "reporting_year": year,
                "state": api_filters.get("stateCode", ""),
                "epa_facility_id": api_filters.get("facilityId", ""),
                "primary_fuel": api_filters.get("unitFuelType", ""),
                "unit_type": api_filters.get("unitType", ""),
            }
            retrieval_jobs.get_job(job_id)["search_url"] = "/explore?" + urlencode(
                {key: value for key, value in search_params.items() if value != ""}
            )
        return redirect(f"/retrieve?job={job_id}" + ("" if started else "&busy=1"))

    job = retrieval_jobs.get_job(request.args.get("job", "")) or retrieval_jobs.running_job()
    return render_template(
        "retrieve.html",
        choices=choices,
        errors=[],
        form={},
        job=job,
        busy="busy" in request.args,
        recent=recent_retrievals(),
    )


def recent_retrievals(limit=6):
    session = SessionLocal()
    rows = (
        session.query(Dataset)
        .filter(Dataset.data_source.like("%API%"))
        .order_by(Dataset.dataset_id.desc())
        .limit(limit)
        .all()
    )
    session.close()
    return rows


@app.route("/api/retrieve/<job_id>")
def api_retrieve_status(job_id):
    """Polled by the retrieval page to show live status."""
    job = retrieval_jobs.get_job(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


# ---------- Upload page ----------

def recent_uploads(limit=8):
    session = SessionLocal()
    rows = session.query(UploadedFile).order_by(UploadedFile.upload_id.desc()).limit(limit).all()
    session.close()
    return rows


def upload_page(errors=None, status=200):
    return render_template(
        "upload.html",
        errors=errors or [],
        recent=recent_uploads(),
        max_mb=uploads.MAX_FILE_BYTES // 1024 // 1024,
        required=[uploads.FIELD_LABELS[field] for field in uploads.REQUIRED_FIELDS],
        optional=[uploads.FIELD_LABELS[field] for field in uploads.COLUMN_ALIASES
                  if field not in uploads.REQUIRED_FIELDS],
    ), status


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(error):
    return upload_page([f"That file is too large. The limit is {uploads.MAX_FILE_BYTES // 1024 // 1024} MB."], 413)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    """
    Upload a CSV or Excel file. The file is checked and saved, then the user
    sees a preview and quality report before anything is imported.
    """
    if request.method == "GET":
        return upload_page()

    file = request.files.get("file")
    original_name = file.filename if file else ""

    # Step 1: extension and size
    size = 0
    if file:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
    problems = uploads.check_file(original_name, size)
    if problems:
        return upload_page(problems, 400)

    # Keep the original file under a unique name, so two uploads called data.csv don't collide
    extension = uploads.file_extension(original_name)
    stored_name = f"{uuid.uuid4().hex[:10]}_{secure_filename(original_name) or 'upload.' + extension}"
    stored_path = os.path.join(uploads.UPLOAD_DIR, stored_name)
    file.save(stored_path)

    session = SessionLocal()
    record = UploadedFile(
        original_filename=original_name,
        stored_path=stored_path,
        file_type=extension,
        file_size=size,
        uploaded_at=datetime.now().isoformat(timespec="seconds"),
        status="pending",
    )
    session.add(record)
    session.flush()

    # Steps 2-4: read it, match the columns, check every row
    try:
        result = uploads.analyze(session, stored_path, original_name)
    except Exception as error:
        session.rollback()
        session.close()
        os.remove(stored_path)
        return upload_page([f"The file couldn't be read: {error}"], 400)

    counts = result.get("counts", {})
    record.rows_read = result["rows_read"]
    record.rows_ready = counts.get("ready", 0)
    record.rows_rejected = counts.get("rejected", 0) + counts.get("duplicate", 0)
    session.commit()
    upload_id = record.upload_id
    session.close()

    uploads.save_analysis(upload_id, result)
    return redirect(f"/upload/{upload_id}")


REVIEW_PROBLEM_LIMIT = 300


@app.route("/upload/<int:upload_id>")
def upload_review(upload_id):
    """Step 5: the preview and quality report, with Approve and Cancel."""
    session = SessionLocal()
    record = session.get(UploadedFile, upload_id)
    session.close()
    if record is None:
        abort(404)

    result = uploads.load_analysis(upload_id) or {}
    problems = result.get("problems", [])

    return render_template(
        "upload_review.html",
        upload=record,
        result=result,
        counts=result.get("counts", {}),
        problems=problems[:REVIEW_PROBLEM_LIMIT],
        problem_total=len(problems),
        preview=[item["record"] for item in result.get("records", [])[:15]],
        preview_lines=[item["line"] for item in result.get("records", [])[:15]],
        labels=uploads.FIELD_LABELS,
    )


@app.route("/upload/<int:upload_id>/approve", methods=["POST"])
def upload_approve(upload_id):
    """Step 6: store the approved records."""
    session = SessionLocal()
    record = session.get(UploadedFile, upload_id)
    if record is None:
        session.close()
        abort(404)
    if record.status != "pending":
        session.close()
        return redirect(f"/upload/{upload_id}")

    result = uploads.load_analysis(upload_id)
    if not result or not result.get("records"):
        session.close()
        return redirect(f"/upload/{upload_id}")

    dataset = uploads.import_upload(session, record, result)
    dataset_id = dataset.dataset_id
    session.close()
    return redirect(f"/datasets/{dataset_id}?show=stored")


@app.route("/upload/<int:upload_id>/cancel", methods=["POST"])
def upload_cancel(upload_id):
    """Cancel an upload: nothing is imported and the stored copy of the file is deleted."""
    session = SessionLocal()
    record = session.get(UploadedFile, upload_id)
    if record is not None and record.status == "pending":
        record.status = "cancelled"
        if record.stored_path and os.path.exists(record.stored_path):
            os.remove(record.stored_path)
        record.stored_path = None
        session.commit()
    session.close()
    return redirect("/upload")


@app.route("/upload/<int:upload_id>/report")
def upload_report(upload_id):
    """The data-quality report (every rejected, duplicate, skipped or questionable row) as CSV."""
    result = uploads.load_analysis(upload_id)
    if result is None:
        abort(404)
    return csv_response(uploads.quality_report_rows(result), [f"upload{upload_id}", "quality_report"])


@app.route("/upload/<int:upload_id>/original")
def upload_original(upload_id):
    """Download the original uploaded file, exactly as it was uploaded."""
    session = SessionLocal()
    record = session.get(UploadedFile, upload_id)
    session.close()
    if record is None or not record.stored_path or not os.path.exists(record.stored_path):
        abort(404)
    return send_file(os.path.abspath(record.stored_path), as_attachment=True,
                     download_name=record.original_filename)


# ---------- Download page ----------

@app.route("/downloads")
def downloads():
    """Choose a dataset, filters and a file format, plus provenance and data-quality reports."""
    session = SessionLocal()
    stored = (
        session.query(Dataset, func.count(AnnualRecord.annual_record_id).label("records"))
        .join(AnnualRecord, AnnualRecord.dataset_id == Dataset.dataset_id)
        .group_by(Dataset.dataset_id)
        .order_by(Dataset.dataset_id.desc())
        .all()
    )
    choices = {
        "states": distinct_values(session, Facility.state),
        "years": sorted(distinct_values(session, AnnualRecord.year), reverse=True),
        "fuels": distinct_values(session, Unit.primary_fuel),
        "unit_types": distinct_values(session, Unit.unit_type),
    }
    upload_rows = session.query(UploadedFile).order_by(UploadedFile.upload_id.desc()).all()
    rejected_pulls = (
        session.query(Dataset)
        .filter(Dataset.notes.like("%Rejected%"))
        .order_by(Dataset.dataset_id.desc())
        .all()
    )
    total = session.query(AnnualRecord).count()
    session.close()

    return render_template(
        "downloads.html",
        stored=stored,
        choices=choices,
        upload_rows=upload_rows,
        rejected_pulls=rejected_pulls,
        total=total,
    )


@app.route("/download-records")
def download_records():
    """The Download page's form: records from one dataset (or all), narrowed by filters, as CSV or Excel."""
    params = {key: value for key, value in request.args.items() if value.strip()}
    file_format = params.pop("format", "csv")
    if file_format not in ("csv", "xlsx"):
        file_format = "csv"
    dataset = params.pop("dataset", "all")

    filters = {key: params[key] for key in ("state", "reporting_year", "primary_fuel", "unit_type", "epa_facility_id")
               if key in params}
    if dataset != "all" and dataset.isdigit():
        filters["dataset_id"] = dataset
    filters["sort"] = "facility"

    results = search_data(**filters)
    name_parts = [f"dataset{dataset}" if dataset != "all" else "all", params.get("state"),
                  params.get("reporting_year"), params.get("primary_fuel"), params.get("epa_facility_id")]
    return file_response(results, name_parts, file_format)


@app.route("/download-provenance")
def download_provenance():
    """Every retrieval and upload: source, date, query, counts and notes."""
    file_format = request.args.get("format", "csv")
    session = SessionLocal()
    rows = (
        session.query(Dataset, func.count(AnnualRecord.annual_record_id).label("records"))
        .outerjoin(AnnualRecord, AnnualRecord.dataset_id == Dataset.dataset_id)
        .group_by(Dataset.dataset_id)
        .order_by(Dataset.dataset_id)
        .all()
    )
    uploads_by_dataset = {row.dataset_id: row for row in session.query(UploadedFile).all() if row.dataset_id}
    session.close()

    results = []
    for dataset, records in rows:
        upload = uploads_by_dataset.get(dataset.dataset_id)
        results.append({
            "Dataset ID": dataset.dataset_id,
            "Dataset name": dataset.dataset_name,
            "Data source": dataset.data_source,
            "Reporting year": dataset.reporting_year,
            "Retrieved or uploaded": dataset.retrieval_date,
            "Original file": dataset.og_filename,
            "Query parameters": dataset.query_parameters,
            "Records received": dataset.num_raw_records,
            "Records accepted": dataset.num_accepted_records,
            "Records stored from this dataset": records,
            "Upload ID": upload.upload_id if upload else None,
            "Notes": dataset.notes,
        })
    return file_response(results, ["provenance"], file_format)


# ---------- Phase 2: shared selection for every analysis page ----------
#
# Every analysis page (Statistics, Dashboard, Compare, Impacts) analyzes exactly the records the
# Explore page shows: the Explore filters travel in the URL, and each page adds its own choices.
# These are the URL parameters that are page choices; everything else is an Explore filter.

ANALYSIS_PARAMS = {
    # paging and sorting on Explore, and file downloads
    "page", "per_page", "order", "what", "format", "chart",
    # Statistics
    "variable", "group", "pct", "gsort",
    # Dashboard
    "split", "x", "y", "scale", "corr", "level", "min_load",
    # Compare
    "cmp", "a", "b", "pa_from", "pa_to", "pb_from", "pb_to", "matched",
    # Impacts
    "by", "isort", "per_mwh",
}

ANALYSIS_PAGES = [
    ("/statistics", "Statistics"),
    ("/dashboard", "Dashboard"),
    ("/comparison", "Compare"),
    ("/impacts", "Impacts"),
]

app.add_template_filter(analysis.format_number, "stat")
app.add_template_filter(analysis.format_compact, "compact")


@app.template_filter("cell")
def table_cell(value, column=""):
    """A value in a chart's number table: years and ranks as they are, other numbers readable."""
    if value is None:
        return "—"
    if isinstance(value, bool) or isinstance(value, str):
        return value
    name = str(column).lower()
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer() and abs(value) < 1e15):
        if any(word in name for word in ("year", "rank", "id", "code")):
            return str(int(value))
        return "{:,}".format(int(value))
    return analysis.format_number(value)


@app.template_filter("pvalue")
def p_value(value):
    if value is None:
        return "—"
    return "< 0.001" if value < 0.001 else "{:.3f}".format(value)


def analysis_filters(params):
    """The Explore filters in a set of URL parameters (the page choices removed)."""
    return {key: value for key, value in params.items() if key not in ANALYSIS_PARAMS}


def analysis_selection():
    """
    The selected records for an analysis page.
    Returns (all URL parameters, Explore filters, Explore result, analysis DataFrame).
    """
    params = explore_params()
    filters = analysis_filters(params)
    result = smart_search.explore(filters, everything=True)
    frame = analysis.build_frame(result["rows"])
    return params, filters, result, frame


def chosen_variable(params, default=analysis.DEFAULT_VARIABLE, allowed=None):
    variable = params.get("variable")
    allowed = allowed or analysis.VARIABLES
    return variable if variable in allowed else default


def page_url(path, filters, **choices):
    """A page's URL with the same selection and the given choices (blank choices are left out)."""
    values = dict(filters)
    for key, value in choices.items():
        if value not in (None, ""):
            values[key] = value
    return path + ("?" + urlencode(values) if values else "")


def selection_context(filters, result, frame, variable=None):
    """What every analysis page shows about the selection, and links to the other pages."""
    explore_url = "/explore" + ("?" + urlencode(filters) if filters else "")
    return {
        "labels": selection_labels(filters, result),
        "selection": analysis.selection_summary(frame),
        "explore_url": explore_url,
        "partial": result["partial"],
        "analysis_pages": [(path, label, page_url(path, filters, variable=variable))
                           for path, label in ANALYSIS_PAGES],
        "filters": filters,
    }


def statistics_request():
    """
    The Statistics page's choices and the selected records.
    Returns (choices, Explore filters, Explore result, analysis DataFrame).
    """
    params, filters, result, frame = analysis_selection()
    variable = chosen_variable(params)
    group = params.get("group") if params.get("group") in analysis.GROUPS else ""
    gsort = params.get("gsort")
    if gsort not in analysis.GROUP_SORTS:
        gsort = analysis.default_group_sort(variable, group)

    choices = {
        "variable": variable,
        "group": group,
        "gsort": gsort,
        "pct_text": params.get("pct", ""),
        "percentiles": analysis.parse_percentiles(params.get("pct")),
    }
    return choices, filters, result, frame


def selection_labels(filters, result):
    """Plain-language labels for every filter in the selection, e.g. "State: Kentucky (KY)"."""
    labels = [item["label"] for item in result["parsed"]["understood"]]
    for key, label in REFINEMENT_LABELS.items():
        if filters.get(key):
            labels.append(f"{label}: {facet_label(key, filters[key])}")
    for field, label, units in RANGE_FIELDS:
        low = filters.get(f"{field}_min")
        high = filters.get(f"{field}_max")
        if low and high:
            labels.append(f"{label} {low} to {high} {units}")
        elif low:
            labels.append(f"{label} at least {low} {units}")
        elif high:
            labels.append(f"{label} at most {high} {units}")
    for term in result["parsed"]["terms"]:
        labels.append(f'Text: "{term}"')
    return labels


def statistics_url(filters, choices, **changes):
    """The Statistics page URL with the same selection and some choices changed."""
    values = dict(filters)
    values["variable"] = choices["variable"]
    if choices["group"]:
        values["group"] = choices["group"]
        values["gsort"] = choices["gsort"]
    if choices["pct_text"]:
        values["pct"] = choices["pct_text"]
    for key, value in changes.items():
        if value is None or value == "":
            values.pop(key, None)
        else:
            values[key] = value
    return "/statistics?" + urlencode(values)


@app.route("/statistics")
def statistics():
    """
    Descriptive statistics for one variable over the Explore selection, overall and by group.
    Everything is in the URL, e.g.
    /statistics?q=coal+kentucky&variable=co2_intensity&group=year
    """
    choices, filters, result, frame = statistics_request()
    variable = choices["variable"]

    summary = analysis.describe(frame, variable, choices["percentiles"])
    groups = []
    if choices["group"]:
        groups = analysis.describe_groups(frame, variable, choices["group"], choices["gsort"])

    sort_links = {
        key: statistics_url(filters, choices, gsort=key) for key in analysis.GROUP_SORTS
    }
    download_base = statistics_url(filters, choices).replace("/statistics?", "/statistics/download?", 1)

    return render_template(
        "statistics.html",
        choices=choices,
        result=result,
        summary=summary,
        groups=groups[:analysis.GROUP_LIMIT],
        group_count=len(groups),
        group_limit=analysis.GROUP_LIMIT,
        sort_links=sort_links,
        download_base=download_base,
        info=analysis.VARIABLES[variable],
        variable_menu=analysis.variables_by_group(),
        group_options=analysis.GROUPS,
        group_sorts=analysis.GROUP_SORTS,
        percentile_label=analysis.percentile_label,
        methods={
            "percentiles": analysis.PERCENTILE_METHOD,
            "std": analysis.STD_METHOD,
            "missing": analysis.MISSING_RULE,
            "mean_vs_overall": analysis.MEAN_VS_OVERALL,
        },
        **selection_context(filters, result, frame, variable),
    )


@app.route("/statistics/download")
def statistics_download():
    """
    The statistics as CSV or Excel, with reproducibility metadata.
    what=summary (overall statistics), groups (grouped table) or dataset (every record
    with every derived indicator).
    """
    choices, filters, result, frame = statistics_request()
    what = request.args.get("what", "summary")
    file_format = "xlsx" if request.args.get("format") == "xlsx" else "csv"
    variable = choices["variable"]
    labels = selection_labels(filters, result)
    explore_url = "/explore" + ("?" + urlencode(filters) if filters else "")

    if what == "dataset":
        columns, rows = analysis.dataset_table(frame)
        lines = analysis.metadata("Analytical dataset with derived indicators", frame, labels, explore_url)
        name_parts = ["analysis-dataset"]
    elif what == "groups" and choices["group"]:
        groups = analysis.describe_groups(frame, variable, choices["group"], choices["gsort"])
        columns, rows = analysis.groups_table(variable, choices["group"], groups)
        lines = analysis.metadata("Grouped descriptive statistics", frame, labels, explore_url,
                                  key=variable, group=choices["group"])
        name_parts = ["statistics", variable, "by", choices["group"]]
    else:
        stats = analysis.describe(frame, variable, choices["percentiles"])
        columns, rows = analysis.summary_table(variable, stats)
        lines = analysis.metadata("Descriptive statistics", frame, labels, explore_url,
                                  key=variable, percentiles=choices["percentiles"])
        name_parts = ["statistics", variable]

    content, mimetype, extension = analysis.export_file(columns, rows, lines, file_format)
    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{file_name(name_parts, extension)}"'},
    )



def export_response(columns, rows, lines, name_parts, file_format):
    content, mimetype, extension = analysis.export_file(columns, rows, lines, file_format)
    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{file_name(name_parts, extension)}"'},
    )


def requested_format():
    return "xlsx" if request.args.get("format") == "xlsx" else "csv"


# ---------- Phase 2: visualization dashboard (proposal 4.4) ----------

DASHBOARD_DEFAULT_VARIABLE = "co2_mass"


def dashboard_choices(params):
    def pick(name, allowed, default):
        value = params.get(name)
        return value if value in allowed else default

    min_load = search_to_number(params.get("min_load"))
    return {
        "variable": chosen_variable(params, DASHBOARD_DEFAULT_VARIABLE),
        "group": pick("group", analysis.GROUPS, "state"),
        "split": pick("split", dashboard.SPLITS, "none"),
        "x": pick("x", dashboard.SCATTER_VARIABLES, "heat_input"),
        "y": pick("y", dashboard.SCATTER_VARIABLES, "co2_mass"),
        "scale": pick("scale", dashboard.SCALES, "log"),
        "corr": pick("corr", dashboard.CORRELATION_METHODS, "spearman"),
        "level": pick("level", dashboard.RANK_LEVELS, "facility"),
        "min_load": dashboard.DEFAULT_MIN_LOAD if min_load is None or min_load < 0 else min_load,
    }


def search_to_number(value):
    from search import to_number
    return to_number(value) if value not in (None, "") else None


def dashboard_url_choices(choices):
    values = dict(choices)
    values["min_load"] = "{:g}".format(choices["min_load"])
    return values


@app.route("/dashboard")
def dashboard_page():
    """
    Interactive charts for the Explore selection: trends, comparisons across groups, distributions,
    relationships, rankings and maps. Every choice is in the URL.
    """
    params, filters, result, frame = analysis_selection()
    choices = dashboard_choices(params)
    charts = []
    if len(frame):
        charts = [dashboard.json_safe(spec) for spec in dashboard.build_all(frame, choices)]
    data_base = page_url("/dashboard/data", filters, **dashboard_url_choices(choices))
    return render_template(
        "dashboard.html",
        choices=choices,
        charts={spec["id"]: spec for spec in charts},
        data_base=data_base,
        variable_menu=analysis.variables_by_group(),
        scatter_variables=[(key, analysis.variable_title(key)) for key in dashboard.SCATTER_VARIABLES],
        group_options=analysis.GROUPS,
        splits=dashboard.SPLITS,
        scales=dashboard.SCALES,
        correlation_methods=dashboard.CORRELATION_METHODS,
        rank_levels=dashboard.RANK_LEVELS,
        info=analysis.VARIABLES[choices["variable"]],
        **selection_context(filters, result, frame, choices["variable"]),
    )


@app.route("/dashboard/data")
def dashboard_data():
    """The numbers behind one dashboard chart, as CSV or Excel with reproducibility metadata."""
    params, filters, result, frame = analysis_selection()
    choices = dashboard_choices(params)
    spec = dashboard.build_one(frame, choices, request.args.get("chart", ""))
    if spec is None:
        abort(404)
    labels = selection_labels(filters, result)
    explore_url = "/explore" + ("?" + urlencode(filters) if filters else "")
    lines = analysis.metadata("Chart data: " + spec["title"], frame, labels, explore_url, key=choices["variable"])
    settings = ", ".join(f"{key}={value}" for key, value in dashboard_url_choices(choices).items())
    lines.insert(2, ("Chart", spec["title"]))
    lines.insert(3, ("Chart settings", settings))
    if spec.get("note"):
        lines.insert(4, ("Chart note", spec["note"]))
    if spec.get("empty"):
        lines.insert(4, ("Chart note", spec["empty"]))
    return export_response(spec["table"]["columns"], spec["table"]["rows"], lines,
                           ["chart", spec["id"], choices["variable"]], requested_format())


# ---------- Phase 2: comparative analysis (proposal 4.5) ----------

COMPARISON_DEFAULT_VARIABLE = "co2_intensity"


def comparison_url_choices(params, definition, variable, scale):
    values = {"cmp": definition["dimension"], "variable": variable, "scale": scale}
    if definition["dimension"] == "period":
        values.update({"pa_from": definition["a"]["from"], "pa_to": definition["a"]["to"],
                       "pb_from": definition["b"]["from"], "pb_to": definition["b"]["to"]})
        if definition["matched"]:
            values["matched"] = "1"
    elif definition["dimension"] not in ("so2_control", "nox_control"):
        values.update({"a": definition.get("a_value"), "b": definition.get("b_value")})
    return values


def comparison_request():
    params, filters, result, frame = analysis_selection()
    variable = chosen_variable(params, COMPARISON_DEFAULT_VARIABLE)
    scale = "linear" if params.get("scale") == "linear" else "log"
    definition = comparison.choose(frame, params)
    return params, filters, result, frame, variable, scale, definition


@app.route("/comparison")
def comparison_page():
    """
    Compare two groups of the selection (periods, states, fuels, unit types, control vs none,
    facilities or units) on one variable and every normalized indicator.
    """
    params, filters, result, frame, variable, scale, definition = comparison_request()
    outcome = None
    if len(frame) and not definition["same"]:
        outcome = comparison.compare(frame, variable, definition, scale)
        outcome["charts"] = [dashboard.json_safe(spec) for spec in outcome["charts"]]
    url_choices = comparison_url_choices(params, definition, variable, scale)
    return render_template(
        "comparison.html",
        definition=definition,
        outcome=outcome,
        variable=variable,
        scale=scale,
        info=analysis.VARIABLES[variable],
        dimensions=comparison.DIMENSIONS,
        variable_menu=analysis.variables_by_group(),
        caveats=comparison.CAVEATS,
        download_base=page_url("/comparison/download", filters, **url_choices),
        ranking_limit=comparison.RANKING_LIMIT,
        **selection_context(filters, result, frame, variable),
    )


@app.route("/comparison/download")
def comparison_download():
    """Comparison results as CSV or Excel: what=summary, indicators or groups."""
    params, filters, result, frame, variable, scale, definition = comparison_request()
    if not len(frame) or definition["same"]:
        abort(404)
    outcome = comparison.compare(frame, variable, definition, scale)
    what = request.args.get("what", "summary")
    labels = selection_labels(filters, result)
    explore_url = "/explore" + ("?" + urlencode(filters) if filters else "")
    a_label = definition["a_label"]
    b_label = definition["b_label"]

    if what == "indicators":
        columns, rows = comparison.indicators_table(outcome)
        kind = "Comparison of normalized indicators"
    elif what == "groups":
        columns, rows = comparison.ranking_table(variable, definition["dimension"], outcome["ranking"])
        kind = "Every group ranked"
    else:
        columns, rows = comparison.summary_table(variable, outcome)
        kind = "Comparison summary statistics"
    lines = analysis.metadata(kind, frame, labels, explore_url, key=variable)
    lines.insert(2, ("Comparing", f"{definition['name']}: A = {a_label}, B = {b_label}"
                     + (" (only units with records in both periods)" if definition["matched"] else "")))
    lines.insert(3, ("Differences", "B − A; percentage difference = (B − A) ÷ |A| × 100"))
    lines.insert(4, ("Tests", "Welch's t-test (unequal variances) with a 95% confidence interval; Mann–Whitney U "
                              "(two-sided); one-way ANOVA and Kruskal–Wallis across groups (SciPy "
                              + comparison.scipy_version() + ")"))
    lines.insert(5, ("Caveats", " ".join(comparison.CAVEATS)))
    return export_response(columns, rows, lines, ["comparison", definition["dimension"], variable, what],
                           requested_format())


# ---------- Phase 2: environmental and health impact indicators (proposal 4.6) ----------

IMPACT_GROUPS = dict(analysis.GROUPS)
IMPACT_GROUPS["unit"] = "Unit"


def impact_labels(frame, by):
    if by == "unit":
        return analysis.unit_labels(frame)
    return analysis.group_labels(frame, by)


def impacts_request():
    params, filters, result, frame = analysis_selection()
    factors = traci.ensure_factors()
    traci.add_impacts(frame, factors)
    categories = traci.categories(factors)
    keys = [key for key, _, _ in categories]
    by = params.get("by") if params.get("by") in IMPACT_GROUPS else "state"
    isort = params.get("isort") if params.get("isort") in keys else (keys[0] if keys else "")
    per_mwh = params.get("per_mwh") == "1"
    choices = {"by": by, "isort": isort, "per_mwh": per_mwh}
    return params, filters, result, frame, factors, categories, choices


def impact_group_rows(frame, factors, categories, choices):
    """One row per group with every category's total and per-MWh value, sorted by the chosen category."""
    labels = impact_labels(frame, choices["by"])
    by_category = traci.summarize_groups(frame, factors, labels)
    rows = {}
    for key, _, _ in categories:
        for item in by_category[key]:
            row = rows.setdefault(item["group"], {"group": item["group"], "records": item["records"]})
            row[key] = item
    sort_field = "intensity" if choices["per_mwh"] else "total"

    def sort_key(row):
        value = row.get(choices["isort"], {}).get(sort_field)
        return (value is None, -(value or 0), str(row["group"]))
    return sorted(rows.values(), key=sort_key)


def impact_metadata(kind, frame, filters, result, factors):
    labels = selection_labels(filters, result)
    explore_url = "/explore" + ("?" + urlencode(filters) if filters else "")
    lines = analysis.metadata(kind, frame, labels, explore_url)
    version = factors[0]["traci_version"] if factors else "none loaded"
    extra = [
        ("TRACI version", version),
        ("TRACI source file", (f"{factors[0]['source_file']} (SHA-256 {factors[0]['source_sha256']})"
                               if factors else "—")),
        ("Official TRACI file", traci.OFFICIAL_URL),
        ("Unit conversion", f"1 short ton = {traci.SHORT_TON_KG} kg"),
        ("Formula", "Impact in category c = sum over pollutants of (mass in kg × TRACI factor for c). "
                    "Categories are never added together. Impact per MWh = impact ÷ gross load of the same records."),
        ("Missing values", "A record's category result is missing when any pollutant that category needs is "
                           "missing; it is never set to 0."),
    ]
    for factor in factors:
        extra.append((f"Factor: {traci.POLLUTANTS[factor['campd_pollutant']]['label']} → "
                      f"{factor['impact_category_name']}",
                      f"{factor['factor_value']:.10g} {factor['factor_unit']} ({factor['substance_name']}, "
                      f"{factor['match_rule']}, {factor['source_sheet']} row {factor['source_row']})"))
    extra.append(("Interpretation", traci.DISCLAIMER))
    return lines[:2] + extra + lines[2:]


@app.route("/impacts")
def impacts():
    """
    Potential environmental and health impacts of the selection's CO2, SO2 and NOx, using EPA
    TRACI 2.2 factors: totals, per-MWh intensity, pollutant contributions and results by group.
    """
    params, filters, result, frame, factors, categories, choices = impacts_request()
    totals = traci.summarize(frame, factors) if len(frame) and factors else []
    rows = impact_group_rows(frame, factors, categories, choices) if len(frame) and factors else []
    charts = []
    if totals:
        charts = [dashboard.json_safe(dashboard.impact_share_chart(totals)),
                  dashboard.json_safe(dashboard.impact_group_chart(rows, categories, choices,
                                                                   IMPACT_GROUPS[choices["by"]]))]
    url_choices = {"by": choices["by"], "isort": choices["isort"], "per_mwh": "1" if choices["per_mwh"] else ""}
    sort_links = {key: page_url("/impacts", filters, **dict(url_choices, isort=key)) for key, _, _ in categories}
    return render_template(
        "impacts.html",
        choices=choices,
        totals=totals,
        rows=rows[:analysis.GROUP_LIMIT],
        group_count=len(rows),
        group_limit=analysis.GROUP_LIMIT,
        categories=categories,
        factors=factors,
        charts={spec["id"]: spec for spec in charts},
        group_options=IMPACT_GROUPS,
        pollutants=traci.POLLUTANTS,
        disclaimer=traci.DISCLAIMER,
        limitations=traci.LIMITATIONS,
        short_ton_kg=traci.SHORT_TON_KG,
        official_url=traci.OFFICIAL_URL,
        traci_page=traci.TRACI_PAGE,
        sort_links=sort_links,
        per_mwh_link=page_url("/impacts", filters, **dict(url_choices, per_mwh="" if choices["per_mwh"] else "1")),
        download_base=page_url("/impacts/download", filters, **url_choices),
        **selection_context(filters, result, frame),
    )


@app.route("/impacts/download")
def impacts_download():
    """Impact results as CSV or Excel: what=totals, groups, records or factors."""
    params, filters, result, frame, factors, categories, choices = impacts_request()
    what = request.args.get("what", "totals")

    if what == "factors":
        columns, rows = traci.factors_table(factors)
        kind = "TRACI characterization factors used"
    elif what == "groups":
        columns = [IMPACT_GROUPS[choices["by"]], "Records"]
        for key, name, unit in categories:
            columns += [f"{name} ({unit})", f"{name} per MWh ({unit}/MWh)", f"{name}: records used"]
        rows = []
        for row in impact_group_rows(frame, factors, categories, choices):
            line = [row["group"], row["records"]]
            for key, _, _ in categories:
                item = row.get(key, {})
                line += [item.get("total"), item.get("intensity"), item.get("used")]
            rows.append(line)
        kind = f"Potential impacts by {IMPACT_GROUPS[choices['by']].lower()}"
    elif what == "records":
        columns = ["Facility", "Facility ID", "State", "Unit", "Year", "Primary Fuel", "CO2 (short tons)",
                   "SO2 (short tons)", "NOx (short tons)", "Gross Load (MWh)"]
        names = ["facility_name", "facility_id", "state", "unit_id", "year", "primary_fuel", "co2_mass", "so2_mass",
                 "nox_mass", "gross_load"]
        for key, name, unit in categories:
            columns.append(f"{name} ({unit})")
            names.append(f"impact_{key}")
        table = frame[names].astype("object").where(frame[names].notna(), None)
        rows = table.values.tolist()
        for row in rows:
            for index in (1, 4):
                if row[index] is not None:
                    row[index] = int(row[index])
        kind = "Potential impacts for every record"
    else:
        columns = ["Impact category", "Unit", "Total", "Records used", "Records missing a pollutant",
                   "Gross load of records used (MWh)", "Impact per MWh"]
        for pollutant in traci.POLLUTANT_ORDER:
            label = traci.POLLUTANTS[pollutant]["label"]
            columns += [f"From {label}", f"Share from {label} (%)"]
        rows = []
        for item in traci.summarize(frame, factors):
            line = [item["name"], item["unit"], item["total"], item["used"], item["missing"], item["load_total"],
                    item["intensity"]]
            shares = {c["pollutant"]: c for c in item["contributions"]}
            for pollutant in traci.POLLUTANT_ORDER:
                part = shares.get(pollutant)
                line += [part["amount"] if part else None, part["share"] if part else None]
            rows.append(line)
        kind = "Potential impact totals"

    lines = impact_metadata(kind, frame, filters, result, factors)
    return export_response(columns, rows, lines, ["impacts", what], requested_format())

if __name__ == "__main__":
    app.run(debug=True)