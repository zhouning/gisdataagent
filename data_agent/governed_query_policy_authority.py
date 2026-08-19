"""Versioned policy current authority for governed semantic queries.

The query security contract intentionally consumes a callback-time reader.  This
module provides a small development authority that can back that reader without
falling back to a static ``allow`` fixture.  Policy versions and revocations are
append-only from the authority's point of view; current evaluation is derived at
read time from the immutable records.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import _sqlstate
from .db_engine import get_engine
from .governed_query_security import (
    GovernedQuerySecurityAuditPort,
    GovernedQuerySecurityCurrentReader,
    GovernedQuerySecurityDecision,
    GovernedQuerySecurityRequest,
    InMemoryGovernedQuerySecurityAudit,
    SecurityEventLedgerGovernedQueryAudit,
    _fingerprint,
    configure_governed_query_security_port_resolver,
    governed_query_security_required,
    governed_query_security_resolver_configured,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    SubjectType,
    TenantId,
)
from .security_event_ledger import SecurityEventLedger
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "190_governed_query_policy_authority.sql"
)
GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATIONS = (
    GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATION,
    Path(__file__).resolve().parent
    / "migrations"
    / "191_governed_query_policy_controlled_writes.sql",
)


class GovernedQueryPolicyAuthorityError(RuntimeError):
    """Base error for the policy current authority."""


class GovernedQueryPolicyAuthorityValidationError(  # noqa: N818
    GovernedQueryPolicyAuthorityError
):
    """A policy, purpose, or request binding is invalid."""


class GovernedQueryPolicyAuthorityConflictError(  # noqa: N818
    GovernedQueryPolicyAuthorityError
):
    """An immutable identity was published with different content."""


class GovernedQueryPolicyAuthorityForbiddenError(  # noqa: N818
    GovernedQueryPolicyAuthorityError
):
    """A policy or purpose belongs to another tenant."""


class GovernedQueryPolicyAuthorityConfigurationError(  # noqa: N818
    GovernedQueryPolicyAuthorityError
):
    """The configured database cannot serve the policy authority."""


class GovernedQueryPolicyAuthorityUnavailableError(  # noqa: N818
    GovernedQueryPolicyAuthorityError
):
    """The policy authority could not complete a database operation."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _unique(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{field} cannot contain blank values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must be unique")
    return normalized


def _actor(value: str, field: str) -> None:
    if not re.fullmatch(r"(?:human|workload|agent):\S{1,128}", value):
        raise ValueError(f"{field} must be a typed subject")


class GovernedQueryPurposeRegistration(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-purpose-registration.v1"
    tenant_id: TenantId
    purpose_code: ShortName
    description: NonEmptyText
    registered_by: NonEmptyText
    registered_at: datetime
    registration_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQueryPurposeRegistration:
        _aware(self.registered_at, "registered_at")
        _actor(self.registered_by, "registered_by")
        values = self.model_dump(mode="json", exclude={"registration_sha256"})
        expected = _fingerprint(self.schema_id, values, "registration_sha256")
        if self.registration_sha256 != expected:
            raise ValueError("purpose registration fingerprint is invalid")
        return self


class GovernedQueryPolicyVersion(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-policy-version.v1"
    tenant_id: TenantId
    policy_ref: NonEmptyText
    policy_version: ShortName
    purpose_code: ShortName
    effect: Literal["allow", "deny"]
    priority: int = Field(default=0, ge=0, le=10_000)
    subject_types: tuple[SubjectType, ...] = Field(
        default=(
            SubjectType.HUMAN,
            SubjectType.WORKLOAD,
            SubjectType.AGENT,
        ),
        min_length=1,
        max_length=3,
    )
    subject_ids: tuple[ShortName, ...] = Field(default=(), max_length=100)
    required_roles: tuple[ShortName, ...] = Field(default=(), max_length=32)
    channels: tuple[ShortName, ...] = Field(
        default=("ontology",), min_length=1, max_length=16
    )
    adapter_ids: tuple[ShortName, ...] = Field(
        default=("gda.ontology.query",), min_length=1, max_length=32
    )
    resource_prefixes: tuple[NonEmptyText, ...] = Field(default=(), max_length=100)
    obligations: tuple[NonEmptyText, ...] = Field(default=(), max_length=32)
    valid_from: datetime
    expires_at: datetime
    published_at: datetime
    published_by: NonEmptyText
    content_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQueryPolicyVersion:
        valid_from = _aware(self.valid_from, "valid_from")
        expires_at = _aware(self.expires_at, "expires_at")
        published_at = _aware(self.published_at, "published_at")
        if expires_at <= valid_from:
            raise ValueError("policy expiry must be after valid_from")
        if published_at > expires_at:
            raise ValueError("policy publication cannot be after expiry")
        _actor(self.published_by, "published_by")
        _unique(self.subject_ids, "subject_ids")
        _unique(self.required_roles, "required_roles")
        _unique(self.channels, "channels")
        _unique(self.adapter_ids, "adapter_ids")
        _unique(self.resource_prefixes, "resource_prefixes")
        _unique(self.obligations, "obligations")
        if self.effect == "deny" and self.obligations:
            raise ValueError("deny policy cannot carry executable obligations")
        values = self.model_dump(
            mode="json", exclude={"content_sha256", "record_sha256"}
        )
        expected_content = _fingerprint(self.schema_id, values, "content_sha256")
        if self.content_sha256 != expected_content:
            raise ValueError("policy content fingerprint is invalid")
        record_values = self.model_dump(mode="json", exclude={"record_sha256"})
        expected_record = _fingerprint(self.schema_id, record_values, "record_sha256")
        if self.record_sha256 != expected_record:
            raise ValueError("policy record fingerprint is invalid")
        return self

    def matches(self, request: GovernedQuerySecurityRequest) -> bool:
        """Return whether this version admits the complete request scope."""

        if request.purpose_code != self.purpose_code:
            return False
        if request.subject_context.subject_type not in self.subject_types:
            return False
        if self.subject_ids and request.subject_context.subject_id not in self.subject_ids:
            return False
        if not set(self.required_roles).issubset(request.subject_context.roles):
            return False
        if request.channel not in self.channels or request.adapter_id not in self.adapter_ids:
            return False
        if self.resource_prefixes and not all(
            any(resource.resource_ref.startswith(prefix) for prefix in self.resource_prefixes)
            for resource in request.resources
        ):
            return False
        return self.valid_from <= request.evaluated_at < self.expires_at

    def specificity(self) -> int:
        return (
            (10 if self.subject_ids else 0)
            + (5 * len(self.required_roles))
            + (3 if self.resource_prefixes else 0)
            + (2 if len(self.channels) == 1 else 0)
            + (2 if len(self.adapter_ids) == 1 else 0)
        )


class GovernedQueryPolicyRevocation(_FrozenModel):
    schema_id: ClassVar[str] = "gda.governed-query-policy-revocation.v1"
    tenant_id: TenantId
    policy_ref: NonEmptyText
    policy_version: ShortName
    revoked_at: datetime
    revoked_by: NonEmptyText
    reason: NonEmptyText
    revocation_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> GovernedQueryPolicyRevocation:
        _aware(self.revoked_at, "revoked_at")
        _actor(self.revoked_by, "revoked_by")
        values = self.model_dump(mode="json", exclude={"revocation_sha256"})
        expected = _fingerprint(self.schema_id, values, "revocation_sha256")
        if self.revocation_sha256 != expected:
            raise ValueError("policy revocation fingerprint is invalid")
        return self


def build_purpose_registration(
    *,
    tenant_id: str,
    purpose_code: str,
    description: str,
    registered_by: str,
    registered_at: datetime,
) -> GovernedQueryPurposeRegistration:
    values = {
        "tenant_id": tenant_id,
        "purpose_code": purpose_code,
        "description": description,
        "registered_by": registered_by,
        "registered_at": registered_at,
    }
    return GovernedQueryPurposeRegistration(
        **values,
        registration_sha256=_fingerprint(
            GovernedQueryPurposeRegistration.schema_id,
            values,
            "registration_sha256",
        ),
    )


def build_policy_version(
    *,
    tenant_id: str,
    policy_ref: str,
    policy_version: str,
    purpose_code: str,
    effect: Literal["allow", "deny"] = "allow",
    priority: int = 0,
    subject_types: tuple[SubjectType, ...] = (
        SubjectType.HUMAN,
        SubjectType.WORKLOAD,
        SubjectType.AGENT,
    ),
    subject_ids: tuple[str, ...] = (),
    required_roles: tuple[str, ...] = (),
    channels: tuple[str, ...] = ("ontology",),
    adapter_ids: tuple[str, ...] = ("gda.ontology.query",),
    resource_prefixes: tuple[str, ...] = (),
    obligations: tuple[str, ...] = (),
    valid_from: datetime,
    expires_at: datetime,
    published_at: datetime,
    published_by: str,
) -> GovernedQueryPolicyVersion:
    values = {
        "tenant_id": tenant_id,
        "policy_ref": policy_ref,
        "policy_version": policy_version,
        "purpose_code": purpose_code,
        "effect": effect,
        "priority": priority,
        "subject_types": subject_types,
        "subject_ids": subject_ids,
        "required_roles": required_roles,
        "channels": channels,
        "adapter_ids": adapter_ids,
        "resource_prefixes": resource_prefixes,
        "obligations": obligations,
        "valid_from": valid_from,
        "expires_at": expires_at,
        "published_at": published_at,
        "published_by": published_by,
    }
    content_sha256 = _fingerprint(
        GovernedQueryPolicyVersion.schema_id, values, "content_sha256"
    )
    record_values = {**values, "content_sha256": content_sha256}
    return GovernedQueryPolicyVersion(
        **{key: value for key, value in record_values.items() if key != "content_sha256"},
        content_sha256=content_sha256,
        record_sha256=_fingerprint(
            GovernedQueryPolicyVersion.schema_id,
            record_values,
            "record_sha256",
        ),
    )


def build_policy_revocation(
    *,
    tenant_id: str,
    policy_ref: str,
    policy_version: str,
    revoked_at: datetime,
    revoked_by: str,
    reason: str,
) -> GovernedQueryPolicyRevocation:
    values = {
        "tenant_id": tenant_id,
        "policy_ref": policy_ref,
        "policy_version": policy_version,
        "revoked_at": revoked_at,
        "revoked_by": revoked_by,
        "reason": reason,
    }
    return GovernedQueryPolicyRevocation(
        **values,
        revocation_sha256=_fingerprint(
            GovernedQueryPolicyRevocation.schema_id, values, "revocation_sha256"
        ),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _typed_model(model_type: type[BaseModel], value: Any, message: str) -> Any:
    try:
        return model_type.model_validate(value)
    except (TypeError, ValueError, ValidationError) as exc:
        raise GovernedQueryPolicyAuthorityConfigurationError(message) from exc


def _purpose_from_row(row: Mapping[str, Any]) -> GovernedQueryPurposeRegistration:
    return _typed_model(
        GovernedQueryPurposeRegistration,
        {
            "tenant_id": row["purpose_tenant_id"],
            "purpose_code": row["purpose_code"],
            "description": row["purpose_description"],
            "registered_by": row["purpose_registered_by"],
            "registered_at": row["purpose_registered_at"],
            "registration_sha256": row["purpose_registration_sha256"],
        },
        "stored query purpose registration is invalid",
    )


def _policy_from_row(row: Mapping[str, Any]) -> GovernedQueryPolicyVersion:
    return _typed_model(
        GovernedQueryPolicyVersion,
        {
            "tenant_id": row["policy_tenant_id"],
            "policy_ref": row["policy_ref"],
            "policy_version": row["policy_version"],
            "purpose_code": row["policy_purpose_code"],
            "effect": row["policy_effect"],
            "priority": row["policy_priority"],
            "subject_types": tuple(_json_value(row["subject_types"])),
            "subject_ids": tuple(_json_value(row["subject_ids"])),
            "required_roles": tuple(_json_value(row["required_roles"])),
            "channels": tuple(_json_value(row["channels"])),
            "adapter_ids": tuple(_json_value(row["adapter_ids"])),
            "resource_prefixes": tuple(_json_value(row["resource_prefixes"])),
            "obligations": tuple(_json_value(row["obligations"])),
            "valid_from": row["valid_from"],
            "expires_at": row["expires_at"],
            "published_at": row["published_at"],
            "published_by": row["published_by"],
            "content_sha256": row["content_sha256"],
            "record_sha256": row["record_sha256"],
        },
        "stored query policy version is invalid",
    )


def _revocation_from_row(row: Mapping[str, Any]) -> GovernedQueryPolicyRevocation:
    return _typed_model(
        GovernedQueryPolicyRevocation,
        {
            "tenant_id": row["revocation_tenant_id"],
            "policy_ref": row["revocation_policy_ref"],
            "policy_version": row["revocation_policy_version"],
            "revoked_at": row["revoked_at"],
            "revoked_by": row["revoked_by"],
            "reason": row["revocation_reason"],
            "revocation_sha256": row["revocation_sha256"],
        },
        "stored query policy revocation is invalid",
    )


class PostgresGovernedQueryPolicyAuthority:
    """Tenant-bound durable policy current authority.

    Writes go through migration-owned SECURITY DEFINER functions.  Current
    evaluation reads purpose, all versions and revocations in one transaction
    timestamp and delegates only the deterministic matching logic to the same
    in-memory evaluator used by development tests.
    """

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,63}", tenant_id.strip()
        ):
            raise GovernedQueryPolicyAuthorityValidationError("invalid tenant_id")
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise GovernedQueryPolicyAuthorityConfigurationError(
                "governed query policy authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise GovernedQueryPolicyAuthorityConfigurationError(
                            "database login is not a member of the policy authority role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except GovernedQueryPolicyAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise GovernedQueryPolicyAuthorityForbiddenError(
                    "governed query policy tenant or role was denied"
                ) from exc
            if state == "23505":
                raise GovernedQueryPolicyAuthorityConflictError(
                    "governed query policy immutable identity conflict"
                ) from exc
            if state in {
                "22007",
                "22023",
                "22P02",
                "23502",
                "23503",
                "23514",
                "55000",
            }:
                raise GovernedQueryPolicyAuthorityValidationError(
                    "governed query policy record was rejected"
                ) from exc
            raise GovernedQueryPolicyAuthorityUnavailableError(
                "governed query policy database operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise GovernedQueryPolicyAuthorityUnavailableError(
                "governed query policy database operation failed"
            ) from exc

    def _require_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.tenant_id:
            raise GovernedQueryPolicyAuthorityForbiddenError("tenant differs")

    @staticmethod
    def _purpose_code(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}", value.strip()
        ):
            raise GovernedQueryPolicyAuthorityValidationError("invalid purpose_code")
        return value.strip()

    def register_purpose(
        self, registration: GovernedQueryPurposeRegistration
    ) -> GovernedQueryPurposeRegistration:
        registration = _typed_model(
            GovernedQueryPurposeRegistration,
            registration.model_dump(mode="python"),
            "purpose registration is invalid",
        )
        self._require_tenant(registration.tenant_id)
        with self._transaction() as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.register_governed_query_purpose(
                        :tenant_id, :purpose_code, :description, :registered_by,
                        :registered_at, :registration_sha256
                    )
                    """
                ),
                registration.model_dump(mode="python"),
            )
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id AS purpose_tenant_id, purpose_code,
                           description AS purpose_description,
                           registered_by AS purpose_registered_by,
                           registered_at AS purpose_registered_at,
                           registration_sha256 AS purpose_registration_sha256
                    FROM gda_control.governed_query_purpose_registration
                    WHERE tenant_id = :tenant_id AND purpose_code = :purpose_code
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "purpose_code": registration.purpose_code,
                },
            ).mappings().one()
        stored = _purpose_from_row(row)
        if stored != registration:
            raise GovernedQueryPolicyAuthorityConfigurationError(
                "policy authority returned a different purpose registration"
            )
        return stored

    def register_policy(
        self, policy: GovernedQueryPolicyVersion
    ) -> GovernedQueryPolicyVersion:
        policy = _typed_model(
            GovernedQueryPolicyVersion,
            policy.model_dump(mode="python"),
            "policy version is invalid",
        )
        self._require_tenant(policy.tenant_id)
        parameters = policy.model_dump(mode="python")
        with self._transaction() as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.register_governed_query_policy_version(
                        :tenant_id, :policy_ref, :policy_version, :purpose_code,
                        :effect, :priority, CAST(:subject_types AS jsonb),
                        CAST(:subject_ids AS jsonb), CAST(:required_roles AS jsonb),
                        CAST(:channels AS jsonb), CAST(:adapter_ids AS jsonb),
                        CAST(:resource_prefixes AS jsonb), CAST(:obligations AS jsonb),
                        :valid_from, :expires_at, :published_at, :published_by,
                        :content_sha256, :record_sha256
                    )
                    """
                ),
                {
                    **parameters,
                    "subject_types": _json(parameters["subject_types"]),
                    "subject_ids": _json(parameters["subject_ids"]),
                    "required_roles": _json(parameters["required_roles"]),
                    "channels": _json(parameters["channels"]),
                    "adapter_ids": _json(parameters["adapter_ids"]),
                    "resource_prefixes": _json(parameters["resource_prefixes"]),
                    "obligations": _json(parameters["obligations"]),
                },
            )
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id AS policy_tenant_id, policy_ref,
                           policy_version, purpose_code AS policy_purpose_code,
                           effect AS policy_effect, priority AS policy_priority,
                           subject_types, subject_ids, required_roles, channels,
                           adapter_ids, resource_prefixes, obligations,
                           valid_from, expires_at, published_at, published_by,
                           content_sha256, record_sha256
                    FROM gda_control.governed_query_policy_version
                    WHERE tenant_id = :tenant_id AND policy_ref = :policy_ref
                      AND policy_version = :policy_version
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "policy_ref": policy.policy_ref,
                    "policy_version": policy.policy_version,
                },
            ).mappings().one()
        stored = _policy_from_row(row)
        if stored != policy:
            raise GovernedQueryPolicyAuthorityConfigurationError(
                "policy authority returned a different policy version"
            )
        return stored

    def revoke_policy(
        self, revocation: GovernedQueryPolicyRevocation
    ) -> GovernedQueryPolicyRevocation:
        revocation = _typed_model(
            GovernedQueryPolicyRevocation,
            revocation.model_dump(mode="python"),
            "policy revocation is invalid",
        )
        self._require_tenant(revocation.tenant_id)
        with self._transaction() as connection:
            connection.execute(
                text(
                    """
                    SELECT gda_control.revoke_governed_query_policy(
                        :tenant_id, :policy_ref, :policy_version, :revoked_at,
                        :revoked_by, :reason, :revocation_sha256
                    )
                    """
                ),
                revocation.model_dump(mode="python"),
            )
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id AS revocation_tenant_id,
                           policy_ref AS revocation_policy_ref,
                           policy_version AS revocation_policy_version,
                           revoked_at, revoked_by, reason AS revocation_reason,
                           revocation_sha256
                    FROM gda_control.governed_query_policy_revocation
                    WHERE tenant_id = :tenant_id AND policy_ref = :policy_ref
                      AND policy_version = :policy_version
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "policy_ref": revocation.policy_ref,
                    "policy_version": revocation.policy_version,
                },
            ).mappings().one()
        stored = _revocation_from_row(row)
        if stored != revocation:
            raise GovernedQueryPolicyAuthorityConfigurationError(
                "policy authority returned a different revocation"
            )
        return stored

    def governed_query_security_decision_current(
        self, request: GovernedQuerySecurityRequest
    ) -> GovernedQuerySecurityDecision:
        self._require_tenant(request.tenant_id)
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    WITH authority_clock AS (
                        SELECT transaction_timestamp() AS authority_now
                    )
                    SELECT clock.authority_now,
                           purpose.tenant_id AS purpose_tenant_id,
                           purpose.purpose_code,
                           purpose.description AS purpose_description,
                           purpose.registered_by AS purpose_registered_by,
                           purpose.registered_at AS purpose_registered_at,
                           purpose.registration_sha256 AS purpose_registration_sha256,
                           policy.tenant_id AS policy_tenant_id,
                           policy.policy_ref, policy.policy_version,
                           policy.purpose_code AS policy_purpose_code,
                           policy.effect AS policy_effect,
                           policy.priority AS policy_priority,
                           policy.subject_types, policy.subject_ids,
                           policy.required_roles, policy.channels,
                           policy.adapter_ids, policy.resource_prefixes,
                           policy.obligations, policy.valid_from,
                           policy.expires_at, policy.published_at,
                           policy.published_by, policy.content_sha256,
                           policy.record_sha256,
                           revocation.tenant_id AS revocation_tenant_id,
                           revocation.policy_ref AS revocation_policy_ref,
                           revocation.policy_version AS revocation_policy_version,
                           revocation.revoked_at, revocation.revoked_by,
                           revocation.reason AS revocation_reason,
                           revocation.revocation_sha256
                    FROM authority_clock AS clock
                    LEFT JOIN gda_control.governed_query_purpose_registration AS purpose
                      ON purpose.tenant_id = :tenant_id
                     AND purpose.purpose_code = :purpose_code
                    LEFT JOIN gda_control.governed_query_policy_version AS policy
                      ON policy.tenant_id = purpose.tenant_id
                     AND policy.purpose_code = purpose.purpose_code
                    LEFT JOIN gda_control.governed_query_policy_revocation AS revocation
                      ON revocation.tenant_id = policy.tenant_id
                     AND revocation.policy_ref = policy.policy_ref
                     AND revocation.policy_version = policy.policy_version
                    ORDER BY policy.policy_ref, policy.published_at,
                             policy.policy_version
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "purpose_code": self._purpose_code(request.purpose_code),
                },
            ).mappings().all()
        if not rows:
            raise GovernedQueryPolicyAuthorityConfigurationError(
                "policy authority current query returned no clock row"
            )
        authority_now = _aware(rows[0]["authority_now"], "authority clock")
        evaluator = InMemoryGovernedQueryPolicyAuthority(
            self.tenant_id,
            clock=lambda: authority_now,
            evaluator_subject="workload:postgres-query-policy-authority",
        )
        if rows[0]["purpose_tenant_id"] is not None:
            evaluator.register_purpose(_purpose_from_row(rows[0]))
        for row in rows:
            if row["policy_tenant_id"] is not None:
                evaluator.register_policy(_policy_from_row(row))
                if row["revocation_tenant_id"] is not None:
                    evaluator.revoke_policy(_revocation_from_row(row))
        return evaluator.governed_query_security_decision_current(request)


class PostgresGovernedQuerySecurityPortResolver:
    """Resolve the durable policy reader and existing immutable audit port."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def resolve(
        self, tenant_id: str
    ) -> tuple[PostgresGovernedQueryPolicyAuthority, SecurityEventLedgerGovernedQueryAudit]:
        authority = PostgresGovernedQueryPolicyAuthority(tenant_id, self._engine)
        audit = SecurityEventLedgerGovernedQueryAudit(
            tenant_id, SecurityEventLedger(self._engine)
        )
        return authority, audit


def configure_default_governed_query_security_resolver(engine: Any = None) -> bool:
    """Install the durable resolver when the public security gate is required.

    Explicit deployment-owned resolvers win.  Development mode remains
    untouched when the required gate is disabled.
    """

    if not governed_query_security_required():
        return False
    if governed_query_security_resolver_configured():
        return False
    selected_engine = engine if engine is not None else get_engine()
    if selected_engine is None or selected_engine.dialect.name != "postgresql":
        raise GovernedQueryPolicyAuthorityConfigurationError(
            "required governed query security resolver needs PostgreSQL"
        )
    configure_governed_query_security_port_resolver(
        PostgresGovernedQuerySecurityPortResolver(selected_engine)
    )
    return True


class InMemoryGovernedQueryPolicyAuthority(GovernedQuerySecurityCurrentReader):
    """Thread-safe append-only policy authority for development and tests."""

    def __init__(
        self,
        tenant_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        evaluator_subject: str = "workload:in-memory-policy-authority",
    ):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise GovernedQueryPolicyAuthorityValidationError("tenant_id is required")
        self.tenant_id = tenant_id.strip()
        self._clock = clock or (lambda: datetime.now(UTC))
        _actor(evaluator_subject, "evaluator_subject")
        self._evaluator_subject = evaluator_subject
        self._lock = RLock()
        self._purposes: dict[str, GovernedQueryPurposeRegistration] = {}
        self._policies: dict[tuple[str, str], GovernedQueryPolicyVersion] = {}
        self._revocations: dict[tuple[str, str], GovernedQueryPolicyRevocation] = {}

    def register_purpose(self, registration: GovernedQueryPurposeRegistration) -> None:
        if registration.tenant_id != self.tenant_id:
            raise GovernedQueryPolicyAuthorityForbiddenError("purpose tenant differs")
        with self._lock:
            existing = self._purposes.get(registration.purpose_code)
            if existing is not None and existing != registration:
                raise GovernedQueryPolicyAuthorityConflictError(
                    "purpose registration is immutable"
                )
            self._purposes[registration.purpose_code] = registration

    def register_policy(self, policy: GovernedQueryPolicyVersion) -> None:
        if policy.tenant_id != self.tenant_id:
            raise GovernedQueryPolicyAuthorityForbiddenError("policy tenant differs")
        with self._lock:
            if policy.purpose_code not in self._purposes:
                raise GovernedQueryPolicyAuthorityValidationError(
                    "policy purpose is not registered"
                )
            key = (policy.policy_ref, policy.policy_version)
            existing = self._policies.get(key)
            if existing is not None and existing != policy:
                raise GovernedQueryPolicyAuthorityConflictError(
                    "policy version is immutable"
                )
            self._policies[key] = policy

    def revoke_policy(self, revocation: GovernedQueryPolicyRevocation) -> None:
        if revocation.tenant_id != self.tenant_id:
            raise GovernedQueryPolicyAuthorityForbiddenError(
                "policy revocation tenant differs"
            )
        with self._lock:
            key = (revocation.policy_ref, revocation.policy_version)
            policy = self._policies.get(key)
            if policy is None:
                raise GovernedQueryPolicyAuthorityValidationError(
                    "cannot revoke an unknown policy version"
                )
            if revocation.revoked_at < policy.published_at:
                raise GovernedQueryPolicyAuthorityValidationError(
                    "policy revocation cannot precede publication"
                )
            existing = self._revocations.get(key)
            if existing is not None and existing != revocation:
                raise GovernedQueryPolicyAuthorityConflictError(
                    "policy revocation is immutable"
                )
            self._revocations[key] = revocation

    def policy_versions(self) -> tuple[GovernedQueryPolicyVersion, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._policies.values(),
                    key=lambda item: (item.policy_ref, item.published_at, item.policy_version),
                )
            )

    def governed_query_security_decision_current(
        self, request: GovernedQuerySecurityRequest
    ) -> GovernedQuerySecurityDecision:
        if request.tenant_id != self.tenant_id:
            raise GovernedQueryPolicyAuthorityForbiddenError(
                "query security request tenant differs"
            )
        current_time = _aware(self._clock(), "authority clock")
        with self._lock:
            purpose = self._purposes.get(request.purpose_code)
            purpose_is_current = (
                purpose is not None and purpose.registered_at <= current_time
            )
            # Only the latest published version of each policy_ref is current;
            # an older matching version must not survive a newer replacement.
            latest: dict[str, GovernedQueryPolicyVersion] = {}
            for policy in self._policies.values():
                if policy.published_at > current_time:
                    continue
                previous = latest.get(policy.policy_ref)
                if previous is None or (policy.published_at, policy.policy_version) > (
                    previous.published_at,
                    previous.policy_version,
                ):
                    latest[policy.policy_ref] = policy
            candidates = [
                policy
                for policy in latest.values()
                if purpose_is_current
                and not (
                    (revocation := self._revocations.get(
                        (policy.policy_ref, policy.policy_version)
                    ))
                    and revocation.revoked_at <= current_time
                )
                and policy.matches(request)
                and policy.valid_from <= current_time < policy.expires_at
            ]
            selected = max(
                candidates,
                key=lambda item: (
                    1 if item.effect == "deny" else 0,
                    item.priority,
                    item.specificity(),
                    item.published_at,
                    item.policy_version,
                ),
                default=None,
            )
        now = current_time
        if selected is None:
            values: dict[str, object] = {
                "request": request,
                "effect": "deny",
                "policy_ref": "gda://policy/semantic-query/default-deny",
                "policy_version": "none",
                "evaluator_subject": self._evaluator_subject,
                "obligations": (),
                "decided_at": now,
                "expires_at": now + timedelta(seconds=1),
                "authority_live_read_performed": True,
                "provider_access_performed": False,
            }
        else:
            values = {
                "request": request,
                "effect": selected.effect,
                "policy_ref": selected.policy_ref,
                "policy_version": selected.policy_version,
                "evaluator_subject": self._evaluator_subject,
                "obligations": selected.obligations,
                "decided_at": now,
                "expires_at": selected.expires_at,
                "authority_live_read_performed": True,
                "provider_access_performed": False,
            }
        return GovernedQuerySecurityDecision(
            **values,
            decision_sha256=_fingerprint(
                GovernedQuerySecurityDecision.schema_id, values, "decision_sha256"
            ),
        )


class InMemoryGovernedQuerySecurityPortResolver:
    """Resolve one authority and audit port per tenant."""

    def __init__(
        self,
        authorities: Mapping[str, InMemoryGovernedQueryPolicyAuthority],
        audits: Mapping[str, GovernedQuerySecurityAuditPort] | None = None,
    ):
        self._authorities = dict(authorities)
        self._audits = dict(audits or {})

    def resolve(
        self, tenant_id: str
    ) -> tuple[InMemoryGovernedQueryPolicyAuthority, GovernedQuerySecurityAuditPort]:
        authority = self._authorities.get(tenant_id)
        if authority is None:
            raise GovernedQueryPolicyAuthorityForbiddenError("unknown policy tenant")
        audit = self._audits.get(tenant_id)
        if audit is None:
            audit = InMemoryGovernedQuerySecurityAudit(tenant_id)
            self._audits[tenant_id] = audit
        return authority, audit


__all__ = [
    "GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATION",
    "GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATIONS",
    "GovernedQueryPolicyAuthorityConfigurationError",
    "GovernedQueryPolicyAuthorityConflictError",
    "GovernedQueryPolicyAuthorityError",
    "GovernedQueryPolicyAuthorityForbiddenError",
    "GovernedQueryPolicyAuthorityValidationError",
    "GovernedQueryPolicyAuthorityUnavailableError",
    "GovernedQueryPolicyRevocation",
    "GovernedQueryPolicyVersion",
    "GovernedQueryPurposeRegistration",
    "InMemoryGovernedQueryPolicyAuthority",
    "InMemoryGovernedQuerySecurityPortResolver",
    "PostgresGovernedQueryPolicyAuthority",
    "PostgresGovernedQuerySecurityPortResolver",
    "build_policy_revocation",
    "build_policy_version",
    "build_purpose_registration",
    "configure_default_governed_query_security_resolver",
]
