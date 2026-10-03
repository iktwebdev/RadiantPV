# BOM Weather Model Import Tool — V1 Specification

## 1. Purpose

Implement a standalone command-line utility that converts Australian Bureau of Meteorology historical daily weather exports into a calibrated JSON weather-model definition suitable for use by the PV Simulator.

The utility is separate from the simulation engine.

Its responsibility is:

```text
BOM historical observations
        ↓
Parse and validate
        ↓
Normalise by date
        ↓
Apply requested training period
        ↓
Calculate monthly statistics
        ↓
Calculate monthly cross-variable correlations
        ↓
Validate resulting model
        ↓
Write JSON weather model
```

Example output:

```text
weather_model_066006_066037.json
```

The simulator shall consume the generated JSON model and shall not need to know anything about BOM file formats.

---

# 2. V1 Input Data

V1 requires three BOM historical daily-weather export directories:

1. Daily Global Solar Exposure
2. Daily Maximum Temperature
3. Daily Minimum Temperature

Each input argument identifies the **BOM export directory**, not an individual CSV file.

Example:

```text id="wd5z0q"
inputs/
├── IDCJAC0016_066006_1800/
│   ├── IDCJAC0016_066006_1800_Note.txt
│   └── IDCJAC0016_066006_1800_Data.csv
│
├── IDCJAC0010_066037_1800/
│   ├── IDCJAC0010_066037_1800_Note.txt
│   └── IDCJAC0010_066037_1800_Data.csv
│
└── IDCJAC0011_066037_1800/
    ├── IDCJAC0011_066037_1800_Note.txt
    └── IDCJAC0011_066037_1800_Data.csv
```

For the initial Sydney model:

```text id="g0h7ql"
Solar exposure:
    BOM product: IDCJAC0016
    Station: 066006
    Sydney Botanic Gardens

Maximum temperature:
    BOM product: IDCJAC0010
    Station: 066037
    Sydney Airport AMO

Minimum temperature:
    BOM product: IDCJAC0011
    Station: 066037
    Sydney Airport AMO
```

Station and location metadata shall be obtained from the BOM `_Note.txt` files rather than supplied independently by the user wherever that metadata is present.

The importer must not hard-code station IDs, station names or locations.

---

# 3. Command-Line Interface

The program shall be a command-line utility.

Suggested executable name:

```text id="qcf6wv"
bom-weather-import
```

Example:

```text id="o0dy0c"
bom-weather-import \
    --solar inputs/IDCJAC0016_066006_1800 \
    --tmax inputs/IDCJAC0010_066037_1800 \
    --tmin inputs/IDCJAC0011_066037_1800 \
    --start-date 2016-01-01 \
    --end-date 2025-12-31 \
    --model-name SydneyWeatherRecent \
    --output weather_model_066006_066037.json
```

The arguments:

```text id="1e9z9c"
--solar
--tmax
--tmin
```

must refer to directories containing complete BOM export datasets.

The importer shall discover the appropriate `_Note.txt` and `_Data.csv` files inside each directory.

---

# 4. BOM Dataset Directory

Represent each BOM input as a dataset rather than simply as a CSV file.

Conceptually:

```cpp id="9ad1bs"
class BomDataset
{
public:
    std::filesystem::path Directory;
    std::filesystem::path NoteFile;
    std::filesystem::path DataFile;

    BomStationMetadata Station;
    BomProductMetadata Product;
    WeatherSeries Observations;
};
```

The importer shall:

1. Verify that the supplied path exists.
2. Verify that it is a directory.
3. Locate exactly one appropriate `_Note.txt`.
4. Locate exactly one appropriate `_Data.csv`.
5. Validate that the two files belong to the same BOM dataset.
6. Parse metadata from the Note file.
7. Parse observations from the Data file.

Ambiguous directories containing multiple candidate Note or Data files shall cause an error rather than an arbitrary file being selected.

---

# 5. Dataset File Discovery

For a directory such as:

```text id="08x4aj"
IDCJAC0016_066006_1800
```

the expected files are:

```text id="4bws64"
IDCJAC0016_066006_1800_Note.txt
IDCJAC0016_066006_1800_Data.csv
```

The preferred discovery mechanism is:

```text id="v5e5eg"
<directory-name>_Note.txt
<directory-name>_Data.csv
```

If exact-name discovery fails, the importer may search for:

```text id="0utsk8"
*_Note.txt
*_Data.csv
```

provided exactly one unambiguous pair exists.

The resolved files must be reported in verbose output.

---

# 6. BOM Note File Parser

Implement a dedicated parser for the BOM descriptive Note file.

The Note file is authoritative metadata for the dataset.

For example, it may contain:

```text id="5oexkh"
** Station Details **

Bureau of Meteorology station number: 66037
Station name: SYDNEY AIRPORT AMO
```

The parser shall extract all useful structured metadata available in the Note file.

At minimum:

```text id="b48b2f"
station number
station name
```

Where present, also extract:

```text id="h3qqw1"
latitude
longitude
station elevation/height
state
station opening date
station closing date
product description
measurement description
units
missing-value description
quality-flag description
```

Do not invent fields that are absent from the Note file.

---

# 7. Station Number Normalisation

BOM station identifiers must be represented consistently.

For example, the Note file may contain:

```text id="h72v77"
66037
```

while the dataset filename contains:

```text id="5nldqy"
066037
```

The importer shall normalise numeric BOM station numbers to the canonical six-digit representation:

```text id="bq5jfw"
66037 -> "066037"
```

Station IDs shall be stored as strings, not integers.

This preserves leading zeroes.

---

# 8. Dataset Identity

The importer shall derive and validate dataset identity from both:

```text id="oy5r54"
directory/file names
Note-file metadata
```

For:

```text id="cj7j4w"
IDCJAC0016_066006_1800
```

derive:

```text id="a65flv"
product_id = IDCJAC0016
station_id = 066006
dataset suffix/version = 1800
```

Then compare the station identifier with the station number parsed from the Note file.

If they disagree, fail with an error such as:

```text id="2i1w23"
Dataset station mismatch.

Directory:
    IDCJAC0016_066006_1800

Station encoded in dataset name:
    066006

Station specified by Note file:
    066037
```

Do not silently continue.

---

# 9. Product Validation

Each command-line argument has an expected BOM product.

For V1:

```text id="1d1m4p"
--solar -> IDCJAC0016
--tmax  -> IDCJAC0010
--tmin  -> IDCJAC0011
```

Validate the product identifier derived from the dataset directory/file names.

For example:

```text id="bf7h28"
--solar inputs/IDCJAC0010_066037_1800
```

shall fail because a maximum-temperature dataset was supplied as solar exposure.

This prevents accidentally producing a plausible-looking but semantically invalid weather model.

---

# 10. BOM Dataset Parser Architecture

Parsing should therefore have two levels:

```text id="8bjhdc"
BomDatasetReader
        |
        +-- BomNoteParser
        |
        +-- BomDataParser
```

Conceptually:

```cpp id="yzp4aj"
class BomDatasetReader
{
public:
    BomDataset Read(
        const std::filesystem::path& directory,
        BomProductType expectedProduct);
};
```

`BomDatasetReader` is responsible for:

```text id="v0nqux"
directory discovery
file pairing
dataset identity
metadata/data consistency validation
```

while:

```text id="q3mqza"
BomNoteParser
```

understands the descriptive text format and:

```text id="kkik85"
BomDataParser
```

understands the CSV format.

The statistical calibration layer must not know anything about BOM filenames or Note-file syntax.# 2. V1 Input Data

V1 requires three daily BOM datasets:

1. Daily Global Solar Exposure
2. Daily Maximum Temperature
3. Daily Minimum Temperature

For the initial Sydney model:

```text
Solar exposure:
    BOM product: IDCJAC0016
    Station: 066006
    Sydney Botanic Gardens

Maximum temperature:
    BOM product: IDCJAC0010
    Station: 066037
    Sydney Airport AMO

Minimum temperature:
    BOM product: IDCJAC0011
    Station: 066037
    Sydney Airport AMO
```

The tool must not hard-code these station IDs.

Station IDs and metadata must be obtained from the supplied files where possible and/or explicitly provided through configuration/command-line parameters.

---

# 11. Station Metadata

Use a common station metadata structure.

For example:

```cpp id="hlavcv"
struct BomStationMetadata
{
    std::string StationId;
    std::string StationName;

    std::optional<double> Latitude;
    std::optional<double> Longitude;
    std::optional<double> ElevationMetres;

    std::optional<Date> Opened;
    std::optional<Date> Closed;
};
```

The exact fields should be based on what BOM actually supplies in the Note files.

Unknown fields should remain absent rather than being assigned artificial defaults.

---

# 12. Multiple Stations in One Weather Model# 2. V1 Input Data

V1 requires three daily BOM datasets:

1. Daily Global Solar Exposure
2. Daily Maximum Temperature
3. Daily Minimum Temperature

For the initial Sydney model:

```text
Solar exposure:
    BOM product: IDCJAC0016
    Station: 066006
    Sydney Botanic Gardens

Maximum temperature:
    BOM product: IDCJAC0010
    Station: 066037
    Sydney Airport AMO

Minimum temperature:
    BOM product: IDCJAC0011
    Station: 066037
    Sydney Airport AMO
```

The tool must not hard-code these station IDs.

Station IDs and metadata must be obtained from the supplied files where possible and/or explicitly provided through configuration/command-line parameters.

The importer must not assume all weather variables originate from the same physical station.

The initial Sydney model deliberately uses:

```text id="02b01g"
Solar:
    066006
    Sydney Botanic Gardens

Temperature:
    066037
    Sydney Airport AMO
```

Therefore the generated model must preserve provenance separately for each dataset.

Do not define one misleading global:

```json id="u3lq2i"
"station": "..."
```

for the complete weather model.

Instead preserve each source independently.

---

# 13. Cross-Validation of Temperature Datasets

For the normal V1 use case, Tmax and Tmin are expected to come from the same station.

After loading:

```text id="e9e6xa"
--tmax
--tmin
```

compare their station IDs.

If they differ, issue a clear warning or fail validation.

For V1, prefer failure unless there is an explicit future option allowing mixed temperature stations.

For example:

```text id="p4nmce"
Temperature station mismatch:

Tmax:
    066037 SYDNEY AIRPORT AMO

Tmin:
    066214 SYDNEY (OBSERVATORY HILL)

V1 requires Tmax and Tmin from the same station.
```

Solar and temperature stations are explicitly permitted to differ.

---

# 14. Generated Model Provenance

The generated JSON shall preserve the metadata extracted from each BOM Note file.

For example:

```json id="4m07yq"
"source": {
    "provider": "Bureau of Meteorology",

    "solar_exposure": {
        "product": "IDCJAC0016",
        "station": {
            "id": "066006",
            "name": "SYDNEY BOTANIC GARDENS",
            "latitude": -33.87,
            "longitude": 151.22,
            "elevation_metres": 15.0
        }
    },

    "temperature_maximum": {
        "product": "IDCJAC0010",
        "station": {
            "id": "066037",
            "name": "SYDNEY AIRPORT AMO",
            "latitude": -33.95,
            "longitude": 151.17,
            "elevation_metres": 6.0
        }
    },

    "temperature_minimum": {
        "product": "IDCJAC0011",
        "station": {
            "id": "066037",
            "name": "SYDNEY AIRPORT AMO",
            "latitude": -33.95,
            "longitude": 151.17,
            "elevation_metres": 6.0
        }
    }
}
```

The numbers above illustrate the schema.

Actual metadata must come from the supplied BOM Note files.

---

# 15. Model Location

Because a weather model may combine observations from multiple nearby stations, do not automatically claim that one station's coordinates are the exact geographical location of the resulting weather model.

For V1, model-level location may be supplied independently:

```text id="4ts7kq"
--location-name Sydney
```

while the exact coordinates of each observation source remain recorded under its source metadata.

If no model-level location is supplied, a descriptive location may be derived from the source metadata, but source-station coordinates must not be silently represented as a distinct site's coordinates.

This becomes important later when a PV installation has its own latitude/longitude.

---

# 16. Revised Processing Sequence

The complete import process becomes:

```text id="q6wtmq"
Parse command line
        ↓
Read --solar directory
        ↓
Discover Note + Data files
        ↓
Parse solar Note metadata
        ↓
Parse solar observations
        ↓
Validate solar dataset identity
        ↓
Read --tmax directory
        ↓
Discover Note + Data files
        ↓
Parse Tmax Note metadata
        ↓
Parse Tmax observations
        ↓
Validate Tmax dataset identity
        ↓
Read --tmin directory
        ↓
Discover Note + Data files
        ↓
Parse Tmin Note metadata
        ↓
Parse Tmin observations
        ↓
Validate Tmin dataset identity
        ↓
Validate Tmax/Tmin station consistency
        ↓
Construct common date-indexed dataset
        ↓
Apply training period
        ↓
Calculate monthly univariate statistics
        ↓
Construct monthly complete-case datasets
        ↓
Calculate monthly correlation matrices
        ↓
Validate matrices
        ↓
Validate Cholesky decomposition
        ↓
Build WeatherModelDefinition
        ↓
Attach complete BOM provenance
        ↓
Write JSON
```

---

# 17. Example Invocation

The expected normal workflow is therefore:

```text id="pp9m6a"
bom-weather-import \
    --solar inputs/IDCJAC0016_066006_1800 \
    --tmax inputs/IDCJAC0010_066037_1800 \
    --tmin inputs/IDCJAC0011_066037_1800 \
    --start-date 2016-01-01 \
    --end-date 2025-12-31 \
    --model-name SydneyWeatherRecent \
    --location-name Sydney \
    --output weather_model_066006_066037.json
```

The user does not need to separately specify:

```text id="lh66k4"
solar station number
temperature station number
station names
station coordinates
BOM product IDs
units
```

when those values can be reliably determined from the BOM dataset itself.

The principle is:

> If BOM supplied the metadata with the dataset, derive it from the dataset rather than asking the user to enter it again.

This reduces configuration duplication and prevents metadata from disagreeing with the actual observations being calibrated.

---

# 3. Command-Line Interface

The program shall be a command-line utility.

Suggested executable name:

```text
bom-weather-import
```

Example:

```text
bom-weather-import \
    --solar IDCJAC0016_066006.csv \
    --tmax IDCJAC0010_066037.csv \
    --tmin IDCJAC0011_066037.csv \
    --start-date 2016-01-01 \
    --end-date 2025-12-31 \
    --output weather_model_066006_066037.json
```

Also support the longer calibration period:

```text
bom-weather-import \
    --solar IDCJAC0016_066006.csv \
    --tmax IDCJAC0010_066037.csv \
    --tmin IDCJAC0011_066037.csv \
    --start-date 1990-01-01 \
    --end-date 2025-12-31 \
    --output weather_model_066006_066037_1990_2025.json
```

The exact command-line library is left to implementation.

---

# 4. Required Command-Line Arguments

Required:

```text
--solar
--tmax
--tmin
--start-date
--end-date
--output
```

Optional useful arguments:

```text
--model-name
--location-name
--pretty
--overwrite
--verbose
```

Example:

```text
--model-name SydneyWeatherRecent
--location-name Sydney
```

If `--model-name` is omitted, generate a deterministic name from the stations and training period.

Do not overwrite an existing output file unless `--overwrite` is specified.

---

# 5. BOM Input Formats

The importer must have separate parsers for each BOM product rather than embedding CSV-column assumptions throughout the application.

Conceptually:

```text
BOM parser
    |
    +-- DailySolarExposureParser
    |
    +-- DailyMaximumTemperatureParser
    |
    +-- DailyMinimumTemperatureParser
```

Each parser converts the BOM-specific record into a common internal observation representation.

For example:

```cpp
struct WeatherObservation
{
    Date date;
    std::optional<double> value;
    std::optional<std::string> quality;
};
```

The rest of the importer must operate on this normalised representation.

---

# 6. BOM Solar Data

Daily Global Solar Exposure corresponds to BOM product:

```text
IDCJAC0016
```

The relevant daily value is:

```text
Daily global solar exposure
```

Units:

```text
MJ/m²/day
```

The importer shall preserve missing observations as missing.

A missing observation must never be interpreted as:

```text
0 MJ/m²/day
```

because zero and missing have completely different meanings.

Solar data may not contain the same quality field semantics as temperature data.

Do not invent quality information that is absent from the source file.

---

# 7. BOM Temperature Data

Daily Maximum Temperature:

```text
IDCJAC0010
```

Daily Minimum Temperature:

```text
IDCJAC0011
```

Units:

```text
degrees Celsius
```

Temperature exports may include BOM quality flags.

Preserve the supplied quality flag in the internal parsed observation.

For V1, valid numeric observations shall not automatically be discarded merely because quality control is incomplete unless an explicit filtering rule is configured.

The importer should report counts by quality flag.

---

# 8. Common Internal Daily Dataset

After parsing the three files, construct a date-indexed dataset:

```text
Date
SolarExposure
TemperatureMinimum
TemperatureMaximum
SolarAvailable
TminAvailable
TmaxAvailable
TemperatureQualityFlags
```

Conceptually:

```text
2016-01-01    27.4    18.2    28.6
2016-01-02    22.1    19.1    30.3
2016-01-03    NULL    17.8    27.4
...
```

Do not perform statistical calculations directly against the raw BOM CSV rows.

First construct this normalised date-indexed dataset.

---

# 9. Date Handling

Construct dates from the BOM:

```text
Year
Month
Day
```

fields.

Validate every date.

Reject malformed calendar dates.

The internal date representation shall not depend on locale.

Use ISO-8601 formatting when writing dates:

```text
YYYY-MM-DD
```

---

# 10. Duplicate Observations

There must be no more than one observation for:

```text
station
variable
date
```

If duplicate observations occur, do not arbitrarily choose one.

Report the duplicate and fail the import unless an explicit duplicate-handling policy is later implemented.

---

# 11. Training Period

Statistics shall only use observations within:

```text
start_date <= observation_date <= end_date
```

The requested training period shall be stored in the generated model.

Example:

```json
"training_period": {
    "start": "2016-01-01",
    "end": "2025-12-31"
}
```

The tool must report the actual available observation range for each input file.

If the requested period extends outside the available range, fail with a clear error rather than silently shortening the requested period.

---

# 12. Missing Data

Missing observations must remain missing throughout parsing and joining.

Do not:

```text
replace missing with zero
forward-fill
back-fill
interpolate
replace with monthly mean
```

for V1.

Monthly univariate statistics shall use all valid observations available for the corresponding variable.

Monthly correlation calculations shall use only dates where all variables participating in that correlation matrix are simultaneously available.

This distinction is important.

For example:

```text
January solar mean/std-dev
```

uses every valid January solar observation.

But:

```text
January solar/Tmin/Tmax correlation matrix
```

uses only January dates having valid:

```text
solar
Tmin
Tmax
```

simultaneously.

---

# 13. Monthly Grouping

Group observations by calendar month:

```text
January
February
...
December
```

All years in the selected training period contribute to the corresponding month.

For example, a 2016–2025 January model uses observations from:

```text
January 2016
January 2017
...
January 2025
```

Do not calculate separate statistics for each year in V1.

---

# 14. Monthly Univariate Statistics

For each variable and calendar month calculate at minimum:

```text
count
mean
standard deviation
minimum
maximum
missing count
```

The stochastic model requires:

```text
mean
standard deviation
```

The remaining statistics are useful calibration diagnostics and should either be included in the JSON or available in the import report.

Use **sample standard deviation** unless there is a compelling reason in the existing project conventions to use population standard deviation.

Document the selected convention explicitly.

Do not label standard deviation as variance.

---

# 15. Solar Statistics

For each month calculate:

\[
\mu_{Solar,m}
\]

and:

\[
\sigma_{Solar,m}
\]

For example:

```json
{
    "month": 1,
    "count": 310,
    "mean": 21.05,
    "std_dev": 8.24
}
```

Values shown here are illustrative of the schema; the importer must calculate them from the supplied files.

---

# 16. Temperature Statistics

Independently calculate monthly statistics for:

```text
TemperatureMinimum
TemperatureMaximum
```

For each:

\[
\mu_m
\]

and:

\[
\sigma_m
\]

using all valid observations for that variable/month.

---

# 17. Monthly Correlation Matrices

For each calendar month calculate the empirical Pearson correlation matrix for:

```text
SolarExposure
TemperatureMinimum
TemperatureMaximum
```

The variable order shall be fixed and explicitly written into the model:

```json
"variables": [
    "solar_exposure",
    "temperature_minimum",
    "temperature_maximum"
]
```

The resulting monthly matrix has the form:

\[
R_m =
\begin{bmatrix}
1 &
\rho_{Solar,Tmin} &
\rho_{Solar,Tmax}
\\
\rho_{Solar,Tmin} &
1 &
\rho_{Tmin,Tmax}
\\
\rho_{Solar,Tmax} &
\rho_{Tmin,Tmax} &
1
\end{bmatrix}
\]

Calculate these correlations using only complete date-matched observations for that month.

Store the number of matched observations used.

Example:

```json
{
    "month": 1,
    "observation_count": 310,
    "correlation_matrix": [
        [1.0, -0.12, 0.42],
        [-0.12, 1.0, 0.71],
        [0.42, 0.71, 1.0]
    ]
}
```

The numbers above are schema examples only and must not be hard-coded.

---

# 18. Correlation Validation

After calculating each correlation matrix validate:

```text
matrix is 3x3
all values finite
symmetric within tolerance
diagonal approximately 1
all entries within [-1,+1]
positive semidefinite
```

Because the simulation engine intends to use Cholesky decomposition, also test whether the resulting matrix can be successfully decomposed using the same numerical assumptions expected by the simulator.

Do not silently alter an invalid matrix.

If a matrix is numerically singular or cannot be decomposed, report:

```text
month
observation count
matrix
reason for failure
```

and fail model generation.

A future version may implement explicit nearest-correlation-matrix repair, but V1 shall not silently repair calibration results.

---

# 19. Distribution

For V1 the generated weather model shall specify:

```json
"distribution": "normal"
```

for:

```text
solar_exposure
temperature_minimum
temperature_maximum
```

The importer is therefore calibrating a monthly multivariate-normal approximation.

The importer architecture must not assume normal distributions are the only possible future model.

Future calibration implementations may use:

```text
lognormal
beta
empirical distribution
bootstrap
kernel density
regime model
time-series model
```

Do not embed the normal-distribution assumption in the generic BOM parsing layer.

---

# 20. Physical Bounds

V1 shall calculate statistics from the observations without truncating or modifying the source data.

The generated model may record known/observed bounds:

```text
observed_minimum
observed_maximum
```

but the importer shall not attempt to modify the fitted normal distribution to enforce physical bounds.

In particular, solar exposure cannot physically be negative, but handling of simulated negative normal draws belongs to the weather-model implementation/design, not the BOM importer.

---

# 21. Model Provenance

The generated JSON must contain enough provenance to reproduce the calibration.

At minimum include:

```text
source provider
BOM product IDs
station IDs
station names if available
station latitude if available
station longitude if available
station elevation if available
requested training period
available source-data periods
generation timestamp
importer version
```

Do not invent unavailable metadata.

If metadata cannot be obtained from the supplied files, either omit it or represent it explicitly as unavailable.

---

# 22. Output JSON

The primary output is a standalone weather-model definition.

Example structure:

```json
{
    "name": "SydneyWeatherRecent",
    "type": "CorrelatedMonthlyWeather",

    "location": {
        "name": "Sydney",
        "latitude": -33.87,
        "longitude": 151.22
    },

    "training_period": {
        "start": "2016-01-01",
        "end": "2025-12-31"
    },

    "source": {
        "provider": "BOM",

        "solar": {
            "product": "IDCJAC0016",
            "station": "066006",
            "station_name": "Sydney Botanic Gardens"
        },

        "temperature": {
            "maximum_product": "IDCJAC0010",
            "minimum_product": "IDCJAC0011",
            "station": "066037",
            "station_name": "Sydney Airport AMO"
        }
    },

    "solar_exposure": {
        "units": "MJ/m2/day",
        "distribution": "normal",
        "monthly": []
    },

    "temperature_minimum": {
        "units": "C",
        "distribution": "normal",
        "monthly": []
    },

    "temperature_maximum": {
        "units": "C",
        "distribution": "normal",
        "monthly": []
    },

    "dependence_model": {
        "type": "correlation_matrix",

        "variables": [
            "solar_exposure",
            "temperature_minimum",
            "temperature_maximum"
        ],

        "monthly": []
    }
}
```

---

# 23. Monthly Variable JSON

Each monthly entry should contain sufficient diagnostic information to understand the fitted model.

Recommended:

```json
{
    "month": 1,
    "observation_count": 310,
    "missing_count": 0,
    "mean": 21.05,
    "std_dev": 8.24,
    "observed_minimum": 1.2,
    "observed_maximum": 34.1
}
```

The simulator only needs some of these fields.

It should ignore additional calibration metadata it does not require.

This permits the generated model file to remain useful for inspection and validation.

---

# 24. Monthly Dependence JSON

Recommended:

```json
{
    "month": 1,
    "observation_count": 310,
    "correlation_matrix": [
        [1.0, -0.12, 0.42],
        [-0.12, 1.0, 0.71],
        [0.42, 0.71, 1.0]
    ]
}
```

The row and column order is defined by:

```json
"variables": [
    "solar_exposure",
    "temperature_minimum",
    "temperature_maximum"
]
```

Do not duplicate variable names inside every matrix.

---

# 25. Deterministic Output

Given:

```text
identical source files
identical command-line parameters
identical importer version
```

the generated model parameters must be identical.

JSON object/array ordering should also be deterministic where practical so generated model files can be meaningfully diffed.

The only field permitted to differ between identical runs should be a generation timestamp if one is included.

Consider making the timestamp optional or excluding it from semantic comparison tests.

---

# 26. Import Report

The tool should print a concise calibration report to stdout.

Example:

```text
BOM Weather Model Import

Solar:
  Product: IDCJAC0016
  Station: 066006
  Available: 1990-01-01 -> 2026-10-01
  Valid observations: 12943
  Missing observations: 480

Maximum temperature:
  Product: IDCJAC0010
  Station: 066037
  Available: ...
  Valid observations: ...

Minimum temperature:
  Product: IDCJAC0011
  Station: 066037
  Available: ...
  Valid observations: ...

Training period:
  2016-01-01 -> 2025-12-31

Matched observations:
  ...

Monthly correlations:
  January: 310 observations
  February: 282 observations
  ...

Validation:
  12/12 correlation matrices valid
  12/12 Cholesky decompositions successful

Output:
  weather_model_066006_066037.json
```

Exact numbers must come from the input files.

---

# 27. Warnings

Warnings should be generated for conditions that do not necessarily prevent calibration, such as:

```text
missing observations
non-accepted/unusual quality flags
very low monthly observation counts
large differences in source coverage
unexpected gaps
```

Warnings shall not silently alter the data.

---

# 28. Fatal Errors

Fail the import for conditions including:

```text
input file cannot be opened
unrecognised BOM format
wrong BOM product type
malformed numeric values where a value is expected
invalid dates
duplicate observations
requested training period unavailable
no valid observations for a required month
insufficient matched observations to calculate correlation
invalid correlation matrix
failed Cholesky validation
output file already exists without --overwrite
output file cannot be written
```

Return a non-zero process exit code.

---

# 29. Recommended Class Structure

Conceptually:

```text
BomWeatherImporter
|
+-- CommandLineOptions
|
+-- BOM
|   |
|   +-- BomFileParser                  [abstract/interface]
|   |
|   +-- DailySolarExposureParser
|   +-- DailyMaximumTemperatureParser
|   +-- DailyMinimumTemperatureParser
|
+-- Data
|   |
|   +-- WeatherObservation
|   +-- WeatherSeries
|   +-- DailyWeatherRecord
|   +-- JoinedWeatherDataset
|
+-- Calibration
|   |
|   +-- MonthlyStatisticsCalculator
|   +-- CorrelationCalculator
|   +-- CorrelationMatrixValidator
|   +-- CholeskyValidator
|   +-- WeatherModelBuilder
|
+-- Output
    |
    +-- WeatherModelDefinition
    +-- JsonWeatherModelWriter
    +-- ImportReportWriter
```

The exact class/file structure may differ, but parsing, calibration and serialisation must remain separated.

---

# 30. Processing Sequence

The program should execute approximately:

```text
Parse command line
        ↓
Open input files
        ↓
Identify/validate BOM products
        ↓
Parse solar observations
        ↓
Parse Tmax observations
        ↓
Parse Tmin observations
        ↓
Validate individual time series
        ↓
Construct date-indexed joined dataset
        ↓
Apply requested training period
        ↓
Calculate monthly solar statistics
        ↓
Calculate monthly Tmin statistics
        ↓
Calculate monthly Tmax statistics
        ↓
Create complete-case monthly datasets
        ↓
Calculate monthly correlation matrices
        ↓
Validate matrices
        ↓
Test Cholesky decomposition
        ↓
Build WeatherModelDefinition
        ↓
Validate complete model
        ↓
Write JSON
        ↓
Print import report
```

---

# 31. Separation from Simulator

The importer and simulator shall share the **weather model JSON schema**, but the simulator shall not depend upon importer implementation classes.

Conceptually:

```text
                BOM CSV files
                     |
                     v
            BOM Weather Importer
                     |
                     v
       weather_model_066006_066037.json
                     |
              ----------------
              |              |
              v              v
         Simulator       Human inspection
```

This is an intentional architectural boundary.

The BOM importer knows about:

```text
BOM products
BOM columns
quality flags
historical observations
statistical calibration
```

The simulator knows about:

```text
weather model parameters
monthly distributions
correlation matrices
stochastic shock generation
```

Neither should know unnecessary details about the other.

---

# 32. Unit Tests

Implement unit tests for:

### BOM parsing

Use small synthetic files containing:

```text
valid rows
missing values
malformed dates
malformed numbers
quality flags
duplicate dates
```

### Date filtering

Verify exact inclusion of:

```text
start date
end date
```

### Missing data

Verify missing observations are excluded rather than converted to zero.

### Monthly grouping

Verify observations from different years are assigned to the correct calendar month.

### Mean

Use a known sample and verify exact expected mean.

### Standard deviation

Use a known sample and verify the selected sample-standard-deviation convention.

### Correlation

Use small known paired datasets and verify expected Pearson correlations.

### Complete-case correlation

Construct data where one variable is missing and verify that date is excluded from the multivariate correlation calculation but remains available for applicable univariate statistics.

### Matrix validation

Test:

```text
valid matrix
non-symmetric matrix
invalid diagonal
coefficient > 1
singular matrix
non-positive-definite matrix
```

### JSON output

Compare generated output against a known expected model.

---

# 33. Integration Test

Create a small synthetic set of three BOM-format files containing several years of daily observations.

Run the complete importer.

Verify:

1. Files are parsed correctly.
2. Training dates are respected.
3. Monthly observation counts are correct.
4. Means are correct.
5. Standard deviations are correct.
6. Complete-case counts are correct.
7. Correlations are correct.
8. All matrices pass validation.
9. Generated JSON conforms to the expected schema.
10. Running the importer twice produces semantically identical JSON.

---

# 34. Real-Data Acceptance Test

Run against the Sydney BOM datasets:

```text
Solar:
    IDCJAC0016
    066006

Tmax:
    IDCJAC0010
    066037

Tmin:
    IDCJAC0011
    066037
```

Generate at least:

```text
weather_model_066006_066037_1990_2025.json
weather_model_066006_066037_2016_2025.json
```

These represent:

```text
SydneyLongTerm
SydneyRecent
```

The importer should successfully generate both models from the same underlying observation files simply by changing the requested training period.

---

# 35. V1 Non-Goals

Do not implement in V1:

```text
automatic BOM downloading
web scraping
BOM API integration
rainfall
wind
humidity
hourly weather
solar DNI/DHI decomposition
serial autocorrelation
AR models
weather regimes
periodicity
ENSO
climate trends
distribution fitting/selection
bootstrap distributions
missing-data interpolation
nearest-correlation-matrix repair
GUI
database storage
simulation
```

These may be added later without changing the basic:

```text
parse -> normalise -> calibrate -> serialise
```

architecture.

---

# 36. Future Extension Requirements

The importer architecture must permit future weather variables such as:

```text
rainfall
wind speed
humidity
cloud cover
DNI
DHI
```

without redesigning the calibration pipeline.

It should also eventually permit models other than independent monthly distributions, including:

```text
serial correlation
autoregressive weather
periodicity
wet/dry regimes
empirical distributions
multivariate bootstrapping
```

Therefore keep:

```text
raw observation parsing
dataset construction
statistical calibration
weather-model construction
JSON serialisation
```

as separate responsibilities.

---

# 37. Primary Design Rule

The importer's output is a **model**, not a cleaned copy of the historical data.

Its purpose is to transform:

\[
Historical\ BOM\ Observations
\]

into:

\[
Calibrated\ Weather\ Model\ Parameters
\]

The simulator subsequently uses those parameters to generate new stochastic weather scenarios.

The simulator must not need access to the original BOM files.

---

# 38. V1 Acceptance Criterion

The tool is complete when the following command:

```text
bom-weather-import \
    --solar <BOM solar file> \
    --tmax <BOM maximum temperature file> \
    --tmin <BOM minimum temperature file> \
    --start-date 2016-01-01 \
    --end-date 2025-12-31 \
    --model-name SydneyWeatherRecent \
    --output weather_model_066006_066037.json
```

produces a validated, deterministic, self-contained JSON definition containing:

```text
model identity
training period
source provenance
monthly solar statistics
monthly Tmin statistics
monthly Tmax statistics
12 monthly correlation matrices
observation counts
units
distribution definitions
```

and that JSON can subsequently be consumed directly by the PV Simulator's `CorrelatedMonthlyWeatherModel`.