from __future__ import annotations

from scripts.certify_chongqing_osm_spark_flink_sql_merge_cross_process_budget import _summary


def test_cross_process_budget_summary_requires_exact_shared_budget() -> None:
    results = [
        {"worker_id": "worker-a"},
        {"worker_id": "worker-a"},
        {"worker_id": "worker-b"},
        {"worker_id": "worker-b"},
    ]
    ledger = {
        "attempt_count": 3,
        "max_attempts": 3,
        "status": "exhausted",
        "events": [
            {
                "worker_id": "worker-a",
                "attempt_number": 1,
                "admitted": True,
                "reason": "budget_admitted",
            },
            {
                "worker_id": "worker-b",
                "attempt_number": 2,
                "admitted": True,
                "reason": "budget_admitted",
            },
            {
                "worker_id": "worker-a",
                "attempt_number": 3,
                "admitted": True,
                "reason": "budget_admitted",
            },
            {
                "worker_id": "worker-b",
                "attempt_number": 4,
                "admitted": False,
                "reason": "retry_budget_exhausted",
            },
        ],
    }
    assert all(_summary(results, ledger, 3).values())
