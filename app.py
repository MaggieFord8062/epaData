import csv
import io
import json
from datetime import date
from urllib.parse import urlencode

from flask import Flask, render_template, request, jsonify, Response, abort
from sqlalchemy import func
from database import SessionLocal
from models import Facility, Unit, AnnualRecord, Dataset
from search import (search_data, advance_search, get_filter_options,
                    find_facilities, RANK_FIELDS, PER_PAGE_CHOICES)

app = Flask(__name__)
app.json.sort_keys = False  # keep result columns in the order search.py lists them


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


def csv_response(results, name_parts):
    """Turn a list of result dicts into a CSV file download."""
    output = io.StringIO()
    if results:
        # Columns starting with "_" are only used for links on the site
        results = [{key: value for key, value in row.items() if not key.startswith("_")} for row in results]
        writer = csv.DictWriter(output, fieldnames=list(results[0].keys()))
        writer.writeheader()
        for row in results:
            # CAMPD lists multiple controls as "A<br>B" or "A|B"; make that readable in a spreadsheet
            writer.writerow({key: str(value).replace("<br>", "; ").replace("|", "; ") if isinstance(value, str) else value
                             for key, value in row.items()})

    # e.g. epaData_KY_Coal_2026-09-25.csv
    safe_parts = ["".join(ch for ch in str(part) if ch.isalnum() or ch in "-_") for part in name_parts if part]
    filename = "_".join(["epaData"] + safe_parts + [date.today().isoformat()]) + ".csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    session = SessionLocal()

    results = (
        session.query(
            Facility.epa_facility_id,
            Facility.facility_name,
            Facility.state,
            Unit.epa_unit_id,
            AnnualRecord.internal_unit_key,
            AnnualRecord.year,
            AnnualRecord.co2_mass,
            AnnualRecord.so2_mass,
            AnnualRecord.nox_mass,
        )
        .join(AnnualRecord, Facility.epa_facility_id == AnnualRecord.epa_facility_id)
        .join(Unit, Unit.internal_unit_key == AnnualRecord.internal_unit_key)
        .order_by(Facility.facility_name, Unit.epa_unit_id, AnnualRecord.year.desc())
        .limit(100)
        .all()
    )

    session.close()

    return render_template("explorer.html", results=results)


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


@app.route("/basic-search", methods=["GET", "POST"])
def basic_search():
    if request.method == "POST":
        search_parameters = request.form.to_dict()
        results = drop_empty_columns(search_data(**search_parameters))
        return render_template(
            "results.html",
            results=results,
            download_url="/download?" + urlencode({k: v for k, v in search_parameters.items() if v}),
        )

    # Filters, sorting and page can all come in the URL, e.g. /basic-search?state=KY&sort=co2_mass&dir=desc
    selected = request.args.to_dict()
    data = get_filter_options(**selected)

    return render_template(
        "basic_search.html",
        selected=selected,
        options=data["options"],
        ranges=data["ranges"],
        count=data["count"],
        per_page=data["per_page"],
        per_page_choices=PER_PAGE_CHOICES,
    )


@app.route("/api/filter-options")
def api_filter_options():
    """Called by the search page every time a filter changes."""
    return jsonify(get_filter_options(**request.args.to_dict()))


@app.route("/api/facilities")
def api_facilities():
    """Called by the top-right search as you type a facility name."""
    return jsonify(find_facilities(request.args.get("q", "")))


@app.route("/download")
def download():
    """CSV of every record matching the search filters in the URL (all columns, no row limit)."""
    filters = request.args.to_dict()
    filters.pop("page", None)       # a download always includes every matching row,
    filters.pop("per_page", None)   # not just the page on screen
    results = search_data(**filters)
    name_parts = [filters.get(key) for key in ("facility_name", "epa_facility_id", "epa_unit_id",
                                               "state", "reporting_year", "primary_fuel")]
    return csv_response(results, name_parts)


@app.route("/download-ranking")
def download_ranking():
    """CSV of a ranking, using the same options as the Rankings form."""
    options = request.args.to_dict()
    if options.get("reporting_year") == "all":
        options.pop("reporting_year")
    results = advance_search(**options)
    name_parts = ["ranking", options.get("type"), options.get("field"), options.get("state"),
                  options.get("reporting_year")]
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


if __name__ == "__main__":
    app.run(debug=True)