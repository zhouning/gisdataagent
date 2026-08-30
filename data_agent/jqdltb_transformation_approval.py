"""Authoritative approval workflow for the AR-0 JQDLTB transformation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from .approval_case_authority import ApprovalCaseAuthority
from .platform_contracts import (
    ApprovalCase,
    JqdltbTransformationContract,
    build_jqdltb_transformation_approval_case,
    compile_jqdltb_executable_contract,
    validate_jqdltb_transformation_execution,
)


class _ApprovalWriteResult(Protocol):
    approval_case: ApprovalCase


class _ApprovalAuthority(Protocol):
    def create(self, case: ApprovalCase, *, owner_ref: str) -> _ApprovalWriteResult: ...

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase: ...


class JqdltbTransformationApprovalService:
    """Use the shared ApprovalCase authority for proposal and execution gates."""

    def __init__(self, authority: _ApprovalAuthority | None = None) -> None:
        self._authority = authority or ApprovalCaseAuthority()

    def request(
        self,
        proposal: JqdltbTransformationContract,
        *,
        case_id: str,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ApprovalCase:
        case = build_jqdltb_transformation_approval_case(
            proposal,
            case_id=case_id,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        return self._authority.create(case, owner_ref=owner_ref).approval_case

    def compile(
        self,
        proposal: JqdltbTransformationContract,
        *,
        approval_case_ref: str,
        created_by: str,
        created_at: datetime,
    ) -> JqdltbTransformationContract:
        approval_case = self._authority.get(
            proposal.tenant_id,
            approval_case_ref,
        )
        return compile_jqdltb_executable_contract(
            proposal,
            approval_case=approval_case,
            created_by=created_by,
            created_at=created_at,
        )

    def validate_execution(
        self,
        contract: JqdltbTransformationContract,
        *,
        diagnostic: dict[str, Any],
        archive_sha256: str,
        bundle_sha256: str,
        standard_version_ref: str,
        standard_fingerprint: str,
        source_resource_version_id: UUID,
        semantic_candidate_audit: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        if contract.approval_case is None:
            raise ValueError("JQDLTB executable contract is missing its ApprovalCase")
        authoritative = self._authority.get(
            contract.tenant_id,
            contract.approval_case.approval_case_ref,
        )
        validate_jqdltb_transformation_execution(
            contract,
            authoritative_approval_case=authoritative,
            diagnostic=diagnostic,
            archive_sha256=archive_sha256,
            bundle_sha256=bundle_sha256,
            standard_version_ref=standard_version_ref,
            standard_fingerprint=standard_fingerprint,
            source_resource_version_id=source_resource_version_id,
            semantic_candidate_audit=semantic_candidate_audit,
            now=now,
        )


__all__ = ["JqdltbTransformationApprovalService"]
