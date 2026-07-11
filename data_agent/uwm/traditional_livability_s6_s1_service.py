from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_s1_comparison import (
    compare_s1_baseline_and_proposal,
)
from data_agent.uwm.traditional_livability_s6_s1_handoff import (
    build_s6_s1_handoff,
)
from data_agent.uwm.traditional_livability_s6_s1_product import (
    FACILITY_FILENAME,
    MATRIX_FILENAME,
    PROFILE_FILENAME,
)


class HandoffNotFound(KeyError):
    pass


class HandoffConflict(RuntimeError):
    pass


class TraditionalLivabilityS6S1Service:
    def __init__(
        self,
        *,
        facility_product: Mapping[str, Any],
        demand_units: list[Mapping[str, Any]],
        metric_profiles: Mapping[str, Any],
        synthesis_matrices: Mapping[str, Mapping[str, Any]],
    ):
        self.facility_product = deepcopy(dict(facility_product))
        self.demand_units = deepcopy(list(demand_units))
        self.metric_profiles = deepcopy(dict(metric_profiles))
        self.synthesis_matrices = deepcopy(dict(synthesis_matrices))
        self._handoffs: dict[str, dict[str, Any]] = {}
        self._results: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_product_dir(cls, product_dir: Path):
        root = Path(product_dir)
        facility = json.loads((root / FACILITY_FILENAME).read_text(encoding="utf-8"))
        profiles = json.loads((root / PROFILE_FILENAME).read_text(encoding="utf-8"))
        matrix_collection = json.loads((root / MATRIX_FILENAME).read_text(encoding="utf-8"))
        matrices = {
            row["matrix_id"]: row
            for row in matrix_collection.get("matrices") or []
            if isinstance(row, Mapping) and row.get("matrix_id")
        }
        demand_units = facility.get("demand_units") or []
        return cls(
            facility_product=facility,
            demand_units=demand_units,
            metric_profiles=profiles,
            synthesis_matrices=matrices,
        )

    def list_profiles(self) -> dict[str, Any]:
        return deepcopy(self.metric_profiles)

    def create_handoff(
        self,
        *,
        s6_analysis: Mapping[str, Any],
        actor_id: str,
        created_at: str,
    ) -> dict[str, Any]:
        handoff = build_s6_s1_handoff(
            s6_analysis=s6_analysis,
            metric_profiles=self.metric_profiles,
            actor_id=actor_id,
            created_at=created_at,
        )
        self._handoffs[handoff["handoff_id"]] = deepcopy(handoff)
        return deepcopy(handoff)

    def get_handoff(self, handoff_id: str, *, actor_id: str) -> dict[str, Any]:
        handoff = self._handoffs.get(str(handoff_id))
        if handoff is None or handoff.get("actor_id") != actor_id:
            raise HandoffNotFound("handoff_not_found")
        return deepcopy(handoff)

    def execute_s1(self, handoff_id: str, *, actor_id: str) -> dict[str, Any]:
        handoff = self.get_handoff(handoff_id, actor_id=actor_id)
        if handoff.get("ready_for_s1") is not True:
            raise HandoffConflict("handoff_not_ready_for_s1")
        if handoff.get("metric_profile_bundle_id") != self.metric_profiles.get("bundle_id"):
            raise HandoffConflict("metric_profile_bundle_mismatch")
        source_bundle = handoff.get("source_resource_bundle")
        source_bundle = source_bundle if isinstance(source_bundle, Mapping) else {}
        if source_bundle.get("bundle_id") != self.facility_product.get("bundle_id"):
            raise HandoffConflict("facility_product_bundle_mismatch")
        profile_id = (handoff.get("applicable_metric_profiles") or [{}])[0].get("profile_id")
        profile = next(
            (
                deepcopy(dict(row))
                for row in self.metric_profiles.get("profiles") or []
                if isinstance(row, Mapping) and row.get("profile_id") == profile_id
            ),
            None,
        )
        if profile is None:
            raise HandoffConflict("metric_profile_missing")
        matrix_id = profile.get("synthesis_matrix_id")
        matrix = deepcopy(self.synthesis_matrices.get(matrix_id) or {"status": "unavailable"})
        result = compare_s1_baseline_and_proposal(
            handoff=handoff,
            facility_product=self.facility_product,
            demand_units=self.demand_units,
            profile=profile,
            synthesis_matrix=matrix,
        )
        self._results[handoff_id] = deepcopy(result)
        return deepcopy(result)
