"""Durable completion receipts for reconciling spatial anonymization outcomes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

SPATIAL_ANONYMIZATION_RECEIPT_SCHEMA = "gda.spatial_anonymization_receipt.v1"
_IDENTIFIER_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DATA_TYPES = frozenset({"point", "polygon"})
_LEVELS = frozenset({"L1", "L2", "L3", "L4"})


class SpatialAnonymizationReceiptError(ValueError):
    pass


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 63
        or not _IDENTIFIER_RE.fullmatch(value)
    ):
        raise SpatialAnonymizationReceiptError(f"invalid {field}")
    return value


def _identifier_with_suffix(value: str, suffix: str) -> str:
    encoded = f"{value}{suffix}".encode()[:63]
    while True:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]


def normalize_security_receipt_context(
    tenant_id: str | None,
    attempt_id: str | UUID | None,
) -> tuple[str, UUID] | None:
    if tenant_id is None and attempt_id is None:
        return None
    if not isinstance(tenant_id, str) or not _TENANT_RE.fullmatch(tenant_id):
        raise SpatialAnonymizationReceiptError("invalid security tenant_id")
    try:
        normalized_attempt_id = (
            attempt_id if isinstance(attempt_id, UUID) else UUID(str(attempt_id))
        )
    except (TypeError, ValueError, AttributeError) as error:
        raise SpatialAnonymizationReceiptError(
            "invalid security attempt_id"
        ) from error
    return tenant_id, normalized_attempt_id


@dataclass(frozen=True)
class SpatialAnonymizationReceipt:
    schema: str
    tenant_id: str
    attempt_id: UUID
    action: str
    source_schema: str
    source_table: str
    output_schema: str
    output_table: str
    spatial_index: str
    data_type: str
    level: str
    output_row_count: int
    status: str

    @classmethod
    def succeeded(
        cls,
        *,
        tenant_id: str,
        attempt_id: str | UUID,
        source_schema: str,
        source_table: str,
        output_schema: str,
        output_table: str,
        data_type: str,
        level: str,
        output_row_count: int,
    ) -> SpatialAnonymizationReceipt:
        context = normalize_security_receipt_context(tenant_id, attempt_id)
        if context is None:
            raise SpatialAnonymizationReceiptError("security context is required")
        normalized_tenant, normalized_attempt = context
        if data_type not in _DATA_TYPES:
            raise SpatialAnonymizationReceiptError("invalid data_type")
        if level not in _LEVELS:
            raise SpatialAnonymizationReceiptError("invalid level")
        if (
            isinstance(output_row_count, bool)
            or not isinstance(output_row_count, int)
            or output_row_count < 0
        ):
            raise SpatialAnonymizationReceiptError("invalid output_row_count")
        return cls(
            schema=SPATIAL_ANONYMIZATION_RECEIPT_SCHEMA,
            tenant_id=normalized_tenant,
            attempt_id=normalized_attempt,
            action="data_anonymize",
            source_schema=_identifier(source_schema, "source_schema"),
            source_table=_identifier(source_table, "source_table"),
            output_schema=_identifier(output_schema, "output_schema"),
            output_table=_identifier(output_table, "output_table"),
            spatial_index=_identifier(
                _identifier_with_suffix(output_table, "_geom_gist"),
                "spatial_index",
            ),
            data_type=data_type,
            level=level,
            output_row_count=output_row_count,
            status="success",
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attempt_id"] = str(self.attempt_id)
        return payload

    def canonical_json(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def parse(cls, value: str) -> SpatialAnonymizationReceipt:
        if not isinstance(value, str) or not value:
            raise SpatialAnonymizationReceiptError("receipt must be non-empty JSON")
        try:
            payload = json.loads(value)
        except (TypeError, ValueError) as error:
            raise SpatialAnonymizationReceiptError("receipt is invalid JSON") from error
        expected_fields = {
            "schema",
            "tenant_id",
            "attempt_id",
            "action",
            "source_schema",
            "source_table",
            "output_schema",
            "output_table",
            "spatial_index",
            "data_type",
            "level",
            "output_row_count",
            "status",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise SpatialAnonymizationReceiptError("receipt fields are invalid")
        receipt = cls.succeeded(
            tenant_id=payload["tenant_id"],
            attempt_id=payload["attempt_id"],
            source_schema=payload["source_schema"],
            source_table=payload["source_table"],
            output_schema=payload["output_schema"],
            output_table=payload["output_table"],
            data_type=payload["data_type"],
            level=payload["level"],
            output_row_count=payload["output_row_count"],
        )
        if (
            payload["schema"] != SPATIAL_ANONYMIZATION_RECEIPT_SCHEMA
            or payload["action"] != "data_anonymize"
            or payload["status"] != "success"
            or payload["spatial_index"] != receipt.spatial_index
        ):
            raise SpatialAnonymizationReceiptError("receipt constants are invalid")
        return receipt
