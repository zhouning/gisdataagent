from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RolloutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_rainfall_mm: float = Field(alias="totalRainfallMm", ge=0.0)
    duration_hours: int = Field(alias="durationHours", ge=1, le=72)

    @field_validator("total_rainfall_mm", mode="before")
    @classmethod
    def validate_total(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("totalRainfallMm must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("totalRainfallMm must be finite")
        return value

    @field_validator("duration_hours", mode="before")
    @classmethod
    def validate_duration(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("durationHours must be an integer")
        numeric = float(value)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ValueError("durationHours must be an integer")
        return int(numeric)


class CompatibilityRolloutRequest(RolloutRequest):
    event_id: str | None = Field(default=None, alias="eventId")
