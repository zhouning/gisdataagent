"""Outcome-free dynamic transfer response metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


TRANSFER_RESPONSE_METRICS_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_transfer_response_metrics.v1"
)
TRANSFER_RESPONSE_QUANTILES = (0.01, 0.05, 0.50, 0.95)


@dataclass(frozen=True)
class DynamicTransferResponseMetrics:
    """Volume-consistent timing and conservation metrics for a perturbation."""

    timestep_seconds: float
    sample_count: int
    input_volume_m3: float
    final_incremental_storage_m3: float
    positive_outlet_volume_m3: float
    negative_outlet_volume_m3: float
    net_outlet_volume_m3: float
    mass_balance_residual_m3: float
    mass_balance_tolerance_m3: float
    positive_recovered_fraction: float
    net_recovered_fraction: float
    negative_to_positive_volume_ratio: float
    peak_positive_response_m3s: float
    peak_positive_interval_end_seconds: float | None
    minimum_response_m3s: float
    center_of_positive_response_seconds: float | None
    first_arrival_above_threshold_seconds: float | None
    response_threshold_m3s: float
    within_window_positive_volume_quantile_seconds: tuple[
        tuple[str, float | None], ...
    ]
    input_recovery_quantile_seconds: tuple[tuple[str, float | None], ...]
    negative_lobe_tolerance_m3: float
    negative_lobe_within_tolerance: bool
    mass_balance_passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": TRANSFER_RESPONSE_METRICS_SCHEMA,
            "response_rate_semantics": "interval_mean_incremental_outlet_flow",
            "quantile_time_semantics": (
                "linear interpolation within each constant-rate interval"
            ),
            "timestep_seconds": self.timestep_seconds,
            "sample_count": self.sample_count,
            "input_volume_m3": self.input_volume_m3,
            "final_incremental_storage_m3": self.final_incremental_storage_m3,
            "positive_outlet_volume_m3": self.positive_outlet_volume_m3,
            "negative_outlet_volume_m3": self.negative_outlet_volume_m3,
            "net_outlet_volume_m3": self.net_outlet_volume_m3,
            "mass_balance_residual_m3": self.mass_balance_residual_m3,
            "mass_balance_tolerance_m3": self.mass_balance_tolerance_m3,
            "mass_balance_residual_to_input_ratio": (
                abs(self.mass_balance_residual_m3) / self.input_volume_m3
            ),
            "positive_recovered_fraction": self.positive_recovered_fraction,
            "net_recovered_fraction": self.net_recovered_fraction,
            "negative_to_positive_volume_ratio": (
                self.negative_to_positive_volume_ratio
            ),
            "peak_positive_response_m3s": self.peak_positive_response_m3s,
            "peak_positive_interval_end_seconds": (
                self.peak_positive_interval_end_seconds
            ),
            "minimum_response_m3s": self.minimum_response_m3s,
            "center_of_positive_response_seconds": (
                self.center_of_positive_response_seconds
            ),
            "first_arrival_above_threshold_seconds": (
                self.first_arrival_above_threshold_seconds
            ),
            "response_threshold_m3s": self.response_threshold_m3s,
            "within_window_positive_volume_quantile_seconds": dict(
                self.within_window_positive_volume_quantile_seconds
            ),
            "within_window_quantile_basis": (
                "positive outlet-response volume recovered inside the simulated window"
            ),
            "input_recovery_quantile_seconds": dict(
                self.input_recovery_quantile_seconds
            ),
            "input_recovery_quantile_basis": (
                "net cumulative outlet-response volume divided by input volume; "
                "null means the fraction was not reached inside the window"
            ),
            "negative_lobe_tolerance_m3": self.negative_lobe_tolerance_m3,
            "negative_lobe_within_tolerance": self.negative_lobe_within_tolerance,
            "mass_balance_passed": self.mass_balance_passed,
        }


def analyze_dynamic_transfer_response(
    incremental_outlet_flow_m3s: tuple[float, ...] | list[float] | np.ndarray,
    *,
    timestep_seconds: float,
    input_volume_m3: float,
    final_incremental_storage_m3: float,
    response_threshold_m3s: float = 1e-6,
    absolute_mass_tolerance_m3: float = 1e-5,
    relative_mass_tolerance: float = 1e-9,
    negative_lobe_relative_tolerance: float = 1e-9,
) -> DynamicTransferResponseMetrics:
    """Summarize an interval-mean outlet response without clipping negative lobes."""

    response = np.asarray(incremental_outlet_flow_m3s, dtype=float)
    scalar_values = (
        timestep_seconds,
        input_volume_m3,
        final_incremental_storage_m3,
        response_threshold_m3s,
        absolute_mass_tolerance_m3,
        relative_mass_tolerance,
        negative_lobe_relative_tolerance,
    )
    if response.ndim != 1 or response.size == 0 or not np.isfinite(response).all():
        raise ValueError("transfer_response_must_be_nonempty_finite_vector")
    if not np.isfinite(scalar_values).all():
        raise ValueError("transfer_response_parameters_must_be_finite")
    if timestep_seconds <= 0.0 or input_volume_m3 <= 0.0:
        raise ValueError("transfer_response_timestep_and_input_must_be_positive")
    if (
        response_threshold_m3s < 0.0
        or absolute_mass_tolerance_m3 < 0.0
        or relative_mass_tolerance < 0.0
        or negative_lobe_relative_tolerance < 0.0
    ):
        raise ValueError("transfer_response_tolerances_must_be_nonnegative")

    dt = float(timestep_seconds)
    positive_rates = np.maximum(response, 0.0)
    negative_rates = np.maximum(-response, 0.0)
    positive_volumes = positive_rates * dt
    signed_volumes = response * dt
    positive_volume = float(positive_volumes.sum())
    negative_volume = float((negative_rates * dt).sum())
    net_volume = float(signed_volumes.sum())
    storage = float(final_incremental_storage_m3)
    input_volume = float(input_volume_m3)
    mass_residual = input_volume - net_volume - storage
    mass_tolerance = float(
        absolute_mass_tolerance_m3
        + relative_mass_tolerance
        * max(input_volume, abs(net_volume), abs(storage), 1.0)
    )
    negative_tolerance = float(
        absolute_mass_tolerance_m3
        + negative_lobe_relative_tolerance * input_volume
    )

    peak_index = int(np.argmax(positive_rates))
    peak = float(positive_rates[peak_index])
    positive_center = (
        None
        if positive_volume <= 0.0
        else float(
            np.sum(
                (np.arange(response.size, dtype=float) + 0.5)
                * dt
                * positive_volumes
            )
            / positive_volume
        )
    )
    arrivals = np.flatnonzero(response > response_threshold_m3s)
    first_arrival = (
        None if arrivals.size == 0 else float((int(arrivals[0]) + 1) * dt)
    )
    window_quantiles = tuple(
        (
            _quantile_name(quantile),
            _volume_quantile_time(positive_volumes, quantile, dt),
        )
        for quantile in TRANSFER_RESPONSE_QUANTILES
    )
    input_quantiles = tuple(
        (
            _quantile_name(quantile),
            _first_net_recovery_time(
                signed_volumes, quantile * input_volume, dt
            ),
        )
        for quantile in TRANSFER_RESPONSE_QUANTILES
    )
    return DynamicTransferResponseMetrics(
        timestep_seconds=dt,
        sample_count=int(response.size),
        input_volume_m3=input_volume,
        final_incremental_storage_m3=storage,
        positive_outlet_volume_m3=positive_volume,
        negative_outlet_volume_m3=negative_volume,
        net_outlet_volume_m3=net_volume,
        mass_balance_residual_m3=float(mass_residual),
        mass_balance_tolerance_m3=mass_tolerance,
        positive_recovered_fraction=positive_volume / input_volume,
        net_recovered_fraction=net_volume / input_volume,
        negative_to_positive_volume_ratio=(
            negative_volume / positive_volume if positive_volume > 0.0 else 0.0
        ),
        peak_positive_response_m3s=peak,
        peak_positive_interval_end_seconds=(
            float((peak_index + 1) * dt) if peak > 0.0 else None
        ),
        minimum_response_m3s=float(response.min()),
        center_of_positive_response_seconds=positive_center,
        first_arrival_above_threshold_seconds=first_arrival,
        response_threshold_m3s=float(response_threshold_m3s),
        within_window_positive_volume_quantile_seconds=window_quantiles,
        input_recovery_quantile_seconds=input_quantiles,
        negative_lobe_tolerance_m3=negative_tolerance,
        negative_lobe_within_tolerance=negative_volume <= negative_tolerance,
        mass_balance_passed=abs(mass_residual) <= mass_tolerance,
    )


def _quantile_name(quantile: float) -> str:
    return f"t{round(100 * quantile):02d}"


def _volume_quantile_time(
    interval_volumes: np.ndarray, quantile: float, timestep_seconds: float
) -> float | None:
    total = float(interval_volumes.sum())
    if total <= 0.0:
        return None
    target = quantile * total
    cumulative_before = 0.0
    for index, volume in enumerate(interval_volumes):
        current = float(volume)
        if current > 0.0 and cumulative_before + current >= target:
            fraction = (target - cumulative_before) / current
            return float((index + fraction) * timestep_seconds)
        cumulative_before += current
    return float(interval_volumes.size * timestep_seconds)


def _first_net_recovery_time(
    signed_interval_volumes: np.ndarray,
    target_volume: float,
    timestep_seconds: float,
) -> float | None:
    cumulative_before = 0.0
    for index, volume in enumerate(signed_interval_volumes):
        cumulative_after = cumulative_before + float(volume)
        if cumulative_before < target_volume <= cumulative_after:
            fraction = (target_volume - cumulative_before) / float(volume)
            return float((index + fraction) * timestep_seconds)
        cumulative_before = cumulative_after
    return None
