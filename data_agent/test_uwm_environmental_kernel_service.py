import json

import pytest

from data_agent.test_build_uwm_environmental_kernel_chongqing import fixture_root
from data_agent.uwm.environmental_kernel.service import (
    EnvironmentalKernelConflict,
    EnvironmentalKernelService,
)
from scripts.build_uwm_environmental_kernel_chongqing import build_product


def product_dir(tmp_path):
    output = tmp_path / "product"
    build_product(source_root=fixture_root(tmp_path), output_dir=output)
    return output


def test_service_loads_bundle_and_returns_deep_copies(tmp_path):
    service = EnvironmentalKernelService(product_dir(tmp_path))
    scene = service.scene()
    scene["bundle_id"] = "mutated"

    assert service.scene()["bundle_id"] != "mutated"
    assert service.evidence_gate()["bundle_id"] == service.map_payload()["bundle_id"]


def test_service_rejects_bundle_mismatch(tmp_path):
    root = product_dir(tmp_path)
    gate_path = root / "evidence_gate.json"
    gate = json.loads(gate_path.read_text())
    gate["bundle_id"] = "other"
    gate_path.write_text(json.dumps(gate))

    with pytest.raises(ValueError, match="environmental_kernel_bundle_mismatch"):
        EnvironmentalKernelService(root)


def test_closed_action_response_returns_conflict_and_binds_actor(tmp_path):
    service = EnvironmentalKernelService(product_dir(tmp_path))
    scene = service.scene()

    with pytest.raises(EnvironmentalKernelConflict) as error:
        service.run(
            request={
                "action_type": "increase_tree_canopy_proxy",
                "target_node_ids": [scene["state"]["spatial_nodes"][0]["node_id"]],
                "state_snapshot_digest": scene["state"]["snapshot_digest"],
                "actor": "spoofed",
            },
            actor="authenticated-user",
        )

    assert error.value.code == "environmental_action_response_closed"
    assert error.value.actor == "authenticated-user"
