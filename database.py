from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models import Base

engine = create_engine("sqlite:///epaData.db")

# Creates any tables that don't exist yet (it never changes tables that already exist)
Base.metadata.create_all(engine)


def add_missing_columns():
    """
    create_all() won't add new columns to tables that already exist.
    Compare every model with the real database and add any column that's missing,
    so an older epaData.db keeps its data and still gets the new columns.
    """
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            column_type = column.type.compile(dialect=engine.dialect)
            with engine.begin() as connection:
                connection.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {column_type}'))
            print(f"Database updated: added {table.name}.{column.name}")


def add_missing_indexes():
    """Create the indexes defined in models.py (on commonly searched fields) if they don't exist yet."""
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(engine, checkfirst=True)


add_missing_columns()
add_missing_indexes()

SessionLocal = sessionmaker(bind=engine)