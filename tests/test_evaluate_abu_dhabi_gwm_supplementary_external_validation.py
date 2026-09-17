from __future__ import annotations

import pandas as pd

from scripts.evaluate_abu_dhabi_gwm_supplementary_external_validation import (
    _aggregate_source_specific,
)


def test_aggregate_keeps_optical_and_sar_sources_separate() -> None:
    frame = pd.DataFrame(
        [
            {
                "observation_source": "landsat",
                "space": "raw_depth_primary",
                "model": "physics",
                "iou": 0.4,
                "precision": 0.5,
                "recall": 0.6,
                "f1": 0.55,
                "brier_score": 0.2,
            },
            {
                "observation_source": "sentinel1",
                "space": "raw_depth_primary",
                "model": "physics",
                "iou": 0.1,
                "precision": 0.2,
                "recall": 0.3,
                "f1": 0.24,
                "brier_score": 0.4,
            },
        ]
    )

    rows = _aggregate_source_specific(frame)

    assert len(rows) == 2
    assert {row["observation_source"] for row in rows} == {"landsat", "sentinel1"}
    assert all(row["event_count"] == 1 for row in rows)
