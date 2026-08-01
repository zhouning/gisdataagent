"""Outcome-free execution plan for traditional-routing conformance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

from .traditional_routing_adapter_contract import (
    build_traditional_routing_adapter_request,
)
from .traditional_routing_conformance import (
    BACKGROUND_FLOWS_M3S,
    PULSE_DURATION_SECONDS,
    PULSE_RATES_M3S,
    ROLLOUT_HOURS,
    TIMESTEPS_SECONDS,
    TRADITIONAL_ROUTING_CONFORMANCE_EVIDENCE_SCHEMA,
    WARMUP_HOURS,
    evaluate_traditional_routing_conformance,
)
from .traditional_routing_docker_executor import (
    TRADITIONAL_ROUTING_DOCKER_EXECUTION_SCHEMA,
    DockerReadOnlyMount,
    execute_traditional_routing_adapter_in_docker,
)
from .traditional_routing_preexecution_audit import (
    ABI_AUDIT_KIND,
    SOURCE_AUDIT_KIND,
    validate_traditional_routing_preexecution_audit,
)

TRADITIONAL_ROUTING_CONFORMANCE_EXECUTION_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_conformance_execution.v1"
)
TRADITIONAL_ROUTING_CONFORMANCE_PROVENANCE_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_conformance_provenance.v1"
)
EXPECTED_EXECUTION_COUNT = 56
EXPECTED_WARMUP_EXECUTION_COUNT = 9
_FORBIDDEN_EXECUTOR_KWARGS = {
    "request",
    "image_id",
    "adapter_command",
    "read_only_mounts",
}

AdapterExecutor = Callable[..., Mapping[str, object]]


def execute_traditional_routing_synthetic_conformance(
    *,
    candidate_registration: Mapping[str, object],
    source_initialization_audit: Mapping[str, object],
    abi_audit: Mapping[str, object],
    image_id: str,
    adapter_command: Sequence[str],
    read_only_mounts: Sequence[DockerReadOnlyMount],
    serialized_zero_state: Mapping[str, object],
    preexecution_audit_artifact_root: Path | None = None,
    executor_kwargs: Mapping[str, object] | None = None,
    adapter_executor_for_testing: AdapterExecutor | None = None,
) -> dict[str, Any]:
    """Execute the frozen synthetic matrix and independently adjudicate it.

    An injected executor is supported only for orchestration tests. Evidence from
    that path deliberately fails the mandatory professional isolation gate.
    """

    is_professional_executor = adapter_executor_for_testing is None
    if is_professional_executor and preexecution_audit_artifact_root is None:
        raise ValueError(
            "traditional_routing_conformance_audit_artifact_recomputation_required"
        )
    audit_artifact_root = (
        None
        if preexecution_audit_artifact_root is None
        else Path(preexecution_audit_artifact_root).resolve()
    )
    registration = _validate_candidate_registration(candidate_registration)
    source_audit_validation = validate_traditional_routing_preexecution_audit(
        registration,
        source_initialization_audit,
        expected_audit_kind=SOURCE_AUDIT_KIND,
        artifact_root=audit_artifact_root,
    )
    abi_audit_validation = validate_traditional_routing_preexecution_audit(
        registration,
        abi_audit,
        expected_audit_kind=ABI_AUDIT_KIND,
        artifact_root=audit_artifact_root,
    )
    source_audit = source_audit_validation["findings"]
    abi = abi_audit_validation["findings"]
    mounts = tuple(read_only_mounts)
    command = tuple(adapter_command)
    _validate_registered_execution_binding(
        registration,
        image_id=image_id,
        adapter_command=command,
        mounts=mounts,
    )
    zero_state = _validate_registered_zero_state(
        registration, serialized_zero_state
    )
    options = dict(executor_kwargs or {})
    if _FORBIDDEN_EXECUTOR_KWARGS.intersection(options):
        raise ValueError("traditional_routing_conformance_executor_kwargs_invalid")

    executor = (
        execute_traditional_routing_adapter_in_docker
        if is_professional_executor
        else adapter_executor_for_testing
    )
    if executor is None:
        raise AssertionError("traditional routing adapter executor missing")
    context = _ExecutionContext(
        candidate_id=str(registration["candidate_id"]),
        runtime_artifact=_runtime_request_descriptor(registration),
        container_platform=dict(registration["execution_binding"]["container_platform"]),
        image_id=image_id,
        adapter_command=command,
        read_only_mounts=mounts,
        zero_state=zero_state,
        executor=executor,
        executor_kwargs=options,
        professional_executor=is_professional_executor,
    )

    zero_trace = context.run(
        run_id="zero-input",
        feature_ids=(1,),
        downstream=(None,),
        timestep_seconds=300.0,
        boundary_rates=np.zeros((12, 1), dtype=float),
        initial_state=zero_state,
    )
    cold_boundary = np.zeros((12, 2), dtype=float)
    cold_boundary[:, 0] = 2.0
    cold_traces = [
        context.run(
            run_id=f"cold-repeat-{repeat}",
            feature_ids=(1, 2),
            downstream=(2, None),
            timestep_seconds=300.0,
            boundary_rates=cold_boundary,
            initial_state=zero_state,
        )
        for repeat in (1, 2)
    ]

    restart_rates = np.arange(1.0, 11.0, dtype=float)
    continuous = context.run(
        run_id="restart-continuous",
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=_upstream_boundary(restart_rates, feature_count=2),
        initial_state=zero_state,
    )
    prefix = context.run(
        run_id="restart-prefix",
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=_upstream_boundary(restart_rates[:4], feature_count=2),
        initial_state=zero_state,
    )
    resumed = context.run(
        run_id="restart-resumed",
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=_upstream_boundary(restart_rates[4:], feature_count=2),
        initial_state=prefix["serialized_final_state"],
    )

    warmup_traces: dict[tuple[float, float], dict[str, Any]] = {}
    base_traces: dict[tuple[float, float], dict[str, Any]] = {}
    warmup_records: list[dict[str, object]] = []
    for background, timestep in product(BACKGROUND_FLOWS_M3S, TIMESTEPS_SECONDS):
        warmup_steps = round(WARMUP_HOURS * 3600.0 / timestep)
        warmup = context.run(
            run_id=_case_id("warmup", background, 0.0, timestep),
            feature_ids=(1,),
            downstream=(None,),
            timestep_seconds=timestep,
            boundary_rates=np.full((warmup_steps, 1), background, dtype=float),
            initial_state=zero_state,
        )
        key = (background, timestep)
        warmup_traces[key] = warmup
        rollout_steps = round(ROLLOUT_HOURS * 3600.0 / timestep)
        base_traces[key] = context.run(
            run_id=_case_id("base", background, 0.0, timestep),
            feature_ids=(1,),
            downstream=(None,),
            timestep_seconds=timestep,
            boundary_rates=np.full((rollout_steps, 1), background, dtype=float),
            initial_state=warmup["serialized_final_state"],
        )
        warmup_records.append(
            {
                "background_flow_m3s": background,
                "timestep_seconds": timestep,
                "warmup_hours": WARMUP_HOURS,
                "trace": warmup,
            }
        )

    pulse_cases: list[dict[str, object]] = []
    for background, perturbation, timestep in product(
        BACKGROUND_FLOWS_M3S,
        PULSE_RATES_M3S,
        TIMESTEPS_SECONDS,
    ):
        steps = round(ROLLOUT_HOURS * 3600.0 / timestep)
        rates = np.full((steps, 1), background, dtype=float)
        rates[: round(PULSE_DURATION_SECONDS / timestep), 0] += perturbation
        key = (background, timestep)
        pulse_cases.append(
            {
                "case_id": _case_id("pulse", background, perturbation, timestep),
                "excitation_kind": "pulse",
                "background_flow_m3s": background,
                "perturbation_rate_m3s": perturbation,
                "timestep_seconds": timestep,
                "warmup_hours": WARMUP_HOURS,
                "rollout_hours": ROLLOUT_HOURS,
                "base_trace": base_traces[key],
                "perturbed_trace": context.run(
                    run_id=_case_id("pulse", background, perturbation, timestep),
                    feature_ids=(1,),
                    downstream=(None,),
                    timestep_seconds=timestep,
                    boundary_rates=rates,
                    initial_state=warmup_traces[key]["serialized_final_state"],
                ),
            }
        )

    step_cases: list[dict[str, object]] = []
    for timestep in TIMESTEPS_SECONDS:
        background = 2.0
        perturbation = 10.0
        steps = round(ROLLOUT_HOURS * 3600.0 / timestep)
        rates = np.full((steps, 1), background + perturbation, dtype=float)
        key = (background, timestep)
        step_cases.append(
            {
                "case_id": _case_id("step", background, perturbation, timestep),
                "excitation_kind": "step",
                "background_flow_m3s": background,
                "perturbation_rate_m3s": perturbation,
                "timestep_seconds": timestep,
                "warmup_hours": WARMUP_HOURS,
                "rollout_hours": ROLLOUT_HOURS,
                "base_trace": base_traces[key],
                "perturbed_trace": context.run(
                    run_id=_case_id("step", background, perturbation, timestep),
                    feature_ids=(1,),
                    downstream=(None,),
                    timestep_seconds=timestep,
                    boundary_rates=rates,
                    initial_state=warmup_traces[key]["serialized_final_state"],
                ),
            }
        )

    confluence_original = context.run(
        run_id="confluence-original",
        feature_ids=(1, 2, 3),
        downstream=(3, 3, None),
        timestep_seconds=300.0,
        boundary_rates=_confluence_boundary((1, 2, 3)),
        initial_state=zero_state,
    )
    confluence_permuted = context.run(
        run_id="confluence-permuted",
        feature_ids=(2, 1, 3),
        downstream=(3, 3, None),
        timestep_seconds=300.0,
        boundary_rates=_confluence_boundary((2, 1, 3)),
        initial_state=zero_state,
    )
    if len(context.receipts) != EXPECTED_EXECUTION_COUNT:
        raise RuntimeError("traditional_routing_conformance_execution_matrix_incomplete")

    network_isolation = is_professional_executor and all(
        receipt["network_isolation_verified"] is True for receipt in context.receipts
    )
    evidence = {
        "schema": TRADITIONAL_ROUTING_CONFORMANCE_EVIDENCE_SCHEMA,
        "candidate_id": registration["candidate_id"],
        "candidate_registration": {
            "identity_matches": True,
            "candidate_registration_ready": True,
        },
        "source_initialization_audit": source_audit,
        "abi_audit": abi,
        "data_isolation": {
            "network_isolation_enforced": network_isolation,
            "observed_discharge_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "score_report_loaded": False,
            "target_parameters_fitted": 0,
            "synthetic_inputs_only": True,
        },
        "zero_input_trace": zero_trace,
        "cold_process_traces": cold_traces,
        "restart_equivalence": {
            "continuous_trace": continuous,
            "prefix_trace": prefix,
            "resumed_trace": resumed,
        },
        "pulse_response_cases": pulse_cases,
        "step_response_cases": step_cases,
        "confluence_permutation": {
            "original_trace": confluence_original,
            "permuted_trace": confluence_permuted,
        },
        "execution_provenance": {
            "schema": TRADITIONAL_ROUTING_CONFORMANCE_PROVENANCE_SCHEMA,
            "executor_mode": (
                "docker_professional_backend"
                if is_professional_executor
                else "injected_test_executor"
            ),
            "professional_network_isolation_claim_allowed": is_professional_executor,
            "execution_count": len(context.receipts),
            "expected_execution_count": EXPECTED_EXECUTION_COUNT,
            "warmup_execution_count": len(warmup_records),
            "expected_warmup_execution_count": EXPECTED_WARMUP_EXECUTION_COUNT,
            "warmup_runs": warmup_records,
            "adapter_execution_receipts": context.receipts,
            "preexecution_audit_receipts": [
                source_audit_validation["receipt"],
                abi_audit_validation["receipt"],
            ],
            "preexecution_audit_artifact_files_recomputed": all(
                validation["receipt"]["artifact_file_identities_recomputed"] is True
                for validation in (source_audit_validation, abi_audit_validation)
            ),
            "registered_artifact_bindings": _registered_artifact_bindings(
                registration, mounts
            ),
            "outcome_inputs_requested": False,
            "real_two_system_inputs_requested": False,
        },
    }
    report = evaluate_traditional_routing_conformance(evidence)
    return {
        "schema": TRADITIONAL_ROUTING_CONFORMANCE_EXECUTION_SCHEMA,
        "status": (
            report["status"]
            if is_professional_executor
            else "test_fixture_evidence_generated_not_professional_execution"
        ),
        "evidence": evidence,
        "conformance_report": report,
        "claim_boundary": {
            "candidate_runtime_invoked": True,
            "synthetic_inputs_only": True,
            "professional_executor_used": is_professional_executor,
            "professional_runtime_certified": (
                is_professional_executor
                and report["decision"]["professional_runtime_certified"] is True
            ),
            "matched_two_system_execution_permitted": (
                is_professional_executor
                and report["decision"]["matched_two_system_execution_permitted"]
                is True
            ),
            "real_two_system_inputs_loaded": False,
            "outcome_values_loaded": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


class _ExecutionContext:
    def __init__(
        self,
        *,
        candidate_id: str,
        runtime_artifact: dict[str, object],
        container_platform: dict[str, object],
        image_id: str,
        adapter_command: tuple[str, ...],
        read_only_mounts: tuple[DockerReadOnlyMount, ...],
        zero_state: dict[str, object],
        executor: AdapterExecutor,
        executor_kwargs: dict[str, object],
        professional_executor: bool,
    ) -> None:
        self.candidate_id = candidate_id
        self.runtime_artifact = runtime_artifact
        self.container_platform = container_platform
        self.image_id = image_id
        self.adapter_command = adapter_command
        self.read_only_mounts = read_only_mounts
        self.zero_state = zero_state
        self.executor = executor
        self.executor_kwargs = executor_kwargs
        self.professional_executor = professional_executor
        self.receipts: list[dict[str, object]] = []

    def run(
        self,
        *,
        run_id: str,
        feature_ids: tuple[int, ...],
        downstream: tuple[int | None, ...],
        timestep_seconds: float,
        boundary_rates: np.ndarray,
        initial_state: Mapping[str, object],
    ) -> dict[str, Any]:
        boundary = np.asarray(boundary_rates, dtype=np.float64)
        if boundary.ndim != 2 or boundary.shape[1] != len(feature_ids):
            raise ValueError("traditional_routing_conformance_boundary_shape_invalid")
        request = build_traditional_routing_adapter_request(
            request_id=f"{self.candidate_id}:{run_id}",
            candidate_id=self.candidate_id,
            runtime_artifact=self.runtime_artifact,
            feature_ids=feature_ids,
            downstream_feature_ids=downstream,
            geometry=_geometry(len(feature_ids)),
            timestep_seconds=timestep_seconds,
            boundary_inflow_m3s=boundary.tolist(),
            lateral_inflow_m3s=np.zeros_like(boundary).tolist(),
            serialized_initial_state=deepcopy(dict(initial_state)),
        )
        result = self.executor(
            request,
            image_id=self.image_id,
            adapter_command=self.adapter_command,
            read_only_mounts=self.read_only_mounts,
            **self.executor_kwargs,
        )
        payload = dict(result)
        trace = payload.get("validated_trace")
        policy = payload.get("command_policy")
        receipt = payload.get("execution_receipt")
        claim = payload.get("claim_boundary")
        valid = (
            payload.get("schema") == TRADITIONAL_ROUTING_DOCKER_EXECUTION_SCHEMA
            and payload.get("status") == "adapter_response_transport_validated"
            and isinstance(trace, dict)
            and trace.get("request_id") == request["request_id"]
            and trace.get("candidate_id") == self.candidate_id
            and isinstance(policy, dict)
            and policy.get("network_mode") == "none"
            and policy.get("root_filesystem_read_only") is True
            and policy.get("host_environment_forwarded") is False
            and isinstance(receipt, dict)
            and receipt.get("requested_image_id") == self.image_id
            and receipt.get("image_identity_matched_before_execution") is True
            and receipt.get("image_platform") == self.container_platform
            and receipt.get("response_validated_after_container_exit") is True
            and isinstance(claim, dict)
            and claim.get("transport_isolation_validated") is True
            and claim.get("professional_runtime_certified") is False
            and claim.get("runtime_admitted") is False
        )
        if not valid:
            raise RuntimeError("traditional_routing_conformance_execution_receipt_invalid")
        self.receipts.append(
            {
                "run_id": run_id,
                "request_id": request["request_id"],
                "request_seal_sha256": request["request_seal"]["sha256"],
                "response_sha256": trace["exchange_receipt"]["response_sha256"],
                "image_id": self.image_id,
                "image_platform": dict(self.container_platform),
                "network_isolation_verified": (
                    self.professional_executor and policy.get("network_mode") == "none"
                ),
                "container_id": receipt.get("container_id"),
            }
        )
        return deepcopy(trace)


def _validate_candidate_registration(
    value: Mapping[str, object],
) -> dict[str, Any]:
    registration = dict(value)
    candidate_id = registration.get("candidate_id")
    gates = registration.get("gates")
    artifacts = registration.get("artifacts")
    manifest = registration.get("manifest_artifact")
    sources = registration.get("source_artifacts")
    execution_binding = registration.get("execution_binding")
    if (
        not isinstance(candidate_id, str)
        or not candidate_id.strip()
        or registration.get("candidate_registration_ready") is not True
        or not isinstance(gates, dict)
        or not gates
        or not all(item is True for item in gates.values())
        or not isinstance(artifacts, dict)
        or not _manifest_identity_valid(manifest)
        or not isinstance(sources, list)
        or not sources
        or not all(_registered_artifact_identity_valid(item) for item in sources)
        or not isinstance(execution_binding, dict)
        or execution_binding.get("identity_matches") is not True
    ):
        raise ValueError("traditional_routing_conformance_candidate_not_registered")
    for name in (
        "license",
        "dependency_lock",
        "runtime",
        "adapter_source",
        "serialized_zero_state",
    ):
        descriptor = artifacts.get(name)
        if not _registered_artifact_identity_valid(descriptor):
            raise ValueError("traditional_routing_conformance_candidate_not_registered")
    zero_state = artifacts["serialized_zero_state"]
    if not _sha256(zero_state.get("canonical_sha256")):
        raise ValueError("traditional_routing_conformance_candidate_not_registered")
    return registration


def _manifest_identity_valid(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and _sha256(value.get("sha256"))
        and isinstance(value.get("size_bytes"), int)
        and not isinstance(value.get("size_bytes"), bool)
        and int(value["size_bytes"]) > 0
    )


def _registered_artifact_identity_valid(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("identity_matches") is True
        and _sha256(value.get("actual_sha256"))
        and isinstance(value.get("actual_size_bytes"), int)
        and not isinstance(value.get("actual_size_bytes"), bool)
        and int(value["actual_size_bytes"]) > 0
    )


def _validate_registered_zero_state(
    registration: Mapping[str, object], value: Mapping[str, object]
) -> dict[str, object]:
    zero_state = deepcopy(dict(value))
    try:
        canonical_sha256 = hashlib.sha256(_canonical_json(zero_state)).hexdigest()
    except (TypeError, ValueError) as error:
        raise ValueError(
            "traditional_routing_conformance_zero_state_invalid"
        ) from error
    descriptor = registration["artifacts"]["serialized_zero_state"]
    if canonical_sha256 != descriptor.get("canonical_sha256"):
        raise ValueError("traditional_routing_conformance_zero_state_identity_mismatch")
    return zero_state


def _validate_registered_execution_binding(
    registration: Mapping[str, object],
    *,
    image_id: str,
    adapter_command: tuple[str, ...],
    mounts: tuple[DockerReadOnlyMount, ...],
) -> None:
    bound = [
        (
            _file_sha256(Path(mount.source)),
            Path(mount.source).stat().st_size,
            mount.target,
        )
        for mount in mounts
        if Path(mount.source).is_file()
    ]
    artifacts = registration["artifacts"]
    required = {
        (
            artifacts[name]["actual_sha256"],
            artifacts[name]["actual_size_bytes"],
        )
        for name in ("runtime", "adapter_source")
    }
    bound_identities = {(sha256, size) for sha256, size, _target in bound}
    adapter = artifacts["adapter_source"]
    adapter_targets = {
        target
        for sha256, size, target in bound
        if sha256 == adapter["actual_sha256"]
        and size == adapter["actual_size_bytes"]
    }
    execution = registration["execution_binding"]
    registered_targets = execution.get("read_only_mount_targets")
    runtime = artifacts["runtime"]
    runtime_targets = {
        target
        for sha256, size, target in bound
        if sha256 == runtime["actual_sha256"]
        and size == runtime["actual_size_bytes"]
    }
    if (
        not mounts
        or not adapter_command
        or not required.issubset(bound_identities)
        or not adapter_targets.intersection(adapter_command)
        or execution.get("backend") != "docker_network_none_v1"
        or execution.get("network_mode") != "none"
        or execution.get("image_id") != image_id
        or execution.get("container_platform")
        not in (
            {"system": "Linux", "machine": "amd64"},
            {"system": "Linux", "machine": "arm64"},
        )
        or execution.get("adapter_command") != list(adapter_command)
        or not isinstance(registered_targets, dict)
        or registered_targets.get("runtime") not in runtime_targets
        or registered_targets.get("adapter_source") not in adapter_targets
    ):
        raise ValueError("traditional_routing_conformance_artifact_mount_binding_invalid")


def _registered_artifact_bindings(
    registration: Mapping[str, object],
    mounts: tuple[DockerReadOnlyMount, ...],
) -> list[dict[str, object]]:
    artifacts = registration["artifacts"]
    bindings = []
    for name in ("runtime", "adapter_source"):
        descriptor = artifacts[name]
        matching = next(
            mount
            for mount in mounts
            if Path(mount.source).is_file()
            and _file_sha256(Path(mount.source)) == descriptor["actual_sha256"]
            and Path(mount.source).stat().st_size == descriptor["actual_size_bytes"]
        )
        bindings.append(
            {
                "artifact_role": name,
                "sha256": descriptor["actual_sha256"],
                "size_bytes": descriptor["actual_size_bytes"],
                "container_target": matching.target,
                "mount_read_only": True,
            }
        )
    zero_state = artifacts["serialized_zero_state"]
    bindings.append(
        {
            "artifact_role": "serialized_zero_state",
            "sha256": zero_state["actual_sha256"],
            "size_bytes": zero_state["actual_size_bytes"],
            "canonical_sha256": zero_state["canonical_sha256"],
            "container_target": None,
            "mount_read_only": None,
            "embedded_in_adapter_requests": True,
        }
    )
    return bindings


def _runtime_request_descriptor(registration: Mapping[str, object]) -> dict[str, object]:
    runtime = registration["artifacts"]["runtime"]
    return {
        "path": runtime["path"],
        "sha256": runtime["actual_sha256"],
        "size_bytes": runtime["actual_size_bytes"],
    }


def _geometry(count: int) -> dict[str, list[float]]:
    return {
        "length_m": [1000.0] * count,
        "bottom_width_m": [10.0] * count,
        "slope": [0.001] * count,
        "manning_n": [0.03] * count,
    }


def _upstream_boundary(rates: np.ndarray, *, feature_count: int) -> np.ndarray:
    result = np.zeros((len(rates), feature_count), dtype=np.float64)
    result[:, 0] = rates
    return result


def _confluence_boundary(feature_ids: tuple[int, int, int]) -> np.ndarray:
    steps = 8
    values = {
        1: np.arange(1.0, steps + 1.0, dtype=float),
        2: np.full(steps, 2.0, dtype=float),
        3: np.zeros(steps, dtype=float),
    }
    return np.column_stack([values[feature_id] for feature_id in feature_ids])


def _case_id(kind: str, background: float, perturbation: float, timestep: float) -> str:
    return f"{kind}:q{background}:p{perturbation}:dt{timestep}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
