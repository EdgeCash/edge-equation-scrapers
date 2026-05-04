"""
Cross-validation helpers for analysis scripts.
==============================================
Pure-stdlib utilities used by run_isotonic_compare.py + run_elo_compare.py
to estimate Brier-score variance across time-ordered folds.

Why time-series CV vs random k-fold:
- Random k-fold splits leak future information into training data —
  fine for IID data, wrong for sports betting where today's predictions
  must use only PRIOR games.
- TimeSeriesSplit (the pattern from sklearn) walks forward through the
  history: fold 0 trains on the first N/(K+1) games and tests on the
  next chunk; fold 1 trains on the first 2N/(K+1) and tests on the
  next; etc. Train data is strictly before test data in every fold.

Why estimate Brier across folds instead of one split:
- A single 80/20 split gives one Brier number with no error bar — we
  can't tell signal from noise. Yesterday's isotonic +0.53% and ELO
  +0.94% findings are both small enough that their significance
  depends on the across-time variance.
- 5 folds → 5 Brier numbers per method → mean ± std → real confidence
  interval. If two methods' CIs overlap, apparent difference is noise.
"""

from __future__ import annotations

import math
from typing import Iterator


def time_series_split(n: int, n_splits: int = 5) -> Iterator[tuple[list[int], list[int]]]:
    """Yield (train_indices, test_indices) tuples for time-series CV.

    Each fold's train data is strictly before its test data — the
    standard sklearn TimeSeriesSplit pattern in ~10 lines of stdlib.

    For n=10000, n_splits=5:
      fold 0: train [0..1666],  test [1666..3333]
      fold 1: train [0..3333],  test [3333..5000]
      fold 2: train [0..5000],  test [5000..6666]
      fold 3: train [0..6666],  test [6666..8333]
      fold 4: train [0..8333],  test [8333..10000]
    """
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")
    fold_size = n // (n_splits + 1)
    if fold_size < 10:
        raise ValueError(
            f"too few samples ({n}) for {n_splits}-fold CV — "
            f"each fold would have <10 test samples"
        )
    for i in range(n_splits):
        test_start = (i + 1) * fold_size
        test_end = (i + 2) * fold_size if i < n_splits - 1 else n
        train_idx = list(range(0, test_start))
        test_idx = list(range(test_start, test_end))
        yield train_idx, test_idx


def stats(values: list[float]) -> dict:
    """Mean, sample standard deviation, and 95% CI half-width of a list.

    The half-width is std/sqrt(n) * 1.96 (normal approximation), which is
    fine for n>=5 folds when the underlying Brier values are reasonably
    bell-shaped across folds. For n<5, treat the CI as an approximation
    of "is this gap real."
    """
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "ci_half": 0.0,
                "min": 0.0, "max": 0.0}
    mean = sum(values) / n
    if n < 2:
        return {"n": 1, "mean": mean, "std": 0.0, "ci_half": 0.0,
                "min": mean, "max": mean}
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std = math.sqrt(variance)
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "ci_half": 1.96 * std / math.sqrt(n),
        "min": min(values),
        "max": max(values),
    }
