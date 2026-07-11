from data_agent.api import uwm_traditional_livability_routes as routes
import json

import pytest
from starlette.requests import Request

from data_agent.test_traditional_livability_facility_dictionary import (
    dictionary_fixture,
    matrix_fixture,
)
from data_agent.test_traditional_livability_s6 import point_request, resource_fixture
from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
    unavailable_compatibility_matrix,
    unavailable_facility_dictionary,
    validate_compatibility_matrix,
    validate_facility_dictionary,
)
from data_agent.uwm.traditional_livability_s6_semantics import (
    resolve_s6_facility_semantics,
    validate_human_confirmation,
)


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def _request(path, *, method="GET", payload=None):
    body = json.dumps(payload or {}).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        },
        receive,
    )


def _write_s6_snapshots(directory, *, resources=None, dictionary=None, compatibility=None):
    directory.mkdir()
    resource_payload = json.loads(json.dumps(resources or resource_fixture()))
    if "content_digest" not in resource_payload:
        resource_payload = dict(resource_payload)
        resource_payload["content_digest"] = compute_canonical_content_digest(
            resource_payload
        )
    (directory / "uwm_traditional_livability_s6_resources.json").write_text(
        json.dumps(resource_payload), encoding="utf-8"
    )
    (directory / "uwm_traditional_livability_s6_dictionary.json").write_text(
        json.dumps(dictionary or unavailable_facility_dictionary()), encoding="utf-8"
    )
    (directory / "uwm_traditional_livability_s6_compatibility.json").write_text(
        json.dumps(compatibility or unavailable_compatibility_matrix()), encoding="utf-8"
    )
    return directory


def _authenticated(monkeypatch, username="authenticated-planner"):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": username})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: (username, "analyst"))


def test_traditional_livability_routes_are_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_uwm_traditional_livability_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/uwm/traditional-livability")
    assert "POST" in _route_methods(route_list, "/api/uwm/traditional-livability/map")
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability"
    )
    assert "POST" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability/map"
    )
    assert "GET" in _route_methods(
        route_list, "/api/uwm/traditional-livability/s1"
    )
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability/s1"
    )
    assert "GET" in _route_methods(
        route_list, "/api/uwm/traditional-livability/s7"
    )
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability/s7"
    )
    for path, method in (
        ("/api/uwm/traditional-livability/s6/resources", "GET"),
        ("/api/uwm/traditional-livability/s6/dictionary", "GET"),
        ("/api/uwm/traditional-livability/s6/analyze", "POST"),
    ):
        assert method in _route_methods(route_list, path)
        assert method in _route_methods(frontend_route_list, path)


def test_s1_snapshot_loader_validates_schema(tmp_path, monkeypatch):
    path = tmp_path / "s1.json"
    path.write_text(json.dumps({"schema": "uwm.traditional_livability.s1_assessment.v1", "assessment_id": "s1"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(path))

    assert routes._load_s1_snapshot()["assessment_id"] == "s1"


def test_s1_snapshot_loader_fails_closed_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(tmp_path / "missing.json"))

    with pytest.raises(routes.S1SnapshotUnavailable) as error:
        routes._load_s1_snapshot()

    assert error.value.payload["ready"] is False
    assert "s1_snapshot_missing" in error.value.payload["blockers"]


def test_s7_snapshot_loader_validates_schema(tmp_path, monkeypatch):
    import json
    path = tmp_path / "s7.json"
    path.write_text(json.dumps({"schema": "uwm.traditional_livability.s7_siting.v1", "siting_id": "s7"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S7_PATH", str(path))
    assert routes._load_s7_snapshot()["siting_id"] == "s7"


def test_s7_snapshot_loader_fails_closed_when_missing(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S7_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(routes.S7SnapshotUnavailable) as error:
        routes._load_s7_snapshot()
    assert error.value.payload["ready"] is False
    assert "s7_snapshot_missing" in error.value.payload["blockers"]


def test_s6_path_accepts_controlled_directory_or_resource_json(tmp_path, monkeypatch):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    resource_path = snapshot_dir / "uwm_traditional_livability_s6_resources.json"

    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    assert routes._resolve_s6_path("resources") == resource_path
    assert routes._resolve_s6_path("dictionary").parent == snapshot_dir

    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(resource_path))
    assert routes._resolve_s6_path("resources") == resource_path
    assert routes._resolve_s6_path("compatibility").parent == snapshot_dir


@pytest.mark.parametrize("failure", ["missing", "unreadable", "invalid_json", "invalid_schema"])
def test_s6_resource_loader_fails_closed(tmp_path, monkeypatch, failure):
    path = tmp_path / "resources.json"
    if failure == "unreadable":
        path.mkdir()
    elif failure == "invalid_json":
        path.write_text("{", encoding="utf-8")
    elif failure == "invalid_schema":
        path.write_text(json.dumps({"schema": "wrong", "ready": True}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))

    with pytest.raises(routes.S6SnapshotUnavailable) as error:
        routes._load_s6_snapshot("resources")

    assert error.value.payload["ready"] is False
    assert error.value.payload["blockers"]


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": "uwm.traditional_livability.s6_fulu_resources.v1", "ready": False},
        {
            "schema": "uwm.traditional_livability.s6_fulu_resources.v1",
            "ready": True,
            "scope": "scope",
            "planning_areas": {},
            "planning_resources": [],
            "current_facilities": [],
        },
    ],
)
def test_s6_resource_loader_rejects_invalid_runtime_contract(tmp_path, monkeypatch, payload):
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))

    with pytest.raises(routes.S6SnapshotUnavailable):
        routes._load_s6_snapshot("resources")


def test_s6_resource_loader_rejects_nonfinite_json(tmp_path, monkeypatch):
    path = tmp_path / "resources.json"
    path.write_text(
        '{"schema":"uwm.traditional_livability.s6_fulu_resources.v1","ready":true,"scope":"scope","planning_areas":[],"planning_resources":[],"current_facilities":[],"bad":NaN}',
        encoding="utf-8",
    )
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))

    with pytest.raises(routes.S6SnapshotUnavailable):
        routes._load_s6_snapshot("resources")


@pytest.mark.parametrize(
    ("digest_value", "expected_blocker"),
    [
        (None, "s6_resources_snapshot_digest_missing"),
        ("sha256:tampered", "s6_resources_snapshot_digest_mismatch"),
    ],
)
def test_s6_resource_loader_requires_exact_canonical_digest(
    tmp_path, monkeypatch, digest_value, expected_blocker
):
    payload = resource_fixture()
    if digest_value is not None:
        payload["content_digest"] = digest_value
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))

    with pytest.raises(routes.S6SnapshotUnavailable) as error:
        routes._load_s6_snapshot("resources")

    assert error.value.payload["blockers"] == [expected_blocker]


@pytest.mark.parametrize(
    "tamper",
    [
        "geometry",
        "raw_resource_evidence",
        "distance_crs",
        "facility_mapping_status",
        "complete_inventory",
    ],
)
def test_s6_resource_loader_rejects_valid_shaped_content_tamper(
    tmp_path, monkeypatch, tamper
):
    payload = json.loads(json.dumps(resource_fixture()))
    payload["content_digest"] = compute_canonical_content_digest(payload)
    if tamper == "geometry":
        payload["planning_areas"][0]["metric_geometry"]["coordinates"][0][0][0] += 1
    elif tamper == "raw_resource_evidence":
        payload["planning_resources"][0]["interpretation_evidence"]["value"] = "tampered"
        payload["planning_resources"][0]["resource_domain"] = "tampered_domain"
    elif tamper == "distance_crs":
        payload["planning_areas"][0]["distance_crs"] = "EPSG:3857"
    elif tamper == "facility_mapping_status":
        payload["current_facilities"][0]["mapping_status"] = "authoritative"
    else:
        payload["facility_inventory"]["complete_inventory"] = True
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))

    with pytest.raises(routes.S6SnapshotUnavailable) as error:
        routes._load_s6_snapshot("resources")

    assert error.value.payload["blockers"] == [
        "s6_resources_snapshot_digest_mismatch"
    ]


@pytest.mark.asyncio
async def test_s6_resources_endpoint_returns_503_for_digest_mismatch(
    tmp_path, monkeypatch
):
    payload = resource_fixture()
    payload["content_digest"] = "sha256:tampered"
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s6_resources(
        _request("/api/uwm/traditional-livability/s6/resources")
    )

    assert response.status_code == 503
    assert json.loads(response.body)["blockers"] == [
        "s6_resources_snapshot_digest_mismatch"
    ]


@pytest.mark.asyncio
async def test_s6_resources_endpoint_returns_503_for_invalid_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "resources.json"
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("user", "analyst"))

    response = await routes.uwm_traditional_livability_s6_resources(
        _request("/api/uwm/traditional-livability/s6/resources")
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_s6_dictionary_unavailable_returns_http_200_blocker(tmp_path, monkeypatch):
    _write_s6_snapshots(tmp_path / "snapshots")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(tmp_path / "snapshots"))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("user", "analyst"))

    response = await routes.uwm_traditional_livability_s6_dictionary(
        _request("/api/uwm/traditional-livability/s6/dictionary")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["schema"] == "uwm.traditional_livability.s6_authority_status.v1"
    assert payload["ready"] is False
    assert payload["facility_dictionary"] == {
        "status": "dictionary_unavailable",
        "version": None,
        "ready": False,
        "blockers": ["authoritative_43_class_facility_dictionary_missing"],
        "content_digest": None,
        "classes": [],
    }
    assert payload["compatibility_matrix"]["status"] == "compatibility_matrix_unavailable"
    assert payload["compatibility_matrix"]["version"] is None
    assert payload["compatibility_matrix"]["ready"] is False
    assert payload["compatibility_matrix"]["blockers"]


@pytest.mark.asyncio
async def test_s6_dictionary_envelope_classes_build_valid_human_selected_confirmation(
    tmp_path, monkeypatch
):
    dictionary = validate_facility_dictionary(dictionary_fixture())
    snapshot_dir = _write_s6_snapshots(
        tmp_path / "snapshots",
        dictionary=dictionary,
    )
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("user", "analyst"))

    response = await routes.uwm_traditional_livability_s6_dictionary(
        _request("/api/uwm/traditional-livability/s6/dictionary")
    )
    envelope = json.loads(response.body)
    exposed_dictionary = envelope["facility_dictionary"]
    selected_class = exposed_dictionary["classes"][0]
    assert set(selected_class) == {"class_id", "label"}
    assert "alias_index" not in exposed_dictionary
    assert "keyword_index" not in exposed_dictionary

    backend_dictionary = {
        "ready": exposed_dictionary["ready"],
        "classes": exposed_dictionary["classes"],
        "source_metadata": {"dictionary_version": exposed_dictionary["version"]},
        "content_digest": exposed_dictionary["content_digest"],
    }
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(
        **original_input,
        dictionary=backend_dictionary,
    )
    selected_candidate = {
        "standard_class_id": selected_class["class_id"],
        "standard_class_label": selected_class["label"],
        "authority_level": "human_confirmation",
        "match_method": "human_selected",
        "confidence": "human_confirmed",
        "dictionary_version": exposed_dictionary["version"],
        "rule_version": None,
        "human_confirmation_required": False,
        "human_confirmed": True,
        "evidence": [
            {
                "evidence_type": "reviewer_reason",
                "reason": "审查员核验了本次申请材料。",
            }
        ],
    }
    confirmation = {
        "actor_id": "frontend_reviewer",
        "confirmed_at": "2026-07-11T02:00:00Z",
        "selected_standard_class_id": selected_class["class_id"],
        "original_input_digest": resolution["original_input_digest"],
        "dictionary_version": exposed_dictionary["version"],
    }

    validated = validate_human_confirmation(
        confirmation,
        dictionary=backend_dictionary,
        original_input=original_input,
        selected_candidate=selected_candidate,
    )

    assert validated["valid"] is True
    assert validated["selected_candidate"]["match_method"] == "human_selected"


@pytest.mark.parametrize("tamper", ["class", "digest"])
@pytest.mark.asyncio
async def test_s6_dictionary_revalidates_normalized_snapshot_and_rejects_tamper(
    tmp_path, monkeypatch, tamper
):
    dictionary = validate_facility_dictionary(dictionary_fixture())
    if tamper == "class":
        dictionary["classes"][0]["label"] = "Tampered label"
    else:
        dictionary["provided_content_digest"] = "sha256:tampered"
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots", dictionary=dictionary)
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s6_dictionary(
        _request("/api/uwm/traditional-livability/s6/dictionary")
    )
    facility_dictionary = json.loads(response.body)["facility_dictionary"]

    assert facility_dictionary["ready"] is False
    assert facility_dictionary["classes"] == []
    assert facility_dictionary["blockers"]


@pytest.mark.parametrize("tamper", ["rule", "digest"])
@pytest.mark.asyncio
async def test_s6_compatibility_revalidates_normalized_snapshot_and_rejects_tamper(
    tmp_path, monkeypatch, tamper
):
    compatibility = validate_compatibility_matrix(matrix_fixture())
    if tamper == "rule":
        compatibility["rules"][0]["relationship"] = "compatible"
    else:
        compatibility["provided_content_digest"] = "sha256:tampered"
    snapshot_dir = _write_s6_snapshots(
        tmp_path / "snapshots", compatibility=compatibility
    )
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s6_dictionary(
        _request("/api/uwm/traditional-livability/s6/dictionary")
    )
    matrix = json.loads(response.body)["compatibility_matrix"]

    assert matrix["ready"] is False
    assert matrix["blockers"]


@pytest.mark.parametrize("matrix_failure", ["missing", "invalid"])
@pytest.mark.asyncio
async def test_s6_dictionary_envelope_reports_matrix_snapshot_failure(
    tmp_path, monkeypatch, matrix_failure
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    matrix_path = snapshot_dir / "uwm_traditional_livability_s6_compatibility.json"
    if matrix_failure == "missing":
        matrix_path.unlink()
    else:
        matrix_path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("user", "analyst"))

    response = await routes.uwm_traditional_livability_s6_dictionary(
        _request("/api/uwm/traditional-livability/s6/dictionary")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["compatibility_matrix"]["ready"] is False
    expected = f"s6_compatibility_snapshot_{'missing' if matrix_failure == 'missing' else 'schema_invalid'}"
    assert expected in payload["compatibility_matrix"]["blockers"]


@pytest.mark.parametrize(
    ("request_payload", "expected_blocker"),
    [
        (point_request(analysis_area_id="outside"), "unknown_analysis_area:outside"),
        (point_request(input_mode="uploaded_shapefile"), "unsupported_input_mode"),
    ],
)
@pytest.mark.asyncio
async def test_s6_analyze_returns_400_for_real_validation_blockers(
    tmp_path, monkeypatch, request_payload, expected_blocker
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("user", "analyst"))

    response = await routes.uwm_traditional_livability_s6_analyze(
        _request("/api/uwm/traditional-livability/s6/analyze", method="POST", payload=request_payload)
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert expected_blocker in payload["validation_blockers"]


@pytest.mark.asyncio
async def test_s6_analyze_keeps_valid_evidence_limited_analysis_http_200(tmp_path, monkeypatch):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("user", "analyst"))

    response = await routes.uwm_traditional_livability_s6_analyze(
        _request(
            "/api/uwm/traditional-livability/s6/analyze",
            method="POST",
            payload=point_request(),
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["validation_blockers"] == []
    assert payload["production_blockers"]


@pytest.mark.asyncio
async def test_s6_analyze_binds_confirmation_actor_to_authenticated_username(
    tmp_path, monkeypatch
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch, "trusted-user")
    request_payload = point_request(
        confirmed_standard_class_id="spoofed.class",
        human_confirmation={
            "actor_id": "spoofed-user",
            "confirmed_at": "2026-07-11T02:00:00Z",
            "selected_standard_class_id": "spoofed.class",
            "original_input_digest": "sha256:spoofed",
            "dictionary_version": "spoofed-version",
            "selected_candidate": {
                "match_method": "human_selected",
                "evidence": [{"evidence_type": "reviewer_reason", "reason": "reviewed"}],
            },
        },
    )

    response = await routes.uwm_traditional_livability_s6_analyze(
        _request(
            "/api/uwm/traditional-livability/s6/analyze",
            method="POST",
            payload=request_payload,
        )
    )
    payload = json.loads(response.body)

    assert payload["human_confirmation_validation"]["actor_id"] == "trusted-user"
    assert payload["normalized_request"]["human_confirmation"]["actor_id"] == "trusted-user"
    assert "spoofed-user" not in response.body.decode("utf-8")
