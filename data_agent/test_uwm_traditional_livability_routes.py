from data_agent.api import uwm_traditional_livability_routes as routes
import json

import pytest
from starlette.requests import Request

from data_agent.test_traditional_livability_facility_dictionary import (
    dictionary_fixture,
    matrix_fixture,
)
from data_agent.test_traditional_livability_s6 import point_request, resource_fixture
from data_agent.test_traditional_livability_s6_semantics import (
    authoritative_dictionary_fixture,
)
from data_agent.uwm import traditional_livability_s4 as s4_engine
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
        ("/api/uwm/traditional-livability/s4/resources", "GET"),
        ("/api/uwm/traditional-livability/s4/analyze", "POST"),
        ("/api/uwm/traditional-livability/s6/resources", "GET"),
        ("/api/uwm/traditional-livability/s6/dictionary", "GET"),
        ("/api/uwm/traditional-livability/s6/analyze", "POST"),
    ):
        assert method in _route_methods(route_list, path)
        assert method in _route_methods(frontend_route_list, path)


def _s1_snapshot():
    payload = {
        "schema": "uwm.traditional_livability.s1_assessment.v1",
        "ready": True,
        "supply_metrics": [],
        "production_blockers": ["facility_capacity_missing"],
    }
    payload["content_digest"] = compute_canonical_content_digest(payload)
    return payload


def _s4_project(**overrides):
    payload = {
        "actor_id": "untrusted-client",
        "analysis_area_id": "fulu_heping",
        "planning_parcel_id": "parcel-selected",
        "project_name": "和平村项目",
        "project_description": "测试项目",
        "uses": [
            {
                "use_id": "use-market",
                "use_name": "农贸市场",
                "raw_use_type": "室内市场",
                "use_description": "固定室内市场",
                "gfa_m2": 1000.0,
                "confirmed_standard_class_id": "facility.market",
                "human_confirmation": None,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _valid_s4_confirmation(dictionary, *, actor_id="spoofed-reviewer"):
    original_input = {
        "facility_name": "农贸市场",
        "raw_facility_type": "室内市场",
        "use_description": "固定室内市场",
    }
    resolution = resolve_s6_facility_semantics(
        **original_input,
        dictionary=dictionary,
    )
    candidate = resolution["candidates"][0]
    return {
        "actor_id": actor_id,
        "confirmed_at": "2026-07-11T02:00:00Z",
        "selected_standard_class_id": candidate["standard_class_id"],
        "original_input_digest": resolution["original_input_digest"],
        "dictionary_version": dictionary["source_metadata"]["dictionary_version"],
        "selected_candidate": candidate,
    }


def _s4_compatibility():
    payload = matrix_fixture()
    payload["effective_date"] = "2026-07-09"
    payload["content_digest"] = compute_canonical_content_digest(payload)
    compatibility = validate_compatibility_matrix(payload)
    assert compatibility["ready"] is True
    return compatibility


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


@pytest.mark.asyncio
async def test_s4_resources_exposes_real_parcels_minimal_classes_and_readiness(
    tmp_path, monkeypatch
):
    snapshot_dir = _write_s6_snapshots(
        tmp_path / "snapshots",
        dictionary=authoritative_dictionary_fixture(),
        compatibility=_s4_compatibility(),
    )
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_resources(
        _request("/api/uwm/traditional-livability/s4/resources")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["schema"] == "uwm.traditional_livability.s4_resources.v1"
    assert {row["planning_parcel_id"] for row in payload["planning_parcels"]} >= {
        "parcel-selected",
        "other-area-parcel",
    }
    assert payload["planning_parcels"][0].keys() <= {
        "planning_parcel_id",
        "analysis_area_id",
        "raw_land_use_code",
        "raw_land_use_name",
        "resource_domain",
        "planning_status",
        "display_geometry_wgs84",
    }
    assert payload["facility_classes"][0].keys() == {"class_id", "label"}
    assert payload["readiness"]["s1"]["ready"] is True
    assert payload["readiness"]["s1"]["blockers"] == ["facility_capacity_missing"]
    assert payload["readiness"]["s6_resources"]["complete"] is False
    assert payload["readiness"]["dictionary"]["complete"] is True
    assert payload["readiness"]["compatibility"]["ready"] is True


@pytest.mark.asyncio
async def test_s4_resources_returns_503_when_required_snapshot_is_tampered(
    tmp_path, monkeypatch
):
    resources = resource_fixture()
    resources["content_digest"] = "sha256:tampered"
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots", resources=resources)
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_resources(
        _request("/api/uwm/traditional-livability/s4/resources")
    )

    assert response.status_code == 503
    assert "s6_resources_snapshot_digest_mismatch" in json.loads(response.body)["blockers"]


@pytest.mark.asyncio
async def test_s4_resources_returns_503_when_s1_snapshot_digest_is_tampered(
    tmp_path, monkeypatch
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    s1_snapshot = _s1_snapshot()
    s1_snapshot["content_digest"] = compute_canonical_content_digest(s1_snapshot)
    s1_snapshot["supply_metrics"].append({"tampered": True})
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(s1_snapshot), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_resources(
        _request("/api/uwm/traditional-livability/s4/resources")
    )

    assert response.status_code == 503
    assert "s1_snapshot_digest_mismatch" in json.loads(response.body)["blockers"]


@pytest.mark.parametrize("authority", ["dictionary", "compatibility"])
@pytest.mark.asyncio
async def test_s4_resources_keeps_missing_or_malformed_optional_authority_http_200(
    tmp_path, monkeypatch, authority
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    authority_path = snapshot_dir / routes.S6_RESOURCE_FILES[authority]
    if authority == "dictionary":
        authority_path.unlink()
    else:
        authority_path.write_text("{malformed", encoding="utf-8")
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_resources(
        _request("/api/uwm/traditional-livability/s4/resources")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["readiness"][authority]["ready"] is False
    assert any(
        blocker.startswith(f"s6_{authority}_snapshot_")
        for blocker in payload["readiness"][authority]["blockers"]
    )


@pytest.mark.asyncio
async def test_s4_analyze_binds_actor_validates_project_and_ignores_client_snapshots(
    tmp_path, monkeypatch
):
    dictionary = authoritative_dictionary_fixture()
    snapshot_dir = _write_s6_snapshots(
        tmp_path / "snapshots",
        dictionary=dictionary,
        compatibility=_s4_compatibility(),
    )
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch, "trusted-planner")
    captured = {"s6_requests": [], "s6_results": []}
    real_validate = routes.validate_s4_project_request
    real_s6_analyze = s4_engine.analyze_s6_facility_proposal

    def capture_validate(payload, *, actor_id):
        result = real_validate(payload, actor_id=actor_id)
        captured["project"] = result
        return result

    def capture_s6(**kwargs):
        captured["s6_requests"].append(kwargs["request"])
        result = real_s6_analyze(**kwargs)
        captured["s6_results"].append(result)
        return result

    monkeypatch.setattr(routes, "validate_s4_project_request", capture_validate)
    monkeypatch.setattr(s4_engine, "analyze_s6_facility_proposal", capture_s6)
    spoofed_confirmation = _valid_s4_confirmation(dictionary)
    omitted_confirmation = _valid_s4_confirmation(dictionary)
    omitted_confirmation.pop("actor_id")
    base_use = _s4_project()["uses"][0]
    request_payload = {
        **_s4_project(
            uses=[
                {
                    **base_use,
                    "use_id": "use-spoofed-actor",
                    "human_confirmation": spoofed_confirmation,
                },
                {
                    **base_use,
                    "use_id": "use-omitted-actor",
                    "human_confirmation": omitted_confirmation,
                },
            ]
        ),
        "s1_snapshot": {"tampered": True},
        "s6_resources": {"tampered": True},
    }

    response = await routes.uwm_traditional_livability_s4_analyze(
        _request("/api/uwm/traditional-livability/s4/analyze", method="POST", payload=request_payload)
    )

    assert response.status_code == 200
    assert captured["project"]["actor_id"] == "trusted-planner"
    assert captured["project"]["raw_request"]["actor_id"] == "untrusted-client"
    normalized_uses = captured["project"]["normalized_request"]["uses"]
    assert {
        use["human_confirmation"]["actor_id"] for use in normalized_uses
    } == {"trusted-planner"}
    assert {
        request["human_confirmation"]["actor_id"]
        for request in captured["s6_requests"]
    } == {"trusted-planner"}
    assert {
        result["human_confirmation_validation"]["actor_id"]
        for result in captured["s6_results"]
    } == {"trusted-planner"}
    assert all(
        result["human_confirmation_validation"]["valid"] is True
        for result in captured["s6_results"]
    )
    assert "spoofed-reviewer" not in json.dumps(captured)
    assert "tampered" not in json.dumps(captured)


@pytest.mark.parametrize("authority", ["dictionary", "compatibility"])
@pytest.mark.asyncio
async def test_s4_analyze_keeps_optional_authority_failure_evidence_limited_http_200(
    tmp_path, monkeypatch, authority
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    authority_path = snapshot_dir / routes.S6_RESOURCE_FILES[authority]
    authority_path.unlink()
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_analyze(
        _request(
            "/api/uwm/traditional-livability/s4/analyze",
            method="POST",
            payload=_s4_project(uses=[{**_s4_project()["uses"][0], "confirmed_standard_class_id": None}]),
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "insufficient_evidence"
    assert payload["project_blockers"]


@pytest.mark.asyncio
async def test_s4_analyze_returns_400_for_invalid_confirmation_from_real_engine(
    tmp_path, monkeypatch
):
    dictionary = authoritative_dictionary_fixture()
    snapshot_dir = _write_s6_snapshots(
        tmp_path / "snapshots",
        dictionary=dictionary,
        compatibility=_s4_compatibility(),
    )
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch, "trusted-planner")
    confirmation = _valid_s4_confirmation(dictionary)
    confirmation["original_input_digest"] = "sha256:tampered"
    project = _s4_project(
        uses=[
            {
                **_s4_project()["uses"][0],
                "human_confirmation": confirmation,
            }
        ]
    )

    response = await routes.uwm_traditional_livability_s4_analyze(
        _request("/api/uwm/traditional-livability/s4/analyze", method="POST", payload=project)
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert payload["validation_blockers"] == ["original_input_digest_mismatch"]


@pytest.mark.parametrize(
    ("project", "expected_blocker"),
    [
        (_s4_project(project_name=""), "project_name_missing"),
        (
            _s4_project(
                uses=[
                    {
                        **_s4_project()["uses"][0],
                        "gfa_m2": 0,
                    }
                ]
            ),
            "uses[0].gfa_m2_must_be_finite_positive_number",
        ),
        (_s4_project(planning_parcel_id="missing"), "unknown_planning_parcel:missing"),
        (_s4_project(analysis_area_id="fulu_heping", planning_parcel_id="other-area-parcel"), "planning_parcel_outside_analysis_area:other-area-parcel"),
    ],
)
@pytest.mark.asyncio
async def test_s4_analyze_returns_400_for_input_parcel_and_cross_area_errors(
    tmp_path, monkeypatch, project, expected_blocker
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_analyze(
        _request("/api/uwm/traditional-livability/s4/analyze", method="POST", payload=project)
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert expected_blocker in payload["validation_errors"]


@pytest.mark.asyncio
async def test_s4_analyze_keeps_valid_evidence_limited_result_http_200(
    tmp_path, monkeypatch
):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    s1_path = tmp_path / "s1.json"
    s1_path.write_text(json.dumps(_s1_snapshot()), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(s1_path))
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    _authenticated(monkeypatch)

    response = await routes.uwm_traditional_livability_s4_analyze(
        _request("/api/uwm/traditional-livability/s4/analyze", method="POST", payload=_s4_project())
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "insufficient_evidence"
    assert payload["project_blockers"]
