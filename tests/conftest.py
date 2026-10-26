"""
Shared test setup.

Every test runs against a small fixture database (8 annual records, 3 facilities,
4 units, 2023-2025) built in a temporary folder, never against your real epaData.db.
The values are chosen so the expected statistics can be worked out by hand; see
tests/test_analysis.py for the arithmetic.

Run the tests from the project folder with:  python -m pytest
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from models import Base, Dataset, Facility, Unit, AnnualRecord  # noqa: E402

FACILITIES = [
    # id, name, state
    (1001, "Alpha Station", "KY"),
    (1002, "Beta Plant", "KY"),
    (2001, "Gamma Energy", "OH"),
]

UNITS = [
    # unit key, facility, unit id, primary fuel, unit type
    (1, 1001, "1", "Coal", "Tangentially-fired"),
    (2, 1001, "2", "Pipeline Natural Gas", "Combined cycle"),
    (3, 1002, "A", "Coal", "Dry bottom wall-fired boiler"),
    (4, 2001, "CT1", "Pipeline Natural Gas", None),  # unit type not reported
]

RECORDS = [
    # unit, year, operating time, gross load, heat input, CO2, SO2, NOx, SO2 control, NOx control
    (1, 2023, 8000, 1_000_000, 10_000_000, 1_000_000, 1000, 2000, "Wet Limestone", None),
    (1, 2024, 7000, 800_000, 8_400_000, 900_000, 800, 1600, "Wet Limestone", None),
    (1, 2025, 0, 0, 0, 0, 0, 0, "Wet Limestone", None),          # did not operate: ratios undefined
    (2, 2024, 6000, 500_000, 3_500_000, 200_000, 1, 50, None, None),
    (2, 2025, 6500, 600_000, 4_200_000, 240_000, 1.2, 60, None, None),
    (3, 2025, 5000, 400_000, 4_400_000, 440_000, 400, 600, None, "Selective Catalytic Reduction"),
    (4, 2023, 1000, 100_000, 1_100_000, 60_000, None, 10, None, None),  # SO2 missing
    (4, 2025, 500, 50_000, 600_000, 30_000, 0.5, 5, None, None),        # no 2024 record
]


def build_fixture_database(path):
    engine = create_engine("sqlite:///" + str(path))
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Dataset(dataset_id=1, dataset_name="Test fixture", data_source="pytest",
                        retrieval_date="2026-10-26", num_raw_records=len(RECORDS),
                        num_accepted_records=len(RECORDS)))
    for facility_id, name, state in FACILITIES:
        session.add(Facility(epa_facility_id=facility_id, facility_name=name, state=state))
    for key, facility_id, unit_id, fuel, unit_type in UNITS:
        session.add(Unit(internal_unit_key=key, epa_facility_id=facility_id, epa_unit_id=unit_id,
                         primary_fuel=fuel, unit_type=unit_type))
    facility_of = {key: facility_id for key, facility_id, _, _, _ in UNITS}
    for unit, year, hours, load, heat, co2, so2, nox, so2_control, nox_control in RECORDS:
        session.add(AnnualRecord(
            epa_facility_id=facility_of[unit], internal_unit_key=unit, year=year, dataset_id=1,
            operating_time=hours, gross_load=load, heat_input=heat,
            co2_mass=co2, so2_mass=so2, nox_mass=nox,
            so2_control_info=so2_control, nox_control_info=nox_control,
        ))
    session.commit()
    session.close()
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def fixture_database(tmp_path_factory):
    """Build the fixture database and work from its folder, so epaData.db means the fixture."""
    folder = tmp_path_factory.mktemp("epadata")
    build_fixture_database(folder / "epaData.db")
    previous = os.getcwd()
    os.chdir(folder)
    yield folder
    os.chdir(previous)


@pytest.fixture(scope="session")
def client(fixture_database):
    """A Flask test client for the app, using the fixture database."""
    app_module = importlib.import_module("app")
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()
