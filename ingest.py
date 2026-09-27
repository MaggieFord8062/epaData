"""
ingest.py
Pulls EPA CAMPD data into epaData.db from the command line.

For each reporting year it:
  1. pulls annual emissions for every state, validates every record and stores the new ones
  2. pulls facility attributes (county, location, source category, operating/retirement dates)
Each pull is recorded on the Datasets page with its query, counts and any rejected rows.

Run from the project folder:
    python ingest.py                     every year from 2015 to 2025
    python ingest.py 2024                just 2024
    python ingest.py 2020 2024           2020 through 2024
    python ingest.py --attributes-only   refresh county, location, source category and dates only

Safe to run more than once: records already in the database are skipped.
"""
import os
import sys

from dotenv import load_dotenv
from client import CAMPDClient, CAMPDError
from database import SessionLocal
from retrieval import DatabaseIndex, retrieve_emissions, retrieve_attributes

DEFAULT_FIRST_YEAR = 2015
DEFAULT_LAST_YEAR = 2025


def years_from_arguments(arguments):
    if not arguments:
        return list(range(DEFAULT_FIRST_YEAR, DEFAULT_LAST_YEAR + 1))
    try:
        numbers = [int(argument) for argument in arguments]
    except ValueError:
        print("Years must be numbers, like: python ingest.py 2020 2024")
        raise SystemExit(1)
    if len(numbers) == 1:
        return numbers
    return list(range(min(numbers), max(numbers) + 1))


def print_dataset(dataset):
    print(f"  Dataset #{dataset.dataset_id}: received {dataset.num_raw_records}, accepted {dataset.num_accepted_records}")
    for note in (dataset.notes or "").split("; "):
        print(f"    {note}")


def main():
    load_dotenv()
    api_key = os.getenv("CAMPD_API_KEY")
    if not api_key:
        print("No CAMPD_API_KEY found in .env")
        raise SystemExit(1)

    arguments = sys.argv[1:]
    attributes_only = "--attributes-only" in arguments
    arguments = [argument for argument in arguments if argument != "--attributes-only"]
    years = years_from_arguments(arguments)

    client = CAMPDClient(api_key)
    # expire_on_commit=False keeps loaded rows in memory after each year is saved,
    # instead of re-reading thousands of them one at a time
    session = SessionLocal(expire_on_commit=False)

    print("Loading what's already in the database...")
    index = DatabaseIndex(session)

    # Oldest year first, so newer years overwrite older facility and unit details
    for year in sorted(years):
        try:
            if not attributes_only:
                print(f"\n{year}: annual emissions (all states)")
                print_dataset(retrieve_emissions(session, client, index, year))
            print(f"{year}: facility attributes")
            print_dataset(retrieve_attributes(session, client, index, year))
        except CAMPDError as error:
            session.rollback()
            print(f"  Skipped {year}: {error}")

    session.close()

    print("\nDone.")
    print(f"Data saved in: {os.path.abspath('epaData.db')}")


if __name__ == "__main__":
    main()