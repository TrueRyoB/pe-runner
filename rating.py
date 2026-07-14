"""Community rating — AtCoder-inspired, adapted for a small group.

Principles (from AtCoder / AHC):
- Rating is an aggregate of your per-contest PERFORMANCES, weighting recent
  contests more (weight 0.9^i). It only changes when you actually participate,
  so skipping a contest never lowers your rating relative to others.
- Inactivity DECAY (like AHC's time-based performance decay): the rating decays
  toward 0 with a half-life, so an inactive high rating doesn't persist forever.

We deliberately do NOT replicate AtCoder's exact percentile/opponent-strength
performance (that needs a large calibrated population). Performance here blends
placement in the contest and how much of it you solved.
"""
from __future__ import annotations

RECENCY_WEIGHT = 0.9        # i-th most recent performance weighted 0.9^i
HALF_LIFE_DAYS = 30.0       # inactivity half-life for the decay
PERF_SCALE = 2000           # performance range ~[0, 2000]


def performance(rank: int, field: int, points: int, max_points: int) -> int:
    """Performance for one contest.

    rank: 1 = best. field: number of participants (solvers). points/max_points:
    how much of the contest the user solved. Blends placement (60%) + achievement
    (40%) so a strong solo effort still scores, and last place isn't zero if they
    solved a lot.
    """
    placement = (field - rank) / (field - 1) if field > 1 else 1.0
    achievement = (points / max_points) if max_points else 0.0
    return round(PERF_SCALE * (0.6 * placement + 0.4 * achievement))


def compute(perfs_recent_first: list[int], last_epoch: int, now: int) -> dict | None:
    """Aggregate a user's performances (most-recent first) into a rating.

    Returns {raw, rating, n, days_inactive, decay} or None if no performances.
    `raw` is the recency-weighted rating; `rating` applies the inactivity decay.
    """
    if not perfs_recent_first:
        return None
    num = den = 0.0
    for i, p in enumerate(perfs_recent_first):
        w = RECENCY_WEIGHT ** (i + 1)
        num += p * w
        den += w
    raw = num / den
    days = max(0.0, (now - last_epoch) / 86400.0)
    decay = 0.5 ** (days / HALF_LIFE_DAYS)
    return {
        "raw": round(raw),
        "rating": round(raw * decay),
        "n": len(perfs_recent_first),
        "days_inactive": days,
        "decay": decay,
    }
