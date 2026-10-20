# data/

```
data/raw/        {Platform}_RAW.parquet     FROZEN source of truth — never edit
data/ml/         built by `make features`   — not shipped, regenerated locally
data/reference/  catalog, stores, schedule, key audit, ML schema
```

## Why raw ships and ml doesn't

The ML layer is **fully reproducible** from raw by one command, and shipping both would
have doubled the download for no benefit. `make features` rebuilds all 109 columns in a
few minutes, and prints the leakage verification while it runs.

## Why parquet

The same data as gzipped CSV is 38 MB; as parquet with categorical dtypes it is 6.7 MB —
about 5.7x smaller, and it preserves dtypes so nothing has to be re-inferred on load.
`pyarrow` is in requirements.txt. If you need CSVs for another tool: `make csv`.

## Rules

- **Never write to `data/raw/`.** Everything derived goes to `data/ml/` or `outputs/`.
- **Filter `data_status == 'REAL'`** before reporting anything as real market fact.
  Only Blinkit's 21,949 rows qualify.
- **Never split randomly.** Use the `split` column — it is chronological.
