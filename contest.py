"""Contest-type tiers and problem selection.

A contest-type bundles EVERYTHING except the start time: a PE difficulty-%
range, how many problems, and the duration. So `/create_contest` only needs
`start` + `contest_type`.

Problems are chosen from the eligible pool (published problems that NOBODY in
the contest has solved) within the tier's difficulty range, spread across that
range for variety.
"""
from __future__ import annotations

import random

# PE difficulty rating: 0 ≈ trivial, 100 ≈ brutal. Ranges below leave ample
# unsolved pool in each tier (measured: ~uniform 0–100% over ~1000 problems).
CONTEST_TYPES: dict[str, dict] = {
    "beginner":     {"label": "初心者", "min": 1,  "max": 10, "num": 4, "duration": 90},
    "intermediate": {"label": "中級者", "min": 10, "max": 35, "num": 4, "duration": 120},
    "advanced":     {"label": "上級者", "min": 30, "max": 75, "num": 3, "duration": 180},
}


def _spread_sample(sorted_pool: list, num: int, rng: random.Random) -> list:
    """Pick `num` problems spread across a difficulty-sorted pool (one per band)."""
    n = len(sorted_pool)
    picks = []
    for i in range(num):
        band = sorted_pool[i * n // num:(i + 1) * n // num] or sorted_pool
        picks.append(band[rng.randrange(len(band))])
    return picks


def select_problems(catalog: dict, excluded_ids: set[int], contest_type: str,
                    rng: random.Random | None = None) -> list[dict]:
    """Pick this tier's problems from the all-unsolved pool. `catalog` maps
    id -> object with .difficulty/.title. Raises ValueError if the pool is too small."""
    if contest_type not in CONTEST_TYPES:
        raise ValueError(f"unknown contest_type: {contest_type}")
    spec = CONTEST_TYPES[contest_type]
    rng = rng or random.Random()
    lo, hi, num = spec["min"], spec["max"], spec["num"]

    pool = [c for pid, c in catalog.items()
            if pid not in excluded_ids and lo <= c.difficulty <= hi]
    if len(pool) < num:
        raise ValueError(
            f"難易度{lo}-{hi}%の未AC問題が{len(pool)}問しか無いにゃ（必要{num}問）。"
            "別のタイプにするか参加者を見直してにゃ。")

    pool.sort(key=lambda c: c.difficulty)
    picks = _spread_sample(pool, num, rng)
    return [{"id": c.id, "title": c.title, "difficulty": c.difficulty} for c in picks]
