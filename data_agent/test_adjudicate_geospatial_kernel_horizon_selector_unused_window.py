import csv
import io
import json
from datetime import UTC, datetime

import pytest

from scripts import adjudicate_geospatial_kernel_horizon_selector_unused_window as audit


def _timestamp_file(root, name: str, timestamp: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"timestamp":"{timestamp}","value":999}}\n', encoding="utf-8")


def test_all_consumed_chunks_fail_closed_without_data_access(tmp_path) -> None:
    timestamps = [
        "2022-05-26T01:00:00Z",
        "2022-06-23T01:00:00Z",
        "2022-07-21T01:00:00Z",
        "2022-08-18T01:00:00Z",
        "2022-09-15T01:00:00Z",
        "2022-10-13T01:00:00Z",
        "2022-11-10T01:00:00Z",
        "2022-12-08T01:00:00Z",
    ]
    for index, timestamp in enumerate(timestamps, start=565):
        _timestamp_file(tmp_path, f"evidence/{index}.json", timestamp)

    ledger_body, report = audit.compile_adjudication(
        scan_roots=(tmp_path,),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        excluded_paths=(),
    )

    assert report["status"] == (
        "no_repository_unconsumed_full_historical_chunk_found"
    )
    assert report["nwm_time_axis"]["candidate_full_chunk_indices"] == list(
        range(565, 573)
    )
    assert report["nwm_time_axis"]["partial_terminal_chunk"]["eligible"] is False
    assert report["selection"]["window_selected"] is False
    assert report["selection"]["nwm_time_chunk_index"] is None
    assert all(
        chunk["total_prior_local_consumption_hit_count"] == 1
        for chunk in report["candidate_chunks"]
    )
    assert report["data_access_boundary"]["network_access_performed"] is False
    assert report["data_access_boundary"]["candidate_window_request_count"] == 0
    rows = list(csv.DictReader(io.StringIO(ledger_body.decode("utf-8"))))
    assert [int(row["chunk_index"]) for row in rows] == list(range(565, 573))


def test_earliest_zero_hit_chunk_is_selected_and_boundaries_are_right_open(
    tmp_path,
) -> None:
    _timestamp_file(tmp_path, "evidence/end-of-565.json", "2022-06-23T01:00:00Z")
    nwm = tmp_path / "inputs/raw/nwm/q_lateral/565.87.zst"
    nwm.parent.mkdir(parents=True, exist_ok=True)
    nwm.write_bytes(b"not-read-as-value-payload")

    _, report = audit.compile_adjudication(
        scan_roots=(tmp_path,),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        excluded_paths=(),
    )

    by_chunk = {
        row["nwm_time_chunk_index"]: row for row in report["candidate_chunks"]
    }
    assert by_chunk[565]["direct_nwm_object_hit_count"] == 1
    assert by_chunk[565]["timestamp_token_hit_count"] == 0
    assert by_chunk[566]["timestamp_token_hit_count"] == 1
    assert report["selection"]["nwm_time_chunk_index"] == 567
    assert report["selection"]["window_start_inclusive_utc"] == (
        "2022-07-21T01:00:00Z"
    )


def test_tampered_nwm_time_metadata_is_rejected(tmp_path) -> None:
    payload = json.loads(audit.DEFAULT_TIME_ZARRAY.read_bytes())
    payload["shape"] = [385705]
    path = tmp_path / "tampered-zarray.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="horizon_selector_adjudication_nwm_time_axis_invalid",
    ):
        audit.compile_adjudication(
            time_zarray_path=path,
            scan_roots=(tmp_path,),
            excluded_paths=(),
        )
