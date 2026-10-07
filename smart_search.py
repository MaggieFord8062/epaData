"""
smart_search.py
The data explorer's search, built to work like a shopping search box:
type whatever you know, in any order, and still get useful results.

    "coal kentucky 2025 co2 over 500k"   -> KY, coal units, 2025, CO2 > 500,000 tons
    "biggest so2 emitters in ohio"       -> OH, sorted by SO2, highest first
    "jefferson county gas turbines"      -> Jefferson County, gas fuel, turbine units
    "mil crek"                           -> corrected to "mill creek"

How it works:
  1. parse_query() pulls out everything it recognizes (years, states, fuels, unit types,
     controls, counties, number conditions, "biggest"/"cleanest" sorting words).
  2. Words it doesn't recognize are matched against facility names, counties, fuels,
     unit types and controls. Misspelled words are corrected to the closest real word.
  3. Results are ranked by relevance: a facility-name match beats a county match,
     which beats a fuel or control match.
  4. If no record matches every word, it shows records that match some of them,
     instead of an empty page.
  5. Sidebar refinements (state, year, fuel...) show how many results each choice has.
"""
import difflib
import os
import re

from search import (DB_PATH, RESULT_COLUMNS, BASE_JOIN, build_where, connect,
                    to_number, to_positive_int)

# ---------- Words the search understands ----------

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "puerto rico": "PR", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
STATE_CODES = set(STATE_NAMES.values())
CODE_TO_STATE = {code: name.title() for name, code in STATE_NAMES.items()}

# Two-letter codes that are also ordinary English words. These only count as a state
# when typed in capitals ("IN", "OH"), so "coal in Kentucky" doesn't mean Indiana.
AMBIGUOUS_CODES = {"in", "or", "me", "ok", "hi", "de", "pa", "ma", "la", "al", "id", "co", "oh", "mi", "mo", "ne", "md"}

# Phrase -> (filter, value, label). Longer phrases are matched first.
PHRASES = {
    # fuels
    "pipeline natural gas": ("fuel_like", "pipeline natural gas", "Pipeline natural gas"),
    "natural gas": ("fuel_like", "natural gas", "Natural gas"),
    "petroleum coke": ("fuel_like", "petroleum coke", "Petroleum coke"),
    "pet coke": ("fuel_like", "petroleum coke", "Petroleum coke"),
    "coal refuse": ("fuel_like", "coal refuse", "Coal refuse"),
    "diesel oil": ("fuel_like", "diesel", "Diesel oil"),
    "residual oil": ("fuel_like", "residual", "Residual oil"),
    "process gas": ("fuel_like", "process gas", "Process gas"),
    "coal": ("fuel_like", "coal", "Coal"),
    "coal-fired": ("fuel_like", "coal", "Coal"),
    "gas": ("fuel_like", "gas", "Gas"),
    "gas-fired": ("fuel_like", "gas", "Gas"),
    "ng": ("fuel_like", "natural gas", "Natural gas"),
    "oil": ("fuel_like", "oil", "Oil"),
    "diesel": ("fuel_like", "diesel", "Diesel oil"),
    "wood": ("fuel_like", "wood", "Wood"),
    "biomass": ("fuel_like", "wood", "Wood"),
    "petcoke": ("fuel_like", "petroleum coke", "Petroleum coke"),
    # unit types
    "combined cycle": ("unit_type_like", "combined cycle", "Combined cycle"),
    "combustion turbine": ("unit_type_like", "combustion turbine", "Combustion turbine"),
    "cell burner": ("unit_type_like", "cell burner", "Cell burner boiler"),
    "dry bottom": ("unit_type_like", "dry bottom", "Dry bottom boiler"),
    "wet bottom": ("unit_type_like", "wet bottom", "Wet bottom boiler"),
    "tangentially fired": ("unit_type_like", "tangentially", "Tangentially-fired"),
    "tangentially-fired": ("unit_type_like", "tangentially", "Tangentially-fired"),
    "fluidized bed": ("unit_type_like", "fluidized", "Fluidized bed"),
    "wall fired": ("unit_type_like", "wall-fired", "Wall-fired boiler"),
    "wall-fired": ("unit_type_like", "wall-fired", "Wall-fired boiler"),
    "cc": ("unit_type_like", "combined cycle", "Combined cycle"),
    "turbine": ("unit_type_like", "turbine", "Turbine"),
    "turbines": ("unit_type_like", "turbine", "Turbine"),
    "boiler": ("unit_type_like", "boiler", "Boiler"),
    "boilers": ("unit_type_like", "boiler", "Boiler"),
    "stoker": ("unit_type_like", "stoker", "Stoker"),
    "cyclone": ("unit_type_like", "cyclone", "Cyclone boiler"),
    "tangential": ("unit_type_like", "tangentially", "Tangentially-fired"),
    "fluidized": ("unit_type_like", "fluidized", "Fluidized bed"),
    "peaker": ("unit_type_like", "turbine", "Turbine"),
    "peakers": ("unit_type_like", "turbine", "Turbine"),
    # controls
    "selective catalytic reduction": ("nox_control", "selective catalytic", "NOx control: SCR"),
    "selective non-catalytic reduction": ("nox_control", "non-catalytic", "NOx control: SNCR"),
    "electrostatic precipitator": ("pm_control", "electrostatic", "PM control: electrostatic precipitator"),
    "low nox": ("nox_control", "low nox", "NOx control: low-NOx burners"),
    "fabric filter": ("pm_control", "baghouse", "PM control: baghouse"),
    "no controls": ("no_controls", "1", "No pollution controls"),
    "uncontrolled": ("no_controls", "1", "No pollution controls"),
    "scr": ("nox_control", "selective catalytic", "NOx control: SCR"),
    "sncr": ("nox_control", "non-catalytic", "NOx control: SNCR"),
    "scrubber": ("has_so2_control", "1", "Has an SO2 scrubber"),
    "scrubbers": ("has_so2_control", "1", "Has an SO2 scrubber"),
    "scrubbed": ("has_so2_control", "1", "Has an SO2 scrubber"),
    "fgd": ("has_so2_control", "1", "Has an SO2 scrubber"),
    "baghouse": ("pm_control", "baghouse", "PM control: baghouse"),
    "esp": ("pm_control", "electrostatic", "PM control: electrostatic precipitator"),
    "precipitator": ("pm_control", "electrostatic", "PM control: electrostatic precipitator"),
    "limestone": ("so2_control", "limestone", "SO2 control: limestone"),
    # status and source category
    "retired": ("status", "retired", "Retired units"),
    "shut down": ("status", "retired", "Retired units"),
    "closed": ("status", "retired", "Retired units"),
    "operating": ("status", "operating", "Operating units"),
    "active": ("status", "operating", "Operating units"),
    "electric utility": ("source_like", "electric utility", "Electric utilities"),
    "utility": ("source_like", "electric utility", "Electric utilities"),
    "utilities": ("source_like", "electric utility", "Electric utilities"),
    "industrial": ("source_like", "industrial", "Industrial sources"),
}

# Words that ask for an order rather than a filter
HIGH_WORDS = {"biggest", "largest", "top", "most", "highest", "dirtiest", "worst", "heaviest", "major", "max", "maximum"}
LOW_WORDS = {"smallest", "lowest", "least", "cleanest", "bottom", "fewest", "min", "minimum"}

METRIC_WORDS = {
    "co2": "co2_mass", "co₂": "co2_mass", "carbon": "co2_mass", "greenhouse": "co2_mass",
    "so2": "so2_mass", "so₂": "so2_mass", "sulfur": "so2_mass", "sulphur": "so2_mass",
    "nox": "nox_mass", "nitrogen": "nox_mass",
    "generation": "gross_load", "generators": "gross_load", "output": "gross_load", "load": "gross_load", "mwh": "gross_load",
    "heat": "heat_input", "mmbtu": "heat_input",
    "hours": "operating_time",
}

METRIC_LABELS = {
    "co2_mass": ("CO2", "tons"), "so2_mass": ("SO2", "tons"), "nox_mass": ("NOx", "tons"),
    "gross_load": ("Gross load", "MWh"), "heat_input": ("Heat input", "mmBtu"),
    "operating_time": ("Operating time", "hours"), "steam_load": ("Steam load", "1000 lb"),
}

# Words that carry no meaning for the search
STOPWORDS = {
    "the", "a", "an", "of", "in", "for", "with", "and", "or", "at", "on", "by", "from", "to", "show", "me", "find",
    "list", "all", "any", "units", "unit", "plants", "plant", "facility", "facilities", "that", "which", "are", "is",
    "data", "records", "record", "year", "years", "state", "fired", "based", "fueled", "fuel", "emitters", "emitter",
    "emissions", "emission", "emitting", "polluters", "polluting", "pollution", "sources", "source", "generating", "power",
    "station", "stations", "what", "where", "who", "have", "has", "had", "using", "uses", "use", "burning", "burn",
    "burns", "than", "per", "tons", "ton", "short", "producing", "producers",
}

# "co2 over 500k", "so2 < 500", "operating time more than 5000 hours", "gross load between 100000 and 1000000"
FIELD_PATTERN = (r"(co2|co₂|carbon|so2|so₂|sulfur|nox|heat input|heat|gross load|generation|load|"
                 r"operating time|operating hours|hours|steam load|steam)")
NUMBER_PATTERN = r"([\d][\d,]*\.?\d*)\s*(k|thousand|m|million|mil)?"
COMPARE_WORDS = {
    ">": "min", ">=": "min", "over": "min", "above": "min", "more than": "min", "greater than": "min", "at least": "min",
    "<": "max", "<=": "max", "under": "max", "below": "max", "less than": "max", "at most": "max", "fewer than": "max",
}
FIELD_FOR_WORD = {
    "co2": "co2_mass", "co₂": "co2_mass", "carbon": "co2_mass", "so2": "so2_mass", "so₂": "so2_mass", "sulfur": "so2_mass",
    "nox": "nox_mass", "heat input": "heat_input", "heat": "heat_input", "gross load": "gross_load", "generation": "gross_load",
    "load": "gross_load", "operating time": "operating_time", "operating hours": "operating_time", "hours": "operating_time",
    "steam load": "steam_load", "steam": "steam_load",
}

FIRST_YEAR = 1995
LAST_YEAR = 2035


def number_value(digits, scale):
    value = float(digits.replace(",", ""))
    if scale in ("k", "thousand"):
        value *= 1_000
    elif scale in ("m", "million", "mil"):
        value *= 1_000_000
    return value


def nice_number(value):
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value / 1_000_000:,.0f} million"
    return f"{value:,.0f}" if value == int(value) else f"{value:,.1f}"


# ---------- Vocabulary from the database (for typo correction) ----------

_vocabulary = {"stamp": None}


def vocabulary():
    """
    Every word that appears in facility names, counties, fuels, unit types and controls,
    plus the counties and facility names themselves. Rebuilt when the database file changes.
    """
    try:
        stamp = os.path.getmtime(DB_PATH)
    except OSError:
        stamp = 0
    if _vocabulary["stamp"] == stamp:
        return _vocabulary

    connection = connect()
    words = set()
    texts = []
    for query in (
        "SELECT DISTINCT facility_name FROM facility",
        "SELECT DISTINCT county FROM facility",
        "SELECT DISTINCT primary_fuel FROM unit",
        "SELECT DISTINCT secondary_fuel FROM unit",
        "SELECT DISTINCT unit_type FROM unit",
        "SELECT DISTINCT so2_control_info FROM annual_records",
        "SELECT DISTINCT nox_control_info FROM annual_records",
        "SELECT DISTINCT pm_control_info FROM annual_records",
        "SELECT DISTINCT source_category FROM facility",
    ):
        for (value,) in connection.execute(query):
            if value:
                texts.append(str(value))
    counties = sorted({row[0] for row in connection.execute("SELECT DISTINCT county FROM facility") if row[0]})
    facilities = [dict(row) for row in connection.execute(
        "SELECT epa_facility_id, facility_name, state FROM facility ORDER BY facility_name")]
    connection.close()

    for text in texts:
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if len(word) >= 3:
                words.add(word)
    words.update(STATE_NAMES)
    words.update(word for phrase in PHRASES for word in phrase.split() if len(word) >= 3)

    _vocabulary.update(stamp=stamp, words=sorted(words), counties=counties, facilities=facilities)
    return _vocabulary


def correct_word(word, words):
    """The closest real word for a misspelling, or None if nothing is close enough."""
    if word in words or len(word) < 3:
        return None
    if word.endswith("s") and word[:-1] in words:
        return word[:-1]
    matches = difflib.get_close_matches(word, words, n=1, cutoff=0.78)
    return matches[0] if matches else None


# ---------- Step 1: understand the query ----------

def parse_query(query, autocorrect=True):
    """
    Turn free text into filters, a sort order and leftover search words.
    Every recognized piece is returned as an "understood" item with the exact text it came from,
    so the page can show it as a chip and remove it from the query.
    """
    original = (query or "").strip()
    text = " " + original + " "
    lowered = text.lower()
    filters = {}
    understood = []
    sort = None
    corrections = []

    def take(start, end, label, kind, key, value):
        nonlocal text, lowered
        piece = text[start:end].strip()
        understood.append({"label": label, "kind": kind, "key": key, "value": value, "text": piece})
        text = text[:start] + " " + text[end:]
        lowered = text.lower()

    # Number conditions: "co2 between 100000 and 1000000", "co2 over 500k", "so2 < 500"
    between = re.compile(FIELD_PATTERN + r"\s+(?:between|from)\s+" + NUMBER_PATTERN + r"\s+(?:and|to|-)\s+" + NUMBER_PATTERN)
    for match in list(between.finditer(lowered))[::-1]:
        field = FIELD_FOR_WORD[match.group(1)]
        low = number_value(match.group(2), match.group(3))
        high = number_value(match.group(4), match.group(5))
        low, high = min(low, high), max(low, high)
        filters[f"{field}_min"] = low
        filters[f"{field}_max"] = high
        name, units = METRIC_LABELS[field]
        take(match.start(), match.end(), f"{name} {nice_number(low)} to {nice_number(high)} {units}", "range", field, None)

    compare = re.compile(FIELD_PATTERN + r"\s*(>=|<=|>|<|over|above|more than|greater than|at least|under|below|less than|at most|fewer than)\s*" + NUMBER_PATTERN)
    for match in list(compare.finditer(lowered))[::-1]:
        field = FIELD_FOR_WORD[match.group(1)]
        side = COMPARE_WORDS[match.group(2)]
        value = number_value(match.group(3), match.group(4))
        filters[f"{field}_{side}"] = value
        name, units = METRIC_LABELS[field]
        word = "over" if side == "min" else "under"
        take(match.start(), match.end(), f"{name} {word} {nice_number(value)} {units}", "range", field, None)

    # "more than 5000 hours" (number first)
    reverse = re.compile(r"(more than|over|at least|less than|under|fewer than)\s+" + NUMBER_PATTERN + r"\s*(hours|hrs|tons of co2|tons of so2|tons of nox|mwh)")
    unit_fields = {"hours": "operating_time", "hrs": "operating_time", "tons of co2": "co2_mass",
                   "tons of so2": "so2_mass", "tons of nox": "nox_mass", "mwh": "gross_load"}
    for match in list(reverse.finditer(lowered))[::-1]:
        field = unit_fields[match.group(4)]
        side = COMPARE_WORDS[match.group(1)]
        value = number_value(match.group(2), match.group(3))
        filters[f"{field}_{side}"] = value
        name, units = METRIC_LABELS[field]
        word = "over" if side == "min" else "under"
        take(match.start(), match.end(), f"{name} {word} {nice_number(value)} {units}", "range", field, None)

    # Year ranges: "2015-2025", "2015 to 2025", "since 2020", "before 2020"
    year_range = re.compile(r"\b((?:19|20)\d{2})\s*(?:-|–|to|through|thru)\s*((?:19|20)\d{2})\b")
    for match in list(year_range.finditer(lowered))[::-1]:
        first, last = sorted((int(match.group(1)), int(match.group(2))))
        filters["year_from"] = first
        filters["year_to"] = last
        take(match.start(), match.end(), f"Years {first}–{last}", "years", None, None)

    for word, key, offset, label in (("since", "year_from", 0, "Since {}"), ("after", "year_from", 1, "After {}"),
                                     ("before", "year_to", -1, "Before {}")):
        for match in list(re.finditer(rf"\b{word}\s+((?:19|20)\d{{2}})\b", lowered))[::-1]:
            year = int(match.group(1))
            filters[key] = year + offset
            take(match.start(), match.end(), label.format(year), "years", None, None)

    # Single years
    years = []
    for match in list(re.finditer(r"\b((?:19|20)\d{2})\b", lowered))[::-1]:
        year = int(match.group(1))
        if FIRST_YEAR <= year <= LAST_YEAR:
            years.append(year)
            take(match.start(), match.end(), str(year), "year", None, year)
    if len(years) == 1:
        filters["reporting_year"] = years[0]
    elif years:
        filters["year_from"] = min(years)
        filters["year_to"] = max(years)

    # "unit 4", "unit CT1"
    for match in list(re.finditer(r"\bunit\s+([a-z]*\d[a-z0-9]*)\b", lowered))[::-1]:
        unit_id = text[match.start(1):match.end(1)].upper()
        filters["epa_unit_id"] = unit_id
        take(match.start(), match.end(), f"Unit {unit_id}", "unit", None, unit_id)

    # Counties: "jefferson county", "fort bend county"
    vocab = vocabulary()
    for match in list(re.finditer(r"\b([a-z.]+(?:\s[a-z.]+)?)\s+county\b", lowered))[::-1]:
        candidate = match.group(1)
        # Prefer the two-word name ("fort bend"), fall back to one word ("bend" -> no; "jefferson")
        options = [candidate, candidate.split()[-1]]
        for option in options:
            name = f"{option} county"
            found = [county for county in vocab["counties"] if county.lower() == name]
            if found:
                start = match.start() if option == candidate else match.end() - len(name)
                filters["county_like"] = found[0]
                take(start, match.end(), found[0], "county", None, found[0])
                break

    # States: full names first ("west virginia" before "virginia")
    for name in sorted(STATE_NAMES, key=len, reverse=True):
        match = re.search(rf"\b{re.escape(name)}\b", lowered)
        if match:
            code = STATE_NAMES[name]
            filters["state"] = code
            take(match.start(), match.end(), CODE_TO_STATE[code], "state", None, code)
            break

    if "state" not in filters:
        for match in re.finditer(r"\b([A-Za-z]{2})\b", text):
            token = match.group(1)
            code = token.upper()
            if code not in STATE_CODES:
                continue
            if token.lower() in AMBIGUOUS_CODES and token != code:
                continue
            filters["state"] = code
            take(match.start(), match.end(), CODE_TO_STATE[code], "state", None, code)
            break

    # Fuels, unit types, controls, status (longest phrases first)
    for phrase in sorted(PHRASES, key=len, reverse=True):
        match = re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", lowered)
        if not match:
            continue
        key, value, label = PHRASES[phrase]
        if key in filters:
            continue
        filters[key] = value
        take(match.start(), match.end(), label, "phrase", key, value)

    # Sorting words: "biggest so2", "cleanest", "top generation"
    tokens = re.findall(r"[\w₂.'-]+", lowered)
    direction = None
    metric = None
    for token in tokens:
        if token in HIGH_WORDS:
            direction = "desc"
        elif token in LOW_WORDS:
            direction = "asc"
        if token in METRIC_WORDS:
            metric = METRIC_WORDS[token]
    if direction:
        metric = metric or "co2_mass"
        sort = (metric, direction)
        name = METRIC_LABELS[metric][0]
        label = f"Sorted by {name}, {'highest' if direction == 'desc' else 'lowest'} first"
        understood.append({"label": label, "kind": "sort", "key": None, "value": None, "text": ""})
    words_to_drop = HIGH_WORDS | LOW_WORDS | set(METRIC_WORDS) | {"time", "input", "gross"}

    # "top 10", "bottom 5": the number is a count, not a facility ID
    for match in list(re.finditer(r"\b(top|bottom|first|largest|biggest|smallest)\s+(\d+)\b", lowered))[::-1]:
        text = text[:match.start(2)] + " " + text[match.end(2):]
        lowered = text.lower()

    # A bare facility ID: "1364"
    for match in list(re.finditer(r"\b(\d{1,6})\b", lowered))[::-1]:
        number = int(match.group(1))
        if any(row["epa_facility_id"] == number for row in vocab["facilities"]):
            filters["epa_facility_id"] = number
            name = next(row["facility_name"] for row in vocab["facilities"] if row["epa_facility_id"] == number)
            take(match.start(), match.end(), f"Facility {number} ({name})", "facility", None, number)
            break

    # Whatever is left becomes search words
    terms = []
    for token in re.findall(r"[\w'.&-]+", lowered):
        token = token.strip(".'-")
        if not token or token in STOPWORDS or token in words_to_drop:
            continue
        if autocorrect:
            fixed = correct_word(token, vocab["words"])
            if fixed:
                corrections.append((token, fixed))
                token = fixed
        terms.append(token)

    return {
        "query": original,
        "filters": filters,
        "terms": terms,
        "sort": sort,
        "understood": understood,
        "corrections": corrections,
    }


def query_without(query, piece):
    """The query with one understood piece removed, for the chip's remove link."""
    if not piece:
        return query
    result = re.sub(re.escape(piece), " ", query, count=1, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip()


# ---------- Step 2: build the SQL ----------

TEXT_COLUMNS = {
    # column, how much a match counts toward relevance
    "facility.facility_name": 30,
    "facility.county": 10,
    "facility.state": 6,
    "unit.epa_unit_id": 6,
    "unit.unit_type": 5,
    "unit.primary_fuel": 5,
    "unit.secondary_fuel": 2,
    "annual_records.so2_control_info": 3,
    "annual_records.nox_control_info": 3,
    "annual_records.pm_control_info": 3,
    "facility.source_category": 2,
}

SEARCHABLE_TEXT = " || ' ' || ".join(f"LOWER(COALESCE({column}, ''))" for column in TEXT_COLUMNS)


def score_expression(terms):
    """
    Relevance for each record: name starts with the word > word anywhere in the name
    > county > state, unit, fuel and type > controls. Also counts how many words matched.
    """
    score_parts = []
    matched_parts = []
    parameters = []
    for term in terms:
        cases = [
            "WHEN LOWER(facility.facility_name) LIKE ? THEN 40",
            "WHEN LOWER(facility.facility_name) LIKE ? THEN 34",
        ]
        parameters.extend([f"{term}%", f"% {term}%"])
        for column, weight in TEXT_COLUMNS.items():
            cases.append(f"WHEN LOWER(COALESCE({column}, '')) LIKE ? THEN {weight}")
            parameters.append(f"%{term}%")
        score_parts.append("(CASE " + " ".join(cases) + " ELSE 0 END)")
    for term in terms:
        matched_parts.append(f"(CASE WHEN ({SEARCHABLE_TEXT}) LIKE ? THEN 1 ELSE 0 END)")
        parameters.append(f"%{term}%")
    return " + ".join(score_parts), " + ".join(matched_parts), parameters


def find_text_matches(connection, terms):
    """
    Score every record against the search words once, into a temporary table.
    Every later query (count, page, sidebar counts) reuses it instead of re-scanning the text.
    """
    connection.execute("DROP TABLE IF EXISTS text_hits")
    if not terms:
        return
    score_sql, matched_sql, values = score_expression(terms)
    connection.execute(
        f"CREATE TEMP TABLE text_hits AS SELECT annual_records.annual_record_id AS id,"
        f" {score_sql} AS score, {matched_sql} AS matched {BASE_JOIN}",
        values,
    )
    connection.execute("DELETE FROM text_hits WHERE matched = 0")
    connection.execute("CREATE INDEX text_hits_id ON text_hits (id)")


# Sort choices for the dropdown and column headers: value -> (label, SQL, direction)
SORT_OPTIONS = {
    "relevance": ("Best match", None, None),
    "newest": ("Newest year", "annual_records.year", "DESC"),
    "co2-desc": ("CO2: highest first", "annual_records.co2_mass", "DESC"),
    "co2-asc": ("CO2: lowest first", "annual_records.co2_mass", "ASC"),
    "so2-desc": ("SO2: highest first", "annual_records.so2_mass", "DESC"),
    "so2-asc": ("SO2: lowest first", "annual_records.so2_mass", "ASC"),
    "nox-desc": ("NOx: highest first", "annual_records.nox_mass", "DESC"),
    "nox-asc": ("NOx: lowest first", "annual_records.nox_mass", "ASC"),
    "load-desc": ("Gross load: highest first", "annual_records.gross_load", "DESC"),
    "heat-desc": ("Heat input: highest first", "annual_records.heat_input", "DESC"),
    "hours-desc": ("Operating time: longest first", "annual_records.operating_time", "DESC"),
    "name-asc": ("Facility name: A to Z", "facility.facility_name", "ASC"),
    "name-desc": ("Facility name: Z to A", "facility.facility_name", "DESC"),
    "state-asc": ("State: A to Z", "facility.state", "ASC"),
    "year-asc": ("Oldest year", "annual_records.year", "ASC"),
    "unit-asc": ("Unit ID", "unit.epa_unit_id", "ASC"),
    "type-asc": ("Unit type", "unit.unit_type", "ASC"),
    "fuel-asc": ("Primary fuel", "unit.primary_fuel", "ASC"),
}

METRIC_SORTS = {
    ("co2_mass", "desc"): "co2-desc", ("co2_mass", "asc"): "co2-asc",
    ("so2_mass", "desc"): "so2-desc", ("so2_mass", "asc"): "so2-asc",
    ("nox_mass", "desc"): "nox-desc", ("nox_mass", "asc"): "nox-asc",
    ("gross_load", "desc"): "load-desc", ("gross_load", "asc"): "load-desc",
    ("heat_input", "desc"): "heat-desc", ("heat_input", "asc"): "heat-desc",
    ("operating_time", "desc"): "hours-desc", ("operating_time", "asc"): "hours-desc",
}

# Refinement filters a person can set from the sidebar (they override what the text said)
REFINEMENTS = ["state", "reporting_year", "primary_fuel", "unit_type", "county", "source_category", "status",
               "year_from", "year_to", "epa_facility_id", "epa_unit_id"]
RANGE_FIELDS = ["co2_mass", "so2_mass", "nox_mass", "gross_load", "heat_input", "operating_time"]

DEFAULT_ORDER = "annual_records.year DESC, annual_records.co2_mass IS NULL, annual_records.co2_mass DESC, facility.facility_name"


def combined_filters(params, parsed):
    """Filters from the text, then the sidebar's choices on top (the sidebar wins)."""
    filters = dict(parsed["filters"])
    for key in REFINEMENTS:
        if params.get(key):
            filters[key] = params[key]
            # A sidebar choice replaces the matching kind of choice from the text
            if key == "primary_fuel":
                filters.pop("fuel_like", None)
            if key == "unit_type":
                filters.pop("unit_type_like", None)
            if key == "county":
                filters.pop("county_like", None)
            if key == "reporting_year":
                filters.pop("year_from", None)
                filters.pop("year_to", None)
            if key == "source_category":
                filters.pop("source_like", None)
    for field in RANGE_FIELDS:
        for side in ("min", "max"):
            value = to_number(params.get(f"{field}_{side}"))
            if value is not None:
                filters[f"{field}_{side}"] = value
    return filters


def where_for(filters, terms, match_all=True, exclude=()):
    where, parameters = build_where(filters, exclude=exclude)
    if terms:
        # Every word, or (when nothing matches every word) at least one of them
        needed = len(terms) if match_all else 1
        where += " AND annual_records.annual_record_id IN (SELECT id FROM text_hits WHERE matched >= ?)"
        parameters = parameters + [needed]
    return where, parameters


# ---------- Step 3: run it ----------

FACETS = {
    # key: (label, SQL expression, how many to show before "more")
    "reporting_year": ("Year", "annual_records.year", 6),
    "state": ("State", "facility.state", 12),
    "primary_fuel": ("Fuel", "unit.primary_fuel", 12),
    "unit_type": ("Unit type", "unit.unit_type", 12),
    "county": ("County", "facility.county", 10),
    "source_category": ("Source category", "facility.source_category", 8),
    "status": ("Status", "CASE WHEN unit.retirement_date IS NOT NULL AND unit.retirement_date != '' THEN 'retired' ELSE 'operating' END", 2),
}

FACET_EXCLUDES = {
    "reporting_year": {"reporting_year", "year_from", "year_to"},
    "state": {"state"},
    "primary_fuel": {"primary_fuel", "fuel_like"},
    "unit_type": {"unit_type", "unit_type_like"},
    "county": {"county", "county_like"},
    "source_category": {"source_category", "source_like"},
    "status": {"status"},
}

PER_PAGE_CHOICES = [25, 50, 100]
DEFAULT_PER_PAGE = 50


def explore(params, page=None, per_page=None, everything=False):
    """
    Run a search. Returns the rows for one page (or every row with everything=True),
    the total count, the sidebar refinements with counts, and how the query was understood.
    """
    autocorrect = params.get("exact") != "1"
    parsed = parse_query(params.get("q", ""), autocorrect=autocorrect)
    filters = combined_filters(params, parsed)
    terms = parsed["terms"]

    connection = connect()
    find_text_matches(connection, terms)

    def count_for(match_all):
        where, values = where_for(filters, terms, match_all)
        return connection.execute(f"SELECT COUNT(*) {BASE_JOIN} {where}", values).fetchone()[0]

    match_all = True
    total = count_for(True)
    partial = False
    if total == 0 and len(terms) > 1:
        total = count_for(False)
        match_all = False
        partial = total > 0

    # Did-you-mean for a facility name when nothing matched
    suggestion = None
    if total == 0 and parsed["query"]:
        names = {row["facility_name"].lower(): row["facility_name"] for row in vocabulary()["facilities"]}
        close = difflib.get_close_matches(" ".join(terms) or parsed["query"].lower(), list(names), n=1, cutoff=0.6)
        if close:
            suggestion = names[close[0]]

    # Order: a chosen sort, then a sort the words asked for, then relevance
    order_key = params.get("order")
    if order_key not in SORT_OPTIONS:
        order_key = METRIC_SORTS.get(parsed["sort"]) if parsed["sort"] else "relevance"
    _, column, direction = SORT_OPTIONS[order_key]
    if column:
        order_sql = f"{column} IS NULL, {column} {direction}, {DEFAULT_ORDER}"
    elif terms:
        order_sql = f"text_hits.matched DESC, text_hits.score DESC, {DEFAULT_ORDER}"
    else:
        order_sql = DEFAULT_ORDER

    per_page = to_positive_int(per_page or params.get("per_page"), DEFAULT_PER_PAGE)
    if per_page not in PER_PAGE_CHOICES:
        per_page = DEFAULT_PER_PAGE
    pages = max(1, -(-total // per_page))
    page = min(to_positive_int(page or params.get("page"), 1), pages)

    where, values = where_for(filters, terms, match_all)
    join = " LEFT JOIN text_hits ON text_hits.id = annual_records.annual_record_id" if terms else ""
    query = f"SELECT {RESULT_COLUMNS} {BASE_JOIN}{join} {where} ORDER BY {order_sql}"
    if not everything:
        query += " LIMIT ? OFFSET ?"
        values = values + [per_page, (page - 1) * per_page]
    rows = [dict(row) for row in connection.execute(query, values).fetchall()]

    facets = {}
    ranges = {}
    if not everything:
        for key, (label, expression, show) in FACETS.items():
            where, values = where_for(filters, terms, match_all, exclude=FACET_EXCLUDES[key])
            found = connection.execute(
                f"SELECT {expression} AS value, COUNT(*) AS n {BASE_JOIN} {where}"
                f" AND {expression} IS NOT NULL AND {expression} != '' GROUP BY value",
                values,
            ).fetchall()
            items = [{"value": row["value"], "count": row["n"]} for row in found]
            if key == "reporting_year":
                items.sort(key=lambda item: item["value"], reverse=True)
            else:
                items.sort(key=lambda item: (-item["count"], str(item["value"])))
            facets[key] = {"label": label, "items": items, "show": show}

        for field in RANGE_FIELDS:
            column = f"annual_records.{field}"
            exclude = {f"{field}_min", f"{field}_max"}
            plain = {key: value for key, value in filters.items() if key not in exclude}
            where, values = where_for(plain, terms, match_all)
            low, high = connection.execute(f"SELECT MIN({column}), MAX({column}) {BASE_JOIN} {where}", values).fetchone()
            ranges[field] = (low, high)

    connection.close()

    return {
        "parsed": parsed,
        "filters": filters,
        "rows": rows,
        "total": total,
        "partial": partial,
        "suggestion": suggestion,
        "order": order_key,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "facets": facets,
        "ranges": ranges,
    }


# ---------- Suggestions while typing ----------

def suggest(text, limit=6):
    """Facilities and ready-made searches that start like what's being typed."""
    text = (text or "").strip().lower()
    if not text:
        return {"facilities": [], "searches": []}
    vocab = vocabulary()

    facilities = [row for row in vocab["facilities"] if text in row["facility_name"].lower()]
    facilities.sort(key=lambda row: (not row["facility_name"].lower().startswith(text), row["facility_name"]))
    if not facilities:
        names = {row["facility_name"].lower(): row for row in vocab["facilities"]}
        for name in difflib.get_close_matches(text, list(names), n=4, cutoff=0.55):
            facilities.append(names[name])

    searches = []
    last = text.split()[-1] if text.split() else ""
    before = text[: len(text) - len(last)].strip()
    candidates = list(STATE_NAMES) + [county.lower() for county in vocab["counties"]] + \
        ["coal", "natural gas", "combined cycle", "combustion turbine", "scrubber", "retired", "biggest co2 emitters",
         "cleanest", "selective catalytic reduction", "baghouse", "wood", "diesel oil"]
    for candidate in candidates:
        if candidate.startswith(last) and candidate != last:
            searches.append(f"{before} {candidate}".strip())
        if len(searches) >= limit:
            break

    return {
        "facilities": [{"id": row["epa_facility_id"], "name": row["facility_name"], "state": row["state"]}
                       for row in facilities[:limit]],
        "searches": searches[:limit],
    }