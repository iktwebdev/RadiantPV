# BOM V1 real-data verification

Validated with `python3 -m unittest discover -s tests -v`: **29 tests passed**.

Both imports ran successfully against the supplied Note/Data pairs. Independent acceptance tests recomputed every monthly mean, sample standard deviation, minimum, maximum, missing count and complete-case Pearson coefficient directly from CSV, then regenerated both outputs and confirmed byte-identical JSON.

## Source coverage

| Variable | Station | CSV dates | Rows | Blank values |
| --- | --- | --- | ---: | ---: |
| Solar | 066006 — SYDNEY BOTANIC GARDENS | 1990-01-01–2026-10-01 | 13,423 | 480 |
| Tmin | 066037 — SYDNEY AIRPORT AMO | 1939-01-01–2026-10-02 | 32,052 | 186 |
| Tmax | 066037 — SYDNEY AIRPORT AMO | 1939-01-01–2026-10-01 | 32,051 | 120 |

Source records have blank numeric values, not numeric missing-value sentinels. Solar has no quality column. Temperature records contain `Y`, `N` and blank flags; blank accumulation metadata also occurs alongside valid readings. All numeric readings were retained. All selected calendar dates have CSV rows; selected missing counts below are blank measurements.

## Calibration counts

| Period | Solar valid / missing | Tmin valid / missing | Tmax valid / missing | Complete dates |
| --- | ---: | ---: | ---: | ---: |
| 2016–2025 | 3,650 / 3 | 3,632 / 21 | 3,648 / 5 | 3,626 |
| 1990–2025 | 12,669 / 480 | 13,124 / 25 | 13,143 / 6 | 12,640 |

## Recent solar sanity check

| Month | Mean (MJ/m²/day) | Sample SD |
| --- | ---: | ---: |
| January | 21.050000 | 8.235635 |
| April | 13.260333 | 3.815826 |
| June | 9.154333 | 2.091314 |
| July | 10.380645 | 2.252624 |
| October | 19.673548 | 5.859996 |
| December | 23.147097 | 7.984218 |

These match all six exploratory estimates to their supplied precision. No calibration adjustment or hard-coded target values were used.

## Monthly complete-case counts and validation

| Month | 2016–2025 | 1990–2025 |
| --- | ---: | ---: |
| 01 | 306 | 1067 |
| 02 | 280 | 991 |
| 03 | 305 | 1080 |
| 04 | 300 | 1037 |
| 05 | 310 | 1077 |
| 06 | 300 | 1040 |
| 07 | 310 | 1079 |
| 08 | 309 | 1069 |
| 09 | 299 | 1053 |
| 10 | 310 | 1080 |
| 11 | 291 | 1018 |
| 12 | 306 | 1049 |

All **24/24** correlation matrices passed dimension, finite-value, symmetry, unit-diagonal, bounds and PSD checks. All **24/24** actual Cholesky decompositions and reconstruction checks passed. Independent determinant checks were strictly positive.

- 2016–2025 determinant range: 0.392264–0.623710.
- 1990–2025 determinant range: 0.452231–0.657184.

January 2016–2025 correlation matrix (solar, Tmin, Tmax):

```json
[
  [
    1.0,
    0.09105333857143466,
    0.5073941638587055
  ],
  [
    0.09105333857143466,
    1.0,
    0.6158832924835387
  ],
  [
    0.5073941638587055,
    0.6158832924835387,
    1.0
  ]
]
```

The matrices are comfortably nonsingular. Temperature statistics show expected seasonal ordering; no obvious column swaps or units errors appeared. Missing values contributed to neither means nor correlation triples.

## Outputs

- [Recent model](../outputs/weather_model_066006_066037_2016_2025.json)
- [Long-term model](../outputs/weather_model_066006_066037_1990_2025.json)

Each file contains the model object alone, 36 univariate monthly summaries, 12 dependence matrices, per-source metadata/file hashes and calibration policies. Model location is only `Sydney`; source coordinates remain under their source stations. Generation time is omitted for byte reproducibility.

## Remaining limitations

No implementation failures remain in these inputs or tests. The parser intentionally accepts the three inspected CSV schemas. The future simulator is not implemented in this repository, so compatibility is validated against the final specification and documented Cholesky assumptions, not a running simulator. Non-`Y` temperature flags remain an explicitly reported source-data quality limitation. See the README for all format/schema decisions.
