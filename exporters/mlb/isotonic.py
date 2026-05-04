"""
Isotonic regression via Pool Adjacent Violators (PAV).
======================================================
Ported from edge-equation-v1 (src/edge_equation/math/isotonic.py)
and adapted to v2 conventions. The PAV implementation is unchanged —
it's pure-stdlib math with no data dependencies, so it survives the
v1→v2 transition cleanly.

Why PAV: deterministic, closed-form, no RNG, no hyperparameters
beyond the direction (mono vs anti-mono). For v2 we use it as a
candidate replacement for the linear logistic-slope calibration in
exporters/mlb/backtest.py — isotonic can correct non-linear
miscalibration that a single-parameter sigmoid can't.

Algorithm:
    1. Sort (x, y, w) by x ascending.
    2. Walk left-to-right. Keep a stack of "blocks", each a
       (left_x, right_x, mean_y, total_w).
    3. Push each new point as its own block.
    4. If the new block's mean_y is less than the previous block's
       mean_y (a violation of monotonicity), pop and merge into one
       block whose mean_y is the weighted average. Repeat until the
       stack is monotone.
    5. Final stack is the isotonic fit. To predict at an arbitrary x,
       locate the block whose [left_x, right_x] contains x; otherwise
       extrapolate to the first / last block's mean_y, or linearly
       interpolate across gaps between blocks.

Typical use inside Edge Equation v2: take raw (predicted_prob,
realized_outcome) pairs from backtest history and fit a monotone
calibration curve. Apply the fit to future predicted probabilities
to get calibrated fair probs.

Source: https://github.com/EdgeCash/edge-equation-v1/blob/main/src/edge_equation/math/isotonic.py
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class IsotonicBlock:
    """One merged pool of training points: monotone-respecting sub-region."""
    left_x: Decimal
    right_x: Decimal
    mean_y: Decimal
    total_weight: Decimal

    def to_dict(self) -> dict:
        return {
            "left_x": str(self.left_x),
            "right_x": str(self.right_x),
            "mean_y": str(self.mean_y),
            "total_weight": str(self.total_weight),
        }


@dataclass(frozen=True)
class IsotonicFit:
    """Full fit: an ordered tuple of merged blocks."""
    blocks: Tuple[IsotonicBlock, ...]
    increasing: bool

    def to_dict(self) -> dict:
        return {
            "increasing": self.increasing,
            "blocks": [b.to_dict() for b in self.blocks],
        }


class IsotonicRegressor:
    """Pool-adjacent-violators fit + predict.

    Stateless static methods so callers don't have to manage instance
    lifecycle — fit() returns an immutable IsotonicFit which is
    everything you need to predict.
    """

    @staticmethod
    def _to_decimal(v) -> Decimal:
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @staticmethod
    def fit(
        xs: Sequence,
        ys: Sequence,
        weights: Optional[Sequence] = None,
        increasing: bool = True,
    ) -> IsotonicFit:
        if len(xs) != len(ys):
            raise ValueError(
                f"xs and ys must be equal length, got {len(xs)} vs {len(ys)}"
            )
        if len(xs) == 0:
            return IsotonicFit(blocks=tuple(), increasing=increasing)
        if weights is not None and len(weights) != len(xs):
            raise ValueError(
                f"weights must match xs length, got {len(weights)} vs {len(xs)}"
            )

        xs_d = [IsotonicRegressor._to_decimal(x) for x in xs]
        ys_d = [IsotonicRegressor._to_decimal(y) for y in ys]
        ws_d = (
            [IsotonicRegressor._to_decimal(w) for w in weights]
            if weights is not None else [Decimal('1')] * len(xs_d)
        )
        for w in ws_d:
            if w <= Decimal('0'):
                raise ValueError(f"weights must be strictly positive, got {w}")

        # Stable sort on x ascending.
        order = sorted(range(len(xs_d)), key=lambda i: xs_d[i])
        xs_s = [xs_d[i] for i in order]
        ys_s = [ys_d[i] for i in order]
        ws_s = [ws_d[i] for i in order]

        # For decreasing fit, flip signs on y before running PAV then flip back.
        if not increasing:
            ys_s = [-y for y in ys_s]

        stack: List[IsotonicBlock] = []
        for i in range(len(xs_s)):
            block = IsotonicBlock(
                left_x=xs_s[i],
                right_x=xs_s[i],
                mean_y=ys_s[i],
                total_weight=ws_s[i],
            )
            stack.append(block)
            # Merge while:
            # (a) the new block shares an x with the previous block
            #     (same-x samples always pool — otherwise predict(x) is
            #     ambiguous), OR
            # (b) the new block's mean_y is less than the previous block's
            #     (classic PAV violation).
            while len(stack) >= 2 and (
                stack[-1].left_x == stack[-2].right_x
                or stack[-1].mean_y < stack[-2].mean_y
            ):
                b2 = stack.pop()
                b1 = stack.pop()
                total_w = b1.total_weight + b2.total_weight
                new_mean = (
                    (b1.mean_y * b1.total_weight + b2.mean_y * b2.total_weight)
                    / total_w
                )
                stack.append(IsotonicBlock(
                    left_x=b1.left_x,
                    right_x=b2.right_x,
                    mean_y=new_mean.quantize(Decimal('0.000001')),
                    total_weight=total_w,
                ))

        if not increasing:
            stack = [
                IsotonicBlock(
                    left_x=b.left_x, right_x=b.right_x,
                    mean_y=-b.mean_y, total_weight=b.total_weight,
                )
                for b in stack
            ]

        return IsotonicFit(blocks=tuple(stack), increasing=increasing)

    @staticmethod
    def predict(fit: IsotonicFit, x) -> Decimal:
        if not fit.blocks:
            return Decimal('0').quantize(Decimal('0.000001'))
        xv = IsotonicRegressor._to_decimal(x)
        first = fit.blocks[0]
        last = fit.blocks[-1]
        if xv <= first.left_x:
            return first.mean_y.quantize(Decimal('0.000001'))
        if xv >= last.right_x:
            return last.mean_y.quantize(Decimal('0.000001'))
        # Locate the block containing x. Linear scan is fine for the
        # sizes we use (fewer than a few thousand blocks in backtest
        # windows).
        for i, block in enumerate(fit.blocks):
            if block.left_x <= xv <= block.right_x:
                return block.mean_y.quantize(Decimal('0.000001'))
            # Gap between block i and block i+1: linearly interpolate
            # between their mean_ys across the gap, so the fit is a
            # continuous step with straight-line connectors (typical
            # sklearn behavior).
            if i + 1 < len(fit.blocks):
                nxt = fit.blocks[i + 1]
                if block.right_x < xv < nxt.left_x:
                    span = nxt.left_x - block.right_x
                    if span == Decimal('0'):
                        return block.mean_y.quantize(Decimal('0.000001'))
                    t = (xv - block.right_x) / span
                    val = block.mean_y + t * (nxt.mean_y - block.mean_y)
                    return val.quantize(Decimal('0.000001'))
        # Shouldn't reach here given the bracketing above; safe fallback.
        return last.mean_y.quantize(Decimal('0.000001'))

    @staticmethod
    def predict_batch(fit: IsotonicFit, xs: Iterable) -> List[Decimal]:
        return [IsotonicRegressor.predict(fit, x) for x in xs]
