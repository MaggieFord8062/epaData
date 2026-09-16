from flask import Flask, render_template
from database import SessionLocal
from models import Facility, Unit, AnnualRecord, Dataset

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


if __name__ == "__main__":
    app.run(debug=True)