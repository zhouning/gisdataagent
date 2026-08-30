import json
from datetime import UTC, datetime

from data_agent import runtime_privilege_contract as contract


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row


class _FakeConnection:
    def __init__(self, *, roles=None, privileges=None):
        self.roles = roles or _valid_roles()
        self.privileges = privileges or _valid_privileges()
        self.executed = []

    def execute(self, statement, parameters):
        sql = str(statement)
        self.executed.append((sql, dict(parameters)))
        if "runtime_privilege_contract:roles" in sql:
            return _FakeResult(self.roles)
        kind = next(
            item
            for item in ("schema", "table", "function")
            if f"runtime_privilege_contract:{item}" in sql
        )
        identity = parameters.get("identity_arguments")
        suffix = f"({identity})" if kind == "function" else ""
        object_id = (
            f"{kind}:{parameters['schema_name']}."
            f"{parameters.get('object_name') or parameters['schema_name']}{suffix}"
        )
        return _FakeResult(self.privileges[object_id])


def _valid_roles():
    return {
        "observer_is_runtime_role": True,
        "runtime_role_exists": True,
        "gateway_role_exists": True,
        "runtime_is_gateway_member": True,
        "gateway_can_login": False,
        "gateway_is_superuser": False,
        "gateway_can_create_db": False,
        "gateway_can_create_role": False,
        "gateway_inherits": False,
        "gateway_bypasses_rls": False,
    }


def _valid_privileges():
    return {
        requirement.object_id: {
            "object_exists": True,
            "role_privileges": list(requirement.expected_privileges),
            "public_privileges": [],
        }
        for requirement in contract.PRIVILEGE_REQUIREMENTS
    }


def _inspect(connection):
    return contract.inspect_runtime_privilege_contract(
        connection,
        profile="staging",
        runtime_role="agent_user",
        generated_at=datetime(2026, 8, 19, 1, 2, 3, tzinfo=UTC),
    )


def test_exact_contract_is_admitted_and_redacted():
    report = _inspect(_FakeConnection())

    assert report["status"] == "in_sync"
    assert report["admission_allowed"] is True
    assert report["read_only"] is True
    assert report["self_healed"] is False
    assert report["drift"] == []
    assert len(report["contract_fingerprint"]) == 64
    assert len(report["evidence_fingerprint"]) == 64
    rendered = json.dumps(report)
    assert "password" not in rendered.lower()
    assert "database_url" not in rendered.lower()


def test_evidence_fingerprint_excludes_observation_time():
    first = contract.inspect_runtime_privilege_contract(
        _FakeConnection(),
        profile="staging",
        generated_at=datetime(2026, 8, 19, 1, tzinfo=UTC),
    )
    second = contract.inspect_runtime_privilege_contract(
        _FakeConnection(),
        profile="staging",
        generated_at=datetime(2026, 8, 19, 2, tzinfo=UTC),
    )

    assert first["generated_at"] != second["generated_at"]
    assert first["evidence_fingerprint"] == second["evidence_fingerprint"]


def test_missing_data_product_grants_block_admission():
    privileges = _valid_privileges()
    privileges["table:gda_control.data_product"] = {
        "object_exists": True,
        "role_privileges": [],
        "public_privileges": [],
    }

    report = _inspect(_FakeConnection(privileges=privileges))
    product = next(
        item
        for item in report["observations"]
        if item["object_id"] == "table:gda_control.data_product"
    )

    assert report["status"] == "blocked"
    assert report["admission_allowed"] is False
    assert product["missing_privileges"] == ["INSERT", "SELECT", "UPDATE"]
    assert product["violations"] == ["missing_privilege"]


def test_excess_and_public_privileges_are_not_treated_as_healthy():
    privileges = _valid_privileges()
    privileges["table:gda_control.data_incident_event"] = {
        "object_exists": True,
        "role_privileges": ["SELECT", "UPDATE"],
        "public_privileges": ["SELECT"],
    }

    report = _inspect(_FakeConnection(privileges=privileges))
    event = next(
        item
        for item in report["observations"]
        if item["object_id"] == "table:gda_control.data_incident_event"
    )

    assert event["unexpected_privileges"] == ["UPDATE"]
    assert event["public_privileges"] == ["SELECT"]
    assert event["violations"] == ["excess_privilege", "public_exposure"]
    assert report["admission_allowed"] is False


def test_role_membership_and_gateway_attributes_fail_closed():
    roles = _valid_roles()
    roles["runtime_is_gateway_member"] = False
    roles["gateway_bypasses_rls"] = True

    report = _inspect(_FakeConnection(roles=roles))

    assert report["role_observation"]["violations"] == [
        "missing_gateway_membership",
        "gateway_role_attribute_drift",
    ]
    assert report["status"] == "blocked"


def test_missing_function_and_schema_are_reported_separately():
    privileges = _valid_privileges()
    privileges["schema:gda_control.gda_control"]["object_exists"] = False
    function_id = (
        "function:gda_control.transition_data_incident"
        "(text, uuid, integer, text, text, text, jsonb)"
    )
    privileges[function_id] = {
        "object_exists": False,
        "role_privileges": [],
        "public_privileges": [],
    }

    report = _inspect(_FakeConnection(privileges=privileges))
    drift = {item["object_id"]: item["violations"] for item in report["drift"]}

    assert drift["schema:gda_control.gda_control"] == ["missing_object"]
    assert drift[function_id] == ["missing_object", "missing_privilege"]
