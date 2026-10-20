# Generator log

## v15 dynamics regeneration — 2026-09-17

Script: `src/pipeline/build_v15_dynamics.py` · parameters: `docs/GENERATOR_v15_PARAMETERS.md` ·
realized draws: `docs/GENERATOR_v15_realized.json` · seed 20260917.

> Recovering the planted parameters with a model proves the MODELING PIPELINE works, exactly like the
> Flipkart −6% check proves the cross-platform join works. It is NOT a market finding.

**Why.** `scripts/audit_signal.py` showed the v10/v14 synthetic rows had no learnable structure:
memoryless stock-outs, 91% one-snapshot restocks, no cross-platform price response, and delivery ETA
that was flat noise (store-mean sd 0.007 min, 0.0003 correlation with store stock-outs, only the fixed
+4 min at 18:00).

**Backup first.** `data/raw/*.parquet` (post patch v2), `PATCH_LOG.md` and `ML_SCHEMA_v2.xlsx` were
copied to `data/archive/v14_pre_regen/` with `SHA256SUMS.txt` before anything was written. It is kept
outside `data/raw/` so the integrity check's extra-file rule still holds.

### Hard-constraint verification (independent cell-by-cell diff against the archive)

| Check | Result |
|---|---|
| REAL Blinkit rows | 21,949 rows, **0 cells differ**, `DataFrame.equals` True |
| Patch v2 corrections on REAL rows | ETA 8/8/11/11 intact; unnamed-row `mrp_source` intact; 33 invalid-MRP labels intact |
| Common panel (products on all 4 platforms × 60 snapshots) | **2,000 before → 2,000 after** (checked before simulating and after writing) |
| Schema | 51 columns, identical order and dtypes, all 4 files |
| Row counts | Blinkit 170,689 · Instamart 150,480 · FlipkartMinutes 142,320 · BigBasket 147,300 (unchanged) |
| `observation_key` | unique 610,789/610,789, identical to v14 in every file |
| Snapshot grid | 60 synthetic snapshots, every synthetic panel complete |
| Provenance | all 588,840 synthetic rows: `source = SIMULATED_GENERATOR_v15`, `data_status = SYNTHETIC`, `is_real_observation = 0`, `price_provenance` updated; `in_common_panel` unchanged |

Columns re-simulated on SYNTHETIC rows only: `selling_price`, `mrp`, `discount_percent`, `unit_price`,
`stock_status`, `in_stock`, `is_bestseller`, `delivery_eta_min`, `delivery_eta_max`, offer fields
(`offer_type`, `offer_value`, `coupon_required`, `buy_quantity`, `get_quantity`), `notes`, `source`,
`price_provenance`. Offers were cleared on 68,594 out-of-stock rows and
7,282 rows whose flat/bank/combo value was ≥ the price.

### Signal audit before → after (`outputs/audit/signal_audit_before_v15.*`, `signal_audit_after_v15.*`)

| Planted | Metric | v14 (before) | v15 (after) |
|---|---|---|---|
| A | hazard range over in-stock run 1..10 | 0.0199 | 0.0389 |
| A | spearman(run length 1..10, hazard) | -0.6121 | 0.903 |
| A | hazard at run 10 / hazard at run 1 | 0.8041 | 2.399 |
| B | share of completed OOS spells of length 1 | 0.9069 | 0.3656 |
| B | mean completed OOS spell length (snapshots) | 1.1045 | 2.673 |
| B | std of completed OOS spell length | 0.3449 | 2.1538 |
| A/E | P(OOS at t+1) | 0.0892 | 0.1167 |
| A/E | P(OOS at t+1 | OOS at t) | 0.0961 | 0.6368 |
| A/E | panel OOS-rate p90 - p10 | 0.1167 | 0.1667 |
| A/E | max - min category OOS rate | 0.0779 | 0.0306 |
| A/E | OOS rate 18:00 - 09:00 | 0.0288 | 0.0169 |
| C | coef on own deviation (-1 = full reversion) | -1.013 | -0.5353 |
| C | coef on competitor gap | -0.0001 | -0.0306 |
| C | mean cross-platform same-snapshot corr | 0.0003 | 0.2715 |
| C | beta: Swiggy Instamart dev_t on Blinkit dev_t-1 (given own t-1) | 0.0024 | 0.4414 |
| C | beta: Swiggy Instamart dev_t on Blinkit dev_t-2 (given own t-1) | -0.009 | 0.2521 |
| C | beta: Flipkart Minutes dev_t on Blinkit dev_t-1 (given own t-1) | -0.0206 | 0.2957 |
| C | beta: Flipkart Minutes dev_t on Blinkit dev_t-2 (given own t-1) | -0.0135 | 0.1745 |
| C | beta: BigBasket dev_t on Blinkit dev_t-1 (given own t-1) | -0.0063 | 0.1818 |
| C | beta: BigBasket dev_t on Blinkit dev_t-2 (given own t-1) | 0.0196 | 0.3499 |
| C | lag-1 autocorr of deviation from panel mean | -0.0126 | 0.4592 |
| C | std of deviation from panel mean | 0.0257 | 0.0292 |
| C | test MAE: future = current price | 10.8763 | 10.5827 |
| C | test MAE: future = price_avg_to_date | 8.8505 | 10.702 |
| D | corr(eta_t, eta_t+1) | -0.1544 | 0.2574 |
| D | R2 of platform x hour mean | 0.8441 | 0.5679 |
| D | R2 of platform x store x hour mean | 0.8442 | 0.6696 |
| D | corr(ETA residual, store-snapshot OOS share) | 0.0003 | 0.3775 |
| D | corr(ETA residual, discount_percent) | -0.0021 | 0.1011 |
| D | mean ETA 18:00 - 09:00 (minutes) | 4.0006 | 3.4452 |
| D | std of store mean ETA within platform (minutes) | 0.0067 | 1.1369 |
| D | corr(ETA residual t, ETA residual t+1) | 0.0008 | 0.266 |
| offers | rows with effective_price clipped to 0.01 | 8432 | 0 |

Reading: A hazard now rises with time in stock (Spearman −0.61 → +0.90; h10/h1 0.80 → 2.40).
B one-snapshot restocks 90.7% → 36.6%, spell sd 0.34 → 2.15. C followers track Blinkit at their
planted lag (β̂ 0.44 / 0.30 / 0.35 vs planted 0.45 / 0.30 / 0.35), cross-platform co-movement
0.0003 → 0.27. D ETA now tracks store stock-out pressure (0.0003 → 0.38), discounts (−0.002 → 0.10),
store (sd 0.007 → 1.14 min) and is persistent (0.001 → 0.27).

**Side effects, stated plainly.**
- Overall OOS rate 8.9% → 11.7%.
- The category OOS spread fell 7.8 → 3.1 points and the evening-minus-morning OOS gap 2.9 → 1.7
  points: fresh items now go out sooner but also restock faster, which partly cancels. Both effects
  are still present.
- Price level per panel and positioning were kept: platform mean prices moved by less than ₹1, and
  Flipkart's median gap is −5.49% (v14 −5.34%).
- Because v15 prices are persistent, the `price_avg_to_date` baseline (MAE 10.70) is now slightly
  worse than naive (10.58), the reverse of v14. Price models must beat both.
- Cheapest-of-4 shares changed from 68.6/29.3/21.4/18.9 to 58.6/20.3/13.8/13.5 (Flipkart /
  Instamart / BigBasket / Blinkit): v15 rounds to ₹1 instead of psychological ₹10/₹50 steps, so there
  are fewer ties, and follower moves are coupled. The ordering is unchanged.
  `tests/test_regression_cheapest.py` records the new values and why.

### Rebuild and hashes (first 16 hex of sha256)

| File | v2 / pre-v15 | v15 |
|---|---|---|
| raw `Blinkit_RAW.parquet` | 4e04dffcac84b821 | **44f9441b8b53da0b** |
| raw `Instamart_RAW.parquet` | 42433edfe5aaffde | **fb33e5f7a7cec520** |
| raw `FlipkartMinutes_RAW.parquet` | 3b693b724ed785d2 | **a788a956ddcb83ed** |
| raw `BigBasket_RAW.parquet` | dcb4f7ba0c826bbd | **83de89b8f53b1d6a** |
| ml `Blinkit_ML_price.parquet` | a0dda89a340d541b | **607ea90b0ae739df** |
| ml `Instamart_ML_price.parquet` | bacc18da106a7eb4 | **3a48b19edf59b13b** |
| ml `FlipkartMinutes_ML_price.parquet` | 42f0736b9613d65e | **83d42d9f663ab688** |
| ml `BigBasket_ML_price.parquet` | 9a93f06e91efed6d | **ade377fbdbc1c167** |
| ml `ML_targets.parquet` | d157b3ff99511a23 | **134250d6ca5e9073** |
| `data/reference/ML_SCHEMA_v2.xlsx` (all 4 sheets regenerated) | 0855b16a88a6773e | **93fedb1c3acab0fd** |

`data/ml/` rebuilt with `python -m src.pipeline.build_features`: all leakage checks PASS, split
chronological (0 dates in two splits), 610,789 rows × 109 columns + 7 targets. Raw baseline updated
in `scripts/verify_raw_integrity.py` (PASS). Test suite: 35 passed (14 existing + 21 new). The 7
dynamics tests were also run against the archived v14 data, where all 7 fail, as they should.
