"""Write CSV copies of every parquet, for tools that can't read parquet."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for folder in ['data/raw', 'data/ml', 'data/reference']:
    for f in sorted((ROOT / folder).glob('*.parquet')):
        out = f.with_suffix('.csv.gz')
        pd.read_parquet(f).to_csv(out, index=False, compression='gzip')
        print(f"  {out.relative_to(ROOT)}  ({out.stat().st_size/1048576:.1f} MB)")
print("done — note CSVs are ~5x larger and lose dtypes")
