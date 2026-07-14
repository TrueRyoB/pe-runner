"""Contest-type presets and problem selection.

A contest-type is a target distribution over difficulty buckets. We select
``num_problems`` from the eligible pool (published problems that NOBODY in the
contest has solved) matching that distribution as closely as the pool allows.
"""
from __future__ import annotations

import random

# Difficulty buckets by PE percent rating.
BUCKETS = {
    "easy":    lambda d: d <= 5,
    "medium":  lambda d: 6 <= d <= 15,
    "hard":    lambda d: 16 <= d <= 40,
    "extreme": lambda d: d > 40,
}

# contest-type -> weight per bucket (need not sum to 1; normalized on use).
CONTEST_TYPES: dict[str, dict[str, float]] = {
    "sprint":   {"easy": 0.6, "medium": 0.4},
    "balanced": {"easy": 0.3, "medium": 0.4, "hard": 0.3},
    "marathon": {"medium": 0.3, "hard": 0.5, "extreme": 0.2},
}


def bucket_of(difficulty: int) -> str | None:
    for name, pred in BUCKETS.items():
        if pred(difficulty):
            return name
    return None


def _allocate(num: int, weights: dict[str, float]) -> dict[str, int]:
    total = sum(weights.values())
    raw = {b: num * w / total for b, w in weights.items()}
    counts = {b: int(v) for b, v in raw.items()}
    # Distribute the remainder to the largest fractional parts.
    remainder = num - sum(counts.values())
    frac = sorted(weights, key=lambda b: raw[b] - counts[b], reverse=True)
    for b in frac[:remainder]:
        counts[b] += 1
    return counts


def select_problems(catalog: dict[int, "object"], excluded_ids: set[int],
                    contest_type: str, num_problems: int,
                    rng: random.Random | None = None) -> list[dict]:
    """Pick problems. ``catalog`` maps id -> object with .difficulty/.title.

    Raises ValueError if the eligible pool can't fill the request.
    """
    if contest_type not in CONTEST_TYPES:
        raise ValueError(f"unknown contest_type: {contest_type}")
    rng = rng or random.Random()

    # Eligible = not solved by anyone in the contest.
    pool_by_bucket: dict[str, list] = {b: [] for b in BUCKETS}
    for pid, cell in catalog.items():
        if pid in excluded_ids:
            continue
        b = bucket_of(cell.difficulty)
        if b:
            pool_by_bucket[b].append(cell)

    weights = CONTEST_TYPES[contest_type]
    want = _allocate(num_problems, weights)

    chosen: list = []
    shortfall = 0
    for bucket, n in want.items():
        pool = pool_by_bucket.get(bucket, [])
        rng.shuffle(pool)
        take = pool[:n]
        chosen.extend(take)
        shortfall += n - len(take)

    # Backfill any shortfall from leftover eligible problems (closest buckets first).
    if shortfall:
        used = {c.id for c in chosen}
        leftovers = [c for b in weights for c in pool_by_bucket[b] if c.id not in used]
        rng.shuffle(leftovers)
        chosen.extend(leftovers[:shortfall])

    if len(chosen) < num_problems:
        raise ValueError(
            f"eligible pool too small: wanted {num_problems}, found {len(chosen)}. "
            "Loosen the contest-type or reduce problem count."
        )

    return [{"id": c.id, "title": c.title, "difficulty": c.difficulty}
            for c in chosen[:num_problems]]
