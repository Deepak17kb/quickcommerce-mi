# Product matcher v1 (model 1)

Question: do two REAL Blinkit listings refer to the same real product ("Amla" vs "Amla (Aula)")?
This is the only model in the project trained on real data. Built 2026-09-17. Code: `src/matching/`.
Run: `python -m src.matching.train`. Outputs: `outputs/models/product_matcher/` (REAL) and
`outputs/models/product_matcher_crossplatform_checks/` (SYNTHETIC evaluation tiers), booster `models/product_matcher_v1.txt`,
review queue `data/reference/MATCH_REVIEW_QUEUE.csv`.

## Status in one paragraph

The pipeline is complete and verified: widened blocking, features, labels with provenance, a group split, LightGBM, a baseline,
three evaluation tiers and contract outputs. **The model's ability to match real name variation is NOT measured yet,** because no
labelled example of it exists. Every verified positive (the 2,419 `CANONICAL_KEY_AUDIT` groups) compares two identical catalog
records. **There is no valid claim that LightGBM beats the string-similarity baseline.** The next step is human work: label
`data/reference/MATCH_REVIEW_PRIORITY.csv` (297 pairs; `label` 1 = same product, 0 = different), then re-run, and tier 1 is
measured automatically. The saved outputs are from the run before R4 and the reserved-key split; re-run after labelling.

## 1. Blocking (`blocking.py`, `config.yaml :: matching.blocking`)

Unit: the catalog product (canonical key). Every attribute a feature uses is identical across the listings of one key, so
different-key listing pairs are duplicates of the key pair.

| | |
|---|---|
| REAL listings used | 21,945 (21,949 minus 4 unnamed listings) |
| Products (canonical keys) | 12,188 |
| Methods | `char_ngram` (TF-IDF char 3-grams on the bracket-stripped name, top-10, cosine ≥ 0.6) + `token` (≥ 2 shared tokens with document frequency ≤ 50, Jaccard ≥ 0.5). `sorted_neighbourhood` is implemented but off: +27k pairs, no recall gain |
| Candidate product pairs | **25,334** (char_ngram 23,680 · both 1,566 · token 88) — 140,812 listing pairs equivalent incl. 17,054 same-key listing pairs |
| Old strategy | exact base name + pack: 364 pairs; widened blocking contains **100%** of them |
| **Recall vs CANONICAL_KEY_AUDIT** | **3,581 / 3,581 = 100%**. Caveat: structural — every audit pair has identical names, so this cannot fail and says nothing about hard cases |
| **Recall on name variation (stress test)** | **99.7%** of 1,500 perturbed real names (strip bracket 100%, add alias bracket 100%, `**` markup 100%, typo 100%, word swap 99.6%, drop last word 98.9%). Perturbations are used for blocking measurement only, never as labels |

## 2. Features (`features.py`)

18 features, all guarded by `src.load.check_feature_set`: Jaro-Winkler, token Jaccard and char-3-gram TF-IDF cosine on the full
and the bracket-stripped name; token-set ratio; bracket presence and bracket-text Jaccard; base-name length ratio; pack exact
match, parsed pack quantity ratio and dimension compatibility; brand match and brand-known; category and subcategory match.

**Raw data defect found (not fixed yet: `data/raw/` is frozen; fix proposed as raw patch v3).** 370 products, 9,099 rows
(819 REAL, 8,280 SYNTHETIC), identical in `data/raw/` and `data/ml/`:
- 166 products / 4,426 rows: `**…**` pack strings stored as `pack_qty` 1.0 (unit_price inflated ~200× median).
- 178 products / 4,200 rows: same-unit combos (`60 g + 40 g`) stored as the first component only.
- 27 products / 473 rows: same-unit combos stored as corrupt values (`1 ltr + 3 x 225 ml` → 225,000).
The matcher parses the pack text itself (`blocking.parse_pack`, 99.3% parse rate) and never uses raw `pack_qty` / `pack_unit`.

## 3. Labels (`labels.py`) — no label is ever guessed

| Provenance | Pairs | Source |
|---|---|---|
| `auto_positive` | **3,718** | 3,581 listing pairs in verified `CANONICAL_KEY_AUDIT` groups (all identical records) + **137 R4** markup-only pairs: names identical once `**` is stripped (case kept), packs equal by the corrected parser, brand and category equal. R4 pairs are feature-identical to identical records too (features normalise markup), so they add labels, not name-variation signal. 22 more formatting-only pairs fail R4 because the v14 brand extraction differs (`Amul Kool` vs `Amul`) and stay in review |
| `auto_negative` | **45,469** | R1 different category + different pack + dissimilar name (11,343); R2 pack variant, same unit, ≥ 5% quantity difference = different SKU by project definition (14,233); R1+R2 (5,496); R3 same pack + different category + dissimilar name (14,397) |
| `human_reviewed` | **0** | `MATCH_REVIEW_PRIORITY.csv` (and `MATCH_REVIEW_QUEUE.csv`); conflicting labels between the two are dropped |
| `needs_review` | **11,834** | every other candidate pair → review queue (was 11,971 before R4) |

Rule history, stated plainly:
- **R2 was corrected before training.** It first used raw `pack_qty`, which labelled `**180 ml**` vs `180 ml` as different: a
  fabricated label. It now parses the pack text and requires the normalised pack strings to differ.
- **R3 was added after the first training run learned a shortcut.** Every positive shares its pack and almost no negative did, so
  LightGBM put 116k gain on `pack_exact` and ~0 on name similarity. It flagged 2.1% of random cross-platform pairs (3,212) as
  matches (baseline 0%) and called 70% of unlabelled hard pairs matches. R3 supplies rule-certain same-pack negatives. Afterwards
  the model relies on `jw_full` (gain 150k) and the random-pair false-positive rate is 0.

Review queue: 11,834 pairs (after R4), ordered by formatting-only differences first (22 left after R4), then same pack, then
highest name similarity. For labelling, use the 297-pair priority batch instead (below). It lists both names, packs, brands, categories and similarity scores, with empty `label` and
`reviewer_note` columns. Re-running never overwrites a filled label.

## 4. Split — by canonical_product_key group

Keys are assigned to test by a stable hash (`md5(seed:key) < 0.25`, independent of which pairs are labelled) **plus every key in
`MATCH_REVIEW_PRIORITY.csv` (564 reserved evaluation keys)**. Pairs straddling the split are dropped. Adding human labels does
not change the training set (25,388 train pairs with or without the batch labelled). The table below is the v1 run from before R4
and the reserved keys; re-running `train` after labelling reproduces the current split.

| | |
|---|---|
| Keys | 12,096 (3,024 test) |
| Train / test pairs | 28,268 / 3,791 |
| Straddling pairs dropped | 16,991 |
| **Keys in both train and test** | **0** |

For comparison, a row-level random split of the same pairs puts 5,945 of 6,570 test keys (90%) into training too.

## 5. Evaluation — three tiers, never blended

LightGBM threshold 0.5. Baseline: `ngram_cos_full ≥ 0.9802` (threshold chosen by max F1 on the train split).

### Tier 1 — MAIN: real Blinkit name variation

**NOT MEASURABLE: 0 human-reviewed pairs.** Tier 1 is measured only on `human_reviewed` test pairs (≥ 30 per class).

### Pipeline check on held-out auto labels — NOT tier 1

| | precision | recall | F1 | PR-AUC |
|---|---|---|---|---|
| LightGBM | 1.000 | 1.000 | 1.000 | 1.000 |
| Baseline | 0.959 | 1.000 | 0.979 | 0.967 |

3,791 test pairs (921 identical-record positives, 2,870 rule negatives). These numbers only show the pipeline works. They are
**not a valid comparison**: the positives are identical records. On the 790 hard pack-variant negatives, the false-positive rate is
LightGBM 0% vs baseline 4.9%. That partly reflects the model reproducing the R2 labelling rule (which is defined by pack size), not
independent evidence.

### Tier 2 — SANITY CHECK (synthetic, byte-copied names)

12,000 same-key cross-platform pairs; names 100% byte-identical. LightGBM match rate **100%**, baseline **100%**.
Proves no bug. **Not evidence of cross-platform matching ability.**

### Tier 3 — NEGATIVE DISCRIMINATION (synthetic cross-platform, different keys)

| Pair set | n | LightGBM FP rate | Baseline FP rate |
|---|---|---|---|
| Random cross-platform pairs | 150,139 | **0.000%** (0 pairs) | 0.000% |
| Hard rule-negative pairs (pack variants on different platforms) | 1,340 | **0.0%** | 4.8% |
| Hard unlabelled pairs (upper bound: truth unknown) | 1,212 | 1.0% predicted match | 1.2% predicted match |

On the 11,971 unlabelled real `needs_review` pairs the model predicts a match for 1.3% (baseline 1.7%). This is behaviour, not
accuracy.

## 6. Verdict

**No valid claim that LightGBM beats the string-similarity baseline.** Tier 1 is not measurable, and auto-label scores are
uninformative. Both methods are clean on random negatives (0 false positives in 150k). LightGBM additionally rejects pack variants,
which the name-only baseline cannot see, but that advantage is partly circular (see above).

## Priority labelling batch (`priority.py`, 2026-09-17)

`data/reference/MATCH_REVIEW_PRIORITY.csv`: **297 pairs, 564 product keys, all reserved as test keys.** Why not only pairs already
in the test split: a pair is a test pair only if both keys are test keys (~6% of pairs), and true same-product pairs with different
keys are rare. Only 9 of the 157 heuristic "likely same" pairs had both keys in the hash test split, which cannot give 30 positives.
Trade-off: tier 1 measures review-selected, harder-than-random pairs.

| Stratum | Pairs | Selection (similarity features only, never label values) |
|---|---|---|
| L_likely_same | 157 (all) | same pack AND identical after markup/case normalisation (22) / bracket text on one side only (59) / identical token set (31) / Jaro-Winkler ≥ 0.97 (45) |
| M_ambiguous | 100 | same pack, char-n-gram cosine 0.75–0.97, 25 per 0.05 bin, one pair per key |
| N_hard_contrast | 40 | same base name with different bracket text (20) + different pack with cosine ≥ 0.80 (20), one pair per key |

Label only this file (`label` 1 = same product, 0 = different). `python -m src.matching.priority --status` counts progress.
Tier 1 needs ≥ 30 of each class. L is where positives are but it mixes aliases with size/colour siblings, so there is no guarantee
of 30 positives until labelled. If positives fall short, a top-up batch is needed before training.

## Review page, label import and the AI proxy (2026-09-25)

**Review page** (`scripts/build_review_page.py` -> `outputs/showcase/match_review.html`, published as the private artifact
"Product Match Review"). All 297 pairs, blind by design: names, packs, brands and categories only; no stratum, selection
reason or score, in a fixed shuffled order. Each decision is saved in the page's store as `labels/r<row>`.
**Import:** `python -m src.matching.import_labels <export>` writes decisions into `MATCH_REVIEW_PRIORITY.csv` exactly as the
terminal reviewer does. It checks that the stored pair text matches the CSV row, keeps an existing label unless `--relabel`,
and holds back decisions from anyone but the page owner unless `--allow-editors`. Labels on the page as of 2026-09-25: **0**.

**AI proxy — NOT tier 1, NOT human labels.** `src/matching/ai_review_data.txt` is Claude's (claude-opus-5-5) blind review of
the same 297 pairs, done the way the page shows them: 76 same, 183 different, 38 unsure. No labelling or training module reads it
(`tests/test_matching.py` enforces this). `python -m src.matching.ai_review` scores the saved matcher outputs against it, with no
retraining -> `outputs/models/product_matcher_ai_proxy_check/`. Results against one AI reviewer:

| 259 AI-labelled pairs | Precision | Recall | F1 | PR-AUC |
|---|---|---|---|---|
| LightGBM (all pairs) | 0.76 | 0.34 | 0.47 | 0.56 |
| Baseline (all pairs) | 0.70 | 0.37 | 0.48 | 0.45 |
| LightGBM, **name variation only** (236 pairs, 53 AI-same) | 0.33 | **0.08** | 0.12 | 0.22 |
| Baseline, name variation only | 0.29 | 0.09 | 0.14 | 0.23 |

*Corrected 2026-10-13 from `outputs/models/product_matcher_ai_proxy_check/metrics.json` (run of 2026-09-25). The table
first read 1.00 / 0.29 / 0.45 / 0.59 and 0.00 / 0.00 / 0.00 / 0.25: it had been written from an earlier run and was not
updated when the model was retrained that day. The conclusion does not change.*

Chance PR-AUC on the name-variation subset is 0.225. "Name variation only" removes the 23 pairs whose name and pack are
identical after stripping case, markup and punctuation (a mechanical rule, not the AI's call). The whole-batch PR-AUC lead of
LightGBM (difference CI 0.03-0.17) comes from those trivial pairs. On the rest, LightGBM finds 4 of the 53 AI-same pairs and gives almost all the others
a probability of about 0: the "local name in brackets" pairs (Amla vs Amla (Aula)), word order, plurals, and a reworded
attribute. Both methods **behave close to exact-match detectors** against this reviewer. That is what training on identical-record positives predicts
(section 2). It is still a hypothesis about the matcher, not a measurement: it becomes evidence only once the AI's agreement with
human labels (`human_agreement`, Cohen's kappa, at least 20 overlapping pairs) is measured.

Stratum was hidden from the AI reviewer. Its labels still fall where the strata predict: L_likely_same 66 S / 63 D / 28 U,
M_ambiguous 5 / 92 / 3, N_hard_contrast 5 / 28 / 7. This is a consistency check, not validation.

## Behavioural test: no labels at all (2026-09-25)

`python -m src.matching.behaviour` -> `outputs/models/product_matcher_behaviour_check/`. Takes 600 REAL catalog records per
edit, applies one edit whose effect on product identity is known **by construction**, and scores (original, edited) with the
saved booster. This is the CheckList method (Ribeiro et al., 2020): no human, AI or rule labels. Before anything else, the
reloaded booster plus refitted featurizer must reproduce 2,000 saved trainer probabilities (max difference 0.0). Edited names
are constructed text, so rows are SYNTHETIC. Pass rates describe behaviour, not accuracy on real pairs, and are not tier 1.

| Edit | Must be | LightGBM pass | Baseline pass |
|---|---|---|---|
| control (unchanged) / markup / UPPER CASE | same | 100% / 100% / 100% | 100% / 100% / 100% |
| punctuation removed | same | **0%** | 24% |
| one-letter typo | same | **0.8%** | 0% |
| local-name alias appended, "Amla (Aula)" | same | **0%** | 0% |
| pack doubled | different | 100% | 0% (name only, by design) |
| number in name doubled | different | 100% | 99% |
| colour word swapped | different | 100% | 100% |

LightGBM passes only the edits that normalisation erases before it sees them. Any other textual difference means "different".
The threshold is not the problem. Threshold-free AUC for an identity-preserving name edit (punctuation, typo, alias) scoring
above an identity-changing one (number, colour) is **0.42 for LightGBM and 0.44 for the baseline, below chance**. A typo or
an alias moves the string further than "Black" -> "White" does. Similarity measures how much text differs; identity depends on
what differs. A v2 therefore needs two things: difference-aware features (which tokens differ, and whether each is a number,
colour, size, variant word, alias or typo) and training positives that contain name variation. Human labels supply the
second. Constructed edits could too, but that would be a new label source and a change to the label policy in `labels.py`;
it is not done here. The guards in `tests/test_matching.py` pin v1's behaviour as documented, so a v2 must update them
deliberately. **v2 was built on 2026-10-13 after the owner's go-ahead, beside v1: `docs/MATCHER_v2.md`.**

This agrees with the AI proxy above, which reached the same pattern by a different route. Two independent routes to one
conclusion is stronger than either alone. Neither is tier 1.

## What would make it real

1. Label `MATCH_REVIEW_PRIORITY.csv` (297 pairs) on the review page or with `python -m src.matching.review`, and import the
   page's labels with `python -m src.matching.import_labels`. At least 30 same and 30 different are needed. If the AI proxy is
   a guide, the batch holds enough positives (76 AI-same), but only human labels count.
2. Re-run `python -m src.matching.train`. Human labels become `human_reviewed`, enter training, and tier 1 is reported with
   LightGBM vs baseline.
3. Re-run `python -m src.matching.ai_review` to measure AI-human agreement. Kappa decides whether the AI proxy findings
   above can be quoted as more than a hypothesis.
4. Only then consider the embeddings / FAISS upgrade (out of scope for v1).
