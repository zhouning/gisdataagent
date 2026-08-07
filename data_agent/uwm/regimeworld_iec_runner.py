"""Admission-first orchestration contracts for formal RegimeWorld-IEC runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from data_agent.uwm.regimeworld_iec_execution_guard import (
    ExecutionAuthorization,
    ExperimentScope,
    authorize_execution,
)
from data_agent.uwm.regimeworld_iec_generator import (
    ControlledScenario,
    ControlledScenarioSpec,
    ControlledUrbanDynamics,
)
from data_agent.uwm.regimeworld_iec_protocol import MODEL_VARIANTS


@dataclass(frozen=True)
class RunShard:
    shard_index: int
    shard_count: int
    scenario_names: tuple[str, ...]


def shard_specs(
    specs: Sequence[ControlledScenarioSpec],
    *,
    shard_index: int,
    shard_count: int,
) -> tuple[ControlledScenarioSpec, ...]:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard index or count")
    return tuple(
        spec for index, spec in enumerate(specs) if index % shard_count == shard_index
    )


def prepare_run(
    scope: ExperimentScope | str,
    specs: Sequence[ControlledScenarioSpec],
    *,
    shard_index: int = 0,
    shard_count: int = 1,
    human_admission_receipt: Path | None = None,
    artifact_root: Path | None = None,
    untouched_freeze_manifest: Path | None = None,
    frozen_artifact_paths: Mapping[str, Path] | None = None,
) -> tuple[ExecutionAuthorization, tuple[ControlledScenarioSpec, ...], RunShard]:
    """Authorize the complete frozen manifest before selecting or generating a shard."""

    authorization = authorize_execution(
        scope,
        specs,
        human_admission_receipt=human_admission_receipt,
        artifact_root=artifact_root,
        untouched_freeze_manifest=untouched_freeze_manifest,
        frozen_artifact_paths=frozen_artifact_paths,
    )
    selected = shard_specs(specs, shard_index=shard_index, shard_count=shard_count)
    if not selected:
        raise ValueError("selected shard is empty")
    return (
        authorization,
        selected,
        RunShard(
            shard_index=shard_index,
            shard_count=shard_count,
            scenario_names=tuple(spec.name for spec in selected),
        ),
    )


def generate_authorized_scenarios(
    authorization: ExecutionAuthorization,
    specs: Iterable[ControlledScenarioSpec],
    *,
    generator_factory: Callable[[ControlledScenarioSpec], Any] = ControlledUrbanDynamics,
) -> tuple[ControlledScenario, ...]:
    specs = tuple(specs)
    unauthorized = [
        spec.name for spec in specs if spec.name not in authorization.scenario_names
    ]
    if unauthorized:
        raise PermissionError(f"scenario generation is not authorized: {unauthorized[:3]}")
    return tuple(generator_factory(spec).generate() for spec in specs)


def build_run_manifest(
    *,
    authorization: ExecutionAuthorization,
    shard: RunShard,
    scenario_specs: Sequence[ControlledScenarioSpec],
    artifact_hashes: Mapping[str, str],
    completed_variants: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    expected_names = set(shard.scenario_names)
    observed_names = {spec.name for spec in scenario_specs}
    if observed_names != expected_names:
        raise ValueError("run manifest scenarios do not match the authorized shard")
    unknown_variants = {
        variant
        for variants in completed_variants.values()
        for variant in variants
        if variant not in MODEL_VARIANTS
    }
    if unknown_variants:
        raise ValueError(f"run manifest contains unknown variants: {sorted(unknown_variants)}")
    missing_scenarios = expected_names - set(completed_variants)
    if missing_scenarios:
        raise ValueError(f"run manifest lacks scenarios: {sorted(missing_scenarios)[:3]}")
    payload = {
        "schema": "uwm.regimeworld_iec_run_manifest.v1",
        "scope": authorization.scope.value,
        "scientific_result": authorization.scientific_result,
        "human_receipt_sha256": authorization.human_receipt_sha256,
        "shard": asdict(shard),
        "scenario_specs": [asdict(spec) for spec in scenario_specs],
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "completed_variants": {
            name: list(variants) for name, variants in sorted(completed_variants.items())
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload
