from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Dataset(Base):
    """
    Provenance: one row for every time data comes into the database,
    whether it's pulled from the CAMPD API or uploaded as a file.
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
    query_parameters = Column(String)  # e.g. {"year": 2024, "stateCode": "KY"}, stored as JSON text

    annual_records = relationship("AnnualRecord", back_populates="dataset")


class Facility(Base):
    __tablename__ = "facility"
    epa_facility_id = Column(Integer, primary_key=True)
    facility_name = Column(String, index=True)
    state = Column(String, index=True)
    county = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    source_category = Column(String, index=True)

    units = relationship("Unit", back_populates="facility")


class Unit(Base):
    __tablename__ = "unit"
    internal_unit_key = Column(Integer, primary_key=True)
    epa_facility_id = Column(Integer, ForeignKey("facility.epa_facility_id"), index=True)
    epa_unit_id = Column(String, index=True)  # string, since values look like "SCT1"
    unit_type = Column(String, index=True)
    primary_fuel = Column(String, index=True)
    secondary_fuel = Column(String, index=True)
    operating_date = Column(String)
    retirement_date = Column(String)

    facility = relationship("Facility", back_populates="units")
    annual_records = relationship("AnnualRecord", back_populates="unit")


class AnnualRecord(Base):
    __tablename__ = "annual_records"
    annual_record_id = Column(Integer, primary_key=True)

    epa_facility_id = Column(Integer, ForeignKey("facility.epa_facility_id"), nullable=False, index=True)
    internal_unit_key = Column(Integer, ForeignKey("unit.internal_unit_key"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)

    # Provenance: which API pull or upload this record came from
    dataset_id = Column(Integer, ForeignKey("dataset.dataset_id"), index=True)

    # Indexed because they're used for range searches and rankings
    operating_time = Column(Float, index=True)
    gross_load = Column(Float, index=True)
    steam_load = Column(Float)
    heat_input = Column(Float, index=True)
    co2_mass = Column(Float, index=True)
    so2_mass = Column(Float, index=True)
    nox_mass = Column(Float, index=True)
    so2_control_info = Column(String)
    nox_control_info = Column(String)
    pm_control_info = Column(String)
    program_code = Column(String)

    unit = relationship("Unit", back_populates="annual_records")
    dataset = relationship("Dataset", back_populates="annual_records")

    __table_args__ = (
        UniqueConstraint("epa_facility_id", "internal_unit_key", "year", name="uq_facility_unit_year"),
    )