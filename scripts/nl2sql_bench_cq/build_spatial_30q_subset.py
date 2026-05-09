"""Build a 30-question stratified subset of the 85q GIS Spatial benchmark for
cross-model-family ablation. Stratify by (difficulty, category) pair, sampling
proportional counts that round to at least 1 per non-empty cell.

Source: the 85 Spatial records inside ``chongqing_geo_nl2sql_100_benchmark.json``
(the file contains 125 rows = 85 Spatial [Easy/Medium/Hard] + 40 Robustness).
We filter Robustness out by difficulty so the stratification budget is spent on
the Spatial portion only, while re-using the exact same ``id`` space as the
full 85q benchmark -- results on this subset are directly comparable.

Output: benchmarks/gis_spatial_30q_subset.json (same record format as source).
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path("D:/adk/benchmarks/chongqing_geo_nl2sql_100_benchmark.json")
OUT = Path("D:/adk/benchmarks/gis_spatial_30q_subset.json")
TARGET = 30
SEED = 20260508
SPATIAL_DIFFICULTIES = {"Easy", "Medium", "Hard"}


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    # The 85q Spatial set lives inside the 100-benchmark file alongside 40
    # Robustness items. Both use a CQ_GEO_* id prefix, so we filter by
    # difficulty: Easy/Medium/Hard are Spatial, Robustness is its own bucket.
    spatial = [r for r in rows if r.get("difficulty") in SPATIAL_DIFFICULTIES]
    if len(spatial) != 85:
        print(f"[warn] expected 85 spatial, got {len(spatial)}")

    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in spatial:
        by_cell[(r.get("difficulty", "?"), r.get("category", "?"))].append(r)

    rng = random.Random(SEED)
    # Largest cells first so proportional rounding errors accumulate on the
    # dominant categories; singleton cells at the tail still contribute >=1
    # until we hit the TARGET budget.
    cells = sorted(by_cell.items(), key=lambda kv: -len(kv[1]))
    total = len(spatial)
    picked: list[dict] = []
    for (_diff, _cat), items in cells:
        share = max(1, round(len(items) / total * TARGET))
        share = min(share, len(items))
        # Shuffle deterministically with the seeded RNG.
        shuffled = list(items)
        rng.shuffle(shuffled)
        picked.extend(shuffled[:share])

    # Trim or pad to exactly TARGET.
    if len(picked) > TARGET:
        picked = picked[:TARGET]
    elif len(picked) < TARGET:
        picked_ids = {r.get("id") for r in picked}
        leftover = [r for r in spatial if r.get("id") not in picked_ids]
        rng.shuffle(leftover)
        picked.extend(leftover[: TARGET - len(picked)])

    picked.sort(key=lambda r: r.get("id", ""))
    OUT.write_text(json.dumps(picked, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} with {len(picked)} rows")
    print("by difficulty:", Counter(r.get("difficulty") for r in picked))
    print("by category:  ", Counter(r.get("category") for r in picked))


if __name__ == "__main__":
    main()
