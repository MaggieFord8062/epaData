import csv
import io
import json
import os
import re
import uuid
from datetime import date, datetime
from urllib.parse import urlencode

from flask import Flask, render_template, request, jsonify, Response, abort, redirect, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from sqlalchemy import func
from database import SessionLocal
from models import Facility, Unit, AnnualRecord, Dataset, UploadedFile
import retrieval_jobs
import smart_search
import uploads
from search import (search_data, advance_search, find_facilities, compare_facilities,
                    facility_units, RANK_FIELDS, COMPARE_LIMIT)

app = Flask(__name__)
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
    """One facility: where it is, its units, and its emissions totaled by year."""
    session = SessionLocal()

    facility = session.get(Facility, facility_id)
    if facility is None:
        session.close()
        abort(404)

    # Each unit with the years it reported
    units = (
        session.query(
            Unit,
            func.min(AnnualRecord.year).label("first_year"),
            func.max(AnnualRecord.year).label("last_year"),
            func.count(AnnualRecord.annual_record_id).label("records"),
        )
        .outerjoin(AnnualRecord, AnnualRecord.internal_unit_key == Unit.internal_unit_key)
        .filter(Unit.epa_facility_id == facility_id)
        .group_by(Unit.internal_unit_key)
        .order_by(Unit.epa_unit_id)
        .all()
    )

    # Facility totals for each reporting year
    yearly = (
        session.query(
            AnnualRecord.year,
            func.count(AnnualRecord.annual_record_id).label("units"),
            func.sum(AnnualRecord.operating_time).label("operating_time"),
            func.sum(AnnualRecord.gross_load).label("gross_load"),
            func.sum(AnnualRecord.heat_input).label("heat_input"),
            func.sum(AnnualRecord.co2_mass).label("co2"),
            func.sum(AnnualRecord.so2_mass).label("so2"),
            func.sum(AnnualRecord.nox_mass).label("nox"),
        )
        .filter(AnnualRecord.epa_facility_id == facility_id)
        .group_by(AnnualRecord.year)
        .order_by(AnnualRecord.year.desc())
        .all()
    )

    # Where this facility's data came from
    sources = (
        session.query(Dataset)
        .join(AnnualRecord, AnnualRecord.dataset_id == Dataset.dataset_id)
        .filter(AnnualRecord.epa_facility_id == facility_id)
        .distinct()
        .order_by(Dataset.reporting_year.desc(), Dataset.dataset_id.desc())
        .all()
    )

    session.close()

    max_co2 = max([row.co2 or 0 for row in yearly] or [0])

    return render_template(
        "facility.html",
        facility=facility,
        units=units,
        yearly=yearly,
        sources=sources,
        max_co2=max_co2,
    )


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

        year = form.get("year", type=int)
        if year is not None and year not in choices["years"]:
            errors.append("Choose a valid reporting year.")

        # Form field -> (CAM API parameter, allowed values, readable label)
        filter_fields = {
            "year": ("year", choices["years"], "Year"),
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


if __name__ == "__main__":
    app.run(debug=True)