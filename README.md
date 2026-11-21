# epaData

**EPA power-sector emissions: retrieved, checked, stored, searched and downloaded.**

epaData is a Flask + SQLite web application for the U.S. EPA's Clean Air Markets Program Data (CAMPD). It pulls annual and hourly emissions for every covered power-plant unit through the EPA CAM API, validates every record, stores it in a relational database with full provenance, and lets users search, rank, compare and download the data. Users can also upload their own CSV or Excel files, which go through the same validation before anything is saved.

Phase 1 of the WKU course project (Data Management Website), extended in Phase 2 into a data analysis and decision-support system: descriptive statistics and derived indicators, an interactive dashboard, comparative analysis, EPA TRACI 2.2 impact indicators, prediction models, and sensitivity and scenario analysis (section 12).
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
12. [Phase 2: analysis](#12-phase-2-analysis)
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

### TRACI 2.2 impact factors (Phase 2)

The Impacts page needs EPA's TRACI 2.2 characterization factors for CO2, SO2 and NOx. A small extract of the official file is in `data/traci_2_2_campd_factors.csv`, and the website loads it automatically the first time the Impacts page opens. To load it yourself, or straight from the official workbook:

```bash
python traci.py import                      # from the extract in data/
python traci.py import traci_2_2.xlsx       # from EPA's workbook (download link in section 12.5)
python traci.py show                        # list the factors in the database
```

Each import is recorded on the Datasets page, like an EPA pull.

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
| 18 | Explore sidebar → **NOx control: None reported**, **Emissions program: ARP**, **Reporting years 2020 to 2025** | Only ARP units without a NOx control from 2020 on; **Variables available for analysis** lists every variable with its missing values |
| 19 | Explore `coal` → **Analyze: Dashboard** | Indexed trend of CO2, SO2, NOx and gross load, bar chart by state, distribution, scatter, correlation heat map, highest and lowest facilities, and two maps |
| 20 | On the dashboard choose **Variable: CO2 intensity** and **Compare by: Primary fuel**, then click the **Coal** bar | Charts switch to overall CO2 intensity; the Coal bar opens its calculation (total CO2 ÷ total gross load, with both totals), the records, units and years behind it, and **See these records in Explore**; **About** explains each chart, **PNG image** saves it, **Data CSV** saves its numbers with metadata |
| 21 | **Compare** → **Reporting periods**, A = 2015 to 2017, B = 2023 to 2025, tick **Only units with records in both periods** | Summary statistics for both periods, differences, every normalized indicator, Welch's t-test and Mann–Whitney results in plain language, and every year ranked |
| 22 | **Compare** → **With vs. without an SO2 control**, variable **SO2 intensity** | Units without an SO2 control against units with one |
| 23 | **Impacts** | Potential global warming, acidification, particulate matter and smog totals, per MWh, with each pollutant's share and the TRACI factors used; click any bar, or open **How this was calculated**, to see the arithmetic |
| 24 | On Impacts, **Group by: Facility**, then **Per MWh** | Facilities ranked by potential impact per MWh of generation |
| 25 | **Statistics** → variable **CO2 intensity** → scroll to **Unusual observations** | Records outside Tukey's fences (Q1 − 1.5 × IQR, Q3 + 1.5 × IQR), the most extreme on each side, and a download of all of them |
| 26 | **Predictions** (every record, or any Explore selection with at least three years) | The target and inputs, the excluded inputs (leakage), the train / validate / test years, and each model's MAE, RMSE, R² and weighted % error on the test year; the decision tree or linear regression is marked **Chosen** (lowest validation error) |
| 27 | On Predictions, switch the pollutant to **SO2**, then **NOx** | The same three models trained for that pollutant; each run is saved in `trained_models/` and the `prediction_model` table and reopened on the next visit |
| 28 | Scroll to **Year-trend forecast** | The selection's annual total with the three year-only models and their five-year forecast; the test-year scores and the forecast table |
| 29 | **Scenarios** | A baseline unit from the test year, its inputs and prediction; the one-at-a-time curve (heat input by default, −50% to +50% in 10% steps) with the baseline marked and out-of-range values shaded; and every named scenario with its absolute and % change |
| 30 | On Scenarios choose **Range in: Values**, From 0, To a number above the training maximum | The extra points are drawn as open circles in a shaded **Outside training range** region and flagged in the table and download |
| 31 | **Download** on Predictions and Scenarios | CSV or Excel files whose top lines list the target, inputs, excluded inputs, training / validation / test years, every model's settings, the saved model file and its SHA-256, the baseline, what was held constant, and the software versions |

---

## 6. Features and pages

| Page | URL | What it does |
|---|---|---|
| Overview | `/` | Project introduction, data sources, current data coverage, navigation |
| Explore | `/explore` | Description-based search: type a sentence, get filters, results, refinements with counts, did-you-mean |
| Statistics | `/statistics` | Descriptive statistics and derived indicators for the Explore selection, overall or grouped (Phase 2) |
| Dashboard | `/dashboard` | Interactive Plotly charts: trends, comparisons, distributions, relationships, rankings, maps; within one state, by county (Phase 2) |
| Compare | `/comparison` | Two groups side by side: periods, states, counties, fuels, unit types, control vs none, facilities, units; tests in plain language (Phase 2) |
| Impacts | `/impacts` | EPA TRACI 2.2 potential-impact indicators for CO2, SO2 and NOx, totals, per MWh and by group (Phase 2) |
| Predictions | `/predictions` | A mean baseline, linear regression and a decision tree for a unit's annual CO2, SO2 or NOx, tested chronologically; a year-trend forecast of the annual total (Phase 2) |
| Scenarios | `/scenarios` | One-variable-at-a-time sensitivity curves and named what-if scenarios on a fitted model, with out-of-range warnings (Phase 2) |
| Sensitivity | `/sensitivity` | For one unit, change gross load and heat input by paired percentages (and optionally the fuel type) and see the predicted CO2 from linear regression or a decision tree, with absolute and % change and a range check (Phase 2) |
| All tools | `/search` | Basic and multi-criteria search on every field, with range and comparison operators |
| Rankings | `/advanced-search` | Top-N, bottom-N and group-and-rank (top in each state), with a bar chart of the ranking |
| Compare | `/compare` | Up to four facilities side by side: CO2 and CO2 per MWh by year (one line per plant) and the chosen year as bars, then the tables |
| History | `/history` | One unit across a range of years, charted and in a table |
| Facility | `/facility/<id>` | Location, CO2 and every emission over the years, CO2 by unit, yearly totals, the nearest facilities, data sources, hourly records |
| Unit | `/unit/<key>` | CO2 and every emission over the years, fuels, controls, dates and every annual record |
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
├── dashboard.py         Phase 2: every dashboard chart (Plotly figure + the table behind it)
├── comparison.py        Phase 2: two-group comparisons, statistical tests, group rankings
├── traci.py             Phase 2: TRACI 2.2 import (exact matching) and impact calculation
├── prediction.py        Phase 2: unit models and year-trend forecast; saving models with joblib
├── scenarios.py         Phase 2: one-variable-at-a-time sensitivity and scenario comparison
├── model_charts.py      Phase 2: the Predictions and Scenarios charts
├── explain.py           Phase 2: what each chart explains about itself (About this chart, click-for-calculation)
├── data/
│   └── traci_2_2_campd_factors.csv   The 6 TRACI 2.2 factors used, extracted from EPA's workbook
├── requirements.txt     Python packages
├── .env.example         Template for .env (copy it, then add your EPA API key)
├── tests/               Automated tests (pytest) with a small fixture database
├── static/
│   ├── style.css        The one stylesheet (the site's design system, section 12.8)
│   ├── nav.js           Nav flyouts, search panel ("/" or Command/Ctrl + K) and phone menu; Copy link
│   ├── touches.js       Sortable chart tables and numbers that count up
│   ├── charts.js        Draws every chart in the browser with Plotly.js
│   ├── suggest.js       Search suggestions as you type
│   ├── picker.js        Facility picker for Compare and History
│   └── vendor/          Plotly.js 2.35.2 and the U.S. map outline, so charts work offline
├── templates/           Jinja templates (base.html plus one per page)
├── uploads/             Original uploaded files (created automatically, not committed)
└── trained_models/      Fitted prediction models saved with joblib (created automatically, not committed)
```

Not committed (see `.gitignore`): `.env`, `.venv/`, `epaData.db`, `uploads/`, `trained_models/`, `__pycache__/`, `.idea/`.

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
| `prediction_model` | `prediction_model_id` | run key (shared by the three models fitted together), target, model kind and name, chosen flag, features (JSON), parameters (JSON), training / validation / test years and record counts, validation and test scores (JSON), selection fingerprint and filters, joblib file path and SHA-256, software versions. **Unique on (run key, model kind)** (Phase 2) |
| `traci_factor` | `traci_factor_id` | TRACI version, CAMPD pollutant, TRACI substance, CAS number, match rule, medium, impact category, factor value and unit, source file, SHA-256, sheet, row and column, import time, dataset key. **Unique on (version, pollutant, medium, category)** (Phase 2) |

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
- **U.S. EPA TRACI** characterization factors. https://www.epa.gov/chemical-research/tool-reduction-and-assessment-chemicals-and-other-environmental-impacts-traci
- EPA TRACI 2.2 (Tool for the Reduction and Assessment of Chemicals and other environmental Impacts), updated 3/2/2022: https://www.epa.gov/traci
- Libraries: Flask, Jinja2, Werkzeug, SQLAlchemy, requests, python-dotenv, openpyxl, pandas, NumPy, SciPy, scikit-learn, joblib, pytest; Plotly.js 2.35.2 (MIT license, included in `static/vendor/` with its U.S. map outline).
- Pedregosa et al., *Scikit-learn: Machine Learning in Python*, JMLR 12, 2011 (linear regression, decision trees, metrics).
- Design: the interface follows the design language of apple.com (type scale, navigation, colors, spacing). No Apple logos, images, icons or font files are included; text uses each visitor's own system font.
- **Generative AI disclosure:** Claude (Anthropic) was used as a coding assistant for parts of the implementation, debugging and documentation. All code was reviewed, run and tested by the team.

---

## 12. Phase 2: analysis

Every analysis page works on **exactly the records the Explore page shows**. Search or refine in Explore, then use the **Analyze** links next to the download buttons (Statistics, Dashboard, Compare, Impacts, Predictions, Scenarios). The Explore filters travel in the URL, the analysis links in the top navigation keep them, and every choice on a page is also in the URL, so any analysis can be bookmarked, shared and reopened (**Copy link**, under each page's title, copies it).

### 12.1 Analytical dataset builder (proposal 4.1)

The Explore sidebar selects the records: reporting-year range or a single year, state, county, facility, unit, primary fuel, unit type, operating status, **SO2, NOx and PM control technology** (or "None reported"), **emissions program** (ARP, CSNOX, RGGI…, matched as a whole code), and minimums or maximums for operating time, gross load, heat input and each pollutant. Above the results, **Selected dataset** shows the number of records, facilities, units and years; **Variables available for analysis** lists every facility, unit, annual and derived variable (marking any with no usable values) and the hourly records stored for those units; **Missing-Value Summary** counts the missing values in each.

### 12.2 Descriptive statistics and derived indicators (proposal 4.2 and 4.3)

The **Statistics** page (`/statistics`) analyzes exactly the records the **Explore** page shows. Search or refine in Explore, then click **Statistics** next to the download buttons; every Explore filter carries over in the URL, so any analysis can be bookmarked, shared and reopened.

Under the statistics, **What the numbers say** puts them into words: where a typical record falls, whether a few large values pull the mean above the median, how wide the spread is, why an overall ratio differs from the average record (large units weigh more), which group is highest and lowest, and how many values are unusual. Each sentence is worked out from the numbers on the page (`analysis.interpret`).

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

**Downloads** (CSV or Excel): the overall statistics, the grouped table, and the analytical dataset (every selected record with all derived indicators). Each file starts with its metadata: analysis date, data source, dataset identifier, a selection fingerprint (a short code that changes if the selected unit-years change), the selected filters and the Explore link that reopens them, the variable and its definition, the percentile and standard-deviation methods, the missing-value rule, and the software version (analysis version, Git commit, pandas, NumPy and SciPy versions). In Excel the metadata is on its own sheet; in CSV it is a block of lines starting with `#`, which pandas skips with `pd.read_csv(path, comment="#")`. Dashboard, comparison and impact downloads use the same format.

### 12.3 Interactive dashboard (proposal 4.4)

`/dashboard` draws, for the selection:

| Chart | What it shows |
|---|---|
| Emissions and generation over time | CO2, SO2, NOx and gross load totals by year, each indexed to its first year = 100, so measures with different units share one axis |
| Variable over time | The chosen variable by year (total, or overall ratio for intensities), optionally one line per fuel family or per control group |

**Years with few units.** If the database holds only some units for the earliest years (for example when only recent years were retrieved in full), a total over a few units can't be compared with one over many: CO2 would look as if it grew several hundred times. So both trends measure change from the first year in which at least half as many units reported as in the busiest year. The indexed chart starts in that year, and the single trend shades the earlier years ("Few units reported"), still draws them, and measures its change from that year. Each chart's note gives the unit counts. A selection where every year is well covered is unchanged.
| Bar chart | The chosen variable by state, county, fuel, unit type, year, facility or control group (county is the default when the selection is one state) |
| Box plots | The spread of the variable within the largest groups |
| Histogram | The distribution of the variable (log scale by default, because a few plants emit most of the total) |
| Scatter plot | Any variable against any other, one color per fuel family, with Spearman and Pearson correlations over all records |
| Correlation heat map | Spearman or Pearson correlations between 11 measured and derived variables, each pair drawn once below the diagonal |
| Highest and lowest | The 10 facilities or units at each end (ratios only rank those above a minimum gross load, 10,000 MWh by default) |
| State or county map | The variable by state; for a one-state selection, by county instead (a bubble at the middle of each county's facilities, zoomed to the state) |
| Facility map | Facility locations sized and shaded by the variable, zoomed to the selection when it covers one state or a region (needs latitude and longitude from `python ingest.py --attributes-only`) |

**Every number explains itself.** Select any point, bar, box, state or cell and a sheet opens under the chart with that value, the calculation behind it written out with the real numbers (for example total CO2 mass ÷ total gross load = CO2 intensity), how many records, units, facilities and years went into it, anything left out and why (missing values, zero gross load), and a link that opens exactly those records in Explore. **About** at the top of each chart says what it shows, how each value is calculated, why that kind of chart fits the data, how to read it, and where the data comes from (`explain.py` writes these for every chart, including the Compare, Impacts, Predictions and Scenarios charts). The dashboard's section links stay at the top of the screen while it scrolls.

Every chart sits in a card laid out like the charts in Apple's Health and Stocks apps: a short label, the title, a headline number with its unit and how much it changed, and a legend where there is more than one series (select a legend entry to hide or show that series). On a single trend line, moving the pointer along the line shows that year's value and its change in the headline, and **5Y / 10Y / 20Y / All** change the years shown. Other charts have tooltips; after zooming in, **Reset zoom** goes back. Cards rise into view and lines draw in as the page scrolls (switched off when the system asks for reduced motion). **PNG image** saves the chart with its title and headline, **Data CSV** or **Excel** saves its numbers with the same reproducibility metadata as other exports, and **Show the numbers** opens the table behind it; click a column heading to sort it (highest first, then lowest first, then the original order). Charts are black, gray and white, and color is used sparingly: on a chart with one series, the mark the headline describes is black and the rest gray (the highest bar, the median line); where series are compared, CO2, coal and group A are black, SO2, gas and group B blue, NOx and oil and other fuels gray, and gross load a dashed black line; maps run from light gray to black; whatever you select turns blue. Plotly.js 2.35.2 and the U.S. map outline are kept in `static/vendor/`, so the charts and maps work without an internet connection (useful for a demo).

### 12.4 Comparative analysis (proposal 4.5)

`/comparison` compares two groups of the selection on one variable: two **reporting periods** (optionally only the units that report in both), two **states**, **fuels** or **unit types**, units **with and without an SO2 or NOx control**, or two **facilities** or **units**. It shows each group's summary statistics with absolute and percentage differences (B − A, and (B − A) ÷ |A| × 100); the same comparison for every **normalized indicator** (totals for amounts, overall ratios for intensities, heat rate and utilization); **Welch's t-test** with a 95% confidence interval for the difference in means and the **Mann–Whitney test** with the chance that a B record is higher, each explained in a sentence; box plots, a chart of the indicator differences and a yearly trend; and **every group ranked**, with one-way ANOVA and Kruskal–Wallis tests of whether the groups differ at all. The page lists the assumptions: unit-year records are not fully independent, so p-values are approximate, and differences are associations, not proven causes. Results download as CSV or Excel with metadata.

### 12.5 Environmental and health impact indicators (proposal 4.6)

`/impacts` turns the selection's CO2, SO2 and NOx into potential-impact indicators with **EPA TRACI 2.2** (updated 3/2/2022):

```
mass (kg)              = mass (short tons) × 907.18474
impact in category c   = Σ over pollutants (mass in kg × TRACI factor for c)
impact per MWh         = impact ÷ gross load of the same records
```

| CAMPD pollutant | TRACI row and how it is matched | Category | Factor |
|---|---|---|---|
| CO2 | CARBON DIOXIDE, CAS 124-38-9 | Global warming | 1 kg CO2 eq / kg |
| SO2 | SULFUR DIOXIDE, CAS 7446-09-5 | Acidification | 1 kg SO2 eq / kg |
| SO2 | SULFUR DIOXIDE, CAS 7446-09-5 | Human health: particulate matter | 0.0611 kg PM2.5 eq / kg |
| NOx | NITROGEN OXIDES, exact name (TRACI lists no CAS number) | Acidification | 0.7 kg SO2 eq / kg |
| NOx | NITROGEN OXIDES, exact name | Human health: particulate matter | 0.00722 kg PM2.5 eq / kg |
| NOx | NITROGEN OXIDES, exact name | Smog formation | 24.79 kg O3 eq / kg |

There is no approximate name matching: TRACI also lists NITROGEN DIOXIDE and NITRIC OXIDE with different factors, and they are never used. If a rule finds no row or more than one, the import stops with an error. Each category keeps its own unit and categories are never added together. A record missing a pollutant that a category needs is left out of that category, never counted as 0. The `traci_factor` table stores the TRACI version, CAMPD pollutant, TRACI substance, CAS number, match rule, medium, impact category, factor, unit, source file, its SHA-256, and the sheet, row and column each factor came from; every impact export repeats them.

Every number shows its own arithmetic: each total has a **How this was calculated** section, and clicking any bar in the impact charts opens the worked calculation behind it (tons × 907.18474 = kg, × the TRACI factor, added within the category, ÷ gross load for per MWh), using that bar's actual numbers. The page shows totals and per-MWh values for the selection, each pollutant's share of each category, results by state, fuel, unit type, year, facility, unit or control group, and the factors used. These are **potential** impacts for comparison; they do not measure actual illness, local exposure or proven environmental damage. TRACI 2.2 removed its eutrophication factors (EPA moved them to a separate spatial dataset), so eutrophication is not included.

The official workbook: https://www.epa.gov/system/files/documents/2024-01/traci_2_2.xlsx (the extract in `data/` was made from the identical copy in EPA's GitHub repository, https://github.com/USEPA/TRACI, file `TraciTool/TRACI_2_2.xlsx`, with `python traci.py extract`).

### 12.6 Prediction models (proposal 5)

`/predictions` answers one clearly defined question for the chosen pollutant (CO2 by default, or SO2 or NOx):

> How much does a generating unit emit in a year, given how it operated that year?

| | |
|---|---|
| **Target** | One unit's annual CO2 (or SO2, NOx) mass in short tons; one record = one unit in one year |
| **Inputs** | Gross load (MWh), heat input (mmBtu), operating time (hours), fuel family (coal, gas, oil and other), unit type, SO2 control reported (0/1), NOx control reported (0/1) |
| **Not used (target leakage)** | The same year's CO2, SO2 and NOx; emission intensities (they are the target divided by load); year-over-year changes (computed from the target); facility and unit IDs (they would memorize units); the year itself |
| **Models** | Mean baseline (predicts the training average), linear regression (ordinary least squares), decision tree (depth chosen on validation from 2, 3, 4, 6, 8, 10, 12, 16; at least 5 records per leaf) |
| **Split** | Chronological: the most recent year is the test year, the one or two years before it validate (two when there are six or more years), every earlier year trains. With 1995–2025: train 1995–2022, validate 2023–2024, test 2025 |
| **Procedure** | 1. Fit every model on the training years. 2. Choose the tree depth and the working model by the lowest mean absolute error on the validation years. 3. Refit every model on training + validation years and score each **once** on the test year |
| **Metrics** | MAE, RMSE, R², weighted % error (Σ\|error\| ÷ Σ actual × 100) and mean error; MAPE (records with actual > 0) is in the downloads but not on the page, because it is undefined at zero and dominated by tiny emitters |

Missing values are never filled in: a record missing the target or a numeric input (or with a negative value) is left out and counted. Gross load, heat input and operating time are standardized inside the pipeline so least squares is numerically stable; this changes no prediction, and the linear coefficients are converted back to real units (short tons per MWh, per mmBtu, per hour). Predictions below zero are set to zero.

**Heat input and CO2.** EPA calculates much of the reported CO2 from heat input and a fuel-specific factor, so CO2 models that use heat input are expected to be very accurate. That is a physical relationship rather than the target leaking in, but it means the unit model describes how CO2 follows the fuel burned; it is not a forecast of the future. The page reports a leakage check (the chosen model's test error refit without heat input) and says so in plain words.

The page also shows what the models learned (linear coefficients in real units, the tree's input importances and its depth search), a predicted-vs-actual chart for every test-year record, and the **biggest misses**: the test-year units the model got most wrong, which are the unusual observations worth checking.

**Year-trend forecast** (Maggie's first version of the module, now on any selection): the selection's annual total, predicted from the year alone with the same three kinds of model, scored on the same kind of chronological split, and forecast five years ahead (each model refit on every year). The page warns when the number of reporting units changes a lot between years, because then the totals partly reflect coverage, not only emissions.

**Saved models (proposal 8.1).** Each training run is saved with joblib in `trained_models/<run key>.joblib` and described in the `prediction_model` table (target, features, parameters, training / validation / test years and counts, scores, selection, file SHA-256, software versions). The run key is a hash of the module version, target, selection fingerprint, database state and scikit-learn version, so the same selection on the same data reopens the same models instead of retraining; a file whose SHA-256 no longer matches is not trusted and the models are trained again. Only files this app wrote are ever loaded (joblib files run code when loaded). The newest 30 runs are kept.

Downloads (CSV or Excel): model evaluation (validation and test scores for every model), every test-year prediction, the tree depth search, the year-trend forecast, and every chart's numbers. Each file starts with the target, inputs, excluded inputs, years, every model's parameters, the saved model file and the software versions.

### 12.7 Sensitivity and scenario analysis (proposal 6)

`/scenarios` uses a fitted unit model (the one chosen on validation, or the other candidate) and a **baseline**: one unit's actual inputs in the test year (a large unit by default, the 90th percentile of the pollutant; any test-year unit can be chosen). It shows the baseline prediction next to the unit's actual value.

**One variable at a time.** Choose gross load, heat input or operating time and a range, either as % of the baseline (default −50% to +50% in 10% steps) or as values in the input's own unit, up to 201 points. Every other input stays at the baseline value. Each point reports the input value, the input's % change, the prediction, and the absolute and % change from the baseline prediction. The chart marks the baseline point with reference lines through it, shades the region outside the training range, and draws those points as open circles.

**Scenarios**, each compared with the baseline:

| Scenario | What changes |
|---|---|
| Gross load +10% | Only gross load |
| Heat input −5% | Only heat input (the same electricity from 5% less fuel) |
| Runs 10% more | Gross load, heat input and operating time all +10% (operating time capped at the hours in the year) |
| Fuel changed | Coal → gas, gas → coal, oil and other → gas |
| Control added or removed | The control that matters for the pollutant (SO2 control for CO2 and SO2, NOx control for NOx) |
| High efficiency (combined) | Gross load +10% and heat input −5% together |
| Your scenario | Any mix of % changes, a fuel and controls from the form |

```
absolute change = scenario prediction − baseline prediction
% change        = (scenario prediction − baseline prediction) ÷ baseline prediction × 100   (undefined when the baseline is 0)
```

A warning appears whenever an input is outside the training range (minimum to maximum of the training and validation records), operating time exceeds the hours in the year, or a fuel and unit-type combination (or a control on a fuel) never appears in training. Bad form values (text, a zero step, an end below the start, too many points, a unit with no test-year record) fall back to safe defaults with a message instead of an error. These are **model-response** results: they show how the fitted model reacts, not what would happen at a real plant, where inputs move together. Downloads list the model and its settings, the baseline unit and inputs, the range, and what was held constant.

### 12.8 Interface design

The interface follows apple.com's design language: one translucent, sticky 44 px navigation bar with flyout menus, a search panel and a phone menu (no logo; on a phone it shows the page's name), with the selection, **Change selection**, the page's main download and **Copy link** under each page's title; centered heroes; full-width bands alternating white and #f5f5f7, with black bands for headline numbers; white cards with 18 px corners (28 px around charts); pill buttons in #0071e3; blue text links; two-tone section headlines; and the gray footer with its directory. Text uses the visitor's own system font (San Francisco on Apple devices) with Apple's type scale and letter spacing, and the layout follows Apple's breakpoints (1068 px and 734 px). Charts use the same fonts and grays, dotted hairline grids, values on the right of time series, and slim rounded bars with their names above them. Color is used sparingly, as on apple.com: marks are black (`#1d1d1f`), gray (`#8e8e93`, `#c7c7cc`) and white, and blue (`#0071e3`) is the one accent, for the second series and for whatever is selected. On a one-series chart the mark the headline number describes is black and the rest gray; maps run from light gray to black, and correlations from blue through light gray to black. The black, blue and gray series passed a color-blind separation check; no purple is used. Sections are spaced generously (120 px between bands on a desktop).

### 12.9 Unusual observations (proposal goal 5)

The Statistics page lists the records whose value of the chosen variable lies outside Tukey's fences, Q1 − 1.5 × IQR and Q3 + 1.5 × IQR (the same rule the box plots use), with the most extreme on each side, how far past the fence each one is in IQRs, and a download of all of them. Emissions are skewed, so large plants often sit above the upper fence: unusual is not the same as wrong. The Predictions page adds the test-year units the model missed by the most.

---

## 13. Run the automated tests

```bash
python -m pytest
```

The tests build a small fixture database (3 facilities, 4 units, 8 annual records, 3 hourly records) in a temporary folder, so they never touch your real `epaData.db`. The fixture values are chosen so every expected result can be checked by hand; the arithmetic is written out at the top of each test file.

| File | What it checks |
|---|---|
| `tests/test_analysis.py` | Derived indicators, missing and zero-denominator handling, descriptive statistics, grouping |
| `tests/test_statistics_page.py` | The Statistics page and its CSV/Excel exports with metadata |
| `tests/test_phase2_pages.py` | Explore filters for controls, programs and years; variable and hourly summaries; every dashboard chart, the headline above it, its About notes and the calculation shown when a point is selected; the Statistics findings; comparisons, with the t-test and Mann–Whitney results checked against SciPy |
| `tests/test_traci.py` | TRACI import with exact matching only (a missing NITROGEN OXIDES row stops the import instead of falling back to NITROGEN DIOXIDE), the bundled factors, and impact totals checked by hand |
| `tests/test_prediction.py` | The chronological split; metrics checked by hand; no input reveals the target; the test year can't influence training, the tree depth or the model choice; linear regression recovers a known CO2 = 0.1 × heat input exactly; saving, reopening and rejecting a changed model file; the year-trend forecast of a straight line; one-at-a-time and scenario % changes checked by hand; out-of-range and bad-input handling; the Predictions and Scenarios pages and downloads |
| `tests/test_unusual.py` | Unusual observations: Tukey's fences and the most extreme records checked by hand, and the Statistics page and its download |
| `tests/test_polish.py` | County labels, bars, maps and comparisons; maps that zoom only to small areas; the single navigation bar keeping the selection; the headline mark in black; sortable tables; distances and nearby facilities; trends that measure change from the first year most units reported; the charts on the facility, unit, history, Compare facilities and Rankings pages |

Expected result: all 108 tests pass.
