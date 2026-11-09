# epaData

**EPA power-sector emissions: retrieved, checked, stored, searched and downloaded.**

epaData is a Flask + SQLite web application for the U.S. EPA's Clean Air Markets Program Data (CAMPD). It pulls annual and hourly emissions for every covered power-plant unit through the EPA CAM API, validates every record, stores it in a relational database with full provenance, and lets users search, rank, compare and download the data. Users can also upload their own CSV or Excel files, which go through the same validation before anything is saved.

Phase 1 of the WKU course project (Data Management Website), extended in Phase 2 into a data analysis and decision-support system: descriptive statistics and derived indicators, an interactive dashboard, comparative analysis, and EPA TRACI 2.2 impact indicators (section 12).
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
| 20 | On the dashboard choose **Variable: CO2 intensity** and **Compare by: Primary fuel** | Charts switch to overall CO2 intensity; hover any chart for values, **PNG image** saves it, **Data CSV** saves its numbers with metadata |
| 21 | **Compare** → **Reporting periods**, A = 2015 to 2017, B = 2023 to 2025, tick **Only units with records in both periods** | Summary statistics for both periods, differences, every normalized indicator, Welch's t-test and Mann–Whitney results in plain language, and every year ranked |
| 22 | **Compare** → **With vs. without an SO2 control**, variable **SO2 intensity** | Units without an SO2 control against units with one |
| 23 | **Impacts** | Potential global warming, acidification, particulate matter and smog totals, per MWh, with each pollutant's share and the TRACI factors used |
| 24 | On Impacts, **Group by: Facility**, then **Show per MWh** | Facilities ranked by potential impact per MWh of generation |

---

## 6. Features and pages

| Page | URL | What it does |
|---|---|---|
| Overview | `/` | Project introduction, data sources, current data coverage, navigation |
| Explore | `/explore` | Description-based search: type a sentence, get filters, results, refinements with counts, did-you-mean |
| Statistics | `/statistics` | Descriptive statistics and derived indicators for the Explore selection, overall or grouped (Phase 2) |
| Dashboard | `/dashboard` | Interactive Plotly charts: trends, comparisons, distributions, relationships, rankings, maps (Phase 2) |
| Compare | `/comparison` | Two groups side by side: periods, states, fuels, unit types, control vs none, facilities, units; tests in plain language (Phase 2) |
| Impacts | `/impacts` | EPA TRACI 2.2 potential-impact indicators for CO2, SO2 and NOx, totals, per MWh and by group (Phase 2) |
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
├── dashboard.py         Phase 2: every dashboard chart (Plotly figure + the table behind it)
├── comparison.py        Phase 2: two-group comparisons, statistical tests, group rankings
├── traci.py             Phase 2: TRACI 2.2 import (exact matching) and impact calculation
├── data/
│   └── traci_2_2_campd_factors.csv   The 6 TRACI 2.2 factors used, extracted from EPA's workbook
├── requirements.txt     Python packages
├── .env.example         Template for .env (copy it, then add your EPA API key)
├── tests/               Automated tests (pytest) with a small fixture database
├── static/charts.js     Draws the dashboard charts in the browser with Plotly.js
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
- **U.S. EPA TRACI** characterization factors (to be used in Phase 2). https://www.epa.gov/chemical-research/tool-reduction-and-assessment-chemicals-and-other-environmental-impacts-traci
- EPA TRACI 2.2 (Tool for the Reduction and Assessment of Chemicals and other environmental Impacts), updated 3/2/2022: https://www.epa.gov/traci
- Libraries: Flask, Jinja2, Werkzeug, SQLAlchemy, requests, python-dotenv, openpyxl, pandas, NumPy, SciPy, pytest; Plotly.js 2.35.2 (loaded in the browser from cdnjs).
- **Generative AI disclosure:** Claude (Anthropic) was used as a coding assistant for parts of the implementation, debugging and documentation. All code was reviewed, run and tested by the team.

---

## 12. Phase 2: analysis

Every analysis page works on **exactly the records the Explore page shows**. Search or refine in Explore, then use the **Analyze** links next to the download buttons (Statistics, Dashboard, Compare, Impacts). The Explore filters travel in the URL, the tabs at the top of each analysis page keep them, and every choice on a page is also in the URL, so any analysis can be bookmarked, shared and reopened.

### 12.1 Analytical dataset builder (proposal 4.1)

The Explore sidebar selects the records: reporting-year range or a single year, state, county, facility, unit, primary fuel, unit type, operating status, **SO2, NOx and PM control technology** (or "None reported"), **emissions program** (ARP, CSNOX, RGGI…, matched as a whole code), and minimums or maximums for operating time, gross load, heat input and each pollutant. Above the results, **Selected dataset** shows the number of records, facilities, units and years; **Variables available for analysis** lists every facility, unit, annual and derived variable (marking any with no usable values) and the hourly records stored for those units; **Missing-Value Summary** counts the missing values in each.

### 12.2 Descriptive statistics and derived indicators (proposal 4.2 and 4.3)

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

**Downloads** (CSV or Excel): the overall statistics, the grouped table, and the analytical dataset (every selected record with all derived indicators). Each file starts with its metadata: analysis date, data source, dataset identifier, a selection fingerprint (a short code that changes if the selected unit-years change), the selected filters and the Explore link that reopens them, the variable and its definition, the percentile and standard-deviation methods, the missing-value rule, and the software version (analysis version, Git commit, pandas, NumPy and SciPy versions). In Excel the metadata is on its own sheet; in CSV it is a block of lines starting with `#`, which pandas skips with `pd.read_csv(path, comment="#")`. Dashboard, comparison and impact downloads use the same format.

### 12.3 Interactive dashboard (proposal 4.4)

`/dashboard` draws, for the selection:

| Chart | What it shows |
|---|---|
| Emissions and generation over time | CO2, SO2, NOx and gross load totals by year, each indexed to its first year = 100, so measures with different units share one axis |
| Variable over time | The chosen variable by year (total, or overall ratio for intensities), optionally one line per fuel family or per control group |
| Bar chart | The chosen variable by state, fuel, unit type, year, facility or control group |
| Box plots | The spread of the variable within the largest groups |
| Histogram | The distribution of the variable (log scale by default, because a few plants emit most of the total) |
| Scatter plot | Any variable against any other, one color per fuel family, with Spearman and Pearson correlations over all records |
| Correlation heat map | Spearman or Pearson correlations between 11 measured and derived variables |
| Highest and lowest | The 10 facilities or units at each end (ratios only rank those above a minimum gross load, 10,000 MWh by default) |
| State map | The variable by state |
| Facility map | Facility locations colored by the variable (needs latitude and longitude from `python ingest.py --attributes-only`) |

Every chart has a title, units, a legend where there is more than one series, and tooltips. **PNG image** saves the chart, **Data CSV** or **Excel** saves its numbers with the same reproducibility metadata as other exports, and **Show the numbers** opens the table behind it. Colors always mean the same thing: CO2, coal and group A are blue; SO2, gas and group B orange; NOx and oil and other fuels green. Charts load Plotly.js from cdnjs, so they need an internet connection; the tables work without one.

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

The page shows totals and per-MWh values for the selection, each pollutant's share of each category, results by state, fuel, unit type, year, facility, unit or control group, and the factors used. These are **potential** impacts for comparison; they do not measure actual illness, local exposure or proven environmental damage. TRACI 2.2 removed its eutrophication factors (EPA moved them to a separate spatial dataset), so eutrophication is not included.

The official workbook: https://www.epa.gov/system/files/documents/2024-01/traci_2_2.xlsx (the extract in `data/` was made from the identical copy in EPA's GitHub repository, https://github.com/USEPA/TRACI, file `TraciTool/TRACI_2_2.xlsx`, with `python traci.py extract`).

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
| `tests/test_phase2_pages.py` | Explore filters for controls, programs and years; variable and hourly summaries; every dashboard chart; comparisons, with the t-test and Mann–Whitney results checked against SciPy |
| `tests/test_traci.py` | TRACI import with exact matching only (a missing NITROGEN OXIDES row stops the import instead of falling back to NITROGEN DIOXIDE), the bundled factors, and impact totals checked by hand |

Expected result: all 63 tests pass.
