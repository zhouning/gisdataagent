"""Causal learned edge-flux innovation with counterfactual mass attribution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .conservative_flux import ConservativeFluxOperator, ConservativeFluxResult
from .contracts import (
    ActionBoundaryFlux,
    EdgeFlux,
    ForcingFlux,
    SourceSinkFlux,
    StockState,
)

CONSERVATIVE_EDGE_FLUX_INNOVATION_SCHEMA = (
    "gwm.geospatial_kernel.conservative_edge_flux_innovation.v1"
)
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _complex_fingerprint(operator: ConservativeFluxOperator) -> str:
    body = json.dumps(
        operator.complex.as_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class EdgeFluxInnovation:
    """A signed forecast correction on an immutable authoritative edge axis."""

    edge_keys: tuple[str, ...]
    values: tuple[float, ...]
    unit: str
    valid_at: datetime
    available_at: datetime
    provenance_id: str
    evidence_level: str
    admitted: bool
    causal_inputs_verified: bool
    future_target_observation_used: bool

    def __post_init__(self) -> None:
        if (
            not self.edge_keys
            or len(self.edge_keys) != len(set(self.edge_keys))
            or any(not isinstance(value, str) or not value.strip() for value in self.edge_keys)
        ):
            raise ValueError("edge_flux_innovation_edge_axis_invalid")
        values = tuple(float(value) for value in self.values)
        if (
            len(values) != len(self.edge_keys)
            or not np.isfinite(np.asarray(values, dtype=float)).all()
        ):
            raise ValueError("edge_flux_innovation_values_invalid")
        object.__setattr__(self, "values", values)
        if not self.unit.strip() or not self.provenance_id.strip():
            raise ValueError("edge_flux_innovation_identity_required")
        if not _aware(self.valid_at) or not _aware(self.available_at):
            raise ValueError("edge_flux_innovation_times_must_be_aware")
        if self.available_at > self.valid_at:
            raise ValueError("edge_flux_innovation_available_after_valid_time")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("edge_flux_innovation_evidence_level_invalid")
        flags = (
            self.admitted,
            self.causal_inputs_verified,
            self.future_target_observation_used,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("edge_flux_innovation_flags_must_be_boolean")
        if self.future_target_observation_used:
            raise ValueError("edge_flux_innovation_future_target_observation_forbidden")
        if self.admitted and (
            self.evidence_level == "candidate" or not self.causal_inputs_verified
        ):
            raise ValueError("edge_flux_innovation_admission_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_EDGE_FLUX_INNOVATION_SCHEMA,
            "edge_keys": list(self.edge_keys),
            "values": list(self.values),
            "unit": self.unit,
            "valid_at": self.valid_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "causal_inputs_verified": self.causal_inputs_verified,
            "future_target_observation_used": self.future_target_observation_used,
            "mass_role": "internal_edge_transfer_adjustment_not_external_source_sink",
        }


@dataclass(frozen=True)
class ConservativeEdgeFluxInnovationConfig:
    allow_unadmitted_innovation_for_diagnostics: bool = False
    absolute_mass_tolerance: float = 1e-9

    def __post_init__(self) -> None:
        if not isinstance(self.allow_unadmitted_innovation_for_diagnostics, bool):
            raise ValueError("edge_flux_innovation_diagnostic_flag_must_be_boolean")
        tolerance = float(self.absolute_mass_tolerance)
        if not np.isfinite(tolerance) or tolerance < 0.0:
            raise ValueError("edge_flux_innovation_mass_tolerance_invalid")
        object.__setattr__(self, "absolute_mass_tolerance", tolerance)


@dataclass(frozen=True)
class ConservativeEdgeFluxInnovationResult:
    """Hybrid transition and its identical-input base-only counterfactual."""

    issue_time: datetime
    complex_fingerprint: str
    base_edge_flux: tuple[float, ...]
    requested_innovation_edge_flux: tuple[float, ...]
    raw_combined_edge_flux: tuple[float, ...]
    combined_edge_flux_before_projection: tuple[float, ...]
    authoritative_direction_clipped_edges: tuple[bool, ...]
    base_counterfactual: ConservativeFluxResult
    hybrid: ConservativeFluxResult
    realized_applied_edge_flux_delta: tuple[float, ...]
    state_delta_due_to_innovation: tuple[float, ...]
    state_delta_global_sum: float
    state_delta_global_tolerance: float
    external_mass_introduced_by_innovation_m3: float
    topology_unchanged: bool
    innovation_admitted: bool
    diagnostic_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_EDGE_FLUX_INNOVATION_SCHEMA,
            "issue_time": self.issue_time.isoformat(),
            "complex_fingerprint": self.complex_fingerprint,
            "base_edge_flux": list(self.base_edge_flux),
            "requested_innovation_edge_flux": list(self.requested_innovation_edge_flux),
            "raw_combined_edge_flux": list(self.raw_combined_edge_flux),
            "combined_edge_flux_before_projection": list(self.combined_edge_flux_before_projection),
            "authoritative_direction_clipped_edges": list(
                self.authoritative_direction_clipped_edges
            ),
            "base_counterfactual": self.base_counterfactual.as_dict(),
            "hybrid": self.hybrid.as_dict(),
            "realized_applied_edge_flux_delta": list(self.realized_applied_edge_flux_delta),
            "state_delta_due_to_innovation": list(self.state_delta_due_to_innovation),
            "innovation_mass_ledger": {
                "state_delta_global_sum": self.state_delta_global_sum,
                "state_delta_global_tolerance": self.state_delta_global_tolerance,
                "external_mass_introduced_by_innovation_m3": (
                    self.external_mass_introduced_by_innovation_m3
                ),
                "global_zero_external_mass_passed": (
                    abs(self.state_delta_global_sum) <= self.state_delta_global_tolerance
                    and self.external_mass_introduced_by_innovation_m3 == 0.0
                ),
            },
            "topology_unchanged": self.topology_unchanged,
            "innovation_admitted": self.innovation_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


class ConservativeEdgeFluxInnovationOperator:
    """Apply a signed learned correction only through admitted internal edges."""

    def __init__(
        self,
        base_operator: ConservativeFluxOperator,
        config: ConservativeEdgeFluxInnovationConfig | None = None,
    ) -> None:
        if not isinstance(base_operator, ConservativeFluxOperator):
            raise TypeError("conservative_flux_operator_required")
        if config is not None and not isinstance(config, ConservativeEdgeFluxInnovationConfig):
            raise TypeError("edge_flux_innovation_config_required")
        self.base_operator = base_operator
        self.config = config or ConservativeEdgeFluxInnovationConfig()

    def step(
        self,
        stock: StockState,
        base_edge_flux: EdgeFlux,
        innovation: EdgeFluxInnovation,
        *,
        issue_time: datetime,
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
        source_sink: SourceSinkFlux | None = None,
    ) -> ConservativeEdgeFluxInnovationResult:
        self._validate_inputs(
            base_edge_flux=base_edge_flux,
            innovation=innovation,
            issue_time=issue_time,
        )
        before = _complex_fingerprint(self.base_operator)
        base = np.asarray(base_edge_flux.values, dtype=float)
        adjustment = np.asarray(innovation.values, dtype=float)
        raw_combined = base + adjustment
        clipped = raw_combined < 0.0
        combined = np.maximum(raw_combined, 0.0)
        combined_flux = EdgeFlux(
            values=tuple(float(value) for value in combined),
            unit=base_edge_flux.unit,
            provenance_id=(
                f"{base_edge_flux.provenance_id}|internal-innovation:{innovation.provenance_id}"
            ),
        )
        counterfactual = self.base_operator.step(
            stock,
            base_edge_flux,
            action=action,
            forcing=forcing,
            source_sink=source_sink,
        )
        hybrid = self.base_operator.step(
            stock,
            combined_flux,
            action=action,
            forcing=forcing,
            source_sink=source_sink,
        )
        after = _complex_fingerprint(self.base_operator)
        if after != before:
            raise RuntimeError("edge_flux_innovation_mutated_geocomplex")
        external_fields = (
            "applied_action_flux",
            "applied_forcing_flux",
            "applied_source_sink_flux",
            "unmet_external_withdrawal",
        )
        if any(getattr(counterfactual, name) != getattr(hybrid, name) for name in external_fields):
            raise RuntimeError("edge_flux_innovation_changed_external_mass_channels")
        edge_delta = np.asarray(hybrid.applied_edge_flux) - np.asarray(
            counterfactual.applied_edge_flux
        )
        state_delta = np.asarray(hybrid.next_stock.values) - np.asarray(
            counterfactual.next_stock.values
        )
        global_delta = float(state_delta.sum())
        scale = max(
            1.0,
            float(np.abs(counterfactual.next_stock.values).sum()),
            float(np.abs(hybrid.next_stock.values).sum()),
        )
        tolerance = self.config.absolute_mass_tolerance + (np.finfo(float).eps * 100.0 * scale)
        if abs(global_delta) > tolerance:
            raise RuntimeError("edge_flux_innovation_global_mass_tolerance_exceeded")
        return ConservativeEdgeFluxInnovationResult(
            issue_time=issue_time,
            complex_fingerprint=before,
            base_edge_flux=tuple(float(value) for value in base),
            requested_innovation_edge_flux=tuple(float(value) for value in adjustment),
            raw_combined_edge_flux=tuple(float(value) for value in raw_combined),
            combined_edge_flux_before_projection=tuple(float(value) for value in combined),
            authoritative_direction_clipped_edges=tuple(bool(value) for value in clipped),
            base_counterfactual=counterfactual,
            hybrid=hybrid,
            realized_applied_edge_flux_delta=tuple(float(value) for value in edge_delta),
            state_delta_due_to_innovation=tuple(float(value) for value in state_delta),
            state_delta_global_sum=global_delta,
            state_delta_global_tolerance=float(tolerance),
            external_mass_introduced_by_innovation_m3=0.0,
            topology_unchanged=True,
            innovation_admitted=innovation.admitted,
            diagnostic_only=not innovation.admitted,
        )

    def _validate_inputs(
        self,
        *,
        base_edge_flux: EdgeFlux,
        innovation: EdgeFluxInnovation,
        issue_time: datetime,
    ) -> None:
        if not isinstance(base_edge_flux, EdgeFlux):
            raise TypeError("base_edge_flux_required")
        if not isinstance(innovation, EdgeFluxInnovation):
            raise TypeError("edge_flux_innovation_required")
        if not _aware(issue_time):
            raise ValueError("edge_flux_innovation_issue_time_must_be_aware")
        complex_ = self.base_operator.complex
        if innovation.edge_keys != complex_.B.edge_keys:
            raise ValueError("edge_flux_innovation_edge_axis_mismatch")
        if innovation.unit != self.base_operator.config.flux_unit:
            raise ValueError("edge_flux_innovation_unit_mismatch")
        if innovation.available_at > issue_time:
            raise ValueError("edge_flux_innovation_not_available_at_issue")
        if innovation.valid_at < issue_time:
            raise ValueError("edge_flux_innovation_valid_before_issue")
        affected = np.abs(np.asarray(innovation.values, dtype=float)) > (
            self.base_operator.config.absolute_tolerance
        )
        admitted_edges = np.asarray(complex_.E.edge_admitted, dtype=bool)
        if bool((affected & ~admitted_edges).any()):
            raise ValueError("edge_flux_innovation_on_unadmitted_edge")
        if innovation.admitted:
            evidence = np.asarray(complex_.E.evidence_level, dtype=object)
            if bool((affected & (evidence == "candidate")).any()):
                raise ValueError("admitted_innovation_on_candidate_edge")
        elif not self.config.allow_unadmitted_innovation_for_diagnostics:
            raise ValueError("unadmitted_edge_flux_innovation_requires_diagnostic_mode")
