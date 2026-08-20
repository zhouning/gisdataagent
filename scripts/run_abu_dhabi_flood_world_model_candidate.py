"""Run the synthetic Abu Dhabi flood world-model candidate scenario."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    AbuDhabiFloodWorldModel,
    DrainageLink,
    FloodAction,
    FloodModelConfig,
    FloodNetwork,
    RainfallForcing,
    SurfacePatch,
)


def build_model() -> AbuDhabiFloodWorldModel:
    network = FloodNetwork(
        network_id="abu-dhabi-synthetic-stormwater-catchments",
        patches=(
            SurfacePatch("catchment-a", 10_000.0, 0.85, 0.0, 2.0, "fixture:patch-a"),
            SurfacePatch("catchment-b", 8_000.0, 0.75, 0.0, 1.0, "fixture:patch-b"),
        ),
        links=(
            DrainageLink(
                "pipe-a-to-b",
                "catchment-a",
                "catchment-b",
                0.05,
                600.0,
                "fixture:pipe-a-to-b",
            ),
            DrainageLink(
                "outfall-b",
                "catchment-b",
                None,
                0.03,
                900.0,
                "fixture:outfall-b",
            ),
        ),
        crs="EPSG:32640",
        provenance_id="fixture:abu-dhabi-flood-network",
    )
    return AbuDhabiFloodWorldModel(network, FloodModelConfig(300.0))


def run() -> dict[str, object]:
    model = build_model()
    initial = model.initial_state()
    rainfall = tuple(
        RainfallForcing(
            (120.0, 120.0),
            duration_seconds=300.0,
            timestamp_s=step * 300.0,
            provenance_id="fixture:synthetic-storm",
        )
        for step in range(4)
    )
    baseline = FloodAction(
        "baseline",
        (1.0, 1.0),
        (0.0, 0.0),
        "fixture:baseline",
    )
    intervention = FloodAction(
        "emergency-pumping-and-gate",
        (2.0, 2.0),
        (2.0, 1.0),
        "fixture:intervention",
    )
    results = model.counterfactual(
        initial,
        rainfall,
        {
            "baseline": (baseline,) * len(rainfall),
            "intervention": (intervention,) * len(rainfall),
        },
    )
    return {
        "scenario_id": "abu-dhabi-stormwater-candidate-synthetic-v1",
        "claim_boundary": "synthetic_diagnostic_only_not_real_city_prediction",
        "network": model.network.as_dict(),
        "results": {name: result.as_dict() for name, result in results.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run()
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    if args.output is None:
        print(text, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
