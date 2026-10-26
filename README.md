# epaData

**EPA power-sector emissions: retrieved, checked, stored, searched and downloaded.**

epaData is a Flask + SQLite web application for the U.S. EPA's Clean Air Markets Program Data (CAMPD). It pulls annual and hourly emissions for every covered power-plant unit through the EPA CAM API, validates every record, stores it in a relational database with full provenance, and lets users search, rank, compare and download the data. Users can also upload their own CSV or Excel files, which go through the same validation before anything is saved.

Phase 1 of the WKU course project (Data Management Website), now being extended in Phase 2 into a data analysis and decision-support system (descriptive statistics and derived indicators so far; see section 12).
Team: **Danny Rios** and **Maggie Ford**.

---

## Contents

1. [Requirements](#1-requirements)
2. [Setup, step by step](#2-setup-step-by-step)
3. [Load the EPA data](#3-load-the-epa-data)
4. [Run the website](#4-run-the-website)
5. [Reproduce the main results](#5-reproduce-the-main-results)
6. [Features and pages](#6-features-and-pages)
7. [Upload file format](#7-upload-file-format)
8. [Project structure](#8-project-structure)
9. [Database schema](#9-database-schema)
10. [Troubleshooting](#10-troubleshooting)
11. [Data sources and acknowledgments](#11-data-sources-and-acknowledgments)
12. [Phase 2: statistics and derived indicators](#12-phase-2-statistics-and-derived-indicators)
13. [Run the automated tests](#13-run-the-automated-tests)

---

## 1. Requirements

| What | Version | Notes |
|---|---|---|
| Python | 3.9 or newer | Tested on 3.9 (macOS) and 3.13 (Linux) |
| pip | any recent | Comes with Python |
| Git | any | To clone the repository |
| EPA API key | free | Needed only to pull data from the EPA (step 2.4) |
| Internet | | Needed for the EPA pull; the website itself runs offline |

No database server is needed: SQLite is built into Python, and the database is a single file, `epaData.db`.

All Python packages are listed in `requirements.txt` (Flask, SQLAlchemy, requests, python-dotenv, openpyxl, pandas, NumPy, pytest and their dependencies). The right NumPy version is picked automatically for Python 3.9 and for 3.10 or newer.

---

## 2. Setup, step by step

### 2.1 Get the code

```bash
git clone https://github.com/MaggieFord8062/epaData.git
cd epaData
```

### 2.2 Create a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Your terminal prompt should now start with `(.venv)`.

### 2.3 Install the packages

```bash
pip install -r requirements.txt
```

### 2.4 Get an EPA API key and put it in `.env`

1. Sign up for a free key at **https://www.epa.gov/power-sector/cam-api-portal** (it arrives by email within a few minutes).
2. In the project folder, copy `.env.example` to a file named exactly `.env` (or create `.env` yourself) with this line:

```
CAMPD_API_KEY=paste-your-key-here
```

Optional, for the session messages on the facility page:

```
FLASK_SECRET_KEY=any-long-random-text
```

The key is read on the server only. It is never sent to the browser, never written into JavaScript, and `.env` is listed in `.gitignore`, so it is never committed to GitHub.

---

## 3. Load the EPA data

The database file is not in the repository (it is too large and is listed in `.gitignore`). Build it with `ingest.py`:

```bash
python ingest.py
```

This pulls **2015 through 2025 for every state**: about 47,000 annual unit records. For each year it:

1. pulls annual apportioned emissions, validates every record and stores the new ones;
2. pulls facility attributes (county, latitude/longitude, source category, operating and retirement dates).

It prints one block per year, for example:

```
2025: annual emissions (all states)
  Dataset #72: received 3989, accepted 3989
    3989 new
    0 already stored
```

The full run takes roughly 10 to 20 minutes, depending on the EPA API. Other options:

```bash
python ingest.py 2024                 # one year
python ingest.py 2020 2024            # a range of years
python ingest.py --attributes-only    # only refresh county, location, source category and dates
```

Running it again is safe: records already in the database are skipped, never duplicated.

**No API key?** You can still run the website. Start it (step 4) and either use the **Retrieve** page later, or load data through the **Upload** page with a CSV or Excel file (section 7).

---

## 4. Run the website

```bash
python app.py
```

Open **http://127.0.0.1:5000** in a browser. Stop the server with `Ctrl+C`.

On first start, `database.py` creates any missing tables and adds any missing columns to an older `epaData.db`, without deleting existing data.

---

## 5. Reproduce the main results

After step 3, each of these should work exactly as described.

| # | Do this | Expected result |
|---|---|---|
| 1 | Home page | Record, facility and unit counts; top emitters; links to every tool |
| 2 | Type `coal kentucky 2025 co2 over 500k` in the search bar | Chips show *State: Kentucky*, *Fuel: Coal*, *Year: 2025*, *CO₂ over 500,000 tons*; every row is a Kentucky coal unit in 2025 above 500,000 tons |
| 3 | Search `biggest so2 emitters in ohio` | Ohio units sorted by SO₂, highest first |
| 4 | Search with a typo, e.g. `mill creak` | "creak" is corrected to "creek" and Mill Creek is found |
| 5 | Open **Mill Creek** (KY), then a unit | Facility page with units and yearly totals; unit page with every year 2015–2025 |
| 6 | **Rankings** → top 10 facilities by CO₂ | Ten facilities, largest first; the link reopens the same ranking |
| 7 | **Rankings** → group by state | The top CO₂ facility in every state |
| 8 | **Compare** → pick up to four facilities | Side-by-side totals with CO₂ per MWh |
| 9 | **History** → pick a unit | The same unit from 2015 to 2025 |
| 10 | **Retrieve** → year 2024, state KY | Live progress, then a new dataset on the **Datasets** page; already-stored records are reported as skipped |
| 11 | **Upload** the sample file from section 7 | Preview, column match, and a quality report listing the rejected rows; **Approve** stores the valid rows |
| 12 | **Download** → a dataset, CSV | A CSV with the same rows the filters show |
| 13 | Facility page → **Hourly records** → a unit and date → **Import** | Hourly rows for that day, including mercury where reported |
| 14 | Explore `coal kentucky` → **Statistics** | Statistics page for the same records; CO₂ intensity by default, with count, missing values, quartiles, percentiles and the overall ratio |
| 15 | On that page choose **Group by: Year** and variable **CO₂ mass** | One row per year with the total CO₂ for Kentucky coal units, oldest first |
| 16 | Choose variable **CO₂ mass % change from previous year** | Year-over-year change per unit; units without a record for the previous year are counted as missing |
| 17 | **Download CSV** in the analytical dataset section | Every selected record with all derived indicators, with the filters, definitions and software version at the top of the file |

---

## 6. Features and pages

| Page | URL | What it does |
|---|---|---|
| Overview | `/` | Project introduction, data sources, current data coverage, navigation |
| Explore | `/explore` | Description-based search: type a sentence, get filters, results, refinements with counts, did-you-mean |
| Statistics | `/statistics` | Descriptive statistics and derived indicators for the Explore selection, overall or grouped (Phase 2) |
| All tools | `/search` | Basic and multi-criteria search on every field, with range and comparison operators |
| Rankings | `/advanced-search` | Top-N, bottom-N and group-and-rank (top in each state) |
| Compare | `/compare` | Up to four facilities side by side |
| History | `/history` | One unit across every reporting year |
| Facility | `/facility/<id>` | Location, units, yearly totals, data sources, hourly records |
| Unit | `/unit/<key>` | Fuels, controls, dates and every annual record |
| Retrieve | `/retrieve` | Pull data from the EPA CAM API with filters; runs in the background with progress |
| Datasets | `/datasets` | Every retrieval and upload: source, date, query, counts, notes |
| Upload | `/upload` | CSV / Excel upload with validation, preview, quality report, approve or cancel |
| Download | `/downloads` | Full datasets, filtered records, quality reports and provenance, as CSV or Excel |

**Search.** Basic fields: facility name and ID, unit ID, state, county, year, primary and secondary fuel, unit type, SO₂/NOx/PM control, source category. Numeric fields (operating time, gross load, heat input, CO₂, SO₂, NOx) accept equals, greater than, less than and between. All conditions combine with AND. Results are paginated (25, 50 or 100 per page), sortable by any column, linked to unit pages, downloadable, and every search is saved in the URL so it can be shared or reopened.

**Description-based search** (`smart_search.py`) understands states and state names, counties, fuels, unit types, control technologies, years and year ranges ("2020 to 2024"), number conditions ("co2 over 500k", "so2 under 500", "operating time more than 5000 hours"), and sorting words ("biggest", "cleanest", "lowest nox"). Misspelled words are corrected against the names and values in the database (`mill creak` finds Mill Creek), and when nothing matches exactly it shows the closest results instead of an empty page.

**Validation.** Every row, from the API or an upload, goes through the same checks: required fields, numeric fields that must be numbers, no negative emissions, operating time no more than 8,784 hours, sensible years, and duplicate facility-unit-year detection. Rejected rows are never discarded silently: they are counted on the dataset and listed in a downloadable quality report.

**Provenance.** Every retrieval and upload creates a dataset row with its source, date, query parameters, reporting year, raw and accepted counts, and notes. Every annual record points to the dataset it came from.

---

## 7. Upload file format

Accepted: `.csv` and `.xlsx`, up to 10 MB.

**Required columns:** facility ID, facility name, state, unit ID, year.
**Optional columns:** unit type, primary fuel, secondary fuel, operating time, gross load, steam load, heat input, CO₂ mass, SO₂ mass, NOx mass, SO₂ control, NOx control, PM control, program code.

Column names are matched flexibly, so `Facility ID`, `facility_id` and `facilityId` all work, as do the column names in CAMPD's own downloads.

A small test file (`sample_upload.csv`), with one deliberately bad row and one duplicate:

```csv
Facility ID,Facility Name,State,Unit ID,Year,Primary Fuel,Unit Type,Operating Time,Gross Load (MWh),Heat Input (mmBtu),CO2 Mass (short tons),SO2 Mass (short tons),NOx Mass (short tons)
99001,Test Station,KY,1,2025,Coal,Tangentially-fired,7200,1500000,14000000,1400000,900,1800
99001,Test Station,KY,2,2025,Pipeline Natural Gas,Combined cycle,6100,800000,6000000,350000,2,120
99001,Test Station,KY,3,2025,Coal,Dry bottom wall-fired boiler,5000,900000,8500000,-900,400,700
99001,Test Station,KY,1,2025,Coal,Tangentially-fired,7200,1500000,14000000,1400000,900,1800
```

Expected: 2 rows ready, 1 rejected ("CO2 is negative (-900)"), 1 duplicate.

---

## 8. Project structure

```
epaData/
├── app.py               Flask routes: pages, downloads, JSON APIs, upload flow
├── database.py          SQLite engine and session; adds missing columns to older databases
├── models.py            SQLAlchemy models (tables, keys, relationships, unique rules)
├── client.py            EPA CAM API client: paging, retries, errors
├── retrieval.py         Pulls, validates and stores annual, attribute and hourly data with provenance
├── retrieval_jobs.py    Runs a retrieval in a background thread and reports progress
├── ingest.py            Command-line bulk loader (2015–2025)
├── validation.py        Record checks shared by API pulls and uploads
├── uploads.py           Upload pipeline: read, match columns, validate, report, import
├── search.py            Filtered search, rankings, comparison, history queries
├── smart_search.py      Description-based search: parsing, typo correction, relevance, facets
├── analysis.py          Phase 2: derived indicators, descriptive statistics, exports with metadata
├── requirements.txt     Python packages
├── .env.example         Template for .env (copy it, then add your EPA API key)
├── tests/               Automated tests (pytest) with a small fixture database
├── static/
│   ├── style.css        The one stylesheet
│   ├── suggest.js       Search suggestions as you type
│   └── picker.js        Facility picker for Compare and History
├── templates/           Jinja templates (base.html plus one per page)
└── uploads/             Original uploaded files (created automatically, not committed)
```

Not committed (see `.gitignore`): `.env`, `.venv/`, `epaData.db`, `uploads/`, `__pycache__/`, `.idea/`.

---

## 9. Database schema

```
dataset ──────────────┬───────────────────────────┬──────────────────┐
  dataset_id PK       │                           │                  │
  name, source,       │                           │                  │
  reporting_year,     │                           │                  │
  retrieval date,     │                           │                  │
  query_parameters,   │                           │                  │
  raw / accepted,     │                           │                  │
  notes               │                           │                  │
                      ▼                           ▼                  ▼
facility ──► unit ──► annual_records         uploaded_file      hourly_records
```

| Table | Key | Main columns |
|---|---|---|
| `facility` | `epa_facility_id` | name, state, county, latitude, longitude, source category, owner |
| `unit` | `internal_unit_key` | `epa_facility_id` → facility, `epa_unit_id`, unit type, primary and secondary fuel (with dates), operating date, retirement date |
| `annual_records` | `annual_record_id` | facility, unit and dataset keys; year; operating time, gross load, steam load, heat input; CO₂, SO₂, NOx mass; SO₂/NOx/PM control info; program code. **Unique on (facility, unit, year)** |
| `dataset` | `dataset_id` | name, source, reporting year, retrieval/upload date, original filename, query parameters (JSON), raw and accepted counts, notes |
| `uploaded_file` | `upload_id` | original filename, stored path, type, size, upload time, status (pending / imported / cancelled), rows read / ready / rejected, dataset key |
| `hourly_records` | `hourly_records_id` | unit and dataset keys; timestamp; operating time, gross load, steam load, heat input; CO₂, SO₂, NOx, mercury mass |

Indexes cover every commonly searched column: state, county, fuel, unit type, year, source category and the emission and load amounts.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `No CAMPD_API_KEY found in .env` | Create `.env` in the project folder (step 2.4), then restart |
| `ModuleNotFoundError` | Activate the virtual environment (`source .venv/bin/activate`) and run `pip install -r requirements.txt` |
| `NotOpenSSLWarning` on macOS | Harmless warning from the system Python; everything still works |
| Port 5000 already in use (macOS AirPlay) | Run `flask --app app run --port 5001` and open http://127.0.0.1:5001 |
| Pages are empty | The database has no data yet: run `python ingest.py` (step 3) |
| Secondary fuel or steam load shows "—" | Not a bug: the EPA reports steam load only for plants that sell steam (about 7% of records) and secondary fuel only for units that registered one (about 40% of units) |
| EPA retrieval fails or times out | The EPA API is occasionally slow; run it again. Already-stored records are skipped |

---

## 11. Data sources and acknowledgments

- **U.S. EPA Clean Air Markets Program Data (CAMPD)**, CAM API: annual and hourly apportioned emissions, MATS hourly mercury, facility attributes. https://campd.epa.gov · https://www.epa.gov/power-sector/cam-api-portal
- **U.S. EPA TRACI** characterization factors (to be used in Phase 2). https://www.epa.gov/chemical-research/tool-reduction-and-assessment-chemicals-and-other-environmental-impacts-traci
- Libraries: Flask, Jinja2, Werkzeug, SQLAlchemy, requests, python-dotenv, openpyxl, pandas, NumPy, pytest.
- **Generative AI disclosure:** Claude (Anthropic) was used as a coding assistant for parts of the implementation, debugging and documentation. All code was reviewed, run and tested by the team.

---

## 12. Phase 2: statistics and derived indicators

The **Statistics** page (`/statistics`) analyzes exactly the records the **Explore** page shows. Search or refine in Explore, then click **Statistics** next to the download buttons; every Explore filter carries over in the URL, so any analysis can be bookmarked, shared and reopened.

**Choices** (also saved in the URL):

| URL parameter | What it does | Values |
|---|---|---|
| `variable` | The variable to analyze | measured values (`co2_mass`, `so2_mass`, `nox_mass`, `gross_load`, `heat_input`, `operating_time`, `steam_load`), derived indicators (below), or year-over-year change (`co2_mass_change`, `co2_mass_change_pct`, and the same for `so2_mass`, `nox_mass`, `gross_load`) |
| `group` | Statistics for each group | `state`, `primary_fuel`, `unit_type`, `year`, `facility`, `so2_control`, `nox_control` |
| `pct` | Extra percentiles | e.g. `5,10,90,95` (default) |
| `gsort` | Grouped-table order | `group`, `records`, `mean`, `median`, `total`, `overall` |

Example: `/statistics?q=coal+kentucky&variable=heat_rate&group=year`

**Statistics** for the selected variable: count of values present, missing count, minimum, first quartile, median, mean, third quartile, maximum, interquartile range, sample standard deviation (n − 1), selected percentiles, the total (for amounts that can be added) and the overall ratio (for ratios). Percentiles use linear interpolation between the closest ranks, the same method as Excel's `PERCENTILE.INC` and NumPy's default.

**Derived indicators** (`analysis.py`):

| Indicator | Formula | Unit |
|---|---|---|
| CO₂ intensity | CO₂ mass ÷ gross load | short tons/MWh |
| SO₂ intensity | SO₂ mass × 2,000 ÷ gross load | lb/MWh |
| NOx intensity | NOx mass × 2,000 ÷ gross load | lb/MWh |
| Heat rate | heat input ÷ gross load | mmBtu/MWh |
| Operating utilization | operating time ÷ hours in the year (8,760 or 8,784) × 100 | % |
| Year-over-year change | this year − the same unit's previous year | same as the variable |
| Year-over-year % change | (this year − previous year) ÷ previous year × 100 | % |

**Missing and undefined values.** A ratio is left missing when either input is missing or the denominator is zero or negative (for example, a unit that reported no gross load); it is never replaced with 0. Missing values are left out of every statistic and counted separately, and the page says how many were missing because the denominator was 0. Year-over-year change reads the previous year from the whole database, so a one-year selection still has something to compare with; it is missing when the unit has no record for the previous year.

**Mean versus overall ratio.** For a ratio, the *mean* averages each record's own ratio (every unit counts equally), while the *overall ratio* divides one total by the other over the same records (large units count more). Both are shown because they answer different questions.

**Downloads** (CSV or Excel): the overall statistics, the grouped table, and the analytical dataset (every selected record with all derived indicators). Each file starts with its metadata: analysis date, data source, dataset identifier, a selection fingerprint (a short code that changes if the selected unit-years change), the selected filters and the Explore link that reopens them, the variable and its definition, the percentile and standard-deviation methods, the missing-value rule, and the software version (analysis version, Git commit, pandas and NumPy versions). In Excel the metadata is on its own sheet; in CSV it is a block of lines starting with `#`, which pandas skips with `pd.read_csv(path, comment="#")`.

---

## 13. Run the automated tests

```bash
python -m pytest
```

The tests build a small fixture database (3 facilities, 4 units, 8 annual records) in a temporary folder, so they never touch your real `epaData.db`. The fixture values are chosen so the expected statistics can be checked by hand; the arithmetic is written out at the top of `tests/test_analysis.py`. Expected result: all tests pass.
