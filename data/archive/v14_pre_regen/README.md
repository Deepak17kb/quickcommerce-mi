# Archive: data/raw before the v15 dynamics regeneration

Copied 2026-09-17, immediately before `src/pipeline/build_v15_dynamics.py` ran.
State = raw after patch v1 + patch v2 (baseline hashes in SHA256SUMS.txt; Blinkit 4e04dffcac84b821).
Also holds the PATCH_LOG.md and ML_SCHEMA_v2.xlsx of that moment.

Kept OUTSIDE data/raw/ on purpose: scripts/verify_raw_integrity.py fails on extra parquet files there.
Nothing reads from this folder. To roll back, copy the four parquet files back into data/raw/,
restore the v2 hashes in scripts/verify_raw_integrity.py, and re-run build_features.
