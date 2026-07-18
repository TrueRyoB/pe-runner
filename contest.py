"""Contest formats and problem selection.

A contest FORMAT is chosen by intended DURATION, not by a single difficulty band.
Each format bundles the duration and a RECIPE: a list of (band, count) slots drawn
from across the difficulty spectrum (e.g. normal = 簡単×1・中下位×2・中上位×2・上位×1).
Spreading a single contest easy→hard lets a newcomer solve *something* while still
separating the top — an onboarding-friendly spread, not a pool-robustness trick.

Problems are chosen from the eligible pool (published problems that NOBODY in the
contest has solved) per slot's band, unique across slots.

Rating-shaping knobs also live on the format (consumed by rating.performance):
- `perf_cap`   : cap a contest's performance as a fraction of scale (speed → no farming)
- `loss_floor` : raise the performance floor (hardcore → 負けより勝ちを優先)
"""
from __future__ import annotations

import random

# Canonical difficulty bands (PE difficulty %: 0 ≈ trivial, 100 ≈ brutal).
# Ranges are inclusive; adjacent bands share a boundary (a boundary problem is
# eligible for either band — selection dedupes across slots).
BANDS: dict[str, tuple[int, int]] = {
    "簡単":   (1, 10),
    "中下位": (10, 25),
    "中位":   (25, 45),
    "中上位": (45, 65),
    "上位":   (65, 80),
    "上上位": (80, 100),
}

# Time-based formats. `slots` is a fixed recipe; `variants` (hardcore) is a list of
# alternative recipes, one picked at random per contest at draw time.
CONTEST_TYPES: dict[str, dict] = {
    "normal": {
        "label": "ノーマル", "duration": 100,
        "slots": [("簡単", 1), ("中下位", 2), ("中上位", 2), ("上位", 1)],
        "perf_cap": None, "loss_floor": 0.0,
    },
    "hardcore": {
        "label": "ハードコア", "duration": 240,
        "variants": [[("中位", 10)], [("上上位", 4)]],  # random one at draw
        "perf_cap": None, "loss_floor": 0.35,           # 負けより勝ちを優先
    },
    "speed": {
        "label": "スピード", "duration": 15,
        "slots": [("簡単", 2), ("中位", 1)],
        "perf_cap": 0.6, "loss_floor": 0.0,             # 荒稼ぎ防止
    },
}


def _slots_str(slots: list[tuple[str, int]]) -> str:
    return "・".join(f"{band}×{n}" for band, n in slots)


def recipe_summary(spec: dict) -> str:
    """Human recipe for a format (for the /create_contest choice label)."""
    if "variants" in spec:
        return " または ".join(_slots_str(v) for v in spec["variants"])
    return _slots_str(spec["slots"])


def total_num(spec: dict) -> int | None:
    """Fixed problem count, or None when it depends on the drawn variant."""
    if "variants" in spec:
        return None
    return sum(n for _, n in spec["slots"])


def _resolve_slots(spec: dict, rng: random.Random) -> list[tuple[str, int]]:
    """Concrete recipe for one contest — resolves hardcore's random variant."""
    if "variants" in spec:
        return list(rng.choice(spec["variants"]))
    return list(spec["slots"])


def _spread_sample(sorted_pool: list, num: int, rng: random.Random) -> list:
    """Pick `num` problems spread across a difficulty-sorted pool (one per sub-band)."""
    n = len(sorted_pool)
    picks = []
    for i in range(num):
        band = sorted_pool[i * n // num:(i + 1) * n // num] or sorted_pool
        picks.append(band[rng.randrange(len(band))])
    return picks


def select_problems(catalog: dict, excluded_ids: set[int], contest_type: str,
                    rng: random.Random | None = None) -> list[dict]:
    """Pick a format's problems from the all-unsolved pool, per recipe slot.
    `catalog` maps id -> object with .id/.difficulty/.title. Problems are unique
    across slots. Raises ValueError if any slot's band lacks enough unsolved problems."""
    if contest_type not in CONTEST_TYPES:
        raise ValueError(f"unknown contest_type: {contest_type}")
    spec = CONTEST_TYPES[contest_type]
    rng = rng or random.Random()
    slots = _resolve_slots(spec, rng)

    used = set(excluded_ids)   # never reuse a problem across slots (or an excluded one)
    chosen = []
    for band, count in slots:
        lo, hi = BANDS[band]
        pool = [c for pid, c in catalog.items()
                if pid not in used and lo <= c.difficulty <= hi]
        if len(pool) < count:
            raise ValueError(
                f"{band}帯({lo}-{hi}%)の未AC問題が{len(pool)}問しか無いにゃ（必要{count}問）。"
                "別の形式にするか参加者を見直してにゃ。")
        pool.sort(key=lambda c: c.difficulty)
        picks = _spread_sample(pool, count, rng)
        for c in picks:
            used.add(c.id)
        chosen.extend(picks)

    chosen.sort(key=lambda c: c.difficulty)
    return [{"id": c.id, "title": c.title, "difficulty": c.difficulty} for c in chosen]
