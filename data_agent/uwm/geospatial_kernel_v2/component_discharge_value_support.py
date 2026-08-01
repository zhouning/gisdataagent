"""Coverage and synchronization support for component-discharge values."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from data_agent.uwm.geospatial_kernel_v2 import (
    cwms_component_discharge_catalog as catalog,
)

SCHEMA = "gwm.geospatial.component_discharge_value_support.v1"
BEGIN = datetime(2021, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 1, tzinfo=UTC)
EXPECTED_HOURLY_POSITIONS = 43_825


@dataclass(frozen=True)
class ComponentDischargeValueSupport:
    component: str
    series_id: str
    annual_payload_count: int
    raw_row_count: int
    duplicate_boundary_row_count: int
    unique_timestamp_count: int
    expected_hourly_position_count: int
    missing_timestamp_count: int
    null_value_count: int
    real_value_count: int
    negative_value_count: int
    zero_value_count: int
    positive_value_count: int
    quality_code_counts: tuple[tuple[int, int], ...]
    earliest_timestamp_utc: str
    latest_timestamp_utc: str

    def __post_init__(self) -> None:
        if (
            self.component not in catalog.EXPECTED_COMPONENTS
            or self.series_id != catalog.EXPECTED_SERIES_IDS[self.component]
            or self.annual_payload_count != 5
            or self.raw_row_count != self.unique_timestamp_count + self.duplicate_boundary_row_count
            or self.expected_hourly_position_count != EXPECTED_HOURLY_POSITIONS
            or self.unique_timestamp_count + self.missing_timestamp_count
            != self.expected_hourly_position_count
            or self.null_value_count + self.real_value_count != self.unique_timestamp_count
            or (
                self.negative_value_count + self.zero_value_count + self.positive_value_count
                != self.real_value_count
            )
            or sum(count for _, count in self.quality_code_counts) != self.unique_timestamp_count
            or not self.quality_code_counts
            or self.earliest_timestamp_utc != "2021-01-01T00:00:00Z"
            or self.latest_timestamp_utc != "2026-01-01T00:00:00Z"
        ):
            raise ValueError("component_discharge_value_support_invalid")

    @property
    def complete_hourly_grid(self) -> bool:
        return (
            self.unique_timestamp_count == self.expected_hourly_position_count
            and self.missing_timestamp_count == 0
        )

    @property
    def complete_real_nonnegative_support(self) -> bool:
        return (
            self.complete_hourly_grid
            and self.null_value_count == 0
            and self.negative_value_count == 0
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "series_id": self.series_id,
            "annual_payload_count": self.annual_payload_count,
            "raw_row_count": self.raw_row_count,
            "duplicate_boundary_row_count": self.duplicate_boundary_row_count,
            "unique_timestamp_count": self.unique_timestamp_count,
            "expected_hourly_position_count": self.expected_hourly_position_count,
            "missing_timestamp_count": self.missing_timestamp_count,
            "null_value_count": self.null_value_count,
            "real_value_count": self.real_value_count,
            "negative_value_count": self.negative_value_count,
            "zero_value_count": self.zero_value_count,
            "positive_value_count": self.positive_value_count,
            "quality_code_counts": {str(code): count for code, count in self.quality_code_counts},
            "earliest_timestamp_utc": self.earliest_timestamp_utc,
            "latest_timestamp_utc": self.latest_timestamp_utc,
            "complete_hourly_grid": self.complete_hourly_grid,
            "complete_real_nonnegative_support": (self.complete_real_nonnegative_support),
            "missing_values_filled": False,
            "quality_codes_interpreted_as_approval": False,
        }


@dataclass(frozen=True)
class SynchronizedComponentDischargeSupport:
    components: tuple[ComponentDischargeValueSupport, ...]
    expected_hourly_position_count: int
    missing_component_hour_count: int
    null_component_hour_count: int
    negative_component_hour_count: int
    eligible_synchronized_hour_count: int

    def __post_init__(self) -> None:
        if (
            tuple(value.component for value in self.components) != catalog.EXPECTED_COMPONENTS
            or self.expected_hourly_position_count != EXPECTED_HOURLY_POSITIONS
            or (
                self.missing_component_hour_count
                + self.null_component_hour_count
                + self.negative_component_hour_count
                + self.eligible_synchronized_hour_count
                != self.expected_hourly_position_count
            )
        ):
            raise ValueError("synchronized_component_discharge_support_invalid")

    @property
    def all_components_complete(self) -> bool:
        return all(value.complete_hourly_grid for value in self.components)

    @property
    def synchronized_support_complete(self) -> bool:
        return (
            self.all_components_complete
            and self.missing_component_hour_count == 0
            and self.null_component_hour_count == 0
            and self.negative_component_hour_count == 0
            and self.eligible_synchronized_hour_count == self.expected_hourly_position_count
        )

    def require_quality_approval_semantics(self) -> None:
        raise ValueError("component_discharge_quality_code_approval_semantics_unadmitted")

    def require_total_discharge_values(self) -> None:
        raise ValueError("component_discharge_total_values_not_compiled")

    def require_event_selection(self) -> None:
        raise ValueError("component_discharge_event_selection_unadmitted")

    def require_gate_command(self) -> None:
        raise ValueError("component_discharge_gate_command_unadmitted")

    def require_human_action(self) -> None:
        raise ValueError("component_discharge_human_action_unadmitted")

    def require_causal_intervention(self) -> None:
        raise ValueError("component_discharge_causal_intervention_unadmitted")

    def require_physical_response_time(self) -> None:
        raise ValueError("component_discharge_physical_response_time_unadmitted")

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("component_discharge_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "role": "source_only_component_discharge_value_support_audit",
            "components": [value.as_dict() for value in self.components],
            "synchronized_support": {
                "expected_hourly_position_count": (self.expected_hourly_position_count),
                "missing_component_hour_count": self.missing_component_hour_count,
                "null_component_hour_count": self.null_component_hour_count,
                "negative_component_hour_count": (self.negative_component_hour_count),
                "eligible_synchronized_hour_count": (self.eligible_synchronized_hour_count),
                "all_components_complete": self.all_components_complete,
                "synchronized_support_complete": (self.synchronized_support_complete),
            },
            "claim_boundary": {
                "per_component_complete_hourly_coverage_admitted": (self.all_components_complete),
                "synchronized_four_component_value_support_admitted": (
                    self.synchronized_support_complete
                ),
                "quality_code_approval_semantics_admitted": False,
                "synchronized_total_discharge_values_compiled": False,
                "component_discharge_event_admitted": False,
                "gate_command_admitted": False,
                "human_action_admitted": False,
                "causal_intervention_admitted": False,
                "physical_response_time_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_synchronized_component_discharge_support(
    payloads_by_component: Mapping[str, tuple[Mapping[str, object], ...]],
) -> SynchronizedComponentDischargeSupport:
    reports = []
    values_by_component = {}
    for component in catalog.EXPECTED_COMPONENTS:
        payloads = payloads_by_component.get(component)
        if payloads is None:
            raise ValueError("component_discharge_payload_group_required")
        report, values = _compile_component(component, payloads)
        reports.append(report)
        values_by_component[component] = values
    expected_times = tuple(
        BEGIN + timedelta(hours=index) for index in range(EXPECTED_HOURLY_POSITIONS)
    )
    missing = 0
    null = 0
    negative = 0
    eligible = 0
    for timestamp in expected_times:
        rows = [values_by_component[key].get(timestamp) for key in catalog.EXPECTED_COMPONENTS]
        if any(value is None for value in rows):
            missing += 1
            continue
        real_rows = [value for value in rows if value is not None]
        if any(value[0] is None for value in real_rows):
            null += 1
            continue
        numeric = [float(value[0]) for value in real_rows if value[0] is not None]
        if any(value < 0.0 for value in numeric):
            negative += 1
            continue
        eligible += 1
    return SynchronizedComponentDischargeSupport(
        tuple(reports),
        EXPECTED_HOURLY_POSITIONS,
        missing,
        null,
        negative,
        eligible,
    )


def _compile_component(
    component: str,
    payloads: tuple[Mapping[str, object], ...],
) -> tuple[
    ComponentDischargeValueSupport,
    dict[datetime, tuple[float | None, int]],
]:
    if len(payloads) != 5:
        raise ValueError("component_discharge_five_annual_payloads_required")
    by_time: dict[datetime, tuple[float | None, int]] = {}
    raw_rows = 0
    duplicates = 0
    for payload in payloads:
        rows = payload.get("values")
        if payload.get("name") != catalog.EXPECTED_SERIES_IDS[component] or not isinstance(
            rows, list
        ):
            raise ValueError("component_discharge_payload_identity_invalid")
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                raise ValueError("component_discharge_value_row_invalid")
            timestamp = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=UTC)
            raw_value = row[1]
            if raw_value is not None and (
                not isinstance(raw_value, (int, float))
                or isinstance(raw_value, bool)
                or not math.isfinite(float(raw_value))
            ):
                raise ValueError("component_discharge_value_row_invalid")
            quality = row[2]
            if not isinstance(quality, int) or isinstance(quality, bool):
                raise ValueError("component_discharge_value_row_invalid")
            value = (
                None if raw_value is None else float(raw_value),
                quality,
            )
            raw_rows += 1
            if timestamp in by_time:
                if by_time[timestamp] != value:
                    raise ValueError("component_discharge_duplicate_boundary_mismatch")
                duplicates += 1
            else:
                by_time[timestamp] = value
    expected_times = {BEGIN + timedelta(hours=index) for index in range(EXPECTED_HOURLY_POSITIONS)}
    actual_times = set(by_time)
    if not actual_times or not actual_times <= expected_times:
        raise ValueError("component_discharge_time_support_invalid")
    values = tuple(value[0] for value in by_time.values())
    real = tuple(value for value in values if value is not None)
    quality_counts = Counter(value[1] for value in by_time.values())
    report = ComponentDischargeValueSupport(
        component=component,
        series_id=catalog.EXPECTED_SERIES_IDS[component],
        annual_payload_count=len(payloads),
        raw_row_count=raw_rows,
        duplicate_boundary_row_count=duplicates,
        unique_timestamp_count=len(by_time),
        expected_hourly_position_count=EXPECTED_HOURLY_POSITIONS,
        missing_timestamp_count=len(expected_times - actual_times),
        null_value_count=sum(value is None for value in values),
        real_value_count=len(real),
        negative_value_count=sum(value < 0.0 for value in real),
        zero_value_count=sum(value == 0.0 for value in real),
        positive_value_count=sum(value > 0.0 for value in real),
        quality_code_counts=tuple(sorted(quality_counts.items())),
        earliest_timestamp_utc=_iso(min(actual_times)),
        latest_timestamp_utc=_iso(max(actual_times)),
    )
    return report, by_time


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
