"""Versioned compatibility profiles for the NL2Semantic2SQL pipeline.

The semantic contract and compiler are model-independent.  A model profile is
the small, explicit compatibility surface for provider behaviour that cannot
be assumed to be identical (prompt rendering, intent fallback and structured
output transport).  Keeping these choices here makes model upgrades auditable
and prevents new ``if family == ...`` branches from leaking into the semantic
planner.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from typing import Any


@dataclass(frozen=True)
class NL2SQLModelProfile:
    """Immutable, serialisable model compatibility contract."""

    profile_id: str
    profile_version: str
    model_id: str
    provider: str
    family: str
    prompt_variant: str
    intent_strategy: str
    grounding_variant: str
    structured_output_mode: str
    reasoning_effort: str
    temperature: float | None
    max_generation_attempts: int
    generation_attempt_timeout_seconds: int | None
    max_generation_output_tokens: int | None
    semantic_ir_enabled: bool
    repair_strategy: str
    refusal_policy: str
    minimum_benchmark_thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_PROFILE_VERSION = "nl2sql-model-profile-v1"


def _profile(
    *,
    profile_id: str,
    model_id: str,
    provider: str,
    family: str,
    prompt_variant: str,
    intent_strategy: str,
    grounding_variant: str,
    structured_output_mode: str,
    semantic_ir_enabled: bool,
    repair_strategy: str,
    max_generation_attempts: int,
    generation_attempt_timeout_seconds: int | None = None,
    max_generation_output_tokens: int | None = None,
    thresholds: dict[str, float],
    reasoning_effort: str = "none",
    temperature: float | None = None,
    refusal_policy: str = "deterministic_read_only_preflight_then_model_contract",
) -> NL2SQLModelProfile:
    return NL2SQLModelProfile(
        profile_id=profile_id,
        profile_version=_PROFILE_VERSION,
        model_id=model_id,
        provider=provider,
        family=family,
        prompt_variant=prompt_variant,
        intent_strategy=intent_strategy,
        grounding_variant=grounding_variant,
        structured_output_mode=structured_output_mode,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
        max_generation_attempts=max_generation_attempts,
        generation_attempt_timeout_seconds=generation_attempt_timeout_seconds,
        max_generation_output_tokens=max_generation_output_tokens,
        semantic_ir_enabled=semantic_ir_enabled,
        repair_strategy=repair_strategy,
        refusal_policy=refusal_policy,
        minimum_benchmark_thresholds=dict(thresholds),
    )


_THRESHOLDS = {
    "liveability_gold_equivalence": 0.80,
    "makani_gold_equivalence": 0.20,
    "refusal_precision": 0.90,
    "refusal_recall": 0.95,
    "query_execution_success": 0.90,
}


def _normalise_model_name(value: str | None) -> str:
    candidate = str(value or "").strip()
    # Model gateways identify a deployed model as, for example,
    # ``ollama_chat/model:tag`` while operators configure ``model:tag``.
    # Treat those as the same model identity so a report's declared profile
    # and a generation event have one stable fingerprint.
    lowered = candidate.casefold()
    for prefix in ("ollama_chat/", "ollama/", "openai/", "litellm/", "lm_studio/"):
        if lowered.startswith(prefix):
            return candidate[len(prefix) :]
    return candidate


def infer_model_family(model_name: str | None = None, family: str | None = None) -> str:
    """Infer a stable family namespace without requiring provider objects."""
    explicit = str(family or "").strip().casefold()
    if explicit:
        return explicit
    name = _normalise_model_name(
        model_name
        or os.environ.get("NL2SQL_AGENT_MODEL")
        or os.environ.get("GDA_LLM_MODEL")
        or os.environ.get("MODEL_STANDARD")
    ).casefold()
    if "gemma" in name:
        return "gemma"
    if "gemini" in name:
        return "gemini"
    if "deepseek" in name:
        return "deepseek"
    if "qwen" in name or "dashscope" in name:
        return "qwen"
    if name.startswith(("gpt-", "openai/gpt-", "chatgpt-")):
        return "openai"
    if "lm_studio" in name or "lmstudio" in name:
        return "lm_studio"
    if name.startswith(("ollama/", "ollama_chat/")):
        return "ollama"
    if "/" in name:
        return "litellm"
    # No explicit family preserves the historical Gemini behaviour.
    return "gemini"


def resolve_nl2sql_model_profile(
    model_name: str | None = None,
    *,
    family: str | None = None,
    provider: str | None = None,
) -> NL2SQLModelProfile:
    """Return the compatibility profile for a model/family combination.

    Profiles intentionally describe capabilities, not benchmark cases.  A
    model-specific override can be added by its exact id without modifying the
    semantic planner; unknown local OpenAI-compatible models use the canonical
    local profile.
    """
    raw_model_id = str(model_name or "").strip()
    model_id = _normalise_model_name(raw_model_id)
    # Preserve a route prefix for family detection: an otherwise unrecognised
    # ``ollama_chat/foo`` is still an Ollama model, while its profile identity
    # remains the canonical ``foo`` model id above.
    resolved_family = infer_model_family(raw_model_id, family)
    provider_name = str(provider or "").strip().casefold()
    if not provider_name:
        lower_model = model_id.casefold()
        configured_provider = str(
            os.environ.get("GDA_LLM_PROVIDER")
            or os.environ.get("LLM_PROVIDER")
            or ""
        ).strip().casefold()
        local_route = lower_model.startswith(("ollama/", "ollama_chat/")) or (
            resolved_family in {"gemma", "qwen", "deepseek"}
            and (":" in lower_model or configured_provider in {"ollama", "lm_studio"})
        )
        if local_route:
            provider_name = configured_provider or "ollama"
        elif resolved_family in {"gemini", "gemma"}:
            provider_name = "google"
        elif resolved_family in {"ollama", "lm_studio"}:
            provider_name = resolved_family
        elif resolved_family in {"openai", "qwen", "deepseek"}:
            provider_name = "openai_compatible"
        else:
            provider_name = "litellm"

    # Exact model overrides are deliberately sparse.  They are a release
    # mechanism for observed transport quirks, not a place for question-level
    # exceptions.
    if resolved_family == "gemini":
        return _profile(
            profile_id="gemini-legacy",
            model_id=model_id or "gemini-default",
            provider=provider_name,
            family=resolved_family,
            prompt_variant="gemini_legacy",
            intent_strategy="rule_then_llm",
            grounding_variant="legacy",
            structured_output_mode="native_json_schema_baseline_text_ir",
            semantic_ir_enabled=True,
            repair_strategy="contract_retry_then_deterministic_validation",
            max_generation_attempts=2,
            thresholds=_THRESHOLDS,
        )
    if resolved_family == "gemma" and provider_name in {"ollama", "lm_studio"}:
        # Gemma's local OpenAI-compatible transports have been observed to
        # stall while compiling nested JSON Schema response constraints.  The
        # prompt still requires JSON and the runtime still validates it with
        # the exact Pydantic proposal model; only provider-side schema
        # transport is disabled for this model family.
        return _profile(
            profile_id="gemma-instruction-json-local",
            model_id=model_id or "gemma-default",
            provider=provider_name,
            family=resolved_family,
            prompt_variant="compact_local",
            intent_strategy="rule_only",
            grounding_variant="compact",
            structured_output_mode="instruction_json",
            semantic_ir_enabled=True,
            repair_strategy="normalise_validate_retry",
            max_generation_attempts=3,
            generation_attempt_timeout_seconds=90,
            # A compact local context needs more room than short aggregate
            # plans, while 1536-token complete-field attempts can exceed the
            # bounded local service window. 1280 is the release profile's
            # middle ground; the 90-second attempt cap gives slow local
            # prefill and generation one usable window while the request-level
            # budget still bounds all retries to 180 seconds by default.
            max_generation_output_tokens=1280,
            temperature=0.0,
            thresholds=_THRESHOLDS,
        )
    if resolved_family in {"qwen", "deepseek", "gemma", "ollama", "lm_studio"}:
        return _profile(
            profile_id=f"{resolved_family}-compact-local",
            model_id=model_id or f"{resolved_family}-default",
            provider=provider_name,
            family=resolved_family,
            prompt_variant="compact_local",
            intent_strategy="rule_only",
            grounding_variant="compact",
            structured_output_mode="adk_output_schema",
            semantic_ir_enabled=True,
            repair_strategy="normalise_validate_retry",
            max_generation_attempts=3,
            thresholds=_THRESHOLDS,
        )
    if resolved_family == "openai":
        return _profile(
            profile_id="openai-canonical",
            model_id=model_id or "openai-default",
            provider=provider_name,
            family=resolved_family,
            prompt_variant="canonical",
            intent_strategy="rule_then_llm",
            grounding_variant="legacy",
            structured_output_mode="adk_output_schema",
            semantic_ir_enabled=True,
            repair_strategy="normalise_validate_retry",
            max_generation_attempts=3,
            thresholds=_THRESHOLDS,
        )
    return _profile(
        profile_id="generic-canonical",
        model_id=model_id or "unknown",
        provider=provider_name,
        family=resolved_family,
        prompt_variant="canonical",
        intent_strategy="rule_then_llm",
        grounding_variant="legacy",
        structured_output_mode="adk_output_schema",
        semantic_ir_enabled=True,
        repair_strategy="normalise_validate_retry",
        max_generation_attempts=3,
        thresholds=_THRESHOLDS,
    )


def profile_for_model(model_name: str | None = None, family: str | None = None) -> dict[str, Any]:
    """Convenience serialisation helper for reports and evidence."""
    profile = resolve_nl2sql_model_profile(model_name, family=family)
    data = profile.to_dict()
    data["fingerprint"] = profile.fingerprint
    return data
