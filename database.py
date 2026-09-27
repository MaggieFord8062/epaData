from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models import Base

engine = create_engine("sqlite:///epaData.db")

# Creates any tables that don't exist yet (it never changes tables that already exist)
Base.metadata.create_all(engine)


def add_missing_columns():
    """
    create_all() won't add a new column to a table that already exists,
    so add dataset_id to annual_records here if an older database doesn't have it.
    """
    columns = [column["name"] for column in inspect(engine).get_columns("annual_records")]
    if "dataset_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE annual_records ADD COLUMN dataset_id INTEGER REFERENCES dataset(dataset_id)"
            ))
        print("Database updated: added dataset_id to annual_records")


add_missing_columns()

SessionLocal = sessionmaker(bind=engine)