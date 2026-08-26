"""Abu Dhabi Zone B design-storm data and deterministic hyetographs.

The values are transcribed from the user-supplied extract of the Abu Dhabi
2022 official publication, Table 3-6.  The table supplies IDF/DDF values, not
an authoritative temporal storm profile.  This module therefore keeps the
published depths separate from the explicit interpolation and alternating
block assumptions used to obtain a five-minute SWMM time series.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any


ZONE_B_TABLE_TITLE = "Table 3-6 - Recommended IDF and DDF tables for use in Zone B"
ZONE_B_SOURCE_YEAR = 2022
ZONE_B_EVIDENCE_SHA256 = "9c202a935230b9d527d9b842f568beb7f531a96ec6d65d6413aded0ba09b0bc9"
ZONE_B_DURATIONS_MINUTES = (5, 10, 15, 30, 60, 120, 180, 360, 720, 1440)

# Published rainfall depth (mm), keyed by return period in years.
ZONE_B_DDF_DEPTH_MM: dict[int, tuple[float, ...]] = {
    2: (4.02, 4.93, 5.53, 6.76, 8.25, 10.08, 11.31, 13.80, 16.92, 20.64),
    5: (9.39, 11.44, 12.76, 15.44, 18.68, 22.60, 25.29, 30.60, 36.96, 44.88),
    10: (10.59, 12.92, 14.43, 17.48, 21.18, 25.68, 28.71, 34.80, 42.24, 51.12),
    25: (15.69, 18.93, 21.02, 25.21, 30.24, 36.26, 40.35, 48.36, 58.08, 69.60),
    50: (23.03, 27.05, 29.56, 34.51, 40.28, 47.02, 51.48, 60.12, 70.20, 81.84),
    100: (26.99, 31.70, 34.64, 40.44, 47.21, 55.12, 60.33, 70.44, 82.20, 96.00),
}

# Published mean intensity (mm/h).  Keeping it independently avoids hiding
# small rounding differences between the two printed halves of the table.
ZONE_B_IDF_INTENSITY_MM_PER_HOUR: dict[int, tuple[float, ...]] = {
    2: (48.39, 29.54, 22.13, 13.51, 8.25, 5.04, 3.77, 2.30, 1.41, 0.86),
    5: (113.18, 68.48, 51.04, 30.88, 18.68, 11.30, 8.43, 5.10, 3.08, 1.87),
    10: (127.64, 77.34, 57.70, 34.96, 21.18, 12.84, 9.57, 5.80, 3.52, 2.13),
    25: (189.05, 113.38, 84.07, 50.42, 30.24, 18.13, 13.45, 8.06, 4.84, 2.90),
    50: (277.48, 161.98, 118.22, 69.01, 40.28, 23.51, 17.16, 10.02, 5.85, 3.41),
    100: (325.17, 189.81, 138.54, 80.87, 47.21, 27.56, 20.11, 11.74, 6.85, 4.00),
}

SUPPORTED_RETURN_PERIODS = tuple(sorted(ZONE_B_DDF_DEPTH_MM))


def official_depth_mm(return_period_years: int, duration_minutes: int = 180) -> float:
    """Return an exact published DDF depth at a tabulated duration."""

    if return_period_years not in ZONE_B_DDF_DEPTH_MM:
        raise ValueError("zone_b_return_period_not_supported")
    try:
        position = ZONE_B_DURATIONS_MINUTES.index(duration_minutes)
    except ValueError as error:
        raise ValueError("zone_b_duration_not_tabulated") from error
    return ZONE_B_DDF_DEPTH_MM[return_period_years][position]


def _interpolated_depths(
    return_period_years: int,
    *,
    duration_minutes: int,
    step_minutes: int,
) -> list[float]:
    """Interpolate cumulative DDF depths on log-duration/log-depth axes."""

    if duration_minutes != 180 or step_minutes != 5:
        raise ValueError("zone_b_abm_requires_180_minutes_and_5_minute_step")
    published_durations = ZONE_B_DURATIONS_MINUTES[:7]
    published_depths = ZONE_B_DDF_DEPTH_MM[return_period_years][:7]
    result: list[float] = []
    for duration in range(step_minutes, duration_minutes + step_minutes, step_minutes):
        if duration in published_durations:
            result.append(published_depths[published_durations.index(duration)])
            continue
        upper_index = next(index for index, value in enumerate(published_durations) if value > duration)
        lower_duration = published_durations[upper_index - 1]
        upper_duration = published_durations[upper_index]
        lower_depth = published_depths[upper_index - 1]
        upper_depth = published_depths[upper_index]
        ratio = (
            (math.log(duration) - math.log(lower_duration))
            / (math.log(upper_duration) - math.log(lower_duration))
        )
        result.append(math.exp(math.log(lower_depth) + ratio * (math.log(upper_depth) - math.log(lower_depth))))
    return result


def zone_b_180_minute_hyetograph(
    return_period_years: int,
    *,
    start: datetime,
    peak_position_percent: float = 40.0,
    tail_minutes: int = 0,
) -> tuple[list[tuple[datetime, float]], dict[str, Any]]:
    """Build a five-minute alternating-block storm from published Zone B DDF.

    Values returned to SWMM are intensity in mm/h.  The largest incremental
    block is placed nearest the requested peak position, followed by blocks in
    descending order alternating after and before the peak.
    """

    if return_period_years not in ZONE_B_DDF_DEPTH_MM:
        raise ValueError("zone_b_return_period_not_supported")
    if not 0.0 <= peak_position_percent <= 100.0:
        raise ValueError("zone_b_peak_position_invalid")
    cumulative = _interpolated_depths(
        return_period_years,
        duration_minutes=180,
        step_minutes=5,
    )
    increments = [cumulative[0], *[current - previous for previous, current in zip(cumulative, cumulative[1:])]]
    if any(value < -1e-9 for value in increments):
        raise ValueError("zone_b_interpolated_depth_not_monotonic")
    increments = [max(0.0, value) for value in increments]

    block_count = len(increments)
    peak_index = min(block_count - 1, max(0, round((block_count - 1) * peak_position_percent / 100.0)))
    positions = [peak_index]
    distance = 1
    while len(positions) < block_count:
        right = peak_index + distance
        left = peak_index - distance
        if right < block_count:
            positions.append(right)
        if left >= 0 and len(positions) < block_count:
            positions.append(left)
        distance += 1
    ordered_depths = [0.0] * block_count
    for depth, position in zip(sorted(increments, reverse=True), positions, strict=True):
        ordered_depths[position] = depth

    values = [
        (start + timedelta(minutes=index * 5), depth * 12.0)
        for index, depth in enumerate(ordered_depths)
    ]
    end_of_rain = start + timedelta(minutes=180)
    simulation_end = end_of_rain + timedelta(minutes=tail_minutes)
    values.append((end_of_rain, 0.0))
    if simulation_end != end_of_rain:
        values.append((simulation_end, 0.0))

    table_depths = {
        str(duration): depth
        for duration, depth in zip(
            ZONE_B_DURATIONS_MINUTES[:7],
            ZONE_B_DDF_DEPTH_MM[return_period_years][:7],
            strict=True,
        )
    }
    return values, {
        "source": "abu_dhabi_2022_official_zone_b_ddf_table_3_6",
        "source_label": "Abu Dhabi 2022 official Zone B DDF (Table 3-6)",
        "source_authority": "official_publication_user_supplied_extract",
        "source_url": None,
        "source_document_year": ZONE_B_SOURCE_YEAR,
        "source_table": ZONE_B_TABLE_TITLE,
        "source_evidence_sha256": ZONE_B_EVIDENCE_SHA256,
        "source_document_title_and_page": "pending_user_confirmation",
        "zone": "B",
        "return_period_years": return_period_years,
        "duration_minutes": 180,
        "published_mean_intensity_mm_per_hour": ZONE_B_IDF_INTENSITY_MM_PER_HOUR[return_period_years][6],
        "published_total_depth_mm": ZONE_B_DDF_DEPTH_MM[return_period_years][6],
        "published_ddf_depths_mm_through_180_minutes": table_depths,
        "native_interval_minutes": 5,
        "generated_intervals": block_count,
        "generated_total_depth_mm": float(sum(ordered_depths)),
        "peak_intensity_mm_per_hour": float(max(value for _, value in values)),
        "temporal_distribution_method": "alternating_block_from_nested_ddf_increments",
        "interpolation_method": "log_duration_log_depth_between_published_points",
        "peak_position_percent": peak_position_percent,
        "peak_position_source": "scenario_assumption_not_published_in_supplied_table_extract",
        "spatial_distribution": "uniform_zone_b_assumption_pending_authoritative_zone_geometry",
        "claim_boundary": (
            "Published DDF depths are official-source inputs; the interpolated five-minute "
            "alternating-block temporal distribution and peak position are modeling assumptions."
        ),
    }
