"""Product matcher (model 1): do two REAL Blinkit listings refer to the same product?

    python -m src.matching.blocking   # candidate pairs + blocking recall
    python -m src.matching.labels     # labels with provenance + data/reference/MATCH_REVIEW_QUEUE.csv
    python -m src.matching.train      # LightGBM vs baseline, three evaluation tiers, saved via the output contract

See docs/MATCHER_v1.md.
"""
from src.matching.blocking import (BlockingConfig, audit_recall, base_name, candidate_pairs, normalize_name,
                                   parse_pack, perturbation_recall, product_records, real_listings)
from src.matching.features import PairFeaturizer, pair_frames
from src.matching.labels import LabelConfig, build as build_labels, provenance_counts, write_review_queue

__all__ = [
    'BlockingConfig', 'audit_recall', 'base_name', 'candidate_pairs', 'normalize_name', 'parse_pack',
    'perturbation_recall', 'product_records', 'real_listings',
    'PairFeaturizer', 'pair_frames',
    'LabelConfig', 'build_labels', 'provenance_counts', 'write_review_queue',
]
