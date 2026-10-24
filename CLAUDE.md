# CLAUDE.md — Quick-Commerce Market Intelligence

Read this fully before touching anything. Several findings here were expensive to establish and get re-litigated by anyone who skips them.

## 1. What this is

Price, stock and ETA observations for four quick-commerce platforms in Bhubaneswar, Odisha — Blinkit, Swiggy Instamart, Flipkart Minutes, BigBasket — plus a leakage-safe feature layer aimed at price intelligence (who is cheaper, by how much, what moves next).

Owner: Deepak, 3rd-year B.Tech CSE (Data Science with AI), LPU. Portfolio project. Method quality matters more than result magnitude.

610,789 rows · 109 raw+feature columns (108 at the original freeze, which already included `split`; +`store_id_source` from patch v1) · 4 platforms · 30 stores · 12,188 catalog products.

## 2. THE MOST IMPORTANT FACT

The dataset is mixed real and synthetic. Every row is labelled. Never blur them.

| Platform | Rows | data_status |
|---|---|---|
| Blinkit | 21,949 | REAL — one observed snapshot, 2026-07-10 |
| Blinkit | 148,740 | SYNTHETIC |
| Swiggy Instamart | 150,480 | SYNTHETIC |
| Flipkart Minutes | 142,320 | SYNTHETIC |
| BigBasket | 147,300 | SYNTHETIC |

Real observations cannot be collected from these platforms programmatically — no public APIs, no scraping. The Blinkit data exists only because a human collected it. The other three were generated deliberately, with the user's explicit informed consent, after being shown the governance tension. The agreed guardrail is hard labelling.

Provenance columns on every row: `source`, `price_provenance`, `enrichment_provenance`, `data_status`, `is_real_observation`.

Real throughout, even on synthetic rows: product names, brands, categories, subcategories, pack sizes, store names, addresses, coordinates, pincodes. Generated on synthetic rows: prices, MRP, discounts, stock, ETA, fees, offers, badges.

```python
real = df[df.data_status == 'REAL']   # the ONLY rows reportable as market fact
```

Any statement like "Instamart is 2% cheaper than Blinkit" derived from synthetic rows is a statement about the generator, not the market. Say so, every time.

> **Synthetic structure is planted, not discovered.** The v15.1 generator plants known dynamics in the SYNTHETIC rows (`docs/GENERATOR_v15_PARAMETERS.md`). Recovering those parameters with a model proves the MODELING PIPELINE works — exactly like the Flipkart −6% recovery check proves the cross-platform join works. It is NOT a market finding. No result computed from synthetic rows may ever be reported as one.

Synthetic generator history: v10 → v14 common panel → v15.0 dynamics → **v15.1 real-calibrated (current, 2026-09-17)**. v15.1 calibrated two things to the REAL Blinkit snapshot: per-category stock-out levels and price-ending styles. The calibrated hazard scales are NOT depletion rates (one snapshot cannot separate depletion from replenishment); never report them as "category X sells out faster". Coarse real-style price grids attenuate the measured price-response coefficient to ~50% of the planted value, and the same would affect real pass-through estimates. Provenance of every parameter (🟢 real-calibrated vs 🟠 assumption): `docs/GENERATOR_v15_PARAMETERS.md`. v15 regenerated only the dynamic columns of SYNTHETIC rows (prices, MRP/discount, stock, ETA, offers) and kept every ID, grid, catalog, store and panel column plus all REAL rows cell-for-cell. Planted: duration-dependent stock-out hazard, variable restock durations, Blinkit-leader / follower price response, ETA driven by store demand pressure. Log: `data/raw/GENERATOR_LOG.md`. Backups: `data/archive/v14_pre_regen/` (pre-v15, also the generator's input) and `data/archive/v15_0_pre_calibration/`.

## 3. Settled findings — do NOT re-derive or reverse these

### 3.1 The source's "5 snapshots" of Blinkit history are fake

The original workbook carried 5 dated snapshots. Its own build notes mark four of them (2026-06-10, 06-17, 06-24, 07-01) as `backfilled_modeled_for_pipeline_testing`: prices are ±2–6% jitter around the 07-10 price, and stock status is identical on all five dates — exactly 20,595 Available / 1,354 Out of Stock, the same SKUs every time.

Only 2026-07-10 carries `is_observed_baseline = True`. There is no real Blinkit history. Any multi-date Blinkit panel is necessarily SYNTHETIC.

Trap: `blinkit_ml_dataset.xlsx` has jitter on its 07-10 prices too (MASTER-00001 reads 35.88 vs real 35.0). Never use it as a price source.

**Real-data source files — neither ships with this repo.**
- `Blinkit_REAL_v7.xlsx` is a **superseded intermediate artifact**, not part of the shipped project. The real un-jittered prices originally came from it. It holds 21,945 of the 21,949 real rows (not the 4 unnamed listings). A local copy existed outside the repo at `Desktop/Project #1/Claude data/` when last checked, 2026-09-17; do not assume it still does.
- `Blinkit_Master_FINAL_Clean_v2.xlsx` (in the owner's `Downloads/`, last checked 2026-09-17) is the **fallback real-data source**. Its `MASTER_PRODUCTS` sheet covers all 21,949 real rows: Selling Price and Stock Status match v7 on 21,945/21,945, and ETA matches raw `delivery_eta_min` on 21,945/21,945. It is the only source for the 4 unnamed listings. Its `PRODUCT_SNAPSHOTS` sheet contains the jittered fake history (§3.1) — use `MASTER_PRODUCTS` only.

**What "verified against source" covers** (last checked 2026-09-17): `selling_price` and `stock_status` on the 21,949 REAL rows — 21,945 matched against `Blinkit_REAL_v7.xlsx` (0 mismatches) plus the 4 unnamed listings matched against `Blinkit_Master_FINAL_Clean_v2.xlsx`. Not "everything verified": other columns were not checked as a whole.

### 3.2 The "2,923 duplicates" are NOT duplicates

Audits flag duplicates on `snapshot_id + store_id + canonical_product_key` (2,923 dupes, 5,342 rows). Investigated across all 2,419 collision groups:

| listing_class | Rows | Groups | Meaning |
|---|---|---|---|
| single_listing | 16,607 | — | no collision |
| distinct_listing | 4,682 | 2,098 | price/MRP/stock/ETA genuinely differ |
| identical_repeat | 660 | 321 | identical except product_id |

Only 339 rows are genuinely removable; they are marked `is_preferred_listing = 0`, not deleted. A store can carry one SKU as several listings at different prices. Deleting them destroys real within-store price variation (done once in v8, reversed).

### 3.3 `canonical_product_key` is intentionally NOT unique

| Key | Grain | Unique? |
|---|---|---|
| observation_key | snapshot_id \| store_id \| product_id | YES — 610,789/610,789 |
| canonical_product_key | SKU (name \| pack_size), cross-platform match key | No, by design |
| product_id | one catalog listing | yes (21,949 real) |
| listing_seq | which listing of that SKU in that store | 1–6 |

Point every duplicate check at `observation_key`.

### 3.4 Leakage bug and the convention that prevents it

Five features once used `groupby().transform()` over the whole panel, so a row at t knew prices from t+1 (price_min below own price at t=0 in 2,028 panels; price_max above in 2,176). Replaced by `price_min_to_date`, `price_max_to_date`, `price_avg_to_date`, `price_volatility_to_date`. `price_median` dropped.

**CONVENTION: a feature at time t may use data up to and INCLUDING t. Nothing may use t+1 or later.**

`build_features.py` prints the leakage verification on every run — if a PASS turns to FAIL, stop.

### 3.5 MRP semantics

Absent MRP is set equal to selling price with `discount_percent = 0` (user's explicit instruction). `mrp_source` makes it reversible: `observed_distinct`, `observed_at_mrp`, `assumed_equal_to_selling_price`, `invalid_source_mrp_below_selling_price_set_to_selling_price` (33 real rows, patch v2: source MRP was present but below selling price), `simulated_discounted`, `simulated_at_mrp`. To restore the strict view, null `mrp` and `discount_percent` where `mrp_source` is `assumed_equal_to_selling_price` or `invalid_source_mrp_below_selling_price_set_to_selling_price`.

Do not use filled MRP as a product-identity attribute.

### 3.6 Deliberate NULLs and sentinels — do not "fix" these

| Field | State | Why |
|---|---|---|
| snapshot_time on REAL rows | 'NOT_RECORDED' | source recorded date only |
| hour on REAL rows | -1 | same; `time_of_day_known` flags it |
| price_lag_1, price_7d_avg | NULL at panel start | no prior observation |
| competitor_avg_price | NULL (18.8%) | SKU on one platform only |
| future_price | NULL at panel end | no next observation |

Do not impute them. A fabricated field on a row flagged REAL is the most misleading thing this project could produce. `date`, `week`, `month`, `dow_num`, `is_weekend` ARE filled on real rows.

### 3.7 Four unnamed listings

MASTER-15606, MASTER-15609, MASTER-16464, MASTER-18803 have no product name in the source and are not in `Blinkit_REAL_v7.xlsx`; their source is `Blinkit_Master_FINAL_Clean_v2.xlsx` (§3.1). Current state after patches v1 + v2:
- `product_name` = self-describing label 'UNNAMED LISTING MASTER-xxxxx'; `pack_size`, `pack_qty`, `pack_unit`, `unit_price` are NULL (v1).
- `selling_price` = `mrp` = 100 / 100 / 150 / 499; `stock_status` Available — match the source.
- `mrp_source = 'assumed_equal_to_selling_price'` (v2). **Inferred, not proven** for these 4 rows: in that source MRP was filled from selling price on every other row where MRP was absent.
- `delivery_eta_min` = `delivery_eta_max` = 8 / 8 / 11 / 11 (v2), confirmed against the source. They were 9 before v2.

### 3.8 Store ids (patch v1)

Real Blinkit rows originally used `BBSR-00N`; synthetic used `BLK-BBSR-00N` for the same 8 stores. Patch v1 unified them on `BLK-BBSR-00N`, kept the original in `store_id_source` (RAW, STORES.csv, CANONICAL_KEY_AUDIT.csv), and repaired two truncated store names. `observation_key` was intentionally NOT rebuilt and still contains `BBSR-00N` on real rows — join stores on `store_id`, never by parsing `observation_key`. RAW now has 51 columns. Receipt: `data/raw/PATCH_LOG.md`.

## 4. What this data CANNOT support

Absent: customers, orders, transactions, quantities sold, revenue, inventory levels, ratings. Supply-side only.

Not buildable — push back if asked: demand forecasting, price elasticity, reorder prediction, recommendation-to-customer, order → AOV → GMV → revenue.

| Blocked | Honest substitute |
|---|---|
| Demand forecasting | Stockout-hazard survival (time-until-OOS) |
| Price elasticity | Competitive price-response (VAR + impulse response) |
| Reorder prediction | Restock-interval model |
| Recommendation | Assortment-gap recommender (store × product implicit MF) |

The full plan — 13 deliverables including SIMULATE (positioning what-ifs only), OPTIMIZE (price cut to target cheapest-share, restock priority, REAL store-coverage gaps) and the RAG + AI analyst (every claim provenance-labelled) — is `docs/PROJECT_PLAN.md`, with what each can and cannot claim.

## 5. Layout and commands

```
src/load.py              data access layer — loading, splits, column roles, feature guard (docs/DATA_ACCESS.md)
src/model_output.py      model output contract — every model saves through it (docs/MODEL_OUTPUT_CONTRACT.md)
src/integrity.py         raw / ML hashes for manifests
src/pipeline/build_v10..v14_panel   how RAW was built (history)
src/pipeline/build_v15_dynamics.py  current synthetic generator v15.1 (run 2026-09-17; reads data/archive/v14_pre_regen; do not re-run casually)
src/diagnostics.py                  shared audit/test measurements (corrected hazard estimator, price endings, ties)
src/pipeline/build_features.py      RAW -> ML, the only one normally re-run
src/pipeline/to_csv.py              optional CSV export
src/matching/            model 1 product matcher v1: blocking, features, labels (provenance + review queue), train (docs/MATCHER_v1.md)
                         v2 beside it: diff_features.py, edits.py, train_v2.py (docs/MATCHER_v2.md)
src/audit/               store_label.py: does store_id on the REAL rows carry information? (docs/STORE_LABEL_AUDIT_v1.md)
src/provenance.py        which REAL results depend on the store label, and the label's status; read by manifests, analyst, pages
src/planner/             collection.py: how big a hand-logged REAL panel must be (docs/COLLECTION_PLANNER_v1.md)
src/coverage/            deliverable 12c store coverage gaps, REAL only (docs/COVERAGE_12C.md)
src/features/            derived past-only feature tables -> data/ml, each with a truncation leakage check:
                         stock_clock.py (in-stock clock, spells, store pressure index), price_grid.py (grid step, stickiness)
src/models/              deliverables 2-10, one module each: price_forecast (2), price_direction (3), stockout_classifier (4),
                         eta_forecast (5), anomaly (6), stockout_survival (7), restock_interval (8), price_response (9),
                         assortment_gaps (10). Docs: docs/<NAME>_v1.md
src/simulate/            engine.py (PriceWorld, StockWorld: parameters read from saved outputs; outages, inactive
                         listings, per-snapshot states) + whatif.py (11), grid.py (cuts and raises),
                         unavailable.py, store_adds.py. Docs: docs/SCENARIOS_v1.md
src/optimize/            price_cut.py (12a), restock_priority.py (12b), promo_frontier.py, restock_lab.py,
                         price_headroom.py (raises), restock_objective.py. Docs: docs/SIMULATE_OPTIMIZE_v1.md, WHATIF_EXTENSIONS_v1.md,
                         PRICE_INCREASES_v1.md
src/analyst/             deliverable 13: kb (BM25 over docs + metrics), tools, guard (refusals + verifier), agent, evaluate
src/chain/listing.py     product x store chain, 7 stages: observe -> applicability -> prediction record -> price grid ->
                         simulation -> optimization -> explanation (docs/LISTING_CHAIN_v1.md)
data/raw/*.parquet       FROZEN — NEVER write here (baseline: scripts/verify_raw_integrity.py, after the v15.1 calibration, checked 2026-09-17)
data/ml/                 generated by build_features — not in git
data/reference/          catalog, stores, schedule, key audit, ML schema
docs/                    how each layer was built
notebooks/01_explore.ipynb
```

This machine is Windows and `make` is not installed. Run the Python directly:

```powershell
python -m src.pipeline.build_features   # make features — prints leakage verification
python -m src.matching.train            # make matching
python -m src.matching.review           # label the priority batch (unblocks model 1 tier 1)
python -m src.matching.import_labels <export>  # labels from the review page   python -m src.matching.ai_review  # AI proxy
python -m src.matching.behaviour        # behavioural (CheckList) test of the saved matcher, no labels
python -m src.models.price_forecast     # deliverable 2, next-price forecast
python -m src.features.stock_clock      # stock-clock table (needed by 3, 4, 5, 7, 8, 11, 12b)
python -m src.features.price_grid       # price-grid table (needed by 3, 6)
python -m src.models.stockout_classifier  # 4    python -m src.models.stockout_survival   # 7
python -m src.models.restock_interval     # 8    python -m src.models.price_response      # 9
python -m src.models.eta_forecast         # 5    python -m src.models.price_direction     # 3
python -m src.models.anomaly              # 6    python -m src.models.assortment_gaps     # 10
python -m src.simulate.whatif             # 11   (needs 5, 7, 8, 9 saved first)
python -m src.optimize.price_cut          # 12a  python -m src.optimize.restock_priority  # 12b
python -m src.analyst "question" [--llm]  # 13   python -m src.analyst.evaluate [--llm]
python -m src.chain.listing --demo        # one listing through all layers (needs 2-10 + grid saved first)
python -m src.simulate.unavailable       # outages   python -m src.simulate.store_adds   # store adds products
python -m src.optimize.price_headroom    # raises    python -m src.optimize.restock_objective  # lost-wins restock
python scripts/build_explorer.py         # outputs/showcase/explorer.html (chain + scenarios + EXTERNAL context)
python -m src.coverage.store_coverage   # deliverable 12c, store coverage gaps
python -m src.matching.train_v2         # matcher v2    python -m src.matching.ai_review --model v2   # its AI proxy
python -m src.audit.store_label         # store-label audit (REAL) + synthetic positive control
python -m src.planner.collection        # collection planner (reads the audit's stock clustering if it has been run)
python scripts/check_claims.py          # headline numbers in the docs vs the saved outputs; exit 1 if any is stale
python scripts/build_reality_check.py   # outputs/showcase/reality_check.html (audit + matcher v2 + planner)
python scripts/build_site.py            # the website: outputs/site/index.html; site/README.md
python scripts/serve_site.py            # the website (Qcom) on http://localhost:8000, the offline analyst behind /api/ask
python -m src.seasonal.festive          # festive planner data -> outputs/festive/festive_planner.json (not a model)
python scripts/check_site.py            # every page and control of the built site, under node; exit 1 if anything throws
python scripts/run_all.py               # everything, in order; rebuilds the run-log page and the site last
python scripts/run_all.py --list | --dry-run | --step a,b | --from x | --resume | --timeout s   # see §13
python -m src.pipeline.contracts        # the 21 data contracts (also a pipeline step); exit 1 if one is broken
python scripts/deploy_pages.py          # publish outputs/site to GitHub Pages (gh-pages branch); see §13
python scripts/readme_assets.py         # README pictures from outputs/site/screens (after site_browser_check.js)
python -m src.pipeline.to_csv           # make csv
```

Expected `make check` result: raw 610,789 | ml 610,789 x 116 | catalog 12,188 (115 before patch v1 added `store_id_source`; ML layer is 109 columns + 7 targets).

## 6. Rules

- Never write to `data/raw/`. Derived output goes to `data/ml/` or `outputs/`.
- Never split randomly. Use the `split` column: train 15 Sep–4 Oct, val 5–8 Oct, test 9–14 Oct, holdout_real. `splits()` does it.
- Never feed identifiers to a model. `feature_columns()` drops them.
- Never impute the structural NULLs in §3.6.
- State REAL or SYNTHETIC explicitly before any claim.
- Keep the provenance columns.
- Beat BOTH price baselines — naive ("tomorrow's price = today's price") and `price_avg_to_date` — or report the model as useless. (On v15.1 data naive is the stronger of the two: test MAE 10.56 vs 11.41.)
- Load through `src/load.py`, save through `src/model_output.py`. Never hand-filter splits or hand-list feature columns.
- **"Frozen" and "verified" claims must be sourced.** Any claim in this repo that data is "frozen" or "verified" must name the exact file it was checked against and the date it was last checked. If that source file cannot be found in the repo, the claim is stale: flag it as unverified, never assume it still holds. Example: "frozen = sha256 baseline in `scripts/verify_raw_integrity.py`, checked 2026-09-17".

### Regression check

Flipkart Minutes was generated at −6%. The features must recover it (values after the v15.1 calibration, 2026-09-17; enforced by `tests/test_regression_cheapest.py`):

| Platform | Cheapest of 4 | Median gap vs competitor avg |
|---|---|---|
| Flipkart Minutes | 56.6% | −5.34% |
| Swiggy Instamart | 24.6% | +0.37% |
| BigBasket | 18.0% | +2.27% |
| Blinkit | 17.5% | +2.95% |

History: v14 68.6 / 29.3 / 21.4 / 18.9 (₹10/₹50 psychological steps, 27.9% tied minimum) → v15.0 58.6 / 20.3 / 13.8 / 13.5 (₹1 rounding, 5.7% tied) → v15.1 above (real-calibrated endings, 14.0% tied). Ties count for every tied platform, and the tie rate is set by the price grid, so rounding changes move these values even though positioning is unchanged (Flipkart −5.35 / −5.49 / −5.34%). If they drift for any other reason, the cross-platform join has broken. Check before blaming the model.

## 7. Performance and correctness traps

- `transform(lambda s: s.expanding().min())` times out at 610k rows. Use native `cummin/cummax/cumsum`; expanding std from cumulative sums of x and x².
- Rolling: `groupby().rolling()` then `reset_index(level=..., drop=True).sort_index()`.
- `pd.to_datetime(..., format='mixed')` — without it every synthetic timestamp becomes NaT.
- Do not name a cumcount variable `n` (shadowed `n = len(dates)`, broke the split).
- Anchor selling price and derive MRP upward from discount depth, never the reverse (broke v4 and v9).
- `snapshot_completion_rate` denominators are per platform AND data_status.
- `np.select` cannot mix `np.nan` with string choices — use a sentinel string.
- Chat file uploads cap at 30 MiB per file.

## 8. Model 1: product matcher v1 (built 2026-09-17, docs/MATCHER_v1.md)

The only model trained on REAL data. `python -m src.matching.train`. Outputs: `outputs/models/product_matcher/` (REAL),
`outputs/models/product_matcher_crossplatform_checks/` (SYNTHETIC tiers 2-3), `models/product_matcher_v1.txt`.

Settled facts — do not re-derive:
- Every `CANONICAL_KEY_AUDIT` positive pair compares two IDENTICAL catalog records (1 distinct name/pack/brand per group).
  They cannot teach or test name variation. Tier 1 (real name variation) is measured only on human labels from
  `data/reference/MATCH_REVIEW_QUEUE.csv` and is currently **NOT MEASURABLE** (0 labels).
- Blocking recall on the audit pairs is 100% structurally. Hard-case blocking recall comes from a perturbation stress test
  (99.7%, blocking measurement only, never labels).
- Labels come only from: audit groups + R4 markup-only rule (auto_positive), rules R1/R2/R3 (auto_negative), or humans
  (`MATCH_REVIEW_PRIORITY.csv` / `MATCH_REVIEW_QUEUE.csv`), all stated in `labels.py`.
  Everything else is `needs_review`. Never guess a label.
- Raw `pack_qty` is wrong for every `**...**` pack (1.0) and for some multipacks. The matcher parses pack text itself.
- Without R3, LightGBM learns "same pack ⇒ same product" (2.1% random-pair false positives). Keep R3.
- Split by canonical_product_key group only (a row split leaks 90% of test keys). Test keys = stable hash + the 564 keys of
  `MATCH_REVIEW_PRIORITY.csv` (reserved evaluation keys). Never regenerate that batch once labels exist.
- Current verdict: **no valid claim that LightGBM beats the string-similarity baseline.** Next step is human labelling, not
  embeddings/FAISS.
- Review page (2026-09-25): `scripts/build_review_page.py`, published as the private artifact "Product Match Review", blind
  (no stratum or score). `python -m src.matching.import_labels <export>` brings its labels into the priority CSV; it holds
  back row/text mismatches, overwrites and non-owner decisions. 0 labels on the page as of 2026-09-25.
- AI proxy (2026-09-25, docs/MATCHER_v1.md): `src/matching/ai_review_data.txt` is Claude's blind review of the 297 pairs
  (76 S / 183 D / 38 U). It is NOT human labels and NOT tier 1; no labelling/training module may read it (test-enforced).
  `python -m src.matching.ai_review` -> `outputs/models/product_matcher_ai_proxy_check/`. On the 236 pairs with real name
  variation, LightGBM finds 4 of 53 AI-same pairs and PR-AUC is at chance (0.222 vs 0.225; baseline 0.228): against this
  reviewer both behave close to exact-match detectors. A hypothesis only until `human_agreement` (kappa, >= 20 pairs) is
  measured. (Corrected 2026-10-13: this line read "0 of 53" and "0.25", written from a run earlier on 2026-09-25 than the
  saved output. `scripts/check_claims.py` now checks such numbers.)
- Behavioural test (2026-09-25, no labels of any kind): `python -m src.matching.behaviour` edits REAL names in
  identity-known ways (rows SYNTHETIC; reloaded booster parity-checked on 2,000 saved scores, max diff 0.0). LightGBM
  passes 100% of identity-changing edits (pack, number, colour) and ~0% of identity-preserving ones that survive
  normalisation (punctuation 0%, typo 0.8%, alias 0%). Threshold-free AUC (preserving vs changing name edit) 0.42 LightGBM,
  0.44 baseline: no threshold fixes it; similarity measures how much differs, identity depends on what differs. v2 needs
  difference-aware features + positives with variation. Training on constructed edits = new label source, a policy change,
  not done without the owner's decision.

- **v2 (2026-10-13, docs/MATCHER_v2.md): `python -m src.matching.train_v2`, beside v1, replaces nothing.** The owner's
  reply of 2026-10-13 to the open items ("whatever is open, start finishing it") was taken as the go-ahead for constructed
  edits as a label source. Settled:
  - Constructed pairs are SYNTHETIC rows with `label_source = CONSTRUCTED_EDIT`, built from TRAIN-key records only. v2's
    claim scope is SYNTHETIC-DERIVED; v1 stays the REAL-only model. An edit is used only when its effect on identity does
    not depend on a judgement call (no word reordering, no variant bracket added to one side).
  - Labels do the work, features generalise. 2x2 ablation on held-out-key edits: new features without new labels change
    nothing (40.7% / 99.7% both ways). With a whole edit family withheld from training, v2's difference-aware features
    pass 85-100% on six of seven families; v1's similarity features fall to 3.5% on number changes and 9.6% on variant
    swaps (v2: 85.3% and 98.6%) and to 60-66% on formatting and typos (the two pack families are 99% for both). In-
    distribution pass rates (99.9% / 100%) are near-circular: never headline them.
  - The alias rule is taught, not learned: 0.3% when its family is withheld. It rests on a convention and five words.
  - **The gate is part of the model.** The only insertions in training are alias brackets, so the booster scores "one
    name says more" as the same product ('Amul Dark Chocolate Bar' / 'Amul Sugar Free Dark Chocolate Bar': 0.9996). No
    constructed edit fixes that honestly. v2 decides only when >= 25 training pairs share the pair's difference
    signature, else `decision = 'abstain'`; `pred_lightgbm` is the gated decision. On the 11,834 unlabelled REAL pairs:
    7,847 different, 70 same, 3,917 abstain. Never use the booster ungated.
  - AI proxy, scored once after the design was fixed (NOT tier 1): gated v2 0.84 precision / 0.30 recall / PR-AUC 0.705
    on the 236 name-variation pairs (v1 0.33 / 0.08 / 0.222). The ungated v1-feature model with constructed labels ranks
    better against this reviewer (PR-AUC 0.831). Choosing between them needs human labels, not this proxy.
  - No module that builds labels or trains may read the AI review; the test now covers train_v2, diff_features and edits.

Upgrade path, only after tier 1 is measured: sentence-transformer bi-encoder → FAISS → LightGBM re-ranker → connected components.

## 9. Honest framing for the write-up

The 30-day panel is generated; a model trained on it partly recovers the generator's assumptions. Fine for demonstrating method, not market findings. Say so. Six well-built models beat thirteen where seven rest on invented demand.

## 10. Known discrepancies (verified against the files, 2026-09-17)

- FIXED by patch v1: fabricated pack fields on the 4 unnamed listings, and the 38-vs-30 store_id split (see §3.7, §3.8). v1 also renamed store_name on 38,100 Blinkit and 16,620 Instamart synthetic rows; its original receipt omitted this, corrected in `data/raw/PATCH_LOG.md`. The `notes` text on the 4 unnamed rows still says selling_price was "left NULL"; the note is stale.
- FIXED by patch v2: ETA on the 4 unnamed listings (9 → 8/8/11/11), `mrp_source` on those 4 (inferred) and on 33 rows with an invalid source MRP (label only). See §3.5, §3.7 and `data/raw/PATCH_LOG.md`.
- FIXED 2026-09-17: `STORES_Instamart.csv` name for `INS-BBSR-007` now matches raw.
- `data/reference/_READ_ME_FIRST.csv` says Blinkit SYNTHETIC = 72,000 (actual 148,740). Stale.
- `docs/README_PIPELINE.md` and `docs/README_ML_v2.md` describe `.xlsx` / `.csv.gz` files and CSV hashes; the repo now ships parquet. Historical, not current.
- `data/ml/` and `ML_SCHEMA_v2.xlsx` rebuilt 2026-09-17 by `python -m src.pipeline.build_features` from raw after the v15.1 calibration (raw baseline `scripts/verify_raw_integrity.py`): all leakage checks PASS, split chronological, regression table as in §6. Tests: 247/247 (2026-10-20, after the data contracts, the runner and the server hardening; 213 on 2026-10-14 after the site additions; 193 earlier on 2026-10-14, after the website and its six tests; 187 on 2026-10-13 after the provenance safeguards of the audit; 182 earlier that day after matcher v2, the store-label audit, the collection planner and the claims ledger; 163 on 2026-09-25 after the behavioural test; 160 after the review-page import and AI-proxy guards; 154 on 2026-09-24 after the manifest check was extended to every new output; 145 after the scenario extensions and EXTERNAL sources; 123 after price increases; 113 after the product x store chain; 100 after the what-if extensions; 91 before them; 51 before deliverables 3-13 added test_feature_tables, test_deliverables, test_analyst; 47 before model 1 added 4).
- v15.1 (see `data/raw/GENERATOR_LOG.md`): synthetic OOS 6.37% (Blinkit at the real category mix 6.19% vs REAL 6.17%); price endings match real (distance 8.7/100); observed price dispersion 4.3% (grid rounding); 14.0% tied cheapest minimum.
- Audit/test hazard metrics use the corrected estimator (`src/diagnostics.py`). The naive one understated duration dependence (2.4 vs 13.1 on v15.0), and the corrected one was validated at 0.994 on memoryless stock and 0.845 on v14.
- Raw `pack_qty` defect (found by the matcher 2026-09-17, NOT fixed, patch v3 proposed): 370 products / 9,099 rows (819 REAL, 8,280 SYNTHETIC), identical in `data/raw/` and `data/ml/`: `**…**` packs stored as 1.0 (4,426 rows), same-unit combos stored as the first component only (4,200) or as corrupt values (473). Wrong `pack_qty`, `unit_price` and `unit_price_std`. The v14 archive (the v15 generator's input) carries it too.

## 11. Deliverables 3-13 (built 2026-09-23): settled facts — do not re-derive

All SYNTHETIC unless marked REAL. Recovery of planted values is a pipeline check, never a market finding.

- **New derived tables, never raw.** `data/ml/stock_clock.parquet` (13 cols) and `data/ml/price_grid.parquet` (8 cols),
  keyed on observation_key, past-only (truncation check in `verify()` and `tests/test_feature_tables.py`).
  `next_snapshot_is_evening` comes from the published schedule, not from t+1 data.
- **Stock hazard (4, 7).** The pooled hazard curve gives Weibull k ≈ 1.38. That is heterogeneity, not a wrong
  generator: category/platform take it to 1.81, a shared log-normal frailty to 1.98 (planted 2). The frailty sd is
  identified only on the full panel (0.495, planted 0.50); on train alone it collapses to 0. Use observed-restock clocks
  for recovery; a clock that began before the panel is a lower bound.
- **Restock (8).** Negative binomial n ≈ 1.94. The FAST/MEDIUM/SLOW groups are recoverable with no labels (adjusted
  Rand 1.0). The BigBasket multiplier lands slightly high (1.41 vs 1.35), within chance across 15 comparisons.
- **Price response (9).** Naive β is attenuated to ~50% by price grids. Indirect inference recovers the planted values,
  but ONLY with each listing's latent level estimated by interval likelihood: with the observed mean, it recovers ~68%.
  Simulating at the planted values must reproduce the naive β̂ before any correction is trusted.
- **ETA (5).** A naive regression gives the store-OOS-share effect as 56 min per 100% (planted 8). It is confounded:
  the same latent demand drives stock-outs and ETA. The state-space fix reaches 19. Conformal intervals are exact on
  average, but misses cluster by store × snapshot (34% of miss variance between clusters), so per-cell (Mondrian)
  calibration does not help. Ship marginal CQR.
- **Anomalies (6, REAL).** The unit-price detector finds the known pack_qty defect at 70% precision@100. A flag means
  "unusual within the snapshot", never "error" or "deal". The temporal detector needs a half-grid-step floor or it
  flags 8% of normal rows.
- **Assortment gaps (10, REAL).** The carry matrix mostly reflects collection depth (1,259-5,608 products per store;
  similarity does not follow distance). A gap is "not seen in this store's listing", not "not stocked". Since
  2026-10-13 read it with §12: the store label itself is not supported.
- **SIMULATE / OPTIMIZE (11, 12).** The engine reads every parameter from saved outputs. It must reproduce the status
  quo (cheapest-of-4 within 1 pp, test OOS path) before any what-if; re-validate after refitting 5, 7, 8 or 9. Static
  what-ifs overstate a leader's gain ~1.7×; the needed cut is ~1.6× deeper once followers react. For restock,
  "longest out first" is worse than random (n ≈ 2); the priority index cuts OOS exposure 26.7%.
- **Analyst (13).** The refusal policy is deterministic and runs before retrieval. The verifier relabels any claim
  from a SYNTHETIC source and flags numbers not in the retrieved evidence. Eval: 28/28 on the tuning set, 12/12 on a
  held-out set. The Claude (`--llm`) engine is tested with a mocked client only; score it live with
  `python -m src.analyst.evaluate --llm` once credentials exist.
- **What-if extensions (2026-09-24, docs/WHATIF_EXTENSIONS_v1.md).** `src/simulate/grid.py` precomputes 84 runs (161 with raises)
  (categories never interact, so one run answers all 13 at once; paired common random numbers). The analyst has three
  experiment tools (simulate_price_move, promo_frontier, restock_capacity); "smallest cut needed" questions stay with
  deliverable 12a. Promo vs list price: the availability cost is real but small (0.4-1.1 pp stock-outs for a 10% promo),
  no interior optimum; Snacks is the only category past a 1 pp budget. Restock lab: the index reaches 63% of a
  clairvoyant oracle at 0.25% capacity and 97% at 4%; top-ups only pay above ~2%. Eval: 33/33 tuning, 15/15 held-out.
  Interactive page: `scripts/build_whatif_lab.py` -> outputs/showcase/whatif_lab.html.
- **Product x store chain (2026-09-24, docs/LISTING_CHAIN_v1.md).** One listing through seven stages, stored in that
  order: observe -> applicability -> prediction record -> price grid -> simulation -> optimization -> explanation.
  Runs on a SYNTHETIC listing; the REAL 2026-07-10 row of the same product and store is context only (no model uses
  it). Applicability is checked per model against the saved outputs (7 in stock / 8 out of stock; 10 never applies to
  a listed product). The grid is inferred from the listing's own PAST prices. The baseline check runs before any
  what-if and blocks a recommendation if it fails; its share test is "observed inside the simulated 2.5-97.5% range,
  ends included" (the old percentile test failed identical all-zero shares). The analyst's explain_listing returns
  stages 1-6 as evidence and never the stored explanation, so the verifier is not checking text against itself.
  Product matching scores QUERY coverage (name coverage sent "sugar" to a sugar-free lassi). Gallery: 9/9 baselines
  pass (6 cut listings + 3 where Blinkit is already cheapest; it read 6/6 before the raise listings were added);
  competitor response doubles the needed cut on 3 of the 6 cut listings; chain vs deliverable 7 stock forecast within
  4.2 pp. Eval: 35/35 tuning, 18/18 held-out (one held-out item re-graded after the matcher fix, noted in evaluate.py).
- **Price increases (2026-09-24, docs/PRICE_INCREASES_v1.md).** The grid holds raises of 1-10% as well as cuts (cells
  carry `direction`, positive `cut_pct` = size, signed `move_pct`; a cell without `direction` is a cut). Planted
  structure holds: for a follower's raise the two views agree exactly (nobody follows a follower); for Blinkit, followers
  follow it up, so static overstates the loss 1.42x (1.76x for a cut's gain). Raises cost less than cuts buy, more so the
  bigger the move (loss/gain 0.96 at 1%, 0.44 at 10%): Blinkit only has 17.7% cheapest share to lose. No free raise:
  1% costs 1.4-2.4 pp in every category, so headroom is 0 at a 1 pp budget; it is reported at 1/2/5 pp together
  (9 and 13 of 13 categories at 2 and 5 pp with the response, 0 and 13 static), never one tuned budget. Withdrawing a
  promo: -0.01 to -0.30 pp stock-outs at a 5% raise. Chain: one target, two directions (smallest cut below it, largest
  raise at/above it); rungs beyond +/-30% are shown, never recommended. "Headroom" never means a raise earns more.
- **Scenario extensions (2026-09-24, docs/SCENARIOS_v1.md).** Measure: cheapest-AVAILABLE-of-4 (in stock and
  cheapest). Engine: `outage=` (length = snapshots out AFTER now; 0 = back before the next snapshot with a fresh clock,
  which is a small gain, not "no outage"; drawn lengths use their own RNG stream) and `active=` (inactive listings are
  simulated so random streams stay paired when listings are added). Outages: the platform with the most wins loses most
  (Flipkart -8.63 pp); Blinkit's cost by category recovers the planted FAST/SLOW restock groups. Substitution check: no
  effect (OR 0.949, CI 0.867-1.038) ONLY with time of day controlled; without it OR 0.909 (p 0.04), confounded because
  Blinkit is out more often before a morning snapshot. Store adds (REAL part is its own REAL-ONLY output): gaps do not
  rebalance category mix (4/8 stores closer); additions are cheaper items in all 8 stores (REAL); fixed restock effort
  dilutes (+2.30% median existing OOS exposure at +50), one extra action more than compensates. Restock objective:
  knee at alpha 0.75 (+6.7 pp lost-wins cut, 90% CI of the mean 4.3-9.1, for 1.3 pp exposure); report CI of the MEAN
  separately from the per-window band. In the chain, an outage only costs a win the listing would have had.
- **EXTERNAL sources (2026-09-24, docs/EXTERNAL_SOURCES_v1.md, facts in docs/external/).** A fourth label, never REAL:
  the verifier relabels any claim from docs/external as EXTERNAL and requires its URL. Only facts confirmed on the
  fetched page; no sales figures (revenue, GMV/GOV/NOV, orders, margin, market share), and GOV/NOV questions are
  refused. The store map is the SAME source as data/reference/STORES*.csv, so matching it is a freshness check, not
  validation. EXTERNAL passages enter an answer only when they share 2+ words with the question and score within 10% of
  the best match. Docs must not quote eval questions (it makes retrieval easier for exactly those questions). Eval:
  42/42 tuning, 25/25 held-out (two held-out items re-graded after fixes, marked in evaluate.py). Page:
  `scripts/build_explorer.py` -> outputs/showcase/explorer.html.

## 12. Additions of 2026-10-13: settled facts — do not re-derive

- **The store label on the REAL rows carries no detectable information (docs/STORE_LABEL_AUDIT_v1.md, REAL).**
  `python -m src.audit.store_label`. Ten permutation tests (2,000 shuffles of store labels across the 21,949 REAL rows):
  none departs after Bonferroni correction. Records sharing a name|pack sit in the same store in 21.0% of 17,054 pairs;
  a label independent of the product gives 21.9%; real per-store listing would give ~0. ETA, price and stock do not vary
  by store (variance between stores 0.0003 each), and ETA follows the product record instead (42% of its variance is
  between name|pack keys). Not a power problem: the ETA test detects a planted 0.2 min shift in one small store 99% of
  the time, and the same statistic is 0.73 on the SYNTHETIC rows where store ETA effects were planted.
  - **What it is not:** a statement about how the source was collected. The source workbooks are not in the repo. Ask
    the person who collected the data before writing "stores were assigned at random".
  - **Affected:** deliverable 10, 12c category coverage, `simulate_store_adds_real`, the store half of the chain's REAL
    context row. Each now carries the caveat; no output was withdrawn. The analyst adds the caveat to any REAL answer
    grouped by store or area. **Unaffected:** price and stock per record (verified against source), the matcher, the
    REAL anomaly detector, the v15.1 calibration (per category), store coordinates (separate public source).
  - **Record-level anatomy (REAL):** among records sharing a name|pack, given one is out of stock another is out 47.1%
    of the time, 6.4x the 7.4% rate; a shuffle within category gives 10.1%. Whether those records are the same product in
    different places or at different times cannot be told. 57.9% of such pairs differ in price, but 0% in Personal Care
    and 7.6% in Home & Cleaning: an open question about the source, never a finding about Blinkit's pricing.
  - The generator plants no such clustering (cross-platform lift 1.16). A candidate for a future generator revision;
    v15.1 was NOT re-run.
  - **Source workbook checked 2026-10-13** (`Blinkit_Master_FINAL_Clean_v2.xlsx` in the owner's Downloads, sha256
    568313ec…77b696, read-only; docs/audit/AUDIT_2026-10-13.md). Store names and addresses come from a public store map
    ("QuickCommerceMap public store listings", public_web_observation, ~50-100 m). Its `STORE_PRODUCT_MAP` sheet pairs
    every product row with one store, but no column or sheet records HOW: the provenance fields on those rows are the
    store's own. So the product-store link is of unknown provenance in the source itself. Status: **UNVERIFIED**.
  - **The status is enforced in code, not only in docs: `src/provenance.py`.** It lists the store-level REAL outputs
    (`assortment_gaps`, `store_category_coverage`, `simulate_store_adds_real`) and reads the status from the saved
    audit. `save_model_outputs` writes it into those manifests (`python -m src.provenance` stamps existing ones); the
    analyst marks each such claim `[REAL, STORE LABEL UNVERIFIED]` and adds a banner; the Explorer page and each chain
    record (`1_observe.real_observation.store_label`) show it. A new store-level REAL output must be added to that list.
    `store_coverage_geography` is not on it: it uses store coordinates only.
- **27 REAL prices were web-researched, not observed (found 2026-10-13, same workbook).** The source marks 27 rows
  "Web researched" with a URL: 14 from blinkit.com product pages, 13 from other sites (brand stores, other retailers).
  `data/raw` labels all 27 `price_provenance = observed` and is frozen, so the correction is
  `data/reference/REAL_PRICE_SOURCE_AUDIT.csv` plus `src.load.web_researched_price_ids()` /
  `real_observed_price_only()`. Use the latter for any statement about real Blinkit PRICES; `real_only()` stays right
  for stock. Existing REAL price results were not re-run without them (27 of 21,949 rows). Proposed for raw patch v3
  together with the pack_qty defect.
- **Collection planner (docs/COLLECTION_PLANNER_v1.md, SYNTHETIC).** `python -m src.planner.collection`: the common
  panel cut down to 126 designs (days x products x snapshots per day), 200 random cuts each, seven plain estimators.
  A planning prior, never a guarantee; effort uses an ASSUMED 20 s per observation. Settled: days and products buy
  different things (price gap and cheapest share are limited by products, evening ETA by days); a short window gives a
  precise wrong restock spell (bias -1.28 snapshots at 2 days, -0.11 at 14); one snapshot a day keeps the cross-section
  and loses every dynamic; the hazard's duration dependence (~240,000 observations) and the price response (500
  products for a week) are out of reach of the owner's 128-product watchlist. The owner's "QuickComm Price Logger"
  artifact had 0 observations on 2026-10-13.
- **Analyst.** Planning passages (the planner doc and output) are down-weighted in `kb.search` unless the question is
  about collecting data: the planner names every quantity and had pushed the stock-out sources out of one held-out
  answer (24/25). Fixed after seeing it, so that item is no longer clean (three re-graded in total, marked in
  evaluate.py). Eval after the fix: 42/42 tuning, 25/25 held-out.
- **Claims ledger.** `python scripts/check_claims.py` checks headline numbers in README.md, CLAUDE.md and the 2026-10-13
  docs against the saved output each came from (`tests/test_claims.py`). A quote that moved or a number that no longer
  rounds to the saved value fails. When a rerun changes a number, update the doc and the registry together.
- **Page.** `scripts/build_reality_check.py` -> outputs/showcase/reality_check.html.
- **Website (2026-10-14, site/README.md).** Sources in `site/` (index.html shell, app.css, app.js, analyst.js);
  `scripts/build_site.py` inlines them with the data into ONE file, `outputs/site/index.html`.
  `python scripts/serve_site.py` (or `start_site.bat`) serves it at http://localhost:8000, loopback by default, with
  `POST /api/ask` answered by the offline analyst. It is no longer published as an artifact. Settled:
  - Site wording (owner's requests, 2026-10-14): no page uses the two data-label words, nor "snapshot". A SYNTHETIC
    number is tagged "Lab" and a REAL one carries no tag (since 2026-10-24, see section 15); a snapshot as a time unit is a "check" (one round of
    prices and stock). Project text is reworded on display by `plain()` in `site/app.js`. The tags themselves stay on
    every number: removing the words is allowed, removing the distinction is not. `scripts/site_smoke.js` fails if
    any of those words reaches a page, a tooltip or a drawn answer. The rule covers the website only: `data_status`
    values, raw data, docs and the CLI analyst keep the labels.
  - Products a person adds on the site (owner's request, 2026-10-14): photo (camera or upload) plus details, saved
    by the server through `src/user_products.py` in `data/user_added/`, tagged USER ("Added by you"). Nothing in
    `src/` reads them (test-enforced); they never join the observed or simulated rows or any model. Editable
    (`PUT /api/products/<id>`); shown first on the Home shelf and in the Festive planner when in season.
  - Product pictures on the site are drawn packshots (`packshot()` in `site/app.js`), illustrations made from the
    product's name, pack and category, never brand photos (copyright; nothing is downloaded). Model charts on the
    Models page are drawn from each model's saved metrics by `build_site.model_charts()`; when a metrics key moves,
    that function is where the chart breaks.
  - It reads saved outputs only. Simulate and Optimize read the precomputed grids; nothing is simulated in the
    browser. An unreachable target is reported as no feasible answer, never extrapolated.
  - `site/analyst.js` is a hand port of the offline analyst (guard, kb, agent routing). When `guard.REFUSALS`,
    `kb.tokenize/stem`, `kb.search` or the routing regexes in `agent.py` change, change the port too:
    `tests/test_site.py` checks the refusal topics and order, and `scripts/site_analyst_eval.js` re-scores the port on
    both question sets with its answer cache OFF at every build (42/42 and 25/25 on 2026-10-14).
  - Experiment claims in the page are the Python analyst's own, produced and verified at build time
    (`build_site.tool_answers`); a price move is formatted in the page from the grid. Do not re-derive them in JS.
  - Festive planner (owner's request, 2026-10-14; `src/seasonal/festive.py`, page `#festive`). Festival dates
    Oct 2026 to Oct 2027 are EXTERNAL (cited panchang and holiday calendars, checked 2026-10-14; one-day
    disagreements noted per festival). Festival -> product type is a METHOD rule (keyword regexes, reviewed by hand
    against the snapshot names; "Chandan" is also a candy brand, camphor also sells as air freshener). Matched rows
    are REAL, 2026-07-10. It answers WHEN a product is in season, never how much more sells: no orders exist, and
    July was not a festival. Output goes to `outputs/festive/`, deliberately outside `outputs/models/` so the analyst
    does not index it; the analyst still refuses "what sells most at Diwali", and the site links that refusal to the
    planner. The calendar ends with Diwali 2027: extend `FESTIVALS` before then.
  - Phones and tablets (owner's request, 2026-10-14): `serve_site.py --lan` (`start_site_lan.bat`,
    `./start_site.sh --lan`) also binds 0.0.0.0 behind a six-digit code (HttpOnly cookie, 5 wrong codes -> 10 min
    lockout, Host must be this machine). It is opt-in: never start it for the owner, since it opens the machine to
    the network and Windows asks about the firewall. No regex lookbehind in `site/*.js` (Safari < 16.4 rejects the
    whole script; test-enforced). Icons and `manifest.webmanifest` come from `build_site.app_icons()`.
  - The server never runs a long job for a question: a listing with no saved chain gets "no saved chain"
    (`serve_site.needs_live_chain`), not a live chain run. The page falls back to its own engine if the server
    does not answer.
  - The site shows the run log, so it must be built after a run finishes: `run_all.py` rebuilds the run-log page and
    the site in its `after_run` phase, then runs `check_site.py`.
  - `check_site.py` (node, stand-in DOM) proves every page and control runs on the real data. It cannot see layout.
    `node scripts/site_browser_check.js` can: with the server running it drives headless Chrome or Edge through
    every page, tab and the analyst, in light, dark, phone and wide widths and as iPad / Android tablets with touch,
    fails on a script error or a sideways scroll, and saves screenshots to `outputs/site/screens`. Last run
    2026-10-14: 74 screenshots, 0 errors. It is not part
    of the test suite (it needs a browser); read the screenshots after any change to `site/`.

## 13. Additions of 2026-10-20: settled facts — do not re-derive

The owner asked (2026-10-20) for a stronger backend and pipeline, more features, hover effects and a more attractive
UI, a live deployment, a new GitHub repository on their profile and an attractive README with the live link.

- **GitHub and the live site.** Repository: https://github.com/Deepak17kb/quickcommerce-mi (public). Live site:
  https://deepak17kb.github.io/quickcommerce-mi/, served from the orphan `gh-pages` branch, which only
  `python scripts/deploy_pages.py` writes (the built page, `sw.js`, icons, manifest, a 404 page, `.nojekyll`; nothing
  else). Redeploy after every site rebuild: the live page does not update itself. It has no Python server behind it,
  so the analyst in the page answers and products a visitor adds stay in that visitor's browser. Not in git:
  `data/ml/` (rebuilt by build_features), `outputs/` (written by runs), `data/user_added/` (photos from the owner's
  camera). Git identity is repo-local: `Deepak` with the account's noreply address, as in the owner's other repos.
- **Data contracts (`src/pipeline/contracts.py`, pipeline step `data_contracts`, right after `price_grid`).** 21
  invariants from this file (composition, provenance, labels agree, observed day only, sentinels kept, schedule, price
  and MRP rules, stock flag, ETA order, stores by platform, ML shape, splits, chronology, past-only bounds, leaky names
  gone, structural NULLs, derived tables keyed 1:1). Every contract has a planted-violation test in
  `tests/test_contracts.py`, and a test keeps that true when a contract is added. Two facts found while writing them:
  the derived tables' column counts in §11 (13, 8) exclude `observation_key`; and `price_lag_1` / `future_price` are
  null exactly at panel start / end when a panel is keyed on data_status + platform + store_id + product_id (31,763
  panels; without data_status an observed row would share a panel with simulated rows).
- **Runner (`scripts/run_all.py`).** `NEEDS` names the steps each step reads; a failure records every descendant as
  BLOCKED (not run), independent steps still run, and the exit code is 1 on any failure. Every model step sits behind
  `data_contracts` (test-enforced). `STEPS` stays a list of 4-tuples: `build_run_page.py` unpacks them. The run page
  no longer says "stopped for low memory" for any step missing from a log. The data contracts were added to the
  2026-10-14 run with `--resume` (41 steps reused, the new one run): the models were NOT refitted on 2026-10-20.
- **Server (`scripts/serve_site.py`).** CSP and security headers on every response, gzip + ETag (2.8 MB -> 0.54 MB, a
  reload is a 304), LRU answer cache, `/api/metrics`, a JSON 500 for any handler error. Rate limits apply to Wi-Fi
  devices only (`LIMIT_LOOPBACK` lets tests limit the loopback). Every early answer to a request with a body (403,
  404, 413, 429) drains the body first: a flaky 404 test on 2026-10-20 was a Windows connection reset on an unread body.
- **Site additions.** Basket (Lab prices for followed listings, entered prices for your products; a mixed basket says
  so; an app missing a price for some line is shown, not ranked), Ctrl K / `/` palette, share, toast, back-to-top,
  reading bar, reveal-on-scroll, count-up, hover effects, service worker (network first). Everything that moves is off
  for reduced motion and for automated browsers (`navigator.webdriver` or HeadlessChrome adds `html.still`), so the
  checks and screenshots see the final state. Headless Chrome does not match `(hover: hover)`, so hover cannot be
  screenshot by the check. `.bar` is the header row's class: do not reuse it (the basket meter is `.bk-meter`).
  `site_smoke.js` presses the basket, palette, theme and share through `window.QCSite`; the browser check also fails
  on a CSP violation or a service worker that does not start and hold the page. Last run 2026-10-20: 81 screenshots,
  0 errors, 0 sideways scroll.
- **CI (`.github/workflows/ci.yml`).** On every push: raw hashes, rebuild of the ML layer and derived tables, the
  contracts, the ten test files that do not read `outputs/`, JS syntax and no lookbehind. Versions pinned to this
  machine's (pandas 3.0.0, numpy 2.4.2, pyarrow 23.0.1). The tests that read `outputs/` run only locally.
- **README** was rewritten for GitHub visitors. It still holds the 16 ledger quotes verbatim; `check_claims.py`
  matches after collapsing whitespace only, so no markdown may go inside a quote. Its pictures come from
  `scripts/readme_assets.py`; refresh them after a change to `site/`.
- `scripts/build_site.py` held a dead duplicate of `model_charts()` that copied the card list and called itself; it
  only worked because a second definition shadowed it. Removed.

## 14. Second pass of 2026-10-20: settled facts — do not re-derive

The owner listed six limits of the first pass and asked to "fix these". What each became:

- **Models retrained.** A full `python scripts/run_all.py` (not --resume) ran on 2026-10-20 with the DAG runner and the
  contract gate. It took three launches (a session end, a closed console window, then idle sleep at 01:42 on
  2026-10-22 each killed it; see section 15) and finished 2026-10-23 with 42/42 steps: every model refit, and the claims
  ledger still 37/37 on the refit outputs. §13's "models were NOT refitted" describes the first pass only.
- **The live site and the Python analyst.** GitHub Pages serves files only. The page asks, in order: its own server
  (`api/health` relative), then the public analyst named in `site/config.json` (`"api"`, or `$QCOM_API` at build time;
  https, or http://localhost / 127.0.0.1 for trying it), else its own engine. A sleeping free host is woken in the
  background (one probe of up to 75 s) and the page switches to it when it answers. `serve_site.py --public`
  (`render.yaml`, Render free tier, one-click button in the README) is read-only: any Host, `$PORT`, no writes (403),
  empty product list, rate limits for every device keyed on the LAST `X-Forwarded-For` entry, CORS for `/api/health`
  and `/api/ask` to `$QCOM_ALLOW_ORIGIN` only. It was NOT deployed: that needs the owner's Render login; `config.json`
  stays empty until a URL exists. `src.load.load_real()` reads the REAL rows with a row filter and releases Arrow's
  pool: the server process fell from 449 MB to 197 MB (measured 2026-10-20), so it fits a 512 MB free tier.
  `tools.real_rows()` uses it; every caller aggregates, so the new 0..n-1 index changes nothing (test-enforced equality).
- **Products on the live site** stay in the visitor's browser by design; Export / Import (Products page) move them as
  one JSON file with photos. `/api/health` says `"writes"`, and the page keeps products on a server only if it does.
- **The live site updates itself.** `site_dist/` is tracked; every build writes it through `deploy_pages.stage()`
  (refuses foreign files, never deletes what it did not write); `.github/workflows/pages.yml` deploys it on any push
  to main that changes it (Pages build type: workflow; the old `gh-pages` branch was removed). `deploy_pages.py` =
  stage + commit site_dist only + push.
- **Run outputs are released, not committed.** `scripts/release_outputs.py` zips data/ml + outputs/ (not screenshots,
  never data/user_added) into a GitHub Release, refused unless every step and test of the run passed, and writes
  `data/OUTPUTS_RELEASE.json` (tracked). `scripts/fetch_outputs.py` (stdlib only) downloads exactly that file, refuses
  a sha256 mismatch and any member outside data/ml/ or outputs/ (absolute, '..', backslash, drive, link), and keeps
  existing files unless --force. CI's `full-suite` job fetches it and runs every test on Linux (requirements-ci.txt,
  exact versions).
- **License.** MIT for the code (LICENSE, holder "Deepak Kumar Behera"); README states the data is shared for learning
  and research with the same permission, names belong to their owners, and nothing is a statement about sales.
- **Badges read the run.** `build_site.badges()` writes shields.io endpoint files (tests, pipeline, contracts, analyst,
  claims) into site_dist/badges; the README points at their raw URLs. A skipped test is reported apart ("N passing,
  k skipped") and no longer counted as not passing on the site either (`meta.run.tests` = tests that ran).
- **README wording (owner, 2026-10-20: "replace all synthetic with real in readme").** Declined as asked: relabelling
  simulated rows as real would misstate the data. Done instead: the README holds no "synthetic"; the data table shows
  the site's tags (Lab, or none for observed rows) and points to `src.load.real_only()`. Keep it that way: "simulated" / "Lab" in
  prose, never "real" for a simulated number.

## 15. Third pass, 2026-10-23: settled facts — do not re-derive

The owner asked for a festive planner that keeps up with every coming festival and special day (Rakhi, Father's Day),
a way from the basket to the cheapest app's cart, Simulate and Optimize that anyone can use, an easier site overall,
and "actual real images of products ... from Google or directly Blinkit".

- **The calendar computes itself (src/seasonal/almanac.py, METHOD).** Sun: Meeus ch. 25. Moon: the 31 largest terms of
  Meeus Table 47.A. Tithi = elongation / 12 deg, read at Bhubaneswar's sunrise, midday, afternoon (aparahna), dusk
  (pradosh), moonrise or midnight as each festival's tradition says. Amanta months named by the sidereal sign (Lahiri)
  at the opening new moon; two new moons in one sign make an adhika month (2026: Adhik Jyeshtha, 17 May - 15 Jun,
  test-enforced). Sankrantis, nth-Sunday days (Mother's Day 2nd Sunday of May, Father's Day 3rd Sunday of June,
  Friendship Day 1st Sunday of August), fixed days, and the tabular Islamic calendar for Eid (approximate: moon
  sighting). It reproduces all 19 cited 2026-27 dates exactly, day AND span (Dhanteras to Bhai Dooj; Durga Puja is
  the five days ending on Dashami, because Shashthi can span two sunrises; Navratri ends the day before Vijayadashami).
  festive.py keeps the cited table (EXTERNAL) and fills every other festival and year (METHOD, `rule` says how) for
  HORIZON_YEARS = 8 ahead; a computed festival within 3 days of a cited one is dropped. The page shows the next 12
  months (`upcoming(366)`) and labels each date's provenance.
- **Special-day groups were read against the observed names before going in.** chocolates (milkshakes, cakes, cold
  coffee excluded), perfumes (fabric conditioners excluded), men's grooming, soft drinks & party snacks, balloons &
  party props (fridge magnets excluded), and "made for the day" groups found by the occasion's own name (Teacher's Day
  bouquets, Valentine chocolate gift packs, Christmas wreath, Women's Day orchid, Ramzan dates). Dropped because the
  data has nothing real for them: stationery, toys, tricolour (only a "Tricolor" pasta), Mother's Day name match (only
  a pickle brand "Maa's"). Father's Day and Friendship Day plan from the general groups.
- **Basket -> app.** `SHOP` in app.js opens each app's own search for a product (blinkit.com/s/?q=, swiggy.com/instamart/
  search?query=, flipkart.com/search?...&marketplace=HYPERLOCAL, bigbasket.com/ps/?q=). No site can fill another app's
  cart; the page says so, and that the app's live price can differ from the Lab price. Checked 2026-10-24 in Chrome:
  Blinkit opens the search with Add buttons; Instamart's own search box writes exactly `search?custom_back=true&query=`,
  but a cold visit asks for a location or sign-in first (the page warns); BigBasket answers 200 and Flipkart routes
  through its location page keeping the search (curl; the browser extension may not visit those two). If an app
  changes its search URL, `SHOP` is the one place.
- **Simulate / Optimize for everyone.** The "Change a price" and "Reach a goal" tabs are a sentence of inline selects,
  answered in a sentence ("cheapest for N of every 100 products") with two 100-square grids; presets, a three-step
  guide, a glossary, and one plain line on every other tab; the old charts sit under "The details". The wording rule
  holds: the smoke test caught "the real market" in new text on 2026-10-23 and it was reworded.
- **Product photos: Open Food Facts only (scripts/fetch_product_photos.py -> data/reference/PRODUCT_PHOTOS.json).** The
  owner asked for Google/Blinkit photos; declined (brand and Blinkit copyright, Blinkit's terms, this project's
  no-scraping rule) and replaced by Open Food Facts (CC BY-SA 3.0), credited on Data & trust. Strict match: brand at the
  start of our name AND every word of their name in ours (at least two) AND at least half of ours in theirs AND a gift
  pack only matches a gift pack; captions say what the photo shows (another pack size is labelled). Food only. The
  first full run (2026-10-24) used ">= 75% of their words" with no reverse check and put a plain Dairy Milk bar on a
  Silk Heart Blush gift pack and a plain KitKat on two Rakhi gift packs; tests/test_publish.py pins those refusals.
  Coverage is modest and refusals are deliberate (a wrong photo is worse than a drawing). Hotlinked from images.openfoodfacts.org; the drawing stays under it.
- **Typical-look photos (2026-10-24, owner: "real images not ai generated").** Open Food Facts matched 3 of 94, so a
  product with no exact photo takes a photo of its KIND from Wikimedia Commons: `KINDS` in fetch_product_photos.py,
  one file per kind, each looked at by eye (no brand or label visible). 82 of 145 products; licence and author are read
  from Commons per file (CC0 / PD / CC BY / CC BY-SA only, else the script stops). The card labels it "Typical look",
  the tooltip says it is not the product's own pack, and Data & trust credits each file. Left out on purpose because
  every free photo showed another brand: sunscreen, face wash, namkeen, air freshener, chocolate bars and gift packs;
  combos ('+'/'combo') take no kind photo. Refusals pinned in tests/test_publish.py. Exact OFF photos now show at
  400 px (200 px looked blurred). The Commons API answers with thumb.wikimedia.org + tracking query; the script stores
  the same file on upload.wikimedia.org. CSP img-src allows images.openfoodfacts.org and upload.wikimedia.org only.
  `python scripts/fetch_product_photos.py --kinds-only` redoes the kind photos without re-searching Open Food Facts.
  The drawn packshots are code-drawn SVG, not AI images.
- **The tour (2026-10-24, for presenting the site).** `TOUR` in site/app.js: seven stops (Home hero, Products shelf,
  Simulate with the Diwali preset pressed, Optimize, Analyst asking a question it must refuse, Festive, Data & trust).
  A spotlight (its own box-shadow, no click-catching overlay) lit between the sticky header and the caption card, so
  the card never covers it; arrows/Enter/Esc. Started by "Take the tour" on Home, from Ctrl K, or `?tour` in the
  address (never in automated browsers, so the checks see pages undimmed). A stop's action runs once per tour.
  Captions read saved numbers (meta), never typed ones. Audit the same day: 0 script errors, 0 sideways scroll on 81
  screenshots; page switches <= 81 ms (<= 345 ms at 4x CPU); live cold load ~1.3 s (LCP), ~2.0 s on 4G + 4x CPU;
  the 2.9 MB page goes out gzipped at 0.58 MB. Moving the big data blocks after the scripts was weighed and not done
  (Home needs the what-if grid, Products the analyst's categories; ~0.3 s for a two-phase render).
- **Runner.** `keep_awake()` (SetThreadExecutionState) stops idle sleep during a run: on 2026-10-22 at 01:42 sleep
  (Kernel-Power 42) killed step 34. A partial run (--step/--only/--from/--resume) now merges into run_all.json.
  Long runs are launched hidden (WMI, ShowWindow=0): the owner closed a visible console window once and killed a run.
- **No tag on observed numbers (2026-10-24; reversed the same day, see section 16).** The owner asked for the observed-data tag and the day's date off the pages, and the
  two Home tiles "seen on Blinkit on one day" / "simulated, and tagged Lab" removed. `chip('REAL')` now renders nothing:
  the Lab tag alone marks simulated numbers, so an untagged number is Blinkit's own (Data & trust says so in its tag
  table). site_smoke.js fails on "10 Jul" anywhere a visitor reads, except their own typed question. Analyst answers
  about the data keep their as-of date in ISO form (2026-07-10): it is part of the answer, not a label.

## 16. Findings first, 2026-10-24 (evening): settled facts, do not re-derive

The owner asked for a critique "as a tech lead from Amazon" and then for every point of it fixed. What changed:

- **Name.** The site is **ShelfPulse** ("Qcom" is Qualcomm's ticker). Renamed in the pages, manifest, server, launchers,
  README, banner and service-worker cache (`shelfpulse-v1`; the old cache is dropped on activate). Product exports are
  named shelfpulse-products-*.json; the import never checked the app name, so older Qcom exports still import.
- **Home leads with the observed day, not the Lab.** Hero: "One day of Blinkit, collected by hand. Here is what it
  revealed." with a findings card; then a 1-observed / 30-simulated strip; tiles count the 21,949 observed listings, not
  the 610,789 rows; then "The engine, tested in the Lab". The Lab product shelf, the welcome box and the festival
  banner left Home (shelf on Products; festivals under More). The ticker leads with the findings; the Lab
  cheapest-of-four line is gone from it.
- **Findings page (#findings), REAL only.** `obsFindings()` in app.js, four findings, all from saved outputs:
  the anomaly detector's top 100 flags are 70% the pack-size defect (819 rows, base 3.7%), with the most unusual
  example named (Hommade Coconut Milk 200 ml at Rs 89 read as Rs 89 per ml); stock-outs cluster (47.1% vs 7.4%, 6.4x;
  10.1% shuffled within category; same product in different places or different moments cannot be told); 27 prices
  were web-researched (14 Blinkit pages, 13 other sites); the store column: 0 of 10 permutation tests after Bonferroni.
  The defect and web-price numbers come from the new `findings` block (`build_site.findings()`).
- **"Observed" tag is back** (`chip('REAL')` -> green "Observed", eye icon), reversing the morning's "no tag": a
  missing tag was not read as a meaning. Still no date on it; "10 Jul" stays banned.
- **Menu.** Seven up front (Home, Findings, Products, Simulate, Optimize, Analyst, Models); Data & trust, Pipeline,
  Festive planner and "Collection plan" (the plan page) under a "More" menu that hangs from the header (`#more-menu`,
  outside the nav strip, which scrolls sideways on phones). The More button shows the open page's name when it is one.
- **No internal plumbing on the pages.** plain() drops "(CLAUDE.md s.x)" citations and calls any other mention "project
  notes"; srcLabel maps CLAUDE.md to "project notes"; contract references go through plain(); a raw row key
  (BASELINE_... | BBSR-... | MASTER-...) is shown as "one row" with the key kept in the tooltip. A scan of every
  page and three analyst answers found none left.
- **Models.** The three observed-data models come first; "Does the data back it? In the Lab only." is no longer
  repeated on seven cards (the Lab tag and the lede say it once); the matcher shows its next step from
  MATCH_REVIEW_PRIORITY.csv (297 pairs, 0 labelled). Labelling is still the owner's job: no label is guessed.
- **Tour.** Home -> Findings -> Products -> Simulate -> Optimize -> Analyst -> Data & trust (Festive dropped).
- **README** banner and intro tell the same story; README pictures regenerated with scripts/readme_assets.py.

