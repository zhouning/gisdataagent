from __future__ import annotations

import json

from scripts.certify_agentops_networkpolicy_enforcement import (
    _run_disposable_probe,
    detect_cni,
)


def test_detect_cni_marks_kindnet_as_non_enforcing() -> None:
    resources = [
        {
            "items": [
                {
                    "metadata": {"name": "kindnet-abc", "namespace": "kube-system"},
                    "spec": {"containers": [{"image": "kindest/kindnetd:v20240726"}]},
                }
            ]
        }
    ]

    result = detect_cni(resources)

    assert result == {
        "name": "kindnet",
        "recognized": True,
        "enforcement_expected": False,
        "reason": "kindnet does not enforce Kubernetes NetworkPolicy",
    }


def test_detect_cni_accepts_known_enforcing_cni() -> None:
    result = detect_cni(
        [
            {
                "items": [
                    {
                        "metadata": {"name": "cilium-agent", "namespace": "kube-system"},
                        "spec": {"containers": [{"image": "quay.io/cilium/cilium:v1.16.0"}]},
                    }
                ]
            }
        ]
    )

    assert result["name"] == "cilium"
    assert result["recognized"] is True
    assert result["enforcement_expected"] is True


def test_disposable_probe_records_allow_and_deny_and_cleans_namespace() -> None:
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def fake_kubectl(*args: str, input_payload: str | None = None, timeout: float = 30):
        del timeout
        calls.append((args, input_payload))
        if args and args[0] == "exec":
            return (args[3] == "allowed", "ok")
        return True, "ok"

    checks = _run_disposable_probe(
        kubectl=fake_kubectl,
        namespace="gda-agentops-netpol-cert-test",
    )

    assert checks == {
        "allowed_ingress_reaches_server": True,
        "denied_ingress_is_blocked": True,
    }
    assert calls[0][0][:3] == ("create", "namespace", "gda-agentops-netpol-cert-test")
    applied = next(payload for args, payload in calls if args[:3] == ("apply", "-f", "-"))
    assert applied is not None
    assert len(json.loads(applied)["items"]) == 5
    assert calls[-1][0][:2] == ("delete", "namespace")
