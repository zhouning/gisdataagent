#!/usr/bin/env python3
"""Adjudicate locally unused NWM windows without network or value access."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESIGN = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_selector_replication_design.json"
)
DEFAULT_TIME_ZARRAY = (
    REPO_ROOT / "data/geotransport_v0_1/metadata/nwm-time-zarray.json"
)
DEFAULT_TIME_ZATTRS = (
    REPO_ROOT / "data/geotransport_v0_1/metadata/nwm-time-zattrs.json"
)
DEFAULT_SCAN_ROOTS = (
    REPO_ROOT / "data/geotransport_v0_1",
    REPO_ROOT / "benchmarks/geotransport_v0_1",
)
DEFAULT_LEDGER = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_horizon_selector_unused_window_adjudication/"
    "consumption_hits.csv"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_selector_unused_window_adjudication.json"
)

SCHEMA = "gwm.geotransport.horizon_selector_unused_window_adjudication.v1"
DESIGN_SCHEMA = "gwm.geotransport.horizon_selector_replication_design.v1"
DESIGN_STATUS = "design_frozen_awaiting_unused_window_adjudication"
NWM_ORIGIN = datetime(1979, 2, 1, 1, tzinfo=UTC)
NWM_TIME_UNITS = "hours since 1979-02-01T01:00:00"
NWM_CALENDAR = "proleptic_gregorian"

TEXT_SUFFIXES = {
    ".cdl",
    ".csv",
    ".f90",
    ".h",
    ".json",
    ".md",
    ".patch",
    ".pxd",
    ".py",
    ".pyx",
    ".rdb",
    ".rst",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"LICENSE", "makefile", "Makefile"}
TIMESTAMP_PATTERN = re.compile(
    rb"(?<!\d)(\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}"
    rb"(?::\d{2}(?:\.\d{1,9})?)?(?:[Zz]|[+-]\d{2}:?\d{2}))(?!\d)"
)
NWM_OBJECT_PATTERN = re.compile(
    r"(?:^|/)raw/nwm/(?P<variable>q_lateral|time|streamflow)/"
    r"(?P<chunk>\d+)(?:\.(?P<feature_chunk>\d+))?\.zst$"
)
LEDGER_FIELDS = (
    "chunk_index",
    "window_start_inclusive_utc",
    "window_end_exclusive_utc",
    "evidence_kind",
    "path",
    "occurrence_count",
    "unique_timestamp_count",
    "first_timestamp_utc",
    "last_timestamp_utc",
    "first_line_number",
    "last_line_number",
    "nwm_variable",
    "nwm_object_name",
)


@dataclass
class _TimestampAggregate:
    count: int = 0
    timestamps: set[datetime] = field(default_factory=set)
    first_line: int | None = None
    last_line: int | None = None

    def add(self, value: datetime, line_number: int) -> None:
        self.count += 1
        self.timestamps.add(value)
        if self.first_line is None:
            self.first_line = line_number
        self.last_line = line_number


@dataclass(frozen=True)
class _CandidateChunk:
    index: int
    start: datetime
    end: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--time-zarray", type=Path, default=DEFAULT_TIME_ZARRAY)
    parser.add_argument("--time-zattrs", type=Path, default=DEFAULT_TIME_ZATTRS)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_adjudication(
    *,
    design_path: Path = DEFAULT_DESIGN,
    time_zarray_path: Path = DEFAULT_TIME_ZARRAY,
    time_zattrs_path: Path = DEFAULT_TIME_ZATTRS,
    scan_roots: Sequence[Path] = DEFAULT_SCAN_ROOTS,
    ledger_path: Path = DEFAULT_LEDGER,
    generated_at: datetime | None = None,
    excluded_paths: Sequence[Path] = (DEFAULT_LEDGER, DEFAULT_OUTPUT),
) -> tuple[bytes, dict[str, Any]]:
    design_body, design = _load_json(design_path)
    zarray_body, zarray = _load_json(time_zarray_path)
    zattrs_body, zattrs = _load_json(time_zattrs_path)
    chunks, partial_chunk = _validate_and_build_chunks(design, zarray, zattrs)
    _verify_frozen_design_artifacts(design)

    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("horizon_selector_adjudication_generated_at_must_be_aware")
    if not scan_roots:
        raise ValueError("horizon_selector_adjudication_scan_roots_required")

    scan = _scan_repository_consumption(
        chunks=chunks,
        scan_roots=tuple(Path(value).resolve() for value in scan_roots),
        excluded_paths={Path(value).resolve() for value in excluded_paths},
    )
    ledger_rows = _ledger_rows(chunks, scan["timestamp_hits"], scan["nwm_hits"])
    ledger_body = _encode_ledger(ledger_rows)
    chunk_results = _chunk_results(chunks, ledger_rows)
    eligible = [row for row in chunk_results if row["eligible_for_selection"]]
    selected = eligible[0] if eligible else None
    if selected is None:
        status = "no_repository_unconsumed_full_historical_chunk_found"
        next_gate = "prospective_sealed_campaign_or_new_archive_period_required"
    else:
        status = "repository_unconsumed_full_historical_chunk_selected"
        next_gate = "freeze_replication_protocol_before_any_network_or_value_access"

    report = {
        "schema": SCHEMA,
        "status": status,
        "generated_at": now.astimezone(UTC).isoformat(),
        "design_id": design["design_id"],
        "bound_artifacts": {
            "frozen_replication_design": _artifact(design_path, design_body),
            "nwm_time_zarray": _artifact(time_zarray_path, zarray_body),
            "nwm_time_zattrs": _artifact(time_zattrs_path, zattrs_body),
            "consumption_hit_ledger": _artifact(ledger_path, ledger_body),
        },
        "nwm_time_axis": {
            "origin_utc": _iso(NWM_ORIGIN),
            "calendar": zattrs["calendar"],
            "shape_hours": zarray["shape"][0],
            "chunk_size_hours": zarray["chunks"][0],
            "complete_chunk_count": zarray["shape"][0] // zarray["chunks"][0],
            "candidate_full_chunk_indices": [chunk.index for chunk in chunks],
            "partial_terminal_chunk": partial_chunk,
        },
        "adjudication_rule": {
            "selection_order": "earliest_complete_candidate_chunk_first",
            "candidate_window_interval": "right_open_[start,end)",
            "timestamp_rule": (
                "any timezone-aware ISO timestamp token in a scoped local text "
                "file that falls in a candidate block is prior local consumption"
            ),
            "direct_nwm_object_rule": (
                "any raw/nwm/{q_lateral,time,streamflow}/<candidate_chunk>"
                "[.<feature_chunk>].zst filename is prior local consumption"
            ),
            "zero_total_hits_required": True,
            "ties_or_ambiguity_fail_closed": True,
            "external_prior_access_proven_absent": False,
        },
        "repository_scan": {
            "roots": scan["root_labels"],
            "inventory_path_size_sha256": scan["inventory_sha256"],
            "files_enumerated": scan["files_enumerated"],
            "text_files_scanned": scan["text_files_scanned"],
            "non_text_files_filename_scanned_only": scan["non_text_files"],
            "text_bytes_scanned": scan["text_bytes_scanned"],
            "timezone_aware_timestamp_tokens_matched": scan[
                "timestamp_tokens_matched"
            ],
            "timezone_aware_timestamp_tokens_parsed": scan[
                "timestamp_tokens_parsed"
            ],
            "timestamp_tokens_rejected_as_invalid": scan[
                "timestamp_tokens_rejected"
            ],
            "candidate_block_timestamp_occurrences": sum(
                hit.count for hit in scan["timestamp_hits"].values()
            ),
            "candidate_chunk_nwm_object_files": len(scan["nwm_hits"]),
            "source_payload_fields_parsed": False,
            "timestamp_tokens_and_filenames_only": True,
            "scan_errors": [],
        },
        "candidate_chunks": chunk_results,
        "selection": {
            "window_selected": selected is not None,
            "nwm_time_chunk_index": (
                selected["nwm_time_chunk_index"] if selected else None
            ),
            "window_start_inclusive_utc": (
                selected["window_start_inclusive_utc"] if selected else None
            ),
            "window_end_exclusive_utc": (
                selected["window_end_exclusive_utc"] if selected else None
            ),
            "eligible_candidate_count": len(eligible),
            "reason": (
                "selected_earliest_zero_hit_complete_chunk"
                if selected
                else "every_complete_candidate_chunk_has_prior_local_consumption"
            ),
        },
        "data_access_boundary": {
            "network_access_performed": False,
            "candidate_window_url_compiled": False,
            "candidate_window_request_count": 0,
            "new_candidate_window_values_requested": False,
            "new_candidate_window_values_loaded": False,
            "existing_local_non_timestamp_values_parsed": False,
        },
        "decision": {
            "historical_replication_can_proceed": selected is not None,
            "next_gate": next_gate,
            "replication_protocol_frozen": False,
            "automatic_execution_authorized": False,
        },
        "claim_boundary": {
            "repository_consumption_audit_completed": True,
            "repository_unconsumed_full_historical_chunk_found": selected is not None,
            "globally_unseen_window_proven": False,
            "replication_predictions_executed": False,
            "replication_scored": False,
            "prior_rejected_candidate_reopened": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }
    return ledger_body, report


def _validate_and_build_chunks(
    design: Mapping[str, Any],
    zarray: Mapping[str, Any],
    zattrs: Mapping[str, Any],
) -> tuple[list[_CandidateChunk], dict[str, Any]]:
    requirements = design.get("window_adjudication_requirements") or {}
    prior_window = requirements.get("must_not_overlap_prior_scored_window") or {}
    if (
        design.get("schema") != DESIGN_SCHEMA
        or design.get("status") != DESIGN_STATUS
        or design.get("design_id") != "horizon_selector_mechanism_replication_v1"
        or requirements.get("window_selected") is not False
        or requirements.get("repository_value_consumption_audit_required") is not True
        or requirements.get("must_start_on_full_nwm_time_chunk_boundary") is not True
        or requirements.get("hour_count") != 672
        or design.get("data_access_boundary", {}).get("new_window_request_count") != 0
        or design.get("claim_boundary", {}).get("replication_scored") is not False
    ):
        raise ValueError("horizon_selector_adjudication_design_invalid")
    try:
        chunk_size = int(zarray["chunks"][0])
        shape = int(zarray["shape"][0])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("horizon_selector_adjudication_nwm_time_axis_invalid") from exc
    if (
        zarray.get("chunks") != [672]
        or zarray.get("shape") != [385704]
        or zarray.get("dtype") != "<i8"
        or zattrs.get("units") != NWM_TIME_UNITS
        or zattrs.get("calendar") != NWM_CALENDAR
        or chunk_size != requirements.get("hour_count")
    ):
        raise ValueError("horizon_selector_adjudication_nwm_time_axis_invalid")

    prior_start = _parse_aware(str(prior_window.get("start_inclusive_utc")))
    prior_end = _parse_aware(str(prior_window.get("end_exclusive_utc")))
    if (
        prior_end - prior_start != timedelta(hours=chunk_size)
        or (prior_end - NWM_ORIGIN).total_seconds() % (chunk_size * 3600) != 0
    ):
        raise ValueError("horizon_selector_adjudication_prior_window_invalid")

    first_candidate = int((prior_end - NWM_ORIGIN).total_seconds() // 3600) // chunk_size
    full_chunk_count, remainder = divmod(shape, chunk_size)
    chunks = [
        _CandidateChunk(
            index=index,
            start=NWM_ORIGIN + timedelta(hours=index * chunk_size),
            end=NWM_ORIGIN + timedelta(hours=(index + 1) * chunk_size),
        )
        for index in range(first_candidate, full_chunk_count)
    ]
    if [chunk.index for chunk in chunks] != list(range(565, 573)) or remainder != 648:
        raise ValueError("horizon_selector_adjudication_candidate_chunks_invalid")
    partial_start = NWM_ORIGIN + timedelta(hours=full_chunk_count * chunk_size)
    partial = {
        "nwm_time_chunk_index": full_chunk_count,
        "start_inclusive_utc": _iso(partial_start),
        "archive_end_exclusive_utc": _iso(NWM_ORIGIN + timedelta(hours=shape)),
        "available_hour_count": remainder,
        "required_hour_count": chunk_size,
        "eligible": False,
        "reason": "partial_terminal_chunk",
    }
    return chunks, partial


def _verify_frozen_design_artifacts(design: Mapping[str, Any]) -> None:
    descriptors = design.get("frozen_artifacts") or {}
    if not isinstance(descriptors, Mapping) or not descriptors:
        raise ValueError("horizon_selector_adjudication_design_artifacts_missing")
    for descriptor in descriptors.values():
        if not isinstance(descriptor, Mapping):
            raise ValueError("horizon_selector_adjudication_design_artifacts_invalid")
        _read_verified(descriptor)


def _scan_repository_consumption(
    *,
    chunks: Sequence[_CandidateChunk],
    scan_roots: Sequence[Path],
    excluded_paths: set[Path],
) -> dict[str, Any]:
    files: dict[Path, tuple[str, int]] = {}
    root_labels: list[str] = []
    for root_index, root in enumerate(scan_roots):
        if not root.is_dir():
            raise ValueError(f"horizon_selector_adjudication_scan_root_missing:{root}")
        root_label = _display_scan_root(root, root_index)
        root_labels.append(root_label)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in excluded_paths:
                continue
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError(
                    "horizon_selector_adjudication_scan_path_outside_root"
                ) from exc
            display = f"{root_label}/{relative}"
            size = resolved.stat().st_size
            prior = files.get(resolved)
            if prior is not None and prior != (display, size):
                raise ValueError("horizon_selector_adjudication_duplicate_scan_path")
            files[resolved] = (display, size)

    inventory = "".join(
        f"{display}\0{size}\n" for display, size in sorted(files.values())
    ).encode("utf-8")
    chunk_by_index = {chunk.index: chunk for chunk in chunks}
    timestamp_hits: dict[tuple[int, str], _TimestampAggregate] = {}
    nwm_hits: list[dict[str, Any]] = []
    text_files_scanned = 0
    non_text_files = 0
    text_bytes_scanned = 0
    matched = 0
    parsed = 0
    rejected = 0

    for path, (display, expected_size) in sorted(
        files.items(), key=lambda item: item[1][0]
    ):
        object_match = NWM_OBJECT_PATTERN.search(display)
        if object_match:
            chunk_index = int(object_match.group("chunk"))
            if chunk_index in chunk_by_index:
                nwm_hits.append(
                    {
                        "chunk_index": chunk_index,
                        "path": display,
                        "variable": object_match.group("variable"),
                        "object_name": Path(display).name,
                    }
                )

        if not _is_text_path(path):
            non_text_files += 1
            continue
        text_files_scanned += 1
        text_bytes_scanned += expected_size
        with path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                for match in TIMESTAMP_PATTERN.finditer(line):
                    matched += 1
                    try:
                        value = _parse_aware(match.group(1).decode("ascii"))
                    except (UnicodeDecodeError, ValueError):
                        rejected += 1
                        continue
                    parsed += 1
                    chunk_index = _candidate_chunk_for_timestamp(value, chunks)
                    if chunk_index is None:
                        continue
                    key = (chunk_index, display)
                    timestamp_hits.setdefault(key, _TimestampAggregate()).add(
                        value, line_number
                    )
        if path.stat().st_size != expected_size:
            raise ValueError("horizon_selector_adjudication_file_changed_during_scan")

    return {
        "root_labels": root_labels,
        "inventory_sha256": hashlib.sha256(inventory).hexdigest(),
        "files_enumerated": len(files),
        "text_files_scanned": text_files_scanned,
        "non_text_files": non_text_files,
        "text_bytes_scanned": text_bytes_scanned,
        "timestamp_tokens_matched": matched,
        "timestamp_tokens_parsed": parsed,
        "timestamp_tokens_rejected": rejected,
        "timestamp_hits": timestamp_hits,
        "nwm_hits": nwm_hits,
    }


def _ledger_rows(
    chunks: Sequence[_CandidateChunk],
    timestamp_hits: Mapping[tuple[int, str], _TimestampAggregate],
    nwm_hits: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    chunk_by_index = {chunk.index: chunk for chunk in chunks}
    rows: list[dict[str, Any]] = []
    for (chunk_index, path), aggregate in timestamp_hits.items():
        timestamps = sorted(aggregate.timestamps)
        chunk = chunk_by_index[chunk_index]
        rows.append(
            {
                "chunk_index": chunk_index,
                "window_start_inclusive_utc": _iso(chunk.start),
                "window_end_exclusive_utc": _iso(chunk.end),
                "evidence_kind": "timezone_aware_iso_timestamp_token",
                "path": path,
                "occurrence_count": aggregate.count,
                "unique_timestamp_count": len(timestamps),
                "first_timestamp_utc": _iso(timestamps[0]),
                "last_timestamp_utc": _iso(timestamps[-1]),
                "first_line_number": aggregate.first_line,
                "last_line_number": aggregate.last_line,
                "nwm_variable": "",
                "nwm_object_name": "",
            }
        )
    for hit in nwm_hits:
        chunk = chunk_by_index[int(hit["chunk_index"])]
        rows.append(
            {
                "chunk_index": chunk.index,
                "window_start_inclusive_utc": _iso(chunk.start),
                "window_end_exclusive_utc": _iso(chunk.end),
                "evidence_kind": "direct_raw_nwm_object_filename",
                "path": hit["path"],
                "occurrence_count": 1,
                "unique_timestamp_count": 0,
                "first_timestamp_utc": "",
                "last_timestamp_utc": "",
                "first_line_number": "",
                "last_line_number": "",
                "nwm_variable": hit["variable"],
                "nwm_object_name": hit["object_name"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            int(row["chunk_index"]),
            str(row["evidence_kind"]),
            str(row["path"]),
        ),
    )


def _chunk_results(
    chunks: Sequence[_CandidateChunk], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for chunk in chunks:
        relevant = [row for row in rows if row["chunk_index"] == chunk.index]
        timestamp_rows = [
            row
            for row in relevant
            if row["evidence_kind"] == "timezone_aware_iso_timestamp_token"
        ]
        object_rows = [
            row
            for row in relevant
            if row["evidence_kind"] == "direct_raw_nwm_object_filename"
        ]
        timestamp_count = sum(int(row["occurrence_count"]) for row in timestamp_rows)
        object_count = sum(int(row["occurrence_count"]) for row in object_rows)
        total = timestamp_count + object_count
        examples = []
        for row in relevant[:5]:
            example = {
                "evidence_kind": row["evidence_kind"],
                "path": row["path"],
                "occurrence_count_in_file": row["occurrence_count"],
            }
            if row["first_timestamp_utc"]:
                example["first_timestamp_utc"] = row["first_timestamp_utc"]
                example["last_timestamp_utc"] = row["last_timestamp_utc"]
            else:
                example["nwm_variable"] = row["nwm_variable"]
                example["nwm_object_name"] = row["nwm_object_name"]
            examples.append(example)
        results.append(
            {
                "nwm_time_chunk_index": chunk.index,
                "window_start_inclusive_utc": _iso(chunk.start),
                "window_end_exclusive_utc": _iso(chunk.end),
                "hour_count": int((chunk.end - chunk.start).total_seconds() // 3600),
                "timestamp_token_hit_count": timestamp_count,
                "timestamp_evidence_file_count": len(timestamp_rows),
                "direct_nwm_object_hit_count": object_count,
                "direct_nwm_object_file_count": len(object_rows),
                "distinct_evidence_file_count": len(
                    {str(row["path"]) for row in relevant}
                ),
                "total_prior_local_consumption_hit_count": total,
                "prior_local_consumption_found": total > 0,
                "eligible_for_selection": total == 0,
                "evidence_examples": examples,
            }
        )
    return results


def _encode_ledger(rows: Sequence[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=LEDGER_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _candidate_chunk_for_timestamp(
    value: datetime, chunks: Sequence[_CandidateChunk]
) -> int | None:
    if not chunks or value < chunks[0].start or value >= chunks[-1].end:
        return None
    chunk_size = chunks[0].end - chunks[0].start
    offset = int((value - chunks[0].start).total_seconds() // chunk_size.total_seconds())
    candidate = chunks[offset]
    return candidate.index if candidate.start <= value < candidate.end else None


def _is_text_path(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_FILENAMES


def _display_scan_root(root: Path, index: int) -> str:
    try:
        return root.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return f"external_audit_root_{index}"


def _parse_aware(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", normalized):
        normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("horizon_selector_adjudication_timezone_required")
    return parsed.astimezone(UTC)


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_selector_adjudication_json_object_required")
    return body, payload


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_selector_adjudication_artifact_outside_repo") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_selector_adjudication_artifact_hash_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_selector_adjudication_artifact_outside_repo") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _assert_pristine(output_path: Path, ledger_path: Path) -> None:
    present = [path.as_posix() for path in (output_path, ledger_path) if path.exists()]
    if present:
        raise ValueError(f"horizon_selector_adjudication_artifact_exists:{present}")


def main() -> int:
    args = parse_args()
    _assert_pristine(args.output, args.ledger)
    ledger_body, report = compile_adjudication(
        design_path=args.design,
        time_zarray_path=args.time_zarray,
        time_zattrs_path=args.time_zattrs,
        ledger_path=args.ledger,
        excluded_paths=(args.ledger, args.output),
    )
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.write_bytes(ledger_body)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"selected_chunk={report['selection']['nwm_time_chunk_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
