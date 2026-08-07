"""Bridge successful connector certifications into the schema drift ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .source_connector_governance import (
    CertificationStatus,
    ConnectorCertificationReport,
    SchemaDriftEvent,
    detect_schema_drift,
)
from .source_schema_drift_ledger import SchemaDriftWriteResult


class SchemaDriftLedgerWriter(Protocol):
    def record(
        self,
        *,
        tenant_id: str,
        source_definition_fingerprint: str,
        event: SchemaDriftEvent,
        detected_by: str,
        detected_at=None,
    ) -> SchemaDriftWriteResult: ...


@dataclass(frozen=True)
class SchemaDriftObservation:
    event: SchemaDriftEvent | None
    write_result: SchemaDriftWriteResult | None


def observe_certification_schema_drift(
    *,
    tenant_id: str,
    previous: ConnectorCertificationReport,
    current: ConnectorCertificationReport,
    ledger: SchemaDriftLedgerWriter,
    detected_by: str,
) -> SchemaDriftObservation:
    """Persist drift only between successful runs of one immutable source definition."""

    if (
        previous.status is not CertificationStatus.PASSED
        or current.status is not CertificationStatus.PASSED
    ):
        raise ValueError("schema drift observation requires two passed certifications")
    if previous.discovery is None or current.discovery is None:
        raise ValueError("schema drift observation requires two discovery snapshots")
    if previous.source_id != current.source_id:
        raise ValueError("schema drift observation cannot cross source identities")
    if previous.source_definition_fingerprint != current.source_definition_fingerprint:
        raise ValueError("schema drift observation requires one immutable source definition")
    if previous.connector_id != current.connector_id:
        raise ValueError("schema drift observation cannot cross connector identities")
    if previous.provider != current.provider:
        raise ValueError("schema drift observation cannot cross provider identities")
    if not detected_by.strip():
        raise ValueError("detected_by is required")

    event = detect_schema_drift(
        current.source_id,
        previous.discovery,
        current.discovery,
    )
    if event is None:
        return SchemaDriftObservation(event=None, write_result=None)
    write_result = ledger.record(
        tenant_id=tenant_id,
        source_definition_fingerprint=current.source_definition_fingerprint,
        event=event,
        detected_by=detected_by,
        detected_at=current.certified_at,
    )
    return SchemaDriftObservation(event=event, write_result=write_result)
