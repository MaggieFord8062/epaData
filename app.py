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

@app.route("/index")
def index():
    return render_template("index.html")

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

    states = sorted({s[0] for s in session.query(Facility.state).distinct().all() if s[0]})
    counties = sorted({c[0] for c in session.query(Facility.county).distinct().all() if c[0]})
    facility_names = sorted({f[0] for f in session.query(Facility.facility_name).distinct().all() if f[0]})
    source_categories = sorted({c[0] for c in session.query(Facility.source_category).distinct().all() if c[0]})
    unit_types = sorted({u[0] for u in session.query(Unit.unit_type).distinct().all() if u[0]})
    primary_fuels = sorted({p[0] for p in session.query(Unit.primary_fuel).distinct().all() if p[0]})
    secondary_fuels = sorted({s[0] for s in session.query(Unit.secondary_fuel).distinct().all() if s[0]})

    session.close()

    return render_template(
        "basic_search.html",
        states=states,
        counties=counties,
        facility_names=facility_names,
        source_categories=source_categories,
        unit_types=unit_types,
        primary_fuels=primary_fuels,
        secondary_fuels=secondary_fuels,
    )


@app.route("/advanced-search", methods=["GET", "POST"])
def advanced_search():
    if request.method == "POST":
        search_parameters = request.form.to_dict()
        results = advance_search(**search_parameters)
        return render_template("results.html", results=results)
    return render_template("advanced_search.html")


if __name__ == "__main__":
    app.run(debug=True)