"""Community rating — closer to AtCoder's aggregation, adapted for a small group.

Per-contest PERFORMANCE (still ours, not opponent-strength calibrated — that needs a
large population): blends placement + achievement, then shaped by the contest FORMAT
(speed capped so it can't be farmed; hardcore floored so a loss barely hurts).

Aggregation into a rating follows AtCoder's math faithfully:
- recency-weighted mean in the 2^(perf/S) domain (weight 0.9^i, i = 1 for newest),
- the finite-contest downward correction (初回補正) → newcomers rated lower, → 0 as n→∞,
- a low-end smoothing so ratings stay positive.
On top of AtCoder we keep an inactivity DECAY (half-life) so idle ratings fade.
It only changes when you participate, so skipping never lowers you relative to others.
"""
from __future__ import annotations

import math

RECENCY_WEIGHT = 0.9        # i-th most recent performance weighted 0.9^i
HALF_LIFE_DAYS = 30.0       # inactivity half-life for the decay
PERF_SCALE = 2000           # performance range ~[0, 2000]
AGG_SCALE = 800             # 2^(perf/AGG_SCALE) aggregation base (AtCoder uses 800)
CORR_SCALE = 1200           # finite-sample correction magnitude (AtCoder constant)

# √(Σ_{i≥1} 0.81^i) / Σ_{i≥1} 0.9^i  — the n→∞ limit the correction subtracts to.
_INF_CORR = math.sqrt(0.81 / (1 - 0.81)) / (0.9 / (1 - 0.9))


def performance(rank: int, field: int, points: int, max_points: int,
                perf_cap: float | None = None, loss_floor: float = 0.0) -> int:
    """Performance for one contest, shaped by the format.

    rank: 1 = best. field: number of ranked participants. points/max_points: how much
    of the contest the user solved. Blends placement (60%) + achievement (40%).
    `loss_floor` lifts the low end (hardcore: 負けより勝ち); `perf_cap` caps the top
    (speed: 荒稼ぎ防止). Both are fractions of the [0,1] base.
    """
    placement = (field - rank) / (field - 1) if field > 1 else 1.0
    achievement = (points / max_points) if max_points else 0.0
    base = 0.6 * placement + 0.4 * achievement          # in [0, 1]
    if loss_floor:
        base = loss_floor + (1.0 - loss_floor) * base   # remap into [loss_floor, 1]
    if perf_cap is not None:
        base = min(base, perf_cap)
    return round(PERF_SCALE * base)


def _finite_correction(n: int) -> float:
    """AtCoder's small-sample downward correction; large for n=1, → 0 as n→∞."""
    s81 = sum(0.81 ** i for i in range(1, n + 1))
    s9 = sum(0.9 ** i for i in range(1, n + 1))
    return CORR_SCALE * (math.sqrt(s81) / s9 - _INF_CORR)


def _smooth_low(r: float) -> float:
    """Keep ratings positive: below 400 they asymptote toward 0 (AtCoder-style)."""
    if r >= 400.0:
        return r
    return 400.0 / math.exp((400.0 - r) / 400.0)


def compute(perfs_recent_first: list[int], last_epoch: int, now: int) -> dict | None:
    """Aggregate a user's performances (most-recent first) into a rating.

    Returns {raw, rating, n, days_inactive, decay} or None if no performances.
    `raw` is the AtCoder-style corrected rating (pre-decay); `rating` applies the
    inactivity decay and low-end smoothing.
    """
    if not perfs_recent_first:
        return None
    n = len(perfs_recent_first)
    num = den = 0.0
    for i, p in enumerate(perfs_recent_first):
        w = RECENCY_WEIGHT ** (i + 1)
        num += w * (2.0 ** (p / AGG_SCALE))
        den += w
    r_agg = AGG_SCALE * math.log2(num / den)
    raw = r_agg - _finite_correction(n)
    days = max(0.0, (now - last_epoch) / 86400.0)
    decay = 0.5 ** (days / HALF_LIFE_DAYS)
    rating = _smooth_low(raw * decay)
    return {
        "raw": round(raw),
        "rating": round(rating),
        "n": n,
        "days_inactive": days,
        "decay": decay,
    }
