"""Persistent public branding configuration for the web application."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db_engine import get_engine

DEFAULT_PLATFORM_NAME = "Geospatial Data Agent"
DEFAULT_PLATFORM_SUBTITLE = "AI-Native Geospatial Data Platform"
BRANDING_NAMESPACE = "platform_branding"
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_FIELDS = {
    "platform_name": (DEFAULT_PLATFORM_NAME, 2, 80),
    "platform_subtitle": (DEFAULT_PLATFORM_SUBTITLE, 0, 120),
}


class BrandingValidationError(ValueError):
    """A branding value cannot be published to the user interface."""


class BrandingStoreUnavailable(RuntimeError):
    """The persistent branding authority is unavailable or not migrated."""


@dataclass(frozen=True)
class PlatformBranding:
    platform_name: str = DEFAULT_PLATFORM_NAME
    platform_subtitle: str = DEFAULT_PLATFORM_SUBTITLE
    updated_by: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_name": self.platform_name,
            "platform_subtitle": self.platform_subtitle,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _validate_text(field: str, value: Any) -> str:
    if field not in _FIELDS:
        raise BrandingValidationError(f"unsupported branding field: {field}")
    if not isinstance(value, str):
        raise BrandingValidationError(f"{field} must be a string")
    normalized = value.strip()
    _default, minimum, maximum = _FIELDS[field]
    if len(normalized) < minimum or len(normalized) > maximum:
        raise BrandingValidationError(
            f"{field} length must be between {minimum} and {maximum} characters"
        )
    if _CONTROL_CHARACTER_RE.search(normalized):
        raise BrandingValidationError(f"{field} cannot contain control characters")
    return normalized


def validate_branding(payload: Mapping[str, Any]) -> dict[str, str]:
    """Validate a complete branding update and return normalized values."""
    missing = [field for field in _FIELDS if field not in payload]
    if missing:
        raise BrandingValidationError(f"missing branding fields: {', '.join(missing)}")
    return {field: _validate_text(field, payload[field]) for field in _FIELDS}


def get_platform_branding() -> PlatformBranding:
    """Return persistent branding, falling back to defaults for public rendering."""
    # Branding is control-plane state; read from the primary to avoid replica lag
    # immediately after an administrator changes the visible product name.
    engine = get_engine()
    if engine is None:
        return PlatformBranding()
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT setting_key, setting_value, updated_by, updated_at
                    FROM app_platform_settings
                    WHERE namespace = :namespace
                      AND setting_key IN ('platform_name', 'platform_subtitle')
                    """
                ),
                {"namespace": BRANDING_NAMESPACE},
            ).mappings().all()
    except SQLAlchemyError:
        return PlatformBranding()

    values = {row["setting_key"]: row for row in rows}
    latest = max(rows, key=lambda row: row["updated_at"]) if rows else None
    return PlatformBranding(
        platform_name=values.get("platform_name", {}).get(
            "setting_value", DEFAULT_PLATFORM_NAME
        ),
        platform_subtitle=values.get("platform_subtitle", {}).get(
            "setting_value", DEFAULT_PLATFORM_SUBTITLE
        ),
        updated_by=latest["updated_by"] if latest else None,
        updated_at=_iso(latest["updated_at"]) if latest else None,
    )


def update_platform_branding(
    payload: Mapping[str, Any], *, updated_by: str
) -> PlatformBranding:
    """Atomically persist a complete platform branding update."""
    values = validate_branding(payload)
    actor = str(updated_by).strip()
    if not actor:
        raise BrandingValidationError("updated_by is required")
    engine = get_engine()
    if engine is None:
        raise BrandingStoreUnavailable("platform branding database is unavailable")
    try:
        with engine.begin() as connection:
            for key, value in values.items():
                connection.execute(
                    text(
                        """
                        INSERT INTO app_platform_settings (
                            namespace, setting_key, setting_value, updated_by, updated_at
                        ) VALUES (
                            :namespace, :key, :value, :updated_by, clock_timestamp()
                        )
                        ON CONFLICT (namespace, setting_key) DO UPDATE
                        SET setting_value = EXCLUDED.setting_value,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "namespace": BRANDING_NAMESPACE,
                        "key": key,
                        "value": value,
                        "updated_by": actor,
                    },
                )
    except SQLAlchemyError as exc:
        raise BrandingStoreUnavailable(
            "platform branding store is unavailable; apply migration 131"
        ) from exc

    return PlatformBranding(
        platform_name=values["platform_name"],
        platform_subtitle=values["platform_subtitle"],
        updated_by=actor,
        updated_at=datetime.now().astimezone().isoformat(),
    )
