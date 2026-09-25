from flask import Flask, render_template, request, jsonify
from sqlalchemy import func
from database import SessionLocal
from models import Facility, Unit, AnnualRecord, Dataset
from search import (search_data, advance_search, get_filter_options,
                    find_facilities, RANK_FIELDS)

app = Flask(__name__)
app.json.sort_keys = False  # keep result columns in the order search.py lists them


def drop_empty_columns(results):
    """Remove columns that are empty in every row (like County, until it's filled in)."""
    if not results:
        return results
    keep = [key for key in results[0] if any(row[key] not in (None, "") for row in results)]
    return [{key: row[key] for key in keep} for row in results]


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

    top_emitters = (
        session.query(
            Facility.facility_name,
            Facility.state,
            func.sum(AnnualRecord.co2_mass).label("co2"),
        )
        .join(AnnualRecord, Facility.epa_facility_id == AnnualRecord.epa_facility_id)
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
            Facility.facility_name,
            Facility.state,
            AnnualRecord.year,
            AnnualRecord.co2_mass,
            AnnualRecord.so2_mass,
            AnnualRecord.nox_mass,
        )
        .join(AnnualRecord, Facility.epa_facility_id == AnnualRecord.epa_facility_id)
        .order_by(Facility.facility_name)
        .limit(100)
        .all()
    )

    session.close()

    return render_template("explorer.html", results=results)


@app.route("/search")
def search():
    return render_template("search.html")


@app.route("/basic-search", methods=["GET", "POST"])
def basic_search():
    if request.method == "POST":
        search_parameters = request.form.to_dict()
        results = drop_empty_columns(search_data(**search_parameters))
        return render_template("results.html", results=results)

    # Filters can come in the URL, e.g. /basic-search?state=KY (from the top-right search)
    selected = request.args.to_dict()
    data = get_filter_options(**selected)

    return render_template(
        "basic_search.html",
        selected=selected,
        options=data["options"],
        ranges=data["ranges"],
        count=data["count"],
    )


@app.route("/api/filter-options")
def api_filter_options():
    """Called by the search page every time a filter changes."""
    return jsonify(get_filter_options(**request.args.to_dict()))


@app.route("/api/facilities")
def api_facilities():
    """Called by the top-right search as you type a facility name."""
    return jsonify(find_facilities(request.args.get("q", "")))


@app.route("/advanced-search", methods=["GET", "POST"])
def advanced_search():
    if request.method == "POST":
        search_parameters = request.form.to_dict()
        results = drop_empty_columns(advance_search(**search_parameters))
        return render_template(
            "results.html",
            results=results,
            ranking=search_parameters,
            rank_label=RANK_FIELDS.get(search_parameters.get("field")),
        )

    session = SessionLocal()
    options = {
        "states": distinct_values(session, Facility.state),
        "years": sorted(distinct_values(session, AnnualRecord.year), reverse=True),
        "unit_types": distinct_values(session, Unit.unit_type),
        "primary_fuels": distinct_values(session, Unit.primary_fuel),
    }
    session.close()

    return render_template("advanced_search.html", rank_fields=RANK_FIELDS, **options)


if __name__ == "__main__":
    app.run(debug=True)