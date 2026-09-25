from flask import Flask, render_template, request
from database import SessionLocal
from models import Facility, Unit, AnnualRecord, Dataset
from search import search_data, advance_search

app = Flask(__name__)


@app.route("/")
def home():
    session = SessionLocal()

    facility_count = session.query(Facility).count()
    unit_count = session.query(Unit).count()
    record_count = session.query(AnnualRecord).count()
    dataset_count = session.query(Dataset).count()

    states = session.query(Facility.state).distinct().count()

    session.close()

    return render_template(
        "home.html",
        facility_count=facility_count,
        unit_count=unit_count,
        record_count=record_count,
        dataset_count=dataset_count,
        states=states,
    )


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
        results = search_data(**search_parameters)
        return render_template("results.html", results=results)

    session = SessionLocal()

    def distinct_values(column):
        """Every non-empty value stored in a column, sorted."""
        return sorted({v[0] for v in session.query(column).distinct().all() if v[0] not in (None, "")})

    options = {
        "facility_names": distinct_values(Facility.facility_name),
        "states": distinct_values(Facility.state),
        "counties": distinct_values(Facility.county),
        "source_categories": distinct_values(Facility.source_category),
        "years": sorted(distinct_values(AnnualRecord.year), reverse=True),
        "unit_types": distinct_values(Unit.unit_type),
        "primary_fuels": distinct_values(Unit.primary_fuel),
        "secondary_fuels": distinct_values(Unit.secondary_fuel),
    }

    session.close()

    return render_template("basic_search.html", **options)


@app.route("/advanced-search", methods=["GET", "POST"])
def advanced_search():
    if request.method == "POST":
        search_parameters = request.form.to_dict()
        results = advance_search(**search_parameters)
        return render_template("results.html", results=results)
    return render_template("advanced_search.html")


if __name__ == "__main__":
    app.run(debug=True)