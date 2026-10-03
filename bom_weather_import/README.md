# BOM Weather Model Import Tool V1

A standalone Python 3.10+ command-line importer with no runtime dependencies.
It reads three BOM **directories**, calibrates a monthly normal weather model,
and writes one `CorrelatedMonthlyWeather` model object. There is no surrounding
simulation object and no simulation implementation.

Run directly from this checkout:

```sh
./bom-weather-import \
  --solar inputs/IDCJAC0016_066006_1800 \
  --tmax inputs/IDCJAC0010_066037_1800 \
  --tmin inputs/IDCJAC0011_066037_1800 \
  --start-date 2016-01-01 \
  --end-date 2025-12-31 \
  --model-name SydneyWeatherRecent \
  --location-name Sydney \
  --output my_weather_model.json
```

`python3 -m bom_weather_import` is equivalent. Optionally install with
`python3 -m pip install .` for the `bom-weather-import` command on PATH.
The start/end dates are inclusive and must be covered by every source dataset.
Use `--verbose` for resolved Note/Data paths and all monthly statistics.
`--overwrite` explicitly permits replacing the output. Input files are protected.
The output parent directory must exist.

JSON is indented UTF-8 with stable ordering and full float precision. By default,
identical files/options/version produce identical bytes, independent of the
checkout directory. `--include-timestamp` adds the current UTC generation time;
only that field then varies. Source file names and SHA-256 hashes preserve input
identity without embedding machine-specific absolute paths.

Exit codes: `0` success, `2` command-line usage, `3` input/identity/coverage,
`4` calibration/matrix failure, `5` output failure. Reports go to stdout;
warnings and errors go to stderr. Output publication is atomic, and existing
files are protected even if another process creates the destination during an import.

## Architecture and numerical contract

- `bom.py`: directory discovery, identity cross-checks, dedicated Note parser,
  and a CSV parser configured with a separate schema for each product.
- `data.py`: normalised observations, date-indexed series and calendar joining.
- `calibration.py`: univariate statistics, complete-case Pearson correlations,
  correlation matrix validation and actual Cholesky decomposition/reconstruction.
  This module does not depend on BOM syntax, metadata or filenames.
- `output.py`: model construction, JSON publication and report formatting.
- `cli.py`: argument handling, orchestration and warnings.

Station IDs are six-character strings. Tmax/Tmin station IDs must agree; solar
may differ. Each source retains its own station and coordinates. Model location
contains only an optional descriptive name supplied with `--location-name`.
No source coordinates are promoted to model coordinates.

Blank values and absent calendar dates remain missing. Monthly missing counts
are the number of calendar days in the requested period without a numeric value.
Available periods describe CSV date coverage, including rows with blank values.
No observation is imputed or filtered by quality. CSV quality flags and optional
accumulation days are preserved internally; quality counts include both numeric
and missing rows. Multi-day accumulation, if encountered, produces a warning and
is retained as supplied. No date shifting is performed: BOM already assigns the
temperature observation dates.

Univariate statistics use all valid values per variable and calendar month.
Standard deviation uses the **sample** denominator `n-1`. Correlations use only
complete date-matched triples, ordered as solar, Tmin, Tmax. Zero-variance
complete-case variables and unusable months fail calibration.

The 3x3 matrix validator checks shape, finiteness, symmetry, unit diagonal,
strict coefficient bounds, and all principal minors for positive semidefiniteness.
Absolute tolerance is `1e-12`. Standard unpivoted Cholesky must also succeed,
with every diagonal residual greater than `1e-12`; reconstruction is checked.
Thus singular and numerically singular PSD matrices fail. No coefficients are
clipped and no matrix repair is performed. A failure reports month, complete-case
count, matrix (when calculable) and reason. The future simulator should use the
same documented numerical contract; no simulator exists here to link against.

## Actual BOM formats and specification decisions

The supplied files use CRLF lines, comma-separated CSV, separate Year/Month/Day
columns and blank fields for missing values. Parsers also accept LF, a UTF-8 BOM,
and reordered recognised columns. Unknown schemas fail explicitly.

| Product | Actual value header | Other measurement columns |
| --- | --- | --- |
| IDCJAC0016 | `Daily global solar exposure (MJ/m*m)` | None; no quality flag |
| IDCJAC0010 | `Maximum temperature (Degree C)` | `Days of accumulation of maximum temperature`, `Quality` |
| IDCJAC0011 | `Minimum temperature (Degree C)` | `Days of accumulation of minimum temperature`, `Quality` |

All three begin with `Product code`, `Bureau of Meteorology station number`,
`Year`, `Month`, `Day`. Temperature quality values in these files are `Y`, `N`,
or blank; numeric readings with incomplete metadata exist. Blank accumulation
metadata does not make a numeric reading missing.

CSV headers are authoritative for measurement descriptions, units and schema.
Temperature Notes instead describe `Daily maximum/minimum temperature (degrees
Celsius)` and a `Period over which ... was measured (days)`. Their descriptions
are retained separately as `note_measurement_description` and `note_units`.
These are wording differences, not a units conversion. Model units are the
specification's `MJ/m2/day` and `C`. Product/station contradictions remain fatal
identity errors rather than silently switching the requested dataset.

Notes provide station IDs without leading zeroes, names, coordinates, elevation,
state, opening **years** (not exact dates), blank closing years, product/reference,
quality/missing-data explanations and export creation information. Unknown fields
are omitted. Available observation dates come from CSV, not station opening years.
Solar is satellite-derived at the station coordinates, not measured at the site;
that provenance is retained. Temperature time-assignment guidance is retained too.

The final specification has differing illustrative provenance layouts (§14/§35).
This implementation uses §14's per-variable source objects and §35–37's model,
monthly statistics and dependence fields. The older incomplete
`inputs/PV_sim_sample_input.json` uses `type: Weather` and nested temperature
fields; the authoritative final specification instead requires
`type: CorrelatedMonthlyWeather` and separate `temperature_minimum` /
`temperature_maximum`. The output is the model alone. Generation timestamps are
opt-in as permitted by §38. No specification or source input was modified.

## Verification

```sh
python3 -m unittest discover -s tests -v
```

The suite covers Note metadata, station normalisation, discovery/ambiguity,
identity/product validation, all CSV products, missing/zero values, quality flags,
duplicates, invalid dates/numbers, inclusive training filtering, absent dates,
monthly grouping, exact sample statistics, Pearson/complete-case correlations,
invalid/PSD/singular matrices, Cholesky reconstruction, JSON rendering,
byte determinism, overwrite protection, error exit codes and a full CLI subprocess.
Synthetic integration directories contain three years of daily rows and exact
orthogonal complete-case vectors with independent missing observations.

Real-data acceptance tests independently re-read the supplied CSVs and verify
all 72 monthly univariate summaries and 24 correlation matrices using separate
formulas. They also rerun both complete imports and compare JSON bytes against
the generated models in `outputs/`.

See [the real-data results](docs/bom_import_verification.md) for counts and checks.

V1 deliberately supports only the three observed BOM export schemas. Additional
BOM layouts need explicit parser support. There is no downloading, imputation,
quality filtering option, distribution fitting, matrix repair or simulation.
