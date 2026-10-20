.PHONY: setup features check matching csv clean verify-raw test verify

setup:          ## create venv and install dependencies
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

features:       ## FIRST RUN: build the ML layer from data/raw (a few minutes)
	python -m src.pipeline.build_features

check:          ## verify everything loads
	@python -c "from src.load import load_raw, load_ml, load_catalog; \
	r=load_raw(); m=load_ml(); c=load_catalog(); \
	print(f'raw {len(r):,} | ml {len(m):,} x {m.shape[1]} | catalog {len(c):,}'); \
	assert r.observation_key.is_unique, 'row key not unique'; print('ok')"

matching:       ## product matcher: candidates, scores, review queue
	python -m src.matching.train

csv:            ## optional: also write CSV copies of every parquet
	python -m src.pipeline.to_csv

verify-raw:     ## sha256 of data/raw/*.parquet vs the frozen baseline; non-zero on mismatch
	python scripts/verify_raw_integrity.py

test:           ## guardrail tests: leakage, split, id columns, real/synthetic counts
	python -m pytest tests -q

verify: verify-raw test   ## run both

clean:
	rm -rf outputs/* && touch outputs/.gitkeep
