import json
from uuid import uuid4

import pytest

from data_agent.spatial_anonymization_receipt import (
    SPATIAL_ANONYMIZATION_RECEIPT_SCHEMA,
    SpatialAnonymizationReceipt,
    SpatialAnonymizationReceiptError,
    normalize_security_receipt_context,
)


def _receipt(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "attempt_id": uuid4(),
        "source_schema": "geo",
        "source_table": "roads",
        "output_schema": "public",
        "output_table": "roads_grid",
        "data_type": "polygon",
        "level": "L3",
        "output_row_count": 12,
    }
    values.update(overrides)
    return SpatialAnonymizationReceipt.succeeded(**values)


def test_receipt_round_trip_has_stable_hash():
    receipt = _receipt()

    parsed = SpatialAnonymizationReceipt.parse(receipt.canonical_json())

    assert parsed == receipt
    assert parsed.schema == SPATIAL_ANONYMIZATION_RECEIPT_SCHEMA
    assert parsed.spatial_index == "roads_grid_geom_gist"
    assert parsed.sha256 == receipt.sha256
    assert len(receipt.sha256) == 64


@pytest.mark.parametrize(
    ("tenant_id", "attempt_id", "message"),
    [
        (None, uuid4(), "tenant_id"),
        ("tenant-a", None, "attempt_id"),
        ("Tenant A", uuid4(), "tenant_id"),
        ("tenant-a", "not-a-uuid", "attempt_id"),
    ],
)
def test_security_context_rejects_partial_or_invalid_values(
    tenant_id, attempt_id, message
):
    with pytest.raises(SpatialAnonymizationReceiptError, match=message):
        normalize_security_receipt_context(tenant_id, attempt_id)


def test_security_context_is_optional_for_legacy_callers():
    assert normalize_security_receipt_context(None, None) is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"data_type": "line"}, "data_type"),
        ({"level": "L9"}, "level"),
        ({"output_row_count": -1}, "output_row_count"),
        ({"output_table": 'roads";DROP'}, "output_table"),
    ],
)
def test_receipt_rejects_invalid_completion_evidence(overrides, message):
    with pytest.raises(SpatialAnonymizationReceiptError, match=message):
        _receipt(**overrides)


def test_parse_rejects_changed_constants_and_extra_fields():
    payload = _receipt().as_dict()
    payload["status"] = "failure"

    with pytest.raises(SpatialAnonymizationReceiptError, match="constants"):
        SpatialAnonymizationReceipt.parse(json.dumps(payload))

    payload = _receipt().as_dict()
    payload["extra"] = True
    with pytest.raises(SpatialAnonymizationReceiptError, match="fields"):
        SpatialAnonymizationReceipt.parse(json.dumps(payload))


def test_long_output_name_uses_postgresql_truncated_index_identifier():
    receipt = _receipt(output_table="道" * 21)

    assert len(receipt.spatial_index.encode("utf-8")) <= 63
    assert receipt.spatial_index.encode("utf-8").decode("utf-8")
