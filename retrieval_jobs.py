"""
retrieval_jobs.py
Runs CAM API retrievals started from the website in the background,
so the page can show live status while the data downloads.

Only one retrieval runs at a time, since they all write to the same SQLite database.
Job status is kept in memory: it's for watching a retrieval, while the permanent
record of every retrieval is its Dataset row (see the Datasets page).
"""
import os
import threading
import uuid
from datetime import datetime

from dotenv import load_dotenv

from client import CAMPDClient, CAMPDError
from database import SessionLocal
from retrieval import DatabaseIndex, retrieve_emissions, retrieve_attributes

load_dotenv()

_jobs = {}
_lock = threading.Lock()
_running_job_id = None


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _summarize(dataset):
    """The parts of a Dataset row the status page shows."""
    return {
        "dataset_id": dataset.dataset_id,
        "name": dataset.dataset_name,
        "received": dataset.num_raw_records,
        "accepted": dataset.num_accepted_records,
        "notes": (dataset.notes or "").split("; "),
    }


def get_job(job_id):
    return _jobs.get(job_id)


def running_job():
    return _jobs.get(_running_job_id) if _running_job_id else None


def start_retrieval(year, filters, include_attributes, labels):
    """
    Start a retrieval in the background and return its job id.
    If one is already running, return that one's id instead of starting another.

    filters: CAM API parameters, e.g. {"stateCode": "KY", "unitFuelType": "Coal"}
    labels:  the same filters in readable form, for the status page
    """
    global _running_job_id

    with _lock:
        if _running_job_id and _jobs[_running_job_id]["status"] == "running":
            return _running_job_id, False

        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "year": year,
            "filters": labels,
            "include_attributes": include_attributes,
            "started": _now(),
            "finished": None,
            "steps": [],
            "datasets": [],
            "error": None,
        }
        _running_job_id = job_id

    thread = threading.Thread(target=_run, args=(job_id, year, filters, include_attributes), daemon=True)
    thread.start()
    return job_id, True


def _run(job_id, year, filters, include_attributes):
    global _running_job_id
    job = _jobs[job_id]

    def progress(message):
        # Replace the last line while pages are still arriving, so the list doesn't fill with counts
        if job["steps"] and message.startswith("Received") and job["steps"][-1]["text"].startswith("Received"):
            job["steps"][-1] = {"time": _now(), "text": message}
        else:
            job["steps"].append({"time": _now(), "text": message})

    session = None
    try:
        api_key = os.getenv("CAMPD_API_KEY")
        if not api_key:
            raise CAMPDError("No CAMPD_API_KEY is set on the server. Add it to the .env file and restart the app.")

        client = CAMPDClient(api_key)
        session = SessionLocal(expire_on_commit=False)

        progress("Loading what's already in the database")
        index = DatabaseIndex(session)

        dataset = retrieve_emissions(session, client, index, year, filters, progress)
        job["datasets"].append(_summarize(dataset))

        if include_attributes:
            dataset = retrieve_attributes(session, client, index, year, filters, progress)
            job["datasets"].append(_summarize(dataset))

        progress("Finished")
        job["status"] = "done"

    except CAMPDError as error:
        if session is not None:
            session.rollback()
        job["status"] = "failed"
        job["error"] = str(error)

    except Exception as error:
        if session is not None:
            session.rollback()
        job["status"] = "failed"
        job["error"] = f"Something went wrong: {error}"

    finally:
        if session is not None:
            session.close()
        job["finished"] = _now()
        with _lock:
            if _running_job_id == job_id:
                _running_job_id = None