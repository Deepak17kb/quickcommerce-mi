# Product matcher v2: difference-aware features and constructed edits

Built 2026-10-13. Code: `src/matching/diff_features.py`, `edits.py`, `train_v2.py`. v1 is untouched and remains the
REAL-only model (`docs/MATCHER_v1.md`).

```
python -m src.matching.train_v2               # -> outputs/models/product_matcher_v2/ + product_matcher_v2_behaviour_check/
python -m src.matching.ai_review --model v2   # -> outputs/models/product_matcher_v2_ai_proxy_check/  (AI proxy, not tier 1)
```

## Status in one paragraph

v1 treats any textual difference as "different product". v2 fixes that on constructed edits and, against the one AI
reviewer, on real name variation: it finds 30% of the AI-same pairs at 84% precision where v1 finds 8% at 33%.
**Tier 1 is still NOT MEASURABLE: 0 human labels.** v2 trains on constructed edits, which are SYNTHETIC rows, so its
claim scope is SYNTHETIC-DERIVED. It abstains on a third of the unlabelled real pairs, and that abstention is part of
the model, not a convenience: without it the booster is confidently wrong on a whole class of pairs.

## The label-source decision

v1's write-up ended: training on constructed edits would be a new label source and a change of policy, not done
without the owner's decision. The owner was asked on 2026-09-25. Their reply of 2026-10-13 to the list of open items
was "whatever is open, start finishing it", which was taken as the go-ahead. v2 sits beside v1 and replaces nothing, so
the decision is reversed by deleting three files and two output folders.

The rule that bounds the new source: **an edit is used only when its effect on identity does not depend on a judgement
call.** That excludes word reordering ("Milk Chocolate" / "Chocolate Milk") and a variant bracket added to one side
("Goggles" / "Goggles (Black)"). Constructed pairs carry `label_source = CONSTRUCTED_EDIT` and `data_status =
SYNTHETIC`. They are never human labels and never tier 1.

## What changed

**Features (`diff_features.py`).** v1 measures how much two names differ. v2 adds 18 features that say what differs.
Shared tokens are cancelled; a leftover token on one side is paired with one on the other when they are one edit apart
and at least one is rare in the catalog (a typo; "mint" / "mini" are two common words and stay a substitution); what
remains is a substitution if both sides have residue and an insertion if only one does. Each is counted, located (in a
bracket or not) and typed (number, variant-lexicon word, rarity).

**Labels (`edits.py`).** 21 edit kinds in 7 families, applied to REAL catalog records from TRAIN keys only, up to
1,500 per kind (26,598 pairs), added to v1's 25,388 auto-labelled training pairs.

| Family | Edits | Product |
|---|---|---|
| formatting | markup, case, punctuation, spacing, & ↔ and | same |
| typos | transposition, dropped letter, doubled letter | same |
| alias bracket | a local-name bracket appended ("Amla" / "Amla (Aula)") | same |
| pack respelled | g ↔ gm, 1 kg ↔ 1000 g | same |
| pack changed | quantity scaled, single → multipack | different |
| number changed | a number in the name doubled or shifted | different |
| variant word swapped | colour, size, flavour, audience, a random catalog word | different |

Blocking, the rules R1–R4, the key split (hash + 564 reserved evaluation keys) and the LightGBM settings are v1's. The
ablation's v1 cell reproduces the saved v1 model exactly (max difference 0.0 on 11,834 pairs).

## Results

### 1. Which half matters: a 2 × 2 ablation

Edits of held-out REAL records (test keys, 11,338 pairs).

| Features | Labels | Same-product edits passed | Different-product edits passed | AUC, same vs different name edits |
|---|---|---|---|---|
| v1 | v1 | 40.7% | 99.7% | 0.32 |
| v1 | + constructed | 97.8% | 97.7% | 0.992 |
| v2 | v1 | 40.7% | 99.7% | 0.39 |
| **v2** | **+ constructed** | **99.9%** | **100.0%** | **1.000** |

Labels do the work. New features without new labels change nothing: the model has never seen a positive that varies.
The bottom row is close to circular, since the model was trained on the generator that wrote the test. The next table
is the one that is not.

### 2. Generalisation: a whole family withheld from training

| Family never trained on | Must be | v2 features | v1 features, same labels |
|---|---|---|---|
| formatting | same | 100.0% | 59.8% |
| typos | same | 99.4% | 65.9% |
| pack respelled | same | 99.6% | 99.6% |
| pack changed | different | 99.2% | 99.2% |
| number changed | different | 85.3% | 3.5% |
| variant word swapped | different | 98.6% | 9.6% |
| **alias bracket** | same | **0.3%** | 1.7% |

This is where the difference-aware features earn their place. With the same constructed labels, similarity features
memorise each edit family and fail on one they were not shown; the features that say what differs carry over. The
alias row is the honest exception: neither model generalises to it. "A one-word bracket added to one side names the
same product" is taught, not learned, and it rests on a catalog convention and five alias words.

### 3. No regression on v1's checks

Held-out auto labels F1 1.00 (v1 1.00). Tier 2, same key across SYNTHETIC platforms: 100% (2,000 pairs). Tier 3,
random different-key pairs: 1 false positive in 75,033 (v1: 0).

### 4. The gate

The only insertions v2 was shown are alias brackets. So the booster scores every pair where one name simply says
more as the same product:

| Pair (both REAL, same pack) | Booster |
|---|---|
| Amul Dark Chocolate Bar / Amul Sugar Free Dark Chocolate Bar | 0.9996 |
| Johnson's Baby Powder / Johnson's Blossoms Baby Powder | 1.0000 |
| Cadbury Dairy Milk Milk Chocolate Bar / Cadbury Dairy Milk Silk Bubbly Milk Chocolate Bar | 1.0000 |

Nothing can be constructed to fix this honestly. Whether an added word changes the product is a judgement call:
"Fresh" does not, "Sugar Free" does. So each pair gets a difference signature, and v2 gives a decision only when at
least 25 training pairs share it. Otherwise it **abstains**. `pred_lightgbm` in the saved output is the gated decision.

On the 11,834 unlabelled REAL pairs: 7,847 different, 70 same, **3,917 abstain** (33.1%). The ungated booster would
have called 410 of the abstained pairs the same. `out_of_support_patterns.csv` lists the uncovered patterns by size;
they are where a human label is worth most.

### 5. Against the AI reviewer (AI proxy, NOT tier 1)

Scored once, after the design above was fixed. 236 pairs with real name variation, 53 AI-same; chance PR-AUC 0.225.

| | Precision | Recall | F1 | False-positive rate | PR-AUC |
|---|---|---|---|---|---|
| v1 | 0.33 | 0.08 | 0.12 | 4.4% | 0.222 |
| String-similarity baseline | 0.29 | 0.09 | 0.14 | 6.6% | 0.228 |
| **v2, gated** | **0.84** | 0.30 | 0.44 | **1.6%** | 0.705 |
| v2, in-support pairs only (148 pairs, 20 AI-same) | 0.84 | 0.80 | 0.82 | 2.3% | 0.782 |
| v2 booster, ungated | 0.66 | 0.91 | 0.76 | 13.7% | 0.705 |
| v1 features + constructed labels, ungated | 0.63 | 0.77 | 0.70 | 13.1% | 0.831 |

F1 difference against the baseline, paired bootstrap 95% CI: 0.11 to 0.48.

What the gate costs and buys, per this reviewer: it withholds 54 "same" calls on 88 abstained pairs, of which the AI
agrees with 32 (59%). 33 of the 53 AI-same pairs sit behind it, which is why gated recall is 30%.

Two things this table does **not** show. First, the ungated v1-feature model ranks pairs better against this reviewer
than v2 does (PR-AUC 0.83 against 0.71), because v2's booster is at 1.0 on the insertion pairs the reviewer splits
59/41. Choosing between them is a question for human labels, not for this proxy. Second, none of it is evidence about
the matcher until the AI reviewer's agreement with humans is measured (`human_agreement`: 0 pairs).

## A correction to the v1 write-up

`docs/MATCHER_v1.md` and CLAUDE.md §8 said v1 recalls 0 of 53 AI-same pairs with PR-AUC 0.25. The saved output of the
2026-09-25 run says 4 of 53 (7.5%) and 0.222; the text had been written from an earlier run. Both are corrected. The
conclusion is unchanged: v1 is at chance on real name variation.

## What would make it real

1. Label the priority batch on the review page (0 labels on 2026-10-13). The 88 abstained name-variation pairs matter
   most: they decide whether "one name says more" is usually the same product.
2. `python -m src.matching.import_labels <export>`, then `train`, `train_v2`, and both `ai_review` runs. Human labels
   enter v2's training as `human_reviewed`, uncovered signatures gain support, and the gate opens where it should.
3. Only then choose between the v1-feature and v2-feature models, and only then consider embeddings.

## Tests

`tests/test_matching.py`: the features on hand-made pairs, the edits, the family map, the gate, the scope, and the
guard that no training module reads the AI review (now including `train_v2.py`, `diff_features.py`, `edits.py`).
