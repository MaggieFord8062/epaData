from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Dataset(Base):
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


class Facility(Base):
    __tablename__ = "facility"
    epa_facility_id = Column(Integer, primary_key=True)
    facility_name = Column(String)
    state = Column(String)
    county = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    source_category = Column(String)

    units = relationship("Unit", back_populates="facility")


class Unit(Base):
    __tablename__ = "unit"
    internal_unit_key = Column(Integer, primary_key=True)
    epa_facility_id = Column(Integer, ForeignKey("facility.epa_facility_id"))
    epa_unit_id = Column(String)  # fixed: was INTEGER, but values like "SCT1" are strings
    unit_type = Column(String)
    primary_fuel = Column(String)
    secondary_fuel = Column(String)
    operating_date = Column(String)
    retirement_date = Column(String)

    facility = relationship("Facility", back_populates="units")
    annual_records = relationship("AnnualRecord", back_populates="unit")


class AnnualRecord(Base):
    __tablename__ = "annual_records"
    annual_record_id = Column(Integer, primary_key=True)

    epa_facility_id = Column(Integer, ForeignKey("facility.epa_facility_id"), nullable=False)
    internal_unit_key = Column(Integer, ForeignKey("unit.internal_unit_key"), nullable=False)
    year = Column(Integer, nullable=False)  # was missing entirely

    operating_time = Column(Float)
    gross_load = Column(Float)
    steam_load = Column(Float)
    heat_input = Column(Float)
    co2_mass = Column(Float)
    so2_mass = Column(Float)
    nox_mass = Column(Float)
    so2_control_info = Column(String)
    nox_control_info = Column(String)
    pm_control_info = Column(String)
    program_code = Column(String)

    unit = relationship("Unit", back_populates="annual_records")

    __table_args__ = (
        UniqueConstraint("epa_facility_id", "internal_unit_key", "year", name="uq_facility_unit_year"),
    )