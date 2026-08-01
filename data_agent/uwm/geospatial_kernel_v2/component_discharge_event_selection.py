"""Outcome-blind event selection from synchronized component discharge."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import fmean

from data_agent.uwm.geospatial_kernel_v2 import (
    component_discharge_value_support as value_support,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    cwms_component_discharge_catalog as catalog,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    release_excitation_identifiability as excitation,
)

SCHEMA = "gwm.geospatial.component_discharge_event_selection.v1"
EVENT_BEFORE_STEP_HOURS = 24
EVENT_AFTER_STEP_HOURS = 48
INCLUSIVE_WINDOW_VALUE_COUNT = 73
MINIMUM_ABSOLUTE_STEP_M3S = 50.0
MINIMUM_WINDOW_RANGE_M3S = 100.0
ANTECEDENT_HOURS = 24
HIGH_FLOW_THRESHOLD_M3S = 200.0
MINIMUM_EVENT_SEPARATION_DAYS = 180
STRATUM_ORDER = (
    "high_increase",
    "high_decrease",
    "low_increase",
    "low_decrease",
)


@dataclass(frozen=True)
class ComponentDischargeEventSelection:
    support: value_support.SynchronizedComponentDischargeSupport
    total_value_count: int
    excluded_interval_count: int
    candidates: tuple[dict[str, object], ...]
    selected_events: tuple[dict[str, object], ...]
    component_gate_candidate_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        strata = tuple(str(value["selection_stratum"]) for value in self.selected_events)
        if (
            not self.support.synchronized_support_complete
            or self.total_value_count != value_support.EXPECTED_HOURLY_POSITIONS
            or self.excluded_interval_count <= 0
            or strata != STRATUM_ORDER
            or len(self.selected_events) != len(STRATUM_ORDER)
            or tuple(key for key, _ in self.component_gate_candidate_counts)
            != catalog.EXPECTED_COMPONENTS
            or any(count < 0 for _, count in self.component_gate_candidate_counts)
        ):
            raise ValueError("component_discharge_event_selection_invalid")

    @property
    def candidate_counts_by_stratum(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(str(value["selection_stratum"]) for value in self.candidates)
        return tuple((key, counts[key]) for key in STRATUM_ORDER)

    @property
    def selected_dominant_components(self) -> tuple[str, ...]:
        return tuple(str(value["dominant_step_component"]) for value in self.selected_events)

    @property
    def synchronized_total_derivation_admissible(self) -> bool:
        return self.support.synchronized_support_complete and self.total_value_count == 43_825

    @property
    def total_discharge_events_admissible(self) -> bool:
        return len(self.selected_events) == 4 and all(
            value["release_excitation_identifiability"]["blind_response_test_admissible"]
            is True
            for value in self.selected_events
        )

    @property
    def non_turbine_component_contrast_admissible(self) -> bool:
        counts = dict(self.component_gate_candidate_counts)
        return any(counts[component] > 0 for component in catalog.EXPECTED_COMPONENTS[:-1])

    def require_quality_approval_semantics(self) -> None:
        raise ValueError("component_event_quality_code_approval_semantics_unadmitted")

    def require_non_turbine_component_contrast(self) -> None:
        if not self.non_turbine_component_contrast_admissible:
            raise ValueError("component_event_non_turbine_contrast_unadmitted")

    def require_gate_command(self) -> None:
        raise ValueError("component_event_gate_command_unadmitted")

    def require_human_action(self) -> None:
        raise ValueError("component_event_human_action_unadmitted")

    def require_observed_downstream_response(self) -> None:
        raise ValueError("component_event_downstream_response_unadmitted")

    def require_causal_intervention(self) -> None:
        raise ValueError("component_event_causal_intervention_unadmitted")

    def require_physical_response_time(self) -> None:
        raise ValueError("component_event_physical_response_time_unadmitted")

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("component_event_runtime_operator_unadmitted")

    def as_dict(self, *, include_candidates: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "schema": SCHEMA,
            "role": "source_only_component_total_discharge_event_selection",
            "total_derivation": {
                "component_order": list(catalog.EXPECTED_COMPONENTS),
                "formula": "orifice_plus_sluice_plus_spillway_plus_turbine",
                "unit": "cms",
                "timestamp_join": "exact_utc_hour",
                "missing_value_policy": "reject_without_filling",
                "total_value_count": self.total_value_count,
                "synchronized_total_derivation_admissible": (
                    self.synchronized_total_derivation_admissible
                ),
            },
            "excluded_interval_count": self.excluded_interval_count,
            "eligible_candidate_count": len(self.candidates),
            "candidate_counts_by_stratum": dict(self.candidate_counts_by_stratum),
            "component_gate_candidate_counts": dict(self.component_gate_candidate_counts),
            "selected_event_count": len(self.selected_events),
            "selected_dominant_components": list(self.selected_dominant_components),
            "selected_events": list(self.selected_events),
            "claim_boundary": {
                "synchronized_total_discharge_derivation_admitted": (
                    self.synchronized_total_derivation_admissible
                ),
                "source_only_total_discharge_events_admitted": (
                    self.total_discharge_events_admissible
                ),
                "quality_code_approval_semantics_admitted": False,
                "non_turbine_component_contrast_admitted": (
                    self.non_turbine_component_contrast_admissible
                ),
                "gate_command_admitted": False,
                "human_action_admitted": False,
                "observed_downstream_response_admitted": False,
                "causal_intervention_admitted": False,
                "physical_response_time_admitted": False,
                "runtime_operator_admitted": False,
            },
        }
        if include_candidates:
            result["eligible_candidates"] = list(self.candidates)
        return result


def compile_component_discharge_event_selection(
    payloads_by_component: Mapping[str, tuple[Mapping[str, object], ...]],
    *,
    excluded_event_times_utc: Sequence[str],
    excluded_windows_utc: Sequence[tuple[str, str]],
    exclusion_radius_days: int,
) -> ComponentDischargeEventSelection:
    if exclusion_radius_days <= 0 or not excluded_event_times_utc:
        raise ValueError("component_event_positive_exclusion_boundary_required")
    support = value_support.compile_synchronized_component_discharge_support(
        payloads_by_component
    )
    values_by_component = {
        component: value_support._compile_component(  # noqa: SLF001
            component, payloads_by_component[component]
        )[1]
        for component in catalog.EXPECTED_COMPONENTS
    }
    times = tuple(sorted(values_by_component[catalog.EXPECTED_COMPONENTS[0]]))
    if len(times) != value_support.EXPECTED_HOURLY_POSITIONS:
        raise ValueError("component_event_complete_time_axis_required")
    component_values = {
        component: tuple(
            _required_value(values_by_component[component][timestamp][0])
            for timestamp in times
        )
        for component in catalog.EXPECTED_COMPONENTS
    }
    component_quality = {
        component: tuple(
            int(values_by_component[component][timestamp][1]) for timestamp in times
        )
        for component in catalog.EXPECTED_COMPONENTS
    }
    totals = tuple(
        sum(component_values[component][index] for component in catalog.EXPECTED_COMPONENTS)
        for index in range(len(times))
    )
    excluded_intervals = _excluded_intervals(
        excluded_event_times_utc,
        excluded_windows_utc,
        exclusion_radius_days,
    )
    candidates = _compile_candidates(
        times,
        totals,
        component_values,
        component_quality,
        excluded_intervals,
    )
    selected = _select_candidates(candidates)
    component_counts = tuple(
        (
            component,
            _count_component_gate_candidates(
                times,
                component_values[component],
                excluded_intervals,
            ),
        )
        for component in catalog.EXPECTED_COMPONENTS
    )
    return ComponentDischargeEventSelection(
        support,
        len(totals),
        len(excluded_intervals),
        candidates,
        selected,
        component_counts,
    )


def _compile_candidates(
    times: tuple[datetime, ...],
    totals: tuple[float, ...],
    component_values: Mapping[str, tuple[float, ...]],
    component_quality: Mapping[str, tuple[int, ...]],
    excluded_intervals: tuple[tuple[datetime, datetime], ...],
) -> tuple[dict[str, object], ...]:
    candidates = []
    for index in range(EVENT_BEFORE_STEP_HOURS, len(times) - EVENT_AFTER_STEP_HOURS):
        signed_step = totals[index] - totals[index - 1]
        if abs(signed_step) < MINIMUM_ABSOLUTE_STEP_M3S:
            continue
        window_start = index - EVENT_BEFORE_STEP_HOURS
        window_end = index + EVENT_AFTER_STEP_HOURS
        if not _window_is_eligible(times, window_start, window_end, excluded_intervals):
            continue
        window = totals[window_start : window_end + 1]
        window_range = max(window) - min(window)
        if window_range < MINIMUM_WINDOW_RANGE_M3S:
            continue
        source_support = excitation.compile_release_excitation_identifiability(window)
        if not source_support.blind_response_test_admissible:
            continue
        component_steps = {
            component: component_values[component][index]
            - component_values[component][index - 1]
            for component in catalog.EXPECTED_COMPONENTS
        }
        dominant = min(
            catalog.EXPECTED_COMPONENTS,
            key=lambda component: (
                -abs(component_steps[component]),
                catalog.EXPECTED_COMPONENTS.index(component),
            ),
        )
        antecedent_mean = fmean(totals[index - ANTECEDENT_HOURS : index])
        flow_class = "high" if antecedent_mean >= HIGH_FLOW_THRESHOLD_M3S else "low"
        direction = "increase" if signed_step > 0.0 else "decrease"
        candidates.append(
            {
                "step_time_utc": _iso(times[index]),
                "source_time_support_offsets_minutes": [-60, 0],
                "start_utc": _iso(times[window_start]),
                "end_utc": _iso(times[window_end]),
                "inclusive_total_value_count": len(window),
                "total_before_step_m3s": totals[index - 1],
                "total_at_step_m3s": totals[index],
                "signed_total_step_m3s": signed_step,
                "absolute_total_step_m3s": abs(signed_step),
                "total_direction": direction,
                "antecedent_total_mean_m3s": antecedent_mean,
                "antecedent_flow_class": flow_class,
                "selection_stratum": f"{flow_class}_{direction}",
                "total_window_range_m3s": window_range,
                "component_values_before_step_m3s": {
                    component: component_values[component][index - 1]
                    for component in catalog.EXPECTED_COMPONENTS
                },
                "component_values_at_step_m3s": {
                    component: component_values[component][index]
                    for component in catalog.EXPECTED_COMPONENTS
                },
                "component_signed_steps_m3s": component_steps,
                "active_step_components": [
                    component
                    for component in catalog.EXPECTED_COMPONENTS
                    if abs(component_steps[component]) > 1e-12
                ],
                "dominant_step_component": dominant,
                "component_quality_codes_in_window": {
                    component: sorted(
                        set(component_quality[component][window_start : window_end + 1])
                    )
                    for component in catalog.EXPECTED_COMPONENTS
                },
                "quality_codes_interpreted_as_approval": False,
                "release_excitation_identifiability": source_support.as_dict(),
            }
        )
    candidates.sort(key=_candidate_rank)
    return tuple(candidates)


def _candidate_rank(value: Mapping[str, object]) -> tuple[object, ...]:
    source = value["release_excitation_identifiability"]
    assert isinstance(source, Mapping)
    return (
        STRATUM_ORDER.index(str(value["selection_stratum"])),
        -int(source["excursion_support_hours"]),
        -float(source["normalized_excitation_volume_step_hours"]),
        float(source["lag_design_condition_number"]),
        -float(value["absolute_total_step_m3s"]),
        str(value["step_time_utc"]),
    )


def _select_candidates(
    candidates: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    selected: list[dict[str, object]] = []
    separation = timedelta(days=MINIMUM_EVENT_SEPARATION_DAYS)
    for stratum in STRATUM_ORDER:
        candidate = next(
            (
                value
                for value in candidates
                if value["selection_stratum"] == stratum
                and all(
                    abs(
                        _parse_time(str(value["step_time_utc"]))
                        - _parse_time(str(prior["step_time_utc"]))
                    )
                    >= separation
                    for prior in selected
                )
            ),
            None,
        )
        if candidate is None:
            raise ValueError(f"component_event_stratum_unavailable:{stratum}")
        step_time = _parse_time(str(candidate["step_time_utc"]))
        selected.append(
            {
                **candidate,
                "event_id": f"component_total_step_{step_time:%Y%m%dT%H%MZ}",
                "role": "blind_component_total_discharge_event",
                "selection_rank": len(selected) + 1,
                "selected_without_downstream_values": True,
                "source_and_target_operators_frozen_before_event_manifest": True,
            }
        )
    return tuple(selected)


def _count_component_gate_candidates(
    times: tuple[datetime, ...],
    values: tuple[float, ...],
    excluded_intervals: tuple[tuple[datetime, datetime], ...],
) -> int:
    count = 0
    for index in range(EVENT_BEFORE_STEP_HOURS, len(times) - EVENT_AFTER_STEP_HOURS):
        if abs(values[index] - values[index - 1]) < MINIMUM_ABSOLUTE_STEP_M3S:
            continue
        start = index - EVENT_BEFORE_STEP_HOURS
        end = index + EVENT_AFTER_STEP_HOURS
        if not _window_is_eligible(times, start, end, excluded_intervals):
            continue
        window = values[start : end + 1]
        if max(window) - min(window) < MINIMUM_WINDOW_RANGE_M3S:
            continue
        if excitation.compile_release_excitation_identifiability(
            window
        ).blind_response_test_admissible:
            count += 1
    return count


def _window_is_eligible(
    times: tuple[datetime, ...],
    start_index: int,
    end_index: int,
    excluded_intervals: tuple[tuple[datetime, datetime], ...],
) -> bool:
    start = times[start_index]
    end = times[end_index]
    expected = tuple(
        start + timedelta(hours=offset)
        for offset in range(end_index - start_index + 1)
    )
    if times[start_index : end_index + 1] != expected:
        return False
    return not any(
        start <= excluded_end and end >= excluded_start
        for excluded_start, excluded_end in excluded_intervals
    )


def _excluded_intervals(
    event_times: Sequence[str],
    windows: Sequence[tuple[str, str]],
    radius_days: int,
) -> tuple[tuple[datetime, datetime], ...]:
    radius = timedelta(days=radius_days)
    intervals = [
        (_parse_time(value) - radius, _parse_time(value) + radius) for value in event_times
    ]
    for start_raw, end_raw in windows:
        start = _parse_time(start_raw)
        end = _parse_time(end_raw)
        if start > end:
            raise ValueError("component_event_exclusion_window_invalid")
        intervals.append((start - radius, end + radius))
    return tuple(intervals)


def _required_value(value: float | None) -> float:
    if value is None:
        raise ValueError("component_event_real_value_required")
    return float(value)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("component_event_timezone_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
