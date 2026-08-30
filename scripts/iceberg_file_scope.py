"""Provider-neutral helpers for Iceberg physical file-scope evidence."""

from __future__ import annotations

from typing import Any


def _stable_partition_value(value: Any) -> Any:
    """Convert Spark Row/struct values into deterministic JSON-compatible data."""
    if hasattr(value, "asDict"):
        value = value.asDict(recursive=True)
    if isinstance(value, dict):
        return {str(key): _stable_partition_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_stable_partition_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _partition_road_id(partition: Any) -> int:
    normalized = _stable_partition_value(partition)
    if isinstance(normalized, dict):
        for key in ("road_id", "identity_road_id"):
            if key in normalized:
                return int(normalized[key])
    if isinstance(normalized, (int, str)):
        return int(normalized)
    raise RuntimeError(f"Iceberg files metadata did not expose road_id partition: {normalized!r}")


def _file_scope_evidence(
    before: tuple[dict[str, Any], ...],
    after: tuple[dict[str, Any], ...],
    plan: dict[str, Any],
) -> dict[str, Any]:
    def by_partition(items: tuple[dict[str, Any], ...]) -> dict[int, list[str]]:
        result: dict[int, list[str]] = {}
        for item in items:
            result.setdefault(int(item["road_id"]), []).append(item["file_path"])
        return {key: sorted(value) for key, value in result.items()}

    before_by_partition = by_partition(before)
    after_by_partition = by_partition(after)
    partition_ids = sorted(set(before_by_partition) | set(after_by_partition))
    changed = [
        partition_id
        for partition_id in partition_ids
        if before_by_partition.get(partition_id, []) != after_by_partition.get(partition_id, [])
    ]
    target_ids = sorted({int(value) for value in plan.get("target_road_ids", [])})
    guard_ids = sorted({int(value) for value in plan.get("expected_unchanged_partition_ids", [])})
    checks = {
        "file_scope_target_partitions_changed": all(
            partition_id in changed for partition_id in target_ids
        ),
        "file_scope_guard_partitions_unchanged": all(
            partition_id not in changed for partition_id in guard_ids
        ),
        "file_scope_changed_partitions_exact": set(changed) == set(target_ids),
    }
    return {
        "checks": checks,
        "before_files": list(before),
        "after_files": list(after),
        "before_files_by_partition": before_by_partition,
        "after_files_by_partition": after_by_partition,
        "changed_partition_ids": changed,
        "target_partition_ids": target_ids,
        "guard_partition_ids": guard_ids,
    }
