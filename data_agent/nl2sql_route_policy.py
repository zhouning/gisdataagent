"""Explicit BIRD query routes shared by the product and evaluation preflight.

The strict candidate owns generation and compilation. Legacy switches remain
available for explicit comparisons; their presence is never evidence that a
strict IR run occurred. This module performs no model or database access.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import os


PROFILES = ("configured", "registered_ir_strict")


class QueryPolicyError(ValueError):
    pass


def _flag(settings: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = settings.get(name, "1" if default else "0").strip().casefold()
    if value in {"1", "true", "on", "yes"}:
        return True
    if value in {"0", "false", "off", "no", ""}:
        return False
    raise QueryPolicyError(name + " must be a boolean")


@dataclass(frozen=True)
class QueryRoutePolicy:
    profile: str
    route: str
    allow_sql_fallback: bool
    strict_contract: bool
    version: str = "bird-query-route-v1"

    def evidence(self) -> dict:
        return asdict(self)


def resolve_bird_query_policy(settings: Mapping[str, str] | None = None) -> QueryRoutePolicy:
    env = os.environ if settings is None else settings
    profile = env.get("GDA_NL2SQL_QUERY_PROFILE", "configured").strip()
    if profile not in PROFILES:
        raise QueryPolicyError("Unknown GDA_NL2SQL_QUERY_PROFILE")
    if profile == "registered_ir_strict":
        # An explicitly contradictory frozen flag is an error, not a reason
        # to silently run a different path. Unset flags are owned by profile.
        if not _flag(env, "GDA_NL2SQL_REGISTERED_IR", default=True):
            raise QueryPolicyError("Strict IR profile conflicts with disabled registered IR")
        for name in ("GDA_NL2SQL_TYPED_BINDINGS", "GDA_NL2SQL_EXECUTION_CONSENSUS"):
            if _flag(env, name):
                raise QueryPolicyError("Strict IR profile conflicts with " + name)
        for name in ("GDA_NL2SQL_REGISTERED_IR_EXPLICIT_OPERATIONS",
                     "GDA_NL2SQL_REGISTERED_IR_CATALOG_SCHEMA",
                     "GDA_NL2SQL_REGISTERED_IR_COMPACT_CATALOG"):
            if not _flag(env, name, default=True):
                raise QueryPolicyError("Strict IR profile conflicts with disabled " + name)
        return QueryRoutePolicy(profile, "registered_ir", False, True)
    enabled = _flag(env, "GDA_NL2SQL_REGISTERED_IR")
    return QueryRoutePolicy(profile, "registered_ir" if enabled else "sql", enabled, False)


def validate_evaluation_profile(settings: Mapping[str, str], requested: str) -> dict:
    """Require an intentional, matching route before any paid generation."""
    policy = resolve_bird_query_policy(settings)
    if requested not in PROFILES or policy.profile != requested:
        raise QueryPolicyError("Requested evaluation profile differs from frozen settings")
    return policy.evidence()
