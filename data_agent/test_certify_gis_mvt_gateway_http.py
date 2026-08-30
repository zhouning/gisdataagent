import json

from scripts import certify_gis_mvt_gateway_http as certification


def test_gateway_http_certificate_wires_callback_and_wraps_fixture_evidence(
    monkeypatch, tmp_path
):
    reset_calls = []
    callback_calls = []
    fixture_calls = []
    proof = {
        "schema": "gda.gis_mvt_gateway_http_certification.v3",
        "status": "passed",
        "transport": "fastapi_http_contract",
    }

    def fake_callback(gateway, release, martin_origin):
        callback_calls.append((gateway, release, martin_origin))
        return proof

    def fake_active_release(database_url, **kwargs):
        fixture_calls.append((database_url, kwargs))
        callback = kwargs["after_activation"]
        assert callback is fake_callback
        assert callback("gateway", {"release": "v1.0.0"}, "http://martin") == proof
        return {
            "fixture": {
                "ephemeral": True,
                "cleanup": "completed",
                "martin_image": "fixture-martin",
            },
            "post_activation": proof,
        }

    monkeypatch.setattr(certification, "reset_engine", lambda: reset_calls.append(True))
    monkeypatch.setattr(certification, "_certify_active_gateway_http", fake_callback)
    monkeypatch.setattr(certification, "certify_active_release", fake_active_release)

    report_path = tmp_path / "gateway-http-report.json"
    report = certification.certify(
        "postgresql://fixture",
        docker_network="fixture-network",
        docker_database_host="fixture-db",
        docker_database_port=6543,
        martin_image="fixture-martin",
        report_path=report_path,
    )

    assert reset_calls == [True, True]
    assert callback_calls == [("gateway", {"release": "v1.0.0"}, "http://martin")]
    assert fixture_calls == [
        (
            "postgresql://fixture",
            {
                "docker_network": "fixture-network",
                "docker_database_host": "fixture-db",
                "docker_database_port": 6543,
                "martin_image": "fixture-martin",
                "after_activation": fake_callback,
            },
        )
    ]
    assert report == {
        "schema": "gda.gis_mvt_gateway_http_certification.v3",
        "status": "passed",
        "fixture": {
            "ephemeral": True,
            "cleanup": "completed",
            "martin_image": "fixture-martin",
        },
        "gateway_http": proof,
    }
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
