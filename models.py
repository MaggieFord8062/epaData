from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------
# Dataset
# ---------------------------------------------------------

class Dataset(Base):
    """
    Stores information about where data came from.
    A dataset can contain many annual records.
    """
    __tablename__ = "dataset"

    dataset_id = Column(Integer, primary_key=True)
    dataset_name = Column(String)
    data_source = Column(String)
    reporting_year = Column(String)
    retrieval_date = Column(String)
    og_filename = Column(String)
    num_raw_records = Column(Integer)
    num_accepted_records = Column(Integer)
    notes = Column(String)
    query_parameters = Column(String)

    # Relationship to AnnualRecord
    annual_records = relationship(
        "AnnualRecord",
        back_populates="dataset"
    )


# ---------------------------------------------------------
# Facility
# ---------------------------------------------------------

class Facility(Base):
    """
    Represents an EPA power-sector facility.
    A facility can contain many units.
    """
    __tablename__ = "facility"

    epa_facility_id = Column(Integer, primary_key=True)

    facility_name = Column(String, index=True)
    state = Column(String, index=True)
    county = Column(String, index=True)

    latitude = Column(Float)
    longitude = Column(Float)

    source_category = Column(String, index=True)
    owner = Column(String)

    # Relationship to Unit
    units = relationship(
        "Unit",
        back_populates="facility"
    )


# ---------------------------------------------------------
# Unit
# ---------------------------------------------------------

class Unit(Base):
    """
    Represents an individual generating unit within a facility.
    A unit can have many annual records, hourly records, and QA tests.
    """
    __tablename__ = "unit"

    internal_unit_key = Column(Integer, primary_key=True)

    epa_facility_id = Column(
        Integer,
        ForeignKey("facility.epa_facility_id"),
        index=True
    )

    epa_unit_id = Column(String, index=True)

    unit_type = Column(String, index=True)

    primary_fuel = Column(String, index=True)
    primary_fuel_start_date = Column(String)
    primary_fuel_end_date = Column(String)

    secondary_fuel = Column(String, index=True)
    secondary_fuel_start_date = Column(String)
    secondary_fuel_end_date = Column(String)

    operating_date = Column(String)
    retirement_date = Column(String)

    # Relationship to Facility
    facility = relationship(
        "Facility",
        back_populates="units"
    )

    # Relationship to AnnualRecord
    annual_records = relationship(
        "AnnualRecord",
        back_populates="unit"
    )

    # Relationship to HourlyRecord
    hourly_records = relationship(
        "HourlyRecord",
        back_populates="unit"
    )

    # Relationship to QATest
    qa_tests = relationship(
        "QATest",
        back_populates="unit"
    )


# ---------------------------------------------------------
# Annual Record
# ---------------------------------------------------------

class AnnualRecord(Base):
    """
    Stores yearly emissions and operating information
    for a facility/unit combination.
    """
    __tablename__ = "annual_records"

    annual_records_id = Column(Integer, primary_key=True)

    epa_facility_id = Column(
        Integer,
        ForeignKey("facility.epa_facility_id"),
        nullable=False,
        index=True
    )

    internal_unit_key = Column(
        Integer,
        ForeignKey("unit.internal_unit_key"),
        nullable=False,
        index=True
    )

    year = Column(
        Integer,
        nullable=False,
        index=True
    )

    # Provenance
    dataset_id = Column(
        Integer,
        ForeignKey("dataset.dataset_id"),
        index=True
    )

    # Operating / emissions data
    operating_time = Column(Float, index=True)
    gross_load = Column(Float, index=True)
    steam_load = Column(Float)
    heat_input = Column(Float, index=True)

    co2_mass = Column(Float, index=True)
    so2_mass = Column(Float, index=True)
    nox_mass = Column(Float, index=True)

    # SO2 controls
    so2_control_info = Column(String)
    so2_control_start_date = Column(String)
    so2_control_end_date = Column(String)

    # NOx controls
    nox_control_info = Column(String)
    nox_control_start_date = Column(String)
    nox_control_end_date = Column(String)

    # CO2 controls
    co2_control_start_date = Column(String)
    co2_control_end_date = Column(String)

    # PM controls
    pm_control_info = Column(String)
    pm_control_start_date = Column(String)
    pm_control_end_date = Column(String)

    # Monitoring
    monitoring_method = Column(String)
    monitoring_method_start_date = Column(String)
    monitoring_method_end_date = Column(String)

    program_code = Column(String)

    # Relationship to Unit
    unit = relationship(
        "Unit",
        back_populates="annual_records"
    )

    # Relationship to Dataset
    dataset = relationship(
        "Dataset",
        back_populates="annual_records"
    )

    # One annual record per facility + unit + year
    __table_args__ = (
        UniqueConstraint(
            "epa_facility_id",
            "internal_unit_key",
            "year",
            name="uq_facility_unit_year"
        ),
    )


# ---------------------------------------------------------
# Hourly Record
# ---------------------------------------------------------

class HourlyRecord(Base):
    """
    Stores hourly operating and emissions information
    for a generating unit.
    """
    __tablename__ = "hourly_record"

    hourly_records_id = Column(Integer, primary_key=True)

    internal_unit_key = Column(
        Integer,
        ForeignKey("unit.internal_unit_key"),
        nullable=False,
        index=True
    )

    timestamp = Column(String, index=True)

    operating_time = Column(Float)
    gross_load = Column(Float)
    steam_load = Column(Float)
    heat_input = Column(Float)

    co2_mass = Column(Float)
    so2_mass = Column(Float)
    nox_mass = Column(Float)
    hg_mass = Column(Float)

    # Relationship to Unit
    unit = relationship(
        "Unit",
        back_populates="hourly_records"
    )


# ---------------------------------------------------------
# QA Tests
# ---------------------------------------------------------

class QATest(Base):
    """
    Stores quality-assurance test information for a unit.
    """
    __tablename__ = "qa_tests"

    qa_test_id = Column(Integer, primary_key=True)

    internal_unit_key = Column(
        Integer,
        ForeignKey("unit.internal_unit_key"),
        nullable=False,
        index=True
    )

    test_date = Column(String)
    test_type = Column(String)
    test_result = Column(String)

    # Relationship to Unit
    unit = relationship(
        "Unit",
        back_populates="qa_tests"
    )