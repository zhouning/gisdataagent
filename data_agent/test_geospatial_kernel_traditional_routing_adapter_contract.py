from __future__ import annotations

from copy import deepcopy

import pytest

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_adapter_contract import (
    TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA,
    TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
    build_traditional_routing_adapter_request,
    validate_traditional_routing_adapter_response,
)


def test_valid_response_can_only_supply_outputs_and_final_state() -> None:
    request = _request()
    response = _response(request)

    trace = validate_traditional_routing_adapter_response(request, response)

    assert trace["boundary_inflow_m3s"] == request["boundary_inflow_m3s"]
    assert trace["lateral_inflow_m3s"] == request["lateral_inflow_m3s"]
    assert trace["feature_ids"] == [10, 20]
    assert trace["routed_discharge_m3s"] == [[2.0, 2.0], [3.0, 3.0]]
    assert trace["exchange_receipt"]["adapter_supplied_input_fields"] is False
    assert len(trace["exchange_receipt"]["request_sha256"]) == 64
    assert len(trace["exchange_receipt"]["response_sha256"]) == 64


def test_adapter_cannot_override_or_echo_input_arrays() -> None:
    request = _request()
    response = _response(request)
    response["boundary_inflow_m3s"] = [[0.0, 0.0], [0.0, 0.0]]

    with pytest.raises(
        ValueError,
        match="traditional_routing_adapter_response_fields_invalid",
    ):
        validate_traditional_routing_adapter_response(request, response)


def test_request_hash_tampering_and_wrong_response_binding_fail_closed() -> None:
    request = _request()
    request["boundary_inflow_m3s"][0][0] = 99.0

    with pytest.raises(
        ValueError,
        match="traditional_routing_adapter_request_seal_invalid",
    ):
        validate_traditional_routing_adapter_response(request, _response(request))

    intact = _request()
    response = _response(intact)
    response["request_sha256"] = "0" * 64
    with pytest.raises(
        ValueError,
        match="traditional_routing_adapter_response_binding_invalid",
    ):
        validate_traditional_routing_adapter_response(intact, response)


def test_outcome_content_and_nonfinite_outputs_are_rejected() -> None:
    request = _request()
    response = _response(request)
    response["serialized_final_state"] = {"outcome_values": [1.0]}
    with pytest.raises(
        ValueError,
        match="traditional_routing_adapter_response_forbidden_content",
    ):
        validate_traditional_routing_adapter_response(request, response)

    response = _response(request)
    response["routed_discharge_m3s"][0][0] = float("nan")
    with pytest.raises(
        ValueError,
        match="traditional_routing_adapter_response_values_invalid",
    ):
        validate_traditional_routing_adapter_response(request, response)


def test_request_rejects_cycles_negative_inputs_and_forbidden_initial_state() -> None:
    kwargs = _request_kwargs()
    kwargs["downstream_feature_ids"] = (20, 10)
    with pytest.raises(ValueError, match="request_network_invalid"):
        build_traditional_routing_adapter_request(**kwargs)

    kwargs = _request_kwargs()
    kwargs["lateral_inflow_m3s"] = ((0.0, -1.0), (0.0, 0.0))
    with pytest.raises(ValueError, match="dynamic_inputs_invalid"):
        build_traditional_routing_adapter_request(**kwargs)

    kwargs = _request_kwargs()
    kwargs["serialized_initial_state"] = {"outcome_path": "forbidden.csv"}
    with pytest.raises(ValueError, match="request_forbidden_content"):
        build_traditional_routing_adapter_request(**kwargs)


def _request() -> dict[str, object]:
    return build_traditional_routing_adapter_request(**_request_kwargs())


def _request_kwargs() -> dict[str, object]:
    return {
        "request_id": "fixture-request-1",
        "candidate_id": "fixture-candidate",
        "runtime_artifact": {
            "path": "candidate/runtime.bin",
            "sha256": "a" * 64,
            "size_bytes": 17,
        },
        "feature_ids": (10, 20),
        "downstream_feature_ids": (20, None),
        "geometry": {
            "length_m": (1000.0, 1200.0),
            "bottom_width_m": (10.0, 12.0),
            "slope": (0.001, 0.002),
            "manning_n": (0.03, 0.035),
        },
        "timestep_seconds": 300.0,
        "boundary_inflow_m3s": ((2.0, 0.0), (3.0, 0.0)),
        "lateral_inflow_m3s": ((0.0, 0.0), (0.0, 0.0)),
        "serialized_initial_state": {"discharge_m3s": [2.0, 2.0]},
    }


def _response(request: dict[str, object]) -> dict[str, object]:
    request_copy = deepcopy(request)
    request_sha256 = request_copy.pop("request_seal")["sha256"]
    return {
        "schema": TRADITIONAL_ROUTING_ADAPTER_RESPONSE_SCHEMA,
        "adapter_protocol": TRADITIONAL_ROUTING_JSON_ADAPTER_PROTOCOL,
        "request_id": request["request_id"],
        "request_sha256": request_sha256,
        "routed_discharge_m3s": [[2.0, 2.0], [3.0, 3.0]],
        "total_storage_m3": [0.0, 0.0, 0.0],
        "serialized_final_state": {"discharge_m3s": [3.0, 3.0]},
    }
